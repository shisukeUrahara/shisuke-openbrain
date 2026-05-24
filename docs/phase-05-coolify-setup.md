# Phase 5 — Coolify + Production Postgres (Operator Guide)

Stand up Coolify on the hardened VPS and provision a pgvector-enabled
Postgres, then load the same schema you've been running locally.

**Prerequisite:** Phase 4 done — VPS hardened, non-root user, port 8000
open (the harden script already opened it).

## Step 1 — Install Coolify (on the VPS)

```bash
ssh shisuke@<VPS-IP>
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```

Open `http://<VPS-IP>:8000` and create the admin account immediately —
the dashboard is exposed until you do.

> Coolify is a self-hosted PaaS: it wraps Docker so you provision
> databases and deploy apps from a UI instead of writing compose +
> nginx + certbot by hand. Think "your own little Heroku on your box."

## Step 2 — Provision Postgres (with pgvector)

In Coolify: **New Resource → Database → PostgreSQL**, and pick the
**PGVector** variant (PostgreSQL 17 + pgvector preloaded). This matters —
the plain Postgres preset has no `vector` extension and the schema load
will fail at `000_extensions.sql`.

- Name: `openbrain-db`
- Database: `openbrain`
- Generate a strong password → save it as `PROD_DB_PASSWORD` in your
  password manager.

Start the resource, wait for **Running / healthy**.

## Step 3 — Load the schema

The schema is identical to local. You have two ways to apply it.

**A — from your laptop (recommended), using the committed script.**
Coolify exposes the DB on the VPS network; tunnel to it over SSH, then
point `load-schema.sh` at the tunnel:

```bash
# Find the published port in Coolify (Resource → Configuration), or
# tunnel directly to the container port 5432.
ssh -N -L 55432:localhost:<coolify-db-published-port> shisuke@<VPS-IP> &

DATABASE_URL="postgresql://postgres:$PROD_DB_PASSWORD@localhost:55432/openbrain" \
  scripts/load-schema.sh

# Verify the acceptance criteria programmatically:
DATABASE_URL="postgresql://postgres:$PROD_DB_PASSWORD@localhost:55432/openbrain" \
  scripts/check-pgvector.sh
```

`load-schema.sh` applies `sql/000_extensions.sql` → `003_dedup.sql` in
order. Every migration is idempotent, so running it twice is safe (and
proves it). To also load a module's tables:

```bash
DATABASE_URL=... scripts/load-schema.sh --with-module documents
# or every module at once:
DATABASE_URL=... scripts/load-schema.sh --all-modules
```

**B — from the Coolify DB terminal (manual).**
Resource → Terminal opens `psql` inside the container. Paste the
contents of each file in order: `000_extensions.sql`, `001_thoughts.sql`,
`002_match_thoughts.sql`, `003_dedup.sql`. Then any module file under
`sql/modules/<name>/` you want enabled.

## Step 4 — Verify

`check-pgvector.sh` is the scripted form of the acceptance criteria. By
hand in the DB terminal:

```sql
\dx     -- must list: vector, pg_trgm, uuid-ossp
\dt     -- must list: thoughts (+ documents, chunks if you loaded them)
\df     -- must list: match_thoughts, upsert_thought (+ match_chunks)
select count(*) from thoughts;   -- 0 on a fresh DB
```

## Step 5 — Capture the internal URL

Coolify shows an **internal** connection string the app will use (apps
and the DB share Coolify's Docker network):

```
postgresql://postgres:<PROD_DB_PASSWORD>@postgresql-openbrain-db:5432/openbrain
```

Save it as `PROD_DATABASE_URL`. The MCP app (Phase 6) reads this as its
`DATABASE_URL` — note the hostname is the **container name**, not
`localhost`, and not the SSH tunnel you used in Step 3.

## Acceptance criteria

- Coolify dashboard reachable, admin account created.
- `openbrain-db` resource state = Running.
- `scripts/check-pgvector.sh` (against the tunnelled DSN) exits 0.
- `select count(*) from thoughts` returns 0.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `000_extensions.sql` errors on `create extension vector` | Wrong preset — you used plain Postgres. Delete the resource and recreate with the **PGVector** variant. |
| `load-schema.sh` can't connect | The SSH tunnel isn't up, or the published port is wrong. Check `Resource → Configuration` for the host port. |
| App later can't reach the DB | App env used the tunnel DSN (`localhost:55432`) instead of the internal container DSN from Step 5. |

## Rollback

Delete the resource in Coolify. The DB is empty at this stage, so there
is no data loss.
