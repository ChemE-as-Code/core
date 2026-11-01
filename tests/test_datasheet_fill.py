"""``cheme datasheets fill``: calculated sizes with their basis in draft datasheets.

The expected numbers are hand calculations (worked in the comments), not outputs of the code."""

from __future__ import annotations

import copy
import math
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.equipment_cost import datasheet_size
from chemeascode.domains.equipment import sizing
from chemeascode.domains.equipment.datasheets import DRAFT_VOLUME
from chemeascode.domains.equipment.fill import (
    FILL_MARK,
    _Network,
    fill_datasheets,
    input_data,
    inputs_fingerprint,
    stale_findings,
    stream_fingerprint,
)
from chemeascode.domains.equipment.schemas.datasheet import Datasheet
from chemeascode.domains.process import hydraulics
from chemeascode.domains.process.separations import shortcut
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.datasheets import draft_missing

runner = CliRunner()


# -- hand calculations of the typed functions -----------------------------------------------------


def test_exchanger_lmtd_f_and_area_by_hand():
    # hot 120 -> 60 degC, cold 20 -> 50 degC (as K differences)
    # counter-current: dT1 = 120 - 50 = 70, dT2 = 60 - 20 = 40, LMTD = 30 / ln(1.75) = 53.608 K
    hot, cold = (393.15, 333.15), (293.15, 323.15)
    assert sizing.lmtd(*hot, *cold, "counter-current") == pytest.approx(53.608, abs=1e-3)
    # co-current: dT1 = 100, dT2 = 10, LMTD = 90 / ln 10 = 39.087 K
    assert sizing.lmtd(*hot, *cold, "co-current") == pytest.approx(39.087, abs=1e-3)
    # 1-2: R = 60/30 = 2, P = 30/100 = 0.3, S = sqrt(5) = 2.236068
    # F = S ln((1-P)/(1-PR)) / ((R-1) ln((2-P(R+1-S))/(2-P(R+1+S))))
    #   = 2.236068 x 0.559616 / (1 x ln(1.770820 / 0.429180)) = 1.251339 / 1.417323 = 0.88289
    f = sizing.correction_factor(*hot, *cold, "1-2")
    assert f == pytest.approx(0.88289, abs=1e-4)
    # cooler/gases-water: 20-300 W/(m2 K), design typical 160 (ASSUMED)
    u = sizing.typical_u("cooler/gases-water")
    assert u is not None and u.value == 160 and "Table 12.1" in u.source
    # A = 100 kW / (160 x 0.88289 x 53.608) = 13.205 m2; with 10 % margin 14.526 m2
    area = sizing.exchanger_area(100.0, 160.0, f, 53.608, 0.1)
    assert area == pytest.approx(14.526, abs=2e-3)
    with pytest.raises(ValueError, match="temperature cross"):
        sizing.lmtd(350, 300, 310, 360, "counter-current")


def test_line_loss_by_hand():
    # water 10 kg/s, rho 1000 kg/m3, mu 1 mPa s, DN 100 schedule 40: ID = 114.3 - 2 x 6.02 =
    # 102.26 mm, A = 8.2130e-3 m2, v = 1.2176 m/s, Re = 1.2451e5, e/D = 0.046 / 102.26 = 4.498e-4
    wall = hydraulics.wall_thickness(100, "40")
    assert wall is not None and wall.value == pytest.approx(0.00602)
    rough = hydraulics.roughness("commercial_steel")
    assert rough is not None and "Moody" in rough.source
    seg = hydraulics.Segment(4.5, 0.1143 - 2 * wall.value, rough.value, {"elbow_90": 0.75})
    loss = hydraulics.line_loss(10.0, 1000.0, 1e-3, [seg])
    s = loss.segments[0]
    assert s.velocity == pytest.approx(1.2176, abs=1e-4)
    assert s.reynolds == pytest.approx(1.2451e5, rel=1e-3)
    # Colebrook: f = 0.019555 (iterated by hand from 0.02: 0.019557, 0.019555, ...)
    assert s.friction_factor == pytest.approx(0.019555, abs=2e-6)
    rr = rough.value / seg.diameter
    residual = 1 / math.sqrt(s.friction_factor) + 2 * math.log10(
        rr / 3.7 + 2.51 / (s.reynolds * math.sqrt(s.friction_factor))
    )
    assert abs(residual) < 1e-9
    # h = (f L / D + K) v^2 / 2g = (0.019555 x 4.5 / 0.10226 + 0.75) x 1.2176^2 / 19.6133
    #   = (0.86053 + 0.75) x 0.075586 = 0.12173 m
    assert loss.head == pytest.approx(0.12173, abs=2e-5)
    assert hydraulics.friction_factor(1000, 1e-4) == (0.064, "laminar 64/Re")


def test_inside_diameter_takes_the_asme_od_of_the_schedule():
    # DN 125 sch 40: ASME B36.10M OD 141.3 mm (NPS 5, 5.563 in), wall 6.55 mm:
    # ID = 141.3 - 13.10 = 128.20 mm (the ISO OD 139.7 would give 126.6 mm)
    inside, od, wall = hydraulics.inside_diameter(125, "40")
    assert od.value == pytest.approx(0.1413) and wall.value == pytest.approx(0.00655)
    assert inside.value == pytest.approx(0.12820, abs=1e-6)
    # DN 25 sch 40: 33.4 - 2 x 3.38 = 26.64 mm; DN 65 sch 40: 73.0 - 2 x 5.16 = 62.68 mm
    assert hydraulics.inside_diameter(25, "40")[0].value == pytest.approx(0.02664, abs=1e-6)
    assert hydraulics.inside_diameter(65, "40")[0].value == pytest.approx(0.06268, abs=1e-6)
    # DN 65 sch 10S: 73.0 - 2 x 3.05 = 66.90 mm
    assert hydraulics.inside_diameter(65, "10S")[0].value == pytest.approx(0.0669, abs=1e-6)
    assert hydraulics.inside_diameter(65, "80") is None


def test_compressor_stages_and_ideal_gas_power_by_hand():
    # 100 -> 900 kPa(a), at most 3.5 per stage: n = ceil(ln 9 / ln 3.5) = ceil(1.754) = 2, r = 3
    n, r = sizing.stages_for(9.0, 3.5)
    assert (n, r) == (2, pytest.approx(3.0))
    # air, 300 K, k 1.4, M 28.96, eta_is 0.8:
    # RT/M = 8.314463 x 300 / 28.96 = 86.130 kJ/kg; k/(k-1) = 3.5; 3^(0.4/1.4) = 1.368738
    # w_s = 86.130 x 3.5 x 0.368738 = 111.158 kJ/kg; w = 111.158 / 0.8 = 138.947 kJ/kg
    # cp = 8.314463 x 1.4 / (0.4 x 28.96) = 1.004833 kJ/(kg K): T2 = 300 + 138.278 = 438.28 K
    stage = sizing.ideal_gas_stage(300.0, 3.0, 1.4, 28.96, 0.8)
    assert stage.work == pytest.approx(138.947, abs=2e-3)
    assert stage.outlet_temperature == pytest.approx(438.28, abs=1e-2)
    # polytropic, eta_p 0.8: (n-1)/n = 0.2857143 / 0.8 = 0.357143;
    # 3^0.357143 = e^0.392362 = 1.480475; the gas work is cp T1 (r^((n-1)/n) - 1)
    # = RT/M x k/(k-1) x 0.480475 = 86.130 x 3.5 x 0.480475 = 144.841 kJ/kg (the polytropic
    # head is 0.8 x this, 115.873); T2 = 300 x 1.480475 = 444.14 K. More than the
    # isentropic-efficiency-0.8 work 138.947: eta_is < eta_p in compression.
    poly = sizing.ideal_gas_stage(300.0, 3.0, 1.4, 28.96, 0.8, "polytropic")
    assert poly.work == pytest.approx(144.841, abs=2e-3)
    assert poly.outlet_temperature == pytest.approx(444.14, abs=1e-2)
    # expansion 1/3, eta_p 0.8: (n-1)/n = 0.2857143 x 0.8 = 0.228571; 3^-0.228571 = 0.777940;
    # w = 86.130 x 3.5 x (0.777940 - 1) = -66.942 kJ/kg; T2 = 300 x 0.777940 = 233.38 K
    expand = sizing.ideal_gas_stage(300.0, 1.0 / 3.0, 1.4, 28.96, 0.8, "polytropic")
    assert expand.work == pytest.approx(-66.942, abs=2e-3)
    assert expand.outlet_temperature == pytest.approx(233.38, abs=1e-2)


def test_fenske_underwood_gilliland_by_hand():
    # binary, alpha 2.5, xD 0.95, xB 0.05, saturated liquid feed z 0.5 (q = 1)
    # Nmin = ln((0.95/0.05)(0.95/0.05)) / ln 2.5 = ln 361 / 0.916291 = 6.4269
    alphas = {"A": 2.5, "B": 1.0}
    feed, xd, xb = {"A": 0.5, "B": 0.5}, {"A": 0.95, "B": 0.05}, {"A": 0.05, "B": 0.95}
    result = shortcut.fug(alphas, feed, xd, xb, 1.0, "A", "B", reflux=1.65)
    assert result.min_stages == pytest.approx(6.4269, abs=1e-4)
    # Underwood: 1.25 / (2.5 - theta) + 0.5 / (1 - theta) = 0 -> theta = 2.5 / 1.75 = 1.428571
    assert result.theta == pytest.approx(1.428571, abs=1e-6)
    # Rmin + 1 = 2.375 / 1.071429 - 0.05 / 0.428571 = 2.216667 - 0.116667 = 2.1 -> Rmin = 1.1
    # (binary check: Rmin = (xD/z - alpha (1 - xD)/(1 - z)) / (alpha - 1) = 1.65 / 1.5 = 1.1)
    assert result.min_reflux == pytest.approx(1.1, abs=1e-6)
    # Gilliland at R = 1.5 Rmin = 1.65: X = 0.55 / 2.65 = 0.207547
    # Y = 1 - exp((1 + 54.4 X)/(11 + 117.2 X) (X - 1)/sqrt X) = 1 - exp(-0.605213) = 0.454042
    # N = (Nmin + Y) / (1 - Y) = 6.880942 / 0.545958 = 12.603
    assert result.stages == pytest.approx(12.603, abs=2e-3)
    with pytest.raises(ValueError):
        shortcut.gilliland(1.0, 1.1, 6.4)


@pytest.mark.parametrize(
    ("type_", "kind"),
    [
        ("TrayColumn", "column"),
        ("ProcessColumn", "column"),
        ("PlateHeatExchanger", "exchanger"),
        ("AirCooledHeatExchanger", "exchanger"),
        ("CentrifugalPump", "pump"),
        ("PressureVessel", "vessel"),
        ("Furnace", "heater"),
        # a word inside the name, but no item of that row
        ("CoolingTower", None),
        ("WetCoolingTower", None),
        ("CoolingTowerRotor", None),
        ("SprayCooler", None),
        ("ElectronicFrequencyConverter", None),
        ("TurbineFlowMeter", None),
    ],
)
def test_the_sizing_row_of_a_dexpi_class(type_: str, kind: str | None):
    from chemeascode.domains.equipment import coverage
    from chemeascode.domains.equipment.datasheets import draft_datasheet, type_fields
    from chemeascode.domains.equipment.fill import _kind
    from chemeascode.domains.equipment.schemas.equipment import EquipmentItem

    assert _kind(type_) == kind
    assert coverage.class_of(type_) == kind
    assert bool(type_fields(type_)) == (kind is not None)
    item = EquipmentItem.model_validate({"tag": "X-1", "type": type_})
    specific = yaml.safe_load(draft_datasheet(item, [], []))["type_specific"]
    assert set(specific) == {key for key, _ in type_fields(type_)}


# -- the fill on a plant repository ---------------------------------------------------------------

EQUIPMENT = [
    {"tag": "T-1", "type": "Tank", "dimensions": {"diameter": 2.0, "height": 3.0}},
    {"tag": "P-1", "type": "CentrifugalPump", "dimensions": {"length": 1.0, "width": 0.5}},
    {"tag": "V-2", "type": "PressureVessel", "dimensions": {"diameter": 2.0, "height": 3.0}},
    {"tag": "K-1", "type": "CentrifugalCompressor"},
    {"tag": "E-1", "type": "TubularHeatExchanger"},
    {"tag": "C-1", "type": "ProcessColumn"},
]
MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: H2O, name: Water, cas: 7732-18-5, molar_mass: 18.015}
  - {id: AIR, name: Air, cas: 132259-10-0, molar_mass: 28.96}
  - {id: N2, name: Nitrogen, cas: 7727-37-9, molar_mass: 28.0134}
  - {id: O2, name: Oxygen, cas: 7782-44-7, molar_mass: 31.9988}
  - {id: AR, name: Argon, cas: 7440-37-1, molar_mass: 39.948}
"""


def _state(p, t, flow, comp, phase=None):
    state = {
        "pressure": {"value": p, "provenance": "given", "source": "basis"},
        "temperature": {"value": t, "provenance": "given", "source": "basis"},
        "flow": {"value": flow, "provenance": "given", "source": "basis"},
        "composition": {"basis": "mole_fraction", "values": comp, "provenance": "given"},
    }
    if phase:
        state["phase"] = {"value": phase, "provenance": "given"}
    return {"design": state}


def _block(node_id, tag, ins, outs):
    return {
        "id": node_id,
        "links": [{"target": "equipment", "ref": tag}],
        "ports": [{"id": p, "direction": "in"} for p in ins]
        + [{"id": p, "direction": "out"} for p in outs],
    }


FLOWSHEET = {
    "schema": "cheme/process/v1",
    "kind": "flowsheet",
    "title": "Fill test",
    "units": {"pressure": "kPa(a)", "temperature": "K", "flow": "kg/h", "duty": "kW"},
    "cases": [{"id": "design", "default": True}],
    "feeds": [{"id": f"F{i}", "ports": [{"id": "out", "direction": "out"}]} for i in range(1, 5)],
    "products": [{"id": f"D{i}", "ports": [{"id": "in", "direction": "in"}]} for i in range(1, 6)],
    "blocks": [
        _block("TK", "T-1", ["in"], ["out"]),
        _block("PU", "P-1", ["in"], ["out"]),
        _block("VE", "V-2", ["in"], ["out"]),
        _block("KO", "K-1", ["in"], ["out"]),
        _block("CO", "E-1", ["in"], ["out"]),
        _block("CL", "C-1", ["in"], ["top", "bottom"]),
    ],
    "streams": [
        {
            "id": "S0",
            "from": "F1.out",
            "to": "TK.in",
            "state": _state(150, 293.15, 36000, {"H2O": 1}),
        },
        {
            "id": "S1",
            "from": "TK.out",
            "to": "PU.in",
            "state": _state(150, 293.15, 36000, {"H2O": 1}),
        },
        {
            "id": "S2",
            "from": "PU.out",
            "to": "VE.in",
            "state": _state(400, 293.15, 36000, {"H2O": 1}),
        },
        {
            "id": "S3",
            "from": "VE.out",
            "to": "D1.in",
            "state": _state(400, 293.15, 36000, {"H2O": 1}, "liquid"),
        },
        {"id": "S4", "from": "F2.out", "to": "KO.in", "state": _state(100, 300, 3600, {"AIR": 1})},
        {"id": "S5", "from": "KO.out", "to": "D2.in", "state": _state(900, 300, 3600, {"AIR": 1})},
        {"id": "S6", "from": "F3.out", "to": "CO.in", "state": _state(500, 310, 3600, {"N2": 1})},
        {"id": "S7", "from": "CO.out", "to": "D3.in", "state": _state(495, 300, 3600, {"N2": 1})},
        {
            "id": "S8",
            "from": "F4.out",
            "to": "CL.in",
            "state": _state(500, 100, 1000, {"N2": 0.5, "O2": 0.5}),
        },
        {
            "id": "S9",
            "from": "CL.top",
            "to": "D4.in",
            "state": _state(500, 95, 500, {"N2": 0.95, "O2": 0.05}),
        },
        {
            "id": "S10",
            "from": "CL.bottom",
            "to": "D5.in",
            "state": _state(500, 100, 500, {"N2": 0.05, "O2": 0.95}),
        },
    ],
}
LAYOUT = {
    "schema": "cheme/layout-model/v1",
    "equipment": [
        {"tag": "T-1", "position": [0, 0, 0], "nozzles": [{"name": "N1", "point": [0, 0, 2.0]}]},
        {
            "tag": "P-1",
            "position": [3, 0, 0],
            "nozzles": [
                {"name": "N1", "point": [3, 0, 0.5]},
                {"name": "N2", "point": [3.5, 0, 1.0]},
            ],
        },
        {"tag": "V-2", "position": [8, 0, 9], "nozzles": [{"name": "N1", "point": [8, 0, 10]}]},
    ],
    "pipes": [
        {
            "id": "L1",
            "dn": 100,
            "od": 0.1143,
            "class": {"code": "A1", "material": "CS"},
            "points": [[0, 0, 2.0], [0, 0, 0.5], [3, 0, 0.5]],
            "ends": [{"kind": "nozzle", "ref": "T-1/N1"}, {"kind": "nozzle", "ref": "P-1/N1"}],
        },
        {
            "id": "L2",
            "dn": 80,
            "od": 0.0889,
            "class": {"code": "A1", "material": "CS"},
            "points": [[3.5, 0, 1.0], [3.5, 0, 10], [8, 0, 10]],
            "ends": [{"kind": "nozzle", "ref": "P-1/N2"}, {"kind": "nozzle", "ref": "V-2/N1"}],
        },
    ],
    "inline": [
        {"pipe": "L2", "point": [3.5, 0, 5.0], "kind": "valve", "dexpi_class": "GlobeValve"},
        {"pipe": "L1", "point": [1.5, 0, 0.5], "kind": "valve", "dexpi_class": "BallValve"},
    ],
}


def _declare(plant: Path, tag: str, **values) -> None:
    path = plant / "equipment" / "datasheets" / f"{tag}.yaml"
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    for key, value in values.items():
        data["type_specific"][key] = value
    header = "".join(line for line in text.splitlines(keepends=True) if line.startswith("#"))
    path.write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def sized(plant: Path) -> Path:
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": EQUIPMENT}), encoding="utf-8"
    )
    (plant / "process" / "materials.yaml").write_text(MATERIALS, encoding="utf-8")
    (plant / "process" / "flowsheet.yaml").write_text(
        yaml.safe_dump(FLOWSHEET, sort_keys=False), encoding="utf-8"
    )
    (plant / "layout").mkdir(exist_ok=True)
    (plant / "layout" / "plant-model.yaml").write_text(yaml.safe_dump(LAYOUT), encoding="utf-8")
    (plant / "process" / "design-basis.yaml").write_text(
        yaml.safe_dump(
            {
                "residence_times": [
                    {"tag": "V-2", "minutes": 10, "volume_fraction": 0.5, "source": "D-1"}
                ]
            }
        ),
        encoding="utf-8",
    )
    result = draft_missing(plant)
    assert "equipment/datasheets/P-1.yaml" in result.written, result.findings
    return plant


def _specific(plant: Path, tag: str) -> dict:
    data = yaml.safe_load(
        (plant / "equipment" / "datasheets" / f"{tag}.yaml").read_text(encoding="utf-8")
    )
    return data["type_specific"]


def test_pump_with_a_short_line_by_hand(sized: Path):
    _declare(
        sized,
        "P-1",
        density_kg_m3={"value": 1000, "unit": "kg/m3", "source": "water at 20 degC, D-2"},
        viscosity_mpa_s={"value": 1.0, "unit": "mPa s", "source": "D-2", "assumed": True},
        vapour_pressure_kpa={"value": 3.17, "unit": "kPa(a)", "source": "D-2"},
    )
    result = fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert result.written == ["equipment/datasheets/P-1.yaml"], result.findings
    spec = _specific(sized, "P-1")
    # Q = 36000 kg/h / 1000 kg/m3 = 36 m3/h
    assert spec["flow_m3_h"]["value"] == 36.0
    # pressure (400 - 150) kPa / (1000 x 9.80665) = 25.4929 m; static 10 - 2 = 8 m
    # suction DN 100 sch 40, 4.5 m, one 90 deg elbow (K 0.75): 0.12173 m (test_line_loss)
    # discharge DN 80 sch 40: ID 88.9 - 2 x 5.49 = 77.92 mm, v = 2.0971 m/s, Re 1.634e5,
    #   f 0.019617, L 13.5 m, elbow 0.75 + globe valve 6.0: (3.3988 + 6.75) x 0.22423 = 2.27555 m
    # H = 25.4929 + 8 + 0.12173 + 2.27555 = 35.890 m
    head = spec["differential_head_m"]
    assert head["value"] == pytest.approx(35.89, abs=0.01)
    assert head["assumed"] is True  # the schedule and roughness are assumptions
    for text in ("T-1/N1", "V-2/N1", "Moody", "Table 6-4", "schedule 40 ASSUMED", "BallValve"):
        assert text in head["source"], text
    # NPSHa = (150 - 3.17) kPa / (rho g) + (2.0 - 0.5) m - 0.12173 m = 14.9724 + 1.5 - 0.1217
    assert spec["npsh_available_m"]["value"] == pytest.approx(16.351, abs=0.002)
    # P = 10 kg/s x 9.80665 x 35.890 m / 0.7 = 5.028 kW
    power = spec["shaft_power_kw"]
    assert power["value"] == pytest.approx(5.028, abs=0.002)
    assert power["assumed"] is True and "--param pump_efficiency=0.7" in power["source"]
    for entry in spec.values():
        if isinstance(entry, dict) and "value" in entry:
            assert entry.get("source"), entry
    # the equipment estimate reads the filled power with its basis
    sheet = Datasheet.model_validate(
        yaml.safe_load((sized / "equipment" / "datasheets" / "P-1.yaml").read_text())
    )
    size, where = datasheet_size(sheet, "shaft_power")
    assert size == pytest.approx(5.028, abs=0.002)
    assert where.startswith("draft datasheet type_specific.shaft_power_kw (ASSUMED:")
    # the declared parameter is recorded in the sizing basis
    data = yaml.safe_load((sized / "equipment" / "datasheets" / "P-1.yaml").read_text())
    assert any(b["parameter"] == "pump_efficiency" for b in data["sizing_basis"])
    # the header comment stays
    assert (sized / "equipment" / "datasheets" / "P-1.yaml").read_text().startswith("# DRAFT")


def test_without_a_layout_the_head_is_the_pressure_difference_assumed(sized: Path):
    (sized / "layout" / "plant-model.yaml").unlink()
    _declare(sized, "P-1", density_kg_m3=1000, viscosity_mpa_s=1.0, vapour_pressure_kpa=3.17)
    fill_datasheets(sized, ["P-1"])
    spec = _specific(sized, "P-1")
    head = spec["differential_head_m"]
    assert head["value"] == pytest.approx(25.49, abs=0.01) and head["assumed"] is True
    assert "static head and line losses not included" in head["source"]
    assert spec["shaft_power_kw"]["value"] == "TBD"
    assert "pump_efficiency" in spec["shaft_power_kw"]["source"]


def test_pump_stream_pressures_at_the_pump_nozzles(sized: Path):
    # a flowsheet carrying the pump's own suction and discharge pressures on its streams: the
    # static head and line losses are in them already and are not added a second time
    _declare(
        sized,
        "P-1",
        density_kg_m3={"value": 1000, "source": "D-2"},
        vapour_pressure_kpa={"value": 3.17, "source": "D-2"},
        stream_pressures_at={"value": "pump", "source": "flowsheet convention, D-7"},
    )
    fill_datasheets(sized, ["P-1"])
    spec = _specific(sized, "P-1")
    head = spec["differential_head_m"]
    # H = (400 - 150) kPa / (1000 x 9.80665) = 25.4929 m; nothing assumed
    assert head["value"] == pytest.approx(25.49, abs=0.01)
    assert "assumed" not in head
    assert "stream_pressures_at pump" in head["source"]
    # NPSHa = (150 - 3.17) / 9.80665 = 14.972 m at the suction nozzle
    npsh = spec["npsh_available_m"]
    assert npsh["value"] == pytest.approx(14.97, abs=0.01) and "assumed" not in npsh


def test_compressor_ideal_gas_with_declared_parameters(sized: Path):
    _declare(sized, "K-1", heat_capacity_ratio={"value": 1.4, "source": "air, D-3"})
    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    fill_datasheets(sized, ["K-1"], parameters=params)
    spec = _specific(sized, "K-1")
    # two stages of ratio 3, each 138.947 kJ/kg at 1 kg/s, intercooled to 300 K (by hand above)
    assert spec["number_of_stages"]["value"] == 2
    assert spec["fluid_power_kw"]["value"] == pytest.approx(277.89, abs=0.01)
    assert spec["intercooler_duties_kw"]["value"] == [pytest.approx(138.9, abs=0.1)]
    assert spec["discharge_temperature_k"]["value"] == pytest.approx(438.3, abs=0.1)
    assert "ideal gas" in spec["fluid_power_kw"]["source"]
    assert spec["fluid_power_kw"]["assumed"] is True
    assert spec["shaft_power_kw"]["value"] == "TBD"  # no mechanical efficiency declared
    assert (
        "no intercooler or aftercooler pressure drop (ASSUMED" in spec["fluid_power_kw"]["source"]
    )
    # a declared intercooler temperature keeps the pressure-drop assumption in the basis
    _declare(sized, "K-1", intercooler_outlet_temperature_degc={"value": 26.85, "source": "D-3"})
    fill_datasheets(sized, ["K-1"], parameters=params)
    spec = _specific(sized, "K-1")
    assert spec["fluid_power_kw"]["value"] == pytest.approx(277.89, abs=0.01)
    for key in ("fluid_power_kw", "intercooler_duties_kw"):
        source = spec[key]["source"]
        assert "intercooled to 26.85 (D-3) degC" in source
        assert "no intercooler or aftercooler pressure drop (ASSUMED" in source


def test_never_overwrites_a_given_value_and_refills_its_own(sized: Path):
    _declare(
        sized,
        "K-1",
        heat_capacity_ratio=1.4,
        fluid_power_kw={"value": 300.0, "unit": "kW", "source": "vendor quote Q-7"},
    )
    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    fill_datasheets(sized, ["K-1"], parameters=params)
    spec = _specific(sized, "K-1")
    assert spec["fluid_power_kw"] == {"value": 300.0, "unit": "kW", "source": "vendor quote Q-7"}
    assert spec["number_of_stages"]["source"].startswith(FILL_MARK)
    assert spec["number_of_stages"]["value"] > 1 and "intercooler_duties_kw" in spec
    # a second run with another assumption rewrites what the fill wrote; one stage has no
    # intercoolers: the earlier duties go (left, they would be stale after the refill)
    fill_datasheets(sized, ["K-1"], parameters={**params, "max_stage_pressure_ratio": "10"})
    spec = _specific(sized, "K-1")
    assert spec["number_of_stages"]["value"] == 1 and "intercooler_duties_kw" not in spec
    assert not _stale(sized)
    # the same inputs again: nothing changes
    again = fill_datasheets(sized, ["K-1"], parameters={**params, "max_stage_pressure_ratio": "10"})
    assert again.unchanged == ["equipment/datasheets/K-1.yaml"] and not again.written


def _stale(plant: Path) -> list:
    return [f for f in stale_findings(Workspace(plant)) if f.rule == "cheme.datasheet-stale"]


def _set_stream(plant: Path, stream_id: str, field: str, value: float) -> None:
    path = plant / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    stream = next(s for s in data["streams"] if s["id"] == stream_id)
    stream["state"]["design"][field]["value"] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_filled_values_carry_the_stream_fingerprint_and_go_stale(sized: Path):
    _declare(
        sized,
        "K-1",
        heat_capacity_ratio={"value": 1.4, "source": "air, D-3"},
        fluid_power_kw={"value": 300.0, "unit": "kW", "source": "vendor quote Q-7"},
    )
    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    fill_datasheets(sized, ["K-1"], parameters=params)
    spec = _specific(sized, "K-1")
    fingerprint = spec["number_of_stages"]["fingerprint"]
    assert len(fingerprint) == 16
    # the stages read the maximum stage ratio; the outlet temperature the
    # efficiency too
    assert spec["number_of_stages"]["inputs"] == ["param:max_stage_pressure_ratio"]
    assert "param:isentropic_efficiency" in spec["discharge_temperature_k"]["inputs"]
    assert "fingerprint" not in spec["fluid_power_kw"]  # the vendor's value is untouched
    assert spec["number_of_stages"]["origin"] == "correlation"
    assert "origin" not in spec["fluid_power_kw"]
    assert "fingerprint" not in spec["heat_capacity_ratio"]
    assert Datasheet.model_validate(
        yaml.safe_load((sized / "equipment" / "datasheets" / "K-1.yaml").read_text())
    )
    assert not _stale(sized)
    # a changed discharge pressure: the values filled from it are stale
    _set_stream(sized, "S5", "pressure", 1000)
    found = _stale(sized)
    assert [f.ids for f in found] == [["K-1"]] and found[0].level == "warning"
    assert "type_specific.number_of_stages" in found[0].message
    assert "fluid_power_kw" not in found[0].message
    assert found[0].line is not None
    # validate reports it too
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(sized))
    assert any(f.rule == "cheme.datasheet-stale" for f in report.findings)
    # a refill rewrites what the fill owns, with the new fingerprint, and keeps the vendor's
    fill_datasheets(sized, ["K-1"], parameters=params)
    spec = _specific(sized, "K-1")
    assert spec["number_of_stages"]["fingerprint"] != fingerprint
    assert spec["fluid_power_kw"] == {"value": 300.0, "unit": "kW", "source": "vendor quote Q-7"}
    assert not _stale(sized)


def test_values_without_a_fingerprint_are_never_stale(sized: Path):
    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    _declare(sized, "K-1", heat_capacity_ratio=1.4)
    fill_datasheets(sized, ["K-1"], parameters=params)
    # a datasheet filled before fingerprints: the same values without them
    path = sized / "equipment" / "datasheets" / "K-1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for entry in data["type_specific"].values():
        if isinstance(entry, dict):
            entry.pop("fingerprint", None)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    _set_stream(sized, "S5", "pressure", 1000)
    assert not _stale(sized)
    # a fingerprint on a value the fill did not write is not compared either
    data["type_specific"]["fluid_power_kw"] = {
        "value": 300.0,
        "unit": "kW",
        "source": "vendor quote Q-7",
        "fingerprint": "0000000000000000",
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert not _stale(sized)


def _stale_keys(plant: Path, tag: str) -> str:
    return " ".join(f.message for f in _stale(plant) if f.ids == [tag])


def test_rerouting_a_pumps_line_makes_its_head_and_npsh_stale(sized: Path):
    # the head and NPSH read the routed pipes and the nozzle elevations of
    # the layout model, not the streams alone
    _declare(
        sized,
        "P-1",
        density_kg_m3={"value": 1000, "source": "D-2"},
        viscosity_mpa_s={"value": 1.0, "source": "D-2"},
        vapour_pressure_kpa={"value": 3.17, "source": "D-2"},
    )
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    spec = _specific(sized, "P-1")

    def layout(refs: list[str]) -> list[str]:
        return [r for r in refs if r.split(":")[0] in ("pipe", "nozzle")]

    assert layout(spec["differential_head_m"]["inputs"]) == [
        "pipe:L1",
        "nozzle:P-1/N1",
        "nozzle:T-1/N1",
        "pipe:L2",
        "nozzle:P-1/N2",
        "nozzle:V-2/N1",
    ]
    assert layout(spec["npsh_available_m"]["inputs"]) == [
        "pipe:L1",
        "nozzle:P-1/N1",
        "nozzle:T-1/N1",
    ]
    assert spec["flow_m3_h"]["inputs"] == ["param:density_kg_m3"]  # and the streams
    assert Datasheet.model_validate(
        yaml.safe_load((sized / "equipment" / "datasheets" / "P-1.yaml").read_text())
    )
    assert not _stale(sized)
    # the suction line takes a longer route: 3 m more down and back
    model = copy.deepcopy(LAYOUT)
    model["pipes"][0]["points"] = [[0, 0, 2.0], [0, 0, -1.0], [3, 0, -1.0], [3, 0, 0.5]]
    (sized / "layout" / "plant-model.yaml").write_text(yaml.safe_dump(model), encoding="utf-8")
    message = _stale_keys(sized, "P-1")
    for key in ("differential_head_m", "npsh_available_m", "shaft_power_kw"):
        assert f"type_specific.{key}" in message, key
    assert "flow_m3_h" not in message
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert not _stale(sized)
    # the source vessel's nozzle raised by 1 m: the static head and NPSH change too
    model["equipment"][0]["nozzles"][0]["point"] = [0, 0, 3.0]
    (sized / "layout" / "plant-model.yaml").write_text(yaml.safe_dump(model), encoding="utf-8")
    assert "type_specific.npsh_available_m" in _stale_keys(sized, "P-1")
    # a layout model that does not parse: not compared (validate reports the file)
    (sized / "layout" / "plant-model.yaml").write_text("pipes: [\n", encoding="utf-8")
    assert not _stale(sized)


def _fill_pump(plant: Path) -> None:
    _declare(
        plant,
        "P-1",
        density_kg_m3={"value": 1000, "source": "D-2"},
        viscosity_mpa_s={"value": 1.0, "source": "D-2"},
        vapour_pressure_kpa={"value": 3.17, "source": "D-2"},
    )
    fill_datasheets(plant, ["P-1"], parameters={"pump_efficiency": "0.7"})


def _only_stale(plant: Path, tag: str, keys: set[str], of: tuple[str, ...]) -> None:
    message = _stale_keys(plant, tag)
    assert set(re.findall(r"type_specific\.(\w+)", message)) & set(of) == keys, message


PUMP_KEYS = ("flow_m3_h", "differential_head_m", "npsh_available_m", "shaft_power_kw")


def test_a_changed_parameter_makes_the_values_that_read_it_stale(sized: Path):
    # a filled value's fingerprint covers the declared parameters it read
    _fill_pump(sized)
    spec = _specific(sized, "P-1")
    head = spec["differential_head_m"]["inputs"]
    for ref in (
        "param:viscosity_mpa_s",
        "param:pipe_schedule",
        "param:pipe_roughness",
        "table:pipe-sizes/40/DN100",
        "table:pipe-sizes/40/DN80",
        "table:roughness/commercial_steel",
        "table:fittings/elbow_90",
        "table:fittings/GlobeValve",
    ):
        assert ref in head, ref
    assert "param:vapour_pressure_kpa" not in head and "param:pump_efficiency" not in head
    assert "param:pump_efficiency" in spec["shaft_power_kw"]["inputs"]
    assert "param:vapour_pressure_kpa" in spec["npsh_available_m"]["inputs"]
    # the --param value is read back from the sizing basis: current
    assert not _stale(sized)
    # a parameter the pump does not read: nothing stale
    _declare(sized, "P-1", tray_efficiency={"value": 0.7, "source": "D-9"})
    assert not _stale(sized)
    # the vapour pressure: the NPSH only
    _declare(sized, "P-1", vapour_pressure_kpa={"value": 5.0, "source": "D-2"})
    _only_stale(sized, "P-1", {"npsh_available_m"}, PUMP_KEYS)
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert not _stale(sized)
    # a parameter that was not declared (schedule 40 assumed) is declared: the line losses
    _declare(sized, "P-1", pipe_schedule={"value": "10S", "source": "D-5"})
    _only_stale(
        sized, "P-1", {"differential_head_m", "npsh_available_m", "shaft_power_kw"}, PUMP_KEYS
    )
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert not _stale(sized)
    # a --dimensions run keeps the --param values recorded behind the sizes
    fill_datasheets(sized, ["P-1"], dimensions=True)
    assert not _stale(sized)
    # the efficiency the fill took from --param, now declared on the sheet: the power only
    _declare(sized, "P-1", pump_efficiency={"value": 0.75, "source": "vendor curve"})
    _only_stale(sized, "P-1", {"shaft_power_kw"}, PUMP_KEYS)


def _patched_table(monkeypatch, module, loader: str, change) -> None:
    data = copy.deepcopy(getattr(module, loader)())
    change(data)
    monkeypatch.setattr(module, loader, lambda: data)


def test_a_changed_table_row_makes_the_values_that_used_it_stale(sized: Path, monkeypatch):
    # and the rows of the shipped tables it used (pipe sizes, roughness,
    # fitting K)
    _fill_pump(sized)
    assert not _stale(sized)
    with monkeypatch.context() as patch:  # rows the lines do not use
        _patched_table(
            patch,
            hydraulics,
            "_data",
            lambda d: (
                d["fittings"]["rows"]["AngleValve"].update(k=2.5),
                d["roughness"]["rows"]["cast_iron"].update(mm=0.3),
                d["walls"]["schedules"]["40"].update({150: 8.0}),
            ),
        )
        assert not _stale(sized)
    with monkeypatch.context() as patch:  # the elbow: on both lines
        _patched_table(
            patch, hydraulics, "_data", lambda d: d["fittings"]["rows"]["elbow_90"].update(k=0.8)
        )
        _only_stale(
            sized, "P-1", {"differential_head_m", "npsh_available_m", "shaft_power_kw"}, PUMP_KEYS
        )
    with monkeypatch.context() as patch:  # the globe valve and DN 80: the discharge line only
        _patched_table(
            patch, hydraulics, "_data", lambda d: d["fittings"]["rows"]["GlobeValve"].update(k=9)
        )
        _only_stale(sized, "P-1", {"differential_head_m", "shaft_power_kw"}, PUMP_KEYS)
    with monkeypatch.context() as patch:
        _patched_table(
            patch, hydraulics, "_data", lambda d: d["walls"]["schedules"]["40"].update({80: 5.5})
        )
        _only_stale(sized, "P-1", {"differential_head_m", "shaft_power_kw"}, PUMP_KEYS)
    # a table note (the check of a row) is not what the value used
    with monkeypatch.context() as patch:
        _patched_table(
            patch,
            hydraulics,
            "_data",
            lambda d: d["fittings"]["rows"]["elbow_90"].update(check="rechecked"),
        )
        assert not _stale(sized)
    assert not _stale(sized)


def test_a_changed_typical_u_row_makes_the_exchanger_area_stale(sized: Path, monkeypatch):
    # the typical overall coefficient the area used (no adapter: the duty is
    # given)
    _declare(
        sized,
        "E-1",
        arrangement="counter-current",
        u_service="cooler/gases-water",
        duty_kw={"value": 10.4, "unit": "kW", "source": "D-4"},
        utility_inlet_temperature_degc={"value": 6.85, "source": "CW supply, D-4"},
        utility_outlet_temperature_degc={"value": 11.85, "source": "CW return, D-4"},
    )
    fill_datasheets(sized, ["E-1"])
    spec = _specific(sized, "E-1")
    assert spec["overall_u_w_m2k"]["value"] == 160
    row = "table:overall-coefficients/cooler/gases-water"
    assert row in spec["overall_u_w_m2k"]["inputs"] and row in spec["area_m2"]["inputs"]
    assert "param:u_service" in spec["area_m2"]["inputs"]
    assert "param:u_service" not in spec["lmtd_k"]["inputs"]
    assert not _stale(sized)
    keys = ("lmtd_k", "overall_u_w_m2k", "area_m2")
    with monkeypatch.context() as patch:  # another row
        _patched_table(
            patch,
            sizing,
            "_u_table",
            lambda d: d["rows"]["cooler/water-brine"].update(range=[1, 2]),
        )
        assert not _stale(sized)
    with monkeypatch.context() as patch:
        _patched_table(
            patch,
            sizing,
            "_u_table",
            lambda d: d["rows"]["cooler/gases-water"].update(range=[20, 200]),
        )
        _only_stale(sized, "E-1", {"overall_u_w_m2k", "area_m2"}, keys)
    # another service row declared: the U and the area, not the LMTD
    _declare(sized, "E-1", u_service="cooler/gases-brine")
    _only_stale(sized, "E-1", {"overall_u_w_m2k", "area_m2"}, keys)
    # a margin declared: the area only
    fill_datasheets(sized, ["E-1"])
    _declare(sized, "E-1", area_margin={"value": 0.1, "source": "D-4"})
    _only_stale(sized, "E-1", {"area_m2"}, keys)


def test_values_filled_before_the_parameters_were_covered_stay_current(sized: Path):
    # a sheet filled before (its inputs name the routed lines only) is
    # compared on what it names: no stale wave without a cause; a refill names the parameters and
    # tables
    from chemeascode.domains.process.model import load

    _fill_pump(sized)
    path = sized / "equipment" / "datasheets" / "P-1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    process, _ = load(sized)
    streams = stream_fingerprint(process, "P-1", "design")
    model = yaml.safe_load((sized / "layout" / "plant-model.yaml").read_text(encoding="utf-8"))
    for entry in data["type_specific"].values():
        if not (isinstance(entry, dict) and entry.get("fingerprint")):
            continue
        # what an earlier fill wrote
        old = [r for r in entry.get("inputs", []) if r.split(":")[0] in ("pipe", "nozzle")]
        if old:
            named = {r: input_data(r, data, process, model, {}) for r in old}
            entry["inputs"], entry["fingerprint"] = old, inputs_fingerprint(streams, named)
        else:
            entry.pop("inputs", None)
            entry["fingerprint"] = streams
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert not _stale(sized)
    # a parameter they do not name: not compared
    _declare(sized, "P-1", vapour_pressure_kpa={"value": 5.0, "source": "D-2"})
    assert not _stale(sized)
    # what they name: as before
    _set_stream(sized, "S1", "pressure", 160)
    _only_stale(sized, "P-1", set(PUMP_KEYS), PUMP_KEYS)
    fill_datasheets(sized, ["P-1"], parameters={"pump_efficiency": "0.7"})
    assert not _stale(sized)
    assert "param:vapour_pressure_kpa" in _specific(sized, "P-1")["npsh_available_m"]["inputs"]


def test_a_volume_from_the_dimensions_follows_them_not_the_streams(sized: Path):
    # the vessel's volume comes from its dimensions alone: a stream change
    # does not make it stale (the residence time, from the outlet flow, is); a dimension change does
    _declare(sized, "V-2", density_kg_m3={"value": 1000, "source": "D-2"})
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    volume = spec["volume_m3"]
    # every field the volume may be read from: one added later that takes priority counts too
    assert "datasheet:dimensions.outside_diameter" in volume["inputs"]
    assert "datasheet:dimensions.tangent_length" in volume["inputs"]
    assert "datasheet:type_specific.diameter_m" in volume["inputs"]
    assert (
        "over the overall height, heads and skirt not separated: an upper bound"
        in (volume["source"])
    )
    assert "origin" not in volume
    assert spec["residence_time_min"]["inputs"] == [
        "residence_time:V-2",
        "datasheet:type_specific.volume_m3",
        "param:density_kg_m3",
    ]
    assert not _stale(sized)
    _set_stream(sized, "S3", "flow", 72000)
    message = _stale_keys(sized, "V-2")
    assert "type_specific.residence_time_min" in message
    assert "volume_m3" not in message
    _set_stream(sized, "S3", "flow", 36000)
    assert not _stale(sized)
    # a hand-edited dimension: the volume is stale (the residence time follows the volume)
    _edit(
        sized, "V-2", lambda d: d["dimensions"].update(overall_height={"value": 4.0, "unit": "m"})
    )
    message = _stale_keys(sized, "V-2")
    assert "type_specific.volume_m3" in message
    fill_datasheets(sized, ["V-2"])
    assert _specific(sized, "V-2")["volume_m3"]["value"] == pytest.approx(12.57, abs=1e-2)
    assert not _stale(sized)
    # a tangent length given later (it takes priority over the overall height): stale
    _edit(
        sized, "V-2", lambda d: d["dimensions"].update(tangent_length={"value": 2.5, "unit": "m"})
    )
    assert "type_specific.volume_m3" in _stale_keys(sized, "V-2")
    fill_datasheets(sized, ["V-2"])
    assert not _stale(sized)
    # the design basis asks for another volume fraction: the residence time is stale
    path = sized / "process" / "design-basis.yaml"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("0.5", "0.8"), encoding="utf-8")
    assert "type_specific.residence_time_min" in _stale_keys(sized, "V-2")
    # a design basis that does not load: not compared (validate reports the file)
    path.write_text("residence_times: [{tag: V-2}]\n", encoding="utf-8")
    assert not _stale(sized)


def _references(plant: Path) -> list:
    from chemeascode.domains.equipment.datasheets import reference_findings

    return reference_findings(Workspace(plant))


def test_fill_names_the_case_and_streams_and_validate_resolves_them(sized: Path):
    from chemeascode.project.validate import validate_workspace

    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    _declare(sized, "K-1", heat_capacity_ratio=1.4)
    fill_datasheets(sized, ["K-1"], parameters=params)
    path = sized / "equipment" / "datasheets" / "K-1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # the case filled from and the streams at the linked node KO, first in operating
    assert list(data["operating"])[:2] == ["case", "streams"]
    assert data["operating"]["case"] == "design"
    assert data["operating"]["streams"] == ["S4", "S5"]
    assert "inlet_pressure" in data["operating"]  # the draft's conditions stay
    sheet = Datasheet.model_validate(data)
    assert sheet.operating.case == "design" and "inlet_pressure" in sheet.operating
    assert not _references(sized)
    # a refill: the same references, not added twice
    again = fill_datasheets(sized, ["K-1"], parameters=params)
    assert again.unchanged == ["equipment/datasheets/K-1.yaml"]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["operating"]["streams"] == ["S4", "S5"]
    assert list(data["operating"]).count("case") == 1
    # an unknown case and an unknown stream are reported, with their lines
    data["operating"]["case"] = "winter"
    data["operating"]["streams"] = ["S4", "S99"]
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    found = _references(sized)
    assert [f.rule for f in found] == ["cheme.contract-ref"] * 2
    assert all(f.level == "warning" and f.ids == ["K-1"] and f.line for f in found)
    assert "'winter' is no case" in found[0].message and "design" in found[0].hint
    assert "'S99' is no stream" in found[1].message
    report = validate_workspace(Workspace(sized))
    assert len([f for f in report.findings if f.rule == "cheme.contract-ref"]) == 2
    # a refill writes the case and streams it read again
    fill_datasheets(sized, ["K-1"], parameters=params)
    assert not _references(sized)
    # without a flowsheet nothing is checked
    data["operating"]["case"] = "winter"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert _references(sized)
    (sized / "process" / "flowsheet.yaml").unlink()
    assert not _references(sized)


def test_a_sheet_that_names_a_case_is_filled_from_it(sized: Path):
    from chemeascode.domains.process.model import load

    flowsheet = sized / "process" / "flowsheet.yaml"
    fs = yaml.safe_load(flowsheet.read_text(encoding="utf-8"))
    fs["cases"].append({"id": "winter"})
    for stream in fs["streams"]:
        if "design" in (stream.get("state") or {}):
            stream["state"]["winter"] = copy.deepcopy(stream["state"]["design"])
    flowsheet.write_text(yaml.safe_dump(fs, sort_keys=False), encoding="utf-8")
    _set_stream(sized, "S4", "pressure", 120)  # design only: the cases now differ
    params = {"isentropic_efficiency": "0.8", "max_stage_pressure_ratio": "3.5"}
    _declare(sized, "K-1", heat_capacity_ratio=1.4)
    path = sized / "equipment" / "datasheets" / "K-1.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.setdefault("operating", {})["case"] = "winter"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    fill_datasheets(sized, ["K-1"], parameters=params)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["operating"]["case"] == "winter"
    process, _ = load(sized)
    winter = stream_fingerprint(process, "K-1", "winter")
    assert winter != stream_fingerprint(process, "K-1", "design")
    marked = [e for e in data["type_specific"].values() if isinstance(e, dict)]
    found = {e["fingerprint"] for e in marked if e.get("fingerprint")}
    # each over the winter streams (and the parameters it read)
    expected = {
        inputs_fingerprint(winter, {r: input_data(r, data, process, None, {}) for r in e["inputs"]})
        if e.get("inputs")
        else winter
        for e in marked
        if e.get("fingerprint")
    }
    assert found == expected
    # --case wins over the sheet's case
    fill_datasheets(sized, ["K-1"], parameters=params, case="design")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["operating"]["case"] == "design"


def test_a_fill_from_no_stream_names_no_case(sized: Path):
    # without declared parameters only some sheets get values calculated from the streams
    # (E-1, C-1); a sheet whose fill wrote none (P-1, K-1: parameters missing) names no case.
    # A vessel's volume from its dimensions has a fingerprint, but not over the streams.
    fill_datasheets(sized)
    for path in (sized / "equipment" / "datasheets").glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        spec = data.get("type_specific") or {}
        calculated = any(
            isinstance(e, dict) and e.get("origin") == "correlation" for e in spec.values()
        )
        assert ("case" in (data.get("operating") or {})) == calculated, path.name


def test_design_basis_terminals_against_the_flowsheet(sized: Path):
    from chemeascode.project.validate import validate_workspace

    path = sized / "process" / "design-basis.yaml"
    basis = yaml.safe_load(path.read_text(encoding="utf-8"))
    basis["feeds"] = [{"name": "Water", "terminal": "F1"}, {"name": "Air", "terminal": "D2"}]
    basis["products"] = [{"name": "Water", "terminal": "D1"}, {"name": "Gas", "terminal": "X9"}]
    basis["utilities"] = [{"name": "Cooling water", "terminal": "nothing to resolve"}]
    path.write_text(yaml.safe_dump(basis, sort_keys=False), encoding="utf-8")
    found = [
        f for f in validate_workspace(Workspace(sized)).findings if f.rule == "cheme.contract-ref"
    ]
    assert [(f.file, f.ids) for f in found] == [
        ("process/design-basis.yaml", ["D2"]),
        ("process/design-basis.yaml", ["X9"]),
    ]
    assert found[0].message.startswith("feeds[1] (Air): terminal 'D2' is no feed")
    assert "D2 is a flowsheet product" in found[0].hint
    assert found[1].message.startswith("products[1] (Gas): terminal 'X9' is no product")
    assert all(f.level == "warning" and f.line for f in found)
    # known terminals are clean; without a flowsheet nothing is checked
    basis["feeds"], basis["products"] = basis["feeds"][:1], basis["products"][:1]
    path.write_text(yaml.safe_dump(basis, sort_keys=False), encoding="utf-8")
    report = validate_workspace(Workspace(sized))
    assert not [f for f in report.findings if f.rule == "cheme.contract-ref"]
    basis["products"].append({"terminal": "X9"})
    path.write_text(yaml.safe_dump(basis, sort_keys=False), encoding="utf-8")
    (sized / "process" / "flowsheet.yaml").unlink()
    report = validate_workspace(Workspace(sized))
    assert not [f for f in report.findings if f.rule == "cheme.contract-ref"]


def test_vessel_residence_time_against_the_design_basis(sized: Path):
    _declare(sized, "V-2", density_kg_m3={"value": 1000, "source": "D-2"})
    result = fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    # V = pi/4 x 2^2 x 3 = 9.425 m3 (the draft's); held 0.5 x 9.425 = 4.712 m3; Q = 36 m3/h
    # t = 4.712 / 36 x 60 = 7.854 min < 10 min required
    assert spec["residence_time_min"]["value"] == pytest.approx(7.854, abs=1e-3)
    rules = [f.rule for f in result.findings]
    assert "cheme.datasheet-residence-time" in rules


def test_fill_marks_its_scope_and_leaves_unsupported_aspects_open(sized: Path):
    from chemeascode.domains.equipment import coverage
    from chemeascode.domains.equipment.datasheets import TYPE_FIELDS

    _declare(
        sized,
        "V-2",
        density_kg_m3={"value": 1000, "source": "D-2"},
        corrosion_allowance_mm={"value": 3.0, "unit": "mm", "source": "D-9 materials review"},
        relief_protection={"value": "supplier", "reason": "relief study RS-1 pending"},
    )
    result = fill_datasheets(sized, ["V-2"])
    path = sized / "equipment" / "datasheets" / "V-2.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    spec = data["type_specific"]
    # unsupported aspects stay TBD with the reason; a given value and a marker are kept
    for key in ("mechanical_design", "rating"):
        assert spec[key]["value"] == "TBD", key
        assert "unsupported in cheme-as-code" in spec[key]["source"], key
        assert key in result.tbd["equipment/datasheets/V-2.yaml"]
    assert spec["corrosion_allowance_mm"]["value"] == 3.0
    assert spec["relief_protection"]["value"] == "supplier"
    # the sheet says its filled values are preliminary
    scope = [b for b in data["sizing_basis"] if b["parameter"] == coverage.SCOPE_PARAMETER]
    assert len(scope) == 1 and scope[0]["value"] == "preliminary"
    assert scope[0]["reference"].startswith(FILL_MARK)
    assert "mechanical code" in scope[0]["reference"]
    assert coverage.status_of(spec["residence_time_min"]) == "preliminary"
    assert coverage.status_of(spec["mechanical_design"]) is None
    assert coverage.status_of(spec["corrosion_allowance_mm"]) is None
    # a refill changes nothing
    text = path.read_text(encoding="utf-8")
    again = fill_datasheets(sized, ["V-2"])
    assert path.read_text(encoding="utf-8") == text
    assert again.unchanged == ["equipment/datasheets/V-2.yaml"]
    # every sized class has a row, every aspect a status
    assert {words[0] for words, _ in TYPE_FIELDS} == set(coverage.SIZING_COVERAGE)
    for row in coverage.coverage_table().values():
        assert set(row) == set(coverage.ASPECTS)
        assert row["mechanical_code"]["status"] == "unsupported"
        assert row["relief"]["status"] == "unsupported"


def test_sizing_doc_matches_the_coverage_table():
    from chemeascode.domains.equipment import coverage

    doc = (Path(__file__).parents[1] / "docs" / "framework" / "sizing.md").read_text("utf-8")
    rows = {
        cells[1].strip(): [c.strip() for c in cells[2:-1]]
        for line in doc.splitlines()
        if line.startswith("| ") and len(cells := line.split("|")) == len(coverage.ASPECTS) + 3
    }
    for cls, row in coverage.coverage_table().items():
        assert rows.get(cls) == [row[a]["status"] for a in coverage.ASPECTS], cls


def _list_dimensions(plant: Path, tag: str, dimensions: dict | None) -> None:
    path = plant / "equipment" / "equipment-list.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    item = next(i for i in data["equipment"] if i["tag"] == tag)
    item.pop("dimensions", None)
    if dimensions is not None:
        item["dimensions"] = dimensions
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _edit(plant: Path, tag: str, change) -> None:
    path = plant / "equipment" / "datasheets" / f"{tag}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_a_filled_volume_follows_changed_dimensions(sized: Path):
    # the draft's volume (from the list's D 2 m x H 3 m) and a fill's own
    # follow the sheet's typed dimensions; a volume written by hand is kept
    _declare(sized, "V-2", density_kg_m3={"value": 1000, "source": "D-2"})
    assert DRAFT_VOLUME in _specific(sized, "V-2")["volume_m3"]["source"]
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    # V = pi/4 x 2^2 x 3 = 9.425 m3 over the overall height: an upper bound
    assert spec["volume_m3"]["value"] == pytest.approx(9.425, abs=1e-3)
    assert spec["volume_m3"]["source"].startswith(FILL_MARK)
    assert "dimensions.outside_diameter" in spec["volume_m3"]["source"]
    assert "dimensions.overall_height" in spec["volume_m3"]["source"]

    # the sheet's overall height doubles: V = pi/4 x 2^2 x 6 = 18.85 m3,
    # t = 0.5 x 18.85 / 36 x 60 = 15.708 min
    def taller(data):
        data["dimensions"]["overall_height"] = {"value": 6.0, "unit": "m", "source": "D-5"}

    _edit(sized, "V-2", taller)
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    assert spec["volume_m3"]["value"] == pytest.approx(18.85, abs=1e-2)
    assert spec["residence_time_min"]["value"] == pytest.approx(15.708, abs=5e-3)

    # the inside diameter and the tangent length given by hand win over the overall sizes:
    # V = pi/4 x 1.9^2 x 5 = 14.176 m3, t = 0.5 x 14.176 / 36 x 60 = 11.81 min
    def shell(data):
        data["dimensions"]["inside_diameter"] = {"value": 1900, "unit": "mm", "source": "V-9"}
        data["dimensions"]["tangent_length"] = {"value": 5.0, "unit": "m", "source": "V-9"}

    _edit(sized, "V-2", shell)
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    assert spec["volume_m3"]["value"] == pytest.approx(14.18, abs=1e-2)
    assert "dimensions.inside_diameter" in spec["volume_m3"]["source"]
    assert "heads not included" in spec["volume_m3"]["source"]
    assert spec["residence_time_min"]["value"] == pytest.approx(11.81, abs=1e-2)
    # a volume written by hand is never rewritten; the residence time uses it
    _declare(sized, "V-2", volume_m3={"value": 20.0, "unit": "m3", "source": "vendor V-9"})
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    assert spec["volume_m3"] == {"value": 20.0, "unit": "m3", "source": "vendor V-9"}
    assert spec["residence_time_min"]["value"] == pytest.approx(16.67, abs=1e-2)


def test_a_filled_volume_from_the_legacy_type_specific_dimensions(sized: Path):
    # an item the list gives no dimensions: the older type_specific diameter_m and height_m
    _list_dimensions(sized, "V-2", None)
    _edit(sized, "V-2", lambda data: data.pop("dimensions", None))
    _declare(
        sized,
        "V-2",
        density_kg_m3={"value": 1000, "source": "D-2"},
        volume_m3={"value": "TBD", "unit": "m3"},
        diameter_m={"value": 2.0, "unit": "m", "source": "D-4"},
        height_m={"value": 3.0, "unit": "m", "source": "D-4"},
    )
    fill_datasheets(sized, ["V-2"])
    assert _specific(sized, "V-2")["volume_m3"]["value"] == pytest.approx(9.425, abs=1e-3)
    _declare(sized, "V-2", height_m={"value": 6.0, "unit": "m", "source": "D-5"})
    fill_datasheets(sized, ["V-2"])
    spec = _specific(sized, "V-2")
    assert spec["volume_m3"]["value"] == pytest.approx(18.85, abs=1e-2)
    assert spec["residence_time_min"]["value"] == pytest.approx(15.708, abs=5e-3)
    # no dimensions any more: the filled volume goes back to TBD, not stale
    _edit(sized, "V-2", lambda data: data["type_specific"].pop("height_m"))
    fill_datasheets(sized, ["V-2"])
    assert _specific(sized, "V-2")["volume_m3"]["value"] == "TBD"


def test_a_1_2_correction_factor_below_0_75_is_a_finding(sized: Path):
    # hot N2 310 -> 300 K, cold 280 -> 302 K: R = 10/22 = 0.4545, P = 22/30 = 0.7333,
    # S = sqrt(R^2 + 1) = 1.098458, a = (2 - P (R + 1 - S)) / (2 - P (R + 1 + S))
    # = 1.738869 / 0.127797 = 13.6065, b = (1 - P) / (1 - P R) = 0.4,
    # F = S ln b / ((R - 1) ln a) = -1.006508 / -1.423936 = 0.7068 < 0.75
    _declare(
        sized,
        "E-1",
        arrangement="1-2",
        overall_u_w_m2k={"value": 100, "source": "D-6"},
        utility_inlet_temperature_degc={"value": 6.85, "source": "D-6"},
        utility_outlet_temperature_degc={"value": 28.85, "source": "D-6"},
    )
    result = fill_datasheets(sized, ["E-1"])
    spec = _specific(sized, "E-1")
    assert spec["lmtd_correction_f"]["value"] == pytest.approx(0.7068, abs=1e-4)
    assert "0.75" in spec["lmtd_correction_f"]["source"]
    assert "cheme.datasheet-fill-correction-factor" in [f.rule for f in result.findings]
    assert sizing.correction_factor(310, 300, 280, 296, "1-2") > sizing.F_MIN


def test_unlinked_and_non_draft_sheets(sized: Path):
    path = sized / "equipment" / "datasheets" / "T-1.yaml"
    text = path.read_text(encoding="utf-8").replace("draft: true\n", "")
    path.write_text(text, encoding="utf-8")
    result = fill_datasheets(sized, ["T-1", "E-1"], write=False)
    assert "equipment/datasheets/T-1.yaml" in result.skipped
    assert path.read_text(encoding="utf-8") == text
    # E-1 without parameters: its area stays TBD with the reason
    data = yaml.safe_load(result.texts["equipment/datasheets/E-1.yaml"])
    area = data["type_specific"]["area_m2"]
    assert area["value"] == "TBD"
    assert result.findings == [] or all(f.level != "error" for f in result.findings)


def test_the_command(sized: Path, monkeypatch):
    monkeypatch.chdir(sized)
    out = runner.invoke(app, ["datasheets", "fill", "--list"])
    assert out.exit_code == 0 and "cooler/gases-water: 20-300" in out.output
    out = runner.invoke(app, ["datasheets", "fill", "--tag", "K-1", "--dry-run", "--param", "x"])
    assert out.exit_code == 2
    out = runner.invoke(app, ["datasheets", "fill", "--tag", "K-1", "--param", "nope=1"])
    assert out.exit_code == 1 and "cheme.datasheet-fill-param" in out.output
    before = (sized / "equipment" / "datasheets" / "K-1.yaml").read_text(encoding="utf-8")
    out = runner.invoke(
        app,
        ["datasheets", "fill", "--tag", "K-1", "--dry-run", "--param", "heat_capacity_ratio=1.4"]
        + ["--param", "isentropic_efficiency=0.8", "--param", "max_stage_pressure_ratio=3.5"],
    )
    assert out.exit_code == 0, out.output
    assert "would fill equipment/datasheets/K-1.yaml: fluid_power_kw" in out.output
    assert (sized / "equipment" / "datasheets" / "K-1.yaml").read_text(encoding="utf-8") == before


def test_fill_from_another_directory(sized: Path, tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = fill_datasheets(sized, ["V-2"], write=False)
    assert "equipment/datasheets/V-2.yaml" in result.texts or result.unchanged


# -- through the property adapter (extra props) ---------------------------------------------------


def test_exchanger_duty_and_area_through_the_adapter(sized: Path):
    pytest.importorskip("thermo")
    _declare(
        sized,
        "E-1",
        arrangement="counter-current",
        u_service="cooler/gases-water",
        utility_inlet_temperature_degc={"value": 6.85, "source": "CW supply, D-4"},
        utility_outlet_temperature_degc={"value": 11.85, "source": "CW return, D-4"},
    )
    result = fill_datasheets(sized, ["E-1"])
    spec = _specific(sized, "E-1")
    # N2 1 kg/s, 310 -> 300 K: Q ~ m cp dT = 1 x 1.0397 x 10 = 10.40 kW with the ideal-gas cp
    # of N2 at 300 K (29.12 J/(mol K), NIST WebBook, / 28.0134 g/mol); the real gas at 5 bar is
    # within 2 %
    duty = spec["duty_kw"]["value"]
    assert duty == pytest.approx(10.40, rel=0.02), result.findings
    assert "S6 -> S7" in spec["duty_kw"]["source"] and "assumed" not in spec["duty_kw"]
    # counter-current: hot 310 -> 300 K, cold 280 -> 285 K: dT1 25, dT2 20,
    # LMTD = 5 / ln 1.25 = 22.407 K; A = Q / (160 x 1 x 22.407)
    assert spec["lmtd_k"]["value"] == pytest.approx(22.407, abs=0.01)
    assert spec["overall_u_w_m2k"]["value"] == 160 and spec["overall_u_w_m2k"]["assumed"]
    area = spec["area_m2"]
    assert area["value"] == pytest.approx(duty * 1000 / (160 * 22.407), rel=1e-3)
    assert area["assumed"] is True and "Table 12.1" in area["source"]
    sheet = Datasheet.model_validate(
        yaml.safe_load((sized / "equipment" / "datasheets" / "E-1.yaml").read_text())
    )
    assert datasheet_size(sheet, "area")[0] == pytest.approx(area["value"])


def test_column_shortcut_through_the_adapter(sized: Path):
    pytest.importorskip("thermo")
    result = fill_datasheets(sized, ["C-1"], parameters={"reflux_ratio_factor": "1.3"})
    spec = _specific(sized, "C-1")
    nmin = spec["minimum_stages"]["value"]
    # N2/O2 at 500 kPa(a): alpha about 3 (bubble/dew points near 94 to 100 K), so
    # Nmin = ln(19 x 19) / ln(alpha) about 5 to 6
    assert 4.0 < nmin < 7.0, result.findings
    assert "Fenske" in spec["minimum_stages"]["source"]
    assert spec["theoretical_stages"]["value"] > nmin
    assert spec["number_of_stages"]["value"] == "TBD"  # no tray efficiency declared
    assert spec["flooding_diameter_m"]["value"] == "TBD"


def test_column_trays_leave_out_the_reboiler(sized: Path):
    # the Gilliland count includes the partial reboiler, an equilibrium stage
    # that is no tray: trays = ceil((N - 1) / E)
    pytest.importorskip("thermo")
    params = {"reflux_ratio_factor": "1.3", "tray_efficiency": "0.6"}
    result = fill_datasheets(sized, ["C-1"], parameters=params)
    spec = _specific(sized, "C-1")
    n = spec["theoretical_stages"]["value"]
    assert isinstance(n, float), result.findings
    trays = spec["number_of_stages"]
    assert trays["value"] == math.ceil((n - 1) / 0.6 - 1e-9)
    assert "- 1 for the reboiler" in trays["source"]
    assert trays["assumed"] is True
    # no condenser type declared, so a total condenser is assumed and said so
    assert "total condenser (not a stage) ASSUMED" in trays["source"]
    # no condenser declaration named; the parameters
    # it read, the condenser type among them (declaring it later makes the value stale)
    assert all(r.startswith("param:") for r in trays["inputs"])
    assert {"param:tray_efficiency", "param:condenser_type"} <= set(trays["inputs"])


def _simulation(plant: Path, specs: dict) -> None:
    from chemeascode.domains.process.simulation import SCHEMA

    data = {"schema": SCHEMA, "kind": "simulation", "specs": specs}
    (plant / "process" / "simulation.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _column_trays(plant: Path, **params: str) -> tuple[float, dict]:
    params = {"reflux_ratio_factor": "1.3", "tray_efficiency": "0.6", **params}
    result = fill_datasheets(plant, ["C-1"], parameters=params)
    spec = _specific(plant, "C-1")
    n = spec["theoretical_stages"]["value"]
    assert isinstance(n, float), result.findings
    return n, spec["number_of_stages"]


def test_column_trays_with_a_declared_total_condenser(sized: Path):
    # a total condenser is no stage: trays = ceil((N - 1) / E), its basis
    # named
    pytest.importorskip("thermo")
    _declare(sized, "C-1", condenser_type={"value": "total", "source": "D-5"})
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 1) / 0.6 - 1e-9)
    assert trays["source"].endswith("; a total condenser (D-5)")
    assert trays["inputs"][0] == "datasheet:type_specific.condenser_type"
    assert "param:tray_efficiency" in trays["inputs"]


def test_column_trays_leave_out_a_partial_condenser(sized: Path):
    # a partial condenser is an equilibrium stage too: trays = ceil((N - 2) /
    # E)
    pytest.importorskip("thermo")
    _declare(sized, "C-1", condenser_type={"value": "partial", "source": "D-5"})
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 2) / 0.6 - 1e-9)
    assert "- 2 for the reboiler and the partial condenser" in trays["source"]
    assert "a partial condenser (D-5)" in trays["source"]
    assert not _stale(sized)
    # the declared type is an input of the value: changing it makes the value stale
    _declare(sized, "C-1", condenser_type={"value": "total", "source": "D-5"})
    assert [f.ids for f in _stale(sized)] == [["C-1"]]


def test_column_condenser_from_the_simulation_spec(sized: Path):
    # the flowsheet's declaration (the step's condenser in
    # process/simulation.yaml)
    pytest.importorskip("thermo")
    _simulation(sized, {"CL": {"condenser": "partial"}})
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 2) / 0.6 - 1e-9)
    assert "a partial condenser (process/simulation.yaml specs.CL.condenser)" in trays["source"]
    assert trays["inputs"][0] == "condenser:CL"
    assert "param:tray_efficiency" in trays["inputs"]
    assert not _stale(sized)
    _simulation(sized, {"CL": {"condenser": "total"}})
    assert [f.ids for f in _stale(sized)] == [["C-1"]]
    # the datasheet's own declaration comes first
    _declare(sized, "C-1", condenser_type={"value": "total", "source": "D-5"})
    _simulation(sized, {"CL": {"condenser": "partial"}})
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 1) / 0.6 - 1e-9)
    assert "a total condenser (D-5)" in trays["source"]


def test_column_condenser_undeclared_in_the_simulation_spec(sized: Path):
    # a spec without condenser (the schema's default total) is no declaration: assumed
    pytest.importorskip("thermo")
    _simulation(sized, {"CL": {"reflux_ratio": 2.0}})
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 1) / 0.6 - 1e-9)
    assert "total condenser (not a stage) ASSUMED" in trays["source"]
    assert trays["assumed"] is True
    # a simulation file that does not load is said so, not passed off as undeclared
    (sized / "process" / "simulation.yaml").write_text("specs: [", encoding="utf-8")
    n, trays = _column_trays(sized)
    assert trays["value"] == math.ceil((n - 1) / 0.6 - 1e-9)
    assert "process/simulation.yaml does not load)" in trays["source"]


def test_column_condenser_type_refusals(sized: Path):
    pytest.importorskip("thermo")
    _declare(sized, "C-1", condenser_type={"value": "dephlegmator", "source": "D-5"})
    _, trays = _column_trays(sized)
    assert trays["value"] == "TBD"
    assert "not one of total, partial, none" in trays["source"]
    # --param: an assumption, recorded in the sizing basis, where the stale check reads it
    # (param:condenser_type)
    _declare(sized, "C-1", condenser_type="TBD")
    n, trays = _column_trays(sized, condenser_type="partial")
    assert trays["value"] == math.ceil((n - 2) / 0.6 - 1e-9)
    assert "ASSUMED: cheme" in trays["source"] and "param:condenser_type" in trays["inputs"]
    assert not _stale(sized)
    sheet = yaml.safe_load((sized / "equipment" / "datasheets" / "C-1.yaml").read_text())
    assert any(b.get("parameter") == "condenser_type" for b in sheet["sizing_basis"])


def test_column_shortcut_with_a_component_absent_from_a_product(sized: Path):
    # a sharp split: no argon in the distillate. Its K at the top dew point is the
    # infinite-dilution ratio, so the shortcut runs (it stayed TBD: "no liquid AR")
    pytest.importorskip("thermo")
    flowsheet = yaml.safe_load((sized / "process" / "flowsheet.yaml").read_text())
    states = {
        "S8": {"N2": 0.5, "O2": 0.49, "AR": 0.01},
        "S9": {"N2": 0.98, "O2": 0.02},
        "S10": {"N2": 0.02, "O2": 0.96, "AR": 0.02},
    }
    for stream in flowsheet["streams"]:
        if stream["id"] in states:
            stream["state"]["design"]["composition"]["values"] = states[stream["id"]]
    (sized / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(flowsheet, sort_keys=False))
    _declare(
        sized,
        "C-1",
        light_key={"value": "N2", "source": "D-3"},
        heavy_key={"value": "O2", "source": "D-3"},
    )
    result = fill_datasheets(sized, ["C-1"], parameters={"reflux_ratio_factor": "1.3"})
    spec = _specific(sized, "C-1")
    # Nmin = ln((0.98/0.02)(0.96/0.02)) / ln(alpha ~3) = ln 2352 / ~1.1, about 6 to 8
    assert 5.0 < spec["minimum_stages"]["value"] < 9.0, result.findings
    assert isinstance(spec["minimum_reflux_ratio"]["value"], float)


def test_a_tee_is_charged_to_the_stretch_that_ends_at_it():
    # A/N1 -> L1 -> plain joint at x 1 -> L2 -> tee at x 2 (L3 branches off) -> B/N1 at x 3:
    # the tee sits at the end of the second stretch, not the first (the plain joint at x 1
    # is not a tee)
    model = {
        "equipment": [
            {"tag": "A", "nozzles": [{"name": "N1", "point": [0, 0, 0]}]},
            {"tag": "B", "nozzles": [{"name": "N1", "point": [3, 0, 0]}]},
        ],
        "pipes": [
            {
                "id": "L1",
                "points": [[0, 0, 0], [1, 0, 0]],
                "ends": [{"kind": "nozzle", "ref": "A/N1"}],
            },
            {
                "id": "L2",
                "points": [[1, 0, 0], [3, 0, 0]],
                "ends": [{}, {"kind": "nozzle", "ref": "B/N1"}],
            },
            {"id": "L3", "points": [[2, 0, 0], [2, 1, 0]]},
        ],
    }
    network = _Network(model)
    target, steps = network.path("A/N1", {"B"})
    assert target == "B/N1"
    assert [(e.pipe["id"], round(e.length, 3)) for e, _ in steps] == [
        ("L1", 1.0),
        ("L2", 1.0),
        ("L2", 1.0),
    ]
    assert network.tees(steps) == [None, "tee_run", None]
