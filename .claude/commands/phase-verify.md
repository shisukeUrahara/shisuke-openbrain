---
description: Run a phase verification script and report pass/fail with diagnostic detail.
argument-hint: <phase-number e.g. 01>
---

# /phase-verify

Run `scripts/verify-phase-<NN>.sh` and report whether the phase is complete.

## Inputs

- `$1` — phase number, zero-padded (`00`, `01`, `02`, …).

## Steps

1. **Locate** `scripts/verify-phase-$1.sh`. If missing, tell the user the verify script for that phase has not been authored.

2. **Run** the script and capture stdout + stderr:
   ```bash
   bash scripts/verify-phase-$1.sh
   ```

3. **Interpret exit code:**
   - `0` → phase is complete. Report ✅ and list any next-phase prerequisites from `plan/PLANNED_PHASES.md`.
   - non-zero → list the failing checks verbatim from the script's output. For each:
     - identify the file or command that is missing/broken
     - propose one concrete fix (file to create, command to run, env var to set)

4. **Cross-reference** with the phase's "Acceptance Criteria" section in `plan/PLANNED_PHASES.md`. If the script passes but acceptance criteria mention manual checks (e.g. "captured thought visible from second client"), surface those for the user to confirm.

5. **Suggest** the next command:
   - On pass: `/phase-start <next>`.
   - On fail: name the single highest-impact subtask to attack first.

## Notes

- This command is read-only by default. It does not edit files. If the user wants you to fix the failing checks, they will ask.
- Always pass the script's actual exit code through — do not soft-fail.
