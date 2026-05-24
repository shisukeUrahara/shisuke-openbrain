"""Image worker main loop.

Pipeline: fetch image bytes -> analyze (VLM produces OCR + description
markdown) -> chunk -> capture_document (kind='image') + add_chunks.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Any

from .analyzer import (
    AnalysisError,
    AnalyzedImage,
    OpenRouterVisionAnalyzer,
    VisionAnalyzer,
)
from .chunker import chunk_markdown
from .config import Config, load_config
from .fetcher import FetchError, FetchedImage, fetch_image
from .mcp_client import McpClient, McpError
from .queue import QueueClient


logger = logging.getLogger("worker_image")


async def process_one(
    job: dict[str, Any],
    *,
    config: Config,
    mcp: McpClient,
    analyzer: VisionAnalyzer,
    chunk_batch_size: int = 8,
) -> dict[str, Any]:
    """Process one image job. Returns a status dict."""

    if "url" not in job and "path" not in job and "file_id" not in job:
        return {"status": "skip", "reason": "no url/path/file_id"}

    try:
        try:
            image: FetchedImage = await fetch_image(
                job, max_bytes=config.max_image_bytes
            )
        except FetchError as exc:
            logger.warning("fetch failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"fetch failed: {exc}"}

        try:
            analyzed: AnalyzedImage = await analyzer.analyze(
                image_bytes=image.data,
                mime=image.mime,
                caption=image.caption,
            )
        except AnalysisError as exc:
            logger.error("vision analysis failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"analysis failed: {exc}"}

        source = job.get("url") or image.source_url or job.get("path") or "image"
        title = job.get("title") or analyzed.title

        capture_kwargs: dict[str, Any] = {
            "title": title,
            "kind": "image",
            "content_md": analyzed.markdown,
            "source": source,
            "sha256": analyzed.sha256,
            "metadata": {
                "mime": image.mime,
                "byte_size": len(image.data),
                "caption": image.caption,
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
                "source": source,
                "document_id": capture_result["id"],
            }

        document_id = capture_result["id"]
        chunks = chunk_markdown(
            analyzed.markdown,
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
            "source": source,
            "document_id": document_id,
            "chunks": len(chunks),
            "inserted": total_inserted,
        }
    except Exception:
        raise


async def run(config: Config) -> None:
    mcp = McpClient(config.brain_url)
    queue = QueueClient(config.redis_url, config.queue)
    analyzer = OpenRouterVisionAnalyzer(
        api_key=config.openrouter_api_key,
        model=config.vision_model,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "image worker ready, queue=%s, model=%s, brain=%s",
        config.queue,
        config.vision_model,
        config.brain_url.split("?", 1)[0]
        + ("?key=…" if "?key=" in config.brain_url else ""),
    )

    try:
        while not stop.is_set():
            job = await queue.pop(timeout_s=5)
            if job is None:
                continue
            try:
                outcome = await process_one(
                    job, config=config, mcp=mcp, analyzer=analyzer
                )
                logger.info("job done: %s", outcome)
            except McpError as exc:
                logger.error("mcp call failed for job %s: %s", job, exc)
            except Exception as exc:  # pragma: no cover -- keep loop alive
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
    logging.getLogger("httpx").setLevel(logging.WARNING)

    config = load_config(require_runtime=False)
    if not config.enabled:
        logger.info(
            "MODULE_WORKERS_IMAGE_ENABLED is false — image worker is idle. "
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
