"""Engineering rules on the generated 3D model: wall penetrations, rack tiers, vent outlets,
pipe spans, operability, escape, lifting and equipment spacing.

They run with the clash rules of :mod:`chemeascode.domains.spatial.model_rules` (one finding list,
the same ``cheme.layout-...`` ids, ``box`` to highlight) on the model document, the routing
intent and the site plan. The criteria are package tables, every value ASSUMED with its basis
(:mod:`chemeascode.domains.spatial.criteria`, ``domains/piping/data/pipe-spans.yaml``), which a
plant overrides under ``criteria:`` in ``layout/site-plan.yaml``.

Rules (``cheme.layout-...``, level):

- ``wall-penetration`` (warning): a pipe through a building's cladding, its roof or a fire
  wall outside the declared openings, or through any wall of a building or structure it has no
  end in (passing through), or running in a wall's plane; (info) a pipe into a casing (a cold
  box) outside a declared opening (a casing penetration to schedule). The opening that would take
  it is in the model's ``penetrations`` (:mod:`chemeascode.domains.spatial.penetrations`);
- ``tier`` (warning): a pipe running along a rack (level runs of 1 m or more inside the rack's
  strip, along its centreline, between its lowest tier and 1 m over the top one), 2.5 m or more
  in all on another tier than its ``tiers`` rule for that rack (or its own ``tier`` intent) of
  ``piping/routing.yaml`` assigns, or between the tiers (on no tier's steel);
- ``vent-outlet`` (warning): the zone sphere around a vent or relief outlet (a generated zone
  volume of source kind ``vent`` or ``psv_outlet``) reaches a walking level up to the walkway
  headroom (:mod:`chemeascode.domains.spatial.floors`: grade, structure floors, stair treads and
  landings, item platforms, a tank's stair, landing and roof platform, step-overs, building
  floors): the outlet's needed height is given; or a pipe's open end (a vent or relief
  tailpipe) lies under a walking surface: within ``vent_plan_clearance_m`` of it in plan and up
  to ``vent_overhead_m`` below it (it discharges into it); or beside one: within
  ``vent_side_clearance_m`` of its edge in plan, at most the walkway headroom above its floor
  (it discharges into the space of a person standing there);
- ``free-span`` (warning): a level run of a pipe with steel supports in the model (``supports``)
  spans farther between them, or from an unsupported end or bend to the first, than the DN's
  span in the table (liquid or gas column by the fluid's name); ``support-missing`` (info): a
  level run longer than that span with no support in the model at all (a local pipe-way
  without steel). A span is measured between the supports and from the outer ones to the ends
  of the level run (a bend, a nozzle, the pipe's end), along one pipe (one DEXPI segment); a
  buried level run (``buried`` in ``piping/routing.yaml``, below grade) is left out;
- ``operability`` (warning): a manual valve's handwheel or lever, or a transmitter head,
  without a walking level at most ``operator_max_height_m`` (``instrument_max_height_m``) below
  it within ``operator_reach_m`` in plan; an in-line item (valve, check valve, relief valve,
  instrument, filter, ...) inside a casing volume (in a closed casing's footprint, below the
  top of its walls) is not operable from outside unless the casing declares a ``hatch``
  opening within ``casing_reach_m`` of it, and then the hatch must be within reach of a
  walking level outside;
- ``access-enclosed`` (warning): a structure floor, an item platform, a ladder or a stair
  inside a casing volume (nobody can stand or climb there in operation);
- ``access-unconnected`` (warning): a declared stair whose top (foot) landing is farther than
  :data:`~chemeascode.domains.spatial.structures.CONNECT` in plan from the level it climbs to
  (from), or a ladder whose top (foot) is farther than ``LADDER_REACH`` from it: it serves
  nothing there;
- ``escape-ways`` (warning): a structure floor (levels at one elevation whose extents are
  within ``CONNECT``, not across a casing wall) with fewer than two connected ways down to
  grade (declared stairs and ladders that are not enclosed, reach the floor and stand on a
  floor below that itself has a connected way down to grade; generated proposals do not count
  until pinned), or with two or more that are not remote from each other (no two arriving at
  the floor ``escape_remote_fraction`` of its diagonal apart in plan: one incident can block
  both), or with a dead end longer than ``dead_end_m``: with one way (a valve access
  platform) the walk to it from the floor's far end, with more the walk in plan from a point
  of the floor to the nearest point where two of its ways lie 45 degrees or more apart
  (:func:`~chemeascode.domains.spatial.structures.dead_end_walk`; checked on every floor with
  the ways it needs), or an item's platform whose far end is more than ``dead_end_m`` along it
  from its only ladder; without a proposal to pin the finding says to place a way by hand;
- ``escape-travel`` (warning): a structure floor that needs a stair (6 m or higher, or in
  regular use) with no connected declared stair, or a point of it more than
  ``stair_travel_m`` in plan from its nearest one;
- ``lifting`` (warning): an item of ``dimensions.weight`` at or above ``heavy_lift_t`` with no
  crane: in a building without an overhead crane (or one too small), outside one without a
  ``crane_pad`` zone within its reach (``reach_m``, else ``crane_reach_m``; the nearest one
  whose lane is clear, else the nearest), or with its crane lane blocked: the strip from the
  nearest point of the pad over the item to its far side, as wide as the item across the
  direction of travel (the load keeps its orientation) plus ``lane_margin_m`` each side,
  above the item's top plus ``lift_clearance_m`` (pipes not ending at the item, cable trays
  but the drop of the item's own (all of a branch that ends at its motor's ``cable_entry``
  beside it: the cable drop from there is no tray), ducts, steel, walls and roofs, other
  items);
- ``laydown`` (warning): no ``laydown`` zone within the crane's reach of a heavy item whose plan
  is at least the item's footprint;
- ``pad-overlap`` (warning): a ``crane_pad`` or ``laydown`` zone overlapping a rack's strip, a
  structure's or a building's footprint in plan;
- ``spacing`` (warning): two items closer in plan than the equipment spacing table's row for
  their families or classes, unless a separation of the site plan names both;
- ``building-spacing`` (warning): two buildings closer in plan than the building spacing
  table's row for their ``use`` (``data/building-spacing.yaml``), unless a separation of the
  site plan names both;
- ``steel-in-way`` (warning): declared steel (a rack bent, a structure with its stairs and
  ladders, a support post) standing in a road's strip below ``headroom_road_m``; a declared
  support post or its crossbar in a ``crane_pad``, ``laydown``, ``escape``, ``keep_clear`` or
  ``maintenance`` zone volume, in an item's box, through a ladder's cage or less than
  ``ladder_clearance_m`` from its rails. Key ``<steel>+<road, zone, tag or ladder>``;
- ``support-stub`` (warning): a declared support ``stub`` taller than ``support_stub_max_m``
  (key ``<stub>+height``), or standing on the support steel of another line (the crossbar of a
  T-post laid out for another line; key ``<stub>+<that support>``).
"""

from __future__ import annotations

import itertools
import math
from typing import Any

from chemeascode.domains.spatial.geometry3d import (
    TOUCH,
    Box,
    Capsule,
    segment_distance,
    segment_segment,
)
from chemeascode.domains.spatial.layout_validate import plan_outline

#: Ways down a structure floor needs.
WAYS_DOWN = 2
#: A floor at or above this elevation needs a stair, m (as the access proposals).
STAIR_ABOVE = 6.0
#: Runs along a rack off their tier shorter than this in all are left out (the jogs onto and
#: off the rack), m.
TIER_RUN = 2.5


def _box(*boxes: tuple[float, ...]) -> list[float]:
    return [
        round(min(b[0] for b in boxes), 3),
        round(min(b[1] for b in boxes), 3),
        round(min(b[2] for b in boxes), 3),
        round(max(b[3] for b in boxes), 3),
        round(max(b[4] for b in boxes), 3),
        round(max(b[5] for b in boxes), 3),
    ]


def _around(p: Any, r: float) -> list[float]:
    return _box((p[0] - r, p[1] - r, p[2] - r, p[0] + r, p[1] + r, p[2] + r))


def _part_point(part: dict[str, Any]) -> tuple[float, float, float] | None:
    if part.get("centre") is not None:
        return tuple(part["centre"])  # type: ignore[return-value]
    if part.get("start") is not None and part.get("end") is not None:
        a, b = part["start"], part["end"]
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
    return None


def _in_rect(p: Any, rect: tuple[float, ...]) -> bool:
    return rect[0] <= p[0] <= rect[2] and rect[1] <= p[1] <= rect[3]


def _rect_distance(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    dx = max(a[0] - b[2], 0.0, b[0] - a[2])
    dy = max(a[1] - b[3], 0.0, b[1] - a[3])
    return math.hypot(dx, dy)


def _point_rect(p: Any, r: tuple[float, ...]) -> float:
    return math.hypot(max(r[0] - p[0], 0.0, p[0] - r[2]), max(r[1] - p[1], 0.0, p[1] - r[3]))


def _footprint(item: dict[str, Any]) -> list[tuple[float, float]]:
    """The plan outline of an item (:func:`~.layout_validate.plan_outline`): a circle for a
    vertical cylinder or a sphere, else its rectangle turned with the item; its box when the
    model gives no sizes."""
    x0, y0, _, x1, y1, _ = item["bbox"]
    centre = ((x0 + x1) / 2, (y0 + y1) / 2)
    shape = item.get("shape")
    dims = item.get("dimensions") or {}
    if shape in ("vertical_cylinder", "sphere"):
        size = min(x1 - x0, y1 - y0)
        return plan_outline(shape, centre, 0.0, size, size)
    across = dims.get("width") if shape == "box" else dims.get("diameter")
    if shape in ("box", "horizontal_cylinder") and dims.get("length") and across:
        rotation = item.get("rotation_deg") or 0.0
        return plan_outline(shape, item.get("position") or centre, rotation, dims["length"], across)
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


class EngineeringRules:
    """The rules above on the state of a :class:`model_rules._Rules` run (its indexes, the
    pipe ends it found and its ``add``)."""

    def __init__(self, base: Any) -> None:
        from chemeascode.domains.spatial.criteria import criteria
        from chemeascode.domains.spatial.floors import (
            casing_volumes,
            closed_casings,
            walking_levels,
        )

        self.base = base
        self.model = base.model
        self.add = base.add
        self.criteria = criteria(base.plan)
        self.floors = walking_levels(self.model)
        self.casings = [box for _, box in closed_casings(self.model)]
        self.volumes = casing_volumes(self.model)
        self.buildings = {b["id"]: b for b in self.model.get("buildings", [])}
        from chemeascode.domains.spatial.access_rules import AccessRules

        self.access = AccessRules(self)

    def _in_casing(self, p: Any) -> bool:
        return any(_in_rect(p, box) for box in self.casings)

    # -- walls and tiers -------------------------------------------------------------------

    def wall_penetration(self) -> None:
        from chemeascode.domains.spatial.penetrations import crossings

        pipes = {p["id"]: p for p in self.model.get("pipes", [])}
        for pen in self.model.get("penetrations") or crossings(self.model):
            pipe = pipes.get(pen["pipe"])
            if pipe is None:
                continue
            building = pen["owner"] in self.buildings
            r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
            in_wall = (pen.get("length") or 0.0) > 2 * r + 0.5
            casing = (
                pen["end_inside"]
                and not building
                and pen.get("material") != "fire_wall"
                and not in_wall
            )
            o = pen["opening"]
            file = "layout/building.yaml" if building else "layout/structures.yaml"
            if o["side"] == "roof" and pen["end_inside"]:
                hint = (
                    "a roof opening cannot be declared: give the line via points "
                    f"(piping/routing.yaml) that enter {pen['owner']} through a wall, then "
                    "declare that opening"
                )
            elif in_wall:
                hint = (
                    "the route runs in the wall's plane: give it via points that cross the "
                    "wall square (piping/routing.yaml), then declare that opening"
                )
            elif pen["end_inside"]:
                hint = (
                    f"declare the opening in {file} (cheme layout pin {pen['id']}: "
                    f"{o['side']} side, offset {o['offset']:g}, width {o['width']:g}, height "
                    f"{o['height']:g}, sill {o['sill']:g} m), or route the line through an "
                    "existing opening (via points)"
                )
            else:
                hint = f"route it around {pen['owner']} (via points in piping/routing.yaml)"
            x, y, z = pen["point"]
            self.add(
                "info" if casing else "warning",
                "wall-penetration",
                f"pipe {pipe['id']} ({pipe['line']}) {pen['reason']} at "
                f"[{x:.1f}, {y:.1f}, {z:.1f}], outside its declared openings",
                [pipe["id"], pen["wall"]],
                _around(pen["point"], r + 0.1),
                hint,
                key=pen["id"],
            )

    def tier(self) -> None:
        from chemeascode.domains.spatial.model_rules import _pipe_box

        routing = self.base.routing
        rules = self.base.rules
        intent: dict[tuple[str, str | None], float] = {}
        for entry in getattr(routing, "lines", None) or ():
            if entry.tier is not None:
                intent[(entry.line.strip(), entry.segment)] = entry.tier
        racks = [
            (rack["id"], rack["points"], rack["width"], sorted(rack.get("levels") or []))
            for rack in self.model.get("racks", [])
            if rack.get("levels")
        ]
        if not racks:
            return
        for pipe in self.base.pipes:
            line = pipe["line"]
            r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
            points = [tuple(p) for p in pipe["points"]]
            # where it runs along a rack: level runs of 1 m or more inside the rack's strip and
            # along its centreline, on a tier (its bottom on the tier) or between them (None)
            used: dict[str, dict[float | None, float]] = {}
            for a, b in zip(points, points[1:], strict=False):
                length = math.dist(a[:2], b[:2])
                if abs(a[2] - b[2]) > 1e-6 or length < 1.0:
                    continue
                for rack_id, centre, width, levels in racks:
                    if not _along_rack(a, b, centre, width):
                        continue
                    if a[2] - r > levels[-1] + 1.0 or a[2] < levels[0] - 1.0:
                        continue  # over the top tier or under the rack: passing it
                    tier = next((t for t in levels if abs(a[2] - r - t) < 0.05), None)
                    on = used.setdefault(rack_id, {})
                    on[tier] = on.get(tier, 0.0) + length
            for rack_id, tiers in used.items():
                expected, why = self._tier_rule(pipe, rack_id, intent, rules)
                if expected is None:
                    continue
                wrong = [t for t in tiers if t is None or abs(t - expected) > 1e-6]
                if sum(tiers[t] for t in wrong) < TIER_RUN - 1e-6:
                    continue  # a jog where it comes onto or leaves the rack
                where = ", ".join(
                    "between its tiers" if t is None else f"on tier {t:g} m"
                    for t in sorted(wrong, key=lambda t: -1.0 if t is None else t)
                )
                self.add(
                    "warning",
                    "tier",
                    f"pipe {pipe['id']} ({line}) runs along {rack_id} {where} "
                    f"({sum(tiers[t] for t in wrong):.1f} m), {why} says {expected:g} m",
                    [pipe["id"], rack_id],
                    _pipe_box(pipe),
                    "free a lane on that tier (widen the rack, move other lines), pin the route, "
                    "or change the rule in piping/routing.yaml",
                    key=f"{pipe['id']}@{rack_id}",
                )

    @staticmethod
    def _tier_rule(
        pipe: dict[str, Any], rack: str, intent: dict[tuple[str, str | None], float], rules: Any
    ) -> tuple[float | None, str]:
        """The tier a pipe should take on *rack*: its own intent, else the first ``tiers`` rule
        matching its fluid or line prefix."""
        line = pipe["line"]
        keys = (
            (line, pipe["id"]),
            (line, pipe["segment"]),
            (line, pipe.get("segment_number")),
            (line, None),
        )
        for key in keys:
            if key in intent:
                return intent[key], "its tier intent in piping/routing.yaml"
        fluid = (pipe.get("fluid") or "").strip().lower()
        for rule in rules.tiers:
            if rule.rack not in (None, rack):
                continue
            fluids = {f.strip().lower() for f in rule.fluids}
            if fluid and fluid in fluids:
                return rule.elevation, f"the tier rule for {pipe.get('fluid')}"
            if any(line.startswith(p) for p in rule.lines):
                return rule.elevation, "the tier rule for its line prefix"
        return None, ""

    # -- vents -----------------------------------------------------------------------------

    def vent_outlet(self) -> None:
        from chemeascode.domains.spatial.floors import sphere_hits

        headroom = self.base.rules.headroom_walkway_m
        for zone in self.model.get("zones", []):
            for k, volume in enumerate(zone.get("volumes", [])):
                if volume.get("source") != "generated" or volume.get("shape") != "sphere":
                    continue
                if volume.get("source_kind") not in ("vent", "psv_outlet"):
                    continue
                centre, radius = tuple(volume["centre"]), volume["radius"]
                hits = sphere_hits(centre, radius, self.floors, headroom)
                if not hits:
                    continue
                needed = max(n for _, n in hits)
                names = sorted({f.id for f, _ in hits})
                shown = ", ".join(names[:4]) + (
                    f" and {len(names) - 4} more" if len(names) > 4 else ""
                )
                item = volume.get("item") or zone["id"]
                self.add(
                    "warning",
                    "vent-outlet",
                    f"the {zone['kind']} zone {zone['id']} around {item} "
                    f"({volume.get('source_kind')}, {radius:g} m at {centre[2]:.1f} m) reaches "
                    f"the walking level {shown} (up to {headroom:g} m above it); the outlet "
                    f"needs {needed:.1f} m",
                    [zone["id"], item, *names[:4]],
                    _around(centre, radius),
                    "raise the outlet (a vents rule in piping/routing.yaml for a line, or the "
                    "item's elevation), or move it away from the walking level",
                    key=f"{zone['id']}+{item}+{k}",
                )
        self._outlets_below()

    def _outlets_below(self) -> None:
        """A pipe's open end under a walking surface (see the module text)."""
        plan = self.criteria.vent_plan_clearance_m
        over = self.criteria.vent_overhead_m
        side = self.criteria.vent_side_clearance_m
        headroom = self.base.rules.headroom_walkway_m
        for pipe in self.base.pipes:
            for end in pipe.get("open_ends") or ():
                point = pipe["points"][-1 if end == "end" else 0]
                x, y, z = point
                beside = sorted(
                    (floor.distance(x, y), z - floor.z, floor.id)
                    for floor in self.floors
                    if floor.kind != "grade"
                    and -1e-6 <= z - floor.z <= headroom + 1e-6
                    and floor.distance(x, y) <= side + 1e-6
                )
                if beside:
                    d, dz, name = beside[0]
                    names = sorted({b[2] for b in beside})
                    shown = ", ".join(names[:4]) + (
                        f" and {len(names) - 4} more" if len(names) > 4 else ""
                    )
                    self.add(
                        "warning",
                        "vent-outlet",
                        f"the open {end} of pipe {pipe['id']} ({pipe['line']}) at "
                        f"[{x:.1f}, {y:.1f}, {z:.1f}] is {d:.2f} m beside and {dz:.2f} m above "
                        f"the walking level {name}: it discharges where people stand on {shown} "
                        f"(within {side:g} m in plan, up to {headroom:g} m above the floor)",
                        [pipe["id"], *names[:4]],
                        _around(point, max(side, 0.5)),
                        "take the outlet above the headroom of the walking surface or away from "
                        "it (a vents rule in piping/routing.yaml, or pin the tailpipe), or move "
                        "the stair, landing or platform",
                        key=f"{pipe['id']}+{end}+beside",
                    )
                    continue
                above = sorted(
                    (
                        math.hypot(floor.z - z, floor.distance(x, y)),
                        floor.z - z,
                        floor.distance(x, y),
                        floor.id,
                    )
                    for floor in self.floors
                    if floor.kind != "grade"
                    and 1e-6 < floor.z - z <= over + 1e-6
                    and floor.distance(x, y) <= plan + 1e-6
                )
                if not above:
                    continue
                _, dz, d, name = above[0]
                names = sorted({a[3] for a in above})
                shown = ", ".join(names[:4]) + (
                    f" and {len(names) - 4} more" if len(names) > 4 else ""
                )
                self.add(
                    "warning",
                    "vent-outlet",
                    f"the open {end} of pipe {pipe['id']} ({pipe['line']}) at "
                    f"[{x:.1f}, {y:.1f}, {z:.1f}] is {dz:.2f} m below and {d:.2f} m beside the "
                    f"walking level {name}: it discharges into {shown} (within "
                    f"{plan:g} m in plan, {over:g} m above)",
                    [pipe["id"], *names[:4]],
                    _around(point, max(plan, 0.5)),
                    "turn the outlet away from the walking surface and take it above it (a vents "
                    "rule in piping/routing.yaml, or pin the tailpipe), or move the stair, landing "
                    "or platform",
                    key=f"{pipe['id']}+{end}+below",
                )

    # -- supports --------------------------------------------------------------------------

    def free_span(self) -> None:
        from chemeascode.domains.piping.pipe_data import is_liquid, max_span
        from chemeascode.domains.spatial.model_rules import _pipe_box
        from chemeascode.domains.spatial.piping_detail import level_stretches, support_arcs

        on: dict[str, list[tuple[float, float, float]]] = {}
        for support in self.model.get("supports", []):
            on.setdefault(support["pipe"], []).append(tuple(support["point"]))
        from chemeascode.domains.spatial.piping_detail import BY_HAND

        proposed: dict[str, list[str]] = {}
        by_hand: dict[str, list[str]] = {}
        for steel in self.model.get("support_steel", []):
            if steel.get("source") == "generated":
                into = by_hand if BY_HAND in str(steel.get("reason") or "") else proposed
                for pid in steel.get("serves", []):
                    into.setdefault(pid, []).append(steel["id"])
        for pipe in self.base.pipes:
            points = [tuple(p) for p in pipe["points"]]
            if len(points) < 2:
                continue
            liquid = is_liquid(pipe.get("fluid"))
            limit = max_span(pipe.get("dn"), liquid)
            arcs, stretches = level_stretches(points)
            worst = 0.0
            bare = 0.0
            for k, j in stretches:
                if all((pipe["id"], m) in self.base.buried for m in range(k, j + 1)):
                    continue  # buried: the soil carries it
                s0, s1 = arcs[k][0], arcs[j][1]
                found = support_arcs(points, arcs, k, j, on.get(pipe["id"], []))
                if not found:
                    if s1 - s0 > limit + 1e-6:
                        bare = max(bare, s1 - s0)
                    continue
                # the spans between the supports, and from the outer ones to the ends of the
                # level run (a bend, a nozzle, the pipe's end)
                stops = sorted({s0, s1, *found})
                gap = max(b - a for a, b in zip(stops, stops[1:], strict=False))
                if gap > limit + 1e-6:
                    worst = max(worst, gap)
            dn = pipe.get("dn")
            size = f"DN {dn:g}" if dn else "DN ?"
            medium = "liquid" if liquid else "gas"
            posts = proposed.get(pipe["id"], [])
            blocked = by_hand.get(pipe["id"], [])
            note = (
                f"; proposed support steel: {', '.join(posts[:3])}"
                + (f" and {len(posts) - 3} more" if len(posts) > 3 else "")
                + " (cheme layout pin <id>)"
                if posts
                else ""
            ) + (
                f"; no place clear of the other pipes for {', '.join(blocked[:3])}"
                + (f" and {len(blocked) - 3} more" if len(blocked) > 3 else "")
                + " (it would stand in a pipe: place the support by hand, not by pin)"
                if blocked
                else ""
            )
            if worst > 0:
                self.add(
                    "warning",
                    "free-span",
                    f"pipe {pipe['id']} ({pipe['line']}, {size}) spans {worst:.1f} m between "
                    f"supports (> {limit:g} m for {size} {medium}, ASSUMED table){note}",
                    [pipe["id"]],
                    _pipe_box(pipe),
                    "add a support (steel under the run: pipe_supports in "
                    "layout/structures.yaml), carry it on a larger line or intermediate rack "
                    "steel (intermediate_supports of the rack), or route it along steel",
                    key=pipe["id"],
                    measured=worst,
                )
            elif bare > 0:
                self.add(
                    "info",
                    "support-missing",
                    f"pipe {pipe['id']} ({pipe['line']}, {size}) runs {bare:.1f} m level with "
                    f"no support in the model (> {limit:g} m span for {size} {medium}){note}",
                    [pipe["id"]],
                    _pipe_box(pipe),
                    "the run needs supports the model does not have (sleepers, T-posts or a "
                    "pipe-way): declare steel under it (pipe_supports in layout/structures.yaml, "
                    "intermediate_supports of a rack), or route it on a rack",
                    key=pipe["id"],
                    measured=bare,
                )

    # -- operability -----------------------------------------------------------------------

    def _lowest_below(self, p: Any) -> float | None:
        reach = self.criteria.operator_reach_m
        below = [
            floor.z
            for floor in self.floors
            if floor.z <= p[2] + 0.05 and floor.distance(p[0], p[1]) <= reach + 1e-6
        ]
        return max(below) if below else None

    def operability(self) -> None:
        op_max = self.criteria.operator_max_height_m
        inst_max = self.criteria.instrument_max_height_m
        checks: list[tuple[str, str, Any, float, list[str], dict[str, Any], Any]] = []
        for item in self.model.get("inline", []):
            parts = item.get("parts") or []
            names = {p["id"].rsplit("/", 1)[-1]: p for p in parts}
            label = item.get("tag") or item["id"]
            if item.get("kind") == "valve":
                if any(n in names for n in ("actuator", "actuator-lower", "motor", "yoke")):
                    continue  # actuated: operated remotely
                part = names.get("handwheel") or names.get("lever")
                if part is None:
                    continue
                point = _part_point(part)
                what = "handwheel" if "handwheel" in names else "lever"
                checks.append(
                    (
                        "valve",
                        f"valve {label} ({item['line']}) {what}",
                        point,
                        op_max,
                        [item["id"]],
                        names,
                        item.get("operator"),
                    )
                )
            elif item.get("kind") == "instrument" and "transmitter" in names:
                point = _part_point(names["transmitter"])
                checks.append(
                    (
                        "instrument",
                        f"instrument {label} ({item['line']}) transmitter",
                        point,
                        inst_max,
                        [item["id"]],
                        names,
                        item.get("operator"),
                    )
                )
        for equipment in self.model.get("equipment", []):
            nozzles = {n["id"]: n for n in equipment.get("nozzles", [])}
            for part in equipment.get("parts", []):
                if part["id"].endswith("/transmitter"):
                    nozzle = part["id"].rsplit("/", 1)[0]
                    checks.append(
                        (
                            "instrument",
                            f"transmitter at {nozzle}",
                            _part_point(part),
                            inst_max,
                            [nozzle],
                            {"transmitter": part},
                            (nozzles.get(nozzle) or {}).get("operator"),
                        )
                    )
        self._enclosed_items(op_max, inst_max)
        reach = self.criteria.operator_reach_m
        proposed = {
            valve: structure["id"]
            for structure in self.model.get("proposed_structures", [])
            for valve in structure.get("serves") or []
        }
        for kind, what, point, limit, ids, names, operator in checks:
            if point is None or self._in_casing(point):
                continue
            floors, stair = self.access.operating_floors(point, limit)
            if floors:
                ok, blockers = self.access.standing(point, floors)
                if ok:
                    continue
                problem = (
                    f"{what} at {point[2]:.1f} m: no free standing space "
                    f"({self.criteria.standing_space_m:g} m square) in front of it on "
                    f"{', '.join(sorted({f.id for f in floors})[:3])}: blocked by "
                    f"{', '.join(blockers[:4])}" + (" and more" if len(blockers) > 4 else "")
                )
            else:
                below = self._lowest_below(point)
                if stair:
                    where = "only a stair flight reaches it, which is no operating position"
                elif below is not None:
                    where = f"the floor below it is {point[2] - below:.1f} m down"
                else:
                    where = "no floor is below it"
                problem = (
                    f"{what} at {point[2]:.1f} m: {where} (more than {limit:g} m; within "
                    f"{reach:g} m in plan)"
                )
            if operator:
                why = self.access.operator(kind, operator, point, names)
                if why is None:
                    continue
                problem += f"; the declared {operator['kind'].replace('_', ' ')} does not "
                problem += f"answer it: {why}"
            elif ids[0] in proposed:
                problem += (
                    f" (proposed: valve access platform {proposed[ids[0]]}; cheme layout "
                    f"pin {proposed[ids[0]]})"
                )
            self.add(
                "warning",
                "operability",
                problem,
                ids,
                _around(point, 0.3),
                "add a platform or step within reach with room to stand, keep stairs and "
                "steel out of the standing space, or declare an operator in "
                "piping/routing.yaml operators: (chainwheel for an infrequently used valve, "
                "extension_spindle or remote_operator, a transmitter's remote_mount), or move "
                "the valve or instrument (the route)",
                key=ids[0],
            )

    def _enclosed_items(self, op_max: float, inst_max: float) -> None:
        """In-line items inside a casing volume (see the module text)."""
        from chemeascode.domains.spatial.floors import in_casing

        if not self.volumes:
            return
        structures = {s["id"]: s for s in self.model.get("structures", [])}
        reach = self.criteria.casing_reach_m
        for item in self.model.get("inline", []):
            if item.get("kind") == "reducer":
                continue
            point = tuple(item["point"])
            owner = in_casing(point, self.volumes)
            if owner is None:
                continue
            structure = structures[owner]
            label = item.get("tag") or item["id"]
            what = f"{item.get('kind', 'item').replace('_', ' ')} {label} ({item['line']})"
            limit = inst_max if item.get("kind") == "instrument" else op_max
            hatches = sorted(
                (_hatch_distance(point, structure, o), o.get("id") or "?", face)
                for o in structure.get("openings") or []
                if o.get("kind") == "hatch"
                for face in [_hatch_face(point, structure, o)]
            )
            wall = _wall_distance(point, structure)
            if hatches and hatches[0][0] <= reach + 1e-6:
                _, hid, face = hatches[0]
                floors, _ = self.access.operating_floors(face, limit)
                if floors:
                    ok, blockers = self.access.standing(face, floors)
                    if ok:
                        continue
                    self.add(
                        "warning",
                        "operability",
                        f"{what} is worked through hatch {hid} of {owner} at {face[2]:.1f} m, "
                        "but the standing space in front of the hatch "
                        f"({self.criteria.standing_space_m:g} m square) is blocked by "
                        f"{', '.join(blockers[:4])}" + (" and more" if len(blockers) > 4 else ""),
                        [item["id"], owner, *blockers[:4]],
                        _around(face, 0.5),
                        "move the stair flight or steel off the hatch, or move the hatch and the "
                        "item along the casing wall to a free stretch of the platform",
                        key=item["id"],
                    )
                    continue
                self.add(
                    "warning",
                    "operability",
                    f"{what} is worked through hatch {hid} of {owner} at {face[2]:.1f} m, but no "
                    f"walking level outside is within reach of it (at most {limit:g} m below, "
                    f"{self.criteria.operator_reach_m:g} m in plan; a stair flight is no "
                    "operating position)",
                    [item["id"], owner],
                    _around(face, 0.5),
                    "add a platform outside the casing at the hatch (layout/structures.yaml "
                    "levels, an extent outside the frame)",
                    key=item["id"],
                )
                continue
            near = (
                f"; its nearest hatch {hatches[0][1]} is {hatches[0][0]:.1f} m away"
                if hatches
                else ""
            )
            self.add(
                "warning",
                "operability",
                f"{what} at [{point[0]:.1f}, {point[1]:.1f}, {point[2]:.1f}] is inside the "
                f"casing of {owner}, {wall:.1f} m in from its wall: not operable or "
                f"maintainable from outside{near}",
                [item["id"], owner],
                _around(point, 0.3),
                "route the line so the item stands outside the casing (via points or a pinned "
                "route in piping/routing.yaml), or bring it to the casing face and declare an "
                f"access hatch (enclosure openings, kind: hatch) within {reach:g} m of it with a "
                "platform outside",
                key=item["id"],
            )

    # -- escape ----------------------------------------------------------------------------

    def escape(self) -> None:
        from chemeascode.domains.spatial.floors import in_casing, rect_in_casing
        from chemeascode.domains.spatial.structures import (
            ALTERNATIVE_DEG,
            CONNECT,
            LADDER_REACH,
            dead_end_walk,
            part_rect,
            point_rect,
            rect_gap,
            remote_distance,
            remote_ways,
            stair_landings,
            way_arrival,
        )

        for structure in self.model.get("structures", []):
            levels = [lv for lv in structure.get("levels", []) if lv["elevation"] > 1e-6]
            if not levels:
                continue
            sid = structure["id"]
            width, depth = structure["width"], structure["depth"]
            rects: dict[str, list[tuple[float, float, float, float]]] = {}
            for part in structure.get("parts", []):
                name = part["id"].split("/")
                if part["kind"] == "box" and part.get("material") == "grating" and len(name) == 3:
                    rects.setdefault(name[1], []).append(part_rect(part))
            elevation = {lv["id"]: lv["elevation"] for lv in levels} | {"grade": 0.0}
            inside = {
                lv["id"]
                for lv in levels
                if rects.get(lv["id"])
                and all(rect_in_casing(r, lv["elevation"], self.volumes) for r in rects[lv["id"]])
            }
            floor_of = _floors(levels, width, depth, inside)
            floor_of["grade"] = -1
            groups: dict[int, list[dict[str, Any]]] = {}
            for level in levels:
                groups.setdefault(floor_of[level["id"]], []).append(level)

            def group_rects(
                g: int, groups: Any = groups, rects: Any = rects
            ) -> list[tuple[float, float, float, float]]:
                return [r for lv in groups.get(g, []) for r in rects.get(lv["id"], [])]

            def box_of(group: list[dict[str, Any]], z: float, rects: Any = rects) -> list[float]:
                found = [r for lv in group for r in rects.get(lv["id"], [])]
                if not found:
                    return _box((0.0, 0.0, z, 0.0, 0.0, z + 2.0))
                return _box(*((r[0], r[1], z, r[2], r[3], z + 2.0) for r in found))

            # the declared ways and whether each is walkable and connected at both ends
            good: list[tuple[dict[str, Any], int, int]] = []
            for kind, ways in (("stair", structure.get("stairs", [])), ("ladder", None)):
                for way in ways if ways is not None else structure.get("ladders", []):
                    if way.get("source") == "generated":
                        continue
                    ends = (way.get("from"), way.get("to"))
                    if None in ends or any(e not in elevation for e in ends):
                        continue
                    low, high = sorted(ends, key=lambda e: elevation[e])
                    if kind == "stair":
                        landings = stair_landings(way)
                        if landings is None:
                            continue
                        foot, head = landings
                        enclosed = next(
                            (
                                o
                                for r, z in ((foot, elevation[low]), (head, elevation[high]))
                                for o in [rect_in_casing(r, z, self.volumes)]
                                if o
                            ),
                            None,
                        )
                        gap_head = min(
                            (rect_gap(head, r) for r in group_rects(floor_of[high])),
                            default=math.inf,
                        )
                        gap_foot = (
                            0.0
                            if low == "grade"
                            else min(
                                (rect_gap(foot, r) for r in group_rects(floor_of[low])),
                                default=math.inf,
                            )
                        )
                        limit = CONNECT
                        where = way["box"]
                    else:
                        base, top = way["base"], way["top"]
                        mid = tuple((base[i] + top[i]) / 2 for i in range(3))
                        enclosed = next(
                            (
                                o
                                for p in (base, mid)
                                for o in [in_casing(p, self.volumes, 0.05)]
                                if o
                            ),
                            None,
                        )
                        gap_head = min(
                            (point_rect(top, r) for r in group_rects(floor_of[high])),
                            default=math.inf,
                        )
                        gap_foot = (
                            0.0
                            if low == "grade"
                            else min(
                                (point_rect(base, r) for r in group_rects(floor_of[low])),
                                default=math.inf,
                            )
                        )
                        limit = LADDER_REACH
                        where = _around(base, 0.5)[:3] + _around(top, 0.5)[3:]
                    if enclosed:
                        self.add(
                            "warning",
                            "access-enclosed",
                            f"{kind} {way['id']} ({low} to {high}) stands inside the casing "
                            f"of {enclosed}: nobody can "
                            "climb there in operation",
                            [way["id"], sid],
                            list(where),
                            "move it outside the casing (a stair or ladder outside the wall to "
                            "platforms outside it, layout/structures.yaml)",
                            key=way["id"],
                        )
                        continue
                    missing = []
                    if high in inside:
                        missing.append(f"{high} at {elevation[high]:g} m is inside the casing")
                    elif gap_head > limit + 1e-6:
                        missing.append(
                            f"its top is {gap_head:.1f} m from {high} at {elevation[high]:g} m "
                            f"(more than {limit:g} m in plan)"
                        )
                    if low in inside:
                        missing.append(f"{low} at {elevation[low]:g} m is inside the casing")
                    elif gap_foot > limit + 1e-6:
                        missing.append(
                            f"its foot is {gap_foot:.1f} m from {low} at {elevation[low]:g} m "
                            f"(more than {limit:g} m in plan)"
                        )
                    if missing:
                        self.add(
                            "warning",
                            "access-unconnected",
                            f"{kind} {way['id']} ({low} to {high}) does not reach the levels "
                            f"it serves: {'; '.join(missing)}",
                            [way["id"], sid, high],
                            list(where),
                            "move the stair or ladder (side, offset) so its landing meets the "
                            "level's grating, or extend the level to it (extent), in "
                            "layout/structures.yaml",
                            key=way["id"],
                        )
                        continue
                    good.append((way, floor_of[low], floor_of[high]))
            # floors with a connected way down to grade
            down_to: set[int] = {-1}
            changed = True
            while changed:
                changed = False
                for _, low_g, high_g in good:
                    if low_g in down_to and high_g not in down_to:
                        down_to.add(high_g)
                        changed = True
            for g, group in sorted(groups.items()):
                ids = {lv["id"] for lv in group}
                names = ", ".join(sorted(ids))
                z = group[0]["elevation"]
                box = box_of(group, z)
                key = f"{sid}/{sorted(ids)[0]}"
                if ids <= inside:
                    owner = next(
                        (
                            o
                            for r in group_rects(g)
                            for o in [rect_in_casing(r, z, self.volumes)]
                            if o
                        ),
                        sid,
                    )
                    self.add(
                        "warning",
                        "access-enclosed",
                        f"{sid} floor {names} at {z:g} m lies inside the casing of {owner}: "
                        "nobody can stand there in operation, and its ways down do not count",
                        [sid, *sorted(ids)],
                        box,
                        "move the platform outside the casing (an extent outside the frame, "
                        "past the wall; the build proposes one: cheme layout pin "
                        f"{sid}/{sorted(ids)[0]}-out), and bring the valves and instruments "
                        "out to it",
                        key=key,
                    )
                    continue
                if all(lv.get("source") == "generated" for lv in group):
                    continue  # a proposed platform: its ways are proposals too
                down = [w for w, low_g, high_g in good if high_g == g and low_g in down_to]
                proposed = sorted(
                    w["id"]
                    for w in [*structure.get("stairs", []), *structure.get("ladders", [])]
                    if w.get("source") == "generated" and w.get("to") in ids
                )
                # a valve access platform needs one way down; every floor with its ways keeps
                # the dead-end walk within dead_end_m
                needed = 1 if structure.get("serves") else WAYS_DOWN
                note = (
                    f" (proposed: {', '.join(proposed)}; pin them)"
                    if proposed
                    else " (no way could be proposed: place one by hand)"
                )
                arrivals = [a for w in down for a in [way_arrival(w)] if a is not None]
                found = dead_end_walk(arrivals, group_rects(g)) if len(down) >= needed else None
                dead = self.criteria.dead_end_m
                if found is not None and found[0] > dead + 1e-6:
                    walk, far = found
                    if len(arrivals) == 1:
                        text = (
                            f"{sid} floor {names} at {z:g} m has one way down and a walk of "
                            f"{walk:.1f} m to it from its far end (> {dead:g} m)"
                        )
                    else:
                        text = (
                            f"{sid} floor {names} at {z:g} m: from ({far[0]:.1f}, {far[1]:.1f}) "
                            f"a walk of {walk:.1f} m in one direction only before two of its "
                            f"{len(arrivals)} ways down lie {ALTERNATIVE_DEG:g} degrees or more "
                            f"apart (dead end > {dead:g} m)"
                        )
                    self.add(
                        "warning",
                        "escape-ways",
                        text + note,
                        [sid, *sorted(ids)],
                        box,
                        "add a ladder or stair at the dead end's far end, or split the "
                        "platform (layout/structures.yaml; cheme layout pin <proposal>)",
                        key=key,
                    )
                fraction = self.criteria.escape_remote_fraction
                if (
                    needed > 1
                    and len(down) >= needed
                    and not remote_ways(arrivals, group_rects(g), fraction)
                ):
                    apart = max(rect_gap(a, b) for a, b in itertools.combinations(arrivals, 2))
                    self.add(
                        "warning",
                        "escape-ways",
                        f"{sid} floor {names} at {z:g} m has {len(down)} connected ways down "
                        f"to grade, but they arrive at most {apart:.1f} m apart (less than "
                        f"{remote_distance(group_rects(g), fraction):.1f} m, {fraction:g} of "
                        f"the floor's diagonal): one incident can block both{note}",
                        [sid, *sorted(ids), *(w["id"] for w in down)],
                        box,
                        "move one of the ways to the far end of the floor, or add a stair or "
                        "caged ladder there, in layout/structures.yaml (cheme layout pin "
                        "<proposal>)",
                        key=key,
                    )
                if len(down) < needed:
                    self.add(
                        "warning",
                        "escape-ways",
                        f"{sid} floor {names} at {z:g} m has {len(down)} connected way(s) "
                        f"down to grade, needs {needed}{note}",
                        [sid, *sorted(ids)],
                        box,
                        "declare a second stair or caged ladder that reaches the floor and "
                        "stands on a floor with its own way down, in layout/structures.yaml "
                        "(cheme layout pin <proposal>)",
                        key=key,
                    )
                regular = any(lv.get("use") == "regular" for lv in group)
                if z < STAIR_ABOVE - 1e-9 and not regular:
                    continue
                stairs = [w for w in down if "box" in w and "flights" in w]
                limit = self.criteria.stair_travel_m
                if not stairs:
                    stair_props = [
                        w["id"]
                        for w in structure.get("stairs", [])
                        if w.get("source") == "generated" and w.get("to") in ids
                    ]
                    note = (
                        f" (proposed: {', '.join(stair_props)})"
                        if stair_props
                        else " (no proposed stair reaches it: place one by hand)"
                    )
                    self.add(
                        "warning",
                        "escape-travel",
                        f"{sid} floor {names} at {z:g} m has no connected declared stair{note}",
                        [sid, *sorted(ids)],
                        box,
                        "declare a stair to it in layout/structures.yaml (cheme layout "
                        "pin <proposal>), or record why ladders are enough",
                        key=key,
                    )
                    continue
                far = 0.0
                for r in group_rects(g):
                    for c in ((r[0], r[1]), (r[2], r[1]), (r[2], r[3]), (r[0], r[3])):
                        near = min(
                            _point_rect(c, (s["box"][0], s["box"][1], s["box"][3], s["box"][4]))
                            for s in stairs
                        )
                        far = max(far, near)
                if far > limit + 1e-6:
                    self.add(
                        "warning",
                        "escape-travel",
                        f"{sid} floor {names} at {z:g} m: a point {far:.1f} m from "
                        f"its nearest stair (> {limit:g} m)",
                        [sid, *sorted(ids)],
                        box,
                        "add a stair at the far end, or record the longer travel's basis",
                        key=key,
                    )
        for platform in self.model.get("platforms", []):
            for part in platform.get("parts", []):
                if part.get("material") != "grating":
                    continue
                if part["kind"] == "annulus":
                    cx, cy, cz = part["centre"]
                    r = part["radius_end"]
                    rect, z = (cx - r, cy - r, cx + r, cy + r), cz
                elif part["kind"] == "box":
                    rect, z = part_rect(part), part["centre"][2]
                else:
                    continue
                owner = rect_in_casing(rect, z, self.volumes)
                if owner is not None:
                    self.add(
                        "warning",
                        "access-enclosed",
                        f"platform {platform['id']} at {z:.1f} m lies inside the casing of "
                        f"{owner}: nobody can stand there in operation",
                        [platform["id"], owner],
                        _box((rect[0], rect[1], z, rect[2], rect[3], z + 2.0)),
                        "remove it (access: {platforms: []} in layout/equipment-placement.yaml) "
                        "and serve the item from platforms outside the casing",
                        key=platform["id"],
                    )
                    break
        dead = self.criteria.dead_end_m
        for platform in self.model.get("platforms", []):
            walk = _platform_walk(platform)
            if walk is None or walk <= dead + 1e-6:
                continue
            top = platform["ladder"]["top"]
            self.add(
                "warning",
                "escape-ways",
                f"platform {platform['id']} has one ladder and a walk of {walk:.1f} m to it "
                f"from its far end (> {dead:g} m)",
                [platform["id"]],
                _around(top, 1.0),
                "add a second ladder at its far end (access in layout/equipment-placement.yaml)"
                ", or split the platform",
                key=platform["id"],
            )

    # -- lifting ---------------------------------------------------------------------------

    def lift_cases(self) -> list[dict[str, Any]]:
        """One case per item of ``heavy_lift_t`` or more outside a casing: its crane (the
        building's, or the nearest ``crane_pad`` within reach), what blocks the lane, the
        laydown zones within reach that hold it. The ``lifting`` rule reports them;
        :mod:`chemeascode.domains.spatial.lifting` turns them into the lifting study."""
        heavy_t = self.criteria.heavy_lift_t
        reach_default = self.criteria.crane_reach_m
        pads, laydowns = [], []
        for zone in self.model.get("zones", []):
            for volume in zone.get("volumes", []):
                if volume.get("shape") != "box":
                    continue
                x0, y0, _, x1, y1, _ = volume["box"]
                if zone["kind"] == "crane_pad":
                    reach = zone.get("reach_m") or reach_default
                    pads.append((zone["id"], (x0, y0, x1, y1), reach))
                elif zone["kind"] == "laydown":
                    laydowns.append((zone["id"], (x0, y0, x1, y1)))
        cases = []
        for item in self.model.get("equipment", []):
            dims = item.get("dimensions", {})
            part = dims.get("lift_weight") is not None  # the heaviest maintenance lift
            try:
                weight = float((dims.get("lift_weight") if part else dims.get("weight")) or 0.0)
            except (TypeError, ValueError):
                continue
            if weight < heavy_t - 1e-9:
                continue
            x0, y0, z0, x1, y1, z1 = item["bbox"]
            rect = (x0, y0, x1, y1)
            centre = ((x0 + x1) / 2, (y0 + y1) / 2)
            if self._in_casing(centre):
                continue
            case: dict[str, Any] = {
                "item": item,
                "tag": item["tag"],
                "weight": weight,
                "part": part,
                "building": None,
                "pad": None,
                "pads": [p for p, _, _ in pads],
                "blockers": [],
                "reach": reach_default,
            }
            building = next(
                (b for b in self.buildings.values() if _in_rect(centre, b["footprint"])), None
            )
            if building is not None:
                case["building"] = building
                origin = building["footprint"]
            else:
                near = sorted(
                    (_rect_distance(pad, rect), pid, pad, r)
                    for pid, pad, r in pads
                    if _rect_distance(pad, rect) <= r + 1e-6
                )
                origin = rect
                if near:
                    # the nearest pad with a clear lane, else the nearest pad
                    lanes = [(entry, sorted(self._lane(item, entry[2]))) for entry in near]
                    (_, pad_id, pad, reach), blockers = next(
                        (lane for lane in lanes if not lane[1]), lanes[0]
                    )
                    origin = pad
                    case.update(pad=(pad_id, pad), reach=reach)
                    case["blockers"] = blockers
            reach = case["reach"]
            size = sorted((x1 - x0, y1 - y0))
            case["size"] = size
            case["laydowns"] = [
                (lid, round(_rect_distance(box, origin), 3))
                for lid, box in laydowns
                if _rect_distance(box, origin) <= reach + 1e-6
                and sorted((box[2] - box[0], box[3] - box[1]))[0] >= size[0] - 1e-6
                and sorted((box[2] - box[0], box[3] - box[1]))[1] >= size[1] - 1e-6
            ]
            cases.append(case)
        return cases

    def gross_lift_t(self, weight: float) -> float:
        """The gross load of a lift, t: weight x ``lift_dynamic_factor`` x (1 +
        ``lift_rigging_fraction``) (both ASSUMED in the package criteria until the plant
        gives its own). An overhead crane must carry it, not the bare weight."""
        c = self.criteria
        return weight * c.lift_dynamic_factor * (1 + c.lift_rigging_fraction)

    def lifting(self) -> None:
        self._pads_overlap()
        for case in self.lift_cases():
            item, tag, weight = case["item"], case["tag"], case["weight"]
            building = case["building"]
            if building is not None:
                crane = building.get("crane")
                gross = self.gross_lift_t(weight)
                if crane is None or float(crane.get("capacity_t", 0.0)) < gross - 1e-9:
                    has = (
                        f"its crane lifts {float(crane['capacity_t']):g} t"
                        if crane
                        else "it has no overhead crane"
                    )
                    self.add(
                        "warning",
                        "lifting",
                        f"{tag} ({weight:g} t, {gross:.3g} t gross with the dynamic and rigging "
                        f"factors) stands in building {building['id']}: {has}",
                        [tag, building["id"]],
                        _box(tuple(item["bbox"])),
                        "declare a crane: {capacity_t} in layout/building.yaml, or a roof hatch "
                        "and a crane pad outside",
                        key=tag,
                    )
            elif case["pad"] is None:
                pads = case["pads"]
                self.add(
                    "warning",
                    "lifting",
                    f"{tag} ({weight:g} t): no crane pad within reach"
                    + (f" ({', '.join(pads)} too far)" if pads else ""),
                    [tag],
                    _box(tuple(item["bbox"])),
                    "declare a crane_pad zone (with reach_m) in layout/zones.yaml near it",
                    key=tag,
                )
            elif case["blockers"]:
                shown = case["blockers"]
                pad_id = case["pad"][0]
                self.add(
                    "warning",
                    "lifting",
                    f"lift of {tag} ({weight:g} t) from crane pad {pad_id}: its lane is "
                    f"blocked by {', '.join(shown[:6])}"
                    + (f" and {len(shown) - 6} more" if len(shown) > 6 else ""),
                    [tag, pad_id, *shown[:6]],
                    _box(tuple(item["bbox"])),
                    "keep the lane between the pad and the item free above the item's "
                    "top (reroute pipes, move the pad or the item)",
                    key=tag,
                )
            if not case["laydowns"]:
                size = case["size"]
                self.add(
                    "warning",
                    "laydown",
                    f"no laydown zone within {case['reach']:g} m fits {tag} "
                    f"({size[1]:.1f} x {size[0]:.1f} m)",
                    [tag],
                    _box(tuple(item["bbox"])),
                    "declare a laydown zone near it at least as large as its footprint "
                    "(layout/zones.yaml)",
                    key=f"laydown-{tag}",
                )

    def _pads_overlap(self) -> None:
        """Crane pads and laydown zones on a rack, a structure or a building (in plan)."""
        from chemeascode.domains.spatial.layout_validate import box_polygon, strip

        others: list[tuple[str, str, list[list[tuple[float, float]]]]] = []
        for rack in self.model.get("racks", []):
            others.append(("rack", rack["id"], strip(rack["points"], rack["width"])))
        for kind in ("structure", "building"):
            for owner in self.model.get(f"{kind}s", []):
                if owner.get("footprint"):
                    others.append((kind, owner["id"], [box_polygon(owner["footprint"])]))
        for zone in self.model.get("zones", []):
            if zone["kind"] not in ("crane_pad", "laydown"):
                continue
            for k, volume in enumerate(zone.get("volumes", [])):
                if volume.get("shape") != "box":
                    continue
                pad = box_polygon(volume["box"])
                for kind, oid, polygons in others:
                    depth = max((_overlap_depth(pad, q) for q in polygons), default=0.0)
                    if depth <= 0.05:
                        continue
                    what = "crane pad" if zone["kind"] == "crane_pad" else "laydown zone"
                    self.add(
                        "warning",
                        "pad-overlap",
                        f"{what} {zone['id']} overlaps {kind} {oid} by {depth:.1f} m in plan",
                        [zone["id"], oid],
                        _box(tuple(volume["box"])),
                        "move the zone clear of it (layout/zones.yaml): a crane stands and loads "
                        "are laid down on open ground, not under a rack or in a structure",
                        key=f"{zone['id']}+{oid}+{k}",
                    )

    def _lane(
        self,
        item: dict[str, Any],
        pad: tuple[float, ...],
        low: float | None = None,
        tops: dict[str, float] | None = None,
    ) -> set[str]:
        """What stands in the crane lane from *pad* over *item* (see the module text): above
        the item's top plus the lift clearance, or above *low*; with *tops*, the top of each
        thing found is recorded there (m)."""
        x0, y0, _, x1, y1, z1 = item["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        px = min(max(cx, pad[0]), pad[2])
        py = min(max(cy, pad[1]), pad[3])
        length = math.hypot(cx - px, cy - py)
        angle = 0.0 if length < 1e-6 else math.degrees(math.atan2(cy - py, cx - px))
        ux, uy = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        # the load keeps its orientation (tag lines): the lane runs to the item's far side
        # along the direction of travel and is the item's width across it plus the margins
        ex, ey = (x1 - x0) / 2, (y1 - y0) / 2
        along = abs(ux) * ex + abs(uy) * ey
        across = abs(uy) * ex + abs(ux) * ey
        total = length + along
        mid = (px + ux * total / 2, py + uy * total / 2)
        width = 2 * across + 2 * self.criteria.lane_margin_m
        found: set[str] = set()
        if low is None:
            low = z1 + self.criteria.lift_clearance_m
        record = tops if tops is not None else {}

        def hit(name: str, top: float) -> None:
            found.add(name)
            record[name] = max(record.get(name, -math.inf), round(top, 3))

        lane = Box("lane", (mid[0], mid[1], low + 100.0), (total, width, 200.0), angle)
        tag = item["tag"]
        lb = lane.aabb
        for capsule, pipe, _ in self.base.capsules:
            if tag in self.base.ends.get(pipe["id"], {}).values():
                continue
            if not all(
                min(capsule.aabb[i + 3], lb[i + 3]) - max(capsule.aabb[i], lb[i]) > 0
                for i in range(3)
            ):
                continue
            if segment_distance(capsule.a, capsule.b, lane) < capsule.r - TOUCH:
                hit(pipe["id"], capsule.aabb[5])
        from chemeascode.domains.spatial.model_rules import _solids_meet

        for member, _, member_id in self.base.steel.near(lb, 0.0):
            r = getattr(member, "r", 0.0)
            if isinstance(member, Capsule):
                if segment_distance(member.a, member.b, lane) < r - TOUCH:
                    hit(member_id, member.aabb[5])
            elif _solids_meet(member, lane):
                hit(member_id, member.aabb[5])
        for part, _, _ in self.base.parts.near(lb, 0.0):
            if part.id != tag and _solids_meet(part, lane):
                hit(part.id, part.aabb[5])
        for kind, run_of in (("trays", _tray_runs), ("ducts", _duct_runs)):
            for entry in self.model.get(kind) or []:
                runs = run_of(entry)
                if (
                    kind == "trays"
                    and (entry.get("refs") or {}).get("tag") == tag
                    and runs
                    and not entry.get("drop_to")  # ends at a cable_entry beside the item
                ):
                    last = runs[-1]
                    if abs(last.a[2] - last.b[2]) > 1e-6:
                        runs = runs[:-1]  # the drop onto the item it feeds
                for capsule in runs:
                    if (
                        all(
                            min(capsule.aabb[i + 3], lb[i + 3]) - max(capsule.aabb[i], lb[i]) > 0
                            for i in range(3)
                        )
                        and segment_distance(capsule.a, capsule.b, lane) < capsule.r - TOUCH
                    ):
                        hit(entry["id"], capsule.aabb[5])
                        break
        for building in self.buildings.values():
            fx0, fy0, fx1, fy1 = building["footprint"]
            top = building["heights"][1]
            if top <= low:
                continue
            solid = Box(
                building["id"],
                ((fx0 + fx1) / 2, (fy0 + fy1) / 2, top / 2),
                (fx1 - fx0, fy1 - fy0, top),
            )
            if _solids_meet(solid, lane):
                hit(building["id"], top)
        for structure in self.model.get("structures", []):
            for wall in structure.get("walls") or []:
                top = wall["centre"][2] + wall["size"][2] / 2
                if top > low:
                    solid = Box(
                        wall["id"],
                        tuple(wall["centre"]),
                        tuple(wall["size"]),
                        wall.get("rotation_deg") or 0.0,
                    )
                    if _solids_meet(solid, lane):
                        hit(structure["id"], top)
        return found

    # -- spacing ---------------------------------------------------------------------------

    def spacing(self) -> None:
        if not self.criteria.spacing_table:
            return
        from chemeascode.domains.spatial.criteria import spacing_rows
        from chemeascode.domains.spatial.layout_distances import polygon_distance

        declared = set()
        for rule in getattr(self.base.plan, "separations", None) or []:
            declared.add(frozenset((rule.from_, rule.to)))
        items = []
        for item in self.model.get("equipment", []):
            x0, y0, _, x1, y1, _ = item["bbox"]
            if self._in_casing(((x0 + x1) / 2, (y0 + y1) / 2)):
                continue
            items.append((item, _footprint(item)))
        for i, (a, pa) in enumerate(items):
            for b, pb in items[i + 1 :]:
                rows = spacing_rows(a, b)
                if not rows or frozenset((a["tag"], b["tag"])) in declared:
                    continue
                za, zb = a["bbox"], b["bbox"]
                if min(za[5], zb[5]) - max(za[2], zb[2]) <= 0.1:
                    continue  # stacked: one stands on or above the other
                row = max(rows, key=lambda r: r["min_m"])
                if (
                    _rect_distance((za[0], za[1], za[3], za[4]), (zb[0], zb[1], zb[3], zb[4]))
                    >= row["min_m"]
                ):
                    continue
                measured = polygon_distance(pa, pb)
                if measured + 1e-6 >= row["min_m"]:
                    continue
                self.add(
                    "warning",
                    "spacing",
                    f"{a['tag']} to {b['tag']}: {measured:.1f} m < {row['min_m']:g} m "
                    f"({row['basis']})",
                    [a["tag"], b["tag"]],
                    _box(tuple(za), tuple(zb)),
                    "move one of them, or declare the pair's separation with its basis in "
                    "layout/site-plan.yaml",
                    key=f"{a['tag']}+{b['tag']}",
                    measured=measured,
                )

    def building_spacing(self) -> None:
        if not self.criteria.spacing_table:
            return
        from chemeascode.domains.spatial.criteria import building_spacing_rows

        declared = set()
        for rule in getattr(self.base.plan, "separations", None) or []:
            declared.add(frozenset((rule.from_, rule.to)))
        buildings = sorted(self.buildings.values(), key=lambda b: b["id"])
        for i, a in enumerate(buildings):
            for b in buildings[i + 1 :]:
                if frozenset((a["id"], b["id"])) in declared:
                    continue
                rows = building_spacing_rows(a, b)
                if not rows:
                    continue
                row = max(rows, key=lambda r: r["min_m"])
                measured = _rect_distance(tuple(a["footprint"]), tuple(b["footprint"]))
                if measured + 1e-6 >= row["min_m"]:
                    continue
                uses = f" ({a.get('use') or 'no use'} / {b.get('use') or 'no use'})"
                self.add(
                    "warning",
                    "building-spacing",
                    f"buildings {a['id']} and {b['id']}{uses} are {measured:.1f} m apart < "
                    f"{row['min_m']:g} m ({row['basis']})",
                    [a["id"], b["id"]],
                    _box(
                        (*a["footprint"][:2], 0.0, *a["footprint"][2:], a["heights"][1]),
                        (*b["footprint"][:2], 0.0, *b["footprint"][2:], b["heights"][1]),
                    ),
                    "move one of them, or declare the pair's separation in "
                    "layout/site-plan.yaml with its basis (a fire- and blast-rated facing wall, "
                    "a noise assessment)",
                    key=f"{a['id']}+{b['id']}",
                    measured=measured,
                )

    # -- steel where it should not stand ----------------------------------------------------

    def steel_in_way(self) -> None:
        """Declared steel in a road below its headroom; declared support steel in a kept-clear
        zone, in an item or at a ladder (see the module text)."""
        from chemeascode.domains.spatial.geometry3d import part_solid
        from chemeascode.domains.spatial.layout_validate import strip
        from chemeascode.domains.spatial.model_rules import _solids_meet
        from chemeascode.domains.spatial.zones import volume_solid

        headroom = self.base.rules.headroom_road_m
        roads = [
            (road["id"], [list(map(tuple, poly)) for poly in strip(road["points"], road["width"])])
            for road in self.model.get("roads", [])
        ]
        owners: list[tuple[str, str, list[dict[str, Any]]]] = []
        for rack in self.model.get("racks", []):
            owners.append((rack["id"], "rack", rack.get("parts", [])))
        for structure in self.model.get("structures", []):
            parts = list(structure.get("parts", []))
            for way in [*structure.get("stairs", []), *structure.get("ladders", [])]:
                parts += way.get("parts", [])
            owners.append((structure["id"], "structure", parts))
        posts = [s for s in self.model.get("support_steel", []) if s.get("source") != "generated"]
        for post in posts:
            owners.append((post["id"], "support", post.get("parts", [])))

        def solids(parts: list[dict[str, Any]]) -> list[Any]:
            found = []
            for part in parts:
                if part.get("material") not in ("steel", "grating", "cage", "handrail"):
                    continue
                solid = part_solid(part)
                if solid is not None:
                    found.append((part, solid))
            return found

        for owner, what, parts in owners:
            for road, polygons in roads:
                for part, solid in solids(parts):
                    x0, y0, z0, x1, y1, z1 = solid.aabb
                    if z0 >= headroom - 1e-6:
                        continue
                    rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    if not any(_overlap_depth(rect, poly) > 0.01 for poly in polygons):
                        continue
                    self.add(
                        "warning",
                        "steel-in-way",
                        f"{what} {owner} stands in road {road} below its {headroom:g} m "
                        f"headroom ({part['id']} at [{(x0 + x1) / 2:.2f}, {(y0 + y1) / 2:.2f}])",
                        [owner, road],
                        _box(solid.aabb),
                        "keep columns, stairs, ladders and posts out of the road (span it, or "
                        "move the steel), or narrow the declared road with a reason",
                        key=f"{owner}+{road}",
                    )
                    break
        zones = [
            (zone, [volume_solid(v, zone["id"]) for v in zone.get("volumes", [])])
            for zone in self.model.get("zones", [])
            if zone.get("kind") in STEEL_FREE_ZONES
        ]
        # each item's outline in plan (a vertical cylinder's circle, else its package box) over
        # the height of its box
        items = [
            (item["tag"], _footprint(item), item["bbox"][2], item["bbox"][5])
            for item in self.model.get("equipment", [])
        ]
        ladders = _ladder_solids(self.model)
        need = self.criteria.ladder_clearance_m
        for post in posts:
            found = solids(post.get("parts", []))
            hits: dict[str, tuple[str, str]] = {}
            for zone, volumes in zones:
                for part, solid in found:
                    if any(_solids_meet(solid, _as_box(v)) for v in volumes):
                        kind = zone["kind"].replace("_", "-")
                        hits.setdefault(zone["id"], (f"the {kind} zone", part["id"]))
            for tag, outline, bottom, top in items:
                for part, solid in found:
                    x0, y0, z0, x1, y1, z1 = solid.aabb
                    if z0 >= top - TOUCH or z1 <= bottom + TOUCH:
                        continue
                    rect = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    if _overlap_depth(rect, outline) > 0.01:
                        hits.setdefault(tag, ("the item", part["id"]))
            for ladder, rail, cage in ladders:
                for part, solid in found:
                    if not isinstance(solid, Capsule):
                        continue
                    gap = segment_segment(solid.a, solid.b, rail.a, rail.b) - solid.r - rail.r
                    if (cage and gap < -TOUCH) or (not cage and gap < need - TOUCH):
                        hits.setdefault(ladder, ("ladder", part["id"]))
            for thing, (what, part_id) in sorted(hits.items()):
                self.add(
                    "warning",
                    "steel-in-way",
                    f"support steel {post['id']} ({part_id}) stands in {what} {thing}",
                    [post["id"], thing],
                    None,
                    "move the post along its pipe out of it, or carry the pipe from steel "
                    "nearby (a bracket, a crossbar of a neighbouring post)",
                    key=f"{post['id']}+{thing}",
                )

    def support_stub(self) -> None:
        """A declared stub taller than ``support_stub_max_m``, or standing on the support steel
        of another line (see the module text)."""
        from chemeascode.domains.spatial.piping_detail import lines_served, members_below

        stub_max = self.criteria.support_stub_max_m
        for post in self.model.get("support_steel", []):
            if post.get("source") == "generated" or post.get("kind") != "stub":
                continue
            top, base = float(post["top"]), float(post.get("base") or 0.0)
            at = (float(post["at"][0]), float(post["at"][1]))
            box = _box((at[0] - 0.2, at[1] - 0.2, base, at[0] + 0.2, at[1] + 0.2, top))
            height = top - base
            serves = lines_served(self.model, post)
            if height > stub_max + 1e-6:
                self.add(
                    "warning",
                    "support-stub",
                    f"support stub {post['id']} is {height:.2f} m tall (base {base:.3f}, top "
                    f"{top:.3f} m; > {stub_max:g} m): a column on steel, not a stub",
                    [post["id"]],
                    box,
                    "carry the pipe from steel close below it (a bracket off a structure or "
                    "rack column, a crossbar), or declare a post or T-post from grade or a "
                    "frame of its own (kind t_post / post, from: grade)",
                    key=f"{post['id']}+height",
                    measured=height,
                )
            on = [
                support
                for tos, _, support in members_below(self.model, at, top)
                if abs(tos - base) <= 0.01 and support is not None and support is not post
            ]
            for support in on[:1]:
                carried_lines = lines_served(self.model, support)
                if serves & carried_lines:
                    continue  # the same line's own steel
                carried = ", ".join(sorted(carried_lines)) or "no pipe"
                self.add(
                    "warning",
                    "support-stub",
                    f"support stub {post['id']} stands on {support['id']}, the support steel "
                    f"of line {carried}: that post was laid out for its own line, not this load",
                    [post["id"], support["id"]],
                    box,
                    "stand it on structure or rack steel, or give it a post of its own; or "
                    "check and declare the carrying post for both lines (a frame)",
                    key=f"{post['id']}+{support['id']}",
                )

    def run(self) -> None:
        self.wall_penetration()
        self.tier()
        self.vent_outlet()
        self.free_span()
        self.operability()
        self.access.run()
        self.escape()
        self.lifting()
        self.spacing()
        self.building_spacing()
        self.steel_in_way()
        self.support_stub()


#: Zone kinds that support steel keeps out of (crane pads and laydowns, escape routes, kept-clear
#: and maintenance spaces).
STEEL_FREE_ZONES = ("crane_pad", "laydown", "escape", "keep_clear", "maintenance")


def _as_box(solid: Any) -> Box:
    """A zone volume as a box (a cylinder's or a sphere's bounding box)."""
    if isinstance(solid, Box):
        return solid
    a = solid.aabb
    centre = ((a[0] + a[3]) / 2, (a[1] + a[4]) / 2, (a[2] + a[5]) / 2)
    return Box("zone", centre, (a[3] - a[0], a[4] - a[1], a[5] - a[2]))


def _ladder_solids(model: dict[str, Any]) -> list[tuple[str, Capsule, bool]]:
    """Every ladder rail and cage of the model as a capsule: ``(ladder id, capsule, cage)``."""
    from chemeascode.domains.spatial.access_rules import _ladder_parts

    found = []
    for ladder, part in _ladder_parts(model):
        r = part.get("radius")
        if r is None:
            r = max(part.get("profile") or (0.07,)) / 2
        capsule = Capsule(part["id"], tuple(part["start"]), tuple(part["end"]), float(r))
        found.append((ladder, capsule, part.get("material") == "cage"))
    return found


def _along_rack(a: Any, b: Any, centre: list[Any], width: float) -> bool:
    """Whether the plan segment *ab* lies inside the strip of a rack (its *centre* line,
    *width*) and runs along it."""
    for c, d in zip(centre, centre[1:], strict=False):
        length = math.dist(c, d)
        if length < 1e-9:
            continue
        ux, uy = (d[0] - c[0]) / length, (d[1] - c[1]) / length
        ok = True
        for p in (a, b):
            t = (p[0] - c[0]) * ux + (p[1] - c[1]) * uy
            n = -(p[0] - c[0]) * uy + (p[1] - c[1]) * ux
            if t < -1e-6 or t > length + 1e-6 or abs(n) > width / 2 + 1e-6:
                ok = False
                break
        if not ok:
            continue
        dx, dy = b[0] - a[0], b[1] - a[1]
        run = math.hypot(dx, dy)
        if run > 1e-9 and abs(dx * ux + dy * uy) / run > 0.9:
            return True
    return False


def _floors(
    levels: list[dict[str, Any]], width: float, depth: float, inside: set[str] | None = None
) -> dict[str, int]:
    """The floor of each level of a model structure: levels at one elevation whose extents are
    within ``CONNECT`` of each other share one, unless a casing wall is between them (one is
    inside the casing, *inside*, the other is not); as the access proposals."""
    from chemeascode.domains.spatial.structures import CONNECT

    inside = inside or set()
    ordered = sorted(levels, key=lambda lv: (lv["elevation"], lv["id"]))
    floor = {lv["id"]: k for k, lv in enumerate(ordered)}
    changed = True
    while changed:
        changed = False
        for a in ordered:
            for b in ordered:
                if floor[a["id"]] == floor[b["id"]]:
                    continue
                if abs(a["elevation"] - b["elevation"]) > 1e-6:
                    continue
                if (a["id"] in inside) != (b["id"] in inside):
                    continue
                ax0, ay0, ax1, ay1 = a.get("extent") or (0.0, 0.0, width, depth)
                bx0, by0, bx1, by1 = b.get("extent") or (0.0, 0.0, width, depth)
                c = CONNECT
                if ax0 <= bx1 + c and bx0 <= ax1 + c and ay0 <= by1 + c and by0 <= ay1 + c:
                    low = min(floor[a["id"]], floor[b["id"]])
                    old = {floor[a["id"]], floor[b["id"]]}
                    for key, value in list(floor.items()):
                        if value in old:
                            floor[key] = low
                    changed = True
    return floor


def _platform_walk(platform: dict[str, Any]) -> float | None:
    """The walk along a platform from its far end to its ladder, m (None without a grating)."""
    gratings = [p for p in platform.get("parts", []) if p.get("material") == "grating"]
    if not gratings:
        return None
    top = platform["ladder"]["top"]
    first = gratings[0]
    if first["kind"] == "annulus":
        cx, cy, _ = first["centre"]
        r = (first["radius"] + first["radius_end"]) / 2
        theta = math.degrees(math.atan2(top[1] - cy, top[0] - cx)) % 360
        arc = first.get("arc_deg")
        if not arc:
            return math.pi * r
        a0, a1 = arc
        span = (a1 - a0) % 360 or 360.0
        into = (theta - a0) % 360
        if into > span + 1e-6:  # the ladder at an end, just outside the sector
            return math.radians(span) * r
        return math.radians(max(into, span - into)) * r
    xs, ys = [], []
    for part in gratings:
        if part["kind"] != "box":
            continue
        cx, cy, _ = part["centre"]
        dx, dy, _ = part["size"]
        if (part.get("rotation_deg") or 0.0) % 180 > 1e-6:
            dx, dy = dy, dx
        xs += [cx - dx / 2, cx + dx / 2]
        ys += [cy - dy / 2, cy + dy / 2]
    if not xs:
        return None
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def _tray_runs(tray: dict[str, Any]) -> list[Capsule]:
    r = max(tray["width"], tray.get("depth", 0.0)) / 2
    points = [tuple(p) for p in tray["points"]]
    return [
        Capsule(tray["id"], a, b, r)  # type: ignore[arg-type]
        for a, b in zip(points, points[1:], strict=False)
        if math.dist(a, b) > 1e-9
    ]


def _duct_runs(duct: dict[str, Any]) -> list[Capsule]:
    r = max(duct.get("width", 0.0), duct.get("height", 0.0)) / 2
    points = [tuple(p) for p in duct["points"]]
    return [
        Capsule(duct["id"], a, b, r)  # type: ignore[arg-type]
        for a, b in zip(points, points[1:], strict=False)
        if math.dist(a, b) > 1e-9
    ]


def _overlap_depth(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """How far two convex polygons overlap: the least overlap of their projections on the
    edge normals (0 when they are apart or only touch)."""
    least = math.inf
    for polygon in (a, b):
        for i, (x0, y0) in enumerate(polygon):
            x1, y1 = polygon[(i + 1) % len(polygon)]
            ax, ay = -(y1 - y0), x1 - x0
            norm = math.hypot(ax, ay)
            if norm < 1e-12:
                continue
            ax, ay = ax / norm, ay / norm
            pa = [x * ax + y * ay for x, y in a]
            pb = [x * ax + y * ay for x, y in b]
            least = min(least, min(max(pa), max(pb)) - max(min(pa), min(pb)))
            if least <= 0:
                return 0.0
    return 0.0 if least is math.inf else least


def _frame_point(p: Any, structure: dict[str, Any]) -> tuple[float, float]:
    """A site point in a structure's own frame (u, v)."""
    ox, oy = structure["origin"]
    a = math.radians(structure.get("rotation_deg") or 0.0)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    dx, dy = p[0] - ox, p[1] - oy
    return (dx * c + dy * s, -dx * s + dy * c)


def _wall_distance(p: Any, structure: dict[str, Any]) -> float:
    """How far in from the nearest side of its frame a point inside it is, m."""
    u, v = _frame_point(p, structure)
    return max(0.0, min(u, structure["width"] - u, v, structure["depth"] - v))


def _hatch_geometry(
    p: Any, structure: dict[str, Any], opening: dict[str, Any]
) -> tuple[float, tuple[float, float, float]]:
    """The distance from *p* to a declared opening of a structure's enclosure (a rectangle in
    the plane of its side) and the point just outside it facing *p*."""
    from chemeascode.domains.spatial.structures import Frame, _side_line

    width, depth = structure["width"], structure["depth"]
    left, right, normal = _side_line(opening["side"], width, depth)
    length = math.dist(left[:2], right[:2]) or 1.0
    ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
    u, v = _frame_point(p, structure)
    along = (u - left[0]) * ux + (v - left[1]) * uy
    inward = -((u - left[0]) * normal[0] + (v - left[1]) * normal[1])
    s0, s1 = opening["offset"], opening["offset"] + opening["width"]
    z0, z1 = opening.get("sill", 0.0), opening.get("sill", 0.0) + opening["height"]
    ds = max(s0 - along, 0.0, along - s1)
    dz = max(z0 - p[2], 0.0, p[2] - z1)
    distance = math.sqrt(ds * ds + dz * dz + max(inward, 0.0) ** 2)
    s = min(max(along, s0), s1)
    z = min(max(p[2], z0), z1)
    f = Frame(tuple(structure["origin"]), structure.get("rotation_deg") or 0.0)
    out = 0.3  # just outside the wall
    face = f.site(left[0] + ux * s + normal[0] * out, left[1] + uy * s + normal[1] * out, z)
    return distance, face


def _hatch_distance(p: Any, structure: dict[str, Any], opening: dict[str, Any]) -> float:
    return _hatch_geometry(p, structure, opening)[0]


def _hatch_face(p: Any, structure: dict[str, Any], opening: dict[str, Any]) -> tuple:
    return _hatch_geometry(p, structure, opening)[1]
