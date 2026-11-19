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
