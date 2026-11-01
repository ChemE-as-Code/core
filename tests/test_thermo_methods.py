"""The supported-method contract (methods.yml): recommendation, phase.py and
the DWSIM route agree on which methods run; substitutions are explicit; binary parameter coverage
tells missing from accepted zeros; electrolytes, solids and pseudocomponents are refused or limited
as the table says."""

from __future__ import annotations

import ast
import itertools
import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.thermodynamics import methods
from chemeascode.domains.process.thermodynamics.model_selection import (
    RULES_FILE,
    select_thermo_model,
)
from chemeascode.domains.process.thermodynamics.phase import (
    ActivityCoefficientModel,
    ActivityCoefficientModelMapping,
    EOSModel,
    EOSModelMapping,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()


def _recommendations() -> list[str]:
    kb = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    return sorted({m for outcome in kb["outcomes"] for m in outcome["models"]})


# -- the table -------------------------------------------------------------------------------


def test_every_recommendation_is_in_the_table_exactly_once():
    table = methods.method_table()
    listed = [name for m in table.methods for name in m.recommended_as]
    assert len(listed) == len(set(listed))
    assert sorted(listed) == _recommendations()
    assert len({m.id for m in table.methods}) == len(table.methods)


def test_simulation_packages_are_the_workers():
    from chemeascode.integrations import dwsim_worker

    assert sorted(methods.simulation_packages()) == sorted(dwsim_worker.PACKAGES)


def test_phase_models_are_what_phase_py_takes():
    from pydantic import TypeAdapter

    models = [m.phase.model for m in methods.method_table().methods if m.phase is not None]
    for model in models:
        if "eos_model" in model:
            TypeAdapter(EOSModel).validate_python(model)
        else:
            TypeAdapter(ActivityCoefficientModel).validate_python(model)
    eos = {m["eos_model"] for m in models if "eos_model" in m}
    liquids = {m["liquid_phase_model"] for m in models if "liquid_phase_model" in m}
    assert eos == {e.value for e in EOSModelMapping}
    assert liquids == {e.value for e in ActivityCoefficientModelMapping}


def test_every_method_is_executable_substituted_or_explicitly_unsupported_per_route():
    table = methods.method_table()
    for m in table.methods:
        for ref in m.substitutes:
            assert table.method(ref.method).id == ref.method and ref.loses
        for route in methods.ROUTES:
            support = methods.route_support(m.id, route)
            if support.executable:
                assert support.model if route == "phase" else support.package
                continue
            assert support.reason
            if support.substitution is None:
                assert "no substitution" in support.reason
            else:
                alt = table.method(support.substitution.method)
                assert alt.executable(route) and support.substitution.substitution is True


def test_routes_claim_no_application_range():
    for route in methods.ROUTES:
        assert methods.application_range(route).startswith("no range claimed")
        assert methods.route_limitations(route)


def test_every_claimed_range_names_a_benchmark_test_that_exists():
    """A package's claim is only as good as its benchmark: the test it names exists."""
    root = Path(__file__).resolve().parents[1]
    for package in methods.simulation_packages():
        claim = methods.simulation_claim(package)
        if claim is not None:
            assert (root / claim.benchmark.test).is_file(), (package, claim.benchmark.test)


def test_only_benchmarked_simulation_packages_claim_a_range():
    """PR claims N2/O2/Ar (tests/test_process_simulate_property_package.py, live), SRK each of
    them alone (tests/test_process_simulate_property_package_srk.py, live), NRTL ethanol +
    water at 101.3 kPa (tests/test_process_simulate_property_package_nrtl.py, live); every
    other package claims none."""
    claimed = {p for p in methods.simulation_packages() if methods.simulation_claim(p)}
    assert claimed == {"Peng-Robinson (PR)", "Soave-Redlich-Kwong (SRK)", "NRTL"}
    for package in claimed:
        claim = methods.simulation_claim(package)
        assert (EXAMPLES.parent / claim.benchmark.test).is_file()
        assert set(claim.regions) == set(claim.components)
        for boxes in claim.regions.values():
            for box in boxes:
                assert box.temperature_K[0] < box.temperature_K[1]
                assert 0 < box.pressure_kPa[0] < box.pressure_kPa[1]
        assert claim.not_claimed and claim.tolerances
    # a claim holding mixtures records the package's own kij for every claimed pair, keyed by
    # sorted CAS numbers; SRK's database has none for these pairs and claims no mixture
    claim = methods.simulation_claim("Peng-Robinson (PR)")
    assert claim.mixtures
    pairs = {"&".join(sorted(p)) for p in itertools.combinations(claim.components, 2)}
    assert set(claim.interaction_parameters.kij) == pairs
    srk = methods.simulation_claim("Soave-Redlich-Kwong (SRK)")
    assert not srk.mixtures and srk.interaction_parameters.kij == {}
    # an activity-coefficient claim records the package's own pair entry instead of a kij
    nrtl = methods.simulation_claim("NRTL")
    assert nrtl.mixtures and nrtl.interaction_parameters.kij == {}
    [(pair, entry)] = nrtl.interaction_parameters.activity.items()
    assert pair == "&".join(sorted(nrtl.components))
    assert set(entry) == {"A12", "A21", "B12", "B21", "C12", "C21", "alpha12"}


def test_the_nrtl_claim_holds_one_isobar_of_ethanol_and_water():
    claim = methods.simulation_claim("NRTL")
    ethanol, water = "64-17-5", "7732-18-5"
    assert methods.outside_claim(claim, 351.5, 101.325, {ethanol, water}) == []
    assert methods.outside_claim(claim, 360.0, 101.3, {water}) == []
    [why] = methods.outside_claim(claim, 340.0, 50.0, {ethanol, water})[:1]
    assert why.startswith("340 K, 50 kPa(a) is outside the boxes of ethanol (351.2-373.2 K at")
    assert methods.outside_claim(claim, 351.5, 101.3, {ethanol, "67-56-1"}) == [
        "component 67-56-1 is not in the claim"
    ]


def test_one_claim_schema_and_one_property_regime_check():
    """Every simulation package's claim, PR's and SRK's alike, is one
    schema (:class:`methods.SimulationClaim`, at ``methods[].simulation.application_range``) read by
    one check, ``predictive.property-regime`` (``maturity._property_regime``, through
    ``simulation_claim`` and ``outside_claim``). A second claim model, rule id or claim reader is a
    duplicate to remove, not to add beside it."""
    src = Path(__file__).resolve().parents[1] / "src" / "chemeascode"
    claim_models, rule_sites, readers = [], [], []
    for path in sorted(src.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        where = path.relative_to(src).as_posix()
        for node in ast.walk(tree):
            # a model of a simulator claim: one that records the simulator version benchmarked
            if isinstance(node, ast.ClassDef) and any(
                isinstance(a, ast.AnnAssign)
                and isinstance(a.target, ast.Name)
                and a.target.id == "simulator_version"
                for a in node.body
            ):
                claim_models.append(f"{where}:{node.name}")
            if isinstance(node, ast.Constant) and node.value == "predictive.property-regime":
                rule_sites.append(where)
            if isinstance(node, ast.FunctionDef) and node.name in (
                "simulation_claim",
                "outside_claim",
            ):
                readers.append(f"{where}:{node.name}")
    methods_py = "domains/process/thermodynamics/methods.py"
    assert claim_models == [f"{methods_py}:SimulationClaim"]
    assert rule_sites == ["project/maturity.py"]
    assert sorted(readers) == [f"{methods_py}:outside_claim", f"{methods_py}:simulation_claim"]
    # the claiming packages hold that one model, where the route's schema puts it
    route = methods.SimulationRoute.model_fields["application_range"].annotation
    assert route == methods.SimulationClaim | None
    for package in ("Peng-Robinson (PR)", "Soave-Redlich-Kwong (SRK)", "NRTL"):
        assert type(methods.simulation_claim(package)) is methods.SimulationClaim, package


def test_outside_claim_names_the_component_and_the_boxes():
    claim = methods.simulation_claim("Peng-Robinson (PR)")
    n2, ar = "7727-37-9", "7440-37-1"
    assert methods.outside_claim(claim, 90.0, 130.0, {n2, ar}) == []
    assert methods.outside_claim(claim, 300.0, 9000.0, {n2}) == []
    assert methods.outside_claim(claim, 130.0, 3000.0, {n2})[0].startswith(
        "130 K, 3000 kPa(a) is outside the boxes of nitrogen (65-320 K at 100-2000 kPa(a);"
    )
    assert methods.outside_claim(claim, 80.0, 130.0, {n2, ar}) == [
        methods.outside_claim(claim, 80.0, 130.0, {ar})[0]
    ]
    assert methods.outside_claim(claim, 300.0, 100.0, {n2, "124-38-9", None}) == [
        "component without a CAS number is not in the claim",
        "component 124-38-9 is not in the claim",
    ]


def test_a_claim_without_mixtures_holds_each_component_alone():
    claim = methods.simulation_claim("Soave-Redlich-Kwong (SRK)")
    n2, ar = "7727-37-9", "7440-37-1"
    assert methods.outside_claim(claim, 90.0, 130.0, {n2}) == []
    assert methods.outside_claim(claim, 90.0, 130.0, {ar}) == []
    assert methods.outside_claim(claim, 90.0, 130.0, {n2, ar}) == [
        "a mixture (argon, nitrogen) is outside the claim, which holds each component alone"
    ]
    # a component outside the claim is named first; a pure state still needs a box
    assert methods.outside_claim(claim, 300.0, 100.0, {n2, None}) == [
        "component without a CAS number is not in the claim"
    ]
    assert methods.outside_claim(claim, 130.0, 3000.0, {n2})[0].startswith("130 K, 3000 kPa(a)")


def test_regime_decisions_are_all_unsupported():
    decisions = methods.regime_decisions()
    assert set(decisions) == {
        "electrolytes",
        "solid_equilibrium",
        "high_temperature_solid_reaction",
        "petroleum_pseudocomponents",
    }
    for decision in decisions.values():
        assert decision.phase.status == decision.simulation.status == "unsupported"
    # the furnace energy basis covers one solid reaction, outside the thermodynamic routes
    furnace = decisions["high_temperature_solid_reaction"].elsewhere["furnace"]
    assert furnace.status == "limited" and "calcination" in furnace.evidence


# -- recommendations state executability ----------------------------------------------------


def test_nonpolar_recommendation_is_executable_and_lkp_is_a_marked_substitution():
    result = select_thermo_model({"is_polar": False, "has_pseudocomponents": False})
    assert result.executable["phase"] == ["Peng-Robinson", "Redlich-Kwong-Soave"]
    assert result.executable["simulation"] == ["Peng-Robinson", "Redlich-Kwong-Soave"]
    assert result.notes == []
    lkp = next(m for m in result.methods if m.recommended == "Lee-Kesler-Plocker")
    assert not lkp.phase.executable and not lkp.simulation.executable
    assert lkp.simulation.substitution.substitution is True
    assert lkp.simulation.substitution.package == "Peng-Robinson (PR)"
    assert lkp.phase.substitution.model == {"eos_model": "Peng-Robinson"}
    assert "corresponding-states" in lkp.phase.substitution.loses


def test_electrolyte_recommendation_has_no_route_and_no_substitution():
    result = select_thermo_model({"is_polar": True, "is_electrolyte": True})
    assert result.executable == {"phase": [], "simulation": []}
    assert all(m.phase.substitution is None for m in result.methods)
    assert all(m.simulation.substitution is None for m in result.methods)
    assert len(result.notes) == 3 and all("unsupported" in n for n in result.notes)
    # Pitzer runs on the electrolyte route, for its qualified systems only
    assert "electrolyte route runs its liquid model for NaCl-H2O only" in result.notes[2]


def test_pseudocomponent_recommendation_has_no_route_and_no_substitution():
    result = select_thermo_model(
        {
            "is_polar": False,
            "has_pseudocomponents": True,
            "pressure_value": 5,
            "pressure_unit": "bar(a)",
        }
    )
    assert result.executable == {"phase": [], "simulation": []}
    assert all("pseudocomponents" in m.limitations for m in result.methods)
    assert all(m.simulation.substitution is None for m in result.methods)


def test_routes_differ_and_say_so_wilson_vs_uniquac():
    result = select_thermo_model(
        {
            "is_polar": True,
            "is_electrolyte": False,
            "pressure_value": 1,
            "pressure_unit": "bar(a)",
            "interaction_parameters_available": True,
            "liquid_liquid_expected": False,
            "vapor_association_expected": False,
        }
    )
    by_id = {m.method: m for m in result.methods}
    assert by_id["WILSON"].phase.executable and not by_id["WILSON"].simulation.executable
    assert by_id["WILSON"].simulation.substitution.package == "NRTL"
    assert by_id["UNIQUAC"].simulation.executable and not by_id["UNIQUAC"].phase.executable
    assert by_id["UNIQUAC"].phase.substitution.method == "NRTL"
    assert by_id["NRTL"].phase.executable and by_id["NRTL"].simulation.executable


def test_high_pressure_polar_has_only_substitutions():
    result = select_thermo_model(
        {
            "is_polar": True,
            "is_electrolyte": False,
            "pressure_value": 50,
            "pressure_unit": "bar(a)",
            "interaction_parameters_available": False,
        }
    )
    assert result.executable == {"phase": [], "simulation": []}
    assert all("substitutions" in n for n in result.notes)


# -- phase.py: refusals, limitations, interaction parameter coverage -------------------------


def _flash(components, z, model, t=298.15, p=1.0, **kwargs):
    from chemeascode.domains.process.thermodynamics.phase import phase_determination

    return phase_determination(
        components=components,
        overall_composition=z,
        temperature_value=t,
        temperature_unit="K",
        pressure_value=p,
        pressure_unit="bar(a)",
        thermodynamic_model=model,
        allow_two_liquids=False,
        **kwargs,
    )


def test_phase_refuses_ions():
    pytest.importorskip("thermo")
    with pytest.raises(ValueError, match="electrolytes are not supported"):
        _flash(["Na+", "Cl-", "water"], [0.05, 0.05, 0.9], {"eos_model": "Peng-Robinson"})


def test_phase_refuses_pseudocomponents():
    pytest.importorskip("thermo")
    with pytest.raises(ValueError, match="pseudocomponents"):
        _flash(["C7+ fraction", "water"], [0.5, 0.5], {"eos_model": "Peng-Robinson"})


def test_phase_has_no_solid_phase_and_says_so():
    # water at 250 K and 1 bar is ice (melting point 273.15 K); the flash has no solid phase
    pytest.importorskip("thermo")
    result = _flash(["water"], None, {"eos_model": "Peng-Robinson"}, t=250.0)
    assert result.liquid_count == 1 and result.gas_count == 0
    assert any("no solid phase" in limitation for limitation in result.limitations)
    assert result.application_range.startswith("no range claimed")
    assert result.method == "PR"


def test_coverage_tells_sourced_missing_and_accepted_zero():
    pytest.importorskip("thermo")
    from thermo.interaction_parameters import IPDB

    from chemeascode.domains.process.thermodynamics.coverage import (
        interaction_parameter_coverage,
    )

    nrtl = {"liquid_phase_model": "NRTL", "vapor_phase_model": "ideal_gas"}
    found = interaction_parameter_coverage(
        ["ethanol", "water", "methane"], nrtl, accepted_zeros=[("methane", "water")]
    )
    status = {p.pair: p.status for p in found.pairs}
    assert status == {
        ("ethanol", "water"): "sourced",
        ("ethanol", "methane"): "missing",
        ("water", "methane"): "accepted_zero",
    }
    sourced = found.sourced[0]
    assert "ChemSep NRTL" in sourced.source
    # the reported values are thermo's own table entries, not computed here
    ethanol, water = "64-17-5", "7732-18-5"
    expected = [
        IPDB.get_ip_specific("ChemSep NRTL", [ethanol, water], "bij"),
        IPDB.get_ip_specific("ChemSep NRTL", [water, ethanol], "bij"),
    ]
    assert sourced.values["bij"] == expected
    assert "uses zero" in found.missing[0].note
    assert found.missing_note() and "ethanol / methane" in found.missing_note()


def test_coverage_accepts_cas_numbers_and_covers_the_vapour_eos():
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.coverage import (
        interaction_parameter_coverage,
    )

    model = {"liquid_phase_model": "Wilson", "vapor_phase_model": "Peng-Robinson"}
    found = interaction_parameter_coverage(
        ["ethanol", "water"], model, accepted_zeros=[("7732-18-5", "64-17-5")]
    )
    sets = {(p.parameter_set, p.status) for p in found.pairs}
    # Wilson has the pair; ChemSep PR has no ethanol/water kij, which the user accepted
    assert sets == {("Wilson", "sourced"), ("Peng-Robinson kij", "accepted_zero")}


def test_coverage_of_unifac_reports_group_pairs_and_unassigned_components():
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.coverage import (
        interaction_parameter_coverage,
    )

    model = {"liquid_phase_model": "UNIFAC", "vapor_phase_model": "ideal_gas"}
    found = interaction_parameter_coverage(["ethanol", "water", "methane"], model)
    assert {p.parameter_set for p in found.pairs} == {"UNIFAC groups"}
    assert all(p.status == "sourced" for p in found.pairs)
    assert any("methane: no UNIFAC groups" in n for n in found.notes)


def test_flash_result_carries_coverage_and_a_missing_note():
    pytest.importorskip("thermo")
    result = _flash(["ethanol", "water"], [0.5, 0.5], {"eos_model": "Peng-Robinson"})
    assert [p.status for p in result.interaction_parameters.pairs] == ["missing"]
    assert any("uses zero" in note for note in result.notes)
    accepted = _flash(
        ["ethanol", "water"],
        [0.5, 0.5],
        {"eos_model": "Peng-Robinson"},
        accepted_zeros=[("ethanol", "water")],
    )
    assert [p.status for p in accepted.interaction_parameters.pairs] == ["accepted_zero"]
    assert accepted.notes == []


def test_cli_phase_coverage_and_check(tmp_path, monkeypatch):
    pytest.importorskip("thermo")
    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(tmp_path)  # no plant repository needed
    args = ["process", "phase", "ethanol", "water", "--model", "Peng-Robinson"]
    shown = runner.invoke(app, [*args, "--check"])
    assert shown.exit_code == 1, shown.output
    assert "ethanol / water: missing" in shown.output
    accepted = runner.invoke(app, [*args, "--check", "--accept-zero", "ethanol:water"])
    assert accepted.exit_code == 0 and "accepted_zero" in accepted.output
    flashed = runner.invoke(
        app, [*args, "--z", "0.5,0.5", "--temperature", "298.15", "--pressure", "1", "--json"]
    )
    assert flashed.exit_code == 0, flashed.output
    data = json.loads(flashed.output)
    assert data["liquid_count"] == 1 and data["interaction_parameters"]["pairs"]
    refused = runner.invoke(app, ["process", "phase", "Na+", "water", "--model", "Peng-Robinson"])
    assert refused.exit_code == 2 and "electrolytes" in refused.output


def test_cli_methods_lists_routes_and_regimes():
    from chemeascode.interfaces.cli import app

    shown = runner.invoke(app, ["process", "methods"])
    assert shown.exit_code == 0
    assert "PR: Peng-Robinson; phase: yes" in shown.output
    assert "simulation range claimed: nitrogen, oxygen, argon (vapor" in shown.output  # PR
    assert "simulation range claimed: nitrogen, oxygen, argon, each alone (no mixture)" in (
        shown.output
    )  # SRK
    assert "LKP: Lee-Kesler-Plocker; phase: no, substitute PR" in shown.output
    assert "regime electrolytes: phase unsupported, simulation unsupported" in shown.output
    assert (
        "regime high_temperature_solid_reaction: phase unsupported, simulation unsupported, "
        "furnace limited" in shown.output
    )


# -- simulation: the property package against the contract and the recorded selection --------


@pytest.fixture
def plant(tmp_path):
    from chemeascode.foundation.workspace import Workspace

    shutil.copytree(EXAMPLES / "process-simulation", tmp_path / "plant")
    return Workspace(tmp_path / "plant")


def _edit(ws, edit) -> None:
    file = ws.root / "process/simulation.yaml"
    data = yaml.safe_load(file.read_text())
    edit(data)
    file.write_text(yaml.safe_dump(data, sort_keys=False))


def _translate(ws):
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.translate import load, translate

    process, _ = load_process(ws.root)
    sim, doc, found = load(ws.root)
    assert not found
    return translate(process, sim, doc, process.flowsheet.default_case())


def _rules(translation, rule):
    return [f for f in translation.findings if f.rule == f"cheme.process-{rule}"]


NONPOLAR = {"is_polar": False, "has_pseudocomponents": False}


def test_unsupported_package_is_refused(plant):
    _edit(plant, lambda d: d.update(property_package="Lee-Kesler-Plocker"))
    out = _translate(plant)
    [finding] = _rules(out, "sim-property-package")
    assert finding.level == "error" and out.model is None
    assert finding.file == "process/simulation.yaml" and finding.line
    assert "Peng-Robinson (PR)" in finding.hint


def test_recommended_package_passes_silently(plant):
    _edit(plant, lambda d: d.update(method_selection={"facts": NONPOLAR}))
    out = _translate(plant)
    assert out.model is not None
    assert not [f for f in out.findings if "method" in f.rule or "package" in f.rule]


def test_package_the_selection_did_not_recommend_is_flagged(plant):
    _edit(
        plant,
        lambda d: d.update(property_package="NRTL", method_selection={"facts": NONPOLAR}),
    )
    out = _translate(plant)
    [finding] = _rules(out, "sim-method-not-recommended")
    assert finding.level == "warning" and out.model is not None
    assert "nonpolar_no_pseudocomponents" in finding.message
    assert "Peng-Robinson (PR)" in finding.hint


def test_recorded_substitution_is_reported_not_hidden(plant):
    facts = {
        "is_polar": True,
        "is_electrolyte": False,
        "pressure_value": 50,
        "pressure_unit": "bar(a)",
        "interaction_parameters_available": True,
    }
    _edit(plant, lambda d: d.update(method_selection={"facts": facts}))
    [warning] = _rules(_translate(plant), "sim-method-not-recommended")
    assert "a substitution for" in warning.message
    _edit(
        plant,
        lambda d: d["method_selection"].update(substitution="nearest executable; accepted by AS"),
    )
    out = _translate(plant)
    [info] = _rules(out, "sim-method-substituted")
    assert info.level == "info" and "accepted by AS" in info.message
    assert "loses:" in info.message


def test_incomplete_selection_facts_are_a_warning(plant):
    _edit(plant, lambda d: d.update(method_selection={"facts": {"is_polar": True}}))
    [finding] = _rules(_translate(plant), "sim-method-selection")
    assert finding.level == "warning" and "is_electrolyte" in finding.message


def test_maturity_check_can_require_a_recorded_selection(plant):
    from chemeascode.domains.process.simulation.translate import (
        load,
        property_package_findings,
    )

    sim, doc, _ = load(plant.root)
    assert sim.method_selection is not None  # the example records one: nothing to report
    assert property_package_findings(sim, doc, require_selection=True) == []
    _edit(plant, lambda d: d.pop("method_selection"))
    sim, doc, _ = load(plant.root)
    assert property_package_findings(sim, doc) == []
    [finding] = property_package_findings(sim, doc, require_selection=True)
    assert finding.rule == "cheme.process-sim-method-unrecorded" and finding.level == "info"
