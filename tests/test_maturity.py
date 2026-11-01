"""cheme maturity: which calculation level the evidence of each example supports, and why.

Two examples reach ``sourced`` with their cited design basis (process-ammonia,
process-double-column); the others have none and reach no level. The tests then add evidence to
copies of them, one requirement at a time (overwriting an example's design basis with the
test-only one below where they need it), and show that schema-valid files, drawings, artifacts
and a converged run alone never raise the level. The run records written here are synthetic (made in
the test, not by DWSIM): they exercise the record checks, not a simulation.
"""

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.fixed_bed import ASSUMPTIONS
from chemeascode.domains.process.model import load
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.simulation import record
from chemeascode.domains.process.simulation.translate import load as load_sim
from chemeascode.domains.process.simulation.translate import translate
from chemeascode.interfaces.cli import app
from chemeascode.project.maturity import MATURITY_FILE, maturity_report

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
DESIGN_BASIS = """\
capacity: {product: test fixture, value: 1}
feeds: [{name: feed of the test fixture}]
products: [{name: product of the test fixture}]
assumptions: [test fixture only]
"""


def _status(report, rid: str) -> str:
    return next(r.status for r in report.requirements if r.id == rid)


def _copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    shutil.copytree(EXAMPLES / name, target)
    return target


#: example -> (requirements that do not pass and why the example reaches no higher level)
EXPECTED = {
    "process-aggregate": {"sourced.design-basis": "missing", "balanced.model-basis": "fail"},
    "process-ammonia": {"sourced.design-basis": "pass", "balanced.model-basis": "fail"},
    "process-blocks": {"sourced.design-basis": "missing", "balanced.model-basis": "fail"},
    "process-double-column": {
        "sourced.design-basis": "pass",
        "balanced.balances-evaluable": "fail",
        "predictive.run-record": "missing",
        "predictive.property-regime": "missing",
    },
    "process-nested": {"sourced.design-basis": "missing", "balanced.model-basis": "fail"},
    "process-recycle": {"sourced.design-basis": "missing", "balanced.model-basis": "fail"},
    "process-separation": {
        "sourced.boundary": "fail",
        "balanced.balances-evaluable": "fail",
        "predictive.run-record": "missing",
    },
    "process-shift": {"sourced.design-basis": "missing", "balanced.model-basis": "fail"},
    "process-simulation": {
        "balanced.balances-evaluable": "fail",
        "predictive.property-regime": "missing",
    },
}


#: the examples with a cited design basis (process/design-basis.yaml); the others reach no level
SOURCED = {"process-ammonia", "process-double-column"}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_each_example_reaches_its_level_and_says_why(name):
    report = maturity_report(EXAMPLES / name)
    data = report.as_dict()
    if name in SOURCED:
        assert report.level == "sourced"
        assert data["library_maturity"] == "concept" and data["level_index"] == 1
    else:
        assert report.level is None
        assert data["library_maturity"] is None and data["level_index"] == 0
    for rid, status in EXPECTED[name].items():
        assert _status(report, rid) == status, rid
    # every requirement that does not pass is a finding with a file, a rule and a hint
    for finding in report.findings:
        assert finding.file and finding.rule.startswith("cheme.maturity-")
        if finding.level == "error":
            assert finding.hint, finding.rule
    # nothing is written
    assert not (EXAMPLES / name / MATURITY_FILE).exists()


def test_the_asu_like_example_stays_below_its_drawings(tmp_path):
    """The double column has its BFD and PFD, a design basis, a valid schema and a simulation
    spec that translates; it still reaches only sourced: open balances and no run record (whose
    streams the declared regime of its property package is checked on)."""
    report = maturity_report(EXAMPLES / "process-double-column")
    sheets = report.artifacts["sheets"]
    assert sheets and all(s["exists"] for s in sheets)
    assert _status(report, "sourced.flowsheet") == "pass"
    assert _status(report, "predictive.simulation-spec") == "pass"
    assert _status(report, "balanced.model-basis") == "pass"  # columns are equilibrium-stage
    assert {u["basis"] for u in report.model_basis} == {"equilibrium-stage"}
    assert report.level == "sourced"


def test_a_design_basis_reaches_sourced_and_sourced_values_reach_balanced(tmp_path):
    root = _copy(tmp_path, "process-ammonia")
    (root / "process" / "design-basis.yaml").write_text(DESIGN_BASIS, encoding="utf-8")
    report = maturity_report(root)
    assert report.level == "sourced"
    assert report.as_dict()["library_maturity"] == "concept"
    assert _status(report, "balanced.balances-closed") == "pass"
    # F1 rests on assumed outlet values: a specified basis without a source
    f1 = next(u for u in report.model_basis if u["id"] == "F1")
    assert (f1["basis"], f1["predictive"], f1["sourced"]) == ("stream-values", False, False)
    r1 = next(u for u in report.model_basis if u["id"] == "R1")
    assert (r1["basis"], r1["predictive"], r1["sourced"]) == ("equilibrium", True, True)

    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    flowsheet.write_text(
        text.replace(
            'provenance: assumed, source: "loop balance; all NH3 condensed"',
            'provenance: given, source: "test fixture: as if from a cited separator model"',
        ),
        encoding="utf-8",
    )
    report = maturity_report(root)
    assert report.level == "balanced"
    assert report.as_dict()["library_maturity"] == "screening"
    # sourced but specified: F1 caps the level at balanced
    assert _status(report, "predictive.model-basis") == "fail"
    detail = next(r.detail for r in report.requirements if r.id == "predictive.model-basis")
    assert "specified: F1 (stream-values)" in detail
    balances = next(r for r in report.requirements if r.id == "balanced.balances-closed")
    row = balances.evidence["balances"]["design"][0]
    assert {"residual_kg_h", "tolerance", "in_kg_h", "out_kg_h"} <= set(row)


def test_a_broken_balance_is_not_balanced(tmp_path):
    root = _copy(tmp_path, "process-ammonia")
    (root / "process" / "design-basis.yaml").write_text(DESIGN_BASIS, encoding="utf-8")
    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    flowsheet.write_text(text.replace("value: 445.8836", "value: 400.0"), encoding="utf-8")
    report = maturity_report(root)
    assert _status(report, "balanced.balances-closed") == "fail"
    assert report.level == "sourced"


def _synthetic_run(
    root: Path,
    *,
    converged: bool = True,
    energy: dict | None = None,
    streams: list[dict] | None = None,
    version: str = "synthetic",
) -> None:
    """A run record as cheme process simulate --fill writes it, made here (not by DWSIM)."""
    process, _ = load(root)
    sim, doc, _ = load_sim(root)
    case = process.flowsheet.default_case()
    found = translate(process, sim, doc, case)
    assert found.model is not None
    from chemeascode.foundation.provenance import source_revision

    record.write(
        root,
        {
            "case": case,
            "run_at": "2026-10-24T00:00:00Z",
            "tool": "cheme-as-code test",
            "simulator": {"name": "dwsim", "version": version, "method": sim.property_package},
            "property_package": sim.property_package,
            "model_fingerprint": found.fingerprint,
            "inputs": source_revision(root, record.RUN_INPUTS).as_dict(),
            "converged": converged,
            "status": "converged" if converged else "not-converged",
            "iterations": 3,
            "messages": [],
            "units": [],
            "streams": streams or [],
            "findings": [],
            **({"energy": energy} if energy is not None else {}),
        },
    )


def test_a_converged_current_run_alone_is_not_predictive(tmp_path):
    root = _copy(tmp_path, "process-double-column")
    (root / "process" / "design-basis.yaml").write_text(DESIGN_BASIS, encoding="utf-8")
    _synthetic_run(root)
    report = maturity_report(root)
    for rid in ("predictive.run-record", "predictive.current", "predictive.converged"):
        assert _status(report, rid) == "pass", rid
    assert _status(report, "predictive.solver") == "pass"
    # convergence is not physical validity: the balances stay open; a run without stream
    # states (and from no benchmarked DWSIM version) shows no stream inside the claimed regime
    assert _status(report, "predictive.balances") == "fail"
    assert _status(report, "predictive.property-regime") == "fail"
    assert report.level != "predictive"


def test_a_run_from_other_inputs_is_stale_and_a_failed_one_does_not_converge(tmp_path):
    root = _copy(tmp_path, "process-double-column")
    _synthetic_run(root, converged=False)
    assert _status(maturity_report(root), "predictive.converged") == "fail"
    sim = root / "process" / "simulation.yaml"
    data = yaml.safe_load(sim.read_text(encoding="utf-8"))
    data["property_package"] = "Soave-Redlich-Kwong (SRK)"
    sim.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = maturity_report(root)
    assert _status(report, "predictive.current") == "fail"
    current = next(r for r in report.requirements if r.id == "predictive.current")
    assert "process/simulation.yaml" in current.evidence["design"]["changed_files"]


def test_engineering_artifacts_never_raise_a_calculation_level(tmp_path):
    """An equipment list and a P&ID are artifacts: reported, never counted."""
    root = _copy(tmp_path, "process-ammonia")
    assert maturity_report(root).level == "sourced"
    (root / "equipment").mkdir()
    (root / "equipment" / "equipment-list.yaml").write_text(
        "schema: cheme/equipment-list/v1\nkind: equipment-list\nequipment: []\n", encoding="utf-8"
    )
    report = maturity_report(root)
    assert report.artifacts["files"]["equipment_list"] == ["equipment/equipment-list.yaml"]
    assert report.level == "sourced"
    assert "never establishes calculation maturity" in report.artifacts["note"]


def test_a_fixed_bed_reports_its_assumptions_and_an_omitted_pressure_drop(tmp_path):
    report = maturity_report(EXAMPLES / "process-shift")
    bed = next(u for u in report.model_basis if u["id"] == "R1")
    assert bed["basis"] == "kinetic" and bed["predictive"] and not bed["sourced"]
    assert "assumed" in bed["detail"]  # the example's pre-exponential factor is illustrative
    assert report.assumptions["models"]["R1"] == list(ASSUMPTIONS)
    assert not any("pressure drop" in t for t in bed["limitations"])  # Ergun data given
    assert not bed["simulated"]
    assert any("not in a simulation" in t for t in bed["limitations"])

    root = _copy(tmp_path, "process-shift")
    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    flowsheet.write_text(text.replace("      viscosity: 2.6e-5\n", ""), encoding="utf-8")
    report = maturity_report(root)
    limits = [x for x in report.limitations if x["subject"] == "R1"]
    assert any("no pressure drop" in x["limitation"] and x["line"] for x in limits)


def test_a_component_split_counts_as_sourced_only_with_a_given_basis(tmp_path):
    root = _copy(tmp_path, "process-separation")
    sim_file = root / "process" / "simulation.yaml"
    data = yaml.safe_load(sim_file.read_text(encoding="utf-8"))
    data["specs"]["C1"] = {"unit": "component_separator", "recoveries": {"C3H8": 0.99}}
    sim_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def c1():
        process, _ = load(root)
        sim, _, _ = load_sim(root)
        return next(u for u in model_bases(process, sim) if u.id == "C1")

    unit = c1()
    assert (unit.basis, unit.predictive, unit.sourced) == ("component-split", False, False)
    data["specs"]["C1"]["basis_source"] = "test fixture: vendor data"
    data["specs"]["C1"]["operating_basis"] = "test fixture conditions"
    sim_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    unit = c1()
    assert (unit.basis, unit.predictive, unit.sourced) == ("component-split", False, True)
    assert "test fixture conditions" in unit.detail
    # the translation's basis (Translation.bases) is the one used
    process, _ = load(root)
    sim, doc, _ = load_sim(root)
    found = translate(process, sim, doc, process.flowsheet.default_case())
    assert found.bases["C1"]["basis"] == "specified"
    unit = next(u for u in model_bases(process, sim, found.bases) if u.id == "C1")
    assert unit.sources == ["test fixture: vendor data"]


def _bed_row(converged: bool) -> dict:
    """A run-record row of a fixed bed coupled as an external unit (synthetic, as
    cheme process simulate --fill writes it)."""
    return {
        "id": "R1",
        "unit": "kinetic_pfr",
        "status": "simulated",
        "coupling": "external-unit",
        "outer_loop": {
            "coupling": "external-unit",
            "iterations": 4,
            "converged": converged,
            "residuals": [{"iteration": 4, "flow": 2e-5, "pressure": 0.0, "temperature_K": 0.01}],
        },
    }


def test_a_bed_counts_as_simulated_only_with_a_converged_external_coupling():
    process, _ = load(EXAMPLES / "process-shift")
    bed = next(u for u in model_bases(process, None, None, {"R1": [_bed_row(True)]}))
    assert bed.simulated and bed.predictive
    assert "outer loop converged" in bed.detail
    assert not any("simulation" in t for t in bed.limitations)
    assert bed.assumptions == list(ASSUMPTIONS)  # the bed model's assumptions stay listed
    assert not bed.sourced  # the rate law still needs a source
    bed = next(u for u in model_bases(process, None, None, {"R1": [_bed_row(False)]}))
    assert not bed.simulated
    assert any("not in a simulation" in t for t in bed.limitations)


#: The examples with a process/simulation.yaml: each records a method_selection whose facts
#: (nonpolar, no pseudocomponents) recommend its property package, Peng-Robinson.
SIMULATED = ["process-double-column", "process-separation", "process-simulation"]


@pytest.mark.parametrize("name", SIMULATED)
def test_each_simulated_example_records_a_selection_that_recommends_its_package(name):
    report = maturity_report(EXAMPLES / name)
    package = next(r for r in report.requirements if r.id == "predictive.property-package")
    assert package.status == "pass", package.detail
    assert package.evidence["findings"] == [] and "substitution" not in package.evidence
    sim, _, _ = load_sim(EXAMPLES / name)
    assert sim.method_selection is not None and sim.method_selection.substitution is None


def test_the_property_package_needs_a_recorded_selection_and_a_run_inside_its_regime(
    tmp_path,
):
    root = _copy(tmp_path, "process-double-column")
    sim_file = root / "process" / "simulation.yaml"
    data = yaml.safe_load(sim_file.read_text(encoding="utf-8"))
    del data["method_selection"]
    sim_file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = maturity_report(root)
    package = next(r for r in report.requirements if r.id == "predictive.property-package")
    assert package.status == "missing"
    assert package.evidence["findings"][0]["rule"] == "cheme.process-sim-method-unrecorded"
    regime = next(r for r in report.requirements if r.id == "predictive.property-regime")
    # PR has a benchmarked range for N2/O2/Ar (methods.yml); without a run nothing is shown
    assert regime.status == "missing" and "no run recorded" in regime.detail
    claim = regime.evidence["claim"]
    assert claim["benchmark"] == "tests/test_process_simulate_property_package.py"
    assert claim["simulator_version"] == "9.0.5"
    assert any("liquid density of mixtures" in t for t in claim["not_claimed"])
    assert any(x["subject"] == "simulation-route" for x in report.limitations)


def _stream(sid: str, t_k: float, p_bar: float, x: dict[str, float]) -> dict:
    """A simulated stream row of a run record (synthetic: written here, not by DWSIM)."""
    return {
        "id": sid,
        "values": {
            "temperature": {"value": t_k, "unit": "K"},
            "pressure": {"value": p_bar, "unit": "bar(a)"},
            "composition": {"basis": "mole_fraction", "values": x},
        },
        "filled": ["temperature", "pressure", "composition"],
        "kept": {},
    }


AIR_X = {"N2": 0.7812, "O2": 0.2096, "AR": 0.0092}
#: The double column's simulated outlets (its feeds are S1 and S6).
OUTLETS = ("S2", "S3", "S4", "S5", "S7", "S8", "S9")


def _regime(root: Path, streams: list[dict], version: str = "9.0.5.0"):
    _synthetic_run(root, streams=streams, version=version)
    return next(
        r for r in maturity_report(root).requirements if r.id == "predictive.property-regime"
    )


def test_the_regime_passes_inside_the_claim_and_names_the_stream_outside(tmp_path):
    root = _copy(tmp_path, "process-double-column")
    # the outlets as --fill records them (the feeds S1, S6 have no row: the check takes them
    # from the translation, as DWSIM got them)
    inside = [
        _stream("S2", 96.0, 5.2, {"N2": 0.9999, "O2": 0.0001}),  # GAN, saturated vapour
        _stream("S5", 94.0, 1.4, {"O2": 0.995, "AR": 0.005}),  # LOX, saturated liquid
        _stream("S3", 80.0, 30.0, {"N2": 1.0}),  # pumped, subcooled
        _stream("S4", 230.0, 80.0, {"N2": 0.9999, "O2": 0.0001}),  # warm, high pressure
        _stream("S7", 80.0, 1.3, {"N2": 0.99, "O2": 0.01}),
        _stream("S8", 92.0, 1.3, {"O2": 0.995, "AR": 0.005}),
        _stream("S9", 94.0, 1.4, {"O2": 0.995, "AR": 0.005}),
    ]
    regime = _regime(root, inside)
    assert regime.status == "pass", regime.detail
    assert regime.evidence["states_checked"] == 9 and regime.evidence["feeds_checked"] == 2
    assert "9 state(s) (2 feed(s), 7 simulated stream(s))" in regime.detail
    # what the claim does not cover stays listed, with the mixture states it concerns
    limits = regime.evidence["limitations"]
    assert any("liquid density of mixtures" in t for t in limits)
    assert any(t.startswith("mixture states whose density") and "S1 (design)" in t for t in limits)
    report = maturity_report(root)
    assert any(x["subject"] == "predictive.property-regime" for x in report.limitations)

    # near-critical (left out of the claim): fails with the stream and the state
    regime = _regime(root, [*inside[:4], _stream("S7", 130.0, 30.0, AIR_X), *inside[5:]])
    assert regime.status == "fail"
    assert regime.detail.startswith("case design, stream S7: 130 K, 3000 kPa(a) is outside")
    assert "of nitrogen (65-320 K at 100-2000 kPa(a);" in regime.detail
    assert regime.hint and "tests/test_process_simulate_property_package.py" in regime.hint
    assert "limitations" not in regime.evidence
    # argon below its box (it freezes at 83.8 K), a component the claim does not cover
    regime = _regime(
        root, [*inside[:5], _stream("S8", 80.0, 1.3, {"N2": 0.9, "AR": 0.1}), inside[6]]
    )
    assert regime.status == "fail" and "outside the boxes of argon" in regime.detail
    regime = _regime(root, [*inside[:6], _stream("S9", 300.0, 1.0, {"N2": 0.99, "CO2": 0.01})])
    assert regime.status == "fail" and "component without a CAS number" in regime.detail
    # another DWSIM version than the one benchmarked
    regime = _regime(root, inside, version="9.0.6.0")
    assert regime.status == "fail" and "the claim is benchmarked on 9.0.5" in regime.detail
    # a run without simulated stream states shows nothing
    assert _regime(root, []).status == "missing"


def test_the_regime_checks_the_feeds_dwsim_flashes(tmp_path):
    """The record holds the simulated outlets only; a feed outside the claim still fails."""
    root = _copy(tmp_path, "process-double-column")
    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    text = text.replace(
        "pressure: {value: 5.5, provenance: given, source: main heat exchanger outlet}",
        "pressure: {value: 30, provenance: given, source: test fixture}",
    ).replace(
        "temperature: {value: -173, provenance: given, source: near the dew point}",
        "temperature: {value: -143.15, provenance: given, source: test fixture}",
    )
    flowsheet.write_text(text, encoding="utf-8")
    regime = _regime(root, [_stream(s, 96.0, 5.2, {"N2": 1.0}) for s in OUTLETS])
    assert regime.status == "fail"
    assert regime.detail.startswith("case design, feed S1: 130 K, 3000 kPa(a) is outside")
    # every outlet is inside, the feed is not
    assert all(o.startswith("case design, feed S1: ") for o in regime.evidence["outside"])


def test_energy_streams_carry_no_state_and_pass(tmp_path):
    """An energy stream's row (a duty) is not a state: a compressor's power does not fail the
    regime."""
    root = _copy(tmp_path, "process-simulation")
    rows = [
        *(_stream(s, 300.0, 8.0, AIR_X) for s in ("S2", "S3", "S4", "S5")),
        {"id": "W1", "values": {"duty": {"value": 55.0, "unit": "kW"}}, "filled": ["duty"]},
    ]
    regime = _regime(root, rows)
    assert regime.status == "pass", regime.detail
    assert regime.evidence["states_checked"] == 5  # the feed S1 and the outlets; not W1


def test_the_regime_needs_dwsims_parameters_and_a_claim(tmp_path):
    root = _copy(tmp_path, "process-double-column")
    sim = root / "process" / "simulation.yaml"
    data = yaml.safe_load(sim.read_text(encoding="utf-8"))
    data["interaction_parameters"] = [
        {"components": ["N2", "O2"], "kij": {"value": 0.0, "provenance": "assumed"}}
    ]
    sim.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    regime = _regime(root, [_stream("AIR", 300.0, 5.6, AIR_X)])
    assert regime.status == "fail" and "sets interaction parameters (N2-O2)" in regime.detail
    del data["interaction_parameters"]
    # SRK claims nitrogen, oxygen and argon each alone: air is outside wherever it lies
    data["property_package"] = "Soave-Redlich-Kwong (SRK)"
    sim.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    regime = _regime(root, [_stream("AIR", 300.0, 5.6, AIR_X)])
    assert regime.status == "fail"
    assert "a mixture (argon, nitrogen, oxygen) is outside the claim" in regime.detail
    assert regime.evidence["claim"]["benchmark"] == (
        "tests/test_process_simulate_property_package_srk.py"
    )
    data["property_package"] = "Peng-Robinson 1978 (PR78)"  # no range claimed for PR78
    sim.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    regime = _regime(root, [_stream("AIR", 300.0, 5.6, AIR_X)])
    assert regime.status == "unsupported"
    assert "methods.yml" in regime.detail and "no range claimed" in regime.detail
    assert "benchmarks" in regime.hint


def test_a_state_the_claim_cannot_judge_fails_the_regime(tmp_path):
    """A gauge pressure (no ambient pressure stated) or a stream without a simulated
    temperature is reported, never counted as inside the claim."""
    root = _copy(tmp_path, "process-double-column")
    others = [_stream(s, 96.0, 5.2, {"N2": 1.0}) for s in OUTLETS[1:]]
    gauge = _stream("S2", 96.0, 4.2, {"N2": 1.0})
    gauge["values"]["pressure"]["unit"] = "bar(g)"
    regime = _regime(root, [gauge, *others])
    assert regime.status == "fail"
    assert regime.evidence["outside"] == ["case design, stream S2: units not convertible"]
    no_temperature = _stream("S2", 96.0, 5.2, {"N2": 1.0})
    del no_temperature["values"]["temperature"]
    regime = _regime(root, [no_temperature, *others])
    assert regime.evidence["outside"] == ["case design, stream S2: no simulated state"]
    # an outlet without a row is reported too, not skipped
    regime = _regime(root, others)
    assert regime.status == "fail"
    assert regime.evidence["outside"] == ["case design, stream S2: no simulated state recorded"]


@pytest.mark.parametrize(
    ("package", "status"),
    [("Peng-Robinson (PR)", "pass"), ("Soave-Redlich-Kwong (SRK)", "fail")],
)
def test_one_regime_check_reads_each_package_claim(tmp_path, package, status):
    """PR and SRK go through the same requirement, once, with their own claim:
    the air feeds S1 and S6 are inside PR's mixture claim, and outside
    SRK's, which holds each component alone."""
    from chemeascode.domains.process.thermodynamics.methods import simulation_claim

    root = _copy(tmp_path, "process-double-column")
    sim_file = root / "process" / "simulation.yaml"
    text = sim_file.read_text(encoding="utf-8")
    sim_file.write_text(text.replace("Peng-Robinson (PR)", package), encoding="utf-8")
    outlets = [_stream(s, 96.0, 5.2, {"N2": 1.0}) for s in OUTLETS]
    _synthetic_run(root, streams=outlets, version="9.0.5.0")
    found = [r for r in maturity_report(root).requirements if r.id == "predictive.property-regime"]
    assert len(found) == 1
    regime = found[0]
    assert regime.status == status, regime.detail
    assert regime.evidence["property_package"] == package
    assert regime.evidence["claim"]["benchmark"] == simulation_claim(package).benchmark.test
    if status == "fail":
        assert regime.evidence["outside"] == [
            f"case design, feed {s}: a mixture (argon, nitrogen, oxygen) is outside the claim, "
            "which holds each component alone"
            for s in ("S1", "S6")
        ]


def test_a_claim_limited_to_some_phases_cannot_pass_without_a_recorded_phase(tmp_path, monkeypatch):
    """The run record holds no phase: a vapour-only claim is reported, never passed."""
    from chemeascode.domains.process.thermodynamics import methods

    claim = methods.simulation_claim("Peng-Robinson (PR)").model_copy(update={"phases": ["vapor"]})
    monkeypatch.setattr(methods, "simulation_claim", lambda package: claim)
    root = _copy(tmp_path, "process-double-column")
    regime = _regime(root, [_stream(s, 96.0, 5.2, {"N2": 1.0}) for s in OUTLETS])
    assert regime.status == "fail"
    assert regime.detail.startswith(
        "case design, feed S1: phase not recorded, so it cannot be shown inside the claimed "
        "phases (vapor)"
    )


def _requirement(report, rid: str):
    return next(r for r in report.requirements if r.id == rid)


def test_engineering_pid_needs_a_drawn_sheet_and_links_need_a_flowsheet(tmp_path):
    """A P&ID declared in plant.yaml but absent or planned is no P&ID, and without
    process/flowsheet.yaml no link is checked."""
    root = _copy(tmp_path, "safety-hazop")
    report = maturity_report(root)
    assert _status(report, "engineering.pid") == "pass"
    links = _requirement(report, "engineering.process-links")
    assert links.status == "missing" and "process/flowsheet.yaml" in links.detail

    # a planned process sheet (a PFD) is not a P&ID: it leaves engineering.pid alone
    plant = root / "plant.yaml"
    text = plant.read_text(encoding="utf-8")
    plant.write_text(
        text + "  - {id: PFD, file: process/PFD.xml, kind: pfd, status: planned}\n",
        encoding="utf-8",
    )
    pid = _requirement(maturity_report(root), "engineering.pid")
    assert pid.status == "pass" and pid.evidence["not_drawn"] == [], pid.detail
    plant.write_text(text, encoding="utf-8")

    # a second sheet, planned: the package is not complete
    plant.write_text(
        plant.read_text(encoding="utf-8")
        + "  - {id: P-02, file: pid/P-02.xml, title: Second, status: planned}\n",
        encoding="utf-8",
    )
    pid = _requirement(maturity_report(root), "engineering.pid")
    assert pid.status == "fail" and "not drawn: P-02" in pid.detail
    assert pid.evidence["not_drawn"] == ["P-02"]

    # a P&ID listed outside the repository is never read: not drawn either
    text = plant.read_text(encoding="utf-8").replace(", status: planned", "")
    plant.write_text(text.replace("pid/P-02.xml", "../outside/P-02.xml"), encoding="utf-8")
    pid = _requirement(maturity_report(root), "engineering.pid")
    assert pid.status == "fail" and pid.evidence["not_drawn"] == ["P-02"]
    # a declared sheet without a file, not planned, beside a drawn one
    plant.write_text(text, encoding="utf-8")
    pid = _requirement(maturity_report(root), "engineering.pid")
    assert pid.status == "fail" and pid.evidence["not_drawn"] == ["P-02"]

    # no sheet file at all: missing, planned or not
    (root / "pid" / "P-01.xml").unlink()
    pid = _requirement(maturity_report(root), "engineering.pid")
    assert pid.status == "missing" and "pid/P-01.xml" in pid.detail
    plant.write_text(plant.read_text(encoding="utf-8").replace(", status: planned", ""))
    assert _status(maturity_report(root), "engineering.pid") == "missing"


def test_a_manifest_claim_above_the_evidence_is_reported_and_left_alone(tmp_path, monkeypatch):
    root = _copy(tmp_path, "process-double-column")
    manifest = root / "process.yaml"
    text = (
        "schema: cheme-as-code/process/v1\nid: x\nmaturity: basic-engineering\n"
        "validation: {status: unreviewed}\n"
    )
    manifest.write_text(text, encoding="utf-8")
    report = maturity_report(root)
    assert report.manifest["claimed_maturity"] == "basic-engineering"
    assert report.manifest["claim_exceeds_evidence"] is True
    assert report.review["manifest_status"] == "unreviewed"
    found = [f for f in report.findings if f.rule == "cheme.maturity-claim-exceeds"]
    assert found and found[0].line == 3 and found[0].hint
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    monkeypatch.chdir(root)
    assert CliRunner().invoke(app, ["maturity", "--write"]).exit_code == 0
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    # the review status and the claim stay as people wrote them: only the report is new
    assert set(after) - set(before) == {root / MATURITY_FILE}
    assert all(after[p] == content for p, content in before.items())


def test_the_command_prints_the_report_and_writes_only_on_request(tmp_path, monkeypatch):
    root = _copy(tmp_path, "process-ammonia")
    monkeypatch.chdir(root)
    runner = CliRunner()
    done = runner.invoke(app, ["maturity", "--json"], catch_exceptions=False)
    assert done.exit_code == 0
    data = json.loads(done.output)
    expected = maturity_report(root).as_dict()
    for item in (data, expected):
        item.pop("checked_at")
    assert data == expected
    assert data["schema"] == "cheme/maturity-report/v1"
    assert [lv["id"] for lv in data["levels"]] == [
        "sourced",
        "balanced",
        "predictive",
        "engineering",
    ]
    assert not (root / MATURITY_FILE).exists()

    done = runner.invoke(app, ["maturity", "--require", "sourced"], catch_exceptions=False)
    assert done.exit_code == 0
    done = runner.invoke(app, ["maturity", "--require", "balanced"], catch_exceptions=False)
    assert done.exit_code == 1
    text = re.sub(r"\x1b\[[0-9;]*m", "", done.output)
    assert "calculation maturity: sourced" in text and "cheme.maturity-balanced-model-basis" in text

    done = runner.invoke(app, ["maturity", "--write"], catch_exceptions=False)
    assert done.exit_code == 0
    written = json.loads((root / MATURITY_FILE).read_text(encoding="utf-8"))
    assert written["level"] == "sourced"
    assert runner.invoke(app, ["maturity", "--require", "nonsense"]).exit_code == 2


def _audit(plant: dict, exchangers=(), levels=()) -> dict:
    """An energy audit as the run record keeps it (synthetic, simulation.energy)."""
    return {
        "closure": {"units": [], "plant": plant},
        "exchangers": list(exchangers),
        "utility_levels": list(levels),
    }


CLOSED = {"status": "ok", "residual_kW": 0.02, "tolerance_kW": 0.5, "reasons": []}


@pytest.mark.parametrize(
    ("energy", "closure", "exchangers"),
    [
        (None, "missing", "missing"),  # a run recorded before the audit existed
        (_audit(CLOSED, [{"id": "E1", "status": "ok"}]), "pass", "pass"),
        (
            _audit(
                {"status": "imbalance", "residual_kW": 40.0, "tolerance_kW": 2.0, "reasons": []}
            ),
            "fail",
            "pass",
        ),
        (
            _audit({"status": "unsupported", "reasons": ["C1: column top without condenser"]}),
            "unsupported",
            "pass",
        ),
        (_audit(CLOSED, [{"id": "E1", "status": "crossed"}]), "pass", "fail"),
        (_audit(CLOSED, [{"id": "E1", "status": "below-min-approach"}]), "pass", "fail"),
        (
            _audit(
                CLOSED,
                [],
                [{"id": "C1", "role": "reboiler", "terminal": "LPS", "status": "infeasible"}],
            ),
            "pass",
            "fail",
        ),
    ],
)
def test_the_energy_audit_of_the_run_gates_predictive(tmp_path, energy, closure, exchangers):
    root = _copy(tmp_path, "process-double-column")
    _synthetic_run(root, energy=energy)
    report = maturity_report(root)
    assert _status(report, "predictive.energy-closure") == closure
    assert _status(report, "predictive.exchangers") == exchangers
    required = {r.id: r.required for r in report.requirements}
    assert required["predictive.energy-closure"] and required["predictive.exchangers"]
    assert not required["balanced.energy-closure"]
    if closure == "unsupported":
        detail = next(r.detail for r in report.requirements if r.id == "predictive.energy-closure")
        assert "column top without condenser" in detail and "heat-of-formation" in detail


def test_stream_properties_must_lie_inside_the_package_claim(tmp_path):
    root = _copy(tmp_path, "process-double-column")
    flowsheet = root / "process" / "flowsheet.yaml"
    text = flowsheet.read_text(encoding="utf-8")
    calculated = (
        "        composition: {basis: mole_fraction, values: {N2: 0.7811, O2: 0.2096, AR: 0.0093},"
        " provenance: given, source: dry air}\n"
    )
    assert calculated in text
    flowsheet.write_text(
        text.replace(
            calculated,
            calculated
            + "        calculated:\n"
            + "          density: {value: 1.0, unit: kg/m3, provenance: calculated,"
            + " source: test fixture}\n",
            1,
        ),
        encoding="utf-8",
    )
    report = maturity_report(root)
    req = next(r for r in report.requirements if r.id == "predictive.stream-properties")
    assert req.status == "pass", req.detail
    assert req.evidence["package"] and req.evidence["benchmark"]["test"].startswith("tests/")
    assert req.evidence["streams_with_calculated_properties"] == ["S1 (design)"]
    text = flowsheet.read_text(encoding="utf-8")
    flowsheet.write_text(
        text.replace("temperature: {value: -173,", "temperature: {value: 200,", 1),
        encoding="utf-8",
    )
    req = next(
        r for r in maturity_report(root).requirements if r.id == "predictive.stream-properties"
    )
    assert req.status == "fail" and "S1 (design)" in req.detail


def test_boundary_gaps_are_artifacts_and_limitations_not_a_gate():
    report = maturity_report(EXAMPLES / "process-ammonia")
    boundary = report.artifacts["boundary"]
    assert boundary["complete"] is False and boundary["findings"]
    assert any(x["subject"] == "boundary" for x in report.limitations)
    assert [r.id for r in report.requirements if "boundary" in r.id] == ["sourced.boundary"]
