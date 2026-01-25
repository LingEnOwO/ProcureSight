from fastapi import FastAPI
from .settings import settings
from .routes.ingest import router as ingest_router
from .routes.invoices import router as invoices_router
from .routes.vendors import router as vendors_router
from .routes.extract import router as extract_router 
from .db import connect_database, disconnect_database


app = FastAPI(
    title="ProcureSight API",
    version="0.0.1",
    description="Contracts for invoices, vendors, and ingestion."
)

@app.on_event("startup")
async def _startup() -> None:
    await connect_database()


@app.on_event("shutdown")
async def _shutdown() -> None:
    await disconnect_database()

app.include_router(ingest_router)
app.include_router(invoices_router)
app.include_router(vendors_router)
app.include_router(extract_router)