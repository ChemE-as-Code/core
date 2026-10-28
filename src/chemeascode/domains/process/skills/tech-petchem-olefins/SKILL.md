---
name: tech-petchem-olefins
description: Process knowledge for ethylene and propylene by steam cracking - furnaces and transfer line exchangers, quench, cracked gas compression and caustic wash, drying, the cold train and recycles, plus on-purpose propylene routes. Use when drafting or reviewing a steam cracker flowsheet.
---

# Olefins by steam cracking

## Purpose and when to use

Reached from `tech-petrochemicals`. A steam cracker turns ethane, LPG, naphtha or gas oil into ethylene, propylene, butadiene, hydrogen and aromatic
liquids, returning unconverted feed to the furnaces. Cracking is a strongly endothermic free-radical process with dilution steam in a fired coil; coke
builds on the coil wall while it runs (Speight 2011, Ch 11).

## Required inputs and missing inputs

Feed slate, capacity, severity, product slate. The source gives different coil outlet temperatures and demethaniser pressures because feeds and recovery
schemes differ: keep both, do not average.

## Workflow and tools

Engineering guidance only; core has no calculation for this. Core's reaction library has `ethane_cracking` (molecular reactions, stoichiometry only; see
`reactions`). Units in flow order:

1. Feed treating where needed (mercury, arsenic, lead removal on condensate feeds; amine and caustic wash, oxygen/NOx hydrogenation and bed treatment on refinery offgas).
2. Convection preheat, dilution steam mixing and radiant coils; severity is set here.
3. Transfer line exchangers directly on the coil outlet raising very high pressure steam.
4. Direct oil quench and primary fractionator on liquid feeds, then quench water tower; quench water raises the dilution steam.
5. Cracked gas compressor, four or five stages with interstage cooling.
6. Caustic wash for CO2 and H2S before the last compression stage, then adsorbent dryers, both upstream of anything cold.
7. Chilling train and cold separation (demethaniser, deethaniser, C2 splitter, depropaniser, C3 splitter, debutaniser); the order is a main design variable.
8. Acetylene and diene hydrogenation, front end or back end.
9. Recycles: ethane and propane to furnaces; mixed C4 hydrogenated before recycle. Purges: fuel gas, hydrogen, fuel oil and heavy gasoline.

| Item | Source value |
|---|---|
| Coil outlet | 800 to 880 degC (1,500 to 1,600 degF) |
| Coil residence | 0.15 to 0.25 s liquid feed, 0.35 to 0.40 s gas |
| Compressor discharge | about 17 to 35 bar (250 to over 500 psig) |
| Tail gas chilling | to about -165 degC |
| Furnace run length | 50 to 70 days heavy feed, over 100 days ethane |

Control handles: coil outlet temperature and steam to hydrocarbon ratio set severity; quench oil and water circulation set heat recovery and dilution steam;
C2 and C3 splitters may run as heat pumps tied to the refrigeration cascade in some schemes, so pressure and refrigeration duty interact. Tower and compressor
controls are project information.

On-purpose propylene (different plants, not to be merged): paraffin dehydrogenation (cyclic fixed bed or moving bed), metathesis, olefin cracking, methanol to olefins,
high severity catalytic cracking sharing the recovery train. Catalytic distillation can treat several cuts in one tower.

## Validation and failure handling

Questions to put to the design:

- Is the transfer line exchanger directly on the furnace outlet with nothing uncooled between? Is dilution steam generated from the quench water circuit?
- Do the caustic wash and dryers precede the first cold item (acid gas would freeze and foul)? Are oxygen and NOx removed before the cold section (deposits can be explosive and plug)?
- Do ethane and propane recycle to furnaces, and does the C4 recycle pass hydrogenation first?
- Does each furnace have a decoke path and effluent destination? Decoking is a design case, not an upset.
- Do the cold columns have named light ends and purge destinations? Spent caustic needs its own destination.
- Does an offgas or condensate feed show its own treating chain?

## Outputs and provenance

Record feed slate, severity and recovery sequence choice in `DESIGN.md`.

## Required human judgment

Furnace and fired-heater safeguarding, cold-section hazards (oxygen/NOx deposits, hydrogen), compressor and relief design. This skill certifies none of them.

## References

- Speight, *Handbook of Industrial Hydrocarbon Processes* (Elsevier 2011), Ch 11.
- Independently verifiable general method: the unit order logic (treat, crack, quench, compress, wash, dry, chill, fractionate) and why acid gas and water precede the cold section.
- Needs review before operational use: all numbers, the heat-pump statement, the deposit-hazard statement (safety-critical).
