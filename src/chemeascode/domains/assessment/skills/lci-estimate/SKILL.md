---
name: lci-estimate
description: Screening LCI dataset for a process without a flowsheet - cheme assess lci-estimate (Tier 0 stoichiometric from process/reactions.yaml, a yield and the sourced defaults of Hischier et al. 2005; Tier 1 with yields, utilities and emissions taken from open literature, patents or BREFs), every default exchange assumed and cited, element balance mandatory, calculation maturity, design maturity and DQR capped by the tier. Use when a process must enter an LCI database or the Atlas before it has a design, when breadth is asked for, or when a stoichiometric or literature-based estimate is compared with a full design.
---

# Tiered LCI estimate

## Purpose and when to use

Give a process that has no flowsheet yet a balanced, labelled screening LCI dataset
(`kind: lci_dataset`) within hours: Tier 0 from the reaction stoichiometry and sourced
defaults, Tier 1 from values taken from sources. Use it for breadth (a library that needs many
processes), for a first look at a route before designing it, and to check an estimate against
a full design (`--compare`). Do not use it when a flowsheet exists: `cheme assess lca` (skill
`lca`) derives the dataset from the design (Tier 2 and up), and that always supersedes an
estimate.

## Required inputs and missing inputs

- `process/reactions.yaml` with the reactions of the route (skill `route-selection` chooses
  them) and `process/materials.yaml` with every component's `formula`: the molar masses come
  from the formulas, and the element balance needs them. Run `cheme validate` first; an
  unbalanced reaction makes the estimate refuse to write.
- The reference product (a component id) and, for several reactions, the key reactant and the
  selectivity to the products (kmol per kmol of the key converted), from a source
  (`selectivity_source`; required at Tier 1, else the dependent amounts are `assumed`).
- The fate of every by-product: `coproduct`, `air`, `water`, `wastewater` or `waste`. There is
  no default fate; ask the user or take it from the source, and say why in `reason`.
- Tier 1: the yield, electricity and heat per kg of product, each with its source (publication
  and table or page). Further exchanges (auxiliaries, catalysts, emissions) with sources.
- **Never fill in a number without a source.** A value nobody can cite stays the default (Tier
  0) or is left out and stated; do not make a Tier 1 out of numbers from memory.

## Workflow and tools

1. **Write `lca/estimate.yaml`** (`cheme schema lci_estimate`, docs/framework/lci-estimate.md):
   `id`, `tier`, `product`, `reactions`, `key` and `selectivity` when there are several,
   `byproducts`, `location` and `year`. Leave out what you have no source for: the defaults
   then apply and are labelled.
2. **Losses.** By default each reactant's unconverted input goes 0.2 % to air and the rest to
   wastewater treatment. A gas reactant is purged rather than drained: set
   `losses: {fate: {<component>: air}, reason: ...}`. Use `losses.water: water` only when the
   loss really is a direct emission (no treatment). The default split
   warns (`cheme.lci-loss-split`) for gases and components of unknown volatility.
3. **Run** `cheme assess lci-estimate` and read the findings: `cheme.lci-estimate` (a reaction
   that does not form the product, a by-product without a fate, selectivities that do not fix
   the extents), `cheme.lci-unbalanced` (the elements do not close: check the stoichiometry
   and the formulas). Read the dataset: every exchange marked `assumed` names its default rule
   in `source`; `[ASSUMED]` marks a default number not confirmed in its source.
4. **Document** under `documentation:` what cheme cannot derive (version, geography
   description, classification, review `unreviewed`, rights, data generator); cheme fills the
   uuid, system model (cut-off), modelling principle, boundary, time and `valid_until`.
5. **Write** `cheme assess lci-estimate --write` (`lca/datasets/<id>.yaml`) and commit it with
   the estimate. `--check` in CI keeps it current.
6. **Compare** with a design where one exists (`--compare` in a repository with a flowsheet of
   the same process): report the error per quantity and its range with the estimate.

## Validation and failure handling

- The element balance is mandatory: a dataset whose elements do not close is never written.
  Fix the reaction or the formula; never add a balancing exchange without a physical reason.
- `cheme.lci-tier-maturity`: the library manifest claims a design maturity above `concept` beside a Tier 0
  or 1 dataset. Lower the claim; reaching `balanced` needs a flowsheet.
- `cheme.lci-tier-quality`: a pedigree better than the tier's floor. The tier caps the data
  quality; a better rating needs better data (Tier 1, then a design).
- `cheme.lci-default-not-assumed`, `cheme.lci-default-unlisted`: the dataset was edited by
  hand. Change the estimate and regenerate; never edit the generated file.

## Outputs and provenance

- `lca/datasets/<id>.yaml`: the dataset per kg of product, with `generation: {tier, method,
  defaults, defaults_used, maturity_cap, pedigree_floor, dqr_floor, components, formulas,
  balance}` and `provenance.files` (sha256 of the estimate, reactions and materials).
- `--json`: the dataset, its balance, the findings and the source revision.
- Studies that read the dataset as a background get `cheme.lci-tier` (info): their results rest
  on a screening estimate.

## Required human judgment

The route, the fates of the by-products, whether a source's yield or energy applies to the
process, and whether a screening estimate is fit for the question are the engineer's and LCA
practitioner's decisions. An agent writes the estimate, cites each value, runs and compares,
and says plainly that the result is a Tier 0 or Tier 1 estimate. It never upgrades a tier by
inventing sources, never presents an estimate as a design, and never raises a manifest's
design maturity because a dataset exists.

## References

- docs/framework/lci-estimate.md (defaults, caps, validation), docs/framework/lca.md
- Hischier, R., Hellweg, S., Capello, C., Primas, A. (2005), Int J LCA 10(1) 59-67,
  doi:10.1065/lca2004.10.181.7 (section 2.3, the stoichiometric approach)
- Althaus, H.-J. et al. (2007), Life cycle inventories of chemicals, ecoinvent report No. 8
- Parvatker, A.G., Eckelman, M.J. (2019), ACS Sustain. Chem. Eng. 7:350 (methods compared)
- skills `lca`, `route-selection`
