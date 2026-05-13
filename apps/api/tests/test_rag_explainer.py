"""
Integration tests for the RAG explanation system.

These tests spin up their own minimal fixtures (org, vendor, invoice, alerts)
so they work against any clean Postgres instance running the ProcureSight schema.
They clean up after themselves via transaction rollback.
"""
import json
import os
import uuid
from decimal import Decimal

import psycopg
import pytest

from apps.api.services.rag_explainer import explain_alert, SUPPORTED_TYPES
from apps.api.services.evidence_retrieval import retrieve_evidence


DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://procure:procure@localhost:5432/procuresight"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_conn():
    """Module-scoped connection; rolled back at end so tests leave no trace."""
    with psycopg.connect(DATABASE_URL) as conn:
        yield conn
        conn.rollback()


@pytest.fixture(scope="module")
def org_id(db_conn):
    with db_conn.cursor() as cur:
        oid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO orgs (id, name) VALUES (%s, %s)",
            (oid, f"test-rag-org-{oid[:8]}"),
        )
        cur.execute("SELECT set_config('app.org_id', %s, true)", (oid,))
    return oid


@pytest.fixture(scope="module")
def vendor_id(db_conn, org_id):
    with db_conn.cursor() as cur:
        vid = str(uuid.uuid4())
        cur.execute(
            "INSERT INTO vendors (id, org_id, name) VALUES (%s, %s, %s)",
            (vid, org_id, "Apex Office Supply"),
        )
    return vid


def _make_invoice(db_conn, org_id, vendor_id, invoice_no, total, invoice_date="2024-01-15"):
    with db_conn.cursor() as cur:
        inv_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO invoices
              (id, org_id, vendor_id, invoice_no, invoice_date, currency, subtotal, tax, total, status)
            VALUES (%s, %s, %s, %s, %s, 'USD', %s, 0, %s, 'received')
            """,
            (inv_id, org_id, vendor_id, invoice_no, invoice_date, total, total),
        )
    return inv_id


def _make_line(db_conn, invoice_id, sku, desc, unit_price, qty=1):
    with db_conn.cursor() as cur:
        line_id = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO invoice_lines (id, invoice_id, sku, "desc", qty, unit_price, line_total)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (line_id, invoice_id, sku, desc, qty, unit_price, unit_price * qty),
        )
    return line_id


def _make_alert(db_conn, org_id, vendor_id, invoice_id, alert_type, severity, message, meta):
    with db_conn.cursor() as cur:
        aid = str(uuid.uuid4())
        cur.execute(
            """
            INSERT INTO alerts (id, org_id, vendor_id, invoice_id, type, severity, message, meta_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (aid, org_id, vendor_id, invoice_id, alert_type, severity, message, json.dumps(meta)),
        )
    return aid


# ---------------------------------------------------------------------------
# unit_price_delta
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def unit_price_alert(db_conn, org_id, vendor_id):
    # 5 historical invoices with cheaper lines
    for i in range(5):
        inv = _make_invoice(db_conn, org_id, vendor_id, f"HIST-PRICE-{i}", Decimal("50.00"), f"2023-0{i+1}-10")
        _make_line(db_conn, inv, "INK-XL-BLK", "XL Black Ink Cartridge", Decimal("44.50"))

    # Current invoice with a spike
    curr_inv = _make_invoice(db_conn, org_id, vendor_id, "INV-PRICE-001", Decimal("155.75"), "2024-03-01")
    line_id = _make_line(db_conn, curr_inv, "INK-XL-BLK", "XL Black Ink Cartridge", Decimal("155.75"))

    alert_id = _make_alert(
        db_conn, org_id, vendor_id, curr_inv,
        "unit_price_delta", "high",
        "Unit price for INK-XL-BLK is 3.5× the historical median",
        {
            "rule": "unit_price_delta_vs_median",
            "ratio": 3.5,
            "unit_price": 155.75,
            "median_unit_price": 44.50,
            "sample_size": 5,
            "sku": "INK-XL-BLK",
            "desc": "XL Black Ink Cartridge",
            "invoice_no": "INV-PRICE-001",
            "invoice_id": curr_inv,
            "vendor_id": vendor_id,
            "line_id": line_id,
        },
    )
    return alert_id


def test_unit_price_delta_explanation(db_conn, org_id, unit_price_alert):
    with db_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))

    result = explain_alert(db_conn, org_id, unit_price_alert, force=True)

    assert result["explanation"], "Explanation text must not be empty"
    assert result["alert_type"] == "unit_price_delta"
    text = result["explanation"].lower()
    assert any(kw in text for kw in ["price", "median", "historical", "vendor"])
    assert result["evidence"]["metrics"]["unit_price"] == 155.75
    assert result["evidence"]["metrics"]["median_unit_price"] == 44.50
    assert len(result["evidence"]["historical_examples"]) > 0


def test_unit_price_delta_cached(db_conn, org_id, unit_price_alert):
    result = explain_alert(db_conn, org_id, unit_price_alert, force=False)
    assert result["cached"] is True
    assert result["explanation"]


def test_unit_price_delta_fallback(db_conn, org_id, unit_price_alert, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = explain_alert(db_conn, org_id, unit_price_alert, force=True)
    assert result["explanation"]
    assert "155.75" in result["explanation"] or "44.50" in result["explanation"]


# ---------------------------------------------------------------------------
# vendor_volume_spike
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def volume_spike_alert(db_conn, org_id, vendor_id):
    for i in range(5):
        _make_invoice(db_conn, org_id, vendor_id, f"HIST-VOL-{i}", Decimal("1200.00"), f"2023-0{i+1}-05")

    curr_inv = _make_invoice(db_conn, org_id, vendor_id, "INV-VOL-001", Decimal("8500.00"), "2024-04-01")

    alert_id = _make_alert(
        db_conn, org_id, vendor_id, curr_inv,
        "vendor_volume_spike", "high",
        "Invoice total is 7.1× the vendor's 30-day median",
        {
            "rule": "vendor_volume_spike",
            "ratio": 7.08,
            "baseline_window": "30d",
            "baseline_median_total": 1200.00,
            "invoice_total": 8500.00,
            "invoice_no": "INV-VOL-001",
            "invoice_id": curr_inv,
            "vendor_id": vendor_id,
            "counts": {"invoice_count_30d": 5, "invoice_count_90d": 5},
        },
    )
    return alert_id


def test_vendor_volume_spike_explanation(db_conn, org_id, volume_spike_alert):
    with db_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))

    result = explain_alert(db_conn, org_id, volume_spike_alert, force=True)

    assert result["explanation"]
    assert result["alert_type"] == "vendor_volume_spike"
    text = result["explanation"].lower()
    assert any(kw in text for kw in ["invoice", "median", "total", "vendor"])
    assert result["evidence"]["metrics"]["invoice_total"] == 8500.00


def test_vendor_volume_spike_fallback(db_conn, org_id, volume_spike_alert, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = explain_alert(db_conn, org_id, volume_spike_alert, force=True)
    assert result["explanation"]
    assert "8,500" in result["explanation"] or "1,200" in result["explanation"]


# ---------------------------------------------------------------------------
# duplicate_invoice
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def duplicate_alert(db_conn, org_id, vendor_id):
    existing_inv = _make_invoice(db_conn, org_id, vendor_id, "INV-DUP-001", Decimal("3000.00"), "2024-02-01")
    incoming_inv = _make_invoice(db_conn, org_id, vendor_id, "INV-DUP-001-B", Decimal("3000.00"), "2024-02-15")

    alert_id = _make_alert(
        db_conn, org_id, vendor_id, incoming_inv,
        "duplicate_invoice", "critical",
        "Invoice INV-DUP-001 matches an existing invoice",
        {
            "rule": "duplicate_invoice",
            "candidate_invoice_id": existing_inv,
            "candidate_invoice_no": "INV-DUP-001",
            "candidate_invoice_total": 3000.00,
            "duplicates": [
                {
                    "invoice_id": existing_inv,
                    "invoice_no": "INV-DUP-001",
                    "total": 3000.00,
                    "invoice_date": "2024-02-01",
                    "match_on": {"invoice_no": True, "total": True},
                }
            ],
        },
    )
    return alert_id


def test_duplicate_invoice_explanation(db_conn, org_id, duplicate_alert):
    with db_conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))

    result = explain_alert(db_conn, org_id, duplicate_alert, force=True)

    assert result["explanation"]
    assert result["alert_type"] == "duplicate_invoice"
    text = result["explanation"].lower()
    assert any(kw in text for kw in ["duplicate", "existing", "match", "invoice"])
    assert result["evidence"]["current_invoice"] is not None


def test_duplicate_invoice_fallback(db_conn, org_id, duplicate_alert, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = explain_alert(db_conn, org_id, duplicate_alert, force=True)
    assert result["explanation"]
    assert any(kw in result["explanation"].lower() for kw in ["duplicate", "match", "invoice"])


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_unknown_alert_id_raises(db_conn, org_id):
    with pytest.raises(ValueError, match="not found"):
        explain_alert(db_conn, org_id, str(uuid.uuid4()))


def test_unsupported_alert_type_raises(db_conn, org_id, vendor_id):
    inv = _make_invoice(db_conn, org_id, vendor_id, "INV-UNSUPPORTED", Decimal("100.00"))
    aid = _make_alert(db_conn, org_id, vendor_id, inv, "contract_policy_violation", "high", "test", {})
    with pytest.raises(ValueError, match="Unsupported"):
        explain_alert(db_conn, org_id, aid)
