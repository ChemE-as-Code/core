"""cheme maturity: a conversion reactor's specified conversion or selectivity counts as sourced
when the decided model basis of process/reaction-evidence.yaml covers it with read observations,
and not when the value is outside them, the source was not read or the file
flags a conflict.

Every number in the evidence fixtures below is FIXTURE DATA made up for the test: the sources,
DOIs, tables and values are not real literature and must not be read as such.
"""

import json
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.chemistry import evidence as ev
from chemeascode.domains.process.model import load
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.project.maturity import maturity_report

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05}
  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05}
templates:
  - {id: mix, components: [A, B, C]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: R1
    stoichiometry: {A: -1, B: 1}
    conversion: {key: A, value: 0.8, provenance: assumed}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1]
    reactor: conversion
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: mix
    state:
      design:
        flow: {value: 100, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: mix
    state:
      design:
        temperature: {value: 500, provenance: given}
"""

#: FIXTURE DATA, not literature: S1 read in full, S2 only seen as a search snippet.
EVIDENCE = {
    "schema": "cheme/reaction-evidence/v1",
    "kind": "reaction-evidence",
    "product": "B",
    "sources": [
        {
            "id": "S1",
            "kind": "paper",
            "title": "Fixture paper (not a real source)",
            "doi": "10.0000/fixture.1",
            "accessed": "2026-01-01",
            "access": "full-text",
        },
        {
            "id": "S2",
            "kind": "paper",
            "title": "Fixture snippet (not a real source)",
            "doi": "10.0000/fixture.2",
            "accessed": "2026-01-01",
            "access": "snippet",
        },
    ],
    "routes": [{"id": "RT1", "status": "selected", "reactions": ["R1"]}],
    "observations": [
        {
            "id": "O1",
            "source": "S1",
            "route": "RT1",
            "location": "Table 1 (fixture)",
            "kind": "experiment",
            "conditions": {
                "temperature": {"range": [480, 520], "unit": "K"},
                "catalyst_formulation": "fixture catalyst X",
            },
            "conversion": [
                {"component": "A", "value": {"range": [75, 85], "unit": "%"}, "basis": "per-pass"}
            ],
            "selectivity": [
                {
                    "product": "B",
                    "relative_to": "A",
                    "value": {"value": 0.9, "unit": "1", "uncertainty": 0.02},
                    "basis": "molar",
                }
            ],
        },
        {
            "id": "O2",
            "source": "S2",
            "route": "RT1",
            "location": "search result (fixture)",
            "kind": "experiment",
            "conditions": {
                "temperature": {"value": 500, "unit": "K"},
                "catalyst_formulation": "fixture catalyst X",
            },
            "conversion": [
                {"component": "A", "value": {"value": 80, "unit": "%"}, "basis": "per-pass"}
            ],
        },
        {
            "id": "O3",
            "source": "S1",
            "route": "RT1",
            "location": "Table 2 (fixture)",
            "kind": "experiment",
            "conditions": {
                "temperature": {"value": 500, "unit": "K"},
                "catalyst_formulation": "fixture catalyst X",
            },
            "conversion": [
                {"component": "A", "value": {"value": 50, "unit": "%"}, "basis": "per-pass"}
            ],
        },
    ],
    "model_basis": {"route": "RT1", "reactions": ["R1"], "evidence": ["O1"]},
}


def _plant(tmp_path: Path, evidence=EVIDENCE, flowsheet=FLOWSHEET, reactions=REACTIONS) -> Path:
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: evidence-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(reactions)
    if evidence is not None:
        (root / ev.EVIDENCE_FILE).write_text(yaml.safe_dump(evidence, sort_keys=False))
    return root


def _reactor(root: Path):
    process, _ = load(root)
    evidence, _, found = ev.load(root)
    assert not found, [f.format() for f in found]
    return next(u for u in model_bases(process, evidence=evidence) if u.id == "R")


def _reactor_unchecked(root: Path):
    """As _reactor, for evidence the schema accepts but the rules would flag."""
    process, _ = load(root)
    evidence, _, _ = ev.load(root)
    return next(u for u in model_bases(process, evidence=evidence) if u.id == "R")


def _with(**changes) -> dict:
    data = yaml.safe_load(yaml.safe_dump(EVIDENCE))
    for key, value in changes.items():
        data[key] = value
    return data


def test_without_evidence_an_assumed_conversion_stays_unsourced(tmp_path):
    unit = _reactor(_plant(tmp_path, evidence=None))
    assert (unit.basis, unit.sourced, unit.evidence) == ("conversion", False, [])


def test_a_covered_conversion_counts_as_sourced_and_names_its_observation(tmp_path):
    root = _plant(tmp_path)
    unit = _reactor(root)
    assert (unit.basis, unit.predictive, unit.sourced) == ("conversion", False, True)
    [support] = unit.evidence
    assert support["supported"] and support["observations"] == ["O1 (S1, Table 1 (fixture))"]
    assert support["observed"] == [0.75, 0.85] and support["temperature_K"] == [480, 520]
    assert "sourced by reaction evidence: conversion of A 0.8 within the observed" in unit.detail
    assert f"{ev.EVIDENCE_FILE}: O1 (S1, Table 1 (fixture))" in unit.sources
    # the maturity requirement passes and reports the support
    report = maturity_report(root)
    req = next(r for r in report.requirements if r.id == "balanced.model-basis")
    assert req.status == "pass", req.detail
    assert req.evidence["reaction_evidence"]["R"][0]["sources"] == ["S1"]


def test_a_value_outside_the_observed_range_is_not_sourced(tmp_path):
    root = _plant(tmp_path, reactions=REACTIONS.replace("value: 0.8", "value: 0.9"))
    unit = _reactor(root)
    assert not unit.sourced
    assert (
        "0.9 outside the observed range 0.75-0.85 at the outlet temperature/pressure (O1;"
        in unit.detail
    )
    assert any("not supported by" in text for text in unit.limitations)
    report = maturity_report(root)
    req = next(r for r in report.requirements if r.id == "balanced.model-basis")
    assert req.status == "fail" and "outside the observed" in req.detail


def test_an_operating_temperature_outside_the_observations_is_not_sourced(tmp_path):
    unit = _reactor(_plant(tmp_path, flowsheet=FLOWSHEET.replace("value: 500", "value: 600")))
    assert not unit.sourced
    assert "O1 left out: at 480-520 K, not the operating temperature" in unit.detail


def test_an_unread_source_does_not_source_a_conversion(tmp_path):
    basis = {"route": "RT1", "reactions": ["R1"], "evidence": ["O2"]}
    unit = _reactor(_plant(tmp_path, evidence=_with(model_basis=basis)))
    assert not unit.sourced
    assert "O2 left out: source S2 not read in full (snippet)" in unit.detail
    # with a read observation beside it, the unread one is left out and noted
    basis = {"route": "RT1", "reactions": ["R1"], "evidence": ["O1", "O2"]}
    unit = _reactor(_plant(tmp_path / "b", evidence=_with(model_basis=basis)))
    assert unit.sourced
    assert unit.evidence[0]["observations"] == ["O1 (S1, Table 1 (fixture))"]
    assert "conversion of A: O2 left out: source S2 not read in full (snippet)" in (
        unit.limitations
    )


def test_a_flagged_conflict_does_not_source_a_conversion(tmp_path):
    basis = {"route": "RT1", "reactions": ["R1"], "evidence": ["O1", "O3"]}
    conflicts = [
        {"about": "conversion of A", "observations": ["O1", "O3"], "resolution": "fixture"}
    ]
    unit = _reactor(_plant(tmp_path, evidence=_with(model_basis=basis, conflicts=conflicts)))
    assert not unit.sourced
    assert "conflict 'conversion of A' on O1, O3 (resolution: fixture)" in unit.detail


def test_a_route_that_is_not_selected_does_not_source_a_conversion(tmp_path):
    routes = [{"id": "RT1", "status": "candidate", "reactions": ["R1"]}]
    unit = _reactor(_plant(tmp_path, evidence=_with(routes=routes)))
    assert not unit.sourced
    assert "route RT1 is candidate, not selected" in unit.detail


def test_a_sourced_conversion_the_evidence_contradicts_is_not_sourced(tmp_path):
    reactions = REACTIONS.replace(
        "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
    ).replace("value: 0.8", "value: 0.95")
    unit = _reactor(_plant(tmp_path, reactions=reactions))
    assert not unit.sourced
    assert "R1 (conversion given) conversion of A: contradicted by" in unit.detail
    assert any(
        t.startswith("contradicted by the evidence: conversion of A 0.95") for t in unit.limitations
    )


def test_a_sourced_conversion_the_evidence_cannot_compare_keeps_its_source(tmp_path):
    # the outlet temperature is unknown: not a contradiction, the own source stands
    reactions = REACTIONS.replace(
        "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
    )
    flowsheet = FLOWSHEET.replace(
        "    state:\n      design:\n        temperature: {value: 500, provenance: given}\n", ""
    )
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet, reactions=reactions))
    assert unit.sourced
    assert any(
        t.startswith("own source kept, not supported by the evidence: conversion of A 0.8")
        and "operating temperature unknown" in t
        for t in unit.limitations
    )
    assert not any(t.startswith("contradicted") for t in unit.limitations)


def test_a_selectivity_reactor_is_sourced_by_conversion_and_selectivity(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "    reactor: conversion\n",
        "    reactor: conversion\n"
        "    selectivity: {key: A, conversion: 0.8, products: {B: 0.91}, provenance: assumed}\n",
    )
    reactions = REACTIONS.replace("    conversion: {key: A, value: 0.8, provenance: assumed}\n", "")
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet, reactions=reactions))
    assert unit.sourced, unit.detail
    assert [(s["quantity"], s["supported"]) for s in unit.evidence] == [
        ("conversion", True),
        ("selectivity", True),
    ]
    # a selectivity outside the observed 0.88-0.92 is not
    flowsheet = flowsheet.replace("B: 0.91", "B: 0.97")
    unit = _reactor(_plant(tmp_path / "b", flowsheet=flowsheet, reactions=reactions))
    assert not unit.sourced
    assert "selectivity to B (of A) 0.97 not supported" in " ".join(unit.limitations)


def test_reactions_sharing_a_key_are_not_compared_with_a_total_conversion(tmp_path):
    reactions = REACTIONS + (
        "  - id: R2\n    stoichiometry: {A: -1, C: 1}\n"
        "    conversion: {key: A, value: 0.05, provenance: assumed}\n"
    )
    flowsheet = FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, R2]")
    basis = {"route": "RT1", "reactions": ["R1", "R2"], "evidence": ["O1"]}
    root = _plant(
        tmp_path, evidence=_with(model_basis=basis), flowsheet=flowsheet, reactions=reactions
    )
    unit = _reactor(root)
    assert not unit.sourced
    assert "reactions R1, R2 consume A" in unit.detail


SELECTIVE = FLOWSHEET.replace(
    "    reactor: conversion\n",
    "    reactor: conversion\n"
    "    selectivity: {key: A, conversion: 0.8, products: {B: 0.91}, provenance: assumed}\n",
)
NO_CONVERSION = REACTIONS.replace("    conversion: {key: A, value: 0.8, provenance: assumed}\n", "")


def _observations(index: int, **changes) -> list:
    found = yaml.safe_load(yaml.safe_dump(EVIDENCE["observations"]))
    found[index].update(changes)
    return found


def test_a_selectivity_is_judged_on_its_own_spec_not_the_reactions_conversions(tmp_path):
    given = REACTIONS.replace(
        "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
    )
    # an assumed selectivity is not sourced by the reaction's (unused) given conversion
    unit = _reactor(_plant(tmp_path, None, SELECTIVE, given))
    assert not unit.sourced
    assert "selectivity (assumed)" in unit.detail
    # a given selectivity with a source is sourced on its own, without evidence
    sourced = SELECTIVE.replace(
        "B: 0.91}, provenance: assumed", 'B: 0.91}, provenance: given, source: "fixture"'
    )
    unit = _reactor(_plant(tmp_path / "b", None, sourced, NO_CONVERSION))
    assert unit.sourced and unit.sources == ["fixture"]


def test_an_own_source_selectivity_the_evidence_contradicts_is_not_sourced(tmp_path):
    flowsheet = SELECTIVE.replace(
        "B: 0.91}, provenance: assumed", 'B: 0.97}, provenance: given, source: "fixture"'
    )
    given = REACTIONS.replace(
        "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
    )
    # also when the reaction carries a given conversion the selectivity overrides
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet, reactions=given))
    assert not unit.sourced
    assert "0.97 outside the observed" in unit.detail
    assert "contradicted by" in unit.detail


def test_a_selectivity_is_compared_as_a_fraction_of_the_stoichiometric_ratio(tmp_path):
    # A -> 2 B: 1.8 kmol B per kmol A converted is the molar selectivity 0.9
    reactions = NO_CONVERSION.replace("{A: -1, B: 1}", "{A: -1, B: 2}")
    flowsheet = SELECTIVE.replace("B: 0.91", "B: 1.8")
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet, reactions=reactions))
    assert unit.sourced, unit.detail
    selectivity = unit.evidence[1]
    assert selectivity["value"] == 0.9 and selectivity["supported"]
    assert any("is the fraction 0.9 (2 B per A" in n for n in selectivity["notes"])
    # B formed from A in two ratios: not compared
    reactions += "  - {id: R2, stoichiometry: {A: -1, B: 1}}\n"
    flowsheet = flowsheet.replace("reactions: [R1]", "reactions: [R1, R2]")
    basis = {"route": "RT1", "reactions": ["R1", "R2"], "evidence": ["O1"]}
    root = _plant(tmp_path / "b", _with(model_basis=basis), flowsheet, reactions)
    unit = _reactor(root)
    assert not unit.sourced
    assert "form B from A in different ratios (1, 2)" in unit.detail


def test_unlabelled_observations_do_not_support(tmp_path):
    o1 = EVIDENCE["observations"][0]
    conversion = [{"component": "A", "value": {"range": [75, 85], "unit": "%"}}]
    unit = _reactor(_plant(tmp_path, _with(observations=_observations(0, conversion=conversion))))
    assert not unit.sourced
    assert "O1 left out: basis not stated (per-pass, overall or equilibrium)" in unit.detail
    selectivity = [dict(o1["selectivity"][0], relative_to="")]
    evidence = _with(observations=_observations(0, selectivity=selectivity))
    unit = _reactor(_plant(tmp_path / "b", evidence, SELECTIVE, NO_CONVERSION))
    assert not unit.sourced
    assert "O1 left out: relative_to not stated (the key is A)" in unit.detail


def test_an_observation_with_an_error_finding_does_not_support(tmp_path):
    # cheme.evidence-location: reported values without the table they are on
    root = _plant(tmp_path, _with(observations=_observations(0, location="")))
    report = maturity_report(root)
    unit = next(u for u in report.model_basis if u["id"] == "R")
    assert not unit["sourced"]
    assert "O1 left out: error finding(s): cheme.evidence-location" in unit["detail"]
    req = next(r for r in report.requirements if r.id == "balanced.model-basis")
    assert req.status == "fail"
    rules = {f["rule"] for f in req.evidence["reaction_evidence_errors"]}
    assert "cheme.evidence-location" in rules


def test_the_value_must_be_covered_at_the_operating_point(tmp_path):
    # O1 at 400 K reports 80 %, O3 at the reactor's 500 K reports 50 %: 0.8 is not supported
    conditions = {
        "temperature": {"value": 400, "unit": "K"},
        "catalyst_formulation": "fixture catalyst X",
    }
    conversion = [{"component": "A", "value": {"value": 80, "unit": "%"}, "basis": "per-pass"}]
    observations = _observations(0, conditions=conditions, conversion=conversion)
    basis = {"route": "RT1", "reactions": ["R1"], "evidence": ["O1", "O3"]}
    unit = _reactor(_plant(tmp_path, _with(observations=observations, model_basis=basis)))
    assert not unit.sourced
    assert "O1 left out: at 400-400 K, not the operating temperature" in " ".join(unit.limitations)
    assert (
        "0.8 outside the observed range 0.5-0.5 at the outlet temperature/pressure (O3;"
        in unit.detail
    )


def test_unknown_operating_conditions_are_not_sourced(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "    state:\n      design:\n        temperature: {value: 500, provenance: given}\n", ""
    )
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet))
    assert not unit.sourced
    assert "operating temperature unknown" in unit.detail
    assert "conversion of A: operating pressure unknown: pressure not compared" in (
        unit.limitations
    )


def test_a_selectivity_step_without_reactor_is_a_conversion_basis(tmp_path):
    flowsheet = SELECTIVE.replace("    reactor: conversion\n", "")
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet, reactions=NO_CONVERSION))
    assert (unit.basis, unit.sourced) == ("conversion", True), unit.detail


def test_errors_on_the_source_or_the_model_basis_block_support(tmp_path):
    # a malformed DOI on S1 blocks every observation citing it
    sources = yaml.safe_load(yaml.safe_dump(EVIDENCE["sources"]))
    sources[0]["doi"] = "not-a-doi"
    report = maturity_report(_plant(tmp_path, _with(sources=sources)))
    unit = next(u for u in report.model_basis if u["id"] == "R")
    assert not unit["sourced"]
    assert "O1 left out: error finding(s): cheme.evidence-identity" in unit["detail"]
    # two routes selected: the decision is not made, nothing is supported
    routes = [
        {"id": "RT1", "status": "selected", "reactions": ["R1"]},
        {"id": "RT2", "status": "selected"},
    ]
    report = maturity_report(_plant(tmp_path / "b", _with(routes=routes)))
    unit = next(u for u in report.model_basis if u["id"] == "R")
    assert not unit["sourced"]
    assert "model basis: cheme.evidence-model-basis: route RT2 is selected" in unit["detail"]


def test_a_duplicated_source_id_is_refused(tmp_path):
    sources = yaml.safe_load(yaml.safe_dump(EVIDENCE["sources"]))
    sources.append(dict(sources[0]))
    unit = _reactor_unchecked(_plant(tmp_path, _with(sources=sources)))
    assert not unit.sourced
    assert "O1 left out: source id S1 is declared 2 times" in unit.detail


def test_observations_on_another_catalyst_or_pooled_across_catalysts(tmp_path):
    conditions = {
        "temperature": {"range": [480, 520], "unit": "K"},
        "catalyst_formulation": "fixture catalyst X",
    }
    observations = _observations(0, conditions=conditions)
    basis = dict(EVIDENCE["model_basis"], catalyst="CAT1")
    # the basis names CAT1; O1 is on CAT2
    conditions_cat2 = dict(conditions, catalyst="CAT2")
    unit = _reactor_unchecked(
        _plant(
            tmp_path,
            _with(observations=_observations(0, conditions=conditions_cat2), model_basis=basis),
        )
    )
    assert not unit.sourced
    assert "O1 left out: on catalyst CAT2, not the model basis's CAT1" in unit.detail
    # no catalyst named: O1 (X, 75-85 %) and O4 (Y, 60 %) are not pooled to cover 0.7
    o4 = dict(
        observations[0],
        id="O4",
        location="Table 4 (fixture)",
        conditions=dict(conditions, catalyst_formulation="fixture catalyst Y"),
        conversion=[{"component": "A", "value": {"value": 60, "unit": "%"}, "basis": "per-pass"}],
    )
    observations.append(o4)
    evidence = _with(
        observations=observations,
        model_basis={"route": "RT1", "reactions": ["R1"], "evidence": ["O1", "O4"]},
    )
    reactions = REACTIONS.replace("value: 0.8", "value: 0.7")
    unit = _reactor_unchecked(_plant(tmp_path / "b", evidence, reactions=reactions))
    assert not unit.sourced
    assert "no single catalyst's observations cover it" in unit.detail
    assert any("not pooled across catalysts" in t for t in unit.limitations)
    # one catalyst's observations cover 0.8: supported, naming that catalyst
    unit = _reactor_unchecked(_plant(tmp_path / "c", evidence))
    assert unit.sourced
    assert unit.evidence[0]["catalyst"] == "fixture catalyst X"


def test_a_reactant_consumed_by_another_reaction_under_another_key(tmp_path):
    # R2 consumes A too, but its conversion is keyed to D
    materials = MATERIALS.replace(
        "  - {id: C, name: C",
        "  - {id: D, name: D, formula: C2H4O, molar_mass: 44.05}\n  - {id: C, name: C",
    )
    reactions = REACTIONS + (
        "  - id: R2\n    stoichiometry: {A: -1, D: -1, C: 1}\n"
        "    conversion: {key: D, value: 0.05, provenance: assumed}\n"
    )
    flowsheet = FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, R2]")
    basis = {"route": "RT1", "reactions": ["R1", "R2"], "evidence": ["O1"]}
    root = _plant(tmp_path, _with(model_basis=basis), flowsheet, reactions)
    (root / "process/materials.yaml").write_text(materials)
    unit = _reactor(root)
    assert not unit.sourced
    assert "reactions R1, R2 consume A" in unit.detail


def test_a_case_without_an_outlet_temperature_is_not_sourced(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "kind: flowsheet\n", "kind: flowsheet\ncases: [{id: design}, {id: turndown}]\n"
    )
    unit = _reactor(_plant(tmp_path, flowsheet=flowsheet))
    assert not unit.sourced
    assert "operating temperature unknown in case turndown" in unit.detail


OWN_06 = REACTIONS.replace(
    "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
).replace("value: 0.8", "value: 0.6")
NO_T = FLOWSHEET.replace(
    "    state:\n      design:\n        temperature: {value: 500, provenance: given}\n", ""
)


@pytest.mark.parametrize("case", ["route rejected", "conflict", "no temperature"])
def test_a_value_outside_the_range_is_not_contradicted_when_nothing_was_comparable(tmp_path, case):
    evidence, flowsheet = EVIDENCE, FLOWSHEET
    if case == "route rejected":
        evidence = _with(routes=[{"id": "RT1", "status": "rejected", "reactions": ["R1"]}])
    elif case == "conflict":
        evidence = _with(
            model_basis={"route": "RT1", "reactions": ["R1"], "evidence": ["O1", "O3"]},
            conflicts=[{"about": "conversion of A", "observations": ["O1", "O3"]}],
        )
    else:
        flowsheet = NO_T
    unit = _reactor_unchecked(_plant(tmp_path, evidence, flowsheet, OWN_06))
    assert unit.sourced, unit.detail
    assert not unit.evidence[0]["contradicted"]
    assert any(
        t.startswith("own source kept, not supported by the evidence: conversion of A 0.6")
        for t in unit.limitations
    )
    assert not any(t.startswith("contradicted") for t in unit.limitations)


CATALYSTS = """\
schema: cheme/catalysts/v1
kind: catalysts
catalysts:
  - {id: CAT1, name: fixture catalyst X, active_phase: fixture}
"""


def test_a_catalyst_given_only_as_a_formulation_is_compared_with_the_basis(tmp_path):
    basis = dict(EVIDENCE["model_basis"], catalyst="CAT1")
    # O1 says "fixture catalyst X" only: unless catalysts.yaml names CAT1 so, it is not CAT1
    unit = _reactor_unchecked(_plant(tmp_path, _with(model_basis=basis)))
    assert not unit.sourced
    assert "O1 left out: on catalyst fixture catalyst X, not the model basis's CAT1" in (
        unit.detail
    )
    root = _plant(tmp_path / "b", _with(model_basis=basis))
    (root / "process/catalysts.yaml").write_text(CATALYSTS)
    unit = _reactor_unchecked(root)
    assert unit.sourced, unit.detail
    assert unit.evidence[0]["catalyst"] == "CAT1"


def test_an_observation_without_a_catalyst_is_not_usable(tmp_path):
    conditions = {"temperature": {"range": [480, 520], "unit": "K"}}
    unit = _reactor(_plant(tmp_path, _with(observations=_observations(0, conditions=conditions))))
    assert not unit.sourced
    assert "O1 left out: catalyst not stated (catalyst or catalyst_formulation)" in unit.detail


def test_a_supported_value_lists_the_conditions_not_compared(tmp_path):
    unit = _reactor(_plant(tmp_path))
    assert unit.sourced
    assert any(
        t.startswith("conversion of A: not compared: residence or contact time, space velocity")
        for t in unit.limitations
    )


def test_a_contradicted_value_lists_the_conditions_not_compared(tmp_path):
    reactions = REACTIONS.replace(
        "provenance: assumed}", 'provenance: given, source: "fixture handbook"}'
    ).replace("value: 0.8", "value: 0.95")
    unit = _reactor(_plant(tmp_path, reactions=reactions))
    [support] = unit.evidence
    assert support["contradicted"]
    assert any(n.startswith("not compared: residence or contact time") for n in support["notes"])
    assert "other conditions not compared" in support["reasons"][0]


def test_the_reactor_catalyst_must_be_the_evidence_catalyst(tmp_path):
    catalysts = CATALYSTS + "  - {id: CAT2, name: fixture catalyst Z, active_phase: fixture}\n"
    on_cat2 = FLOWSHEET.replace(
        "    reactor: conversion\n", "    reactor: conversion\n    catalyst: CAT2\n"
    )
    basis = dict(EVIDENCE["model_basis"], catalyst="CAT1")
    root = _plant(tmp_path, _with(model_basis=basis), on_cat2)
    (root / "process/catalysts.yaml").write_text(catalysts)
    unit = _reactor_unchecked(root)
    assert not unit.sourced
    assert "evidence on CAT1, reactor holds CAT2" in unit.detail
    # the basis names none: the observations must be on the reactor's catalyst (O1 is on X)
    root = _plant(tmp_path / "b", EVIDENCE, on_cat2)
    (root / "process/catalysts.yaml").write_text(catalysts)
    unit = _reactor_unchecked(root)
    assert not unit.sourced
    assert "O1 left out: on catalyst fixture catalyst X, not the reactor's CAT2" in unit.detail
    # the reactor on CAT1 ("fixture catalyst X" by name): supported
    on_cat1 = on_cat2.replace("catalyst: CAT2", "catalyst: CAT1")
    root = _plant(tmp_path / "c", EVIDENCE, on_cat1)
    (root / "process/catalysts.yaml").write_text(catalysts)
    assert _reactor_unchecked(root).sourced


def test_the_evidence_file_is_a_fingerprinted_input(tmp_path):
    root = _plant(tmp_path)
    before = maturity_report(root).as_dict()["source"]
    path = root / ev.EVIDENCE_FILE
    path.write_text(path.read_text() + "# edited\n")
    after = maturity_report(root).as_dict()["source"]
    assert before != after
    assert ev.EVIDENCE_FILE in json.dumps(after)
