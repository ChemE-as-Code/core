---
name: hazop-risk-classification
description: Classify the scenarios of a HAZOP study on the study's own risk matrix - decide per category whether the consequence is significant, choose the severity and likelihood codes the matrix descriptions support with the criterion as basis, say when two codes are close, keep initial and residual apart, and propose actions where the band needs one; every code a proposal for the team. Use when scenarios are to be rated or re-rated, when the team wants suggested codes to discuss, or when ratings marked uncertain are reviewed, for the whole study, a node or one scenario.
---

# HAZOP risk classification

## Purpose and when to use

Suggest the risk ratings of the scenarios: for each category of the matrix, the severity of the
consequence and the likelihood of the cause, each tied to the words of the matrix that support
it. It prepares the team's rating; skill `hazop-assessment` records the ratings and looks the
bands up. Use it after the scenarios are drafted (skill `hazop-scenario-propagation`), before a
session so the team has a starting point, or to go through the ratings someone marked
uncertain.

## Required inputs and missing inputs

- The study and its risk matrix (`risk_matrix:`; `cheme schema risk-matrix`): the categories,
  the description of every severity and likelihood code, and the bands that need an action.
  Read all of it before the first rating. The matrix `cheme init` writes is example data:
  without the project's own matrix, rate nothing and ask for it.
- Each scenario's cause, consequence, outcome and path (`notes:`), and the fluid's hazards.
- For likelihood: what the project holds about how often the cause happens (operating
  experience, the company's failure data, a LOPA or reliability study), or its frequency
  library (`frequencies:` of the study, `cheme schema frequencies`: initiating-event
  frequencies with their sources, project data written or obtained by the team) with
  `max_frequency` on the matrix's likelihood codes. Without either, the likelihood stays open.
- For residual ratings: which safeguards the team credits and why.

## Workflow and tools

1. **What is left to rate**: `cheme safety hazop check H-01` lists unrated scenarios and
   missing codes (`hazop-unresolved`).
2. **Which categories.** For each scenario, go through the matrix's categories (people, asset,
   environment, reputation, ... as the matrix names them). Rate a category only where the
   consequence is significant in it; leave the others out rather than rating them lowest.
3. **Severity** (initial: the outcome with no safeguard acting, as the scenario states it).
   Compare the consequence with each code's description in that category and take the code
   whose description it meets. The `basis` names the criterion and the fact that meets it:
   `"matrix people 3, lost-time injury: hot water at the seal next to the walkway"`. Where two
   codes are close, say so in the basis (`"between 2 and 3; 3 if the area is manned"`), take the
   one the facts support, and leave the question for the team.
4. **Likelihood** (of the cause). Take the code whose description matches the evidence the
   project holds, and name that evidence in the basis. With no evidence, write `likelihood:
   null` and say what is needed: an unknown code stays unresolved, it is never filled with a
   default. Do not estimate a frequency, and do not convert a number from another study's scale.
   **With a frequency library**, choose what the cause is an instance of and link it instead of
   typing a code: `frequency: {event_type: pump_seal_failure}` (its screening value: the highest
   of its records, LOPA initiating-event records first) or `frequency: {record: F009}` when a
   record's `conditions` fit the cause better (a non-routine task rather than an emergency).
   `cheme safety hazop rate --write` derives the likelihood from the record and the matrix's
   `max_frequency` (never type it: `hazop-likelihood-derived`). The library's `modes:` map
   failure modes to event types, its `aliases` help find one. No event type fits, a record is
   per a length (100 m of pipe) or the event type has no record (`hazop-frequency`, info): no
   link, `likelihood: null` and what is needed. Name the record and that it is unverified in
   the basis when the library says so.
5. **Initial and residual stay apart.** The initial rating ignores the safeguards. A residual
   rating is a separate entry, made only for the safeguards the team credits, and its basis
   names them (skill `safeguard-crediting`). Never lower a code because a safeguard is listed.
6. **Write the ratings** under the scenario's `risk:` as proposals:
   ```yaml
   risk:
     initial:
       - {category: people, severity: "3", likelihood: null, status: proposed, by: agent,
          basis: "matrix people 3, lost-time injury: hot water at the seal next to the walkway; likelihood: no failure data for P-101 seals yet"}
       - {category: asset, severity: "2", frequency: {event_type: pump_seal_failure},
          status: proposed, by: agent,
          basis: "matrix asset 2, seal and bearing repair; likelihood from the library's pump_seal_failure (unverified)"}
   ```
   Then look the bands up as skill `hazop-assessment` says (`cheme safety hazop rate H-01
   --target S3 --write`); never write a band by hand.
7. **Actions where the band needs one** (`hazop-action-required`): propose one to three actions
   (`actions:`, `status: proposed`, referenced from the scenario). Each names the item or
   function by tag, says what to add, change or verify, and says which part of the scenario it
   addresses. Where the gap to a tolerable band is large, prefer a change to the design over a
   procedure.
8. **Hand over** a short list for the team: the ratings marked as close calls, the open
   likelihoods and what they need, and the proposed actions.

**Revise one scenario.** Change only that scenario's ratings or actions, keeping their ids, and
rate its bands again (`--target <scenario>`).

## Validation and failure handling

- `hazop-unknown-code`: a category or code the matrix does not have; use the matrix's codes.
- `hazop-rating-duplicate`: one rating per category in each of `initial` and `residual`.
- `hazop-matrix-example`: the matrix is example data; stop and ask for the project's matrix.
- `hazop-band-stale`, `hazop-band-edited`: rate again; change the rating, not the band.
- A consequence the matrix's descriptions do not cover (a category it lacks, an outcome beyond
  its highest code): say so and ask; do not stretch a description to fit.

## Outputs and provenance

Proposed ratings (`status: proposed`, `by: agent`) with a basis quoting the matrix criterion
and the evidence; bands only from `cheme safety hazop rate --write`; proposed actions; and the
hand-over list. Commit with a message naming the study and the scenarios rated.

## Required human judgment

Severity, likelihood, which safeguards are credited, and whether a risk is tolerable are the
team's decisions. A suggested code is a starting point for their discussion, never a finding.
Never set `status: accepted`, never invent failure data or a frequency, and never present a
rating as agreed.

## References

- `safety/README.md`; `cheme schema hazop-study`, `cheme schema risk-matrix`.
- IEC 61882:2016 (HAZOP); ISO 31000 (risk criteria); the project's risk matrix procedure.
- Skills `hazop-assessment` (recording ratings, bands), `hazop-scenario-propagation` (the
  scenarios), `safeguard-crediting` (residual ratings), `hazop-review`, `process-safety` (hub).
