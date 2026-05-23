"""Fetch a PDF onto local disk given a job payload.

Supports two payload shapes:
  - {"path": "/abs/or/rel.pdf"} — already on disk, return as-is.
  - {"url":  "https://.../file.pdf"} — download via httpx into a temp
    file, return the temp path. Caller is responsible for cleanup
    (worker.process_one removes the temp file in a finally block).

Rejects downloads that exceed `max_bytes` (default 20 MB) so a hostile
URL cannot fill the worker's disk. Streams in 64 KB chunks so memory
stays bounded regardless of PDF size.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path

import httpx


logger = logging.getLogger("worker_pdf.fetcher")

_DOWNLOAD_CHUNK = 64 * 1024  # 64 KB
_USER_AGENT = "openbrain-pdf-worker/0.1"


class FetchError(RuntimeError):
    """Raised when the fetcher cannot produce a usable local PDF."""


async def fetch_pdf(
    job: dict,
    *,
    max_bytes: int = 20 * 1024 * 1024,
    client: httpx.AsyncClient | None = None,
    timeout: float = 60.0,
) -> tuple[Path, bool]:
    """Resolve `job` to a local file path.

    Returns (path, owned). `owned` is True when we created the file
    in a temp dir and the caller must delete it after use.
    """
    if path := job.get("path"):
        local = Path(path)
        if not local.is_file():
            raise FetchError(f"path not found or not a file: {local}")
        if local.stat().st_size > max_bytes:
            raise FetchError(
                f"file too large ({local.stat().st_size} bytes > {max_bytes})"
            )
        return local, False

    url = job.get("url")
    if not url:
        raise FetchError("job missing both `path` and `url`")

    owned = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owned = True
    try:
        # tempfile.NamedTemporaryFile keeps the handle open; we close
        # it explicitly because Docling re-opens by path.
        suffix = _suffix_from_url(url)
        fd = tempfile.NamedTemporaryFile(
            prefix="openbrain-pdf-", suffix=suffix, delete=False
        )
        dest = Path(fd.name)
        bytes_written = 0
        try:
            async with client.stream(
                "GET", url, headers={"User-Agent": _USER_AGENT}
            ) as response:
                if response.status_code != 200:
                    raise FetchError(
                        f"non-200 from {url}: {response.status_code}"
                    )
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
        return dest, True
    finally:
        if owned:
            await client.aclose()


def _suffix_from_url(url: str) -> str:
    tail = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if tail.lower().endswith(".pdf"):
        return ".pdf"
    return ".bin"
