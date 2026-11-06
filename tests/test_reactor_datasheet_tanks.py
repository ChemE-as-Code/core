"""Reactor datasheets of stirred tanks and batches: the working
volume and duty of a CSTR series from its solved model; a batch's left to its size and cycle."""

from pathlib import Path

import pytest
import yaml

from chemeascode.domains.equipment.fill import fill_datasheets
from chemeascode.project.datasheets import draft_missing

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 160}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 160}
templates:
  - {id: liquid, components: [A, B]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     heat_of_reaction: {value: -50000, provenance: assumed},
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
    reactor: cstr
    tank: {residence_time: 500, count: 2, provenance: assumed}
    links: [{target: equipment, ref: R-1}]
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 350, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 36, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: liquid
"""


def _write(plant: Path, flowsheet: str = FLOWSHEET) -> None:
    (plant / "process/materials.yaml").write_text(MATERIALS)
    (plant / "process/reactions.yaml").write_text(REACTIONS)
    (plant / "process/flowsheet.yaml").write_text(flowsheet)
    (plant / "equipment/equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": [{"tag": "R-1", "type": "PressureVessel"}]})
    )


def test_a_cstr_series_fills_its_volume_and_duty(plant: Path):
    _write(plant)
    draft_missing(plant)
    result = fill_datasheets(plant, ["R-1"])
    assert not [f.format() for f in result.findings if f.level == "error"]
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    # Q0 = 36 kmol/h x 0.1 m3/kmol = 0.001 m3/s; 2 tanks of 500 s (0.5 m3) each
    assert specific["volume_m3"]["value"] == pytest.approx(1.0, rel=1e-3)
    assert "lower bound" in specific["volume_m3"]["source"]
    # isothermal at 350 K: the duty removes the heat of the converted A
    x = 1 - 1 / (1 + 0.002 * 500) ** 2
    assert specific["duty_kw"]["value"] == pytest.approx(-50000 * x * 0.01, rel=1e-3)


def test_a_batch_leaves_volume_and_duty_open(plant: Path):
    _write(
        plant,
        FLOWSHEET.replace("reactor: cstr", "reactor: batch").replace(
            "tank: {residence_time: 500, count: 2, provenance: assumed}",
            "batch: {time: 600, provenance: assumed}",
        ),
    )
    draft_missing(plant)
    fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    assert "batch size and cycle" in str(specific["volume_m3"])


def test_a_batch_takes_its_vessel_and_peak_duty_from_the_recipe(plant: Path):
    """S1 is 36 kmol/h x 44.05 kg/kmol: a batch of 2 h of it is 7.2 m3, over 80 % fill 9 m3,
    rounded up to 10 m3 (core#158 package 3)."""
    _write(
        plant,
        FLOWSHEET.replace("reactor: cstr", "reactor: batch").replace(
            "tank: {residence_time: 500, count: 2, provenance: assumed}",
            "batch: {time: 600, provenance: assumed}",
        ),
    )
    hours = {"provenance": "assumed"}
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {"value": 36 * 44.05 * 2, "unit": "kg", "stream": "S1", **hours},
        "hours_per_year": {"value": 8000, **hours},
        "unit_procedures": [
            {
                "id": "REACT",
                "unit": "R",
                "vessel": {"fill_fraction": 0.8, **hours},
                "operations": [
                    {"id": "charge", "kind": "charge", "duration": {"value": 1, **hours}},
                    {"id": "react", "kind": "react", "from": "R"},
                ],
            }
        ],
    }
    (plant / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    draft_missing(plant)
    fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    assert specific["volume_m3"]["value"] == pytest.approx(10.0)
    assert "process/recipe.yaml" in specific["volume_m3"]["source"]
    assert specific["duty_kw"]["value"] < 0


def test_the_recipe_vessel_goes_stale_with_the_batch_size_stream(plant: Path):
    from chemeascode.domains.equipment.fill import input_data
    from chemeascode.domains.process.model import load

    test_a_batch_takes_its_vessel_and_peak_duty_from_the_recipe(plant)
    process, _ = load(plant)
    before = input_data("recipe:REACT", {}, process, None, {})
    path = plant / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("flow: {value: 36,", "flow: {value: 40,"))
    process, _ = load(plant)
    assert input_data("recipe:REACT", {}, process, None, {}) != before
