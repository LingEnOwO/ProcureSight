from fastapi import FastAPI, Body, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List
import mimetypes
import hashlib
from dotenv import load_dotenv
import asyncio, json
from starlette.responses import StreamingResponse

# local helpers
from .db import insert_raw_doc, db_ok, get_raw_doc_by_hash
from .storage import put_object, s3_ok

load_dotenv(".env.local")

class Settings(BaseSettings):
    ORG_ID: str
    UPLOADER_ID: str | None = None

settings = Settings()

app = FastAPI(
    title="ProcureSight API",
    version="0.0.1",
    description="Contracts for invoices, vendors, and ingestion."
)

SUBSCRIBERS: set[asyncio.Queue] = set()

async def broadcast(event: dict):
    # Push event to all connected clients
    msg = json.dumps(event)
    dead = []
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except Exception:
            dead.append(q)
    for q in dead:
        SUBSCRIBERS.discard(q)

@app.get("/events")
async def sse_events():
    """
    Server-Sent Events stream.
    - Sends JSON events as `data: {...}\n\n`
    - Emits a keepalive comment every 15s so proxies don't time out.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()
    SUBSCRIBERS.add(queue)

    async def event_generator():
        try:
            # initial hello so clients know they're connected
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    # wait up to 15s for a real event
                    msg = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    # keppalive (comment line per SSE spec)
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            # client disconnected
            pass
        finally:
            SUBSCRIBERS.discard(queue)
    return StreamingResponse(event_generator(),
                             media_type = "text/event-stream",
                             headers={
                                 "Cache-Control": "no-cache",
                                 "Connection": "keep-alive",
                             })
            
# Ingestion
@app.post("/api/ingest", tags=["ingestion"])
async def ingest(file: UploadFile = File(...), org_id: str | None = Form(None)):
    org = org_id or settings.ORG_ID

    # Read bytes
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {e}")
    
    # Compute content hash for idempotency
    digest = hashlib.sha256(data).hexdigest()

    # Fast duplicate check (per org, by content hash) BEFORE touching S3
    existing = get_raw_doc_by_hash(org_id=org, sha256=digest)
    if existing:
        # Do not upload again and do not insert another DB row.
        # Optionally skip broadcast for duplicates to avoid noisy toasts.s
        return {
            "raw_doc_id": existing["id"],
            "s3_key": existing["s3_key"],
            "duplicate": True,
        }
    
    # Determine content type
    content_type = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"

    # Store bytes -> MinIO
    try:
        s3_key = put_object(org, file.filename, content_type, data)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"S3 upload failed: {e}")
    
    # Register metadata -> Postgres
    try: 
        raw_doc_id = insert_raw_doc(
            org_id=org,
            s3_key=s3_key,
            filename=file.filename,
            mime=content_type,
            byte_len=len(data),
            sha256=digest,
            uploaded_by=settings.UPLOADER_ID,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DB insert failed: {e}")

    await broadcast({
        "type": "upload_received",
        "raw_doc_id": raw_doc_id,
        "s3_key": s3_key,
    })
    return {"raw_doc_id": raw_doc_id, "s3_key": s3_key, "duplicate": False}

@app.get("/health", tags=["meta"])
def health():
    ok_db = db_ok()
    ok_s3 = s3_ok()
    return {"ok": ok_db and ok_s3, "db": ok_db, "s3": ok_s3}

class Vendor(BaseModel):
    id: int = Field(..., example=1)
    name: str = Field(..., example="Apex Office Supply")

class InvoiceLine(BaseModel):
    sku: str
    desc: str
    qty: float
    unit_price: float
    line_total: float

class Invoice(BaseModel):
    id: int | None = None
    vendor_id: int
    invoice_no: str
    date: str  # ISO YYYY-MM-DD
    currency: str
    subtotal: float
    tax: float
    total: float
    lines: List[InvoiceLine] = []

@app.get("/vendors", response_model=List[Vendor], tags=["vendors"])
def list_vendors():
    #stub for contract
    return [Vendor(id=1, name="Apex Office Supply")]

@app.post("/invoices", response_model=Invoice, tags=["invoices"])
def create_invoices(inv: Invoice = Body(...)):
    # echo back with a fake id (contract-only stub)
    return inv.model_copy(update={"id": 123})