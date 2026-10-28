---
name: lists-sync
description: Keep the equipment, line and instrument lists (YAML) consistent with the P&ID sheets and the flowsheet links - add missing items, flag removed ones, align types, sheets and nominal diameters. Use after any P&ID change that adds, removes or retags an item or changes a DN, or when cheme validate reports equipment-*, line-*, instrument-* or process-link-unresolved findings.
---

# Keeping the lists in step with the P&IDs

## Purpose and when to use

The P&IDs and the lists describe the same plant. `cheme validate` compares them and ends
with a line naming what it compared (sheets, lists, cross-checks). The schemas are printed by
`cheme schema <kind>`; `cheme schema` alone lists the kinds.

## Required inputs and missing inputs

The sheets in `pid/`, `equipment/equipment-list.yaml`, `piping/line-list.yaml`,
`control/instrument-list.yaml`; leave unknown values out rather than guessing (step 2).

## Workflow and tools

1. Run `cheme validate` and collect the cross-check findings:

   | rule | meaning |
   |---|---|
   | `cheme.equipment-not-listed` / `equipment-not-on-pid` | equipment tag on a sheet and not in `equipment/equipment-list.yaml`, or the reverse |
   | `cheme.line-not-listed` / `line-not-on-pid` | `LineNumber` of a `PipingNetworkSystem` and `piping/line-list.yaml` disagree |
   | `cheme.line-dn-mismatch` | the list's `nominal_diameter` (or a segment's) differs from the sheet |
   | `cheme.line-endpoint-mismatch` | the list's `from`/`to` names equipment the drawn line does not reach, and the line ends at other equipment instead: connect the line to the right nozzle, or fix the list |
   | `cheme.instrument-not-listed` / `instrument-not-on-pid` | printed instrument tag (e.g. `PI-4712.01`) and `control/instrument-list.yaml` disagree |
   | `cheme.line-not-on-pid` with id `<line>/<segment>` | a listed segment whose `SegmentNumber` is not on the line's sheet |
   | `cheme.equipment-duplicate` / `line-duplicate` / `instrument-duplicate` | an entry listed twice; keep one |
   | `cheme.piping-item-not-listed` / `piping-item-not-on-pid` | a tagged safety valve, rupture disc, breather valve, flame arrestor or silencer and `piping/special-items.yaml` disagree |
   | `cheme.interlock-unknown-tag` / `instrument-no-interlock` | a cause or effect tag of `control/cause-effect.yaml` that is in no list and on no sheet; a trip instrument (HH/LL letters, or notes saying it trips) in no interlock, as its cause or in its logic |
   | `cheme.piping-item-type-mismatch` / `piping-item-line-mismatch` | the list's `type` or `line` differs from the sheet |

2. **Equipment** on a P&ID but not in the list: add an entry with `tag`, `type` (the DEXPI
   class, e.g. `CentrifugalPump`), `sheet`, and what you can read from the P&ID (design pressure
   and temperature, material). Leave unknowns out rather than guessing.
3. **In a list but on no P&ID**: an item whose `sheet:` names a planned sheet (or one that did
   not load), or one without `sheet:` at the first stage (or while a sheet did not load), is
   only an info line, one per sheet: it is expected there. After the first stage an item
   without `sheet:` is a warning even while other sheets are planned, so give every item its
   `sheet:`; it is then checked as soon as that sheet is drafted. A warning means the item's
   sheet is drafted (or it has none) and the item is not on it: ask whether it
   was removed on purpose. If yes, delete the entry
   (or say in `notes` why it stays, e.g. a spare drawn on a later sheet); if no, it still needs
   drawing.
4. **Lines**: one entry per `LineNumber` in `piping/line-list.yaml` with `number`, `from`, `to`,
   `nominal_diameter` (`DN50`), `fluid`, and `notes` for anything a reader should know (why it
   is sized as it is, ASSUMED values). `cheme show <LineNumber>` lists the line's segments
   and nodes with their DN. A line whose segments have different DNs (a reducer, a branch)
   gets `segments`, one entry for **every** segment whose DN differs from the line's (the
   reference P&ID's line 47126; `SegmentNumber`s as `cheme show 47126` prints them):
   ```yaml
   - number: "47126"
     from: P4712                     # Nozzle9 of the reciprocating pump
     to: H1008                       # Nozzle10 of the heat exchanger
     nominal_diameter: DN50          # the main run
     notes: DN25 branches - one drain, two instrument connections
     segments:
       - {number: S2, nominal_diameter: DN25, notes: drain via ball valve}
       - {number: S5, nominal_diameter: DN25, notes: instrument connection PI-4712.01}
       - {number: S9, nominal_diameter: DN25, notes: instrument connection PICSA-4712.02}
   ```
   `line-dn-mismatch` then compares segment by segment -- only the segments listed, so a
   missing one goes unchecked.
5. **DN changes**: after changing a line's DN on the sheet (dexpi-xml recipe "Change a line's DN
   everywhere"), change `nominal_diameter` (and the affected `segments`) in the line list in the
   same commit.
6. **Instruments**: one entry per `ProcessInstrumentationFunction` in
   `control/instrument-list.yaml` with its printed `tag` (category + functions + `-` + number,
   e.g. `PICSA-4712.02`), `service`, `sheet`, `notes`.
7. **Tagged piping components** (safety valves, silencers, rupture discs, flame arrestors) are
   DEXPI piping components, neither equipment nor instruments. They go in
   `piping/special-items.yaml` (kind `piping_items`), not in a table in `DESIGN.md`; once the
   file exists, validate compares it with the sheets, and the layout may place them:
   ```yaml
   piping_items:
     - {tag: PSV-201, type: SpringLoadedGlobeSafetyValve, line: G-201, sheet: P-04,
        set_pressure_barg: 34, relief_case: blocked outlet}
     - {tag: S-201, type: Silencer, line: VNT-201, sheet: P-04}
   ```
   The tag is the component's `PipingComponentNumber` (or `PositionNumber`, else
   `PipingComponentName`) as printed; a segment-local number such as `C1` is no tag.
8. **Interlocks**: every trip is one entry of `control/cause-effect.yaml`, the one place that
   says what it does (instrument-list notes and sheet labels only refer to it, "see C&E I-07"):
   ```yaml
   interlocks:
     - id: I-07
       title: Tank low-low level
       cause: {tag: LIA-301, condition: LALL}
       effects:
         - {tag: P-301A, action: stop}   # trip, stop, start, close, open, depressurize, alarm
         - {tag: XV-301, action: close}
       sheet: P-04
       sil: null
       notes: D-024
   ```
   When a tag changes, change it here in the same commit. `cheme cause-effect` writes the
   matrix to `build/cause-effect.html` and `.csv` for review.
9. **Datasheets** (detail stage): one `equipment/datasheets/<TAG>.yaml` per equipment item,
   format and a pump example in `equipment/datasheets/README.md` (`cheme schema datasheet`).
   Its `design.pressure_barg` / `temperature_degc` must match the equipment list
   (`cheme.datasheet-mismatch`), its tag must be listed (`cheme.datasheet-not-listed`);
   mark every value you have not calculated `assumed: true`. A retagged item renames its
   datasheet in the same commit.
   `cheme datasheets draft [--tag T] [--dry-run]` writes a draft for every listed item
   without one (never over an existing file): type, service, design conditions and material
   from the list, its dimensions, its nozzles from the P&IDs, the inlet and outlet conditions
   of the flowsheet streams linked to it, every value with its `source`, unknowns `TBD`, a
   vessel's volume from its dimensions `assumed: true`, and `draft: true`.
   `cheme datasheets fill [--tag T] [--param name=value]` then calculates the sizes a
   draft leaves TBD (exchanger duty and area, pump head, NPSH and power, compressor stages and
   power, column shortcut stages, vessel residence time) with their basis: skill `datasheets`.
   Check every derived value, then remove `draft: true`: the `datasheets` gate does not count a
   draft.
10. **Flowsheet links** (`process/flowsheet.yaml`, skill `process-design`): blocks, steps,
   streams, feeds and products link to equipment, lines, instruments and sheets
   (`links: [{target: equipment | line | instrument | sheet, ref: ..., sheet: ...}]`). A link
   that resolves against no list entry (or a `sheet:` scope the list contradicts) is
   `cheme.process-link-unresolved`: info in `validate`, a warning in the concept gate
   `process-links-concept`, an error in the basic gate `process-links`. When an item is
   retagged, renumbered, moved to another sheet or removed, change the links in the same
   commit; when a P&ID adds equipment or a line for a PFD step or stream, add the link.
   `cheme check --stage basic` runs the `process-links` gate, which names every unresolved
   link and why; the viewer's stream table marks them too.
11. `cheme validate` again until no cross-check finding is left, then commit lists and sheet
   together.

## Validation and failure handling

Run `cheme validate` until no cross-check finding is left (step 11);
`cheme check --stage basic` names every unresolved flowsheet link (step 10).

## Outputs and provenance

Updated lists, `piping/special-items.yaml`, `control/cause-effect.yaml`, datasheets and
flowsheet links, committed with the sheet (step 11).

## Required human judgment

An item in a list but on no drafted sheet: ask whether it was removed on purpose (step 3).

## References

Skills `dexpi-xml`, `process-design`; `equipment/datasheets/README.md`.
