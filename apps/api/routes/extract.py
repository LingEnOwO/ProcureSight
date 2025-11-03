# apps/api/routes/extract.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from psycopg import connect
from pydantic import ValidationError
from ..repos.invoices import ensure_vendor, upsert_invoice, replace_lines
from ..services.structured_extract import parse_csv_bytes, parse_json_bytes
from ..models.invoice import Invoice
from ..settings import settings

router = APIRouter(prefix="/extract", tags=["extraction"])


def get_conn():
    """Open a Postgres connection and set per-request org context."""
    conn = connect(settings.DATABASE_URL)
    org_id = settings.ORG_ID
    # Establish org context for RLS/policies if your DB uses it
    with conn.cursor() as cur:
        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
        # Using set_config(..., true) sets the GUC for the current transaction (LOCAL).
    return conn, org_id


@router.post("/structured")
def extract_structured(file: UploadFile = File(...), raw_doc_id: int | None = None):
    conn, org_id = get_conn()
    if not org_id:
        raise HTTPException(400, "Missing org context")

    try:
        content = file.file.read()
        if file.content_type in ("text/csv", "application/vnd.ms-excel") or file.filename.endswith(".csv"):
            # Expect a single-invoice JSON summary alongside (recommended), or a single invoice per file.
            # For v0, assume the file is already a JSON with header+lines. If truly CSV,
            # you can pre-convert to JSON using your script.
            raise HTTPException(415, "CSV-to-JSON denormalization not implemented in endpoint v0")

        elif file.content_type == "application/json" or file.filename.endswith(".json"):
            doc = parse_json_bytes(content)
            try:
                inv = Invoice(**doc)  # enforce schema; raise 422 if mismatch
            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors())

            with conn:
                vendor_id = ensure_vendor(conn, org_id, inv.vendor)
                invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
                replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])
            return {"ok": True, "invoice_id": invoice_id}
        else:
            raise HTTPException(415, f"Unsupported type: {file.content_type}")
    finally:
        conn.close()