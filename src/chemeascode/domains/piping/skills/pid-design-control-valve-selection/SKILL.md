---
name: pid-design-control-valve-selection
description: What a control valve is, as a question set - which bodies may throttle, flow characteristic, rangeability, why the valve is smaller than its line, cavitation and flashing, noise, seat leakage. Use when asked which control valve suits a duty or why a valve is smaller than its line.
---

# Choosing a control valve

## Purpose and when to use

`pid-design-control-valve-station` covers what goes around the valve; this covers what the valve
is. Almost none of it is on a P&ID, so most of what follows is a question with a drawing
consequence. Ask before asserting.

## Required inputs and missing inputs

Not on the drawing: characteristic, trim, flow coefficient, rangeability, seat-leakage class,
stroke time, bore. Ask for them with the valve's share of system pressure drop at minimum, normal
and maximum flow, whether the service can flash or cavitate, and the noise prediction. Do not read
them off a body type.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Which bodies throttle.** Seat-opening area proportional to travel makes the globe family
throttle well; rotary and flexible-body valves throttle over part of their range; a wedge gate
valve controls only near closed and should not throttle (Zappe, *Valve Selection Handbook*,
Elsevier 1999, §2). Ball and butterfly classes cover both blocking and characterised control
valves: ask what the trim is. Sources differ on usable band: a butterfly about 15 to 70 degrees of
disc rotation (Zappe §3) against about 30 to 70 percent of range (Toghraei, *P&ID Development*,
Wiley 2019, §7.4.2), which are different quantities. A ball is called a good throttling body
(Zappe §3), also a body passing nothing below about a third open (Sotoodeh, *A Practical Guide to
Piping and Valves for the Oil and Gas Industry*, Elsevier 2021, Ch 2), and a blocking valve needing
a V-port before it may throttle (Toghraei §7.4.2); say so rather than pick. Zappe states his scope
is manual valves, check valves and relief devices: cite him for shared physics, not control-valve
hardware.

**Characteristic** is defined by gain (flow change per unit travel; Poe and Mokhatab, *Modeling,
Control, and Optimization of Natural Gas Processing Plants*, Gulf 2017, App. A): linear constant;
quick-opening greatest low in the range; equal percentage greatest high. The inherent curve is
at constant drop; installed behaviour depends on the valve's share of system drop (Zappe §2; Basu
and Debnath, *Power Plant Instrumentation and Control Handbook*, Academic Press 2019, §6.1).
General guidance (Poe App. A §4.1): equal percentage when the valve takes the minority of the
drop (also usual for temperature loops); linear when it takes the majority and the drop stays
roughly constant (level and flow duties); quick-opening for on/off or large flow wanted at once.
Basu §6.1 gives a finer map for level and flow duties and says the choice needs experience. Where
they disagree: Basu's map can select quick-opening for a modulating level loop; three others
confine it to on/off, fast-start or deluge duty (Poe App. A; Ray and Das, *Process Equipment and
Plant Design*, Elsevier 2020, §19.6; Bolton Ch 7). A quick-opening trim on a modulating level
duty is worth a query, noting one published map selects it. A globe valve is re-characterised by
trim; ball, butterfly and eccentric-plug bodies are not easily (butterfly roughly equal
percentage, eccentric disc roughly linear; Poe App. A, Basu §6.1).

**Rangeability and size.** Rangeability is maximum over minimum controllable flow; turndown is
normal maximum over minimum, about 0.7 of rangeability (Basu §6.1). The installed figure falls
roughly with the square root of the valve's share of drop (Ray and Das §19.6). Throttling near the
seat damages the seating faces (Zappe §2), so a valve absorbing a large drop is often a size or
more below its line: expected, not an anomaly. Control band and sizing band are different
quantities (Poe App. A; Ray and Das §19.6; Basu §6.1): say which the project uses. Where one
valve cannot cover the range, two in split range with a slowed changeover (Basu §6.1).

**Cavitation and flashing** differ. Flashing: downstream pressure at or below vapour pressure, no
recovery, damage is downstream erosion; answers are sizing, downstream pipe room, erosion-suited
body (often angle) and hard trim (Basu §6.1). Cavitation: pressure falls below vapour pressure
inside the valve then recovers, bubbles collapse, damage is pitting at the collapse (Zappe §2);
answers move or prevent collapse by staging the drop, hardening trim, or enlarging the passage
downstream. Staging does not cure flashing; confirm any anti-cavitation trim against the vendor's
flashing range. Zappe's air-injection remedy is a waterworks measure and must not be carried into
hydrocarbon, flammable or oxygen-sensitive service.

**Noise** comes mainly from turbulence downstream (Zappe §2). Two figures near 85 dBA are
different: a candidate trigger for special trim, a metre from the source (Basu §6.1), and a
workplace exposure limit averaged over a day (Toghraei §18). Trim or diffuser treats the source;
lagging and enclosure treat the path.

**Seat leakage** is separate from characteristic: specify a class, never infer shutoff from the
characteristic. Classes are a new-valve property and degrade in service (Basu §6.1). Where the
process needs isolation as well as control, use a separate valve. Isolation-valve leakage
standards are a different system (Sotoodeh Ch 14).

## Validation and failure handling

A plain full-bore ball or gate valve on a modulating duty is worth a query (seat erosion and loss
of shutoff). On a control-valve bypass a ball or gate valve cannot throttle: see the station skill.

## Outputs and provenance

Body class of each valve and whether it settles throttling; the questions asked and what each
would change on the drawing (size step, downstream enlargement, orifice, note).

## Required human judgment

Characteristic, trim, shutoff class and service severity: the vendor and the control engineer.

## References

Zappe §2, §3; Toghraei §7.4.2, §18; Sotoodeh Ch 2, Ch 14; Poe and Mokhatab App. A; Basu and
Debnath §6.1; Ray and Das §19.6; Bolton Ch 7. Needs review before operational use: all numeric
bands (15 to 70 degrees, 30 to 70 percent, a third open, 0.7, 85 dBA),
section numbers (inherited). Anti-surge valve selection is absent from the sources.
