---
name: pfd-drawing
description: Check and improve how the generated PFD (process/PFD.xml from cheme process build) looks - sheet, symbols, utility stubs, junctions, stream table, layout pins - by changing only the drawing hints in process/flowsheet.yaml. Use after cheme process build, before a PFD goes to review, or when a PFD looks cluttered.
---

# The PFD drawing

## Purpose and when to use

The BFD and PFD are generated from `process/flowsheet.yaml` by `cheme process build` and never
edited by hand (ADR 0046). How they look follows from the flowsheet: step classes, terminal
categories, an optional `symbol:` per step, and `layout.pfd` pins. Use this skill to review a
rebuilt PFD and to fix what looks wrong through those inputs.

## What the generator draws

- The smallest ISO sheet (A3 to A0, or elongated A3x3 to A0x3) that holds the drawing and the
  stream table, with frame, zone markers and title block. A layout wider than an A0 wraps into
  rows.
- Each step with the ISO symbol of its DEXPI class; `Mixing`, `MixingSimple`,
  `SplittingMaterial` and `Splitting` as junction tees; `ProcessStep` and unmapped classes as a
  box (a lumped section or package).
- Utility terminals (`category: utility`, a `utility:` given, or only energy ports) as short
  stubs on top of each step they serve, flagged with the terminal id; not as boxes.
- Feeds and products as flags at the left and right; blocks holding steps as dash-dot process
  areas; the stream table (phase, °C, bar, kg/h, main components, duties) below.

## The loop

1. `cheme process build`, then `cheme render process/PFD.xml --png --scale 2` and look at the
   whole sheet, then at crops (`--crop X0,Y0,X1,Y1`) of each process area.
2. Check: does every piece of equipment have the right symbol? Is a tank, drum or rotary mixer
   modelled as `Mixing` drawn as a junction? Are utilities stubs (not boxes with long dashed
   lines)? Are the stream table's values filled (blank: not given or stale; `*`: assumed)?
3. Fix through the inputs, rebuild, look again:
   - **Wrong symbol:** add `symbol:` to the step, a name from the symbol library (as
     `cheme fragment shape` takes it, e.g. `TANK_CONE_ROOF_SHAPE`, `VESSEL_DISHED_ENDS_SHAPE`,
     `STATIC_MIXER_SHAPE`, `MIXER_SHAPE`), `junction` or `box`. It is drawing only and changes
     no balance or fingerprint. An unknown name is `cheme.process-symbol`. Prefer the right
     `class:` when the class itself is wrong (that is an engineering change: say so).
   - **A utility drawn as a box:** give the terminal `category: utility` (and `utility:` with
     its levels where known); that is also what the LCA and TEA read.
   - **Layout:** pins (`layout.pfd`, written by `cheme process layout pin`) fix positions
     absolutely and stop the automatic placement on the sheet. Pins written for an older
     generator often no longer fit (node sizes changed): remove them and rebuild before adding
     new ones; pin only the few nodes that need it, with a comment why.
4. `cheme validate` must stay clean; commit the flowsheet change and the rebuilt sheets
   together.

## Limits

One sheet per PFD; utility stubs always on top of the symbol; a wrapped layout keeps each
layer's column, so a row can be sparse. Record a drawing limit you cannot fix in the PR rather
than distorting the flowsheet to work around it.
