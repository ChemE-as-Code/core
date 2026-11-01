# 0003. DEXPI 2.0.1 XML through pyDEXPI as the P&ID format, kept canonical for small diffs

- **Status:** Accepted
- **Date:** 2026-10-17

## Context

P&IDs need an open, vendor-neutral, machine-readable format that keeps both the engineering model
and the drawing. DEXPI 2.0.1 is that standard; pyDEXPI (Process Intelligence Research) loads,
validates, serializes, diffs and renders it. Raw XML, however, produces noisy diffs when a tool
reorders attributes or regenerates ids, and `git diff` of XML is hard to review.

## Decision

- P&ID sheets are DEXPI 2.0.1 XML files (`pid/*.xml`), loaded and serialized with pyDEXPI. Core
  writes no DEXPI loader or serializer of its own. Since the framework restructuring, all model
  loading and export goes through one module, `domains/piping/dexpi_io.py`.
- `cheme fmt` defines the canonical form (pyDEXPI's serializer output, readable object ids via
  `assign_ids`); the pre-commit hook runs `fmt --check`, so diffs stay minimal and ids stay
  stable.
- `cheme git-setup` installs a git textconv driver (`pid/*.xml diff=dexpi` in
  `.gitattributes`) so that `git diff` shows a readable projection keyed by XML ids.
- Generated BFD/PFD sheets are DEXPI XML as well, produced from the process YAML.

## Consequences

- Positive: an open standard, lossless round trip, a validator and an SVG renderer for free.
- Positive: small, reviewable diffs; ids are the keys of findings, review quotes and `accept:`
  entries.
- Negative: XML is verbose for agents; the skills (`dexpi-xml`, `pid-edit`, `pid-draft`) and
  snippets compensate. Text tools (`fmt`, `show`, line index, authoring) are XML-specific.
- Negative: a hard dependency on pyDEXPI's development line
  ([0004](0004-pin-pydexpi-by-git-commit.md)).
- Open: a git-oriented DEXPI YAML serialization is under consideration; architecture.md
  ("Possible DEXPI YAML serialization") records what would change. Nothing of it is decided.

## Evidence

- 0.1.0: lossless DEXPI 2.0.1 load, `fmt`, `git-setup` textconv driver and pre-commit hook;
  readable textconv later.
- One load/export path, enforced by
  `test_dexpi_models_load_and_export_through_one_module` in `tests/test_boundaries.py`.
- `src/chemeascode/domains/piping/fmt.py`, `dexpi_io.py`, `src/chemeascode/integrations/git.py`,
  [architecture.md](../framework/architecture.md).
