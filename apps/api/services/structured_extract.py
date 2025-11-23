import csv, io, json
from typing import Iterable
#from .validators import validate_invoice  # wraps InvoiceIn for Task 2 later

CSV_HEADER_MAP = {
  "invoice_no": {"invoice", "invoice_no", "invoice number", "inv_no"},
  "vendor": {"vendor", "supplier", "vendor_name"},
  "invoice_date": {"date", "invoice_date"},
  "due_date": {"due", "due_date"},
  "currency": {"currency"},
  "subtotal": {"subtotal"},
  "tax": {"tax", "tax_total"},
  "total": {"total", "grand_total"},
}

def normalize_invoice_doc(doc: dict) -> dict:
    if "date" in doc and "invoice_date" not in doc:
        doc["invoice_date"] = doc.pop("date")
    return doc

def _normalize_header(h: str) -> str:
    h = h.strip().lower()
    for key, aliases in CSV_HEADER_MAP.items():
        if h in aliases:
            return key
    return h # allow lines columns to pass through (sku, desc, qty, unit_price, line_total)

def assemble_invoices_from_rows(rows: list[dict]) -> list[dict]:
    """Group CSV rows by invoice_no into a list of invoice-level dicts."""
    if not rows:
        raise ValueError("CSV file contained no rows")

    grouped: dict[str, list[dict]] = {}
    for row in rows:
        invoice_no = row.get("invoice_no")
        if not invoice_no:
            raise ValueError("CSV row missing required invoice_no field")
        grouped.setdefault(invoice_no, []).append(row)

    invoices = []
    for invoice_no, inv_rows in grouped.items():
        header = inv_rows[0]
        invoice = {
            "invoice_no": header.get("invoice_no"),
            "vendor": header.get("vendor"),
            "invoice_date": header.get("invoice_date"),
            "due_date": header.get("due_date"),
            "currency": header.get("currency"),
            "subtotal": header.get("subtotal"),
            "tax": header.get("tax"),
            "total": header.get("total"),
            "lines": [],
        }
        for row in inv_rows:
            line = {
                "sku": row.get("sku"),
                "desc": row.get("desc"),
                "qty": float(row.get("qty") or 0),
                "unit_price": float(row.get("unit_price") or 0),
                "line_total": float(row.get("line_total") or 0),
            }
            invoice["lines"].append(line)
        invoices.append(invoice)

    return invoices

"""def assemble_invoice_from_rows(rows: list[dict]) -> dict:
    invoices = assemble_invoices_from_rows(rows)
    # for v0 callers that assume single-invoice CSVs
    return invoices[0]"""

def parse_csv_bytes(b: bytes) -> Iterable[dict]:
    text = b.decode("utf-8", errors="replace")
    rdr = csv.DictReader(io.StringIO(text))
    for row in rdr:
        norm = { _normalize_header(k): v for k, v in row.items() }
        # Expect either a header row for invoice and separate file for lines,
        # or a denormalized format; for v0 assume one invoice per file (recommended).
        yield norm
def parse_json_bytes(b:bytes) -> dict:
    doc = json.loads(b) # expect {invoice_no, vendor, ..., lines:[...]}
    doc = normalize_invoice_doc(doc)
    return doc