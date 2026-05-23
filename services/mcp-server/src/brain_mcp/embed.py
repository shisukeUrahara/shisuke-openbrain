"""Embedding provider abstraction.

Two backends behind one `embed(text) -> list[float]` interface:

* OpenRouter (`text-embedding-3-small`, 1536-dim) — default, cloud.
* Ollama (`bge-m3`, 1024-dim) — local-first, opt-in via
  `EMBED_PROVIDER=ollama`.

The dimension lock is enforced at the SQL layer (`vector(1536)`).
Switching providers to one with a different output dimension requires
a migration script that re-embeds every row — see
`plan/DECISIONS.md`.
"""
from __future__ import annotations

import httpx

from .config import Config


_OPENROUTER_URL = "https://openrouter.ai/api/v1/embeddings"
_OPENROUTER_MODEL = "openai/text-embedding-3-small"
_OLLAMA_MODEL = "bge-m3"


class EmbeddingError(RuntimeError):
    """Raised when the upstream embedding provider returns a non-2xx
    response. Carries the provider name, status code, and the raw body
    so the failure surfaces to the MCP client instead of vanishing."""


async def embed(text: str, *, config: Config, timeout: float = 30.0) -> list[float]:
    """Return the embedding for `text` using the configured provider."""
    provider = config.embed_provider
    if provider == "openrouter":
        return await _embed_openrouter(text, config=config, timeout=timeout)
    if provider == "ollama":
        return await _embed_ollama(text, config=config, timeout=timeout)
    raise EmbeddingError(f"unknown embed provider: {provider!r}")


async def _embed_openrouter(
    text: str, *, config: Config, timeout: float
) -> list[float]:
    if not config.openrouter_api_key:
        raise EmbeddingError("OPENROUTER_API_KEY is required for openrouter provider")

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            _OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {config.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": _OPENROUTER_MODEL, "input": text},
        )

    if response.status_code != 200:
        raise EmbeddingError(
            f"openrouter embeddings failed: status={response.status_code} body={response.text}"
        )
    payload = response.json()
    try:
        return payload["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise EmbeddingError(
            f"unexpected openrouter response shape: {payload!r}"
        ) from exc


async def _embed_ollama(text: str, *, config: Config, timeout: float) -> list[float]:
    url = config.ollama_url.rstrip("/") + "/api/embeddings"
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(url, json={"model": _OLLAMA_MODEL, "prompt": text})

    if response.status_code != 200:
        raise EmbeddingError(
            f"ollama embeddings failed: status={response.status_code} body={response.text}"
        )
    payload = response.json()
    try:
        return payload["embedding"]
    except (KeyError, TypeError) as exc:
        raise EmbeddingError(
            f"unexpected ollama response shape: {payload!r}"
        ) from exc
