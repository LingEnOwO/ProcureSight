"""
Characterization tests for the anomaly-scoring rules.

What is left here is what still needs a database: ``build_duplicate_alert``,
which needs none but has always lived beside these, and the ``score_invoice``
orchestrator, which does. Three of the four rules are functions of an
InvoiceSnapshot now and their cases moved to files that need no connection —
test_unit_price_rule.py, test_volume_spike_rule.py and
test_contract_policy_rule.py. excessive_consulting, the rule that still holds a
connection, is covered in test_excessive_consulting.py.

Everything here must stay green through the rest of the scoring/DB seam refactor
(#15) — any change in alert count, severity, or meta shape should be a
deliberate, reviewed decision, not an accident.

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

from apps.api.services.anomaly_scoring import (
    score_invoice,
    build_duplicate_alert,
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
#
# The rule is a function of a snapshot now, so its own cases live in
# test_unit_price_rule.py, which needs no database. What is left here is the
# orchestrator test at the bottom of this file, which still exercises the rule
# end to end against real Postgres.


# ===========================================================================
# vendor_volume_spike
# ===========================================================================
#
# A function of a snapshot too, so its cases live in test_volume_spike_rule.py.
# Nothing is left here: the rule needs a vendor spend history *and* a spiking
# invoice, which is several rows of setup to reach arithmetic that needs none.


# ===========================================================================
# duplicate_invoice (build_duplicate_alert)
#
# Duplicates are caught in the worker BEFORE insert (the duplicate row is never
# written — see test_worker.py for that end-to-end path). build_duplicate_alert
# owns the alert's shape and severity; these are pure unit tests of that logic.
# ===========================================================================

def test_build_duplicate_alert_critical_when_total_also_matches():
    alert = build_duplicate_alert(
        org_id="org-1",
        vendor_id="vendor-1",
        existing={"id": "existing-id", "total": Decimal("3000.00")},
        incoming_invoice_no="INV-DUP-A",
        incoming_vendor="Acme",
        incoming_total=3000.0,
        incoming_raw_doc_id=42,
    )
    assert alert.type == "duplicate_invoice"
    assert alert.severity == "critical"
    # alert points at the existing invoice, not the rejected re-upload
    assert alert.invoice_id == "existing-id"
    assert alert.meta["matched_fields"] == ["vendor_id", "invoice_no", "total"]
    assert alert.meta["incoming_raw_doc_id"] == 42


def test_build_duplicate_alert_high_when_total_differs():
    alert = build_duplicate_alert(
        org_id="org-1",
        vendor_id="vendor-1",
        existing={"id": "existing-id", "total": Decimal("3000.00")},
        incoming_invoice_no="INV-DUP-B",
        incoming_vendor="Acme",
        incoming_total=9999.0,
        incoming_raw_doc_id=42,
    )
    assert alert.severity == "high"
    assert alert.meta["matched_fields"] == ["vendor_id", "invoice_no"]


def test_build_duplicate_alert_high_when_existing_total_missing():
    alert = build_duplicate_alert(
        org_id="org-1",
        vendor_id="vendor-1",
        existing={"id": "existing-id", "total": None},
        incoming_invoice_no="INV-DUP-C",
        incoming_vendor="Acme",
        incoming_total=3000.0,
        incoming_raw_doc_id=42,
    )
    assert alert.severity == "high"


# ===========================================================================
# contract_policy_violation
# ===========================================================================
#
# Its three sub-rules are covered from snapshot literals in
# test_contract_policy_rule.py. The orchestrator test below still drives the
# rule end to end against real Postgres, which is where the contract read and
# the snapshot assembly are worth proving.


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
