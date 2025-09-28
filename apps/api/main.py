from fastapi import FastAPI, Body
from pydantic import BaseModel, Field
from typing import List

app = FastAPI(
    title="ProcureSight API",
    version="0.0.1",
    description="Contracts for invoices, vendors, and ingestion."
)

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

@app.get("/health", tags=["meta"])
def health():
    return {"ok": True}

@app.get("/vendors", response_model=List[Vendor], tags=["vendors"])
def list_vendors():
    #stub for contract
    return [Vendor(id=1, name="Apex Office Supply")]

@app.post("/invoices", response_model=Invoice, tags=["invoices"])
def create_invoices(inv: Invoice = Body(...)):
    # echo back with a fake id (contract-only stub)
    return inv.model_copy(update={"id": 123})