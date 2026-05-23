"""Unit tests for worker_article.fetcher.

Mocks HTTP at the httpx wire layer so we exercise the trafilatura
extraction path against a known fixture HTML and the failure paths
without any network.

Layer: unit
Phase: 12.b
Run:   pytest services/workers/article/tests/unit/test_fetcher.py -v
"""
from __future__ import annotations

import httpx
import pytest

from worker_article.fetcher import ExtractedArticle, fetch_article


_FIXTURE_HTML = """\
<!DOCTYPE html>
<html>
<head><title>The Sample Post Title</title></head>
<body>
<article>
<h1>The Sample Post Title</h1>
<p>This is the first paragraph of an article designed to be long
enough that trafilatura keeps it. We want to be sure the extractor
actually sees substantive prose so it does not bail with the
"too short" branch our worker honors.</p>

<p>This is the second paragraph. It contains a link to
<a href="https://example.org/other">somewhere else</a> and continues
to ramble for a few sentences so the body crosses the 300-char
threshold the fetcher requires.</p>

<p>Third paragraph with even more text to push us well clear of any
minimum-length check. The fetcher should produce a markdown body of
several hundred characters at least.</p>
</article>
</body>
</html>
"""


def _client_with_handler(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────

async def test_fetch_returns_extracted_article():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_FIXTURE_HTML)

    async with _client_with_handler(handler) as client:
        article = await fetch_article("https://example.com/post", client=client)

    assert article is not None
    assert isinstance(article, ExtractedArticle)
    assert article.url == "https://example.com/post"
    assert "Sample Post" in article.title
    assert "first paragraph" in article.markdown
    assert len(article.sha256) == 64


async def test_sha256_is_deterministic_for_same_markdown():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=_FIXTURE_HTML)

    async with _client_with_handler(handler) as client:
        a = await fetch_article("https://x.com/a", client=client)
        b = await fetch_article("https://x.com/b", client=client)
    assert a is not None and b is not None
    assert a.sha256 == b.sha256


# ──────────────────────────────────────────────────────────────────
# Failure paths
# ──────────────────────────────────────────────────────────────────

async def test_non_200_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    async with _client_with_handler(handler) as client:
        article = await fetch_article("https://x.com", client=client)
    assert article is None


async def test_too_short_body_returns_none():
    """Pages whose extracted body is below the floor are skipped."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body><p>tiny</p></body></html>")

    async with _client_with_handler(handler) as client:
        article = await fetch_article("https://x.com", client=client)
    assert article is None


async def test_network_error_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dns")

    async with _client_with_handler(handler) as client:
        article = await fetch_article("https://nope.invalid", client=client)
    assert article is None
