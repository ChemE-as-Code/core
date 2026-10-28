---
name: pid-design-vessels-and-tanks
description: What to consider on a vessel, drum, separator or tank on a P&ID - nozzle set, level and pressure measurement, drains and vents, relief, and breathing and flame protection of atmospheric tanks. Use when adding, completing or reviewing a container.
---

# Vessel or tank

## Purpose and when to use

A container is drawn for normal operation and for filling, emptying, inspection and protection
(Toghraei, *P&ID Development*, Wiley 2019, §9.9). Unit-level behaviour of separators:
`unit-ops-phase-separation`.

## Required inputs and missing inputs

Design pressure and temperature, fluid and whether flammable, roof type of a tank, whether people
enter it, what blanket gas if any. Ask for these.

## Workflow and tools

Engineering guidance only; core has no calculation for this.

**Nozzles**
- Process nozzles for every stream; main streams normally DN50 and above (Toghraei §9.9.4).
  Injection, dosing, sampling, analyser connections and small vessels are legitimately smaller.
- Instrument nozzles for level, pressure, temperature; a few spare ones are cheap early.
- Spare process nozzles, about 10 to 20 percent of the operating ones, mid-range sizes (§9.9.1).
- Manway or hand hole for access, sized by the vessel code and project; entry isolation:
  `pid-design-isolation-vents-drains`.
- Drain at the bottom, vent at the top, a relief connection, and on tanks a breathing nozzle and
  an overflow (Toghraei §9.10). Ask whether an outlet needs a vortex breaker; it is a note, not a
  drawn item.

**Measurement**: a non-flooded container has a level measurement; a gas-filled one a pressure
measurement (Toghraei §14.9.1). Take level from the shell, not from an outlet line (CCPS,
*Guidelines for Engineering Design for Process Safety*, §9.2.4); a level gauge has its own vent and
drain valves (Toghraei §13.11.1.3). Ask about a low-level trip on a pump suction drum and a
high-level trip on a compressor suction drum, on their own nozzles, not sharing the control sensor
(CCPS §9.2.4, §4.4.8). Redundant level on hazardous holdup (CCPS §9.2.4).

**Protection**
- A pressure vessel that can be blocked in needs a relief device on its own top nozzle:
  `pid-design-pressure-relief`.
- A fixed-roof atmospheric tank breathes in both directions (free vent, or a breather valve where
  vapour loss or blanketing matters) and needs emergency venting for fire. In flammable service,
  flame protection is a flame arrester or a pressure-vacuum valve certified for flame protection;
  an ordinary breather gives none (Toghraei §9.11, §12.17; CCPS §14.3.5). A floating-roof tank has
  no vapour space; read the roof type before reporting anything missing.
- A blanketed tank adds a blanket-gas regulator and a controlled vent (`utility-air-and-inert-gas`).
- Merged streams into one nozzle need backflow protection where one can push into the other
  (different pressures or fluids, or an isolable source); two gravity drains or branches of one
  header at one pressure need none at the nozzle.

## Validation and failure handling

A separator or drum may sit under a different class name than a vessel; check its drain, vent,
level and isolation by hand. Do not give a tank pressure relief without vacuum relief.

## Outputs and provenance

Nozzles added with purpose, instruments by tag, missing data (design pressure, capacity, service).

## Required human judgment

Relief and venting basis, flame protection, entry isolation.

## References

Toghraei §9.9, §9.9.1, §9.9.4, §9.10, §9.11, §12.17, §13.11.1.3, §14.9.1; CCPS §4.4.8, §9.2.4,
§14.3.5. Needs review before operational use: the DN50 and 10 to 20 percent figures, all section
numbers (inherited), and the flame-protection statement (safety-critical).
