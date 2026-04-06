import logging

from fastapi import APIRouter, HTTPException, Depends, Request
from starlette.status import HTTP_202_ACCEPTED

from ..auth import get_user_context, UserContext
from ..db import get_raw_doc_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/extract", tags=["extraction"])


@router.post("/structured", status_code=HTTP_202_ACCEPTED)
async def extract_structured(
    request: Request,
    raw_doc_id: int | None = None,
    user_ctx: UserContext = Depends(get_user_context),
):
    """
    Enqueue an async structured-extraction job (CSV or JSON) for a document
    that has already been uploaded via POST /ingest.

    Returns a job_id immediately. Poll GET /jobs/{job_id} for status and result.
    """
    org_id = user_ctx.org_id
    if not org_id:
        raise HTTPException(400, "Missing org context")
    if raw_doc_id is None:
        raise HTTPException(400, "raw_doc_id is required")

    raw_doc = get_raw_doc_by_id(raw_doc_id, org_id=org_id)
    if not raw_doc:
        raise HTTPException(404, "raw_doc not found")

    content_type = raw_doc["mime"] or ""
    filename = raw_doc["filename"] or ""
    if content_type in ("text/csv", "application/vnd.ms-excel") or filename.endswith(".csv"):
        doc_type = "structured_csv"
    elif content_type == "application/json" or filename.endswith(".json"):
        doc_type = "structured_json"
    else:
        raise HTTPException(415, f"Unsupported type for structured extraction: {content_type}")

    job = await request.app.state.arq_pool.enqueue_job(
        "extract_document",
        org_id=org_id,
        raw_doc_id=raw_doc_id,
        s3_key=raw_doc["s3_key"],
        doc_type=doc_type,
        filename=filename,
        content_type=content_type,
    )
    return {"job_id": job.job_id}


@router.post("/unstructured", status_code=HTTP_202_ACCEPTED)
async def extract_unstructured(
    request: Request,
    raw_doc_id: int | None = None,
    user_ctx: UserContext = Depends(get_user_context),
):
    """
    Enqueue an async unstructured-extraction job (PDF → LLM pipeline) for a
    document that has already been uploaded via POST /ingest.

    Returns a job_id immediately. Poll GET /jobs/{job_id} for status and result.
    """
    org_id = user_ctx.org_id
    if not org_id:
        raise HTTPException(400, "Missing org context")
    if raw_doc_id is None:
        raise HTTPException(400, "raw_doc_id is required")

    raw_doc = get_raw_doc_by_id(raw_doc_id, org_id=org_id)
    if not raw_doc:
        raise HTTPException(404, "raw_doc not found")

    content_type = raw_doc["mime"] or ""
    filename = raw_doc["filename"] or ""
    if content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(415, f"Unsupported type for unstructured extraction: {content_type}")

    job = await request.app.state.arq_pool.enqueue_job(
        "extract_document",
        org_id=org_id,
        raw_doc_id=raw_doc_id,
        s3_key=raw_doc["s3_key"],
        doc_type="unstructured",
        filename=filename,
        content_type=content_type,
    )
    return {"job_id": job.job_id}
