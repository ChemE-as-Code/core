"""``cheme process extract``: liquid-liquid extraction stages on NRTL.

The benchmark compares the bundled system water + 1-propanol + n-butyl acetate (NRTL parameters
of Hajjar and Enders, Fluid Phase Equilib. 582 (2024) 114104) with the tie lines Costa et al.
measured at 323.15 K (J. Chem. Eng. Data 54 (2009) 2845, read from its NIST ThermoML file).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.separations import extraction, lle
from chemeascode.interfaces.cli import app

pytest.importorskip("thermo")

runner = CliRunner()
SYSTEM = "water-1-propanol-butyl-acetate"

#: Costa et al. 2009, 323.15 K, mole fractions (water, 1-propanol, n-butyl acetate); ThermoML
#: data set 27 of https://trc.nist.gov/ThermoML/10.1021/je900337a.xml (n-butyl acetate by
#: difference). The binary edge (no 1-propanol) is checked separately.
COSTA_TIE_LINES = [
    # (aqueous phase, organic phase)
    ((0.9842, 0.0154), (0.2009, 0.1664)),
    ((0.9757, 0.0238), (0.2769, 0.2593)),
    ((0.9643, 0.0349), (0.4117, 0.3279)),
    ((0.9580, 0.0410), (0.4889, 0.3363)),
]
COSTA_BINARY = ((0.9998, 0.0), (0.1305, 0.0))


def _composition(water: float, propanol: float) -> np.ndarray:
    return np.array([water, propanol, 1.0 - water - propanol])


def _model(temperature: float = 323.15):
    from chemeascode.integrations.thermo import nrtl_ln_gammas

    system = extraction.bundled_systems()[SYSTEM]
    return nrtl_ln_gammas(temperature, **system.matrices())


def _tie_line(model, aqueous: np.ndarray, organic: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The model's tie line through the midpoint of a measured one (aqueous, organic)."""
    eq = lle.split(model, (aqueous + organic) / 2)
    assert eq.liquids == 2 and eq.converged
    x1, x2 = np.asarray(eq.x1), np.asarray(eq.x2)
    return (x1, x2) if x1[0] > x2[0] else (x2, x1)


def test_the_bundled_system_reproduces_the_measured_tie_lines():
    """The qualification of the bundled system: phase compositions, the 1-propanol distribution
    coefficient and the selectivity, and the solvent in the aqueous phase, against Costa et al.
    within the tolerances data/lle-systems.yaml records (and its recorded observed values)."""
    system = extraction.bundled_systems()[SYSTEM]
    q = system.qualification
    assert q is not None and q.test == f"tests/test_extraction.py::{_name()}"
    model = _model(q.temperature_K[0])
    worst = dict.fromkeys(q.tolerances, 0.0)
    for (wa, pa), (wo, po) in COSTA_TIE_LINES:
        aqueous, organic = _composition(wa, pa), _composition(wo, po)
        aq, org = _tie_line(model, aqueous, organic)
        d_calc, d_exp = org[1] / aq[1], organic[1] / aqueous[1]
        s_calc = d_calc / (org[0] / aq[0])
        s_exp = d_exp / (organic[0] / aqueous[0])
        figures = {
            "composition_abs": max(np.abs(aq - aqueous).max(), np.abs(org - organic).max()),
            "distribution_rel": abs(d_calc / d_exp - 1.0),
            "selectivity_rel": abs(s_calc / s_exp - 1.0),
            "solvent_in_raffinate_abs": abs(aq[2] - aqueous[2]),
        }
        for key, value in figures.items():
            worst[key] = max(worst[key], float(value))
    for key, tolerance in q.tolerances.items():
        assert worst[key] <= tolerance, (key, worst[key])
        assert worst[key] == pytest.approx(q.observed[key], abs=1e-3), key
    # the range the qualification claims is the one the tie lines span
    assert q.solute_min == {"raffinate": 0.0154, "extract": 0.1664}
    assert q.solute_max == {"raffinate": 0.041, "extract": 0.3363}


def _name() -> str:
    return "test_the_bundled_system_reproduces_the_measured_tie_lines"


def test_the_binary_edge_deviation_is_the_recorded_one():
    """Without 1-propanol the model under-predicts water in the ester phase (0.076 against
    0.1305 measured): the deviation the system's notes record, outside the qualified range."""
    aq, org = _tie_line(_model(), _composition(*COSTA_BINARY[0]), _composition(*COSTA_BINARY[1]))
    assert aq[0] == pytest.approx(0.9998, abs=0.002)
    assert org[0] == pytest.approx(0.076, abs=0.002)
    notes = " ".join(extraction.bundled_systems()[SYSTEM].qualification.notes)
    assert "0.076" in notes and "0.1305" in notes


# -- plant files ----------------------------------------------------------------------------------


def _unit(**changes) -> dict:
    unit = {
        "id": "X-101",
        "represents": "B-3",
        "system": SYSTEM,
        "stages": 1,
        "temperature": {"value": 50, "unit": "°C", "provenance": "given"},
        "carrier": "water",
        "solute": "1-propanol",
        "solvent": "n-butyl acetate",
        "feed": {
            "flow": {"value": 1000, "unit": "kg/h", "provenance": "given"},
            "composition": {
                "basis": "mass_fraction",
                "values": {"water": 0.8, "1-propanol": 0.2},
                "provenance": "given",
            },
        },
        "solvent_feed": {
            "flow": {"value": 400, "unit": "kg/h", "provenance": "given"},
            "composition": {
                "basis": "mass_fraction",
                "values": {"n-butyl acetate": 1.0},
                "provenance": "given",
            },
        },
    }
    for key, value in changes.items():
        if key == "solvent_flow":
            unit["solvent_feed"]["flow"]["value"] = value
        elif value is None:
            unit.pop(key)
        else:
            unit[key] = value
    return unit


def _plant(tmp_path: Path, *units: dict) -> Path:
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: extract-test\nstage: concept\nsheets: []\n")
    data = {"schema": extraction.SCHEMA, "units": list(units)}
    (root / extraction.EXTRACTION_FILE).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return root


def _evaluate(**changes) -> extraction.UnitOutcome:
    return extraction.evaluate_unit(extraction.ExtractionUnit.model_validate(_unit(**changes)))


def test_one_stage_inside_the_benchmark_is_qualified():
    out = _evaluate()
    assert out.status == "converged", out.messages
    assert out.qualification["status"] == "qualified", out.qualification
    assert out.qualification["benchmark"].endswith(_name())
    p = out.performance
    # one equilibrium stage: two thirds of the 1-propanol into the ester
    assert 0.6 < p["solute_recovery"] < 0.75
    assert 0 < p["solvent_loss_fraction"] < 0.1
    assert p["distribution_mass"]["stage_1"] > 1 and p["selectivity"]["stage_1"] > 10
    assert p["solvent_to_feed_mass_ratio"] == pytest.approx(0.4)
    assert out.closure["status"] == "closed"
    assert out.closure["max_relative_component_imbalance"] < 1e-8
    assert out.energy["status"] == "not-evaluated"
    assert "regeneration" in out.boundary
    assert out.model["parameter_source"]["doi"] == "10.1016/j.fluid.2024.114104"
    assert out.model["backend"] == "thermo" and out.model["backend_version"]
    # the specified split a flowsheet component_separator can cite
    assert p["split_to_extract"]["1-propanol"] == pytest.approx(p["solute_recovery"])


def test_the_cascade_satisfies_the_stage_equations():
    """Three countercurrent stages: each stage is an equilibrium (iso-activity) and balances its
    inlets, the cascade closes, and it recovers more than one stage does."""
    out = _evaluate(stages=3)
    assert out.status == "converged", out.messages
    model = _model()
    feed = np.array(list(out.streams["feed"]["component_kmol_h"].values()))
    solvent = np.array(list(out.streams["solvent_feed"]["component_kmol_h"].values()))
    raff = [np.array(list(s["raffinate"]["component_kmol_h"].values())) for s in out.stages]
    extr = [np.array(list(s["extract"]["component_kmol_h"].values())) for s in out.stages]
    for n in range(3):
        inlet = (feed if n == 0 else raff[n - 1]) + (solvent if n == 2 else extr[n + 1])
        assert raff[n] + extr[n] == pytest.approx(inlet, rel=1e-8, abs=1e-10)
        x1, x2 = raff[n] / raff[n].sum(), extr[n] / extr[n].sum()
        activity = [np.log(x) + np.asarray(model(list(x))[0]) for x in (x1, x2)]
        assert np.abs(activity[0] - activity[1]).max() < 1e-7
        assert out.stages[n]["liquids"] == 2
    assert out.closure["max_relative_component_imbalance"] < 1e-8
    assert out.performance["solute_recovery"] > _evaluate().performance["solute_recovery"] + 0.1
    # the raffinate leaves the benchmarked range: the result is not qualified, and says why
    assert out.qualification["status"] == "unqualified"
    assert any("below the smallest benchmarked" in r for r in out.qualification["reasons"])


def test_a_mixture_near_the_plait_point_converges_and_is_unqualified():
    out = _evaluate(solvent_flow=30)
    assert out.status == "converged", out.messages
    assert any("above the largest" in r for r in out.qualification["reasons"])


def test_no_two_phase_region_is_refused():
    """5 kg/h of n-butyl acetate dissolves in the feed: one liquid, nothing to extract into."""
    out = _evaluate(solvent_flow=5)
    assert out.status == "refused"
    assert [f.rule for f in out.findings] == ["cheme.extraction-one-liquid"]
    assert "no two-phase region" in out.findings[0].message
    assert out.findings[0].hint
    assert not out.performance and not out.stages


def test_a_temperature_outside_the_parameters_is_refused():
    out = _evaluate(temperature={"value": 80, "unit": "°C", "provenance": "given"})
    assert out.status == "refused"
    assert out.findings[0].rule == "cheme.extraction-temperature"
    assert "not extrapolated" in out.findings[0].message


def test_a_missing_pair_is_refused_not_taken_as_zero():
    system = extraction.bundled_systems()[SYSTEM].model_dump(mode="json")
    system["id"] = "own"
    system.pop("qualification")
    system["nrtl"]["pairs"] = system["nrtl"]["pairs"][:2]
    out = _evaluate(system=None, model=system)
    assert out.status == "refused"
    assert out.findings[0].rule == "cheme.extraction-parameters"
    assert "1-propanol/n-butyl acetate" in out.findings[0].message


def test_parameters_from_the_plant_file_are_predictive_not_qualified():
    system = extraction.bundled_systems()[SYSTEM].model_dump(mode="json")
    system["id"] = "own"
    out = _evaluate(system=None, model=system)
    assert out.status == "converged"
    assert out.qualification["status"] == "unqualified"
    assert "plant file" in out.qualification["reasons"][0]
    assert out.model["parameters"] == "plant file (model:)"


def test_an_unknown_component_or_system_is_refused():
    out = _evaluate(solute="acetone")
    assert out.findings[0].rule == "cheme.extraction-component"
    out = _evaluate(system="water-acetone-mibk")
    assert out.findings[0].rule == "cheme.extraction-system"


def test_the_report_gives_findings_with_lines(tmp_path):
    root = _plant(tmp_path, _unit(), _unit(id="X-102", solvent_flow=5))
    report = extraction.extraction_report(root)
    assert [u.status for u in report.units] == ["converged", "refused"]
    assert not report.ok
    (finding,) = report.findings
    assert finding.file == extraction.EXTRACTION_FILE and finding.line
    assert finding.rule == "cheme.extraction-one-liquid" and finding.hint
    lines = (root / extraction.EXTRACTION_FILE).read_text(encoding="utf-8").splitlines()
    assert "solvent_feed" in lines[finding.line - 2]  # the line of its first key
    with pytest.raises(KeyError):
        extraction.extraction_report(root, "X-999")
    doc = report.as_dict()
    assert doc["schema"] == "cheme/extraction-result/v1"
    assert doc["source"]["fingerprints"][extraction.EXTRACTION_FILE]


def test_a_schema_error_is_a_finding(tmp_path):
    root = _plant(tmp_path, _unit(stages=0))
    report = extraction.extraction_report(root)
    assert report.findings[0].rule == "cheme.extraction-schema"
    assert report.findings[0].line and not report.units


def test_cli_extract(tmp_path, monkeypatch):
    root = _plant(tmp_path, _unit(), _unit(id="X-102", solvent_flow=5))
    before = sorted(p.name for p in (root / "process").iterdir())
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "extract", "X-101"])
    assert result.exit_code == 0, result.output
    assert "X-101: converged" in result.output and "qualification: qualified" in result.output
    assert "solvent regeneration" in result.output
    result = runner.invoke(app, ["process", "extract", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert [r["status"] for r in payload["results"]] == ["converged", "refused"]
    assert payload["results"][0]["schema"] == "cheme/adapter-result/v1"
    assert payload["findings"][0]["rule"] == "cheme.extraction-one-liquid"
    assert runner.invoke(app, ["process", "extract", "X-999"]).exit_code == 2
    assert sorted(p.name for p in (root / "process").iterdir()) == before


def test_cli_extract_systems(tmp_path, monkeypatch):
    result = runner.invoke(app, ["process", "extract", "--systems"])
    assert result.exit_code == 0, result.output
    assert SYSTEM in result.output and "Costa" in result.output
    rows = json.loads(runner.invoke(app, ["process", "extract", "--systems", "--json"]).output)
    assert rows[0]["qualified"] and rows[0]["tolerances"]["composition_abs"] == 0.035


def test_cli_extract_without_the_file(tmp_path, monkeypatch):
    root = _plant(tmp_path, _unit())
    (root / extraction.EXTRACTION_FILE).unlink()
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "extract"])
    assert result.exit_code == 2
    assert "does not exist" in result.output


def test_validate_reports_schema_errors_of_the_extraction_file(tmp_path, monkeypatch):
    root = _plant(tmp_path, _unit(stages=0))
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["validate", "--json"])
    findings = json.loads(result.output)["findings"]
    assert any(f["rule"] == "cheme.extraction-schema" and f["line"] for f in findings)
