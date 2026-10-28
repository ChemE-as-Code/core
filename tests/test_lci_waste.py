"""Wastes, by-products, recycling and end of life consistent with the system model, and the
cut-off flows recorded in the dataset (pre-release issue 180).

The plant is ``examples/process-blocks`` (see ``test_lca.py``): 1000 kg/h feed and 350 kW of
steam make 400 kg/h of product PROD and 600 kg/h of WATER, 8000 h/a over 20 a. 1 t of PROD is
2.5 h; allocation none. The input mass (the cut-off criteria's basis) is the feed, 1000 kg/h.
"""

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca.cutoff import findings as cutoff_findings
from chemeascode.domains.assessment.lca.cutoff import input_mass, never_cut
from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import dataset_yaml, lca_report
from chemeascode.domains.assessment.lca.schemas import (
    CutoffFlow,
    FlowMap,
    LcaFile,
    LciDataset,
)
from chemeascode.domains.assessment.mto import MtoRow, mto_csv

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
HOURS = 8000


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
        _factor("steel", "kg", 2.0),
        _factor("sieve", "kg", 3.0),
        _factor("landfill", "kg", 0.1),
        _factor("recycling", "kg", 0.2),
        _factor("primary-steel", "kg", 2.0),
        _factor("credit", "kg", -1.5),
        _factor("wastewater", "kg", 0.001),
        _factor("nickel", "kg", 12.0),
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
        {
            "key": "product:WATER",
            "factor": "wastewater",
            "source": "test",
            "treatment": {"kind": "waste", "route": "wastewater treatment"},
        },
    ],
    "operation": {"hours_per_year": HOURS, "life_years": 20},
}


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    return root


def _write(root: Path, scope: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(FACTORS, sort_keys=False))


def _scope(**changes) -> dict:
    scope = copy.deepcopy(SCOPE)
    scope.update(changes)
    return scope


def _exchanges(report) -> dict:
    return {e.key: e for e in report.inventory.dataset.exchanges}


def _rules(report) -> list[str]:
    return [f.rule for f in report.findings]


# -- outputs of the flowsheet: waste, recyclable, by-product ------------------------------------


def test_a_waste_output_is_linked_to_its_treatment(blocks: Path) -> None:
    _write(blocks, SCOPE)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    water = _exchanges(report)["product:WATER"]
    assert water.treatment.kind == "waste" and water.treatment.route == "wastewater treatment"
    assert water.link.factor == "wastewater" and not water.free
    # 1500 kg of waste water per t of PROD
    assert report.totals()["gwp"] == pytest.approx(1250 + 220.5 + 1.5)


def _recyclable(credit: bool = True) -> dict:
    treatment = {"kind": "recyclable", "route": "reuse as process water"}
    if credit:
        treatment |= {"credit": {"factor": "credit", "source": "avoided demineralised water"}}
    return {
        "key": "product:WATER",
        "factor": "recycling",
        "source": "test",
        "treatment": treatment,
    }


def test_a_recyclable_leaves_burden_free_under_cut_off(blocks: Path) -> None:
    scope = _scope(flows=[*SCOPE["flows"][:2], _recyclable()])
    _write(blocks, scope)
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    water = exchanges["product:WATER"]
    # cut-off: the recycler carries the treatment, and there is no credit
    assert water.free and water.link is None
    assert water.treatment.credit.factor == "credit"  # recorded for a substitution build
    assert not [k for k in exchanges if k.startswith("avoided:")]
    assert report.totals()["gwp"] == pytest.approx(1250 + 220.5)
    assert "cheme.lca-cutoff-credit" not in _rules(report)
    assert report.inventory.dataset.system_model is None  # not stated: recorded as none


def test_substitution_credits_the_avoided_production(blocks: Path) -> None:
    scope = _scope(flows=[*SCOPE["flows"][:2], _recyclable()], system_model="substitution")
    _write(blocks, scope)
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    avoided = exchanges["avoided:product.WATER"]
    assert (avoided.type, avoided.amount, avoided.streams) == ("input", -600, ["product:WATER"])
    assert exchanges["product:WATER"].link.factor == "recycling"
    assert report.inventory.dataset.system_model == "substitution"
    # 1500 kg recycled x 0.2, less 1500 kg avoided x -1.5 (negative amount x negative factor)
    assert report.totals()["gwp"] == pytest.approx(1250 + 220.5 + 1500 * 0.2 + 1500 * 1.5)
    # the dataset written reads back, its credit with it
    LciDataset.model_validate(yaml.safe_load(dataset_yaml(report)))


def test_a_by_product_output_is_free_under_cut_off(blocks: Path) -> None:
    flow = {
        "key": "product:WATER",
        "free": True,
        "source": "sold as cooling-tower make-up",
        "treatment": {"kind": "byproduct", "route": "sold"},
    }
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], flow]))
    water = _exchanges(lca_report(blocks))["product:WATER"]
    assert water.free and water.treatment.kind == "byproduct"


# -- consumables and construction: what goes in also comes out ----------------------------------


SIEVE = {
    "id": "sieve",
    "title": "Molecular sieve",
    "unit": "t",
    "per_replacement": 4,
    "every_years": 2,
    "factor": "sieve",
    "source": "adsorber refill",
}


def test_a_consumable_is_disposed(blocks: Path) -> None:
    sieve = SIEVE | {
        "disposal": {"route": "landfill", "factor": "landfill", "source": "spent sieve"}
    }
    _write(blocks, _scope(consumables=[sieve]))
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    spent = exchanges["disposal:consumable.sieve"]
    # 4 t every 2 years = 0.25 kg/h in, and out again
    assert (spent.type, spent.amount, spent.unit) == ("output", pytest.approx(0.25), "kg")
    assert spent.treatment.kind == "waste" and spent.treatment.route == "landfill"
    assert spent.streams == ["consumable:sieve"]
    rows = {r.key: r for r in report.inventory.rows}
    assert rows["disposal:consumable.sieve"].quantity == pytest.approx(0.25 * 2.5)
    assert report.totals()["gwp"] == pytest.approx(1250 + 220.5 + 1.5 + 0.625 * (3.0 + 0.1))
    assert "cheme.lca-disposal" not in _rules(report)


def test_a_replaced_consumable_without_disposal_is_a_finding(blocks: Path) -> None:
    oil = {"id": "oil", "unit": "kg", "per_year": 100, "factor": "sieve", "source": "lube oil"}
    _write(blocks, _scope(consumables=[SIEVE, oil]))
    report = lca_report(blocks)
    levels = {f.ids[0]: f.level for f in report.findings if f.rule == "cheme.lca-disposal"}
    assert levels == {"consumable:sieve": "warning", "consumable:oil": "info"}
    assert any("consumable sieve" in p for p in lca_gate(blocks, ["cutoff-criteria"]))


def test_a_catalyst_charge_goes_to_metal_recovery(blocks: Path) -> None:
    catalyst = {
        "id": "catalyst",
        "unit": "kg",
        "initial_charge": 2000,
        "per_replacement": 2000,
        "every_years": 5,
        "catalyst": True,
        "metals": {"Ni": 0.2},
        "factor": "nickel",
        "source": "reformer catalyst",
        "disposal": {
            "kind": "recyclable",
            "route": "metal recovery",
            "credit": {"factor": "nickel", "source": "avoided primary nickel"},
            "ratio": 0.2,
            "source": "spent catalyst to a nickel refiner",
        },
    }
    _write(blocks, _scope(consumables=[catalyst]))
    exchanges = _exchanges(lca_report(blocks))
    # 2000 kg every 5 a plus the first charge over 20 a: 500 kg/a
    per_hour = 500 / HOURS
    assert exchanges["consumable:catalyst"].amount == pytest.approx(per_hour)
    assert exchanges["consumable:catalyst"].metals == {"Ni": 0.2}
    spent = exchanges["disposal:consumable.catalyst"]
    assert spent.amount == pytest.approx(per_hour) and spent.metals == {"Ni": 0.2}
    assert spent.free and "avoided:disposal.consumable.catalyst" not in exchanges
    _write(blocks, _scope(consumables=[catalyst], system_model="substitution"))
    exchanges = _exchanges(lca_report(blocks))
    credit = exchanges["avoided:disposal.consumable.catalyst"]
    assert credit.amount == pytest.approx(-per_hour * 0.2)


def _plant_with_steel(root: Path) -> None:
    (root / "estimate").mkdir()
    (root / "estimate" / "mto.csv").write_text(
        mto_csv([MtoRow("steel", "HEB300", count=12, quantity=16, unit="t")])
    )


def test_construction_and_maintenance_are_disposed(blocks: Path) -> None:
    _plant_with_steel(blocks)
    steel = {
        "id": "steel",
        "takeoff": "mto",
        "category": "steel",
        "factor": "steel",
        "source": "take-off",
        "disposal": {
            "kind": "recyclable",
            "route": "steel scrap to an electric arc furnace",
            "fraction": 0.9,
            "credit": {"factor": "primary-steel", "source": "avoided primary steel"},
            "source": "90 % recovered",
        },
    }
    scope = _scope(
        construction=[steel],
        maintenance={"fraction_per_year": 0.02, "applies_to": ["steel"], "source": "2 %/a"},
    )
    _write(blocks, scope)
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    built = exchanges["construction:steel"].amount  # 16 t over 160,000 h = 0.1 kg/h
    assert built == pytest.approx(0.1)
    scrap = exchanges["disposal:construction.steel"]
    assert (scrap.phase, scrap.amount, scrap.free) == ("end-of-life", pytest.approx(0.09), True)
    spares = exchanges["disposal:maintenance.steel"]
    assert spares.phase == "maintenance"
    assert spares.amount == pytest.approx(0.1 * 0.02 * 20 * 0.9)
    assert report.totals(phase="end-of-life")["gwp"] == pytest.approx(0)


# -- end of life: material outputs and the study's system model ---------------------------------


def _eol(**changes) -> dict:
    entry = {
        "id": "steel",
        "applies_to": ["construction:steel"],
        "fraction": 0.9,
        "kind": "recyclable",
        "route": "steel scrap",
        "credit": {"factor": "primary-steel", "source": "avoided primary steel"},
        "source": "90 % recovered",
    }
    entry.update(changes)
    return entry


STEEL = {
    "id": "steel",
    "takeoff": "mto",
    "category": "steel",
    "factor": "steel",
    "source": "take-off",
}


def test_end_of_life_recycling_gives_no_credit_under_cut_off(blocks: Path) -> None:
    _plant_with_steel(blocks)
    _write(blocks, _scope(construction=[STEEL], end_of_life=[_eol()]))
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    scrap = exchanges["end-of-life:steel"]
    assert scrap.free and scrap.treatment.kind == "recyclable"
    assert not [k for k in exchanges if k.startswith("avoided:")]
    assert report.totals(phase="end-of-life")["gwp"] == pytest.approx(0)
    assert "cheme.lca-eol-kind" not in _rules(report)


def test_end_of_life_credit_in_the_substitution_variant(blocks: Path) -> None:
    _plant_with_steel(blocks)
    _write(blocks, _scope(construction=[STEEL], end_of_life=[_eol()], system_model="substitution"))
    report = lca_report(blocks)
    credit = _exchanges(report)["avoided:end-of-life.steel"]
    assert credit.amount == pytest.approx(-0.09) and credit.phase == "end-of-life"
    assert report.totals(phase="end-of-life")["gwp"] == pytest.approx(-0.09 * 2.5 * 2.0)


def test_a_credit_hidden_in_a_background_is_flagged_under_cut_off(blocks: Path) -> None:
    _plant_with_steel(blocks)
    legacy = {
        "id": "steel",
        "applies_to": ["construction:steel"],
        "fraction": 0.9,
        "factor": "credit",
        "source": "recycling credit",
    }
    _write(blocks, _scope(construction=[STEEL], end_of_life=[legacy]))
    report = lca_report(blocks)
    # read as before (the numbers do not change), but no longer silently
    assert report.totals(phase="end-of-life")["gwp"] == pytest.approx(-0.09 * 2.5 * 1.5)
    assert {"cheme.lca-eol-kind", "cheme.lca-cutoff-credit"} <= set(_rules(report))
    assert any("negative impact" in p for p in lca_gate(blocks, ["cutoff-criteria"]))


def test_substitution_allocation_in_a_cut_off_study_is_a_finding(blocks: Path) -> None:
    scope = _scope(
        allocation={
            "method": "substitution",
            "coproducts": ["WATER"],
            "substitution": {"WATER": {"factor": "wastewater", "source": "test"}},
        },
        flows=SCOPE["flows"][:2],
    )
    _write(blocks, scope)
    assert "cheme.lca-system-model" in _rules(lca_report(blocks))
    # co-product credits in a cut-off study fail the gate (pre-release PR 311 review)
    assert any("allocation substitution" in p for p in lca_gate(blocks, ["cutoff-criteria"]))
    _write(blocks, scope | {"system_model": "substitution"})
    assert not any("allocation substitution" in p for p in lca_gate(blocks, ["cutoff-criteria"]))


# -- cut-off flows recorded and checked ---------------------------------------------------------


def test_cut_flows_are_recorded_and_checked(blocks: Path) -> None:
    # 1 % of 1000 kg/h over 8000 h is 80 t/a
    cutoff = [
        {"id": "packaging", "per_year": 8000, "reason": "pallets and bags, 0.1 %"},
        {"id": "antifoam", "per_year": 40000, "reason": "dosed antifoam, 0.5 %"},
    ]
    _write(blocks, _scope(cutoff=cutoff))
    report = lca_report(blocks)
    cut = {c.key: c for c in report.inventory.dataset.cutoff}
    assert cut["cutoff:packaging"].amount == pytest.approx(1.0)
    assert input_mass(report.inventory.dataset) == pytest.approx(1000 + 1 + 5)
    assert "cut off by the study's criteria: cutoff:antifoam (dosed antifoam, 0.5 %)" in (
        report.limitations
    )
    assert lca_gate(blocks, ["cutoff-criteria"]) == []
    # the dataset written keeps them, so the library build can check them again
    dataset = LciDataset.model_validate(yaml.safe_load(dataset_yaml(report)))
    assert [c.key for c in dataset.cutoff] == ["cutoff:packaging", "cutoff:antifoam"]
    assert cutoff_findings(dataset, "lca/dataset.yaml") == []


def test_cut_flows_above_the_criteria(blocks: Path) -> None:
    cutoff = [
        {"id": "a", "per_year": 72000, "reason": "0.9 %"},
        {"id": "b", "per_year": 16000, "reason": "0.2 %"},
        {"id": "big", "per_year": 90000, "reason": "1.1 %"},
        {"id": "unknown", "reason": "not known"},
    ]
    _write(blocks, _scope(cutoff=cutoff))
    report = lca_report(blocks)
    rules = {f.rule: f for f in report.findings if f.rule.startswith("cheme.lca-cutoff")}
    assert rules["cheme.lca-cutoff-share"].ids == ["cutoff:big"]
    assert "cheme.lca-cutoff-sum" in rules
    assert rules["cheme.lca-cutoff-unchecked"].ids == ["cutoff:unknown"]
    # share and sum fail the gate; the flow with no amount is an info and does not
    assert len(lca_gate(blocks, ["cutoff-criteria"])) == 2


def test_never_cut() -> None:
    def flow(**kw) -> CutoffFlow:
        return CutoffFlow(key="cutoff:x", reason="small", amount=0.001, **kw)

    assert "Pt" in never_cut(flow(catalyst=True, contains=["Pt"]))
    assert "N2O" in never_cut(flow(cas="10024-97-2", direction="output"))
    assert "SF6" in never_cut(flow(cas="2551-62-4"))
    assert "Hg" in never_cut(flow(cas="7439-97-6"))
    assert "heavy metals" in never_cut(flow(direction="output", contains=["Cd"]))
    assert never_cut(flow(contains=["Fe"])) == ""
    # a precious or critical metal named in contains is never cut, catalyst flag or not
    assert "Pt" in never_cut(flow(contains=["Pt"]))
    assert "Ni" in never_cut(flow(contains=["Ni"]))
    assert "Ni" in never_cut(flow(catalyst=True, contains=["Ni"]))


def test_a_disposal_cut_off_is_recorded(blocks: Path) -> None:
    catalyst = {
        "id": "catalyst",
        "unit": "kg",
        "per_replacement": 100,
        "every_years": 5,
        "catalyst": True,
        "metals": {"Pt": 0.003},
        "factor": "nickel",
        "source": "test",
        "disposal": {
            "route": "returned to the vendor",
            "cutoff": "below 0.01 % of the input",
            "source": "vendor take-back",
        },
    }
    _write(blocks, _scope(consumables=[catalyst]))
    report = lca_report(blocks)
    (cut,) = report.inventory.dataset.cutoff
    assert (cut.key, cut.direction, cut.contains, cut.catalyst) == (
        "disposal:consumable.catalyst",
        "output",
        ["Pt"],
        True,
    )
    assert "disposal:consumable.catalyst" not in _exchanges(report)
    assert any("never cut" in p for p in lca_gate(blocks, ["cutoff-criteria"]))


# -- schema ------------------------------------------------------------------------------------


DATASET = {
    "schema": "cheme/lci_dataset/v2",
    "kind": "lci_dataset",
    "id": "scrap",
    "exchanges": [
        {"key": "product:P", "type": "product", "amount": 1.0, "unit": "kg"},
        {
            "key": "avoided:end-of-life.steel",
            "type": "input",
            "amount": -0.4,
            "unit": "kg",
            "link": {"factor": "primary-steel", "source": "credit"},
        },
    ],
}


def test_a_cut_off_dataset_holds_no_credits() -> None:
    with pytest.raises(ValidationError, match="avoided-burden credits"):
        LciDataset.model_validate(DATASET)
    with pytest.raises(ValidationError, match="avoided-burden credits"):
        LciDataset.model_validate(DATASET | {"system_model": "cutoff"})
    assert LciDataset.model_validate(DATASET | {"system_model": "substitution"})
    bad = copy.deepcopy(DATASET) | {"system_model": "substitution"}
    bad["exchanges"][1]["amount"] = 0.4
    with pytest.raises(ValidationError, match="negative amount"):
        LciDataset.model_validate(bad)
    # a negative input not named avoided: is reported (the build can refuse it)
    other = copy.deepcopy(DATASET)
    other["exchanges"][1]["key"] = "end-of-life:scrap"
    found = cutoff_findings(LciDataset.model_validate(other), "d.yaml")
    assert [f.rule for f in found] == ["cheme.lca-cutoff-credit"]


def test_schema_rules() -> None:
    # a waste may carry a credit (the heat of an incineration): it counts only when crediting
    assert FlowMap.model_validate(
        {
            "key": "product:W",
            "factor": "x",
            "source": "test",
            "treatment": {
                "kind": "waste",
                "route": "incineration with energy recovery",
                "credit": {"factor": "y", "source": "test"},
            },
        }
    )
    with pytest.raises(ValidationError, match="only a product"):
        FlowMap.model_validate(
            {
                "key": "feed:W",
                "factor": "x",
                "source": "test",
                "treatment": {"kind": "waste", "route": "landfill"},
            }
        )
    with pytest.raises(ValidationError, match="a waste is not free"):
        FlowMap.model_validate(
            {
                "key": "product:W",
                "free": True,
                "source": "test",
                "treatment": {"kind": "waste", "route": "landfill"},
            }
        )
    base = _scope(consumables=[SIEVE | {"disposal": {"route": "landfill", "source": "test"}}])
    with pytest.raises(ValidationError, match="give one of"):
        LcaFile.model_validate(base)
    recyclable = {"kind": "recyclable", "route": "regeneration", "source": "test"}
    assert LcaFile.model_validate(_scope(consumables=[SIEVE | {"disposal": recyclable}]))
    with pytest.raises(ValidationError, match="only a mass is disposed"):
        LcaFile.model_validate(
            _scope(consumables=[SIEVE | {"unit": "kWh", "disposal": recyclable}])
        )
    with pytest.raises(ValidationError, match="system_model substitution and dataset"):
        LcaFile.model_validate(
            _scope(system_model="substitution", dataset={"system_model": "cutoff"})
        )
    with pytest.raises(ValidationError, match="names its route"):
        LcaFile.model_validate(_scope(end_of_life=[_eol(route="")]))
    with pytest.raises(ValidationError, match="need kind"):
        LcaFile.model_validate(_scope(end_of_life=[_eol(kind=None)]))
    with pytest.raises(ValidationError, match="element symbols"):
        LcaFile.model_validate(_scope(consumables=[SIEVE | {"metals": {"nickel": 0.2}}]))


def test_disposal_and_credits_follow_their_source_in_the_monte_carlo(blocks: Path) -> None:
    import numpy as np

    from chemeascode.domains.assessment.lca.uncertainty import _derived

    sieve = SIEVE | {
        "disposal": {
            "kind": "recyclable",
            "route": "regeneration",
            "factor": "landfill",
            "credit": {"factor": "credit", "source": "avoided sieve"},
            "source": "spent sieve",
        },
        "uncertainty": {"gsd2": 1.5},
    }
    scope = _scope(
        consumables=[sieve],
        system_model="substitution",
        uncertainty={"iterations": 200, "seed": 1},
    )
    _write(blocks, scope)
    report = lca_report(blocks)
    assert "amount:consumable:sieve" in report.uncertainty.varied
    assert "amount:disposal:consumable.sieve" not in report.uncertainty.varied
    by_key = _exchanges(report)
    multiplier = {"consumable:sieve": np.array([0.5, 1.0, 2.0])}
    one = np.ones(3)
    # no multiplier of its own: each takes its source's, draw by draw (the credit through the
    # disposal it is streamed from)
    for key in ("disposal:consumable.sieve", "avoided:disposal.consumable.sieve"):
        got = _derived(by_key[key], by_key, multiplier, one)
        assert got is not None and np.allclose(got, multiplier["consumable:sieve"]), key
        multiplier[key] = got


def _from_boiler(blocks: Path, dataset: dict) -> dict:
    """A scope whose STEAM comes from the background dataset *dataset* (lca/boiler.yaml)."""
    (blocks / "lca").mkdir(exist_ok=True)
    (blocks / "lca" / "boiler.yaml").write_text(yaml.safe_dump(dataset, sort_keys=False))
    scope = _scope()
    scope["flows"][1] = {
        "key": "feed:STEAM",
        "dataset": {"path": "lca/boiler.yaml", "product": "STEAM"},
        "source": "test",
    }
    return scope


def _boiler(gas: float, **extra) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "steam-boiler",
        "exchanges": [
            {"key": "product:STEAM", "type": "product", "amount": 1, "unit": "kWh"},
            {
                "key": "feed:GAS",
                "type": "input",
                "amount": gas,
                "unit": "kWh",
                "link": {"factor": "steam", "source": "test"},
            },
        ],
        **extra,
    }


def test_mixed_system_models_are_a_finding(blocks: Path) -> None:
    scope = _from_boiler(blocks, _boiler(1.1, system_model="substitution"))
    _write(blocks, scope)
    found = [f for f in lca_report(blocks).findings if f.rule == "cheme.lca-system-model-mixed"]
    assert len(found) == 1 and found[0].level == "warning"
    assert "lca/boiler.yaml" in found[0].ids
    assert any("another system model" in p for p in lca_gate(blocks, ["cutoff-criteria"]))
    # the same dataset in a study of its own system model is not mixed
    _write(blocks, scope | {"system_model": "substitution"})
    assert "cheme.lca-system-model-mixed" not in _rules(lca_report(blocks))


# -- review fixes -------------------------------------------------------------------------------


def _treatment_flow(**treatment) -> dict:
    return {
        "key": "product:WATER",
        "factor": "wastewater",
        "source": "test",
        "treatment": treatment,
    }


def test_a_recyclable_burned_is_flagged(blocks: Path) -> None:
    flow = _treatment_flow(kind="recyclable", route="incineration with energy recovery")
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], flow]))
    found = [f for f in lca_report(blocks).findings if f.rule == "cheme.lca-recyclable-energy"]
    assert len(found) == 1 and found[0].ids == ["product:WATER"]
    # a waste linked to its incineration is the right form: no finding
    waste = _treatment_flow(kind="waste", route="incineration with energy recovery")
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], waste]))
    assert "cheme.lca-recyclable-energy" not in _rules(lca_report(blocks))


def test_a_hazardous_recyclable_without_a_background_is_flagged(blocks: Path) -> None:
    free = {
        "key": "product:WATER",
        "free": True,
        "source": "test",
        "treatment": {"kind": "recyclable", "route": "solvent recovery", "hazardous": True},
    }
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], free]))
    found = [f for f in lca_report(blocks).findings if f.rule == "cheme.lca-hazardous-recyclable"]
    assert len(found) == 1 and found[0].level == "warning"
    # a background, or hazardous unset: no finding
    linked = _treatment_flow(kind="recyclable", route="solvent recovery", hazardous=True)
    for flow in (linked, free | {"treatment": free["treatment"] | {"hazardous": False}}):
        _write(blocks, _scope(flows=[*SCOPE["flows"][:2], flow]))
        assert "cheme.lca-hazardous-recyclable" not in _rules(lca_report(blocks))


def test_a_hazardous_recyclable_with_a_background_counts_it_under_cut_off(blocks: Path) -> None:
    # pre-release PR 311 review: linking the treatment (the remedy of
    # cheme.lca-hazardous-recyclable) must count it; the producer pays for the treatment of a
    # hazardous recyclable
    linked = _treatment_flow(kind="recyclable", route="solvent recovery", hazardous=True)
    for model in ("cutoff", "apos", "substitution"):
        _write(blocks, _scope(flows=[*SCOPE["flows"][:2], linked], system_model=model))
        report = lca_report(blocks)
        water = _exchanges(report)["product:WATER"]
        assert not water.free and water.link.factor == "wastewater", model
        assert report.totals()["gwp"] == pytest.approx(1250 + 220.5 + 1.5), model
    # not hazardous: burden-free under cut-off, as before
    plain = _treatment_flow(kind="recyclable", route="solvent recovery")
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], plain]))
    assert _exchanges(lca_report(blocks))["product:WATER"].free


def _burned() -> dict:
    return _treatment_flow(
        kind="waste",
        route="incineration with energy recovery",
        credit={"factor": "credit", "source": "avoided grid electricity"},
    )


def test_a_waste_credit_counts_only_under_crediting_models(blocks: Path) -> None:
    flows = [*SCOPE["flows"][:2], _burned()]
    for model in ("cutoff", "apos"):
        _write(blocks, _scope(flows=flows, system_model=model))
        report = lca_report(blocks)
        assert report.loaded, [f.format() for f in report.findings]
        exchanges = _exchanges(report)
        assert not [k for k in exchanges if k.startswith("avoided:")]
        # the burden of the incineration stays with the producer; the credit is only recorded
        assert exchanges["product:WATER"].link.factor == "wastewater"
        assert exchanges["product:WATER"].treatment.credit.factor == "credit"
        assert "cheme.lca-cutoff-credit" not in _rules(report)
    _write(blocks, _scope(flows=flows, system_model="substitution"))
    exchanges = _exchanges(lca_report(blocks))
    assert exchanges["avoided:product.WATER"].amount == pytest.approx(-600)
    assert exchanges["product:WATER"].link.factor == "wastewater"


def test_a_nickel_catalyst_is_never_cut(blocks: Path) -> None:
    cutoff = [{"id": "ni", "per_year": 80, "reason": "tiny", "catalyst": True, "contains": ["Ni"]}]
    _write(blocks, _scope(cutoff=cutoff))
    report = lca_report(blocks)
    assert "cheme.lca-cutoff-never" in _rules(report)
    assert any("never cut" in p for p in lca_gate(blocks, ["cutoff-criteria"]))
    # a spent consumable with metals is taken as a catalyst, flag or not
    spent = {
        "id": "ads",
        "unit": "kg",
        "per_replacement": 100,
        "every_years": 5,
        "metals": {"Ni": 0.1},
        "factor": "nickel",
        "source": "test",
        "disposal": {"route": "vendor", "cutoff": "below 0.01 %", "source": "test"},
    }
    _write(blocks, _scope(consumables=[spent]))
    report = lca_report(blocks)
    (cut,) = report.inventory.dataset.cutoff
    assert cut.catalyst and cut.contains == ["Ni"]
    assert "cheme.lca-cutoff-never" in _rules(report)


def test_end_of_life_does_not_count_a_disposed_source_twice(blocks: Path) -> None:
    _plant_with_steel(blocks)
    steel = STEEL | {
        "disposal": {
            "kind": "recyclable",
            "route": "steel scrap",
            "fraction": 0.9,
            "credit": {"factor": "primary-steel", "source": "avoided primary steel"},
            "source": "90 % recovered",
        }
    }
    scope = _scope(construction=[steel], end_of_life=[_eol()], system_model="substitution")
    _write(blocks, scope)
    report = lca_report(blocks)
    exchanges = _exchanges(report)
    found = [f for f in report.findings if f.rule == "cheme.lca-eol-double"]
    assert len(found) == 1
    assert "end of life steel" in found[0].message and "construction:steel" in found[0].message
    assert "end-of-life:steel" not in exchanges
    # credited once: by the disposal
    assert [k for k in exchanges if k.startswith("avoided:")] == [
        "avoided:disposal.construction.steel"
    ]
    assert exchanges["avoided:disposal.construction.steel"].amount == pytest.approx(-0.09)
    # no disposal on the source: the end_of_life entry counts, with no finding
    scope = _scope(construction=[STEEL], end_of_life=[_eol()], system_model="substitution")
    _write(blocks, scope)
    report = lca_report(blocks)
    assert "cheme.lca-eol-double" not in _rules(report)
    assert "avoided:end-of-life.steel" in _exchanges(report)


def test_a_credit_in_a_background_dataset_with_no_system_model_is_an_info(blocks: Path) -> None:
    _write(blocks, _from_boiler(blocks, _boiler(-0.1)))
    report = lca_report(blocks)
    levels = [f.level for f in report.findings if f.rule == "cheme.lca-cutoff-credit"]
    assert levels == ["info"]
    assert not any("negative inputs" in p for p in lca_gate(blocks, ["cutoff-criteria"]))
    # the same dataset as the plant's own is a warning
    own = LciDataset.model_validate(_boiler(-0.1))
    assert [f.level for f in cutoff_findings(own, "d.yaml")] == ["warning"]


def test_unknown_amounts_do_not_fail_the_gate(blocks: Path) -> None:
    _write(blocks, _scope(cutoff=[{"id": "unknown", "reason": "not known"}]))
    report = lca_report(blocks)
    levels = [f.level for f in report.findings if f.rule == "cheme.lca-cutoff-unchecked"]
    assert levels == ["info"]
    assert lca_gate(blocks, ["cutoff-criteria"]) == []


def test_a_partial_disposal_says_what_happens_to_the_rest(blocks: Path) -> None:
    sieve = SIEVE | {
        "disposal": {
            "route": "landfill",
            "factor": "landfill",
            "fraction": 0.8,
            "source": "spent sieve",
        }
    }
    _write(blocks, _scope(consumables=[sieve]))
    report = lca_report(blocks)
    (info,) = [f for f in report.findings if f.rule == "cheme.lca-disposal-fraction"]
    assert info.level == "info" and "retained or used up" in info.message
    assert _exchanges(report)["disposal:consumable.sieve"].amount == pytest.approx(0.25 * 0.8)
    assert lca_gate(blocks, ["cutoff-criteria"]) == []


# -- post-merge review of pre-release PR 311 -------------------------------------------------------


def test_a_free_by_product_is_a_finding_under_cut_off(blocks: Path) -> None:
    flow = {
        "key": "product:WATER",
        "free": True,
        "source": "sold as cooling-tower make-up",
        "treatment": {"kind": "byproduct", "route": "sold"},
    }
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], flow]))
    report = lca_report(blocks)
    assert "cheme.lca-byproduct-free" in _rules(report)
    assert any("product:WATER" in p for p in lca_gate(blocks, ["cutoff-criteria"]))


def test_a_finite_consumable_in_volume_is_not_silently_undisposed(blocks: Path) -> None:
    bed = {
        "id": "bed",
        "unit": "m3",
        "per_replacement": 2,
        "every_years": 4,
        "factor": "sieve",
        "source": "adsorber bed",
    }
    _write(blocks, _scope(consumables=[bed]))
    levels = {
        f.ids[0]: f.level for f in lca_report(blocks).findings if f.rule == "cheme.lca-disposal"
    }
    assert levels == {"consumable:bed": "warning"}


def test_contains_takes_element_symbols_and_more_flows_are_never_cut() -> None:
    with pytest.raises(ValidationError):
        CutoffFlow(key="cutoff:x", reason="small", contains=["platinum"])
    flow = CutoffFlow(key="cutoff:x", reason="small", amount=0.001, cas="75-69-4")
    assert "CFC-11" in never_cut(flow)
    chromium = CutoffFlow(key="cutoff:x", reason="small", amount=0.001, contains=["Cr"])
    assert "heavy metals" in never_cut(chromium)


def test_energy_routes_of_a_recyclable_are_flagged(blocks: Path) -> None:
    flow = _treatment_flow(kind="recyclable", route="co-processing in a cement kiln")
    _write(blocks, _scope(flows=[*SCOPE["flows"][:2], flow]))
    assert "cheme.lca-recyclable-energy" in _rules(lca_report(blocks))
