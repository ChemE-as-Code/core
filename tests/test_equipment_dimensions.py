"""Equipment-list ``dimensions`` and ``cheme.equipment-dimension-mismatch``."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.equipment.dimensions import dimension_problems
from chemeascode.domains.equipment.schemas.equipment import Dimensions
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from chemeascode.schemas import EquipmentList


def q(value, unit):
    return SimpleNamespace(value=value, unit=SimpleNamespace(value=unit))


def test_dimensions_schema():
    item = EquipmentList.model_validate(
        yaml.safe_load(
            "equipment:\n  - {tag: T1, type: Tank, dimensions: {diameter: 6, height: 7, "
            "head: cone_roof, support: none, weight: 12}}\n"
        )
    ).equipment[0]
    assert item.dimensions.diameter == 6 and item.dimensions.head == "cone_roof"
    box = Dimensions(length=2, depth=0.8, height=1)
    assert box.across == 0.8
    for bad in (
        {"diameter": 2, "width": 1, "height": 3},
        {"width": 1, "depth": 1, "height": 1},
        {"diameter": -1, "height": 2},
        {"head": "flat"},
        {"diameter": 2, "height": float("inf")},
        {"diameter": 2, "height": 3, "support": "stilts"},
    ):
        with pytest.raises(ValidationError):
            Dimensions.model_validate(bad)


def test_capacity_and_lengths_against_the_dexpi_attributes():
    tank = SimpleNamespace(
        nominalCapacityVolume=q(26.0, "MetreCubed"), cylinderLength=q(4.0, "Metre")
    )
    problems = dimension_problems(Dimensions(diameter=6, height=7), tank)
    assert len(problems) == 1 and "more than 2 times" in problems[0]
    assert dimension_problems(Dimensions(diameter=2.9, height=4.2), tank) == []
    assert "does not fit" in dimension_problems(Dimensions(diameter=2, height=4), tank)[0]
    short = dimension_problems(Dimensions(diameter=3.2, height=3.5), tank)
    assert len(short) == 1 and short[0].startswith("CylinderLength 4 m is longer")
    exchanger = SimpleNamespace(
        tubeBundle=SimpleNamespace(tubeLength=q(2200.0, "Millimetre")),
        chambers=[
            SimpleNamespace(nominalDiameter=q(800.0, "Millimetre"), insideDiameter=None),
            SimpleNamespace(nominalDiameter=None, insideDiameter=None),
        ],
    )
    assert dimension_problems(Dimensions(diameter=0.8, length=3), exchanger) == []
    found = dimension_problems(Dimensions(diameter=1.2, length=2), exchanger)
    assert [p.split(" ", 1)[0] for p in found] == ["TubeLength", "chamber"]
    plate = SimpleNamespace(plateHeight=q(850.0, "Millimetre"), plateWidth=q(1.1, "Metre"))
    assert dimension_problems(Dimensions(length=1.2, width=0.6, height=1.8), plate) == []
    assert len(dimension_problems(Dimensions(length=1.0, width=0.6, height=0.8), plate)) == 2
    # no attribute, no finding; an unknown unit is not compared
    assert dimension_problems(Dimensions(diameter=1, height=1), SimpleNamespace()) == []
    odd = SimpleNamespace(cylinderLength=q(4.0, "Furlong"))
    assert dimension_problems(Dimensions(diameter=1, height=1), odd) == []


def test_validate_reports_a_mismatch_on_the_equipment_list(plant: Path):
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        "  - {tag: H1007, type: PlateHeatExchanger, sheet: P-01}\n"
        "  - {tag: H1008, type: TubularHeatExchanger, sheet: P-01,\n"
        "     dimensions: {diameter: 0.8, length: 3}}\n"
        "  - {tag: P4711, type: CentrifugalPump, sheet: P-01}\n"
        "  - {tag: P4712, type: ReciprocatingPump, sheet: P-01}\n"
        "  - {tag: T4750, type: Tank, sheet: P-01, dimensions: {diameter: 6, height: 7}}\n"
    )
    report = validate_workspace(Workspace(plant))
    found = [f for f in report.findings if f.rule == "cheme.equipment-dimension-mismatch"]
    assert {f.ids[0] for f in found} == {"T4750"}
    assert all(f.file == "equipment/equipment-list.yaml" and f.line == 7 for f in found)
    assert any("NominalCapacityVolume 26" in f.message for f in found)
    assert all(f.level == "warning" for f in found)
