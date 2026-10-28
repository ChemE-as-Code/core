---
name: pid-design-heat-exchangers
description: What to consider around a shell-and-tube or plate exchanger, condenser or reboiler on a P&ID - configuration by service, stream orientation, temperature measurement, vents and drains per side, condenser and reboiler content, isolation and relief per enclosure. Use when adding, completing or reviewing an exchanger.
---

# Heat exchanger installation

## Purpose and when to use

An exchanger is two enclosures sharing a wall, so most of what it needs comes in pairs (Toghraei,
*P&ID Development*, Wiley 2019, §11.7). Single-exchanger duty and fluid allocation:
`unit-ops-heat-transfer`.

## Required inputs and missing inputs

Both streams (fluid, phase, pressure, temperature), duty, differential temperature at start-up
and upset, design pressure of each side, cleaning needs, for reboilers the type. Ask for what is
missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Configuration follows service
(Ludwig, *Applied Process Design for Chemical and Petrochemical Plants* v3, Elsevier 2001, Ch 10):
fixed tubesheet for general duty where shell-to-tube metal temperature difference stays small in
every case (checked to the construction code, not a rule of thumb); floating head beyond that or
when both sides need mechanical cleaning; U-tube for large differences with clean tube-side fluid
only; kettle when the boiling fluid is on the shell side and needs disengaging space; plate and
frame for close approaches, viscous or corrosive liquids and frequent cleaning, limited by gasket
compatibility, pressure and port velocity. Say which the drawing shows when it matters.

**Streams**: hot in at the top and out at the bottom, cold in at the bottom and out at the top is
usual, condensers and evaporators included; the vendor data sheet decides where it differs
(Toghraei §11.7). A temperature measurement on every stream in and out; the target stream's
outlet is normally controlled (Toghraei §14.9.3). Design pressure and temperature on each
chamber.

**Vents and drains**: Ludwig's list (Ch 10) is vents on the shell and tube-side heads for inerts,
drains on the shell and most heads, and couplings on process nozzles for flushing, sampling and
thermowells. Pattern: `pid-design-isolation-vents-drains`.

**Condensers**
- Non-condensables govern: a trace of inert collapses the condensing coefficient, so vapour must
  reach a vent.
- A partial condenser has a liquid outlet and a vapour outlet that goes somewhere.
- Cooler-condenser and multizone units are named as such.
- Subcooling needs a level to hold (seal, dam baffle, level control), so there is something to
  control.

**Reboilers** (Ludwig Ch 10): kettle (own disengaging space, internal weir fixing level, bottoms
drawn beyond the weir; the same shell as chiller has no weir); vertical thermosiphon (full-opening
valve or variable orifice on the liquid inlet, full-diameter top vapour nozzle, elevation
relative to the column is load-bearing); horizontal thermosiphon (no disengaging space); forced
circulation (adds a pump, `pid-design-pumps`). Viscosity is the first-cut selector: below about
0.5 cP vertical thermosiphon is usual, above it horizontal is usually more economic. Steam-heated
reboilers need condensate removed; see `utility-steam-and-condensate`.

**Isolation and bypass**: block valves on every nozzle and an isolation bypass are justified only
where the plant can run without the exchanger: a parallel spare, or clean-in-place with a large
downstream inventory that averages temperature (Toghraei §11.7.2). A control bypass holding a
temperature is a different thing.

**Relief**: overpressure protection for each enclosure that can be blocked in, tube rupture the
usual governing case (Toghraei §11.7.4). A side permanently open to a protected vessel may already
be covered. CCPS (*Guidelines for Engineering Design for Process Safety* §14.2.3.1) discusses
excusing the tube-rupture case where the low-pressure side is designed to at least two-thirds of
the high-pressure side; that excuses only that case, not fire, blocked outlet or thermal
expansion. Establish the blocked-in case and pressure ratio first (`relief-scenarios`). A
cooling-water side that can be blocked in between two closed valves needs the thermal-expansion
question asked (`utility-cooling-water`); where one valve is locked open nothing is trapped.

## Validation and failure handling

Ask which justification applies before calling a bypass or its absence wrong. Do not put both
vents on one side and both drains on the other.

## Outputs and provenance

Vents, drains and instruments by side; configuration and reboiler type assumed; isolation
justification; missing data.

## Required human judgment

Configuration, relief case and ratio, isolation philosophy.

## References

Toghraei §11.7, §11.7.2, §11.7.4, §14.9.3; Ludwig v3 Ch 10; CCPS §14.2.3.1. Needs review before
operational use: the two-thirds ratio, the 0.5 cP selector, all section numbers (inherited).
