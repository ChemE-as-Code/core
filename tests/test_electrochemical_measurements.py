"""Measured electrochemical series (domains/experiments/electrochemistry.py): Faradaic
efficiency from gas data, the water dissociation efficiency from the anolyte titration, the
point statistics, the rules, the measured performance (interpolated, never extrapolated), the
plots and the command.

Reference values (independent of the code):

- F = 96485.33212 C/mol and R = 8.314462618 J/(mol K), CODATA 2018 (both exact);
- the pooled water dissociation efficiency of the reverse-bias bipolar-membrane cell in 1 M KOH
  at 25/50/100/150/200/250 mA/cm2, 0.6305/0.8233/0.9303/0.9576/0.9656/0.9782 (sd
  0.0323/0.0307/0.0154/0.0082/0.0101/0.0058), as process-library#329 reproduced them from the
  4TU raw data of Prats Vergel, Vermaas, Burdyny et al. (Nat. Chem. Eng. 2025,
  doi:10.4121/5c4fc325-a71b-4ca8-9c1b-01c0405936a2.v1). Only these numbers are used here, not
  the data set.
"""

from __future__ import annotations

import copy
import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.experiments.electrochemistry import (
    FARADAY,
    GAS_CONSTANT,
    MODEL,
    ElectrochemicalMeasurements,
    MeasuredPerformance,
    evaluate,
    measurement_plots,
    measurement_report,
)
from chemeascode.interfaces.cli import app

DATA = Path(__file__).resolve().parent / "data" / "electrochemical" / "co2-bpm"
SERIES = "experiments/electrochemistry/synthetic-bpm.yaml"
runner = CliRunner()

#: process-library#329: pooled WDE (mean, sd) by current density in mA/cm2
WDE_329 = {
    25: (0.6305, 0.0323),
    50: (0.8233, 0.0307),
    100: (0.9303, 0.0154),
    150: (0.9576, 0.0082),
    200: (0.9656, 0.0101),
    250: (0.9782, 0.0058),
}

BASE = {
    "schema": "cheme/electrochemical-measurements/v1",
    "kind": "electrochemical_measurements",
    "id": "test",
    "provenance": "given",
    "source": "test data",
    "cell": {
        "active_area": {"value": 5, "unit": "cm2"},
        "temperature": {"value": 298.15, "unit": "K"},
    },
    "voltage_basis": "cell",
    "products": [
        {"id": "CO", "electrons": 2, "electrode": "cathode", "reaction": "CO2R"},
        {"id": "H2", "electrons": 2, "electrode": "cathode", "reaction": "WS"},
    ],
    "points": [
        {
            "id": "P1",
            "current": {"value": 0.5, "unit": "A"},
            "duration": {"value": 3600, "unit": "s"},
            "replicates": [
                {
                    "id": "R1",
                    "voltage": {"value": 3.0},
                    "faradaic_efficiency": {"CO": {"value": 0.7}, "H2": {"value": 0.25}},
                }
            ],
        }
    ],
}

GAS = {
    "flow_unit": "sccm",
    "standard_conditions": {
        "temperature": {"value": 273.15, "unit": "K"},
        "pressure": {"value": 101.325, "unit": "kPa"},
    },
    "flow_correction": {"factor": 1.0, "source": "test"},
}

TITRATION = {
    "method": "warder-double-endpoint",
    "titrant_concentration": {"value": 0.1, "unit": "mol/L"},
    "anolyte_volume": {"value": 90, "unit": "mL"},
    "aliquot_volume": {"value": 1, "unit": "mL"},
}


def _data(edit=None) -> dict:
    data = copy.deepcopy(BASE)
    if edit is not None:
        edit(data)
    return data


def _run(data: dict):
    return evaluate(ElectrochemicalMeasurements.model_validate(data), "m.yaml")


def _file(tmp_path: Path, data: dict, name: str = "m.yaml") -> Path:
    folder = tmp_path / "experiments" / "electrochemistry"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _report(tmp_path: Path, data: dict):
    path = _file(tmp_path, data)
    return measurement_report(tmp_path, path.relative_to(tmp_path))


def _rules(report, level: str | None = None) -> set[str]:
    return {f.rule for f in report.findings if level is None or f.level == level}


def _rep(data: dict, point: int = 0, rep: int = 0) -> dict:
    return data["points"][point]["replicates"][rep]


# -- Faradaic efficiency and the water dissociation efficiency ----------------------------------


def test_faradaic_efficiency_from_gas_data_by_hand():
    """0.5 A, 50 sccm at 273.15 K and 101.325 kPa with 2 mol% CO: the molar flow is
    p V / (R T), the CO flow 2 % of it, FE = 2 F Ndot_CO / I."""

    def edit(d):
        d["gas"] = GAS
        rep = _rep(d)
        del rep["faradaic_efficiency"]
        rep.update(outlet_flow=50, fractions={"CO": {"value": 2, "unit": "mol%"}})

    report = _run(_data(edit))
    assert not _rules(report, "error")
    total = 50e-6 / 60 * 101325 / (GAS_CONSTANT * 273.15)  # mol/s
    fe = 2 * FARADAY * 0.02 * total / 0.5
    # by hand: 0.05 L/min / 22.414 L/mol (molar volume at 273.15 K, 101.325 kPa) = 3.718e-5
    # mol/s; 2 % of it, times 2F / 0.5 A
    assert fe == pytest.approx(0.28698, abs=5e-5)
    rep = report.points[0].replicates[0]
    assert rep.outlet_flow_mol_s == pytest.approx(total, rel=1e-12)
    assert rep.faradaic_efficiency["CO"] == pytest.approx(fe, rel=1e-12)
    assert rep.faradaic_basis["CO"] == "gas"
    # j = 0.5 A / 5 cm2 = 1000 A/m2; j_CO = FE j
    assert report.points[0].current_density_a_m2 == pytest.approx(1000)
    assert rep.partial_current_density_a_m2["CO"] == pytest.approx(fe * 1000, rel=1e-12)
    # charge balance: sum FE + unassigned = 1
    assert rep.faradaic_sum + rep.unassigned_current_fraction == pytest.approx(1.0, abs=1e-15)
    # the same in ppm, and a meter correction multiplies the flow
    report = _run(
        _data(
            lambda d: (
                edit(d),
                _rep(d)["fractions"].update(CO={"value": 20000, "unit": "ppm"}),
                d["gas"].update(flow_correction={"factor": 1.1, "source": "test"}),
            )
        )
    )
    assert report.points[0].replicates[0].faradaic_efficiency["CO"] == pytest.approx(1.1 * fe)


def _titration_point(volumes: dict) -> dict:
    """25 mA/cm2 on 5 cm2 (0.125 A) for 3600 s, 0.1 M HCl, 90 mL anolyte, 1 mL aliquots."""

    def edit(d):
        d["titration"] = TITRATION
        d["cell"]["membrane"] = {"kind": "bipolar", "bias": "reverse"}
        point = d["points"][0]
        point.pop("current")
        point["current_density"] = {"value": 25, "unit": "mA/cm2"}
        point["replicates"] = [{"id": "R1", "titration": volumes}]

    return _data(edit)


def test_water_dissociation_efficiency_from_the_titration_by_hand():
    """The paper's equations (process-library#329 reproduced them) on a synthetic point whose
    volumes give the pooled 25 mA/cm2 value, 0.6305: V0 - V2 = 0.0496 mL of K+ lost and
    V2 - V1 = 0.1419 mL of carbon gained, of 0.1 M HCl, times 90 mL / 1 mL."""
    volumes = {"V0": 10.000, "V1": 9.8085, "V2": 9.9504}
    report = _run(_titration_point(volumes))
    assert not _rules(report, "error") and not _rules(report, "warning")
    rep = report.points[0].replicates[0]
    n_k = (10.000 - 9.9504) * 1e-3 * 0.1 * 90 / 1  # mol
    n_c = (9.9504 - 9.8085) * 1e-3 * 0.1 * 90 / 1
    wde = 1 - FARADAY * (n_k + n_c) / (0.125 * 3600)
    assert rep.co_ions_mol["cation"] == pytest.approx(n_k, rel=1e-12)
    assert rep.co_ions_mol["carbon"] == pytest.approx(n_c, rel=1e-12)
    assert rep.water_dissociation_efficiency == pytest.approx(wde, rel=1e-12)
    assert rep.water_dissociation_basis == "titration"
    assert wde == pytest.approx(WDE_329[25][0], abs=5e-4)  # rounding of the volumes
    assert rep.co_ion_carbon_fraction == pytest.approx(n_c / (n_k + n_c))
    assert rep.co_ion_carbon_fraction == pytest.approx(0.741, abs=1e-3)
    # the titration does not touch the Faradaic efficiency (none measured here)
    assert rep.faradaic_efficiency == {} and rep.faradaic_sum is None


def _series_329() -> dict:
    """A measurement file with the pooled #329 series as two direct replicates per point,
    mean +- sd / sqrt(2): their mean and sample standard deviation are the published pair."""

    def edit(d):
        d["cell"]["membrane"] = {"kind": "bipolar", "bias": "reverse"}
        d["points"] = [
            {
                "id": f"j{j}",
                "current_density": {"value": j, "unit": "mA/cm2"},
                "duration": {"value": 3600, "unit": "s"},
                "replicates": [
                    {
                        "id": f"R{k}",
                        "water_dissociation_efficiency": {"value": m + s * sd / math.sqrt(2)},
                    }
                    for k, s in ((1, -1), (2, 1))
                ],
            }
            for j, (m, sd) in WDE_329.items()
        ]

    return _data(edit)


def test_the_329_series_interpolates_and_refuses_outside_25_to_250(tmp_path):
    report = _report(tmp_path, _series_329())
    assert not _rules(report, "error")
    for point, (j, (mean, sd)) in zip(report.points, WDE_329.items(), strict=True):
        assert point.current_density_a_m2 == pytest.approx(10 * j)
        stat = point.water_dissociation_efficiency
        assert (stat.mean, stat.sd, stat.n) == (pytest.approx(mean), pytest.approx(sd), 2)
    performance = MeasuredPerformance(report)
    assert performance.bounds == (250.0, 2500.0)  # derived from the points
    assert "cheme.electrochem-validity" in _rules(report, "info")
    # at a measured point: its values; between two: linear in the current density
    at = performance.at(1000.0)
    assert at.bracket == ("j100", "j100") and at.water_dissociation_efficiency == pytest.approx(
        0.9303
    )
    at = performance.at(750.0)
    assert at.available and at.bracket == ("j50", "j100")
    assert at.water_dissociation_efficiency == pytest.approx((0.8233 + 0.9303) / 2)
    assert at.water_dissociation_efficiency_sd == pytest.approx((0.0307 + 0.0154) / 2)
    at = performance.at(2200.0)
    assert at.water_dissociation_efficiency == pytest.approx(0.9656 + 0.4 * (0.9782 - 0.9656))
    assert performance.at(250.0).water_dissociation_efficiency == pytest.approx(0.6305)
    assert performance.at(2500.0).water_dissociation_efficiency == pytest.approx(0.9782)
    # outside 25-250 mA/cm2: no value, never extrapolated
    for j in (200.0, 2600.0, 0.0):
        at = performance.at(j)
        assert not at.in_range and at.extrapolated and not at.available
        assert at.water_dissociation_efficiency is None and at.voltage_v is None
        assert at.bounds == (250.0, 2500.0) and "outside the validity range" in at.reason


# -- the synthetic series -----------------------------------------------------------------------


def test_synthetic_series_balances(tmp_path):
    report = measurement_report(DATA, SERIES)
    assert not _rules(report, "error") and not _rules(report, "warning")
    assert report.source.fingerprints.keys() == {SERIES}
    for point in report.points:
        assert point.faradaic_sum.n == 2 and point.voltage_v.sd is not None
        for rep in point.replicates:
            assert rep.faradaic_sum + rep.unassigned_current_fraction == pytest.approx(1.0)
            # the CO2 fed leaves as CO2, CO and carbonate in the anolyte (to the rounding)
            assert rep.carbon["closed"] and abs(rep.carbon["relative_residual"]) < 0.005
            # P = U I; Q = I (U - sum FE_i U_tn,i)
            current = point.current_a
            assert rep.power_w == pytest.approx(rep.voltage_v * current)
            utn = {"CO": 1.46644, "H2": 1.48121}
            assert rep.heat_w == pytest.approx(
                current
                * (rep.voltage_v - sum(fe * utn[n] for n, fe in rep.faradaic_efficiency.items()))
            )
    # the chronopotentiometry replicate: the mean over 600-3600 s, start-up left out
    p200 = report.points[2].replicates[1]
    assert p200.voltage_v == pytest.approx((3.88 + 3.86 + 3.85 + 3.86 + 3.85 + 3.86) / 6)
    assert p200.voltage_samples == 6


def test_measured_performance_interpolates_between_points():
    report = measurement_report(DATA, SERIES)
    performance = MeasuredPerformance(report)
    p100, p200 = report.points[1], report.points[2]
    at = performance.at(1500.0)
    assert at.in_range and not at.extrapolated and at.bracket == ("P100", "P200")
    assert at.voltage_v == pytest.approx((p100.voltage_v.mean + p200.voltage_v.mean) / 2)
    co = (p100.faradaic_efficiency["CO"].mean + p200.faradaic_efficiency["CO"].mean) / 2
    assert at.faradaic_efficiency["CO"] == pytest.approx(co)
    assert at.voltage_basis == "cell"
    # below the declared 500 A/m2: refused
    at = performance.at(400.0)
    assert not at.in_range and at.voltage_v is None and not at.faradaic_efficiency


def test_declared_validity_beyond_the_points_is_still_not_extrapolated(tmp_path):
    data = yaml.safe_load((DATA / SERIES).read_text(encoding="utf-8"))
    data["validity"]["current_density"] = [250, 3000]
    report = _report(tmp_path, data)
    assert "cheme.electrochem-validity" in _rules(report, "warning")
    at = MeasuredPerformance(report).at(2500.0)
    assert at.in_range and at.extrapolated and not at.available and at.voltage_v is None
    assert "beyond the measured points" in at.reason


def test_fe_and_wde_are_separate():
    """A titration changes the water dissociation efficiency, never the Faradaic efficiency,
    and the other way round."""
    base = _titration_point({"V0": 10.0, "V1": 9.8, "V2": 9.95})

    def with_fe(d, co):
        _rep(d)["faradaic_efficiency"] = {"CO": {"value": co}}

    one = _run(_data(lambda d: (d.update(copy.deepcopy(base)), with_fe(d, 0.7))))
    two = _run(_data(lambda d: (d.update(copy.deepcopy(base)), with_fe(d, 0.5))))
    other = copy.deepcopy(base)
    _rep(other)["titration"] = {"V0": 10.0, "V1": 9.9, "V2": 9.98}
    three = _run(_data(lambda d: (d.update(other), with_fe(d, 0.7))))
    r1, r2, r3 = (r.points[0].replicates[0] for r in (one, two, three))
    assert r1.water_dissociation_efficiency == r2.water_dissociation_efficiency
    assert r1.faradaic_efficiency == r3.faradaic_efficiency
    assert r1.water_dissociation_efficiency != r3.water_dissociation_efficiency
    assert r1.unassigned_current_fraction == pytest.approx(0.3)  # 1 - FE, WDE plays no part


# -- rules --------------------------------------------------------------------------------------


def test_schema_errors_name_the_line(tmp_path):
    data = _data(lambda d: _rep(d).update(colour="red"))
    path = _file(tmp_path, data)
    report = measurement_report(tmp_path, path)
    assert not report.points
    lines = path.read_text(encoding="utf-8").splitlines()
    line = next(i for i, text in enumerate(lines, start=1) if "colour:" in text)
    assert [(f.rule, f.line) for f in report.findings] == [("cheme.electrochem-schema", line)]
    assert report.findings[0].file == "experiments/electrochemistry/m.yaml"


@pytest.mark.parametrize(
    "edit",
    [
        # gas data and a direct Faradaic efficiency for one product
        lambda d: _rep(d).update(fractions={"CO": {"value": 1, "unit": "mol%"}}),
        # current and current density
        lambda d: d["points"][0].update(current_density={"value": 1, "unit": "A/m2"}),
        # a titration and a direct WDE
        lambda d: _rep(d).update(
            titration={"V0": 1, "V1": 0.5, "V2": 0.8},
            water_dissociation_efficiency={"value": 0.9},
        ),
        # a voltage as value and series
        lambda d: _rep(d).update(voltage={"value": 3.0, "series": [[0, 3.0]]}),
    ],
)
def test_one_way_per_quantity(edit):
    with pytest.raises(ValueError):
        ElectrochemicalMeasurements.model_validate(_data(edit))


@pytest.mark.parametrize(
    ("edit", "rule"),
    [
        (lambda d: d["products"].append(dict(d["products"][0])), "cheme.electrochem-schema"),
        (lambda d: d["points"].append(copy.deepcopy(d["points"][0])), "cheme.electrochem-schema"),
        (
            lambda d: _rep(d)["faradaic_efficiency"].update(HCOOH={"value": 0.1}),
            "cheme.electrochem-schema",
        ),
        (lambda d: d["points"][0]["current"].update(unit="mA/m2"), "cheme.electrochem-unit"),
        (lambda d: _rep(d)["voltage"].update(unit="kV"), "cheme.electrochem-unit"),
        (
            lambda d: (
                d.update(gas={"flow_unit": "sccm"})
                or _rep(d).update(outlet_flow=50, fractions={"CO2": {"value": 90, "unit": "mol%"}})
            ),
            "cheme.electrochem-input-missing",
        ),
        (
            lambda d: d.update(gas=GAS) or _rep(d).update(fractions={"H2O": {"value": 1}}),
            "cheme.electrochem-schema",
        ),
        (
            lambda d: (
                d.update(gas=GAS)
                or _rep(d).pop("faradaic_efficiency")
                and _rep(d).update(fractions={"CO": {"value": 2, "unit": "mol%"}})
            ),
            "cheme.electrochem-input-missing",
        ),
        (
            lambda d: _rep(d).update(titration={"V0": 10, "V1": 9.8, "V2": 9.9}),
            "cheme.electrochem-input-missing",
        ),
        (
            lambda d: (
                d.update(titration=TITRATION)
                or d["points"][0].pop("duration")
                and _rep(d).update(titration={"V0": 10, "V1": 9.8, "V2": 9.9})
            ),
            "cheme.electrochem-input-missing",
        ),
        (
            lambda d: _rep(d).update(voltage={"series": [[0, 3.0], [10, 3.1]], "window": [20, 30]}),
            "cheme.electrochem-input-missing",
        ),
    ],
)
def test_error_findings(edit, rule):
    report = _run(_data(edit))
    assert rule in _rules(report, "error"), [f.format() for f in report.findings]
    finding = next(f for f in report.findings if f.rule == rule)
    assert finding.file == "m.yaml" and finding.hint


def test_standard_conditions_are_never_assumed():
    def edit(d):
        d["gas"] = {"flow_unit": "slpm"}
        rep = _rep(d)
        del rep["faradaic_efficiency"]
        rep.update(outlet_flow=0.05, fractions={"CO": {"value": 2, "unit": "mol%"}})

    report = _run(_data(edit))
    finding = next(f for f in report.findings if f.rule == "cheme.electrochem-input-missing")
    assert "273.15 K and 101.325 kPa" in finding.hint and "never assumed" in finding.hint
    assert report.points[0].replicates[0].faradaic_efficiency == {}
    # a molar flow needs no standard conditions
    report = _run(
        _data(
            lambda d: (
                edit(d),
                d["gas"].update(flow_unit="mol/s"),
                _rep(d).update(outlet_flow=1e-5),
            )
        )
    )
    assert not _rules(report, "error")
    assert report.points[0].replicates[0].faradaic_efficiency["CO"] == pytest.approx(
        2 * FARADAY * 0.02 * 1e-5 / 0.5
    )


@pytest.mark.parametrize(
    ("values", "level"),
    [
        ([1.10], "error"),  # one replicate above 1.05
        ([1.04], None),  # one replicate, within 1.05
        ([1.02, 1.03], "error"),  # mean 1.025 > 1 + 3 x 0.0071
        ([0.99, 1.05], None),  # mean 1.02 < 1 + 3 x 0.042
        ([0.85], "warning"),  # below 0.9: an unmeasured product
    ],
)
def test_faradaic_sum(values, level):
    def edit(d):
        d["points"][0]["replicates"] = [
            {"id": f"R{k}", "faradaic_efficiency": {"CO": {"value": v}}}
            for k, v in enumerate(values)
        ]

    report = _run(_data(edit))
    high = "cheme.electrochem-fe-sum-high" in _rules(report, "error")
    low = "cheme.electrochem-fe-sum-low" in _rules(report, "warning")
    assert (high, low) == (level == "error", level == "warning")
    assert ("cheme.electrochem-single-replicate" in _rules(report, "info")) == (len(values) == 1)
    if len(values) == 1:
        assert report.points[0].faradaic_sum.sd is None


def test_warnings_and_infos():
    report = _run(_data(lambda d: d["cell"].update(membrane={"kind": "bipolar"})))
    assert "cheme.electrochem-crossover-assumed" in _rules(report, "warning")
    assert "cheme.electrochem-heat" in _rules(report, "info")  # no thermoneutral voltages
    assert report.points[0].replicates[0].heat_w is None
    assert report.points[0].replicates[0].power_w == pytest.approx(1.5)
    report = _run(_data())
    assert "cheme.electrochem-crossover-assumed" not in _rules(report)  # no membrane
    # titration volumes out of order
    data = _titration_point({"V0": 10.0, "V1": 9.95, "V2": 9.9})
    assert "cheme.electrochem-titration" in _rules(_run(data), "warning")

    def flows(d, position: str | None = None, correction: bool = True):
        d["gas"] = copy.deepcopy(GAS)
        if not correction:
            del d["gas"]["flow_correction"]
        if position:
            d["gas"]["flow_position"] = position
        rep = _rep(d)
        del rep["faradaic_efficiency"]
        rep.update(outlet_flow=20, fractions={"CO": {"value": 10, "unit": "mol%"}})

    assert "cheme.electrochem-flow-correction" in _rules(
        _run(_data(lambda d: flows(d, correction=False))), "info"
    )
    report = _run(_data(lambda d: flows(d, "inlet")))
    assert "cheme.electrochem-flow-position" in _rules(report, "warning")
    # a carbon balance far off: the CO2 fed does not match the outlet
    data = yaml.safe_load((DATA / SERIES).read_text(encoding="utf-8"))
    data["gas"]["inlet"]["flow"] = 30
    report = evaluate(ElectrochemicalMeasurements.model_validate(data), SERIES)
    assert "cheme.electrochem-carbon-balance" in _rules(report, "warning")
    del data["gas"]["inlet"]
    report = evaluate(ElectrochemicalMeasurements.model_validate(data), SERIES)
    assert any("carbon balance not checked" in text for text in report.limitations)


def test_electrode_potentials_are_no_terminal_voltage():
    report = _run(_data(lambda d: d.update(voltage_basis="electrode_vs_reference")))
    assert "cheme.electrochem-voltage-basis" in _rules(report, "info")
    assert report.points[0].power_w is None
    at = MeasuredPerformance(report).at(1000.0)
    assert at.available and at.voltage_v is None  # the efficiencies only
    figures = measurement_plots(report)
    assert "polarisation.svg" not in figures and "electrode-potential.svg" in figures
    assert "not a cell voltage" in figures["electrode-potential.svg"]


def test_plots_only_for_supported_inputs():
    figures = measurement_plots(measurement_report(DATA, SERIES))
    assert set(figures) == {
        "polarisation.svg",
        "faradaic-efficiency.svg",
        "partial-current-density.svg",
        "water-dissociation-efficiency.svg",
    }
    for svg in figures.values():
        root = ET.fromstring(svg)
        assert (
            root.tag.endswith("svg") and root.find("{http://www.w3.org/2000/svg}title") is not None
        )
    assert "not a Faradaic efficiency" in figures["water-dissociation-efficiency.svg"]
    # no Faradaic efficiency and no titration: the polarisation curve only
    report = _run(_data(lambda d: _rep(d).pop("faradaic_efficiency")))
    assert set(measurement_plots(report)) == {"polarisation.svg"}


# -- the command and the function ---------------------------------------------------------------


def test_cli_json_is_the_report(tmp_path, monkeypatch):
    monkeypatch.chdir(DATA)
    result = runner.invoke(
        app, ["experiments", "electrochem", SERIES, "--json", "--plot", str(tmp_path / "fig")]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == json.loads(measurement_report(DATA, SERIES).to_json())
    assert payload["model"] == MODEL and payload["assumptions"] and payload["limitations"]
    assert payload["core_version"] and payload["points"][0]["voltage_v"]["n"] == 2
    assert set(payload["source"]["fingerprints"]) == {SERIES}
    assert len(list((tmp_path / "fig").glob("*.svg"))) == 4
    # from elsewhere, the function gives the same
    monkeypatch.chdir(tmp_path)
    assert measurement_report(DATA, SERIES).points[0].id == "P050"


def test_cli_outside_a_plant_and_exit_codes(tmp_path, monkeypatch):
    data = _data(lambda d: _rep(d)["faradaic_efficiency"]["CO"].update(value=1.2))
    path = tmp_path / "loose.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "electrochem", "loose.yaml"])
    assert result.exit_code == 1 and "fe-sum-high" in result.stdout
    assert "loose.yaml:" in result.stdout
    assert runner.invoke(app, ["experiments", "electrochem", "missing.yaml"]).exit_code == 2


def test_validate_reports_measurement_findings(tmp_path):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    (tmp_path / "plant.yaml").write_text(
        "name: t\ndescription: t\nstage: concept\nsheets: []\n", encoding="utf-8"
    )
    _file(tmp_path, _data(lambda d: _rep(d)["faradaic_efficiency"]["CO"].update(value=1.2)))
    report = validate_workspace(Workspace(tmp_path))
    assert "experiments/electrochemistry/m.yaml" in report.files
    assert "cheme.electrochem-fe-sum-high" in {f.rule for f in report.findings}


def test_schema_is_in_the_catalogue():
    from chemeascode.schemas import OTHER_SCHEMAS

    model, where = OTHER_SCHEMAS["electrochemical-measurements"]
    assert model is ElectrochemicalMeasurements and where == "experiments/electrochemistry/*.yaml"
    result = runner.invoke(app, ["schema", "electrochemical-measurements"])
    assert result.exit_code == 0 and "voltage_basis" in result.stdout


def test_import_needs_neither_typer_nor_fastapi():
    code = (
        "import sys; import chemeascode.domains.experiments.electrochemistry; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True, env={**os.environ})
