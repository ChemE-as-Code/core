"""Rate laws fitted to integral data: conversions measured in batch,
plug-flow and stirred-tank reactors, recovered parameters and intervals, and cheme
experiments fit-rate on such a file."""

import math
import random

import pytest
from pydantic import ValidationError

from chemeascode.domains.chemistry.rates import R
from chemeascode.domains.experiments.kinetic_fit import (
    IntegralPoint,
    KineticData,
    _conversion,
    fit_integral,
)

A_TRUE, EA_TRUE = 1.0e6, 50000.0
FIRST = {"A": -1, "B": 1}


def _k(t: float) -> float:
    return A_TRUE * math.exp(-EA_TRUE / (R * t))


def _data(integral, **extra):
    return KineticData.model_validate(
        {
            "schema": "cheme/kinetic-data/v1",
            "kind": "kinetic-data",
            "reaction": "R1",
            "basis": "volume",
            "key": "A",
            "integral": integral,
            "provenance": "assumed",
        }
        | extra
    )


def _first_order_points():
    points = []
    for t in (320.0, 340.0, 360.0):
        for time in (10.0, 30.0, 90.0):
            k = _k(t)
            points.append(
                {
                    "reactor": "batch",
                    "temperature": t,
                    "time": time,
                    "concentrations": {"A": 2.0},
                    "conversion": 1 - math.exp(-k * time),
                }
            )
            points.append(
                {
                    "reactor": "cstr",
                    "temperature": t,
                    "time": time,
                    "concentrations": {"A": 2.0},
                    "conversion": k * time / (1 + k * time),
                }
            )
    return points


def test_first_order_parameters_are_recovered():
    fit = fit_integral(_data(_first_order_points()), FIRST, {"A": 1.0})
    assert pytest.approx(A_TRUE, rel=1e-4) == fit.law.k.A
    assert fit.law.k.Ea == pytest.approx(EA_TRUE, rel=1e-5)
    assert fit.law.driving == "concentration" and fit.law.orders == {"A": 1.0}
    assert fit.law.temperature_range == (320.0, 360.0)
    assert max(abs(r) for r in fit.residuals) < 1e-7
    assert fit.r_squared == pytest.approx(1.0)


def test_an_order_is_fitted_and_the_intervals_hold_the_truth():
    stoich = {"A": -1, "B": -1, "C": 1}
    truth = {"A": 1.5, "B": 1.0}
    rng = random.Random(7)
    points = []
    for t in (330.0, 350.0):
        for ca in (0.5, 1.0, 2.0):
            for time in (60.0, 200.0, 600.0):
                p = IntegralPoint(
                    reactor="pfr",
                    temperature=t,
                    time=time,
                    concentrations={"A": ca, "B": 3.0},
                    conversion=0.5,
                )
                x = _conversion(p, "A", stoich, truth, _k(t) / 100, 1.0)
                points.append(p.model_dump() | {"conversion": x + rng.gauss(0, 0.002)})
    fit = fit_integral(_data(points), stoich, {"A": 1.0, "B": 1.0}, ["A"])
    lo, hi = fit.interval("order_A")
    assert lo < 1.5 < hi and hi - lo < 0.1
    lo, hi = fit.interval("Ea")
    assert lo < EA_TRUE < hi


def test_what_integral_data_need():
    with pytest.raises(ValidationError, match="key component"):
        _data(_first_order_points(), key="")
    with pytest.raises(ValidationError, match="not both"):
        _data(
            _first_order_points(),
            points=[{"temperature": 300, "partial_pressures": {"A": 1}, "rate": 1}] * 2,
        )
    with pytest.raises(ValidationError, match="catalyst_loading"):
        _data(_first_order_points(), basis="catalyst_mass")
    with pytest.raises(ValueError, match="not a reactant"):
        fit_integral(_data(_first_order_points(), key="B"), FIRST, {"A": 1.0})
    one_t = [p for p in _first_order_points() if p["temperature"] == 340.0]
    with pytest.raises(ValueError, match="one temperature only: Ea is not determined"):
        fit_integral(_data(one_t), FIRST, {"A": 1.0})


def test_one_temperature_is_refused_not_fitted_with_ea_zero():
    """Isothermal conversions gave a law with Ea = 0 and no temperature
    range, which covered (and was used at) every temperature with an Arrhenius factor of 1."""
    k = 0.01
    points = [
        {
            "reactor": "batch",
            "temperature": 600.0,
            "time": time,
            "concentrations": {"A": 1.0},
            "conversion": 1 - math.exp(-k * time),
        }
        for time in (20.0, 50.0, 100.0, 200.0)
    ]
    with pytest.raises(ValueError, match="Ea is not determined"):
        fit_integral(_data(points), FIRST, {"A": 1.0})


def test_fit_rate_on_an_integral_file(tmp_path):
    import yaml

    from chemeascode.project.kinetics import KineticsProblem, fit_file

    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "experiments/kinetics").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: fit\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(
        "schema: cheme/process/v1\nkind: materials\ncomponents:\n"
        "  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05}\n"
        "  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05}\n"
    )
    (root / "process/reactions.yaml").write_text(
        "schema: cheme/reactions/v1\nkind: reactions\n"
        "reactions:\n  - {id: R1, stoichiometry: {A: -1, B: 1}}\n"
    )
    path = root / "experiments/kinetics/batch.yaml"
    path.write_text(
        yaml.safe_dump(_data(_first_order_points()).model_dump(mode="json", by_alias=True))
    )
    fit = fit_file(root, path)
    assert fit.law.k.Ea == pytest.approx(EA_TRUE, rel=1e-5)
    with pytest.raises(KineticsProblem, match="forward power law only"):
        fit_file(root, path, reverse=True)


def test_an_inhibitor_outside_the_reaction_keeps_its_concentration():
    p = IntegralPoint(
        reactor="batch",
        temperature=350.0,
        time=100.0,
        concentrations={"A": 1.0, "I": 2.0},
        conversion=0.5,
    )
    plain = _conversion(p, "A", FIRST, {"A": 1.0}, 0.01, 1.0)
    inhibited = _conversion(p, "A", FIRST, {"A": 1.0, "I": -1.0}, 0.01, 1.0)
    assert plain == pytest.approx(1 - math.exp(-1.0), rel=1e-6)
    assert inhibited == pytest.approx(1 - math.exp(-0.5), rel=1e-6)  # k / c_I
