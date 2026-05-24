"""Unit tests for brain_mcp.ratelimit.

Builds a tiny Starlette app behind RateLimitMiddleware and drives it via
httpx's ASGI transport. The 60s window is exercised with an injected
clock so the tests never sleep.

Layer: unit
Phase: 09
Run:   pytest services/mcp-server/tests/unit/test_ratelimit.py -v
"""
from __future__ import annotations

import httpx
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from brain_mcp.ratelimit import RateLimitMiddleware


class _Clock:
    """A controllable monotonic clock."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def _build_app(per_min: int, clock: _Clock) -> Starlette:
    async def root(_request):
        return JSONResponse({"ok": True})

    async def health(_request):
        return JSONResponse({"ok": True})

    app = Starlette(routes=[
        Route("/", root, methods=["GET", "POST"]),
        Route("/health", health, methods=["GET"]),
    ])
    app.add_middleware(RateLimitMiddleware, per_min=per_min, now=clock)
    return app


def _client(app: Starlette) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_requests_under_the_limit_pass():
    clock = _Clock()
    async with _client(_build_app(per_min=5, clock=clock)) as client:
        for _ in range(5):
            assert (await client.get("/")).status_code == 200


async def test_the_request_over_the_limit_is_429():
    """The 101st-style call within the window is rejected with 429 and a
    Retry-After header."""
    clock = _Clock()
    async with _client(_build_app(per_min=5, clock=clock)) as client:
        for _ in range(5):
            assert (await client.get("/")).status_code == 200
        over = await client.get("/")
    assert over.status_code == 429
    assert over.json()["limit_per_min"] == 5
    assert int(over.headers["Retry-After"]) >= 1


async def test_window_slides_so_capacity_returns():
    """After the 60s window passes, earlier hits expire and capacity is
    available again."""
    clock = _Clock()
    async with _client(_build_app(per_min=3, clock=clock)) as client:
        for _ in range(3):
            assert (await client.get("/")).status_code == 200
        assert (await client.get("/")).status_code == 429
        clock.advance(61)  # slide past the window
        assert (await client.get("/")).status_code == 200


async def test_health_is_never_rate_limited():
    clock = _Clock()
    async with _client(_build_app(per_min=2, clock=clock)) as client:
        for _ in range(10):
            assert (await client.get("/health")).status_code == 200


async def test_distinct_ips_have_independent_budgets():
    clock = _Clock()
    async with _client(_build_app(per_min=2, clock=clock)) as client:
        h1 = {"x-forwarded-for": "10.0.0.1"}
        h2 = {"x-forwarded-for": "10.0.0.2"}
        assert (await client.get("/", headers=h1)).status_code == 200
        assert (await client.get("/", headers=h1)).status_code == 200
        assert (await client.get("/", headers=h1)).status_code == 429
        # A different IP still has its full budget.
        assert (await client.get("/", headers=h2)).status_code == 200
        assert (await client.get("/", headers=h2)).status_code == 200
        assert (await client.get("/", headers=h2)).status_code == 429


async def test_x_forwarded_for_takes_the_first_hop():
    clock = _Clock()
    async with _client(_build_app(per_min=1, clock=clock)) as client:
        # Same real client IP behind two proxies -> same budget.
        assert (await client.get("/", headers={"x-forwarded-for": "9.9.9.9, 10.0.0.5"})).status_code == 200
        assert (await client.get("/", headers={"x-forwarded-for": "9.9.9.9, 10.0.0.6"})).status_code == 429


def test_per_min_must_be_positive():
    with pytest.raises(ValueError):
        RateLimitMiddleware(app=None, per_min=0)
