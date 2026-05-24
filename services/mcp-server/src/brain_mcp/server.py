"""FastMCP server entry point.

Wires:
1. Configuration (env + features.yaml).
2. asyncpg pool (init on startup, close on shutdown).
3. FastMCP tools — core tools always; module-gated tools register
   conditionally based on `config.modules.*`.
4. The /health endpoint (allow-listed, no auth).
5. The BrainKeyAuth middleware.

Run locally with:
    python -m brain_mcp.server
"""
from __future__ import annotations

import contextlib
import logging
import os
from typing import AsyncIterator

from fastmcp import FastMCP
from starlette.applications import Starlette

from .auth import BrainKeyAuth
from .ratelimit import RateLimitMiddleware
from .config import Config, load_config
from .db import close_pool, init_pool
from .health import register_health
from .tools import core_browse, core_capture, core_search, core_stats


logger = logging.getLogger("brain_mcp")


def build_mcp(config: Config) -> FastMCP:
    """Construct the FastMCP instance and register tools."""
    mcp = FastMCP(name="openbrain", version="0.1.0")

    core_capture.register(mcp, config=config)
    core_search.register(mcp, config=config)
    core_browse.register(mcp, config=config)
    core_stats.register(mcp, config=config)

    if config.modules.documents:
        # Phase 10 — optional documents module. Importing inside the
        # branch keeps the module's deps from loading when the flag
        # is off.
        try:
            from .tools import docs_capture, docs_chunks, docs_search

            docs_capture.register(mcp, config=config)
            docs_chunks.register(mcp, config=config)
            docs_search.register(mcp, config=config)
        except ImportError:
            logger.warning(
                "MODULE_DOCUMENTS_ENABLED is true but tools/docs_*.py "
                "are not present yet — skipping registration"
            )

    if config.modules.graphify:
        # Phase 15 — graphify synthesis. The export tool dumps a
        # project slice to markdown for the on-demand graphify CLI.
        try:
            from .tools import graphify_export

            graphify_export.register(mcp, config=config)
        except ImportError:
            logger.warning(
                "MODULE_GRAPHIFY_ENABLED is true but tools/graphify_export.py "
                "is not present yet — skipping registration"
            )

    return mcp


def build_app(config: Config | None = None) -> Starlette:
    """Build the Starlette ASGI app with pool lifecycle, /health,
    and bearer-key auth wired in.

    The lifespan handler initialises the asyncpg pool on startup and
    closes it on shutdown so a fresh server boot always has a clean
    pool.
    """
    config = config or load_config()
    mcp = build_mcp(config)
    # stateless_http=True: avoid the streamable-HTTP session handshake
    #   so any one-shot JSON-RPC request (curl, basic clients, smoke
    #   tests) works without a separate initialize round-trip.
    # json_response=True: return plain JSON instead of an SSE stream,
    #   which matches what most non-MCP-aware HTTP clients expect.
    app = mcp.http_app(stateless_http=True, json_response=True)

    register_health(app, config)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        await init_pool(config)
        try:
            yield
        finally:
            await close_pool()

    # Compose lifespans: FastMCP's http_app already sets a lifespan
    # that initialises the MCP session manager. We layer ours on top.
    original_lifespan = app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def combined_lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with original_lifespan(_app):
            async with lifespan(_app):
                yield

    app.router.lifespan_context = combined_lifespan
    # add_middleware prepends, so the LAST add is the OUTERMOST layer.
    # Auth first, then rate-limit on top: a flood is rejected with 429
    # before we even check the key, so an unauthenticated attacker can't
    # burn auth cycles. /health is allow-listed in both.
    app.add_middleware(BrainKeyAuth, brain_key=config.brain_key)
    if config.rate_limit_enabled:
        app.add_middleware(RateLimitMiddleware, per_min=config.rate_limit_per_min)
    return app


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config()
    logger.info(
        "starting brain-mcp on :8080 (embed_provider=%s, modules=%s)",
        config.embed_provider,
        {k: v for k, v in config.modules.as_dict().items() if v},
    )
    import uvicorn

    uvicorn.run(
        build_app(config),
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8080")),
        log_level="info",
    )


if __name__ == "__main__":
    main()
