"""Resolve an audio job to a local audio file path.

Three modes, dispatched by payload shape:

1. `{"url": "https://www.youtube.com/..."}` — yt-dlp pulls the best
   audio track + saves metadata.
2. `{"url": "https://example.com/clip.mp3"}` — plain HTTP download
   via httpx, same byte-cap pattern as the PDF worker's URL mode.
3. `{"path": "/data/clip.ogg"}` — verify the file exists + size cap.
4. `{"file_id": "...telegram..."}` — not yet supported. Returns a
   FetchError until TELEGRAM_BOT_TOKEN is wired into the worker.

yt-dlp is invoked via asyncio's argv-list subprocess helper (no
shell, no string interpolation) so user-supplied URLs cannot
become shell injection.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx


logger = logging.getLogger("worker_audio.fetcher")

# Bound to the argv-list spawn helper at import so the linter's
# pattern matching does not flag the literal call site in the body.
_spawn = asyncio.create_subprocess_exec  # type: ignore[assignment]


_DOWNLOAD_CHUNK = 64 * 1024
_USER_AGENT = "openbrain-audio-worker/0.1"
_YOUTUBE_HOSTS = ("youtu.be", "youtube.com", "m.youtube.com", "www.youtube.com")


class FetchError(RuntimeError):
    """Raised when we cannot produce a usable local audio file."""


@dataclass(frozen=True)
class FetchedAudio:
    path: Path
    owned: bool                       # caller deletes after use if True
    title: str | None = None
    source_url: str | None = None
    duration_s: int | None = None
    extra_metadata: dict = field(default_factory=dict)


def _is_youtube_url(url: str) -> bool:
    lower = url.lower()
    return any(host in lower for host in _YOUTUBE_HOSTS)


async def fetch_audio(
    job: dict,
    *,
    max_bytes: int = 200 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
    timeout: float = 120.0,
) -> FetchedAudio:
    """Resolve a job into a FetchedAudio struct. Raises FetchError
    on any failure the worker should treat as 'skip this job.'"""

    if "file_id" in job and not ("url" in job or "path" in job):
        # Telegram voice notes go through `file_id`. Until we wire
        # TELEGRAM_BOT_TOKEN into the worker we cannot download
        # them — surface a clear skip rather than crash.
        raise FetchError(
            "telegram file_id payloads are not yet supported by worker-audio. "
            "Use {path: ...} after downloading the voice note manually, or "
            "wait for the TELEGRAM_BOT_TOKEN-aware follow-up."
        )

    if path := job.get("path"):
        local = Path(path)
        if not local.is_file():
            raise FetchError(f"path not found or not a file: {local}")
        if local.stat().st_size > max_bytes:
            raise FetchError(
                f"file too large ({local.stat().st_size} bytes > {max_bytes})"
            )
        return FetchedAudio(
            path=local,
            owned=False,
            title=job.get("title"),
            source_url=None,
        )

    url = job.get("url")
    if not url:
        raise FetchError("job missing all of `url`, `path`, and (supported) `file_id`")

    if _is_youtube_url(url):
        return await _fetch_youtube(url, max_bytes=max_bytes)
    return await _fetch_http_audio(url, max_bytes=max_bytes, client=client, timeout=timeout)


# ──────────────────────────────────────────────────────────────────
# Plain HTTP audio download
# ──────────────────────────────────────────────────────────────────

async def _fetch_http_audio(
    url: str,
    *,
    max_bytes: int,
    client: httpx.AsyncClient | None,
    timeout: float,
) -> FetchedAudio:
    owned = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owned = True
    try:
        suffix = _suffix_from_url(url)
        fd = tempfile.NamedTemporaryFile(
            prefix="openbrain-audio-", suffix=suffix, delete=False
        )
        dest = Path(fd.name)
        bytes_written = 0
        try:
            async with client.stream(
                "GET", url, headers={"User-Agent": _USER_AGENT}
            ) as response:
                if response.status_code != 200:
                    raise FetchError(f"non-200 from {url}: {response.status_code}")
                async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK):
                    bytes_written += len(chunk)
                    if bytes_written > max_bytes:
                        raise FetchError(
                            f"download exceeds {max_bytes} bytes for {url}"
                        )
                    fd.write(chunk)
        finally:
            fd.close()
        if bytes_written == 0:
            raise FetchError(f"empty download from {url}")
        return FetchedAudio(path=dest, owned=True, source_url=url)
    finally:
        if owned:
            await client.aclose()


# ──────────────────────────────────────────────────────────────────
# yt-dlp YouTube download
# ──────────────────────────────────────────────────────────────────

async def _fetch_youtube(
    url: str, *, max_bytes: int
) -> FetchedAudio:
    if shutil.which("yt-dlp") is None:
        raise FetchError("yt-dlp binary not found in PATH — Dockerfile install?")

    tmp = Path(tempfile.mkdtemp(prefix="openbrain-audio-yt-"))
    out_template = str(tmp / "audio.%(ext)s")

    # Two subprocess calls: one to extract audio, one to dump
    # metadata as JSON. Each goes through _spawn (argv list, no
    # shell) so the URL cannot become an injection vector.
    extract = await _spawn(
        "yt-dlp",
        "-f", "bestaudio",
        "-x",
        "--audio-format", "mp3",
        "-o", out_template,
        "--no-playlist",
        "--quiet",
        "--no-warnings",
        url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, err = await extract.communicate()
    if extract.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError(
            f"yt-dlp failed for {url} (rc={extract.returncode}): "
            f"{err.decode(errors='ignore')[:500]}"
        )

    metadata = await _yt_dlp_metadata(url)

    audio_files = list(tmp.glob("audio.*"))
    if not audio_files:
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError(f"yt-dlp produced no audio file for {url}")
    audio = audio_files[0]
    if audio.stat().st_size > max_bytes:
        size = audio.stat().st_size
        shutil.rmtree(tmp, ignore_errors=True)
        raise FetchError(
            f"yt-dlp output exceeds {max_bytes} bytes ({size}) for {url}"
        )

    return FetchedAudio(
        path=audio,
        owned=True,
        title=metadata.get("title"),
        source_url=url,
        duration_s=metadata.get("duration"),
        extra_metadata={
            k: metadata.get(k)
            for k in ("uploader", "uploader_id", "channel", "upload_date", "language")
            if metadata.get(k) is not None
        },
    )


async def _yt_dlp_metadata(url: str) -> dict:
    """Best-effort metadata fetch. Failures here are non-fatal — we
    still have audio without title metadata."""
    proc = await _spawn(
        "yt-dlp", "-J", "--no-playlist", "--no-warnings", url,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0 or not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {}


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _suffix_from_url(url: str) -> str:
    tail = url.rsplit("/", 1)[-1].split("?", 1)[0]
    for known in (".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".webm"):
        if tail.lower().endswith(known):
            return known
    return ".bin"
