# Phase 12.e — Image Worker Go-Live (Operator Guide)

Image worker needs three things to go live:

1. `OPENROUTER_API_KEY` set on **both** the MCP server (for embedding) and the worker (for the VLM call). Same key, two containers read it.
2. `MODULE_WORKERS_IMAGE_ENABLED=true` in `.env`.
3. The `image` compose profile is up.

Total: ~2 minutes. No models to download.

## Step 1 — Enable + start

```bash
grep -q '^MODULE_WORKERS_IMAGE_ENABLED=' .env \
  && sed -i 's|^MODULE_WORKERS_IMAGE_ENABLED=.*$|MODULE_WORKERS_IMAGE_ENABLED=true|' .env \
  || echo 'MODULE_WORKERS_IMAGE_ENABLED=true' >> .env

# Confirm OPENROUTER_API_KEY is set:
grep '^OPENROUTER_API_KEY=' .env || echo "MISSING: add OPENROUTER_API_KEY=sk-or-v1-... to .env"

# Small build (~150 MB):
docker compose --profile image build worker-image

docker compose --profile image up -d
```

## Step 2 — Push an image

URL mode (any public JPEG/PNG):

```bash
docker compose --profile image exec redis redis-cli LPUSH ingest:image \
  '{"url":"https://upload.wikimedia.org/wikipedia/commons/4/47/PNG_transparency_demonstration_1.png","caption":"transparency demo"}'
```

Path mode (drop the image into the container first):

```bash
docker cp ~/screenshots/receipt.jpg openbrain-worker-image:/tmp/receipt.jpg
docker compose --profile image exec redis redis-cli LPUSH ingest:image \
  '{"path":"/tmp/receipt.jpg","caption":"lunch receipt"}'
```

## Step 3 — Watch it process

```bash
docker compose --profile image logs -f worker-image
```

Expected timeline (no model warm-up):

```
image worker ready, queue=ingest:image, model=qwen/qwen-2.5-vl-7b-instruct, ...
job done: {'status': 'ingested', ..., 'chunks': 1}
```

Most images finish in 3–8 seconds — the wait is the round-trip to OpenRouter's VLM endpoint plus the embedding step.

## Step 4 — Verify in Postgres

```bash
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain <<'SQL'
\x
SELECT title, kind, source, metadata->>'caption' AS caption,
       metadata->>'mime' AS mime, length(content_md) AS body_len,
       created_at
FROM documents
WHERE kind = 'image'
ORDER BY created_at DESC LIMIT 5;

SELECT d.title, c.content
FROM chunks c JOIN documents d ON d.id = c.document_id
WHERE d.kind = 'image'
ORDER BY c.created_at DESC LIMIT 5;
SQL
```

Each captured image's `content_md` follows this template:

```markdown
> User caption: <text>          (only if you set caption)

## Extracted Text
<OCR of any visible text — "None" if no text>

## Description
<2-4 sentence retrieval-friendly description>
```

## Step 5 — Search from Claude Code

Once you have a few images in the brain:

```
"Use search_chunks against openbrain-local to find images that mention <topic>."
```

You'll get hits with `document_kind=image`, the original URL or path, and the section of the OCR/description that matched.

## Vision model selection

OpenRouter exposes many vision models. Trade-offs:

| Model | Cost / image | Quality | Notes |
|---|---|---|---|
| `qwen/qwen-2.5-vl-7b-instruct` | ~$0.001 | very good for OCR + descriptions | default |
| `qwen/qwen2-vl-72b-instruct` | ~$0.003 | best OCR | heavier |
| `meta-llama/llama-3.2-11b-vision-instruct` | ~$0.0015 | strong general description | weaker OCR |
| `anthropic/claude-3-5-haiku-20241022` | ~$0.003 | excellent description, structured outputs | not always best at small text |

Set via `.env`:
```
WORKER_VISION_MODEL=qwen/qwen2-vl-72b-instruct
```

Restart: `docker compose --profile image up -d --force-recreate worker-image`.

## Limits

| Limit | Default | Override |
|---|---|---|
| Max download size | 10 MB | `WORKER_MAX_IMAGE_BYTES` |
| Max chunk tokens | 800 | `WORKER_MAX_CHUNK_TOKENS` |
| Chunk overlap tokens | 120 | `WORKER_CHUNK_OVERLAP_TOKENS` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `vision analysis failed: status=401` | OPENROUTER_API_KEY wrong or missing. Recreate the container after fixing `.env`. |
| `vision analysis failed: status=429` | OpenRouter rate limit. Wait, or top up credits. |
| `empty VLM response` | Model misbehaved. Try a different `WORKER_VISION_MODEL`. |
| `fetch failed: file too large` | Bump `WORKER_MAX_IMAGE_BYTES`. Telegram caps at 20 MB anyway. |
| `not yet supported: telegram file_id` | Documented gap — same as the audio and PDF workers. Path-mode payloads only until the Telegram-token handoff lands. |
| `capture_document tool error: OPENROUTER_API_KEY` | The MCP server needs the same key for embedding. Add to `.env` and recreate mcp-server. |

## Costs

- VLM call: ~$0.001 per image (qwen-2.5-vl-7b-instruct).
- Embedding: ~$0.0001 (OCR text is usually short).
- Total: about a tenth of a cent per image. 100 images/day = ~$0.10/day = $3/month.

## Telegram handoff

Same gap as the other workers — bot pushes `{file_id, caption, message_id}` for photos but the worker has no `TELEGRAM_BOT_TOKEN` yet. Route via `{path}` for now.
