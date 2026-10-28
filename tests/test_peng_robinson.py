"""Peng-Robinson fugacity coefficients and real-gas equilibria: pure components against thermo,
the ammonia equilibrium against Larson and Dodge (1923), and the rules and command."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chemeascode.domains.chemistry.eos import Critical, fugacity_coefficients
from chemeascode.domains.chemistry.equilibrium import equilibrate, equilibrate_real, reaction_ln_k
from chemeascode.domains.process.model import load, rules
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CRITICAL = {
    "N2": Critical(Tc=126.192, Pc=3395.8, omega=0.0372),
    "H2": Critical(Tc=33.145, Pc=1296.4, omega=-0.219),
    "NH3": Critical(Tc=405.56, Pc=11363.4, omega=0.256),
}


@pytest.mark.parametrize(
    ("name", "t", "p"), [("N2", 300.0, 10000.0), ("NH3", 700.0, 20000.0), ("H2", 400.0, 30000.0)]
)
def test_pure_components_against_thermo(name, t, p):
    thermo = pytest.importorskip("thermo")
    c = CRITICAL[name]
    eos = thermo.PR(Tc=c.Tc, Pc=c.Pc * 1000, omega=c.omega, T=t, P=p * 1000)
    # far above Tc thermo labels the one root as liquid-like
    reference = eos.phi_g if hasattr(eos, "phi_g") else eos.phi_l
    assert fugacity_coefficients({name: 1.0}, t, p, CRITICAL)[name] == pytest.approx(
        reference, rel=1e-9
    )


def test_an_ideal_gas_limit():
    phi = fugacity_coefficients({"N2": 0.25, "H2": 0.75}, 700.0, 1.0, CRITICAL)
    assert phi == pytest.approx({"N2": 1.0, "H2": 1.0}, abs=1e-4)
    with pytest.raises(ValueError, match="no critical constants for AR"):
        fugacity_coefficients({"N2": 0.5, "AR": 0.5}, 700.0, 100.0, CRITICAL)


@pytest.mark.parametrize(("atm", "measured", "tol"), [(100, 16.36, 0.5), (300, 35.5, 1.5)])
def test_ammonia_equilibrium_against_larson_and_dodge(atm, measured, tol):
    # Larson and Dodge, J. Am. Chem. Soc. 45 (1923) 2918: NH3 at equilibrium, 450 C, H2:N2 = 3
    process, _ = load(EXAMPLES / "process-ammonia")
    reaction = process.reactions.by_id()["NH3_SYN"]
    ln_k = reaction_ln_k(reaction, process.ideal_gas(), 723.15)
    feed, p = {"N2": 1.0, "H2": 3.0}, atm * 101.325
    real, _ = equilibrate_real([reaction.stoichiometry], [ln_k], feed, p, 723.15, CRITICAL)
    ideal, _ = equilibrate([reaction.stoichiometry], [ln_k], feed, p)
    y_real = 100 * real["NH3"] / sum(real.values())
    y_ideal = 100 * ideal["NH3"] / sum(ideal.values())
    assert y_real == pytest.approx(measured, abs=tol)
    assert abs(y_real - measured) < abs(y_ideal - measured)


def test_the_example_is_at_its_real_gas_equilibrium():
    from chemeascode.domains.process.reactors import reactor_report

    r1 = next(r for r in reactor_report(EXAMPLES / "process-ammonia").reactors if r["node"] == "R1")
    assert r1["reactions"][0]["ln_q_over_k"] == pytest.approx(0.0, abs=1e-4)


def test_rules(tmp_path):
    import shutil

    root = tmp_path / "nh3"
    shutil.copytree(EXAMPLES / "process-ammonia", root, ignore=shutil.ignore_patterns("build"))
    materials = root / "process/materials.yaml"
    text = materials.read_text()
    start = text.index("    critical:", text.index("id: AR"))
    end = text.index("\n", start) + 1
    materials.write_text(text[:start] + text[end:])
    process, _ = load(root)
    found = [f for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("without the critical constants of AR" in f.message for f in found)
    flowsheet = root / "process/flowsheet.yaml"
    flowsheet.write_text(
        flowsheet.read_text().replace(
            "    reactor: equilibrium\n",
            "    reactor: conversion\n    conversion: {NH3_SYN: 0.25}\n",
        )
    )
    process, _ = load(root)
    assert any("fugacity peng_robinson is used by equilibrium" in f.message for f in rules(process))


def test_thermo_prints_critical_constants():
    pytest.importorskip("chemicals")
    shown = CliRunner().invoke(app, ["chemistry", "thermo", "ammonia"])
    assert "critical: {Tc: 405.56, Pc: 11363.4, omega: 0.256" in shown.output
    as_json = json.loads(
        CliRunner().invoke(app, ["chemistry", "thermo", "ammonia", "--json"]).output
    )
    assert as_json[0]["critical"]["Tc"] == pytest.approx(405.56)


def test_review_fixes(tmp_path):
    import shutil

    from chemeascode.domains.process.reactors import reactor_report

    # a product's critical constants are needed, though no stream carries it yet
    root = tmp_path / "nh3"
    shutil.copytree(EXAMPLES / "process-ammonia", root, ignore=shutil.ignore_patterns("build"))
    materials = root / "process/materials.yaml"
    text = materials.read_text()
    start = text.index("    critical:", text.index("id: NH3"))
    materials.write_text(text[:start] + text[text.index("\n", start) + 1 :])
    process, _ = load(root)
    found = [f for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("critical constants of NH3" in f.message for f in found)
    # and the report gives no ideal ln(Q/K) for the real-gas reactor then
    r1 = next(r for r in reactor_report(root).reactors if r["node"] == "R1")
    assert r1["reactions"][0]["ln_q_over_k"] is None
    assert any("fugacity coefficients" in m for m in r1["missing"])


def test_very_high_pressure_converges():
    process, _ = load(EXAMPLES / "process-ammonia")
    reaction = process.reactions.by_id()["NH3_SYN"]
    ln_k = reaction_ln_k(reaction, process.ideal_gas(), 723.15)
    out, _ = equilibrate_real(
        [reaction.stoichiometry], [ln_k], {"N2": 1.0, "H2": 3.0}, 1000 * 101.325, 723.15, CRITICAL
    )
    # Larson and Dodge: 69.4 % at 1000 atm; classic PR without k_ij falls short there
    assert 55 < 100 * out["NH3"] / sum(out.values()) < 75
