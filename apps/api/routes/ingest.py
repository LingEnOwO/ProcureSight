from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
import mimetypes, hashlib
from starlette.responses import StreamingResponse
from ..storage import put_object, s3_ok
from ..db import insert_raw_doc, get_raw_doc_by_hash, db_ok
from ..services.sse_redis import redis_sse_subscriber, redis_publish
from ..auth import get_user_context, UserContext

router = APIRouter(tags=["ingestion"])


@router.get("/events")
async def sse_events(
    request: Request,
    user_ctx: UserContext = Depends(get_user_context),
):
    """
    Server-Sent Events stream.
    - Sends JSON events as `data: {...}\n\n`
    - Emits a keepalive comment every 15s so proxies don't time out.
    - Events are delivered via Redis pub/sub so ARQ workers can broadcast
      to all connected FastAPI processes.
    """
    org_id = user_ctx.org_id
    redis_client = request.app.state.redis

    async def event_generator():
        yield "event: hello\ndata: {}\n\n"
        async for msg in redis_sse_subscriber(redis_client, org_id):
            if msg == "__keepalive__":
                yield ": ping\n\n"
            else:
                yield f"data: {msg}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@router.post("/ingest")
async def ingest(
    request: Request,
    file: UploadFile = File(...),
    user_ctx: UserContext = Depends(get_user_context),
):
    """
    Ingest file upload. User context from trusted Next.js gateway headers.
    """
    org = user_ctx.org_id

    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {e}")

    digest = hashlib.sha256(data).hexdigest()

    existing = get_raw_doc_by_hash(org_id=org, sha256=digest)
    if existing:
        return {
            "raw_doc_id": existing["id"],
            "s3_key": existing["s3_key"],
            "duplicate": True,
        }

    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    try:
        s3_key = put_object(org, file.filename, content_type, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"S3 upload failed: {e}")

    try:
        raw_doc_id = insert_raw_doc(
            org_id=org,
            s3_key=s3_key,
            filename=file.filename,
            mime=content_type,
            byte_len=len(data),
            sha256=digest,
            uploaded_by=user_ctx.business_user_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DB insert failed: {e}")

    await redis_publish(request.app.state.redis, org, {
        "type": "upload_received",
        "raw_doc_id": raw_doc_id,
        "s3_key": s3_key,
    })

    return {"raw_doc_id": raw_doc_id, "s3_key": s3_key, "duplicate": False}


@router.get("/health")
def health():
    ok_db = db_ok()
    ok_s3 = s3_ok()
    return {"ok": ok_db and ok_s3, "db": ok_db, "s3": ok_s3}
