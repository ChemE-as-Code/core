# Tiered LCI estimates

A database "for all industrial processes" needs datasets for processes that have no flowsheet
yet. `cheme assess lci-estimate` builds a screening LCI dataset (`kind: lci_dataset`) from the
reaction stoichiometry, a yield and a set of sourced defaults, and labels it with its tier
(pre-release issue 182). The established screening approaches are the reference: Hischier et al. (2005, Int J
LCA 10:59) and the ecoinvent chemicals report (Althaus et al. 2007, ecoinvent report No. 8);
Parvatker and Eckelman (2019, ACS Sustain. Chem. Eng. 7:350) compare such methods.

| tier | what the numbers are | how | caps |
|---|---|---|---|
| 0 | stoichiometric | reactions, a yield (95 % by default), losses and energy from defaults | calculation maturity `sourced`, pedigree floor `[4, 4, 3, 3, 4]` (DQR bound for floored exchanges: >= 3.33; the typical Tier 0 default scores about 4.67) |
| 1 | sourced conceptual | yield, electricity and heat (and any further exchange) from open literature, patents or BREFs, each with its source | calculation maturity `sourced`, pedigree floor `[3, 4, 3, 3, 3]` (DQR bound for floored exchanges: >= 3.0) |
| 2+ | the flowsheet | `cheme assess lca` from `process/flowsheet.yaml` and its simulation | none from the tier |

A dataset without `generation` is a flowsheet-derived (Tier 2+) or hand-written dataset.

## The estimate

`lca/estimate.yaml` (`cheme schema lci_estimate`) names the reactions of
`process/reactions.yaml` and the reference product, a component of `process/materials.yaml`
whose formulas give the molar masses:

```yaml
schema: cheme/lci_estimate/v1
kind: lci_estimate
id: ethylene-oxide-t0
tier: 0
product: EO
reactions: [EPOX, BURN]          # several reactions: key and selectivity fix the extents
key: C2H4
selectivity: {EO: 0.8, CO2: 0.4}  # kmol per kmol of C2H4 converted
byproducts:                       # every product of the reactions besides the reference one
  CO2: {fate: air}
  H2O: {fate: wastewater}
location: GLO
year: 2026
# Tier 1 (or a Tier 0 that knows better): a value with its source replaces the default
# yield: {value: 0.97, source: "<publication, table>"}
# electricity: {value: 0.15, source: "..."}     # kWh per kg of product
# heat: {value: 1.1, source: "..."}             # kWh per kg of product
# losses: {fate: {C2H4: air}, reason: "a gas: vented, not drained"}
# exchanges: [{key: input:catalyst, type: input, amount: 1e-5, unit: kg, source: "..."}]
# documentation: {version: 1.0.0, review: unreviewed, rights: CC-BY-4.0, ...}
```

```sh
cheme assess lci-estimate                  # the dataset as YAML
cheme assess lci-estimate --write          # lca/datasets/<id>.yaml (or output:)
cheme assess lci-estimate --check          # exit 1 when the written dataset is not current
cheme assess lci-estimate --compare        # against the repository's flowsheet, per kg
cheme assess lci-estimate --json           # dataset, balance, findings, source revision
```

Python: `chemeascode.domains.assessment.lca.estimate.lci_estimate(root, path)` returns the
dataset, its element balance, the findings and the source revision.

## How the dataset is built

Per kg of the reference product (`basis: 1 kg of <product>`):

1. **Reactants.** The reactions' net consumption per kg of product, divided by the efficiency
   over the whole scheme (`yield`, default 0.95: "an efficiency of 95% is assumed" over the
   entire stoichiometric equation, Hischier et al. 2005, section 2.3). With several reactions,
   `selectivity_extents` solves the extents from the selectivities. The selectivities need a
   source (`selectivity_source: {source: ..., source_id: ...}`): Tier 1 with several reactions
   requires it. Without one (Tier 0) every amount that depends on them (the reactants, the
   by-products) is `assumed` with the default poor pedigree, not `calculated`.
2. **By-products.** Every product of the scheme other than the reference product needs a fate:
   `coproduct` (a product exchange, with `properties` for allocation), `air` or `water` (an
   emission with its elementary flow identity from the packaged crosswalk), `wastewater` or
   `waste` (a technosphere output to treatment). No default fate: the estimate names them.
3. **Unconverted input.** For each reactant, an air share of 0.2 % of its input mass (Hischier et
   al. 2005) and the rest to water. By default the rest goes to **wastewater treatment** (an
   output), since the library's cut-off system model keeps treatment without recovery in the
   producer's system; `losses.water: water` makes it a direct emission, as Hischier et al.
   calculate it. Solid waste: 0 (omitted, as there). `losses.fate` sends a component's whole
   loss elsewhere (a gas that is purged), with its reason. Where the default split routes a
   component to wastewater without an explicit fate (`losses.fate`, or `losses.water` set), the
   estimate warns with `cheme.lci-loss-split`: for a component that is a gas at ambient
   conditions (`normal_boiling_point` below 298.15 K in `process/materials.yaml`) and for one
   whose boiling point is not given; a known liquid or solid is not flagged. The hint names
   `losses.fate`.
4. **Energy.** Electricity and heat per kg: the estimate's sourced values (not negative), else
   the site averages of the defaults. The heat is a heat flow in kWh (carrier `heat`), the
   heat that fossil fuel generates for preheating and distillation (Hischier et al. 2005,
   p. 61), not a fuel input; the exchange says so in its title and carrier `source`.
5. **Documentation.** A uuid stable across versions (uuid5 of `estimate/<id>`), system model
   cut-off, attributional, the system boundary (infrastructure, transport and catalysts
   excluded unless given), the time period and `valid_until` from the year (reference year + 5; a Tier 0 estimate on
   the energy defaults says in its description that these date from 2000, beyond the 10-year
   limit for secondary data, and that `valid_until` does not endorse them); the estimate's
   `documentation:` overrides and completes it.
6. **Data quality.** Each default exchange takes the pedigree its default gives; the others the
   rule `cheme default pedigree v1`; none is better than the tier's floor (see below).
7. **Element balance.** Mandatory. The dataset records the formula of each material exchange's
   component (`generation.formulas`) and the balance of every element (`generation.balance`).
   A dataset whose elements do not close is not written (`cheme.lci-unbalanced`): an
   unbalanced reaction or a by-product without its formula is caught here. A mass exchange of
   a Tier 1 estimate without a component (a catalyst) stays outside the balance
   (`generation.balance.outside`), so a closed balance says nothing about it: the warning
   `cheme.lci-mass-outside-balance` names it.

`generation` records it:

```yaml
generation:
  tier: 0
  method: stoichiometric screening (Hischier et al. 2005; Althaus et al. 2007)
  defaults: cheme tier-defaults 1.0.0
  defaults_used: [yield, loss-air, loss-water, loss-waste, electricity, heat]
  spec: lca/estimate.yaml
  maturity_cap: sourced
  pedigree_floor: [4, 4, 3, 3, 4]
  dqr_floor: 3.3333
  components: {feed:N2: N2, ...}
  formulas: {feed:N2: N2, ...}
  balance: {closed: true, tolerance: 1.0e-06, elements: {H: [0.1869, 0.1869], N: [...]}}
```

Every exchange that takes a default is `provenance: assumed`, origin `design-rule`, and its
`source` cites the rule (`cheme tier-defaults 1.0.0: <name>`, with `[ASSUMED]` where the
number is not confirmed) and the publication. A reactant amount computed with the default
yield counts as a default exchange.

## The defaults

`src/chemeascode/domains/assessment/lca/data/tier-defaults.yaml`, versioned (`version`): a
change of a value bumps it, and every dataset records the version it was built with. Each value
states its source and `status`: `confirmed` when the number was read in the cited publication
(`checked` says where and when), `ASSUMED` when it is the approach's commonly quoted number,
attributed to the source but not read in it (no open copy prints it).

| default | value | status | source |
|---|---|---|---|
| `yield` | 0.95 (efficiency over the scheme) | confirmed | Hischier et al. 2005, section 2.3 |
| `loss-air` | 0.002 of the input mass | confirmed | Hischier et al. 2005, section 2.3 |
| `loss-water` | the rest of the unconverted input | confirmed | Hischier et al. 2005, section 2.3 (routed to wastewater treatment by default) |
| `loss-waste` | 0 | confirmed | Hischier et al. 2005, section 2.3 (solid wastes omitted) |
| `electricity` | 0.3333 kWh (1.2 MJ) per kg | **ASSUMED** | attributed to the Gendorf (2000) site average that the ecoinvent v2-era proxies used; not read in Hischier et al. 2005 or Althaus et al. 2007 |
| `heat` | 0.5556 kWh (2.0 MJ) per kg, from fossil fuel | **ASSUMED** | as electricity |
| `infrastructure` | 4e-10 units of a generic organics plant per kg | confirmed, not applied | Hischier et al. 2005, section 2.3 (p. 61) |
| `transport-lorry`, `transport-train` | 100 km lorry, 600 km train per input, within Europe | confirmed, not applied | Hischier et al. 2005, section 2.1 (p. 60), after Frischknecht et al. 2004 (HCl: 200 km by train only) |

The open version of Hischier et al. (2005, p. 61) confirms that the energy and water defaults
are averages of the Gendorf site's environmental report (Werk Gendorf 2000) but does not print
the numbers, and no open copy of ecoinvent report No. 8 was found: the 1.2 MJ electricity and
2 MJ heat per kg are ASSUMED until someone checks them against the report. They are the 2000
site averages that the ecoinvent v2-era chemicals proxies used; newer ecoinvent proxies rest on
later Gendorf reports, so these values may be low for a present-day process, and the temporal
pedigree stays poor. A site average says little about one process: a Tier 1 value from a
source is always better. The yield, air share, water difference, omitted solid waste and
infrastructure are on p. 61; the 95 % efficiency is also applied in Althaus et al. 2007
(ecoinvent report No. 8), which was not read directly.

**What is not estimated.** The approach also gives standard transport distances (p. 60: 100 km
lorry and 600 km train within Europe for basic chemicals, after Frischknecht et al. 2004) and
a water consumption from the Gendorf report. The distances are confirmed and recorded in the
defaults, but not applied: the generator builds no transport exchanges, and the system
boundary states transport as excluded. Plant infrastructure is excluded likewise (the library
includes it only when a design provides it). **Cooling water** and process water are not
estimated, which biases the inventory low. As in ecoinvent (stated on p. 61 for the APME data
as the overall methodology), air, N2 and O2 are not inventoried as resources: the generator
does not add any such resource exchange; a reactant among them is an input `feed:<id>` because
the element balance needs it, and its unconverted share is an emission to air or a loss as
any other component.

The pedigrees in the file are cheme's convention (ASSUMED): defaults score reliability 4 (a
qualified estimate), completeness 5 (representativeness unknown), temporal 5 (data of 2000 or a
rule from 2005), geographical 4 or 5 and technological 4 or 5 (a site average or a generic
rule, not the technology).

## The caps

- **Calculation and design maturity.** `generation.maturity_cap` (calculation maturity) is
  `sourced` for Tiers 0 and 1: the level `balanced` needs a balanced conceptual PFD, which is
  the flowsheet path. The schema refuses a Tier 0 or 1 dataset claiming more, and a library
  manifest (`process.yaml`) whose `maturity` (design maturity) is above `concept` next to a
  Tier 0 or 1 dataset fails `cheme.lci-tier-maturity`, both in `cheme assess lci-estimate` and
  when a study reads the dataset. This applies to a repository without
  `process/flowsheet.yaml`, whose manifest describes the process by its datasets. With a
  flowsheet the manifest's design maturity rests on the design (`cheme maturity`), and a
  screening dataset that the study reads as a background does not cap it.
- **Data quality.** `pedigree_floor`, the best scores any exchange may have: Tier 0
  `[4, 4, 3, 3, 4]`, Tier 1 `[3, 4, 3, 3, 3]` (cheme's convention, ASSUMED). The default
  pedigree rule applies it to a generated dataset's exchanges, so the TfS DQR is never better
  than `dqr_floor`, the mean of the floor's temporal, geographical and technological scores.
  A pedigree set by hand below the floor fails `cheme.lci-tier-quality`.

`tier_findings` checks a generated dataset whenever a study reads it as a background: the
balance (`cheme.lci-unbalanced`), a default exchange not assumed or not listed
(`cheme.lci-default-not-assumed`, `cheme.lci-default-unlisted`), the floor and the design
maturity,
plus, for a Tier 0 or 1 dataset, an info `cheme.lci-tier` that the study rests on a screening
estimate. `lci_estimate` itself adds the warning `cheme.lci-loss-split` (see step 3).

## Validation against a full design

`cheme assess lci-estimate --compare` (`compare_with_design`) compares an estimate with the
repository's flowsheet, per kg of the product: each reactant fed, the unconverted input that
leaves (summed over its fates against the design's other product terminals), and electricity
and heat where the design has energy terminals. Only input terminals naming electricity or
power, or heat, steam, fired heat or fuel, count as a supply; cooling and heat rejection,
exported energy and terminals of another name are listed as not compared
(`design_energy`, tested on a synthetic set of terminals).

core has one full design that makes a pure product by reaction, `examples/process-ammonia`
(the synthesis loop; the other reacting example, `process-shift`, sends a mixed gas onward).
A Tier 0 estimate of `NH3_SYN`, with the purged gases sent to air
(`tests/test_lci_estimate.py`):

| quantity per kg NH3 | Tier 0 | design | error |
|---|---|---|---|
| N2 fed | 0.8657 kg | 0.9130 kg | -5.2 % |
| H2 fed | 0.1869 kg | 0.1971 kg | -5.2 % |
| N2 lost (purge) | 0.0433 kg | 0.0906 kg | -52 % |
| H2 lost (purge) | 0.0093 kg | 0.0196 kg | -52 % |

The default efficiency (95 %) is close to the loop's (90 %): the reactants are 5 % low and the
losses half the design's. The design has no energy terminals, so the energy defaults are not
compared (the energy defaults are not validated against any design), and argon (an inert of the makeup gas) is not estimated. No impact category is
compared yet: the examples carry no background, and the ranges per impact need the library's
designs (ammonia, methanol) with a reference background.

## Where it sits

- `domains/process/screening_balance.py`: the stoichiometric balance per kg of product and
  the element masses (a balance belongs to `process`).
- `domains/assessment/lca/balance.py`: the element balance of a dataset, the minimal check
  behind an interface (`element_balance(dataset) -> ElementBalance`) that the balance gates of
  pre-release issue 174 replace.
- `domains/assessment/lca/estimate.py`: the estimate, the defaults, the tier checks and the
  comparison; `cheme assess lci-estimate` is its CLI.
