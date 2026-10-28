# 0011. Per-value provenance (given/assumed/calculated) and sha256 fingerprints for staleness

- **Status:** Accepted
- **Date:** 2026-10-19 (process values and generated sheets); shared convention on 2026-10-21

## Context

An engineering number is only as good as its origin: a specification, an engineer's guess or a
computation. Generated artifacts (BFD/PFD, layout model, calculated stream values, datasheet
fills) go out of date when their inputs change, and nobody notices unless the tool records what
they were generated from.

## Decision

- Values carry `provenance: given | assumed | calculated` and, when given, a `source`; an
  optional `origin` refines the class (`measured`, `vendor`, `literature`, `design-rule`,
  `estimate`, `simulated`, `correlation`). DEXPI sheets map them to SPECIFIED, ESTIMATED,
  CALCULATED.
- Generated files and calculated values record fingerprints of their inputs (sha256, four fixed
  formats listed in contract.md) and the generator version. `cheme validate` reports
  `generated-edited`, `generated-version`, `generated-outdated`, `*-stale` findings.
- Change impact is conservative: `cheme impact` flags "review needed" at level info. Nothing is
  regenerated, rewritten or declared invalid automatically. Stale values are never exported.
- No universal object model: identity is the path from the repository root plus printed tags and
  XML ids; relations (derived-from, represents, analyses, depends-on) are recorded only where
  needed (optional `basis:`).

## Consequences

- Positive: reviewers see which numbers are backed; staleness is detected without a graph store
  or workflow engine.
- Negative: fingerprint formats are frozen: changing one would mark every recorded value stale.
  Moving a module under `domains/process/` changes `generator_fingerprint()` and requires
  rebuilding the examples.
- Limitation: provenance is self-declared for `given`/`assumed`; the tool checks presence and
  consistency, not truth.

## Evidence

- Process schema with per-value provenance and the generated BFD/PFD provenance comment:
  pre-release commit 17ab51f, pre-release commit 18dc7d5 in pre-release PR 45.
- `foundation/provenance.py` and review `basis`: pre-release commit 0ac1131 in pre-release PR 58.
- Engineering contract pre-release PR 119; one value fingerprint pre-release PR 123; `origin`
  pre-release PR 130; honest staleness for propagated and simulated values pre-release PR 275.
- [contract.md](../framework/contract.md), [architecture.md](../framework/architecture.md)
  ("Identity, relationships, provenance", "Change impact"), `src/chemeascode/project/impact.py`.
