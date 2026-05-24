# obsidian-sync

Mirrors every Open Brain `documents` row to a markdown file in a vault directory, so you get a human-readable, Obsidian-openable, git-syncable copy of everything the ingestion workers capture.

Phase 13. Behind `MODULE_OBSIDIAN_MIRROR_ENABLED`.

## How it works

```
documents INSERT
   │  (Postgres trigger documents_notify_trigger)
   ▼
NOTIFY new_document {id, title, kind, project}
   │  (asyncpg LISTEN)
   ▼
obsidian-sync listener
   │  fetch the full row, render frontmatter + content_md
   ▼
/vault/<project>/<kind>/<safe-title>.md
   │  (separate cron container, every 15 min)
   ▼
git add -A && git commit && git push   →  private GitHub vault repo
   │
   ▼
Obsidian Desktop / Mobile (via the Obsidian Git plugin or Working Copy)
```

The listener also does a **backfill sweep on startup** — any document that exists in Postgres but has no corresponding file in the vault gets written. That covers documents captured while the listener was down, and the initial population of an existing brain.

## Vault layout

```
/vault/
├── <project or "inbox">/
│   ├── article/
│   │   └── How_pgvector_HNSW_works.md
│   ├── pdf/
│   │   └── Q4_strategy_memo.md
│   ├── youtube/
│   ├── voice/
│   └── image/
```

Each note carries YAML frontmatter so Obsidian and Dataview can query it:

```markdown
---
doc_id: 7f3c…
kind: article
source: https://example.com/post
project: ax
created: 2026-05-23T12:00:00+00:00
---

<the document's content_md>
```

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_OBSIDIAN_MIRROR_ENABLED` | always | Master flag |
| `DATABASE_URL` | flag on | Postgres DSN (listener connects directly, not via MCP) |
| `VAULT_DIR` | optional | Where to write notes; default `/vault` |
| `VAULT_BACKFILL_ON_START` | optional | `true` (default) runs the catch-up sweep on boot |

## Git sync

The listener only writes files. A separate lightweight cron container (declared in docker-compose) runs `git add/commit/push` against `/vault` every 15 minutes. To wire it:

1. `git init` the vault directory and add a private GitHub remote.
2. Mount your deploy key / token so the cron container can push.
3. On your laptop, clone the same repo and open it in Obsidian.

The git plumbing is documented in `docs/phase-13-go-live.md`. The mirror works without git — you just lose the off-box sync.

## Layout

```
src/obsidian_sync/
├── __init__.py
├── config.py        # env + features.yaml
├── render.py        # pure: document row -> (relative path, file text)
├── db.py            # asyncpg connect + LISTEN + fetch helpers
└── main.py          # backfill sweep + LISTEN loop
```

`render.py` is pure (no I/O) so the path-building and frontmatter logic is unit-tested without a database or filesystem.
