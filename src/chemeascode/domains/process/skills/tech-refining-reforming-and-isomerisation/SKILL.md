---
name: tech-refining-reforming-and-isomerisation
description: Reference for catalytic reforming and C5/C6 isomerisation. The reheat chain of heaters and reactors, recycle gas and hydrogen bleed, stabilisation, and the drying and chloride handling of isomerisation. Use when naphtha upgrading units are being discussed or reviewed.
---

# Reforming and isomerisation

## Purpose and when to use

Catalytic reforming raises the octane of heavy naphtha by making aromatics and isoparaffins and is
the refinery process that makes hydrogen as a by-product. Isomerisation branches the normal C5 and C6
of light naphtha so it can go to the gasoline pool. Reached from `tech-refining`.

## Required inputs and missing inputs

Naphtha cut and its sulfur, nitrogen, arsenic and lead content, target octane, hydrogen balance of the
refinery, and for isomerisation the olefin, water and oxygenate content of the feed. Ask for any that
is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Hydrogen yield and octane are not
computed by core.

Reforming (semi-regenerative): hydrotreated naphtha charge (pretreatment is not optional, since
sulfur, nitrogen, arsenic and lead poison the catalyst); feed joined with recycle gas through a
feed/effluent exchanger; a chain of fired heater and reactor pairs in series (three is typical),
because the dominant reactions are endothermic and each reactor outlet is colder than its inlet;
effluent cooling and separator drum; separator gas split between recycle compressor and a hydrogen
bleed, which holds loop pressure; debutaniser on the liquid, bottoms being reformate.

Isomerisation: charge pump and a pair of liquid driers, with its own make-up hydrogen compressor and
gas driers (water is the true poison); feed heater and a first reactor; interchange cooling and a
second reactor (equilibrium favours low temperature, so inlet temperature falls along the train);
organic chloride injection from a metering pump; stabiliser with reboiler, condenser and reflux
drum, its overhead through a caustic scrubber before the fuel system; no hydrogen recycle loop, which
is the clearest topological difference from a hydrotreater.

Variants: semi-regenerative reforming runs about a year before burning carbon off; cyclic reforming
adds a swing reactor; continuous catalyst regeneration moves catalyst through the reactors, allowing
higher severity at lower pressure. The sources describe the continuous variant only at that level, so
its catalyst transfer and regeneration hardware is project information. For isomerisation the choice is
once-through or recycle of unconverted normals; n-pentane boils between isopentane and the C6 isomers,
so that recycle is separated by molecular sieve rather than by distillation.

Control reported: each reforming heater outlet on its own temperature controller (severity and octane
follow from the set points together); recycle on hydrogen to feed ratio; separator pressure on the
bleed; debutaniser bottoms temperature on reformate vapour pressure; chloride on metered injection.

## Validation and failure handling

Questions for a flowsheet or P&ID:

- Does each reforming reactor have its own fired heater upstream, and does the feed come from a
  hydrotreater rather than from storage?
- Does the recycle loop close through a compressor, and does the hydrogen bleed have a named
  destination?
- Does an isomerisation unit show two driers on liquid feed and two on make-up hydrogen, the chloride
  injection point, a caustic scrubber on the stabiliser overhead, and cross-connected reactors?
- Do reformate and isomerate lines end at blending or storage?

Poison protection is upstream: the reformer has no in-unit defence against a poisoned bed. Water
shortens chlorided isomerisation catalyst life permanently. Olefinic naphtha from cracking units must
not reach an isomerisation reactor because it polymerises on the catalyst. This skill does not certify
any protection.

## Outputs and provenance

Line-up, hydrogen make as a quoted range with its source, and open points.

## Required human judgment

Severity and octane target, catalyst regeneration scheme, feed limits, hydrogen disposition.

## References

- Parkash, *Refining Processes Handbook*, Elsevier 2003, Ch 4 (worked reforming and isomerisation
  cases; isomerisation feed limits). Speight, *Handbook of Industrial Hydrocarbon Processes*, Elsevier
  2011, Ch 11 (net hydrogen quoted as 300-1200 scf per bbl, a wider band than the worked case: read
  as the design range). Figures are indicative; needs review before operational use.
- `tech-refining`, `tech-refining-hydroprocessing`.
