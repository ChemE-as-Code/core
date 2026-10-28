# Staged agent design run

A repeatable way to let coding agents design this plant in stages, each followed by an
independent reviewer agent. The full description, record layout and budget guidance are in
cheme-as-code's `docs/agent-design-run.md`.

1. Write the plant specification into `spec.md`; adjust `stages.json` (stage id, target stage of
   `plant.yaml`, task, budgets).
2. Trust the folder once in Claude Code, or rely on `--settings .claude/settings.json` (the
   runner passes it and `allowed-tools.txt`).
3. Per stage, from the repository root:
   ```sh
   python3 scripts/agent-run/run_stage.py stage S1 --dry-run   # look at the prompt
   python3 scripts/agent-run/run_stage.py stage S1 --budget 3
   python3 scripts/agent-run/run_stage.py review S1 --budget 2
   ```
   The runner uses the standard library only and runs on any python3 from 3.9 (macOS's
   `/usr/bin/python3`); `uv run python scripts/agent-run/run_stage.py ...` works too.
4. A human merges the stage branch after reading the review; signs off with
   `cheme check --stage <stage> --write --review reviews/<record>.md`.

The prompt's `THIS STAGE` comes from `cheme status --json` (sheets already drawn are never
assigned again; failing gates), `FIX FIRST` from the previous review's `carry_over` and the open
review findings. Outputs go to `build/agent-run/<stage>/`: `prompt.txt`, `launch.json`,
`result.json`, `stderr.log`, the reviewer's `review.json` and, last, `done` (wait for it).
After each session the runner writes a run record with `cheme runs record ... --checks --commit`
(`runs/<run-id>/`, committed alone; see `runs/README.md`), and starts the session with
`CHEME_RUN_RECORD=off` so that the session's own hooks do not record it a second time.
`--total-cap USD` keeps a chain of sessions inside one total (it sums `total_cost_usd`, never
`num_turns`); `extra_tools` in `stages.json` or `--extra-tool` allow more for one stage. Check
each stage's work yourself (`cheme validate`, `check`, the renders) before merging: a
session's summary is not evidence.
