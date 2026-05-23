"""Redis producer for worker queues.

Workers pop jobs off the corresponding list via BRPOP. The bot only
ever pushes; it never reads.
"""
from __future__ import annotations

import json
from typing import Any

from redis import asyncio as aioredis


class QueueClient:
    def __init__(self, redis_url: str) -> None:
        if not redis_url:
            raise ValueError("redis_url must be set")
        self._redis = aioredis.from_url(redis_url, decode_responses=True)

    async def enqueue(self, queue: str, job: dict[str, Any]) -> int:
        """LPUSH a JSON-serialised job. Returns the new list length."""
        return await self._redis.lpush(queue, json.dumps(job))

    async def close(self) -> None:
        await self._redis.aclose()
