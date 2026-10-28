---
name: hazop-study
description: Set up and draft a HAZOP study in safety/hazop/<id>/study.yaml - start it with cheme safety hazop init, record scope, operating modes, team and the analysed P&ID and control revisions, propose nodes with their members and design intent, work through guide words and parameters, and draft causes, consequences, candidate safeguards and actions from the plant as drawn, every entry status proposed for the team to accept. Use when a HAZOP or a node of one is to be started, extended or prepared for a session, or when asked which deviations a part of the plant needs.
---

# HAZOP study: setup and drafting

## Purpose and when to use

Prepare the study file the HAZOP team works in: `safety/hazop/<id>/study.yaml`
(`cheme schema hazop-study`; the file format and the workflow are in `safety/README.md`). Use
it to start a study, to add a node, or to draft the deviations and scenarios of a node before
or during a session. You draft; the team decides. Everything you write is a proposal
(`status: proposed`, `by: agent`), and the study stays a draft until the team has accepted it
(skill `hazop-assessment` for the ratings, `hazop-review` for the review).

## Required inputs and missing inputs

- The P&IDs (`pid/*.xml`, read with `cheme show <tag>`, `cheme render --png`), the lists
  (equipment, lines, instruments, special items), `control/cause-effect.yaml` (interlocks),
  `process/design-basis.yaml` and the flowsheet (fluids, pressures, temperatures),
  `DESIGN.md`.
- From the team, and to ask for when they are not written down: the study's scope and its
  boundaries, the operating modes (normal, start-up, shutdown, maintenance, ...), the team
  members, the risk matrix (`safety/risk-matrix.yaml`; the one `cheme init` writes is example
  data), the design intent where the files do not state it (setpoints, ranges, the purpose
  of a line), and what lies beyond the battery limits.
- Do not guess process knowledge the files do not hold: a pressure, a fluid's hazard, whether
  a valve fails open or closed, an operating procedure. Write the question into `notes:` of the
  entry and ask.

## Workflow and tools

1. **Start the study** (once):
   ```sh
   cheme safety hazop init H-01 --title "Feed vessel and transfer pump" \
     --input pid/P-01.xml --input control/cause-effect.yaml
   ```
   It writes the header, `analysed:` with the sha256 of each input (the revision analysed) and
   `risk_matrix: safety/risk-matrix.yaml` when that file exists. An input may be a directory
   (`--input control/`): it is recorded at the HEAD commit and must have no uncommitted change. Fill in `scope`, `modes`,
   `team` and `assessment_basis` from what the team tells you. An input added later:
   `cheme safety hazop stamp H-01 --input pid/P-02.xml --write`.
2. **Propose nodes.** A node is a part of the plant with one design intent: a vessel and its
   connections, a line from one item to the next, a pump and its discharge, a column section.
   Give each a stable id (`N1`, `N2`, ... never renumbered: a new node between N1 and N2 is
   `N3`, its place in the list is only the display order), a `title`, its `members` (tags as
   printed; `{tag: X, sheet: P-02}` where a tag is on several sheets with different meaning;
   `{sheet: P-01, object: Nozzle-7}` for an untagged DEXPI object), the `design_intent`
   (what it is meant to do, with the ranges), and `status: proposed`, `by: agent`.
3. **Deviations.** For each parameter of the intent (flow, pressure, temperature, level,
   composition, phase, reaction, ...) the guide words that give a meaningful deviation:
   `no`, `more`, `less`, `as-well-as`, `part-of`, `reverse`, `other-than`, and for
   sequences `early`, `late`, `before`, `after`. Each deviation gets an id (`N1-HL`). A
   deviation without a credible cause stays, with the reason in `notes:`.
4. **Scenarios.** One per credible cause and consequence: `id` (`S1`, ... unique in the
   study, never reused), `cause` (what fails, by tag), `consequence` (the outcome assuming
   the safeguards fail), `refs` (the tags of cause and consequence), `modes` when it applies
   only to some. Several consequences of one cause are several scenarios.
5. **Candidate safeguards** (`safeguards:` register, referenced by id from the scenarios):
   only what the plant has: an instrument with an alarm, a control loop, an interlock of
   `control/cause-effect.yaml` (`kind: interlock, interlock: I-01`), a relief device of
   the special-items list, a check valve on the P&ID, a mechanical design feature, a written
   procedure the team names. Give `refs` (tags) or `interlock`. A safeguard that is not on the
   P&ID or in the C&E is not a safeguard: it is an action.
6. **Candidate actions** (`actions:` register, `status: proposed`): what the team should
   consider, written as a recommendation (`text`), referenced from the scenario.
7. **Check after every edit**: `cheme safety hazop check H-01` (or `cheme validate`). Fix
   every error; the infos (`hazop-unresolved`) list what remains for the team.

Worked example: `examples/study.yaml` beside this skill (`example: true`): two nodes of a
vessel V-101, a pump P-101 and a control valve FV-104, with safeguards by tag and by interlock,
initial and residual ratings with their bands, an open action, and one scenario still proposed
by an agent. It is the study of the example plant `examples/safety-hazop/` of cheme-as-code.

## Validation and failure handling

- `hazop-schema`: a key or value the schema does not have (`cheme schema hazop-study`).
- `hazop-duplicate-id`: every id of the study is unique across nodes, deviations, scenarios,
  safeguards, actions and modes.
- `hazop-unknown-ref`: a scenario names a safeguard, action or mode not declared.
- `hazop-unknown-tag`, `hazop-not-on-sheet`, `hazop-unknown-sheet`: the tag is not in the plant
  as drawn. Fix the reference; never add the item to a list to silence it.
- `hazop-unknown-interlock`, `hazop-safeguard-unresolved`: declare the trip in
  `control/cause-effect.yaml` first (skill of the control data, `cheme cause-effect`), or
  give the safeguard its device.
- `hazop-input-changed`: a P&ID changed since the study analysed it; see skill `hazop-review`.

## Outputs and provenance

The study file only. Each entry you add has `status: proposed` and `by: agent` (or the person
who proposed it in a session). The analysed revisions are recorded by `init` and `stamp`, never
typed. Commit with a message naming the study and the nodes drafted.

## Required human judgment

The team decides the scope, the nodes, which deviations are credible, the causes and
consequences, and whether a safeguard is effective. Never set `status: accepted` yourself,
never invent equipment, instruments, safeguards, procedures, frequencies or approval records,
and never present a proposal as the team's finding. Ask when the files do not say how the
plant behaves.

## References

- `safety/README.md` (file format, workflow, commands); `cheme schema hazop-study`.
- IEC 61882:2016, Hazard and operability studies (HAZOP studies) - Application guide.
- Skills `hazop-assessment` (ratings and bands), `hazop-review` (review and revisions),
  `review` (review records), `hazop-equipment-causes` (deviations by equipment),
  `safeguard-crediting` (what may be credited), `relief-scenarios`, `process-safety` (hub).
