# 0034. HAZOP likelihood of the outcome: the cause's frequency times LOPA modifiers

- **Status:** Proposed
- **Date:** 2026-11-02

## Context

ADR 0033 derives a rating's likelihood from the project's frequency library: the frequency of
the cause (an initiating event). A risk matrix's likelihood, however, describes the event rated:
"a similar event has occurred somewhere in our industry", "likely to occur once or twice in the
facility lifetime". The event rated is the consequence as written, which the cause brings about
only under conditions: the plant in the mode the cause matters in, a release that ignites, a
person present. Rating the cause's frequency as the outcome's overstates its likelihood; on a
pump-station case the derived likelihoods ran several grades above a study team's.

LOPA states the outcome's frequency before protection layers as the initiating event frequency
times the probability of enabling conditions and conditional modifiers (ignition, explosion,
presence, vulnerability). Published LOPA guidance lists generic values for some of them; their
terms of use differ and some are restricted.

## Decision

- The frequency library (`cheme/frequencies/v1`) may hold **modifiers**: id, kind (`enabling`,
  `ignition`, `explosion`, `presence`, `vulnerability`, `damage`, `failure`, `other`), a
  probability, the conditions it holds under, the matrix `categories` it may modify (none: any),
  its source and locator, `verified`. Project data with its source; cheme-as-code ships none.
- A rating's link may name modifiers (`frequency: {event_type, modifiers: [...]}`). The value
  placed in the matrix's `max_frequency` grades is the cause's frequency times their product:
  the likelihood of the outcome, initial (no protection layer). An unknown modifier, or one
  outside its categories (presence for harm to the environment), is `hazop-frequency` (error).
- **Sources carry their terms**: `licence`, `publication` (`public`, `restricted`, `local`, as
  for LCA sources) and `redistribution`. A derived likelihood carries the most restrictive label
  of the sources it rests on (none: a source not labelled); `rate` prints it beside the chain
  (`F020 0.1 x IGN 0.03 = 0.003/yr`). The label records the terms; it does not interpret a
  licence.
- The skill rates the likelihood of the outcome. The agent selects modifiers; their values come
  from the team or a cited source, never from the agent. A factor the outcome needs but the
  library lacks is a named gap, and the rating stays on the cause's frequency (conservative). A
  modifier is added only where the outcome as written needs it, never until a code comes out
  lower.

## Consequences

- Positive: the likelihood rated is the one the matrix describes; every factor is named, sourced
  and labelled; a change of a modifier shows up as `hazop-likelihood-derived`.
- Negative: more choices per rating, and generic modifiers (ignition by release rate,
  vulnerability by manning) need site facts (release rate, manning) the agent may not have.
- Known limitations: no event tree (one product per rating); `failure` modifiers (a rupture at an
  overpressure) depend on design data and need it per item; the walk of ADR 0032 does not yet
  attach modifiers to its top events; residual ratings (protection layer PFDs) stay the team's.

## Evidence

- `src/chemeascode/domains/safety/schemas.py` (`Modifier`, `FrequencySource` terms,
  `FrequencyRef.modifiers`), `frequencies.py` (`derive`, `Derived.chain`), the `rate` command.
- `tests/test_hazop_frequencies.py`; skills `hazop-risk-classification`, `hazop-assessment`.
