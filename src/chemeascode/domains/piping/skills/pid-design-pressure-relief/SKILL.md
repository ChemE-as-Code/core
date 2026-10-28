---
name: pid-design-pressure-relief
description: What to consider for relief devices, rupture discs and tank breathing on a P&ID - where a device is needed, precise terms, inlet and outlet content, back pressure and valve type, rupture-disc combinations. Use when adding, moving or reviewing a relief device.
---

# Pressure relief

## Purpose and when to use

A relief device is the last layer; nothing in its path should reduce, delay or redirect the
release. This skill prompts questions; scenarios, sizing and set pressure are `relief-scenarios`
and the project's relief study.

## Required inputs and missing inputs

The governing overpressure scenarios, design pressure, set pressure with unit, fluid and phase at
relief, discharge destination and its back pressure. None is on the P&ID by default; ask.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Where a device is needed**: any enclosure that can be blocked in with an overpressure scenario
(fire, blocked outlet, thermal expansion, control or utility failure, tube rupture) (Toghraei,
*P&ID Development*, Wiley 2019, §12.9; CCPS, *Guidelines for Engineering Design for Process
Safety*, §14.2). Typical candidates: pressure vessels, each exchanger side, positive-displacement
pump and compressor discharges, blocked-in liquid lines exposed to heat. An atmospheric tank needs
a breathing path in both directions plus emergency venting for fire (`pid-design-vessels-and-tanks`).

**Terms** (Zappe, *Valve Selection Handbook*, Elsevier 1999, Ch 5): set pressure is where the
valve starts to open; overpressure is the rise above it while relieving; accumulation is the rise
above the vessel's rated working pressure; blowdown is set pressure minus reseat pressure; chatter
is rapid opening and closing with the disc striking the seat. Back pressure is superimposed
(present before opening) plus built-up (made by the discharge).

**Layout questions**
- Inlet pressure loss at rated flow must stay below the valve's blowdown, otherwise it reseats and
  reopens repeatedly; take the limit from the adopted code. The fix is a larger inlet, not a
  longer one.
- Back pressure decides the valve type and what may share a header: a conventional valve's set
  pressure shifts with superimposed back pressure; a balanced bellows valve tolerates more, and
  its bonnet vent may need piping to a safe place; a pilot-operated valve is little affected, and
  needs backflow prevention if outlet pressure can exceed inlet. An open-bonnet valve must not
  discharge to a closed header. Take limits from the manufacturer and code.
- An oversized device can cycle at low flow; ask the manufacturer about restricting lift.
- On a vessel, mount on the container, close, on a top nozzle; on a pump or compressor discharge
  or exchanger side, on the connected pipe. Connecting piping short, not smaller than the device
  inlet; relief piping may widen away from the device, never narrow.
- Nothing in the path restricts or delays release: no control valve, and no check valve placed to
  stop forward flow. A pilot valve's own backflow preventer is part of the device.
- Isolation valves in the path, if the project allows any, are full bore and locked or car-sealed
  open, which the model cannot record: say it in the description. A conventional or reduced-bore
  butterfly valve does not suit (Sotoodeh, *A Practical Guide to Piping and Valves for the Oil and
  Gas Industry*, Elsevier 2021, Ch 2); a certified full-bore one with locking is used on large
  low-pressure vents where nothing else is practical.
- The outlet goes to a safe location (flare or vent header, or a safe atmospheric point).

**Rupture discs**: they suit very fast excursions, no-leak fluids, viscous fluids, and services
where solids or cold would seize a valve; they do not reclose. With a relief valve, a disc
upstream protects the valve from corrosive fluid and leakage, one downstream keeps header fluid
out. Ask how the space between disc and valve is monitored, since pressure trapped there changes
the burst pressure.

## Validation and failure handling

Do not treat absence of a device as an error before the blocked-in case is established, or its
presence as adequate before the scenario is. Recording: set pressure with unit, vacuum set
pressure for vacuum devices, inlet and outlet sizes, tag.

## Outputs and provenance

Device, tag, set pressure with unit, what it protects, discharge point, back-pressure assumption.

## Required human judgment

Everything quantitative: scenario, set pressure, sizing, header duty, interspace arrangement.

## References

Toghraei §12.9; CCPS §14.2; Zappe Ch 5; Sotoodeh Ch 2. Needs review before operational use: the
back-pressure and valve-type statements and the interspace question carry no section citation in
the source and are included as questions only; the terms are general method (Zappe).
