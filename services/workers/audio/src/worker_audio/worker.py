"""Audio worker main loop.

Pops jobs from `ingest:voice` and `ingest:youtube`, fetches the
audio (path / HTTP / yt-dlp), transcribes via faster-whisper,
chunks, captures + add_chunks via MCP.

`kind` is derived from the queue the job came off (or from URL
shape for path-mode jobs): `youtube` if a YouTube URL was involved,
otherwise `voice`.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path
from shutil import rmtree
from typing import Any

from .chunker import chunk_markdown
from .config import Config, load_config
from .fetcher import FetchError, FetchedAudio, fetch_audio
from .mcp_client import McpClient, McpError
from .queue import QueueClient
from .transcriber import AudioTranscriber, Transcript, WhisperTranscriber


logger = logging.getLogger("worker_audio")


def _kind_for_job(job: dict[str, Any], queue_name: str, *, voice_queue: str) -> str:
    """Derive the document kind from the originating queue + payload."""
    if queue_name == voice_queue:
        return "voice"
    return "youtube"


async def process_one(
    job: dict[str, Any],
    *,
    config: Config,
    mcp: McpClient,
    transcriber: AudioTranscriber,
    queue_name: str,
    chunk_batch_size: int = 8,
) -> dict[str, Any]:
    """Process one queued audio job. Returns a status dict."""

    if "url" not in job and "path" not in job and "file_id" not in job:
        return {"status": "skip", "reason": "no url/path/file_id"}

    audio: FetchedAudio | None = None
    try:
        try:
            audio = await fetch_audio(job, max_bytes=config.max_audio_bytes)
        except FetchError as exc:
            logger.warning("fetch failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"fetch failed: {exc}"}

        title_fallback = job.get("title") or audio.title or Path(audio.path).stem
        try:
            transcript: Transcript = transcriber.transcribe(
                audio.path, title_fallback=title_fallback
            )
        except Exception as exc:
            logger.exception("transcription failed for %s: %s", job, exc)
            return {"status": "skip", "reason": f"transcribe failed: {exc}"}

        if not transcript.markdown.strip():
            return {"status": "skip", "reason": "empty transcript"}

        kind = _kind_for_job(job, queue_name, voice_queue=config.queue_voice)
        source = job.get("url") or audio.source_url or str(audio.path)
        title = job.get("title") or transcript.title

        capture_kwargs: dict[str, Any] = {
            "title": title,
            "kind": kind,
            "content_md": transcript.markdown,
            "source": source,
            "sha256": transcript.sha256,
            "metadata": {
                "language": transcript.language,
                "duration_s": transcript.duration_s or audio.duration_s,
                "segment_count": transcript.segment_count,
                "note": job.get("note"),
                "message_id": job.get("message_id"),
                **audio.extra_metadata,
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
            transcript.markdown,
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
            "kind": kind,
            "document_id": document_id,
            "chunks": len(chunks),
            "inserted": total_inserted,
            "language": transcript.language,
            "duration_s": transcript.duration_s,
        }
    finally:
        if audio is not None and audio.owned:
            _cleanup_audio(audio.path)


def _cleanup_audio(path: Path) -> None:
    """Remove the temp file. yt-dlp downloads live inside a per-job
    tempdir, so for those we wipe the whole parent."""
    parent = path.parent
    if parent.name.startswith("openbrain-audio-yt-"):
        rmtree(parent, ignore_errors=True)
        return
    try:
        path.unlink()
    except OSError:
        logger.warning("failed to delete temp audio file %s", path)


async def run(config: Config) -> None:
    mcp = McpClient(config.brain_url)
    queue = QueueClient(
        config.redis_url,
        voice_queue=config.queue_voice,
        youtube_queue=config.queue_youtube,
    )
    transcriber = WhisperTranscriber(
        model_name=config.whisper_model,
        compute_type=config.whisper_compute_type,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info(
        "audio worker ready, queues=[%s, %s], model=%s, brain=%s",
        config.queue_voice,
        config.queue_youtube,
        config.whisper_model,
        config.brain_url.split("?", 1)[0]
        + ("?key=…" if "?key=" in config.brain_url else ""),
    )

    try:
        while not stop.is_set():
            result = await queue.pop(timeout_s=5)
            if result is None:
                continue
            queue_name, job = result
            try:
                outcome = await process_one(
                    job,
                    config=config,
                    mcp=mcp,
                    transcriber=transcriber,
                    queue_name=queue_name,
                )
                logger.info("job done (%s): %s", queue_name, outcome)
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
            "MODULE_WORKERS_AUDIO_ENABLED is false — audio worker is idle. "
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
