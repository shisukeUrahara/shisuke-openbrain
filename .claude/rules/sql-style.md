# SQL Style Rule

## Hard guard rails (from `CLAUDE.md`)

1. **Never** modify the structure of the existing `thoughts` table beyond adding columns or indexes.
2. **Never** include `DROP TABLE`, `DROP DATABASE`, `DROP SCHEMA`, `TRUNCATE`, or unqualified `DELETE FROM <table>;` in any SQL file or generated query.
3. Every CREATE statement uses `IF NOT EXISTS` (tables, indexes, extensions) or `CREATE OR REPLACE` (functions, views, triggers).
4. Every migration is **idempotent**. Running it twice → same state. Tests must prove this.

## File layout

| Concern | Path |
|---|---|
| Core migrations | `sql/0NN_<name>.sql` |
| Per-module migrations | `sql/modules/<module-id>/0NN_<name>.sql` |
| One-off ops scripts (rare) | `scripts/sql/<name>.sql` — never auto-applied |

Numbering: zero-padded, monotonically increasing within the directory. New core migration → look at `ls sql/0*.sql | sort | tail -1`, increment.

## File header

Every migration starts with:

```sql
-- sql/<path>/0NN_<name>.sql
-- Purpose: <one line, plain English>
-- Phase:   <NN from plan/PLANNED_PHASES.md>
-- Module:  <module-id or "core">
-- Applies-twice-safely: yes
```

## Statement conventions

- One logical change per file.
- Lowercase keywords (`select`, `where`, `create index`). PostgreSQL convention in this repo.
- Two-space indent inside `do $$ ... $$` blocks.
- Indexes named explicitly. Pattern: `<table>_<column(s)>_<kind>_idx`, e.g. `thoughts_embedding_idx`, `chunks_document_id_idx`.
- Foreign keys named explicitly: `<from-table>_<col>_fkey`.

## Vector specifics

- `vector(1536)` is the project default (locked to OpenAI `text-embedding-3-small` for now).
- HNSW indexes use `vector_cosine_ops` and `m = 16, ef_construction = 64` unless tuning experiment is in progress and documented in `plan/DECISIONS.md`.
- Any change to embedding dimension requires:
  1. A `plan/DECISIONS.md` entry justifying it.
  2. A re-embed migration script for existing rows.
  3. Schema change executed only after re-embed completes.

## RPC functions

- `language plpgsql stable` unless side-effecting.
- Use `security definer` only if absolutely required and documented; default is `security invoker`.
- Return composite types or `returns table (...)`; avoid `returns void` for query helpers.

## Reversibility

- Adding a column: safe. Default value should be `null` or a literal; not a function call that scans the table.
- Adding an index: safe. Use `create index concurrently if not exists` for prod-sized tables.
- Adding a function: safe under `create or replace`.
- Renaming, dropping, type changes: **NOT ALLOWED** without a documented exception in `plan/DECISIONS.md` and an explicit user confirmation in the commit message.

## When you must change something dangerous

The agent is forbidden from doing this autonomously. The user must:
1. Open `plan/DECISIONS.md` and write the entry.
2. Schedule a backup and test restore window.
3. Write the forward migration AND a confirmed-safe backward migration.
4. Apply locally, run the test suite, then apply to prod.

## Testing

Every migration ships with a matching `services/mcp-server/tests/integration/test_migration_<name>.py` that:
- Applies the migration on a fresh `pg` fixture.
- Applies it a second time → no error (proves idempotency).
- Asserts the new object exists via `information_schema` / `pg_*` catalogs.
- For functions: invokes the function with at least one valid input.

## Production application

Local first, prod second. Prod application path:
1. Open Coolify → DB resource → Terminal.
2. Paste migration verbatim from the committed file.
3. Re-run once to confirm idempotency on the live DB.
4. Note the apply timestamp in `plan/RUNBOOK.md`.
