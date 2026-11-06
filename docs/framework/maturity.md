# Calculation maturity and its evidence

`cheme maturity` evaluates a plant repository and says which **calculation maturity level** the
evidence in it supports, requirement by requirement. It is read-only (`--write` writes only
`checks/maturity.json`) and lives in `chemeascode.project.maturity`; the model basis of each
reactor and separator comes from `chemeascode.domains.process.model_basis`.

## Three axes, kept apart

Calculation maturity is one of the axes the [glossary](../concepts/glossary.md) defines: it is
neither the design maturity a process-library manifest claims (`process.yaml` `maturity`,
mapped [below](#mapping-onto-the-process-library-manifest)) nor the project stage of
`plant.yaml` ([stages and gates](../concepts/stages-and-gates.md)). The report keeps three
further views of the evidence apart:

| Axis | What it says | Who sets it | Where |
| --- | --- | --- | --- |
| Calculation maturity | how far the numbers are backed: sourced, balanced, predicted | evaluated from files | `levels`, `level` in the report |
| Artifact completeness | which deliverables exist (sheets, lists, datasheets, layout, estimate, LCA) | reported as found | `artifacts` |
| Independent review | who has checked the design | people only | the library manifest's `validation.status`, review records |

Artifacts never raise a calculation level: a PFD drawn from unbalanced numbers is still
unbalanced. Review is echoed (`review.manifest_status`, `review.records`) and never written or
inferred; gates passing is not a review.

## The four levels

A level is **reached** when every required requirement of it and of every level below it
passes. Each requirement has one status:

- `pass`: the evidence satisfies it;
- `fail`: the evidence is there and does not satisfy it;
- `missing`: an input file or a record is absent;
- `unsupported`: core cannot evaluate it today (no method or declaration exists). A required
  requirement that is unsupported blocks the level: what cannot be checked is not claimed.

Requirements marked *not required* are reported (and listed as limitations) but do not block.

### 1. `sourced`: sourced process description

| Requirement | Passes when |
| --- | --- |
| `sourced.flowsheet` | `process/flowsheet.yaml` (and `materials.yaml`) load without schema errors |
| `sourced.design-basis` | `process/design-basis.yaml` is valid and states a capacity, feeds and products |
| `sourced.boundary` | the flowsheet declares feeds and products, and every feed stream's flow and composition is `given` with a `source` in every case |

Schema validity alone (`sourced.flowsheet`) is necessary, never sufficient.

### 2. `balanced`: balanced conceptual PFD

| Requirement | Passes when |
| --- | --- |
| `balanced.process-rules` | no error-level `cheme.process-*` rule (units, ports, reactions, reactors) |
| `balanced.balances-evaluable` | every block and step balance (mass and components, or elements and reaction extents for a reactive one) can be evaluated in every case |
| `balanced.balances-closed` | every balance closes within the flowsheet's explicit `tolerance` (`abs` kg/h + `rel`); the evidence lists in, out, residual and tolerance per node and case |
| `balanced.model-basis` | every reactor and separator rests on a model whose data are given, or on specified values given with a source |
| `balanced.energy-closure` | *not required*: the flowsheet's energy balances per block and step (`domains/process/energy.py`: stream enthalpies against energy streams) close; reported as evidence, since a conceptual PFD may declare no duties |
| `balanced.furnace-energy` | *not required, listed only when `process/furnaces.yaml` exists*: every solid-reaction furnace has a calculated energy basis that closes (`domains/process/furnace.py`, [furnace energy basis](furnace.md)); `fail` on an error or an open closure, `unsupported` for a refused furnace (another reaction, data out of range, no Cantera), `missing` for the specific-energy fallback only. Its assumptions and what it does not claim (conversion, temperature profiles, grade) are listed as limitations. The degree of calcination is an input, so it never supports `predictive` |

### 3. `predictive`: converged predictive simulation

| Requirement | Passes when |
| --- | --- |
| `predictive.simulation-spec` | `process/simulation.yaml` translates into a simulator model for every case |
| `predictive.run-record` | `process/simulation-run.json` has a run for every case |
| `predictive.current` | each run's model fingerprint equals the one the inputs translate to now (changed files are listed) |
| `predictive.converged` | each run converged with no error finding (among them a conversion reactor short of or beyond its declared conversion, `cheme.process-sim-conversion-mismatch`) |
| `predictive.solver` | the simulator, its version, the property package and the core version are recorded |
| `predictive.coverage` | no step is excluded from the simulation (excluded steps keep specified values) |
| `predictive.balances` | the balances of the (simulated) flowsheet are evaluable and close: convergence alone is not physical validity |
| `predictive.model-basis` | every reactor and separator is predicted by a model inside the simulation; a specified split, conversion or stream values fail it |
| `predictive.property-package` | the supported-method contract (`simulation.translate.property_package_findings`, required selection): the worker runs the package and a recorded `method_selection` recommends it. An error or warning fails it, no recorded selection is `missing`, a recorded substitution passes and is listed as a limitation |
| `predictive.property-regime` | the property methods are used inside their declared regimes: the simulation's property package has a benchmarked range in `thermodynamics/methods.yml` (`methods[].simulation.application_range`, `methods.simulation_claim`) and every state DWSIM evaluated with it lies inside it (temperature, pressure, the components present): the feeds of each recorded case, from its translation (the record holds the simulated outlets only), and every material stream of the run records (energy streams carry no state). The run must be on the DWSIM version benchmarked, with DWSIM's own interaction parameters (a `simulation.yaml` `interaction_parameters` override fails it). A feed or stream outside fails it, naming the case, the stream and the state; so do another DWSIM version, a material stream row without a state or with a gauge pressure, a simulated outlet the record holds no row for, a claim limited to some phases (the record holds no phase, so it cannot be shown), and a case without a simulator model; no run, or a run record without any simulated stream state, is `missing`. Three packages claim a range. "Peng-Robinson (PR)": nitrogen, oxygen and argon, per component (N2 and O2: 65-320 K up to 2000 kPa(a) in every phase, subcooled liquid at 65-100 K up to 6000 kPa(a), gas at 170-320 K up to 10000 kPa(a); argon the same from 85 K, its subcooled-liquid box from 90 K; a mixture state must lie in a box of each component present), DWSIM 9.0.5 against CoolProp reference equations of state (`tests/test_process_simulate_property_package.py`); the claimed properties are phase equilibrium, enthalpy differences and the density of subcritical pure liquids. "Soave-Redlich-Kwong (SRK)": nitrogen, oxygen and argon each alone (`mixtures: false`; a state with two or more of them fails), in the same boxes and tolerances, for saturation temperature, enthalpy differences and subcritical liquid density (`tests/test_process_simulate_property_package_srk.py`): DWSIM 9.0.5's SRK has no interaction parameters for their pairs and every tested mixture but nitrogen-argon 90/10 misses the saturation-temperature or phase-composition tolerance. "NRTL": ethanol + water on one isobar, 101.3 kPa(a) as the data give it (101.25-101.35 kPa(a), 351.2-373.2 K), for the bubble temperature and the vapour in equilibrium (`tests/test_process_simulate_property_package_nrtl.py`, against two measured data sets with their expanded uncertainties, thermo's NRTL as a second implementation); it claims the `two-phase` phase only, so any NRTL plant fails the requirement on the phase its run record does not hold. On a pass the requirement lists what is not claimed (mixture liquid density, gas density) and the mixture states it concerns as limitations of the report. A package without a claim stays *unsupported*. The route's limitations (no electrolytes, pseudocomponents or solids; DWSIM's own interaction parameters) are listed |
| `predictive.stream-properties` | every stream with calculated properties (`state.calculated`) lies inside the benchmarked claim of the process's property package (`props.choose_package`, the per-stream coverage of `cheme process props --coverage`); the evidence names the package and its benchmark test and reference. No calculated properties: passes, nothing to check |
| `predictive.energy-closure` | the run record's energy audit (`energy`, `simulation/energy.py`) closes the plant: status `ok` within its tolerance passes, `imbalance` fails; `unsupported` or `not-evaluable` (a reactor without a heat-of-formation basis: its property package's enthalpy reference is not verified, only Peng-Robinson, PR78 and SRK are, or the run did not report DWSIM's formation enthalpies; or a unit whose duty sign is not established, such as a column top without condenser) is unsupported and blocks the level, with the audit's reasons. A component separator's imbalance (a specified split, enthalpy out minus in) is a stated residual of the plant closure: a plant that closes with it passes, and the detail names each stated value (ADR 0038); a run recorded before that change stays unsupported until it is simulated again. The heat-of-formation basis is verified live on vapour-phase reactors (ammonia synthesis) and on a liquid-phase conversion reactor (MTBE synthesis from isobutene and methanol, 298.15 K, 2000 kPa(a), `tests/test_process_simulate_energy_liquid.py`): a liquid's enthalpy is the package's departure from the ideal gas (DWSIM's pure liquids within 0.7 % of thermo's PR, PR78 and SRK departure functions), the liquid reactor's duty is reproduced (residual below 1e-11 kW, asserted 1e-2 kW) with each of the three, and the liquid reaction heat with Peng-Robinson, -33.1 kJ/mol (-65.5 as ideal gas), is within 2.0 % of a calorimetric value (-33.8 kJ/mol, Solà et al. 1994) and 7.0 % of one from liquid formation enthalpies (-35.6 kJ/mol, NIST WebBook); the tolerance is 10 %, what the spread of these values supports. A third published calorimetric value, -39.8 kJ/mol at 319 K (Arntz and Gottlieb 1985), is about 17 % away and not met: the published liquid values span about -33.8 to -39.8 kJ/mol and the simulation lies at the low-magnitude end. That accuracy is shown for this one reaction and Peng-Robinson only; the closure itself does not judge it. In DWSIM a liquid-phase reaction converts only the inlet's liquid phase: a reactor inlet the package splits (SRK splits this mixture at 298.15 K) reaches less than the declared conversion. simulate compares each conversion reactor's conversion from the stream flows with the declared one and records `cheme.process-sim-conversion-mismatch` (an error, so `predictive.converged` fails) when they differ by more than 0.001 (`simulation/conversion.py`, ADR 0030). A run recorded before the audit is `missing` |
| `predictive.exchangers` | no exchanger in the audit is `crossed` or `below-min-approach`, and no utility level is `infeasible` for its duty (physical-validity findings, not convergence) |
| `predictive.formation-data` | the reaction heat the simulator applies (DWSIM's database formation enthalpies) agrees, reactor by reactor, with the formation enthalpies declared in `process/materials.yaml` within the data tolerance, 1 % of the reaction heat and at least 0.1 kW, independent of the reactor's duty or mode (`cheme.process-sim-formation-data`; recomputed from the run's recorded DWSIM values and component changes against `materials.yaml` as it is now, since the declared values are not in the run's fingerprint). Declared values that differ beyond it fail; a smaller nonzero difference, chemicals' fallback values or a reacting component without a value pass with a recorded limitation; a reactor whose closure is unsupported is unsupported. No reactor: passes |

Electrolytes (ADR 0027): the simulation route has no electrolyte package. A
`simulation.yaml` whose compounds put a salt, acid or base of `electrolytes.yml` (listed, or any compound of an
alkali or alkaline-earth metal) together with
water does not translate (`cheme.process-sim-electrolyte`, error), so `predictive.simulation-spec`
fails instead of the electrolyte passing as a neutral molecule. The electrolyte route
(`cheme process electrolyte`: aqueous NaCl, Pitzer's equations, benchmarked range in
`electrolytes.yml`) is a point calculation of one liquid phase; it is evidence for a design
note or a specified split, and does not satisfy any `predictive.*` requirement.

Petroleum pseudocomponents (`process/assays.yaml`, [assays](assay.md)) do not count
towards `predictive`: the simulation route does not take them, so a flowsheet with a petroleum
fraction has no run to qualify. Their characterisation and flash are reported by `cheme process
assay` (refusals, the record's staleness, and per state whether it lies inside
`assay.FLASH_CLAIM`) and by `cheme process methods` (regime `petroleum_pseudocomponents`:
phase and simulation unsupported, assay limited).

### 4. `engineering`: preliminary/basic engineering package

| Requirement | Passes when |
| --- | --- |
| `engineering.equipment-list` | an equipment list without validation errors |
| `engineering.datasheets` | a valid, final datasheet for every equipment item (the `datasheets` gate) |
| `engineering.pid` | P&ID sheets without validation errors, every declared P&ID drawn: `missing` while no sheet file exists (none is drawn yet), `fail` when some are drawn and a declared one is not: planned, without a file or outside the repository (`cheme.sheet-planned`, `cheme.missing-sheet`, `cheme.sheet-outside-repo`, unless accepted) |
| `engineering.process-links` | every flowsheet link resolves against the lists and sheets; `missing` without `process/flowsheet.yaml` |
| `engineering.consistency` | *not required, unsupported*: datasheet duties and sizes are not cross-checked against the simulation |

Whatever passes, the report lists as limitations that mechanical design to a code, materials and
corrosion, relief sizing and control/dynamic behaviour are not checked.

## Model basis: specified versus predictive

Each reactor and separator (a step, or a block without steps; separators are `Separating`
classes with two or more material outlets; splitters are design decisions and not classified)
gets a basis. For a simulated separator it follows the translation's basis
(`translate.UNIT_BASIS`, a spec's `basis`, `basis_source`, `operating_basis`): `predictive` is
`equilibrium-stage`, `shortcut` is `shortcut`, `specified` is `component-split`.

| Basis | Predictive | Sourced when |
| --- | --- | --- |
| `kinetic` (`reactor: pfr`, a fixed bed, or `reactor: cstr` / `batch`, stirred tanks; inside the simulation only when every recorded run shows its `external-unit` coupling with a converged `outer_loop`) | yes | every rate law is `given` with a source (also after `cheme process propagate` has filled the outlet: a calculated outlet is not a specification) |
| `equilibrium` (`reactor: equilibrium` or `gibbs`; a Gibbs reactor's components are those of all its streams' compositions and templates, inlets and outlets) | yes | the components' ideal-gas data (or the equilibrium constants) are given; in a Gibbs reactor only the components in an independent reaction need them, an inert (in none, e.g. argon) is named in the detail and needs no formation data (without its heat capacity, its sensible heat is left out of the duty, ASSUMED); a component without the data it needs (or a Gibbs reactor with no component known) is reported as "no ideal-gas data" and not sourced, also before the outlet is calculated |
| `equilibrium-stage` (flash, rigorous column in the simulation) | yes | always (the simulator's property package) |
| `shortcut` (Fenske-Underwood-Gilliland column in the simulation) | yes | always |
| `conversion` (specified conversion per reaction, or a node's `selectivity:`: the key's conversion and the selectivities) | no | the reaction's `conversion` (the `selectivity:`, from its own `provenance` and `source`) is `given` with a source and the evidence does not contradict it, or the decided model basis of `process/reaction-evidence.yaml` covers it at the outlet temperature and pressure (below); a node-level `conversion:` has no provenance and counts as assumed |
| `electrochemical-cell` (a step a cell of `process/cells.yaml` links to: [electrochemical cells](electrochemical-cells.md), Faraday balance from a specified voltage and current efficiency) | no | the voltage, the Faradaic efficiency and every side reaction's current fraction are `given` with a source, and the cell is not refused |
| `component-split` (a unit whose translation basis is `specified`: a component separator) | no | its spec gives a non-empty `basis_source` (`operating_basis` is shown with it) |
| `solubility-equilibrium` (a `crystallizer:` with `basis: solubility`, solved by `cheme process propagate`: the mother liquor leaves saturated; never inside the simulation, so it fails `predictive.model-basis` as "not in the simulation") | yes | its solubility and its filter or centrifuge (`separation:`) are `given` with a source and, with solubility points, the temperature lies inside them |
| `imposed-yield` (a `crystallizer:` with `basis: yield`: the fraction of the solute that crystallizes, given) | no | its yield and its `separation:` are `given` with a source |
| `solid-split` (a `solid_separation:`: a filter or centrifuge with given solid recovery and cake liquid) | no | it is `given` with a source |
| `residual-moisture` (a `dryer:`: a batch (filter-)dryer or vacuum dryer to a given residual moisture, solved by `cheme process propagate`) | no | its `residual_moisture` is `given` with a source |
| `rayleigh` (a `still:`: a batch still or solvent swap, one equilibrium stage over the batch (ADR 0055), solved by `cheme process propagate`; never inside the simulation, so it fails `predictive.model-basis` as "not in the simulation") | yes | its volatility data are `given` with a source: the constant relative volatilities (`volatility: {model: constant, alpha}`), or with Raoult's law the `vapour_pressure` of every volatile component its inlets carry (neither `nonvolatile` nor a solid) |
| `batch-shortcut` (a `still:` with a `column:`: batch rectification on Diwekar's shortcut, Fenske-Underwood-Gilliland at each point of the batch (ADR 0061), solved by `cheme process propagate`; never inside the simulation) | yes | as `rayleigh`: its volatility data are `given` with a source |
| `adsorption-equilibrium` (a component separator whose recoveries follow from core's equilibrium TSA cycle in `process/adsorption.yaml`, below; never simulated) | yes | every input of the entry is given with a source |
| `external-performance` (a component separator whose recoveries follow from an external performance model in `process/adsorption.yaml`) | no | every input of the entry is given with a source |
| `stream-values` (outlet values as written) | no | every outlet flow and composition is `given` with a source |
| `undeclared` | no | never (an outlet value is missing) |

Specified bases count only as specified: sourced, they support `balanced`; they never support
`predictive`, however well the simulation converges.

**Adsorbers** (`domains/process/separations/adsorption.py`, `cheme process adsorption`, ADR
0024). An adsorber stays a `component_separator` in the simulation. `process/adsorption.yaml`
(schema `cheme/adsorption/v1`, optional) gives it a performance basis, one entry per separator:

- `technique: tsa`, `performance: calculated`: core's equilibrium TSA cycle. Each layer's key
  components are held to the stoichiometric time less half the measured mass transfer zone
  (from sourced isotherms at the feed state, competitive extended Langmuir or Sips within a
  layer, and the residual loading the purge leaves). The cyclic-steady-state balance gives the
  recoveries: the void gas and co-adsorbed carrier lost per cycle, and the product impurity in
  equilibrium with the residual loading. The regeneration heat is the sensible heat of
  adsorbent and vessel plus the heat of desorption. The hot purge must carry it with an ideal
  thermal front and carry the desorbed key components at their equilibrium partial pressure at
  the regeneration temperature. Above the isotherm's highest pressure only that pressure is
  used, a conservative bound. Heating, cooling and switching must fit in the other beds'
  adsorption time. The adsorbent inventory and its replacement rate (from `life`) are reported
  as a consumable outside the cycle. Every isotherm states the temperature and partial-pressure
  range it was measured over. An evaluation outside that range refuses the calculation
  (`cheme.adsorption-isotherm-range`).
- `performance: external`: an external model's recoveries, utilities and operating range. The
  feed must lie in that range (`cheme.adsorption-external-range`) and every feed component needs
  a recovery (`cheme.adsorption-external-closure`). The performance itself is not checked.
- `technique: psa` with `performance: calculated` is `cheme.adsorption-unsupported`: core has no
  PSA cycle model.

An entry *qualifies* when every case is inside the ranges, meets the product `specification`
(`cheme.adsorption-spec`) and regenerates (`cheme.adsorption-regeneration`). Its recoveries are
compared with the simulator's `recoveries` within `split_tolerance` (default 0.01;
`cheme.adsorption-split` when they differ). Only a qualified, sourced entry whose split agrees
changes the basis: to `adsorption-equilibrium` (predictive, never simulated, so
`predictive.model-basis` still fails with "not in the simulation") or to `external-performance`
(specified). Otherwise the basis stays `component-split`, with the reason listed as a
limitation. The calculation assumes local equilibrium, an isothermal adsorption step and a
uniformly heated bed. It does not model the thermal front, breakthrough dynamics or heat
losses. A component without an isotherm in a layer is treated as not adsorbed, so the key
components' capacity is then an upper bound. `process/adsorption.yaml` is one of the report's
fingerprinted inputs, and each entry carries a fingerprint of its inputs and feeds.

*Reference case* (`tests/test_adsorption_reference.py`): CO2 removal from dry air on 13X, the CO2
layer of an ASU front-end purification. The isotherm is the 3-site Langmuir fit of Grade 544 13X
in NASA/TM-2017-219847, measured at 0-200 °C and 0.001-108 kPa. The mass transfer zone is
198 mm at 400 ppm CO2, 25 °C, 7.9 bar(a) and 146 kmol/(m² h) (US 6,506,236 Example 1). The
case is qualified as follows:

- the isotherm reproduces the measured points within 3.5 % at the feed states (0-25 °C,
  0.08-1 kPa CO2; within 1.2 % above 0.2 kPa). At 150-200 °C it is within 12 %; there it only
  bounds the desorbing CO2;
- the cycle relations equal the hand calculation (`tests/test_adsorption.py`);
- a feed below 273.15 K and a regeneration above 473.15 K are refused.

The calculated breakthrough, recovery and regeneration duty are not compared with a measured TSA
cycle: no open dataset was found. N2 and O2 co-adsorption is not included, since the source
gives no N2 isotherm for Grade 544. Water is removed upstream on alumina and stays a sourced
split.

**Reaction evidence** (`domains/process/evidence_basis.py`, `evidence.model_support`). A
specified conversion counts as sourced when `process/reaction-evidence.yaml` (schema
`cheme/reaction-evidence/v1`) has a `model_basis` on a route with `status: selected` that
names the reaction (for a `selectivity:`, every reaction of the step), and the basis's cited
observations on that route cover the value at the reactor's outlet temperature and pressure.
Only temperature and pressure are compared: residence or contact time, space velocity, feed
composition and ratios, catalyst loading, phase and solvent are not, and every verdict
(supported or contradicted) lists them as not compared. `process/reaction-evidence.yaml`
is one of the report's fingerprinted inputs.

- no `cheme.evidence-*` error may be on the model basis or a route (two routes selected, the
  basis on a route not selected, ...): the decision is not made, nothing is supported. The
  errors are listed in `balanced.model-basis`'s `reaction_evidence_errors`;
- an observation counts only when its source was read in `full-text` (not `abstract`,
  `snippet` or `unavailable`) and its id is declared once, no error names the observation or
  its source (a missing location, a snippet's values, a fraction out of range, a malformed
  DOI or patent number, a duplicated id, ...), it states its catalyst (`catalyst`, else
  `catalyst_formulation`; a non-catalytic reaction says so in the formulation; neither: left
  out, "catalyst not stated") and, when the basis names a `catalyst`, it is that one (the same
  id, or a formulation equal to the id or to its `name` in `process/catalysts.yaml`; when the
  basis names none and the step declares `catalyst:`, the step's catalyst likewise; a basis
  catalyst other than the step's: not supported, "evidence on X, reactor holds Y"), its
  value is `reported` or `derived` (not `assumed`) in a fraction unit, and it is labelled: a
  conversion `basis: per-pass` (an unstated basis, `overall` or `equilibrium` does not
  count), a selectivity `basis: molar` with `relative_to` the key. The others are listed as
  left out, with the reason;
- the conditions compared are the reactor's outlet temperatures and pressures in the
  flowsheet's cases. A case without an outlet temperature makes the value **not sourced**: it is used in
  every case and is a claim at the reactor's conditions. An observation counts only when it
  reports a temperature whose range (with its `uncertainty`; a single value covers only
  itself) holds every operating temperature, and, where both give a pressure, likewise for
  the pressure. A pressure either side does not give is listed as not compared;
- the value lies within the range those observations span (each one's value or range,
  widened by its `uncertainty`): no extrapolation in value, temperature or pressure. An
  observation at another temperature never widens it, and observations on different
  catalysts (grouped by their own id or formulation) are not pooled: one catalyst's
  observations must cover the value;
- the step's `selectivity:` gives kmol of product per kmol of key converted; it is divided by
  the product's over the key's coefficient in the step's reactions that form it from the key
  (A -> 2 B: 1.8 is the molar selectivity 0.9). A product formed from the key by none of
  them, or by several in different ratios, is not compared;
- a `conflicts:` entry naming a cited observation of that value means it is not sourced,
  whatever its `resolution` says: cite only the evidence the model keeps;
- a reaction whose key another reaction of the step also consumes (under any key) is not
  compared with an observed (total) conversion: give the step a `selectivity:`.

The unit's `evidence` (and `balanced.model-basis`'s `reaction_evidence`) lists per value the
observations (`id (source, location)`), sources, catalyst, observed range and conditions, or
the reasons it does not stand; a reason is also in the detail and the unit's limitations.

A value's own source: a reaction's `conversion` `given` with a source, or a step's
`selectivity:` `given` with a source (judged on the spec itself, never on the reactions'
unused conversions; a step with `selectivity:` is a `conversion` basis with or without
`reactor: conversion`). Evidence that **contradicts** it (nothing else blocks the comparison
and the usable observations, at the known outlet temperature, exclude the value) makes it not
sourced, its own source notwithstanding ("contradicted by the evidence"). Evidence that
cannot compare it (a route not selected, an error on the basis, a flagged conflict, an
unknown outlet temperature, no usable observation, a shared reactant, a ratio not compared,
...) is never a contradiction, whatever range the observations show; it leaves the own source
standing, with the reason as a limitation ("own source kept, not supported by the
evidence"). The basis stays `conversion`: specified, never predictive.

A **fixed bed** (`kinetic`) also reports its model assumptions (steady state, ideal gas,
pseudo-homogeneous, rate laws as effective particle rates, plug flow) and its limitations: an
omitted pressure drop when the catalyst's particle diameter or voidage, the bed's diameter or
the gas viscosity is missing, and, unless the run record shows a converged external-unit
coupling for it, that it is not part of a converged simulation (solved by `cheme process
propagate` on its own, or a coupling that did not converge). With that coupling it counts as a
kinetic reactor predicted inside the simulation; its rate law still needs a source and its
assumptions stay listed.

A **stirred tank or batch** (`kinetic`, `reactor: cstr` / `batch`) reports its own assumptions
(`stirred_tank.ASSUMPTIONS`: ideally mixed, rate laws as effective rates, one phase; a CSTR at
steady state, a batch without charging or emptying time), "no tank declared" / "no batch
declared" when its `tank:` or `batch:` is missing, and the same simulation limitation as the
fixed bed. A kinetic reactor without reactions is not sourced ("no reactions").

A **liquid-liquid extractor** stays a `component-split` in the flowsheet and the simulation (a
component separator with given recoveries): the equilibrium stages of `process/extraction.yaml`
(`cheme process extract`, ADR 0019) are solved by core outside the simulation, so
they are evidence for the separator's `basis_source` (cite the unit's `split_to_extract`), not
a predictive unit of the simulated plant. The extraction result carries its own
`qualification`: `qualified` only for a bundled LLE system with a benchmark, inside the
benchmarked temperature and solute fractions; with parameters from the plant file it is a
predictive calculation, `unqualified`. Solvent regeneration is a separate unit.

## Reaction library entries

Every entry of the bundled reaction library carries a `model_basis` (`stoichiometry_only`,
`conversion_selectivity`, `equilibrium`, `kinetic`), validated against the entry's data by
`reaction_library.py`: `equilibrium` needs every reaction reversible, in the gas phase, with an
equilibrium constant or ideal-gas data over the whole window; `kinetic` a rate law per reaction;
`conversion_selectivity` a conversion per reaction (`provenance: given` only when each is sourced).
Today 8 entries are `equilibrium` (an ideal-gas equilibrium limit) and 15 `stoichiometry_only`.
The 23 entries are chemistry seeds, not 23 plant benchmarks.

## Mapping onto the process-library manifest

The library manifest (`process.yaml`, schema `cheme-as-code/process/v1`) keeps its own fields;
its `maturity` is the **design maturity** claimed for the process. The report maps the
calculation maturity onto it rather than competing:

| Calculation maturity reached | Highest design maturity (manifest `maturity`) it supports |
| --- | --- |
| none | none |
| `sourced` | `concept` |
| `balanced` | `screening` |
| `predictive` | `screening` |
| `engineering` | `basic-engineering` |

`detail-engineering` and `operating-reference` are supported by no check here. The text output
ends with `calculation maturity: <level> (design maturity claimed: <claim>)` and the design
maturity the evidence supports. When a
`process.yaml` sits at the repository root, the report gives `manifest.claimed_maturity`,
`manifest.supported_maturity` and `manifest.claim_exceeds_evidence`, and a
`cheme.maturity-claim-exceeds` warning with the line of the claim. `validation.status` is echoed
as `review.manifest_status`; nothing writes it.

## Report format

`cheme maturity --json` (and `checks/maturity.json` with `--write`) print schema
`cheme/maturity-report/v1`:

- `core_version`, `checked_at`, `source` (git commit, dirty inputs, sha256 of each input file);
- `level` (null or a level id: the calculation maturity), `level_index` (0-4), `library_maturity`
  (the highest design maturity it supports);
- `levels`: per level `id`, `title`, `library_maturity`, `status`, `reached` and its
  `requirements` (`id`, `title`, `status`, `required`, `rule`, `file`, `line`, `detail`, `hint`,
  `evidence`);
- `model_basis`: per reactor and separator `basis`, `predictive`, `sourced`, `simulated`,
  `sources`, `assumptions`, `limitations`, `file`, `line`;
- `cases`: each operating case with whether it balances and whether it translates for simulation;
- `assumptions`: the design basis's, the count of `assumed` values per file, the model
  assumptions per unit;
- `unresolved`: every required requirement that fails or is missing;
- `limitations`: unit limitations, unsupported requirements, engineering scope;
- `artifacts`, `review`, `manifest`: the other two axes and the manifest claim; `artifacts.boundary`
  is the boundary-completeness check (`assessment.flows.boundary_gaps`: unclassified terminals,
  duties without an energy stream), whose warnings are also limitations, never a level gate;
- `findings`: each requirement that does not pass as a finding (file, line, rule
  `cheme.maturity-<requirement>`, hint).

- `evaluated_through`: the highest level evaluated (`engineering` for the command); a level above
  it has status `not-evaluated` and no requirements, and a manifest claim only a higher level
  could support has `claim_exceeds_evidence: null` (undecided).

`--require LEVEL` exits 1 below that level, for CI.

## As a gate: `kind: maturity`

A check in `checks/checks.yaml` can gate a stage on the level:

```yaml
- id: maturity-balanced
  title: The conceptual PFD is sourced and balanced
  stage: basic
  kind: maturity
  require: [balanced]      # one of sourced, balanced, predictive, engineering
  max_claim: true          # optional: also fail when process.yaml claims more than the evidence
```

It fails when the computed level is below `require`; the detail names the first failing
requirements (file, line, rule `cheme.maturity-<requirement>`, status, hint) and the gate's
`evidence` (in `checks/status.json` at a sign-off) lists all of them under `failing`, with
`level`, `library_maturity` and `evaluated_through`. With `max_claim: true` it also fails on
`cheme.maturity-claim-exceeds` (detail `process.yaml:<line>: rule message (hint)`, the same under `evidence.claim`); a gate with only `max_claim` checks the claim alone. A passing
gate is evidence of the level, not a review: the gate never sets `validation.status`.

**Cost.** The gate evaluates only the levels it needs (`maturity_report(root, through=...)`):
the level in `require`, or the lowest level that could support the `process.yaml` claim if that
is higher. Only the `engineering` level runs the whole-repository `cheme validate` (every P&ID
loaded with pyDEXPI; some 30 s on a plant like ASU-1), and it reuses the validation the
`cheme check` run already shares between its gates, so it runs at most once per run.

`chemeascode.project.maturity.maturity_payload(root, through=None)` returns the same report as
JSON-ready data for read-only callers: it writes nothing, `checked_at` is only in the returned
data, and without `through` it runs the full evaluation once per call. `cheme serve` answers
`GET /api/maturity?through=` with it for the working tree, evaluated on every request and one
request at a time, so a viewer asking without `through` waits for the whole-repository
validation (some 30 s on ASU-1); `through=predictive` or lower skips it. `cheme export-static`
stores the full answer in a working-tree snapshot without `--exclude` only (it quotes evidence
from across the repository), with `checked_at` null so the snapshot stays deterministic, and so
runs the validation a second time after `validate`.
