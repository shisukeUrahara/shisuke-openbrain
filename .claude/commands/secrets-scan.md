---
description: Scan staged changes (and optionally full history) for leaked secrets before commit/push.
argument-hint: <staged|history>  (default: staged)
---

# /secrets-scan

Pre-commit / pre-push guard. Hunts for accidental secret leaks per `CLAUDE.md` guard rails.

## Inputs

- `$1` — scope. `staged` (default): only what's in the git index. `history`: full `git log -p`.

## Patterns to detect

| Class | Regex | Example match |
|---|---|---|
| Brain key | `BRAIN_KEY=[a-f0-9]{40,}` | 64-hex key in env file |
| OpenRouter | `sk-or-v1-[A-Za-z0-9]{40,}` | OpenRouter API key |
| OpenAI | `sk-[A-Za-z0-9]{32,}` | OpenAI / proxy key |
| Anthropic | `sk-ant-[A-Za-z0-9_-]{40,}` | Anthropic key |
| Telegram bot | `[0-9]{8,12}:[A-Za-z0-9_-]{30,}` | BotFather token |
| Supabase service role | `eyJ[A-Za-z0-9_-]{40,}\.[A-Za-z0-9_-]{40,}\.` | JWT-shape |
| Generic password | `(POSTGRES_PASSWORD|DB_PASSWORD|PASSWORD)\s*=\s*["'][^"' ]{8,}` | Inline password |
| AWS access key | `AKIA[0-9A-Z]{16}` | AWS access key id |
| GitHub PAT | `gh[pousr]_[A-Za-z0-9]{36,}` | GitHub fine-grained / classic PAT |
| Cloudflare API | `CLOUDFLARE_API_TOKEN\s*=\s*[A-Za-z0-9_-]{30,}` | CF token |

## Steps

1. Pick source:
   - `staged` → `git diff --cached -p`
   - `history` → `git log -p` (warn: slow on large repos)

2. Pipe through `grep -inE '<pattern1>|<pattern2>|…'` with the patterns above.

3. For each hit:
   - Show the file path + line number.
   - Show the matched line, with the secret value masked (`…` after first 4 chars) before displaying to the user.

4. If any hit:
   - **Block** the commit/push. Print: `ABORT: <N> potential secret(s) detected`.
   - Suggest fix: move value to `.env`, ensure `.env` is gitignored.
   - For `history` scope hits: warn that the secret is already in remote history if the branch was ever pushed. Tell the user to rotate the secret immediately and consider `git filter-repo`.

5. If clean: print `✓ no secrets detected in <scope>`.

## Exit semantics

- Exit `0` on clean.
- Exit `1` on any hit so the command can be wired into a `pre-commit` hook later.
