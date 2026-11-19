"""Thermal screening of reactors: adiabatic rise, MTSR, Stoessel's
class and the hot spot's sensitivity of a cooled bed, with their findings and cheme process
reactor-hazards."""

import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.safety import reaction_hazards
from chemeascode.domains.safety.reaction_hazards import criticality, screen
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize(
    "mtsr, mtt, td24, expected",
    [
        (350, 360, 400, 1),
        (350, 420, 400, 2),
        (370, 360, 400, 3),
        (410, 360, 400, 4),
        (410, 420, 400, 5),
    ],
)
def test_stoessel_classes(mtsr, mtt, td24, expected):
    assert criticality(mtsr, mtt, td24) == expected


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 160, normal_boiling_point: 390}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 160, normal_boiling_point: 410}
  - {id: S, name: Solvent, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 100, normal_boiling_point: 373}
templates:
  - {id: liquid, components: [A, B, S]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     heat_of_reaction: {value: -80000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},
            orders: {A: 1}, provenance: assumed}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1]
    reactor: batch
    batch: {time: 600, provenance: assumed}
    hazard: {td24: 420, provenance: given, source: "ARC test 12"}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 330, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 5, provenance: given}
        composition: {basis: mole_fraction, values: {A: 0.2, S: 0.8}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: liquid
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, materials=MATERIALS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: hazard-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    return root


def test_a_batch_is_screened_to_its_class(tmp_path):
    report = screen(_plant(tmp_path))
    (entry,) = report.entries
    # 1 kmol A per 5 kmol: 80000 kJ over 160 + 4 x 100 kJ/K
    rise = 80000.0 * 1.0 / (160.0 + 4 * 100.0)
    assert entry.adiabatic_rise == pytest.approx(rise)
    assert entry.accumulation == 1.0
    assert entry.mtsr == pytest.approx(330.0 + rise)  # 472.9 K
    assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    assert entry.td24 == 420.0
    assert entry.criticality == 4  # MTT < TD24 < MTSR
    (finding,) = report.findings
    assert finding.rule == "cheme.reactor-hazard-class" and finding.level == "warning"
    assert finding.line is not None and "class 4" in finding.message


def test_a_cstr_accumulates_only_its_unconverted_key(tmp_path):
    flowsheet = FLOWSHEET.replace("reactor: batch", "reactor: cstr").replace(
        "batch: {time: 600, provenance: assumed}",
        "tank: {residence_time: 2000, provenance: assumed}",
    )
    (entry,) = screen(_plant(tmp_path, flowsheet)).entries
    x = 0.002 * 2000 / (1 + 0.002 * 2000)  # 0.8
    assert entry.accumulation == pytest.approx(1 - x, rel=1e-6)
    assert entry.mtsr == pytest.approx(330.0 + (1 - x) * 80000.0 / 560.0, rel=1e-6)
    assert entry.criticality == 1  # 358.6 K < MTT 373 K < TD24 420 K


def test_what_the_screening_lacks_is_reported(tmp_path):
    flowsheet = FLOWSHEET.replace(
        '    hazard: {td24: 420, provenance: given, source: "ARC test 12"}\n', ""
    )
    materials = MATERIALS.replace("liquid_heat_capacity: 100, ", "")
    report = screen(_plant(tmp_path, flowsheet, materials))
    (entry,) = report.entries
    assert entry.mtsr is None and entry.criticality is None
    (finding,) = report.findings
    assert finding.rule == "cheme.reactor-hazard-missing" and finding.level == "info"
    assert "liquid_heat_capacity of S" in finding.message and "TD24" in finding.message


def test_mtsr_above_mtt_without_td24_is_a_warning(tmp_path):
    flowsheet = FLOWSHEET.replace("td24: 420", "mtt: 400")
    report = screen(_plant(tmp_path, flowsheet))
    rules = {f.rule for f in report.findings}
    assert rules == {"cheme.reactor-hazard-mtsr", "cheme.reactor-hazard-missing"}


def test_a_cooled_bed_gets_its_sensitivity(tmp_path, monkeypatch):
    root = tmp_path / "shift"
    shutil.copytree(EXAMPLES / "process-shift", root)
    path = root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    reactor = next(n for key in ("blocks", "steps") for n in data.get(key) or [] if n.get("bed"))
    reactor["bed"] |= {
        "heat": "cooled",
        "coolant_temperature": 620.0,
        "heat_transfer_coefficient": 150.0,
        "diameter": 0.05,
        "tubes": 400,
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    report = screen(root)
    (entry,) = [e for e in report.entries if e.model == "pfr"]
    assert entry.sensitivity is not None and 0 <= entry.sensitivity < 5
    monkeypatch.setattr(reaction_hazards, "SENSITIVE", -1.0)
    assert any(f.rule == "cheme.reactor-hazard-sensitivity" for f in screen(root).findings)


def test_cli(tmp_path, monkeypatch):
    monkeypatch.chdir(_plant(tmp_path))
    result = CliRunner().invoke(app, ["process", "reactor-hazards"])
    assert result.exit_code == 1
    assert "class 4" in result.output and "do not replace calorimetry" in result.output


def test_a_cstr_series_is_screened_at_its_first_tank(tmp_path):
    flowsheet = FLOWSHEET.replace("reactor: batch", "reactor: cstr").replace(
        "batch: {time: 600, provenance: assumed}",
        "tank: {residence_time: 1000, count: 3, provenance: assumed}",
    )
    (entry,) = screen(_plant(tmp_path, flowsheet)).entries
    first = 0.002 * 1000 / (1 + 0.002 * 1000)  # the first tank converts 2/3
    assert entry.accumulation == pytest.approx(1 - first, rel=1e-6)


ENERGY_IN = (
    FLOWSHEET.replace(
        "  - {id: F, ports: [{id: out, direction: out}]}\n",
        "  - {id: F, ports: [{id: out, direction: out}]}\n"
        "  - {id: POWER, ports: [{id: q, direction: out, kind: energy}]}\n",
    )
    .replace(
        "    ports: [{id: in, direction: in}, {id: out, direction: out}]\n",
        "    ports: [{id: in, direction: in}, {id: out, direction: out},\n"
        "            {id: power, direction: in, kind: energy}]\n",
    )
    .replace("  - id: S2\n", "  - {id: P1, kind: energy, from: POWER.q, to: R.power}\n  - id: S2\n")
)


@pytest.mark.parametrize("model", ["batch", "conversion"])
def test_an_energy_stream_into_the_reactor_is_no_inlet(tmp_path, model):
    # agitator power into a batch, or the heat a conversion step takes up: the reactor is still
    # screened from its one material inlet, as the tank and reactor models count it
    flowsheet = ENERGY_IN
    reactions = None
    if model == "conversion":
        flowsheet = flowsheet.replace("    reactor: batch\n", "    reactor: conversion\n").replace(
            "    batch: {time: 600, provenance: assumed}\n", ""
        )
        reactions = REACTIONS.replace(
            "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},\n"
            "            orders: {A: 1}, provenance: assumed}}\n",
            "     conversion: {key: A, value: 0.5, provenance: assumed}}\n",
        )
    root = _plant(tmp_path, flowsheet)
    if reactions is not None:
        (root / "process/reactions.yaml").write_text(reactions)
    report = screen(root)
    (entry,) = report.entries
    assert "one inlet stream" not in entry.missing
    rise = 80000.0 * 1.0 / (160.0 + 4 * 100.0)
    assert entry.adiabatic_rise == pytest.approx(rise)
    assert entry.mtsr == pytest.approx(330.0 + rise)  # above the MTT of 373 K
    assert entry.criticality == 4
    assert [f.rule for f in report.findings] == ["cheme.reactor-hazard-class"]


GAS_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05,
     ideal_gas: {dHf_298: 0, S_298: 200, cp_R: [3.5]}}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05,
     ideal_gas: {dHf_298: -100000, S_298: 200, cp_R: [3.5]}}
templates:
  - {id: gas, components: [A, B]}
"""

GAS_REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: vapor,
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 1.0},
            orders: {A: 1}, provenance: assumed}}
"""


@pytest.mark.parametrize("heat", ["adiabatic", "isothermal"])
def test_a_gas_batch_is_screened_at_constant_volume(tmp_path, heat):
    # #303: a closed gas batch runs at constant volume (the batch model's cv and dU): the
    # screening's dT_ad is its adiabatic run's rise, not dH over cp
    from chemeascode.domains.process.model import load
    from chemeascode.domains.process.stirred_tank import solve_node

    flowsheet = (
        FLOWSHEET.replace(
            "batch: {time: 600, provenance: assumed}",
            f"batch: {{time: 200, heat: {heat}, provenance: assumed}}",
        )
        .replace("template: liquid", "template: gas")
        .replace("temperature: {value: 330,", "temperature: {value: 300,")
        .replace("pressure: {value: 101.325,", "pressure: {value: 200,")
        .replace("flow: {value: 5,", "flow: {value: 1,")
        .replace("values: {A: 0.2, S: 0.8}", "values: {A: 1.0}")
    )
    root = _plant(tmp_path, flowsheet, GAS_MATERIALS)
    (root / "process/reactions.yaml").write_text(GAS_REACTIONS)
    (entry,) = screen(root).entries
    cv = 3.5 * 8.314462618 - 8.314462618
    assert entry.adiabatic_rise == pytest.approx(100000.0 / cv, rel=1e-9)  # not 100000 / cp
    assert entry.mtsr == pytest.approx(300.0 + 100000.0 / cv, rel=1e-9)
    if heat == "adiabatic":
        process, _ = load(root)
        node = process.nodes["R"]
        inlet = next(s for s in process.flowsheet.streams if s.id == "S1")
        solved, _ = solve_node(process, node, inlet, "design")
        assert solved.temperature - 300.0 == pytest.approx(entry.adiabatic_rise, rel=1e-4)


def test_a_gas_batch_counts_its_change_in_moles(tmp_path):
    # #303: A -> 2 B in a closed vessel releases dU = dH - dnu R T, over cv
    flowsheet = (
        FLOWSHEET.replace("template: liquid", "template: gas")
        .replace("temperature: {value: 330,", "temperature: {value: 300,")
        .replace("values: {A: 0.2, S: 0.8}", "values: {A: 1.0}")
    )
    root = _plant(tmp_path, flowsheet, GAS_MATERIALS)
    (root / "process/reactions.yaml").write_text(
        GAS_REACTIONS.replace("{A: -1, B: 1}", "{A: -1, B: 2}")
    )
    (entry,) = screen(root).entries
    r = 8.314462618
    cp = 3.5 * r
    dh = -200000.0 + cp * (300.0 - 298.15)  # 2 B - A at 300 K
    du = dh - 1 * r * 300.0
    assert entry.adiabatic_rise == pytest.approx(-du / (cp - r), rel=1e-9)


def _outlet_at(flowsheet, kelvin):
    """*flowsheet* with the reactor's outlet S2 given at *kelvin*."""
    s2 = "  - id: S2\n    from: R.out\n    to: P.in\n    template: liquid\n"
    assert s2 in flowsheet
    return flowsheet.replace(
        s2,
        s2 + f"    state:\n      design:\n        temperature: {{value: {kelvin}, "
        "provenance: given}\n",
    )


@pytest.mark.parametrize("heat, t_p", [("isothermal", 353.0), ("adiabatic", 330.0)])
def test_an_isothermal_batch_is_screened_at_its_held_temperature(tmp_path, heat, t_p):
    # #304: the batch model holds an isothermal batch at its outlet's given temperature from
    # the start; a cooling failure begins there, not at the charge's 330 K
    flowsheet = _outlet_at(
        FLOWSHEET.replace(
            "batch: {time: 600, provenance: assumed}",
            f"batch: {{time: 600, heat: {heat}, provenance: assumed}}",
        ),
        353.0,
    )
    (entry,) = screen(_plant(tmp_path, flowsheet)).entries
    rise = 80000.0 * 1.0 / (160.0 + 4 * 100.0)
    assert entry.process_temperature == pytest.approx(t_p)
    assert entry.mtsr == pytest.approx(t_p + rise)


CONVERSION = FLOWSHEET.replace("    reactor: batch\n", "    reactor: conversion\n").replace(
    "    batch: {time: 600, provenance: assumed}\n", ""
)
CONVERSION_REACTIONS = REACTIONS.replace(
    "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},\n"
    "            orders: {A: 1}, provenance: assumed}}\n",
    "     conversion: {key: A, value: 0.5, provenance: assumed}}\n",
)


@pytest.mark.parametrize("outlet, t_p", [(380.0, 380.0), (310.0, 330.0), (None, 330.0)])
def test_a_conversion_step_is_screened_at_its_outlet_temperature(tmp_path, outlet, t_p):
    # #305: a step run at its outlet's given temperature above its feed's, the outlet's
    # composition not known: the fresh feed's potential from there (on the safe side; the
    # inlet's where the step cools its feed)
    flowsheet = CONVERSION if outlet is None else _outlet_at(CONVERSION, outlet)
    root = _plant(tmp_path, flowsheet)
    (root / "process/reactions.yaml").write_text(CONVERSION_REACTIONS)
    (entry,) = screen(root).entries
    rise = 80000.0 * 1.0 / (160.0 + 4 * 100.0)
    assert entry.process_temperature == pytest.approx(t_p)
    assert entry.mtsr == pytest.approx(t_p + rise)


TWO_KEYS_MATERIALS = MATERIALS.replace(
    "templates:\n  - {id: liquid, components: [A, B, S]}\n",
    "  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
    "     liquid_heat_capacity: 160, normal_boiling_point: 420}\n"
    "  - {id: D, name: D, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
    "     liquid_heat_capacity: 160, normal_boiling_point: 420}\n"
    "templates:\n  - {id: liquid, components: [A, B, C, D, S]}\n",
)
TWO_KEYS_REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     heat_of_reaction: {value: -10000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 1.0},
            orders: {A: 1}, provenance: assumed}}
  - {id: R2, stoichiometry: {C: -1, D: 1}, phase: liquid,
     heat_of_reaction: {value: -150000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.0001},
            orders: {C: 1}, provenance: assumed}}
"""


@pytest.mark.parametrize("named", [None, "[R2]"])
def test_a_cstr_accumulates_each_reaction_by_its_own_reactant(tmp_path, named):
    # #306: a fast, mild R1 on A and a slow, strong R2 on C: R2's accumulation is its own
    # unconverted C, not the first-listed reactant A's
    flowsheet = (
        FLOWSHEET.replace("reactor: batch", "reactor: cstr")
        .replace("reactions: [R1]", "reactions: [R1, R2]")
        .replace(
            "batch: {time: 600, provenance: assumed}",
            "tank: {residence_time: 1000, provenance: assumed}",
        )
        .replace("values: {A: 0.2, S: 0.8}", "values: {A: 0.2, C: 0.2, S: 0.6}")
    )
    if named:
        flowsheet = flowsheet.replace(
            "hazard: {td24: 420,", f"hazard: {{reactions: {named}, td24: 420,"
        )
    root = _plant(tmp_path, flowsheet, TWO_KEYS_MATERIALS)
    (root / "process/reactions.yaml").write_text(TWO_KEYS_REACTIONS)
    (entry,) = screen(root).entries
    capacity = 160.0 + 160.0 + 3 * 100.0  # 1 kmol A, 1 C, 3 S
    rise = 150000.0 / capacity
    held_c = 1 - 0.0001 * 1000 / (1 + 0.0001 * 1000)
    assert entry.adiabatic_rise == pytest.approx(rise)
    assert entry.accumulation == pytest.approx(held_c, rel=1e-6)
    assert entry.mtsr == pytest.approx(330.0 + held_c * rise, rel=1e-6)
    held_a = 1 - 1.0 * 1000 / (1 + 1.0 * 1000)
    assert entry.per_reaction["R1"]["mtsr"] == pytest.approx(
        330.0 + held_a * 10000.0 / capacity, rel=1e-6
    )
    assert entry.per_reaction["R2"]["mtsr"] == pytest.approx(entry.mtsr, rel=1e-9)


@pytest.mark.parametrize(
    "outlet, t_p, accumulation",
    [(380.0, 330.0, 1.0), (401.0, 330.0, 1.0), (420.0, 420.0, 0.5)],
)
def test_a_conversion_step_with_its_outlet_known_is_screened_from_the_hotter_state(
    tmp_path, outlet, t_p, accumulation
):
    # #305: with the outlet's composition the cooling failure starts from the fresh feed at
    # the inlet or from the outlet's unconverted half at its temperature, whichever is hotter:
    # cooled (380 K) or adiabatic (about 330 + 71.4 K), the feed's; heated above that, the
    # outlet's, without counting the converted half's heat twice
    flowsheet = _outlet_at(CONVERSION, outlet).replace(
        f"temperature: {{value: {outlet}, provenance: given}}\n",
        f"temperature: {{value: {outlet}, provenance: given}}\n"
        "        flow: {value: 5, provenance: given}\n"
        "        composition: {basis: mole_fraction, values: {A: 0.1, B: 0.1, S: 0.8}, "
        "provenance: given}\n",
    )
    root = _plant(tmp_path, flowsheet)
    (root / "process/reactions.yaml").write_text(CONVERSION_REACTIONS)
    (entry,) = screen(root).entries
    rise = 80000.0 * 1.0 / (160.0 + 4 * 100.0)
    assert entry.process_temperature == pytest.approx(t_p)
    assert entry.accumulation == pytest.approx(accumulation)
    assert entry.mtsr == pytest.approx(t_p + accumulation * rise)
