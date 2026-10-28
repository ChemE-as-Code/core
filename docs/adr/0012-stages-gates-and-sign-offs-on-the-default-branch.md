# 0012. Stages, gates and sign-offs count only on the default branch, with no unapproved self-review

- **Status:** Accepted
- **Date:** 2026-10-18 (fail-closed hardening on 2026-10-25)

## Context

Plant design proceeds in stages (concept, basic, detail). With agents doing much of the work, a
stage must not be declared done by the same actor that did it, and claims must be tied to an
exact, reviewed state of the files.

## Decision

- Stages are data in `plant.yaml`; each has gates in `checks/checks.yaml` (kinds such as rules,
  on-sheet, review, datasheets, maturity, issues), evaluated by `cheme check`.
- `cheme check --write` signs a stage off into `checks/status.json` with provenance (signer,
  commit, gate results). It refuses a dirty tree, failing gates, a review record that is the
  signer's own (`reviewer_kind: self` or the reviewer is the signer) without an `approved_by`
  naming someone else, and open critical/high review findings or ones "closed" by a commit not
  in HEAD's history.
- A review counts only for the `scope` at its `reviewed_commit` with no changes since. A stage
  counts as reached only when its sign-off is on the default branch; stage work happens on a
  branch and is merged by a human or the reviewer, never the stage agent.
- Gates and reviews fail closed: when git cannot tell, or a stage or gate is unknown, it does not
  pass.

## Consequences

- Positive: separation of duties between author, reviewer and approver, enforced by the tool,
  with the evidence in git.
- Positive: gates are per stage, so artifacts of different maturities coexist.
- Negative: sign-off depends on git state and merge discipline; a repository without a protected
  default branch can still be bypassed by a person with push rights.
- Limitation: gates passing is not a review; independent review remains a human act
  ([0013](0013-calculation-maturity-separate-from-completeness-and-review.md)).

## Evidence

- Review gate, stable review finding ids, sign-off with provenance refusing a self-signed review,
  branch and merge policy: pre-release commit 2df834e, pre-release commit 467a816,
  pre-release commit d060778, pre-release commit c224cc3 in pre-release PR 34
  (pre-release issues 12, 25, 26, 32).
- Fail closed: pre-release PR 281 (pre-release commit f45d2c6).
- `src/chemeascode/project/signoff.py`, `project/checks.py`, `foundation/reviews.py`, the
  template's `STAGES.md` and `AGENTS.md`, `README.md` ("check"),
  [stages and gates](../concepts/stages-and-gates.md).
