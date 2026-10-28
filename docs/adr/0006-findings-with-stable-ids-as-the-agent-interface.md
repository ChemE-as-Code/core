# 0006. Findings with `file:line`, rule id, hint and a stable id as the agent interface

- **Status:** Accepted
- **Date:** 2026-10-17 (`file:line` findings); stable ids and `accept:` on 2026-10-18

## Context

An agent (or an engineer) fixing a plant needs to know exactly where a problem is and what to
do about it, in a form that survives edits. Free-form reports, dialogs or GUI markers are not
actionable by a coding agent. Some findings are deliberate design choices and must be
acknowledgeable without silencing the rule everywhere.

## Decision

- Every check produces `Finding`s (`foundation/findings.py`): file, line where known, level
  (error/warning/info), rule id (`cheme.<rule>` or `dexpi.<rule>`), the object ids concerned, a
  message and a hint. Text output is one line per finding,
  `file:line: level rule [ids]: message (hint)`; `--json` gives the same data.
- Each finding has a stable id `<file>#<rule>:<subject>`, independent of line numbers.
  `checks/checks.yaml` `accept:` entries name these ids with a reason. Warnings and infos can be
  accepted; errors cannot. Unused accepts are reported.
- Exit codes are part of the interface (`--fail-on`, gates); the CLI is what agents call.

## Consequences

- Positive: an agent can act on one line; CI, pre-commit hooks, gates, the viewer and review
  records all share the same findings and ids.
- Positive: deliberate deviations are recorded in git with a reason, typically a `D-NNN`
  decision of the plant's `DESIGN.md`.
- Negative: rule ids and the id format are a public contract; renaming a rule breaks
  `accept:` entries in plant repositories (as the rename in [0018](0018-rename-plantcode-to-cheme-as-code-without-aliases.md) did).
- Negative: the subject of an id depends on readable, stable XML ids, which `cheme fmt` has to
  keep ([0003](0003-dexpi-xml-via-pydexpi-as-the-pid-format.md)).

## Evidence

- pre-release commit 62c29e1 (0.1.0 validate with `file:line` findings).
- Stable ids and accepted findings: pre-release commit bb4cbae, pre-release commit 8ec87fa
  in pre-release PR 34 (pre-release issues 11, 18, 29, 30).
- `src/chemeascode/foundation/findings.py` (`Finding.id`), `README.md` ("Accepting a finding"),
  `AGENTS.md` ("Every finding a command prints names a file, a line where known, a rule id and a
  hint").
