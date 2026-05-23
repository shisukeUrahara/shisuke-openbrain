"""Main worker loop for PDF ingestion.

Pipeline per job:
  fetch_pdf(job)      -> (local_path, owned)
  extractor.extract() -> ExtractedDocument
  chunk_markdown()    -> chunks[]
  mcp.capture_document -> {id, sha256, duplicate, ...}
    (skip add_chunks if duplicate=True)
  mcp.add_chunks       -> batched

Idle mode (flag off) sleeps forever, same as other workers.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

from .chunker import chunk_markdown
from .config import Config, load_config
from .extractor import ExtractedDocument, PdfExtractor, PymupdfExtractor
from .fetcher import FetchError, fetch_pdf
from .mcp_client import McpClient, McpError
from .queue import QueueClient


logger = logging.getLogger("worker_pdf")


async def process_one(
    job: dict[str, Any],
    *,
    config: Config,
    mcp: McpClient,
    extractor: PdfExtractor,
    chunk_batch_size: int = 8,
) -> dict[str, Any]:
    """Process one queued PDF job. Returns a small status dict."""
    if "path" not in job and "url" not in job:
        return {"status": "skip", "reason": "no path or url"}

    local_path: Path | None = None
    owned = False
    try:
        try:
            local_path, owned = await fetch_pdf(
                job, max_bytes=config.max_pdf_bytes
            )
        except FetchError as exc:
            logger.warning("fetch failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"fetch failed: {exc}"}

        try:
            article: ExtractedDocument = extractor.extract(local_path)
        except Exception as exc:  # docling raises a few flavours
            logger.exception("docling extraction failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"extract failed: {exc}"}

        title = job.get("title") or article.title
        source = job.get("url") or str(local_path)

        capture_kwargs: dict[str, Any] = {
            "title": title,
            "kind": "pdf",
            "content_md": article.markdown,
            "source": source,
            "sha256": article.sha256,
            "metadata": {
                "page_count": article.page_count,
                "note": job.get("note"),
                "message_id": job.get("message_id"),
                "file_name": job.get("file_name"),
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
            "source": source,
            "document_id": document_id,
            "chunks": len(chunks),
            "inserted": total_inserted,
            "page_count": article.page_count,
        }
    finally:
        if owned and local_path and local_path.exists():
            try:
                local_path.unlink()
            except OSError:
                logger.warning("failed to delete temp file %s", local_path)


async def run(config: Config) -> None:
    mcp = McpClient(config.brain_url)
    queue = QueueClient(config.redis_url, config.queue)
    extractor = PymupdfExtractor()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "pdf worker ready, queue=%s, brain=%s",
        config.queue,
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
                    job, config=config, mcp=mcp, extractor=extractor
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
            "MODULE_WORKERS_PDF_ENABLED is false — pdf worker is idle. "
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
