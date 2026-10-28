---
name: tech-gas-acid-gas-removal
description: Reference for acid gas removal in a gas plant. The amine absorber and regenerator loop, physical and hybrid solvents, membranes and scavengers, what selects between them, and the usual failure modes. Use when H2S or CO2 removal from natural gas is being discussed or reviewed.
---

# Acid gas removal

## Purpose and when to use

Takes H2S and CO2 (and, where the solvent allows, COS and mercaptans) out of feed gas and
concentrates them in one stream for sulfur recovery or reinjection. Reached from
`tech-gas-processing`. The chemical solvent loop is the reference arrangement; the other routes
differ from it in structure.

## Required inputs and missing inputs

Feed H2S and CO2 content and pressure (hence acid gas partial pressure), the treated gas
specification and the coldest downstream step, whether COS or mercaptans must come out,
hydrocarbon content, and the destination of the acid gas. Ask for any that is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Absorber and regenerator duties
need a rigorous simulation with a suitable property method (see
`thermodynamic-model-selection` and `process-simulation`; whether the solvent chemistry is
supported is a question for the method contract, `cheme process methods`).

Units of the chemical solvent loop, in flow order: inlet filter separator (with a coalescer for
lube oil or aerosol); feed cooler; absorber with a water wash, mist eliminator and knockout drum;
rich solvent letdown to a flash drum that skims hydrocarbon and releases flash gas; lean/rich
exchanger; regenerator with reboiler, condenser and reflux drum (reflux water returns and also
scrubs solvent from the acid gas); lean cooler, a filter slipstream, surge tank and circulation
pump. A thermal reclaimer on a reboiler sidestream appears where the solvent forms irreversible
degradation products.

Selecting the route:

- Chemical solvents suit low acid gas partial pressure and deep removal and co-absorb little
  hydrocarbon. Primary amines are the most aggressive and corrosive; tertiary amines are selective
  for H2S and cheap to regenerate but slow on CO2 unless promoted.
- Physical solvent capacity follows acid gas partial pressure, which is why that family wins at
  high partial pressure (roughly 50 psi and above; Kohl and Nielsen, *Gas Purification*, 5th ed.,
  Gulf 1997, Ch 14). They regenerate largely by pressure flashing, dry the gas, and co-absorb
  hydrocarbon, which then needs a recycle compressor.
- Hybrid solvents blend both families for a high acid gas load with a tight specification.
- Membranes do bulk CO2 removal without moving parts but lose hydrocarbon to the permeate, need
  pretreatment and scale by module count. Scavenger beds in lead-lag pairs suit small loads.

Control handles reported for the amine loop (Mokhatab, Poe and Mak, *Handbook of Natural Gas
Transmission and Processing*, 3rd ed., Elsevier 2015, Ch 13): treated gas H2S/CO2 analysis as the
primary measurement, which for selective removal can reset a regenerator overhead temperature;
stripping held by ratioing reboiler heat to rich solvent flow; lean solvent held a few degrees above
the gas so hydrocarbon does not condense, using a bypass on the lean cooler.

## Validation and failure handling

Questions to put to a flowsheet or P&ID, which apply to the chemical solvent route only (a
membrane has no absorber loop, a physical solvent unit regenerates by flashing, a scavenger is a
once-through bed):

- Is there a water wash, mist eliminator and knockout drum on the absorber, and a hydrocarbon skim
  on the rich flash drum?
- Are filters on a lean slipstream, and does the lean cooler have temperature-difference control?
- Does the acid gas have a named destination, and is reflux water returned?
- Where the solvent degrades irreversibly, is there a reclaimer?

Failure modes the literature names: foaming (hydrocarbon entrainment, heat-stable salts), with
differential pressure on the columns as early warning; corrosion in the regenerator bottom, letdown
lines, rich side of the lean/rich exchanger and overhead; oxygen ingress, so storage is blanketed;
ammonia and cyanide from refinery feeds in the overhead. A scavenger bed regenerated with air can
ignite if oxygen is admitted fast. Thresholds for heat-stable salt purge, post-weld heat treatment
and similar measures belong to the project's materials and solvent supplier basis.

## Outputs and provenance

The route chosen with its basis (partial pressure, specification, hydrocarbon content), the open
points, and the statements below marked as needing review.

## Required human judgment

Solvent and route selection, materials and corrosion measures, reclaiming and purge philosophy,
and any scavenger regeneration procedure.

## References

- Kohl and Nielsen, *Gas Purification*, 5th ed., Gulf 1997, Ch 14 (physical solvent preference at
  high acid gas partial pressure). General method.
- Mokhatab, Poe and Mak, *Handbook of Natural Gas Transmission and Processing*, 3rd ed.,
  Elsevier 2015, Ch 13 (control of the amine loop). General method.
- Needs review before operational use: unit line-up details and failure modes (stated here as
  general descriptions without section-level support); typical operating figures were not carried
  over because they had no section-level citation.
- `tech-gas-processing`, `tech-gas-sulfur-recovery`, `tech-refining-hydrogen-and-sulfur`.
