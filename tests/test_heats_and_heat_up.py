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


def test_a_still_with_heat_up_heats_its_charge_to_its_bubble_point(tmp_path):
    from chemeascode.domains.process.batch_still import still_report

    (unit,) = still_report(_still_plant(tmp_path).root).units
    sol = unit["solution"]
    a, p = _charge_moles()
    bubble = _bubble()
    assert sol["temperatures_K"][0] == pytest.approx(bubble, abs=1e-4)
    heat_up = (a * 136.0 + p * 200.0) * (bubble - 300.0)  # kJ/h: per hour of flows
    assert sol["heat_up_kWh_per_batch"] == pytest.approx(heat_up * 4.0 / 3600.0, rel=1e-5)
    assert sol["duty_terms_kW"]["charge heat-up"] == pytest.approx(heat_up / 3600.0, rel=1e-5)
    assert sol["year_average_duty_kW"] == pytest.approx(
        sol["duty_terms_kW"]["boil-up"] + heat_up / 3600.0, rel=1e-9
    )
    (plain,) = still_report(_still_plant(tmp_path / "plain", heat_up=False).root).units
    assert "duty_terms_kW" not in plain["solution"]  # as in 1.9.0
    assert plain["solution"]["year_average_duty_kW"] == pytest.approx(
        sol["duty_terms_kW"]["boil-up"], rel=1e-12
    )


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


def test_the_metal_and_the_heat_up_are_terms_of_the_semibatchs_duty(tmp_path):
    """The charge enters at 290 K, the batch is held at 300 K (its outlet's given temperature):
    heat_up adds 5 x 150 x 10 kJ/h, and the vessel's 1000 kJ/K metal heated by 10 K each batch
    of 4.5 h of flows adds 1000 x 10 / 4.5 kJ/h."""
    recipe = recipes._jacketed(metal_heat_capacity=1000.0)
    ws = recipes._plant(tmp_path, recipe, propagate=False)
    path = ws.root / "process/flowsheet.yaml"
    text = path.read_text().replace(
        "batch: {dosing: [{stream: S2, time: 3600}], time: 1800, ",
        "batch: {dosing: [{stream: S2, time: 3600}], time: 1800, heat_up: true, ",
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
    (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "R"]
    terms = row["model_duty"]["terms_kW"]
    assert terms["charge heat-up"] == pytest.approx(5 * 150.0 * 10.0 / 3600.0, rel=1e-9)
    assert terms["vessel metal"] == pytest.approx(1000.0 * 10.0 / 4.5 / 3600.0, rel=1e-6)
    assert "the vessel's metal (UP1, 1000 kJ/K) from 290 to 300 K" in row["model_duty"]["basis"]


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
    end = sol["temperatures_K"][1]
    assert sol["duty_terms_kW"]["vessel metal"] == pytest.approx(
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
