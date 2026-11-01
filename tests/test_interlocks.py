"""control/cause-effect.yaml: interlocks cross-checked by validate, and the C&E matrix."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.control.interlocks import is_trip_tag
from chemeascode.domains.control.schemas import Interlock
from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()

INTERLOCK = """\
interlocks:
  - id: I-07
    cause: {tag: PICSA-4712.02, condition: PAHH}
    effects:
      - {tag: P4712, action: stop}
      - {tag: 66KL21, action: close}
    sheet: P-01
    notes: D-024
"""


def findings(rule_prefix: str) -> list[dict]:
    result = runner.invoke(app, ["validate", "--json"])
    return [f for f in json.loads(result.output)["findings"] if f["rule"].startswith(rule_prefix)]


def test_init_creates_the_list_and_schema(plant: Path):
    assert "interlocks: []" in (plant / "control" / "cause-effect.yaml").read_text()
    result = runner.invoke(app, ["schema", "interlocks"])
    assert result.exit_code == 0 and "depressurize" in result.output


def test_trip_tags():
    assert is_trip_tag("TSLL-4114") and is_trip_tag("LALL-4108") and is_trip_tag("PAHH-1")
    assert not is_trip_tag("LIA-4108") and not is_trip_tag("PICSA-4712.02")


def test_interlock_tags_must_exist(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control" / "cause-effect.yaml").write_text(INTERLOCK)
    assert findings("cheme.interlock") == []
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace("tag: 66KL21,", "tag: XV-9,")
    )
    unknown = findings("cheme.interlock-unknown-tag")
    assert len(unknown) == 1 and unknown[0]["ids"] == ["I-07", "XV-9"]
    assert unknown[0]["line"] == 6
    # The reference numbers valves C1, C2 within each segment: no tag to point an effect at.
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace("tag: 66KL21,", "tag: C1,")
    )
    assert [f["ids"] for f in findings("cheme.interlock-unknown-tag")] == [["I-07", "C1"]]
    # Renaming the drawn tag on the sheet makes the entry stale.
    (plant / "control" / "cause-effect.yaml").write_text(INTERLOCK)
    sheet = plant / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<String>P4712</String>", "<String>P4799</String>"))
    assert [f["ids"][1] for f in findings("cheme.interlock-unknown-tag")] == ["P4712"]


def test_duplicate_interlock(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    entry = INTERLOCK.split("\n", 1)[1]
    (plant / "control" / "cause-effect.yaml").write_text(INTERLOCK + entry)
    assert [f["rule"] for f in findings("cheme.interlock")] == ["cheme.interlock-duplicate"]


def test_trip_instrument_without_interlock_by_stage(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control" / "instrument-list.yaml").write_text(
        "instruments:\n"
        "  - {tag: TSLL-4114, service: LIN vaporizer outlet low temperature trip}\n"
        "  - {tag: LIA-4108, notes: LALL trips P-4102A/B}\n"
        "  - {tag: PICSA-4712.02}\n"
    )
    found = {f["ids"][0]: f for f in findings("cheme.instrument-no-interlock")}
    assert set(found) == {"TSLL-4114", "LIA-4108"}
    assert found["TSLL-4114"]["level"] == "info"  # concept stage
    plant_yaml = plant / "plant.yaml"
    plant_yaml.write_text(plant_yaml.read_text().replace("stage: concept", "stage: basic"))
    found = {f["ids"][0]: f for f in findings("cheme.instrument-no-interlock")}
    assert found["TSLL-4114"]["level"] == "warning"
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace("PICSA-4712.02", "TSLL-4114")
    )
    found = {f["ids"][0] for f in findings("cheme.instrument-no-interlock")}
    assert found == {"LIA-4108"}


def test_voting_instruments_of_the_logic_are_in_the_interlock(plant: Path, monkeypatch):
    # A 2oo3 trip: the cause is the row of the matrix, the other two voters sit in the logic.
    monkeypatch.chdir(plant)
    (plant / "control" / "instrument-list.yaml").write_text(
        "instruments:\n"
        "  - {tag: LSLL-105A}\n  - {tag: LSLL-105B}\n  - {tag: LSLL-105C}\n"
        "  - {tag: LSLL-106}\n"
    )
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace("PICSA-4712.02", "LSLL-105A") + "    logic:\n"
        "      vote: {k: 2, of: [{tag: LSLL-105A, state: LSLL}, {tag: LSLL-105B, state: LSLL},\n"
        "                     {tag: LSLL-105C, state: LSLL}]}\n"
    )
    found = findings("cheme.instrument-no-interlock")
    assert [f["ids"][0] for f in found] == ["LSLL-106"]  # in no interlock: still reported
    assert "in no interlock" in found[0]["message"] and "logic" in found[0]["message"]


def test_matrix_and_api(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control" / "cause-effect.yaml").write_text(INTERLOCK)
    result = runner.invoke(app, ["cause-effect"])
    assert result.exit_code == 0, result.output
    assert "build/cause-effect.html" in result.output
    csv_text = (plant / "build" / "cause-effect.csv").read_text()
    assert csv_text.splitlines() == [
        "id,cause,condition,sheet,sil,P4712,66KL21",
        "I-07,PICSA-4712.02,PAHH,P-01,,stop,close",
    ]
    assert '<td class="stop">stop</td>' in (plant / "build" / "cause-effect.html").read_text()
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "c&e")
    api = TestClient(create_app(plant, None, allowed_hosts=["testserver"]))
    data = api.get("/api/interlocks").json()
    assert data["columns"] == ["P4712", "66KL21"]
    assert data["rows"][0]["cells"] == ["stop", "close"]
    assert data["interlocks"][0]["cause"]["condition"] == "PAHH"


def test_two_effects_on_one_tag_keep_both_actions(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace(
            "{tag: 66KL21, action: close}",
            "{tag: 66KL21, action: close}\n      - {tag: 66KL21, action: alarm}",
        )
    )
    duplicate = findings("cheme.interlock-duplicate-effect")
    assert len(duplicate) == 1 and duplicate[0]["ids"] == ["I-07", "66KL21"]
    assert duplicate[0]["level"] == "warning" and duplicate[0]["line"] == 7
    assert "(close, alarm)" in duplicate[0]["message"]
    assert "shows close + alarm in its cell" in duplicate[0]["message"]
    result = runner.invoke(app, ["cause-effect"])
    assert result.exit_code == 0, result.output
    assert (plant / "build" / "cause-effect.csv").read_text().splitlines() == [
        "id,cause,condition,sheet,sil,P4712,66KL21",
        "I-07,PICSA-4712.02,PAHH,P-01,,stop,close + alarm",
    ]
    html = (plant / "build" / "cause-effect.html").read_text()
    assert '<td class="close alarm">close + alarm</td>' in html


def test_an_action_repeated_on_one_tag_is_one_finding_and_shown_once(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    repeat = "{tag: 66KL21, action: close}\n      - {tag: 66KL21, action: close}"
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace(
            "{tag: 66KL21, action: close}", repeat + "\n      - {tag: 66KL21, action: close}"
        )
    )
    (duplicate,) = findings("cheme.interlock-duplicate-effect")
    assert (
        "66KL21 is listed 3 times with action close; the matrix shows it once"
        in (duplicate["message"])
    )
    assert runner.invoke(app, ["cause-effect"]).exit_code == 0
    csv_text = (plant / "build" / "cause-effect.csv").read_text()
    assert csv_text.splitlines()[1] == "I-07,PICSA-4712.02,PAHH,P-01,,stop,close"


def test_sil_0_is_written_apart_from_no_sil(plant: Path, monkeypatch):
    # 0: screened, no SIL requirement; none: not screened yet. The matrix keeps them apart.
    monkeypatch.chdir(plant)
    entry = INTERLOCK.split("\n", 1)[1]
    (plant / "control" / "cause-effect.yaml").write_text(
        INTERLOCK.replace("    notes: D-024\n", "    sil: 0\n    notes: D-024\n")
        + entry.replace("I-07", "I-08")
    )
    assert runner.invoke(app, ["cause-effect"]).exit_code == 0
    assert (plant / "build" / "cause-effect.csv").read_text().splitlines()[1:] == [
        "I-07,PICSA-4712.02,PAHH,P-01,0,stop,close",
        "I-08,PICSA-4712.02,PAHH,P-01,,stop,close",
    ]
    html = (plant / "build" / "cause-effect.html").read_text()
    assert "<td>P-01</td><td>0</td>" in html and "<td>P-01</td><td></td>" in html


@pytest.mark.parametrize(
    ("given", "read"),
    [
        (2, 2),
        ("SIL 2", 2),
        ("SIL-2", 2),
        ("sil3", 3),
        ("2", 2),
        ("a", "a"),
        ("A", "a"),
        (0, 0),
        ("SIL 0", 0),
        (None, None),
        ("", None),
    ],
)
def test_sil_values_of_iec_61511_are_read(given, read):
    data = {"id": "I-1", "cause": {"tag": "LT-1"}, "effects": [{"tag": "P-1", "action": "stop"}]}
    assert Interlock.model_validate({**data, "sil": given}).sil == read


@pytest.mark.parametrize("given", [7, "banana", "SIL 5", 22, -1, True, "b", "２", "SIL 1-2"])
def test_other_sil_values_are_refused(given):
    data = {"id": "I-1", "cause": {"tag": "LT-1"}, "effects": [{"tag": "P-1", "action": "stop"}]}
    with pytest.raises(ValidationError, match="SIL|Input should be"):
        Interlock.model_validate({**data, "sil": given})
