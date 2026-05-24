#!/usr/bin/env bash
# Assert an Open Brain database has the expected schema objects.
#
# This is the programmatic form of the Phase 5 acceptance criteria
# (\dx lists vector/pg_trgm/uuid-ossp, \dt lists thoughts, \df lists
# the match functions). Point it at local or production Postgres.
#
# Usage:
#   scripts/check-pgvector.sh
#   scripts/check-pgvector.sh --dsn postgresql://user:pw@host:5432/db
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

dsn="${DATABASE_URL:-}"
while [ $# -gt 0 ]; do
  case "$1" in
    --dsn) dsn="$2"; shift 2 ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$dsn" ] && [ -f .env ]; then
  dsn="$(awk -F= '/^DATABASE_URL=/{sub(/^DATABASE_URL=/,""); print; exit}' .env)"
fi
[ -n "$dsn" ] || { echo "error: no DSN (set DATABASE_URL or --dsn)" >&2; exit 2; }

fail=0
q() { psql "$dsn" -tAc "$1" 2>/dev/null; }

want_ext() {
  if [ "$(q "select 1 from pg_extension where extname='$1'")" = "1" ]; then
    echo "  ✓ extension $1"
  else
    echo "  ✗ extension $1 MISSING"; fail=1
  fi
}
want_table() {
  if [ "$(q "select to_regclass('public.$1') is not null")" = "t" ]; then
    echo "  ✓ table $1"
  else
    echo "  ✗ table $1 MISSING"; fail=1
  fi
}
want_func() {
  if [ "$(q "select 1 from pg_proc where proname='$1' limit 1")" = "1" ]; then
    echo "  ✓ function $1"
  else
    echo "  ✗ function $1 MISSING"; fail=1
  fi
}

echo "==> extensions"
want_ext vector
want_ext pg_trgm
want_ext "uuid-ossp"

echo "==> core tables"
want_table thoughts

echo "==> core functions"
want_func match_thoughts
want_func upsert_thought

if [ "$fail" -eq 0 ]; then
  echo "==> schema OK"
  exit 0
else
  echo "==> schema INCOMPLETE" >&2
  exit 1
fi
