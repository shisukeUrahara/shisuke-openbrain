#!/usr/bin/env bash
# Phase 10 acceptance gate — documents module.
#
# Checks:
#   - Prerequisite gates (0/1/2) still green.
#   - All three module migrations present in sql/modules/documents/.
#   - All three module tool files present + each exposes register().
#   - Module is correctly OFF when the flag is unset (4 tools).
#   - Module is correctly ON when the flag is true (7 tools, schema applied).
#   - Integration tests pass.
#   - Bats smoke passes against the live stack (when stack is up and
#     MODULE_DOCUMENTS_ENABLED=true).
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

echo "── phase 10: prerequisites ──"
for prev in 00 01 02; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 10: module migrations ──"
for f in 010_documents.sql 011_chunks.sql 012_match_chunks.sql; do
  check "test -s sql/modules/documents/$f" "sql/modules/documents/$f present"
  check "head -15 sql/modules/documents/$f | grep -q '^-- Idempotent: yes'" "$f declares idempotency"
  check "head -15 sql/modules/documents/$f | grep -q '^-- Module:  documents'" "$f declares module=documents"
done

check "! grep -inE '\\b(DROP\\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\\b|DELETE\\s+FROM\\s+\\w+\\s*;)' sql/modules/documents/*.sql" \
  "no DROP/TRUNCATE/unqualified-DELETE in module migrations"

echo "── phase 10: module tool plugins ──"
for t in docs_capture.py docs_chunks.py docs_search.py; do
  check "test -s services/mcp-server/src/brain_mcp/tools/$t" "tools/$t present"
  check "grep -q 'def register' services/mcp-server/src/brain_mcp/tools/$t" "tools/$t exposes register()"
done

echo "── phase 10: integration tests pass ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/mcp-server/tests/integration/test_documents_schema.py services/mcp-server/tests/integration/test_tools_documents.py -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m documents pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m documents pytest suite FAILED — run pytest services/mcp-server/tests/integration -k documents -v\n"
    fail=$((fail+1))
  fi
else
  skip_with "documents pytest suite" "pytest not installed"
fi

echo "── phase 10: live flag-toggle behaviour ──"
if docker compose ps mcp-server 2>/dev/null | grep -qE 'healthy|running'; then
  : "${BRAIN_KEY:=}"
  if [ -z "$BRAIN_KEY" ] && [ -f .env ]; then
    BRAIN_KEY="$(awk -F= '/^BRAIN_KEY=/ {print $2}' .env)"
  fi
  if [ -z "$BRAIN_KEY" ]; then
    skip_with "live flag toggle" "BRAIN_KEY not set"
  else
    # Read the actual /health flag.
    flag=$(curl -s http://localhost:8080/health | jq -r '.modules.documents' 2>/dev/null)
    if [ "$flag" = "true" ]; then
      # The documents flag adds 3 tools on top of the 4 core tools.
      # Other module flags (e.g. graphify) may add more, so assert
      # "at least 7 AND the 7 core+documents names are all present"
      # rather than an exact count — the off-contract below stays exact.
      names=$(curl -s -X POST "http://localhost:8080/mcp" \
        -H "x-brain-key: $BRAIN_KEY" \
        -H 'Content-Type: application/json' -H 'Accept: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
        | jq -r '[.result.tools[].name] as $n
                 | (["capture","search","browse","stats","capture_document","add_chunks","search_chunks"] - $n) | length')
      if [ "$names" = "0" ]; then
        printf "  \033[32m✓\033[0m flag ON: tools/list includes all 4 core + 3 documents tools\n"; pass=$((pass+1))
      else
        printf "  \033[31m✗\033[0m flag ON but %s core/documents tool(s) missing from tools/list\n" "$names"
        fail=$((fail+1))
      fi
    else
      # Flag off — check the off contract instead.
      count=$(curl -s -X POST "http://localhost:8080/mcp" \
        -H "x-brain-key: $BRAIN_KEY" \
        -H 'Content-Type: application/json' -H 'Accept: application/json' \
        -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
        | jq -r '.result.tools | length')
      if [ "$count" = "4" ]; then
        printf "  \033[32m✓\033[0m flag OFF: tools/list returns 4 core tools\n"; pass=$((pass+1))
      else
        printf "  \033[31m✗\033[0m flag OFF but tools/list returns %s (expected 4)\n" "$count"
        fail=$((fail+1))
      fi
    fi
  fi
else
  skip_with "live flag toggle" "mcp-server is not running"
fi

echo "── phase 10: bats smoke against live stack (flag ON) ──"
if docker compose ps mcp-server 2>/dev/null | grep -qE 'healthy|running'; then
  flag=$(curl -s http://localhost:8080/health | jq -r '.modules.documents' 2>/dev/null)
  if [ "$flag" = "true" ]; then
    : "${BRAIN_KEY:=}"
    if [ -z "$BRAIN_KEY" ] && [ -f .env ]; then
      BRAIN_KEY="$(awk -F= '/^BRAIN_KEY=/ {print $2}' .env)"
    fi
    if BRAIN_KEY="$BRAIN_KEY" bats tests/smoke/phase-10.bats >/dev/null 2>&1; then
      printf "  \033[32m✓\033[0m phase-10 bats smoke passes\n"; pass=$((pass+1))
    else
      printf "  \033[31m✗\033[0m phase-10 bats smoke FAILED\n"
      fail=$((fail+1))
    fi
  else
    skip_with "phase-10 bats smoke" "MODULE_DOCUMENTS_ENABLED is not true on the running container"
  fi
else
  skip_with "phase-10 bats smoke" "mcp-server is not running"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 10: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 10: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
