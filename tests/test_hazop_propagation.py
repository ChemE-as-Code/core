"""Scenario propagation (domains/safety/propagation.py, cheme safety hazop propagate).

The library here is synthetic: generic mode ids and no failure data, only enough responses to
exercise the walk. A real library is project data (safety/failure-modes.yaml).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.piping import dexpi_io
from chemeascode.domains.piping.authoring import (
    Nozzle,
    Sheet,
    equipment,
    instrument,
    line,
    offpage,
    valve,
)
from chemeascode.domains.safety import propagation as prop
from chemeascode.domains.safety.propagation import Context, Deviation, propagate
from chemeascode.domains.safety.schemas import FailureModeLibrary, PlantRef
from chemeascode.interfaces.cli import app
from chemeascode.templates.install import bundled_skills, init

EMPTY = Path(str(bundled_skills()["dexpi-xml"])) / "snippets" / "empty-sheet.xml"
NO_FLOW = Deviation("flow", "no")

LIBRARY = """
schema: cheme/failure-modes/v1
kind: failure-modes
example: true
source: synthetic test data
classes:
  CentrifugalPump:
    modes:
      - {id: M1, gives: {parameter: flow, guide_word: "no", towards: both}, needs: power}
      - {id: M2, gives: {parameter: flow, guide_word: reverse, towards: downstream}}
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, via: outlet, effect: responds,
         gives: {parameter: temperature, guide_word: more, towards: none}}
      - {incoming: {parameter: temperature, guide_word: more}, effect: stops,
         top_event: loss-of-containment}
      - {incoming: {parameter: flow, guide_word: "no"}, via: inlet, effect: passes}
  OperatedValve:
    modes:
      - {id: M3, gives: {parameter: flow, guide_word: "no", towards: both}, needs: actuation,
         fail: closed}
      - {id: M4, gives: {parameter: flow, guide_word: more}, needs: actuation, fail: open}
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, effect: passes}
      - {incoming: {parameter: flow, guide_word: more}, effect: passes}
      - {incoming: {parameter: flow, guide_word: reverse}, effect: passes}
  CheckValve:
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, effect: passes}
      - {incoming: {parameter: flow, guide_word: reverse}, effect: passes}
  Vessel:
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, via: outlet, effect: responds,
         gives: {parameter: level, guide_word: more, towards: none}}
      - {incoming: {parameter: level, guide_word: more}, effect: stops, top_event: overfill}
"""


def library(text: str = LIBRARY) -> FailureModeLibrary:
    return FailureModeLibrary.model_validate(yaml.safe_load(text))


def draw(path: Path) -> None:
    """V-101 -> 80-P-101 -> P-101 -> 50-P-102 (CV-1, FV-104) -> off-page, LT-102 on V-101,
    FIC-104 on 50-P-102 actuating FV-104."""
    shutil.copy(EMPTY, path)
    sheet = Sheet.load(path)
    vessel = equipment(
        sheet,
        "PressureVessel",
        "V-101",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(100, 120),
        nozzles=[Nozzle("N2", (0, 20), 80), Nozzle("N5", (10, -12), 25)],
    )
    pump = equipment(
        sheet,
        "CentrifugalPump",
        "P-101",
        shape="CENTRIFUGAL_PUMP_SHAPE",
        at=(160, 170),
        nozzles=[Nozzle("N1", (-7.5, 0), 80), Nozzle("N2", (0, -7.5), 50)],
    )
    line(sheet, "80-P-101", dn=80, fluid="Water", route=[vessel["N2"], (100, 170), pump["N1"]])
    control_valve = valve("FV104", "GlobeValve", at=(220, 100), tag="FV-104")
    discharge = line(
        sheet,
        "50-P-102",
        dn=50,
        fluid="Water",
        route=[
            pump["N2"],
            (160, 100),
            valve("CV1", "SwingCheckValve", at=(190, 100), tag="CV-1"),
            control_valve,
            offpage("out", at=(260, 100)),
        ],
    )
    instrument(sheet, "LT-102", at=(130, 95), sensing=vessel["N5"])
    instrument(
        sheet,
        "FIC-104",
        at=(240, 80),
        sensing=discharge,
        sensing_at=(240, 100),
        signal_to=control_valve,
    )
    sheet.save()


@pytest.fixture(scope="module")
def model(tmp_path_factory):
    path = tmp_path_factory.mktemp("sheet") / "P-01.xml"
    draw(path)
    return dexpi_io.load(path.read_bytes()).model


def run(model, members, context=None, deviation=None, lib=None):
    refs = [PlantRef(tag=m) for m in members]
    return propagate([("P-01", model)], lib or library(), refs, context, deviation)


def tags(candidate) -> list[str]:
    return [s.label for s in candidate.path]


def test_a_response_says_what_it_turns_into_or_where_it_stops():
    base = (
        "schema: cheme/failure-modes/v1\nkind: failure-modes\nclasses:\n  Vessel:\n    responses:\n"
    )
    with pytest.raises(ValidationError, match="gives"):
        library(
            base + "      - {incoming: {parameter: flow, guide_word: 'no'}, effect: responds}\n"
        )
    with pytest.raises(ValidationError, match="top_event"):
        library(base + "      - {incoming: {parameter: flow, guide_word: 'no'}, effect: stops}\n")
    assert library(base.rstrip("\n") + " []\n").classes["Vessel"].responses == []


def test_a_local_cause_is_followed_downstream_to_the_study_limit(model):
    result = run(model, ["P-101", "50-P-102"], deviation=NO_FLOW)
    down = [c for c in result.candidates if c.cause == "P-101" and c.end == "study-limit"]
    assert len(down) == 1
    candidate = down[0]
    assert candidate.kind == "local" and candidate.mode == "M1" and candidate.at == "P-101"
    assert tags(candidate)[:3] == ["P-101", "CV-1", "FV-104"]
    assert candidate.path[-1].effect == "study-limit"
    assert candidate.fluid == "Water"
    assert ("control", "FIC-104") in [(g.kind, g.ref) for g in candidate.safeguards]


def test_a_pipe_may_end_at_an_item_of_a_later_segment():
    from pydexpi.pydexpi_classes import pydexpi_classes as d

    a, b = d.GateValve(id="A"), d.GateValve(id="B")
    first = d.PipingNetworkSegment(
        id="S1", items=[a], connections=[d.Pipe(sourceItem=a, targetItem=b)]
    )
    second = d.PipingNetworkSegment(id="S2", items=[b])
    system = d.PipingNetworkSystem(id="L1", segments=[first, second])
    model = d.EngineeringModel(conceptualModel=d.PlantModel(pipingNetworkSystems=[system]))
    index = prop._index([("P-01", model)])
    assert [(t, s) for t, s in index.down[id(a)]] == [(id(b), id(first))]


def test_upstream_the_vessel_fills_to_a_top_event_with_its_level_trip(model):
    context = Context(interlocks={"LT-102": ["I-01"]})
    result = run(model, ["P-101"], context, NO_FLOW)
    up = [c for c in result.candidates if c.top_event == "overfill"]
    assert len(up) == 1
    candidate = up[0]
    assert [(s.label, s.deviation.text(), s.effect) for s in candidate.path] == [
        ("P-101", "no flow", "cause"),
        ("V-101", "no flow", "responds"),
        ("V-101", "more level", "stops"),
    ]
    guards = [(g.kind, g.ref) for g in candidate.safeguards]
    assert ("instrument", "LT-102") in guards and ("interlock", "I-01") in guards


def test_an_unrecorded_fail_position_keeps_both_branches_with_a_question(model):
    result = run(model, ["FV-104"])
    modes = {c.mode for c in result.candidates if c.cause == "FV-104"}
    assert modes == {"M3", "M4"}
    assert all("fail position of FV-104 not recorded" in c.questions[0] for c in result.candidates)

    closed = run(model, ["FV-104"], Context(fail={"FV-104": "closed"}))
    assert {c.mode for c in closed.candidates} == {"M3"}
    assert all(not c.questions for c in closed.candidates)


def test_an_actuation_failure_needs_an_actuated_valve(model):
    # CV-1 is no OperatedValve, and a library entry for check valves with an actuation mode
    # would not apply to it either: it has no actuating system.
    text = LIBRARY.replace(
        "  CheckValve:\n",
        "  CheckValve:\n    modes:\n      - {id: M9, gives: {parameter: flow, guide_word: 'no'}, "
        "needs: actuation}\n",
    )
    assert run(model, ["CV-1"], lib=library(text)).candidates == []


def test_a_driver_brings_another_deviation_into_the_node(model):
    hot = Deviation("temperature", "more")
    result = run(model, ["P-101", "FV-104"], Context(fail={"FV-104": "closed"}), hot)
    drivers = [c for c in result.candidates if c.cause == "FV-104"]
    assert drivers and all(c.kind == "driver" and c.at == "P-101" for c in drivers)
    assert drivers[0].top_event == "loss-of-containment"
    assert tags(drivers[0])[0] == "FV-104" and drivers[0].reached > 0


def test_reverse_flow_names_the_check_valve_on_its_path(model):
    result = run(model, ["P-101"], deviation=Deviation("flow", "reverse"))
    assert result.candidates
    guards = [(g.kind, g.ref) for g in result.candidates[0].safeguards]
    assert ("check-valve", "CV-1") in guards


def test_a_missing_response_ends_the_walk_with_a_question(model):
    # The most specific class with an entry wins: an empty SwingCheckValve entry hides CheckValve.
    lib = library(LIBRARY.replace("  CheckValve:", "  SwingCheckValve: {}\n  CheckValve:"))
    result = run(model, ["P-101"], deviation=NO_FLOW, lib=lib)
    stuck = [c for c in result.candidates if c.end == "unknown"]
    assert stuck and tags(stuck[0])[-1] == "CV-1"
    assert "no response of SwingCheckValve (CV-1) to no flow" in stuck[0].questions[-1]


def test_a_response_that_repeats_itself_ends_as_visited(model):
    lib = library(
        LIBRARY.replace(
            "effect: stops, top_event: overfill}",
            "effect: responds,\n"
            "         gives: {parameter: level, guide_word: more, towards: none}}",
        )
    )
    result = run(model, ["P-101"], deviation=NO_FLOW, lib=lib)
    assert any(c.end == "visited" for c in result.candidates)


def test_members_not_drawn_or_not_in_the_library_are_reported(model):
    result = run(model, ["P-101", "LT-102", "X-999"])
    assert result.unresolved == ["X-999"]
    assert result.uncovered == ["LT-102 (ProcessInstrumentationFunction)"]


def test_a_line_member_brings_its_segments_into_the_node(model):
    # V-101 has no failure mode; P-101's no flow reaches it through 80-P-101 only.
    result = run(model, ["P-101", "80-P-101"], deviation=NO_FLOW)
    assert any(c.at == "P-101" for c in result.candidates)
    alone = run(model, ["V-101", "80-P-101"], deviation=NO_FLOW)
    assert alone.candidates == []  # the cause (P-101) is outside the node: induced


def test_a_relief_device_next_to_the_path_is_a_pressure_safeguard():
    index = prop._Index()
    index.objects[1] = prop._Object("P-01", "V1", "V-1", "PressureVessel", ("PressureVessel",))
    index.objects[2] = prop._Object(
        "P-01",
        "PSV1",
        "PSV-1",
        "SpringLoadedGlobeSafetyValve",
        ("SpringLoadedGlobeSafetyValve", "SafetyValveOrFitting"),
    )
    index.down[1] = [(2, 10)]
    step = prop.Step(
        "P-01", "V1", "V-1", "PressureVessel", Deviation("pressure", "more"), "cause", 1
    )
    guards = prop._safeguards(index, [step], Context())
    assert [(g.kind, g.ref) for g in guards] == [("relief", "PSV-1")]
    flow = prop.Step("P-01", "V1", "V-1", "PressureVessel", NO_FLOW, "cause", 1)
    assert prop._safeguards(index, [flow], Context()) == []


# ---------------------------------------------------------------------------
# cheme safety hazop propagate
# ---------------------------------------------------------------------------

runner = CliRunner()


@pytest.fixture
def plant(tmp_path: Path, monkeypatch) -> Path:
    root = tmp_path / "plant"
    init(root, "Test plant")
    monkeypatch.chdir(root)
    draw(root / "pid" / "P-01.xml")
    result = runner.invoke(app, ["safety", "hazop", "init", "H-01", "--input", "pid/P-01.xml"])
    assert result.exit_code == 0, result.output
    study = root / "safety" / "hazop" / "H-01" / "study.yaml"
    data = yaml.safe_load(study.read_text(encoding="utf-8"))
    data["nodes"] = [
        {
            "id": "N2",
            "members": ["P-101", "FV-104", "50-P-102"],
            "deviations": [{"id": "N2-NF", "guide_word": "no", "parameter": "flow"}],
        }
    ]
    study.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return root


def test_the_command_needs_the_library(plant):
    result = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--node", "N2"])
    assert result.exit_code == 2
    assert "no failure-mode library safety/failure-modes.yaml" in result.output


def test_the_command_prints_the_candidates_and_writes_nothing(plant):
    (plant / "safety" / "failure-modes.yaml").write_text(LIBRARY, encoding="utf-8")
    study = plant / "safety" / "hazop" / "H-01" / "study.yaml"
    before = study.read_text(encoding="utf-8")
    result = runner.invoke(
        app,
        ["safety", "hazop", "propagate", "H-01", "--node", "N2", "--deviation", "N2-NF", "--json"],
    )
    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert out["sheets"] == ["P-01"]
    assert {c["deviation"]["guide_word"] for c in out["candidates"]} == {"no"}
    assert any(c["top_event"] == "overfill" for c in out["candidates"])
    assert study.read_text(encoding="utf-8") == before

    text = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--node", "N2"])
    assert text.exit_code == 0 and "P-101 M1 [local]" in text.output

    missing = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--node", "N9"])
    assert missing.exit_code == 2 and "no node N9" in missing.output
