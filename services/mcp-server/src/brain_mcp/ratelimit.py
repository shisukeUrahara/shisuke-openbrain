"""Per-IP rate-limiting middleware.

A fixed-budget sliding window: each client IP may make at most
`per_min` requests in any trailing 60-second window; the next request
gets a 429 with a `Retry-After` header. State is in-memory, so the
limit is per-process — fine for the single-instance deployment this
fork targets. If you ever run multiple replicas, move the counter to
Redis (the worker queue already gives you a Redis dependency to lean
on); this middleware is deliberately small so that swap is local.

`/health` is allow-listed so an uptime monitor polling every few
seconds never trips the limit.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp


_WINDOW_SECONDS = 60.0
_DEFAULT_ALLOWLISTED_PATHS = ("/health",)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests from an IP that exceeds `per_min` in any trailing
    60s window with HTTP 429."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        per_min: int = 100,
        allowlisted_paths: Iterable[str] = _DEFAULT_ALLOWLISTED_PATHS,
        now: "callable[[], float] | None" = None,
    ) -> None:
        super().__init__(app)
        if per_min < 1:
            raise ValueError("per_min must be >= 1")
        self._per_min = per_min
        self._allowlist = tuple(allowlisted_paths)
        # Injectable clock makes the window testable without sleeping.
        self._now = now or time.monotonic
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _client_ip(self, request: Request) -> str:
        # Behind Coolify's proxy the real client is in X-Forwarded-For;
        # fall back to the socket peer for direct connections.
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",", 1)[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method == "OPTIONS" or request.url.path in self._allowlist:
            return await call_next(request)

        ip = self._client_ip(request)
        now = self._now()
        window_start = now - _WINDOW_SECONDS

        bucket = self._hits[ip]
        while bucket and bucket[0] < window_start:
            bucket.popleft()

        if len(bucket) >= self._per_min:
            retry_after = max(1, int(_WINDOW_SECONDS - (now - bucket[0])))
            return JSONResponse(
                {"error": "rate limit exceeded", "limit_per_min": self._per_min},
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )

        bucket.append(now)
        return await call_next(request)
