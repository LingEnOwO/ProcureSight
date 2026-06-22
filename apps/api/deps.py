"""
Request-scoped FastAPI dependencies.

Composes identity (``auth.get_user_context``) with the connection pools
(``db.pool`` / ``db.async_pool``) to yield a database connection that already
has the per-request Row-Level-Security context applied — the ``app.org_id`` and
``app.actor_id`` GUCs.

Routes depend on ``org_conn`` / ``org_aconn`` instead of opening a pool
connection and calling ``set_config`` by hand. This keeps the tenant-isolation
guarantee in one audited place (a route can no longer forget to scope its
queries) and removes the boilerplate that was repeated in every handler.

Both GUCs are set with ``is_local=true`` so they are scoped to the connection's
current transaction, which the pool's context manager commits on success and
rolls back on error — matching the previous per-route behavior.
"""
from typing import AsyncIterator, Iterator

from fastapi import Depends
from psycopg import AsyncConnection, Connection

from .auth import UserContext, get_user_context
from .db import async_pool, pool


def org_conn(user_ctx: UserContext = Depends(get_user_context)) -> Iterator[Connection]:
    """Yield a sync pooled connection scoped to the caller's org (RLS GUCs set)."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT set_config('app.org_id', %s, true)", (user_ctx.org_id,))
            cur.execute("SELECT set_config('app.actor_id', %s, true)", (user_ctx.business_user_id,))
        yield conn


async def org_aconn(
    user_ctx: UserContext = Depends(get_user_context),
) -> AsyncIterator[AsyncConnection]:
    """Yield an async pooled connection scoped to the caller's org (RLS GUCs set)."""
    async with async_pool.connection() as aconn:
        await aconn.execute("SELECT set_config('app.org_id', %s, true)", (user_ctx.org_id,))
        await aconn.execute(
            "SELECT set_config('app.actor_id', %s, true)", (user_ctx.business_user_id,)
        )
        yield aconn
