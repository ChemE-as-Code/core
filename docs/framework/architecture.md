# Framework architecture

`cheme-as-code` is one installable package. This document sets out its internal modules, what each
one owns, and which imports are allowed between them. The repository name (`core`), the package
name, the CLI name, its commands and the `cheme serve` endpoints stay as they are. Modules
that moved are importable only from their new path (no compatibility layer for internal modules; ADR 0032 says what is public);
see [migration-table.md](migration-table.md).

## Layout

```
src/chemeascode/
  foundation/      artifact-independent infrastructure: findings, workspace, git queries, reviews
  domains/
    requirements/  design basis, cases, constraints, assumptions, acceptance criteria
    chemistry/     molecules, reactions, routes, kinetics, property sources
    experiments/   records, datasets, parameter estimation, uncertainty
    process/       materials, flowsheet, BFD/PFD, mass and energy balances, stream properties;
                   thermodynamics/ (phase, model selection), heat_integration/ (pinch targets),
                   separations/ (selection)
    equipment/     equipment list, datasheets, sizing
    piping/        P&IDs (DEXPI), line list, special items, tag rules, authoring
    control/       instrument list, cause and effect, interlocks, control loops, sequences,
                   narratives and control philosophy, electrical list (motors, cables)
    safety/        HAZOP and related studies, safeguards, evidence
    assessment/    material take-off and estimate, costing, utilities summaries, LCA, alternatives
    spatial/       site plan, buildings, placement, distances, clearances, routing
  project/         workspace-wide composition: validate_workspace, checks/gates, sign-off, status
  interfaces/
    cli/           Typer app (`cheme`), argument parsing and output formatting only
    api/           `cheme serve`, the read-only JSON API for the viewer (extra `serve`)
    mcp/           README only: the intended boundary of an MCP adapter
  integrations/    adapters to external tools: git setup, pyDEXPI glue, thermo, resvg, PubChem, NIST, ...
  templates/       `cheme init`: installing the project template and the bundled skills
    project/       the project template (data)
  schemas/         the schema catalogue (`cheme schema NAME`): re-exports each owner's schemas
```

Each schema of a plant-repository file lives with its owner: `foundation/schemas/` (`plant.yaml`,
`checks/checks.yaml`, `checks/status.json`, review front matter, on `foundation/schema_base.py`),
`domains/requirements/schemas.py` (design basis), `domains/equipment/schemas/` (equipment list,
datasheets), `domains/piping/schemas/` (line and instrument lists, special items),
`domains/control/schemas.py` (cause and effect, electrical list), `domains/spatial/schemas.py` (layout) and
`domains/process/schema.py`. `chemeascode.schemas` only re-exports them, and it sits above the
domains: `project` and the interfaces read it, a domain imports the owner module directly.

Bundled skills live with their owner: `domains/<d>/skills/<name>/` and `project/skills/<name>/`.
`cheme init` installs them into the plant repository's `.claude/skills/<name>/`.

`domains/chemistry` holds property retrieval (`properties.py`) and reaction kinetics
(`kinetics/`); `domains/safety` holds the OSHA hazard data (`hazard_data.py`) and the HAZOP
studies with their risk matrix ([hazop.md](hazop.md)). Their web and
service adapters are in `integrations/` (`http.py` is the one transport: standard library,
injectable for tests, no environment or API keys read), so a domain never opens a connection
itself.

A domain with no code today, such as experiments, gets a `README.md` that states its scope and
nothing else. `assessment` has its first functions, the material take-off of the layout model
and its estimate ([mto.md](mto.md)); it reads the model as a file, not through `spatial`. `requirements` has only its schema (`schemas.py`, the design basis) and a
`README.md` for the rest of its scope.

`project/` is an addition to the logical structure in the specification. `validate_workspace`,
the gate kinds in `checks.py` and `cheme status` each call into several domains, so they
can live neither in `foundation` (which imports no domain) nor in an interface (because both
`cli` and `api` call them).

## Responsibilities

| Module | Owns | Must not contain |
|---|---|---|
| `foundation` | `units` (the one unit converter and the (a)/(g) pressure convention), `Finding`/`Level`/`Report` (stable finding ids `<file>#<rule>:<subject>`), YAML source-line helpers, `Workspace` (paths and file kinds of a plant repository), `gitinfo` (read-only git, argument lists only), review records and their status vocabulary, the `plant.yaml`/`checks.yaml`/`status.json` schemas | engineering rules, DEXPI specifics, Typer, FastAPI |
| `domains/<d>` | that domain's schemas, loaders, rules (findings), calculations, generators, and skills (`domains/<d>/skills/<name>/`) | CLI parsing, HTTP, printing, agent or LLM calls |
| `project` | composing the domains over one workspace: `validate_workspace`, gate evaluation, sign-off, status summary, change impact | engineering methods (it calls the domains) |
| `interfaces/cli` | commands, options, exit codes, output formats | logic that has no Python entry point in a domain or in `project` |
| `interfaces/api` | read-only endpoints. Paths go through `clean_path`/`Snapshot` and revisions through `Repo.resolve` | writes to the plant repository, engineering logic |
| `integrations` | wrappers over external programs and libraries (git config and hooks, thermo, resvg, DWSIM; CAD later) | domain rules |
| `templates` | copying the template, `dot-` renaming, placeholder substitution, skill installation and its manifest | anything a running plant check needs |

## Dependency directions

```
interfaces  ->  project  ->  domains  ->  foundation
     |             |            |
     +-------------+------------+-->  integrations  ->  foundation
templates  ->  foundation (and reads skill files from domains/*/skills as package data)
```

- `foundation` imports only the standard library, pydantic, PyYAML and lxml. It never imports a
  domain, `project`, an interface or an integration.
- A domain imports `foundation`, `integrations`, and only the domains listed for it below. No
  domain imports `project`, `interfaces` or `templates`.
- `integrations` import `foundation` only. Optional dependencies are imported inside functions.
- `project` may import any domain. `interfaces` may import anything except each other: `cli` does
  not import `api`. The one exception is `cheme serve`, which imports `interfaces.api` lazily
  inside the command.

Allowed domain-to-domain imports. They follow the direction in which information flows.
Feedback, for example a safety finding that sends the team back to chemistry, travels through
artifacts and review records, not through imports.

| Domain | May import |
|---|---|
| requirements | (none) |
| chemistry | requirements |
| experiments | requirements, chemistry |
| process | requirements, chemistry, experiments |
| equipment | requirements, process |
| piping | process, equipment |
| control | process, equipment, piping |
| safety | chemistry, process, equipment, piping, control |
| assessment | requirements, process, equipment |
| spatial | equipment, piping, control, safety (the zone radius table: safety classifies, spatial places; the electrical list, motor list and cable sizes: control declares, spatial routes the trays) |

A P&ID is one artifact that combines equipment, piping and control information. The DEXPI file
handling (`fmt`, `render`, `show`, `diffview`, `sheet_query`, authoring) lives in `piping`.
`control` reads instruments and signal lines through piping's `SheetIndex`/`sheet_query`, and
does not keep a second model.

`tests/test_boundaries.py` enforces these rules by parsing every import with `ast`, including
imports inside functions, so they cannot drift unnoticed. It also checks that `foundation` and the
domains never import an interface, `project` or `templates`, that the package `__init__` files of
`foundation` and the domains import nothing, and that importing the basic modules in a fresh
interpreter loads no optional dependency. The code still breaks the layer rules in three places.
Each is listed in the test's `EXCEPTIONS` with its reason, and the test fails once an exception
is no longer needed:

- `foundation.workspace.check_requirement` imports Typer lazily to print and exit, until the CLI
  gets its own wrapper around `requirement_problem`.
- `integrations.git` (the git textconv driver) renders a readable projection of a P&ID through
  `domains.piping.render`. That projection is piping logic and belongs in `domains/piping`.
- `foundation.workspace.Workspace.parsed_lists` validates each engineering list against its
  domain's schema through the catalogue's `LIST_SCHEMAS` (a lazy import). Its two callers
  (`project.status`, `domains.process.streams`) could pass the schemas in instead.

The list parsing that `domains.process.streams` used to borrow from `project.status` is now
`Workspace.parsed_lists` in `foundation`. The earlier exception for the catalogue
(`chemeascode.schemas -> domains.process.schema`) went away when the schemas moved to their owners.

`validate.Report` stays in `project/validate.py`: its `drawing_lines()` reads the piping drawing
rules, which `foundation` may not import.

## Domain, artifact type, stage, status

These are four independent axes. None of them implies a fixed pipeline.

| Axis | Values today | Where |
|---|---|---|
| Domain | the ten packages above | code ownership |
| Artifact type | `plant.yaml` sheet `kind` (`pid`, `bfd`, `pfd`); the file kinds of `Workspace` (`process/*.yaml`, lists, datasheets, layout, `control/cause-effect.yaml`, review records, `checks/*`) | `foundation/schemas/plant.py`, `foundation/workspace.py` |
| Project stage | `plant.yaml` `stages` (template: `concept`, `basic`, `detail`); `stage` = the current one; a stage is *reached* when its sign-off in `checks/status.json` is on the default branch | template `STAGES.md`, `signoff.py` |
| Artifact status | sheet `status: planned \| drafted`; generated-sheet states `generated-edited` / `generated-version` / `generated-outdated`; generated layout model `layout-model-edited` / `-version` / `-outdated` / `-missing` (`domains/spatial/model.py`); review finding status `open \| closed <sha> \| accepted: ... \| superseded by ...`; review `reviewer_kind` + `approved_by`; stage sign-off | `foundation/schemas/plant.py`, `domains/process/provenance.py`, `foundation/reviews.py`, `foundation/schemas/status.py` |

Each generic status maps onto existing mechanisms. No new mandatory field is needed.

| Generic | Existing mechanism |
|---|---|
| draft | sheet `drafted`, or any file not covered by a current review |
| reviewed | covered by the `scope` of a review record whose `reviewed_commit` is an ancestor of HEAD, with no changes since (`provenance.content_changes`, as checked by the review gate `current: true`: a change of nothing but full sha256 or commit digests, such as a regenerated output's source fingerprint, is not a change; when git cannot tell, it is not reviewed) |
| approved | a human review (`reviewer_kind: human`, or `approved_by` set) and a stage sign-off in `status.json` |
| superseded | earlier git revisions; review findings `superseded by <id>` |
| review needed | the scope changed since `reviewed_commit`; a generated sheet whose `source_sha256` no longer matches (`generated-outdated`); a stale calculated stream value |

A project holds artifacts at different maturities at once, for example a PFD that has been
signed off for `basic` next to a P&ID that is still `planned`. Gates are per stage, and stages
are data in `plant.yaml`, so a project can add or reorder them.

## Identity, relationships, provenance

The convention reuses what exists. It is optional and extensible, and it adds no universal object
model:

- **Artifact identity.** The path from the repository root (`pid/P-03.xml`,
  `equipment/datasheets/P-101.yaml`). For sheets, the `plant.yaml` sheet `id` is an alias.
- **Engineering-object reference.** The printed tag (`P-101`, `AIA-3103`), resolved through the
  lists and `sheet_query`. Inside a DEXPI file the XML `ID` is used. Flowsheet `links` already
  reference list tags and sheet ids (`process.model.link_problem`).
- **Finding identity.** `Finding.id`, the target of the `accept:` entries in `checks/checks.yaml`.
- **Source revision.** A git commit sha: review `reviewed_commit`, sign-off `commit`, generator
  `frame` revision. For generated files, a content fingerprint (`source_sha256`).
- **Producing tool and version.** The `cheme-process` provenance comment (`generator_version`,
  `generator_sha256`, `schema`, `view`, `case`, `source_sha256`, `output_sha256`).
  `plant.yaml` `requires: cheme-as-code>=X.Y` gives the version.
- **Typed relationships.** Existing ones: *represents* (a BFD/PFD sheet represents
  `process/*.yaml`; a sheet item represents a list tag), *derived-from* (a generated sheet from
  its sources; a `generator` sheet from `script` + `frame`), *analyses* (a review record's
  `scope` at `reviewed_commit`), *depends-on* (gates on stages). New relationships are recorded
  as an optional `basis:` list (`{path, revision, relation}`) on the artifacts that need it,
  starting with review records. Unset means unchanged behaviour.

`foundation/provenance.py` implements the shared part: `RELATIONS`, `file_fingerprint`,
`SourceRevision` (commit, dirty inputs, fingerprints) with `source_revision(root, paths)`, and
`changed_since(root, path, revision)` for a commit or a fingerprint. The `basis` entry is the
`Basis` model of `foundation/schemas/reviews.py`.

[Engineering contract](contract.md) states, per entity and value, the ids, references, units,
provenance, uncertainty, decisions, solver status and schema versions, and what `cheme validate`
checks of them.

## Change impact

The approach is conservative. When a referenced source changed after the revision or
fingerprint an artifact records, the artifact is flagged `review needed` with a finding that
names the file, the source, both revisions and a hint. Nothing is regenerated, and nothing is
declared invalid. The signals already exist (`generated-outdated`, review gate `current`, stale
calculated values). `project.impact.review_needed(workspace)` collects them, plus the review
`basis` entries, as `cheme.review-needed` findings at level info, and the read-only command
`cheme impact [--json]` prints them. It builds no graph store, event system or workflow
engine. The drift of `generator:` P&IDs is not part of it, because detecting it runs the
generator script; `cheme validate` reports that as `generated-sheet-drift`.

## Use from downstream applications

1. **Direct import.** Call domain functions with explicit inputs, for example
   `domains.process.streams.stream_report(root, case)` → `StreamReport` (streams with units
   and provenance, balances, findings, `source` revision), `domains.process.model.load(root)` →
   `(Process, findings)` or `balances(process, case)`. `stream_report` is the reference
   pattern: `cheme process streams` only formats its result (see
   [contributing.md](contributing.md)). Results are dataclasses or pydantic models plus `Finding` lists. No
   function reads the current directory. `Workspace(root)` is passed explicitly.
2. **Worker on a snapshot.** The caller exports or checks out a revision to a directory. The
   worker runs `project.validate_workspace(Workspace(root))`, a generator or a calculation there.
   It returns the proposed files (bytes plus a path), the findings, and the source revision (the
   commit sha, or the fingerprints in the provenance comment). The caller compares that revision
   with its current one before it applies anything.

Authentication, collaborative editing, database transactions, and the decision to accept
proposed changes stay with the caller. This repository contains no code specific to any
downstream application.

## MCP boundary

`interfaces/mcp/README.md` documents the intended boundary. A future adapter would be an optional
extra that wraps the same functions the CLI calls. It would expose only a curated, read-mostly
set with JSON schemas taken from the pydantic models, and it would never touch pyDEXPI's private
MCP server or editor layer. Agents edit files directly, as they do today. No adapter is
implemented now.

## Optional dependencies

- `import chemeascode`, `chemeascode.foundation` and every `chemeascode.domains.<d>` package
  `__init__` import no Typer, FastAPI, uvicorn, thermo, chemicals or resvg. A subprocess test
  checks `sys.modules` after the import.
- Optional libraries are imported inside the function that needs them and stay in their extras:
  `serve` (fastapi, uvicorn), `png` (resvg-py), `props` (thermo, chemicals), `units` (Pint,
  used lazily by `foundation.units` for units beyond the plant-file convention) and `chemistry`
  (RDKit, for SMILES checks in `integrations/rdkit.py`). A missing extra produces a finding or
  error that names the extra.
- New heavy dependencies, such as simulators, CAD or ML models, go into a new extra and an
  `integrations/` adapter, never into the base dependencies. A program that needs its own
  runtime runs out of process: DWSIM (.NET) runs `integrations/dwsim_worker.py` in the Docker
  image of `docker/dwsim/` (or next to a local install), and `integrations/dwsim.py` talks to it
  in JSON; `domains/process/simulation/` builds the model and writes the results back. The
  tests that need it run with `CHEME_DWSIM_TESTS=1` (workflow `dwsim`).
- Typer is a base dependency for the CLI, but only `interfaces/cli` imports it.

## Possible DEXPI YAML serialization

The owner is considering a git-oriented YAML serialization of DEXPI models with import and
export in pyDEXPI, for P&IDs and likewise for DEXPI process models. Core's own
`process/*.yaml` flowsheet format could later converge with such a process YAML. Whether, when
and how is undecided. This section records what core would have to change; nothing of it is
implemented.

### Where the serialization lives

pyDEXPI owns the format: its schema, the loader, the serializer and the round-trip guarantee
(XML -> model -> YAML -> model -> XML). Core only selects a format per sheet and calls pyDEXPI.
Core does not write its own DEXPI YAML mapping, for the same reason it does not write its own XML
loader. Core's `process/*.yaml` stays core's format until a pyDEXPI process YAML exists. Any
convergence would then be a migration of that format, with `cheme process build` kept as
the generator.

### What in core depends on the XML form today

- **`cheme fmt`** (`domains/piping/fmt.py`): it defines the canonical XML (pyDEXPI's
  serializer output) and gives every object a readable id (`assign_ids`). Diffs, `show` ranges,
  review quotes and the pre-commit check (`fmt --check`) all assume that canonical form.
  XML comments are dropped and reported, except cheme-as-code's own (text starting with
  `cheme-`, such as `cheme-process`), which are written back at the top of the document.
- **The git projection** (`integrations/git.py`, `pid/*.xml diff=dexpi` in the template's
  `.gitattributes`): `cheme git-setup` installs a textconv driver that shows `git diff` of a
  P&ID as review text keyed by XML ids. A YAML file would be readable in git without it, but
  the projection's id keys would have to match.
- **Generated-sheet fingerprints** (`domains/process/provenance.py`): the `cheme-process`
  provenance is an XML comment at the top of `process/BFD.xml`/`PFD.xml`, and `output_sha256`
  is taken over the C14N form of the XML. `validate` uses it for `generated-edited`,
  `generated-version` and `generated-outdated`. The `generator:` P&IDs
  (`domains/piping/generators.py`) compare XML trees after `fmt`.
- **`validate` line numbers**: `SheetIndex` (`domains/piping/sheet_index.py`) maps XML ids to
  source lines through lxml, so every P&ID finding names `file:line`. Drawing rules, tag rules
  and tag references in texts (`tag_rules.py`, `tagrefs.py`) also read the XML with lxml.
- **`cheme show`** (`domains/piping/show.py`): it prints `file:start-end` of an object and of
  its drawing from the XML text.
- **`copy`, `fragment`, `move`, `rename`, `set` and the authoring API**
  (`domains/piping/authoring/`): they edit or print XML text directly, so the result stays a
  minimal text diff. The `dexpi-xml` snippets and `shapes.md` are generated from a reference XML
  by `scripts/build_snippets.py`.
- **The skills** `dexpi-xml`, `pid-edit` and `pid-draft` teach agents to edit the XML as text.
  `lists-sync` and `review` quote XML ids.
- **The viewer and SVG export**: `/api/pid.svg` renders through pyDEXPI's SVG export from the
  loaded model, which would work from any format pyDEXPI loads. `/api/diff` and
  `cheme diff` use pyDEXPI's `id_diff` on models, but `diffview` maps changes back to XML
  elements for the drawing (`_represented_by`), and `/api/file` serves the raw text.
- **Benchmarks: none.** Core has no benchmark or evaluation code that reads DEXPI files, so none
  would need porting. Evaluation material stays in the research repositories.

### How to keep the format replaceable

1. **One load and save path per format.** P&ID models are loaded and exported through
   `domains/piping/dexpi_io.py` (`load`, `dump`); `tests/test_boundaries.py` checks that no
   other module calls pyDEXPI's loader or serializer. The one remaining direct caller is
   `domains/process/sheets.py`, which writes the BFD/PFD: `process` may not import `piping`,
   and changing it changes the generator fingerprint. When a second format arrives, move the
   seam to `integrations/pydexpi.py` so that both domains share it, and rebuild the examples once.
2. **A per-sheet `format` in `plant.yaml`**, optional and defaulting to `xml`, so existing
   repositories stay valid without edits. `Workspace.pid_files()` and the sheet kinds would read
   it, and `dexpi_io.load` would dispatch on it.
3. **XML as an export target.** For tools that need DEXPI XML (other CAD tools, the
   reference viewer, exchange with partners), a command such as `cheme export --xml` would
   write it from any stored format. The stored format is what agents edit and git diffs.
4. **Text-level tools per format.** `fmt`, `show`, the line-number index and the authoring
   API are XML-specific by nature. With YAML they would get YAML counterparts (YAML line numbers
   already exist in `foundation/yamlsource.py`), or they would stay XML-only and refuse YAML
   sheets with a finding that names the format.

### Open questions

- **Drawing data.** Does the YAML hold the diagram (positions, shapes, labels), or only the
  engineering model with the graphics kept elsewhere? P&IDs in core are drawn sheets. Losing
  the drawing would break `render`, the drawing rules and the viewer.
- **Round-trip fidelity.** Is XML -> YAML -> XML lossless for everything core relies on: ids,
  `ConceptualModel` vs drawing split, generic attributes, the provenance comment, element
  order? This needs a corpus test in pyDEXPI over the template, the examples and real plant
  repositories.
- **Id stability.** Readable ids from `fmt` are the keys of review quotes, `accept:` entries,
  finding ids and `basis` references. A YAML form must keep them unchanged and must not
  regenerate them.
- **Mixed repositories.** Can one repository hold XML and YAML sheets at once? Cross-sheet rules
  (off-page connectors, tag uniqueness, lists vs P&IDs) work on models and would allow it, but the
  text tools and the skills would have to handle both.
- **Migration command.** A `cheme migrate --to yaml SHEET` would convert a sheet, check the
  round trip (models equal under `id_diff`), update `plant.yaml` and the `.gitattributes`
  pattern, and commit the change as a single rename-and-rewrite commit, so that history stays
  traceable.
- **Process models.** Does `process/*.yaml` become the pyDEXPI process YAML, or do the two map
  onto each other? Core's YAML carries provenance per value (`given`/`assumed`/`calculated`),
  cases and layout overrides, which a DEXPI process model does not have today.

### Recommendation on sequencing

1. Leave core on XML until pyDEXPI has the YAML format with a tested round trip on a corpus that
   includes core's template and examples.
2. Then add the optional `format` key and the dispatch in `dexpi_io`, with the seam moved to
   `integrations/pydexpi.py`. Add read support first: `validate`, `render`, `diff`, `status` and the
   viewer endpoints on YAML sheets. `fmt`, `show` and the authoring commands refuse YAML sheets
   with a clear finding.
3. Then add `cheme export --xml` and the migration command, and try both on one real plant
   repository.
4. Port the text tools and skills to YAML only if agents and reviewers find the YAML form better
   in practice.
5. Consider converging `process/*.yaml` with a pyDEXPI process YAML last, as a migration of the
   format with `process build` kept as the generator. It should not be a precondition for
   anything above.
