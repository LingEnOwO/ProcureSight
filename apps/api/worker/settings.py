import arq
from arq.connections import RedisSettings
from psycopg_pool import AsyncConnectionPool

from apps.api.settings import settings as app_settings
from apps.api.worker.tasks import extract_document, score_invoice_job


async def startup(ctx: dict) -> None:
    ctx["db_pool"] = AsyncConnectionPool(
        conninfo=app_settings.app_db_url,
        min_size=2,
        max_size=10,
        open=False,
    )
    await ctx["db_pool"].open()
    # ArqRedis subclasses redis.asyncio.Redis, so it doubles as a pub/sub client
    ctx["arq_pool"] = await arq.create_pool(
        RedisSettings(host=app_settings.REDIS_HOST, port=app_settings.REDIS_PORT)
    )


async def shutdown(ctx: dict) -> None:
    await ctx["db_pool"].close()
    await ctx["arq_pool"].aclose()


class WorkerSettings:
    functions = [extract_document, score_invoice_job]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings(
        host=app_settings.REDIS_HOST,
        port=app_settings.REDIS_PORT,
    )
    max_jobs = 10
    job_timeout = 300   # 5-minute hard cap per job
    keep_result = 3600  # results readable for 1 hour via GET /jobs/{job_id}
