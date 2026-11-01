"""Control foundations: the loop register, sequences, narrative and control
philosophy, validated against the lists, the C&E, the operating cases and each other, and reported.

The plant is ``examples/process-separation`` (a depropanizer): feed flow, flash drum level and
pressure, column feed temperature in cascade on the hot pentane flow, one low-low level trip,
a startup and a shutdown sequence.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.control.schemas import (
    Condition,
    Interlock,
    LoopLink,
    SequenceAction,
    Vote,
)
from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()
EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "process-separation"


@pytest.fixture
def sep(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "sep"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build"))
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "example")
    monkeypatch.chdir(root)
    return root


def findings(prefix: str = "cheme.control") -> list[dict]:
    result = runner.invoke(app, ["validate", "--json"])
    report = json.loads(result.output)
    return [f for f in report["findings"] if f["rule"].startswith(prefix)]


def rules(found: list[dict]) -> set[str]:
    return {f["rule"] for f in found}


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


LOOPS = Path("control/loops.yaml")
SEQUENCES = Path("control/sequences.yaml")


# -- the example ---------------------------------------------------------------------------------


def test_the_example_has_only_its_draft_findings(sep: Path):
    found = findings("cheme.")
    assert [
        f for f in found if f["level"] != "info" and f["rule"].startswith("cheme.control")
    ] == []
    control = [f for f in found if f["rule"].startswith("cheme.control")]
    # PIC-104 is the deliberate draft: no fail position, setpoint and fail position open.
    incomplete = [f for f in control if f["rule"] == "cheme.control-incomplete"]
    assert [f["ids"] for f in incomplete] == [["loop PIC-104"]]
    assert "fail position of PV-104" in incomplete[0]["message"]
    assert incomplete[0]["file"] == "control/loops.yaml" and incomplete[0]["line"]
    assert "cheme.control-unresolved" in rules(control)
    assert "cheme.control-logic-text" in rules(control)  # the operator's judgement in abort
    shared = [f for f in control if f["rule"] == "cheme.control-shared-element"]
    assert shared[0]["ids"] == ["FIC-105", "I-01", "FV-105"]


def test_schema_lists_the_control_kinds():
    listing = runner.invoke(app, ["schema"]).output
    for kind in ("loops", "sequences", "narrative", "control_philosophy"):
        assert kind in listing
    loops = json.loads(runner.invoke(app, ["schema", "loops"]).output)
    assert loops["properties"]["schema"]["description"].startswith("cheme/loops/v1")


def test_every_loop_names_measurement_and_element_or_says_what_is_open(sep: Path):
    data = yaml.safe_load((sep / LOOPS).read_text())
    for loop in data["loops"]:
        masters = {link["loop"] for other in data["loops"] for link in other.get("links", [])}
        assert loop["measurement"]
        assert loop.get("final_elements") or loop["id"] in masters


# -- references ----------------------------------------------------------------------------------


def test_a_renamed_tag_is_an_actionable_finding(sep: Path):
    edit(sep / "control/instrument-list.yaml", "{tag: FT-101,", "{tag: FT-111,")
    unknown = findings("cheme.control-unknown-tag")
    assert [f["ids"] for f in unknown] == [["loop FIC-101", "FT-101"]]
    assert unknown[0]["file"] == "control/loops.yaml"
    assert unknown[0]["line"] == 12
    assert "list / draw" in unknown[0]["hint"]


def test_a_removed_tag_in_a_sequence(sep: Path):
    edit(
        sep / "control/instrument-list.yaml",
        "  - {tag: XV-107, service: D-101 liquid outlet shut-off valve}\n",
        "",
    )
    unknown = findings("cheme.control-unknown-tag")
    assert {f["file"] for f in unknown} == {"control/sequences.yaml"}
    assert all("XV-107" in f["ids"] for f in unknown)


def test_dangling_references(sep: Path):
    edit(
        sep / LOOPS,
        "interlocks: [I-01]\n    rationale: Averaging",
        "interlocks: [I-99]\n    rationale: Averaging",
    )
    edit(
        sep / LOOPS, "cases: [design]\n    variable: flow", "cases: [turndown]\n    variable: flow"
    )
    edit(sep / LOOPS, "section: PREHEAT", "section: HEAT")
    edit(sep / SEQUENCES, "        next: end", "        next: S9")
    found = findings("cheme.control-ref")
    messages = " | ".join(f["message"] for f in found)
    assert "interlock I-99 is not in control/cause-effect.yaml" in messages
    assert "case turndown is not in process/flowsheet.yaml cases" in messages
    assert "section HEAT is not in process/narrative.md sections" in messages
    assert "next S9 is not a step of the sequence" in messages


def test_without_a_cause_effect_list_the_interlock_reference_says_so(sep: Path):
    (sep / "control/cause-effect.yaml").unlink()
    found = findings("cheme.control-ref")
    assert found and all("(the plant has no such file)" in f["message"] for f in found)


# -- values --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("value: 80, unit: °C", "value: 80, unit: degF", "use K or °C"),
        (
            "value: 3600, unit: kg/h, provenance: given, source: basis of design,\n         cases",
            "value: 3600, unit: m, provenance: given, source: basis of design,\n         cases",
            "is not a unit of flow",
        ),
        ('value: 50, unit: "%", provenance', "value: 50, provenance", "has no unit"),
        ("delay: {value: 30, unit: s}", "delay: {value: 30, unit: kg}", "not a unit of time"),
    ],
)
def test_units(sep: Path, old: str, new: str, message: str):
    for path in (LOOPS, SEQUENCES):
        if old in (sep / path).read_text():
            edit(sep / path, old, new)
    found = findings("cheme.control-unit")
    assert len(found) == 1 and message in found[0]["message"], found


def test_a_pressure_needs_absolute_or_gauge(sep: Path):
    edit(
        sep / LOOPS,
        "{kind: setpoint, unresolved: flash pressure follows from the flash design "
        "(cheme process simulate)}",
        "{kind: setpoint, value: 6, unit: bar, provenance: assumed}",
    )
    found = findings("cheme.control-unit")
    assert "with (a) or (g)" in found[0]["message"]


def test_a_target_follows_its_operating_case(sep: Path):
    assert findings("cheme.control-case") == []
    # The flowsheet changes: the linked setpoint no longer agrees.
    edit(sep / "process/flowsheet.yaml", "flow: {value: 3600,", "flow: {value: 4000,")
    found = findings("cheme.control-case")
    assert len(found) == 2  # the loop's setpoint and the startup's last step
    assert "differs from stream S1 flow in case design, 4000 kg/h" in found[0]["message"]


def test_a_setpoint_outside_its_limits(sep: Path):
    edit(sep / LOOPS, "{kind: setpoint, value: 50,", "{kind: setpoint, value: 90,")
    found = findings("cheme.control-conflict")
    assert len(found) == 1 and "outside its high limit 80 %" in found[0]["message"]


# -- structure -----------------------------------------------------------------------------------


def test_a_cascade_ring_is_an_error(sep: Path):
    edit(
        sep / LOOPS,
        "    modes: [manual, auto]\n    normal_mode: auto\n    rationale: Cascade",
        "    modes: [manual, auto, cascade]\n    normal_mode: auto\n    rationale: Cascade",
    )
    edit(
        sep / LOOPS,
        "    rationale: Cascade onto",
        "    links: [{type: cascade, loop: FIC-105}]\n    rationale: Cascade onto",
    )
    found = findings("cheme.control-cycle")
    assert len(found) == 1 and found[0]["level"] == "error"
    assert "TIC-103" in found[0]["message"] and "FIC-105" in found[0]["message"]


def test_an_override_pair_is_intentional_feedback(sep: Path):
    """Two loops on one valve conflict, unless an override links them (a ring of overrides is
    no setpoint cycle)."""
    edit(
        sep / LOOPS,
        "      - {tag: LV-102, kind: valve, actuator: pneumatic, fail: closed}",
        "      - {tag: FV-101, kind: valve, actuator: pneumatic, fail: closed}",
    )
    conflict = findings("cheme.control-conflict")
    assert [f["ids"] for f in conflict] == [["FIC-101", "LIC-102", "FV-101"]]
    edit(
        sep / LOOPS,
        "    rationale: The let-down",
        "    links: [{type: override, loop: LIC-102, select: low}]\n    rationale: The let-down",
    )
    edit(
        sep / LOOPS,
        "    interlocks: [I-01]\n    rationale: Averaging",
        "    interlocks: [I-01]\n    links: [{type: override, loop: FIC-101, select: low}]\n"
        "    rationale: Averaging",
    )
    found = findings()
    assert rules(found) & {"cheme.control-conflict", "cheme.control-cycle"} == set()


def test_a_cascade_slave_needs_the_cascade_mode(sep: Path):
    edit(
        sep / LOOPS,
        "    modes: [manual, auto, cascade]\n    normal_mode: cascade",
        "    modes: [manual, auto]\n    normal_mode: auto",
    )
    messages = [f["message"] for f in findings("cheme.control-conflict")]
    assert any("cascade is not one of its modes" in m for m in messages)
    assert any("puts loop FIC-105 in cascade" in m for m in messages)  # SEQ-START step S3


def test_sequence_transitions(sep: Path):
    seq = sep / SEQUENCES
    edit(
        seq,
        "        next: end\n",
        "        next: end\n      - id: S5\n        title: Orphan\n"
        "        actions: [{loop: TIC-103, action: manual}]\n",
    )
    edit(seq, "        complete: {loop: LIC-102, state: in auto}\n", "")
    found = findings()
    unreachable = [f for f in found if f["rule"] == "cheme.control-unreachable"]
    assert [f["ids"] for f in unreachable] == [["SEQ-START", "S5"]]
    incomplete = [f["message"] for f in found if f["rule"] == "cheme.control-incomplete"]
    assert "sequence SEQ-START step S2: no completion condition" in incomplete
    assert "sequence SEQ-START step S5: no completion condition" in incomplete


def test_duplicate_ids(sep: Path):
    edit(
        sep / SEQUENCES,
        "      - id: S2\n        title: Level",
        "      - id: S1\n        title: Level",
    )
    data = (sep / LOOPS).read_text()
    (sep / LOOPS).write_text(data.replace("  - id: PIC-104", "  - id: FIC-101"))
    found = [f for f in findings() if f["rule"] == "cheme.control-duplicate"]
    assert {f["file"] for f in found} == {"control/loops.yaml", "control/sequences.yaml"}
    assert all(f["level"] == "error" for f in found)


def test_a_draft_sequence_is_reported_not_refused(sep: Path):
    (sep / SEQUENCES).write_text(
        "sequences:\n  - id: SEQ-X\n    mode: startup\n"
        "    steps: [{id: S1, actions: [{text: open the bypass slowly}],"
        " complete: {unresolved: vendor to confirm}}]\n"
    )
    found = findings()
    messages = [f["message"] for f in found if f["rule"] == "cheme.control-incomplete"]
    assert "sequence SEQ-X: a startup sequence without start permissives" in messages
    assert "sequence SEQ-X: what happens on abort is not stated" in messages
    assert "cheme.control-unresolved" in rules(found)
    assert "cheme.control-logic-text" in rules(found)


# -- the formats ---------------------------------------------------------------------------------


def test_condition_forms():
    with pytest.raises(ValidationError, match="exactly one"):
        Condition.model_validate({"tag": "LT-1", "state": "LAH", "text": "and more"})
    with pytest.raises(ValidationError, match="one item"):
        Condition.model_validate({"tag": "LT-1", "loop": "LIC-1"})
    with pytest.raises(ValidationError, match="more than the 2"):
        Vote.model_validate({"k": 3, "of": [{"tag": "a"}, {"tag": "b"}]})
    voted = Condition.model_validate(
        {
            "vote": {"k": 2, "of": [{"tag": "PT-1"}, {"tag": "PT-2"}, {"tag": "PT-3"}]},
            "delay": {"value": 2, "unit": "s"},
        }
    )
    from chemeascode.domains.control.report import describe

    assert describe(voted) == "2oo3(PT-1, PT-2, PT-3) for 2 s"


def test_action_and_link_forms():
    with pytest.raises(ValidationError, match="not one of"):
        SequenceAction.model_validate({"tag": "P-1", "action": "auto"})
    with pytest.raises(ValidationError, match="takes a setpoint"):
        SequenceAction.model_validate({"loop": "FIC-1", "action": "setpoint"})
    with pytest.raises(ValidationError, match="give the loop"):
        LoopLink.model_validate({"type": "cascade", "tag": "FT-1"})


def test_an_existing_cause_effect_file_still_loads_and_renders(plant: Path, monkeypatch):
    """The interlock fields are optional: a file of 0.8 loads, and its matrix is unchanged."""
    monkeypatch.chdir(plant)
    (plant / "control" / "cause-effect.yaml").write_text(
        "interlocks:\n  - id: I-07\n    cause: {tag: PICSA-4712.02, condition: PAHH}\n"
        "    effects: [{tag: P4712, action: stop}]\n    sheet: P-01\n"
    )
    assert findings("cheme.interlock") == []
    assert runner.invoke(app, ["cause-effect"]).exit_code == 0
    csv_text = (plant / "build" / "cause-effect.csv").read_text()
    assert csv_text == "id,cause,condition,sheet,sil,P4712\nI-07,PICSA-4712.02,PAHH,P-01,,stop\n"
    interlock = Interlock.model_validate(
        {"id": "I-1", "cause": {"tag": "PT-1"}, "effects": [{"tag": "P-1", "action": "stop"}]}
    )
    assert interlock.latching is None and interlock.reset is None  # unknown, not defaulted


def test_interlock_logic_tags_are_checked(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "control" / "cause-effect.yaml").write_text(
        "interlocks:\n  - id: I-07\n    cause: {tag: PICSA-4712.02, condition: PAHH}\n"
        "    logic: {vote: {k: 2, of: [{tag: PICSA-4712.02, state: PAHH}, {tag: PT-9, state: PAHH},"
        " {tag: PT-10, state: PAHH}]}}\n"
        "    effects: [{tag: P4712, action: stop}]\n    latching: true\n    reset: manual\n"
    )
    unknown = findings("cheme.interlock-unknown-tag")
    assert sorted(f["ids"][1] for f in unknown) == ["PT-10", "PT-9"]
    assert all(f["line"] == 4 for f in unknown)


# -- documents -----------------------------------------------------------------------------------


def test_narrative_sections_need_their_headings(sep: Path):
    edit(sep / "process/narrative.md", "## PREHEAT Feed preheat", "## Feed preheat")
    found = findings("cheme.control-incomplete")
    assert [f["message"] for f in found if f["file"] == "process/narrative.md"] == [
        "section PREHEAT: has no heading in the text"
    ]


def test_invalid_front_matter(sep: Path):
    edit(sep / "process/narrative.md", "  - id: COLUMN\n", "  - id: COLUMN\n    colour: red\n")
    found = findings("cheme.control-document")
    assert len(found) == 1 and found[0]["level"] == "error"
    assert found[0]["line"] == 21 and "colour" in found[0]["message"]


def test_philosophy_topics(sep: Path):
    edit(sep / "control/philosophy.md", "## Control hierarchy", "## Hierarchy")
    found = [
        f for f in findings("cheme.control-incomplete") if f["file"] == "control/philosophy.md"
    ]
    assert [f["message"] for f in found] == [
        "the control philosophy has no section 'Control hierarchy'"
    ]


def test_a_declared_input_that_changed_is_stale(sep: Path):
    from chemeascode.foundation.provenance import file_fingerprint

    revision = file_fingerprint(sep / "process/flowsheet.yaml")
    edit(
        sep / LOOPS,
        "loops:\n",
        f"basis:\n  - {{path: process/flowsheet.yaml, revision: '{revision}'}}\nloops:\n",
    )
    assert findings("cheme.control-stale") == []
    edit(sep / "process/flowsheet.yaml", "title: Depropanizer", "title: Depropaniser")
    stale = findings("cheme.control-stale")
    assert len(stale) == 1 and stale[0]["file"] == "control/loops.yaml" and stale[0]["line"] == 6


# -- review status and the reports -----------------------------------------------------------------


def _review(root: Path, kind: str, scope: str) -> None:
    head = git(root, "rev-parse", "HEAD").strip()
    (root / "reviews").mkdir(exist_ok=True)
    (root / "reviews" / f"2026-10-24-control-{kind}.md").write_text(
        f"---\ntopic: control\nreviewed_commit: {head}\nscope: [{scope}]\n"
        f"reviewer: A. Reviewer\nreviewer_kind: {kind}\n---\n\n# Control review\n\n"
        "## Findings\n\n| id | severity | status | finding |\n|---|---|---|---|\n"
        f"| 2026-10-24-control-{kind}#1 | minor | open | wording |\n"
    )
    git(root, "add", "-A")
    git(root, "commit", "-qm", f"{kind} review")


def test_review_status_drafted_reviewed_accepted(sep: Path):
    from chemeascode.domains.control.report import control_report

    def status() -> dict[str, str]:
        return {f["path"]: f["status"] for f in control_report(sep).files}

    assert set(status().values()) == {"drafted"}
    _review(sep, "agent", "control/loops.yaml")
    assert status()["control/loops.yaml"] == "reviewed"
    assert status()["control/sequences.yaml"] == "drafted"
    _review(sep, "human", "control/")
    assert status()["control/loops.yaml"] == "accepted"
    assert status()["control/sequences.yaml"] == "accepted"
    assert status()["process/narrative.md"] == "drafted"
    edit(sep / LOOPS, "title: Feed flow\n", "title: Feed rate\n")
    report = control_report(sep)
    loops = next(f for f in report.files if f["path"] == "control/loops.yaml")
    assert loops["status"] == "drafted" and "changed since the review" in loops["detail"]


def test_report_files_and_json(sep: Path):
    result = runner.invoke(app, ["control", "report"])
    assert result.exit_code == 0, result.output
    assert "build/control-loops.html" in result.output
    assert "control/loops.yaml: drafted" in result.output
    page = (sep / "build" / "control-loops.html").read_text()
    assert "FIC-101" in page and "setpoint 3600 kg/h (given: basis of design) [design]" in page
    assert "PROPOSED" in page
    rows = (sep / "build" / "control-loops.csv").read_text().splitlines()
    assert rows[0].startswith("id,title,section,variable,measurement")
    assert rows[1].startswith(
        "FIC-101,Feed flow,FEED,flow,FT-101,FIC-101,reverse,FV-101 fail closed"
    )
    sequences = (sep / "build" / "control-sequences.html").read_text()
    assert "Start permissives" in sequences and "LT-102 &gt; 30 % for 30 s" in sequences
    data = json.loads(runner.invoke(app, ["control", "report", "--json"]).output)
    assert data["present"] and [loop["id"] for loop in data["loops"]][:2] == ["FIC-101", "LIC-102"]
    assert data["loops"][4]["findings"] == {"error": 0, "warning": 0, "info": 3}
    assert data["source"]["commit"] == git(sep, "rev-parse", "HEAD").strip()
    assert "control/loops.yaml" in data["source"]["fingerprints"]


def test_report_matches_validate(sep: Path):
    from chemeascode.domains.control.report import control_report

    reported = {f.id for f in control_report(sep).findings}
    validated = {
        f"{f['file']}#{f['rule'].removeprefix('cheme.')}:{f['key'] or '+'.join(f['ids'])}"
        for f in findings()
    }
    assert reported == validated


def test_a_plant_without_control_records(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["control", "report"])
    assert result.exit_code == 2 and "no control records yet" in result.output


def test_the_function_runs_from_elsewhere_without_typer(sep: Path, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    code = (
        "import sys, json; from pathlib import Path\n"
        "from chemeascode.domains.control.report import control_report\n"
        f"r = control_report(Path({str(sep)!r}))\n"
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules\n"
        "print(json.dumps([l['id'] for l in r.loops]))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert json.loads(out.stdout)[0] == "FIC-101"


def test_api_and_snapshot(sep: Path, plant: Path, tmp_path: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.export_static import export_static
    from chemeascode.interfaces.api.serve import create_app

    api = TestClient(create_app(sep, None, allowed_hosts=["testserver"]))
    data = api.get("/api/control").json()
    assert [s["id"] for s in data["sequences"]] == ["SEQ-START", "SEQ-STOP"]
    assert {d["kind"] for d in data["documents"]} == {"narrative", "philosophy"}
    empty = TestClient(create_app(plant, None, allowed_hosts=["testserver"]))
    assert empty.get("/api/control").status_code == 404  # no empty control page
    manifest = export_static(sep, tmp_path / "out")
    assert manifest["entries"]["control"]["status"] == 200


# -- regressions from review ---------------------------------------------------------------------


def test_an_invalid_register_or_list_does_not_flood_references(sep: Path):
    edit(sep / LOOPS, "action: reverse", "action: backwards")
    edit(sep / "control/instrument-list.yaml", "  - {tag: FT-101,", "  - {tagg: FT-101,")
    found = findings("")
    flood = [f for f in found if f["rule"] in ("cheme.control-ref", "cheme.control-unknown-tag")]
    assert flood == []
    assert {f["file"] for f in found if f["rule"] == "yaml.schema"} >= {
        "control/loops.yaml",
        "control/instrument-list.yaml",
    }


def test_each_draft_gap_has_its_own_id(sep: Path):
    (sep / LOOPS).write_text("loops:\n  - id: X-1\n    targets: [{value: 5}]\n")
    found = [f for f in findings() if f["file"] == "control/loops.yaml"]
    keys = [(f["rule"], f["key"]) for f in found]
    assert len(keys) == len(set(keys)) and len(keys) >= 6


def test_a_document_that_is_not_utf8_is_a_finding(sep: Path):
    (sep / "process/narrative.md").write_bytes("# Narrative\n\nDruckbehälter\n".encode("latin-1"))
    found = findings("cheme.control-document")
    assert len(found) == 1 and "UTF-8" in found[0]["message"]


def test_a_byte_order_mark_is_not_part_of_the_front_matter(sep: Path):
    path = sep / "process/narrative.md"
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert findings("cheme.control-ref") == []


def test_cases_are_compared_on_an_absolute_scale(sep: Path):
    """The tolerance (0.5 K) does not depend on the unit's zero point: 47 °C and 320.15 K
    against S1 at 45 °C give the same answer, and so do 45.3 °C and 318.45 K."""
    old = "value: 80, unit: °C, provenance: assumed, source: until cheme process simulate fills S5"
    results = []
    for value in ("47, unit: °C", "320.15, unit: K", "45.3, unit: °C", "318.45, unit: K"):
        text = (sep / LOOPS).read_text()
        new = f"value: {value}, provenance: assumed, stream: S1, property: temperature"
        (sep / LOOPS).write_text(text.replace(old, new))
        results.append(len(findings("cheme.control-case")))
        (sep / LOOPS).write_text(text)
    assert results == [1, 1, 0, 0]


def test_a_gauge_target_against_an_absolute_case_is_said_not_compared(sep: Path):
    edit(
        sep / LOOPS,
        "{kind: setpoint, unresolved: flash pressure follows from the flash design "
        "(cheme process simulate)}",
        "{kind: setpoint, value: 11, unit: bar(g), provenance: assumed, stream: S1, "
        "property: pressure}",
    )
    found = findings("cheme.control-case")
    assert (
        len(found) == 1
        and found[0]["level"] == "info"
        and "cannot be compared" in found[0]["message"]
    )


@pytest.mark.parametrize(
    "unit", ["m3/h", "m3/min", "L/h", "Nm3/h", "Nm3/d", "Sm3/h", "Sm3/min", "Sm³/h"]
)
def test_volumetric_flow_units(sep: Path, unit: str):
    edit(
        sep / LOOPS,
        "value: 5000, unit: kg/h, provenance: assumed, source: hot oil circulation,\n"
        "         cases: [design], stream: H1, property: flow}",
        f"value: 8, unit: {unit}, provenance: assumed, source: hot oil circulation}}",
    )
    assert findings("cheme.control-unit") == []


@pytest.mark.parametrize(
    ("unit", "variable", "problem"),
    [
        ("m3/d", "flow", None),
        ("Nm3/min", "flow", None),
        ("cm3/s", "flow", None),
        ("m3/h", "level", "'m3/h' is not a unit of level"),
        ("Nm3", "flow", "'Nm3' is not a unit of flow"),
    ],
)
def test_volume_units_written_with_a_digit(unit: str, variable: str, problem: str | None):
    pytest.importorskip("pint")
    from chemeascode.domains.control.register import unit_problem

    assert unit_problem(unit, variable) == problem


def test_a_normal_volume_flow_is_not_compared_on_an_assumed_normal_state(sep: Path):
    """The flowsheet's normal state (here 15 °C) defines Nm3; the register does not apply
    another one (DIN 1343 would make 3600 Nm3/h 160.6 kmol/h instead of 152.25)."""
    edit(
        sep / "process/flowsheet.yaml",
        "  enthalpy: kJ/kmol\n",
        "  enthalpy: kJ/kmol\n"
        "  normal_conditions: {temperature: 288.15, pressure: 101.325, basis: ideal_gas}\n",
    )
    edit(
        sep / "process/flowsheet.yaml",
        "flow: {value: 3600, provenance: given, source: basis of design}",
        "flow: {value: 3600, unit: Nm3/h, provenance: given, source: basis of design}",
    )
    edit(
        sep / LOOPS,
        "value: 3600, unit: kg/h, provenance: given",
        "value: 152.253, unit: kmol/h, provenance: given",
    )
    found = findings("cheme.control-case")
    assert {f["level"] for f in found} == {"info"}, found
    assert any("in kmol/h cannot be compared" in f["message"] for f in found), found


def test_interlock_delays_are_times(sep: Path):
    edit(
        sep / "control/cause-effect.yaml",
        "delay: {value: 5, unit: s}",
        "delay: {value: 5, unit: kg}",
    )
    found = findings("cheme.control-unit")
    assert len(found) == 1 and found[0]["file"] == "control/cause-effect.yaml"


def test_a_scope_written_with_dot_slash_covers_the_file(sep: Path):
    from chemeascode.domains.control.report import control_report

    _review(sep, "human", "./control/loops.yaml")
    status = {f["path"]: f["status"] for f in control_report(sep).files}
    assert status["control/loops.yaml"] == "accepted"


def test_two_gauge_pressures_are_compared(sep: Path):
    edit(
        sep / "process/flowsheet.yaml",
        "pressure: {value: 12, provenance: given, source: battery limit}",
        "pressure: {value: 12, unit: bar(g), provenance: given, source: battery limit}",
    )
    target = (
        "{kind: setpoint, unresolved: flash pressure follows from the flash design "
        "(cheme process simulate)}"
    )
    text = (sep / LOOPS).read_text()
    for value, expected in (("12", []), ("15", ["warning"])):
        new = (
            f"{{kind: setpoint, value: {value}, unit: bar(g), provenance: assumed, "
            "stream: S1, property: pressure}"
        )
        (sep / LOOPS).write_text(text.replace(target, new))
        assert [f["level"] for f in findings("cheme.control-case")] == expected


def test_duplicate_objectives_and_failures(sep: Path):
    edit(sep / "control/philosophy.md", "id: OBJ-2,", "id: OBJ-1,")
    edit(sep / "control/philosophy.md", "id: F-HOTOIL", "id: F-AIR")
    found = findings("cheme.control-duplicate")
    assert sorted(f["ids"][0] for f in found) == ["F-AIR", "OBJ-1"]


def test_interlock_delays_are_checked_without_other_control_records(sep: Path):
    for path in (LOOPS, SEQUENCES, Path("process/narrative.md"), Path("control/philosophy.md")):
        (sep / path).unlink()
    edit(
        sep / "control/cause-effect.yaml",
        "delay: {value: 5, unit: s}",
        "delay: {value: 5, unit: kg}",
    )
    found = findings("cheme.control-unit")
    assert len(found) == 1 and found[0]["line"] == 10


def test_a_longer_id_is_not_the_section_heading(sep: Path):
    edit(sep / "process/narrative.md", "## FEED Feed let-down", "## FEED-X Feed let-down")
    messages = [f["message"] for f in findings("cheme.control-incomplete")]
    assert "section FEED: has no heading in the text" in messages


def test_each_cascade_ring_has_its_own_id(sep: Path):
    (sep / LOOPS).write_text(
        "loops:\n"
        "  - {id: A-1, modes: [cascade],\n"
        "     links: [{type: cascade, loop: B-1}, {type: cascade, loop: C-1}]}\n"
        "  - {id: B-1, modes: [cascade], links: [{type: cascade, loop: A-1}]}\n"
        "  - {id: C-1, modes: [cascade], links: [{type: cascade, loop: A-1}]}\n"
    )
    found = findings("cheme.control-cycle")
    assert len(found) == 2 and len({f["key"] for f in found}) == 2


def test_a_list_that_is_not_utf8_is_a_finding(sep: Path):
    (sep / LOOPS).write_bytes("loops:\n  - {id: FIC-1, title: Druckbehälter}\n".encode("latin-1"))
    report = json.loads(runner.invoke(app, ["validate", "--json"]).output)
    assert any(
        f["file"] == "control/loops.yaml" and "UTF-8" in f["message"] for f in report["findings"]
    )


def test_a_bare_off_is_the_fail_position_off():
    """YAML reads `fail: off` as false; it means the heater fails off."""
    import yaml as _yaml

    from chemeascode.domains.control.schemas import FinalElement

    data = _yaml.safe_load("{tag: E-1, kind: heater, fail: off}")
    assert data["fail"] is False
    assert FinalElement.model_validate(data).fail == "off"
    with pytest.raises(ValidationError):
        FinalElement.model_validate({"tag": "E-1", "fail": True})
