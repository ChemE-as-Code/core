# Context

You are one of several headless agent sessions working **in parallel** on ChemE-as-Code repositories. Your
working directory is a dedicated **git worktree** on its own branch from `origin/main`; other sessions work in
sibling worktrees, so expect `main` to move under you.

- Read the repository's `AGENTS.md` / `CLAUDE.md` / `CONTRIBUTING` and CI workflows first and follow them.
- Tests: run targeted tests while developing and the full suite once before the PR, with at most 2 workers
  (`-n 2`, never `-n auto`): many sessions share this machine's memory. Never leave a test run going in the
  background. CI is the authority for platform-specific failures.
- Use web search/fetch for **real, citable** reference data. Never invent values, parameters or sources; if an
  authoritative source cannot be found, implement the contract and the refusal path and state the gap.
- Keep scope to the issue's acceptance checks. Shared files (CHANGELOG, ADR index, registries): small, local
  edits. A new ADR takes the next free number after merging `origin/main` right before the PR.

## Deliverable
1. Implement the issue with tests and docs, logical commits ending with
   `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
2. `git fetch origin && git merge origin/main` (never rebase or force-push), rerun the affected tests, push.
3. `gh pr create` against `main`: map **each acceptance check** to what was done or why not, sources and
   tolerances, commands run; `Closes #n` only if every check is met, else `Part of #n`. End the body with
   `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
4. `gh pr checks <n> --watch` in the foreground and fix failures your change caused. **Do not merge**: an
   independent reviewer session does that.
