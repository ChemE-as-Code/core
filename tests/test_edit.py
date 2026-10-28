"""cheme move / rename / set (pre-release issue 14), the copy options that adapt a copy
(pre-release issue 8), and cheme.duplicate-tag."""

from collections import Counter
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.authoring.copy import CopyError, copy_object
from chemeascode.domains.piping.authoring.edit import EditError, move_object, rename, set_values
from chemeascode.domains.piping.drawing import RULES as DRAWING_RULES
from chemeascode.domains.piping.fmt import format_file
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace

runner = CliRunner()


@pytest.fixture
def sheet(plant: Path) -> Path:
    path = plant / "pid" / "P-01.xml"
    format_file(path)
    return path


def _findings(root: Path) -> Counter:
    report = validate_workspace(Workspace.find(root))
    return Counter((f.level, f.rule, f.message) for f in report.findings)


def _new(path: Path, baseline: Counter) -> list[tuple[str, str, str]]:
    added = (_findings(path.parents[1]) - baseline).elements()
    # Drawing-geometry findings follow the drawing, not the model; tested in test_drawing.py.
    return sorted(f for f in added if f[0] != "info" and f[1] not in DRAWING_RULES)


def _root(path: Path) -> etree._Element:
    return etree.parse(str(path)).getroot()


def _obj(root: etree._Element, object_id: str) -> etree._Element:
    found = root.find(f".//Object[@id='{object_id}']")
    assert found is not None, object_id
    return found


def _xy(element: etree._Element) -> tuple[float, float]:
    point = element.find("Data[@property='Position']/AggregatedDataValue")
    return (
        float(point.findtext("Data[@property='X']/Double")),
        float(point.findtext("Data[@property='Y']/Double")),
    )


def _label_texts(root: etree._Element, object_id: str) -> set[str]:
    return {
        t.findtext("Data[@property='Text']/String")
        for t in root.iter("Object")
        if t.get("type") == "Core/Diagram.Text"
        and t.find(f".//References[@objects='#{object_id}']") is not None
    }


def _points(root: etree._Element) -> list[tuple[str, str]]:
    return [
        (p.getparent().getparent().get("property") or "", p.text or "") for p in root.iter("Double")
    ]


# -- copy (pre-release issue 8) --------------------------------------------------------------------


def test_copy_instrument_with_another_measured_variable_retags_sensor_and_actuator(sheet: Path):
    """An AI copied as FI must get the sensor FT, not AT (the ASU FQI-4149 / FI-4148 bug)."""
    baseline = _findings(sheet.parents[1])
    result = copy_object(
        sheet, "ProcessInstrumentationFunction2", "FIC2B", tag="FICSA-4713.02", offset=(30, 0)
    )
    root = _root(sheet)
    copy_ = _obj(root, "FIC2B")
    sensor = _obj(root, "FIC2B_ProcessSignalGeneratingFunction2")
    actuator = _obj(root, "FIC2B_ActuatingFunction1")
    assert copy_.findtext("Data[@property='ProcessInstrumentationFunctionCategory']/String") == "F"
    assert (
        sensor.findtext("Data[@property='ProcessSignalGeneratingFunctionNumber']/String")
        == "FT4713.02"
    )
    assert actuator.findtext("Data[@property='ActuatingFunctionNumber']/String") == "FV4713.02"
    assert "'FT4713.02'" in ", ".join(result.tag_fields)
    assert _label_texts(root, "FIC2B") == {"FICSA", "4713.02"}
    assert any("SensingLocation" in n and "--sense-at" in n for n in result.notes)
    new = _new(sheet, baseline)
    assert not [f for f in new if f[0] == "error" or "label-stale" in f[1]], new


def test_copy_line_sets_inner_tags_fluid_and_connects_in_one_command(sheet: Path):
    baseline = _findings(sheet.parents[1])
    # A spare pump, then its suction line copied from the duty pump's, connected to it.
    copy_object(sheet, "P4711", "Pump_B", tag="P4711B", offset=(0, 30))
    result = copy_object(
        sheet,
        "PipingNetworkSystem1",
        "Line_47199",
        tag="47199",
        offset=(0, 30),
        sets=[("FluidCode", "Nitrogen")],
        connects=[("Pipe1", "Pump_B_Nozzle1:Pump_B_PipingNode2")],
    )
    assert result.dropped == [], result.dropped
    root = _root(sheet)
    pipe = _obj(root, "Line_47199_Pipe1")
    assert pipe.find("References[@property='TargetItem']").get("objects") == "#Pump_B_Nozzle1"
    assert pipe.find("References[@property='TargetNode']").get("objects") == "#Pump_B_PipingNode2"
    segment = _obj(root, "Line_47199_PipingNetworkSegment1")
    assert segment.find("References[@property='TargetNode']").get("objects") == (
        "#Pump_B_PipingNode2"
    )
    line = _obj(root, "Line_47199_Pipe1_Drawing1_Groups1_Elements1")
    target = line.find("References[@property='Target']").get("objects").lstrip("#")
    assert _obj(root, target).find("References[@property='Node']").get("objects") == (
        "#Pump_B_PipingNode2"
    )
    for object_id in ("Line_47199", "Line_47199_PipingNetworkSegment1"):
        assert _obj(root, object_id).findtext("Data[@property='FluidCode']/String") == "Nitrogen"
    assert "Nitrogen 47199 75HB13 80" in _label_texts(root, "Line_47199")
    assert any(e.startswith("connected:") for e in result.edits)
    new = _new(sheet, baseline)
    assert [r for _, r, _ in new if r not in ("cheme.line-not-listed",)] == [
        "cheme.equipment-not-listed"
    ], new


def test_copy_renames_inner_tags_and_lists_the_duplicates_left(sheet: Path):
    # Give two valves of segment 3 plant-wide tags, then copy the line.
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "FV-4711")])
    plain = copy_object(sheet, "PipingNetworkSystem3", "Line_A", tag="47193", write=False)
    assert any(d.startswith("FV-4711: Line_A_GlobeValve2") for d in plain.duplicates)
    assert "duplicate tags (give each its own" in "\n".join(plain.report("P-01"))

    result = copy_object(
        sheet, "PipingNetworkSystem3", "Line_B", tag="47193", renames=[("FV-4711", "FV-4799")]
    )
    assert not [d for d in result.duplicates if d.startswith("FV-")], result.duplicates
    root = _root(sheet)
    # The id that spelled the tag follows it, and so does the valve's label.
    valve = _obj(root, "Line_B_GlobeValve2")
    assert valve.findtext("Data[@property='PipingComponentNumber']/String") == "FV-4799"
    assert any(e.startswith("renamed: FV-4711 -> FV-4799") for e in result.edits)
    with pytest.raises(CopyError, match="nothing in the copy has the tag"):
        copy_object(sheet, "PipingNetworkSystem3", "Line_C", renames=[("XX-1", "XX-2")])
    with pytest.raises(CopyError, match="no copied object has"):
        copy_object(sheet, "PipingNetworkSystem3", "Line_C", sets=[("TagName", "X")])


def test_copy_renumber_follows_ids_tags_and_labels(sheet: Path):
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "FV4711")])
    rename(sheet, "GlobeValve2", "Valve_FV4711")
    result = copy_object(
        sheet, "PipingNetworkSystem3", "Line_N", tag="47193", renumbers=[("4711", "4712")]
    )
    assert result.renamed["Valve_FV4711"] == "Line_N_Valve_FV4712"
    root = _root(sheet)
    valve = _obj(root, "Line_N_Valve_FV4712")
    assert valve.findtext("Data[@property='PipingComponentNumber']/String") == "FV4712"


def test_copy_sense_at_repoints_the_sensing_location_and_draws_its_node(sheet: Path):
    baseline = _findings(sheet.parents[1])
    result = copy_object(
        sheet,
        "ProcessInstrumentationFunction1",
        "PIF_X",
        tag="PI-4799.01",
        offset=(20, 0),
        sense_at="PipingNetworkSegment1:60,154",
    )
    root = _root(sheet)
    sensor = _obj(root, "PIF_X_ProcessSignalGeneratingFunction1")
    assert sensor.find("References[@property='SensingLocation']").get("objects") == (
        "#PipingNetworkSegment1"
    )
    position = _obj(root, "PIF_X_SensePosition")
    assert _xy(position) == (60.0, 154.0)
    line = _obj(root, "PIF_X_MeasuringLineFunction1_Drawing1_Groups1_Elements1")
    assert line.find("References[@property='Source']").get("objects") == "#PIF_X_SensePosition"
    assert not [d for d in result.dropped if "Source" in d]
    new = _new(sheet, baseline)
    assert not [f for f in new if f[0] == "error"], new


def test_copy_cli_takes_the_new_options(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    out = runner.invoke(
        app,
        [
            "copy",
            "PipingNetworkSystem1",
            "--prefix",
            "Line_Z",
            "--tag",
            "47198",
            "--set",
            "FluidCode=Nitrogen",
            "--print",
        ],
    )
    assert out.exit_code == 0, out.output
    assert "set: FluidCode = 'Nitrogen'" in out.output
    bad = runner.invoke(app, ["copy", "PipingNetworkSystem1", "--prefix", "Z", "--set", "X"])
    assert bad.exit_code == 2


# -- validate: duplicate tags ---------------------------------------------------------------------


def test_validate_reports_duplicate_piping_component_and_instrument_tags(sheet: Path):
    root_dir = sheet.parents[1]
    # The reference numbers valves per segment (C1, C2): not plant-wide tags, no finding.
    assert not [f for f in _findings(root_dir) if f[1] == "cheme.duplicate-tag"]
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "HV-4146")])
    set_values(sheet, "GlobeValve3", [("PipingComponentNumber", "HV-4146")])
    copy_object(sheet, "ProcessInstrumentationFunction1", "PIF_DUP", offset=(20, 0))
    report = validate_workspace(Workspace.find(root_dir))
    found = [f for f in report.findings if f.rule == "cheme.duplicate-tag"]
    assert {f.level for f in found} == {"error"}
    messages = " ".join(f.message for f in found)
    assert "piping component tag HV-4146" in messages and "instrument tag PI-4712.01" in messages
    assert all(f.line and f.hint for f in found)


def test_validate_reports_duplicate_tags_across_sheets(sheet: Path):
    import shutil

    root_dir = sheet.parents[1]
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "HV-4146")])
    shutil.copy(sheet, root_dir / "pid" / "P-02.xml")  # plant.yaml lists none: every pid/*.xml
    found = [
        f
        for f in validate_workspace(Workspace.find(root_dir)).findings
        if f.rule == "cheme.duplicate-tag"
    ]
    assert any(f.file == "pid/P-02.xml" and "pid/P-01.xml" in f.message for f in found), found


# -- move (pre-release issue 14) -------------------------------------------------------------------


def test_move_shifts_symbol_nodes_and_labels_only(sheet: Path):
    baseline = _findings(sheet.parents[1])
    before = _root(sheet)
    symbol_before = _xy(
        before.find(
            ".//Object[@id='CentrifugalPump1_Drawing1']//Object[@type='Core/Diagram.ShapeUsage']"
        )
    )
    result = move_object(sheet, "P4711", (-8, 12))
    after = _root(sheet)
    symbol = _xy(
        after.find(
            ".//Object[@id='CentrifugalPump1_Drawing1']//Object[@type='Core/Diagram.ShapeUsage']"
        )
    )
    assert symbol == (symbol_before[0] - 8, symbol_before[1] + 12)
    # Exactly the coordinates it reports moved changed, nothing else (X and Y of each point).
    changed = [(x, y) for x, y in zip(_points(before), _points(after), strict=True) if x != y]
    moved = [c for c in result.changes if " Position: " in c]
    assert len(moved) == 12 and len(changed) == 2 * len(moved)
    # The pipes at its nozzles follow by reference; their bends (if any) are reported.
    follows = [c for c in result.changes if "follows:" in c]
    assert len(follows) == 2 and all("now slanted" in c for c in follows), result.changes
    assert any("data table" in n or "data-table band" in n for n in result.notes), result.notes
    new = _new(sheet, baseline)
    assert not new, new


def test_move_print_changes_nothing_and_shows_a_diff(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    content = sheet.read_bytes()
    out = runner.invoke(app, ["move", "P4711", "--offset", "-8,12", "--print"])
    assert out.exit_code == 0, out.output
    assert sheet.read_bytes() == content
    assert "--- a/pid/P-01.xml" in out.output and "+++ b/pid/P-01.xml" in out.output


def test_move_and_rename_refuse_unknown_ids(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    for args in (
        ["move", "NoSuchThing", "--offset", "1,1"],
        ["rename", "NoSuchThing", "Other"],
        ["set", "NoSuchThing", "FluidCode=X"],
    ):
        out = runner.invoke(app, args)
        assert out.exit_code == 2 and "NoSuchThing" in out.output, (args, out.output)
    out = runner.invoke(app, ["move", "P4711", "--offset", "x"])
    assert out.exit_code == 2


# -- rename (pre-release issue 14) -----------------------------------------------------------------


def test_rename_with_children_leaves_no_dangling_reference(sheet: Path):
    baseline = _findings(sheet.parents[1])
    result = rename(sheet, "Nozzle1", "P4711_N1", children=True)
    root = _root(sheet)
    ids = {e.get("id") for e in root.iter("Object") if e.get("id")}
    assert "P4711_N1" in ids and "Nozzle1" not in ids
    assert not [i for i in ids if i.startswith("Nozzle1_")]
    targets = {t.lstrip("#") for r in root.iter("References") for t in r.get("objects", "").split()}
    assert targets <= ids
    assert "Nozzle1 -> P4711_N1" in "\n".join(result.changes)
    assert not _new(sheet, baseline)


def test_rename_refuses_a_collision_and_a_bad_id(sheet: Path, monkeypatch):
    content = sheet.read_bytes()
    with pytest.raises(EditError, match="already exist"):
        rename(sheet, "Nozzle1", "Nozzle2")
    with pytest.raises(ValueError):
        rename(sheet, "Nozzle1", "N-1")
    assert sheet.read_bytes() == content
    monkeypatch.chdir(sheet.parents[1])
    out = runner.invoke(app, ["rename", "Nozzle1", "Nozzle2"])
    assert out.exit_code == 2 and "already exist" in out.output


def test_rename_a_tag_updates_data_labels_and_with_ids_the_ids(sheet: Path):
    baseline = _findings(sheet.parents[1])
    result = rename(sheet, "P4711", "P4799", ids=False)
    root = _root(sheet)
    pump = _obj(root, "CentrifugalPump1")
    assert pump.findtext("Data[@property='TagName']/String") == "P4799"
    assert pump.findtext("Data[@property='TagNameSequenceNumber']/String") == "4799"
    assert "P4711" not in _label_texts(root, "CentrifugalPump1")
    assert any("label" in c for c in result.changes)
    new = [f for f in _new(sheet, baseline) if "equipment-not-listed" not in f[1]]
    assert not new, new


def test_rename_an_instrument_tag_follows_its_functions(sheet: Path):
    rename(sheet, "PI-4712.01", "FI-4712.01")
    root = _root(sheet)
    sensor = _obj(root, "ProcessSignalGeneratingFunction1")
    number = sensor.findtext("Data[@property='ProcessSignalGeneratingFunctionNumber']/String")
    assert number == "FT4712.01"
    assert "FI" in _label_texts(root, "ProcessInstrumentationFunction1")


# -- set (pre-release issue 14) --------------------------------------------------------------------


def test_set_fluid_code_updates_data_and_every_label_showing_it(sheet: Path, monkeypatch):
    baseline = _findings(sheet.parents[1])
    monkeypatch.chdir(sheet.parents[1])
    out = runner.invoke(app, ["set", "PipingNetworkSystem1", "FluidCode=Nitrogen"])
    assert out.exit_code == 0, out.output
    root = _root(sheet)
    system = _obj(root, "PipingNetworkSystem1")
    assert system.findtext("Data[@property='FluidCode']/String") == "Nitrogen"
    assert "Nitrogen 47121 75HB13 80" in _label_texts(root, "PipingNetworkSystem1")
    assert "label " in out.output
    new = _new(sheet, baseline)
    assert not [f for f in new if "label-stale" in f[1]], new
    assert not new, new


def test_set_types_values_as_dexpi_defines_them(sheet: Path):
    result = set_values(
        sheet,
        "PipingNetworkSegment1",
        [
            ("OnHold", "OnHold"),
            ("InsulationThickness", "50 mm"),
            ("SegmentNumber", "S9"),
        ],
    )
    root = _root(sheet)
    segment = _obj(root, "PipingNetworkSegment1")
    assert segment.find("Data[@property='OnHold']/DataReference").get("data") == (
        "Plant/Enumerations.OnHoldClassification.OnHold"
    )
    quantity = segment.find("Data[@property='InsulationThickness']/AggregatedDataValue")
    assert quantity.find("Data[@property='Unit']/DataReference").get("data") == (
        "Core/PhysicalQuantities.LengthUnit.Millimetre"
    )
    assert quantity.findtext("Data[@property='Value']/Double") == "50.0"
    assert len(result.changes) >= 3
    # A drawing value by a dotted path, typed as the Double it is.
    line = "PipingNetworkSegment1_Connections1_Drawing1_Groups1_Elements1"
    if _root(sheet).find(f".//Object[@id='{line}']") is not None:
        set_values(sheet, line, [("Stroke.Width", "0.7")])
        assert _obj(_root(sheet), line).findtext(".//Data[@property='Width']/Double") == "0.7"


def test_set_refuses_unknown_properties_and_bad_values(sheet: Path):
    content = sheet.read_bytes()
    with pytest.raises(EditError, match="no data attribute 'Fluidcod'"):
        set_values(sheet, "PipingNetworkSystem1", [("Fluidcod", "X")])
    with pytest.raises(EditError, match="not one of"):
        set_values(sheet, "PipingNetworkSegment1", [("OnHold", "Maybe")])
    with pytest.raises(EditError, match="not a quantity"):
        set_values(sheet, "PipingNetworkSegment1", [("InsulationThickness", "thick")])
    assert sheet.read_bytes() == content


def test_set_keeps_every_significant_digit_and_refuses_non_finite_values(sheet: Path):
    """Doubles are not rounded to six decimals; a signed exponent parses; nan/inf refused
    (pre-release issue 214)."""
    result = set_values(
        sheet,
        "Tank1",
        [
            ("NominalCapacityVolume", "4e-7 MetreCubed"),
            ("CylinderLength", "12.3456789 Metre"),
        ],
    )
    tank = _obj(_root(sheet), "Tank1")

    def value(prop: str) -> str:
        return tank.findtext(f"Data[@property='{prop}']/AggregatedDataValue/Data/Double")

    assert float(value("NominalCapacityVolume")) == 4e-7
    assert value("CylinderLength") == "12.3456789"
    assert any("12.3456789" in c for c in result.changes), result.changes
    for text, expected in (("1.5E+1 Metre", "15.0"), (".5 Metre", "0.5"), ("+2e0 Metre", "2.0")):
        set_values(sheet, "Tank1", [("CylinderLength", text)])
        assert (
            _obj(_root(sheet), "Tank1").findtext(
                "Data[@property='CylinderLength']/AggregatedDataValue/Data/Double"
            )
            == expected
        ), text
    content = sheet.read_bytes()
    for text in ("nan Metre", "inf Metre", "1e999 Metre", "nan", "-inf"):
        with pytest.raises(EditError):
            set_values(sheet, "Tank1", [("CylinderLength", text)])
    text = "Tank1_Drawing1_Groups3_Elements27"  # a label Text: its Rotation is a plain Double
    for bad in ("nan", "inf"):
        with pytest.raises(EditError, match="not a number"):
            set_values(sheet, text, [("Rotation", bad)])
    assert sheet.read_bytes() == content
    set_values(sheet, text, [("Rotation", "1e20")])
    assert _obj(_root(sheet), text).findtext("Data[@property='Rotation']/Double") == "1e+20"


def test_coordinates_still_format_to_six_decimals():
    from chemeascode.domains.piping.authoring._xml import data_number, number

    assert [number(v) for v in (160, -2.5, -0.0, 1e-9, 100.00000000001)] == [
        "160.0",
        "-2.5",
        "0.0",
        "0.0",
        "100.0",
    ]
    assert [data_number(v) for v in (4e-7, -0.0, 12.3456789)] == ["4e-07", "0.0", "12.3456789"]
    for bad in (float("nan"), float("inf")):
        with pytest.raises(ValueError, match="not a finite number"):
            number(bad)
        with pytest.raises(ValueError, match="not a finite number"):
            data_number(bad)


# -- documentation --------------------------------------------------------------------------------

SKILLS = Path(__file__).parents[1] / "src" / "chemeascode" / "domains" / "piping" / "skills"


def test_skills_document_the_edit_commands_and_copy_options():
    dexpi = (SKILLS / "dexpi-xml" / "SKILL.md").read_text()
    edit = (SKILLS / "pid-edit" / "SKILL.md").read_text()
    for text in (dexpi, edit):
        for command in ("cheme move", "cheme rename", "cheme set"):
            assert command in text, command
    recipe = dexpi.split("### Parallel / spare equipment", 1)[1].split("###", 1)[0]
    for option in ("--rename", "--renumber", "--set", "--connect", "--sense-at"):
        assert option in recipe, option


def test_move_an_instrument_keeps_its_sensing_node_and_reports_the_measuring_line(sheet: Path):
    baseline = _findings(sheet.parents[1])
    before = _root(sheet)
    sensing = _xy(_obj(before, "InstrumentationNodePosition1"))
    result = move_object(sheet, "PI-4712.01", (5, -5))
    after = _root(sheet)
    assert _xy(_obj(after, "InstrumentationNodePosition1")) == sensing  # on the flange: stays
    assert any("follows:" in c and "InstrumentationNodePosition1" in c for c in result.changes)
    assert not _new(sheet, baseline)


def test_move_a_single_label_text(sheet: Path):
    text_id = "PipingNetworkSystem1_Drawing1_Groups1_Elements1"
    x, y = _xy(_obj(_root(sheet), text_id))
    result = move_object(sheet, text_id, (0, -2))
    assert _xy(_obj(_root(sheet), text_id)) == (x, y - 2)
    assert len([c for c in result.changes if " Position: " in c]) == 1


# -- review fixes ---------------------------------------------------------------------------------


def test_a_duplicated_instrument_is_retagged_by_its_id(sheet: Path, monkeypatch):
    """The duplicate-tag hint leads to a command that also retags the sensor
    (pre-release issue 8)."""
    copy_object(sheet, "ProcessInstrumentationFunction1", "PIF_DUP", offset=(20, 0))
    found = [
        f
        for f in validate_workspace(Workspace.find(sheet.parents[1])).findings
        if f.rule == "cheme.duplicate-tag"
    ]
    assert found and "cheme rename" in found[0].hint and "--tag" in found[0].hint, found
    monkeypatch.chdir(sheet.parents[1])
    # By tag it is ambiguous; by id with --tag it is the tag that changes.
    assert runner.invoke(app, ["rename", "PI-4712.01", "FI-4799"]).exit_code == 2
    out = runner.invoke(app, ["rename", "PIF_DUP", "FI-4799", "--tag"])
    assert out.exit_code == 0, out.output
    root = _root(sheet)
    pif = _obj(root, "PIF_DUP")
    assert pif.findtext("Data[@property='ProcessInstrumentationFunctionNumber']/String") == "4799"
    sensor = _obj(root, "PIF_DUP_ProcessSignalGeneratingFunction1")
    assert sensor.findtext("Data[@property='ProcessSignalGeneratingFunctionNumber']/String") == (
        "FT4799"
    )
    assert not [
        f
        for f in validate_workspace(Workspace.find(sheet.parents[1])).findings
        if f.rule == "cheme.duplicate-tag"
    ]
    # --ids with --tag renames this object's ids only, never the original's.
    rename(sheet, "ProcessInstrumentationFunction1", "PIF_PI471201")
    copy_object(sheet, "PIF_PI471201", "PIF_PI471201B", offset=(40, 0))
    rename(sheet, "PIF_PI471201B", "PI-4712.09", tag=True, ids=True)
    ids = {e.get("id") for e in _root(sheet).iter("Object") if e.get("id")}
    assert "PIF_PI471209B" in ids and "PIF_PI471201" in ids, sorted(i for i in ids if "PIF" in i)


def test_set_of_an_instrument_number_or_category_follows_its_functions(sheet: Path):
    result = set_values(
        sheet,
        "ProcessInstrumentationFunction1",
        [
            ("ProcessInstrumentationFunctionNumber", "4798"),
            ("ProcessInstrumentationFunctionCategory", "F"),
        ],
    )
    sensor = _obj(_root(sheet), "ProcessSignalGeneratingFunction1")
    number = sensor.findtext("Data[@property='ProcessSignalGeneratingFunctionNumber']/String")
    assert number == "FT4798", result.changes


def test_rename_and_set_find_a_safety_valve_by_its_position_number(sheet: Path, monkeypatch):
    set_values(sheet, "SpringLoadedGlobeSafetyValve1", [("PositionNumber", "TSV-4144")])
    monkeypatch.chdir(sheet.parents[1])
    out = runner.invoke(app, ["rename", "TSV-4144", "TSV-4145"])
    assert out.exit_code == 0, out.output
    valve = _obj(_root(sheet), "SpringLoadedGlobeSafetyValve1")
    assert valve.findtext("Data[@property='PositionNumber']/String") == "TSV-4145"
    assert runner.invoke(app, ["move", "TSV-4145", "--offset", "2,0"]).exit_code == 0


def test_rename_refuses_a_tag_another_object_has(sheet: Path, monkeypatch):
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "HV-4146")])
    set_values(sheet, "SpringLoadedGlobeSafetyValve1", [("PositionNumber", "TSV-4144")])
    content = sheet.read_bytes()
    with pytest.raises(EditError, match="already the tag"):
        rename(sheet, "HV-4146", "TSV-4144")
    assert sheet.read_bytes() == content
    monkeypatch.chdir(sheet.parents[1])
    out = runner.invoke(app, ["rename", "HV-4146", "TSV-4144"])
    assert out.exit_code == 2 and "already the tag" in out.output


def test_set_refreshes_labels_without_ids_on_an_unformatted_sheet(plant: Path):
    """The fixture formats the sheet; a fresh copy of the reference has Texts without ids."""
    path = plant / "pid" / "P-01.xml"
    baseline = _findings(plant)
    result = set_values(path, "PipingNetworkSystem1", [("FluidCode", "Water")])
    assert not [c for c in result.changes if "has no id" in c], result.changes
    assert "Water 47121 75HB13 80" in _label_texts(_root(path), "PipingNetworkSystem1")
    assert not [f for f in _new(path, baseline) if "label-stale" in f[1]]


def test_validate_one_sheet_still_sees_tags_of_the_other_sheets(sheet: Path):
    import shutil

    root_dir = sheet.parents[1]
    set_values(sheet, "GlobeValve2", [("PipingComponentNumber", "HV-4146")])
    other = root_dir / "pid" / "P-02.xml"
    shutil.copy(sheet, other)
    for target, name in ((sheet, "pid/P-01.xml"), (other, "pid/P-02.xml")):
        found = [
            f
            for f in validate_workspace(Workspace.find(root_dir), only=[target]).findings
            if f.rule == "cheme.duplicate-tag"
        ]
        assert found and {f.file for f in found} == {name}, (name, found)


def test_copy_connect_refuses_a_node_another_pipe_ends_at(sheet: Path):
    content = sheet.read_bytes()
    with pytest.raises(CopyError, match="already"):
        copy_object(
            sheet,
            "PipingNetworkSystem1",
            "Line_47199",
            tag="47199",
            offset=(0, 30),
            connects=[("Pipe1", "Nozzle1:PipingNode2")],
        )
    assert sheet.read_bytes() == content
