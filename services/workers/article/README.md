# worker-article

Article ingestion worker. Pops URLs off Redis list `ingest:article`, fetches them, extracts a clean markdown body via trafilatura, chunks the markdown into ~800-token passages, and calls the MCP server's `capture_document` + `add_chunks` tools.

Phase 12.b. Behind `MODULE_WORKERS_ARTICLE_ENABLED`.

## Pipeline

```
                                  ┌──────────────────┐
[telegram-bot] LPUSH ingest:article → │                  │
                                  │   worker-article │   trafilatura → markdown
[any producer] LPUSH ingest:article → │  (BRPOP loop)    │   chunker     → chunks[]
                                  └────────┬─────────┘
                                           │
                                           ▼
                                  ┌──────────────────┐
                                  │   MCP server     │
                                  │  capture_document│ — dedupes by SHA-256
                                  │  add_chunks      │ — idempotent per index
                                  └──────────────────┘
```

## Dedup contract

Every job carries `{url, note?, message_id?}`. The worker:

1. Computes `sha256(content_md)` after extraction.
2. Calls `capture_document(..., sha256=...)`.
3. If the MCP returns `duplicate: true`, skips chunk generation entirely — the document was already ingested and re-chunking would only burn embedding credits.
4. Otherwise chunks the markdown and posts the chunks in batches of 8.

## Layout

```
src/worker_article/
├── __init__.py
├── config.py        # env + features.yaml; idle-mode + runtime modes
├── chunker.py       # pure paragraph-based markdown chunker
├── fetcher.py       # trafilatura wrapper, returns {title, markdown, sha256}
├── mcp_client.py    # JSON-RPC wrapper for capture_document + add_chunks
├── queue.py         # Redis BRPOP wrapper
└── worker.py        # process_one() + main() loop
```

`chunker.py` is pure — no I/O. Easy to unit-test with known inputs.
`fetcher.py` is impure (network) but accepts an injected `httpx.AsyncClient` for tests.
`worker.py` is the only file that does `BRPOP`.

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_WORKERS_ARTICLE_ENABLED` | always | Master flag |
| `BRAIN_URL` | flag on | Full MCP URL with `?key=` |
| `REDIS_URL` | flag on | Redis DSN |
| `WORKER_QUEUE` | optional | Override the queue name (default `ingest:article`) |
| `LOG_LEVEL` | optional | INFO by default |

## Local dev

```bash
# Build
docker compose --profile article build worker-article

# Add to .env:
MODULE_WORKERS_ARTICLE_ENABLED=true

# Bring up
docker compose --profile article up -d
docker compose logs -f worker-article
```

Then push a job:

```bash
docker compose exec redis redis-cli LPUSH ingest:article \
  '{"url": "https://example.com/post"}'
```

Wait a few seconds, then check it landed:

```bash
psql "$DATABASE_URL" -c "select kind, title, source from documents order by created_at desc limit 5"
psql "$DATABASE_URL" -c "select count(*) from chunks"
```
