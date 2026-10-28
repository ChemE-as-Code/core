"""Emissions the flowsheet does not carry: combustion, equipment leaks, storage tanks, flares,
effluent and non-routine operation (``emission_estimates:``, pre-release issue 176).

The plant is ``examples/process-blocks`` (see ``test_lca.py``): 1000 kg/h feed and 350 kW of
steam make 400 kg/h of product PROD (S3: ethanol 0.95, water 0.05 by mass) and 600 kg/h of
WATER (S5), 8000 h/a. Every factor below is a test number with the source "test value": it is
no published emission factor.
"""

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca.emissions import (
    RULE_ADDED,
    RULE_COUNTS,
    RULE_FACTOR,
    RULE_INCOMPLETE,
    RULE_SIMULATED,
    activity_in,
    factor_set,
    factor_sets,
    leak_counts,
)
from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.quality import default_pedigree
from chemeascode.domains.assessment.lca.report import dataset_yaml, lca_report
from chemeascode.domains.assessment.lca.schemas import (
    DatasetExchange,
    EmissionEstimate,
    EmissionFactor,
    EmissionFactorSet,
    LcaFile,
    LciDataset,
    StudyUncertainty,
)
from chemeascode.domains.assessment.mto import MtoRow, mto_csv
from chemeascode.foundation.schemas.checks import Check

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
HOURS = 8000
TEST = "test value"
AIR = {"compartment": "air", "subcompartment": "unspecified"}

FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq", "elementary": "ipcc2021-gwp100"}],
    "factors": [
        {
            "id": "feed",
            "unit": "kg",
            "values": {"gwp": 0.5},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
        {
            "id": "steam",
            "unit": "MJ",
            "values": {"gwp": 0.07},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
        {
            "id": "wastewater",
            "unit": "kg",
            "values": {"gwp": 0.001},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
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
        {"key": "product:WATER", "factor": "wastewater", "source": "test"},
    ],
    "operation": {"hours_per_year": HOURS, "life_years": 20},
}


def _f(value: float, unit: str, **extra) -> dict:
    return {"value": value, "unit": unit, "source": TEST, **extra}


def _p(value: float, unit: str = "") -> dict:
    return {"value": value, "unit": unit, "source": TEST}


LEAKS = {
    "id": "leaks",
    "method": "equipment-leaks",
    "stream": "S3",
    "components": ["ETOH"],
    "service": "light-liquid",
    "factors": {
        "valve": _f(0.001, "kg/h"),
        "relief-valve": _f(0.002, "kg/h"),
        "flange": _f(0.0005, "kg/h"),
        "pump-seal": _f(10, "g/h"),
    },
    "ldar": {"valve": _p(0.5)},
    "elementary": AIR,
    "source": "average-factor method of the test",
}
#: 10 valves x 0.001 x (1 - 0.5) + 2 relief valves x 0.002 + 20 flanges x 0.0005 + 1 pump seal
#: x 0.010 kg/h
LEAK_TOTAL = 0.005 + 0.004 + 0.010 + 0.010


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    (root / "estimate").mkdir()
    (root / "estimate" / "mto.csv").write_text(
        mto_csv(
            [
                MtoRow("valve", "BallValve", 50, None, "PN16", count=10, quantity=10, unit="ea"),
                MtoRow("valve", "SpringLoadedGlobeSafetyValve", 25, count=2, quantity=2, unit="ea"),
                MtoRow("flange", "weld neck flange", 50, count=20, quantity=20, unit="ea"),
                MtoRow("gasket", "gasket and bolt set", 50, count=20, quantity=20, unit="ea"),
                MtoRow("steel", "HEB300", count=12, quantity=16, unit="t"),
            ]
        )
    )
    _equipment(root, [{"tag": "P-1", "type": "CentrifugalPump"}])
    return root


def _equipment(root: Path, items: list[dict]) -> None:
    (root / "equipment").mkdir(exist_ok=True)
    (root / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": items}, sort_keys=False)
    )


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


def _wastewater(root: Path, category: str = "wastewater") -> None:
    path = root / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    for node in data["products"]:
        if node["id"] == "WATER":
            node["category"] = category
    path.write_text(yaml.safe_dump(data, sort_keys=False))


# -- equipment leaks from the P&ID take-off: the first end-to-end case --------------------------


def test_leaks_count_the_takeoff_and_the_equipment(blocks: Path) -> None:
    _write(blocks, _scope(emission_estimates=[LEAKS]))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    leak = _exchanges(report)["emission:ETOH"]
    assert leak.amount == pytest.approx(LEAK_TOTAL)
    assert leak.type == "emission" and leak.provenance == "estimated"
    assert leak.source.startswith("estimated (equipment-leaks, emission_estimates leaks)")
    assert "10 valve" in leak.source and "LDAR 0.5" in leak.source
    assert leak.cas == "64-17-5" and leak.link.elementary.compartment == "air"
    assert "emission_estimates.leaks" in leak.streams and "S3" in leak.streams
    # the default pedigree of an emission-factor estimate (cheme default pedigree v1)
    assert leak.pedigree.scores[0] == 3 and leak.pedigree.scores[4] == 3
    # the dataset written carries it and loads again
    reread = LciDataset.model_validate(yaml.safe_load(dataset_yaml(report)))
    assert next(e for e in reread.exchanges if e.key == "emission:ETOH").provenance == "estimated"
    assert "provenance: estimated" in dataset_yaml(report)


def test_leak_counts_follow_the_takeoff_mapping() -> None:
    entry = EmissionEstimate.model_validate(LEAKS)
    rows = [
        MtoRow("valve", "GlobeValve", 25, count=3, quantity=3, unit="ea"),
        MtoRow("valve", "SpringLoadedGlobeSafetyValve", 25, count=1, quantity=1, unit="ea"),
        MtoRow("flange", "weld neck flange", 25, pipe_class="PN40", count=8, quantity=8, unit="ea"),
        MtoRow("elbow", "elbow 90", 25, count=4, quantity=4, unit="ea"),
    ]
    from chemeascode.domains.equipment.schemas.equipment import EquipmentItem

    items = [
        EquipmentItem(tag="P-1", type="CentrifugalPump"),
        EquipmentItem(tag="K-1", type="CentrifugalCompressor"),
        EquipmentItem(tag="T-1", type="Tank"),
    ]
    assert leak_counts(entry, rows, items) == {
        "valve": 3,
        "relief-valve": 1,
        "flange": 8,
        "pump-seal": 1,
        "compressor-seal": 1,
    }
    scoped = entry.model_copy(update={"equipment": ["K-*"], "counts": {"flange": 0}})
    assert leak_counts(scoped, rows, items) == {"valve": 3, "relief-valve": 1, "compressor-seal": 1}
    where = EmissionEstimate.model_validate(LEAKS | {"where": {"class": "PN40"}})
    assert leak_counts(where, rows, []) == {"flange": 8}


def test_leaks_scale_with_the_hours_under_pressure(blocks: Path) -> None:
    leaks = LEAKS | {"hours_per_year": _p(8760, "h")}
    _write(blocks, _scope(emission_estimates=[leaks]))
    leak = _exchanges(lca_report(blocks))["emission:ETOH"]
    assert leak.amount == pytest.approx(LEAK_TOTAL * 8760 / HOURS)


def test_counted_components_without_a_factor_are_a_gap(blocks: Path) -> None:
    leaks = copy.deepcopy(LEAKS)
    del leaks["factors"]["flange"]
    _write(blocks, _scope(emission_estimates=[leaks]))
    report = lca_report(blocks)
    found = [f for f in report.findings if f.rule == RULE_COUNTS]
    assert found and "20 flange" in found[0].message
    assert _exchanges(report)["emission:ETOH"].amount == pytest.approx(LEAK_TOTAL - 0.010)


def test_leaks_without_a_takeoff_say_so(blocks: Path) -> None:
    (blocks / "estimate" / "mto.csv").unlink()
    _write(blocks, _scope(emission_estimates=[LEAKS]))
    report = lca_report(blocks)
    assert any(f.rule == RULE_COUNTS and "mto.csv" in f.message for f in report.findings)
    # only the pump seal of the equipment list is counted
    assert _exchanges(report)["emission:ETOH"].amount == pytest.approx(0.010)


# -- combustion, storage, flare, effluent, non-routine ------------------------------------------


COMBUSTION = {
    "id": "heater",
    "method": "combustion",
    "equipment": ["H-101"],
    "activity": {"value": 100, "unit": "kg", "source": "fuel from the duty, test"},
    "lhv": _p(50, "MJ/kg"),
    "factors": {
        "NOx": _f(0.1, "kg/GJ", uncertainty={"gsd2": 1.5, "source": TEST}),
        "CO": _f(20, "g/GJ"),
        "CH4": _f(1, "g/GJ"),
        "N2O": _f(0.1, "g/GJ"),
        "PM10": _f(0.5, "g/GJ"),
    },
    "cas": {"NOx": "10102-44-0", "CO": "630-08-0", "CH4": "74-82-8", "N2O": "10024-97-2"},
    "elementary": AIR,
    "source": "fuel x factor, test",
}


def test_a_fired_heater_reports_its_combustion_emissions(blocks: Path) -> None:
    _equipment(blocks, [{"tag": "H-101", "type": "Furnace"}])
    _write(blocks, _scope(emission_estimates=[COMBUSTION]))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    exchanges = _exchanges(report)
    # 100 kg/h x 50 MJ/kg = 5 GJ/h
    assert exchanges["emission:NOx"].amount == pytest.approx(0.5)
    assert exchanges["emission:CO"].amount == pytest.approx(0.1)
    assert exchanges["emission:CH4"].amount == pytest.approx(0.005)
    assert exchanges["emission:N2O"].amount == pytest.approx(0.0005)
    assert exchanges["emission:PM10"].amount == pytest.approx(0.0025)
    assert exchanges["emission:NOx"].uncertainty.gsd2 == 1.5
    assert exchanges["emission:CH4"].cas == "74-82-8"
    assert all(exchanges[f"emission:{s}"].provenance == "estimated" for s in ("NOx", "CO"))
    # the heater is covered
    assert RULE_INCOMPLETE not in _rules(report)


def test_a_mass_factor_of_an_energy_activity_needs_the_heating_value(blocks: Path) -> None:
    heater = COMBUSTION | {"lhv": None}
    heater.pop("lhv")
    _write(blocks, _scope(emission_estimates=[heater]))
    report = lca_report(blocks)
    assert not report.inventory.dataset
    assert any("needs lhv" in f.message for f in report.findings if f.level == "error")


def test_activity_conversions() -> None:
    assert activity_in(1, "t", "kg", None, None) == (1000, "")
    assert activity_in(100, "kg", "GJ", 50, None)[0] == pytest.approx(5)
    assert activity_in(5, "GJ", "kg", 50, None)[0] == pytest.approx(100)
    assert activity_in(600, "kg", "L", None, 1000)[0] == pytest.approx(600)
    assert activity_in(1, "m3", "kg", None, None)[0] is None


def test_storage_losses_from_a_rate_are_speciated(blocks: Path) -> None:
    tank = {
        "id": "tank",
        "method": "storage-tank",
        "equipment": ["T-1"],
        "stream": "S3",
        "rate": _f(800, "kg/a"),
        "elementary": AIR,
        "source": "working and breathing losses calculated elsewhere, test",
    }
    _equipment(blocks, [{"tag": "T-1", "type": "Tank"}])
    _write(blocks, _scope(emission_estimates=[tank]))
    exchanges = _exchanges(lca_report(blocks))
    # 800 kg/a / 8000 h, 0.95 ethanol and 0.05 water by mass
    assert exchanges["emission:ETOH"].amount == pytest.approx(0.095)
    assert exchanges["emission:H2O"].amount == pytest.approx(0.005)


def test_storage_losses_as_a_fraction_of_the_throughput(blocks: Path) -> None:
    tank = {
        "id": "tank",
        "method": "storage-tank",
        "exchange": "product:PROD",
        "components": ["ETOH"],
        "loss": _p(0.001),
        "elementary": AIR,
        "source": "declared loss fraction, test",
    }
    _write(blocks, _scope(emission_estimates=[tank]))
    assert _exchanges(lca_report(blocks))["emission:ETOH"].amount == pytest.approx(0.4)


def test_a_flare_reports_its_slip_and_products(blocks: Path) -> None:
    flare = {
        "id": "flare",
        "method": "flare",
        "stream": "S3",
        "components": ["ETOH"],
        "efficiency": _p(0.98),
        "factors": {"CO": _f(1, "kg/t")},
        "elementary": AIR,
        "source": "flare slip and products, test",
    }
    _write(blocks, _scope(emission_estimates=[flare]))
    exchanges = _exchanges(lca_report(blocks))
    # (1 - 0.98) x 380 kg/h of ethanol (0.95 of 400 kg/h); the water passes through;
    # 0.4 t/h x 1 kg/t of CO
    assert exchanges["emission:ETOH"].amount == pytest.approx(7.6)
    assert "emission:H2O" not in exchanges
    assert exchanges["emission:CO"].amount == pytest.approx(0.4)


def test_effluent_concentrations_after_treatment(blocks: Path) -> None:
    effluent = {
        "id": "effluent",
        "method": "effluent",
        "exchange": "product:WATER",
        "density": _p(1000, "kg/m3"),
        "factors": {"COD": _f(100, "mg/L"), "N-total": _f(10, "g/m3")},
        "removal": {"COD": _p(0.5)},
        "treatment": "on-site biological treatment",
        "elementary": {"compartment": "water", "subcompartment": "fresh-surface"},
        "source": "concentration x flow, test",
    }
    _write(blocks, _scope(emission_estimates=[effluent]))
    exchanges = _exchanges(lca_report(blocks))
    # 600 kg/h = 0.6 m3/h
    assert exchanges["emission:COD"].amount == pytest.approx(0.03)
    assert exchanges["emission:N-total"].amount == pytest.approx(0.006)
    # COD has no CAS number: no elementary identity is guessed, it waits for a flows: entry
    report = lca_report(blocks)
    assert exchanges["emission:COD"].link is None
    assert any("emission:COD" in f.ids for f in report.findings if f.rule == "cheme.lca-unmapped")


def test_non_routine_operation_is_kept_apart(blocks: Path) -> None:
    upsets = {
        "id": "upsets",
        "method": "non-routine",
        "of": ["leaks"],
        "fraction": _p(0.1),
        "source": "declared start-up and shutdown share, test",
    }
    _write(blocks, _scope(emission_estimates=[LEAKS, upsets]))
    exchanges = _exchanges(lca_report(blocks))
    routine, extra = exchanges["emission:ETOH"], exchanges["emission:ETOH.non-routine"]
    assert routine.amount == pytest.approx(LEAK_TOTAL)
    assert extra.amount == pytest.approx(LEAK_TOTAL * 0.1)
    assert extra.phase == "non-routine" and extra.provenance == "estimated"
    # it takes the routine emission's identity
    assert extra.cas == routine.cas and extra.link.elementary == routine.link.elementary


# -- simulated components are never overwritten without a finding -------------------------------


def _released_water(root: Path) -> dict:
    flows = [
        *SCOPE["flows"][:2],
        {"key": "product:WATER", "emission": True, "source": "test"},
        {"key": "emission:ETOH", "elementary": AIR, "source": "test"},
        {"key": "emission:H2O", "free": True, "source": "test"},
    ]
    return _scope(flows=flows)


def test_an_estimate_does_not_overwrite_a_simulated_emission(blocks: Path) -> None:
    scope = _released_water(blocks)
    scope["emission_estimates"] = [LEAKS]
    _write(blocks, scope)
    report = lca_report(blocks)
    ethanol = _exchanges(report)["emission:ETOH"]
    assert ethanol.amount == pytest.approx(600 * 0.0333333)
    assert ethanol.provenance != "estimated"
    assert RULE_SIMULATED in _rules(report)


def test_an_estimate_may_be_added_to_a_simulated_emission(blocks: Path) -> None:
    scope = _released_water(blocks)
    scope["emission_estimates"] = [LEAKS | {"add": True}]
    _write(blocks, scope)
    report = lca_report(blocks)
    ethanol = _exchanges(report)["emission:ETOH"]
    assert ethanol.amount == pytest.approx(600 * 0.0333333 + LEAK_TOTAL)
    # the weakest of the values summed: the simulated stream's assumed
    assert ethanol.provenance == "assumed" and "equipment-leaks" in ethanol.source
    assert "emission_estimates.leaks" in ethanol.streams
    assert RULE_ADDED in _rules(report) and RULE_SIMULATED not in _rules(report)


# -- factor sets: no factor is packaged, a placeholder refuses ----------------------------------


def test_the_packaged_factor_sets_are_placeholders_without_values() -> None:
    assert factor_sets() == ["emep-eea-guidebook", "epa-ap42", "epa-equipment-leaks"]
    for name in factor_sets():
        found = factor_set(name)
        assert found.status == "placeholder" and found.factors == [] and found.source is None
        assert "TODO" in found.todo and "TODO" in found.licence_note


def test_a_factor_from_a_placeholder_set_refuses_to_run(blocks: Path) -> None:
    heater = copy.deepcopy(COMBUSTION)
    heater["factors"] = {"NOx": {"set": "epa-ap42", "id": "natural-gas-boiler-nox"}}
    _write(blocks, _scope(emission_estimates=[heater]))
    report = lca_report(blocks)
    errors = [f for f in report.findings if f.level == "error"]
    assert errors and errors[0].rule == RULE_FACTOR and "placeholder" in errors[0].message
    assert report.inventory.dataset is None


def test_an_unknown_factor_set_refuses_to_run(blocks: Path) -> None:
    heater = copy.deepcopy(COMBUSTION)
    heater["factors"] = {"NOx": {"set": "nowhere", "id": "x"}}
    _write(blocks, _scope(emission_estimates=[heater]))
    report = lca_report(blocks)
    assert any(f.rule == RULE_FACTOR and "no packaged" in f.message for f in report.findings)


def test_a_factor_set_entry_format() -> None:
    base = {
        "schema": "cheme/lca/v1",
        "kind": "emission_factors",
        "id": "example-set",
        "title": "An example set",
        "provider": "Nobody",
    }
    with pytest.raises(ValidationError, match="todo"):
        EmissionFactorSet.model_validate(base | {"status": "placeholder"})
    with pytest.raises(ValidationError, match="no factors"):
        EmissionFactorSet.model_validate(
            base
            | {
                "status": "placeholder",
                "todo": "read the values from the source",
                "factors": [
                    {
                        "id": "a",
                        "method": "combustion",
                        "applies_to": "gas boiler",
                        "value": 1,
                        "unit": "g/GJ",
                        "table": "table 1",
                    }
                ],
            }
        )
    with pytest.raises(ValidationError, match="redistribution"):
        EmissionFactorSet.model_validate(base | {"status": "verified"})


# -- schema -------------------------------------------------------------------------------------


def test_estimates_state_their_parameters() -> None:
    with pytest.raises(ValidationError, match="service"):
        EmissionEstimate.model_validate({k: v for k, v in LEAKS.items() if k != "service"})
    with pytest.raises(ValidationError, match="component types"):
        EmissionEstimate.model_validate(LEAKS | {"factors": {"gasket": _f(1, "kg/h")}})
    with pytest.raises(ValidationError, match="needs factors"):
        EmissionEstimate.model_validate(COMBUSTION | {"factors": {}})
    with pytest.raises(ValidationError, match="loss or rate"):
        EmissionEstimate.model_validate(
            {"id": "t", "method": "storage-tank", "stream": "S3", "source": TEST}
        )
    with pytest.raises(ValidationError, match="of and fraction"):
        EmissionEstimate.model_validate({"id": "n", "method": "non-routine", "source": TEST})
    with pytest.raises(ValidationError, match="a fraction"):
        EmissionEstimate.model_validate(
            {"id": "f", "method": "flare", "stream": "S3", "efficiency": _p(1.2), "source": TEST}
        )
    with pytest.raises(ValidationError, match="value, unit"):
        EmissionFactor.model_validate({"value": 1, "unit": "kg/GJ"})
    with pytest.raises(ValidationError, match="both set and id"):
        EmissionFactor.model_validate({"set": "epa-ap42"})
    with pytest.raises(ValidationError, match="appears twice"):
        LcaFile.model_validate(
            _scope(
                emission_estimates=[LEAKS],
                emission_exclusions=[
                    {"id": "leaks", "method": "storage-tank", "reason": "no volatile liquid"}
                ],
            )
        )


def test_estimated_is_a_provenance_of_exchanges_and_defaults() -> None:
    exchange = DatasetExchange(
        key="emission:NOx", type="emission", amount=1.0, unit="kg", provenance="estimated"
    )
    dataset = LciDataset.model_validate(
        {
            "schema": "cheme/lci_dataset/v2",
            "kind": "lci_dataset",
            "id": "x",
            "year": 2025,
            "location": "DE",
            "exchanges": [
                {"key": "product:P", "type": "product", "amount": 1, "unit": "kg"},
                exchange.model_dump(),
            ],
        }
    )
    pedigree = default_pedigree(dataset.exchanges[1], dataset)
    assert pedigree.scores == [3, 4, 3, 1, 3]
    assert StudyUncertainty.model_validate({"defaults": {"estimated": {"gsd2": 1.5}}})
    with pytest.raises(ValidationError):
        DatasetExchange(key="emission:NOx", type="emission", amount=1, unit="kg", provenance="x")


# -- completeness: lci-emissions-incomplete -----------------------------------------------------


def test_sources_without_an_estimate_are_a_warning_and_fail_the_gate(blocks: Path) -> None:
    _equipment(
        blocks,
        [
            {"tag": "H-101", "type": "Furnace"},
            {"tag": "T-1", "type": "Tank"},
            {"tag": "P-1", "type": "CentrifugalPump"},
        ],
    )
    _wastewater(blocks)
    scope = _scope()
    scope["flows"][2] = {"key": "product:WATER", "free": True, "source": "test"}
    _write(blocks, scope)
    report = lca_report(blocks)
    found = [f for f in report.findings if f.rule == RULE_INCOMPLETE]
    assert len(found) == 1 and found[0].level == "warning"
    assert set(found[0].ids) == {"H-101", "T-1", "product:WATER"}
    failing = lca_gate(blocks, ["lci-emissions-complete"])
    assert failing and "H-101" in failing[0]


def test_declared_exclusions_and_estimates_complete_the_emissions(blocks: Path) -> None:
    _equipment(blocks, [{"tag": "H-101", "type": "Furnace"}, {"tag": "T-1", "type": "Tank"}])
    _wastewater(blocks)
    scope = _scope(
        emission_estimates=[COMBUSTION],
        emission_exclusions=[
            {
                "id": "tanks",
                "method": "storage-tank",
                "equipment": ["T-*"],
                "reason": "inert cryogenic liquid, no pollutant in the boil-off",
                "source": "test",
            }
        ],
    )
    # the wastewater goes to a treatment background: its emissions are counted there
    _write(blocks, scope)
    report = lca_report(blocks)
    assert RULE_INCOMPLETE not in _rules(report)
    assert lca_gate(blocks, ["lci-emissions-complete"]) == []
    cut = {c.key: c for c in report.inventory.dataset.cutoff}
    assert cut["emission-excluded:tanks"].reason.startswith("inert cryogenic")
    assert any("emission-excluded:tanks" in item for item in report.limitations)


def test_a_wastewater_outlet_released_as_its_components_needs_an_effluent_estimate(
    blocks: Path,
) -> None:
    _wastewater(blocks)
    scope = _released_water(blocks)
    _write(blocks, scope)
    report = lca_report(blocks)
    found = [f for f in report.findings if f.rule == RULE_INCOMPLETE]
    assert found and found[0].ids == ["product:WATER"]
    scope["emission_exclusions"] = [
        {
            "id": "ww",
            "method": "effluent",
            "exchange": "product:WATER",
            "reason": "ethanol and water are its only constituents (counted)",
        }
    ]
    _write(blocks, scope)
    assert RULE_INCOMPLETE not in _rules(lca_report(blocks))


def test_the_gate_requirement_is_a_lca_check() -> None:
    check = Check.model_validate(
        {
            "id": "lca",
            "title": "LCA",
            "stage": "basic",
            "kind": "lca",
            "require": ["lci-emissions-complete"],
        }
    )
    assert check.require == ["lci-emissions-complete"]


# -- review fixes (pre-release issue 176) ----------------------------------------------------------


def test_a_flare_needs_its_combustibles(blocks: Path) -> None:
    flare = {"id": "flare", "method": "flare", "stream": "S3", "efficiency": _p(0.98),
             "elementary": AIR, "source": "flare slip, test"}  # fmt: skip
    _write(blocks, _scope(emission_estimates=[flare]))
    report = lca_report(blocks)
    assert any(
        f.level == "error" and "needs components: (the combustibles)" in f.message
        for f in report.findings
    )


@pytest.mark.parametrize(
    ("lhv", "nox"),
    [(_p(50, "MJ/kg"), 0.5), (_p(50000, "kJ/kg"), 0.5), (_p(50, "GJ/t"), 0.5),
     (_p(13.8889, "kWh/kg"), 0.5)],
)  # fmt: skip
def test_the_heating_value_is_read_in_its_unit(blocks: Path, lhv: dict, nox: float) -> None:
    _write(blocks, _scope(emission_estimates=[COMBUSTION | {"lhv": lhv}]))
    exchanges = _exchanges(lca_report(blocks))
    assert exchanges["emission:NOx"].amount == pytest.approx(nox, rel=1e-4)


def test_an_unknown_unit_of_a_conversion_is_refused(blocks: Path) -> None:
    _write(blocks, _scope(emission_estimates=[COMBUSTION | {"lhv": _p(50, "Btu/lb")}]))
    report = lca_report(blocks)
    assert any(f.level == "error" and "lhv unit 'Btu/lb'" in f.message for f in report.findings)
    effluent = {"id": "effluent", "method": "effluent", "exchange": "product:WATER",
                "density": _p(1.0, "kg/L"), "factors": {"COD": _f(100, "mg/L")},
                "elementary": {"compartment": "water"}, "source": "test"}  # fmt: skip
    _write(blocks, _scope(emission_estimates=[effluent]))
    # 600 kg/h at 1 kg/L = 0.6 m3/h x 100 g/m3
    assert _exchanges(lca_report(blocks))["emission:COD"].amount == pytest.approx(0.06)


def test_two_leak_estimates_counting_the_same_components_are_named(blocks: Path) -> None:
    gas = LEAKS | {"id": "leaks-gas", "service": "gas"}
    _write(blocks, _scope(emission_estimates=[LEAKS, gas]))
    report = lca_report(blocks)
    found = [f for f in report.findings if f.rule == RULE_COUNTS and "both count" in f.message]
    assert len(found) == 1
    assert "leaks and leaks-gas" in found[0].message and "P-1 (pump-seal)" in found[0].message
    # their own components each: no warning
    liquid = LEAKS | {"count_from": ["equipment"]}
    gas = gas | {"count_from": ["mto"]}
    _write(blocks, _scope(emission_estimates=[liquid, gas]))
    assert not any("both count" in f.message for f in lca_report(blocks).findings)


def test_estimated_emissions_are_outside_the_mass_balance(blocks: Path) -> None:
    _write(blocks, _scope(emission_estimates=[COMBUSTION]))
    report = lca_report(blocks)
    nox = _exchanges(report)["emission:NOx"]
    assert nox.balance_exclusion.startswith("estimated (emission_estimates heater)")
    assert report.balance.excluded["emission:NOx"] == nox.balance_exclusion
    assert "emission:NOx" not in report.balance.unknown


@pytest.mark.parametrize("reformer", ["PrimaryReformer", "SteamReformer", "ProcessHeater",
                                      "HeatRecoverySteamGenerator"])  # fmt: skip
def test_fired_reformers_and_heaters_need_an_estimate(blocks: Path, reformer: str) -> None:
    _equipment(blocks, [{"tag": "H-101", "type": reformer}])
    _write(blocks, _scope())
    report = lca_report(blocks)
    assert RULE_INCOMPLETE in _rules(report)
    _write(blocks, _scope(emission_estimates=[COMBUSTION]))
    assert RULE_INCOMPLETE not in _rules(lca_report(blocks))


def test_non_routine_shares_only_what_is_written(blocks: Path) -> None:
    scope = _released_water(blocks)
    upsets = {"id": "upsets", "method": "non-routine", "of": ["leaks"], "fraction": _p(0.1),
              "source": "declared share, test"}  # fmt: skip
    scope["emission_estimates"] = [LEAKS, upsets]
    _write(blocks, scope)
    report = lca_report(blocks)
    # the leaks are left to the simulated ethanol: no share of them is written
    assert "emission:ETOH.non-routine" not in _exchanges(report)
    assert any("of leaks: nothing of it is counted" in f.message for f in report.findings)
    # with add: true they are written, and so is the share
    scope["emission_estimates"] = [LEAKS | {"add": True}, upsets]
    _write(blocks, scope)
    extra = _exchanges(lca_report(blocks))["emission:ETOH.non-routine"]
    assert extra.amount == pytest.approx(0.1 * LEAK_TOTAL)


def test_a_share_of_a_non_routine_estimate_is_named(blocks: Path) -> None:
    upsets = {"id": "upsets", "method": "non-routine", "of": ["leaks"], "fraction": _p(0.1),
              "source": "test"}  # fmt: skip
    nested = upsets | {"id": "nested", "of": ["upsets"]}
    _write(blocks, _scope(emission_estimates=[LEAKS, upsets, nested]))
    report = lca_report(blocks)
    assert any("of upsets: nothing of it is counted: a non-routine" in f.message
               for f in report.findings)  # fmt: skip
