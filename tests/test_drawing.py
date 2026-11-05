"""Drawing-geometry lint (``chemeascode.domains.piping.drawing``): rules on synthetic sheets and the
reference."""

import os
import time
from pathlib import Path

import pytest
from lxml import etree

from chemeascode.domains.piping.drawing import (
    Context,
    DrawingFinding,
    lint_drawing,
    parse_transform,
    read_drawing,
    text_box,
)
from chemeascode.domains.piping.render import Crop
from chemeascode.project.validate import validate_pid
from tests.conftest import REFERENCE

PIPE = "Plant/Piping.Pipe"
SYSTEM = "Plant/Piping.PipingNetworkSystem"
INSTRUMENT = "Plant/Instrumentation.ProcessInstrumentationFunction"
TANK = "Plant/ProcessEquipment.Tank"


def _svg(*parts: str) -> etree._Element:
    return etree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" width="420" height="297" '
        f'viewBox="0 0 420 297"><g class="diagram">{"".join(parts)}</g></svg>'
    )


def _polyline(points: str, dashed: bool = False) -> str:
    dash = ' stroke-dasharray="2,0.4"' if dashed else ""
    return f'<polyline points="{points}" fill="none" stroke="black" stroke-width="0.5"{dash}/>'


def _text(x, y, text, baseline="middle", anchor="start", size=2.0, transform="") -> str:
    turn = f' transform="{transform}"' if transform else ""
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" dominant-baseline="{baseline}" '
        f'font-size="{size}"{turn}>{text}</text>'
    )


def _line(system: str, pipes: dict[str, str], *labels: str) -> str:
    drawn = "".join(
        f'<g id="{p}" class="representation-group"><g class="static">{_polyline(pts)}</g></g>'
        for p, pts in pipes.items()
    )
    texts = f'<g class="pipingnetworksystemlabel">{"".join(labels)}</g>' if labels else ""
    return f'<g id="{system}" class="representation-group">{drawn}{texts}</g>'


def _bubble(object_id: str, x: float, y: float, *notes: str) -> str:
    shape = (
        f'<g class="static"><g><g id="BUBBLE" transform="translate({x},{y})">'
        '<ellipse cx="0" cy="0" rx="3.75" ry="3.75" fill="none" stroke="green"/></g></g></g>'
    )
    label = (
        f'<g class="processinstrumentationfunctionlabel">{_text(x, y, "TI", anchor="middle")}</g>'
    )
    static = f'<g class="static">{"".join(notes)}</g>' if notes else ""
    return f'<g id="{object_id}" class="representation-group">{shape}{label}{static}</g>'


def _tank(object_id: str, x0: float, y0: float, x1: float, y1: float) -> str:
    return (
        f'<g id="{object_id}" class="representation-group"><g class="static"><g>'
        f'<g id="TANK_SHAPE" transform="translate({x0},{y0})">'
        f'<polyline points="0,0 {x1 - x0},0 {x1 - x0},{y1 - y0} 0,{y1 - y0} 0,0" fill="none" '
        'stroke="red"/></g></g></g></g>'
    )


def _context(**kinds: str) -> Context:
    return Context(kinds={**kinds}, names={})


def _lint(svg: etree._Element, context: Context):
    return lint_drawing(read_drawing(svg, context.kinds), context)


def _rules(found) -> list[str]:
    return sorted(f.rule.removeprefix("cheme.") for f in found)


# -- text extents ---------------------------------------------------------------------------


def test_text_extents_follow_anchor_and_baseline():
    start = text_box(100, 50, "DN 80", 2.0, "start", "middle")
    middle = text_box(100, 50, "DN 80", 2.0, "middle", "middle")
    end = text_box(100, 50, "DN 80", 2.0, "end", "middle")
    width = start[2] - start[0]
    assert 5 < width < 7
    assert start[0] == 100 and end[2] == 100
    assert middle[0] == pytest.approx(100 - width / 2)
    # text-bottom: y is the bottom of the em box, the glyphs sit above it.
    bottom = text_box(100, 50, "DN 80", 2.0, "start", "text-bottom")
    assert bottom[3] < 50 and bottom[1] < start[1]
    # hanging: y is the top.
    top = text_box(100, 50, "DN 80", 2.0, "start", "hanging")
    assert top[1] == pytest.approx(50) and top[3] > 50
    # The alphabetic baseline (default): the glyphs stand on y.
    plain = text_box(100, 50, "DN 80", 2.0, None, None)
    assert plain[3] == pytest.approx(50)


def test_rotated_text_box_turns_with_it():
    context = _context(L1=SYSTEM, L1_P1=PIPE)
    turned = _svg(
        _line(
            "L1",
            {"L1_P1": "100,0 100,200"},
            _text(100, 100, "DN 80", anchor="middle", transform="rotate(270 100 100)"),
        )
    )
    label = read_drawing(turned, context.kinds).labels[0]
    x0, y0, x1, y1 = label.box
    assert y1 - y0 > x1 - x0  # tall, not wide
    assert parse_transform("rotate(270 100 100)")[4] == pytest.approx(0, abs=1e-9)


# -- line-through-label -----------------------------------------------------------------------


def test_line_through_its_own_dn_label():
    context = _context(L1=SYSTEM, L1_P1=PIPE)
    on_line = _svg(_line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 100, "DN 80")))
    found = _lint(on_line, context)
    assert _rules(found) == ["line-through-label"]
    assert "its own pipe" in found[0].message and "'DN 80'" in found[0].message
    assert found[0].ids == ["L1_P1", "L1"]


def test_label_above_its_line_is_clear():
    context = _context(L1=SYSTEM, L1_P1=PIPE)
    # text-bottom at the line's y: the glyphs stand above it.
    above = _svg(_line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 100, "DN 80", "text-bottom")))
    assert _lint(above, context) == []
    # The same text one millimetre lower reaches down through the line.
    lower = _svg(_line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 101.2, "DN 80", "text-bottom")))
    assert _rules(_lint(lower, context)) == ["line-through-label"]


# -- line-crossing ----------------------------------------------------------------------------


def test_crossing_pipes():
    context = _context(L1=SYSTEM, L1_P1=PIPE, L2=SYSTEM, L2_P1=PIPE)
    crossing = _svg(
        _line("L1", {"L1_P1": "10,100 200,100"}),
        _line("L2", {"L2_P1": "100,10 100,200"}),
    )
    found = _lint(crossing, context)
    assert _rules(found) == ["line-crossing"]
    assert "(100.0,100.0)" in found[0].message
    assert found[0].ids == ["L1_P1", "L2_P1"]
    assert found[0].box[0] < 100 < found[0].box[2]


def test_a_branch_ending_on_a_line_is_no_crossing():
    context = _context(L1=SYSTEM, L1_P1=PIPE, L2=SYSTEM, L2_P1=PIPE, I1=INSTRUMENT)
    tee = _svg(
        _line("L1", {"L1_P1": "10,100 200,100"}),
        _line("L2", {"L2_P1": "100,10 100,100"}),
        # A dashed signal line crossing another dashed one is not checked either.
        f'<g id="I1" class="representation-group"><g class="static">'
        f"{_polyline('150,10 150,90', True)}{_polyline('140,50 160,50', True)}</g></g>",
    )
    assert _lint(tee, context) == []


def test_signal_line_across_a_pipe():
    context = _context(L1=SYSTEM, L1_P1=PIPE, I1=INSTRUMENT)
    across = _svg(
        _line("L1", {"L1_P1": "10,100 200,100"}),
        f'<g id="I1" class="representation-group"><g class="static">'
        f"{_polyline('120,50 120,150', True)}</g></g>",
    )
    found = _lint(across, context)
    assert _rules(found) == ["line-crossing"]
    assert "signal line" in found[0].message


# -- label-overlap ----------------------------------------------------------------------------


def test_overlapping_texts():
    context = _context(L1=SYSTEM, L1_P1=PIPE, L2=SYSTEM, L2_P1=PIPE)
    texts = _svg(
        _line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 95, "L-1001")),
        _line("L2", {"L2_P1": "10,150 200,150"}, _text(43, 95.5, "L-1002")),
    )
    found = _lint(texts, context)
    assert "label-overlap" in _rules(found)
    overlap = next(f for f in found if f.rule == "cheme.label-overlap")
    assert "'L-1001'" in overlap.message and "'L-1002'" in overlap.message


def test_text_on_another_objects_symbol():
    context = _context(T1=TANK, I1=INSTRUMENT)
    sheet = _svg(_tank("T1", 100, 100, 130, 160), _bubble("I1", 80, 130, _text(98, 120, "note")))
    found = [f for f in _lint(sheet, context) if f.rule == "cheme.label-overlap"]
    assert len(found) == 1 and "symbol of T1" in found[0].message
    # Its own symbol is no overlap: the instrument letters in their bubble.
    alone = _svg(_bubble("I1", 80, 130))
    assert _lint(alone, _context(I1=INSTRUMENT)) == []


COLUMN = "Plant/ProcessEquipment.ProcessColumn"
NOZZLE = "Plant/ProcessEquipment.ProcessNozzle"


def _equipment(object_id: str, shape: str, *texts: str, parts: str = "") -> str:
    """An equipment item drawn by *shape* (SVG in sheet mm) with its tag *texts*."""
    label = f'<g class="equipmenttagnamelabel">{"".join(texts)}</g>' if texts else ""
    return (
        f'<g id="{object_id}" class="representation-group"><g class="static"><g>'
        f'<g id="SHAPE" transform="translate(0,0)">{shape}</g></g></g>{parts}{label}</g>'
    )


def _circle(x, y, r) -> str:
    return f'<ellipse cx="{x}" cy="{y}" rx="{r}" ry="{r}" fill="none" stroke="black"/>'


def test_an_equipment_tag_on_its_own_outline():
    """'E-101' written across the E-101 circle; inside the symbol or clear of
    it is fine."""
    context = Context(kinds={"E1": TANK}, names={"E1": "E-101"})
    on = _svg(_equipment("E1", _circle(100, 100, 5), _text(100, 95, "E-101", anchor="middle")))
    found = [f for f in _lint(on, context) if f.rule == "cheme.label-overlap"]
    assert len(found) == 1 and "sits on the outline of its own symbol" in found[0].message
    assert found[0].ids == ["E1"]
    inside = _svg(_equipment("E1", _circle(100, 100, 8), _text(100, 100, "E-101", anchor="middle")))
    assert _lint(inside, context) == []
    clear = _svg(_equipment("E1", _circle(100, 100, 5), _text(100, 88, "E-101", anchor="middle")))
    assert _lint(clear, context) == []


def test_a_column_tag_over_its_internals_and_its_nozzles():
    """A tag inside a column may cross the internals drawn in it (a packed bed), not the shell."""
    shell = _polyline("88,70 88,157 91,160 109,160 112,157 112,70 88,70")
    packing = _polyline("88,74 112,74 88,99 112,99 88,74")
    nozzle = (
        '<g id="N1" class="representation-group"><g class="static">'
        f"{_polyline('112,86 118,86')}</g></g>"
    )
    context = Context(kinds={"C1": COLUMN, "N1": NOZZLE}, names={"C1": "C-3102"})
    inside = _svg(
        _equipment("C1", shell + packing, _text(100, 87.5, "C-3102", anchor="middle"), parts=nozzle)
    )
    assert _lint(inside, context) == []
    on_shell = _svg(_equipment("C1", shell + packing, _text(112, 120, "C-3102", anchor="middle")))
    found = [f for f in _lint(on_shell, context) if f.rule == "cheme.label-overlap"]
    assert len(found) == 1 and "C-3102 (C1)" in found[0].message


def test_a_line_through_an_equipment_body():
    """A pipe across a vessel it does not end on; a pipe to a nozzle, or into
    the body to an internal, is fine."""
    vessel = _polyline("100,100 130,100 130,160 100,160 100,100")
    context = Context(
        kinds={"T1": TANK, "N1": NOZZLE, "L1": SYSTEM, "L1_P1": PIPE},
        names={"T1": "V-101", "L1": "AIR-103"},
    )
    nozzle = (
        '<g id="N1" class="representation-group"><g class="static">'
        f"{_polyline('130,120 135,120')}</g></g>"
    )
    across = _svg(_equipment("T1", vessel, parts=nozzle), _line("L1", {"L1_P1": "80,130 150,130"}))
    found = [f for f in _lint(across, context) if f.rule == "cheme.line-through-symbol"]
    assert len(found) == 1 and "runs through the body of V-101 (T1)" in found[0].message
    assert found[0].ids == ["L1_P1", "T1"] and "nozzle" in found[0].hint
    to_nozzle = _svg(
        _equipment("T1", vessel, parts=nozzle), _line("L1", {"L1_P1": "135,120 170,120"})
    )
    assert _lint(to_nozzle, context) == []
    to_internal = _svg(
        _equipment("T1", vessel, parts=nozzle), _line("L1", {"L1_P1": "80,130 115,130"})
    )
    assert [f for f in _lint(to_internal, context) if "through-symbol" in f.rule] == []


# -- line-through-valve, line-on-pipe, line-not-orthogonal --------------------------------------

SEGMENT = "Plant/Piping.PipingNetworkSegment"
GLOBE = "Plant/Piping.GlobeValve"
ACTUATOR = "Plant/Instrumentation.ControlledActuator"
SIGNAL = "Plant/Instrumentation.SignalConveyingFunction"
MEASURING = "Plant/Instrumentation.MeasuringLineFunction"


def _shape(object_id: str, svg: str) -> str:
    """An object drawn by a shape (a ShapeUsage: its strokes are symbol outlines)."""
    return (
        f'<g id="{object_id}" class="representation-group"><g class="static"><g>'
        f'<g transform="translate(0,0)">{svg}</g></g></g></g>'
    )


def _valve_line(line: str, x: float, y: float, vertical: bool = False) -> str:
    """Line *line* through a globe valve ``V_<line>`` at x, y (horizontal or vertical): its
    two pipes end at the valve's nodes, 2 mm either side."""
    if vertical:
        body = f"{x + 1},{y - 2} {x - 1},{y + 2} {x + 1},{y + 2} {x - 1},{y - 2} {x + 1},{y - 2}"
        pipes = {
            f"{line}_P1": f"{x},{y - 40} {x},{y - 2}",
            f"{line}_P2": f"{x},{y + 2} {x},{y + 40}",
        }
    else:
        body = f"{x + 2},{y + 1} {x - 2},{y - 1} {x - 2},{y + 1} {x + 2},{y - 1} {x + 2},{y + 1}"
        pipes = {
            f"{line}_P1": f"{x - 50},{y} {x - 2},{y}",
            f"{line}_P2": f"{x + 2},{y} {x + 50},{y}",
        }
    drawn = "".join(
        f'<g id="{p}" class="representation-group"><g class="static">{_polyline(pts)}</g></g>'
        for p, pts in pipes.items()
    )
    valve = _shape(f"V_{line}", f'<polygon points="{body}" fill="none" stroke="black"/>')
    return (
        f'<g id="{line}" class="representation-group">'
        f'<g id="{line}_S1" class="representation-group">{drawn}{valve}</g></g>'
    )


def _actuator(object_id: str, x: float, y: float) -> str:
    """An actuator on the valve at x, y: its head 3.6 mm across, 3.6 mm up its stem."""
    return _shape(object_id, f"{_circle(x, y - 5.4, 1.8)}{_polyline(f'{x},{y - 3.6} {x},{y}')}")


def _loop(object_id: str, x: float, y: float, signal: str = "", measuring: str = "") -> str:
    """Instrument *object_id* (bubble at x, y) with its signal and measuring lines."""
    parts = _bubble(object_id, x, y).removesuffix("</g>")
    for suffix, points in (("Signal", signal), ("MeasuringLine", measuring)):
        if points:
            parts += (
                f'<g id="{object_id}_{suffix}" class="representation-group"><g class="static">'
                f"{_polyline(points, dashed=suffix == 'Signal')}</g></g>"
            )
    return parts + "</g>"


def _valve_context(**more: str) -> Context:
    kinds = {
        "L1": SYSTEM,
        "L1_S1": SEGMENT,
        "L1_P1": PIPE,
        "L1_P2": PIPE,
        "V_L1": GLOBE,
        "A1": ACTUATOR,
        "I1": INSTRUMENT,
        "I1_Signal": SIGNAL,
        "I1_MeasuringLine": MEASURING,
        **more,
    }
    context = Context(kinds=kinds, names={"V_L1": "UV-1703", "I1": "UIC-1703", "L1": "PG-1089"})
    context.parents = {"L1_P1": "L1", "L1_P2": "L1"}
    context.actuated = {"A1": "V_L1"}
    return context


def _through_valve(sheet, context):
    return [f for f in _lint(sheet, context) if f.rule == "cheme.line-through-valve"]


def test_a_signal_line_through_its_control_valve_to_the_actuator():
    """ammonia-1 P-108: UIC-1703 below the pipe, its signal drawn straight up through UV-1703
    and the actuator to the actuator's top. From above, ending on the actuator, it is fine; so
    are the valve's own pipes and its actuator's stem."""
    context = _valve_context()
    valve = _valve_line("L1", 190, 80) + _actuator("A1", 190, 80)
    through = _svg(valve, _loop("I1", 160, 100, signal="163.75,100 190,100 190,72.8"))
    (found,) = _through_valve(through, context)
    assert "signal line I1_Signal runs through the body and the actuator of UV-1703 (V_L1)" in (
        found.message
    )
    assert found.ids == ["I1_Signal", "V_L1", "A1"] and found.key == "I1_Signal+V_L1"
    assert "away from the pipe" in found.hint
    above = _svg(valve, _loop("I1", 160, 60, signal="163.75,60 190,60 190,72.8"))
    assert _lint(above, context) == []
    # From the side, into the actuator's centre: it ends on the actuator.
    centre = _svg(valve, _loop("I1", 160, 74.6, signal="163.75,74.6 190,74.6"))
    assert _through_valve(centre, context) == []


def test_a_signal_line_along_the_pipe_through_a_valve():
    """A signal line drawn on the pipe, through the valve: through the valve, and on the pipe."""
    context = _valve_context()
    sheet = _svg(
        _valve_line("L1", 190, 80),
        _actuator("A1", 190, 80),
        _loop("I1", 230, 100, signal="226.25,100 220,100 220,80 170,80 170,60"),
    )
    found = _lint(sheet, context)
    (valve,) = [f for f in found if f.rule == "cheme.line-through-valve"]
    assert "runs through the body of UV-1703" in valve.message
    (on_pipe,) = [f for f in found if f.rule == "cheme.line-on-pipe"]
    assert on_pipe.ids == ["I1_Signal", "L1_P1", "L1_P2"] and on_pipe.key == "I1_Signal+L1"
    assert "on top of it, for 50.0 mm" in on_pipe.message


def test_an_actuator_drawn_on_the_pipe_and_a_pipe_through_a_valve():
    """A valve on a vertical pipe with its actuator up the pipe (ammonia-1 P-104 TV-1306): the
    pipe runs through the actuator. Another line's pipe across the valve runs through it."""
    context = _valve_context(
        L2=SYSTEM, L2_S1=SEGMENT, L2_P1=PIPE, L2_P2=PIPE, V_L2=GLOBE, A2=ACTUATOR
    )
    context.actuated["A2"] = "V_L2"
    context.names["V_L2"] = "TV-1306"
    sheet = _svg(_valve_line("L2", 300, 120, vertical=True), _actuator("A2", 300, 120))
    (found,) = _through_valve(sheet, context)
    assert found.message == "pipe L2_P1 runs through the actuator of TV-1306 (V_L2)"
    assert "turn the actuator off the pipe" in found.hint
    across = _svg(_valve_line("L1", 190, 80), _line("L3", {"L3_P1": "190,40 190,120"}))
    context.kinds.update(L3=SYSTEM, L3_P1=PIPE)
    (found,) = _through_valve(across, context)
    assert found.message == "pipe L3_P1 runs through the body of UV-1703 (V_L1)"


def test_a_slanted_measuring_line():
    """A measuring line straight from its tap to the bubble (diagonal) is reported (info); a
    hop over another line, with short slanted legs, is not."""
    context = _valve_context()
    slanted = _svg(_loop("I1", 160, 100, measuring="165,130 160,103.75"))
    (found,) = [f for f in _lint(slanted, context) if f.rule == "cheme.line-not-orthogonal"]
    assert found.level == "info" and found.ids == ["I1_MeasuringLine"]
    assert "(165.0,130.0)-(160.0,103.8)" in found.message
    hop = "160,130 160,120 159.5,119 159.5,117 160,116 160,103.75"
    assert _lint(_svg(_loop("I1", 160, 100, measuring=hop)), context) == []


def test_context_knows_the_valve_an_actuator_operates():
    from chemeascode.domains.piping.drawing import context_from_xml

    root = etree.fromstring(
        '<PlantModel><Object id="S" type="Plant/Instrumentation.ActuatingSystem">'
        '<Components property="ControlledActuator">'
        '<Object id="A" type="Plant/Instrumentation.ControlledActuator"/></Components>'
        '<Components property="OperatedValveReference">'
        '<Object id="R" type="Plant/Instrumentation.OperatedValveReference">'
        '<References objects="#UV1" property="Valve"/></Object></Components></Object>'
        "</PlantModel>"
    )
    context = context_from_xml(root)
    assert context.actuated == {"A": "UV1"} and context.is_actuator("A")


# -- offpage-not-on-edge ----------------------------------------------------------------------

IN_CONNECTOR = "Plant/Piping.FlowInPipeOffPageConnector"
OUT_CONNECTOR = "Plant/Piping.FlowOutPipeOffPageConnector"
#: An A3 sheet's border (inside 4..416, 4..293) and a title block whose top is at y 263.
_FRAME = (
    '<g id="Border" class="border">'
    + _polyline("4,4 416,4 416,293 4,293 4,4")
    + "</g>"
    + '<g id="Title" class="label">'
    + _polyline("296,263 416,263 416,293 296,293 296,263")
    + "</g>"
)


def _connector(object_id: str, x: float, y: float, note: str = "") -> str:
    """An 8 x 8 mm off-page connector arrow with its top left corner at x, y and its note."""
    arrow = f"{x},{y} {x + 5},{y} {x + 8},{y + 4} {x + 5},{y + 8} {x},{y + 8} {x},{y}"
    text = f'<g class="static">{_text(x, y - 2, note)}</g>' if note else ""
    return (
        f'<g id="{object_id}" class="representation-group"><g class="static"><g>'
        f'<g transform="translate(0,0)">{_polyline(arrow)}</g></g></g>{text}</g>'
    )


def _offpage(*parts: str, **kinds: str) -> list[DrawingFinding]:
    context = _context(**kinds)
    found = _lint(_svg(*parts, _FRAME), context)
    return [f for f in found if f.rule == "cheme.offpage-not-on-edge"]


def test_offpage_connector_on_the_edge_passes_mid_sheet_fires():
    on_edges = _offpage(
        _connector("IN1", 12, 100, "from P-01"),  # 8 mm in from the left edge
        _connector("OUT1", 405, 100, "to P-03"),  # 3 mm from the right edge
        _connector("OUT2", 200, 250, "to P-04"),  # 5 mm above the title block's top
        IN1=IN_CONNECTOR,
        OUT1=OUT_CONNECTOR,
        OUT2=OUT_CONNECTOR,
    )
    assert on_edges == []
    (found,) = _offpage(_connector("OUT1", 200, 120, "to P-03"), OUT1=OUT_CONNECTOR)
    assert found.level == "warning" and found.ids == ["OUT1"] and found.key == "OUT1"
    assert "sits 116 mm inside the drawing area's top edge" in found.message
    assert "within 10 mm, or 35 mm" in found.message
    assert "`cheme move OUT1 --offset=0,-111`" in found.hint
    assert "outgoing connector goes on the right edge: --offset=203,0" in found.hint


def test_a_header_row_set_in_from_the_edge_needs_a_clear_way_to_it():
    """24 mm below the top border with only its own text above it is on the edge (a header
    sheet's row); with a pipe of another line between it and the edge it is not."""
    row = _connector("OUT1", 200, 28, "to E-101, P-02")
    assert _offpage(row, OUT1=OUT_CONNECTOR) == []
    pipe = _line("L1", {"L1_P1": "100,15 300,15"})
    (found,) = _offpage(row, pipe, OUT1=OUT_CONNECTOR, L1=SYSTEM, L1_P1=PIPE)
    assert "24 mm inside the drawing area's top edge" in found.message


def test_open_ends_may_sit_by_their_valve():
    """A vent to atmosphere, a drain or a hose connection drawn with an off-page connector is no
    connection to another sheet; one whose text names a sheet or the battery limit is."""
    assert (
        _offpage(
            _connector("OPC_PSV1_atm", 150, 100),
            _connector("OUT2", 200, 100, "to drain"),
            _connector("IN3", 250, 100, "tanker hose"),
            _connector("OUT4", 300, 100, "to atmosphere (safe location)"),
            OPC_PSV1_atm=OUT_CONNECTOR,
            OUT2=OUT_CONNECTOR,
            IN3=IN_CONNECTOR,
            OUT4=OUT_CONNECTOR,
        )
        == []
    )
    found = _offpage(
        _connector("OUT1", 150, 100, "to vent header, P-07"),
        _connector("OUT2", 200, 100, "to closed drain"),
        _connector("OUT3", 250, 100, "to flare (B/L)"),
        OUT1=OUT_CONNECTOR,
        OUT2=OUT_CONNECTOR,
        OUT3=OUT_CONNECTOR,
    )
    assert sorted(f.ids[0] for f in found) == ["OUT1", "OUT2", "OUT3"]


# -- label-far-from-owner ---------------------------------------------------------------------


def test_misplaced_note_is_far_from_the_instrument_it_names():
    kinds = {"I1": INSTRUMENT, "I2": INSTRUMENT, "T1": TANK}
    note = _text(205, 140, "LALL-4108 trip P-4102A/B")
    sheet = _svg(
        _bubble("I1", 20, 140), _bubble("I2", 200, 150, note), _tank("T1", 230, 100, 260, 170)
    )
    context = Context(kinds=kinds, names={"I1": "LIA-4108", "I2": "TSLL-4114", "T1": "T-4101"})
    context.named[("LALL-4108 trip P-4102A/B", 205.0, 140.0)] = ["I1"]
    found = [f for f in _lint(sheet, context) if f.rule == "cheme.label-far-from-owner"]
    assert len(found) == 1
    assert "LIA-4108 (I1), the instrument it names first" in found[0].message
    assert "T-4101 (T1)" in found[0].message  # what it sits by
    # Next to the instrument it names, it is fine.
    near = _svg(_bubble("I1", 20, 140), _bubble("I2", 30, 150, _text(25, 134, "LALL-4108 trip")))
    context.named = {("LALL-4108 trip", 25.0, 134.0): ["I1"]}
    assert [f for f in _lint(near, context) if f.rule.endswith("far-from-owner")] == []


def test_label_far_from_its_line_and_label_nearer_another():
    context = _context(L1=SYSTEM, L1_P1=PIPE, L2=SYSTEM, L2_P1=PIPE)
    far = _svg(_line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 130, "DN 80")))
    found = _lint(far, context)
    assert _rules(found) == ["label-far-from-owner"] and "29 mm from L1" in found[0].message
    nearer = _svg(
        _line("L1", {"L1_P1": "10,100 200,100"}, _text(40, 109, "L-1001")),
        _line("L2", {"L2_P1": "10,112 200,112"}),
    )
    found = _lint(nearer, context)
    assert _rules(found) == ["label-far-from-owner"]
    assert "reads as L2's" in found[0].message


# -- sheet frame --------------------------------------------------------------------------------


def test_border_and_title_block_give_no_findings():
    context = _context(L1=SYSTEM, L1_P1=PIPE)
    frame = (
        '<g id="Border" class="border">'
        + _polyline("5,5 415,5 415,292 5,292 5,5")
        + _polyline("5,100 415,100")
        + "".join(_text(10 + 30 * i, 100, str(i)) for i in range(12))
        + "</g>"
        + '<g id="Title" class="label">'
        + _polyline("300,250 415,250")
        + _text(300, 250, "DRAWING NO")
        + _text(301, 250, "PROJECT")
        + "</g>"
    )
    # A line through the zone numbers and the title block texts.
    sheet = _svg(_line("L1", {"L1_P1": "0,250 420,250"}), frame)
    assert _lint(sheet, context) == []


# -- on real sheets ---------------------------------------------------------------------------


def _drawing_findings(path: Path):
    findings, model = validate_pid(path)
    assert model is not None
    return [f for f in findings if f.box is not None]


def test_reference_has_few_drawing_findings():
    """The DEXPI reference P&ID: its two real crossings of line 47126, the crossing of 47122 and
    47130, and two labels its own lines touch; nothing else."""
    found = _drawing_findings(REFERENCE)
    assert sorted((f.rule, *f.ids) for f in found) == [
        ("cheme.line-crossing", "Pipe2", "Pipe25"),
        ("cheme.line-crossing", "Pipe20", "Pipe27"),
        ("cheme.line-crossing", "Pipe20", "Pipe29"),
        ("cheme.line-through-label", "Pipe19", "PipingNetworkSystem6"),
        ("cheme.line-through-label", "Pipe25", "PipingNetworkSystem2"),
    ]
    for finding in found:
        assert finding.line, finding
        crop = Crop.parse(finding.crop)
        x0, y0, x1, y1 = finding.box
        assert crop.x0 <= x0 and crop.y0 <= y0 and x1 <= crop.x1 and y1 <= crop.y1
        assert finding.id.startswith("reference_pid.xml#") or "#" in finding.id


def test_moved_tag_label_is_far_from_its_tank(tmp_path: Path):
    root = etree.parse(str(REFERENCE)).getroot()
    text = next(
        t
        for t in root.iter("Object")
        if t.get("type") == "Core/Diagram.Text"
        and (t.findtext("Data[@property='Text']/String") or "") == "T4750"
    )
    position = "Data[@property='Position']/AggregatedDataValue/Data[@property='{}']/*"
    text.find(position.format("X")).text = "60"
    text.find(position.format("Y")).text = "40"
    path = tmp_path / "moved.xml"
    path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
    far = [f for f in _drawing_findings(path) if f.rule == "cheme.label-far-from-owner"]
    assert len(far) == 1 and "'T4750'" in far[0].message and far[0].ids == ["Tank1"]
    assert far[0].line and far[0].crop


def tag_left_of_the_sheet(directory: Path) -> Path:
    """The reference with the tank's tag text moved to x = -30 mm: the SVG's viewBox then starts
    left of the sheet (pyDEXPI grows it to cover the text)."""
    root = etree.parse(str(REFERENCE)).getroot()
    text = next(
        t
        for t in root.iter("Object")
        if t.get("type") == "Core/Diagram.Text"
        and (t.findtext("Data[@property='Text']/String") or "") == "T4750"
    )
    position = "Data[@property='Position']/AggregatedDataValue/Data[@property='X']/*"
    text.find(position).text = "-30"
    path = directory / "left.xml"
    path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))
    return path


def test_viewbox_origin_is_kept_and_crops_contain_their_box():
    """A viewBox that does not start at 0,0: the drawing keeps its origin, and a finding left of
    the sheet gets a crop that contains it, x0 < x1."""
    svg = etree.fromstring(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="-41.25 -5 461.25 302">'
        '<g class="diagram"/></svg>'
    )
    drawing = read_drawing(svg, {})
    assert drawing.origin == (-41.25, -5) and drawing.box == (-41.25, -5, 420, 297)
    finding = DrawingFinding("r", "warning", "m", [], (-36.4, 96.2, -23.6, 99.4), "k")
    x0, y0, x1, y1 = finding.crop(drawing.box)
    assert (x0, y0, x1, y1) == pytest.approx((-41.25, 86.2, -13.6, 109.4))
    # The margin stays on the sheet; the finding's own box is never cut.
    assert finding.crop((0, 0, 420, 297)) == pytest.approx((-36.4, 86.2, -13.6, 109.4))
    on_sheet = DrawingFinding("r", "warning", "m", [], (2, 2, 8, 8), "k")
    assert on_sheet.crop((0, 0, 420, 297)) == (0, 0, 18, 18)


def test_text_outside_frame_left_of_the_sheet_has_a_usable_crop(tmp_path: Path):
    path = tag_left_of_the_sheet(tmp_path)
    (outside,) = [f for f in _drawing_findings(path) if f.rule == "cheme.text-outside-frame"]
    crop = Crop.parse(outside.crop)
    x0, y0, x1, y1 = outside.box
    assert x1 < 0  # wholly left of the sheet
    assert crop.x0 <= x0 and crop.y0 <= y0 and x1 <= crop.x1 and y1 <= crop.y1
    assert outside.crop.split(",")[0] == f"{crop.x0:g}"  # printed in order, x0 < x1


def test_drawing_rules_are_fast():
    from pydexpi.loaders.public import load_xml_with_report

    from chemeascode.domains.piping.drawing import lint_model

    content = REFERENCE.read_bytes()
    model = load_xml_with_report(content, strict=True).model
    root = etree.fromstring(content)
    started = time.perf_counter()
    lint_model(model, root)
    assert time.perf_counter() - started < 1.0


ASU = os.environ.get("CHEME_ASU_REPO")


@pytest.mark.skipif(not ASU, reason="set CHEME_ASU_REPO to the ASU-1 test repository")
def test_asu_sheets_show_the_reviewers_defects():  # pragma: no cover - needs the ASU repository
    pid = Path(ASU) / "pid"
    found = {name: _drawing_findings(pid / name) for name in ("P-01.xml", "P-03.xml", "P-04.xml")}

    def has(sheet: str, rule: str, *words: str) -> bool:
        return any(
            f.rule == f"cheme.{rule}" and all(w in f.message for w in words) for f in found[sheet]
        )

    assert has("P-04.xml", "line-crossing", "GOX-4003", "UIC4103")
    assert has("P-03.xml", "line-crossing", "GOX-3001", "LOX-3001")
    assert has("P-01.xml", "line-through-label", "its own pipe CWR-1001", "'DN 250'")
    assert has("P-04.xml", "label-far-from-owner", "LALL-4108", "LIA-4108", "T-4101")


@pytest.mark.skipif(not ASU, reason="set CHEME_ASU_REPO to the ASU-1 test repository")
def test_asu_gate_and_texts_naming_tags(tmp_path: Path):  # pragma: no cover - needs the ASU repo
    import shutil

    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.checks import gate_findings
    from chemeascode.project.validate import validate_workspace
    from chemeascode.schemas import Accept, Check

    repo = tmp_path / "asu"
    shutil.copytree(ASU, repo, ignore=shutil.ignore_patterns(".git", "build"))
    report = validate_workspace(Workspace(repo))
    named = ("cheme.label-tag-unknown", "cheme.offpage-mismatch")
    assert [f for f in report.findings if f.rule in named] == []
    gate = Check(
        id="drawing-clean",
        title="Drawing clean",
        stage="basic",
        kind="validate",
        fail_on="warning",
        rules=["cheme.line-through-label", "cheme.label-far-from-owner"],
    )
    failing = gate_findings(report.findings, gate)
    note = [f for f in failing if "LALL-4108" in f.message and "far-from-owner" in f.rule]
    assert len(note) == 1 and note[0].file == "pid/P-04.xml"
    gate.accept = [Accept(id=note[0].id, reason="C&E table covers the LIN tank trip")]
    assert note[0] not in gate_findings(report.findings, gate)

    sheet = repo / "pid" / "P-04.xml"
    text = sheet.read_text(encoding="utf-8")
    sheet.write_text(
        text.replace("from P-03 LIN-3001 (subcooled)", "from P-03 LN-3001 (subcooled)")
    )
    report = validate_workspace(Workspace(repo))
    mismatch = [f for f in report.findings if f.rule == "cheme.offpage-mismatch"]
    assert len(mismatch) == 1 and "LIN-3001" in mismatch[0].message
