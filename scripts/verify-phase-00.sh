#!/usr/bin/env bash
# Phase 0 acceptance gate. Verifies tooling installed + scaffold files present.
# Exit 0 = phase complete. Non-zero = something missing.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

fail=0
pass=0
check() {
  if eval "$1" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m %s\n" "$2"
    pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m %s\n" "$2"
    fail=$((fail+1))
  fi
}

echo "── phase 0: tooling ──"
check "docker --version"                                    "docker installed"
check "docker compose version"                              "docker compose installed"
check "command -v uv || command -v python3"                 "python toolchain present (uv or python3)"
check "python3 --version | grep -qE 'Python 3\\.(1[2-9]|[2-9][0-9])'" "python ≥ 3.12"
check "command -v psql"                                     "psql client installed"
check "command -v jq"                                       "jq installed"
check "command -v bats"                                     "bats-core installed"
check "command -v openssl"                                  "openssl installed"

echo "── phase 0: scaffold files ──"
check "test -f config/features.yaml"                        "config/features.yaml present"
check "test -f .env.example"                                ".env.example present"
check "test -f Makefile"                                    "Makefile present"
check "test -x scripts/run-tests.sh"                        "scripts/run-tests.sh executable"
check "test -x scripts/verify-phase-00.sh"                  "scripts/verify-phase-00.sh executable"
check "test -d config && test -d scripts && test -d sql && test -d services && test -d tests" "core dirs created"

echo "── phase 0: gitignore hygiene ──"
check "grep -qE '^\\.env\$' .gitignore"                     ".env gitignored"
check "grep -qE '^plan/\$' .gitignore"                      "plan/ gitignored"

echo "── phase 0: features.yaml integrity ──"
check "python3 -c 'import yaml; d=yaml.safe_load(open(\"config/features.yaml\")); assert d[\"modules\"][\"telegram_bot\"][\"enabled\"] is False'" "yaml parseable + telegram_bot default false"

echo "── phase 0: .env.example completeness ──"
check "test \$(grep -c '^MODULE_' .env.example) -ge 8"      ".env.example lists ≥ 8 module flags"
check "grep -q '^BRAIN_KEY=' .env.example"                  "BRAIN_KEY listed in .env.example"
check "grep -q '^DATABASE_URL=' .env.example"               "DATABASE_URL listed in .env.example"
check "grep -q '^EMBED_PROVIDER=' .env.example"             "EMBED_PROVIDER listed in .env.example"

echo "── phase 0: secret hygiene ──"
# Strict patterns that won't match documentation placeholders like
# sk-or-v1-your-key-here or BRAIN_KEY=<set-me>. Real keys are long
# uninterrupted alphanumeric runs.
check "! git log -p 2>/dev/null | grep -iE 'BRAIN_KEY=[a-f0-9]{40,}|OPENROUTER_API_KEY=sk-or-v1-[A-Za-z0-9]{40,}' >/dev/null" "no secrets in git history"

echo
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 0: OK (%d/%d)\033[0m\n" "$pass" "$((pass+fail))"
  exit 0
else
  printf "\033[31mphase 0: FAIL (%d/%d passed, %d failed)\033[0m\n" "$pass" "$((pass+fail))" "$fail"
  exit 1
fi
