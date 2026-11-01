"""Reaction evidence (process/reaction-evidence.yaml): the schema, the cheme.evidence-* rules,
the route comparison of cheme chemistry evidence and the findings in cheme validate.

The worked example is ``examples/reaction-evidence-ethyl-acetate``: three routes to ethyl
acetate from papers and patents read in full, with conflicting kinetics, sources that could
not be read, missing kinetics, an ambiguous yield basis and the handoff to reactions.yaml."""

import copy
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.chemistry.evidence import (
    EVIDENCE_FILE,
    Declared,
    ReactionEvidence,
    Value,
    comparison_text,
    route_comparison,
    rules,
)
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.evidence import evidence_findings
from chemeascode.project.validate import validate_workspace

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "reaction-evidence-ethyl-acetate"
runner = CliRunner()


def _example() -> dict:
    return yaml.safe_load((EXAMPLE / EVIDENCE_FILE).read_text(encoding="utf-8"))


def _rules(data: dict, declared: Declared | None = None) -> list:
    return rules(ReactionEvidence.model_validate(data), None, declared)


def _ids(findings, rule: str) -> list[list[str]]:
    return [f.ids for f in findings if f.rule == f"cheme.evidence-{rule}"]


def _minimal(**overrides) -> dict:
    """One source read in full, one route, one observation with a conversion."""
    data = {
        "schema": "cheme/reaction-evidence/v1",
        "kind": "reaction-evidence",
        "product": "P",
        "sources": [
            {
                "id": "S1",
                "kind": "paper",
                "doi": "10.1000/xyz",
                "accessed": "2026-01-02",
                "access": "full-text",
            },
        ],
        "routes": [{"id": "R1", "reactants": ["A"], "products": ["P"]}],
        "observations": [
            {
                "id": "O1",
                "source": "S1",
                "route": "R1",
                "location": "Table 1",
                "kind": "experiment",
                "conversion": [{"component": "A", "value": {"value": 50, "unit": "%"}}],
            },
        ],
    }
    data.update(overrides)
    return data


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root)
    return root


# -- the worked example -------------------------------------------------------------------------


def test_the_example_validates_without_errors_and_flags_the_ambiguous_yields(plant):
    report = validate_workspace(Workspace(plant))
    evidence = [f for f in report.findings if f.file == EVIDENCE_FILE]
    assert not [f for f in report.findings if f.level == "error"], [
        f.format() for f in report.findings
    ]
    assert EVIDENCE_FILE in report.files
    # the patent reports a yield of 95 % above a conversion of 66 % and says of neither what
    # it is relative to: flagged, not repaired
    assert {f.ids[0] for f in evidence} == {"O-BP-1", "O-BP-4"}
    assert {f.rule for f in evidence} == {"cheme.evidence-yield-basis"}
    assert len({f.id for f in evidence}) == len(evidence)


def test_the_example_compares_routes_with_conflicts_gaps_and_unread_sources():
    evidence = ReactionEvidence.model_validate(_example())
    by_id = {s.id: s for s in route_comparison(evidence)}
    assert list(by_id) == ["ESTER", "DEHYD", "ADD"]
    ester = by_id["ESTER"]
    assert ester.status == "selected"
    assert ester.sources == ["S-KIR", "S-AHM"]
    assert ester.temperature == pytest.approx((313.15, 353.0))
    assert ester.performance["conversion"]["AcOH"] == pytest.approx((0.68, 0.75))
    assert len(ester.kinetics) == 2
    assert any("activation energy" in c for c in ester.conflicts)
    assert any("catalyst-mass basis" in g for g in ester.gaps)  # missing kinetics
    dehyd = by_id["DEHYD"]
    # an assumed pressure (the patent does not say absolute or gauge) does not count
    assert dehyd.pressure == pytest.approx((101.325, 101.325))
    assert dehyd.performance["selectivity"]["EtOAc"] == pytest.approx((0.20, 0.35))
    add = by_id["ADD"]
    assert "conversion" in add.performance and "yield" in add.performance
    assert add.scales == ["patent-example"]
    text = comparison_text(evidence)
    for unread in ("S-CAL (unavailable)", "S-SAN (snippet)", "S-CAR (unavailable)"):
        assert f"not read, no observation: {unread}" in text
    assert "model basis: route ESTER, reactions ESTERIF, catalyst AMB15" in text


def test_the_example_hands_over_to_the_reactions_file(plant):
    evidence = ReactionEvidence.model_validate(_example())
    reactions = Reactions.model_validate(
        yaml.safe_load((plant / "process/reactions.yaml").read_text(encoding="utf-8"))
    )
    basis = evidence.model_basis
    assert basis is not None and basis.reactions == ["ESTERIF"]
    model = reactions.by_id()["ESTERIF"]
    assert model.conversion is not None and model.conversion.value == 0.75
    assert "O-KIR-CONV" in model.conversion.source
    # the handoff is clean; without the citation it is reported
    found, _ = evidence_findings(plant)
    assert not _ids(found, "handoff")
    text = (plant / "process/reactions.yaml").read_text(encoding="utf-8")
    (plant / "process/reactions.yaml").write_text(
        text.replace("reaction-evidence O-KIR-CONV (S-KIR p. 574)", "a handbook"), "utf-8"
    )
    found, _ = evidence_findings(plant)
    handoff = [f for f in found if f.rule == "cheme.evidence-handoff"]
    assert [(f.file, f.level, f.ids) for f in handoff] == [
        ("process/reactions.yaml", "info", ["ESTERIF"])
    ]
    assert handoff[0].line is not None


# -- schema -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, problem",
    [
        ({"value": 1, "range": [0, 2], "unit": "K"}, "not both"),
        ({"unit": "K"}, "not both"),
        ({"range": [3, 2], "unit": "K"}, "min <= max"),
        ({"value": 1, "unit": "K", "status": "derived"}, "derived_from"),
        ({"value": 1, "unit": "K", "status": "assumed"}, "note"),
    ],
)
def test_a_value_says_what_it_is(value, problem):
    with pytest.raises(ValidationError, match=problem):
        Value.model_validate(value)


def test_a_wrong_schema_or_unknown_key_is_a_schema_finding(plant):
    path = plant / EVIDENCE_FILE
    path.write_text(
        path.read_text(encoding="utf-8")
        .replace("  question:", "  questoin:", 1)
        .replace("question: >-", "questoin: >-", 1),
        "utf-8",
    )
    found, present = evidence_findings(plant)
    assert present
    assert [f.rule for f in found] == ["cheme.evidence-schema"]
    assert "questoin" in found[0].message and found[0].line is not None


# -- rules --------------------------------------------------------------------------------------


def test_the_minimal_file_is_clean():
    assert _rules(_minimal()) == []


def test_references_ids_and_identities():
    data = _minimal()
    data["sources"] += [
        {"id": "S2", "kind": "patent", "accessed": "2026-01-02", "access": "full-text"},
        {
            "id": "S3",
            "kind": "paper",
            "doi": "doi:10.1/x",
            "accessed": "2026-01-02",
            "access": "full-text",
        },
        {
            "id": "S4",
            "kind": "patent",
            "patent": "US 7,652,167",
            "accessed": "2026-01-02",
            "access": "full-text",
        },
        {"id": "S5", "kind": "paper", "accessed": "2026-01-02", "access": "abstract"},
        {"id": "O1", "kind": "web", "accessed": "2026-01-02", "access": "full-text"},
    ]
    data["observations"].append(
        {"id": "O2", "source": "S9", "route": "R9", "location": "p. 1", "kind": "experiment"}
    )
    data["conflicts"] = [{"about": "k", "observations": ["O1", "O7"]}]
    data["searches"] = [{"query": "q", "tool": "web search", "date": "2026-01-02", "found": ["S8"]}]
    found = _rules(data)
    assert _ids(found, "duplicate-id") == [["O1"]]
    assert sorted(_ids(found, "reference")) == [["O7"], ["R9"], ["S8"], ["S9"]]
    identity = {(f.ids[0], f.level) for f in found if f.rule == "cheme.evidence-identity"}
    assert identity == {("S2", "error"), ("S3", "error"), ("S4", "warning"), ("S5", "warning")}


def test_numbers_need_a_location_and_a_source_that_was_read():
    data = _minimal()
    data["observations"][0]["location"] = ""
    assert _ids(_rules(data), "location") == [["O1"]]
    for access in ("snippet", "unavailable"):
        data = _minimal()
        data["sources"][0]["access"] = access
        found = _rules(data)
        assert _ids(found, "access") == [["O1", "S1"]]
        assert "snippet does not establish" in found[0].hint
    # what the source does not give is listed, not filled in: no values, no finding
    data = _minimal()
    data["sources"][0]["access"] = "unavailable"
    data["observations"][0]["conversion"] = []
    data["observations"][0]["missing"] = ["full text unavailable: conversion not read"]
    assert _rules(data) == []
    # a derived or assumed value is no claim of the source
    data = _minimal()
    data["sources"][0]["access"] = "snippet"
    data["observations"][0]["conversion"][0]["value"] |= {"status": "assumed", "note": "guess"}
    assert _rules(data) == []


@pytest.mark.parametrize(
    "where, value, problem",
    [
        ("temperature", {"value": 300, "unit": "F"}, "temperature in 'F'"),
        ("temperature", {"value": -300, "unit": "°C"}, "not above 0 K"),
        ("pressure", {"value": 1, "unit": "bar"}, "pressure in 'bar'"),
        ("residence_time", {"value": 1, "unit": "hours"}, "residence_time in 'hours'"),
        ("catalyst_loading", {"value": 1, "unit": " "}, "has no unit"),
    ],
)
def test_condition_units(where, value, problem):
    data = _minimal()
    data["observations"][0]["conditions"] = {where: value}
    found = _rules(data)
    assert [f.rule for f in found] == ["cheme.evidence-unit"]
    assert problem in found[0].message


def test_fractions_are_percent_or_one_and_inside_zero_to_one():
    data = _minimal()
    data["observations"][0]["conversion"][0]["value"] = {"value": 75, "unit": "1"}
    found = _rules(data)
    assert [f.rule for f in found] == ["cheme.evidence-unit"]
    assert "outside 0 to 1" in found[0].message
    data["observations"][0]["conversion"][0]["value"] = {"value": 0.75, "unit": "mol/mol"}
    assert "'mol/mol'" in _rules(data)[0].message


def test_conversion_selectivity_and_yield_stay_apart():
    data = _minimal()
    obs = data["observations"][0]
    obs["selectivity"] = [{"product": "P", "value": {"value": 90, "unit": "%"}}]
    obs["yield"] = [{"product": "P", "value": {"value": 40, "unit": "%"}, "relative_to": "A"}]
    found = _rules(data)
    messages = [f.message for f in found if f.rule == "cheme.evidence-yield-basis"]
    assert len(messages) == 2
    assert any("neither isolated nor analytical" in m for m in messages)
    assert any("selectivity to P relative to no reactant" in m for m in messages)
    assert not _ids(found, "yield-conversion")
    # a molar yield above the conversion of its reactant mixes up the bases
    obs["yield"][0] |= {"type": "analytical", "value": {"value": 0.8, "unit": "1"}}
    obs["selectivity"][0]["relative_to"] = "A"
    found = _rules(data)
    assert [f.rule for f in found] == ["cheme.evidence-yield-conversion"]
    # on a mass basis the comparison does not hold
    obs["yield"][0]["basis"] = "mass"
    assert _rules(data) == []


def test_duplicate_evidence():
    data = _minimal()
    data["observations"].append(
        copy.deepcopy(data["observations"][0]) | {"id": "O2", "location": "table 1"}
    )
    found = _rules(data)
    assert _ids(found, "duplicate") == [["O2", "O1"]]


def test_kinetics_need_a_basis_and_a_validity_range():
    data = _minimal()
    data["observations"][0]["kinetics"] = {
        "equation": "r = k cA",
        "parameters": {"Ea": {"value": 80, "unit": "kJ/mol"}},
    }
    found = _rules(data)
    assert [f.rule for f in found] == ["cheme.evidence-kinetics"]
    assert "rate basis and temperature range" in found[0].message
    data["observations"][0]["kinetics"] |= {
        "rate_basis": "per kg of catalyst",
        "temperature_range": {"range": [300, 350], "unit": "K"},
    }
    assert _rules(data) == []
    data["observations"][0]["kinetics"]["parameters"]["A"] = {"value": 1e6, "unit": ""}
    assert [f.rule for f in _rules(data)] == ["cheme.evidence-unit"]


def test_the_model_basis_is_explicit():
    data = _minimal()
    data["routes"][0]["status"] = "selected"
    found = _rules(data)
    assert [f.message for f in found] == ["route R1 is selected but there is no model_basis"]
    data["routes"].append({"id": "R2", "status": "selected"})
    assert len(_ids(_rules(data), "model-basis")) == 2
    data["routes"][1]["status"] = "candidate"
    data["model_basis"] = {"route": "R2", "reactions": ["X"], "evidence": []}
    messages = [f.message for f in _rules(data) if f.rule == "cheme.evidence-model-basis"]
    assert "model_basis uses route R2, which is candidate" in messages
    assert "model_basis names no evidence" in messages
    # the model's reactions must be in reactions.yaml (an error, even without the file)
    data["model_basis"] = {"route": "R1", "reactions": ["X"], "evidence": ["O1"]}
    assert _ids(_rules(data), "reaction") == [["X"]]
    assert _ids(_rules(data, Declared(reactions={})), "reaction") == [["X"]]


def test_evidence_is_not_pooled_across_catalysts_or_routes_silently():
    data = _minimal()
    data["routes"][0]["status"] = "selected"
    data["routes"].append({"id": "R2"})
    data["observations"][0]["conditions"] = {"catalyst_formulation": "5 % Pd/C"}
    data["observations"].append(
        {
            "id": "O2",
            "source": "S1",
            "route": "R2",
            "location": "Table 2",
            "kind": "experiment",
            "conditions": {"catalyst_formulation": "Raney Ni"},
        }
    )
    data["model_basis"] = {"route": "R1", "reactions": ["X"], "evidence": ["O1", "O2"]}
    declared = Declared(reactions={"X": None})  # type: ignore[dict-item]
    messages = [f.message for f in _rules(data, declared) if f.level == "warning"]
    assert "model_basis: observation O2 belongs to route R2, not R1" in messages
    assert any(
        m.startswith("model_basis pools observations on different catalysts") for m in messages
    )
    data["model_basis"]["assumptions"] = ["both are hydrogenation catalysts of similar activity"]
    messages = [f.message for f in _rules(data, declared)]
    assert not any("pools" in m for m in messages)


def test_ids_of_the_other_files():
    data = _minimal()
    data["routes"][0] |= {"reactions": ["R_X"], "catalysts": ["CAT"]}
    data["observations"][0]["conditions"] = {
        "catalyst": "CAT2",
        "feed": {"B": {"value": 1, "unit": "1"}},
    }
    # without the files nothing is checked (only a model basis needs reactions.yaml)
    assert _rules(data) == []
    declared = Declared(components={"A"}, reactions={}, catalysts={"CAT"})
    found = _rules(data, declared)
    assert sorted(_ids(found, "component")) == [["B"], ["P"]]
    assert _ids(found, "reaction") == [["R1", "R_X"]]
    assert _ids(found, "catalyst") == [["CAT2"]]
    assert all(f.level == "warning" for f in found)


# -- workspace and CLI --------------------------------------------------------------------------


def test_validate_reads_the_file_only_when_a_target_concerns_it(plant):
    path = plant / EVIDENCE_FILE
    path.write_text(
        path.read_text(encoding="utf-8").replace("location: Abstract", "location: ''"), "utf-8"
    )
    targets = {(plant / "plant.yaml").resolve()}
    assert evidence_findings(plant, targets) == ([], True)
    for target in (EVIDENCE_FILE, "process/materials.yaml"):
        found, _ = evidence_findings(plant, {(plant / target).resolve()})
        assert _ids(found, "location") == [["O-PET-ABS"]]
    report = validate_workspace(Workspace(plant))
    assert report.failed()


def test_a_plant_without_the_file_is_unchanged(plant):
    (plant / EVIDENCE_FILE).unlink()
    assert evidence_findings(plant) == ([], False)
    assert EVIDENCE_FILE not in validate_workspace(Workspace(plant)).files


def test_cli_prints_the_comparison_and_fails_on_errors(plant, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["chemistry", "evidence"])
    assert result.exit_code == 0, result.output
    assert result.output.startswith("product: EtOAc")
    assert "ESTER [selected]" in result.output
    assert "warning cheme.evidence-yield-basis" in result.output
    result = runner.invoke(app, ["chemistry", "evidence", "--json"])
    document = json.loads(result.stdout)
    assert [r["id"] for r in document["routes"]] == ["ESTER", "DEHYD", "ADD"]
    assert document["model_basis"]["route"] == "ESTER"
    assert {f["rule"] for f in document["findings"]} == {"cheme.evidence-yield-basis"}
    path = plant / EVIDENCE_FILE
    path.write_text(path.read_text(encoding="utf-8").replace("unit: K}", "unit: F}", 1), "utf-8")
    result = runner.invoke(app, ["chemistry", "evidence"])
    assert result.exit_code == 1
    assert "error cheme.evidence-unit" in result.output
    path.unlink()
    result = runner.invoke(app, ["chemistry", "evidence"])
    assert result.exit_code == 2
    assert "skill reaction-evidence-search" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)


def test_schema_command_exports_the_evidence_schema(plant, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["schema", "reaction-evidence"])
    assert result.exit_code == 0, result.output
    assert "model_basis" in json.loads(result.stdout)["properties"]


def test_the_rules_need_neither_typer_nor_the_process_model():
    code = (
        "import sys; import chemeascode.domains.chemistry.evidence; "
        "assert 'typer' not in sys.modules; "
        "assert 'chemeascode.domains.process.model' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_every_finding_has_its_own_id():
    """Accepting one finding in checks.yaml never accepts another."""
    data = _minimal()
    data["routes"] += [{"id": "R2", "status": "selected"}, {"id": "R3", "status": "selected"}]
    obs = data["observations"][0]
    obs["conditions"] = {
        "temperature": {"value": 1, "unit": "F"},
        "pressure": {"value": 1, "unit": "bar"},
    }
    obs["selectivity"] = [{"product": "P", "value": {"value": 9, "unit": "%"}}] * 2
    obs["yield"] = [{"product": "P", "value": {"value": 9, "unit": "%"}}] * 2
    data["observations"] += [
        {"id": f"O{n}", "source": "S9", "route": "R9", "location": f"p. {n}", "kind": "experiment"}
        for n in (2, 3)
    ]
    data["model_basis"] = {"route": "R2", "reactions": ["X", "Y"], "evidence": ["O2", "O3"]}
    found = _rules(data, Declared(components=set(), reactions={}, catalysts=set()))
    assert len(found) > 15
    assert len({f.id for f in found}) == len(found), sorted(f.id for f in found)


@pytest.mark.parametrize(
    "number, ok",
    [
        ("US7652167B2", True),
        ("EP0757027A1", True),
        ("USRE45678E", True),
        ("JPH0812345A", True),
        ("JP2000-123456A", True),
        ("US7652167", True),
        ("WO2000020375A1", True),
        ("US 7,652,167", False),
        ("7652167", False),
    ],
)
def test_patent_numbers(number, ok):
    data = _minimal()
    data["sources"][0] = {
        "id": "S1",
        "kind": "patent",
        "patent": number,
        "accessed": "2026-01-02",
        "access": "full-text",
    }
    assert (_ids(_rules(data), "identity") == []) is ok


def test_a_broken_reactions_file_is_not_a_missing_reaction(plant):
    path = plant / "process/reactions.yaml"
    path.write_text(
        path.read_text(encoding="utf-8").replace("    phase: liquid", "    phse: liquid"), "utf-8"
    )
    found, _ = evidence_findings(plant)
    assert not _ids(found, "reaction")
    path.unlink()
    found, _ = evidence_findings(plant)
    assert _ids(found, "reaction") == [["ESTERIF"]]


def test_a_file_that_is_not_utf8_does_not_stop_the_checks(plant):
    (plant / "process/materials.yaml").write_bytes(
        "components: [{id: X, name: 'T \xb0'}]\n".encode("latin-1")
    )
    evidence_findings(plant)  # materials unreadable: components not checked
    (plant / EVIDENCE_FILE).write_bytes(b"schema: x\nproduct: '\xb0'\n")
    found, _ = evidence_findings(plant)
    assert [f.rule for f in found] == ["yaml.syntax"]


def test_the_handoff_line_counts_duplicated_ids(plant):
    path = plant / "process/reactions.yaml"
    text = path.read_text(encoding="utf-8").replace(
        "reaction-evidence O-KIR-CONV (S-KIR p. 574)", "a handbook"
    )
    head, entry = text.split("reactions:\n", 1)
    other = entry.replace("id: ESTERIF", "id: OTHER")
    # a duplicated id before it: ESTERIF is the third entry, the second distinct id
    written = head + "reactions:\n" + other + other + entry
    path.write_text(written, "utf-8")
    lines = written.splitlines()
    first = lines.index("  - id: ESTERIF") + 1
    conversion = next(n for n in range(first, len(lines) + 1) if "conversion:" in lines[n - 1])
    expected = conversion + 1  # the line of the conversion's mapping
    found, _ = evidence_findings(plant)
    handoff = [f for f in found if f.rule == "cheme.evidence-handoff"]
    assert [f.line for f in handoff] == [expected]


def test_model_evidence_on_another_catalyst_is_flagged():
    data = _minimal()
    data["routes"][0]["status"] = "selected"
    data["observations"][0]["conditions"] = {"catalyst": "CAT_B"}
    data["model_basis"] = {
        "route": "R1",
        "reactions": ["X"],
        "catalyst": "CAT_A",
        "evidence": ["O1"],
    }
    found = _rules(data, Declared(reactions={"X": None}))  # type: ignore[dict-item]
    assert [f.message for f in found] == [
        "model_basis: catalyst CAT_A, but observation O1 is on CAT_B"
    ]


def test_cli_shows_accepted_warnings_as_validate_does(plant, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "checks").mkdir(exist_ok=True)
    (plant / "checks/checks.yaml").write_text(
        "accept:\n"
        "  - id: 'process/reaction-evidence.yaml#evidence-yield-basis:O-BP-1+*'\n"
        "    reason: the patent does not define its yield; recorded in missing\n",
        "utf-8",
    )
    result = runner.invoke(app, ["chemistry", "evidence", "--json"])
    assert result.exit_code == 0, result.output
    levels = {(f["ids"][0], f["level"]) for f in json.loads(result.stdout)["findings"]}
    assert levels == {("O-BP-1", "info"), ("O-BP-4", "warning")}
