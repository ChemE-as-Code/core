"""The batch still's jacket-limited boil-up and its activity coefficients (ADR 0078, core#182):
a boil-up from the jacket's UA and medium against the still's bubble point, against the
quadrature of its closed form, and a non-ideal liquid on modified Raoult's law with UNIFAC,
against Rayleigh's equation on an independent bubble point; a still that uses neither as
before."""

import math

import pytest

from chemeascode.domains.process.batch_still import (
    StillError,
    _heat_up,
    _heat_up_time,
    rules,
    solve_still,
    still_report,
)
from chemeascode.domains.process.model import load
from chemeascode.domains.process.schema import Boilup, Component, Still
from tests import test_batch_still as still
from tests.test_still_gaps import BENZENE, COMPONENTS, P_ATM, _boiling, _raoult

JACKET = {"value": 2.0, "unit": "kW/K", "medium_temperature": 450.0, "provenance": "assumed"}

# methanol and toluene as examples/process-solvent-swap gives them (NIST WebBook: Ambrose and
# Sprake 1970, Besley and Bottomley 1974): log10(P/bar) = a - b / (T/K + c)
MEOH = {"a": 5.20409, "b": 1581.341, "c": -33.5, "temperature_range": [288.1, 356.83]}
TOL = {"a": 4.07827, "b": 1343.943, "c": -53.773, "temperature_range": [308.52, 384.66]}
PAIR = {
    "M": Component.model_validate(
        {
            "id": "M",
            "name": "methanol",
            "cas": "67-56-1",
            "molar_mass": 32.042,
            "heat_of_vaporization": 37400,
            "vapour_pressure": MEOH | {"provenance": "given"},
        }
    ),
    "T": Component.model_validate(
        {
            "id": "T",
            "name": "toluene",
            "cas": "108-88-3",
            "molar_mass": 92.141,
            "heat_of_vaporization": 37100,
            "vapour_pressure": TOL | {"provenance": "given"},
        }
    ),
}


def _pair_still(activity, end):
    volatility = {"model": "raoult", "provenance": "assumed"}
    if activity is not None:
        volatility["activity"] = activity
    return Still.model_validate(
        {
            "volatility": volatility,
            "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
            "end": end,
            "outlets": {"distillate": "top", "residue": "bottom"},
            "provenance": "assumed",
        }
    )


def _antoine(data, t):
    return 100.0 * 10 ** (data["a"] - data["b"] / (t + data["c"]))


def _unifac_bubble(x_m):
    """K and the vapour's methanol fraction of methanol x_m in toluene at 1 atm: sum gamma_i
    x_i P_i(T) = P by bisection, the coefficients from core's other UNIFAC entry
    (``unifac_activity_coefficients``, thermo's from_subgroups) updated until T settles."""
    from chemeascode.integrations.thermo import unifac_activity_coefficients

    t = 350.0
    for _ in range(100):
        g = unifac_activity_coefficients(["67-56-1", "108-88-3"], t, [x_m, 1 - x_m])
        lo, hi = 250.0, 450.0
        for _ in range(100):
            mid = (lo + hi) / 2
            p = g[0] * x_m * _antoine(MEOH, mid) + g[1] * (1 - x_m) * _antoine(TOL, mid)
            lo, hi = (lo, mid) if p > P_ATM else (mid, hi)
        new = (lo + hi) / 2
        if abs(new - t) < 1e-10:
            break
        t = new
    return t, g[0] * x_m * _antoine(MEOH, t) / P_ATM


# -- the jacket --------------------------------------------------------------------------------


def test_a_jackets_boilup_follows_its_falling_driving_force():
    """Benzene over a dissolved non-volatile P, boiled up by a jacket (UA 2 kW/K, medium at
    450 K) to half the charge distilled: the vapour is benzene alone, the still at
    x_A P_A(T) = P, and each kmol takes lambda / (UA (T_m - T)). The time is that quadrature
    over the path (Simpson), the latent heat lambda S per batch, the peak duty UA (T_m - T_0)."""
    hours = 2.0
    spec = _raoult(boilup=JACKET, end={"distilled": 0.5})
    result = solve_still(spec, {"A": 60.0, "P": 40.0}, None, COMPONENTS, P_ATM, hours)
    latent = 30720.0
    ua, medium = JACKET["value"], JACKET["medium_temperature"]

    def temperature(s):
        x = (60.0 - s) / (100.0 - s)
        return _boiling(BENZENE, P_ATM / x)

    n = 2000
    width = 50.0 / n
    total = 0.0
    for i in range(n + 1):
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        total += weight * latent / (ua * (medium - temperature(i * width)))
    seconds = hours * total * width / 3
    assert result.time == pytest.approx(seconds, rel=1e-7)
    assert result.energy == pytest.approx(latent * 50.0 * hours, rel=1e-9)
    t0, t_end = result.temperatures
    assert t0 == pytest.approx(temperature(0.0), abs=1e-6)
    assert t_end == pytest.approx(temperature(50.0), abs=1e-6)
    assert result.peak_duty == pytest.approx(ua * (medium - t0), rel=1e-3)
    # a constant heat input at the jacket's start would be faster: the driving force falls
    start = _raoult(
        boilup={"value": ua * (medium - t0), "unit": "kW", "provenance": "assumed"},
        end={"distilled": 0.5},
    )
    constant = solve_still(start, {"A": 60.0, "P": 40.0}, None, COMPONENTS, P_ATM, hours)
    assert constant.time < 0.9 * result.time


def test_a_jacket_cannot_heat_the_still_to_its_medium():
    """An end at or above the medium's temperature is refused when read; a residue end the
    still would reach only above it stalls with the reason, not as a still boiling dry."""
    with pytest.raises(ValueError, match="at or above the jacket's medium"):
        _raoult(boilup=JACKET, end={"temperature": 450.0})
    with pytest.raises(ValueError, match="at or above the jacket's medium"):
        _raoult(
            end=None,
            cuts=[
                {"outlet": "c1", "end": {"temperature": 400.0}},
                {
                    "outlet": "c2",
                    "end": {"temperature": 430.0},
                    "boilup": JACKET | {"medium_temperature": 425.0},
                },
            ],
            outlets={"residue": "bottom"},
        )
    spec = _raoult(
        boilup=JACKET | {"medium_temperature": 400.0},
        end={"residue": {"key": "A", "mole_fraction": 0.05}},
    )
    with pytest.raises(StillError, match="nears its jacket's medium at 400 K"):
        solve_still(spec, {"A": 60.0, "P": 40.0}, None, COMPONENTS, P_ATM)


def test_a_jackets_boilup_is_declared_whole():
    with pytest.raises(ValueError, match="medium_temperature with unit kW/K"):
        Boilup.model_validate({"value": 2.0, "unit": "kW/K", "provenance": "assumed"})
    with pytest.raises(ValueError, match="medium_temperature with unit kW/K"):
        Boilup.model_validate(
            {"value": 2.0, "unit": "kW", "medium_temperature": 400.0, "provenance": "assumed"}
        )
    with pytest.raises(ValueError, match="kW/K needs volatility raoult"):
        still._still(boilup=JACKET)
    # a boil-up without a jacket dumps as before (the outlets' fingerprint)
    plain = Boilup.model_validate({"value": 2.0, "unit": "kW", "provenance": "assumed"})
    rate = {"value", "unit", "medium_temperature"}
    assert plain.model_dump(mode="json", include=rate) == {"value": 2.0, "unit": "kW"}
    jacket = Boilup.model_validate(JACKET)
    assert jacket.model_dump(mode="json", include=rate)["medium_temperature"] == 450.0


def test_a_jackets_heat_up_takes_its_own_time():
    """With heat_up_time, the charge's heat-up from 300 K to its bubble point T_0 takes the
    jacket's own time, C / UA ln((T_m - 300) / (T_m - T_0)), not the boil-up's mean input."""
    from types import SimpleNamespace

    comps = dict(COMPONENTS)
    comps["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17, "liquid_heat_capacity": 200}
    )
    spec = _raoult(boilup=JACKET, heat_up=True, heat_up_time=True)
    result = solve_still(spec, {"A": 8.0, "P": 2.0}, None, comps, P_ATM, hours=4.0)
    result.charge_temperature = 300.0
    _heat_up(result, comps)
    _heat_up_time(None, SimpleNamespace(id="S", still=spec), result, "design")
    bubble = _boiling(BENZENE, P_ATM / 0.8)
    capacity = (8.0 * 136 + 2.0 * 200) * 4.0  # kJ/K per batch
    exact = capacity / 2.0 * math.log((450.0 - 300.0) / (450.0 - bubble))
    assert result.heat_up_time == pytest.approx(exact, rel=1e-9)


# -- activity coefficients ---------------------------------------------------------------------


def test_a_non_ideal_still_follows_rayleigh_on_its_own_bubble_point():
    """Methanol 0.3 in toluene at 1 atm on UNIFAC, 30 % distilled: the residue's x satisfies
    Rayleigh's ln(W0 / W) = integral from x to x0 of dx / (y - x), with y from an independent
    modified-Raoult bubble point (Simpson); the still starts and ends at that bubble point."""
    spec = _pair_still("unifac", {"distilled": 0.3})
    result = solve_still(spec, {"M": 30.0, "T": 70.0}, None, PAIR, P_ATM)
    residue = result.residue
    x_end = residue["M"] / sum(residue.values())
    n = 200
    width = (0.3 - x_end) / n
    total = 0.0
    for i in range(n + 1):
        x = x_end + i * width
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        total += weight / (_unifac_bubble(x)[1] - x)
    assert total * width / 3 == pytest.approx(math.log(1 / 0.7), rel=1e-6)
    t0, t_end = result.temperatures
    assert t0 == pytest.approx(_unifac_bubble(0.3)[0], abs=1e-6)
    assert t_end == pytest.approx(_unifac_bubble(x_end)[0], abs=1e-6)
    ideal = solve_still(
        _pair_still(None, {"distilled": 0.3}), {"M": 30, "T": 70}, None, PAIR, P_ATM
    )
    assert ideal.temperatures[0] > t0 + 15.0  # the ideal liquid misses the positive deviation


def test_past_the_azeotrope_the_lighter_component_stays_in_the_still():
    """Methanol 0.97 in toluene: on UNIFAC the charge lies past the minimum-boiling azeotrope,
    so the vapour is leaner in methanol than the liquid and the residue grows richer in it; an
    ideal liquid strips it from the residue."""
    end = {"distilled": 0.3}
    charge = {"M": 97.0, "T": 3.0}
    real = solve_still(_pair_still("unifac", end), charge, None, PAIR, P_ATM)
    ideal = solve_still(_pair_still(None, end), charge, None, PAIR, P_ATM)

    def x_m(moles):
        return moles["M"] / sum(moles.values())

    assert x_m(real.residue) > 0.97 > x_m(real.cuts[0].moles)
    assert x_m(ideal.residue) < 0.97 < x_m(ideal.cuts[0].moles)
    assert _unifac_bubble(0.97)[1] < 0.97


def test_a_column_takes_the_non_ideal_volatilities_at_the_still():
    """A one-stage column is the still itself, with the activity coefficients too."""
    column = {"stages": 1, "reflux": "constant", "ratio": 2.0, "provenance": "assumed"}
    end = {"distilled": 0.3}
    plain = solve_still(_pair_still("unifac", end), {"M": 30, "T": 70}, None, PAIR, P_ATM)
    dump = _pair_still("unifac", end).model_dump(mode="json")
    spec = Still.model_validate(dump | {"column": column})
    ruled = solve_still(spec, {"M": 30, "T": 70}, None, PAIR, P_ATM)
    assert ruled.residue["M"] == pytest.approx(plain.residue["M"], rel=1e-7)
    assert ruled.time == pytest.approx(3.0 * plain.time, rel=1e-7)


def test_activity_needs_raoult_and_the_cas_numbers():
    with pytest.raises(ValueError, match="activity: with model raoult"):
        still._still(
            volatility={
                "model": "constant",
                "alpha": {"A": 2.5},
                "activity": "unifac",
                "provenance": "assumed",
            }
        )
    no_cas = {n: c.model_copy(update={"cas": ""}) for n, c in PAIR.items()}
    with pytest.raises(StillError, match="needs the CAS number .* none of M, T"):
        solve_still(
            _pair_still("unifac", {"distilled": 0.3}), {"M": 30, "T": 70}, None, no_cas, P_ATM
        )


# -- in a plant --------------------------------------------------------------------------------

CAS = {"A": "71-43-2", "B": "108-88-3", "P": "91-20-3"}


def _plant(tmp_path, cas=True, jacket=True, activity=True):
    materials = still.MATERIALS
    if cas:
        for n, number in CAS.items():
            materials = materials.replace(f"id: {n}\n", f"id: {n}\n    cas: {number}\n", 1)
        materials = materials.replace(
            "{id: P, name: product,", "{id: P, cas: 91-20-3, name: product,"
        )
    flowsheet = still.FLOWSHEET
    if jacket:
        flowsheet = flowsheet.replace(
            "boilup: {value: 20, unit: kmol/h,",
            "boilup: {value: 3, unit: kW/K, medium_temperature: 433.15,",
        )
    if activity:
        flowsheet = flowsheet.replace(
            "volatility: {model: raoult,", "volatility: {model: raoult, activity: unifac,"
        )
    return still._plant(tmp_path, flowsheet=flowsheet, materials=materials)


def test_a_plant_reports_its_jacket_and_its_activity_coefficients(tmp_path):
    (unit,) = still_report(_plant(tmp_path).root).units
    assert unit["problem"] is None
    assert "UNIFAC activity coefficients" in unit["detail"]
    assert "(jacket, medium at 433.15 K)" in unit["detail"]
    assert any(a.startswith("a non-ideal liquid") for a in unit["assumptions"])
    assert any(a.startswith("a jacket's boil-up") for a in unit["assumptions"])
    assert not any(a.startswith("an ideal liquid") for a in unit["assumptions"])
    (plain,) = still_report(_plant(tmp_path / "p", jacket=False, activity=False).root).units
    assert "UNIFAC" not in plain["detail"] and "jacket" not in plain["detail"]
    assert any(a.startswith("an ideal liquid") for a in plain["assumptions"])


def test_a_plant_without_cas_numbers_is_told_which(tmp_path):
    process, _ = load(_plant(tmp_path, cas=False).root)
    found = [f for f in rules(process) if "CAS number" in f.message]
    assert len(found) == 1 and found[0].level == "error"
    assert "none of A, B, P" in found[0].message
    process, _ = load(_plant(tmp_path / "ideal", cas=False, activity=False).root)
    assert not [f for f in rules(process) if "CAS number" in f.message]


def test_a_plant_on_a_jacket_reports_no_constant_boilup(tmp_path):
    """Review of #323: a jacket's boil-up falls as the pot heats, so the still's assumptions
    put it in place of the constant boil-up (with heat_up too), not beside it."""
    (unit,) = still_report(_plant(tmp_path, activity=False).root).units
    assert not any("constant boil-up" in a for a in unit["assumptions"])
    assert any(a.startswith("the jacket's boil-up from the start") for a in unit["assumptions"])
    heated = still.FLOWSHEET.replace(
        "boilup: {value: 20, unit: kmol/h,",
        "heat_up: true\n      boilup: {value: 3, unit: kW/K, medium_temperature: 433.15,",
    )
    materials = still.MATERIALS.replace(
        "molar_mass: 128.17}", "molar_mass: 128.17, liquid_heat_capacity: 200}"
    )
    plant = still._plant(tmp_path / "heated", flowsheet=heated, materials=materials)
    (unit,) = still_report(plant.root).units
    assert not any("constant boil-up" in a for a in unit["assumptions"])
    assert any("then the jacket's boil-up" in a for a in unit["assumptions"])


def test_a_column_plant_reports_its_activity_coefficients(tmp_path):
    """Review of #323: a column's assumptions have no ideal liquid to replace; the modified
    Raoult's law with UNIFAC is added, and the column's volatilities say they take the
    activity coefficients, not 'raoult or constant'."""
    ws = _plant(tmp_path)
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "      outlets: {distillate: top, residue: bottom}",
            "      column: {stages: 3, reflux: constant, ratio: 2.0, provenance: assumed}\n"
            "      outlets: {distillate: top, residue: bottom}",
        )
    )
    (unit,) = still_report(ws.root).units
    assert unit["problem"] is None
    assumptions = unit["assumptions"]
    assert any(a.startswith("a non-ideal liquid: modified Raoult's law") for a in assumptions)
    assert any(a.startswith("the K-values gamma_i P_i(T) / P") for a in assumptions)
    assert not any("(raoult) or constant" in a for a in assumptions)
    assert not any("constant boil-up" in a for a in assumptions)


def test_validate_names_the_jackets_unit_without_a_latent_heat(tmp_path):
    materials = still.MATERIALS.replace("    heat_of_vaporization: 33180\n", "")
    flowsheet = still.FLOWSHEET.replace(
        "boilup: {value: 20, unit: kmol/h,",
        "boilup: {value: 3, unit: kW/K, medium_temperature: 433.15,",
    )
    found = still._findings(still._plant(tmp_path, flowsheet=flowsheet, materials=materials))
    (latent,) = [f for f in found if "heat_of_vaporization" in f.message]
    assert latent.level == "error"
    assert latent.message.endswith("no heat_of_vaporization of B: the boil-up in kW/K is not known")


def test_one_jacket_on_every_cut_times_the_heat_up_as_on_the_still():
    """Review of #323: where every cut has its own boil-up (ADR 0068: the mean over the
    boil-up), one jacket on each heats the charge as it would on the still: the jacket's own
    C / UA ln((T_m - T_in) / (T_m - T_0)). Different jackets keep ADR 0068's mean."""
    from types import SimpleNamespace

    comps = dict(COMPONENTS)
    comps["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17, "liquid_heat_capacity": 200}
    )
    plain = {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"}

    def timed(cuts):
        spec = _raoult(
            boilup=plain,
            end=None,
            cuts=cuts,
            outlets={"residue": "bottom"},
            heat_up=True,
            heat_up_time=True,
        )
        result = solve_still(spec, {"A": 8.0, "P": 2.0}, None, comps, P_ATM, hours=4.0)
        result.charge_temperature = 300.0
        _heat_up(result, comps)
        _heat_up_time(None, SimpleNamespace(id="S", still=spec), result, "design")
        return result

    one = timed([{"outlet": "c1", "end": {"distilled": 0.5}, "boilup": JACKET}])
    bubble = _boiling(BENZENE, P_ATM / 0.8)
    capacity = (8.0 * 136 + 2.0 * 200) * 4.0  # kJ/K per batch
    exact = capacity / 2.0 * math.log((450.0 - 300.0) / (450.0 - bubble))
    assert one.heat_up_time == pytest.approx(exact, rel=1e-9)
    two = timed(
        [
            {"outlet": "c1", "end": {"distilled": 0.25}, "boilup": JACKET},
            {"outlet": "c2", "end": {"distilled": 0.5}, "boilup": JACKET | {"value": 3.0}},
        ]
    )
    assert two.heat_up_time == pytest.approx(capacity * (bubble - 300.0) / two.duty, rel=1e-9)


# -- one liquid ---------------------------------------------------------------------------------

# water as acetyl-chloride-1 (process-library) gives it: NIST WebBook (C7732185), fitted by NIST
# to Stull (1947); log10(P/bar) = a - b / (T/K + c)
WATER = {"a": 4.6543, "b": 1435.264, "c": -64.848, "temperature_range": [255.9, 373.0]}


def test_a_liquid_that_splits_into_two_is_refused():
    """Review of #323: water 0.1 in toluene at 1 atm. UNIFAC puts water's activity far above
    1, so a homogeneous liquid would boil some 30 K below the heteroazeotrope, where P_water +
    P_toluene = P and below which no liquid of the two boils. The still refuses it."""
    comps = {
        "W": Component.model_validate(
            {
                "id": "W",
                "name": "water",
                "cas": "7732-18-5",
                "molar_mass": 18.015,
                "vapour_pressure": WATER | {"provenance": "given"},
            }
        ),
        "T": PAIR["T"],
    }
    lo, hi = 300.0, 400.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if _antoine(WATER, mid) + _antoine(TOL, mid) > P_ATM else (mid, hi)
    assert 357.0 < lo < 358.0  # the heteroazeotrope at 1 atm on these constants
    for charge in ({"W": 10.0, "T": 90.0}, {"W": 50.0, "T": 50.0}):
        with pytest.raises(StillError, match=r"splits into two liquids at .* is above 1"):
            solve_still(_pair_still("unifac", {"distilled": 0.3}), charge, None, comps, P_ATM)
    # a trace of water dissolves: one liquid
    trace = solve_still(
        _pair_still("unifac", {"distilled": 0.3}), {"W": 1e-4, "T": 100.0}, None, comps, P_ATM
    )
    assert trace.temperatures[0] > lo


def test_the_tangent_plane_finds_a_split_below_unit_activities():
    """1-butanol 0.1 in water at 360 K: on UNIFAC both activities stay below 1, but a liquid
    rich in butanol lies below the tangent plane; the liquid at 0.01 or 0.6 butanol is one."""
    from chemeascode.domains.process.batch_still import _Phase
    from chemeascode.integrations.thermo import unifac_gammas

    gammas = unifac_gammas(["71-36-3", "7732-18-5"])
    phase = _Phase(
        ["BUOH", "W"],
        [True, True],
        "raoult",
        None,
        [None, None],
        P_ATM,
        [None, None],
        activity=gammas,
    )
    x = [0.1, 0.9]
    assert all(g * xi < 1.0 for g, xi in zip(gammas(360.0, x), x, strict=True))
    with pytest.raises(StillError, match="BUOH .* lies below the tangent plane"):
        phase.one_liquid(x, 360.0)
    phase.one_liquid([0.01, 0.99], 360.0)
    phase.one_liquid([0.6, 0.4], 360.0)


def test_a_pair_of_groups_without_unifac_parameters_is_refused():
    """Review of #323: UNIFAC's table has no water-iodide (main groups 7 and 32) parameters;
    thermo would take them as 0, part of an ideal liquid. Refused, naming the pair."""
    from chemeascode.integrations.thermo import unifac_gammas

    with pytest.raises(
        ValueError, match=r"between main groups 7 \(H2O.* and 32 \(I, of CAS 74-88-4"
    ):
        unifac_gammas(["67-56-1", "74-88-4", "7732-18-5"])
    unifac_gammas(["67-56-1", "108-88-3"])  # a pair it has


# -- the stall ----------------------------------------------------------------------------------


def test_a_jacket_still_that_crawls_on_a_trace_stalls_on_its_pace(tmp_path, monkeypatch):
    """Review of #323: the batch-rectification example's crawl near empty (the column on its
    ACCL trace) with a jacket far above the still (medium 600 K, the still near 414 K) stalls
    with the pace's reason, not the medium's."""
    from chemeascode.domains.process import batch_still
    from chemeascode.domains.process.batch_still import inlets_of, solve_node
    from tests.test_batch_rectification import PRODUCT, _copy

    boil = (
        "{value: 150, unit: kW, provenance: assumed, "
        'source: "the reboiler\'s heat input: illustrative"}'
    )

    def edit(text):
        assert PRODUCT in text and boil in text
        text = text.replace(PRODUCT, "{outlet: product, end: {distilled: 0.9982}}")
        return text.replace(
            boil, "{value: 1, unit: kW/K, medium_temperature: 600, provenance: assumed}"
        )

    monkeypatch.setattr(batch_still, "MAX_STEPS", 20000)
    process, _ = load(_copy(tmp_path, edit).root)
    node = process.nodes["ST1"]
    with pytest.raises(StillError) as failure:
        solve_node(process, node, inlets_of(process, node), "design")
    assert "crawls near empty" in str(failure.value)
    assert "jacket's medium" not in str(failure.value)


# -- with the charge's flash (ADR 0077) --------------------------------------------------------


def test_a_jacket_boils_up_from_where_the_charge_flashed():
    """A charge of benzene over P entering at 380 K, above its bubble point at 1 atm, flashes
    first (ADR 0077); the jacket then boils up from the flashed liquid's bubble point. The end at
    half the charge distilled counts the flash's vapour, so the jacket's time is the quadrature
    of lambda / (UA (T_m - T)) from what the flash took to 50 kmol."""
    hours = 2.0
    comps = dict(COMPONENTS)
    comps["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17, "liquid_heat_capacity": 200}
    )
    spec = _raoult(boilup=JACKET, end={"distilled": 0.5}, flash=True)
    charge = {"A": 60.0, "P": 40.0}
    result = solve_still(spec, charge, None, comps, P_ATM, hours, charge_temperature=380.0)
    flashed = result.flash.moles["A"]
    assert 0.0 < flashed < 50.0 and set(result.flash.moles) == {"A"}
    latent = 30720.0
    ua, medium = JACKET["value"], JACKET["medium_temperature"]

    def temperature(s):
        x = (60.0 - s) / (100.0 - s)
        return _boiling(BENZENE, P_ATM / x)

    assert result.flash.temperature == pytest.approx(temperature(flashed), abs=1e-6)
    assert result.temperatures[0] == pytest.approx(result.flash.temperature, abs=1e-6)
    n = 2000
    width = (50.0 - flashed) / n
    total = 0.0
    for i in range(n + 1):
        weight = 1 if i in (0, n) else 4 if i % 2 else 2
        total += weight * latent / (ua * (medium - temperature(flashed + i * width)))
    assert result.time == pytest.approx(hours * total * width / 3, rel=1e-6)
    assert result.cuts[0].moles["A"] == pytest.approx(50.0, rel=1e-9)


def test_a_non_ideal_charge_flashes_on_its_activity_coefficients():
    """Methanol 0.3 in toluene at 1 atm entering 5 K above its UNIFAC bubble point (well below
    the ideal liquid's): with activity unifac it flashes, to the UNIFAC bubble point of the
    liquid it leaves; as an ideal liquid it is below its bubble point and does not flash."""
    comps = {
        n: c.model_copy(update={"liquid_heat_capacity": cp})
        for (n, c), cp in zip(PAIR.items(), (81.1, 157.0), strict=True)
    }
    t_in = _unifac_bubble(0.3)[0] + 5.0
    charge = {"M": 30.0, "T": 70.0}
    end = {"distilled": 0.3}
    spec = _pair_still("unifac", end).model_copy(update={"flash": True})
    result = solve_still(spec, charge, None, comps, P_ATM, charge_temperature=t_in)
    flash = result.flash
    assert flash.moles["M"] > 0.0 and flash.temperature < t_in
    left = {n: charge[n] - flash.moles.get(n, 0.0) for n in charge}
    x_left = left["M"] / sum(left.values())
    assert flash.temperature == pytest.approx(_unifac_bubble(x_left)[0], abs=1e-6)
    for n, v in charge.items():
        assert sum(c.moles[n] for c in result.cuts) + result.residue[n] == pytest.approx(
            v, rel=1e-12
        )
    ideal = _pair_still(None, end).model_copy(update={"flash": True})
    plain = solve_still(ideal, charge, None, comps, P_ATM, charge_temperature=t_in)
    assert plain.flash.moles == {}
