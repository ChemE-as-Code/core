"""Small XML helpers shared by ``copy`` and ``fragment``: builders, text offsets, points."""

from __future__ import annotations

import math
import re

from lxml import etree

from chemeascode.domains.piping.show import _MARKUP

#: An XML id cheme-as-code accepts (``cheme.object-without-id`` / DEXPI ids).
ID_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")

POINT = "Core/Diagram.Point"


def check_id(value: str, what: str = "id") -> str:
    if not ID_PATTERN.match(value):
        raise ValueError(
            f"{what} {value!r} is not a valid id: letters, digits and _ only, not starting "
            "with a digit (no hyphens or dots)"
        )
    return value


def element_offsets(text: str) -> list[tuple[int, int]]:
    """Character offsets ``(start, end)`` of every element, in document order (``root.iter()``).

    ``start`` is the ``<`` of the start tag, ``end`` just past the ``>`` of the end tag.
    """
    spans: list[list[int]] = []
    stack: list[int] = []
    for match in _MARKUP.finditer(text):
        closing, name, _, empty = match.group(1, 2, 3, 4)
        if name is None:
            continue
        if closing:
            if stack:
                spans[stack.pop()][1] = match.end()
        else:
            spans.append([match.start(), match.end()])
            if not empty:
                stack.append(len(spans) - 1)
    return [(start, end) for start, end in spans]


def offsets_by_element(root: etree._Element, text: str) -> dict[etree._Element, tuple[int, int]]:
    elements = [e for e in root.iter() if isinstance(e.tag, str)]
    spans = element_offsets(text)
    if len(spans) != len(elements):
        raise ValueError("cannot map the XML text to its elements (unusual markup)")
    return dict(zip(elements, spans, strict=True))


def indent_at(text: str, offset: int) -> str:
    """The whitespace that starts the line *offset* is on, up to *offset*."""
    line_start = text.rfind("\n", 0, offset) + 1
    prefix = text[line_start:offset]
    return prefix if not prefix.strip() else ""


def number(value: float) -> str:
    """A coordinate (or other drawing Double) as the reference writes it: ``160.0``, ``-2.5``, no
    ``-0.0``. Rounded to six decimals, which drops the noise of rotating and shifting points."""
    value = round(_finite(value), 6)
    if value == 0:
        value = 0.0
    return repr(value)


def data_number(value: float) -> str:
    """A Double data value with every significant digit (``4e-07``, ``12.3456789``), no ``-0.0``:
    an engineering value is never rounded to a number of decimals."""
    value = _finite(value)
    if value == 0:
        value = 0.0
    return repr(value)


def _finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{value!r} is not a finite number")
    return value


def fmt_num(value: float) -> str:
    """A number for messages: ``160``, ``119.5``."""
    return f"{round(float(value), 6):g}"


def parse_pair(text: str, what: str) -> tuple[float, float]:
    try:
        x, y = (float(v) for v in text.split(","))
    except ValueError as failure:
        raise ValueError(f"{what}: expected X,Y (two numbers), got {text!r}") from failure
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(f"{what}: not finite: {text!r}")
    return x, y


def parse_points(text: str, what: str = "--points") -> list[tuple[float, float]]:
    return [parse_pair(p.strip(), what) for p in text.split(";") if p.strip()]


def rotate(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    """(dx, dy) rotated by *degrees* on the sheet (Y down, as a ShapeUsage's Rotation)."""
    a = math.radians(degrees)
    return (dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a))


def points_of(element: etree._Element) -> list[etree._Element]:
    """Every ``Core/Diagram.Point`` value below *element*."""
    return [p for p in element.iter("AggregatedDataValue") if p.get("type") == POINT]


def point_xy(point: etree._Element) -> tuple[float, float] | None:
    try:
        return (
            float(point.findtext("Data[@property='X']/Double")),
            float(point.findtext("Data[@property='Y']/Double")),
        )
    except (TypeError, ValueError):
        return None


def shift_point(point: etree._Element, dx: float, dy: float) -> None:
    for axis, delta in (("X", dx), ("Y", dy)):
        value = point.find(f"Data[@property='{axis}']/Double")
        if value is not None and value.text is not None and delta:
            value.text = number(float(value.text) + delta)


def _arc_extremes(
    centre: tuple[float, float], rx: float, ry: float, arc: etree._Element
) -> list[tuple[float, float]]:
    """The points of an ``EllipseArc`` that bound it: its ends and the axis points it passes.

    As pyDEXPI's SVG export draws it: angles in degrees in the Y-down sheet frame, from
    ``StartAngle`` to ``EndAngle`` in the positive direction, the ellipse turned by
    ``Rotation``.
    """
    try:
        start = float(arc.findtext("Data[@property='StartAngle']/Double"))
        end = float(arc.findtext("Data[@property='EndAngle']/Double"))
    except (TypeError, ValueError):
        return [(centre[0] - rx, centre[1] - ry), (centre[0] + rx, centre[1] + ry)]
    try:
        turn = math.radians(float(arc.findtext("Data[@property='Rotation']/Double") or 0.0))
    except ValueError:
        turn = 0.0
    sweep = (end - start) % 360.0 or 360.0
    # The ends, and every axis direction (0, 90, 180, 270 degrees) the arc sweeps through.
    angles = [start, start + sweep]
    angles += [start + a for a in ((k * 90.0 - start) % 360.0 for k in range(4)) if a <= sweep]
    # A turned ellipse's extremes are not at the axis points: sample it as well.
    if abs(math.sin(2 * turn)) > 1e-9:
        angles += [start + sweep * i / 72 for i in range(73)]
    cos_t, sin_t = math.cos(turn), math.sin(turn)
    found = []
    for angle in angles:
        a = math.radians(angle)
        lx, ly = rx * math.cos(a), ry * math.sin(a)
        x, y = centre[0] + lx * cos_t - ly * sin_t, centre[1] + lx * sin_t + ly * cos_t
        found.append((round(x, 9), round(y, 9)))
    return found


def extent(element: etree._Element) -> tuple[float, float, float, float] | None:
    """The box of *element*'s points, with circles and ellipses at their full radius and
    elliptic arcs as far as they reach."""
    xy = [p for p in map(point_xy, points_of(element)) if p is not None]
    for round_ in element.iter("Object"):
        kind = round_.get("type")
        if kind not in ("Core/Diagram.Ellipse", "Core/Diagram.Circle", "Core/Diagram.EllipseArc"):
            continue
        centre = round_.find("Data[@property='Center']/AggregatedDataValue")
        middle = point_xy(centre) if centre is not None else None
        try:
            if kind == "Core/Diagram.Circle":
                rx = ry = float(round_.findtext("Data[@property='Radius']/Double"))
            else:
                rx = float(round_.findtext("Data[@property='HorizontalSemiAxis']/Double"))
                ry = float(round_.findtext("Data[@property='VerticalSemiAxis']/Double"))
        except (TypeError, ValueError):
            continue
        if middle is None:
            continue
        if kind == "Core/Diagram.EllipseArc":
            xy += _arc_extremes(middle, rx, ry, round_)
        else:
            xy += [(middle[0] - rx, middle[1] - ry), (middle[0] + rx, middle[1] + ry)]
    if not xy:
        return None
    xs, ys = [p[0] for p in xy], [p[1] for p in xy]
    return min(xs), min(ys), max(xs), max(ys)


# -- builders -----------------------------------------------------------------------------------


def obj(object_id: str | None, kind: str, *children: etree._Element) -> etree._Element:
    element = etree.Element("Object")
    if object_id:
        element.set("id", object_id)
    element.set("type", kind)
    element.extend(children)
    return element


def comps(prop: str, *objects: etree._Element) -> etree._Element:
    element = etree.Element("Components", property=prop)
    element.extend(objects)
    return element


def ref(prop: str, *ids: str) -> etree._Element:
    return etree.Element("References", objects=" ".join(f"#{i}" for i in ids), property=prop)


def _data(prop: str, child: etree._Element) -> etree._Element:
    element = etree.Element("Data", property=prop)
    element.append(child)
    return element


def string(prop: str, value: str) -> etree._Element:
    child = etree.Element("String")
    child.text = value
    return _data(prop, child)


def double(prop: str, value: float) -> etree._Element:
    child = etree.Element("Double")
    child.text = number(value)
    return _data(prop, child)


def integer(prop: str, value: int) -> etree._Element:
    child = etree.Element("Integer")
    child.text = str(value)
    return _data(prop, child)


def boolean(prop: str, value: bool) -> etree._Element:
    child = etree.Element("Boolean")
    child.text = "true" if value else "false"
    return _data(prop, child)


def enum(prop: str, value: str) -> etree._Element:
    return _data(prop, etree.Element("DataReference", data=value))


def point_value(x: float, y: float) -> etree._Element:
    value = etree.Element("AggregatedDataValue", type=POINT)
    value.append(double("X", x))
    value.append(double("Y", y))
    return value


def point(prop: str, x: float, y: float) -> etree._Element:
    return _data(prop, point_value(x, y))


def points(prop: str, xy: list[tuple[float, float]]) -> etree._Element:
    element = etree.Element("Data", property=prop)
    element.extend(point_value(x, y) for x, y in xy)
    return element


def color(prop: str, r: int, g: int, b: int) -> etree._Element:
    value = etree.Element("AggregatedDataValue", type="Core/Diagram.Color")
    value.extend([integer("B", b), integer("G", g), integer("R", r)])
    return _data(prop, value)


def stroke(rgb: tuple[int, int, int], width: float) -> etree._Element:
    value = etree.Element("AggregatedDataValue", type="Core/Diagram.Stroke")
    value.extend(
        [
            color("Color", *rgb),
            enum("DashStyle", "Core/Diagram.DashStyle.Solid"),
            double("Width", width),
        ]
    )
    return _data("Stroke", value)


def to_text(element: etree._Element) -> str:
    etree.indent(element, space="  ")
    return etree.tostring(element, encoding="unicode")
