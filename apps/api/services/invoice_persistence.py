"""
Invoice persistence shared by the API create endpoint and the worker pipeline.

Both paths need to write an invoice and its line items together; this keeps that
write in one place and wraps it in an explicit transaction so a failure can
never leave an invoice with stale or missing lines. The vendor must already
exist — callers that deduplicate need the vendor id before deciding whether to
write, so ``ensure_vendor`` stays at the call site.
"""
from typing import Optional

from psycopg import Connection

from apps.api.models.invoice import Invoice
from apps.api.repos.invoices import insert_invoice, replace_lines, upsert_invoice


def persist_invoice(
    conn: Connection,
    *,
    org_id: str,
    vendor_id: str,
    invoice: Invoice,
    raw_doc_id: Optional[int],
    upsert: bool,
) -> str:
    """Write ``invoice`` and its lines atomically; return the invoice id.

    ``upsert=True``  uses ``ON CONFLICT DO UPDATE`` (the API create endpoint).
    ``upsert=False`` uses a plain INSERT — the caller must have already confirmed
    no existing row (the worker, via ``find_invoice_by_key``).
    """
    payload = invoice.dict()
    lines = [ln.dict() for ln in invoice.lines]
    with conn.transaction():
        if upsert:
            invoice_id = upsert_invoice(conn, org_id, vendor_id, payload, raw_doc_id)
        else:
            invoice_id = insert_invoice(conn, org_id, vendor_id, payload, raw_doc_id)
        replace_lines(conn, str(invoice_id), lines)
    return str(invoice_id)
