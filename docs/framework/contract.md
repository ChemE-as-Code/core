# Engineering contract

This page states what a value, an id and a reference mean in every cheme-as-code file, which code
owns each convention and what `cheme validate` checks. It extends
[Identity, relationships, provenance](architecture.md#identity-relationships-provenance): it
adds no universal object model, and files keep their own schemas. Each table lists the known
gaps; the follow-ups at the end are the work of
pre-release issue 81.

## Identity

An id is stable when it matches `ID_PATTERN` (`foundation/schema_base.py`): letters, digits,
`_` and `-`, starting with a letter. Free text belongs in `name` or `title`.

| Entity | Id | Where | Checked |
|---|---|---|---|
| Feed, product, block, step, stream | `id` | `process/flowsheet.yaml` | pattern and unique across the flowsheet: `cheme.process-id`, `-duplicate-id` (error) |
| Port | `id` | `process/flowsheet.yaml` | pattern (`cheme.process-id`, error) |
| Component | `id`; optional `cas`, `chebi`, `inchikey`, `smiles` | `process/materials.yaml` | unique (`cheme.process-duplicate-id`); pattern `cheme.contract-id` (warning); CAS check digit `cheme.component-cas` (warning); InChIKey shape (schema); SMILES against InChIKey and formula `cheme.component-identity` (warning, with RDKit) |
| Reaction | `id`; derived `reaction_smiles` | `process/reactions.yaml` | unique (`cheme.reaction-duplicate-id`); pattern `cheme.contract-id` (warning) |
| Catalyst | `id` | `process/catalysts.yaml` | unique (`cheme.catalyst-duplicate-id`); pattern `cheme.contract-id` (warning) |
| Evidence source, route, observation | `id` (one set per file) | `process/reaction-evidence.yaml` | unique (`cheme.evidence-duplicate-id`); a source's DOI and patent publication number (`cheme.evidence-identity`) |
| Operating case | `cases[].id` | `process/flowsheet.yaml` | unique, at most one default; pattern `cheme.contract-id` (warning) |
| Control loop, sequence, step; narrative section, objective, failure | `id` | `control/loops.yaml`, `control/sequences.yaml`, front matter of `process/narrative.md`, `control/philosophy.md` | pattern (schema); unique `cheme.control-duplicate` (error) |
| Equipment, instrument, piping item | `tag` | the lists | duplicates (warning); against the P&IDs |
| Line | `number` | `piping/line-list.yaml` | duplicates (warning); against the P&IDs |
| Sheet | `id` | `plant.yaml` | unique |
| LCA flow, consumable, dataset | `feed:<id>`, `product:<id>`, `emission:<component>`; `id` | `lca/*.yaml` | pattern (schema); resolved by `cheme assess lca` |
| HAZOP node, deviation, scenario, safeguard, action, mode | `id` | `safety/hazop/<id>/study.yaml` | pattern (schema); unique across the study: `cheme.hazop-duplicate-id` (error) |
| Risk band, grade, category | `id` / `code` | the risk matrix | unique: `cheme.risk-matrix-duplicate` (error) |
| Decision | `D-NNN` | `DESIGN.md` headings | `cheme.decision-unknown` (info, see below) |
| Finding | `<file>#<rule>:<subject>` | `foundation/findings.py` | target of `accept:` |

The components' external key is the CAS number. The thermo property adapter, exergy and the
DWSIM compound list look a component up by it; `simulation.yaml` `components` maps an id to a
DWSIM name when CAS is not enough. A component may also give its standard InChIKey and its
SMILES (`domains/chemistry/identifiers.py` checks them): the InChIKey is the key across
databases, the SMILES what RDKit, the kinetics records and the property lookups read. With
RDKit installed, `cheme validate` derives the InChIKey and the formula from the SMILES and
warns when they differ from the given ones; without it the SMILES is not checked.

A reaction's external identifier is its reaction SMILES, `reactants>>products`
(`Reaction.reaction_smiles`, `reaction_smiles` in `GET /api/reactions`). It is derived from the
stoichiometry and the components' SMILES, each molecule repeated by its coefficient, and never
stored; it is null unless every component has a SMILES and every coefficient is whole.

**Gaps.** Plant tags have no pattern, only a heuristic (`piping/tagrefs.py`). The InChIKey is
not yet used as the key of kinetics retrieval or of LCA elementary flows, which still match by
name, SMILES or CAS; a reaction with fractional coefficients has no reaction SMILES. The
flowsheet keeps its own copy of the pattern (`domains/process/model.py` `_ID`) because editing a
generator module makes every built sheet outdated; a test keeps both the same.

## References

| From | To | Syntax | Resolved by |
|---|---|---|---|
| Inside a file | an entity of that file | bare id (`Step.block`, `StreamDef.from_: NODE.port`) | the file's rules |
| Flowsheet | equipment, line, instrument, sheet | `links: [{target, ref, sheet?, role?}]` | `cheme.process-link-unresolved`; gate `process-links` |
| Flowsheet, reactions | components, reactions, catalysts | bare id | `cheme.process-component`, `-reaction`, `-catalyst`, `cheme.reaction-component` |
| Reactions (`catalyst`, `rate.catalyst`, `mechanism.catalyst`) | catalysts | bare id (a reaction's own `catalyst` may be the catalyst's `name`) | `cheme.catalyst-unknown` (warning), `cheme.catalyst-by-name` (info); none without `process/catalysts.yaml` |
| Reaction evidence (routes, observations, `model_basis`) | components, reactions, catalysts; its own sources, routes, observations | bare id | `cheme.evidence-reference` (error); `-component`, `-catalyst` (warnings, only with the file); `-reaction` (a model reaction: error) |
| `simulation.yaml` | steps, blocks, streams, components | bare id as key | `cheme.process-sim-unknown-step` (validate); `sim-spec` (simulate) |
| LCA | flowsheet products, feeds, streams, equipment | typed key `feed:`/`product:`/`emission:`; tag globs | `cheme assess lca` |
| Datasheet | equipment list | file name `<TAG>.yaml` and `tag` | `cheme.datasheet-not-listed` |
| Datasheet `operating` | flowsheet case, streams | `case: <case id>`, `streams: [<stream id>, ...]` (written by `datasheets fill`) | `cheme.contract-ref` (warning; none without a flowsheet) |
| Design basis feeds, products | flowsheet feeds, products | `terminal: <feed or product id>` | `cheme.contract-ref` (warning; none without a flowsheet) |
| Interlocks, electrical, placement | tags | bare tag | `cheme.interlock-unknown-tag`, electrical cross-check, `layout-unknown-tag` |
| HAZOP study | its safeguards, actions, modes | bare id | `cheme.hazop-unknown-ref` (error) |
| HAZOP study | tags, sheets, DEXPI objects | `members`/`refs`: `TAG`, `{tag, sheet}`, `{sheet, object}` | `cheme.hazop-unknown-tag` (warning), `-unknown-sheet` (error), `-not-on-sheet` (warning) |
| HAZOP safeguard | interlocks | `interlock: <id>` | `cheme.hazop-unknown-interlock` (error) |
| HAZOP study | the risk matrix; the analysed inputs | `risk_matrix: <path>`; `analysed: [{path, revision, relation}]` | `cheme.hazop-matrix`, `-unknown-code` (error); `cheme.hazop-input-changed` (warning) |
| Loops, sequences, narrative, philosophy | tags; loops, sequences, steps, sections; interlocks; cases, blocks, streams | bare id (`loop:`, `interlock:`, `stream:` + `property:`) | `cheme.control-unknown-tag`, `cheme.control-ref` (warning), `cheme.control-case` (a target against its case value); see [control.md](control.md) |
| Any YAML value or comment | a decision | `D-NNN` | `cheme.decision-unknown` |

**Gaps.** `Line.from_`/`to` are not resolved. A catalyst reference from the reactions is a
warning, not an error (no gate makes it one); `Reaction.catalyst` still accepts free text for
older files, and the `catalyst` of a kinetic data set (`experiments/`) is not resolved. The
catalyst references are checked by `domains/process/sheets.py` (`catalyst_reference_findings`)
and not by the generator module `model.py`, so that built sheets stay current. The case and
stream references are checked outside the generator modules too (`domains/equipment/datasheets.py`
`reference_findings`, `domains/process/sheets.py` `design_basis_reference_findings`). Only
`operating` names a case: `design` and `type_specific` values do not, and a `datasheets fill`
value's own case is known only from the sheet's `operating.case`. `datasheets draft` writes no
references, and a design-basis utility names no flowsheet stream.

## Values

The process `Quantity` (`domains/process/schema.py`) is the canonical shape:

```yaml
flow: {value: 12735.5, unit: kg/h, provenance: calculated,
       source: 'cheme process propagate: reactor R1 from S1', fingerprint: 5406c177142daee5}
```

- **Units.** Pressure units carry absolute or gauge (`kPa(a)`, `bar(g)`); `foundation/units.py`
  converts and refuses gauge to absolute without an ambient pressure. Without `unit`, the
  flowsheet's `units:` default applies; a gauge default is refused (`cheme.process-gauge-default`).
- **Provenance.** `Provenance` (`foundation/schema_base.py`):
  - `given`: the user's figure (a specification, a vendor figure, a measurement);
  - `assumed`: an engineering guess, which should cite its basis (a `D-NNN`, a reference);
  - `calculated`: a tool's result, never edited by hand.
  A tool marks its own values by starting `source` with its name (`cheme process simulate:`,
  `cheme process propagate:`, `cheme process props`, `cheme datasheets fill`); it rewrites only
  those. Conversions and equilibrium-constant fits admit only `given` or `assumed`.
- **Origin.** An optional `origin` (`Origin`, `foundation/schema_base.py`) on a process
  `Quantity` and `CompositionValue` (the simulation specs too), a datasheet `Quantity` and an
  LCA exchange refines the class without replacing it: `given` is `measured`, `vendor` or
  `literature`; `assumed` is `design-rule`, `estimate` or `literature`; `calculated` is
  `simulated` or `correlation` (`ORIGIN_CLASSES`). Validate reports another pairing in the
  flowsheet or the simulation specs as `cheme.provenance-origin` (warning). `simulate --fill`
  writes `simulated`, `props --fill` and `datasheets fill` (on the values from the streams)
  write `correlation`; propagate writes none (a balance). A tool sets it only on the values it
  rewrites. The datasheet draft carries a stream value's origin over. No fingerprint includes
  it (`NOT_INPUTS`, `foundation/provenance.py`), and the sheets' `source_sha256` drops it while
  it is unset.
- **Staleness.** A calculated value carries the fingerprint of its inputs:
  `cheme.process-calculated-stale` (validate), `cheme.process-sim-stale` (simulate --check),
  `cheme.hazop-band-stale` (validate: a HAZOP band whose rating or matrix changed; a band that
  differs from the lookup with unchanged inputs is `cheme.hazop-band-edited`, an error),
  `cheme.datasheet-stale` (validate: a value `datasheets fill` calculated, when the streams at
  the item's linked nodes or the inputs its `inputs:` names changed; a value without a
  fingerprint is never reported; a `catalyst:` input covers the whole catalyst record).
  `written_by(value, tool)` (`foundation/provenance.py`) is the one test of "this tool wrote
  it, so it may rewrite it".
- **Fingerprint formats.** Four are in plant repositories, and each stays as it is (a new format
  would mark every recorded value stale):
  - `fingerprint: 5406c177142daee5` on a value: 16 hex digits of the sha256 of its inputs as
    sorted JSON (`value_fingerprint`). New code uses it for values.
  - `sha256:<hex>` for one file's content (`file_fingerprint`; review `basis`, run records,
    the layout model's `sources`). New code uses it for files.
  - The full hex digest without prefix in the BFD/PFD `cheme-process` comment and the layout
    model's `generator_sha256` and `output_sha256` (canonical content, not a file).
  - The LCA report's `files`, which is `sha256:<hex>` or a git blob id.
- **Variants.** A datasheet `Quantity` has `assumed: bool` in place of `provenance`, and a
  `value` that may be `TBD`, `supplier` or `not_applicable`; the datasheet draft maps `assumed`
  to `assumed: true` and the rest to `source`. LCA rows have `amount` plus `unit` and the same
  `provenance` (and the `origin` all the values summed give). DEXPI sheets map `given`,
  `assumed` and `calculated` to SPECIFIED, ESTIMATED and CALCULATED, and the origin `measured`
  to OBSERVED (pyDEXPI's `QuantityProvenance` has no member for the other origins); the
  description names the origin (`given, measured; source: ...`).

**Gaps.** The origin is optional: values written before it existed, by hand or by a tool, give
none, and a tool adds it only when it rewrites a value. The datasheet `assumed: bool` stays as
it is beside the origin. The 16-hex value fingerprint in `domains/process/props.py`, a
generator module, is still computed there (it gives the same digest as `value_fingerprint`):
moving it changes the generator fingerprint, so it waits for a release that rebuilds the sheets.
A `datasheets fill` dimension or weight from a layout model or the equipment list carries no
fingerprint (a vessel's volume from them names the sheet's dimensions in `inputs:`).

## Uncertainty

One model, `Uncertainty` (`foundation/uncertainty.py`), states the uncertainty of a value: a
distribution (`lognormal`, `normal`, `triangular`, `uniform`) relative to the deterministic
value, or pedigree scores. The LCA defined it (`lca.yaml`; `domains/assessment/lca/schemas.py`
re-exports it) and the TEA premises reuse it. Each study has defaults per provenance class
(`StudyUncertainty.defaults`), and may key one by an origin (`measured: {gsd2: 1.02}`): it
wins over the class's for an exchange whose values all give that origin. A process `Quantity` and a `CompositionValue` may give an
optional `uncertainty` (`process/flowsheet.yaml`, and the specs of `process/simulation.yaml`,
which reuse the quantity). Props, propagate, the datasheet fill and the simulator model leave it
out of their fingerprints. The sheets' `source_sha256` drops it while it is unset, so an
unchanged flowsheet keeps every fingerprint; a given uncertainty asks for a rebuild like any edit.
`cheme assess lca` gives a feed or product exchange the uncertainty of its `flows:` entry. If
that entry has none, it uses the flowsheet's: the uncertainty every stream flow (or duty) summed
into the terminal gives, when they all give the same one. Otherwise the study's default applies.
Estimates carry an AACE class (`estimate_class`) and its accuracy range. Everything else holds
ranges only (`ApplicationRange`, catalyst windows, `SimTolerance`).

**Gaps.** Only the LCA samples the process uncertainties: the TEA and the simulation ignore
them, and an LCA emission exchange (`emission:*`, from flow and composition) takes the default.
A sensitivity or tornado over process quantities does not exist yet.

## Assumptions and decisions

`DESIGN.md` at the repository root is the register: one heading per entry, `## D-NNN <title>
(<date>)`, then `Decision`, `Reason`, `Rejected` and `Assumptions` (template:
`templates/project/DESIGN.md`). Values cite an entry in `source`, `basis` or a comment. `cheme
validate` reports a cited id without a heading as `cheme.decision-unknown` (info, once per file
and id; `project/decisions.py`). Every `*.yaml` of the repository is read, comments and
generated files included; hidden directories, `build`, `dist`, `node_modules`, nested
repositories and files outside the root are not. A repository without `DESIGN.md`, or with no
entry in it yet, is not checked.

## Results and solver status

- **Simulation.** `process/simulation-run.json` (`cheme/simulation-run/v1`,
  `domains/process/simulation/record.py`), one entry per case, each an
  [adapter result](#model-and-solver-adapter-contract): simulator and version, property
  package, model fingerprint, input fingerprints, `converged` and `status`, `iterations`, per
  unit its status and convergence, per stream the values written and kept. `cheme validate` and `simulate --check`
  report a record whose model the inputs no longer translate to (`cheme.process-sim-run-stale`);
  translating needs no simulator.
- **Deviations.** Findings are the deviation channel of every tool (`sim-deviation`,
  `sim-not-converged`, `process-balance`); `checks/status.json` holds the gate results
  (`CheckResult`).

**Gaps.** Equilibrium (`NotConverged`), flash (`FlashCalculationResult`) and balance
calculations, called inside other tools, still report status their own way; propagate, props
and DWSIM return the adapter result.

## Versioning

A versioned file declares `schema: cheme/<kind>/vN` and `kind:`. The reader accepts exactly its
version and gives the shared message (`unsupported_schema`, which also spells the id from before
the rename). Every other file kind (`plant.yaml`, the lists of `LIST_SCHEMAS`, the layout inputs
of `LAYOUT_SCHEMAS`, datasheets, review front matter, `checks/status.json`) takes an optional
`schema: cheme/<kind>/v1`, the kind as `cheme schema` lists it (`optional_schema` in
`foundation/schema_base.py`); a file without it reads as v1. `cheme init` writes it. Generated artefacts record their generator version and fingerprints (BFD/PFD
comment, layout model, simulation run record). `plant.yaml` `requires:` gates the tool version.

**Policy for a breaking change.** Bump `N`, register the `(kind, vN-1, vN)` transform in
`foundation/migrate.py` (`cheme migrate`), read both for one minor release, and note it in the
changelog. Adding an optional field is not a breaking change. `cheme migrate` (`--check`, the
default, lists the files that would change and exits 1; `--write` rewrites them) ships one
transform, `v0` (no `schema:`) to `v1`: it inserts the field as the first key, as text, so
comments stay; and the LCI dataset's `v1` (`cheme/lca/v1`) to `cheme/lci_dataset/v2` for the
hand-written datasets in `lca/datasets/`. Generated files and review records are left alone.

**Gaps.** The field stays optional on the kinds that had none, so a file without it is not
reported. The required-schema kinds (process, simulation, reactions, catalysts, LCA, TEA,
kinetic data) join `cheme migrate`'s inputs when their v2 arrives.

## Model and solver adapter contract

An adapter (DWSIM; property and propagation calculations; later IDAES/Pyomo or Cantera where
they fill a demonstrated gap) takes the flowsheet, a case and its specs, and returns one
adapter result per case (`AdapterResult`, `foundation/schemas/run.py`; `cheme schema
adapter-result`):

```yaml
schema: cheme/adapter-result/v1
case: design
status: converged | not-converged | refused | failed
solver: {name: DWSIM, version: 9.0.5.0, method: Peng-Robinson (PR)}
model_fingerprint: 3f2a...           # the translated inputs
inputs: {commit: ..., fingerprints: {process/flowsheet.yaml: sha256:...}}
iterations: 12
units:   [{id: K1, status: simulated, converged: true, results: {...}}]
streams: [{id: S2, values: {...}, filled: [temperature]}]
findings: [...]
```

- `status`: `converged` (it solved what it was given), `not-converged` (it ran and left
  something unsolved, named in `messages`), `refused` (it did not start: an input it does not
  support) or `failed` (it started and broke off).
- `iterations`: what the solver counts, null where it counts nothing.
- `model_fingerprint`: null where the adapter fingerprints each value instead.

| Adapter | Where | `solver` | `iterations` | Not converged |
|---|---|---|---|---|
| DWSIM | `simulate --fill`: each entry of `process/simulation-run.json` | `simulator` key: `dwsim`, version, `method` = property package | flowsheet passes: one per solve without a recycle, else the slowest recycle's `IterationsTaken`, summed over the re-solves (DWSIM's flowsheet solver has no count of its own) | the simulator's messages |
| Propagation | `cheme process propagate --json` | `cheme process propagate`, cheme-as-code version | sweeps through the nodes | the nodes not solved (also in `units`, `status: not-solved`) |
| Properties | `cheme process props --json` | `thermo`, its version, the EOS | null (one flash per stream) | the streams refused or missing inputs |

The DWSIM entry keeps the keys it had (`simulator`, `converged`, `property_package`); an entry
written before `status` and `simulator.method` existed reads the same, `status` following
`converged`. `--json` prints `{"lines": [...], "results": [<adapter result>]}` and writes no
file.

Each adapter writes values as `provenance: calculated` with its name at the start of `source`.
It stays in `core` (`integrations/` for the backend, the domain for the translation); agent
skills and MCP tools call it and hold no algorithm of their own.

## History

Contract work for pre-release issue 81:

| Topic | Issue | Change |
|---|---|---|
| This contract, id, decision and run-record checks | — | pre-release PR 119 |
| Catalyst references | pre-release issue 118 | pre-release PR 122 |
| One value fingerprint, stale datasheet values | pre-release issue 117 | pre-release PR 123 |
| Adapter result record, DWSIM iterations | pre-release issue 116 | pre-release PR 124 |
| `schema:` on every file, `cheme migrate` | pre-release issue 113 | pre-release PR 125 |
| Component InChIKey and SMILES, reaction SMILES | pre-release issue 114 | pre-release PR 126 |
| Case and stream references | pre-release issue 115 | pre-release PR 128 |
| Uncertainty on process quantities | pre-release issue 112 | pre-release PR 129 |
| Provenance `origin` | pre-release issue 111 | pre-release PR 130 |
| HAZOP study and risk matrix ids, references, bands | pre-release issue 136 | this change ([hazop.md](hazop.md)) |

What is still missing is in each section's **Gaps** line; line from/to is pre-release issue 38.
