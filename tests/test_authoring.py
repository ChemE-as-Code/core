"""cheme copy and cheme fragment: what they write validates where it is documented to go."""

import re
from collections import Counter
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.authoring.copy import CopyError, copy_object, new_id_for
from chemeascode.domains.piping.authoring.fragment import FragmentError, make_fragment
from chemeascode.domains.piping.drawing import RULES as DRAWING_RULES
from chemeascode.domains.piping.fmt import format_file
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace

runner = CliRunner()


@pytest.fixture
def sheet(plant: Path) -> Path:
    """The reference P&ID in a plant repository, formatted (every object has an id)."""
    path = plant / "pid" / "P-01.xml"
    format_file(path)
    return path


def _findings(root: Path) -> Counter:
    report = validate_workspace(Workspace.find(root))
    return Counter((f.level, f.rule, f.message) for f in report.findings)


def _ids(path: Path) -> list[str]:
    root = etree.parse(str(path)).getroot()
    return [e.get("id") for e in root.iter("Object") if e.get("id")]


def _new_findings(path: Path, baseline: Counter) -> list[tuple[str, str, str]]:
    """The errors and warnings validate adds after the change (infos are advice, not faults)."""
    format_file(path)
    ids = _ids(path)
    assert len(ids) == len(set(ids)), [i for i, n in Counter(ids).items() if n > 1]
    added = (_findings(path.parents[1]) - baseline).elements()
    # Drawing-geometry findings follow the drawing, not the model: a split pipe renames a
    # crossing the reference already has. They are tested in test_drawing.py.
    return sorted(f for f in added if f[0] != "info" and f[1] not in DRAWING_RULES)


# -- copy -------------------------------------------------------------------------------------


def test_new_ids_follow_the_scheme():
    assert new_id_for("CentrifugalPump1", "CentrifugalPump1", "Pump_P4711B") == "Pump_P4711B"
    assert (
        new_id_for("CentrifugalPump1_Drawing1", "CentrifugalPump1", "Pump_P4711B")
        == "Pump_P4711B_Drawing1"
    )
    assert new_id_for("Nozzle1", "CentrifugalPump1", "Pump_P4711B") == "Pump_P4711B_Nozzle1"


def test_copy_spare_pump_validates(sheet: Path):
    baseline = _findings(sheet.parents[1])
    before = _ids(sheet)
    result = copy_object(sheet, "P4711", "Pump_P4711B", tag="P4711B", offset=(0, 30))
    assert result.new_id == "Pump_P4711B"
    assert result.renamed["Nozzle1"] == "Pump_P4711B_Nozzle1"
    assert result.texts_updated == 2  # the tag label and the data table's Ident
    assert "TagNameSuffix 'B'" in ", ".join(result.tag_fields)
    # The pipes and segments at the original's nozzles stay, and are reported.
    assert any(n.startswith("Pipe1 (Pipe)") for n in result.not_copied)
    assert any(n.startswith("Pipe2 (Pipe)") for n in result.not_copied)
    assert "free slot" in result.table_note

    after = _ids(sheet)
    assert set(before) < set(after) and len(after) == len(set(after))
    root = etree.parse(str(sheet)).getroot()
    pump = root.find(".//Object[@id='Pump_P4711B']")
    assert pump.findtext("Data[@property='TagName']/String") == "P4711B"
    symbol = root.find(
        ".//Object[@id='Pump_P4711B_Drawing1']//Object[@type='Core/Diagram.ShapeUsage']"
    )
    assert symbol.findtext(".//Data[@property='Y']/Double") == "184.0"
    # Copied drawing references are internal, the shape is the catalogue's.
    assert symbol.find("References[@property='Shape']").get("objects") == "#Shape21"
    texts = [t.text for t in root.iterfind(".//Object[@id='Pump_P4711B_Drawing1']//String")]
    assert "P4711B" in texts and "P4711" not in texts

    new = _new_findings(sheet, baseline)
    assert [(level, rule) for level, rule, _ in new] == [
        ("warning", "cheme.equipment-not-listed")
    ], new
    assert "P4711B" in new[0][2]


def test_copy_print_changes_nothing(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    content = sheet.read_bytes()
    result = runner.invoke(
        app, ["copy", "P4711", "--prefix", "Pump_P4711B", "--tag", "P4711B", "--print"]
    )
    assert result.exit_code == 0, result.output
    assert sheet.read_bytes() == content
    assert '<Object id="Pump_P4711B" type="Plant/ProcessEquipment.CentrifugalPump">' in (
        result.output
    )
    assert "<!-- DRAWING: Pump_P4711B_Drawing1" in result.output


def test_copy_cli_reports_ids_ranges_and_left_behind(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    result = runner.invoke(
        app, ["copy", "P4711", "--prefix", "Pump_P4711B", "--tag", "P4711B", "--offset", "0,30"]
    )
    assert result.exit_code == 0, result.output
    out = result.output
    assert "CentrifugalPump1 -> Pump_P4711B" in out
    assert "pid/P-01.xml:" in out and "(drawing) at " in out
    assert "not copied" in out and "Pipe1 (Pipe)" in out
    # A second copy with the same prefix would clash.
    again = runner.invoke(app, ["copy", "P4711", "--prefix", "Pump_P4711B"])
    assert again.exit_code == 2 and "clash" in again.output


def test_copy_valve_into_another_segment(sheet: Path):
    baseline = _findings(sheet.parents[1])
    result = copy_object(
        sheet, "GlobeValve2", "GlobeValve_C1B", offset=(10, 0), into="PipingNetworkSegment3"
    )
    # The pipes at the valve are left behind; nothing inside the copy points at them.
    assert any(n.startswith("Pipe3 (Pipe)") for n in result.not_copied)
    root = etree.parse(str(sheet)).getroot()
    segment = root.find(".//Object[@id='PipingNetworkSegment3']")
    assert segment.find("Components[@property='Items']/Object[@id='GlobeValve_C1B']") is not None
    drawing = root.find(".//Object[@id='PipingNetworkSegment3_Drawing1']")
    assert drawing.find(".//Object[@id='GlobeValve_C1B_Drawing1']") is not None
    # An unconnected inline valve is allowed by validate; the copy itself adds no finding
    # other than what the label/segment rules say about an unconnected item.
    new = _new_findings(sheet, baseline)
    assert not [f for f in new if f[0] == "error"], new


def test_copy_refuses_unknown_and_bad_prefix(sheet: Path):
    with pytest.raises(CopyError):
        copy_object(sheet, "NoSuchThing", "X")
    with pytest.raises(ValueError):
        copy_object(sheet, "P4711", "P-4711B")


# -- fragments ----------------------------------------------------------------------------------


def _parse(xml: str) -> etree._Element:
    return etree.fromstring(xml)


def _object(root: etree._Element, object_id: str) -> etree._Element:
    found = root.find(f".//Object[@id='{object_id}']")
    assert found is not None, object_id
    return found


def _components(holder: etree._Element, prop: str) -> etree._Element:
    found = holder.find(f"Components[@property='{prop}']")
    if found is None:
        found = etree.Element("Components", property=prop)
        holder.insert(0, found)
    return found


def _drawing_of(root: etree._Element, object_id: str) -> etree._Element:
    for reference in root.iter("References"):
        if reference.get("property") == "Represents" and reference.get("objects") == (
            f"#{object_id}"
        ):
            return reference.getparent()
    raise AssertionError(f"no drawing of {object_id}")


def _paste(root: etree._Element, made, conceptual_into: tuple[str, str] | None, drawn_in: str):
    """Paste a fragment where its comments say: an object's Components, a drawing's Groups."""
    if conceptual_into is not None:
        holder, prop = conceptual_into
        _components(_object(root, holder), prop).append(_parse(made.part("CONCEPTUAL").xml))
    _components(_drawing_of(root, drawn_in), "Groups").append(_parse(made.part("DRAWING").xml))
    shape = made.part("SHAPE")
    if shape is not None:
        catalogue = root.find(".//Object[@type='Core/Diagram.ShapeCatalogue']")
        _components(catalogue, "Shapes").append(_parse(shape.xml))


def _set_ref(element: etree._Element, prop: str, target: str) -> None:
    element.find(f"References[@property='{prop}']").set("objects", f"#{target}")


def _write(root: etree._Element, path: Path) -> None:
    path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="UTF-8"))


def _remove_empty_items(root: etree._Element) -> None:
    for components in root.iter("Components"):
        if components.get("property") == "Items" and not len(components.findall("Object")):
            components.getparent().remove(components)


def test_spare_pump_recipe_with_every_fragment_kind_validates(sheet: Path):
    """The dexpi-xml recipe 'parallel / spare equipment', built from copy and fragments."""
    baseline = _findings(sheet.parents[1])
    copy_object(sheet, "P4711", "Pump_P4711B", tag="P4711B", offset=(0, 30))
    root = etree.parse(str(sheet)).getroot()

    def frag(kind: str, object_id: str, **options):
        _write(root, sheet)
        return make_fragment(kind, object_id, sheet=sheet, **options)

    # node: give the spare's suction nozzle a fresh node (and node position) from a fragment.
    nozzle = _object(root, "Pump_P4711B_Nozzle1")
    old_node = _object(root, "Pump_P4711B_PipingNode2")
    old_node.getparent().remove(old_node)
    old_drawing = _drawing_of(root, "Pump_P4711B_PipingNode2")
    old_drawing.getparent().remove(old_drawing)
    made = frag("node", "Node_P4711B_in", dn="80", at="74.75,184")
    nozzle_nodes = nozzle.find("Components[@property='Nodes']")
    nozzle_nodes.append(_parse(made.part("CONCEPTUAL").xml))
    _components(_drawing_of(root, "Pump_P4711B_Nozzle1"), "Groups").append(
        _parse(made.part("DRAWING").xml)
    )

    # Suction, line 47121: tee on Pipe1, branch down to a gate valve and the spare.
    made = frag("tee", "Tee_47121", dn="80", at="66,154", branch="down")
    _paste(root, made, ("PipingNetworkSegment1", "Items"), "PipingNetworkSegment1")
    pipe1 = _object(root, "Pipe1")
    segment1 = _object(root, "PipingNetworkSegment1")
    for holder in (pipe1, segment1):
        _set_ref(holder, "TargetItem", "Tee_47121")
        _set_ref(holder, "TargetNode", "Tee_47121_N1")
    _set_ref(
        _object(root, "Pipe1_Drawing1").find(".//Object[@type='Core/Diagram.ConnectorLine']"),
        "Target",
        "Tee_47121_N1_Position",
    )
    system1 = "PipingNetworkSystem1"
    for segment_id, start, end, number in (
        ("Seg_47121_S2", "Tee_47121:Tee_47121_N2", "Nozzle1:PipingNode2", "S2"),
        ("Seg_47121_S3", "Tee_47121:Tee_47121_N3", "Pump_P4711B_Nozzle1:Node_P4711B_in", "S3"),
    ):
        made = frag(
            "segment",
            segment_id,
            source=start,
            target=end,
            like="PipingNetworkSegment1",
            number=number,
        )
        _paste(root, made, (system1, "Segments"), system1)
    made = frag(
        "pipe", "Pipe_47121_S2", source="Tee_47121:Tee_47121_N2", target="Nozzle1:PipingNode2"
    )
    _paste(root, made, ("Seg_47121_S2", "Connections"), "Seg_47121_S2")
    made = frag("valve", "Valve_P4711B_in", valve_class="GateValve", dn="80", at="70,184")
    assert made.part("SHAPE") is not None  # no gate valve in the reference catalogue
    _paste(root, made, ("Seg_47121_S3", "Items"), "Seg_47121_S3")
    made = frag(
        "pipe",
        "Pipe_47121_S3a",
        source="Tee_47121:Tee_47121_N3",
        target="Valve_P4711B_in:Valve_P4711B_in_N1",
        points="66,184",
    )
    _paste(root, made, ("Seg_47121_S3", "Connections"), "Seg_47121_S3")
    made = frag(
        "pipe",
        "Pipe_47121_S3b",
        source="Valve_P4711B_in:Valve_P4711B_in_N2",
        target="Pump_P4711B_Nozzle1:Node_P4711B_in",
    )
    _paste(root, made, ("Seg_47121_S3", "Connections"), "Seg_47121_S3")

    # Discharge, line 47122: tee on Pipe2; the spare's branch with a check valve flows into it.
    made = frag("tee", "Tee_47122", dn="80", at="100,154", branch="down")
    _paste(root, made, ("PipingNetworkSegment2", "Items"), "PipingNetworkSegment2")
    for holder in (_object(root, "Pipe2"), _object(root, "PipingNetworkSegment2")):
        _set_ref(holder, "TargetItem", "Tee_47122")
        _set_ref(holder, "TargetNode", "Tee_47122_N1")
    _set_ref(
        _object(root, "Pipe2_Drawing1").find(".//Object[@type='Core/Diagram.ConnectorLine']"),
        "Target",
        "Tee_47122_N1_Position",
    )
    system2 = "PipingNetworkSystem2"
    for segment_id, start, end, number in (
        ("Seg_47122_S2", "Tee_47122:Tee_47122_N2", "Nozzle3:PipingNode4", "S2"),
        (
            "Seg_47122_S3",
            "Pump_P4711B_Nozzle2:Pump_P4711B_PipingNode3",
            "Tee_47122:Tee_47122_N3",
            "S3",
        ),
    ):
        made = frag(
            "segment",
            segment_id,
            source=start,
            target=end,
            like="PipingNetworkSegment2",
            number=number,
        )
        _paste(root, made, (system2, "Segments"), system2)
    made = frag(
        "pipe", "Pipe_47122_S2", source="Tee_47122:Tee_47122_N2", target="Nozzle3:PipingNode4"
    )
    _paste(root, made, ("Seg_47122_S2", "Connections"), "Seg_47122_S2")
    made = frag(
        "valve",
        "Valve_P4711B_check",
        valve_class="SwingCheckValve",
        dn="80",
        at="97,184",
        tag="C9",
    )
    assert made.part("SHAPE") is None
    _paste(root, made, ("Seg_47122_S3", "Items"), "Seg_47122_S3")
    made = frag(
        "pipe",
        "Pipe_47122_S3a",
        source="Pump_P4711B_Nozzle2:Pump_P4711B_PipingNode3",
        target="Valve_P4711B_check:Valve_P4711B_check_N1",
    )
    assert "Pump_P4711B_PipingNodePosition3" in made.part("DRAWING").xml  # from the sheet
    _paste(root, made, ("Seg_47122_S3", "Connections"), "Seg_47122_S3")
    made = frag(
        "pipe",
        "Pipe_47122_S3b",
        source="Valve_P4711B_check:Valve_P4711B_check_N2",
        target="Tee_47122:Tee_47122_N3",
        points="100,184",
    )
    _paste(root, made, ("Seg_47122_S3", "Connections"), "Seg_47122_S3")

    # label: the check valve's number, with the cached text read from the sheet.
    made = frag("label", "Label_C9", for_id="Valve_P4711B_check", attribute="PipingComponentNumber")
    assert "<String>C9</String>" in made.part("DRAWING").xml
    assert "Plant/Diagram.ValveLabel" in made.part("DRAWING").xml
    _paste(root, made, None, "Valve_P4711B_check")
    made = frag(
        "label",
        "Label_P4711B_flow",
        for_id="Pump_P4711B",
        attribute="DesignVolumeFlowRate",
        at="84,196",
    )
    assert "200 m³/h" in made.part("DRAWING").xml
    _paste(root, made, None, "Pump_P4711B")

    _remove_empty_items(root)
    _write(root, sheet)
    new = _new_findings(sheet, baseline)
    assert [(level, rule) for level, rule, _ in new] == [
        ("warning", "cheme.equipment-not-listed")
    ], new


def test_bypass_recipe_validates(sheet: Path):
    """The dexpi-xml recipe 'bypass around a valve': two tees, four segments."""
    baseline = _findings(sheet.parents[1])
    root = etree.parse(str(sheet)).getroot()

    def frag(kind: str, object_id: str, **options):
        _write(root, sheet)
        return make_fragment(kind, object_id, sheet=sheet, **options)

    # Line 47123 runs Nozzle4 -> Pipe3 -> C1 (GlobeValve2) -> Pipe4 -> Nozzle5, upwards at x 160.
    system = "PipingNetworkSystem3"
    made = frag("tee", "Tee_C1_in", dn="80", at="160,127", rotation=270, branch="right")
    _paste(root, made, ("PipingNetworkSegment3", "Items"), "PipingNetworkSegment3")
    made = frag("tee", "Tee_C1_out", dn="80", at="160,111", rotation=270, branch="right")
    # The segment running from the inlet tee through C1 ends at the outlet tee and owns it.
    segment1 = _object(root, "PipingNetworkSegment3")
    pipe3, pipe4 = _object(root, "Pipe3"), _object(root, "Pipe4")
    for holder in (pipe3, segment1):
        _set_ref(holder, "TargetItem", "Tee_C1_in")
        _set_ref(holder, "TargetNode", "Tee_C1_in_N1")
    _set_ref(
        _object(root, "Pipe3_Drawing1").find(".//Object[@type='Core/Diagram.ConnectorLine']"),
        "Target",
        "Tee_C1_in_N1_Position",
    )
    # S2: inlet tee run-out -> C1 -> outlet tee (owns it); C1 and Pipe4 move into it.
    made_s2 = frag(
        "segment",
        "Seg_47123_S2",
        source="Tee_C1_in:Tee_C1_in_N2",
        target="Tee_C1_out:Tee_C1_out_N1",
        like="PipingNetworkSegment3",
        number="S2",
    )
    _paste(root, made_s2, (system, "Segments"), system)
    s2 = _object(root, "Seg_47123_S2")
    valve = _object(root, "GlobeValve2")
    _components(s2, "Items").append(valve)
    _paste(root, made, ("Seg_47123_S2", "Items"), "Seg_47123_S2")
    pipe_in = frag(
        "pipe", "Pipe_C1_in", source="Tee_C1_in:Tee_C1_in_N2", target="GlobeValve2:PipingNode6"
    )
    _components(s2, "Connections").append(_parse(pipe_in.part("CONCEPTUAL").xml))
    _set_ref(pipe4, "TargetItem", "Tee_C1_out")
    _set_ref(pipe4, "TargetNode", "Tee_C1_out_N1")
    _components(s2, "Connections").append(pipe4)
    s2_drawing = _components(_drawing_of(root, "Seg_47123_S2"), "Groups")
    s2_drawing.append(_parse(pipe_in.part("DRAWING").xml))
    s2_drawing.append(_object(root, "GlobeValve2_Drawing1"))
    pipe4_drawing = _object(root, "Pipe4_Drawing1")
    line4 = pipe4_drawing.find(".//Object[@type='Core/Diagram.ConnectorLine']")
    _set_ref(line4, "Target", "Tee_C1_out_N1_Position")
    line4.remove(line4.find("Data[@property='InnerPoints']"))
    s2_drawing.append(pipe4_drawing)
    # S3: outlet tee run-out -> Nozzle5 (with the old bends).
    made = frag(
        "segment",
        "Seg_47123_S3",
        source="Tee_C1_out:Tee_C1_out_N2",
        target="Nozzle5:PipingNode8",
        like="PipingNetworkSegment3",
        number="S3",
    )
    _paste(root, made, (system, "Segments"), system)
    made = frag(
        "pipe",
        "Pipe_47123_S3",
        source="Tee_C1_out:Tee_C1_out_N2",
        target="Nozzle5:PipingNode8",
        points="160,61;181,61",
    )
    _paste(root, made, ("Seg_47123_S3", "Connections"), "Seg_47123_S3")
    # S4, the bypass: inlet tee branch -> globe valve C3 -> outlet tee branch.
    made = frag(
        "segment",
        "Seg_47123_S4",
        source="Tee_C1_in:Tee_C1_in_N3",
        target="Tee_C1_out:Tee_C1_out_N3",
        like="PipingNetworkSegment3",
        number="S4",
    )
    _paste(root, made, (system, "Segments"), system)
    made = frag(
        "valve", "Valve_C3", valve_class="GlobeValve", dn="80", at="170,119", rotation=270, tag="C3"
    )
    _paste(root, made, ("Seg_47123_S4", "Items"), "Seg_47123_S4")
    for pipe_id, start, end, bend in (
        ("Pipe_bypass_in", "Tee_C1_in:Tee_C1_in_N3", "Valve_C3:Valve_C3_N1", "170,127"),
        ("Pipe_bypass_out", "Valve_C3:Valve_C3_N2", "Tee_C1_out:Tee_C1_out_N3", "170,111"),
    ):
        made = frag("pipe", pipe_id, source=start, target=end, points=bend)
        _paste(root, made, ("Seg_47123_S4", "Connections"), "Seg_47123_S4")
    # The old segment now only holds Pipe3 and the inlet tee.
    _set_ref(segment1, "TargetItem", "Tee_C1_in")
    _set_ref(segment1, "TargetNode", "Tee_C1_in_N1")

    _remove_empty_items(root)
    _write(root, sheet)
    new = _new_findings(sheet, baseline)
    assert not new, new


def test_fragment_cli_prints_delimited_parts_and_changes_nothing(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    content = sheet.read_bytes()
    result = runner.invoke(
        app,
        [
            "fragment",
            "valve",
            "--id",
            "V1",
            "--class",
            "BallValve",
            "--dn",
            "50",
            "--at",
            "10,20",
            "--rotation",
            "90",
            "--sheet",
            "pid/P-01.xml",
        ],
    )
    assert result.exit_code == 0, result.output
    assert sheet.read_bytes() == content
    out = result.stdout
    assert out.index("<!-- CONCEPTUAL:") < out.index("<!-- DRAWING:") < out.index("<!-- END -->")
    assert "#Shape8" in out  # BALL_VALVE_SHAPE, looked up by name in the sheet's catalogue
    # rotation 90: flow downwards, inlet above the symbol, outlet below.
    assert "<Double>18.0</Double>" in out and "<Double>22.0</Double>" in out


def test_fragment_rejects_bad_input(sheet: Path):
    with pytest.raises(FragmentError):
        make_fragment("elbow", "X")
    with pytest.raises(FragmentError):
        make_fragment("valve", "V", valve_class="NeedleValve", dn="50", at="1,1")
    with pytest.raises(FragmentError):
        make_fragment("pipe", "P", source="A", target="B:C")
    with pytest.raises(ValueError):
        make_fragment("node", "bad-id", dn="50")
    with pytest.raises(FragmentError):  # the id exists in the sheet
        make_fragment("node", "Nozzle1", dn="50", sheet=sheet)


@pytest.mark.parametrize(
    "options",
    [
        {"scale": "nan"},
        {"scale": "inf"},
        {"scale": "1,nan"},
        {"rotation": float("nan")},
        {"rotation": float("inf")},
        {"dn": "nan"},
    ],
)
def test_fragment_refuses_non_finite_numbers(options: dict):
    """--scale, --rotation and --dn refuse nan and inf instead of writing them."""
    with pytest.raises(FragmentError):
        make_fragment("valve", "VX1", **{"dn": "50", "at": "10,10", **options})
    if "dn" not in options:  # equipment takes no DN
        with pytest.raises(FragmentError):
            make_fragment("equipment", "TX1", item_class="Tank", tag="T-9", at="10,10", **options)


def test_fragment_cli_refuses_a_nan_rotation():
    out = runner.invoke(
        app,
        ["fragment", "valve", "--id", "VX1", "--dn", "50", "--at", "10,10", "--rotation", "nan"],
    )
    assert out.exit_code != 0 and "--rotation" in out.output, out.output


def test_copy_on_an_unformatted_sheet_leaves_ids_to_fmt(plant: Path):
    path = plant / "pid" / "P-01.xml"  # the reference as published: drawings have no ids
    result = copy_object(path, "P4711", "Pump_P4711B", tag="P4711B", offset=(0, 30))
    assert result.drawing_ids == [None]
    assert "Pump_P4711B" in _ids(path)
    format_file(path)
    ids = _ids(path)
    assert len(ids) == len(set(ids))
    assert "Pump_P4711B_Drawing1" in ids


def test_copy_instrument_with_tag_sets_category_letters_and_number(sheet: Path):
    baseline = _findings(sheet.parents[1])
    result = copy_object(
        sheet, "ProcessInstrumentationFunction2", "PIF2B", tag="PICSA-4713.02", offset=(30, 0)
    )
    assert result.new_tag == "PICSA-4713.02"
    assert result.texts_updated == 1  # the bubble's number; the letters stay PICSA
    root = etree.parse(str(sheet)).getroot()
    copy_ = root.find(".//Object[@id='PIF2B']")

    def value(element, prop):
        return element.findtext(f"Data[@property='{prop}']/String")

    assert value(copy_, "ProcessInstrumentationFunctionCategory") == "P"
    assert value(copy_, "ProcessInstrumentationFunctions") == "ICSA"
    assert value(copy_, "ProcessInstrumentationFunctionNumber") == "4713.02"
    sensor = copy_.find(".//Object[@id='PIF2B_ProcessSignalGeneratingFunction2']")
    actuator = copy_.find(".//Object[@id='PIF2B_ActuatingFunction1']")
    assert value(sensor, "ProcessSignalGeneratingFunctionNumber") == "PT4713.02"
    assert value(actuator, "ActuatingFunctionNumber") == "PV4713.02"
    texts = {
        t.text
        for t in root.iterfind(".//Object[@type='Core/Diagram.Text']/Data[@property='Text']/String")
        if t.getparent().getparent().find(".//References[@objects='#PIF2B']") is not None
    }
    assert texts == {"PICSA", "4713.02"}

    new = _new_findings(sheet, baseline)
    assert not [f for f in new if f[0] == "error"], new
    assert not [f for f in new if "label-stale" in f[1] or "PICSA-PICSA" in f[2]], new


def test_copy_instrument_refuses_a_tag_it_cannot_split(sheet: Path):
    with pytest.raises(CopyError, match="LETTERS-NUMBER"):
        copy_object(sheet, "ProcessInstrumentationFunction2", "PIF2B", tag="PICSA")


def test_copy_into_refuses_a_parent_that_cannot_hold_it(sheet: Path):
    content = sheet.read_bytes()
    with pytest.raises(CopyError, match="no TaggedPlantItems"):
        copy_object(sheet, "CentrifugalPump1", "PumpX", into="PipingNetworkSystem1")
    assert sheet.read_bytes() == content


# -- fragment safety --------------------------------------------------------------------------


@pytest.mark.parametrize("rotation", [90, 270])
def test_tee_default_branch_is_perpendicular_to_a_rotated_run(rotation: int):
    made = make_fragment("tee", "T9", dn="80", at="100,100", rotation=rotation)
    root = _parse(made.part("DRAWING").xml)
    xy = {}
    for position in root.iter("Object"):
        if position.get("type") == "Plant/Diagram.PipingNodePosition":
            point = position.find(".//AggregatedDataValue[@type='Core/Diagram.Point']")
            xy[position.get("id")] = tuple(
                round(float(point.findtext(f"Data[@property='{c}']/Double")), 6) for c in "XY"
            )
    assert len(set(xy.values())) == 3, xy
    assert xy["T9_N3_Position"][1] == 100  # sideways from a vertical run


def test_tee_refuses_a_branch_along_the_run():
    with pytest.raises(FragmentError, match="along the run"):
        make_fragment("tee", "T9", dn="80", at="100,100", rotation=90, branch="up")


def test_pipe_without_sheet_says_what_it_assumes():
    made = make_fragment("pipe", "P9", source="Nozzle1:PipingNode2", target="V:V_N1")
    assert any("--sheet" in note and "PipingNode2_Position" in note for note in made.notes)


def test_fragment_cli_finds_the_sheet_of_existing_nodes(sheet: Path, monkeypatch):
    monkeypatch.chdir(sheet.parents[1])
    result = runner.invoke(
        app,
        [
            "fragment",
            "pipe",
            "--id",
            "P9",
            "--from",
            "Nozzle1:PipingNode2",
            "--to",
            "CentrifugalPump1:PipingNode3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "using --sheet pid/P-01.xml" in result.stderr
    root = etree.parse(str(sheet)).getroot()
    positions = {
        p.get("id")
        for p in root.iter("Object")
        if p.get("type") == "Plant/Diagram.PipingNodePosition"
    }
    targets = {
        r.get("objects").lstrip("#")
        for r in _parse(
            result.stdout.split("<!-- DRAWING:")[1].split("-->", 1)[1].split("<!--")[0]
        ).iter("References")
        if r.get("property") in ("Source", "Target")
    }
    assert targets and targets <= positions, targets
    # --like works without --sheet too: the segment it names is found the same way.
    segment = runner.invoke(
        app,
        [
            "fragment",
            "segment",
            "--id",
            "S9",
            "--from",
            "Nozzle1:PipingNode2",
            "--to",
            "CentrifugalPump1:PipingNode3",
            "--like",
            "PipingNetworkSegment1",
            "--number",
            "S2",
        ],
    )
    assert segment.exit_code == 0, segment.output


# -- documentation agents copy from ------------------------------------------------------------

SKILLS = Path(__file__).parents[1] / "src" / "chemeascode" / "domains" / "piping" / "skills"


def test_skill_fragment_commands_name_the_sheet():
    """Agents copy recipe commands verbatim; without --sheet pipe ends and --like go wrong."""
    skill = (SKILLS / "dexpi-xml" / "SKILL.md").read_text()
    commands = re.findall(r"`((?:cheme )?fragment \w+ --id [^`]+)`", skill)
    assert len(commands) >= 8, commands
    assert [c for c in commands if "--sheet" not in c] == []


def test_plant_agents_md_lists_copy_and_fragment(tmp_path: Path):
    from chemeascode.templates.install import init

    init(tmp_path / "p", "P")
    agents = (tmp_path / "p" / "AGENTS.md").read_text()
    assert "| `cheme copy " in agents and "| `cheme fragment " in agents
