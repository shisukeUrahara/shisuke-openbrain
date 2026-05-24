#!/usr/bin/env bash
# Phase 3 acceptance gate — local AI client wiring + e2e harness.
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

echo "── phase 3: prerequisites ──"
for prev in 00 01 02; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 3: e2e harness + config ──"
check "test -s tests/e2e/test_capture_search_loop.py"                 "e2e harness present"
check "grep -q 'def test_capture_then_search_finds_it' tests/e2e/test_capture_search_loop.py" \
       "capture/search loop test defined"
check "grep -q 'pytest.mark.e2e' tests/e2e/test_capture_search_loop.py" \
       "e2e marker applied"
check "test -s pyproject.toml && grep -q 'e2e:' pyproject.toml"        "root pyproject registers e2e marker"
# The harness must never hard-fail on a missing embedding key — it skips.
check "grep -q 'pytest.skip' tests/e2e/test_capture_search_loop.py"    "harness skips gracefully without an embedding key"

echo "── phase 3: e2e collection (no run) ──"
if command -v python3 >/dev/null 2>&1 && python3 -c 'import httpx, pytest' >/dev/null 2>&1; then
  if python3 -m pytest tests/e2e --collect-only -q >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m e2e suite collects cleanly\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m e2e suite fails to collect\n"; fail=$((fail+1))
  fi
else
  skip_with "e2e collection" "python3 + httpx/pytest not available on host"
fi

echo "── phase 3: e2e run against live stack ──"
if docker compose ps mcp-server 2>/dev/null | grep -qE 'Up|running|healthy' \
   && python3 -c 'import httpx, pytest' >/dev/null 2>&1; then
  if [ -f .env ]; then set -a; . ./.env; set +a; fi
  # stats test must pass (it needs no key); capture/search may skip.
  if BRAIN_KEY="${BRAIN_KEY:-}" python3 -m pytest tests/e2e -q >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m e2e run passes (capture/search may skip without a key)\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m e2e run FAILED\n"; fail=$((fail+1))
  fi
else
  skip_with "e2e live run" "mcp-server not running or host lacks httpx/pytest"
fi

echo "── phase 3: client-wiring docs ──"
check "test -s docs/phase-03-go-live.md"                              "client-wiring go-live doc present"
check "grep -q 'claude mcp add' docs/phase-03-go-live.md"             "doc shows the claude mcp add command"

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 3: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 3: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
