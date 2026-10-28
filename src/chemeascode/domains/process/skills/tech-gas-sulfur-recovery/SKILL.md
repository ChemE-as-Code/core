---
name: tech-gas-sulfur-recovery
description: Reference for converting acid gas to sulfur. The Claus thermal and catalytic stages, tail gas treating, sulfur degassing and storage, and the alternatives for lean or small loads. Use when a sulfur recovery unit is being discussed or reviewed, in a gas plant or a refinery.
---

# Sulfur recovery

## Purpose and when to use

Converts H2S in acid gas to elemental sulfur, with a tail gas unit behind it to catch what
equilibrium leaves. Reached from `tech-gas-processing`; the refinery counterpart is
`tech-refining-hydrogen-and-sulfur`, which refers back here for the Claus detail.

## Required inputs and missing inputs

Acid gas flow and composition (H2S, CO2, hydrocarbons, ammonia from sour water stripping), the
recovery or emission requirement, and whether there is a sulfur market or reinjection is possible.
Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Claus equilibrium would need a
suitable reaction and property model (see `reactions`, `thermodynamic-model-selection`); core makes
no claim of a validated Claus model.

Units in flow order: acid gas feed knockout drum (liquid reaching the burner plugs it and damages
refractory); combustion air blowers with main and trim valves; burner and reaction furnace, where
about one third of the H2S is burned to SO2 and the rest reacts with it; waste heat boiler; sulfur
condenser, then two or three reheat, catalytic reactor, condenser stages; sulfur rundown through
hydraulic seals to a pit and pump; tail gas treating (hydrogenation of all sulfur species to H2S,
quench tower, selective amine absorber, acid gas recycled to the Claus front end, vent to
atmosphere or a thermal oxidiser); degassing, then heated storage and forming.

The air ratio is the central loop. Best conversion needs two moles of H2S per mole of SO2,
measured by a tail gas analyser after the last condenser; main air is set feed-forward from acid gas
and a trim valve is driven by the analyser (Mokhatab, Poe and Mak, *Handbook of Natural Gas
Transmission and Processing*, 3rd ed., Elsevier 2015, Ch 13). Transport delay is long, so predictive
schemes can hold stoichiometry better than feedback alone. Converter inlet temperature is set through
the reheat and must stay above the sulfur dew point; condensers run as cold as cooling allows.

Variants: a straight-through Claus needs a rich acid gas; leaner gas is handled by air preheat,
bypassing hot gas around the waste heat boiler, oxygen enrichment or an acid gas enrichment unit.
Direct oxidation suits lean, hydrocarbon-free feed. Liquid redox can replace solvent, Claus and tail
gas units at small scale; scavengers take the smallest loads. Sub-dewpoint and selective oxidation
stages raise recovery without a full tail gas unit. With no sulfur market the acid gas may be
compressed and reinjected.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Is there a knockout drum ahead of the burner with a liquid removal route?
- Is there a reheater before each reactor and a condenser after each, with a seal leg on each
  rundown?
- Are liquid sulfur lines shown steam jacketed, sloped and free draining?
- Is the tail gas analyser located after the last condenser, with main and trim air valves?
- Does tail gas amine acid gas return to the Claus front end rather than vent?
- Do degassing offgas and the pit and tank vapour spaces have a defined sweep and destination?

A crash shutdown is hard on the unit because sulfur solidifies in the beds; ask how the unit is
cleared before shutdown. SO2 breakthrough into the tail gas amine degrades the solvent. Rising
reactor pressure drop can mean carbon deposits or a failed internal. Sulfur pits and tanks present two
different hazards that must not be confused: toxicity (H2S dangerous at parts per million, governing
for anyone near the pit) and flammability of the vapour space (a percent-by-volume limit). A design
below the flammable limit can still hold an atmosphere that is lethal to approach. Sweep rate,
detection and alarm levels are project safety requirements to be taken from the site's toxic gas
basis; they are not set points to read from this skill, and this skill does not certify them.

## Outputs and provenance

Unit line-up with the air-ratio strategy, the recovery target and how it is met, and open points.

## Required human judgment

Recovery target and tail gas route, shutdown and start-up procedure, pit and tank safety basis,
reinjection versus sulfur production.

## References

- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 13 (air ratio control). General method.
- Needs review before operational use: temperatures, recoveries, catalytic stage figures and
  sulfur handling temperatures were dropped (no section-level citation); unit line-up, variants
  and hazard statements retained as general descriptions. The H2S toxicity versus flammability
  distinction is a protective statement not tied to a cited section.
- `tech-gas-acid-gas-removal`, `tech-refining-hydrogen-and-sulfur`.
