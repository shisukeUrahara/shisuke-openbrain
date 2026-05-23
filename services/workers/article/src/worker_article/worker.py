"""Main worker loop.

Pops one job at a time off the article queue, runs it through
fetch → chunk → MCP capture_document → MCP add_chunks. Designed to
process_one() is the pure-business-logic seam tests target.

When MODULE_WORKERS_ARTICLE_ENABLED is false the entry point logs
"disabled, idle" and sleeps forever so docker-compose lifecycles
stay predictable.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

from .chunker import chunk_markdown
from .config import Config, load_config
from .fetcher import ExtractedArticle, fetch_article
from .mcp_client import McpClient, McpError
from .queue import QueueClient


logger = logging.getLogger("worker_article")


async def process_one(
    job: dict[str, Any],
    *,
    config: Config,
    mcp: McpClient,
    fetcher=fetch_article,
    chunk_batch_size: int = 8,
) -> dict[str, Any]:
    """Process one queued job. Returns a small summary dict useful
    for tests and structured logging."""
    url = job.get("url")
    if not url:
        return {"status": "skip", "reason": "no url"}

    article: ExtractedArticle | None = await fetcher(url)
    if article is None:
        return {"status": "skip", "reason": "extract failed", "url": url}

    capture_kwargs: dict[str, Any] = {
        "title": article.title,
        "kind": "article",
        "content_md": article.markdown,
        "source": article.url,
        "sha256": article.sha256,
        "metadata": {
            "note": job.get("note"),
            "message_id": job.get("message_id"),
        },
    }
    if job.get("project") is not None:
        capture_kwargs["project"] = job["project"]
    capture_result = await mcp.capture_document(**capture_kwargs)
    if capture_result.get("duplicate"):
        return {
            "status": "duplicate",
            "url": url,
            "document_id": capture_result["id"],
        }

    document_id = capture_result["id"]
    chunks = chunk_markdown(
        article.markdown,
        max_tokens=config.max_chunk_tokens,
        overlap_tokens=config.chunk_overlap_tokens,
    )

    total_inserted = 0
    for start in range(0, len(chunks), chunk_batch_size):
        batch = chunks[start : start + chunk_batch_size]
        result = await mcp.add_chunks(document_id=document_id, chunks=batch)
        total_inserted += int(result.get("inserted", 0))

    return {
        "status": "ingested",
        "url": url,
        "document_id": document_id,
        "chunks": len(chunks),
        "inserted": total_inserted,
    }


async def run(config: Config) -> None:
    mcp = McpClient(config.brain_url)
    queue = QueueClient(config.redis_url, config.queue)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "article worker ready, queue=%s, brain=%s",
        config.queue,
        config.brain_url.split("?", 1)[0] + ("?key=…" if "?key=" in config.brain_url else ""),
    )

    try:
        while not stop.is_set():
            job = await queue.pop(timeout_s=5)
            if job is None:
                continue
            try:
                outcome = await process_one(job, config=config, mcp=mcp)
                logger.info("job done: %s", outcome)
            except McpError as exc:
                logger.error("mcp call failed for job %s: %s", job, exc)
            except Exception as exc:  # pragma: no cover -- catch-all so the loop survives
                logger.exception("unhandled error for job %s: %s", job, exc)
    finally:
        await queue.close()


async def _idle_forever() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(require_runtime=False)
    if not config.enabled:
        logger.info(
            "MODULE_WORKERS_ARTICLE_ENABLED is false — worker is idle. "
            "Set the flag to true and restart to start consuming."
        )
        asyncio.run(_idle_forever())
        return

    try:
        config = load_config(require_runtime=True)
    except RuntimeError as exc:
        logger.error("refusing to start: %s", exc)
        sys.exit(2)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
