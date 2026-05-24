#!/usr/bin/env bash
# Phase 5 acceptance gate — Coolify + production Postgres prep.
#
# The Coolify install + DB provisioning are run-on-VPS steps, deferred
# to deploy time. What this gate checks now is the machine-independent
# half: the schema-load + schema-check scripts exist, are correct, and
# (when a local DB is up) actually apply idempotently and pass the
# pgvector acceptance checks. That is the same schema that will go to
# production, exercised locally.
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

echo "── phase 5: prerequisites ──"
for prev in 00 01; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 5: schema scripts ──"
check "test -x scripts/load-schema.sh"                                "load-schema.sh is executable"
check "test -x scripts/check-pgvector.sh"                             "check-pgvector.sh is executable"
check "bash scripts/load-schema.sh --help | grep -q 'all-modules'"    "load-schema documents its flags"
# Password must never be echoed in clear — the script masks it.
check "grep -q 'sed -E' scripts/load-schema.sh"                       "load-schema masks the DSN password"

echo "── phase 5: live local DB (applies the prod schema) ──"
LOCAL_DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
if command -v psql >/dev/null 2>&1 && psql "$LOCAL_DSN" -tAc "select 1" >/dev/null 2>&1; then
  if DATABASE_URL="$LOCAL_DSN" bash scripts/load-schema.sh >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m load-schema applies core idempotently\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m load-schema FAILED\n"; fail=$((fail+1))
  fi
  # Second run must also succeed — that is the idempotency proof.
  if DATABASE_URL="$LOCAL_DSN" bash scripts/load-schema.sh >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m load-schema is idempotent (second run clean)\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m load-schema not idempotent\n"; fail=$((fail+1))
  fi
  if DATABASE_URL="$LOCAL_DSN" bash scripts/check-pgvector.sh >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m check-pgvector passes (vector/pg_trgm/uuid-ossp, thoughts, fns)\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m check-pgvector FAILED\n"; fail=$((fail+1))
  fi
else
  skip_with "live schema apply + check" "no reachable local Postgres (docker compose up -d)"
fi

echo "── phase 5: Coolify setup doc ──"
check "test -s docs/phase-05-coolify-setup.md"                        "Coolify setup doc present"
check "grep -q 'PGVector' docs/phase-05-coolify-setup.md"             "doc specifies the pgvector preset"
check "grep -q 'load-schema.sh' docs/phase-05-coolify-setup.md"       "doc references the schema-load script"

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 5: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 5: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
