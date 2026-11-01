"""Ideal-gas thermochemistry, chemical equilibrium, equilibrium and Gibbs reactors in cheme process
propagate, the reactor rules and cheme process reactors."""

import math
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.chemistry.equilibrium import NotConverged, equilibrate
from chemeascode.domains.chemistry.thermochemistry import (
    IdealGas,
    R,
    independent_reactions,
    inert_species,
    ln_k,
    reaction_enthalpy,
)
from chemeascode.domains.equipment.fill import fill_datasheets
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.datasheets import draft_missing

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

#: chemicals 1.5.2 (ATcT dHf, CRC S0, Poling Cp/R, 50-1000 K), as cheme chemistry thermo prints.
DATA = {
    "CO": IdealGas(
        dHf_298=-110525.0,
        S_298=197.7,
        cp_R=[3.912, -0.003913, 1.182e-05, -1.3e-08, 5.15e-12],
        temperature_range=(50, 1000),
    ),
    "H2O": IdealGas(
        dHf_298=-241822.0,
        S_298=188.8,
        cp_R=[4.395, -0.004186, 1.405e-05, -1.564e-08, 6.32e-12],
        temperature_range=(50, 1000),
    ),
    "CO2": IdealGas(
        dHf_298=-393474.0,
        S_298=213.8,
        cp_R=[3.259, 0.001356, 1.502e-05, -2.374e-08, 1.056e-11],
        temperature_range=(50, 1000),
    ),
    "H2": IdealGas(
        dHf_298=0.0,
        S_298=130.7,
        cp_R=[2.883, 0.003681, -7.72e-06, 6.92e-09, -2.13e-12],
        temperature_range=(50, 1000),
    ),
    "CH4": IdealGas(
        dHf_298=-74534.0,
        S_298=186.3,
        cp_R=[4.568, -0.008975, 3.631e-05, -3.407e-08, 1.091e-11],
        temperature_range=(50, 1000),
    ),
}
WGS = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
SMR = {"CH4": -1, "H2O": -1, "CO": 1, "H2": 3}
FORMULAS = {"CO": "CO", "H2O": "H2O", "CO2": "CO2", "H2": "H2", "CH4": "CH4", "AR": "Ar"}


# -- thermochemistry ----------------------------------------------------------------------------


def test_reference_state_and_pressure():
    co = DATA["CO"]
    assert co.enthalpy(298.15) == pytest.approx(-110525.0)
    assert co.entropy(298.15) == pytest.approx(197.7)
    assert co.entropy(298.15, 1000.0) == pytest.approx(197.7 - 8.314462618 * math.log(10))
    assert co.cp(298.15) == pytest.approx(29.1, rel=0.01)  # NIST WebBook 29.14 J/(mol K)


def test_water_gas_shift_against_twigg():
    # Twigg, Catalyst Handbook (2nd ed.), the shift equilibrium correlation
    t = 1000.0
    twigg = math.exp(
        5693.5 / t + 1.077 * math.log(t) + 5.44e-4 * t - 1.125e-7 * t**2 - 49170 / t**2 - 13.148
    )
    assert math.exp(ln_k(WGS, DATA, t)) == pytest.approx(twigg, rel=0.03)
    assert reaction_enthalpy(WGS, DATA, 298.15) == pytest.approx(-41127.0)


def test_ammonia_kp_at_450_c():
    data = {
        "N2": IdealGas(
            dHf_298=0.0, S_298=191.6, cp_R=[3.539, -0.000261, 7e-08, 1.57e-09, -9.9e-13]
        ),
        "H2": DATA["H2"],
        "NH3": IdealGas(
            dHf_298=-45558.0,
            S_298=192.8,
            cp_R=[4.238, -0.004215, 2.041e-05, -2.126e-08, 7.61e-12],
        ),
    }
    # Gillespie and Beattie (1930): Kp of 1/2 N2 + 3/2 H2 = NH3 at 450 C about 6.5e-3 atm^-1
    kp = math.exp(ln_k({"N2": -0.5, "H2": -1.5, "NH3": 1}, data, 723.15))
    assert 6.0e-3 < kp < 7.0e-3


def test_independent_reactions_balance_the_elements():
    species = ["CH4", "H2O", "CO", "CO2", "H2", "AR"]
    basis = independent_reactions(species, FORMULAS)
    assert len(basis) == 2  # 6 species, 3 elements of the reacting ones + Ar alone
    for reaction in basis:
        assert "AR" not in reaction
        for element in ("C", "H", "O"):
            atoms = {"CH4": {"C": 1, "H": 4}, "H2O": {"H": 2, "O": 1}, "CO": {"C": 1, "O": 1}}
            atoms |= {"CO2": {"C": 1, "O": 2}, "H2": {"H": 2}}
            assert sum(nu * atoms[n].get(element, 0) for n, nu in reaction.items()) == 0
    with pytest.raises(ValueError, match="formula"):
        independent_reactions(["CH4", "X"], FORMULAS)


def test_ideal_gas_range_must_be_ordered():
    with pytest.raises(ValueError, match="min < max"):
        IdealGas(dHf_298=0, S_298=1, cp_R=[2.5], temperature_range=(500, 300))


# -- equilibrium --------------------------------------------------------------------------------


def _k_of(out, reaction, pressure):
    total = sum(out.values())
    return sum(nu * math.log(out[n] / total * pressure / 100.0) for n, nu in reaction.items())


def test_reforming_equilibrium_satisfies_both_constants_and_the_elements():
    t, p = 900.0, 100.0
    feed = {"CH4": 1.0, "H2O": 3.0}
    ks = [ln_k(SMR, DATA, t), ln_k(WGS, DATA, t)]
    out, xi = equilibrate([SMR, WGS], ks, feed, p)
    assert _k_of(out, SMR, p) == pytest.approx(ks[0], abs=1e-6)
    assert _k_of(out, WGS, p) == pytest.approx(ks[1], abs=1e-6)
    carbon = out["CH4"] + out["CO"] + out["CO2"]
    hydrogen = 4 * out["CH4"] + 2 * out["H2O"] + 2 * out["H2"]
    oxygen = out["H2O"] + out["CO"] + 2 * out["CO2"]
    assert (carbon, hydrogen, oxygen) == pytest.approx((1.0, 10.0, 3.0))
    # a dependent third reaction changes nothing
    overall = {"CH4": -1, "H2O": -2, "CO2": 1, "H2": 4}
    again, _ = equilibrate([SMR, WGS, overall], [*ks, ks[0] + ks[1]], feed, p)
    assert again == pytest.approx(out, rel=1e-6)


def test_pressure_shifts_the_equilibrium():
    t = 900.0
    ks = [ln_k(SMR, DATA, t), ln_k(WGS, DATA, t)]
    low, _ = equilibrate([SMR, WGS], ks, {"CH4": 1.0, "H2O": 3.0}, 100.0)
    high, _ = equilibrate([SMR, WGS], ks, {"CH4": 1.0, "H2O": 3.0}, 3000.0)
    assert high["CH4"] > low["CH4"]  # Le Chatelier: more moles on the product side


def test_empty_feed_is_refused():
    with pytest.raises(NotConverged):
        equilibrate([WGS], [0.0], {}, 100.0)


# -- the flowsheet ------------------------------------------------------------------------------


def _ig(name):
    d = DATA[name]
    return (
        f"{{dHf_298: {d.dHf_298}, S_298: {d.S_298}, cp_R: {d.cp_R}, "
        f"temperature_range: [50, 1000], provenance: given}}"
    )


MATERIALS = f"""\
schema: cheme/process/v1
kind: materials
components:
  - {{id: CH4, name: Methane, formula: CH4, molar_mass: 16.043, ideal_gas: {_ig("CH4")}}}
  - {{id: H2O, name: Water, formula: H2O, molar_mass: 18.015, ideal_gas: {_ig("H2O")}}}
  - {{id: CO, name: Carbon monoxide, formula: CO, molar_mass: 28.010, ideal_gas: {_ig("CO")}}}
  - {{id: CO2, name: Carbon dioxide, formula: CO2, molar_mass: 44.009, ideal_gas: {_ig("CO2")}}}
  - {{id: H2, name: Hydrogen, formula: H2, molar_mass: 2.016, ideal_gas: {_ig("H2")}}}
  - {{id: AR, name: Argon, formula: Ar, molar_mass: 39.948}}
templates:
  - {{id: gas, components: [CH4, H2O, CO, CO2, H2, AR]}}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: SMR, stoichiometry: {CH4: -1, H2O: -1, CO: 1, H2: 3}, reversible: true}
  - {id: WGS, stoichiometry: {CO: -1, H2O: -1, CO2: 1, H2: 1}, reversible: true,
     heat_of_reaction: {value: -41127, provenance: given}}
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
    reactions: [SMR, WGS]
    reactor: equilibrium
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: gas
    state:
      design:
        temperature: {value: 700, provenance: given}
        pressure: {value: 100, provenance: given}
        flow: {value: 100, provenance: given}
        composition:
          basis: mole_fraction
          values: {CH4: 0.24, H2O: 0.72, AR: 0.04}
          provenance: given
  - id: S2
    from: R.out
    to: P.in
    template: gas
    state:
      design:
        temperature: {value: 900, provenance: assumed}
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, reactions=REACTIONS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: equilibrium-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(reactions)
    return Workspace(root)


def _fill(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return run(ws, process, "design", write=True)


def _outlet(ws):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return data["streams"][1]["state"]["design"]


def _rules(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def test_equilibrium_reactor_is_solved_and_balances(tmp_path):
    ws = _plant(tmp_path)
    result = _fill(ws)
    assert result.written == 1, [f.format() for f in result.findings]
    comp = _outlet(ws)["composition"]
    assert comp["source"] == "cheme process propagate: reactor R from S1"
    expected, _ = equilibrate(
        [SMR, WGS],
        [ln_k(SMR, DATA, 900.0), ln_k(WGS, DATA, 900.0)],
        {"CH4": 24, "H2O": 72, "AR": 4},
        100.0,
    )
    total = sum(expected.values())
    assert comp["values"]["H2"] == pytest.approx(expected["H2"] / total, rel=1e-5)
    assert not [f for f in _rules(ws) if f.level == "error"], [f.format() for f in _rules(ws)]
    # a different outlet temperature makes the outlet stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "value: 900, provenance: assumed", "value: 950, provenance: assumed"
        )
    )
    assert any(f.rule == "cheme.process-calculated-stale" for f in _rules(ws))


def test_gibbs_reactor_matches_the_equilibrium_of_its_independent_reactions(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace(
            "    reactions: [SMR, WGS]\n    reactor: equilibrium\n", "    reactor: gibbs\n"
        ),
    )
    assert _fill(ws).written == 1
    gibbs = _outlet(ws)["composition"]["values"]
    other = _plant(tmp_path / "eq")
    _fill(other)
    assert gibbs == pytest.approx(_outlet(other)["composition"]["values"], rel=1e-4, abs=1e-9)


GIBBS = FLOWSHEET.replace(
    "    reactions: [SMR, WGS]\n    reactor: equilibrium\n", "    reactor: gibbs\n"
)
#: Argon: Cp/R 2.5, NIST WebBook S 154.8 kJ/(kmol K).
ARGON = "{dHf_298: 0.0, S_298: 154.8, cp_R: [2.5], provenance: given, source: NIST WebBook}"


def _basis(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return next(u for u in model_bases(process) if u.id == "R")


def _reactor(ws):
    return next(r for r in reactor_report(ws.root).reactors if r["node"] == "R")


def test_inert_species_take_part_in_no_independent_reaction():
    assert inert_species(["CH4", "H2O", "CO", "CO2", "H2", "AR"], FORMULAS) == ["AR"]
    formulas = FORMULAS | {"N2": "N2", "NO": "NO"}
    assert inert_species(["N2", "CO", "H2O", "CO2", "H2"], formulas) == ["N2"]
    assert inert_species(["N2", "NO", "CO", "H2O", "CO2", "H2"], formulas) == []  # N2 reacts
    with pytest.raises(ValueError, match="formula"):
        inert_species(["CH4", "X"], FORMULAS)


def test_gibbs_reactor_with_an_inert_without_formation_data_solves_and_is_sourced(tmp_path):
    # argon has no ideal_gas data, the reacting species have sourced data
    ws = _plant(tmp_path, GIBBS)
    before = _basis(ws)  # the outlet is not calculated yet: the templates name the components
    assert (before.basis, before.sourced) == ("equilibrium", True), before.detail
    assert _fill(ws).written == 1
    assert _outlet(ws)["composition"]["values"]["AR"] > 0
    unit = _basis(ws)
    assert (unit.basis, unit.predictive, unit.sourced) == ("equilibrium", True, True), unit.detail
    assert "inert, in no independent reaction: AR" in unit.detail
    assert any(a.startswith("ASSUMED: AR (inert)") for a in unit.assumptions)
    # the duty counts every species but argon, whose sensible heat is left out, ASSUMED
    bare = _reactor(ws)
    assert bare["duty_kW"] is not None, bare["missing"]
    assert len(bare["duty_assumptions"]) == 1 and "inert AR" in bare["duty_assumptions"][0]
    # with argon's heat capacity its sensible heat is counted: 4 kmol/h from 700 to 900 K
    # (to the rounding of the written compositions)
    given = _plant(tmp_path / "argon", GIBBS)
    (given.root / "process/materials.yaml").write_text(
        MATERIALS.replace("molar_mass: 39.948}", f"molar_mass: 39.948, ideal_gas: {ARGON}}}")
    )
    _fill(given)
    assert not any(a.startswith("ASSUMED") for a in _basis(given).assumptions)
    counted = _reactor(given)
    assert counted["duty_assumptions"] == []
    sensible = 4.0 * 2.5 * R * (900.0 - 700.0) / 3600.0
    assert counted["duty_kW"] - bare["duty_kW"] == pytest.approx(sensible, rel=1e-4)


def test_reactor_datasheet_marks_the_duty_without_an_inert_sensible_heat(tmp_path):
    ws = _plant(
        tmp_path,
        GIBBS.replace(
            "    reactor: gibbs\n",
            "    reactor: gibbs\n    links: [{target: equipment, ref: R-1}]\n",
        ),
    )
    _fill(ws)
    (ws.root / "equipment").mkdir()
    (ws.root / "equipment/equipment-list.yaml").write_text(
        "equipment:\n  - {tag: R-1, type: PressureVessel}\n"
    )
    draft_missing(ws.root)
    fill_datasheets(ws.root, ["R-1"])
    sheet = yaml.safe_load((ws.root / "equipment/datasheets/R-1.yaml").read_text())
    duty = sheet["type_specific"]["duty_kw"]
    assert duty["value"] == pytest.approx(_reactor(ws)["duty_kW"], rel=1e-3)
    assert "ASSUMED: the sensible heat of inert AR is left out" in duty["source"]


def test_gibbs_reactor_with_a_reacting_species_without_formation_data_is_blocked(tmp_path):
    ws = _plant(tmp_path, GIBBS)
    (ws.root / "process/materials.yaml").write_text(
        MATERIALS.replace(f", ideal_gas: {_ig('CO2')}", "")
    )
    found = [f for f in _fill(ws).findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "no ideal_gas data for CO2" in found[0].message
    assert "composition" not in _outlet(ws)
    unit = _basis(ws)
    assert not unit.sourced and "no ideal-gas data for CO2" in unit.detail
    assert unit.detail.endswith(": no ideal-gas data for CO2")  # the inert is not asked for


def test_approach_lowers_the_conversion_of_an_endothermic_reaction(tmp_path):
    ws = _plant(tmp_path)
    _fill(ws)
    plain = _outlet(ws)["composition"]["values"]["CH4"]
    slow = _plant(
        tmp_path / "slow",
        FLOWSHEET.replace(
            "    reactor: equilibrium\n", "    reactor: equilibrium\n    approach: -30\n"
        ),
    )
    _fill(slow)
    assert _outlet(slow)["composition"]["values"]["CH4"] > plain


def test_missing_temperature_and_data_are_reported(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace(
            "        temperature: {value: 900, provenance: assumed}\n",
            "        pressure: {value: 100, provenance: assumed}\n",
        ),
    )
    found = [f for f in _fill(ws).findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "outlet temperature" in found[0].message
    ws = _plant(
        tmp_path / "hot",
        FLOWSHEET.replace("value: 900, provenance: assumed", "value: 1100, provenance: assumed"),
    )
    found = [f for f in _fill(ws).findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "temperature_range" in found[0].message


def test_reactor_rules(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace("    reactor: equilibrium\n", "    reactor: gibbs\n    approach: 5\n"),
    )
    assert any(f.rule == "cheme.process-reactor" and "Gibbs" in f.message for f in _rules(ws))
    ws = _plant(
        tmp_path / "a",
        reactions=REACTIONS.replace("reversible: true,\n", "\n", 1).replace(
            "{CO: -1, H2O: -1, CO2: 1, H2: 1}, reversible: true", "{CO: -1, H2O: -1, CO2: 1, H2: 1}"
        ),
    )
    assert any(
        f.rule == "cheme.process-reactor" and f.level == "warning" and "irreversible" in f.message
        for f in _rules(ws)
    )
    ws = _plant(tmp_path / "b", FLOWSHEET.replace("reactor: equilibrium", "reactor: conversion"))
    assert any(
        f.rule == "cheme.process-reactor" and "without a conversion" in f.message
        for f in _rules(ws)
    )
    ws = _plant(tmp_path / "c", FLOWSHEET.replace("    reactions: [SMR, WGS]\n", ""))
    assert any(
        f.rule == "cheme.process-reactor" and "names no reactions" in f.message for f in _rules(ws)
    )
    ws = _plant(
        tmp_path / "d", FLOWSHEET.replace("    reactor: equilibrium\n", "    approach: 5\n")
    )
    assert any(f.rule == "cheme.process-reactor" and "approach" in f.message for f in _rules(ws))


def test_heat_of_reaction_is_checked_against_the_formation_data(tmp_path):
    ws = _plant(tmp_path)
    assert not [f for f in _rules(ws) if f.rule == "cheme.process-heat-of-reaction"]
    ws = _plant(tmp_path / "x", reactions=REACTIONS.replace("value: -41127", "value: -50000"))
    found = [f for f in _rules(ws) if f.rule == "cheme.process-heat-of-reaction"]
    assert found and found[0].file == "process/reactions.yaml" and found[0].line


# -- cheme process reactors ---------------------------------------------------------------------


def test_reactor_report_of_the_ammonia_example(tmp_path):
    root = tmp_path / "nh3"
    shutil.copytree(EXAMPLES / "process-ammonia", root, ignore=shutil.ignore_patterns("build"))
    report = reactor_report(root)
    r1 = next(r for r in report.reactors if r["node"] == "R1")
    assert r1["model"] == "equilibrium" and r1["approach_K"] == 20
    reaction = r1["reactions"][0]
    assert reaction["ln_q_over_k"] == pytest.approx(0.0, abs=1e-3)  # at equilibrium
    assert reaction["heat_of_reaction_kJ_kmol"] == pytest.approx(-105477, rel=1e-3)
    assert r1["duty_kW"] < 0  # heat removed
    loop = next(r for r in report.reactors if r["node"] == "LOOP")
    assert loop["model"] is None and loop["missing"]


def test_reactors_cli(tmp_path, monkeypatch):
    root = tmp_path / "nh3"
    shutil.copytree(EXAMPLES / "process-ammonia", root, ignore=shutil.ignore_patterns("build"))
    monkeypatch.chdir(root)
    shown = CliRunner().invoke(app, ["process", "reactors"])
    assert shown.exit_code == 0, shown.output
    assert "step R1 (equilibrium)" in shown.output and "duty" in shown.output
    as_json = CliRunner().invoke(app, ["process", "reactors", "--json"])
    assert '"duty_kW"' in as_json.output


def test_thermo_cli_prints_ideal_gas_data():
    pytest.importorskip("chemicals")
    shown = CliRunner().invoke(app, ["chemistry", "thermo", "ammonia", "argon"])
    assert shown.exit_code == 0, shown.output
    assert "dHf_298: -45558.0" in shown.output and "cp_R: [2.5]" in shown.output
    entry = yaml.safe_load(shown.output.splitlines()[1])["ideal_gas"]
    IdealGas.model_validate(entry)
    wide = CliRunner().invoke(app, ["chemistry", "thermo", "methane", "--fit", "298.15,1500"])
    assert "temperature_range: [298.15, 1500]" in wide.output and "fitted" in wide.output
    assert CliRunner().invoke(app, ["chemistry", "thermo", "nosuchthing"]).exit_code == 1


# -- review fixes -------------------------------------------------------------------------------


@pytest.mark.parametrize("ln_k_value", [-60.0, -20.0, 0.0, 20.0, 60.0])
def test_equilibrium_converges_over_the_whole_range_and_balances_exactly(ln_k_value):
    syn = {"N2": -1, "H2": -3, "NH3": 2}
    out, _ = equilibrate([syn], [ln_k_value], {"N2": 1.0, "H2": 3.0}, 100.0)
    assert out["N2"] + out["NH3"] / 2 == pytest.approx(1.0, abs=1e-12)
    assert out["H2"] + 1.5 * out["NH3"] == pytest.approx(3.0, abs=1e-12)
    assert out["N2"] <= 1.0 and out["H2"] <= 3.0


def test_outlet_flow_is_written_even_when_the_composition_cannot_be(tmp_path):
    text = FLOWSHEET.replace(
        "        temperature: {value: 900, provenance: assumed}\n",
        "        pressure: {value: 100, provenance: assumed}\n",
    )
    ws = _plant(tmp_path, text)
    result = _fill(ws)
    assert any(f.rule == "cheme.process-propagate-reactor" for f in result.findings)
    assert _outlet(ws)["flow"]["provenance"] == "calculated" and "composition" not in _outlet(ws)


def test_a_given_outlet_composition_is_not_solved_again(tmp_path):
    text = FLOWSHEET.replace(
        "        temperature: {value: 900, provenance: assumed}\n",
        "        composition: {basis: mole_fraction, values: {CH4: 0.1, H2O: 0.5, CO: 0.1, "
        "CO2: 0.05, H2: 0.21, AR: 0.04}, provenance: assumed}\n",
    )
    ws = _plant(tmp_path, text)
    result = _fill(ws)
    assert not [f for f in result.findings if f.rule == "cheme.process-propagate-reactor"]


def test_a_gauge_outlet_pressure_falls_back_to_the_inlet(tmp_path):
    text = FLOWSHEET.replace(
        "        temperature: {value: 900, provenance: assumed}\n",
        "        temperature: {value: 900, provenance: assumed}\n"
        "        pressure: {value: 0, unit: kPa(g), provenance: assumed}\n",
    )
    ws = _plant(tmp_path, text)
    assert _fill(ws).written == 1
    report = reactor_report(ws.root)
    assert report.reactors[0]["pressure_out_kPa"] == 100


def test_gas_and_liquid_reactions_are_not_taken_to_one_equilibrium(tmp_path):
    ws = _plant(
        tmp_path,
        reactions=REACTIONS.replace("reversible: true}", "reversible: true, phase: liquid}", 1),
    )
    # one liquid reaction among gas ones, and without a liquid equilibrium constant
    messages = [f.message for f in _rules(ws) if f.rule == "cheme.process-reactor"]
    assert any("gas-phase and liquid-phase reactions together" in m for m in messages)
    found = [f for f in _fill(ws).findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "not both" in found[0].message


def test_heat_check_does_not_extrapolate(tmp_path):
    ws = _plant(
        tmp_path,
        reactions=REACTIONS.replace(
            "value: -41127, provenance: given",
            "value: -50000, temperature: 1200, provenance: given",
        ),
    )
    assert not [f for f in _rules(ws) if f.rule == "cheme.process-heat-of-reaction"]


def test_equilibrium_constant_range_must_be_ordered():
    from chemeascode.domains.chemistry.reactions import EquilibriumConstant

    with pytest.raises(ValueError, match="min < max"):
        EquilibriumConstant(a=1, temperature_range=(900, 600), provenance="given")


def test_fitted_heat_capacity_is_reproducible():
    pytest.importorskip("thermo")
    import os
    import subprocess
    import sys

    code = (
        "from chemeascode.integrations.thermo import fitted_cp_R;"
        "print(fitted_cp_R('74-82-8', (300, 3000))['method'])"
    )
    methods = {
        subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": seed},
            check=True,
        ).stdout.strip()
        for seed in ("1", "2", "3")
    }
    assert len(methods) == 1
