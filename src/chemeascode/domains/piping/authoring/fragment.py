"""``cheme fragment``: ready-to-paste XML for the verbose parts of a sheet.

Each fragment has a CONCEPTUAL part (the plant object) and a DRAWING part (how it is drawn),
each preceded by an XML comment saying where it goes, and a SHAPE part when the symbol is not
in the catalogue yet. Ids derive from ``--id``:

- node: ``ID``; with ``--at`` its group ``ID_Drawing`` and position ``ID_Position``;
- valve: ``ID``, nodes ``ID_N1`` (inlet) and ``ID_N2`` (outlet); drawing ``ID_Drawing`` with
  ``ID_Symbol``/``ID_SymbolShape`` and node groups ``ID_N1_Drawing``/``ID_N1_Position``, ...;
- tee: ``ID``, nodes ``ID_N1`` (run in), ``ID_N2`` (run out), ``ID_N3`` (branch); drawn as a
  valve is;
- pipe: ``ID``; drawing ``ID_Drawing``, ``ID_Line``, ``ID_LineShape`` (the ConnectorLine);
- segment: ``ID``; drawing ``ID_Drawing``;
- label: no conceptual part; ``ID``, ``ID_Text``, ``ID_Template``, ``ID_Fragment``;
- equipment, nozzle, instrument, signal, offpage, line, note, shape: see
  ``chemeascode.domains.piping.authoring.fragment_items``.

The node positions a fragment draws are named ``<node id>_Position``, so a ``pipe`` fragment
between two fragment nodes finds them without ``--sheet``. With ``--sheet`` the shape ids come
from the sheet's catalogue (looked up by shape name), a pipe's node positions from the sheet, and
a label's text from the value it shows.
"""

from __future__ import annotations

import copy as _copy
import math
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    boolean,
    check_id,
    color,
    comps,
    double,
    enum,
    fmt_num,
    obj,
    parse_pair,
    parse_points,
    point,
    point_xy,
    points,
    ref,
    rotate,
    string,
    stroke,
    to_text,
)
from chemeascode.domains.piping.show import Sheet, data_value, short_class

KINDS = (
    "node",
    "pipe",
    "valve",
    "tee",
    "segment",
    "label",
    "equipment",
    "nozzle",
    "instrument",
    "signal",
    "offpage",
    "line",
    "note",
    "shape",
)

#: The kinds ``chemeascode.domains.piping.authoring.fragment_items`` makes.
DRAFTING_KINDS = ("equipment", "nozzle", "instrument", "signal", "offpage", "line", "note", "shape")

#: Valve (inline item) class -> the catalogue's shape name and the reference id (None: an
#: added shape, see ``chemeascode.domains.piping.authoring.shapes``).
VALVE_SHAPES = {
    "GlobeValve": ("GLOBE_VALVE_SHAPE", "Shape3"),
    "BallValve": ("BALL_VALVE_SHAPE", "Shape8"),
    "GateValve": ("GATE_VALVE_SHAPE", None),
    "SwingCheckValve": ("SWING_CHECK_VALVE_SHAPE", "Shape6"),
    "ButterflyValve": ("BUTTERFLY_VALVE_SHAPE", "Shape5"),
    "OperatedValve": ("VALVE_SHAPE", None),
    "CheckValve": ("CHECK_VALVE_SHAPE", None),
    "SteamTrap": ("STEAM_TRAP_SHAPE", None),
    "Strainer": ("STRAINER_SHAPE", None),
    "ConicalStrainer": ("STRAINER_SHAPE", None),
    "FlameArrestor": ("FLAME_ARRESTOR_SHAPE", None),
    "RuptureDisc": ("RUPTURE_DISC_SHAPE", None),
    "Silencer": ("SILENCER_SHAPE", None),
}
#: Half the length of an inline symbol at scale 1 (its ends, the shape's ports): valves are
#: 10 mm long, the silencer 12 mm, the rupture disc 5 mm and the flame arrestor 4 mm.
INLINE_HALF = {"Silencer": 6.0, "RuptureDisc": 2.5, "FlameArrestor": 2.0}
#: Default scale of an inline symbol other than a valve's 0.4.
INLINE_SCALE = {"Silencer": 0.5}
TEE_SHAPE = ("T_TYPE_CONNECTION_SHAPE", "Shape12")
PIPE_RGB = (128, 128, 0)
#: A valve symbol (10 x 5 at scale 1) at scale 0.4: its ends are 2 mm from the centre.
VALVE_SCALE = 0.4
VALVE_HALF = 2.0
TEE_SCALE = 0.0001
TEE_HALF = 0.001
BRANCH = {"up": (0.0, -1.0), "down": (0.0, 1.0), "left": (-1.0, 0.0), "right": (1.0, 0.0)}

#: Label class for an attribute when the object's class is unknown (no ``--sheet``).
LABEL_BY_ATTRIBUTE = {
    "TagName": "EquipmentTagNameLabel",
    "PipingComponentNumber": "ValveLabel",
    "PipingComponentName": "ValveLabel",
    "LineNumber": "PipingNetworkSystemLabel",
    "SegmentNumber": "PipingNetworkSegmentLabel",
    "SubTagName": "NozzleStandardLabel",
    "ActuatingSystemNumber": "ActuatingSystemNumberLabel",
}


class FragmentError(Exception):
    """The fragment cannot be made; the message says why."""


@dataclass
class Part:
    title: str
    where: str
    xml: str = ""
    #: Where it goes, for tools: (id of the holding object, Components property). None when
    #: the holder is not known (no --sheet) or the part needs no paste.
    into: tuple[str, str] | None = None


@dataclass
class Fragment:
    kind: str
    object_id: str
    summary: str
    parts: list[Part] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [_comment(f"cheme fragment {self.kind} {self.object_id}: {self.summary}")]
        for part in self.parts:
            lines.append(_comment(f"{part.title}: {part.where}"))
            if part.xml:
                lines.append(part.xml)
        lines.append(_comment("END"))
        return "\n".join(lines)

    def part(self, title: str) -> Part | None:
        return next((p for p in self.parts if p.title == title), None)

    def all(self, title: str) -> list[Part]:
        return [p for p in self.parts if p.title == title]


def _comment(text: str) -> str:
    while "--" in text:
        text = text.replace("--", "-")
    return f"<!-- {text.rstrip('-')} -->"


# -- pieces -------------------------------------------------------------------------------------


def dn_number(dn: str | None) -> str:
    if dn is None:
        raise FragmentError("--dn is required (e.g. --dn 80)")
    value = dn.upper().replace("DN", "").strip()
    try:
        number = float(value)
    except ValueError as failure:
        raise FragmentError(f"--dn: not a nominal diameter: {dn!r}") from failure
    if not math.isfinite(number) or number <= 0:
        raise FragmentError(f"--dn: must be a positive number: {dn!r}")
    return fmt_num(number)


def _standard(dn: str, standard: str, notes: list[str]) -> str | None:
    if standard.lower() == "none":
        return None
    from pydexpi.pydexpi_classes.pydexpi_classes import NominalDiameterStandardClassification

    wanted = f"{standard}ObjectDn{dn}".lower()
    for member in NominalDiameterStandardClassification:
        if member.value.lower() == wanted:
            return f"Plant/Enumerations.NominalDiameterStandardClassification.{member.value}"
    notes.append(f"no {standard} DN {dn} in DEXPI's NominalDiameterStandard: left out")
    return None


def piping_node(node_id: str, dn: str, standard: str | None) -> etree._Element:
    data = [
        string("NominalDiameterNumericalValueRepresentation", dn),
        string("NominalDiameterRepresentation", f"DN {dn}"),
    ]
    if standard:
        data.append(enum("NominalDiameterStandard", standard))
    data.append(string("NominalDiameterTypeRepresentation", "DN"))
    return obj(node_id, "Plant/Piping.PipingNode", *data)


def node_position(node_id: str, x: float, y: float) -> etree._Element:
    return obj(
        f"{node_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "NodePositions",
            obj(
                f"{node_id}_Position",
                "Plant/Diagram.PipingNodePosition",
                ref("Node", node_id),
                point("Position", x, y),
            ),
        ),
        ref("Represents", node_id),
    )


def shape_usage(
    usage_id: str,
    shape_id: str,
    x: float,
    y: float,
    rotation: float,
    scale: float | tuple[float, float],
    mirrored: bool = False,
) -> etree._Element:
    """A ShapeUsage of *shape_id*; *scale* is one factor or (ScaleX, ScaleY)."""
    sx, sy = (scale, scale) if isinstance(scale, int | float) else scale
    return obj(
        usage_id,
        "Core/Diagram.ShapeUsage",
        ref("Shape", shape_id),
        boolean("IsMirrored", mirrored),
        point("Position", x, y),
        double("Rotation", rotation % 360),
        double("ScaleX", sx),
        double("ScaleY", sy),
    )


class _SheetInfo:
    """What a fragment reads from ``--sheet``: shapes, node positions, objects."""

    def __init__(self, path: Path):
        self.path = path
        self.sheet = Sheet.load(path, str(path))
        self.shapes: dict[str, str] = {}
        self.positions: dict[str, str] = {}
        for element in self.sheet.root.iter("Object"):
            kind = element.get("type")
            if kind == "Core/Diagram.Shape" and element.get("id"):
                shape_name = data_value(element, "Name")
                if shape_name:
                    self.shapes.setdefault(shape_name, element.get("id"))
            elif kind == "Plant/Diagram.PipingNodePosition" and element.get("id"):
                node = element.find("References[@property='Node']")
                if node is not None and node.get("objects", "").split():
                    target = node.get("objects").split()[0].lstrip("#")
                    self.positions.setdefault(target, element.get("id"))

    def catalogue(self) -> str:
        catalogue = self.sheet.root.find(".//Object[@type='Core/Diagram.ShapeCatalogue']")
        if catalogue is None or not catalogue.get("id"):
            return "the sheet's ShapeCatalogue"
        return f"{catalogue.get('id')} ({self.sheet.line(catalogue)})"

    def catalogue_id(self) -> str | None:
        catalogue = self.sheet.root.find(".//Object[@type='Core/Diagram.ShapeCatalogue']")
        return catalogue.get("id") if catalogue is not None else None

    def first(self, kind: str) -> etree._Element | None:
        return next((e for e in self.sheet.root.iter("Object") if e.get("type") == kind), None)

    def holder(self, kind: str, prop: str) -> tuple[str, tuple[str, str] | None]:
        """Where to paste into ``<Components property=prop>`` of the first object of *kind*."""
        element = self.first(kind)
        if element is None or not element.get("id"):
            return f'<Components property="{prop}"> of the {kind.rsplit(".", 1)[-1]}', None
        components = element.find(f"Components[@property='{prop}']")
        if components is None:
            return (
                f'<Components property="{prop}"> of {element.get("id")} '
                f"({self.sheet.line(element)}): create it, it has none yet",
                (element.get("id"), prop),
            )
        return (
            f'<Components property="{prop}"> of {element.get("id")} '
            f"({self.sheet.line(components)})",
            (element.get("id"), prop),
        )


def resolve_shape(name: str, info: _SheetInfo | None, parts: list[Part]) -> str:
    """The id of catalogue shape *name* to reference, adding a SHAPE part when it is missing.

    With ``--sheet``: the sheet's own shape of that name, or the template catalogue's (a SHAPE
    part to paste once). Without: the reference shapes are in every sheet made from the
    template; an added shape comes with a SHAPE part, to paste unless the catalogue has it.
    """
    from chemeascode.domains.piping.authoring.shapes import BY_NAME, catalogue

    if info is not None and name in info.shapes:
        return info.shapes[name]
    template = catalogue().get(name)
    if template is None:
        raise FragmentError(
            f"no {name} in the shape catalogue: the dexpi-xml skill's shapes.md lists every "
            "shape (fragment shape NAME prints one)"
        )
    shape_id = template.get("id")
    if info is None and name not in BY_NAME:
        return shape_id
    if any(p.title == "SHAPE" and f'id="{shape_id}"' in p.xml for p in parts):
        return shape_id
    if info is not None and shape_id in info.sheet.by_id:
        raise FragmentError(
            f"{info.path} has no {name}, but its id {shape_id} is taken: paste the shape from "
            f"`cheme fragment shape {name} --id <new id>` and reference that"
        )
    where = (
        f'paste once into <Components property="Shapes"> of {info.catalogue()}'
        if info
        else 'paste once into <Components property="Shapes"> of the ShapeCatalogue, '
        f"unless the catalogue has a {name} already (then use its id)"
    )
    into = (info.catalogue_id(), "Shapes") if info and info.catalogue_id() else None
    parts.append(Part("SHAPE", where, to_text(_copy.deepcopy(template)), into))
    return shape_id


def _shape(
    name: str, default: str | None, info: _SheetInfo | None, valve_class: str, parts: list[Part]
) -> str:
    return resolve_shape(name, info, parts)


def _at(at: str | None) -> tuple[float, float]:
    if at is None:
        raise FragmentError("--at X,Y is required (sheet mm, Y down)")
    return parse_pair(at, "--at")


def _item_node(value: str | None, option: str) -> tuple[str, str]:
    if not value or ":" not in value:
        raise FragmentError(f"{option} ITEM:NODE is required, e.g. {option} Pump_P4711B:Node1")
    item, node = (v.strip() for v in value.split(":", 1))
    return check_id(item, option), check_id(node, option)


# -- kinds --------------------------------------------------------------------------------------


def _node(object_id: str, dn: str, standard: str, at: str | None) -> Fragment:
    made = Fragment("node", object_id, f"PipingNode DN {dn}")
    node = piping_node(object_id, dn, _standard(dn, standard, made.notes))
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Nodes"> of the item that owns it (a nozzle owns one, '
            "an inline valve two: node 1 inlet, node 2 outlet)",
            to_text(node),
        )
    )
    if at is None:
        made.parts.append(
            Part(
                "DRAWING",
                "none without --at X,Y; with it, a PipingNodePosition group for the item's "
                'RepresentationGroup <Components property="Groups">',
            )
        )
    else:
        x, y = parse_pair(at, "--at")
        made.parts.append(
            Part(
                "DRAWING",
                'into <Components property="Groups"> of the RepresentationGroup that draws the '
                f"item; pipes attach to #{object_id}_Position at {fmt_num(x)},{fmt_num(y)}",
                to_text(node_position(object_id, x, y)),
            )
        )
    return made


def _valve(
    object_id: str,
    valve_class: str,
    dn: str,
    standard: str,
    at: str | None,
    rotation: float,
    tag: str | None,
    info: _SheetInfo | None,
    scale: float | None = None,
) -> Fragment:
    if valve_class not in VALVE_SHAPES:
        raise FragmentError(f"--class {valve_class}: one of {', '.join(VALVE_SHAPES)}")
    x, y = _at(at)
    made = Fragment(
        "valve",
        object_id,
        f"{valve_class} DN {dn} at {fmt_num(x)},{fmt_num(y)}, rotation {fmt_num(rotation)}",
    )
    std = _standard(dn, standard, made.notes)
    inlet, outlet = f"{object_id}_N1", f"{object_id}_N2"
    data = [string("PipingComponentNumber", tag)] if tag else []
    valve = obj(
        object_id,
        f"Plant/Piping.{valve_class}",
        comps("Nodes", piping_node(inlet, dn, std), piping_node(outlet, dn, std)),
        *data,
    )
    shapes: list[Part] = []
    name, default = VALVE_SHAPES[valve_class]
    shape_id = _shape(name, default, info, valve_class, shapes)
    scale = scale if scale is not None else INLINE_SCALE.get(valve_class, VALVE_SCALE)
    half = INLINE_HALF.get(valve_class, VALVE_HALF / VALVE_SCALE) * scale
    ix, iy = rotate(-half, 0.0, rotation)
    ox, oy = rotate(half, 0.0, rotation)
    inlet_at, outlet_at = (x + ix, y + iy), (x + ox, y + oy)
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            node_position(inlet, *inlet_at),
            node_position(outlet, *outlet_at),
            obj(
                f"{object_id}_Symbol",
                "Core/Diagram.Static",
                comps(
                    "Elements",
                    shape_usage(f"{object_id}_SymbolShape", shape_id, x, y, rotation, scale),
                ),
            ),
        ),
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Items"> of the PipingNetworkSegment it sits in. The '
            f"pipe before it ends at TargetItem #{object_id} TargetNode #{inlet} (inlet), the "
            f"pipe after it starts at SourceItem #{object_id} SourceNode #{outlet} (outlet)",
            to_text(valve),
        )
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of that segment\'s RepresentationGroup '
            "(the one with References Represents the segment). ConnectorLines end at "
            f"#{inlet}_Position ({_xy(inlet_at)}) and start at #{outlet}_Position "
            f"({_xy(outlet_at)})",
            to_text(drawing),
        )
    )
    made.parts += shapes
    return made


def _xy(xy: tuple[float, float]) -> str:
    return f"{fmt_num(xy[0])},{fmt_num(xy[1])}"


def _tee(
    object_id: str,
    dn: str,
    branch_dn: str,
    standard: str,
    at: str | None,
    rotation: float,
    branch: str | None,
    tag: str | None,
    info: _SheetInfo | None,
) -> Fragment:
    run = rotate(1.0, 0.0, rotation)
    if branch is None:
        # Default: the branch leaves on the left of the flow ("up" for flow left to right).
        bx, by = rotate(0.0, -1.0, rotation)
        branch = min(BRANCH, key=lambda b: (BRANCH[b][0] - bx) ** 2 + (BRANCH[b][1] - by) ** 2)
    elif branch not in BRANCH:
        raise FragmentError(f"--branch {branch}: one of {', '.join(BRANCH)}")
    else:
        bx, by = BRANCH[branch]
        if abs(bx * run[0] + by * run[1]) > 0.5:
            sides = [b for b, (vx, vy) in BRANCH.items() if abs(vx * run[0] + vy * run[1]) <= 0.5]
            raise FragmentError(
                f"--branch {branch} lies along the run (--rotation {fmt_num(rotation)}): the "
                f"branch node would sit on a run node. Use --branch {' or '.join(sides)}"
            )
    x, y = _at(at)
    made = Fragment(
        "tee",
        object_id,
        f"PipeTee DN {dn}, branch DN {branch_dn} {branch}, at {fmt_num(x)},{fmt_num(y)}",
    )
    std = _standard(dn, standard, made.notes)
    branch_std = std if branch_dn == dn else _standard(branch_dn, standard, made.notes)
    run_in, run_out, side = (f"{object_id}_N{i}" for i in (1, 2, 3))
    data = [string("PipingComponentNumber", tag)] if tag else []
    tee = obj(
        object_id,
        "Plant/Piping.PipeTee",
        comps(
            "Nodes",
            piping_node(run_in, dn, std),
            piping_node(run_out, dn, std),
            piping_node(side, branch_dn, branch_std),
        ),
        *data,
    )
    shapes: list[Part] = []
    shape_id = _shape(*TEE_SHAPE, info, "PipeTee", shapes)
    ix, iy = rotate(-TEE_HALF, 0.0, rotation)
    ox, oy = rotate(TEE_HALF, 0.0, rotation)
    bx, by = TEE_HALF * bx, TEE_HALF * by
    at_in, at_out, at_side = (x + ix, y + iy), (x + ox, y + oy), (x + bx, y + by)
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            node_position(run_in, *at_in),
            node_position(run_out, *at_out),
            node_position(side, *at_side),
            obj(
                f"{object_id}_Symbol",
                "Core/Diagram.Static",
                comps(
                    "Elements",
                    shape_usage(f"{object_id}_SymbolShape", shape_id, x, y, 0.0, TEE_SCALE),
                ),
            ),
        ),
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Items"> of the segment that ENDS at the tee (only that '
            f"one owns it): its last pipe ends at TargetItem #{object_id} TargetNode #{run_in}, "
            f"and so do the segment's own TargetItem/TargetNode. The run continues in a segment "
            f"starting at SourceItem #{object_id} SourceNode #{run_out}; the branch segment "
            f"starts (or, flowing into the tee, ends) at #{side}",
            to_text(tee),
        )
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of the owning segment\'s RepresentationGroup. '
            f"Lines attach at #{run_in}_Position ({_xy(at_in)}), #{run_out}_Position "
            f"({_xy(at_out)}) and #{side}_Position ({_xy(at_side)})",
            to_text(drawing),
        )
    )
    made.parts += shapes
    return made


def _pipe(
    object_id: str,
    source: str | None,
    target: str | None,
    bends: str | None,
    info: _SheetInfo | None,
) -> Fragment:
    (from_item, from_node), (to_item, to_node) = (
        _item_node(source, "--from"),
        _item_node(target, "--to"),
    )
    made = Fragment("pipe", object_id, f"Pipe {from_item}.{from_node} -> {to_item}.{to_node}")
    positions = []
    if info is None:
        made.notes.append(
            f"no --sheet: the line assumes the fragment naming #{from_node}_Position and "
            f"#{to_node}_Position. For a node already on a sheet (a nozzle's, a valve's), pass "
            "--sheet pid/<sheet>.xml so the real PipingNodePosition ids are used"
        )
    for item, node in ((from_item, from_node), (to_item, to_node)):
        position = f"{node}_Position"
        if info is not None:
            sheet = info.sheet
            node_element = sheet.by_id.get(node)
            item_element = sheet.by_id.get(item)
            if item_element is None:
                raise FragmentError(f"{info.path}: no object {item}")
            if node_element is None:
                raise FragmentError(f"{info.path}: no node {node}")
            if item_element not in node_element.iterancestors():
                made.notes.append(f"{node} is not a node of {item}")
            users = [
                r.getparent().get("id") or short_class(r.getparent())
                for r, prop in sheet.incoming.get(node, [])
                if prop in ("SourceNode", "TargetNode")
                and short_class(r.getparent()) in ("Pipe", "DirectPipingConnection")
            ]
            if users:
                made.notes.append(
                    f"{node} is already connected by {', '.join(users)}: one node takes one pipe"
                )
            if node in info.positions:
                position = info.positions[node]
            else:
                made.notes.append(f"{node} has no PipingNodePosition in the sheet: draw one")
        positions.append(position)
    pipe = obj(
        object_id,
        "Plant/Piping.Pipe",
        ref("SourceItem", from_item),
        ref("SourceNode", from_node),
        ref("TargetItem", to_item),
        ref("TargetNode", to_node),
    )
    line_data = [ref("Source", positions[0]), ref("Target", positions[1])]
    inner = parse_points(bends) if bends else []
    if inner:
        line_data.append(points("InnerPoints", inner))
    line_data.append(stroke(PIPE_RGB, 0.5))
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            obj(
                f"{object_id}_Line",
                "Core/Diagram.Static",
                comps(
                    "Elements",
                    obj(f"{object_id}_LineShape", "Core/Diagram.ConnectorLine", *line_data),
                ),
            ),
        ),
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Connections"> of its PipingNetworkSegment, in flow '
            "order. As the segment's first pipe, the segment's SourceItem/SourceNode are "
            f"#{from_item}/#{from_node}; as its last, TargetItem/TargetNode are "
            f"#{to_item}/#{to_node}",
            to_text(pipe),
        )
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of the segment\'s RepresentationGroup. The '
            f"line runs from #{positions[0]} to #{positions[1]}"
            + (f" with bends at {'; '.join(_xy(p) for p in inner)}" if inner else " straight"),
            to_text(drawing),
        )
    )
    return made


def _segment(
    object_id: str,
    source: str | None,
    target: str | None,
    dn: str | None,
    standard: str,
    number: str | None,
    like: str | None,
    info: _SheetInfo | None,
) -> Fragment:
    (from_item, from_node), (to_item, to_node) = (
        _item_node(source, "--from"),
        _item_node(target, "--to"),
    )
    made = Fragment(
        "segment", object_id, f"PipingNetworkSegment {from_item}.{from_node} -> {to_item}.{to_node}"
    )
    data: list[etree._Element] = []
    if like:
        if info is None:
            raise FragmentError("--like needs --sheet (the segment to take the data from)")
        model = info.sheet.by_id.get(like)
        if model is None or short_class(model) != "PipingNetworkSegment":
            raise FragmentError(f"--like {like}: no PipingNetworkSegment with this id")
        data = [_copy.deepcopy(d) for d in model.findall("Data")]
        for element in data:
            element.tail = None
    if dn is not None or not like:
        size = dn_number(dn)
        std = _standard(size, standard, made.notes)
        dn_data = [
            string("NominalDiameterNumericalValueRepresentation", size),
            string("NominalDiameterRepresentation", f"DN {size}"),
            *([enum("NominalDiameterStandard", std)] if std else []),
            string("NominalDiameterTypeRepresentation", "DN"),
        ]
        names = {d.get("property") for d in dn_data}
        kept = [d for d in data if d.get("property") not in names | {"NominalDiameterStandard"}]
        data = kept + dn_data
    if number:
        data = [d for d in data if d.get("property") != "SegmentNumber"]
        data.append(string("SegmentNumber", number))
    data.sort(key=lambda d: d.get("property", ""))
    connections = comps("Connections")
    connections.append(etree.Comment(" pipe fragments, in flow order "))
    items = comps("Items")
    items.append(etree.Comment(" valves, reducers, and the tee it ends at (if any) "))
    segment = obj(
        object_id,
        "Plant/Piping.PipingNetworkSegment",
        connections,
        items,
        ref("SourceItem", from_item),
        ref("SourceNode", from_node),
        ref("TargetItem", to_item),
        ref("TargetNode", to_node),
        *data,
    )
    groups = comps("Groups")
    groups.append(etree.Comment(" the drawings of its pipes and items "))
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        groups,
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Segments"> of its PipingNetworkSystem. Its ends are '
            "where its first pipe starts and its last pipe ends; remove an empty Items",
            to_text(segment),
        )
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of the PipingNetworkSystem\'s RepresentationGroup',
            to_text(drawing),
        )
    )
    return made


def _label_class(element: etree._Element | None, attribute: str) -> str:
    if element is None:
        return LABEL_BY_ATTRIBUTE.get(attribute, "CustomLabel")
    kind = short_class(element)
    if kind.endswith("Nozzle"):
        return "NozzleStandardLabel"
    if kind in ("PipingNetworkSystem", "PipingNetworkSegment", "ProcessInstrumentationFunction"):
        return f"{kind}Label"
    if kind == "ActuatingSystem":
        return "ActuatingSystemNumberLabel"
    if kind.endswith("Reducer"):
        return "ReducerLabel"
    if "Safety" in kind:
        return "SafetyValveOrFittingLabel"
    if kind.endswith("Valve"):
        return "ValveLabel"
    if element.find("Data[@property='TagName']") is not None and attribute == "TagName":
        return "EquipmentTagNameLabel"
    return "CustomLabel"


def _rendered(info: _SheetInfo, object_id: str, attribute: str, shown: str) -> str | None:
    """The value the label shows, rendered as validate's label-stale rule renders it."""
    from pydexpi.pydexpi_classes.core.diagram import AttributeRepresentation, TextTemplate
    from pydexpi.toolkits.label_toolkit import render_text_template
    from pydexpi.toolkits.model_toolkit import get_instances_by_ids

    from chemeascode.domains.piping import dexpi_io

    try:
        model = dexpi_io.load(info.path.read_bytes(), strict=True).model
        found = get_instances_by_ids(model, [object_id]).get(object_id)
        if found is None:
            return None
        fragment = AttributeRepresentation(object=found, attributeName=attribute, type=shown)
        return render_text_template(TextTemplate(fragments=[fragment]))
    except Exception:  # noqa: BLE001 - any failure: fall back to the XML value
        return None


def _symbol_usage(drawing: etree._Element) -> etree._Element | None:
    """The drawing's own placed symbol (not one of a nested part's, like a nozzle)."""
    for usage in drawing.iter("Object"):
        if usage.get("type") != "Core/Diagram.ShapeUsage":
            continue
        groups = [
            a
            for a in usage.iterancestors("Object")
            if a.get("type") == "Core/Diagram.RepresentationGroup"
        ]
        if groups and groups[0] is drawing and point_xy_of(usage):
            return usage
    return None


def _symbol_at(drawing: etree._Element) -> tuple[float, float] | None:
    """Where the drawing's own symbol is (not one of a nested part's, like a nozzle)."""
    usage = _symbol_usage(drawing)
    return point_xy_of(usage) if usage is not None else None


def _symbol_turn(drawing: etree._Element) -> float | None:
    """The rotation of the drawing's own symbol, in degrees (0 when it has none)."""
    usage = _symbol_usage(drawing)
    if usage is None:
        return None
    try:
        return float(usage.findtext("Data[@property='Rotation']/Double") or 0.0)
    except ValueError:
        return 0.0


def point_xy_of(element: etree._Element) -> tuple[float, float] | None:
    value = element.find("Data[@property='Position']/AggregatedDataValue")
    return point_xy(value) if value is not None else None


def _label(
    object_id: str,
    for_id: str | None,
    attribute: str | None,
    at: str | None,
    info: _SheetInfo | None,
) -> Fragment:
    if not for_id or not attribute:
        raise FragmentError("label needs --for ID and --attribute NAME (e.g. TagName)")
    check_id(for_id, "--for")
    element = None
    drawn_by = None
    text = ""
    shown = "Value"
    made = Fragment("label", object_id, f"{attribute} of {for_id}")
    if info is not None:
        element = info.sheet.by_id.get(for_id)
        if element is None:
            raise FragmentError(f"{info.path}: no object {for_id}")
        quantity = element.find(
            f"Data[@property='{attribute}']/AggregatedDataValue"
            "[@type='Core/PhysicalQuantities.PhysicalQuantity']"
        )
        shown = "ValueAndUnits" if quantity is not None else "Value"
        rendered = _rendered(info, for_id, attribute, shown)
        if rendered is None:
            rendered = data_value(element, attribute)
            if rendered is None:
                made.notes.append(
                    f"{for_id} has no value for {attribute}: check the attribute name; the "
                    "cached Text is empty"
                )
        text = rendered or ""
        drawings = info.sheet.drawings.get(for_id, [])
        if drawings:
            drawn_by = drawings[0]
    else:
        made.notes.append(
            "without --sheet the cached Text is empty: set it to the value shown "
            "(cheme.label-stale says which)"
        )
    if at is not None:
        x, y = parse_pair(at, "--at")
    elif drawn_by is not None and _symbol_at(drawn_by):
        sx, sy = _symbol_at(drawn_by)
        x, y = sx, sy - 6.0
        made.notes.append(f"placed 6 mm above the symbol of {for_id}: move it with --at X,Y")
    else:
        raise FragmentError("--at X,Y is required (or --sheet with a drawn --for object)")
    label_class = _label_class(element, attribute)
    size = 4.5 if label_class == "EquipmentTagNameLabel" else 3.0
    template = obj(
        f"{object_id}_Template",
        "Core/Diagram.TextTemplate",
        comps(
            "Fragments",
            obj(
                f"{object_id}_Fragment",
                "Core/Diagram.AttributeRepresentation",
                ref("Object", for_id),
                string("AttributeName", attribute),
                enum("Type", f"Core/Diagram.AttributeRepresentationType.{shown}"),
            ),
        ),
    )
    label = obj(
        object_id,
        f"Plant/Diagram.{label_class}",
        comps(
            "Elements",
            obj(
                f"{object_id}_Text",
                "Core/Diagram.Text",
                comps("Template", template),
                enum("Alignment", "Core/Diagram.TextAlignment.CenterCenter"),
                color("Color", 0, 0, 0),
                string("Font", "Calibri"),
                point("Position", x, y),
                double("Rotation", 0.0),
                double("Size", size),
                string("Text", text),
            ),
        ),
    )
    made.summary += f" ({label_class}, {text!r}) at {fmt_num(x)},{fmt_num(y)}"
    made.parts.append(Part("CONCEPTUAL", "nothing: a label is drawing only"))
    where = 'into <Components property="Groups"> of the RepresentationGroup that draws '
    if drawn_by is not None and info is not None:
        where += f"{for_id}: {drawn_by.get('id')} ({info.sheet.where(drawn_by)})"
    else:
        where += f"{for_id} (References Represents #{for_id})"
    made.parts.append(Part("DRAWING", where, to_text(label)))
    return made


def make_fragment(
    kind: str,
    object_id: str | None,
    *,
    dn: str | None = None,
    standard: str = "Din2448",
    source: str | None = None,
    target: str | None = None,
    points: str | None = None,
    valve_class: str | None = None,
    at: str | None = None,
    rotation: float = 0.0,
    branch_dn: str | None = None,
    branch: str | None = None,
    for_id: str | None = None,
    attribute: str | None = None,
    tag: str | None = None,
    number: str | None = None,
    like: str | None = None,
    sheet: Path | None = None,
    scale: str | None = None,
    **options,
) -> Fragment:
    """The fragment of *kind* for a new object *object_id*.

    The kinds equipment, nozzle, instrument, signal, offpage, note and shape take further
    *options*; see ``chemeascode.domains.piping.authoring.fragment_items``.
    """
    if kind not in KINDS:
        raise FragmentError(f"unknown kind {kind!r}: one of {', '.join(KINDS)}")
    if object_id is None and kind != "shape":
        raise FragmentError(f"{kind} needs --id ID (the new object's id)")
    if object_id is not None:
        check_id(object_id, "--id")
    if not math.isfinite(rotation):
        raise FragmentError(f"--rotation: expected degrees, got {rotation!r}")
    info = _SheetInfo(sheet) if sheet is not None else None
    if info is not None and object_id is not None:
        clash = [
            i
            for i in (object_id, f"{object_id}_Drawing", f"{object_id}_N1")
            if i in info.sheet.by_id
        ]
        if clash:
            raise FragmentError(f"--id {object_id}: {clash[0]} exists in {sheet}; choose another")
    valve_class = options.pop("item_class", None) or valve_class
    if kind in DRAFTING_KINDS:
        from chemeascode.domains.piping.authoring import fragment_items

        return fragment_items.make(
            kind,
            object_id,
            info,
            dn=dn,
            standard=standard,
            source=source,
            target=target,
            points=points,
            item_class=valve_class,
            at=at,
            rotation=rotation,
            tag=tag,
            number=number,
            scale=scale,
            **options,
        )
    if options:
        raise FragmentError(
            f"{kind} takes no {', '.join('--' + o.replace('_', '-') for o in options)}"
        )
    if kind == "node":
        return _node(object_id, dn_number(dn), standard, at)
    if kind == "valve" and scale:
        sx, sy = parse_scale(scale)
        if abs(sx - sy) > 1e-9:
            raise FragmentError(
                f"--scale {scale}: a valve symbol scales evenly; give one number (S)"
            )
    if kind == "valve":
        return _valve(
            object_id,
            valve_class or "GlobeValve",
            dn_number(dn),
            standard,
            at,
            rotation,
            tag,
            info,
            parse_scale(scale)[0] if scale else None,
        )
    if kind == "tee":
        size = dn_number(dn)
        return _tee(
            object_id,
            size,
            dn_number(branch_dn) if branch_dn else size,
            standard,
            at,
            rotation,
            branch,
            tag,
            info,
        )
    if kind == "pipe":
        return _pipe(object_id, source, target, points, info)
    if kind == "segment":
        return _segment(object_id, source, target, dn, standard, number, like, info)
    return _label(object_id, for_id, attribute, at, info)


def parse_scale(text: str) -> tuple[float, float]:
    """``--scale 0.5`` or ``--scale 1,1.4`` (ScaleX, ScaleY)."""
    try:
        values = [float(v) for v in text.split(",")]
    except ValueError as failure:
        raise FragmentError(f"--scale: expected S or SX,SY, got {text!r}") from failure
    if len(values) == 1:
        values *= 2
    if len(values) != 2 or not all(math.isfinite(v) and v > 0 for v in values):
        raise FragmentError(f"--scale: expected one or two positive numbers, got {text!r}")
    return values[0], values[1]
