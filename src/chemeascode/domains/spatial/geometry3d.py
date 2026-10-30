"""3D solids and distances for the router, the clash rules and the 2D drawings.

Pure Python, deterministic, metres in the site frame. Every solid is convex and knows its
axis-aligned box (``aabb``) and the distance from a point to it (0 inside). The distance from a
straight segment to a convex solid is convex along the segment, so :func:`segment_distance`
finds it by a ternary search; a capsule (a pipe: its axis and outer radius) clashes with a solid
when that distance is below the radius.

A model part becomes a solid by :func:`part_solid`: a ``cylinder`` stays one, a ``cone`` is
taken as the cylinder of its larger radius, a ``cap`` as the cylinder from its base to its apex,
a ``member`` as a capsule of half its larger section size, a ``box`` (turned about z) and a
``sphere`` stay what they are, an ``annulus`` (a platform) is the cylinder ring's outer
cylinder slice, a ``torus`` the cylinder around it (as thick as its tube), a ``frustum`` the
box of its larger face. A detail part (``lod: 2``) is no solid: the clash checks, the router
and the drawings take the envelope (``lod`` None or 1); ``detail=True`` asks for the parts
drawn close up instead (``lod`` None or 2).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

Vec = tuple[float, float, float]
Box3 = tuple[float, float, float, float, float, float]

#: Overlaps and distances at or below this count as touching, m.
TOUCH = 1e-3


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Vec, s: float) -> Vec:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def norm(a: Vec) -> float:
    return math.sqrt(dot(a, a))


def dist(a: Vec, b: Vec) -> float:
    return norm(sub(a, b))


def lerp(a: Vec, b: Vec, t: float) -> Vec:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def point_segment(p: Vec, a: Vec, b: Vec) -> tuple[float, float]:
    """Distance from *p* to segment *ab* and the parameter (0..1) of the nearest point."""
    d = sub(b, a)
    length2 = dot(d, d)
    t = 0.0 if length2 <= 1e-18 else max(0.0, min(1.0, dot(sub(p, a), d) / length2))
    return dist(p, lerp(a, b, t)), t


def segment_segment(p1: Vec, q1: Vec, p2: Vec, q2: Vec) -> float:
    """Shortest distance between segments *p1q1* and *p2q2*."""
    d1, d2, r = sub(q1, p1), sub(q2, p2), sub(p1, p2)
    a, e, f = dot(d1, d1), dot(d2, d2), dot(d2, r)
    if a <= 1e-18 and e <= 1e-18:
        return dist(p1, p2)
    if a <= 1e-18:
        s, t = 0.0, max(0.0, min(1.0, f / e))
    else:
        c = dot(d1, r)
        if e <= 1e-18:
            t, s = 0.0, max(0.0, min(1.0, -c / a))
        else:
            b = dot(d1, d2)
            denom = a * e - b * b
            s = max(0.0, min(1.0, (b * f - c * e) / denom)) if denom > 1e-18 else 0.0
            t = (b * s + f) / e
            if t < 0.0:
                t, s = 0.0, max(0.0, min(1.0, -c / a))
            elif t > 1.0:
                t, s = 1.0, max(0.0, min(1.0, (b - c) / a))
    return dist(lerp(p1, q1, s), lerp(p2, q2, t))


def boxes_overlap(a: Box3, b: Box3, margin: float = 0.0) -> bool:
    return all(min(a[i + 3], b[i + 3]) - max(a[i], b[i]) > -margin - 1e-12 for i in range(3))


def segment_box(a: Vec, b: Vec, r: float = 0.0) -> Box3:
    return (
        min(a[0], b[0]) - r,
        min(a[1], b[1]) - r,
        min(a[2], b[2]) - r,
        max(a[0], b[0]) + r,
        max(a[1], b[1]) + r,
        max(a[2], b[2]) + r,
    )


# ---------------------------------------------------------------------------
# Solids
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Solid:
    """A convex solid; ``id`` names what it belongs to (an equipment part, a member, ...)."""

    id: str

    @property
    def aabb(self) -> Box3:  # pragma: no cover - overridden
        raise NotImplementedError

    def distance(self, p: Vec) -> float:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass(frozen=True)
class Capsule(Solid):
    a: Vec = (0.0, 0.0, 0.0)
    b: Vec = (0.0, 0.0, 0.0)
    r: float = 0.0

    @property
    def aabb(self) -> Box3:
        return segment_box(self.a, self.b, self.r)

    def distance(self, p: Vec) -> float:
        return max(0.0, point_segment(p, self.a, self.b)[0] - self.r)


@dataclass(frozen=True)
class Cylinder(Solid):
    """A solid cylinder from *a* to *b* (axis end points) of radius *r*."""

    a: Vec = (0.0, 0.0, 0.0)
    b: Vec = (0.0, 0.0, 0.0)
    r: float = 0.0

    @property
    def aabb(self) -> Box3:
        d = sub(self.b, self.a)
        length = norm(d) or 1.0
        ext = []
        for i in range(3):
            c = d[i] / length
            ext.append(self.r * math.sqrt(max(0.0, 1.0 - c * c)))
        return (
            min(self.a[0], self.b[0]) - ext[0],
            min(self.a[1], self.b[1]) - ext[1],
            min(self.a[2], self.b[2]) - ext[2],
            max(self.a[0], self.b[0]) + ext[0],
            max(self.a[1], self.b[1]) + ext[1],
            max(self.a[2], self.b[2]) + ext[2],
        )

    def distance(self, p: Vec) -> float:
        d = sub(self.b, self.a)
        length = norm(d)
        if length <= 1e-12:
            return max(0.0, dist(p, self.a) - self.r)
        u = scale(d, 1.0 / length)
        w = sub(p, self.a)
        t = dot(w, u)
        radial = norm(sub(w, scale(u, t)))
        axial = -t if t < 0 else (t - length if t > length else 0.0)
        out = max(0.0, radial - self.r)
        return math.hypot(axial, out)


@dataclass(frozen=True)
class Box(Solid):
    """A box: centre, full sizes along its own axes, turned by *rotation_deg* about z."""

    centre: Vec = (0.0, 0.0, 0.0)
    size: Vec = (0.0, 0.0, 0.0)
    rotation_deg: float = 0.0

    @property
    def aabb(self) -> Box3:
        a = math.radians(self.rotation_deg)
        c, s = abs(math.cos(a)), abs(math.sin(a))
        hx = (self.size[0] * c + self.size[1] * s) / 2
        hy = (self.size[0] * s + self.size[1] * c) / 2
        hz = self.size[2] / 2
        x, y, z = self.centre
        return (x - hx, y - hy, z - hz, x + hx, y + hy, z + hz)

    def local(self, p: Vec) -> Vec:
        a = math.radians(self.rotation_deg)
        c, s = math.cos(a), math.sin(a)
        dx, dy, dz = sub(p, self.centre)
        return (dx * c + dy * s, -dx * s + dy * c, dz)

    def distance(self, p: Vec) -> float:
        q = self.local(p)
        out = [max(0.0, abs(q[i]) - self.size[i] / 2) for i in range(3)]
        return math.sqrt(out[0] ** 2 + out[1] ** 2 + out[2] ** 2)


@dataclass(frozen=True)
class Sphere(Solid):
    centre: Vec = (0.0, 0.0, 0.0)
    r: float = 0.0

    @property
    def aabb(self) -> Box3:
        x, y, z = self.centre
        r = self.r
        return (x - r, y - r, z - r, x + r, y + r, z + r)

    def distance(self, p: Vec) -> float:
        return max(0.0, dist(p, self.centre) - self.r)


def segment_distance(a: Vec, b: Vec, solid: Solid, iterations: int = 40) -> float:
    """Shortest distance from segment *ab* to a convex *solid* (0 when they meet)."""
    if isinstance(solid, Capsule):
        return max(0.0, segment_segment(a, b, solid.a, solid.b) - solid.r)
    if isinstance(solid, Sphere):
        return max(0.0, point_segment(solid.centre, a, b)[0] - solid.r)
    lo, hi = 0.0, 1.0
    f = solid.distance
    for _ in range(iterations):
        m1 = lo + (hi - lo) / 3
        m2 = hi - (hi - lo) / 3
        if f(lerp(a, b, m1)) <= f(lerp(a, b, m2)):
            hi = m2
        else:
            lo = m1
    return min(f(a), f(b), f(lerp(a, b, (lo + hi) / 2)))


def part_solid(
    part: dict[str, Any], owner: str | None = None, detail: bool = False
) -> Solid | None:
    """The solid of a model part (see the module text); None for a part it cannot read, and
    for a detail part (``lod: 2``; with *detail*: for an envelope part, ``lod: 1``)."""
    if part.get("lod") == (1 if detail else 2):
        return None
    kind = part.get("kind")
    pid = owner or part.get("id", "")
    if kind == "cylinder":
        return Cylinder(pid, tuple(part["start"]), tuple(part["end"]), part["radius"])
    if kind == "cone":
        r = max(part["radius"], part.get("radius_end") or 0.0)
        return Cylinder(pid, tuple(part["start"]), tuple(part["end"]), r)
    if kind == "cap":
        c = tuple(part["centre"])
        tip = add(c, scale(tuple(part["axis"]), part.get("depth") or 0.0))
        return Cylinder(pid, c, tip, part["radius"])
    if kind == "member":
        b, h = part.get("profile") or (0.1, 0.1)
        return Capsule(pid, tuple(part["start"]), tuple(part["end"]), max(b, h) / 2)
    if kind == "box":
        return Box(pid, tuple(part["centre"]), tuple(part["size"]), part.get("rotation_deg") or 0.0)
    if kind == "sphere":
        return Sphere(pid, tuple(part["centre"]), part["radius"])
    if kind == "annulus":
        c = tuple(part["centre"])
        depth = part.get("depth") or 0.05
        return Cylinder(pid, (c[0], c[1], c[2] - depth), c, part["radius_end"])
    if kind == "torus":
        c = tuple(part["centre"])
        tube = part.get("tube") or 0.0
        axis = scale(tuple(part["axis"]), tube)
        return Cylinder(pid, sub(c, axis), add(c, axis), part["radius"] + tube)
    if kind == "frustum":
        x, y, z = part["centre"]
        dx, dy, height = part["size"]
        tx, ty = part.get("size_end") or (dx, dy)
        size = (max(dx, tx), max(dy, ty), height)
        return Box(pid, (x, y, z + height / 2), size, part.get("rotation_deg") or 0.0)
    return None


# ---------------------------------------------------------------------------
# A bucket index over solids
# ---------------------------------------------------------------------------


class Index:
    """Solids filed by plan cells of *cell* metres, for quick candidate lookups."""

    def __init__(self, cell: float = 4.0) -> None:
        self.cell = cell
        self.items: list[tuple[Solid, Box3, Any]] = []
        self.buckets: dict[tuple[int, int], list[int]] = {}

    def add(self, solid: Solid, data: Any = None) -> None:
        box = solid.aabb
        n = len(self.items)
        self.items.append((solid, box, data))
        c = self.cell
        for i in range(math.floor(box[0] / c), math.floor(box[3] / c) + 1):
            for j in range(math.floor(box[1] / c), math.floor(box[4] / c) + 1):
                self.buckets.setdefault((i, j), []).append(n)

    def near(self, box: Box3, margin: float = 0.0) -> list[tuple[Solid, Box3, Any]]:
        """Solids whose box comes within *margin* of *box*, in the order they were added."""
        c = self.cell
        found: set[int] = set()
        for i in range(math.floor((box[0] - margin) / c), math.floor((box[3] + margin) / c) + 1):
            for j in range(
                math.floor((box[1] - margin) / c), math.floor((box[4] + margin) / c) + 1
            ):
                found.update(self.buckets.get((i, j), ()))
        return [
            self.items[n] for n in sorted(found) if boxes_overlap(self.items[n][1], box, margin)
        ]


def polyline_length(points: Iterable[Vec]) -> float:
    pts = list(points)
    return sum(dist(a, b) for a, b in zip(pts, pts[1:], strict=False))


def point_at(points: list[Vec], s: float) -> tuple[Vec, Vec]:
    """The point at arc length *s* along a polyline and the unit direction there."""
    run = 0.0
    last = (1.0, 0.0, 0.0)
    for a, b in zip(points, points[1:], strict=False):
        length = dist(a, b)
        if length <= 1e-12:
            continue
        last = scale(sub(b, a), 1.0 / length)
        if run + length >= s - 1e-12:
            return lerp(a, b, max(0.0, s - run) / length), last
        run += length
    return points[-1], last


def split_at(points: list[Vec], s: float) -> tuple[list[Vec], list[Vec]]:
    """A polyline cut at arc length *s* into the part before and after (both keep the cut)."""
    run = 0.0
    for i, (a, b) in enumerate(zip(points, points[1:], strict=False)):
        length = dist(a, b)
        if run + length >= s - 1e-9:
            t = 0.0 if length <= 1e-12 else max(0.0, min(1.0, (s - run) / length))
            cut = lerp(a, b, t)
            before = [*points[: i + 1], cut]
            after = [cut, *points[i + 1 :]]
            return simplify(before), simplify(after)
        run += length
    return simplify(points), [points[-1], points[-1]]


def split_at_many(
    points: list[Vec], cuts: list[float], at: list[Vec | None] | None = None
) -> tuple[list[list[Vec]], list[Vec]]:
    """A polyline cut at the increasing arc lengths *cuts*: the ``len(cuts) + 1`` pieces and the
    cut points. Each cut point is computed once and is both the last point of the piece before
    and the first of the piece after, so neighbours meet exactly. ``at[i]``, where given and
    within 1 µm of cut *i*, is used as that cut point (a point another pipe already starts at)."""
    segs = list(zip(points, points[1:], strict=False))
    pieces: list[list[Vec]] = []
    found: list[Vec] = []
    current = [points[0]]
    run = 0.0
    i = 0
    for k, s in enumerate(cuts):
        while i < len(segs):
            a, b = segs[i]
            length = dist(a, b)
            if length > 1e-12 and run + length >= s - 1e-12:
                break
            run += length
            current.append(b)
            i += 1
        if i < len(segs):
            a, b = segs[i]
            p = lerp(a, b, min(1.0, max(0.0, s - run) / dist(a, b)))
        else:
            p = points[-1]
        given = at[k] if at else None
        if given is not None and dist(given, p) <= 1e-6:
            p = given
        current.append(p)
        pieces.append(current)
        found.append(p)
        current = [p]
    current.extend(b for _, b in segs[i:])
    pieces.append(current)
    out = []
    for piece in pieces:
        kept = simplify(piece)
        kept[0], kept[-1] = piece[0], piece[-1]  # simplify may drop an end within 1e-6 of a bend
        out.append(kept)
    return out, found


def simplify(points: list[Vec]) -> list[Vec]:
    """Drop repeated points, points in the middle of a straight run and spikes (a run that
    turns straight back on itself is cut where it turns)."""
    found: list[Vec] = []
    for p in points:
        while True:
            if found and dist(found[-1], p) <= 1e-6:
                break
            if len(found) >= 2:
                a, b = found[-2], found[-1]
                u, v = sub(b, a), sub(p, b)
                nu, nv = norm(u), norm(v)
                if nu > 1e-9 and nv > 1e-9:
                    cos = dot(u, v) / (nu * nv)
                    if cos > 1 - 1e-9 or cos < -1 + 1e-9:
                        found.pop()  # b is in the middle of a run, or the tip of a spike
                        continue
            found.append(p)
            break
    if len(found) == 1:
        found.append(found[0])
    return found
