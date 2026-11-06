"""Batch rectification (``still.column``, ADR 0061): Diwekar's shortcut batch column on
Fenske-Underwood-Gilliland against its limits and closed forms (one stage is Rayleigh's still,
an infinite reflux the Fenske limit at alpha^N, Underwood's binary minimum reflux, the
constant-distillate balance), against a rigorous plate-to-plate binary column as a bound, the
purity end, the design by a minimum-reflux factor, the reboiler's and condenser's duties in
cheme process propagate, the rules and the example plant."""

import math
import shutil
from pathlib import Path

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
    # the product reaches its 99.5 wt% specification, with a calculated recovery
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
