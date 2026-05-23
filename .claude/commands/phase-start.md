---
description: Begin a phase from plan/PLANNED_PHASES.md. Creates branch, scaffolds, runs prerequisite checks.
argument-hint: <phase-number e.g. 01>
---

# /phase-start

Start work on a phase defined in `plan/PLANNED_PHASES.md`.

## Inputs

- `$1` — phase number (zero-padded, e.g. `00`, `01`, `12.b`).

## Steps

1. **Verify previous phase is green.**
   - Determine the previous phase number `N-1`.
   - Run `bash scripts/verify-phase-$(printf '%02d' $((N-1))).sh` if it exists. If it fails, STOP and tell the user the previous phase has unmet acceptance criteria.

2. **Check working tree clean.**
   - `git status --short` → must be empty. Otherwise stash or warn.

3. **Re-read the phase section** in `plan/PLANNED_PHASES.md` for the requested phase. Summarise:
   - Goal
   - Prerequisites
   - Acceptance criteria
   - Risks
   - Per-task verification commands

4. **Create branch.** Convention from `plan/IMPLEMENTATION_STRATEGY.md`:
   ```
   git checkout -b feat/phase-<NN>-<short-slug>
   ```
   Slug comes from the phase title (kebab-case, ≤ 4 words).

5. **Scaffold files** the phase will fill. Create empty file stubs only — do not implement yet. The user explicitly chose `plan-then-implement`.

6. **Stub failing tests** for any deterministic pieces (see `plan/IMPLEMENTATION_STRATEGY.md` §4 — TDD candidates).

7. **Report** to the user:
   - Branch name
   - Files scaffolded
   - First subtask to implement next
   - Estimated time

## Failure modes

- Phase number missing → ask for it.
- Phase not in PLANNED_PHASES.md → stop and tell the user.
- Previous phase verification failed → do not proceed.

## Output style

Terse. Bullet list of created files. One sentence per next step.
