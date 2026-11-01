# 0018. Rename plantcode to cheme-as-code, and no compatibility aliases before 1.0

- **Status:** Accepted
- **Date:** 2026-10-22 (rename, 0.7.0); no compatibility layer since 2026-10-21

## Context

The package started as `plantcode` for P&IDs. By 0.6 it covered chemistry, sizing, cost, LCA,
safety and layout, and the repositories had moved to the ChemE-as-Code GitHub organisation.
Keeping old names (package, command, rule ids, schema ids) as aliases, or old module paths as
shims, would double the public surface during a phase of rapid change.

## Decision

- In 0.7.0 the distribution became `cheme-as-code`, the import `chemeascode`, the command
  `cheme`; rule ids `cheme.*`, schema ids `cheme/<kind>/vN`, environment variables `CHEME_*`.
- Pre-1.0 there are no aliases or shims: old names and moved module paths stop working.
  Old names in plant files give an error naming the new one (`requires:`, schema ids, the
  generated-sheet marker); old imports fail with `ModuleNotFoundError`. Plant repositories migrate once, following
  [rename.md](../framework/rename.md). Module moves are recorded in
  [migration-table.md](../framework/migration-table.md) and the CHANGELOG, and
  `tests/test_old_paths.py` checks that removed names stay removed.
- Historical texts (decision records, review records) keep the old names.

## Consequences

- Positive: one name everywhere; a small, honest public surface.
- Negative: every existing plant repository had to be migrated (schema ids, rule ids in
  `accept:` entries, generator scripts, hooks via `cheme git-setup`, regenerated sheets).
- Negative: research code pinned to old versions cannot upgrade without edits; this is why
  research projects pin a tag or commit ([contributing.md](../framework/contributing.md)).
- Limitation: some names stayed for practical reasons (CI secret `PLANTCODE_READ_TOKEN`, the git
  diff driver `dexpi`).

## Evidence

- The rename and its audit; the organisation move; no compatibility layer.
- [rename.md](../framework/rename.md), [SUMMARY.md](../framework/SUMMARY.md), `REFERENCE.md` (formerly the README).
