"""Where people stand in the 3D model: the walking levels the rules on the model and the vent
risers of the router keep clear.

A walking level (:class:`Floor`) is a plan region at an elevation:

- ``grade`` at 0 m everywhere, except inside a structure closed by walls on every side that is
  no fire wall (a casing: :func:`casing_volumes`; a cold box casing is filled, nobody walks in
  it);
- each structure level's grating (``<structure>/<level>``), and the treads (kind ``stair``) and
  landings (kind ``landing``) of its stairs;
- each access platform of an item (``<tag>/platform-<n>``: its ring sector or its gratings);
- each grating of an item (a tank's spiral stair treads, kind ``stair``; its landing and roof
  platform, kind ``item``), of a step-over (its deck, kind ``step_over``; treads ``stair``)
  and of a rack (a walkway, kind ``rack``);
- each building level (floor, platform or roof) over the building's footprint.

A grating inside a casing volume (in its footprint and below the top of its walls) is no
walking level (a platform inside a perlite-filled cold box cannot be stood on): it is left out
when it lies wholly in the casing's footprint, else the footprint is a hole in it. A casing's
roof (at or above the top of its walls) is a walking level.

Pure geometry on the model document; the router calls it with the declared platforms only (the
proposals follow the routes), the rules on the finished model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

#: Iterations of :func:`clear_height` before it gives up raising the point.
RAISE_STEPS = 32


@dataclass(frozen=True)
class Floor:
    """A walking level: ``shape`` is ``("all",)``, ``("rect", x0, y0, x1, y1)`` or ``("ring",
    cx, cy, r0, r1, a0, a1)`` (a ring sector, degrees ccw from east; a0 = a1 = 0: all round),
    minus the ``holes`` (rectangles; grade under a closed casing)."""

    id: str
    kind: str  # grade, structure, platform, building, stair, landing, item, step_over, rack
    z: float
    shape: tuple
    holes: tuple = ()

    def distance(self, x: float, y: float) -> float:
        """Plan distance from ``(x, y)`` to the region (0 inside it)."""
        if any(_rect_distance(x, y, h) == 0.0 for h in self.holes):
            return min(_rect_edge_distance(x, y, h) for h in self.holes if _inside_rect(x, y, h))
        kind = self.shape[0]
        if kind == "all":
            return 0.0
        if kind == "rect":
            return _rect_distance(x, y, self.shape[1:])
        _, cx, cy, r0, r1, a0, a1 = self.shape
        return _ring_distance(x, y, cx, cy, r0, r1, a0, a1)

    def corners(self) -> list[tuple[float, float]]:
        """Points on the region's outline (its corners; a ring sector's ends and arc)."""
        kind = self.shape[0]
        if kind == "rect":
            x0, y0, x1, y1 = self.shape[1:]
            return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        if kind == "ring":
            _, cx, cy, r0, r1, a0, a1 = self.shape
            span = (a1 - a0) % 360 or 360.0
            found = []
            for k in range(13):
                a = math.radians(a0 + span * k / 12)
                found.append((cx + r1 * math.cos(a), cy + r1 * math.sin(a)))
            return found
        return []


def _inside_rect(x: float, y: float, r: tuple) -> bool:
    return r[0] <= x <= r[2] and r[1] <= y <= r[3]


def _rect_distance(x: float, y: float, r: tuple) -> float:
    dx = max(r[0] - x, 0.0, x - r[2])
    dy = max(r[1] - y, 0.0, y - r[3])
    return math.hypot(dx, dy)


def _rect_edge_distance(x: float, y: float, r: tuple) -> float:
    return min(x - r[0], r[2] - x, y - r[1], r[3] - y)


def _ring_distance(
    x: float, y: float, cx: float, cy: float, r0: float, r1: float, a0: float, a1: float
) -> float:
    d = math.hypot(x - cx, y - cy)
    angle = math.degrees(math.atan2(y - cy, x - cx)) % 360
    full = abs((a1 - a0) % 360) < 1e-9
    if full or (angle - a0) % 360 <= (a1 - a0) % 360 + 1e-9:
        return max(r0 - d, 0.0, d - r1)
    best = math.inf
    for a in (a0, a1):
        t = math.radians(a)
        p = (cx + r0 * math.cos(t), cy + r0 * math.sin(t))
        q = (cx + r1 * math.cos(t), cy + r1 * math.sin(t))
        best = min(best, _point_segment_2d((x, y), p, q))
    return best


def _point_segment_2d(p: tuple, a: tuple, b: tuple) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n < 1e-12 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def _box_rect(part: dict[str, Any]) -> tuple[float, float, float, float]:
    """The plan rectangle of a box part (its axis-aligned bounds when turned off 90 degrees)."""
    cx, cy, _ = part["centre"]
    dx, dy, _ = part["size"]
    a = math.radians(part.get("rotation_deg") or 0.0)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    c, s = (0.0 if c < 1e-9 else c), (0.0 if s < 1e-9 else s)
    hx, hy = (dx * c + dy * s) / 2, (dx * s + dy * c) / 2
    return (cx - hx, cy - hy, cx + hx, cy + hy)


#: How far into a casing's footprint (m) a rectangle may reach and still count as outside it.
CASING_EDGE = 0.05


def closed_casings(model: dict[str, Any]) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Footprints of the structures walled on every side by walls that are no fire walls."""
    found = []
    for structure in model.get("structures", []):
        walls = structure.get("walls") or []
        sides = set()
        for wall in walls:
            if wall.get("material") == "fire_wall":
                continue
            name = wall["id"].rsplit("/", 1)[-1]  # wall-<side> or wall-<side>-<k>
            parts = name.split("-")
            if len(parts) >= 2:
                sides.add(parts[1])
        if {"south", "east", "north", "west"} <= sides:
            found.append((structure["id"], tuple(structure["footprint"])))
    return found


def casing_volumes(
    model: dict[str, Any],
) -> list[tuple[str, tuple[float, float, float, float], float]]:
    """``(structure id, footprint, top)`` of each closed casing (:func:`closed_casings`):
    its frame's footprint and the top of its walls, m."""
    tops = {
        s["id"]: max((w["centre"][2] + w["size"][2] / 2 for w in s.get("walls") or []), default=0.0)
        for s in model.get("structures", [])
    }
    return [(sid, box, tops.get(sid, 0.0)) for sid, box in closed_casings(model)]


def in_casing(
    p: Any,
    volumes: list[tuple[str, tuple[float, float, float, float], float]],
    margin: float = 0.0,
) -> str | None:
    """The casing whose volume holds point *p* (in its footprint, shrunk by *margin*, and below
    the top of its walls), None outside every casing."""
    for sid, (x0, y0, x1, y1), top in volumes:
        if (
            x0 + margin < p[0] < x1 - margin
            and y0 + margin < p[1] < y1 - margin
            and p[2] < top - CASING_EDGE
        ):
            return sid
    return None


def rect_in_casing(
    rect: tuple[float, ...],
    z: float,
    volumes: list[tuple[str, tuple[float, float, float, float], float]],
) -> str | None:
    """The casing whose volume holds the plan rectangle *rect* at elevation *z* wholly."""
    for sid, (x0, y0, x1, y1), top in volumes:
        if z >= top - CASING_EDGE:
            continue
        e = CASING_EDGE
        if rect[0] >= x0 - e and rect[1] >= y0 - e and rect[2] <= x1 + e and rect[3] <= y1 + e:
            return sid
    return None


def _overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    e = CASING_EDGE
    return a[0] < b[2] - e and b[0] < a[2] - e and a[1] < b[3] - e and b[1] < a[3] - e


def _grating_kind(part_id: str, default: str) -> str:
    name = part_id.rsplit("/", 1)[-1]
    if "tread" in name:
        return "stair"
    if "landing" in name:
        return "landing" if default == "structure" else default
    return default


def walking_levels(model: dict[str, Any]) -> list[Floor]:
    """Every walking level of *model* (see the module text)."""
    volumes = casing_volumes(model)
    holes = tuple(box for _, box, _ in volumes)
    found = [Floor("grade", "grade", 0.0, ("all",), holes)]

    def add(fid: str, kind: str, z: float, rect: tuple[float, ...]) -> None:
        if rect_in_casing(rect, z, volumes) is not None:
            return  # inside a casing: nobody stands there
        cut = tuple(
            box for _, box, top in volumes if z < top - CASING_EDGE and _overlaps(rect, box)
        )
        found.append(Floor(fid, kind, z, ("rect", *rect), cut))

    for structure in model.get("structures", []):
        for part in structure.get("parts", []):
            if part.get("kind") == "box" and part.get("material") == "grating":
                top = part["centre"][2] + part["size"][2] / 2
                add(part["id"].rsplit("/", 1)[0], "structure", top, _box_rect(part))
        for stair in structure.get("stairs", []):
            for part in stair.get("parts", []):
                if part.get("kind") == "box" and part.get("material") == "grating":
                    top = part["centre"][2] + part["size"][2] / 2
                    add(part["id"], _grating_kind(part["id"], "structure"), top, _box_rect(part))
    for platform in model.get("platforms", []):
        for part in platform.get("parts", []):
            if part.get("material") != "grating":
                continue
            if part["kind"] == "annulus":
                cx, cy, cz = part["centre"]
                r = part["radius_end"]
                if rect_in_casing((cx - r, cy - r, cx + r, cy + r), cz, volumes) is not None:
                    continue
                a0, a1 = part.get("arc_deg") or (0.0, 0.0)
                shape = ("ring", cx, cy, part["radius"], part["radius_end"], a0, a1)
                found.append(Floor(platform["id"], "platform", cz, shape))
            elif part["kind"] == "box":
                top = part["centre"][2] + part["size"][2] / 2
                add(platform["id"], "platform", top, _box_rect(part))
    for key, kind in (("equipment", "item"), ("step_overs", "step_over"), ("racks", "rack")):
        for owner in model.get(key) or []:
            for part in owner.get("parts", []):
                if part.get("kind") != "box" or part.get("material") != "grating":
                    continue
                top = part["centre"][2] + part["size"][2] / 2
                add(part["id"], _grating_kind(part["id"], kind), top, _box_rect(part))
    for building in model.get("buildings", []):
        x0, y0, x1, y1 = building["footprint"]
        for level in building.get("levels", []):
            if level["elevation"] <= 1e-6:
                continue  # grade
            found.append(
                Floor(
                    f"{building['id']}/{level['id']}",
                    "building",
                    level["elevation"],
                    ("rect", x0, y0, x1, y1),
                )
            )
    return found


def sphere_hits(
    centre: tuple[float, float, float], radius: float, floors: list[Floor], headroom: float
) -> list[tuple[Floor, float]]:
    """The walking levels whose occupied space (the region up to *headroom* above it) a sphere
    reaches, each with the height the sphere's centre would need to clear it."""
    x, y, z = centre
    hits = []
    for floor in floors:
        d = floor.distance(x, y)
        if d >= radius - 1e-9:
            continue
        if floor.z <= z <= floor.z + headroom:
            dz = 0.0
        else:
            dz = min(abs(z - floor.z), abs(z - floor.z - headroom))
        if d * d + dz * dz < radius * radius - 1e-9:
            needed = floor.z + headroom + math.sqrt(radius * radius - d * d)
            hits.append((floor, needed))
    return hits


def clear_height(
    centre: tuple[float, float, float], radius: float, floors: list[Floor], headroom: float
) -> float:
    """The lowest elevation at or above *centre*'s at which a sphere of *radius* around the
    point clears every walking level's occupied space (:func:`sphere_hits`)."""
    z = centre[2]
    for _ in range(RAISE_STEPS):
        hits = sphere_hits((centre[0], centre[1], z), radius, floors, headroom)
        if not hits:
            return z
        z = max(needed for _, needed in hits) + 1e-6
    return z
