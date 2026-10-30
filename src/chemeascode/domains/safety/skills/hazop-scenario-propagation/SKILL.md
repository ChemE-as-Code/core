---
name: hazop-scenario-propagation
description: Develop the scenarios of a HAZOP node deviation by propagation over the P&ID - ask the deviations the node's objects call for, find causes inside the node, follow each deviation object by object with cheme show until it is stopped, absorbed or reaches a top event (loss of containment, internal fire or explosion), take the outcome from the fluid's hazards, and write the credible cause-consequence rows with their path and candidate safeguards as proposals. Use when the team asks for the causes, consequences or scenarios of a deviation (no flow at N1), wants a node's scenarios checked for gaps, or one row revised.
---

# HAZOP scenario propagation

## Purpose and when to use

Draft the worksheet rows of a node: for each deviation, the causes that can produce it and the
consequences it leads to if no safeguard acts. Causes are looked for inside the node;
consequences are found by following the deviation through the plant as drawn, one object at a
time, so every row can be traced. Use it once the nodes exist (skill `hazop-node-breakdown`),
before or during a session, or to check a node's scenarios for a missing cause or a consequence
nobody followed far enough. You propose; the team decides what is credible.

## Required inputs and missing inputs

- The study with its nodes (`members`, `design_intent`) and the analysed P&IDs, read with
  `cheme show <tag>` (connections, the item at the other end of each line, instruments) and
  `cheme render --png`.
- `control/cause-effect.yaml` (trips), the instrument list (alarms, fail positions where
  given), the special-items list (relief devices, check valves).
- The fluid in each line and vessel and its hazards (flammable, toxic, hot, under pressure,
  harmful to the environment): `process/design-basis.yaml`, the stream table, the line list's
  fluid codes. DEXPI files often do not say. A missing fluid is a question for the team, never a
  guess.
- The operating modes of the study: a cause may belong to start-up or shutdown only.
- Optional: the project's failure-mode library `safety/failure-modes.yaml` (`cheme schema
  failure-modes`, written by the team with its sources), which `cheme safety hazop propagate`
  needs. Without it, trace by hand; never write the library yourself to have one.

## Workflow and tools

1. **The deviations to ask.** The parameters of the node's design intent and of its objects:
   lines and pumps (flow, pressure, and temperature where it matters), control valves (flow,
   pressure), vessels (level, pressure, temperature, composition), exchangers (temperature,
   flow on each side), reactors (reaction, temperature, composition). Combine each with the guide
   words that give a meaningful deviation (`no`, `more`, `less`, `reverse`, `as-well-as`,
   `part-of`, `other-than`; `early`, `late`, `before`, `after` for sequences). Skill
   `hazop-equipment-causes` lists what is credible per equipment type. Write every deviation you
   asked, also one with no credible cause: it stays with the reason in its `notes:`.
2. **Causes, inside the node only.** Four kinds:
   - *local*: an object of the node fails and gives the deviation directly (P-101 stops: no flow);
   - *driver*: a local failure gives another deviation that an object of the node turns into
     the one asked (FV-104 fails open: more inflow to V-101, so high level);
   - *common*: a utility or operator failure, only where the node holds an object that needs it
     (loss of power where there is a pump or motor; loss of actuating energy where there is an
     actuated valve, worded at the valve: "FV-104 actuator fails, the valve goes to its fail
     position"; a wrong line-up where there is a manual valve);
   - *induced*: a deviation that enters from a neighbouring node. It is analysed in that node;
     here it is a reference ("less flow: see N1, P-101 stops"), not a new cause.
3. **Consequences: follow the deviation.** Start at the node's own objects, then go outward
   along the connections `cheme show` prints (downstream for an outlet effect, upstream for an
   inlet effect). At each object decide one of:
   - *responds*: the object turns it into another deviation, which continues from that object
     (more inflow to a vessel: high level; no cooling water: high process outlet temperature);
   - *passes*: it continues unchanged (high temperature through a pump, pressure through a
     closed pressure vessel and fittings);
   - *no effect*: the object does not react to it; nothing is recorded there and it passes on;
   - *absorbs*: the object's design stops it going further (a vessel's inventory takes up a flow
     change; an atmospheric tank does not pass high pressure on), but its own response still
     counts (the tank's shell overpressure);
   - *stops*: a **top event**, a loss of primary containment (leak, rupture, overfill,
     overpressure) or a fire or explosion inside the equipment. Nothing travels on through the
     piping after it.
   Damage to equipment, off-spec product and lost production are consequences that do not stop
   the chain: record them and go on (a damaged pump also stops pumping). Stop as well at a
   study limit (record "beyond the study limit at <connector>") and at an object already
   visited. **Safeguards never stop the chain**: a check valve, a relief valve or a trip is a
   protection, recorded in step 5. The row describes the consequence with none of them acting.
4. **From the top event to the outcome.** It depends on what is released, not on the piping: a
   flammable liquid can burn as a pool fire or flash, or spill if not ignited; a flammable gas
   can give a jet fire, a flash fire or an explosion; a toxic fluid, exposure; a hot or
   pressurised one, burns and injury; one with no hazardous property, lost production and damage.
   List the outcomes that apply, without probabilities. Without a known fluid, stop at the top
   event ("discharge line ruptures; fluid not known") and ask.
5. **Pick the credible rows and write them.** Keep a cause only where its failure fits the
   item's service on this plant; one row per distinct cause and outcome; the worst credible
   outcome per cause, and another only if it is a different hazard. For each, a scenario:
   ```yaml
   - id: S5
     cause: "P-101 stops while running (motor trip, loss of power)"
     consequence: "No flow to the battery limit; the receiving unit is starved (production loss)"
     refs: [P-101, 50-P-102]
     safeguards: [SG3]
     status: proposed
     by: agent
     notes: "path: P-101 (no flow) > 50-P-102 > off-page Line_50P102_To; beyond the study limit"
   ```
   - `cause` and `consequence` name tags and read as worksheet entries.
   - `notes:` keeps the path you followed, object by object, so a reviewer can retrace it.
   - `safeguards`: candidates from the study's register, only what the plant has (an alarm, a
     control loop, an interlock of `control/cause-effect.yaml`, a relief device, a check valve);
     a missing one is an action, not a safeguard (skill `safeguard-crediting` for what counts).
   - A deviation with causes but no hazardous consequence: write that in the deviation's
     `notes:` with the path that showed it, so the team can disagree.
6. **Check**: `cheme safety hazop check H-01`.

**Optional: the walk as a cross-check.** With a failure-mode library,
`cheme safety hazop propagate H-01 --node N1 [--deviation "no flow"] [--paths] [--json]` does
steps 2 and 3 mechanically: each failure mode of the node's objects is walked over the analysed
P&IDs with the library's responses, one candidate per outcome on its shortest path. It prints
one line per outcome (deviation, top event or end, where, the causes that reach it) and the
open questions once each; `--paths` gives every candidate with its path and the safeguards on
it. It is a tool, not a step: use it where it helps (a large or meshed node, a check after
drafting for a cause or branch nobody followed, the instruments and interlocks along a long
path) and skip it for a small node. Read its output as candidates, never as rows:
- the end of each walk: `top-event` (go on with step 4), `study-limit`, `absorbed`, `unknown`
  (the library has no response there: a question, never a guessed response), `depth` (cut off
  after 40 objects: follow it by hand), and, only counted, `closed`, `visited` and
  `no-connection`;
- a valve with a normally closed or locked closed role stops a walk: the line-up of normal
  operation. A cause at that valve (opened in error, passing) still starts its own walk, but
  another mode (a switched standby filter, a start-up line-up) is yours to follow by hand;
- it judges nothing: credibility and outcome are steps 4 and 5, and a safeguard on the path is
  a candidate, not an effective one (skill `safeguard-crediting`). Consequences inside a pump
  or at a seal come from its own responses in the library, not from the walk.
Say in a scenario's `notes:` when the walk found it.

**Revise one row.** Change only that scenario's `cause`, `consequence`, `refs`, `safeguards` and
`notes`, keeping its id; a different cause or outcome is a new scenario with a new id.

## Validation and failure handling

- `hazop-unknown-tag`, `hazop-not-on-sheet`: a tag in `refs` is not drawn; fix the reference.
- `hazop-unknown-ref`, `hazop-safeguard-unresolved`, `hazop-unknown-interlock`: a safeguard id
  not declared, or a safeguard with no device or interlock.
- A path that leaves the analysed sheets through an off-page connector with no partner: stop
  there, record it, and ask whether the other sheet belongs to the study.
- A behaviour the files do not settle (a fail position, a set pressure, whether a vessel is
  rated for the pump's shut-off pressure): write the question in `notes:`; do not choose.
- `propagate` names the node's objects whose class the library does not cover and the members
  it cannot resolve: trace those by hand. A gap in the library is for the team to fill.

## Outputs and provenance

`deviations:` and their scenarios in the study file, each scenario `status: proposed`, `by:
agent`, with its path in `notes:` and its candidate safeguards. No rating is written in this
step (skill `hazop-risk-classification`). Commit with a message naming the node and the
deviations drafted.

## Required human judgment

The team decides which deviations are meaningful, which causes are credible, how far a
consequence goes and what the outcome is, and whether a safeguard is effective. Never set
`status: accepted`, never invent a cause the plant cannot have, a fluid, a frequency or a
safeguard, and never present a traced path as the team's conclusion.

## References

- `safety/README.md`; `cheme schema hazop-study`; `cheme show --help`.
- `cheme safety hazop propagate --help`, `cheme schema failure-modes` (the optional walk).
- IEC 61882:2016, Hazard and operability studies (HAZOP studies) - Application guide.
- Skills `hazop-node-breakdown` (the nodes), `hazop-equipment-causes` (credible deviations and
  causes per equipment type), `safeguard-crediting`, `relief-scenarios`,
  `hazop-risk-classification` (the ratings), `hazop-study`, `process-safety` (hub).
