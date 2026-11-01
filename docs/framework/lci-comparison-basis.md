# ADR: comparison basis of regional electricity backgrounds

Status: accepted. Code: `domains/assessment/lca/comparability.py`,
`FactorScope` in `schemas.py`, `backgrounds.py` (packaged scopes), the method-mix check in
`report.py`. Builds on [lci-scenarios.md](lci-scenarios.md) and the grid electricity profiles.

## Context

The packaged grid profiles give sourced factors for many geographies, but they measure different
things. The process library's ASU numbers (UK 66.7, NL 88.3, DE 104.7 kg CO2e per t GOX, exergy
allocation) put DESNZ (electricity at the consumer, with T&D and well-to-tank) beside EEA ENER038
(gross generation, direct emissions only). They are **screening sensitivities, not like-for-like
country footprints**, and nothing here has independent industrial validation. Core used to tell
two factors apart only by parsing the free-text `method` of their source, which cannot express
most of the differences below.

## The comparison dimensions

Two backgrounds may be set side by side as a like-for-like pair only if they agree on every one
of these. Each is a field of the optional `scope` of a source or a factor.

| dimension | values | why it matters | severity if it differs |
|---|---|---|---|
| `basis` | `direct` (emissions at the plant), `direct+upstream` (plus fuel supply chain, well-to-tank), `life-cycle` (plus infrastructure, manufacturing) | upstream and infrastructure can be tens of percent of a low-carbon grid | **hard** |
| `gases` | `co2`, `co2e` | CO2 only omits CH4 and N2O | **hard** |
| `accounting` | `generation` (territorial: the geography's own generation), `consumption` (trade-adjusted) | imports and exports move the figure of a country in either direction | **hard** |
| `delivery` | `generation` (per kWh generated), `consumer` (at the point of use, T&D losses included) | a loss uplift of a few percent, to be stated | soft |
| `gwp` | `AR4`, `AR5`, `AR6`, `AR4/AR5`, `mixed` | only for CO2e; changes the CH4 and N2O weights | soft |
| `mix` | `grid-average`, `residual-mix` | a residual mix excludes what contracts claimed | soft |
| data year | the factor's `year` (see below) | a grid decarbonises by several percent a year | soft |

Not a dimension yet: gross versus net generation. eGRID divides by net generation, EEA and
Ember by gross generation (own use of the power plants included); all are `delivery:
generation`. The difference is a few percent; today other dimensions (`gwp`, `basis`) already
keep such pairs apart, and a future pair that differs only in this way must state it in `note`.

Hard differences measure a different quantity: the totals are **not comparable**. Soft
differences are biases that a stated uplift or caveat can bound: the pair is a **proxy**.

**Data year versus publication year.** `year` keeps its meaning: the reference year a factor
file gives, used as given. Several sources date a file by its publication
(`desnz-ghg-2026:electricity-gb` is year 2026, the year of the 2026 set). A factor may also
declare, optionally and additively, `data_year` (the year the data describe) and
`publication_year` (the year the source published or versioned them); `data_year` may not lie
after `publication_year` (decision 6).

Migration: nothing changes for a factor without `data_year`; its records keep their bytes
(`publication_year` is not written into records). Declaring a `data_year` on a factor a scenario
links changes that scenario's record (and possibly its verdict): rerun
`cheme assess lca-scenarios --write` then. `desnz-ghg-2026` declares only `publication_year`,
so projects on it need no rerun for this.

## Decisions

1. **Structured scope, optional and additive.** `Source.scope` and `Factor.scope` (a
   `FactorScope`, all fields optional). A factor's scope overrides its source's field by field.
   An unset field is *not declared*; core never assumes it equal, with one exception: two
   factors citing the same source share its methodology, so a dimension both leave undeclared
   is not a difference between them (EEA NL against EEA DE). A project's copy of a packaged
   source next to its `include` keeps the packaged scope (the copy's own fields win). Existing
   files load and compute as before.
2. **Packaged profiles keep their bytes.** A packaged profile edit changes its fingerprint in
   every project's `lca/manifest.json` and scenario records, so the scopes of the five existing
   profiles live in `data/background_scopes/<profile id>.yaml` and are applied when the profile
   loads. The profile files and the manifest are unchanged (the manifest does not record scope).
   A scope written inside a profile file wins over the sidecar, field by field. Scopes were
   read from each profile's own notes; where a profile does not state a dimension it stays
   undeclared (EEA's GWP basis; DESNZ's accounting). The sidecar is not fingerprinted in the
   manifest (that is what keeps it stable): a change to it ships with a new software version and
   a changelog entry, and an entry that matches nothing in its profile is an error.
   The verdict looks at replaced backgrounds, the electricity procurement (`contractual`,
   `residual-mix`, `on-site` make a proxy) and gaps; a different design `case` changes the
   foreground, which the record states separately (`kind: design-case`).
3. **Method-mix reads the scope.** `cheme.lca-method-mix` warns, per category, when the
   contributions differ in `basis`, `gases` or (for CO2e) `gwp`, as declared. Contributions
   without a declared `gwp` fall back to the former reading of the source's `method` text, so
   projects without scopes behave as before (EEA, whose scope leaves `gwp` undeclared, is
   therefore read as AR5 from its method text here, while the verdict treats it as
   undeclared). A CO2-only factor has no GWP basis: it counts as the method `CO2 only`, so it
   is still flagged beside a CO2e factor whose GWP basis is known from either source, and
   `gases` tells it apart where both declare it.
4. **Scenario comparability verdict.** For every scenario, against the baseline:
   - `like-for-like`: every dimension of every replaced background is declared and equal, no
     exchange is dropped, no background is declared a proxy, no foreign geography is kept;
   - `proxy`: no hard difference, but a soft one, an undeclared dimension, a `proxy:`
     declaration, or a kept background of another geography;
   - `not comparable`: a hard difference, or an exchange the baseline characterises is a gap
     (the total does not stand).

   Declaring `proxy:` discloses a difference, it never makes a hard one comparable. A scenario
   that replaces no background keeps the baseline's and is `like-for-like` on the background.
   The baseline's own entry is `baseline`.
5. **Where it surfaces.** `lca/scenarios/<id>.json` gets `comparability` (`verdict`, `reasons`,
   `compared`: each replaced pair with its differing dimensions), and each linked exchange its
   `scope` (null: not declared). `results.md` gets a comparability row, one line per scenario
   and marks a `not comparable` scenario's totals "(not comparable)". `cheme assess lca
   --json` and `GET /api/lca` get `comparability` (per scenario) and the sources' `scope`,
   additively; their older `not_comparable` (and a record's `impacts.comparable`) keep their
   meaning: gaps only.
6. **Data year and publication year.** `Factor.data_year` and
   `Factor.publication_year` are optional; `year` is never reinterpreted. The year dimension of
   the verdict compares `data_year` where a factor declares it and `year` otherwise, and says
   which (`compared[].years`, and `[data_year / year]` in the reason) whenever a data year takes
   part; `publication_year` is metadata and never compared. Packaged profiles declare years in
   the sidecar (`years:`, factor id glob -> `data_year` / `publication_year`; every matching
   entry counts, two giving one key different values are an error, the profile file wins).
   `desnz-ghg-2026` declares `publication_year: 2026` (its `year` is the publication year); its
   data year (2025 by the DESNZ methodology, section 3.8, see [lca.md](lca.md)) is not declared
   until checked against the paper. The checks of time representativeness
   (`cheme.lca-reference-year`, `cheme.lca-scenario-year`, the dataset's temporal data quality)
   still read `year`, on purpose until a follow-up moves them to `data_year` where declared.

## Consequences

- Records and `results.md` of projects with scenarios gain these fields: one `--write` of
  `cheme assess lca --write` and `cheme assess lca-scenarios --write` after upgrading. Manifests
  of projects without scenarios do not change.
- A project's own factors without scope give `proxy`, never `like-for-like`: declaring a scope
  is the way to a like-for-like set.
- The ASU's NL and DE scenarios (DESNZ UK baseline, EEA 2024) differ in `basis` and are
  therefore `not comparable` with the baseline; a like-for-like set needs one declared basis
  (for example the Ember life-cycle series for all countries, or generation-based factors for
  all with a labelled loss uplift). That decision belongs to the process library.
- A like-for-like set of grid factors for several countries is built from the user's own copy
  of Ember's long-format data with `scripts/build_grid_profile.py`: one basis
  for all (`basis: direct`, `gases: co2`, `accounting: generation`, `delivery: generation`,
  `mix: grid-average`), `data_year` set, the release, licence (CC BY 4.0, as Ember's page states),
  attribution and the SHA-256 of the copy recorded. The package does not ship the result: the
  script writes a project file, so no third-party data is redistributed beyond what the project
  chooses, and the packaged profiles keep their bytes. The set is CO2 only and direct: it is
  `not comparable` with the packaged life-cycle `ember-2025`, with DESNZ and with the CO2e EEA
  series (the verdict says which dimension differs). Chosen as the conservative basis because it
  is the one Ember's current long-format file states; a CO2e or life-cycle series needs a file
  that carries it.
- Not done: other sources for the generator (EEA ENER038, eGRID, UBA, CBS: files and terms not
  checked for it), consumption-based variants (T&D losses, trade balance), the UBA PDF series
  (CO2e, upstream; awaiting written clarification from UBA); the time-representativeness checks
  still read `year` (decision 6).
