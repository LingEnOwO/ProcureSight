from fastapi import FastAPI, Body, UploadFile, File, Form, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List
import mimetypes
from dotenv import load_dotenv

# local helpers
from .db import insert_raw_doc, db_ok
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

# Ingestion
@app.post("/api/ingest", tags=["ingestion"])
async def ingest(file: UploadFile = File(...), org_id: str | None = Form(None)):
    org = org_id or settings.ORG_ID

    # Read bytes
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {e}")
    
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
            uploaded_by=settings.UPLOADER_ID,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"DB insert failed: {e}")

    return {"raw_doc_id": raw_doc_id, "s3_key": s3_key}

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