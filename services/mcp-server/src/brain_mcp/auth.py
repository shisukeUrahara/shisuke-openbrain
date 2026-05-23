"""Bearer-key auth middleware.

Single shared secret (`BRAIN_KEY`) accepted either via:
* `x-brain-key` request header (preferred), OR
* `?key=` query parameter (convenient for clients that cannot set
  custom headers, like Claude Desktop's custom-connector field).

`OPTIONS` preflight requests pass through (CORS). `/health` is
intentionally allow-listed so uptime monitors can hit it without
holding the key.
"""
from __future__ import annotations

from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp


_DEFAULT_ALLOWLISTED_PATHS = ("/health",)


class BrainKeyAuth(BaseHTTPMiddleware):
    """Reject any request whose `x-brain-key` header or `?key=` query
    parameter does not exactly match the configured brain key."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        brain_key: str,
        allowlisted_paths: Iterable[str] = _DEFAULT_ALLOWLISTED_PATHS,
    ) -> None:
        super().__init__(app)
        if not brain_key:
            raise ValueError(
                "BrainKeyAuth requires a non-empty brain_key; refuse to start "
                "without authentication"
            )
        self._brain_key = brain_key
        self._allowlist = tuple(allowlisted_paths)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Preflight CORS — never gate.
        if request.method == "OPTIONS":
            return await call_next(request)

        # Allow-list health / status / liveness endpoints.
        if request.url.path in self._allowlist:
            return await call_next(request)

        supplied = (
            request.headers.get("x-brain-key")
            or request.query_params.get("key")
        )
        if supplied != self._brain_key:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)
