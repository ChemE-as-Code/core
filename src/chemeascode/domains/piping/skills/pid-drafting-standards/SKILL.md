---
name: pid-drafting-standards
description: Make a P&ID sheet look like a professional contractor drawing - layout, line routing, instrument bubbles, valve and actuator placement, labels, connectors and notes - without changing its engineering content. Use when drafting a sheet, before a sheet goes to review, or when asked to tidy or improve the look of P&IDs.
---

# P&ID drafting standards

## Purpose and when to use

A sheet can validate clean and still look amateurish: the drawing lint (`cheme validate`,
`cheme render --findings`) catches overlaps, crossings, lines through valves
(`cheme.line-through-valve`), signal lines on pipes (`cheme.line-on-pipe`) and slanted lines
(`cheme.line-not-orthogonal`), all failing the `drawing-clean` gate, but not a crammed layout,
uneven spacing or a connector on the wrong edge. Use this skill as the visual pass after
`pid-draft` or `pid-edit`, and for a drawing-only clean-up of existing sheets. It changes
**geometry only**: symbol positions and scale, nozzle and node positions, line routes, actuator
orientation, label and note positions. Never add, remove or reconnect an object, or change a tag or value, in this
pass; an improvement that needs one is an engineering change for `pid-edit` and the reviewer.

Read `dexpi-xml` and `pid-edit` first; a sheet with `generator:` in `plant.yaml` is changed in
its script and `cheme regen`, never in the XML (`scripts/README.md`).

## The loop, per sheet

1. Baseline: `cheme render pid/<S>.xml --png --scale 3`, the tiles
   (`--tiles auto --findings`), and `cheme validate` counts by rule. Keep them.
2. **Look** at the full sheet and every tile; write down the defects against the checklist
   below. The lint cannot see most of them.
3. Fix with `cheme move` (symbols, nodes, labels; attached lines follow), `cheme set`
   (e.g. an actuator's `Rotation`, a symbol's scale) and, for bends and polyline points only,
   a direct edit followed by `cheme fmt`. Re-render and look again until the sheet meets the
   standard.
4. Prove nothing but drawing changed: `cheme diff <base> --list --flat` must list only
   `(graphics)` changes, nothing added or removed; `cheme validate` gains no finding of any
   drawing rule (it should lose some). Commit per sheet.

## Checklist

**Layout**
- Flow left to right; the main line straight and horizontal through the middle band.
- Equipment on a common baseline; pumps on a lower baseline; spared pumps (A/B) as identical,
  aligned pairs, tags in the same place.
- Even spacing, no crowded corner while other areas are empty; nothing outside the frame or on
  the title block or notes area.

**Lines**
- Orthogonal, few bends, no jogs of a few millimetres (align the nozzles instead: e.g. a
  compressor drawn at its catalogue scale puts its nozzles over the cooler's).
- No line along another line, through a symbol or through text; parallel lines 6-8 mm apart or
  more; crossings only where unavoidable (record an unavoidable one as an `accept:` in
  `checks/checks.yaml` with the reason).
- Vapour leaves vessels at the top, liquid at the bottom.

**Instruments and valves**
- Bubbles close to their tapping, on one offset, aligned in rows; measuring lines orthogonal
  (bubble level with or straight above/below its tapping; add one elbow if needed).
- A measuring line and a signal line never share a bubble point; move one off.
- **Signal lines never run through a valve body or along the process pipe.** Turn the
  actuator to the side the controller is on (`cheme set <actuator> Rotation=...`), or move the
  controller beside the valve, so the signal is short and straight.
- Control valve stations symmetrical; inline items centred on their line with clearance.

**Labels, connectors, notes**
- Each equipment tag in a consistent place near its symbol (below, or beside where lines leave
  below); line number and DN beside their line, parallel to it, never ambiguous between two
  lines.
- Off-page connectors: incoming on the left edge, outgoing on the right, at one x per edge,
  evenly stacked, their texts clear of each other and of the border. Move one there even if
  that adds a crossing or two: a connector mid-sheet or on the wrong edge is worse than a
  clean right-angle crossing.
  The lint checks the placement (`cheme.offpage-not-on-edge`, in the `drawing-clean` gate): a
  connector to another sheet or the battery limit off the edges fails, a vent to atm., drain or
  hose end may stay by its valve; it does not check which edge.
- Notes left-aligned in the notes area, not in the drawing.

## Pitfalls

- `cheme move` on an instrument node also drags a signal-line point lying exactly on it: check
  every signal line after moving bubbles (`cheme diff --flat`).
- Any byte change to a sheet trips `cheme.hazop-input-changed` for the HAZOP studies stamped
  with it and `cheme.layout-model-outdated`. Do not restamp a HAZOP (`cheme safety hazop
  stamp`) yourself: that records a reassessment, a person's call. Say in the PR that the change
  is drawing-only so they can.
- Moving a tag far from its symbol raises `label-far-from-owner`; keep labels within about
  15 mm of their owner.
- Nozzle positions may be read by the layout model: moving a nozzle along its own symbol
  outline is drawing, moving it to another side is a change to discuss.

## Output

Per sheet: the defects found, what changed, the drawing-rule counts before/after, the commit,
and what was left and why (an engineering decision, or a move that would add crossings).
