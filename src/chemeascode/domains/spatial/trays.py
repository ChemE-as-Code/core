"""Cable trays and the cable schedule of the 3D model, from the electrical list.

Pure Python and deterministic, on the model document after the pipes are routed. Inputs: the
electrical list (``electrical/electrical-list.yaml``: rooms in buildings, the motor list,
feeders, junction boxes), the instrument functions the P&IDs draw (what each measures), the
instrument list, ``electrical/tray-rules.yaml`` (:class:`~.schemas.TrayRules`; defaults
without it) and the site plan's racks.

**Ends.** A room's cables leave it at its ``point``, else at the middle of the side of its
building that faces the nearest rack, 0.5 m outside, at ``entry_elevation_m`` (rooms of one
building side by side, 1.5 m apart). A motor's cable ends at its item's terminal box (the
``<tag>/terminal-box`` part; else the motor, else the top of the item), a feeder's at its item
or point. A motor's ``cable_entry`` (a side of the item's plan footprint, or a point) ends its
branch beside the item instead (:func:`entry_point`; the tray's ``drop_to`` the terminal box),
the cable dropping from there to the terminal box; one the placed item makes impossible
(:func:`entry_problem`) gives the motor no cable and :func:`cable_entry_findings` an error.
An instrument stands where it measures (the ``SensingLocation`` of its P&ID function: a
nozzle's flange, the middle of a routed segment, an in-line item, an item), an actuated valve
(:func:`~chemeascode.domains.control.electrical.actuated_valve`) at its in-line item; an
``instruments`` entry of the electrical list may place it (``point``) or take it out (``skip``).
A function located ``Field`` (a local gauge) or without a sensor needs no cable.

**Junction boxes.** An instrument goes to its entry's ``jb``, else to the first junction box
whose ``instruments`` patterns match it, else to the nearest declared box with a point within
``jb_reach_m`` that has room (``capacity``, default ``defaults.jb_capacity``); the rest are
grouped by site plan area, ordered by x and y and cut into boxes of that capacity, each box
proposed (``JB-<area>-<k>``, ``source: generated``, ``review_needed``) at the middle of its
instruments, ``jb_elevation_m`` above grade, moved to the nearest free spot. A declared box
without a point is placed the same way (``review_needed``). Each instrument has a field cable
to its box (not in trays: its length is the orthogonal distance), each box a multipair cable
to the control room (:func:`~chemeascode.domains.control.electrical.control_room`).

**Trays.** Motor, feeder and multipair cables run in trays: from the room to the nearest rack
(``room``), along the racks (``trunk``, on the rack's tray tier: a ``tiers`` rule, else
``tier_gap_m`` above its top pipe tier on steel of its own, ``tray_tiers``), from one rack to
the next at a joint (``link``) and from the rack to the load (``branch``); a load farther than
``rack_reach_m`` from every rack (or a plant without racks) gets a branch from the room.
Power trays run ``lane_fraction`` of the rack width to the left of its centreline (seen along
it), instrument trays as far to the right; a trunk is cut where its set of cables changes, so
each piece is as wide as its cables need: the smallest of ``widths_mm`` whose cross-section
times ``fill_max_power`` (``fill_max_instrument``) holds the cables' (``fill`` is the cables'
cross-section over the tray's; above the limit at the largest width: finding ``tray-fill``).
A rack in ``power_trays`` has that many power trays side by side, centred on the power lane,
the largest width and ``spacing_m`` apart (:meth:`Cabling._assign` gives each cable one of
them for its way along the rack: its voltage class first, then fill); its trunks are cut per
tray (``PT-<rack>-<letter>-<k>``) and the room legs and links split with the trays at their
ends (``PT-<room>-<letter>``, ``PT-<rack>-<rack>-<letters>``).
The legs off the rack are orthogonal A* routes of the pipe router
(:meth:`~chemeascode.domains.spatial.routing.Router.leg`) clear of the items, steel, pipes and
the trays before them by ``spacing_m``; instrument trays keep ``separation_m`` from the power
trays, which are routed first.

**Cables** (the schedule): tag, from, to, both points, size and diameter from the package
table, the trays in order, ``route_length`` (along the trays and the drops to the terminals,
the orthogonal distance for a field cable) and ``length`` (with ``termination_m`` at each end
and ``slack``). A load that gets no cable (not placed, no room, no position) is listed under
``cabling.missing`` with the reason; a cable whose trays could not be routed is
``review_needed`` with its ``reason``.

:func:`tray_findings` are the rules on them (run with the model rules): ``tray-fill``,
``tray-separation``, ``tray-voltage`` (a cable in a power tray of the other voltage class),
``clash-tray`` (a tray through an item, a pipe or steel), ``tray-zone`` (a tray inside a zone
of a kind in ``avoid_zones``: oxygen-enriched and hazardous areas by default), ``tray-span`` (a level tray run longer than ``support_span_m`` with no steel within
``support_reach_m`` of it: rack bents, tray tiers, structure steel and walls, building walls),
``cable-missing`` and ``cable-unrouted``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.control.electrical import (
    CableType,
    actuated_valve,
    control_room,
    field_cable,
    matches,
    multipair_cable,
    power_cable,
)
from chemeascode.domains.spatial.geometry3d import (
    TOUCH,
    Box,
    Capsule,
    dist,
    part_solid,
    point_at,
    polyline_length,
    segment_distance,
    segment_segment,
    simplify,
)
from chemeascode.domains.spatial.schemas import RoutingRules, TrayRules, TrayRuleSet
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

Vec = tuple[float, float, float]
#: Junction box size [x, y, z], m (ASSUMED).
JB_SIZE = (0.6, 0.25, 0.8)
#: Rooms of one building leave it this far apart along the side, m.
ROOM_PITCH = 1.5
#: How far a room's exit stands outside its building, m.
ROOM_OUT = 0.5
#: A tray ends this far above the terminal it feeds, m.
DROP = 0.6
#: How far a rack's default tray tier may rise above ``tier_gap_m`` to clear the pipes, m.
TIER_RAISE = 3.0
#: At most this many findings of one rule are listed one by one.
LIMIT = 200


@dataclass
class Device:
    """An instrument or actuated valve that needs a field cable."""

    tag: str
    kind: str  # transmitter, control_valve, on_off_valve
    point: Vec | None
    area: str | None = None
    jb: str | None = None
    reason: str = ""


@dataclass
class Route:
    """A cable that runs in trays, from a room to a load."""

    tag: str
    system: str
    kind: str
    room: str
    to: str
    cable: CableType
    start: Vec  # room exit
    end: Vec  # tray end at the load
    terminal: Vec  # the load's connection point
    owner: str | None = None  # the placed item the load is part of
    power_kw: float | None = None
    basis: str = ""
    trays: list[str] = field(default_factory=list)
    reason: str = ""
    entry: bool = False  # the tray ends at the motor's cable_entry beside the item


@dataclass
class Tray:
    id: str
    system: str
    kind: str
    cables: list[str]
    rack: str | None = None
    points: list[Vec] = field(default_factory=list)
    method: str | None = None
    ends_at: str | None = None  # the item a branch ends at
    width: float = 0.0
    drop_to: Vec | None = None  # a branch ending at a cable_entry: the terminal its cable drops to
    voltage: str | None = None  # lv, hv: a power tray of a rack with power_trays of that class
    slot: int | None = None  # a trunk's power tray on a rack with power_trays


def _rules(trays: Any) -> TrayRuleSet:
    if trays is None:
        return TrayRuleSet()
    return trays.rules if isinstance(trays, TrayRules) else trays


def _system(kind: str) -> str:
    return "instrument" if kind in ("control", "rack_room") else "power"


def _terminal(item: dict[str, Any]) -> Vec:
    """Where a motor's cable connects: its terminal box, else its motor, else the top of the
    item."""
    tag = item["tag"]
    parts = {p["id"]: p for p in item.get("parts", [])}
    box = parts.get(f"{tag}/terminal-box")
    if box is not None and box.get("centre") is not None:
        x, y, z = box["centre"]
        return (x, y, z + (box.get("size") or (0, 0, 0))[2] / 2)
    motor = parts.get(f"{tag}/motor")
    if motor is not None and motor.get("start") is not None:
        a, b = motor["start"], motor["end"]
        top = max(a[2], b[2]) + (motor.get("radius") or 0.0)
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, top)
    x0, y0, _, x1, y1, z1 = item["bbox"]
    return ((x0 + x1) / 2, (y0 + y1) / 2, z1)


def entry_problem(entry: Any, bbox: list[float]) -> str:
    """Why a motor's ``cable_entry`` cannot be beside an item of *bbox* (``[x0, y0, z0, x1, y1,
    z1]``), with the hint's facts; '' when it can."""
    x0, y0, _, x1, y1, _ = bbox
    if entry.point is not None:
        x, y = entry.point
        if x0 + 1e-6 < x < x1 - 1e-6 and y0 + 1e-6 < y < y1 - 1e-6:
            return (
                f"its point [{x:g}, {y:g}] is inside the item's footprint "
                f"[{x0:g}, {y0:g}, {x1:g}, {y1:g}]: the tray would end over the machine"
            )
        return ""
    half = ((x1 - x0) if entry.side in ("north", "south") else (y1 - y0)) / 2
    offset = entry.offset_m or 0.0
    if abs(offset) > half + 1e-6:
        return (
            f"offset_m {offset:g} is beyond the {entry.side} side, which is {2 * half:g} m long "
            f"(at most {half:g} m from its middle)"
        )
    return ""


def entry_point(entry: Any, bbox: list[float], clearance: float) -> tuple[float, float]:
    """The plan point where a tray ends for *entry* beside an item of *bbox*; *clearance* out
    from the side when the entry gives none (see :class:`~chemeascode.domains.control.schemas.
    CableEntry`)."""
    if entry.point is not None:
        return (float(entry.point[0]), float(entry.point[1]))
    x0, y0, _, x1, y1, _ = bbox
    c = clearance if entry.clearance_m is None else entry.clearance_m
    offset = entry.offset_m or 0.0
    xm, ym = (x0 + x1) / 2 + offset, (y0 + y1) / 2 + offset
    return {
        "north": (xm, y1 + c),
        "south": (xm, y0 - c),
        "east": (x1 + c, ym),
        "west": (x0 - c, ym),
    }[entry.side]


def _peak(loads: list[tuple[float, float, float]], lo: float, hi: float) -> float:
    """The largest cross-section *loads* (``(lo, hi, area)`` along a rack) put on one piece of
    ``[lo, hi]``; at the point *lo* for an empty span."""
    if hi - lo <= 1e-6:
        return sum(area for a, b, area in loads if a - 1e-9 <= lo <= b + 1e-9)
    stops = sorted({lo, hi, *(s for a, b, _ in loads for s in (a, b) if lo < s < hi)})
    return max(
        sum(area for a, b, area in loads if a < (p + q) / 2 < b)
        for p, q in zip(stops, stops[1:], strict=False)
    )


def _manhattan(a: Vec, b: Vec) -> float:
    return sum(abs(a[i] - b[i]) for i in range(3))


def _width(cables: list[CableType], fill_max: float, rules: TrayRuleSet) -> tuple[float, float]:
    """The tray width for *cables* (m) and its fill."""
    area = sum(c.area_mm2 for c in cables)
    depth = rules.depth_mm
    for width in rules.widths_mm:
        if area <= width * depth * fill_max + 1e-9:
            return width / 1000, area / (width * depth)
    width = rules.widths_mm[-1]
    return width / 1000, area / (width * depth)


def _along(points: list[tuple[float, float]], s: float) -> tuple[float, float, float, float] | None:
    """The point at arc length *s* of a polyline and the unit direction there, ``(x, y, ux,
    uy)``: the polyline's end beyond its length; None for a polyline without length."""
    found = None
    run = 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = math.dist(a, b)
        if length <= 1e-9:
            continue
        t = min(max((s - run) / length, 0.0), 1.0)
        found = (
            a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            (b[0] - a[0]) / length,
            (b[1] - a[1]) / length,
        )
        if run + length >= s - 1e-9:
            break
        run += length
    return found


def _run_parts(tray_id: str, points: list[Vec], width: float, depth: float, material: str):
    """One box per straight run of a tray's bottom centreline."""
    parts = []
    for k, (a, b) in enumerate(zip(points, points[1:], strict=False)):
        length = dist(a, b)
        if length <= 1e-6:
            continue
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2)
        if abs(a[2] - b[2]) > 1e-6 and math.hypot(b[0] - a[0], b[1] - a[1]) <= 1e-6:
            centre, size, angle = mid, (width, depth, length), 0.0
        else:
            angle = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
            centre = (mid[0], mid[1], mid[2] + depth / 2)
            size = (math.hypot(b[0] - a[0], b[1] - a[1]), width, depth)
        parts.append(
            {
                "id": f"{tray_id}/run-{k}",
                "kind": "box",
                "material": material,
                "centre": centre,
                "size": size,
                "rotation_deg": angle,
            }
        )
    return parts


class Cabling:
    """Builds the cabling sections of a model document (see the module text)."""

    def __init__(
        self,
        document: dict[str, Any],
        electrical: Any,
        motors: list[Any],
        functions: list[Any],
        instruments: Any,
        trays: Any,
        plan: Any,
        routing_rules: RoutingRules | None = None,
        files: dict[str, str] | None = None,
    ) -> None:
        self.document = document
        self.electrical = electrical
        self.motors = motors
        self.functions = functions
        self.instruments = instruments
        self.rules = _rules(trays)
        self.plan = plan
        self.routing_rules = routing_rules or RoutingRules()
        self.files = files or {}
        self.missing: list[dict[str, str]] = []
        self.items = {e["tag"]: e for e in document.get("equipment", [])}
        self.rooms: dict[str, Vec] = {}
        self.room_kind: dict[str, str] = {}
        self.network = None
        self.tiers: dict[str, float] = {}
        self.power_trays: dict[str, list[str]] = {}
        racks = list(plan.racks) if plan is not None else []
        self.racks = {rack.id: rack for rack in racks}
        if racks:
            from chemeascode.domains.spatial.layout_distances import RackNetwork

            self.network = RackNetwork(racks)
            declared = {tier.rack: tier.elevation for tier in self.rules.tiers}
            #: The voltage class of each power tray of the racks with power_trays.
            self.power_trays = {
                p.rack: p.classes for p in self.rules.power_trays if p.rack in self.racks
            }
            for rack in racks:
                top = max(rack.levels) if rack.levels else 0.0
                self.tiers[rack.id] = declared.get(rack.id, top + self.rules.tier_gap_m)
        self._router = None
        from chemeascode.domains.spatial.criteria import criteria

        #: A crane lane's margin beside its load: a cable_entry's default clearance takes it.
        self.lane_margin = criteria(plan).lane_margin_m

    # -- the router of the legs ---------------------------------------------------------

    @property
    def router(self) -> Any:
        if self._router is None:
            from chemeascode.domains.spatial.routing import Router
            from chemeascode.domains.spatial.schemas import Routing

            base = self.routing_rules.model_dump()
            base.update(spacing_m=self.rules.spacing_m, grid_m=self.rules.grid_m, vents=[])
            routing = Routing(rules=RoutingRules.model_validate(base))
            router = Router(self.document, [], None, routing, None, self.plan)
            for pipe in self.document.get("pipes", []):
                r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
                points = [tuple(p) for p in pipe["points"]]
                for a, b in zip(points, points[1:], strict=False):
                    if dist(a, b) > 1e-9:
                        router.pipes_index.add(Capsule(pipe["id"], a, b, r), "pipe")
            self._router = router
        return self._router

    def _block(self, tray_id: str, points: list[Vec], width: float, extra: float = 0.0) -> None:
        """File a routed tray with the router, so the legs after it keep clear of it."""
        r = width / 2 + extra
        for a, b in zip(points, points[1:], strict=False):
            if dist(a, b) > 1e-9:
                self.router.pipes_index.add(Capsule(tray_id, a, b, r), "tray")

    # -- ends ---------------------------------------------------------------------------

    def _missing(self, tag: str, kind: str, reason: str) -> None:
        self.missing.append({"tag": tag, "kind": kind, "reason": reason})

    def room_exits(self) -> None:
        """The exit point of every room (see the module text)."""
        buildings = {b["id"]: b for b in self.document.get("buildings", [])}
        by_building: dict[str, list[Any]] = {}
        for room in self.electrical.rooms:
            self.room_kind[room.id] = room.kind
            if room.point is not None:
                self.rooms[room.id] = tuple(room.point)  # type: ignore[assignment]
            elif room.building in buildings:
                by_building.setdefault(room.building, []).append(room)
        for building_id, rooms in sorted(by_building.items()):
            building = buildings[building_id]
            x0, y0, x1, y1 = building["footprint"]
            centre = ((x0 + x1) / 2, (y0 + y1) / 2)
            target = centre
            if self.network is not None:
                best = None
                for rack_id in sorted(self.racks):
                    d, q, _ = self.network.project(rack_id, centre)
                    if best is None or d < best[0]:
                        best = (d, q)
                assert best is not None
                target = best[1]
            sides = [
                ((0.0, -1.0), ((x0 + x1) / 2, y0), (1.0, 0.0)),
                ((1.0, 0.0), (x1, (y0 + y1) / 2), (0.0, 1.0)),
                ((0.0, 1.0), ((x0 + x1) / 2, y1), (-1.0, 0.0)),
                ((-1.0, 0.0), (x0, (y0 + y1) / 2), (0.0, -1.0)),
            ]
            vx, vy = target[0] - centre[0], target[1] - centre[1]
            normal, middle, along = max(sides, key=lambda s: s[0][0] * vx + s[0][1] * vy)
            top = building["heights"][1]
            z = min(self.rules.entry_elevation_m, max(top - 0.3, 0.5))
            n = len(rooms)
            for k, room in enumerate(sorted(rooms, key=lambda r: r.id)):
                shift = (k - (n - 1) / 2) * ROOM_PITCH
                self.rooms[room.id] = (
                    middle[0] + normal[0] * ROOM_OUT + along[0] * shift,
                    middle[1] + normal[1] * ROOM_OUT + along[1] * shift,
                    z,
                )

    def _area(self, p: Vec) -> str | None:
        if self.plan is None:
            return None
        from chemeascode.domains.spatial.layout_distances import area_of

        return area_of(self.plan, (p[0], p[1]))

    def _sensing_points(self) -> dict[tuple[str, str], Vec]:
        """Points of the model objects an instrument may measure, by (sheet, DEXPI id)."""
        found: dict[tuple[str, str], Vec] = {}
        for item in self.document.get("equipment", []):
            sheet = item["refs"].get("sheet") or ""
            for nozzle in item["nozzles"]:
                dexpi = nozzle["refs"].get("dexpi")
                if dexpi:
                    found.setdefault((sheet, dexpi), tuple(nozzle["point"]))  # type: ignore[arg-type]
            dexpi = item["refs"].get("dexpi")
            if dexpi:
                x0, y0, z0, x1, y1, z1 = item["bbox"]
                found.setdefault((sheet, dexpi), ((x0 + x1) / 2, (y0 + y1) / 2, min(z1, z0 + 1.5)))
        for pipe in self.document.get("pipes", []):
            sheet = pipe["refs"].get("sheet") or ""
            points = [tuple(p) for p in pipe["points"]]
            point, _ = point_at(points, polyline_length(points) / 2)  # type: ignore[arg-type]
            found.setdefault((sheet, pipe["segment"]), point)
        for item in self.document.get("inline", []):
            sheet = item["refs"].get("sheet") or ""
            dexpi = item["refs"].get("dexpi")
            if dexpi:
                found.setdefault((sheet, dexpi), tuple(item["point"]))  # type: ignore[arg-type]
        return found

    def devices(self) -> list[Device]:
        """Every instrument and actuated valve that needs a field cable, with its point."""
        entries = {e.tag: e for e in self.electrical.instruments}
        points = self._sensing_points()
        found: dict[str, Device] = {}
        drawn: dict[str, Any] = {}
        for function in self.functions:
            drawn.setdefault(function.tag, function)
        listed = [i.tag.strip() for i in getattr(self.instruments, "instruments", None) or ()]
        for tag in [*drawn, *[t for t in listed if t not in drawn]]:
            entry = entries.get(tag)
            if entry is not None and entry.skip:
                continue
            function = drawn.get(tag)
            if function is not None and not function.cabled and entry is None:
                continue  # a local gauge or a function without a sensor in the field
            point = tuple(entry.point) if entry is not None and entry.point else None
            if point is None and function is not None and function.sensing:
                point = points.get((function.sheet, function.sensing))
            reason = ""
            if point is None:
                if function is None:
                    reason = "drawn on no P&ID: give its point in the electrical list"
                elif not function.sensing:
                    reason = "its P&ID function measures nothing (no SensingLocation)"
                else:
                    reason = f"the model does not place what it measures ({function.sensing})"
            found[tag] = Device(tag, "transmitter", point, reason=reason)  # type: ignore[arg-type]
        for item in self.document.get("inline", []):
            tag = item.get("tag")
            kind = actuated_valve(tag, item.get("dexpi_class") or "")
            if not tag or kind is None or tag in found:
                continue
            entry = entries.get(tag)
            if entry is not None and entry.skip:
                continue
            point = tuple(entry.point) if entry is not None and entry.point else item["point"]
            found[tag] = Device(tag, kind, tuple(point))  # type: ignore[arg-type]
        for tag, entry in entries.items():
            if tag not in found and not entry.skip and entry.point is not None:
                found[tag] = Device(tag, "transmitter", tuple(entry.point))  # type: ignore[arg-type]
        for device in found.values():
            entry = entries.get(device.tag)
            device.jb = entry.jb if entry is not None else None
            if device.point is not None:
                device.area = self._area(device.point)
        return [found[tag] for tag in sorted(found)]

    def _free_spot(self, x: float, y: float, z: float) -> Vec:
        """The nearest point to (x, y) at height *z* where a junction box stands clear."""
        router = self.router
        hx, hy, hz = (s / 2 + 0.3 for s in JB_SIZE)

        racks = []
        if self.plan is not None:
            from chemeascode.domains.spatial.layout_validate import strip

            for rack in self.plan.racks:
                racks += strip(rack.points, rack.width + 2.0)

        def clear(p: Vec) -> bool:
            from chemeascode.domains.spatial.layout_distances import _inside

            if any(_inside((p[0], p[1]), polygon) for polygon in racks):
                return False  # not under a rack: its drop would cross the pipe tiers
            box = (p[0] - hx, p[1] - hy, 0.0, p[0] + hx, p[1] + hy, p[2] + hz)
            for index in (router.static, router.pipes_index):
                for solid, _, kind in index.near(box, 0.0):
                    if kind == "road":
                        continue
                    probe = Box("jb", (p[0], p[1], (p[2] + hz) / 2), (2 * hx, 2 * hy, p[2] + hz))
                    if _solids_touch(solid, probe):
                        return False
            return True

        for ring in range(16):
            candidates = [(x, y)] if ring == 0 else []
            for i in range(-ring, ring + 1):
                for j in (-ring, ring):
                    candidates += [(x + i, y + j), (x + j, y + i)]
            for cx, cy in sorted(set(candidates), key=lambda c: (math.dist(c, (x, y)), c)):
                p = (cx, cy, z)
                if clear(p):
                    return p
        return (x, y, z)

    def junction_boxes(self, devices: list[Device]) -> list[dict[str, Any]]:
        """Assign every device to a junction box (see the module text); the boxes."""
        defaults = self.electrical.defaults
        declared = list(self.electrical.junction_boxes)
        room = control_room(self.electrical)
        boxes: dict[str, dict[str, Any]] = {}
        for jb in declared:
            boxes[jb.tag] = {
                "tag": jb.tag,
                "point": tuple(jb.point) if jb.point is not None else None,
                "area": jb.area,
                "room": jb.room or room,
                "capacity": jb.capacity or defaults.jb_capacity,
                "devices": [],
                "source": "declared",
            }
        placed = [d for d in devices if d.point is not None]
        for device in devices:
            if device.point is None:
                self._missing(device.tag, "instrument", device.reason or "no position")
        free: list[Device] = []
        for device in placed:
            target = device.jb
            if target is None:
                target = next(
                    (
                        jb.tag
                        for jb in declared
                        if jb.instruments and matches(device.tag, jb.instruments)
                    ),
                    None,
                )
            if target is not None and target in boxes:
                boxes[target]["devices"].append(device)
            else:
                free.append(device)
        rest: list[Device] = []
        for device in free:
            best = None
            for tag, box in boxes.items():
                if box["point"] is None or len(box["devices"]) >= box["capacity"]:
                    continue
                d = dist(device.point, box["point"])  # type: ignore[arg-type]
                if d <= self.rules.jb_reach_m and (best is None or (d, tag) < best):
                    best = (d, tag)
            if best is not None:
                boxes[best[1]]["devices"].append(device)
            else:
                rest.append(device)
        groups: dict[str, list[Device]] = {}
        for device in rest:
            groups.setdefault(device.area or "", []).append(device)
        capacity = defaults.jb_capacity
        for area, members in sorted(groups.items()):
            members.sort(key=lambda d: (round(d.point[0], 1), round(d.point[1], 1), d.tag))  # type: ignore[index]
            for k in range(0, len(members), capacity):
                chunk = members[k : k + capacity]
                tag = f"JB-{area}-{k // capacity + 1}" if area else f"JB-{k // capacity + 1}"
                boxes[tag] = {
                    "tag": tag,
                    "point": None,
                    "area": area or None,
                    "room": room,
                    "capacity": capacity,
                    "devices": chunk,
                    "source": "generated",
                }
        found = []
        z = self.rules.jb_elevation_m
        for tag in sorted(boxes):
            box = boxes[tag]
            review = box["source"] == "generated" or box["point"] is None
            if box["point"] is None:
                members = box["devices"]
                if members:
                    x = sum(d.point[0] for d in members) / len(members)
                    y = sum(d.point[1] for d in members) / len(members)
                elif box["area"] and self.plan is not None:
                    area = next((a for a in self.plan.areas if a.id == box["area"]), None)
                    if area is None:
                        self._missing(
                            tag, "junction_box", f"area {box['area']} is not in the site plan"
                        )
                        continue
                    x, y = (area.box[0] + area.box[2]) / 2, (area.box[1] + area.box[3]) / 2
                else:
                    self._missing(tag, "junction_box", "no point, no area and no instruments")
                    continue
                box["point"] = self._free_spot(round(x * 2) / 2, round(y * 2) / 2, z)
            point = box["point"]
            x, y, zc = point
            entry = {
                "id": tag,
                "refs": {"tag": tag, "file": self.files.get("electrical")},
                "source": box["source"],
                "tag": tag,
                "point": point,
                "area": box["area"] or self._area(point),
                "instruments": sorted(d.tag for d in box["devices"]),
                "room": box["room"],
                "review_needed": True if review else None,
                "parts": [
                    {
                        "id": f"{tag}/box",
                        "kind": "box",
                        "material": "junction_box",
                        "centre": point,
                        "size": JB_SIZE,
                        "rotation_deg": 0.0,
                    },
                    {
                        "id": f"{tag}/stand",
                        "kind": "cylinder",
                        "material": "steel",
                        "start": (x, y, 0.0),
                        "end": (x, y, zc - JB_SIZE[2] / 2),
                        "radius": 0.04,
                        "lod": 2,
                    },
                ],
                "_devices": box["devices"],
            }
            found.append(entry)
        return found

    # -- trays --------------------------------------------------------------------------

    def _access(self, p: Vec) -> tuple[str, float] | None:
        """The rack a point takes (the nearest within ``rack_reach_m``) and the arc there."""
        if self.network is None:
            return None
        best = None
        for rack_id in sorted(self.racks):
            d, _, s = self.network.project(rack_id, (p[0], p[1]))
            if d <= self.rules.rack_reach_m and (best is None or d < best[0] - 1e-9):
                best = (d, rack_id, s)
        return (best[1], best[2]) if best is not None else None

    def _lane(self, rack_id: str, system: str, slot: int | None = None) -> float:
        """The offset of a tray's centreline from its rack's (left positive): power trays
        ``lane_fraction`` of the width to the left, the power trays of a rack with power_trays
        centred there, the largest width and ``spacing_m`` apart."""
        rack = self.racks[rack_id]
        d = self.rules.lane_fraction * rack.width
        if system != "power":
            return -d
        classes = self.power_trays.get(rack_id)
        if classes and slot is not None:
            pitch = self.rules.widths_mm[-1] / 1000 + self.rules.spacing_m
            d += (slot - (len(classes) - 1) / 2) * pitch
        return d

    def _letter(self, rack_id: str, slot: int | None) -> str:
        """The letter of power tray *slot* of a rack in tray ids ('' for a rack's only one)."""
        if slot is None or len(self.power_trays.get(rack_id) or ()) < 2:
            return ""
        return chr(ord("A") + slot)

    def _class(self, route: Route) -> str:
        voltage = route.cable.voltage_v
        return "hv" if voltage is not None and voltage > self.rules.lv_max_v + 1e-9 else "lv"

    def _assign(self, routes: list[Route], paths: dict[str, Any]) -> dict[tuple[str, str], int]:
        """The power tray of each cable on each rack with power_trays, by (tag, rack): the
        cables of the higher voltage class first, the larger first, each into a tray of its
        class (else an ``any`` tray, else any other), the one that stays under
        ``fill_max_power`` at the largest width, then the one whose fullest piece along the
        cable's span is emptiest, then the first."""
        spans: dict[str, dict[str, tuple[float, float]]] = {}
        for route in routes:
            for rack_id, s in paths[route.tag][2]:
                if rack_id in self.power_trays:
                    lo, hi = spans.setdefault(rack_id, {}).get(route.tag, (s, s))
                    spans[rack_id][route.tag] = (min(lo, s), max(hi, s))
        by_tag = {r.tag: r for r in routes}
        cap = self.rules.widths_mm[-1] * self.rules.depth_mm * self.rules.fill_max_power
        found: dict[tuple[str, str], int] = {}
        for rack_id in sorted(spans):
            classes = self.power_trays[rack_id]
            loads: list[list[tuple[float, float, float]]] = [[] for _ in classes]
            tags = sorted(
                spans[rack_id],
                key=lambda t: (self._class(by_tag[t]) != "hv", -by_tag[t].cable.area_mm2, t),
            )
            for tag in tags:
                lo, hi = spans[rack_id][tag]
                area = by_tag[tag].cable.area_mm2
                wanted = self._class(by_tag[tag])
                ranked = []
                for k, kind in enumerate(classes):
                    peak = _peak(loads[k], lo, hi) + area
                    match = 0 if kind == wanted else 1 if kind == "any" else 2
                    ranked.append((match == 2, peak > cap + 1e-9, match, round(peak, 6), k))
                k = min(ranked)[-1]
                loads[k].append((lo, hi, area))
                found[(tag, rack_id)] = k
        return found

    def _voltage(self, rack_id: str, slot: int | None) -> str | None:
        classes = self.power_trays.get(rack_id)
        if slot is None or not classes or classes[slot] == "any":
            return None
        return classes[slot]

    def _lane_points(
        self, rack_id: str, system: str, s0: float, s1: float, slot: int | None = None
    ) -> list[Vec]:
        from chemeascode.domains.spatial.layout_distances import offset_polyline, sub_polyline

        centre = [tuple(p) for p in self.racks[rack_id].points]
        lo, hi = min(s0, s1), max(s0, s1)
        piece = sub_polyline(centre, lo, hi)
        if len(piece) < 2:
            piece = [piece[0], piece[0]]
        lane = offset_polyline(piece, self._lane(rack_id, system, slot))
        z = self.tiers[rack_id]
        points = [(p[0], p[1], z) for p in lane]
        return points if s0 <= s1 else points[::-1]

    def _lane_point(self, rack_id: str, s: float, *, system: str, slot: int | None = None) -> Vec:
        """The point of the lane of *system* (power tray *slot*) at arc *s* of the rack's
        centreline."""
        points = [tuple(p) for p in self.racks[rack_id].points]
        d = self._lane(rack_id, system, slot)
        run = 0.0
        x, y, ux, uy = points[0][0], points[0][1], 1.0, 0.0
        for a, b in zip(points, points[1:], strict=False):
            length = math.dist(a, b)
            if length <= 1e-9:
                continue
            ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            t = min(max(s - run, 0.0), length)
            x, y = a[0] + ux * t, a[1] + uy * t
            if run + length >= s - 1e-9:
                break
            run += length
        return (x - uy * d, y + ux * d, self.tiers[rack_id])

    def route(self, routes: list[Route]) -> tuple[list[Tray], list[dict[str, Any]]]:
        """The trays of *routes* and the tray tier steel (see the module text): the topology
        and the trunks of both systems first, then the tier steel, then the legs off the racks,
        power before instrument."""
        plans = {
            system: self._plan(system, [r for r in routes if r.system == system])
            for system in ("power", "instrument")
        }
        trunks = [t for plan in plans.values() for t in plan["trunks"]]
        if self._raise_tiers(trunks):
            plans = {
                system: self._plan(system, [r for r in routes if r.system == system])
                for system in ("power", "instrument")
            }
            trunks = [t for plan in plans.values() for t in plan["trunks"]]
        tiers = self.tier_steel(trunks)
        extra = max(self.rules.separation_m - self.rules.spacing_m, 0.0)
        for tray in trunks:
            # one id per lane: a leg starting anywhere on it may leave it (the router's bubble)
            lane = f"lane:{tray.rack}:{tray.system}"
            if tray.rack is not None and self._letter(tray.rack, tray.slot):
                lane += f":{self._letter(tray.rack, tray.slot)}"
            self._block(
                lane, tray.points, tray.width, extra if tray.system == "instrument" else 0.0
            )
        trays: list[Tray] = list(trunks)
        taken = {t.id for t in trunks}
        for system in ("power", "instrument"):
            plan = plans[system]
            grow = extra if system == "instrument" else 0.0
            for tray, a, b in plan["legs"]:
                base, n = tray.id, 1
                while tray.id in taken:
                    n += 1
                    tray.id = f"{base}-{n}"
                taken.add(tray.id)
                tray.width = self._tray_width(tray, plan["by_tag"])
                r = max(tray.width, self.rules.depth_mm / 1000) / 2 + grow
                drop = None
                if tray.kind == "branch":
                    z = max(b[2], self.rules.branch_elevation_m)
                    if z > b[2] + 1e-6:
                        drop, b = b, (b[0], b[1], z)
                if dist(a, b) <= 1e-6:
                    points, method = [a, b], "astar"
                else:
                    points, method = self.router.leg(a, b, r)
                if drop is not None:
                    points = [*points, drop]
                tray.points = simplify([tuple(p) for p in points])  # type: ignore[misc]
                tray.method = method
                self._block(tray.id, tray.points, tray.width, grow)
                trays.append(tray)
            self._chains(plan, trays)
        return trays, tiers

    def _trunk_clear(self, tray: Tray, dz: float) -> bool:
        """Whether *tray* raised by *dz* keeps ``spacing_m`` from the items, walls, steel and
        pipes."""
        r = max(tray.width, self.rules.depth_mm / 1000) / 2 + self.rules.spacing_m
        points = [(p[0], p[1], p[2] + dz + self.rules.depth_mm / 2000) for p in tray.points]
        for a, b in zip(points, points[1:], strict=False):
            capsule = Capsule(tray.id, a, b, r)
            for index in (self.router.static, self.router.pipes_index):
                for solid, _, kind in index.near(capsule.aabb, 0.0):
                    if kind in ("zone", "road", "envelope", "stub"):
                        continue
                    if segment_distance(a, b, solid) < r - TOUCH:
                        return False
        return True

    def _raise_tiers(self, trunks: list[Tray]) -> bool:
        """Raise the tray tier of each rack without a ``tiers`` rule in steps of the grid (at
        most :data:`TIER_RAISE` m) until its trunks are clear; whether any tier moved."""
        declared = {tier.rack for tier in self.rules.tiers}
        moved = False
        step = self.rules.grid_m
        for rack_id in sorted({t.rack for t in trunks if t.rack and t.rack not in declared}):
            mine = [t for t in trunks if t.rack == rack_id]
            for k in range(round(TIER_RAISE / step) + 1):
                if all(self._trunk_clear(t, k * step) for t in mine):
                    if k:
                        self.tiers[rack_id] += k * step
                        moved = True
                    break
        return moved

    def _plan(self, system: str, routes: list[Route]) -> dict[str, Any]:
        """The topology of one system's cables: the rack path of each, the trunk pieces (with
        their points) and the legs to route."""
        trunks: dict[str, list[tuple[float, float, str]]] = {}
        links: dict[tuple[tuple[str, float], tuple[str, float]], list[str]] = {}
        room_access: dict[str, tuple[str, float] | None] = {}
        paths: dict[str, tuple[Any, Any, list[tuple[str, float]]]] = {}
        for route in routes:
            if route.room not in room_access:
                room_access[route.room] = self._access(route.start)
            start = room_access[route.room]
            end = self._access(route.end)
            nodes = None
            if start is not None and end is not None and self.network is not None:
                found = self.network._dijkstra(start[0], start[1], end[0], end[1])
                nodes = found[1] if found is not None else None
            if nodes is None:
                paths[route.tag] = (None, None, [])
                continue
            paths[route.tag] = (start, end, nodes)
            for (r1, s1), (r2, s2) in zip(nodes, nodes[1:], strict=False):
                if r1 == r2:
                    if abs(s2 - s1) > 1e-6:
                        trunks.setdefault(r1, []).append((min(s1, s2), max(s1, s2), route.tag))
                else:
                    key = tuple(sorted(((r1, s1), (r2, s2))))
                    links.setdefault(key, []).append(route.tag)  # type: ignore[arg-type]
        by_tag = {r.tag: r for r in routes}
        prefix = "PT" if system == "power" else "IT"
        # the power tray of each cable on a rack with power_trays (none elsewhere: its only one)
        slot_of = self._assign(routes, paths) if system == "power" else {}

        def order(slot: int | None) -> int:
            return -1 if slot is None else slot

        pieces: dict[tuple[str, int | None], list[tuple[float, float, str]]] = {}
        trunk_trays: list[Tray] = []
        for rack_id in sorted(trunks):
            by_slot: dict[int | None, list[tuple[float, float, str]]] = {}
            for span in trunks[rack_id]:
                by_slot.setdefault(slot_of.get((span[2], rack_id)), []).append(span)
            for slot in sorted(by_slot, key=order):
                spans = by_slot[slot]
                letter = self._letter(rack_id, slot)
                name = f"{prefix}-{rack_id}" + (f"-{letter}" if letter else "")
                stops = sorted({s for lo, hi, _ in spans for s in (lo, hi)})
                k = 0
                for a, b in zip(stops, stops[1:], strict=False):
                    if b - a <= 1e-6:
                        continue
                    cables = sorted({t for lo, hi, t in spans if lo <= a + 1e-9 and hi >= b - 1e-9})
                    if not cables:
                        continue
                    k += 1
                    tray = Tray(f"{name}-{k}", system, "trunk", cables, rack=rack_id)
                    tray.slot, tray.voltage = slot, self._voltage(rack_id, slot)
                    tray.points = self._lane_points(rack_id, system, a, b, slot)
                    tray.width = self._tray_width(tray, by_tag)
                    trunk_trays.append(tray)
                    pieces.setdefault((rack_id, slot), []).append((a, b, tray.id))
        legs: list[tuple[Tray, Vec, Vec]] = []
        link_ids: dict[Any, Tray] = {}
        for room in sorted(room_access):
            access = room_access[room]
            cables = sorted(r.tag for r in routes if r.room == room and paths[r.tag][2])
            if access is None or not cables:
                continue
            groups: dict[int | None, list[str]] = {}
            for tag in cables:
                groups.setdefault(slot_of.get((tag, access[0])), []).append(tag)
            for slot in sorted(groups, key=order):
                letter = self._letter(access[0], slot)
                tray = Tray(
                    f"{prefix}-{room}" + (f"-{letter}" if letter else ""),
                    system,
                    "room",
                    groups[slot],
                    voltage=self._voltage(access[0], slot),
                )
                end = self._lane_point(*access, system=system, slot=slot)
                legs.append((tray, by_tag[groups[slot][0]].start, end))
        for key, cables in sorted(links.items()):
            (r1, s1), (r2, s2) = key
            pairs: dict[tuple[int | None, int | None], list[str]] = {}
            for tag in sorted(set(cables)):
                pairs.setdefault((slot_of.get((tag, r1)), slot_of.get((tag, r2))), []).append(tag)
            for k1, k2 in sorted(pairs, key=lambda pair: (order(pair[0]), order(pair[1]))):
                letters = self._letter(r1, k1) + self._letter(r2, k2)
                voltages = {self._voltage(r1, k1), self._voltage(r2, k2)} - {None}
                tray = Tray(
                    f"{prefix}-{r1}-{r2}" + (f"-{letters}" if letters else ""),
                    system,
                    "link",
                    pairs[(k1, k2)],
                    voltage=voltages.pop() if len(voltages) == 1 else None,
                )
                link_ids[(key, k1, k2)] = tray
                legs.append(
                    (
                        tray,
                        self._lane_point(r1, s1, system=system, slot=k1),
                        self._lane_point(r2, s2, system=system, slot=k2),
                    )
                )
        for route in routes:
            start, end, nodes = paths[route.tag]
            tray = Tray(
                f"{prefix}-{route.to}",
                system,
                "branch",
                [route.tag],
                ends_at=route.owner,
                drop_to=route.terminal if route.entry else None,
            )
            if nodes:
                slot = slot_of.get((route.tag, end[0]))
                legs.append((tray, self._lane_point(*end, system=system, slot=slot), route.end))
            else:
                legs.append((tray, route.start, route.end))
        return {
            "system": system,
            "routes": routes,
            "by_tag": by_tag,
            "paths": paths,
            "pieces": pieces,
            "trunks": trunk_trays,
            "legs": legs,
            "links": link_ids,
            "slots": slot_of,
        }

    def _chains(self, plan: dict[str, Any], trays: list[Tray]) -> None:
        """Each cable's trays of one system, in order from its room."""
        rooms = {
            tag: t.id
            for t in trays
            if t.kind == "room" and t.system == plan["system"]
            for tag in t.cables
        }
        branches = {
            t.cables[0]: t.id for t in trays if t.kind == "branch" and t.system == plan["system"]
        }
        slot_of = plan["slots"]
        for route in plan["routes"]:
            start, end, nodes = plan["paths"][route.tag]
            if not nodes:
                route.trays = [branches[route.tag]]
                route.reason = "no rack in reach: fed directly from the room"
                continue
            chain = [rooms[route.tag]] if route.tag in rooms else []
            for (r1, s1), (r2, s2) in zip(nodes, nodes[1:], strict=False):
                if r1 != r2:
                    key = tuple(sorted(((r1, s1), (r2, s2))))
                    (q1, _), (q2, _) = key
                    slots = (slot_of.get((route.tag, q1)), slot_of.get((route.tag, q2)))
                    chain.append(plan["links"][(key, *slots)].id)
                    continue
                lo, hi = min(s1, s2), max(s1, s2)
                hits = [
                    (a, tid)
                    for a, b, tid in plan["pieces"].get((r1, slot_of.get((route.tag, r1))), [])
                    if a >= lo - 1e-9 and b <= hi + 1e-9 and b - a > 1e-6
                ]
                hits.sort(reverse=s2 < s1)
                chain += [tid for _, tid in hits]
            chain.append(branches[route.tag])
            route.trays = list(dict.fromkeys(chain))

    def _tray_width(self, tray: Tray, by_tag: dict[str, Route]) -> float:
        fill_max = (
            self.rules.fill_max_power if tray.system == "power" else self.rules.fill_max_instrument
        )
        return _width([by_tag[c].cable for c in tray.cables], fill_max, self.rules)[0]

    def tier_steel(self, trays: list[Tray]) -> list[dict[str, Any]]:
        """The steel of each rack tray tier that stands above the rack's pipe tiers: column
        extensions and a beam at each bent along the trunk's span."""
        from chemeascode.domains.spatial.layout_distances import _polyline_project
        from chemeascode.domains.spatial.structures import BEAM_LARGEST, BEAMS, Frame, section

        spans: dict[str, list[float]] = {}
        for tray in trays:
            if tray.kind != "trunk" or tray.rack is None:
                continue
            centre = [tuple(p) for p in self.racks[tray.rack].points]
            for p in (tray.points[0], tray.points[-1]):
                spans.setdefault(tray.rack, []).append(_polyline_project(centre, (p[0], p[1]))[2])
        found = []
        for rack_id in sorted(spans):
            rack = self.racks[rack_id]
            spacing = rack.bent_spacing_m or self.routing_rules.rack_bent_spacing_m
            top = max(rack.levels) if rack.levels else 0.0
            tier = self.tiers[rack_id]
            if any(abs(tier - level) < 1e-6 for level in rack.levels) or tier <= top:
                continue
            lo, hi = min(spans[rack_id]), max(spans[rack_id])
            points = [tuple(p) for p in rack.points]
            total = sum(math.dist(a, b) for a, b in zip(points, points[1:], strict=False))
            count = max(1, round(total / spacing))
            col = ("HEB300", 0.3, 0.3)
            beam = section([rack.width], BEAMS, BEAM_LARGEST, None)
            f = Frame((0.0, 0.0), 0.0)
            parts = []
            for k in range(count + 1):
                s = total * k / count
                if s < lo - spacing / 2 or s > hi + spacing / 2:
                    continue
                at = _along(points, s)
                if at is None:
                    continue
                x, y, ux, uy = at
                nx, ny = -uy, ux
                half = rack.width / 2 + col[1] / 2
                ends = [(x + nx * half, y + ny * half), (x - nx * half, y - ny * half)]
                for side, (px, py) in enumerate(ends):
                    parts.append(
                        f.member(
                            f"{rack_id}/tray-tier/bent-{k}/col-{side}",
                            (px, py, top),
                            (px, py, tier),
                            col,
                        )
                    )
                z = tier - beam[2] / 2
                parts.append(
                    f.member(
                        f"{rack_id}/tray-tier/bent-{k}/beam", (*ends[0], z), (*ends[1], z), beam
                    )
                )
            for part in parts:
                solid = part_solid(part, rack_id)
                if solid is not None:
                    self.router.static.add(solid, "steel")
            found.append(
                {
                    "id": f"{rack_id}/tray-tier",
                    "refs": {"file": self.files.get("trays") or self.files.get("site_plan")},
                    "source": "generated",
                    "rack": rack_id,
                    "elevation": tier,
                    "parts": parts,
                }
            )
        return found

    # -- the whole ----------------------------------------------------------------------

    def build(self) -> dict[str, Any]:
        """The model sections ``tray_tiers``, ``trays``, ``junction_boxes``, ``cables`` and
        ``cabling``."""
        self.room_exits()
        routes: list[Route] = []
        cables: list[dict[str, Any]] = []
        for motor in self.motors:
            if motor.skip:
                continue
            kind = motor.kind
            what = "motor" if kind == "motor" else "feeder"
            item = self.items.get(motor.item) if motor.item else None
            if motor.point is not None:
                terminal = tuple(motor.point)
            elif item is not None:
                terminal = _terminal(item)
            else:
                self._missing(motor.tag, what, f"{motor.item} is not placed in the layout")
                continue
            if motor.room is None:
                self._missing(motor.tag, what, "fed from no room (electrical list rooms)")
                continue
            if motor.room not in self.rooms:
                self._missing(motor.tag, what, f"room {motor.room} has no building in the layout")
                continue
            cable = power_cable(motor.power_kw, motor.voltage_v, motor.power_factor)
            end = (terminal[0], terminal[1], terminal[2] + DROP)
            entry = motor.cable_entry if item is not None else None
            if entry is not None:
                why = entry_problem(entry, item["bbox"])  # type: ignore[index]
                if why:
                    self._missing(motor.tag, what, f"cable_entry: {why}")
                    continue
                width = _width([cable], self.rules.fill_max_power, self.rules)[0]
                clearance = self.lane_margin + width / 2 + self.rules.spacing_m
                x, y = entry_point(entry, item["bbox"], clearance)  # type: ignore[index]
                z = terminal[2] + DROP if entry.elevation_m is None else entry.elevation_m
                end = (x, y, z)
            basis = f"power: {motor.basis}" + (f" ({motor.source})" if motor.source else "")
            if motor.assumed:
                basis += ", ASSUMED"
            if motor.power_factor is not None:
                basis += f"; power factor {motor.power_factor:g}" + (
                    " ASSUMED (resistive load)" if motor.power_factor_assumed else ""
                )
            routes.append(
                Route(
                    tag=f"C-{motor.tag}",
                    system="power",
                    kind=what,
                    room=motor.room,
                    to=motor.tag,
                    cable=cable,
                    start=self.rooms[motor.room],
                    end=end,
                    terminal=terminal,  # type: ignore[arg-type]
                    owner=motor.item,
                    power_kw=motor.power_kw,
                    basis=basis,
                    entry=entry is not None,
                )
            )
        devices = self.devices()
        boxes = self.junction_boxes(devices)
        spare = self.electrical.defaults.spare_pairs
        for box in boxes:
            members: list[Device] = box.pop("_devices")
            point = tuple(box["point"])
            for device in members:
                field_type = field_cable(device.kind)
                run = _manhattan(device.point, point)  # type: ignore[arg-type]
                cables.append(
                    self._cable(
                        f"IC-{device.tag}",
                        "instrument",
                        "field",
                        device.tag,
                        box["tag"],
                        device.point,  # type: ignore[arg-type]
                        point,  # type: ignore[arg-type]
                        field_type,
                        [],
                        run,
                        basis=field_type.basis,
                    )
                )
            if not members:
                continue
            room = box["room"]
            if room is None or room not in self.rooms:
                why = "no control room" if room is None else f"room {room} has no building"
                self._missing(box["tag"], "junction_box", f"{why}: no multipair cable")
                continue
            pairs = sum(field_cable(d.kind).pairs or 1 for d in members)
            cable = multipair_cable(pairs, spare)
            terminal = (point[0], point[1], point[2] + JB_SIZE[2] / 2)
            routes.append(
                Route(
                    tag=f"MC-{box['tag']}",
                    system="instrument",
                    kind="multipair",
                    room=room,
                    to=box["tag"],
                    cable=cable,
                    start=self.rooms[room],
                    end=(terminal[0], terminal[1], terminal[2] + DROP),
                    terminal=terminal,
                    basis=f"{pairs} pairs in use, {spare:.0%} spare; {cable.basis}",
                )
            )
        trays, tiers = self.route(routes)
        lengths = {t.id: polyline_length(t.points) for t in trays}
        by_id = {t.id: t for t in trays}
        for route in routes:
            run = sum(lengths[t] for t in route.trays)
            run += _manhattan(route.end, route.terminal)
            unrouted = [t for t in route.trays if by_id[t].method == "direct"]
            reason = route.reason
            if unrouted:
                reason = f"tray {unrouted[0]} found no clear way (direct, review it)"
            cables.append(
                self._cable(
                    route.tag,
                    route.system,
                    route.kind,
                    route.room,
                    route.to,
                    route.start,
                    route.terminal,
                    route.cable,
                    route.trays,
                    run,
                    power_kw=route.power_kw,
                    basis=route.basis or route.cable.basis,
                    review=bool(unrouted) or route.power_kw is None and route.kind != "multipair",
                    reason=reason or None,
                )
            )
        cable_types = {c["tag"]: c for c in cables}
        tray_entries = []
        for tray in trays:
            width = tray.width
            depth = self.rules.depth_mm / 1000
            fill_max = (
                self.rules.fill_max_power
                if tray.system == "power"
                else self.rules.fill_max_instrument
            )
            area = sum(
                cable_types[c]["count"] * math.pi * cable_types[c]["od_mm"] ** 2 / 4
                for c in tray.cables
            )
            refs: dict[str, Any] = {"file": self.files.get("electrical")}
            if tray.ends_at:
                refs["tag"] = tray.ends_at
            tray_entries.append(
                {
                    "id": tray.id,
                    "refs": refs,
                    "source": "generated",
                    "system": tray.system,
                    "kind": tray.kind,
                    "points": tray.points,
                    "drop_to": tray.drop_to,
                    "width": width,
                    "depth": depth,
                    "length": lengths[tray.id],
                    "cables": tray.cables,
                    "fill": round(area / (width * 1000 * self.rules.depth_mm), 3),
                    "fill_max": fill_max,
                    "rack": tray.rack,
                    "voltage": tray.voltage,
                    "method": tray.method,
                    "review_needed": True if tray.method == "direct" else None,
                    "parts": _run_parts(tray.id, tray.points, width, depth, f"tray_{tray.system}"),
                }
            )
        cables.sort(key=lambda c: c["tag"])
        motors = [m for m in self.motors if m.kind == "motor"]
        summary = {
            "cables": len(cables),
            "power": sum(1 for c in cables if c["system"] == "power"),
            "instrument": sum(1 for c in cables if c["system"] == "instrument"),
            "motors": len(motors),
            "motors_skipped": sum(1 for m in motors if m.skip),
            "instruments": len(devices),
            "junction_boxes": len(boxes),
            "trays": len(tray_entries),
            "tray_length_m": round(sum(lengths.values()), 3),
            "cable_length_m": round(sum(c["length"] for c in cables), 3),
            "rules": {
                "separation_m": self.rules.separation_m,
                "spacing_m": self.rules.spacing_m,
                "fill_max_power": self.rules.fill_max_power,
                "fill_max_instrument": self.rules.fill_max_instrument,
                "avoid_zones": list(self.rules.avoid_zones),
                "support_span_m": self.rules.support_span_m,
                "support_reach_m": self.rules.support_reach_m,
            },
            "missing": sorted(self.missing, key=lambda m: (m["kind"], m["tag"])),
        }
        if self.power_trays:
            summary["rules"]["power_trays"] = dict(sorted(self.power_trays.items()))
            summary["rules"]["lv_max_v"] = self.rules.lv_max_v
        return {
            "tray_tiers": tiers,
            "trays": tray_entries,
            "junction_boxes": boxes,
            "cables": cables,
            "cabling": summary,
        }

    def _cable(
        self,
        tag: str,
        system: str,
        kind: str,
        start_tag: str,
        end_tag: str,
        a: Vec,
        b: Vec,
        cable: CableType,
        trays: list[str],
        run: float,
        *,
        power_kw: float | None = None,
        basis: str = "",
        review: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        length = run * (1 + self.rules.slack) + 2 * self.rules.termination_m
        return {
            "id": tag,
            "refs": {"tag": end_tag, "file": self.files.get("electrical")},
            "source": "generated",
            "tag": tag,
            "system": system,
            "kind": kind,
            "from": start_tag,
            "to": end_tag,
            "from_point": a,
            "to_point": b,
            "size": cable.size,
            "od_mm": cable.od_mm,
            "count": cable.count,
            "voltage_v": cable.voltage_v,
            "power_kw": power_kw,
            "current_a": cable.current_a,
            "pairs": cable.pairs,
            "trays": trays,
            "route_length": run,
            "length": math.ceil(length),
            "basis": basis or None,
            "review_needed": True if review else None,
            "reason": reason,
        }


def _solids_touch(solid: Any, box: Box) -> bool:
    from chemeascode.domains.spatial.geometry3d import Cylinder, Sphere

    if isinstance(solid, Cylinder | Capsule):
        return segment_distance(solid.a, solid.b, box) < solid.r - TOUCH
    if isinstance(solid, Sphere):
        return box.distance(solid.centre) < solid.r - TOUCH
    aa, bb = solid.aabb, box.aabb
    return all(min(aa[i + 3], bb[i + 3]) - max(aa[i], bb[i]) > TOUCH for i in range(3))


def build_cabling(
    document: dict[str, Any],
    electrical: Any,
    motors: list[Any],
    functions: list[Any],
    instruments: Any = None,
    trays: Any = None,
    plan: Any = None,
    routing_rules: RoutingRules | None = None,
    files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """The cabling sections of *document* (see the module text)."""
    return Cabling(
        document, electrical, motors, functions, instruments, trays, plan, routing_rules, files
    ).build()


# ---------------------------------------------------------------------------
# Rules on the trays and cables
# ---------------------------------------------------------------------------


def _capsules(tray: dict[str, Any]) -> list[Capsule]:
    r = tray["width"] / 2
    points = [tuple(p) for p in tray["points"]]
    return [
        Capsule(tray["id"], a, b, r)  # type: ignore[arg-type]
        for a, b in zip(points, points[1:], strict=False)
        if dist(a, b) > 1e-9  # type: ignore[arg-type]
    ]


def _box(a: tuple[float, ...], b: tuple[float, ...]) -> list[float]:
    return [round(min(a[i], b[i]), 3) for i in range(3)] + [
        round(max(a[i + 3], b[i + 3]), 3) for i in range(3)
    ]


def _zones(model: dict[str, Any], trays: list[dict[str, Any]], rules: dict, add: Any) -> None:
    """``tray-zone``: a tray run inside a zone of a kind in ``avoid_zones``."""
    from chemeascode.domains.spatial.zones import volume_solid

    kinds = set(rules.get("avoid_zones", ("oxygen_enriched", "hazardous")))
    for zone in model.get("zones", []):
        hint_only = zone.get("kind") == "oxygen_deficient" and zone.get("kind") not in kinds
        if zone.get("kind") not in kinds and not hint_only:
            continue
        solids = [volume_solid(v, zone["id"]) for v in zone.get("volumes", [])]
        for tray in trays:
            for capsule in _capsules(tray):
                hit = next(
                    (
                        solid
                        for solid in solids
                        if all(
                            min(capsule.aabb[i + 3], solid.aabb[i + 3])
                            - max(capsule.aabb[i], solid.aabb[i])
                            > 0
                            for i in range(3)
                        )
                        and segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH
                    ),
                    None,
                )
                if hit is None:
                    continue
                kind = zone["kind"].replace("_", "-")
                if hint_only:
                    add(
                        "info",
                        "tray-zone",
                        f"{tray['system']} tray {tray['id']} runs inside the {kind} zone "
                        f"{zone['id']} (oxygen_deficient is not in avoid_zones)",
                        [tray["id"], zone["id"]],
                        _box(capsule.aabb, hit.aabb),
                        "where people would work on the trays in an inert vent zone, add "
                        "oxygen_deficient to avoid_zones in electrical/tray-rules.yaml (it is "
                        "then a warning), or move the tray or the vent",
                        key=f"{tray['id']}+{zone['id']}",
                    )
                    break
                add(
                    "warning",
                    "tray-zone",
                    f"{tray['system']} tray {tray['id']} runs inside the {kind} zone {zone['id']}",
                    [tray["id"], zone["id"]],
                    _box(capsule.aabb, hit.aabb),
                    "move the tray out of the zone (another tier or lane, a tiers rule in "
                    "electrical/tray-rules.yaml), or raise the release point; else record the "
                    "cable sheath and glands chosen for the zone and accept the finding",
                    key=f"{tray['id']}+{zone['id']}",
                )
                break


def _spans(
    model: dict[str, Any], trays: list[dict[str, Any]], rules: dict, steel: Any, add: Any
) -> None:
    """``tray-span``: a level tray run longer than ``support_span_m`` without steel (rack and
    tray tier members, structure steel and walls, building walls) within ``support_reach_m``."""
    from chemeascode.domains.spatial.geometry3d import Index, point_segment

    span = float(rules.get("support_span_m", 6.0))
    reach = float(rules.get("support_reach_m", 1.0))
    walls = Index(4.0)
    for owner in model.get("structures", []):
        for part in owner.get("walls") or []:
            solid = part_solid(part, owner["id"])
            if solid is not None:
                walls.add(solid, part["id"])
    for building in model.get("buildings", []):
        for part in building.get("parts", []):
            if part.get("kind") == "box" and part.get("lod") is None:
                solid = part_solid(part, building["id"])
                if solid is not None:
                    walls.add(solid, part["id"])
    tiers = Index(4.0)
    for tier in model.get("tray_tiers") or []:
        for part in tier.get("parts", []):
            solid = part_solid(part, tier["id"])
            if solid is not None:
                tiers.add(solid, part["id"])
    for tray in trays:
        if tray.get("rack"):
            continue  # on a rack's tray tier: carried by its bents
        points = [tuple(p) for p in tray["points"]]
        worst = 0.0
        where: tuple[Vec, Vec] | None = None
        for a, b in zip(points, points[1:], strict=False):
            length = dist(a, b)  # type: ignore[arg-type]
            if abs(a[2] - b[2]) > 1e-6 or length <= span + 1e-6:
                continue
            r = tray["width"] / 2 + reach
            box = (
                min(a[0], b[0]) - r,
                min(a[1], b[1]) - r,
                min(a[2], b[2]) - r - tray.get("depth", 0.1),
                max(a[0], b[0]) + r,
                max(a[1], b[1]) + r,
                max(a[2], b[2]) + r,
            )
            stops = [0.0, length]
            for index in (steel, tiers, walls):
                for solid, _, _ in index.near(box, 0.0):
                    if isinstance(solid, Capsule):
                        d = segment_segment(a, b, solid.a, solid.b) - solid.r  # type: ignore[arg-type]
                        if d > reach + tray["width"] / 2 + 1e-6:
                            continue
                        # where along the run: the nearest of points along the member's axis
                        best = min(
                            (
                                tuple(
                                    solid.a[i] + (solid.b[i] - solid.a[i]) * k / 8 for i in range(3)
                                )
                                for k in range(9)
                            ),
                            key=lambda q: point_segment(q, a, b)[0],  # type: ignore[arg-type]
                        )
                        stops.append(point_segment(best, a, b)[1] * length)  # type: ignore[arg-type]
                    else:
                        samples = max(2, math.ceil(length / 0.5))
                        for k in range(samples + 1):
                            t = k / samples
                            p = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
                            if solid.distance(p) <= reach + tray["width"] / 2 + 1e-6:
                                stops.append(t * length)
            stops.sort()
            gap = max(q - p for p, q in zip(stops, stops[1:], strict=False))
            if gap > worst + 1e-9:
                worst, where = gap, (a, b)
        if worst > span + 1e-6 and where is not None:
            a, b = where
            add(
                "warning",
                "tray-span",
                f"{tray['system']} tray {tray['id']} runs {worst:.1f} m level with no steel "
                f"within {reach:g} m (> {span:g} m between supports, ASSUMED)",
                [tray["id"]],
                [round(min(a[i], b[i]), 3) for i in range(3)]
                + [round(max(a[i], b[i]), 3) for i in range(3)],
                "run the tray along a rack or structure, or declare support steel under it "
                "(a structure in layout/structures.yaml, posts or a rack); off the racks, a "
                "trench or buried cable at grade may serve instead",
                key=tray["id"],
                measured=worst,
            )


def cable_entry_findings(workspace: Any, model: dict[str, Any]) -> list[Finding]:
    """``cheme.electrical-cable-entry`` (error, on the electrical list's line): a motor's
    ``cable_entry`` that cannot be beside its placed item in *model* (a point inside the item's
    footprint, an offset beyond the side). The build gives that motor no cable
    (``cable-missing``) rather than end its tray over the machine."""
    from chemeascode.domains.control.electrical import ELECTRICAL_FILE
    from chemeascode.foundation.yamlsource import _compose, _yaml_line

    path = workspace.list_file("electrical")
    if path is None:
        return []
    electrical = workspace.parsed_lists(("electrical",)).get("electrical")
    if electrical is None:
        return []  # validate reports the schema error
    items = {e["tag"]: e for e in model.get("equipment", [])}
    document = None
    found = []
    for k, motor in enumerate(electrical.motors):
        item = items.get(motor.driven.strip())
        if motor.cable_entry is None or motor.skip or item is None:
            continue  # an item not placed: cable-missing says so
        why = entry_problem(motor.cable_entry, item["bbox"])
        if not why:
            continue
        if document is None:
            document = _compose(path)
        found.append(
            Finding(
                ELECTRICAL_FILE,
                "error",
                "cheme.electrical-cable-entry",
                f"cable_entry of the motor of {motor.driven}: {why}",
                line=_yaml_line(document, ["motors", k, "cable_entry"]),
                ids=[motor.driven],
                hint="give a side of the item (north, south, east, west) with offset_m within "
                "half its length, or a point outside its footprint, and rebuild",
                key=motor.driven,
            )
        )
    return found


def _fill_hint(tray: dict[str, Any], rules: dict[str, Any]) -> str:
    """The way out of a ``tray-fill`` finding on *tray*: on a rack's power trunk, as many
    power trays on the rack (``power_trays``) as its cables need; on a power room leg or link,
    more power trays on the racks it joins (it splits with them)."""
    tail = (
        "split the loads over more rooms, or allow a fuller tray in electrical/tray-rules.yaml "
        "with a reason"
    )
    kind = tray.get("kind")
    if tray["system"] != "power" or kind == "branch":
        return f"run a second tray beside it, {tail}"
    rack = tray.get("rack")
    if kind == "trunk" and rack:
        declared = (rules.get("power_trays") or {}).get(rack)
        need = (len(declared) if declared else 1) - 1 + math.ceil(tray["fill"] / tray["fill_max"])
        return (
            f"declare {need} power trays on rack {rack} in electrical/tray-rules.yaml "
            f"(power_trays: [{{rack: {rack}, trays: {need}}}], or one voltage class per tray, "
            f"e.g. [hv, hv, lv]): the build shares the cables out over them; else {tail}"
        )
    return (
        "declare more power trays on the rack it leads to (power_trays in "
        "electrical/tray-rules.yaml): its cables then split with the rack's trays; else " + tail
    )


def tray_findings(model: dict[str, Any]) -> list[Finding]:
    """``cheme.layout-tray-fill``, ``-tray-separation``, ``-tray-voltage``, ``-clash-tray``,
    ``-tray-zone``, ``-tray-span``, ``-cable-missing`` and ``-cable-unrouted`` on a model
    document (nothing without its ``trays``)."""
    trays = model.get("trays")
    cabling = model.get("cabling") or {}
    if trays is None:
        return []
    found: list[Finding] = []
    counts: dict[str, int] = {}

    def add(
        level: str,
        rule: str,
        message: str,
        ids: list[str],
        box,
        hint: str,
        key: str = "",
        measured: float | None = None,
    ):
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
                measured=None if measured is None else round(measured, 3),
            )
        )

    rules = cabling.get("rules") or {}
    separation = float(rules.get("separation_m", 0.3))
    for tray in trays:
        if tray["fill"] > tray["fill_max"] + 1e-9:
            add(
                "warning",
                "tray-fill",
                f"tray {tray['id']} is {tray['fill']:.0%} full at {tray['width'] * 1000:g} mm "
                f"(at most {tray['fill_max']:.0%}): {len(tray['cables'])} cables",
                [tray["id"]],
                None,
                _fill_hint(tray, rules),
                key=tray["id"],
            )
    lv_max = float(rules.get("lv_max_v", 1000.0))
    voltages = {c["tag"]: c.get("voltage_v") for c in model.get("cables") or []}
    for tray in trays:
        if tray.get("voltage") is None:
            continue
        other = [
            tag
            for tag in tray["cables"]
            if voltages.get(tag) is not None
            and ("hv" if voltages[tag] > lv_max + 1e-9 else "lv") != tray["voltage"]
        ]
        if other:
            add(
                "warning",
                "tray-voltage",
                f"{tray['voltage']} power tray {tray['id']} carries {len(other)} cable(s) of "
                f"the other voltage class (limit {lv_max:g} V): {', '.join(other[:5])}",
                [tray["id"], *other[:5]],
                None,
                "give the rack a power tray of their class or an any tray (power_trays in "
                "electrical/tray-rules.yaml) and rebuild; HV and LV cables share a tray only "
                "with a fixed barrier between them (accept the finding with that reason)",
                key=tray["id"],
            )
    power = [(c, t) for t in trays if t["system"] == "power" for c in _capsules(t)]
    instrument = [(c, t) for t in trays if t["system"] == "instrument" for c in _capsules(t)]
    seen: set[tuple[str, str]] = set()
    for a, ta in power:
        for b, tb in instrument:
            pair = (ta["id"], tb["id"])
            if pair in seen:
                continue
            reach = a.r + b.r + separation
            if any(
                a.aabb[i] - reach > b.aabb[i + 3] or b.aabb[i] - reach > a.aabb[i + 3]
                for i in range(3)
            ):
                continue
            gap = segment_segment(a.a, a.b, b.a, b.b) - a.r - b.r
            if gap < separation - 0.01:
                seen.add(pair)
                add(
                    "warning",
                    "tray-separation",
                    f"power tray {ta['id']} and instrument tray {tb['id']} are {max(gap, 0.0):.2f} "
                    f"m apart (< {separation:g} m)",
                    [ta["id"], tb["id"]],
                    _box(a.aabb, b.aabb),
                    "move one of them (a tiers rule, another room exit), or put a metal divider "
                    "between them and accept the finding with that reason",
                    key=f"{ta['id']}+{tb['id']}",
                )
    # clashes with items, pipes and steel (LOD 1 solids)
    from chemeascode.domains.spatial.geometry3d import Index

    parts = Index(4.0)
    for item in model.get("equipment", []):
        for part in item["parts"]:
            solid = part_solid(part, item["tag"])
            if solid is not None:
                parts.add(solid, part["id"])
    steel = Index(4.0)
    for owner in (*model.get("structures", []), *model.get("racks", [])):
        for part in owner.get("parts", []):
            if part["kind"] == "member":
                solid = part_solid(part, owner["id"])
                if solid is not None:
                    steel.add(solid, part["id"])
    pipes = Index(4.0)
    for pipe in model.get("pipes", []):
        r = pipe["od"] / 2 + pipe.get("insulation_mm", 0.0) / 1000
        points = [tuple(p) for p in pipe["points"]]
        for a, b in zip(points, points[1:], strict=False):
            if dist(a, b) > 1e-9:  # type: ignore[arg-type]
                pipes.add(Capsule(pipe["id"], a, b, r), pipe["id"])  # type: ignore[arg-type]
    for tray in trays:
        # a branch ending at a cable_entry stands beside its item: none of it may touch it
        own = None if tray.get("drop_to") else tray["refs"].get("tag")
        capsules = _capsules(tray)
        hit: set[str] = set()
        for k, capsule in enumerate(capsules):
            last = k == len(capsules) - 1
            for index, what in ((parts, "item"), (steel, "steel"), (pipes, "pipe")):
                for solid, box, ref in index.near(capsule.aabb, 0.0):
                    if what == "item" and solid.id == own and last:
                        continue  # the branch's drop onto the item it feeds
                    name = ref if what != "item" else f"{solid.id} ({ref})"
                    if name in hit:
                        continue
                    if what == "pipe":
                        close = segment_segment(capsule.a, capsule.b, solid.a, solid.b) < (
                            capsule.r + solid.r - TOUCH
                        )
                    else:
                        close = segment_distance(capsule.a, capsule.b, solid) < capsule.r - TOUCH
                    if close:
                        hit.add(name)
                        add(
                            "warning",
                            "clash-tray",
                            f"tray {tray['id']} runs through {what} {name}",
                            [tray["id"], solid.id],
                            _box(capsule.aabb, box),
                            "route the tray around it (another rack tier, a room point), or "
                            "move the item",
                            key=f"{tray['id']}+{ref}",
                        )
    _zones(model, trays, rules, add)
    _spans(model, trays, rules, steel, add)
    for entry in cabling.get("missing", []):
        add(
            "warning",
            "cable-missing",
            f"{entry['kind']} {entry['tag']} has no cable: {entry['reason']}",
            [entry["tag"]],
            None,
            "complete electrical/electrical-list.yaml (rooms in buildings, motors, instrument "
            "points) and rebuild",
            key=entry["tag"],
        )
    for cable in model.get("cables") or []:
        if cable.get("review_needed") and cable.get("reason") and "direct" in cable["reason"]:
            add(
                "warning",
                "cable-unrouted",
                f"cable {cable['tag']} ({cable['from']} to {cable['to']}): {cable['reason']}",
                [cable["tag"]],
                None,
                "give the tray a clear way (a room point, a rack nearer the load) and rebuild",
                key=cable["tag"],
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


# ---------------------------------------------------------------------------
# The cable schedule
# ---------------------------------------------------------------------------

#: The schedule's columns, in order.
SCHEDULE_COLUMNS = (
    "tag",
    "system",
    "kind",
    "from",
    "to",
    "size",
    "od_mm",
    "voltage_v",
    "power_kw",
    "current_a",
    "pairs",
    "route_length_m",
    "length_m",
    "trays",
    "review_needed",
)
#: Where ``cheme layout cables --write`` puts the schedule.
SCHEDULE_FILES = ("electrical/cable-schedule.csv", "electrical/cable-schedule.md")


def _num(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}" if value == int(value) else f"{value:.2f}".rstrip("0").rstrip(".")
    return str(value)


def cable_schedule(model: dict[str, Any]) -> list[dict[str, str]]:
    """The cable schedule of a model document: one row per cable (:data:`SCHEDULE_COLUMNS`),
    by tag; empty without cables."""
    rows = []
    for cable in model.get("cables") or []:
        rows.append(
            {
                "tag": cable["tag"],
                "system": cable["system"],
                "kind": cable["kind"],
                "from": cable["from"],
                "to": cable["to"],
                "size": cable["size"],
                "od_mm": _num(cable["od_mm"]),
                "voltage_v": _num(cable.get("voltage_v")),
                "power_kw": _num(cable.get("power_kw")),
                "current_a": _num(cable.get("current_a")),
                "pairs": _num(cable.get("pairs")),
                "route_length_m": f"{cable['route_length']:.1f}",
                "length_m": _num(cable["length"]),
                "trays": " ".join(cable.get("trays") or []),
                "review_needed": "yes" if cable.get("review_needed") else "",
            }
        )
    return sorted(rows, key=lambda r: r["tag"])


def schedule_csv(rows: list[dict[str, str]]) -> str:
    """*rows* as CSV (comma separated, a header line, ``\\n`` line ends)."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(SCHEDULE_COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def schedule_markdown(model: dict[str, Any], model_file: str = LAYOUT_MODEL_FILE) -> str:
    """The cable schedule as Markdown: the cables, the totals by size, the trays and what has
    no cable."""
    rows = cable_schedule(model)
    cabling = model.get("cabling") or {}
    source = (model.get("provenance") or {}).get("output_sha256", "")[:12]
    lines = [
        "# Cable schedule",
        "",
        f"Generated by `cheme layout cables` from `{model_file}` (output {source}). Do not "
        "edit: change the electrical list or the layout and rebuild. Cable sizes are ASSUMED "
        "from a catalogue table for tray sizing; the electrical design sizes the cables.",
        "",
        "| tag | from | to | size | V | kW | A | trays | length m |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row['tag']} | {row['from']} | {row['to']} | {row['size']} | {row['voltage_v']} "
            f"| {row['power_kw']} | {row['current_a']} | {row['trays']} | {row['length_m']}"
            f"{' (review)' if row['review_needed'] else ''} |"
        )
    totals: dict[tuple[str, str], list[float]] = {}
    for cable in model.get("cables") or []:
        entry = totals.setdefault((cable["system"], cable["size"]), [0, 0.0])
        entry[0] += cable.get("count", 1)
        entry[1] += cable["length"] * cable.get("count", 1)
    lines += [
        "",
        "## Totals by size",
        "",
        "| system | size | cables | length m |",
        "|---|---|---|---|",
    ]
    for (system, size), (count, length) in sorted(totals.items()):
        lines.append(f"| {system} | {size} | {count:g} | {length:g} |")
    lines += [
        "",
        "## Trays",
        "",
        "| tray | system | kind | width mm | length m | cables | fill |",
        "|---|---|---|---|---|---|---|",
    ]
    for tray in model.get("trays") or []:
        lines.append(
            f"| {tray['id']} | {tray['system']} | {tray['kind']} | {tray['width'] * 1000:g} | "
            f"{tray['length']:.1f} | {len(tray['cables'])} | {tray['fill']:.0%} |"
        )
    missing = cabling.get("missing") or []
    if missing:
        lines += ["", "## Without a cable", ""]
        lines += [f"- {m['kind']} {m['tag']}: {m['reason']}" for m in missing]
    return "\n".join(lines) + "\n"
