"""Dynamic electrolysis duties (domains/process/electrolysis_duty.py, ``process/duties.yaml``):
the constant-efficiency limit, convergence in the tolerance, the measured range, dosing, bleed
and inventory, the comparison at equal product, the operating map and the plots, the
agreement with the process-library#329 reproduction and its validation case, and the command.

Fixture: tests/data/electrochemical/co2-duty, the synthetic measured cell BPM-1 of co2-bpm
(50-200 mA/cm2 on 5 cm2) and a specified cell BPM-S (constants, 500-4000 A/m2).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process import electrolysis_duty as ed
from chemeascode.domains.process.electrolysis_duty import (
    FARADAY,
    MODEL,
    Duty,
    DutyCell,
    SpecifiedPerformance,
    compare,
    compare_duties,
    duty_findings,
    duty_report,
    operating_map,
    simulate_duty,
)
from chemeascode.domains.process.electrolysis_plots import duty_plots, map_plot
from chemeascode.interfaces.cli import app

DATA = Path(__file__).resolve().parent / "data" / "electrochemical"
runner = CliRunner()


def _plant(tmp_path: Path) -> Path:
    root = tmp_path / "co2-duty"
    shutil.copytree(DATA / "co2-duty", root)
    return root


def _duties(root: Path, edit) -> None:
    path = root / "process" / "duties.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data["duties"])
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _by_id(report, did):
    return next(d for d in report.duties if d.id == did)


def _rules(findings, did=None):
    return {f.rule for f in findings if did is None or did in f.ids}


# -- the constant-efficiency limit --------------------------------------------------------------


def test_equal_charge_gives_equal_hydroxide_deficit(tmp_path):
    """Specified constants: a constant 1 A and an on/off 2 A at half duty pass the same charge
    over 100 h; the cumulative hydroxide deficit of both is (1 - WDE) Q / F (WDE 0.95), and so
    are the reservoir states, to the integration tolerance."""
    report = duty_report(_plant(tmp_path), ["SPEC-CONST", "SPEC-ONOFF"])
    const, onoff = _by_id(report, "SPEC-CONST"), _by_id(report, "SPEC-ONOFF")
    for d in (const, onoff):
        assert d.ended == "horizon" and d.feasible
        q = d.totals["charge_c"]
        assert q == pytest.approx(100 * 3600, rel=1e-9)
        assert d.totals["hydroxide_deficit_mol"] == pytest.approx(0.05 * q / FARADAY, rel=1e-9)
    assert onoff.operating_time_h == pytest.approx(50.0)
    for key in ("final_cation_mol", "final_carbon_mol", "product_mol", "energy_kwh"):
        assert onoff.totals[key] == pytest.approx(const.totals[key], rel=1e-9)
    assert onoff.totals["final_ph"] == pytest.approx(const.totals["final_ph"], abs=1e-9)
    # the on/off current is on and off in the series, the constant one is not
    assert set(onoff.series["current_a"]) == {0.0, 2.0}
    assert set(const.series["current_a"]) == {1.0}


# -- convergence in the tolerance ---------------------------------------------------------------

#: The threshold time changes by less than this (relative) when the tolerance is halved.
CONVERGED = 1e-6


def test_threshold_time_converges_with_the_tolerance(tmp_path):
    """A nonlinear case: a current ramp across the measured knots of BPM-1 (the WDE and C_x
    change with j), 0.1 L, and CO2 degassing to air above saturation (a kink in the rates),
    to pH 8.5. Halving the relative tolerance from 1e-6 to 5e-7 changes the threshold time by
    less than 1e-6 of it (found: about 3e-7), and both agree with a run at 1e-10 to better
    than 1e-5 (found: about 2e-6; the saturation kink limits the order)."""
    root = _plant(tmp_path)

    def ramp(duties):
        d = duties[0]
        d["schedule"] = {
            "kind": "piecewise",
            "points": [[0, 0.3], [200, 1.0]],
            "time_unit": "h",
            "unit": "A",
            "interpolation": "linear",
        }
        d["reservoir"]["degassing"] = {
            "kla": {"value": 2, "unit": "1/h", "source": "test"},
            "co2_partial_pressure": {"value": 0.0004, "unit": "atm", "source": "test: air"},
        }
        d["reservoir"]["volume"]["value"] = 0.1
        d["threshold"]["ph"] = 8.5  # below about pH 10 the dissolved CO2 degasses

    _duties(root, ramp)
    times = {}
    for rtol in (1e-6, 5e-7, 1e-10):
        _duties(root, lambda duties, r=rtol: duties[0].__setitem__("tolerance", r))
        d = _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")
        assert d.ended == "threshold" and d.totals["co2_degassed_mol"] > 1e-3
        times[rtol] = d.time_to_threshold_h
    assert abs(times[1e-6] - times[5e-7]) <= CONVERGED * times[5e-7]
    assert abs(times[5e-7] - times[1e-10]) <= 1e-5 * times[1e-10]


# -- the measured range -------------------------------------------------------------------------


def test_power_beyond_the_measured_range_is_flagged_and_not_extrapolated(tmp_path):
    report = duty_report(_plant(tmp_path), ["MEAS-POWER"])
    d = _by_id(report, "MEAS-POWER")
    assert d.ended == "measured-range-exit" and not d.feasible
    assert d.first_exit_h == pytest.approx(10.0)
    assert d.simulated_h == pytest.approx(10.0)
    assert d.time_outside_measured_range_h == pytest.approx(40.0)
    assert d.operating_time_h == pytest.approx(50.0)
    finding = next(f for f in report.findings if f.rule == "cheme.duty-out-of-range")
    assert finding.level == "warning" and "10 h" in finding.message and finding.line
    # inside the range the power is met: N U(j) I = P
    p = [u * i for u, i in zip(d.series["voltage_v"], d.series["current_a"], strict=True) if u]
    assert p and all(v == pytest.approx(2.0, rel=1e-9) for v in p)
    exit_event = next(e for e in d.events if e["kind"] == "measured-range-exit")
    assert "4.5 W" in exit_event["detail"]


def test_a_current_outside_then_inside_is_summed(tmp_path):
    """0.75 A for 5 h, 1.5 A (300 mA/cm2, beyond 200) for 5 h, 0.75 A again: the transient
    stops at 5 h; 5 h of the 20 h of operation are outside."""
    root = _plant(tmp_path)

    def steps(duties):
        duties[0]["schedule"] = {
            "kind": "piecewise",
            "points": [[0, 0.75], [5, 1.5], [10, 0.75]],
            "time_unit": "h",
        }
        duties[0]["horizon"] = {"value": 20, "unit": "h"}

    _duties(root, steps)
    d = _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")
    assert d.ended == "measured-range-exit" and d.first_exit_h == pytest.approx(5.0)
    assert d.time_outside_measured_range_h == pytest.approx(5.0)
    assert d.operating_time_h == pytest.approx(20.0)
    assert all(d.series["in_measured_range"])  # the transient is the part inside
    detail = next(e["detail"] for e in d.events if e["kind"] == "measured-range-exit")
    assert "3000 A/m2" in detail


def test_a_linear_ramp_leaves_the_range_where_it_crosses_the_bound(tmp_path):
    """0.5 A to 1.5 A over 10 h: j = 2000 A/m2 (1 A) at 5 h."""
    root = _plant(tmp_path)

    def ramp(duties):
        duties[0]["schedule"] = {
            "kind": "piecewise",
            "points": [[0, 0.5], [10, 1.5]],
            "interpolation": "linear",
        }
        duties[0]["horizon"] = {"value": 10, "unit": "h"}

    _duties(root, ramp)
    d = _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")
    assert d.first_exit_h == pytest.approx(5.0, rel=1e-9)
    assert d.time_outside_measured_range_h == pytest.approx(5.0, rel=1e-9)


def test_a_temperature_outside_the_measurement_stops_at_once(tmp_path):
    root = _plant(tmp_path)
    _duties(
        root,
        lambda duties: duties[0]["reservoir"].__setitem__(
            "temperature", {"value": 60, "unit": "°C"}
        ),
    )
    report = duty_report(root, ["MEAS-150"])
    d = _by_id(report, "MEAS-150")
    assert d.ended == "measured-range-exit" and d.simulated_h == 0
    assert d.time_outside_measured_range_h == pytest.approx(2000.0)
    assert "temperature" in d.events[0]["detail"]
    assert "cheme.duty-out-of-range" in _rules(report.findings)


def test_the_measured_cell_follows_its_series(tmp_path):
    """At 150 mA/cm2 (between P100 and P200) the duty's voltage, FE and WDE are those of
    MeasuredPerformance.at."""
    from chemeascode.domains.experiments.electrochemistry import (
        MeasuredPerformance,
        measurement_report,
    )

    root = _plant(tmp_path)
    d = _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")
    point = MeasuredPerformance(
        measurement_report(root, "experiments/electrochemistry/synthetic-bpm.yaml")
    ).at(1500.0)
    assert d.series["voltage_v"][1] == pytest.approx(point.voltage_v)
    assert d.series["current_density_a_m2"][1] == pytest.approx(1500.0)
    rate = d.series["product_rate_mol_s"][1]
    assert rate == pytest.approx(point.faradaic_efficiency["CO"] * 0.75 / (2 * FARADAY))
    wde = point.water_dissociation_efficiency
    assert d.totals["hydroxide_deficit_mol"] == pytest.approx(
        (1 - wde) * d.totals["charge_c"] / FARADAY, rel=1e-9
    )
    assert d.time_to_threshold_h is not None and d.performance == "measured"


# -- process-library#329: reproduction and validation, kept apart ------------------------------


def _bench(wde: float, cx: float, area_cm2: float = 5.0) -> DutyCell:
    performance = SpecifiedPerformance(3.9, 0.8, wde, {"K+": 1 - cx, "HCO3-": cx})
    return DutyCell("bench", performance, 2.0, "CO", 1.0, 0.0280101, area_cm2 * 1e-4)


def _duty(j_ma_cm2: float, volume_l: float, koh: float, horizon_h: float = 20000) -> Duty:
    return Duty.model_validate(
        {
            "id": "rbpm",
            "cell": "bench",
            "schedule": {
                "kind": "constant_current",
                "current_density": {"value": j_ma_cm2, "unit": "mA/cm2"},
            },
            "reservoir": {
                "volume": {"value": volume_l, "unit": "L"},
                # the script's initial values (process-library#329 source.yaml): CO3--, HCO3-
                # and CO2 1e-7 M, H+ from Kw
                "composition": {
                    "hydroxide": {"value": koh, "unit": "mol/L"},
                    "carbonate": {"value": 1e-7, "unit": "mol/L"},
                    "bicarbonate": {"value": 1e-7, "unit": "mol/L"},
                    "co2": {"value": 1e-7, "unit": "mol/L"},
                },
                "model": "well-mixed-carbonate",
            },
            "threshold": {"ph": 12, "source": "the paper's criterion: anolyte pH below 12"},
            "horizon": {"value": horizon_h, "unit": "h"},
        }
    )


#: Agreement with the authors' finite-rate model on a concentration basis. Start from 0.5 %:
#: the two models share the balance (fluxes, initial state, constants) and differ only in the
#: speciation, finite-rate CO2 hydration and carbonate kinetics in the authors' model against
#: instantaneous equilibrium here. At pH >= 12 nearly all carbon is CO3-2 in both (CO3-2 /
#: HCO3- = 10^(pH - pK2) ~ 48 at pH 12) and the authors' rate constants are fast against the
#: fluxes, so the speciation lag is small; our run agrees to about 1e-5 (322.303 h against
#: 322.30 h), well inside 0.5 %, which also covers the 4-figure rounding of the reference.
REPRODUCTION_TOLERANCE = 0.005


def test_reproduction_of_329_d1_on_a_concentration_basis():
    """process-library#329 D1 (our run of the authors' model, values only): 200 mA/cm2, 5 cm2,
    one cell, 1 M KOH, C_x 0.66, WDE 0.95, no degassing: time to pH 12 on a concentration basis
    322.30 h at 1 L and 3223.0 h at 10 L."""
    cell = _bench(0.95, 0.66)
    one = simulate_duty(_duty(200, 1.0, 1.0), cell)
    ten = simulate_duty(_duty(200, 10.0, 1.0), cell)
    assert one.time_to_threshold_h == pytest.approx(322.30, rel=REPRODUCTION_TOLERANCE)
    assert ten.time_to_threshold_h == pytest.approx(3223.0, rel=REPRODUCTION_TOLERANCE)
    # a concentration basis scales exactly with the volume (the authors' pH stop on the H+
    # amount stops at pH 13 at 10 L instead: #329 D1)
    assert ten.time_to_threshold_h / one.time_to_threshold_h == pytest.approx(10.0, rel=1e-9)
    assert one.totals["final_ph"] == pytest.approx(12.0, abs=1e-6)


def test_validation_against_329_v1_is_within_the_envelope():
    """process-library#329 V1, a validation and not a reproduction: 20 mL, 0.1 M KOH,
    100 mA/cm2, WDE 0.96456, C_x 0.77945 (Fig. 4a/4c at 0.1 M). The authors' model gives
    1.544 h to pH 12, the measurement 1.472 h; the #329 envelope over the inputs +- 2 sd is
    1.305-1.868 h. Ours must lie in it."""
    d = simulate_duty(_duty(100, 0.020, 0.1, horizon_h=10), _bench(0.96456, 0.77945))
    assert d.ended == "threshold"
    assert 1.305 <= d.time_to_threshold_h <= 1.868
    assert d.time_to_threshold_h == pytest.approx(1.544, rel=0.01)  # beside the envelope


# -- dosing, bleed and inventory ----------------------------------------------------------------


def test_dosing_on_a_ph_trigger_keeps_the_anolyte_above_the_threshold(tmp_path):
    report = duty_report(_plant(tmp_path), ["SPEC-DOSED"])
    d = _by_id(report, "SPEC-DOSED")
    assert d.ended == "horizon" and d.time_to_threshold_h is None
    kinds = [e["kind"] for e in d.events]
    assert kinds[0] == "dosing-on" and kinds[1] == "dosing-off"
    assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False))  # alternating
    for e in d.events:
        assert e["ph"] == pytest.approx(13.0 if e["kind"] == "dosing-on" else 13.3, abs=1e-6)
    t = d.totals
    assert t["dosing_mol"] == pytest.approx(5.0 * t["dosing_solution_l"], rel=1e-9)
    assert t["dosing_solution_kg"] == pytest.approx(1.22 * t["dosing_solution_l"], rel=1e-9)
    assert t["dosing_hydroxide_kg"] == pytest.approx(t["dosing_mol"] * 0.0561049, rel=1e-4)
    assert t["bleed_l"] == pytest.approx(0.6) and t["makeup_water_l"] == pytest.approx(0.6)
    volume = 0.2 + t["dosing_solution_l"]
    assert t["final_volume_l"] == pytest.approx(volume, rel=1e-9)
    assert t["minimum_ph"] >= 13.0 - 1e-6
    assert any(d.series["dosing_on"]) and not all(d.series["dosing_on"])


def test_a_bleed_without_make_up_reaches_the_minimum_inventory(tmp_path):
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[4].pop("makeup_water"))
    report = duty_report(root, ["SPEC-DOSED"])
    d = _by_id(report, "SPEC-DOSED")
    assert d.ended == "minimum-inventory" and not d.feasible
    assert d.totals["final_volume_l"] == pytest.approx(0.05, rel=1e-6)
    assert "cheme.duty-inventory-low" in _rules(report.findings)


def test_weak_dosing_is_saturated(tmp_path):
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[4]["dosing"]["rate"].__setitem__("value", 0.1))
    report = duty_report(root, ["SPEC-DOSED"])
    d = _by_id(report, "SPEC-DOSED")
    assert d.ended == "threshold"
    saturated = [f for f in report.findings if f.rule == "cheme.duty-dosing-saturated"]
    assert saturated and "while dosing" in saturated[0].message


def test_continuous_dosing_and_its_balance(tmp_path):
    root = _plant(tmp_path)

    def dose(duties):
        duties[2]["dosing"] = {
            "kind": "continuous",
            "concentration": {"value": 1, "unit": "mol/L"},
            "rate": {"value": 1, "unit": "mL/h"},
        }

    _duties(root, dose)
    d = _by_id(duty_report(root, ["SPEC-CONST"]), "SPEC-CONST")
    assert d.totals["dosing_mol"] == pytest.approx(0.1, rel=1e-9)  # 1 M x 1 mL/h x 100 h
    assert d.totals["dosing_solution_kg"] is None  # no density stated
    assert any("density" in text for text in d.limitations)
    # the cation balance: initial + dosed - (1 - C_x) (1 - WDE) Q / F
    lost = 0.34 * d.totals["hydroxide_deficit_mol"]
    assert d.totals["final_cation_mol"] == pytest.approx(1.0 + 0.1 - lost, rel=1e-9)


# -- findings -----------------------------------------------------------------------------------


def test_threshold_and_horizon_findings_name_the_criterion(tmp_path):
    report = duty_report(_plant(tmp_path), ["MEAS-150", "SPEC-CONST"])
    reached = next(f for f in report.findings if f.rule == "cheme.duty-threshold-reached")
    assert reached.level == "info" and "time to the specified pH threshold 12" in reached.message
    assert "corrosion" not in reached.message
    horizon = next(f for f in report.findings if f.rule == "cheme.duty-horizon-reached")
    assert "SPEC-CONST" in horizon.ids
    assert "cheme.duty-degassing" in _rules(report.findings)


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda d: d.__setitem__("cell", "NOPE"), "cheme.duty-cell-missing"),
        (lambda d: d["reservoir"].__setitem__("model", "finite-rate"), "cheme.duty-model-unknown"),
        (lambda d: d["reservoir"]["volume"].__setitem__("unit", "gal"), "cheme.duty-schema"),
        (lambda d: d["reservoir"].__setitem__("cation", "Na+"), "cheme.duty-model-species"),
        (lambda d: d.__setitem__("schedule", {"kind": "ramp"}), "cheme.duty-schema"),
        (lambda d: d["reservoir"]["volume"].__setitem__("value", 0), "cheme.duty-schema"),
    ],
)
def test_refusals(tmp_path, edit, rule):
    root = _plant(tmp_path)
    _duties(root, lambda duties: edit(duties[2]))
    report = duty_report(root)
    found = [f for f in report.findings if f.rule == rule]
    assert found and found[0].level == "error" and found[0].line, report.findings
    if rule != "cheme.duty-schema" or "kind" not in str(found[0].message):
        assert any(d.refused for d in report.duties) or not report.duties


def test_a_specified_cell_without_wde_or_product_is_refused(tmp_path):
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[2].pop("product"))
    report = duty_report(root, ["SPEC-CONST"])
    assert _by_id(report, "SPEC-CONST").refused
    assert "no product" in next(f.message for f in report.findings if "SPEC-CONST" in f.ids)
    cells = root / "process" / "cells.yaml"
    data = yaml.safe_load(cells.read_text(encoding="utf-8"))
    data["cells"][1]["membrane"].pop("water_dissociation_efficiency")
    cells.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = duty_report(root, ["SPEC-ONOFF"])
    message = next(f.message for f in report.findings if f.rule == "cheme.duty-cell-missing")
    assert "water_dissociation_efficiency" in message


def test_a_dosing_trigger_below_the_threshold_is_an_error(tmp_path):
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[4]["dosing"].__setitem__("trigger_ph", 11.5))
    report = duty_report(root, ["SPEC-DOSED"])
    assert any(f.rule == "cheme.duty-schema" and "trigger" in f.message for f in report.findings)


def test_a_failed_integration_is_not_converged(tmp_path, monkeypatch):
    from chemeascode.foundation import ode

    real = ode.solve

    def failing(*args, **kwargs):
        solution = real(*args, **{**kwargs, "max_steps": 1})
        return solution

    monkeypatch.setattr(ed, "solve", failing)
    _duties(root := _plant(tmp_path), lambda duties: duties[0].__setitem__("tolerance", 1e-10))
    report = duty_report(root, ["MEAS-150"])
    d = _by_id(report, "MEAS-150")
    assert d.ended == "not-converged" and not d.feasible
    assert "cheme.duty-not-converged" in _rules(report.findings)


# -- comparison at equal delivered product ------------------------------------------------------


def test_compare_at_equal_delivered_product(tmp_path):
    root = _plant(tmp_path)
    c = compare_duties(root, ["SPEC-CONST", "SPEC-ONOFF", "MEAS-150"], 0.02)
    assert c.product == "CO" and c.tolerance == ed.DEFAULT_PRODUCT_TOLERANCE
    rows = {r.id: r for r in c.rows}
    for r in rows.values():
        assert r.reached and r.ended == "product-target"
        assert abs(r.delivered_kg - 0.02) <= 1e-3 * 0.02
    # specified constants: equal product, equal charge and deficit, whatever the schedule
    a, b = rows["SPEC-CONST"], rows["SPEC-ONOFF"]
    assert a.charge_c == pytest.approx(b.charge_c, rel=1e-9)
    assert a.hydroxide_deficit_mol == pytest.approx(b.hydroxide_deficit_mol, rel=1e-9)
    assert a.elapsed_h != pytest.approx(b.elapsed_h)  # the on/off runs at twice the current
    assert rows["MEAS-150"].charge_c != pytest.approx(a.charge_c)  # another FE


def test_a_duty_that_ends_first_does_not_reach_the_target(tmp_path):
    c = compare_duties(_plant(tmp_path), ["SPEC-CONST", "MEAS-POWER"], 0.2)
    rows = {r.id: r for r in c.rows}
    assert not rows["SPEC-CONST"].reached and rows["SPEC-CONST"].ended == "horizon"
    assert not rows["MEAS-POWER"].reached and rows["MEAS-POWER"].ended == "measured-range-exit"
    assert rows["MEAS-POWER"].time_outside_measured_range_h == pytest.approx(40.0)
    assert sum(f.rule == "cheme.duty-target-not-reached" for f in c.findings) == 2
    with pytest.raises(KeyError):
        compare_duties(_plant(tmp_path / "x"), ["NOPE"], 0.1)


def test_compare_refuses_different_products():
    cell = _bench(0.95, 0.66)
    other = DutyCell(**{**cell.__dict__, "product": "H2", "product_molar_mass_kg_mol": 0.002})
    c = compare([(_duty(200, 1.0, 1.0), cell), (_duty(200, 1.0, 1.0), other)], 0.001)
    assert c.product is None and "cheme.duty-compare" in _rules(c.findings)


# -- the operating map and the plots ------------------------------------------------------------


def test_operating_map_scales_with_wde_and_volume():
    cell = _bench(0.95, 0.66)
    duty = _duty(200, 1.0, 1.0, horizon_h=5000)
    m = operating_map(duty, cell, wde=(0.5, 0.95), volume_l=(0.1, 1.0), resolution=(4, 3))
    assert len(m.time_h) == 3 and len(m.time_h[0]) == 4
    assert m.volume_l == pytest.approx([0.1, 10**-0.5, 1.0])
    # time to the threshold ~ V / (1 - WDE): along both axes it grows
    for row in m.time_h:
        assert all(a < b for a, b in zip(row, row[1:], strict=False))
    for col in range(4):
        assert m.time_h[0][col] < m.time_h[1][col] < m.time_h[2][col]
    assert m.time_h[2][3] == pytest.approx(322.30, rel=REPRODUCTION_TOLERANCE)
    assert m.measured_wde == [] and m.duty_wde == 0.95


def test_plots_keep_measured_points_apart_from_simulated_transients(tmp_path):
    report = duty_report(_plant(tmp_path), ["MEAS-150", "MEAS-POWER"])
    figures = duty_plots(report)
    assert set(figures) == {
        "duty-MEAS-150.svg",
        "map-MEAS-150.svg",
        "duty-MEAS-POWER.svg",
        "map-MEAS-POWER.svg",
    }
    time_plot = figures["duty-MEAS-150.svg"]
    assert "stated threshold pH 12" in time_plot and "simulated" in time_plot
    assert 'class="line"' in time_plot and 'class="measured"' not in time_plot
    assert "not simulated" in figures["duty-MEAS-POWER.svg"]  # the time after the exit
    page = figures["map-MEAS-150.svg"]
    assert page.count('class="measured"') == 3 + 1  # P050, P100, P200 and the legend
    assert "measured WDE" in page and "this duty (simulated)" in page
    assert "outside the measured WDE range" in page
    for svg in figures.values():
        assert svg.startswith("<svg") and "prefers-color-scheme: dark" in svg


def test_map_without_reaching_the_threshold():
    cell = _bench(0.95, 0.66)
    m = operating_map(_duty(200, 1.0, 1.0, horizon_h=10), cell, wde=(0.9, 0.99), resolution=(2, 2))
    assert m.time_h == [[None, None], [None, None]]
    assert "not reached within the horizon" in map_plot(m)


# -- the command and the function ---------------------------------------------------------------


def test_cli_json_is_the_report(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "duty", "SPEC-CONST", "MEAS-POWER", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == json.loads(duty_report(root, ["SPEC-CONST", "MEAS-POWER"]).to_json())
    assert payload["model"] == MODEL and payload["assumptions"] and payload["limitations"]
    model = payload["duties"][0]["anolyte_model"]
    assert (model["id"], model["version"]) == ("well-mixed-carbonate", 1)
    assert model["assumptions"] and model["limitations"]
    assert set(payload["source"]["fingerprints"]) >= {
        "process/duties.yaml",
        "process/cells.yaml",
        "experiments/electrochemistry/synthetic-bpm.yaml",
    }
    monkeypatch.chdir(tmp_path)  # the function from elsewhere
    assert _by_id(duty_report(root, ["SPEC-CONST"]), "SPEC-CONST").feasible


def test_cli_text_plots_and_compare(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["process", "duty", "MEAS-150", "--plot", str(tmp_path / "p")])
    assert result.exit_code == 0, result.output
    assert "time to the specified pH threshold 12" in result.stdout
    assert sorted(p.name for p in (tmp_path / "p").iterdir()) == [
        "duty-MEAS-150.svg",
        "map-MEAS-150.svg",
    ]
    result = runner.invoke(
        app, ["process", "duty", "--compare", "SPEC-CONST,SPEC-ONOFF", "--co", "0.02", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    expected = compare_duties(root, ["SPEC-CONST", "SPEC-ONOFF"], 0.02).as_dict()
    assert payload == json.loads(json.dumps(expected))
    assert payload["basis"] == "equal delivered product"


def test_cli_exit_codes(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["process", "duty", "NOPE"]).exit_code == 2
    assert runner.invoke(app, ["process", "duty", "--compare", "SPEC-CONST"]).exit_code == 2
    _duties(root, lambda duties: duties[0].__setitem__("cell", "NOPE"))
    result = runner.invoke(app, ["process", "duty", "MEAS-150"])
    assert result.exit_code == 1 and "refused" in result.stdout
    (root / "process" / "duties.yaml").unlink()
    assert runner.invoke(app, ["process", "duty"]).exit_code == 2


def test_validate_reports_duty_findings_without_integrating(tmp_path):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[1]["reservoir"].__setitem__("model", "unknown"))
    report = validate_workspace(Workspace(root))
    assert "process/duties.yaml" in report.files
    assert "cheme.duty-model-unknown" in {f.rule for f in report.findings}
    assert {f.rule for f in duty_findings(root)} == {"cheme.duty-model-unknown"}


def test_the_schema_is_in_the_catalogue():
    from chemeascode.schemas import OTHER_SCHEMAS

    model, where = OTHER_SCHEMAS["process-duties"]
    assert model is ed.Duties and where == "process/duties.yaml"


def test_import_needs_neither_typer_nor_fastapi():
    code = (
        "import sys; import chemeascode.domains.process.electrolysis_duty; "
        "import chemeascode.domains.process.electrolysis_plots; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ})


# -- review fixes: inventories, validate, membranes, caps, the state layout, the range --------


def test_a_cation_inventory_that_runs_out_ends_the_duty():
    """20 mL of 0.01 M KOH (2e-4 mol K+) at 0.5 A, WDE 0.9, C_x 0.66: the cation leaves at
    0.34 x 0.1 x 0.5 / F mol/s and is gone after about 0.32 h. The duty ends there (more K+
    cannot leave than the reservoir held) and is not feasible, with an inventory-low warning,
    instead of integrating on with a negative inventory."""
    duty = Duty.model_validate(
        {
            "id": "drain",
            "cell": "bench",
            "schedule": {"kind": "constant_current", "current": {"value": 0.5, "unit": "A"}},
            "reservoir": {
                "volume": {"value": 20, "unit": "mL"},
                "composition": {"hydroxide": {"value": 0.01, "unit": "mol/L"}},
                "model": "well-mixed-carbonate",
            },
            "threshold": {"ph": 3},
            "horizon": {"value": 10, "unit": "h"},
        }
    )
    out = ed._Out(ed.DUTIES_FILE, None)
    d = simulate_duty(duty, _bench(0.9, 0.66), out=out)
    expected_h = 2e-4 / (0.34 * 0.1 * 0.5 / FARADAY) / 3600
    assert d.ended == "minimum-inventory" and not d.feasible
    assert d.simulated_h == pytest.approx(expected_h, rel=1e-6)
    assert d.totals["final_cation_mol"] == pytest.approx(0.0, abs=1e-12)
    assert min(d.series["cation_mol"]) >= -1e-12
    event = next(e for e in d.events if e["kind"] == "minimum-inventory")
    assert "cation inventory is exhausted" in event["detail"]
    low = next(f for f in out.findings if f.rule == "cheme.duty-inventory-low")
    assert low.level == "warning" and "exhausted" in low.message


def test_validate_reports_the_errors_the_duty_refuses_on(tmp_path):
    """``cheme validate`` (duty_findings) reports the unit, range and model-species errors
    that need no integration, the same as ``cheme process duty`` before it integrates."""
    root = _plant(tmp_path)

    def edit(duties):
        duties[0]["reservoir"]["volume"]["unit"] = "gal"
        duties[4]["dosing"]["trigger_ph"] = 11.5
        duties[2]["reservoir"]["cation"] = "Na+"

    _duties(root, edit)
    found = duty_findings(root)
    messages = {(f.rule, f.message) for f in found if f.level == "error"}
    assert any(r == "cheme.duty-schema" and "'gal'" in m for r, m in messages)
    assert any(r == "cheme.duty-schema" and "trigger pH 11.5" in m for r, m in messages)
    assert any(r == "cheme.duty-model-species" and "Na+" in m for r, m in messages)
    report = duty_report(root)
    assert messages == {(f.rule, f.message) for f in report.errors}
    assert all(f.line for f in found)


@pytest.mark.parametrize(
    ("edit", "text"),
    [
        (lambda m: m.__setitem__("co_ion_crossover", {"K+": 0.2, "HCO3-": 0.3}), "add up to 0.5"),
        (
            lambda m: m["water_dissociation_efficiency"].__setitem__("value", 1.4),
            "water dissociation efficiency 1.4",
        ),
    ],
)
def test_an_invalid_membrane_block_is_refused(tmp_path, edit, text):
    root = _plant(tmp_path)
    cells = root / "process" / "cells.yaml"
    data = yaml.safe_load(cells.read_text(encoding="utf-8"))
    edit(data["cells"][1]["membrane"])  # BPM-S
    cells.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = duty_report(root, ["SPEC-CONST"])
    assert _by_id(report, "SPEC-CONST").refused
    missing = [f for f in report.findings if f.rule == "cheme.duty-cell-missing"]
    assert missing and text in missing[0].message and missing[0].level == "error"
    assert any(f.rule == "cheme.duty-cell-missing" for f in duty_findings(root))


def test_the_fluxes_of_a_valid_membrane_are_electroneutral():
    from chemeascode.domains.chemistry.carbonate import charge_closure

    for shares in ({"K+": 0.34, "HCO3-": 0.66}, {"K+": 0.5, "CO3-2": 0.5}):
        cell = DutyCell("c", SpecifiedPerformance(3.9, 0.8, 0.9, shares), 2.0, "CO", 1.0)
        duty = _duty(200, 1.0, 1.0)
        plan = ed._plan(
            duty, DutyCell(**{**cell.__dict__, "area_m2": 5e-4}), ed._Out("x", None), []
        )
        op = ed._Op(1.0, None, cell.performance.at(None), True)
        fluxes, _ = ed._fluxes(op, plan, cell, False)
        assert charge_closure(fluxes, "K+") == pytest.approx(0.0, abs=1e-18)


def _without_titrations(node):
    if isinstance(node, dict):
        return {k: _without_titrations(v) for k, v in node.items() if k != "titration"}
    if isinstance(node, list):
        return [_without_titrations(v) for v in node]
    return node


def test_a_measured_cell_without_a_wde_is_refused(tmp_path):
    """No titration in the measurement and no WDE in the membrane block: cell-missing, not a
    duty that is "outside the measured range" from t = 0."""
    root = _plant(tmp_path)
    path = root / "experiments" / "electrochemistry" / "synthetic-bpm.yaml"
    data = _without_titrations(yaml.safe_load(path.read_text(encoding="utf-8")))
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = duty_report(root, ["MEAS-150"])
    d = _by_id(report, "MEAS-150")
    assert d.refused and "cheme.duty-out-of-range" not in _rules(report.findings)
    missing = next(f for f in report.findings if f.rule == "cheme.duty-cell-missing")
    assert "water dissociation efficiency" in missing.message
    assert "co-ion split" not in missing.message  # the membrane block gives the split
    assert "cheme.duty-cell-missing" in _rules(duty_findings(root), "MEAS-150")


def test_too_many_on_off_periods_is_a_schema_error(tmp_path):
    """A 1 s period over 300 h (1.08e6 periods) is refused, not silently truncated."""
    root = _plant(tmp_path)

    def edit(duties):
        duties[3]["schedule"]["period"] = {"value": 1, "unit": "s"}
        duties[3]["horizon"] = {"value": 300, "unit": "h"}

    _duties(root, edit)
    report = duty_report(root, ["SPEC-ONOFF"])
    assert _by_id(report, "SPEC-ONOFF").refused
    error = next(f for f in report.errors if f.rule == "cheme.duty-schema")
    assert "1.08e+06 periods" in error.message and str(ed.MAX_PERIODS) in error.message
    assert any("periods" in f.message for f in duty_findings(root))


def test_dosing_chatter_is_not_a_convergence_failure(tmp_path, monkeypatch):
    """Past MAX_DOSING_SWITCHES the transient stops with a dosing-chatter warning naming the
    band, not a not-converged error (the integration converged)."""
    monkeypatch.setattr(ed, "MAX_DOSING_SWITCHES", 6)
    report = duty_report(_plant(tmp_path), ["SPEC-DOSED"])
    d = _by_id(report, "SPEC-DOSED")
    assert d.ended == "dosing-switch-limit" and not d.feasible
    assert sum(e["kind"] in ("dosing-on", "dosing-off") for e in d.events) == 7
    rules = _rules(report.findings)
    assert "cheme.duty-not-converged" not in rules and not report.errors
    chatter = next(f for f in report.findings if f.rule == "cheme.duty-dosing-chatter")
    assert chatter.level == "warning" and "stop pH 13.3" in chatter.message
    assert "widen stop_ph - trigger_ph" in chatter.hint


class _Permuted:
    """well-mixed-carbonate with its state reordered (volume, cation, carbon) and the
    inventories renamed nowhere: the duty must find them by name."""

    id = "permuted-carbonate"
    version = 1

    def __init__(self, **parameters):
        from chemeascode.domains.chemistry.carbonate import WellMixedCarbonate

        self.inner = WellMixedCarbonate(**parameters)
        self.state = tuple(self.inner.state[i] for i in (2, 0, 1))
        for name in ("species", "composition_keys", "validity", "assumptions", "limitations"):
            setattr(self, name, getattr(self.inner, name))
        self.degassing = self.inner.degassing

    @staticmethod
    def _back(s):
        return [s[1], s[2], s[0]]

    def initial(self, composition, volume_l):
        c, t, v = self.inner.initial(composition, volume_l)
        return [v, c, t]

    def rates(self, state, fluxes, t):
        c, t_, v = self.inner.rates(self._back(state), fluxes, t)
        return [v, c, t_]

    def losses(self, state):
        return self.inner.losses(self._back(state))

    def speciate(self, state, volume_l=None):
        return self.inner.speciate(self._back(state), volume_l)

    def describe(self):
        return {**self.inner.describe(), "id": self.id}


class _NoVolume(_Permuted):
    id = "no-volume"

    def __init__(self, **parameters):
        super().__init__(**parameters)
        self.state = (("water", "L"), ("cation", "mol"), ("carbon", "mol"))


def test_the_duty_reads_the_model_state_by_name(tmp_path, monkeypatch):
    from chemeascode.domains.chemistry import anolyte

    monkeypatch.setitem(anolyte._REGISTRY, "permuted-carbonate", (__name__, "_Permuted"))
    monkeypatch.setitem(anolyte._REGISTRY, "no-volume", (__name__, "_NoVolume"))
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[4].pop("makeup_water"))  # ends on the minimum volume
    stock = _by_id(duty_report(root, ["SPEC-DOSED"]), "SPEC-DOSED")
    _duties(root, lambda duties: duties[4]["reservoir"].__setitem__("model", "permuted-carbonate"))
    permuted = _by_id(duty_report(root, ["SPEC-DOSED"]), "SPEC-DOSED")
    assert permuted.ended == stock.ended == "minimum-inventory"
    assert permuted.simulated_h == pytest.approx(stock.simulated_h, rel=1e-9)
    for key in ("cation_mol", "carbon_mol", "volume_l", "ph"):
        assert permuted.series[key] == pytest.approx(stock.series[key], rel=1e-9, abs=1e-12)
    assert permuted.series["cation_mol"][0] == pytest.approx(0.2)
    _duties(root, lambda duties: duties[4]["reservoir"].__setitem__("model", "no-volume"))
    report = duty_report(root, ["SPEC-DOSED"])
    assert _by_id(report, "SPEC-DOSED").refused
    species = next(f for f in report.errors if f.rule == "cheme.duty-model-species")
    assert "volume (L)" in species.message


def test_the_json_records_the_measured_range(tmp_path):
    report = duty_report(_plant(tmp_path), ["MEAS-150", "MEAS-POWER", "SPEC-CONST"])
    payload = json.loads(report.to_json())
    ranges = {d["id"]: d["measured_range"] for d in payload["duties"]}
    meas = ranges["MEAS-150"]
    assert meas["basis"] == "measured" and meas["current_density_a_m2"] == [500.0, 2000.0]
    assert meas["source"] == "experiments/electrochemistry/synthetic-bpm.yaml"
    assert meas["temperature_k"] and meas["water_dissociation_efficiency"]
    assert meas["power_w"] is None and ranges["MEAS-POWER"]["power_w"][1] < 4.5
    spec = ranges["SPEC-CONST"]
    assert spec["basis"] == "specified" and spec["current_density_a_m2"] == [500, 4000]
    assert "measured range: current density 500-2000 A/m2" in ed.report_text(report)


def test_cli_compare_with_plots_ids_and_tolerance(tmp_path, monkeypatch):
    root = _plant(tmp_path)
    monkeypatch.chdir(root)
    args = ["process", "duty", "--compare", "SPEC-CONST,SPEC-ONOFF", "--co", "0.02"]
    result = runner.invoke(app, [*args, "--plot", str(tmp_path / "c")])
    assert result.exit_code == 0, result.output
    assert {p.name for p in (tmp_path / "c").iterdir()} >= {
        "duty-SPEC-CONST.svg",
        "duty-SPEC-ONOFF.svg",
    }
    result = runner.invoke(app, ["process", "duty", "MEAS-150", *args[2:]])
    assert result.exit_code == 2 and "MEAS-150" in result.output
    result = runner.invoke(app, [*args, "--tolerance", "0.01", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["tolerance"] == 0.01
    expected = compare_duties(root, ["SPEC-CONST", "SPEC-ONOFF"], 0.02, 0.01).as_dict()
    assert payload == json.loads(json.dumps(expected))


# -- totals by route, reservoir.size: to_horizon, a duty naming a stack -------------------------


def _closes(t: dict) -> tuple[float, float]:
    """The relative residuals of the cation and the carbon balance by route."""
    cation = (
        t["initial_cation_mol"]
        + t["dosing_cation_mol"]
        - t["bleed_cation_mol"]
        - t["membrane_cation_mol"]
    )
    carbon = (
        t["initial_carbon_mol"]
        + t["membrane_carbon_mol"]
        - t["bleed_carbon_mol"]
        - t["co2_degassed_mol"]
    )
    return (
        abs(cation - t["final_cation_mol"]) / t["final_cation_mol"],
        abs(carbon - t["final_carbon_mol"]) / max(t["final_carbon_mol"], 1e-30),
    )


def test_totals_by_route_close_the_cation_and_carbon_balances(tmp_path):
    """Every duty's cation (initial + dosed - bled - membrane = final) and carbon (initial +
    membrane - bled - degassed = final) close by route alone to 1e-9, with dosing, a bleed,
    make-up water and degassing; the membrane's routes are the co-ion current's shares
    (specified: 0.34 K+ and 0.66 HCO3- of (1 - WDE) Q / F, WDE 0.95)."""
    root = _plant(tmp_path)

    def degas(duties):
        duty = json.loads(json.dumps(duties[4]))  # SPEC-DOSED
        duty["id"] = "SPEC-DEGAS"
        duty["reservoir"]["composition"] = {
            "bicarbonate": {"value": 0.5, "unit": "mol/L"},
            "co2": {"value": 0.05, "unit": "mol/L"},
        }
        duty["threshold"]["ph"] = 6  # dosed from the start (trigger pH 13), CO2 degassing
        duty["reservoir"]["degassing"] = {
            "kla": {"value": 5, "unit": "1/h"},
            "co2_partial_pressure": {"value": 0.0004, "unit": "atm"},
        }
        duties.append(duty)

    _duties(root, degas)
    report = duty_report(root)
    for d in report.duties:
        assert not d.refused, d.reasons
        cation, carbon = _closes(d.totals)
        assert cation <= 1e-9 and carbon <= 1e-9, (d.id, cation, carbon)
    dosed = _by_id(report, "SPEC-DOSED").totals
    assert dosed["bleed_cation_mol"] > 0 and dosed["dosing_cation_mol"] == dosed["dosing_mol"]
    assert _by_id(report, "SPEC-DEGAS").totals["co2_degassed_mol"] > 0
    t = _by_id(report, "SPEC-CONST").totals
    co = 0.05 * t["charge_c"] / FARADAY
    assert t["membrane_cation_mol"] == pytest.approx(0.34 * co, rel=1e-12)
    assert t["membrane_carbon_mol"] == pytest.approx(0.66 * co, rel=1e-12)
    assert t["bleed_cation_mol"] == 0 and t["bleed_carbon_mol"] == 0
    # one carbon per HCO3-: the membrane's routes together are the hydroxide deficit
    for d in report.duties:
        m = d.totals
        assert m["membrane_cation_mol"] + m["membrane_carbon_mol"] == pytest.approx(
            m["hydroxide_deficit_mol"], rel=1e-9
        )
    # in the totals and the text, not the series
    assert "routes" not in _by_id(report, "SPEC-CONST").series
    assert "by route: cation" in ed.report_text(report)


def test_reservoir_size_to_horizon_gives_the_exact_volume(tmp_path):
    """MEAS-150 (1 L, no dosing) reaches pH 12 at t_thr; size: to_horizon gives V0 H / t_thr,
    and a reservoir just below it reaches the threshold before the horizon, just above it
    does not; with a time margin the target is H (1 + m), or H + a time; the same volume comes
    from a stated volume that does not reach the threshold (the charge path followed)."""
    root = _plant(tmp_path)
    plain = _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")
    _duties(root, lambda duties: duties[0]["reservoir"].update(size="to_horizon"))
    report = duty_report(root, ["MEAS-150"])
    d = _by_id(report, "MEAS-150")
    assert d.totals == plain.totals  # the run itself as without size
    exact = 1.0 * 2000 / d.time_to_threshold_h
    need = d.required_volume
    assert need["volume_l"] == pytest.approx(exact, rel=1e-12)
    assert need["target_h"] == 2000 and need["probe_volume_l"] == 1.0
    assert any(
        f.rule == "cheme.duty-size" and f.level == "info" and f"{exact:.6g} L" in f.message
        for f in report.findings
    )
    assert "reservoir.size to_horizon" in ed.report_text(report)

    def at(volume, margin=None):
        def edit(duties):
            duties[0]["reservoir"]["volume"]["value"] = volume
            if margin is not None:
                duties[0]["reservoir"]["time_margin"] = margin

        _duties(root, edit)
        return _by_id(duty_report(root, ["MEAS-150"]), "MEAS-150")

    below, above = at(exact * (1 - 1e-4)), at(exact * (1 + 1e-4))
    assert below.ended == "threshold" and not below.feasible
    assert above.ended == "horizon" and above.feasible
    # from above: the threshold is not reached in the run, the charge path gives the same
    assert above.required_volume["volume_l"] == pytest.approx(exact, rel=1e-9)
    assert at(10 * exact).required_volume["volume_l"] == pytest.approx(exact, rel=1e-9)
    assert at(1.0, {"value": 10, "unit": "%"}).required_volume["volume_l"] == pytest.approx(
        1.1 * exact, rel=1e-9
    )
    margin = at(1.0, {"value": 500, "unit": "h"}).required_volume
    assert margin["volume_l"] == pytest.approx(2500 / 2000 * exact, rel=1e-9)
    assert margin["target_h"] == 2500


def test_reservoir_size_to_horizon_with_an_on_off_schedule_is_exact(tmp_path):
    """On and off at one current: the volume scales with the charge, not the time
    (V0 Q(H) / Q*); a reservoir 1e-4 below reaches the threshold first, 1e-4 above does not."""
    root = _plant(tmp_path)

    def onoff(duties):
        duty = duties[3]  # SPEC-ONOFF: 2 A, half of 4 h
        duty["reservoir"]["size"] = "to_horizon"
        duty["horizon"]["value"] = 1000
        duty["schedule"]["period"]["value"] = 7  # the threshold falls inside an on period

    _duties(root, onoff)
    need = _by_id(duty_report(root, ["SPEC-ONOFF"]), "SPEC-ONOFF").required_volume
    assert need["volume_l"] is not None, need
    for factor, ended in ((1 - 1e-4, "threshold"), (1 + 1e-4, "horizon")):
        _duties(
            root, lambda d, f=factor: d[3]["reservoir"]["volume"].update(value=need["volume_l"] * f)
        )
        assert _by_id(duty_report(root, ["SPEC-ONOFF"]), "SPEC-ONOFF").ended == ended


def test_reservoir_size_to_horizon_is_refused_where_the_scaling_is_not_exact(tmp_path):
    """Dosing, bleed and make-up (SPEC-DOSED), or two current densities (a measured cell's
    WDE changes): a cheme.duty-size error and no volume; the duty itself still runs. A time
    margin without size is a warning; cheme validate reports the static refusals."""
    root = _plant(tmp_path)

    def edit(duties):
        duties[4]["reservoir"]["size"] = "to_horizon"  # SPEC-DOSED
        duties[1]["reservoir"]["size"] = "to_horizon"  # MEAS-POWER: leaves the range
        duties[0]["schedule"] = {  # MEAS-150 at two current densities
            "kind": "piecewise",
            "points": [[0, 150], [10, 100]],
            "unit": "mA/cm2",
        }
        duties[0]["reservoir"]["size"] = "to_horizon"
        duties[2]["reservoir"]["time_margin"] = {"value": 0.1}  # SPEC-CONST, no size

    _duties(root, edit)
    report = duty_report(root)
    errors = {f.ids[0]: f.message for f in report.findings if f.rule == "cheme.duty-size"}
    assert "dosing, a bleed, make-up water" in errors["SPEC-DOSED"]
    assert "more than one water dissociation efficiency" in errors["MEAS-150"]
    assert "measured range" in errors["MEAS-POWER"]
    for did in ("SPEC-DOSED", "MEAS-150", "MEAS-POWER"):
        d = _by_id(report, did)
        assert not d.refused and d.required_volume["volume_l"] is None
    assert any(
        f.rule == "cheme.duty-size" and f.level == "warning" and "SPEC-CONST" in f.ids
        for f in report.findings
    )
    static = {(f.ids[0], f.level) for f in duty_findings(root) if f.rule == "cheme.duty-size"}
    assert static == {("SPEC-DOSED", "error"), ("SPEC-CONST", "warning")}


def test_a_duty_naming_an_unknown_stack_is_refused(tmp_path):
    """stack: names a stack of process/cells.yaml (cheme validate), and a duty naming one
    runs only at that stack's arrangement: given none, it is refused."""
    root = _plant(tmp_path)
    _duties(root, lambda duties: duties[2].update(stack="STK-X"))
    assert any(
        f.rule == "cheme.duty-arrangement" and f.level == "error" and "STK-X" in f.message
        for f in duty_findings(root)
    )
    report = duty_report(root, ["SPEC-CONST"])
    d = _by_id(report, "SPEC-CONST")
    assert d.refused and "whose arrangement is not given" in d.reasons[0]
    compared = compare_duties(root, ["SPEC-CONST"], 0.01)
    assert not compared.rows[0].reached and "STK-X" in compared.rows[0].reason
