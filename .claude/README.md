# .claude/ — Project Claude Code Workspace

This directory configures Claude Code for the `shisuke-openbrain` project, following Boris Cherny's 10-tip pattern and the `shanraisshan/claude-code-best-practice` repo layout.

## Layout

```
.claude/
├── settings.json          # permissions, statusline, output style, attribution
├── commands/              # reusable slash commands (Boris tip 4)
│   ├── phase-start.md     # /phase-start <NN>   — begin a phase
│   ├── phase-verify.md    # /phase-verify <NN>  — run verify-phase-NN.sh
│   ├── db.md              # /db                  — psql shortcut
│   ├── mcp-test.md        # /mcp-test            — curl MCP server
│   ├── techdebt.md        # /techdebt            — end-of-session cleanup
│   └── secrets-scan.md    # /secrets-scan        — pre-commit secret grep
├── agents/                # subagents (Boris tip 8)
│   ├── plan-reviewer.md          # staff-engineer plan reviewer
│   ├── sql-migration-writer.md   # idempotent SQL author
│   ├── python-test-writer.md     # pytest + bats author
│   └── secret-scanner.md         # commit-time secret detector
└── rules/                 # coding standards loaded by main agent + subagents
    ├── commit-style.md           # no Claude attribution, conventional commits
    ├── sql-style.md              # additive-only, IF NOT EXISTS, never DROP
    └── python-style.md           # ruff + pep8 + type hints + async patterns
```

## How Boris's tips map to this project

| Tip | Where |
|---|---|
| **1. Parallel sessions via worktrees** | `plan/WORKTREE_WORKFLOW.md` + `/worktree-new` slash command |
| **2. Plan mode + plan review** | `plan/PLANNED_PHASES.md` + `plan-reviewer` subagent |
| **3. Living `CLAUDE.md`** | Root `CLAUDE.md` with guard rails; update after every correction |
| **4. Reusable commands** | `.claude/commands/` — every recurring task here |
| **5. End-to-end bug fixing** | `bug-fixer` agent (add later); use Docker logs + MCP |
| **6. Sharper prompting** | `plan-reviewer` agent challenges plans before code |
| **7. Terminal + statusline** | `settings.json` statusline shows `[branch] phase` |
| **8. Subagents** | `.claude/agents/` — domain-specific |
| **9. Data CLI access** | `/db` slash command = `psql` shortcut, our `bq` equivalent |
| **10. Learning style** | `settings.json` → `outputStyle: Explanatory` |

## Rules loaded automatically

Place global directives in root `CLAUDE.md`. Specialised rules in `.claude/rules/*.md` are referenced by subagents and slash commands explicitly.

## Updating this directory

- After correcting Claude on something repeatable → update `CLAUDE.md` or add a rule file.
- After running the same multi-step task twice → add a slash command.
- After noticing a class of bug → add an agent or extend the rule.
- Commit `.claude/` to git so the workspace is reproducible across machines.
