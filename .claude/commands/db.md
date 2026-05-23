---
description: Run a psql query against the local (or specified) Postgres. Our equivalent of Boris's bq tip.
argument-hint: <sql-query or '\\dt' style meta-command>
---

# /db

Shortcut to query Postgres without hand-typing the connection string.

## Inputs

- `$1` — SQL query OR a `psql` meta-command. If empty, default to `\dt+`.

## Resolution

1. Determine the target DB URL:
   - Prefer `$DATABASE_URL` from the environment.
   - Else use `.env` file (`DATABASE_URL` line).
   - Else fall back to `postgresql://postgres:devpass@localhost:5432/openbrain` (our local dev default).

2. Validate the query is safe:
   - **Refuse** anything matching `DROP TABLE`, `DROP DATABASE`, `TRUNCATE`, or an unqualified `DELETE FROM ... ;` without a `WHERE`. (CLAUDE.md guard rail.)
   - For `INSERT`/`UPDATE`/`DELETE` with WHERE — print the query and ASK the user to confirm before executing.

3. Run:
   ```bash
   psql "$DATABASE_URL" -c "$1" --pset=expanded=auto
   ```

4. **Report** the result. For large result sets (> 30 rows), truncate and summarise (count + first 10 rows).

## Common patterns

- `/db` → list all tables
- `/db "\\d thoughts"` → describe thoughts table
- `/db "select count(*) from thoughts"` → row count
- `/db "select id, content from thoughts order by created_at desc limit 5"` → recent captures
- `/db "\\dx"` → list extensions (verify pgvector installed)
- `/db "explain analyze select * from match_thoughts(..., 0.7, 10, '{}'::jsonb)"` → check HNSW index usage

## Notes

- Read-only queries are auto-approved by `.claude/settings.json`.
- Mutating queries fall under the `ask` permission category and prompt for confirmation.
- For production, the user must explicitly set `DATABASE_URL` to the prod URL; we do not auto-route to prod.
