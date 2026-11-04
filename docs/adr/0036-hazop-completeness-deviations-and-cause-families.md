# 0036. HAZOP completeness: the deviations a node's equipment calls for and the cause families it has to consider

- **Status:** Proposed
- **Date:** 2026-11-04

## Context

ADR 0032 checks a drafted HAZOP study against a walk of the P&IDs: the top events the
project's failure modes bring to a node that no scenario covers. That walk only follows
equipment failures. On a crude-oil pump station, studies drafted by an agent recovered about a
quarter to a third of the causes of the human team's worksheet, and the misses were systematic,
not random:

- about a third of the team's deviations were never developed, most of them temperature and the
  less common guide words (as well as, other than);
- whole cause families were rarely considered: external and site causes (fire, cold, weather)
  not once, the loss of a utility, operator and maintenance actions and the plant beyond the
  study boundary at well under half the team's rate.

A walk cannot find these: none is an equipment failure travelling along a pipe. What the
drafts lacked was not knowledge but the question; a team asks it from habit and a guide-word
list.

Forces: no LLM in a domain function (ADR 0010), so the tool cannot judge whether a scenario's
text answers a question; it may only compare structure (deviations present, ids and tags in
`refs`). The checks must be general: what they ask comes from the DEXPI classes of the members
and from the plant's own files, never from one case. No published guide-word table may be
copied (licence). The triage file of ADR 0032 already records decisions about gaps.

## Decision

`cheme safety hazop propagate --coverage` runs two more checks for every node with members,
each a gap kind of the same triage file (`cheme/hazop-coverage/v1`, additive fields only, per
ADR 0005):

- **Deviations** (`kind: deviation`). A deviation matrix (`cheme/hazop-deviation-matrix/v1`)
  names equipment families by DEXPI class (a line member counts as `PipingNetworkSegment`) and,
  per family, the guide words meaningful for each parameter. cheme-as-code ships a default,
  written from general practice for this purpose
  (`chemeascode.domains.safety.completeness.DEFAULT_MATRIX`: line and piping, vessel, heat
  exchanger or heater, pump or compressor, relief device, filter or strainer);
  `safety/deviation-matrix.yaml` replaces it as a whole. An expected (guide word, parameter) of
  a node is a gap unless the node has that deviation with a scenario or with `notes`, or the
  triage decides it (`dismissed` or `question` with a reason; without `guide_word` the decision
  covers every guide word of the parameter). Parameters are compared by their words, case and
  spacing aside.
- **Cause families** (`kind: cause`). One prompt per node and family that applies, listing the
  plant items that make it concrete: `utility` (the design basis `utilities`) and `external`
  (the design basis `site` entries, and fire) for every node; `boundary` where an off-page
  connector is a member, next to one or on a member line; `operator` where the node has a valve
  without an actuator (not a check or safety valve), a filter, a strainer, a line blind or a
  hand switch (ISA first letter H); `control` where it has a controller (ISA: a C after the
  first letter) or a member named by a C&E interlock (cause, logic or effect). A boundary,
  operator or control prompt is covered when a scenario of the node names one of its items in
  `refs` (tag or object id; an interlock by its id only, since a trip instrument in a row's
  refs is mostly the safeguard, not the cause). Otherwise the
  triage decides it: `covered` with the scenario ids that answer it (the tool refuses an id that
  is no scenario of that node), `dismissed` or `question` with a reason.
- The two checks need no failure-mode library: under `--coverage`, without one the walk is
  skipped with a one-line note and the checks still run. The command exits 1 while a gap of any
  kind is open; `--write` lists every kind; decisions of every kind survive later writes. The
  file's `walk.inputs` records the fingerprints of the design basis, the cause and effect and
  the project's matrix, and the command says when they changed.
- A node without members (a global node) gets no prompts in this version.

## Consequences

- Positive: the two systematic misses become questions the drafter must answer in writing;
  every decision is in one reviewable file with its reason, next to the walk's.
- Positive: deterministic and general; a project adapts the deviations without code.
- Negative: more open items per study (on the 17 nodes with members of the pump station: 100
  deviations and 46 cause families before any decision, besides 22 walk gaps). Parameter-wide
  decisions keep the triage short, but a decision copied into every node satisfies the tool
  without the thought; the skill says so and the reviewer has to read the reasons.
- Negative: a utility or external cause analysed once in a global node is asked again in every
  node, to be dismissed there with the reason naming the global row.
- Known limitations: a deviation's or a decision's text is never judged, only its presence; the
  parameter of a deviation must use the matrix's word (`level`, not `seal oil level`) to count;
  operator items are the members only, not the items of a member line; a pig trap or another
  item DEXPI has no class for is recognised only through its manual valves.

## Evidence

- `src/chemeascode/domains/safety/completeness.py` (checks, default matrix),
  `src/chemeascode/domains/safety/schemas.py` (`Outcome.kind`, `family`, `scenarios`, status
  `covered`; `DeviationMatrix`), `src/chemeascode/domains/safety/propagation.py` (`triage`),
  `src/chemeascode/project/hazop.py` (`study_coverage`),
  `src/chemeascode/interfaces/cli/safety.py`.
- `tests/test_hazop_completeness.py`; skill `hazop-scenario-propagation` (coverage section).
- Extends ADR 0032 (scenario propagation and its coverage).
