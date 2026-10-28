"""Builders for equipment, instruments, off-page connectors and notes.

Each returns a :class:`~chemeascode.domains.piping.authoring.fragment.Fragment` (CONCEPTUAL and
DRAWING parts, each saying where it goes), the same form ``cheme fragment`` prints, so a CLI
kind and the Python API (``chemeascode.domains.piping.authoring``) can share one implementation.
Ids derive from the object id:

- equipment ``ID``: nozzles ``ID_<name>`` with node ``ID_<name>_Node``; drawing ``ID_Drawing``
  with ``ID_Symbol``/``ID_SymbolShape``, nozzle drawings ``ID_<name>_Drawing`` and the tag label
  ``ID_TagLabel``;
- instrument ``ID`` (default ``Inst_<tag without hyphens>``): ``ID_Sensor`` (signal generating
  function), ``ID_MeasuringLine``; with a controlled valve ``ID_Actuating``, ``ID_Signal``,
  ``ID_System`` (actuating system), ``ID_Actuator``, ``ID_ValveRef``; drawing ``ID_Drawing``
  with ``ID_Bubble``, ``ID_Label``, ``ID_SensePosition``, ``ID_BubblePosition``;
- off-page connector ``ID``: node ``ID_N1``; drawing ``ID_Drawing``;
- note ``ID``: a Static with ``ID_Text``, owned by no object.
"""

from __future__ import annotations

import math
import re

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    check_id,
    color,
    comps,
    double,
    enum,
    fmt_num,
    obj,
    point,
    points,
    ref,
    rotate,
    string,
    to_text,
)
from chemeascode.domains.piping.authoring.fragment import (
    Fragment,
    FragmentError,
    Part,
    _label,
    _standard,
    node_position,
    piping_node,
    shape_usage,
)
from chemeascode.domains.piping.drawing import _CAP, segment_box_distance, text_width

EQUIPMENT_RGB = (128, 0, 0)
INSTRUMENT_RGB = (0, 128, 0)
SIGNAL_RGB = (0, 0, 0)
#: Off-page connector arrows at the reference P&ID's scale.
OFFPAGE_SCALE = 0.7
#: The inside of the template's A3 border (sheet mm): default notes are kept within it.
FRAME = (4.0, 4.0, 416.0, 293.0)


def note_in_frame(
    note: str, at: tuple[float, float], align: str, connector: tuple[float, float]
) -> tuple[tuple[float, float], str]:
    """Where an off-page note goes: at *at* (beyond the arrow), or, when that would run out of
    the frame (a connector at the sheet edge), centred above the *connector*, inside it."""
    if align == "CenterCenter":
        return at, align
    width = text_width(note, 2.5)
    left = at[0] - (width if align == "RightCenter" else 0.0)
    right = at[0] + (width if align == "LeftCenter" else 0.0)
    if FRAME[0] <= left and right <= FRAME[2]:
        return at, align
    half = width / 2
    cx = min(max(connector[0], FRAME[0] + half + 1.0), FRAME[2] - half - 1.0)
    return (cx, connector[1] - 5.0), "CenterCenter"


OFFPAGE_SHAPES = {
    "in": ("FlowInPipeOffPageConnector", "ARROW_FOR_INLET_OF_ESSENTIAL_SUBSTANCES_SHAPE", "Shape2"),
    "out": (
        "FlowOutPipeOffPageConnector",
        "ARROW_FOR_OUTLET_OF_ESSENTIAL_SUBSTANCES_SHAPE",
        "Shape14",
    ),
}
#: Bubble shape, its catalogue id and half width and height (mm, at scale 1). Both reference
#: bubbles are 13.5 x 7.5 mm: the field bubble's sides are arcs of radius 3.75 around x = +-3.
BUBBLE_SHAPES = {
    "central": ("INSTRUMENTATION_BUBBLE_SHAPE_CENTRAL", "Shape17", 6.75, 3.75),
    "field": ("INSTRUMENTATION_BUBBLE_SHAPE_FIELD", "Shape16", 6.75, 3.75),
}
ACTUATOR_SHAPE = ("CONTROLLED_ACTUATOR_SHAPE", "Shape1")
#: The text size of an equipment tag label (as ``_label`` writes it).
EQUIPMENT_LABEL_SIZE = 4.5
#: CONTROLLED_ACTUATOR_SHAPE (13.5 + 4.5 mm long) at scale 0.4, drawn up from the valve centre.
ACTUATOR_SCALE = 0.4
ACTUATOR_REACH = 7.2

_TAG = re.compile(r"^([A-Za-z]+)-?(\d+)(.*)$")
_INSTRUMENT_TAG = re.compile(r"^([A-Za-z]+)-?([0-9][0-9A-Za-z.]*)$")


def dashed_stroke(rgb: tuple[int, int, int], width: float, dash: str = "Dash") -> etree._Element:
    value = etree.Element("AggregatedDataValue", type="Core/Diagram.Stroke")
    value.extend(
        [
            color("Color", *rgb),
            enum("DashStyle", f"Core/Diagram.DashStyle.{dash}"),
            double("Width", width),
        ]
    )
    element = etree.Element("Data", property="Stroke")
    element.append(value)
    return element


def text_element(
    text_id: str,
    text: str,
    x: float,
    y: float,
    *,
    size: float = 2.5,
    align: str = "CenterCenter",
    shows: list[tuple[str, str]] | None = None,
) -> etree._Element:
    """A ``Core/Diagram.Text``; *shows* (object id, attribute) pairs make its template."""
    children: list[etree._Element] = []
    if shows:
        fragments = [
            obj(
                f"{text_id}_Fragment{i}" if len(shows) > 1 else f"{text_id}_Fragment",
                "Core/Diagram.AttributeRepresentation",
                ref("Object", object_id),
                string("AttributeName", attribute),
                enum("Type", "Core/Diagram.AttributeRepresentationType.Value"),
            )
            for i, (object_id, attribute) in enumerate(shows, 1)
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
    children += [
        enum("Alignment", f"Core/Diagram.TextAlignment.{align}"),
        color("Color", 0, 0, 0),
        string("Font", "Calibri"),
        point("Position", x, y),
        double("Rotation", 0.0),
        double("Size", size),
        string("Text", text),
    ]
    return obj(text_id, "Core/Diagram.Text", *children)


def _static(static_id: str, *elements: etree._Element) -> etree._Element:
    return obj(static_id, "Core/Diagram.Static", comps("Elements", *elements))


def _polyline(
    line_id: str, xy: list[tuple[float, float]], stroke: etree._Element
) -> etree._Element:
    return obj(line_id, "Core/Diagram.PolyLine", points("Points", xy), stroke)


def _xy(xy: tuple[float, float]) -> str:
    return f"{fmt_num(xy[0])},{fmt_num(xy[1])}"


# -- equipment ----------------------------------------------------------------------------------


def tag_parts(tag: str) -> list[etree._Element]:
    """``TagName`` and, when the tag reads ``P-4711A``, its prefix, sequence number and suffix."""
    data = [string("TagName", tag)]
    match = _TAG.match(tag)
    if match:
        prefix, sequence, suffix = match.groups()
        data += [
            string("TagNamePrefix", prefix),
            string("TagNameSequenceNumber", sequence),
        ]
        if suffix:
            data.append(string("TagNameSuffix", suffix))
    return data


def equipment_class(cls: str) -> str:
    """The DEXPI type of equipment class *cls* (``CentrifugalPump`` or a full type)."""
    if "/" in cls:
        return cls
    from pydexpi.pydexpi_classes.plant import processEquipment

    found = getattr(processEquipment, cls, None)
    tagged = getattr(processEquipment, "TaggedPlantItem", None)
    if not isinstance(found, type) or (tagged is not None and not issubclass(found, tagged)):
        raise FragmentError(
            f"equipment class {cls!r} is not a DEXPI process equipment class (e.g. Tank, "
            "Vessel, CentrifugalPump, CentrifugalCompressor, TubularHeatExchanger, ProcessColumn)"
        )
    return f"Plant/ProcessEquipment.{cls}"


#: How far a pipe is taken to run straight out of a nozzle when placing a tag label (mm).
NOZZLE_REACH = 40.0
#: The least distance kept between a tag label and a nozzle's pipe (mm).
LABEL_CLEARANCE = 1.0


def nozzle_direction(dx: float, dy: float, half: tuple[float, float]) -> tuple[float, float]:
    """The sheet axis a nozzle at offset (dx, dy) from the symbol centre points along, relative
    to the symbol's half width and height (a side nozzle high on a column points sideways)."""
    hx, hy = half if half[0] > 1e-9 and half[1] > 1e-9 else (1.0, 1.0)
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return (0.0, 1.0)
    if abs(dx) / hx >= abs(dy) / hy:
        return (1.0 if dx > 0 else -1.0, 0.0)
    return (0.0, 1.0 if dy > 0 else -1.0)


def tag_label_spot(
    centre: tuple[float, float],
    box: tuple[float, float, float, float],
    nozzles: list[tuple[tuple[float, float], tuple[float, float]]],
    text: str,
    size: float,
    offset: float,
) -> tuple[tuple[float, float], bool]:
    """Where an equipment tag label (centred text) goes, and whether that spot is clear.

    *box*: the symbol's box as offsets from *centre*; *nozzles*: each nozzle's point (offset from
    *centre*) and the direction its pipe leaves in. The first spot whose label box keeps
    :data:`LABEL_CLEARANCE` from every nozzle's pipe (taken :data:`NOZZLE_REACH` straight out)
    wins: below the symbol (*offset* from its bottom edge to the label's centre), above it, to
    the right, to the left, then the four corners. When none is clear: below.
    """
    x, y = centre
    x0, y0, x1, y1 = box
    width, height = text_width(text, size), size * _CAP
    gap = max(offset - height / 2, 0.5)
    side = gap + width / 2
    below, above = y1 + offset, y0 - offset
    spots = [
        (0.0, below),
        (0.0, above),
        (x1 + side, 0.0),
        (x0 - side, 0.0),
        (x1 + side, below),
        (x0 - side, below),
        (x1 + side, above),
        (x0 - side, above),
    ]
    rays = [
        ((x + dx, y + dy), (x + dx + NOZZLE_REACH * ux, y + dy + NOZZLE_REACH * uy))
        for (dx, dy), (ux, uy) in nozzles
    ]
    for sx, sy in spots:
        cx, cy = x + sx, y + sy
        label = (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)
        if all(segment_box_distance(a, b, label) >= LABEL_CLEARANCE for a, b in rays):
            return (cx, cy), True
    return (x, y + below), False


def equipment_fragment(
    object_id: str,
    cls: str,
    tag: str,
    shape_id: str,
    at: tuple[float, float],
    nozzles: list[tuple[str, tuple[float, float], str | None]],
    *,
    rotation: float = 0.0,
    scale: float | tuple[float, float] = 1.0,
    label_at: tuple[float, float] | None = None,
    standard: str = "Din2448",
    extent: tuple[float, float, float, float] | None = None,
    markers: list[tuple[str, float, float, bool]] = (),  # type: ignore[assignment]
) -> Fragment:
    """Equipment *object_id* with nozzles ``(name, (dx, dy) from at, DN)``, drawn as *shape_id*.

    Nozzle offsets are sheet mm from *at* (Y down), not rotated with the symbol. The tag label
    goes to *label_at*, default 4 mm below the symbol (*extent*: the shape's box at scale 1), or,
    when a nozzle's pipe would cross it there, above it, beside it or at a corner
    (:func:`tag_label_spot`). *scale* is one factor or (ScaleX, ScaleY). *markers* are
    ``(shape id, dy, ScaleY, mirrored)``: shapes drawn on the symbol at *dy* from its centre
    (rotated with it), with the symbol's ScaleX, as ``cheme fragment equipment --marker`` draws
    packed beds and trays.
    """
    check_id(object_id, "equipment id")
    sx, sy = (scale, scale) if isinstance(scale, int | float) else scale
    if min(sx, sy) <= 0:
        raise FragmentError(f"equipment {object_id}: scale must be positive, got {scale!r}")
    x, y = at
    made = Fragment("equipment", object_id, f"{cls} {tag} at {_xy(at)}")
    nozzle_objects, nozzle_drawings = [], []
    for name, (dx, dy), dn in nozzles:
        nozzle_id = check_id(f"{object_id}_{name}", "nozzle id")
        node_id = f"{nozzle_id}_Node"
        nodes = []
        if dn is not None:
            nodes.append(piping_node(node_id, dn, _standard(dn, standard, made.notes)))
        else:
            nodes.append(obj(node_id, "Plant/Piping.PipingNode"))
        nozzle_objects.append(
            obj(
                nozzle_id,
                "Plant/ProcessEquipment.ProcessNozzle",
                comps("Nodes", *nodes),
                string("SubTagName", name),
            )
        )
        nozzle_drawings.append(
            obj(
                f"{nozzle_id}_Drawing",
                "Core/Diagram.RepresentationGroup",
                comps("Groups", node_position(node_id, x + dx, y + dy)),
                ref("Represents", nozzle_id),
            )
        )
    children = [comps("Nozzles", *nozzle_objects)] if nozzle_objects else []
    equipment = obj(object_id, equipment_class(cls), *children, *tag_parts(tag))
    if label_at is None:
        x0, y0, x1, y1 = extent or (-7.5, -7.5, 7.5, 7.5)
        x0, x1, y0, y1 = x0 * sx, x1 * sx, y0 * sy, y1 * sy
        corners = [rotate(cx, cy, rotation) for cx in (x0, x1) for cy in (y0, y1)]
        box = (
            min(c[0] for c in corners),
            min(c[1] for c in corners),
            max(c[0] for c in corners),
            max(c[1] for c in corners),
        )
        half = (max(-box[0], box[2]), max(-box[1], box[3]))
        label_at, clear = tag_label_spot(
            at,
            box,
            [(offset, nozzle_direction(*offset, half)) for _, offset, _ in nozzles],
            tag,
            EQUIPMENT_LABEL_SIZE,
            4.0,
        )
        if not clear:
            made.notes.append(
                f"tag label of {tag}: every spot around the symbol is crossed by a nozzle's "
                "pipe; it is below the symbol, pass label_at=(x, y)"
            )
    marker_usages = []
    for number, (marker_shape, dy, marker_sy, mirrored) in enumerate(markers, 1):
        if marker_sy <= 0:
            raise FragmentError(f"equipment {object_id}: marker {number} ScaleY must be positive")
        mdx, mdy = rotate(0.0, dy, rotation)
        marker_usages.append(
            shape_usage(
                f"{object_id}_Marker{number}",
                marker_shape,
                x + mdx,
                y + mdy,
                rotation,
                (sx, marker_sy),
                mirrored,
            )
        )
    label = _label(f"{object_id}_TagLabel", object_id, "TagName", _xy(label_at), None)
    label_element = etree.fromstring(label.part("DRAWING").xml)
    cached = label_element.find(".//Data[@property='Text']/String")
    if cached is not None:
        cached.text = tag
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps(
            "Groups",
            _static(
                f"{object_id}_Symbol",
                shape_usage(f"{object_id}_SymbolShape", shape_id, x, y, rotation, (sx, sy)),
                *marker_usages,
            ),
            *nozzle_drawings,
            label_element,
        ),
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="TaggedPlantItems"> of the PlantModel',
            to_text(equipment),
        )
    )
    nozzle_text = "; ".join(
        f"#{object_id}_{name}_Node_Position at {_xy((x + dx, y + dy))}"
        for name, (dx, dy), _ in nozzles
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of the Diagram. Pipes attach to the nozzle '
            f"node positions: {nozzle_text or 'none (no nozzles)'}",
            to_text(drawing),
        )
    )
    return made


# -- instruments --------------------------------------------------------------------------------


def instrument_parts(tag: str) -> tuple[str, str, str]:
    """``PIC-4101`` -> category ``P``, functions ``IC``, number ``4101``."""
    match = _INSTRUMENT_TAG.match(tag.strip())
    if not match:
        raise FragmentError(
            f"instrument tag {tag!r}: expected letters, a hyphen and a number, e.g. PIC-4101"
        )
    letters, num = match.groups()
    return letters[0].upper(), letters[1:].upper(), num


def _edge(
    centre: tuple[float, float], half: tuple[float, float], towards: tuple[float, float]
) -> tuple[str, tuple[float, float]]:
    """The bubble's connection point (top, bottom, left, right) nearest to *towards*."""
    x, y = centre
    hx, hy = half
    candidates = {
        "top": (x, y - hy),
        "bottom": (x, y + hy),
        "left": (x - hx, y),
        "right": (x + hx, y),
    }
    side = min(candidates, key=lambda k: math.dist(candidates[k], towards))
    return side, candidates[side]


def _orthogonal(start: tuple[float, float], end: tuple[float, float]) -> list[tuple[float, float]]:
    if math.isclose(start[0], end[0]) or math.isclose(start[1], end[1]):
        return [start, end]
    return [start, (end[0], start[1]), end]


def instrument_fragment(
    object_id: str,
    tag: str,
    at: tuple[float, float],
    *,
    sensing: str | None = None,
    sensing_at: tuple[float, float] | None = None,
    location: str = "central",
    bubble_shape: str | None = None,
    signal_valve: str | None = None,
    valve_at: tuple[float, float] | None = None,
    valve_tag: str | None = None,
    actuator_shape: str | None = None,
    signal_function: str | None = None,
    function_at: tuple[float, float] | None = None,
    signal_points: list[tuple[float, float]] | None = None,
    fail_action: str | None = None,
) -> Fragment:
    """An instrument function *tag* with its bubble at *at*.

    *sensing* (an object id) and *sensing_at* (where the measuring line starts) add the sensor
    and the measuring line. *signal_valve* (a valve id drawn at *valve_at*) adds an actuating
    function, a signal and an actuating system with a controlled actuator on that valve;
    *signal_function* (another instrument function's id, its bubble at *function_at*) a signal
    to it (a cascade). *signal_points* are the signal line's bends.
    """
    check_id(object_id, "instrument id")
    if location not in BUBBLE_SHAPES:
        raise FragmentError(f"location {location!r}: one of {', '.join(BUBBLE_SHAPES)}")
    if signal_valve and signal_function:
        raise FragmentError("signal to a valve or to an instrument function, not both")
    category, functions, num = instrument_parts(tag)
    made = Fragment("instrument", object_id, f"{tag} at {_xy(at)}")
    _, default_shape, half_x, half_y = BUBBLE_SHAPES[location]
    shape_id = bubble_shape or default_shape
    pif: list[etree._Element] = []
    signals: list[etree._Element] = []
    groups: list[etree._Element] = [
        _static(f"{object_id}_Bubble", shape_usage(f"{object_id}_BubbleShape", shape_id, *at, 0, 1))
    ]
    positions: list[etree._Element] = []
    if sensing:
        check_id(sensing, "sensing")
        sensor = obj(
            f"{object_id}_Sensor",
            "Plant/Instrumentation.ProcessSignalGeneratingFunction",
            ref("SensingLocation", sensing),
            string("ProcessSignalGeneratingFunctionNumber", f"{category}T{num}"),
        )
        pif.append(comps("ProcessSignalGeneratingFunctions", sensor))
        signals.append(
            obj(
                f"{object_id}_MeasuringLine",
                "Plant/Instrumentation.MeasuringLineFunction",
                ref("Source", f"{object_id}_Sensor"),
                ref("Target", object_id),
            )
        )
        if sensing_at is None:
            made.notes.append(f"no sensing point for {sensing}: the measuring line is not drawn")
        else:
            _, bubble_end = _edge(at, (half_x, half_y), sensing_at)
            positions += [
                obj(
                    f"{object_id}_SensePosition",
                    "Plant/Diagram.InstrumentationNodePosition",
                    point("Position", *sensing_at),
                ),
                obj(
                    f"{object_id}_BubblePosition",
                    "Plant/Diagram.InstrumentationNodePosition",
                    point("Position", *bubble_end),
                ),
            ]
            line = obj(
                f"{object_id}_MeasuringLine_Shape",
                "Core/Diagram.ConnectorLine",
                ref("Source", f"{object_id}_SensePosition"),
                ref("Target", f"{object_id}_BubblePosition"),
                dashed_stroke(INSTRUMENT_RGB, 0.25, "Solid"),
            )
            groups.append(
                obj(
                    f"{object_id}_MeasuringLine_Drawing",
                    "Core/Diagram.RepresentationGroup",
                    comps("Groups", _static(f"{object_id}_MeasuringLine_Line", line)),
                    ref("Represents", f"{object_id}_MeasuringLine"),
                )
            )
    systems: list[etree._Element] = []
    system_drawings: list[etree._Element] = []
    target_at: tuple[float, float] | None = None
    if signal_valve:
        check_id(signal_valve, "signal_to")
        number_text = valve_tag or f"{category}V{num}"
        pif.append(
            comps(
                "ActuatingFunctions",
                obj(
                    f"{object_id}_Actuating",
                    "Plant/Instrumentation.ActuatingFunction",
                    string("ActuatingFunctionNumber", number_text),
                    ref("Systems", f"{object_id}_System"),
                ),
            )
        )
        signals.append(
            obj(
                f"{object_id}_Signal",
                "Plant/Instrumentation.SignalConveyingFunction",
                ref("Source", object_id),
                ref("Target", f"{object_id}_Actuating"),
            )
        )
        actuator_data = [string("DeviceTypeName", "general")]
        if fail_action:
            names = {"FC": "FailClose", "FO": "FailOpen", "FL": "FailRetainPosition"}
            value = names.get(fail_action.upper(), fail_action)
            if value not in names.values():
                raise FragmentError(f"fail_action {fail_action!r}: FC, FO or FL")
            actuator_data.append(
                enum("FailAction", f"Plant/Enumerations.FailActionClassification.{value}")
            )
            actuator_data.append(
                string(
                    "FailActionRepresentation",
                    {"FailClose": "F.C.", "FailOpen": "F.O.", "FailRetainPosition": "F.L."}[value],
                )
            )
        systems.append(
            obj(
                f"{object_id}_System",
                "Plant/Instrumentation.ActuatingSystem",
                comps(
                    "ControlledActuator",
                    obj(
                        f"{object_id}_Actuator",
                        "Plant/Instrumentation.ControlledActuator",
                        *actuator_data,
                    ),
                ),
                comps(
                    "OperatedValveReference",
                    obj(
                        f"{object_id}_ValveRef",
                        "Plant/Instrumentation.OperatedValveReference",
                        ref("Valve", signal_valve),
                    ),
                ),
                string("ActuatingSystemNumber", number_text),
            )
        )
        if valve_at is not None:
            vx, vy = valve_at
            system_drawings.append(
                obj(
                    f"{object_id}_Actuator_Drawing",
                    "Core/Diagram.RepresentationGroup",
                    comps(
                        "Groups",
                        _static(
                            f"{object_id}_Actuator_Symbol",
                            shape_usage(
                                f"{object_id}_Actuator_SymbolShape",
                                actuator_shape or ACTUATOR_SHAPE[1],
                                vx,
                                vy,
                                270.0,
                                ACTUATOR_SCALE,
                            ),
                        ),
                    ),
                    ref("Represents", f"{object_id}_Actuator"),
                )
            )
            target_at = (vx, vy - ACTUATOR_REACH)
        else:
            made.notes.append(f"{signal_valve} is not drawn: no actuator symbol, no signal line")
    if signal_function:
        check_id(signal_function, "signal_to")
        signals.append(
            obj(
                f"{object_id}_Signal",
                "Plant/Instrumentation.SignalConveyingFunction",
                ref("Source", object_id),
                ref("Target", signal_function),
            )
        )
        if function_at is not None:
            target_at = function_at
    if target_at is not None:
        bends = list(signal_points or [])
        first = bends[0] if bends else target_at
        _, start = _edge(at, (half_x, half_y), first)
        if signal_function and function_at is not None:
            _, target_at = _edge(function_at, (half_x, half_y), bends[-1] if bends else start)
        route = [start, *bends, target_at] if bends else _orthogonal(start, target_at)
        groups.append(
            obj(
                f"{object_id}_Signal_Drawing",
                "Core/Diagram.RepresentationGroup",
                comps(
                    "Groups",
                    _static(
                        f"{object_id}_Signal_Line",
                        _polyline(
                            f"{object_id}_Signal_Shape", route, dashed_stroke(SIGNAL_RGB, 0.25)
                        ),
                    ),
                ),
                ref("Represents", f"{object_id}_Signal"),
            )
        )
    if signals:
        pif.append(comps("SignalConveyingFunctions", *signals))
    location_value = "CentralLocation" if location == "central" else "Field"
    function = obj(
        object_id,
        "Plant/Instrumentation.ProcessInstrumentationFunction",
        *pif,
        enum("Location", f"Plant/Enumerations.LocationClassification.{location_value}"),
        string("ProcessInstrumentationFunctionCategory", category),
        string("ProcessInstrumentationFunctionNumber", num),
        string("ProcessInstrumentationFunctions", functions),
    )
    x, y = at
    label = obj(
        f"{object_id}_Label",
        "Plant/Diagram.ProcessInstrumentationFunctionLabel",
        comps(
            "Elements",
            text_element(
                f"{object_id}_Letters",
                category + functions,
                x,
                y - 1.4,
                size=2.5,
                shows=[
                    (object_id, "ProcessInstrumentationFunctionCategory"),
                    (object_id, "ProcessInstrumentationFunctions"),
                ],
            ),
            text_element(
                f"{object_id}_Number",
                num,
                x,
                y + 1.6,
                size=2.5,
                shows=[(object_id, "ProcessInstrumentationFunctionNumber")],
            ),
        ),
    )
    groups.append(label)
    drawing_children = [comps("Groups", *groups)]
    if positions:
        drawing_children.append(comps("NodePositions", *positions))
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        *drawing_children,
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="ProcessInstrumentationFunctions"> of the PlantModel',
            to_text(function),
        )
    )
    made.parts.append(
        Part("DRAWING", 'into <Components property="Groups"> of the Diagram', to_text(drawing))
    )
    for system in systems:
        made.parts.append(
            Part(
                "SYSTEM",
                'into <Components property="ActuatingSystems"> of the PlantModel',
                to_text(system),
            )
        )
    for system_drawing in system_drawings:
        made.parts.append(
            Part(
                "SYSTEM DRAWING",
                'into <Components property="Groups"> of the Diagram',
                to_text(system_drawing),
            )
        )
    return made


# -- off-page connectors and notes --------------------------------------------------------------


def offpage_fragment(
    object_id: str,
    direction: str,
    at: tuple[float, float],
    *,
    rotation: float = 0.0,
    shape_id: str | None = None,
    note: str | None = None,
    note_at: tuple[float, float] | None = None,
) -> Fragment:
    """A flow-in (``in``) or flow-out (``out``) off-page connector; its node sits at *at*.

    *rotation* is the flow direction (0: left to right): an inlet arrow ends at the node, an
    outlet arrow starts there. *note* (e.g. ``from P-02``) is drawn at *note_at*, by default
    beyond the arrow.
    """
    check_id(object_id, "off-page id")
    if direction not in OFFPAGE_SHAPES:
        raise FragmentError(f"off-page direction {direction!r}: in or out")
    cls, _, default_shape = OFFPAGE_SHAPES[direction]
    made = Fragment("offpage", object_id, f"{cls} at {_xy(at)}, flow {fmt_num(rotation)} deg")
    node_id = f"{object_id}_N1"
    connector = obj(
        object_id,
        f"Plant/Piping.{cls}",
        comps("Nodes", obj(node_id, "Plant/Piping.PipingNode")),
    )
    x, y = at
    groups = [
        node_position(node_id, x, y),
        _static(
            f"{object_id}_Symbol",
            shape_usage(
                f"{object_id}_SymbolShape", shape_id or default_shape, x, y, rotation, OFFPAGE_SCALE
            ),
        ),
    ]
    if note:
        if note_at is None:
            reach = 10.0 * OFFPAGE_SCALE + 2.0
            dx, dy = rotate(-reach if direction == "in" else reach, 0.0, rotation)
            note_at = (x + dx, y + dy)
            align = "RightCenter" if dx < -0.5 else "LeftCenter" if dx > 0.5 else "CenterCenter"
            note_at, align = note_in_frame(note, note_at, align, (x, y))
        else:
            align = "CenterCenter"
        groups.append(
            _static(
                f"{object_id}_Note",
                text_element(f"{object_id}_NoteText", note, *note_at, size=2.5, align=align),
            )
        )
    drawing = obj(
        f"{object_id}_Drawing",
        "Core/Diagram.RepresentationGroup",
        comps("Groups", *groups),
        ref("Represents", object_id),
    )
    made.parts.append(
        Part(
            "CONCEPTUAL",
            'into <Components property="Items"> of the segment that starts (in) or ends (out) at '
            f"it: that segment's SourceItem/TargetItem #{object_id}, node #{node_id}",
            to_text(connector),
        )
    )
    made.parts.append(
        Part(
            "DRAWING",
            'into <Components property="Groups"> of that segment\'s RepresentationGroup; the '
            f"line attaches at #{node_id}_Position ({_xy(at)})",
            to_text(drawing),
        )
    )
    return made


def note_fragment(
    object_id: str,
    text: str,
    at: tuple[float, float],
    *,
    size: float = 2.5,
    align: str = "LeftCenter",
) -> Fragment:
    """Free text on the sheet, owned by no object (no label rule follows it)."""
    check_id(object_id, "note id")
    made = Fragment("note", object_id, f"{text!r} at {_xy(at)}")
    note = _static(object_id, text_element(f"{object_id}_Text", text, *at, size=size, align=align))
    made.parts.append(Part("CONCEPTUAL", "nothing: a note is drawing only"))
    made.parts.append(
        Part("DRAWING", 'into <Components property="Groups"> of the Diagram', to_text(note))
    )
    return made
