import logging

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from pydantic import ValidationError

from ..auth import get_user_context, UserContext
from ..repos.invoices import ensure_vendor, upsert_invoice, replace_lines
from ..repos.alerts import insert_alert_candidates
from ..services.structured_extract import parse_csv_bytes, parse_json_bytes, assemble_invoices_from_rows
from ..services.unstructured_extract import extract_invoice_from_pdf
from ..services.validator import validate_invoice, compute_invoice_confidence, compute_field_confidence, needs_review
from ..services.anomaly_scoring import score_invoice
from ..services.alert_notifications import (
    build_invoice_link,
    send_alert_to_slack,
    send_alert_sse,
)
from ..models.invoice import Invoice
from ..settings import settings
from ..db import pool, async_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("/structured")
async def extract_structured(
    file: UploadFile = File(...),
    raw_doc_id: int | None = None,
    user_ctx: UserContext = Depends(get_user_context)
):
    org_id = user_ctx.org_id
    if not org_id:
        raise HTTPException(400, "Missing org context")

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
                if report.has_warnings:
                    warnings.extend(issue.dict() for issue in report.warnings)

                invoice_confidence = compute_invoice_confidence(report)
                field_confidence = compute_field_confidence(report)
                review_flag = needs_review(report)
                inv = report.normalized_invoice
                invoices.append(inv)

        except ValidationError as ve:
            raise HTTPException(status_code=422, detail=ve.errors())
        invoice_ids: list[str] = []
        for inv in invoices:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
                vendor_id = ensure_vendor(conn, org_id, inv.vendor)
                invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
                replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])
            invoice_ids.append(str(invoice_id))

        # Scoring must run after the invoice/line writes are committed.
        for iid in invoice_ids:
            async with async_pool.connection() as aconn:
                await aconn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
                candidates = await score_invoice(
                    aconn,
                    org_id=str(org_id),
                    invoice_id=str(iid),
                )
            if candidates:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
                    insert_alert_candidates(conn, candidates)

            invoice_url = build_invoice_link(str(iid))
            for cand in candidates:
                try:
                    send_alert_to_slack(cand, invoice_url=invoice_url)
                    send_alert_sse(cand)
                except Exception:
                    logger.exception(
                        "Failed to send Slack/SSE notification for alert.",
                        extra={"invoice_id": str(iid)},
                    )

        # For now we return only the last invoice_id plus the validation metadata,
        # matching the original behavior.
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
            if report.has_warnings:
                warnings.extend(issue.dict() for issue in report.warnings)

            invoice_confidence = compute_invoice_confidence(report)
            field_confidence = compute_field_confidence(report)
            review_flag = needs_review(report)
            inv = report.normalized_invoice

        except ValidationError as ve:
            raise HTTPException(status_code=422, detail=ve.errors())

        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
            vendor_id = ensure_vendor(conn, org_id, inv.vendor)
            invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
            replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])

        # Run scoring after commit so scoring can see the inserted invoice/lines.
        async with async_pool.connection() as aconn:
            await aconn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
            candidates = await score_invoice(
                aconn,
                org_id=str(org_id),
                invoice_id=str(invoice_id),
            )
        logger.warning("candidate_count=%d", len(candidates))
        if candidates:
            with pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
                insert_alert_candidates(conn, candidates)

        invoice_url = build_invoice_link(str(invoice_id))
        for cand in candidates:
            try:
                send_alert_to_slack(cand, invoice_url=invoice_url)
                send_alert_sse(cand)
            except Exception:
                logger.exception(
                    "Failed to send Slack/SSE notification for alert.",
                    extra={"invoice_id": str(invoice_id)},
                )

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



@router.post("/unstructured")
async def extract_unstructured(
    file: UploadFile = File(...),
    raw_doc_id: str | None = None,
    user_ctx: UserContext = Depends(get_user_context)
):
    """
    Extract an invoice from an unstructured document (e.g., PDF) using
    the unstructured extraction pipeline (PDF -> text -> LLM -> Invoice),
    then run business validation and persist to the database.
    """
    org_id = user_ctx.org_id
    if not org_id:
        raise HTTPException(400, "Missing org context")

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

    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
        vendor_id = ensure_vendor(conn, org_id, inv.vendor)
        invoice_id = upsert_invoice(conn, org_id, vendor_id, inv.dict(), raw_doc_id)
        replace_lines(conn, invoice_id, [ln.dict() for ln in inv.lines])

    # Run scoring after commit so scoring can see the inserted invoice/lines.
    async with async_pool.connection() as aconn:
        await aconn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
        candidates = await score_invoice(
            aconn,
            org_id=str(org_id),
            invoice_id=str(invoice_id),
        )
    if candidates:
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT set_config('app.org_id', %s, true)", (org_id,))
            insert_alert_candidates(conn, candidates)

    invoice_url = build_invoice_link(str(invoice_id))
    for cand in candidates:
        try:
            send_alert_to_slack(cand, invoice_url=invoice_url)
            send_alert_sse(cand)
        except Exception:
            logger.exception(
                "Failed to send Slack/SSE notification for alert.",
                extra={"invoice_id": str(invoice_id)},
            )

    return {
        "ok": True,
        "invoice_id": invoice_id,
        "warnings": warnings,
        "invoice_confidence": invoice_confidence,
        "field_confidence": field_confidence,
        "needs_review": review_flag,
    }