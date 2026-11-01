"""cheme fragment's drafting kinds: equipment, nozzle, instrument, signal, offpage, line, note
and shape. Every kind is pasted where its comments say into the template's empty sheet (or a
sheet that lacks the shape), formatted and validated."""

import re
import shutil
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.authoring._xml import point_xy, points_of
from chemeascode.domains.piping.authoring.fragment import FragmentError, make_fragment
from chemeascode.domains.piping.authoring.shapes import (
    ADDED_SHAPES,
    EQUIPMENT_RGB,
    EQUIPMENT_SHAPES,
    catalogue,
)
from chemeascode.domains.piping.drawing import RULES as DRAWING_RULES
from chemeascode.domains.piping.fmt import format_file
from chemeascode.domains.piping.render import load_model, render_svg
from chemeascode.domains.piping.show import show
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]
EMPTY = ROOT / "src/chemeascode/domains/piping/skills/dexpi-xml/snippets/empty-sheet.xml"
#: Findings about the lists (the sheet's items are not in equipment/instrument/line lists yet).
LIST_RULES = {
    "cheme.equipment-not-listed",
    "cheme.instrument-not-listed",
    "cheme.line-not-listed",
    "cheme.label-tag-unknown",
}
#: Drawing-geometry findings follow where the test places things; tested in test_drawing.py.
IGNORED_RULES = LIST_RULES | set(DRAWING_RULES)


@pytest.fixture
def empty(plant: Path) -> Path:
    """The template's empty sheet as pid/P-01.xml of a plant repository."""
    path = plant / "pid" / "P-01.xml"
    shutil.copy(EMPTY, path)
    return path


def _findings(root: Path) -> Counter:
    report = validate_workspace(Workspace.find(root))
    return Counter((f.level, f.rule, f.message) for f in report.findings)


def _new(path: Path, baseline: Counter) -> list[tuple[str, str, str]]:
    format_file(path)
    ids = [e.get("id") for e in etree.parse(str(path)).getroot().iter("Object") if e.get("id")]
    assert len(ids) == len(set(ids)), [i for i, n in Counter(ids).items() if n > 1]
    added = (_findings(path.parents[1]) - baseline).elements()
    return sorted(f for f in added if f[0] != "info" and f[1] not in IGNORED_RULES)


class Paster:
    """Pastes fragments into a sheet the way their comments say, rereading it each time."""

    def __init__(self, path: Path):
        self.path = path
        self.root = etree.parse(str(path)).getroot()

    def save(self) -> None:
        self.path.write_bytes(etree.tostring(self.root, xml_declaration=True, encoding="UTF-8"))

    def find(self, object_id: str) -> etree._Element:
        found = self.root.find(f".//Object[@id='{object_id}']")
        assert found is not None, object_id
        return found

    def drawing_of(self, object_id: str) -> etree._Element:
        for reference in self.root.iter("References"):
            if reference.get("property") == "Represents" and reference.get("objects") == (
                f"#{object_id}"
            ):
                return reference.getparent()
        raise AssertionError(f"no drawing of {object_id}")

    def components(self, holder: etree._Element, prop: str, create: bool) -> etree._Element:
        """The block to paste into; a new one when the comment says "create it", as written."""
        if create:
            found = etree.Element("Components", property=prop)
            holder.insert(0, found)
            return found
        found = holder.find(f"Components[@property='{prop}']")
        assert found is not None, f"no {prop} block in {holder.get('id')} to paste into"
        return found

    def make(self, kind: str, object_id: str | None, **options):
        self.save()
        return make_fragment(kind, object_id, sheet=self.path, **options)

    def paste(self, made, **where: tuple[str, str]) -> None:
        """Paste every part: by its ``into`` or by ``where[title]`` (holder id, property)."""
        for part in made.parts:
            if not part.xml:
                continue
            into = where.get(part.title.replace(" ", "_").lower()) or part.into
            assert into is not None, (made.kind, part.title, part.where)
            holder, prop = into
            create = "create it" in part.where and part.title.replace(" ", "_").lower() not in where
            target = self.components(self.find(holder), prop, create)
            target.append(etree.fromstring(part.xml))
        self.save()


def _segment_paste(paster: Paster, segment: str):
    drawing = paster.drawing_of(segment).get("id")
    return {"conceptual": (segment, "Items"), "drawing": (drawing, "Groups")}


def _build_section(path: Path, signals: bool = True) -> Paster:
    """An ASU section, from fragments only: tank, pump, level loop, trip to XV and LV, off-page.

    T-4101 (flat-bottom tank) -> XV-4136 -> P-4101 -> LV-4107 -> off-page to P-05. LIC-4107 on
    the tank's level connection controls LV-4107; LSLL-4108 trips XV-4136 and LV-4107.
    """
    p = Paster(path)
    made = p.make(
        "equipment",
        "T4101",
        item_class="Tank",
        tag="T-4101",
        shape="FLAT_BOTTOM_TANK_SHAPE",
        at="80,110",
        nozzles=["N1:0,12.5:100", "L1:-15,5"],
    )
    p.paste(made)
    made = p.make(
        "equipment",
        "P4101",
        item_class="CentrifugalPump",
        tag="P-4101",
        at="130,170",
        nozzles=["N1:-7.5,0:100", "N2:0,-7.5:80"],
    )
    assert made.part("SHAPE") is None  # CENTRIFUGAL_PUMP_SHAPE is the sheet's Shape21
    p.paste(made)
    # Suction line LOX-4101: tank N1 (80,126.5) -> XV-4136 (80,150, flowing down) -> pump N1.
    p.paste(p.make("line", "Line_LOX4101", number="LOX-4101", dn="100", fluid="LOX", at="84,140"))
    made = p.make(
        "segment",
        "Line_LOX4101_S1",
        source="T4101_N1:T4101_N1_Node",
        target="P4101_N1:P4101_N1_Node",
        dn="100",
        number="S1",
    )
    p.paste(
        made,
        conceptual=("Line_LOX4101", "Segments"),
        drawing=("Line_LOX4101_Drawing", "Groups"),
    )
    made = p.make(
        "valve",
        "XV4136",
        valve_class="BallValve",
        dn="100",
        at="80,150",
        rotation=90,
        tag="XV-4136",
    )
    p.paste(made, **_segment_paste(p, "Line_LOX4101_S1"))
    for pipe, start, end, bends in (
        ("Pipe_LOX4101_1", "T4101_N1:T4101_N1_Node", "XV4136:XV4136_N1", None),
        ("Pipe_LOX4101_2", "XV4136:XV4136_N2", "P4101_N1:P4101_N1_Node", "80,170"),
    ):
        made = p.make("pipe", pipe, source=start, target=end, points=bends)
        p.paste(
            made,
            conceptual=("Line_LOX4101_S1", "Connections"),
            drawing=("Line_LOX4101_S1_Drawing", "Groups"),
        )
    # Discharge line LOX-4102: pump N2 (130,158.5) -> LV-4107 (170,140) -> off-page out.
    p.paste(p.make("line", "Line_LOX4102", number="LOX-4102", dn="80", fluid="LOX", at="140,138"))
    made = p.make(
        "segment",
        "Line_LOX4102_S1",
        source="P4101_N2:P4101_N2_Node",
        target="OPC_LOX4102:OPC_LOX4102_N",
        dn="80",
        number="S1",
    )
    p.paste(
        made,
        conceptual=("Line_LOX4102", "Segments"),
        drawing=("Line_LOX4102_Drawing", "Groups"),
    )
    made = p.make("valve", "LV4107", valve_class="GlobeValve", dn="80", at="170,140", tag="LV-4107")
    p.paste(made, **_segment_paste(p, "Line_LOX4102_S1"))
    made = p.make(
        "offpage", "OPC_LOX4102", direction="out", at="210,140", dn="80", note="to P-05 V-5101"
    )
    p.paste(made, **_segment_paste(p, "Line_LOX4102_S1"))
    for pipe, start, end, bends in (
        ("Pipe_LOX4102_1", "P4101_N2:P4101_N2_Node", "LV4107:LV4107_N1", "130,140"),
        ("Pipe_LOX4102_2", "LV4107:LV4107_N2", "OPC_LOX4102:OPC_LOX4102_N", None),
    ):
        made = p.make("pipe", pipe, source=start, target=end, points=bends)
        p.paste(
            made,
            conceptual=("Line_LOX4102_S1", "Connections"),
            drawing=("Line_LOX4102_S1_Drawing", "Groups"),
        )
    # Instruments on the tank's level connection, the control loop and the trip.
    for object_id, tag, at in (
        ("Inst_LIC4107", "LIC-4107", "40,100"),
        ("Inst_LSLL4108", "LSLL-4108", "40,130"),
    ):
        p.paste(p.make("instrument", object_id, tag=tag, at=at, sense="T4101_L1"))
    if not signals:
        return p
    made = p.make("signal", "Sig_LIC4107", source="Inst_LIC4107", target="LV4107", fail_action="FC")
    assert made.part("ACTUATING SYSTEM") is not None
    p.paste(made)
    made = p.make("signal", "Sig_LSLL4108", source="Inst_LSLL4108", target="XV4136,LV4107")
    # One trip, two final elements: a new system for XV-4136, LV-4107's is reused.
    assert len(made.all("ACTUATING SYSTEM")) == 1
    assert len(made.all("CONCEPTUAL")) == 2 and len(made.all("DRAWING")) == 2
    p.paste(made)
    made = p.make(
        "note",
        "Note_Trip4108",
        at="20,200",
        text_value="LSLL-4108 trip: close XV-4136 and LV-4107, stop P-4101",
    )
    p.paste(made)
    return p


def test_section_from_fragments_validates_renders_and_shows(empty: Path):
    baseline = _findings(empty.parents[1])
    _build_section(empty)
    assert _new(empty, baseline) == []
    root = etree.parse(str(empty)).getroot()
    # The control and trip relations are modelled, not drawn only.
    systems = root.findall(".//Object[@type='Plant/Instrumentation.ActuatingSystem']")
    assert sorted(s.get("id") for s in systems) == [
        "LV4107_ActuatingSystem",
        "XV4136_ActuatingSystem",
    ]
    valves = {
        s.get("id"): s.find(".//Object[@type='Plant/Instrumentation.OperatedValveReference']")
        .find("References[@property='Valve']")
        .get("objects")
        for s in systems
    }
    assert valves == {"LV4107_ActuatingSystem": "#LV4107", "XV4136_ActuatingSystem": "#XV4136"}
    lines = root.findall(".//Object[@type='Plant/Instrumentation.SignalLineFunction']")
    assert len(lines) == 3
    dashed = root.find(".//Object[@id='Sig_LIC4107_LineShape']")
    assert dashed.find(".//DataReference").get("data") == "Core/Diagram.DashStyle.Dash"
    # show follows the valve to its controllers.
    text, found = show("LV4107", [(empty, "pid/P-01.xml")])
    assert found
    joined = "\n".join(text)
    assert "Inst_LIC4107" in joined and "Inst_LSLL4108" in joined
    # The sheet renders.
    svg = render_svg(load_model(empty))
    assert "<svg" in svg[:400]


def test_note_gives_no_label_literal_finding(empty: Path):
    """The P-04 trip text as a note: no cheme.label-literal, unlike inside a drawing."""
    p = _build_section(empty)
    format_file(empty)
    text_value = "LSLL-4108 / LIC-4107 trip P-4101, XV-4136, LV-4107"
    p = Paster(empty)
    p.paste(p.make("note", "Note_Trip", at="20,210", text_value=text_value))
    format_file(empty)
    rules = {f.rule for f in validate_workspace(Workspace.find(empty.parents[1])).findings}
    assert "cheme.label-literal" not in rules
    # The same text inside the valve's drawing is a label-literal (it repeats XV-4136).
    p = Paster(empty)
    note = p.find("Note_Trip")
    note.getparent().remove(note)
    p.drawing_of("XV4136").find("Components[@property='Groups']").append(note)
    p.save()
    rules = {f.rule for f in validate_workspace(Workspace.find(empty.parents[1])).findings}
    assert "cheme.label-literal" in rules


def test_nozzle_goes_into_the_equipment_and_its_drawing(empty: Path):
    baseline = _findings(empty.parents[1])
    p = _build_section(empty)
    made = p.make("nozzle", "T4101_N6", on="T4101", at="15,-5", dn="50")
    assert made.part("CONCEPTUAL").into == ("T4101", "Nozzles")
    assert made.part("DRAWING").into == ("T4101_Drawing", "Groups")
    assert "SubTagName" in made.part("CONCEPTUAL").xml and "<String>N2</String>" in (
        made.part("CONCEPTUAL").xml
    )  # N1 and L1 exist: the next free N number
    p.paste(made)
    assert _new(empty, baseline) == []
    root = etree.parse(str(empty)).getroot()
    nozzle = root.find(
        ".//Object[@id='T4101']/Components[@property='Nozzles']/Object[@id='T4101_N6']"
    )
    assert nozzle is not None
    assert root.find(".//Object[@id='T4101_Drawing']//Object[@id='T4101_N6_Drawing']") is not None
    # The stub runs outwards from the outline (95,105); the pipe attaches at its end.
    position = root.find(".//Object[@id='T4101_N6_Node_Position']")
    assert [float(v.text) for v in position.iter("Double")] == [99.0, 105.0]


EQUIPMENT_SYMBOLS = [s for s in ADDED_SHAPES if s.rgb == EQUIPMENT_RGB]


@pytest.mark.parametrize("shape", EQUIPMENT_SYMBOLS, ids=lambda s: s.name)
def test_every_added_shape_validates_and_renders(empty: Path, shape):
    """Each added equipment symbol used by an equipment fragment: from the empty sheet's
    catalogue, or (not in the template) with the SHAPE part to paste once."""
    baseline = _findings(empty.parents[1])
    p = Paster(empty)
    item_class = shape.classes[0] if shape.classes else "Vessel"
    made = p.make(
        "equipment",
        "E1",
        item_class=item_class,
        tag="E-1",
        shape=shape.name,
        at="100,100",
        nozzles=["N1:-20,0:50"],
    )
    assert (made.part("SHAPE") is None) == shape.template
    assert f'#{shape.shape_id}"' in made.part("DRAWING").xml
    p.paste(made)
    assert _new(empty, baseline) == []
    assert "<svg" in render_svg(load_model(empty))[:400]


def test_silencer_is_an_inline_item(empty: Path):
    p = Paster(empty)
    made = p.make("valve", "S1101", valve_class="Silencer", dn="300", at="50,50", tag="S-1101")
    assert "Plant/Piping.Silencer" in made.part("CONCEPTUAL").xml
    assert "#Shape_Silencer" in made.part("DRAWING").xml
    # Scale 0.5: the ends are 3 mm from the centre.
    assert "<Double>47.0</Double>" in made.part("DRAWING").xml


def test_shapes_missing_from_an_older_sheet_come_as_a_shape_part(plant: Path):
    """The reference P&ID has no compressor: the fragment brings the shape to paste."""
    path = plant / "pid" / "P-01.xml"
    format_file(path)
    baseline = _findings(plant)
    p = Paster(path)
    made = p.make(
        "equipment",
        "K1101",
        item_class="CentrifugalCompressor",
        tag="K-1101",
        at="200,250",
        nozzles=["N1:-7.5,0:600", "N2:0,-7.5:400"],
    )
    shapes = made.all("SHAPE")
    assert [s.into[1] for s in shapes] == ["Shapes"]
    # the library symbol's own ISO 10628-2 number, nothing invented (ADR 0022)
    assert "<String>ISO10628:2012-X8179-A</String>" in shapes[0].xml
    p.paste(made)
    assert _new(path, baseline) == []
    # Once pasted, fragment shape says it is there.
    made = make_fragment("shape", None, name="CENTRIFUGAL_COMPRESSOR_SHAPE", sheet=path)
    assert not made.part("SHAPE").xml and "already" in made.part("SHAPE").where


def test_fragment_shape_cli(plant: Path, monkeypatch):
    path = plant / "pid" / "P-01.xml"
    format_file(path)
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["fragment", "shape", "column", "--sheet", "pid/P-01.xml"])
    assert result.exit_code == 0, result.output
    assert '<Object id="Shape_Column" type="Core/Diagram.Shape">' in result.stdout
    assert "Shapes" in result.stdout
    present = runner.invoke(
        app, ["fragment", "shape", "GLOBE_VALVE_SHAPE", "--sheet", "pid/P-01.xml"]
    )
    assert present.exit_code == 0 and "already as #Shape3" in present.stdout
    unknown = runner.invoke(app, ["fragment", "shape", "COMPRESOR"])
    assert unknown.exit_code == 2 and "did you mean" in unknown.output


def test_help_lists_the_new_kinds():
    result = runner.invoke(app, ["fragment", "--help"], terminal_width=200)
    for kind in ("equipment", "nozzle", "instrument", "signal", "offpage", "line", "note", "shape"):
        assert kind in result.output


def test_signal_on_a_drawn_actuator_reuses_its_symbol(plant: Path):
    """A valve whose drawing already has an actuator symbol (as the ASU sheets draw them)."""
    path = plant / "pid" / "P-01.xml"
    shutil.copy(EMPTY, path)
    p = _build_section(path)
    format_file(path)
    p = Paster(path)
    made = p.make("signal", "Sig_LIC4107b", source="Inst_LIC4107", target="LV4107")
    assert made.part("ACTUATING SYSTEM") is None  # reuses LV4107_ActuatingSystem
    assert "#LV4107_Actuator_Position" in made.part("DRAWING").xml
    assert any("operated by LV4107_ActuatingSystem" in n for n in made.notes)


def test_drafting_kinds_reject_bad_input(empty: Path):
    with pytest.raises(FragmentError, match="no such DEXPI class"):
        make_fragment("equipment", "E", item_class="Compresor", tag="K-1", at="1,1", sheet=empty)
    with pytest.raises(FragmentError, match="inline fitting"):
        make_fragment("equipment", "E", valve_class="Silencer", tag="S-1", at="1,1")
    with pytest.raises(FragmentError, match="needs --sheet"):
        make_fragment("signal", "S", source="A", target="B")
    with pytest.raises(FragmentError, match="needs --id"):
        make_fragment("note", None, at="1,1", text_value="x")
    with pytest.raises(FragmentError, match="offpage needs --in"):
        make_fragment("offpage", "O", at="1,1")
    p = _build_section(empty)
    with pytest.raises(FragmentError, match="not a sensing location"):
        p.make("instrument", "I", tag="PI-1", at="1,1", sense="T4101")
    with pytest.raises(FragmentError, match="a signal goes to an operated valve"):
        p.make("signal", "S9", source="Inst_LIC4107", target="P4101")


def test_equipment_shapes_table_names_catalogue_shapes():
    names = set(catalogue())
    assert set(EQUIPMENT_SHAPES.values()) <= names
    for shape in ADDED_SHAPES:
        assert shape.name in names
        element = catalogue()[shape.name]
        number = element.findtext("Data[@property='SymbolRegistrationNumber']/String")
        assert number == (f"ISO10628:2012-{shape.iso}-A" if shape.iso else shape.name)


# -- review fixes ---------------------------------------------------------------------------------


def test_trip_to_two_new_valves_creates_each_block_once(empty: Path):
    """A fresh switch (no ActuatingFunctions) trips two valves without actuating systems: each
    new block is created once, the second part goes into it, and pasting as written loads."""
    baseline = _findings(empty.parents[1])
    p = _build_section(empty, signals=False)
    made = p.make("signal", "Sig_LSLL4108", source="Inst_LSLL4108", target="XV4136,LV4107")
    assert len(made.all("ACTUATING SYSTEM")) == 2
    assert len(made.all("ACTUATING FUNCTION")) == 2
    for into in {p.into for p in made.parts if p.into}:
        creating = [p for p in made.parts if p.into == into and "create it" in p.where]
        assert len(creating) <= 1, (into, [p.where for p in creating])
    second = made.all("ACTUATING FUNCTION")[1]
    assert "that the ACTUATING FUNCTION part above creates" in second.where
    p.paste(made)
    assert _new(empty, baseline) == []
    root = etree.parse(str(empty)).getroot()
    systems = root.findall(".//Object[@type='Plant/Instrumentation.ActuatingSystem']")
    assert {s.get("id") for s in systems} == {"XV4136_ActuatingSystem", "LV4107_ActuatingSystem"}
    holder = root.find(".//Object[@id='Inst_LSLL4108']")
    assert len(holder.findall("Components[@property='ActuatingFunctions']")) == 1
    text, found = show("XV4136", [(empty, "pid/P-01.xml")])
    assert found and "Inst_LSLL4108" in "\n".join(text)


def _line_path(root: etree._Element, made) -> list[tuple[float, float]]:
    """The pasted ConnectorLine of *made*'s (last) DRAWING part: start, bends, end."""
    line = etree.fromstring(made.all("DRAWING")[-1].xml)
    connector = next(
        e for e in line.iter("Object") if e.get("type") == "Core/Diagram.ConnectorLine"
    )

    def at(prop: str) -> tuple[float, float]:
        node = connector.find(f"References[@property='{prop}']").get("objects").lstrip("#")
        position = root.find(f".//Object[@id='{node}']")
        return point_xy(position.find("Data[@property='Position']/AggregatedDataValue"))

    inner = connector.find("Data[@property='InnerPoints']")
    bends = [point_xy(v) for v in points_of(inner)] if inner is not None else []
    return [at("Source"), *bends, at("Target")]


def _crosses_circle(path, centre, radius: float) -> bool:
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        steps = max(1, int(max(abs(bx - ax), abs(by - ay)) / 0.05))
        for i in range(steps + 1):
            x, y = ax + (bx - ax) * i / steps, ay + (by - ay) * i / steps
            if (x - centre[0]) ** 2 + (y - centre[1]) ** 2 < (radius - 0.05) ** 2:
                return True
    return False


def _crosses_box(path, box) -> bool:
    x0, y0, x1, y1 = box
    for (ax, ay), (bx, by) in zip(path, path[1:], strict=False):
        steps = max(1, int(max(abs(bx - ax), abs(by - ay)) / 0.05))
        for i in range(steps + 1):
            x, y = ax + (bx - ax) * i / steps, ay + (by - ay) * i / steps
            if x0 + 0.05 < x < x1 - 0.05 and y0 + 0.05 < y < y1 - 0.05:
                return True
    return False


def test_signal_lines_leave_the_bubble_outwards(empty: Path):
    """The review's case: the measuring line takes the bubble's Bottom node, then the signal to
    the valve below must not start at Left/Right heading through the bubble's centre; and a
    second signal from the same instrument must not run from Top down through the bubble."""
    baseline = _findings(empty.parents[1])
    p = _build_section(empty, signals=False)
    p.paste(
        p.make(
            "instrument",
            "Inst_FIC4110",
            tag="FIC-4110",
            at="170,110",
            sense="Line_LOX4102_S1:170,140",
        )
    )
    made = p.make("signal", "Sig_FIC4110", source="Inst_FIC4110", target="LV4107", fail_action="FO")
    p.paste(made)
    path = _line_path(p.root, made)
    assert not _crosses_circle(path, (170, 110), 3.75), path
    made = p.make("signal", "Sig_LIC4107", source="Inst_LIC4107", target="Inst_FIC4110")
    p.paste(made)
    path = _line_path(p.root, made)
    assert not _crosses_circle(path, (170, 110), 3.75), path
    assert not _crosses_circle(path, (40, 100), 3.75), path
    assert _new(empty, baseline) == []
    # The same relation again: a warning, and still clear of the bubble.
    made = p.make("signal", "Sig_FIC4110b", source="Inst_FIC4110", target="LV4107")
    assert any(n.startswith("WARNING") and "Sig_FIC4110" in n for n in made.notes), made.notes
    p.paste(made)
    assert not _crosses_circle(_line_path(p.root, made), (170, 110), 3.75)


def test_measuring_line_leaves_the_nozzle_away_from_its_equipment(empty: Path):
    """An instrument connection on the pump's right side, the bubble up and to the left: the
    line goes out to the right first instead of across the pump symbol."""
    p = _build_section(empty, signals=False)
    p.paste(p.make("nozzle", "P4101_I1", on="P4101", at="7.5,0"))
    made = p.make("instrument", "Inst_PI4120", tag="PI-4120", at="100,140", sense="P4101_I1")
    p.paste(made)
    root = p.root
    measuring = next(
        e
        for e in etree.fromstring(made.part("DRAWING").xml).iter("Object")
        if e.get("type") == "Core/Diagram.ConnectorLine"
    )
    inner = measuring.find("Data[@property='InnerPoints']")
    bends = [point_xy(v) for v in points_of(inner)] if inner is not None else []
    end = measuring.find("References[@property='Target']").get("objects").lstrip("#")
    end_xy = point_xy(
        root.find(f".//Object[@id='{end}']").find("Data[@property='Position']/AggregatedDataValue")
    )
    path = [(137.5, 170.0), *bends, end_xy]
    assert path[1][0] > 137.5 and abs(path[1][1] - 170) < 1e-6, path  # out to the right
    assert not _crosses_box(path, (122.5, 162.5, 137.5, 177.5)), path  # the 15 mm pump
    assert not _crosses_circle(path, (100, 140), 3.75), path


def test_column_markers(empty: Path):
    """Beds and trays inside a column come from --marker, no hand-typed ShapeUsage."""
    baseline = _findings(empty.parents[1])
    p = Paster(empty)
    made = p.make(
        "equipment",
        "C1101",
        item_class="ProcessColumn",
        tag="C-1101",
        shape="COLUMN_SHAPE",
        at="100,100",
        scale="1,3",
        markers=["COLUMN_PACKED_BED_SHAPE:-20:1.5", "column_tray:15:1:m", "COLUMN_TRAY_SHAPE:22"],
        nozzles=["N1:0,-30:100"],
    )
    p.paste(made)
    assert _new(empty, baseline) == []
    symbol = p.find("C1101_Symbol")
    usages = symbol.findall(".//Object[@type='Core/Diagram.ShapeUsage']")
    assert [u.get("id") for u in usages] == [
        "C1101_SymbolShape",
        "C1101_Marker1",
        "C1101_Marker2",
        "C1101_Marker3",
    ]
    bed = usages[1]
    assert bed.findtext("Data[@property='ScaleY']/Double") in ("1.5", "1.50")
    assert point_xy(bed.find("Data[@property='Position']/AggregatedDataValue")) == (100.0, 80.0)
    assert usages[2].findtext("Data[@property='IsMirrored']/Boolean") == "true"
    with pytest.raises(FragmentError, match="--marker"):
        make_fragment(
            "equipment", "C2", item_class="ProcessColumn", tag="C-2", at="1,1", markers=["X"]
        )


def test_fragment_cli_messages(plant: Path):
    result = runner.invoke(app, ["fragment", "valve", "extra", "--id", "V1", "--dn", "50"])
    assert result.exit_code == 2 and "valve takes no NAME argument" in result.output
    assert "--name" not in result.output
    result = runner.invoke(app, ["fragment", "signal", "Sig1", "--from", "A", "--to", "B"])
    assert result.exit_code == 2 and "--id Sig1" in result.output
    result = runner.invoke(
        app, ["fragment", "offpage", "--id", "O1", "--in", "--out", "--at", "1,1"]
    )
    assert result.exit_code == 2 and "not both" in result.output
    result = runner.invoke(
        app, ["fragment", "valve", "--id", "V1", "--dn", "50", "--at", "1,1", "--scale", "0.4,0.6"]
    )
    assert result.exit_code == 2 and "scales evenly" in result.output
    result = runner.invoke(
        app, ["fragment", "valve", "--id", "V1", "--dn", "50", "--at", "1,1", "--scale", "0.5"]
    )
    assert result.exit_code == 0, result.output
    # CI forces colour (Rich adds ANSI codes) and may wrap differently: compare the bare text.
    raw = runner.invoke(
        app, ["fragment", "--help"], terminal_width=200, env={"NO_COLOR": "1", "COLUMNS": "200"}
    ).output
    help_text = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", raw).replace("│", " ").split())
    for phrase in (
        "signal: the source instrument",
        "pipe/signal/instrument",
        "equipment/offpage",
        "--marker",
    ):
        assert phrase in help_text, phrase


def test_gate_valve_borrows_no_registration_number():
    """DEXPI's C02V03 gives ISO10628:2012-2101-A to its OPERATED_VALVE_SHAPE (a general valve,
    here VALVE_SHAPE); the gate valve has its own ISO 10628-2 number (ADR 0022)."""
    element = catalogue()["GATE_VALVE_SHAPE"]
    number = element.findtext("Data[@property='SymbolRegistrationNumber']/String")
    assert number == "ISO10628:2012-X8074-A"
    assert "2101" not in EMPTY.read_text(encoding="utf-8")


def _drawing_findings(root: Path) -> list[tuple[str, str]]:
    report = validate_workspace(Workspace.find(root))
    return sorted((f.rule, f.message) for f in report.findings if f.rule in DRAWING_RULES)


def test_router_output_is_drawing_clean(empty: Path):
    """The section drawn from fragments only comes out clean for the drawing
    lint.

    Before, LIC-4107's signal to LV-4107 ran down through the LSLL-4108 bubble and its
    letters and across the suction line LOX-4101, and the suction line ran through T-4101's
    tag (put below the tank, where its outlet nozzle is). The router now keeps clear of the
    drawn bubbles, equipment and texts and avoids crossing pipes, and the tag goes clear of
    the outlet nozzle (`builders.tag_label_spot`).
    """
    p = _build_section(empty)
    found = _drawing_findings(empty.parents[1])
    assert found == [], "\n".join(map(str, found))
    tag = p.find("T4101_TagText")
    assert point_xy(tag.find("Data[@property='Position']/AggregatedDataValue"))[1] < 110
    # A flow loop on the discharge line, its signal to the same valve: still clean.
    p.paste(
        p.make(
            "instrument",
            "Inst_FIC4110",
            tag="FIC-4110",
            at="195,115",
            sense="Line_LOX4102_S1:190,140",
        )
    )
    p.paste(p.make("signal", "Sig_FIC4110", source="Inst_FIC4110", target="LV4107"))
    p.paste(p.make("signal", "Sig_LIC4107_FIC", source="Inst_LIC4107", target="Inst_FIC4110"))
    found = _drawing_findings(empty.parents[1])
    assert found == [], "\n".join(map(str, found))
