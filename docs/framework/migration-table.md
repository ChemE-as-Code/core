# Migration table

**Final status.** This table covers every module, package, skill and template directory of the
package before the restructuring: old location, new location, and the session that moved it.
**F2** is the restructuring session; **R** is the final review session, which moved the schemas;
**C1** removed the compatibility layer. **Later** marks what is deferred (summary below).

**No compatibility layer.** Pre-1.0, the owner decided against keeping old import paths. Until
C1 an alias finder (`chemeascode/_moved.py`) made every old name import the module of its new
name; C1 deleted it together with `tests/test_compat.py` and updated every reference in `src/`,
tests, skills, `templates/project/`, `examples/`, `scripts/` and the docs. An old path now
raises `ModuleNotFoundError`; `tests/test_old_paths.py` checks a representative set so that no
shim comes back by accident. The console script is `chemeascode.interfaces.cli:app`;
`python -m chemeascode` still works. CLI commands, options and `cheme serve` endpoints are
unchanged.

- **F2** moved the Python modules, the bundled skills and the template data. `Report` stays in
  `project/validate.py` (see architecture.md).
- **F3** moved no module. It added `foundation/provenance.py`, `project/impact.py`,
  `interfaces/cli/skills.py` and `templates/skills-manifest.json` (written by
  `scripts/build_skill_manifest.py`), and `domains/process/streams.py` gained `stream_report`.
  The list parsing of `project.status._lists` became `foundation.workspace.Workspace.parsed_lists`
  (`_lists` stays as a wrapper).
- **M1/M2** added the LLM4ChemE modules (new paths only, see below).
- **R** moved the schema modules to their owners (rows marked R) and added
  `domains/piping/dexpi_io.py`, the one load/export path for DEXPI models in piping and project.
- **C1** removed the alias finder; the generator scripts of plant repositories must import
  `chemeascode.domains.piping.authoring` instead of `chemeascode.authoring`.

**Deferred (later):**

- splitting the P&ID document and list rules out of `project/validate.py` into
  `domains/{piping,equipment,control}`;
- a CLI-side wrapper around `requirement_problem`, so that `foundation.workspace` stops
  importing Typer;
- moving the git textconv projection from `integrations/git.py` into `domains/piping`;
- passing the list schemas into `Workspace.parsed_lists` instead of reading the catalogue;
- splitting the instrument list schema from `domains/piping/schemas/lines.py` into `control`;
- moving `domains/process/sheets.py`'s direct pyDEXPI load/export behind a shared seam in
  `integrations/pydexpi.py`. This changes the generator fingerprint, so do it together with
  another generator change;
- public names, with aliases, for the underscore helpers in `foundation` (`_yaml_line`,
  `_entries`, ...).

The three boundary exceptions in `tests/test_boundaries.py` are the second, third and fourth of
these items: each still breaks a layer rule today.

## Generator fingerprint

`process.provenance.generator_fingerprint()` hashes every `*.py` in `domains/process/` by name
and content. A change there makes every generated BFD/PFD report `cheme.generated-version`
(a warning) until `cheme process build` is run. The examples and test data in this
repository were rebuilt in C1.

## Python modules

| Old location | New location | Compatibility | When |
|---|---|---|---|
| `chemeascode/__init__.py` | unchanged | no imports (the alias finder it installed was removed in C1) | F2, C1 |
| `chemeascode/__main__.py` | unchanged | imports `chemeascode.interfaces.cli` | F2 |
| `validate.py` `Finding`, `Level`, `_SEVERITY` | `foundation/findings.py` | none: old path removed; `project.validate` imports them | F2 |
| `validate.py` `Report` | stays in `project/validate.py` | `drawing_lines()` reads piping's drawing rules | n/a |
| `validate.py` `_compose`, `_yaml_line`, `_entries`, `_duplicates` | `foundation/yamlsource.py` | none: old path removed; `project.validate` imports them | F2 |
| `validate.py` `accept_matches`, `accepted_entries`, `acceptance` | `foundation/acceptance.py` | none: old path removed; `project.validate` imports them | F2 |
| `validate.py` `_LOADER_LEVELS`, `_RULE_LEVELS` | `integrations/pydexpi.py` | none: old path removed; `project.validate` imports them | F2 |
| `validate.py` `SheetIndex`, `_index`, `_id_lines`, `_drawn_for`, `_POSITION`, `_UNIT_SPELLINGS` | `domains/piping/sheet_index.py` | none: old path removed; `project.validate` imports them | F2 |
| `validate.py` (rest: `validate_workspace`, `validate_pid`, list and cross checks) | `project/validate.py` | none: old path removed | F2 |
| `validate.py` P&ID document rules, list rules | `domains/piping/pid_rules.py`, `domains/equipment/list_rules.py`, `domains/control/list_rules.py` | not decided; no compatibility names | later (big, low value now) |
| `workspace.py` | `foundation/workspace.py` | none: old path removed | F2 |
| `workspace.check_requirement` (lazy Typer import; it prints and exits) | stays in `foundation/workspace.py` for now; the boundary test lists it as the one allowed exception | callers (`cli`, `serve`) unchanged; later the CLI gets its own wrapper around `requirement_problem` | later |
| `gitinfo.py` | `foundation/gitinfo.py` | none: old path removed | F2 |
| `reviews.py` | `foundation/reviews.py` | none: old path removed (after `Finding` is extracted) | F2 |
| `checks.py` | `project/checks.py` | none: old path removed | F2 |
| `signoff.py` | `project/signoff.py` | none: old path removed | F2 |
| `status.py` | `project/status.py` | none: old path removed | F2 |
| `process/` (package: `build`, `fill`, `layout`, `model`, `propagate`, `props`, `provenance`, `schema`, `sheets`, `streams`, `summary`) | `domains/process/` | none: old path removed | F2 |
| `process/cli.py` | `interfaces/cli/process.py` | none: old path removed | F2 |
| `datasheets.py` | `domains/equipment/datasheets.py` | none: old path removed | F2 |
| `interlocks.py` | `domains/control/interlocks.py` | none: old path removed | F2 |
| `layout_validate.py` | `domains/spatial/layout_validate.py` | none: old path removed | F2 |
| `layout_distances.py` | `domains/spatial/layout_distances.py` | none: old path removed | F2 |
| `piping_items.py` | `domains/piping/piping_items.py` | none: old path removed | F2 |
| `tag_rules.py` | `domains/piping/tag_rules.py` | none: old path removed | F2 |
| `tagrefs.py` | `domains/piping/tagrefs.py` | none: old path removed | F2 |
| `sheet_query.py` | `domains/piping/sheet_query.py` | none: old path removed | F2 |
| `sheets.py` | `domains/piping/sheets.py` | none: old path removed (`TEMPLATE_SHEET` follows the snippet move) | F2 (path in F3) |
| `drawing.py` | `domains/piping/drawing.py` | none: old path removed | F2 |
| `generators.py` | `domains/piping/generators.py` | none: old path removed | F2 |
| `fmt.py` | `domains/piping/fmt.py` | none: old path removed | F2 |
| `render.py` | `domains/piping/render.py` | none: old path removed (resvg stays lazy) | F2 |
| `show.py` | `domains/piping/show.py` | none: old path removed | F2 |
| `diffview.py` | `domains/piping/diffview.py` | none: old path removed | F2 |
| `authoring/` (`_xml`, `builders`, `copy`, `edit`, `fragment`, `fragment_items`, `shapes`, `sheet`) | `domains/piping/authoring/` | none: old path removed (generator scripts must import `chemeascode.domains.piping.authoring`) | F2 |
| `gitsetup.py` | `integrations/git.py` | none: old path removed | F2 |
| `cli.py` | `interfaces/cli/__init__.py` (the `app`) | none: old path removed; the entry point is `chemeascode.interfaces.cli:app` | F2, C1 |
| `cli_edit.py`, `cli_scripts.py`, `sheet_cli.py` | `interfaces/cli/edit.py`, `scripts.py`, `sheet.py` | none: old path removed | F2 |
| `run.py` | `interfaces/cli/run.py` | none: old path removed | F2 |
| `serve.py` | `interfaces/api/serve.py` | none: old path removed (endpoints unchanged) | F2 |
| `init.py` | `templates/install.py` | none: old path removed (`template_dir()` keeps its name and return type) | F2 |
| `schemas/__init__.py` (aggregate used by `cheme schema NAME`) | unchanged path | keeps re-exporting every schema class (same objects), now from the owners | n/a |
| `schemas/_base.py` | `foundation/schema_base.py` | none: old path removed | R |
| `schemas/plant.py`, `checks.py`, `status.py`, `reviews.py` | `foundation/schemas/` | none: old path removed | R |
| `schemas/design_basis.py` | `domains/requirements/schemas.py` | none: old path removed | R |
| `schemas/equipment.py`, `datasheet.py` | `domains/equipment/schemas/equipment.py`, `datasheet.py` (kept as two modules, so `git log --follow` keeps both histories; the plan had one module) | none: old path removed | R |
| `schemas/lines.py` (line and instrument list) | `domains/piping/schemas/lines.py` | none: old path removed (splitting off the instrument list into control comes later) | R |
| `schemas/piping_items.py` | `domains/piping/schemas/piping_items.py` | none: old path removed | R |
| `schemas/interlocks.py` | `domains/control/schemas.py` | none: old path removed | R |
| `schemas/layout.py` | `domains/spatial/schemas.py` (now also defines `LAYOUT_SCHEMAS`, re-exported by the catalogue) | none: old path removed | R |

F2 moved only Python files, and kept their content apart from import lines. The schemas were
deferred from F3 and F4 and moved in the final session R. `cheme schema` (the listing and the
JSON Schema of all 16 kinds) was snapshotted before the move and is byte-identical after it.

## New packages without moved code (F2)

`foundation/`, `domains/<d>/` (an `__init__.py` with a docstring only, no imports), `project/`,
`interfaces/{cli,api}/`, `integrations/`, `templates/`. Domains without code get a
`README.md` scope document only: `requirements` (until R moved its schema in), `chemistry` and
`safety` (until M2), `experiments`, `assessment`. `interfaces/mcp/` has `README.md` only and no `__init__.py`, so nothing
importable promises an adapter.

## LLM4ChemE (M1, M2)

New modules, no old `chemeascode` paths: the per-component table, with what was
not migrated and why, is [llm4cheme-migration.md](llm4cheme-migration.md). New in M2:
`domains/chemistry/{properties.py,kinetics/,skills/}`, `domains/safety/hazard_data.py`,
`integrations/{http,pubchem,cactus,nist_webbook,osha,thermo,unifac,rdkit,prediction_services,nist_kinetics,rmg}.py`, `interfaces/cli/chemistry.py` (`cheme chemistry props`), extra
`chemistry` (rdkit).

## New in R

| New | What | Compatibility |
|---|---|---|
| `domains/piping/dexpi_io.py` | `load(content, strict=...)` and `dump(model, metadata)`, wrapping pyDEXPI's public XML loader and serializer; `fmt`, `render`, `sheets`, `sheet_query`, the authoring API and `project.validate` call it | internal; the functions it replaced were not public. `test_boundaries` checks that only it and `domains/process/sheets.py` call the pyDEXPI loader or serializer |
| `foundation/schemas/__init__.py`, `domains/{equipment,piping}/schemas/__init__.py` | packages for the moved schemas | the old `chemeascode.schemas.<name>` paths were removed in C1; `chemeascode.schemas` stays the catalogue |

## Template, skills and data

| Current | New | Treatment | When |
|---|---|---|---|
| `template/dot-claude/skills/dexpi-xml/` (`SKILL.md`, `NOTICE.md`, generated `shapes.md` and `snippets/`) | `domains/piping/skills/dexpi-xml/` | installer maps it to `.claude/skills/dexpi-xml/`; `scripts/build_snippets.py` `OUT` and `sheets.TEMPLATE_SHEET`/`authoring.shapes` paths updated | F2 (moved early) |
| `template/dot-claude/skills/pid-draft/`, `pid-edit/`, `lists-sync/` | `domains/piping/skills/<name>/` | installer mapping | F2 (moved early) |
| `template/dot-claude/skills/process-design/` | `domains/process/skills/process-design/` | installer mapping | F2 (moved early) |
| `template/dot-claude/skills/layout-yaml/` | `domains/spatial/skills/layout-yaml/` | installer mapping | F2 (moved early) |
| `template/dot-claude/skills/review/` | `project/skills/review/` (it runs validate, checks, render and sign-off) | installer mapping | F2 (moved early) |
| `template/dot-claude/settings.json` | `templates/project/dot-claude/settings.json` | moved data, same install path | F2 (moved early) |
| `template/` (everything else: `AGENTS.md`, `CLAUDE.md`, `DESIGN.md`, `PROGRESS.md`, `README.md`, `STAGES.md`, `plant.yaml`, `checks/`, `control/`, `equipment/` with `datasheets/`, `layout/`, `pid/`, `piping/`, `process/`, `reviews/`, `scripts/` with `agent-run/`, `dot-github/workflows/validate.yml`, `dot-gitattributes`, `dot-gitignore`) | `templates/project/` | moved data; `template_dir()` returns the new place; `init` output is byte-identical (`tests/test_init_golden.py` compares the file tree and hashes with `tests/data/init-manifest.txt`, recorded before the move) | F2 (moved early) |
| `scripts/build_snippets.py` | unchanged | `OUT` points at `domains/piping/skills/dexpi-xml` | F2 (moved early) |
| `pyproject.toml` `per-file-target-version` for `template/scripts/agent-run/*.py` | `templates/project/scripts/agent-run/*.py` | path updated | F2 (moved early) |
| `AGENTS.md` lines naming `src/chemeascode/template/` and the snippets path | updated paths; the boundary rule line stays verbatim | docs | F2 (moved early) |
| `tests/` that use literal template paths (`test_snippets.py`, `test_fragment_items.py`, `test_scripts.py`, `test_dogfood_fixes.py`, `test_authoring.py`, `test_edit.py`, `test_gates.py`) | read through `template_dir()` or a new `bundled_skills()` helper | test update | F2 (moved early) |

Hatch packages `src/chemeascode` with all non-ignored files, which is how the template ships
today. Skill directories under `domains/*/skills/` ship the same way. F3 checks this with
`uv build` and a listing of the wheel.

**Intended changes to `cheme init` output.** The install mechanism and paths are unchanged
(skills still go to `.claude/skills/<name>/`, `dot-` files are renamed as before). The written
content changed on purpose, each time with `tests/data/init-manifest.txt` regenerated in the same
commit: in F3, the seven `SKILL.md` files (common section structure), `reviews/README.md`
(`basis:`) and `AGENTS.md` (the `impact` and `skills` rows); in M1 and M2, five new skills
(`phase-calculation`, `thermodynamic-model-selection`, `separation-method-selection`,
`property-retrieval`, `materials`). In C1, the template's `AGENTS.md`, `scripts/README.md` and
`scripts/example_draft.py` and the `dexpi-xml`, `pid-draft` and `pid-edit` skills name
`chemeascode.domains.piping.authoring` instead of `chemeascode.authoring`.

## Unchanged

- The CLI commands and options, including `init --force`, which keeps its current semantics
  (`init` now also reports a locally modified skill it kept or replaced). Safe skill updates
  come in through the new `cheme skills status|update`; change impact through the new
  read-only `cheme impact`.
- `cheme serve` endpoints and payloads (`/api/repo`, `branches`, `log`, `tree`, `file`,
  `pid.svg`, `diff`, `yaml`, `layout`, `status`, `interlocks`, `streams`, `validate`, `session`,
  `checks/run`, `checks`, the SPA fallback). C1 added `GET /api/impact` (the `cheme impact --json`
  report) for the viewer.
- File formats and schema ids (`cheme/process/v1`), finding rule ids, `status.json`, and the
  review record format, apart from the optional review `basis:` list (F3; records without it
  parse as before).
- `tests/`, `docs/`, `scripts/`, and CI (`.github/workflows/ci.yml`).
