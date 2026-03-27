from contextlib import asynccontextmanager
from fastapi import FastAPI
from .settings import settings
from .routes.ingest import router as ingest_router
from .routes.invoices import router as invoices_router
from .routes.vendors import router as vendors_router
from .routes.extract import router as extract_router
from .routes.alerts import router as alerts_router
from .db import async_pool
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    await async_pool.open()
    yield
    await async_pool.close()


app = FastAPI(
    title="ProcureSight API",
    version="0.0.1",
    description="Contracts for invoices, vendors, and ingestion.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(invoices_router)
app.include_router(vendors_router)
app.include_router(extract_router)
app.include_router(alerts_router)