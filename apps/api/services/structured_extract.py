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