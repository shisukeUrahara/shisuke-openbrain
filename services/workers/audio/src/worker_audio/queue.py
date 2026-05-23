"""Redis consumer for multiple ingest queues.

The audio worker polls two queues: ingest:voice and ingest:youtube.
BRPOP can read from multiple keys atomically — it returns the first
list that has an element. We pass both, then dispatch by which list
fired.
"""
from __future__ import annotations

import json
from typing import Any

from redis import asyncio as aioredis


class QueueClient:
    def __init__(self, redis_url: str, *, voice_queue: str, youtube_queue: str) -> None:
        if not redis_url:
            raise ValueError("redis_url must be set")
        self._redis = aioredis.from_url(redis_url, decode_responses=True)
        self._voice = voice_queue
        self._youtube = youtube_queue

    async def pop(self, timeout_s: int = 5) -> tuple[str, dict[str, Any]] | None:
        """Block up to timeout_s for a job from either queue.

        Returns (queue_name, job_dict) or None on timeout. queue_name
        is the original list key so the worker can dispatch.
        """
        result = await self._redis.brpop([self._voice, self._youtube], timeout=timeout_s)
        if result is None:
            return None
        queue_name, payload = result
        return queue_name, json.loads(payload)

    async def lpush_voice(self, job: dict[str, Any]) -> int:
        return await self._redis.lpush(self._voice, json.dumps(job))

    async def lpush_youtube(self, job: dict[str, Any]) -> int:
        return await self._redis.lpush(self._youtube, json.dumps(job))

    async def close(self) -> None:
        await self._redis.aclose()
