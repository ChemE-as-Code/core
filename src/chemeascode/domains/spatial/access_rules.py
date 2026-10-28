"""Access rules on the generated 3D model: headroom over the walking surfaces above grade, pipes
clear of ladders and of the walkway of ring platforms, the operator's standing space in front
of valves, transmitters and hatches, the clear width beside a stair's next flight, ladder heads
and stair heads in vent zones, and the operators declared for valves and transmitters out of
reach.

They run with the engineering rules (:mod:`chemeascode.domains.spatial.engineering_rules`), on
the same state (its walking levels, criteria, pipe capsules, steel index and ``add``). Rules
(``cheme.layout-...``, level):

- ``headroom`` (warning): a pipe lower than ``access_headroom_m`` (2.1 m, ASSUMED) over a
  structure floor, an item platform, a stair tread or landing, or an item's stair, landing and
  roof platform (:mod:`chemeascode.domains.spatial.floors`): its top above the walking surface
  and its bottom less than the headroom above it, over the surface in plan. A vertical run
  counts on stairs and landings only (a riser through a grating passes a cut-out); the first
  and last run at the item a pipe connects to are left out (the nozzle's own run over its
  platform), and so is a crossing with a proposed step-over (it is reviewed as such). Key
  ``<pipe>+<walking surface>`` (a stair or platform as a whole);
- ``operability`` (warning): besides the reach (engineering rules), the operator needs a free
  square of ``standing_space_m`` (0.6 m, ASSUMED), ``access_headroom_m`` high, on a floor
  within reach of the handwheel, lever, transmitter head or casing hatch: stair parts, ladders,
  steel members and items in it block it. A stair flight is no operating position (its
  landings are);
- ``landing-width`` (warning): where one stair arrives at a floor and the next leaves from it
  (stacked stairs), the free width of the walk between the two landings, beside the next
  stair's flights below the headroom, is less than the narrower stair's width;
- ``egress-zone`` (warning): a ladder's head (the top of a structure's, a platform's or a
  rack's ladder, up to the headroom above it) or a stair's top landing inside a zone volume of
  kind ``oxygen_deficient``, ``oxygen_enriched`` or ``hazardous``: the way off a roof or
  platform starts in the zone;
- ``ladder-clearance`` (warning): a pipe less than ``ladder_clearance_m`` (0.2 m, ASSUMED) from
  a ladder's rails (from grade to the top of its handhold extension), or through its cage: the
  climb, the toe space behind the rungs or the step-off at its head is blocked; a structure's,
  a rack's, an item platform's and an item's own ladder. Key ``<pipe>+<ladder>``;
- ``access-unconnected`` (warning): an item platform's ladder whose foot stands on no walking
  level (not on the platform below, a floor or grade within
  :data:`~chemeascode.domains.spatial.structures.CONNECT` in plan, nor where the item stands),
  or whose top is farther than ``LADDER_REACH`` in plan from its platform: it does not reach
  the platform it is drawn for (as the rule of the same id on structure stairs and ladders);
- ``walkway-riser`` (warning): a vertical run rising through an item's ring platform (its
  sector in plan) that cuts its outer edge (the handrail), or leaves less than
  ``walkway_clear_m`` (0.6 m, ASSUMED) of the walkway on its wider side; not the run at the
  nozzle of the item the pipe connects to. Key ``<pipe>+<platform>``;
- declared operators (``operators:`` of ``piping/routing.yaml``, copied onto the model's
  in-line items and nozzles as ``operator``): a ``chainwheel`` on a handwheel valve declared
  ``use: infrequent`` whose handwheel is at most ``chainwheel_max_height_m`` above a floor
  within reach; an ``extension_spindle`` or ``remote_operator`` whose length (declared, else
  from the handwheel to a pedestal 1 m above the nearest floor) is at most
  ``extension_max_m``; a transmitter's ``remote_mount`` on ``impulse`` lines or a
  ``capillary`` whose run (declared, else to a stand 1.2 m above the nearest floor) is at most
  ``impulse_max_m`` or ``capillary_max_m``. An accepted operator answers the reach finding; one
  that does not fit is an ``operability`` finding saying why. Every value is ASSUMED
  (``domains/spatial/data/layout-criteria.yaml``) until the site's standard replaces it.
"""

from __future__ import annotations

import math
import re
from typing import Any

from chemeascode.domains.spatial.geometry3d import (
    TOUCH,
    Box,
    Capsule,
    Index,
    segment_distance,
    segment_segment,
)

#: Kinds of walking level the access headroom applies to.
HEADROOM_KINDS = ("structure", "platform", "stair", "landing", "item")
#: Kinds a vertical pipe run may not pass through.
STAIR_KINDS = ("stair", "landing")
#: Zone kinds a way off a roof or platform may not start in.
EGRESS_ZONES = ("oxygen_deficient", "oxygen_enriched", "hazardous")
#: A pipe's top must stand this far above a surface to count as over it (a pipe lying in or
#: under a grating does not), m.
ABOVE = 0.05
#: Height of a remote operator's pedestal handwheel above its floor, m (ASSUMED).
PEDESTAL_M = 1.0
#: Height of a remote-mounted transmitter on its stand above its floor, m (as the model's
#: transmitter stands).
STAND_M = 1.2
#: A standing square keeps this far in from a floor's edge (its handrail), m.
EDGE = 0.1
#: Sample step along a pipe for the headroom rule, m.
STEP = 0.25


def walk_owner(floor_id: str) -> str:
    """The walking surface a walking level belongs to: a structure's stair (``S/ST1``) for its
    treads and landings, an item's stair (``T-1/stair``) for its treads and landing, else the
    level itself."""
    parts = floor_id.split("/")
    kept = []
    for part in parts:
        if part.startswith(("flight-", "tread-", "landing")):
            break
        kept.append(part)
    if len(kept) == len(parts) and parts[-1].startswith(("stair-tread", "stair-landing")):
        return "/".join([*parts[:-1], "stair"])
    return "/".join(kept)


def _floor_rect(floor: Any) -> tuple[float, float, float, float] | None:
    shape = floor.shape
    if shape[0] == "rect":
        return tuple(shape[1:])  # type: ignore[return-value]
    if shape[0] == "ring":
        _, cx, cy, _, r1, _, _ = shape
        return (cx - r1, cy - r1, cx + r1, cy + r1)
    return None


def _box(*boxes: tuple[float, ...]) -> list[float]:
    return [
        round(min(b[0] for b in boxes), 3),
        round(min(b[1] for b in boxes), 3),
        round(min(b[2] for b in boxes), 3),
        round(max(b[3] for b in boxes), 3),
        round(max(b[4] for b in boxes), 3),
        round(max(b[5] for b in boxes), 3),
    ]


def _shown(names: list[str], n: int = 4) -> str:
    return ", ".join(names[:n]) + (f" and {len(names) - n} more" if len(names) > n else "")


def _stair_of(part_id: str) -> str | None:
    """The stair a part belongs to (``S/ST1`` of ``S/ST1/flight-0/tread-3``), None for others."""
    parts = part_id.split("/")
    for k, part in enumerate(parts):
        if part.startswith(("flight-", "landing")):
            return "/".join(parts[:k])
    return None


class AccessRules:
    """The rules above on the state of an :class:`EngineeringRules` run."""

    def __init__(self, eng: Any) -> None:
        self.eng = eng
        self.base = eng.base
        self.model = eng.model
        self.add = eng.add
        self.criteria = eng.criteria
        self.floors = eng.floors
        self._obstacles: Index | None = None

    # -- headroom over the walking surfaces ------------------------------------------------

    def headroom(self) -> None:
        need = self.criteria.access_headroom_m
        floors = [
            f for f in self.floors if f.kind in HEADROOM_KINDS and not f.id.startswith("step-over-")
        ]
        index = Index(4.0)
        for floor in floors:
            rect = _floor_rect(floor)
            if rect is None:
                continue
            x0, y0, x1, y1 = rect
            index.add(
                Box(
                    floor.id,
                    ((x0 + x1) / 2, (y0 + y1) / 2, floor.z + need / 2),
                    (x1 - x0, y1 - y0, need),
                ),
                floor,
            )
        stepped = {(s["pipe"], s["walkway"]) for s in self.model.get("step_overs") or []}
        worst: dict[tuple[str, str], tuple[float, Any, dict[str, Any], list[float]]] = {}
        for capsule, pipe, k in self.base.capsules:
            ends = self.base.ends.get(pipe["id"], {})
            count = len(pipe["points"]) - 1
            if (k == 0 and 0 in ends) or (k == count - 1 and 1 in ends):
                continue  # the run at the nozzle of the item it connects to
            a, b = capsule.a, capsule.b
            r = capsule.r
            vertical = math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-6
            for _, _, floor in index.near(capsule.aabb, 0.0):
                if vertical and floor.kind not in STAIR_KINDS:
                    continue
                owner = walk_owner(floor.id)
                if (pipe["id"], owner) in stepped:
                    continue
                n = max(1, math.ceil(math.dist(a, b) / STEP))
                for i in range(n + 1):
                    p = tuple(a[j] + (b[j] - a[j]) * i / n for j in range(3))
                    if p[2] + r <= floor.z + ABOVE or p[2] - r >= floor.z + need - TOUCH:
                        continue
                    if floor.distance(p[0], p[1]) >= r - TOUCH:
                        continue
                    clear = p[2] - r - floor.z
                    key = (pipe["id"], owner)
                    if key not in worst or clear < worst[key][0]:
                        worst[key] = (clear, floor, pipe, list(capsule.aabb))
        for (pid, owner), (clear, floor, pipe, box) in sorted(worst.items()):
            where = (
                "through"
                if clear < 0
                else f"{max(clear, 0.0):.2f} m above"  # bottom above the surface
            )
            what = {
                "stair": "the stair",
                "landing": "the stair landing",
                "structure": "the floor",
                "platform": "the platform",
                "item": "the walking surface",
            }[floor.kind]
            self.add(
                "warning",
                "headroom",
                f"pipe {pid} ({pipe['line']}) runs {where} {what} {owner} at "
                f"{floor.z:.2f} m, lower than the {need:g} m headroom over it",
                [pid, owner],
                _box(tuple(box), (*box[:2], floor.z, *box[3:5], floor.z + need)),
                "route it clear of the walking surface: at least the headroom above it, or under "
                "its steel (via points, elevation or a pinned route in piping/routing.yaml); "
                "or move the stair or platform",
                key=f"{pid}+{owner}",
            )

    # -- the operator's standing space -----------------------------------------------------

    def obstacles(self) -> Index:
        """Stair parts, ladders, steel members and items: what blocks a standing space."""
        if self._obstacles is not None:
            return self._obstacles
        from chemeascode.domains.spatial.geometry3d import part_solid

        index = Index(4.0)

        def parts_of(parts: list[dict[str, Any]], owner: str) -> None:
            for part in parts:
                if _floor_grating(part):
                    continue  # a landing or platform grating is a floor
                solid = part_solid(part, part["id"])
                if solid is not None:
                    index.add(solid, part["id"])

        for structure in self.model.get("structures", []):
            for part in structure.get("parts", []):
                if part.get("kind") == "member":
                    solid = part_solid(part, part["id"])
                    if solid is not None:
                        index.add(solid, part["id"])
            for way in [*structure.get("stairs", []), *structure.get("ladders", [])]:
                parts_of(way.get("parts", []), way["id"])
        for platform in self.model.get("platforms", []):
            ladder = platform.get("ladder") or {}
            parts_of(ladder.get("parts", []), platform["id"])
        for rack in self.model.get("racks", []):
            for part in rack.get("parts", []):
                solid = part_solid(part, part["id"])
                if solid is not None:
                    index.add(solid, part["id"])
            for ladder in rack.get("ladders") or []:
                parts_of(ladder.get("parts", []), ladder["id"])
        for item in self.model.get("equipment", []):
            for part in item.get("parts", []):
                if _floor_grating(part):
                    continue
                solid = part_solid(part, part["id"])
                if solid is not None:
                    index.add(solid, part["id"])
        self._obstacles = index
        return index

    def _candidates(self, p: Any, floor: Any) -> list[tuple[float, float]]:
        """Centres of standing squares on *floor* near *p*: around it and clamped into the
        floor (shrunk by half the square)."""
        h = self.criteria.standing_space_m / 2
        reach = self.criteria.operator_reach_m
        inset = h + EDGE  # clear of the handrail along the floor's edge
        around = [(p[0], p[1])]
        for k in range(8):
            a = math.pi * k / 4
            for d in (h + 0.1, h + reach):
                around.append((p[0] + d * math.cos(a), p[1] + d * math.sin(a)))
        found = []
        shape = floor.shape
        for x, y in around:
            if shape[0] == "rect":
                x0, y0, x1, y1 = shape[1:]
                cx = (x0 + x1) / 2 if x1 - x0 < 2 * inset else min(max(x, x0 + inset), x1 - inset)
                cy = (y0 + y1) / 2 if y1 - y0 < 2 * inset else min(max(y, y0 + inset), y1 - inset)
            elif shape[0] == "ring":
                _, ox, oy, r0, r1, a0, a1 = shape
                d = math.hypot(x - ox, y - oy)
                angle = math.degrees(math.atan2(y - oy, x - ox)) % 360
                span = (a1 - a0) % 360
                if span > 1e-9 and (angle - a0) % 360 > span:
                    to0 = min((angle - a0) % 360, (a0 - angle) % 360)
                    to1 = min((angle - a1) % 360, (a1 - angle) % 360)
                    angle = a0 if to0 <= to1 else a1
                rr = (r0 + r1) / 2 if r1 - r0 < 2 * inset else min(max(d, r0 + inset), r1 - inset)
                cx = ox + rr * math.cos(math.radians(angle))
                cy = oy + rr * math.sin(math.radians(angle))
            else:
                cx, cy = x, y
            if floor.distance(cx, cy) > 1e-6:
                continue  # in a hole (a casing's footprint at grade)
            dx = max(abs(p[0] - cx) - h, 0.0)
            dy = max(abs(p[1] - cy) - h, 0.0)
            if math.hypot(dx, dy) > reach + EDGE + 1e-6:
                continue
            c = (round(cx, 4), round(cy, 4))
            if c not in found:
                found.append(c)
        return found

    def standing(self, p: Any, floors: list[Any]) -> tuple[bool, list[str]]:
        """Whether a free standing square on one of *floors* (each within reach of *p*) lets an
        operator work at *p*; else what blocks them."""
        from chemeascode.domains.spatial.model_rules import _solids_meet

        side = self.criteria.standing_space_m
        height = self.criteria.access_headroom_m
        index = self.obstacles()
        blockers: set[str] = set()
        for floor in floors:
            own = _stair_of(floor.id)
            for cx, cy in self._candidates(p, floor):
                space = Box("stand", (cx, cy, floor.z + ABOVE + height / 2), (side, side, height))
                hit = set()
                for solid, _, pid in index.near(space.aabb, 0.0):
                    if own is not None and _stair_of(pid) == own:
                        continue  # the landing's own stair
                    if isinstance(solid, Capsule):
                        if segment_distance(solid.a, solid.b, space) < solid.r - TOUCH:
                            hit.add(pid)
                    elif _solids_meet(solid, space):
                        hit.add(pid)
                if not hit:
                    return True, []
                blockers |= hit
        named = sorted({_stair_of(b) or b.rsplit("/", 1)[0] for b in blockers})
        return False, named

    def operating_floors(self, p: Any, height: float) -> tuple[list[Any], bool]:
        """The floors an operator may work at *p* from (within reach, at most *height* below
        it; no stair flight), and whether a stair flight alone would reach it."""
        reach = self.criteria.operator_reach_m
        found, stair = [], False
        for floor in self.floors:
            rise = p[2] - floor.z
            if -0.05 <= rise <= height + 1e-6 and floor.distance(p[0], p[1]) <= reach + 1e-6:
                if floor.kind == "stair":
                    stair = True
                else:
                    found.append(floor)
        return found, stair

    # -- declared operators ----------------------------------------------------------------

    def nearest_floor(self, p: Any, lift: float) -> tuple[float, Any]:
        """The shortest orthogonal run from *p* to a point *lift* above a floor (no stair
        flight) within reach of it, and that floor."""
        reach = self.criteria.operator_reach_m
        best: tuple[float, Any] = (math.inf, None)
        for floor in self.floors:
            if floor.kind == "stair" or floor.z > p[2] + 0.05:
                continue
            d = max(floor.distance(p[0], p[1]) - reach, 0.0)
            run = d + abs(p[2] - (floor.z + lift))
            if run < best[0] - 1e-9:
                best = (run, floor)
        return best

    def operator(
        self, kind: str, op: dict[str, Any], point: Any, names: dict[str, Any]
    ) -> str | None:
        """None when the declared operator *op* makes the item at *point* operable, else why
        not. *kind* is ``valve`` or ``instrument``."""
        c = self.criteria
        how = op.get("kind")
        if kind == "valve" and how == "chainwheel":
            if "handwheel" not in names:
                return "a chain wheel needs a handwheel (a gear operator), not a lever"
            if op.get("use") != "infrequent":
                return "a chain wheel is for a valve declared use: infrequent"
            below = [
                floor.z
                for floor in self.floors
                if floor.kind != "stair"
                and floor.z <= point[2] + 0.05
                and floor.distance(point[0], point[1]) <= c.operator_reach_m + 1e-6
            ]
            if not below:
                return "no floor under the chain wheel within reach"
            rise = point[2] - max(below)
            if rise > c.chainwheel_max_height_m + 1e-6:
                # rounded up to the centimetre, so a rise just over the limit never reads as
                # the limit itself
                shown = math.ceil(rise * 100 - 1e-6) / 100
                return (
                    f"its chain wheel is {shown:.2f} m above the floor (more than "
                    f"{c.chainwheel_max_height_m:g} m)"
                )
            return None
        if kind == "valve" and how in ("extension_spindle", "remote_operator"):
            needed, floor = self.nearest_floor(point, PEDESTAL_M)
            length = op.get("length_m") or needed
            if floor is None:
                return "no floor to bring the operator to"
            if length > c.extension_max_m + 1e-6:
                return (
                    f"the {how.replace('_', ' ')} would be {length:.1f} m long to {floor.id} "
                    f"(more than {c.extension_max_m:g} m)"
                )
            return None
        if kind == "instrument" and how == "remote_mount":
            needed, floor = self.nearest_floor(point, STAND_M)
            via = op.get("via") or "impulse"
            limit = c.capillary_max_m if via == "capillary" else c.impulse_max_m
            length = op.get("length_m") or needed
            if floor is None:
                return "no floor to mount the transmitter at"
            if length > limit + 1e-6:
                return (
                    f"the {via} run would be {length:.1f} m to a stand on {floor.id} (more "
                    f"than {limit:g} m)"
                )
            return None
        return f"a {how} does not operate a {kind}"

    # -- landing width ---------------------------------------------------------------------

    def landing_width(self) -> None:
        from chemeascode.domains.spatial.structures import part_rect, stair_landings

        need_h = self.criteria.access_headroom_m
        for structure in self.model.get("structures", []):
            stairs = [s for s in structure.get("stairs", []) if s.get("source") != "generated"]
            if len(stairs) < 2:
                continue
            levels = {lv["id"]: lv for lv in structure.get("levels", [])}
            gratings = {}
            for part in structure.get("parts", []):
                name = part["id"].split("/")
                if part["kind"] == "box" and part.get("material") == "grating" and len(name) == 3:
                    gratings.setdefault(name[1], []).append(part_rect(part))
            for a in stairs:
                for b in stairs:
                    if a is b or a.get("to") != b.get("from") or a.get("to") in (None, "grade"):
                        continue
                    level = levels.get(a["to"])
                    found_a, found_b = stair_landings(a), stair_landings(b)
                    if level is None or found_a is None or found_b is None:
                        continue
                    head, foot = found_a[1], found_b[0]
                    z = level["elevation"]
                    self._walk(structure, a, b, head, foot, z, gratings, need_h)

    def _walk(
        self,
        structure: dict[str, Any],
        a: dict[str, Any],
        b: dict[str, Any],
        head: tuple[float, ...],
        foot: tuple[float, ...],
        z: float,
        gratings: dict[str, list[tuple[float, ...]]],
        need_h: float,
    ) -> None:
        """The walk on the floor at *z* from stair *a*'s top landing *head* to stair *b*'s foot
        landing *foot* (see the module text)."""
        width = min(a.get("width") or 0.0, b.get("width") or 0.0)
        hx = (head[0] + head[2]) / 2 - (foot[0] + foot[2]) / 2
        hy = (head[1] + head[3]) / 2 - (foot[1] + foot[3]) / 2
        axis = 0 if abs(hx) >= abs(hy) else 1  # along x or y
        lo = min(head[2 + axis], foot[2 + axis])
        hi = max(head[axis], foot[axis])
        if hi - lo <= 1e-6:
            return  # the landings meet: nothing to walk beside
        across = 1 - axis
        at_z = {lv["id"] for lv in structure.get("levels", []) if abs(lv["elevation"] - z) < 1e-6}
        rects = [
            r
            for lid, rs in gratings.items()
            if lid in at_z
            for r in rs
            if r[axis] <= lo + 1e-6 and r[2 + axis] >= hi - 1e-6
        ]
        if not rects:
            return
        c0 = min(r[across] for r in rects)
        c1 = max(r[2 + across] for r in rects)
        blocked: list[tuple[float, float]] = []
        for way in (a, b):
            for part in way.get("parts", []):
                if part.get("lod") == 2:
                    continue
                pb = _part_box(part)
                if pb is None:
                    continue
                if pb[5] <= z + ABOVE or pb[2] >= z + need_h:
                    continue  # under the floor or above the headroom
                if pb[3 + axis] <= lo + 1e-6 or pb[axis] >= hi - 1e-6:
                    continue
                blocked.append((pb[across], pb[3 + across]))
        free = _free(c0, c1, blocked)
        if free >= width - 0.01:
            return
        sid = structure["id"]
        box = [lo, c0, z, hi, c1, z + need_h] if axis == 0 else [c0, lo, z, c1, hi, z + need_h]
        self.add(
            "warning",
            "landing-width",
            f"from {a['id']} to {b['id']} at {z:g} m the walk beside the next flight is "
            f"{free:.2f} m clear, less than the stair width {width:g} m",
            [a["id"], b["id"], sid],
            [round(v, 3) for v in box],
            "widen the floor beside the stair (the level's extent in layout/structures.yaml), "
            "or turn the stacked stairs so each arrives where the next one starts",
            key=f"{a['id']}+{b['id']}",
        )

    # -- ways off a roof or platform in a zone ---------------------------------------------

    def egress_zones(self) -> None:
        from chemeascode.domains.spatial.zones import volume_solid

        need = self.criteria.access_headroom_m
        zones = [
            (zone, [volume_solid(v, zone["id"]) for v in zone.get("volumes", [])])
            for zone in self.model.get("zones", [])
            if zone.get("kind") in EGRESS_ZONES
        ]
        if not zones:
            return
        heads: list[tuple[str, str, tuple[float, float, float], tuple[float, float, float]]] = []
        for structure in self.model.get("structures", []):
            for ladder in structure.get("ladders", []):
                top = tuple(ladder["top"])
                heads.append((ladder["id"], "ladder head", top, (top[0], top[1], top[2] + need)))
            for stair in structure.get("stairs", []):
                landing = max(
                    (p for p in stair.get("parts", []) if "/landing-" in p["id"]),
                    key=lambda p: p["centre"][2],
                    default=None,
                )
                if landing is None:
                    continue
                c = landing["centre"]
                top = (c[0], c[1], c[2])
                heads.append((stair["id"], "stair head", top, (c[0], c[1], c[2] + need)))
        for platform in self.model.get("platforms", []):
            ladder = platform.get("ladder")
            if ladder and ladder.get("top"):
                top = tuple(ladder["top"])
                heads.append((platform["id"], "ladder head", top, (top[0], top[1], top[2] + need)))
        for rack in self.model.get("racks", []):
            for ladder in rack.get("ladders") or []:
                if ladder.get("top"):
                    top = tuple(ladder["top"])
                    heads.append((ladder["id"], "ladder head", top, (*top[:2], top[2] + need)))
        for way, what, a, b in heads:
            for zone, solids in zones:
                if any(segment_distance(a, b, solid) < 1e-6 for solid in solids):
                    kind = zone["kind"].replace("_", "-")
                    self.add(
                        "warning",
                        "egress-zone",
                        f"the {what} of {way} at [{a[0]:.1f}, {a[1]:.1f}, {a[2]:.1f}] is inside "
                        f"the {kind} zone {zone['id']}: the way off starts in the zone",
                        [way, zone["id"]],
                        _box((*a, *b)),
                        "move the vent or breather away from the way off (or raise it), or "
                        "move the ladder or stair to the other end of the roof or platform",
                        key=f"{way}+{zone['id']}",
                    )

    def unknown_operators(self) -> None:
        from chemeascode.domains.spatial.piping_detail import operator_targets

        routing = self.base.routing
        for op in getattr(routing, "operators", None) or ():
            if operator_targets(self.model, op.item):
                continue
            self.add(
                "warning",
                "operator-unknown",
                f"the {op.kind.replace('_', ' ')} declared for {op.item} names no valve, "
                "in-line instrument or nozzle of the model",
                [op.item],
                None,
                "name the valve's or instrument's tag, its in-line id (<sheet>/<DEXPI id>) or "
                "TAG/NOZZLE in piping/routing.yaml operators:",
                key=f"operator:{op.item}",
            )

    # -- ladders and risers through ring platforms ---------------------------------------

    def ladder_clearance(self) -> None:
        need = self.criteria.ladder_clearance_m
        index = Index(4.0)
        for ladder, part in _ladder_parts(self.model):
            cage = part.get("material") == "cage"
            r = part.get("radius")
            if r is None:
                r = max(part.get("profile") or (0.07,)) / 2
            solid = Capsule(part["id"], tuple(part["start"]), tuple(part["end"]), float(r))
            index.add(solid, (ladder, cage))
        worst: dict[tuple[str, str], tuple[float, bool, dict[str, Any], list[float]]] = {}
        for capsule, pipe, _ in self.base.capsules:
            for solid, _, (ladder, cage) in index.near(capsule.aabb, need):
                gap = segment_segment(capsule.a, capsule.b, solid.a, solid.b) - capsule.r - solid.r
                if (cage and gap >= -TOUCH) or (not cage and gap >= need - TOUCH):
                    continue
                key = (pipe["id"], ladder)
                score = gap - (10.0 if cage else 0.0)  # through a cage first
                if key not in worst or score < worst[key][0] - (10.0 if worst[key][1] else 0.0):
                    worst[key] = (gap, cage, pipe, list(capsule.aabb))
        for (pid, ladder), (gap, cage, pipe, box) in sorted(worst.items()):
            where = (
                "through its cage"
                if cage
                else f"{max(gap, 0.0):.2f} m from its rails (less than {need:g} m)"
                if gap > 0
                else "through its rails"
            )
            self.add(
                "warning",
                "ladder-clearance",
                f"pipe {pid} ({pipe['line']}) runs {where} at ladder {ladder}: the climb, the "
                "toe space behind the rungs or the step-off at its head is blocked",
                [pid, ladder],
                _box(tuple(box)),
                f"route the pipe at least {need:g} m clear of the ladder's rails and outside its "
                "cage (via points or a pinned route in piping/routing.yaml), or move the ladder",
                key=f"{pid}+{ladder}",
                measured=None if cage or gap <= 0 else gap,
            )

    def walkway_risers(self) -> None:
        need = self.criteria.walkway_clear_m
        rings = [f for f in self.floors if f.shape and f.shape[0] == "ring"]
        if not rings:
            return
        worst: dict[tuple[str, str], tuple[float, bool, Any, dict[str, Any], list[float]]] = {}
        for capsule, pipe, k in self.base.capsules:
            ends = self.base.ends.get(pipe["id"], {})
            count = len(pipe["points"]) - 1
            if (k == 0 and 0 in ends) or (k == count - 1 and 1 in ends):
                continue  # the run at the nozzle of the item it connects to
            a, b, r = capsule.a, capsule.b, capsule.r
            if math.hypot(b[0] - a[0], b[1] - a[1]) > 1e-6:
                continue
            lo, hi = sorted((a[2], b[2]))
            for floor in rings:
                if not lo < floor.z + ABOVE < hi:
                    continue  # it does not rise through the surface
                if floor.distance(a[0], a[1]) >= r - TOUCH:
                    continue
                _, cx, cy, r0, r1, _, _ = floor.shape
                at = math.hypot(a[0] - cx, a[1] - cy)
                inner, outer = at - r - r0, r1 - (at + r)
                cuts = outer < -TOUCH and at - r < r1
                clear = max(inner, outer)
                if clear >= need - TOUCH and not cuts:
                    continue
                key = (pipe["id"], walk_owner(floor.id))
                if key not in worst or clear < worst[key][0]:
                    worst[key] = (clear, cuts, floor, pipe, list(capsule.aabb))
        for (pid, owner), (clear, cuts, floor, pipe, box) in sorted(worst.items()):
            why = (
                "through its handrail"
                if cuts
                else f"leaving {max(clear, 0.0):.2f} m of walkway beside it (less than {need:g} m)"
            )
            self.add(
                "warning",
                "walkway-riser",
                f"pipe {pid} ({pipe['line']}) rises through the platform {owner} at "
                f"{floor.z:.2f} m, {why}",
                [pid, owner],
                _box(tuple(box)),
                "run the riser outside the platform's handrail or in the gap of its arc, or move "
                "the nozzle to the end of the arc (piping/routing.yaml, the placement's nozzles)",
                key=f"{pid}+{owner}",
            )

    def platform_ladders(self) -> None:
        from chemeascode.domains.spatial.structures import CONNECT, LADDER_REACH

        stands = {
            e["tag"]: (e.get("position") or (0.0, 0.0, 0.0))[2]
            for e in self.model.get("equipment", [])
        }
        for platform in self.model.get("platforms", []):
            ladder = platform.get("ladder")
            if not ladder:
                continue
            base, top = ladder["base"], ladder["top"]
            missing = []
            own = [f.distance(top[0], top[1]) for f in self.floors if f.id == platform["id"]]
            if own and min(own) > LADDER_REACH + 1e-6:
                missing.append(
                    f"its top is {min(own):.1f} m from the platform (more than {LADDER_REACH:g} "
                    "m in plan)"
                )
            on_floor = any(
                abs(f.z - base[2]) <= 0.05 and f.distance(base[0], base[1]) <= CONNECT + 1e-6
                for f in self.floors
            )
            if not on_floor and abs(base[2] - stands.get(platform["tag"], 0.0)) > 0.05:
                missing.append(f"its foot at {base[2]:.1f} m stands on no walking level")
            if not missing:
                continue
            self.add(
                "warning",
                "access-unconnected",
                f"the ladder of platform {platform['id']} does not reach it from a floor: "
                f"{'; '.join(missing)}",
                [ladder["id"], platform["id"]],
                _box(
                    (base[0] - 0.5, base[1] - 0.5, base[2], base[0] + 0.5, base[1] + 0.5, base[2]),
                    (top[0] - 0.5, top[1] - 0.5, top[2], top[0] + 0.5, top[1] + 0.5, top[2] + 1.1),
                ),
                "set ladder_side to an angle the platform below covers (the ladder then stands "
                "beside both platforms), or leave it out so the build places each ladder, or "
                "widen the arc of the platform below to the ladder (access in "
                "layout/equipment-placement.yaml)",
                key=ladder["id"],
            )

    def run(self) -> None:
        self.unknown_operators()
        self.platform_ladders()
        self.headroom()
        self.ladder_clearance()
        self.walkway_risers()
        self.landing_width()
        self.egress_zones()


def _ladder_parts(model: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Every ladder's rails and cage in the model, with the ladder's id, found by where the
    ladder is, not by its name: a structure's and a rack's ``ladders``, an item platform's
    ``ladder`` and an item's own (its parts ``<tag>/ladder-rail-<n>`` and ``<tag>/ladder-cage``,
    as ``<tag>/ladder``)."""
    found: list[tuple[str, dict[str, Any]]] = []

    def solids(ladder: dict[str, Any]) -> None:
        for part in ladder.get("parts") or []:
            if "start" in part and "end" in part and part.get("kind") in ("member", "cylinder"):
                found.append((ladder["id"], part))

    for owner in [*(model.get("structures") or []), *(model.get("racks") or [])]:
        for ladder in owner.get("ladders") or []:
            solids(ladder)
    for platform in model.get("platforms") or []:
        if platform.get("ladder"):
            solids(platform["ladder"])
    for item in model.get("equipment") or []:
        for part in item.get("parts") or []:
            owner, _, name = str(part.get("id") or "").rpartition("/")
            own = name == "ladder-cage" or re.fullmatch(r"ladder-rail-\d+", name) is not None
            if own and "start" in part and "end" in part:
                found.append((f"{owner}/ladder", part))
    return found


def _floor_grating(part: dict[str, Any]) -> bool:
    """A grating that is a floor (a landing, a platform, a deck), not a stair tread."""
    return (
        part.get("kind") == "box"
        and part.get("material") == "grating"
        and "tread" not in part["id"]
    )


def _part_box(part: dict[str, Any]) -> tuple[float, ...] | None:
    from chemeascode.domains.spatial.geometry3d import part_solid

    solid = part_solid(part)
    return None if solid is None else solid.aabb


def _free(c0: float, c1: float, blocked: list[tuple[float, float]]) -> float:
    """The widest free interval of ``[c0, c1]`` outside the *blocked* intervals."""
    edges = sorted((max(lo, c0), min(hi, c1)) for lo, hi in blocked if hi > c0 and lo < c1)
    best, at = 0.0, c0
    for lo, hi in edges:
        best = max(best, lo - at)
        at = max(at, hi)
    return max(best, c1 - at)
