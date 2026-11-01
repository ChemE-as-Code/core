"""The electrolyte route: the NaCl-H2O claim of electrolytes.yml against
independent reference data, its refusals, and the refusal of electrolytes by the phase and
simulation routes.

Reference data (tests/data/electrolytes/nacl-h2o-reference.yaml): Hamer and Wu (1972), Table 16
(25 C, 0.001-6 mol/kg); Pitzer, Peiper and Busey (1984), Tables A-8, A-9 and A-13 (0-100 C, 1
and 200 bar, 0.1-6 mol/kg). The tolerances are the contract's (electrolytes.yml, with their
basis); the tests read them from there, so a looser contract cannot pass silently: each
benchmark also asserts the largest deviation found, for the record.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.thermodynamics import electrolytes as el
from chemeascode.domains.process.thermodynamics import methods

DATA = Path(__file__).parent / "data" / "electrolytes" / "nacl-h2o-reference.yaml"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REFERENCE = yaml.safe_load(DATA.read_text(encoding="utf-8"))
PPB = REFERENCE["pitzer_peiper_busey_1984"]
ATM = 101.325
R = 8.314462618  # J/(mol K)
runner = CliRunner()


def _needs_solver():
    pytest.importorskip("cantera")
    pytest.importorskip("chemicals")


def _system():
    return el.electrolyte_table().system("NaCl-H2O")


def _tolerance(name: str) -> float:
    return _system().tolerances[name]


# -- the contract ---------------------------------------------------------------------------------


def test_the_contract_is_versioned_and_complete():
    table = el.electrolyte_table()
    assert table.meta["version"] == 1
    system = _system()
    # charge: the species of the dissociation balance, and conserve the salt's elements
    charges = system.charges()
    assert sum(charges[s] * n for s, n in system.salt.dissociation.items()) == 0
    from_species: dict[str, int] = {}
    for s, n in system.salt.dissociation.items():
        for e, k in system.species_elements(s).items():
            from_species[e] = from_species.get(e, 0) + k * n
    assert from_species == system.salt.elements
    assert system.application_range.temperature_K == (273.15, 373.15)
    assert system.application_range.pressure_kPa == (None, 1000.0)
    assert system.application_range.molality_mol_per_kg == (0.0, 6.0)
    assert system.application_range.enthalpy_temperature_K == (313.15, 373.15)
    assert system.benchmark.test == "tests/test_electrolytes.py"
    assert "Silvester" in system.model.parameter_source
    # the method it executes says so, and the regime decision follows
    pitzer = methods.method_table().method(system.method)
    assert pitzer.electrolyte is not None and pitzer.electrolyte.systems == ["NaCl-H2O"]
    decision = methods.regime_decisions()["electrolytes"]
    assert decision.elsewhere["electrolyte"].status == "limited"
    assert decision.phase.status == decision.simulation.status == "unsupported"


def test_the_apparent_electrolytes_are_the_compounds_named():
    """Each CAS number of apparent_electrolytes is the compound its name says (chemicals)."""
    identifiers = pytest.importorskip("chemicals.identifiers")
    for entry in el.electrolyte_table().apparent_electrolytes:
        assert identifiers.CAS_from_any(entry.name) == entry.cas, entry.name
    assert {e.system for e in el.electrolyte_table().apparent_electrolytes} == {None, "NaCl-H2O"}


def test_the_module_imports_without_the_solver():
    code = (
        "import sys\n"
        "import chemeascode.domains.process.thermodynamics.electrolytes as el\n"
        "el.electrolyte_table()\n"
        "print(sorted(m for m in ('cantera', 'chemicals', 'thermo') if m in sys.modules))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


# -- the benchmark --------------------------------------------------------------------------------


def test_25C_against_hamer_and_wu():
    """gamma+- and phi at 298.15 K, 0.001-6 mol/kg, against Hamer and Wu (1972) Table 16."""
    _needs_solver()
    tol_g = _tolerance("ln_mean_activity_coefficient_abs")
    tol_phi = _tolerance("osmotic_coefficient_abs")
    worst_g = worst_phi = 0.0
    for m, (phi, gamma) in REFERENCE["hamer_wu_1972"]["rows"].items():
        state = el.electrolyte_state(298.15, ATM, molality=float(m))
        d_g = abs(math.log(state.mean_activity_coefficient / gamma))
        d_phi = abs(state.osmotic_coefficient - phi)
        assert d_g <= tol_g and d_phi <= tol_phi, (m, state.mean_activity_coefficient, gamma)
        worst_g, worst_phi = max(worst_g, d_g), max(worst_phi, d_phi)
    # for the record: far inside the tolerances at 25 C
    assert worst_g < 0.004 and worst_phi < 0.004


def _rows(table: str, pressure: str):
    for t_c, values in PPB[table][pressure].items():
        for m, value in zip(PPB["molalities"], values, strict=True):
            yield 273.15 + t_c, m, value


def test_0_to_100C_against_pitzer_peiper_busey():
    """gamma+- (Table A-8) and phi (Table A-9) at 1 bar, 0-100 C, 0.1-6 mol/kg."""
    _needs_solver()
    tol_g = _tolerance("ln_mean_activity_coefficient_abs")
    tol_phi = _tolerance("osmotic_coefficient_abs")
    worst = {"gamma": (0.0, None), "phi": (0.0, None)}
    for (t, m, gamma), (_, _, phi) in zip(
        _rows("activity_coefficient", "1 bar"), _rows("osmotic_coefficient", "1 bar"), strict=True
    ):
        state = el.electrolyte_state(t, ATM, molality=m)
        d_g = abs(math.log(state.mean_activity_coefficient / gamma))
        d_phi = abs(state.osmotic_coefficient - phi)
        assert d_g <= tol_g, (t, m, state.mean_activity_coefficient, gamma)
        assert d_phi <= tol_phi, (t, m, state.osmotic_coefficient, phi)
        worst["gamma"] = max(worst["gamma"], (d_g, (t, m)))
        worst["phi"] = max(worst["phi"], (d_phi, (t, m)))
    # the largest departures are at 0 C (tolerance_basis); 0.016 and 0.006
    assert worst["gamma"][1][0] == 273.15 and worst["gamma"][0] > 0.015
    assert worst["phi"][1][0] == 273.15


def test_relative_enthalpy_against_pitzer_peiper_busey():
    """phi_L/RT (Table A-13) at 1 bar, 40-100 C, within the reference's own uncertainty."""
    _needs_solver()
    tol = _tolerance("relative_apparent_molar_enthalpy_over_RT_abs")
    lo, hi = _system().application_range.enthalpy_temperature_K
    checked = 0
    for t, m, reference in _rows("relative_apparent_molar_enthalpy_over_RT", "1 bar"):
        state = el.electrolyte_state(t, ATM, molality=m)
        if not lo <= t <= hi:
            assert state.relative_apparent_molar_enthalpy_J_per_mol is None
            assert any("not claimed" in n for n in state.notes)
            continue
        value = state.relative_apparent_molar_enthalpy_J_per_mol / (R * t)
        assert abs(value - reference) <= tol, (t, m, value, reference)
        checked += 1
    assert checked == 7 * len(PPB["molalities"])


def test_relative_enthalpy_below_40C_is_rightly_not_claimed():
    """Why the enthalpy range starts at 313.15 K: below, the 1977 temperature functions miss
    the 1984 evaluation beyond its uncertainty (0.09 RT at 25 C, 0.65 RT at 0 C)."""
    _needs_solver()
    from chemeascode.integrations.cantera import hmw_state

    text = el.cantera_input(_system())
    tol = _tolerance("relative_apparent_molar_enthalpy_over_RT_abs")
    misses = {}
    for t, m, reference in _rows("relative_apparent_molar_enthalpy_over_RT", "1 bar"):
        if t >= 313.15:
            continue
        state = hmw_state(text, t, ATM * 1000, {"Na+": m, "Cl-": m})
        phi_l = sum(state["relative_enthalpies"][s] * n for s, n in state["amounts"].items()) / m
        misses[t] = max(misses.get(t, 0.0), abs(phi_l / (R * t) - reference))
    assert misses[298.15] > tol and misses[273.15] > 0.6
    assert misses[303.15] > tol  # 30 C misses too: the range starts at the next table row


def test_up_to_1000_kPa_against_the_tables_interpolated_in_pressure():
    """At 1000 kPa(a), against the reference interpolated linearly between 1 and 200 bar; and
    the pressure effect the range rests on (tolerance_basis) is what the tables say."""
    _needs_solver()
    tol_g = _tolerance("ln_mean_activity_coefficient_abs")
    tol_phi = _tolerance("osmotic_coefficient_abs")
    tol_l = _tolerance("relative_apparent_molar_enthalpy_over_RT_abs")
    w = (10.0 - 1.0) / (200.0 - 1.0)

    def at_10_bar(table):
        low, high = list(_rows(table, "1 bar")), list(_rows(table, "200 bar"))
        return [
            (t, m, a + w * (b - a), abs(b - a))
            for (t, m, a), (_, _, b) in zip(low, high, strict=True)
        ]

    gammas, phis = at_10_bar("activity_coefficient"), at_10_bar("osmotic_coefficient")
    enthalpies = at_10_bar("relative_apparent_molar_enthalpy_over_RT")
    assert round(max(d for *_, d in gammas), 6) <= 0.034
    assert round(max(d for *_, d in phis), 6) <= 0.012
    assert round(max(d for t, _, _, d in enthalpies if t >= 313.15), 6) <= 0.089
    for (t, m, gamma, _), (_, _, phi, _), (_, _, l_rt, _) in zip(
        gammas, phis, enthalpies, strict=True
    ):
        if t not in (273.15, 298.15, 323.15, 373.15):
            continue
        state = el.electrolyte_state(t, 1000.0, molality=m)
        assert abs(math.log(state.mean_activity_coefficient / gamma)) <= tol_g, (t, m)
        assert abs(state.osmotic_coefficient - phi) <= tol_phi, (t, m)
        if state.relative_apparent_molar_enthalpy_J_per_mol is not None:
            assert abs(state.relative_apparent_molar_enthalpy_J_per_mol / (R * t) - l_rt) <= tol_l


def test_closure_and_composition_bases_agree():
    _needs_solver()
    by_molality = el.electrolyte_state(323.15, ATM, molality=2.0)
    closure = by_molality.closure
    assert closure.closed and abs(closure.charge_mol_per_kg) < 1e-12
    assert closure.max_relative_deviation < 1e-12
    assert closure.elements["Na"] == pytest.approx((2.0, 2.0))
    assert closure.elements["O"][0] == pytest.approx(1000 / 18.015, rel=1e-4)  # mol water/kg
    assert by_molality.species_molalities == {"Na+": 2.0, "Cl-": 2.0}
    assert by_molality.ionic_strength_mol_per_kg == pytest.approx(2.0)
    # 2 mol/kg is 116.8856 g NaCl per 1116.8856 g solution
    assert by_molality.mass_fraction == pytest.approx(116.8856 / 1116.8856, rel=1e-12)
    by_mass = el.electrolyte_state(323.15, ATM, mass_fraction=by_molality.mass_fraction)
    by_species = el.electrolyte_state(323.15, ATM, species={"Na+": 2.0, "Cl-": 2.0})
    for other in (by_mass, by_species):
        assert other.molality_mol_per_kg == pytest.approx(2.0, rel=1e-12)
        assert other.mean_activity_coefficient == pytest.approx(
            by_molality.mean_activity_coefficient, rel=1e-10
        )
    assert by_mass.composition_basis == "mass_fraction"
    assert by_species.composition_basis == "species"
    # the phase output: the water vapour pressure is a_w times IAPWS-95's (101.418 kPa at
    # 373.15 K, IAPWS-95 release)
    hot = el.electrolyte_state(373.15, ATM, molality=1.0)
    assert hot.pure_water_vapour_pressure_kPa == pytest.approx(101.418, abs=0.001)
    assert hot.water_vapour_pressure_kPa == pytest.approx(
        hot.water_activity * hot.pure_water_vapour_pressure_kPa
    )
    # a_w from phi: ln a_w = -2 m M_w phi
    assert math.log(hot.water_activity) == pytest.approx(
        -2 * 1.0 * 0.018015 * hot.osmotic_coefficient, rel=1e-4
    )


def test_standard_states_do_not_enter_the_results():
    """The species' standard states are zero in the input; arbitrary ones give the same excess
    and relative properties."""
    _needs_solver()
    from chemeascode.integrations.cantera import hmw_state

    text = el.cantera_input(_system())
    other = text.replace("h0: 0.0", "h0: -123456.0").replace("s0: 0.0", "s0: 42.0")
    other = other.replace("cp0: 0.0", "cp0: 77.0").replace(
        "molar-volume: 0.0", "molar-volume: 0.01"
    )
    assert other != text
    for t in (283.15, 333.15):
        a = hmw_state(text, t, 2e5, {"Na+": 3.0, "Cl-": 3.0})
        b = hmw_state(other, t, 2e5, {"Na+": 3.0, "Cl-": 3.0})
        for key in ("activities", "relative_enthalpies"):
            for s in a[key]:
                assert b[key][s] == pytest.approx(a[key][s], rel=1e-8, abs=1e-6), (key, s)


def test_another_solver_version_is_noted(monkeypatch):
    _needs_solver()
    monkeypatch.setattr(el.electrolyte_table().route, "solver_version", "0.0.1")
    state = el.electrolyte_state(323.15, ATM, molality=1.0)
    assert any("not the version benchmarked" in n for n in state.notes)


# -- refusals -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "rule", "text"),
    [
        ({"molality": 6.5}, "range", "outside (0, 6]"),
        ({"molality": 0.0}, "range", "outside (0, 6]"),
        ({"molality": 1.0, "temperature_K": 380.0}, "range", "outside 273.15-373.15 K"),
        ({"molality": 1.0, "temperature_K": 268.15}, "range", "outside 273.15-373.15 K"),
        ({"molality": 1.0, "pressure_kPa": 1500.0}, "range", "outside 0-1000 kPa(a)"),
        ({"mass_fraction": 1.2}, "composition", "not between 0 and 1"),
        ({}, "composition", "give one composition"),
        ({"molality": 1.0, "mass_fraction": 0.05}, "composition", "give one composition"),
        ({"species": {"Na+": 1.0, "Cl-": 0.9}}, "charge-balance", "not electroneutral"),
        ({"species": {"Na+": 1.0, "K+": 1.0, "Cl-": 2.0}}, "unsupported", "K+"),
        ({"species": {"H+": 1.0, "Cl-": 1.0}}, "unsupported", "H+"),
        ({"molality": 1.0, "system": "H2SO4-H2O"}, "system", "no electrolyte system"),
    ],
)
def test_outside_the_contract_is_refused(kwargs, rule, text):
    """Refused before the solver runs (no extra needed), naming the rule and a hint."""
    args = {"temperature_K": 298.15, "pressure_kPa": ATM, **kwargs}
    with pytest.raises(el.ElectrolyteError, match=re.escape(text)) as refused:
        el.electrolyte_state(args.pop("temperature_K"), args.pop("pressure_kPa"), **args)
    assert refused.value.rule == f"cheme.process-electrolyte-{rule}"
    assert refused.value.hint


def test_a_boiling_solution_is_refused():
    _needs_solver()
    with pytest.raises(el.ElectrolyteError, match="boils") as refused:
        el.electrolyte_state(373.15, ATM, molality=0.001)  # p_w 101.41 kPa(a)
    assert refused.value.rule == "cheme.process-electrolyte-phase"
    el.electrolyte_state(373.15, ATM, molality=0.1)  # p_w 101.08 kPa(a): liquid


def test_the_phase_route_refuses_salt_in_water():
    """thermo would flash NaCl as a neutral molecule: refused, pointing at the electrolyte
    route; ions stay refused."""
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.coverage import (
        interaction_parameter_coverage,
    )

    with pytest.raises(ValueError, match="electrolytes are not supported") as refused:
        interaction_parameter_coverage(["water", "sodium chloride"], {"eos_model": "Peng-Robinson"})
    assert "sodium chloride with water" in str(refused.value)
    assert "cheme process electrolyte" in str(refused.value)
    with pytest.raises(ValueError, match="no route models this electrolyte"):
        interaction_parameter_coverage(
            ["water", "sulfuric acid"],
            {"liquid_phase_model": "NRTL", "vapor_phase_model": "ideal_gas"},
        )
    # beyond the list, by formula: lithium bromide (an absorption chiller's brine)
    with pytest.raises(ValueError, match=r"lithium bromide \(BrLi\) with water"):
        interaction_parameter_coverage(["water", "lithium bromide"], {"eos_model": "Peng-Robinson"})
    # without water, an apparent electrolyte is no dissolved electrolyte
    assert el.dissolved_electrolytes(["7647-01-0", "7782-50-5"]) == []


def test_salts_beyond_the_list_are_found_by_formula():
    water = el.WATER_CAS
    found = el.dissolved_electrolytes(
        [water, "1302-42-7", "584-08-7", "67-56-1"],
        {"1302-42-7": "NaAlO2", "584-08-7": "K2CO3", "67-56-1": "CH4O", water: "H2O"},
        {"1302-42-7": "sodium aluminate"},
    )
    assert [(e.cas, e.name, e.system) for e in found] == [
        ("1302-42-7", "sodium aluminate (NaAlO2)", None),
        ("584-08-7", "K2CO3 (K2CO3)", None),
    ]
    # a listed one keeps its entry (and its system); none without water or without a formula
    [nacl] = el.dissolved_electrolytes([water, "7647-14-5"], {"7647-14-5": "NaCl"})
    assert nacl.system == "NaCl-H2O"
    assert el.dissolved_electrolytes(["584-08-7"], {"584-08-7": "K2CO3"}) == []
    assert el.dissolved_electrolytes([water, "584-08-7"]) == []


def test_the_simulation_route_refuses_salt_in_water(tmp_path):
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.translate import load, translate

    shutil.copytree(EXAMPLES / "process-simulation", tmp_path / "plant")
    materials = tmp_path / "plant/process/materials.yaml"
    text = materials.read_text(encoding="utf-8")
    # the example's components, re-identified as water and sodium chloride
    text = text.replace("cas: 7782-44-7", "cas: 7732-18-5").replace(
        "cas: 7440-37-1", "cas: 7647-14-5"
    )
    materials.write_text(text, encoding="utf-8")
    process, _ = load_process(tmp_path / "plant")
    sim, doc, found = load(tmp_path / "plant")
    assert not found
    out = translate(process, sim, doc, process.flowsheet.default_case())
    [finding] = [f for f in out.findings if f.rule == "cheme.process-sim-electrolyte"]
    assert finding.level == "error" and out.model is None
    assert finding.file == "process/simulation.yaml" and finding.line
    assert finding.ids == ["AR"] and "neutral molecule" in finding.message
    assert "cheme process electrolyte" in finding.hint
    # a salt the list does not name is found by its formula in materials.yaml
    text = materials.read_text(encoding="utf-8").replace("cas: 7647-14-5", "cas: 584-08-7")
    materials.write_text(text.replace("formula: Ar,", "formula: K2CO3,"), encoding="utf-8")
    process, _ = load_process(tmp_path / "plant")
    out = translate(process, sim, doc, process.flowsheet.default_case())
    [finding] = [f for f in out.findings if f.rule == "cheme.process-sim-electrolyte"]
    assert finding.ids == ["AR"] and "(K2CO3) with water" in finding.message
    assert "no route models this electrolyte" in finding.hint


# -- model selection and the CLI ------------------------------------------------------------------


def test_the_electrolyte_recommendation_names_the_route():
    from chemeascode.domains.process.thermodynamics.model_selection import select_thermo_model

    result = select_thermo_model({"is_polar": True, "is_electrolyte": True})
    assert result.executable == {"phase": [], "simulation": []}
    pitzer = next(m for m in result.methods if m.method == "PITZER-RKS")
    assert pitzer.electrolyte.systems == ["NaCl-H2O"]
    [note] = [n for n in result.notes if "electrolyte route" in n]
    assert "NaCl-H2O only" in note


def test_cli_matches_the_function_and_refuses_with_exit_3():
    from chemeascode.interfaces.cli import app

    refused = runner.invoke(
        app, ["process", "electrolyte", "--temperature", "25", "--temperature-unit", "°C",
              "--pressure", "1", "--molality", "7"],
    )  # fmt: skip
    assert refused.exit_code == 3
    assert "refused cheme.process-electrolyte-range" in refused.output
    pytest.importorskip("cantera")
    pytest.importorskip("chemicals")
    shown = runner.invoke(
        app, ["process", "electrolyte", "--temperature", "50", "--temperature-unit", "°C",
              "--pressure", "101.325", "--pressure-unit", "kPa(a)", "--species", "Na+=3,Cl-=3",
              "--json"],
    )  # fmt: skip
    assert shown.exit_code == 0, shown.output
    data = json.loads(shown.output)
    direct = el.electrolyte_state(323.15, ATM, species={"Na+": 3.0, "Cl-": 3.0})
    assert data == json.loads(direct.model_dump_json())
    text = runner.invoke(
        app, ["process", "electrolyte", "--temperature", "323.15", "--pressure", "1",
              "--molality", "3"],
    )  # fmt: skip
    assert text.exit_code == 0
    assert "mean activity coefficient (molality scale)" in text.output
    assert "method PITZER-RKS" in text.output
    methods_out = runner.invoke(app, ["process", "methods"])
    assert "electrolyte route: NaCl-H2O only" in methods_out.output
    assert (
        "regime electrolytes: phase unsupported, simulation unsupported, electrolyte limited"
        in (methods_out.output)
    )
