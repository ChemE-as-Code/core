# 0046. The PFD drawn as an engineering sheet: ISO frame, stream table, utility stubs, junctions

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

The generated PFDs of the process library did not look like engineering drawings. The sheet
was as wide as the layered layout, up to 4.9 m for 20 steps and 1.2 m high, with no frame or
title block. Every utility terminal (power, cooling water, each steam level) was a box with a
dashed line to every step it served, so these lines ran across the whole sheet and set its
height. Mixing steps drawn with the rotary-mixer symbol looked like agitated vessels. Small
offsets between port heights put 1 to 3 mm jogs into straight lines, long titles made nodes
wide, and the stream values were in the XML but not on the drawing. ADR 0022 kept the plain
box for junctions.

## Decision

`cheme process build` (generator 6) draws the PFD as an engineering sheet:

- **Sheet.** The smallest ISO 216 sheet (A3 to A0) or ISO 5457 elongated sheet (A3x3 to A0x3),
  landscape, by area, that holds the drawing, the stream table and the title block; beyond
  those, a sheet A0 high and as wide as needed. ISO 5457 frame (20 mm filing margin), zone
  markers, and a title block (title, subtitle, project, drawing number, case, sheet, generator
  note). A layout with pins is not moved (pins are absolute). The BFD gets the same frame.
- **Rows.** A top-level layout wider than an A0's drawing width (1130 mm) wraps into two to four
  rows (`layout(rows=)`), chosen for a width-to-height ratio near 1.8, on one grid of columns
  shared by all rows; lines between rows and recycles go through the grid router. A feed sits
  in the column just before its first consumer (not all feeds in the first column), so it
  enters where it is used.
- **Utilities.** A terminal with `category: utility`, a `utility:` or only energy ports is
  drawn at each step it serves: a short vertical stub on top of the step's symbol with the
  utility's id as a flag, the stream's id beside it. Its DEXPI ports and connections are
  unchanged; only their node positions move next to the step (and the block ports the stream
  passes, along the stub).
- **Junctions.** `Mixing`, `MixingSimple`, `SplittingMaterial` and `Splitting` are drawn as a
  junction (a short header with tee dots), not a symbol or a box (supersedes that point of ADR
  0022). A step's optional `symbol:` (an ISO symbol name, `junction` or `box`) overrides its
  class's drawing, e.g. a tank modelled as `Mixing`; it is drawing only and excluded from every
  fingerprint while unset. An unknown name is `cheme.process-symbol` (warning) and the class's
  drawing is used. More classes get symbols (`GeneratingFlow`, `TransportingFluids`: pump;
  `SteeringFlow`: control valve; `Crystallizing`: jacketed vessel; `SeparatingMechanically`:
  separator).
- **Drawing.** Inlets are aligned with their source port where a shift of at most 14 mm keeps
  the column's gaps (no small jogs); titles wrap into up to three lines; process lines 0.5,
  equipment 0.35; filled flow arrowheads at each line's end; blocks holding steps are dash-dot
  grey process areas, and delegation lines are drawn like the stream, so a stream reads as one
  line through the area boundary; feeds and products are flags pointing the way of the flow.
- **Stream table.** Below the drawing: per material stream the phase (vapour fraction),
  temperature in °C, pressure in bar(a) (bar(g) if any stream is gauge), mass flow and the mass
  flows of the 14 largest components, and per energy stream the duty, from the default case.
  Assumed values carry `*`; stale or missing values are blank.
- **Renders.** `cheme render` paints the backdrop in the sheet's `BackgroundColor` (white)
  instead of pyDEXPI's viewer grey, unless a filled shape on the sheet has that colour.

## Consequences

- Positive: the 44 PFDs of the process library read as PFDs: a framed sheet of a standard size,
  equipment symbols, local utility connections, straight main lines and the stream data on the
  drawing. The DEXPI model (steps, ports, connections, values) is unchanged by the drawing.
- Negative: every generated BFD/PFD is outdated by the generator bump and must be rebuilt; the
  PFD XML grows by about 60 % (each table cell is a DEXPI `Text`), the BFD by about 30 %.
- Negative: layout pins written for generator 5 may no longer fit the new node sizes (the
  process library's nitric-acid-1 pins were dropped for the automatic layout).
- Known limitations: one sheet per PFD (a large plant is wrapped into rows, not split into
  sheets); utility stubs always sit on top of the symbol (a column's condenser and reboiler
  duties both on top); a utility's flag is its terminal id; the wrapped layout keeps each
  layer's column, so a row can be sparse.

## Evidence

- `src/chemeascode/domains/process/build.py` (stubs, junctions, arrowheads, rows),
  `pfd_sheet.py` (sheet choice, frame, title block, stream table), `layout.py`
  (`_align_inlets`, `rows`), `symbols.py` (`JUNCTION`, `BOX`, `step_drawing`), `schema.py`
  (`Step.symbol`), `model.py` (`cheme.process-symbol`), `piping/render.py`
  (`sheet_background`).
- Tests: `tests/test_process.py`, `tests/test_issue48.py`, `tests/test_symbols.py`.
