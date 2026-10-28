---
name: control-sequences
description: Write and review startup, shutdown and abnormal-mode sequences in control/sequences.yaml - start permissives separate from trips, steps with entry and completion conditions, timeouts, abort, reset and restart - referring to the C&E interlocks and loops by id. Use when a plant needs its operating modes described, when reviewing a sequence before HAZOP, or when cheme.control-* findings name control/sequences.yaml.
---

# Operating sequences

## Purpose and when to use

Describe how the plant is taken from one state to another: startup, normal shutdown, and the
abnormal modes that matter (a trip and restart, a utility failure, regeneration). Each sequence
says what must hold before it may start (permissives), its steps, what ends each step, what
happens when a step takes too long or something trips, and how the plant is reset and
restarted. Use it with the loops (skill `control-loops`) and the narrative (skill
`control-narrative`), and to review a sequence before a HAZOP.

## Required inputs and missing inputs

- `control/loops.yaml` (the loops a step puts in manual, auto or cascade or gives a setpoint),
  `control/cause-effect.yaml` (the trips, by id), the equipment and instrument lists.
- The operating cases of `process/flowsheet.yaml`; vendor startup instructions for packages.
- What only people know: the startup order the operators use, hold points, how long a step
  may take. Leave an unknown condition `unresolved`, never invent one.

## Workflow and tools

1. **One entry per sequence** in `control/sequences.yaml` (`cheme schema sequences`): `id`,
   `title`, `mode` (startup, shutdown, abnormal, normal, other), `section`, `cases`,
   `equipment`.
2. **Permissives** are the conditions to start; **trips** are not repeated: list their C&E ids
   under `interlocks`. A permissive may name an interlock (`{interlock: I-01, state: reset}`).
3. **Steps**: `actions` (a tag start/stop/open/close, a loop to manual/auto/cascade or a
   setpoint, another sequence run; `by: operator | automatic`), `complete` (what must hold
   before the next step), `entry` where more than the previous step is needed, `timeout` with
   `on_timeout` (a step or `abort`), `next` where the order is not the list order, `operator`
   for instructions and judgement.
4. **Conditions** use items in a state, `all`, `any`, `vote: {k, of}`, `delay`, `deadband`.
   Logic the format cannot express is `text` (it stays visible as
   `cheme.control-logic-text`); what is not known is `unresolved`.
5. **Abort and reset.** `abort`: its `condition` (besides the trips), the `actions`, the
   sequence that follows (`then`). `reset`: `latching`, `manual`, the `condition` to reset and
   the `restart` condition.
6. `cheme validate`, then `cheme control report` (`build/control-sequences.html`).

### Reviewing a sequence

Walk it as the operator would, from the permissives to the last step, and for each step ask:
can the completion condition be seen from the control room; what if it never comes (timeout);
what if a trip comes now (abort, reset, restart); which loop is in which mode; does a step move
a valve an interlock also moves. Record the findings in a review record (skill `review`) with
the sequences in its `scope`.

## Validation and failure handling

- Errors: `cheme.control-duplicate` (a sequence or step id twice).
- Warnings: `cheme.control-ref` (a step, loop, sequence or interlock that does not exist),
  `cheme.control-unknown-tag`, `cheme.control-unreachable` (a step nothing leads to),
  `cheme.control-conflict` (a loop put in a mode it does not have, `on_timeout` without a
  timeout), `cheme.control-unit` (a delay or timeout that is not a time).
- Info: `cheme.control-incomplete` (a step without completion condition, a startup without
  permissives, a sequence without abort or reset, a timeout without what happens then),
  `cheme.control-unresolved`, `cheme.control-logic-text`.

## Outputs and provenance

`control/sequences.yaml`, committed; the sequence report from `cheme control report`. The
setpoints a step gives carry their provenance; the review status comes from the review records.

## Required human judgment

The order of operations, hold points, abort and restart behaviour are operating decisions with
safety consequences. The format records intent and checks structure; it does not show that a
sequence is safe, that a trip is independent, or that it can be implemented in a given DCS.

## References

- `docs/framework/control.md` of cheme-as-code.
- Skills `control-loops`, `control-narrative`, `review`.
- Worked example: `examples/process-separation/control/sequences.yaml` of cheme-as-code.
