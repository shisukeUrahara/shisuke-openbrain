#!/usr/bin/env bash
# Phase 12.b acceptance gate — article ingestion worker.
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

echo "── phase 12.b: prerequisites ──"
for prev in 00 01 02 10 11; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 12.b: scaffold ──"
check "test -s services/workers/article/pyproject.toml"            "pyproject.toml present"
check "test -s services/workers/article/Dockerfile"                 "Dockerfile present"
check "test -s services/workers/article/README.md"                  "README.md present"
for m in __init__.py config.py chunker.py fetcher.py mcp_client.py queue.py worker.py; do
  check "test -s services/workers/article/src/worker_article/$m"    "src/worker_article/$m present"
done

echo "── phase 12.b: docker-compose ──"
check "grep -q '^\\s*worker-article:' docker-compose.yml"          "worker-article service declared"
check "docker compose --profile article config | grep -A20 '^\\s*worker-article:' | grep -q 'profiles:'" \
       "worker-article uses article profile"
check "grep -q 'MODULE_WORKERS_ARTICLE_ENABLED' docker-compose.yml" "module flag wired"
check "grep -q 'ingest:article' docker-compose.yml"                 "default queue ingest:article wired"
check "docker compose --profile article config --quiet"             "compose lints clean with article profile"

echo "── phase 12.b: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/workers/article/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m worker-article pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m worker-article pytest suite FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "worker-article pytest suite" "pytest not installed"
fi

echo "── phase 12.b: live smoke ──"
if docker compose --profile article ps worker-article 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if bats tests/smoke/phase-12b.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-12b bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-12b bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-12b bats smoke" "worker-article container is not running (start with docker compose --profile article up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 12.b: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 12.b: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
