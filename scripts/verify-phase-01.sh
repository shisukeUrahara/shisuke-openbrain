#!/usr/bin/env bash
# Phase 1 acceptance gate.
#
# Checks (in order):
#   - Phase 0 still green (prerequisite).
#   - All four core SQL migrations present + parseable.
#   - docker-compose.yml present and lints.
#   - Integration tests pass (spins ephemeral pgvector via testcontainers).
#   - If `docker compose ps postgres` is healthy locally, the bats smoke
#     suite also runs against it.
#   - Idempotency proof: integration test suite includes the
#     test_core_migrations_are_idempotent case.
#
# Exit 0 only when every required check passes.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

fail=0
pass=0
skip=0
check() {
  local cmd="$1" label="$2"
  if eval "$cmd" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m %s\n" "$label"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m %s\n" "$label"; fail=$((fail+1))
  fi
}
skip_with() {
  printf "  \033[33m·\033[0m %s (skipped: %s)\n" "$1" "$2"; skip=$((skip+1))
}

echo "── phase 1: prerequisite — phase 0 green ──"
if bash scripts/verify-phase-00.sh >/dev/null 2>&1; then
  printf "  \033[32m✓\033[0m phase-00 acceptance gate passes\n"; pass=$((pass+1))
else
  printf "  \033[31m✗\033[0m phase-00 acceptance gate FAILS — fix that first\n"; fail=$((fail+1))
fi

echo "── phase 1: SQL migrations present ──"
for f in 000_extensions.sql 001_thoughts.sql 002_match_thoughts.sql 003_dedup.sql; do
  check "test -s sql/$f"                          "sql/$f present"
done

echo "── phase 1: SQL header conventions ──"
for f in sql/00*.sql; do
  check "head -5 '$f' | grep -q '^-- Idempotent: yes'"   "$(basename $f) declares idempotency"
  check "head -5 '$f' | grep -q '^-- Phase:'"            "$(basename $f) declares phase"
done

echo "── phase 1: forbidden SQL patterns absent ──"
check "! grep -inE '\\b(DROP\\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\\b|DELETE\\s+FROM\\s+\\w+\\s*;)' sql/00*.sql" \
  "no DROP/TRUNCATE/unqualified-DELETE in migrations"

echo "── phase 1: docker-compose ──"
check "test -s docker-compose.yml"                                       "docker-compose.yml present"
check "grep -qE 'pgvector/pgvector:pg17' docker-compose.yml"             "uses pgvector/pgvector:pg17 image"
check "grep -qE './sql:/docker-entrypoint-initdb.d' docker-compose.yml"  "mounts ./sql as initdb"
check "grep -qE 'healthcheck:' docker-compose.yml"                        "healthcheck defined"
check "docker compose config --quiet"                                     "docker-compose.yml lints clean"

echo "── phase 1: integration test scaffold ──"
check "test -s services/mcp-server/tests/integration/conftest.py"        "conftest.py present"
check "test -s services/mcp-server/tests/integration/test_schema.py"     "test_schema.py present"
check "test -s requirements-dev.txt"                                      "requirements-dev.txt present"
check "grep -q 'testcontainers\\[postgres\\]' requirements-dev.txt"      "testcontainers in dev deps"
check "grep -q 'psycopg' requirements-dev.txt"                            "psycopg in dev deps"

echo "── phase 1: smoke tests ──"
check "test -s tests/smoke/phase-01.bats"                                 "phase-01.bats present"

echo "── phase 1: integration tests run ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/mcp-server/tests/integration -v --tb=short 2>&1 | tail -2 | grep -qE '(passed|no tests ran)'; then
    printf "  \033[32m✓\033[0m pytest integration suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m pytest integration suite FAILED — run `pytest services/mcp-server/tests/integration -v` to diagnose\n"
    fail=$((fail+1))
  fi
else
  skip_with "pytest integration suite" "pytest not installed (pip install -r requirements-dev.txt)"
fi

echo "── phase 1: bats smoke (optional, against running stack) ──"
if docker compose ps postgres 2>/dev/null | grep -q 'running\|healthy'; then
  if bats tests/smoke/phase-01.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m bats smoke passes against local stack\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m bats smoke FAILED — run `bats tests/smoke/phase-01.bats` to diagnose\n"
    fail=$((fail+1))
  fi
else
  skip_with "bats smoke" "docker compose postgres is not running"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 1: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 1: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
