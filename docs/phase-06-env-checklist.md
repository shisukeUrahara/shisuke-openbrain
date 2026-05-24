# Phase 6 — Production Environment Variable Checklist

Set these on the Coolify **Application** (not the database resource).
The server reads config once at startup via `brain_mcp.config.load_config()`;
nothing reads `os.environ` outside that loader.

## Required

| Var | Example | Why |
|---|---|---|
| `DATABASE_URL` | `postgresql://postgres:<pw>@postgresql-openbrain-db:5432/openbrain` | Internal container DSN from Phase 5 Step 5. The server opens its pool at startup and **fails fast** if this is wrong — Coolify will show the app unhealthy. |
| `BRAIN_KEY` | `<openssl rand -hex 32>` | Bearer key. Clients send it as `x-brain-key` header or `?key=`. `/health` is the only unauthenticated route. |
| `EMBED_PROVIDER` | `openrouter` | Selects the embedding backend. |
| `OPENROUTER_API_KEY` | `sk-or-v1-…` | Required when `EMBED_PROVIDER=openrouter`. Without it, capture/search return a 401 from the embedding call (the rest of the API still works). |

## Module flags — all default false

Leave every module off at first deploy. Enable one at a time, each per
its own go-live doc, redeploying after each flip.

| Var | Enables |
|---|---|
| `MODULE_DOCUMENTS_ENABLED` | `capture_document`, `add_chunks`, `search_chunks` |
| `MODULE_GRAPHIFY_ENABLED` | `export_project_corpus` (needs documents too) |
| `MODULE_TELEGRAM_BOT_ENABLED` | Telegram capture bot (separate service) |
| `MODULE_WORKERS_ARTICLE_ENABLED` | Article ingestion worker |
| `MODULE_WORKERS_PDF_ENABLED` | PDF ingestion worker |
| `MODULE_WORKERS_AUDIO_ENABLED` | Audio/YouTube ingestion worker |
| `MODULE_WORKERS_IMAGE_ENABLED` | Image OCR/description worker |
| `MODULE_OBSIDIAN_MIRROR_ENABLED` | Obsidian vault mirror |
| `MODULE_N8N_SCHEDULER_ENABLED` | n8n cron workflows |

## Verify the env took effect

After deploy, `GET /health` echoes the resolved config:

```json
{
  "ok": true,
  "version": "0.1.0",
  "embed_provider": "openrouter",
  "modules": { "documents": false, "graphify": false, ... }
}
```

- `embed_provider` must match `EMBED_PROVIDER`.
- every `modules.*` must be `false` on first deploy.

## Secrets hygiene

- Never bake any of these into the repo, the Dockerfile, or compose.
  They live only in Coolify's env store.
- Rotating `BRAIN_KEY` requires updating every client (Phase 7) — do it
  deliberately.
- The `secret-scanner` agent runs before commits to catch accidental
  leaks of `sk-or-v1-…` keys or hex `BRAIN_KEY` values.
