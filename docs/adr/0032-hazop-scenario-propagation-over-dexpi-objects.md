# 0032. HAZOP scenario propagation over the DEXPI objects, with the failure modes as project data

- **Status:** Proposed
- **Date:** 2026-10-28

## Context

The skill `hazop-scenario-propagation` asks an agent to find the causes of a node's deviations
and to follow each one over the P&ID, object by object, to a top event. An agent can do this
with `cheme show`, but the walk is long, easy to cut short and different from run to run. The
walk itself needs no judgement: given what each kind of object can fail into and what it does
with an incoming deviation, the path is a function of the P&ID. The judgement (which causes are
credible, what the outcome is, which safeguards work) stays with the team.

Two forces shape how:

- **No licensed content.** The failure modes and responses of equipment are the kind of data
  the HAZOP literature tabulates. Until a licence is cleared, cheme-as-code ships none of it.
- **Simplicity and isolation.** cheme-as-code builds no P&ID graph today: `cheme show` walks the
  XML itself. pyDEXPI has a graph loader (networkx levels `complete`, `process`, `conceptual`,
  `process_flow`), but its `process` level collapses and drops objects (piping nodes, piping
  systems) by rules this project does not control. A shared graph layer would have a single
  user. Options considered: a topology module in `domains/piping` on pyDEXPI's graph loader; a
  graph built inside `domains/safety`; walking the pyDEXPI objects directly.

## Decision

- `domains/safety/propagation.py` walks the **pyDEXPI objects** of the study's analysed P&IDs
  directly: `Pipe` source to target is the flow direction, a nozzle stands for its equipment, an
  off-page connector is a study limit, an instrument function senses at its sensing location and
  actuates the valve of its actuating system. Its only index is private to the module (plain
  dicts built once per call). No graph library is imported and no graph is exported.
- `propagate()` is a **pure function**: the caller (`project/hazop.py`) reads the files and passes
  the models, the library and the plant context (C&E interlocks, fail positions of
  `control/loops.yaml`) in. Deterministic and without LLM calls (ADR 0010).
- The failure modes are **project data** in `safety/failure-modes.yaml`
  (`cheme/failure-modes/v1`, kind `failure-modes`): per DEXPI class its modes (the deviation each
  gives, what it needs, the fail position it applies at) and responses (to an incoming deviation,
  by inlet or outlet: responds, passes, no-effect, absorbs, stops at a top event). An object
  takes the entry of its most specific class that has one. cheme-as-code ships the schema and the
  engine; tests use synthetic data. Where the content comes from and under which licence is the
  library's `source:`.
- `cheme safety hazop propagate STUDY --node N [--deviation D]` prints the candidate scenarios
  (cause, path, top event or limit, candidate safeguards, questions) and **writes nothing**.
  Safeguards are collected along the path and never stop it. What the files do not settle (a
  fail position not recorded, a response the library lacks, the fluid at a top event) is a
  question on the candidate, never a choice.
- The walk is **breadth first and reports outcomes, not routes**: per cause it takes each object
  with a given deviation and direction once, and keeps one candidate per outcome (deviation at
  the node, end, top event, the object it ends at) on its shortest path. A valve whose DEXPI
  `Role` is normally closed, locked closed or car sealed closed stops a walk (the line-up of
  normal operation). The command prints one line per outcome with its causes; `--paths` and
  `--json` give every candidate. On the pump-station case (14 nodes) enumerating every route
  gave 126,643 candidates, 31 % of them cut off at the depth limit in loops through recycles
  and closed valves; outcomes on shortest paths give 12,011, none cut off.
- **Causes are the node's, consequences are wherever the walk ends.** 74 % of the case's
  top-event candidates lie in another node than their cause, and some top events are reached
  from up to seven nodes. Each candidate names the other nodes its path enters (and where), and
  `propagate STUDY` without `--node` groups every node's top events by consequence, so the team
  discusses a shared consequence once. A node never repeats another node's cause: a deviation
  entering from outside is that node's reference, not a new row.
- **The walk checks the study; it does not seed it.** `propagate --coverage` compares each
  node's scenarios with its top events by tag (the deviation, the cause and the object the walk
  ends at named in the scenario's `refs`; no text is compared, ADR 0010) and lists what no
  scenario covers, and the scenarios no walk reaches. A gap is closed by a scenario or by a
  `dismissed:` entry on the node with its reason, a proposal like every other. Seeding rows from
  the walk was set aside: it anchors the draft on the library and hides what the library lacks.
- If another domain needs the same connectivity, the index moves to `domains/piping` then, not
  before.

## Consequences

- Positive: one module and one file format; no dependency added; the walk is reproducible and
  testable on synthetic sheets; every step names a real DEXPI object (id and tag), so a path can
  be retraced with `cheme show`.
- Positive: gaps are visible: a member whose class has no library entry is a
  `cheme.hazop-class-uncovered` finding, a missing response ends the walk with a question.
- Negative: the results are only as good as the project's library, which every project has to
  write (or obtain under a licence) before the command says anything.
- Negative: the index reimplements connectivity that `cheme show` also derives (from the XML).
- Known limitations and open follow-ups: off-page connectors are not paired across sheets
  (P&IDs here carry no model link between them); writing candidates into the study
  (`--write`, with fingerprints and staleness, ADR 0011) is the next step. The skill names the
  command as an optional cross-check, not a required step: the trace by hand stays its method.
  Other operating modes than normal (a switched standby, a start-up line-up) are not walked.

## Evidence

- `src/chemeascode/domains/safety/propagation.py`, `src/chemeascode/domains/safety/schemas.py`
  (`FailureModeLibrary`), `src/chemeascode/project/hazop.py` (`node_propagation`),
  `src/chemeascode/interfaces/cli/safety.py` (`propagate`).
- `tests/test_hazop_propagation.py`.
