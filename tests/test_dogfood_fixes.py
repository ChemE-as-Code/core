"""Regression tests for the defects the 0.4 dogfood found (D1-D15 in its report)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from chemeascode.templates.install import bundled_skills, init
from tests.conftest import git

runner = CliRunner()
EMPTY = Path(str(bundled_skills()["dexpi-xml"])) / "snippets" / "empty-sheet.xml"


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "plant"
    init(root, "Test plant")
    git(root, "init", "-q", "-b", "main")
    monkeypatch.chdir(root)
    shutil.copy(EMPTY, root / "pid" / "P-01.xml")
    return root


def invoke(*args: str):
    return runner.invoke(app, list(args))


def _findings(*args: str) -> list[dict]:
    result = invoke("validate", "--json", *args)
    return json.loads(result.output)["findings"]


def _errors(*args: str) -> list[dict]:
    return [f for f in _findings(*args) if f["level"] == "error"]


def _two_tanks(sheet, via=None):
    from chemeascode.domains.piping.authoring import Nozzle, equipment, line

    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80), Nozzle("N2", (0, -15), 25)],
    )
    b = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    route = [a["N1"], via, b["N1"]] if via is not None else [a["N1"], b["N1"]]
    made = line(sheet, "80-A-1", dn=80, route=route)
    return a, b, made


# -- D1: instrument(sensing=<line id or equipment>) --------------------------------------------


def test_instrument_sensing_a_line_id_measures_on_its_segment(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, instrument

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _, _, made = _two_tanks(sheet)
    instrument(sheet, "FI-101", at=(130, 70), sensing=made.id, sensing_at=(130, 100))
    instrument(sheet, "FI-102", at=(160, 70), sensing=made, sensing_at=(160, 100))
    sheet.save()
    function = sheet.find("Inst_FI101")
    sensing = function.find(".//References[@property='SensingLocation']")
    assert sensing is not None and sensing.get("objects") == f"#{made.segments[0]}"
    assert not _errors("pid/P-01.xml")


def test_instrument_refuses_equipment_as_sensing_location(fresh: Path):
    from chemeascode.domains.piping.authoring import AuthoringError, Sheet, instrument

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a, _, _ = _two_tanks(sheet)
    with pytest.raises(AuthoringError, match="not a sensing location"):
        instrument(sheet, "LI-101", at=(40, 60), sensing=a, sensing_at=(60, 100))
    with pytest.raises(AuthoringError, match="not a sensing location"):
        instrument(sheet, "LI-102", at=(40, 60), sensing=a.id, sensing_at=(60, 100))
    assert not sheet.has("Inst_LI101") and not sheet.has("Inst_LI102")


def test_instrument_finds_where_a_nozzle_given_by_id_is_drawn(fresh: Path):
    """D11: sensing=<nozzle id> without sensing_at starts the measuring line at the nozzle."""
    from chemeascode.domains.piping.authoring import Sheet, instrument

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _two_tanks(sheet)
    instrument(sheet, "PI-101", at=(40, 60), sensing="T1_N2")
    sheet.save()
    assert sheet.has("Inst_PI101")


def test_save_refused_by_pydexpi_leaves_the_sheet_on_disk(fresh: Path):
    """D1: a refused save no longer overwrites the sheet with a broken file."""
    from chemeascode.domains.piping.authoring import AuthoringError, Sheet, instrument

    path = fresh / "pid" / "P-01.xml"
    sheet = Sheet.load(path)
    _, _, made = _two_tanks(sheet)
    sheet.save()
    before = path.read_bytes()
    instrument(sheet, "FI-101", at=(130, 70), sensing=made, sensing_at=(130, 100))
    # What the old API wrote for a line id: a SensingLocation on the PipingNetworkSystem.
    sheet.find("Inst_FI101").find(".//References[@property='SensingLocation']").set(
        "objects", f"#{made.id}"
    )
    with pytest.raises(AuthoringError, match="not written"):
        sheet.save()
    assert path.read_bytes() == before
    assert (fresh / "pid" / "P-01.refused.xml").is_file()


# -- D5, D7: texts outside the frame or the title block, lines through bubbles ----------------


def test_offpage_note_at_the_sheet_edge_stays_inside_the_frame(fresh: Path):
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line, offpage

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 150),
        nozzles=[Nozzle("N1", (-10, 0), 80), Nozzle("N2", (10, 0), 80)],
    )
    line(sheet, "80-A-1", dn=80, route=[offpage("in", at=(15, 150), note="from P-02"), a["N1"]])
    line(sheet, "80-A-2", dn=80, route=[a["N2"], offpage("out", at=(405, 150), note="to P-03")])
    sheet.save()
    assert not [f for f in _findings("pid/P-01.xml") if f["rule"].endswith("outside-frame")]
    printed = invoke(
        "fragment", "offpage", "--id", "OPC9", "--out", "--at", "400,250", "--note", "to P-04",
        "--sheet", "pid/P-01.xml",
    )  # fmt: skip
    assert printed.exit_code == 0, printed.output
    assert "CenterCenter" in printed.output


def test_lint_reports_text_outside_the_frame_and_an_overflowing_title(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, note

    started = invoke(
        "sheet", "new", "P-02", "--title",
        "Air compression, purification, cold box and LIN backup",
    )  # fmt: skip
    assert started.exit_code == 0, started.output
    sheet = Sheet.load(fresh / "pid" / "P-02.xml")
    note(sheet, "a note that starts left of the frame", at=(2, 150))
    sheet.save()
    rules = [f["rule"] for f in _findings("pid/P-02.xml")]
    assert "cheme.text-outside-frame" in rules
    assert "cheme.title-text-overflow" in rules


def test_lint_reports_a_pipe_through_an_instrument_bubble(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, instrument

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _, _, made = _two_tanks(sheet)
    instrument(sheet, "TI-101", at=(130, 100))  # the bubble sits on the pipe
    instrument(sheet, "TI-102", at=(160, 120), sensing=made, sensing_at=(160, 100))
    sheet.save()
    through = [f for f in _findings("pid/P-01.xml") if f["rule"].endswith("line-through-symbol")]
    assert len(through) == 1 and "TI-101" in through[0]["message"], through


# -- D6: round symbols' extents -----------------------------------------------------------------


def test_shape_extent_includes_circles_and_ellipses(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    for name in ("CENTRIFUGAL_COMPRESSOR_SHAPE", "HEAT_EXCHANGER_GENERAL_SHAPE"):
        if name not in sheet.shapes:
            continue
        x0, y0, x1, y1 = sheet.shape_extent(sheet.shape(name))
        assert x1 - x0 >= 15 and y1 - y0 >= 15, name


# -- Cause and effect without control/cause-effect.yaml ---------------------------------------


def test_trip_instrument_asks_for_the_cause_effect_file_when_there_is_none(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, instrument

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _, _, made = _two_tanks(sheet)
    instrument(sheet, "PSHH-101", at=(130, 120), sensing=made, sensing_at=(130, 100))
    sheet.save()
    (fresh / "control" / "cause-effect.yaml").unlink(missing_ok=True)
    found = [f for f in _findings() if f["rule"] == "cheme.instrument-no-interlock"]
    assert found and "PSHH-101" in found[0]["message"], found
    assert "no such file" in found[0]["message"]


# -- D13: validate a file of another plant ----------------------------------------------------


def test_validate_refuses_a_path_outside_the_plant(fresh: Path, tmp_path: Path):
    other = tmp_path / "other.yaml"
    other.write_text("items: []\n")
    result = invoke("validate", str(other))
    assert result.exit_code == 2
    assert "not in this plant" in result.output
    assert invoke("validate", "pid/NOPE.xml").exit_code == 2


# -- D14: show prints a shared control chain once ---------------------------------------------


def test_show_prints_the_instrumentation_of_a_tag_once(fresh: Path):
    from chemeascode.domains.piping.authoring import (
        Nozzle,
        Sheet,
        equipment,
        instrument,
        line,
        valve,
    )

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80)],
    )
    b = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(240, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    made = line(
        sheet,
        "80-A-1",
        dn=80,
        route=[a["N1"], valve("PV1", "GlobeValve", at=(180, 100), tag="PV-101"), b["N1"]],
    )
    instrument(
        sheet, "PIC-101", at=(110, 130), sensing=made, sensing_at=(110, 100), signal_to="PV1"
    )
    sheet.save()
    shown = invoke("show", "PV-101")
    assert shown.exit_code == 0, shown.output
    assert shown.output.count("instrumentation (1 function(s))") == 1, shown.output
    assert shown.output.count("instrumentation: as above") == 2, shown.output


# -- D3: side nozzles of a tall column ----------------------------------------------------------


def _rotations(output: str) -> dict[str, float]:
    from lxml import etree

    found = {}
    for part in output.split("<!--")[1:]:
        xml = part.split("-->", 1)[1].strip()
        if not xml.startswith("<"):
            continue
        for element in etree.fromstring(f"<x>{xml}</x>").iter("Object"):
            rotation = element.findtext("Data[@property='Rotation']/Double")
            if element.get("type") == "Core/Diagram.ShapeUsage" and rotation is not None:
                found[element.get("id")] = float(rotation)
    return found


def test_fragment_equipment_side_nozzle_of_a_tall_column_points_sideways(fresh: Path):
    result = invoke(
        "fragment", "equipment", "--id", "C1", "--class", "ProcessColumn", "--tag", "C-1",
        "--shape", "COLUMN_SHAPE", "--at", "250,140", "--scale", "1,1.6",
        "--nozzle", "N1:-10,40:80", "--nozzle", "N2:0,-80:80", "--nozzle", "N3:10,30:50:up",
        "--sheet", "pid/P-01.xml",
    )  # fmt: skip
    if result.exit_code != 0 and "COLUMN_SHAPE" in result.output:
        pytest.skip(result.output)
    assert result.exit_code == 0, result.output
    rotations = _rotations(result.output)
    nozzle = {k.split("_")[1]: v for k, v in rotations.items() if k.startswith("C1_N")}
    assert nozzle["N1"] == 180  # left
    assert nozzle["N2"] == 270  # up
    assert nozzle["N3"] == 270  # as asked


# -- D4: fragment signal from an instrument drawn by the authoring API -------------------------


def test_fragment_signal_starts_at_the_bubble_not_at_the_tap(fresh: Path):
    from chemeascode.domains.piping.authoring import (
        Nozzle,
        Sheet,
        equipment,
        instrument,
        line,
        valve,
    )

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80)],
    )
    b = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(240, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    made = line(
        sheet,
        "80-A-1",
        dn=80,
        route=[a["N1"], valve("XV1", "BallValve", at=(180, 100), tag="XV-1"), b["N1"]],
    )
    instrument(sheet, "PT-101", at=(110, 130), sensing=made, sensing_at=(110, 100))
    sheet.save()
    result = invoke(
        "fragment", "signal", "--id", "Sig_PT101_XV1", "--from", "Inst_PT101", "--to", "XV1",
        "--sheet", "pid/P-01.xml",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "#Inst_PT101_SensePosition" not in result.output
    assert "#Inst_PT101_BubblePosition" in result.output


# -- D2: copy --sense-at of an instrument drawn by the authoring API ---------------------------


def test_copy_sense_at_moves_the_copied_measuring_line_instead_of_adding_one(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, instrument
    from chemeascode.domains.piping.authoring._xml import point_xy

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _, _, made = _two_tanks(sheet)
    instrument(sheet, "TI-101", at=(110, 120), sensing=made, sensing_at=(110, 100))
    sheet.save()
    result = invoke(
        "copy", "TI-101", "--prefix", "Inst_TI102", "--tag", "TI-102", "--offset", "50,-40",
        "--sense-at", f"{made.segments[0]}:160,100",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert "no measuring line of the copy was left open" not in result.output
    assert not _errors("pid/P-01.xml")
    copied = Sheet.load(fresh / "pid" / "P-01.xml")

    def at(object_id: str):
        return point_xy(copied.find(object_id).find("Data[@property='Position']/*"))

    assert at("Inst_TI102_SensePosition") == (160, 100)
    # The bubble is at 160,80 now: the line leaves it at the bottom, towards the pipe.
    bubble = at("Inst_TI102_BubblePosition")
    assert bubble[0] == 160 and bubble[1] > 80


# -- D10: equipment(scale=(sx, sy), markers=[...]) -------------------------------------------


def _usages(sheet, object_id: str) -> dict[str, tuple[str, float, float, float, bool]]:
    found = {}
    for element in sheet.find(f"{object_id}_Drawing").iter("Object"):
        if element.get("type") != "Core/Diagram.ShapeUsage":
            continue
        shape = element.find("References[@property='Shape']").get("objects").lstrip("#")
        y = float(element.findtext("Data[@property='Position']//Data[@property='Y']/Double"))
        found[element.get("id")] = (
            shape,
            y,
            float(element.findtext("Data[@property='ScaleX']/Double")),
            float(element.findtext("Data[@property='ScaleY']/Double")),
            element.findtext("Data[@property='IsMirrored']/Boolean") == "true",
        )
    return found


def test_equipment_takes_an_anisotropic_scale_and_column_markers(fresh: Path):
    from lxml import etree

    from chemeascode.domains.piping.authoring import Marker, Nozzle, Sheet, equipment

    path = fresh / "pid" / "P-01.xml"
    # A sheet from an older template: its catalogue has no tray shape.
    root = etree.parse(str(path))
    for shape in root.iter("Object"):
        if shape.findtext("Data[@property='Name']/String") == "COLUMN_TRAY_SHAPE":
            shape.getparent().remove(shape)
    root.write(str(path), xml_declaration=True, encoding="UTF-8")
    sheet = Sheet.load(path)
    assert "COLUMN_TRAY_SHAPE" not in sheet.shapes
    column = equipment(
        sheet,
        "ProcessColumn",
        "C-1",
        shape="COLUMN_SHAPE",
        at=(200, 140),
        scale=(1.0, 1.6),
        markers=[
            Marker("COLUMN_PACKED_BED_SHAPE", -20, 1.5),
            ("column-tray", 10),
            "COLUMN_TRAY_SHAPE:20:1:m",
        ],
        nozzles=[Nozzle("N1", (0, -40), 50)],
    )
    usages = _usages(sheet, column.id)
    symbol = usages["C1_SymbolShape"]
    assert symbol[2:4] == (1.0, 1.6)
    bed, tray, mirrored = usages["C1_Marker1"], usages["C1_Marker2"], usages["C1_Marker3"]
    assert bed[0] == sheet.shapes["COLUMN_PACKED_BED_SHAPE"]
    assert (bed[1], bed[2], bed[3], bed[4]) == (120.0, 1.0, 1.5, False)
    assert tray[0] == sheet.shapes["COLUMN_TRAY_SHAPE"] and tray[1] == 150.0
    assert mirrored[4] is True
    sheet.save()
    assert not _errors("pid/P-01.xml")


def test_equipment_refuses_a_bad_marker(fresh: Path):
    from chemeascode.domains.piping.authoring import AuthoringError, Sheet, equipment

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    with pytest.raises(AuthoringError, match="NAME:dy"):
        equipment(sheet, "ProcessColumn", "C-1", shape="COLUMN_SHAPE", at=(200, 140),
                  markers=["COLUMN_TRAY_SHAPE"])  # fmt: skip
    with pytest.raises(AuthoringError, match="no shape"):
        equipment(sheet, "ProcessColumn", "C-1", shape="COLUMN_SHAPE", at=(200, 140),
                  markers=[("NO_SUCH_SHAPE", 0)])  # fmt: skip
    with pytest.raises(AuthoringError, match="scale must be positive"):
        equipment(sheet, "ProcessColumn", "C-1", shape="COLUMN_SHAPE", at=(200, 140),
                  scale=(1.0, 0))  # fmt: skip
    # Nothing of the refused columns is left behind.
    assert not sheet.has("C1")


# -- D12: rename a valve tag shared with its actuating system ---------------------------------


def _actuated_valve(fresh: Path, instrument_tag: str) -> None:
    from chemeascode.domains.piping.authoring import Sheet, instrument, valve

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _two_tanks(sheet, via=valve("XV104", "BallValve", at=(130, 100), tag="XV-104"))
    instrument(sheet, instrument_tag, at=(130, 70), signal_to="XV104")
    sheet.save()


@pytest.mark.parametrize("instrument_tag", ["XV-104", "HS-104"])
def test_rename_retags_a_valve_with_its_actuation_chain(fresh: Path, instrument_tag: str):
    from chemeascode.domains.piping.authoring import Sheet

    _actuated_valve(fresh, instrument_tag)
    result = invoke("rename", "XV-104", "XV-105", "--ids")
    assert result.exit_code == 0, result.output
    assert "its actuation chain: retagged together" in result.output
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    assert not sheet.has("XV104") and sheet.has("XV105")
    text = (fresh / "pid" / "P-01.xml").read_text()
    assert "XV-104" not in text
    assert text.count("<String>XV-105</String>") >= 3  # valve, actuating system and function
    if instrument_tag == "HS-104":  # the hand switch keeps its own tag
        assert invoke("show", "HS-104").exit_code == 0
    assert not _errors("pid/P-01.xml")


def test_rename_with_ids_leaves_ids_that_only_contain_the_tag(fresh: Path):
    """Renaming vessel V-101 with --ids keeps the ids of valve FV-101 (FV101)
    (pre-release issue 213)."""
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line, valve

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    vessel = equipment(
        sheet,
        "Tank",
        "V-101",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80)],
    )
    tank = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    via = valve("FV101", "BallValve", at=(130, 100), tag="FV-101")
    line(sheet, "80-A-1", dn=80, route=[vessel["N1"], via, tank["N1"]])
    sheet.save()
    # Outside the vessel an id spells the whole tag (scope); inside it one holds a longer tag
    # (the whole-tag match).
    assert invoke("rename", "T2", "Spare_V101_T2").exit_code == 0
    assert invoke("rename", "V101_N1", "V101_XV101").exit_code == 0
    before = Sheet.load(fresh / "pid" / "P-01.xml")
    fv_ids = sorted(i for i in before.index.by_id if i.startswith("FV101"))
    assert fv_ids

    result = invoke("rename", "V-101", "V-105", "--ids")
    assert result.exit_code == 0, result.output
    after = Sheet.load(fresh / "pid" / "P-01.xml")
    assert after.has("V105") and not after.has("V101")
    assert after.has("Spare_V101_T2") and after.has("V105_XV101")
    assert sorted(i for i in after.index.by_id if i.startswith("FV10")) == fv_ids
    assert "FV105" not in result.output
    assert invoke("show", "FV-101").exit_code == 0
    assert not _errors("pid/P-01.xml")


def test_rename_with_ids_of_a_valve_and_its_chain_keeps_the_instrument_ids(
    tmp_path: Path, monkeypatch
):
    """safety-hazop: FV-104 with --ids renames the FV104* ids, never Inst_FIC104_*
    (pre-release issue 213)."""
    from chemeascode.domains.piping.authoring import Sheet

    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).parents[1] / "examples" / "safety-hazop", root)
    monkeypatch.chdir(root)
    sheet = root / "pid" / "P-01.xml"
    before = set(Sheet.load(sheet).index.by_id)
    valve_ids = sorted(i for i in before if i.startswith("FV104"))
    assert len(valve_ids) >= 10

    result = invoke("rename", "FV-104", "FV-107", "--ids")
    assert result.exit_code == 0, result.output
    after = set(Sheet.load(sheet).index.by_id)
    assert sorted(i for i in after if i.startswith("FV107")) == [
        "FV107" + i[len("FV104") :] for i in valve_ids
    ]
    assert not [i for i in after if i.startswith("FV104")]
    assert {i for i in before if "FIC104" in i} <= after


def test_rename_still_refuses_a_tag_shared_with_an_unrelated_object(fresh: Path):
    from chemeascode.domains.piping.authoring import Sheet, equipment, valve

    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    _two_tanks(sheet, via=valve("XV104", "BallValve", at=(130, 100), tag="XV-104"))
    equipment(
        sheet, "Tank", "XV-104", id="T3", shape="VESSEL_WITH_DISHED_HEADS_SHAPE", at=(130, 160)
    )
    sheet.save()
    result = invoke("rename", "XV-104", "XV-105")
    assert result.exit_code != 0
    assert "names 2 objects" in result.output
