"""Kinetic data and fitted rate laws: power law and LHHW recovered from synthetic data, the
reversible factor, refusals, a mechanism lumped into a power law, and cheme experiments."""

import json
import math
import random

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.chemistry.microkinetics import Mechanism, analyse
from chemeascode.domains.experiments.kinetic_fit import (
    SCHEMA,
    KineticData,
    fit_lhhw,
    fit_power_law,
    sample_mechanism,
)
from chemeascode.interfaces.cli import app

R = 8.314462618


def _data(points, **kw):
    return KineticData.model_validate(
        {
            "schema": SCHEMA,
            "kind": "kinetic-data",
            "reaction": "R",
            "basis": "catalyst_mass",
            "points": points,
            "provenance": "assumed",
            **kw,
        }
    )


def _power_points(noise=0.01, reverse_k=None):
    random.seed(1)
    points = []
    for t in (550, 600, 650, 700):
        for co in (0.5, 1.0, 2.0):
            for h2o in (2.0, 5.0):
                r = 1e3 * math.exp(-80000 / (R * t)) * co**0.8 * h2o**0.3
                p = {"CO": co, "H2O": h2o}
                if reverse_k is not None:
                    p |= {"CO2": 0.5, "H2": 1.0}
                    r *= 1 - (0.5 * 1.0) / (co * h2o) / reverse_k
                points.append(
                    {
                        "temperature": t,
                        "partial_pressures": p,
                        "rate": r * math.exp(random.gauss(0, noise)),
                    }
                )
    return points


def test_a_power_law_is_recovered_with_its_intervals():
    fit = fit_power_law(_data(_power_points()), ["CO", "H2O"])
    assert fit.law.k.Ea == pytest.approx(80000, rel=0.005)
    assert fit.law.orders == pytest.approx({"CO": 0.8, "H2O": 0.3}, abs=0.01)
    lo, hi = fit.interval("Ea")
    assert lo < 80000 < hi
    assert fit.r_squared > 0.999 and fit.law.provenance == "calculated"
    assert fit.law.temperature_range == (550, 700)


def test_the_reversible_factor_is_divided_out():
    data = _data(_power_points(noise=0.0, reverse_k=4.0))
    wgs = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
    fit = fit_power_law(data, ["CO", "H2O"], wgs, lambda t: math.log(4.0))
    assert fit.law.k.Ea == pytest.approx(80000, rel=1e-6)
    assert fit.law.reverse == "equilibrium"
    naive = fit_power_law(data, ["CO", "H2O"])
    assert abs(naive.law.orders["CO"] - 0.8) > 0.05  # without it the orders are off


def test_an_lhhw_law_is_recovered():
    points = []
    for t in (550, 600, 650, 700):
        for co in (0.2, 0.5, 1.0, 2.0, 4.0):
            r = (
                1e3
                * math.exp(-80000 / (R * t))
                * co
                / (1 + 0.02 * math.exp(20000 / (R * t)) * co) ** 2
            )
            points.append({"temperature": t, "partial_pressures": {"CO": co}, "rate": r})
    fit = fit_lhhw(_data(points), {"CO": 1.0}, ["CO"], power=2)
    assert fit.law.k.Ea == pytest.approx(80000, rel=1e-4)
    term = fit.law.adsorption[0]
    assert pytest.approx(0.02, rel=1e-3) == term.A and term.dH == pytest.approx(-20000, rel=1e-3)
    assert fit.r_squared == pytest.approx(1.0, abs=1e-9)


def test_refusals():
    few = _data(_power_points()[:3])
    with pytest.raises(ValueError, match="give more data"):
        fit_power_law(few, ["CO", "H2O"])
    beyond = _power_points(noise=0.0)
    beyond[0]["partial_pressures"] |= {"CO2": 50.0, "H2": 50.0}
    with pytest.raises(ValueError, match="beyond equilibrium"):
        fit_power_law(
            _data(beyond), ["CO"], {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}, lambda t: 0.0
        )
    with pytest.raises(ValueError, match="no partial pressure of O2"):
        fit_power_law(_data(_power_points()), ["O2"])
    with pytest.raises(ValueError, match="not supported"):
        _data(_power_points(), schema="cheme/kinetic-data/v2")


CO_OX = {
    "site_density": 2.7063e-5,
    "adsorbates": ["CO*", "O*"],
    "provenance": "assumed",
    "source": "after Deutschmann et al. (1996)",
    "steps": [
        {
            "id": "S1",
            "stoichiometry": {"CO": -1, "*": -1, "CO*": 1},
            "sticking": {"s0": 0.84},
            "reverse": {"A": 1e13, "Ea": 125500},
        },
        {
            "id": "S2",
            "stoichiometry": {"O2": -1, "*": -2, "O*": 2},
            "sticking": {"s0": 0.07},
            "reverse": {"A": 1e13, "Ea": 213200},
        },
        {
            "id": "S3",
            "stoichiometry": {"CO*": -1, "O*": -1, "CO2": 1, "*": 2},
            "forward": {"A": 1e13, "Ea": 105000},
        },
    ],
}
MASSES = {"CO": 28.010, "O2": 31.998, "CO2": 44.009}


def test_a_mechanism_lumped_into_a_power_law():
    mech = Mechanism.model_validate(CO_OX)
    data = sample_mechanism(
        mech,
        MASSES,
        "CO2",
        2.0,
        [480, 500, 520],
        {"CO": [0.008, 0.01, 0.0125], "O2": [0.08, 0.1, 0.125]},
        1e-4,
        "COOX",
    )
    assert len(data.points) == 27 and data.provenance == "calculated"
    fit = fit_power_law(data, ["CO", "O2"])
    # the lumped law reproduces the mechanism's own orders and activation energy
    state = analyse(mech, 500, {"CO": 0.01, "O2": 0.1}, MASSES, "CO2", ["CO", "O2"])
    assert fit.law.orders["CO"] == pytest.approx(state.orders["CO"], abs=0.02)
    assert fit.law.orders["O2"] == pytest.approx(state.orders["O2"], abs=0.02)
    assert fit.law.k.Ea == pytest.approx(state.apparent_activation, rel=0.02)


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: CO, name: Carbon monoxide, formula: CO, molar_mass: 28.010}
  - {id: O2, name: Oxygen, formula: O2, molar_mass: 31.998}
  - {id: CO2, name: Carbon dioxide, formula: CO2, molar_mass: 44.009}
"""


def test_sample_and_fit_from_the_command_line(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: fit\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    reactions = {
        "schema": "cheme/reactions/v1",
        "kind": "reactions",
        "reactions": [
            {"id": "COOX", "stoichiometry": {"CO": -2, "O2": -1, "CO2": 2}, "mechanism": CO_OX}
        ],
    }
    (root / "process/reactions.yaml").write_text(yaml.safe_dump(reactions, sort_keys=False))
    monkeypatch.chdir(root)
    made = CliRunner().invoke(
        app,
        [
            "experiments",
            "sample-mechanism",
            "COOX",
            "-T",
            "480",
            "-T",
            "500",
            "-T",
            "520",
            "-p",
            "CO=0.008,0.01,0.0125",
            "-p",
            "O2=0.08,0.1,0.125",
            "--sites-per-kg",
            "1e-4",
            "--out",
            "experiments/kinetics/coox.yaml",
        ],
    )
    assert made.exit_code == 0, made.output
    assert "27 points" in made.output
    shown = CliRunner().invoke(
        app,
        [
            "experiments",
            "fit-rate",
            "experiments/kinetics/coox.yaml",
            "--order",
            "CO",
            "--order",
            "O2",
        ],
    )
    assert shown.exit_code == 0, shown.output
    assert "rate:" in shown.output and "95 %" in shown.output
    rate = yaml.safe_load(shown.output[shown.output.index("rate:") :])["rate"]
    assert rate["form"] == "power_law" and rate["orders"]["CO"] == pytest.approx(-2.0, abs=0.05)
    as_json = json.loads(
        CliRunner()
        .invoke(app, ["experiments", "fit-rate", "experiments/kinetics/coox.yaml", "--json"])
        .output
    )
    assert set(as_json["rate"]["orders"]) == {"CO", "O2"}  # default: the reactants
    bad = CliRunner().invoke(
        app, ["experiments", "fit-rate", "experiments/kinetics/coox.yaml", "--reverse"]
    )
    assert bad.exit_code == 1 and "not reversible" in bad.output
    mixed = CliRunner().invoke(
        app, ["experiments", "fit-rate", "experiments/kinetics/coox.yaml", "--order", "CO=0.5"]
    )
    assert mixed.exit_code == 2 and "no =EXPONENT" in mixed.output


# -- review fixes -------------------------------------------------------------------------------


def _isothermal():
    return [
        {"temperature": 600, "partial_pressures": {"CO": co}, "rate": 1e-3 * co}
        for co in (0.1, 0.5, 1.0, 2.0, 5.0)
    ]


def test_parameters_the_data_do_not_determine_are_refused():
    with pytest.raises(ValueError, match="one temperature only: Ea is not determined"):
        fit_power_law(_data(_isothermal()), ["CO"])
    constant = [
        {"temperature": t, "partial_pressures": {"CO": 1.0}, "rate": math.exp(-1000 / t)}
        for t in (500, 550, 600, 650)
    ]
    with pytest.raises(ValueError, match="partial pressure of CO only"):
        fit_power_law(_data(constant), ["CO"])


def test_lhhw_refusals():
    points = []
    for t in (550, 600, 650):
        for co in (0.5, 1.0, 2.0, 4.0):
            points.append(
                {
                    "temperature": t,
                    "partial_pressures": {"CO": co},
                    "rate": math.exp(-8000 / t) * co**1.5,
                }
            )
    with pytest.raises(ValueError, match="H2 is adsorbed, but no point"):
        fit_lhhw(_data(points), {"CO": 1.0}, ["CO", "H2"], 2)
    # a zero-order component needs no pressure
    with pytest.raises(ValueError) as found:
        fit_lhhw(_data(points), {"CO": 1.0, "H2": 0.0}, ["CO"], 2)
    assert "KeyError" not in repr(found.value)
    # CO^1.5 without saturation is no LHHW law with CO in the numerator to the first power
    with pytest.raises(ValueError, match="does not fit|do not determine"):
        fit_lhhw(_data(points), {"CO": 1.0}, ["CO"], 2)


def test_an_absent_reactant_under_reverse_is_refused():
    points = _power_points(noise=0.0, reverse_k=4.0)
    points[0]["partial_pressures"]["H2O"] = 0.0
    wgs = {"CO": -1, "H2O": -1, "CO2": 1, "H2": 1}
    with pytest.raises(ValueError, match="reactant H2O absent"):
        fit_power_law(_data(points), ["CO"], wgs, lambda t: math.log(4.0))


def test_the_95_percent_quantile_is_conservative():
    from chemeascode.domains.experiments.kinetic_fit import _t95

    assert _t95(11) == 2.228 and _t95(31) == 2.042 and _t95(61) == 2.000
    assert _t95(0) == math.inf
