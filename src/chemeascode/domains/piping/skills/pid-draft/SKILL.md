---
name: pid-draft
description: Draft a new P&ID sheet from the design basis and equipment list - start from the empty sheet, add equipment, lines, valves, instruments, signal lines and off-page connectors with cheme fragment (any size of sheet); a generator script using the chemeascode.domains.piping.authoring API, run by cheme run, only for what fragments cannot express. Use when a sheet does not exist yet or a section is redrawn from scratch.
---

# Drafting a new P&ID sheet

## Purpose and when to use

Draft a new sheet in `pid/` when it does not exist yet or a section is redrawn from scratch;
change an existing sheet with `pid-edit`.

## Required inputs and missing inputs

Inputs: the PFD (`process/flowsheet.yaml` and `process/PFD.xml`, skill `process-design`),
`process/design-basis.yaml`, `equipment/equipment-list.yaml`, `piping/line-list.yaml`,
`control/instrument-list.yaml`, `DESIGN.md` for decisions already made.

**Start from the PFD** when the plant has one. `cheme process streams --md` gives the stream
table (pressure, temperature, flow, phase per stream, with provenance) and
`cheme render process/PFD.xml --png` the drawing:
- every PFD step becomes one or more equipment items (spares, trains): add them to the equipment
  list with their `sheet:`, and give the step `links: [{target: equipment, ref: <tag>}]`;
- every material stream becomes a line (or a chain of lines through equipment): add it to the
  line list, and give the stream `{target: line, ref: <number>, sheet: <sheet>}`;
- stream conditions are the operating point for design data and DN; do not copy them into the
  sheet as text, the stream table stays their source;
- a PFD block is a good first guess for a sheet split.
`cheme validate` checks the links (`cheme.process-link-unresolved`) once the list
entries exist.

The sheet split can be declared at concept stage, before anything is drawn: list each sheet in
`plant.yaml` with `status: planned` (no file needed) and give every list item its `sheet:`.
Validate then reports the planned sheet as info and holds back the not-on-pid findings of the
items assigned to it; do not create empty frames to silence it.

## Workflow and tools

1. **Plan on paper first.** For what belongs around a pump, compressor, vessel, exchanger, control
   valve, relief device or instrument, see the hub skill `pid-design`. Write the sheet's content as a short list in `DESIGN.md`: equipment
   (tag, class, the PFD step it implements), lines (number, from, to, DN, the PFD stream it
   carries), valves per line, instruments. Decide a rough
   layout: process flow left to right, equipment in a row at mid height, the equipment-data
   band at the bottom.
2. **Start the file** with `cheme sheet new <sheet> --title '...'`: it writes
   `pid/<sheet>.xml` from the template frame with a real title block (drawing and sheet
   number, title, project, client, site, revision and dates from `plant.yaml`; status
   "for review"; approver, approval date and checker empty), adds the sheet to `plant.yaml`
   `sheets:` or turns a `status: planned` entry to drafted. Change title-block values with
   `cheme sheet meta <sheet> Key=Value ...` (`Revision=B`, `Title=...`, `Status=...`; no
   pairs prints them); it updates the MetaData and the title-block texts together. Never put an
   approver or checker in before the stage is signed off (`cheme.titleblock-approval`).
   Do not copy `snippets/empty-sheet.xml` by hand: its placeholders are reported as
   `cheme.template-metadata`.
3. **Fill it**. Write files with the Write and Edit tools only (no heredocs, `sed -i` or
   `awk`), one command per Bash call, scratch output in `build/` (`AGENTS.md`):
   - **With fragments (prefer this, whatever the sheet's size)**: one item at a time, following
     the `dexpi-xml` skill ("Writing the verbose parts"). `cheme fragment equipment` writes
     equipment with its nozzles and symbol (`--class`, `--tag`, `--nozzle N1:dx,dy:DN`), `line`
     and `segment` the piping systems, `valve`, `tee` and `pipe` what is in them, `offpage` the
     sheet-edge connectors, `instrument` an instrument on a nozzle or segment, `signal` a
     control or trip signal to its valves (it models the actuating system), `note` free text;
     `cheme copy` repeats an item already drawn (`--prefix`, `--tag`, `--offset`). Always
     pass `--sheet pid/<sheet>.xml` so shapes and node positions are found, and paste each part
     where its comment says. A symbol the sheet lacks comes as a SHAPE part
     (`fragment shape NAME` prints one). Run
     `cheme fmt` and `cheme validate` after each item, and
     `cheme render pid/<sheet>.xml --png --crop X0,Y0,X1,Y1` around it to see it placed.
     `cheme show <id>` finds what you wrote earlier by id or tag.
   - **Generator script, when fragments cannot express it** (or the sheet should stay
     generated): write `scripts/draft_<sheet>.py` with the Python API `chemeascode.domains.piping.authoring`
     (start from `scripts/example_draft.py`) and run it with
     **`cheme run scripts/draft_<sheet>.py pid/<sheet>.xml`**. System `python3` and
     `uv run python` cannot import pyDEXPI or chemeascode in a plant repository; `cheme run`
     uses cheme-as-code's interpreter, passes the arguments and exit code through and runs in the
     repository root.
     ```python
     import sys
     from chemeascode.domains.piping.authoring import (
         Sheet,
         Nozzle,
         equipment,
         line,
         valve,
         tee,
         instrument,
     )
     from chemeascode.domains.piping.authoring import offpage, note

     sheet = Sheet.load(sys.argv[1])  # the frame: the empty sheet
     pump = equipment(
         sheet,
         "CentrifugalPump",
         "P-201",
         shape="CENTRIFUGAL_PUMP_SHAPE",
         at=(160, 150),
         nozzles=[Nozzle("N1", (-7.5, 0), 80), Nozzle("N2", (0, -7.5), 50)],
     )
     line(
         sheet,
         "80-W-201",
         dn=80,
         fluid="Water",
         route=[
             offpage("in", at=(40, 150), note="from P-01"),
             valve("HV201", "GateValve", tag="HV-201"),
             pump["N1"],
         ],
     )
     instrument(sheet, "PI-201", at=(175, 125), sensing=pump["N2"])
     sheet.save()  # writes and runs cheme fmt
     ```
     `equipment` (class, tag, catalogue shape, nozzles; a column with `scale=(1.0, 1.6)` and
     `markers=[Marker("COLUMN_PACKED_BED_SHAPE", -20, 1.5), Marker("COLUMN_TRAY_SHAPE", 20)]`
     for its beds and trays, never pasted `fragment equipment` XML), `line` (start port, bends, `valve`,
     `tee`, end port or `offpage`; it builds the system, segments, pipes and node positions
     and puts the number and DN labels beside the route, never on it), `instrument`
     (`sensing=`, `signal_to=` a valve: actuating system, actuator and signal line), `note`
     (free text), `label`. They write the same XML as `cheme fragment` and refuse ids that
     exist. **Do not write your own XML or string-template helpers**; if the API lacks
     something, write that part by hand afterwards (`pid-edit`) or with `cheme fragment`.
   - **Decide the sheet's state** (`scripts/README.md`): if the script stays the source, add
     `generator: {script: scripts/draft_<sheet>.py, frame: <commit with the empty sheet>}` to
     the sheet in `plant.yaml` and from then on change the script and run
     `cheme regen <sheet>`, never the XML. Otherwise leave `generator:` out: the XML is the
     source from now on and later changes are XML edits (`pid-edit`); the script is provenance
     and is never rerun over the sheet. `cheme regen --detach <sheet>` switches a generated
     sheet to hand-maintained.
4. **Validate, render, review** as in `pid-edit`: `cheme validate` until clean (it ends with
   the line naming what it compared), `cheme render pid/<sheet>.xml --png` for the whole
   sheet and `--crop` for details, and check every listed equipment item, line and instrument is
   on the sheet (`equipment-not-on-pid`, `line-not-on-pid`, `instrument-not-on-pid`). Clear the
   drawing findings (`line-through-label`, `line-crossing`, `label-overlap`,
   `label-far-from-owner`; each has a `[crop ...]`): a generator that places labels by a fixed
   offset gets them wrong everywhere at once, so fix the offset in the script and regenerate.
   Then sweep the whole sheet: `cheme render pid/<sheet>.xml --png --tiles auto` and read
   every tile (`--findings` marks the lint's findings on them).
   `cheme diff HEAD --list` before the commit lists every object the sheet adds.
5. **Fill the lists** (`lists-sync`): line list with DN per line (and `segments` where the DN
   changes along a line), instrument list with the printed tags, and the flowsheet links of the
   steps and streams the sheet draws.
6. **Trips and interlocks** go into `control/cause-effect.yaml` (kind `interlocks`: cause tag
   and condition, effects with an action each), not into literal sheet text or instrument-list
   notes. On the sheet put at most a short reference next to the instrument, e.g. `see C&E
   I-07`; validate then checks the tags (`cheme.interlock-unknown-tag`) and asks for an
   entry for every HH/LL switch (`cheme.instrument-no-interlock`).
7. **Commit** the sheet, the plant.yaml entry, the lists and the script together. For a
   generated sheet commit the script and the regenerated sheet in the same commit, so `regen`
   can tell later hand edits from script changes.

## Validation and failure handling

Step 4: `cheme validate` until clean, then render and read the sheet; a finding in a
generated sheet is fixed in the script and the sheet regenerated.

## Outputs and provenance

`pid/<sheet>.xml`, its `plant.yaml` entry, the list entries and any `scripts/draft_<sheet>.py`,
committed together (step 7); the script is the source only if `generator:` names it (step 3).

## Required human judgment

The layout and sheet split (step 1); approver and checker go in only after sign-off (step 2).

## References

Skills `dexpi-xml`, `pid-edit`, `lists-sync`, `process-design`, `pid-design` (engineering content),
`pid-review-design-review` (review before issue); `scripts/README.md`,
`scripts/example_draft.py`.
