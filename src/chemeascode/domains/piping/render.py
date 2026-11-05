"""P&ID to SVG, through pyDEXPI's SVG export, and SVG to PNG through resvg.

Each drawn object's ``<g>`` carries the id of the object it represents, which is what the diff
viewer highlights by. The sheet's own drawings (title block, border), which represent no object,
are given the XML id of their DEXPI Label or Border object here, so they can be highlighted too.
The export passes the sheet's XML coordinates through unchanged: the SVG's user units are the
sheet's own millimetres, origin top left, Y pointing down -- there is no flip. A crop box is
given in those units, so positions read from the XML can be used directly.
"""

from __future__ import annotations

import contextlib
import copy
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

PNG_EXTRA_HINT = (
    "uv tool install 'cheme-as-code[png]' -- cheme-as-code is not on PyPI, so name the repository: "
    "uv tool install 'cheme-as-code[png] @ git+https://github.com/ChemE-as-Code/core.git'"
)

#: The largest PNG written, in pixels (width x height).
MAX_PNG_PIXELS = 100_000_000


class NothingToDraw(Exception):
    """The model has no diagram."""


class PngUnavailable(Exception):
    """resvg (the ``png`` extra) is not installed."""


class TooLarge(Exception):
    """The PNG would have more than :data:`MAX_PNG_PIXELS` pixels."""


@dataclass(frozen=True)
class Crop:
    """A sheet region in millimetres, Y down: ``x0,y0`` to ``x1,y1``."""

    x0: float
    y0: float
    x1: float
    y1: float

    @classmethod
    def parse(cls, text: str) -> Crop:
        """``"X0,Y0,X1,Y1"``; corners in any order. ``ValueError`` when it is not a box."""
        parts = [p.strip() for p in text.split(",")]
        if len(parts) != 4:
            raise ValueError(f"crop needs four numbers X0,Y0,X1,Y1, got {text!r}")
        try:
            x0, y0, x1, y1 = (float(p) for p in parts)
        except ValueError:
            raise ValueError(f"crop needs four numbers X0,Y0,X1,Y1, got {text!r}") from None
        if not all(math.isfinite(v) for v in (x0, y0, x1, y1)):
            raise ValueError(f"crop needs four finite numbers X0,Y0,X1,Y1, got {text!r}")
        box = cls(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        if box.width <= 0 or box.height <= 0:
            raise ValueError(f"crop box {text!r} has no area")
        return box

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0


def load_model(source: Path | bytes) -> Any:
    """Load a DEXPI XML document from a path or from bytes (strict)."""
    from chemeascode.domains.piping import dexpi_io

    content = source.read_bytes() if isinstance(source, Path) else source
    return dexpi_io.load(content, strict=True).model


#: The ids pyDEXPI's loader makes up for objects without an XML id (new on every load).
_GENERATED_ID = re.compile(r"id_[0-9a-f]{32}")


def name_sheet_drawings(svg: etree._Element, diagram: Any) -> etree._Element:
    """Give the ``<g>`` of each top-level Label or Border of *diagram* its object's XML id.

    pyDEXPI's export writes one ``<g>`` per diagram group, in order, but only a group that
    represents an object gets an id. The title block is a ``Core/Diagram.Label`` directly under
    the diagram, so without this it cannot be highlighted or picked. Groups are matched in
    document order and by class name; on any mismatch nothing is changed. Ids pyDEXPI made up
    (the XML had none) are not written.
    """
    from pydexpi.pydexpi_classes import RepresentationGroup, RepresentationTypeGroup

    content = next((g for g in svg.iter("{*}g", "g") if g.get("class") == "diagram"), None)
    if content is None:
        return svg
    drawn = [
        g for g in diagram.groups if isinstance(g, (RepresentationGroup, RepresentationTypeGroup))
    ]
    children = [c for c in content if isinstance(c.tag, str) and etree.QName(c).localname == "g"]
    if len(drawn) != len(children):
        return svg
    for group, element in zip(drawn, children, strict=True):
        if isinstance(group, RepresentationGroup):
            if element.get("id") != group.represents.id:
                return svg
            continue
        if element.get("class") != type(group).__name__.lower():
            return svg
        object_id = getattr(group, "id", None)
        if element.get("id") or not object_id or _GENERATED_ID.fullmatch(object_id):
            continue
        element.set("id", object_id)
    return svg


def svg_element(model: Any) -> etree._Element:
    """The model's first diagram as an SVG element."""
    from pydexpi.exports.svg_export import DrawDiagram

    if not model.diagram:
        raise NothingToDraw("the model has no diagram")
    diagram = model.diagram[0] if isinstance(model.diagram, list) else model.diagram
    svg = name_sheet_drawings(DrawDiagram(diagram).draw_svg(return_element=True), diagram)
    return sheet_background(svg, diagram)


def sheet_background(svg: etree._Element, diagram: Any) -> etree._Element:
    """Paint the backdrop in the sheet's own ``BackgroundColor`` (white paper) instead of
    pyDEXPI's neutral viewer grey, unless a filled shape on the sheet has that colour and would
    vanish against it (pyDEXPI's reason for the grey); then the grey stays."""
    color = getattr(diagram, "backgroundColor", None)
    backdrop = next((e for e in svg if isinstance(e.tag, str) and _local(e.tag) == "rect"), None)
    if color is None or backdrop is None or backdrop.get("fill") != "#f0f0f0":
        return svg
    paper = f"rgb({color.r},{color.g},{color.b})"
    fills = {e.get("fill", "").replace(" ", "") for e in svg.iter() if isinstance(e.tag, str)}
    hexed = f"#{color.r:02x}{color.g:02x}{color.b:02x}"
    if paper in fills or hexed in fills or (hexed == "#ffffff" and {"white", "#fff"} & fills):
        return svg
    backdrop.set("fill", hexed)
    return svg


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


#: How much :func:`emphasise_inline` enlarges inline symbols and actuators, and thickens their
#: strokes (a valve at the usual 0.4 is 4 x 2 mm drawn with 0.25 mm lines).
INLINE_EMPHASIS = 1.5
INLINE_STROKE = 2.0
_SCALE = re.compile(r"scale\(\s*([-+\d.eE]+)\s*(?:[,\s]\s*([-+\d.eE]+)\s*)?\)")


def inline_ids(model: Any) -> set[str]:
    """The ids of the model's inline items: piping components on segments (valves, fittings,
    reducers, silencers, ...) and the actuators and positioners of its actuating systems."""
    from pydexpi.pydexpi_classes import ControlledActuator, PipingComponent, Positioner

    found: set[str] = set()
    concept = model.conceptualModel
    if concept is None:
        return found
    for system in concept.pipingNetworkSystems or []:
        for segment in system.segments or []:
            for item in segment.items or []:
                if isinstance(item, PipingComponent) and item.id:
                    found.add(item.id)
    for system in concept.actuatingSystems or []:
        for part in (
            getattr(system, "controlledActuator", None),
            getattr(system, "positioner", None),
        ):
            if isinstance(part, (ControlledActuator, Positioner)) and part.id:
                found.add(part.id)
    return found


def emphasise_inline(
    svg: etree._Element,
    model: Any,
    factor: float = INLINE_EMPHASIS,
    stroke: float = INLINE_STROKE,
) -> etree._Element:
    """Draw inline items larger and bolder, for reading a full-sheet render.

    Each symbol of an item :func:`inline_ids` names is scaled by *factor* about its insertion
    point (the valve's centre, where an actuator also starts) and its strokes are *stroke* times
    as wide. Pipes, labels and the XML are unchanged: this is a review aid, not the drawing; the
    symbols may then overlap the pipe ends next to them.
    """
    ids = inline_ids(model)
    if not ids:
        return svg

    def bigger(match: re.Match[str]) -> str:
        sx = float(match.group(1))
        sy = float(match.group(2)) if match.group(2) is not None else sx
        return f"scale({sx * factor:.4g},{sy * factor:.4g})"

    for group in svg.iter("{*}g", "g"):
        if group.get("id") not in ids:
            continue
        for static in group:
            if not isinstance(static.tag, str) or static.get("class") != "static":
                continue
            for element in static.iter():
                if not isinstance(element.tag, str):
                    continue
                transform = element.get("transform")
                if transform and "scale(" in transform:
                    element.set("transform", _SCALE.sub(bigger, transform, count=1))
                width = element.get("stroke-width")
                if width:
                    with contextlib.suppress(ValueError):
                        element.set("stroke-width", f"{float(width) * stroke:g}")
    return svg


def crop_svg(svg: etree._Element, crop: Crop) -> etree._Element:
    """Limit *svg* to the sheet region *crop* (sets its viewBox, width and height)."""
    svg.set("viewBox", f"{crop.x0:g} {crop.y0:g} {crop.width:g} {crop.height:g}")
    svg.set("width", f"{crop.width:g}")
    svg.set("height", f"{crop.height:g}")
    return svg


def render_svg(model: Any, crop: Crop | None = None) -> str:
    """The model's first diagram as SVG text (limited to *crop*, when given)."""
    svg = svg_element(model)
    if crop is not None:
        crop_svg(svg, crop)
    return etree.tostring(svg, encoding="unicode")


def check_png_size(svg: str, scale: float) -> None:
    """Raise :class:`TooLarge` when *svg* at *scale* would exceed :data:`MAX_PNG_PIXELS`."""
    root = etree.fromstring(svg.encode("utf-8"))
    try:
        width, height = (
            float(root.get(a, "").removesuffix("mm") or 0) for a in ("width", "height")
        )
    except ValueError:  # pragma: no cover - a size in other units: resvg decides
        return
    if not (math.isfinite(width) and math.isfinite(height)):
        raise TooLarge(f"the SVG size {width} x {height} is not finite")
    pixels = width * height * scale * scale
    if pixels > MAX_PNG_PIXELS:
        raise TooLarge(
            f"the PNG would be {width * scale:.0f} x {height * scale:.0f} px, more than "
            f"{MAX_PNG_PIXELS // 1_000_000} Mpx; use a smaller --crop or --scale"
        )


def svg_to_png(svg: str, scale: float = 4.0) -> bytes:
    """*svg* rasterised by resvg, *scale* pixels per SVG unit (per sheet millimetre).

    :class:`TooLarge` when the image would exceed :data:`MAX_PNG_PIXELS`.
    """
    check_png_size(svg, scale)
    try:
        import resvg_py
    except ImportError as missing:
        raise PngUnavailable(
            f"PNG output needs resvg, which is not installed. Install the extra: {PNG_EXTRA_HINT}"
        ) from missing
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, zoom=scale, background="#ffffff"))


def _write(svg: etree._Element, output: Path, png: bool, scale: float) -> Path:
    text = etree.tostring(svg, encoding="unicode")
    output.parent.mkdir(parents=True, exist_ok=True)
    if png:
        output.write_bytes(svg_to_png(text, scale))
    else:
        output.write_text(text, encoding="utf-8", newline="")
    return output


def lint_findings(source: Path | bytes, model: Any) -> list[Any]:
    """The drawing-geometry findings of a sheet (``domains.piping.drawing``), for an overlay."""
    from chemeascode.domains.piping.drawing import lint_model

    content = source.read_bytes() if isinstance(source, Path) else source
    root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    return lint_model(model, root)[0]


@dataclass
class Mark:
    """One drawing finding as an overlay shows it: its number, id and acceptance."""

    number: int
    finding: Any
    #: Its validate id (``<sheet>#<rule>:<subject>``), as ``accept:`` entries name it.
    id: str
    #: The reason of the checks.yaml ``accept:`` entry that accepts it, if one does.
    accepted: str | None = None

    @property
    def caption(self) -> str:
        rule = self.finding.rule.removeprefix("cheme.")
        return f"{self.number} {rule}" + (" (accepted)" if self.accepted else "")

    def entry(self) -> dict[str, Any]:
        """Its entry in a tile index."""
        entry: dict[str, Any] = {"n": self.number, "rule": self.finding.rule, "id": self.id}
        if self.accepted:
            entry["accepted"] = self.accepted
        return entry


def finding_marks(found: list[Any], sheet: str, accept: list[Any] | None = None) -> list[Mark]:
    """Number *found* (drawing findings of *sheet*, its repository path) and apply *accept*.

    *accept*: checks/checks.yaml's ``accept:`` entries; the findings they accept stay marked,
    in grey and captioned ``(accepted)``, so the reviewer sees what was accepted and why.
    """
    from chemeascode.foundation.acceptance import acceptance
    from chemeascode.foundation.findings import Finding

    marks = []
    for number, item in enumerate(found, 1):
        finding = Finding(sheet, item.level, item.rule, item.message, ids=item.ids, key=item.key)
        entry = acceptance(accept or [], finding)
        marks.append(Mark(number, item, finding.id, entry.reason if entry else None))
    return marks


def _marked(svg: etree._Element, marks: list[Mark]) -> etree._Element:
    from chemeascode.domains.piping.drawing import overlay

    return overlay(
        svg, [(m.finding.box, m.caption, "grey" if m.accepted else "red") for m in marks]
    )


def render_file(
    path: Path | bytes,
    output: Path,
    *,
    png: bool = False,
    scale: float = 4.0,
    crop: Crop | None = None,
    findings: bool = False,
    sheet: str | None = None,
    accept: list[Any] | None = None,
    emphasise: bool = False,
) -> Path:
    """Render the P&ID at *path* (or its bytes) to *output*, as SVG or PNG.

    With *findings* the drawing-geometry findings are drawn on it as numbered red frames, those
    *accept* accepts in grey (*sheet*: the sheet's repository path, for the finding ids). With
    *emphasise* inline valves, fittings and actuators are drawn larger and bolder
    (:func:`emphasise_inline`).
    """
    model = load_model(path)
    svg = svg_element(model)
    if emphasise:
        emphasise_inline(svg, model)
    if findings:
        name = sheet or (path.name if isinstance(path, Path) else "")
        _marked(svg, finding_marks(lint_findings(path, model), name, accept))
    if crop is not None:
        crop_svg(svg, crop)
    return _write(svg, output, png, scale)


#: How much neighbouring tiles overlap, as a share of a tile.
TILE_OVERLAP = 0.1
_GRID = re.compile(r"^\s*(\d{1,2})\s*[xX]\s*(\d{1,2})\s*$")


def parse_grid(text: str, width: float, height: float, scale: float) -> tuple[int, int]:
    """``"4x3"`` -> (4 columns, 3 rows); ``"auto"``: tiles of at most 1600 x 1200 px.

    ``ValueError`` for anything else, or more than 26 rows or columns.
    """
    if text.strip().lower() == "auto":

        def count(length: float, pixels: float) -> int:
            tile = pixels / scale
            return max(1, math.ceil((length / tile - TILE_OVERLAP) / (1 - TILE_OVERLAP)))

        return min(count(width, 1600), 26), min(count(height, 1200), 26)
    match = _GRID.match(text)
    if not match:
        raise ValueError(f"tiles needs COLUMNSxROWS (e.g. 4x3) or auto, got {text!r}")
    columns, rows = int(match.group(1)), int(match.group(2))
    if not (1 <= columns <= 26 and 1 <= rows <= 26):
        raise ValueError(f"tiles needs 1 to 26 columns and rows, got {text!r}")
    return columns, rows


def tile_boxes(
    width: float,
    height: float,
    columns: int,
    rows: int,
    origin: tuple[float, float] = (0.0, 0.0),
) -> list[tuple[str, Crop]]:
    """The tiles of a *width* x *height* sheet whose top left corner is at *origin*, overlapping
    by :data:`TILE_OVERLAP`.

    Named by row letter and column number, ``A1`` top left, ``B3`` second row, third column.
    Corners are rounded to 0.01 mm, so the printed box reproduces the tile with ``--crop``.
    """

    def spans(start: float, length: float, count: int) -> list[tuple[float, float]]:
        size = length / (count - (count - 1) * TILE_OVERLAP)
        step = size * (1 - TILE_OVERLAP)
        return [
            (
                round(start + i * step, 2),
                round(start + (length if i == count - 1 else i * step + size), 2),
            )
            for i in range(count)
        ]

    return [
        (f"{chr(ord('A') + r)}{c + 1}", Crop(x0, y0, x1, y1))
        for r, (y0, y1) in enumerate(spans(origin[1], height, rows))
        for c, (x0, x1) in enumerate(spans(origin[0], width, columns))
    ]


def sheet_box(svg: etree._Element) -> Crop:
    """The region the SVG shows, in sheet mm (its viewBox). pyDEXPI grows the viewBox to cover
    everything drawn, so its origin is negative when something lies left of or above the sheet.
    """
    box = [float(v) for v in re.findall(r"[-+]?[\d.]+(?:[eE][-+]?\d+)?", svg.get("viewBox", ""))]
    if len(box) == 4:
        x, y, width, height = box
        return Crop(x, y, x + width, y + height)
    width = float(svg.get("width", "420") or 420)
    return Crop(0.0, 0.0, width, float(svg.get("height", "297") or 297))


@dataclass
class Tile:
    name: str
    crop: Crop
    file: Path
    #: The findings it shows, as numbered on the sheet.
    marks: list[Mark] = field(default_factory=list)

    @property
    def findings(self) -> list[str]:
        """Their captions, e.g. ``3 line-crossing (accepted)``."""
        return [m.caption for m in self.marks]


def render_tiles(
    path: Path | bytes,
    directory: Path,
    stem: str,
    grid: str,
    *,
    png: bool = False,
    scale: float = 8.0,
    findings: bool = False,
    sheet: str | None = None,
    accept: list[Any] | None = None,
    emphasise: bool = False,
) -> list[Tile]:
    """Render the sheet as overlapping tiles ``<stem>_tile-<RC>.svg|png`` in *directory*.

    ``ValueError`` for a malformed *grid*. With *findings* the drawing findings are marked on the
    tiles (those *accept* accepts in grey) and each tile lists those it shows. *emphasise*: as
    for :func:`render_file`.
    """
    model = load_model(path)
    svg = svg_element(model)
    if emphasise:
        emphasise_inline(svg, model)
    sheet_region = sheet_box(svg)
    width, height = sheet_region.width, sheet_region.height
    columns, rows = parse_grid(grid, width, height, scale)
    name = sheet or (path.name if isinstance(path, Path) else "")
    found = finding_marks(lint_findings(path, model), name, accept) if findings else []
    if found:
        _marked(svg, found)
    suffix = ".png" if png else ".svg"
    tiles = []
    for name, box in tile_boxes(width, height, columns, rows, (sheet_region.x0, sheet_region.y0)):
        tile = crop_svg(copy.deepcopy(svg), box)
        output = _write(tile, directory / f"{stem}_tile-{name}{suffix}", png, scale)
        shown = [
            m
            for m in found
            if (b := m.finding.box)[0] < box.x1
            and b[2] > box.x0
            and b[1] < box.y1
            and b[3] > box.y0
        ]
        tiles.append(Tile(name, box, output, shown))
    return tiles
