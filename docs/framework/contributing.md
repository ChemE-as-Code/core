# Contributing to the framework

This guide says where new code, skills, schemas and integrations go in `cheme-as-code`, and which
rules keep the package usable from the CLI, the viewer API, agents and downstream applications
alike. Read [architecture.md](architecture.md) for the reasons behind the rules. The repository
conventions in `AGENTS.md` (Python 3.12+, uv, ruff line length 100, pytest) apply throughout.

## Where things go

Work through this list from the top. The first match is the place.

1. **An engineering method** (a calculation, a rule that produces findings, a loader, a
   generator) goes in the domain that owns the subject: `domains/<d>/<module>.py`. Use the
   domain table in architecture.md; if two domains seem to fit, take the one the information
   flows *from* (a balance belongs to `process`, even if `assessment` reports it).
2. **A schema of a file in a plant repository** goes next to the code that reads it:
   `domains/<d>/schemas.py` (or `domains/<d>/schemas/<name>.py` when a domain has several),
   built on `foundation.schema_base.Strict`; a file every repository has (`plant.yaml`,
   checks, status, review records) goes in `foundation/schemas/`. Re-export the model from the
   catalogue `chemeascode.schemas` (and `LIST_SCHEMAS`/`OTHER_SCHEMAS` when `cheme schema` should
   list it). Domain code imports the owner module, not the catalogue. Add optional fields only:
   an existing plant repository must stay valid without edits.
3. **Something every domain needs** (findings, YAML line numbers, workspace paths, git queries,
   review records, provenance) goes in `foundation/`, but only when it holds no engineering
   knowledge. Keep foundation small; when in doubt, keep the code in its domain.
4. **Composition over the whole workspace** (validate everything, evaluate gates, sign-off,
   status, change impact) goes in `project/`.
5. **A wrapper over an external program or library** (git configuration, thermo, resvg, a
   simulator, a CAD exchange format) goes in `integrations/`, with the optional import inside the
   function. Domain code calls the wrapper; it does not import the library itself.
6. **A command** goes in `interfaces/cli/`, **an endpoint** in `interfaces/api/serve.py`. Both
   only parse input, call one function of a domain or of `project`, and format the result. If
   you are writing an engineering rule in an interface, move it down first.
7. **A skill** goes with the capability it drives: `domains/<d>/skills/<name>/SKILL.md`
   (workspace-wide skills: `project/skills/<name>/`), with `scripts/`, `references/` or
   `examples/` beside it where useful. See "Adding or changing a skill".
8. **Project template files** (what `cheme init` writes besides the skills) go in
   `templates/project/`. A file whose name starts with `dot-` is written as `.<rest>`.

A domain without code keeps only its `README.md` scope document. Do not add empty classes,
placeholder functions or tools that return invented results; add the first real function
instead.

## Import rules

```
interfaces  ->  project  ->  domains  ->  foundation
     |             |            |
     +-------------+------------+-->  integrations  ->  foundation
templates  ->  foundation
```

- `foundation` imports no domain, `project`, interface, integration or template.
- A domain imports `foundation`, `integrations` and the domains architecture.md allows it.
  Feedback in the other direction (a safety finding that sends the team back to chemistry)
  travels through files and review records, not imports.
- Typer only in `interfaces/cli`, FastAPI and uvicorn only in `interfaces/api`.
- `foundation/__init__.py` and every `domains/<d>/__init__.py` import nothing.

`tests/test_boundaries.py` checks every import, including those inside functions, and imports the
basic modules in a fresh interpreter to make sure no optional dependency loads. A rule the code
still breaks is listed in its `EXCEPTIONS` with the reason; the test fails once an exception is
no longer needed, so remove it when you fix the cause.

## Optional dependencies

- Base dependencies are what `import chemeascode` and a plain `cheme validate` need. Anything
  heavy (thermodynamics, simulators, CAD, ML models, web servers) goes into an extra in
  `pyproject.toml` (today `props`, `serve`, `png`, `units`, `chemistry`, `lca`).
- Import an optional library inside the function that uses it, never at module level, and
  only from `integrations/` or the domain function that needs it. When it is missing, return
  a finding or raise an error that names the extra (`pip install 'cheme-as-code[props]'`).
- Add the library to `LAZY_ONLY` and `OPTIONAL` in `tests/test_boundaries.py`.
- Agents and LLMs are never a dependency of a deterministic function. A skill may call an agent
  workflow; a domain function may not.

## The pattern: one implementation, called from Python and the CLI

`cheme process streams` is the worked example
(`src/chemeascode/domains/process/streams.py`, `tests/test_stream_report.py`):

1. **The function lives in the domain** and takes explicit inputs:
   `stream_report(root: Path, case: str | None = None) -> StreamReport`. It never reads the
   current directory, never prints, never exits.
2. **The result is structured**: a dataclass with the values and their units, per-value
   provenance (`given`, `assumed`, `calculated`), the findings (`Finding`, each with file, line,
   rule id and hint) and a `SourceRevision` (git commit, dirty inputs, sha256 per input file,
   from `foundation.provenance`), so a caller can check later that the result still applies.
   Input problems are findings; only a wrong call (no plant repository, an undeclared case)
   raises.
3. **The command is a thin wrapper**: it finds the workspace, calls the function, maps
   exceptions to exit codes and formats the result. Keep existing output byte-identical when
   refactoring a command onto a function: snapshot it before, compare after.
4. **Tests** compare the CLI output with the function's result, call the function from another
   working directory, and import it in a subprocess to show it needs neither Typer nor FastAPI.

A worker on a project snapshot uses the same functions: check out or export the revision into a
directory, call the function with that directory, return the result with its `source`.

## Provenance and change impact

- An artifact is identified by its path from the repository root. A source revision is a commit
  sha or `sha256:<hex>` of a file (`foundation.provenance.file_fingerprint`).
- A result computed from files should carry a `SourceRevision`
  (`foundation.provenance.source_revision(root, paths)`).
- A relationship that the existing mechanisms do not record goes into an optional
  `basis: [{path, revision, relation}]` list, with `relation` one of `derived-from`,
  `represents`, `analyses`, `depends-on`. Review records have it today.
- `project/impact.py` turns changed sources into `cheme.review-needed` findings at level
  info. A new artifact kind with recorded sources adds a collector there. Never regenerate,
  rewrite or declare anything invalid from it.

## Adding or changing a skill

1. Put it in `domains/<d>/skills/<name>/SKILL.md` (or `project/skills/<name>/`). Skill names are
   unique across the package; `templates.install.bundled_skills()` refuses duplicates.
2. Keep the frontmatter (`name`, `description`) and use the seven sections, in this order:
   *Purpose and when to use*, *Required inputs and missing inputs*, *Workflow and tools*,
   *Validation and failure handling*, *Outputs and provenance*, *Required human judgment*,
   *References*.
3. A skill describes judgment and workflow and calls `cheme` commands. Shared engineering
   algorithms belong in a domain function, not in a skill script.
4. Run `uv run python scripts/build_skill_manifest.py` and
   `uv run python tests/test_init_golden.py > tests/data/init-manifest.txt`, and commit both
   outputs. `tests/test_skills.py` fails while the manifest lacks the current hash, so that
   `cheme skills status` can tell an outdated installed copy from a locally changed one.
5. `cheme init` and `cheme skills update` never replace a locally modified skill
   without `--force`; keep it that way.

## Moving a module

There is no compatibility layer for internal modules: a move changes the import path. Moving a
module on the documented Python API (ADR 0032) is a breaking change and needs a new major
version, or the new path first and the removal in the next major.

1. `git mv` the file, so `git log --follow` keeps its history. Change only import lines.
2. Update every reference to the old path: `src/`, tests, skills (`SKILL.md`, scripts),
   `templates/project/`, `examples/`, `scripts/` and the docs. Do not add a shim or alias
   module; `tests/test_old_paths.py` checks that the removed top-level names stay removed.
3. Add a row to [migration-table.md](migration-table.md) and a CHANGELOG entry, since plant
   repositories' generator scripts may import the old path.
4. Anything under `domains/process/*.py` changes `generator_fingerprint()`. Rebuild the examples
   (`uv run --directory examples/<example> cheme process build`) and commit the sheets;
   only `generator_sha256` changes.

## Releases and versions

cheme-as-code follows semantic versioning from 1.0.0 (ADR 0032). A release sets `version` in
`pyproject.toml` (then `uv lock`), adds a dated CHANGELOG section (with "Breaking" first when
there is one, and its migration), and is tagged on `main` after the merge with an annotated
`vX.Y.Z` tag and a GitHub release whose notes are that CHANGELOG section. A breaking change to
the public interface the ADR lists needs a new major version.

## Architecture decisions

A change that alters the architecture (layers, module ownership, import rules, base versus
optional dependencies, a new out-of-process worker), a public file format or schema, the agent
interface (commands, findings, skills) or a contract with another ChemE-as-Code repository (the
viewer API, the project template, the process library) adds a new Architecture Decision Record in
`docs/adr/`, or supersedes an existing one, in the same pull request. Copy
`docs/adr/template.md`, add the record to the index in [the ADR overview](../adr/README.md) and to `nav` in
`mkdocs.yml`. An accepted ADR is not rewritten: a new one supersedes it. ADRs record decisions
about this software; a plant's engineering decisions belong in that plant's `DESIGN.md`.

## Tests

- Tests live in `tests/`, one file per feature or module, and import the modules from their
  current paths.
- Test behaviour, not folder layout: an output, a finding, a refusal, an import that must not
  happen.
- `tests/test_init_golden.py` pins what `cheme init` writes. Regenerate the manifest only for
  an intended change and say so in the commit message.
- A test that reads Rich help or error text strips ANSI codes first
  (`re.sub(r"\x1b\[[0-9;]*m", "", output)`): CI forces coloured output, so a test that passes
  locally can fail there.
- Run `uv run pytest -q` and `uv run ruff check . && uv run ruff format --check .` before every
  commit.
- Catch the exceptions you expect. An `except Exception` is for a reporting boundary (a file,
  pyDEXPI or a third-party library that can fail in any way, reported as a finding or an error)
  and carries `# noqa: BLE001 - <why>`. Every `subprocess.run` passes `check=`; a `noqa` names
  the rule it silences, and ruff (`RUF100`) flags one that silences nothing.

## Web databases and prediction services

An adapter to a web database or a service goes in `integrations/<name>.py` and takes an
`integrations.http.HttpClient` argument; the parsing of a page is a separate function of the
HTML, tested on a saved snippet. A service endpoint is a required argument: no default host,
no environment variable, no key read at import. Tests never touch the network; a live test is
skipped unless `CHEME_NETWORK_TESTS=1`. The domain function chooses between sources and
returns the source with every value.

## Research and paper projects

Paper-specific experiments, manuscripts, datasets and results do not belong in this
repository. A research project is its own repository that depends on the package:

```toml
[project]
dependencies = ["cheme-as-code[props] @ git+https://<host>/<org>/core@<tag-or-sha>"]
```

Pin a tag or commit, so that results stay reproducible, and record that pin with the results.
Import the domain functions (`chemeascode.domains.process.streams.stream_report`, ...) rather than
the CLI. When a method from a research project turns out to be generally useful, contribute it
here as a domain function with tests, following this guide, and keep the experiment in the
research repository.

Code from other repositories comes in only when its licence allows it under AGPL-3.0-or-later;
[companion-inventory.md](companion-inventory.md) lists candidate components and their status.

## Documentation site

The documentation site is built with MkDocs Material from `mkdocs.yml` and `docs/` (dependency
group `docs`). Preview it with live reload, or build it as CI does:

```sh
uv sync --all-extras --group docs
uv run --group docs mkdocs serve           # http://127.0.0.1:8000, rebuilds on changes
uv run --group docs mkdocs build --strict  # site/, fails on any warning
```

Most guide pages contain no copy of their text: a comment such as
`<!-- readme: ### process: BFD, PFD, stream table and properties -->` includes that section of
`REFERENCE.md`, the full reference (or, with `include:`, of another repository file such as the project template's
`STAGES.md`) when the site is built (`docs/hooks/includes.py`). Change REFERENCE.md, not the page;
renaming a heading there that a page includes fails the strict build. The CLI, schema and serve
API reference pages are not files at all: `docs/hooks/reference.py` generates them from the
Typer app, the `cheme schema` catalogue and the OpenAPI document of `cheme serve` on every build.
A new page must be added to `nav` in `mkdocs.yml`.
