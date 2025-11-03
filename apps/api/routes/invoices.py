from fastapi import APIRouter, Body, HTTPException, Query
from psycopg import connect
from ..settings import settings
from typing import Optional, List
from pydantic import BaseModel
from ..repos.invoices import (
    ensure_vendor,
    upsert_invoice,
    replace_lines,
    list_invoices as repo_list_invoices,
    get_invoice_with_lines,
    update_invoice_fields,
)
from ..models.invoice import Invoice, InvoiceLine

router = APIRouter(prefix="/invoices", tags=["invoices"])

def get_conn():
    conn = connect(settings.DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (settings.ORG_ID,))
    return conn

# Pydantic model for PATCH
class InvoicePatch(BaseModel):
    vendor_id: Optional[str] = None
    invoice_no: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    lines: Optional[List[InvoiceLine]] = None


# List invoices endpoint
@router.get("")
def list_invoices(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    conn = get_conn()
    try:
        items = repo_list_invoices(conn, limit=limit, offset=offset)
        return {"items": items, "limit": limit, "offset": offset}
    finally:
        conn.close()

# Get single invoice with lines
@router.get("/{invoice_id}")
def get_invoice(invoice_id: str):
    conn = get_conn()
    try:
        inv = get_invoice_with_lines(conn, invoice_id)
        if not inv:
            raise HTTPException(status_code=404, detail="Invoice not found")
        return inv
    finally:
        conn.close()

# ToDo: Add authentication process for patch and post
# PATCH endpoint for partial updates
@router.patch("/{invoice_id}")
def patch_invoice(invoice_id: str, patch: InvoicePatch = Body(...)):
    conn = get_conn()
    try:
        with conn:
            # Update scalar fields
            fields = {k: v for k, v in patch.model_dump(exclude_none=True).items() if k != "lines"}
            ok = update_invoice_fields(conn, invoice_id, fields)
            if not ok:
                raise HTTPException(status_code=404, detail="Invoice not found")
            # Replace lines if provided
            if patch.lines is not None:
                replace_lines(conn, invoice_id, [ln.model_dump() for ln in patch.lines])
        return {"ok": True, "invoice_id": invoice_id}
    finally:
        conn.close()

@router.post("", response_model=Invoice)
def create_invoices(inv: Invoice = Body(...)):
    try:
        conn = get_conn()
        with conn:
            vendor_name = getattr(inv, "vendor", None) or "Unknown Vendor"
            vendor_id = ensure_vendor(conn, settings.ORG_ID, vendor_name)
            invoice_id = upsert_invoice(conn, settings.ORG_ID, vendor_id, inv.dict(), raw_doc_id=None)
            replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])
        return inv.model_copy(update={"id": invoice_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()