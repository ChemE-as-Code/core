---
name: tech-refining
description: Orient a petroleum refinery. How crude becomes products, which units a configuration (hydroskimming, conversion, deep conversion) implies, what each is for, and which member skill (tech-refining-*) holds the detail. Use when a refinery unit or configuration is being discussed.
---

# Refining (hub)

## Purpose and when to use

A refinery is a sequence of separations and conversions taking a crude of given quality to a product
slate of given specification. Its shape follows from the crude's weight and sourness, what the market
wants, and what fuel specifications demand (Parkash, *Refining Processes Handbook*, Elsevier 2003).
Use this hub to place a unit in its configuration, then go to the member skill.

## Required inputs and missing inputs

Crude assay (gravity, sulfur, metals), product slate and specifications, and the existing units if any.
Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. To record units as blocks and steps, use
skill `process-design`. Crude and petroleum fractions are pseudocomponents; check
`cheme process methods` for what core covers before relying on a simulation. A sourced naphtha
assay (TBP or D86 curve with its density, or its cuts) goes in `process/assays.yaml`;
`cheme process assay` characterises it into pseudocomponents, refuses an insufficient assay or
one outside the correlations' range (light ends, heavy fractions), and flashes it with
Peng-Robinson only inside its benchmarked claim (`docs/framework/assay.md`). DWSIM does not take
pseudocomponents.

The spine: desalting, atmospheric distillation, vacuum distillation, conversion of the heavy cuts,
treating of every product, blending, storage and shipping. Distillation separates what is already
there; conversion makes what is not, so conversion capacity distinguishes configurations:

- Hydroskimming: distillation, reforming and treating; suits a light sweet crude and leaves a large
  fuel oil surplus.
- Conversion: adds catalytic cracking or hydrocracking, turning gas oil into gasoline and distillate.
- Deep conversion: adds coking, visbreaking or resid hydrocracking so the vacuum residue is destroyed
  rather than sold.

The sourer and heavier the crude, the more hydrogen is needed and the larger the sulfur block. A
conversion unit brings a fractionator, a gas plant for its light ends, treating of its products,
hydrogen if it is a hydroprocessing unit, and sulfur recovery for the H2S that treating removes.
These are implications shared across units (usually one gas plant, one hydrogen system and one sulfur
block per refinery), so the question for a flowsheet is whether each duty has somewhere to go, not
whether each unit owns one.

| Skill | For |
|---|---|
| `tech-refining-crude-and-vacuum-distillation` | Desalting, atmospheric column, vacuum column |
| `tech-refining-hydroprocessing` | Hydrotreating and hydrocracking |
| `tech-refining-catalytic-cracking` | Fluid catalytic cracking and gas concentration |
| `tech-refining-reforming-and-isomerisation` | Catalytic reforming, C5/C6 isomerisation |
| `tech-refining-residue-upgrading` | Delayed coking, visbreaking, solvent deasphalting |
| `tech-refining-hydrogen-and-sulfur` | Steam reforming hydrogen, amine circuit, Claus |
| `tech-refining-treating-and-blending` | Sweetening, sour water, blending, tankage |

Utility and offsite systems, and relief and flare arrangements, have no core skill; they are project
information.

## Validation and failure handling

Refinery units are described in the literature at the level of purpose, conditions and yields.
Stream-by-stream topology and control detail vary by project, so give the line-up with confidence
but treat instrumentation as project information unless a cited source supports it.

## Outputs and provenance

A short configuration statement (which of the three), the implied hydrogen, gas plant and sulfur
duties, and open questions.

## Required human judgment

Configuration choice, conversion capacity, hydrogen and sulfur capacity, and all control and
protection decisions.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003: configuration logic. General method;
  needs review before operational use for any statement about a specific project.
- Member skills `tech-refining-*`; `process-design`.
