"""P&ID rendering and default placement: field bubble extent (pre-release issue 35), equipment tag
labels clear of nozzles (pre-release issue 37), inline items emphasised on full-sheet renders
(pre-release issue 41) and the shape catalogue covering the ASU sheets' equipment
(pre-release issue 15)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.authoring._xml import extent
from chemeascode.domains.piping.authoring.builders import BUBBLE_SHAPES, tag_label_spot
from chemeascode.domains.piping.authoring.fragment import make_fragment
from chemeascode.domains.piping.authoring.shapes import EQUIPMENT_SHAPES, catalogue
from chemeascode.domains.piping.drawing import segment_box_distance, text_box, text_width
from chemeascode.domains.piping.render import emphasise_inline, inline_ids, load_model, svg_element
from chemeascode.interfaces.cli import app
from tests.conftest import REFERENCE

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[1]
EMPTY = ROOT / "src/chemeascode/domains/piping/skills/dexpi-xml/snippets/empty-sheet.xml"


@pytest.fixture
def empty(plant: Path) -> Path:
    path = plant / "pid" / "P-01.xml"
    shutil.copy(EMPTY, path)
    return path


def _texts(xml: str) -> dict[str, tuple[float, float, float, str]]:
    """id -> (x, y, size, text) of each Core/Diagram.Text in a fragment part."""
    found = {}
    for text in etree.fromstring(xml).iter("Object"):
        if text.get("type") != "Core/Diagram.Text":
            continue
        x = float(text.findtext("Data[@property='Position']//Data[@property='X']/Double"))
        y = float(text.findtext("Data[@property='Position']//Data[@property='Y']/Double"))
        size = float(text.findtext("Data[@property='Size']/Double"))
        found[text.get("id")] = (x, y, size, text.findtext("Data[@property='Text']/String") or "")
    return found


# -- pre-release issue 35: the field bubble is as wide as the central one --------------------------


def test_field_bubble_extent_counts_its_arcs():
    shapes = catalogue()
    # Lines from x = -3 to 3 and arcs of radius 3.75 around x = +-3: 13.5 x 7.5 mm.
    assert extent(shapes["INSTRUMENTATION_BUBBLE_SHAPE_FIELD"]) == (-6.75, -3.75, 6.75, 3.75)
    assert extent(shapes["INSTRUMENTATION_BUBBLE_SHAPE_CENTRAL"]) == (-6.75, -3.75, 6.75, 3.75)
    # The dished heads are arcs too: the vessel is 30 mm high, not 25.
    assert extent(shapes["VESSEL_WITH_DISHED_HEADS_SHAPE"]) == (-10.0, -15.0, 10.0, 15.0)


def test_bubble_half_sizes_match_the_catalogue():
    shapes = catalogue()
    for name, _, half_x, half_y in BUBBLE_SHAPES.values():
        assert extent(shapes[name]) == (-half_x, -half_y, half_x, half_y), name


def test_api_field_instrument_measuring_line_ends_on_the_bubble(empty: Path):
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, instrument

    sheet = Sheet.load(empty)
    tank = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(50, 100),
        nozzles=[Nozzle("N1", (10, 0), 50)],
    )
    instrument(
        sheet, "PI-101", at=(100, 100), sensing=tank["N1"], sensing_at=(60, 100), location="field"
    )
    sheet.save()
    position = sheet.find("Inst_PI101_BubblePosition")
    x = float(position.findtext(".//Data[@property='X']/Double"))
    assert x == pytest.approx(100 - 6.75)


@pytest.mark.parametrize("field", [True, False])
def test_fragment_instrument_letters_stay_inside_the_bubble(field: bool):
    made = make_fragment(
        "instrument", "Inst1", tag="PICSA-4712.02", at="100,100", sense="N1:100,130", field=field
    )
    texts = _texts(made.part("DRAWING").xml)
    letters, number = texts["Inst1_Letters"], texts["Inst1_Number"]
    top = text_box(letters[0], letters[1], letters[3], letters[2], "middle", "middle")[1]
    bottom = text_box(number[0], number[1], number[3], number[2], "middle", "middle")[3]
    # The bubble's top and bottom lines are at 100 -+ 3.75, drawn 0.2 mm wide.
    assert top >= 100 - 3.75 + 0.1, top
    assert bottom <= 100 + 3.75 - 0.1, bottom
    if field:  # no middle line: the two lines are centred, the capitals clear of the top
        assert top >= 100 - 3.75 + 0.5, top


# -- pre-release issue 37: equipment tag labels avoid the nozzles' pipes ---------------------------


def _label_box(x: float, y: float, text: str, size: float) -> tuple[float, float, float, float]:
    width, height = text_width(text, size), size * 0.716
    return (x - width / 2, y - height / 2, x + width / 2, y + height / 2)


def test_tag_label_spot_without_nozzles_is_below():
    (x, y), clear = tag_label_spot((100, 100), (-10, -15, 10, 15), [], "T-1", 4.5, 4.0)
    assert clear and (x, y) == (100, 119)


def test_tag_label_spot_leaves_the_bottom_to_a_bottom_nozzle():
    nozzles = [((0.0, 15.0), (0.0, 1.0))]
    (x, y), clear = tag_label_spot((100, 100), (-10, -15, 10, 15), nozzles, "T-1", 4.5, 4.0)
    assert clear and y < 100  # above
    nozzles += [((0.0, -15.0), (0.0, -1.0))]
    (x, y), clear = tag_label_spot((100, 100), (-10, -15, 10, 15), nozzles, "T-1", 4.5, 4.0)
    assert clear and x > 110 and y == 100  # to the right


def test_tag_label_spot_reports_when_every_spot_is_crossed():
    # Nozzles on all sides and at the corners, each pipe running past the label spots.
    nozzles = [((dx, dy), (ux, uy)) for dx, dy, ux, uy in [
        (-6, 15, 0, 1), (0, 15, 0, 1), (6, 15, 0, 1), (8, 15, 0, 1), (-8, 15, 0, 1),
        (-6, -15, 0, -1), (0, -15, 0, -1), (6, -15, 0, -1), (8, -15, 0, -1), (-8, -15, 0, -1),
        (10, 0, 1, 0), (-10, 0, -1, 0), (10, 19, 1, 0), (-10, 19, -1, 0),
        (10, -19, 1, 0), (-10, -19, -1, 0),
    ]]  # fmt: skip
    (x, y), clear = tag_label_spot((100, 100), (-10, -15, 10, 15), nozzles, "T-1", 4.5, 4.0)
    assert not clear and (x, y) == (100, 119)


def test_api_equipment_label_clear_of_a_bottom_nozzle(empty: Path):
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment

    sheet = Sheet.load(empty)
    equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(100, 100),
        nozzles=[Nozzle("N1", (0, 15), 80), Nozzle("N2", (10, 0), 50)],
    )
    equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 100),
        nozzles=[Nozzle("N1", (10, 0), 50)],
    )
    sheet.save()
    texts = _texts(etree.tostring(sheet.find("T1_Drawing")).decode())
    (x, y, size, text) = next(iter(texts.values()))
    box = _label_box(x, y, "T-1", size)
    assert segment_box_distance((100, 115), (100, 155), box) >= 1.0
    assert segment_box_distance((110, 100), (150, 100), box) >= 1.0
    assert y < 100 - 15  # above the vessel
    # Without a bottom nozzle the label stays 4 mm below the symbol.
    (x2, y2, _, _) = next(iter(_texts(etree.tostring(sheet.find("T2_Drawing")).decode()).values()))
    assert (x2, y2) == (200, 119)


def test_fragment_equipment_label_clear_of_a_bottom_nozzle(empty: Path):
    made = make_fragment(
        "equipment",
        "K1",
        item_class="CentrifugalPump",
        tag="P-101",
        at="100,100",
        nozzles=["N1:-7.5,0:80", "N2:0,7.5:80"],
        sheet=empty,
    )
    x, y, size, _ = _texts(made.part("DRAWING").xml)["K1_TagText"]
    box = _label_box(x, y, "P-101", size)
    assert segment_box_distance((100, 107.5), (100, 150), box) >= 1.0
    assert segment_box_distance((92.5, 100), (50, 100), box) >= 1.0
    assert any("clear of the nozzles" in n for n in made.notes), made.notes


# -- pre-release issue 41: inline items emphasised on a render -------------------------------------

_SCALE = re.compile(r"scale\(([-\d.]+),([-\d.]+)\)")


def _group(svg: etree._Element, object_id: str) -> etree._Element:
    return next(g for g in svg.iter("{*}g") if g.get("id") == object_id)


def test_inline_ids_are_the_valves_fittings_and_actuators():
    found = inline_ids(load_model(REFERENCE))
    assert {"BallValve1", "GlobeValve2", "PipeReducer1", "ControlledActuator1"} <= found
    assert not {"CentrifugalPump1", "Tank1", "PipingNetworkSegment3", "Pipe3"} & found


def test_emphasise_inline_scales_valves_and_thickens_their_lines():
    model = load_model(REFERENCE)
    svg = svg_element(model)
    plain = etree.tostring(_group(svg, "Pipe3"))
    emphasise_inline(svg, model)
    valve = next(g for g in _group(svg, "BallValve1").iter("{*}g") if g.get("transform"))
    assert _SCALE.search(valve.get("transform")).groups() == ("0.6", "0.6")
    assert valve.get("transform").startswith("translate(231.00,154.00)")
    assert {e.get("stroke-width") for e in valve if e.get("stroke-width")} == {"0.5"}
    actuator = next(
        g for g in _group(svg, "ControlledActuator1").iter("{*}g") if g.get("transform")
    )
    assert _SCALE.search(actuator.get("transform")).groups() == ("0.675", "0.675")
    # Pipes, labels and equipment are drawn as before.
    assert etree.tostring(_group(svg, "Pipe3")) == plain
    pump = next(g for g in _group(svg, "CentrifugalPump1").iter("{*}g") if g.get("transform"))
    assert "scale(0.70,0.70)" in pump.get("transform")
    label = next(t for t in _group(svg, "BallValve1").iter("{*}text"))
    assert label.get("font-size") == "3.0"


def test_render_emphasise_inline_writes_its_own_file(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    plain = runner.invoke(app, ["render", "pid/P-01.xml"])
    assert plain.exit_code == 0, plain.output
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--emphasise-inline"])
    assert result.exit_code == 0, result.output
    out = plant / "build" / "P-01_inline.svg"
    assert out.is_file() and "P-01_inline.svg" in result.output
    assert (plant / "build" / "P-01.svg").read_text() != out.read_text()
    tiles = runner.invoke(app, ["render", "pid/P-01.xml", "--emphasise-inline", "--tiles", "2x1"])
    assert tiles.exit_code == 0, tiles.output
    assert (plant / "build" / "P-01_inline_tile-A1.svg").is_file()


# -- pre-release issue 15: the catalogue draws what the ASU sheets needed custom shapes for --------

#: The classes ASU-1 drew with custom ShapeASU_* symbols (P-01 to P-04, before the catalogue had
#: them), and the catalogue shape for each that has no class default.
ASU_CUSTOM = {
    "GasFilter": None,
    "CentrifugalCompressor": None,
    "TubularHeatExchanger": None,
    "ProcessColumn": None,
    "PressureVessel": None,
    "ElectricHeater": None,
    "PlateHeatExchanger": "PLATE_FIN_HEAT_EXCHANGER_SHAPE",
    "Turbine": None,
    "Tank": "TANK_CONE_ROOF_SHAPE",
    "HeatExchanger": "AMBIENT_VAPORIZER_SHAPE",
    "Silencer": "SILENCER_SHAPE",
}


def test_catalogue_covers_the_asu_custom_shapes():
    shapes = catalogue()
    for cls, named in ASU_CUSTOM.items():
        name = named or EQUIPMENT_SHAPES[cls]
        assert name in shapes, (cls, name)
        number = shapes[name].findtext("Data[@property='SymbolRegistrationNumber']/String")
        assert number is None or not number.startswith("ASU-"), (name, number)
