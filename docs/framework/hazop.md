# HAZOP studies

The foundation for HAZOP in cheme-as-code (pre-release issue 136): a versioned study file, a versioned risk
matrix, one deterministic band lookup, validation against the plant, staleness, a report, a
review record and a stage gate. Everything else a HAZOP tool may do (node selection, scenario
propagation, frequency estimation, safeguard credits, consequence modelling, LLM
classification) is a separate capability. It builds on this format and does not replace it.

<!-- readme: ### safety: HAZOP studies | body -->

## Files

| File | Schema | Owner |
|---|---|---|
| `safety/hazop/<study-id>/study.yaml` | `cheme/hazop-study/v1` (`kind: hazop-study`) | `domains/safety/schemas.py` (`HazopStudy`) |
| `safety/risk-matrix.yaml` (any path the study names) | `cheme/risk-matrix/v1` (`kind: risk-matrix`) | `domains/safety/schemas.py` (`RiskMatrix`) |
| `build/hazop/<study-id>.md`, `.html` | derived, never edited | `domains/safety/hazop_report.py` |
| `reviews/<date>-hazop-<study-id>.md` | the review record (`cheme schema review`) | `foundation/reviews.py` |

One study is one directory, so material that belongs to it (session notes, attendance, a
signed copy) can sit next to `study.yaml`. The file is nested in worksheet order:

```
study: scope, modes, analysed inputs, risk_matrix, assessment_basis, team
  nodes[]: id, title, design_intent, members (plant refs), modes, status
    deviations[]: id, guide_word, parameter, notes
      scenarios[]: id, cause, consequence, refs, modes, safeguards (ids), actions (ids), status
        risk.initial[] / risk.residual[]: category, severity, likelihood, basis, evidence, status, band
    dismissed[]: guide_word, parameter, top_event, at, causes, reason, status (propagate --coverage)
  safeguards[]: id, title, kind, refs, interlock, status
  actions[]: id, text, owner, due, status, response
```

Scenarios are the rated unit: one cause leading to one consequence, the row of a worksheet. A
study that records one cause with several consequences writes several scenarios. Safeguards and
actions are registers referenced by id, because one safeguard protects several scenarios and an
action closes several gaps.

## Identity and references

- **Ids** follow `ID_PATTERN` and share one namespace per study (nodes, deviations, scenarios,
  safeguards, actions, modes): `cheme.hazop-duplicate-id`. The list order is display order:
  inserting or moving an entry changes no id and no fingerprint (a band's fingerprint holds its
  matrix and codes, not its position).
- **Plant references** (`members`, `refs`) are printed tags, resolved like the interlocks'
  (`domains/control/interlocks.py` `known_tags`: every list and every loaded sheet). `{tag,
  sheet}` qualifies a tag by its `plant.yaml` sheet id, and `{sheet, object}` names a DEXPI
  object by its XML id. A bare string is short for `{tag: ...}`.
- **Interlocks** stay in `control/cause-effect.yaml`. A safeguard names one by id
  (`interlock: I-01`) and is checked against it (`cheme.hazop-unknown-interlock`).
- **Analysed inputs** (`analysed: [{path, revision, relation}]`) reuse the review `Basis`:
  a `sha256:` file fingerprint, or the HEAD commit for a directory (`stamp` refuses a directory
  with uncommitted changes, so the commit identifies it). `foundation.provenance.changed_since`
  compares them; an input unchanged since its revision keeps it. Only the declared inputs count.

## Judgement, calculation, review

| What | Where | Who |
|---|---|---|
| Proposal | `status: proposed` (the default) on nodes, scenarios, safeguards, ratings, actions and the risk matrix; `by:` names the proposer | an agent or one person |
| Authored judgement | `status: accepted`; ratings' codes with `basis` and `evidence`; the matrix's `status: accepted` with `accepted_by` | the team |
| Calculated value | a rating's `band: {value, provenance: calculated, source: 'cheme safety hazop rate: <matrix>', fingerprint}` | `cheme safety hazop rate --write` only |
| Review decision | `reviews/*.md` with `topic: hazop`, the study directory in `scope`, the analysed inputs in `basis` | the reviewer |

The default is `proposed`, so an entry nobody marked is never read as agreed. The state of a
study (`domains/safety/hazop.py` `study_state`) is derived, never declared:

| State | Meaning |
|---|---|
| `invalid` | an error finding (schema, ids, references, codes, a hand-edited band) |
| `draft` | something unresolved: proposals, unrated scenarios, missing codes or basis, bands missing or stale, a required action missing, a changed input, example data |
| `assessed` | complete and current, every judgement accepted; not approved |
| `reviewed` | assessed, and the newest review record covering the study is a human one, with nothing in its scope (read from the repository root) or the study's analysed inputs changed since; a git failure, or an open critical or high finding of any covering record (at the most severe rating any record gives it), keeps it `assessed` |

## The lookup

`domains/safety/risk_matrix.py` `lookup(matrix, category, severity, likelihood)` reads one
cell, nothing more. The matrix states the band order (`bands`, lowest risk first), the grades,
the categories and the cells: shared (`cells`) or per category (`categories[].cells`). The
matrix's own rules refuse duplicate codes and cells (a YAML key given twice included), unknown
codes and bands, and an incomplete mapping. A matrix with an error gives no band at all. A
missing code, an unknown code or a missing cell is a problem the caller reports. No band is
ever assumed, and the band order is never alphabetical or a product of codes.

A band's fingerprint is `value_fingerprint({matrix, category, severity, likelihood})`, with
`matrix` the fingerprint of the whole parsed matrix, and the band records those inputs
(`inputs: {matrix, category, severity, likelihood}`). A band whose inputs differ from the
rating's or the matrix's now (a rating moved to another category included) is stale, and the
finding says what it was looked up from; `rate --write` rewrites it. A band whose fingerprint
is not the one of the inputs it records, or whose `source` names another tool, was not written
by the lookup (`cheme.hazop-band-edited`, an error) and `rate` never overwrites it. A band whose
`inputs` record no `category` (written before they did) was looked up in the matrix category
whose fingerprint matches; a band written before `inputs` existed is checked by its
fingerprint alone. Any change to the matrix's content (not its
comments or layout) makes every band stale. A scenario's band for the policy check
(`requires_action`) is the worst, in the matrix's order, over its categories: each at its
residual rating where the team gave one, else at its initial rating.

Writing is targeted: `write_bands` edits the text of the ratings concerned (block or flow
mappings) and leaves every other line, comment and key order as it was.

## Rules

`cheme validate` checks every study; `cheme validate <files>` checks the studies among the
files (or those whose matrix is among them) without the references to the plant, whose lists
and sheets it does not read then.

`cheme.hazop-*` (`domains/safety/hazop.py`) and `cheme.risk-matrix-*`
(`domains/safety/risk_matrix.py`); the module docstrings list each with its level. `cheme
impact` adds `cheme.review-needed` for a changed analysed input and for stale bands.

## Extension points

- `extensions:` on the study, a node and a scenario: data of other tools by tool name (a
  scenario engine's anchors, a node breakdown's evidence, a classifier's distribution).
  cheme-as-code keeps and ignores it, so such a tool needs no schema change to store its data.
- New optional fields (a safeguard's independence, a probability of failure on demand, an
  initiating frequency with its source) can be added to v1 without breaking existing files.
  Values a tool calculates follow the contract: `provenance: calculated`, the tool's name at the
  start of `source`, a fingerprint of its inputs.
- A tool that proposes nodes, scenarios or ratings writes them `status: proposed` with `by:`
  naming it. The team's acceptance stays a separate, human edit.
- Another matrix shape (e.g. a continuous frequency scale with a view as a matrix) can produce
  a `cheme/risk-matrix/v1` file as its view. The lookup and the study stay as they are.

## Not covered

Automated node selection, frequency estimation, safeguard credit (LOPA), consequence modelling
and LLM classification; a dedicated viewer page. Scenario propagation over the P&ID exists as a
read-only cross-check (`cheme safety hazop propagate`, ADR 0032): it never writes scenarios,
`--coverage` reports the top events no scenario covers. None of
them is needed for authoring, validation or reporting, and no database, external analysis
package, LLM service or credential is.
