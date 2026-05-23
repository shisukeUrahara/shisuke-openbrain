---
description: End-of-session sweep — find duplication, dead code, missing tests, drift between sql/ and DB.
---

# /techdebt

Boris Cherny's pattern. Run at the close of a working session before merging a branch.

## Scope checks

### 1. Code duplication
- Run `rg --type py -A 5 "def " services/ | sort | uniq -c | sort -rn | head -20` to spot likely repeated function bodies. Flag suspects ≥ 2 occurrences with similar signatures.
- Run `rg --type py "TODO|FIXME|XXX|HACK" services/ | head` and list outstanding markers.

### 2. Dead code
- For each Python module added in this branch: check that at least one test imports it.
  ```bash
  for mod in $(git diff --name-only main...HEAD | grep 'services/.*\.py$' | grep -v test_); do
    name=$(basename "$mod" .py)
    if ! rg -q "import .*\\b$name\\b|from .*\\b$name\\b" services/*/tests/; then
      echo "untested: $mod"
    fi
  done
  ```

### 3. Missing tests
- Every public function added/modified in this branch should have ≥ 1 test. List ones that do not.
- Read `plan/PLANNED_PHASES.md` Section C — confirm test layer matches task type (unit / integration / e2e / smoke).

### 4. SQL drift
- Compare `sql/` migrations against live DB:
  ```bash
  expected=$(sha256sum sql/*.sql sql/modules/*/*.sql 2>/dev/null | sha256sum | cut -d' ' -f1)
  ```
  Compare to a stored fingerprint in `plan/SCHEMA_FINGERPRINT.txt` (if it exists). Mismatch = drift; tell user to regenerate.

### 5. Secrets hygiene
- `git diff main...HEAD -p | grep -iE 'BRAIN_KEY=[a-f0-9]{32}|sk-or-v1-|password\s*=\s*["'\''][^"'\'' ]{6,}'` — any hit blocks the session close.

### 6. Module flag coverage
- For every newly added MCP tool, verify it sits behind a `if config.modules.X` guard if it belongs to an optional module.
- For every new docker-compose service, verify it has a `profiles:` entry if it is module-gated.

### 7. CLAUDE.md drift
- If the user corrected the agent during this session for something not yet in `CLAUDE.md`, propose a one-line addition. Do not auto-edit — ask first.

## Output

A single markdown checklist with one box per finding. Each box has:
- file path + line(s)
- one-line description
- suggested fix (file:line edit, command, or "delete")

The user picks which to address before merging the branch.
