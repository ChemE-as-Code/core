# 0048. Generated process sheets written without indentation

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

ADR 0046 (generator 6) put a stream table, a frame and a title block on the PFD. The process
library's PFDs grew by 55 to 100 % (methanol-1 1.11 to 1.72 MB, hda-1 1.80 to 2.70 MB,
ammonia-1 4.54 to 7.53 MB, asu-1 1.44 to 2.90 MB). Measured on these four sheets, the sheet's
own drawing (stream table, frame, title block) is 29 to 36 % of the bytes, the stream table's
`Text` elements alone 20 to 30 % (244 to 1437 cells at about 1.5 kB each). Half of every file,
table or not, is the two-space indentation pyDEXPI's serializer writes by default.

The candidates that change the drawing were checked against DEXPI 2.0.1, pyDEXPI and the
renderer and rejected:

- **One text per table row or column, with line breaks.** pyDEXPI's SVG export (which `cheme
  render`, `cheme serve` and the viewer use) writes a `Text` as one SVG `<text>`, so a line
  break collapses to a space; DEXPI has no line spacing, so another reader would place the lines
  at its own pitch, not on the table's 4.2 mm rows.
- **Leaving out default presentation attributes.** Every attribute of a DEXPI `Text` (alignment,
  colour, font, position, rotation, size, text) and of a `Stroke` is mandatory (cardinality 1);
  pyDEXPI's classes require them.
- **Rounding coordinates.** The sheet's coordinates are already rounded to 0.001 mm and mostly
  written with one decimal; nothing to gain.
- **Merging the table's and frame's rules into a few polylines.** About 6 % of a PFD, and the
  render changes at the joins (line caps and joins of one polyline are not those of many
  lines).

## Decision

`cheme process build` (generator 7) writes the BFD and the PFD through pyDEXPI's serializer with
no indentation (`DexpiXmlSerializer(indent=build.XML_INDENT)` in `sheets.produce`; the
constant sits in the fingerprinted `build.py`). Every
element still starts a line of its own. The tree, the model pyDEXPI loads, the SVG and the PNG
are byte-identical to the indented form; only whitespace between elements goes.

P&IDs keep `cheme fmt`'s two-space indentation: agents edit them; a generated sheet is not
edited by hand (`cheme.generated-edited`).

The generator fingerprint (`provenance.GENERATOR_MODULES`) also covers `pfd_sheet.py`,
`symbols.py` and `data/iso_shapes.json`, which draw the PFD's sheet and symbols but were left
out; a test keeps every process module `build.py` imports in it.

## Consequences

- Positive: a PFD or BFD is 44 to 48 % smaller on disk (methanol-1 PFD 1.72 to 0.90 MB,
  ammonia-1 7.53 to 3.92 MB), smaller than before ADR 0046. Nothing it shows or holds changes;
  diffs stay line by line with the same line count.
- Negative: the nesting is no longer visible when the XML is read as text. Every sheet is
  outdated (`cheme.generated-version`) and is rebuilt with `cheme process build` once, a
  whole-file diff. `cheme fmt PATH` run on a generated sheet by hand re-indents it, which is an
  edit (`cheme.generated-edited`); `cheme fmt` without paths does not touch process sheets.
- Git compresses the indentation well (the methanol-1 PFD is 46 kB gzipped either way), so the
  saving is in checkouts, downloads of single files and tools reading them, not in pack size.

## Evidence

- `src/chemeascode/domains/process/build.py` (`XML_INDENT`),
  `src/chemeascode/domains/process/sheets.py` (`produce`),
  `src/chemeascode/domains/process/provenance.py` (`GENERATOR_MODULES`).
- Tests: `tests/test_process.py` (`test_sheets_are_written_unindented_and_draw_the_same`,
  `test_generator_fingerprint_covers_what_build_imports`).
