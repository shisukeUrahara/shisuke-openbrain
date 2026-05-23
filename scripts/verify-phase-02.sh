#!/usr/bin/env bash
# Phase 2 acceptance gate.
#
# Checks (in order):
#   - Phase 0 and Phase 1 still green (prerequisites).
#   - All required source modules present (config, db, embed, auth,
#     health, server, tools/__init__, tools/core_*).
#   - mcp-server pyproject.toml present and parses.
#   - Dockerfile present.
#   - docker-compose.yml has the mcp-server service with the right
#     env, port, and healthcheck.
#   - Unit + integration test suites pass.
#   - If `docker compose ps mcp-server` is healthy, bats smoke also
#     runs against the live stack.
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

# ──────────────────────────────────────────────────────────────────
echo "── phase 2: prerequisites ──"
if bash scripts/verify-phase-00.sh >/dev/null 2>&1; then
  printf "  \033[32m✓\033[0m phase-00 acceptance gate passes\n"; pass=$((pass+1))
else
  printf "  \033[31m✗\033[0m phase-00 acceptance gate FAILS\n"; fail=$((fail+1))
fi
if bash scripts/verify-phase-01.sh >/dev/null 2>&1; then
  printf "  \033[32m✓\033[0m phase-01 acceptance gate passes\n"; pass=$((pass+1))
else
  printf "  \033[31m✗\033[0m phase-01 acceptance gate FAILS\n"; fail=$((fail+1))
fi

# ──────────────────────────────────────────────────────────────────
echo "── phase 2: package scaffold ──"
check "test -s services/mcp-server/pyproject.toml" "pyproject.toml present"
check "test -s services/mcp-server/Dockerfile"      "Dockerfile present"
check "test -s services/mcp-server/README.md"       "service README present"

echo "── phase 2: source modules ──"
for m in config.py db.py embed.py auth.py health.py server.py; do
  check "test -s services/mcp-server/src/brain_mcp/$m" "brain_mcp/$m present"
done

echo "── phase 2: tool plugins ──"
for t in __init__.py core_capture.py core_search.py core_browse.py core_stats.py; do
  check "test -s services/mcp-server/src/brain_mcp/tools/$t" "tools/$t present"
done
check "grep -q 'def register' services/mcp-server/src/brain_mcp/tools/core_capture.py" "core_capture exposes register()"
check "grep -q 'def register' services/mcp-server/src/brain_mcp/tools/core_search.py"  "core_search exposes register()"
check "grep -q 'def register' services/mcp-server/src/brain_mcp/tools/core_browse.py"  "core_browse exposes register()"
check "grep -q 'def register' services/mcp-server/src/brain_mcp/tools/core_stats.py"   "core_stats exposes register()"

echo "── phase 2: docker-compose ──"
check "grep -q 'mcp-server:' docker-compose.yml"                            "mcp-server service declared"
check "grep -q 'context:.*services/mcp-server' docker-compose.yml"          "compose builds from services/mcp-server"
check "grep -qE ':-8080\\}:8080|\"8080:8080\"' docker-compose.yml"           "mcp-server port 8080 exposed"
check "grep -q 'BRAIN_KEY:?BRAIN_KEY' docker-compose.yml"                   "BRAIN_KEY required by compose"
check "grep -q 'MODULE_DOCUMENTS_ENABLED' docker-compose.yml"               "module flags wired through"
check "grep -q '/health' docker-compose.yml"                                 "healthcheck hits /health"
check "docker compose config --quiet"                                        "docker-compose.yml lints clean"

echo "── phase 2: unit + integration tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/mcp-server/tests -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m pytest mcp-server suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m pytest mcp-server suite FAILED — run pytest services/mcp-server/tests -v\n"
    fail=$((fail+1))
  fi
else
  skip_with "pytest mcp-server suite" "pytest not installed"
fi

echo "── phase 2: bats smoke against live stack ──"
if docker compose ps mcp-server 2>/dev/null | grep -qE 'healthy|running'; then
  : "${BRAIN_KEY:=}"
  if [ -z "$BRAIN_KEY" ] && [ -f .env ]; then
    BRAIN_KEY="$(awk -F= '/^BRAIN_KEY=/ {print $2}' .env)"
  fi
  if [ -z "$BRAIN_KEY" ]; then
    skip_with "bats smoke" "BRAIN_KEY not set"
  else
    if BRAIN_KEY="$BRAIN_KEY" bats tests/smoke/phase-02.bats >/dev/null 2>&1; then
      printf "  \033[32m✓\033[0m phase-02 bats smoke passes\n"; pass=$((pass+1))
    else
      printf "  \033[31m✗\033[0m phase-02 bats smoke FAILED — run with: BRAIN_KEY=\$(awk -F= '/^BRAIN_KEY=/ {print \$2}' .env) bats tests/smoke/phase-02.bats\n"
      fail=$((fail+1))
    fi
  fi
else
  skip_with "bats smoke" "docker compose mcp-server is not running"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 2: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 2: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
