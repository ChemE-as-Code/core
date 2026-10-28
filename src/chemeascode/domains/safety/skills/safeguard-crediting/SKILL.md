---
name: safeguard-crediting
description: Ask whether something on a P&ID or in a HAZOP study counts as an independent protection layer against a given cause - independence over sensor, logic and final element, control loops credited against their own failure, operator response to an alarm, sharing a sensor between control and trip, and where a claimed integrity level actually lives. Use when judging, drafting or reviewing HAZOP safeguards. It frames questions; it never certifies independence.
---

# Crediting safeguards

## Purpose and when to use

Listing what is drawn near a hazard is easy; saying which of it protects against that
cause is the work. Use this skill when proposing safeguards for a HAZOP scenario
(`hazop-study`), reviewing a study (`hazop-review`) or asking whether a trip, alarm or relief
device can be counted against a cause. It rests on CCPS, *Guidelines for Engineering Design for
Process Safety* (AIChE), chapter 9, and on Moran, *An Applied Guide to Process and Plant Design*
(Butterworth-Heinemann 2015), chapter 15 for the functional-safety statement.

## Required inputs and missing inputs

The scenario's cause with its tags, the candidate safeguard with its sensor, logic solver and
final element, `control/cause-effect.yaml`, the P&ID (tappings, isolation, shared final elements)
and the control philosophy. Not derivable from files: logic-solver architecture, I/O assignment,
data-highway sharing, programmer and vendor commonality, integrity level, failure probability. Ask
for them.

## Workflow and tools

Engineering guidance only; core has no calculation for this. `cheme safety hazop check` verifies
that safeguard references resolve to tags and interlocks; it says nothing about independence.

1. Reduce the risk as far as possible in the innermost layer before adding the next, and
   understand the independence between layers clearly (CCPS 9.3.2.3). A trip where a design change
   would do answers the wrong question.
2. Test independence over the whole chain of sensor, logic and final element, not the logic alone.
   A part shared with the cause makes the layer not independent of that cause. CCPS quotes roughly a
   hundredfold improvement in probability of failure on demand as the benchmark per layer (9.6.8.2);
   numeric: manual review, and do not turn it into a credited figure here.
3. Do not credit a control loop against a cause that is its own failure. The safety system acts when
   the basic control system has failed, and that failure is what puts demands on it (9.6.8.1,
   9.3.2.1). Moran states the same from the functional-safety side: protection functions are
   implemented independently of the control systems whose failure creates the demand.
4. Operator response to an alarm: CCPS is flat that safety-system operation should be automatic and
   that arrangements relying on a person are not independent protection layers in that sense, while
   noting that such action may still count toward overall mitigation of an event (9.6.8.2). Report
   both halves.
5. Sharing between control and trip is conditional, not forbidden (9.6.8.2): logic solvers are
   strongly recommended to be separate; a sensor or final element may be shared only in the cases
   the source scopes by integrity level (level 1 or 2 with a single device and an independent physical
   layer such as a relief valve or dike; level 3 with two devices, one shared). Report which case is
   relied on; do not assert a level. In every case the study team must judge the sharing acceptable.
   A stricter service or project rule governs. A shared sensor's failure creates the demand the
   trip must answer, while sharing makes sensor failure more visible through the control loop.
6. Common-mode and covert faults are far likelier in programmable systems linked by data highways,
   shared software, a single supervising computer or one programmer; subtle common-mode paths
   persist even with diverse elements (9.3.2, 9.3.2.3). One I/O module can disable many loops, so
   address the I/O assignment, not more loops.
7. Where a claimed integrity level lives: the chain (process connection, sensor, wiring, input,
   processor, output, wiring, pilot device, final element) is as good as its weakest link, and
   attention tends to go to the programmable part while field devices and wiring get little (9.6.8.2).
   On the drawing look at the tapping, isolation and final element, not the logic symbol.

Assert from files: that a device exists, where it senses and acts, whether a trip and a control
loop share a tapping or final element, and whether a physical layer is also present. Do not assert
an integrity level, a failure probability, that sharing was judged acceptable, or that a layer is
independent because it is drawn separately.

## Validation and failure handling

Patterns to raise as questions, not defects: a sensor or final element shared between a control
loop and a trip; redundant sensors on one process connection; a trip driven by a single sensor.
The first two are exactly the sharing the source permits under conditions. A passing
`cheme safety hazop check` is not evidence of independence.

## Outputs and provenance

For each scenario: the cause, what you believe protects against it, why it is or is not independent
of that cause, which conditions you can see met, and what only the study can settle. Safeguards stay
`status: proposed` in the study file.

## Required human judgment

Independence, integrity level, acceptability of shared devices and the credit given to any layer
belong to the HAZOP team and a functional-safety assessment. This skill never certifies that
protection layers are independent or that a plant is safe.

## References

- CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE), chapter 9: 9.3.2, 9.3.2.1,
  9.3.2.3, 9.6.8.1, 9.6.8.2. Moran 2015, chapter 15. Statements are re-expressed from these; the
  hundredfold figure and integrity-level conditions need review before operational use.
- Skills `process-safety`, `hazop-study`, `hazop-assessment`, `hazop-review`, `relief-scenarios`.
