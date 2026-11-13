# Architecture Decision Records

This directory records the architecturally significant decisions about **cheme-as-code
itself**: the package, the `cheme` CLI, its file formats and schemas, the agent interface
(commands, findings, skills) and its contracts with the other ChemE-as-Code repositories
(project-template, viewer, process-library). Each record says what was decided, why, what it
costs, and where the evidence is (pull request, commit, files).

**Not here: a plant's engineering decisions.** Why a plant uses a given column, material or
safeguard is recorded in that plant repository's `DESIGN.md`, as `D-NNN` entries, and cited
from values (`assumed` with a basis), `accept:` reasons and review records. An ADR is about the
software that checks plants; a `D-NNN` decision is about one plant. Do not mix the two.

The format is Michael Nygard's lightweight one (Title, Status, Context, Decision,
Consequences) with an added Evidence section. [ADR 0001](0001-record-architecture-decisions.md)
records the decision to keep these records.

## When to write one

A pull request that changes any of the following adds a new ADR, or supersedes an existing one,
in the same pull request:

- the architecture: layers, module ownership, import rules, a new integration boundary or
  out-of-process worker, base versus optional dependencies;
- a public file format or schema: a new file kind, a breaking schema version, fingerprint or id
  formats, rule-id conventions;
- the agent interface: how agents call the tool, finding format, skill distribution, an MCP or
  other adapter;
- a cross-repository contract: the `cheme serve` API or static snapshot format used by the
  viewer, the generated project template, what the process library relies on.

Bug fixes, new rules or commands inside an existing decision, and documentation need no ADR.

## How to add one

1. Copy [template.md](template.md) to `NNNN-kebab-title.md` with the next free number.
2. Fill in Context, Decision, Consequences (positive and negative, including known limitations)
   and Evidence. Keep it short; link the detailed docs rather than copying them.
3. Status `Accepted` when the pull request is merged (`Proposed` while under discussion).
4. To change an accepted decision, do not rewrite it: write a new ADR and set the old one's
   status to `Superseded by [NNNN](...)`. Typos and broken links may be fixed in place.
5. Add the record to the index below and to `nav` in `mkdocs.yml`.

## Index

ADRs 0002 to 0018 were written retroactively on 2026-10-25 from the repository's history
(0.1.0 to 0.8.0); the date is when the decision was taken according to git.

| ADR | Title | Status | Date |
|---|---|---|---|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions | Accepted | 2026-10-25 |
| [0002](0002-plant-data-as-plain-files-in-git.md) | Plant data as plain files in git, the single source of truth | Accepted | 2026-10-17 |
| [0003](0003-dexpi-xml-via-pydexpi-as-the-pid-format.md) | DEXPI 2.0.1 XML through pyDEXPI as the P&ID format, kept canonical for small diffs | Accepted | 2026-10-17 |
| [0004](0004-pin-pydexpi-by-git-commit.md) | Pin pyDEXPI as a git dependency by commit | Accepted | 2026-10-22 |
| [0005](0005-versioned-yaml-schemas-and-cheme-migrate.md) | Engineering YAML with versioned schemas, additive changes and `cheme migrate` | Accepted | 2026-10-19 |
| [0006](0006-findings-with-stable-ids-as-the-agent-interface.md) | Findings with `file:line`, rule id, hint and a stable id as the agent interface | Accepted | 2026-10-17 |
| [0007](0007-agents-edit-files-directly-no-mcp-server.md) | Agents edit files directly; the CLI, not an MCP server, is the tool interface | Accepted | 2026-10-17 |
| [0008](0008-skills-shipped-as-copies-into-plant-repositories.md) | Skills ship with the package and are installed as copies into plant repositories | Accepted | 2026-10-17 |
| [0009](0009-layered-package-with-enforced-import-rules.md) | One package in layers, foundation, domains, project, interfaces, with enforced imports | Accepted | 2026-10-21 |
| [0010](0010-deterministic-domains-no-llm-calls.md) | Deterministic engineering functions: no LLM or agent calls in the package | Accepted | 2026-10-21 |
| [0011](0011-per-value-provenance-and-fingerprints.md) | Per-value provenance (given/assumed/calculated) and sha256 fingerprints for staleness | Accepted | 2026-10-19 |
| [0012](0012-stages-gates-and-sign-offs-on-the-default-branch.md) | Stages, gates and sign-offs count only on the default branch, with no unapproved self-review | Accepted | 2026-10-18 |
| [0013](0013-calculation-maturity-separate-from-completeness-and-review.md) | Calculation maturity levels, with "unsupported" blocking, kept apart from completeness and review | Accepted | 2026-10-24 |
| [0014](0014-dwsim-as-an-out-of-process-simulation-worker.md) | DWSIM as an out-of-process simulation worker, and property methods claimed only where benchmarked | Accepted | 2026-10-22 |
| [0015](0015-optional-backends-and-licensed-data-not-shipped.md) | Brightway as an optional LCA backend; licensed third-party data is linked or fetched, never shipped | Accepted | 2026-10-22 |
| [0016](0016-read-only-serve-api-and-static-snapshots.md) | A read-only `cheme serve` API and static snapshots for the viewer | Accepted | 2026-10-17 |
| [0017](0017-project-template-generated-from-cheme-init.md) | The project-template repository is generated from `cheme init` by CI | Accepted | 2026-10-24 |
| [0018](0018-rename-plantcode-to-cheme-as-code-without-aliases.md) | Rename plantcode to cheme-as-code, and no compatibility aliases before 1.0 | Accepted | 2026-10-22 |
| [0019](0019-liquid-liquid-extraction-as-qualified-equilibrium-stages-outside-the-simulation.md) | Liquid-liquid extraction as qualified equilibrium stages, solved by core outside the simulation | Accepted | 2026-10-27 |
| [0020](0020-review-currency-ignores-digest-only-changes.md) | A review stays current through a change of nothing but full digests | Accepted | 2026-10-27 |
| [0021](0021-furnace-energy-basis-for-solid-reactions.md) | A furnace energy basis for high-temperature solid reactions from condensed-phase data, never a fluid flash | Proposed | 2026-10-27 |
| [0022](0022-iso-10628-symbol-library-and-pfd-symbols.md) | An ISO 10628-2 symbol library for the P&ID catalogue and the PFD steps | Accepted | 2026-10-27 |
| [0023](0023-electrochemical-cell-contract.md) | Electrochemical cells as a versioned contract with specified performance | Accepted | 2026-10-27 |
| [0024](0024-adsorber-performance-basis-outside-the-simulation.md) | Adsorber performance basis: an equilibrium TSA cycle and external results, outside the simulation | Accepted | 2026-10-27 |
| [0025](0025-solid-components-and-a-bounded-crystallizer-adapter.md) | Solids as components and a bounded crystallizer adapter outside the simulation | Accepted | 2026-10-27 |
| [0026](0026-petroleum-assays-as-versioned-pseudocomponents.md) | Petroleum assays characterised into versioned pseudocomponents, claimed only where benchmarked | Accepted | 2026-10-27 |
| [0027](0027-qualified-electrolyte-systems-through-pitzer-in-cantera.md) | Qualified electrolyte systems through Pitzer's equations in Cantera, refused everywhere else | Accepted | 2026-10-27 |
| [0028](0028-composition-limits-in-property-package-claims.md) | A property package claim may limit composition, per box and per pair | Accepted | 2026-10-27 |
| [0029](0029-run-records-per-run.md) | Run records per run in the plant repository, written by core | Proposed | 2026-10-27 |
| [0030](0030-conversion-reactors-checked-against-the-declared-conversion.md) | Conversion reactors checked against the declared conversion, an error beyond 0.001 | Accepted | 2026-10-27 |
| [0031](0031-one-glossary-and-qualified-maturity.md) | One glossary for the project name and the maturity, stage and review axes | Accepted | 2026-10-27 |
| [0032](0032-semantic-versioning-from-1-0-0.md) | Semantic versioning from 1.0.0 | Accepted | 2026-10-29 |
| [0033](0033-worker-iterates-tear-streams.md) | The DWSIM worker iterates the tear streams itself | Accepted | 2026-10-29 |
| [0034](0034-serve-library-mode.md) | `cheme serve` serves a folder of plants, each under its own prefix | Accepted | 2026-10-30 |
| [0035](0035-motor-cable-entry-beside-the-machine.md) | A motor's cable entry ends its tray beside the machine | Accepted | 2026-10-30 |
| [0036](0036-buried-lines-in-the-routing-intent.md) | Buried lines in the routing intent, with a cover rule instead of headroom | Accepted | 2026-10-30 |
| [0037](0037-several-power-trays-per-rack.md) | Several power trays per rack, by voltage class and fill | Accepted | 2026-10-30 |
| [0038](0038-stated-imbalance-of-specified-splits.md) | A specified split's energy imbalance is stated, and the plant closure takes it | Proposed | 2026-10-30 |
| [0039](0039-idaes-as-an-optional-second-simulation-backend.md) | IDAES as an optional second simulation backend, chosen in simulation.yaml | Proposed | 2026-10-31 |
| [0040](0040-pinch-targets-from-the-recorded-simulation-run.md) | Pinch targets from the recorded simulation run, every duty in one class and reconciled | Proposed | 2026-11-04 |
| [0041](0041-measured-electrochemical-performance-and-membrane-block.md) | Measured electrochemical performance from a processed series, and a membrane block | Accepted | 2026-11-06 |
| [0042](0042-watertap-and-idaes-not-reused-for-electrochemical-cells.md) | WaterTAP and IDAES are not reused for measured electrochemical cells | Accepted | 2026-11-06 |
| [0043](0043-dynamic-electrolysis-duties-and-anolyte-models.md) | Dynamic electrolysis duties with an anolyte model interface, on a concentration basis | Accepted | 2026-11-06 |
| [0044](0044-stack-sizing-and-skid-inputs-through-the-equipment-list.md) | Stack sizing in process/cells.yaml, skid equipment inputs through the equipment list | Accepted | 2026-11-06 |
| [0045](0045-a-design-case-lci-dataset-with-its-own-identity.md) | A design case's LCI dataset, generated with an identity that names the case | Accepted | 2026-11-06 |
| [0046](0046-pfd-drawn-as-an-engineering-sheet.md) | The PFD drawn as an engineering sheet: ISO frame, stream table, utility stubs, junctions | Proposed | 2026-11-05 |
| [0047](0047-valve-pipe-and-slant-drawing-rules-in-the-gate.md) | Lines through valves, along pipes and slanted lines are drawing findings the gate fails on | Proposed | 2026-11-05 |
| [0048](0048-generated-process-sheets-written-without-indentation.md) | Generated process sheets written without indentation | Proposed | 2026-11-05 |
| [0049](0049-off-page-connectors-on-the-sheet-edge-in-the-gate.md) | Off-page connectors off the sheet's edge are a drawing finding the gate fails on | Proposed | 2026-11-05 |
| [0050](0050-semi-batch-reactor-with-dosing-accumulation.md) | A semi-batch reactor with dosed feeds, its accumulation taken by the thermal screening | Proposed | 2026-11-05 |
| [0051](0051-batch-recipe-derives-the-cycle-time.md) | A batch recipe in process/recipe.yaml derives the cycle time; the flowsheet holds year averages | Proposed | 2026-11-05 |
| [0052](0052-batch-vessel-and-jacket-from-the-recipe.md) | Batch vessels and jackets are sized in the recipe, from the reactor model's content | Proposed | 2026-11-05 |
| [0053](0053-per-batch-lca-consumables.md) | Per-batch LCA exchanges are consumables per batch of the recipe | Proposed | 2026-11-05 |
| [0054](0054-gas-evolution-and-gas-dosing-in-a-batch.md) | Gas evolution and gas dosing in a batch: a vent outlet the gas leaves by as it forms | Proposed | 2026-11-05 |
| [0055](0055-batch-still-and-solvent-swap.md) | A batch (Rayleigh) still and solvent swap as a flowsheet step, solved natively | Proposed | 2026-11-05 |
| [0056](0056-precipitation-from-a-mixed-liquor.md) | Precipitation from a mixed liquor in the crystallizer; phase changes are not screened as reactions | Proposed | 2026-11-05 |
| [0057](0057-filter-dryer-and-recipe-units-over-several-steps.md) | A filter-dryer step to a residual moisture, and recipe units over several steps | Proposed | 2026-11-05 |
| [0058](0058-semi-batch-thermal-screening.md) | Semi-batch thermal screening: the MTT of what boils, the reactions that count, the MTSR over time, the gas release | Proposed | 2026-11-05 |
| [0059](0059-batch-models-write-their-energy-streams.md) | Batch models write and check the duty of their energy streams | Proposed | 2026-11-05 |
| [0060](0060-recycle-convergence-with-tear-streams.md) | Propagate converges recycles at declared tear streams (substitution or Wegstein) | Proposed | 2026-11-05 |
| [0061](0061-batch-rectification-on-the-shortcut.md) | Batch rectification: a column on the batch still, on the Fenske-Underwood-Gilliland shortcut | Proposed | 2026-11-06 |
| [0062](0062-vent-vapour-condenser-and-gas-solubility.md) | A batch's vent carries the liquid's vapour, with a partial vent condenser and a Henry split | Proposed | 2026-11-06 |
| [0063](0063-heats-of-solution-heat-up-and-vessel-metal.md) | Heats of solution and mixing, the heat-up of the charge and of the vessel's metal | Proposed | 2026-11-06 |
| [0064](0064-feos-pc-saft-as-an-optional-property-backend.md) | feos (PC-SAFT) as an optional property backend, first for liquid water-methanol density | Proposed | 2026-11-06 |
| [0068](0068-batch-still-phases-cut-conditions-and-heat-up-time.md) | Batch still: components in a phase of their own, a cut's own pressure and boil-up, the heat-up's time; an end at a temperature that stops where found | Proposed | 2026-11-12 |
| [0069](0069-thermal-screening-beyond-the-largest-reaction.md) | Thermal screening beyond the largest reaction: the network, every dose, the release over the batch, the content's boiling | Proposed | 2026-11-12 |
| [0070](0070-design-specifications-and-component-separators.md) | Propagate solves feeds and splits for design specifications (with the tears, Newton-Broyden) and component separators from their split | Proposed | 2026-11-12 |
| [0071](0071-gas-liquid-batch-head-space-sweep-and-absorption.md) | Gas-liquid batch: inerts, a head space, degassing, the heat of absorption and the vent condenser's freezing | Proposed | 2026-11-12 |
