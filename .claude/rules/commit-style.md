# Commit Style Rule

## Scope

Applies to every `git commit`, `git tag -a`, and every PR description written by Claude in this repo.

## Hard rules

1. **No Claude / Anthropic / model-name attribution anywhere.**
   - Forbidden in commit subject, body, footers, PR titles, PR bodies, tag annotations.
   - This includes: `Co-Authored-By: Claude …`, `🤖 Generated with [Claude Code]…`, `claude-opus-4-7`, `Claude Opus 4.7`, `Sonnet`, `Haiku`, version strings.
   - If `settings.json` has an `attribution` block, both `commit` and `pr` fields must be empty strings.
   - Commits stand on their content alone.

2. **Conventional Commits subject.**
   - Format: `<type>(<scope>): <imperative description>`
   - Allowed types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`, `build`, `perf`, `style`.
   - Optional scope is a phase ID, a service, or a module: `feat(phase-02): …`, `fix(workers/pdf): …`, `chore(deps): …`.
   - Subject in imperative mood, no trailing period, ≤ 72 chars.

3. **Body.**
   - Wrap at 72 chars.
   - Explain **why**, not what (the diff shows what).
   - Reference the phase or task by name where relevant (`Closes Phase 1 acceptance criterion 1.5`).
   - List breaking changes under `BREAKING CHANGE:` if any.

4. **Trailers.**
   - `Refs: <issue-or-doc-path>` is encouraged.
   - `Signed-off-by:` is fine if the user signs commits.
   - No agent-identity trailers, ever.

5. **Bundling.**
   - One logical change per commit. Do not bundle phases.
   - If you find yourself writing "and also" in the body, split.

6. **Heredoc usage.**
   - When invoking `git commit -m "..."`, always pass multi-line bodies via heredoc to avoid shell quoting bugs.

## Examples

### Good
```
feat(phase-01): add sql/001_thoughts.sql with hnsw and gin indexes

Establish the core thoughts table per PLANNED_PHASES.md Phase 1.5.
Includes the HNSW vector index, GIN metadata index, and the updated_at
trigger. Migration is idempotent (CREATE INDEX IF NOT EXISTS).

Refs: plan/PLANNED_PHASES.md Phase 1
```

### Good
```
fix(mcp-server): reject embedding length mismatch in capture

asyncpg silently coerced over-length vectors before this change.
Add explicit length check that 401s with a clear message.
```

### Bad — model name in attribution
```
docs: update README

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
```
(Forbidden by this rule and `CLAUDE.md`.)

### Bad — bundled changes
```
feat: add SQL migrations, wire MCP tools, deploy to VPS
```
(Three phases in one commit. Split.)

## Enforcement

- `secret-scanner` agent runs before every commit to block leaked secrets in the message body.
- `commit-style` rule is read by the main agent before formulating a commit message.
- The CI workflow (when added in Phase 9.5) will reject PRs whose commits contain banned attribution patterns.
