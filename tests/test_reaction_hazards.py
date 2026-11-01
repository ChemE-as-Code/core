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
