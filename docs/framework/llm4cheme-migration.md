# LLM4ChemE migration

LLM4ChemE (package `llm4cheme`) is owned by the same group as `core`. Its owner has cleared its
code and skills for migration into `core` under `core`'s AGPL-3.0-or-later license. Third-party
data keeps its own license, and its `LICENSE` and `SOURCE.md` files move with it.

The goal is that `core` becomes the home of LLM4ChemE's reusable, LLM-independent engineering
tools and their skills. The agent runtime, the LLM wrappers, the workflows and the evaluation
code stay in LLM4ChemE, which can depend on `cheme-as-code` for the migrated tools (see
"Research and paper projects" in [contributing.md](contributing.md)).

The migration runs in two sessions. **M1** moves the process side (units, phase calculations,
thermodynamic model selection, pinch analysis, separation method selection). **M2** moves the
chemistry side (property retrieval, databases, kinetics, prediction-service clients) and the
skill knowledge that needs it. Both sessions are done; the tables below give the final
status of every component.

## Rules applied to every migrated tool

- Typed inputs and structured results (dataclasses or pydantic models), explicit units in the
  field names or documented per field, no current-directory state, no printing, no file writes.
- No LLM, agent or LangChain import. The `llm_tools` wrappers are not migrated; what they did
  deterministically (input models, unit conversion, the result model) is part of the domain
  function now.
- Optional libraries are imported inside the function that needs them and belong to an extra
  (`pyproject.toml`). `import chemeascode` and every domain package stay free of them
  (`tests/test_boundaries.py`).
- Package data is read through `importlib.resources`, never through a path relative to the
  working directory (this replaces LLM4ChemE's `src/paths.py`).
- New process modules live in sub-packages of `domains/process/` (`thermodynamics/`,
  `heat_integration/`, `separations/`). `generator_fingerprint()` hashes only the `*.py` files
  directly in `domains/process/`, the code that generates BFD/PFD sheets, so these analysis
  tools do not make existing generated sheets outdated.
- Each tool's tests are ported to `tests/`. A test that needs an extra uses
  `pytest.importorskip`; a test that would need the network is mocked.

## Component table

Status: **M1** (moved in session M1), **M2** (moved in session M2), **no** (not migrated, with
the reason). Deps lists what the component needs in `core`; "base" means the base dependencies.

### Process side

| LLM4ChemE component | Destination in core | Status | Deps |
|---|---|---|---|
| `src/tools/unit_conversion.py` (`convert_units`, `parse_unit`), `src/schemas/quantity.py` (`ureg`) | `foundation/units.py`: `convert_units`, `parse_unit`, `registry`, plus core's pressure convention (`(a)`/`(g)` units) and `to_kpa_abs`/`to_kelvin`, which `domains/process` re-exports | M1 | base for K, °C and core's pressure units; extra `units` (Pint) for every other unit |
| `src/schemas/quantity.py` `QuantityModel`, `src/tools/heat_integration/unit_conversion.py` | none: `foundation.units.convert_units` covers the conversion; `core` already has its `Quantity` (`domains/process/schema.py`) | no (duplicate) | |
| `src/tools/phase_calculations/phase_tools.py`, `src/llm_tools/wrapped_phase_tool.py` (`phase_determination`, `EOSModel`, `ActivityCoefficientModel`, `FlashCalculationResult`) | `domains/process/thermodynamics/phase.py`: `phase_determination(...) -> FlashCalculationResult` (same signature, plus `temperature_K`/`pressure_Pa` in the result), with `EOSModel` and `ActivityCoefficientModel` | M1 | extra `props` (thermo, chemicals, numpy) |
| `src/data/srk.json`, `srk.ipd`, `convert_srk_to_json.py` (ChemSep SRK kij) | not shipped any more: `cheme data fetch chemsep-srk` installs it (`thermodynamics/chemsep_srk.py`, the converter ported); `data/chemsep/SOURCE.md` records origin and licence status | M1 | data |
| `src/tools/thermo_model_selection/` (`kb_schema.py`, `rule_inference.py`, `thermo_model_selection_rules.yml`), `src/llm_tools/wrapped_thermo_tools.py` | `domains/process/thermodynamics/rules.py` (knowledge-base engine), `model_selection.py` (`select_thermo_model`), `model_selection_rules.yml` as package data | M1 | base |
| `src/tools/heat_integration/pypinch.py` (PyPinch, GPL-3.0), `tools.py`, `src/schemas/heat_integration.py` | `domains/process/heat_integration/pinch.py`: `pinch_analysis(streams, dt_min) -> PinchResult`, the problem-table algorithm written anew without pandas, matplotlib, printing or CSV files in the working directory; streams may be piecewise (sensible and isothermal latent segments, exact in the cascade); the result is labelled as energy targets (`basis: targets`), not a synthesized or rated exchanger network; `minimum_approach` checks one exchanger's composite curves | M1 | base |
| `src/tools/separation_selection/tools_separation_methods.py`: matrices, pre-questions, COP, DSE, PI-matrix scoring, `select_separation_methods_core`, `select_binary_separation_methods`, `select_multicomponent_separation_methods` | `domains/process/separations/selection.py` | M1 | base |
| same file: HANNA activity coefficients, derived relative volatility | `domains/chemistry/properties.py` (`PropertyRetriever.mixture`, `relative_volatility`) on top of `integrations/prediction_services.py` | M2 | base; HANNA endpoint as an argument |
| same file: `get_property_for_separation_methods`, `Component` | none (see the chemistry table: superseded by `get_many` + `mixture`) | no (superseded) | |
| same file: LangChain `StructuredTool` helpers | none | no (LLM-coupled) | |
| `src/data/binary_separation_methods_dataset.json`, `Ternary_separation_methods_dataset.json` | none | no: prompt/answer benchmarks of the multi-agent system (evaluation material, see below) | |
| `skills/phase-calculation`, `skills/thermodynamic-model-selection`, `skills/separation-method-selection` | `domains/process/skills/<name>/SKILL.md`, in core's seven-section structure, calling the Python functions above; installed by `cheme init` | M1 | |

### Chemistry and safety side

| LLM4ChemE component | Destination in core | Status | Deps |
|---|---|---|---|
| `src/tools/chemical_property/unify_chemical_property_retrieval.py`, `src/schemas/chemical_properties.py` | `domains/chemistry/properties.py`: `PropertyRetriever` (`get`, `get_many`, `mixture`), `retrieve_properties`, `SOURCE_ORDER`, `relative_volatility`, `grappa_antoine_to_canonical`, `select_antoine_set`; results are `PropertyResult` (value, units, source, error, metadata) | M2 | base; each source as below |
| same: async manager, global singleton, negative-cache TTL, `PropertyJSONEncoder`, the `Cpm`/`Cpl`/`Cpg` aliases and the single-point heat-capacity tables | none: the retriever is synchronous, caches per instance, and gives `cp_ideal_gas`/`cp_liquid`/`cp_solid` in J/mol/K | no (simplified) | |
| `src/databases/online_databases/pubchem.py` | `integrations/pubchem.py` (typed `PubChemProperties`, no JSON strings) | M2 | base |
| `src/databases/online_databases/nist_webbook.py` (scrapy spider) | `integrations/nist_webbook.py`, the same XPaths on lxml over HTTP; no scrapy, no multiprocessing | M2 | base |
| `src/databases/cactus.py` | `integrations/cactus.py` | M2 | base |
| `src/databases/online_databases/thermo.py` (LangChain tools) | `integrations/thermo.py`: `chemical_properties()` | M2 | extra `props` |
| `src/databases/online_databases/unifac_model_retrieval.py`, `src/schemas/unifac_models.py` | `integrations/unifac.py` (models and parser together; lxml instead of BeautifulSoup) | M2 | base |
| `src/databases/rdkit_tools.py` | `integrations/rdkit.py` | M2 | extra `chemistry` (rdkit) |
| `src/databases/online_databases/osha_safety_data.py` (Selenium) | adapter `integrations/osha.py` (HTTP + lxml, same table positions); owner `domains/safety/hazard_data.py` (flash point in K, explosive limits in vol-%) | M2 | base; the live site was not reachable from the session, see the module docstring |
| `src/tools/property_prediction/tools_grappa.py`, `tools_hanna.py` | `integrations/prediction_services.py`: `grappa_vapor_pressure`, `grappa_antoine_parameters`, `grappa_boiling_point`, `hanna_activity_coefficients`, each with a required `endpoint` | M2 | base |
| `services/grappa_service`, `services/hanna_service`, `services/rmg_service` | none: run them from an LLM4ChemE checkout (`docker compose up -d grappa-api hanna-api rmg-api`; ports 8080, 8000, 8001) and pass their base URL | no (services and ML runtimes) | |
| `src/tools/reaction_kinetics/` (identifier, filter, retriever), `src/databases/nist_kinetics.py`, `rmg_kinetics.py`, `src/schemas/reaction_kinetics.py` | `domains/chemistry/kinetics/` (`records.py`, `identification.py`, `filter.py` in plain Python instead of pandas, `retrieval.py`), adapters `integrations/nist_kinetics.py`, `integrations/rmg.py` (RMG endpoint required) | M2 | extra `chemistry` for SMILES checks |
| `src/databases/open_reaction_db.py` | none | no (a stub raising `NotImplementedError`) | |
| `src/schemas/kinetics_output_schema.py`, `src/schemas/response_formats.py` | none | no (LLM response shapes) | |
| `src/databases/offline_databases/` (`solvents/`, `polymers/`), `src/tools/offline_databases/` | none | no: both datasets' `LICENSE` files are placeholders ("License: TODO — confirm and record the upstream license") and their `SOURCE.md` files leave the upstream source open, so redistribution in an AGPL package is not established. The SQL ingestion code stays with them: without a dataset it would have nothing to serve. Move both together once the owner records the upstream terms. | |
| `src/tools/separation_selection/tools_separation_methods.py`: `get_property_for_separation_methods`, `Component` | none: it formatted a property snapshot for the agent; `PropertyRetriever.get_many` and `mixture` (relative volatility, boiling-point difference, HANNA γ) give the same values with sources | no (superseded) | |
| `skills/property-retrieval` | `domains/chemistry/skills/property-retrieval/` | M2 | |
| `skills/materials` | `domains/chemistry/skills/materials/`, rewritten for `process/materials.yaml` and stream compositions in `process/flowsheet.yaml` (YAML edits, no editor commands) | M2 | |

### Not migrated

| LLM4ChemE component | Reason |
|---|---|
| `src/domain/`, `src/application/`, `src/infrastructure/` (agents, routers, LLM factories, YAML graph factory, skill loader, system-message builders), `src/cli.py`, `main.py`, `configs/` | the agent framework; deterministic tools in `core` must run without an agent runtime |
| `src/llm_tools/` | LLM tool wrappers; their deterministic parts moved with the tools (see above) |
| `src/workflows/` (`dexpi_process`, `separation_method`, `reaction_kinetics`, `state_access.py`) | LangGraph state and handlers |
| `src/evaluation/`, `src/data/*_dataset.json`, `examples/`, system messages | evaluation and paper material; stays with the research repository |
| `src/tools/dexpi_process/`, `src/llm_tools/dexpi_process/`, `src/workflows/dexpi_process/` | built on pyDEXPI's editor commands (`process.*`), which `core` does not use: `core` edits DEXPI files directly (`dexpi-xml`, `pid-edit`) and generates BFD/PFD sheets from YAML (`cheme process build`) |
| `skills/general-dexpi-operations`, the DEXPI parts of `skills/process-steps-and-streams` and `skills/materials` | written for those editor tools; the engineering knowledge is recorded below for folding into `core`'s skills |
| `scripts/generate_pydexpi_reference.py`, `scripts/example_dexpi_bfd.py`, `scripts/blank_agent_example.py` | reference generation for the editor skills, examples of the agent runtime; `core` has `scripts/build_snippets.py` |
| `src/paths.py` | replaced by `importlib.resources` |

## Engineering knowledge from the DEXPI skills

The editor-based skills hold rules that are independent of how a file is changed. Rules that are
clearly correct and fit `core`'s YAML-first, file-editing workflow are folded into
`process-design` (and `dexpi-xml` where they concern the XML). M2 was to fold them, together with
the materials skill. Candidates:

- Materials: a material template lists the components; a material state refers to a template
  and gives a composition whose fractions sum to one on a stated basis (mole or mass).
- Ports and streams: every stream connects one outlet port to one inlet port; a port carries
  one stream; the direction of a port follows the flow.
- Steps: a process step is decomposed into sub-steps only where the decomposition carries
  information; the hierarchy level (process, unit operation, ...) follows the decomposition.

M2 folded the materials rules into the `materials` skill (template order defines the order of
every composition vector; fractions of one composition sum to one on the stated basis). The
port and step rules were not added to `process-design`: they still need checking against the
rules `cheme validate` applies to `process/*.yaml`, so that the skill does not restate or
contradict a check. This is open.

## Tests

| LLM4ChemE test | Ported to | Status |
|---|---|---|
| `tests/tools/test_unit_conversion.py` | `tests/test_units.py` | M1 |
| `tests/tools/test_phase_tools.py` | `tests/test_thermo_phase.py` | M1 |
| `tests/tools/test_ruledb_inference_engine.py`, `test_thermo_model_selection_tool.py` (+ the knowledge-base fixtures of `tests/tools/conftest.py`) | `tests/test_thermo_model_selection.py` | M1 |
| `tests/tools/test_separation_method.py` | `tests/test_separation_selection.py` | M1 |
| (no tests in LLM4ChemE for pinch analysis) | `tests/test_pinch.py`, new | M1 |
| `test_thermo_tool.py`, `test_pubchem.py`, `test_nist_webook_retrieval.py`, `test_cactus.py`, `test_rdkit_tools.py`, `test_unify_chemical_property_retrieval.py`, `test_unified_property_retrieval.py`, `test_unifaq_model_retrieval.py`, `test_osha_retrieval.py`, `test_scraping_extra.py`, `test_offline_databases*.py`, `tests/databases/`, kinetics tests, `test_tools_grappa.py`, `test_rmg_*.py` | `tests/test_chemistry_properties.py`, `test_chemistry_cli.py`, `test_kinetics_*.py`, `test_nist_kinetics.py`, `test_rmg_client.py`, `test_chemistry_adapters_rdkit_cactus.py`, every network access mocked | M2 |
| `tests/application/`, `tests/domain/`, `tests/infrastructure/`, `tests/workflows/`, `tests/evaluation/`, `tests/services/`, DEXPI tool tests, `test_offline_databases*.py`, `tests/databases/`, `test_scraping_extra.py`, `test_rmg_service.py` | none | no |
