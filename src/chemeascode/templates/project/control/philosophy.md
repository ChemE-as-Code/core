---
# Control philosophy. Schema of this front matter: `cheme schema control_philosophy`.
# Skill control-narrative.
schema: cheme/control_philosophy/v1
objectives: []
#  - {id: OBJ-1, title: Feed the plant at the rate of the operating case, loops: [FIC-101]}
failures: []
#  - id: F-AIR
#    title: Loss of instrument air
#    response: The control valves go to their fail positions; ...
#    loops: [FIC-101]
#    interlocks: [I-01]
unresolved: []
---

# Control philosophy

> PROPOSED. Not approved for implementation; the review status comes from `reviews/`. Loops,
> sequences and trips are defined in `control/loops.yaml`, `control/sequences.yaml` and
> `control/cause-effect.yaml`; this text explains them and does not repeat their values.

## Operating objectives

<!-- What the control must achieve (throughput, product quality, energy, availability), by id
(OBJ-1, ...) as in the front matter. -->

## Control hierarchy

<!-- Regulatory control (the loops), sequences between modes, protective functions (the C&E).
A regulatory loop is never counted as a safeguard. -->

## Normal operation and disturbances

<!-- How the loops hold the operating point, and what each expected disturbance does. -->

## Operator and automatic actions

<!-- What runs automatically, what the operator sets, decides and resets. -->

## Equipment and utility failures

<!-- Loss of instrument air, power, cooling water, steam, a machine trip: the designed
response, by id (F-AIR, ...) as in the front matter. -->

## Assumptions and open points

<!-- What is assumed or not decided yet. -->
