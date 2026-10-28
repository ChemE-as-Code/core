---
name: pid-design-instrumentation
description: What to consider when adding an instrument, loop or alarm on a P&ID - where a sensor may sit, root valves, installation needs of common measurements, which measurements each equipment class normally has, and keeping alarms, trips and control independent. Use when adding or reviewing instruments.
---

# Instrumentation and loops

## Purpose and when to use

An instrument on a P&ID is a function with a tag, a place it senses and a signal it sends. This
covers placement and independence. Loop behaviour and tuning: `control-loops`; crediting a trip as
a safeguard: `safeguard-crediting`. Lists: `lists-sync`.

## Required inputs and missing inputs

The measured variable and point, the duty (indicate, control, alarm, trip), the service. Tag
letters follow the identification standard the project adopted; this skill does not reproduce it.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Where the sensor sits**
- Temperature: in moving fluid, not a stagnant leg, in a thermowell. Column tray temperatures at
  the downcomer, overhead and bottoms in the piping (CCPS, *Guidelines for Engineering Design for
  Process Safety*, §9.2.1).
- Pressure: close to the point of interest and never with a process block valve between it and
  that point, which leaves it reading a dead leg (CCPS §9.2.2). Its own root valve does not count.
- Level: referenced to the container through shell nozzles, directly or via an external bridle,
  not from flowing piping such as an outlet or pump suction (CCPS §9.2.4; Toghraei, *P&ID
  Development*, Wiley 2019, §13.11.1.3).
- Flow: element upstream of and close to its control valve (Toghraei §13.13).
- Root valve on a tap that opens a process connection (pressure, differential pressure, level
  bridles, sample and gauge points) so the instrument can be serviced online (Toghraei §8.7.2).
  A thermowell, diaphragm seal or non-intrusive instrument opens none.

**Installation needs** (Bolton, *Instrumentation and Control Systems*, Elsevier 2004, Ch 2): an
orifice is tapped about one pipe diameter upstream and half a diameter downstream and needs
straight run; it silts on particle-laden liquid. A glass-tube variable-area meter is mounted
vertically (a note, not drawn). Differential-pressure level on a closed tank takes its low side
from the gas space, or the reading drifts with pressure. A thermowell slows response. A resistance
element with two wires suits short or calibrated runs; three or four wires cancel cable
resistance on long runs. Signals carry a live zero.

**What each equipment class normally has** (Toghraei §14.9): level on a non-flooded container,
pressure on a gas-filled one, discharge pressure on a centrifugal pump, temperature on every
exchanger stream, vibration with discharge temperature and pressure on a compressor, differential
pressure across a filter or strainer. Priority sets the form: test point, field gauge, control-room
indicator or loop.

**Alarms, trips, control**
- A trip acts on the high-high or low-low limit, leaving high or low as the operator warning
  (Toghraei §16.7; CCPS §9.4).
- A trip and a control loop do not share a sensor, process connection or final element; redundant
  sensors have separate taps (CCPS §9.2.8, §9.3).
- Ask whether a trip's final element reaches the safe state on demand. Spring-return fail-safe is
  the usual answer; a motor-operated or electro-hydraulic actuator that fails in place is
  acceptable only if the verification credits its power supply and stroke time.
- A gauge has no signal line; a transmitter does and sits in the field.
- Trips and interlocks are recorded in `control/cause-effect.yaml` (see `pid-draft`).

## Validation and failure handling

Do not call a thermowell-less or root-valve-less instrument a defect where the type needs none.
`cheme validate` checks the lists and interlock tags, not the placement rules above.

## Outputs and provenance

Each function by tag, what it senses and drives, placement assumptions, letters not resolved.

## Required human judgment

Trip logic and final-element failure state, independence of layers, redundancy.

## References

CCPS §9.2.1, §9.2.2, §9.2.4, §9.2.8, §9.3, §9.4; Toghraei §8.7.2, §13.11.1.3, §13.13, §14.9,
§16.7; Bolton Ch 2. Needs review before operational use: all section numbers (inherited); the
final-element statement has no section citation in the source and is kept as a question.
