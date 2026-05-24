# Phase 8 — Backups, Monitoring, Restore Drill (Operator Guide)

Daily backups to R2, an uptime monitor on `/health`, and — the part you
cannot skip — a **tested** restore. An untested backup is not a backup.

**Prerequisite:** Phase 6 (server + DB live).

## Step 1 — R2 bucket

In Cloudflare R2, create `openbrain-backups-prod`. Generate an
S3-compatible access key + secret; save them. R2 is S3-compatible, so
both Coolify's backup feature and `rclone` can target it.

## Step 2 — Coolify scheduled backup

Coolify → DB resource (`openbrain-db`) → **Backups**:

- Schedule: daily **03:00 UTC**.
- Destination: **S3-compatible**, R2 endpoint + the keys from Step 1.
- Retention: 7 daily + 4 weekly + 6 monthly.

Click **Backup Now** once and confirm the object appears in the R2 UI
(or `rclone lsf r2:openbrain-backups-prod`).

## Step 3 — On-demand backup (and the source for the drill)

`scripts/backup-db.sh` is the manual/local equivalent of the cron. It
runs `pg_dump` inside a **version-matched** `pgvector/pgvector:pg17`
container — important, because an older host `pg_dump` refuses to dump a
PG17 server.

```bash
# local
DATABASE_URL=postgresql://postgres:devpass@localhost:5432/openbrain \
  scripts/backup-db.sh --out ./backups

# production (over the SSH tunnel from Phase 5)
DATABASE_URL=postgresql://postgres:$PROD_DB_PASSWORD@localhost:55432/openbrain \
  scripts/backup-db.sh --out ./backups

# optional R2 upload — set a configured rclone remote:
R2_REMOTE=r2:openbrain-backups-prod \
  DATABASE_URL=... scripts/backup-db.sh
```

It writes `openbrain-<UTC-timestamp>.sql.gz` and masks the DSN password
in its output.

## Step 4 — Restore drill (mandatory)

```bash
scripts/restore-test.sh ./backups/openbrain-<stamp>.sql.gz
# -> "restored OK — thoughts table present, N row(s)"  (exit 0)
```

It spins a throwaway PG17 container, restores the dump, asserts the
`thoughts` table is present and queryable, then removes the container
(via an EXIT trap, even on failure). It touches nothing real.

Do this against a **real downloaded production backup** at least once,
and re-run it whenever the schema changes. A green drill is the only
evidence the backups are usable.

## Step 5 — Uptime monitor

Add an HTTP monitor (UptimeRobot or Healthchecks.io) on
`https://brain.yourdomain.com/health`, every 5 minutes, alerting to
email + Telegram. `/health` is unauthenticated by design precisely so a
monitor can hit it.

Test the alert: in Coolify, stop the Application briefly; confirm the
alert fires; start it again.

## Step 6 — Logs

Confirm Coolify shows live logs for both the Application and the DB
resource (Resource → Logs). That's your first stop when the monitor
goes red.

## Acceptance criteria

- A backup object exists in R2 (web UI or `rclone lsf`).
- `scripts/restore-test.sh <real-prod-backup>` exits 0 with row count
  reported.
- Uptime monitor green; alert verified by a brief stop.

## Why this matters

The plan is explicit: skipping the restore drill **voids** the phase.
Backups you have never restored fail exactly when you need them —
wrong format, missing extension, version skew. The drill catches all
three cheaply, on a throwaway container, before a real outage does.
