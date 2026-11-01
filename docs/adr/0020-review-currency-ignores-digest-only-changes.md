# 0020. A review stays current through a change of nothing but full digests

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

A review counts only for its `scope` at its `reviewed_commit` with no changes since
([ADR 0012](0012-stages-gates-and-sign-offs-on-the-default-branch.md)). Generated outputs record
the fingerprint of the sources or model they were made from
([ADR 0011](0011-per-value-provenance-and-fingerprints.md)), e.g. the model `output_sha256` in
`layout/lifting-study.md`. When the model was rebuilt and the study regenerated with the same
lifts, only that line changed, but the review went stale and needed a new independent review
(process-library asu-1, reviews 14 to 16). Options considered: per-generator
canonical content hashes (every generator would need one, and the gate would have to know
them), stripping known provenance lines per file kind (the same, by file name), or masking
digests in any scoped file.

## Decision

- A scoped file whose bytes differ from its blob at `reviewed_commit` in nothing but **full
  digests** has not changed for review currency: line endings are normalised to `\n` and every
  64-hex sha256 (with or without `sha256:`) and every 40-hex commit id, not part of a longer
  alphanumeric run, is masked before comparing (`provenance.DIGEST`, `digest_only`,
  `content_changes`).
- This applies everywhere a review's scope is compared: the review gate (`current: true`), a
  file's review status (`reviews.coverage`), `cheme impact` and the HAZOP review status, all
  through `reviews.scope_changes` / `provenance.content_changes`.
- Shorter hex runs (16-hex value fingerprints, abbreviated commits) and uppercase hex are
  content. An added or deleted file, and a git failure, still count as changed (fail closed).
- Currency of a generated output against its sources is a separate, explicit check
  (`cheme.layout-model-outdated`, `cheme.layout-lifting-study-outdated`), so a regenerated
  output that the review no longer has to look at again is still required to be regenerated.

## Consequences

- Positive: regenerating an output after an input rebuild that does not change its content
  keeps the review; no per-generator code; the gate, coverage and impact agree.
- Negative: the masking is not limited to generated files. A hand edit whose only change is a
  full digest (re-pinning a `sha256:` or commit reference to another revision of a source)
  does not stale a review either; whether that source changed in substance is left to the
  explicit currency checks and `cheme impact`.
- Each changed scoped file costs one `git show`.

## Evidence

- `provenance.digest_only`, `provenance.content_changes`,
  `gitinfo.show`, `reviews.scope_changes`, `lifting.study_findings`.
- Tests: `tests/test_gates.py::test_a_digest_only_regeneration_keeps_a_review_current`,
  `tests/test_layout_model.py::test_validate_and_the_gate_report_an_outdated_lifting_study`.
- Docs: `docs/framework/layout-model.md`, `docs/framework/architecture.md`, template
  `reviews/README.md`.
