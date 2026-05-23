# Phase 12.b — Article Worker Go-Live (Operator Guide)

The article worker is fully built and tested locally with stubbed embeddings. To make end-to-end ingestion work against real URLs, the MCP server needs a real OpenRouter API key so the documents-module embedding step actually produces vectors.

This guide walks the 3 minutes of human action to flip live.

## Prerequisites

* `docker compose --profile article up -d` (postgres + mcp-server + redis + worker-article all running).
* You have an OpenRouter account with at least a few cents of credit ([openrouter.ai/keys](https://openrouter.ai/keys)).
* `MODULE_DOCUMENTS_ENABLED=true` and `MODULE_WORKERS_ARTICLE_ENABLED=true` in `.env`.

## Step 1 — Add your OpenRouter key

```bash
# Append to your .env (which is gitignored)
echo "OPENROUTER_API_KEY=sk-or-v1-<your-key-here>" >> .env

# Restart the MCP server so it picks up the new env value
docker compose up -d --force-recreate mcp-server
```

The `mcp-server` container will read `OPENROUTER_API_KEY` on startup and pass it to the embed provider.

## Step 2 — Push a real article URL

```bash
docker compose --profile article exec redis redis-cli LPUSH ingest:article \
  '{"url":"https://en.wikipedia.org/wiki/Markdown","project":"test"}'
```

Optional: add `"note"` and `"message_id"` fields if you want metadata on the captured document (the Telegram bot adds these automatically).

## Step 3 — Watch it process

```bash
docker compose --profile article logs -f worker-article
```

Within ~10 seconds you should see:

```
article worker ready, queue=ingest:article, ...
job done: {'status': 'ingested', 'url': '...', 'document_id': '...', 'chunks': 12, 'inserted': 12}
```

## Step 4 — Verify in Postgres

```bash
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain <<'SQL'
\x
SELECT id, kind, title, source, length(content_md) AS body_len, project
FROM documents
ORDER BY created_at DESC
LIMIT 3;

SELECT count(*) AS chunks_total,
       count(*) FILTER (WHERE embedding IS NOT NULL) AS chunks_embedded
FROM chunks;
SQL
```

The new document should be there, and `chunks_embedded` should equal `chunks_total` (every chunk got its vector).

## Step 5 — Search it from Claude Code or another MCP client

Wire Claude Code at the local MCP if you haven't already (Phase 3):

```bash
claude mcp add --transport http openbrain-local \
  "http://localhost:8080/mcp?key=$(awk -F= '/^BRAIN_KEY=/ {print $2}' .env)"
```

Then ask Claude Code something like: "Use openbrain-local's `search_chunks` tool to find passages about markdown syntax." You should get hits with `document_title: Markdown`, `document_source: https://en.wikipedia.org/wiki/Markdown`, similarity around 0.6–0.9.

## Re-ingestion is free

The worker hashes each article's extracted markdown with SHA-256 and passes that as the `sha256` field to `capture_document`. The MCP tool returns `duplicate: true` if it has already seen that hash, and the worker skips chunk generation entirely — no embedding credits spent on repeat content.

## Troubleshooting

| Symptom in logs | Fix |
|---|---|
| `capture_document tool error: ... OPENROUTER_API_KEY is required` | Step 1 above. Restart the mcp-server. |
| `extract too short` warning | The page's body fell below the 300-char extraction floor. trafilatura did not find substantive content (often a JS-rendered SPA). Either skip the URL or add a fallback to Crawl4AI in a follow-up (out of scope for Phase 12.b). |
| `non-200 for URL` | The site returned 4xx/5xx. The worker logs and acks — paste the URL into a browser to see what happened. |
| `mcp call failed for job` with HTTP 401 | `BRAIN_URL`'s `?key=` does not match `BRAIN_KEY` in the mcp-server's env. Re-source `.env` and recreate both containers. |

## Costs

`text-embedding-3-small` is $0.02 / 1M tokens. A typical 2,000-word article produces 5–10 chunks of ~800 tokens each = ~5,000–8,000 tokens = roughly **$0.0001 per article**. A 50-article day costs less than a cent.

## When you're done

* `git push` if you committed any local config changes.
* The worker keeps running and consuming any new jobs your Telegram bot or other producers push.
* Phase 12.c (PDF worker) is next.
