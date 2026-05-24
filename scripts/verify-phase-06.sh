#!/usr/bin/env bash
# Phase 6 acceptance gate — deploy MCP server (prep half).
#
# The actual Coolify deploy + TLS are run-on-VPS. What this gate proves
# locally: the prod Dockerfile builds, the resulting image boots HEALTHY
# against a real Postgres and serves /health with the 4 core tools (the
# exact artifact Coolify will run), the production smoke suite exists and
# collects, and the deploy docs + env checklist are present.
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

echo "── phase 6: prerequisites ──"
for prev in 02 05; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 6: prod artifacts ──"
check "test -s services/mcp-server/Dockerfile"                        "Dockerfile present"
check "grep -q 'HEALTHCHECK' services/mcp-server/Dockerfile"          "Dockerfile has a healthcheck"
check "grep -q 'EXPOSE 8080' services/mcp-server/Dockerfile"          "Dockerfile exposes 8080"
check "test -s tests/e2e/test_prod_smoke.py"                          "prod smoke suite present"
check "grep -q 'pytest.mark.e2e' tests/e2e/test_prod_smoke.py"        "prod smoke uses e2e marker"
check "grep -q 'status_code == 401' tests/e2e/test_prod_smoke.py"     "prod smoke asserts auth rejection"
check "test -s docs/phase-06-deploy-mcp.md"                           "deploy doc present"
check "test -s docs/phase-06-env-checklist.md"                        "env checklist present"

echo "── phase 6: prod smoke collects + skips without a deployment ──"
if python3 -c 'import httpx, pytest' >/dev/null 2>&1; then
  # With no BRAIN_URL set, every test must skip (not fail, not error).
  out="$(python3 -m pytest tests/e2e/test_prod_smoke.py -q 2>&1 || true)"
  if printf '%s' "$out" | grep -qE '[0-9]+ skipped' && ! printf '%s' "$out" | grep -qE 'failed|error'; then
    printf "  \033[32m✓\033[0m prod smoke skips cleanly with no BRAIN_URL\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m prod smoke did not skip cleanly\n"; fail=$((fail+1))
  fi
else
  skip_with "prod smoke collection" "python3 + httpx/pytest not available"
fi

echo "── phase 6: prod image builds + boots healthy (against local PG) ──"
LOCAL_DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@postgres:5432/${POSTGRES_DB:-openbrain}"
net="$(docker compose ps -q postgres 2>/dev/null | head -1)"
if [ -n "$net" ]; then
  net="$(docker inspect -f '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}' "$net" 2>/dev/null | head -1)"
fi
if command -v docker >/dev/null 2>&1 && [ -n "$net" ]; then
  img="openbrain-mcp:phase06-verify"
  if docker build -q -t "$img" services/mcp-server >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m prod image builds\n"; pass=$((pass+1))
    docker rm -f ob-p6-gate >/dev/null 2>&1 || true
    docker run -d --name ob-p6-gate --network "$net" \
      -e BRAIN_KEY=gatekey -e EMBED_PROVIDER=openrouter -e OPENROUTER_API_KEY=x \
      -e DATABASE_URL="$LOCAL_DSN" -p 18081:8080 "$img" >/dev/null 2>&1 || true
    healthy=0
    for _ in $(seq 1 15); do
      sleep 1
      if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:18081/health 2>/dev/null)" = "200" ]; then
        healthy=1; break
      fi
    done
    if [ "$healthy" -eq 1 ]; then
      printf "  \033[32m✓\033[0m prod image boots healthy and serves /health\n"; pass=$((pass+1))
      n=$(curl -s -X POST http://localhost:18081/mcp -H 'x-brain-key: gatekey' \
            -H 'Content-Type: application/json' -H 'Accept: application/json' \
            -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq -r '.result.tools|length')
      if [ "$n" = "4" ]; then
        printf "  \033[32m✓\033[0m flags-off image exposes exactly 4 core tools\n"; pass=$((pass+1))
      else
        printf "  \033[31m✗\033[0m flags-off image exposes %s tools (expected 4)\n" "$n"; fail=$((fail+1))
      fi
    else
      printf "  \033[31m✗\033[0m prod image did not become healthy\n"; fail=$((fail+1))
    fi
    docker rm -f ob-p6-gate >/dev/null 2>&1 || true
  else
    printf "  \033[31m✗\033[0m prod image failed to build\n"; fail=$((fail+1))
  fi
else
  skip_with "prod image boot" "docker unavailable or local postgres not running"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 6: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 6: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
