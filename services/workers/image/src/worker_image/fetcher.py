"""Resolve an image job to raw image bytes + mime type.

Same payload-shape pattern as the other workers:

- `{"url": "https://..."}`  -> httpx download into memory
- `{"path": "/data/img.jpg"}` -> read from disk
- `{"file_id": "..."}`        -> not supported yet (TELEGRAM_BOT_TOKEN)

The image worker returns bytes rather than a path because the
analyzer base64-encodes the bytes into the VLM request anyway —
no need to write a temp file.
"""
from __future__ import annotations

import logging
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path

import httpx


logger = logging.getLogger("worker_image.fetcher")


_USER_AGENT = "openbrain-image-worker/0.1"
_DOWNLOAD_CHUNK = 64 * 1024


class FetchError(RuntimeError):
    """Raised when we cannot produce a usable image."""


@dataclass(frozen=True)
class FetchedImage:
    data: bytes
    mime: str
    source_url: str | None = None
    caption: str | None = None
    extra_metadata: dict = field(default_factory=dict)


async def fetch_image(
    job: dict,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> FetchedImage:
    """Resolve a job into a FetchedImage struct."""

    if "file_id" in job and not ("url" in job or "path" in job):
        raise FetchError(
            "telegram file_id payloads are not yet supported by worker-image. "
            "Use {path: ...} after downloading the photo manually, or wait for "
            "the TELEGRAM_BOT_TOKEN-aware follow-up."
        )

    if path := job.get("path"):
        local = Path(path)
        if not local.is_file():
            raise FetchError(f"path not found or not a file: {local}")
        size = local.stat().st_size
        if size > max_bytes:
            raise FetchError(f"file too large ({size} bytes > {max_bytes})")
        return FetchedImage(
            data=local.read_bytes(),
            mime=_guess_mime(local.name) or "image/jpeg",
            source_url=None,
            caption=job.get("caption"),
        )

    url = job.get("url")
    if not url:
        raise FetchError("job missing all of `url`, `path`, and (supported) `file_id`")

    return await _fetch_url(url, max_bytes=max_bytes, client=client, timeout=timeout, caption=job.get("caption"))


async def _fetch_url(
    url: str,
    *,
    max_bytes: int,
    client: httpx.AsyncClient | None,
    timeout: float,
    caption: str | None,
) -> FetchedImage:
    owned = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owned = True
    try:
        buf = bytearray()
        mime = "image/jpeg"
        async with client.stream(
            "GET", url, headers={"User-Agent": _USER_AGENT}
        ) as response:
            if response.status_code != 200:
                raise FetchError(f"non-200 from {url}: {response.status_code}")
            ct = response.headers.get("content-type", "")
            if ct.startswith("image/"):
                mime = ct.split(";", 1)[0].strip()
            async for chunk in response.aiter_bytes(_DOWNLOAD_CHUNK):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise FetchError(
                        f"download exceeds {max_bytes} bytes for {url}"
                    )
        if not buf:
            raise FetchError(f"empty download from {url}")
        return FetchedImage(
            data=bytes(buf), mime=mime, source_url=url, caption=caption
        )
    finally:
        if owned:
            await client.aclose()


def _guess_mime(filename: str) -> str | None:
    mime, _ = mimetypes.guess_type(filename)
    if mime and mime.startswith("image/"):
        return mime
    return None
