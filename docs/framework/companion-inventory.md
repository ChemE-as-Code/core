# Companion repositories: reusable-component inventory

This inventory covers `pi-agent-kit` and `LLM4ChemE`, both inspected read-only in October 2026.

## Licensing

Both repositories carry a proprietary **Trade Secret License**, while `core` is
**AGPL-3.0-or-later**. A component can enter `core` only in one of two ways:

1. **Relicensing.** Its owners relicense the component under AGPL-3.0-or-later (or a
   compatible license) and contribute it. Third-party data has its own terms: LLM4ChemE's
   `offline_databases/{polymers,solvents}` each carry their own `LICENSE` and `SOURCE.md`, and
   those terms decide separately.
2. **Staying external.** The component remains where it is. A project, or a downstream
   application, depends on it next to `core`. `core` never imports it.

**LLM4ChemE is in category 1.** It is owned by the same group as `core`, and its owner has
cleared its code and skills for migration into `core` under `core`'s license, AGPL-3.0-or-later
(the license at the time of clearing and again now). Third-party data
that moves keeps its own `LICENSE` and `SOURCE.md` files, and a dataset moves only if its license
permits redistribution in an AGPL-3.0-or-later package. What moves, where, and what stays is tracked in
[llm4cheme-migration.md](llm4cheme-migration.md); the LLM4ChemE table below is the original
inventory. After M2 every row is either in `core` or recorded there as not migrated; the
solvent and polymer datasets stay in LLM4ChemE until their upstream licenses are recorded.

**pi-agent-kit stays in category 2.** It is not cleared; nothing from it is copied into `core`.
The "Target" column of its table only records where a component would belong after relicensing.

## pi-agent-kit

The package is still `template-ML-repo`, a project template whose only runtime dependency is
`requests`. It has 2 test files and CI (ruff, pyright, pytest).

| Component | What it does | Deps | Tests | Target | Blockers |
|---|---|---|---|---|---|
| `tools/property_retrieval/online_retrieval.py` | PubChem lookup by name: formula, molar mass, SMILES, InChIKey, descriptors | requests (network) | yes | `domains/chemistry` (property sources) as an `integrations/pubchem` adapter | license; network access must stay optional and cached |
| `skills/property-retrieval/` (`SKILL.md`, `scripts/batch_lookup.py`) | agent skill and batch script around the tool above | requests | yes | `domains/chemistry/skills/` | license; the script should call the shared function, not keep its own copy |
| CI, Dockerfile, README template | project scaffolding | none | n/a | none | nothing to migrate |

## LLM4ChemE

The package is `llm4cheme`. Its dependencies are langchain/langgraph, OpenAI/Ollama/Mistral
clients, thermo, rdkit, Pint, scipy and pandas. It pins pyDEXPI-dev by commit. There are about
113 test files, and CI runs ruff, pyright and pytest, with testcontainers for Postgres.

| Component | What it does | Deps | LLM-coupled | Tests | Target | Blockers |
|---|---|---|---|---|---|---|
| `src/domain/`, `src/application/`, `src/infrastructure/` (agents, routers, LLM factories, YAML graph factory, skill loader), `src/cli.py`, `main.py`, `configs/` | multi-agent framework and runtime | langchain, langgraph, LLM SDKs | yes | yes | stays external (agent runtime; `core` stays usable without one) | LLM runtime; license |
| `src/tools/dexpi_process/` | deterministic edits of a DEXPI ProcessModel | pyDEXPI | no | yes | none | **uses pyDEXPI's private editor layer** (its `process.*` commands), which `core` must not use; core edits files directly |
| `src/llm_tools/dexpi_process/` | LLM tool wrappers and argument schemas for the above | pyDEXPI, langchain | yes | yes | none | private editor layer; LLM-coupled |
| `src/workflows/dexpi_process/` (graph state, document, edit summary, validation report, serialization) | graph state around a ProcessModel; edit summaries through pyDEXPI diff | pyDEXPI, langgraph | yes | yes | none | `process_model_document.py` and `validation_report.py` reference a private pyDEXPI extension package; editor layer; LLM state |
| `skills/general-dexpi-operations`, `materials`, `process-steps-and-streams` (with `references/`) | DEXPI ProcessModel skills and class references | none | skill text | yes (references checked against pyDEXPI) | none; `core`'s process skill is YAML-first (`process-design`) | skill text written for the editor tools; `general-dexpi-operations` refers to a private pyDEXPI extension package; license |
| `src/tools/chemical_property/`, `src/databases/online_databases/` (PubChem, NIST WebBook, OSHA, thermo, UNIFAC retrieval), `cactus.py`, `rdkit_tools.py` | unified property lookup over online sources, thermo and RDKit | thermo, rdkit, requests; scrapy and selenium (extra) | mostly no | yes | `domains/chemistry` + `integrations/` (one adapter per source, optional extra) | license; network and scraping; overlaps with `core`'s pinned `thermo` adapter (`process/props.py`); OSHA data is safety-relevant |
| `src/databases/offline_databases/`, `src/tools/offline_databases/` | local solvent and polymer databases (SQLite/Postgres) with query tools | SQLAlchemy, sqlmodel, psycopg | tools yes | yes | stays external, or `integrations/` behind an extra | license plus third-party data licenses; database server dependency |
| `src/tools/phase_calculations/`, `wrapped_phase_tool.py`, `wrapped_thermo_tools.py`, `skills/phase-calculation` | flash and phase calculations | thermo, Pint | wrappers yes | yes | `domains/process` (thermodynamics), next to `process/props.py` | license; must share `core`'s pinned thermo method rather than add a second one |
| `src/tools/thermo_model_selection/`, `skills/thermodynamic-model-selection` | rule-based choice of thermodynamic model (knowledge base and inference) | none | engine no | yes | `domains/chemistry` or `domains/process` (property method choice) | license; the knowledge base's provenance must be stated |
| `src/tools/separation_selection/`, `skills/separation-method-selection`, `src/workflows/separation_method/` | separation method selection | none | partly | yes | `domains/process` (separations) | license; tied to evaluation datasets |
| `src/tools/reaction_kinetics/`, `src/databases/{nist_kinetics,rmg_kinetics,open_reaction_db}.py`, `src/schemas/reaction_kinetics.py`, `kinetics_output_schema.py`, `src/workflows/reaction_kinetics/` | kinetics retrieval and filtering (NIST, RMG, Open Reaction Database) | rdkit, requests | partly | yes | `domains/chemistry` (kinetics) + `integrations/` | license; network sources |
| `src/tools/heat_integration/`, `src/schemas/heat_integration.py` | pinch analysis | PyPinch, Pint | tools yes | not seen | `domains/process` (heat integration) | license; no tests found |
| `src/tools/unit_conversion.py`, `src/schemas/quantity.py` | unit conversion and quantity schema | Pint | no | not seen | would inform a `foundation` units convention; `core` keeps its own unit tables in `process.model` for now | license; adding Pint to `foundation` must be decided deliberately |
| `services/rmg_service/`, `services/grappa_service/`, `services/hanna_service/` and their clients (`tools_grappa.py`, `tools_hanna.py`) | FastAPI services around RMG, a GNN property model and an activity-coefficient model | RMG, ML runtimes, FastAPI, Docker | client wrappers | yes / partly | `integrations/` clients only; the services stay external | license; heavy runtimes |
| `src/evaluation/`, `src/data/*.json` (benchmark datasets), `examples/` notebooks | evaluation harness, benchmark data, tutorials | langsmith, openai | yes | yes | stays external (paper and research) | research-specific |
| `scripts/generate_pydexpi_reference.py`, `example_dexpi_bfd.py` | generate reference docs from pyDEXPI classes; example | pyDEXPI | partly | n/a | none (`core` has its own `scripts/build_snippets.py`) | license |

No component in either repository covers requirements, control, spatial or (apart from the
OSHA lookup) safety.

## Research and paper projects

A paper project is not migrated into `core`. It keeps its own repository, with its manuscript,
experiments, datasets and results, and depends on the framework:

- It pins `cheme-as-code` in its `pyproject.toml` (a git URL with a tag or commit, as `core` itself
  does for pyDEXPI), plus the extras it needs (`props`, `serve`, `png`).
- It imports domain functions directly, for example
  `from chemeascode.domains.process.model import load, balances`. It uses `cheme init` only
  when it is itself a plant repository.
- It records the `cheme-as-code` version and the git commit of its inputs alongside its results,
  using the same provenance fields `core` writes (`generator_version`, `source_sha256`, commit
  sha), so that results can be traced.
- A capability that proves reusable is proposed to `core` as an ordinary contribution, under
  AGPL, with tests. The rest stays in the paper repository.
