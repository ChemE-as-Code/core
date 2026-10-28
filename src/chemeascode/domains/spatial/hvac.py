"""HVAC of the 3D model: air handling units, ventilated rooms, terminals and rectangular ducts,
from ``layout/hvac.yaml``.

Pure Python and deterministic, on the model document after the pipes and cable trays are
routed. Inputs: ``layout/hvac.yaml`` (:class:`~.schemas.Hvac`: units, rooms, rules), the
buildings of the model (footprint, levels, openings, crane) and the package table
``data/duct-sizing.yaml`` (velocity limits, standard sides, aspect ratio, terminal size; every
value ASSUMED, a plant overrides them under ``rules``).

**Rooms.** A room is its building's footprint (or its plan ``extent``) on one level, as high as
the level's clear height (or its ``height``). Its supply air is ``air_changes_per_h`` times its
volume (or ``flow_m3h``), its extract air ``extract_fraction`` of that. The ceiling is the top
of the room, or the underside of the crane runway of a building with a crane (the runway's top
of rail, less its girder); the supply ducts run with their centreline ``ceiling_gap_m`` plus the
envelope of the room's supply main (half its larger side) under it (or at the room's
``duct_elevation_m``), the extract ducts lower by both mains' envelopes and ``spacing_m``.

**Terminals.** Declared terminals (``supply``, ``extract``: points in plan) form one row in the
order given. Otherwise a room gets as many terminals as its air needs at ``terminal_max_m3h``
each, in rows along its longer side, at least ``terminal_pitch_m`` apart: the supply rows in the
half of the room on the low side of its shorter axis, the extract rows in the other half. Each
terminal takes an equal share of the room's air.

**Ducts.** Every unit has four ports on its top (outdoor air, exhaust, return and supply air
along its length), each with a riser straight up to the elevation its duct runs at (the lowest
row of its system, the middle of its louvre), reserved before any duct is routed. The intake
and exhaust are routed first (short, fixed at both ends), then per unit and system (supply
from the supply port, extract to the return port) the rows are joined into a tree: farthest
row first, each row's *main* from the nearest point of the tree's level mains so far (or the
riser) to the row, where it meets a straight row at the nearest point of its line (a declared
row that is not straight at its nearest terminal); from there the row's *headers* run from
terminal to terminal both ways. The *intake* runs from the unit's ``intake``
louvre to its outdoor air port (all the supply air: no recirculation), the *exhaust* from its
exhaust port to its ``exhaust`` opening (all the extract air). Each leg is an orthogonal A*
route of the pipe router (:meth:`~chemeascode.domains.spatial.routing.Router.leg`) kept inside
the building (it may not leave by a door or louvre) and ``spacing_m`` clear of the items,
steel, walls, pipes, trays, units and the ducts before it, with the envelope of a round duct as
wide as the larger side of the rectangle.

**Sizes.** Each piece of constant air flow (a main is cut where another main tees off it) is
the smallest rectangle of the standard sides (height at most ``max_height_mm``, width over
height at most ``max_aspect``) that carries its air at or below the velocity limit of its kind
(``main``, ``header``, ``intake``, ``exhaust``); a main is routed with the size the air of
every row still to come would need, so it keeps its clearance when the rows after it tee off.

:func:`hvac_findings` are the rules on them (run with the model rules): ``hvac-capacity`` (a
duct above its velocity limit at its largest size, a louvre above its face velocity, a unit
over its capacity, a room or unit without its air path), ``duct-unrouted`` and ``clash-duct``
(a duct through an item, steel, a pipe, a tray, a unit or another system's duct).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.spatial.geometry3d import (
    TOUCH,
    Box,
    Capsule,
    dist,
    part_solid,
    point_segment,
    polyline_length,
    segment_distance,
    segment_segment,
    simplify,
    split_at,
)
from chemeascode.domains.spatial.routing import Router
from chemeascode.domains.spatial.schemas import Hvac, HvacRuleSet, RoutingRules
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

Vec = tuple[float, float, float]
DATA = Path(__file__).parent / "data" / "duct-sizing.yaml"
#: The model's name of each system, and the prefix of its duct ids.
PREFIX = {"supply": "SA", "extract": "EA", "outdoor": "OA", "exhaust": "XA"}
#: Ports along a unit's length, as fractions of it from its middle.
PORTS = (("outdoor", -0.375), ("exhaust", -0.125), ("return", 0.125), ("supply", 0.375))
#: Height of a unit's base frame (detail), m.
BASE = 0.15
#: Size of a terminal's grille in plan, and its depth, m.
GRILLE = (0.6, 0.6, 0.1)
#: At most this many findings of one rule are listed one by one.
LIMIT = 200


@cache
def sizing_table() -> dict[str, Any]:
    """The package table ``data/duct-sizing.yaml``."""
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


@dataclass
class Limits:
    """The sizing rules in force: the package table with the plant's overrides."""

    velocities: dict[str, float]
    bases: dict[str, str]
    sides: list[float]  # m
    max_aspect: float
    max_height: float  # m
    terminal_max: float  # m3/h
    free_area: float

    @classmethod
    def of(cls, rules: HvacRuleSet) -> Limits:
        table = sizing_table()
        velocities = {k: float(v["max_m_s"]) for k, v in table["velocities"].items()}
        bases = {k: str(v.get("basis", "")) for k, v in table["velocities"].items()}
        for kind, limit in rules.velocities.items():
            velocities[kind] = limit.max_m_s
            bases[kind] = limit.basis or "layout/hvac.yaml"
        sides = rules.sides_mm if rules.sides_mm is not None else table["sides_mm"]
        return cls(
            velocities=velocities,
            bases=bases,
            sides=[s / 1000 for s in sides],
            max_aspect=rules.max_aspect or float(table["max_aspect"]),
            max_height=rules.max_height_mm / 1000,
            terminal_max=rules.terminal_max_m3h or float(table["terminal_max_m3h"]),
            free_area=rules.louvre_free_area or float(table["louvre_free_area"]),
        )

    def rectangles(self) -> list[tuple[float, float]]:
        """Every standard (width, height): height up to the largest allowed, width at least the
        height and at most ``max_aspect`` times it; by area, then width."""
        heights = [h for h in self.sides if h <= self.max_height + 1e-9] or [self.sides[0]]
        found = {
            (w, h)
            for h in heights
            for w in self.sides
            if h - 1e-9 <= w <= self.max_aspect * h + 1e-9
        }
        return sorted(found, key=lambda r: (round(r[0] * r[1], 6), r[0], r[1]))

    def size(self, flow_m3h: float, kind: str) -> tuple[float, float]:
        """The smallest standard rectangle that carries *flow_m3h* at the limit of *kind*; the
        largest when none does."""
        rects = self.rectangles()
        need = flow_m3h / 3600 / self.velocities[kind]
        for w, h in rects:
            if w * h >= need - 1e-12:
                return w, h
        return rects[-1]


def velocity(flow_m3h: float, w: float, h: float) -> float:
    return flow_m3h / 3600 / (w * h)


@dataclass
class Row:
    """Terminals of one room and system that one header joins, in duct order."""

    room: str
    system: str
    index: int
    terminals: list[dict[str, Any]]

    @property
    def flow(self) -> float:
        return sum(t["flow_m3h"] for t in self.terminals)


@dataclass
class Main:
    """A routed main of a unit's tree: from its tee (or the port) to the first terminal of its
    row."""

    row: Row
    points: list[Vec]
    method: str
    parent: int | None
    arc: float  # where it tees off its parent, along the parent
    children: list[int] = field(default_factory=list)
    total: float = 0.0


class DuctRouter(Router):
    """The pipe router kept inside one building: a node outside ``bounds`` is blocked, and the
    fallback route runs under the building's ceiling instead of over everything."""

    bounds: tuple[float, float, float, float, float, float] | None = None

    def blocked_fn(self, inflate, bubbles, margin=None):
        inner = super().blocked_fn(inflate, bubbles, margin)
        bounds = self.bounds
        if bounds is None:
            return inner
        x0, y0, z0, x1, y1, z1 = bounds

        def blocked(key, p):
            if not (x0 <= p[0] <= x1 and y0 <= p[1] <= y1 and z0 <= p[2] <= z1):
                return True
            return inner(key, p)

        blocked.edge = inner.edge  # type: ignore[attr-defined]
        blocked.in_bubble = inner.in_bubble  # type: ignore[attr-defined]
        return blocked

    def direct(self, a: Vec, b: Vec, r: float) -> list[Vec]:
        z = max(a[2], b[2])
        if self.bounds is not None:
            z = min(z, self.bounds[5] - r)
        return simplify([a, (a[0], a[1], z), (b[0], a[1], z), (b[0], b[1], z), b])


def _box_parts(pid: str, points: list[Vec], w: float, h: float, material: str):
    """One box per straight run of a duct's centreline (width across, height vertical)."""
    parts = []
    for k, (a, b) in enumerate(zip(points, points[1:], strict=False)):
        length = dist(a, b)
        if length <= 1e-6:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
        if abs(a[2] - b[2]) > 1e-6 and math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6:
            size, angle = (w, h, length), 0.0
        else:
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            size = (math.hypot(b[0] - a[0], b[1] - a[1]), w, h)
        parts.append(
            {
                "id": f"{pid}/run-{k}",
                "kind": "box",
                "material": material,
                "centre": mid,
                "size": size,
                "rotation_deg": angle,
            }
        )
    return parts


def _sub(points: list[Vec], a: float, b: float) -> list[Vec]:
    """The piece of a polyline between arcs *a* and *b*."""
    _, after = split_at(points, a)
    piece, _ = split_at(after, b - a)
    return piece


def _project(points: list[Vec], p: Vec) -> tuple[float, Vec, float] | None:
    """The nearest point to *p* on the level runs of a polyline: (distance, point, arc)."""
    best = None
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = dist(a, b)
        if length > 1e-9 and abs(a[2] - b[2]) <= 1e-6:
            _, t = point_segment(p, a, b)
            q = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2])
            d = sum(abs(q[i] - p[i]) for i in range(3))
            if best is None or d < best[0] - 1e-9:
                best = (d, q, run + t * length)
        run += length
    return best


def _manhattan(a: Vec, b: Vec) -> float:
    return sum(abs(a[i] - b[i]) for i in range(3))


def _on_row(row: Row, p: Vec) -> bool:
    """Whether *p* lies on a straight row's line between its end terminals."""
    a, b = row.terminals[0]["point"], row.terminals[-1]["point"]
    axes = [i for i in range(3) if abs(a[i] - b[i]) > 1e-6]
    if len(axes) != 1:
        return False
    i = axes[0]
    if any(abs(p[j] - a[j]) > 1e-6 for j in range(3) if j != i):
        return False
    return min(a[i], b[i]) - 1e-6 <= p[i] <= max(a[i], b[i]) + 1e-6


def _junction(row: Row, p: Vec) -> tuple[Vec, list[dict[str, Any]], list[dict[str, Any]]]:
    """Where a main from *p* meets a row: the nearest point of a straight row (its terminals
    on one axis-parallel line), else its nearest terminal; with the terminals beyond it on
    either side, each side nearest first."""
    terminals = row.terminals
    pts = [t["point"] for t in terminals]
    a, b = pts[0], pts[-1]
    axes = [i for i in range(3) if abs(a[i] - b[i]) > 1e-6]
    straight = len(axes) == 1 and all(
        abs(q[i] - a[i]) <= 1e-6 for q in pts for i in range(3) if i != axes[0]
    )
    if straight:
        i = axes[0]
        lo, hi = min(a[i], b[i]), max(a[i], b[i])
        at = min(max(p[i], lo), hi)
        joint = tuple(at if j == i else a[j] for j in range(3))
        sign = 1.0 if b[i] > a[i] else -1.0
        after = sorted(
            (t for t in terminals if (t["point"][i] - at) * sign > 1e-6),
            key=lambda t: abs(t["point"][i] - at),
        )
        before = sorted(
            (t for t in terminals if (t["point"][i] - at) * sign < -1e-6),
            key=lambda t: abs(t["point"][i] - at),
        )
        return joint, before, after  # type: ignore[return-value]
    m = min(range(len(pts)), key=lambda k: (_manhattan(pts[k], p), k))
    return pts[m], terminals[:m][::-1], terminals[m + 1 :]


class Ventilation:
    """Builds the HVAC sections of a model document (see the module text)."""

    def __init__(
        self,
        document: dict[str, Any],
        hvac: Hvac,
        plan: Any = None,
        routing_rules: RoutingRules | None = None,
        file: str = "layout/hvac.yaml",
    ) -> None:
        self.document = document
        self.hvac = hvac
        self.rules = hvac.rules
        self.limits = Limits.of(hvac.rules)
        self.plan = plan
        self.routing_rules = routing_rules or RoutingRules()
        self.file = file
        self.buildings = {b["id"]: b for b in document.get("buildings", [])}
        self.missing: list[dict[str, str]] = []
        self.ducts: list[dict[str, Any]] = []
        self._router: DuctRouter | None = None
        self.units: dict[str, dict[str, Any]] = {}
        self.risers: dict[tuple[str, str], Vec] = {}

    # -- the router -------------------------------------------------------------------

    @property
    def router(self) -> DuctRouter:
        if self._router is None:
            from chemeascode.domains.spatial.schemas import Routing

            base = self.routing_rules.model_dump()
            base.update(spacing_m=self.rules.spacing_m, grid_m=self.rules.grid_m, vents=[])
            routing = Routing(rules=RoutingRules.model_validate(base))
            router = DuctRouter(self.document, [], None, routing, None, self.plan)
            for building in self.document.get("buildings", []):
                for part in building.get("parts", []):
                    if part["kind"] == "member":  # a crane runway
                        solid = part_solid(part, building["id"])
                        if solid is not None:
                            router.static.add(solid, "steel")
            for pipe in self.document.get("pipes", []):
                r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
                self._block(router, pipe["id"], [tuple(p) for p in pipe["points"]], r, "pipe")
            for tray in self.document.get("trays") or []:
                r = max(tray["width"], tray["depth"]) / 2
                self._block(router, tray["id"], [tuple(p) for p in tray["points"]], r, "tray")
            for unit in self.units.values():
                for part in unit["parts"]:
                    solid = part_solid(part, unit["id"])
                    if solid is not None:
                        router.static.add(solid, "equipment")
            self._router = router
        return self._router

    @staticmethod
    def _block(router: Router, pid: str, points: list[Vec], r: float, kind: str) -> None:
        for a, b in zip(points, points[1:], strict=False):
            if dist(a, b) > 1e-9:
                router.pipes_index.add(Capsule(pid, a, b, r), kind)

    def _leg(self, building: str, a: Vec, b: Vec, r: float) -> tuple[list[Vec], str]:
        router = self.router
        x0, y0, x1, y1 = self.buildings[building]["footprint"]
        z0, z1 = self.buildings[building]["heights"]
        router.bounds = (x0, y0, z0, x1, y1, z1)
        if dist(a, b) <= 1e-6:
            return [a, b], "astar"
        points, method = router.leg(a, b, r)
        return simplify([tuple(p) for p in points]), method  # type: ignore[misc]

    # -- geometry of the buildings ----------------------------------------------------

    def _level(self, building: dict[str, Any], level_id: str | None) -> tuple[float, float, str]:
        """Floor elevation, clear height and id of a building's level (default its lowest
        floor; the whole building without levels)."""
        levels = sorted(building.get("levels", []), key=lambda lv: lv["elevation"])
        chosen = None
        if level_id is not None:
            chosen = next((lv for lv in levels if lv["id"] == level_id), None)
        if chosen is None:
            chosen = next((lv for lv in levels if lv["kind"] == "floor"), None)
        if chosen is None:
            z0, z1 = building["heights"]
            return z0, z1 - z0, ""
        return chosen["elevation"], chosen["clear_height"], chosen["id"]

    def _ceiling(self, building: dict[str, Any], floor: float, height: float) -> float:
        """The underside of what a duct may not rise into: the room's top, or the crane
        runway."""
        top = floor + height
        crane = building.get("crane")
        if crane:
            rail = crane.get("rail_elevation")
            if rail is None:
                rail = building["heights"][1] - 1.5
            girder = 0.6 if crane.get("capacity_t", 0) > 20 else 0.4
            if floor < rail <= top + 1e-9:
                top = min(top, rail - girder)
        return top

    def _opening(self, building: dict[str, Any], opening_id: str) -> dict[str, Any] | None:
        for opening in building.get("openings", []):
            if opening.get("id") == opening_id:
                return opening
        return None

    def _opening_point(
        self, building: dict[str, Any], opening: dict[str, Any], inset: float
    ) -> tuple[Vec, Vec]:
        """The middle of an opening on the building's inner face and the point *inset* m in
        from it."""
        from chemeascode.domains.spatial.structures import Frame, _side_line

        f = Frame(tuple(building["origin"]), building["rotation_deg"])
        left, right, normal = _side_line(opening["side"], building["width"], building["depth"])
        length = math.dist(left[:2], right[:2])
        ux, uy = (right[0] - left[0]) / length, (right[1] - left[1]) / length
        s = min(length, opening["offset"] + opening["width"] / 2)
        z = opening.get("sill", 0.0) + opening["height"] / 2
        u, v = left[0] + ux * s, left[1] + uy * s
        face = f.site(u, v, z)
        inner = f.site(u - normal[0] * inset, v - normal[1] * inset, z)
        return face, inner

    # -- units ------------------------------------------------------------------------

    def place_units(self) -> None:
        for unit in sorted(self.hvac.units, key=lambda u: u.id):
            building = self.buildings.get(unit.building)
            if building is None:
                self._missing(unit.id, "unit", f"building {unit.building} is not in the layout")
                continue
            floor, _, level = self._level(building, unit.level)
            length, width, height = unit.size
            a = math.radians(unit.rotation_deg)
            c, s = round(math.cos(a), 12), round(math.sin(a), 12)
            x, y = unit.position
            top = floor + height
            ports = {name: (x + c * f * length, y + s * f * length, top) for name, f in PORTS}
            parts = [
                {
                    "id": f"{unit.id}/casing",
                    "kind": "box",
                    "material": "ahu",
                    "centre": (x, y, floor + height / 2),
                    "size": (length, width, height),
                    "rotation_deg": float(unit.rotation_deg),
                },
                {
                    "id": f"{unit.id}/base",
                    "kind": "box",
                    "material": "steel",
                    "centre": (x, y, floor + BASE / 2),
                    "size": (length + 0.1, width + 0.1, BASE),
                    "rotation_deg": float(unit.rotation_deg),
                    "lod": 2,
                },
            ]
            for k in range(1, 4):  # the section joints of the casing
                u = -length / 2 + k * length / 4
                parts.append(
                    {
                        "id": f"{unit.id}/joint-{k}",
                        "kind": "box",
                        "material": "steel",
                        "centre": (x + c * u, y + s * u, floor + height / 2),
                        "size": (0.06, width + 0.04, height + 0.02),
                        "rotation_deg": float(unit.rotation_deg),
                        "lod": 2,
                    }
                )
            self.units[unit.id] = {
                "id": unit.id,
                "refs": {"tag": unit.id, "file": self.file},
                "source": "declared",
                "title": unit.title,
                "building": unit.building,
                "level": level or None,
                "position": (x, y, floor),
                "size": unit.size,
                "rotation_deg": float(unit.rotation_deg),
                "capacity_m3h": unit.capacity_m3h,
                "supply_m3h": 0.0,
                "extract_m3h": 0.0,
                "intake": unit.intake,
                "exhaust": unit.exhaust,
                "ports": ports,
                "parts": parts,
                "_declared": unit,
            }

    def _missing(self, tag: str, kind: str, reason: str, level: str = "warning") -> None:
        self.missing.append({"tag": tag, "kind": kind, "reason": reason, "level": level})

    # -- rooms and terminals ----------------------------------------------------------

    def rooms(self) -> list[dict[str, Any]]:
        found = []
        for room in sorted(self.hvac.rooms, key=lambda r: r.id):
            building = self.buildings.get(room.building)
            if building is None:
                self._missing(room.id, "room", f"building {room.building} is not in the layout")
                continue
            floor, clear, level = self._level(building, room.level)
            height = room.height or clear
            extent = tuple(room.extent) if room.extent else tuple(building["footprint"])
            x0, y0, x1, y1 = extent
            volume = (x1 - x0) * (y1 - y0) * height
            if room.flow_m3h is not None:
                supply = room.flow_m3h
                changes = supply / volume
            else:
                changes = room.air_changes_per_h or 0.0
                supply = changes * volume
            extract = supply * room.extract_fraction
            ceiling = self._ceiling(building, floor, height)
            gap = self.rules.ceiling_gap_m
            # the envelopes of the room's largest ducts (its mains) keep the gap to the ceiling
            # and the spacing between the two layers
            r_supply = self._radius(supply, "main")
            r_extract = self._radius(extract, "main") if extract > 1e-9 else 0.0
            z_supply = room.duct_elevation_m
            if z_supply is None:
                z_supply = ceiling - gap - r_supply
            z_extract = z_supply - r_supply - self.rules.spacing_m - r_extract
            terminals = []
            for system, flow, z, declared in (
                ("supply", supply, z_supply, room.supply),
                ("extract", extract, z_extract, room.extract),
            ):
                if flow <= 1e-9:
                    continue
                terminals += self._terminals(room.id, system, flow, z, extent, declared)
            unit = self.units.get(room.unit)
            if unit is None:
                self._missing(room.id, "room", f"unit {room.unit} is not placed in the layout")
            elif unit["building"] != room.building:
                self._missing(
                    room.id,
                    "room",
                    f"unit {room.unit} stands in {unit['building']}, the room in "
                    f"{room.building}: ducts run inside one building",
                )
                unit = None
            if unit is not None:
                unit["supply_m3h"] += supply
                unit["extract_m3h"] += extract
            found.append(
                {
                    "id": room.id,
                    "refs": {"file": self.file},
                    "source": "declared",
                    "title": room.title,
                    "building": room.building,
                    "level": level or None,
                    "unit": room.unit,
                    "extent": extent,
                    "floor": floor,
                    "height": height,
                    "volume_m3": round(volume, 3),
                    "air_changes_per_h": round(changes, 3),
                    "supply_m3h": round(supply, 3),
                    "extract_m3h": round(extract, 3),
                    "basis": room.basis or None,
                    "terminals": terminals,
                    "_served": unit is not None,
                }
            )
        return found

    def _terminals(
        self,
        room: str,
        system: str,
        flow: float,
        z: float,
        extent: tuple[float, ...],
        declared: list[Any],
    ) -> list[dict[str, Any]]:
        """The terminals of one room and system (see the module text), each with its row."""
        x0, y0, x1, y1 = extent
        points: list[tuple[int, float, float]] = []
        source = "declared"
        if declared:
            points = [(1, p[0], p[1]) for p in declared]
        else:
            source = "generated"
            along_x = (x1 - x0) >= (y1 - y0)
            length, wide = (x1 - x0, y1 - y0) if along_x else (y1 - y0, x1 - x0)
            n = max(1, math.ceil(flow / self.limits.terminal_max - 1e-9))
            rows = max(1, math.ceil(n * self.rules.terminal_pitch_m / length))
            rows = min(rows, max(1, math.floor(wide / 2 / self.rules.terminal_pitch_m)))
            per = math.ceil(n / rows)
            for j in range(rows):
                across = wide / 2 * (j + 0.5) / rows
                if system == "extract":
                    across += wide / 2
                for i in range(per):
                    s = length * (i + 0.5) / per
                    u, v = round(s * 2) / 2, round(across * 2) / 2
                    x, y = (x0 + u, y0 + v) if along_x else (x0 + v, y0 + u)
                    points.append((j + 1, x, y))
        share = flow / len(points)
        found = []
        w, h = self.limits.size(share, "header")
        for k, (row, x, y) in enumerate(points, 1):
            found.append(
                {
                    "id": f"{room}/{system}-{k}",
                    "system": system,
                    "point": (x, y, z),
                    "flow_m3h": round(share, 3),
                    "source": source,
                    "parts": [
                        {
                            "id": f"{room}/{system}-{k}/grille",
                            "kind": "box",
                            "material": f"grille_{system}",
                            "centre": (x, y, z - h / 2 - GRILLE[2] / 2),
                            "size": GRILLE,
                            "rotation_deg": 0.0,
                            "lod": 2,
                        }
                    ],
                    "_row": row,
                    "_share": share,
                }
            )
        return found

    # -- the ducts --------------------------------------------------------------------

    def _duct(
        self,
        pid: str,
        system: str,
        kind: str,
        unit: str,
        room: str | None,
        points: list[Vec],
        flow: float,
        method: str,
        serves: list[str] | None = None,
    ) -> dict[str, Any]:
        w, h = self.limits.size(flow, kind)
        v = velocity(flow, w, h)
        review = method == "direct"
        entry = {
            "id": pid,
            "refs": {"tag": unit, "file": self.file},
            "source": "generated",
            "system": system,
            "kind": kind,
            "unit": unit,
            "room": room,
            "serves": serves,
            "points": points,
            "width": w,
            "height": h,
            "flow_m3h": round(flow, 3),
            "velocity_m_s": round(v, 3),
            "velocity_max_m_s": self.limits.velocities[kind],
            "length": polyline_length(points),
            "method": method,
            "review_needed": True if review else None,
            "reason": "found no clear way inside the building (direct, review it)"
            if review
            else None,
            "parts": _box_parts(pid, points, w, h, f"duct_{system}"),
        }
        self.ducts.append(entry)
        return entry

    def _radius(self, flow: float, kind: str) -> float:
        w, h = self.limits.size(flow, kind)
        return max(w, h) / 2

    def network(self, unit: dict[str, Any], system: str, rows: list[Row]) -> None:
        """The tree of one unit and system (see the module text): mains, then headers."""
        building = unit["building"]
        net = f"net:{unit['id']}:{system}"
        port = unit["ports"]["supply" if system == "supply" else "return"]
        remaining = sum(r.flow for r in rows)
        tip = self.risers[(unit["id"], system)]

        def far(row: Row) -> tuple[float, str, int]:
            return (-_manhattan(_junction(row, tip)[0], port), row.room, row.index)

        mains: list[Main] = []
        header = 0
        for row in sorted(rows, key=far):
            r = self._radius(remaining, "main")
            remaining -= row.flow
            aim = _junction(row, tip)[0]
            best = (
                round(_manhattan(aim, tip), 6),
                len(rows),
                tip,
                None,
                0.0,
            )  # mains first on a tie
            for k, main in enumerate(mains):
                hit = _project(main.points, aim)
                if hit is not None and (round(hit[0], 6), k) < best[:2]:
                    best = (round(hit[0], 6), k, hit[1], k, hit[2])
            _, _, at, parent, arc = best
            joint, before, after = _junction(row, at)
            points, method = self._leg(building, at, joint, r)
            # a main that reaches the row's line before its end joins the row there
            while len(points) > 2 and _on_row(row, points[-2]) and _on_row(row, points[-1]):
                points = points[:-1]
            if points[-1] != joint:
                joint, before, after = _junction(row, points[-1])
            if parent is None:
                points = simplify([port, *points])
                arc = 0.0
            mains.append(Main(row, points, method, parent, arc))
            if parent is not None:
                mains[parent].children.append(len(mains) - 1)
            self._block(self.router, net, points, r, "duct")
            # the headers, from the joint terminal to terminal both ways
            header = 0
            for side in (after, before):
                left = sum(t["_share"] for t in side)
                last = joint
                for terminal in side:
                    rh = self._radius(left, "header")
                    hpoints, hmethod = self._leg(building, last, terminal["point"], rh)
                    self._block(self.router, net, hpoints, rh, "duct")
                    header += 1
                    self._duct(
                        f"{PREFIX[system]}-{row.room}-{row.index}-H{header}",
                        system,
                        "header",
                        unit["id"],
                        row.room,
                        hpoints,
                        left,
                        hmethod,
                        [row.room],
                    )
                    left -= terminal["_share"]
                    last = terminal["point"]
        # flows: a main carries its row and every main teed off it further along
        for k in range(len(mains) - 1, -1, -1):
            main = mains[k]
            main.total = main.row.flow + sum(mains[c].total for c in main.children)
        for main in mains:
            length = polyline_length(main.points)
            cuts = sorted({mains[c].arc for c in main.children if 1e-6 < mains[c].arc < length})
            stops = [0.0, *cuts, length]
            n = 0
            for a, b in zip(stops, stops[1:], strict=False):
                if b - a <= 1e-6:
                    continue
                n += 1
                down = [mains[c] for c in main.children if mains[c].arc >= b - 1e-6]
                flow = main.row.flow + sum(c.total for c in down)
                serves = sorted({main.row.room}.union(*(self._rooms_below(mains, c) for c in down)))
                self._duct(
                    f"{PREFIX[system]}-{main.row.room}-{main.row.index}-{n}",
                    system,
                    "main",
                    unit["id"],
                    main.row.room,
                    _sub(main.points, a, b),
                    flow,
                    main.method,
                    serves,
                )

    @staticmethod
    def _rooms_below(mains: list[Main], main: Main) -> set[str]:
        found = {main.row.room}
        for c in main.children:
            found |= Ventilation._rooms_below(mains, mains[c])
        return found

    def reserve(self, unit: dict[str, Any], rooms: list[dict[str, Any]]) -> None:
        """The riser of each port: straight up from the port to the elevation its duct runs at
        (the lowest row of its system, the middle of its louvre), at least clear of the unit;
        filed with the router before any duct is routed, so no duct blocks another's way up."""
        building = self.buildings[unit["building"]]
        for system, port_name, flow_key, kind in (
            ("supply", "supply", "supply_m3h", "main"),
            ("extract", "return", "extract_m3h", "main"),
            ("outdoor", "outdoor", "supply_m3h", "intake"),
            ("exhaust", "exhaust", "extract_m3h", "exhaust"),
        ):
            flow = unit[flow_key]
            if flow <= 1e-9:
                continue
            r = self._radius(flow, kind)
            port = unit["ports"][port_name]
            z = port[2] + r + self.rules.spacing_m + 0.1
            if system in ("supply", "extract"):
                levels = [
                    t["point"][2]
                    for room in rooms
                    if room["unit"] == unit["id"] and room["_served"]
                    for t in room["terminals"]
                    if t["system"] == system
                ]
            else:
                opening_id = unit["intake"] if system == "outdoor" else unit["exhaust"]
                opening = self._opening(building, opening_id) if opening_id else None
                levels = [self._opening_point(building, opening, 0.0)[0][2]] if opening else []
            if levels:
                z = max(z, min(levels))
            top = (port[0], port[1], z)
            self.risers[(unit["id"], system)] = top
            self._block(self.router, f"net:{unit['id']}:{system}", [port, top], r, "duct")

    def connection(self, unit: dict[str, Any], kind: str) -> None:
        """The intake (louvre to outdoor air port) or exhaust (exhaust port to its opening)."""
        building = self.buildings[unit["building"]]
        opening_id = unit["intake"] if kind == "intake" else unit["exhaust"]
        flow = unit["supply_m3h"] if kind == "intake" else unit["extract_m3h"]
        system = "outdoor" if kind == "intake" else "exhaust"
        if flow <= 1e-9:
            return
        if opening_id is None:
            if kind == "intake":
                self._missing(
                    unit["id"], "unit", "no intake: the outdoor air for its rooms has no way in"
                )
            else:
                self._missing(
                    unit["id"],
                    "unit",
                    "no exhaust opening: the extract air is not ducted out",
                    level="info",
                )
            return
        opening = self._opening(building, opening_id)
        if opening is None:
            self._missing(
                unit["id"], "unit", f"{kind} {opening_id} is not an opening of {building['id']}"
            )
            return
        r = self._radius(flow, kind)
        face, inner = self._opening_point(building, opening, r + self.rules.spacing_m + 0.1)
        port = unit["ports"]["outdoor" if kind == "intake" else "exhaust"]
        tip = self.risers[(unit["id"], system)]
        points, method = self._leg(unit["building"], inner, tip, r)
        points = simplify([face, *points, port])
        if kind == "exhaust":
            points = points[::-1]
        self._block(self.router, f"net:{unit['id']}:{system}", points, r, "duct")
        self._duct(
            f"{PREFIX[system]}-{unit['id']}", system, kind, unit["id"], None, points, flow, method
        )
        louvres = self.louvres.setdefault(
            (building["id"], opening_id),
            {
                "building": building["id"],
                "opening": opening_id,
                "kind": opening.get("kind", "opening"),
                "flow_m3h": 0.0,
                "free_area_m2": round(
                    opening["width"] * opening["height"] * self.limits.free_area, 3
                ),
                "units": [],
            },
        )
        louvres["flow_m3h"] += flow
        louvres["units"].append(unit["id"])

    # -- the whole --------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """The model sections ``hvac_units``, ``hvac_rooms``, ``ducts`` and ``hvac``."""
        self.louvres: dict[tuple[str, str], dict[str, Any]] = {}
        self.place_units()
        rooms = self.rooms()
        for unit_id in sorted(self.units):
            unit = self.units[unit_id]
            self.reserve(unit, rooms)
            for kind in ("intake", "exhaust"):  # short and fixed at both ends: first
                self.connection(unit, kind)
            for system in ("supply", "extract"):
                rows: dict[tuple[str, int], Row] = {}
                for room in rooms:
                    if room["unit"] != unit_id or not room["_served"]:
                        continue
                    for terminal in room["terminals"]:
                        if terminal["system"] != system:
                            continue
                        key = (room["id"], terminal["_row"])
                        rows.setdefault(key, Row(room["id"], system, terminal["_row"], []))
                        rows[key].terminals.append(terminal)
                if rows:
                    self.network(unit, system, [rows[k] for k in sorted(rows)])
        for room in rooms:
            room.pop("_served")
            for terminal in room["terminals"]:
                terminal.pop("_row")
                terminal.pop("_share")
        units = []
        for unit_id in sorted(self.units):
            unit = self.units[unit_id]
            unit.pop("_declared")
            unit["supply_m3h"] = round(unit["supply_m3h"], 3)
            unit["extract_m3h"] = round(unit["extract_m3h"], 3)
            units.append(unit)
        louvres = []
        for key in sorted(self.louvres):
            entry = self.louvres[key]
            entry["flow_m3h"] = round(entry["flow_m3h"], 3)
            v = entry["flow_m3h"] / 3600 / entry["free_area_m2"] if entry["free_area_m2"] else 0
            entry["velocity_m_s"] = round(v, 3)
            entry["velocity_max_m_s"] = self.limits.velocities["louvre"]
            louvres.append(entry)
        self.ducts.sort(key=lambda d: d["id"])
        summary = {
            "units": len(units),
            "rooms": len(rooms),
            "terminals": sum(len(r["terminals"]) for r in rooms),
            "ducts": len(self.ducts),
            "supply_m3h": round(sum(r["supply_m3h"] for r in rooms), 3),
            "extract_m3h": round(sum(r["extract_m3h"] for r in rooms), 3),
            "duct_length_m": round(sum(d["length"] for d in self.ducts), 3),
            "duct_area_m2": round(
                sum(2 * (d["width"] + d["height"]) * d["length"] for d in self.ducts), 3
            ),
            "louvres": louvres,
            "rules": {
                "velocities": dict(sorted(self.limits.velocities.items())),
                "max_height_mm": self.rules.max_height_mm,
                "max_aspect": self.limits.max_aspect,
                "terminal_max_m3h": self.limits.terminal_max,
                "spacing_m": self.rules.spacing_m,
                "louvre_free_area": self.limits.free_area,
            },
            "missing": sorted(self.missing, key=lambda m: (m["kind"], m["tag"], m["reason"])),
        }
        return {
            "hvac_units": units,
            "hvac_rooms": rooms,
            "ducts": self.ducts,
            "hvac": summary,
        }


def build_hvac(
    document: dict[str, Any],
    hvac: Hvac,
    plan: Any = None,
    routing_rules: RoutingRules | None = None,
    file: str = "layout/hvac.yaml",
) -> dict[str, Any]:
    """The HVAC sections of *document* (see the module text)."""
    return Ventilation(document, hvac, plan, routing_rules, file).build()


# ---------------------------------------------------------------------------
# Rules on the ducts
# ---------------------------------------------------------------------------


def _capsules(owner: str, points: list[Any], r: float) -> list[Capsule]:
    pts = [tuple(p) for p in points]
    return [
        Capsule(owner, a, b, r)  # type: ignore[arg-type]
        for a, b in zip(pts, pts[1:], strict=False)
        if dist(a, b) > 1e-9  # type: ignore[arg-type]
    ]


def _box(a: tuple[float, ...], b: tuple[float, ...]) -> list[float]:
    return [round(min(a[i], b[i]), 3) for i in range(3)] + [
        round(max(a[i + 3], b[i + 3]), 3) for i in range(3)
    ]


def hvac_findings(model: dict[str, Any]) -> list[Finding]:
    """``cheme.layout-hvac-capacity``, ``-duct-unrouted`` and ``-clash-duct`` on a model
    document (nothing without its ``ducts``)."""
    ducts = model.get("ducts")
    if ducts is None:
        return []
    summary = model.get("hvac") or {}
    found: list[Finding] = []
    counts: dict[str, int] = {}

    def add(level: str, rule: str, message: str, ids: list[str], box, hint: str, key: str):
        counts[rule] = counts.get(rule, 0) + 1
        if counts[rule] > LIMIT:
            return
        found.append(
            Finding(
                LAYOUT_MODEL_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.layout-{rule}",
                message,
                ids=ids,
                hint=hint,
                key=key,
                box=box,
            )
        )

    for duct in ducts:
        if duct["velocity_m_s"] > duct["velocity_max_m_s"] + 1e-9:
            rooms = ", ".join(duct.get("serves") or ([duct["room"]] if duct.get("room") else []))
            add(
                "warning",
                "hvac-capacity",
                f"duct {duct['id']} carries {duct['flow_m3h']:.0f} m3/h at "
                f"{duct['velocity_m_s']:.1f} m/s in {duct['width'] * 1000:.0f} x "
                f"{duct['height'] * 1000:.0f} mm, above the {duct['velocity_max_m_s']:g} m/s "
                f"limit of a {duct['kind']} duct"
                + (f": {rooms} cannot get their air changes at the limit" if rooms else ""),
                [duct["id"]],
                None,
                "allow deeper ducts (rules.max_height_mm), split the rooms over more units or "
                "rows (declared terminals), lower the air changes with a basis, or raise the "
                "limit in layout/hvac.yaml with a reason",
                duct["id"],
            )
    for unit in model.get("hvac_units") or []:
        capacity = unit.get("capacity_m3h")
        if capacity is not None and unit["supply_m3h"] > capacity + 1e-6:
            add(
                "warning",
                "hvac-capacity",
                f"unit {unit['id']} supplies {unit['supply_m3h']:.0f} m3/h to its rooms, above "
                f"its capacity of {capacity:.0f} m3/h",
                [unit["id"]],
                None,
                "a larger unit, a second unit, or fewer air changes with a basis",
                unit["id"],
            )
    for louvre in summary.get("louvres") or []:
        if louvre["velocity_m_s"] > louvre["velocity_max_m_s"] + 1e-9:
            name = f"{louvre['building']}/{louvre['opening']}"
            add(
                "warning",
                "hvac-capacity",
                f"{louvre['kind']} {name} passes {louvre['flow_m3h']:.0f} m3/h at "
                f"{louvre['velocity_m_s']:.1f} m/s through {louvre['free_area_m2']:g} m2 free "
                f"area (at most {louvre['velocity_max_m_s']:g} m/s)",
                [louvre["opening"], *louvre["units"]],
                None,
                "a larger louvre in layout/building.yaml, or a second one for the unit",
                name,
            )
    for entry in summary.get("missing") or []:
        add(
            entry.get("level", "warning"),
            "hvac-capacity",
            f"{entry['kind']} {entry['tag']}: {entry['reason']}",
            [entry["tag"]],
            None,
            "complete layout/hvac.yaml (units in the room's building, intake and exhaust "
            "openings of that building) and rebuild",
            f"{entry['tag']}:{entry['reason'][:40]}",
        )
    for duct in ducts:
        if duct.get("method") == "direct":
            add(
                "warning",
                "duct-unrouted",
                f"duct {duct['id']} ({duct['system']}, {duct['unit']}): {duct.get('reason')}",
                [duct["id"]],
                None,
                "give the duct room (move the unit, declare terminals, another duct elevation) "
                "and rebuild",
                duct["id"],
            )
    # clashes with items, steel, pipes, trays, units and other systems' ducts (LOD 1)
    from chemeascode.domains.spatial.geometry3d import Index

    solids = Index(4.0)
    for item in model.get("equipment", []):
        for part in item["parts"]:
            solid = part_solid(part, item["tag"])
            if solid is not None:
                solids.add(solid, ("item", f"{item['tag']} ({part['id']})", None))
    for owner in (
        *model.get("structures", []),
        *model.get("racks", []),
        *(model.get("tray_tiers") or []),
        *model.get("buildings", []),
    ):
        for part in owner.get("parts", []):
            if part["kind"] == "member":
                solid = part_solid(part, owner["id"])
                if solid is not None:
                    solids.add(solid, ("steel", part["id"], None))
    for unit in model.get("hvac_units") or []:
        for part in unit["parts"]:
            solid = part_solid(part, unit["id"])
            if solid is not None:
                solids.add(solid, ("unit", unit["id"], unit["id"]))
    for pipe in model.get("pipes", []):
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        for capsule in _capsules(pipe["id"], pipe["points"], r):
            solids.add(capsule, ("pipe", pipe["id"], None))
    for tray in model.get("trays") or []:
        for capsule in _capsules(tray["id"], tray["points"], max(tray["width"], tray["depth"]) / 2):
            solids.add(capsule, ("tray", tray["id"], None))
    for duct in ducts:
        net = f"{duct['unit']}:{duct['system']}"
        for capsule in _capsules(
            duct["id"], duct["points"], max(duct["width"], duct["height"]) / 2
        ):
            solids.add(capsule, ("duct", duct["id"], net))
    for duct in ducts:
        net = f"{duct['unit']}:{duct['system']}"
        capsules = _capsules(duct["id"], duct["points"], max(duct["width"], duct["height"]) / 2)
        hit: set[str] = set()
        for k, capsule in enumerate(capsules):
            end = k in (0, len(capsules) - 1)
            for solid, box, (what, name, owner) in solids.near(capsule.aabb, 0.0):
                if what == "duct" and owner == net:
                    continue  # its own system's tree
                if what == "unit" and owner == duct["unit"] and end:
                    continue  # onto its unit's port
                if name in hit:
                    continue
                if isinstance(solid, Capsule):
                    gap = segment_segment(capsule.a, capsule.b, solid.a, solid.b)
                    close = gap < capsule.r + solid.r - TOUCH
                else:
                    close = segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH
                if not close:
                    continue
                if what == "duct" and duct["id"] > name:
                    continue  # each pair of ducts once
                hit.add(name)
                add(
                    "warning",
                    "clash-duct",
                    f"duct {duct['id']} runs through {what} {name}",
                    [duct["id"], solid.id],
                    _box(capsule.aabb, box),
                    "route the duct around it (declared terminals, the room's "
                    "duct_elevation_m), or move the item or unit",
                    f"{duct['id']}+{name}",
                )
    # a unit standing in an item, steel, a pipe or a tray
    for unit in model.get("hvac_units") or []:
        casing = next((p for p in unit["parts"] if p.get("lod") != 2), None)
        solid = part_solid(casing, unit["id"]) if casing is not None else None
        if not isinstance(solid, Box):
            continue
        hit = set()
        for other, box, (what, name, _) in solids.near(solid.aabb, 0.0):
            if what in ("unit", "duct") or name in hit:
                continue
            if isinstance(other, Capsule):
                close = segment_distance(other.a, other.b, solid) < other.r - TOUCH
            else:
                aa, bb = other.aabb, solid.aabb
                close = all(min(aa[i + 3], bb[i + 3]) - max(aa[i], bb[i]) > TOUCH for i in range(3))
            if close:
                hit.add(name)
                add(
                    "warning",
                    "clash-duct",
                    f"unit {unit['id']} stands in {what} {name}",
                    [unit["id"], other.id],
                    _box(solid.aabb, box),
                    "move the unit (position in layout/hvac.yaml) to a free spot of its building",
                    f"{unit['id']}+{name}",
                )
    for rule, count in sorted(counts.items()):
        if count > LIMIT:
            found.append(
                Finding(
                    LAYOUT_MODEL_FILE,
                    "info",
                    f"cheme.layout-{rule}",
                    f"{count - LIMIT} more {rule} findings not listed",
                    key=f"more-{rule}",
                )
            )
    return found
