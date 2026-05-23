#!/usr/bin/env bash
# Phase 11 acceptance gate — telegram capture bot.
#
# Checks:
#   - Phase 0/1/2 gates still green.
#   - Service scaffold present (pyproject, Dockerfile, src/brain_bot/*).
#   - docker-compose has telegram-bot + redis services behind the
#     `telegram` profile.
#   - Unit test suite passes (no live token required).
#   - When the live stack is up with `--profile telegram`, the bats
#     smoke suite verifies idle-mode contract.
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

echo "── phase 11: prerequisites ──"
for prev in 00 01 02; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 11: scaffold ──"
check "test -s services/telegram-bot/pyproject.toml" "pyproject.toml present"
check "test -s services/telegram-bot/Dockerfile"     "Dockerfile present"
check "test -s services/telegram-bot/README.md"      "README.md present"
for m in __init__.py config.py handlers.py mcp_client.py queue_client.py server.py; do
  check "test -s services/telegram-bot/src/brain_bot/$m" "src/brain_bot/$m present"
done

echo "── phase 11: docker-compose ──"
check "grep -q '^\\s*telegram-bot:' docker-compose.yml"           "telegram-bot service declared"
check "grep -q '^\\s*redis:' docker-compose.yml"                   "redis service declared"
# Use a yq-free approach: ask docker compose itself which profiles
# each service belongs to.
check "docker compose --profile telegram config | grep -A20 '^\\s*telegram-bot:' | grep -q 'profiles:'" \
       "telegram-bot uses telegram profile"
check "docker compose --profile telegram config | grep -A20 '^\\s*redis:' | grep -q 'profiles:'" \
       "redis uses profile gating"
check "grep -q 'MODULE_TELEGRAM_BOT_ENABLED' docker-compose.yml"   "module flag wired"
check "docker compose --profile telegram config --quiet"            "compose lints clean with telegram profile"

echo "── phase 11: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/telegram-bot/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m telegram-bot pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m telegram-bot pytest suite FAILED — run pytest services/telegram-bot/tests/unit -v\n"
    fail=$((fail+1))
  fi
else
  skip_with "telegram-bot pytest suite" "pytest not installed"
fi

echo "── phase 11: idle-mode smoke ──"
# docker compose ps filters by enabled profiles, so we have to pass
# `--profile telegram` to see the bot container.
if docker compose --profile telegram ps telegram-bot 2>/dev/null | grep -qE 'running|healthy|\bUp\b'; then
  if bats tests/smoke/phase-11.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-11 bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-11 bats smoke FAILED — run with verbose flag to diagnose\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-11 bats smoke" "telegram-bot container is not running (start with docker compose --profile telegram up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 11: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 11: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
