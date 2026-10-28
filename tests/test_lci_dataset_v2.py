"""The LCI dataset contract v2 (``cheme/lci_dataset/v2``): documentation (pre-release issue 179),
elementary flow identities and resources (pre-release issue 175), units and energy carriers
(pre-release issue 177) and data quality per exchange (pre-release issue 178), and the migration of
v1 datasets.

The plant is ``examples/process-blocks`` (see ``test_lca.py``): 1000 kg/h feed and 350 kW of
steam make 400 kg/h of product PROD and 600 kg/h of waste water WATER.
"""

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.lca.documentation import NAMESPACE, missing
from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import dataset_yaml, lca_report
from chemeascode.domains.assessment.lca.schemas import (
    DATASET_SCHEMA,
    Allocation,
    LcaFile,
    LciDataset,
)
from chemeascode.foundation.migrate import lci_dataset_v2, migrate
from chemeascode.foundation.schemas.checks import Check
from chemeascode.foundation.workspace import Workspace

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq", "elementary": "ipcc2021-gwp100"}],
    "factors": [
        {
            "id": i,
            "unit": u,
            "values": {"gwp": v},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        }
        for i, u, v in (("feed", "kg", 0.5), ("steam", "MJ", 0.07), ("power", "kWh", 0.4))
    ],
}
SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
    "location": "NL",
    "year": 2025,
    "technology": "Continuous block process",
    "rights": "CC-BY-4.0",
    "allocation": {"coproducts": ["WATER"], "method": "mass", "source": "test"},
    "operation": {"hours_per_year": 8000, "life_years": 20},
    "flows": [
        {"key": "feed:FEED", "factor": "feed", "source": "test"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
    ],
}
#: What the study declares for the publication minimum (dataset: of lca/lca.yaml).
DOCUMENTED = {
    "uuid": "5b6d0c43-6f5e-4c55-9d1d-6f6f6a9b1c2e",
    "version": "1.0.0",
    "methodology_version": "2026.1",
    "geography": {"description": "One design for a Dutch site", "site": "Rotterdam"},
    "system_model": "cutoff",
    "technology_level": "current",
    "classification": {"isic": "2011", "cpc": "34210"},
    "modelling": {"principle": "attributional"},
    "review": "unreviewed",
    "data_generator": "Test author",
}
#: A hand-written v1 dataset (schema: cheme/lca/v1).
V1 = {
    "schema": "cheme/lca/v1",
    "kind": "lci_dataset",
    "id": "feedstock",
    "basis": "1 batch",
    "exchanges": [
        {"key": "product:FEEDSTOCK", "type": "product", "amount": 1.0, "unit": "kg"},
        {
            "key": "feed:POWER",
            "type": "input",
            "amount": 2.0,
            "unit": "kWh",
            "link": {"factor": "power", "source": "grid"},
        },
    ],
}


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    return root


def _write(root: Path, scope: dict, factors: dict | None = None) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors or FACTORS))


# -- pre-release issue 179: documentation, version, migration --------------------------------------


def test_a_v1_dataset_loads_with_defaults_and_findings(blocks: Path) -> None:
    dataset = LciDataset.model_validate(V1)
    assert dataset.version_of_schema == "v1"
    assert dataset.uuid is None and dataset.review == []
    assert "uuid" in missing(dataset) and "review" in missing(dataset)
    (blocks / "lca" / "datasets").mkdir(parents=True)
    (blocks / "lca" / "datasets" / "feedstock.yaml").write_text(yaml.safe_dump(V1))
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0] = {
        "key": "feed:FEED",
        "dataset": {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"},
        "source": "upstream",
    }
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    rules = {(f.file, f.rule) for f in report.findings}
    assert ("lca/datasets/feedstock.yaml", "cheme.lca-dataset-v1") in rules
    assert ("lca/datasets/feedstock.yaml", "cheme.lca-dataset-undocumented") in rules


def test_an_unknown_dataset_schema_is_refused() -> None:
    with pytest.raises(ValidationError, match="cheme/lci_dataset/v2"):
        LciDataset.model_validate({**V1, "schema": "cheme/lci_dataset/v3"})


def test_cheme_migrate_rewrites_a_hand_written_v1_dataset(blocks: Path) -> None:
    text = "# upstream\nschema: cheme/lca/v1  # v1\n" + yaml.safe_dump(
        {k: v for k, v in V1.items() if k != "schema"}, sort_keys=False
    )
    assert lci_dataset_v2(text, "lci_dataset").startswith(
        "# upstream\nschema: cheme/lci_dataset/v2  # v1\n"
    )
    (blocks / "lca" / "datasets").mkdir(parents=True)
    path = blocks / "lca" / "datasets" / "feedstock.yaml"
    path.write_text(text)
    (found,) = [m for m in migrate(Workspace(blocks), write=True) if m.kind == "lci_dataset"]
    assert (found.kind, found.found, found.target) == ("lci_dataset", "v1", "v2")
    migrated = LciDataset.model_validate(yaml.safe_load(path.read_text()))
    assert migrated.version_of_schema == "v2"
    assert not [m for m in migrate(Workspace(blocks)) if m.kind == "lci_dataset"]


def test_the_derived_dataset_is_v2_with_what_cheme_can_fill_in(blocks: Path) -> None:
    _write(blocks, SCOPE)
    report = lca_report(blocks)
    dataset = report.inventory.dataset
    assert dataset.schema_ == DATASET_SCHEMA
    # stable across versions: from the plant and the dataset id
    import uuid

    assert dataset.uuid == str(uuid.uuid5(NAMESPACE, f"{dataset.title}/{dataset.id}"))
    assert dataset.time.start == 2025 and dataset.valid_until == 2030
    volume = dataset.production_volume
    assert volume.amount == pytest.approx(400 * 8000) and volume.unit == "kg/a"
    assert "mass" in dataset.modelling.multifunctionality
    undocumented = next(f for f in report.findings if f.rule == "cheme.lca-dataset-undocumented")
    assert undocumented.file == "lca/lca.yaml" and "version" in undocumented.ids
    text = dataset_yaml(report)
    again = LciDataset.model_validate(yaml.safe_load(text))
    assert again.uuid == dataset.uuid and again.valid_until == 2030


def test_the_gate_lci_documented(blocks: Path) -> None:
    _write(blocks, SCOPE)
    (problem,) = lca_gate(blocks, ["lci-documented"])
    assert "version" in problem and "classification.isic" in problem
    _write(blocks, {**SCOPE, "dataset": DOCUMENTED})
    assert lca_gate(blocks, ["lci-documented"]) == []
    dataset = lca_report(blocks).inventory.dataset
    assert dataset.uuid == DOCUMENTED["uuid"] and dataset.review[0].type == "none"
    check = Check(id="lca", title="LCA", stage="basic", kind="lca", require=["lci-documented"])
    assert check.require == ["lci-documented"]


def test_documentation_fields_validate() -> None:
    scope = LcaFile.model_validate(
        {
            **SCOPE,
            "allocation": {**SCOPE["allocation"], "deviation": "Euro Chlor PCR"},
            "dataset": {
                **DOCUMENTED,
                "review": {"type": "internal", "reviewer": "A. Reviewer", "date": "2026-10-01"},
                "superseded_by": {"id": "blocks-2", "version": "2.0.0"},
            },
        }
    )
    assert scope.allocation.deviation == "Euro Chlor PCR"
    assert scope.dataset.review[0].reviewer == "A. Reviewer"
    for bad in (
        {"version": "1.0"},
        {"uuid": "not-a-uuid"},
        {"review": [{"type": "panel"}]},  # names its reviewer
        {"classification": {"isic": "20A"}},
        {"time": {"start": 2030}, "valid_until": 2025},
    ):
        with pytest.raises(ValidationError):
            LcaFile.model_validate({**SCOPE, "dataset": bad})
    assert Allocation(deviation="x").deviation == "x"


def test_formulas_must_give_the_amount() -> None:
    dataset = {
        **V1,
        "schema": DATASET_SCHEMA,
        "parameters": [
            {"name": "capacity", "value": 4.0, "unit": "kg"},
            {"name": "power_per_kg", "value": 0.5, "unit": "kWh/kg"},
        ],
    }
    dataset["exchanges"] = copy.deepcopy(V1["exchanges"])
    dataset["exchanges"][1]["formula"] = "capacity * power_per_kg"
    assert LciDataset.model_validate(dataset).exchanges[1].formula
    dataset["exchanges"][1]["formula"] = "capacity * power_per_kg + 1"
    with pytest.raises(ValidationError, match="gives 3"):
        LciDataset.model_validate(dataset)
    dataset["exchanges"][1]["formula"] = "__import__('os')"
    with pytest.raises(ValidationError, match="not arithmetic"):
        LciDataset.model_validate(dataset)


# -- pre-release issue 175: elementary flow identities, sub-compartments, resources ----------------


def _resource_scope() -> dict:
    """FEED taken from nature (river water with ethanol), WATER released to surface water."""
    scope = copy.deepcopy(SCOPE)
    scope["allocation"] = {"method": "none"}
    scope["flows"] = [
        {"key": "feed:FEED", "resource": True, "source": "taken from the river"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
        {
            "key": "resource:H2O",
            "elementary": {"compartment": "resource", "flow": "water-river"},
            "source": "river water",
        },
        {"key": "resource:ETOH", "missing": "no resource flow for ethanol", "source": "test"},
        {"key": "product:WATER", "emission": True, "source": "discharged"},
        {
            "key": "emission:H2O",
            "elementary": {"compartment": "water", "subcompartment": "fresh-surface"},
            "source": "to the river",
        },
        {"key": "emission:ETOH", "elementary": {"compartment": "water"}, "source": "to the river"},
    ]
    return scope


def test_resources_and_emissions_carry_reference_list_identities(blocks: Path) -> None:
    _write(blocks, _resource_scope())
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    by_key = {e.key: e for e in report.inventory.dataset.exchanges}
    feed = by_key["feed:FEED"]
    assert feed.type == "input" and feed.source.startswith("taken from nature")
    water = by_key["resource:H2O"]
    assert water.type == "resource" and water.amount == pytest.approx(600.0)
    ef, bio = water.flow
    assert (ef.list, ef.uuid) == ("ef-3.1", None)  # not verified offline: a TODO, never guessed
    assert bio.uuid == "8c75e7ab-8ab8-41e4-b394-c166ff5b050d"  # Water, river (biosphere3)
    assert bio.categories == ["natural resource", "in water"] and bio.per_unit == 0.001
    released = by_key["emission:H2O"].flow[1]
    assert released.name == "Water" and released.categories == ["water", "surface water"]
    assert by_key["emission:ETOH"].flow == []  # ethanol is not in the curated crosswalk
    rules = {f.rule: f for f in report.findings}
    assert rules["cheme.lca-flow-uuid"].level == "info"
    assert rules["cheme.lca-subcompartment"].ids == ["emission:ETOH"]
    assert "emission:ETOH" in rules["cheme.lca-flow-identity"].ids
    assert "cheme.lca-water-resource" not in rules
    # the inventory shows the resource rows; the feed itself is counted by them
    rows = {r.key: r for r in report.inventory.rows}
    assert rows["feed:FEED"].mapping == "resource" and rows["resource:H2O"].kind == "resource"
    # withdrawal 0.6 m3/h, 0.58 m3/h returned with the waste water
    w = report.water
    assert w["withdrawal"] == pytest.approx(0.6)
    assert w["returned"] == pytest.approx(0.58, rel=1e-5)
    assert w["consumption"] == pytest.approx(0.02, rel=1e-3)
    assert manifest_water(blocks) == w


def manifest_water(root: Path):
    from chemeascode.domains.assessment.lca.report import manifest

    return manifest(lca_report(root))["water"]


def test_a_water_feed_taken_free_is_a_warning(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0] = {"key": "feed:FEED", "free": True, "source": "well"}
    _write(blocks, scope)
    finding = next(f for f in lca_report(blocks).findings if f.rule == "cheme.lca-water-resource")
    assert finding.level == "warning" and finding.ids == ["feed:FEED"]


def test_the_moisture_of_an_air_intake_is_not_a_water_withdrawal() -> None:
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.inventory import _water_findings

    components = {
        "N2": NS(cas="7727-37-9"),
        "O2": NS(cas="7782-44-7"),
        "H2O": NS(cas="7732-18-5"),
    }
    process = NS(
        flowsheet=NS(feeds=[NS(id="AIR"), NS(id="MAKEUP")], products=[]),
        components=lambda: components,
    )
    terminals = {
        # humid ambient air: 1 % water by mass
        "feed:AIR": NS(direction="input", components={"N2": 75.0, "O2": 24.0, "H2O": 1.0}),
        "feed:MAKEUP": NS(direction="input", components={"H2O": 10.0}),
    }
    found = []
    _water_findings(lambda *a: found.append(a), process, terminals, {}, [])
    (finding,) = found
    assert finding[1] == "cheme.lca-water-resource" and finding[-1] == ["feed:MAKEUP"]
    del terminals["feed:MAKEUP"]
    found.clear()
    _water_findings(lambda *a: found.append(a), process, terminals, {}, [])
    assert found == []


def test_a_free_or_unmapped_emission_is_not_given_a_compartment(blocks: Path) -> None:
    scope = _resource_scope()
    # the waste water goes to a drain the study does not map: neither air nor water is guessed
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "emission:H2O"]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    water = next(e for e in report.inventory.dataset.exchanges if e.key == "emission:H2O")
    assert water.flow == []
    identity = next(f for f in report.findings if f.rule == "cheme.lca-flow-identity")
    assert "emission:H2O" in identity.ids and "no receiving compartment" in identity.message
    assert report.water["evaporated"] == 0 and report.water["returned"] == 0


def test_subcompartments_and_origins_validate() -> None:
    from chemeascode.domains.assessment.lca.elementary import identities
    from chemeascode.domains.assessment.lca.schemas import Elementary, FlowMap

    with pytest.raises(ValidationError, match="subcompartment"):
        Elementary(compartment="air", subcompartment="sea")
    with pytest.raises(ValidationError, match="compartment resource"):
        FlowMap(key="resource:H2O", elementary={"compartment": "air"}, source="xyz")
    with pytest.raises(ValidationError, match="only a feed"):
        FlowMap(key="product:P", resource=True, source="xyz")
    luc, _ = identities("124-38-9", Elementary(origin="land-use-change"))
    assert luc[1].name == "Carbon dioxide, from soil or biomass stock"
    stack, _ = identities(
        "7446-09-5", Elementary(subcompartment="non-urban-high-stack")
    )  # SO2 from a high stack is another flow than a ground-level release
    assert stack[1].uuid == "78c3efe4-421c-4d30-82e4-b97ac5124993"
    air, _ = identities("7727-37-9", Elementary(compartment="resource"))
    assert air[1].categories == ["natural resource", "in air"]
    assert identities("124-38-9", Elementary(compartment="water")) == (
        [],
        "CAS 124-38-9 water fossil is not in the crosswalk",
    )


def test_the_crosswalk_records_its_sources_and_only_well_formed_uuids() -> None:
    import re

    from chemeascode.domains.assessment.lca.elementary import BIOSPHERE3_CATEGORIES, crosswalk
    from chemeascode.domains.assessment.lca.schemas import UUID_PATTERN

    data = crosswalk()
    assert set(data["source"]) == {"biosphere3", "ef-3.1"}
    seen = set()
    for flow in data["flows"].values():
        for sub, uuid in flow["biosphere3"]["uuid"].items():
            assert re.match(UUID_PATTERN, uuid) and uuid not in seen
            assert (flow["compartment"], sub) in BIOSPHERE3_CATEGORIES
            seen.add(uuid)
        # an EF 3.1 UUID only as read from the reference package (scripts/fill_ef31_uuids.py),
        # with the package's version in the source; none is guessed
        ef = flow.get("ef-3.1")
        if ef is not None:
            assert "no UUID recorded" not in data["source"]["ef-3.1"]
            for sub, uuid in ef["uuid"].items():
                assert sub in flow["biosphere3"]["uuid"] and re.match(UUID_PATTERN, uuid)
                assert uuid not in seen and ef["categories"][sub]
                seen.add(uuid)


def test_an_ef31_identity_is_used_once_the_crosswalk_records_it(monkeypatch) -> None:
    """pre-release issue 313: identities() gives the EF 3.1 identity where the crosswalk has its
    UUID, and uuid: null (reported) where it has not. The UUID here is a test value, not EF
    3.1's."""
    from chemeascode.domains.assessment.lca import elementary
    from chemeascode.domains.assessment.lca.schemas import Elementary

    data = copy.deepcopy(elementary.crosswalk())
    test_uuid = "00000000-0000-4000-8000-000000000001"
    data["flows"]["sulfur-dioxide"]["ef-3.1"] = {
        "name": "sulfur dioxide (test)",
        "unit": "kg",
        "uuid": {"unspecified": test_uuid},
        "categories": {"unspecified": ["Emissions", "Emissions to air", "test"]},
    }
    monkeypatch.setattr(elementary, "crosswalk", lambda: data)
    found, _ = elementary.identities("7446-09-5", Elementary())
    assert (found[0].list, found[0].uuid, found[0].unit) == ("ef-3.1", test_uuid, "kg")
    assert found[0].categories[-1] == "test" and not elementary.unverified(found)
    high, _ = elementary.identities("7446-09-5", Elementary(subcompartment="non-urban-high-stack"))
    assert high[0].uuid is None and elementary.unverified(high)


# -- pre-release issue 177: units, energy carriers, functional units, product state ----------------


def test_the_lci_units_live_in_foundation_units() -> None:
    from chemeascode.domains.assessment.lca.schemas import FACTOR_UNITS, FUNCTIONAL_UNITS
    from chemeascode.foundation.units import (
        LCI_UNITS,
        UnitError,
        gas_volume_to_kg,
        lci_convert,
    )

    assert FACTOR_UNITS is LCI_UNITS  # one unit table
    assert {"Nm3", "Sm3", "MJ", "kWh", "ea", "kg", "t"} <= set(FUNCTIONAL_UNITS)
    assert lci_convert(1, "GJ", "kWh") == pytest.approx(277.7778, rel=1e-6)
    assert lci_convert(2, "ea*a", "ea*h") == 17520
    assert lci_convert(1, "Sm3", "Nm3") == pytest.approx(273.15 / 288.15)
    # 1 Nm3 of oxygen (31.9988 kg/kmol) at 0 °C and 1.01325 bar
    assert gas_volume_to_kg(1, "Nm3", 31.9988) == pytest.approx(1.42762, rel=1e-5)
    with pytest.raises(UnitError):
        lci_convert(1, "Nm3", "kg")


def test_the_lci_unit_factors_agree_with_pint() -> None:
    pint = pytest.importorskip("pint")
    from chemeascode.foundation.units import LCI_UNITS

    ureg = pint.UnitRegistry()
    spelled = {"kWh": "kilowatt_hour", "MWh": "megawatt_hour", "MJ": "MJ", "GJ": "GJ"}
    for unit, name in spelled.items():
        assert ureg.Quantity(1, name).to("kilowatt_hour").magnitude == pytest.approx(
            LCI_UNITS[unit][1]
        )
    assert ureg.Quantity(1, "liter").to("m**3").magnitude == pytest.approx(LCI_UNITS["L"][1])


def _with_steam_utility(root: Path) -> None:
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    old = "  - {id: STEAM, title: LP steam, ports: [{id: q, direction: out, kind: energy}]}"
    new = (
        "  - {id: STEAM, title: LP steam, ports: [{id: q, direction: out, kind: energy}], "
        "category: utility, utility: {kind: steam, supply_temperature: "
        "{value: 423.15, provenance: assumed}}}"
    )
    assert old in text
    path.write_text(text.replace(old, new))


def test_energy_exchanges_get_their_carrier_from_the_utility(blocks: Path) -> None:
    _write(blocks, SCOPE)
    report = lca_report(blocks)
    steam = next(e for e in report.inventory.dataset.exchanges if e.key == "feed:STEAM")
    assert steam.carrier is None
    assert next(f for f in report.findings if f.rule == "cheme.lca-carrier").ids == ["feed:STEAM"]
    _with_steam_utility(blocks)
    report = lca_report(blocks)
    steam = next(e for e in report.inventory.dataset.exchanges if e.key == "feed:STEAM")
    assert steam.carrier.kind == "steam" and steam.carrier.temperature == pytest.approx(150.0)
    assert not [f for f in report.findings if f.rule == "cheme.lca-carrier"]


def _with_utility(root: Path, utility: str) -> None:
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    old = "  - {id: STEAM, title: LP steam, ports: [{id: q, direction: out, kind: energy}]}"
    new = (
        "  - {id: STEAM, title: LP steam, ports: [{id: q, direction: out, kind: energy}], "
        f"category: utility, utility: {utility}}}"
    )
    assert old in text
    path.write_text(text.replace(old, new))


def test_steam_carriers_get_their_pressure_and_level_from_the_utility(blocks: Path) -> None:
    """pre-release issue 313: the flowsheet's utility level gives the carrier its level, temperature
    and pressure (bar(a); a gauge pressure read against 101.325 kPa)."""
    _write(blocks, SCOPE)
    _with_utility(
        blocks,
        "{kind: steam, level: LP, supply_temperature: {value: 423.15, provenance: assumed}, "
        "pressure: {value: 3.0, unit: 'bar(g)', provenance: assumed}}",
    )
    report = lca_report(blocks)
    steam = next(e for e in report.inventory.dataset.exchanges if e.key == "feed:STEAM")
    assert steam.carrier.kind == "steam" and steam.carrier.level == "LP"
    assert steam.carrier.temperature == pytest.approx(150.0)
    assert steam.carrier.pressure == pytest.approx(4.01325)
    assert not [f for f in report.findings if f.rule.startswith("cheme.lca-carrier")]


def test_a_steam_carrier_without_its_pressure_is_reported(blocks: Path) -> None:
    _write(blocks, SCOPE)
    _with_steam_utility(blocks)  # a supply temperature, no pressure
    report = lca_report(blocks)
    steam = next(e for e in report.inventory.dataset.exchanges if e.key == "feed:STEAM")
    assert steam.carrier.pressure is None  # never derived or guessed
    found = next(f for f in report.findings if f.rule == "cheme.lca-carrier-level")
    assert found.ids == ["feed:STEAM"] and "pressure" in found.message


def test_heat_carriers_get_their_level_and_no_pressure(blocks: Path) -> None:
    _write(blocks, SCOPE)
    _with_utility(
        blocks,
        "{kind: hot_oil, level: HTF-1, supply_temperature: {value: 573.15, provenance: assumed}, "
        "pressure: {value: 500, provenance: assumed}}",
    )
    report = lca_report(blocks)
    heat = next(e for e in report.inventory.dataset.exchanges if e.key == "feed:STEAM")
    assert (heat.carrier.kind, heat.carrier.level) == ("heat", "HTF-1")
    assert heat.carrier.temperature == pytest.approx(300.0)
    assert heat.carrier.pressure is None  # a pressure is a steam carrier's only
    assert not [f for f in report.findings if f.rule == "cheme.lca-carrier-level"]


def test_an_energy_product_carries_the_exergy_of_its_carrier() -> None:
    from chemeascode.domains.assessment.lca.inventory import _carrier_exergy
    from chemeascode.domains.assessment.lca.schemas import Carrier

    assert _carrier_exergy(Carrier(kind="electricity"))[0] == 3600
    mp_steam, how = _carrier_exergy(Carrier(kind="steam", temperature=200.0, pressure=16.0))
    assert mp_steam == pytest.approx(3600 * (1 - 298.15 / 473.15)) and "Carnot" in how
    cold, _ = _carrier_exergy(Carrier(kind="cold", temperature=-30.0))
    assert cold == pytest.approx(3600 * (298.15 / 243.15 - 1))
    assert _carrier_exergy(Carrier(kind="heat"))[0] is None  # no temperature: not guessed


def test_products_carry_their_state(blocks: Path) -> None:
    _write(blocks, SCOPE)
    product = lca_report(blocks).inventory.dataset.product("PROD")
    state = product.state
    assert state.pressure == pytest.approx(1.1) and state.component == "ETOH"
    assert (state.purity, state.basis) == (0.95, "mass")


@pytest.mark.parametrize(
    ("functional_unit", "kg"),
    [
        ({"amount": 1, "unit": "t"}, 1000.0),
        # 1 Nm3 of the product: 0.95/0.05 ethanol/water by mass, ideal gas at 0 °C, 1.01325 bar
        (
            {"amount": 1, "unit": "Nm3"},
            1 / 22.41396954 * 1 / (0.95 / 46.069 + 0.05 / 18.015),
        ),
        # 1 GJ by its energy content (allocation.properties.PROD.energy, 26800 kJ/kg)
        ({"amount": 1, "unit": "GJ"}, 1e6 / 26800),
        ({"amount": 2, "unit": "ea", "kg_per_unit": 0.75, "source": "a drum"}, 1.5),
    ],
)
def test_functional_units_beyond_mass(blocks: Path, functional_unit: dict, kg: float) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["functional_unit"] = {"product": "PROD", **functional_unit}
    scope["allocation"] = {
        "method": "none",
        "properties": {"PROD": {"energy": 26800, "source": "test"}},
    }
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.inventory.amount == pytest.approx(kg, rel=1e-6)
    feed = next(r for r in report.inventory.rows if r.key == "feed:FEED")
    assert feed.quantity == pytest.approx(1000 / 400 * kg, rel=1e-6)


def test_a_functional_unit_that_cannot_be_converted_is_an_error(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["functional_unit"] = {"product": "PROD", "amount": 1, "unit": "ea"}
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    assert any(
        f.rule == "cheme.lca-functional-unit" and "kg_per_unit" in f.message
        for f in report.findings
    )
    with pytest.raises(ValidationError, match="functional unit"):
        LcaFile.model_validate({**SCOPE, "functional_unit": {"product": "P", "unit": "lb"}})


# -- pre-release issue 178: pedigree per exchange, gsd2, data quality rating -----------------------


def _exchange(report, key: str):
    return next(e for e in report.inventory.dataset.exchanges if e.key == key)


def test_every_exchange_gets_a_pedigree_by_the_default_rule(blocks: Path) -> None:
    from chemeascode.domains.assessment.lca.quality import RULE

    _write(blocks, SCOPE)  # NL, 2025
    report = lca_report(blocks)
    for exchange in report.inventory.dataset.exchanges:
        assert exchange.pedigree is not None and exchange.pedigree.rule.startswith(RULE)
        assert exchange.basic_uncertainty is not None
    steam = _exchange(report, "feed:STEAM")  # an assumed duty
    assert steam.pedigree.scores == [4, 4, 1, 1, 2] and steam.basic_uncertainty == 1.05
    # the scores are relative to the declared scope: no location, no year
    _write(blocks, {k: v for k, v in SCOPE.items() if k not in ("location", "year")})
    steam = _exchange(lca_report(blocks), "feed:STEAM")
    assert steam.pedigree.scores[2:4] == [5, 5]
    # a region claimed for one design scores lower than its country
    _write(blocks, {**SCOPE, "location": "RER"})
    assert _exchange(lca_report(blocks), "feed:STEAM").pedigree.scores[3] == 3


def test_the_design_maturity_caps_the_technological_score(blocks: Path) -> None:
    (blocks / "process.yaml").write_text("maturity: concept\n")
    _write(blocks, SCOPE)
    report = lca_report(blocks)
    assert report.maturity == "concept"
    steam = _exchange(report, "feed:STEAM")
    assert steam.pedigree.scores[4] == 3 and "maturity concept" in steam.pedigree.rule


def test_a_pedigree_set_by_hand_records_its_reason() -> None:
    dataset = copy.deepcopy(V1)
    dataset["exchanges"][1]["pedigree"] = {"scores": [1, 2, 1, 1, 1]}
    with pytest.raises(ValidationError, match="records its reason"):
        LciDataset.model_validate(dataset)
    dataset["exchanges"][1]["pedigree"]["reason"] = "metered at the plant, audited 2025"
    exchange = LciDataset.model_validate(dataset).exchanges[1]
    from chemeascode.domains.assessment.lca.quality import gsd2
    from chemeascode.foundation.uncertainty import pedigree_gsd2

    assert gsd2(exchange) == pytest.approx(pedigree_gsd2([1, 2, 1, 1, 1], 1.05))


def test_basic_uncertainty_by_exchange_type() -> None:
    from chemeascode.domains.assessment.lca.quality import basic_uncertainty
    from chemeascode.domains.assessment.lca.schemas import DatasetExchange

    def basic(**fields) -> float:
        return basic_uncertainty(DatasetExchange(amount=1, **fields))[0]

    assert basic(key="feed:POWER", type="input", unit="kWh") == 1.05
    assert basic(key="transport:lorry", type="input", unit="tkm") == 2.0
    assert basic(key="construction:steel", type="input", unit="kg", phase="construction") == 3.0
    assert basic(key="emission:CO", type="emission", unit="kg", cas="630-08-0") == 5.0
    assert basic(key="emission:CH4", type="emission", unit="kg", cas="74-82-8") == 1.5
    # NH3 from combustion or a process (1.2 is the agricultural value)
    assert basic(key="emission:NH3", type="emission", unit="kg", cas="7664-41-7") == 1.5
    # no CAS number: by the crosswalk id the emission is mapped to
    from chemeascode.domains.assessment.lca.schemas import Background

    pm = Background(elementary={"flow": "particulate-matter-pm2.5"}, source="stack")
    assert basic(key="emission:PM", type="emission", unit="kg", link=pm) == 3.0


def test_secondary_data_are_not_of_the_reference_year() -> None:
    from chemeascode.domains.assessment.lca.quality import default_pedigree
    from chemeascode.domains.assessment.lca.schemas import DatasetExchange

    dataset = LciDataset.model_validate({**V1, "schema": DATASET_SCHEMA, "year": 2025})
    own = DatasetExchange(key="feed:A", type="input", amount=1, unit="kg", provenance="given")
    cited = own.model_copy(update={"origin": "literature"})
    assert default_pedigree(own, dataset).scores[2] == 1
    assert default_pedigree(cited, dataset).scores[2] == 3


def test_methane_from_land_use_change_is_a_gap_not_outside_the_method() -> None:
    from chemeascode.domains.assessment.lca.methods import factor, listed

    assert factor("ipcc2021-gwp100", "74-82-8", "air", "land-use-change") is None
    assert listed("ipcc2021-gwp100", "74-82-8", "air")  # a real gap: elementary-origin
    assert not listed("ipcc2021-gwp100", "64-17-5", "air")  # ethanol: outside the method


def test_the_data_quality_rating(blocks: Path) -> None:
    from chemeascode.domains.assessment.lca.quality import rating

    scope = copy.deepcopy(SCOPE)
    del scope["location"]  # an undeclared geography: the weakest indicator
    _write(blocks, scope)
    report = lca_report(blocks)
    q = report.data_quality
    # weighted by the climate contributions of the feed (given) and the steam (assumed)
    assert q.weighted and q.basis == "gwp" and q.exchanges == 2
    assert q.GeR == 5 and q.weakest == "GeR"
    assert q.dqr == pytest.approx((q.TeR + q.GeR + q.TiR) / 3)
    assert q.dqr_pef == pytest.approx((q.TeR + q.GeR + q.TiR + q.P) / 4)
    assert q.primary_share == 0.0  # a design: nothing measured at the plant
    unweighted = rating(report.inventory.dataset)
    assert not unweighted.weighted and unweighted.basis == "unit process (unweighted)"
    from chemeascode.domains.assessment.lca.report import manifest

    assert manifest(report)["data_quality"]["weakest"] == "GeR"


def test_measured_data_count_as_primary(blocks: Path) -> None:
    from chemeascode.domains.assessment.lca.quality import rating, score

    dataset = copy.deepcopy(V1)
    dataset["exchanges"].append(
        {
            "key": "feed:GAS",
            "type": "input",
            "amount": 1.0,
            "unit": "kg",
            "origin": "measured",
            "provenance": "given",
            "link": {"factor": "gas", "source": "meter"},
        }
    )
    scored = score(LciDataset.model_validate(dataset))
    found = rating(scored, {"feed:POWER": 1.0, "feed:GAS": 3.0}, "gwp")
    assert found.primary_share == pytest.approx(0.75)


def test_coverage_prints_the_rating_and_monte_carlo_uses_the_pedigree(
    blocks: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    _write(blocks, {**SCOPE, "uncertainty": {"iterations": 200, "seed": 1}})
    report = lca_report(blocks)
    # no exchange has its own uncertainty and the study gives no defaults: every one varies by
    # its pedigree, the co-product too (the allocation shares move)
    assert report.uncertainty.bases == {
        "amount:feed:FEED": "pedigree",
        "amount:feed:STEAM": "pedigree",
        "amount:product:WATER": "pedigree",
    }
    monkeypatch.chdir(blocks)
    result = CliRunner().invoke(app, ["assess", "lca", "--coverage"])
    assert result.exit_code == 0, result.output
    assert "data quality (gwp, 2 exchanges): DQR" in result.output
    assert "primary data share 0%" in result.output


def test_an_energy_product_as_the_functional_unit(blocks: Path) -> None:
    """50 kW of exported electricity EL beside PROD and WATER, 1 MWh of EL, by exergy."""
    from chemeascode.domains.assessment.lca.scenarios import compare_cases

    path = blocks / "process" / "flowsheet.yaml"
    text = path.read_text()
    for old, new in (
        (
            "  - {id: WATER, title: Waste water, ports: [{id: in, direction: in}]}",
            "  - {id: WATER, title: Waste water, ports: [{id: in, direction: in}]}\n"
            "  - {id: EL, title: Power export, ports: [{id: in, direction: in, kind: energy}], "
            "category: utility, utility: {kind: electricity}}",
        ),
        (
            "      - {id: bottom, direction: out}",
            "      - {id: bottom, direction: out}\n"
            "      - {id: power, direction: out, kind: energy}",
        ),
    ):
        assert old in text
        text = text.replace(old, new)
    text += (
        "  - id: Q2\n    title: Power export\n    kind: energy\n    from: SEP.power\n"
        "    to: EL.in\n    state:\n      design:\n        duty: {value: 50, provenance: assumed}\n"
    )
    path.write_text(text)
    scope = {
        **SCOPE,
        "functional_unit": {"product": "EL", "amount": 1, "unit": "MWh"},
        "allocation": {
            "coproducts": ["PROD", "WATER"],
            "method": "exergy",
            "source": "test",
            "properties": {
                "PROD": {"exergy": 29000, "source": "test"},
                "WATER": {"exergy": 50, "source": "test"},
            },
        },
    }
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    inventory = report.inventory
    assert inventory.amount == pytest.approx(1000.0)  # kWh
    # electricity's exergy is its energy: 50 kW x 3600 kJ/kWh against the material products'
    share = 50 * 3600 / (400 * 29000 + 600 * 50 + 50 * 3600)
    assert inventory.shares["EL"] == pytest.approx(share)
    feed = next(r for r in inventory.rows if r.key == "feed:FEED")
    assert feed.quantity == pytest.approx(1000 / 50 * 1000 * share)  # about 304.8 kg/MWh
    (row,) = compare_cases(blocks)[0]
    assert row["product"]["unit"] == "kWh/h"
    assert row["per_unit"]["feed:FEED"] == {"amount": 20.0, "unit": "kg/kWh"}
    assert row["per_unit"]["feed:STEAM"]["unit"] == "kWh/kWh"
