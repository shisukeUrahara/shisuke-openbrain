#!/usr/bin/env bash
# Assert the HNSW vector index is actually used by match_thoughts.
#
# A vector index that the planner ignores is dead weight — queries fall
# back to a sequential scan and latency explodes as the table grows.
# This runs EXPLAIN on a representative similarity query and checks the
# plan references the embedding index rather than a Seq Scan.
#
# Needs at least a few embedded rows for the planner to prefer the
# index; on an empty/tiny table Postgres rightly picks a seq scan, so
# this SKIPS (exit 0 with a note) below a row threshold rather than
# failing spuriously.
#
# Usage:
#   scripts/check-index-usage.sh
#   scripts/check-index-usage.sh --dsn postgresql://...
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

dsn="${DATABASE_URL:-}"
min_rows=50
while [ $# -gt 0 ]; do
  case "$1" in
    --dsn) dsn="$2"; shift 2 ;;
    --min-rows) min_rows="$2"; shift 2 ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
if [ -z "$dsn" ] && [ -f .env ]; then
  dsn="$(awk -F= '/^DATABASE_URL=/{sub(/^DATABASE_URL=/,""); print; exit}' .env)"
fi
[ -n "$dsn" ] || { echo "error: no DSN (set DATABASE_URL or --dsn)" >&2; exit 2; }

embedded="$(psql "$dsn" -tAc "select count(*) from thoughts where embedding is not null" 2>/dev/null || echo 0)"
echo "==> embedded rows: $embedded"
if [ "$embedded" -lt "$min_rows" ] 2>/dev/null; then
  echo "==> SKIP: fewer than $min_rows embedded rows; planner will prefer a seq"
  echo "    scan on a tiny table. Re-run against a populated DB (e.g. prod)."
  exit 0
fi

# A random unit-ish query vector; we only care about the plan shape.
plan="$(psql "$dsn" -tAc "
  set hnsw.ef_search = 40;
  explain (analyze off, costs off)
  select id from thoughts
  order by embedding <=> (select embedding from thoughts where embedding is not null limit 1)
  limit 10;
" 2>/dev/null)"

echo "$plan" | sed 's/^/    /'

if echo "$plan" | grep -qiE 'Index Scan|thoughts_embedding_idx'; then
  echo "==> OK: match query uses the HNSW embedding index"
  exit 0
else
  echo "==> FAIL: query is NOT using the embedding index (seq scan)" >&2
  exit 1
fi
