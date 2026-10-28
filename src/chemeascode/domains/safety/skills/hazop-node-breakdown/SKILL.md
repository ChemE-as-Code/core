---
name: hazop-node-breakdown
description: Split the P&IDs of a HAZOP study into nodes - trace the plant with cheme show, place every vessel, line, valve and instrument by named boundary rules, write each node's members, title and design intent into safety/hazop/<id>/study.yaml as proposals, and check that every drawn item is in a node. Use when a study needs its nodes, when the team asks why an item is in a node or where a node starts and ends, or to revise one node after a P&ID change.
---

# HAZOP node breakdown

## Purpose and when to use

Propose the nodes of a HAZOP study: parts of the plant that each have one design intent and can
be discussed in one sitting. Use it after `cheme safety hazop init` (skill `hazop-study`, step
1) and before deviations are drafted, when the team wants to compare its own split with a
proposed one, or when a changed P&ID (`hazop-input-changed`) moves items between nodes. Every
boundary you draw names the rule behind it, so the team can see why an item ended up where it is
and overrule exactly that rule. You propose; the team decides the nodes.

## Required inputs and missing inputs

- The study (`safety/hazop/<id>/study.yaml`) with its scope and its `analysed:` P&IDs.
- The P&IDs (`cheme render --png` for the picture, `cheme show <tag>` for each item's
  connections, the item at the other end of each line and its instruments), the equipment,
  line and instrument lists, and `control/cause-effect.yaml` (the trips).
- For the design intents: `process/design-basis.yaml`, the flowsheet and stream table (flows,
  pressures, temperatures, fluids), the datasheets and `DESIGN.md`.
- From the team, when the files do not say: the study limits beyond the battery limit or an
  off-page connector, whether parallel trains are studied once or each, and how big a node the
  team is used to. Ask; do not assume a team convention.

## Workflow and tools

1. **List what has to be placed.** Every item in the study's scope: the equipment list, the
   line list, the instruments and the special items on the analysed sheets. At the end, each is
   a member of exactly one node (the global node of step 4 holds none).
2. **Trace the plant.** Start at each feed (an off-page connector or a nozzle at the study
   limit) and follow the flow with `cheme show <tag>`: its nozzles, the segment and line on each,
   and the item at the other end. Note every vessel, pump, exchanger, control valve, relief
   device, branch and change of line.
3. **Place the items by the boundary rules.** Name the rule (its label) for each boundary in the
   node's `notes:`.

   | Label | Rule |
   |---|---|
   | `vessel` | A major vessel (drum, column, reactor, tank) is a node of its own; its lines start and end at its nozzles. |
   | `line` | The piping between two major vessels, or a vessel and a study limit, is a line node, with the pumps, filters, exchangers and valves on it and a pump's recycle line. |
   | `branch` | A dead-end branch (vent, drain, sample point, bridle, tie-in stub) goes with the node it hangs off. |
   | `exchanger-sides` | An exchanger's process side and its utility side are different nodes; the exchanger itself goes with its process side. |
   | `fluid-change` | A change of fluid (a mixing point, a reactor outlet, a phase split) starts a new node. |
   | `class-break` | A change of piping class (pressure or temperature rating) may start a new node; the team decides whether it does. |
   | `control-valve` | A control valve may end a node (the valve stays with the upstream node), most usefully where a node would otherwise hold several control loops. |
   | `study-limit` | An off-page connector or battery limit at the edge of the study starts or ends a node. |
   | `relief` | A relief device stays with the node it protects; its discharge belongs to the relief or flare system. |
   | `instruments` | An instrument goes with the item it acts on (a valve's actuator, a controller's final element) or, if it has no final element, with the item it measures. |
   | `headers` | A line node that joins more than two vessels or limits through a header is split per group of equipment; parallel trains with a shared tag number stay together. |
   | `parallel-trains` | Identical parallel trains are studied each, or once with their differences recorded; the team says which. |

4. **Add a global node** (last in the list) for what no line node covers: loss of utilities,
   siting and layout, effects of one unit on another, and failures that span several nodes. It
   has no members; say so in its design intent.
5. **Check the size.** A node the team cannot discuss in one sitting (several control loops,
   several branches, a long list of equipment) is split at a control valve or a header; two
   very small nodes with the same intent may be merged. Say which rule you applied.
6. **Write the nodes** in the direction of flow:
   ```yaml
   nodes:
     - id: N1
       title: V-101 feed vessel and P-101 suction
       design_intent: >-
         Receive water from the supply and hold it between the level alarms of LT-102, feeding the
         suction of P-101 through 80-P-101. Assumed: ambient temperature (no stream data yet).
       members: [V-101, LT-102, PI-103, 80-P-101]
       status: proposed
       by: agent
       notes: "vessel: V-101 with its nozzles; instruments: LT-102 and PI-103 measure V-101; study-limit: inlet off-page connector"
   ```
   - `id`: `N1`, `N2`, ... stable, never renumbered; the list order is the display order.
   - `title`: what a HAZOP team would call it, at most about eight words, naming the main tags.
   - `design_intent`: two to four sentences: what the node is for, how it does it (equipment and
     control loops by tag), and its operating range (flow, pressure, temperature, level) where the
     files give one. Anything not in the files goes at the end as "Assumed: ..." or as a question
     in `notes:`.
   - `members`: tags as printed; `{tag: X, sheet: P-02}` for a tag drawn on several sheets with
     different meaning; `{sheet: P-01, object: <XML id>}` for an untagged object.
7. **Check**: `cheme safety hazop check H-01`, then compare the members of all nodes with the list
   of step 1: name any item in no node, or in two, and fix it.

**Revise one node.** After a P&ID change: `cheme diff` for what changed, `cheme show` for the
changed items, then change only that node's `members`, `design_intent` and `notes`, keeping its
id; a new part of the plant gets a new id. Check again.

## Validation and failure handling

- `hazop-unknown-tag`, `hazop-not-on-sheet`, `hazop-unknown-sheet`: a member is not on the
  analysed sheets as drawn. Fix the member; never add an item to a list to silence it.
- `hazop-duplicate-id`: node ids share one namespace with deviations, scenarios, safeguards,
  actions and modes.
- An item in no node, or in two: `cheme safety hazop check` does not test coverage; step 7 does.
- A line with no clear flow direction, an off-page connector with no partner sheet, or an item
  whose service the files do not say: write the question in `notes:` and ask the team.

## Outputs and provenance

The `nodes:` of the study file, each `status: proposed` and `by: agent`, with the boundary
rules in `notes:`. No deviation, scenario or rating is written in this step (skills
`hazop-scenario-propagation` and `hazop-risk-classification`). Commit with a message naming the
study and the nodes proposed.

## Required human judgment

The team decides the nodes: where a boundary goes, whether a class break or a control valve
ends a node, how parallel trains are treated and what the design intent is. Never set
`status: accepted`, never invent an operating range, a fluid or a setpoint, and never present
the proposed split as the team's.

## References

- `safety/README.md`; `cheme schema hazop-study`; `cheme show --help`.
- IEC 61882:2016, Hazard and operability studies (HAZOP studies) - Application guide.
- Skills `hazop-study` (setup and drafting), `hazop-scenario-propagation` (scenarios of a node),
  `hazop-review` (revising after a P&ID change), `process-safety` (hub).
