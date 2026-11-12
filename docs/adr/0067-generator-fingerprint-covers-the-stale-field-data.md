# 0067. The generator fingerprint covers the stale-field data, not the stale-value code

- **Status:** Proposed
- **Date:** 2026-11-12

## Context

A BFD/PFD records `generator_sha256`, the fingerprint of the generator
(`process.provenance.generator_fingerprint`); a sheet whose fingerprint differs from the
installed cheme-as-code's is reported `cheme.generated-version` until `cheme process build` is
run. Since 0.6 the fingerprint hashes the sheet-drawing modules (`GENERATOR_MODULES`; ADR 0048
added `pfd_sheet.py`, `symbols.py` and the ISO shapes; `props.py` is in it as well).

The stream table and the energy-duty cells of a PFD leave a stale value blank. `props.stale()`
decides which, and asks `propagate.stale_fields` and `simulation.translate.stale_fields`; those
depend on `propagate.py`, `recycle.py` and `duties.py`. None of them is fingerprinted, so a
change to what propagate or simulate write, or to how they judge it stale, can change a drawn
PFD with `generator_sha256` unchanged (core#202). 1.9 widened this (`propagate.WRITTEN` gained
`duty`, ADR 0059; recycle convergence, ADR 0060), 1.10 again (ADR 0061 to 0063).

`cheme validate` does not close the gap for BFD/PFD sheets: it rebuilds generated P&IDs in a
scratch copy (`cheme.generated-sheet-drift`), but checks a process sheet only by its
provenance record (`generated-edited`, `generated-version`, `generated-outdated`). Only `cheme
process build` notices, by writing the sheet.

Options considered (core#202):

- **Fingerprint `propagate.py`, `recycle.py`, `duties.py` and `simulation/translate.py`.**
  Complete, but these modules change in most releases, and each change would mark every BFD/PFD
  in the process library outdated and need a rebuild of all of them, for edits that almost
  never change a drawn sheet.
- **A hand-bumped version constant for the stale-field rules.** Narrow, but relies on someone
  remembering to bump it; nothing would tell a reviewer it was forgotten.
- **Correct the comment and the CHANGELOG only.** Leaves the most likely sheet-changing edit,
  a field that can now (or no longer) be stale, unnoticed.

## Decision

`generator_sha256` also covers the stale-field data, by value: `provenance.STALE_FIELD_DATA`
names, per tool whose values `props.stale()` asks about, the fields it writes (`WRITTEN`) and
the source its values carry (`SOURCE`): `propagate.WRITTEN`, `propagate.SOURCE`,
`simulation.translate.WRITTEN` and `simulation.translate.SOURCE`. `stale_field_data()` writes
them as canonical JSON (sorted keys, no spaces), and the fingerprint hashes that string after
the module files. Adding, removing or renaming a field that a sheet can show as stale, or
changing a tool's source, changes the fingerprint; editing the code that derives the values or
decides whether one is stale does not.

A test keeps the data complete: `build.py` and `pfd_sheet.py` get stale fields only through
`props.stale()`, which asks exactly propagate and translate, and every upper-case module
constant their `stale_fields` and `ours` read is in `STALE_FIELD_DATA`.

## Consequences

- Positive: the edit most likely to change a drawn PFD's blank cells, a field added to or taken
  out of what propagate or simulate write, marks the sheets `cheme.generated-version`.
  Everyday edits to the derivation code leave the library's sheets current.
- Negative: the fingerprint changes once with this decision, so every BFD/PFD needs `cheme
  process build` once (only the `generator_sha256` in the provenance comment changes).
- Known limitation: a change to the derivation code (propagate, recycle, duties, translate) that
  turns a value stale or current is still not noticed by the fingerprint, nor by `cheme
  validate`; `cheme process build` writes the sheet ("written") and the diff shows it. A
  rebuild-and-compare for BFD/PFD sheets in `cheme validate`, as for generated P&IDs, would close
  it and is left open.

## Evidence

- core#202.
- `src/chemeascode/domains/process/provenance.py` (`STALE_FIELD_DATA`, `stale_field_data`,
  `generator_fingerprint`, the comment above `GENERATOR_MODULES`).
- Tests: `tests/test_process.py` (`test_generator_fingerprint_changes_with_the_stale_fields`,
  `test_generator_fingerprint_covers_the_stale_marking_data`,
  `test_generator_fingerprint_covers_what_build_imports`).
