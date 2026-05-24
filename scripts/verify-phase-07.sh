#!/usr/bin/env bash
# Phase 7 acceptance gate — wire AI clients to production (prep half).
#
# Wiring each client and the cross-client round-trip are manual steps
# against the deployment. The machine-independent half: a client-agnostic
# endpoint validator that exercises exactly what a client does on connect,
# the all-clients setup doc, and the no-trailing-slash rule baked into
# both.
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

echo "── phase 7: prerequisites ──"
for prev in 02 06; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 7: endpoint validator + docs ──"
check "test -x scripts/check-client-endpoint.sh"                      "check-client-endpoint.sh executable"
check "grep -q 'trailing slash' scripts/check-client-endpoint.sh"     "validator handles the trailing-slash trap"
check "grep -q '401' scripts/check-client-endpoint.sh"                "validator checks auth rejection"
check "test -s docs/phase-07-client-setup.md"                         "client setup doc present"
for client in 'Claude Code' 'Claude Desktop' 'ChatGPT' 'Cursor'; do
  check "grep -q '$client' docs/phase-07-client-setup.md"             "doc covers $client"
done
check "grep -q 'no trailing slash' docs/phase-07-client-setup.md"     "doc states the no-trailing-slash rule"

echo "── phase 7: validator against the live local endpoint ──"
KEY="${BRAIN_KEY:-}"
if [ -z "$KEY" ] && [ -f .env ]; then
  KEY="$(awk -F= '/^BRAIN_KEY=/{print $2; exit}' .env)"
fi
if [ -n "$KEY" ] && [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health 2>/dev/null)" = "200" ]; then
  if bash scripts/check-client-endpoint.sh "http://localhost:8080/mcp" "$KEY" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m validator accepts the live endpoint with a good key\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m validator rejected the live endpoint\n"; fail=$((fail+1))
  fi
  if ! bash scripts/check-client-endpoint.sh "http://localhost:8080/mcp" "wrong-key" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m validator fails on a wrong key (exit non-zero)\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m validator did not fail on a wrong key\n"; fail=$((fail+1))
  fi
else
  skip_with "live endpoint validation" "mcp-server not running or BRAIN_KEY unset"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 7: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 7: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
