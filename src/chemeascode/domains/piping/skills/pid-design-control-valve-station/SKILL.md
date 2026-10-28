---
name: pid-design-control-valve-station
description: What to consider around a control valve on a P&ID - block valves, drains, bypass, reducers, piping class through the station, fail action and how the loop is wired. Use when adding, completing or reviewing a control valve.
---

# Control valve station

## Purpose and when to use

A control valve is the item most likely to need work while the plant runs (Toghraei, *P&ID
Development*, Wiley 2019, §8.7.1), so its station exists to let it be removed. This covers what
goes around the valve; what the valve is (`pid-design-control-valve-selection`).

## Required inputs and missing inputs

Service and what is safe on loss of air or power; whether the plant can run on a manual bypass;
valve and line sizes. Ask for the safe state; do not infer it from the valve.

## Workflow and tools

Engineering guidance only; core has no calculation for this. In flow order:

1. Upstream block valve, line size (Toghraei §7.18), and a drain upstream to remove trapped
   liquid before maintenance (`pid-design-isolation-vents-drains`).
2. A reducer when the valve body is smaller than the line (Toghraei §7.11). Both ends of a valve
   normally carry the same nominal diameter; a size change is a fitting (§6.14.1.2). A
   reducing-body valve, with different end sizes for flashing or high-drop service, is the
   exception: record both sizes.
3. The valve, its actuator and a fail action chosen for the safe state of this service
   (Toghraei §7.10.2). The stored value and the drawn text should agree.
4. Enlarger back to line size; downstream block valve.
5. A bypass around the station with a throttling valve (a globe type) no larger than the line, so
   operators can hold the process by hand while the valve is out (Toghraei §6.12.1, §7.13.1). A
   gate or ball bypass gives only open or shut. If the project wants tight bypass isolation, add a
   block valve in series.

**Piping class**: carry the higher class through the whole station, including bypass and
downstream block valve, and drop to the lower class only beyond it (Beale and Bowers, *The
Planning Guide to Piping Design*, Elsevier 2018, §3.4); see `pid-design-materials-and-spec-breaks`.

**Loop**
- The instrumentation function drives the actuator, not a block valve.
- A flow element goes upstream of and close to its control valve, since the valve's turbulence
  corrupts a reading behind it (Toghraei §13.13); pressure and temperature sensors may sit on
  either side.
- A control loop and a trip do not share a sensor or final element (CCPS, *Guidelines for
  Engineering Design for Process Safety*, §9.3).
- Fail action: the test is the safe state of this service on loss of air. It usually, not always,
  follows the heat direction: heat-adding streams normally fail closed, heat-removing streams
  open (Bolton, *Instrumentation and Control Systems*, Elsevier 2004, Ch 6). Exceptions to hold in
  mind: a pilot fuel control valve may fail open so the pilot stays lit while its shutdown valve
  fails closed; a large valve whose sudden movement upsets more than its frozen position may
  fail in place. Where the drawn action differs from the heat direction, ask what safe state was
  judged.
- Where the valve must stroke fast, the stroke time and fail action choose the assembly (valve
  plus actuator), not the body type alone; read it off the vendor data.

## Validation and failure handling

Do not leave the fail action unset. Do not put a control valve on a compressor suction to set
capacity (`pid-design-compressors`) or anywhere in a relief path (`pid-design-pressure-relief`).

## Outputs and provenance

Body and size chosen and why, fail action and its basis, what could not be settled.

## Required human judgment

Fail action, bypass philosophy, class through the station.

## References

Toghraei §6.12.1, §6.14.1.2, §7.10.2, §7.11, §7.13.1, §7.18, §8.7.1, §13.13; Beale and Bowers §3.4;
CCPS §9.3; Bolton Ch 6. Needs review before operational use: all section numbers (inherited),
fail-action statements (safety-critical).
