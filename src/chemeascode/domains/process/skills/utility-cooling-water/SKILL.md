---
name: utility-cooling-water
description: Once-through, recirculating and indirect seawater cooling circuits, tower make-up, blowdown and dosing, what each exchanger carries on its water side, catching a process leak into the water, and closed loops. Member of utility-systems.
---

# Cooling water

## Purpose and when to use

Cooling water is most of a plant's water use and mostly uneventful: valves sit open and nothing is
controlled. The drawing matters where the circuit takes water in and throws it out, where a leak
could put process fluid into the water, and at each exchanger's water side. Hub: skill
`utility-systems`.

## Required inputs and missing inputs

Which lines are make-up, return and blowdown (the project's fluid codes), the circuit type, and
for each cooler the process-side and water-side design pressures. Ask when missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Three arrangements** (Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 9). Once-through:
pumps draw from sea, river or lake and the warm water goes to disposal. Recirculating: pumps draw
from the tower basin and the return goes to the tower top. Indirect seawater: fresh circulating
water is cooled against seawater in dedicated exchangers before the tower, so only those need
resistant metallurgy; direct seawater reaches every exchanger. A seawater intake adds low-lift
pumps into a sump, bar, scraper and rotary screens ahead of high-lift pumps, with chlorine
injected upstream of the high-lift suction.

**Recirculating circuit** (Parkash Ch 9; Ray and Das, *Process Equipment and Plant Design*,
Elsevier 2020, Ch 7; Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §6.2.5): basin with
make-up inlet, overflow and drain; circulating pumps with a strainer at the suction into a common
header; blowdown, because evaporation concentrates dissolved solids; chemical injection
(corrosion inhibitor, pH control, biocide or chlorine; sources place these at different points, so
check each is present); a side-stream filter where the project has one. Pump sparing is not fixed
by any source: one sizing example uses two half-capacity pumps with no spare, another asks for
sufficient redundancy with a standby starting on low header pressure (Ray and Das Ch 7; Basu and
Debnath, *Power Plant Instrumentation and Control Handbook*, Academic Press 2019, Ch 2). Where the
water is dirty, a strainer on each unit's supply branch as well (Parkash Ch 9).

**At each exchanger** (Karre §6.2.5, §11.33, §2.9):
- Block valves on water-side inlet and outlet so one fouled exchanger can be separated; blinds
  where the project wants them; butterfly block valves alone are common.
- Usually no temperature control; a control valve belongs only on a temperature-critical duty.
- A small thermal relief valve on the water side against blocked-in water being heated. It is no
  protection against tube rupture.
- Tube-rupture protection where the process-side design pressure is high enough against the
  water-side design pressure for a burst tube to overpressure the water side. Compare design
  pressures, not operating ones; the test belongs to the exchanger relief work. The water side is
  designed for pump dead-head and raising it to be exempt rarely pays, so relief goes on the water
  side, and its discharge carries process fluid and goes to a safe or closed destination, not an
  open drain (Karre §4.2.3).
- Pressure gauges on inlet and outlet, and often a restriction orifice on users at grade, because
  users at different elevations take unequal flow.

Water usually goes on the tube side where it can be cleaned (Karre §6.2.5; Ray and Das Ch 3);
confirm the side. The normal return is designed around 40-47 °C (Parkash Ch 9; Ray and Das Ch 18).
One reference caps the water outlet at about 60 °C, above which minerals deposit (Karre §6.2.5);
deposits follow the hot tube wall, which can run above the bulk return, so treat 60 °C as an outer
ceiling, not a target. The high-point vent on the water side of a hydrocarbon cooler is also where
gas from a leaking tube collects and can be sampled.

**Process fluid in the water.** A tube leak on a hydrocarbon exchanger running above the water
pressure pushes process fluid into the water; on an open tower that becomes a fire and, in sour
service, a toxic hazard. One refinery arrangement uses two return headers: exchangers whose oil
side runs above a stated pressure return to an intermediate header passing an oil separator, the
rest to a clean one (Parkash Ch 9); the threshold is that source's own. The sources describe
nothing for a recirculating tower; that is silence, not evidence the risk is absent. Where
high-pressure hydrocarbon coolers return to a tower with no way shown of catching a leak (a
sampling point or analyser on the return, gas detection at the tower), raise it as a finding and
ask what monitoring the site runs.

**Closed loops.** Tempered and chilled water are closed: a buffer or expansion tank replaces the
basin, with level-controlled make-up; pumps, a cooler or chiller, and the users. No open-type
blowdown or tower treatment (Karre §6.2.11, §6.2.12; Basu Ch 2).

## Validation and failure handling

Nothing here is checked by cheme. Treat missing temperature control, sparing or a missing
strainer as questions, not defects. Whether tube-rupture relief is required is a design-pressure
comparison for the relief study.

## Outputs and provenance

The arrangement used and how the cooling-water lines were identified; the tower's make-up,
blowdown and dosing; per cooler the isolation, thermal relief, tube-rupture relief and its
discharge, and balancing; how a process leak into the water would be caught.

## Required human judgment

Tube-rupture relief need and sizing, leak monitoring, metallurgy for seawater, and sparing.

## References

- Parkash 2003, Ch 9. Ray and Das 2020, Ch 3, 7, 18. Karre 2023, §2.9, §4.2.3, §6.2.5, §6.2.11-12,
  §11.33. Basu and Debnath 2019, Ch 2.
- Sources disagree on pump sparing and chemical injection points. Needs review before
  operational use: the 40-47 °C and 60 °C figures (design values of the sources, not limits) and
  the leak-catching recommendation, which is protective guidance not stated by the sources for
  recirculating towers.
