# Phase 12.c — PDF Worker Go-Live (Operator Guide)

The PDF worker is built, tested, and wired into compose. Live ingestion needs three things from you:

1. The MCP server has `OPENROUTER_API_KEY` set (same key from Phase 12.b — if it's already wired you're done with this part).
2. `MODULE_WORKERS_PDF_ENABLED=true` in `.env`.
3. The `pdf` compose profile is up.

Total: ~3 minutes. No model downloads — pymupdf is ready immediately.

## Step 1 — Enable + start

```bash
# 1. Flag on
grep -q '^MODULE_WORKERS_PDF_ENABLED=' .env \
  && sed -i 's|^MODULE_WORKERS_PDF_ENABLED=.*$|MODULE_WORKERS_PDF_ENABLED=true|' .env \
  || echo 'MODULE_WORKERS_PDF_ENABLED=true' >> .env

# 2. Build (~300 MB, ~30 seconds; pymupdf is self-contained).
docker compose --profile pdf build worker-pdf

# 3. Up
docker compose --profile pdf up -d
```

## Step 2 — Push a PDF job

Two payload shapes work. URL mode is the easiest for testing:

```bash
docker compose --profile pdf exec redis redis-cli LPUSH ingest:pdf \
  '{"url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"}'
```

Path mode (when the PDF is already on a shared volume):

```bash
# Drop the PDF into a path the worker container can see.
docker cp /local/path/file.pdf openbrain-worker-pdf:/tmp/file.pdf
docker compose --profile pdf exec redis redis-cli LPUSH ingest:pdf \
  '{"path":"/tmp/file.pdf","project":"reading-list"}'
```

## Step 3 — Watch it process

```bash
docker compose --profile pdf logs -f worker-pdf
```

Expected timeline:

```
pdf worker ready, queue=ingest:pdf, ...
job done: {'status': 'ingested', ..., 'chunks': 4, 'page_count': 1, ...}
```

pymupdf has no model downloads and no warm-up — jobs typically finish in 1–3 seconds for short PDFs and 5–15 seconds for book-length ones. Most of the time is spent embedding chunks via OpenRouter, not extracting.

## Step 4 — Verify in Postgres

```bash
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain <<'SQL'
\x
SELECT title, kind, source, metadata->>'page_count' AS pages,
       length(content_md) AS body_len, project, created_at
FROM documents
WHERE kind = 'pdf'
ORDER BY created_at DESC LIMIT 3;

SELECT count(*) AS chunks_total,
       count(*) FILTER (WHERE embedding IS NOT NULL) AS chunks_embedded
FROM chunks c
JOIN documents d ON d.id = c.document_id
WHERE d.kind = 'pdf';
SQL
```

`chunks_embedded` should equal `chunks_total` for PDF chunks.

## Step 5 — Search from Claude Code

```
"Use search_chunks against openbrain-local to find passages about <topic from your PDF>."
```

Hits come back with `document_kind=pdf` and the original PDF URL or path as the source.

## Size and timeout caps

| Limit | Default | Override |
|---|---|---|
| Max download size | 20 MB | `WORKER_MAX_PDF_BYTES` in `.env` |
| HTTP fetch timeout | 60 s | `WORKER_FETCH_TIMEOUT_S` (not yet exposed; edit fetcher.py) |
| Max chunk tokens | 800 | `WORKER_MAX_CHUNK_TOKENS` |
| Chunk overlap tokens | 120 | `WORKER_CHUNK_OVERLAP_TOKENS` |

The 20 MB cap matches the Telegram Bot API's download limit. For larger PDFs you would currently have to mount the file as a volume and use path-mode payloads.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `fetch failed: file too large` | Bump `WORKER_MAX_PDF_BYTES` or chunk the source PDF. |
| `extract failed: ...` | pymupdf could not parse the file. Corrupted, encrypted, or password-protected PDFs surface here. Open in a viewer to confirm. |
| Scanned PDF with no text layer extracted | pymupdf has no OCR. Pre-process with `ocrmypdf input.pdf output.pdf` then re-push, or swap `PymupdfExtractor` for a Docling-backed extractor in `extractor.py`. The `PdfExtractor` Protocol is the seam. |
| `capture_document tool error: OPENROUTER_API_KEY is required` | Same as Phase 12.b: add the key to `.env` and `docker compose up -d --force-recreate mcp-server`. |
| Container repeatedly exits with code 2 | `refusing to start` means a required env var is missing. Logs show which. |

## Telegram-side PDF handoff

The Telegram bot currently classifies PDF messages and pushes a payload of `{file_id, file_name, mime_type, message_id}`. The worker does not yet know how to download from Telegram (which would require `TELEGRAM_BOT_TOKEN` in the worker). Two paths forward:

1. Add `TELEGRAM_BOT_TOKEN` to the worker and a small `_download_from_telegram(file_id)` helper. Logged as a follow-up task.
2. Telegram bot pre-downloads to a shared volume and pushes a path-mode payload instead. Cleaner separation; touches only the bot.

Either is one weekend of work. Until then, route Telegram-forwarded PDFs through the path-mode handoff yourself or skip them.
