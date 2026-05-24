#!/usr/bin/env bash
# Phase 13 acceptance gate — obsidian vault mirror.
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

echo "── phase 13: prerequisites ──"
for prev in 00 01 02 10; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 13: migration ──"
check "test -s sql/modules/obsidian/020_notify_document.sql"          "notify migration present"
check "head -15 sql/modules/obsidian/020_notify_document.sql | grep -q '^-- Idempotent: yes'" "migration declares idempotency"
check "grep -q 'pg_notify' sql/modules/obsidian/020_notify_document.sql" "uses pg_notify"
check "! grep -inE '\\b(DROP\\s+TABLE|TRUNCATE\\b|DELETE\\s+FROM\\s+\\w+\\s*;)' sql/modules/obsidian/020_notify_document.sql" \
  "no forbidden SQL (DROP TRIGGER IF EXISTS is allowed)"

echo "── phase 13: scaffold ──"
check "test -s services/obsidian-sync/pyproject.toml"                 "pyproject.toml present"
check "test -s services/obsidian-sync/Dockerfile"                      "Dockerfile present"
check "test -s services/obsidian-sync/README.md"                       "README.md present"
for m in __init__.py config.py render.py db.py main.py; do
  check "test -s services/obsidian-sync/src/obsidian_sync/$m"          "src/obsidian_sync/$m present"
done

echo "── phase 13: docker-compose ──"
check "grep -q '^\\s*obsidian-sync:' docker-compose.yml"               "obsidian-sync service declared"
check "grep -q '^\\s*obsidian-git:' docker-compose.yml"                "obsidian-git push sidecar declared"
check "docker compose --profile obsidian config | grep -A20 '^\\s*obsidian-sync:' | grep -q 'profiles:'" \
       "obsidian-sync uses obsidian profile"
check "grep -q 'MODULE_OBSIDIAN_MIRROR_ENABLED' docker-compose.yml"    "module flag wired"
check "grep -q 'vault:/vault' docker-compose.yml"                      "vault volume mounted"
check "docker compose --profile obsidian config --quiet"               "compose lints clean with obsidian profile"

echo "── phase 13: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/obsidian-sync/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m obsidian-sync unit suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m obsidian-sync unit suite FAILED\n"
    fail=$((fail+1))
  fi
  # The notify-trigger integration test lives in the mcp-server tests.
  if pytest services/mcp-server/tests/integration/test_obsidian_notify.py -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m notify-trigger integration suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m notify-trigger integration suite FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "pytest suites" "pytest not installed"
fi

echo "── phase 13: live smoke ──"
if docker compose --profile obsidian ps obsidian-sync 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if POSTGRES_USER="${POSTGRES_USER:-postgres}" POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-devpass}" POSTGRES_DB="${POSTGRES_DB:-openbrain}" \
       bats tests/smoke/phase-13.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-13 bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-13 bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-13 bats smoke" "obsidian-sync container is not running (start with docker compose --profile obsidian up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 13: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 13: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
