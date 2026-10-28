---
name: utility-air-and-inert-gas
description: Instrument air and plant air, which users take which, nitrogen supply and backflow protection, purging safely, tank blanketing and its fail positions, and the hazard every blanket or purge gas leaves behind. Member of utility-systems.
---

# Air and inert gas

## Purpose and when to use

Instrument air makes a plant's valves move; nitrogen keeps air out of places it must not be. Both
are needed most when the plant is down, for purging, clean-out and making equipment safe to open
(Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §6.1). Hub: skill `utility-systems`.

## Required inputs and missing inputs

Which lines are instrument air, plant air and nitrogen (the project's fluid codes), the nitrogen
header pressure, the blanket gas for each tank, and the project's confined-space procedure. Ask
for any that are missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Instrument air.** Dried to a low dew point and filtered. One gas-plant reference quotes -40 °F as
typical, another gives the requirement without a number; a dew point means little without its
pressure, so take figure and basis from the project (Mokhatab, Poe and Mak, *Handbook of Natural
Gas Transmission and Processing*, Elsevier 2015, §3.5.1; Toghraei, *P&ID Development*, Wiley 2019,
§17.4.1). A receiver damps swings and backup compressors are expected (Mokhatab §3.5.1); no source
gives a hold-up time. Distribution is header, sub-header, manifold near the users; tubing from the
manifold to each instrument is field-routed and not drawn (Karre §6.2.3; Toghraei §6.10). Every
automatic valve's actuator takes instrument air, not plant air (Toghraei §7.7); where it is
unavailable, valves are hydraulic or electric. Loss of instrument air counts as loss of power for
a pneumatic valve's fail position (Toghraei §7.10.2).

**Plant air** comes from the same compressors undried, for air-driven pumps, tools and utility
hoses (Karre §6.2.4). Where the two share a system, instrument air has priority: low
instrument-air pressure cuts off the plant-air take-off, and that shut-off is drawn (Toghraei
§17.2.4). A critical instrument-air user can also have a loop feed or a local receiver. Plant air
is not breathing air: none of these sources sets a breathing-air quality, so a respirator or
breathing-air point is fed from a separately qualified system. A breathing point fed from plant
air with no purification and monitoring shown is a question for the project.

**Nitrogen** comes from on-site generation, bulk storage or bottles and serves purging, seal gas
and blanketing (Mokhatab §3.5.1). Low-pressure nitrogen is let down from a higher-pressure system;
the pressure differs between sources, so read the project's (Karre §6.2.2, §11.21). Keep process
out of the header (isolation arrangement in `utility-systems`, Karre §6.3): an intermittent
connection carries check valves, a normally closed spectacle blind and a second isolation valve; a
continuous user keeps the check valves and relies on nitrogen pressure staying above process
pressure; one reference asks for a double check valve on a tank's nitrogen supply (Karre §6.2.2).
A temporary hose from a station needs no further check valve at the equipment, since the station
has one (Toghraei §17.2.5), provided the equipment runs below header pressure and the hose comes
off after use.

**Every blanket or purge gas leaves a hazard.** The sources read do not treat this; it is general
guidance, uncited. Treat any vessel, enclosure or pit that has been purged or blanketed as
hazardous to enter until isolated, ventilated and cleared under the site's confined-space
procedure. Nitrogen displaces oxygen without warning. Carbon dioxide does the same, is also toxic
and heavier than air, and an oxygen test alone will not find it. Fuel or natural gas is flammable
and, in sour service, toxic.

**Purging** displaces air before start-up or hydrocarbon before opening up. Steam can purge but
not blanket (Toghraei §17.9.2; Mokhatab §18.7). Conditions that matter more than the gas:
process gas may displace an inert gas, never air (uncited general guidance); steam condenses, so a
steamed-out vessel closed in is pulled under vacuum unless rated for it; test for what is being
removed (oxygen when purging air out, flammables and in sour service H2S when purging hydrocarbon
out); air goes in last and only once flammables are gone (one source lists air among purge media
without that condition, Toghraei §17.9.2); in sour service pyrophoric scale can ignite on opening
(uncited general guidance). The drawing carries nitrogen connections, high-point vents and
low-point drains (Mokhatab §18.7).

**Tank blanketing** holds a small positive pressure of a chosen gas over the liquid (Toghraei
§17.9.1, §9.12). Filling compresses and emptying pulls a vacuum, so both inlet and vent need
control. Published shapes: a self-acting blanketing valve on the inlet with a pressure-vacuum vent
set above it (common, though not set out as a scheme by these sources); one pressure controller
driving two valves in split range with the split point stated (Karre §11.23; Toghraei §14.8.4);
regulators on inlet and outlet, or an oxygen analyser controlling the inlet (Toghraei §15.10);
two regulating valves that never open together, the vent to vapour recovery (Mokhatab §5.5.2).
Inlet and vent must not open together; an inlet regulator with a free vent is the defect to look
for. Where the vent goes is the project's choice (Karre §11.23; Mokhatab §5.5.2; Toghraei §9.11).

**Fail positions: check what each failure loads and whether it is protected.** One reference fails
the nitrogen inlet closed and the vent open (Karre §11.23); another's general rule fails nitrogen
open as a low-energy stream (Toghraei §7.10.2), yet nitrogen at header pressure is often the
largest overpressure source a low-pressure tank has. So ask: an inlet that fails open, is relief
shown able to pass that flow; an inlet that fails closed, is vacuum relief shown; a fuel-gas
blanket whose inlet can fail closed while vacuum relief draws in air turns the vapour space
flammable. Relief sizing is the question to ask. Know the blanket gas: natural gas is sometimes
called inert only while air is kept out; carbon dioxide forms acid with water (Toghraei §17.9.1;
Mokhatab §5.5.1). Pressure-vacuum relief is independent of the blanketing control; a vent to flare
also needs a continuous purge bleed, and a plain overflow defeats a blanket (Mokhatab §5.5.1;
Toghraei §9.11).

## Validation and failure handling

Nothing here is checked by cheme. Present gaps as questions or findings for review, not as
certified conclusions. Never report field-routed instrument tubing as a missing connection.

## Outputs and provenance

Which lines are which gas and how that was established; priority of instrument over plant air;
how each nitrogen connection keeps process out of the header and whether it is intermittent or
continuous; for each blanketed tank the gas, inlet and vent control, fail positions and what
protects each; purge hardware; any breathing-air point fed from plant air.

## Required human judgment

Confined-space entry, breathing-air quality, relief sizing for blanket failures, and the vent
destination. These guide questions; they do not certify safety or independence of protection.

## References

- Karre 2023, §6.1-6.3, §11.21, §11.23. Mokhatab, Poe and Mak 2015, §3.5.1, §5.5, §18.7.
  Toghraei 2019, §6.10, §7.7, §7.10.2, §9.11-9.12, §14.8.4, §15.10, §17.2, §17.4.1, §17.9.
- Sources disagree on blanket gas, nitrogen inlet fail position, and low-pressure nitrogen
  pressure; sources are silent on breathing-air quality and nitrogen asphyxiation. Needs review
  before operational use: all uncited protective statements marked above.
