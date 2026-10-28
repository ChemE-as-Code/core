---
name: relief-scenarios
description: Ask which cause a relief device answers, which scenario governs its size, and when a device may be unnecessary - external fire, blocked outlet, control valve failure, tube rupture, thermal expansion, utility failure, runaway reaction, vacuum - from CCPS chapter 14. Use when asked why a relief device is needed, what it protects against, or whether one can be left out. Questions and review only; no sizing.
---

# Relief scenarios and the governing case

## Purpose and when to use

A relief device exists to answer a named cause. If nobody can name the cause, the device has
neither a set pressure nor a size, so "which case is this device for?" is the most useful question
about one. Use this skill to put that question, to check that the drawn arrangement is credible for
the claimed cause, and to see which exemptions are claimed. How a device is connected and where it
discharges is a drawing matter (`pid-draft`); sizing is a relief study. Layer argument and cause list
follow CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE), section 2.1.2 and
chapter 14; the list is the set of common causes, not a complete enumeration (CCPS attributes
the full list to standards outside this source).

## Required inputs and missing inputs

The P&ID and line list, `process/design-basis.yaml`, the equipment and special-items lists, and
where they exist the datasheets (design pressure, MAWP), the relief study and the HAZOP. Not
derivable from drawings: design pressure, set pressure, orifice size, relieving rate, wetted
area, back pressure, whether two-phase flow occurs, which case governs. Ask for the document that
holds each; do not estimate it. Optional relief data on a P&ID cannot be relied on.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Walk the plant and, per device, ask
which of these causes it is for and what in the documents makes that credible:

- External fire: wetted wall heats and boils the contents where a pool fire could reach; gas-filled
  vessels are in scope for thermal expansion of the gas, and a depressuring valve does not by
  itself excuse a relief device (CCPS 14.2.1.2). Relief does not make the vessel safe: the dry
  vapour-space wall can still fail by overtemperature (14.2.1).
- Blocked outlet: an outlet valve closed while a pump, compressor or higher-pressure source keeps
  delivering. For a fired heater coil the protection belongs at the coil outlet, upstream of the
  outlet block valve (14.2.4.2). A blocked inlet is different: with no flow the tubes overheat while
  the pressure stays normal, so a relief device cannot answer it; the answers are low-flow alarm
  and fuel cutout. Do not report a missing relief device for that case.
- Control valve failure, open or closed: credit the position that makes the load worse, not the
  drawn fail position; the tag describes loss of utility and a valve can also stick (14.2.2.6,
  2.6.5). A manual bypass counts, and where its capacity exceeds the valve's it sets the case
  (14.2.3.3).
- Tube rupture: high-pressure side into low-pressure side. The code scope covers internal
  failure of heat exchangers and of other enclosures with a bundle, coil or jacket; ask for the
  design pressure of both sides (14.2.3.1).
- Thermal expansion of liquid trapped between closed valves and warmed by tracing, jacket, coil, an
  exchanger or the sun. The isolatable segment and its heat source are both drawn.
- Power failure: how far it reaches (one item, a substation, the plant) is the question; spares on
  separate motor control centres or a turbine driver on one of a pair show that it was bounded
  (14.2.2.5, 3.8.7). Cooling or reflux failure removes the condensing duty from a column or
  refrigeration loop; utility failure (instrument air, steam, cooling water, inert gas) reaches
  whatever the utility served.
- Runaway reaction: kinetics and calorimetry decide the size and the drawing cannot (14.2.4.1). The
  drawing does show whether the case was addressed: relief to a knockout or catch tank, quench or
  inhibitor injection, feed trip, remote depressuring (4.4.1.2). Say which you can see.
- Vacuum: draining or pumping out without a vent path, or condensing a vapour space (14.2.2.9).
  A fixed-roof tank normally needs inbreathing as well as outbreathing; design for full vacuum is
  preferred where practicable (14.3.6). On an inerted flammable tank a missing air-admitting
  breaker may be deliberate (4.3.1.2). A floating roof has no vapour space to breathe.

Raise as questions only, without demanding a device: vapour breakthrough after loss of liquid level
into a lower-rated system (a consequence in the source, not a developed sizing case), and reverse
flow through a failed check valve (treated as a backflow and contamination hazard, answered by
instrumentation and double block and bleed).

Which case governs, two different questions (CCPS 15.1.7):

- A device is sized for the largest single credible case, not by adding independent cases.
  Adding streams within one case is legitimate where they belong to it (a vacuum tower losing motive
  steam relieves process steam, overhead gases and non-condensables, 14.2.2.11; a fixed-roof tank
  vacuum vent combines maximum withdrawal and thermal contraction, 4.3.1.1).
- A header, knockout drum and flare are sized for the cumulative load of everything that can
  discharge together, so common-mode causes (fire, power failure, cooling-water failure) dominate.
- An instrumented shutdown may be credited to reduce flare and header load, but the recommended
  practice is to assume the trip on the largest single contributor does not work (15.1.7, 4.4.2).
  Crediting a trip in place of a device or to shrink one is a heavier case: see `safeguard-crediting`.

Routes by which a device may not be required. Each removes one scenario, not the device, unless
every case is removed. Treat each as a claim to verify:

- Low-side rating: a low-pressure side designed to at least two-thirds of the high-pressure side
  is frequently taken as exempting its relief valve from the tube-rupture case only (14.2.3.1). The
  fire, blocked-outlet and thermal-expansion cases remain. CCPS reports this as common practice and
  leaves the deciding criterion to a standard not in its text. Numeric threshold: manual review
  against the project's code.
- Containment by design: rating both exchanger sides for the maximum attainable pressure removes
  tube rupture for the shell; rating for full vacuum removes the vacuum case (2.6.1). A reactor rated
  to contain a runaway removes the need for a large emergency relief system, not for relief, and only
  where kinetics and side reactions under runaway are established (4.4.1.1).
- System rated above the source: equipment designed for the maximum pressure the pump, compressor
  or upstream source can reach is not overpressured by a blocked outlet (14.2.2.1). Raising a
  device's set pressure on equipment of unchanged rating is not this; it removes the protection.
- One device for several items: the path between them has no block valve, no potential blockage
  and enough capacity (14.5.2, 14.2.1.1). Block valves are drawn; pressure drop and accumulation are
  not.

Block valves in the relief path are not banned. Sparing (parallel devices with full-port or
three-way isolation, a bleed between block and device, key-lock or car-seal) is the recommended
way to maintain a device on line (14.5.2); all of it is drawable. What is never acceptable is a
system left with no assured protection.

Common traps: assuming the drawn fail action; forgetting the control-valve bypass; crediting an
escape path a check or control valve will close; summing cases for one device; assuming every trip
works; assuming only the normal fluid is present when wash solvents may be; assuming single phase;
assuming a device that has lifted is still dependable before it is checked.

## Validation and failure handling

`cheme validate` and the P&ID checks do not know the governing case. A missing device is a prompt
to ask which cause was intended, not a verdict, and no check evaluates the exemptions above.
Findings about vessels, exchangers or tanks without a device are questions of this kind.

## Outputs and provenance

State the cause you think the device answers, what in the documents supports it, and what you
could not establish, naming the datasheet or study that holds it. Record the claimed governing
case and its source in `DESIGN.md` or the relief study, never a number you inferred.

## Required human judgment

The governing case, the credited scenarios, set pressure, size, the exemption criteria and
whether an exemption is acceptable are for the relief study and the HAZOP team. This skill never
certifies that protection is adequate.

## References

- CCPS, *Guidelines for Engineering Design for Process Safety* (AIChE): sections 2.1.2, 2.6.1,
  2.6.5, 3.8.7, 4.3.1, 4.4.1, 4.4.2, chapter 14 (14.2.1 to 14.2.4, 14.3.6, 14.5.2), 15.1.7. Mechanism
  statements are retained as general method; the two-thirds figure and all section-cited
  exemptions need review before operational use.
- Skills `process-safety`, `safeguard-crediting`, `hazop-equipment-causes`, `pid-draft`.
