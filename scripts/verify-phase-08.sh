#!/usr/bin/env bash
# Phase 8 acceptance gate — backups + restore drill (prep half).
#
# R2 wiring + the Coolify schedule + the uptime monitor are run-against-
# prod steps. The core of this phase — that a backup is actually
# restorable — is proven HERE, locally: dump the live local DB, restore
# the dump into a throwaway PG17, assert the thoughts table survives.
# That is the same backup-db.sh / restore-test.sh you run against prod.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

fail=0
pass=0
skip=0
check() {
  if eval "$1" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m %s\n" "$2"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m %s\n" "$2"; fail=$((fail+1))
  fi
}
skip_with() {
  printf "  \033[33m·\033[0m %s (skipped: %s)\n" "$1" "$2"; skip=$((skip+1))
}

echo "── phase 8: prerequisites ──"
for prev in 01 06; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 8: scripts + docs ──"
check "test -x scripts/backup-db.sh"                                  "backup-db.sh executable"
check "test -x scripts/restore-test.sh"                               "restore-test.sh executable"
check "grep -q 'pgvector/pgvector:pg17' scripts/backup-db.sh"         "backup uses a version-matched dumper"
check "grep -q 'sed -E' scripts/backup-db.sh"                         "backup masks the DSN password"
check "grep -q 'trap cleanup EXIT' scripts/restore-test.sh"           "restore drill always cleans up its container"
check "test -s docs/phase-08-backups-monitoring.md"                   "backups/monitoring doc present"
check "grep -q 'restore-test.sh' docs/phase-08-backups-monitoring.md" "doc walks the restore drill"

echo "── phase 8: live backup → restore loop (the real proof) ──"
LOCAL_DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
if command -v docker >/dev/null 2>&1 \
   && command -v psql >/dev/null 2>&1 \
   && psql "$LOCAL_DSN" -tAc "select 1" >/dev/null 2>&1; then
  tmp="$(mktemp -d)"
  if DATABASE_URL="$LOCAL_DSN" bash scripts/backup-db.sh --out "$tmp" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m backup-db produces a dump from the live DB\n"; pass=$((pass+1))
    bk="$(ls -t "$tmp"/*.sql.gz 2>/dev/null | head -1)"
    if [ -n "$bk" ] && bash scripts/restore-test.sh "$bk" >/dev/null 2>&1; then
      printf "  \033[32m✓\033[0m restore-test restores that dump into a throwaway PG and asserts thoughts\n"; pass=$((pass+1))
    else
      printf "  \033[31m✗\033[0m restore-test FAILED on the produced dump\n"; fail=$((fail+1))
    fi
  else
    printf "  \033[31m✗\033[0m backup-db FAILED against the live DB\n"; fail=$((fail+1))
  fi
  rm -rf "$tmp"
else
  skip_with "live backup/restore loop" "docker, psql, or local Postgres unavailable"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 8: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 8: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
