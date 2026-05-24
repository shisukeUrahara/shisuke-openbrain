#!/usr/bin/env bash
# Phase 14 acceptance gate — n8n scheduler.
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

echo "── phase 14: prerequisites ──"
for prev in 00 01 02; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 14: scaffold + workflows ──"
check "test -s services/n8n/README.md"                              "README.md present"
check "test -s services/n8n/workflows/daily-digest.json"            "daily-digest.json present"
check "test -s services/n8n/workflows/weekly-review.json"           "weekly-review.json present"
check "jq -e '(.name|length>0) and (.nodes|length>=4) and (.connections|length>0)' services/n8n/workflows/daily-digest.json" \
  "daily-digest.json has valid importable shape"
check "jq -e '(.name|length>0) and (.nodes|length>=4) and (.connections|length>0)' services/n8n/workflows/weekly-review.json" \
  "weekly-review.json has valid importable shape"
check "jq -e '[.nodes[].type] | any(. == \"n8n-nodes-base.scheduleTrigger\")' services/n8n/workflows/daily-digest.json" \
  "daily-digest has a schedule trigger"
check "jq -e '[.nodes[].type] | any(. == \"n8n-nodes-base.scheduleTrigger\")' services/n8n/workflows/weekly-review.json" \
  "weekly-review has a schedule trigger"
# Secrets must not be baked into the committed workflow JSON.
check "! grep -iqE 'sk-or-v1-[A-Za-z0-9]{20,}|BRAIN_KEY=[a-f0-9]{40,}' services/n8n/workflows/*.json" \
  "no secrets baked into workflow JSON"

echo "── phase 14: docker-compose ──"
check "grep -q '^\\s*n8n:' docker-compose.yml"                       "n8n service declared"
check "docker compose --profile n8n config | grep -A30 '^\\s*n8n:' | grep -q 'profiles:'" \
       "n8n uses n8n profile"
check "grep -q 'DB_POSTGRESDB_SCHEMA: n8n' docker-compose.yml"        "n8n uses dedicated postgres schema"
check "grep -q 'N8N_ENCRYPTION_KEY' docker-compose.yml"              "n8n encryption key wired"
check "grep -q '/workflows:ro' docker-compose.yml"                  "workflow templates mounted read-only"
check "docker compose --profile n8n config --quiet"                  "compose lints clean with n8n profile"

echo "── phase 14: live smoke ──"
if docker compose --profile n8n ps n8n 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if POSTGRES_USER="${POSTGRES_USER:-postgres}" POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-devpass}" POSTGRES_DB="${POSTGRES_DB:-openbrain}" \
       bats tests/smoke/phase-14.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-14 bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-14 bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-14 bats smoke" "n8n container is not running (start with docker compose --profile n8n up -d n8n)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 14: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 14: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
