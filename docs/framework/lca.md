# LCA

`cheme assess lca` computes the life cycle assessment of a plant (ISO 14040/44) per
functional unit. It covers operation and construction, and can add prospective or sensitivity
scenarios.
- Code: `domains/assessment/lca/`, plus the Brightway adapter `integrations/brightway.py`.
- Template: `templates/project/lca/`.
- Skill: `lca`.

## Inputs

| file | kind | what |
|---|---|---|
| `process/flowsheet.yaml` | `process-flowsheet` | the feeds and products in one case. A material terminal is counted in kg/h (mass flow of its streams). An energy terminal (streams `kind: energy` with `duty`: electric power, steam, cooling water) is counted in kWh/h |
| `lca/lca.yaml` | `lca` | goal and scope, see below |
| `lca/factors.yaml` | `lca_factors` | backend `factors`: the project's characterised factors per unit of a flow (any unit of [Units](#units), e.g. kg, t, kWh, MJ, m3, Nm3, tkm), one value per impact category, each with status, source, year and licence |
| `estimate/mto.csv` | (generated) | construction: the take-off of the 3D model (`cheme assess mto --write`) |
| `equipment/equipment-list.yaml` | `equipment` | construction: `dimensions.weight` (t, empty) and `material` of each item |

### `lca/lca.yaml`

- `functional_unit`: an amount of one product of the flowsheet. A material product (counted in
  kg) may be per kg, g or t; per Nm3 or Sm3 (through its mean molar mass from the flowsheet's
  composition, ideal gas at the unit's reference state); per kWh, MWh, MJ or GJ (through its
  energy content, `allocation.properties.<product>.energy`, kJ/kg, e.g. the LHV: hydrogen per
  MJ LHV); or per item `ea` with `kg_per_unit` and its `source`. An energy product (electricity
  from CHP, exported steam, counted in kWh) is per kWh, MWh, MJ or GJ. A unit that cannot be
  converted is the error `cheme.lca-functional-unit`. Also `boundary` (cradle-to-gate or
  gate-to-gate) and `case`.
- `allocation`: how the burdens are shared between the co-products listed (`coproducts`). The
  inventory stays unallocated (see [LCI datasets](#lci-datasets)); allocation is the study's
  choice:
  - `mass`: by mass flow;
  - `economic`: by mass flow times price (`prices`, or `properties.<product>.price`);
  - `energy`: by mass flow times energy content (`properties.<product>.energy`, kJ/kg, e.g. LHV);
  - `exergy`: by exergy flow. A product's exergy comes from its streams' calculated `exergy`
    (`cheme process props --fill`), or `properties.<product>.exergy`;
  - `shares`: given fractions (`shares`, summing to 1);
  - `substitution` (system expansion): the functional unit's product carries everything, and each
    other co-product is credited with the production it avoids (`substitution: {product:
    background}`);
  - `none`: the functional unit's product carries everything.

  Every method whose data is complete is computed too, for comparison (`compare` narrows the
  list).
- `flows:`: the background of each operation flow. The key is `feed:<id>`, `product:<id>` or
  `emission:<component>`. Each entry gives one of the following:
  - `free: true`: no burden;
  - `emission: true`: the product is released to the environment, and its components become
    `emission:<component>` flows;
  - a background: `factor: <id>`, `activity: {database, name, reference_product, location}`,
    `biosphere: {database, name, categories}`, or `dataset: {path, product, allocation}`.
    `factor` serves the factors backend, `activity` and `biosphere` the Brightway backend. An
    entry may give a factor together with an activity or biosphere flow, so that either backend
    can run. `dataset` (an LCI dataset, below) serves both backends and excludes the others.
- `operation: {hours_per_year, life_years}` and `construction:`: the plant's materials, counted
  once and spread over the functional unit's product made in the plant's life.
  - `takeoff: mto` with a `category` and the `where:` filters of `estimate/rates.yaml` (item,
    DN range, class, spec, group) counts take-off rows.
  - `takeoff: equipment` with `equipment: {tag, type, material}` globs counts empty weights.
  - The first entry that matches a row or item counts it.
- What the flowsheet and the take-off do not hold, each an exchange of the dataset:
  - `consumables:` supplies of the operation, such as an adsorbent or catalyst replaced every few
    years, or a lubricant. Each gives `per_year`, or `per_replacement` with `every_years`, in
    its `unit` (plus an `initial_charge` spread over the plant's life), and has a background.
    A batch plant's per-batch use (cleaning solvent, rinse water, a nitrogen purge, the
    make-up of an off-spec share) gives `per_batch`: times the batches per year over the hours
    of `process/recipe.yaml`, the basis of the flowsheet's year averages (ADR 0053); without a
    recipe it is the error `cheme.lca-per-batch`.
    A catalyst says `catalyst: true` and its `metals: {Pt: 0.003}` (mass fractions).
    `disposal:` says what leaves the plant of it (see [Wastes, by-products and end of
    life](#wastes-by-products-and-end-of-life)).
  - `maintenance: {fraction_per_year, applies_to}`: spare parts as a yearly fraction of the
    construction entries matched by `applies_to` (globs on ids), with their backgrounds. These
    are the `maintenance:<id>` exchanges, phase `maintenance`.
  - `transport:` the mass of the exchanges matched by `applies_to` (globs on keys such as
    `construction:*` or `consumable:*`; inputs only) times `distance_km`, in t*km. The background is per
    `tkm` (Brightway: `ton kilometer`).
  - `end_of_life:` a `fraction` of the construction, maintenance or consumable mass (e.g. a
    spent adsorbent) matched by `applies_to` leaves as a material output `end-of-life:<id>`, per
    kg, phase `end-of-life`. `kind: waste | recyclable` and `route` classify it; the study's
    `system_model` decides whether a `credit` applies (see below). An entry without `kind`
    is read as before (its output linked to its background), with the info
    `cheme.lca-eol-kind`.
- `system_model: cutoff | apos | substitution | consequential` (default cutoff) and `cutoff:`,
  the flows left out by the cut-off criteria with their amounts (see below).
- `emission_estimates:` and `emission_exclusions:`: the emissions the flowsheet does not carry
  (combustion, equipment leaks, storage tanks, flares, effluent, non-routine operation), each
  with its method, scope and sourced factors, and the sources declared negligible (see
  [Emissions the flowsheet does not carry](#emissions-the-flowsheet-does-not-carry)).
- `backend: factors | brightway`, and `brightway: {project, categories: [{id, title, method}],
  biosphere}`.
- `uncertainty: {iterations, seed, defaults, factors}`: a Monte Carlo of the baseline (see
  [Uncertainty](#uncertainty)).
- `scenarios:`: each scenario replaces factor ids (`factors: {old: new}`, backend factors) or
  database names (`databases: {old: new}`, backend brightway). The results show the baseline and
  every scenario. A regional background scenario adds `location`, `year`, `electricity`,
  `missing:` and `proxy:` (flow key -> why), and a design-case scenario names its computed
  flowsheet `case:`; `cheme assess lca-scenarios` writes one record per scenario
  (`lca/scenarios/<id>.json`). See [design cases and regional LCI scenarios](lci-scenarios.md).

## Wastes, by-products and end of life

Outputs that are neither a product nor an emission (spent catalysts and adsorbents, waste oil,
sludges, off-spec product, scrap) are material outputs of the dataset with a `treatment`,
classified after ecoinvent's logic (by-product or waste by economic value):

| kind | what | `cutoff`, `apos` | `substitution`, `consequential` |
|---|---|---|---|
| `waste` | sent to a treatment the producer pays for, incineration with energy recovery included | linked to its treatment | linked to its treatment, plus its `credit` if given (e.g. the heat or electricity displaced) |
| `recyclable` | material for recycling or re-use, with a positive market value or an accepted scrap grade | free: the recycler carries the treatment, no credit | linked to its recycling background, plus its `credit` |
| `byproduct` | a by-product below 1 % of the output mass that carries no burden | free, with the warning `cheme.lca-byproduct-free` | as a recyclable |

An ordinary by-product with value (exported steam, a fuel, a valuable material) is a co-product,
not a cut-off flow: ecoinvent cut-off allocates "ordinary by-products" among the products and cuts
off only the by-products of waste treatment and recyclables. List it in `allocation.coproducts`.
A `byproduct` output left burden-free under a non-crediting model is the warning
`cheme.lca-byproduct-free` (failing the `cutoff-criteria` gate); keep the kind only for a flow
below 1 % of the output mass, and say why (ASSUMED negligible).

**Decision (deviation from the coordinator brief, 2026-10-25, to be confirmed):** the brief and
process-library `docs/system-model.md` section 3 say that waste with energy recovery leaves the
producer's system burden-free. This framework follows ecoinvent cut-off instead: the incineration
burden stays with the waste producer and only the recovered heat comes burden-free. The brief
and the library page need the same correction, or this rule must be reversed deliberately.

Energy recovery is **not** `recyclable`. In ecoinvent's cut-off model the burden of the
incineration stays with the waste producer; only the recovered energy leaves burden-free
([system models](https://support.ecoinvent.org/system-models)). Give waste oil or spent solvent
that is burned as `kind: waste`, linked to its incineration. A `recyclable` whose route names
incineration or energy recovery is the warning `cheme.lca-recyclable-energy`. A `recyclable`
needs a positive market value or an accepted scrap grade. A hazardous one
(`hazardous: true`) counts its background (the recycler's or the hazardous waste treatment)
under every system model, cut-off included, as a waste does; with no background of its own it is
the warning `cheme.lca-hazardous-recyclable`. The burden of an incineration does not follow the
composition of the waste (Doka 2003): that is not implemented, a known limitation.

The treatment background is the exchange's own (`factor`, `activity` or `dataset`, e.g. landfill
of spent zeolite, incineration of waste mineral oil, wastewater treatment, or an Atlas utility
dataset). Sign convention: every output and every treatment is a positive amount; a credit is
never hidden in a background with a negative impact. It is an `avoided:<key>` input of
**negative** amount, linked to the background of the displaced product (`credit`) and scaled by
`ratio` (units displaced per unit of output), written only under a crediting system model. Any
kind may carry a `credit`, so a substitution variant can credit the heat or electricity an
incineration displaces; under cutoff and apos it is recorded and not applied. A
cut-off dataset therefore holds no avoided-burden credits: the schema refuses `avoided:`
exchanges unless `system_model` is substitution or consequential. Under `apos`, recyclable and
by-product outputs are treated as under `cutoff` (the share of upstream burdens APOS gives them
is not modelled; info `cheme.lca-system-model`).

Where the outputs come from:
- a product of the flowsheet: `flows: [{key: product:<id>, <background or free>, treatment:
  {kind, route, credit, ratio}}]`;
- a consumable or a construction material: `disposal: {kind: waste | recyclable, route,
  fraction, <treatment background>, credit, ratio}`. The engine writes
  `disposal:consumable.<id>` (phase operation), `disposal:construction.<id>` (end of life) and
  `disposal:maintenance.<id>` (the replaced spares), in kg, so that what goes in also comes
  out. A spent catalyst keeps the `metals` of its consumable. A `recyclable` without a
  background leaves burden-free. A `fraction` below 1 sends only that share of the mass to
  the disposal; the remainder is assumed retained or used up (info
  `cheme.lca-disposal-fraction`);
- `end_of_life:` entries with `kind`, as above. A source that has a `disposal:` is not matched
  again by an `end_of_life:` entry: the match is skipped with the warning `cheme.lca-eol-double`
  naming both, so that a mass is not disposed or credited twice.

A consumable that is replaced or charged (`every_years`, `initial_charge`) without a disposal is
the warning `cheme.lca-disposal`; one bought per year (possibly used up) the info.
`disposal: {route, cutoff: "<why>", source}` records the disposal as cut off instead.

The study's `system_model` is copied into the dataset only when stated (unset, the study is
computed under cutoff). The findings `cheme.lca-system-model` (allocation by substitution in a
non-crediting study), `cheme.lca-cutoff-credit` (an end-of-life or recyclable output with a
negative impact in a non-crediting study, or a negative input in the plant's own cut-off
dataset; for a loaded background dataset that states no system model, an info only) and
`cheme.lca-system-model-mixed` (background datasets of another system model) guard against
mixing system models.

### Cut-off flows

The dataset records every flow it leaves out in `cutoff:` (`key`, `title`, `direction`,
`amount` in the dataset's basis, `unit`, `reason`, `cas`, `catalyst`, `contains`, `source`), so
that the criteria can be checked where the dataset is made and where it is used. Entries come
from the study's `cutoff:` list (`{id, direction, unit, per_year, reason, cas, catalyst,
contains, source}`, keys `cutoff:<id>`), from construction entries with `cutoff:` (with the amount
they match) and from disposals with `cutoff:`. `lca.cutoff.findings` checks the Atlas criteria. ISO 14044 4.2.3.3 names the types of cut-off
criteria (mass, energy, environmental significance) but no number: the 1 % for each flow and
the 1 % for the sum are an Atlas choice (process-library `docs/system-model.md`).

- a cut flow is below 1 % of the process's input mass (`cheme.lca-cutoff-share`), and all cut
  flows together are below 1 % (`cheme.lca-cutoff-sum`). The input mass is every operation input
  and resource counted in kg plus the cut inputs; cooling water is outside it, as the flowsheet
  counts it as a duty (kWh, carrier `cold`). The sum counts the cut outputs and the cut
  inputs alike against the input mass (ISO asks for similar criteria for outputs);
- never cut (`cheme.lca-cutoff-never`): any flow that names a precious or critical metal in
  `contains` or `metals` (a catalyst, an adsorbent or any other flow, whether or not it is
  marked `catalyst`; the platinum-group metals, Au, Ag, and catalyst-relevant critical raw
  materials such as Co, Ni, Cu, V, W and the rare earths; Au and Ag are precious metals, not
  critical raw materials), and flows with high characterisation factors (N2O, SF6, NF3, PFCs,
  HFCs, and heavy metals: Cd, Hg, Pb, As, Cr, Cu, Ni, Se, Zn). A consumable with `metals` is
  taken as a catalyst when its disposal is cut off;
- a cut flow without an amount in kg cannot be checked (info `cheme.lca-cutoff-unchecked`; it
  does not fail the gate).

The cut flows are listed as limitations in `results.md`. The gate requirement `cutoff-criteria`
fails on the warnings among these findings, a credit in a non-crediting model (allocation by
substitution in a non-crediting study included, `cheme.lca-system-model`), and a replaced
consumable without a disposal. Infos do not fail it.

**What a library build must regenerate.** A dataset written before these fields existed has no
`treatment`, `disposal:` outputs or `cutoff:` list. Its end-of-life outputs (without `kind`)
are read as before. To export a cut-off build without credits, a library regenerates each
dataset from its study after (1) adding `disposal:` to every replaced consumable (spent
adsorbent, waste oil, spent catalyst) and to the construction materials, (2) giving each
`end_of_life:` entry `kind` and `route` and moving any recycling credit to `credit:`, and (3)
recording its cut flows with amounts in `cutoff:`. The build then links a recyclable's credit
only for a substitution variant, from `treatment.credit` of the output, and checks `cutoff:`
with the rules above (the same fields and thresholds).

## Units

Every LCA amount, factor and functional unit is converted with one table,
`foundation.units.LCI_UNITS` (no second unit system), by quantity kind; the inventory counts each
kind in its base unit:

| kind | base | also |
|---|---|---|
| mass | kg | g, t |
| energy | kWh | MWh, MJ, GJ |
| length | m | km |
| area (land transformation) | m2 | |
| land occupation | m2*a | |
| volume | m3 | L |
| gas volume at a reference state | Nm3 (0 °C, 1.01325 bar) | Sm3 (15 °C, 1.01325 bar) |
| count | ea | |
| use of rented or shared equipment | ea*h | ea*a (8760 h) |
| transport | tkm | |
| radioactivity | kBq | |

A gas volume converts to kg through the molar mass (ideal gas, 22.414 m3/kmol at 0 °C and
1.01325 bar, CODATA 2018): `foundation.units.gas_volume_to_kg`.

**Energy carriers.** An energy exchange (kWh) carries `carrier: {kind, temperature, pressure,
level, lhv, composition, source}`: `electricity`, `heat`, `steam`, `fuel` or `cold`, with the
temperature (°C) of heat, steam or cold, the pressure (bar(a)) and level (LP, MP, HP) of steam,
and the LHV (MJ/kg) and composition of a fuel. `cheme assess lca` infers it from the flowsheet's
energy terminal (`category: utility`, `utility.kind`): electricity; steam; hot_oil and
fired_heat as heat; fuel; cooling_water, air_cooling and refrigerant as cold (heat rejected at
their level), with the utility's supply temperature, its `level` (e.g. LP, MP, HP) and, for
steam, its `pressure` (`utility: {kind: steam, level: MP, supply_temperature: ..., pressure:
...}`; bar(a), a gauge pressure read against 101.325 kPa). The pressure never sets the
temperature, and neither is guessed: a heat, steam or cold carrier without its temperature, or
steam without its pressure, is reported (info `cheme.lca-carrier-level`). An energy terminal
without a utility kind gets no carrier (info `cheme.lca-carrier`): the migration of v1's bare
kWh. An energy product's
exergy comes from its carrier: 3600 kJ/kWh for electricity, the Carnot factor `1 - T0/T` (cold:
`T0/T - 1`, T0 = 298.15 K) for heat, steam and cold at a stated temperature, so exported steam
can share burdens by exergy as a co-product. Linking converts kWh to a factor or activity per MJ
when the kinds match.

**Product state.** A material product's `state: {phase, pressure, temperature, purity, basis,
component, grade}` comes from its streams in the case (what every stream agrees on; gauge
pressures read against 101.325 kPa): GOX at 30 bar(g) and LOX are distinct reference products.
Exporters write it into the reference product's name or properties.

## Calculation

1. **Terminal flows.** Each is the sum of the streams reaching a feed or product (a stream from a
   feed straight to a product counts at both ends). Balances are not recomputed.
2. **The unallocated dataset.** The terminal flows, the emissions by component and the
   construction (its totals divided by `hours_per_year x life_years`) make the plant's LCI
   dataset, per hour of operation.
3. **Allocation share.** The share of the functional unit's product is its weight over the
   co-products' total (mass, mass x price, mass x energy content, exergy flow, a given share).
   One product carries everything whatever the method.
4. **Per functional unit.** Each flow is multiplied by
   `share x FU / product flow`. Co-products are listed with what is made alongside one
   functional unit.
   With substitution, each other co-product gives a credit row `substitution:<product>` of minus
   what is made alongside one functional unit.
5. **Impacts.** Each mapped row's quantity is multiplied by its background per unit:
   - **factors:** the factor's value in the category, converted to the row's unit;
   - **brightway:** the activity's score per unit of its reference product (bw2calc: the
     technosphere factorised once, solved per activity, per method; a treatment activity, whose
     reference product is produced -1, is solved for one unit treated), or the method's characterisation factor of the biosphere flow.

   The Brightway project is only read: cheme writes no foreground database into it.

   A row whose background is a dataset takes that dataset's product: one unit of it, allocated
   by the reference's `allocation` (default: the dataset's own, else mass), characterised with
   the same backend and scenario, recursively. A cycle is an error.

## Boundary check

The inventory holds only the flowsheet's terminals. What the flowsheet implies but does not
declare is not in it: a heater, cooler, compressor, pump, column or reactor with no energy
stream (its steam, cooling, refrigeration or power is in no exchange), or a product without
`category` (whether it is a product, wastewater, off-gas, solid waste or an emission is not
stated). The LCA runs the same check as the TEA and `cheme process energy`
(`assessment.flows.boundary_gaps`; rules and coverage in the TEA's [Boundary](tea.md#boundary))
and reports what it finds as findings `cheme.boundary-*`, after the LCA's own. It adds nothing
to the inventory and changes neither the totals nor the classification: `complete` stays
"within the declared boundary", and the check says what that boundary leaves out.
`process/simulation.yaml`, where a reactor is declared adiabatic, is one of the LCA's inputs.

The report's `boundary_check` (`--json`, `/api/lca`; `boundary` stays the study's statement from
`lca/lca.yaml`) has the TEA's `boundary` fields: `complete` (no warning *from these rules*, not a
complete inventory), `checked`, `noted`, `not_checked`, `categories`, `unassigned_duties` and
`gaps` (rule, level, ids, message, file, line). `lca/results.md` states gaps under its title and
has a section Boundary check: what was checked, noted and not checked, the utilities the
inventory excludes, the products without a category, and the gaps by rule. `--coverage` prints
one line `boundary check:` with the rules that warn and the steps whose utilities are in no
exchange.

## Direct emissions, resources and impact categories

A plant's own emissions (`emission:<component>`) can be mapped `elementary: {compartment,
subcompartment, origin}`, so they are characterised by the component's CAS number from
`process/materials.yaml`:
- `compartment`: `air`, `water`, `soil`, or `resource` (a flow taken from nature);
- `subcompartment`, after EF 3.1: air `unspecified`, `urban-close-to-ground`,
  `non-urban-high-stack`, `lower-stratosphere`; water `unspecified`, `fresh-surface`, `ground`,
  `sea`; soil `unspecified`, `agricultural`, `industrial`; resource `unspecified`, `in-air`,
  `in-water`, `in-ground`, `land`. An emission without one counts as `unspecified`, with the
  info `cheme.lca-subcompartment`: methods characterise particulates, NOx, NH3 or metals
  differently by release point;
- `origin`: `fossil`, `biogenic` or `land-use-change` (ISO 14067, EF 3.1);
- `flow`: the crosswalk id when CAS and compartment do not decide (a water source:
  `water-river`, `water-lake`, `water-sea`, `water-well`, `water-cooling`; land:
  `occupation-industrial-area`, ...).

**Resources.** A feed mapped `resource: true` (ambient air, river water) is taken from nature:
each of its components becomes a `resource:<component>` exchange (type `resource`, in kg),
mapped like an emission (`elementary: {compartment: resource, ...}`, `free`, or `missing`). A
hand-written dataset may also give resources in m3, m2 (transformation) or kWh, and land
occupation in m2*a. `cheme assess lca --coverage`, `--json` and `manifest.json` report the
dataset's water: `withdrawal` (water resources), `returned` (emitted to water), `evaporated`
(emitted to air) and `consumption` (withdrawal minus returned), in m3 per its basis (water in kg
at 1000 kg/m3). It counts the foreground's elementary flows only: water bought from a supply
(a technosphere input) and released to a river makes consumption negative. A water feed (one
whose main component by mass is water) taken free or unmapped, or a cooling-water duty mapped
free or unmapped, without any water resource flow is the warning `cheme.lca-water-resource`: the
withdrawal would be invisible. The moisture of an air intake is not a water withdrawal and is
not flagged.

**Identity.** Every emission and resource exchange of the dataset carries `flow:`, its identity
in reference lists, the primary list first: `{list: ef-3.1, uuid}` (the EF 3.1 reference package,
European Commission), then `{list: biosphere3, uuid, name, categories, unit, per_unit}` (the
ecoinvent elementary exchange list Brightway uses). They come from a small curated crosswalk,
`domains/assessment/lca/data/elementary-flows.yaml`, of the flows the packaged methods, examples
and tests use (CO2, CH4 and CO fossil, biogenic and from land-use change, CO2 in air, N2O, SF6,
N2, O2, Ar, water to air and water, water resources by source, NOx, SO2, NH3, PM2.5, NMVOC,
industrial land), with its sources and licence notes. CAS stays an attribute. The biosphere3
identifiers were read from the ecoinvent 3.9 elementary exchange list as distributed with bw2io.
**No EF 3.1 UUID is recorded yet**: none could be verified offline against the reference
package, so every EF 3.1 identity is `uuid: null` and reported (`cheme.lca-flow-uuid`, info); a
TODO of the crosswalk, never guessed. A flow the crosswalk does not hold has no identity
(`cheme.lca-flow-identity`, info). A free or unmapped emission has no identity: it states no
receiving compartment (a drain is water, a vent is air), so it is never guessed and
`cheme.lca-flow-identity` names it; map it with `elementary:` to identify it. A free or unmapped
resource is identified only where the crosswalk needs no origin (N2, O2, Ar, water), never
guessed for carbon. Exports (process-library#51) map by these identities, not by name.

Characterisation:
- **backend factors:** a category of `lca/factors.yaml` names a packaged method category
  (`elementary: ipcc2021-gwp100`). The emission is characterised in that category by the
  method's factor, next to the supply chain's factors.
  - Packaged now: IPCC 2021 (AR6) GWP100 and GWP20 for CO2 (fossil and land-use change 1,
    biogenic 0), CH4 (fossil 29.8, non-fossil 27.0), N2O and SF6
    (`domains/assessment/lca/data/methods.yaml`, with its source). A row holds for every
    sub-compartment; resources are outside the method.
  - An emission without a factor in the method is a gap (see below), with a warning. A
    substance the method characterises, but not for the emission's origin (methane from
    land-use change: no row until a source states its factor), is a real gap
    (`elementary-origin`) that `no-gaps` refuses, not outside the method.
- **backend brightway:** the biosphere flow of that CAS number in `brightway.biosphere`.
  - The flow whose code is the exchange's biosphere3 UUID (its `flow:` identity from the
    crosswalk) is taken first; CAS and name are the fallback for databases with other codes.
  - The sub-compartment given is preferred, else the compartment's unspecified one.
  - With `origin: biogenic`, a non-fossil flow is preferred; with `land-use-change`, one "from
    soil or biomass stock".
  - It is characterised by the project's methods, so every category the project has (all of
    EF 3.1 with ecoinvent) applies.

More impact categories:
- **factors:** add categories to `lca/factors.yaml` and values to the factors (any number of
  categories).
- **brightway:** add the project's methods to `brightway.categories` (for example the 16
  EF 3.1 categories).

## Emissions the flowsheet does not carry

A steady-state flowsheet gives the emissions of the streams that leave as `emission: true`
products. NOx from a fired heater, VOC leaking from valves and flanges, tank breathing losses,
the slip of a flare or the COD of an effluent are not in it. `emission_estimates:` in
`lca/lca.yaml` adds them. The engine (`domains/assessment/lca/emissions.py`) computes
each estimate per hour of operation and writes `emission:<substance>` exchanges into
`lca/dataset.yaml` with provenance **`estimated`**, the method, the estimate's id and every
factor's source in `source`, and `emission_estimates.<id>` (and the stream) in `streams`.

```yaml
emission_estimates:
  - id: leaks
    method: equipment-leaks
    stream: S-12               # speciates the total by its mass composition
    components: [C2H4, C2H6]   # the organics only (default: every component)
    service: gas               # gas, light-liquid, heavy-liquid
    factors:                   # kg/h per component, each from the study's source
      valve: {value: ..., unit: kg/h, source: "<document, table>"}
      flange: {value: ..., unit: kg/h, source: "<document, table>"}
    ldar: {valve: {value: ..., source: "<LDAR programme>"}}   # optional reduction
    elementary: {compartment: air, subcompartment: urban-close-to-ground}
    source: average-factor method, <document>
  - id: heater
    method: combustion
    equipment: [H-101]
    exchange: feed:FUEL        # or stream:, or activity: {value, unit, source} per hour
    lhv: {value: ..., unit: MJ/kg, source: "..."}   # a factor per GJ of a fuel in kg
    factors: {NOx: {value: ..., unit: g/GJ, source: "<guidebook table, permit or BAT-AEL>"}}
    cas: {NOx: <CAS>}          # a substance not in process/materials.yaml
    source: fuel x emission factor
emission_exclusions:
  - id: tanks
    method: storage-tank
    equipment: [T-*]
    reason: inert cryogenic liquid; the boil-off is returned to the process
```

| method | calculation (per hour of operation) |
|---|---|
| `combustion` | activity x factor per substance; activity a fuel exchange, a stream or `activity:`; `lhv` converts mass and energy |
| `equipment-leaks` | sum over component types of count x factor (`<mass>/h` per component) x (1 - `ldar`), x `hours_per_year` / operating hours, speciated by the stream's composition over `components` |
| `storage-tank` | `loss` (a fraction of the throughput) or `rate` (`kg/h`, `kg/a`, e.g. working and breathing losses after AP-42 ch. 7.1 calculated elsewhere), shared over `components` (the vapour lost: list the volatile ones) |
| `flare` | unburned slip (1 - `efficiency`) x the flow of each combustible in `components` (required; each by its own share of the gas, the inerts pass through), plus `factors` per gas flared (CO, NOx, soot) |
| `effluent` | concentration (`mg/L`, `g/m3`, `kg/t`, ...) after the declared `treatment` x water flow (`density` converts a mass flow) x (1 - `removal`) |
| `non-routine` | `fraction` of the estimates or `emission:<component>` keys it is `of` (start-up, shutdown, upsets), written apart as `emission:<substance>.non-routine` (phase `non-routine`) |

A factor's unit is `<kg|g|mg|t>/<basis>`; an activity that is not in the factor's basis is
converted within its quantity kind, or by `lhv` (MJ/kg; also GJ/t, kJ/kg, kJ/g, MJ/t, GJ/kg,
kWh/kg) or `density` (kg/m3; also g/L, kg/L, t/m3, g/cm3, g/mL); any other unit of them, and
anything else, is the error `cheme.lci-emission-estimate`, never a guess. `lhv` is the heating
value on the basis the factor's source uses: give the gross (higher) heating value when the
factors are per energy on a gross basis, and say so in its `source`. Every factor gives its `uncertainty` if
known (else the estimate's, else the study's default for `estimated`, else its pedigree).

**Component counts.** An equipment-leak estimate counts, by default (`count_from: [mto,
equipment]`), the valves, relief valves and flanges of the P&ID take-off (`estimate/mto.csv`,
from the DEXPI P&IDs; `where:` filters the rows as a rate does) and one seal per pump and per
compressor of the equipment list (`equipment:` filters the tags). The mapping is cheme's
convention (ASSUMED): a valve whose DEXPI class names safety or relief is a `relief-valve`; `counts:`
replaces a type's count (double seals, multi-stage machines). A counted type without a factor,
a missing take-off, an estimate that counts nothing and a component two leak estimates both
count (its leaks would be estimated twice; give each estimate its own `where:`, `equipment:`
or `count_from:`) are the warning `cheme.lci-emission-counts` (a gap, not 0).

**Simulated components are never overwritten.** A substance the flowsheet emits too is left
out with the warning `cheme.lci-emission-simulated`; `add: true` adds the estimate to it (a path
the flowsheet does not carry, such as leaks beside a vent) with the info
`cheme.lci-emission-added`, and the exchange keeps the weakest provenance of the two. A
`non-routine` estimate is a share only of what is written: of an estimate whose substances are
all left to the flowsheet, or of another non-routine estimate, nothing is counted, with the
warning `cheme.lci-emission-estimate`.

**Balances.** An estimated exchange is outside the flowsheet's mass balance: it carries
`balance_exclusion` (`estimated (emission_estimates <id>): ...`) and takes no part in the mass,
element and carbon balances (see [Mass, element and energy
balances](#mass-element-and-energy-balances)); a non-routine one is outside them by its phase.
An estimate `add:`ed to a simulated emission stays in them as part of that exchange, the
simulated amount plus the estimate (leaks beside a vent are small against its tolerance). The CO2 of a fuel belongs in the flowsheet
(the fuel feed and the flue gas), so that the carbon balance checks it.

**Identity.** An estimated emission is mapped like any emission: a `flows:` entry of its key
(a non-routine one falls back to its routine key's entry and identity), else the estimate's
`elementary:` (characterised by CAS: from `cas:` or `process/materials.yaml`). Without either it
is unmapped and unidentified (COD, total N have no CAS: map them to a factor).

**Factors and factor sets.** cheme-as-code packages **no emission factor**. The study supplies
each factor with its source (a guidebook table, an AP-42 section, the EPA leak protocol, a
permit, a BREF BAT-AEL, a measurement). A factor may instead name an entry of a packaged factor
set, `{set: <id>, id: <entry>}`: a set is a registry entry (`data/emission-factors/<id>.yaml`,
kind `emission_factors`: title, provider, `status`, `source` with version, licence, attribution
and redistribution, and the factors with their tables). The sets shipped, `epa-equipment-leaks`,
`epa-ap42` and `emep-eea-guidebook`, are **placeholders**: their values have not been read from
the source documents and their terms have not been checked (`todo` and `licence_note` say
what is open). A factor naming a placeholder refuses to run (`cheme.lci-emission-factor`,
error). A set becomes `verified` only with its source (`redistribution: true`) and factors
read from it.

**Completeness.** `cheme.lci-emissions-incomplete` (warning) names the emission sources with
neither an estimate nor a declared exclusion: equipment of a combustion class (`*Furnace*`,
`*Boiler*`, `*Burner*`, `*FiredHeater*`, `*GasTurbine*`, `*Incinerator*`, `*Oxidiser*`,
`*SteamGenerator*`, `*Reformer*`, `*ProcessHeater*`, `*Kiln*`, ...; covered by `combustion` or
`flare`; an unfired reformer, such as an adiabatic pre-reformer, is declared in
`emission_exclusions:` with that reason), a flare (`*Flare*`), a storage tank (`*Tank*`, `*Silo*`;
covered by `storage-tank`), a feed of utility kind `fuel` (covered by an estimate whose
`exchange` or `stream` is it) and a `wastewater` product that is not sent to a treatment
background (free, unmapped, or released as its components; covered by `effluent`). An
estimate covers a source by its `equipment` globs, `exchange` or `stream`;
`emission_exclusions:` declares a source negligible or out of scope with its `reason` (by
`equipment`, `exchange`, or every source of the method when neither is given). Exclusions are
recorded among the dataset's cut-off flows (`emission-excluded:<id>`, no amount) and listed as
limitations. The gate requirement `lci-emissions-complete` fails on the warning.

## Open data, sources and coverage

A study must be usable and publishable without a licensed database. Three layers stay apart:
the foreground (the plant's own unallocated dataset, `lca/dataset.yaml`), the background links
(`lca/lca.yaml` mappings and `lca/factors.yaml` or a local Brightway project) and the study's
results (`lca/results.*`, `gaps.csv`).

**Source registry.** Each factor names its entry in `sources:` (`source_id`): provider, exact
version, URL, licence or terms reference, attribution, geography, reference year,
characterisation method, a checksum of the file read, and the publication policy of results it
contributes to: `public`, `restricted` (private unless a reviewed project policy allows the
artifact) or `local` (never leaves the machine). `redistribution: true` says its numbers may be
bundled. The registry records terms; it neither interprets a licence nor grants rights, and free
access alone does not establish that results may be published. An LCI dataset has the same
`sources:` for exchanges whose amounts are externally supplied (`source_id` on the exchange),
and `rights` for its own data: a foreground label does not lift a source's restrictions.

**Packaged open profiles.** `include: [desnz-ghg-2026]` in `lca/factors.yaml` adds a profile of
`domains/assessment/lca/data/backgrounds/`, its factor ids prefixed (`desnz-ghg-2026:electricity-gb`).
`desnz-ghg-2026` is the UK Government GHG Conversion Factors for Company Reporting 2026 (DESNZ,
flat file v1.2), Open Government Licence v3.0 (publication and redistribution with the
attribution):

| factor | per | kg CO2e | what |
|---|---|---|---|
| `electricity-gb` | kWh | 0.18436 | UK grid at the consumer: generation, T&D, well-to-tank |
| `natural-gas-gb` | kWh (GCV) | 0.21252 | combustion and well-to-tank |
| `lorry-hgv-gb` | tkm | 0.12715 | average non-refrigerated HGV, average laden, with WTT |
| `water-supply-gb`, `water-treatment-gb` | m3 | 0.1913, 0.17088 | mains water, waste water treatment |
| `metals-construction`, `steel-cans`, `aluminium-cans-foil` | t | 3821.9, 2861.6, 9113.6 | primary production to the point of sale |
| `concrete`, `aggregates`, `insulation` | t | 118.80, 7.80, 1861.8 | primary production |

It is climate change only, UK, GWP100 of AR4/AR5 (DESNZ methodology Table 1), biogenic CO2
excluded; the material factors are not suitable for recycling credits (methodology 12.1). A
study elsewhere uses it as a proxy (`proxy:` on the mapping, which marks the contribution
PROXY) and reads the result as screening. Its electricity factor is at the consumer (T&D
losses and well-to-tank included), data year 2025 per the methodology (3.8: the 2026 set uses
2025 data), AR5 for its four rows (Table 1);
the factor's `year` field gives the publication year, which the sidecar
`data/background_scopes/desnz-ghg-2026.yaml` declares as `publication_year: 2026`. The sidecar
declares `data_year: 2025` for the electricity factors only; the other factors' data years are not
checked and stay undeclared ([lci-comparison-basis.md](lci-comparison-basis.md), decision 6).

**Grid electricity profiles**. Each one is generated from the publisher's file,
names the cell or line of every value, and records the file's checksum and terms. They differ
in scope, so read the table before you compare scenarios built on different ones:

| profile | geographies | scope | basis | terms |
|---|---|---|---|---|
| `desnz-ghg-2026` | GB | at the consumer: T&D losses and well-to-tank included | CO2e, AR5 (electricity rows), data 2025 | OGL-3.0 |
| `egrid-2023` | US and its 27 eGRID subregions (`electricity-us`, `electricity-us-erct`, location `US-ERCT`) | at generation, total output rate, direct plant emissions: no T&D losses (US 4.2 %), no upstream; generation mix of the area (no imports or exports) | CO2e (CO2, CH4, N2O), AR5, data 2023 | public domain in the US |
| `eea-ener038-2024` | EU-27 (`electricity-eu27`) and all 27 member states (`electricity-de`, `-nl`, `-fr`, ...) | gross generation, direct emissions only, biomass excluded, no upstream; own use, T&D and imports not counted | CO2e, UNFCCC inventories (AR5 inferred), data 2024, integers in g for countries | CC BY under the EEA legal notice: acknowledge the EEA in each copy |
| `ember-2025` | G20, EU-27 members and aggregate, NO, CH, world (`electricity-glo`) | gross generation, life cycle (upstream, supply chain, manufacturing), no T&D; 2025 partly projected, regions and world estimated | CO2e, modelled per technology, mixed GWP basis (upstream methane at 21) | CC-BY-4.0 |
| `uba-strommix-2026` | DE (`electricity-de-2023`, `-2024`, `-2025`) | direct CO2 only (no CH4, N2O, upstream) per kWh of net German electricity: territorial, generation-based, net of own use and line losses, trade balance not applied; 2024 preliminary, 2025 estimated (`ESTIMATE`, so results stay screening) | CO2, data 2023 to 2025 | UBA data terms (§12a EGovG): commercial reuse with UBA named and changes marked; not a CC licence |

- A factor at generation stands in for electricity at the consumer only as a proxy: say so in
  the mapping or the scenario (`proxy:`), and the result is screening.
- Do not mix direct-emission and life-cycle profiles in one comparison without saying so; the
  method-mix check (`cheme.lca-method-mix`) flags `ember-2025` next to the AR5 profiles. The
  check and each scenario's comparability verdict (`like-for-like`, `proxy`, `not comparable`)
  read the factors' structured `scope` (basis, delivery point, gases, GWP, mix, accounting), not
  the text above: see [comparison basis](lci-comparison-basis.md).
- An eGRID subregion code (`US-ERCT`) is no US state: a plant given as `US-TX` with a subregion
  factor is flagged as another geography. Give the plant's location as the subregion, or mark
  the factor a proxy.
- Umweltbundesamt (DE): only the three figures stated on UBA's summary page are packaged, under
  the website's data terms (§12a EGovG); the March 2026 report PDF, marked "all rights reserved",
  is not, until UBA Fachgebiet V 1.5 clarifies in writing that its tables (CO2e, with upstream)
  may be republished.
- Not packaged: CO2emissiefactoren.nl (no licence stated) and ADEME Base Carbone (open licence,
  but a four-year smoothed consumption factor that fits none of the profiles above).

More profiles join one at a time, each checked for its terms and scientific fit before it is
packaged.

**Status.** A factor is `PUBLISHED`, `EPD`, `ASSUMED`, `PROXY` (a published number for a
related flow) or `ESTIMATE` (derived by the project); a proxy and an estimate state their
`basis` and `validity`. A mapping's `proxy:` marks a published factor used for a related flow.

**Factor status per exchange.** Every exchange gets the weakest status of its
contributions over the categories, weakest first: `gap` (no burden in a category; an
elementary flow outside a method is none), `example` (`example: true` in `lca/factors.yaml`;
packaged characterisation methods are not affected), `ASSUMED`, `PROXY` (also a `proxy:`
mapping), `ESTIMATE`, `EPD`, `PUBLISHED` (also a packaged method's characterisation factor),
`database` (a Brightway activity or biosphere flow, which carries no status of its own) and
`none` (no burden by declaration: free, a co-product, outside every method). Inside a
referenced dataset the weakest status travels up. `--json` gives `factor_status` per scenario
and `factors_published`; `lca/manifest.json` gives the baseline's under `result`. A published
result rests on `PUBLISHED`, `EPD`, `database` or `none` only: `cheme assess lca --strict`
exits 1 otherwise, naming each exchange as the error `cheme.lca-factor-status`, and the gate
requirement `factors-published` fails the same way, over the baseline and every scenario. The
status says where a number comes from, not that it is right: a `database` or `PUBLISHED`
factor can still be the wrong background, which the review judges.
A mapping `missing: "<why>"` declares that no background is available (yet): the exchange
stays in the inventory with its quantity, counts as mapped (a decision was made) and is a gap
in every category. Never drop such an exchange or map it free.

**Outside a method.** An elementary flow (a direct emission, or a Brightway biosphere flow)
that a method does not list contributes nothing to that category by the method's definition:
it is reported ("Outside the methods" in results.md, `gaps.csv` with its reason) but is no gap.
A category may say `elementary: none` when the plant's direct emissions do not contribute to it
at all; unset, a direct emission there is a gap.

**Gaps, never zeros.** An exchange without a burden in a category is a gap: unmapped, declared
`missing`, a factor without that category, a direct emission the packaged method or the
Brightway method does not characterise, a category without an elementary method, or an
exchange of a referenced dataset that has no background (carried up with its quantity scaled to
the study, key `<flow> < <dataset>#<exchange>`). The construction adds gaps whose amount is
unknown: an equipment item without a weight (`no-weight:<entry>/<tag>`), a take-off row or item
no construction entry counts (`unmatched:<row or tag>`), and an entry whose take-off or
equipment list is absent (`no-takeoff:<entry>`). A construction entry `cutoff: "<why>"` leaves
what it matches out by the study's cut-off criteria (ISO 14044 4.2.3.3): no gap, listed as a
limitation. Gaps keep their quantity and unit, are excluded from the totals and listed in
`lca/gaps.csv`, `results.md` and the API (`gaps`). No coverage percentage is given: without a
bound there is no defensible denominator; read the quantities instead.

**Classification.** `results.md`, `--coverage` and the API give the result's class and reasons:
- `unavailable`: the LCA does not compute;
- `partial`: a gap in the baseline;
- `screening`: no gap, but example factors, a factor `ASSUMED`, `PROXY` or `ESTIMATE`, climate
  categories only, a factor of another geography than the study's `location`, more than 10
  years from its `year`, or a category whose contributions rest on different characterisation
  methods (`cheme.lca-geography`, `-reference-year`, `-method-mix`), or a geography or year
  that cannot be checked (no study `location` or `year`, a contribution without one: info
  `cheme.lca-unchecked`). Geographies compare as regions: GB and UK are one, a GB factor
  represents a GB-ENG site, GLO or RER represent none. Methods compare by their IPCC basis
  (AR4, AR5, AR6). A referenced dataset's inner statuses, geographies and years count too;
- `complete`: every exchange characterised in every category with published or declared data,
  within the declared boundary. Complete is not validated: the review judges the mapping and
  the data.

Climate categories alone are a screening carbon footprint, never a full LCA. What the boundary
leaves out (no construction, no end of life, no transport, gate-to-gate) is listed as a
limitation, not assumed absent.

**Foreground without a background.** `cheme assess lca --dataset` (or `--inventory`) alone
derives the unallocated foreground without `lca/factors.yaml`, a Brightway project or
credentials: what a public library publishes. `cheme validate` checks `lci_dataset` files the
same way. `--case <id>` (with `--dataset`, `--write` or `--check`) gives the dataset of another
computed flowsheet case. Its id, title and uuid name the case, and `--write` writes it to
`lca/datasets/<dataset id>-<case>.yaml`
([design case datasets](lci-scenarios.md#a-design-cases-own-dataset), ADR 0045).

## Publication and the run manifest

**Publication policy.** A result's policy is the most restrictive of the sources its
contributions draw on: the baseline, every scenario, the allocation comparison's substitution
credits, and the contributions inside referenced datasets:
- a registry entry's `publication`;
- packaged characterisation methods (IPCC): `public`;
- a Brightway database: its `expect` entry's `publication`, else `brightway.publication`,
  `restricted` by default; a database without `expect` (matched by name only) is never
  `public`, so an open database must be identified to be published;
- a factor without a registry entry: the factor file's `publication`, `restricted` by default
  (also inside a dataset: the marker travels up).

Results are publishable when the policy is `public`, or `restricted` with a reviewed decision
in `lca/lca.yaml` (`publication: {allow_restricted: true, review: reviews/<record>.md,
approved_by: <a person>}`). `local` is never published. A report existing, a public
foreground, or the repository's software licence is no such decision: third-party data keep
their own terms. `results.md`, `--coverage` and the API state the policy, which sources make it
so, and whether the results may be published (`--coverage` prints it); the gate requirement
`publishable` checks it.

`cheme export-static` follows the policy and fails closed. The `lca` answer stays only when it
computes where the snapshot is made and is publishable. The committed result files
(`lca/results.csv`, `results.md`, `gaps.csv`, `uncertainty.csv`) stay only when, in addition,
the committed `lca/manifest.json` says they are publishable: they may come from another run
(another backend, a licensed database). Excluding `lca/lca.yaml` or `lca/factors.yaml` (e.g.
`--exclude 'lca/**'`) withholds both. `manifest.json` lists what is withheld and why under
`withheld`. The foreground
(`lca/dataset.yaml`, `inventory.csv`) and the run manifest stay: they hold no background
scores. `cheme serve` is local and answers everything, with the policy in the answer.

**Run manifest.** `lca/manifest.json` records what the results rest on: the functional unit,
case, boundary and allocation; a sha256 of every input file and referenced dataset (line
endings normalised); `results`, the sha256 of the text of `results.csv` (a consumer hashes the
committed file with normalised line endings and compares: a mismatch means the results were
written by another run); a hash of the mappings (flows, construction, supplies, allocation); the
background (the included profiles' fingerprints and the sources' titles, providers, URLs,
versions, licences, attribution texts and checksums: what a consumer must show with the
numbers, or the Brightway project with each database's provider, version, system model and
size and a sha256 of each method's characterisation factors); the categories and methods; scenarios and Monte Carlo settings; the software
(major.minor); and the result's class and policy. It has no commit, time or absolute path, so
it changes only when what the results rest on changes: the gate's `lca-current` then fails
until the outputs are rewritten. The take-off and the equipment list are fingerprinted only
when the construction reads them. Recording the software is deliberate: a new cheme-as-code
(or bw2data) minor version asks for one `cheme assess lca --write`, as the calculation may
have changed.

**Brightway database identity.** `brightway.expect: {<database>: {provider, version,
system_model}}` is checked against the metadata the database records (`bd.databases[name]`);
a mismatch is an error (`cheme.lca-brightway-identity`). Without `expect`, the databases are
matched by name only, with the warning `cheme.lca-brightway-unverified`. A user who imported
the database records its identity once:

```python
bd.databases["ecoinvent-3.10-cutoff"].update(
    {"provider": "ecoinvent", "version": "3.10", "system_model": "cutoff"}
)
bd.databases.flush()
```

**Rerunning with a licensed background.** Keep the foreground (`lca/dataset.yaml` is the same
for both backends), add `activity:` mappings beside the `factor:` ones and switch `backend:
brightway` on a branch or a local copy. The manifest records the changed background and
mappings, so the two runs can be compared. Results drawing on the licensed database are
`restricted`: keep them local unless the database's terms and a reviewed decision allow more.

## Uncertainty

`uncertainty: {iterations: 1000, seed: 1, defaults: {assumed: {gsd2: 1.5}, calculated: {gsd2:
1.1}}, factors: {gsd2: 1.2}}` runs a Monte Carlo of the baseline with the study's allocation
method.

**What varies:**
- Every exchange of the plant's dataset varies by its own `uncertainty` (given on the flow, the
  construction entry, the consumable, ...), else by the study's default for its origin or
  provenance, else by the lognormal of its pedigree (see [Data quality](#data-quality)). Every
  exchange has a pedigree, so none goes unsampled silently; `bases` of the result (in `--json`)
  says for each input which applied (`given`, `study default`, `pedigree`). A distribution
  without spread (`gsd2: 1`) fixes an amount.
- Products vary too, so the allocation shares move.
- Every factor varies by its `uncertainty` in `lca/factors.yaml`, or `factors`. One multiplier
  per factor is shared by every row that uses it.

**Distributions,** relative to the value:
- `lognormal` with `gsd2`, the squared geometric standard deviation: 95 % lie within
  value / gsd2 and value x gsd2.
- `lognormal` with `pedigree` scores (reliability, completeness, temporal, geographical,
  technological; 1 to 5) on a `basic` gsd2. These combine as in ecoinvent:
  `gsd2 = exp(sqrt(sum(ln U ** 2)))`, with the empirically based uncertainty factors of
  Ciroth et al. (2016).
- `normal` with `cv`.
- `triangular` and `uniform` with `low` and `high` multipliers.

**Outputs:**
- `lca/uncertainty.csv`: deterministic value, mean, median, sd and the 95 % interval per
  category, to four significant digits. The seed makes it reproducible, and the `lca-current`
  gate checks it.
- `results.md` adds those values and the inputs ranked by their Spearman rank correlation with
  each total (the sensitivity).

Correlations:
- The functional unit's product is the reference and is not sampled.
- Maintenance follows its construction entry.
- Transport and end of life follow the mass-weighted multipliers of the exchanges they count.
- Each other exchange varies independently.

Reproducibility: the seed fixes the draws for a given numpy version. `uv.lock` pins numpy, so
`lca/uncertainty.csv` stays current until numpy is upgraded; rewrite it then.

Limits:
- With backend brightway, the database's own uncertainty is not sampled.
- A row whose background is a dataset takes that dataset's deterministic unit score.

## Data quality

**Per exchange.** Every exchange of a dataset carries a `pedigree: {scores, rule, reason}` on
the ecoinvent pedigree matrix (Weidema et al. 2013, data quality guideline for ecoinvent v3):
reliability, completeness, temporal, geographical and further technological correlation, 1
(best) to 5, relative to the dataset's declared scope (its `location` and `year`), not to the
plant. And a `basic_uncertainty` (gsd2) by exchange type. Together they give a lognormal gsd2
with the Ciroth et al. (2016) factors, `gsd2 = exp(sqrt(ln(basic)^2 + sum ln(U_i)^2))`, which the
Monte Carlo uses when no explicit uncertainty applies.

Nothing goes unscored: `cheme assess lca` (and the reading of a referenced dataset, v1
included) gives every exchange without one the default of the rule `cheme default pedigree v1`
(`domains/assessment/lca/quality.py`). The rule is cheme's convention, ASSUMED, recorded on each
pedigree it gives; a pedigree set by hand records its `reason` (it does not load without one):

| indicator | default |
|---|---|
| reliability | origin `measured` or `vendor` 2; `literature`, `simulated`, `correlation` 3; `design-rule`, `estimate` 4; else provenance `given`, `calculated` or `estimated` 3, `assumed` 4 (a verified measurement scores 1 only by hand) |
| completeness | 4: one plant (one site) represents the dataset |
| temporal | when the dataset declares its reference `year`: 1 for the design's own data, 3 for origin `literature`, `correlation` or `design-rule` and provenance `estimated` (secondary data, not of that year); 5 when no `year` is declared |
| geographical | 1 for a country or site code, 3 for a region (GLO, RER, RoW, EU27, ...: one design claimed for a larger area), 5 when no `location` is declared |
| technological | the process's own data (`given`, `calculated`) 1, an estimate for it (`assumed`) 2, `literature` and emission-factor estimates (`estimated`) 3; at least 3 for a `concept` and 2 for a `screening` design (design maturity, `maturity` of `process.yaml`) |

Basic uncertainty (gsd2), the default basic uncertainties of the ecoinvent v3 guideline (the
ecoinvent v2 factors, Frischknecht et al. 2007): energy, materials, wastes and resources 1.05;
transport 2.0; construction and maintenance (infrastructure) 3.0; land occupation 1.5,
transformation 2.0; emissions to air CO2 and SO2 1.05, CH4, NOx, N2O, NH3 and NMVOC 1.5,
PM2.5 3.0, CO 5.0 (combustion and process values; the table gives 1.2 for agricultural CH4 and
NH3); another emission 1.5 (ASSUMED). **Not verified yet**: these values were
entered without the guideline at hand and are still to be checked against its table of default
basic uncertainties, which will then be cited here; until then they are working defaults.

**Per dataset.** `cheme assess lca --coverage`, `--json` (`data_quality`) and `manifest.json`
give the plant's dataset's rating:
- the **TfS DQR** (Together for Sustainability PCF Guideline v3): TeR, GeR, TiR (the pedigree's
  technological, geographical and temporal scores, whose scales run the same way) averaged over
  the exchanges, weighted by each one's absolute contribution to the study's first climate
  category; without contributions (no climate category, an unlinked dataset) the unweighted
  unit-process value, flagged `weighted: false` as a simplification; DQR = their mean;
- the **PEF-style** indicators, adding precision P (from reliability) and completeness C, and
  DQR_PEF = (TeR + GeR + TiR + P) / 4;
- the **primary data share** (PDS): the share of data measured at the plant (origin
  `measured`), weighted the same way;
- the weakest of TeR, GeR and TiR.

Products, free exchanges and the vents or feeds counted by their components are not rated.
`--coverage` prints it, e.g. `data quality (gwp, 12 exchanges): DQR 2.31 (TfS: TeR 1.80, GeR
5.00, ...); weakest: GeR`.

## Carbon accounting and product carbon footprints

A study that declares `carbon_accounting:` in `lca/lca.yaml` is a product carbon footprint
(PCF) after ISO 14067 and the TfS PCF Guideline v3. Without it nothing below
applies and no output changes.

```yaml
carbon_accounting:
  biogenic: minus-one-plus-one   # or zero-zero; both report everything below
  ccu_rule: cut-off              # or upstream
  ccs: technosphere              # or emitted
  content:                       # where the flowsheet's composition does not say it
    feed:BIOMASS: {biogenic_fraction: 1.0, source: supplier declaration 2025}
  ipcc: {report: AR6, gwp_horizon: 100}   # for --pact, unless the category is ipcc2021-gwp100
  pact:                          # for --pact
    company_name: Example Chemicals
    company_ids: [urn:pact:company:customcode:buyer-assigned:1234]
    product_ids: [urn:pact:cas.org:substance-number:67-56-1]
    product_name: Methanol
    cpc: "34110"
flows:
  - {key: feed:CO2, factor: dac-capture, co2_source: direct-air-capture, source: ...}
  - {key: product:CO2OUT, factor: transport-and-storage, source: ...,
     storage: {permanence: saline aquifer under Directive 2009/31/EC, monitored}}
```

**Carbon content.** Every material exchange of the plant's dataset gets `carbon: {total,
biogenic_fraction, source}`: the total (kg C per kg) from the stream composition and the
components' formulas (`process/materials.yaml`), or from `content:`; the biogenic fraction from
the trace below. The product's carbon content and its biogenic and fossil parts are always
reported, even when small or 0.

**Biogenic fraction of the inputs.** A captured CO2 feedstock (`co2_source`) from a fossil point
source is fossil, always: a fossil point source is never a removal. CO2 from a biogenic point
source or from direct air capture is non-fossil under `ccu_rule: cut-off` (the CO2 carries its
capture, purification and compression burden through its background; its carbon is a removal
only through the product's biogenic carbon content), and fossil under `ccu_rule: upstream` (the
emitter or the capture plant claims the benefit). `ccu_rule` applies to the study's own (root)
dataset only: the datasets it references through `dataset:` backgrounds are traced with the
`co2_source` they declare, under the cut-off rule. An input with a declared `biogenic_fraction`
takes it first, a resource included; an undeclared resource `Carbon dioxide, in air` is the
biogenic uptake. An input linked to another dataset (`dataset:`) carries that dataset's traced
product fraction; any other carbon input, a carbon-bearing resource other than CO2 in air
included, counts as fossil (info `cheme.lca-carbon-assumed-fossil`: no removal without
evidence). A characterised CO2 uptake (a resource row with a climate factor) is a biogenic term,
never a fossil credit; if the climate category gives biogenic CO2 a non-zero value,
`cheme.lca-pcf-biogenic` (warning) says that amount is left out of the PCF (the removal is
counted once, through the product's carbon). Carbon
from direct air capture is booked with the biogenic (non-fossil) carbon, as the reference
lists' `Carbon dioxide, in air` and `Carbon dioxide, non-fossil` flows do.

**Tracing** (`domains/assessment/lca/carbon.py`). A dataset is one well-mixed carbon pool:
outputs that declare their biogenic fraction keep it, every other carbon output takes what is
left. The datasets of a chain (through `dataset:` backgrounds) are solved together as one linear
system, a carbon-flow matrix, so loops between processes close; Carbon Minds describe a
carbon-flow matrix for their supply chain (cm.chemicals methodology V2.03), and this is our own
implementation of the idea. The CO2, CO and CH4 emissions are then split by the traced fraction
into `emission:<component>` (fossil) and `emission:<component>.biogenic`, each characterised by
its origin (`trace_emissions: false` keeps the mapped origin and reports a mismatch,
`cheme.lca-carbon-origin`). Simplification: a plant that burns a fossil fuel beside a biogenic
feed declares its product's fraction, since one pool would mix them; tracing through the
flowsheet's units is not done yet.

**Checks.** `cheme.lca-carbon-balance` (warning): carbon in against products, outputs,
emissions and storage, within 1 % (5 % for `concept` and `screening` designs, the tolerances
of the balance gates); `cheme.lca-carbon-biogenic`: the declared biogenic contents cannot come from
the inputs; `cheme.lca-carbon-origin` (a mapped emission origin against the traced fraction) uses
the same design-maturity tolerance as the balance; `cheme.lca-carbon-unknown` (info): material exchanges without a carbon content,
left out; `cheme.lca-ccu-double-count`: a captured CO2 whose background already claims a
removal (negative) under `ccu_rule: cut-off`; `cheme.lca-ccs-emitted` (info). The interface
to the balance gates is `carbon.CarbonFlow` (kg C and biogenic kg C per exchange).

**CCS.** CO2 to geological storage is a technosphere output (`storage:` on a product mapping,
with its `permanence`), linked to transport and storage. Stored fossil CO2 is simply not
emitted; stored biogenic CO2 is a removal. `ccs: emitted` counts the stored CO2 as emitted with
its origin (e.g. while permanence is not shown).

**PCF breakdown** (`results.md`, rows of category `pcf` in `results.csv`, `carbon` in `--json`,
`pcf` in `manifest.json`), per functional unit, from the study's GWP100 climate category:

| line | what |
|---|---|
| fossil GHG emissions | direct fossil emissions and every background contribution (factors are taken as excluding biogenic CO2) |
| direct land-use change | emissions of origin `land-use-change` |
| other biogenic GHG emissions | biogenic CH4 (and other non-CO2 biogenic GHGs) |
| PCF excluding biogenic CO2 | the three above |
| biogenic carbon withdrawal | -44/12 x the product's biogenic carbon (kg CO2-eq, <= 0) |
| uptake of other biogenic carbon | -44/12 x the biogenic carbon that leaves as CH4, CO or in a non-product output (waste, purge) |
| biogenic CO2 to storage | -1 x the biogenic CO2 sent to permanent storage |
| PCF including biogenic CO2 | excluding + withdrawal + other uptake + stored biogenic CO2 |
| carbon content of the product | total, biogenic, fossil (kg C), and the part from captured CO2 (CCU), of it from a biogenic point source or the air (DAC) |
| foreground flows | biogenic CO2 emitted and taken up, CO2 stored (kg CO2) |

Cradle-to-gate, the -1 of every uptake and the +1 of every biogenic CO2 release cancel. What does
not cancel is biogenic carbon that does not leave as CO2: the carbon in the product, in CH4, CO
or a non-product output (waste, purge), and the biogenic CO2 stored. Their uptake is booked (the
release of biogenic CH4 is charged at its own GWP in "other biogenic"; the release of CO is not
charged, ASSUMED). Removals follow the carbon physically, not an allocated share. The carbon
contents are on a **physical basis** (the carbon traced through the process; cheme has no
mass-balance attribution). Flows of origin `land-use-change` come from carbon stocks, not from
the inputs, and are left out of the carbon balance. Two things the trace cannot see are
reported: a carbon input with a biogenic fraction whose background has a negative climate impact
(`cheme.lca-pcf-background-uptake`: the factor may already credit the uptake that the
withdrawal then counts again), and a climate factor that characterises biogenic CO2
(`cheme.lca-pcf-biogenic`). `biogenic: minus-one-plus-one` (the TfS v3 requirement) states the PCF
including biogenic CO2; `zero-zero` states the one excluding it; both report every line.

**PACT export.** `cheme assess lca --pact pact.json` writes the product's cradle-to-gate PCF as
a WBCSD PACT (Pathfinder) `ProductFootprint`, data model v2 (Technical Specifications 2.3;
property names, enumerations and constraints read from the specification's
`spec/v2/openapi.yaml`, whose licence does not allow redistributing it, so cheme checks the
document against its own model, `lca/pact.py`).

- **Declared unit**, by the product's unit (a dataset counts products in base units): kg
  `kilogram`, kWh `kilowatt hour`, m3 `cubic meter`, m2 `square meter`; any other unit (Nm3, ...)
  is refused. The amount is the functional unit in the product's unit (1 t of a product in kg is
  1000 kg).
- **Cradle-to-gate only, exempted emissions stated.** A study with `boundary: gate-to-gate` is
  not exported. What the boundary leaves out (construction, plant end of life, transport of
  supplies) and the flows cut off by the criteria are exempted emissions whose share cheme cannot
  know: `carbon_accounting.pact.exempted_emissions_percent` (at most 5) with
  `exempted_emissions_description` (mark an estimate ASSUMED), else no document is made. A study
  that leaves out nothing exports 0 %. `dqi.coveragePercent` is 100 less that share.
- **Properties required from 2025 on** (the specification's O* properties) are all written for a
  period including 2025 or later, and `validate` checks them: `landManagementGhgEmissions` is
  "0" (land management is not modelled: ASSUMED, stated in the comment), and
  `biogenicAccountingMethodology` is cheme's mapping, ISO for -1/+1 and PEF for 0/0.
- **Reference period**: the study's `year`, the end excluded. `primaryDataShare` and `dqi` come
  from the dataset's rating, the TfS indicators (1 to 5) mapped linearly onto PACT's 1 to 3
  (cheme's mapping; the TfS values are repeated in `comment`); they are
  required when the period includes the beginning of 2025 or later (calendar 2024, ending
  2025-01-01, is before it).
- **Geography** from `location`: an ISO 3166-1 alpha-2 code is `geographyCountry`, an ISO 3166-2
  subdivision (`DE-BY`) `geographyCountrySubdivision`, a PACT region (`Western Europe`)
  `geographyRegionOrSubregion`; an empty location is global. Any other location is refused, never
  exported as global.
- **IPCC report**: `carbon_accounting.ipcc: {report: AR5|AR6, gwp_horizon: 100}`, or an exact
  packaged category (`elementary: ipcc2021-gwp100` is AR6). It is never guessed from titles, and
  only a 100-year horizon is exported.
- **Identifiers** are URNs. The specification accepts any URN and recommends
  `urn:pact:<domain-of-issuer>:<identifier-type>:<id>`, which cheme checks for a `urn:pact:` value.
- **Biogenic CO2**: `pCfIncludingBiogenic = pCfExcludingBiogenic + biogenicCarbonWithdrawal`, plus
  the uptake of biogenic carbon that leaves as CH4, CO or in a non-product output (stated with
  its amount in `comment`). The biogenic CO2 sent to storage (`ccs: technosphere`) is a
  technological removal PACT v2 has no field for: it is not in `pCfIncludingBiogenic`, and the
  `comment` states it with the figure that includes it. `fossilGhgEmissions` contains every
  background contribution (biogenic CH4 or land-use change inside background factors is not
  separated), the carbon contents are physical, and the carbon from captured CO2 (CCU, of it
  DAC or biogenic) is stated in the `comment`. The TfS guideline rule
  (`productOrSectorSpecificRules`) and `biogenicAccountingMethodology: ISO` are written only for
  `biogenic: minus-one-plus-one`.
- **Id and version**: the footprint `id` is a uuid5 of the dataset, its version, the product, the
  case and a hash of the `pcf` values and the reference period, so a changed result gets a new id
  instead of reusing one with `version` 1.

A result with gaps in the climate category is not exported (PACT needs the share of exempted
emissions, and the size of a gap is unknown), nor one without `carbon_accounting.pact`, a year,
a CPC code, an IPCC declaration or a data quality rating. The file is not part of `--write`:
PACT records when it was created.

## LCI datasets

An LCI dataset (`kind: lci_dataset`, `cheme schema lci_dataset`) is a reusable, unallocated
inventory of one process:
- **Exchanges:** each has a `type` (`product`, `input`, `output`, `emission`, `resource`), an
  amount and unit in the dataset's `basis` (e.g. `1 h of operation`), its provenance (`given`,
  `calculated`, `estimated`, `assumed`; `estimated` is an emission-factor estimate), and a
  `link` (its background) or `free`. v2 adds `flow` (elementary identities), `carrier`,
  `state`, `pedigree`, `basic_uncertainty`, `formula`, and `composition` and
  `balance_exclusion` for the balances (see [Mass, element and energy
  balances](#mass-element-and-energy-balances)).
- **Products** carry `properties` (`price`, `energy`, `exergy` per unit) for allocation.
- **Scope:** `foreground` means the process's own exchanges, still to be linked to backgrounds;
  `linked` means a cradle-to-gate dataset whose inputs are already accounted for. A
  foreground inventory is not a footprint.
- **Default allocation:** `allocation`, used when a study names none. `allocation.deviation`
  (here and in `lca/lca.yaml`) states why the method departs from the library's
  multi-functionality hierarchy, e.g. a sector PCR.

A process without a flowsheet gets a screening dataset from `cheme assess lci-estimate`: Tier 0
(stoichiometric) or Tier 1 (sourced conceptual), labelled with `generation: {tier, method,
defaults_used}`, every default exchange assumed, its calculation maturity and DQR capped and its element
balance closed. See [Tiered LCI estimates](lci-estimate.md).

### Version and migration

`schema: cheme/lci_dataset/v2`. A v1 dataset (`schema: cheme/lca/v1`, the LCA
files' id it shared) still loads: every field v2 adds is optional, the per-exchange data
quality is defaulted by rule (see [Data quality](#data-quality)), and `cheme assess lca` warns
`cheme.lca-dataset-v1` and lists what it lacks (`cheme.lca-dataset-undocumented`, info).
`cheme migrate --write` rewrites the `schema:` line of the hand-written datasets in
`lca/datasets/`, keeping comments; `cheme assess lca --write` rewrites a generated
`lca/dataset.yaml`.

### Mass, element and energy balances

Every dataset is checked for closure over its exchanges (`assessment.lca.balance`):
the plant's `lca/dataset.yaml` by `cheme assess lca`, and each dataset a study references
(`dataset:` backgrounds, hand-written ones included). Inputs and resources (free ones such as
air and water included) count in; products, outputs (wastes, by-products, CO2 to storage) and
emissions count out, per the dataset's basis.

- **Mass:** every material exchange of the operation in kg, in Nm3 where its composition
  gives the molar mass (ideal gas at 0 °C and 1.01325 bar), and water (CAS 7732-18-5)
  in m3 at 1000 kg/m3, the volume convention of LCI databases. Beside another m3 flow that is
  not counted (a wastewater return without a CAS number), water in m3 is excluded too, with
  the reason naming it: one side of a water balance alone would open it.
- **Elements** (C, H, O, N, S, Cl, the metals, P, whatever the compositions hold): from each
  exchange's `composition`: mass `fractions` of components read as molecular formulas unless
  `formulas` names them (`{fractions: {MEOH: 0.98, H2O: 0.02}, formulas: {MEOH: CH4O, H2O:
  H2O}}`), or mass fractions of `elements` (a fuel's ultimate analysis, with `ash` for the
  residue: counted in the mass, in no element). A flowsheet-derived
  dataset gets it from the stream table, with the formulas of `process/materials.yaml` (`''`
  where a component has none, so that the balance names it). Without a composition the
  formula of a Tier 0/1 estimate (`generation.formulas`) is used, then that of a common
  elementary flow by CAS number (CO2, CO, CH4, H2O, N2, O2, Ar, H2, NH3, N2O, NO, NO2 for NOx,
  SO2, H2S, HCl, Cl2, methanol). A material exchange with none of them makes the element and
  carbon balances *not assessable*, named (never counted as 0).
- **Carbon by origin:** the carbon of the inputs split into fossil, biogenic and atmospheric
  (direct air capture, the uptake of CO2 from air) as the carbon accounting traces it (see
  [Carbon accounting](#carbon-accounting-and-product-carbon-footprints)), against the carbon of
  the products, emissions and other outputs (wastes). It closes when the totals agree and no
  output whose origin is declared (an emission mapped `origin: fossil|biogenic`, a declared
  `biogenic_fraction`) carries more carbon of that origin than the inputs give: the check that
  keeps `origin:` on emissions honest. A CO2 resource (CO2 taken from air) is atmospheric
  carbon, whatever `biogenic_fraction` it declares. When the origin of some input carbon
  cannot be traced (a referenced dataset that does not load), the carbon balance is *not
  assessable*, with the reason: its carbon is never assumed fossil for this check.
- **Energy** is reported as a closure fraction, not a pass or fail: electricity, heat and steam
  in, and fuels at their lower heating value (`carrier.lhv`, MJ/kg; a gaseous fuel in Nm3 by
  the molar mass of its composition, also when it is outside the mass balance), against the heat rejected (`cold`
  duties), the energy exported and the products' energy content (`properties.energy`). The
  sensible and latent enthalpy of the material streams is not in a dataset and not counted;
  energy exchanges without a carrier, and fuels without an LHV or a molar mass, are listed.
- **Excluded**, each with its reason: an exchange's own `balance_exclusion` (e.g. an adsorbent
  charge counted over its life), another phase (construction, maintenance, end of life), an
  avoided-production credit, an emission of origin `land-use-change` (carbon from soil and
  biomass stocks, not from the inputs), a vent or intake counted by its
  `emission:*`/`resource:*` exchanges, energy (the energy closure) and any other unit (ea, tkm,
  m3 other than water). The recorded cut-off
  flows are listed beside the balance, not counted in it (the cut-off criteria bound them).

The default tolerance, relative to the larger side, is 1 % for a dataset derived from a
simulated flowsheet and 5 % for a sourced screening dataset: a Tier 0 or 1 estimate, a dataset
not derived from a flowsheet (written by hand), or a design whose design maturity is `concept` or
`screening` (`process.yaml`, as the carbon balance of the carbon accounting). An open balance is
the warning `cheme.lci-mass-balance`, `cheme.lci-element-balance` or `cheme.lci-carbon-origin`
naming its residual (kg per basis and %); a balance that cannot be assessed is the info
`cheme.lci-balance-unassessable`. For publication the gate requirements of the same names
(`kind: lca`) turn them into failures, a balance that cannot be assessed included: give the
exchange its composition or a `balance_exclusion` with the reason.

`cheme assess lca --balance` prints the table (in, out, residual in kg and % per quantity and
element, carbon by origin, energy, the exclusions; `--json` as JSON). It needs only the
inventory, no factors or background, which is why it is its own option rather than part of
`--coverage`; `--coverage` prints a one-line summary. `lca/manifest.json` records the result as
`balance` (status per requirement, closures, the exchanges without a composition, exclusions),
for the library's `datapackage.json` and the Atlas.

### Documentation

What a professional LCI database documents of each dataset. The study declares what cheme
cannot derive under `dataset:` of `lca/lca.yaml`; `cheme assess lca` copies it into
`lca/dataset.yaml` and fills in:
- `uuid`: uuid5 of `<flowsheet title>/<dataset id>` in a fixed namespace, so it is stable
  across versions while the title and id stay; pin it with `dataset.uuid` before a rename;
- `time.start` (the reference `year`) and `valid_until` (`year` + 5: the data-freshness rule
  for primary data, overridable);
- `production_volume`: the reference product's flow x `operation.hours_per_year`;
- `modelling.multifunctionality`: from the allocation;
- `location`, `year`, `technology` and `rights` from the study, as before.

Classification, review, version, system model and the data generator are never guessed. The
paths below are abbreviated (ILCD 1.1 / EF 3.1 process dataset, EcoSpold2 activity dataset);
the converters (process-library#51) are checked against the format specifications.

| field | what | ILCD | EcoSpold2 |
|---|---|---|---|
| `uuid` | identity, stable across versions | `dataSetInformation/common:UUID` | `activity/@id` |
| `version` | `major.minor.patch` | `publicationAndOwnership/common:dataSetVersion` | `fileAttributes/@majorRelease`, `@minorRelease`, `@majorRevision` |
| `methodology_version` | the library methodology it was built under | `complianceDeclarations` (free text) | `generalComment` |
| `superseded_by` | `{id, version}` of its successor | the successor's `common:referenceToPrecedingDataSetVersion` | - |
| `parent` | uuid of the dataset this is a (regional) variant of | - | `activity/@parentActivityId` |
| `title` | name | `dataSetInformation/name/baseName` | `activity/activityName` |
| `location` | ISO 3166-1 alpha-2, GLO, RER or RoW | `geography/locationOfOperationSupplyOrProduction/@location` | `geography/shortname` |
| `geography.description` | representativeness of the location | `.../descriptionOfRestrictions` | `geography/comment` |
| `geography.site`, `.applicable` | the facility's place; where it may also be applied | `descriptionOfRestrictions` (text) | `geography/comment` |
| `year`, `time.start` | the data's reference year; first valid year | `time/common:referenceYear` | `timePeriod/@startDate` |
| `valid_until` | last year of use | `time/common:dataSetValidUntil` | `timePeriod/@endDate` |
| `time.description` | temporal representativeness | `time/common:timeRepresentativenessDescription` | `timePeriod/comment` |
| `technology` | the included process steps | `technology/technologyDescriptionAndIncludedProcesses` | `activity/includedActivitiesStart`, `generalComment` |
| `technology_level` | undefined, new, modern, current, old, outdated | - | `technology/@technologyLevel` |
| `boundary`, `system_boundary` | text; included and excluded steps, cut-off criteria, infrastructure, catalysts, non-routine operation | `dataSourcesTreatmentAndRepresentativeness/dataCutOffAndCompletenessPrinciples`, `deviationsFromCutOffAndCompletenessPrinciples` | `representativeness/extrapolations`, `activity/includedActivitiesEnd` |
| `production_volume` | annual output in its geography | `dataSourcesTreatmentAndRepresentativeness/annualSupplyOrProductionVolume` | `intermediateExchange/@productionVolumeAmount` |
| `classification.isic`, `.cpc` | ISIC Rev.4 class, CPC Ver. 2.1 subclass | `classificationInformation/common:classification` | `activity/classification`; `intermediateExchange/classification` |
| `modelling.principle` | attributional, consequential | `LCIMethodAndAllocation/LCIMethodPrinciple` | `activity/@specialActivityType`, system model |
| `system_model` | cutoff, apos, substitution, consequential | `LCIMethodAndAllocation/LCIMethodApproaches` | `representativeness/@systemModelName` |
| `modelling.multifunctionality`, `allocation` | multi-output handling, default allocation | `LCIMethodAndAllocation/LCIMethodApproaches` | `representativeness/@systemModelName`, `intermediateExchange/property` |
| `allocation.deviation` | a departure from the hierarchy | `LCIMethodAndAllocation/deviationsFromLCIMethodApproaches` | `generalComment` |
| `modelling.sampling` | sampling and representativeness | `dataSourcesTreatmentAndRepresentativeness/samplingProcedure` | `representativeness/samplingProcedure` |
| `review` | `{type: none, internal, independent-external, panel; reviewer, scope, date, report}`; `unreviewed` states none | `validation/review` | `modellingAndValidation/review` |
| `data_generator`, `entry_by` | who modelled it, who entered it | `dataGenerator`, `dataEntryBy` | `dataGeneratorAndPublication/@personName`, `dataEntryBy/@personName` |
| `rights`, `sources` | its own data's terms; externally supplied amounts | `publicationAndOwnership/common:licenseType` | `dataGeneratorAndPublication/@accessRestrictedTo` |
| `cutoff` | flows left out by the cut-off criteria, with amount and reason | `dataSourcesTreatmentAndRepresentativeness/deviationsFromCutOffAndCompletenessPrinciples` | `representativeness/extrapolations` (text) |
| exchange `treatment` | waste, recyclable or by-product output, its route and credit | `exchange/generalComment` | `intermediateExchange/classification` (waste, by-product), `comment` |
| `parameters`, exchange `formula` | named values and how amounts follow from them | `mathematicalRelations/variableParameter` | `flowData/parameter`, `intermediateExchange/@mathematicalRelation` |

An exchange's `formula` (`+ - * / **` and parentheses on numbers and parameter names) must give
its amount; a mismatch does not load.

**Publication minimum.** The gate requirement `lci-documented` (`kind: lca`) checks the plant's
dataset for: `uuid`, `version`, `title`, `location`, `geography.description`, `year`,
`valid_until`, `system_model`, `technology`, `technology_level`, a boundary (`boundary` or
`system_boundary`), `classification.isic` and `.cpc`, `modelling.principle`,
`modelling.multifunctionality` (a multi-output dataset), a `review` record (`unreviewed` counts:
it is stated), flow identities (every emission and resource with a UUID in a reference list),
`rights` and `data_generator`. Roughly the ILCD "data entry level".

Two uses:
- **Process design:** `cheme assess lca --write` writes the plant's dataset as
  `lca/dataset.yaml`, derived from the flowsheet, with the files it came from
  (`provenance.files`). The study's results are this dataset, allocated and characterised.
- **A library of processes (e.g. the Process Atlas):**
  - Datasets derived from plant repositories, or written by hand (`lca/datasets/*.yaml`), are
    kept unallocated.
  - A study links one as the background of a flow, with `dataset: {path, product, allocation}`,
    and makes its own choices of allocation, boundary and background.
  - Such a link replaces a background activity, so `cheme assess lca` checks that the dataset
    can stand in for the flow (warning `cheme.lca-link-compat`, an info when the mapping's
    `proxy:` says why it stands): the substance (the CAS number of the feed's main component
    against the product's `cas`), phase and grade (`state.purity` of the same basis) the plant
    takes; a product delivered below the pressure the plant takes it at (the compression is in
    neither); when the study itself shares burdens between co-products, a multi-product dataset
    allocated by the same method; and the study's system model (an unset one is cutoff; a
    crediting mismatch is `cheme.lca-system-model-mixed`). A unit of another kind is an error
    (`cheme.lca-dataset`). Transport is not compared: a dataset's `transport:` exchanges carry
    its own inputs, and nothing says yet whether a product is delivered.

## Exergy

`cheme process props --fill` writes each stream's molar exergy (`calculated.exergy`, kJ/kmol)
where the property method applies:
- **Chemical:** the standard chemical exergies of Szargut et al. (1988, model II;
  `domains/process/data/chemical-exergy.yaml`) plus the ideal mixing term.
- **Physical:** `(h - h0) - T0 (s - s0)` against the same composition at 298.15 K and
  101.325 kPa.

Exergy allocation weighs a compressed or cold product by the work it holds, which mass
allocation ignores. For example, pipeline oxygen at 31 bar holds about 12.3 MJ/kmol, against
3.97 MJ/kmol for oxygen at ambient conditions.

## Outputs

`cheme assess lca --write` writes these files, and `--check` compares them:
- `lca/inventory.csv`: per row the phase, the plant's amount (per hour, or in total for
  construction), the quantity per functional unit, its provenance and its mapping;
- `lca/results.csv`: one row per scenario, category and contribution, with its phase, and a
  total row per scenario and category;
- `lca/results.md`: the result's class and reasons, the scenario comparison, the split by
  phase, the allocation comparison (every method's share and totals, or why it does not
  apply), the contributions to the baseline, the inventory, the gaps, the boundary check
  (see Boundary check), the sources with their attribution, and the limitations;
- `lca/gaps.csv`: every scenario's gaps (the header alone when there is none);
- `lca/dataset.yaml`: the plant's unallocated LCI dataset;
- `lca/manifest.json`: the run manifest;
- `lca/uncertainty.csv`, with `uncertainty:`.

With `carbon_accounting:`, `results.md` and `results.csv` add the PCF breakdown, and `--pact`
writes a PACT footprint (see Carbon accounting).

Findings are reported as `cheme.lca-*`. The gate is `kind: lca` with `require: [mapped,
factors, no-gaps, factors-published, publishable, lci-documented, cutoff-criteria, lci-emissions-complete,
lci-mass-balance, lci-element-balance, lci-carbon-origin, lca-current]`. While the LCA does not
compute, every requirement fails.

## Viewer API

`GET /api/lca?rev=` (`cheme serve`) returns `cheme assess lca --json` of a revision
without the source:
- inventory;
- categories;
- totals and the totals of each scenario;
- impacts by scenario, category, phase and contributor, each with its `source_id`;
- the classification, its label and reasons, `climate_only`, the limitations, the gaps and
  the sources used;
- `publication`: the policy, whether the results are publishable, and the sources that
  restrict them;
- `data_quality` (the dataset's rating) and `water` (its water balance), or null;
- `boundary_check`: what the flowsheet's declared boundary leaves out (see Boundary check);
- findings.

It returns 404 when there is no `lca/lca.yaml`, and 422 with the first error when the LCA does
not compute. `GET /api/repo` says `has_lca`. The viewer's LCA page draws it as a contribution
Sankey, scenario bars, and contribution and inventory tables.

## Brightway, ecoinvent and premise

Install the extra with `pip install 'cheme-as-code[lca]'` (bw2data, bw2calc). It has no wheels for
Python 3.15 yet; use 3.12 to 3.14.

The Brightway project lives outside the plant repository, in `BRIGHTWAY2_DIR` or Brightway's
default directory. Each user imports the databases they are licensed for there, so licensed
content is never committed:

```python
import bw2data as bd, bw2io as bi

bd.projects.set_current("asu-1")
bi.import_ecoinvent_release("3.10", "cutoff", "<user>", "<password>")  # ecoinvent licence
# or an open database, e.g. one exported as JSON-LD from the Federal LCA Commons:
# bi.JSONLDImporter(...) and then .apply_strategies(), .write_database()
```

`cheme assess lca-search "electricity medium voltage" --database ecoinvent-3.10-cutoff`
prints `activity:` mappings ready to paste into `lca/lca.yaml`.

`cheme assess lca-map` does this for every exchange without a background (unmapped, or
declared `missing:`): it searches the project with the exchange's name (or the id of its key
when the name finds nothing; `--query` for one exchange), and lists numbered candidates with the
query that found them and whether their unit fits. It is a dry run. `--apply KEY=N --source S`
(repeatable) writes the approved candidates, and only them, as `activity:`: in place of the
entry's `missing:` (its `source:` becomes S), or as a new `flows:` entry for an unmapped feed or
product. The edit keeps the rest of the file and its comments, and is refused, with nothing
written, when a candidate is a biosphere flow or per another kind of unit, or when the file
would not parse to exactly that change or validate. Emissions, resources and disposals are
mapped by hand. Review the diff, then run `cheme assess lca --write`.

**Provider profiles.** A study's flows are named in the flowsheet's own terms: a
feed's or product's key, and a feed's `utility.kind`. That is the provider-independent part of the
exchange contract. A provider profile (`kind: lca_mapping_profile`, e.g.
`lca/mapping-profiles/ecoinvent-3.11-cutoff.yaml`) says how one background provider names the
activity for them: `provider`, `version`, `system_model`, and `entries` of
`{match: {key: feed:POWER} | {utility: electricity}, activity, source, proxy}`. A study selects
profiles with `brightway.mapping_profiles: [paths]` (backend brightway; under backend factors
they are unused, the info `cheme.lca-mapping-profile-unused`).

- A profile maps only the feeds and products that `flows:` leaves without an entry: the
  study's own entry, `missing:` included, always wins. The first matching entry of the first
  profile is taken, a key before a utility kind within a profile.
- A utility kind matches feeds only: a product of a utility kind (exported power or steam) may
  be an export, so products are matched by key only. A gate-to-gate study maps its feeds free,
  so profiles map none of its feeds.
- The info `cheme.lca-mapping-profile-used` lists what a profile mapped; a profile that does
  not load is the error `cheme.lca-mapping-profile`; the warning
  `cheme.lca-mapping-profile-fit` names a profile whose system model is not the study's, whose
  provider, version or system model contradicts `brightway.expect` of its databases, or whose
  key entries name no flow of the flowsheet. An activity a profile names that the project lacks
  is reported on the flow like any other (`cheme.lca-activity-missing`): correct it in the
  profile.
- The profiles are inputs of the run manifest, so editing one makes the results stale.

What a profile does not do yet: keys are per plant, so across plants only the utility entries
are reusable until entries can match a substance (CAS number) or the Atlas's chemical slugs (and
the process library's `lci/mappings.yaml` can be exported as profiles); entries carry no
`treatment:`, `uncertainty:` or CCU/CCS fields (map such flows in `flows:`); construction,
consumable and transport entries; `cheme assess lca-cases` does not apply them yet; and
changing provider still needs the project, `biosphere`, `expect` and the method tuples of the
other provider, and the study's own `activity:` entries rewritten. A profile holds activity
names only, never a factor or result of the provider; still, the names it supplies are written
into `lca/inventory.csv` and `lca/dataset.yaml` like any mapping, so commit a profile (and the
results) only where the provider's terms allow its names. Private local profiles outside the
repository are not supported yet.

**Prospective scenarios with premise.** premise writes scenario databases into the same
project. Install it in its own environment, as its documentation recommends; premise is not a
cheme extra because its pinned dependencies do not build on current Python versions:

```python
from premise import NewDatabase

ndb = NewDatabase(
    scenarios=[{"model": "remind", "pathway": "SSP2-PkBudg1150", "year": 2050}],
    source_db="ecoinvent-3.10-cutoff",
    source_version="3.10",
    key="<premise key>",
)
ndb.update()
ndb.write_db_to_brightway(name="ei310-remind-pkbudg1150-2050")
```

Then name the database in a scenario. Activity names stay the same, so no mapping changes:

```yaml
scenarios:
  - id: "2050-pkbudg1150"
    databases: {ecoinvent-3.10-cutoff: ei310-remind-pkbudg1150-2050}
    source: "premise 2.x, REMIND SSP2-PkBudg1150, 2050"
```

Without a database licence, the same scenario mechanism works on factors, e.g.
`factors: {electricity: electricity-2050}` with a published grid projection as the source.
