"""
Characterization tests for the extraction pipelines (CSV / JSON / PDF).

These are pure functions (no DB, no network) except the PDF→LLM path, which we
exercise by patching the OpenAI call. They lock down header normalization, row
grouping, JSON date aliasing, and the guard branches that previously had no
coverage at all (plan item 4.4).
"""
import json

import pytest

from apps.api.services import structured_extract as se
from apps.api.services import unstructured_extract as ue
from apps.api.models.invoice import Invoice


# ===========================================================================
# CSV
# ===========================================================================

def test_parse_csv_normalizes_header_aliases():
    csv_bytes = (
        b"Invoice Number,Supplier,Date,Currency,Subtotal,Tax,Total,sku,desc,qty,unit_price,line_total\n"
        b"INV-9,Acme,2024-01-02,USD,100,0,100,SKU1,Widget,1,100,100\n"
    )
    rows = list(se.parse_csv_bytes(csv_bytes))
    assert len(rows) == 1
    row = rows[0]
    # aliased headers map to canonical keys
    assert row["invoice_no"] == "INV-9"
    assert row["vendor"] == "Acme"
    assert row["invoice_date"] == "2024-01-02"
    # unknown columns (line fields) pass through unchanged
    assert row["sku"] == "SKU1"
    assert row["qty"] == "1"


def test_assemble_groups_rows_by_invoice_no():
    rows = [
        {"invoice_no": "A", "vendor": "V1", "total": "30", "sku": "s1", "desc": "d1",
         "qty": "1", "unit_price": "10", "line_total": "10"},
        {"invoice_no": "A", "vendor": "V1", "sku": "s2", "desc": "d2",
         "qty": "2", "unit_price": "10", "line_total": "20"},
        {"invoice_no": "B", "vendor": "V2", "total": "5", "sku": "s3", "desc": "d3",
         "qty": "1", "unit_price": "5", "line_total": "5"},
    ]
    invoices = se.assemble_invoices_from_rows(rows)
    assert len(invoices) == 2
    inv_a = next(i for i in invoices if i["invoice_no"] == "A")
    assert inv_a["vendor"] == "V1"
    assert len(inv_a["lines"]) == 2
    assert inv_a["lines"][1]["qty"] == 2.0  # coerced to float


def test_assemble_empty_rows_raises():
    with pytest.raises(ValueError, match="no rows"):
        se.assemble_invoices_from_rows([])


def test_assemble_missing_invoice_no_raises():
    with pytest.raises(ValueError, match="invoice_no"):
        se.assemble_invoices_from_rows([{"vendor": "V", "qty": "1"}])


def test_csv_end_to_end_single_invoice():
    csv_bytes = (
        b"invoice_no,vendor,date,currency,subtotal,tax,total,sku,desc,qty,unit_price,line_total\n"
        b"INV-1,Acme,2024-01-01,USD,30,0,30,S1,Widget,1,10,10\n"
        b"INV-1,Acme,2024-01-01,USD,30,0,30,S2,Gadget,2,10,20\n"
    )
    rows = list(se.parse_csv_bytes(csv_bytes))
    invoices = se.assemble_invoices_from_rows(rows)
    assert len(invoices) == 1
    assert invoices[0]["invoice_no"] == "INV-1"
    assert len(invoices[0]["lines"]) == 2


# ===========================================================================
# JSON
# ===========================================================================

def test_parse_json_returns_doc_with_lines():
    payload = {
        "invoice_no": "J-1", "vendor": "Acme", "invoice_date": "2024-02-02",
        "currency": "USD", "subtotal": 10, "tax": 0, "total": 10,
        "lines": [{"sku": "x", "desc": "d", "qty": 1, "unit_price": 10, "line_total": 10}],
    }
    doc = se.parse_json_bytes(json.dumps(payload).encode())
    assert doc["invoice_no"] == "J-1"
    assert len(doc["lines"]) == 1


def test_normalize_invoice_doc_maps_date_to_invoice_date():
    doc = se.normalize_invoice_doc({"date": "2024-01-01", "vendor": "V"})
    assert doc["invoice_date"] == "2024-01-01"
    assert "date" not in doc


def test_parse_json_applies_date_alias():
    doc = se.parse_json_bytes(b'{"date": "2024-01-01", "vendor": "V"}')
    assert doc["invoice_date"] == "2024-01-01"


# ===========================================================================
# PDF text extraction + LLM pipeline
# ===========================================================================

def test_extract_text_from_empty_pdf_raises():
    with pytest.raises(ValueError, match="Empty PDF"):
        ue.extract_text_from_pdf(b"")


def test_llm_extract_empty_text_raises():
    with pytest.raises(ValueError, match="Empty text"):
        ue.llm_extract_invoice_from_text("   ")


def test_llm_extract_without_api_key_raises(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        ue.llm_extract_invoice_from_text("Invoice INV-1 total 100")


def test_extract_invoice_from_pdf_pipeline(monkeypatch):
    """PDF→text→LLM→Invoice wiring, with the text and LLM steps stubbed."""
    extracted = {
        "invoice_no": "PDF-1", "vendor": "PDF Vendor", "invoice_date": "2024-03-01",
        "due_date": None, "currency": "USD", "subtotal": 50.0, "tax": 5.0, "total": 55.0,
        "lines": [{"sku": "A", "desc": "Thing", "qty": 1, "unit_price": 50.0, "line_total": 50.0}],
    }
    monkeypatch.setattr(ue, "extract_text_from_pdf", lambda content: "some invoice text")
    monkeypatch.setattr(ue, "llm_extract_invoice_from_text", lambda text: extracted)

    inv = ue.extract_invoice_from_pdf(b"%PDF-fake-bytes")
    assert isinstance(inv, Invoice)
    assert inv.invoice_no == "PDF-1"
    assert inv.vendor == "PDF Vendor"
    assert len(inv.lines) == 1
