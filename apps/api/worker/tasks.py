"""
ARQ background tasks for ProcureSight.

Two jobs:
  extract_document  — fetch from S3, run extraction pipeline, persist invoice,
                      then enqueue score_invoice_job.
  score_invoice_job — run the anomaly-scoring rules, persist alerts, send Slack
                      notification, publish SSE event via Redis pub/sub.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pydantic import ValidationError

from apps.api.services.structured_extract import (
    assemble_invoices_from_rows,
    parse_csv_bytes,
    parse_json_bytes,
)
from apps.api.services.unstructured_extract import extract_invoice_from_pdf
from apps.api.services.validator import (
    compute_field_confidence,
    compute_invoice_confidence,
    needs_review,
    validate_invoice,
)
from apps.api.models.alert import AlertCandidate
from apps.api.services.anomaly_scoring import build_duplicate_alert, score_invoice
from apps.api.services.alert_notifications import (
    build_invoice_link,
    build_sse_payload,
    send_alert_to_slack,
)
from apps.api.repos.invoices import ensure_vendor, find_invoice_by_key
from apps.api.repos.extractions import insert_extraction
from apps.api.services.invoice_persistence import persist_invoice
from apps.api.repos.alerts import insert_alert_candidates
from apps.api.models.invoice import Invoice
from apps.api.storage import s3
from apps.api.settings import settings
from apps.api.db import pool as sync_pool

logger = logging.getLogger(__name__)

_loop = asyncio.get_event_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fetch_s3_bytes(s3_key: str) -> bytes:
    """Synchronous S3 fetch — wrapped in run_in_executor by callers."""
    resp = s3.get_object(Bucket=settings.S3_BUCKET, Key=s3_key)
    return resp["Body"].read()


def _extract_unstructured(content: bytes) -> Invoice:
    """Synchronous PDF → LLM pipeline — wrapped in run_in_executor by callers."""
    return extract_invoice_from_pdf(content)


# ---------------------------------------------------------------------------
# Job 1: extract_document
# ---------------------------------------------------------------------------

async def extract_document(
    ctx: dict,
    *,
    org_id: str,
    raw_doc_id: int,
    s3_key: str,
    doc_type: str,
    filename: str,
    content_type: str,
) -> dict[str, Any]:
    """
    Fetch a document from S3, run the appropriate extraction pipeline,
    validate the invoice, persist it to Postgres, then enqueue scoring.

    doc_type is one of: "unstructured" | "structured_csv" | "structured_json"
    """
    loop = asyncio.get_running_loop()

    # 1. Fetch raw bytes from S3 (boto3 is blocking)
    logger.info("Fetching s3_key=%s from bucket=%s", s3_key, settings.S3_BUCKET)
    content: bytes = await loop.run_in_executor(None, _fetch_s3_bytes, s3_key)

    # 2. Extract invoice(s) based on document type
    warnings: list[dict] = []

    if doc_type == "unstructured":
        inv = await loop.run_in_executor(None, _extract_unstructured, content)
        report = validate_invoice(inv)
        if report.has_errors:
            return {
                "ok": False,
                "errors": [e.dict() for e in report.errors],
            }
        warnings = [w.dict() for w in report.warnings]
        invoice_confidence = compute_invoice_confidence(report)
        field_confidence = compute_field_confidence(report)
        review_flag = needs_review(report)
        inv = report.normalized_invoice
        invoices = [inv]

    elif doc_type in ("structured_csv", "structured_json"):
        if doc_type == "structured_csv":
            rows = list(parse_csv_bytes(content))
            docs = assemble_invoices_from_rows(rows)
        else:
            doc = parse_json_bytes(content)
            docs = [doc]

        invoices = []
        invoice_confidence = 1.0
        field_confidence = {}
        review_flag = False
        for doc in docs:
            try:
                inv = Invoice(**doc)
            except ValidationError as ve:
                return {"ok": False, "errors": ve.errors()}
            report = validate_invoice(inv)
            if report.has_errors:
                return {"ok": False, "errors": [e.dict() for e in report.errors]}
            warnings.extend(w.dict() for w in report.warnings)
            invoice_confidence = compute_invoice_confidence(report)
            field_confidence = compute_field_confidence(report)
            review_flag = needs_review(report)
            invoices.append(report.normalized_invoice)
    else:
        return {"ok": False, "errors": [{"message": f"Unknown doc_type: {doc_type}"}]}

    # 3. Persist each invoice using the sync pool in a thread executor
    def _persist(inv: Invoice) -> tuple[str | None, AlertCandidate | None]:
        with sync_pool.connection() as conn:
            conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
            vendor_id = ensure_vendor(conn, str(org_id), inv.vendor)
            existing = find_invoice_by_key(conn, str(org_id), str(vendor_id), inv.invoice_no)

            if existing:
                insert_extraction(
                    conn,
                    raw_doc_id=raw_doc_id,
                    invoice_id=None,
                    confidence=invoice_confidence,
                    field_confidence=field_confidence,
                    warnings=warnings,
                    needs_review=True,
                )
                dup_alert = build_duplicate_alert(
                    org_id=str(org_id),
                    vendor_id=str(vendor_id),
                    existing=existing,
                    incoming_invoice_no=inv.invoice_no,
                    incoming_vendor=inv.vendor,
                    incoming_total=float(inv.total),
                    incoming_raw_doc_id=raw_doc_id,
                )
                insert_alert_candidates(conn, [dup_alert])
                return None, dup_alert

            invoice_id = persist_invoice(
                conn,
                org_id=str(org_id),
                vendor_id=str(vendor_id),
                invoice=inv,
                raw_doc_id=raw_doc_id,
                upsert=False,
            )
            insert_extraction(
                conn,
                raw_doc_id=raw_doc_id,
                invoice_id=str(invoice_id),
                confidence=invoice_confidence,
                field_confidence=field_confidence,
                warnings=warnings,
                needs_review=review_flag,
            )
            return str(invoice_id), None

    results: list[tuple[str | None, AlertCandidate | None]] = []
    for inv in invoices:
        result = await loop.run_in_executor(None, _persist, inv)
        results.append(result)

    # 4. Enqueue scoring or publish duplicate alert SSE for each invoice
    arq_pool = ctx["arq_pool"]
    channel = f"sse:{org_id}"
    invoice_ids: list[str] = []

    for inv, (invoice_id, dup_alert) in zip(invoices, results):
        if dup_alert is not None:
            try:
                payload = build_sse_payload(dup_alert)
                await arq_pool.publish(channel, json.dumps(payload))
            except Exception:
                logger.exception("Failed to publish duplicate invoice SSE event.")
        elif invoice_id is not None:
            invoice_ids.append(invoice_id)
            await arq_pool.enqueue_job(
                "score_invoice_job",
                org_id=org_id,
                invoice_id=invoice_id,
            )

    last_id = invoice_ids[-1] if invoice_ids else None
    return {
        "ok": True,
        "invoice_id": last_id,
        "invoice_ids": invoice_ids,
        "warnings": warnings,
        "invoice_confidence": invoice_confidence,
        "field_confidence": field_confidence,
        "needs_review": review_flag,
    }


# ---------------------------------------------------------------------------
# Job 2: score_invoice_job
# ---------------------------------------------------------------------------

async def score_invoice_job(
    ctx: dict,
    *,
    org_id: str,
    invoice_id: str,
) -> dict[str, Any]:
    """
    Run anomaly scoring for a single invoice, persist alerts, send Slack
    notifications, and publish SSE events via Redis pub/sub.
    """
    db_pool = ctx["db_pool"]
    arq_pool = ctx["arq_pool"]  # ArqRedis IS a redis.asyncio.Redis

    # 1. Run scoring (uses async connection)
    async with db_pool.connection() as aconn:
        await aconn.execute(
            "SELECT set_config('app.org_id', %s, true)", (str(org_id),)
        )
        candidates = await score_invoice(aconn, org_id=str(org_id), invoice_id=str(invoice_id))

    # 2. Persist alerts
    if candidates:
        def _persist_alerts() -> None:
            with sync_pool.connection() as conn:
                conn.execute("SELECT set_config('app.org_id', %s, true)", (str(org_id),))
                insert_alert_candidates(conn, candidates)

        await asyncio.get_running_loop().run_in_executor(None, _persist_alerts)

    # 3. Send Slack + publish SSE for each alert
    invoice_url = build_invoice_link(str(invoice_id))
    channel = f"sse:{org_id}"

    for cand in candidates:
        try:
            await send_alert_to_slack(cand, invoice_url=invoice_url)
        except Exception:
            logger.exception("Failed to send Slack notification for alert.")

        try:
            payload = build_sse_payload(cand)
            await arq_pool.publish(channel, json.dumps(payload))
        except Exception:
            logger.exception("Failed to publish SSE alert event to Redis.")

    return {"ok": True, "alert_count": len(candidates)}
