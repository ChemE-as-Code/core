# A staged agent design run

How to let coding agents (Claude Code, headless) design a plant in stages, each stage followed
by an independent reviewer agent whose findings the next stage fixes first. It packages the
ASU-1 agent design test of 2026-10-18: six stages took a 500 t/d GOX air separation unit from an
empty `cheme init` repository to a basic-engineering draft (4 P&IDs, lists, layout, a
sign-off) for $29 of a $50 cap. Everything here ships with the template, in
`scripts/agent-run/` of every new plant repository.

## What you need

- `cheme` and `claude` (Claude Code) on PATH, or `CHEME` / `CLAUDE_BIN` naming them;
  an API key with a budget cap.
- A plant repository from `cheme init`, in git (`git init`, `cheme git-setup`).
- `scripts/agent-run/spec.md`: the plant specification, written once (capacity, products,
  site, sections and sheets, safety topics, quality expected). Every prompt includes it.
- `scripts/agent-run/stages.json`: the stages, each with `id`, `target` (a `plant.yaml` stage),
  `task`, `budget_usd` and `review_budget_usd`.
- A trusted folder, or the runner's `--settings .claude/settings.json` (see "Running agents
  headless" in REFERENCE.md): without either, `.claude/settings.json` is ignored and commands are
  denied. With `--settings` Claude Code still prints `Ignoring N permissions.allow entries`
  for the untrusted project file while the entries apply from the flag; the runner's
  `permission_denials` count in `launch.json` is the measure.

## Running a stage

From the repository root, one stage and its review at a time:

```sh
python3 scripts/agent-run/run_stage.py stage S1 --dry-run     # print the prompt, run nothing
python3 scripts/agent-run/run_stage.py stage S1 --budget 3
python3 scripts/agent-run/run_stage.py review S1 --budget 2
```

The runner is standard library only and runs on python3 3.9 or later, so macOS's
`/usr/bin/python3` (3.9.6) is enough; `uv run python scripts/agent-run/run_stage.py ...` works too.

Then read the review, merge the stage branch (a human or the reviewer, never the stage agent;
see the template's `AGENTS.md`) and run the next stage. The runner has no user-specific paths:
re-running S1 on a fresh `cheme init` repository needs only the commands above, `spec.md`
and a budget.

The runner (`run_stage.py`, standard library only) calls

```
claude -p <prompt> --output-format json --max-turns 200 --max-budget-usd <budget>
       --settings .claude/settings.json --allowedTools <allowed-tools.txt>
```

and writes to `build/agent-run/<stage>/`: `prompt.txt` (the exact prompt), `launch.json`
(command, cheme-as-code version, HEAD, start and end time, exit code, `total_cost_usd`,
`num_turns_last_segment`, the number of `permission_denials`), `result.json` (Claude Code's
JSON result), `stderr.log` and, last, `done`. The review goes to
`build/agent-run/<stage>/review/` and the reviewer writes `build/agent-run/<stage>/review.json`.
The allowed tools are in `scripts/agent-run/allowed-tools.txt`, one per line: read-only shell
commands, `cheme`, `git` add/commit/switch, Edit and Write -- deliberately no `sed -i`,
`awk`, `cp` or heredocs. A stage that needs more (`npm` and `npx` for a viewer stage) lists
them as `"extra_tools": ["Bash(npm:*)", "Bash(npx:*)"]` in its `stages.json` entry, or gets
`--extra-tool 'Bash(npm:*)'` (repeatable); without them that session runs into permission
denials.

### A chain of sessions inside one total

`--total-cap USD` keeps the whole run inside one budget: before a session starts, the runner
adds up `total_cost_usd` of every earlier `result.json` under `build/agent-run/` (stages and
reviews), lowers this session's `--max-budget-usd` to what is left and skips the session (exit
3) when nothing is. `total_cost_usd` is cumulative and the number to use; `num_turns` counts
only the last segment of a session that ended after a background task (one session showed
"1 turn" at $5.23), so `launch.json` keeps it as `num_turns_last_segment`.

```sh
python3 scripts/agent-run/run_stage.py stage S2 --total-cap 50
```

### Waiting for a session

The runner writes `build/agent-run/<stage>/done` (`exit N`) after everything else; it prints
`<stage> stage: exit N in <dir>`. Wait on that file or that line. Do not wait with `pgrep -f
...`: it matches the waiting shell's own command line and never returns.

### After a stage: check, do not trust

Never accept a session's summary as the result. The orchestrator (a person or the agent
running the chain) re-runs, on the stage branch, what the summary claims: `cheme validate`,
`cheme fmt --check`, `cheme check --stage <target>`, the renders, and in a cheme-as-code
checkout the test suite -- an integration report once left a `TEST_COUNT` placeholder where
the number of passing tests belonged. `launch.json` records cost, turns and the number of
`permission_denials` for the record.

### Runs against a development build

When the stage tests a cheme-as-code branch, point the plant repository's git hooks at that
build: in the plant repository (or its worktree) run `uv run --project <cheme-as-code
checkout> cheme git-setup`, and set `CHEME` to that build's `cheme`. A hook installed by an
older global `cheme` rejects the newer schema, and a session that then bypasses the hook
(`--no-verify`) commits unchecked work: the stage prompt and the template's `AGENTS.md`
forbid that from the first stage on. Give every session its own worktree and branch and push
nothing; the orchestrator opens the pull requests after its own checks.

## The stage prompt

`scripts/agent-run/stage-prompt.md`, filled per stage:

- the role and the rules: work as `AGENTS.md` and the skills say, start with `cheme status`,
  Edit/Write only, one command per Bash call, a branch `stage/<target>-<stage>`, commit midway,
  never bypass a git hook (`--no-verify`), no self review or sign-off, end with a summary saying
  whether a merge is pending;
- `PLANT SPECIFICATION`: `spec.md`;
- `THIS STAGE`: the task from `stages.json`, then what `cheme status --json` says is left:
  the sheets already drawn ("never draw them again" -- in the ASU run the stage text fell one
  sheet behind and S3 was told to draw a sheet S2 had drawn), the sheets not drawn yet, the next
  sheet to draw, the failing gates of every stage up to the target and the validation counts by
  sheet;
- `FIX FIRST`: the previous review's `carry_over` list and the open review findings.

## The reviewer prompt

`scripts/agent-run/reviewer-prompt.md`. The independent reviewer did the most useful work of the
ASU run (it found the shared LOX tank / GOX blowdown vent, the missing GOX suction vent and the
compander oil path). It is an agent other than the stage agent, with its own budget. It checks
`cheme status`, `validate` (and `--fail-on warning`), `fmt --check`, the stage's commits and
`diff main --list`, the lists against the sheets, DESIGN.md numbers, `check --stage <target>`,
and renders each new or changed sheet to PNG and reads it. It writes

1. a review record `reviews/<date>-<stage>-review.md` with front matter (`reviewer_kind:
   agent`, `reviewed_commit`, `scope`, `branch`, `merge`), findings with ids, severity and
   status, and a Previous findings section (the format of `reviews/README.md`), so the next
   stage and `kind: review` gates see it; and
2. `review.json`: `scores` (process, safety, drawing, consistency, 0-5), `acceptable`,
   `findings` (`id`, `severity`, `where`, `finding`, `fix`) and `carry_over`, the hand-over list
   for the next stage's `FIX FIRST`.

The reviewer's record is an agent review: a stage passes a `require_kind: [human]` gate only
after a person has reviewed it, and `cheme check --write` refuses a self-signed review.

## Budgets

From the ASU run (S1 $2.18, S2 $5.85, S3 $4.66, S4 $5.64, S5 $5.67, S6 $5.11 at 44-167 turns):

| stage type | budget |
|---|---|
| concept (design basis, DESIGN.md, lists, gates; no XML) | about $3 |
| one large sheet (30,000-50,000 lines of DEXPI) with its lists | $6-8 |
| fixes from a review plus a small sheet | $5-6 |
| layout (site plan, placement, separations, racks) | about $5 |
| close-out: fixes, review record by the reviewer, merge, sign-off by a human | $5-6, split |
| independent review | $2-3 |

Draw one large sheet per stage: S2 stopped with about $2 left and put P-03 off. Split the
close-out into layout, then fixes, then review and sign-off: S6 combined them and used 167 turns
and $5.11 of $6. Commit midway in every stage.

## The run record

Records are kept per run, not per stage: every session, stage or review, leaves its own folder
`runs/<run-id>/` in the plant repository (run id: the start in UTC, `YYYYMMDD-HHMMSS-<slug>`, the
slug the stage id or `review-<stage>`), written by `cheme runs record` (ADR 0029; the format is
in REFERENCE.md, "Run records"):

| file | holds |
|---|---|
| `run.yaml` | schema `process-run/v1`: kind `agent`, start and end commit, times, cost (`total_cost_usd` of `result.json`), budget, model, turns, tokens, the `cheme` commands the agent ran, `cheme check` / `cheme maturity` after the run, and the software versions (`tools`, below); `complete: false` with notes when a fact is missing |
| `task.md` | the exact prompt (`build/agent-run/<stage>/prompt.txt`) |
| `report.md` | the session's final message (`result` of `result.json`) |
| `session.jsonl.gz` | the Claude Code transcript; kept in `build/run-records/` instead when the session used web tools, and not exported when it holds an API key |

`run_stage.py` notes HEAD before the session, runs Claude Code with `CHEME_RUN_RECORD=off` and
then calls `cheme runs record --session-id <id> --kind agent --slug <stage> --task-file
prompt.txt --cost <total_cost_usd> --budget <cap> --start-commit <sha> --checks --commit
--runner-name run_stage.py`, which commits the run folder alone (`<process>: run record
<run-id>`) before `done` is written. An external runner does the same.

`tools` in `run.yaml` pins the software that produced the run (`cheme schema process-run`):

| field | from |
|---|---|
| `cheme` | the installed cheme-as-code version |
| `core_commit`, `core_dirty` | the commit of a git install (`direct_url.json`, clean), else the HEAD of the source checkout of an editable or local install and whether it had uncommitted changes (untracked files count) |
| `pydexpi` | the installed pyDEXPI version |
| `claude_code` | the `version` of the transcript's last line, else `claude --version` |
| `claude_agent_sdk` | `--sdk-version`, passed by a runner built on the Claude Agent SDK |
| `runner` | `{name, commit, dirty}` from `--runner-name`, `--runner-commit`, `--runner-dirty` (or `--runner-clean`); `run_stage.py` gives only its name, its commit being the plant repository's start commit |
| `same_revision` | `true` only when `core_commit` and the runner's commit, each read from its own source, are the same commit and neither checkout had changes (the runner in `agent-cli/` of the same clean checkout); `false` when they differ or either is dirty; null when either commit is unknown |

A version nobody knows is null; a null in `tools` never makes a record incomplete. Records
written before these fields existed stay valid. Interactive sessions record themselves through the template's
hooks (`SessionStart`: `cheme runs start --hook`, `SessionEnd`: `cheme runs record --hook`;
uncommitted, skipped when nothing changed); `CHEME_RUN_RECORD=off` keeps the hooks of a session
that its runner records from writing a second record. A record is never edited; a revision is a
new run. `cheme runs list` gives one line per run (cost, wall time, turns, complete).

`build/agent-run/<stage>/` keeps its working files (`launch.json`, now with `run_record`,
`result.json`, `stderr.log`, `review.json`, `done`). The assessment of a whole design run
(quality by area, what worked, where agents struggled, next steps) is a review record in
`reviews/`, citing the run ids.

## Related

- Branches and merges: the template's `AGENTS.md`, `STAGES.md` and the `review` skill (stage
  work on `stage/<stage>-<topic>`, merged by a human or the reviewer; a stage counts once its
  sign-off is on the default branch).
- Headless permissions: "Running agents headless" in REFERENCE.md.
- Where the repository stands between stages: `cheme status [--json]`.
- Sign-off: `cheme check --stage <stage> --write --review <record>`.
