"""Pipes through walls: where a routed pipe passes a building's cladding or roof, or a
structure's enclosure wall (a cold box casing, a fire wall), outside the declared openings.

The walls in the model are already cut around the declared openings (``openings`` of a
building, ``enclosure.openings`` of a structure), so every pipe run that still meets a wall
panel passes it outside an opening. Each such crossing is a model ``penetration``
(``source: generated``, ``review_needed``) with the opening that would take it, in the owner's
own frame (``side``, ``offset`` from the side's left end seen from outside, ``width``,
``height``, ``sill`` above grade, ``kind: opening``): the pipe's outside diameter with its
insulation plus :data:`SLEEVE_GAP` all round, rounded up to :data:`ROUND`. ``cheme layout
pin <owner>/<line>`` declares it.

A building's roof slab is a panel too (the router lets a line with an end inside the building
pass it like the walls): a pipe whose axis meets the slab (not one that only grazes the eaves
with its outside diameter) is a penetration with ``side: roof`` and the opening in the owner's
plan frame (``offset`` and ``width`` along the owner's own x from its origin corner, ``sill``
and ``height`` along its own y; seen from above, north up, on an unrotated owner). A roof
opening cannot be declared: ``cheme layout pin`` refuses it, and the rule asks for a line with
an end inside to enter through a wall instead.

Pure geometry on the model document after routing; the rule ``layout-wall-penetration``
(:mod:`chemeascode.domains.spatial.model_rules`) reports the crossings.
"""

from __future__ import annotations

import math
from typing import Any

from chemeascode.domains.spatial.geometry3d import TOUCH, Box, segment_distance

Vec = tuple[float, float, float]
#: Clearance all round a pipe in a proposed wall opening (sleeve), m (ASSUMED).
SLEEVE_GAP = 0.05
#: Proposed openings are rounded outward to this, m.
ROUND = 0.05

_SIDE_LINE = {
    "south": lambda w, d: ((0.0, 0.0), (w, 0.0)),
    "east": lambda w, d: ((w, 0.0), (w, d)),
    "north": lambda w, d: ((w, d), (0.0, d)),
    "west": lambda w, d: ((0.0, d), (0.0, 0.0)),
}


def wall_panels(model: dict[str, Any]) -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    """``(owner, kind, panel)`` of every wall panel (and building roof slab): ``kind`` is
    ``structure`` or ``building``."""
    found = []
    for structure in model.get("structures", []):
        for wall in structure.get("walls") or []:
            if wall.get("kind") == "box" and wall.get("lod") != 2:
                found.append((structure, "structure", wall))
    for building in model.get("buildings", []):
        for part in building.get("parts") or []:
            name = part["id"].rsplit("/", 1)[-1]
            panel = name.startswith("wall-") or name == "roof"
            if part.get("kind") == "box" and panel and part.get("lod") != 2:
                found.append((building, "building", part))
    return found


def _side(panel: dict[str, Any]) -> str:
    name = panel["id"].rsplit("/", 1)[-1]
    return "roof" if name == "roof" else name.split("-")[1]


def _clip(a: Vec, b: Vec, box: Box, grow: float) -> tuple[float, float] | None:
    """The parameter range of segment *ab* inside *box* grown by *grow* (in its own frame)."""
    la, lb = box.local(a), box.local(b)
    t0, t1 = 0.0, 1.0
    for i in range(3):
        half = box.size[i] / 2 + grow
        d = lb[i] - la[i]
        if abs(d) < 1e-12:
            if abs(la[i]) > half:
                return None
            continue
        u0, u1 = (-half - la[i]) / d, (half - la[i]) / d
        if u0 > u1:
            u0, u1 = u1, u0
        t0, t1 = max(t0, u0), min(t1, u1)
        if t1 < t0 - 1e-12:
            return None
    return t0, t1


def _owner_frame(owner: dict[str, Any], p: Vec) -> tuple[float, float]:
    """*p* in the owner's own frame (``u`` along its x, ``v`` along its y)."""
    ox, oy = owner["origin"]
    a = math.radians(owner.get("rotation_deg") or 0.0)
    c, s = round(math.cos(a), 12), round(math.sin(a), 12)
    dx, dy = p[0] - ox, p[1] - oy
    return dx * c + dy * s, -dx * s + dy * c


def _along(owner: dict[str, Any], side: str, p: Vec) -> float:
    """Where *p* lies along *side* of its owner, from the side's left end seen from outside."""
    u, v = _owner_frame(owner, p)
    left, right = _SIDE_LINE[side](owner["width"], owner["depth"])
    length = math.dist(left, right) or 1.0
    ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
    return (u - left[0]) * ux + (v - left[1]) * uy


def _face(owner: dict[str, Any], side: str, p: Vec) -> tuple[float, float]:
    """*p* on the face of *side* seen from outside: along the side and its elevation; on the
    roof, the owner's own plan frame (its x and y from its origin corner)."""
    if side == "roof":
        return _owner_frame(owner, p)
    return _along(owner, side, p), p[2]


def _top(owner: dict[str, Any], kind: str) -> float:
    if kind == "building":
        return owner["heights"][1]
    return owner.get("height") or 0.0


def _inside(owner: dict[str, Any], kind: str, p: Any) -> bool:
    x0, y0, x1, y1 = owner["footprint"]
    return (
        x0 - 1e-6 <= p[0] <= x1 + 1e-6
        and y0 - 1e-6 <= p[1] <= y1 + 1e-6
        and (p[2] <= _top(owner, kind) + 1e-6)
    )


def _down(value: float) -> float:
    return math.floor(value / ROUND + 1e-6) * ROUND


def _up(value: float) -> float:
    return math.ceil(value / ROUND - 1e-6) * ROUND


def crossings(model: dict[str, Any]) -> list[dict[str, Any]]:
    """The model's ``penetrations`` (see the module text), in pipe order."""
    panels = wall_panels(model)
    if not panels:
        return []
    found: list[dict[str, Any]] = []
    names: dict[str, int] = {}
    for pipe in model.get("pipes", []):
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        points = [tuple(p) for p in pipe["points"]]
        ends = (points[0], points[-1])
        # the runs of one pipe that meet one side of a wall one after the other (a bend in the
        # wall, a run along it) make one penetration
        groups: list[dict[str, Any]] = []
        current: dict[tuple[str, str], dict[str, Any]] = {}
        for k, (a, b) in enumerate(zip(points, points[1:], strict=False)):
            for owner, kind, panel in panels:
                solid = Box(
                    panel["id"],
                    tuple(panel["centre"]),
                    tuple(panel["size"]),
                    panel.get("rotation_deg") or 0.0,
                )
                lo = [min(a[i], b[i]) - r for i in range(3)]
                hi = [max(a[i], b[i]) + r for i in range(3)]
                box = solid.aabb
                if any(hi[i] < box[i] or lo[i] > box[i + 3] for i in range(3)):
                    continue
                if segment_distance(a, b, solid) >= r - TOUCH:
                    continue
                side = _side(panel)
                span = _clip(a, b, solid, 0.0)
                if span is None and side != "roof":  # the roof only where the axis meets it
                    span = _clip(a, b, solid, r)
                if span is None:
                    continue
                p0 = tuple(a[i] + (b[i] - a[i]) * span[0] for i in range(3))
                p1 = tuple(a[i] + (b[i] - a[i]) * span[1] for i in range(3))
                (s0, z0), (s1, z1) = _face(owner, side, p0), _face(owner, side, p1)
                s0, s1 = sorted((s0, s1))
                z0, z1 = sorted((z0, z1))
                key = (owner["id"], side)
                entry = current.get(key)
                if entry is None or entry["run"] < k - 1:
                    entry = current[key] = {
                        "run": k,
                        "owner": owner,
                        "kind": kind,
                        "panel": panel,
                        "side": side,
                        "extent": [s0, s1, z0, z1],
                        "points": [p0, p1],
                    }
                    groups.append(entry)
                else:
                    entry["run"] = k
                    e = entry["extent"]
                    entry["extent"] = [min(e[0], s0), max(e[1], s1), min(e[2], z0), max(e[3], z1)]
                    entry["points"] += [p0, p1]
        for entry in groups:
            owner, kind, panel = entry["owner"], entry["kind"], entry["panel"]
            owner_id, side = owner["id"], entry["side"]
            s0, s1, z0, z1 = entry["extent"]
            grow = r + SLEEVE_GAP
            offset = max(0.0, _down(s0 - grow))
            sill = max(0.0, _down(z0 - grow))
            opening = {
                "side": side,
                "offset": round(offset, 3),
                "width": round(_up(s1 + grow) - offset, 3),
                "height": round(_up(z1 + grow) - sill, 3),
                "sill": round(sill, 3),
                "kind": "opening",
            }
            pts = entry["points"]
            point = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
            inside = any(_inside(owner, kind, e) for e in ends)
            material = panel.get("material") or ""
            if not inside:
                reason = f"passes through the {material or 'wall'} of {owner_id}"
            elif side == "roof":
                reason = f"through the roof of building {owner_id}: a roof penetration"
            elif material == "fire_wall":
                reason = f"through fire wall {owner_id}: a fire-rated penetration"
            elif kind == "building":
                reason = f"into building {owner_id}: an opening in its {material or 'wall'}"
            else:
                reason = f"into {owner_id}: a {material or 'wall'} penetration"
            along = max(s1 - s0, z1 - z0)
            if along > 2 * r + 0.5:
                plane = "roof slab" if side == "roof" else "wall"
                reason += f", running {along:.1f} m in the {plane}"
            name = f"{owner_id}/{pipe['line']}"
            names[name] = names.get(name, 0) + 1
            pid = name if names[name] == 1 else f"{name}-{names[name]}"
            found.append(
                {
                    "id": pid,
                    "refs": {"lines": [pipe["line"]], "segments": [pipe["segment"]]},
                    "source": "generated",
                    "owner": owner_id,
                    "wall": panel["id"],
                    "pipe": pipe["id"],
                    "point": point,
                    "material": material,
                    "end_inside": inside,
                    "length": round(along, 3),
                    "opening": opening,
                    "review_needed": True,
                    "reason": reason,
                }
            )
    return found
