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


GATES = """
schema: cheme/failure-modes/v1
kind: failure-modes
example: true
source: synthetic test data
classes:
  GateValve:
    modes:
      - {id: M5, gives: {parameter: flow, guide_word: "no", towards: downstream}}
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, effect: passes}
"""


def gates(edges: list[tuple[str, str]], roles: dict[str, str] | None = None):
    """A model of untagged gate valves joined by *edges*; *roles* gives a valve a role name."""
    from pydexpi.pydexpi_classes import pydexpi_classes as d

    names = sorted({n for edge in edges for n in edge})
    valves = {n: d.GateValve(id=n) for n in names}
    for name, role in (roles or {}).items():
        valves[name].performedRoles = [d.Role(name=role)]
    pipes = [d.Pipe(sourceItem=valves[a], targetItem=valves[b]) for a, b in edges]
    segment = d.PipingNetworkSegment(id="S1", items=list(valves.values()), connections=pipes)
    system = d.PipingNetworkSystem(id="L1", segments=[segment])
    return d.EngineeringModel(conceptualModel=d.PlantModel(pipingNetworkSystems=[system]))


def walk(model, members):
    refs = [PlantRef(sheet="P-01", object=m) for m in members]
    return propagate([("P-01", model)], library(GATES), refs).candidates


def test_two_routes_to_the_same_outcome_give_one_candidate_on_the_shorter():
    # A splits to B and C, which join again at D before E; C takes the long way round.
    model = gates([("A", "B"), ("A", "C"), ("C", "X"), ("X", "D"), ("B", "D"), ("D", "E")])
    ends = [c for c in walk(model, ["A"]) if c.end == "no-connection"]
    assert len(ends) == 1  # one per route before
    assert tags(ends[0]) == ["A", "B", "D", "E"]


def test_a_recycle_is_walked_once():
    model = gates([("A", "B"), ("B", "C"), ("C", "A"), ("B", "E")])
    candidates = walk(model, ["A"])
    assert {c.end for c in candidates} == {"visited", "no-connection"}
    assert all(c.end != "depth" for c in candidates)


@pytest.mark.parametrize(
    "role", ["Normally closed", "urn:example:valve-position:locked-closed", "CAR_SEALED_CLOSED"]
)
def test_a_valve_closed_in_normal_operation_stops_the_walk(role):
    model = gates([("A", "B"), ("B", "E")], roles={"B": role})
    candidates = [c for c in walk(model, ["A", "E"]) if c.cause == "A"]
    assert [(c.end, tags(c)) for c in candidates] == [("closed", ["A", "B"])]
    assert candidates[0].path[-1].effect == "closed"
    open_ = gates([("A", "B"), ("B", "E")], roles={"B": "Locked open"})
    assert all(c.end != "closed" for c in walk(open_, ["A"]))


STATES = """
schema: cheme/failure-modes/v1
kind: failure-modes
example: true
source: synthetic test data
classes:
  GateValve:
    modes:
      - {id: SHUT, gives: {parameter: flow, guide_word: "no", towards: downstream}}
      - {id: OPEN, gives: {parameter: flow, guide_word: more, towards: downstream}}
      - {id: BACK, gives: {parameter: pressure, guide_word: more, towards: upstream}}
    responses:
      - {incoming: {parameter: flow, guide_word: "no"}, effect: passes}
      - {incoming: {parameter: flow, guide_word: more}, effect: passes}
      - {incoming: {parameter: pressure, guide_word: more}, effect: passes}
  CheckValve:
    responses:
      - {incoming: {parameter: pressure, guide_word: more}, effect: passes}
      - {incoming: {parameter: flow, guide_word: "no"}, effect: passes}
"""


@pytest.mark.parametrize(
    ("role", "modes"),
    [
        ("Normally closed", {"OPEN"}),  # closed already: it can only open (or pass)
        ("Locked open", {"SHUT", "BACK"}),  # open already: it can only close
        (None, {"SHUT", "BACK"}),  # no role: open, as the P&ID draws it
    ],
)
def test_a_valve_fails_only_away_from_its_normal_state(role, modes):
    model = gates([("A", "B")], roles={"A": role} if role else None)
    refs = [PlantRef(sheet="P-01", object="A")]
    found = propagate([("P-01", model)], library(STATES), refs).candidates
    assert {c.mode for c in found if c.cause == "A"} == modes


def test_a_controllers_final_element_throttles_and_fails_both_ways(model):
    text = LIBRARY.replace(
        "  OperatedValve:\n    modes:\n",
        "  OperatedValve:\n    modes:\n"
        "      - {id: M8, gives: {parameter: flow, guide_word: 'no', towards: downstream}}\n",
    )
    # FV-104 is FIC-104's final element: a throttling valve keeps its opening and closing modes.
    found = run(model, ["FV-104"], Context(fail={"FV-104": "open"}), lib=library(text))
    assert {"M4", "M8"} <= {c.mode for c in found.candidates}


def test_a_check_valve_holds_pressure_coming_back():
    from pydexpi.pydexpi_classes import pydexpi_classes as d

    a, check, b = d.GateValve(id="A"), d.SwingCheckValve(id="CV"), d.GateValve(id="B")
    pipes = [d.Pipe(sourceItem=a, targetItem=check), d.Pipe(sourceItem=check, targetItem=b)]
    segment = d.PipingNetworkSegment(id="S1", items=[a, check, b], connections=pipes)
    system = d.PipingNetworkSystem(id="L1", segments=[segment])
    plant = d.EngineeringModel(conceptualModel=d.PlantModel(pipingNetworkSystems=[system]))
    refs = [PlantRef(sheet="P-01", object=m) for m in ("A", "B")]
    found = propagate([("P-01", plant)], library(STATES), refs).candidates
    back = [c for c in found if c.cause == "B" and c.mode == "BACK"]
    assert [(c.end, tags(c), c.path[-1].effect) for c in back] == [
        ("closed", ["B", "CV"], "check-valve")
    ]
    # Downstream, with the flow, it passes as before.
    forward = [c for c in found if c.cause == "A" and c.mode == "SHUT"]
    assert forward and tags(forward[0])[:3] == ["A", "CV", "B"]


def test_a_control_loop_failure_belongs_to_a_controller_and_its_variable():
    def mode(parameter, guide_word, towards):
        gives = {"parameter": parameter, "guide_word": guide_word, "towards": towards}
        return prop.FailureMode.model_validate(
            {"id": "X", "gives": gives, "at": "final-element", "mechanism": "test"}
        )

    hot, high_pressure = mode("temperature", "more", "none"), mode("pressure", "more", "none")
    trip = mode("flow", "no", "both")
    pic = prop._Instrument("PIC-403", "pressure", [], [1])
    logic = prop._Instrument("US-001", None, [], [1])
    alarm = prop._Instrument("PIAH-406", "pressure", [], [1])
    assert prop._loop_allows(high_pressure, pic) and not prop._loop_allows(hot, pic)
    assert not prop._loop_allows(high_pressure, logic)
    assert not prop._loop_allows(high_pressure, alarm)
    assert all(prop._loop_allows(trip, i) for i in (pic, logic, alarm))  # a spurious trip: any


def test_trains_studied_once_share_their_rows():
    assert prop._alike("MOV-413B", "MOV-413A") and prop._alike("P-401E", "P-401A")
    assert prop._alike("P-101", "P-101")
    assert not prop._alike("MOV-413", "MOV-414") and not prop._alike("SB-301", "SB-302")
    assert not prop._alike("PC_130", "PC_146")  # untagged objects: only themselves


def test_a_row_under_another_deviation_covers_the_walk(model):
    from chemeascode.domains.safety.schemas import Node

    candidates = run(model, ["P-101"]).candidates
    scenario = {"id": "S1", "cause": "P-101 stops", "refs": ["P-101", "V-101"]}
    node = Node.model_validate(
        {
            "id": "N2",
            "members": ["P-101"],
            "deviations": [{"guide_word": "more", "parameter": "level", "scenarios": [scenario]}],
        }
    )
    assert not at_vessel(prop.coverage(node, candidates))  # the no flow walk ends at V-101


def top_event(cause: tuple[str, str, str], end: tuple[str, str, str]) -> prop.Candidate:
    """A walk from *cause* to an overpressure at *end*, each (label, object id, train)."""
    over = Deviation("pressure", "more")
    steps = [
        prop.Step("P-01", obj, label, "GateValve", over, effect, key)
        for key, (label, obj, _train), effect in ((1, cause, "cause"), (2, end, "stops"))
    ]
    return prop.Candidate(
        over,
        cause[0],
        cause[0],
        "M",
        "test",
        "local",
        steps,
        0,
        "top-event",
        "overpressure",
        None,
        [],
        [],
        [],
        cause_names=tuple(dict.fromkeys(cause[:2])),
        cause_train=cause[2],
        end_names=tuple(dict.fromkeys(end[:2])),
        end_train=end[2],
    )


def node_with(refs: list):
    from chemeascode.domains.safety.schemas import Node

    scenario = {"id": "S1", "cause": "the valve", "refs": refs}
    return Node.model_validate(
        {
            "id": "N2",
            "members": ["V-1"],
            "deviations": [
                {"guide_word": "more", "parameter": "pressure", "scenarios": [scenario]}
            ],
        }
    )


def test_a_row_may_name_an_object_by_its_id_or_its_tag():
    # The walk names the kicker valve by its tag; the study names the same object by its id.
    kicker = ("Pig receiver kicker MOV", "PC_SG_KICKER_101", "Pig receiver kicker MOV")
    walk = [top_event(kicker, ("F-401A", "F401A", "F-401A"))]
    by_id = node_with([{"sheet": "P-01", "object": "PC_SG_KICKER_101"}, "F-401A"])
    assert prop.coverage(by_id, walk).gaps == [] and prop.coverage(by_id, walk).covered == 1
    elsewhere = node_with([{"sheet": "P-01", "object": "PC_OTHER"}, "F-401A"])
    assert prop.coverage(elsewhere, walk).gaps


def test_an_untagged_object_takes_the_train_of_its_neighbour():
    index = prop._Index()
    for key, (tag, cls) in enumerate(
        [
            ("MOV-412A", "GateValve"),
            (None, "SwingCheckValve"),
            ("MOV-412B", "GateValve"),
            (None, "SwingCheckValve"),
            (None, "SwingCheckValve"),
        ],
        start=1,
    ):
        index.objects[key] = prop._Object("P-01", f"PC_{key}", tag, cls, (cls, "CheckValve"))
    index.down[2], index.down[4] = [(1, 10)], [(3, 11)]  # PC_2 -> MOV-412A, PC_4 -> MOV-412B
    assert prop._train(index, 2) == "MOV-412A|SwingCheckValve"
    assert prop._alike(prop._train(index, 4), prop._train(index, 2))
    assert prop._train(index, 5) == "PC_5"  # no tagged neighbour: only itself
    # A row for train A's check valve covers train B's.
    walk = [top_event(("PC_4", "PC_4", prop._train(index, 4)), ("SB-301", "SB301", "SB-301"))]
    row = node_with([{"sheet": "P-01", "object": "PC_2"}, "SB-301"])
    walk.append(top_event(("PC_2", "PC_2", prop._train(index, 2)), ("SB-301", "SB301", "SB-301")))
    assert prop.coverage(row, walk).gaps == []


def test_a_candidate_names_the_other_nodes_its_path_enters(model):
    others = {"N1": [PlantRef(tag="V-101")], "N3": [PlantRef(tag="FV-104")]}
    refs = [PlantRef(tag="P-101")]
    result = propagate([("P-01", model)], library(), refs, deviation=NO_FLOW, others=others)
    by_end = {c.top_event or c.end: c.crosses for c in result.candidates if c.cause == "P-101"}
    assert by_end["overfill"] == [("N1", "V-101")]
    assert by_end["study-limit"] == [("N3", "FV-104")]
    # A line member of another node: its first object on the path names it.
    lines = {"N9": [PlantRef(tag="50-P-102")]}
    result = propagate([("P-01", model)], library(), refs, deviation=NO_FLOW, others=lines)
    limit = next(c for c in result.candidates if c.end == "study-limit")
    assert limit.crosses == [("N9", "CV-1")]


OVERFILL = {"node": "N2", "guide_word": "no", "parameter": "flow", "top_event": "overfill"}


def scenario_node(refs):
    from chemeascode.domains.safety.schemas import Node

    scenario = {"id": "S1", "cause": "P-101 stops", "refs": refs}
    return Node.model_validate(
        {
            "id": "N2",
            "members": ["P-101"],
            "deviations": [{"guide_word": "no", "parameter": "flow", "scenarios": [scenario]}],
        }
    )


def outcome(**fields):
    from chemeascode.domains.safety.schemas import Outcome

    return Outcome.model_validate({**OVERFILL, "at": "V-101", **fields})


def at_vessel(result):
    return [g for g in result.gaps if g.at == "V-101"]


def test_coverage_compares_the_scenarios_by_tag_and_takes_the_triage(model):
    candidates = run(model, ["P-101"]).candidates
    full = prop.coverage(scenario_node(["P-101", "V-101"]), candidates)
    assert not at_vessel(full) and full.covered and full.unreached == []
    cause_only = at_vessel(prop.coverage(scenario_node(["P-101"]), candidates))
    assert [(g.top_event, g.cause_only, g.uncovered) for g in cause_only] == [
        ("overfill", ["P-101"], [])
    ]
    elsewhere = prop.coverage(scenario_node(["X-1"]), candidates)
    assert at_vessel(elsewhere)[0].uncovered == ["P-101"] and elsewhere.unreached == ["S1"]

    gone = prop.coverage(
        scenario_node(["X-1"]), candidates, [outcome(status="dismissed", reason="the team's")]
    )
    assert not at_vessel(gone) and gone.dismissed == 1
    asked = prop.coverage(
        scenario_node(["X-1"]), candidates, [outcome(status="question", reason="which fluid?")]
    )
    assert not at_vessel(asked) and asked.questions == 1
    for undecided in (outcome(), outcome(status="dismissed", reason="x", causes=["P-9"])):
        result = prop.coverage(scenario_node(["X-1"]), candidates, [undecided])
        assert at_vessel(result) and result.dismissed == 0
    with pytest.raises(ValidationError, match="needs its reason"):
        outcome(status="dismissed")


def test_the_triage_lists_open_gaps_and_keeps_decisions(model):
    candidates = run(model, ["P-101"]).candidates
    gaps = prop.coverage(scenario_node(["X-1"]), candidates)
    decided = outcome(at="X-9", status="dismissed", reason="kept")
    stale_open = outcome(at="X-8")
    elsewhere = outcome(node="N7", at="X-7")
    listed = prop.triage([("N2", gaps)], [decided, stale_open, elsewhere], "tool")
    assert decided in listed and elsewhere in listed and stale_open not in listed
    vessel = [o for o in listed if o.at == "V-101"]
    assert [(o.status, o.causes, o.by) for o in vessel] == [("open", ["P-101"], "tool")]
    again = prop.triage([("N2", gaps)], listed, "tool")
    assert again == listed  # a second write changes nothing


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
        {"id": "N1", "members": ["V-101", "80-P-101"]},
        {
            "id": "N2",
            "members": ["P-101", "FV-104", "50-P-102"],
            "deviations": [{"id": "N2-NF", "guide_word": "no", "parameter": "flow"}],
        },
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
    assert text.exit_code == 0
    assert "no flow -> overfill at V-101 (Water) [via N1]: P-101" in text.output
    assert "path:" not in text.output
    assert "question (" in text.output  # FV-104's fail position, once with its count
    paths = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--node", "N2", "--paths"])
    assert paths.exit_code == 0 and "P-101 M1 [local]" in paths.output
    assert "path: P-101 (no flow, cause)" in paths.output
    assert "  crosses: N1 at V-101" in paths.output

    every = runner.invoke(app, ["safety", "hazop", "propagate", "H-01"])
    assert every.exit_code == 0, every.output
    assert "overfill at V-101 (Water): 1 node(s)\n  N2: P-101" in every.output
    data = json.loads(runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--json"]).output)
    assert data["nodes"] == ["N1", "N2"]
    overfill = next(c for c in data["consequences"] if c["top_event"] == "overfill")
    assert overfill["nodes"] == [{"node": "N2", "causes": ["P-101"]}]
    alone = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--deviation", "no flow"])
    assert alone.exit_code == 2 and "--deviation needs --node" in alone.output

    node_coverage = ["safety", "hazop", "propagate", "H-01", "--node", "N2", "--coverage"]
    gaps = runner.invoke(app, node_coverage)
    assert gaps.exit_code == 1, gaps.output
    assert "N2: no flow -> overfill at V-101 (Water) [via N1]; no scenario: P-101" in gaps.output
    every = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--coverage", "--json"])
    assert every.exit_code == 1
    nodes = {n["node"]: n for n in json.loads(every.output)["nodes"]}
    assert nodes["N1"]["gaps"] == [] and nodes["N2"]["gaps"]
    both = ["safety", "hazop", "propagate", "H-01", "--coverage", "--deviation", "N2-NF"]
    assert runner.invoke(app, both).exit_code == 2
    assert runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--write"]).exit_code == 2

    # The triage file: written open, decided by hand, kept by the next write.
    triage = plant / "safety" / "hazop" / "H-01" / "coverage.yaml"
    written = runner.invoke(app, [*node_coverage, "--write"])
    assert written.exit_code == 1 and "(written)" in written.output
    data = yaml.safe_load(triage.read_text(encoding="utf-8"))
    assert data["kind"] == "hazop-coverage" and data["walk"]["sheets"]
    assert b"\r\n" not in triage.read_bytes()
    assert "reason:" not in triage.read_text(encoding="utf-8")  # empty fields left out
    for entry in data["outcomes"]:
        entry.update(status="dismissed", reason="test: not credible here", by="agent")
    triage.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    closed = runner.invoke(app, [*node_coverage, "--write"])
    assert closed.exit_code == 0, closed.output
    assert yaml.safe_load(triage.read_text(encoding="utf-8"))["outcomes"] == data["outcomes"]
    assert study.read_text(encoding="utf-8") == before

    pid = plant / "pid" / "P-01.xml"
    pid.write_bytes(pid.read_bytes() + b"\n")
    assert "changed since it was written" in runner.invoke(app, node_coverage).output
    assert study.read_text(encoding="utf-8") == before

    missing = runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--node", "N9"])
    assert missing.exit_code == 2 and "no node N9" in missing.output
