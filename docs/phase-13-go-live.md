# Phase 13 — Obsidian Vault Mirror Go-Live (Operator Guide)

The mirror turns every captured document into a markdown file you can open in Obsidian and sync across devices via git. Two pieces: the `obsidian-sync` listener (writes files) and the `obsidian-git` sidecar (pushes them to a remote).

## Step 1 — Apply the notify trigger

The listener relies on a Postgres NOTIFY trigger. Apply it once:

```bash
# Local dev
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain \
  -f sql/modules/obsidian/020_notify_document.sql

# Production (Coolify DB terminal) — paste the file's contents.
```

It is idempotent; re-applying is safe.

## Step 2 — Enable + start the listener

```bash
grep -q '^MODULE_OBSIDIAN_MIRROR_ENABLED=' .env \
  && sed -i 's|^MODULE_OBSIDIAN_MIRROR_ENABLED=.*$|MODULE_OBSIDIAN_MIRROR_ENABLED=true|' .env \
  || echo 'MODULE_OBSIDIAN_MIRROR_ENABLED=true' >> .env

docker compose --profile obsidian build obsidian-sync
docker compose --profile obsidian up -d obsidian-sync obsidian-git
```

On startup the listener runs a **backfill sweep**: every document already in Postgres that has no file in the vault gets written. Then it LISTENs and mirrors new captures live.

## Step 3 — Confirm files are landing

```bash
docker compose --profile obsidian logs -f obsidian-sync
# expect: "backfill complete: N new note(s) written" then "listening on new_document"

docker compose --profile obsidian exec obsidian-sync find /vault -type f
```

Each note:

```markdown
---
doc_id: <uuid>
kind: article
source: https://example.com/x
project: ax
created: 2026-05-23T12:00:00+00:00
---

<the document body>
```

Layout: `/vault/<project|inbox>/<kind>/<safe-title>.md`.

## Step 4 — Wire git sync to a private repo

The `obsidian-git` sidecar runs `git add/commit/push` against `/vault` every 15 minutes — but only once the vault is a git repo with a remote. Set that up:

```bash
# Open a shell in the sidecar (alpine/git).
docker compose --profile obsidian exec obsidian-git sh

# Inside the container:
cd /vault
git init
git config user.email "brain@yourdomain.com"
git config user.name "Open Brain"
git remote add origin git@github.com:<you>/openbrain-vault.git   # private repo
# Provide push credentials — easiest is a deploy token in the URL:
#   git remote add origin https://<token>@github.com/<you>/openbrain-vault.git
git add -A && git commit -m "initial vault" && git push -u origin HEAD
exit
```

After that, the sidecar's loop commits + pushes any changes every 15 minutes automatically. No remote configured = the sidecar commits locally but skips the push (no error).

> **Security:** the deploy token sits inside the named volume's `.git/config`, not in the repo or the image. Use a scoped, repo-only token. Rotate if the host is compromised.

## Step 5 — Open in Obsidian

- **Desktop:** clone the vault repo locally, "Open folder as vault" in Obsidian, install the community **Obsidian Git** plugin to pull on a schedule.
- **iOS:** use Working Copy to clone the repo, then point Obsidian Mobile at the Working Copy folder.
- **Android:** Termux + git, or the Obsidian Git plugin (limited on mobile).

You now have two surfaces on the same data: the Postgres rows the AI queries, and a human-browsable markdown vault with folders, tags, backlinks, and graph view.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `MODULE_OBSIDIAN_MIRROR_ENABLED` | false | Master flag |
| `DATABASE_URL` | (compose default) | Postgres DSN — connects directly for LISTEN |
| `VAULT_DIR` | `/vault` | Where notes are written |
| `VAULT_BACKFILL_ON_START` | true | Run the catch-up sweep on boot |

## Troubleshooting

| Symptom | Fix |
|---|---|
| No files appear on insert | Trigger not applied. Re-run Step 1, confirm `SELECT count(*) FROM pg_trigger WHERE tgname='documents_notify_trigger'` returns 1. |
| Listener logs "refusing to start" | `DATABASE_URL` missing. Check the compose env / `.env`. |
| Backfill writes nothing but DB has docs | Files already exist in the vault (backfill uses overwrite=false). Delete the vault volume to force a full re-write: `docker volume rm openbrain_vault` then restart. |
| git sidecar never pushes | The vault is not a git repo, or `origin` is unset. Do Step 4. |
| Push fails with auth error | Deploy token expired or lacks write scope. Re-set the remote URL with a fresh token. |

## Notes

- The mirror is one-directional: Postgres → vault. Edits you make in Obsidian are **not** written back to the brain. Treat the vault as a read view. (Bidirectional sync is a possible future phase but adds conflict-resolution complexity.)
- Deleting a document in Postgres does NOT delete its vault file (the trigger is INSERT-only). Stale files are harmless; prune manually if you care.
