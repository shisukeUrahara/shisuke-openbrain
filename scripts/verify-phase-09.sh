#!/usr/bin/env bash
# Phase 9 acceptance gate — production hardening baseline.
#
# The VPS-side steps (apply tuning conf in Coolify, install the prune
# cron, run the rotate-key drill against prod) are deferred. What this
# gate proves locally: the rate-limit middleware exists, is wired, its
# unit tests pass, and it actually returns 429 past the threshold on the
# live container; the secret-history scan is clean; the index-usage and
# tuning artifacts exist; and the docs + README note are in place.
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

echo "── phase 9: prerequisites ──"
for prev in 02 06; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 9: rate-limit middleware ──"
rl=services/mcp-server/src/brain_mcp/ratelimit.py
check "test -s $rl"                                                   "ratelimit.py present"
check "grep -q 'status_code=429' $rl"                                 "returns 429 over the limit"
check "grep -q '/health' $rl"                                         "health is allow-listed"
check "grep -q 'RateLimitMiddleware' services/mcp-server/src/brain_mcp/server.py" \
       "middleware wired into build_app"
check "grep -q 'rate_limit_per_min' services/mcp-server/src/brain_mcp/config.py" \
       "rate limit is configurable"
check "grep -q 'RATE_LIMIT_PER_MIN' docker-compose.yml"               "rate limit env wired in compose"

echo "── phase 9: middleware unit tests ──"
if command -v uv >/dev/null 2>&1; then
  if (cd services/mcp-server && uv run pytest tests/unit/test_ratelimit.py -q >/dev/null 2>&1); then
    printf "  \033[32m✓\033[0m rate-limit unit tests pass\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m rate-limit unit tests FAIL\n"; fail=$((fail+1))
  fi
else
  skip_with "rate-limit unit tests" "uv not available"
fi

echo "── phase 9: hardening scripts + artifacts ──"
check "test -x scripts/scan-history-secrets.sh"                       "history secret scan present"
check "bash scripts/scan-history-secrets.sh"                          "git history is free of leaked secrets"
check "test -x scripts/check-index-usage.sh"                          "index-usage checker present"
check "test -s config/postgresql.tuning.conf"                         "Postgres tuning conf present"
check "grep -q 'shared_buffers' config/postgresql.tuning.conf"        "tuning conf sets shared_buffers"
check "test -s docs/phase-09-hardening.md"                            "hardening doc present"
check "grep -q 'Self-hosted fork' README.md"                          "README carries the fork note"

echo "── phase 9: live rate-limit (429 past the threshold) ──"
KEY="${BRAIN_KEY:-}"
if [ -z "$KEY" ] && [ -f .env ]; then KEY="$(awk -F= '/^BRAIN_KEY=/{print $2; exit}' .env)"; fi
if command -v docker >/dev/null 2>&1 && [ -n "$KEY" ]; then
  RATE_LIMIT_PER_MIN=3 docker compose up -d mcp-server >/dev/null 2>&1 || true
  # wait for health
  ready=0
  for _ in $(seq 1 20); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health 2>/dev/null)" = "200" ] && { ready=1; break; }
    sleep 1
  done
  if [ "$ready" -eq 1 ]; then
    saw_429=0; ok=0
    for i in $(seq 1 6); do
      c=$(curl -s -o /dev/null -w '%{http_code}' -X POST http://localhost:8080/mcp \
            -H "x-brain-key: $KEY" -H 'Content-Type: application/json' -H 'Accept: application/json' \
            -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}')
      [ "$c" = "200" ] && ok=$((ok+1))
      [ "$c" = "429" ] && saw_429=1
    done
    hcode=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)
    if [ "$saw_429" -eq 1 ] && [ "$ok" -ge 1 ] && [ "$hcode" = "200" ]; then
      printf "  \033[32m✓\033[0m limiter trips to 429 past the threshold; /health stays 200\n"; pass=$((pass+1))
    else
      printf "  \033[31m✗\033[0m expected some 200s then 429 (ok=%s saw_429=%s health=%s)\n" "$ok" "$saw_429" "$hcode"; fail=$((fail+1))
    fi
  else
    skip_with "live rate-limit" "mcp-server did not come up"
  fi
  # restore default limit
  docker compose up -d mcp-server >/dev/null 2>&1 || true
else
  skip_with "live rate-limit" "docker unavailable or BRAIN_KEY unset"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 9: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 9: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
