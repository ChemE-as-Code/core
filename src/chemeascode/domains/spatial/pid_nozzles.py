"""The nozzles of each equipment item as a P&ID draws them, for placing them in 3D.

For every tagged equipment item of a loaded DEXPI model: its nozzles (``SubTagName``, DEXPI id,
DN of the nozzle's piping node), the line numbers and segment ids that end at each nozzle, and
where the nozzle is drawn relative to the item's symbol: ``(u, v)``, the offset of the nozzle's
node position from the centre of the symbol's drawn box, divided by the box's half width and
half height (sheet axes: x right, y down), and the ``side`` that offset points to (``top``,
``bottom``, ``left``, ``right``; None for a nozzle not drawn, or drawn at the centre).

The symbol's box is that of its catalogue shape's primitives (polylines, polygons, ellipses),
scaled, mirrored and rotated as the ``ShapeUsage`` places it, so the centre does not depend on
where the shape's origin lies.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

#: A nozzle closer than this (relative to the half box) to the symbol's centre has no side.
CENTRE = 0.05
_LENGTH = {"Millimetre": 0.001, "Centimetre": 0.01, "Metre": 1.0}


@dataclass(frozen=True)
class PidNozzle:
    """One nozzle of an item on a P&ID."""

    name: str  # SubTagName, else the DEXPI id
    dexpi_id: str
    dn: int | float | None
    lines: tuple[str, ...] = ()
    segments: tuple[str, ...] = ()
    #: Offset from the symbol's centre in half box sizes, sheet axes (x right, y down).
    offset: tuple[float, float] | None = None
    side: str | None = None


@dataclass(frozen=True)
class PidEquipment:
    """One tagged equipment item of a sheet with its nozzles."""

    tag: str
    cls: str
    dexpi_id: str
    sheet: str
    nozzles: tuple[PidNozzle, ...] = ()
    #: The symbol is drawn taller than wide.
    drawn_tall: bool = False
    #: Tube length of a tube bundle, m (the bundle-pull length), when the P&ID gives it.
    tube_length: float | None = None
    names: frozenset[str] = field(default_factory=frozenset)


def _number(text: Any) -> int | float | None:
    if text is None:
        return None
    found = re.search(r"\d+(?:\.\d+)?", str(text))
    if found is None:
        return None
    value = float(found.group(0))
    return int(value) if value.is_integer() else value


def nozzle_dn(nozzle: Any) -> int | float | None:
    """The DN of a nozzle, from its first piping node that states one."""
    for node in getattr(nozzle, "nodes", None) or ():
        for name in (
            "nominalDiameterNumericalValueRepresentation",
            "nominalDiameterRepresentation",
        ):
            value = _number(getattr(node, name, None))
            if value is not None:
                return value
    return None


def side_of(u: float, v: float) -> str | None:
    """``top``, ``bottom``, ``left`` or ``right`` of an offset (sheet axes, y down)."""
    if abs(u) < CENTRE and abs(v) < CENTRE:
        return None
    if abs(v) >= abs(u):
        return "top" if v < 0 else "bottom"
    return "left" if u < 0 else "right"


def _groups(group: Any) -> list[Any]:
    found = [group]
    for child in getattr(group, "groups", None) or ():
        found += _groups(child)
    return found


def _symbol_box(usage: Any) -> tuple[float, float, float, float] | None:
    """``(cx, cy, half width, half height)`` of a ShapeUsage on the sheet."""
    shape = getattr(usage, "shape", None)
    position = getattr(usage, "position", None)
    if shape is None or position is None:
        return None
    local: list[tuple[float, float]] = []
    for primitive in getattr(shape, "primitives", None) or ():
        for point in getattr(primitive, "points", None) or ():
            local.append((point.x, point.y))
        centre = getattr(primitive, "center", None)
        if centre is not None:
            rx = getattr(primitive, "horizontalSemiAxis", 0.0) or getattr(primitive, "radius", 0.0)
            ry = getattr(primitive, "verticalSemiAxis", 0.0) or rx
            local += [(centre.x - rx, centre.y - ry), (centre.x + rx, centre.y + ry)]
    if not local:
        local = [(0.0, 0.0)]
    sx = getattr(usage, "scaleX", 1.0) or 1.0
    sy = getattr(usage, "scaleY", 1.0) or 1.0
    mirror = -1.0 if getattr(usage, "isMirrored", False) else 1.0
    a = math.radians(getattr(usage, "rotation", 0.0) or 0.0)
    c, s = math.cos(a), math.sin(a)
    points = []
    for x, y in local:
        x, y = mirror * x * sx, y * sy
        points.append((position.x + x * c - y * s, position.y + x * s + y * c))
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    return ((x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2)


def _tube_length(item: Any) -> float | None:
    bundle = getattr(item, "tubeBundle", None)
    quantity = getattr(bundle, "tubeLength", None)
    value = getattr(quantity, "value", None)
    unit = getattr(getattr(quantity, "unit", None), "value", None)
    if isinstance(value, int | float) and unit in _LENGTH and value > 0:
        return float(value) * _LENGTH[unit]
    return None


def sheet_equipment(model: Any, sheet: str) -> dict[str, PidEquipment]:
    """Every tagged equipment item of a loaded *model* (sheet *sheet*) with its nozzles, by tag
    (the first item of a tag wins)."""
    from pydexpi.pydexpi_classes.pydexpi_classes import TaggedPlantItem
    from pydexpi.toolkits.display_name import get_tag
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    # Where each line and segment ends: id() of the item -> (line numbers, segment ids)
    ends: dict[int, tuple[set[str], set[str]]] = {}
    conceptual = model.conceptualModel
    for system in getattr(conceptual, "pipingNetworkSystems", None) or ():
        number = (getattr(system, "lineNumber", None) or "").strip()
        for segment in system.segments or ():
            for holder in (segment, *(segment.connections or ())):
                for side in ("sourceItem", "targetItem"):
                    item = getattr(holder, side, None)
                    if item is None:
                        continue
                    lines, segments = ends.setdefault(id(item), (set(), set()))
                    if number:
                        lines.add(number)
                    if segment.id:
                        segments.add(segment.id)

    # Drawing: node positions, and the symbol of each represented object
    positions: dict[int, tuple[float, float]] = {}
    symbols: dict[int, tuple[float, float, float, float]] = {}
    diagram = getattr(model, "diagram", None)
    every = []
    for top in getattr(diagram, "groups", None) or ():
        every += _groups(top)
    for holder in [diagram, *every]:
        for node_position in getattr(holder, "nodePositions", None) or ():
            node = getattr(node_position, "node", None)
            point = getattr(node_position, "position", None)
            if node is not None and point is not None:
                positions.setdefault(id(node), (point.x, point.y))
    for group in every:
        represents = getattr(group, "represents", None)
        if represents is None or id(represents) in symbols:
            continue
        for child in getattr(group, "groups", None) or ():
            for element in getattr(child, "elements", None) or ():
                box = _symbol_box(element) if hasattr(element, "shape") else None
                if box is not None:
                    symbols.setdefault(id(represents), box)

    found: dict[str, PidEquipment] = {}
    for obj in get_all_instances_in_model(model):
        if not isinstance(obj, TaggedPlantItem):
            continue
        tag = (get_tag(obj) or "").strip()
        if not tag or tag in found:
            continue
        box = symbols.get(id(obj))
        nozzles = []
        for nozzle in getattr(obj, "nozzles", None) or ():
            name = (getattr(nozzle, "subTagName", None) or "").strip() or (nozzle.id or "")
            lines, segments = set(), set()
            for target in (nozzle, *(getattr(nozzle, "nodes", None) or ())):
                more = ends.get(id(target))
                if more:
                    lines |= more[0]
                    segments |= more[1]
            offset = side = None
            point = next((positions[id(n)] for n in nozzle.nodes or () if id(n) in positions), None)
            if box is not None and point is not None:
                cx, cy, hw, hh = box
                u = (point[0] - cx) / hw if hw > 1e-9 else 0.0
                v = (point[1] - cy) / hh if hh > 1e-9 else 0.0
                offset = (round(u, 4), round(v, 4))
                side = side_of(u, v)
            nozzles.append(
                PidNozzle(
                    name=name,
                    dexpi_id=nozzle.id or "",
                    dn=nozzle_dn(nozzle),
                    lines=tuple(sorted(lines)),
                    segments=tuple(sorted(segments)),
                    offset=offset,
                    side=side,
                )
            )
        names = frozenset(n.name for n in nozzles) | frozenset(n.dexpi_id for n in nozzles)
        found[tag] = PidEquipment(
            tag=tag,
            cls=type(obj).__name__,
            dexpi_id=obj.id or "",
            sheet=sheet,
            nozzles=tuple(nozzles),
            drawn_tall=box is not None and box[3] > 1.2 * box[2],
            tube_length=_tube_length(obj),
            names=names - {""},
        )
    return found
