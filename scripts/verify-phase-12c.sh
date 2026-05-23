#!/usr/bin/env bash
# Phase 12.c acceptance gate — pdf worker.
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

echo "── phase 12.c: prerequisites ──"
for prev in 00 01 02 10; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 12.c: scaffold ──"
check "test -s services/workers/pdf/pyproject.toml"                "pyproject.toml present"
check "test -s services/workers/pdf/Dockerfile"                     "Dockerfile present"
check "test -s services/workers/pdf/README.md"                      "README.md present"
for m in __init__.py config.py chunker.py fetcher.py extractor.py mcp_client.py queue.py worker.py; do
  check "test -s services/workers/pdf/src/worker_pdf/$m"            "src/worker_pdf/$m present"
done

echo "── phase 12.c: docker-compose ──"
check "grep -q '^\\s*worker-pdf:' docker-compose.yml"               "worker-pdf service declared"
check "docker compose --profile pdf config | grep -A20 '^\\s*worker-pdf:' | grep -q 'profiles:'" \
       "worker-pdf uses pdf profile"
check "grep -q 'MODULE_WORKERS_PDF_ENABLED' docker-compose.yml"     "module flag wired"
check "grep -q 'ingest:pdf' docker-compose.yml"                     "default queue ingest:pdf wired"
check "docker compose --profile pdf config --quiet"                 "compose lints clean with pdf profile"

echo "── phase 12.c: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/workers/pdf/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m worker-pdf pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m worker-pdf pytest suite FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "worker-pdf pytest suite" "pytest not installed"
fi

echo "── phase 12.c: live smoke ──"
if docker compose --profile pdf ps worker-pdf 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if bats tests/smoke/phase-12c.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-12c bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-12c bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-12c bats smoke" "worker-pdf container is not running (start with docker compose --profile pdf up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 12.c: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 12.c: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
