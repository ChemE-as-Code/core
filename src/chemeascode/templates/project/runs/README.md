# Run records

One folder per design session, `runs/<run-id>/` (run id: the start in UTC, `YYYYMMDD-HHMMSS`,
then optionally `-<slug>`):

| file | holds |
|---|---|
| `run.yaml` | schema `process-run/v1` (`cheme schema process-run`): kind, start and end commit, times, cost as reported (never estimated), budget, model, turns, tokens, the `cheme` commands run, checks after the run; `complete: false` with `incomplete_notes` when a fact is missing |
| `task.md` | what the session was asked |
| `report.md` | what it reported (optional) |
| `session.jsonl.gz` | the Claude Code transcript, when it may be published (no API key in it, no web tools used; otherwise it stays in the ignored `build/run-records/`) |

`cheme runs record` writes a folder: the hooks in `.claude/settings.json` do it at the end of an
interactive session that changed something (left for you to commit), the agent runner
(`scripts/agent-run/run_stage.py`) after each session it starts (committed alone). Set
`CHEME_RUN_RECORD=off` to switch the hooks off. `cheme runs list` lists the records.

Never edit or delete a record: a revision is a new run.
