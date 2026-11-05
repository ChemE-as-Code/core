---
name: unit-ops-distillation
description: Distillation columns and their auxiliaries - which arrangement (flash drum, fractionator, reboiled stripper, batch still), overhead and bottoms systems, feed zone, side draws and pumparounds, the usual control loops, and rules of thumb with their source. Use when a column, stripper or still is designed or reviewed; method ranking is separation-method-selection.
---

# Distillation columns

## Purpose and when to use

A column alone separates nothing: the separation comes from vapour returned at the bottom and
liquid returned at the top, so the auxiliaries are part of the operation (Ray and Das, *Process
Equipment and Plant Design*, Elsevier 2020, Ch 11). Use for the arrangement around a column. To
choose between conventional and intensified separations use `separation-method-selection`.

## Required inputs and missing inputs

Feed state and composition, products and purities, operating pressure, whether the column runs
under vacuum, and whether the bottoms can decompose at its boiling temperature. Ask for what is
missing.

## Workflow and tools

Mostly engineering guidance. Core's calculations for this are:

- shortcut and rigorous columns: `process-simulation` and `separation-method-selection`
  (downstream representation);
- column stage estimates: `cheme datasheets fill` (Fenske-Underwood-Gilliland);
- phase and azeotrope checks: `phase-calculation`;
- a batch still without reflux, its cuts and a solvent swap: `still:` on the flowsheet step
  (skill `process-design`). It is a Rayleigh balance with Raoult's law or a constant relative
  volatility, solved by `cheme process propagate` and reported by `cheme process stills`
  (boil-up time and duty per batch).

Arrangement:

| Arrangement | Stages | Feed | Reflux |
|---|---|---|---|
| Flash drum | one | above the liquid level | none |
| Fractionator | many | between top and bottom | liquid at top and vapour at bottom |
| Reboiled stripper | many | at the top, as liquid | vapour only |
| Batch still | one or many | charged before starting | top only; the still is the reboiler |

A total condenser is common. A total reboiler is not: vaporising the whole bottoms gives no
equilibrium stage and concentrates non-volatile impurity on the surface, so a partial reboiler
holding a level is the norm. Full vaporisation is unusual, not necessarily wrong.

Overhead: vapour line, condenser, reflux drum, reflux line, distillate draw, and a route for
non-condensables (dissolved gas in the feed; air leaking into a vacuum column). That route can be
a vent off the drum or the ejector suction off the condenser; a drum without a vent nozzle is not
by itself a defect. With a total condenser the condensate drains by gravity, so the drum sits
below it. A partial condenser draws vapour product and counts as a stage.

Bottoms: the reboiler returns vapour below the bottom tray and above the liquid level. Where the
bottoms would decompose before boiling there may be no reboiler, with superheated stripping steam
injected instead and the separation taken under vacuum; the design then limits time at
temperature. Do not report a missing reboiler on such a column without asking.

Feed zone: tray spacing above the feed is larger to cut entrainment. Where the best feed tray is
uncertain, alternative feed nozzles on neighbouring trays are a deliberate feature.

Side draws leave a chimney tray (not a mass-transfer tray): vapour passes the hatted chimneys,
liquid collects in a pan and leaves, the excess overflows as internal reflux. A pumparound is
drawn from an intermediate tray, cooled and returned above its draw (two trays above in the
source); the trays it spans do not fractionate. Reboiler types are in `unit-ops-heat-transfer`.

Control (Ray and Das Ch 11): column top pressure (manipulated by vent rate, condenser flooding,
hot-vapour bypass or coolant rate; some columns float on a downstream system); reflux drum level
on distillate; top temperature as a quality proxy on reflux; bottom level on the bottoms draw.
Whether a vent valve exists depends on the pressure scheme. On a batch still the heat input is
the controlled variable, because a step in heat floods the column.

Rules of thumb (Ray and Das Ch 11 as read; see References):

- Reflux ratio 1.2 to 1.35 times the minimum (1.1 to 1.2 refrigerated); the optimum is flat.
- About N-1 simple columns for N products on sharp two-product splits. An ordering heuristic only:
  side draws, dividing walls and complex columns give more products from fewer shells.
- Hydrocarbon columns are run slightly above atmospheric so a leak cannot draw air in.
- Overhead condenser pressure drop about 0.15 to 0.25 kg/cm2; overhead vapour line about 15 m/s.
- Trays are built to be loaded from above; a surge from below is a large force on a large tray, so
  steady pressure is a mechanical requirement too.

## Validation and failure handling

Questions for a design: no route for non-condensables anywhere in the overhead; a condenser with
no gravity route to its drum; neither a reboiler nor stripping steam (ask first, see above); a
side draw without a chimney tray; a pumparound returned below its draw; a refluxed column without
a way to adjust reflux (a reboiled stripper and a flash drum have none to adjust); no way to hold
pressure; a partial condenser with no vapour destination. `cheme validate` does not check these.

## Outputs and provenance

State the arrangement, the pressure scheme, and the source of each rule of thumb used. Record in
`DESIGN.md`.

## Required human judgment

Column pressure, vacuum operation, thermal limits of the bottoms, and every relief and
non-condensable provision need a person; nothing here certifies safety.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, Ch 11 (arrangement, control,
  reflux, number of columns).
- `separation-method-selection`, `phase-calculation`, `process-simulation`, `unit-ops-heat-transfer`.
- Retained as general method: arrangement table, overhead/bottoms/side-draw roles, control loops.
- Needs review before operational use: the numeric rules of thumb (condenser pressure drop,
  vapour line velocity, reflux multiples), checked against the source before use.
