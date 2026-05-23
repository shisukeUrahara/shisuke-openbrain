"""Unit tests for brain_mcp.auth.

Builds a tiny Starlette app, wraps it with BrainKeyAuth, and exercises
the middleware via httpx's ASGI transport. No network involved.

Layer: unit
Phase: 02
Run:   pytest services/mcp-server/tests/unit/test_auth.py -v
"""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from brain_mcp.auth import BrainKeyAuth


BRAIN_KEY = "a" * 64


def _build_app() -> Starlette:
    async def root(_request):
        return JSONResponse({"ok": True})

    async def health(_request):
        return JSONResponse({"ok": True, "modules": {}})

    app = Starlette(routes=[
        Route("/", root, methods=["GET", "POST"]),
        Route("/health", health, methods=["GET"]),
    ])
    app.add_middleware(BrainKeyAuth, brain_key=BRAIN_KEY)
    return app


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ──────────────────────────────────────────────────────────────────
# Reject path
# ──────────────────────────────────────────────────────────────────

async def test_missing_key_returns_401():
    async with _client(_build_app()) as client:
        response = await client.get("/")
    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized"}


async def test_wrong_key_in_header_returns_401():
    async with _client(_build_app()) as client:
        response = await client.get("/", headers={"x-brain-key": "wrong"})
    assert response.status_code == 401


async def test_wrong_key_in_query_returns_401():
    async with _client(_build_app()) as client:
        response = await client.get("/", params={"key": "wrong"})
    assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────
# Accept path
# ──────────────────────────────────────────────────────────────────

async def test_correct_key_in_header_passes():
    async with _client(_build_app()) as client:
        response = await client.get("/", headers={"x-brain-key": BRAIN_KEY})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_correct_key_in_query_passes():
    async with _client(_build_app()) as client:
        response = await client.get("/", params={"key": BRAIN_KEY})
    assert response.status_code == 200


async def test_header_wins_when_both_supplied():
    """If the header is wrong, the request is rejected even if the
    query param is right — header reads first and decides."""
    async with _client(_build_app()) as client:
        response = await client.get(
            "/",
            headers={"x-brain-key": "wrong"},
            params={"key": BRAIN_KEY},
        )
    assert response.status_code == 401


# ──────────────────────────────────────────────────────────────────
# Allow-list
# ──────────────────────────────────────────────────────────────────

async def test_health_endpoint_is_open_without_key():
    """Uptime monitors hit /health; they cannot hold the brain key."""
    async with _client(_build_app()) as client:
        response = await client.get("/health")
    assert response.status_code == 200


async def test_options_preflight_passes_without_key():
    async with _client(_build_app()) as client:
        response = await client.request("OPTIONS", "/")
    assert response.status_code in (200, 405)  # depends on Starlette route config; what matters is it isn't 401


# ──────────────────────────────────────────────────────────────────
# Misconfiguration
# ──────────────────────────────────────────────────────────────────

async def test_empty_brain_key_raises_at_construction():
    """Refuse to start a server with empty auth — silent open access
    would be worse than failing loudly at boot."""
    app = Starlette()
    with pytest.raises(ValueError, match="non-empty brain_key"):
        app.add_middleware(BrainKeyAuth, brain_key="")
        # Starlette resolves middleware lazily; instantiate explicitly:
        BrainKeyAuth(app, brain_key="")
