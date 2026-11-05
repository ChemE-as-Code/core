"""Drawing-geometry lint: what a reader of the rendered sheet sees, checked by geometry.

The rules work on the SVG pyDEXPI's export draws (as ``cheme render`` does), so they see the
lines, symbols and texts exactly where the sheet puts them, after every ``ShapeUsage`` transform:

``cheme.line-through-label``
    a pipe or signal line passes through a text box, including its own line number or DN label;
``cheme.line-crossing``
    two process lines, or a process and a signal line, cross away from a node or tee;
``cheme.label-overlap``
    a text box overlaps another text box, or a symbol outline of an object it does not belong to,
    or an equipment tag sits on the outline of its own symbol (a tag inside its vessel, also over
    the internals drawn inside a column, is fine);
``cheme.label-far-from-owner``
    a label is far from the object it represents, or clearly closer to another object of the
    same kind (a valve label nearer another valve). A literal note that names tags (a trip note)
    may sit by any object it names.
``cheme.line-through-symbol``
    a pipe or signal line runs through an instrument bubble, or through the body of an equipment
    item, that it does not end on (a line ending at a nozzle, or inside the body at an internal
    or a tap, is fine);
``cheme.line-through-valve``
    a signal or measuring line runs through the body of a valve, a pipe of another segment through
    a valve, or any line through an actuator's head (a control valve's signal drawn up through
    the valve to its actuator, an actuator drawn on the pipe); a line ending on the valve or the
    actuator, and the pipes of the segment the valve sits on, are fine;
``cheme.line-on-pipe``
    a signal or measuring line drawn on top of a pipe, along it (a signal line run down the pipe
    to an actuator drawn on it);
``cheme.line-not-orthogonal`` (info)
    a signal or measuring line with a slanted stretch, neither horizontal nor vertical (a short
    hop over another line is fine);
``cheme.offpage-not-on-edge``
    an off-page connector that does not sit on an edge of the drawing area (the inside of the
    border, down to the top of the title block): within ``EDGE_TOLERANCE`` of it, or within
    ``EDGE_REACH`` with nothing else drawn between it and the edge. An open end drawn where it
    is (its id or text says to atmosphere, a vent, a drain, a hose connection, and its text names
    no sheet or battery limit) may sit anywhere.

Text extents are estimated from the font size, the characters (Arial widths, the export's
fallback font), ``text-anchor`` and ``dominant-baseline``. The sheet's border and title block are
not checked. Every finding carries a box in sheet millimetres and a ``--crop`` for
``cheme render`` around it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

from lxml import etree

from chemeascode.domains.piping.tagrefs import TAG_TOKEN, expand, instrument_loop

#: Points of a polyline, in sheet mm.
Point = tuple[float, float]
#: x0, y0, x1, y1 in sheet mm, x0 <= x1, y0 <= y1.
Box = tuple[float, float, float, float]

RULES = (
    "cheme.line-through-label",
    "cheme.line-crossing",
    "cheme.label-overlap",
    "cheme.label-far-from-owner",
    "cheme.text-outside-frame",
    "cheme.title-text-overflow",
    "cheme.line-through-symbol",
    "cheme.line-through-valve",
    "cheme.line-on-pipe",
    "cheme.line-not-orthogonal",
    "cheme.offpage-not-on-edge",
)

#: How far a line must run inside a text box to go through it (mm): less is a graze, which the
#: estimated text extents cannot tell from a near miss.
THROUGH_DEPTH = 0.3
#: A crossing closer than this to either line's end is a joint (a tee, a branch), not a crossing.
JOINT_TOLERANCE = 0.5
#: How far two text boxes must overlap to count (mm).
OVERLAP_DEPTH = 0.25
#: How far a symbol outline must reach into a text box to count (mm).
SYMBOL_DEPTH = 0.4
#: A label farther than this from its object is reported (mm).
FAR_DISTANCE = 15.0
#: A label at least this far from its own object (mm) and less than half as far from another
#: object of the same kind is reported as misattached.
MISATTACHED_MIN = 4.0
#: The margin around a finding's box in its crop (mm).
CROP_MARGIN = 10.0

# Arial advance widths in em (the export names the font with Arial as fallback).
_WIDTHS: dict[str, float] = {
    **dict.fromkeys("ABEKPSVXY", 0.667),
    **dict.fromkeys("CDHNRU", 0.722),
    **dict.fromkeys("GOQ", 0.778),
    **dict.fromkeys("FTZ", 0.611),
    "I": 0.278,
    "J": 0.5,
    "L": 0.556,
    "M": 0.833,
    "W": 0.944,
    **dict.fromkeys("0123456789", 0.556),
    **dict.fromkeys("abdeghnopqu", 0.556),
    **dict.fromkeys("ckssvxyz", 0.5),
    **dict.fromkeys("fijlt", 0.25),
    "m": 0.833,
    "r": 0.333,
    "w": 0.722,
    **dict.fromkeys(" .,:;'|!/", 0.278),
    **dict.fromkeys("-()[]", 0.333),
    **dict.fromkeys("+=<>~", 0.584),
    "%": 0.889,
    "&": 0.667,
    "°": 0.4,
    "_": 0.556,
}
_CAP = 0.716  # cap height, em
_DESCENT = 0.212  # descender, em
_X_HEIGHT = 0.519
_DESCENDERS = set("gjpqy,;()[]")


def text_width(text: str, size: float) -> float:
    """Estimated advance width of *text* at font *size* (mm)."""
    return size * sum(_WIDTHS.get(c, 0.6) for c in text)


def text_box(
    x: float, y: float, text: str, size: float, anchor: str | None, baseline: str | None
) -> Box:
    """The box the glyphs of *text* cover, anchored at (x, y) as SVG places it (Y down).

    ``text-anchor`` start / middle / end puts x at the left, centre or right end;
    ``dominant-baseline`` puts y at the alphabetic baseline (default), the middle of the
    lower-case letters (``middle``), the centre of the em box (``central``), the top
    (``hanging``, ``text-top``) or the bottom of the em box (``text-bottom``).
    """
    width = text_width(text, size)
    left = {"middle": x - width / 2, "end": x - width}.get(anchor or "start", x)
    if baseline in ("middle",):
        base = y + size * _X_HEIGHT / 2
    elif baseline in ("central",):
        base = y + size * (_CAP / 2)
    elif baseline in ("hanging", "text-top", "text-before-edge"):
        base = y + size * _CAP
    elif baseline in ("text-bottom", "text-after-edge", "ideographic"):
        base = y - size * _DESCENT
    else:
        base = y
    bottom = base + (size * _DESCENT if _DESCENDERS & set(text) else 0.0)
    return (left, base - size * _CAP, left + width, bottom)


# ---------------------------------------------------------------------------
# Transforms and SVG primitives
# ---------------------------------------------------------------------------

Matrix = tuple[float, float, float, float, float, float]  # a b c d e f, as SVG's matrix()
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _multiply(m: Matrix, n: Matrix) -> Matrix:
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (
        a * a2 + c * b2,
        b * a2 + d * b2,
        a * c2 + c * d2,
        b * c2 + d * d2,
        a * e2 + c * f2 + e,
        b * e2 + d * f2 + f,
    )


def _apply(m: Matrix, x: float, y: float) -> Point:
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


_TRANSFORM = re.compile(r"(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)")
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def parse_transform(text: str | None) -> Matrix:
    """An SVG ``transform`` attribute as one matrix."""
    matrix = _IDENTITY
    for name, args in _TRANSFORM.findall(text or ""):
        v = [float(n) for n in _NUMBER.findall(args)]
        if name == "matrix" and len(v) == 6:
            step: Matrix = tuple(v)  # type: ignore[assignment]
        elif name == "translate" and v:
            step = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0.0)
        elif name == "scale" and v:
            step = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        elif name == "rotate" and v:
            r = math.radians(v[0])
            cos, sin = math.cos(r), math.sin(r)
            step = (cos, sin, -sin, cos, 0, 0)
            if len(v) == 3:
                step = _multiply(
                    _multiply((1, 0, 0, 1, v[1], v[2]), step), (1, 0, 0, 1, -v[1], -v[2])
                )
        elif name == "skewX" and v:
            step = (1, 0, math.tan(math.radians(v[0])), 1, 0, 0)
        elif name == "skewY" and v:
            step = (1, math.tan(math.radians(v[0])), 0, 1, 0, 0)
        else:
            continue
        matrix = _multiply(matrix, step)
    return matrix


def _floats(text: str | None) -> list[float]:
    return [float(n) for n in _NUMBER.findall(text or "")]


def _ellipse_points(cx: float, cy: float, rx: float, ry: float, steps: int = 24) -> list[Point]:
    return [
        (cx + rx * math.cos(2 * math.pi * i / steps), cy + ry * math.sin(2 * math.pi * i / steps))
        for i in range(steps + 1)
    ]


def _arc_points(
    start: Point, rx: float, ry: float, phi: float, large: bool, sweep: bool, end: Point
) -> list[Point]:
    """An SVG elliptical arc as a few points (SVG spec F.6.5 centre parametrisation)."""
    if rx == 0 or ry == 0 or start == end:
        return [end]
    rx, ry = abs(rx), abs(ry)
    cos, sin = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (start[0] - end[0]) / 2, (start[1] - end[1]) / 2
    x1, y1 = cos * dx + sin * dy, -sin * dx + cos * dy
    scale = (x1 * x1) / (rx * rx) + (y1 * y1) / (ry * ry)
    if scale > 1:
        rx, ry = rx * math.sqrt(scale), ry * math.sqrt(scale)
    numerator = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    denominator = rx * rx * y1 * y1 + ry * ry * x1 * x1
    factor = math.sqrt(max(0.0, numerator / denominator)) if denominator else 0.0
    if large == sweep:
        factor = -factor
    cx1, cy1 = factor * rx * y1 / ry, -factor * ry * x1 / rx
    cx = cos * cx1 - sin * cy1 + (start[0] + end[0]) / 2
    cy = sin * cx1 + cos * cy1 + (start[1] + end[1]) / 2

    def angle(ux: float, uy: float) -> float:
        return math.atan2(uy, ux)

    theta = angle((x1 - cx1) / rx, (y1 - cy1) / ry)
    delta = angle((-x1 - cx1) / rx, (-y1 - cy1) / ry) - theta
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi
    steps = max(2, int(abs(delta) / (math.pi / 8)) + 1)
    points = []
    for i in range(1, steps + 1):
        t = theta + delta * i / steps
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        points.append((cos * ex - sin * ey + cx, sin * ex + cos * ey + cy))
    return points


def _path_polylines(d: str) -> list[list[Point]]:
    """The subpaths of an SVG path ``d`` (M, L, H, V, A, C, Q, Z; absolute or relative)."""
    tokens = re.findall(r"[MmLlHhVvAaCcSsQqTtZz]|" + _NUMBER.pattern, d)
    paths: list[list[Point]] = []
    current: list[Point] = []
    x = y = 0.0
    start = (0.0, 0.0)
    command = ""
    i = 0

    def take(n: int) -> list[float] | None:
        nonlocal i
        if i + n > len(tokens) or any(t.isalpha() for t in tokens[i : i + n]):
            return None
        values = [float(t) for t in tokens[i : i + n]]
        i += n
        return values

    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
            if command in "Zz":
                if current:
                    current.append(start)
                    paths.append(current)
                current = []
                x, y = start
                continue
        relative = command.islower()
        kind = command.upper()
        if kind == "M":
            v = take(2)
            if v is None:
                break
            if current:
                paths.append(current)
            x, y = (x + v[0], y + v[1]) if relative else (v[0], v[1])
            start = (x, y)
            current = [(x, y)]
            command = "l" if relative else "L"
        elif kind == "L" or kind == "T":
            v = take(2)
            if v is None:
                break
            x, y = (x + v[0], y + v[1]) if relative else (v[0], v[1])
            current.append((x, y))
        elif kind == "H":
            v = take(1)
            if v is None:
                break
            x = x + v[0] if relative else v[0]
            current.append((x, y))
        elif kind == "V":
            v = take(1)
            if v is None:
                break
            y = y + v[0] if relative else v[0]
            current.append((x, y))
        elif kind == "A":
            v = take(7)
            if v is None:
                break
            end = (x + v[5], y + v[6]) if relative else (v[5], v[6])
            current += _arc_points((x, y), v[0], v[1], v[2], bool(v[3]), bool(v[4]), end)
            x, y = end
        elif kind in "CSQ":
            n = {"C": 6, "S": 4, "Q": 4}[kind]
            v = take(n)
            if v is None:
                break
            ex, ey = v[-2], v[-1]
            x, y = (x + ex, y + ey) if relative else (ex, ey)
            current.append((x, y))  # the chord is enough for lint geometry
        else:
            break
        if not current:
            current = [(x, y)]
    if len(current) > 1:
        paths.append(current)
    return [p for p in paths if len(p) > 1]


# ---------------------------------------------------------------------------
# The drawn sheet
# ---------------------------------------------------------------------------


@dataclass
class Stroke:
    """One drawn polyline: a pipe, a signal line or part of a symbol outline."""

    points: list[Point]
    #: ``process`` (a pipe), ``signal`` (a signal or measuring line) or ``symbol``.
    kind: str
    #: Ids of the objects it draws, nearest first.
    owners: list[str]

    @property
    def owner(self) -> str:
        return self.owners[0] if self.owners else ""

    def segments(self) -> Iterator[tuple[Point, Point]]:
        for a, b in zip(self.points, self.points[1:], strict=False):
            if a != b:
                yield a, b


@dataclass
class Label:
    """One drawn text with its estimated box."""

    text: str
    box: Box
    owners: list[str]
    #: The export's label class (``pipingnetworksystemlabel``, ``valvelabel``, ...) or ``""``.
    css: str
    x: float
    y: float
    #: Where the text is anchored on the sheet (its x, y with the transforms applied).
    anchor: Point | None = None

    @property
    def owner(self) -> str:
        return self.owners[0] if self.owners else ""


@dataclass
class Drawing:
    """What a sheet draws, outside its border and title block."""

    width: float
    height: float
    strokes: list[Stroke] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    #: The inside of the sheet's border, where the drawing goes (None: no border drawn).
    frame: Box | None = None
    #: The title block's cells (its closed rectangles) and its texts.
    title_cells: list[Box] = field(default_factory=list)
    title_labels: list[Label] = field(default_factory=list)
    #: The top left corner of the SVG's viewBox: negative when something is drawn left of or
    #: above the sheet (pyDEXPI grows the viewBox to cover it).
    origin: tuple[float, float] = (0.0, 0.0)

    @property
    def box(self) -> Box:
        """The region the SVG shows: its viewBox as ``(x0, y0, x1, y1)``."""
        x, y = self.origin
        return (x, y, x + self.width, y + self.height)


def _local(element: etree._Element) -> str:
    return etree.QName(element).localname if isinstance(element.tag, str) else ""


def read_drawing(svg: etree._Element, kinds: dict[str, str]) -> Drawing:
    """The strokes and texts of an exported sheet.

    *kinds* maps object ids to their DEXPI class (``Plant/Piping.Pipe``, ...), to tell pipes
    and signal lines from symbol outlines.
    """
    box = _floats(svg.get("viewBox"))
    x, y, width, height = box if len(box) == 4 else (0.0, 0.0, 420.0, 297.0)
    drawing = Drawing(width, height, origin=(x, y))
    content = next((g for g in svg.iter("{*}g", "g") if g.get("class") == "diagram"), svg)
    frames = {"border": Drawing(width, height), "label": Drawing(width, height)}

    def visit(
        element: etree._Element,
        matrix: Matrix,
        owners: list[str],
        shaped: bool,
        into: Drawing = drawing,
    ) -> None:
        name = _local(element)
        if not name:
            return
        transform = element.get("transform")
        if transform:
            matrix = _multiply(matrix, parse_transform(transform))
        if name == "g":
            css = element.get("class", "")
            if element.getparent() is content and css in frames:
                into = frames[css]  # the sheet frame and title block, kept apart
            if element.get("id") and css == "representation-group":
                owners = [element.get("id"), *owners]
            shaped = shaped or bool(transform)
            for child in element:
                visit(child, matrix, owners, shaped, into)
            return
        if name == "text":
            _add_text(into, element, matrix, owners)
            return
        if element.get("stroke") in (None, "none") and name != "text":
            return
        lines: list[list[Point]] = []
        if name in ("polyline", "polygon"):
            values = _floats(element.get("points"))
            points = list(zip(values[::2], values[1::2], strict=False))
            if name == "polygon" and points:
                points.append(points[0])
            lines.append(points)
        elif name == "line":
            v = [float(element.get(a, 0) or 0) for a in ("x1", "y1", "x2", "y2")]
            lines.append([(v[0], v[1]), (v[2], v[3])])
        elif name in ("ellipse", "circle"):
            cx, cy = float(element.get("cx", 0) or 0), float(element.get("cy", 0) or 0)
            rx = float(element.get("rx", element.get("r", 0)) or 0)
            ry = float(element.get("ry", element.get("r", 0)) or 0)
            lines.append(_ellipse_points(cx, cy, rx, ry))
        elif name == "rect":
            x, y = float(element.get("x", 0) or 0), float(element.get("y", 0) or 0)
            w, h = float(element.get("width", 0) or 0), float(element.get("height", 0) or 0)
            lines.append([(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)])
        elif name == "path":
            lines += _path_polylines(element.get("d", ""))
        kind = "symbol"
        if not shaped:
            owner_class = kinds.get(owners[0], "") if owners else ""
            if owner_class.endswith(".Pipe"):
                kind = "process"
            elif "LineFunction" in owner_class or element.get("stroke-dasharray"):
                kind = "signal"
        for points in lines:
            mapped = [_apply(matrix, x, y) for x, y in points]
            if len(mapped) > 1:
                into.strokes.append(Stroke(mapped, kind, owners))

    for child in content:
        visit(child, _IDENTITY, [], False)
    rectangles = [_bounds(s.points) for s in frames["border"].strokes if _closed(s)]
    inner = [r for r in rectangles if _area(r) > 0.5 * width * height]
    drawing.frame = min(inner, key=_area) if inner else None
    drawing.title_cells = [_bounds(s.points) for s in frames["label"].strokes if _closed(s)]
    drawing.title_labels = frames["label"].labels
    return drawing


def _closed(stroke: Stroke) -> bool:
    """Whether *stroke* is a closed rectangle (a frame or a title block cell)."""
    points = stroke.points
    return len(points) == 5 and math.dist(points[0], points[-1]) < 1e-6


def _add_text(drawing: Drawing, element: etree._Element, matrix: Matrix, owners: list[str]) -> None:
    """*element* (a ``<text>``) with its box; *matrix* already holds its own transform."""
    content = "".join(element.itertext()).strip()
    if not content:
        return
    try:
        x, y = float(element.get("x", 0) or 0), float(element.get("y", 0) or 0)
        size = float(element.get("font-size", "3") or 3)
    except ValueError:
        return
    local = text_box(
        x, y, content, size, element.get("text-anchor"), element.get("dominant-baseline")
    )
    corners = [_apply(matrix, cx, cy) for cx in (local[0], local[2]) for cy in (local[1], local[3])]
    xs, ys = [c[0] for c in corners], [c[1] for c in corners]
    parent = element.getparent()
    css = parent.get("class", "") if parent is not None and _local(parent) == "g" else ""
    css = "" if css in ("representation-group", "static") else css
    box = (min(xs), min(ys), max(xs), max(ys))
    drawing.labels.append(Label(content, box, owners, css, x, y, _apply(matrix, x, y)))


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------


def _shrink(box: Box, by: float) -> Box:
    return (box[0] + by, box[1] + by, box[2] - by, box[3] - by)


def _grow(box: Box, by: float) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _clip(a: Point, b: Point, box: Box) -> tuple[Point, Point] | None:
    """The part of segment a-b inside *box* (Liang-Barsky), or None."""
    x0, y0, x1, y1 = box
    if x0 >= x1 or y0 >= y1:
        return None
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        t = q / p
        if p < 0:
            if t > t1:
                return None
            t0 = max(t0, t)
        else:
            if t < t0:
                return None
            t1 = min(t1, t)
    if t0 > t1:
        return None
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def _cross(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    """Where segments a-b and c-d cross away from all four ends, or None."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-12:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    length_ab, length_cd = math.hypot(rx, ry), math.hypot(sx, sy)
    if not (0 < t < 1 and 0 < u < 1):
        return None
    if min(t, 1 - t) * length_ab < JOINT_TOLERANCE or min(u, 1 - u) * length_cd < JOINT_TOLERANCE:
        return None
    return (a[0] + t * rx, a[1] + t * ry)


def _point_box_distance(p: Point, box: Box) -> float:
    dx = max(box[0] - p[0], 0.0, p[0] - box[2])
    dy = max(box[1] - p[1], 0.0, p[1] - box[3])
    return math.hypot(dx, dy)


def _segment_point_distance(a: Point, b: Point, p: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = (
        0.0
        if length == 0
        else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length))
    )
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def segment_box_distance(a: Point, b: Point, box: Box) -> float:
    """The shortest distance between segment a-b and *box* (0 when they meet)."""
    if _clip(a, b, box) is not None:
        return 0.0
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    return min(
        min(_point_box_distance(a, box), _point_box_distance(b, box)),
        min(_segment_point_distance(a, b, c) for c in corners),
    )


def _overlap(p: Box, q: Box) -> tuple[float, float]:
    return (min(p[2], q[2]) - max(p[0], q[0]), min(p[3], q[3]) - max(p[1], q[1]))


def _union(boxes: Iterable[Box]) -> Box:
    boxes = list(boxes)
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def _bounds(points: Iterable[Point]) -> Box:
    points = list(points)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


class _Grid:
    """A uniform grid over boxes, to find what may meet a box without testing everything."""

    def __init__(self, cell: float = 10.0) -> None:
        self.cell = cell
        self.cells: dict[tuple[int, int], list[int]] = {}

    def _keys(self, box: Box) -> Iterator[tuple[int, int]]:
        c = self.cell
        for i in range(math.floor(box[0] / c), math.floor(box[2] / c) + 1):
            for j in range(math.floor(box[1] / c), math.floor(box[3] / c) + 1):
                yield i, j

    def add(self, index: int, box: Box) -> None:
        for key in self._keys(box):
            self.cells.setdefault(key, []).append(index)

    def near(self, box: Box) -> set[int]:
        found: set[int] = set()
        for key in self._keys(box):
            found.update(self.cells.get(key, ()))
        return found


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


@dataclass
class DrawingFinding:
    """One geometry finding, before it is turned into a validate ``Finding``."""

    rule: str
    level: str
    message: str
    ids: list[str]
    box: Box
    #: What makes the finding's id stable: the objects (and the text) it is about.
    key: str
    #: A drawn text the finding is about (for its line in the file).
    text: Label | None = None
    hint: str = ""

    def crop(self, sheet: Box, margin: float = CROP_MARGIN) -> Box:
        """The finding's box plus *margin*, the margin kept inside *sheet* (the drawing's
        viewBox). The finding's own box is never cut, so the crop always shows it."""
        x0, y0, x1, y1 = _grow(self.box, margin)
        bx0, by0, bx1, by1 = self.box
        return (
            max(min(sheet[0], bx0), x0),
            max(min(sheet[1], by0), y0),
            min(max(sheet[2], bx1), x1),
            min(max(sheet[3], by1), y1),
        )


def crop_text(box: Box) -> str:
    """``X0,Y0,X1,Y1`` rounded to 0.1 mm, outward."""
    x0, y0, x1, y1 = box
    return ",".join(
        f"{v:g}"
        for v in (
            math.floor(x0 * 10) / 10,
            math.floor(y0 * 10) / 10,
            math.ceil(x1 * 10) / 10,
            math.ceil(y1 * 10) / 10,
        )
    )


def _slug(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())[:40]


@dataclass
class Context:
    """What the rules know about the objects of the sheet (from its XML)."""

    #: DEXPI class of every object id.
    kinds: dict[str, str]
    #: The printed name of an object (tag, line number), for messages.
    names: dict[str, str]
    #: Ids an object belongs to besides its drawing ancestors (a pipe -> its line).
    parents: dict[str, str] = field(default_factory=dict)
    #: For a literal text naming tags: the ids of the objects it names, by (text, x, y).
    named: dict[tuple[str, float, float], list[str]] = field(default_factory=dict)
    #: The valve each actuator operates (an actuating system's actuator -> its valve).
    actuated: dict[str, str] = field(default_factory=dict)

    def name(self, object_id: str) -> str:
        name = self.names.get(object_id)
        parent = self.parents.get(object_id)
        if not name and parent:
            name = self.names.get(parent)
        return f"{name} ({object_id})" if name and name != object_id else object_id

    def is_body(self, object_id: str) -> bool:
        """Whether *object_id* is an equipment item drawn with a body (not a nozzle)."""
        return self.category(object_id) == "equipment" and "Nozzle" not in self.kinds.get(
            object_id, ""
        )

    def is_actuator(self, object_id: str) -> bool:
        """Whether *object_id* is an actuator (drawn on its valve's stem)."""
        return self.kinds.get(object_id, "").endswith("Actuator")

    def category(self, object_id: str) -> str:
        kind = self.kinds.get(object_id, "")
        short = kind.rsplit(".", 1)[-1]
        if kind.startswith(("Plant/ProcessEquipment.", "Plant/Equipment")):
            return "equipment"
        if short.endswith(("Valve", "Cock", "Damper")) or "Valve" in short:
            return "valve"
        if short == "ProcessInstrumentationFunction":
            return "instrument"
        if short == "PipingNetworkSystem":
            return "line"
        return short


def equipment_bodies(drawing: Drawing, context: Context) -> dict[str, list[Stroke]]:
    """The symbol strokes of each equipment item's own body, by its id.

    Its nozzles and the parts drawn as objects of their own (a chamber, a tube bundle, an
    impeller) are left out, and so is an item drawn inside another one (its strokes belong to
    the outer item's drawing only where they are the outer item's own).
    """
    bodies: dict[str, list[Stroke]] = {}
    for stroke in drawing.strokes:
        if stroke.kind != "symbol" or not stroke.owners:
            continue
        owner = stroke.owners[0]
        if not context.is_body(owner):
            continue
        if any(context.category(o) == "equipment" for o in stroke.owners[1:]):
            continue
        bodies.setdefault(owner, []).append(stroke)
    return bodies


#: A column stroke this far (mm) inside the top and bottom of the column's outline is an
#: internal (a packed bed, a tray), which a tag inside the column may cross.
INTERNAL_MARGIN = 0.5


def _outline(strokes: list[Stroke], kind: str) -> list[Stroke]:
    """The strokes of a body that draw its outline: a column's internals left out."""
    if "Column" not in kind:
        return strokes
    top = min(p[1] for s in strokes for p in s.points)
    bottom = max(p[1] for s in strokes for p in s.points)
    return [
        s
        for s in strokes
        if min(p[1] for p in s.points) <= top + INTERNAL_MARGIN
        or max(p[1] for p in s.points) >= bottom - INTERNAL_MARGIN
    ]


def _line_kind(stroke: Stroke) -> str:
    return "pipe" if stroke.kind == "process" else "signal line"


def lint_drawing(drawing: Drawing, context: Context) -> list[DrawingFinding]:
    """Every geometry finding on one sheet."""
    findings: list[DrawingFinding] = []
    lines = [s for s in drawing.strokes if s.kind in ("process", "signal")]
    symbols = [s for s in drawing.strokes if s.kind == "symbol"]
    findings += _through_labels(drawing, lines, context)
    findings += _crossings(lines, context)
    findings += _overlaps(drawing, symbols, context)
    findings += _far_labels(drawing, context)
    findings += _outside_frame(drawing, context)
    findings += _title_overflow(drawing)
    findings += _through_symbols(lines, symbols, context)
    findings += _through_valves(lines, symbols, context)
    findings += _on_pipes(lines, context)
    findings += _not_orthogonal(lines, context)
    findings += _offpage_not_on_edge(drawing, context)
    return findings


#: How far a text may stick out of the frame (mm).
OUTSIDE_TOLERANCE = 0.5
#: How far a title block text may stick out of its cell (mm): the text width is estimated, and
#: the template's own captions fill their cells.
TITLE_TOLERANCE = 2.0
#: A line ending this close to a crossing with a bubble outline ends on the bubble (mm).
ENDS_ON = 1.0
#: How far a line must run inside an equipment body's box to go through it (mm): less runs
#: along its outline (a pipe drawn down the vessel wall from a side nozzle).
BODY_DEPTH = 1.0


def _outside_frame(drawing: Drawing, context: Context) -> list[DrawingFinding]:
    frame = drawing.frame or drawing.box
    findings = []
    for label in drawing.labels:
        box = label.box
        out = max(frame[0] - box[0], frame[1] - box[1], box[2] - frame[2], box[3] - frame[3])
        if out <= OUTSIDE_TOLERANCE:
            continue
        whose = context.name(label.owner) if label.owner else "the sheet"
        findings.append(
            DrawingFinding(
                "cheme.text-outside-frame",
                "warning",
                f"text {label.text!r} of {whose} runs {out:.1f} mm outside the drawing frame",
                [label.owner] if label.owner else [],
                box,
                f"{label.owner}:{_slug(label.text)}:outside",
                text=label,
                hint="move the text inside the frame (an off-page note goes on the inner side "
                "of its connector)",
            )
        )
    return findings


def _title_overflow(drawing: Drawing) -> list[DrawingFinding]:
    findings = []
    for label in drawing.title_labels:
        if label.anchor is None:
            continue
        x, y = label.anchor
        cells = [
            c
            for c in drawing.title_cells
            if c[0] - 0.1 <= x <= c[2] + 0.1 and c[1] - 0.1 <= y <= c[3] + 0.1
        ]
        if not cells:
            continue
        cell = min(cells, key=_area)
        out = max(cell[0] - label.box[0], label.box[2] - cell[2])
        if out <= TITLE_TOLERANCE:
            continue
        findings.append(
            DrawingFinding(
                "cheme.title-text-overflow",
                "warning",
                f"title block text {label.text!r} is {out:.1f} mm wider than its cell",
                [],
                _union([label.box, cell]),
                f"title:{_slug(label.text)}",
                text=label,
                hint="shorten the text (the sheet title comes from plant.yaml; cheme sheet "
                "meta prints the title block)",
            )
        )
    return findings


def _meets(a: Point, b: Point, c: Point, d: Point) -> Point | None:
    """Where segment a-b meets the outline segment c-d (its ends included), or None."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denominator = rx * sy - ry * sx
    if abs(denominator) < 1e-12:
        return None
    qx, qy = c[0] - a[0], c[1] - a[1]
    t = (qx * sy - qy * sx) / denominator
    u = (qx * ry - qy * rx) / denominator
    if not (0 <= t <= 1 and 0 <= u <= 1):
        return None
    return (a[0] + t * rx, a[1] + t * ry)


def _through_symbols(
    lines: list[Stroke], symbols: list[Stroke], context: Context
) -> list[DrawingFinding]:
    """Pipes and signal lines running through an instrument bubble or an equipment body they do
    not end on."""
    bubbles = []
    for stroke in symbols:
        owner = next((o for o in stroke.owners if context.category(o) == "instrument"), None)
        if owner is not None:
            bubbles.append((stroke, owner))
    body_box: dict[str, Box] = {}
    for owner, strokes in equipment_bodies(Drawing(0, 0, symbols), context).items():
        bubbles += [(stroke, owner) for stroke in strokes]
        body_box[owner] = _bounds(p for stroke in strokes for p in stroke.points)
    if not bubbles:
        return []
    segments, grid = _segment_grid([s for s, _ in bubbles])
    owner_of = {id(s): owner for s, owner in bubbles}
    found: dict[tuple[str, str], tuple[Stroke, list[Point]]] = {}
    for line in lines:
        ends = (line.points[0], line.points[-1])
        for a, b in line.segments():
            for index in sorted(grid.near(_bounds((a, b)))):
                c, d, bubble = segments[index]
                instrument = owner_of[id(bubble)]
                if instrument in line.owners:
                    continue
                box = body_box.get(instrument)
                if box is not None:
                    if any(_inside(e, box) for e in ends):
                        continue  # to an internal or a tap inside the body
                    inner = _clip(a, b, _shrink(box, BODY_DEPTH))
                    if inner is None or math.dist(*inner) <= BODY_DEPTH:
                        continue  # along or past the outline, not through the body
                point = _meets(a, b, c, d)
                if point is None or any(math.dist(point, e) <= ENDS_ON for e in ends):
                    continue
                _, points = found.setdefault((line.owner, instrument), (line, []))
                if all(math.dist(point, p) > JOINT_TOLERANCE for p in points):
                    points.append(point)
    findings = []
    for (line_id, instrument), (line, points) in found.items():
        body = instrument in body_box
        findings.append(
            DrawingFinding(
                "cheme.line-through-symbol",
                "warning",
                f"{_line_kind(line)} {context.name(line_id)} runs through the "
                f"{'body' if body else 'bubble'} of {context.name(instrument)}",
                [line_id, instrument],
                _grow(_bounds(points), 1.0),
                f"{line_id}+{instrument}:symbol",
                hint=(
                    "route the line around the equipment, or end it at a nozzle"
                    if body
                    else "move the instrument clear of the line, or route the line around it"
                ),
            )
        )
    return findings


#: How far a line must run inside the box of a valve's or an actuator's outline to go through it
#: (mm): the symbols are small (a globe valve 4 x 2 mm, an actuator 3.6 mm across).
VALVE_DEPTH = 0.3


def valve_parts(symbols: list[Stroke], context: Context) -> dict[str, list[tuple[Stroke, Box]]]:
    """The outlines of each valve and actuator, with their boxes, by the valve's or actuator's id.

    An outline is a symbol stroke of three points or more (the valve's body, a ball, an actuator's
    head); a two-point stroke (an actuator's stem, a gate valve's bar) is no body to run through.
    """
    parts: dict[str, list[tuple[Stroke, Box]]] = {}
    for stroke in symbols:
        if stroke.kind != "symbol" or not stroke.owners or len(stroke.points) < 3:
            continue
        owner = stroke.owners[0]
        if context.category(owner) != "valve" and not context.is_actuator(owner):
            continue
        box = _bounds(stroke.points)
        if min(box[2] - box[0], box[3] - box[1]) <= 2 * VALVE_DEPTH:
            continue
        parts.setdefault(owner, []).append((stroke, box))
    return parts


def _through_valves(
    lines: list[Stroke], symbols: list[Stroke], context: Context
) -> list[DrawingFinding]:
    """Lines running through the body of a valve or an actuator they do not end on.

    A valve's own pipes (of the segment it sits on) may run into it; a signal or measuring line,
    or another line's pipe, may not, and no line may run through an actuator (the pipe its valve
    sits on included: an actuator drawn on the pipe). A line with an end inside the outline ends
    on it (a signal line to the actuator's centre), and so does one meeting it within
    ``ENDS_ON`` of its end (a signal line to the top of the actuator).
    """
    parts = valve_parts(symbols, context)
    if not parts:
        return []
    owner_of = {id(stroke): owner for owner, found in parts.items() for stroke, _ in found}
    box_of = {id(stroke): box for found in parts.values() for stroke, box in found}
    segments, grid = _segment_grid([stroke for found in parts.values() for stroke, _ in found])
    #: (line, valve) -> the line, the parts it runs through (valve body, actuator), the points.
    found: dict[tuple[str, str], tuple[Stroke, dict[str, str], list[Point]]] = {}
    for line in lines:
        ends = (line.points[0], line.points[-1])
        for a, b in line.segments():
            for index in sorted(grid.near(_bounds((a, b)))):
                c, d, outline = segments[index]
                owner = owner_of[id(outline)]
                if owner in line.owners:
                    continue
                actuator = context.is_actuator(owner)
                if (
                    line.kind == "process"
                    and not actuator
                    and set(line.owners) & set(outline.owners[1:])
                ):
                    continue  # the pipe the valve sits on
                inner = _shrink(box_of[id(outline)], VALVE_DEPTH)
                if any(_inside(e, inner) for e in ends):
                    continue  # ends on the valve or the actuator
                clipped = _clip(a, b, inner)
                if clipped is None or math.dist(*clipped) <= VALVE_DEPTH:
                    continue  # along or past the outline
                point = _meets(a, b, c, d)
                if point is None or any(math.dist(point, e) <= ENDS_ON for e in ends):
                    continue
                valve = context.actuated.get(owner, owner)
                _, hit, points = found.setdefault((line.owner, valve), (line, {}, []))
                hit["actuator" if actuator else "body"] = owner
                if all(math.dist(point, p) > JOINT_TOLERANCE for p in points):
                    points.append(point)
    findings = []
    for (line_id, valve), (line, hit, points) in found.items():
        if "body" in hit and "actuator" in hit:
            what = f"the body and the actuator of {context.name(valve)}"
        elif "body" in hit:
            what = f"the body of {context.name(valve)}"
        elif valve != hit["actuator"]:
            what = f"the actuator of {context.name(valve)}"
        else:
            what = f"the actuator {context.name(valve)}"
        if line.kind == "process" and "actuator" in hit:
            hint = (
                "turn the actuator off the pipe: its stem at right angles to the pipe, the "
                "signal line arriving at the actuator from the side away from the pipe"
            )
        elif line.kind == "process":
            hint = "route the pipe around the valve, or end it at the valve's node"
        elif "body" in hit:
            hint = (
                "route the line around the valve: a signal line arrives at the actuator from "
                "the side away from the pipe, a measuring line taps the pipe clear of the valve"
            )
        else:
            hint = "end the signal line on the side of the actuator it comes from"
        findings.append(
            DrawingFinding(
                "cheme.line-through-valve",
                "warning",
                f"{_line_kind(line)} {context.name(line_id)} runs through {what}",
                list(dict.fromkeys([line_id, valve, *hit.values()])),
                _grow(_bounds(points), 1.0),
                f"{line_id}+{valve}",
                hint=hint,
            )
        )
    return findings


#: A signal line this close (mm) to a pipe, parallel to it, is drawn on it ...
ON_PIPE_DISTANCE = 0.3
#: ... when it runs along it this far (mm).
ON_PIPE_LENGTH = 1.0


def _on_pipes(lines: list[Stroke], context: Context) -> list[DrawingFinding]:
    """Signal and measuring lines drawn on top of a pipe: a horizontal or vertical stretch of
    the signal line on a pipe's stretch, longer than ``ON_PIPE_LENGTH``."""
    pipes = [s for s in lines if s.kind == "process"]
    if not pipes:
        return []
    segments, grid = _segment_grid(pipes)
    found: dict[tuple[str, str], tuple[Stroke, Stroke, list[Point]]] = {}
    for line in lines:
        if line.kind != "signal":
            continue
        for a, b in line.segments():
            for axis in (0, 1):
                across = 1 - axis
                if abs(a[across] - b[across]) > 0.05:
                    continue
                for index in sorted(grid.near(_grow(_bounds((a, b)), ON_PIPE_DISTANCE))):
                    c, d, pipe = segments[index]
                    if abs(c[across] - d[across]) > 0.05:
                        continue
                    if abs(a[across] - c[across]) > ON_PIPE_DISTANCE:
                        continue
                    low = max(min(a[axis], b[axis]), min(c[axis], d[axis]))
                    high = min(max(a[axis], b[axis]), max(c[axis], d[axis]))
                    if high - low <= ON_PIPE_LENGTH:
                        continue
                    ends = [(low, a[across]), (high, a[across])]
                    if axis == 1:
                        ends = [(a[across], low), (a[across], high)]
                    system = context.parents.get(pipe.owner, pipe.owner)
                    _, pipe_ids, points = found.setdefault((line.owner, system), (line, [], []))
                    pipe_ids.append(pipe.owner)
                    points += ends
    findings = []
    for (line_id, system), (line, pipe_ids, points) in found.items():
        box = _bounds(points)
        length = max(box[2] - box[0], box[3] - box[1])
        pipe_ids = list(dict.fromkeys(pipe_ids))
        findings.append(
            DrawingFinding(
                "cheme.line-on-pipe",
                "warning",
                f"{_line_kind(line)} {context.name(line_id)} runs along pipe "
                f"{context.name(pipe_ids[0])}, on top of it, for {length:.1f} mm",
                [line_id, *pipe_ids],
                _grow(box, 1.0),
                f"{line_id}+{system}",
                hint="route the signal line clear of the pipe (it crosses a pipe at right angles); "
                "turn an actuator drawn on the pipe off it",
            )
        )
    return findings


#: A signal line stretch at least this long (mm) ...
SLANT_LENGTH = 2.0
#: ... and more than this many degrees off horizontal and vertical is slanted.
SLANT_ANGLE = 1.0


def _not_orthogonal(lines: list[Stroke], context: Context) -> list[DrawingFinding]:
    """Signal and measuring lines with a slanted stretch (one finding per line). Shorter
    stretches are left out: a hop over a crossing line is drawn with short slanted legs."""
    findings = []
    for line in lines:
        if line.kind != "signal":
            continue
        slanted = []
        for a, b in line.segments():
            dx, dy = abs(b[0] - a[0]), abs(b[1] - a[1])
            if math.hypot(dx, dy) < SLANT_LENGTH:
                continue
            if math.degrees(math.atan2(min(dx, dy), max(dx, dy))) > SLANT_ANGLE:
                slanted.append((a, b))
        if not slanted:
            continue
        where = ", ".join(f"({a[0]:.1f},{a[1]:.1f})-({b[0]:.1f},{b[1]:.1f})" for a, b in slanted)
        findings.append(
            DrawingFinding(
                "cheme.line-not-orthogonal",
                "info",
                f"{_line_kind(line)} {context.name(line.owner)} runs slanted from {where}",
                [line.owner],
                _bounds(p for segment in slanted for p in segment),
                f"{line.owner}",
                hint="draw it in horizontal and vertical stretches (a corner point where it turns)",
            )
        )
    return findings


#: An off-page connector this close (mm) to an edge of the drawing area sits on it ...
EDGE_TOLERANCE = 10.0
#: ... and so does one up to this far in with nothing but its own line and texts drawn between
#: it and the edge (a header sheet's row of connectors, its texts outside it; the DEXPI
#: reference P&ID's two connectors, 27 and 31 mm in).
EDGE_REACH = 35.0
#: An open end drawn where it is (to atmosphere, a drain, a hose connection), not a connection
#: to another sheet: its id or its own text says so ("to atm.", "to drain"; a closed drain is a
#: header elsewhere) ...
LOCAL_END = re.compile(
    r"\b(atm|atmosphere|sky|safe location|vent|breather|hose|funnel|sewer)\b|(?<!closed )\bdrain\b"
)
#: ... unless its text names a sheet or the battery limit ("to vent header, P-07", "to flare
#: (B/L)"): DEXPI 2.0 draws both with the same off-page connector classes, and the sheets carry
#: no reference to the other sheet's connector, so the words are what tells them apart.
SHEET_END = re.compile(r"\bp-\d+\b|\bsheet\b|\bb/?l\b|battery limit")


@dataclass
class Placement:
    """Where an off-page connector sits on its sheet."""

    connector: str
    #: ``in``, ``out`` or ``""`` (a connector of no flow direction, such as a signal's).
    direction: str
    box: Box
    #: The nearest edge of the drawing area (``left``, ``right``, ``top``, ``bottom``) and how
    #: far (mm) the connector's symbol is from it.
    edge: str
    distance: float
    #: Whether it counts as on that edge.
    on_edge: bool
    #: Whether it is an open end drawn where it is (``LOCAL_END``, its text naming no sheet or
    #: battery limit: ``SHEET_END``), which may sit anywhere.
    local: bool


def drawing_area(drawing: Drawing) -> Box:
    """The inside of the sheet's border down to the top of its title block (the notes band
    beside the title block is below the drawing area)."""
    frame = drawing.frame or drawing.box
    if not drawing.title_cells:
        return frame
    top = _union(drawing.title_cells)[1]
    return (frame[0], frame[1], frame[2], top if frame[1] < top < frame[3] else frame[3])


def offpage_placements(drawing: Drawing, context: Context) -> list[Placement]:
    """Every drawn off-page connector of the sheet and the edge it is nearest."""
    area = drawing_area(drawing)
    symbols: dict[str, list[Stroke]] = {}
    for stroke in drawing.strokes:
        if stroke.kind == "symbol" and context.kinds.get(stroke.owner, "").endswith(
            "OffPageConnector"
        ):
            symbols.setdefault(stroke.owner, []).append(stroke)
    placements = []
    for connector, strokes in symbols.items():
        box = _bounds(p for s in strokes for p in s.points)
        own = set(strokes[0].owners)
        gaps = {
            "left": (box[0] - area[0], (area[0], box[1], box[0], box[3])),
            "right": (area[2] - box[2], (box[2], box[1], area[2], box[3])),
            "top": (box[1] - area[1], (box[0], area[1], box[2], box[1])),
            "bottom": (area[3] - box[3], (box[0], box[3], box[2], area[3])),
        }
        edge = min(gaps, key=lambda e: gaps[e][0])
        distance, strip = max(gaps[edge][0], 0.0), gaps[edge][1]
        on_edge = distance <= EDGE_TOLERANCE or (
            distance <= EDGE_REACH and _clear(drawing, _shrink(strip, THROUGH_DEPTH), own)
        )
        kind = context.kinds.get(connector, "").rsplit(".", 1)[-1]
        direction = "in" if kind.startswith("FlowIn") else "out" if "FlowOut" in kind else ""
        texts = " ".join(t.text for t in drawing.labels if connector in t.owners).lower()
        words = f"{connector.replace('_', ' ').lower()} {texts}"
        local = bool(LOCAL_END.search(words)) and not SHEET_END.search(texts)
        placements.append(Placement(connector, direction, box, edge, distance, on_edge, local))
    return placements


def _clear(drawing: Drawing, strip: Box, own: set[str]) -> bool:
    """Whether nothing but what belongs to *own* (a connector, its segment and line) is drawn
    in *strip*."""
    if strip[0] >= strip[2] or strip[1] >= strip[3]:
        return True
    for stroke in drawing.strokes:
        if own & set(stroke.owners):
            continue
        if any(_clip(a, b, strip) is not None for a, b in stroke.segments()):
            return False
    return not any(
        min(_overlap(label.box, strip)) > 0
        for label in drawing.labels
        if not own & set(label.owners)
    )


def _offpage_not_on_edge(drawing: Drawing, context: Context) -> list[DrawingFinding]:
    """Off-page connectors that do not sit on an edge of the drawing area (one finding each);
    open ends drawn where they are (to atmosphere, a drain, a hose) are left out."""
    area = drawing_area(drawing)
    findings = []
    for place in offpage_placements(drawing, context):
        if place.on_edge or place.local:
            continue
        box = place.box
        offsets = {
            "left": (area[0] + EDGE_TOLERANCE / 2 - box[0], 0.0),
            "right": (area[2] - EDGE_TOLERANCE / 2 - box[2], 0.0),
            "top": (0.0, area[1] + EDGE_TOLERANCE / 2 - box[1]),
            "bottom": (0.0, area[3] - EDGE_TOLERANCE / 2 - box[3]),
        }
        dx, dy = offsets[place.edge]
        move = f"`cheme move {place.connector} --offset={dx:.0f},{dy:.0f}`"
        side = {"in": "left", "out": "right"}.get(place.direction)
        if side and side != place.edge:
            sx, sy = offsets[side]
            move += (
                f" (an {'incoming' if side == 'left' else 'outgoing'} connector goes on the "
                f"{side} edge: --offset={sx:.0f},{sy:.0f}; a utility header's connectors may "
                "share the top or bottom edge)"
            )
        findings.append(
            DrawingFinding(
                "cheme.offpage-not-on-edge",
                "warning",
                f"off-page connector {context.name(place.connector)} sits "
                f"{place.distance:.0f} mm inside the drawing area's {place.edge} edge: a "
                "connection to another sheet or the battery limit goes on the edge (within "
                f"{EDGE_TOLERANCE:g} mm, or {EDGE_REACH:g} mm with nothing else drawn between "
                "it and the edge); only an open end whose id or text says atm., vent, drain or "
                "hose, naming no sheet or B/L, may stay by its valve",
                [place.connector],
                box,
                place.connector,
                hint=f"move it onto the nearest edge ({place.edge}): {move}; then route its "
                "line to it in horizontal and vertical stretches. A crossing this adds is "
                "accepted in the drawing-clean gate with a reason",
            )
        )
    return findings


def _inside(point: Point, box: Box) -> bool:
    return box[0] < point[0] < box[2] and box[1] < point[1] < box[3]


def _segment_grid(strokes: list[Stroke]) -> tuple[list[tuple[Point, Point, Stroke]], _Grid]:
    segments = [(a, b, s) for s in strokes for a, b in s.segments()]
    grid = _Grid()
    for index, (a, b, _) in enumerate(segments):
        grid.add(index, _bounds((a, b)))
    return segments, grid


def _through_labels(
    drawing: Drawing, lines: list[Stroke], context: Context
) -> list[DrawingFinding]:
    segments, grid = _segment_grid(lines)
    findings: list[DrawingFinding] = []
    for label in drawing.labels:
        inner = _shrink(label.box, THROUGH_DEPTH)
        if inner[0] >= inner[2] or inner[1] >= inner[3]:
            inner = label.box
        hits: dict[str, tuple[Stroke, tuple[Point, Point]]] = {}
        for index in sorted(grid.near(label.box)):
            a, b, stroke = segments[index]
            clipped = _clip(a, b, inner)
            if clipped is None or stroke.owner in hits:
                continue
            if label.owner and stroke.owner == label.owner and label.css == "":
                continue  # an instrument's own lines meet its bubble texts
            hits[stroke.owner] = (stroke, clipped)
        for owner, (stroke, (p, q)) in hits.items():
            own = label.owner in stroke.owners or context.parents.get(owner) == label.owner
            whose = "its own " if own else ""
            findings.append(
                DrawingFinding(
                    "cheme.line-through-label",
                    "warning",
                    f"{whose}{_line_kind(stroke)} {context.name(owner)} runs through the text "
                    f"{label.text!r} of {context.name(label.owner) if label.owner else 'the sheet'}"
                    f" at ({(p[0] + q[0]) / 2:.1f},{(p[1] + q[1]) / 2:.1f})",
                    [i for i in (owner, label.owner) if i],
                    _union([label.box, _bounds((p, q))]),
                    f"{owner}+{label.owner}:{_slug(label.text)}",
                    text=label,
                    hint="move the text clear of the line (about 1 mm), or route the line "
                    "around it",
                )
            )
    return findings


def _crossings(lines: list[Stroke], context: Context) -> list[DrawingFinding]:
    segments, grid = _segment_grid(lines)
    found: dict[tuple[str, str], tuple[Stroke, Stroke, list[Point]]] = {}
    for i, (a, b, first) in enumerate(segments):
        for j in sorted(grid.near(_bounds((a, b)))):
            if j <= i:
                continue
            c, d, second = segments[j]
            if first.kind == "signal" and second.kind == "signal":
                continue
            if first is second:
                continue
            point = _cross(a, b, c, d)
            if point is None:
                continue
            one, two = sorted((first, second), key=lambda s: (s.kind != "process", s.owner))
            key = (one.owner, two.owner)
            if key not in found:
                found[key] = (one, two, [])
            if all(math.dist(point, p) > JOINT_TOLERANCE for p in found[key][2]):
                found[key][2].append(point)
    findings = []
    for (first_id, second_id), (one, two, points) in found.items():
        where = ", ".join(f"({x:.1f},{y:.1f})" for x, y in points)
        findings.append(
            DrawingFinding(
                "cheme.line-crossing",
                "warning",
                f"{_line_kind(one)} {context.name(first_id)} crosses {_line_kind(two)} "
                f"{context.name(second_id)} at {where}, away from any node",
                [first_id, second_id],
                _grow(_bounds(points), 1.0),
                f"{first_id}+{second_id}",
                hint="route one line around the other; a crossing that cannot be avoided can be "
                "accepted with a reason in checks/checks.yaml (accept:)",
            )
        )
    return findings


def _belongs(label: Label, owners: list[str], context: Context) -> bool:
    """Whether a symbol drawn for *owners* (nearest first) is part of what *label* names."""
    if not label.owner or not owners:
        return False
    if owners[0] == label.owner or owners[0] in label.owners:
        return True  # the label's own symbol, or the item it is a part of
    if label.owner in owners:
        return context.category(label.owner) not in ("line", "PipingNetworkSegment")
    return False


def _overlaps(drawing: Drawing, symbols: list[Stroke], context: Context) -> list[DrawingFinding]:
    findings: list[DrawingFinding] = []
    labels = drawing.labels
    grid = _Grid()
    for index, label in enumerate(labels):
        grid.add(index, label.box)
    for i, label in enumerate(labels):
        for j in sorted(grid.near(label.box)):
            if j <= i:
                continue
            other = labels[j]
            dx, dy = _overlap(label.box, other.box)
            if dx <= OVERLAP_DEPTH or dy <= OVERLAP_DEPTH:
                continue
            first, second = sorted((label, other), key=lambda t: (t.owner, t.text))
            findings.append(
                DrawingFinding(
                    "cheme.label-overlap",
                    "warning",
                    f"text {first.text!r} of {context.name(first.owner) or 'the sheet'} overlaps "
                    f"text {second.text!r} of {context.name(second.owner) or 'the sheet'}",
                    [i for i in dict.fromkeys((first.owner, second.owner)) if i],
                    _union([first.box, second.box]),
                    f"{first.owner}:{_slug(first.text)}+{second.owner}:{_slug(second.text)}",
                    text=first,
                    hint="move one of the texts",
                )
            )
    segments, segment_grid = _segment_grid(symbols)
    for label in labels:
        inner = _shrink(label.box, SYMBOL_DEPTH)
        if inner[0] >= inner[2] or inner[1] >= inner[3]:
            continue
        hits: dict[str, list[Point]] = {}
        for index in sorted(segment_grid.near(label.box)):
            a, b, stroke = segments[index]
            if _belongs(label, stroke.owners, context):
                continue
            clipped = _clip(a, b, inner)
            if clipped is not None:
                hits.setdefault(stroke.owner, []).extend(clipped)
        for owner, points in hits.items():
            findings.append(
                DrawingFinding(
                    "cheme.label-overlap",
                    "warning",
                    f"text {label.text!r} of {context.name(label.owner) or 'the sheet'} overlaps "
                    f"the symbol of {context.name(owner)}",
                    [i for i in (label.owner, owner) if i],
                    _union([label.box, _bounds(points)]),
                    f"{label.owner}:{_slug(label.text)}+{owner}",
                    text=label,
                    hint="move the text off the symbol",
                )
            )
    findings += _on_own_outline(drawing, context)
    return findings


def _on_own_outline(drawing: Drawing, context: Context) -> list[DrawingFinding]:
    """Equipment texts (the tag) that the outline of the item's own symbol runs through."""
    bodies = equipment_bodies(drawing, context)
    findings = []
    for label in drawing.labels:
        strokes = bodies.get(label.owner)
        if not strokes:
            continue
        inner = _shrink(label.box, SYMBOL_DEPTH)
        if inner[0] >= inner[2] or inner[1] >= inner[3]:
            continue
        points = [
            point
            for stroke in _outline(strokes, context.kinds.get(label.owner, ""))
            for a, b in stroke.segments()
            if (clipped := _clip(a, b, inner)) is not None
            for point in clipped
        ]
        if not points:
            continue
        findings.append(
            DrawingFinding(
                "cheme.label-overlap",
                "warning",
                f"text {label.text!r} of {context.name(label.owner)} sits on the outline of its "
                "own symbol",
                [label.owner],
                _union([label.box, _bounds(points)]),
                f"{label.owner}:{_slug(label.text)}+own",
                text=label,
                hint="move the text inside the symbol or clear of it (about 1 mm)",
            )
        )
    return findings


def _contains(strokes: list[Stroke], box: Box) -> bool:
    """Whether the symbol *strokes* draw encloses *box* (an item drawn inside a column)."""
    outline = (
        _bounds(p for stroke in strokes if stroke.kind == "symbol" for p in stroke.points)
        if any(s.kind == "symbol" for s in strokes)
        else None
    )
    return outline is not None and (
        outline[0] <= box[0]
        and outline[1] <= box[1]
        and box[2] <= outline[2]
        and box[3] <= outline[3]
    )


def _area(box: Box) -> float:
    return (box[2] - box[0]) * (box[3] - box[1])


def _owner_strokes(drawing: Drawing) -> dict[str, list[Stroke]]:
    """The strokes drawn for each object id, its parts' strokes included."""
    found: dict[str, list[Stroke]] = {}
    for stroke in drawing.strokes:
        for owner in stroke.owners:
            found.setdefault(owner, []).append(stroke)
    return found


def _distance(box: Box, strokes: list[Stroke]) -> float:
    best = math.inf
    for stroke in strokes:
        if stroke.kind == "symbol":
            outline = _bounds(stroke.points)
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            inside = outline[0] <= centre[0] <= outline[2] and outline[1] <= centre[1] <= outline[3]
            if inside and _area(outline) > 4:
                return 0.0  # inside a symbol: a tag in its vessel
        for a, b in stroke.segments():
            best = min(best, segment_box_distance(a, b, box))
            if best == 0:
                return 0.0
    return best


def _far_labels(drawing: Drawing, context: Context) -> list[DrawingFinding]:
    strokes = _owner_strokes(drawing)
    by_category: dict[str, list[str]] = {}
    for owner in strokes:
        category = context.category(owner)
        if category in ("equipment", "valve", "instrument", "line"):
            by_category.setdefault(category, []).append(owner)
    findings: list[DrawingFinding] = []
    for label in drawing.labels:
        if not label.owner:
            continue
        named = context.named.get((label.text, round(label.x, 6), round(label.y, 6)), [])
        owners = named or [label.owner]
        drawn = [o for o in owners if strokes.get(o)]
        if not drawn:
            continue
        distances = {o: _distance(label.box, strokes[o]) for o in drawn}
        own = min(distances, key=distances.__getitem__)
        d_own = distances[own]
        if d_own > FAR_DISTANCE:
            near = _nearest(label.box, strokes, context, exclude={own})
            names = ", ".join(f"{context.name(o)} at {d:.0f} mm" for o, d in near)
            whom = (
                f"{context.name(own)}, the instrument it names first"
                if named
                else context.name(own)
            )
            findings.append(
                DrawingFinding(
                    "cheme.label-far-from-owner",
                    "warning",
                    f"text {label.text!r} is {d_own:.0f} mm from {whom}"
                    + (f"; it sits by {names}" if names else ""),
                    list(dict.fromkeys([label.owner, own])),
                    label.box,
                    f"{label.owner}:{_slug(label.text)}",
                    text=label,
                    hint=f"move it next to {context.name(own)} (within {FAR_DISTANCE:g} mm)",
                )
            )
            continue
        if named or d_own < MISATTACHED_MIN:
            continue
        category = context.category(own)
        if category not in by_category:
            continue
        around = _bounds(p for stroke in strokes[own] for p in stroke.points)
        rivals = [
            (o, _distance(label.box, strokes[o]))
            for o in by_category[category]
            if o not in owners and o not in label.owners and not _contains(strokes[o], around)
        ]
        rivals = [(o, d) for o, d in rivals if d < d_own / 2]
        if not rivals:
            continue
        rival, d_rival = min(rivals, key=lambda r: r[1])
        findings.append(
            DrawingFinding(
                "cheme.label-far-from-owner",
                "warning",
                f"text {label.text!r} of {context.name(own)} is {d_own:.1f} mm from it and "
                f"{d_rival:.1f} mm from {context.name(rival)}: it reads as {rival}'s",
                [own, rival],
                label.box,
                f"{label.owner}:{_slug(label.text)}",
                text=label,
                hint=f"move it next to {context.name(own)}",
            )
        )
    return findings


def _nearest(
    box: Box, strokes: dict[str, list[Stroke]], context: Context, exclude: set[str]
) -> list[tuple[str, float]]:
    """The nearest equipment item and the two nearest instruments to *box*."""
    found: list[tuple[str, float]] = []
    for category, count in (("equipment", 1), ("instrument", 2)):
        candidates = sorted(
            (
                (o, _distance(box, s))
                for o, s in strokes.items()
                if o not in exclude and context.category(o) == category
            ),
            key=lambda c: c[1],
        )
        found += [c for c in candidates[:count] if c[1] <= 2 * FAR_DISTANCE]
    return found


# ---------------------------------------------------------------------------
# The sheet's XML
# ---------------------------------------------------------------------------


def context_from_xml(root: etree._Element) -> Context:
    """Class and printed name of every object of a sheet; the instruments literal notes name."""
    from chemeascode.domains.piping.show import TAG_PROPERTIES, data_value, instrument_tag

    kinds: dict[str, str] = {}
    names: dict[str, str] = {}
    parents: dict[str, str] = {}
    for element in root.iter("Object"):
        object_id = element.get("id")
        if not object_id:
            continue
        kinds[object_id] = element.get("type", "")
        name = instrument_tag(element) or next(
            (v for p in TAG_PROPERTIES[:5] if (v := data_value(element, p))), None
        )
        if name:
            names[object_id] = name
        if element.get("type", "").endswith("Piping.Pipe"):
            system = next(
                (
                    a.get("id")
                    for a in element.iterancestors("Object")
                    if a.get("type", "").endswith("PipingNetworkSystem")
                ),
                None,
            )
            if system:
                parents[object_id] = system
    context = Context(kinds, names, parents)
    for system in root.iter("Object"):
        if not system.get("type", "").endswith("ActuatingSystem"):
            continue
        valves = [
            r.get("objects", "").lstrip("#")
            for r in system.iter("References")
            if r.get("property") == "Valve"
        ]
        for actuator in system.iter("Object"):
            if actuator.get("id") and actuator.get("type", "").endswith("Actuator") and valves:
                context.actuated[actuator.get("id")] = valves[0]
    instruments = {
        name: object_id
        for object_id, name in names.items()
        if kinds[object_id].endswith("ProcessInstrumentationFunction")
    }
    for text, x, y, tokens in literal_texts(root):
        # The note's subject is the tag it starts with ("LALL-4108 / TSLL-4114 trip ..."):
        # when that is an instrument of this sheet, the note belongs next to it.
        subject = resolve_instrument(tokens[0], instruments) if tokens else None
        if subject:
            context.named[(text, x, y)] = [subject]
    return context


def resolve_instrument(tag: str, instruments: dict[str, str]) -> str | None:
    """The id of the instrument *tag* names: its own tag, or a function of its loop.

    ``LALL-4108`` (the low-low alarm of level loop 4108) resolves to ``LIA-4108``: same
    measured variable (first letter), same number.
    """
    if tag in instruments:
        return instruments[tag]
    loop = instrument_loop(tag)
    if loop is None:
        return None
    return next((i for t, i in instruments.items() if instrument_loop(t) == loop), None)


def literal_texts(root: etree._Element) -> Iterator[tuple[str, float, float, list[str]]]:
    """(text, x, y, tag tokens) of each drawn text made of literal text only.

    The sheet's border and title block (texts of the diagram itself) are left out.
    """
    from chemeascode.domains.piping.sheet_index import _POSITION

    for text in root.iter("Object"):
        if text.get("type") != "Core/Diagram.Text":
            continue
        fragments = text.findall("Components[@property='Template']/Object/Components/Object")
        if any(f.get("type") != "Core/Diagram.LiteralText" for f in fragments):
            continue
        if _on_sheet_frame(text):
            continue
        cached = text.find("Data[@property='Text']/String")
        content = (cached.text or "").strip() if cached is not None else ""
        x, y = text.find(_POSITION.format("X")), text.find(_POSITION.format("Y"))
        if not content or x is None or y is None:
            continue
        try:
            position = (round(float(x.text or ""), 6), round(float(y.text or ""), 6))
        except ValueError:
            continue
        tokens = [name for token in TAG_TOKEN.findall(content) for name in expand(token)]
        yield content, *position, tokens


def _on_sheet_frame(text: etree._Element) -> bool:
    """Whether *text* is part of the diagram's own border or title block."""
    for holder in text.iterancestors("Object"):
        kind = holder.get("type", "")
        if kind == "Core/Diagram.Diagram":
            return False
        if kind in ("Core/Diagram.Border", "Core/Diagram.Label"):
            parent = holder.getparent()
            owner = parent.getparent() if parent is not None else None
            if owner is not None and owner.get("type") == "Core/Diagram.Diagram":
                return True
    return False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def lint_model(model: Any, root: etree._Element) -> tuple[list[DrawingFinding], Drawing]:
    """The geometry findings of a loaded sheet (*root*: its XML), and what it draws."""
    from chemeascode.domains.piping.render import svg_element

    svg = svg_element(model)
    context = context_from_xml(root)
    drawing = read_drawing(svg, context.kinds)
    return lint_drawing(drawing, context), drawing


#: Overlay colours: frame stroke and fill for a finding, and for an accepted one.
_OVERLAY_COLOURS = {"red": "rgb(220,0,0)", "grey": "rgb(130,130,130)"}


def overlay(svg: etree._Element, marks: list[tuple[Any, ...]]) -> etree._Element:
    """Draw each (box, caption[, colour]) of *marks* on *svg* as a frame with its caption.

    *colour* is ``red`` (default) or ``grey`` (an accepted finding).
    """
    namespace = etree.QName(svg).namespace
    tag = (lambda name: f"{{{namespace}}}{name}") if namespace else (lambda name: name)
    group = etree.SubElement(svg, tag("g"), {"class": "cheme-findings"})
    for mark in marks:
        (x0, y0, x1, y1), caption = mark[0], mark[1]
        colour = _OVERLAY_COLOURS[mark[2] if len(mark) > 2 else "red"]
        fill = "rgb(255,0,0)" if colour == _OVERLAY_COLOURS["red"] else colour
        etree.SubElement(
            group,
            tag("rect"),
            {
                "x": f"{x0:.2f}",
                "y": f"{y0:.2f}",
                "width": f"{max(x1 - x0, 0.5):.2f}",
                "height": f"{max(y1 - y0, 0.5):.2f}",
                "fill": fill,
                "fill-opacity": "0.12",
                "stroke": colour,
                "stroke-width": "0.3",
            },
        )
        label = etree.SubElement(
            group,
            tag("text"),
            {
                "x": f"{x0:.2f}",
                "y": f"{y0 - 0.4:.2f}",
                "font-family": "Arial",
                "font-size": "1.8",
                "fill": colour,
            },
        )
        label.text = caption
    return svg
