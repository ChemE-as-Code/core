---
name: utility-systems
description: Overview of plant utilities - steam, condensate, cooling water, nitrogen, instrument and plant air, boiler feed water, fuel gas, hot oil, chilled water - what each contains, how it is isolated from the process, and an index of one deeper skill per system. Use before adding or reviewing any utility connection.
---

# Utility systems

## Purpose and when to use

Utilities are what the process consumes rather than makes: heating, cooling, purging, cleaning and
instrument power. They must stay available when the plant is down, because steam and nitrogen free
a vessel of hydrocarbon and air then ventilates it before entry (Karre, *P&ID: A Stepwise
Approach*, De Gruyter 2023, §6.1). Which systems a plant has is plant-specific. Utility
connections are added to a P&ID after the process piping and control, and before isolation, drain
and vent valves (Karre §1.9).

Members, by flat name:

| Skill | Covers |
|---|---|
| `utility-steam-and-condensate` | Header levels and letdown, desuperheating, trap stations, condensate return and contamination |
| `utility-boiler-feed-water` | Water grades, deaerator, dosing, polishing, boiler blowdown and protection |
| `utility-cooling-water` | Once-through, recirculating and indirect seawater circuits, exchanger water side, closed loops |
| `utility-air-and-inert-gas` | Instrument and plant air, nitrogen, purging, tank blanketing |
| `utility-fuel-systems` | Fuel gas conditioning, the fuel train to each burner, fuel oil |

## Required inputs and missing inputs

The project's fluid or service codes and line-number vocabulary: one project's steam code is
another's condensate, so confirm the code list before reading a service from a line. The
utilities the plant actually has, and the project's own standard for levels, pressures and
isolation arrangements. If absent, ask.

## Workflow and tools

At flowsheet level a utility is a terminal in `process/flowsheet.yaml` with a `utility:` entry
(kind, supply and return temperature, minimum approach) from the design basis; every heater,
cooler, machine, column and non-adiabatic reactor needs an energy stream to one, and
`cheme process energy` reports the gaps (skill `process-design`). Beyond that, engineering
guidance only; core has no calculation for utility sizing or arrangement.

**What each system contains** (levels and figures are examples, not standards):

- **Steam** at several levels set by the site. One reference gives about 600, 250-300 and 50 psig
  (Karre §6.2.1); refineries often run four (Parkash, *Refining Processes Handbook*, Gulf 2003,
  Ch 10). The boiler superheats so that transit losses do not condense the steam.
- **Condensate**, named after its steam and cascaded through flash drums towards the deaerator.
  A letdown leaves steam superheated, so it is often paired with a desuperheater.
- **Cooling water**: tower, circulating pumps, strainer at the pump suction, network, exchangers.
  Usually on the tube side where it can be cleaned, but confirm the side. Most exchangers get no
  temperature control. A thermal-relief valve on the water side is no protection against tube
  rupture.
- **Low-pressure nitrogen** for purging and blanketing; **instrument air** compressed, cooled,
  knocked out and dried, delivered at each battery limit (instrument tubing is field-routed and
  not drawn); **plant air**, undried, for tools and stations. Plant air is not a breathing supply.
- **Water grades**: clarified, soft, boiler feed, demineralised (stored in corrosion-resistant
  or lined material).
- **Fuel gas**: sweetened before firing where it carries H2S; knockout drums and a fuel train.
- **Hot oil**, a closed loop for duties above steam's reach: surge drum for thermal expansion,
  fired heater, circulation pumps with basket strainers on the inlets, then the users.
- **Tempered and chilled water**, closed loops with a buffer tank or chiller.

**Isolating a utility from the process.** A hazardous fluid backing into a shared header endangers
every other user of that utility (Karre §6.3). For an intermittent connection (purge, steam-out,
flushing), from the header towards the equipment: a piping specification break (one source's
practice, not universal; the question underneath it is pressure rating, which check valves do not
settle); check valves against backflow with a drain connection; a spectacle blind normally closed
(unlike a maintenance blind, which is drawn open); and a further isolation valve. Keep the run from
the first block to the equipment short. A continuous user (blanketing, seal gas, reboiler steam,
cooler water) cannot have a normally closed blind; it keeps check valves and isolation and relies
on utility pressure staying above process pressure. Client standards vary the arrangement.

**Distribution and stations.** At a unit's battery limit a utility line carries a block valve, a
pressure gauge, a pressure transmitter and a flow transmitter; each main header carries a block
valve (Karre). A utility station groups clarified water, plant air, low-pressure steam and
low-pressure nitrogen; reduced combinations are common. Each utility's hose coupling is unique to
it so that nitrogen cannot be connected where air is expected. Hot water for cleaning is made by
mixing steam into water through a unit that cuts the steam if the water fails; plain mixing
delivers live steam at the nozzle. Headers are sized with roughly 20-30 % margin for future
demand.

## Validation and failure handling

`cheme process energy` reports utility-terminal gaps (`cheme.boundary-*`); `cheme validate` checks
the YAML. The arrangements above are not checked by cheme; the listing of questions in a review is
the output. When a figure here conflicts with the project's standard, the project wins.

## Outputs and provenance

Name the utility, its level or grade, and the isolation arrangement added or found missing, and
state which figures came from a project standard and which from a textbook example.

## Required human judgment

Levels, grades, isolation philosophy and client standards. Nothing here certifies that an
arrangement is safe; protective statements are prompts for questions to the project.

## References

- Karre, *P&ID: A Stepwise Approach*, De Gruyter 2023, §1.9, §6.1-6.3, §6.2.1.
- Parkash, *Refining Processes Handbook*, Gulf 2003, Ch 10.
- Retained as general method: isolation of utility from process, header/stations. Needs review
  before operational use: the 20-30 % header margin and the statements on station couplings and
  steam-water mixing units, which the sources read do not state and which are general engineering
  guidance, not cited.
