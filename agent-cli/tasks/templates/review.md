You are an **independent reviewer** of a new process-library case study: {title}
(`processes/{pid}/`, branch `case/{pid}`, issue #{issue}), produced by a design agent in an
earlier session. You did not write it. Your job is to review, not to redesign: do not change
design files. Follow this folder's AGENTS.md, the skill `review` and `reviews/README.md`.

## Review
- `git log --oneline origin/main..HEAD` and `git diff --stat origin/main..HEAD`; read DESIGN.md,
  process/design-basis.yaml, process/flowsheet.yaml, lca/, process.yaml and runs/*/report.md.
- Re-run yourself (never trust the report): `cheme validate`, `cheme check`, `cheme maturity`,
  `cheme process streams`, `cheme process propagate --check`, `cheme assess lca --coverage`.
- Check: the route and boundary match the issue's scope; balances close and the numbers are
  plausible for this technology (yields, conversions, utilities per kg product, compare with
  general engineering knowledge and the cited sources' facts); every key value is sourced or
  marked ASSUMED; no third-party tables, figures or passages copied (library CLAUDE.md); the
  LCI is per functional unit, consistent with the flowsheet (mass in = mass out within
  tolerance), has no zero-filled or licensed background values, and every gap is described;
  process.yaml is honest about maturity; nothing outside `processes/{pid}/` changed.

## Output
Write `reviews/{date}-pfd-lci-review.md` with the front matter of `reviews/README.md`
(`topic: design`, `reviewed_commit` = current HEAD, `scope`, `reviewer: review-agent`,
`reviewer_kind: agent`, `branch: case/{pid}`, `merge: pending`) and findings with ids
(R-01 ...), severity (critical | high | medium | low), file/line, what is wrong and the fix.
Critical/high = would mislead a reader or breaks the balance/LCI; do not inflate. Commit it
(`git add reviews && git commit`). Do not push.

End your final answer with exactly one line: `VERDICT: merge` (no open critical/high) or
`VERDICT: fix` (open critical/high findings).
