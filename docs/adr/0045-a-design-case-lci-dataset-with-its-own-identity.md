# 0045. A design case's LCI dataset, generated with an identity that names the case

- **Status:** Accepted
- **Date:** 2026-11-06 (proposed 2026-11-04)

## Context

`cheme assess lca --dataset` and `--write` derive the plant's unallocated LCI dataset
(`lca/dataset.yaml`) for one flowsheet case: the one `lca/lca.yaml` names (`case:`), else the
flowsheet's default. A plant with two computed designs (process-library#331: Skid A and
Skid B of the CO2 electrolysis plant, tracker core#136) needs a dataset for each. The scenario
records already have ids `<dataset>/<case>/<scenario>` and `cheme assess lca-cases` sets the
cases side by side ([ADR: design cases and regional scenarios](../framework/lci-scenarios.md)),
but a second dataset could only be made by editing `case:` in a scratch copy. Such a copy
also has the base dataset's id, title and uuid. The library's `build_lci` refuses two datasets
of one process with the same name, reference product, location and unit, and two datasets
with one uuid are one dataset to every LCA tool.

Options considered:

1. A second `lca.yaml` per case. This duplicates the study and goes against the one-project
   rule of the scenarios ADR.
2. Suffix the id and derive the uuid from the new id as the base one is
   (`uuid5(NAMESPACE, "<plant>/<id>")`). The case uuid is then unrelated to a uuid the study
   pins under `dataset: uuid:`.
3. Derive the identity from the base dataset's: the id and title get the case, and the uuid is
   a uuid5 in the base uuid's namespace.

## Decision

`cheme assess lca --dataset|--write|--check --case <id>` derives the unallocated dataset of
flowsheet case `<id>` with the study's scope. It is the same derivation as `lca/dataset.yaml`,
read from that case's stream states. When `<id>` is not the study's case, the dataset gets the
identity of a design case's dataset (option 3, `domains/assessment/lca/case_dataset.py`):

| field | value |
|---|---|
| `id` | `<dataset id>-<case>`, the case id made an identifier (lower case; what is not `[A-Za-z0-9_.-]` becomes `-`) |
| `title` | `<title>, case <case>` (the dataset id when the title is empty) |
| `uuid` | `uuid5(<base uuid>, "case:<case>")`, where the base uuid is the one `lca/lca.yaml` pins (`dataset: uuid:`) or the one cheme derives for `lca/dataset.yaml` |
| `description`, `provenance.case` | the case (as before: they always named it) |
| `parent` | the base uuid: the case dataset is a variant of the study's dataset |
| `review` | `unreviewed` (`[{type: none}]`) when the study states a review, else none: a review of the study's dataset is not one of this dataset |
| `superseded_by` | none: what supersedes the study's dataset does not supersede this one |

The reference product, functional unit, basis, location, allocation and the rest of the
`dataset:` documentation stay those of the study. The same base uuid and case id always give
the same uuid, and the base dataset's own uuid does not change.

- `--write --case <id>` writes only that dataset, to `lca/datasets/<dataset id>-<case>.yaml`.
  The study's outputs (`lca/dataset.yaml`, results, manifest) are not written, since they
  belong to the study's case. cheme never overwrites a file there that it did not generate for
  that case (`provenance.generator: cheme assess lca`, `provenance.case: <id>`, no
  `generation:`). Such a file is the error `cheme.lca-dataset-not-generated`.
- The file is marked as generated in two places: a header comment that names the command and
  the check, and the provenance the schema already has (`generator`, `case`, and the sha256 of
  each input file under `files`). No schema field is added.
- `--check --case <id>` exits 1 with the error `cheme.lca-dataset-stale` when the file is
  missing or differs from what would be generated now. The finding names the file, and its
  hint is `rerun cheme assess lca --write --case <id>`. A project that commits the file keeps
  it current with a `kind: command` gate running this check. `cheme assess lca --check`
  without `--case` checks the study's outputs as before.
- Two declared cases whose ids give one identifier (`Hot` and `hot`, `Skid B` and `skid-b`)
  would share the dataset id and the file. Neither gets a dataset: `--dataset`, `--write`
  and `--check --case` report the error `cheme.lca-case-id-clash` naming both, and exit 1.
  The study's own case never clashes, since its dataset is `lca/dataset.yaml`.
- `cheme assess lca --check` reports a stale `lca/dataset.yaml` as the same
  `cheme.lca-dataset-stale` finding (hint `rerun cheme assess lca --write`), beside the line
  it always printed.
- A case the flowsheet does not declare is a usage error (exit 2) that lists the declared
  cases. `--case` with any other output option (`--json`, `--csv`, `--inventory`,
  `--coverage`, `--balance`, `--pact`, `--strict`), or without `--dataset`, `--write` or
  `--check`, is also a usage error (exit 2).
- `--case` naming the study's own case is the same as leaving `--case` out. `lca/dataset.yaml`
  stays byte-identical for every existing plant; `tests/test_lca_case_dataset.py` compares it
  with a snapshot taken before this change.
- In Python, `lca_report(root, case=...)` computes the foreground of that case (this implies
  `inventory_only`) and sets `variant_case`. `case_dataset(root, case)` returns the path, the
  text and the report, and `variant_case(root, case)` resolves the study's case.

## Consequences

- Positive: two designs of one plant export two datasets with distinct ids, titles and uuids
  from one project, without a scratch copy, and both are checked as current. The uuids can be
  reproduced from the base uuid and the case id alone.
- Positive: `lca/datasets/` already holds generated datasets (`cheme assess lci-estimate`) and
  hand-written ones. `cheme assess lca` loads a dataset there when a study references it as a
  background, and `cheme migrate` reads every file there. The generated case dataset needs no
  new loader.
- Negative: `cheme validate` does not read `lca/datasets/`, so a committed case dataset that
  was edited by hand is caught by `--check --case` (and by a study that loads it), not by
  `cheme validate`. `cheme migrate` treats the case datasets as inputs like the other files
  there: after a schema bump, rewrite them with `--write --case` rather than migrating them.
- Negative: data quality (`lca/manifest.json`), the study's allocation, the results and the
  scenario records apply to the study's case only. A design case's dataset carries the
  study's `dataset:` documentation as written. A `production_volume` pinned there is the study
  case's, so give it per case in the consumer, or leave it to be derived (cheme derives it
  from each case's own product flow). Only the review, `superseded_by` and `parent` are
  reset for the case (see the table); `version` and `classification` are the study's.
- Negative: renaming a case or the flowsheet title changes the case dataset's id, file name
  and uuid. The old file then stays behind, because `--check --case` only checks the case it
  is given.
- Known limitations and follow-ups: `cheme assess lca --check` without `--case` does not
  discover the case datasets already written, and nothing reports a generated file whose case
  was removed. A case cannot state its own review or documentation: give each design its
  own in the consumer.

## Evidence

- core#136 (tracker); process-library#331 ("export both designs").
- `src/chemeascode/domains/assessment/lca/case_dataset.py`, `lca_report(case=...)` and
  `dataset_yaml` in `domains/assessment/lca/report.py`, and `--case` in
  `interfaces/cli/assess.py`.
- `tests/test_lca_case_dataset.py` and the snapshot `tests/data/lca-case-dataset/asu-design-dataset.yaml`.
- Docs: [design cases and regional LCI scenarios](../framework/lci-scenarios.md#a-design-cases-own-dataset),
  [LCA](../framework/lca.md).
