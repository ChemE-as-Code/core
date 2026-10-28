---
name: unit-ops-liquid-liquid-extraction
description: Liquid-liquid extraction - why solvent recovery belongs on the flowsheet from the start, the two-product recovery loop, contactor choice, which phase is dispersed and what interface position implies. Use when an extractor, mixer-settler or solvent recovery is designed or reviewed.
---

# Liquid-liquid extraction

## Purpose and when to use

Extraction is chosen when distillation cannot do the job economically: close relative volatility,
an azeotrope that will not break, a heat-sensitive product, a non-volatile metal ion, or a dilute
organic in an aqueous effluent (Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020,
Ch 13). Solvent recovery usually costs more than the extraction in capital and operation, so it
belongs on the flowsheet from the first sketch.

## Required inputs and missing inputs

Feed and solute, candidate solvent and its mutual solubility, liquid-liquid equilibrium data,
density difference, interfacial tension, number of stages needed. Core has no liquid-liquid
equilibrium for this; ask for data or state the gap.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Extraction can be represented as a
`component_separator` with specified recoveries (`separation-method-selection`, untested, no LLE);
`phase-calculation` can check whether a mixture splits into two liquid phases.

Loop: feed and solvent enter; two streams leave, extract and raffinate, both needing solvent
recovery (normally distillation); recovered solvent plus make-up returns. The minimum flowsheet is
one extractor and two recovery columns.

Contactor (indicative bands that overlap; a cost and plot decision where two serve):

| Service | Contactor |
|---|---|
| Easy phase separation, up to about 3 stages | Static column (spray, packed, sieve tray) |
| Easy separation, about 3 to 8 stages | Mixer-settler battery |
| Moderate difficulty, up to about 8 stages | Agitated column (reciprocating plate, rotating disc, pulsed) |
| Difficult phase separation, few stages | Centrifugal contactor |

Commercial equipment gives roughly one to eight theoretical countercurrent stages. Efficiency is
80 % and up for mixer-settlers, possibly under 30 % on sieve trays; disappointing efficiency is
usually incomplete settling, not poor mixing. Bubble caps are not used.

Dispersed phase: in sieve tray and packed towers the higher-flow phase is dispersed, in other
column types the lower-flow phase. An interface at the top means the light phase is dispersed; at
the bottom, the heavy phase, and the interface needs a level controller. The phase wetting the
internals should be continuous. Choice also follows density, viscosity, flow ratio, flooding and
materials; dispersing a flammable liquid reduces its holdup but raises interfacial area and
carryover, so it is a documented project decision. Where densities are close, centrifugal force
does the separating.

Practical points: a smaller immiscibility envelope needs more solvent, and it shrinks with
temperature; too-low interfacial tension gives a stable dispersion, worsened by dust and
surfactants; some towers hold the ends at different temperatures with a pump-back.

## Validation and failure handling

Questions for a design: recovery on only one product; no make-up solvent; no interface level
control; no coalescer or settler where phases separate slowly; no path for solvent degradation
products.

## Outputs and provenance

State the contactor, dispersed phase and recovery arrangement with sources. Record in `DESIGN.md`.

## Required human judgment

Solvent selection, dispersed phase, and handling of flammable or toxic solvents need a person.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 13.
- `separation-method-selection`, `phase-calculation`, `unit-ops-distillation`.
- Retained as general method: loop structure, interface logic.
- Needs review before operational use: contactor stage bands and efficiencies.
