"""Redis consumer for the article queue."""
from __future__ import annotations

import json
from typing import Any

from redis import asyncio as aioredis


class QueueClient:
    def __init__(self, redis_url: str, queue: str) -> None:
        if not redis_url:
            raise ValueError("redis_url must be set")
        if not queue:
            raise ValueError("queue must be set")
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._queue = queue

    async def pop(self, timeout_s: int = 5) -> dict[str, Any] | None:
        """Block up to `timeout_s` seconds for one job. Returns None
        on timeout so the worker loop can run periodic checks."""
        result = await self._redis.brpop([self._queue], timeout=timeout_s)
        if result is None:
            return None
        _queue_name, payload = result
        return json.loads(payload)

    async def lpush(self, job: dict[str, Any]) -> int:
        """Used by integration tests to seed the queue."""
        return await self._redis.lpush(self._queue, json.dumps(job))

    async def close(self) -> None:
        await self._redis.aclose()
