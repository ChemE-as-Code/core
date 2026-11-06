# 0022. An ISO 10628-2 symbol library for the P&ID catalogue and the PFD steps

- **Status:** Accepted (the junction drawing amended by [0046](0046-pfd-drawn-as-an-engineering-sheet.md))
- **Date:** 2026-10-27

## Context

The DEXPI 2.0.1 reference P&ID has 25 shapes. cheme-as-code added 17 more, drawn by hand "in the
style of" ISO 10628-2 and registered under their names because no number had been checked. Plants
need more symbols than that (rotary pumps, columns with internals, separators, cyclones, dryers,
check valves, steam traps, ...), and the hand-drawn ones were approximations. The PFD drew every
process step as a plain box, whatever its DEXPI class, so a pump and a column looked the same.

A curated set of ISO 10628-2 symbols exists as DEXPI shapes (PolyLine, Polygon, Ellipse), with
connection points per symbol and the ISO 10628-2 registration number of each symbol's class. It
is not part of this repository: `scripts/import_iso_shapes.py` takes the shape catalogue, the
ports and the annotations as arguments, and the generated JSON is what ships.

## Decision

- cheme-as-code ships a symbol library of 85 ISO 10628-2 symbols:
  `domains/process/data/iso_shapes.json`, read by `domains/process/symbols.py`. It is generated
  by `scripts/import_iso_shapes.py` from the selection `scripts/iso_shapes.yaml` (source name,
  catalogue name, meaning, size, default classes) and is never edited by hand. Each symbol is
  scaled at import to the sheet size cheme-as-code draws it at (15 mm machines, 25-30 mm
  vessels and tanks, 20 mm wide columns, 10 mm long inline items), in sheet millimetres, Y down.
- The library lives in `domains/process` because both the PFD (`process`) and the P&ID
  (`piping`, which may import `process`) draw from it; `foundation` holds no DEXPI specifics.
- Library symbols carry their ISO 10628-2 registration number as
  `SymbolRegistrationNumber` `ISO10628:2012-<number>-A`. Shapes cheme-as-code still draws itself
  (column tray and packed-bed markers, axial compressor, silencer, ambient vaporizer, plate-fin
  exchanger) keep their name as the registration number. No number is invented.
- The hand-drawn shapes a library symbol covers are replaced. `TURBINE_SHAPE`, `BLOWER_SHAPE`,
  `COLUMN_SHAPE`, `GAS_FILTER_SHAPE`, `AIR_COOLER_SHAPE`, `ELECTRIC_HEATER_SHAPE` and
  `GATE_VALVE_SHAPE` keep their names and ids with the ISO geometry; the renamed ones resolve
  through `LEGACY_NAMES` (`CENTRIFUGAL_COMPRESSOR_SHAPE`, `HEAT_EXCHANGER_GENERAL_SHAPE`,
  `SHELL_AND_TUBE_HEAT_EXCHANGER_SHAPE`, `FLAT_BOTTOM_TANK_SHAPE`). A sheet that already has an
  old shape keeps it: every sheet carries its own catalogue.
- The template's `empty-sheet.xml` holds only the shapes it held before (as their ISO
  replacements, `template: true`); every other library symbol is added to a sheet's catalogue on
  first use (`fragment equipment|valve|shape`, `Sheet.use_shape`). New sheets stay small.
- `cheme process build` draws a PFD step with the symbol of its DEXPI step class
  (`STEP_SYMBOLS`, through the class's base classes; `Pumping` a pump, `Distilling` a column,
  `Cooling` a heat exchanger, ...), with its id and title below it and short stubs joining its
  ports to the symbol. Junctions (`SplittingMaterial`, `MixingSimple`) and plain `ProcessStep`
  keep the box. The generator version goes to 5.

## Consequences

- Positive: P&IDs and PFDs use standard symbols with registration numbers; agents have a symbol
  (and its connection points, listed in `shapes.md`) for most equipment without inventing one;
  the PFD reads like a flowsheet.
- Positive: adding a symbol is an entry in `iso_shapes.yaml` and a rerun of the import, then of
  `scripts/build_snippets.py`.
- Negative: every generated BFD/PFD is outdated by the generator bump and must be rebuilt.
- Negative: the registration numbers are taken from the curated annotations, not re-checked
  symbol by symbol against the printed standard. In review, 44 of the 85 were cross-checked
  against the DEXPI 2.0.1 reference P&ID, DEXPI's C02V03 test case and the Wikimedia Commons
  symbol files drawn from EN ISO 10628-2:2012; two annotations were wrong and are overridden in
  `iso_shapes.yaml` with that evidence (reciprocating piston pump X8094, not the diaphragm pump's
  X8095; general turbine 2571, not 2517). The other 41 (most vessels, columns, heat exchangers,
  separators and several valves) were unchecked at first.
- Update (2026-10-28): the vessels, columns and the first heat exchangers were checked against
  the printed table of ISO 10628-2:2012 (Table 2, items 1.1-3.7, the publicly available preview
  pages). The shell-and-tube and plate exchangers are the ISO 14617 symbols 2511, 2512, 2513 and
  2516, not X2511-X2516 (clause 5: X2nnn marks ISO 14617 symbol *examples*), as the DEXPI
  reference writes them; they are overridden in `iso_shapes.yaml`. X8007 is the vessel with
  dished bottom and *surface indication* and X8000 the vessel with a full-tube coil on the
  shell; their descriptions are corrected. Confirmed unchanged: 301, 2061, 2062, 2064, X2062,
  X2063, X2069, X8009, X8200, X8100, X8101, X8011, X8012, X8015 and X8079. Still unchecked
  against the printed table (beyond the preview): the double-pipe, spiral and air-cooler
  exchangers (annotated X2515, X2517, X2505; by the pattern above probably 2515 and 2517
  without X) and the groups from furnaces onwards.
- Limitation: the PFD picks the symbol from the step class only, not from its method; a step
  class without a mapping draws the box.

## Evidence

- `src/chemeascode/domains/process/symbols.py`, `src/chemeascode/domains/process/data/iso_shapes.json`
- `src/chemeascode/domains/piping/authoring/shapes.py`, `scripts/import_iso_shapes.py`,
  `scripts/iso_shapes.yaml`, `scripts/build_snippets.py`
- `src/chemeascode/domains/process/build.py` (`_symbol`, `node_group`)
- `tests/test_symbols.py`
