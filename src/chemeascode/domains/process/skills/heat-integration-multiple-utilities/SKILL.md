---
name: heat-integration-multiple-utilities
description: The grand composite curve and how it places several steam, hot oil, cooling water and refrigeration levels, utility pinches, and the process-to-utility approach the shift has to respect. Use when choosing or checking utility levels against process heat demand.
---

# Multiple utility levels

## Purpose and when to use

The composite curves give only the extreme utility needs: a hot utility above the hottest stream
and a cold utility below the coldest. Real plants have levels in between (several steam pressures,
hot oil, cooling water, refrigeration), and the cheapest level that can do a duty is preferred,
subject to the area its smaller driving force needs: low-pressure rather than high-pressure
steam, cooling water rather than refrigeration (Ray and Das, *Process Equipment and Plant Design*,
Elsevier 2020, §5.5). Part of the family `heat-integration`.

## Required inputs and missing inputs

The problem-table cascade (`heat-integration-minimum-utility-targets`), the available utility
levels with their temperatures, and the process-to-utility approach the project uses. Ask for what
is missing.

## Workflow and tools

Engineering guidance only; core has no calculation for utility-level placement. The Python function
`pinch_analysis` returns the grand composite curve as (shifted temperature, net heat flow) points,
which can be used to read the construction below by hand or in a script.

The grand composite curve plots the heat flowing down the problem-table cascade against shifted
temperature (§5.5). Use the feasible cascade, with the minimum hot utility already added at the top,
so the curve touches zero at the pinch. Its ends are the minimum hot and cold utility with only
the extreme levels used.

Placing an intermediate hot utility such as low-pressure steam:

1. Take its shifted temperature: actual temperature minus dTmin/2.
2. Draw a horizontal line at that temperature from the temperature axis to where it first touches
   the curve.
3. The line's length is the most duty that level can take; the dearer level above supplies the rest.

Below the pinch do the same for a cold utility at its temperature plus dTmin/2, to use as much
cooling water as possible before refrigeration (§5.5). Where a utility line touches the curve is a
utility pinch: heat moved across it shifts load from a cheaper level to a dearer one (§5.5). A
network for several levels has more than one pinch to respect, and its grid must include every
utility for the enthalpy to balance.

The shift has to match the approach you mean. The worked method shifts utilities by the same
dTmin/2 as process streams; the source also gives separate typical process-to-utility approaches
(tighter for steam heating and refrigeration, wider for flue gas; §5.3.2, §5.5) and does not
reconcile the two. With a project process-to-utility approach dTu, on the shifted scale a hot
utility at Tu is drawn at Tu - dTu + dTmin/2 and a cold utility at Tu at Tu + dTu - dTmin/2 (an
extension of the textbook method; both reduce to the standard shift when dTu equals dTmin). State
which basis you used.

A study can report savings beyond the network (§5.6): moving duty from high- to low-pressure
steam, scope for power generation, and process changes (reactor temperature, column pressure) that
move the curves themselves.

## Validation and failure handling

A utility line that does not touch the curve does not limit the duty at that level. If a level's
temperature crosses the process side after the shift, it cannot serve that duty; `cheme process
simulate` flags this for declared utility terminals (`sim-utility-level`).

## Outputs and provenance

The curve, each level's temperature, shift basis (dTmin/2 or dTu), duty assigned per level, and the
utility pinches found.

## Required human judgment

The rules for placing a heat pump, a heat engine or a distillation column against the grand
composite curve, and total-site analysis across units sharing steam mains, are not in the cited
source. Name them as the next step; do not supply them. Utility levels available on site are a
project fact to ask for.

## References

- Ray and Das, *Process Equipment and Plant Design*, Elsevier 2020, §5.3.2, §5.5, §5.6.

Retained as general method (cited textbook): the curve construction and utility pinch. Needs review
before operational use: the dTu shift formulas (an extension, not stated in the book).
