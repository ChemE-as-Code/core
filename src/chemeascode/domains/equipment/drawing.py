"""The outline drawing of a datasheet, ``equipment/datasheets/<TAG>.svg``.

Drawn from the datasheet alone (and the title block fields of ``plant.yaml``), on an A3 sheet
(420 x 297 mm, SVG units sheet millimetres):

- **Elevation**: a vertical vessel, column or tank seen from the south (site east to the right):
  shell, heads by their type, skirt, legs or lugs, tangent lines, the column sections; a
  horizontal vessel or shell-and-tube exchanger from the side, along its own axis, on its
  saddles; a machine, a plate exchanger or anything else as its box with the baseplate and the
  shaft centre line. Nozzles where the datasheet locates them (``face``, ``orientation_deg``,
  ``offset_m``, ``elevation_m``, ``axial_m``, ``projection_m``), as wide as their DN. The
  base line is labelled with the item it stands on (``support.stands_on``) or its base
  elevation (``support.elevation``), else ``base / grade``; the schematic saddles (or legs)
  of a horizontal item move clear of its bottom nozzles. An item ``housed_in`` another (no
  main dimensions of its own) says so instead of being drawn.
- **Nozzle orientation** (plan, north up for a vertical item; the item's own frame with a
  north arrow for a horizontal one): side nozzles radially at their angle, top and bottom
  nozzles at their offset, the 0/90/180/270 degree marks.
- Dimension lines for the stated main dimensions only (overall height or length, tangent to
  tangent, support height, diameter), ``*`` marking an assumed value; the nozzle schedule (the
  connected lines as the service where none is given); the
  main dimensions, weights and materials; a title block (tag, service, class, plant, project,
  revision, the datasheet's fingerprint, ``DRAFT`` for a draft).

What the datasheet does not state is not drawn as a fact: an unknown head is drawn flat with a
note, a nozzle without a location is listed in the schedule (marked) but not placed, and the
proportions the drawing needs that no dimension gives (saddle positions, nozzle stubs without a
projection) are schematic, which the notes say. The text is deterministic: the same datasheet
gives the same bytes, so ``cheme datasheets drawing --check`` can compare it with the file.
"""

from __future__ import annotations

import math
from html import escape
from typing import Any

from chemeascode.domains.equipment.outline import (
    WEIGHT_UNITS,
    Length,
    Outline,
    assumed,
    head_depth,
    number,
    outline,
    text,
)
from chemeascode.domains.equipment.schemas.datasheet import Datasheet, DatasheetNozzle, Material

SHEET = (420.0, 297.0)
#: Views and tables on the sheet: x0, y0, x1, y1 (mm).
ELEVATION = (15.0, 17.0, 215.0, 200.0)
PLAN = (220.0, 17.0, 405.0, 120.0)
SCHEDULE = (220.0, 124.0, 405.0, 216.0)
TABLE = (15.0, 204.0, 215.0, 282.0)
TITLE = (220.0, 220.0, 405.0, 282.0)
ROW = 4.0
#: A nozzle stub drawn without a projection: this length, m (schematic).
STUB = 0.3
GENERATOR = "cheme datasheets drawing"

_STYLE = """
.frame{fill:none;stroke:#000;stroke-width:0.5}
.thin{fill:none;stroke:#000;stroke-width:0.25}
.outline{fill:#fff;stroke:#000;stroke-width:0.5}
.hidden{fill:none;stroke:#000;stroke-width:0.25;stroke-dasharray:1.5 1}
.centre{fill:none;stroke:#555;stroke-width:0.18;stroke-dasharray:4 1 1 1}
.tl{fill:none;stroke:#555;stroke-width:0.18;stroke-dasharray:2 1}
.dim{fill:none;stroke:#1f4e79;stroke-width:0.18}
.nozzle{fill:#fff;stroke:#b71c1c;stroke-width:0.35}
.section{fill:none;stroke:#2e7d32;stroke-width:0.25;stroke-dasharray:2 1}
text{font-family:'DejaVu Sans',Arial,Helvetica,sans-serif;fill:#000}
.t2{font-size:2.2px}.t25{font-size:2.5px}.t3{font-size:3px}.t35{font-size:3.5px}
.t5{font-size:5px;font-weight:bold}.t7{font-size:7px;font-weight:bold}
.dimt{font-size:2.3px;fill:#1f4e79}.nt{font-size:2.3px;fill:#b71c1c}
.note{font-size:2.2px;fill:#555}
.draft{font-size:40px;font-weight:bold;fill:#c62828;fill-opacity:0.12}
"""


def _f(value: float) -> str:
    text_ = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text_ in ("-0", "") else text_


def _g(value: float) -> str:
    return f"{value:.4g}"


def _len(length: Length | None) -> str:
    if length is None:
        return ""
    return f"{_g(length.value)}{'*' if length.assumed else ''}"


class _Svg:
    def __init__(self) -> None:
        self.parts: list[str] = []
        #: nozzle labels of the current view: (x, y, suffix, anchor) -> marks, in order
        self.labels: dict[tuple[float, float, str, str], list[str]] = {}
        self.places: dict[tuple[float, float, str, str], tuple[float, float, str]] = {}

    def label(
        self,
        x: float,
        y: float,
        mark: str,
        anchor: str = "start",
        suffix: str = "",
        at: tuple[float, float] | None = None,
    ) -> None:
        """A nozzle label, drawn by :meth:`flush_labels`: labels at the same place (within
        0.5 mm, same suffix; or of nozzles at the same point *at* on the sheet) are combined
        (``N3, N4 270°``), at the place of the first."""
        cx, cy = at if at is not None else (x, y)
        key = (round(cx * 2) / 2, round(cy * 2) / 2, suffix, anchor if at is None else "at")
        if key not in self.places:
            self.places[key] = (x, y, anchor)
        self.labels.setdefault(key, []).append(mark)

    def flush_labels(self) -> None:
        """Draw the view's nozzle labels; one that would overlap a label drawn before it steps
        down until it is clear (in the order the nozzles are listed: deterministic)."""
        placed: list[tuple[float, float, float]] = []
        for key, marks in self.labels.items():
            x, y, anchor = self.places[key]
            suffix = key[2]
            value = ", ".join(marks) + (f" {suffix}" if suffix else "")
            width = 1.3 * len(value)  # about 0.55 em per character at 2.3 mm
            x0 = x if anchor == "start" else x - width if anchor == "end" else x - width / 2
            for _ in range(20):
                if not any(
                    abs(y - py) < 2.6 and x0 < px1 and px0 < x0 + width for px0, px1, py in placed
                ):
                    break
                y += 2.8
            placed.append((x0, x0 + width, y))
            self.text(x, y, value, "nt", anchor)
        self.labels, self.places = {}, {}

    def add(self, element: str) -> None:
        self.parts.append(element)

    def line(self, x1: float, y1: float, x2: float, y2: float, cls: str) -> None:
        self.add(f'<line x1="{_f(x1)}" y1="{_f(y1)}" x2="{_f(x2)}" y2="{_f(y2)}" class="{cls}"/>')

    def rect(self, x: float, y: float, w: float, h: float, cls: str) -> None:
        x, w = (x + w, -w) if w < 0 else (x, w)
        y, h = (y + h, -h) if h < 0 else (y, h)
        self.add(f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" class="{cls}"/>')

    def circle(self, x: float, y: float, r: float, cls: str) -> None:
        self.add(f'<circle cx="{_f(x)}" cy="{_f(y)}" r="{_f(max(r, 0.2))}" class="{cls}"/>')

    def path(self, d: str, cls: str) -> None:
        self.add(f'<path d="{d}" class="{cls}"/>')

    def text(
        self,
        x: float,
        y: float,
        value: str,
        cls: str = "t25",
        anchor: str = "start",
        rotate: float | None = None,
    ) -> None:
        turn = f' transform="rotate({_f(rotate)} {_f(x)} {_f(y)})"' if rotate else ""
        self.add(
            f'<text x="{_f(x)}" y="{_f(y)}" class="{cls}" text-anchor="{anchor}"{turn}>'
            f"{escape(value)}</text>"
        )

    def dimension(
        self, x1: float, y1: float, x2: float, y2: float, label: str, offset: float
    ) -> None:
        """A dimension line between two points, *offset* mm beside them (positive: to the right
        of the direction from 1 to 2 on the sheet), with extension lines and arrow heads."""
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return
        nx, ny = -dy / length * offset, dx / length * offset
        a = (x1 + nx, y1 + ny)
        b = (x2 + nx, y2 + ny)
        sign = 1 if offset >= 0 else -1
        ex, ey = -dy / length * sign, dx / length * sign
        self.line(x1 + ex * 0.8, y1 + ey * 0.8, a[0] + ex * 1.2, a[1] + ey * 1.2, "dim")
        self.line(x2 + ex * 0.8, y2 + ey * 0.8, b[0] + ex * 1.2, b[1] + ey * 1.2, "dim")
        self.line(*a, *b, "dim")
        ux, uy = dx / length, dy / length
        for (px, py), s in ((a, 1), (b, -1)):
            self.path(
                f"M{_f(px)},{_f(py)} l{_f(s * ux * 1.6 - uy * 0.5)},{_f(s * uy * 1.6 + ux * 0.5)} "
                f"l{_f(uy * 1.0)},{_f(-ux * 1.0)} z",
                "dim",
            )
        angle = math.degrees(math.atan2(dy, dx))
        if angle >= 90:
            angle -= 180
        elif angle < -90:
            angle += 180
        # the glyphs stand on the baseline towards the text's "up": keep them off the line
        up = (math.sin(math.radians(angle)), -math.cos(math.radians(angle)))
        gap = 0.8 if up[0] * ex + up[1] * ey > 0 else 2.6
        mx, my = (a[0] + b[0]) / 2 + ex * gap, (a[1] + b[1]) / 2 + ey * gap
        self.text(mx, my, label, "dimt", "middle", angle if abs(angle) > 0.1 else None)

    def svg(self) -> str:
        w, h = SHEET
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(w)}mm" height="{_f(h)}mm" '
            f'viewBox="0 0 {_f(w)} {_f(h)}">\n'
            f"<style>{_STYLE}</style>\n"
            '<rect x="0" y="0" width="420" height="297" fill="#fff"/>\n'
            + "\n".join(self.parts)
            + "\n</svg>\n"
        )


class _View:
    """A view box with a scale (mm per m), metres to sheet mm, z or y up."""

    def __init__(
        self, box: tuple[float, float, float, float], extent: tuple[float, float, float, float]
    ) -> None:
        x0, y0, x1, y1 = box
        ex0, ez0, ex1, ez1 = extent
        w, h = max(ex1 - ex0, 1e-6), max(ez1 - ez0, 1e-6)
        self.scale = min((x1 - x0) / w, (y1 - y0) / h)
        self.ox = (x0 + x1) / 2 - (ex0 + ex1) / 2 * self.scale
        self.oy = (y0 + y1) / 2 + (ez0 + ez1) / 2 * self.scale

    def x(self, value: float) -> float:
        return self.ox + value * self.scale

    def y(self, value: float) -> float:
        return self.oy - value * self.scale

    def m(self, value: float) -> float:
        return value * self.scale


def _dn_m(nozzle: DatasheetNozzle) -> float:
    dn = number(nozzle.dn) if nozzle.dn is not None else None
    return (dn or 50.0) / 1000.0


def _mark(nozzle: DatasheetNozzle) -> str:
    return nozzle.mark or nozzle.name


# -- vertical items ------------------------------------------------------------------------------


class _Vertical:
    def __init__(self, shape: Outline) -> None:
        self.o = shape
        diameter = shape.diameter
        self.D = diameter.value if diameter else 0.0
        self.R = self.D / 2
        head = shape.head
        bottom = "flat" if shape.kind == "tank" else head
        ht = head_depth(head, self.D)
        hb = head_depth(bottom, self.D)
        self.head_known = ht is not None
        self.ht = ht or 0.0
        self.hb = hb or 0.0
        self.top_head = head if ht is not None else "flat"
        self.bottom_head = bottom if hb is not None else "flat"
        # a skirt, legs or lugs carry the shell at its bottom tangent line, the bottom head
        # hanging inside; anything else stands under the bottom head
        hangs = shape.support in ("skirt", "legs", "lugs")
        given = shape.support_height.value if shape.support_height else None
        tangent = shape.tangent.value if shape.tangent else None
        total = shape.height.value if shape.height else None
        self.support_known = given is not None
        if given is not None:
            z0 = given if hangs else given + self.hb
        elif total is not None and tangent is not None:
            z0 = max(total - tangent - self.ht, self.hb)
            self.support_known = True
        else:
            z0 = self.hb
        if tangent is None:
            tangent = max((total or 0.0) - z0 - self.ht, 0.0)
        self.z0 = z0
        self.s = z0 if hangs else z0 - self.hb  # the top of the support
        self.tt = tangent
        self.z1 = self.z0 + self.tt
        self.top = self.z1 + self.ht

    def drawable(self) -> bool:
        return self.D > 0 and self.tt > 0


def _base_label(o: Outline) -> str:
    """The label of the base line: the item it stands on, its base elevation, or grade."""
    level = f"+{_len(o.support_elevation)} m" if o.support_elevation is not None else ""
    if o.support_on:
        return f"base on {o.support_on}" + (f" ({level})" if level else "")
    if level:
        return f"base {level}"
    return "base / grade"


def _nozzle_reach(nozzle: DatasheetNozzle, base: float) -> float:
    """How far a nozzle stands out from where it leaves the item, m."""
    if nozzle.projection_m is not None:
        return max(nozzle.projection_m - base, 0.05)
    return max(STUB, 2 * _dn_m(nozzle))


def _vertical_elevation(svg: _Svg, v: _Vertical, nozzles: list[DatasheetNozzle]) -> list[str]:
    o = v.o
    reach = max([_nozzle_reach(n, v.R) for n in nozzles] or [STUB])
    pad = v.R + reach
    view = _View(ELEVATION, (-pad - 0.25 * v.D, -0.06 * v.top, pad + 0.25 * v.D, v.top * 1.04))
    X, Y = view.x, view.y
    notes: list[str] = []
    R = v.R
    # support
    if v.s > 0:
        support = o.support
        if support == "skirt":
            svg.rect(X(-R), Y(v.z0), view.m(v.D), view.m(v.z0), "outline")
        elif support in ("legs", "lugs"):
            for x in (-0.8 * R, 0.8 * R):
                w = max(0.05 * v.D, 0.05)
                svg.rect(X(x - w / 2), Y(v.z0), view.m(w), view.m(v.z0), "outline")
        elif support == "base_plate":
            svg.rect(X(-0.6 * v.D), Y(v.s), view.m(1.2 * v.D), view.m(v.s), "outline")
    # bottom head, shell, top head
    if v.hb > 0:
        rx, ry = view.m(R), view.m(v.hb)
        if v.bottom_head == "cone":
            svg.path(
                f"M{_f(X(-R))},{_f(Y(v.z0))} L{_f(X(0))},{_f(Y(v.z0 - v.hb))} L{_f(X(R))},"
                f"{_f(Y(v.z0))}",
                "outline",
            )
        else:
            svg.path(
                f"M{_f(X(-R))},{_f(Y(v.z0))} A{_f(rx)},{_f(ry)} 0 0 0 {_f(X(R))},{_f(Y(v.z0))}",
                "hidden" if o.support == "skirt" else "outline",
            )
    svg.rect(X(-R), Y(v.z1), view.m(v.D), view.m(v.tt), "outline")
    if v.ht > 0:
        rx, ry = view.m(R), view.m(v.ht)
        if v.top_head in ("cone", "cone_roof"):
            svg.path(
                f"M{_f(X(-R))},{_f(Y(v.z1))} L{_f(X(0))},{_f(Y(v.top))} L{_f(X(R))},{_f(Y(v.z1))}",
                "outline",
            )
        else:
            svg.path(
                f"M{_f(X(-R))},{_f(Y(v.z1))} A{_f(rx)},{_f(ry)} 0 0 1 {_f(X(R))},{_f(Y(v.z1))}",
                "outline",
            )
    # tangent lines, centre line, grade
    for z in (v.z0, v.z1):
        if (z == v.z0 and v.hb > 0) or (z == v.z1 and v.ht > 0):
            svg.line(X(-R - 0.15 * v.D), Y(z), X(R + 0.15 * v.D), Y(z), "tl")
            svg.text(X(R + 0.16 * v.D), Y(z) + 0.8, "TL", "note")
    svg.line(X(0), Y(-0.03 * v.top), X(0), Y(v.top * 1.02), "centre")
    svg.line(X(-pad - 0.2 * v.D), Y(0), X(pad + 0.2 * v.D), Y(0), "thin")
    svg.text(X(-pad - 0.2 * v.D), Y(0) + 3, _base_label(o), "note", "end")
    # column sections
    for name, bottom, height in o.sections:
        z = v.z0 + bottom.value
        svg.rect(X(-0.9 * R), Y(z + height.value), view.m(1.8 * R), view.m(height.value), "section")
        svg.text(X(0), Y(z + height.value / 2) + 0.8, name, "t2", "middle")
    # dimensions (left of the item)
    left = X(-R)
    step = 7.0
    if o.height is not None:
        svg.dimension(left, Y(0), left, Y(v.top), f"{_len(o.height)} overall", -step * 3)
    if o.tangent is not None:
        svg.dimension(left, Y(v.z0), left, Y(v.z1), f"{_len(o.tangent)} T-T", -step * 2)
    if o.support_height is not None:
        svg.dimension(left, Y(0), left, Y(v.z0), f"{_len(o.support_height)} {o.support}", -step)
    diameter = o.od or o.id
    if diameter is not None:
        label = f"{'OD' if o.od else 'ID'} {_len(diameter)}"
        svg.dimension(X(-R), Y(0), X(R), Y(0), label, 6.0)
    if not v.head_known:
        notes.append("head type not given: drawn flat")
    if o.support not in ("", "none") and not v.support_known:
        notes.append(f"{o.support} height not given: not drawn")
    # nozzles
    for nozzle in nozzles:
        _vertical_nozzle(svg, view, v, nozzle)
    svg.flush_labels()
    return notes


def _vertical_nozzle(svg: _Svg, view: _View, v: _Vertical, nozzle: DatasheetNozzle) -> None:
    X, Y = view.x, view.y
    w = _dn_m(nozzle)
    face = nozzle.face or "side"
    theta = math.radians(nozzle.orientation_deg) if nozzle.orientation_deg is not None else None
    if face == "side":
        z = nozzle.elevation_m
        assert theta is not None and z is not None
        c = math.cos(theta)
        if abs(c) < 0.17:  # towards or away from the viewer: a circle on the shell
            svg.circle(X(v.R * c), Y(z), view.m(w / 2), "nozzle")
            svg.label(X(v.R * c) + view.m(w / 2) + 0.8, Y(z) - 0.8, _mark(nozzle))
            return
        x0 = v.R * c
        x1 = (v.R + _nozzle_reach(nozzle, v.R)) * c
        svg.rect(X(min(x0, x1)), Y(z + w / 2), view.m(abs(x1 - x0)), view.m(w), "nozzle")
        svg.line(X(x1), Y(z + w * 0.8), X(x1), Y(z - w * 0.8), "nozzle")
        anchor = "start" if c > 0 else "end"
        svg.label(X(x1) + (1.0 if c > 0 else -1.0), Y(z) + 0.8, _mark(nozzle), anchor)
        return
    offset = nozzle.offset_m or 0.0
    x = offset * math.cos(theta) if theta is not None else 0.0
    up = face == "top"
    z = nozzle.elevation_m
    if z is None:
        z = v.top if up else v.z0 - v.hb
    reach = _nozzle_reach(nozzle, 0.0)
    z1 = z + reach if up else z - reach
    svg.rect(X(x - w / 2), Y(max(z, z1)), view.m(w), view.m(abs(z1 - z)), "nozzle")
    svg.line(X(x - w * 0.8), Y(z1), X(x + w * 0.8), Y(z1), "nozzle")
    svg.label(X(x), Y(z1) + (-1.0 if up else 3.0), _mark(nozzle), "middle")


def _plan_frame(svg: _Svg, view: _View, radius: float, north_deg: float = 90.0) -> None:
    """The degree marks round a circle of *radius* (m) at the view's origin, and a north arrow
    at *north_deg* (plan angle on the sheet, counter-clockwise from the sheet's right)."""
    X, Y = view.x, view.y
    for angle in (0, 90, 180, 270):
        a = math.radians(angle)
        svg.line(
            X(0), Y(0), X(1.25 * radius * math.cos(a)), Y(1.25 * radius * math.sin(a)), "centre"
        )
    labels = {0: "0°", 90: "90°", 180: "180°", 270: "270°"}
    for angle, label in labels.items():
        a = math.radians(angle)
        x, y = X(1.33 * radius * math.cos(a)), Y(1.33 * radius * math.sin(a))
        svg.text(x, y + 0.9, label, "note", "middle")
    _north(svg, north_deg)


def _vertical_plan(svg: _Svg, v: _Vertical, nozzles: list[DatasheetNozzle]) -> None:
    reach = max([_nozzle_reach(n, v.R) for n in nozzles if (n.face or "side") == "side"] or [0])
    pad = 1.4 * (v.R + reach)
    view = _View(PLAN, (-pad, -pad, pad, pad))
    X, Y = view.x, view.y
    svg.circle(X(0), Y(0), view.m(v.R), "outline")
    _plan_frame(svg, view, v.R + reach)
    for nozzle in nozzles:
        if nozzle.orientation_deg is None and (nozzle.face or "side") == "side":
            continue
        w = _dn_m(nozzle)
        face = nozzle.face or "side"
        a = math.radians(nozzle.orientation_deg or 0.0)
        c, s = math.cos(a), math.sin(a)
        if face == "side":
            r1 = nozzle.projection_m if nozzle.projection_m is not None else v.R + STUB
            r1 = max(r1, v.R + 0.05)
            px, py = -s * w / 2, c * w / 2
            points = [
                (v.R * c + px, v.R * s + py),
                (r1 * c + px, r1 * s + py),
                (r1 * c - px, r1 * s - py),
                (v.R * c - px, v.R * s - py),
            ]
            svg.path("M" + " L".join(f"{_f(X(x))},{_f(Y(y))}" for x, y in points) + " z", "nozzle")
            lx, ly = X((r1 + 0.08 * v.D) * c), Y((r1 + 0.08 * v.D) * s)
            # off the 0/180 degree centre line: just above it, or below a southern nozzle
            dy = 3.0 if s < -0.2 else -1.2 if abs(s) <= 0.2 else -0.6
            anchor = "start" if c > 0.2 else "end" if c < -0.2 else "middle"
            svg.label(lx, ly + dy, _mark(nozzle), anchor, f"{nozzle.orientation_deg:g}°")
        else:
            offset = nozzle.offset_m or 0.0
            x, y = offset * c, offset * s
            svg.circle(X(x), Y(y), view.m(w / 2), "nozzle" if face == "top" else "hidden")
            svg.label(X(x) + view.m(w / 2) + 0.6, Y(y) - 0.6, _mark(nozzle), at=(X(x), Y(y)))
    svg.flush_labels()
    svg.text(PLAN[0] + 1, PLAN[1] + 3, "NOZZLE ORIENTATION (plan, looking down)", "t3")
    svg.text(
        PLAN[0] + 1,
        PLAN[3] - 1,
        "angles from site east (x), counter-clockwise; bottom nozzles dashed",
        "note",
    )


def _vertical_placeable(nozzle: DatasheetNozzle) -> bool:
    face = nozzle.face or ""
    if face == "side":
        return nozzle.orientation_deg is not None and nozzle.elevation_m is not None
    return face in ("top", "bottom")


# -- horizontal items ----------------------------------------------------------------------------


class _Horizontal:
    def __init__(self, shape: Outline) -> None:
        self.o = shape
        diameter = shape.diameter
        self.D = diameter.value if diameter else 0.0
        self.R = self.D / 2
        hd = head_depth(shape.head, self.D)
        self.head_known = hd is not None
        self.h = hd or 0.0
        tangent = shape.tangent.value if shape.tangent else None
        total = shape.length.value if shape.length else None
        if tangent is None:
            tangent = max((total or 0.0) - 2 * self.h, 0.0)
        self.tt = tangent
        self.L = self.tt + 2 * self.h
        lift = None
        if shape.support_height is not None:
            lift = shape.support_height.value
        elif shape.height is not None and shape.height.value > self.D:
            lift = shape.height.value - self.D
        self.lift_known = lift is not None
        self.lift = lift or 0.0
        self.zc = self.lift + self.R
        self.axis = shape.axis_deg

    def drawable(self) -> bool:
        return self.D > 0 and self.tt > 0

    def local(self, nozzle: DatasheetNozzle) -> tuple[float, float] | None:
        """(axial, lateral) of a nozzle in the item's frame, m; None when not located."""
        rel = None
        if nozzle.orientation_deg is not None and self.axis is not None:
            rel = math.radians(nozzle.orientation_deg - self.axis)
        face = nozzle.face or ""
        if nozzle.axial_m is not None:
            if face == "side":
                lateral = self.R * (1 if rel is None or math.sin(rel) >= 0 else -1)
            elif rel is not None and nozzle.offset_m is not None:
                lateral = nozzle.offset_m * math.sin(rel)
            else:
                lateral = 0.0
            return nozzle.axial_m, lateral
        if face in ("top", "bottom") and rel is not None and nozzle.offset_m is not None:
            return nozzle.offset_m * math.cos(rel), nozzle.offset_m * math.sin(rel)
        if face in ("top", "bottom") and not nozzle.offset_m:
            return 0.0, 0.0
        return None


def _clear_of_bottom_nozzles(
    h: _Horizontal, at: float, half: float, nozzles: list[DatasheetNozzle]
) -> list[float]:
    """The axial centres of the two schematic supports (*half* their width, m), at *at* each
    side of the middle, each moved the least distance (towards the middle on a tie) that keeps
    it clear of the bottom nozzles' stubs, within the tangent lines; where nothing is clear it
    stays. Deterministic: the drawing does not change unless the datasheet does."""
    gap = max(0.1, 0.02 * h.L)
    blocked = []
    for nozzle in nozzles:
        place = h.local(nozzle)
        if (nozzle.face or "side") != "bottom" or place is None:
            continue
        reach = _dn_m(nozzle) / 2 + gap + half
        blocked.append((place[0] - reach, place[0] + reach))

    def clear(x: float) -> bool:
        return all(not lo < x < hi for lo, hi in blocked)

    limit = max(h.tt / 2 - half, 0.0)
    centres = []
    for x in (-at, at):
        if clear(x):
            centres.append(x)
            continue
        edges = [e for lo, hi in blocked for e in (lo, hi)]
        free = [e for e in edges if -limit <= e <= limit and e * x > 0 and clear(e)]
        centres.append(min(free, key=lambda e: (abs(e - x), abs(e))) if free else x)
    return centres


def _horizontal_elevation(svg: _Svg, h: _Horizontal, nozzles: list[DatasheetNozzle]) -> list[str]:
    o = h.o
    top = h.zc + h.R
    view = _View(
        ELEVATION,
        (-h.L / 2 - 0.12 * h.L, -0.25 * top, h.L / 2 + 0.12 * h.L, top + 0.25 * top + STUB),
    )
    X, Y = view.x, view.y
    notes: list[str] = []
    R, x0, x1 = h.R, -h.tt / 2, h.tt / 2
    if h.lift > 0 and o.support in ("saddles", ""):
        half = 0.04 * h.D + 0.1
        for x in _clear_of_bottom_nozzles(h, 0.3 * h.L, half, nozzles):
            svg.rect(
                X(x - half), Y(h.zc - 0.7 * R), view.m(2 * half), view.m(h.zc - 0.7 * R), "outline"
            )
        notes.append("saddle positions schematic")
    elif h.lift > 0 and o.support in ("legs", "lugs"):
        half = 0.03 * h.D
        for x in _clear_of_bottom_nozzles(h, 0.35 * h.L, half, nozzles):
            svg.rect(X(x - half), Y(h.zc), view.m(2 * half), view.m(h.zc), "outline")
    svg.rect(X(x0), Y(h.zc + R), view.m(h.tt), view.m(h.D), "outline")
    if h.h > 0:
        rx, ry = view.m(h.h), view.m(R)
        svg.path(
            f"M{_f(X(x0))},{_f(Y(h.zc + R))} A{_f(rx)},{_f(ry)} 0 0 0 {_f(X(x0))},"
            f"{_f(Y(h.zc - R))}",
            "outline",
        )
        svg.path(
            f"M{_f(X(x1))},{_f(Y(h.zc + R))} A{_f(rx)},{_f(ry)} 0 0 1 {_f(X(x1))},"
            f"{_f(Y(h.zc - R))}",
            "outline",
        )
        for x in (x0, x1):
            svg.line(X(x), Y(h.zc + 1.15 * R), X(x), Y(h.zc - 1.15 * R), "tl")
            svg.text(X(x), Y(h.zc + 1.18 * R), "TL", "note", "middle")
    svg.line(X(-h.L / 2 - 0.08 * h.L), Y(h.zc), X(h.L / 2 + 0.08 * h.L), Y(h.zc), "centre")
    svg.line(X(-h.L / 2 - 0.1 * h.L), Y(0), X(h.L / 2 + 0.1 * h.L), Y(0), "thin")
    svg.text(X(-h.L / 2 - 0.1 * h.L), Y(0) + 3, _base_label(o), "note")
    if o.length is not None:
        svg.dimension(X(-h.L / 2), Y(0), X(h.L / 2), Y(0), f"{_len(o.length)} overall", 11.0)
    if o.tangent is not None:
        svg.dimension(X(x0), Y(0), X(x1), Y(0), f"{_len(o.tangent)} T-T", 5.0)
    right = X(h.L / 2)
    diameter = o.od or o.id
    if diameter is not None:
        svg.dimension(
            right,
            Y(h.zc - R),
            right,
            Y(h.zc + R),
            f"{'OD' if o.od else 'ID'} {_len(diameter)}",
            6.0,
        )
    if o.height is not None:
        svg.dimension(right, Y(0), right, Y(top), f"{_len(o.height)} overall", 14.0)
    if o.support_height is not None:
        svg.dimension(
            X(-h.L / 2), Y(0), X(-h.L / 2), Y(h.lift), f"{_len(o.support_height)} {o.support}", -6.0
        )
    if not h.head_known:
        notes.append("head type not given: drawn flat")
    if o.support not in ("", "none") and not h.lift_known:
        notes.append(f"{o.support} height not given: shell drawn on grade")
    for nozzle in nozzles:
        place = h.local(nozzle)
        if place is None:
            continue
        axial, _ = place
        w = _dn_m(nozzle)
        face = nozzle.face or "side"
        if face == "side":
            z = nozzle.elevation_m if nozzle.elevation_m is not None else h.zc
            svg.circle(X(axial), Y(z), view.m(w / 2), "nozzle")
            svg.label(X(axial) + view.m(w / 2) + 0.6, Y(z) - 0.6, _mark(nozzle))
            continue
        up = face == "top"
        z = nozzle.elevation_m if nozzle.elevation_m is not None else (h.zc + R if up else h.zc - R)
        reach = _nozzle_reach(nozzle, 0.0)
        z1 = z + reach if up else z - reach
        svg.rect(X(axial - w / 2), Y(max(z, z1)), view.m(w), view.m(abs(z1 - z)), "nozzle")
        svg.line(X(axial - w * 0.8), Y(z1), X(axial + w * 0.8), Y(z1), "nozzle")
        svg.label(X(axial), Y(z1) + (-1.0 if up else 3.0), _mark(nozzle), "middle")
    svg.flush_labels()
    return notes


def _horizontal_plan(svg: _Svg, h: _Horizontal, nozzles: list[DatasheetNozzle]) -> None:
    pad = 0.12 * h.L
    view = _View(PLAN, (-h.L / 2 - pad, -h.R - pad - STUB, h.L / 2 + pad, h.R + pad + STUB))
    X, Y = view.x, view.y
    R, x0, x1 = h.R, -h.tt / 2, h.tt / 2
    svg.rect(X(x0), Y(R), view.m(h.tt), view.m(h.D), "outline")
    if h.h > 0:
        rx, ry = view.m(h.h), view.m(R)
        svg.path(
            f"M{_f(X(x0))},{_f(Y(R))} A{_f(rx)},{_f(ry)} 0 0 0 {_f(X(x0))},{_f(Y(-R))}", "outline"
        )
        svg.path(
            f"M{_f(X(x1))},{_f(Y(R))} A{_f(rx)},{_f(ry)} 0 0 1 {_f(X(x1))},{_f(Y(-R))}", "outline"
        )
    svg.line(X(-h.L / 2 - pad / 2), Y(0), X(h.L / 2 + pad / 2), Y(0), "centre")
    for nozzle in nozzles:
        place = h.local(nozzle)
        if place is None:
            continue
        axial, lateral = place
        w = _dn_m(nozzle)
        face = nozzle.face or "side"
        if face == "side":
            sign = 1 if lateral >= 0 else -1
            y1 = sign * (R + _nozzle_reach(nozzle, 0.0))
            svg.rect(
                X(axial - w / 2),
                Y(max(sign * R, y1)),
                view.m(w),
                view.m(abs(y1 - sign * R)),
                "nozzle",
            )
            svg.label(X(axial), Y(y1) + (-1.0 if sign > 0 else 3.0), _mark(nozzle), "middle")
        else:
            svg.circle(X(axial), Y(lateral), view.m(w / 2), "nozzle" if face == "top" else "hidden")
            svg.label(
                X(axial) + view.m(w / 2) + 0.6,
                Y(lateral) - 0.6,
                _mark(nozzle),
                at=(X(axial), Y(lateral)),
            )
    svg.flush_labels()
    if h.axis is not None:
        _north(svg, 90.0 - h.axis)
        caption = f"item axis {h.axis:g}° from site east"
    else:
        caption = "item frame (axis direction not given: no north arrow)"
    svg.text(PLAN[0] + 1, PLAN[1] + 3, "PLAN (item frame, looking down)", "t3")
    svg.text(PLAN[0] + 1, PLAN[3] - 1, caption + "; bottom nozzles dashed", "note")


def _north(svg: _Svg, north_deg: float) -> None:
    x0, y0, x1, y1 = PLAN
    ax, ay = x1 - 9, y0 + 11
    a = math.radians(north_deg)
    tip = (ax + 6 * math.cos(a), ay - 6 * math.sin(a))
    tail = (ax - 4 * math.cos(a), ay + 4 * math.sin(a))
    svg.line(*tail, *tip, "thin")
    svg.path(
        f"M{_f(tip[0])},{_f(tip[1])} L{_f(ax + 2 * math.cos(a + 2.6))},"
        f"{_f(ay - 2 * math.sin(a + 2.6))} L{_f(ax + 2 * math.cos(a - 2.6))},"
        f"{_f(ay - 2 * math.sin(a - 2.6))} z",
        "thin",
    )
    svg.text(tip[0] + 2.2 * math.cos(a), tip[1] - 2.2 * math.sin(a) + 1, "N", "t3", "middle")


# -- boxes (machines, plate exchangers, anything else) -------------------------------------------


def _box_views(svg: _Svg, o: Outline, nozzles: list[DatasheetNozzle]) -> list[str]:
    L = (o.length or o.base_length or Length(0.0)).value
    W = (o.width or o.base_width or Length(0.0)).value
    H = (o.height or Length(0.0)).value
    notes: list[str] = []
    if L <= 0 or H <= 0:
        missing = [
            f"overall_{name}" for name, given in (("length", L), ("height", H)) if given <= 0
        ]
        return [f"no dimensions.{' or '.join(missing)}: no elevation drawn"]
    view = _View(ELEVATION, (-0.65 * L, -0.25 * H, 0.65 * L, 1.3 * H))
    X, Y = view.x, view.y
    svg.rect(X(-L / 2), Y(H), view.m(L), view.m(H), "outline")
    if o.base_length is not None:
        bl = o.base_length.value
        svg.rect(
            X(-bl / 2), Y(min(0.08 * H, 0.15)), view.m(bl), view.m(min(0.08 * H, 0.15)), "outline"
        )
        svg.dimension(X(-bl / 2), Y(0), X(bl / 2), Y(0), f"{_len(o.base_length)} baseplate", 5)
    if o.shaft_height is not None:
        z = o.shaft_height.value
        svg.line(X(-0.6 * L), Y(z), X(0.6 * L), Y(z), "centre")
        svg.dimension(X(L / 2), Y(0), X(L / 2), Y(z), f"{_len(o.shaft_height)} shaft", 6)
    svg.line(X(-0.62 * L), Y(0), X(0.62 * L), Y(0), "thin")
    if o.length is not None:
        svg.dimension(X(-L / 2), Y(0), X(L / 2), Y(0), f"{_len(o.length)} overall", 11)
    if o.height is not None:
        svg.dimension(X(-L / 2), Y(0), X(-L / 2), Y(H), f"{_len(o.height)} overall", -6)
    for nozzle in nozzles:
        if nozzle.axial_m is None or nozzle.elevation_m is None:
            continue
        w = _dn_m(nozzle)
        x, z = nozzle.axial_m, nozzle.elevation_m
        if (nozzle.face or "side") == "top":
            reach = _nozzle_reach(nozzle, 0.0)
            svg.rect(X(x - w / 2), Y(z + reach), view.m(w), view.m(reach), "nozzle")
            svg.label(X(x), Y(z + reach) - 1, _mark(nozzle), "middle")
        else:
            svg.circle(X(x), Y(z), view.m(w / 2), "nozzle")
            svg.label(X(x) + view.m(w / 2) + 0.6, Y(z) - 0.6, _mark(nozzle))
    svg.flush_labels()
    if W > 0:
        plan = _View(PLAN, (-0.7 * L, -0.9 * W, 0.7 * L, 0.9 * W))
        PX, PY = plan.x, plan.y
        svg.rect(PX(-L / 2), PY(W / 2), plan.m(L), plan.m(W), "outline")
        if o.base_length is not None and o.base_width is not None:
            bl, bw = o.base_length.value, o.base_width.value
            svg.rect(PX(-bl / 2), PY(bw / 2), plan.m(bl), plan.m(bw), "hidden")
            svg.dimension(
                PX(L / 2), PY(-bw / 2), PX(L / 2), PY(bw / 2), f"{_len(o.base_width)} baseplate", 5
            )
        if o.width is not None:
            svg.dimension(
                PX(-L / 2), PY(-W / 2), PX(-L / 2), PY(W / 2), f"{_len(o.width)} overall", -5
            )
        svg.line(PX(-0.65 * L), PY(0), PX(0.65 * L), PY(0), "centre")
        if o.axis_deg is not None:
            _north(svg, 90.0 - o.axis_deg)
        svg.text(PLAN[0] + 1, PLAN[1] + 3, "PLAN (item frame, looking down)", "t3")
    else:
        notes.append("no overall width: no plan drawn")
    notes.append("outline as the overall box; the shape inside is the supplier's")
    return notes


# -- tables --------------------------------------------------------------------------------------


def _short(value: str, size: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= size else value[: size - 1] + "…"


def _schedule(svg: _Svg, nozzles: list[DatasheetNozzle], placed: set[str]) -> None:
    x0, y0, x1, y1 = SCHEDULE
    svg.text(x0 + 1, y0 + 3, "NOZZLE SCHEDULE", "t3")
    columns = (
        ("Mark", 0.0),
        ("Service", 12.0),
        ("DN", 58.0),
        ("Rating", 68.0),
        ("Face", 84.0),
        ("Orient.", 95.0),
        ("Elev. m", 108.0),
        ("Proj. m", 122.0),
        ("Line", 136.0),
    )
    y = y0 + 7.5
    for title, dx in columns:
        svg.text(x0 + 1 + dx, y, title, "t2")
    svg.line(x0, y + 1, x1, y + 1, "thin")
    rows = int((y1 - y - 6) // ROW)
    for index, nozzle in enumerate(nozzles):
        if index == rows - 1 and len(nozzles) > rows:
            svg.text(x0 + 1, y + ROW, f"... and {len(nozzles) - index} more", "t2")
            break
        y += ROW
        orient = "" if nozzle.orientation_deg is None else f"{nozzle.orientation_deg:g}°"
        if (nozzle.face or "") in ("top", "bottom"):
            orient = nozzle.face + (f" {orient}" if orient else "")
        values = (
            _mark(nozzle) + ("" if nozzle.name in placed else " †"),
            _short(nozzle.service or ", ".join(nozzle.lines), 26),
            text(nozzle.dn) if nozzle.dn is not None else "",
            _short(nozzle.rating, 9),
            _short(nozzle.facing, 6),
            orient,
            "" if nozzle.elevation_m is None else _g(nozzle.elevation_m),
            "" if nozzle.projection_m is None else _g(nozzle.projection_m),
            _short(", ".join(nozzle.lines), 22),
        )
        for (_, dx), value in zip(columns, values, strict=True):
            svg.text(x0 + 1 + dx, y, value or "-", "t2")
    svg.text(x0 + 1, y1 - 1, "† location not given: not on the drawing; * ASSUMED", "note")
    svg.rect(x0, y0, x1 - x0, y1 - y0, "thin")


def _entry_row(name: str, entry: Any, unit: str = "m") -> tuple[str, str, str] | None:
    if entry is None:
        return None
    if isinstance(entry, Material):
        value = entry.value + (f" ({entry.material_class})" if entry.material_class else "")
        return name, value + ("*" if entry.assumed else ""), entry.source or entry.reason
    value = text(entry)
    if not value:
        return None
    shown_unit = ""
    if hasattr(entry, "unit"):
        shown_unit = entry.unit
    elif isinstance(entry, int | float):
        shown_unit = unit
    star = "*" if assumed(entry) else ""
    source = getattr(entry, "source", "") or getattr(entry, "reason", "")
    return name, f"{value}{' ' + shown_unit if shown_unit else ''}{star}", source


def _table_rows(sheet: Datasheet) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str] | None] = []
    d = sheet.dimensions
    if d is not None:
        rows += [
            ("Orientation", d.orientation, "") if d.orientation else None,
            _entry_row("Housed in", d.housed_in, ""),
            _entry_row("Outside diameter", d.outside_diameter),
            _entry_row("Inside diameter", d.inside_diameter),
            _entry_row("Tangent to tangent", d.tangent_length),
            _entry_row("Head", d.head, ""),
            _entry_row("Overall height", d.overall_height),
            _entry_row("Overall length", d.overall_length),
            _entry_row("Overall width", d.overall_width),
        ]
        if d.support is not None:
            rows += [
                _entry_row("Support", d.support.type, ""),
                _entry_row("Support height", d.support.height),
                _entry_row("Supports", d.support.count, ""),
                _entry_row("Stands on", d.support.stands_on, ""),
                _entry_row("Base elevation", d.support.elevation),
            ]
        for section in d.sections:
            parts = [
                text(section.internals),
                f"{text(section.count)} trays" if section.count is not None else "",
                f"spacing {text(section.spacing)}" if section.spacing is not None else "",
                f"height {text(section.height)}" if section.height is not None else "",
            ]
            rows.append((f"Section {section.id}", ", ".join(p for p in parts if p), ""))
        rows.append(_entry_row("Shell passes", d.shell_passes, ""))
        if d.tubes is not None:
            rows += [
                _entry_row("Tubes", d.tubes.count, ""),
                _entry_row("Tube OD", d.tubes.outside_diameter),
                _entry_row("Tube length", d.tubes.length),
                _entry_row("Tube passes", d.tubes.passes, ""),
                _entry_row("Tube pitch", d.tubes.pitch),
            ]
        if d.plates is not None:
            rows += [
                _entry_row("Plates", d.plates.count, ""),
                _entry_row("Plate height", d.plates.height),
                _entry_row("Plate width", d.plates.width),
            ]
        if d.baseplate is not None:
            rows += [
                _entry_row("Baseplate length", d.baseplate.length),
                _entry_row("Baseplate width", d.baseplate.width),
            ]
        rows.append(_entry_row("Shaft height", d.shaft_height))
    if sheet.weights is not None:
        rows += [
            _entry_row("Weight empty", sheet.weights.empty, "t"),
            _entry_row("Weight operating", sheet.weights.operating, "t"),
            _entry_row("Weight test", sheet.weights.test, "t"),
        ]
    for part, entry in sheet.materials.items():
        rows.append(_entry_row(f"Material {part}", entry, ""))
    return [r for r in rows if r is not None]


def _table(svg: _Svg, sheet: Datasheet, shape: Outline, notes: list[str]) -> None:
    x0, y0, x1, y1 = TABLE
    svg.text(x0 + 1, y0 + 3, "MAIN DIMENSIONS, WEIGHTS, MATERIALS", "t3")
    rows = _table_rows(sheet)
    if shape.basis == "type_specific":
        rows = [
            (name, _len(length) + " m", "type_specific (older draft)")
            for name, length in (
                ("Diameter", shape.od),
                ("Height", shape.height),
                ("Length", shape.length),
                ("Width", shape.width),
            )
            if length is not None
        ] + rows
    room = int((y1 - y0 - 6 - ROW * (len(notes) + 1)) // ROW)
    y = y0 + 3
    for index, (name, value, source) in enumerate(rows):
        if index == room - 1 and len(rows) > room:
            y += ROW
            svg.text(x0 + 1, y, f"... and {len(rows) - index} more (see the datasheet)", "t2")
            break
        y += ROW
        svg.text(x0 + 1, y, _short(name, 22), "t2")
        svg.text(x0 + 38, y, _short(value, 34), "t2")
        svg.text(x0 + 100, y, _short(source, 62), "note")
    if not rows:
        y += ROW
        svg.text(x0 + 1, y, "no main dimensions given (dimensions: in the datasheet)", "t2")
    every = [
        *notes,
        "dimensions in m, weights in t; * ASSUMED; not to scale where no dimension is given",
    ]
    for index, note in enumerate(every):
        svg.text(
            x0 + 1, y1 - 1 - ROW * (len(every) - 1 - index), _short("NOTE: " + note, 130), "note"
        )
    svg.rect(x0, y0, x1 - x0, y1 - y0, "thin")


def _title(svg: _Svg, sheet: Datasheet, meta: dict[str, str], source: str) -> None:
    x0, y0, x1, y1 = TITLE
    svg.rect(x0, y0, x1 - x0, y1 - y0, "frame")
    svg.text(x0 + 3, y0 + 9, sheet.tag.strip(), "t7")
    svg.text(x0 + 3, y0 + 15, _short(sheet.service or "", 70), "t35")
    svg.text(x0 + 3, y0 + 20, _short(f"{sheet.type or ''} - OUTLINE DRAWING", 80), "t25")
    svg.line(x0, y0 + 23, x1, y0 + 23, "thin")
    rows = (
        ("Plant", meta.get("plant", "")),
        ("Project", meta.get("project", "")),
        ("Client / site", " / ".join(v for v in (meta.get("client"), meta.get("site")) if v)),
        ("Revision", meta.get("revision", "")),
        ("Datasheet", f"equipment/datasheets/{sheet.tag.strip()}.yaml"),
        ("Source", source),
    )
    y = y0 + 23
    for name, value in rows:
        y += 4.6
        svg.text(x0 + 3, y, name, "t25")
        svg.text(x0 + 30, y, _short(value, 82), "t25")
    status = "DRAFT (draft: true)" if sheet.draft else "datasheet final"
    svg.text(x1 - 3, y0 + 9, status, "t3" if not sheet.draft else "t35", "end")
    svg.text(x1 - 3, y1 - 1.5, f"generated by {GENERATOR}: do not edit", "note", "end")


def title_meta(config: Any) -> dict[str, str]:
    """The title block fields of a ``plant.yaml`` (a ``PlantConfig``, or None)."""
    if config is None:
        return {}
    meta = {"plant": str(getattr(config, "name", "") or "")}
    project = getattr(config, "project", None)
    if project is not None:
        meta.update(
            project=" ".join(v for v in (project.number, project.name) if v),
            client=project.client,
            site=project.site,
            revision=project.revision,
        )
    return meta


def render_outline(sheet: Datasheet, meta: dict[str, str] | None = None, source: str = "") -> str:
    """The outline drawing of *sheet* (see the module text). *meta*: the title block fields
    (:func:`title_meta`); *source*: the datasheet's fingerprint (``sha256:...``)."""
    meta = meta or {}
    svg = _Svg()
    svg.rect(10.0, 10.0, SHEET[0] - 20.0, SHEET[1] - 20.0, "frame")
    shape = outline(sheet)
    nozzles = list(sheet.nozzles)
    notes: list[str] = []
    placed: set[str] = set()
    svg.text(ELEVATION[0] + 1, ELEVATION[1] + 1, "ELEVATION", "t3")
    if shape.family == "vertical":
        v = _Vertical(shape)
        if v.drawable():
            located = [n for n in nozzles if _vertical_placeable(n)]
            placed = {n.name for n in located}
            notes += _vertical_elevation(svg, v, located)
            _vertical_plan(svg, v, located)
            svg.text(
                ELEVATION[0] + 1,
                ELEVATION[1] + 4.5,
                "seen from the south (site east to the right)",
                "note",
            )
        else:
            notes.append(
                "no dimensions.outside_diameter (or inside_diameter) with a tangent_length or "
                "overall_height: nothing drawn"
            )
    elif shape.family == "horizontal":
        h = _Horizontal(shape)
        if h.drawable():
            located = [n for n in nozzles if h.local(n) is not None]
            placed = {n.name for n in located}
            notes += _horizontal_elevation(svg, h, located)
            _horizontal_plan(svg, h, located)
            svg.text(
                ELEVATION[0] + 1, ELEVATION[1] + 4.5, "side view along the item's axis", "note"
            )
        else:
            notes.append(
                "no dimensions.outside_diameter (or inside_diameter) with a tangent_length or "
                "overall_length: nothing drawn"
            )
    else:
        located = [n for n in nozzles if n.axial_m is not None and n.elevation_m is not None]
        placed = {n.name for n in located}
        notes += _box_views(svg, shape, located)
    if shape.housed_in:
        empty = [n for n in notes if n.endswith(("nothing drawn", "no elevation drawn"))]
        notes = [n for n in notes if n not in empty]
        notes.insert(
            0,
            f"housed in {shape.housed_in}: no main dimensions of its own, not drawn"
            if empty
            else f"housed in {shape.housed_in}",
        )
    if shape.basis == "type_specific":
        notes.append(
            "main sizes from type_specific (an older draft): move them into dimensions: "
            "(cheme datasheets fill --dimensions)"
        )
    if any(n.projection_m is None for n in nozzles if n.name in placed):
        notes.append(f"nozzle stubs without projection_m drawn {STUB:g} m (schematic)")
    svg.flush_labels()
    _schedule(svg, nozzles, placed)
    _table(svg, sheet, shape, notes)
    _title(svg, sheet, meta, source)
    if sheet.draft:
        svg.text(210, 150, "DRAFT", "draft", "middle", -25)
    return svg.svg()


def weight_t(entry: Any) -> float | None:
    """A weight in t."""
    return number(entry, WEIGHT_UNITS)
