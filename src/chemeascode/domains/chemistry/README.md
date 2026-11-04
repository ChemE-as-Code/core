# Chemistry and product discovery

**Scope.** Candidate molecules and materials, reaction networks, synthesis routes, stoichiometry,
kinetics and selectivity, with links to the chemical evidence and property sources behind them.

**Artifact types.** Component definitions, a reaction network, a route comparison, kinetic
parameter sets with their sources.

**Code today.** `properties.py`: pure-component and binary properties from PubChem, the NIST
WebBook, OSHA, thermo and the GRAPPA/HANNA services, each value with its source
(`cheme chemistry props`). `kinetics/`: reaction identification, NIST and RMG kinetics
retrieval and the filter that reduces them to one Arrhenius record. `reactions.py`: the
schema of `process/reactions.yaml` (stoichiometry, conversion, heat of reaction, catalyst),
formula parsing and element balances, extent fitting and the conversion reactor that
`process` uses. `thermochemistry.py`, `equilibrium.py`: ideal-gas data, heats of reaction,
equilibria. `rates.py`, `catalysts.py`: rate laws and catalyst records. `microkinetics.py`:
mean-field surface mechanisms, their steady state and degree of rate control, and the Cantera
export. `anolyte.py`, `carbonate.py`: the interface and registry of anolyte (electrolyte
reservoir) models and the first one, `well-mixed-carbonate` (equilibrium carbonate speciation of
a hydroxide anolyte), which `process` electrolysis duties integrate. `evidence.py`: the reaction evidence of a plant (`process/reaction-evidence.yaml`):
sources, observations, candidate routes, conflicts and the model basis, its `cheme.evidence-*`
rules and the route comparison (`cheme chemistry evidence`). Skills: `property-retrieval`,
`materials`, `reactions`, `reaction-evidence-search`, `route-selection`. Adapters live in `integrations/`. Moved from LLM4ChemE, see
[the migration](../../../../docs/framework/llm4cheme-migration.md).

**What will live here.** Surface energies from databases (Catalysis-Hub, once its API answers
again) for mechanisms, and further adapters to property and database services through
`integrations/`. The reaction library of industrial processes lives in `process`
(`reaction_library.py`), since an entry spans materials, reactions and catalysts.

**Out of scope.** Flowsheet balances (`process`), experiment records and parameter estimation
(`experiments`), and any LLM-driven generation of molecules or routes: deterministic tools only,
the agent stays outside.

May import: `requirements`. See [the architecture](../../../../docs/framework/architecture.md).
