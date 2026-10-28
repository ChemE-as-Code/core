---
name: control-safeguarding-and-interlocks
description: Questions to ask when reading or adding an interlock, trip or alarm - the order of protection layers from control to relief, why a P&ID cannot say what an interlock does, switching-valve tag letters, kinds of safety function, fire and gas, and what a drawing at an early revision may legitimately lack. Use when working on control/cause-effect.yaml, reviewing trips and alarms before a HAZOP, or judging a safety function shown on a P&ID.
---

# Safeguarding and interlocks

## Purpose and when to use

Orientation for reading and drafting protective functions: alarms, trips (interlocks) and their
relation to control and relief. It guides questions; it does not establish that a layer is
independent, assign a SIL or show that a function is adequate. Use it with `control-loops`
(regulatory control is not a safeguard), the HAZOP skills `hazop-study` and `hazop-review`, and
`control/cause-effect.yaml`.

## Required inputs and missing inputs

- `control/cause-effect.yaml` (the interlocks by id), `control/loops.yaml`, the P&IDs and the
  instrument and special-items lists.
- The revision or issue stage of the drawings, and the hazard assessment (HAZOP, LOPA or other)
  that justifies each function. If these do not exist, say so; do not infer the function from the
  drawing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Tools that help: `cheme cause-effect`
(matrix of the C&E file), `cheme validate`, `cheme show <tag>`.

**Layers.** Protection is commonly described as layered, each acting further out than the last
(Toghraei, *P&ID Development*, Wiley 2019, §16.4): basic control, alarm, safety instrumented
system, mechanical relief. Read it as a prompt: a trip firing suggests the alarm layer did not
recover the plant; a relief device lifting suggests the trip did not, and lifting moves process
fluid to atmosphere or flare. Whether two layers actually fail independently (shared sensor, valve,
power, logic solver) is for the hazard study; `cheme.control-shared-element` flags only a
shared tag.

**Alarm and trip settings.** Alarms at high/low, trips at high-high/low-low, with time between
them for the operator to act. How much time depends on process dynamics, sensor and final-element
response and the action required; take setpoints and delays from the C&E and hazard basis, never
from a typical figure. An alarm set at the trip point gives no warning. A trip with no alarm on the
same parameter is a question to put against the C&E table, not a defect: a safety function with its
own sensing may not need one, and many alarms only prompt operators.

**Features of safety functions to ask about.** Where risk is judged very high the duty may be given
to the safety system with no basic-control loop for it, which can be deliberate. Sensor and final
element are usually kept close together so the action is fast. Composition measurements are often
avoided in safety functions as less reliable than pressure, level, flow and temperature. A command to a valve is not evidence it moved; limit switches
(open/closed position feedback) on critical valves report real position.

**What the drawing cannot say.** A P&ID usually condenses a function to an interlock symbol with
a number on each participating element; what happens (which valve opens, which closes) lives in the
cause-and-effect table (Toghraei §16.8). So: do not infer the action from the drawing; an interlock
number without a C&E row is a finding; sparser or denser depictions of the same function are not
by themselves defects. An unmarked interlock symbol does not say whether it is process (BPCS) or
safety (SIS): ask.

**Tag letters** (ISA-style, to be checked against the project's own identification standard):
`XV` is commonly a switching valve driven by one event, `UV` by several events, `KV` by time or a
schedule. Time alone does not rule a function out of the safety layer (a burner pre-purge is
timed), so read the C&E rather than the letter; a `KV` presented as a safety function with nothing
in the C&E to support it is a question.

**Kinds of safety function.** Emergency shutdown removes energy; emergency isolation (often
double block and bleed) follows where a leak would still be intolerable; emergency depressuring
(blowdown) empties inventory to flare or another safe place, to a stated pressure in a stated time
(the word "blowdown" also names a relief valve's set-to-reseat gap, a boiler draw-off and an
adsorber step: say which). High-integrity pressure protection cuts off a high-pressure source
before it reaches equipment not rated for it; crediting it in place of a relief device, or to reduce
its size, would need a case under the applicable functional-safety standard (IEC 61511) and
acceptance under the pressure-equipment rules in force, which not every jurisdiction grants. Fire
exposure and thermal expansion are cases where mechanical relief is normally still expected. Never
read a protection layer on a drawing as a reason to omit relief. Name the reach of a function: one
item, a few items, a unit or the plant.

**Burner management.** Fired equipment with an enclosed combustion chamber (heater, boiler,
furnace, incinerator) is commonly asked: is there a proven air pre-purge (set volume changes at
proven flow) before light-off, flame proving, and fuel trip valves? Open flares and pilots have no
chamber to purge. Snuffing steam is a separate connection and is not the pre-purge. Requirements
are set by the applicable code (for example NFPA 85/86, EN 746-2 or local rules), not by this skill.

**Fire and gas.** Detection of fire, flammable and toxic gas; alarm is its minimum output, and it may
also start shutdown, deluge or ventilation shutdown: ask what it actuates. Detector and alarm
locations belong on the plot plan, not the P&ID, so missing detectors are not a P&ID defect; the
valves and dampers it drives are plant equipment and do belong on the drawing.

**Revision stage.** Control-loop structure is preliminary on early issues and complete later;
safety-function structure later still; monitoring-only instruments last (Toghraei §19.5). Establish
the revision before reporting absence of a safety function.

## Validation and failure handling

Things worth raising as questions: an interlock id with no C&E entry (`cheme validate`); alarm
and trip at the same point; a safety function whose final element has no stated safe state; a
critical switching valve without position feedback; a loop sharing a sensor or valve with an
interlock (`cheme.control-shared-element`, `cheme.control-alarm-trip`). Say plainly when the C&E
table, not the drawing, holds the answer.

## Outputs and provenance

`control/cause-effect.yaml` and its matrix from `cheme cause-effect`; review notes recorded
through the `review` and HAZOP skills. Cite the document that justifies each trip.

## Required human judgment

Layer independence, required integrity, trip setpoints and delays, response times, safe states and
the case for any substitution of a safety function for relief are decisions for the HAZOP/LOPA
team and responsible engineers under the applicable standards. This skill certifies none of them.

## References

- Toghraei, *Piping and Instrumentation Diagram Development* (Wiley 2019), §16.4 (layers), §16.8
  (cause-and-effect), §19.5 (issue stages): general method, paraphrased and independently verifiable.
- IEC 61511 and burner-management codes: named for orientation only; nothing here is taken from their text.
- Needs review before operational use: the tag-letter meanings (secondary description of ISA-5.1),
  the point that composition analysers are generally avoided in safety functions, and burner pre-purge practice.
- Skills `control-loops`, `control-narrative`, `control-sequences`, `hazop-study`, `hazop-review`,
  `hazop-assessment`, `area-classification`.
