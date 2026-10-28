"""Distances on the plot plan: line routes over pipe racks, declared separations, ``show --layout``.

Everything is horizontal (plan) geometry in metres, on the footprints the layout rules use: an
equipment item's plan outline (a circle for a vertical cylinder, else its turned rectangle;
``layout_validate.plan_outline``), a building's rotated rectangle, an area's box, and roads and
racks as strips along their centrelines.

**Line routes** (``cheme.layout-line-*``). Each end of a line of ``piping/line-list.yaml`` is
resolved to a place: a placed tag (equipment or piping item; ``K-4101/N2`` is read as
``K-4101``), an area id, the line's ``from_area`` / ``to_area``, or -- for an end that names
another line -- the point of that line (taken as the straight run between its own resolved ends)
nearest the other end. A line whose ends lie in different areas, or further apart than the site
plan's ``max_unsupported_length`` (default 30 m), needs a rack: each end must be within
``rack_reach`` of a rack centreline (``schemas.rack_reach``, the value the pipe router uses
too; default: ``max_unsupported_length``, as the run from an end to the rack is unsupported
pipe), and the racks at the two ends must be connected (strips
touching or crossing). The route length is estimated along the rack
centrelines.

**Separations** (``cheme.layout-separation``): the site plan's ``separations`` each name two
things (a tag, area, building, road, rack or ``site-boundary``) and a minimum horizontal distance,
``min_m`` or ``min_factor_of_height`` times the height of the taller of the two (or the one
``height_of`` names). The distance is between footprints, or between centres with
``measure: centre``.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.spatial.layout_validate import (
    EPS,
    Polygon,
    body_outline,
    box_polygon,
    building_corners,
    building_heights,
    polygons_overlap,
    resolve,
    strip,
)
from chemeascode.domains.spatial.schemas import rack_reach

Point = tuple[float, float]
SITE_BOUNDARY = "site-boundary"


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def point_segment(p: Point, a: Point, b: Point) -> tuple[float, Point, float]:
    """Distance from *p* to segment *ab*, the nearest point, and its parameter (0..1)."""
    ax, ay = a
    dx, dy = b[0] - ax, b[1] - ay
    length2 = dx * dx + dy * dy
    t = (
        0.0
        if length2 <= EPS
        else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / length2))
    )
    q = (ax + t * dx, ay + t * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q, t


def _segments_cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    def orient(p: Point, q: Point, r: Point) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def segment_distance(a: Point, b: Point, c: Point, d: Point) -> float:
    if _segments_cross(a, b, c, d):
        return 0.0
    return min(
        point_segment(a, c, d)[0],
        point_segment(b, c, d)[0],
        point_segment(c, a, b)[0],
        point_segment(d, a, b)[0],
    )


def _edges(polygon: Polygon) -> list[tuple[Point, Point]]:
    if len(polygon) == 1:
        return [(polygon[0], polygon[0])]
    return [(polygon[i], polygon[(i + 1) % len(polygon)]) for i in range(len(polygon))]


def _inside(p: Point, polygon: Polygon) -> bool:
    """Whether *p* lies inside the convex *polygon* (or on it)."""
    if len(polygon) < 3:
        return False
    sign = 0.0
    for a, b in _edges(polygon):
        cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
        if abs(cross) <= EPS:
            continue
        if sign == 0.0:
            sign = cross
        elif sign * cross < 0:
            return False
    return True


def polygon_distance(a: Polygon, b: Polygon) -> float:
    """Horizontal distance between two convex polygons (a single point is a polygon); 0 when they
    touch or overlap."""
    if len(a) >= 3 and len(b) >= 3 and polygons_overlap(a, b):
        return 0.0
    if any(_inside(p, b) for p in a) or any(_inside(p, a) for p in b):
        return 0.0
    return min(segment_distance(p, q, r, s) for p, q in _edges(a) for r, s in _edges(b))


def shape_distance(a: list[Polygon], b: list[Polygon]) -> float:
    """Horizontal distance between two shapes; infinite when one has no outline."""
    return min((polygon_distance(p, q) for p in a for q in b), default=math.inf)


def centre(polygons: list[Polygon]) -> Point:
    points = [p for polygon in polygons for p in polygon]
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def nearest_point(polygons: list[Polygon], target: Point) -> Point:
    """The point of the shape nearest *target* (*target* itself when inside)."""
    best: tuple[float, Point] | None = None
    for polygon in polygons:
        if _inside(target, polygon):
            return target
        for a, b in _edges(polygon):
            distance, q, _ = point_segment(target, a, b)
            if best is None or distance < best[0]:
                best = (distance, q)
    assert best is not None
    return best[1]


def boundary_distance(polygons: list[Polygon], width: float, depth: float) -> float:
    """Distance from a shape inside the site to the site boundary."""
    return min(min(x, width - x, y, depth - y) for polygon in polygons for x, y in polygon)


# ---------------------------------------------------------------------------
# Things on the plot plan
# ---------------------------------------------------------------------------


@dataclass
class Thing:
    """Something on the plot plan with a footprint."""

    kind: str  # equipment, area, building, road, rack
    id: str
    polygons: list[Polygon]
    height: float = 0.0  # top above grade, m
    area: str | None = None


def things(layout: Any) -> dict[str, Thing]:
    """Every placed item, area, building, road and rack of *layout*, by id (tags first)."""
    found: dict[str, Thing] = {}
    plan = layout.site_plan
    for i, item in enumerate(layout.placement.equipment if layout.placement else []):
        shape = layout.resolved[i].body if i < len(layout.resolved) else resolve(item).body
        found.setdefault(
            item.tag, Thing("equipment", item.tag, [body_outline(shape)], shape.bbox()[5])
        )
    for building in layout.buildings.buildings if layout.buildings else []:
        found.setdefault(
            building.id,
            Thing(
                "building", building.id, [building_corners(building)], building_heights(building)[1]
            ),
        )
    if plan is not None:
        for area in plan.areas:
            found.setdefault(area.id, Thing("area", area.id, [box_polygon(area.box)]))
        for road in plan.roads:
            found.setdefault(road.id, Thing("road", road.id, strip(road.points, road.width)))
        for structure in layout.structures.structures if layout.structures else []:
            from chemeascode.domains.spatial.structures import Frame

            frame = Frame(structure.origin, structure.rotation_deg)
            corners = [
                frame.site(u, v)[:2]
                for u, v in (
                    (0, 0),
                    (structure.width, 0),
                    (structure.width, structure.depth),
                    (0, structure.depth),
                )
            ]
            top = max((lv.elevation for lv in structure.levels), default=0.0)
            found.setdefault(structure.id, Thing("building", structure.id, [corners], top))
        for rack in plan.racks:
            top = max(rack.levels) if rack.levels else 0.0
            found.setdefault(rack.id, Thing("rack", rack.id, strip(rack.points, rack.width), top))
        for thing in found.values():
            if thing.kind in ("equipment", "building"):
                thing.area = area_of(plan, centre(thing.polygons))
    return found


def area_of(plan: Any, point: Point) -> str | None:
    """The (non-road) area the point lies in."""
    for area in plan.areas:
        x0, y0, x1, y1 = area.box
        if (
            area.kind != "road"
            and x0 - EPS <= point[0] <= x1 + EPS
            and y0 - EPS <= point[1] <= y1 + EPS
        ):
            return area.id
    return None


# ---------------------------------------------------------------------------
# Racks as a network
# ---------------------------------------------------------------------------


def _polyline_project(points: list[Point], p: Point) -> tuple[float, Point, float]:
    """Distance from *p* to a polyline, the nearest point and its arc length along it."""
    best = (math.inf, points[0], 0.0)
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        distance, q, t = point_segment(p, a, b)
        if distance < best[0]:
            best = (distance, q, run + t * length)
        run += length
    return best


def _crossings(a: list[Point], b: list[Point]) -> list[tuple[float, float]]:
    """Arc lengths ``(along a, along b)`` of each point where polylines *a* and *b* cross or
    touch (parallel segments that overlap are left out)."""
    found = []
    run_a = 0.0
    for p, q in zip(a, a[1:], strict=False):
        rx, ry = q[0] - p[0], q[1] - p[1]
        length_a = math.hypot(rx, ry)
        run_b = 0.0
        for c, d in zip(b, b[1:], strict=False):
            sx, sy = d[0] - c[0], d[1] - c[1]
            length_b = math.hypot(sx, sy)
            cross = rx * sy - ry * sx
            if length_a > EPS and length_b > EPS and abs(cross) > EPS * length_a * length_b:
                wx, wy = c[0] - p[0], c[1] - p[1]
                t = (wx * sy - wy * sx) / cross
                u = (wx * ry - wy * rx) / cross
                ta, tb = EPS / length_a, EPS / length_b
                if -ta <= t <= 1 + ta and -tb <= u <= 1 + tb:
                    t, u = min(max(t, 0.0), 1.0), min(max(u, 0.0), 1.0)
                    found.append((run_a + t * length_a, run_b + u * length_b))
            run_b += length_b
        run_a += length_a
    return found


class RackNetwork:
    """Racks joined where their strips touch; shortest paths along the centrelines."""

    def __init__(self, racks: list[Any]) -> None:
        self.racks = {rack.id: rack for rack in racks}
        self.points = {rack.id: [tuple(p) for p in rack.points] for rack in racks}
        self.strips = {rack.id: strip(rack.points, rack.width) for rack in racks}
        self.joints: list[tuple[str, float, str, float, float]] = []
        ids = list(self.racks)
        parent = {r: r for r in ids}

        def find(r: str) -> str:
            while parent[r] != r:
                parent[r] = parent[parent[r]]
                r = parent[r]
            return r

        for i, a in enumerate(ids):
            for b in ids[i + 1 :]:
                if shape_distance(self.strips[a], self.strips[b]) > EPS:
                    continue
                self.joints.extend(self._joints(a, b))
                parent[find(a)] = find(b)
        self.component = {r: find(r) for r in ids}

    def _joints(self, a: str, b: str) -> list[tuple[str, float, str, float, float]]:
        """Where racks *a* and *b* meet: each point where their centrelines cross or touch (gap
        0; two racks can cross more than once), and the closest pair of a centreline vertex and
        the other centreline: always without a crossing, else when it is no further apart than
        a rack width and more than a rack width from every crossing (a branch ending on the edge
        of the other rack's strip that also crosses it elsewhere)."""
        crossings: list[tuple[float, float]] = []
        for sa, sb in _crossings(self.points[a], self.points[b]):
            if all(abs(sa - x) > EPS or abs(sb - y) > EPS for x, y in crossings):
                crossings.append((sa, sb))
        best: tuple[float, float, float] | None = None
        for point in self.points[a]:
            d, _, s = _polyline_project(self.points[b], point)
            sa = _polyline_project(self.points[a], point)[2]
            if best is None or d < best[0]:
                best = (d, sa, s)
        for point in self.points[b]:
            d, _, s = _polyline_project(self.points[a], point)
            sb = _polyline_project(self.points[b], point)[2]
            if best is None or d < best[0]:
                best = (d, s, sb)
        assert best is not None
        found = [(a, sa, b, sb, 0.0) for sa, sb in crossings]
        gap, sa, sb = best
        near = max(self.racks[a].width, self.racks[b].width)
        at = sub_polyline(self.points[a], sa, sa)[0]
        if not crossings or (
            gap <= near
            and all(
                math.dist(at, sub_polyline(self.points[a], x, x)[0]) > near for x, _ in crossings
            )
        ):
            found.append((a, sa, b, sb, gap))
        return found

    def nearest(
        self, polygons: list[Polygon], toward: Point
    ) -> list[tuple[float, str, Point, float]]:
        """``(distance, rack, entry point, arc length)`` of each rack from a shape, nearest first.

        The distance is from the shape's point nearest the rack to the rack's centreline."""
        found = []
        for rack_id, points in self.points.items():
            best = (math.inf, points[0], 0.0)
            for polygon in polygons:
                for p in polygon:
                    candidate = _polyline_project(points, p)
                    if candidate[0] < best[0]:
                        best = candidate
                for a, b in _edges(polygon):
                    for q in points:
                        d, on_shape, _ = point_segment(q, a, b)
                        if d < best[0]:
                            best = (d, q, _polyline_project(points, q)[2])
                if any(_inside(q, polygon) for q in points):
                    inside = next(q for q in points if _inside(q, polygon))
                    best = (0.0, inside, _polyline_project(points, inside)[2])
            found.append((best[0], rack_id, best[1], best[2]))
        return sorted(found)

    def path_length(self, a: str, sa: float, b: str, sb: float) -> float | None:
        """Shortest length along the centrelines from arc *sa* of rack *a* to *sb* of rack *b*."""
        found = self._dijkstra(a, sa, b, sb)
        return found[0] if found is not None else None

    def path(self, a: str, sa: float, b: str, sb: float) -> list[tuple[str, list[Point]]] | None:
        """The shortest way along the centrelines from arc *sa* of rack *a* to *sb* of rack
        *b*: ``[(rack, polyline), ...]``, one polyline per rack in travel order (a joint between
        racks is the jump from one polyline's end to the next one's start); None when the racks
        are not connected."""
        found = self._dijkstra(a, sa, b, sb)
        if found is None:
            return None
        nodes = found[1]
        legs: list[tuple[str, list[Point]]] = []
        for (r1, s1), (r2, s2) in zip(nodes, nodes[1:], strict=False):
            if r1 != r2:
                continue
            piece = sub_polyline(self.points[r1], s1, s2)
            if legs and legs[-1][0] == r1:
                legs[-1] = (r1, legs[-1][1] + piece[1:])
            else:
                legs.append((r1, piece))
        if not legs:
            point = sub_polyline(self.points[a], sa, sa)
            legs.append((a, point))
        return legs

    def _dijkstra(
        self, a: str, sa: float, b: str, sb: float
    ) -> tuple[float, list[tuple[str, float]]] | None:
        if self.component.get(a) != self.component.get(b):
            return None
        stops: dict[str, set[float]] = {r: set() for r in self.racks}
        stops[a].add(sa)
        stops[b].add(sb)
        for ra, s1, rb, s2, _ in self.joints:
            stops[ra].add(s1)
            stops[rb].add(s2)
        edges: dict[tuple[str, float], list[tuple[tuple[str, float], float]]] = {}
        for rack, positions in stops.items():
            ordered = sorted(positions)
            for x, y in zip(ordered, ordered[1:], strict=False):
                edges.setdefault((rack, x), []).append(((rack, y), y - x))
                edges.setdefault((rack, y), []).append(((rack, x), y - x))
        for ra, s1, rb, s2, gap in self.joints:
            edges.setdefault((ra, s1), []).append(((rb, s2), gap))
            edges.setdefault((rb, s2), []).append(((ra, s1), gap))
        start, goal = (a, sa), (b, sb)
        best = {start: 0.0}
        previous: dict[tuple[str, float], tuple[str, float]] = {}
        queue = [(0.0, start)]
        while queue:
            cost, node = heapq.heappop(queue)
            if node == goal:
                nodes = [node]
                while nodes[-1] in previous:
                    nodes.append(previous[nodes[-1]])
                return cost, nodes[::-1]
            if cost > best.get(node, math.inf):
                continue
            for neighbour, weight in edges.get(node, []):
                total = cost + weight
                if total < best.get(neighbour, math.inf) - EPS:
                    best[neighbour] = total
                    previous[neighbour] = node
                    heapq.heappush(queue, (total, neighbour))
        return None

    def project(self, rack: str, p: Point) -> tuple[float, Point, float]:
        """Distance from *p* to the centreline of *rack*, the nearest point, its arc length."""
        return _polyline_project(self.points[rack], p)


def offset_polyline(points: list[Point], d: float) -> list[Point]:
    """*points* moved *d* to the left of their direction (mitred at the bends)."""
    if abs(d) <= EPS or len(points) < 2:
        return list(points)
    normals = []
    for a, b in zip(points, points[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
        normals.append((-(b[1] - a[1]) / length, (b[0] - a[0]) / length))
    found = []
    for i, p in enumerate(points):
        if i == 0:
            n = normals[0]
        elif i == len(points) - 1:
            n = normals[-1]
        else:
            n0, n1 = normals[i - 1], normals[i]
            mx, my = n0[0] + n1[0], n0[1] + n1[1]
            m = math.hypot(mx, my)
            if m <= EPS:
                n = n1
            else:
                mx, my = mx / m, my / m
                c = mx * n1[0] + my * n1[1]
                n = (mx / c, my / c) if abs(c) > 0.2 else n1
        found.append((p[0] + n[0] * d, p[1] + n[1] * d))
    return found


def sub_polyline(points: list[Point], s1: float, s2: float) -> list[Point]:
    """The part of a polyline from arc length *s1* to *s2* (reversed when *s2* < *s1*)."""
    lo, hi = min(s1, s2), max(s1, s2)
    found: list[Point] = []
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        if length <= EPS:
            continue
        t0, t1 = (lo - run) / length, (hi - run) / length
        if t1 >= -EPS and t0 <= 1 + EPS:
            for t in (max(0.0, t0), min(1.0, t1)):
                q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
                if not found or math.hypot(q[0] - found[-1][0], q[1] - found[-1][1]) > EPS:
                    found.append(q)
        run += length
    if not found:
        end = points[-1] if lo >= run else points[0]
        found = [end]
    if len(found) == 1:
        found.append(found[0])
    return found if s2 >= s1 else found[::-1]


# ---------------------------------------------------------------------------
# Line routes
# ---------------------------------------------------------------------------


@dataclass
class End:
    text: str
    polygons: list[Polygon] | None = None
    label: str = ""
    area: str | None = None
    via_line: str | None = None


@dataclass
class LineRoute:
    """What the route check found for one line (``GET /api/layout`` ``lines``)."""

    number: str
    from_: str
    to: str
    from_point: Point | None = None
    to_point: Point | None = None
    distance: float | None = None
    length_est: float | None = None
    racks: list[str] = field(default_factory=list)
    finding: str | None = None  # the rule of the finding on it, if any

    def as_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "from": self.from_,
            "to": self.to,
            "from_point": list(self.from_point) if self.from_point else None,
            "to_point": list(self.to_point) if self.to_point else None,
            "distance": round(self.distance, 1) if self.distance is not None else None,
            "length_est": round(self.length_est, 1) if self.length_est is not None else None,
            "racks": self.racks,
            "finding": self.finding,
        }


def _base_tag(text: str) -> str:
    for separator in ("/", " ", "("):
        text = text.split(separator, 1)[0]
    return text.strip()


def route_lines(rules: Any, lines: Any) -> list[LineRoute]:
    """``cheme.layout-line-route`` / ``-line-unrouted`` / ``-line-length`` for *lines*
    (a parsed line list); findings go to *rules* (the layout rules of ``layout_validate``)."""
    layout = rules.layout
    plan = layout.site_plan
    if plan is None or layout.placement is None or lines is None:
        return []
    placed = things(layout)
    areas = {a.id: a for a in plan.areas}
    by_number = {line.number.strip(): line for line in lines.lines}
    network = RackNetwork(list(plan.racks))
    limit = plan.max_unsupported_length
    routing = getattr(layout, "routing", None)
    reach = rack_reach(plan, routing.rules if routing is not None else None)

    def resolve(text: str, area: str | None, depth: int = 0) -> End:
        text = (text or "").strip()
        tag = _base_tag(text)
        for key in (text, tag):
            thing = placed.get(key)
            if thing is not None and thing.kind in ("equipment", "building", "area"):
                found_area = thing.area if thing.kind != "area" else thing.id
                return End(text, thing.polygons, key, found_area)
        if area and area in areas:
            return End(text, [box_polygon(areas[area].box)], f"area {area}", area)
        other = by_number.get(text) or by_number.get(tag)
        if other is not None and depth < 3:
            a = resolve(other.from_, other.from_area, depth + 1)
            b = resolve(other.to, other.to_area, depth + 1)
            if a.polygons and b.polygons:
                p, q = centre(a.polygons), centre(b.polygons)
                return End(text, [[p, q]], f"line {other.number}", None, via_line=other.number)
            known = a if a.polygons else b if b.polygons else None
            if known is not None:
                return End(
                    text,
                    known.polygons,
                    f"line {other.number} at {known.label}",
                    known.area,
                    other.number,
                )
        return End(text)

    rules_tags = (
        {item.tag.strip() for item in rules.equipment.equipment} if rules.equipment else set()
    )
    if rules.piping_items is not None:
        rules_tags |= {item.tag.strip() for item in rules.piping_items.piping_items}
    rules_tags |= rules.drawn_tags
    routes = []
    for position, line in enumerate(lines.lines):
        number = line.number.strip()
        start = resolve(line.from_, line.from_area)
        end = resolve(line.to, line.to_area)
        route = LineRoute(number, line.from_, line.to)
        routes.append(route)
        loc = ("lines", position)
        if not start.polygons or not end.polygons:
            missing = [e.text for e in (start, end) if not e.polygons]
            # Only an end that names a listed or drawn tag should be on the plot plan (not BL).
            if (start.polygons or end.polygons) and any(
                text.strip() in rules_tags or _base_tag(text) in rules_tags for text in missing
            ):
                rules.add_line(
                    loc,
                    "info",
                    "line-unrouted",
                    f"line {number}: {', '.join(missing)} is not placed, so its route is not "
                    "checked",
                    [number],
                    "place it in layout/equipment-placement.yaml (a silencer or relief valve "
                    "drawn on a sheet: list it in piping/special-items.yaml first), or give the "
                    "line from_area / to_area",
                )
                route.finding = "cheme.layout-line-unrouted"
            continue
        # A line-to-line end sits at the point of the other line nearest this line's other end.
        if start.via_line:
            start.polygons = [[nearest_point(start.polygons, centre(end.polygons))]]
            start.area = area_of(plan, start.polygons[0][0])
        if end.via_line:
            end.polygons = [[nearest_point(end.polygons, centre(start.polygons))]]
            end.area = area_of(plan, end.polygons[0][0])
        p = nearest_point(start.polygons, centre(end.polygons))
        q = nearest_point(end.polygons, p)
        route.from_point, route.to_point = p, q
        distance = math.hypot(p[0] - q[0], p[1] - q[1])
        route.distance = distance
        across = start.area != end.area and None not in (start.area, end.area)
        if not across and distance <= limit:
            continue
        if not plan.racks:
            reason = "the site plan has no racks"
            racks_a = racks_b = []
        else:
            racks_a = network.nearest(start.polygons, q)
            racks_b = network.nearest(end.polygons, p)
        best = None
        for da, ra, _, sa in racks_a:
            if da > reach:
                break
            for db, rb, _, sb in racks_b:
                if db > reach:
                    break
                along = network.path_length(ra, sa, rb, sb)
                if along is None:
                    continue
                total = da + along + db
                if best is None or total < best[0]:
                    best = (total, ra, rb)
        where = (
            f"{start.label} ({start.area or 'no area'}) to {end.label} ({end.area or 'no area'}): "
            f"{distance:.0f} m"
        )
        if best is not None:
            route.length_est = best[0]
            route.racks = list(dict.fromkeys([best[1], best[2]]))
            rules.add_line(
                loc,
                "info",
                "line-length",
                f"line {number} {where} apart, about {best[0]:.0f} m along racks "
                f"{', '.join(route.racks)}",
                [number],
                "use the estimate for line lengths, pressure drop and velocity checks",
            )
            route.finding = "cheme.layout-line-length"
            continue
        if plan.racks:
            gaps = []
            for label, found in ((start.label, racks_a), (end.label, racks_b)):
                near = found[0]
                if near[0] > reach:
                    gaps.append(f"nearest rack to {label} is {near[1]}, {near[0]:.0f} m away")
            if not gaps:
                gaps.append(
                    f"racks {racks_a[0][1]} and {racks_b[0][1]} near its ends are not connected"
                )
            reason = "; ".join(gaps)
        rules.add_line(
            loc,
            "warning",
            "line-route",
            f"line {number} {where} {'across areas' if across else 'apart'} and no rack "
            f"carries it: {reason} (reach {reach:g} m)",
            [number],
            "add or extend a rack (site-plan.yaml racks) to reach both ends, or move the items "
            "closer; set max_unsupported_length / rack_reach in site-plan.yaml for this plant",
        )
        route.finding = "cheme.layout-line-route"
    return routes


# ---------------------------------------------------------------------------
# Separations
# ---------------------------------------------------------------------------


def separations(rules: Any) -> None:
    """``cheme.layout-separation`` for each declared separation of the site plan."""
    plan = rules.layout.site_plan
    if plan is None or not plan.separations:
        return
    found = things(rules.layout)
    width, depth = plan.site.width, plan.site.depth
    zones = {z.id for z in rules.layout.zones.zones} if rules.layout.zones is not None else set()
    for position, rule in enumerate(plan.separations):
        loc = ("separations", position)
        if rule.from_ in zones or rule.to in zones:
            continue  # measured on the built model (model_rules: layout-separation)
        unknown = [
            name for name in (rule.from_, rule.to) if name != SITE_BOUNDARY and name not in found
        ]
        if unknown:
            rules.add(
                "site_plan",
                loc,
                "warning",
                "separation",
                f"separation {rule.from_} to {rule.to} names {', '.join(unknown)}, which is no "
                "placed tag, area, building, road or rack",
                unknown,
                "use a tag of equipment-placement.yaml, an id of site-plan.yaml or "
                "building.yaml, or site-boundary",
            )
            continue
        a = found.get(rule.from_)
        b = found.get(rule.to)
        if a is None and b is None:
            continue
        heights = [t.height for t in (a, b) if t is not None]
        if rule.height_of == "from":
            heights = [a.height] if a else []
        elif rule.height_of == "to":
            heights = [b.height] if b else []
        if rule.min_m is not None:
            required, basis = rule.min_m, f"{rule.min_m:g} m"
        else:
            height = max(heights) if heights else 0.0
            required = (rule.min_factor_of_height or 0.0) * height
            basis = f"{rule.min_factor_of_height:g} x height {height:g} m"
        if a is None or b is None:
            thing = a or b
            assert thing is not None
            measured = boundary_distance(thing.polygons, width, depth)
        elif rule.measure == "centre":
            pa, pb = centre(a.polygons), centre(b.polygons)
            measured = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        else:
            measured = shape_distance(a.polygons, b.polygons)
        if measured + 1e-6 >= required:
            continue
        why = "; ".join(x for x in (rule.basis, rule.reason) if x)
        rules.add(
            "site_plan",
            loc,
            "warning",
            "separation",
            f"{rule.from_} to {rule.to}: {measured:.1f} m < {required:.1f} m ({basis}"
            + (f"; {why}" if why else "")
            + ")",
            [rule.from_, rule.to],
            "move one of them, or record in DESIGN.md why the shorter distance is acceptable "
            "and change the separation",
        )


# ---------------------------------------------------------------------------
# show --layout
# ---------------------------------------------------------------------------


def measure(layout: Any, tag: str, count: int = 5) -> list[str] | None:
    """Measured distances from *tag* to the nearest items, buildings, roads, racks and the site
    boundary, for ``cheme show TAG --layout``; None when *tag* is not on the plot plan."""
    found = things(layout)
    thing = found.get(tag)
    if thing is None:
        return None
    plan = layout.site_plan
    lines = [
        f"{tag} ({thing.kind}"
        + (f", area {thing.area}" if thing.area else "")
        + (f", top {thing.height:g} m" if thing.height else "")
        + f"), centre {centre(thing.polygons)[0]:.1f}, {centre(thing.polygons)[1]:.1f}:"
    ]
    titles = {
        "equipment": "nearest items",
        "building": "buildings",
        "road": "roads",
        "rack": "racks",
        "area": "areas",
    }
    for kind, title in titles.items():
        others = [
            (shape_distance(thing.polygons, other.polygons), other)
            for other in found.values()
            if other.kind == kind and other.id != tag
        ]
        if not others:
            continue
        others.sort(key=lambda x: (x[0], x[1].id))
        shown = ", ".join(
            f"{other.id} {distance:.1f} m"
            + (
                f" (centres {math.dist(centre(thing.polygons), centre(other.polygons)):.1f} m)"
                if kind == "equipment"
                else ""
            )
            for distance, other in others[:count]
        )
        lines.append(f"  {title}: {shown}")
    if plan is not None:
        edge = boundary_distance(thing.polygons, plan.site.width, plan.site.depth)
        lines.append(f"  site boundary: {edge:.1f} m")
    lines.append("  (horizontal distances between footprints; 0 m: touching or overlapping)")
    return lines


def show_layout(workspace: Any, tag: str) -> tuple[list[str], bool]:
    """``cheme show TAG --layout``: the lines to print, and whether *tag* was found."""
    from chemeascode.domains.spatial.layout_validate import workspace_layout

    # the equipment list's dimensions size the items (without it every item would take its
    # family's default size and the distances would be wrong)
    lists = workspace.parsed_lists(("equipment", "piping_items"))
    layout = workspace_layout(workspace, lists.get("equipment"), lists.get("piping_items"))
    if not layout.present:
        return ["no layout files (layout/*.yaml)"], False
    if not layout.ruled:
        return ["a layout file is invalid; run `cheme validate`"], False
    lines = measure(layout, tag)
    if lines is None:
        return [
            f"{tag} is not on the plot plan (no placed tag, area, building, road or rack)"
        ], False
    return lines, True
