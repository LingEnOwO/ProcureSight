from fastapi import APIRouter, Body, HTTPException, Query, Depends
from psycopg import Connection
from ..auth import get_user_context, UserContext
from ..deps import org_conn
from typing import Optional, List
from pydantic import BaseModel
from ..repos.invoices import (
    ensure_vendor,
    replace_lines,
    list_invoices as repo_list_invoices,
    get_invoice_with_lines,
    update_invoice_fields,
)
from ..services.invoice_persistence import persist_invoice
from ..models.invoice import Invoice, InvoiceLine

router = APIRouter(prefix="/invoices", tags=["invoices"])


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
def list_invoices(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn: Connection = Depends(org_conn),
):
    items = repo_list_invoices(conn, limit=limit, offset=offset)
    return {"items": items, "limit": limit, "offset": offset}


# Get single invoice with lines
@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: str,
    conn: Connection = Depends(org_conn),
):
    inv = get_invoice_with_lines(conn, invoice_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


# PATCH endpoint for partial updates
@router.patch("/{invoice_id}")
def patch_invoice(
    invoice_id: str,
    patch: InvoicePatch = Body(...),
    conn: Connection = Depends(org_conn),
):
    fields = {k: v for k, v in patch.model_dump(exclude_none=True).items() if k != "lines"}
    ok = update_invoice_fields(conn, invoice_id, fields)
    if not ok:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if patch.lines is not None:
        replace_lines(conn, invoice_id, [ln.model_dump() for ln in patch.lines])
    return {"ok": True, "invoice_id": invoice_id}


@router.post("", response_model=Invoice)
def create_invoices(
    inv: Invoice = Body(...),
    conn: Connection = Depends(org_conn),
    user_ctx: UserContext = Depends(get_user_context),
):
    try:
        vendor_name = getattr(inv, "vendor", None) or "Unknown Vendor"
        vendor_id = ensure_vendor(conn, user_ctx.org_id, vendor_name)
        invoice_id = persist_invoice(
            conn,
            org_id=user_ctx.org_id,
            vendor_id=vendor_id,
            invoice=inv,
            raw_doc_id=None,
            upsert=True,
        )
        return inv.model_copy(update={"id": invoice_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
