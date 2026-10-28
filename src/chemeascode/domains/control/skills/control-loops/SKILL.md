---
name: control-loops
description: Define the regulatory control loops in control/loops.yaml - measurement, controller, final elements with fail positions, action, setpoints with units and provenance, modes, cascade/ratio/feedforward/override links, alarms with operator responses - and check them with cheme validate and cheme control report. Also carries the control-strategy guidance behind the pairings: whether a parameter earns a loop, sensor and valve placement, standard schemes per equipment type, and telling cascade, ratio, selective, override and split range apart. Use when a P&ID or flowsheet gains control loops, before a HAZOP, or when cheme.control-* findings name control/loops.yaml.
---

# Control loops

## Purpose and when to use

Keep one register of the plant's regulatory loops: what each controls, with which measurement
and which final element, to which target, in which modes, and how it is linked to other loops.
It is the source the narrative, the control philosophy, the sequences and later tuning or DCS
work refer to. Use it while the P&IDs get their instrumentation, and before a HAZOP. A loop is
regulatory control, never a safeguard: trips belong in `control/cause-effect.yaml` (`cheme cause-effect`).

## Required inputs and missing inputs

- The instrument list and the P&IDs: the measurement and the valve or drive tags.
- `process/flowsheet.yaml`: the operating cases and the stream values a setpoint comes from.
- The equipment datasheets for limits; the vendor for a package's own controls.
- What only people decide: the control strategy (which variable is paired with which valve),
  the fail positions (a safety question for each valve), the modes. A fail position or action
  nobody gave is left out, never guessed: it stays a `cheme.control-incomplete` finding.

## Workflow and tools

1. **One entry per loop** in `control/loops.yaml` (`cheme schema loops`): `id` (the loop tag),
   `title`, `purpose`, `section`, `cases`, `variable`, `measurement: [{tag}]`, `controller`.
2. **Action and final element.** `action: direct` when the output rises with the measurement,
   `reverse` when it falls. Each final element: `tag`, `kind`, `actuator`, `fail` (open,
   closed, last; a drive stop, a heater off: the position on loss of signal, power or air).
   The two are independent; do not infer one from the other. A split range gives each
   element its `range` of the output; `travel: [100, 0]` an element that closes as the output
   rises.
3. **Targets** with `value`, `unit`, `provenance` and `source`; `modes` and `cases` they apply
   to; a setpoint that is a case value names it (`stream: S1, property: flow`) and validate
   keeps the two in step. A value not known yet: `unresolved: <why>`. Pressures with (a) or
   (g), temperatures in K or °C.
4. **Modes** (`manual`, `auto`, `cascade`), `normal_mode`, and `transitions` with who makes them
   and when (`condition`).
5. **Links** on the loop they act on: `cascade` (the master's output is this loop's setpoint;
   the slave needs the `cascade` mode, the master no final element), `ratio`, `feedforward`,
   `override` (`select: low | high`; the loops share the final element). A ring of cascade links
   is an error; ratio, override and feedforward links may form rings.
6. **Alarms and trips.** List process alarms with what the operator does (`response`). A
   high-high or low-low condition is a trip: put it in the C&E and list its id under
   `interlocks`.
7. **Rationale and judgement.** `rationale`: why this pairing and these modes; `operator`: what
   the operator has to judge; `unresolved`: each open point.
8. `cheme validate`, then `cheme control report` (the loop summary in `build/`).

## Control-strategy guidance

Engineering guidance only; core has no calculation for this, and `cheme validate` checks the
register's structure, not whether a strategy is sound. Use it to ask the right questions before
filling steps 1-5. Statements follow Toghraei, *Piping and Instrumentation Diagram Development*
(Wiley 2019), ch. 14 (§14.8.5, §14.9) unless marked otherwise.

**Does the parameter earn a loop?** Ask, per parameter of each item, how much monitoring it
needs. Roughly: the item's main purpose (or a critical weakness) justifies an automatic loop;
a quick effect on quality or smooth running suggests a control-room indication the operator acts
on; a slow effect suggests a field indicator; a negligible one, nothing. So an instrument that
belongs to no loop is not by itself a defect. Where the risk is high enough that the duty goes to
a safety function, a deliberate absence of a basic-control loop can be intended (skill
`control-safeguarding-and-interlocks`). Risk is likelihood times consequence of the actual plant:
a recirculation line lowers the chance of dead-heading a pump but does not remove it, and for
flammable, hot or toxic service the consequence of a release, not the machine's price, should
drive the decision.

**Main-purpose parameter by item** (a starting question, not a rule): tank or non-flooded
liquid vessel, level; gas vessel or flooded liquid vessel, pressure; pump, compressor, fan,
blower, flow or discharge pressure; exchanger, furnace, boiler, temperature of the target stream;
a unit operation, product composition plus the vessel's own control.

**Sensor against valve.** Flow: the valve usually sits downstream of the element, because its
turbulence disturbs a reading behind it; how strictly depends on the meter type and its
installation requirements, so check the meter's own basis. Pressure: either side is valid and
names the loop (upstream: fore-pressure; downstream: back-pressure). Temperature and
composition: either side. Level: follows the plant-wide strategy. One valve cannot hold both
pressure and flow of a line, so decide which is held; a liquid-filled line (including one through
a flooded vessel) normally supports one valve holding a given variable, since two controllers on
one incompressible stream tend not to settle. Two valves in series sharing one duty (staged
letdown against cavitation) are a different case.

**Standard schemes by equipment** (options to weigh, not a prescription):
- Centrifugal pump: capacity by a discharge valve or by speed (a valve suits any circuit; speed
  loses its advantage where most of the head is static); minimum flow by a recirculation line to
  suction with the sensor inside that loop. Whether the line is continuous (orifice), on-off or
  controlled depends on how much recycle the duty can afford; pump power is only a proxy. A pump
  at no flow heats its trapped liquid, so on hazardous service minimum-flow protection or a
  low-flow trip is a question to settle on the consequence, not on size. This book's size bands
  for the recirculation device need review before use and are not reproduced.
- Positive-displacement pump: throttling the discharge does not control capacity; consider
  diverting through a recirculation line, speed, or stroke. Its recirculation sensor sits outside
  the loop, unlike the centrifugal minimum-flow case.
- Gas movers: capacity by recirculation (cooled, with a check valve), speed, suction throttling,
  or a machine-specific device (axial blade pitch, centrifugal inlet guide vanes, reciprocating
  unloading). Discharge throttling suits dynamic machines, not positive-displacement ones. A
  machine that can reach its surge line needs a question on anti-surge protection with a fast
  recycle; the surge line and duty decide, not the driver rating.
- Heat exchangers: sensor on the outlet of the target stream, valve on the other stream (if a
  stream's temperature matters, its flow probably does too, so do not throttle it). Throttling the
  other stream is common for a utility exchanger; for a process exchanger consider bypass control
  so the total flow stays constant. With both a bypass valve and a through valve carrying flow,
  parallel range, not split range.
- Splitting a stream where one branch is level-controlled and the other flow-controlled: flow
  control on the smaller branch tends to be more accurate (column reflux and product, for
  example).
- For utility headers and plants see the skills `utility-cooling-water`, `utility-steam-and-condensate`;
  for column, reactor and heat-transfer specifics `unit-ops-distillation`, `unit-ops-reactors`,
  `unit-ops-heat-transfer`.

**Telling architectures apart** (what feeds the set point): cascade, a controller's output;
ratio, a sensor signal, usually scaled; selective, several sensor signals meeting at a selector;
override, several controller signals meeting at a selector; split range, one controller driving
two valves over different parts of its output; parallel range, driving them together when total
flow must stay constant. These map to the `cascade`, `ratio`, `override` and split-range
(`range`) fields of step 5 and step 2; selective control has no dedicated field, so describe it in
`rationale`.

When writing a loop up, name what is measured, what is manipulated, and what it protects against.

## Validation and failure handling

- Errors: `cheme.control-duplicate`, `cheme.control-cycle` (setpoints that depend on each
  other).
- Warnings: `cheme.control-unknown-tag` (a tag renamed or removed on the P&ID: fix the
  register, or the list), `cheme.control-ref`, `cheme.control-conflict` (two loops on one
  valve without an override, a setpoint outside its limits, a mode the loop does not have),
  `cheme.control-unit`, `cheme.control-case` (the setpoint left its operating case: update one
  of them).
- Info: `cheme.control-incomplete` (draft gaps), `cheme.control-unresolved`,
  `cheme.control-shared-element` (the loop shares a sensor or valve with an interlock: not an
  error, but the HAZOP must judge independence), `cheme.control-alarm-trip`.
- The stage gates decide when the info findings must be gone: the template's gate
  `control-complete` (detail, `fail_on: info`) lists the rules it requires; the ones to judge
  rather than remove (`-shared-element`, `-alarm-trip`, `-logic-text`) and `-stale` are left
  out.

## Outputs and provenance

`control/loops.yaml`, committed; `build/control-loops.html` and `.csv` from `cheme control
report` (not committed). Each target carries its provenance; record the inputs the register
rests on under `basis:` with their revision.

## Required human judgment

Pairings, fail positions, the modes and the operator's role are design decisions with safety
consequences. The register states intent: it assigns no SIL, claims no independence of
protection layers and sets no safe operating limit. A reviewer (skill `review`) accepts it.

## References

- `docs/framework/control.md` of cheme-as-code: conventions and rules.
- Skills `control-narrative`, `control-sequences`, `control-safeguarding-and-interlocks`, `review`.
- Toghraei, *Piping and Instrumentation Diagram Development* (Wiley 2019), §14.8.5 (loop
  architectures), §14.9 (which parameters get a loop). The control-strategy section is general
  engineering method paraphrased from this book and is independently verifiable against it;
  the pump-power bands and blower/compressor figures of the source were dropped as needing review.
- Worked example: `examples/process-separation/control/loops.yaml` of cheme-as-code.
