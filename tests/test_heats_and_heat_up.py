"""Heats of solution and mixing, the charge's heat-up and the vessel's metal (ADR 0063): a
dose's heat_of_solution in the semi-batch's heat, peak cooling duty, adiabatic balance, duty and
dT_ad (not the MTSR), against closed forms; a batch's and a still's charge heated to its
temperature or bubble point; a recipe vessel's metal_heat_capacity in the jacket times, the
heat of a heat-up and in the models' duties; and plants that use none of it."""

import copy
import math
from typing import ClassVar

import pytest
import yaml

from chemeascode.domains.process import recipe as recipe_module
from chemeascode.domains.process.duties import crystallizer_duty
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.recipe import Vessel, recipe_report, recipe_text
from chemeascode.domains.process.schema import Batch, Dosing, Step, Still
from chemeascode.domains.process.stirred_tank import Dose, solve_batch
from chemeascode.domains.safety.reaction_hazards import screen
from tests import test_batch_still as still
from tests import test_duties as duties
from tests import test_recipe as recipes
from tests import test_semibatch as semi
from tests import test_semibatch_vent as vents

DOSING = semi.DOSING
HEAT = semi.HEAT  # kJ/kmol of the reaction, exothermic
SOLUTION = -20000.0  # kJ/kmol (J/mol) of A as it mixes in, exothermic


def _dose(t=300.0, solution=-SOLUTION, moles=1.0):
    """1 kmol of A dosed over DOSING s, releasing *solution* kJ/kmol as it mixes in."""
    return Dose({"A": moles}, t, [(0.0, DOSING, 1.0)], {}, solution * moles)


# -- the heat of solution, closed forms ---------------------------------------------------------


def test_the_heat_of_solution_is_a_term_of_the_isothermal_semibatch():
    """All of the dose mixes in: its heat of solution is n dH_sol, whatever the reaction does;
    the reaction's term is as without it."""
    plain = semi._semibatch(1e-2)
    mixed = semi._semibatch(1e-2, doses=[_dose()])
    assert mixed.heat_terms["solution"] == pytest.approx(SOLUTION, rel=1e-12)
    assert mixed.heat_terms["reaction"] == pytest.approx(plain.heat_terms["reaction"], rel=1e-12)
    assert "solution" not in plain.heat_terms  # a dose without heat_of_solution: as in 1.9.0
    assert mixed.extents == plain.extents and mixed.outlet == plain.outlet


def test_the_peak_cooling_duty_takes_the_heat_of_solution_at_the_dosing_rate():
    """Fast first order, dosed at a constant q: the reaction's heat rate q (-dH)(1 - exp(-k t))
    peaks when the dosing ends, and the mixing releases q (-dH_sol) all along; per m3 of the end
    volume, 0.6 m3."""
    k = 1e-2
    result = semi._semibatch(k, doses=[_dose()])
    q = 1.0 / DOSING
    exact = q * (-HEAT * (1 - math.exp(-k * DOSING)) - SOLUTION) / 0.6
    assert result.peak_cooling_duty == pytest.approx(exact, rel=1e-6)
    plain = semi._semibatch(k)
    assert result.peak_cooling_duty - plain.peak_cooling_duty == pytest.approx(
        q * -SOLUTION / 0.6, rel=1e-3
    )


def test_an_adiabatic_semibatch_takes_the_heat_of_solution_into_its_balance():
    """Equal heat capacities: C_end T_end = C_charge T_0 + C_dose T_dose + (-dH) extent +
    (-dH_sol) n_dose."""
    result = semi._semibatch(1e-3, semi._batch(heat="adiabatic"), doses=[_dose(290.0)])
    extent = result.extents["R1"]
    expected = (5.0 * 150.0 * 300.0 + 1.0 * 150.0 * 290.0 - HEAT * extent - SOLUTION) / (
        6.0 * 150.0
    )
    assert result.temperature == pytest.approx(expected, rel=1e-7)


def test_the_heat_of_solution_is_not_in_the_cooling_failure():
    """Released as the dose mixes in, it is not accumulated: with the dosing stopped by a
    cooling failure none of it is left, so the isothermal batch's MTSR is as without it."""
    plain = semi._semibatch(1e-4)
    mixed = semi._semibatch(1e-4, doses=[_dose()])
    assert mixed.cooling_failure == pytest.approx(plain.cooling_failure, rel=1e-12)


def test_the_schema_of_the_heat_of_solution_and_the_heat_up():
    dose = Dosing.model_validate(
        {
            "stream": "D",
            "time": 60,
            "heat_of_solution": {"values": {"A": -75000}, "provenance": "assumed"},
        }
    )
    assert dose.heat_of_solution.values == {"A": -75000} and dose.heat_of_solution.unit == "kJ/kmol"
    with pytest.raises(ValueError):
        Dosing.model_validate(
            {"stream": "D", "time": 60, "heat_of_solution": {"values": {}, "provenance": "assumed"}}
        )
    with pytest.raises(ValueError, match="heat_up: an isothermal batch"):
        Batch.model_validate(
            {"time": 5, "heat": "adiabatic", "heat_up": True, "provenance": "assumed"}
        )
    with pytest.raises(ValueError, match="heat_up needs volatility raoult"):
        Still.model_validate(
            {
                "volatility": {"model": "constant", "alpha": {"A": 2.0}, "provenance": "assumed"},
                "boilup": {"value": 1, "unit": "kmol/h", "provenance": "assumed"},
                "end": {"distilled": 0.5},
                "outlets": {"distillate": "d", "residue": "r"},
                "heat_up": True,
                "provenance": "assumed",
            }
        )
    # left out of the dumps when not given: the fingerprints of 1.9.0 stay
    assert "heat_of_solution" not in Dosing.model_validate({"stream": "D", "time": 1}).model_dump()
    assert "heat_up" not in Batch.model_validate({"time": 5, "provenance": "assumed"}).model_dump()
    assert (
        "metal_heat_capacity" not in Vessel.model_validate({"provenance": "assumed"}).model_dump()
    )


# -- the heat of solution in a plant --------------------------------------------------------------

MIXING = "{stream: S2, time: 3600, heat_of_solution: {values: {A: -20000}, provenance: assumed}}"


def _mixing(flowsheet):
    return flowsheet.replace("{stream: S2, time: 3600}", MIXING)


def test_propagate_writes_the_heat_of_solution_into_the_duty(tmp_path):
    ws = semi._plant(tmp_path, _mixing(duties._cooled()))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level != "info"], [
        f.format() for f in result.findings
    ]
    q1 = duties._streams(ws)["Q1"]["state"]["design"]["duty"]
    assert q1["provenance"] == "calculated"
    assert q1["value"] == pytest.approx(duties._removed() - SOLUTION / 3600.0, rel=1e-5)
    (row,) = reactor_report(ws.root).reactors
    terms = row["model_duty"]["terms_kW"]
    assert terms["solution"] == pytest.approx(SOLUTION / 3600.0, rel=1e-9)
    assert "heat of solution as they mix in" in row["model_duty"]["basis"]
    # a changed heat of solution makes the duty stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("A: -20000", "A: -30000"))
    process, _ = load(ws.root)
    stale = [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert any("Q1" in f.message for f in stale), [f.format() for f in stale]


def test_the_screening_counts_the_heat_of_solution_in_dt_ad_not_the_mtsr(tmp_path):
    """dT_ad: the reaction's and the dose's heat of solution over the whole batch's heat
    capacity, 6 kmol x 150 kJ/(kmol K); the MTSR is the model's cooling failure, as without."""
    (plain,) = screen(semi._plant(tmp_path / "plain").root).entries
    (mixed,) = screen(semi._plant(tmp_path / "mixed", _mixing(semi.FLOWSHEET)).root).entries
    rise = -SOLUTION / (6 * 150.0)
    assert mixed.adiabatic_rise == pytest.approx(-HEAT / (6 * 150.0) + rise, rel=1e-6)
    assert mixed.heat_of_solution["adiabatic_rise_K"] == pytest.approx(rise, rel=1e-9)
    assert mixed.heat_of_solution["in_mtsr"] is False
    assert mixed.mtsr == pytest.approx(plain.mtsr, rel=1e-12)
    assert any("not in the MTSR" in n for n in mixed.notes)
    assert plain.heat_of_solution is None


def test_the_recipe_jacket_check_takes_the_heat_of_solution(tmp_path):
    plain = recipes._plant(tmp_path / "plain", recipes._jacketed())
    ws = recipes._plant(tmp_path / "mixed", recipes._jacketed(), propagate=False)
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(_mixing(path.read_text()))
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    (before,) = recipe_report(plain.root).vessels
    (after,) = recipe_report(ws.root).vessels
    # the mixing's kW over the batch: q (-dH_sol) times the batch's 4.5 h of flows
    assert after.peak_duty - before.peak_duty == pytest.approx(-SOLUTION / 3600.0 * 4.5, rel=2e-3)


def test_a_partly_absorbed_gas_releases_its_heat_of_absorption_on_its_share(tmp_path):
    """absorbed 0.8: the liquid takes up 0.8 kmol of A, which releases its heat of absorption;
    the share passing to the vent none."""
    flowsheet = vents.FLOWSHEET.replace(
        "time: 3600}]",
        "time: 3600, absorbed: 0.8, heat_of_solution: {values: {A: -20000}, provenance: assumed}}]",
    )
    ws = vents._plant(tmp_path, flowsheet)
    (ws.root / "process/materials.yaml").write_text(
        vents.MATERIALS.replace("{id: gas, components: [G]}", "{id: gas, components: [A, G]}")
    )
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    (row,) = reactor_report(ws.root).reactors
    assert row["model_duty"]["terms_kW"]["solution"] == pytest.approx(
        0.8 * SOLUTION / 3600.0, rel=1e-9
    )
    (entry,) = screen(ws.root).entries
    assert entry.adiabatic_rise == pytest.approx(0.8 * (-HEAT - SOLUTION) / (5.8 * 150.0), rel=1e-6)


def test_rules_of_the_heat_of_solution(tmp_path):
    stray = semi.FLOWSHEET.replace(
        "{stream: S2, time: 3600}",
        "{stream: S2, time: 3600, heat_of_solution: {values: {X: -1, B: -2}, provenance: assumed}}",
    )
    messages = semi._messages(semi._plant(tmp_path, stray))
    assert any("heat_of_solution of the undeclared component(s) X" in m for m in messages)
    assert any("heat_of_solution of B, which the dose S2 does not carry" in m for m in messages)
    assert not semi._messages(semi._plant(tmp_path / "ok", _mixing(semi.FLOWSHEET)))


# -- the charge's heat-up -------------------------------------------------------------------------


def test_a_batch_with_heat_up_heats_its_charge_to_the_batch_temperature():
    """The charge enters at 290 K, the batch is held at 300 K: n cp dT = 5 x 150 x 10 kJ;
    without heat_up the model holds the batch at 300 K from the start, as in 1.9.0."""

    def solved(**kw):
        return solve_batch(
            semi._reactions(1e-2),
            {"S": 5.0},
            290.0,
            101.325,
            semi._batch(**kw),
            {},
            semi.Liquid(semi.V),
            semi.CP,
            isothermal_at=300.0,
            doses=[Dose({"A": 1.0}, 300.0, [(0.0, DOSING, 1.0)])],
        )

    plain, heated = solved(), solved(heat_up=True)
    assert "charge heat-up" not in plain.heat_terms
    assert heated.heat_terms["charge heat-up"] == pytest.approx(5 * 150.0 * 10.0, rel=1e-12)
    assert heated.heat_terms["reaction"] == pytest.approx(plain.heat_terms["reaction"])
    assert heated.charge_temperature == 290.0 and heated.temperature == 300.0
    without_cp = solve_batch(
        semi._reactions(1e-2),
        {"S": 5.0},
        290.0,
        101.325,
        semi._batch(heat_up=True),
        {},
        semi.Liquid(semi.V),
        {"A": 150.0, "B": 150.0},
        isothermal_at=300.0,
        doses=[Dose({"A": 1.0}, 300.0, [(0.0, DOSING, 1.0)])],
    )
    assert without_cp.heat_terms is None and "heat_up" in without_cp.heat_missing[0]


STILL_CP = (
    still.MATERIALS.replace(
        "    heat_of_vaporization: 30720\n",
        "    heat_of_vaporization: 30720\n    liquid_heat_capacity: 136\n",
    )
    .replace(
        "    heat_of_vaporization: 33180\n",
        "    heat_of_vaporization: 33180\n    liquid_heat_capacity: 157\n",
    )
    .replace("molar_mass: 128.17}", "molar_mass: 128.17, liquid_heat_capacity: 200}")
)
#: the still of test_batch_still, its charge S1 at 300 K (benzene 0.8, the non-volatile P 0.2)
#: and 4 h of flows a batch
STILL_FLOWSHEET = still.FLOWSHEET.replace("units: {flow: kmol/h}", "units: {flow: kg/h}")


def _bubble(x=0.8, p=101.325):
    """K where x P_A(T) = P: the charge's bubble point (P does not boil)."""
    from chemeascode.domains.process.schema import VapourPressure

    vp = VapourPressure.model_validate(still.BENZENE | {"provenance": "given"})
    lo, hi = 300.0, 450.0
    for _ in range(100):
        t = (lo + hi) / 2
        lo, hi = (lo, t) if x * vp.kpa(t) > p else (t, hi)
    return (lo + hi) / 2


def _still_plant(tmp_path, heat_up=True, recipe=None):
    flowsheet = STILL_FLOWSHEET
    if heat_up:
        flowsheet = flowsheet.replace("    still:\n", "    still:\n      heat_up: true\n")
    return still._plant(
        tmp_path, flowsheet=flowsheet, materials=STILL_CP, recipe=recipe or still.RECIPE
    )


def _charge_moles():
    """kmol/h of the charge: 100 kg/h of benzene 0.8, P 0.2 (mole fractions)."""
    mw = 0.8 * 78.11 + 0.2 * 128.17
    return 100.0 / mw * 0.8, 100.0 / mw * 0.2


def _mixing_temperature(sol, fed_share):
    """K of the still as the swap's feed mixes in at constant level (fed = boiled up): the
    profile's temperature averaged over the share distilled while it feeds (trapezoids)."""
    points = [(p["distilled"], p["temperature_K"]) for p in sol["profile"]]
    area = 0.0
    for (a, ta), (b, tb) in zip(points, points[1:], strict=False):
        if a >= fed_share:
            break
        top = min(b, fed_share)
        tb = ta + (tb - ta) * (top - a) / (b - a)
        area += (top - a) * (ta + tb) / 2
    return area / fed_share


def test_a_still_with_heat_up_heats_its_charge_to_its_bubble_point(tmp_path):
    """The charge from 300 K to its bubble point, and the swap's feed (B, 120 kg/h at 300 K)
    to the still's temperature as it mixes in: F cp (T_mix - 300)."""
    from chemeascode.domains.process.batch_still import report_text, still_report

    report = still_report(_still_plant(tmp_path).root)
    (unit,) = report.units
    sol = unit["solution"]
    a, p = _charge_moles()
    bubble = _bubble()
    assert sol["temperatures_K"][0] == pytest.approx(bubble, abs=1e-4)
    heat_up = (a * 136.0 + p * 200.0) * (bubble - 300.0)  # kJ/h: per hour of flows
    assert sol["heat_up_kWh_per_batch"] == pytest.approx(heat_up * 4.0 / 3600.0, rel=1e-5)
    assert sol["duty_terms_kW"]["charge heat-up"] == pytest.approx(heat_up / 3600.0, rel=1e-5)
    fed = 120.0 / 92.14  # kmol/h of toluene
    t_mix = _mixing_temperature(sol, fed / (a + p + fed))
    assert bubble < t_mix < sol["temperatures_K"][1]
    feed_heat = fed * 157.0 * (t_mix - 300.0)
    assert sol["duty_terms_kW"]["feed heat-up"] == pytest.approx(feed_heat / 3600.0, rel=2e-3)
    assert sol["feed_heat_up_kWh_per_batch"] == pytest.approx(
        sol["duty_terms_kW"]["feed heat-up"] * 4.0, rel=1e-9
    )
    assert sol["year_average_duty_kW"] == pytest.approx(
        sum(sol["duty_terms_kW"][k] for k in ("boil-up", "charge heat-up", "feed heat-up")),
        rel=1e-12,
    )
    # the whole energy per batch is on the year average's basis; the latent heat stays apart
    assert sol["total_energy_kWh_per_batch"] == pytest.approx(
        sol["year_average_duty_kW"] * 4.0, rel=1e-12
    )
    assert sol["energy_kWh_per_batch"] == pytest.approx(
        sol["duty_terms_kW"]["boil-up"] * 4.0, rel=1e-9
    )
    text = report_text(report)
    assert f"year average {sol['year_average_duty_kW']:.6g} kW" in text
    assert f"whole duty {sol['total_energy_kWh_per_batch']:.4g} kWh per batch" in text
    assert text.count("year average") == 1
    # the assumptions say what the duty holds, not that there is no heat-up
    assumptions = unit["assumptions"]
    assert not any("no heat-up to the bubble point" in a for a in assumptions)
    assert not any(
        a.startswith("the duty is the vapour's latent heat (") and a.endswith(")")
        for a in assumptions
    )
    assert any(a.startswith("heat_up: the charge heated") and "the feed" in a for a in assumptions)
    (plain,) = still_report(_still_plant(tmp_path / "plain", heat_up=False).root).units
    assert "duty_terms_kW" not in plain["solution"]  # as in 1.9.0
    assert "total_energy_kWh_per_batch" not in plain["solution"]
    assert plain["solution"]["year_average_duty_kW"] == pytest.approx(
        sol["duty_terms_kW"]["boil-up"], rel=1e-12
    )
    from chemeascode.domains.process.batch_still import ASSUMPTIONS

    assert plain["assumptions"] == list(ASSUMPTIONS)


def test_a_swap_without_the_feeds_heat_capacity_has_no_duty_and_says_why(tmp_path):
    from chemeascode.domains.process.batch_still import still_report

    materials = STILL_CP.replace(
        "    heat_of_vaporization: 33180\n    liquid_heat_capacity: 157\n",
        "    heat_of_vaporization: 33180\n",
    )
    flowsheet = STILL_FLOWSHEET.replace("    still:\n", "    still:\n      heat_up: true\n")
    ws = still._plant(tmp_path, flowsheet=flowsheet, materials=materials, recipe=still.RECIPE)
    (unit,) = still_report(ws.root).units
    sol = unit["solution"]
    assert sol["year_average_duty_kW"] is None
    assert "liquid_heat_capacity of B (the feed)" in sol["duty_missing"][0]


# -- the vessel's metal ---------------------------------------------------------------------------


def test_the_metal_lengthens_the_jacket_times_and_has_its_heat(tmp_path):
    """t = (C + C_m) / (U A) ln((T_m - T_0) / (T_m - T_1)), the metal at the content's
    temperature; its heat C_m (T_1 - T_0) per batch beside the content's."""
    recipe = recipes._jacketed(metal_heat_capacity=2000.0)
    ops = recipe["unit_procedures"][0]["operations"]
    ops.insert(1, {"id": "heatup", "kind": "heat", "temperatures": [290, 300]})
    ops.insert(4, {"id": "cooldown", "kind": "cool", "temperatures": [300, 290]})
    result = recipe_report(recipes._plant(tmp_path, recipe).root)
    d = (16 / math.pi) ** (1 / 3)
    bottom = math.pi * d**2 / 4

    def time(capacity, volume, medium, start, end):
        ua = 0.4 * (math.pi * d * volume / bottom + bottom)
        return capacity / ua * math.log((medium - start) / (medium - end)) / 3600

    steps = {s.operation: s for s in result.steps if s.procedure == "UP1"}
    heat, cool = steps["heatup"], steps["cooldown"]
    charge, end = 5 * 150 * 4.5, 6 * 150 * 4.5  # kJ/K of the content, before and after the dose
    assert heat.end - heat.start == pytest.approx(time(charge + 2000, 2.25, 350, 290, 300))
    assert cool.end - cool.start == pytest.approx(time(end + 2000, 2.7, 250, 300, 290))
    up, down = result.heats
    assert (up.operation, up.content_kJ, up.metal_kJ) == (
        "heatup",
        pytest.approx(charge * 10),
        20000,
    )
    assert (down.content_kJ, down.metal_kJ) == (pytest.approx(-end * 10), -20000)
    assert up.mean_kW == pytest.approx(up.kJ / ((heat.end - heat.start) * 3600))
    assert up.year_average_kW == pytest.approx(
        up.kJ * result.batches_per_year / 8000 / 3600, rel=1e-12
    )
    assert "vessel metal 20 MJ" in recipe_text(result)
    assert result.as_dict()["heats"][0]["kJ"] == pytest.approx(up.kJ)


def test_a_recipe_without_jacket_times_reports_no_heats(tmp_path):
    result = recipe_report(recipes._plant(tmp_path).root)
    assert result.heats == [] and "heats" not in result.as_dict()


def test_a_recipe_without_a_vessels_metal_reports_as_in_1_9_0(tmp_path):
    """Jacket-timed heat and cool operations without metal_heat_capacity: no heats, no lines."""
    recipe = recipes._jacketed()
    ops = recipe["unit_procedures"][0]["operations"]
    ops.insert(1, {"id": "heatup", "kind": "heat", "temperatures": [290, 300]})
    ops.insert(4, {"id": "cooldown", "kind": "cool", "temperatures": [300, 290]})
    result = recipe_report(recipes._plant(tmp_path, recipe).root)
    assert {s.operation for s in result.steps} >= {"heatup", "cooldown"}
    assert result.heats == [] and "heats" not in result.as_dict()
    text = recipe_text(result)
    assert "heat-up heatup" not in text and "cool-down cooldown" not in text
    # with metal, a cool-down's metal heat is negative, never -0.0 for want of metal
    metal = recipes._jacketed(metal_heat_capacity=500.0)
    metal["unit_procedures"][0]["operations"] = ops
    up, down = recipe_report(recipes._plant(tmp_path / "metal", metal).root).heats
    assert (up.metal_kJ, down.metal_kJ) == (5000.0, -5000.0)


def _held_at_300(tmp_path, recipe, heat_up=True, cooling=False):
    """The recipe's semi-batch R charged at 290 K and held at 300 K (its outlet's given
    temperature), with *heat_up*; *cooling*: its duty on a cooling-water stream Q1."""
    ws = recipes._plant(tmp_path, recipe, propagate=False)
    path = ws.root / "process/flowsheet.yaml"
    text = path.read_text()
    if heat_up:
        text = text.replace(
            "batch: {dosing: [{stream: S2, time: 3600}], time: 1800, ",
            "batch: {dosing: [{stream: S2, time: 3600}], time: 1800, heat_up: true, ",
        )
    if cooling:
        text = (
            text.replace("products:\n", "products:\n" + duties.CW)
            .replace(
                "{id: dose, direction: in}, {id: out, direction: out}]",
                "{id: dose, direction: in}, {id: out, direction: out}, "
                "{id: q, direction: out, kind: energy}]",
            )
            .rstrip("\n")
            + "\n  - {id: Q1, kind: energy, from: R.q, to: CW.r}\n"
        )
    text = text.replace(
        "        temperature: {value: 300, provenance: given}\n",
        "        temperature: {value: 290, provenance: given}\n",
        1,
    ).replace(
        "  - id: S3\n    from: R.out\n    to: C.in\n    template: liquid\n",
        "  - id: S3\n    from: R.out\n    to: C.in\n    template: liquid\n"
        "    state:\n      design:\n        temperature: {value: 300, provenance: given}\n",
    )
    path.write_text(text)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    return ws


def test_the_metal_and_the_heat_up_are_terms_of_the_semibatchs_duty(tmp_path):
    """The charge enters at 290 K, the batch is held at 300 K (its outlet's given temperature):
    heat_up adds 5 x 150 x 10 kJ/h, and the vessel's 1000 kJ/K metal heated by 10 K each batch
    of 4.5 h of flows adds 1000 x 10 / 4.5 kJ/h."""
    ws = _held_at_300(tmp_path, recipes._jacketed(metal_heat_capacity=1000.0))
    (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "R"]
    terms = row["model_duty"]["terms_kW"]
    assert terms["charge heat-up"] == pytest.approx(5 * 150.0 * 10.0 / 3600.0, rel=1e-9)
    assert terms["vessel metal"] == pytest.approx(1000.0 * 10.0 / 4.5 / 3600.0, rel=1e-6)
    assert "the vessel's metal (UP1, 1000 kJ/K) from 290 to 300 K" in row["model_duty"]["basis"]


def test_without_heat_up_the_batch_leaves_the_metal_to_the_recipes_heat_up(tmp_path):
    """heat_up false: the model holds the batch at 300 K from the start, so neither the content's
    heat-up nor the metal's is in its duty; the recipe's heat operation 290 -> 300 K holds both
    (counted once)."""
    recipe = recipes._jacketed(metal_heat_capacity=1000.0)
    recipe["unit_procedures"][0]["operations"].insert(
        1, {"id": "heatup", "kind": "heat", "temperatures": [290, 300]}
    )
    ws = _held_at_300(tmp_path, recipe, heat_up=False)
    (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "R"]
    duty = row["model_duty"]
    assert "vessel metal" not in duty["terms_kW"] and "charge heat-up" not in duty["terms_kW"]
    assert duty["heat_in_kW"] == pytest.approx(sum(duty["terms_kW"].values()), rel=1e-12)
    assert "the vessel's metal (UP1) not included" in duty["basis"]
    (heat,) = recipe_report(ws.root).heats
    assert (heat.content_kJ, heat.metal_kJ) == (pytest.approx(5 * 150 * 4.5 * 10), 10000)
    # with heat_up the model holds both, from the charge's 290 K
    ws = _held_at_300(tmp_path / "heated", recipe)
    (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "R"]
    assert row["model_duty"]["terms_kW"]["vessel metal"] == pytest.approx(
        1000.0 * 10.0 / 4.5 / 3600.0, rel=1e-6
    )


def test_the_metal_is_a_term_of_the_stills_duty_and_its_pot_is_sized(tmp_path):
    """C-101's metal heated with the charge from 300 K to the still's end temperature, each
    batch of 4 h of flows; the still's pot is a vessel the recipe accepts (its given volume)."""
    from chemeascode.domains.process.batch_still import still_report

    recipe = copy.deepcopy(still.RECIPE)
    recipe["unit_procedures"][0]["vessel"] = {
        "volume": 2.0,
        "metal_heat_capacity": 2500.0,
        "provenance": "assumed",
    }
    ws = _still_plant(tmp_path, heat_up=False, recipe=recipe)
    (unit,) = still_report(ws.root).units
    sol = unit["solution"]
    start, end = sol["temperatures_K"]
    # without heat_up the model starts at the bubble point, and so does the metal
    assert sol["duty_terms_kW"]["vessel metal"] == pytest.approx(
        2500.0 * (end - start) / 4.0 / 3600.0, rel=1e-6
    )
    assert any(
        "vessel's metal (UP1, 2500 kJ/K)" in a and "from the bubble point" in a
        for a in unit["assumptions"]
    )
    assert any("no heat-up to the bubble point" in a for a in unit["assumptions"])
    (heated,) = still_report(_still_plant(tmp_path / "heated", recipe=recipe).root).units
    end = heated["solution"]["temperatures_K"][1]
    assert heated["solution"]["duty_terms_kW"]["vessel metal"] == pytest.approx(
        2500.0 * (end - 300.0) / 4.0 / 3600.0, rel=1e-6
    )
    result = recipe_report(ws.root)
    assert not [f.format() for f in result.findings if f.level == "error"]
    (vessel,) = result.vessels
    assert vessel.volume == 2.0
    # without a volume and the charge's liquid_molar_volume, the pot cannot be sized
    recipe["unit_procedures"][0]["vessel"].pop("volume")
    ws = _still_plant(tmp_path / "unsized", heat_up=False, recipe=recipe)
    messages = [f.message for f in recipe_report(ws.root).findings]
    assert any("no volume of what its still takes in" in m for m in messages)


def _solved_still(charge_temperature, temperatures, volatility="raoult", heat_up=True):
    """A still node and its solution (:class:`.StillResult`'s fields still_duty reads): 4 h of
    flows, 36000 kJ boiled up per batch (2.5 kW), no heat-up of the charge."""
    from types import SimpleNamespace

    node = SimpleNamespace(
        id="ST",
        still=SimpleNamespace(
            heat_up=heat_up, feed=None, volatility=SimpleNamespace(model=volatility)
        ),
    )
    result = SimpleNamespace(
        energy=36000.0,
        hours=4.0,
        notes=[],
        heat_up=0.0,
        heat_up_missing="",
        feed_heat_up=None,
        temperatures=temperatures,
        charge_temperature=charge_temperature,
        charge={},
        fed={},
    )
    return node, result, SimpleNamespace(components=dict)


def test_a_charge_above_its_bubble_point_heats_the_metal_from_the_bubble_point(monkeypatch):
    """benzoyl-chloride-1's crude enters its 5 kPa still at 413.15 K, above its 376.47 K bubble
    point: it takes no heat-up (its flash is not modelled), and the metal follows the content
    from the bubble point to the 396.94 K end, C_m (T_end - T_bubble), never from the charge's
    413.15 K down (a negative term that would make heat_up lower the duty)."""
    from chemeascode.domains.process.duties import still_duty

    monkeypatch.setattr(recipe_module, "metal_of", lambda process, node, case: (1500.0, 4.0, "UP"))
    node, result, process = _solved_still(413.15, (376.47, 396.94))
    duty = still_duty(node, result, process, "design")
    metal = 1500.0 * (396.94 - 376.47) / 4.0 / 3600.0
    assert duty.terms_kW["vessel metal"] == pytest.approx(metal, rel=1e-12)
    assert duty.terms_kW["charge heat-up"] == 0.0
    # the same as without heat_up, which starts at the bubble point
    node, result, process = _solved_still(413.15, (376.47, 396.94), heat_up=False)
    assert still_duty(node, result, process, "design").heat_kW == pytest.approx(duty.heat_kW)
    # a charge below its bubble point still heats the metal from its own temperature
    node, result, process = _solved_still(300.0, (376.47, 396.94))
    duty = still_duty(node, result, process, "design")
    assert duty.terms_kW["vessel metal"] == pytest.approx(
        1500.0 * (396.94 - 300.0) / 4.0 / 3600.0, rel=1e-12
    )


def test_a_still_at_constant_volatility_keeps_its_duty_in_a_vessel_with_metal(monkeypatch):
    """benzyl-chloroformate-1's degassing still T101 (constant alpha, no temperature modelled)
    shares the R-101 vessel with a semi-batch: the vessel's metal_heat_capacity leaves the
    still's boil-up duty as it is, with the metal left out and its basis saying why."""
    from chemeascode.domains.process.duties import still_duty

    monkeypatch.setattr(
        recipe_module, "metal_of", lambda process, node, case: (700.0, 4.0, "R-101")
    )
    node, result, process = _solved_still(None, None, volatility="constant", heat_up=False)
    duty = still_duty(node, result, process, "design")
    assert duty.heat_kW == pytest.approx(2.5) and not duty.missing
    assert duty.terms_kW == {"boil-up": pytest.approx(2.5)}
    assert (
        "the vessel's metal (R-101) not included: a still at constant volatility models no "
        "temperature" in duty.basis
    )
    # a raoult still without its temperatures is not known, as before
    node, result, process = _solved_still(None, None, heat_up=False)
    assert still_duty(node, result, process, "design").heat_kW is None


def test_the_metal_is_a_term_of_the_crystallizers_duty(monkeypatch):
    """The feed cooled from 333.15 to 313.15 K cools the vessel's 3000 kJ/K with it, each batch
    of 10 h of flows: 3000 x -20 / 10 kJ/h."""
    monkeypatch.setattr(recipe_module, "metal_of", lambda process, node, case: (3000.0, 10.0, "UP"))

    class Solved:
        energy: ClassVar[dict] = {
            "duty_kW": -3.5,
            "sensible_kJ_h": -12600.0,
            "crystallization_kJ_h": 0.0,
            "evaporation_kJ_h": 0.0,
            "feed_temperature_K": 333.15,
            "temperature_K": 313.15,
            "basis": "lumped",
        }

    node = Step.model_validate({"id": "CR", "block": "B"})
    duty = crystallizer_duty(node, Solved(), process=object(), case="design")
    assert duty.terms_kW["vessel metal"] == pytest.approx(3000.0 * -20.0 / 10.0 / 3600.0)
    assert duty.heat_kW == pytest.approx(-3.5 + 3000.0 * -20.0 / 10.0 / 3600.0)
    assert duty.inputs["vessel_metal"]["heat_capacity"] == 3000.0
    # without process (the 1.9.0 call) the duty is the model's alone
    assert crystallizer_duty(node, Solved()).heat_kW == -3.5


def test_a_plant_without_the_new_fields_keeps_its_duties_and_fingerprints(tmp_path):
    """The semi-batch of test_duties: its written duty and the outlet's fingerprint do not
    change when the recipe gives a vessel without metal."""
    ws = semi._plant(tmp_path, duties._cooled())
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    streams = {s["id"]: s for s in data["streams"]}
    q1 = streams["Q1"]["state"]["design"]["duty"]
    assert q1["value"] == pytest.approx(duties._removed(), rel=1e-5)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]


# -- what changes only a duty leaves the outlets and the tears fresh -----------------------------


def _stale(ws):
    process, _ = load(ws.root)
    return sorted(
        {
            f.message.split(":")[0]
            for f in rules(process)
            if f.rule == "cheme.process-calculated-stale"
        }
    )


def _edit(ws, old, new, file="process/flowsheet.yaml"):
    path = ws.root / file
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def test_heat_up_and_a_heat_of_solution_make_only_the_duty_stale(tmp_path):
    """batch.heat_up and an isothermal batch's heat_of_solution change its duty, not its outlet:
    only the energy stream Q1 is stale, S3 (composition, flow) stays fresh."""
    ws = semi._plant(tmp_path, duties._cooled())
    run(ws, load(ws.root)[0], "design", write=True)
    assert _stale(ws) == []
    _edit(
        ws,
        "batch: {dosing: [{stream: S2, time: 3600}], ",
        "batch: {heat_up: true, dosing: [{stream: S2, time: 3600}], ",
    )
    stale = _stale(ws)
    assert stale and all("Q1" in m for m in stale), stale
    run(ws, load(ws.root)[0], "design", write=True)
    assert _stale(ws) == []
    _edit(ws, "{stream: S2, time: 3600}", MIXING)
    stale = _stale(ws)
    assert stale and all("Q1" in m for m in stale), stale


def test_the_vessels_metal_makes_only_the_duty_stale(tmp_path):
    ws = _held_at_300(tmp_path, recipes._jacketed(metal_heat_capacity=1000.0), cooling=True)
    q1 = duties._streams(ws)["Q1"]["state"]["design"]["duty"]
    assert q1["provenance"] == "calculated"
    assert _stale(ws) == []
    _edit(ws, "metal_heat_capacity: 1000.0", "metal_heat_capacity: 2000.0", "process/recipe.yaml")
    stale = _stale(ws)
    assert stale and all("Q1" in m for m in stale), stale


def test_a_tear_downstream_of_a_duty_only_input_keeps_its_fingerprint(tmp_path):
    """The tear fingerprint (loop_inputs) leaves out still.heat_up, still.condenser_port (the
    stream the condenser's duty is written on, ADR 0061), batch.heat_up and an isothermal
    batch's heats of solution; an adiabatic batch's heat of solution is in it."""
    from chemeascode.domains.process.recycle import loop_inputs

    def fingerprint(ws, tear):
        process, _ = load(ws.root)
        return loop_inputs(process, "design", [tear])

    assert fingerprint(_still_plant(tmp_path / "a", heat_up=False), "S4") == fingerprint(
        _still_plant(tmp_path / "b"), "S4"
    )
    ported = still._plant(
        tmp_path / "p",
        flowsheet=still.FLOWSHEET.replace(
            "    still:\n", "    still:\n      condenser_port: top\n"
        ),
        recipe=still.RECIPE,
    )
    assert "condenser_port: top" in (ported.root / "process/flowsheet.yaml").read_text()
    assert fingerprint(ported, "S4") == fingerprint(
        still._plant(tmp_path / "q", flowsheet=still.FLOWSHEET, recipe=still.RECIPE), "S4"
    )
    plain = semi._plant(tmp_path / "c")
    heated = semi._plant(
        tmp_path / "d",
        semi.FLOWSHEET.replace("batch: {", "batch: {heat_up: true, "),
    )
    mixed = semi._plant(tmp_path / "e", _mixing(semi.FLOWSHEET))
    assert fingerprint(plain, "S3") == fingerprint(heated, "S3") == fingerprint(mixed, "S3")
    adiabatic = semi.FLOWSHEET.replace("batch: {", "batch: {heat: adiabatic, ")
    assert fingerprint(semi._plant(tmp_path / "f", adiabatic), "S3") != fingerprint(
        semi._plant(tmp_path / "g", _mixing(adiabatic)), "S3"
    )
