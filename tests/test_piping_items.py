"""piping/special-items.yaml: tagged piping components against the P&IDs and the layout."""

import json
from pathlib import Path

from typer.testing import CliRunner

from chemeascode.interfaces.cli import app

runner = CliRunner()
LIST = "piping/special-items.yaml"


def findings(root: Path, prefix: str = "cheme.piping-item") -> list[dict]:
    result = runner.invoke(app, ["validate", "--json"])
    return [f for f in json.loads(result.output)["findings"] if f["rule"].startswith(prefix)]


def write_list(root: Path, *rows: str) -> None:
    (root / LIST).write_text("piping_items:\n" + "".join(f"  - {row}\n" for row in rows))


SV = (
    "{tag: SV 104.01, type: SpringLoadedGlobeSafetyValve, line: 47125, sheet: P-01,"
    " set_pressure_barg: 6}"
)


def test_without_the_list_nothing_changes(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    assert findings(plant) == []
    result = runner.invoke(app, ["validate"])
    assert "piping_items" not in result.output


def test_listed_safety_valve_validates(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write_list(plant, SV)
    assert findings(plant) == []
    assert "piping_items list vs P&IDs" in runner.invoke(app, ["validate"]).output


def test_unlisted_safety_valve_and_missing_item(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    # With its sheet: without one, a missing item is held back as info at the first stage.
    write_list(plant, "{tag: S-4101, type: Silencer, line: 47125, sheet: P-01}")
    found = {f["rule"]: f for f in findings(plant)}
    assert found["cheme.piping-item-not-on-pid"]["ids"] == ["S-4101"]
    assert found["cheme.piping-item-not-on-pid"]["line"] == 2
    listed = found["cheme.piping-item-not-listed"]
    assert listed["file"] == "pid/P-01.xml" and listed["ids"][0] == "SV 104.01"
    # Ordinary valves (C1, C2, ...) need not be listed.
    assert len([f for f in findings(plant) if f["rule"].endswith("not-listed")]) == 1


def test_type_and_line_mismatch(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write_list(plant, "{tag: SV 104.01, type: Silencer, line: 47124}")
    rules = {f["rule"] for f in findings(plant)}
    assert rules == {"cheme.piping-item-type-mismatch", "cheme.piping-item-line-mismatch"}
    write_list(plant, "{tag: SV 104.01, type: SafetyValveOrFitting, line: 47125}")
    assert findings(plant) == []  # a DEXPI superclass is fine


def test_removed_from_the_sheet(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write_list(plant, SV)
    sheet = plant / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<String>SV 104.01</String>", "<String> </String>"))
    rules = [f["rule"] for f in findings(plant)]
    assert rules == ["cheme.piping-item-not-on-pid"]


def test_duplicate(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write_list(plant, SV, SV)
    assert [f["rule"] for f in findings(plant)] == ["cheme.piping-item-duplicate"]


def test_piping_items_can_be_placed(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "layout" / "site-plan.yaml").write_text("site: {width: 50, depth: 50}\n")
    (plant / "layout" / "equipment-placement.yaml").write_text(
        "equipment:\n  - {tag: SV 104.01, position: [5, 5, 0], shape: box, size: [1, 1, 1]}\n"
    )
    unknown = findings(plant, "cheme.layout-unknown-tag")
    assert unknown and "piping/special-items.yaml" not in unknown[0]["message"]
    write_list(plant, SV)
    assert findings(plant, "cheme.layout-unknown-tag") == []
    assert runner.invoke(app, ["schema", "piping_items"]).exit_code == 0


# -- the printed tag of a piping component (pre-release issue 210) ---------------------------------


def test_component_tag_skips_segment_local_numbers():
    from chemeascode.domains.piping.sheet_query import component_tag

    assert component_tag("FV-104", None, None) == "FV-104"
    assert component_tag("FV-104", None, "66KL21") == "FV-104"
    assert component_tag("C1", None, "66KL21") == "66KL21"
    assert component_tag("C5", None, "73KH12") == "73KH12"
    assert component_tag(None, "SV 104.01", None) == "SV 104.01"
    assert component_tag("C1", "TSV-4144", None) == "TSV-4144"
    assert component_tag("V1", None, "Gate valve") == "V1"
    # A name never overrides a number, even one that looks like a tag (review of
    # pre-release PR 283).
    assert component_tag("V12", None, "Gate-valve") == "V12"
    assert component_tag("HV12", None, "Ball-valve") == "HV12"
    assert component_tag(None, "P7", "Ball-valve") == "P7"
    assert component_tag("C1", " ", None) is None  # only a segment-local number: untagged


def _drawn(path: Path):
    from chemeascode.domains.piping import dexpi_io
    from chemeascode.domains.piping.sheet_query import sheet_items

    model = dexpi_io.load(path.read_bytes(), strict=False).model
    return {item.id: item.tag for item in sheet_items(model, path.name) if item.kind == "piping"}


def test_sheet_items_give_the_reference_valves_their_printed_tag():
    """The reference numbers valves C1, C2 per segment and prints PipingComponentName."""
    import re

    from tests.conftest import REFERENCE

    tags = _drawn(REFERENCE)
    assert tags["ButterflyValve1"] == "66KL21"
    assert tags["SpringLoadedGlobeSafetyValve1"] == "SV 104.01"
    assert not [t for t in tags.values() if re.fullmatch(r"C\d+", t)], tags
    assert "GlobeValve2" not in tags  # only C1: not merged with the other C1s under one tag
    # The reference gives its five ball valves one name: they share the printed label 73KH12.
    assert sorted(i for i, t in tags.items() if t == "73KH12") == [
        f"BallValve{n}" for n in range(1, 6)
    ]


def test_sheet_items_keep_a_tag_in_piping_component_number():
    example = Path(__file__).parents[1] / "examples" / "safety-hazop" / "pid" / "P-01.xml"
    assert "FV-104" in _drawn(example).values()


def test_show_names_a_reference_valve_by_its_printed_tag():
    from chemeascode.domains.piping.show import Sheet
    from tests.conftest import REFERENCE

    sheet = Sheet.load(REFERENCE, "ref.xml")
    valve = sheet.by_id["ButterflyValve1"]
    assert sheet.label(valve) == "ButterflyValve1 (ButterflyValve 66KL21)"
    assert sheet.find("66KL21") == [valve]
    assert valve in sheet.find("C1")  # still found by its segment number
