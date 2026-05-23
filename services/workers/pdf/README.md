# worker-pdf

PDF ingestion worker. Pops jobs off Redis list `ingest:pdf`, extracts the document to markdown via [Docling](https://github.com/DS4SD/docling), chunks the markdown, and calls the MCP server's `capture_document` + `add_chunks` tools.

Phase 12.c. Behind `MODULE_WORKERS_PDF_ENABLED`.

## Job payload

Workers accept either of two payload shapes so the same queue works for multiple producers:

```json
{ "path": "/data/uploads/report.pdf", "title": "optional", "project": "optional" }
```

```json
{ "url": "https://example.com/whitepaper.pdf", "title": "optional" }
```

`title` is optional — the worker derives one from the PDF metadata if absent. `project` and `note` propagate to the captured document's metadata.

The Telegram bot currently pushes `{file_id, file_name, mime_type, message_id}` payloads. Downloading those into a shared volume is a small follow-up that lands once we wire `TELEGRAM_BOT_TOKEN` into the worker; until then the bot's PDF handler is informational only.

## Pipeline

```
LPUSH ingest:pdf → worker-pdf
                     ├── fetcher: resolve {url|path} → /tmp/<sha>.pdf
                     ├── extractor: docling → markdown + page count
                     ├── chunker:  paragraph-based, max 800 tokens, 120 overlap
                     └── mcp client:
                            capture_document(sha256-dedup)
                            add_chunks(batch=8)
```

## Docling cold start

The first time the worker container processes any PDF Docling downloads its layout/OCR models (~500MB). This takes 30–90 seconds and persists in the container's filesystem for the lifetime of that container — restarting the container re-downloads them. For VPS deploys we mount a named volume at `/root/.cache/docling` so the models survive container restarts.

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_WORKERS_PDF_ENABLED` | always | Master flag |
| `BRAIN_URL` | flag on | Full MCP URL with `?key=` |
| `REDIS_URL` | flag on | Redis DSN |
| `WORKER_QUEUE` | optional | Override queue name (default `ingest:pdf`) |
| `WORKER_MAX_PDF_BYTES` | optional | Reject downloads over N bytes; default 20 MB (Telegram cap) |
| `WORKER_MAX_CHUNK_TOKENS` | optional | Default 800 |
| `WORKER_CHUNK_OVERLAP_TOKENS` | optional | Default 120 |

## Local dev

```bash
docker compose --profile pdf build worker-pdf      # ~500MB image
docker compose --profile pdf up -d
```

Then push a job. Easiest is a public PDF:

```bash
docker compose --profile pdf exec redis redis-cli LPUSH ingest:pdf \
  '{"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}'
docker compose --profile pdf logs -f worker-pdf
```

Wait ~10 seconds for Docling cold start on the first job, then a few seconds per subsequent job.

## Layout

```
src/worker_pdf/
├── __init__.py
├── config.py        # env + features.yaml loader
├── chunker.py       # pure paragraph-based markdown chunker (same shape as article)
├── fetcher.py       # url -> local path (httpx) | path -> path (verify exists)
├── extractor.py     # docling wrapper -> ExtractedDocument
├── mcp_client.py    # JSON-RPC wrapper for capture_document + add_chunks
├── queue.py         # redis BRPOP wrapper
└── worker.py        # process_one + main loop
```
