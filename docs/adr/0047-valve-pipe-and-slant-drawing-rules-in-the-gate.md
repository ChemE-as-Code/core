# 0047. Lines through valves, along pipes and slanted lines are drawing findings the gate fails on

- **Status:** Proposed
- **Date:** 2026-11-05

## Context

A drawing pass over the process library's asu-1, hda-1 and ammonia-1 P&IDs found that their most
common defect, a control valve's signal line drawn up through the valve body to its actuator,
was invisible to the drawing lint: `cheme.line-through-symbol` checks bubbles and equipment
bodies, not valves or actuators. Signal lines drawn on top of pipes and slanted measuring lines
were not reported either. The defects came from the authoring API's `instrument()`, which drew
every actuator up from the valve and every measuring line as one straight, usually slanted line.

## Decision

- The drawing lint reports `cheme.line-through-valve` (warning: a signal or measuring line
  through a valve body or an actuator head, or another segment's pipe through a valve),
  `cheme.line-on-pipe` (warning: a signal or measuring line on top of a pipe) and
  `cheme.line-not-orthogonal` (info: a signal or measuring line with a slanted stretch).
- The template's `drawing-clean` gate lists the three rules, with `fail_on: info` so the info
  rule fails it too. Findings are accepted one by one with a reason, as for the other rules.
- `instrument()` draws the actuator at right angles to the valve's line on the bubble's side,
  the signal line orthogonal from the bubble's side into the actuator's stem, and the measuring
  line orthogonal, leaving its line at right angles (bends through `sensing_points`).

## Consequences

- Positive: the defects a reviewer sees first on a P&ID are found by `cheme validate` and block
  the basic stage; new sheets drafted with the API do not have them.
- Negative: plant repositories made with an earlier template keep their own `checks.yaml` and
  get the stricter gate only when they add the rules; a generator script rerun with the new
  `instrument()` draws its actuators and measuring lines differently.
- Known limitation: the sensing line's direction is taken from the line drawn through the
  sensing point; at a nozzle on a vessel wall a script may need `sensing_points`.

## Evidence

- `src/chemeascode/domains/piping/drawing.py`, `authoring/builders.py` (`_actuator`,
  `_signal_route`, `_measuring_route`), `templates/project/checks/checks.yaml`.
- `tests/test_drawing.py`, `tests/test_dogfood_fixes.py`, `tests/test_drawing_gates.py`.
