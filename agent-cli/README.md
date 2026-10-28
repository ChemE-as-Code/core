# agent-cli

Runs Claude agents (Claude Agent SDK) on ChemE-as-Code repositories with a hard dollar cap, and
the overnight orchestration of process-library case studies.

It lives in `agent-cli/` of the cheme-as-code repository, with its own `pyproject.toml` and
`uv.lock`; the commands below run in this folder. cheme-as-code itself needs none of it (no agent
runner, no LLM provider). Project-specific job files, case lists, prompts, transcripts and results
stay outside git (`.gitignore`); `jobs/examples/` and `tasks/templates/` are the reusable parts.

## Setup

macOS / Linux:

```sh
uv sync                         # Python 3.12, claude-agent-sdk, pyyaml, psutil
export ANTHROPIC_API_KEY=...    # in ~/.zshrc; run.sh sources it
```

Windows (PowerShell):

```powershell
uv sync
[Environment]::SetEnvironmentVariable('ANTHROPIC_API_KEY', '...', 'User')   # once; run.ps1 reads it
.\run.ps1 --task-file tasks\x.md --cwd .. --budget 5                       # = run.sh
```

`cheme` (cheme-as-code) must be on PATH for process work. On Windows, Claude Code's PowerShell tool is
guarded like Bash (Remove-Item, Stop-Process, `Get-ChildItem env:`, ...).

## One run

```sh
./run.sh --task-file tasks/<task>.md --cwd <repo or process folder> --budget 10 [--unattended] [--slug name]
```

- The task text goes to an Opus 5.5 agent (`--model`, `--effort` to change) in `--cwd`, which
  loads that folder's CLAUDE.md, skills and settings.
- `--budget` is a hard limit in USD (the SDK stops the run).
- Guards (PreToolUse hooks): destructive shell commands (rm, `xargs rm`, git push/reset/clean,
  git worktree remove, gh pr merge, `gh api` with PUT/POST/PATCH/DELETE, ...) ask y/N, or are
  refused with `--unattended`; commands that could print the API key (also `os.environ`,
  `process.env`, `/proc/*/environ`) are refused; writes outside `--cwd` are refused (relative
  paths resolve against `--cwd`). Everything else runs without prompts. `tests/test_guards.py`
  pins these patterns: `uv run --with pytest pytest -q`.
- Headless sessions must not end their turn to wait: the waiting tools (ScheduleWakeup, Monitor,
  Cron*, RemoteTrigger) are disabled, the task gets a rule to run background work in the
  foreground and to end with `STATUS: DONE` / `STATUS: BLOCKED: <reason>` (or the task's own final
  line, e.g. `VERDICT: ...`). Without one, the runner sends up to `--nudges` (default 2)
  "continue" prompts in the same session.
- A session that crashes (Claude Code out of memory, native crash, ...) is still recorded in
  `runs.jsonl` with `subtype: crashed` and a cost estimated from its transcript
  (`cost_estimated: true`), so `night.py`'s ledger never counts it as free; without an estimate
  the ledger counts its full cap. The SDK message buffer is 64 MB (one large tool output exceeded
  the 1 MB default and killed sessions).
- The API key is read from the environment only, never printed or written.
- Every run appends cost, time, turns, tokens and session id to `runs.jsonl` and writes a
  transcript to `logs/<run-id>.log` (both git-ignored).
- In a plant repository or process folder (with `plant.yaml`) it calls `cheme runs record`
  (core ADR 0029; needs a current `cheme`), which writes and commits `runs/<run-id>/`: commits,
  times, API cost, tokens, the `cheme` commands run and `cheme check`/`maturity` after the run,
  the transcript (secret-scanned; kept out of git when the session used web tools), and the
  versions of core, pyDEXPI, Claude Code, the Agent SDK and this runner (`agent-cli` commit and
  dirty flag). The installed `cheme` and this runner are recorded independently, each from its
  own source; the record says `same_revision: true` only when both are the same clean commit
  (e.g. `cheme` installed from `git+…@<sha>` and the runner run from a clean checkout of that
  sha). It sets `CHEME_RUN_RECORD=off` so the folder's own session hooks do not write a
  second record.

### Approval of destructive commands

`--approve ask` (default) asks y/N; `--approve deny` (= `--unattended`) refuses them; `--approve auto` allows
them except a hard-deny list (force-push, pushing to main/master, deleting repositories or releases,
recursive deletes outside the tree) so agents can push their branches and merge their own PRs. Every
decision is appended to `logs/audit.jsonl`.

## Parallel jobs, supervised (`jobs.py`)

```sh
uv run jobs.py jobs/examples/issues.json --total 150 --dry-run   # what would run, caps vs limit
uv run jobs.py jobs/examples/issues.json --total 150             # run; same command again resumes
.\run.ps1 -Jobs jobs\examples\issues.json --total 150             # Windows
```

A job file lists agent jobs (`name`, `cwd`, `budget`, `task` or `task_file`, optional `preamble_file`,
`approve`, `model`, `effort`, `max_restarts`) and per job an optional `then` job, e.g. an independent review
that starts when the implementation ends with `STATUS: DONE` (see `jobs/examples/`). Each job is one
`agent.py` session; the supervisor

- starts a job only while `--min-free-gb` (8) RAM is free and fewer than `--max-sessions` (8) run, and only
  if the batch's spend (from `runs.jsonl`, crashed runs included) plus the caps of running jobs stays within
  `--total`;
- restarts a job whose session crashed or stopped without a final line (up to `max_restarts`), telling the
  new session about the partial work in its worktree; `BLOCKED` and budget-exhausted jobs are not retried;
- kills pytest runs older than an hour in the job folders (agents leave background test runs behind; they
  held 80 processes and 30+ GB in one run) and, below `--emergency-gb` (3) free RAM, the largest one;
- keeps state in `logs/jobs/<file>.state.json` and logs to `logs/jobs/<file>.log`; sessions are detached,
  so restarting the supervisor does not stop them.

Give each job its own git worktree (`git worktree add ../wt/<name> -b <branch> origin/main`) so parallel
sessions never share a checkout.

## Overnight orchestration

```sh
uv run night.py --cases cases.json --total 100 --lanes 6 [--only ammonia-1 hda-1]
```

The case list is a JSON file (`pid`, `title`, process-library `issue`, `skill`, `notes`; format in
`jobs/examples/cases.json`); `cases.json` here is git-ignored. The process-library checkout and the
worktree folder default to siblings of this repository (`CHEME_LIBRARY`, `CHEME_WORKTREES`).

Per case: a git worktree `<worktrees>/<pid>` on `case/<pid>`, `cheme init`,
then design (`tasks/templates/design.md`), push and PR, independent review
(`templates/review.md`), a fix run if the review says `VERDICT: fix`, CI, merge. The ledger
counts `runs.jsonl` since `LEDGER_SINCE` plus the caps of every running agent, so several
orchestrators cannot overspend together. It is resumable: finished stages and existing PRs are
reused. Agents never push or merge; the script does.

## Layout

| path | |
|---|---|
| `agent.py` | the runner (guards, budget, run record) |
| `run.sh` | loads the key from ~/.zshrc, then `uv run agent.py` |
| `night.py` | overnight orchestrator for process-library cases |
| `jobs.py` | generic parallel job supervisor (RAM, spend, restarts, follow-up jobs) |
| `procs.py` | cross-platform process and memory helpers (psutil) |
| `run.ps1` | Windows counterpart of `run.sh` |
| `jobs/examples/` | job file with implement/review preambles; `cases.json` format for night.py |
| `tests/` | guard patterns and the jobs state machine (`uv run --with pytest pytest -q`) |
| `tasks/` | prompts; `tasks/templates/` for night.py, `tasks/gen/` the prompts actually sent (not in git) |
