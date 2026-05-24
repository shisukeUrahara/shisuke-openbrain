#!/usr/bin/env bash
# Apply the Open Brain schema to a Postgres database, in order.
#
# Locally, docker-compose mounts ./sql into docker-entrypoint-initdb.d
# and Postgres auto-runs the top-level core migrations on first init.
# Production (Coolify-provisioned Postgres) has no such auto-run — you
# point this script at the database instead. It is also the right tool
# for applying module migrations, which initdb.d does NOT pick up
# (it only runs top-level *.sql, not sql/modules/**).
#
# Every migration is idempotent (CREATE ... IF NOT EXISTS / CREATE OR
# REPLACE), so re-running this is safe and is in fact how we prove
# idempotency.
#
# Usage:
#   scripts/load-schema.sh                       # core only, uses $DATABASE_URL
#   scripts/load-schema.sh --with-module documents
#   scripts/load-schema.sh --all-modules
#   DATABASE_URL=postgresql://... scripts/load-schema.sh
#   scripts/load-schema.sh --dsn postgresql://user:pw@host:5432/db
#
# Reads DATABASE_URL from the environment or .env if --dsn is not given.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

dsn="${DATABASE_URL:-}"
modules=()
all_modules=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dsn) dsn="$2"; shift 2 ;;
    --with-module) modules+=("$2"); shift 2 ;;
    --all-modules) all_modules=1; shift ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$dsn" ] && [ -f .env ]; then
  dsn="$(awk -F= '/^DATABASE_URL=/{sub(/^DATABASE_URL=/,""); print; exit}' .env)"
fi
if [ -z "$dsn" ]; then
  echo "error: no DSN. Set DATABASE_URL, pass --dsn, or add it to .env" >&2
  exit 2
fi

# Mask the password when echoing the target.
masked="$(printf '%s' "$dsn" | sed -E 's#(://[^:]+:)[^@]+@#\1***@#')"
echo "==> target: $masked"

apply() {
  local f="$1"
  [ -f "$f" ] || { echo "  ! missing: $f" >&2; return 1; }
  echo "  -> $f"
  psql "$dsn" -v ON_ERROR_STOP=1 -q -f "$f"
}

echo "==> core migrations"
for f in $(ls sql/0*.sql | sort); do
  apply "$f"
done

if [ "$all_modules" -eq 1 ]; then
  for d in sql/modules/*/; do
    modules+=("$(basename "$d")")
  done
fi

# De-duplicate the module list while preserving order.
if [ "${#modules[@]}" -gt 0 ]; then
  declare -A seen
  for m in "${modules[@]}"; do
    [ -n "${seen[$m]:-}" ] && continue
    seen[$m]=1
    dir="sql/modules/$m"
    if [ ! -d "$dir" ]; then
      echo "  ! no such module dir: $dir" >&2
      exit 1
    fi
    echo "==> module: $m"
    for f in $(ls "$dir"/*.sql | sort); do
      apply "$f"
    done
  done
fi

echo "==> done."
