# worker-pdf

PDF ingestion worker. Pops jobs off Redis list `ingest:pdf`, extracts the document to markdown via [pymupdf](https://pymupdf.readthedocs.io/), chunks the markdown, and calls the MCP server's `capture_document` + `add_chunks` tools.

Phase 12.c. Behind `MODULE_WORKERS_PDF_ENABLED`.

## Why pymupdf, not Docling

pymupdf gives us text-layer extraction with reasonable layout preservation at **~5 MB of dependencies** instead of Docling's **~3 GB of PyTorch + transformers**. For a personal-brain workload (articles, reports, papers, ebooks) the extraction quality is comparable and the image build drops from ~5 minutes to ~30 seconds. The trade-off:

- ✅ Text-layer PDFs (95% of real-world content): markdown, headers, lists, basic tables.
- ❌ Scanned PDFs without a text layer: pymupdf extracts nothing → worker logs "extract too short" and skips. Pre-OCR with `ocrmypdf` if you need them, or swap the extractor back to Docling (the `PdfExtractor` Protocol is the seam).

## Job payload

Workers accept either of two payload shapes so the same queue works for multiple producers:

```json
{ "path": "/data/uploads/report.pdf", "title": "optional", "project": "optional" }
```

```json
{ "url": "https://example.com/whitepaper.pdf", "title": "optional" }
```

`title` is optional — the worker derives one from the PDF metadata if absent, falling back to the file's stem. `project` and `note` propagate to the captured document's metadata.

The Telegram bot currently pushes `{file_id, file_name, mime_type, message_id}` payloads. Downloading those into a shared volume is a small follow-up that lands once we wire `TELEGRAM_BOT_TOKEN` into the worker; until then the bot's PDF handler is informational only.

## Pipeline

```
LPUSH ingest:pdf → worker-pdf
                     ├── fetcher: resolve {url|path} → /tmp/<sha>.pdf
                     ├── extractor: pymupdf → markdown + page count
                     ├── chunker:  paragraph-based, max 800 tokens, 120 overlap
                     └── mcp client:
                            capture_document(sha256-dedup)
                            add_chunks(batch=8)
```

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
docker compose --profile pdf build worker-pdf      # ~300 MB image, ~30s build
docker compose --profile pdf up -d
```

Then push a job. Easiest is a public PDF:

```bash
docker compose --profile pdf exec redis redis-cli LPUSH ingest:pdf \
  '{"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}'
docker compose --profile pdf logs -f worker-pdf
```

No cold-start delay — pymupdf is ready immediately.

## Layout

```
src/worker_pdf/
├── __init__.py
├── config.py        # env + features.yaml loader
├── chunker.py       # pure paragraph-based markdown chunker
├── fetcher.py       # url -> local path (httpx) | path -> path (verify)
├── extractor.py     # pymupdf wrapper behind PdfExtractor Protocol
├── mcp_client.py    # JSON-RPC wrapper for capture_document + add_chunks
├── queue.py         # redis BRPOP wrapper
└── worker.py        # process_one + main loop
```
