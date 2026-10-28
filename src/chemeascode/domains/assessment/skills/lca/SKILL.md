---
name: lca
description: Life cycle assessment of the plant per functional unit - cheme assess lca (goal and scope in lca/lca.yaml, the flowsheet's feeds, products and utilities as the operation inventory, take-off and equipment weights as the construction, allocation between co-products, characterisation with the project's factors or a Brightway project with ecoinvent, prospective scenarios such as premise 2050 databases). Use when a carbon footprint, an LCA, environmental impacts, a comparison of design alternatives by impacts, or a prospective (future) assessment is asked for, or when the gate lca fails.
---

# Life cycle assessment

## Purpose and when to use

Give the plant's environmental impacts per functional unit (e.g. kg CO2-eq per t of product),
with every number traceable to a flow of the design and a background with a source. Use it for
a carbon footprint, a screening LCA at concept stage, the comparison of alternatives (each a
branch: same scope, different flowsheet), the contribution analysis that shows which utility or
material dominates, a prospective assessment (electricity mix in 2030 or 2050), and when the
gate `lca` fails.

## Required inputs and missing inputs

- A flowsheet with flows: `cheme process streams` shows every feed and product with a flow
  (or duty) in the case to assess. Utilities must be **energy terminals**: a feed `POWER` or
  `STEAM`, a product `CW` (heat rejected), with streams `kind: energy` and a `duty` per
  consumer (skill `process-design`). Without them the inventory has no utilities.
- The goal and scope in `lca/lca.yaml` (`cheme schema lca`): the functional unit (an amount
  of one product), the boundary, the co-products and the allocation, the background of every
  flow. Ask the user for the goal (what decision the LCA serves) and the functional unit when
  they are not given; they decide everything after.
- Backgrounds, with sources. **Never invent a factor** and never present a number from memory
  as data.
  - Without a database licence: `lca/factors.yaml`. The file `cheme init` writes includes the
    packaged open profile `desnz-ghg-2026` (UK DESNZ 2026, OGL-3.0, results publishable with
    its attribution): electricity, natural gas, lorry tkm, water, construction materials, as
    `desnz-ghg-2026:<id>` (docs/framework/lca.md of cheme-as-code lists them). It is climate-only and UK: a
    screening carbon footprint, and a proxy outside the UK. Add published values of the
    project (a national grid factor from the agency that publishes it, an EPD, a
    peer-reviewed dataset), each with status, source, year, `location` and a `sources:`
    registry entry (provider, exact version, licence, attribution, `publication`). Free
    access is not permission: record the terms, and ask the user when they are unclear.
  - With a Brightway project (ecoinvent licence, or an open database such as USLCI): `backend:
    brightway`, with `activity:` and `biosphere:` mappings that `cheme assess lca-search`
    finds; `cheme assess lca-map` lists candidates for every open exchange, and `--apply
    KEY=N --source S` writes only the candidates you chose (check each before applying); a
    provider profile (`brightway.mapping_profiles`, kind `lca_mapping_profile`) maps the feeds
    and products `flows:` leaves without an entry. The project is the user's; licensed data
    never goes into the repository.
- Construction: `estimate/mto.csv` (skill `mto-estimate`) and `dimensions.weight` of the
  equipment, plus `operation: {hours_per_year, life_years}` from the design basis.

## Workflow and tools

1. **Scope.** Write `lca/lca.yaml`: `goal`, `functional_unit`, `boundary`, `case`. Decide the
   co-products. With several products (an ASU: GOX, GAN, LOX, LIN), allocation changes the
   answer more than most factors. ISO 14044 prefers avoiding allocation (system expansion:
   `method: substitution`, with the avoided production of each co-product); otherwise a
   physical basis (`exergy` when the products differ in pressure, temperature or purity; run
   `cheme process props --fill` first, or give `properties.<product>.exergy`), then
   economic. Read the allocation comparison in `lca/results.md`: every method whose data is
   complete is computed. Choose one, record why in `allocation.source`, and report the
   spread.
2. **Map every flow.** Run `cheme assess lca` and read `cheme.lca-unmapped`. For each
   feed, product and emitted component give one entry:
   - `free: true` for resources without burden (ambient air) and for atmospheric components
     returned unchanged (N2, O2, Ar, water, CO2 taken in with the air);
   - `emission: true` for a product released to the environment, then each component free or
     `elementary: {compartment: air, subcompartment: non-urban-high-stack, origin: fossil}`
     (characterised by its CAS number; the sub-compartment where the release point is known,
     origin fossil, biogenic or land-use-change);
   - `resource: true` for a feed taken from nature (river or well water, ambient air), then
     each component `elementary: {compartment: resource, flow: water-river}` or free. Water
     withdrawn or evaporated must show as a resource (`cheme.lca-water-resource` warns); read
     the water balance in `--coverage`. Never invent a flow UUID: the identities come from the
     packaged crosswalk (`cheme.lca-flow-identity`, `cheme.lca-flow-uuid` name what is open);
   - a `factor:` or an `activity:` otherwise, or a `dataset:` (another process's unallocated LCI
     dataset, `kind: lci_dataset`) when the input comes from a process modelled in the
     repository or a process library.
   A published factor used for a related flow (another material, geography or technology)
   gets `proxy: "<what stands for what, and where that holds>"`; a number the project derives
   is a factor `ESTIMATE` with `basis` and `validity`. A flow without any background gets
   `missing: "<why>"`: it stays in the inventory as a gap, and the results say so; never map
   it `free` or drop the entry to make it disappear.
   Choose market activities ("market for electricity, medium voltage") for the right location.
   For energy, mind the unit: the inventory counts kWh, a heat activity is per MJ, and the
   conversion is automatic when the kinds match. Give every energy terminal its `utility.kind`
   and supply temperature in the flowsheet, and steam its `pressure` and `level` (LP, MP, HP):
   the dataset's exchanges then carry their carrier (steam at its level, heat at its
   temperature, cold), which decides the background to link (`cheme.lca-carrier` names the
   ones without, `cheme.lca-carrier-level` those without their level). A gas product may be per Nm3 (functional unit),
   a fuel or hydrogen per MJ LHV (with the product's `energy`), electricity or steam per kWh.
3. **Construction.** Add `operation` and `construction:` entries: steel, pipe, concrete and
   insulation from the take-off, and equipment by material from the equipment list. Read
   `lca-construction-unmapped` and `lca-equipment-weight`. Missing weights count as zero: give
   them as ASSUMED estimates with a source, or state the gap.
4. **Run and read.** `cheme assess lca --coverage` first: the classification (complete,
   screening, partial, unavailable) and why, every gap with its quantity, the sources and
   the limitations, and the `boundary check:` line: a step without an energy stream or a
   product without `category` (`cheme.boundary-*`) is left out of the inventory, never added
   for you; close it in the flowsheet (see the process-design skill) or state it beside the
   result. Then `cheme assess lca` (Markdown): totals per scenario, the split by
   phase, the contributions. Report the result under its label ("partial screening carbon
   footprint"), with the gaps beside the totals and without a coverage percentage. Check the dominant contributor against an independent estimate. Example:
   specific power x grid factor for an air separation, or the fuel's carbon for a reformer.
   Investigate any result that disagrees by more than the data's accuracy.
   For a product carbon footprint (ISO 14067, TfS, PACT), declare `carbon_accounting:` (the
   biogenic method, the CCU rule, CCS, each feed's biogenic fraction with its source, and
   `co2_source` on captured CO2) and report the PCF breakdown: excluding and including biogenic
   CO2, and the product's biogenic and fossil carbon content. Read `cheme.lca-carbon-*`; never
   declare a fossil point source biogenic. `--pact FILE` exports it for a customer.
5. **Uncertainty and data quality.** Every dataset exchange carries a pedigree (the default
   rule's, from its provenance and origin, the declared location and year, and the design
   maturity of `process.yaml`); the Monte Carlo uses its lognormal where neither the exchange nor
   `uncertainty.defaults` give one. Override a pedigree only with a `reason` (e.g. a metered
   value). Give `uncertainty:` with defaults by provenance where the study knows better, and
   the known uncertainties of the main flows and factors. Report the 95 % interval with the
   result, read the sensitivity (refine first what ranks highest), and report the DQR from
   `--coverage` (TfS DQR, PEF-style indicators, primary data share) with its weakest indicator.
   Declaring a larger geography than the data represent lowers it: never claim a region to
   look representative.
6. **Scenarios.** Add `scenarios:` for the questions the goal asks, e.g. a grid factor for 2030
   or 2050 (`factors:`), or premise databases (`databases:`, see docs/framework/lca.md). Name
   the model, pathway and year in `source`. A regional background (another country's grid)
   gives `location`, `year` and `electricity` (grid-average, residual-mix, contractual with its
   instrument in `source`, on-site), and declares `missing:` or `proxy:` (flow key -> why) where
   no background of that region exists: never a zero, never the baseline's relabelled. A
   physical change (a hot climate, another capacity) needs its own computed flowsheet case
   (`case:`); never scale a design. `cheme assess lca-scenarios --write` writes one record per
   scenario (`lca/scenarios/<id>.json`, docs/framework/lci-scenarios.md). Each record and
   `results.md` carry a verdict against the baseline (`like-for-like`, `proxy`,
   `not comparable`), read from the factors' structured `scope` (basis, delivery, gases, gwp,
   mix, accounting; docs/framework/lci-comparison-basis.md). Give your own factors a `scope`
   where the source states it; never report a `proxy` or `not comparable` scenario as a
   like-for-like country comparison. A factor dated by its publication keeps that `year`; give
   `data_year` (and `publication_year`) only where the source states them, never by guessing.
7. **Write and gate.** `cheme assess lca --write`; commit `lca/*` with the inputs. The gate
   `kind: lca` requires `mapped`, then `lca-current`, `no-gaps` when the result must not be
   partial, and `factors` once the project's own replace an example. A result meant for
   publication also requires `factors-published` and passes `cheme assess lca --strict`: every
   exchange's factor status (`--json` `factor_status`) is `PUBLISHED`, `EPD`, `database` or
   `none`; an example, `ASSUMED`, `PROXY` or `ESTIMATE` factor or a gap is named as
   `cheme.lca-factor-status`. Never relabel a factor's status to pass it: replace the number
   with a published one, or report the result as screening.
8. **Licensed background rerun (optional).** With the user's own licensed database in a
   local Brightway project, keep the same foreground (`lca/dataset.yaml` does not change) and
   switch `backend: brightway`, giving each mapping an `activity:` beside its `factor:` (a
   mapping may hold both, so either backend runs). Record in
   `DESIGN.md` which mappings changed, so the two results can be compared. Give
   `brightway.expect` (provider, version, system model) so the database is identified, not
   just named. Results drawing on a licensed database are `restricted`: they stay local
   unless its terms and a reviewed `publication:` decision of a person allow more; never
   commit or publish them by default, and never write that decision yourself.
9. **Foreground only.** `cheme assess lca --dataset` exports the unallocated foreground with
   no factors, Brightway or credentials: what a process library publishes.
10. **Document the dataset** before it is published (`cheme/lci_dataset/v2`). Give what cheme
   cannot derive under `dataset:` of `lca/lca.yaml`: `version`, `methodology_version`,
   `geography.description` (what the location code represents; the site apart), `system_model`,
   `technology_level`, `classification` (ISIC Rev.4, CPC 2.1), `modelling.principle`, `review`
   (`unreviewed` when none was made: never invent a review), `data_generator`, and
   `allocation.deviation` when the allocation departs from the library hierarchy. cheme fills
   the uuid, time period, `valid_until`, production volume and multi-functionality. Read
   `cheme.lca-dataset-undocumented`; the gate requirement `lci-documented` checks the
   publication minimum. A v1 dataset (`schema: cheme/lca/v1`) still loads with a warning:
   `cheme migrate --write` rewrites a hand-written one.

11. **Wastes and end of life** (pre-release issue 180). What goes in also comes out: give every replaced or
   charged consumable (adsorbent, catalyst) and the construction materials a `disposal:`
   (`kind: waste | recyclable`, `route`, its treatment background or `missing:`), classify
   waste outputs of the flowsheet with `treatment:`, and give `end_of_life:` entries `kind`
   and `route`. `recyclable` is material recycling or re-use only (a positive market value or
   an accepted scrap grade); burned waste, energy recovery included, is `kind: waste` linked
   to its incineration (`hazardous: true` for a hazardous one). Never put a recycling credit into a background with a negative factor: give it
   as `credit:` (any kind, e.g. the heat of an incineration), which counts only with
   `system_model: substitution` (the default is cutoff: no credits). Record what you leave out
   in `cutoff:` with its amount and reason; the 1 % criteria are an Atlas choice (ISO 14044
   gives no number). Never cut a precious- or critical-metal flow or a high-CF flow (N2O, SF6,
   HFCs, heavy metals). Read
   `cheme.lca-disposal` and `cheme.lca-cutoff-*`; the gate requirement `cutoff-criteria` checks
   them.

12. **Balances** (pre-release issue 174). Run `cheme assess lca --balance`: the dataset must close in mass,
   in each element and in carbon by origin (1 % for a simulated flowsheet, 5 % for a sourced
   screening dataset). An open balance means a missing purge, waste, by-product or free
   resource, or a wrong composition or origin: fix the flowsheet or the dataset, never widen
   the tolerance. A material exchange without a composition makes the balance not assessable:
   give it `composition:` (fractions with formulas, or elements, with the source) or a
   `balance_exclusion:` with the reason. Read `cheme.lci-mass-balance`,
   `cheme.lci-element-balance`, `cheme.lci-carbon-origin`; the gate requirements of the same
   names check them.
13. **Emissions the flowsheet does not carry** (pre-release issue 176). A fired heater, a flare, storage
   tanks, a wastewater outlet and equipment leaks emit what no stream holds (NOx, CO, PM,
   CH4/N2O, VOC, COD, N, P). Add `emission_estimates:` (method `combustion`,
   `equipment-leaks`, `storage-tank`, `flare`, `effluent` or `non-routine`; scope `equipment`,
   `stream` or `exchange`; parameters and factors). Take every factor from its source (a
   guidebook table, AP-42, the EPA leak protocol, a permit, a BAT-AEL) and record that source
   on the factor; never write a factor from memory, and never point at a packaged factor set
   (they are placeholders and refuse to run). Equipment leaks count the P&ID take-off and the
   equipment list for you; check `counts`, and give two leak estimates their own components.
   Give `lhv` and `density` with their unit, on the heating-value basis (net or gross) the
   factors' source uses. A flare lists its combustibles in `components:`. A fired reformer
   (the primary reformer of a steam-reforming route) is a combustion unit: estimate NOx, CO,
   CH4, N2O and PM from its fuel. What is negligible goes in `emission_exclusions:`
   with its reason (inert or cryogenic service). Read `cheme.lci-emissions-incomplete`,
   `cheme.lci-emission-*`; the gate requirement `lci-emissions-complete` checks them.

## Validation and failure handling

- `cheme validate` checks `lca/lca.yaml` and `lca/factors.yaml` against their schemas.
- Errors stop the LCA. Examples:
  - `lca-functional-unit`, `lca-coproduct`, `lca-allocation` (scope);
  - `lca-flow-invalid`, `lca-flow-mixed`, `lca-emission-components` (the flowsheet);
  - `lca-factor-unknown`, `lca-factor-unit`, `lca-activity-missing`, `lca-activity-unit`,
    `lca-brightway` (backgrounds).
  Fix the input they name; never work around them by mapping a flow `free`.
- `lca-link-compat` (warning): a `dataset:` background that may not stand in for its flow
  (another substance, phase, grade or lower pressure, allocation, or system model).
  Link a fitting dataset, or keep the link with a `proxy:` that says why.
- `lca-map-refused`, `lca-map-key` (`cheme assess lca-map --apply`): nothing was written; choose
  another candidate or map the exchange by hand.
- `cheme assess lca --check` exits 1 when the written files are stale: rewrite them, never
  edit them.
- A flow you cannot map yet stays unmapped: a gap in every category (`lca/gaps.csv`),
  excluded from the totals, and the result is partial. Record the gap and its likely
  sensitivity (what it would add at a plausible factor) in `DESIGN.md`.
- `lca-geography`, `lca-reference-year`, `lca-method-mix` warn that factors do not fit the
  study's location, year or one characterisation method: the result is screening.

## Outputs and provenance

- `lca/inventory.csv`: each flow with its phase, the plant's amount, the quantity per
  functional unit, its provenance (given, calculated, estimated, assumed: the weakest value used) and its
  mapping.
- `lca/results.csv` and `lca/results.md`: impacts per scenario, category, phase and
  contributor, with the factor's status, source and year, or the Brightway activity.
- `lca/gaps.csv`: every exchange and category without a burden, with its quantity.
- `lca/manifest.json`: what the results rest on (inputs, mappings, background versions,
  methods, settings, software) and their class and publication policy; a change to any of
  them makes the gate's `lca-current` fail.
- `lca/dataset.yaml`: the plant's unallocated LCI dataset (foreground scope, per hour): what
  a process library keeps and other studies reference. Give `rights:` (its own data's terms),
  `location`, `year` and `technology` in `lca/lca.yaml`, and its documentation under
  `dataset:` (step 10).
- `--json` adds the findings and the source revision (git commit, fingerprints of the files
  read).

## Required human judgment

The goal, the functional unit, the system boundary, the allocation method, the choice of
background datasets and scenarios, and the interpretation are the LCA practitioner's decisions
(ISO 14044). An agent may assemble the inventory, propose mappings with their sources, run the
calculation, check plausibility and draft the interpretation. It does not choose the
allocation or the datasets without saying so, never presents example factors as results, and
never signs off. A comparative assertion disclosed to the public needs a critical review (ISO
14044 section 6); say so when the goal implies one.

## References

- `cheme schema lca`, `cheme schema lca_factors`, `lca/README.md`,
  `docs/framework/lca.md` (calculation, Brightway, ecoinvent and premise set-up)
- ISO 14040:2006 and ISO 14044:2006 (principles, requirements, allocation hierarchy)
- skills `process-design` (energy streams, cases), `mto-estimate` (take-off), `review`
