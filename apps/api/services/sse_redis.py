"""
Redis-backed SSE subscriber.

Channel pattern: sse:{org_id}

- ARQ workers publish to  redis.publish("sse:{org_id}", json_str)
- FastAPI /events endpoint subscribes per connected client via redis_sse_subscriber()
- Multiple FastAPI processes/pods all receive events correctly via Redis fan-out
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis


async def redis_sse_subscriber(
    redis_client: aioredis.Redis,
    org_id: str,
) -> AsyncGenerator[str, None]:
    """
    Subscribe to sse:{org_id} and yield raw JSON strings as events arrive.
    Yields the sentinel string "__keepalive__" every 15 seconds when idle.
    Cleans up subscription automatically on client disconnect (generator close).
    """
    pubsub = redis_client.pubsub()
    channel = f"sse:{org_id}"
    await pubsub.subscribe(channel)
    try:
        while True:
            try:
                msg = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=15.0,
                )
                if msg and msg["type"] == "message":
                    data = msg["data"]
                    if isinstance(data, bytes):
                        data = data.decode()
                    yield data
                else:
                    yield "__keepalive__"
            except asyncio.TimeoutError:
                yield "__keepalive__"
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


async def redis_publish(redis_client: aioredis.Redis, org_id: str, event: dict[str, Any]) -> None:
    """Publish a dict event to the sse:{org_id} Redis channel."""
    channel = f"sse:{org_id}"
    await redis_client.publish(channel, json.dumps(event))
