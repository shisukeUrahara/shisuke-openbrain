#!/usr/bin/env bash
# Scan the full git history for leaked secrets (Phase 9.1).
#
# The pre-commit secret-scanner agent guards new commits; this checks
# what is ALREADY in history — a leak introduced before the guard, or
# in a branch that skipped it. Run it before making the repo public and
# periodically thereafter.
#
# Patterns are tuned to this project's real secret shapes so doc
# placeholders (sk-or-v1-your-key, BRAIN_KEY=<...>) do not false-positive:
#   - OpenRouter keys:  sk-or-v1-<40+ base62>
#   - Brain keys:       BRAIN_KEY=<40+ hex>
#   - Generic 64-hex assignments to *_KEY / *_SECRET / *_TOKEN
#
# Usage:
#   scripts/scan-history-secrets.sh
# Exit 0 = clean, 1 = potential leak found.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

patterns=(
  'sk-or-v1-[A-Za-z0-9]{40,}'
  'BRAIN_KEY=[a-f0-9]{40,}'
  '(API_KEY|SECRET|TOKEN|PASSWORD)=[A-Za-z0-9/+]{40,}'
)

found=0
for pat in "${patterns[@]}"; do
  # -p shows the patch; scope to additions only by grepping the diff.
  hits="$(git log -p --all 2>/dev/null | grep -nE "^\+.*$pat" || true)"
  if [ -n "$hits" ]; then
    echo "!! potential leak matching /$pat/ in history:"
    printf '%s\n' "$hits" | head -20
    found=1
  fi
done

if [ "$found" -eq 0 ]; then
  echo "==> history clean: no secret patterns found in any commit"
  exit 0
else
  echo "==> POTENTIAL SECRET IN HISTORY — rotate the secret and consider" >&2
  echo "    rewriting history (git filter-repo) before going public." >&2
  exit 1
fi
