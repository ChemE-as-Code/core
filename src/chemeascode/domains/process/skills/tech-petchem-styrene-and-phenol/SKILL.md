---
name: tech-petchem-styrene-and-phenol
description: Process knowledge for the two benzene alkylation chains - ethylbenzene and styrene by dehydrogenation, and cumene, phenol and acetone by peroxidation and cleavage - with recycles, inhibitor practice and hazard-bearing streams. Use when drafting or reviewing a styrene or phenol flowsheet.
---

# Styrene and phenol from benzene

## Purpose and when to use

Reached from `tech-petrochemicals`. Two chains start from benzene and a light olefin: ethylene to ethylbenzene and styrene; propylene to cumene and then phenol with acetone as
a fixed co-product. Alkylation is exothermic (heat recovered as steam between beds), ethylbenzene dehydrogenation endothermic (steam dilution, vacuum), cumene oxidation and cleavage exothermic
(Speight 2002, Part 2).

## Required inputs and missing inputs

Chain, capacity, alkylation technology (fixed bed or catalytic distillation), styrene reheat scheme. Controller sets on a drawing are project information.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Core's reaction library has `ethylbenzene`, `styrene` (equilibrium basis) and `cumene` entries (see `reactions`).

- Ethylbenzene: fresh and recycle benzene to a multi-bed alkylator with ethylene distributed between beds; a transalkylation reactor on recycled polyethylbenzene; benzene, ethylbenzene and polyethylbenzene columns.
- Styrene: ethylbenzene vaporised with superheated steam, multistage adiabatic reactors with reheat, waste heat train, hydrocarbon/water decanter, offgas compression with aromatics absorber, condensate stripping,
  benzene/toluene column, ethylbenzene/styrene splitter, finishing column.
- Cumene: fixed-bed alkylator, transalkylator, depropaniser, benzene, cumene and polyisopropylbenzene columns.
- Phenol: cumene oxidised with air in series oxidisers, oxidate concentrated (unreacted cumene returned), acid cleavage, neutralisation, fractionation to acetone, phenol and heavies; alpha-methylstyrene hydrogenated back
  to cumene; phenol cut extractively distilled.

| Item | Source value |
|---|---|
| Ethylbenzene | 0.265 t ethylene and 0.738 t benzene per t |
| Cumene | 0.35 t propylene and 0.65 t benzene per t, 99.7 % yield |
| Styrene | steam:ethylbenzene about 1.0 by weight; selectivity above 97 %; 60 to 70 % per pass |
| Phenol | 1.31 t cumene per t phenol, 0.616 t acetone co-produced |

Consumption figures are approximately consistent with stoichiometry (independently checkable). Control handles: ethylene split between beds with interbed steam generation; cooled effluent recycle on fixed-bed cumene,
boiling liquid in a reactive column; styrene steam ratio, inlet temperature and vacuum (conversion held below maximum because selectivity falls; steam supplies heat, suppresses coking, shifts equilibrium
and cleans the catalyst, Speight 2011, Ch 11); oxidation at low conversion and temperature to hold hydroperoxide selectivity.

Variants: fixed bed versus catalytic distillation alkylation (column route tolerates dilute ethylene, down to about 10 mol%); interstage reheat indirect, direct or oxidative; styrene recovery by extractive distillation of a pyrolysis gasoline C8 cut.

## Validation and failure handling

Questions to put to the design:

- Do benzene and the polyalkylbenzene stream have return paths? On a fixed-bed alkylator does olefin enter between beds with interbed steam generation or cooled effluent recycle? A catalytic distillation alkylator has
  neither: check reboiler and condenser duty against the exotherm.
- Styrene polymerises in hot columns: does every styrene-bearing column have inhibitor injection and run under vacuum? Scope this to styrene service only; upstream benzene and toluene recovery needs neither.
- Does the offgas pass an absorber and process condensate get stripped before steam raising?
- Cumene hydroperoxide is the hazard of the phenol unit: how are concentrated inventory, cleavage temperature and neutralisation handled? Does spent air and wastewater have a treatment destination?
- Does alpha-methylstyrene return to the oxidisers through hydrogenation?

## Outputs and provenance

Record alkylation technology, styrene reheat scheme, inhibitor basis and sources in `DESIGN.md`.

## Required human judgment

Hydroperoxide and runaway hazards, styrene polymerisation control, relief, vent treatment, technology choice. This skill certifies none of them.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 2; Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 11.
- Independently verifiable general method: stoichiometric consumption, recycle logic, inhibitor-plus-vacuum rationale.
- Needs review before operational use: conversions and steam ratios, hydroperoxide safeguards, catalytic distillation claims.
- Reference to a project or licensor basis in the source was removed; arrangement choices are a project decision.
