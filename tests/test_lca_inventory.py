"""Consumables, maintenance, transport and end of life in the plant's LCI dataset.

The plant is ``examples/process-blocks`` with a take-off (10 t of steel) and an equipment list
(a 5 t stainless vessel), 8000 h/a over 20 a: 160,000 h. 1 t of product is 2.5 h; allocation
none, so every exchange per functional unit is 2.5 x its amount per hour.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.report import dataset_yaml, lca_report
from chemeascode.domains.assessment.lca.schemas import LcaFile, LciDataset
from chemeascode.domains.assessment.mto import MtoRow, mto_csv

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
HOURS = 8000 * 20


def _factor(id_: str, unit: str, gwp: float) -> dict:
    return {
        "id": id_,
        "unit": unit,
        "values": {"gwp": gwp},
        "status": "ASSUMED",
        "source": "test",
        "year": 2025,
    }


FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq"}],
    "factors": [
        _factor("feed", "kg", 0.5),
        _factor("steam", "MJ", 0.07),
        _factor("steel", "t", 2000),
        _factor("sieve", "kg", 3.0),
        _factor("lorry", "tkm", 0.1),
        _factor("recycling", "kg", -1.5),
    ],
}
SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
    "allocation": {"method": "none"},
    "flows": [
        {"key": "feed:FEED", "factor": "feed", "source": "test"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
        {"key": "product:WATER", "free": True, "source": "test"},
    ],
    "operation": {"hours_per_year": 8000, "life_years": 20},
    "construction": [
        {"id": "steel", "takeoff": "mto", "category": "steel", "factor": "steel", "source": "test"},
        {
            "id": "vessels",
            "takeoff": "equipment",
            "equipment": {"material": "*"},
            "factor": "steel",
            "source": "test",
        },
    ],
    "consumables": [
        {
            "id": "sieve",
            "title": "Molecular sieve",
            "unit": "t",
            "per_replacement": 4,
            "every_years": 2,
            "factor": "sieve",
            "source": "adsorber refill",
        },
    ],
    "maintenance": {"fraction_per_year": 0.02, "applies_to": ["steel"], "source": "2 %/a"},
    "transport": [
        {
            "id": "to-site",
            "applies_to": ["construction:*"],
            "distance_km": 500,
            "factor": "lorry",
            "source": "lorry to site",
        },
    ],
    "end_of_life": [
        {
            "id": "steel",
            "applies_to": ["construction:steel", "maintenance:steel"],
            "fraction": 0.9,
            "factor": "recycling",
            "source": "90 % recycled",
        },
    ],
}


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root)
    (root / "estimate").mkdir()
    (root / "estimate" / "mto.csv").write_text(
        mto_csv([MtoRow("steel", "HEB300", count=12, quantity=10, unit="t")])
    )
    (root / "equipment").mkdir()
    (root / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump(
            {
                "equipment": [
                    {
                        "tag": "V-1",
                        "type": "Vessel",
                        "material": "SS",
                        "dimensions": {"diameter": 2, "height": 5, "weight": 5},
                    }
                ]
            }
        )
    )
    _write(root, SCOPE)
    return root


def _write(root: Path, scope: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(FACTORS, sort_keys=False))


def test_supplies_per_functional_unit(plant: Path) -> None:
    report = lca_report(plant)
    assert report.loaded, [f.format() for f in report.findings]
    rows = {r.key: r for r in report.inventory.rows}
    # 4 t every 2 years = 2000 kg/a = 0.25 kg/h
    sieve = rows["consumable:sieve"]
    assert (sieve.unit, sieve.phase) == ("kg", "operation")
    assert sieve.quantity == pytest.approx(0.25 * 2.5)
    # 2 %/a of the steel over 20 a: 0.0625 kg/h x 0.02 x 20
    maintenance = rows["maintenance:steel"]
    assert maintenance.phase == "maintenance" and maintenance.mapping == "factor:steel"
    assert maintenance.quantity == pytest.approx(0.0625 * 0.02 * 20 * 2.5)
    assert maintenance.plant == pytest.approx(0.0625 * 0.02 * 20 * HOURS)  # total over the life
    assert "maintenance:vessels" not in rows
    # 15 t of construction over 160,000 h, 500 km
    transport = rows["transport:to-site"]
    assert (transport.unit, transport.phase, transport.kind) == ("tkm", "construction", "transport")
    assert transport.quantity == pytest.approx(15000 / HOURS / 1000 * 500 * 2.5)
    # 90 % of the steel and its replacements, recycled with a credit
    eol = rows["end-of-life:steel"]
    assert eol.phase == "end-of-life" and eol.direction == "output"
    assert eol.quantity == pytest.approx((0.0625 + 0.025) * 0.9 * 2.5)
    by_phase = {p: report.totals(phase=p)["gwp"] for p in ("maintenance", "end-of-life")}
    assert by_phase["maintenance"] == pytest.approx(maintenance.quantity * 2)
    assert by_phase["end-of-life"] == pytest.approx(-eol.quantity * 1.5)
    from chemeascode.domains.assessment.lca.report import results_markdown

    markdown = results_markdown(report)
    assert "phases: operation, construction, maintenance, end-of-life" in markdown
    assert "| category | operation | construction | maintenance | end-of-life |" in markdown
    assert report.totals(phase="operation")["gwp"] == pytest.approx(
        1250 + 220.5 + sieve.quantity * 3
    )


def test_supplies_are_in_the_dataset(plant: Path) -> None:
    dataset = LciDataset.model_validate(yaml.safe_load(dataset_yaml(lca_report(plant))))
    keys = {e.key: e for e in dataset.exchanges}
    assert keys["transport:to-site"].unit == "tkm"
    assert keys["transport:to-site"].streams == ["construction:steel", "construction:vessels"]
    assert keys["end-of-life:steel"].type == "output"


def test_unmatched_and_unit_warnings(plant: Path) -> None:
    scope = yaml.safe_load(yaml.safe_dump(SCOPE))
    scope["maintenance"]["applies_to"] = ["nothing*"]
    scope["transport"][0]["applies_to"] = ["feed:STEAM"]
    _write(plant, scope)
    findings = lca_report(plant).findings
    rules = [f.rule for f in findings]
    assert rules.count("cheme.lca-supply-unmatched") == 2
    assert "cheme.lca-supply-unit" in rules


def test_schema_rules() -> None:
    from pydantic import ValidationError

    base = {
        k: v
        for k, v in SCOPE.items()
        if k not in ("operation", "construction", "maintenance", "end_of_life")
    }
    with pytest.raises(ValidationError, match="consumables needs operation"):
        LcaFile.model_validate(base)
    bad = yaml.safe_load(yaml.safe_dump(SCOPE))
    bad["consumables"][0]["per_year"] = 1
    with pytest.raises(ValidationError, match="give per_year, or per_replacement"):
        LcaFile.model_validate(bad)
    bad = yaml.safe_load(yaml.safe_dump(SCOPE))
    del bad["consumables"][0]["every_years"]
    with pytest.raises(ValidationError, match="per_replacement needs every_years"):
        LcaFile.model_validate(bad)
    bad = yaml.safe_load(yaml.safe_dump(SCOPE))
    bad["consumables"][0]["unit"] = "tkm"
    with pytest.raises(ValidationError, match="unit 'tkm'"):
        LcaFile.model_validate(bad)


def test_transport_counts_inputs_only_and_consumables_reach_end_of_life(plant: Path) -> None:
    scope = yaml.safe_load(yaml.safe_dump(SCOPE))
    scope["transport"][0]["applies_to"] = ["*"]
    scope["end_of_life"].append(
        {
            "id": "sieve",
            "applies_to": ["consumable:sieve"],
            "factor": "recycling",
            "source": "spent sieve",
        }
    )
    _write(plant, scope)
    rows = {r.key: r for r in lca_report(plant).inventory.rows}
    streams = rows["transport:to-site"].streams
    assert "product:PROD" not in streams and "product:WATER" not in streams
    assert {"feed:FEED", "consumable:sieve", "construction:steel"} <= set(streams)
    assert rows["end-of-life:sieve"].quantity == pytest.approx(rows["consumable:sieve"].quantity)


def test_monte_carlo_keeps_supplies_with_their_sources(plant: Path) -> None:
    scope = yaml.safe_load(yaml.safe_dump(SCOPE))
    scope["construction"][0]["uncertainty"] = {"gsd2": 1.5}
    scope["uncertainty"] = {"iterations": 500, "seed": 3}
    _write(plant, scope)
    mc = lca_report(plant).uncertainty
    # maintenance, transport and end of life follow the steel: never inputs of their own; the
    # other exchanges vary by their pedigree
    assert "amount:construction:steel" in mc.varied
    assert mc.bases["amount:construction:steel"] == "given"
    assert not [
        v for v in mc.varied if v.split(":")[1] in ("maintenance", "transport", "end-of-life")
    ]
    assert {b for k, b in mc.bases.items() if k != "amount:construction:steel"} == {"pedigree"}


def test_a_consumable_per_batch_follows_the_recipe(plant: Path) -> None:
    """core#158 package 5: 500 kg of rinse water per batch, 1000 batches of 8 h in 8000 h
    (process/recipe.yaml): 62.5 kg/h of the flowsheet's year averages, 2.5 h per t of PROD."""
    hours = {"provenance": "assumed"}
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {"value": 3200, "unit": "kg", "stream": "S3", **hours},
        "hours_per_year": {"value": 8000, **hours},
        "unit_procedures": [
            {
                "id": "SEPARATE",
                "unit": "SEP",
                "operations": [{"id": "run", "kind": "other", "duration": {"value": 8, **hours}}],
            }
        ],
    }
    (plant / "process" / "recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    scope = {**SCOPE, "consumables": [*SCOPE["consumables"]]}
    scope["consumables"].append(
        {
            "id": "rinse",
            "title": "Rinse water",
            "unit": "kg",
            "per_batch": 500,
            "factor": "sieve",
            "source": "rinse of the vessel (ASSUMED)",
        }
    )
    _write(plant, scope)
    report = lca_report(plant)
    assert report.loaded, [f.format() for f in report.findings]
    rinse = {r.key: r for r in report.inventory.rows}["consumable:rinse"]
    assert rinse.quantity == pytest.approx(62.5 * 2.5)
    dataset = LciDataset.model_validate(yaml.safe_load(dataset_yaml(report)))
    (exchange,) = [e for e in dataset.exchanges if e.key == "consumable:rinse"]
    assert "500 kg per batch x 1000 batches in 8000 h" in exchange.source
    # a recipe that does not load is said to, not called missing
    (plant / "process" / "recipe.yaml").write_text("schema: cheme/recipe/v1\nkind: recipe\n")
    report = lca_report(plant)
    (finding,) = [f for f in report.findings if f.rule == "cheme.lca-per-batch"]
    assert "does not load" in finding.message
    # without the recipe: an error, not a silent zero
    (plant / "process" / "recipe.yaml").unlink()
    report = lca_report(plant)
    assert any(f.rule == "cheme.lca-per-batch" for f in report.findings)
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="per_batch"):
        LcaFile.model_validate(
            {**scope, "consumables": [{**scope["consumables"][-1], "per_year": 1}]}
        )
