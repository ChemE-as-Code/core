---
name: hazop-equipment-causes
description: Ask which HAZOP deviations actually bite on pumps, compressors, columns, separators, fired heaters, heat exchangers, reactors and storage tanks, and which causes are credible, with the mechanism, from CCPS chapters 4 and 14 and Moran chapters 13 and 15. Use when drafting deviations and causes for a node of a HAZOP study. A starting set for a team, not a checklist.
---

# HAZOP deviations and causes by equipment

## Purpose and when to use

A guide-word grid produces every combination; this skill suggests which deviations carry real
consequence on a given equipment type and why, so that `hazop-study` drafts credible scenarios.
It is a starting set to put to a team, not a checklist and not a deviation table: the source's own
equipment table concerns loss of containment and leaves overpressure causes out, so it is no
substitute. Sources: CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE),
chapters 4 and 14; Moran, *An Applied Guide to Process and Plant Design* (Butterworth-Heinemann
2015), chapters 13 and 15. Wording here is the skill's own.

## Required inputs and missing inputs

The node's members and design intent from the P&ID and `process/design-basis.yaml`, the machine type
(centrifugal or positive displacement, sealed or sealless), the fluids and phases, and the
utilities served. Ask when the machine type, fail position or heat source is not in the files.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Equipment types the source covers:

- Pumps. Low or no flow matters more than high. Deadheading heats the trapped liquid until it
  flashes or decomposes, and pumps have burst this way (CCPS 4.4.11.1). A closed discharge does not
  at once damage a centrifugal pump, though deadheading must still be prevented beyond a very short
  time, whereas throttled suction cavitates it quickly; a positive-displacement pump suffers
  rapidly from a closed discharge (Moran 13). Dry running is a separate deviation and the dominant
  failure of sealless pumps, where it destroys the bearings (4.4.11.1); a level-based inhibit from the
  feed vessel is a usual answer, flow measurement a second.
- Compressors. Surge is the defining low-flow deviation: flow oscillates and reverses, with
  vibration and thrust-bearing temperature that can damage the machine permanently. Stonewall is the
  high-flow limit (4.4.11.2). A reciprocating machine does not limit its own pressure, unlike a
  deadheaded centrifugal one, so it needs relief, and the source notes such valves have failed
  (4.4.11.2). Liquid entering the chamber usually traces to an upstream separator.
- Columns (a thin set; the source is brief). Loss of heat sink from lost coolant, excess reboil or
  fire (4.4.2); lost reflux from power failure, pump trip or a control valve failing closed
  (14.2.2.7); also flooding, fouling, high pressure drop, poor contact and damage to internals.
  Reducing inventory for inherent safety may make a column more sensitive to upset when controls
  cannot react fast enough, for example before a reflux pump runs dry (4.4.2): a consequence to
  check, not an argument against less inventory.
- Separators. High and low level are different hazards. High level carries liquid over to
  downstream machinery; low level lets gas blow by into the liquid line, damaging control valves,
  possibly overpressuring a lower-rated system and contaminating product (4.4.8). Ask whether the
  downstream system is rated for upstream pressure.
- Fired heaters. Firebox explosion at light-off or after flame failure (4.4.4). For coil rupture,
  a closed outlet block valve is answered by a device at the coil outlet, but a closed inlet is not:
  tubes overheat with normal pressure, so low-flow alarm and fuel cutout apply (14.2.4.2;
  `relief-scenarios`). A deviation invisible to the parameter one would instinctively watch.
- Storage tanks. Underpressure and level dominate over process upset. Vent capacity too small for the
  operating cases plus a rapid weather change is a common failure (14.1). Underpressure follows rapid
  withdrawal or sudden cooling; level issues include overfilling, unattended water draw-off, snow or
  water loading on the roof, and a tilted, wedged floating roof (4.3.1.1).
- Heat exchangers. Tube rupture, a blocked-in cold side warmed by the hot side, and for air coolers
  separate fan and louver failures. Which side is to be at higher pressure is a design decision
  (4.4.3.2); ask whether that holds in every state, since blocked-in sides, out-of-service items or
  start-up can invert it.
- Reactors. Loss of cooling, feed or quench, and loss of agitation. A motor ammeter does not detect a
  shaft turning with the impeller gone, so detection must sense agitation near the impeller
  (4.4.1.6): a case of a detector that does not detect what it is credited against. Overcharging has a
  hydraulic answer (restriction orifice, head tank sized to the charge) that the source treats as weak:
  it can corrode, be omitted after maintenance or be removed by a repipe or new impeller, and double
  charging stays a study case (4.4.1.4, 2.5.3).
- Utilities as common cause. Instrument air, power, cooling water and steam reach many items at once.
  Do not assume loss of instrument air drives every valve to its tagged position: the tag describes
  that failure, and a valve can stick.

Scope limits: for process vessels of none of the types above the source's vessel section is
mechanical integrity (welds, materials, nozzle loads) and gives nothing usable on process deviation.
Say so rather than reasoning by analogy from a separator.

## Validation and failure handling

Every proposed deviation is a question for the team: write what you could not judge into `notes:`
of the entry. `cheme safety hazop check` tests references only, not credibility of causes.

## Outputs and provenance

Entries in `safety/hazop/<id>/study.yaml` with `status: proposed`, `by: agent`, the cause by tag and
the mechanism, plus the list of things the files could not settle.

## Required human judgment

Which deviations are credible, the consequences, and whether any listed protection is effective are
the HAZOP team's. Nothing here is complete: a review of this kind does not ensure all hazards are found
(CCPS 10.1.5).

## References

- CCPS 2.5.3, 4.3.1.1, 4.4.1.4, 4.4.1.6, 4.4.2, 4.4.3.2, 4.4.4, 4.4.8, 4.4.11.1, 4.4.11.2, 10.1.5,
  14.1, 14.2.2.7, 14.2.4.2. Moran chapters 13 and 15. Mechanism statements are retained as
  independently verifiable general method, re-expressed; all need review by a person before use in a study.
- Skills `process-safety`, `hazop-study`, `relief-scenarios`, `safeguard-crediting`.
