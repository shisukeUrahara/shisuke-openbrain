#!/usr/bin/env bash
# Phase 15 acceptance gate — graphify export module.
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

echo "── phase 15: prerequisites ──"
for prev in 00 01 02 10; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 15: tool + wiring ──"
tool=services/mcp-server/src/brain_mcp/tools/graphify_export.py
check "test -s $tool"                                                 "graphify_export.py present"
check "grep -q 'def export_project_corpus' $tool"                     "export_project_corpus tool defined"
check "grep -q 'def register' $tool"                                  "module exposes register(mcp, *, config)"
# Path-traversal guard must be present — project is user-controlled.
check "grep -q 'refusing to write outside out_dir' $tool"             "out_dir traversal guard present"
check "grep -q \"if config.modules.graphify\" services/mcp-server/src/brain_mcp/server.py" \
       "server registers graphify behind its module flag"

echo "── phase 15: unit/integration tests ──"
itest=services/mcp-server/tests/integration/test_tools_graphify.py
check "test -s $itest"                                                "graphify integration test present"
if command -v uv >/dev/null 2>&1 && [ -d services/mcp-server ]; then
  if (cd services/mcp-server && uv run pytest tests/integration/test_tools_graphify.py -q >/dev/null 2>&1); then
    printf "  \033[32m✓\033[0m graphify integration tests pass\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m graphify integration tests FAIL\n"; fail=$((fail+1))
  fi
else
  skip_with "graphify integration tests" "uv not available"
fi

echo "── phase 15: docker-compose ──"
check "grep -q 'exports:/exports' docker-compose.yml"                 "exports volume mounted into mcp-server"
check "docker compose config | grep -qE '^\\s+exports:'"              "exports named volume declared"
check "docker compose config --quiet"                                 "compose lints clean"

echo "── phase 15: live smoke ──"
if docker compose ps mcp-server 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if [ -f .env ]; then set -a; . ./.env; set +a; fi
  if bats tests/smoke/phase-15.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-15 bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-15 bats smoke FAILED\n"; fail=$((fail+1))
  fi
else
  skip_with "phase-15 bats smoke" "mcp-server is not running (start with docker compose up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 15: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 15: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
