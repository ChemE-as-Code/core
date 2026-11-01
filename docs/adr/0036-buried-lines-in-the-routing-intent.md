# 0036. Buried lines in the routing intent, with a cover rule instead of headroom

- **Status:** Accepted
- **Date:** 2026-10-30

## Context

The layout rules on the model treated every routed pipe as a pipe above grade. In the ammonia-1
run (process-library#304, cheme 1.0.1) the buried DN 1400 cooling-water headers cross roads R-5
and R-6 with their centreline 3.0 m below grade. The road headroom rule reported each crossing
as `cheme.layout-headroom` with "-3.71 m clear", and gates `layout-3d` and `layout-detail`
failed until the owner accepted the four findings (core#70). The same runs gave 43
`layout-support-missing` findings for spans the soil carries. A project could put a route below
grade (`elevation`, `via`, a pinned `route`), but it could not say that the line is buried.
Without that, no rule could tell a buried pipe from a pipe at the wrong height.

Options considered: treat every run below grade as buried (it would silently pass a route that
went below grade by mistake, and change findings for existing projects); a per-plant exemption
of the headroom rule (it hides what the crossing needs); a declaration on the line in
`piping/routing.yaml`, where the routing intent already is.

## Decision

- A `lines[]` entry of `piping/routing.yaml` (the `routing` kind) takes an optional `buried`:
  `true` or `{cover_m?, basis?}`. It applies to the line or the segment the entry names, as the
  other intent does. The schema refuses `buried` together with `rack` or `tier`, and with an
  `elevation` at or above 0. `cover_m` must be positive.
- The router copies it onto the model's pipe as `buried: {cover_m?, basis?}`. The field is
  optional in the model and absent without the declaration. `cheme layout pin` keeps it on a
  replaced route entry.
- A run of a buried pipe is in the ground where its top (axis plus OD / 2 and insulation) is at
  or below grade (z = 0). Such a run gets no road or escape-route headroom finding. It meets no
  steel member, equipment part, envelope or zone volume that stands wholly above grade (a steel
  member judged by its axis). It gets no ladder-clearance finding and no `free-span` or
  `support-missing` finding. A footing or pit below grade still clashes. Risers and runs at or
  above grade keep every rule of a pipe above grade, including the road headroom.
- New rule `cheme.layout-buried-cover` (warning). Where the soil over a buried run's top is
  less than its `cover_m`, it reports the worst point off the roads (key `<pipe>`). Under a
  road the least cover is `max(cover_m, road_cover_m)` (key `<pipe>+<road>`). Vertical runs
  are left out. The finding names the model file, the pipe and road ids, a `box` and the cover
  as `measured`, with a hint pointing at `piping/routing.yaml`.
- New routing rule `rules.road_cover_m`, default 1.2 m. The value is ASSUMED. Secondary sources
  cite 1.2 m (4 ft) under the road surface for uncased pipeline crossings after API RP 1102
  (e.g. <https://help.technicaltoolboxes.com/?p=1956>: "4ft <= H <= 10 ft for highways (API
  1102)"). It was not checked against the standard, and the site's or road authority's value replaces it.
- The `clashes` requirement of the `layout-model` gates counts `cheme.layout-buried-cover` by
  default, with the clashes and `cheme.layout-headroom`. Declaring a line buried therefore does
  not take its road crossings out of the gate.
- The material take-off lists the length of a buried pipe in the ground as rows of their own,
  `group: buried`. A riser counts up to where it leaves the ground.
- Without `buried` nothing changes: the model, the findings and the take-off are as before.

## Consequences

- Positive: a buried main is a declared design choice, checked for its cover. It no longer
  needs an acceptance against a rule that does not apply to it. In ammonia-1 the four headroom
  findings and 43 support-missing infos go, and gates `layout-3d` and `layout-detail` pass
  without the owner's acceptances.
- Positive: the take-off separates buried pipe (coating, trench) from pipe above grade.
- Negative: new optional fields: `buried` on routing entries and model pipes, and
  `road_cover_m` in the routing rules. Older readers that forbid unknown keys see `buried` only
  in models built with the declaration.
- Known limitations: grade is the plane z = 0 (no terrain or road levels). The cover is
  measured to the pipe's top, not to a coating or casing. A sleeve or slab at a crossing is not
  modelled: a crossing protected that way is accepted with its reason. The router does not
  route a buried line itself: its route below grade is given as `elevation`, `via` or a pinned
  `route`. Buried pipes still clash with each other and with anything else below grade.
  Trench, coating and cathodic protection are not in the take-off.

## Evidence

- core#70; ammonia-1 DESIGN.md D-038 (process-library#304, PR process-library#264).
- `src/chemeascode/domains/spatial/schemas.py` (`Buried`, `LineRouting.buried`,
  `RoutingRules.road_cover_m`, `ModelPipe.buried`), `routing.py` (`_pipe`), `model_rules.py`
  (`buried_run`, `buried_cover`, the skips), `engineering_rules.py` (`free_span`),
  `access_rules.py` (`ladder_clearance`), `gates.py` (`CLASH_RULES`), `pins.py`
  (`ROUTE_KEEPS`), `domains/assessment/mto.py` (`_buried_length`).
- `tests/test_layout_buried.py`; `docs/framework/layout-model.md`, `docs/framework/mto.md`, the
  `pipe-routing` skill.
