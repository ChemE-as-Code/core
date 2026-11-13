"""Batch rectification (``still.column``, ADR 0061): Diwekar's shortcut batch column on
Fenske-Underwood-Gilliland against its limits and closed forms (one stage is Rayleigh's still,
an infinite reflux the Fenske limit at alpha^N, Underwood's binary minimum reflux, the
constant-distillate balance), against a rigorous plate-to-plate binary column as a bound, the
purity end, the design by a minimum-reflux factor, the reboiler's and condenser's duties in
cheme process propagate, the rules and the example plant."""

import math
import shutil
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from chemeascode.domains.process.batch_still import (
    _Column,
    _Phase,
    gilliland_reflux,
    gilliland_stages,
    hengstebeck,
    solve_still,
    still_report,
    underwood_min_reflux,
    underwood_root,
)
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import recipe_report
from chemeascode.domains.process.schema import Column, Still
from chemeascode.foundation.workspace import Workspace

ALPHA = 2.0
EXAMPLE = Path(__file__).parents[1] / "examples/process-batch-rectification"


def _still(column=None, **kw):
    spec = {
        "volatility": {
            "model": "constant",
            "alpha": {"A": ALPHA, "B": 1.0},
            "provenance": "assumed",
        },
        "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
        "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
        "outlets": {"distillate": "top", "residue": "bottom"},
        "provenance": "assumed",
    }
    if column is not None:
        spec["column"] = column | {"provenance": "assumed"}
    return Still.model_validate(spec | kw)


def _rayleigh(x0, x, alpha):
    """ln(W0/W) of a binary at constant relative volatility."""
    return 1 / (alpha - 1) * math.log(x0 * (1 - x) / (x * (1 - x0))) + math.log((1 - x) / (1 - x0))


CHARGE = {"A": 50.0, "B": 50.0}
LATENT = {"A": 30000.0, "B": 30000.0}


class _Comp:
    def __init__(self, latent):
        self.heat_of_vaporization = latent
        self.vapour_pressure = None
        self.molar_mass = 50.0


COMPS = {n: _Comp(h) for n, h in LATENT.items()}


# -- limits and closed forms --------------------------------------------------------------------


def test_one_stage_is_rayleighs_still_and_the_reflux_only_slows_it():
    plain = solve_still(_still(), CHARGE, None, COMPS, None)
    one = solve_still(
        _still({"stages": 1, "reflux": "constant", "ratio": 0}), CHARGE, None, COMPS, None
    )
    w = sum(one.residue.values())
    assert math.log(100 / w) == pytest.approx(_rayleigh(0.5, 0.2, ALPHA), rel=1e-8)
    assert one.residue == pytest.approx(plain.residue, rel=1e-9)
    assert one.time == pytest.approx(plain.time, rel=1e-9)
    assert one.energy == pytest.approx(plain.energy, rel=1e-9)
    slow = solve_still(
        _still({"stages": 1, "reflux": "constant", "ratio": 3}), CHARGE, None, COMPS, None
    )
    assert slow.residue == pytest.approx(plain.residue, rel=1e-9)
    # (R + 1) = 4 moles boil up (and condense) per mole distilled
    assert slow.time == pytest.approx(4 * plain.time, rel=1e-9)
    assert slow.energy == pytest.approx(4 * plain.energy, rel=1e-9)
    # the energy is the latent heat of what boils up: (R + 1) D lambda
    distilled = sum(slow.cuts[0].moles.values())
    assert slow.energy == pytest.approx(4 * distilled * 30000.0, rel=1e-9)


@pytest.mark.parametrize("stages", [2, 3, 6])
def test_total_reflux_is_the_fenske_limit_rayleigh_at_alpha_to_the_n(stages):
    result = solve_still(
        _still({"stages": stages, "reflux": "constant", "ratio": 1e9}),
        CHARGE,
        None,
        {},
        None,
    )
    w = sum(result.residue.values())
    assert result.residue["A"] / w == pytest.approx(0.2, rel=1e-9)
    assert math.log(100 / w) == pytest.approx(_rayleigh(0.5, 0.2, ALPHA**stages), rel=1e-7)


@pytest.mark.parametrize("x, c1", [(0.4, 2.0), (0.4, 4.0), (0.15, 3.0), (0.7, 1.5)])
def test_underwoods_minimum_reflux_against_the_binary_closed_form(x, c1):
    """A binary fed as a saturated liquid: R_min = [x_D/x_F - alpha (1 - x_D)/(1 - x_F)] /
    (alpha - 1)."""
    alpha = [ALPHA, 1.0]
    liquid = [x, 1 - x]
    xd = hengstebeck(alpha, liquid, c1)
    # Hengstebeck-Geddes for a binary is Fenske: x_D/(1 - x_D) = alpha^C1 x/(1 - x)
    assert xd[0] / xd[1] == pytest.approx(ALPHA**c1 * x / (1 - x), rel=1e-12)
    theta = underwood_root(alpha, liquid, 1)
    closed = (xd[0] / x - ALPHA * (1 - xd[0]) / (1 - x)) / (ALPHA - 1)
    assert underwood_min_reflux(alpha, xd, theta) == pytest.approx(closed, rel=1e-9)


def test_gillilands_inverse_and_its_limits():
    for rmin, nmin, ratio in [(0.8, 4.0, 1.2), (2.0, 8.0, 5.0), (0.3, 2.5, 0.31)]:
        n = gilliland_stages(ratio, rmin, nmin)
        assert n > nmin
        assert gilliland_reflux(n, rmin, nmin) == pytest.approx(ratio, rel=1e-9)
    assert gilliland_stages(1.0, 1.0, 3.0) == math.inf
    assert gilliland_reflux(3.0, 1.0, 3.0) == math.inf


def test_constant_distillate_follows_the_binary_balance():
    """Holding x_D, the balance gives D = W0 (x0 - x_B)/(x_D - x_B) (Bogart); the time is the
    integral of (R + 1) dD / V with the column's own R along it."""
    spec = _still(
        {
            "stages": 8,
            "reflux": "constant_distillate",
            "distillate": {"key": "A", "mole_fraction": 0.95},
            "maximum_ratio": 1000,
        }
    )
    result = solve_still(spec, CHARGE, None, {}, None)
    (cut,) = result.cuts
    distilled = sum(cut.moles.values())
    assert distilled == pytest.approx(100 * (0.5 - 0.2) / (0.95 - 0.2), rel=1e-8)
    assert cut.moles["A"] / distilled == pytest.approx(0.95, rel=1e-9)
    ratios = [r for r in result.refluxes if r is not None]
    assert ratios == sorted(ratios)  # the reflux rises as the still is stripped
    assert result.column["reflux_ratio"][0] < 3 < 10 < result.column["reflux_ratio"][1]
    # Simpson over x_B: dD = W0 (x_D - x0)/(x_D - x_B)^2 dx_B
    phase = _Phase(["A", "B"], [True, True], "constant", [ALPHA, 1.0], [None, None], None, [0, 0])
    column = _Column(spec.column, phase, ["A", "B"], [50.0, 50.0])
    n = 400
    total = 0.0
    for i in range(n + 1):
        xb = 0.2 + (0.5 - 0.2) * i / n
        r = column.top([xb, 1 - xb]).reflux
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        total += weight * (r + 1) * 100 * (0.95 - 0.5) / (0.95 - xb) ** 2
    seconds = total * (0.3 / n) / 3 / 10 * 3600  # 10 kmol/h of vapour
    assert result.time == pytest.approx(seconds, rel=1e-6)


def _plate_to_plate(xb, reflux, stages, alpha=ALPHA):
    """The distillate of a binary column of *stages* equilibrium stages (the still the last),
    total condenser, constant molar overflow, whose still holds *xb*: stepped down from the
    top, the distillate found by bisection."""

    def bottom(xd):
        y = xd
        for j in range(stages):
            x = y / (alpha - (alpha - 1) * y)
            if j == stages - 1:
                return x
            y = reflux / (reflux + 1) * x + xd / (reflux + 1)
        return x

    lo, hi = xb, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if bottom(mid) > xb else (mid, hi)
    return (lo + hi) / 2


@pytest.mark.parametrize("stages, reflux", [(5, 2.0), (8, 4.0), (10, 10.0), (20, 3.0)])
def test_a_rigorous_binary_column_bounds_the_shortcut(stages, reflux):
    """Plate to plate (the same constant alpha, constant molar overflow, no holdup) gives a
    purer distillate than Gilliland's correlation at the same stages and reflux: the shortcut
    is conservative, within 0.1 in mole fraction and 6 % in the batch's mean purity."""
    spec = _still({"stages": stages, "reflux": "constant", "ratio": reflux})
    phase = _Phase(["A", "B"], [True, True], "constant", [ALPHA, 1.0], [None, None], None, [0, 0])
    column = _Column(spec.column, phase, ["A", "B"], [50.0, 50.0])
    for xb in (0.5, 0.3, 0.1):
        short = column.top([xb, 1 - xb]).distillate[0]
        rigorous = _plate_to_plate(xb, reflux, stages)
        assert xb < short <= rigorous + 1e-12
        assert rigorous - short < 0.1
    # the batch from 0.5 to a residue of 0.2: ln(W0/W) = integral dx/(x_D - x)
    n = 400
    integral = 0.0
    for i in range(n + 1):
        xb = 0.2 + 0.3 * i / n
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        integral += weight / (_plate_to_plate(xb, reflux, stages) - xb)
    w = 100 * math.exp(-integral * (0.3 / n) / 3)
    rigorous_purity = (50 - 0.2 * w) / (100 - w)
    result = solve_still(spec, CHARGE, None, {}, None)
    (cut,) = result.cuts
    purity = cut.moles["A"] / sum(cut.moles.values())
    assert purity <= rigorous_purity + 1e-9
    assert purity > 0.94 * rigorous_purity


def _rigorous_top(xb, alpha, reflux, stages):
    """The distillate of a multicomponent column of *stages* equilibrium stages (the still the
    last), total condenser, constant molar overflow, whose still holds *xb*: stepped down from
    the top, the distillate found by Newton on the still's composition (log ratios)."""
    alpha, xb = np.array(alpha, float), np.maximum(np.array(xb, float), 1e-300)

    def still(xd):
        y = xd
        for j in range(stages):
            x = y / alpha
            x /= x.sum()
            if j == stages - 1:
                return x
            y = (reflux * x + xd) / (reflux + 1)

    def residual(u):
        xd = np.exp(u - u.max())
        x = still(xd / xd.sum())
        return np.log(x[:-1] / x[-1]) - np.log(xb[:-1] / xb[-1])

    u = np.log(alpha ** (0.7 * stages) * xb)
    for _ in range(200):
        r = residual(u)
        if np.max(np.abs(r)) < 1e-12:
            break
        jac = np.empty((len(u) - 1, len(u) - 1))
        for i in range(len(u) - 1):
            du = np.zeros(len(u))
            du[i] = 1e-7
            jac[:, i] = (residual(u + du) - r) / 1e-7
        step = np.linalg.solve(jac, -r)
        lam = 1.0
        while lam > 1e-6:
            trial = u.copy()
            trial[:-1] += lam * step
            if np.max(np.abs(residual(trial))) < np.max(np.abs(r)):
                break
            lam /= 2
        u = trial
    xd = np.exp(u - u.max())
    return xd / xd.sum()


TERNARY = {"A": 4.0, "B": 2.0, "C": 1.0}


def _ternary(column, **kw):
    return _still(
        column,
        volatility={"model": "constant", "alpha": TERNARY, "provenance": "assumed"},
        **kw,
    )


@pytest.mark.parametrize("xa", [3e-3, 1e-3, 3e-4, 1e-4, 0.0])
def test_a_rigorous_ternary_column_bounds_the_shortcut_once_the_light_end_is_traces(xa):
    """Once a forerun has taken A down to traces, the column separates B from C (core#193):
    the shortcut's keys move to B/C, and A takes no more of the distillate than the still's
    vapour brings up. Against plate to plate (alpha 4/2/1, 10 stages, R 3) the distillate's B
    is never purer and within 0.01 (0.0005 at 1e-4 of A, where A/B keys gave 0.916)."""
    spec = _ternary({"stages": 10, "reflux": "constant", "ratio": 3})
    names = ["A", "B", "C"]
    phase = _Phase(names, [True] * 3, "constant", list(TERNARY.values()), [None] * 3, None, [0] * 3)
    xb = [xa, 0.7 * (1 - xa), 0.3 * (1 - xa)]
    column = _Column(spec.column, phase, names, [5.0, 65.0, 30.0])
    top = column.top([100 * v for v in xb])
    rigorous = _rigorous_top(xb, list(TERNARY.values()), 3.0, 10)
    assert top.distillate[1] <= rigorous[1] + 5e-4
    assert rigorous[1] - top.distillate[1] < 0.01
    assert top.distillate[2] == pytest.approx(rigorous[2], abs=1e-3)
    if xa > 0:
        # the column's balance: no more A than the still's vapour brings up
        vapour = hengstebeck(list(TERNARY.values()), xb, 1.0)
        assert top.distillate[0] <= 4 * vapour[0] * (1 + 1e-12)
        assert top.distillate[0] >= rigorous[0]


def test_a_forerun_then_a_main_cut_against_a_rigorous_ternary_batch():
    """The standard campaign at constant reflux: a forerun until A is 0.1 mol% of the still,
    then a main cut of B until B is 30 mol%. The main cut's B against a batch integrated on the
    rigorous column (RK4 over the moles distilled): never purer, within 0.005 (B/A keys for the
    whole batch gave 0.746 against 0.947)."""
    spec = _ternary(
        {"stages": 10, "reflux": "constant", "ratio": 3},
        end=None,
        cuts=[
            {"outlet": "fore", "end": {"residue": {"key": "A", "mole_fraction": 1e-3}}},
            {"outlet": "main", "end": {"residue": {"key": "B", "mole_fraction": 0.3}}},
        ],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, {"A": 5.0, "B": 65.0, "C": 30.0}, None, {}, None)
    fore, main = result.cuts
    short = main.moles["B"] / sum(main.moles.values())
    assert any("light key moved from A to B" in n for n in result.notes)

    alpha = list(TERNARY.values())

    def xd(n):
        return _rigorous_top(n / n.sum(), alpha, 3.0, 10)

    n, h, start, cuts = np.array([5.0, 65.0, 30.0]), 0.05, np.array([5.0, 65.0, 30.0]), []
    while len(cuts) < 2:
        x = n / n.sum()
        if (not cuts and x[0] <= 1e-3) or (cuts and x[1] <= 0.3):
            cuts.append(start - n)
            start = n.copy()
            continue
        k1 = xd(n)
        k2 = xd(n - h / 2 * k1)
        k3 = xd(n - h / 2 * k2)
        k4 = xd(n - h * k3)
        n = n - h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    rigorous = cuts[1][1] / cuts[1].sum()
    assert short <= rigorous + 1e-3
    assert rigorous - short < 0.005
    # the forerun's C is overpredicted (A/B keys: Hengstebeck's one index for all), never under
    assert fore.moles["C"] / sum(fore.moles.values()) > cuts[0][2] / cuts[0].sum()


def test_gilliland_just_above_the_minimum_reflux_is_infinite_stages_not_a_division():
    """Molokanov's Y is 1 to double precision for X below about 5e-6 (core#193): the stages
    are then infinite (as at the minimum), not a ZeroDivisionError."""
    assert gilliland_stages(3.0, 3.0 - 5e-6 * 4, 2.0) > 1e10
    assert gilliland_stages(3.0, 3.0 - 1e-9, 2.0) == math.inf
    # a still stripped deep: the Fenske index's bisection lands on such points
    spec = _still(
        {"stages": 10, "reflux": "constant", "ratio": 3},
        end={"residue": {"key": "B", "mole_fraction": 0.9995}},
    )
    result = solve_still(spec, CHARGE, None, {}, None)
    w = sum(result.residue.values())
    assert result.residue["B"] / w == pytest.approx(0.9995, rel=1e-9)
    ternary = _ternary(
        {"stages": 10, "reflux": "constant", "ratio": 3},
        end={"residue": {"key": "A", "mole_fraction": 1e-4}},
    )
    result = solve_still(ternary, {"A": 5.0, "B": 65.0, "C": 30.0}, None, {}, None)
    assert result.residue["A"] / sum(result.residue.values()) == pytest.approx(1e-4, rel=1e-6)


def test_a_constant_distillate_not_held_anywhere_is_noted_with_where():
    """The note that the column reached its maximum reflux looks at every point, not only the
    last (core#193): a forerun at the maximum whose reflux then falls again is noted, and so is
    a distillate key that is not the most volatile."""
    spec = _ternary(
        {
            "stages": 10,
            "reflux": "constant_distillate",
            "distillate": {"key": "B", "mole_fraction": 0.95},
            "maximum_ratio": 10,
        },
        end=None,
        cuts=[
            {"outlet": "fore", "end": {"distilled": 0.05}},
            {"outlet": "prod", "end": {"residue": {"key": "B", "mole_fraction": 0.3}}},
        ],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, {"A": 2.0, "B": 90.0, "C": 8.0}, None, {}, None)
    fore = result.cuts[0]
    assert fore.moles["B"] / sum(fore.moles.values()) < 0.9
    assert result.column["reflux_ratio"][1] < 10
    (note,) = [n for n in result.notes if "maximum reflux ratio 10" in n]
    assert "from 0 % to " in note and "of the charge distilled" in note
    assert any("distillate key B is not the most volatile" in n for n in result.notes)
    # an A/B binary holding B: the spec is not met at the start, the reflux ends at 0
    binary = _still(
        {
            "stages": 10,
            "reflux": "constant_distillate",
            "distillate": {"key": "B", "mole_fraction": 0.6},
            "maximum_ratio": 5,
        },
        end={"residue": {"key": "A", "mole_fraction": 0.1}},
    )
    result = solve_still(binary, CHARGE, None, {}, None)
    assert result.column["reflux_ratio"] == [5.0, 0.0]
    assert any("maximum reflux ratio 5" in n for n in result.notes)
    assert any("distillate key B is not the most volatile" in n for n in result.notes)
    # the most volatile key, held throughout: no notes
    held = solve_still(
        _still(
            {
                "stages": 8,
                "reflux": "constant_distillate",
                "distillate": {"key": "A", "mole_fraction": 0.95},
                "maximum_ratio": 1000,
            }
        ),
        CHARGE,
        None,
        {},
        None,
    )
    assert not [n for n in held.notes if "maximum reflux" in n or "most volatile" in n]


def test_a_purity_end_collects_a_cut_to_its_specification():
    spec = _still(
        {"stages": 8, "reflux": "constant", "ratio": 4},
        end=None,
        cuts=[
            {"outlet": "product", "end": {"purity": {"key": "A", "fraction": 0.95}}},
            {"outlet": "slop", "end": {"residue": {"key": "A", "mole_fraction": 0.05}}},
        ],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, CHARGE, None, {}, None)
    product, slop = result.cuts
    assert product.moles["A"] / sum(product.moles.values()) == pytest.approx(0.95, rel=1e-9)
    assert slop.moles["A"] / sum(slop.moles.values()) < 0.95
    for n in ("A", "B"):
        total = product.moles[n] + slop.moles[n] + result.residue[n]
        assert total == pytest.approx(50.0, rel=1e-12)
    # on a mass basis (molar masses 40 and 60)
    comps = {"A": _Comp(None), "B": _Comp(None)}
    comps["A"].molar_mass, comps["B"].molar_mass = 40.0, 60.0
    mass = _still(
        {"stages": 8, "reflux": "constant", "ratio": 4},
        end={"purity": {"key": "A", "fraction": 0.95}, "basis": "mass"},
    )
    (cut,) = solve_still(mass, CHARGE, None, comps, None).cuts
    kg = {n: v * comps[n].molar_mass for n, v in cut.moles.items()}
    assert kg["A"] / sum(kg.values()) == pytest.approx(0.95, rel=1e-9)
    # a key leaner than the fraction at the start: the end is reached at once (an empty cut)
    lean = _still(
        {"stages": 2, "reflux": "constant", "ratio": 0.5},
        end={"purity": {"key": "A", "fraction": 0.99}},
    )
    early = solve_still(lean, CHARGE, None, {}, None)
    assert sum(early.cuts[0].moles.values()) == 0
    assert any("reached when it starts" in n for n in early.notes)


def test_the_minimum_reflux_factor_designs_the_column_at_the_start():
    spec = _still(
        {
            "minimum_reflux_factor": 1.5,
            "reflux": "constant",
            "distillate": {"key": "A", "mole_fraction": 0.95},
        }
    )
    result = solve_still(spec, CHARGE, None, {}, None)
    design = result.column["design"]
    assert design["reflux"] == pytest.approx(1.5 * design["minimum_reflux"], rel=1e-12)
    assert design["stages"] == pytest.approx(
        gilliland_stages(design["reflux"], design["minimum_reflux"], design["minimum_stages"])
    )
    # the binary's Fenske index for 0.95 from 0.5
    assert design["minimum_stages"] == pytest.approx(math.log(19) / math.log(ALPHA), rel=1e-9)
    # at the start the column so designed gives the distillate it was designed for
    assert result.profile and result.column["reflux_ratio"][0] == pytest.approx(design["reflux"])
    phase = _Phase(["A", "B"], [True, True], "constant", [ALPHA, 1.0], [None, None], None, [0, 0])
    column = _Column(spec.column, phase, ["A", "B"], [50.0, 50.0])
    assert column.top([0.5, 0.5]).distillate[0] == pytest.approx(0.95, rel=1e-9)
    assert any("theoretical stages (not whole)" in n for n in result.notes)


def test_a_ternary_with_a_nonvolatile_balances_and_holds_its_distillate():
    spec = _still(
        {
            "stages": 12,
            "reflux": "constant_distillate",
            "distillate": {"key": "A", "mole_fraction": 0.99},
            "maximum_ratio": 6,
        },
        volatility={
            "model": "constant",
            "alpha": {"A": 4.0, "B": 2.0, "C": 1.0},
            "provenance": "assumed",
        },
        nonvolatile=["P"],
        end={"residue": {"key": "A", "mole_fraction": 0.02}},
    )
    charge = {"A": 60.0, "B": 25.0, "C": 10.0, "P": 5.0}
    result = solve_still(spec, charge, None, {}, None)
    (cut,) = result.cuts
    assert cut.moles["P"] == 0
    for n, v in charge.items():
        assert cut.moles[n] + result.residue[n] == pytest.approx(v, rel=1e-12)
    assert result.column["heavy_key"] == "B"
    # the reflux reached its maximum: the cut's purity is below the held 0.99
    assert result.column["reflux_ratio"][1] == pytest.approx(6.0)
    assert 0.9 < cut.moles["A"] / sum(cut.moles.values()) < 0.99
    assert any("maximum reflux ratio 6" in n for n in result.notes)


def test_the_column_schema():
    def column(**kw):
        return Column.model_validate({"reflux": "constant", "provenance": "assumed"} | kw)

    column(stages=5, ratio=2)
    column(minimum_reflux_factor=1.3, distillate={"key": "A", "mole_fraction": 0.9})
    for bad in (
        {"ratio": 2},  # no stages, no factor
        {"stages": 5},  # constant with stages and no ratio
        {"stages": 5, "ratio": 2, "minimum_reflux_factor": 1.2},
        {"minimum_reflux_factor": 1.2},  # no distillate
        {"stages": 5, "ratio": 2, "maximum_ratio": 3},
        {"stages": 5, "ratio": 2, "distillate": {"key": "A", "mole_fraction": 0.9}},
        {"stages": 5, "reflux": "constant_distillate", "maximum_ratio": 3},
        {
            "stages": 5,
            "reflux": "constant_distillate",
            "distillate": {"key": "A", "mole_fraction": 0.9},
        },
        {"stages": 0.5, "ratio": 1},
        {"minimum_reflux_factor": 1.0, "distillate": {"key": "A", "mole_fraction": 0.9}},
    ):
        with pytest.raises(ValidationError):
            column(**bad)
    # a still without a column or a purity end dumps as in 1.9.0 (its fingerprints stay)
    dump = _still().model_dump(mode="json")
    assert "column" not in dump and "condenser_port" not in dump
    assert "purity" not in dump["end"]


# -- in a plant: the example, propagate, the rules ----------------------------------------------


def _copy(tmp_path, edit=None):
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root)
    if edit is not None:
        path = root / "process/flowsheet.yaml"
        path.write_text(edit(path.read_text()))
    return Workspace(root)


def _propagate(ws, write):
    process, _ = load(ws.root)
    return run(ws, process, "design", write=write)


def _findings(ws):
    process, findings = load(ws.root)
    return [f for f in findings + rules(process) if f.rule == "cheme.process-still"]


def test_the_batch_rectification_example_is_current():
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(EXAMPLE))
    assert not [f.format() for f in report.findings if f.level != "info"]
    process, _ = load(EXAMPLE)
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    (unit,) = still_report(EXAMPLE).units
    sol = unit["solution"]
    assert unit["model"] == "batch rectification" and unit["basis"] == "batch-shortcut"
    assert unit["predictive"] and not unit["sourced"] and not unit["differences"]
    product, offcut = sol["cuts"]
    # the product reaches its 99.8 wt% specification, with a calculated recovery
    assert product["mass_fractions"]["ACCL"] == pytest.approx(0.998, rel=1e-9)
    assert product["recovery"]["ACCL"] > 0.99
    assert sol["residue"]["mole_fractions"]["ACCL"] == pytest.approx(0.05, rel=1e-6)
    assert sol["column"]["reflux_ratio"][1] == pytest.approx(4.0)
    # the duties: the reboiler's and the condenser's year average on Q1 and Q2
    streams = {s.id: s for s in process.flowsheet.streams}
    q1 = streams["Q1"].state["design"].duty
    q2 = streams["Q2"].state["design"].duty
    assert q1.provenance == q2.provenance == "calculated"
    assert q1.value == pytest.approx(sol["year_average_duty_kW"], rel=1e-5)
    assert q2.value == pytest.approx(q1.value, rel=1e-9)
    assert "still condenser duty ST1" in q2.source
    recipe = recipe_report(EXAMPLE)
    distil = next(s for s in recipe.steps if s.operation == "distil")
    assert distil.basis == "calculated"
    assert distil.end - distil.start == pytest.approx(sol["boilup_time_h"], rel=1e-9)


def test_propagate_writes_the_reboiler_and_the_condenser(tmp_path):
    def clear(text):
        lines = []
        for line in text.splitlines():
            if line.startswith("  - {id: Q"):
                line = line.split(", state:")[0] + "}"
            lines.append(line)
        return "\n".join(lines) + "\n"

    ws = _copy(tmp_path, clear)
    _propagate(ws, write=True)
    process, _ = load(ws.root)
    streams = {s.id: s for s in process.flowsheet.streams}
    reboil = streams["Q1"].state["design"].duty
    condense = streams["Q2"].state["design"].duty
    assert reboil.value == pytest.approx(condense.value, rel=1e-9)
    assert reboil.value > 0
    # an assumed condenser duty that differs is compared, never overwritten
    path = ws.root / "process/flowsheet.yaml"
    text = path.read_text().replace(
        f"duty: {{value: {condense.value:g}, provenance: calculated",
        "duty: {value: 10, provenance: assumed",
    )
    path.write_text(text)
    found = _propagate(ws, write=False)
    messages = [f.message for f in found.findings if f.rule == "cheme.process-duty"]
    assert any(
        "ST1 (still condenser): energy stream Q2 duty 10 kW (assumed)" in m for m in messages
    )


def test_the_condenser_port_and_the_default_streams(tmp_path):
    # no condenser stream: the reboiler is still written, the condenser is an info
    def no_q2(text):
        lines = [line for line in text.splitlines() if "id: Q2" not in line]
        return "\n".join(lines) + "\n"

    ws = _copy(tmp_path / "a", no_q2)
    found = _propagate(ws, write=False)
    infos = [f.message for f in found.findings if f.rule == "cheme.process-duty"]
    assert any(
        "ST1 (still condenser): its duty is not written: no heat stream out" in m for m in infos
    )
    # a condenser_port that is no energy port out of the still is an error
    ws = _copy(
        tmp_path / "b",
        lambda t: t.replace(
            "      outlets: {residue: bottom}\n",
            "      outlets: {residue: bottom}\n      condenser_port: steam\n",
        ),
    )
    messages = [f.message for f in _findings(ws) if f.level == "error"]
    assert "ST1: condenser_port steam is no energy port out of it" in messages
    # unknown and non-volatile keys of the column
    ws = _copy(
        tmp_path / "c",
        lambda t: t.replace(
            "        maximum_ratio: 4\n", "        maximum_ratio: 4\n        heavy_key: H3PO3\n"
        ).replace("distillate: {key: ACCL,", "distillate: {key: NOPE,"),
    )
    messages = [f.message for f in _findings(ws) if f.level == "error"]
    assert "ST1: the column's distillate NOPE is not a component" in messages
    assert "ST1: the column's heavy_key H3PO3 is non-volatile" in messages


def test_the_purity_key_and_a_condenser_port_that_is_the_energy_port(tmp_path):
    # a purity end whose key is no component
    ws = _copy(
        tmp_path / "a",
        lambda t: t.replace(
            "{purity: {key: ACCL, fraction: 0.998}", "{purity: {key: NOPE, fraction: 0.998}"
        ),
    )
    found = [f for f in _findings(ws) if f.level == "error"]
    (purity,) = [f for f in found if "purity key" in f.message]
    assert purity.message == "ST1: the end's purity key NOPE is not a component"
    assert purity.hint and purity.file
    # condenser_port and energy_port name the same energy port out
    ws = _copy(
        tmp_path / "b",
        lambda t: t.replace(
            "    title: Still with its column\n",
            "    title: Still with its column\n    energy_port: condenser\n",
        ).replace(
            "      outlets: {residue: bottom}\n",
            "      outlets: {residue: bottom}\n      condenser_port: condenser\n",
        ),
    )
    messages = [f.message for f in _findings(ws) if f.level == "error"]
    assert "ST1: condenser_port and energy_port are both condenser" in messages
    assert not any("no energy port out of it" in m for m in messages)


def test_a_rayleigh_still_with_a_condenser_port_writes_its_condenser(tmp_path):
    """A one-stage still (no column) gets its condenser's duty only where condenser_port names
    the stream: the same latent heat as its boil-up."""

    def rayleigh(text):
        start = text.index("      column:\n")
        end = text.index("      cuts:\n")
        text = text[:start] + text[end:]
        text = text.replace(
            "      outlets: {residue: bottom}\n",
            "      outlets: {residue: bottom}\n      condenser_port: condenser\n",
        )
        text = text.replace("{key: ACCL, fraction: 0.998}", "{key: ACCL, fraction: 0.97}")
        lines = []
        for line in text.splitlines():
            if line.startswith("  - {id: Q"):
                line = line.split(", state:")[0] + "}"
            lines.append(line)
        return "\n".join(lines) + "\n"

    ws = _copy(tmp_path, rayleigh)
    ws.root.joinpath("process/recipe.yaml").unlink()
    _propagate(ws, write=True)
    process, _ = load(ws.root)
    streams = {s.id: s for s in process.flowsheet.streams}
    (unit,) = still_report(ws.root).units
    assert unit["basis"] == "rayleigh"
    expected = unit["solution"]["year_average_duty_kW"]
    assert streams["Q1"].state["design"].duty.value == pytest.approx(expected, rel=1e-5)
    assert streams["Q2"].state["design"].duty.value == pytest.approx(expected, rel=1e-5)


def test_the_still_condensers_freezing_check(tmp_path):
    """ADR 0071 (process-library potassium-tert-butoxide-1 L-9): a still's condenser whose
    coolant's supply lies below the melting point of a component its distillate carries warns;
    a trace (below 1 mol%) does not count, nor does a supply above the melting point."""
    rule = "cheme.process-condenser-freezing"

    def found(ws):
        process, findings = load(ws.root)
        return [f for f in findings + rules(process) if f.rule == rule]

    def cold(supply):
        return lambda t: t.replace(
            "utility: {kind: cooling_water}",
            f"utility: {{kind: cooling_water, supply_temperature: {{value: {supply}, "
            "provenance: assumed}}",
        )

    def melting(ws, edits):
        path = ws.root / "process/materials.yaml"
        text = path.read_text()
        for name, tm in edits.items():
            text = text.replace(f"  - id: {name}\n", f"  - id: {name}\n    melting_point: {tm}\n")
        path.write_text(text)
        return ws

    # acetic acid (289.8 K) is a trace of the distillate: no warning
    assert not found(melting(_copy(tmp_path / "a", cold(285)), {"ACOH": 289.8}))
    # a distillate of ACCL melting at 290 K (illustrative) over a 285 K coolant: the column's
    # default condenser stream Q2 warns
    ws = melting(_copy(tmp_path / "b", cold(285)), {"ACOH": 289.8, "ACCL": 290})
    (warning,) = found(ws)
    assert warning.level == "warning" and "ACCL (290 K)" in warning.message
    assert "ACOH" not in warning.message and "coolant CW's supply at 285 K" in warning.message
    assert warning.line is not None and warning.hint
    # named as the condenser_port, the same
    named = _copy(
        tmp_path / "c",
        lambda t: cold(285)(t).replace(
            "      outlets: {residue: bottom}\n",
            "      outlets: {residue: bottom}\n      condenser_port: condenser\n",
        ),
    )
    assert len(found(melting(named, {"ACCL": 290}))) == 1
    # a coolant above the melting point, or no supply temperature: none
    assert not found(melting(_copy(tmp_path / "d", cold(295)), {"ACCL": 290}))
    assert not found(melting(_copy(tmp_path / "e"), {"ACCL": 290}))


def _ended(tmp_path, end):
    """The example with its product cut ended at *end*: its still's node and inlets."""
    from chemeascode.domains.process.batch_still import inlets_of

    ws = _copy(
        tmp_path,
        lambda text: text.replace(
            "{outlet: product, end: {purity: {key: ACCL, fraction: 0.998}, basis: mass}}",
            f"{{outlet: product, end: {end}}}",
        ),
    )
    process, _ = load(ws.root)
    node = process.nodes["ST1"]
    return process, node, inlets_of(process, node)


@pytest.mark.parametrize("hours", [10, 2.495])
def test_a_column_still_that_runs_dry_before_a_time_end_fails_at_once(tmp_path, hours):
    """The example's product cut ended at 10 h, long after the still runs dry: the column's
    error control kept the step far above the boils-dry floor, so the still crept on near
    empty without end (core 1.11.0 hung, and so did an end at 2.495 h). A run of small steps
    whose pace does not reach the end within the step budget stalls: StillError within a few
    seconds, naming the volatile content left and the remedy."""
    import time

    from chemeascode.domains.process.batch_still import StillError, solve_node

    process, node, inlets = _ended(tmp_path, f"{{time: {hours * 3600:g}}}")
    start = time.monotonic()
    with pytest.raises(StillError, match="stalls before its end.*volatile.*end the cut earlier"):
        solve_node(process, node, inlets, "design")
    assert time.monotonic() - start < 20.0


@pytest.mark.parametrize("end", ["{time: 8964}", "{distilled: 0.9967}"])
def test_a_column_still_slow_but_progressing_near_empty_reaches_its_end(tmp_path, end):
    """Integration review of 1.12.0: an end at 2.49 h (or 99.67 % distilled) is reached on a
    tail where explicit Dopri5 takes tiny steps on the PCL3 trace the column enriches (about
    2e-7 kmol a step, every one below the small-step share). The pre-1.12.0 code solved it
    (residue 0.01446 kmol); the stall guard refused it as boiling dry after 500 small steps.
    At its pace the end is within the step budget, so it solves as before."""
    from chemeascode.domains.process.batch_still import solve_node

    process, node, inlets = _ended(tmp_path, end)
    result, _ = solve_node(process, node, inlets, "design")
    assert sum(result.residue.values()) == pytest.approx(0.01445, abs=2e-4)


def test_a_light_key_the_column_clears_to_nothing_does_not_stall():
    """Integration review of 1.12.0: a forerun to a purity end strips A to 1e-17 kmol; the
    column's gain (alpha^stages, about 1e13) and Underwood's pole at A held explicit Dopri5 at
    its stability limit (4e-10 kmol a step) for some 1850 steps until A underflowed, and the
    main cut then ended within 140 steps. The pace check projected the slow run linearly and
    refused the cut (after 4596 steps, 20.09 kmol left), which the pre-1.12.0 code solved. An
    amount below 1e-100 of the charge is now gone (no longer a pole), and a run of small steps
    in which a volatile component falls 1000-fold is progress."""
    spec = Still.model_validate(
        {
            "volatility": {
                "model": "constant",
                "alpha": {"A": 10.1435, "B": 4.5999, "C": 1.0},
                "provenance": "assumed",
            },
            "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
            "column": {
                "stages": 13,
                "reflux": "constant_distillate",
                "distillate": {"key": "A", "mole_fraction": 0.9166},
                "maximum_ratio": 32,
                "provenance": "assumed",
            },
            "cuts": [
                {"outlet": "forerun", "end": {"purity": {"key": "A", "fraction": 0.8479}}},
                {"outlet": "main", "end": {"distilled": 0.51892}},
            ],
            "outlets": {"residue": "bottom"},
            "provenance": "assumed",
        }
    )
    result = solve_still(spec, {"A": 42.46695, "B": 0.0029449, "C": 25.86294}, None, {}, None)
    assert result.residue["C"] == pytest.approx(18.248, abs=1e-3)
    assert result.time == pytest.approx(70791.2, abs=0.1)


def test_the_stall_guard_leaves_a_bubble_point_still_as_it_was():
    """Integration review of 1.12.0: the stall guard evaluated the stop at the start of each
    cut and again on the step that crossed it, which moved the bubble point's warm start and
    shifted a Raoult still's cuts by 2e-8 (2.21443518 kmol for 2.21443523). It evaluates the
    stop where the code before it did, so the cuts are the same to the last digits."""
    from chemeascode.domains.process.schema import Component

    def comp(name, vp, mw, latent):
        spec = {"id": name, "name": name, "molar_mass": mw, "heat_of_vaporization": latent}
        if vp:
            spec["vapour_pressure"] = vp | {"provenance": "given", "source": "x"}
        return Component.model_validate(spec)

    comps = {
        "A": comp(
            "A",
            {"a": 4.72583, "b": 1660.652, "c": -1.461, "temperature_range": [287.7, 354.07]},
            78.11,
            30720,
        ),
        "B": comp(
            "B",
            {"a": 4.07827, "b": 1343.943, "c": -53.773, "temperature_range": [308.52, 384.66]},
            92.14,
            33180,
        ),
        "P": comp("P", None, 128.0, None),
    }
    ends = [
        {"time": 1800},
        {"distilled": 0.15},
        {"distilled": 0.2, "basis": "mass"},
        {"purity": {"key": "A", "fraction": 0.98}},
        {"residue": {"key": "A", "mole_fraction": 1e-3}},
        {"temperature": 383.0},
    ]
    spec = _still(
        {
            "stages": 10,
            "reflux": "constant_distillate",
            "distillate": {"key": "A", "mole_fraction": 0.99},
            "maximum_ratio": 20,
        },
        volatility={"model": "raoult", "provenance": "assumed", "source": "x"},
        pressure=101.325,
        nonvolatile=["P"],
        end=None,
        cuts=[{"outlet": f"c{i}", "end": e} for i, e in enumerate(ends)],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, {"A": 30.0, "B": 40.0, "P": 30.0}, None, comps, 101.325)
    cuts = [sum(c.moles.values()) for c in result.cuts]
    assert cuts == pytest.approx(
        [
            1.371064070398571,
            13.628935929601434,
            10.223928853946878,
            2.214435232211436,
            6.607246939555203,
            0.0,
        ],
        rel=1e-11,
        abs=1e-12,
    )
    assert result.time == pytest.approx(126937.04774572354, rel=1e-12)


def test_a_still_boilup_no_cut_uses_does_not_count(tmp_path):
    """Every cut with its own boil-up in 1/h, the still's own (150 kW) unused: the outlets do
    not depend on the hours of flows, so the recipe's batch size on the product cut is no
    circle, and no heat_of_vaporization is asked for the unused kW boil-up (ADR 0068)."""
    from chemeascode.domains.process.batch_still import outlets_need_hours

    cuts = (
        "{outlet: product, end: {time: 3600}, boilup: {value: 2, unit: 1/h, provenance: assumed}}",
        "{outlet: offcut, end: {residue: {key: ACCL, mole_fraction: 0.05}}, boilup: {value: 2, "
        "unit: 1/h, provenance: assumed}}",
    )
    ws = _copy(
        tmp_path,
        lambda text: text.replace(
            "{outlet: product, end: {purity: {key: ACCL, fraction: 0.998}, basis: mass}}", cuts[0]
        ).replace("{outlet: offcut, end: {residue: {key: ACCL, mole_fraction: 0.05}}}", cuts[1]),
    )
    recipe = ws.root / "process/recipe.yaml"
    recipe.write_text(recipe.read_text().replace("unit: kg, stream: S1,", "unit: kg, stream: S2,"))
    process, _ = load(ws.root)
    spec = process.nodes["ST1"].still
    assert spec.boilup.unit == "kW" and [b.unit for b in spec.boilups()] == ["1/h", "1/h"]
    assert not outlets_need_hours(spec)
    result = _propagate(ws, write=True)
    assert not [f.format() for f in result.findings if f.level in ("error", "warning")]
    assert result.written >= 5
    # the still's own boil-up still counts with a feed or a cut without its own
    timed = spec.model_copy(
        update={"cuts": [spec.cuts[0], spec.cuts[1].model_copy(update={"boilup": None})]}
    )
    assert [b.unit for b in timed.boilups()] == ["kW", "1/h"] and not outlets_need_hours(timed)
    first = spec.model_copy(
        update={"cuts": [spec.cuts[0].model_copy(update={"boilup": None}), spec.cuts[1]]}
    )
    assert outlets_need_hours(first)
