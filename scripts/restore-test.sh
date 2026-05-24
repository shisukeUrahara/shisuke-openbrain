#!/usr/bin/env bash
# Restore drill — prove a backup is actually restorable.
#
# "Untested backup = no backup." This spins an ephemeral, throwaway
# pgvector Postgres, restores the given dump into it, and asserts the
# thoughts table came back. It touches nothing real — the container is
# removed at the end (and on any error via trap).
#
# Accepts the .sql.gz produced by backup-db.sh, a plain .sql, or a
# pg_dump custom-format .dump.
#
# Usage:
#   scripts/restore-test.sh ./backups/openbrain-<stamp>.sql.gz
#   scripts/restore-test.sh ./backup.dump
set -euo pipefail

backup_file="${1:?usage: restore-test.sh <path to .sql.gz | .sql | .dump>}"
[ -f "$backup_file" ] || { echo "no such file: $backup_file" >&2; exit 2; }

# Validate the format up front — before spinning a container — so a bad
# argument fails fast and cheap.
case "$backup_file" in
  *.sql.gz|*.sql|*.dump) ;;
  *) echo "unsupported backup format: $backup_file" >&2; exit 2 ;;
esac

pg_image="pgvector/pgvector:pg17"
container="pg-restore-test-$$"
port=5434
pw="restoredrill"
base_dsn="postgresql://postgres:$pw@localhost:$port"

cleanup() { docker rm -f "$container" >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "==> starting throwaway $pg_image on :$port"
docker run -d --name "$container" \
  -e POSTGRES_PASSWORD="$pw" -p "$port:5432" "$pg_image" >/dev/null

# Wait for readiness rather than a blind sleep.
for _ in $(seq 1 30); do
  if docker exec "$container" pg_isready -U postgres >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$container" pg_isready -U postgres >/dev/null 2>&1 \
  || { echo "restore PG never became ready" >&2; exit 1; }

# The dump references database "openbrain"; create it (and pgvector)
# before restoring so a plain-SQL dump that omits CREATE DATABASE works.
docker exec "$container" psql -U postgres -tAc \
  "select 1 from pg_database where datname='openbrain'" | grep -q 1 \
  || docker exec "$container" createdb -U postgres openbrain
docker exec "$container" psql -U postgres -d openbrain -c \
  "create extension if not exists vector" >/dev/null 2>&1 || true

echo "==> restoring $backup_file"
case "$backup_file" in
  *.sql.gz) gunzip -c "$backup_file" | psql "$base_dsn/openbrain" -v ON_ERROR_STOP=0 -q ;;
  *.sql)    psql "$base_dsn/openbrain" -v ON_ERROR_STOP=0 -q -f "$backup_file" ;;
  *.dump)   pg_restore --no-owner --no-privileges -d "$base_dsn/openbrain" "$backup_file" ;;
  *) echo "unsupported backup format: $backup_file" >&2; exit 2 ;;
esac

# Assert the core table exists and is queryable. A successful restore of
# an Open Brain dump must have the thoughts table; row count >= 0 (an
# empty-but-present table still proves structural restore).
if ! psql "$base_dsn/openbrain" -tAc "select to_regclass('public.thoughts') is not null" | grep -q t; then
  echo "==> FAIL: thoughts table not present after restore" >&2
  exit 1
fi
rows="$(psql "$base_dsn/openbrain" -tAc "select count(*) from thoughts")"
echo "==> restored OK — thoughts table present, $rows row(s)"
