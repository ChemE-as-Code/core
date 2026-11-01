# Framework restructuring: summary

`cheme-as-code` is now the initial ChemE-as-Code framework. It is still one installable package
with the same name, CLI, entry point (`chemeascode.interfaces.cli:app`), commands, options and
`cheme serve` endpoints. The restructuring was incremental: modules moved to their owners.
Pre-1.0, the old import paths were then removed rather than kept.

## What changed

- **Structure.** `foundation/` (findings, workspace, git queries, reviews, provenance, units,
  the common schemas), `domains/` (ten domains), `project/` (workspace-wide composition:
  validate, gates, sign-off, status, impact), `interfaces/{cli,api}` (`interfaces/mcp` has a
  boundary README only), `integrations/` (git, pyDEXPI glue, web and service adapters, thermo,
  RDKit) and `templates/`. Responsibilities and import rules are in
  [architecture.md](architecture.md), and `tests/test_boundaries.py` enforces them.
- **No compatibility layer.** The 45 old module names (for example `chemeascode.validate`,
  `chemeascode.process`, `chemeascode.authoring`, `chemeascode.cli`) no longer import; generator
  scripts import `chemeascode.domains.piping.authoring`. `tests/test_old_paths.py` checks that a
  representative set stays removed. The full table, including what was deferred, is [migration-table.md](migration-table.md).
- **Schemas** live with their owners. `chemeascode.schemas` remains the catalogue, and
  `cheme schema` output is byte-identical.
- **Skills** live with their domain (`domains/<d>/skills/<name>/`), use one seven-section
  structure, and are installed into `.claude/skills/<name>/` as before. A manifest of known
  versions backs `cheme skills status|update`, which never overwrites a locally modified
  skill without `--force`.
- **Pattern.** `domains.process.streams.stream_report(root, case)` is the engineering function,
  and `cheme process streams` only formats it. Its output was byte-identical before and after
  the refactor.
- **Provenance and change impact.** `foundation.provenance` covers source revisions,
  fingerprints and the relations derived-from, represents, analyses and depends-on. Review records
  take an optional `basis:`. The read-only `cheme impact` flags review-needed artifacts at
  level info and never regenerates anything.
- **DEXPI I/O.** `domains/piping/dexpi_io.py` is the one load/export path for DEXPI models in
  piping and project. architecture.md has a design section on a possible DEXPI YAML
  serialization; none of it is implemented.
- **LLM4ChemE migration** (cleared under AGPL by its owner; see
  [llm4cheme-migration.md](llm4cheme-migration.md)):
  - units (`foundation.units`, with Pint optional);
  - thermodynamic model selection, phase calculations, separation method selection and pinch
    analysis (`domains/process`);
  - property retrieval and kinetics (`domains/chemistry`, adapters in `integrations/`);
  - OSHA hazard data (`domains/safety`);
  - `cheme chemistry props`;
  - five skills.

  None of it imports an LLM or agent library. The ported tests pass, and network access is mocked.
- **pi-agent-kit** is inventoried only and nothing was copied
  ([companion-inventory.md](companion-inventory.md)).
- **Contributor guide**: [contributing.md](contributing.md).

## Verification (final session)

- Full test suite, ruff check and ruff format check: green.
- Wheel built and installed into a fresh virtual environment: `cheme --help`, `init` (skills
  and their resources installed) and `validate` work.
- `import chemeascode`, foundation, every domain and the main Python entry points load none of
  thermo, chemicals, Pint, RDKit, FastAPI, uvicorn, resvg or Typer.
- Serve tests and the viewer's contract tests pass.
- No pyDEXPI editor command, patches or MCP-server import. No downstream product name in the
  diff or the commit messages.

The commands and their results are in the session report, outside the repository.

## Limitations

- `cheme init` writes five more skills than before, and the earlier skills have a new
  section structure. Both changes are intended, and the golden manifest records them.
- Existing generated BFD/PFD sheets report `cheme.generated-version` until
  `cheme process build` is run once, because the generator code moved.
- The chemistry web adapters are tested on recorded response shapes, not against the live sites.
  The ChemSep SRK data is no longer shipped: its licence is unconfirmed for the IPD files
  (`data/chemsep/SOURCE.md`), and `cheme data fetch chemsep-srk` installs it per user.
- Three layer-rule exceptions remain, each listed with its reason in `tests/test_boundaries.py`.

## Remaining migration work

- The items under "Deferred" in migration-table.md: splitting the P&ID and list rules out of
  `project/validate.py`, the three boundary exceptions, the instrument list schema, the process
  sheets' pyDEXPI calls, and public names for the foundation helpers.
- LLM4ChemE: the solvent and polymer datasets (and their SQL code) once their upstream licenses
  are recorded; folding the port/stream and step rules into `process-design` after checking them
  against `cheme validate`.
- Domains with scope documents only (`experiments`, most of `requirements`,
  `safety` beyond hazard data, equipment sizing): their first real functions.
- An MCP adapter, if wanted, along the boundary in `interfaces/mcp/README.md`.
- The project-template repository is generated from `cheme init` output and was not touched.
  Regenerate it, or its `.claude/skills/` copies will show as outdated.
