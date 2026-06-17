import logging
import os

import arq
from psycopg_pool import AsyncConnectionPool

from apps.api.settings import settings as app_settings
from apps.api.db import pool as sync_pool
from apps.api.worker.tasks import extract_document, score_invoice_job


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


async def startup(ctx: dict) -> None:
    ctx["db_pool"] = AsyncConnectionPool(
        conninfo=app_settings.app_db_url,
        min_size=2,
        max_size=int(os.getenv("ARQ_DB_POOL_MAX_SIZE", "10")),
        open=False,
    )
    await ctx["db_pool"].open()
    sync_pool.open()
    # ArqRedis subclasses redis.asyncio.Redis, so it doubles as a pub/sub client
    ctx["arq_pool"] = await arq.create_pool(app_settings.redis_settings)


async def shutdown(ctx: dict) -> None:
    sync_pool.close()
    await ctx["db_pool"].close()
    await ctx["arq_pool"].aclose()


class WorkerSettings:
    functions = [extract_document, score_invoice_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = app_settings.redis_settings
    max_jobs = int(os.getenv("ARQ_MAX_JOBS", "10"))
    job_timeout = 300   # 5-minute hard cap per job
    keep_result = 3600  # results readable for 1 hour via GET /jobs/{job_id}
