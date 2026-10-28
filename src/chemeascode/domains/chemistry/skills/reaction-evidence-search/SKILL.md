---
name: reaction-evidence-search
description: Gather the reaction evidence at the start of process design. Resolve the product's and reactants' identities, search papers, patents, open reaction data and kinetics sources with the search tools this agent has, read each source, record one observation per experiment or patent example (exact location; conditions; conversion, selectivity and yield kept distinct; kinetics with units, basis and validity range) and record the candidate routes, conflicts and gaps in process/reaction-evidence.yaml, checked by cheme validate. Use before choosing or changing a reaction model, or when asked where a conversion, selectivity or rate law comes from.
---

# Reaction evidence search

## Purpose and when to use

Before `process/reactions.yaml` holds a reaction model, find out what the literature and
patents actually report about the routes to the product. The record is
`process/reaction-evidence.yaml` (schema `cheme/reaction-evidence/v1`, `cheme schema
reaction-evidence`): the searches run, the sources read, one observation per experiment or
operating example, the candidate routes, the conflicts between sources and what is still
missing. It is evidence, not the model: choosing the route and the model's inputs is a
separate step (skill `route-selection`).

What the record is used for later: `cheme chemistry evidence` compares the routes, and once
a route is selected with a `model_basis` (skill `route-selection`), `cheme maturity` counts a
conversion reactor's specified conversion or selectivity as sourced only where the basis's
cited observations cover it at the reactor's temperature and pressure (only these two
conditions are compared). Only observations from sources read in `full-text`, without an
error finding, with reported (not assumed) values labelled per pass (conversion) or molar and
relative to the key (selectivity), and with the temperature and catalyst (`catalyst` id, else
`catalyst_formulation`; "none (thermal)" when uncatalysed) they were measured at, count; a
snippet, an abstract, an unlabelled value, an observation without a catalyst, a source with a
malformed identity or a flagged conflict does not, and observations on different catalysts
are not pooled. So record ranges, bases, catalysts and conditions as the source gives them,
and keep conflicts.

Use it at the concept stage, before the first reactor is written; when a route, catalyst or
operating window is reopened; and whenever someone asks where a conversion, selectivity or
rate law came from.

This skill gathers and records evidence. It is not a search application or a reaction
database, and it does not bundle source documents.

## Required inputs and missing inputs

- The product and the design question: target scale, phase, feedstocks that are on or off
  the table, the operating range of interest (`question:` in the file). Ask for the question
  if it is not given. A search with no question returns too much to read.
- **Search tools.** This skill needs at least one tool that searches the web, the literature
  or patents, and one that fetches a page or document (for example a web search and a web
  fetch tool, a literature or patent search connector, an MCP server for a database). Use the
  ones you have. Do not assume a particular provider. If no search tool is available, or a
  service refuses or fails, record the search with `status: unavailable` and the reason, tell
  the user what is missing, and stop before writing observations. Never fill in from memory
  instead.
- For each component: a name the sources use. The identities themselves are resolved in
  step 1.

## Workflow and tools

1. **Identities.** Resolve the product, the reactants and the expected by-products to one
   chemical each: `cheme chemistry props NAME` (PubChem: CAS, SMILES, InChIKey, formula,
   molar mass; skill `property-retrieval`) and declare them in `process/materials.yaml`
   (skill `materials`) with their synonyms in `name`. Search with the synonyms and the CAS
   number. The evidence file names components by these ids (`evidence-component` warns
   otherwise).
2. **Plan the searches.** From the question, list the candidate routes (feedstock, reaction
   type, catalyst family) and, per route, what the model will need: stoichiometry and side
   reactions, conversion and selectivity at conditions, kinetics with their basis, catalyst
   and its window, the separation and recycle context. Write each route under `routes:` with
   `status: candidate`.
3. **Search and log every query.** Per route, search reviews first (for the landscape), then
   primary papers, patents (for operating examples and industrial conditions), open reaction
   data and kinetics sources (`cheme chemistry kinetics` reads NIST and RMG for elementary
   gas-phase steps). Log each query as you run it:

   ```yaml
   searches:
     - {query: "ethyl acetate ethanol dehydrogenation copper catalyst selectivity",
        tool: web search, date: 2026-10-24, found: [S2, S3]}
     - {query: "...", tool: patent search, date: 2026-10-24, status: unavailable,
        notes: "service returned 503 twice"}
   ```

4. **Read the source.** Open each source you will use (a full-text page, the patent's
   description, the article PDF). Record it once under `sources:`, with `doi` (the bare
   `10.xxxx/...`) or `patent` (the publication number with kind code: `US7652167B2`),
   `url`, `accessed`, `access` (what you actually read: `full-text`, `abstract`, `snippet`
   or `unavailable`) and `reuse` (the licence, or "copyrighted: citation and extracted facts
   only"). **A search snippet does not establish a number.** A source you could only see as
   a snippet or an abstract may still be listed, but its numbers stay out
   (`evidence-access` is an error), and what is missing goes under the observation's
   `missing:`.
5. **One observation per experiment or example.** Each run, table row or patent example is
   its own observation. Give its `location` (page, table, figure, paragraph or "Example 3")
   and keep its context:

   ```yaml
   observations:
     - id: O1
       source: S2
       route: DEHYD
       location: "Table 2, entry 4"
       kind: experiment
       scale: lab
       conditions:
         temperature: {value: 250, unit: °C}
         pressure: {value: 2, unit: MPa(a)}
         phase: gas
         catalyst_formulation: "Cu/ZnO/ZrO2/Al2O3, 1 g"
         feed: {EtOH: {value: 1, unit: "1", note: "pure ethanol"}}
         space_velocity: {value: 0.9, unit: 1/h, note: WHSV}
       conversion: [{component: EtOH, value: {value: 61, unit: "%"}, basis: per-pass}]
       selectivity:
         - {product: EtOAc, value: {value: 79, unit: "%"}, relative_to: EtOH, basis: molar}
       byproducts: [acetaldehyde, butanol]
       missing: [isolated yield, catalyst lifetime]
   ```

   - Keep **conversion, selectivity and yield distinct**, each with `relative_to` (its
     denominator), `basis` (molar, carbon, mass) and, for a yield, `type: isolated` or
     `analytical`. Write the term the source uses. A number the source calls "yield"
     without saying of what stays a yield with no `type`. `evidence-yield-basis` then warns,
     and you say so in `missing`. Never convert a yield into a conversion.
   - Units as reported, in the units the file reads: K or °C; pressures with (a) or (g);
     s, min, h; fractions in % or `1`. Anything else (a loading, a space velocity, a kinetic
     parameter) carries the source's unit as text.
   - `status:` on a value: `reported` (the default: the source states it at the location),
     `derived` (you computed it from reported values: `derived_from` says how) or
     `assumed` (not in the source: `note` says why). Prefer leaving a value out and naming
     it in `missing`. Write `assumed` only when the user asks for a working value.
   - Kinetics go into `kinetics:` as the source writes them: the `equation`, every parameter
     with its unit, the `rate_basis` (per kg of catalyst, per m3 of liquid), the
     `temperature_range` (and `pressure_range`) of the data, and `fitting` (reactor, data,
     method). Without a basis or a range, `evidence-kinetics` warns. List them under
     `missing` if the source does not say.
   - Patent examples are `kind: operating-example`, `scale: patent-example`. They show
     conditions that were reported, not industrial deployment, validated kinetics or
     commercial performance. Say so in the route's gaps where it matters.
6. **Conflicts and gaps.** Where two observations disagree (a rate constant, an activation
   energy, a selectivity at the same conditions), record both observations and add a
   `conflicts:` entry naming them. Do not average them. Per route, list in `gaps:` what the
   model will need that no source gives (side-reaction kinetics, catalyst lifetime, data at
   the target pressure).
7. **Check and compare.** Run `cheme validate`, then fix every `cheme.evidence-*` error.
   `cheme chemistry evidence` prints the route comparison: per route its sources and
   observations, the reported ranges of temperature, pressure, conversion, selectivity and
   yield (each kept apart), kinetics, conflicts, sources not read in full and gaps. Hand over
   to `route-selection`.

## Validation and failure handling

- `cheme.evidence-schema`: the file does not follow the schema (an unknown key, a value with
  neither `value` nor `range`, a derived value without `derived_from`).
- `cheme.evidence-duplicate-id`, `-reference`: ids are shared between sources, routes and
  observations, and every reference must resolve.
- `cheme.evidence-identity`: a malformed DOI or patent number, or a patent without its
  number (errors); a paper with neither DOI nor URL (warning).
- `cheme.evidence-location`: reported values without the page, table, figure or example.
- `cheme.evidence-access`: numbers from a source you did not read. Read it, or move the
  numbers to `missing`.
- `cheme.evidence-unit`: a unit the file does not read, or a fraction outside 0 to 1 (a
  percentage written with unit `1`).
- `cheme.evidence-yield-basis`, `-yield-conversion` (warnings): an ambiguous yield, or a molar
  yield above its reactant's conversion (the source's "yield" may be a selectivity).
- `cheme.evidence-duplicate` (warning): one location recorded twice. Record each experiment
  once.
- `cheme.evidence-kinetics` (warning): kinetics without a basis or a validity range.
- `cheme.evidence-component`, `-catalyst` (warnings): an id that `process/materials.yaml` or
  `process/catalysts.yaml` does not declare.
- Search tool missing, rate-limited, paywall: record it (`status: unavailable`,
  `access: unavailable`) and report it to the user. An unavailable source is a gap, not a
  reason to guess.

## Expected outputs and provenance

`process/reaction-evidence.yaml`, reviewed in the diff: the searches with their dates, the
sources with identifiers, access and reuse conditions, the observations with their
locations, the routes, the conflicts and the gaps. It stores citations and the facts
extracted from them, never the source documents. Store copies of documents only when their
licence allows it and the user asks. Nothing in `process/reactions.yaml` changes in this
skill.

## Required human judgments

- The design question: scale, phase, feedstocks and operating range the search is for.
- Whether a source is relevant and credible (a review's summary against the primary paper; a
  patent's broad claims against its worked examples).
- Whether two observations are comparable at all (catalyst, particle size, reactor, analysis).
- When the search is complete enough to compare routes.

## References

- `route-selection` (route comparison and the model basis), `reactions` (the model),
  `materials` and `property-retrieval` (identities), `process-design`.
- `cheme schema reaction-evidence`, `cheme chemistry evidence`, `cheme chemistry kinetics`.
