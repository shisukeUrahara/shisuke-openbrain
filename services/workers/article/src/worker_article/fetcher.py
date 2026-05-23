"""Article fetcher wrapping trafilatura.

Returns a normalised ExtractedArticle struct. Network I/O is async
via httpx so the worker stays single-threaded; trafilatura's
extraction work is sync but fast enough to run inline.

Failure modes are explicit. If the page does not yield enough body
text to be useful (< 300 chars after extraction) the fetcher
returns None — the worker logs and acks the job rather than retry
forever.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import httpx
import trafilatura


logger = logging.getLogger("worker_article.fetcher")

_MIN_BODY_CHARS = 300
_USER_AGENT = "openbrain-article-worker/0.1 (+https://github.com/shisukeUrahara/shisuke-openbrain)"


@dataclass(frozen=True)
class ExtractedArticle:
    url: str
    title: str
    markdown: str
    sha256: str


async def fetch_article(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    timeout: float = 30.0,
) -> ExtractedArticle | None:
    """Fetch and extract a single URL. Returns None on extraction
    failure (page missing, body too short, network error)."""
    owned = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout, follow_redirects=True)
        owned = True
    try:
        try:
            response = await client.get(
                url,
                headers={"User-Agent": _USER_AGENT},
            )
        except httpx.HTTPError as exc:
            logger.warning("fetch failed for %s: %s", url, exc)
            return None

        if response.status_code != 200:
            logger.warning("non-200 for %s: %d", url, response.status_code)
            return None

        html = response.text
        markdown = trafilatura.extract(
            html,
            output_format="markdown",
            include_links=True,
            include_images=False,
            with_metadata=False,
        )
        if not markdown or len(markdown) < _MIN_BODY_CHARS:
            logger.warning("extract too short for %s: %d chars", url, len(markdown or ""))
            return None

        meta = trafilatura.extract_metadata(html)
        title = (meta.title if meta and meta.title else None) or _fallback_title(url)
        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return ExtractedArticle(url=url, title=title, markdown=markdown, sha256=sha)
    finally:
        if owned:
            await client.aclose()


def _fallback_title(url: str) -> str:
    return url.rsplit("/", 1)[-1] or url
