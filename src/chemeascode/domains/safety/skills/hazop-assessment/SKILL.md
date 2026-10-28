---
name: hazop-assessment
description: Assess the scenarios of a HAZOP study against its risk matrix - help the team give severity and likelihood codes per category, initial (before safeguards) and residual (with them), each with its basis; keep agent suggestions as proposals; look the bands up with cheme safety hazop rate (never by hand); find unrated scenarios, missing codes and scenarios whose band the matrix policy says needs an action. Use when ratings are to be recorded, a matrix changed, a band is stale, or the study must become assessed.
---

# HAZOP assessment: ratings and bands

## Purpose and when to use

Turn the team's risk judgement into ratings in the study (`risk.initial`, `risk.residual` of
each scenario) and let the shared lookup give the bands. Use it during and after HAZOP sessions,
when `cheme safety hazop check` lists unrated scenarios or missing bands, when the matrix
changed (`hazop-band-stale`), or before the review.

## Required inputs and missing inputs

- The study (`safety/hazop/<id>/study.yaml`) and its risk matrix (`risk_matrix:`, `cheme schema
  risk-matrix`): its categories, the meaning of every severity and likelihood code, the band
  order and which bands require an action (`requires_action`). Read the matrix before rating.
- `safety/risk-matrix.yaml` as `cheme init` writes it is **example data** (`example: true`):
  ask for the company's matrix, its procedure and revision before anything is assessed.
- From the team: the severity of each consequence per category, the likelihood of its cause,
  and which safeguards they credit for the residual rating, each with the argument. Frequencies,
  failure rates and safeguard credits are the team's or a separate study's (e.g. a LOPA): do
  not estimate them.

## Workflow and tools

1. **Initial risk** (before the safeguards): one entry per category with a significant
   consequence (leave a category out when nothing significant happens in it):
   ```yaml
   risk:
     initial:
       - {category: people, severity: "3", likelihood: C, status: proposed, by: agent,
          basis: "hot water release at the seal while an operator is near (matrix: 3 = lost-time injury)"}
   ```
   The `basis` quotes the matrix description it meets and why. A code you suggest is
   `status: proposed`; only the team sets `accepted`. Unknown codes stay `null` (`severity:
   null`): they are listed as unresolved, never filled with a default.
2. **Residual risk** (with the safeguards the team credits): its own entries, its own basis
   naming the safeguards credited. Never derive it from the initial rating or from the
   safeguards listed, and never lower a rating because a safeguard exists. No residual rating
   means none was made.
3. **Look the bands up** (the only way a band gets into the file):
   ```sh
   cheme safety hazop rate H-01                 # check only: what each rating gives, what is stale
   cheme safety hazop rate H-01 --target S3 --write   # one scenario (or a node id: all of its scenarios)
   cheme safety hazop rate H-01 --write         # every rating
   ```
   It writes `band: {value, provenance: calculated, source: 'cheme safety hazop rate: <matrix>',
   fingerprint}` into each rating and changes nothing else. A changed rating or matrix makes
   the band stale until it is rated again.
4. **Policy.** `hazop-action-required`: the scenario's band (residual where rated, else
   initial, per category, the worst) is one the matrix says needs an action. Propose one
   (`actions:`, `status: proposed`) for the team, or ask whether they credit more safeguards
   (a residual rating with its basis).
5. **Check**: `cheme safety hazop check H-01` until no error remains and the unresolved infos
   are only what the team still has to decide.

## Validation and failure handling

- `hazop-unknown-code`: a category, severity or likelihood the matrix does not have, or a
  matrix without that cell. Use the matrix's codes; complete the matrix
  (`cheme.risk-matrix-incomplete`) instead of guessing a band.
- `hazop-rating-duplicate`: one rating per category in each list.
- `hazop-matrix`: no usable matrix; its `cheme.risk-matrix-*` findings say why.
- `hazop-band-stale`: rate again (`--target`); `hazop-band-edited` (error): a band was edited by
  hand; change the rating, not the band, and rate again.
- `cheme safety hazop rate` exits 1 while a band is missing, stale or unresolved.

## Outputs and provenance

The ratings (authored: codes, basis, evidence, status, by) and the bands (calculated by the
lookup, with the matrix and input fingerprint). The report shows both:
`cheme safety hazop report H-01`.

## Required human judgment

Severity, likelihood, which safeguards are credited and whether the residual risk is
tolerable are the team's decisions. Agents may suggest codes with their basis, always as
proposals, and must say what the suggestion rests on. Never fabricate frequencies, failure
data, safeguard credits or a team's acceptance. The lookup only reads the matrix: it does not
make a scenario safe.

## References

- `safety/README.md`; `cheme schema hazop-study`, `cheme schema risk-matrix`.
- IEC 61882:2016; ISO 31000 (risk criteria); the company's risk matrix procedure.
- Skills `hazop-study` (drafting), `hazop-review` (review and revisions).
