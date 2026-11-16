"""The batch still's gaps the library's batch entries found (ADR 0068): an end at a temperature
that lands where it is (core#198), a component at zero amount that needs no vapour pressure
(core#214), components in a phase of their own out of the liquid's mole fractions, a cut's own
pressure and boil-up (a boil-up in m3/h too), and the heat-up's time; against closed forms
where they exist, and a still that uses none of it as before."""

import copy
import math

import pytest

from chemeascode.domains.process.batch_still import (
    GAS_CONSTANT,
    report_text,
    solve_node,
    solve_still,
    still_report,
)
from chemeascode.domains.process.model import load
from chemeascode.domains.process.recipe import recipe_report
from chemeascode.domains.process.schema import Component, Still, VapourPressure
from tests import test_batch_still as still
from tests import test_heats_and_heat_up as heats

P_ATM = 101.325
BENZENE = VapourPressure.model_validate(still.BENZENE | {"provenance": "given"})
TOLUENE = VapourPressure.model_validate(still.TOLUENE | {"provenance": "given"})
COMPONENTS = {
    "A": Component.model_validate(
        {
            "id": "A",
            "name": "benzene",
            "molar_mass": 78.11,
            "heat_of_vaporization": 30720,
            "liquid_heat_capacity": 136,
            "vapour_pressure": still.BENZENE | {"provenance": "given"},
        }
    ),
    "B": Component.model_validate(
        {
            "id": "B",
            "name": "toluene",
            "molar_mass": 92.14,
            "heat_of_vaporization": 33180,
            "vapour_pressure": still.TOLUENE | {"provenance": "given"},
        }
    ),
    "P": Component.model_validate({"id": "P", "name": "product", "molar_mass": 128.17}),
    "S": Component.model_validate({"id": "S", "name": "salt", "molar_mass": 58.44}),
    "H": Component.model_validate({"id": "H", "name": "hydrogen", "molar_mass": 2.016}),
}


def _raoult(**kw):
    spec = {
        "volatility": {"model": "raoult", "provenance": "given", "source": "NIST WebBook"},
        "nonvolatile": ["P"],
        "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
        "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
        "outlets": {"distillate": "top", "residue": "bottom"},
        "provenance": "assumed",
    }
    return Still.model_validate(spec | kw)


def _boiling(vp: VapourPressure, p: float) -> float:
    """K where *vp* is *p* kPa: Antoine inverted (log10, bar, K)."""
    return vp.b / (vp.a - math.log10(p / 100.0)) - vp.c


def _bubble(x_a: float, x_b: float, p: float) -> float:
    """K where x_A P_A(T) + x_B P_B(T) = p (bisection, independent of the still's own)."""
    lo, hi = 200.0, 600.0
    for _ in range(200):
        t = (lo + hi) / 2
        lo, hi = (lo, t) if x_a * BENZENE.kpa(t) + x_b * TOLUENE.kpa(t) > p else (t, hi)
    return (lo + hi) / 2


# -- core#198: an end at a temperature --------------------------------------------------------


@pytest.mark.parametrize("unit, hours", [("kW", 1.0), ("kW", 3.7), ("kmol/h", 10.4113)])
def test_an_end_at_a_temperature_solves_wherever_the_still_passes(unit, hours):
    """core#198: an end at a temperature failed with "boils dry before its end" for some
    temperatures between two that solved. The bubble point converges to a tolerance from the
    last one's guess, so re-evaluating the stop where the bisection had found it could fall
    1e-9 K short of an end tested at 1e-15 K. In 1.11.0, many of these 180 ends failed; each
    must end at its temperature, the residue boiling there, the more distilled the hotter."""
    distilled = []
    for i in range(60):
        t_end = 380.5 + 0.5 * i  # the charge boils at 379.82 K
        spec = _raoult(
            boilup={"value": 25.0, "unit": unit, "provenance": "assumed"},
            end={"temperature": t_end},
        )
        result = solve_still(spec, {"A": 30, "B": 40, "P": 30}, None, COMPONENTS, P_ATM, hours)
        assert result.temperatures[1] == pytest.approx(t_end, abs=1e-6)
        r = result.residue
        total = sum(r.values())  # P dissolved: it counts in the liquid
        assert _bubble(r["A"] / total, r["B"] / total, P_ATM) == pytest.approx(t_end, abs=1e-6)
        distilled.append(sum(result.cuts[0].moles.values()))
    assert all(b > a for a, b in zip(distilled, distilled[1:], strict=False))


# -- core#214: a component at zero amount ----------------------------------------------------


def test_a_component_at_zero_amount_needs_no_vapour_pressure():
    """core#214: hydrogen vented whole by the reactor before is 0 in the still's charge and its
    swap's feed; it has no vapour pressure and need not be listed nonvolatile."""
    spec = _raoult(
        end={"residue": {"key": "A", "mole_fraction": 0.05}},
        feed={"stream": "F", "mode": "constant_level"},
    )
    result = solve_still(spec, {"A": 80, "P": 20, "H": 0.0}, {"B": 50, "H": 0.0}, COMPONENTS, P_ATM)
    assert "H" not in result.residue and not any("H" in c.moles for c in result.cuts)


def test_a_plant_whose_charge_lists_a_component_at_zero_validates_and_solves(tmp_path):
    flowsheet = still.FLOWSHEET.replace(
        "values: {A: 0.8, P: 0.2}", "values: {A: 0.8, P: 0.2, W: 0.0}"
    ).replace("values: {B: 1.0}", "values: {B: 1.0, W: 0.0}")
    assert flowsheet.count("W: 0.0") == 2
    ws = still._plant(tmp_path, flowsheet, still.TEMPLATE_W)
    assert not still._findings(ws)
    (unit,) = still_report(ws.root).units
    assert unit["problem"] is None and unit["sourced"], unit


# -- components in a phase of their own -------------------------------------------------------


def test_a_suspended_solid_does_not_dilute_the_liquid():
    """One volatile component and a salt in a phase of its own: the still boils at the pure
    component's boiling point all along; counted in the liquid, the salt raises it to where
    x_A P_A(T) = P (Raoult's law on the mixture)."""
    charge = {"A": 60.0, "S": 40.0}
    apart = solve_still(
        _raoult(nonvolatile=[], separate_phase=["S"], end={"distilled": 0.5}),
        charge,
        None,
        COMPONENTS,
        P_ATM,
    )
    t_b = _boiling(BENZENE, P_ATM)
    assert apart.temperatures == pytest.approx((t_b, t_b), abs=1e-6)
    assert all(t == pytest.approx(t_b, abs=1e-6) for _, _, t, _ in apart.profile)
    assert apart.residue["S"] == 40.0 and apart.residue["A"] == pytest.approx(10.0, rel=1e-9)
    counted = solve_still(
        _raoult(nonvolatile=["S"], end={"distilled": 0.5}), charge, None, COMPONENTS, P_ATM
    )
    assert counted.temperatures[0] == pytest.approx(_boiling(BENZENE, P_ATM / 0.6), abs=1e-6)
    assert counted.temperatures[1] == pytest.approx(_boiling(BENZENE, P_ATM / 0.2), abs=1e-6)


def test_a_separate_phase_leaves_the_liquids_distillation_as_without_it():
    """Benzene and toluene with a suspended salt apart: the cuts, the residue's liquid, the
    temperatures and the time are those of the binary alone; the residue end is the liquid's
    mole fraction; the salt stays in the residue."""
    end = {"residue": {"key": "A", "mole_fraction": 0.1}}
    binary = solve_still(_raoult(end=end), {"A": 50, "B": 50}, None, COMPONENTS, P_ATM)
    slurry = solve_still(
        _raoult(end=end, separate_phase=["S"]),
        {"A": 50, "B": 50, "S": 80},
        None,
        COMPONENTS,
        P_ATM,
    )
    for n in ("A", "B"):
        assert slurry.residue[n] == pytest.approx(binary.residue[n], rel=1e-9)
        assert slurry.cuts[0].moles[n] == pytest.approx(binary.cuts[0].moles[n], rel=1e-9)
    assert slurry.residue["S"] == 80 and slurry.cuts[0].moles["S"] == 0
    assert slurry.temperatures == pytest.approx(binary.temperatures, abs=1e-7)
    assert slurry.time == pytest.approx(binary.time, rel=1e-9)
    assert slurry.residue["A"] / (slurry.residue["A"] + slurry.residue["B"]) == pytest.approx(0.1)


def test_a_column_over_a_slurry_sees_the_liquid_only():
    column = {
        "stages": 4,
        "reflux": "constant",
        "ratio": 2.0,
        "provenance": "assumed",
    }
    end = {"residue": {"key": "A", "mole_fraction": 0.05}}
    binary = solve_still(
        _raoult(end=end, column=column), {"A": 50, "B": 50}, None, COMPONENTS, 101.325
    )
    slurry = solve_still(
        _raoult(end=end, column=column, separate_phase=["S"]),
        {"A": 50, "B": 50, "S": 30},
        None,
        COMPONENTS,
        P_ATM,
    )
    assert slurry.cuts[0].moles["A"] == pytest.approx(binary.cuts[0].moles["A"], rel=1e-8)
    assert slurry.time == pytest.approx(binary.time, rel=1e-8)


def test_a_separate_phase_is_checked(tmp_path):
    with pytest.raises(ValueError, match="separate_phase"):
        Still.model_validate(
            still._still(separate_phase=["A"]).model_dump(mode="json", by_alias=True)
        )
    flowsheet = still.FLOWSHEET.replace(
        "      nonvolatile: [P]\n", "      nonvolatile: [P]\n      separate_phase: [P, X]\n"
    )
    messages = [f.message for f in still._findings(still._plant(tmp_path, flowsheet))]
    assert any("separate_phase X is not a component" in m for m in messages), messages
    flowsheet = still.FLOWSHEET.replace(
        "      nonvolatile: [P]\n", "      separate_phase: [P]\n"
    ).replace("key: A, mole_fraction: 0.01", "key: P, mole_fraction: 0.5")
    messages = [f.message for f in still._findings(still._plant(tmp_path / "b", flowsheet))]
    assert any("residue key P is in a phase of its own" in m for m in messages), messages


# -- a cut's own pressure and boil-up ---------------------------------------------------------


def test_each_cut_at_its_own_pressure_and_boilup():
    """Benzene over a dissolved non-volatile P: a cut at 101.325 kPa(a) to 50 mol% benzene, at
    10 kmol/h, then a vacuum cut at 30 kPa(a) to 20 mol%, at 2 kmol/h. One volatile component
    distils whatever the pressure (the residue's benzene x P_P / (1 - x)), each cut ends where
    x P_A(T) = its pressure, and its time is what it boils up over its own rate."""
    spec = _raoult(
        end=None,
        cuts=[
            {"outlet": "c1", "end": {"residue": {"key": "A", "mole_fraction": 0.5}}},
            {
                "outlet": "c2",
                "pressure": 30.0,
                "boilup": {"value": 2.0, "unit": "kmol/h", "provenance": "assumed"},
                "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
            },
        ],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, {"A": 80.0, "P": 20.0}, None, COMPONENTS, P_ATM)
    c1, c2 = result.cuts
    assert c1.moles["A"] == pytest.approx(80 - 20, rel=1e-9)
    assert c2.moles["A"] == pytest.approx(20 - 5, rel=1e-9)
    assert result.residue["A"] == pytest.approx(5.0, rel=1e-9)
    assert (c1.pressure, c2.pressure) == (P_ATM, 30.0)
    assert c1.temperature == pytest.approx(_boiling(BENZENE, P_ATM / 0.5), abs=1e-6)
    assert c2.temperature == pytest.approx(_boiling(BENZENE, 30.0 / 0.2), abs=1e-6)
    assert c1.time == pytest.approx(60 / 10 * 3600, rel=1e-9)
    assert c2.time == pytest.approx(c1.time + 15 / 2 * 3600, rel=1e-9)
    (note,) = [n for n in result.notes if n.startswith("cut c2 at 30 kPa(a)")]
    assert f"steps from {c1.temperature:.5g} to {_boiling(BENZENE, 30 / 0.5):.5g} K" in note


def test_the_first_cuts_pressure_is_the_stills_from_the_start():
    spec = _raoult(
        end=None,
        cuts=[{"outlet": "c1", "pressure": 20.0, "end": {"distilled": 0.3}}],
        outlets={"residue": "bottom"},
    )
    result = solve_still(spec, {"A": 100.0}, None, COMPONENTS, P_ATM)
    t_b = _boiling(BENZENE, 20.0)
    assert result.temperatures == pytest.approx((t_b, t_b), abs=1e-6)
    assert not [n for n in result.notes if "kPa(a): the still steps" in n]


def test_a_boilup_in_m3_per_hour_is_the_vapours_volume():
    """Pure benzene at 20 kPa(a) boils at T_b all along: a vacuum pump drawing 500 m3/h of its
    vapour takes 500 P / (R T_b) kmol/h; half of 100 kmol over 4 h of flows a batch."""
    spec = _raoult(
        nonvolatile=[],
        pressure=20.0,
        boilup={"value": 500.0, "unit": "m3/h", "provenance": "assumed"},
        end={"distilled": 0.5},
    )
    result = solve_still(spec, {"A": 100.0}, None, COMPONENTS, 20.0, hours=4.0)
    t_b = _boiling(BENZENE, 20.0)
    rate = 500.0 * 20.0 / (GAS_CONSTANT * t_b)  # kmol/h of vapour
    assert result.time == pytest.approx(50.0 * 4.0 / rate * 3600.0, rel=1e-9)
    with pytest.raises(ValueError, match="m3/h needs volatility raoult"):
        still._still(boilup={"value": 1.0, "unit": "m3/h", "provenance": "assumed"})


def test_a_cuts_pressure_needs_raoult():
    with pytest.raises(ValueError, match="cut's pressure needs volatility raoult"):
        still._still(
            end=None,
            cuts=[{"outlet": "c1", "pressure": 10.0, "end": {"distilled": 0.3}}],
            outlets={"residue": "bottom"},
        )


def _cut_plant(tmp_path, cut_boilup=None, end="{distilled: 0.3}"):
    """test_batch_still's swap with its distillate in two cuts, the second at 50 kPa(a)."""
    extra = f", boilup: {cut_boilup}" if cut_boilup else ""
    flowsheet = (
        still.FLOWSHEET.replace(
            "      end: {residue: {key: A, mole_fraction: 0.01}}\n"
            "      outlets: {distillate: top, residue: bottom}\n",
            "      cuts:\n"
            f"        - {{outlet: top, end: {end}}}\n"
            f"        - {{outlet: top2, pressure: 50, end: {{distilled: 0.6}}{extra}}}\n"
            "      outlets: {residue: bottom}\n",
        )
        .replace(
            "      - {id: top, direction: out}\n",
            "      - {id: top, direction: out}\n      - {id: top2, direction: out}\n",
        )
        .replace(
            "  - {id: D, ports: [{id: in, direction: in}]}\n",
            "  - {id: D, ports: [{id: in, direction: in}]}\n"
            "  - {id: D2, ports: [{id: in, direction: in}]}\n",
        )
    )
    flowsheet += "  - id: S5\n    from: S.top2\n    to: D2.in\n    template: liquid\n"
    return still._plant(tmp_path, flowsheet)


def test_a_cuts_pressure_is_in_the_fingerprint_and_its_boilup_only_with_a_time(tmp_path):
    def inputs(ws):
        process, _ = load(ws.root)
        node = process.nodes["S"]
        from chemeascode.domains.process.batch_still import inlets_of

        return solve_node(process, node, inlets_of(process, node), "design")[1]

    plain = inputs(_cut_plant(tmp_path / "a"))
    assert plain["still"]["cuts"][1]["pressure"] == 50
    assert "pressure" not in plain["still"]["cuts"][0] and "cut_boilups" not in plain
    boil = "{value: 5, unit: kmol/h, provenance: assumed}"
    assert inputs(_cut_plant(tmp_path / "b", boil)) == plain
    timed = inputs(_cut_plant(tmp_path / "c", boil, end="{time: 3000}"))
    assert timed["cut_boilups"] == {"top2": {"value": 5.0, "unit": "kmol/h"}}
    (unit,) = still_report(_cut_plant(tmp_path / "d", boil).root).units
    second = unit["solution"]["cuts"][1]
    assert second["pressure_kPa"] == 50 and second["boilup"] == {"value": 5.0, "unit": "kmol/h"}
    assert "pressure_kPa" not in unit["solution"]["cuts"][0]
    report = still_report(_cut_plant(tmp_path / "e", boil).root)
    assert "at 50 kPa(a), boil-up 5 kmol/h" in report_text(report)


# -- the heat-up's time -----------------------------------------------------------------------


def test_the_heat_up_takes_time_at_the_boilups_heat_input():
    """Benzene over P, charged at 300 K, boiled up at 50 kW: the charge's heat-up to its bubble
    point, sum n cp (T_b - 300) per hour of flows times the hours, takes that over 50 kW."""
    from types import SimpleNamespace

    from chemeascode.domains.process.batch_still import _heat_up, _heat_up_time

    comps = dict(COMPONENTS)
    comps["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17, "liquid_heat_capacity": 200}
    )
    spec = _raoult(
        boilup={"value": 50.0, "unit": "kW", "provenance": "assumed"},
        heat_up=True,
        heat_up_time=True,
    )
    result = solve_still(spec, {"A": 8.0, "P": 2.0}, None, comps, P_ATM, hours=4.0)
    result.charge_temperature = 300.0
    _heat_up(result, comps)
    node = SimpleNamespace(id="S", still=spec)
    _heat_up_time(None, node, result, "design")
    bubble = _boiling(BENZENE, P_ATM / 0.8)
    kj = (8.0 * 136 + 2.0 * 200) * (bubble - 300.0) * 4.0
    assert result.heat_up_time == pytest.approx(kj / 50.0, rel=1e-6)


def test_a_forerun_the_vacuum_pump_limits_does_not_slow_the_heat_up():
    """A still boiled up at 50 kW whose forerun the vacuum pump limits (its own boil-up in
    m3/h): the heat-up takes the heater's 50 kW, not the mean over the cuts, which the slow
    forerun pulls down. A still boiled up in kmol/h takes the mean of the cuts at its own
    boil-up; one whose every cut has its own, the mean over the whole boil-up."""
    from types import SimpleNamespace

    from chemeascode.domains.process.batch_still import _heat_up, _heat_up_time

    comps = dict(COMPONENTS)
    comps["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17, "liquid_heat_capacity": 200}
    )
    pump = {"value": 5.0, "unit": "m3/h", "provenance": "assumed"}

    def timed(boilup, cuts):
        spec = _raoult(
            boilup=boilup,
            heat_up=True,
            heat_up_time=True,
            end=None,
            cuts=cuts,
            outlets={"residue": "bottom"},
        )
        result = solve_still(spec, {"A": 8.0, "P": 2.0}, None, comps, P_ATM, hours=4.0)
        result.charge_temperature = 300.0
        _heat_up(result, comps)
        _heat_up_time(None, SimpleNamespace(id="S", still=spec), result, "design")
        return result

    forerun = {"outlet": "c1", "end": {"distilled": 0.1}, "boilup": pump}
    main = {"outlet": "c2", "end": {"distilled": 0.6}}
    bubble = _boiling(BENZENE, P_ATM / 0.8)
    kj = (8.0 * 136 + 2.0 * 200) * (bubble - 300.0) * 4.0
    kw = timed({"value": 50.0, "unit": "kW", "provenance": "assumed"}, [forerun, main])
    assert kw.duty < 50.0  # the forerun's few m3/h pull the mean down
    assert kw.heat_up_time == pytest.approx(kj / 50.0, rel=1e-6)
    molar = timed({"value": 20.0, "unit": "kmol/h", "provenance": "assumed"}, [forerun, main])
    second = molar.cuts[1]
    rate = second.energy / (second.time - molar.cuts[0].time)
    assert molar.duty < rate
    assert molar.heat_up_time == pytest.approx(kj / rate, rel=1e-9)
    every = timed(
        {"value": 50.0, "unit": "kW", "provenance": "assumed"},
        [forerun, main | {"boilup": {"value": 20.0, "unit": "kmol/h", "provenance": "assumed"}}],
    )
    assert every.heat_up_time == pytest.approx(kj / every.duty, rel=1e-9)


def _timed_plant(tmp_path, heat_up_time=True, metal=None):
    recipe = copy.deepcopy(still.RECIPE)
    if metal is not None:
        recipe["unit_procedures"][0]["vessel"] = {
            "volume": 2.0,
            "metal_heat_capacity": metal,
            "provenance": "assumed",
        }
    ws = heats._still_plant(tmp_path, recipe=recipe)
    if heat_up_time:
        path = ws.root / "process/flowsheet.yaml"
        text = path.read_text().replace(
            "      heat_up: true\n", "      heat_up: true\n      heat_up_time: true\n"
        )
        path.write_text(text)
    return ws


@pytest.mark.parametrize("metal", [None, 2500.0])
def test_the_heat_up_time_is_in_the_report_and_the_recipes_distil(tmp_path, metal):
    """The swap of test_heats_and_heat_up (its charge and feed heated, 4 h of flows a batch,
    20 kmol/h boiled up), with and without C-101's metal: the heat terms besides the boil-up
    over the boil-up's mean heat input, in the still's report and the recipe's distil time; a
    still without heat_up_time as before."""
    (unit,) = still_report(_timed_plant(tmp_path / "t", metal=metal).root).units
    sol = unit["solution"]
    extra = sol["total_energy_kWh_per_batch"] - sol["energy_kWh_per_batch"]
    assert sol["heat_up_time_h"] == pytest.approx(extra / sol["duty_kW"], rel=1e-9)
    assert sol["time_h"] == pytest.approx(sol["boilup_time_h"] + sol["heat_up_time_h"], rel=1e-12)
    if metal:
        assert sol["duty_terms_kW"]["vessel metal"] > 0
    timed = recipe_report(_timed_plant(tmp_path / "r", metal=metal).root)
    plain = recipe_report(_timed_plant(tmp_path / "p", heat_up_time=False, metal=metal).root)
    (swap_t,) = [s for s in timed.steps if s.operation == "swap"]
    (swap_p,) = [s for s in plain.steps if s.operation == "swap"]
    assert swap_p.end - swap_p.start == pytest.approx(sol["boilup_time_h"], rel=1e-9)
    assert swap_t.end - swap_t.start == pytest.approx(sol["time_h"], rel=1e-9)
    (plain_unit,) = still_report(_timed_plant(tmp_path / "s", heat_up_time=False).root).units
    assert "heat_up_time_h" not in plain_unit["solution"]


def _ramp_plant(tmp_path, metal=2500.0):
    """The swap of _timed_plant charged at 330 K, its distillate in two cuts, the second at
    5 kPa(a), which ends the still below the charge's temperature, in C-101 with its metal."""
    path = _timed_plant(tmp_path, metal=metal).root / "process/flowsheet.yaml"
    text = (
        path.read_text()
        .replace(
            "      end: {residue: {key: A, mole_fraction: 0.01}}\n"
            "      outlets: {distillate: top, residue: bottom}\n",
            "      cuts:\n"
            "        - {outlet: top, end: {distilled: 0.3}}\n"
            "        - {outlet: top2, pressure: 5, end: {distilled: 0.6}}\n"
            "      outlets: {residue: bottom}\n",
        )
        .replace(
            "      - {id: top, direction: out}\n",
            "      - {id: top, direction: out}\n      - {id: top2, direction: out}\n",
        )
        .replace(
            "  - {id: D, ports: [{id: in, direction: in}]}\n",
            "  - {id: D, ports: [{id: in, direction: in}]}\n"
            "  - {id: D2, ports: [{id: in, direction: in}]}\n",
        )
        .replace("temperature: {value: 300,", "temperature: {value: 330,", 1)
    )
    path.write_text(text + "  - id: S5\n    from: S.top2\n    to: D2.in\n    template: liquid\n")
    return path.parent.parent


def test_a_vacuum_ramp_ending_below_the_charge_times_the_metals_heat_up(tmp_path):
    """A still charged at 330 K, boiling up from its bubble point T_0 at 1 atm and ending near
    305 K at 5 kPa(a): its metal's term in the duty is negative (C_m (T_end - 330) over the
    hours), but it heats with the charge from 330 K to T_0 first. The heat-up takes the charge's
    and the feed's heat-up plus C_m (T_0 - 330), not their sum less the metal's cooling."""
    (unit,) = still_report(_ramp_plant(tmp_path / "t")).units
    sol = unit["solution"]
    first, end = sol["temperatures_K"]
    assert end < 330.0 < first
    terms = sol["duty_terms_kW"]
    assert terms["vessel metal"] == pytest.approx(2500.0 * (end - 330.0) / (4 * 3600), rel=1e-9)
    heated = (terms["charge heat-up"] + terms["feed heat-up"]) * 4.0  # kWh per batch
    metal = 2500.0 * (first - 330.0) / 3600.0  # kWh: C-101's metal to T_0
    assert sol["heat_up_time_h"] == pytest.approx((heated + metal) / sol["duty_kW"], rel=1e-9)
    timed = recipe_report(_ramp_plant(tmp_path / "r"))
    (swap,) = [s for s in timed.steps if s.operation == "swap"]
    assert swap.end - swap.start == pytest.approx(sol["time_h"], rel=1e-9)


def test_heat_up_time_needs_raoult():
    with pytest.raises(ValueError, match="heat_up_time needs volatility raoult"):
        still._still(heat_up_time=True)


# -- a still that uses none of it -------------------------------------------------------------


def test_a_still_without_the_new_fields_dumps_as_before():
    spec = _raoult(
        end=None,
        cuts=[{"outlet": "c1", "end": {"distilled": 0.3}}],
        outlets={"residue": "bottom"},
    )
    dump = spec.model_dump(mode="json")
    assert "separate_phase" not in dump and "heat_up_time" not in dump
    assert set(dump["cuts"][0]) == {"outlet", "end"}
