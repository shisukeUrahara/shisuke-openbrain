"""Health endpoint.

Returns 200 with the active module set when the server is up. The
auth middleware allow-lists this path so external uptime monitors
(and Coolify health checks) can hit it without holding the brain key.
"""
from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .config import Config


def build_health_route(config: Config) -> Route:
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "version": _read_version(),
                "embed_provider": config.embed_provider,
                "modules": config.modules.as_dict(),
            }
        )

    return Route("/health", health, methods=["GET"])


def register_health(app: Starlette, config: Config) -> None:
    """Mount /health at the top of the app's route list so the auth
    middleware never has a chance to gate it. Idempotent — calling
    twice does not register the route twice."""
    route = build_health_route(config)
    for existing in app.routes:
        if getattr(existing, "path", None) == "/health":
            return
    app.routes.insert(0, route)


def _read_version() -> str:
    try:
        from . import __version__

        return __version__
    except Exception:
        return "unknown"
