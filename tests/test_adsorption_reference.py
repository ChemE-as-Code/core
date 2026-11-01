"""The bounded reference case of the equilibrium TSA calculation: CO2
removal from dry compressed air on zeolite 13X, the CO2 layer of an air separation unit's front-end
purification, from published measurements.

Sources (public):

- isotherm: Cmarik, Son, Knox, "Standard Isotherm Fit Information for Dry CO2 on Sorbents for
  4-Bed Molecular Sieve", NASA/TM-2017-219847 (NTRS 20180002395), Grade 544 13X (Grace
  SYLOBEAD MS S 544): the 3-site Langmuir fit of Table 2 and the measured points of Table 1
  (0-200 °C, 0.001-108 kPa); the isosteric heat of Table 4: 43.3 kJ/mol (at 1.15 mol/kg), inside
  the 45.4-42.6 kJ/mol Table 4 gives over the 0.05-1.29 mol/kg the bed cycles through (1.29 mol/kg
  is the loading at the feed state); the heat of desorption is about 8 % of the bed heat;
- mass transfer zone: US 6,506,236 B2 (Air Products), Example 1: 198 mm (7.8 in) for CO2 in 13X
  with 18 wt % binder, 1.7 mm beads, air with 400 ppm CO2 at 25 °C, 100 psig, 146 kmol/(m2 h),
  regenerated in N2 at 200 °C;
- bed properties of 13X (bulk density 708 kg/m3 from a solid density of 2360 kg/m3, bed voidage
  0.4 and particle voidage 0.5; heat capacity 0.92 kJ/(kg K)): IDAES-PSE,
  models_extra/temperature_swing_adsorption/fixed_bed_tsa0d.py, zeolite 13X parameters, citing
  Hefti et al., Microporous Mesoporous Mater. 215 (2015) 215-228;
- purge heat capacity: nitrogen, CoolProp 8.0.0 (reference equation of state), the mean over
  298.15-473.15 K at 110 kPa, 29.28 kJ/(kmol K).

The bed diameter (3 m: the superficial flux of the MTZ measurement at about 1030 kmol/h), the
layer length and the cycle times are design choices of the case. What is qualified: the
isotherm against the measured points over the states the cycle evaluates (tolerances from the
fit's own residuals, below), the cycle relations against the hand calculation of
tests/test_adsorption.py, and the refusal outside the measured range. Not qualified: the
calculated cycle performance against a measured TSA cycle (no open dataset was found), N2/O2
co-adsorption and competition (no N2 isotherm for Grade 544 in the source: CO2 capacity is an
upper bound), water (removed upstream by the alumina layer, a sourced split).
"""

from __future__ import annotations

import json
import math

import pytest
import yaml

from chemeascode.domains.process.separations.adsorption import adsorption_report, single_loading
from chemeascode.domains.process.separations.schema import Isotherm
from tests.test_adsorption import PLANT, _write

NASA = "Cmarik, Son, Knox, NASA/TM-2017-219847 (NTRS 20180002395), Grade 544 13X"
GRADE_544 = {
    "component": "CO2",
    "model": "multi-site-langmuir",
    "pressure_unit": "kPa",
    "parameters": {
        "b0_1": 5.057e-8,
        "E_1": 5584,
        "a0_1": 1.640,
        "c0_1": 8.350e-9,
        "b0_2": 8.201e-8,
        "E_2": 4408,
        "a0_2": 2.537,
        "c0_2": 1.417e-8,
        "b0_3": 5.032e-9,
        "E_3": 4408,
        "a0_3": 1.995,
        "c0_3": -2.668e-9,
    },
    "heat_of_adsorption": {"value": 43.3, "unit": "kJ/mol", "source": f"{NASA}, Table 4"},
    "valid": {"temperature": [273.15, 473.15], "partial_pressure": [0.001, 104]},
    "source": f"{NASA}, Table 2 (fit), Table 1 (measured, 0-200 °C, 0.001-108 kPa)",
}

#: Measured points of NASA/TM-2017-219847 Table 1: (°C, kPa, mol/kg).
ADSORPTION_WINDOW = [  # the feed states: 0-25 °C, CO2 at 0.08-1 kPa
    (0, 0.087579, 1.451034),
    (10, 0.107761, 1.234227),
    (10, 0.195871, 1.516219),
    (10, 0.291254, 1.719896),
    (10, 0.386323, 1.875618),
    (25, 0.102845, 0.761839),
    (25, 0.193889, 1.048121),
    (25, 0.292963, 1.247616),
    (25, 0.388172, 1.391691),
    (25, 0.489418, 1.511427),
    (25, 0.976941, 1.897445),
]
REGENERATION_WINDOW = [  # where the desorption bound is evaluated: 150-200 °C, 8-108 kPa
    (150, 8.005888, 0.364556),
    (150, 50.6233, 1.307692),
    (150, 103.9757, 1.876349),
    (175, 8.008995, 0.206839),
    (175, 50.75289, 0.889649),
    (175, 104.0956, 1.383091),
    (200, 48.20017, 0.461258),
    (200, 98.70695, 0.794646),
    (200, 108.1094, 0.850145),
]


def _given(value, unit, source):
    return {"value": value, "unit": unit, "source": source}


DESIGN = "design choice of the reference case (tests/test_adsorption_reference.py)"
IDAES = "IDAES-PSE fixed_bed_tsa0d.py zeolite 13X parameters (Hefti et al. 2015)"
MTZ = "US 6,506,236 B2, Example 1 (13X, 18 wt% binder, 1.7 mm, 400 ppm CO2, 25 °C, 100 psig)"
FLUX = 146.0  # kmol/(m2 h), US 6,506,236 B2 Example 1
DIAMETER = 3.0
FEED = FLUX * math.pi / 4 * DIAMETER**2  # kmol/h
FEED_PRESSURE = 689.476 + 101.325  # 100 psig in kPa(a)

CASE = {
    "schema": "cheme/adsorption/v1",
    "kind": "adsorption",
    "units": [
        {
            "id": "A1",
            "technique": "tsa",
            "performance": "calculated",
            "product_outlet": "dry",
            "specification": {"CO2": _given(0.1, "ppm", DESIGN)},
            "layers": [
                {
                    "adsorbent": "zeolite 13X (Grade 544 isotherm)",
                    "length": _given(1.0, "m", DESIGN),
                    "bulk_density": _given(708, "kg/m3", IDAES),
                    "heat_capacity": _given(0.92, "kJ/(kg K)", IDAES),
                    "void_fraction": _given(0.7, "-", IDAES),
                    "removes": ["CO2"],
                    "mass_transfer_zone": _given(198, "mm", MTZ),
                    "isotherms": [GRADE_544],
                }
            ],
            "cycle": {
                "beds": 2,
                "diameter": _given(DIAMETER, "m", DESIGN),
                "adsorption_time": _given(4, "h", DESIGN),
                "heating_time": _given(1.5, "h", DESIGN),
                "cooling_time": _given(2.0, "h", DESIGN),
                "switch_time": _given(0.5, "h", DESIGN),
                "regeneration_temperature": _given(200, "°C", MTZ),
                "regeneration_pressure": _given(110, "kPa(a)", DESIGN),
                "purge": {
                    "flow": _given(0.2 * FEED, "kmol/h", DESIGN),
                    "composition": {"N2": 1.0},
                    "supply_temperature": _given(298.15, "K", DESIGN),
                    "heat_capacity": _given(
                        29.28, "kJ/(kmol K)", "CoolProp 8.0.0 N2, mean 298.15-473.15 K, 110 kPa"
                    ),
                },
            },
        }
    ],
}


def _iso() -> Isotherm:
    return Isotherm.model_validate(GRADE_544)


@pytest.mark.parametrize(("celsius", "kpa", "measured"), ADSORPTION_WINDOW)
def test_isotherm_reproduces_the_measured_capacity_at_the_feed_states(celsius, kpa, measured):
    """Within 3.5 %: the largest residual of the source's fit in this window is 3.2 %
    (25 °C, 0.10 kPa); at 0.2-1 kPa it is below 1.2 %."""
    assert single_loading(_iso(), kpa, celsius + 273.15) == pytest.approx(measured, rel=0.035)


@pytest.mark.parametrize(("celsius", "kpa", "measured"), REGENERATION_WINDOW)
def test_isotherm_at_the_regeneration_states(celsius, kpa, measured):
    """Within 12 %: the fit's residuals at 150-200 °C (it over-predicts by up to 11.6 % at
    200 °C); used only to bound the desorbed CO2's partial pressure."""
    assert single_loading(_iso(), kpa, celsius + 273.15) == pytest.approx(measured, rel=0.12)


@pytest.fixture
def asu(tmp_path):
    root = tmp_path / "asu"
    flowsheet = PLANT["process/flowsheet.yaml"]
    flowsheet = flowsheet.replace("{value: 790,", f"{{value: {FEED_PRESSURE},")
    flowsheet = flowsheet.replace("flow: {value: 100,", f"flow: {{value: {FEED},")
    files = {**PLANT, "process/flowsheet.yaml": flowsheet}
    files["process/simulation.yaml"] = PLANT["process/simulation.yaml"].replace(
        "{CO2: 1.0, N2: 0.00206, O2: 0.000407, AR: 0.000407}",
        "{CO2: 1.0, N2: 0.000314, O2: 0.000382, AR: 0.000382}",
    )
    _write(root, files, json.loads(json.dumps(CASE)))
    return root


def test_the_reference_case_qualifies(asu):
    report = adsorption_report(asu)
    assert [f.rule for f in report.findings] == []
    unit = report.units[0]
    assert unit.status == "qualified" and unit.consistent
    row = unit.cases[0]
    key = row.layers[0]["keys"]["CO2"]
    # capacity at the feed state: 400 ppm of 790.8 kPa(a) at 25 °C
    p_co2 = 0.0004 * FEED_PRESSURE
    assert key["loading_feed_mol_kg"] == pytest.approx(single_loading(_iso(), p_co2, 298.15))
    assert 1.25 < key["loading_feed_mol_kg"] < 1.40  # between the measured 0.29 and 0.39 kPa
    # breakthrough: the measured MTZ leaves 1 - 0.099 m of the 1 m layer in use
    assert key["breakthrough_time_h"] == pytest.approx(key["stoichiometric_time_h"] * 0.901)
    assert key["breakthrough_time_h"] > 4  # the CO2 front stays in the bed: spec met
    assert row.specification["CO2"]["met"]
    # the desorbing CO2 is above the measured pressures at 200 °C: bounded at 104 kPa
    assert key["desorption_partial_pressure_kPa"] is None and "104" in key["desorption_bound"]
    # carriers lose the void gas once per cycle (no isotherm: not co-adsorbed)
    void_loss = 0.7 * math.pi / 4 * DIAMETER**2 * 1.0 / (8.314462618 * 298.15)
    loss_o2 = void_loss * 0.2095 * FEED_PRESSURE / (FEED * 0.2095 * 4)
    assert row.recoveries["O2"] == pytest.approx(1 - loss_o2, rel=1e-9)
    assert row.closure["relative_residual"] < 1e-12  # bookkeeping: holds by construction
    # regeneration: the bed needs about 0.9 GJ per cycle; the 0.2 purge/feed ratio carries it
    reg = row.regeneration
    assert 0.85e6 < reg["bed_heat_kJ"] < 0.92e6
    assert reg["hot_purge_kmol"] > reg["min_purge_thermal_kmol"] > reg["min_purge_desorption_kmol"]
    assert reg["heater_duty_kW"] == pytest.approx(0.2 * FEED / 3600 * 29.28 * 175, rel=1e-9)
    assert any("no isotherm for AR, N2, O2" in x for x in unit.limitations)


@pytest.mark.parametrize(
    ("temperature", "message"),
    [(263.15, "T = 263.1 K outside 273.15-473.15 K"), (298.15, None)],
)
def test_the_case_refuses_outside_the_measured_range(asu, temperature, message):
    path = asu / "process/flowsheet.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("value: 298.15,", f"value: {temperature},"), encoding="utf-8")
    report = adsorption_report(asu)
    if message is None:
        assert report.units[0].status == "qualified"
        return
    assert report.units[0].status == "refused"
    assert message in report.findings[0].message


def test_regeneration_above_the_measured_temperatures_is_refused(asu):
    path = asu / "process/adsorption.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["units"][0]["cycle"]["regeneration_temperature"]["value"] = 250
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    finding = adsorption_report(asu).findings[0]
    assert finding.rule == "cheme.adsorption-isotherm-range"
    assert "at the regeneration temperature" in finding.message


def test_the_purge_heat_capacity_matches_coolprop():
    coolprop = pytest.importorskip("CoolProp.CoolProp")
    h = [coolprop.PropsSI("Hmolar", "T", t, "P", 110e3, "Nitrogen") for t in (298.15, 473.15)]
    assert (h[1] - h[0]) / 175 == pytest.approx(29.28, abs=0.01)
