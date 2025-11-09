# apps/api/routes/extract.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from psycopg import connect
from pydantic import ValidationError
from ..repos.invoices import ensure_vendor, upsert_invoice, replace_lines
from ..services.structured_extract import parse_csv_bytes, parse_json_bytes, assemble_invoices_from_rows
from ..services.unstructured_extract import extract_invoice_from_pdf
from ..services.validator import validate_invoice, compute_invoice_confidence, compute_field_confidence, needs_review
from ..models.invoice import Invoice
from ..models.validation import ValidationReport
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
        warnings: list[dict] = []
        if file.content_type in ("text/csv", "application/vnd.ms-excel") or file.filename.endswith(".csv"):
            rows = list(parse_csv_bytes(content))
            docs = assemble_invoices_from_rows(rows)
            invoices = []
            try:
                for doc in docs:
                    inv = Invoice(**doc)
                    report = validate_invoice(inv) 
                    if report.has_errors:
                        raise HTTPException(
                            status_code=422,
                            detail=[{
                                "field": issue.field,
                                "code": issue.code,
                                "message": issue.message,
                                "diff": issue.diff,
                            } for issue in report.errors]
                        )
                    if report.has_warnings:
                        warnings.extend(issue.dict() for issue in report.warnings)

                    invoice_confidence = compute_invoice_confidence(report)
                    field_confidence = compute_field_confidence(report)
                    review_flag = needs_review(report)
                    inv = report.normalized_invoice 
                    invoices.append(inv)

            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors())

            with conn:
                invoice_ids = []
                for inv in invoices:
                    vendor_id = ensure_vendor(conn, org_id, inv.vendor)
                    invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
                    replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])
                    invoice_ids.append(invoice_id)
                    
            return {
                "ok": True, 
                "invoice_id": invoice_id, 
                "warnings": warnings,
                "invoice_confidence": invoice_confidence,
                "field_confidence": field_confidence,
                "needs_review": review_flag,
            }

        elif file.content_type == "application/json" or file.filename.endswith(".json"):
            doc = parse_json_bytes(content)
            try:
                inv = Invoice(**doc)  # enforce schema; raise 422 if mismatch
                report = validate_invoice(inv) 
                if report.has_errors:
                    raise HTTPException(
                        status_code=422,
                        detail=[{
                            "field": issue.field,
                            "code": issue.code,
                            "message": issue.message,
                            "diff": issue.diff,
                        } for issue in report.errors]
                    )
                if report.has_warnings:
                    warnings.extend(issue.dict() for issue in report.warnings)

                invoice_confidence = compute_invoice_confidence(report)
                field_confidence = compute_field_confidence(report)
                review_flag = needs_review(report)
                inv = report.normalized_invoice 
                
            except ValidationError as ve:
                raise HTTPException(status_code=422, detail=ve.errors())

            with conn:
                vendor_id = ensure_vendor(conn, org_id, inv.vendor)
                invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
                replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])

            return {
                "ok": True, 
                "invoice_id": invoice_id, 
                "warnings": warnings,
                "invoice_confidence": invoice_confidence,
                "field_confidence": field_confidence,
                "needs_review": review_flag,
            }
        else:
            raise HTTPException(415, f"Unsupported type: {file.content_type}")
    finally:
        conn.close()

@router.post("/unstructured")
def extract_unstructured(file: UploadFile = File(...), raw_doc_id: int | None = None):
    """
    Extract an invoice from an unstructured document (e.g., PDF) using
    the unstructured extraction pipeline (PDF -> text -> LLM -> Invoice),
    then run business validation and persist to the database.
    """
    conn, org_id = get_conn()
    if not org_id:
        raise HTTPException(400, "Missing org context")

    try:
        content = file.file.read()
        if not content:
            raise HTTPException(400, "Empty file upload")

        # Basic content-type/extension guard; adjust as needed for other formats.
        if file.content_type != "application/pdf" and not file.filename.lower().endswith(".pdf"):
            raise HTTPException(415, f"Unsupported type for unstructured extraction: {file.content_type}")

        try:
            # PDF bytes -> text -> dict -> Invoice (schema-level validation)
            inv = extract_invoice_from_pdf(content)
        except ValidationError as ve:
            # Schema mismatch between LLM output and Invoice model
            raise HTTPException(status_code=422, detail=ve.errors())

        report = validate_invoice(inv)
        if report.has_errors:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "field": issue.field,
                        "code": issue.code,
                        "message": issue.message,
                        "diff": issue.diff,
                    }
                    for issue in report.errors
                ],
            )

        warnings = [issue.dict() for issue in report.warnings]
        invoice_confidence = compute_invoice_confidence(report)
        field_confidence = compute_field_confidence(report)
        review_flag = needs_review(report)
        inv = report.normalized_invoice

        with conn:
            vendor_id = ensure_vendor(conn, org_id, inv.vendor)
            invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
            replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])

        return {
            "ok": True,
            "invoice_id": invoice_id,
            "warnings": warnings,
            "invoice_confidence": invoice_confidence,
            "field_confidence": field_confidence,
            "needs_review": review_flag,
        }
    finally:
        conn.close()