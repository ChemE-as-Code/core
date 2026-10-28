---
name: property-retrieval
description: Look up pure-component properties (identifiers, thermochemistry, vapour pressure, Antoine parameters, critical data, hazard data) from PubChem, the NIST WebBook, OSHA and thermo, or binary properties (activity coefficients, relative volatility, boiling-point difference), with the source of every value. Use when a property of a named compound is needed as evidence or as an input.
---

# Property retrieval

## Purpose and when to use

Gets property values from public databases and correlations through one function, with the
source of each value. Use it to fill a component's identifiers in `process/materials.yaml`,
to find the boiling points and volatilities a separation screening asks for, or to collect
hazard data for a safety review. It does not replace `cheme process props`: stream
properties written to `process/flowsheet.yaml` come from that command's validated method
(`process-design`).

## Required inputs and missing inputs

- The component: a name or a CAS number. A CAS number is unambiguous; prefer it. For a
  binary property, both components, and their SMILES when HANNA is asked.
- The property names (`cheme chemistry props --help` lists them, or
  `chemeascode.domains.chemistry.properties.SOURCE_ORDER`).
- The temperature and pressure with units, for temperature-dependent properties.
- For predictions, the base URL of a running GRAPPA or HANNA service. Without it they are not
  asked. The services run from an LLM4ChemE checkout (`docker compose up -d grappa-api
  hanna-api`); `cheme-as-code` holds only the clients.

If the component is ambiguous (an isomer, a trade name), ask for the CAS number.

## Workflow and tools

CLI, one component:

```bash
cheme chemistry props 64-17-5 -p temperature_boil -p vapor_pressure \
  --temperature 70 --temperature-unit °C            # web sources, then thermo
cheme chemistry props water -p viscosity --source Thermo --json   # offline
```

Python, including binary properties:

```python
from chemeascode.domains.chemistry.properties import PropertyRetriever, Source

retriever = PropertyRetriever()  # sources=set(Source) minus the services without endpoint
results = retriever.get_many("64-17-5", ["smiles", "temperature_boil"], 343.15, 101325.0)
alpha = retriever.mixture("benzene", "toluene", "relative_volatility", temperature_K=363.15)
```

Each property has a source order: identifiers PubChem first, thermochemistry NIST first, then
thermo, GRAPPA last. Hazard data come from OSHA (`chemeascode.domains.safety.hazard_data` gives
them in SI units), searched by CAS number: a name is resolved to its CAS number through PubChem
first. osha.gov refuses non-browser clients (HTTP 403), so these lookups usually fail with that
message; report the values as missing. For a separation, ask binary properties for adjacent pairs only: sort the
components by boiling point and pair neighbours.

## Validation and failure handling

- A value that no source gives comes back with `ok == False` and an `error` naming the sources
  tried; the CLI exits 1. Report that the value is missing. Never fill it from memory.
- A NIST Antoine set used outside its fitted range carries a `note` saying it is extrapolated;
  vapour pressure is then taken from the next source instead.
- `relative_volatility` without activity coefficients is the ideal ratio (`metadata["ideal"]`).
- CACTUS (used to resolve names in the kinetics tools) can misread condensed formulas; treat
  its result as lower confidence.

## Expected outputs and provenance

Every result names its `source` (PubChem, NIST, OSHA, Thermo, GRAPPA, HANNA, Derived), its
`units` as the source gives them, and `metadata` with the source URL, the method or the inputs
of a derived value. Record the source next to each value you write to a file, e.g. as a comment
in `process/materials.yaml` or in the evidence of a review.

## Required human judgments

- Whether a database value applies to the case (purity, phase, temperature range).
- Whether a GRAPPA or HANNA prediction may be used at all for the decision at hand.
- Which value wins when sources disagree beyond their uncertainty.

## References

- `chemeascode.domains.chemistry.properties`, `chemeascode.integrations` (adapters:
  `pubchem`, `nist_webbook`, `osha`, `thermo`, `unifac`, `cactus`, `rdkit`,
  `prediction_services`).
- `docs/framework/llm4cheme-migration.md` for what moved from LLM4ChemE and what did not.
