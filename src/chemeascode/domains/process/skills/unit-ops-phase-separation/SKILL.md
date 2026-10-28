---
name: unit-ops-phase-separation
description: Gas-liquid and three-phase separators, knockout drums, scrubbers, slug catchers and coalescers - separation mechanisms, what a separator needs for its duty, horizontal versus vertical, and control. Use when a separator or slug catcher is designed or reviewed; phase identification itself is phase-calculation.
---

# Phase separation

## Purpose and when to use

Separation uses three mechanisms in sequence: a momentum change at the inlet, gravity settling in
the body, then coalescence of what is too fine to settle (Mokhatab, Poe and Mak, *Handbook of
Natural Gas Transmission and Processing* 3e, Elsevier 2015, Ch 4). Gravity alone rarely removes
droplets below about 250 micrometre. For which phases exist at given conditions use
`phase-calculation`.

## Required inputs and missing inputs

Phases present, flows, densities, droplet size to remove, carryover the downstream equipment
tolerates, slugging tendency, solids. Ask what the vessel protects before judging it.

## Workflow and tools

Engineering guidance only; core has no calculation for this beyond `flash` units
(`process-simulation`) and vessel volume and residence time in `cheme datasheets fill`.

A gas-liquid separator is built from: a primary section with an inlet device, a gravity section
with retention time, a mist extractor at the gas outlet, and pressure and level control. How many
a vessel needs follows its duty. One protecting a compressor, cold box or catalyst needs all of
them (and an inlet device that does not shatter droplets); a bulk knockout sized on gravity alone
may have a plain inlet nozzle and no demister. A liquid-liquid separator or plain liquid knockout
has no gas outlet to demist, and a vessel floating on a downstream system may have no pressure
control of its own.

Three-phase horizontal: inlet device, a water-wash zone, settling section, oil weir with the water
outlet upstream of it, gas to the mist extractor and out through a pressure valve. Vertical: gas up
through the mist extractor, liquid down a downcomer to a spreader at the oil-water interface, a
chimney equalising pressure.

| Horizontal | Vertical |
|---|---|
| Large volumes, three-phase, foaming, medium to high gas-oil ratio; smaller diameter for gas rate; larger surge; level control more critical; solids harder to clear | Small flows, very high or low gas-oil ratio, limited plot; level control less critical; solids clean-out easy; larger diameter for gas capacity |

In a horizontal vessel settling is transverse to the gas flow; in a vertical vessel droplets fall
against the rising gas, so gas velocity competes with settling velocity.

Control: pressure on the gas outlet; for three-phase duty an interface level controller on the water
dump and a separate oil level, two loops, one an interface measurement.

Related: a scrubber has a very high gas-to-liquid ratio, for secondary duty, not for slugging
streams. A slug catcher is sized for the largest slug the line can deliver; above roughly 100 m3
the finger type tends to replace the vessel type on cost. Its design code (piping or vessel)
follows the design and jurisdiction, and relief, depressuring and inspection apply either way. It
often holds a large high-pressure inventory; emergency depressuring and its rate come from a
depressuring study, not from this skill. Multistage separation uses two to four separators in
series at falling pressure, three the usual optimum; low-pressure gas needs recompression to be
recovered. A coalescer polishes aerosols below about 5 micrometre.

## Validation and failure handling

Questions for a design: a protective separator with no inlet device or mist extractor; a
three-phase vessel with one level loop; a water outlet downstream of the oil weir; a slug catcher
with no depressuring basis; a vertical vessel on a duty that can slug.

## Outputs and provenance

State the duty, what the vessel protects, and the source of each figure. Record in `DESIGN.md`.

## Required human judgment

Slug catcher code, depressuring and every relief provision need a person; nothing here certifies
safety.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing* 3e, Elsevier 2015, Ch 4.
- `phase-calculation`, `process-simulation`, `datasheets`.
- Retained as general method: mechanisms, section roles, horizontal versus vertical direction.
- Needs review before operational use: 250 micrometre, 5 micrometre, 100 m3, three stages.
  The source's compressor-suction level-trip check was dropped (no cited basis).
