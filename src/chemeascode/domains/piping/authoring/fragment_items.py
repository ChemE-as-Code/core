"""``cheme fragment`` kinds for drafting a sheet: equipment, nozzle, instrument, signal,
offpage, line, note and shape.

Like the piping kinds (``chemeascode.domains.piping.authoring.fragment``), each prints a
CONCEPTUAL and a DRAWING part, each saying where it goes (and, with ``--sheet``, the holder's id
and line), plus a SHAPE part when the sheet's catalogue lacks the symbol. Ids derive from ``--id``:

- equipment ``ID``: nozzles ``ID_<name>`` with node ``ID_<name>_Node``; drawing ``ID_Drawing``
  with ``ID_Symbol``, ``ID_TagLabel``, nozzle drawings ``ID_<name>_Drawing`` holding
  ``ID_<name>_Node_Position`` (PipingNodePosition) or, for an instrument connection (a nozzle
  without DN), ``ID_<name>_Position`` (InstrumentationNodePosition);
- nozzle ``ID`` on existing equipment: node ``ID_Node``, drawing ``ID_Drawing``;
- instrument ``ID``: sensor ``ID_Sensor``, measuring line ``ID_MeasuringLine``; drawing
  ``ID_Drawing`` with the bubble, labels and node positions ``ID_Top``, ``ID_Bottom``,
  ``ID_Left``, ``ID_Right``;
- signal ``ID`` (a SignalLineFunction; with several targets ``ID_<target>``): towards a valve,
  ``ID_Actuating`` (ActuatingFunction in the source instrument) and, unless the valve has one,
  the actuating system ``<valve>_ActuatingSystem`` with ``<valve>_Actuator`` and
  ``<valve>_ValveReference``; drawing ``ID_Drawing`` (the dashed line);
- offpage ``ID`` with node ``ID_N``; drawing ``ID_Drawing``;
- line ``ID`` (a PipingNetworkSystem, for segment fragments to go into); drawing ``ID_Drawing``
  with the number label ``ID_Label``;
- note ``ID`` (a Static with ``ID_Text``), drawing only;
- shape: the catalogue's id, or ``--id``.

Offsets (``--nozzle N1:dx,dy``, ``nozzle --at dx,dy``) are from the equipment symbol's position
along the sheet axes (X right, Y down), not rotated with the symbol, and name a point on the
symbol's outline. A nozzle with a DN is drawn as a 4 mm stub outwards from it (along the axis
the offset points), and its pipes attach at the stub's end; one without a DN is an instrument
connection, its InstrumentationNodePosition on the outline.
"""

from __future__ import annotations

import copy as _copy
import difflib
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    boolean,
    color,
    comps,
    double,
    enum,
    extent,
    fmt_num,
    obj,
    parse_pair,
    parse_points,
    point,
    points,
    ref,
    rotate,
    string,
    to_text,
)
from chemeascode.domains.piping.authoring.builders import tag_label_spot
from chemeascode.domains.piping.authoring.fragment import (
    Fragment,
    FragmentError,
    Part,
    _SheetInfo,
    _standard,
    _symbol_at,
    _xy,
    dn_number,
    node_position,
    parse_scale,
    piping_node,
    point_xy_of,
    resolve_shape,
)
from chemeascode.domains.piping.show import data_value, short_class

PLANT = "Plant/PlantModel"
DIAGRAM = "Core/Diagram.Diagram"
NOZZLE_SHAPE = "NOZZLE_SHAPE"
ACTUATOR_SHAPE = "CONTROLLED_ACTUATOR_SHAPE"
BUBBLE_CENTRAL = "INSTRUMENTATION_BUBBLE_SHAPE_CENTRAL"
BUBBLE_FIELD = "INSTRUMENTATION_BUBBLE_SHAPE_FIELD"
#: Bubble node positions relative to its centre (the reference's, see the dexpi-xml skill).
BUBBLE_NODES = {
    "Top": (0.0, -3.75),
    "Bottom": (0.0, 3.75),
    "Left": (-6.75, 0.0),
    "Right": (6.75, 0.0),
}
MEASURING_RGB = (0, 128, 0)
SIGNAL_RGB = (0, 0, 0)  # as the authoring API draws signal lines
# How far from a bubble's centre its own connection points are (sheet mm).
BUBBLE_REACH = 10.0
#: The text size of an equipment tag label.
TAG_SIZE = 3.5
#: The actuator symbol's stem end (where the signal line attaches), at scale 1.
ACTUATOR_REACH = 18.0
ACTUATOR_SCALE = 0.4
#: Nozzle stub (NOZZLE_SHAPE at 0.8 x 0.4, as the reference draws the pump's nozzles).
NOZZLE_STUB = 4.0
OFFPAGE_SCALE = 0.7
FAIL_ACTIONS = {
    "FC": ("FailClose", "F.C."),
    "FO": ("FailOpen", "F.O."),
    "FL": ("FailRetainPosition", "F.L."),
}


# -- helpers ------------------------------------------------------------------------------------


def _pydexpi_class(name: str) -> type | None:
    from pydexpi.pydexpi_classes import pydexpi_classes

    found = getattr(pydexpi_classes, name, None)
    return found if isinstance(found, type) else None


def _dexpi_type(name: str, package: str, option: str) -> str:
    """``CentrifugalCompressor`` -> ``Plant/ProcessEquipment.CentrifugalCompressor``."""
    from pydexpi.toolkits.base_model_utils import get_dexpi_package_mapping

    mapping = get_dexpi_package_mapping()
    path = mapping.get(name)
    if path is None or not path.startswith(package + "."):
        candidates = [k for k, v in mapping.items() if v.startswith(package + ".")]
        close = difflib.get_close_matches(name, candidates, n=4, cutoff=0.5)
        if path is not None:
            kind = path.rsplit(".", 1)[0]
            hint = " (an inline fitting: fragment valve --class)" if ".Piping" in kind else ""
            raise FragmentError(f"{option} {name} is a {kind} class, not {package}{hint}")
        raise FragmentError(
            f"{option} {name}: no such DEXPI class"
            + (f"; did you mean {', '.join(close)}?" if close else "")
        )
    first, rest = path.split(".", 1)
    return f"{first}/{rest}"


def _is(element: etree._Element, base: str) -> bool:
    cls, wanted = _pydexpi_class(short_class(element)), _pydexpi_class(base)
    return bool(cls and wanted and issubclass(cls, wanted))


def _need_sheet(info: _SheetInfo | None, kind: str, why: str) -> _SheetInfo:
    if info is None:
        raise FragmentError(f"{kind} needs --sheet pid/<sheet>.xml ({why})")
    return info


def _get(info: _SheetInfo, object_id: str, option: str) -> etree._Element:
    element = info.sheet.by_id.get(object_id)
    if element is None:
        close = difflib.get_close_matches(object_id, list(info.sheet.by_id), n=3)
        raise FragmentError(
            f"{option} {object_id}: no object with this id in {info.path}"
            + (f"; did you mean {', '.join(close)}?" if close else "")
        )
    return element


def _where(
    info: _SheetInfo | None, kind: str, prop: str, fallback: str
) -> tuple[str, tuple | None]:
    if info is None:
        return f'into <Components property="{prop}"> of the {fallback}', None
    text, into = info.holder(kind, prop)
    return "into " + text, into


def _object_where(
    info: _SheetInfo, element: etree._Element, prop: str
) -> tuple[str, tuple[str, str]]:
    components = element.find(f"Components[@property='{prop}']")
    if components is None:
        text = (
            f'into <Components property="{prop}"> of {element.get("id")} '
            f"({info.sheet.line(element)}): create it, it has none yet"
        )
    else:
        text = (
            f'into <Components property="{prop}"> of {element.get("id")} '
            f"({info.sheet.line(components)})"
        )
    return text, (element.get("id"), prop)


def _drawing_where(
    info: _SheetInfo, object_id: str, what: str
) -> tuple[str, tuple[str, str] | None, etree._Element | None]:
    drawings = info.sheet.drawings.get(object_id, [])
    if not drawings:
        return (
            f'into <Components property="Groups"> of the RepresentationGroup that draws '
            f"{object_id} ({what} is not drawn in {info.path}: draw it first)",
            None,
            None,
        )
    drawing = drawings[0]
    return (
        f'into <Components property="Groups"> of {drawing.get("id")} '
        f"({info.sheet.where(drawing)}), the drawing of {object_id}",
        (drawing.get("id"), "Groups") if drawing.get("id") else None,
        drawing,
    )


def usage(
    usage_id: str,
    shape_id: str,
    x: float,
    y: float,
    rotation: float = 0.0,
    scale: tuple[float, float] = (1.0, 1.0),
    mirrored: bool = False,
) -> etree._Element:
    return obj(
        usage_id,
        "Core/Diagram.ShapeUsage",
        ref("Shape", shape_id),
        boolean("IsMirrored", mirrored),
        point("Position", x, y),
        double("Rotation", rotation % 360),
        double("ScaleX", scale[0]),
        double("ScaleY", scale[1]),
    )


def static(group_id: str, *elements: etree._Element) -> etree._Element:
    return obj(group_id, "Core/Diagram.Static", comps("Elements", *elements))


def text(
    text_id: str,
    x: float,
    y: float,
    value: str,
    size: float = 3.0,
    align: str = "CenterCenter",
    attributes: list[tuple[str, str]] | None = None,
) -> etree._Element:
    """A Text; with *attributes* ((object id, attribute name), ...) a template shows them."""
    children: list[etree._Element] = []
    if attributes:
        fragments = [
            obj(
                f"{text_id}_Fragment{i}" if len(attributes) > 1 else f"{text_id}_Fragment",
                "Core/Diagram.AttributeRepresentation",
                ref("Object", target),
                string("AttributeName", attribute),
                enum("Type", "Core/Diagram.AttributeRepresentationType.Value"),
            )
            for i, (target, attribute) in enumerate(attributes, 1)
        ]
        children.append(
            comps(
                "Template",
                obj(
                    f"{text_id}_Template",
                    "Core/Diagram.TextTemplate",
                    comps("Fragments", *fragments),
                ),
            )
        )
    return obj(
        text_id,
        "Core/Diagram.Text",
        *children,
        enum("Alignment", f"Core/Diagram.TextAlignment.{align}"),
        color("Color", 0, 0, 0),
        string("Font", "Calibri"),
        point("Position", x, y),
        double("Rotation", 0.0),
        double("Size", size),
        string("Text", value),
    )


def line_stroke(rgb: tuple[int, int, int], width: float, dash: str) -> etree._Element:
    from chemeascode.domains.piping.authoring.shapes import _stroke

    return _stroke(rgb, width, dash)


def connector(
    line_id: str,
    source: str,
    target: str,
    bends: list[tuple[float, float]],
    rgb: tuple[int, int, int],
    dash: str,
    width: float = 0.2,
) -> etree._Element:
    data = [ref("Source", source), ref("Target", target)]
    if bends:
        data.append(points("InnerPoints", bends))
    data.append(line_stroke(rgb, width, dash))
    return obj(line_id, "Core/Diagram.ConnectorLine", *data)


def instrumentation_position(position_id: str, x: float, y: float) -> etree._Element:
    return obj(position_id, "Plant/Diagram.InstrumentationNodePosition", point("Position", x, y))


def _offset(text: str, what: str) -> tuple[float, float]:
    return parse_pair(text, what)


DIRECTIONS = {"right": (1.0, 0.0), "left": (-1.0, 0.0), "down": (0.0, 1.0), "up": (0.0, -1.0)}


def _outward(dx: float, dy: float, half: tuple[float, float] | None = None) -> tuple[float, float]:
    """The sheet axis a nozzle at offset (dx, dy) from the centre points along.

    With *half* (the symbol's half width and height) the offset is compared relative to the
    symbol, so a side nozzle high on a tall column points sideways, not down the shell.
    """
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        raise FragmentError("a nozzle offset of 0,0 sits on the symbol's centre: give dx,dy")
    hx, hy = half if half and half[0] > 1e-9 and half[1] > 1e-9 else (1.0, 1.0)
    if abs(dx) / hx >= abs(dy) / hy:
        return (1.0 if dx > 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy > 0 else -1.0)


def _angle(direction: tuple[float, float]) -> float:
    return math.degrees(math.atan2(direction[1], direction[0])) % 360


def _shape_extent(shape_id: str, name: str, info: _SheetInfo | None):
    """The symbol's extent at scale 1 (points only), from the sheet or the template."""
    from chemeascode.domains.piping.authoring.shapes import catalogue

    element = info.sheet.by_id.get(shape_id) if info is not None else None
    if element is None:
        element = catalogue().get(name)
    found = extent(element) if element is not None else None
    return found or (-5.0, -5.0, 5.0, 5.0)


def _split_tag(tag: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"([A-Za-z]*)[-\s]?(\d+)(.*)", tag.strip())
    if not match:
        raise FragmentError(
            f"--tag {tag}: an equipment tag is PREFIX-NUMBER[SUFFIX], e.g. K-1101 or P-1101A"
        )
    return match.group(1), match.group(2), match.group(3)


def _nozzle_spec(
    spec: str,
) -> tuple[str, tuple[float, float], str | None, tuple[float, float] | None]:
    """``N1:-7.5,0:80`` -> (``N1``, (-7.5, 0), ``80``, None); no DN: an instrument connection.
    A fourth part names the stub's direction: ``N1:-10,40:80:left`` (``N1:-10,40::left``)."""
    parts = spec.split(":")
    if len(parts) not in (2, 3, 4) or not parts[0]:
        raise FragmentError(
            f"--nozzle {spec}: expected NAME:dx,dy[:DN[:DIRECTION]] (e.g. N1:-7.5,0:80; no DN "
            "for an instrument connection; DIRECTION left, right, up or down)"
        )
    direction = None
    if len(parts) == 4:
        direction = DIRECTIONS.get(parts[3].strip().lower())
        if direction is None:
            raise FragmentError(
                f"--nozzle {spec}: direction {parts[3]!r} is not one of {', '.join(DIRECTIONS)}"
            )
    name = parts[0].strip()
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise FragmentError(f"--nozzle {spec}: the name {name!r} must be letters and digits")
    offset = _offset(parts[1], f"--nozzle {name}")
    dn = dn_number(parts[2]) if len(parts) >= 3 and parts[2].strip() else None
    return name, offset, dn, direction


def _nozzle_parts(
    nozzle_id: str,
    sub_tag: str,
    wall_at: tuple[float, float],
    outward: tuple[float, float],
    dn: str | None,
    standard: str,
    nozzle_shape: str,
    notes: list[str],
) -> tuple[etree._Element, etree._Element, tuple[float, float]]:
    """A ProcessNozzle, its drawing and where pipes attach.

    *wall_at* is on the symbol's outline. A nozzle with a DN gets a stub (NOZZLE_SHAPE) from
    there outwards, its node position at the stub's end; an instrument connection (no DN) an
    InstrumentationNodePosition on the outline.
    """
    x, y = wall_at
    if dn is None:
        nozzle = obj(
            nozzle_id, "Plant/ProcessEquipment.ProcessNozzle", string("SubTagName", sub_tag)
        )
        drawing = obj(
            f"{nozzle_id}_Drawing",
            "Core/Diagram.RepresentationGroup",
            comps("NodePositions", instrumentation_position(f"{nozzle_id}_Position", x, y)),
            ref("Represents", nozzle_id),
        )
        return nozzle, drawing, (x, y)
    node_id = f"{nozzle_id}_Node"
    nozzle = obj(
        nozzle_id,
        "Plant/ProcessEquipment.ProcessNozzle",
        comps("Nodes", piping_node(node_id, dn, _standard(dn, standard, notes))),
        string("SubTagName", sub_tag),
    )
    stub_at = (x, y)
    x, y = x + NOZZLE_STUB * outward[0], y + NOZZLE_STUB * outward[1]
    drawing = obj(
        f"{nozzle_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            node_position(node_id, x, y),
            static(
                f"{nozzle_id}_Symbol",
                usage(
                    f"{nozzle_id}_SymbolShape", nozzle_shape, *stub_at, _angle(outward), (0.8, 0.4)
                ),
            ),
        ),
        ref("Represents", nozzle_id),
    )
    return nozzle, drawing, (x, y)


# -- equipment ----------------------------------------------------------------------------------


def _marker_spec(spec: str) -> tuple[str, float, float, bool]:
    """``COLUMN_PACKED_BED_SHAPE:-20:1.5`` -> (name, dy, ScaleY, mirrored); ``:m`` mirrors."""
    fields = [f.strip() for f in spec.split(":")]
    mirrored = len(fields) > 2 and fields[-1].lower() in ("m", "mirror", "mirrored")
    if mirrored:
        fields = fields[:-1]
    if len(fields) not in (2, 3) or not fields[0]:
        raise FragmentError(
            f"--marker {spec}: expected NAME:dy[:SY][:m] (e.g. COLUMN_PACKED_BED_SHAPE:-20:1.5, "
            "COLUMN_TRAY_SHAPE:10:1:m)"
        )
    try:
        dy = float(fields[1])
        sy = float(fields[2]) if len(fields) == 3 else 1.0
    except ValueError as failure:
        raise FragmentError(f"--marker {spec}: dy and SY are numbers") from failure
    if sy <= 0:
        raise FragmentError(f"--marker {spec}: SY must be positive")
    return fields[0], dy, sy, mirrored


def _equipment(
    object_id: str,
    info: _SheetInfo | None,
    *,
    item_class: str | None,
    tag: str | None,
    shape: str | None,
    at: str | None,
    rotation: float,
    scale: str | None,
    nozzles: list[str] | None,
    label_at: str | None,
    standard: str,
    markers: list[str] | None = None,
    **_: object,
) -> Fragment:
    from chemeascode.domains.piping.authoring.shapes import EQUIPMENT_SHAPES, normalise_name

    if not item_class:
        raise FragmentError("equipment needs --class CLASS (e.g. CentrifugalCompressor, Tank)")
    if not tag:
        raise FragmentError("equipment needs --tag TAG (e.g. K-1101)")
    kind = _dexpi_type(item_class, "Plant.ProcessEquipment", "--class")
    if at is None:
        raise FragmentError("--at X,Y is required (the symbol's centre, sheet mm, Y down)")
    x, y = parse_pair(at, "--at")
    if shape:
        name = normalise_name(shape)
    elif item_class in EQUIPMENT_SHAPES:
        name = EQUIPMENT_SHAPES[item_class]
    else:
        raise FragmentError(
            f"no default symbol for {item_class}: pass --shape NAME (the dexpi-xml skill's "
            "shapes.md lists them)"
        )
    sx, sy = parse_scale(scale) if scale else (1.0, 1.0)
    prefix, sequence, suffix = _split_tag(tag)
    made = Fragment(
        "equipment", object_id, f"{item_class} {tag} ({name}) at {fmt_num(x)},{fmt_num(y)}"
    )
    shapes: list[Part] = []
    shape_id = resolve_shape(name, info, shapes)
    nozzle_shape = None
    nozzle_objects, nozzle_drawings, placed = [], [], []
    x0, y0, x1, y1 = _shape_extent(shape_id, name, info)
    corners = [rotate(cx * sx, cy * sy, rotation) for cx in (x0, x1) for cy in (y0, y1)]
    half = (max(abs(c[0]) for c in corners), max(abs(c[1]) for c in corners))
    pipes_out = []
    for spec in nozzles or []:
        nozzle_name, (dx, dy), dn, direction = _nozzle_spec(spec)
        nozzle_id = f"{object_id}_{nozzle_name}"
        if dn is not None and nozzle_shape is None:
            nozzle_shape = resolve_shape(NOZZLE_SHAPE, info, shapes)
        direction = direction or _outward(dx, dy, half)
        pipes_out.append(((dx, dy), direction))
        nozzle, drawing, attach = _nozzle_parts(
            nozzle_id,
            nozzle_name,
            (x + dx, y + dy),
            direction,
            dn,
            standard,
            nozzle_shape or "",
            made.notes,
        )
        nozzle_objects.append(nozzle)
        nozzle_drawings.append(drawing)
        position = f"{nozzle_id}_Node_Position" if dn else f"{nozzle_id}_Position"
        placed.append(
            f"{nozzle_name} {'DN ' + dn if dn else '(instrument connection)'} at "
            f"{_xy(attach)} -> #{position}"
        )
    if len({p.split()[0] for p in placed}) != len(placed):
        raise FragmentError("--nozzle: two nozzles have the same name")
    marker_usages = []
    for number_, spec in enumerate(markers or [], 1):
        marker_name, dy, marker_sy, mirrored = _marker_spec(spec)
        marker_shape = resolve_shape(normalise_name(marker_name), info, shapes)
        mdx, mdy = rotate(0.0, dy, rotation)
        marker_usages.append(
            usage(
                f"{object_id}_Marker{number_}",
                marker_shape,
                x + mdx,
                y + mdy,
                rotation,
                (sx, marker_sy),
                mirrored,
            )
        )
    data = [string("TagName", tag)]
    if prefix:
        data.append(string("TagNamePrefix", prefix))
    data.append(string("TagNameSequenceNumber", sequence))
    if suffix:
        data.append(string("TagNameSuffix", suffix))
    children = [comps("Nozzles", *nozzle_objects)] if nozzle_objects else []
    equipment = obj(object_id, kind, *children, *data)
    if label_at:
        lx, ly = parse_pair(label_at, "--label-at")
    else:
        box = (
            min(c[0] for c in corners),
            min(c[1] for c in corners),
            max(c[0] for c in corners),
            max(c[1] for c in corners),
        )
        (lx, ly), clear = tag_label_spot((x, y), box, pipes_out, tag, TAG_SIZE, 5.0)
        where = "clear of the nozzles" if clear else "below the symbol, crossed by a nozzle's pipe"
        made.notes.append(
            f"tag label {fmt_num(lx)},{fmt_num(ly)} ({where}): move it with --label-at"
        )
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            static(
                f"{object_id}_Symbol",
                usage(f"{object_id}_SymbolShape", shape_id, x, y, rotation, (sx, sy)),
                *marker_usages,
            ),
            obj(
                f"{object_id}_TagLabel",
                "Plant/Diagram.EquipmentTagNameLabel",
                comps(
                    "Elements",
                    text(
                        f"{object_id}_TagText",
                        lx,
                        ly,
                        tag,
                        TAG_SIZE,
                        attributes=[(object_id, "TagName")],
                    ),
                ),
            ),
            *nozzle_drawings,
        ),
        ref("Represents", object_id),
    )
    where, into = _where(info, PLANT, "TaggedPlantItems", "PlantModel")
    made.parts.append(Part("CONCEPTUAL", where, to_text(equipment), into))
    where, into = _where(info, DIAGRAM, "Groups", "Diagram (the sheet's drawing)")
    made.parts.append(
        Part(
            "DRAWING",
            where + ". Nozzles: " + ("; ".join(placed) if placed else "none (add with --nozzle)"),
            to_text(drawing),
            into,
        )
    )
    made.parts += shapes
    if not placed:
        made.notes.append("no --nozzle given: pipes need nozzles (fragment nozzle adds one later)")
    return made


# -- nozzle -------------------------------------------------------------------------------------


def _nozzle(
    object_id: str,
    info: _SheetInfo | None,
    *,
    on: str | None,
    at: str | None,
    dn: str | None,
    tag: str | None,
    standard: str,
    **_: object,
) -> Fragment:
    info = _need_sheet(info, "nozzle", "the equipment's position and drawing come from it")
    if not on:
        raise FragmentError("nozzle needs --on EQUIPMENT (the id of the equipment it belongs to)")
    if at is None:
        raise FragmentError("nozzle needs --at dx,dy (offset from the equipment symbol's centre)")
    equipment = _get(info, on, "--on")
    if not _is(equipment, "NozzleOwner"):
        raise FragmentError(f"--on {on} is a {short_class(equipment)}, which has no nozzles")
    dx, dy = _offset(at, "--at")
    size = dn_number(dn) if dn else None
    drawing_where, drawing_into, drawing = _drawing_where(info, on, short_class(equipment))
    centre = _symbol_at(drawing) if drawing is not None else None
    if centre is None:
        raise FragmentError(f"{on} has no drawn symbol in {info.path}: cannot place a nozzle on it")
    existing = [
        data_value(n, "SubTagName") or ""
        for n in equipment.findall("Components[@property='Nozzles']/Object")
    ]
    if tag:
        sub_tag = tag
        made_note = f"{on} has a nozzle {tag} already" if tag in existing else None
    else:
        numbers = [int(m.group(1)) for t in existing for m in [re.fullmatch(r"N(\d+)", t)] if m]
        sub_tag = f"N{max(numbers, default=0) + 1}"
        made_note = None
    x, y = centre[0] + dx, centre[1] + dy
    made = Fragment(
        "nozzle",
        object_id,
        f"nozzle {sub_tag} {'DN ' + size if size else '(instrument connection)'} on {on} at "
        f"{fmt_num(x)},{fmt_num(y)}",
    )
    if made_note:
        made.notes.append(made_note)
    shapes: list[Part] = []
    nozzle_shape = resolve_shape(NOZZLE_SHAPE, info, shapes) if size else ""
    box = _symbol_box(info, on)
    half = (
        (max(centre[0] - box[0], box[2] - centre[0]), max(centre[1] - box[1], box[3] - centre[1]))
        if box
        else None
    )
    nozzle, nozzle_drawing, attach = _nozzle_parts(
        object_id, sub_tag, (x, y), _outward(dx, dy, half), size, standard, nozzle_shape, made.notes
    )
    where, into = _object_where(info, equipment, "Nozzles")
    position = f"{object_id}_Node_Position" if size else f"{object_id}_Position"
    made.parts.append(Part("CONCEPTUAL", where, to_text(nozzle), into))
    made.parts.append(
        Part(
            "DRAWING",
            drawing_where + f". Pipes (or a measuring line) attach at #{position} ({_xy(attach)})",
            to_text(nozzle_drawing),
            drawing_into,
        )
    )
    made.parts += shapes
    return made


# -- instrument ---------------------------------------------------------------------------------


def _instrument_tag(tag: str) -> tuple[str, str, str]:
    match = re.fullmatch(r"([A-Za-z]+)[-\s]?(\S*\d\S*)", tag.strip())
    if not match:
        raise FragmentError(f"--tag {tag}: an instrument tag is LETTERS-NUMBER, e.g. PIC-4101")
    letters, number = match.group(1).upper(), match.group(2)
    return letters[0], letters[1:], number


def _positions_in(drawing: etree._Element, direct: bool = False) -> list[etree._Element]:
    if direct:
        holder = drawing.find("Components[@property='NodePositions']")
        found = list(holder) if holder is not None else []
    else:
        found = list(drawing.iter("Object"))
    return [
        p
        for p in found
        if isinstance(p.tag, str)
        and p.get("type") == "Plant/Diagram.InstrumentationNodePosition"
        and p.get("id")
    ]


def _nearest(
    candidates: list[tuple[str, tuple[float, float]]], to: tuple[float, float]
) -> tuple[str, tuple[float, float]]:
    return min(candidates, key=lambda c: (c[1][0] - to[0]) ** 2 + (c[1][1] - to[1]) ** 2)


Box = tuple[float, float, float, float]
#: Half width and height of an instrument bubble's box (to its Left/Right and Top/Bottom nodes).
BUBBLE_HALF = (6.75, 3.75)
#: Where the letters and the number of a bubble go (dy from its centre, 3 mm text, centred on
#: the middle of the lower-case letters). The central bubble keeps the reference's places, on
#: either side of its middle line; the field bubble has none, so its two lines are centred in
#: it: at the reference's -2.25 the capitals touch the field bubble's top (D15).
BUBBLE_TEXT_CENTRAL = (-2.25, 1.2)
BUBBLE_TEXT_FIELD = (-1.5, 2.0)
#: How far a routed line runs straight out of a node before it turns, when it has to.
ROUTE_STUB = 3.0
_EPS = 1e-6


def _bubble_box(centre: tuple[float, float]) -> Box:
    return (
        centre[0] - BUBBLE_HALF[0],
        centre[1] - BUBBLE_HALF[1],
        centre[0] + BUBBLE_HALF[0],
        centre[1] + BUBBLE_HALF[1],
    )


def _segment_enters(a: tuple[float, float], b: tuple[float, float], box: Box) -> bool:
    """Whether segment a-b runs through the inside of *box* (touching its edge does not)."""
    x0, y0, x1, y1 = box[0] + 1e-3, box[1] + 1e-3, box[2] - 1e-3, box[3] - 1e-3
    if x0 >= x1 or y0 >= y1:
        return False
    low, high = 0.0, 1.0
    dx, dy = b[0] - a[0], b[1] - a[1]
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if abs(p) < _EPS:
            if q <= 0:
                return False
            continue
        t = q / p
        if p < 0:
            low = max(low, t)
        else:
            high = min(high, t)
        if low >= high:
            return False
    return (high - low) * math.hypot(dx, dy) > 1e-3


def _direction(a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(b[0] - a[0], b[1] - a[1])
    return (0.0, 0.0) if length < _EPS else ((b[0] - a[0]) / length, (b[1] - a[1]) / length)


def _simplify(path: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Drops repeated points and points on a straight run."""
    out: list[tuple[float, float]] = []
    for point_ in path:
        if out and math.hypot(point_[0] - out[-1][0], point_[1] - out[-1][1]) < _EPS:
            continue
        if len(out) >= 2:
            d1, d2 = _direction(out[-2], out[-1]), _direction(out[-1], point_)
            if abs(d1[0] * d2[1] - d1[1] * d2[0]) < _EPS and d1[0] * d2[0] + d1[1] * d2[1] > 0:
                out[-1] = point_
                continue
        out.append(point_)
    return out


def _routes(
    start: tuple[float, float],
    out: tuple[float, float] | None,
    end: tuple[float, float],
    end_out: tuple[float, float] | None,
    channels: tuple[list[float], list[float]] = ([], []),
) -> list[list[tuple[float, float]]]:
    """Orthogonal candidate paths (start and end included): one bend either way, and with a
    straight stub out of the start node (and into the end node) before turning; with
    *channels* (x and y values clear of the obstacles) also two bends, the middle run along
    one of them, to go round what lies between."""
    heads = [start]
    if out is not None:
        heads.append((start[0] + ROUTE_STUB * out[0], start[1] + ROUTE_STUB * out[1]))
    tails = [end]
    if end_out is not None:
        tails.append((end[0] + ROUTE_STUB * end_out[0], end[1] + ROUTE_STUB * end_out[1]))
    found = []
    for head in heads:
        for tail in tails:
            for corner in ((tail[0], head[1]), (head[0], tail[1])):
                path = [start, head, corner, tail, end]
                found.append(_simplify(path))
            for y in channels[1]:
                found.append(_simplify([start, head, (head[0], y), (tail[0], y), tail, end]))
            for x in channels[0]:
                found.append(_simplify([start, head, (x, head[1]), (x, tail[1]), tail, end]))
    return found


#: How far a detour runs clear of what it goes round (mm), and how far beyond the two ends'
#: box the router looks for one.
CHANNEL_GAP = 3.0
CHANNEL_REACH = 40.0


def _channels(
    points: list[tuple[float, float]], boxes: list[Box]
) -> tuple[list[float], list[float]]:
    """x and y values just outside the *boxes* near *points* (the line's possible ends)."""
    x0 = min(p[0] for p in points) - CHANNEL_REACH
    x1 = max(p[0] for p in points) + CHANNEL_REACH
    y0 = min(p[1] for p in points) - CHANNEL_REACH
    y1 = max(p[1] for p in points) + CHANNEL_REACH
    xs: set[float] = set()
    ys: set[float] = set()
    for box in boxes:
        if box[2] < x0 or box[0] > x1 or box[3] < y0 or box[1] > y1:
            continue
        xs.update((round(box[0] - CHANNEL_GAP, 3), round(box[2] + CHANNEL_GAP, 3)))
        ys.update((round(box[1] - CHANNEL_GAP, 3), round(box[3] + CHANNEL_GAP, 3)))
    return sorted(xs), sorted(ys)


#: Route costs (mm of line): through a symbol, through a text, across a pipe.
SYMBOL_COST = 1000.0
TEXT_COST = 300.0
CROSSING_COST = 60.0


@dataclass
class SheetObstacles:
    """What a new signal or measuring line should keep clear of, read from the drawn sheet:
    instrument bubbles and equipment bodies, the texts, and the pipes (crossing one is a
    ``cheme.line-crossing``)."""

    symbols: list[Box] = field(default_factory=list)
    texts: list[Box] = field(default_factory=list)
    pipes: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)

    def cost(self, a: tuple[float, float], b: tuple[float, float]) -> float:
        from chemeascode.domains.piping.drawing import _cross

        return (
            SYMBOL_COST * sum(_segment_enters(a, b, box) for box in self.symbols)
            + TEXT_COST * sum(_segment_enters(a, b, box) for box in self.texts)
            + CROSSING_COST * sum(_cross(a, b, c, d) is not None for c, d in self.pipes)
        )


def sheet_obstacles(info: _SheetInfo | None) -> SheetObstacles:
    """The obstacles of *info*'s sheet as ``cheme render`` draws it (none when it does not
    render), so that the router's lines come out clean for the drawing lint
    (pre-release issue 44)."""
    found = SheetObstacles()
    if info is None or not Path(info.path).is_file():
        return found
    try:
        from chemeascode.domains.piping.drawing import (
            context_from_xml,
            equipment_bodies,
            read_drawing,
        )
        from chemeascode.domains.piping.render import load_model, svg_element

        context = context_from_xml(info.sheet.root)
        drawing = read_drawing(svg_element(load_model(Path(info.path))), context.kinds)
    except Exception:  # noqa: BLE001 - a sheet that does not render: route as before
        return found
    bubbles: dict[str, list[tuple[float, float]]] = {}
    for stroke in drawing.strokes:
        if stroke.kind == "process":
            found.pipes += list(stroke.segments())
        elif stroke.kind == "symbol":
            owner = next((o for o in stroke.owners if context.category(o) == "instrument"), None)
            if owner is not None:
                bubbles.setdefault(owner, []).extend(stroke.points)
    found.symbols += [_bounds(points) for points in bubbles.values()]
    for strokes in equipment_bodies(drawing, context).values():
        found.symbols.append(_bounds([p for stroke in strokes for p in stroke.points]))
    found.texts += [label.box for label in drawing.labels]
    return found


def _bounds(points: list[tuple[float, float]]) -> Box:
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _best_route(
    starts: list[tuple[str, tuple[float, float], tuple[float, float] | None]],
    ends: list[tuple[str, tuple[float, float], tuple[float, float] | None]],
    obstacles: list[Box],
    sheet: SheetObstacles | None = None,
) -> tuple[tuple[str, tuple[float, float]], tuple[str, tuple[float, float]], list]:
    """The start node, end node and bends of the shortest orthogonal line that leaves its start
    node outwards (along the node's direction), enters its end node from outside, crosses none
    of the *obstacles* (the bubbles and the equipment it starts at) and, with *sheet*, as few
    of the sheet's symbols, texts and pipes as it can. A node's direction is the way a line
    leaves it (for an end node: the way the line comes in, reversed); None: any."""
    best = None
    channels: tuple[list[float], list[float]] = ([], [])
    if sheet is not None:
        channels = _channels(
            [xy for _, xy, _ in starts] + [xy for _, xy, _ in ends],
            obstacles + sheet.symbols + sheet.texts,
        )
    for start_id, start_xy, out in starts:
        for end_id, end_xy, end_out in ends:
            for path in _routes(start_xy, out, end_xy, end_out, channels):
                if len(path) < 2:
                    continue
                cost = sum(
                    math.hypot(b[0] - a[0], b[1] - a[1])
                    for a, b in zip(path, path[1:], strict=False)
                )
                cost += 2.0 * (len(path) - 2)
                first, last = _direction(path[0], path[1]), _direction(path[-2], path[-1])
                if out is not None and first[0] * out[0] + first[1] * out[1] <= _EPS:
                    cost += 1000.0
                if end_out is not None and last[0] * end_out[0] + last[1] * end_out[1] >= -_EPS:
                    cost += 1000.0
                for a, b in zip(path, path[1:], strict=False):
                    cost += SYMBOL_COST * sum(_segment_enters(a, b, box) for box in obstacles)
                    if sheet is not None:
                        cost += sheet.cost(a, b)
                if best is None or cost < best[0] - _EPS:
                    best = (cost, (start_id, start_xy), (end_id, end_xy), path[1:-1])
    assert best is not None
    return best[1], best[2], best[3]


def _clear_of(sheet: SheetObstacles, ends: list[tuple[float, float] | None]) -> SheetObstacles:
    """*sheet* without the symbols and texts at the line's own *ends* (its bubbles, the
    valve's actuator and tag): the line starts and ends there."""

    def at_end(box: Box) -> bool:
        return any(
            e is not None and box[0] - 1 <= e[0] <= box[2] + 1 and box[1] - 1 <= e[1] <= box[3] + 1
            for e in ends
        )

    return SheetObstacles(
        [b for b in sheet.symbols if not at_end(b)],
        [b for b in sheet.texts if not at_end(b)],
        sheet.pipes,
    )


def _measuring_obstacles(info: _SheetInfo | None, own: Box | None) -> SheetObstacles:
    """The sheet's obstacles for a measuring line: its own equipment (already an obstacle) and
    the pipe it taps left out of the crossings count."""
    sheet = sheet_obstacles(info)
    return SheetObstacles(
        [b for b in sheet.symbols if own is None or b != own], sheet.texts, sheet.pipes
    )


def _bubble_out(name: str) -> tuple[float, float]:
    dx, dy = BUBBLE_NODES[name]
    return _outward(dx, dy)


def _node_out(node_id: str, xy: tuple[float, float], centre: tuple[float, float] | None):
    """The direction a bubble node faces (from its id's suffix, else from the centre)."""
    for name in BUBBLE_NODES:
        if node_id.lower().endswith("_" + name.lower()):
            return _bubble_out(name)
    if centre is not None and math.hypot(xy[0] - centre[0], xy[1] - centre[1]) > _EPS:
        return _outward(xy[0] - centre[0], xy[1] - centre[1])
    return None


def _bubble_centre(info: _SheetInfo, element_id: str) -> tuple[float, float] | None:
    for drawing in info.sheet.drawings.get(element_id, []):
        found = _symbol_at(drawing)
        if found:
            return found
    return None


def _symbol_box(info: _SheetInfo, element_id: str) -> Box | None:
    """The sheet box of the main symbol drawing *element_id* (scaled and rotated)."""
    for drawing in info.sheet.drawings.get(element_id, []):
        for element in drawing.iter("Object"):
            if element.get("type") != "Core/Diagram.ShapeUsage":
                continue
            shape = element.find("References[@property='Shape']")
            shape_id = (shape.get("objects") or "").lstrip("#") if shape is not None else ""
            shape_element = info.sheet.by_id.get(shape_id)
            name = (
                shape_element.findtext("Data[@property='Name']/String") or ""
                if shape_element is not None
                else ""
            )
            (x, y), rotation, sx = _usage_geometry(element)
            sy = float(element.findtext("Data[@property='ScaleY']/Double") or sx)
            x0, y0, x1, y1 = _shape_extent(shape_id, name, info)
            corners = [rotate(cx * sx, cy * sy, rotation) for cx in (x0, x1) for cy in (y0, y1)]
            xs, ys = [x + c[0] for c in corners], [y + c[1] for c in corners]
            return min(xs), min(ys), max(xs), max(ys)
    return None


def _duplicate_signal(info: _SheetInfo, source: str, target_id: str, system_id: str | None):
    """The id of a signal line from *source* to *target_id* (or its actuating system), if any."""
    for element in info.sheet.root.iter("Object"):
        if element.get("type") != "Plant/Instrumentation.SignalLineFunction":
            continue
        source_ref = element.find("References[@property='Source']")
        target_ref = element.find("References[@property='Target']")
        if source_ref is None or target_ref is None:
            continue
        if source_ref.get("objects", "").lstrip("#") != source:
            continue
        to = target_ref.get("objects", "").lstrip("#")
        if to == target_id:
            return element.get("id") or "(no id)"
        reached = info.sheet.by_id.get(to)
        if system_id and reached is not None:
            systems = reached.find("References[@property='Systems']")
            if systems is not None and f"#{system_id}" in (systems.get("objects") or "").split():
                return element.get("id") or "(no id)"
    return None


def _equipment_of(info: _SheetInfo, item_id: str) -> str | None:
    """The equipment a nozzle belongs to (None for anything else)."""
    element = info.sheet.by_id.get(item_id)
    if element is None or not _is(element, "Nozzle"):
        return None
    for ancestor in element.iterancestors("Object"):
        if ancestor.get("id") and info.sheet.drawings.get(ancestor.get("id")):
            return ancestor.get("id")
    return None


def _instrument(
    object_id: str,
    info: _SheetInfo | None,
    *,
    tag: str | None,
    at: str | None,
    sense: str | None,
    field: bool = False,
    points: str | None,
    **_: object,
) -> Fragment:
    if not tag:
        raise FragmentError("instrument needs --tag LETTERS-NUMBER (e.g. PIC-4101)")
    if at is None:
        raise FragmentError("instrument needs --at X,Y (the bubble's centre)")
    if not sense:
        raise FragmentError(
            "instrument needs --sense ITEM[:x,y]: the nozzle, segment or inline item it "
            "measures, and optionally where its measuring line starts"
        )
    category, functions, number = _instrument_tag(tag)
    x, y = parse_pair(at, "--at")
    item, _, sense_at = sense.partition(":")
    item = item.strip()
    made = Fragment(
        "instrument",
        object_id,
        f"{category}{functions}-{number} ({'field' if field else 'central'}) at "
        f"{fmt_num(x)},{fmt_num(y)}, sensing {item}",
    )
    sense_position: str
    sense_xy: tuple[float, float] | None = None
    own_sense = None
    if info is not None:
        element = _get(info, item, "--sense")
        if not _is(element, "SensingLocation"):
            raise FragmentError(
                f"--sense {item} is a {short_class(element)}, not a sensing location: use one of "
                "its nozzles (fragment nozzle adds an instrument connection), its segment or "
                "an inline item"
            )
    if sense_at:
        sense_xy = parse_pair(sense_at, "--sense")
        sense_position = f"{object_id}_SensePosition"
        own_sense = instrumentation_position(sense_position, *sense_xy)
    elif info is not None:
        found = [
            (p.get("id"), point_xy_of(p))
            for d in info.sheet.drawings.get(item, [])
            for p in _positions_in(d)
            if point_xy_of(p)
        ]
        if not found:
            raise FragmentError(
                f"{item} has no InstrumentationNodePosition in {info.path}: give the start of "
                f"the measuring line, --sense {item}:x,y"
            )
        sense_position, sense_xy = _nearest(found, (x, y))
    else:
        sense_position = f"{item}_Position"
        made.notes.append(
            f"no --sheet: the measuring line starts at #{sense_position} (an instrument "
            f"connection drawn by fragment equipment/nozzle); otherwise give --sense {item}:x,y"
        )
    nodes = {k: (x + dx, y + dy) for k, (dx, dy) in BUBBLE_NODES.items()}
    route: list[tuple[float, float]] = []
    if sense_xy is not None and not points:
        # Out of the nozzle along the way it faces, clear of its equipment and of the bubble.
        sense_out, obstacles = None, [_bubble_box((x, y))]
        equipment = _equipment_of(info, item) if info is not None else None
        box = _symbol_box(info, equipment) if equipment is not None else None
        if box is not None:
            obstacles.append(box)
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            if math.hypot(sense_xy[0] - centre[0], sense_xy[1] - centre[1]) > _EPS:
                sense_out = _outward(sense_xy[0] - centre[0], sense_xy[1] - centre[1])
        _, (end_name, _), route = _best_route(
            [(sense_position, sense_xy, sense_out)],
            [(k, v, _bubble_out(k)) for k, v in nodes.items()],
            obstacles,
            _measuring_obstacles(info, box),
        )
    elif sense_xy is not None:
        end_name = _nearest(list(nodes.items()), sense_xy)[0]
    else:
        end_name = "Bottom"
    shapes: list[Part] = []
    bubble = resolve_shape(BUBBLE_FIELD if field else BUBBLE_CENTRAL, info, shapes)
    sensor = obj(
        f"{object_id}_Sensor",
        "Plant/Instrumentation.ProcessSignalGeneratingFunction",
        ref("SensingLocation", item),
        string("ProcessSignalGeneratingFunctionNumber", f"{category}T{number}"),
    )
    measuring = obj(
        f"{object_id}_MeasuringLine",
        "Plant/Instrumentation.MeasuringLineFunction",
        ref("Source", f"{object_id}_Sensor"),
        ref("Target", object_id),
    )
    location = "Field" if field else "CentralLocation"
    data = [
        enum("Location", f"Plant/Enumerations.LocationClassification.{location}"),
        string("ProcessInstrumentationFunctionCategory", category),
        string("ProcessInstrumentationFunctionNumber", number),
    ]
    if functions:
        data.append(string("ProcessInstrumentationFunctions", functions))
    function = obj(
        object_id,
        "Plant/Instrumentation.ProcessInstrumentationFunction",
        comps("ProcessSignalGeneratingFunctions", sensor),
        comps("SignalConveyingFunctions", measuring),
        *data,
    )
    letters_from = [(object_id, "ProcessInstrumentationFunctionCategory")]
    if functions:
        letters_from.append((object_id, "ProcessInstrumentationFunctions"))
    bends = parse_points(points) if points else route
    letters_dy, number_dy = BUBBLE_TEXT_FIELD if field else BUBBLE_TEXT_CENTRAL
    positions = [instrumentation_position(f"{object_id}_{k}", *v) for k, v in nodes.items()]
    if own_sense is not None:
        positions.append(own_sense)
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            static(f"{object_id}_Bubble", usage(f"{object_id}_BubbleShape", bubble, x, y)),
            obj(
                f"{object_id}_Label",
                "Plant/Diagram.ProcessInstrumentationFunctionLabel",
                comps(
                    "Elements",
                    text(
                        f"{object_id}_Letters",
                        x,
                        y + letters_dy,
                        category + functions,
                        attributes=letters_from,
                    ),
                    text(
                        f"{object_id}_Number",
                        x,
                        y + number_dy,
                        number,
                        attributes=[(object_id, "ProcessInstrumentationFunctionNumber")],
                    ),
                ),
            ),
            obj(
                f"{object_id}_MeasuringLine_Drawing",
                "Core/Diagram.RepresentationGroup",
                comps(
                    "Groups",
                    static(
                        f"{object_id}_MeasuringLine_Line",
                        connector(
                            f"{object_id}_MeasuringLine_LineShape",
                            sense_position,
                            f"{object_id}_{end_name}",
                            bends,
                            MEASURING_RGB,
                            "Solid",
                        ),
                    ),
                ),
                ref("Represents", f"{object_id}_MeasuringLine"),
            ),
        ),
        comps("NodePositions", *positions),
        ref("Represents", object_id),
    )
    where, into = _where(info, PLANT, "ProcessInstrumentationFunctions", "PlantModel")
    made.parts.append(Part("CONCEPTUAL", where, to_text(function), into))
    where, into = _where(info, DIAGRAM, "Groups", "Diagram (the sheet's drawing)")
    made.parts.append(
        Part(
            "DRAWING",
            where + f". Measuring line from #{sense_position} to #{object_id}_{end_name}; signal "
            f"lines start at #{object_id}_Top/_Bottom/_Left/_Right (fragment signal)",
            to_text(drawing),
            into,
        )
    )
    made.parts += shapes
    return made


# -- signal -------------------------------------------------------------------------------------


def _bubble_positions(
    info: _SheetInfo, element_id: str, free: bool = False
) -> list[tuple[str, tuple[float, float]]]:
    """The instrument's own node positions on its bubble; *free*: those no line uses yet, if
    there are any. The tap of a measuring line drawn with the instrument (the authoring API's
    ``_SensePosition``, on the pipe) is not on the bubble and is left out."""
    found = []
    for drawing in info.sheet.drawings.get(element_id, []):
        for position in _positions_in(drawing, direct=True):
            xy = point_xy_of(position)
            if xy:
                found.append((position.get("id"), xy))
    centre = _bubble_centre(info, element_id)
    if centre is not None:
        on_bubble = [f for f in found if math.dist(f[1], centre) <= BUBBLE_REACH]
        found = on_bubble or found
    if free:
        used = {
            r.get("objects", "").lstrip("#")
            for r in info.sheet.root.iter("References")
            if r.get("property") in ("Source", "Target")
        }
        unused = [f for f in found if f[0] not in used]
        return unused or found
    return found


def _actuator_usage(info: _SheetInfo, valve_id: str) -> etree._Element | None:
    actuator = info.shapes.get(ACTUATOR_SHAPE)
    if actuator is None:
        return None
    for drawing in info.sheet.drawings.get(valve_id, []):
        for element in drawing.iter("Object"):
            if element.get("type") != "Core/Diagram.ShapeUsage":
                continue
            shape = element.find("References[@property='Shape']")
            if shape is not None and shape.get("objects") == f"#{actuator}":
                return element
    return None


def _usage_geometry(element: etree._Element) -> tuple[tuple[float, float], float, float]:
    xy = point_xy_of(element) or (0.0, 0.0)
    rotation = float(element.findtext("Data[@property='Rotation']/Double") or 0.0)
    scale = float(element.findtext("Data[@property='ScaleX']/Double") or 1.0)
    return xy, rotation, scale


def _valve_symbol(info: _SheetInfo, valve_id: str) -> tuple[tuple[float, float], float] | None:
    for drawing in info.sheet.drawings.get(valve_id, []):
        for element in drawing.iter("Object"):
            if element.get("type") == "Core/Diagram.ShapeUsage":
                xy, rotation, _ = _usage_geometry(element)
                return xy, rotation
    return None


def _existing_system(info: _SheetInfo, valve_id: str) -> etree._Element | None:
    for reference, prop in info.sheet.incoming.get(valve_id, []):
        if prop != "Valve":
            continue
        for ancestor in reference.iterancestors("Object"):
            if short_class(ancestor) == "ActuatingSystem":
                return ancestor
    return None


def _signal(
    object_id: str,
    info: _SheetInfo | None,
    *,
    source: str | None,
    target: str | None,
    points: str | None,
    fail_action: str | None,
    number: str | None,
    **_: object,
) -> Fragment:
    info = _need_sheet(info, "signal", "the instrument, the valve and their positions are on it")
    if not source or not target:
        raise FragmentError("signal needs --from INSTRUMENT and --to VALVE|INSTRUMENT[,...]")
    origin = _get(info, source, "--from")
    if short_class(origin) != "ProcessInstrumentationFunction":
        raise FragmentError(
            f"--from {source} is a {short_class(origin)}: a signal starts at a "
            "ProcessInstrumentationFunction (the controller or switch)"
        )
    targets = [t.strip() for t in target.split(",") if t.strip()]
    if len(set(targets)) != len(targets):
        raise FragmentError("--to names a target twice")
    if points and len(targets) > 1:
        raise FragmentError("--points draws one line: give one --to with it")
    action = None
    if fail_action:
        action = FAIL_ACTIONS.get(fail_action.upper().replace(".", ""))
        if action is None:
            raise FragmentError(f"--fail-action {fail_action}: one of {', '.join(FAIL_ACTIONS)}")
    starts = _bubble_positions(info, source, free=True)
    if not starts:
        raise FragmentError(f"{source} has no InstrumentationNodePositions in its drawing")
    made = Fragment("signal", object_id, f"signal line {source} -> {', '.join(targets)}")
    source_centre = _bubble_centre(info, source)
    route_starts = [(i, xy, _node_out(i, xy, source_centre)) for i, xy in starts]
    obstacles = [_bubble_box(source_centre)] if source_centre else []
    drawn = sheet_obstacles(info)
    function_where = {
        prop: _object_where(info, origin, prop)
        for prop in ("SignalConveyingFunctions", "ActuatingFunctions")
    }
    line_where, line_into, source_drawing = _drawing_where(info, source, "the instrument")
    if source_drawing is not None:
        drawn_only = [
            line.get("id") or "(no id)"
            for line in source_drawing.iter("Object")
            if line.get("type") == "Core/Diagram.PolyLine"
            and line.find(".//DataReference[@data='Core/Diagram.DashStyle.Dash']") is not None
        ]
        if drawn_only:
            made.notes.append(
                f"{source}'s drawing has dashed PolyLines ({', '.join(drawn_only)}): a signal "
                "drawn only; remove the one this signal line replaces"
            )
    for target_id in targets:
        signal_id = object_id if len(targets) == 1 else f"{object_id}_{target_id}"
        if len(targets) > 1:
            clash = [i for i in (signal_id, f"{signal_id}_Drawing") if i in info.sheet.by_id]
            if clash:
                raise FragmentError(f"{clash[0]} exists in {info.path}: choose another --id")
        element = _get(info, target_id, "--to")
        drawing_extra: list[etree._Element] = []
        if short_class(element) == "ProcessInstrumentationFunction":
            ends = _bubble_positions(info, target_id)
            if not ends:
                raise FragmentError(f"{target_id} has no InstrumentationNodePositions")
            target_centre = _bubble_centre(info, target_id)
            (start_id, start_xy), (end_id, end_xy), route = _best_route(
                route_starts,
                [(i, xy, _node_out(i, xy, target_centre)) for i, xy in ends],
                obstacles + ([_bubble_box(target_centre)] if target_centre else []),
                _clear_of(drawn, [source_centre, target_centre]),
            )
            duplicate = _duplicate_signal(info, source, target_id, None)
            function = obj(
                signal_id,
                "Plant/Instrumentation.SignalLineFunction",
                ref("Source", source),
                ref("Target", target_id),
            )
            what = f"signal from {source} to instrument {target_id}"
        elif _is(element, "OperatedValve"):
            system = _existing_system(info, target_id)
            actuating_id = f"{signal_id}_Actuating"
            valve_number = data_value(element, "PipingComponentNumber") or target_id
            if system is not None:
                system_id = system.get("id")
                system_number = data_value(system, "ActuatingSystemNumber") or valve_number
                ends = [
                    (p.get("id"), point_xy_of(p))
                    for d in info.sheet.drawings.get(system_id, [])
                    for p in _positions_in(d)
                    if point_xy_of(p)
                ]
                made.notes.append(
                    f"{target_id} is operated by {system_id} already: the signal joins it"
                )
                if action:
                    made.notes.append(f"--fail-action ignored: {system_id}'s actuator has its own")
            else:
                system_id = f"{target_id}_ActuatingSystem"
                for i in (system_id, f"{target_id}_Actuator", f"{system_id}_Drawing"):
                    if i in info.sheet.by_id:
                        raise FragmentError(f"{i} exists in {info.path} but operates no valve")
                system_number = number or valve_number
                tip = _actuator_tip(info, target_id)
                ends = [(f"{target_id}_Actuator_Position", tip)] if tip else []
                made.parts += _actuating_system(
                    info, element, system_id, system_number, action, made.notes
                )
            if not ends:
                tip = _actuator_tip(info, target_id)
                if tip is None:
                    raise FragmentError(f"{target_id} has no drawn symbol in {info.path}")
                end_id = f"{signal_id}_TargetPosition"
                ends = [(end_id, tip)]
                drawing_extra.append(instrumentation_position(end_id, *tip))
            # The line comes in along the actuator's stem, from beyond its end.
            stem = _actuator_out(info, target_id)
            (start_id, start_xy), (end_id, end_xy), route = _best_route(
                route_starts,
                [(i, xy, stem) for i, xy in ends],
                obstacles,
                _clear_of(drawn, [source_centre, *(xy for _, xy in ends)]),
            )
            duplicate = _duplicate_signal(info, source, target_id, system_id)
            actuating = obj(
                actuating_id,
                "Plant/Instrumentation.ActuatingFunction",
                ref("Systems", system_id),
                string("ActuatingFunctionNumber", system_number),
            )
            function = obj(
                signal_id,
                "Plant/Instrumentation.SignalLineFunction",
                ref("Source", source),
                ref("Target", actuating_id),
            )
            where, into = function_where["ActuatingFunctions"]
            made.parts.append(Part("ACTUATING FUNCTION", where, to_text(actuating), into))
            what = f"signal from {source} to {target_id}'s actuating system {system_id}"
        else:
            raise FragmentError(
                f"--to {target_id} is a {short_class(element)}: a signal goes to an operated "
                "valve (GlobeValve, BallValve, ...) or another instrument function"
            )
        if duplicate:
            made.notes.append(
                f"WARNING: {source} signals {target_id} already ({duplicate}): this adds a "
                "second signal line for the same relation; drop it unless that is meant"
            )
        bends = parse_points(points) if points else route
        children = [
            comps(
                "Groups",
                static(
                    f"{signal_id}_Line",
                    connector(
                        f"{signal_id}_LineShape", start_id, end_id, bends, SIGNAL_RGB, "Dash"
                    ),
                ),
            )
        ]
        if drawing_extra:
            children.append(comps("NodePositions", *drawing_extra))
        drawing = obj(
            f"{signal_id}_Drawing",
            "Core/Diagram.RepresentationGroup",
            *children,
            ref("Represents", signal_id),
        )
        where, into = function_where["SignalConveyingFunctions"]
        made.parts.insert(
            len([p for p in made.parts if p.title == "CONCEPTUAL"]),
            Part("CONCEPTUAL", where + f": the {what}", to_text(function), into),
        )
        made.parts.append(
            Part(
                "DRAWING",
                line_where + f". Dashed line #{start_id} ({_xy(start_xy)}) -> #{end_id} "
                f"({_xy(end_xy)})" + (f" via {'; '.join(_xy(b) for b in bends)}" if bends else ""),
                to_text(drawing),
                line_into,
            )
        )
    return made


def _actuator_tip(info: _SheetInfo, valve_id: str) -> tuple[float, float] | None:
    """Where the stem of the valve's actuator ends: drawn, or where _actuating_system puts it."""
    drawn = _actuator_usage(info, valve_id)
    if drawn is not None:
        (x, y), rotation, scale = _usage_geometry(drawn)
        dx, dy = rotate(ACTUATOR_REACH * scale, 0.0, rotation)
        return x + dx, y + dy
    symbol = _valve_symbol(info, valve_id)
    if symbol is None:
        return None
    (x, y), rotation = symbol
    side = _actuator_side(rotation)
    dx, dy = rotate(ACTUATOR_REACH * ACTUATOR_SCALE, 0.0, side)
    return x + dx, y + dy


def _actuator_out(info: _SheetInfo, valve_id: str) -> tuple[float, float]:
    """The direction the valve's actuator stem points (drawn, or as _actuating_system draws it)."""
    drawn = _actuator_usage(info, valve_id)
    if drawn is not None:
        rotation = _usage_geometry(drawn)[1]
    else:
        symbol = _valve_symbol(info, valve_id)
        rotation = _actuator_side(symbol[1]) if symbol else 270.0
    dx, dy = rotate(1.0, 0.0, rotation)
    return _outward(dx, dy)


def _actuator_horizontal(info: _SheetInfo, valve_id: str) -> bool:
    """Whether the valve's actuator (drawn, or as _actuating_system draws it) points sideways."""
    return abs(_actuator_out(info, valve_id)[1]) < _EPS


def _actuator_side(valve_rotation: float) -> float:
    """Actuator up for a horizontal valve, to the left for a vertical one."""
    horizontal = round(valve_rotation / 90) % 2 == 0
    return 270.0 if horizontal else 180.0


def _actuating_system(
    info: _SheetInfo,
    valve: etree._Element,
    system_id: str,
    system_number: str,
    action: tuple[str, str] | None,
    notes: list[str],
) -> list[Part]:
    valve_id = valve.get("id")
    actuator_id = f"{valve_id}_Actuator"
    actuator_data = [string("DeviceTypeName", "general")]
    if action:
        actuator_data += [
            enum("FailAction", f"Plant/Enumerations.FailActionClassification.{action[0]}"),
            string("FailActionRepresentation", action[1]),
        ]
    system = obj(
        system_id,
        "Plant/Instrumentation.ActuatingSystem",
        comps(
            "ControlledActuator",
            obj(actuator_id, "Plant/Instrumentation.ControlledActuator", *actuator_data),
        ),
        comps(
            "OperatedValveReference",
            obj(
                f"{valve_id}_ValveReference",
                "Plant/Instrumentation.OperatedValveReference",
                ref("Valve", valve_id),
            ),
        ),
        string("ActuatingSystemNumber", system_number),
    )
    parts: list[Part] = []
    tip = _actuator_tip(info, valve_id)
    drawn = _actuator_usage(info, valve_id)
    groups: list[etree._Element] = []
    if drawn is None:
        symbol = _valve_symbol(info, valve_id)
        if symbol is None:
            raise FragmentError(f"{valve_id} has no drawn symbol in {info.path}")
        (x, y), rotation = symbol
        shape_id = resolve_shape(ACTUATOR_SHAPE, info, parts)
        groups.append(
            static(
                f"{actuator_id}_Symbol",
                usage(
                    f"{actuator_id}_SymbolShape",
                    shape_id,
                    x,
                    y,
                    _actuator_side(rotation),
                    (ACTUATOR_SCALE, ACTUATOR_SCALE),
                ),
            )
        )
    else:
        notes.append(
            f"{valve_id}'s drawing has an actuator symbol already: the actuating system's "
            "drawing holds only the position the signal line ends at (and the fail action)"
        )
    if action:
        # Beside the actuator's circle (radius about 2 mm at scale 0.4), clear of the stem.
        if _actuator_horizontal(info, valve_id):
            label_at, label_align = (tip[0], tip[1] - 3.5), "CenterCenter"
        else:
            label_at, label_align = (tip[0] + 3.0, tip[1]), "LeftCenter"
        groups.append(
            obj(
                f"{actuator_id}_FailAction",
                "Plant/Diagram.FailActionLabel",
                comps(
                    "Elements",
                    text(
                        f"{actuator_id}_FailActionText",
                        *label_at,
                        action[1],
                        2.0,
                        label_align,
                        [(actuator_id, "FailActionRepresentation")],
                    ),
                ),
            )
        )
    actuator_children = [comps("Groups", *groups)] if groups else []
    drawing = obj(
        f"{system_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            obj(
                f"{actuator_id}_Drawing",
                "Core/Diagram.RepresentationGroup",
                *actuator_children,
                comps("NodePositions", instrumentation_position(f"{actuator_id}_Position", *tip)),
                ref("Represents", actuator_id),
            ),
        ),
        ref("Represents", system_id),
    )
    where, into = _where(info, PLANT, "ActuatingSystems", "PlantModel")
    parts.insert(
        0,
        Part(
            "ACTUATING SYSTEM",
            where + f": {system_id} operates {valve_id} (OperatedValveReference)",
            to_text(system),
            into,
        ),
    )
    where, into = _where(info, DIAGRAM, "Groups", "Diagram")
    parts.insert(
        1,
        Part(
            "ACTUATING SYSTEM DRAWING",
            where + f"; signal lines end at #{actuator_id}_Position ({_xy(tip)})",
            to_text(drawing),
            into,
        ),
    )
    return parts


# -- off-page connector -------------------------------------------------------------------------


def _offpage(
    object_id: str,
    info: _SheetInfo | None,
    *,
    direction: str | None,
    at: str | None,
    rotation: float,
    dn: str | None,
    standard: str,
    note: str | None,
    note_at: str | None,
    **_: object,
) -> Fragment:
    if direction not in ("in", "out"):
        raise FragmentError("offpage needs --in (flow comes from another sheet) or --out")
    if at is None:
        raise FragmentError("offpage needs --at X,Y (where the pipe meets the arrow)")
    x, y = parse_pair(at, "--at")
    inflow = direction == "in"
    kind = "FlowInPipeOffPageConnector" if inflow else "FlowOutPipeOffPageConnector"
    made = Fragment("offpage", object_id, f"{kind} at {fmt_num(x)},{fmt_num(y)}")
    node_id = f"{object_id}_N"
    size = dn_number(dn) if dn else None
    node = (
        piping_node(node_id, size, _standard(size, standard, made.notes))
        if size
        else obj(node_id, "Plant/Piping.PipingNode")
    )
    connector_object = obj(object_id, f"Plant/Piping.{kind}", comps("Nodes", node))
    shapes: list[Part] = []
    name = (
        "ARROW_FOR_INLET_OF_ESSENTIAL_SUBSTANCES_SHAPE"
        if inflow
        else "ARROW_FOR_OUTLET_OF_ESSENTIAL_SUBSTANCES_SHAPE"
    )
    shape_id = resolve_shape(name, info, shapes)
    groups = [
        node_position(node_id, x, y),
        static(
            f"{object_id}_Symbol",
            usage(f"{object_id}_SymbolShape", shape_id, x, y, rotation, (OFFPAGE_SCALE,) * 2),
        ),
    ]
    if note:
        # Beyond the arrow (7 mm long), on the side away from the pipe.
        far = rotate(-9.0 if inflow else 9.0, 0.0, rotation)
        if abs(far[0]) >= abs(far[1]):
            align = "LeftCenter" if far[0] > 0 else "RightCenter"
        else:
            align = "CenterCenter"
            far = (far[0], far[1] + (2.0 if far[1] > 0 else -2.0))
        if note_at:
            nx, ny = parse_pair(note_at, "--note-at")
        else:
            from chemeascode.domains.piping.authoring.builders import note_in_frame

            (nx, ny), align = note_in_frame(note, (x + far[0], y + far[1]), align, (x, y))
        groups.append(
            static(
                f"{object_id}_Note",
                text(f"{object_id}_NoteText", nx, ny, note, 2.5, align),
            )
        )
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps("Groups", *groups),
        ref("Represents", object_id),
    )
    if inflow:
        where = (
            'into <Components property="Items"> of the PipingNetworkSegment that STARTS at it '
            f"(it owns it): the segment and its first pipe have SourceItem #{object_id} "
            f"SourceNode #{node_id}"
        )
    else:
        where = (
            'into <Components property="Items"> of the PipingNetworkSegment that ENDS at it: '
            f"the segment and its last pipe have TargetItem #{object_id} TargetNode #{node_id}"
        )
    made.parts.append(Part("CONCEPTUAL", where, to_text(connector_object)))
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of that segment\'s RepresentationGroup. The '
            f"pipe attaches at #{node_id}_Position ({_xy((x, y))})",
            to_text(drawing),
        )
    )
    made.parts += shapes
    return made


# -- line ---------------------------------------------------------------------------------------


def _line(
    object_id: str,
    info: _SheetInfo | None,
    *,
    number: str | None,
    dn: str | None,
    standard: str,
    fluid: str | None,
    at: str | None,
    **_: object,
) -> Fragment:
    if not number:
        raise FragmentError("line needs --number LINE (its LineNumber, e.g. LOX-4101)")
    size = dn_number(dn)
    made = Fragment("line", object_id, f"PipingNetworkSystem {number} DN {size}")
    std = _standard(size, standard, made.notes)
    data = []
    if fluid:
        data.append(string("FluidCode", fluid))
    data += [
        string("LineNumber", number),
        string("NominalDiameterNumericalValueRepresentation", size),
        string("NominalDiameterRepresentation", f"DN {size}"),
        *([enum("NominalDiameterStandard", std)] if std else []),
        string("NominalDiameterTypeRepresentation", "DN"),
    ]
    segments = comps("Segments")
    segments.append(etree.Comment(" segment fragments (fragment segment ...), in flow order "))
    system = obj(object_id, "Plant/Piping.PipingNetworkSystem", segments, *data)
    groups = comps("Groups")
    groups.append(etree.Comment(" the drawings of its segments "))
    if at is not None:
        x, y = parse_pair(at, "--at")
        groups.append(
            obj(
                f"{object_id}_Label",
                "Plant/Diagram.PipingNetworkSystemLabel",
                comps(
                    "Elements",
                    text(
                        f"{object_id}_LabelText",
                        x,
                        y,
                        number,
                        2.5,
                        "LeftBottom",
                        [(object_id, "LineNumber")],
                    ),
                ),
            )
        )
    else:
        made.notes.append("no --at: the line has no number label (give --at X,Y for one)")
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        groups,
        ref("Represents", object_id),
    )
    where, into = _where(info, PLANT, "PipingNetworkSystems", "PlantModel")
    made.parts.append(
        Part("CONCEPTUAL", where + "; its segments go into Segments", to_text(system), into)
    )
    where, into = _where(info, DIAGRAM, "Groups", "Diagram (the sheet's drawing)")
    made.parts.append(
        Part("DRAWING", where + "; segment drawings go into its Groups", to_text(drawing), into)
    )
    return made


# -- note ---------------------------------------------------------------------------------------


def _note(
    object_id: str,
    info: _SheetInfo | None,
    *,
    at: str | None,
    text_value: str | None,
    size: float | None = None,
    **_: object,
) -> Fragment:
    if not text_value:
        raise FragmentError("note needs --text TEXT")
    if at is None:
        raise FragmentError("note needs --at X,Y (the text's left end)")
    x, y = parse_pair(at, "--at")
    made = Fragment("note", object_id, f"free text at {fmt_num(x)},{fmt_num(y)}")
    note = static(object_id, text(f"{object_id}_Text", x, y, text_value, size or 2.5, "LeftCenter"))
    made.parts.append(Part("CONCEPTUAL", "nothing: a note is drawing only, owned by no object"))
    where, into = _where(info, DIAGRAM, "Groups", "Diagram (the sheet's drawing, top level)")
    made.parts.append(
        Part(
            "DRAWING",
            where + ". At the top level it belongs to no object, so cheme.label-literal "
            "does not read it as a label",
            to_text(note),
            into,
        )
    )
    return made


# -- shape --------------------------------------------------------------------------------------


def _shape_kind(object_id: str | None, info: _SheetInfo | None, *, name: str | None, **_: object):
    from chemeascode.domains.piping.authoring.shapes import catalogue, normalise_name

    names = sorted(catalogue())
    if not name:
        raise FragmentError("shape needs a NAME, one of: " + ", ".join(names))
    wanted = normalise_name(name)
    template = catalogue().get(wanted)
    if template is None:
        close = difflib.get_close_matches(wanted, names, n=4, cutoff=0.4)
        raise FragmentError(
            f"no shape {wanted} in the catalogue"
            + (f"; did you mean {', '.join(close)}?" if close else "")
            + " (the dexpi-xml skill's shapes.md lists them)"
        )
    shape_id = object_id or template.get("id")
    made = Fragment("shape", shape_id, f"{wanted}")
    if info is not None and wanted in info.shapes:
        present = info.sheet.by_id.get(info.shapes[wanted])
        made.summary += " (present)"
        made.parts.append(
            Part(
                "SHAPE",
                f"nothing to paste: {info.path} has {wanted} already as #{info.shapes[wanted]} "
                f"({info.sheet.line(present) if present is not None else 'catalogue'}); "
                "reference that id",
            )
        )
        made.notes.append(f"{wanted} is in {info.path} already: #{info.shapes[wanted]}")
        return made
    if info is not None and shape_id in info.sheet.by_id:
        raise FragmentError(f"{info.path} has an object {shape_id}: pass --id NEW_ID")
    element = _copy.deepcopy(template)
    if shape_id != template.get("id"):
        old = template.get("id")
        for child in element.iter("Object"):
            if child.get("id", "").startswith(old):
                child.set("id", shape_id + child.get("id")[len(old) :])
    where = 'paste once into <Components property="Shapes"> of ' + (
        info.catalogue() if info is not None else "the sheet's ShapeCatalogue"
    )
    into = (info.catalogue_id(), "Shapes") if info is not None and info.catalogue_id() else None
    made.parts.append(
        Part("SHAPE", where + f"; reference it as #{shape_id}", to_text(element), into)
    )
    return made


_KINDS = {
    "equipment": _equipment,
    "nozzle": _nozzle,
    "instrument": _instrument,
    "signal": _signal,
    "offpage": _offpage,
    "line": _line,
    "note": _note,
    "shape": _shape_kind,
}


def make(kind: str, object_id: str | None, info: _SheetInfo | None, **options) -> Fragment:
    """The fragment of one of the drafting kinds; options as ``make_fragment`` takes them."""
    import inspect

    function = _KINDS[kind]
    for name, parameter in inspect.signature(function).parameters.items():
        if parameter.kind is parameter.KEYWORD_ONLY and parameter.default is parameter.empty:
            options.setdefault(name, None)
    return _one_new_block_each(function(object_id, info, **options))


def _one_new_block_each(made: Fragment) -> Fragment:
    """Several parts into the same new ``<Components>`` (a trip to two valves gives two
    ACTUATING FUNCTIONs into an instrument that has none): only the first says to create it,
    the rest go into the block it creates (two blocks of one property lose objects)."""
    created: dict[tuple[str, str], Part] = {}
    for part in made.parts:
        if part.into is None:
            continue
        first = created.get(part.into)
        if first is not None and "create it, it has none yet" in part.where:
            holder, prop = part.into
            detail = part.where.split(": create it, it has none yet", 1)[-1]
            part.where = (
                f'into the <Components property="{prop}"> of {holder} that the {first.title} '
                f"part above creates (one block for both, not a second one){detail}"
            )
        elif "create it, it has none yet" in part.where:
            created[part.into] = part
    return made
