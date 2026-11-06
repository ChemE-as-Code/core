"""Completeness of a HAZOP node (domains/safety/completeness.py): the deviations its equipment
calls for and the cause families it has to consider, as gap kinds of
``cheme safety hazop propagate --coverage`` (ADR 0036)."""

from __future__ import annotations

import json

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.safety import completeness as comp
from chemeascode.domains.safety import propagation as prop
from chemeascode.domains.safety.schemas import HazopCoverage, Node, Outcome
from chemeascode.interfaces.cli import app
from tests.test_hazop_propagation import gates, model, plant  # noqa: F401 - fixtures

runner = CliRunner()
PLANT = comp.Plant(
    utilities=[{"id": "power", "title": "Electric power"}],
    site={"climate": "cold winters"},
    interlocks={"I-01": {"LT-102", "P-101"}},
)


def node(members, deviations=(), node_id="N2") -> Node:
    return Node.model_validate(
        {"id": node_id, "members": list(members), "deviations": list(deviations)}
    )


def decision(**fields) -> Outcome:
    return Outcome.model_validate({"node": "N2", "reason": "test", "by": "agent", **fields})


@pytest.fixture(scope="module")
def index(model):  # noqa: F811 - the sheet fixture
    return prop._index([("P-01", model)])


def test_families_come_from_the_dexpi_classes_of_the_members(index):
    assert comp.families({"Tank", "Vessel", "ProcessEquipment"}) == ["vessel"]
    relief = {"SpringLoadedGlobeSafetyValve", "SafetyValveOrFitting", "PipingComponent"}
    assert comp.families(relief) == [
        "line",  # a relief device is a piping component too
        "relief",
    ]
    assert comp.families({"ProcessInstrumentationFunction"}) == []
    pump_and_line = comp.node_classes(index, node(["P-101", "80-P-101"]))
    assert comp.families(pump_and_line) == ["line", "machine"]
    assert comp.families(comp.node_classes(index, node(["V-101"]))) == ["vessel"]


def test_an_expected_deviation_the_node_does_not_develop_is_a_gap(index):
    deviations = [
        {"guide_word": "more", "parameter": "Level", "notes": "overfill: see N1"},  # notes only
        {"guide_word": "less", "parameter": "level"},  # neither scenario nor notes
    ]
    vessel = node(["V-101"], deviations)
    result = comp.completeness(index, vessel, PLANT)
    gaps = {g.text() for g in result.deviations}
    assert "more level" not in gaps and "less level" in gaps
    assert {"more temperature", "less temperature", "more pressure"} <= gaps
    assert result.developed == 1
    assert all(g.families == ["vessel"] for g in result.deviations)

    # A decision without a guide word decides every guide word of its parameter.
    one_fluid = decision(kind="deviation", parameter="temperature", status="dismissed")
    asked = decision(kind="deviation", guide_word="less", parameter="level", status="question")
    decided = comp.completeness(index, vessel, PLANT, [one_fluid, asked])
    left = {g.text() for g in decided.deviations}
    assert not {"more temperature", "less temperature", "less level"} & left
    assert (decided.deviations_dismissed, decided.deviations_questions) == (2, 1)
    other_node = decision(kind="deviation", node="N9", parameter="temperature", status="dismissed")
    assert comp.completeness(index, vessel, PLANT, [other_node]).deviations == result.deviations


def test_a_node_without_members_gets_no_gaps(index):
    assert comp.completeness(index, node([], node_id="N18"), PLANT) == comp.Completeness([], [])


def test_utilities_and_site_hazards_are_asked_once_each_at_the_global_node(index):
    site = comp.Plant(
        utilities=[{"id": "power"}, {"id": "nitrogen"}],
        site={
            "climate": "cold winters",
            "location": "inland",
            "occupancy": "low",
            "seismic": "zone 2",
        },
    )
    found = comp.completeness(index, node([], node_id="N18"), site, study_wide="N18")
    assert [(p.family, p.item) for p in found.causes] == [
        ("utility", "power"), ("utility", "nitrogen"),
        ("external", "climate"), ("external", "seismic"), ("external", "fire"),
    ]  # fmt: skip
    assert found.deviations == []  # no members: nothing to deviate
    # A node with members then asks only its own families.
    member = prompts(comp.completeness(index, node(["P-101", "50-P-102"]), site, study_wide="N18"))
    assert "utility" not in member and "external" not in member
    # Each item is decided on its own.
    one = decision(node="N18", kind="cause", family="utility", item="power", status="dismissed")
    left = comp.completeness(index, node([], node_id="N18"), site, [one], study_wide="N18")
    assert ("utility", "power") not in [(p.family, p.item) for p in left.causes]
    assert ("utility", "nitrogen") in [(p.family, p.item) for p in left.causes]
    assert left.causes_dismissed == 1
    # A study-wide decision may name a scenario of any node; a node's own may not.
    row = {"id": "S5", "cause": "nitrogen lost", "refs": ["P-101"]}
    flow = {"guide_word": "more", "parameter": "flow", "scenarios": [row]}
    study = [node([], node_id="N18"), node(["P-101"], [flow])]
    wide = decision(
        node="N18",
        kind="cause",
        family="utility",
        item="nitrogen",
        status="covered",
        scenarios=["S5"],
    )
    assert comp.check_decisions(study, [wide]) == []
    own = decision(node="N3", kind="cause", family="operator", status="covered", scenarios=["S5"])
    assert comp.check_decisions([*study, node(["V-101"], node_id="N3")], [own])


def prompts(result) -> dict[str, list[str]]:
    return {p.family: [i.label for i in p.items] for p in result.causes}


def test_cause_prompts_list_the_plant_items_of_each_family(index):
    line_node = node(["P-101", "FV-104", "50-P-102", "FIC-104"])
    found = prompts(comp.completeness(index, line_node, PLANT))
    assert found["utility"] == ["power"] and found["external"] == ["climate", "fire"]
    assert len(found["boundary"]) == 1  # the off-page connector at the end of 50-P-102
    assert found["control"] == ["FIC-104", "I-01"]  # a controller; a C&E naming P-101
    assert "operator" not in found  # FV-104 is actuated, CV-1 a check valve
    vessel = prompts(comp.completeness(index, node(["V-101", "80-P-101"]), PLANT))
    assert sorted(vessel) == ["external", "utility"]
    bare = prompts(comp.completeness(index, node(["V-101"]), comp.Plant()))
    assert bare == {"utility": [], "external": ["fire"]}  # fire, whatever the site

    manual = gates([("A", "B")])
    by_hand = prop._index([("P-01", manual)])
    refs = [{"sheet": "P-01", "object": "A"}]
    assert prompts(comp.completeness(by_hand, node(refs), comp.Plant()))["operator"] == ["A"]


def test_a_scenario_naming_an_item_covers_its_prompt(index):
    members = ["P-101", "FV-104", "50-P-102", "FIC-104"]
    limit = comp.completeness(index, node(members), PLANT).causes
    connector = next(p for p in limit if p.family == "boundary").items[0].names[-1]
    rows = [
        {"id": "S1", "cause": "FIC-104 fails", "refs": ["FIC-104"]},
        {"id": "S2", "cause": "back pressure", "refs": [{"sheet": "P-01", "object": connector}]},
    ]
    flow = [{"guide_word": "no", "parameter": "flow", "scenarios": rows}]
    result = comp.completeness(index, node(members, flow), PLANT)
    assert sorted(prompts(result)) == ["external", "utility"]  # never covered by refs
    assert result.covered == 2


def test_a_covered_decision_names_scenarios_of_its_node(index):
    with pytest.raises(ValidationError, match="needs the scenarios"):
        decision(kind="cause", family="utility", status="covered")
    with pytest.raises(ValidationError, match="cause outcomes only"):
        decision(kind="deviation", parameter="flow", status="covered", scenarios=["S1"])
    with pytest.raises(ValidationError, match="needs its family"):
        decision(kind="cause", status="dismissed")
    with pytest.raises(ValidationError, match="needs guide_word"):
        Outcome.model_validate({"node": "N2", "guide_word": "no", "parameter": "flow"})
    rows = [{"id": "S1", "cause": "power fails", "refs": ["P-101"]}]
    study = [node(["P-101"], [{"guide_word": "no", "parameter": "flow", "scenarios": rows}])]
    good = decision(kind="cause", family="utility", status="covered", scenarios=["S1"])
    bad = decision(kind="cause", family="external", status="covered", scenarios=["S9"])
    assert comp.check_decisions(study, [good]) == []
    assert comp.check_decisions(study, [bad]) == ["N2 external: covered by S9, no scenario of N2"]
    result = comp.completeness(index, study[0], PLANT, [good])
    assert "utility" not in prompts(result) and result.covered == 1


def test_the_triage_keeps_the_decisions_of_every_kind(index):
    result = comp.completeness(index, node(["V-101"]), PLANT)
    wanted = comp.wanted("N2", result, "tool")
    kinds = {o.kind for o in wanted}
    assert kinds == {"deviation", "cause"}
    assert next(o for o in wanted if o.family == "external").causes == ["climate", "fire"]
    dismissed = decision(kind="deviation", parameter="temperature", status="dismissed")
    covered = decision(kind="cause", family="utility", status="covered", scenarios=["S1"])
    stale = Outcome.model_validate({"kind": "cause", "node": "N2", "family": "control"})
    walk = Outcome.model_validate(
        {"node": "N2", "guide_word": "no", "parameter": "flow", "top_event": "overfill", "at": "X"}
    )
    listed = prop.triage([], [dismissed, covered, stale, walk], "tool", [("N2", wanted)])
    assert listed[:3] == [dismissed, covered, walk]  # the walk was not run: its open one stays
    assert stale not in listed and all(o in listed for o in wanted)
    assert prop.triage([], listed, "tool", [("N2", wanted)]) == listed


def test_an_old_triage_file_still_loads():
    old = {
        "schema": "cheme/hazop-coverage/v1",
        "kind": "hazop-coverage",
        "study": "H-01",
        "walk": {"library": "sha256:0", "sheets": {"pid/P-01.xml": "sha256:1"}},
        "outcomes": [
            {
                "node": "N2",
                "guide_word": "no",
                "parameter": "flow",
                "top_event": "overfill",
                "at": "V-101",
                "status": "dismissed",
                "reason": "kept",
            }
        ],
    }
    loaded = HazopCoverage.model_validate(old)
    assert loaded.outcomes[0].kind == "walk" and loaded.walk.inputs == {}


def test_the_command_checks_completeness_without_a_library(plant):  # noqa: F811
    study = plant / "safety" / "hazop" / "H-01" / "study.yaml"
    data = yaml.safe_load(study.read_text(encoding="utf-8"))
    data["nodes"][1]["members"].append("FIC-104")
    study.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    coverage = ["safety", "hazop", "propagate", "H-01", "--coverage"]
    text = runner.invoke(app, coverage)
    assert text.exit_code == 1, text.output
    assert "walk: skipped (--no-walk, or no failure-mode library" in text.output
    assert "N2: reverse flow [line, machine]" in text.output
    assert "N2 control: a control or trip function acting wrongly" in text.output
    assert "FIC-104 (controller)" in text.output
    out = json.loads(runner.invoke(app, [*coverage, "--json"]).output)
    assert out["library"] is None and out["matrix"] == "default" and out["open"] > 0
    nodes = {n["node"]: n for n in out["nodes"]}
    assert "gaps" not in nodes["N2"]  # no walk
    assert {p["family"] for p in nodes["N1"]["causes"]["prompts"]} == {"utility", "external"}

    written = runner.invoke(app, [*coverage, "--write"])
    assert written.exit_code == 1 and "(written)" in written.output
    triage = plant / "safety" / "hazop" / "H-01" / "coverage.yaml"
    text_written = triage.read_text(encoding="utf-8")
    assert "null" not in text_written and "top_event" not in text_written
    data = yaml.safe_load(text_written)
    assert data["walk"]["library"] == "" and "process/design-basis.yaml" in data["walk"]["inputs"]
    assert {o["kind"] for o in data["outcomes"]} == {"deviation", "cause"}
    for entry in data["outcomes"]:
        entry.update(status="dismissed", reason="test: decided", by="agent")
    triage.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert runner.invoke(app, coverage).exit_code == 0

    # A covered decision naming no scenario of its node is refused.
    data["outcomes"][-1].update(status="covered", scenarios=["S9"])
    triage.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    refused = runner.invoke(app, coverage)
    assert refused.exit_code == 2 and "no scenario of" in refused.output

    # The project's matrix replaces the default.
    data["outcomes"] = []
    triage.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    matrix = {
        "schema": "cheme/hazop-deviation-matrix/v1",
        "kind": "hazop-deviation-matrix",
        "families": [{"id": "pump", "classes": ["Pump"], "deviations": {"flow": ["more"]}}],
    }
    (plant / "safety" / "deviation-matrix.yaml").write_text(yaml.safe_dump(matrix), "utf-8")
    own = json.loads(runner.invoke(app, [*coverage, "--json"]).output)
    assert own["matrix"] == "safety/deviation-matrix.yaml"
    gaps = {n["node"]: n["deviations"]["gaps"] for n in own["nodes"]}
    assert gaps == {
        "N1": [],
        "N2": [{"guide_word": "more", "parameter": "flow", "families": ["pump"]}],
    }
    assert "changed since it was written" in runner.invoke(app, coverage).output

    # With a library the walk runs, unless --no-walk asks for the two checks only.
    from tests.test_hazop_propagation import LIBRARY

    (plant / "safety" / "failure-modes.yaml").write_text(LIBRARY, encoding="utf-8")
    walked = {
        n["node"]: n for n in json.loads(runner.invoke(app, [*coverage, "--json"]).output)["nodes"]
    }
    assert "gaps" in walked["N2"]
    checks = runner.invoke(app, [*coverage, "--no-walk", "--json"])
    assert "gaps" not in {n["node"]: n for n in json.loads(checks.output)["nodes"]}["N2"]
    assert runner.invoke(app, ["safety", "hazop", "propagate", "H-01", "--no-walk"]).exit_code == 2


def test_the_matrix_kind_is_in_the_schema_catalogue():
    result = runner.invoke(app, ["schema", "hazop-deviation-matrix"])
    assert result.exit_code == 0 and "EquipmentFamily" in result.output
