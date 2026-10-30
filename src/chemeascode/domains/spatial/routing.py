"""Pipe routes of the 3D model: one polyline per DEXPI piping segment.

Pure Python and deterministic: the same inputs give the same routes. The router works on the
built model (equipment parts, nozzles, envelopes, structures, zones), the piping network of the
P&IDs (:mod:`chemeascode.domains.spatial.pid_network`), the line list (DN, class, insulation,
fluid, the ends of a line leaving the sheets), ``piping/pipe-specs.yaml`` and
``piping/routing.yaml``.

**Topology.** Each segment ends at a nozzle (a fixed point with its outward direction), a tee,
an off-page connector or a piping component. Connectors are paired by line number across the
sheets (in sheet and file order); a connector without a partner takes the line list's end of
the line: ``ATM`` (or a vent) is an open end; ``BL`` (any end that is no placed tag or line, such
as ``CW`` or ``CWR``) a *battery limit*: the first ``battery_limits`` rule of ``routing.yaml``
matching the line (number pattern or fluid) gives a point or a rack end, else the line's
``from_area``/``to_area`` edge, else the free rack end nearest the other end (in the line's
lane on its tier), else the site edge nearest the other end; a placed tag is its nozzle on that
line (else its box), another line number the nearest point of that line.
A component two segments share (a safety valve with its outlet line) joins them; one only one
segment reaches is the open end of a vent or relief line, unless it is placed. An open end
beyond a silencer or safety valve of the segment that is placed in the layout ends at that
item instead (the vent discharges there). Segments are
chained through connector pairs, shared components and the run of each tee (nodes 0 and 1);
a tee's branch (node 2) starts from the point the run's route gives the tee.

**Order.** Chains by their largest DN (descending), then by id; a chain whose end waits for a
tee or line not routed yet comes back once it is.

**Routes.** A nozzle end leaves along its direction for a stub of at least 2 x OD (a stub that
ends under or inside its own item continues sideways out of the item's outline). Every leg is
an orthogonal A* search on a grid of ``grid_m`` (default 0.5 m), aligned to its start, with a
cost per bend, around every obstacle grown by the pipe's outer radius (OD + insulation) plus
``spacing_m``: equipment parts and maintenance envelopes, steel members (rack beams and columns
too), stairs and ladders, the
stubs of the other nozzles, the pipes routed before, the forbidden zones (keep clear, laydown,
maintenance; escape routes up to the walkway headroom) and the road headroom
(``headroom_road_m`` above each road). Enclosure walls (a cold box casing, a fire wall) and
building walls are obstacles for a line passing by and passable for a line with an end inside
(its wall penetration). Near each end (a bubble) the fixed obstacles block only where the pipe
itself would cut them and the pipes routed before by ``spacing_m`` (each move there checked as a
whole); the pipe an end lies on (the run a branch leaves) does not block there. The last run
onto the end is moved onto the end's exact position where that keeps the spacing, else another
arrival at the goal node is tried. A search that does not reach its goal within
:data:`MAX_EXPANSIONS` is retried on a grid twice as coarse, then on half the grid with
:data:`FINE_EXPANSIONS` (``astar_fine``), and only then replaced by an orthogonal route over the
obstacles at a clear elevation (``method: direct``, ``review_needed``).

*Rack or local* (the pipe's ``reason``). A chain goes over the racks when an end is a battery
limit at a rack end, the line asks for a ``rack`` or ``tier``, its ends lie in different areas,
the straight line between them crosses a road or another area, or they are more than
``local_max_m`` (default 15 m) apart in plan; for the length alone only while the rack route is
at most ``rack_detour_factor`` times the plan distance. The racks are chosen by twice the
orthogonal distance to and from them (an unsupported run off the rack counts double) plus the
run along them, :data:`RACK_CHANGE_COST` per change of rack and :data:`ROAD_CROSSING_COST` for
a way to or from a rack across a road; ends whose rack points are closer than the rack is wide
stay local (``rack run too short``), and a piece shorter than its rack is wide (touching a rack
at a joint) is dropped. On
the rack: up (or down) near each end, off the bents, to the tier's *passing* elevation (above
the top tier, under the steel of the others), by A* to the rack point nearest that end, onto
the tier (a ``routing.yaml`` tier rule by fluid or line prefix, else the lowest tier for DN 300
and above and the highest otherwise), along the rack network's centrelines in a lane of its
own (lanes are taken from the rack's edge on the side the line comes from inward, in routing
order, so the large lines run outboard; a lane is shared along the rack by lines whose runs do
not overlap; a lane that would cut a pipe routed before, such as another line's riser through
the tier, is passed over for the next, then the next tier), by A* over or under the lanes from
one rack onto the next, and off again near the other end. Ends within the rack reach
(``schemas.rack_reach``: the site plan's ``rack_reach``, the value the line-route check uses)
of a rack can use it. A chain
that stays local runs at the pipe-way elevation: up (or down) near each end to
``local_elevation_m`` (bottom of pipe, default 3.5 m), across, and down near the other end;
except ends closer than ``grade_max_m`` (default 3 m), runs from or to a pump (its suction and
discharge at grade) and lines whose ends both lie above the pipe-way, which take one leg as
found. A route that doubles back under (or over) itself (a run, a riser and a run straight
back, such as a lane run past the point where the line drops off the rack) is cut to the
riser where the two runs overlap, wherever that riser keeps its spacing. ``via`` points and
``elevation`` turn a route into local legs through those points; a
pinned ``route`` is taken as it is. The router counts the chains per method and per reason, and
the battery limit ends by how they were placed (``routing.reasons``, ``battery_limits``).

**In-line items** (valves, check valves, safety valves, reducers, silencers, instruments) are
placed along their segment's route in DEXPI order, 1 m apart from the start (closer when the
route is short); a component at a segment's end sits at that end. A component two segments
share is one item (its id once), with both segments in its refs.

**Open ends** (a vent or relief outlet) rise ``vent_rise_m`` (default 1 m) above the stub; a
``vents`` rule of ``routing.yaml`` matching the line (number pattern or fluid) gives its own
``rise_m`` and raises the outlet until a sphere of its ``radius_m`` (default: the line's zone
radius from ``layout/zones.yaml``, :func:`zones.line_radii`) clears every walking level
(:mod:`chemeascode.domains.spatial.floors`) up to the walkway headroom, at most ``max_rise_m``.
The declared platforms of items are walking levels already (the proposed ones follow the routes).

A chain runs on a rack in the lane of its largest pipe; its smaller segments keep their bottom
of pipe on the tier (:func:`_flat_bottom`).

A segment the router cannot route is listed under ``unrouted`` with the reason.
"""

from __future__ import annotations

import fnmatch
import heapq
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.piping.pipe_data import insulation, outside_diameter, parse_dn, pipe_class
from chemeascode.domains.spatial.geometry3d import (
    Box,
    Capsule,
    Index,
    Solid,
    add,
    dist,
    part_solid,
    point_at,
    point_segment,
    polyline_length,
    scale,
    segment_distance,
    simplify,
    split_at,
    sub,
)
from chemeascode.domains.spatial.pid_network import Segment
from chemeascode.domains.spatial.schemas import FORBIDDEN_ZONES, RoutingRules, rack_reach

Vec = tuple[float, float, float]
#: A* node expansions before a search gives up.
MAX_EXPANSIONS = 30000
#: Arrivals at the goal node an A* search tries before it takes the first one as it is.
GOAL_ARRIVALS = 12
#: Expansions of the last, fine-grid search before a leg falls back to ``direct``.
FINE_EXPANSIONS = 150000
#: Extra cost of a bend, m.
BEND_COST = 1.0
#: Search margin around the two ends of a local leg, m.
MARGIN = 6.0
#: Spacing of in-line items along a route from its start, m.
INLINE_PITCH = 1.0
#: Depth and flange width of a rack beam the router keeps clear of, m (the bents' beams are
#: HE sections of about this size).
RACK_BEAM_DEPTH = 0.4
RACK_BEAM_WIDTH = 0.3
#: Lanes on a rack closer than this along it count as overlapping, m.
LANE_GAP = 1.0
#: Extra cost of a route that changes racks, m (one rack all the way is preferred).
RACK_CHANGE_COST = 5.0
#: Weight of the unsupported runs to and from a rack against the run along it.
OFF_RACK_WEIGHT = 2.0
#: Extra cost of a way to or from a rack that crosses a road (another rack should carry it), m.
ROAD_CROSSING_COST = 100.0
#: Lanes tried on one tier before the next tier, when the first ones cross pipes routed before.
LANE_TRIES = 8
#: Least distance between two junctions (tees) along a chain, m.
JUNCTION_GAP = 2.0
#: How far a route may come inside the spacing of a pinned pipe not yet in the way before it
#: is routed again with it (the router's own tolerance and the millimetres of a pin), m.
PIN_TOLERANCE = 0.01
#: Rise of an open vent or relief end above its stub, m.
OPEN_RISE = 1.0
OPEN_WORDS = ("atm", "atmosphere", "vent", "sky")
DIRS = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


@dataclass
class LineInfo:
    number: str
    dn: float | None = None
    pressure_class: str | None = None
    insulation: str | None = None
    fluid: str | None = None
    from_: str = ""
    to: str = ""
    from_area: str | None = None
    to_area: str | None = None


@dataclass
class EndPoint:
    """A resolved end of a chain."""

    kind: str  # fixed, open, junction, edge, item, line, unresolved
    point: Vec | None = None
    direction: Vec | None = None
    key: str | None = None  # junction key, item tag, line number
    area: str | None = None
    owner: str | None = None  # equipment tag of a nozzle
    reason: str = ""
    label: str = ""
    nozzle: str | None = None  # model nozzle id
    rack_end: str | None = None  # a battery limit at an end of this rack
    basis: str | None = None  # how a battery limit end was placed (rule, area, rack end, ...)


@dataclass
class Chain:
    id: str
    segments: list[tuple[int, bool]]  # (segment index, reversed)
    start: EndPoint
    end: EndPoint
    junctions: list[str | None] = field(default_factory=list)  # between consecutive segments
    dn: float = 0.0


@dataclass
class RouteResult:
    pipes: list[dict[str, Any]] = field(default_factory=list)
    inline: list[dict[str, Any]] = field(default_factory=list)
    unrouted: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


def _stem(sheet: str) -> str:
    return sheet.rsplit("/", 1)[-1].removesuffix(".xml")


class Router:
    """Routes every segment of *segments* through *model* (the model document so far)."""

    def __init__(
        self,
        model: dict[str, Any],
        segments: list[Segment],
        lines: Any = None,
        routing: Any = None,
        specs: Any = None,
        plan: Any = None,
        only: set[str] | None = None,
        keep: list[dict[str, Any]] | None = None,
        vent_radii: dict[str, float] | None = None,
    ) -> None:
        self.keep = {p["id"]: p for p in keep or []}
        self.vent_radii = vent_radii or {}
        self._floors: list[Any] | None = None
        self.model = model
        self.segments = segments
        self.index_of = {id(s): i for i, s in enumerate(segments)}
        self.plan = plan
        self.specs = specs
        self.routing = routing
        self.rules: RoutingRules = routing.rules if routing is not None else RoutingRules()
        self.only = only
        self.lines: dict[str, LineInfo] = {}
        for line in getattr(lines, "lines", None) or ():
            self.lines[line.number.strip()] = LineInfo(
                line.number.strip(),
                parse_dn(line.nominal_diameter),
                line.pressure_class,
                line.insulation,
                line.fluid,
                line.from_,
                line.to,
                line.from_area,
                line.to_area,
            )
        self.intent: dict[tuple[str, str | None], Any] = {}
        for entry in getattr(routing, "lines", None) or ():
            self.intent[(entry.line.strip(), entry.segment)] = entry
        self.equipment = {e["tag"]: e for e in model.get("equipment", [])}
        self.nozzles: dict[tuple[str, str], dict[str, Any]] = {}
        for item in model.get("equipment", []):
            for nozzle in item["nozzles"]:
                self.nozzles[(item["tag"], nozzle["refs"].get("dexpi", ""))] = nozzle
                self.nozzles.setdefault((item["tag"], nozzle["name"]), nozzle)
        self.static = Index(4.0)
        self._static_obstacles()
        self.pipes_index = Index(4.0)
        self.junction_points: dict[str, Vec] = {}
        self.line_points: dict[str, list[list[Vec]]] = {}
        self.lanes: dict[tuple[str, float], list[tuple[float, float, float, float]]] = {}
        #: pinned pipes that are no obstacles yet: ``(place, capsules, lanes)``, *place* their
        #: chain's in the routing order as if nothing were pinned (see :meth:`pinned`)
        self.deferred: list[tuple[int, list[Capsule], list[tuple[Any, Any]]]] = []
        self.order: dict[int, int] = {}
        self.result = RouteResult()
        self.methods: Counter[str] = Counter()
        self.reasons: Counter[str] = Counter()
        #: the stubs of the nozzles the chain being routed starts and ends at (not obstacles)
        self.exempt: set[str] = set()
        self.limits: Counter[str] = Counter()
        self.rack_why = "no rack in reach"
        self.inline_ids: dict[str, dict[str, Any]] = {}
        self.astar_fallback: list[Vec] | None = None
        self.chain_of: dict[int, Chain] = {}
        self.wall_exempt: set[str] = set()
        self.road_polygons: list[list[tuple[float, float]]] = []
        if plan is not None:
            from chemeascode.domains.spatial.layout_validate import strip

            for road in plan.roads:
                self.road_polygons += strip(road.points, road.width)

    # -- obstacles ------------------------------------------------------------------

    def _static_obstacles(self) -> None:
        add_ = self.static.add
        for item in self.model.get("equipment", []):
            for part in item["parts"]:
                solid = part_solid(part, item["tag"])
                if solid is not None:
                    add_(solid, "equipment")
            for envelope in item["envelopes"]:
                add_(
                    Box(
                        item["tag"],
                        tuple(envelope["centre"]),
                        tuple(envelope["size"]),
                        envelope["rotation_deg"],
                    ),
                    "envelope",
                )
        # every connected nozzle keeps the space of its stub free for its own pipe
        for item in self.model.get("equipment", []):
            for nozzle in item["nozzles"]:
                if not nozzle["refs"].get("segments"):
                    continue
                od = outside_diameter(nozzle.get("dn"))
                start = tuple(nozzle["point"])
                tip = add(start, scale(tuple(nozzle["direction"]), max(2 * od, 0.3)))
                add_(Capsule(nozzle["id"], start, tip, od / 2), "stub")
        # enclosure and building walls: passable for a line with an end inside (its wall
        # penetration), an obstacle for lines passing by (see blocked_fn)
        self.enclosures: dict[str, tuple[float, float, float, float]] = {}
        owners = [(s, s.get("walls") or []) for s in self.model.get("structures", [])]
        owners += [(b, b.get("parts") or []) for b in self.model.get("buildings", [])]
        for owner, parts in owners:
            panels = [w for w in parts if isinstance(w, dict) and w.get("kind") == "box"]
            if not panels:
                continue
            self.enclosures[owner["id"]] = tuple(owner["footprint"])  # type: ignore[assignment]
            for wall in panels:
                solid = part_solid(wall, owner["id"])
                if solid is not None:
                    add_(solid, "wall")
        for structure in self.model.get("structures", []):
            for part in structure["parts"]:
                solid = part_solid(part, structure["id"]) if part["kind"] == "member" else None
                if solid is not None:  # not the detail (mid rails, toe plates, posts)
                    add_(solid, "steel")
            for stair in structure["stairs"]:
                x0, y0, z0, x1, y1, z1 = stair["box"]
                add_(
                    Box(
                        stair["id"],
                        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2),
                        (x1 - x0, y1 - y0, z1 - z0),
                    ),
                    "steel",
                )
        for rack in self.model.get("racks", []):
            for part in rack.get("parts", []):
                # columns and the beams of every tier (a lane rests on its beam: touching is
                # not blocked, see blocked_fn)
                solid = part_solid(part, rack["id"])
                if solid is not None:
                    add_(solid, "steel")
        for area in self.model.get("areas", []):
            for part in area.get("parts", []):  # a bund's walls: pipes go over them
                solid = part_solid(part, area["id"])
                if solid is not None:
                    add_(solid, "steel")
        from chemeascode.domains.spatial.zones import volume_solid

        for zone in self.model.get("zones", []):
            if zone["kind"] not in FORBIDDEN_ZONES:
                continue
            for volume in zone["volumes"]:
                solid = volume_solid(volume, zone["id"])
                if zone["kind"] == "escape" and isinstance(solid, Box):
                    x0, y0, z0, x1, y1, _ = solid.aabb
                    top = z0 + self.rules.headroom_walkway_m
                    solid = Box(
                        zone["id"],
                        ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + top) / 2),
                        (x1 - x0, y1 - y0, top - z0),
                    )
                add_(solid, "zone")
        if self.plan is not None:
            from chemeascode.domains.spatial.layout_validate import strip

            h = self.rules.headroom_road_m
            for road in self.plan.roads:
                for k, polygon in enumerate(strip(road.points, road.width)):
                    (ax, ay), (bx, by), (cx, cy), _ = polygon
                    length = math.hypot(bx - ax, by - ay)
                    wide = math.hypot(cx - bx, cy - by)
                    angle = math.degrees(math.atan2(by - ay, bx - ax))
                    centre = ((ax + cx) / 2, (ay + cy) / 2, h / 2 - 0.5)
                    add_(Box(f"{road.id}/{k}", centre, (length, wide, h + 1.0), angle), "road")

    def blocked_fn(
        self, inflate: float, bubbles: list[tuple[Vec, float]], margin: float | None = None
    ):
        """A memoised test whether a point is too close to an obstacle (*inflate* m: the pipe's
        radius, the spacing and half a grid step). Within a bubble ``(centre, radius)`` around an
        end, the fixed obstacles only block where the pipe itself would cut into them (the end
        may lie close to the item its nozzle sits on), zones not at all (a zone the end lies in),
        and the pipes routed before by the spacing without the grid margin; a pipe the end lies
        on (the run a branch leaves) does not block within its radius of the end. *margin* is
        the grid margin inside *inflate* (default half the rules' grid step). ``blocked.edge(p,
        q)`` says whether the straight move between two nodes keeps the spacing from the pipes
        (tested where a node lies in a bubble, since the nodes there have no margin)."""
        memo: dict[tuple[int, int, int], bool] = {}
        exempt = self.exempt
        margin = self.rules.grid_m / 2 if margin is None else margin
        clearance = max(inflate - margin, 0.0)  # pipe radius + spacing
        pipe_r = max(clearance - self.rules.spacing_m, 0.0)

        def in_bubble_at(p: Vec) -> bool:
            return any(dist(p, centre) <= radius for centre, radius in bubbles)

        # the pipes each end lies on (a branch's run, or the pipes meeting at a junction)
        runs = [
            (
                centre,
                {
                    s.id
                    for s, _, _ in self.pipes_index.near((*centre, *centre), 1e-6)
                    if s.distance(centre) < 1e-6
                },
            )
            for centre, _ in bubbles
        ]

        def on_run(solid: Any, p: Vec) -> bool:
            """Whether *solid* belongs to a pipe an end lies on and *p* is within its reach of
            that end."""
            reach = inflate + getattr(solid, "r", 0.0)
            return any(solid.id in ids and dist(p, centre) <= reach for centre, ids in runs)

        def edge(p: Vec, q: Vec) -> bool:
            box = (min(p[0], q[0]), min(p[1], q[1]), min(p[2], q[2]))
            box += (max(p[0], q[0]), max(p[1], q[1]), max(p[2], q[2]))
            for solid, _, _ in self.pipes_index.near(box, clearance):
                if segment_distance(p, q, solid) < clearance - 1e-9 and not (
                    on_run(solid, p) or on_run(solid, q)
                ):
                    return False
            return True

        def blocked(key: tuple[int, int, int], p: Vec) -> bool:
            found = memo.get(key)
            if found is not None:
                return found
            near = [dist(p, centre) for centre, _ in bubbles]
            in_bubble = any(d <= radius for d, (_, radius) in zip(near, bubbles, strict=True))
            box = (p[0], p[1], p[2], p[0], p[1], p[2])
            hit = False
            for solid, _, kind in self.static.near(box, inflate):
                if kind == "stub" and solid.id in exempt:
                    continue
                if kind == "wall" and solid.id in self.wall_exempt:
                    continue
                if in_bubble:
                    if kind in ("zone", "stub", "envelope", "road"):
                        continue
                    if solid.distance(p) < pipe_r - 1e-9:
                        hit = True
                        break
                elif solid.distance(p) < inflate - 1e-9:
                    hit = True
                    break
            if not hit:
                # near an end, pipes block by their real clearance (a lane start next to the
                # lanes routed before stays reachable), elsewhere with the grid margin
                limit = clearance if in_bubble else inflate
                for solid, _, _ in self.pipes_index.near(box, inflate):
                    if solid.distance(p) >= limit - 1e-9:
                        continue
                    if on_run(solid, p):  # the run a branch leaves (or meets)
                        continue
                    hit = True
                    break
            memo[key] = hit
            return hit

        blocked.edge = edge  # type: ignore[attr-defined]
        blocked.in_bubble = in_bubble_at  # type: ignore[attr-defined]
        return blocked

    # -- A* -------------------------------------------------------------------------

    def astar(
        self,
        a: Vec,
        b: Vec,
        r: float,
        grid: float,
        margin: float,
        budget: int = MAX_EXPANSIONS,
    ) -> list[Vec] | None:
        """An orthogonal route from *a* to *b* (see the module text), None when not found
        (``astar_fallback`` then holds a route that reached the goal node but whose way onto
        *b* is tight, if any)."""
        self.astar_fallback = None
        # grown by half a grid step, so the whole edge between two free nodes is clear
        inflate = r + self.rules.spacing_m + grid / 2
        bubble = max(1.5 * grid, inflate + grid / 2)
        blocked = self.blocked_fn(inflate, [(a, bubble), (b, bubble)], grid / 2)
        ox, oy, oz = a

        def point(n: tuple[int, int, int]) -> Vec:
            return (ox + n[0] * grid, oy + n[1] * grid, oz + n[2] * grid)

        goal = (round((b[0] - ox) / grid), round((b[1] - oy) / grid), round((b[2] - oz) / grid))
        lo = (
            math.floor((min(a[0], b[0]) - margin - ox) / grid),
            math.floor((min(a[1], b[1]) - margin - oy) / grid),
            math.ceil((r + 0.1 - oz) / grid),
        )
        hi = (
            math.ceil((max(a[0], b[0]) + margin - ox) / grid),
            math.ceil((max(a[1], b[1]) + margin - oy) / grid),
            math.ceil((max(a[2], b[2]) + margin - oz) / grid),
        )
        lo = (lo[0], lo[1], min(lo[2], 0, goal[2]))
        start = (0, 0, 0)

        def h(n: tuple[int, int, int]) -> float:
            return grid * (abs(n[0] - goal[0]) + abs(n[1] - goal[1]) + abs(n[2] - goal[2]))

        best: dict[tuple[int, int, int], float] = {start: 0.0}
        came: dict[tuple[int, int, int], tuple[tuple[int, int, int], int]] = {}
        Node = tuple[int, int, int]
        heap: list[tuple[float, float, int, Node, int, Node | None]] = [
            (h(start), h(start), 0, start, -1, None)
        ]
        counter = 0
        expanded = 0
        arrivals: set[Node] = set()
        fallback: list[Vec] | None = None
        while heap:
            _, _, _, node, direction, parent = heapq.heappop(heap)
            if node == goal:
                # the goal node only stands for *b* (off the grid): an arrival counts when the
                # way onto *b* from it keeps the spacing; else the next arrival is tried
                path = [parent] if parent is not None else [node]
                while path[-1] in came:
                    path.append(came[path[-1]][0])
                points = [point(n) for n in reversed(path)]
                points[0] = a
                if parent is not None:
                    points.append(point(goal))
                last = points[-1]
                for candidate in (
                    _onto_goal(points, b),
                    [*points, (b[0], last[1], last[2]), (b[0], b[1], last[2]), b],
                ):
                    candidate = simplify(candidate)
                    tail = candidate[max(0, len(candidate) - 5) :]
                    if all(blocked.edge(p, q) for p, q in zip(tail, tail[1:], strict=False)):
                        return candidate
                if fallback is None:
                    fallback = simplify(_onto_goal(points, b))
                if len(arrivals) >= GOAL_ARRIVALS:
                    break
                continue
            expanded += 1
            if expanded > budget:
                break
            cost = best[node]
            for d, (dx, dy, dz) in enumerate(DIRS):
                n = (node[0] + dx, node[1] + dy, node[2] + dz)
                if not (
                    lo[0] <= n[0] <= hi[0] and lo[1] <= n[1] <= hi[1] and lo[2] <= n[2] <= hi[2]
                ):
                    continue
                if n != goal and blocked(n, point(n)):
                    continue
                # the moves near an end keep the spacing from the pipes (the move onto the goal
                # node, which only stands for the goal, is checked with the final approach)
                here, there = point(node), point(n)
                if (
                    n != goal
                    and (blocked.in_bubble(here) or blocked.in_bubble(there))
                    and not blocked.edge(here, there)
                ):
                    continue
                total = cost + grid + (BEND_COST if direction not in (-1, d) else 0.0)
                if n == goal:
                    if node not in arrivals:
                        arrivals.add(node)
                        counter += 1
                        heapq.heappush(heap, (total, 0.0, counter, n, d, node))
                    continue
                if total < best.get(n, math.inf) - 1e-9:
                    best[n] = total
                    came[n] = (node, d)
                    counter += 1
                    hn = h(n)
                    heapq.heappush(heap, (total + hn, hn, counter, n, d, None))
        # no clean way onto the goal: the caller may still take the best one found
        self.astar_fallback = fallback
        return None

    def direct(self, a: Vec, b: Vec, r: float) -> list[Vec]:
        """Up from *a* to an elevation clear of every obstacle between the two ends, across in
        x then y, down to *b*."""
        box = (min(a[0], b[0]), min(a[1], b[1]), 0.0, max(a[0], b[0]), max(a[1], b[1]), 1e3)
        top = max(a[2], b[2])
        inflate = r + self.rules.spacing_m
        for index in (self.static, self.pipes_index):
            for _, aabb, kind in index.near(box, inflate):
                if kind == "road":
                    continue
                top = max(top, aabb[5])
        z = top + inflate + 0.1
        return simplify([a, (a[0], a[1], z), (b[0], a[1], z), (b[0], b[1], z), b])

    def leg(self, a: Vec, b: Vec, r: float) -> tuple[list[Vec], str]:
        """A local leg: A* on the grid, then on a coarser grid, then on a finer one with a
        larger search; then the first A* route whose last step onto *b* is tight; then
        direct."""
        grid = self.rules.grid_m
        tight: tuple[list[Vec], str] | None = None
        for g, margin, method, budget in (
            (grid, MARGIN, "astar", MAX_EXPANSIONS),
            (2 * grid, 2 * MARGIN, "astar_coarse", MAX_EXPANSIONS),
            # narrow corridors (a crowded nozzle cluster, the inside of a frame): half the grid,
            # so the grid margin is smaller, with a larger search
            (grid / 2, MARGIN, "astar_fine", FINE_EXPANSIONS),
        ):
            found = self.astar(a, b, r, g, margin, budget)
            if found is not None:
                return found, method
            if tight is None and self.astar_fallback is not None:
                tight = (self.astar_fallback, method)
        if tight is not None:  # reaches its goal, only the last metre is tight
            return tight
        return self.direct(a, b, r), "direct"

    # -- topology -------------------------------------------------------------------

    def _resolve_nozzle(self, end: Any) -> EndPoint:
        tag = end.tag
        if tag is None:
            return EndPoint("unresolved", reason=f"nozzle {end.ref} belongs to no tagged item")
        if tag not in self.equipment:
            return EndPoint("unresolved", reason=f"{tag} is not placed", label=tag)
        nozzle = self.nozzles.get((tag, end.ref)) or self.nozzles.get((tag, end.name))
        if nozzle is None:
            return EndPoint("unresolved", reason=f"{tag} has no nozzle {end.name} in the model")
        return EndPoint(
            "fixed",
            tuple(nozzle["point"]),
            tuple(nozzle["direction"]),
            owner=tag,
            label=nozzle["id"],
            nozzle=nozzle["id"],
        )

    def _resolve_text(self, text: str, area: str | None, line: str) -> EndPoint:
        """A line list end of a connector without a partner (see the module text)."""
        raw = (text or "").strip()
        word = raw.lower()
        if any(w == word or word.startswith(w + " ") for w in OPEN_WORDS):
            return EndPoint("open", label=raw)
        tag = raw.split("/", 1)[0].split(" ", 1)[0].strip()
        if tag in self.equipment:
            for nozzle in self.equipment[tag]["nozzles"]:
                if line in (nozzle["refs"].get("lines") or []):
                    return EndPoint(
                        "fixed",
                        tuple(nozzle["point"]),
                        tuple(nozzle["direction"]),
                        owner=tag,
                        label=nozzle["id"],
                        nozzle=nozzle["id"],
                    )
            return EndPoint("item", key=tag, owner=tag, label=tag)
        if raw in self.lines and raw != line:
            return EndPoint("line", key=raw, label=f"line {raw}")
        return EndPoint("edge", area=area, label=raw or "BL", key=line)

    def build_chains(self, pins: bool = True) -> list[Chain]:
        """The chains of segments (see the module text); with *pins* False as if no route
        were pinned (:meth:`_virtual_order`)."""
        segs = self.segments
        # off-page connector pairs, by line, in sheet and file order
        outs: dict[str, list[tuple[int, int]]] = {}
        ins: dict[str, list[tuple[int, int]]] = {}
        for i, s in enumerate(segs):
            for side, end in ((0, s.source), (1, s.target)):
                if end.kind == "opc_out":
                    outs.setdefault(s.line, []).append((i, side))
                elif end.kind == "opc_in":
                    ins.setdefault(s.line, []).append((i, side))
        opc_key: dict[tuple[int, int], str] = {}
        for line, found in outs.items():
            free = list(ins.get(line, []))
            for k, pair_out in enumerate(found):
                if _open_connector(segs[pair_out[0]], pair_out[1]):
                    continue
                pair_in = next(
                    (m for m in free if segs[m[0]].sheet != segs[pair_out[0]].sheet), None
                )
                if pair_in is None:
                    continue
                free.remove(pair_in)
                key = f"opc:{line}:{k}"
                opc_key[pair_out] = key
                opc_key[pair_in] = key
        # junctions: key -> [(segment, side, node)]
        attached: dict[str, list[tuple[int, int, int]]] = {}
        item_count: Counter[str] = Counter()
        for s in segs:
            for end in (s.source, s.target):
                if end.kind == "item":
                    item_count[f"{s.sheet}:{end.ref}"] += 1
        ends: dict[tuple[int, int], EndPoint] = {}
        pinned = {i for i, s in enumerate(segs) if pins and self._intent(s, "route") is not None}
        for i, s in enumerate(segs):
            info = self.lines.get(s.line)
            for side, end in ((0, s.source), (1, s.target)):
                key = None
                node = 0
                if end.kind == "item" and end.tag and end.tag in self.equipment:
                    # a component placed in the layout (a relief valve on a structure): the
                    # segments meeting at it end there, each its own chain
                    ends[(i, side)] = EndPoint("item", key=end.tag, owner=end.tag, label=end.tag)
                    continue
                if end.kind == "tee":
                    key, node = f"{s.sheet}:{end.ref}", end.node if end.node is not None else 2
                elif end.kind in ("opc_in", "opc_out") and (i, side) in opc_key:
                    key, node = opc_key[(i, side)], side
                elif end.kind == "item" and item_count[f"{s.sheet}:{end.ref}"] > 1:
                    key, node = f"{s.sheet}:{end.ref}", side
                if key is not None:
                    attached.setdefault(key, []).append((i, side, node))
                    ends[(i, side)] = EndPoint("junction", key=key, label=key)
                    continue
                if end.kind == "nozzle":
                    ends[(i, side)] = self._resolve_nozzle(end)
                elif end.kind in ("opc_in", "opc_out"):
                    if _open_connector(s, side):
                        ends[(i, side)] = EndPoint("open", label=end.ref)
                    elif info is None:
                        ends[(i, side)] = EndPoint(
                            "unresolved",
                            reason=f"connector {end.ref}: line {s.line} is not in the line list",
                        )
                    elif side == 0:
                        ends[(i, side)] = self._resolve_text(info.from_, info.from_area, s.line)
                    else:
                        ends[(i, side)] = self._resolve_text(info.to, info.to_area, s.line)
                elif end.kind == "item":
                    if end.tag and end.tag in self.equipment:
                        ends[(i, side)] = EndPoint(
                            "item", key=end.tag, owner=end.tag, label=end.tag
                        )
                    else:
                        ends[(i, side)] = EndPoint("open", label=end.tag or end.ref)
                elif end.kind == "tee":
                    ends[(i, side)] = EndPoint("unresolved", reason="tee without a node")
                else:
                    ends[(i, side)] = EndPoint("unresolved", reason="the segment ends at nothing")
        # an open end beyond a placed in-line item (a silencer or safety valve placed in the
        # layout): the line ends at that item, where it discharges
        self.end_items: dict[int, dict[str, int]] = {}
        for (i, side), found in list(ends.items()):
            if found.kind != "open":
                continue
            seg_ends = {segs[i].source.ref, segs[i].target.ref}
            items = [item for item in segs[i].items if item.dexpi_id not in seg_ends]
            for item in reversed(items) if side == 1 else items:
                if item.tag and item.tag in self.equipment:
                    ends[(i, side)] = EndPoint("item", key=item.tag, owner=item.tag, label=item.tag)
                    self.end_items.setdefault(i, {})[item.dexpi_id] = side
                    break
        links: dict[tuple[int, int], tuple[int, int]] = {}
        self.branch_of: dict[str, list[tuple[int, int]]] = {}
        for key, members in attached.items():
            ordered = sorted(members, key=lambda m: (m[2], m[0], m[1]))
            usable = [m for m in ordered if m[0] not in pinned]
            # the run through a tee (or a component two segments share) is chosen among all its
            # segments; a pinned one ends its chain there, so the other run segment starts at
            # the pinned end instead of running on into the branch as if it were the run
            run = ordered
            if len(ordered) >= 3:
                run_nodes = [m for m in ordered if m[2] in (0, 1)]
                run = run_nodes[:2] if len(run_nodes) >= 2 else ordered[:2]
            elif len(ordered) == 1:
                run = []
            if any(m[0] in pinned for m in run):
                run = []
            if len(run) == 2:
                (i1, s1, _), (i2, s2, _) = run
                links[(i1, s1)] = (i2, s2)
                links[(i2, s2)] = (i1, s1)
            for m in usable:
                if (m[0], m[1]) not in links:
                    self.branch_of.setdefault(key, []).append((m[0], m[1]))
        self.ends = ends
        self.attached = attached
        chains: list[Chain] = []
        done: set[int] = set()
        order = sorted(range(len(segs)), key=lambda i: (segs[i].sheet, i))
        starts = [i for i in order if (i, 0) not in links or (i, 1) not in links]
        for i in starts + order:
            if i in done:
                continue
            side = 0 if (i, 0) not in links else 1 if (i, 1) not in links else 0
            members: list[tuple[int, bool]] = []
            junctions: list[str | None] = []
            current, entry = i, side
            first_end = ends[(i, side)]
            while True:
                done.add(current)
                members.append((current, entry == 1))
                exit_side = 1 - entry
                nxt = links.get((current, exit_side))
                if nxt is None or nxt[0] in done:
                    last_end = ends[(current, exit_side)]
                    break
                junctions.append(ends[(current, exit_side)].key)
                current, entry = nxt
            dn = max((self._dn(segs[m]) or 0.0) for m, _ in members)
            s0 = segs[members[0][0]]
            chains.append(
                Chain(f"{_stem(s0.sheet)}/{s0.id}", members, first_end, last_end, junctions, dn)
            )
        return chains

    # -- intent and data --------------------------------------------------------------

    def _intent(self, s: Segment, name: str) -> Any:
        # the sheet-qualified id first: a line drawn on two sheets may repeat a segment id
        keys = ((s.line, f"{_stem(s.sheet)}/{s.id}"), (s.line, s.id), (s.line, s.number))
        for key in keys:
            entry = self.intent.get(key)
            if entry is not None and getattr(entry, name) not in (None, []):
                return getattr(entry, name)
        entry = self.intent.get((s.line, None))
        if entry is not None and name != "route":
            value = getattr(entry, name)
            if value not in (None, []):
                return value
        return None

    def _dn(self, s: Segment) -> float | None:
        if s.dn:
            return s.dn
        info = self.lines.get(s.line)
        return info.dn if info else None

    def sizes(self, s: Segment) -> tuple[float, float, float]:
        """``(dn, od, insulation thickness)`` of a segment, m for the last two."""
        dn = self._dn(s) or 50.0
        info = self.lines.get(s.line)
        ins = insulation(info.insulation if info else None, dn, self.specs)
        return dn, outside_diameter(dn), ins.thickness

    # -- routing ----------------------------------------------------------------------

    def area_of(self, p: Vec) -> str | None:
        if self.plan is None:
            return None
        from chemeascode.domains.spatial.layout_distances import area_of

        return area_of(self.plan, (p[0], p[1]))

    def _place(self, end: EndPoint, other: Vec | None, r: float) -> EndPoint | None:
        """*end* with its point, None while it waits for a tee or line not routed yet."""
        if end.kind == "fixed":
            return end
        if end.kind == "junction":
            point = self.junction_points.get(end.key or "")
            return None if point is None else EndPoint("fixed", point, None, label=end.label)
        if end.kind == "line":
            routes = self.line_points.get(end.key or "")
            if not routes:
                return None
            target = other or (0.0, 0.0, 0.0)
            best = min(
                (p for route in routes for p in _samples(route)), key=lambda p: dist(p, target)
            )
            return EndPoint("fixed", best, None, label=end.label)
        if end.kind == "item":
            item = self.equipment[end.key or ""]
            x0, y0, z0, x1, y1, z1 = item["bbox"]
            target = other or ((x0 + x1) / 2, (y0 + y1) / 2, z1)
            point = (
                min(max(target[0], x0), x1),
                min(max(target[1], y0), y1),
                (z0 + z1) / 2,
            )
            return EndPoint("fixed", point, None, owner=end.key, label=end.label)
        if end.kind == "edge":
            if other is None:
                return EndPoint("unresolved", reason=f"{end.label}: no other end to start from")
            line = end.key or ""
            info = self.lines.get(line)
            fluid = info.fluid if info else None
            dn = (info.dn if info else None) or 50.0
            rule = self._battery_limit(line, fluid)
            if rule is not None:
                name = rule.id or (rule.lines or rule.fluids)[0]
                if rule.point is not None:
                    return EndPoint(
                        "fixed",
                        tuple(rule.point),
                        None,
                        label=f"battery limit {name}",
                        basis="battery limit rule",
                    )
                found = self._rack_end(rule.rack, rule.rack_end, other, line, fluid, dn, r)
                if found is not None:
                    found.basis = "battery limit rule"
                    return found
            z = self.rules.headroom_road_m + r + 0.5
            if self.plan is not None and end.area:
                area = next((a for a in self.plan.areas if a.id == end.area), None)
                if area is not None:
                    x0, y0, x1, y1 = area.box
                    inside = x0 <= other[0] <= x1 and y0 <= other[1] <= y1
                    if not inside:
                        p = (min(max(other[0], x0), x1), min(max(other[1], y0), y1), z)
                        return EndPoint("fixed", p, None, label=f"area {area.id}", basis="area")
            if self.plan is None:
                return EndPoint("unresolved", reason=f"{end.label}: no site plan for the edge")
            found = self._rack_end(None, "nearest", other, line, fluid, dn, r)
            if found is not None:
                return found
            w, d = self.plan.site.width, self.plan.site.depth
            x, y = other[0], other[1]
            candidates = [(x, (0.0, y)), (w - x, (w, y)), (y, (x, 0.0)), (d - y, (x, d))]
            _, (px, py) = min(candidates)
            return EndPoint(
                "fixed", (px, py, z), None, label=f"site edge ({end.label})", basis="site edge"
            )
        return end

    def _battery_limit(self, line: str, fluid: str | None) -> Any:
        """The first ``battery_limits`` rule matching *line* (pattern) or *fluid*."""
        for rule in self.rules.battery_limits:
            fluids = {f.strip().lower() for f in rule.fluids}
            if fluid and fluid.strip().lower() in fluids:
                return rule
            for pattern in rule.lines:
                if any(c in pattern for c in "*?["):
                    if fnmatch.fnmatchcase(line, pattern):
                        return rule
                elif line.startswith(pattern):
                    return rule
        return None

    def _rack_end(
        self,
        rack_id: str | None,
        which: str,
        other: Vec,
        line: str,
        fluid: str | None,
        dn: float,
        r: float,
    ) -> EndPoint | None:
        """A battery limit at an end of *rack_id* (any rack: the free end nearest *other*, an
        end inside another rack's strip being a joint, not an end), on the line's tier."""
        if self.plan is None:
            return None
        from chemeascode.domains.spatial.layout_distances import _inside

        candidates = []
        for rack in self.plan.racks:
            if rack_id is not None and rack.id != rack_id:
                continue
            points = [tuple(p) for p in rack.points]
            for label, p in (("start", points[0]), ("end", points[-1])):
                if which in ("start", "end") and label != which:
                    continue
                if rack_id is None and any(
                    _inside(p, polygon)
                    for o in self.plan.racks
                    if o.id != rack.id
                    for polygon in self._strips(o)
                ):
                    continue
                d = math.hypot(p[0] - other[0], p[1] - other[1])
                candidates.append((d, rack.id, label, p, rack))
        if not candidates:
            return None
        _, rid, label, (x, y), rack = min(candidates, key=lambda c: c[:3])
        z = self.tier_for(rack, line, fluid, dn) + r
        return EndPoint(
            "fixed",
            (x, y, z),
            None,
            label=f"battery limit (rack {rid} {label})",
            rack_end=rid,
            basis="battery limit rule" if rack_id is not None else "rack end",
        )

    def _strips(self, rack: Any) -> list[Any]:
        from chemeascode.domains.spatial.layout_validate import strip

        return strip(rack.points, rack.width + 1.0)

    def crossing(self, a: Vec, b: Vec, areas: set[str | None]) -> str | None:
        """Whether the straight plan line from *a* to *b* crosses a road or an area other than
        *areas*: ``crosses a road``, ``crosses another area`` or None."""
        if self.plan is None:
            return None
        from chemeascode.domains.spatial.layout_distances import _inside

        n = max(1, math.ceil(math.hypot(b[0] - a[0], b[1] - a[1])))
        for k in range(1, n):
            p = (a[0] + (b[0] - a[0]) * k / n, a[1] + (b[1] - a[1]) * k / n)
            if any(_inside(p, polygon) for polygon in self.road_polygons):
                return "crosses a road"
            area = self.area_of((p[0], p[1], 0.0))
            if area is not None and area not in areas:
                return "crosses another area"
        return None

    def _crosses_road(self, p: Vec, q: tuple[float, float]) -> bool:
        """Whether the plan line from *p* to *q* crosses a road."""
        from chemeascode.domains.spatial.layout_distances import _inside

        n = max(1, math.ceil(math.hypot(q[0] - p[0], q[1] - p[1])))
        for k in range(1, n):
            x = p[0] + (q[0] - p[0]) * k / n
            y = p[1] + (q[1] - p[1]) * k / n
            if any(_inside((x, y), polygon) for polygon in self.road_polygons):
                return True
        return False

    def riser(self, p: Vec, z: float, r: float, toward: Vec) -> Vec:
        """A free point at elevation *z* near *p*: straight above or below it, else stepped out
        (toward *toward* first) until clear of the obstacles."""
        grid = self.rules.grid_m
        inflate = r + self.rules.spacing_m + grid / 2
        blocked = self.blocked_fn(inflate, [])
        dx, dy = toward[0] - p[0], toward[1] - p[1]
        first = (1 if dx > 0 else -1, 0) if abs(dx) >= abs(dy) else (0, 1 if dy > 0 else -1)
        order = [first, (-first[0], -first[1]), (first[1], first[0]), (-first[1], -first[0])]
        candidate = (p[0], p[1], z)
        if not blocked((0, 0, 0), candidate):
            return candidate
        for k in range(1, 13):
            for ux, uy in order:
                q = (p[0] + ux * k * grid, p[1] + uy * k * grid, z)
                if not blocked((ux * k, uy * k, 0), q):
                    return q
        return candidate

    def through(self, points: list[Vec], r: float) -> tuple[list[Vec], set[str]]:
        """Local legs through *points* in turn: the route and the leg methods."""
        route, methods = [points[0]], set()
        for target in points[1:]:
            if dist(route[-1], target) < 1e-9:
                continue
            piece, m = self.leg(route[-1], target, r)
            route += piece[1:]
            methods.add(m)
        return route, methods

    def local(self, a: Vec, b: Vec, r: float, z: float) -> tuple[list[Vec], str]:
        """A local route at the pipe-way elevation *z*: up (or down) near *a*, across, down
        near *b*."""
        ra, rb = self.riser(a, z, r, b), self.riser(b, z, r, a)
        route, methods = self.through([a, ra, rb, b], r)
        return simplify(route), _combine("", methods)

    def _stub(self, end: EndPoint, od: float, toward: Vec | None = None) -> list[Vec]:
        """The nozzle and the end of its stub (one point without a direction), out of the
        item's outline when the stub ends under or inside it (:meth:`_exit`)."""
        assert end.point is not None
        if end.direction is None:
            return [end.point]
        length = max(2 * od, 0.3)
        tip = add(end.point, scale(end.direction, length))
        floor = od / 2 + 0.1
        if tip[2] < floor:  # a bottom nozzle near grade: no deeper than the floor clearance
            drop = max(0.0, end.point[2] - floor)
            tip = (end.point[0], end.point[1], end.point[2] - drop)
        stub = simplify([end.point, tip])
        exit_ = self._exit(end.owner, tip, od, toward)
        return stub + [exit_] if exit_ is not None else stub

    def _exit(self, owner: str | None, tip: Vec, od: float, toward: Vec | None) -> Vec | None:
        """Where a stub ending under or inside its own item (a bottom nozzle under a horizontal
        drum or inside a skirt) leaves the item's plan outline: straight out to the nearest side
        (toward *toward* when two are as near), clear by the pipe's radius and spacing; None when
        the tip is outside the outline."""
        item = self.equipment.get(owner or "")
        if item is None:
            return None
        x0, y0, z0, x1, y1, z1 = item["bbox"]
        x, y, z = tip
        if not (x0 < x < x1 and y0 < y < y1 and z0 <= z < z1):
            return None
        clear = od / 2 + self.rules.spacing_m + self.rules.grid_m
        options = [
            (x - x0, (x0 - clear, y, z)),
            (x1 - x, (x1 + clear, y, z)),
            (y - y0, (x, y0 - clear, z)),
            (y1 - y, (x, y1 + clear, z)),
        ]
        target = toward or tip
        options.sort(key=lambda o: (round(o[0], 3), dist(o[1], target)))
        return options[0][1]

    def vent_rule(self, segs: list[Segment]) -> Any:
        """The first ``vents`` rule of ``routing.yaml`` matching the line of *segs*."""
        line = segs[0].line.strip()
        info = self.lines.get(line)
        fluid = (info.fluid if info is not None else None) or segs[0].fluid
        for rule in self.rules.vents:
            fluids = {f.strip().lower() for f in rule.fluids}
            if (fluid and fluid.strip().lower() in fluids) or any(
                fnmatch.fnmatchcase(line, p if any(c in p for c in "*?[") else p + "*")
                for p in rule.lines
            ):
                return rule
        return None

    def vent_rise(self, segs: list[Segment], tip: Vec) -> float:
        """How far an open end rises above its stub's *tip*: ``vent_rise_m``; for a line a
        ``vents`` rule matches, its ``rise_m``, raised until the zone sphere around the outlet
        clears the walking levels (:func:`floors.clear_height`), at most its ``max_rise_m``."""
        rule = self.vent_rule(segs)
        if rule is None:
            return self.rules.vent_rise_m
        rise = rule.rise_m if rule.rise_m is not None else self.rules.vent_rise_m
        radius = rule.radius_m
        if radius is None:
            radius = self.vent_radii.get(segs[0].line.strip())
        if radius:
            from chemeascode.domains.spatial.floors import clear_height, walking_levels

            if self._floors is None:
                self._floors = walking_levels(self.model)
            top = (tip[0], tip[1], tip[2] + rise)
            z = clear_height(top, radius, self._floors, self.rules.headroom_walkway_m)
            rise = max(rise, math.ceil((z - tip[2]) * 10 - 1e-6) / 10)
        return min(rise, rule.max_rise_m)

    def _open_route(
        self, stub: list[Vec], fixed: EndPoint, r: float, rise: float = OPEN_RISE
    ) -> list[Vec]:
        """A vent or relief end: the stub, then a riser *rise* above its tip (default
        :data:`OPEN_RISE`, else :meth:`vent_rise`); when that riser would cut a pipe routed
        before or steel, the tip first steps sideways (away from the item) until the riser is
        clear."""
        tip = stub[-1]
        upward = fixed.direction is not None and fixed.direction[2] > 0.7
        inflate = r + self.rules.spacing_m
        # the line the vent or relief valve sits on (its outlet leaves from a point on it)
        run = {
            s.id
            for s, _, _ in self.pipes_index.near((*stub[0], *stub[0]), 1e-6)
            if s.distance(stub[0]) < 1e-6
        }

        def clear(a: Vec, b: Vec) -> bool:
            box = (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]))
            box += (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))
            for index, kinds in ((self.pipes_index, None), (self.static, ("steel",))):
                for solid, _, kind in index.near(box, inflate):
                    if kinds is not None and kind not in kinds:
                        continue
                    if kinds is None and solid.id in run:
                        continue
                    if segment_distance(a, b, solid) < inflate - 1e-6:
                        return False
            return True

        top = add(tip, (0.0, 0.0, rise))
        if clear(tip, top):
            route = [stub[0], top] if upward else [*stub, top]
            return simplify(route)
        out = fixed.direction if fixed.direction is not None and not upward else (1.0, 0.0, 0.0)
        flat = (out[0], out[1], 0.0)
        norm = math.hypot(flat[0], flat[1]) or 1.0
        flat = (flat[0] / norm, flat[1] / norm, 0.0)
        sides = [flat, (-flat[1], flat[0], 0.0), (flat[1], -flat[0], 0.0)]
        for k in range(1, 9):
            for d in sides:
                step = add(tip, scale(d, k * self.rules.grid_m))
                riser = add(step, (0.0, 0.0, rise))
                if clear(tip, step) and clear(step, riser):
                    return simplify([*stub, step, riser])
        return simplify([*stub, top])

    def tier_for(self, rack: Any, line: str, fluid: str | None, dn: float) -> float:
        levels = sorted(rack.levels)
        for tier in self.rules.tiers:
            if tier.rack not in (None, rack.id):
                continue
            fluids = {f.strip().lower() for f in tier.fluids}
            if (fluid and fluid.strip().lower() in fluids) or any(
                line.startswith(prefix) for prefix in tier.lines
            ):
                return tier.elevation
        if not levels:
            return self.rules.headroom_road_m
        return levels[0] if dn >= 300 else levels[-1]

    def lane(
        self,
        rack: Any,
        tier: float,
        width: float,
        span: tuple[float, float] = (0.0, math.inf),
        side: int = 0,
        avoid: tuple[tuple[float, float], ...] = (),
    ) -> float | None:
        """A lane *width* wide on *rack* at *tier* over the arc *span* along the rack: its
        offset from the centreline (left of the rack's drawn direction positive), taken from
        the edges inward (on *side*, +1 left or -1 right, the side the line comes from; else
        the side used less), free of the lanes of the pipes routed before where their spans
        overlap (a lane is shared along the rack) and of the offsets in *avoid*; None when
        full."""
        taken = self.lanes.setdefault((rack.id, tier), [])
        s0, s1 = span
        busy = [(lo, hi) for lo, hi, a, b in taken if a < s1 + LANE_GAP and b > s0 - LANE_GAP]
        busy += list(avoid)
        half = rack.width / 2
        eps = 1e-9

        def free(lo: float, hi: float) -> bool:
            return (
                lo >= -half - eps
                and hi <= half + eps
                and all(hi <= b_lo + eps or lo >= b_hi - eps for b_lo, b_hi in busy)
            )

        # the centre on the millimetre, as the route is written (rounded away from the edge or
        # lane it is placed against): a pinned copy of the route takes back exactly this lane
        # (:meth:`_pin_lanes`), so pinning a route moves no other line
        def from_left() -> tuple[float, float] | None:
            for top in sorted({half, *(lo for lo, _ in busy)}, reverse=True):
                centre = math.floor((top - width / 2) * 1000 + 1e-6) / 1000
                if free(centre - width / 2, centre + width / 2):
                    return (centre - width / 2, centre + width / 2)
            return None

        def from_right() -> tuple[float, float] | None:
            for bottom in sorted({-half, *(hi for _, hi in busy)}):
                centre = math.ceil((bottom + width / 2) * 1000 - 1e-6) / 1000
                if free(centre - width / 2, centre + width / 2):
                    return (centre - width / 2, centre + width / 2)
            return None

        left = sum(hi - lo for lo, hi in busy if lo + hi > 0)
        right = sum(hi - lo for lo, hi in busy if lo + hi <= 0)
        if side:
            order = (from_left, from_right) if side > 0 else (from_right, from_left)
        else:
            order = (from_left, from_right) if left <= right else (from_right, from_left)
        for fit in order:
            found = fit()
            if found is not None:
                centre = round((found[0] + found[1]) / 2, 3)
                taken.append(_lane_entry(centre, width, s0, s1))
                return centre
        return None

    def _clear(self, run: list[Vec], r: float) -> bool:
        """Whether the polyline *run* (a lane on a rack) keeps its spacing from every pipe
        routed so far."""
        inflate = r + self.rules.spacing_m
        for a, b in zip(run, run[1:], strict=False):
            box = (
                min(a[0], b[0]),
                min(a[1], b[1]),
                min(a[2], b[2]),
                max(a[0], b[0]),
                max(a[1], b[1]),
                max(a[2], b[2]),
            )
            for solid, _, _ in self.pipes_index.near(box, inflate):
                if segment_distance(a, b, solid) < inflate - 1e-6:
                    return False
        return True

    def _release(self, rack: Any, tier: float, offset: float, span: tuple[float, float]) -> None:
        """Give back the lane at *offset* that :meth:`lane` just took."""
        taken = self.lanes.get((rack.id, tier), [])
        for k in range(len(taken) - 1, -1, -1):
            lo, hi, a, b = taken[k]
            if abs((lo + hi) / 2 - offset) < 1e-9 and (a, b) == _lane_entry(0, 0, *span)[2:]:
                del taken[k]
                return

    def _passing(self, rack: Any, tier: float, r: float) -> float:
        """The elevation a pipe of radius *r* reaches its lane on *tier* from: above the top
        tier, else under the tier's steel."""
        levels = sorted(rack.levels) or [tier]
        if tier >= levels[-1] - 1e-9:
            return tier + r + 2 * r + self.rules.grid_m + 0.3
        return max(tier - RACK_BEAM_DEPTH - r - self.rules.spacing_m - self.rules.grid_m, r + 0.3)

    def _between_bents(self, rack: Any, tier: float, s: float, r: float) -> float:
        """Arc *s* along *rack*, moved off its bents where a line rises (or drops) through the
        tiers to *tier* (also onto the top tier, which it reaches past the beams below)."""
        levels = sorted(rack.levels)
        if not levels:
            return s
        from chemeascode.domains.spatial.structures import rack_stations

        points = [tuple(p) for p in rack.points]
        total = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
        bents, mids = rack_stations(rack, self.rules.rack_bent_spacing_m)
        clear = RACK_BEAM_WIDTH / 2 + r + self.rules.spacing_m + 0.05
        for station in sorted([*bents, *mids]):
            if abs(s - station) < clear:
                up, down = station + clear, station - clear
                if up > total:
                    return max(down, 0.0)
                if down < 0:
                    return up
                return up if s >= station else down
        return s

    def rack_route(
        self,
        a: Vec,
        b: Vec,
        r: float,
        seg: Segment,
        dn: float,
        explicit: Any,
        ends: tuple[str | None, str | None] = (None, None),
    ) -> tuple[list[Vec], str, dict[str, Any]] | None:
        """Up near *a* above the rack tier, across onto the rack's nearest point, along the
        racks in a lane, off at the point nearest *b* and down near it; None without a rack in
        reach that carries it. An end that is a battery limit at a rack end (*ends*: the rack
        id of each) stops at the end of its lane."""
        if self.plan is None or not self.plan.racks:
            return None
        from chemeascode.domains.spatial.layout_distances import RackNetwork, offset_polyline

        network = getattr(self, "_network", None)
        if network is None:
            network = self._network = RackNetwork(list(self.plan.racks))
        reach = rack_reach(self.plan, self.rules)
        racks = {rack.id: rack for rack in self.plan.racks}
        wanted = self._intent(seg, "rack") or ends[0] or ends[1]
        self.rack_why = "no rack in reach"
        options = []
        short = 0
        for ra in racks:
            da, pa_, sa = network.project(ra, (a[0], a[1]))
            if da > reach:
                continue
            for rb in racks:
                db, pb_, sb = network.project(rb, (b[0], b[1]))
                if db > reach:
                    continue
                length = network.path_length(ra, sa, rb, sb)
                if length is None:
                    continue
                if length < max(racks[ra].width, racks[rb].width) and not any(ends):
                    short += 1  # touches the racks only where they cross: no rack run
                    continue
                bonus = 0.0 if not wanted or wanted in (ra, rb) else 1e6
                # to and from the rack orthogonally, and a little for each change of rack
                off = abs(a[0] - pa_[0]) + abs(a[1] - pa_[1]) + abs(b[0] - pb_[0])
                off += abs(b[1] - pb_[1])
                change = 0.0 if ra == rb else RACK_CHANGE_COST
                # the way to and from the rack does not cross a road (racks carry the lines
                # over the roads)
                road = sum(
                    ROAD_CROSSING_COST
                    for end, at in ((a, pa_), (b, pb_))
                    if self._crosses_road(end, at)
                )
                total = OFF_RACK_WEIGHT * off + length + change + road + bonus
                options.append((total, ra, sa, rb, sb))
        if not options:
            if short:
                self.rack_why = "rack run too short"
            return None
        _, ra, sa, rb, sb = min(options)
        fluid = seg.fluid or (self.lines[seg.line].fluid if seg.line in self.lines else None)

        def tier_of(rack: Any) -> float:
            return explicit if explicit is not None else self.tier_for(rack, seg.line, fluid, dn)

        # a line that comes up onto a tier from below does so between the bents
        if ends[0] is None:
            sa = self._between_bents(racks[ra], tier_of(racks[ra]), sa, r)
        if ends[1] is None:
            sb = self._between_bents(racks[rb], tier_of(racks[rb]), sb, r)
        legs = network.path(ra, sa, rb, sb)
        assert legs is not None
        # a leg shorter than its rack is wide (the line touches a rack only at a joint) is no
        # run on that rack: the line goes straight onto the next one
        if len(legs) > 1:
            kept = [
                leg
                for leg in legs
                if _plan_length(leg[1]) >= max(racks[leg[0]].width, 1.0) or leg is legs[-1]
            ]
            legs = []
            for rack_id, polyline in kept:  # what remains of one rack is one leg again
                if legs and legs[-1][0] == rack_id:
                    legs[-1] = (rack_id, legs[-1][1] + polyline[1:])
                else:
                    legs.append((rack_id, polyline))
        width = 2 * r + self.rules.spacing_m
        points: list[Vec] = []
        used_racks, tiers = [], []
        hop_methods: set[str] = set()
        for k, (rack_id, polyline) in enumerate(legs):
            rack = racks[rack_id]
            side = 0
            if k == 0 and ends[0] is None:
                side = _side(network.points[rack_id], a)
            elif k == len(legs) - 1 and ends[1] is None:
                side = _side(network.points[rack_id], b)
            centre = network.points[rack_id]
            arcs = sorted(_polyline_arc(centre, p) for p in (polyline[0], polyline[-1]))
            span = (arcs[0], arcs[1])
            direction = _same_direction(network.points[rack_id], polyline)
            first = tier_of(rack)
            run: list[Vec] = []
            tier = first
            # the wanted tier first, then the others; on each, the lanes from the edge inward
            # until one is clear of the pipes routed before (their risers and crossings)
            for candidate in [first, *(lv for lv in sorted(rack.levels) if lv != first)]:
                avoid: list[tuple[float, float]] = []
                for _ in range(LANE_TRIES):
                    offset = self.lane(rack, candidate, width, span, side, tuple(avoid))
                    if offset is None:
                        break
                    shifted = offset_polyline(polyline, offset if direction else -offset)
                    trial = [(x, y, candidate + r) for x, y in shifted]
                    if self._clear(trial, r):
                        run, tier = trial, candidate
                        break
                    self._release(rack, candidate, offset, span)
                    avoid.append((offset - width / 2, offset + width / 2))
                if run:
                    break
            if not run:  # every lane crosses a pipe: the first free lane, wanted tier first
                offset, tier = None, first
                for candidate in [first, *(lv for lv in sorted(rack.levels) if lv != first)]:
                    offset = self.lane(rack, candidate, width, span, side)
                    if offset is not None:
                        tier = candidate
                        break
                shifted = offset_polyline(polyline, (offset or 0.0) * (1 if direction else -1))
                run = [(x, y, tier + r) for x, y in shifted]
            if points:
                # from one rack onto the next past the lanes of both (over the top tier, under
                # the others), around the pipes routed before
                last = points[-1]
                hop = self._passing(racks[used_racks[-1]], tiers[-1], r)
                if hop > last[2]:
                    hop = max(hop, self._passing(rack, tier, r))
                piece, m = self.through([last, (last[0], last[1], hop), run[0]], r)
                hop_methods.update(m)
                points += piece[1:-1]
            points += run
            used_racks.append(rack_id)
            tiers.append(tier)
        # rise (or drop) near each end to the passing elevation of the tier (above the top tier,
        # under the others), across to the lane and onto it, so the lane is reached past the
        # lanes of the pipes before
        z_in = self._passing(racks[used_racks[0]], tiers[0], r)
        z_out = self._passing(racks[used_racks[-1]], tiers[-1], r)
        above_in = (points[0][0], points[0][1], z_in)
        above_out = (points[-1][0], points[-1][1], z_out)
        methods: set[str] = set(hop_methods)
        up: list[Vec] = [points[0]]
        # onto and off the lane straight from or to the passing elevation above (or below) it
        # where that point is free, so the line does not cross the tier's other lanes at their
        # height; from the riser's top across by A* (the passing elevation is shared by every
        # line of the tier, so the cross-over goes around the lines routed before)
        free = self.blocked_fn(r + self.rules.spacing_m + self.rules.grid_m / 2, [])
        if ends[0] is None:
            riser = self.riser(a, above_in[2], r, above_in)
            via = [above_in] if not free((0, 0, 1), above_in) else []
            up, m = self.through([a, riser, *via, points[0]], r)
            methods |= m
        down: list[Vec] = [points[-1]]
        if ends[1] is None:
            riser = self.riser(b, above_out[2], r, above_out)
            via = [above_out] if not free((0, 0, 2), above_out) else []
            down, m = self.through([points[-1], *via, riser, b], r)
            methods |= m
        method = _combine("rack", methods)
        route = simplify(up[:-1] + points + down[1:])
        extra = {
            "racks": list(dict.fromkeys(used_racks)),
            "tier": tiers[0],
            "on_rack": list(points),
            "lane_z": [tier + r for tier in tiers],
        }
        return route, method, extra

    def route_chain(self, chain: Chain) -> bool:
        """Route *chain*; False while it waits for a tee or line not routed yet."""
        saved = {key: list(taken) for key, taken in self.lanes.items()}
        segs = [self.segments[i] for i, _ in chain.segments]
        for s in segs:
            reason = self._intent(s, "skip")
            if reason:
                for t in segs:
                    self.unrouted(t, f"skipped: {reason}")
                return True
        sizes = [self.sizes(s) for s in segs]
        r = max(od / 2 + ins for _, od, ins in sizes)
        od_max = max(od for _, od, _ in sizes)
        start, end = chain.start, chain.end
        if start.kind == "unresolved" or end.kind == "unresolved":
            why = start.reason if start.kind == "unresolved" else end.reason
            for s in segs:
                self.unrouted(s, why)
            return True
        if start.kind == "open" and end.kind == "open":
            for s in segs:
                self.unrouted(s, "both ends are open (no nozzle, tee or placed item)")
            return True

        def place(e: EndPoint, other: EndPoint | None) -> EndPoint | None:
            if e.kind == "open":
                return e
            point = other.point if other is not None and other.kind == "fixed" else None
            return self._place(e, point, r)

        a = place(start, None) if start.kind != "edge" else None
        b = place(end, a) if end.kind != "edge" else None
        if start.kind == "edge":
            a = place(start, b)
        if end.kind == "edge":
            b = place(end, a)
        if a is not None and b is not None and start.kind == "item" and b.kind == "fixed":
            a = place(start, b)
        if a is None or b is None:
            return False
        self.exempt = {e.nozzle for e in (a, b) if e.nozzle}
        # a line with an end inside an enclosure or building passes its walls
        self.wall_exempt = {
            oid
            for oid, (x0, y0, x1, y1) in self.enclosures.items()
            for e in (a, b)
            if e.point is not None and x0 <= e.point[0] <= x1 and y0 <= e.point[1] <= y1
        }
        for e in (a, b):
            if e.kind == "unresolved":
                for s in segs:
                    self.unrouted(s, e.reason)
                return True
        open_ends: list[str] = []
        method = "astar"
        reason = ""
        extra: dict[str, Any] = {}
        if a.kind == "open" or b.kind == "open":
            flip = a.kind == "open"
            fixed = b if flip else a
            stub = self._stub(fixed, od_max)
            route = self._open_route(stub, fixed, r, self.vent_rise(segs, stub[-1]))
            if flip:
                route = route[::-1]
            open_ends = ["start" if flip else "end"]
            method = "open"
            reason = "open end"
        else:
            assert a.point is not None and b.point is not None
            sa, sb = self._stub(a, od_max, b.point), self._stub(b, od_max, a.point)
            pa, pb = sa[-1], sb[-1]
            vias = []
            elevation = None
            explicit_tier = None
            for s in segs:
                vias += [tuple(v) for v in (self._intent(s, "via") or [])]
                elevation = elevation if elevation is not None else self._intent(s, "elevation")
                explicit_tier = (
                    explicit_tier if explicit_tier is not None else self._intent(s, "tier")
                )
            vias = list(dict.fromkeys(vias))
            if elevation is not None:
                vias = [(pa[0], pa[1], elevation), *vias, (pb[0], pb[1], elevation)]
            middle: list[Vec] | None = None
            if vias:
                middle, methods = [pa], set()
                for target in [*vias, pb]:
                    piece, m = self.leg(middle[-1], target, r)
                    middle += piece[1:]
                    methods.add(m)
                method = (
                    "via"
                    if methods <= {"astar"}
                    else "via+" + "+".join(sorted(methods - {"astar"}))
                )
                reason = "intent: elevation" if elevation is not None else "intent: via"
            else:
                middle, method, extra, reason = self.choose(
                    pa, pb, a, b, r, segs, chain, explicit_tier
                )
                middle = self._unhairpin(middle, r, extra)
            route = simplify(sa[:-1] + middle + list(reversed(sb[:-1])))
        extra = {**extra, "reason": reason}
        planned, junctions = self._plan(chain, segs, sizes, route, extra, open_ends)
        hits = self._near_deferred(
            [(points, od / 2 + ins) for _, points, _, od, ins, *_ in planned]
        )
        if hits:  # too close to a pinned pipe not yet in the way: route again with it there
            self.lanes = saved
            # one at a time, the latest in the order first (it is the least likely to have
            # been routed around this chain)
            first = max(hits, key=lambda h: h[0])[1]
            self._activate(lambda _, capsules: capsules is first)
            return self.route_chain(chain)
        self.methods[method] += 1
        self.reasons[reason] += 1
        for e in (a, b):
            if e.basis:
                self.limits[e.basis] += 1
        for key, point in junctions:
            self.junction_points.setdefault(key, point)
        for s, points, dn, od, ins, mine, ends in planned:
            self._pipe(s, points, dn, od, ins, method, mine, ends, "generated")
        # junction keys at the chain's ends: a pinned neighbour or a junction this chain reaches
        for end_, point in ((start, route[0]), (end, route[-1])):
            if end_.kind == "junction" and end_.key:
                self.junction_points.setdefault(end_.key, point)
        return True

    def _unhairpin(self, points: list[Vec], r: float, extra: dict[str, Any]) -> list[Vec]:
        """*points* without the U-turns that double back under (or over) themselves: a run
        along one direction, a riser and a run straight back (a lane run past the point where
        the line drops off the rack, then back below it) becomes the shorter run and the riser
        where the two overlap, wherever that riser keeps its spacing from every obstacle and
        pipe; the rack points in *extra* (``on_rack``) follow the moved point."""
        pts = list(points)
        changed = True
        while changed:
            changed = False
            for i in range(len(pts) - 3):
                p0, p1, p2, p3 = pts[i : i + 4]
                h1, v, h2 = sub(p1, p0), sub(p2, p1), sub(p3, p2)
                if abs(h1[2]) > 1e-9 or abs(h2[2]) > 1e-9 or math.hypot(v[0], v[1]) > 1e-9:
                    continue
                a, b = math.hypot(h1[0], h1[1]), math.hypot(h2[0], h2[1])
                if a < 1e-9 or b < 1e-9 or abs(v[2]) < 1e-9:
                    continue
                if (h1[0] * h2[0] + h1[1] * h2[1]) / (a * b) > -1 + 1e-9:
                    continue
                if b <= a:  # the riser moves back along the first run to the end of the second
                    q = (p1[0] + h2[0], p1[1] + h2[1], p1[2])
                    leg, moved = (q, p3), p1
                else:  # the riser moves to the start of the first run
                    q = (p0[0], p0[1], p2[2])
                    leg, moved = (p0, q), p2
                if not self._free_leg(leg[0], leg[1], r):
                    continue
                pts = simplify([*pts[: i + 1], q, p3, *pts[i + 4 :]])
                if extra.get("on_rack"):
                    extra["on_rack"] = [q if p == moved else p for p in extra["on_rack"]]
                changed = True
                break
        return pts

    def _free_leg(self, a: Vec, b: Vec, r: float) -> bool:
        """Whether the straight leg *a*-*b* of a pipe of radius *r* keeps ``spacing_m`` from
        every fixed obstacle (but the stubs and walls this chain may pass) and every pipe
        routed so far."""
        inflate = r + self.rules.spacing_m
        box = (min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]))
        box += (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))
        for solid, _, kind in self.static.near(box, inflate):
            if kind == "stub" and solid.id in self.exempt:
                continue
            if kind == "wall" and solid.id in self.wall_exempt:
                continue
            if segment_distance(a, b, solid) < inflate - 1e-9:
                return False
        return self._clear([a, b], r)

    def choose(
        self,
        pa: Vec,
        pb: Vec,
        a: EndPoint,
        b: EndPoint,
        r: float,
        segs: list[Segment],
        chain: Chain,
        explicit_tier: Any,
    ) -> tuple[list[Vec], str, dict[str, Any], str]:
        """Rack or local, and why: ``(route, method, extra, reason)`` (see the module text)."""
        rules = self.rules
        distance = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
        area_a, area_b = self.area_of(pa), self.area_of(pb)
        wants: list[str] = []
        if a.rack_end or b.rack_end:
            wants.append("battery limit at a rack end")
        if self._intent(segs[0], "rack") is not None or explicit_tier is not None:
            wants.append("intent")
        if None not in (area_a, area_b) and area_a != area_b:
            wants.append("across areas")
        crossing = self.crossing(pa, pb, {area_a, area_b})
        if crossing:
            wants.append(crossing)
        if distance > rules.local_max_m:
            wants.append("longer than local_max_m")
        fallback = ""
        if wants:
            found = self.rack_route(
                pa, pb, r, segs[0], chain.dn, explicit_tier, (a.rack_end, b.rack_end)
            )
            if found is None:
                fallback = self.rack_why
            elif wants == ["longer than local_max_m"] and polyline_length(
                found[0]
            ) > rules.rack_detour_factor * (abs(pa[0] - pb[0]) + abs(pa[1] - pb[1]) + 1.0):
                fallback = "rack detour too long"
            else:
                route, method, extra = found
                return route, method, extra, f"rack: {wants[0]}"
        owners = {a.owner, b.owner} - {None}
        pump = any(self.equipment[o].get("family") == "pump" for o in owners if o in self.equipment)
        z = rules.local_elevation_m + r
        if fallback:
            route, method = self.local(pa, pb, r, z)
            return route, method, {}, f"local: {fallback}"
        if distance <= rules.grade_max_m:
            route, method = self.leg(pa, pb, r)
            return route, method, {}, "local: short run"
        if pump:
            route, method = self.leg(pa, pb, r)
            return route, method, {}, "local: pump run at grade"
        if min(pa[2], pb[2]) >= z:
            route, method = self.leg(pa, pb, r)
            return route, method, {}, "local: above the pipe-way"
        route, method = self.local(pa, pb, r, z)
        return route, method, {}, "local: pipe-way"

    def _plan(
        self,
        chain: Chain,
        segs: list[Segment],
        sizes: list[tuple[float, float, float]],
        route: list[Vec],
        extra: dict[str, Any],
        open_ends: list[str],
    ) -> tuple[list[tuple[Any, ...]], list[tuple[str, Vec]]]:
        """Split *route* at the chain's junctions into one pipe per segment: ``(segment,
        points, dn, od, insulation, extra, open ends)`` each, and the junction points ``(key,
        point)`` along it."""
        total = polyline_length(route)
        n = len(segs)
        cuts = self._cuts(chain, route, total)
        pieces = []
        rest = route
        done = 0.0
        for cut in cuts:
            before, rest = split_at(rest, cut - done)
            done = cut
            pieces.append(before)
        pieces.append(rest)
        junctions = []
        for cut, key in zip(cuts, chain.junctions, strict=True):
            point, _ = point_at(route, cut)
            if key:
                junctions.append((key, point))
        if extra.get("on_rack") and len(pieces) > 1:
            pieces = _flat_bottom(pieces, sizes, extra["on_rack"], extra.get("lane_z", []))
        planned = []
        for k, (s, piece) in enumerate(zip(segs, pieces, strict=True)):
            reversed_ = chain.segments[k][1]
            points = piece[::-1] if reversed_ else piece
            dn, od, ins = sizes[k]
            ends = []
            if "start" in open_ends and k == 0:
                ends.append("end" if reversed_ else "start")
            if "end" in open_ends and k == n - 1:
                ends.append("start" if reversed_ else "end")
            mine = extra
            if extra.get("on_rack"):
                # only a segment that runs along the rack is on it
                rack_points = set(extra["on_rack"])
                runs = [
                    a
                    for a, b in zip(points, points[1:], strict=False)
                    if (a in rack_points or b in rack_points)
                    and abs(a[2] - b[2]) < 1e-6
                    and dist(a, b) > 1.0
                ]
                mine = extra if runs else {"reason": extra.get("reason")}
            planned.append((s, points, dn, od, ins, mine, sorted(ends)))
        return planned, junctions

    def _cuts(self, chain: Chain, route: list[Vec], total: float) -> list[float]:
        """Arc lengths of the junctions along *route*: near where a branch from the junction is
        going, else spread evenly; increasing, at least a little apart."""
        n = len(chain.junctions)
        if n == 0:
            return []
        wanted: list[float | None] = []
        for key in chain.junctions:
            pinned = self.junction_points.get(key or "")
            if pinned is not None:  # a pinned branch starts there: the tee where it meets
                wanted.append(_arc_nearest(route, pinned))
                continue
            target = self._branch_target(key)
            if target is None:
                wanted.append(None)
                continue
            wanted.append(_project(route, target))
        known = [(0.0, 0.0)] + [(i + 1, w) for i, w in enumerate(wanted) if w is not None]
        known.append((n + 1, total))
        filled = []
        for i, w in enumerate(wanted):
            if w is not None:
                filled.append(w)
                continue
            lo = max((k for k in known if k[0] <= i), key=lambda k: k[0])
            hi = min((k for k in known if k[0] >= i + 2), key=lambda k: k[0])
            t = (i + 1 - lo[0]) / (hi[0] - lo[0])
            filled.append(lo[1] + (hi[1] - lo[1]) * t)
        gap = min(JUNCTION_GAP, total / (n + 1))
        for i in range(n):
            low = (filled[i - 1] if i else 0.0) + gap
            filled[i] = max(filled[i], low)
        for i in range(n - 1, -1, -1):
            high = (filled[i + 1] if i + 1 < n else total) - gap
            filled[i] = max(0.0, min(filled[i], high))
        return filled

    def _branch_target(self, key: str | None) -> Vec | None:
        """Where the branch leaving junction *key* goes: the far end of its chain (through the
        connector pairs and components it continues over) where that is a fixed point, else
        the far end of its first segment."""
        if key is None:
            return None
        for i, side in self.branch_of.get(key, []):
            chain = self.chain_of.get(i)
            if chain is not None:
                for near, far in ((chain.start, chain.end), (chain.end, chain.start)):
                    if (
                        near.kind == "junction"
                        and near.key == key
                        and far.kind == "fixed"
                        and far.point is not None
                    ):
                        return far.point
            other = self.ends.get((i, 1 - side))
            if other is not None and other.kind == "fixed" and other.point is not None:
                return other.point
        return None

    @staticmethod
    def _end_ref(end: EndPoint) -> dict[str, Any]:
        """What a pipe's end connects to (``ModelPipeEnd``)."""
        if end.nozzle:
            return {"kind": "nozzle", "ref": end.nozzle}
        if end.kind == "junction":
            return {"kind": "junction", "ref": end.key}
        if end.kind == "open":
            return {"kind": "open"}
        if end.kind == "item":
            return {"kind": "item", "ref": end.key}
        if end.kind == "line":
            return {"kind": "line", "ref": end.key}
        return {"kind": "battery_limit"}

    def _pipe(
        self,
        s: Segment,
        points: list[Vec],
        dn: float,
        od: float,
        ins: float,
        method: str,
        extra: dict[str, Any],
        open_ends: list[str],
        source: str,
        index: bool = True,
    ) -> list[Capsule]:
        """Add the pipe of *s* along *points* (and its in-line items); its capsules go into the
        pipe index unless *index* is False. Returns the capsules."""
        info = self.lines.get(s.line)
        pid = f"{_stem(s.sheet)}/{s.id}"
        entry: dict[str, Any] = {
            "id": pid,
            "refs": {"lines": [s.line], "segments": [s.id], "sheet": s.sheet},
            "source": source,
            "line": s.line,
            "segment": s.id,
            "segment_number": s.number or None,
            "dn": dn,
            "od": od,
            "insulation_mm": round(ins * 1000, 1),
            "class": pipe_class(info.pressure_class if info else None, self.specs) or None,
            "fluid": s.fluid or (info.fluid if info else None),
            "points": points,
            "length": polyline_length(points),
            "method": method,
        }
        if extra.get("racks"):
            entry["racks"] = extra["racks"]
            entry["tier"] = extra["tier"]
        if open_ends:
            entry["open_ends"] = open_ends
        at = self.index_of.get(id(s))
        if at is not None and all((at, side) in self.ends for side in (0, 1)):
            entry["ends"] = [self._end_ref(self.ends[(at, side)]) for side in (0, 1)]
        if extra.get("reason"):
            entry["reason"] = extra["reason"]
        if method.startswith("direct") or "direct" in method:
            entry["review_needed"] = True
        buried = self._intent(s, "buried")
        if buried is not None:
            entry["buried"] = buried.model_dump(exclude_defaults=True)
        self.result.pipes.append({k: v for k, v in entry.items() if v is not None})
        self.line_points.setdefault(s.line, []).append(points)
        r = od / 2 + ins
        capsules = [
            Capsule(pid, a, b, r)
            for a, b in zip(points, points[1:], strict=False)
            if dist(a, b) > 1e-9
        ]
        if index:
            for capsule in capsules:
                self.pipes_index.add(capsule, "pipe")
        self._inline(s, points, pid)
        return capsules

    def _inline(self, s: Segment, points: list[Vec], pid: str) -> None:
        total = polyline_length(points)
        items = list(s.items)
        if not items:
            return
        at_end = {s.target.ref: total, s.source.ref: 0.0}
        index = self.segments.index(s) if s in self.segments else -1
        for dexpi_id, side in getattr(self, "end_items", {}).get(index, {}).items():
            at_end[dexpi_id] = total if side == 1 else 0.0
        middle = [i for i in items if i.dexpi_id not in at_end]
        start = min(0.5, total / 4)
        span = max(total - 2 * start, 0.0)
        pitch = (
            INLINE_PITCH if INLINE_PITCH * (len(middle) + 1) <= span else span / (len(middle) + 1)
        )
        k = 0
        for item in items:
            if item.dexpi_id in at_end:
                arc = at_end[item.dexpi_id]
            else:
                k += 1
                arc = start + pitch * k
            iid = f"{_stem(s.sheet)}/{item.dexpi_id}"
            seen = self.inline_ids.get(iid)
            if seen is not None:
                # a component two segments share (a valve between them, a safety valve with
                # its outlet): one item, with both segments in its refs
                for key, value in (("segments", s.id), ("lines", s.line)):
                    if value not in seen["refs"][key]:
                        seen["refs"][key].append(value)
                continue
            point, direction = point_at(points, min(arc, total))
            entry = {
                "id": iid,
                "refs": {
                    "dexpi": item.dexpi_id,
                    "sheet": s.sheet,
                    "lines": [s.line],
                    "segments": [s.id],
                    **({"tag": item.tag} if item.tag else {}),
                },
                "source": "generated",
                "kind": item.kind,
                "dexpi_class": item.cls,
                "point": point,
                "direction": direction,
                "line": s.line,
                "segment": s.id,
                "pipe": pid,
            }
            if item.tag:
                entry["tag"] = item.tag
            self.inline_ids[iid] = entry
            self.result.inline.append(entry)

    def unrouted(self, s: Segment, reason: str) -> None:
        self.result.unrouted.append(
            {
                "line": s.line,
                "segment": s.id,
                "segment_number": s.number or None,
                "sheet": s.sheet,
                "reason": reason,
            }
        )

    def pinned(self) -> None:
        """Pinned segments go first, exactly as given. They become obstacles (and take their
        lanes on the racks) only where the routing reaches the chains that would have been
        routed after them were nothing pinned (:meth:`_virtual_order`), or where a chain
        routed before would come too close to them: so a chain keeps its route and lane
        whatever is pinned after it."""
        for s in self.segments:
            route = self._intent(s, "route")
            if route is None:
                continue
            dn, od, ins = self.sizes(s)
            points = [tuple(p) for p in route]
            self.methods["pinned"] += 1
            self.reasons["pinned"] += 1
            index = self.segments.index(s)
            # a pinned vent or relief line keeps its open end: the zones of its sources apply
            ends = [
                name
                for side, name in ((0, "start"), (1, "end"))
                if (found := self.ends.get((index, side))) is not None and found.kind == "open"
            ]
            lanes = self._pin_lanes(points, od / 2 + ins)
            extra: dict[str, Any] = {"reason": "pinned"}
            if lanes:  # its rack runs, as a routed pipe names them (intermediate rack steel)
                extra["racks"] = list(dict.fromkeys(rack for (rack, _), _ in lanes))
                extra["tier"] = lanes[0][0][1]
            capsules = self._pipe(s, points, dn, od, ins, "pinned", extra, ends, "pinned", False)
            self.deferred.append((self.order.get(index, -1), capsules, lanes))
            for side, point in ((0, points[0]), (1, points[-1])):
                end = (s.source, s.target)[side]
                key = None
                if end.kind == "tee":
                    key = f"{s.sheet}:{end.ref}"
                for k, members in self.attached.items():
                    if any(m[0] == self.segments.index(s) and m[1] == side for m in members):
                        key = k
                if key:
                    self.junction_points[key] = point

    def _virtual_order(self) -> dict[int, int]:
        """The place of each segment's chain in the routing order as if no route were pinned:
        by DN and id, a chain whose tee or line end waits for another chain after it (as
        :meth:`run` routes them). A pinned pipe becomes an obstacle where its chain would have
        been routed, so pinning a route leaves the routes before it as they were."""
        chains = self.build_chains(pins=False)
        keys: set[str] = set()
        lines: set[str] = set()
        place: dict[int, int] = {}
        n = 0

        def ready(end: EndPoint) -> bool:
            if end.kind == "junction":
                return (end.key or "") in keys
            if end.kind == "line":
                return (end.key or "") in lines
            return True

        pending = sorted(chains, key=lambda c: (-c.dn, c.id))
        while pending:
            waiting = []
            for chain in pending:
                if not (ready(chain.start) and ready(chain.end)):
                    waiting.append(chain)
                    continue
                segs = [self.segments[i] for i, _ in chain.segments]
                routed = not any(self._intent(s, "skip") for s in segs) and not any(
                    e.kind == "unresolved" for e in (chain.start, chain.end)
                )
                if routed and not (chain.start.kind == chain.end.kind == "open"):
                    keys.update(k for k in chain.junctions if k)
                    keys.update(
                        e.key or "" for e in (chain.start, chain.end) if e.kind == "junction"
                    )
                    lines.update(s.line for s in segs)
                for i, _ in chain.segments:
                    place[i] = n
                n += 1
            if len(waiting) == len(pending):
                for chain in waiting:
                    for i, _ in chain.segments:
                        place[i] = n
                    n += 1
                break
            pending = waiting
        return place

    def _pin_lanes(self, points: list[Vec], r: float) -> list[tuple[Any, Any]]:
        """The rack lanes a pinned route of radius *r* runs in: ``((rack, tier), (lo, hi, s0,
        s1))`` for each level run of 1 m or more along a rack's strip with its bottom on a
        tier (as :meth:`lane` records them)."""
        if self.plan is None or not self.plan.racks:
            return []
        width = 2 * r + self.rules.spacing_m
        found: list[tuple[Any, Any]] = []
        for a, b in zip(points, points[1:], strict=False):
            if abs(a[2] - b[2]) > 1e-6 or dist(a, b) < 1.0:
                continue
            for rack in self.plan.racks:
                tier = next((t for t in rack.levels if abs(a[2] - r - t) < 0.02), None)
                if tier is None:
                    continue
                centre = [tuple(p) for p in rack.points]
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2])
                from chemeascode.domains.spatial.layout_distances import _polyline_project

                d = _polyline_project(centre, (mid[0], mid[1]))[0]
                if d > rack.width / 2 + 1e-6:
                    continue
                ends = [_polyline_project(centre, (p[0], p[1])) for p in (a, b)]
                if any(e[0] > rack.width / 2 + 1e-6 for e in ends):
                    continue
                if abs(abs(ends[1][2] - ends[0][2]) - dist(a, b)) > 0.05:
                    continue  # across the rack, not along it
                offset = round(_side(centre, mid) * d, 3)
                s0, s1 = sorted((ends[0][2], ends[1][2]))
                found.append(((rack.id, tier), _lane_entry(offset, width, s0, s1)))
        return found

    def _activate(self, keep: Any) -> None:
        """Make the deferred pinned pipes for which *keep* ``(place, capsules)`` is true
        obstacles, with their lanes."""
        rest = []
        for entry in self.deferred:
            place, capsules, lanes = entry
            if not keep(place, capsules):
                rest.append(entry)
                continue
            for capsule in capsules:
                self.pipes_index.add(capsule, "pipe")
            for key, lane in lanes:
                self.lanes.setdefault(key, []).append(lane)
        self.deferred = rest

    def _near_deferred(
        self, pipes: list[tuple[list[Vec], float]]
    ) -> list[tuple[int, list[Capsule]]]:
        """The deferred pinned pipes ``(place, capsules)`` that one of *pipes* ``(points,
        radius)`` comes closer to than ``spacing_m``; where an end of the pipe lies on the
        pinned one (a branch off a pinned run, a pinned neighbour) the run next to that end is
        left out as far as their clearance reaches."""
        hits = []
        for place, capsules, _ in self.deferred:
            widest = max((c.r for c in capsules), default=0.0)
            for points, r in pipes:
                inflate = r + self.rules.spacing_m
                # an end on the pinned pipe's axis (a tee on it, its end): not one merely
                # inside it, as a misplaced pinned branch would make it
                touching = [
                    e
                    for e in (points[0], points[-1])
                    if any(point_segment(e, c.a, c.b)[0] < PIN_TOLERANCE for c in capsules)
                ]
                reach = inflate + widest + 0.05
                close = False
                for a, b in zip(points, points[1:], strict=False):
                    for e in touching:
                        if dist(a, e) < 1e-9:
                            a = _toward(a, b, reach)
                        if b is not None and a is not None and dist(b, e) < 1e-9:
                            b = _toward(b, a, reach)
                    if a is None or b is None:
                        continue
                    if any(segment_distance(a, b, c) < inflate - PIN_TOLERANCE for c in capsules):
                        close = True
                        break
                if close:
                    hits.append((place, capsules))
                    break
        return hits

    def run(self) -> RouteResult:
        began = time.perf_counter()
        self.order = self._virtual_order()
        chains = self.build_chains()
        self.chain_of = {i: c for c in chains for i, _ in c.segments}
        self.pinned()
        pinned = {i for i, s in enumerate(self.segments) if self._intent(s, "route") is not None}
        chains = [c for c in chains if not any(i in pinned for i, _ in c.segments)]
        if self.only is not None:
            for c in chains:
                lines = {self.segments[i].line for i, _ in c.segments}
                if lines & self.only:
                    continue
                for i, _ in c.segments:
                    s = self.segments[i]
                    old = self.keep.get(f"{_stem(s.sheet)}/{s.id}")
                    if old is None:
                        self.unrouted(s, "not routed in this run (layout route --line)")
                        continue
                    points = [tuple(p) for p in old["points"]]
                    dn, od, ins = self.sizes(s)
                    extra = {
                        "racks": old.get("racks"),
                        "tier": old.get("tier"),
                        "reason": old.get("reason"),
                    }
                    self.methods[old["method"]] += 1
                    self._pipe(
                        s,
                        points,
                        dn,
                        od,
                        ins,
                        old["method"],
                        extra,
                        old.get("open_ends", []),
                        old["source"],
                    )
                    for key, members in self.attached.items():
                        for m in members:
                            if m[0] == i:
                                self.junction_points.setdefault(key, points[-1 if m[1] else 0])
            chains = [
                c for c in chains if {self.segments[i].line for i, _ in c.segments} & self.only
            ]
        pending = sorted(chains, key=lambda c: (-c.dn, c.id))
        while pending:
            waiting = []
            for chain in pending:
                # the pinned pipes whose chains would have been routed before this one
                at = min(self.order.get(i, 0) for i, _ in chain.segments)
                self._activate(lambda place, _, at=at: place < at)
                if not self.route_chain(chain):
                    waiting.append(chain)
            if len(waiting) == len(pending):
                for chain in waiting:
                    for end in (chain.start, chain.end):
                        if end.kind in ("junction", "line"):
                            why = f"it starts or ends at {end.label}, which no route reaches"
                            break
                    else:
                        why = "its ends wait for each other"
                    for i, _ in chain.segments:
                        self.unrouted(self.segments[i], why)
                break
            pending = waiting
        self._activate(lambda *_: True)
        self.result.pipes.sort(key=lambda p: p["id"])
        self.result.inline.sort(key=lambda i: i["id"])
        self.result.unrouted.sort(key=lambda u: (u["line"], u["sheet"], u["segment"]))
        fill = []
        racks = {rack.id: rack for rack in (self.plan.racks if self.plan is not None else [])}
        for (rack_id, tier), taken in sorted(self.lanes.items()):
            if not taken:
                continue
            width = racks[rack_id].width
            # the most crowded cross-section along the rack
            used = max(
                sum(hi - lo for lo, hi, a, b in taken if a <= s + 1e-9 and b >= s - 1e-9)
                for _, _, s, _ in taken
            )
            fill.append(
                {
                    "rack": rack_id,
                    "tier": tier,
                    "used_m": used,
                    "width_m": width,
                    "fill": used / width if width else 0.0,
                }
            )
        self.result.stats = {
            "rack_fill": fill,
            "segments": len(self.segments),
            "routed": len(self.result.pipes),
            "unrouted": len(self.result.unrouted),
            "methods": dict(sorted(self.methods.items())),
            "reasons": dict(sorted(self.reasons.items())),
            "battery_limits": dict(sorted(self.limits.items())),
            "seconds": round(time.perf_counter() - began, 2),
        }
        return self.result


def _combine(base: str, methods: set[str]) -> str:
    """The method of a route of several legs: *base* (``rack``) with the legs that fell back
    (``rack+astar_coarse``); without a base the worst leg (``direct`` over ``astar_fine`` over
    ``astar_coarse`` over ``astar``)."""
    if base:
        return base if methods <= {"astar"} else base + "+" + "+".join(sorted(methods - {"astar"}))
    for method in ("direct", "astar_fine", "astar_coarse"):
        if method in methods:
            return method
    return "astar"


def _flat_bottom(
    pieces: list[list[Vec]],
    sizes: list[tuple[float, float, float]],
    on_rack: list[Vec],
    lane_z: list[float],
) -> list[list[Vec]]:
    """The *pieces* of a chain routed along a rack at the lane of its largest pipe, each
    smaller one lowered onto the tier where it runs in a lane (bottom of pipe on the beams, as
    an eccentric flat-bottom reducer keeps it), with a step at the junction where its
    neighbour stays higher. *sizes* are ``(dn, od, insulation)`` per piece; *on_rack* the
    route's points along the racks, *lane_z* the elevations of its lanes."""
    r_chain = max(od / 2 + ins for _, od, ins in sizes)
    runs = [
        (a, b)
        for a, b in zip(on_rack, on_rack[1:], strict=False)
        if abs(a[2] - b[2]) < 1e-6 and any(abs(a[2] - z) < 1e-6 for z in lane_z)
    ]
    if not runs:
        return pieces

    def on_run(p: Vec) -> bool:
        from chemeascode.domains.spatial.geometry3d import point_segment

        return any(abs(p[2] - a[2]) < 1e-6 and point_segment(p, a, b)[0] < 1e-6 for a, b in runs)

    drops = [r_chain - (od / 2 + ins) for _, od, ins in sizes]
    out: list[list[Vec]] = []
    for k, piece in enumerate(pieces):
        drop = drops[k]
        if drop < 1e-6:
            out.append(piece)
            continue
        lowered = [(p[0], p[1], p[2] - drop) if on_run(p) else p for p in piece]
        if k > 0 and on_run(piece[0]) and abs(drops[k - 1] - drop) > 1e-6:
            # the previous piece ends at the junction at its own height
            shared = piece[0]
            lowered.insert(0, (shared[0], shared[1], shared[2] - max(drops[k - 1], 0.0)))
        if k < len(pieces) - 1 and on_run(piece[-1]) and drops[k + 1] < 1e-6:
            # the next piece (the chain's largest) starts at the junction at the lane height
            lowered.append(piece[-1])
        out.append(lowered)
    return out


def _open_connector(s: Segment, side: int) -> bool:
    """Whether an off-page connector end goes to atmosphere: its id says ``atm`` or ``vent``,
    or it is the outlet of a safety valve or silencer the segment starts at."""
    end = (s.source, s.target)[side]
    if re.search(r"(^|[^a-z])(atm|vent)", end.ref.lower()):
        return True
    other = (s.source, s.target)[1 - side]
    return other.kind == "item" and any(
        word in other.cls for word in ("Safety", "Relief", "Silencer", "Vent")
    )


def _onto_goal(points: list[Vec], b: Vec) -> list[Vec]:
    """*points* (a grid path ending at the grid node nearest *b*) ending exactly at *b*: the
    last straight run is moved onto *b*'s line, the small jogs off the grid done where that run
    starts (away from *b*, whose neighbours, such as the next lane on a rack, are close)."""
    last = points[-1]
    if len(points) < 2:
        return [*points, b]
    prev = points[-2]
    axis = next((i for i in range(3) if abs(last[i] - prev[i]) > 1e-9), None)
    if axis is None:
        return [*points, b]
    k = len(points) - 1
    while k > 0 and all(abs(points[k - 1][i] - last[i]) < 1e-9 for i in range(3) if i != axis):
        k -= 1
    start = list(points[k])
    jogs = []
    for i in range(3):
        if i != axis and abs(start[i] - b[i]) > 1e-9:
            start[i] = b[i]
            jogs.append(tuple(start))
    return [*points[: k + 1], *jogs, b]  # type: ignore[list-item]


def _toward(a: Vec, b: Vec, d: float) -> Vec | None:
    """The point *d* from *a* towards *b*; None when *b* is no farther than that."""
    length = dist(a, b)
    if length <= d + 1e-9:
        return None
    t = d / length
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def _arc_nearest(route: list[Vec], p: Vec) -> float:
    """Arc length of the point of *route* nearest *p*."""
    from chemeascode.domains.spatial.geometry3d import point_segment

    best, run, found = math.inf, 0.0, 0.0
    for a, b in zip(route, route[1:], strict=False):
        d, t = point_segment(p, a, b)
        if d < best - 1e-9:
            best, found = d, run + t * dist(a, b)
        run += dist(a, b)
    return found


def _plan_length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))


def _lane_entry(
    centre: float, width: float, s0: float, s1: float
) -> tuple[float, float, float, float]:
    """A lane as :attr:`Router.lanes` records it: ``(lo, hi, s0, s1)`` around *centre* (on
    the millimetre), its span along the rack on the millimetre, as a route written to the
    model and pinned from it gives them back."""
    return (centre - width / 2, centre + width / 2, round(s0, 3), round(s1, 3))


def _steps(length: float, step: float) -> int:
    """Sample intervals of a run *length* long at *step*: a length a hair over a multiple of
    the step (rounding of a pinned route) does not add one."""
    return max(1, math.ceil(length / step - 1e-6))


def _samples(route: list[Vec], step: float = 0.5) -> list[Vec]:
    found = []
    for a, b in zip(route, route[1:], strict=False):
        n = _steps(dist(a, b), step)
        found += [tuple(a[i] + (b[i] - a[i]) * k / n for i in range(3)) for k in range(n)]
    found.append(route[-1])
    return found  # type: ignore[return-value]


def _project(route: list[Vec], p: Vec) -> float:
    """Arc length of the point of *route* from which *p* is nearest by an orthogonal run in
    plan (where a branch to *p* leaves the route best): the first such point along the route.
    Exact (the plan distance is piecewise linear along a segment: its least value lies at an
    end or where the segment passes *p*'s x or y), so a route a hair longer or shifted (a
    pinned copy written to the millimetre) moves the point by no more than that hair."""
    best, run, found = math.inf, 0.0, 0.0
    for a, b in zip(route, route[1:], strict=False):
        length = dist(a, b)
        ts = {0.0, 1.0}
        for i in (0, 1):
            span = b[i] - a[i]
            if abs(span) > 1e-12:
                t = (p[i] - a[i]) / span
                if 0.0 < t < 1.0:
                    ts.add(t)
        for t in sorted(ts):
            x, y = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
            d = abs(p[0] - x) + abs(p[1] - y)
            if d < best - 1e-9:
                best, found = d, run + t * length
        run += length
    return found


def _side(centreline: list[tuple[float, float]], p: Vec) -> int:
    """+1 when *p* lies left of the centreline's drawn direction (at its nearest point), -1
    right, 0 on it."""
    from chemeascode.domains.spatial.layout_distances import point_segment

    best = None
    for a, b in zip(centreline, centreline[1:], strict=False):
        d = point_segment((p[0], p[1]), a, b)[0]
        if best is None or d < best[0]:
            best = (d, a, b)
    if best is None:
        return 0
    _, a, b = best
    cross = (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])
    return 1 if cross > 1e-9 else -1 if cross < -1e-9 else 0


def _polyline_arc(centreline: list[tuple[float, float]], p: tuple[float, float]) -> float:
    from chemeascode.domains.spatial.layout_distances import _polyline_project

    return _polyline_project(centreline, p)[2]


def _same_direction(
    centreline: list[tuple[float, float]], piece: list[tuple[float, float]]
) -> bool:
    """Whether *piece* runs the way the rack's centreline is drawn."""
    from chemeascode.domains.spatial.layout_distances import _polyline_project

    if len(piece) < 2:
        return True
    s0 = _polyline_project(centreline, piece[0])[2]
    s1 = _polyline_project(centreline, piece[-1])[2]
    return s1 >= s0


def route_model(
    model: dict[str, Any],
    segments: list[Segment],
    lines: Any = None,
    routing: Any = None,
    specs: Any = None,
    plan: Any = None,
    only: set[str] | None = None,
    keep: list[dict[str, Any]] | None = None,
    vent_radii: dict[str, float] | None = None,
) -> RouteResult:
    """Route every segment (see the module text). *vent_radii*: the zone radius of each line
    with an open end (:func:`zones.line_radii`), for the ``vents`` rules."""
    return Router(model, segments, lines, routing, specs, plan, only, keep, vent_radii).run()


__all__ = ["RouteResult", "Router", "Solid", "route_model", "sub"]
