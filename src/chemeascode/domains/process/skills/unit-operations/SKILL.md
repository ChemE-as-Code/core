---
name: unit-operations
description: Index of the unit-operation knowledge skills (distillation, absorption and stripping, adsorption and drying, liquid-liquid extraction, reactors, heat exchangers, evaporation, phase separation, refrigeration) and the five questions that apply to every unit. Use when a question is about a column, absorber, adsorber, extractor, reactor, evaporator, separator, exchanger or refrigeration loop itself, to pick the member skill.
---

# Unit operations

## Purpose and when to use

A unit operation is what a process step does; the equipment is how it is done. This skill is the
index of the member skills and holds the questions common to all of them. The members are
engineering guidance, concise and cited; they give questions to put to a design and rules of
thumb with their source, not calculations.

| Skill | For |
|---|---|
| `unit-ops-distillation` | Columns, flash drums, strippers, batch stills, overhead and bottoms systems |
| `unit-ops-absorption-and-stripping` | Absorbers and strippers with a solvent circulation loop |
| `unit-ops-adsorption-and-drying` | Fixed adsorbent beds, driers, regeneration and switching |
| `unit-ops-liquid-liquid-extraction` | Extractors, mixer-settlers and solvent recovery |
| `unit-ops-reactors` | Stirred tank, tubular, packed and fluidised bed reactors, in their separation and recycle context |
| `unit-ops-heat-transfer` | One exchanger as a unit: duty, fluid allocation, temperature cross, air coolers, fouling, control |
| `unit-ops-evaporation` | Evaporators, multiple effect, vapour recompression |
| `unit-ops-phase-separation` | Separators, knockout drums, slug catchers, coalescers |
| `unit-ops-refrigeration` | Mechanical, cascade, absorption and steam-jet refrigeration |

Overlaps with skills that compute: `separation-method-selection` ranks separation methods,
`phase-calculation` identifies phases, `datasheets` sizes equipment, `reactions` and
`cheme process reactor-choice` handle reactor models and the choice of an ideal reactor. The members
cross-reference them instead of repeating them.

## Required inputs and missing inputs

None to read the guidance. To apply it, the service of the unit is needed (fluids, duty,
pressure and temperature range); ask for what is not in `process/flowsheet.yaml` rather than
assuming it.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Ask, for whichever operation is in
question:

1. What leaves that did not arrive as a product (non-condensables, vents, purges, drains)? A unit
   without a path for it is often incomplete.
2. What circulates, and what drives it? A forced loop carries a pump or compressor; a thermosiphon
   reboiler, natural-circulation evaporator or gravity reflux is driven by density difference and
   shows none. A loop whose fluid degrades, fouls or is lost needs clean-up or make-up; a sealed
   loop of a stable fluid may need neither. Establish which before naming anything missing.
3. What sets an elevation (gravity drain to a drum, thermosiphon head, pump suction head)?
4. What is the control handle? Usually an inventory (level or pressure) and a quality
   (temperature or analysis); name both.
5. What is the unit's own failure mode (flooding, fouling, freezing, surging, coking,
   channelling)?

Material and energy balances of the flowsheet are `process-design` and `cheme process energy`;
rigorous unit models are `process-simulation`.

## Validation and failure handling

Do not report an item as missing before the service is established: many "missing" items are
legitimately absent for a given arrangement (each member names these cases). Say what is
unknown instead of filling it in.

## Outputs and provenance

Report the findings as questions or observations tied to the unit, each with the member skill's
source. Record decisions and their basis in `DESIGN.md`.

## Required human judgment

Selection of the operation, its arrangement, and every safety-relevant provision belong to the
responsible engineer. Nothing here certifies a design as safe or complete.

## References

- Members above; each lists its sources.
- Isolation, relief, vents and drains are P&ID matters; see `pid-draft`.
- Retained as general method: the five questions are generic engineering prompts (no external
  source); needs review before operational use: none beyond the members' own flags.
