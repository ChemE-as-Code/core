# 0029. Run records per run in the plant repository, written by core

- **Status:** Proposed
- **Date:** 2026-10-27
- **Amended 2026-10-28:** `tools` pins every software version of a run, all optional so earlier
  records stay valid: `core_commit` also for an editable or local install (HEAD of the source
  checkout, after `direct_url.json`) with `core_dirty`, `pydexpi`, `claude_code` (the
  transcript's `version`, else `claude --version`), `claude_agent_sdk` (`--sdk-version`) and
  `runner` (`--runner-name`, `--runner-commit`, `--runner-dirty`). A null value never makes a
  record incomplete.
- **Amended 2026-10-28 (monorepo):** the agent runner lives in `agent-cli/` of this repository.
  `core_commit` and the runner commit are still recorded independently, each from the source
  that was installed or executed; `same_revision` says whether they are one clean commit, and is
  `false` when either checkout is dirty.

## Context

Design sessions on a plant repository (interactive Claude Code sessions and headless agent runs)
left their traces in `build/agent-run/<stage>/` (ignored) and, by hand, in a per-stage folder
under `reviews/<date>-agent-design-run/` (`docs/agent-design-run.md`). The cost, the turns, the
commits a session started and ended on, and what it was asked were therefore lost for
interactive sessions and copied by hand, per stage, for agent runs; a stage with a revision had
no place for its second session. The process library decided a format for these records
(ChemE-as-Code/process-library ADR 0020, `docs/run-records.md`): one folder per run, not per
stage, `runs/<run-id>/` with `run.yaml` (schema `process-run/v1`), `task.md`, an optional
`report.md` and the gzipped session transcript; unknown values null, never guessed; a revision
is a new run. Every plant repository needs the writer, so it belongs to core, which ships the
project template and its hooks.

Options considered: a writer in the process library (only its plants would record); a script
in the template (stdlib only, copied into every plant, hard to update); a `cheme` command,
updated with the tools, called by Claude Code hooks for interactive sessions and by runners for
headless ones.

## Decision

- cheme-as-code owns the run-record format and its writer. `runs/<run-id>/run.yaml` follows
  `chemeascode.foundation.schemas.run_record.RunRecord` (`cheme schema process-run`);
  `run_id` is the start in UTC, `YYYYMMDD-HHMMSS`, optionally `-<slug>`. A value nobody knows
  is null; `complete` is false when a fact the recorder looks for (start and end commit, start
  and finish, session id, turns and tokens, the task, the transcript in the folder) is missing,
  and `incomplete_notes` says which and why. A cost or budget that the caller does not know is
  null without making the record incomplete; a cost is never estimated (`cost_source: api` only
  when the caller passed the API's figure).
- `cheme runs start` writes the start of a session (HEAD, branch, time, a digest of the working
  tree) to `build/run-records/<session id>.start.json`; `cheme runs record` composes the record
  from it (or `--start-commit`), the Claude Code transcript (`integrations/claude_code.py`,
  tolerant of unknown lines: each API message's usage counted once, by `message.id`) and the
  caller's facts, and writes the folder. `--checks` records `cheme check` and `cheme maturity`
  (run in-process) after the run; `--commit` commits the run folder alone. `cheme runs list`
  reads the records. An existing folder is refused: records are never edited.
- The project template's `.claude/settings.json` runs `cheme runs start --hook` on
  `SessionStart` and `cheme runs record --hook` on `SessionEnd`. A hook never fails the session
  (any error: one line on stderr, exit 0), never commits, never runs checks, and records nothing
  when HEAD and the working tree are as at the start, or when `CHEME_RUN_RECORD=off` (set by a
  runner that records its sessions itself). `scripts/agent-run/run_stage.py` records each
  session with `--kind agent --checks --commit --runner-name run_stage.py`.
- The transcript is published only when it is safe to: holding `sk-ant-` or the value of
  `ANTHROPIC_API_KEY` it is not exported at all; after WebFetch, WebSearch, `curl` or `wget`
  it is written to the ignored `build/run-records/` instead of the run folder. Otherwise it is
  gzipped with mtime 0 and its sha256 recorded.

## Consequences

- Positive: every session that changed a plant repository leaves a record, interactive ones
  included, with what it cost and on which commits it started and ended; the format has one
  owner and one writer, updated with `uv tool upgrade`; a runner needs one command.
- Positive: a record is reproducible from its inputs (the gzip carries no time stamp) and
  never rewritten, so the history of runs is append-only in git.
- Negative: interactive records stay uncommitted until the person commits them; a session that
  resumes an earlier one is recorded from its resumption, with the transcript lines before it
  left out. A cost is known only for headless runs (the API's `total_cost_usd`).
- Negative: `--commit` runs the repository's pre-commit hook like any commit; a hook that
  refuses (an invalid P&ID) leaves the record uncommitted and the command exits 1.
- Known limitations: Claude Code's transcript format is not a published contract; the reader
  skips what it does not understand and reports the count as incomplete. `effort` is recorded
  only when the caller passes it. Publication excludes `runs/**` in the process library.

## Evidence

- `src/chemeascode/foundation/schemas/run_record.py`, `src/chemeascode/integrations/claude_code.py`,
  `src/chemeascode/project/run_records.py`, `src/chemeascode/interfaces/cli/runs.py`.
- `src/chemeascode/templates/project/dot-claude/settings.json` (hooks),
  `src/chemeascode/templates/project/scripts/agent-run/run_stage.py`,
  `src/chemeascode/templates/project/runs/README.md`, `docs/agent-design-run.md`.
- `tests/test_run_records.py`, `tests/test_agent_run.py`.
