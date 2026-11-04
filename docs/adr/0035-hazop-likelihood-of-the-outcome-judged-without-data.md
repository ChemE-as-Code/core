# 0035. HAZOP likelihood of the outcome, judged against the matrix's descriptions without data

- **Status:** Proposed
- **Date:** 2026-11-04

## Context

ADR 0033 lets a rating take its likelihood from a project frequency library and leaves it
`null` where the project holds no evidence. Two things made that rule too strict for a HAZOP:

- **The matrix describes the outcome.** A risk matrix's likelihood grades speak of how often an
  event like the consequence happens ("has occurred in the industry", "once in the life of the
  plant"). A library record is the frequency of the cause; the outcome is rarer wherever it needs
  more to happen (a rupture after the overpressure, ignition, someone present). On a case study
  rated against a team's worksheet, likelihoods from cause frequencies were about three and a
  half grades more likely than the team's.
- **A risk-ranked HAZOP judges.** In common practice the team chooses the likelihood grade from
  the matrix's descriptions and its experience; frequencies are calculated afterwards, in a
  LOPA or a QRA, for the scenarios the HAZOP flags. A `null` wherever no data exists leaves most
  ratings without a band, so the study gives the team nothing to discuss.

Forces: no LLM in a domain function (ADR 0010), so the judgement is the agent's or the team's,
in the study file, never the tool's; no invented numbers; every agent entry stays a proposal.
A quantified outcome likelihood (LOPA conditional modifiers) is a separate proposal (PR #127,
draft) and is not decided here.

## Decision

- **The likelihood of a rating is that of its outcome** as the consequence states it (initial:
  no safeguard acting), the way the matrix's descriptions read.
- **Order of evidence** (skill `hazop-risk-classification`, step 4): project evidence (operating
  experience, company data, a LOPA or reliability study); else a frequency library link
  (ADR 0033), whose derived code is the cause's and an upper bound for the outcome, said so in
  the basis; else **judgement against the matrix's descriptions**; else `null` with what is
  needed.
- **A judged likelihood is marked**: its basis starts with `judged:` and argues what has to
  happen for the outcome and which description that meets. It is a code, never a frequency or
  a probability, and never a number converted from another scale. Between two codes the agent
  names both and takes the more likely. It stays `status: proposed` and is listed for the team
  in the hand-over.
- cheme-as-code is unchanged: `cheme safety hazop rate` looks the band up from whatever code the
  rating has, and derives only linked ones (ADR 0033).

## Consequences

- Positive: every scenario with a credible outcome gets a band to discuss, as in a team's
  risk-ranked HAZOP; a judged code is told apart from a derived one by its basis.
- Positive: the frequency library keeps its role where it fits, with its limit (the cause, not
  the outcome) said in each basis.
- Negative: a judged code is not reproducible the way a derived one is; it rests on the
  argument in its basis and on the team's review.
- Known limitations: `judged:` is a convention of the basis text, not a schema field, and no
  rule checks it; the conditional factors between cause and outcome are argued, not quantified
  (PR #127).

## Evidence

- Skills `hazop-risk-classification` (step 4, the example, the hand-over) and
  `hazop-assessment` (inputs); `assessment_basis` of `examples/safety-hazop/safety/hazop/H-01`
  and of the `hazop-study` skill example.
- Amends [ADR 0033](0033-hazop-likelihood-from-a-project-frequency-library.md) where it left a
  likelihood without evidence `null`.
