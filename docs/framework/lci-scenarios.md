# ADR: design cases and regional LCI scenarios without duplicating plants

Status: accepted. Code: `domains/assessment/lca/scenarios.py`, the `Scenario` model
of `lca/lca.yaml`, the `Case` model of `process/flowsheet.yaml`. Commands:
`cheme assess lca-scenarios`, `cheme assess lca-cases`.

## Context

A process design (e.g. the process library's 500 t/d GOX air separation unit) should be
usable for several operating cases and several geographical backgrounds without copying the
engineering project, and without presenting an unvalidated capacity or a swapped grid factor
as a new plant. Four things must stay apart:

1. the **technology/configuration** (which physical process);
2. the **design or operating case** (capacity, specifications, operating point: which
   foreground inventory is valid);
3. the **background scenario** (region, year, electricity procurement, background data: how
   the foreground is contextualised);
4. **evidence**: the calculation maturity and design maturity of the design and model, and
   separately the coverage, provenance and review of the inventory. A region swap never raises
   the calculation maturity or the design maturity.

## What already existed

| concept | existing entity |
|---|---|
| reference design / technology | the plant repository; `lca.yaml technology`; `lci_dataset` `id`, `technology`; the process library's `process.yaml` |
| design / operating case | the flowsheet's `cases:` (stream states per case); `lca.yaml case` picks one |
| unallocated foreground | `lca/dataset.yaml` (`kind: lci_dataset`, per 1 h of operation), derived by `inventory.py` |
| background scenario | `lca.yaml scenarios:`: factor ids (`factors:`) or Brightway databases (`databases:`) replaced |
| functional unit, multi-output | `functional_unit`, `allocation.py` (allocation applied after the unallocated dataset) |
| coverage | gaps (never zeros), `missing:` mappings, classification, geography and year checks |
| staleness, publication | `lca/manifest.json` fingerprints; the source registry and publication policy |
| maturity | `cheme maturity` (design deliverables), independent of the LCA |

So no new top-level `technologies/` or `scenarios/` entity is needed. The design case is a
flowsheet case; the regional scenario is an `lca.yaml` scenario. What was missing was metadata
and a per-scenario output.

## Decision

**Additive optional fields, existing files.** No field is required; existing `process.yaml`,
`flowsheet.yaml`, `lca.yaml` and `lci_dataset` files load and compute as before.

On a flowsheet case (`process/flowsheet.yaml cases:`):

| field | meaning | unset |
|---|---|---|
| `capacity` | the declared capacity of the case, e.g. `500 t/d GOX` | not declared |
| `provenance` | `given`, `calculated`, `assumed` or `extrapolated` | not declared |
| `applicability` | `{range, source, limitations}`: an envelope with its source, not a scaling law | none claimed |
| `source` | what the operating point rests on | — |

On a scenario (`lca/lca.yaml scenarios:`), besides `id`, `title`, `factors`, `databases`,
`source`:

| field | meaning | unset |
|---|---|---|
| `location` | the geography the background represents: makes it a **regional** scenario, checked against this geography | the study's location; former behaviour |
| `year` | the background's reference year | the study's year |
| `electricity` | `grid-average`, `residual-mix`, `contractual` (needs `source`: the instrument), `on-site` | not stated |
| `case` | a separately computed flowsheet case: the foreground changes with it | the study's case: foreground unchanged |
| `missing` | flow key (globs) -> why no background of this region exists: a gap with its quantity | — |
| `proxy` | flow key (globs) -> why the background stands in for this region: marked `PROXY` | — |

Rules:

- A regional scenario's contributions are checked against its own geography and year
  (`cheme.lca-scenario-geography`, `-year`, info `-unchecked`). A background kept from the
  baseline (the ASU's UK grid in an NL scenario) is named in a warning, never relabelled. The
  baseline mapping's `proxy:` note describes the baseline's geography: in a regional scenario
  it does not silence the check, and a background the scenario replaces is judged by its own
  status. Only the scenario's own `proxy:` declaration discloses a foreign background.
- A scenario that cannot find a regional background declares it `missing`: the exchange stays
  in the inventory with its quantity and is a gap. A replacement factor that does not exist is
  an error. Nothing falls back silently to another region or to zero.
- A physical change (ambient temperature, cooling, compressor work, capacity) needs its own
  computed flowsheet case. A scenario naming `case:` is a **design-case** scenario; one without
  is a **background sensitivity** whose foreground is the baseline's. Nothing scales a design
  to a capacity it was not computed for; `cheme assess lca-cases` only sets existing cases side
  by side, and a case marked `extrapolated` is labelled as not predictive.
- Scenarios without `location` behave exactly as before (including the mapping's proxy marker).

**One record per scenario.** `cheme assess lca-scenarios --write` writes
`lca/scenarios/<scenario>.json` (schema `cheme/lca-scenario/v1`) for the baseline and every
scenario; scenarios never overwrite each other. A record holds:

- `id`: `<dataset id>/<case>/<scenario>`, stable while the plant's flowsheet title, the case id
  and the scenario id are; `scenario` (kind `baseline`, `background` or `design-case`,
  geography, year, electricity, source, the replacements, `missing`, `proxy`); `process`
  (dataset id, title, technology); `design_case` (capacity, provenance, applicability,
  `extrapolated`);
- three layers, each labelled `layer`:
  - `foreground` (`foreground`): every exchange of the unallocated dataset in its basis
    (`1 h of operation`), its `relation` to the baseline (`baseline`, `unchanged`,
    `design-case`) and a fingerprint of the exchanges;
  - `linked_inventory` (`linked-inventory`): each non-product exchange with its quantity and
    unit, its background in this scenario and the baseline's mapping, whether the scenario
    replaced it, geography, year, status, `source_id` and `state` (`linked`, `proxy`,
    `missing`, `unmapped`, `free`, `released`, `gap`, `partial`), and `data_year` where the
    factor declares one;
  - `impacts` (`characterized-impact`): per functional unit (`functional_unit`: product,
    amount, unit, `reference_amount` `{value, unit}` in the reference product's unit, and `kg`,
    the same in kg, which is `null` for an energy product such as exported electricity or
    steam), with the allocation method and shares, the categories, totals, classification and reasons, and `comparable`/`dropped`
    (`dropped_by_category`): the exchanges the baseline characterises that are gaps in this
    scenario. A category's total is `null` when such an exchange is missing or when all its
    contributions are gaps: a total without the electricity is not a lower footprint, and a
    category with no data is not zero. Otherwise a total follows core's convention: it excludes
    the gaps, which are listed with their quantities, and `partial_categories` names the
    categories where that is so. `characterised_sum` keeps the sum of what was
    characterised, gaps excluded, for analysis only. `comparable` covers the gaps only; whether
    the backgrounds measure the same thing is `comparability` below;
- `comparability` ([lci-comparison-basis.md](lci-comparison-basis.md)): `verdict`
  (`baseline`, `like-for-like`, `proxy`, `not comparable`), `reasons` and `compared` (each
  replaced background pair with its differing or undeclared dimensions), and each linked
  exchange's `scope` (null: not declared). A scenario can be `comparable` (no gap) and still
  `not comparable` on its verdict, e.g. a direct-emission grid factor against a life-cycle one;
- `gaps`, `notes`, `warnings` (the scenario's own: its characterisation and, for a design-case
  scenario, its own case's inventory; never another scenario's; and the study's general ones,
  such as the flowsheet's boundary check `cheme.boundary-*`), `publication` (the scenario's own policy) and `inputs` (the run
  manifest's file fingerprints, mapping hash, background profiles and sources, software, and a
  hash of the scenario definition). No time, commit or absolute path: a rerun gives the same
  file, and `--check` fails when an input, a factor, a profile, a database identity or the
  software changes, or when a record's scenario was removed from `lca.yaml` (`--write` deletes
  such a record).

The record keeps the per-hour foreground and the per-functional-unit impacts apart: an
unallocated per-hour inventory is not a kg-oxygen footprint. Allocation stays the study's
choice (`allocation:`) and is stated where it is applied.

The same rule applies outside the records. `results.md` shows such a scenario's cell as "not
comparable (no background for ...)", or "no total" when every contribution is a gap, and
marks a total "(not comparable)" when the scenario's verdict is `not comparable`.
`cheme assess lca --json` and `GET /api/lca` add `not_comparable`: for each scenario and
category, the dropped exchange keys, or null. `results.csv` keeps its numeric rows, with the
gaps in `gaps.csv`. `cheme export-static` withholds `lca/scenarios/**` together with the other
LCA result files whenever the results may not be published.

## Why this avoids duplication

The engineering sources (P&IDs, flowsheet, design basis) exist once. A regional background is
a few lines in `lca.yaml` and, where needed, factors in `lca/factors.yaml`; a different
operating point is a flowsheet case of the same project. Consumers (the process library, the
Process Atlas, Brightway jobs) read the records; no folder is copied per region or capacity.

## Consequences and limits

- `cheme assess lca-scenarios` is separate from `cheme assess lca --write`, so projects with
  former scenarios gain no new outputs and their `lca-current` gates stay as they are. Projects
  that publish scenarios commit `lca/scenarios/*.json` and check them with `--check`.
- The packaged open data are UK (DESNZ). Regional factors for other countries must come from
  the project with their source and licence; until then a scenario declares `missing` or
  `proxy`. The core test fixture uses synthetic NL/DE factors, marked synthetic.
- Findings of the shared dataset resolver (`dataset:` backgrounds) are not yet tagged per
  scenario and appear in every record.
- With backend brightway, the records name activities and replaced databases; the per-exchange
  geography is what the activity mapping gives.
- Not done here: a scale-up model, a capacity optimiser, a facility registry. A specific
  facility (coordinates, measured data) is not modelled: `location` is background
  applicability, not a site.

## Example

```yaml
# lca/lca.yaml
scenarios:
  - id: nl-grid-2025
    title: Netherlands grid average 2025
    location: NL
    year: 2025
    electricity: grid-average
    factors: {"desnz-ghg-2026:electricity-gb": electricity-nl}
    missing: {"product:CW": "no NL cooling water factor yet"}
    source: "<the published NL grid factor and its licence>"
  - id: hot-climate
    case: hot          # a computed flowsheet case, not a scaled one
    source: "flowsheet case hot: 40 C ambient"
```

```sh
cheme assess lca-scenarios                 # summary per scenario
cheme assess lca-scenarios nl-grid-2025 --json
cheme assess lca-scenarios --write         # lca/scenarios/<id>.json
cheme assess lca-scenarios --check         # exit 1 when a record is stale
cheme assess lca-cases                     # existing cases side by side, per unit of product
```

The fixture `tests/data/lca-scenarios-asu` shows all of it on an ASU-like plant.

## Publishing from the process library

The process library's catalog builder reads `lca/scenarios/*.json` of each process and exports
the design case, the scenarios and their evidence; `--public` keeps only records whose
`publication.publishable` is true and withholds the impact numbers of the others (geography,
year, states and gaps stay, since they hold no restricted numbers).
