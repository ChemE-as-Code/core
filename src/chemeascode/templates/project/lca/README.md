# LCA

The life cycle assessment of the plant's operation (ISO 14040/44), per functional unit.

| file | what | written by |
|---|---|---|
| `lca.yaml` | goal and scope: the functional unit (a product of `process/flowsheet.yaml`), the case, the allocation between co-products, the impact categories, and the background of every feed, product and emitted component (`cheme schema lca`) | people; `cheme init` writes none, since the flowsheet has no products yet |
| `factors.yaml` | the project's characterised factors per kg, t, kWh, MJ, ... of a flow, one value per impact category, each with status, source, year, geography and its `sources:` registry entry (licence, publication policy); `include:` adds packaged open profiles (docs/framework/lca.md of cheme-as-code lists them) | people; the file `cheme init` writes includes the open profile `desnz-ghg-2026` (UK DESNZ 2026, OGL-3.0): a screening carbon footprint |
| `inventory.csv` | the foreground inventory per functional unit: feeds and products of the flowsheet (kg, energy in kWh), emissions by component, co-products | `cheme assess lca --write` |
| `results.csv`, `results.md` | impacts per category, with the contribution of each flow | `cheme assess lca --write` |
| `gaps.csv` | every exchange and category without a burden (unmapped, a factor without the category, an emission the method does not characterise, an unlinked exchange of a referenced dataset): excluded from the totals, never 0 | `cheme assess lca --write` |
| `manifest.json` | what the results rest on (inputs, mappings, background versions, methods, settings, software), their class and publication policy | `cheme assess lca --write` |
| `dataset.yaml` | the plant's unallocated LCI dataset (`kind: lci_dataset`, per hour of operation): what other studies and a process library reference (`dataset: {path, product, allocation}`) | `cheme assess lca --write` |
| `datasets/*.yaml` | LCI datasets of other processes, written by hand or copied from a library, used as backgrounds | people |

A minimal `lca.yaml`:

```yaml
schema: cheme/lca/v1
kind: lca
goal: Carbon footprint of the product for the concept comparison (DESIGN.md D-0xx)
functional_unit: {product: PROD, amount: 1, unit: t}
allocation: {method: exergy, coproducts: [PROD, BYPROD], source: "DESIGN.md D-0xx"}  # mass, economic, energy, exergy, shares, substitution, none
flows:
  - {key: feed:AIR, free: true, source: "ambient air, a resource without burden"}
  - {key: feed:POWER, factor: desnz-ghg-2026:electricity-gb, source: "grid supply at the site", proxy: "UK grid for a site outside the UK"}
  - {key: product:VENT, emission: true, source: "released to the atmosphere"}
  - {key: emission:CO2, elementary: {compartment: air, origin: fossil}, source: "fossil CO2 from the reformer"}
```

Before `lca/dataset.yaml` is published (a process library, the Atlas), document it under
`dataset:` (`cheme schema lca`; the gate requirement `lci-documented` checks the minimum):

```yaml
dataset:
  version: 1.0.0
  geography: {description: "One design for a generic coastal site; UK grid as a proxy"}
  system_model: cutoff
  technology_level: current
  classification: {isic: "<class>", cpc: "<subclass>"}  # ISIC Rev.4, CPC Ver. 2.1 (UNSD)
  modelling: {principle: attributional}
  review: unreviewed
  data_generator: "<who modelled it>"
```

The construction phase counts the take-off (`estimate/mto.csv`) and the equipment weights,
spread over the plant's life:

```yaml
operation: {hours_per_year: 8000, life_years: 20, source: "design basis"}
construction:
  - {id: steel, takeoff: mto, category: steel, factor: steel-sections, source: "rack and structure steel"}
  - {id: vessels, takeoff: equipment, equipment: {material: "*SS*"}, factor: stainless-steel, source: "empty weights"}
```

Supplies the flowsheet and the take-off do not hold: `consumables` (e.g. an adsorbent
replaced every 5 years), `maintenance` (a yearly fraction of the construction), `transport`
(t*km of matched exchanges) and `end_of_life` (treatment or recycling of the construction
mass). What goes in also comes out: give a replaced consumable and a construction material a
`disposal:`, and classify waste outputs of the flowsheet with `treatment:`. Under the default
`system_model: cutoff` a recyclable (material recycling or re-use; burned waste is a `waste`
linked to its incineration) leaves burden-free and earns no credit:

```yaml
consumables:
  - id: sieve
    unit: t
    per_replacement: 36
    every_years: 6
    missing: "no open factor for 13X molecular sieve"
    source: "two beds replaced every 6 years (ASSUMED)"
    disposal: {kind: waste, route: landfill, missing: "no open landfill factor", source: "spent sieve, inert"}
cutoff:
  - {id: packaging, per_year: 500, unit: kg, reason: "pallets and bags, below 0.1 % of the input mass"}
```

With a Brightway project (ecoinvent or an open database, `pip install 'cheme-as-code[lca]'`), set
`backend: brightway` and give the flows an `activity:` (`cheme assess lca-search` finds
them; `cheme assess lca-map` lists candidates for every open exchange and `--apply` writes the
approved ones). `scenarios:` compare the baseline with other factors or databases (e.g. premise 2050).
See the skill `lca`.

Never edit `inventory.csv` or `results.*` by hand: change the flowsheet, `lca.yaml` or
`factors.yaml`, then rewrite them. Energy streams (`kind: energy`, with `duty`) from an energy
feed (electric power, steam) or to an energy product (cooling water) are counted in kWh. The
gate `kind: lca` (`checks/checks.yaml`, require `mapped`, `factors`, `no-gaps`, `factors-published`, `publishable`, `cutoff-criteria`, `lci-emissions-complete`, `lci-mass-balance`, `lci-element-balance`, `lci-carbon-origin`, `lca-current`)
checks the mapping is complete, the factors are the project's, no exchange is a gap, every
exchange rests on published factors (no example, `ASSUMED`, `PROXY` or `ESTIMATE`), the
results may be published under their sources' terms, every combustion unit, tank and
untreated wastewater outlet has an emission estimate or a declared exclusion
(`emission_estimates:`, `emission_exclusions:`), the dataset closes in mass, elements and
carbon by origin (`cheme assess lca --balance`), and the outputs are current.

`results.md` says what the result is: **complete** within the declared boundary (every exchange
characterised in every category with published or declared data; not a validation),
**screening** (example, assumed, proxy or estimated factors, climate categories only, or another
geography, reference year or characterisation method), **partial** (gaps), or **unavailable**.
Climate categories alone are a screening carbon footprint, never a full LCA.
`cheme assess lca --coverage` prints the classification, its reasons, the gaps, the sources
and what the boundary leaves out. `cheme assess lca --dataset` exports the unallocated
foreground without factors, a Brightway project or credentials.

Licensed databases (ecoinvent and others) must not be copied into this repository: they
live in a local Brightway project. Give each factor its registry entry (`source_id` ->
`sources:` with provider, exact version, licence, attribution and `publication: public |
restricted | local`). The registry records terms; it does not grant rights: free access alone
does not make results publishable.
