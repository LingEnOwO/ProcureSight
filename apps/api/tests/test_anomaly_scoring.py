"""
Characterization tests for the anomaly-scoring rules.

These lock down the *current* behavior of the four scoring rules that had no
direct coverage before (unit_price_delta, vendor_volume_spike,
duplicate_invoice, contract_policy_violation) plus the score_invoice
orchestrator. excessive_consulting is already covered in
test_excessive_consulting.py.

They must stay green through the planned scoring refactor (splitting
anomaly_scoring.py into a package) — any change in alert count, severity, or
meta shape should be a deliberate, reviewed decision, not an accident.

Design notes
------------
* Tests run against a real Postgres (the analytics *views* do the baseline math,
  so they cannot be meaningfully mocked). The scorer is async but the repos
  accept any object exposing an async ``cursor()``; we bridge a sync psycopg
  connection with _AsyncConnWrapper (same trick as test_excessive_consulting).
* We deliberately do NOT commit: the scorer uses the same wrapped connection, so
  it sees this transaction's uncommitted rows, and the module-scoped rollback
  leaves the database clean afterward.
* Each test uses its own vendor so the per-vendor analytics views
  (vendor_unit_price_stats, vendor_spend_stats) and the one-contract-per-vendor
  constraint don't bleed across tests.
"""
import os
import uuid
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import pytest

from apps.api.services import anomaly_scoring
from apps.api.services.anomaly_scoring import (
    score_invoice,
    _score_unit_price_deltas_for_invoice,
    _score_vendor_volume_spikes_for_invoice,
    _score_duplicate_invoices_for_invoice,
    _score_contract_policy_violations_for_invoice,
)


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn():
    """Module-scoped connection; rolled back at end so tests leave no trace.

    Intentionally no commits anywhere in this module — see module docstring.
    """
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def org_id(db_conn):
    oid = str(uuid.uuid4())
    with db_conn.cursor() as cur:
        cur.execute("INSERT INTO orgs (id, name) VALUES (%s, %s)", (oid, f"sc-test-{oid[:8]}"))
        cur.execute("SELECT set_config('app.org_id', %s, true)", (oid,))
    return oid


# ---------------------------------------------------------------------------
# Insert helpers (no commit)
# ---------------------------------------------------------------------------

def _mk_vendor(conn, org_id, name=None):
    vid = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vid, org_id, name or f"Vendor-{vid[:8]}"),
        )
    return vid


def _make_invoice(conn, org_id, vendor_id, invoice_no, total, invoice_date, due_date=None):
    inv_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, due_date, currency,
               subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'USD', %s, 0, %s, 'received')
            """,
            (inv_id, org_id, vendor_id, invoice_no, invoice_date, due_date, total, total),
        )
    return inv_id


def _make_line(conn, invoice_id, sku, desc, unit_price, qty=1):
    line_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, invoice_id, sku, desc, qty, unit_price, float(unit_price) * qty),
        )
    return line_id


def _make_contract(conn, org_id, vendor_id, *, spending_limit=None,
                   approved_categories=None, payment_terms_days=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO vendor_contracts
              (org_id, vendor_id, spending_limit, approved_categories, payment_terms_days)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (org_id, vendor_id, spending_limit, approved_categories, payment_terms_days),
        )


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def _days_ahead(n):
    return (date.today() + timedelta(days=n)).isoformat()


def _uno(prefix):
    """Unique invoice number."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Async bridge: lets the async scorer/repos run against a sync connection.
# ---------------------------------------------------------------------------

class _AsyncCursor:
    def __init__(self, conn, row_factory=None):
        self._conn = conn
        self._row_factory = row_factory
        self._cur = None

    async def __aenter__(self):
        kwargs = {"row_factory": self._row_factory} if self._row_factory else {}
        self._cur = self._conn.cursor(**kwargs)
        return self

    async def __aexit__(self, *args):
        self._cur.close()

    async def execute(self, query, params=None):
        self._cur.execute(query, params)

    async def fetchall(self):
        return self._cur.fetchall()

    async def fetchone(self):
        return self._cur.fetchone()

    @property
    def description(self):
        return self._cur.description


class _AsyncConnWrapper:
    def __init__(self, conn):
        self._conn = conn

    def cursor(self, row_factory=None):
        return _AsyncCursor(self._conn, row_factory=row_factory)


@pytest.fixture
def adb(db_conn):
    return _AsyncConnWrapper(db_conn)


# Helper to build a price-baseline group: `n` historical invoices each with one
# line at `hist_price` for (vendor, sku, desc), all dated in the past so they do
# not pollute the recent-window spend stats used by the volume rule.
def _seed_price_history(db_conn, org_id, vendor_id, sku, desc, hist_price, n=5):
    for i in range(n):
        inv = _make_invoice(
            db_conn, org_id, vendor_id, _uno("HIST"), Decimal("1.00"),
            invoice_date=f"2024-0{(i % 9) + 1}-10",
        )
        _make_line(db_conn, inv, sku, desc, Decimal(str(hist_price)))


# ===========================================================================
# unit_price_delta
# ===========================================================================

@pytest.mark.anyio
async def test_unit_price_high_severity(db_conn, adb, org_id):
    """3x+ over the historical median → high."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_price_history(db_conn, org_id, vendor, "WIDGET", "Widget", 40, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("CUR"), Decimal("1.00"), _days_ago(1))
    _make_line(db_conn, cur_inv, "WIDGET", "Widget", Decimal("200"))  # 200/40 = 5x

    out = await _score_unit_price_deltas_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)

    assert len(out) == 1
    c = out[0]
    assert c.type == "unit_price_delta"
    assert c.severity == "high"
    assert c.meta["ratio"] == pytest.approx(5.0)
    assert c.meta["median_unit_price"] == pytest.approx(40.0)
    assert c.meta["unit_price"] == pytest.approx(200.0)
    assert c.meta["sample_size"] == 6  # 5 historical + current line


@pytest.mark.anyio
async def test_unit_price_medium_severity(db_conn, adb, org_id):
    """2x–3x median → medium."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_price_history(db_conn, org_id, vendor, "GADGET", "Gadget", 40, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("CUR"), Decimal("1.00"), _days_ago(1))
    _make_line(db_conn, cur_inv, "GADGET", "Gadget", Decimal("100"))  # 2.5x

    out = await _score_unit_price_deltas_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert len(out) == 1
    assert out[0].severity == "medium"
    assert out[0].meta["ratio"] == pytest.approx(2.5)


@pytest.mark.anyio
async def test_unit_price_low_severity(db_conn, adb, org_id):
    """1.5x–2x median → low."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_price_history(db_conn, org_id, vendor, "BOLT", "Bolt", 40, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("CUR"), Decimal("1.00"), _days_ago(1))
    _make_line(db_conn, cur_inv, "BOLT", "Bolt", Decimal("70"))  # 1.75x

    out = await _score_unit_price_deltas_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert len(out) == 1
    assert out[0].severity == "low"


@pytest.mark.anyio
async def test_unit_price_no_alert_below_threshold(db_conn, adb, org_id):
    """Below 1.5x median → no alert."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_price_history(db_conn, org_id, vendor, "NUT", "Nut", 40, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("CUR"), Decimal("1.00"), _days_ago(1))
    _make_line(db_conn, cur_inv, "NUT", "Nut", Decimal("50"))  # 1.25x

    out = await _score_unit_price_deltas_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert out == []


@pytest.mark.anyio
async def test_unit_price_no_alert_insufficient_samples(db_conn, adb, org_id):
    """Fewer than MIN_SAMPLE_SIZE_FOR_BASELINE lines in the group → no baseline → no alert."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_price_history(db_conn, org_id, vendor, "RARE", "Rare", 40, n=3)  # +current = 4 < 5
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("CUR"), Decimal("1.00"), _days_ago(1))
    _make_line(db_conn, cur_inv, "RARE", "Rare", Decimal("400"))  # huge ratio, but too few samples

    out = await _score_unit_price_deltas_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert out == []


# ===========================================================================
# vendor_volume_spike
# ===========================================================================

def _seed_recent_invoices(db_conn, org_id, vendor_id, total, n):
    """n recent (within 30d) historical invoices at `total`, no lines needed
    (the spend-stats view aggregates invoices.total without joining lines)."""
    for i in range(n):
        _make_invoice(
            db_conn, org_id, vendor_id, _uno("VHIST"), Decimal(str(total)),
            invoice_date=_days_ago(i + 2),
        )


@pytest.mark.anyio
async def test_volume_spike_high_severity(db_conn, adb, org_id):
    """3x+ the vendor's recent median invoice total → high."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_recent_invoices(db_conn, org_id, vendor, 1000, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("VCUR"), Decimal("8000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("8000"))  # current invoice needs a line

    out = await _score_vendor_volume_spikes_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert len(out) == 1
    c = out[0]
    assert c.type == "vendor_volume_spike"
    assert c.severity == "high"
    assert c.meta["baseline_median_total"] == pytest.approx(1000.0)
    assert c.meta["ratio"] == pytest.approx(8.0)
    assert c.meta["baseline_window"] == "90d"


@pytest.mark.anyio
async def test_volume_spike_medium_severity(db_conn, adb, org_id):
    """2x–3x recent median → medium."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_recent_invoices(db_conn, org_id, vendor, 1000, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("VCUR"), Decimal("2500"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("2500"))

    out = await _score_vendor_volume_spikes_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert len(out) == 1
    assert out[0].severity == "medium"
    assert out[0].meta["ratio"] == pytest.approx(2.5)


@pytest.mark.anyio
async def test_volume_spike_no_alert_below_threshold(db_conn, adb, org_id):
    """Below 2x recent median → no alert."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_recent_invoices(db_conn, org_id, vendor, 1000, n=5)
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("VCUR"), Decimal("1500"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("1500"))

    out = await _score_vendor_volume_spikes_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert out == []


@pytest.mark.anyio
async def test_volume_spike_no_alert_insufficient_history(db_conn, adb, org_id):
    """Fewer than MIN_INVOICES_FOR_SPEND_BASELINE invoices in window → no baseline → no alert."""
    vendor = _mk_vendor(db_conn, org_id)
    _seed_recent_invoices(db_conn, org_id, vendor, 1000, n=3)  # +current = 4 < 5
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("VCUR"), Decimal("8000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("8000"))

    out = await _score_vendor_volume_spikes_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert out == []


# ===========================================================================
# duplicate_invoice
#
# NOTE: invoices has UNIQUE(org_id, vendor_id, invoice_no), and the rule's
# finder only matches on EXACT invoice_no for the same vendor. So two real rows
# can never satisfy the match — the rule is effectively unreachable through
# normal ingestion (the worker's pre-insert dedup is the real defense). We
# characterize both that reality and the severity branch (via a targeted patch).
# ===========================================================================

@pytest.mark.anyio
async def test_duplicate_no_alert_for_same_total_different_number(db_conn, adb, org_id):
    """Same vendor + same total but different invoice_no is NOT flagged by this rule."""
    vendor = _mk_vendor(db_conn, org_id)
    other = _make_invoice(db_conn, org_id, vendor, _uno("DUP-OTHER"), Decimal("3000"), _days_ago(5))
    _make_line(db_conn, other, "X", "X", Decimal("3000"))
    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("DUP-CUR"), Decimal("3000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("3000"))

    out = await _score_duplicate_invoices_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)
    assert out == []


@pytest.mark.anyio
async def test_duplicate_critical_when_number_and_total_match(db_conn, adb, org_id, monkeypatch):
    """A duplicate matching both invoice_no AND total → critical."""
    vendor = _mk_vendor(db_conn, org_id)
    cur_inv = _make_invoice(db_conn, org_id, vendor, "INV-DUP-A", Decimal("3000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("3000"))

    async def fake_finder(db, *, org_id, vendor_id, invoice_id, invoice_no):
        return [{
            "id": str(uuid.uuid4()),
            "vendor_id": vendor_id,
            "invoice_no": invoice_no,          # matches
            "total": Decimal("3000"),          # matches
            "invoice_date": date(2026, 1, 1),
        }]

    monkeypatch.setattr(anomaly_scoring, "_find_potential_duplicate_invoices", fake_finder)
    out = await _score_duplicate_invoices_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)

    assert len(out) == 1
    c = out[0]
    assert c.type == "duplicate_invoice"
    assert c.severity == "critical"
    assert len(c.meta["duplicates"]) == 1
    assert c.meta["duplicates"][0]["match_on"] == {"invoice_no": True, "total": True}


@pytest.mark.anyio
async def test_duplicate_medium_when_only_number_matches(db_conn, adb, org_id, monkeypatch):
    """A duplicate matching invoice_no but NOT total → medium."""
    vendor = _mk_vendor(db_conn, org_id)
    cur_inv = _make_invoice(db_conn, org_id, vendor, "INV-DUP-B", Decimal("3000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "X", "X", Decimal("3000"))

    async def fake_finder(db, *, org_id, vendor_id, invoice_id, invoice_no):
        return [{
            "id": str(uuid.uuid4()),
            "vendor_id": vendor_id,
            "invoice_no": invoice_no,          # matches
            "total": Decimal("9999"),          # differs
            "invoice_date": date(2026, 1, 1),
        }]

    monkeypatch.setattr(anomaly_scoring, "_find_potential_duplicate_invoices", fake_finder)
    out = await _score_duplicate_invoices_for_invoice(adb, org_id=org_id, invoice_id=cur_inv)

    assert len(out) == 1
    assert out[0].severity == "medium"
    assert out[0].meta["duplicates"][0]["match_on"] == {"invoice_no": True, "total": False}


# ===========================================================================
# contract_policy_violation
# ===========================================================================

@pytest.mark.anyio
async def test_contract_no_alert_without_contract(db_conn, adb, org_id):
    vendor = _mk_vendor(db_conn, org_id)
    inv = _make_invoice(db_conn, org_id, vendor, _uno("NC"), Decimal("99999"), _days_ago(1))
    _make_line(db_conn, inv, "X", "Anything", Decimal("99999"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert out == []


@pytest.mark.anyio
async def test_contract_spending_limit_exceeded(db_conn, adb, org_id):
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(db_conn, org_id, vendor, spending_limit=Decimal("1000"))
    inv = _make_invoice(db_conn, org_id, vendor, _uno("SL"), Decimal("5000"), _days_ago(1))
    _make_line(db_conn, inv, "X", "Widget", Decimal("5000"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert len(out) == 1
    c = out[0]
    assert c.type == "contract_policy_violation"
    assert c.severity == "high"
    assert c.meta["rule"] == "spending_limit_exceeded"
    assert c.meta["spending_limit"] == pytest.approx(1000.0)
    assert c.meta["invoice_total"] == pytest.approx(5000.0)


@pytest.mark.anyio
async def test_contract_unapproved_category(db_conn, adb, org_id):
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(db_conn, org_id, vendor, approved_categories=["office supplies"])
    inv = _make_invoice(db_conn, org_id, vendor, _uno("UC"), Decimal("500"), _days_ago(1))
    _make_line(db_conn, inv, "CONS", "Premium Consulting", Decimal("500"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert len(out) == 1
    assert out[0].meta["rule"] == "unapproved_category"
    assert out[0].severity == "high"


@pytest.mark.anyio
async def test_contract_approved_category_no_alert(db_conn, adb, org_id):
    """A line whose text contains an approved category substring is allowed."""
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(db_conn, org_id, vendor, approved_categories=["office supplies"])
    inv = _make_invoice(db_conn, org_id, vendor, _uno("AC"), Decimal("500"), _days_ago(1))
    _make_line(db_conn, inv, "PAPER", "Office Supplies - Copy Paper", Decimal("500"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert out == []


@pytest.mark.anyio
async def test_contract_payment_terms_violation(db_conn, adb, org_id):
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(db_conn, org_id, vendor, payment_terms_days=30)
    inv = _make_invoice(
        db_conn, org_id, vendor, _uno("PT"), Decimal("500"),
        invoice_date=_days_ago(1), due_date=_days_ahead(45),  # ~46 day terms
    )
    _make_line(db_conn, inv, "X", "Widget", Decimal("500"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert len(out) == 1
    c = out[0]
    assert c.severity == "medium"
    assert c.meta["rule"] == "payment_terms_violation"
    assert c.meta["contracted_days"] == 30
    assert c.meta["actual_days"] > 30


@pytest.mark.anyio
async def test_contract_clean_invoice_no_alerts(db_conn, adb, org_id):
    """Within spending limit, approved category, and payment terms → no alerts."""
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(
        db_conn, org_id, vendor,
        spending_limit=Decimal("10000"), approved_categories=["widget"], payment_terms_days=60,
    )
    inv = _make_invoice(
        db_conn, org_id, vendor, _uno("OK"), Decimal("500"),
        invoice_date=_days_ago(1), due_date=_days_ahead(30),
    )
    _make_line(db_conn, inv, "WID", "Widget Assembly", Decimal("500"))

    out = await _score_contract_policy_violations_for_invoice(adb, org_id=org_id, invoice_id=inv)
    assert out == []


# ===========================================================================
# score_invoice orchestrator
# ===========================================================================

@pytest.mark.anyio
async def test_score_invoice_aggregates_multiple_rules(db_conn, adb, org_id):
    """An invoice that violates the price baseline AND the contract spending limit
    should surface both alert types from the top-level entry point.

    No consulting keywords are used, so the excessive_consulting rule short-
    circuits before any vector search — no OpenAI mocking required.
    """
    vendor = _mk_vendor(db_conn, org_id)
    _make_contract(db_conn, org_id, vendor, spending_limit=Decimal("1000"))
    # Price baseline (old dates → does not feed the recent-window volume rule).
    _seed_price_history(db_conn, org_id, vendor, "WIDGET", "Widget", 40, n=5)

    cur_inv = _make_invoice(db_conn, org_id, vendor, _uno("MULTI"), Decimal("5000"), _days_ago(1))
    _make_line(db_conn, cur_inv, "WIDGET", "Widget", Decimal("200"))  # 5x median + total 5000 > 1000

    out = await score_invoice(adb, org_id=org_id, invoice_id=cur_inv)

    types = sorted(c.type for c in out)
    assert types == ["contract_policy_violation", "unit_price_delta"]
