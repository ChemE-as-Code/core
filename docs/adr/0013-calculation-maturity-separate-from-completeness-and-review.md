# 0013. Calculation maturity levels, with "unsupported" blocking, kept apart from completeness and review

- **Status:** Accepted
- **Date:** 2026-10-24 (`cheme maturity`); maturity gate on 2026-10-25

## Context

A plant repository can contain a complete-looking package (PFD, P&IDs, datasheets) built on
numbers that were never balanced or simulated. "All gates green" was at risk of being read as
"the design is validated". Agents in particular tend to over-claim.

## Decision

- `cheme maturity` evaluates, requirement by requirement, which **calculation maturity level**
  the evidence supports: `sourced`, `balanced`, `predictive`, `engineering`. A level is reached
  when every required requirement of it and every level below passes.
- Each requirement is `pass`, `fail`, `missing` or `unsupported`. A required requirement that
  core cannot evaluate is `unsupported` and **blocks** the level: what cannot be checked is not
  claimed. Specified bases (a given conversion or split) never support `predictive`, however well
  a simulation converges; convergence alone is not physical validity.
- Three axes are kept apart: calculation maturity (evaluated from files), artifact completeness
  (reported as found, never raises a level) and independent review (people only; echoed, never
  written or inferred). Gates passing is not a review.
- A `kind: maturity` gate can require a level for a stage; every report lists its limitations.

## Consequences

- Positive: honest, evidence-linked claims that downstream readers (process library, papers) can
  rely on; gaps are explicit as `unsupported` or `missing` rather than silently passing.
- Negative: many real designs stay at `balanced` until core gains methods and benchmarks
  (e.g. `predictive.property-regime` is claimed only for Peng-Robinson on N2/O2/Ar,
  [0014](0014-dwsim-as-an-out-of-process-simulation-worker.md)).
- Negative: the requirement list is long and evolving; each new requirement can lower the level of
  existing repositories.

## Evidence

- The maturity report, then the maturity gate.
- `src/chemeascode/project/maturity.py`, `domains/process/model_basis.py`,
  [maturity.md](../framework/maturity.md).
