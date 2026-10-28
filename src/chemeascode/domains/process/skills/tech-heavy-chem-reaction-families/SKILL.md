---
name: tech-heavy-chem-reaction-families
description: Which reactor, separation and recycle arrangement a reaction type tends to imply - alkylation, dehydrogenation, esterification, hydrogenation, nitration, oxidation, polymerisation, sulfonation and the other general reaction families. Use when the process is unfamiliar and only the reaction type is known, before reaction data and route selection.
---

# Reaction families and the arrangements they imply

## Purpose and when to use

Reached from `tech-heavy-chemicals`. Eighteen reaction families cover most of what a general chemical plant
does. Recognising the reaction suggests a first topology (reactor, separation, recycle) before the specific
chemistry is settled. This is a starting sketch, not a design; reaction evidence and route choice belong to
`reaction-evidence-search`, `route-selection` and `reactions`. For a hydrocarbon-derived chain see also
`tech-petrochemicals`.

## Required inputs and missing inputs

The reaction type, phase behaviour, heat of reaction and whether it is equilibrium limited. If these are unknown,
ask the chemist; do not guess.

## Workflow and tools

Engineering guidance only; core has no calculation for this (core's `cheme process reactors` and
`reactor-choice` work on reactions you have written in `process/reactions.yaml`). Three questions settle most of
the topology:

- Exothermic and fast? Heat removal defines the reactor. Jacket area scales with the square of vessel size while
  heat release scales with the cube, so jackets give way to internal coils or an external circulating cooler at a
  scale set by heat-release rate, geometry and achievable coefficient, not by a fixed volume.
- Equilibrium limited? Something must leave as it forms: reactive column, product removal between beds, or an
  excess of one reagent.
- Low per-pass conversion? Expect a recycle with a purge or a by-product upgrading step.

Families (Speight, Part 1):

- Alkylation: acid catalysed, exothermic; contactor, acid/hydrocarbon separator, stripper and fractionation, acid
  recycle with regeneration slipstream.
- Amination: metal reduction in a stirred vessel with a bottom dump for sludge; the ammonia route a pressure
  reactor, ammonia recovery and purification, ammonia recycled.
- Condensation/addition (aluminium chloride): corrosive, aluminium-bearing residue; no flowsheet in the source.
- Dehydration: olefin or ether, usually vapour phase over alumina; selectivity is the problem.
- Dehydrogenation: endothermic, equilibrium limited; multistage reactor with interstage heating, condenser,
  fractionation, hydrogen overhead.
- Esterification: equilibrium limited; reactive column, wash on condensed overhead, alcohol recycle.
- Ethynylation and vinylation: chemistry only in the source; no arrangement to read off.
- Fermentation: propagation, fermenter, extraction, concentration, crystalliser; no reactor detail.
- Friedel-Crafts: feed dryness governs; drying on every feed, lined reactor, a route for acid sludge.
- Halogenation (chlorination): strongly exothermic; thermal then light-catalysed reactors, absorber, scrubber,
  stripper, dryer, one column per product; hydrogen chloride recovered or consumed by oxychlorination.
- Hydration/hydrolysis: direct hydration converts little per pass (large olefin recycle); indirect uses acid
  absorbers, hydrolyser and acid reconcentration.
- Hydroformylation: olefin plus synthesis gas, exothermic, homogeneous catalyst, catalyst recycled. Oxo adds
  catalyst conditioning and hydrogenation to alcohol.
- Hydrogenation: fixed bed where the feed has vapour pressure, stirred vessel for solids or heavy liquids; feed
  and effluent exchange; a sulfur guard ahead of a copper catalyst.
- Nitration: mixed acid; nitrator, separator, washer, distillation, spent acid reconcentration; cooling holds selectivity.
- Oxidation: partial oxidation is the aim, combustion the failure mode; liquid-phase air-blown needs an air
  distributor and external cooler; vapour phase concentrates heat in the catalyst zone.
- Polymerisation: exothermic, so heat removal is mandatory; the key question is whether polymer dissolves in
  its monomer (steep viscosity rise) or precipitates and must be kept suspended.
- Sulfonation: stops below a critical acid strength, so the water of reaction must leave (acid excess, azeotropic
  or reduced-pressure removal, or oleum fed into circulating acid); isomer separation follows.

Recurring shapes: reactor, separator, light-ends column, product column and heavy-ends draw with feed recycle;
reactor, absorber, stripper, column for a dilute gas product; mixed-acid reaction with acid reconcentration;
reactor, neutraliser, crystalliser, filter and dryer for a solid with mother liquors returned (Ray and Das, Ch 15).

## Validation and failure handling

The source omits valves and ancillary equipment by the author's statement, so loops, trips, isolation and relief
are project information. Check that a drawn arrangement answers the three questions above: heat removal, how the
equilibrium is shifted, and where unconverted feed and by-products go.

## Outputs and provenance

Record the reaction type, the arrangement chosen and why in `DESIGN.md`, citing the source; reaction data go into
`process/reactions.yaml` through `reactions`.

## Required human judgment

Reaction hazards (runaway, decomposition, toxic or corrosive reagents) and the choice among arrangements are the
engineer's. This skill certifies nothing about safety.

## References

- Speight, *Chemical Process and Design Handbook* (McGraw-Hill 2002), Part 1, Reaction Types.
- Ray and Das, *Process Equipment and Plant Design* (Elsevier 2020), Ch 15.
- Independently verifiable general method: the three screening questions and the heat-removal scaling argument.
- Needs review before operational use: the family-by-family arrangements (high-level, single-source).
