---
name: pid-edit
description: Change an existing P&ID sheet in pid/ - add, remove or modify equipment, lines, valves or instruments - by editing the DEXPI XML directly, then formatting, validating and rendering until clean. Use for any change to an existing sheet.
---

# Editing a P&ID sheet

## Purpose and when to use

Any change to an existing sheet in `pid/`.

Large restructures (many items, a whole new section) are often easier with a generator script
using `chemeascode.domains.piping.authoring`, run by `cheme run`: see `pid-draft`.

## Required inputs and missing inputs

The sheet `pid/<sheet>.xml` and its entry in `plant.yaml` (`generator:` or not, below).

Read the `dexpi-xml` skill first if you have not in this session; its Conventions and Recipes
(insert a valve or a tee, remove an item, add an instrument, change a DN) cover most edits.

## Workflow and tools

1. **Find the place.** `cheme show <id or tag>` (an XML id, `TagName`, printed instrument
   tag, `LineNumber` or `PipingComponentNumber`) prints the `file:start-end` of the object's
   block and of its drawing, its owner chain, what it references and what references it, each
   with a line number. For equipment it adds the segment and line at each nozzle and what exists
   only for it (branch segments, tees, whole lines); for a valve or instrument the whole
   instrument chain (loop, sensing, signal lines, actuating system, valve). Read those line
   ranges, not the whole file. `grep -n` is the fallback for
   text that is not an object (`grep -n 'T4750' pid/P-01.xml`).
2. **Look at the region** before you change it:
   `cheme render pid/P-01.xml --png --crop X0,Y0,X1,Y1` (sheet mm, Y down; take the
   `at X0,Y0,X1,Y1 mm` region `cheme show` prints for the drawing, plus a 20 mm margin). It
   writes `build/P-01_crop-X0-Y0-X1-Y1.png`, so keep that file as the before picture (or render
   `--rev HEAD` with the same crop later).
   Note free space and nearby coordinates so new symbols sit on the line and off other symbols.
3. **Plan the change in both trees**: what objects are added, removed or changed in the
   conceptual model, and which groups, symbols, node positions, lines and label texts in the
   drawing follow. Removing something: every incoming reference `cheme show` listed must be
   deleted or re-pointed.
4. **Edit the file in place, with the Edit tool** -- never `sed -i`, `awk`, heredocs or a
   `python3 -` rewrite, and one command per Bash call (no loops or `&&` chains; see
   `AGENTS.md`). Use readable ids that say what the object is
   (`GlobeValve_FV101_bypass`). Let cheme-as-code write the verbose XML (see `dexpi-xml`, "Writing
   the verbose parts"):
   - **change what is there**: `cheme move <id> --offset DX,DY` (a symbol with its node
     positions and labels; the attached lines follow), `cheme rename OLD NEW [--children]`
     (an id and every reference; or a tag and its labels; `rename <id> NEWTAG --tag` retags one
     of two objects sharing a tag), `cheme set <id> PROP=VALUE`
     (one data value by its DEXPI name and the labels showing it). Add `--print` to see the
     diff first. These come before any hand edit;
   - **another one like an existing object** (a spare pump, a second identical valve, a line
     with its valves):
     `cheme copy <id or tag> --prefix NEWID --tag NEWTAG --offset DX,DY`. It copies the
     drawing too, renames every id and prints what it did not copy (the pipes at the original's
     nozzles). In the same command give inner valves their own tags (`--rename HV-146=HV-147`,
     `--renumber 144:145`), set the fluid (`--set 'FluidCode=Liquid nitrogen'`), connect an
     open pipe end (`--connect PIPE=ITEM:NODE`) and an instrument's sensing point
     (`--sense-at SEGMENT:X,Y`); the report's `duplicate tags:` must say `none`. Connect the
     rest with fragments;
   - **a new valve, tee, pipe, segment, line, node or label, new equipment or a nozzle on
     existing equipment, an instrument, a signal line (control loop or trip, with its actuating
     system), an off-page connector or a free note**: `cheme fragment <kind> --id ...
     --sheet pid/<sheet>.xml` and paste each part where its comment says;
   - **by hand**: re-pointing references (a pipe's or segment's ends, a ConnectorLine's
     `Source`/`Target`), moving `<Object>` blocks between parents, deleting blocks.
   Do not write a templating script or a deep-copy script for drawing XML; if copy or fragment
   cannot do something you need, say so in your report.
5. **Format, validate, render**:
   ```sh
   cheme fmt pid/P-01.xml
   cheme validate
   cheme render pid/P-01.xml --png --crop X0,Y0,X1,Y1
   ```
   Fix every `error`, then every new `warning`. Repeat until clean. Look at the PNG: symbols on
   their lines, lines meeting at node positions, labels readable and saying the right thing.
   The drawing rules see what an eye misses: `line-through-label`, `line-crossing`,
   `label-overlap`, `label-far-from-owner`, `line-through-symbol`, `line-through-valve` (a
   signal line through a valve to its actuator, an actuator drawn on the pipe: turn the stem at
   right angles to the pipe, the signal arriving from the far side), `line-on-pipe` and
   `line-not-orthogonal` (info) findings come with `[crop X0,Y0,X1,Y1]`; render
   that crop, fix the placement, and quote the `drawing <sheet>:` counts validate prints before
   you write "no overlaps" anywhere. A crossing you cannot avoid is accepted with a reason in
   `checks/checks.yaml` (`accept:`, by the finding's `[id ...]`), not left as a warning.
6. **Review the change** before committing: `cheme diff HEAD --list` prints one line per
   changed plant item (`<kind> <class> <id> [tag]: N added, M removed, K modified`). Every line
   should be an item you meant to change. `--list --verbose` lists each change under its item,
   `--list --flat` one line per object
   (`<kind> <class> <id> [tag] (<domain>) <attrs> -> drawn as <owner|not drawn>`): no changed
   plant item should be `not drawn`. `cheme diff HEAD` writes `build/diff.html` for a person to look at; `--json` is
   the same data for a script.
7. **Keep the lists in step** (`lists-sync` skill): a new or removed tag, line or instrument,
   and a changed DN, go into the equipment, line or instrument list.
8. **Commit** one logical change per commit, message saying what changed on which sheet and why.
   Log the change in `PROGRESS.md` (date, sheet, what, why). `git diff` shows sheets as review
   text with the XML ids as written (after `cheme git-setup`).

**Generated sheets.** If the sheet's entry in `plant.yaml` has `generator:`, do not edit its
XML: change the script and run `cheme regen <sheet>` (validate warns
`generated-sheet-drift` otherwise, and `regen` refuses to overwrite hand edits). If the XML has
to become the source instead, run `cheme regen --detach <sheet>` first, then edit the XML
as above. A sheet without `generator:` is hand-maintained: a `scripts/draft_<sheet>.py` next
to it is provenance only; never rerun it over the sheet.

## Validation and failure handling

Steps 5 and 6: format, validate and render until clean, then review the diff.

Never delete a validation finding by deleting the content it is about unless that is the change
you were asked for.

## Outputs and provenance

The edited sheet, the list changes (step 7), and a commit with its `PROGRESS.md` entry (step 8).

## Required human judgment

Whether each changed item in the diff was meant (step 6); a reason for an accepted crossing
(step 5); what copy or fragment could not do goes in the report (step 4).

## References

Skills `dexpi-xml`, `lists-sync`, `pid-draft`.
