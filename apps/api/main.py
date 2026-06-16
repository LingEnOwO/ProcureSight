from contextlib import asynccontextmanager
from fastapi import FastAPI
import arq
import redis.asyncio as aioredis
from .settings import settings
from .routes.ingest import router as ingest_router
from .routes.invoices import router as invoices_router
from .routes.vendors import router as vendors_router
from .routes.extract import router as extract_router
from .routes.alerts import router as alerts_router
from .routes.alert_explanations import router as alert_explanations_router
from .routes.jobs import router as jobs_router
from .routes.score import router as score_router
from .db import async_pool, pool as sync_pool
from fastapi.middleware.cors import CORSMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    sync_pool.open()
    await async_pool.open()
    app.state.arq_pool = await arq.create_pool(settings.redis_settings)
    _redis_password = f":{settings.REDIS_PASSWORD}@" if settings.REDIS_PASSWORD else ""
    app.state.redis = aioredis.from_url(
        f"redis://{_redis_password}{settings.REDIS_HOST}:{settings.REDIS_PORT}",
        decode_responses=True,
    )
    yield
    sync_pool.close()
    await async_pool.close()
    await app.state.arq_pool.aclose()
    await app.state.redis.aclose()


app = FastAPI(
    title="ProcureSight API",
    version="0.0.1",
    description="Contracts for invoices, vendors, and ingestion.",
    lifespan=lifespan,
)

_allowed_origins = ["http://localhost:3000"]
if settings.APP_BASE_URL:
    _allowed_origins.append(settings.APP_BASE_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest_router)
app.include_router(invoices_router)
app.include_router(vendors_router)
app.include_router(extract_router)
app.include_router(alerts_router)
app.include_router(alert_explanations_router)
app.include_router(jobs_router)
app.include_router(score_router)