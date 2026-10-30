"""Validation of the 3D layout: ``layout/site-plan.yaml``, ``building.yaml`` and
``equipment-placement.yaml``, against each other and the equipment list.

Each file is parsed and checked against its schema first; the ``cheme.layout-*`` rules then
run on the files that passed. Geometry is tested in plan, each thing over its height band: an
equipment item by its plan outline (:func:`plan_outline`: a circle for a vertical cylinder or a
sphere, else its rectangle turned with the item) over the height of its box; against another
item also by its solid parts standing out of that outline (:func:`clash_pieces`: a tank's
stair, a vessel's base plate, a plinth); a building by its rotated rectangle (exact, since a
building turns in steps of 90 degrees). Roads and racks are strips along their centrelines,
with the segments lengthened by half the width at each bend so the joints are closed (as the
viewer draws them).

Heights: a level is as high as its declared ``height``, else up to the next level, else
:data:`DEFAULT_LEVEL_HEIGHT` (a floor) or a slab (a platform or roof); a building without levels
is :data:`DEFAULT_BUILDING_HEIGHT` high. A rack occupies the height from its lowest tier minus
:data:`RACK_CLEARANCE` up to its top tier plus :data:`RACK_CLEARANCE`, so items at grade under it
are fine as long as they stay below the lowest tier.

The functions work on file contents rather than paths, so ``cheme serve`` runs the same rules
on a git revision.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from chemeascode.domains.equipment.schemas.equipment import EquipmentList
from chemeascode.domains.spatial.geometry3d import Box, Capsule, Cylinder, Sphere, part_solid
from chemeascode.domains.spatial.schemas import (
    LAYOUT_SCHEMAS,
    Building,
    BuildingList,
    Level,
    Placement,
    PlacementList,
    Rack,
    SitePlan,
)
from chemeascode.domains.spatial.shapes import Body, Dims, body, family_for
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_FILES, Workspace
from chemeascode.foundation.yamlsource import _yaml_line, syntax_finding

#: Overlaps (m) at or below this are touching, not clashing.
EPS = 1e-6
#: How far (m) an item on a level may sit from the level's elevation.
LEVEL_TOLERANCE = 0.05
#: Height (m) of a top floor without a declared height, and of a building without levels.
DEFAULT_LEVEL_HEIGHT = 4.0
DEFAULT_BUILDING_HEIGHT = 6.0
#: Thickness (m) of a platform or roof without a declared height.
SLABS = {"platform": 0.2, "roof": 0.3}
#: Headroom (m) kept below a rack's lowest tier and above its top tier.
RACK_CLEARANCE = 0.5

Box2 = tuple[float, float, float, float]  # x0, y0, x1, y1
Box3 = tuple[float, float, float, float, float, float]  # x0, y0, z0, x1, y1, z1
Polygon = list[tuple[float, float]]


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def item_dims(dimensions: Any) -> Dims:
    """Equipment-list ``dimensions`` as the sizes :mod:`~chemeascode.domains.spatial.shapes`
    takes."""
    return Dims(
        diameter=dimensions.diameter,
        height=dimensions.height,
        length=dimensions.length,
        width=dimensions.across,
        head=dimensions.head,
        support=dimensions.support,
        orientation=getattr(dimensions, "orientation", None),
        variant=getattr(dimensions, "variant", None),
    )


def size_dims(item: Placement) -> Dims | None:
    """A placement's fallback ``size`` as sizes, None without one."""
    size = item.size
    if size is None:
        return None
    if isinstance(size, tuple):
        return Dims(length=size[0], width=size[1], height=size[2])
    return Dims(diameter=size.diameter, height=size.height, length=size.length)


@dataclass
class Resolved:
    """What a placement stands for: the body and where its size came from."""

    body: Body
    #: ``list`` (equipment-list dimensions), ``placement`` (its size) or ``default``.
    size_from: str
    type: str | None = None


def resolve(item: Placement, listed: Any = None, bundle_length: float | None = None) -> Resolved:
    """The :class:`~chemeascode.domains.spatial.shapes.Body` of a placement: the family from the
    listed item's ``type``, the sizes from its ``dimensions``, else the placement's ``size``,
    else the family's defaults; ``shape`` overrides the shape."""
    type_name = getattr(listed, "type", None)
    family = family_for(type_name)
    dimensions = getattr(listed, "dimensions", None)
    shape = item.shape
    if dimensions is not None:
        dims, source = item_dims(dimensions), "list"
    elif item.size is not None:
        dims, source = size_dims(item), "placement"
        shape = shape or item.size_shape()
    else:
        dims, source = None, "default"
    grade = item.mount is None and (item.position[2] <= 1e-6 or item.plinth is not None)
    found = body(
        family,
        dims,
        item.position,
        item.rotation_deg,
        shape,
        bundle_length,
        type_name=type_name,
        grade=grade,
        plinth=item.plinth or 0.0,
    )
    return Resolved(found, source, type_name)


def equipment_box(item: Placement, resolved: Resolved | None = None) -> Box3:
    """The axis-aligned box around *item*'s shape after its rotation (round shapes do not grow
    when turned); without *resolved*, from the placement alone."""
    return (resolved or resolve(item)).body.bbox()


def building_corners(building: Building) -> Polygon:
    """The four corners of *building* in the site frame."""
    angle = math.radians(building.rotation_deg)
    c, s = round(math.cos(angle)), round(math.sin(angle))  # multiples of 90 degrees
    ox, oy = building.origin
    local = [(0.0, 0.0), (building.width, 0.0), (building.width, building.depth)]
    local.append((0.0, building.depth))
    return [(ox + u * c - v * s, oy + u * s + v * c) for u, v in local]


def building_footprint(building: Building) -> Box2:
    """``[x0, y0, x1, y1]`` of *building* in the site frame."""
    corners = building_corners(building)
    xs, ys = [p[0] for p in corners], [p[1] for p in corners]
    return (min(xs), min(ys), max(xs), max(ys))


def level_heights(building: Building) -> list[tuple[Level, float, bool]]:
    """The levels of *building* by elevation, each with its clear height and whether that height
    is known (declared, or up to the next level) rather than a default."""
    levels = sorted(building.levels, key=lambda level: level.elevation)
    found = []
    for i, level in enumerate(levels):
        if level.height > 0:
            found.append((level, level.height, True))
        elif i + 1 < len(levels) and levels[i + 1].elevation - level.elevation > EPS:
            found.append((level, levels[i + 1].elevation - level.elevation, True))
        else:
            found.append((level, SLABS.get(level.kind, DEFAULT_LEVEL_HEIGHT), False))
    return found


def building_heights(building: Building) -> tuple[float, float]:
    """Bottom and top elevation of *building*."""
    heights = level_heights(building)
    if not heights:
        return (0.0, DEFAULT_BUILDING_HEIGHT)
    bottom = min(0.0, *(level.elevation for level, _, _ in heights))
    top = max(level.elevation + height for level, height, _ in heights)
    return (bottom, top)


def rack_heights(rack: Rack) -> tuple[float, float]:
    """The height band a rack takes up: ``(-inf, inf)`` when it has no tiers."""
    if not rack.levels:
        return (-math.inf, math.inf)
    return (min(rack.levels) - RACK_CLEARANCE, max(rack.levels) + RACK_CLEARANCE)


def strip(points: Iterable[tuple[float, float]], width: float) -> list[Polygon]:
    """One rectangle per segment of a polyline *width* wide. Each segment is lengthened by half
    the width where it meets the next or previous one, so the outside of every bend is covered;
    the ends of the polyline stay where they are."""
    points = list(points)
    found = []
    last = len(points) - 1
    for i, ((x0, y0), (x1, y1)) in enumerate(zip(points, points[1:], strict=False)):
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= EPS:
            continue
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        e0 = width / 2 if i > 0 else 0.0
        e1 = width / 2 if i + 1 < last else 0.0
        x0, y0, x1, y1 = x0 - ux * e0, y0 - uy * e0, x1 + ux * e1, y1 + uy * e1
        nx, ny = -uy * width / 2, ux * width / 2
        found.append(
            [(x0 + nx, y0 + ny), (x1 + nx, y1 + ny), (x1 - nx, y1 - ny), (x0 - nx, y0 - ny)]
        )
    return found


def box_polygon(box: Box2 | Box3) -> Polygon:
    if len(box) == 6:
        x0, y0, _, x1, y1, _ = box
    else:
        x0, y0, x1, y1 = box
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


#: Sides of the polygon a round plan outline is drawn with. It is inscribed, so two outlines
#: whose circles only touch never overlap; the radius is short by up to 0.2 % between corners
#: (6 mm on a D 6 m tank), by which an overlap may be missed and a distance overstated.
CIRCLE_SIDES = 48
#: A part standing out beyond its item's plan outline by no more than this is in the outline
#: (a body flange on an exchanger's channel), m.
PART_TOLERANCE = 0.05


def _circle(x: float, y: float, r: float, sides: int = CIRCLE_SIDES) -> Polygon:
    step = 2 * math.pi / sides
    return [(x + r * math.cos(k * step), y + r * math.sin(k * step)) for k in range(sides)]


def plan_outline(
    shape: str, position: Iterable[float], rotation_deg: float, dx: float, dy: float
) -> Polygon:
    """The outline in plan of an item of *shape* centred at *position* whose own frame is *dx*
    by *dy*: a circle for a vertical cylinder or a sphere, else the rectangle turned by
    *rotation_deg*."""
    x, y = list(position)[:2]
    if shape in ("vertical_cylinder", "sphere"):
        return _circle(x, y, dx / 2)
    a = math.radians(rotation_deg)
    c, s = math.cos(a), math.sin(a)
    corners = ((-dx / 2, -dy / 2), (dx / 2, -dy / 2), (dx / 2, dy / 2), (-dx / 2, dy / 2))
    return [(x + u * c - v * s, y + u * s + v * c) for u, v in corners]


def body_outline(item: Body) -> Polygon:
    """The plan outline of a placed item's shape (:func:`plan_outline`)."""
    dx, dy, _ = item.extent
    return plan_outline(item.shape, item.position, item.rotation_deg, dx, dy)


def _hull(points: list[tuple[float, float]]) -> Polygon:
    """The convex hull of *points*, counterclockwise."""
    points = sorted(set(points))
    if len(points) <= 2:
        return points

    def half(ordered: list[tuple[float, float]]) -> Polygon:
        found: Polygon = []
        for p in ordered:
            while len(found) >= 2 and (
                (found[-1][0] - found[-2][0]) * (p[1] - found[-2][1])
                - (found[-1][1] - found[-2][1]) * (p[0] - found[-2][0])
                <= 0
            ):
                found.pop()
            found.append(p)
        return found

    return half(points)[:-1] + half(points[::-1])[:-1]


def _disk(centre: tuple[float, ...], axis: tuple[float, ...], r: float) -> Polygon:
    """Points (in plan) round the edge of the disk of radius *r* at *centre* across *axis*."""
    ax, ay, az = axis
    length = math.sqrt(ax * ax + ay * ay + az * az) or 1.0
    ax, ay, az = ax / length, ay / length, az / length
    # two unit vectors across the axis
    e1 = (-ay, ax, 0.0) if abs(az) < 0.9 else (0.0, -az, ay)
    n1 = math.sqrt(sum(v * v for v in e1))
    e1 = (e1[0] / n1, e1[1] / n1, e1[2] / n1)
    e2 = (ay * e1[2] - az * e1[1], az * e1[0] - ax * e1[2])
    step = 2 * math.pi / 24
    return [
        (
            centre[0] + r * (math.cos(k * step) * e1[0] + math.sin(k * step) * e2[0]),
            centre[1] + r * (math.cos(k * step) * e1[1] + math.sin(k * step) * e2[1]),
        )
        for k in range(24)
    ]


def solid_outline(solid: Any) -> Polygon:
    """The outline in plan of a solid of :mod:`~chemeascode.domains.spatial.geometry3d`: a
    turned box's rectangle, a cylinder's two end disks and what lies between, a capsule's or a
    sphere's circles; else its box."""
    if isinstance(solid, Box):
        return plan_outline("box", solid.centre, solid.rotation_deg, *solid.size[:2])
    if isinstance(solid, Cylinder):
        axis = tuple(b - a for a, b in zip(solid.a, solid.b, strict=True))
        return _hull(_disk(solid.a, axis, solid.r) + _disk(solid.b, axis, solid.r))
    if isinstance(solid, Capsule):
        return _hull(_circle(*solid.a[:2], solid.r, 24) + _circle(*solid.b[:2], solid.r, 24))
    if isinstance(solid, Sphere):
        return _circle(*solid.centre[:2], solid.r, 24)
    return box_polygon(solid.aabb)


def _within(polygon: Polygon, outline: Polygon, tolerance: float) -> bool:
    """Whether *polygon* lies inside the convex, counterclockwise *outline* grown by
    *tolerance*; never inside an outline without an edge (an item without sizes)."""
    edges = 0
    for (x0, y0), (x1, y1) in zip(outline, outline[1:] + outline[:1], strict=True):
        length = math.hypot(x1 - x0, y1 - y0)
        if length <= EPS:
            continue
        edges += 1
        for x, y in polygon:
            if ((x1 - x0) * (y - y0) - (y1 - y0) * (x - x0)) / length < -tolerance:
                return False
    return edges > 0


@dataclass(frozen=True)
class Piece:
    """A piece of an item's clash shape: its outline in plan over a height band; *part* names a
    part standing out beyond the item's outline (None: the outline itself)."""

    part: str | None
    polygon: Polygon
    low: float
    high: float

    @property
    def extent(self) -> Box3:
        xs, ys = [p[0] for p in self.polygon], [p[1] for p in self.polygon]
        return (min(xs), min(ys), self.low, max(xs), max(ys), self.high)


def clash_pieces(item: Body) -> list[Piece]:
    """The shape the clash rule tests of a placed item: its plan outline over the height of its
    box, and each solid part (``lod`` up to 1) standing out beyond that outline, such as a
    tank's stair, a vessel's base plate or a plinth."""
    box = item.bbox()
    outline = body_outline(item)
    found = [Piece(None, outline, box[2], box[5])]
    for part in item.parts():
        solid = part_solid({k: v for k, v in asdict(part).items() if v is not None})
        if solid is None:
            continue
        polygon = solid_outline(solid)
        if _within(polygon, outline, PART_TOLERANCE):
            continue
        aabb = solid.aabb
        found.append(Piece(part.id, polygon, aabb[2], aabb[5]))
    return found


def pieces_clash(a: list[Piece], b: list[Piece]) -> tuple[Piece, Piece] | None:
    """The first pair of pieces of two items that overlap in plan and in height, None when
    they do not."""
    for pa in a:
        ea = pa.extent
        for pb in b:
            eb = pb.extent
            if boxes_overlap(ea, eb) and polygons_overlap(pa.polygon, pb.polygon):
                return (pa, pb)
    return None


def polygons_overlap(a: Polygon, b: Polygon) -> bool:
    """Whether two convex polygons share more than a boundary (separating axis test)."""
    for polygon in (a, b):
        for i, (x0, y0) in enumerate(polygon):
            x1, y1 = polygon[(i + 1) % len(polygon)]
            ax, ay = -(y1 - y0), x1 - x0
            norm = math.hypot(ax, ay)
            if norm <= EPS:
                continue
            ax, ay = ax / norm, ay / norm
            pa = [x * ax + y * ay for x, y in a]
            pb = [x * ax + y * ay for x, y in b]
            if min(max(pa), max(pb)) - max(min(pa), min(pb)) <= EPS:
                return False
    return True


def _overlap(a0: float, a1: float, b0: float, b1: float) -> bool:
    return min(a1, b1) - max(a0, b0) > EPS


def boxes_overlap(a: Box3, b: Box3) -> bool:
    return all(_overlap(a[i], a[i + 3], b[i], b[i + 3]) for i in range(3))


def _extent(boxes: Iterable[Box3]) -> Box3:
    """The box around *boxes*."""
    boxes = list(boxes)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        min(b[2] for b in boxes),
        max(b[3] for b in boxes),
        max(b[4] for b in boxes),
        max(b[5] for b in boxes),
    )


def _inside(polygon: Polygon, box: Box2) -> bool:
    x0, y0, x1, y1 = box
    return all(x0 - EPS <= x <= x1 + EPS and y0 - EPS <= y <= y1 + EPS for x, y in polygon)


def _fmt(box: Iterable[float]) -> str:
    return "[" + ", ".join(f"{v:g}" for v in box) + "]"


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _union_branch(step: Any) -> bool:
    """Whether a pydantic error location step names a union branch, not a YAML key."""
    return isinstance(step, str) and (step.startswith("tuple[") or step == "PlacementSize")


def parse(text: str, kind: str, name: str) -> tuple[list[Finding], BaseModel | None, Any]:
    """Findings for one layout file, its model (``None`` when invalid), and its YAML nodes."""
    try:
        document = yaml.compose(text)
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as failure:
        return [syntax_finding(name, failure, text)], None, None
    try:
        return [], LAYOUT_SCHEMAS[kind].model_validate(data), document
    except ValidationError as failure:
        findings = []
        for error in failure.errors():
            loc = [p for p in error["loc"] if not _union_branch(p)]
            findings.append(
                Finding(
                    name,
                    "error",
                    "yaml.schema",
                    f"{'.'.join(str(p) for p in loc)}: {error['msg']}",
                    line=_yaml_line(document, loc),
                    hint=f"see `cheme schema {kind}`",
                )
            )
        return findings, None, document


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass
class Layout:
    """The parsed layout files of a repository (or revision) and what the rules found."""

    site_plan: SitePlan | None = None
    buildings: BuildingList | None = None
    placement: PlacementList | None = None
    structures: Any = None
    zones: Any = None
    routing: Any = None
    pipe_specs: Any = None
    trays: Any = None
    hvac: Any = None
    findings: list[Finding] = field(default_factory=list)
    #: Kinds of the layout files present.
    present: list[str] = field(default_factory=list)
    #: Tags of the placements a clash finding names.
    clashing: set[str] = field(default_factory=set)
    #: ``(kind, id)`` of everything a clash finding names; kind is ``equipment``, ``building``,
    #: ``road`` (a road or a ``road`` area) or ``rack``.
    clash_refs: set[tuple[str, str]] = field(default_factory=set)
    #: Whether the cross rules ran (all present files passed their schema).
    ruled: bool = False
    #: Route of each line of the line list
    #: (see :mod:`chemeascode.domains.spatial.layout_distances`).
    lines: list[Any] = field(default_factory=list)
    #: The body of each placement, in the order of ``placement.equipment``.
    resolved: list[Resolved] = field(default_factory=list)

    def box(self, index: int) -> Box3:
        """The box around placement *index*."""
        return self.resolved[index].body.bbox()


class _Rules:
    def __init__(
        self,
        layout: Layout,
        names: dict[str, str],
        documents: dict[str, Any],
        equipment: EquipmentList | None,
        equipment_name: str,
        equipment_document: Any,
        piping_items: Any = None,
        lines: Any = None,
        lines_text: tuple[str, str] | None = None,
        drawn_tags: set[str] | None = None,
        nozzles: dict[str, set[str]] | None = None,
    ) -> None:
        self.layout = layout
        self.drawn_tags = drawn_tags or set()
        self.nozzles = nozzles
        self.names = names
        self.documents = documents
        self.equipment = equipment
        self.equipment_name = equipment_name
        self.equipment_document = equipment_document
        self.piping_items = piping_items
        self.lines = lines
        self.lines_name = lines_text[0] if lines_text else "piping/line-list.yaml"
        self.lines_document = None
        if lines_text is not None:
            try:
                self.lines_document = yaml.compose(lines_text[1])
            except yaml.YAMLError:
                self.lines_document = None

    def add(
        self,
        kind: str,
        loc: tuple[Any, ...],
        level: str,
        rule: str,
        message: str,
        ids: list[str],
        hint: str,
    ) -> None:
        document = self.documents.get(kind) if kind != "equipment" else self.equipment_document
        name = self.names[kind] if kind != "equipment" else self.equipment_name
        self.layout.findings.append(
            Finding(
                name,
                level,  # type: ignore[arg-type]
                f"cheme.layout-{rule}",
                message,
                line=_yaml_line(document, loc) if document is not None else None,
                ids=ids,
                hint=hint,
            )
        )

    def add_line(
        self, loc: tuple[Any, ...], level: str, rule: str, message: str, ids: list[str], hint: str
    ) -> None:
        """A finding on an entry of the line list."""
        document = self.lines_document
        self.layout.findings.append(
            Finding(
                self.lines_name,
                level,  # type: ignore[arg-type]
                f"cheme.layout-{rule}",
                message,
                line=_yaml_line(document, loc) if document is not None else None,
                ids=ids,
                hint=hint,
            )
        )

    def run(self) -> None:
        site = self.layout.site_plan
        buildings = self.layout.buildings.buildings if self.layout.buildings else []
        placements = self.layout.placement.equipment if self.layout.placement else []
        self.duplicates()
        if site is not None:
            self.outside_site(site.site.width, site.site.depth, buildings, placements)
            self.area_overlap()
        self.levels(buildings, placements)
        self.clashes(buildings, placements)
        self.tags(placements)
        self.sizes(placements)
        self.nozzle_overrides(placements)
        self.routing_lines()
        self.tray_tiers()
        self.hvac_refs(buildings)
        from chemeascode.domains.spatial.layout_distances import route_lines, separations

        separations(self)
        self.layout.lines = route_lines(self, self.lines)

    # -- layout-tray-rack -------------------------------------------------------

    def tray_tiers(self) -> None:
        """A tray tier rule naming a rack the site plan lacks."""
        trays = self.layout.trays
        if trays is None:
            return
        racks = (
            {rack.id for rack in self.layout.site_plan.racks} if self.layout.site_plan else set()
        )
        for k, tier in enumerate(trays.rules.tiers):
            if tier.rack not in racks:
                self.add(
                    "trays",
                    ("rules", "tiers", k, "rack"),
                    "error",
                    "tray-rack",
                    f"tray tier on rack {tier.rack}, which the site plan does not declare",
                    [tier.rack],
                    f"racks: {', '.join(sorted(racks)) or 'none'}",
                )
        self.power_trays()

    def power_trays(self) -> None:
        """``power_trays`` naming a rack the site plan lacks or twice (error), or more trays
        than fit on the power side of the rack (warning)."""
        rules = self.layout.trays.rules  # type: ignore[union-attr]
        racks = {r.id: r for r in self.layout.site_plan.racks} if self.layout.site_plan else {}
        seen: set[str] = set()
        for k, entry in enumerate(rules.power_trays):
            loc = ("rules", "power_trays", k, "rack")
            rack = racks.get(entry.rack)
            if rack is None or entry.rack in seen:
                twice = entry.rack in seen
                self.add(
                    "trays",
                    loc,
                    "error",
                    "tray-rack",
                    f"power trays on rack {entry.rack}, "
                    + ("listed twice" if twice else "which the site plan does not declare"),
                    [entry.rack],
                    "one power_trays entry per rack"
                    if twice
                    else f"racks: {', '.join(sorted(racks)) or 'none'}",
                )
                seen.add(entry.rack)
                continue
            seen.add(entry.rack)
            n = len(entry.classes)
            widest = rules.widths_mm[-1] / 1000
            pitch = widest + rules.spacing_m
            lane = rules.lane_fraction * rack.width
            inner = lane - (n - 1) / 2 * pitch - widest / 2
            outer = lane + (n - 1) / 2 * pitch + widest / 2
            if inner < -EPS or outer > rack.width / 2 + EPS:
                self.add(
                    "trays",
                    ("rules", "power_trays", k, "trays"),
                    "warning",
                    "tray-rack",
                    f"{n} power trays on rack {entry.rack} take {inner:.2f} .. {outer:.2f} m from "
                    f"its centreline at the largest width ({widest * 1000:g} mm, {pitch:g} m "
                    f"apart): beyond the power half of the {rack.width:g} m rack",
                    [entry.rack],
                    "fewer power trays, smaller widths_mm or another lane_fraction, or a wider "
                    "rack in the site plan",
                )

    # -- layout-hvac-ref ---------------------------------------------------------

    def hvac_refs(self, buildings: list[Building]) -> None:
        """What ``layout/hvac.yaml`` names that the layout lacks: a building, a level, a unit,
        an opening of the unit's building; a unit, room or terminal outside its building, a
        room served by a unit in another building; duplicate ids."""
        hvac = self.layout.hvac
        if hvac is None:
            return
        by_id = {b.id: b for b in buildings}
        known = ", ".join(sorted(by_id)) or "none"

        def inside(building: Building, x: float, y: float) -> bool:
            x0, y0, x1, y1 = building_footprint(building)
            return x0 - EPS <= x <= x1 + EPS and y0 - EPS <= y <= y1 + EPS

        def ref(loc: tuple[Any, ...], message: str, ids: list[str], hint: str) -> None:
            self.add("hvac", loc, "error", "hvac-ref", message, ids, hint)

        seen: set[str] = set()
        units = {}
        for k, unit in enumerate(hvac.units):
            if unit.id in seen:
                ref(("units", k, "id"), f"unit id {unit.id} is used twice", [unit.id], "rename")
            seen.add(unit.id)
            units[unit.id] = unit
            building = by_id.get(unit.building)
            if building is None:
                ref(
                    ("units", k, "building"),
                    f"unit {unit.id} stands in building {unit.building}, which "
                    "layout/building.yaml does not declare",
                    [unit.id, unit.building],
                    f"buildings: {known}",
                )
                continue
            if unit.level is not None and unit.level not in {lv.id for lv in building.levels}:
                ref(
                    ("units", k, "level"),
                    f"unit {unit.id}: building {building.id} has no level {unit.level}",
                    [unit.id],
                    "a level id of that building",
                )
            if not inside(building, *unit.position):
                ref(
                    ("units", k, "position"),
                    f"unit {unit.id} at {list(unit.position)} stands outside building "
                    f"{building.id}",
                    [unit.id],
                    "ducts run inside buildings: place the unit in its building",
                )
            openings = {o.id: o for o in building.openings if o.id}
            for name in ("intake", "exhaust"):
                value = getattr(unit, name)
                if value is not None and value not in openings:
                    ref(
                        ("units", k, name),
                        f"unit {unit.id}: {name} {value} is not an opening of {building.id}",
                        [unit.id, value],
                        "an opening id (a louvre) of the unit's building in layout/building.yaml",
                    )
        for k, room in enumerate(hvac.rooms):
            if room.id in seen:
                ref(("rooms", k, "id"), f"room id {room.id} is used twice", [room.id], "rename")
            seen.add(room.id)
            building = by_id.get(room.building)
            if building is None:
                ref(
                    ("rooms", k, "building"),
                    f"room {room.id} is in building {room.building}, which layout/building.yaml "
                    "does not declare",
                    [room.id, room.building],
                    f"buildings: {known}",
                )
                continue
            if room.level is not None and room.level not in {lv.id for lv in building.levels}:
                ref(
                    ("rooms", k, "level"),
                    f"room {room.id}: building {building.id} has no level {room.level}",
                    [room.id],
                    "a level id of that building",
                )
            unit = units.get(room.unit)
            if unit is None:
                ref(
                    ("rooms", k, "unit"),
                    f"room {room.id} is served by unit {room.unit}, which units: does not declare",
                    [room.id, room.unit],
                    f"units: {', '.join(sorted(units)) or 'none'}",
                )
            elif unit.building != room.building:
                ref(
                    ("rooms", k, "unit"),
                    f"room {room.id} in {room.building} is served by unit {unit.id} in "
                    f"{unit.building}",
                    [room.id, unit.id],
                    "ducts run inside one building: a unit in the room's building",
                )
            if room.extent is not None:
                x0, y0, x1, y1 = room.extent
                if not (inside(building, x0, y0) and inside(building, x1, y1)):
                    ref(
                        ("rooms", k, "extent"),
                        f"room {room.id}: extent {list(room.extent)} reaches outside building "
                        f"{building.id}",
                        [room.id],
                        "an extent within the building's footprint",
                    )
            box = room.extent or building_footprint(building)
            for name in ("supply", "extract"):
                for j, point in enumerate(getattr(room, name)):
                    x, y = point
                    if not (
                        box[0] - EPS <= x <= box[2] + EPS and box[1] - EPS <= y <= box[3] + EPS
                    ):
                        ref(
                            ("rooms", k, name, j),
                            f"room {room.id}: {name} terminal {list(point)} lies outside the room",
                            [room.id],
                            "terminals within the room's extent",
                        )

    # -- layout-duplicate -------------------------------------------------------

    def duplicates(self) -> None:
        groups: list[tuple[str, str, list[str]]] = []
        if self.layout.site_plan is not None:
            plan = self.layout.site_plan
            for key in ("areas", "roads", "racks"):
                groups.append(("site_plan", key, [item.id for item in getattr(plan, key)]))
        if self.layout.buildings is not None:
            groups.append(
                ("building", "buildings", [b.id for b in self.layout.buildings.buildings])
            )
        if self.layout.placement is not None:
            groups.append(
                ("placement", "equipment", [p.tag for p in self.layout.placement.equipment])
            )
        if self.layout.structures is not None:
            groups.append(
                ("structures", "structures", [s.id for s in self.layout.structures.structures])
            )
        if self.layout.zones is not None:
            groups.append(("zones", "zones", [z.id for z in self.layout.zones.zones]))
        for kind, key, ids in groups:
            seen: set[str] = set()
            for position, item_id in enumerate(ids):
                if item_id in seen:
                    self.add(
                        kind,
                        (key, position),
                        "warning",
                        "duplicate",
                        f"{item_id} is listed twice under {key}",
                        [item_id],
                        "merge the two entries into one or give each its own id",
                    )
                seen.add(item_id)

    # -- layout-outside-site ----------------------------------------------------

    def outside_site(
        self, width: float, depth: float, buildings: list[Building], placements: list[Placement]
    ) -> None:
        site_box = (0.0, 0.0, width, depth)
        plan = self.layout.site_plan
        assert plan is not None
        hint = f"keep everything inside the site, 0..{width:g} east and 0..{depth:g} north"
        candidates: list[tuple[str, tuple[Any, ...], str, list[Polygon]]] = []
        for i, area in enumerate(plan.areas):
            candidates.append(
                ("site_plan", ("areas", i), f"area {area.id}", [box_polygon(area.box)])
            )
        for key, items in (("roads", plan.roads), ("racks", plan.racks)):
            for i, item in enumerate(items):
                label = f"{key[:-1]} {item.id}"
                candidates.append(("site_plan", (key, i), label, strip(item.points, item.width)))
        for i, building in enumerate(buildings):
            candidates.append(
                (
                    "building",
                    ("buildings", i),
                    f"building {building.id}",
                    [building_corners(building)],
                )
            )
        for i, item in enumerate(placements):
            candidates.append(
                (
                    "placement",
                    ("equipment", i),
                    f"equipment {item.tag}",
                    [box_polygon(self.layout.box(i))],
                )
            )
        for kind, loc, label, polygons in candidates:
            if kind not in self.names:
                continue
            if not all(_inside(polygon, site_box) for polygon in polygons):
                self.add(
                    kind,
                    loc,
                    "error",
                    "outside-site",
                    f"{label} extends outside the site",
                    [label.split(" ", 1)[1]],
                    hint,
                )

    # -- layout-area-overlap ------------------------------------------------------

    def area_overlap(self) -> None:
        assert self.layout.site_plan is not None
        areas = self.layout.site_plan.areas
        for i, a in enumerate(areas):
            for b in areas[i + 1 :]:
                if "road" in (a.kind, b.kind) or "bund" in (a.kind, b.kind):
                    continue  # roads cross areas; a bund lies within its storage area
                if _overlap(a.box[0], a.box[2], b.box[0], b.box[2]) and _overlap(
                    a.box[1], a.box[3], b.box[1], b.box[3]
                ):
                    self.add(
                        "site_plan",
                        ("areas", i),
                        "warning",
                        "area-overlap",
                        f"areas {a.id} {_fmt(a.box)} and {b.id} {_fmt(b.box)} overlap",
                        [a.id, b.id],
                        "move one box so the plot areas only touch",
                    )

    # -- layout-level -------------------------------------------------------------

    def levels(self, buildings: list[Building], placements: list[Placement]) -> None:
        by_id = {b.id: b for b in buildings}
        for i, item in enumerate(placements):
            if item.mount is None:
                continue
            if item.mount.structure is not None:
                self.structure_mount(i, item)
                continue
            building = by_id.get(item.building)
            if building is None:
                self.add(
                    "placement",
                    ("equipment", i, "mount"),
                    "error",
                    "level",
                    f"{item.tag} is placed in building {item.building}, which is not in "
                    f"layout/building.yaml",
                    [item.tag],
                    "use a building id of layout/building.yaml, or drop mount:",
                )
                continue
            footprint = building_footprint(building)
            if not _inside(box_polygon(self.layout.box(i)), footprint):
                self.add(
                    "placement",
                    ("equipment", i, "position"),
                    "error",
                    "level",
                    f"{item.tag} {_fmt(self.layout.box(i))} is not inside building "
                    f"{building.id} {_fmt(footprint)}",
                    [item.tag, building.id],
                    "move the item inside the building outline, or drop its mount:",
                )
            if item.level is None:
                if building.levels:
                    self.add(
                        "placement",
                        ("equipment", i, "mount"),
                        "warning",
                        "level",
                        f"{item.tag} is placed in building {building.id} without a level, so "
                        f"its elevation is not checked",
                        [item.tag, building.id],
                        f"levels of {building.id}: {', '.join(lv.id for lv in building.levels)}",
                    )
                continue
            heights = {lv.id: (height, known) for lv, height, known in level_heights(building)}
            level = next((lv for lv in building.levels if lv.id == item.level), None)
            if level is None:
                known = ", ".join(lv.id for lv in building.levels) or "none"
                self.add(
                    "placement",
                    ("equipment", i, "mount", "level"),
                    "error",
                    "level",
                    f"{item.tag}: building {building.id} has no level {item.level}",
                    [item.tag, building.id],
                    f"levels of {building.id}: {known}",
                )
                continue
            z = item.position[2]
            if abs(z - level.elevation) > LEVEL_TOLERANCE:
                self.add(
                    "placement",
                    ("equipment", i, "position"),
                    "error",
                    "level",
                    f"{item.tag} stands at z = {z:g} m, but level {level.id} of "
                    f"{building.id} is at {level.elevation:g} m",
                    [item.tag, building.id],
                    f"set position z to {level.elevation:g}, the level's elevation",
                )
            clear, known = heights[level.id]
            top = self.layout.box(i)[5]
            if known and top > level.elevation + clear + EPS:
                self.add(
                    "placement",
                    ("equipment", i),
                    "warning",
                    "level",
                    f"{item.tag} reaches up to {top:g} m, above the {clear:g} m clear height of "
                    f"level {level.id} of {building.id} (up to {level.elevation + clear:g} m)",
                    [item.tag, building.id],
                    "make the item lower, move it to a level with more headroom, or raise the "
                    "level's height",
                )

    def structure_mount(self, i: int, item: Placement) -> None:
        """An item on a steel structure's level: the structure and level exist, z is the
        level's elevation, the footprint lies inside the frame."""
        from chemeascode.domains.spatial.structures import Frame

        structures = self.layout.structures.structures if self.layout.structures else []
        sid = item.mount.structure if item.mount else None
        structure = next((s for s in structures if s.id == sid), None)
        if structure is None:
            self.add(
                "placement",
                ("equipment", i, "mount"),
                "error",
                "level",
                f"{item.tag} is mounted on structure {sid}, which is not in layout/structures.yaml",
                [item.tag],
                "use a structure id of layout/structures.yaml, or drop mount:",
            )
            return
        frame = Frame(structure.origin, structure.rotation_deg)
        corners = [
            frame.site(u, v)
            for u, v in (
                (0, 0),
                (structure.width, 0),
                (structure.width, structure.depth),
                (0, structure.depth),
            )
        ]
        footprint = (
            min(c[0] for c in corners),
            min(c[1] for c in corners),
            max(c[0] for c in corners),
            max(c[1] for c in corners),
        )
        if not _inside(box_polygon(self.layout.box(i)), footprint):
            self.add(
                "placement",
                ("equipment", i, "position"),
                "error",
                "level",
                f"{item.tag} {_fmt(self.layout.box(i))} is not inside structure {sid} "
                f"{_fmt(footprint)}",
                [item.tag, structure.id],
                "move the item onto the frame, or drop its mount:",
            )
        if item.level is None:
            self.add(
                "placement",
                ("equipment", i, "mount"),
                "warning",
                "level",
                f"{item.tag} is mounted on structure {sid} without a level, so its elevation is "
                "not checked",
                [item.tag, structure.id],
                f"levels of {sid}: {', '.join(lv.id for lv in structure.levels) or 'none'}",
            )
            return
        elevation = structure.elevation(item.level)
        if elevation is None or item.level == "grade":
            known = ", ".join(lv.id for lv in structure.levels) or "none"
            self.add(
                "placement",
                ("equipment", i, "mount", "level"),
                "error",
                "level",
                f"{item.tag}: structure {sid} has no level {item.level}",
                [item.tag, structure.id],
                f"levels of {sid}: {known}",
            )
            return
        z = item.position[2]
        if abs(z - elevation) > LEVEL_TOLERANCE:
            self.add(
                "placement",
                ("equipment", i, "position"),
                "error",
                "level",
                f"{item.tag} stands at z = {z:g} m, but level {item.level} of {sid} is at "
                f"{elevation:g} m",
                [item.tag, structure.id],
                f"set position z to {elevation:g}, the level's elevation",
            )

    # -- layout-clash ---------------------------------------------------------------

    def clashes(self, buildings: list[Building], placements: list[Placement]) -> None:
        boxes = [self.layout.box(i) for i in range(len(placements))]
        pieces = [clash_pieces(self.layout.resolved[i].body) for i in range(len(placements))]
        reach = [_extent(p.extent for p in found) for found in pieces]
        outlines = [found[0].polygon for found in pieces]
        hint = (
            "move one of them; each item is its outline in plan (a circle for a vertical "
            "vessel, the turned rectangle else) over the height of its box, with the parts "
            "standing out of it (a tank's stair, a base plate, a plinth)"
        )
        for i, a in enumerate(placements):
            for j in range(i + 1, len(placements)):
                b = placements[j]
                if a.tag == b.tag or not boxes_overlap(reach[i], reach[j]):
                    continue
                hit = pieces_clash(pieces[i], pieces[j])
                if hit is None:
                    continue
                where = " and ".join(
                    f"{tag}'s {piece.part}"
                    for tag, piece in ((a.tag, hit[0]), (b.tag, hit[1]))
                    if piece.part is not None
                )
                self.clash(
                    i,
                    f"{a.tag} {_fmt(boxes[i])} and {b.tag} {_fmt(boxes[j])} intersect"
                    + (f" ({where})" if where else ""),
                    [a.tag, b.tag],
                    hint,
                    "equipment",
                )
        for i, item in enumerate(placements):
            box = boxes[i]
            outline = outlines[i]
            for building in buildings:
                if item.building == building.id:
                    continue
                footprint = building_footprint(building)
                if not polygons_overlap(outline, building_corners(building)):
                    continue
                if not _overlap(box[2], box[5], *building_heights(building)):
                    continue
                self.clash(
                    i,
                    f"{item.tag} {_fmt(box)} intersects building {building.id} "
                    f"{_fmt(footprint)} but is not placed in it",
                    [item.tag, building.id],
                    "move it out of the building, or set mount: {building, level}",
                    "building",
                )
            plan = self.layout.site_plan
            if plan is None:
                continue
            for road_id, polygons in self.roads():
                if any(polygons_overlap(outline, p) for p in polygons):
                    self.clash(
                        i,
                        f"{item.tag} {_fmt(box)} stands on road {road_id}",
                        [item.tag, road_id],
                        "keep equipment off the road footprint",
                        "road",
                    )
            for rack in plan.racks:
                low, high = rack_heights(rack)
                if not _overlap(box[2], box[5], low, high):
                    continue
                if any(polygons_overlap(outline, p) for p in strip(rack.points, rack.width)):
                    tiers = ", ".join(f"{z:g}" for z in sorted(rack.levels)) or "none given"
                    self.clash(
                        i,
                        f"{item.tag} {_fmt(box)} runs into rack {rack.id} (tiers at {tiers} m)",
                        [item.tag, rack.id],
                        f"under a rack, keep the top of an item at least {RACK_CLEARANCE:g} m "
                        "below the lowest tier; otherwise move it beside the rack",
                        "rack",
                    )
        self.building_clashes(buildings)

    def roads(self) -> list[tuple[str, list[Polygon]]]:
        """Each road (and ``road`` area) of the site plan with its footprint."""
        plan = self.layout.site_plan
        if plan is None:
            return []
        found = [(r.id, strip(r.points, r.width)) for r in plan.roads]
        return found + [(a.id, [box_polygon(a.box)]) for a in plan.areas if a.kind == "road"]

    def building_clashes(self, buildings: list[Building]) -> None:
        """Buildings against roads, racks and each other."""
        plan = self.layout.site_plan
        corners = [building_corners(b) for b in buildings]
        heights = [building_heights(b) for b in buildings]
        for i, building in enumerate(buildings):
            for road_id, polygons in self.roads():
                if any(polygons_overlap(corners[i], p) for p in polygons):
                    self.add_building_clash(
                        i,
                        f"building {building.id} stands on road {road_id}",
                        [building.id, road_id],
                        "move the building off the road, or reroute the road",
                        "road",
                    )
            for rack in plan.racks if plan is not None else []:
                if not _overlap(*heights[i], *rack_heights(rack)):
                    continue
                if any(polygons_overlap(corners[i], p) for p in strip(rack.points, rack.width)):
                    self.add_building_clash(
                        i,
                        f"rack {rack.id} runs through building {building.id} (building up to "
                        f"{heights[i][1]:g} m)",
                        [building.id, rack.id],
                        "route the rack around the building, or keep its lowest tier at least "
                        f"{RACK_CLEARANCE:g} m above the building's top",
                        "rack",
                    )
            for j in range(i + 1, len(buildings)):
                other = buildings[j]
                if building.id == other.id or not _overlap(*heights[i], *heights[j]):
                    continue
                if polygons_overlap(corners[i], corners[j]):
                    self.add_building_clash(
                        i,
                        f"buildings {building.id} {_fmt(building_footprint(building))} and "
                        f"{other.id} {_fmt(building_footprint(other))} overlap",
                        [building.id, other.id],
                        "move one building so the outlines only touch",
                        "building",
                    )

    def add_building_clash(
        self, i: int, message: str, ids: list[str], hint: str, other: str
    ) -> None:
        """A clash of building *i* (``ids[0]``) with ``ids[1]``, a thing of kind *other*."""
        self.layout.clash_refs.update({("building", ids[0]), (other, ids[1])})
        self.add("building", ("buildings", i), "error", "clash", message, ids, hint)

    def clash(self, i: int, message: str, ids: list[str], hint: str, other: str) -> None:
        """A clash of placement *i* (``ids[0]``) with ``ids[1]``, a thing of kind *other*."""
        tags = [ids[0]] + ([ids[1]] if other == "equipment" else [])
        self.layout.clashing.update(tags)
        self.layout.clash_refs.update({("equipment", ids[0]), (other, ids[1])})
        self.add("placement", ("equipment", i), "error", "clash", message, ids, hint)

    # -- layout-unknown-tag, layout-not-placed --------------------------------------

    def tags(self, placements: list[Placement]) -> None:
        if self.equipment is None or self.layout.placement is None:
            return
        listed = [item.tag for item in self.equipment.equipment]
        piping = [p.tag for p in self.piping_items.piping_items] if self.piping_items else []
        placed = {item.tag for item in placements}
        for i, item in enumerate(placements):
            if item.tag not in listed and item.tag not in piping:
                lists = "equipment/equipment-list.yaml" + (
                    " or piping/special-items.yaml" if self.piping_items else ""
                )
                self.add(
                    "placement",
                    ("equipment", i, "tag"),
                    "error",
                    "unknown-tag",
                    f"{item.tag} is placed but not in {lists}",
                    [item.tag],
                    "fix the tag, or add the item to the equipment list (a silencer or relief "
                    "valve: to piping/special-items.yaml)",
                )
        for position, tag in enumerate(listed):
            if tag not in placed:
                self.add(
                    "equipment",
                    ("equipment", position),
                    "info",
                    "not-placed",
                    f"{tag} has no placement in layout/equipment-placement.yaml",
                    [tag],
                    "add it to layout/equipment-placement.yaml",
                )

    # -- layout-size-from-placement, layout-size-ignored, layout-size-missing ----------------

    def listed(self, tag: str) -> Any:
        return listed_item(tag, self.equipment, self.piping_items)

    def sizes(self, placements: list[Placement]) -> None:
        """Where each item's size comes from: the equipment list's ``dimensions`` win; a
        placement ``size`` is the fallback for an item without them."""
        if self.equipment is None:
            return  # without the equipment list nothing says where a size should come from
        listed = {item.tag for item in self.equipment.equipment}
        fallback = []
        for i, item in enumerate(placements):
            source = self.layout.resolved[i].size_from
            entry = self.listed(item.tag)
            if item.size is not None and getattr(entry, "dimensions", None) is not None:
                self.add(
                    "placement",
                    ("equipment", i, "size"),
                    "warning",
                    "size-ignored",
                    f"{item.tag} has dimensions in the equipment list; its placement size "
                    "is ignored",
                    [item.tag],
                    "remove size from the placement (the equipment list is the one source of "
                    "sizes)",
                )
            elif source == "placement" and item.tag in listed:
                fallback.append(item.tag)
            elif source == "default":
                family = self.layout.resolved[i].body.family
                self.add(
                    "placement",
                    ("equipment", i),
                    "warning",
                    "size-missing",
                    f"{item.tag} has no dimensions in the equipment list and no size here; it "
                    f"is drawn with the assumed size of a {family} "
                    f"{_fmt(self.layout.resolved[i].body.extent)}",
                    [item.tag],
                    "give dimensions: {diameter, height} or {length, width, height} in "
                    "equipment/equipment-list.yaml (mark estimates ASSUMED)",
                )
        if fallback:
            more = f" and {len(fallback) - 8} more" if len(fallback) > 8 else ""
            shown = ", ".join(fallback[:8]) + more
            first = next(i for i, p in enumerate(placements) if p.tag == fallback[0])
            self.add(
                "placement",
                ("equipment", first, "size"),
                "info",
                "size-from-placement",
                f"{len(fallback)} items take their size from the placement, not from "
                f"dimensions in the equipment list: {shown}",
                fallback,
                "move each size into dimensions of equipment/equipment-list.yaml and drop it here",
            )

    # -- layout-routing-unknown-line --------------------------------------------------------

    def routing_lines(self) -> None:
        routing = self.layout.routing
        if routing is None or self.lines is None or "routing" not in self.names:
            return
        known = {line.number.strip() for line in self.lines.lines}
        for k, entry in enumerate(routing.lines):
            if entry.line.strip() not in known:
                self.add(
                    "routing",
                    ("lines", k, "line"),
                    "warning",
                    "routing-unknown-line",
                    f"piping/routing.yaml names line {entry.line}, which is not in the line list",
                    [entry.line],
                    "use a line number of piping/line-list.yaml",
                )

    # -- layout-nozzle-unknown ----------------------------------------------------------------

    def nozzle_overrides(self, placements: list[Placement]) -> None:
        """A nozzle override must name a nozzle the item's P&ID draws."""
        if self.nozzles is None:
            return
        for i, item in enumerate(placements):
            known = self.nozzles.get(item.tag)
            if known is None:
                continue
            for k, nozzle in enumerate(item.nozzles):
                if nozzle.id in known:
                    continue
                names = ", ".join(sorted(known)) or "none"
                self.add(
                    "placement",
                    ("equipment", i, "nozzles", k),
                    "error",
                    "nozzle-unknown",
                    f"{item.tag} has no nozzle {nozzle.id} on its P&ID",
                    [item.tag],
                    f"nozzles of {item.tag}: {names}",
                )


def listed_item(tag: str, equipment: Any, piping_items: Any = None) -> Any:
    """The equipment-list (or special-items) entry of *tag*, None when not listed."""
    for item in equipment.equipment if equipment is not None else ():
        if item.tag == tag:
            return item
    for item in piping_items.piping_items if piping_items is not None else ():
        if item.tag == tag:
            return item
    return None


#: The attribute of :class:`Layout` each layout file kind is parsed into.
_ATTRIBUTE = {"building": "buildings"}


def check_layout(
    texts: dict[str, tuple[str, str]],
    equipment: EquipmentList | None = None,
    equipment_text: tuple[str, str] | None = None,
    unreadable: dict[str, tuple[str, str]] | None = None,
    piping_items: Any = None,
    lines: Any = None,
    lines_text: tuple[str, str] | None = None,
    drawn_tags: set[str] | None = None,
    nozzles: dict[str, set[str]] | None = None,
) -> Layout:
    """Validate the layout files.

    *texts*: ``{kind: (name, content)}`` for each layout file present (kinds of
    :data:`~chemeascode.foundation.workspace.LAYOUT_FILES`). *equipment*: the parsed equipment
    list, and *equipment_text* its ``(name, content)`` for line numbers; without it the tag rules
    are skipped. *unreadable*: ``{kind: (name, reason)}`` for layout files that exist but cannot be
    read (e.g. a symlink out of the repository); each is an error and the cross rules are skipped,
    as for an invalid file. *drawn_tags*: the tags drawn on the P&IDs; a line end naming one that
    is not placed gets ``cheme.layout-line-unrouted`` (as does a listed tag). *nozzles*: the
    nozzle names (SubTagName and DEXPI id) of each tag on the P&IDs; with it, a nozzle override
    naming another one is ``cheme.layout-nozzle-unknown``.
    """
    layout = Layout()
    names: dict[str, str] = {}
    documents: dict[str, Any] = {}
    valid = True
    for kind, (name, reason) in (unreadable or {}).items():
        layout.present.append(kind)
        layout.findings.append(
            Finding(
                name,
                "error",
                "cheme.layout-unreadable",
                reason,
                hint="the layout rules are skipped until every layout file can be read",
            )
        )
        valid = False
    for kind in LAYOUT_FILES:
        if kind not in texts:
            continue
        name, text = texts[kind]
        names[kind] = name
        layout.present.append(kind)
        findings, model, document = parse(text, kind, name)
        layout.findings += findings
        documents[kind] = document
        if model is None:
            valid = False
        else:
            setattr(layout, _ATTRIBUTE.get(kind, kind), model)
    if layout.placement is not None:
        layout.resolved = [
            resolve(item, listed_item(item.tag, equipment, piping_items))
            for item in layout.placement.equipment
        ]
    if not valid or not layout.present:
        return layout
    equipment_name, equipment_document = "equipment/equipment-list.yaml", None
    if equipment_text is not None:
        equipment_name = equipment_text[0]
        try:
            equipment_document = yaml.compose(equipment_text[1])
        except yaml.YAMLError:
            equipment_document = None
    _Rules(
        layout,
        names,
        documents,
        equipment,
        equipment_name,
        equipment_document,
        piping_items,
        lines,
        lines_text,
        drawn_tags,
        nozzles,
    ).run()
    layout.ruled = True
    return layout


def workspace_layout(
    workspace: Workspace,
    equipment: EquipmentList | None,
    piping_items: Any = None,
    lines: Any = None,
    drawn_tags: set[str] | None = None,
    nozzles: dict[str, set[str]] | None = None,
) -> Layout:
    """:func:`check_layout` on the layout files of *workspace*."""
    texts = {}
    for kind in LAYOUT_FILES:
        path = workspace.layout_file(kind)
        if path is not None:
            texts[kind] = (workspace.relative(path), path.read_text(encoding="utf-8"))
    equipment_path = workspace.list_file("equipment")
    equipment_text = None
    if equipment is not None and equipment_path is not None:
        equipment_text = (
            workspace.relative(equipment_path),
            equipment_path.read_text(encoding="utf-8"),
        )
    lines_path = workspace.list_file("lines")
    lines_text = None
    if lines is not None and lines_path is not None:
        lines_text = (workspace.relative(lines_path), lines_path.read_text(encoding="utf-8"))
    return check_layout(
        texts,
        equipment,
        equipment_text,
        piping_items=piping_items,
        lines=lines,
        lines_text=lines_text,
        drawn_tags=drawn_tags,
        nozzles=nozzles,
    )
