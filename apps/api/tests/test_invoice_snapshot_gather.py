"""
Tests for the gathering adapter — the one piece of scoring that touches the
database.

This is the *only* database-backed surface scoring keeps (see issue #15). Two
things are worth proving against real Postgres and nowhere else:

1. The keys are derived from the invoice correctly — the batch asks for the
   Purchased Items on the invoice, and only those.
2. The batched Baseline fetch returns what the old per-line lookups returned,
   so the rules resolve the same Baseline they resolve today.

Everything else about scoring is arithmetic over a snapshot and belongs in a
test that needs no connection.

These use a real ``psycopg.AsyncConnection`` rather than the sync-to-async
bridge the older scoring tests carry: the adapter is async, so there is nothing
to bridge. Nothing is committed; each test rolls its own connection back.
"""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest

from apps.api.models.invoice_snapshot import InvoiceSnapshot
from apps.api.repos.invoice_stats import (
    get_vendor_unit_price_stats,
    get_vendor_unit_price_stats_for_skus,
)
from apps.api.services.anomaly_scoring import select_price_baseline
from apps.api.services.scoring_gather import gather_invoice_snapshot


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)

MIN_SAMPLES = 5  # what the view needs before a baseline is worth comparing against


async def _baseline_the_old_query_resolved(db, *, org_id, vendor_id, sku, desc=None):
    """What the deleted per-line lookup resolved to, as a reference implementation.

    It is gone from ``repos/invoice_stats.py`` — the rule reads Baselines from
    the snapshot now, so nothing in the app called it any more. It survives here
    only as the *other* side of an equivalence check, which is why re-stating it
    is not duplication: an equivalence proved against itself proves nothing.

    It rests on one property of ``get_vendor_unit_price_stats`` — that the view
    read comes back best-sampled first — so that property is asserted directly
    by ``test_the_view_read_returns_the_best_sampled_row_first`` below rather
    than left to drift.
    """
    rows = await get_vendor_unit_price_stats(
        db, org_id=org_id, vendor_id=vendor_id, sku=sku, desc=desc
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db():
    """Function-scoped async connection, rolled back so tests leave no trace."""
    conn = await psycopg.AsyncConnection.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        await conn.rollback()
        await conn.close()


@pytest.fixture
async def org_id(db):
    oid = str(uuid.uuid4())
    async with db.cursor() as cur:
        await cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (oid, f"gather-{oid[:8]}"))
        await cur.execute("SELECT set_config('app.org_id', %s, true)", (oid,))
    return oid


@pytest.fixture
async def vendor_id(db, org_id):
    return await _mk_vendor(db, org_id)


# ---------------------------------------------------------------------------
# Insert helpers (no commit)
# ---------------------------------------------------------------------------

async def _mk_vendor(db, org_id, name=None):
    vid = str(uuid.uuid4())
    async with db.cursor() as cur:
        await cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vid, org_id, name or f"Vendor-{vid[:8]}"),
        )
    return vid


async def _mk_invoice(db, org_id, vendor_id, *, total=Decimal("100.00"), days_ago=1):
    inv_id = str(uuid.uuid4())
    invoice_date = (date.today() - timedelta(days=days_ago)).isoformat()
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, due_date, currency,
               subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'USD', %s, 0, %s, 'received')
            """,
            (
                inv_id,
                org_id,
                vendor_id,
                f"INV-{uuid.uuid4().hex[:8]}",
                invoice_date,
                invoice_date,
                total,
                total,
            ),
        )
    return inv_id


async def _mk_line(db, invoice_id, sku, desc, unit_price, qty=1):
    line_id = str(uuid.uuid4())
    async with db.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, invoice_id, sku, desc, qty, unit_price, Decimal(str(unit_price)) * qty),
        )
    return line_id


async def _seed_price_history(db, org_id, vendor_id, sku, desc, price, n=MIN_SAMPLES):
    """`n` past invoices, each one line at `price` for (vendor, sku, desc)."""
    for i in range(n):
        inv = await _mk_invoice(db, org_id, vendor_id, total=Decimal(str(price)), days_ago=200 + i)
        await _mk_line(db, inv, sku, desc, Decimal(str(price)))


# ===========================================================================
# The snapshot the adapter builds
# ===========================================================================

@pytest.mark.anyio
async def test_snapshot_carries_the_invoice_header_and_every_line(db, org_id, vendor_id):
    inv = await _mk_invoice(db, org_id, vendor_id, total=Decimal("250.00"))
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("100"))
    await _mk_line(db, inv, "GADGET", "Gadget", Decimal("150"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    assert isinstance(snapshot, InvoiceSnapshot)
    assert snapshot.org_id == str(org_id)
    assert str(snapshot.invoice["id"]) == inv
    assert str(snapshot.invoice["vendor_id"]) == vendor_id
    assert snapshot.invoice["total"] == Decimal("250.00")
    assert {line["sku"] for line in snapshot.lines} == {"WIDGET", "GADGET"}


@pytest.mark.anyio
async def test_missing_invoice_gathers_nothing(db, org_id):
    assert await gather_invoice_snapshot(db, org_id=org_id, invoice_id=str(uuid.uuid4())) is None


@pytest.mark.anyio
async def test_an_invoice_with_no_lines_is_a_snapshot_with_no_lines(db, org_id, vendor_id):
    """Representable, not an error. Whether it produces alerts is a rule's call."""
    inv = await _mk_invoice(db, org_id, vendor_id)

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    assert snapshot is not None
    assert snapshot.lines == []
    assert snapshot.price_baselines == {}


# ===========================================================================
# Baselines: batched, keyed by the invoice's Purchased Items
# ===========================================================================

@pytest.mark.anyio
async def test_baselines_cover_the_purchased_items_on_the_invoice(db, org_id, vendor_id):
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40)
    await _seed_price_history(db, org_id, vendor_id, "GADGET", "Gadget", 60)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("200"))
    await _mk_line(db, inv, "GADGET", "Gadget", Decimal("300"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    assert set(snapshot.price_baselines) == {"WIDGET", "GADGET"}
    assert snapshot.price_baselines["WIDGET"][0]["median_unit_price"] == Decimal("40")


@pytest.mark.anyio
async def test_baselines_are_not_fetched_for_the_vendors_other_purchased_items(
    db, org_id, vendor_id
):
    """Snapshot size follows the invoice, not the vendor's history."""
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40)
    await _seed_price_history(db, org_id, vendor_id, "ELSEWHERE", "Elsewhere", 90)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("200"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    assert set(snapshot.price_baselines) == {"WIDGET"}


@pytest.mark.anyio
async def test_baselines_are_not_fetched_from_another_vendor(db, org_id, vendor_id):
    other_vendor = await _mk_vendor(db, org_id)
    await _seed_price_history(db, org_id, other_vendor, "WIDGET", "Widget", 500)
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("200"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    medians = [row["median_unit_price"] for row in snapshot.price_baselines["WIDGET"]]
    assert medians == [Decimal("40")]


@pytest.mark.anyio
async def test_lines_without_a_sku_contribute_no_key(db, org_id, vendor_id):
    """A line with no SKU has no identifiable Purchased Item (ADR-0001)."""
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("200"))
    await _mk_line(db, inv, None, "Delivery surcharge", Decimal("25"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    assert set(snapshot.price_baselines) == {"WIDGET"}


@pytest.mark.anyio
async def test_the_batch_is_one_round_trip_whatever_the_line_count(db, org_id, vendor_id):
    """The per-line lookup this replaces issued one query per line."""
    for i in range(4):
        await _seed_price_history(db, org_id, vendor_id, f"SKU-{i}", f"Item {i}", 10 + i)
    inv = await _mk_invoice(db, org_id, vendor_id)
    for i in range(4):
        await _mk_line(db, inv, f"SKU-{i}", f"Item {i}", Decimal("100"))

    counting = _CountingConnection(db)
    snapshot = await gather_invoice_snapshot(counting, org_id=org_id, invoice_id=inv)

    assert len(snapshot.price_baselines) == 4
    baseline_queries = [q for q in counting.queries if "vendor_unit_price_stats" in q]
    assert len(baseline_queries) == 1


@pytest.mark.anyio
async def test_no_query_is_issued_when_the_invoice_has_no_skus(db, org_id, vendor_id):
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, None, "Delivery surcharge", Decimal("25"))

    counting = _CountingConnection(db)
    snapshot = await gather_invoice_snapshot(counting, org_id=org_id, invoice_id=inv)

    assert snapshot.price_baselines == {}
    assert not [q for q in counting.queries if "vendor_unit_price_stats" in q]


# ===========================================================================
# The adapter narrows nothing; the rule does the narrowing
# ===========================================================================

@pytest.mark.anyio
async def test_every_description_variant_survives_into_the_snapshot(db, org_id, vendor_id):
    """The view still groups by description, so one SKU can yield several rows.
    The adapter hands back all of them — picking one is a rule's job."""
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40, n=6)
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "WIDGET, blue", 90, n=5)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", "Widget", Decimal("200"))

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)

    rows = snapshot.price_baselines["WIDGET"]
    assert {row["desc"] for row in rows} == {"Widget", "WIDGET, blue"}


@pytest.mark.anyio
async def test_the_view_read_returns_the_best_sampled_row_first(db, org_id, vendor_id):
    """The property the reference implementation above leans on.

    ``_baseline_the_old_query_resolved`` takes ``rows[0]``, and
    ``select_price_baseline`` takes ``candidates[0]``. Both are only "the
    best-sampled row" because ``get_vendor_unit_price_stats`` orders by
    ``sample_size`` descending. Drop that ORDER BY and every equivalence test
    below would keep passing by coincidence, so assert it on its own.
    """
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40, n=5)
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "WIDGET, blue", 90, n=8)

    rows = await get_vendor_unit_price_stats(db, org_id=org_id, vendor_id=vendor_id, sku="WIDGET")

    sample_sizes = [row["sample_size"] for row in rows]
    assert sample_sizes == sorted(sample_sizes, reverse=True)
    assert rows[0]["desc"] == "WIDGET, blue"


@pytest.mark.anyio
@pytest.mark.parametrize("line_desc", ["Widget", "WIDGET, blue", None, "unseen description"])
async def test_batch_plus_selection_resolves_what_the_per_line_lookup_resolved(
    db, org_id, vendor_id, line_desc
):
    """The behaviour-preservation check this ticket exists to make.

    Whatever the per-line lookup returned for a line, the batched
    fetch plus ``select_price_baseline`` must return the same row.
    """
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Widget", 40, n=6)
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "WIDGET, blue", 90, n=5)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", line_desc, Decimal("200"))

    per_line = await _baseline_the_old_query_resolved(
        db, org_id=org_id, vendor_id=vendor_id, sku="WIDGET", desc=line_desc
    )

    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)
    batched = select_price_baseline(snapshot.price_baselines.get("WIDGET", []), desc=line_desc)

    assert batched == per_line


@pytest.mark.anyio
async def test_a_tie_on_sample_size_resolves_the_same_way_in_both(db, org_id, vendor_id):
    """The edge the equivalence turns on.

    Two descriptions under one SKU, equally well sampled, and a line with no
    description to narrow by — so "the best-sampled row" is a tie. Without a
    tiebreaker each query could break it differently and the line would compare
    against a different median, so this is where a batched fetch could silently
    change which alert fires.
    """
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Alpha", 40, n=5)
    await _seed_price_history(db, org_id, vendor_id, "WIDGET", "Beta", 90, n=5)
    inv = await _mk_invoice(db, org_id, vendor_id)
    await _mk_line(db, inv, "WIDGET", None, Decimal("200"))

    per_line = await _baseline_the_old_query_resolved(
        db, org_id=org_id, vendor_id=vendor_id, sku="WIDGET", desc=None
    )
    snapshot = await gather_invoice_snapshot(db, org_id=org_id, invoice_id=inv)
    batched = select_price_baseline(snapshot.price_baselines["WIDGET"], desc=None)

    assert per_line["sample_size"] == 5
    assert batched == per_line
    # And the tie breaks the same way every time, not just consistently within one run.
    assert batched["desc"] == "Alpha"


@pytest.mark.anyio
async def test_batched_repo_returns_the_union_of_the_per_sku_lookups(db, org_id, vendor_id):
    """The repo query itself: one call, same rows as calling it per SKU."""
    for sku, desc, price in [("A", "Alpha", 10), ("B", "Beta", 20), ("C", "Gamma", 30)]:
        await _seed_price_history(db, org_id, vendor_id, sku, desc, price)

    batched = await get_vendor_unit_price_stats_for_skus(
        db, org_id=org_id, vendor_id=vendor_id, skus=["A", "B"]
    )

    assert {row["sku"] for row in batched} == {"A", "B"}
    for row in batched:
        one = await _baseline_the_old_query_resolved(
            db, org_id=org_id, vendor_id=vendor_id, sku=row["sku"], desc=row["desc"]
        )
        assert one == row


@pytest.mark.anyio
async def test_batched_repo_with_no_skus_returns_nothing(db, org_id, vendor_id):
    assert await get_vendor_unit_price_stats_for_skus(
        db, org_id=org_id, vendor_id=vendor_id, skus=[]
    ) == []


# ---------------------------------------------------------------------------
# A connection that records the SQL it is asked to run.
# ---------------------------------------------------------------------------

class _CountingConnection:
    """Wraps an async connection and records every query text executed."""

    def __init__(self, conn):
        self._conn = conn
        self.queries = []

    def cursor(self, *args, **kwargs):
        return _CountingCursor(self._conn.cursor(*args, **kwargs), self.queries)


class _CountingCursor:
    def __init__(self, cur, queries):
        self._cur = cur
        self._queries = queries

    async def __aenter__(self):
        self._cur = await self._cur.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self._cur.__aexit__(*args)

    async def execute(self, query, params=None):
        self._queries.append(query)
        return await self._cur.execute(query, params)

    def __getattr__(self, name):
        return getattr(self._cur, name)
