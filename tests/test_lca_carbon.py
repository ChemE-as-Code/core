"""Carbon accounting: carbon content, fossil and biogenic carbon traced
through the inputs, CCU and CCS, the PCF breakdown and the PACT export.

Two plants:

- methanol from captured CO2 (CO2 + 3 H2 -> CH3OH + H2O), 1 t/h of methanol: 1393.5 kg/h CO2
  and 192 kg/h H2 in; 1000 kg/h methanol, 562.2 kg/h water and a purge of 20 kg/h CO2 and
  3.25 kg/h H2 out. Carbon: 1393.5 x 12.011/44.009 = 380.3 kg C/h in, 374.9 (methanol) +
  5.5 (purge) out. Factors (test values): captured CO2 0.15, H2 1.0 kg CO2-eq/kg;
- bio-ethanol: ``examples/process-blocks`` (400 kg/h of 95 % ethanol from a 40 % ethanol feed),
  the feed declared biogenic; 1 t of product is 2.5 h.
"""

import datetime as dt
import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.carbon import CO2_PER_C, ELEMENTARY_CARBON, trace
from chemeascode.domains.assessment.lca.pact import ProductFootprint, footprint, validate
from chemeascode.domains.assessment.lca.report import lca_report, outputs, results_csv
from chemeascode.domains.assessment.lca.schemas import (
    CarbonAccounting,
    DatasetExchange,
    FlowMap,
    LciDataset,
)
from chemeascode.interfaces.cli import app

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
C_CO2 = ELEMENTARY_CARBON["124-38-9"][1]
C_MEOH = 12.011 / (12.011 + 4 * 1.008 + 15.999)
C_ETOH = 2 * 12.011 / (2 * 12.011 + 6 * 1.008 + 15.999)

MATERIALS = {
    "schema": "cheme/process/v1",
    "kind": "materials",
    "components": [
        {"id": "CO2", "name": "Carbon dioxide", "formula": "CO2", "cas": "124-38-9",
         "molar_mass": 44.009},
        {"id": "H2", "name": "Hydrogen", "formula": "H2", "cas": "1333-74-0", "molar_mass": 2.016},
        {"id": "MEOH", "name": "Methanol", "formula": "CH4O", "cas": "67-56-1",
         "molar_mass": 32.042},
        {"id": "H2O", "name": "Water", "formula": "H2O", "cas": "7732-18-5", "molar_mass": 18.015},
    ],
    "templates": [{"id": "all", "title": "Synthesis", "components": ["CO2", "H2", "MEOH", "H2O"]}],
}  # fmt: skip


def _stream(id_: str, src: str, dst: str, flow: float, composition: dict) -> dict:
    return {
        "id": id_,
        "from": src,
        "to": dst,
        "template": "all",
        "state": {
            "design": {
                "flow": {"value": flow, "basis": "mass", "provenance": "given", "source": "test"},
                "composition": {
                    "basis": "mass_fraction",
                    "values": composition,
                    "provenance": "given",
                    "source": "test",
                },
            }
        },
    }


FLOWSHEET = {
    "schema": "cheme/process/v1",
    "kind": "flowsheet",
    "title": "Methanol from captured CO2",
    "units": {"pressure": "kPa(a)", "temperature": "K", "flow": "kg/h", "duty": "kW"},
    "cases": [{"id": "design", "description": "Design", "default": True}],
    "feeds": [
        {"id": "CO2", "title": "Captured CO2", "ports": [{"id": "out", "direction": "out"}]},
        {"id": "H2", "title": "Hydrogen", "ports": [{"id": "out", "direction": "out"}]},
    ],
    "products": [
        {"id": p, "title": p, "category": c, "ports": [{"id": "in", "direction": "in"}]}
        for p, c in (("MEOH", "product"), ("WATER", "wastewater"), ("PURGE", "off_gas"))
    ],
    "blocks": [
        {
            "id": "R",
            "title": "Synthesis",
            "class": "ReactingChemicals",
            "ports": [
                {"id": "co2", "direction": "in"},
                {"id": "h2", "direction": "in"},
                {"id": "meoh", "direction": "out"},
                {"id": "water", "direction": "out"},
                {"id": "purge", "direction": "out"},
            ],
        }
    ],
    "streams": [
        _stream("S1", "CO2.out", "R.co2", 1393.5, {"CO2": 1.0}),
        _stream("S2", "H2.out", "R.h2", 192.0, {"H2": 1.0}),
        _stream("S3", "R.meoh", "MEOH.in", 1000.0, {"MEOH": 1.0}),
        _stream("S4", "R.water", "WATER.in", 562.2, {"H2O": 1.0}),
        _stream("S5", "R.purge", "PURGE.in", 23.25, {"CO2": 20 / 23.25, "H2": 3.25 / 23.25}),
    ],
}


def _factor(id_: str, gwp: float) -> dict:
    return {"id": id_, "unit": "kg", "values": {"climate": gwp}, "status": "ASSUMED",
            "source": "test", "year": 2025}  # fmt: skip


FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [
        {"id": "climate", "unit": "kg CO2-eq", "method": "IPCC 2021 GWP100",
         "elementary": "ipcc2021-gwp100"}
    ],
    "factors": [_factor("capture", 0.15), _factor("h2", 1.0), _factor("feed", 0.5),
                _factor("storage", 0.02)],
}  # fmt: skip
PACT = {
    "company_name": "Test plant",
    "company_ids": ["urn:pact:company:customcode:buyer-assigned:test"],
    "product_ids": ["urn:pact:product:cas:67-56-1"],
    "product_name": "Methanol from captured CO2",
    "cpc": "34110",
    # the fixture builds no plant, transport or construction: a stated estimate (test only)
    "exempted_emissions_percent": 1.0,
    "exempted_emissions_description": "ASSUMED for the test: plant, transport and EoL left out.",
}


def _scope(source: str = "direct-air-capture", **accounting) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lca",
        "functional_unit": {"product": "MEOH", "amount": 1, "unit": "t"},
        "year": 2025,
        "location": "DE",
        "allocation": {"method": "none"},
        "flows": [
            {"key": "feed:CO2", "factor": "capture", "co2_source": source, "source": "test"},
            {"key": "feed:H2", "factor": "h2", "source": "test"},
            {"key": "product:WATER", "free": True, "source": "test"},
            {"key": "product:PURGE", "emission": True, "source": "test"},
            {"key": "emission:CO2", "elementary": {"compartment": "air"}, "source": "test"},
            {"key": "emission:H2", "free": True, "source": "test"},
            # in the template, not in the purge (0 kg/h)
            {"key": "emission:H2O", "free": True, "source": "test"},
            {"key": "emission:MEOH", "free": True, "source": "test"},
        ],
        "carbon_accounting": {"pact": PACT, **accounting},
    }


def _write(root: Path, scope: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(FACTORS, sort_keys=False))


@pytest.fixture
def methanol(tmp_path: Path) -> Path:
    root = tmp_path / "methanol"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text(yaml.safe_dump({"name": "methanol"}))
    (root / "process" / "materials.yaml").write_text(yaml.safe_dump(MATERIALS))
    (root / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(FLOWSHEET, sort_keys=False))
    _write(root, _scope())
    return root


def _loaded(root: Path):
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings if f.level == "error"]
    return report


def test_methanol_from_air_captured_co2(methanol: Path) -> None:
    report = _loaded(methanol)
    carbon = report.inventory.carbon
    assert carbon.total("in") == pytest.approx(1393.5 * C_CO2)
    assert carbon.residual == pytest.approx(0, abs=0.05)
    assert carbon.fraction == pytest.approx(1.0)  # direct air capture: non-fossil
    product = report.inventory.dataset.product("MEOH")
    assert product.carbon.total == pytest.approx(C_MEOH, rel=1e-6)
    assert product.carbon.biogenic_fraction == pytest.approx(1.0)
    # the purge's CO2 is non-fossil: one biogenic emission, characterised 0
    emission = next(e for e in report.inventory.dataset.exchanges if e.key == "emission:CO2")
    assert emission.link.elementary.origin == "biogenic"
    assert emission.flow[1].name == "Carbon dioxide, non-fossil"
    pcf = report.pcf
    assert pcf.fossil == pytest.approx(1393.5 * 0.15 + 192.0)
    assert pcf.excluding == pytest.approx(pcf.fossil)
    assert pcf.biogenic_carbon == pytest.approx(1000 * C_MEOH, rel=1e-6)
    assert pcf.fossil_carbon == pytest.approx(0, abs=1e-9)
    assert pcf.withdrawal == pytest.approx(-1000 * C_MEOH * CO2_PER_C, rel=1e-6)
    assert pcf.including == pytest.approx(pcf.excluding + pcf.withdrawal)
    assert pcf.headline == pcf.including  # -1/+1 (TfS v3)
    assert pcf.biogenic_co2_emitted == pytest.approx(20.0)
    assert not pcf.problems
    rules = {f.rule for f in report.findings}
    assert "cheme.lca-carbon-balance" not in rules
    assert "cheme.lca-carbon-biogenic" not in rules


def test_a_fossil_point_source_is_never_a_removal(methanol: Path) -> None:
    _write(methanol, _scope("fossil-point-source"))
    report = _loaded(methanol)
    pcf = report.pcf
    assert report.inventory.carbon.fraction == pytest.approx(0.0)
    assert pcf.biogenic_carbon == 0 and pcf.withdrawal == 0
    assert pcf.fossil_carbon == pytest.approx(1000 * C_MEOH, rel=1e-6)
    # the purge's CO2 is fossil and counts
    assert pcf.fossil == pytest.approx(1393.5 * 0.15 + 192.0 + 20.0)
    assert pcf.including == pytest.approx(pcf.excluding)
    with pytest.raises(ValueError, match="never a removal"):
        DatasetExchange(
            key="feed:CO2",
            type="input",
            amount=1,
            unit="kg",
            co2_source="fossil-point-source",
            carbon={"biogenic_fraction": 0.5},
        )


def test_ccu_upstream_rule_counts_captured_carbon_as_fossil(methanol: Path) -> None:
    _write(methanol, _scope("biogenic-point-source", ccu_rule="upstream"))
    report = _loaded(methanol)
    assert report.pcf.biogenic_carbon == 0
    assert report.pcf.fossil == pytest.approx(1393.5 * 0.15 + 192.0 + 20.0)


def test_ccu_double_count_is_reported(methanol: Path) -> None:
    factors = json.loads(json.dumps(FACTORS))
    factors["factors"][0]["values"]["climate"] = -0.8  # a removal claimed by the capture
    _write(methanol, _scope())
    (methanol / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    report = _loaded(methanol)
    assert "cheme.lca-ccu-double-count" in {f.rule for f in report.findings}


def test_ccs_output_and_its_permanence(methanol: Path) -> None:
    scope = _scope("biogenic-point-source")
    purge = next(f for f in scope["flows"] if f["key"] == "product:PURGE")
    purge.pop("emission")
    purge.update(factor="storage", storage={"permanence": "saline aquifer, monitored (test)"})
    scope["flows"] = [f for f in scope["flows"] if not f["key"].startswith("emission:")]
    _write(methanol, scope)
    report = _loaded(methanol)
    stored = report.inventory.dataset.product("PURGE") or next(
        e for e in report.inventory.dataset.exchanges if e.key == "product:PURGE"
    )
    assert stored.type == "output" and stored.storage is not None
    pcf = report.pcf
    assert pcf.stored_co2 == pytest.approx(20.0, rel=1e-6)
    assert pcf.stored_biogenic == pytest.approx(-20.0, rel=1e-6)  # BECCS: a removal
    assert pcf.including == pytest.approx(pcf.excluding + pcf.withdrawal - 20.0, rel=1e-6)
    scope["carbon_accounting"]["ccs"] = "emitted"
    _write(methanol, scope)
    report = _loaded(methanol)
    assert report.pcf.stored_biogenic == 0
    assert report.pcf.biogenic_co2_emitted == pytest.approx(20.0, rel=1e-6)
    assert "cheme.lca-ccs-emitted" in {f.rule for f in report.findings}
    with pytest.raises(ValueError, match="only a product sent to storage"):
        FlowMap(key="feed:CO2", factor="x", source="test", storage={"permanence": "abc"})


def test_carbon_balance_gap_is_reported(methanol: Path) -> None:
    scope = _scope()
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "product:PURGE"]
    scope["flows"].append({"key": "product:PURGE", "free": True, "source": "test"})
    scope["carbon_accounting"]["content"] = {"product:PURGE": {"total": 0.0, "source": "wrong"}}
    _write(methanol, scope)
    report = _loaded(methanol)
    found = [f for f in report.findings if f.rule == "cheme.lca-carbon-balance"]
    assert found and "residual +5.4" in found[0].message


def test_pcf_in_results_and_pact_export(methanol: Path) -> None:
    report = _loaded(methanol)
    files = outputs(report)
    assert "## Product carbon footprint per 1 t MEOH" in files["lca/results.md"]
    rows = [r for r in results_csv(report).splitlines() if r.startswith("baseline,pcf,")]
    assert any(",including," in r for r in rows) and any(",biogenic_carbon," in r for r in rows)
    assert json.loads(report.to_json())["carbon"]["pcf"]["headline"] == pytest.approx(
        report.pcf.including
    )
    document, problems = footprint(report, dt.datetime(2026, 10, 25, tzinfo=dt.UTC))
    assert not problems, problems
    assert validate(document) == []
    ProductFootprint.model_validate(document)
    pcf = document["pcf"]
    assert pcf["declaredUnit"] == "kilogram" and pcf["unitaryProductAmount"] == "1000"
    assert float(pcf["pCfExcludingBiogenic"]) == pytest.approx(report.pcf.excluding / 1000, 1e-6)
    assert float(pcf["biogenicCarbonContent"]) == pytest.approx(C_MEOH, rel=1e-5)
    assert float(pcf["biogenicCarbonWithdrawal"]) < 0
    assert pcf["characterizationFactors"] == "AR6" and pcf["geographyCountry"] == "DE"
    assert 1 <= pcf["dqi"]["technologicalDQR"] <= 3
    # deterministic id: the same product and dataset give the same footprint id
    again, _ = footprint(report, dt.datetime(2027, 1, 1, tzinfo=dt.UTC))
    assert again["id"] == document["id"]
    broken = json.loads(json.dumps(document))
    broken["pcf"]["biogenicCarbonWithdrawal"] = "1.5"
    broken["companyIds"] = ["not-a-urn"]
    assert len(validate(broken)) == 2


def test_pact_needs_identity_and_no_gaps(methanol: Path) -> None:
    scope = _scope()
    del scope["carbon_accounting"]["pact"]
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "feed:H2"]
    _write(methanol, scope)
    report = _loaded(methanol)
    document, problems = footprint(report, dt.datetime(2026, 1, 1, tzinfo=dt.UTC))
    assert document is None
    assert any("carbon_accounting.pact" in p for p in problems)
    assert any("gaps" in p for p in problems)


def test_cli_writes_pact(methanol: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(methanol)
    out = methanol / "pact.json"
    result = CliRunner().invoke(app, ["assess", "lca", "--pact", str(out)])
    assert result.exit_code == 0, result.output
    assert validate(json.loads(out.read_text())) == []


def test_without_carbon_accounting_nothing_changes(methanol: Path) -> None:
    scope = _scope()
    del scope["carbon_accounting"]
    for flow in scope["flows"]:
        flow.pop("co2_source", None)
    _write(methanol, scope)
    report = _loaded(methanol)
    assert report.pcf is None and report.inventory.carbon is None
    assert all(e.carbon is None for e in report.inventory.dataset.exchanges)
    assert "Product carbon footprint" not in outputs(report)["lca/results.md"]


# -- bio-based ------------------------------------------------------------------------------------


def _bio_scope(fraction: float, **accounting) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lca",
        "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
        "year": 2025,
        "allocation": {"method": "none"},
        "flows": [
            {"key": "feed:FEED", "factor": "feed", "source": "test"},
            {"key": "feed:STEAM", "free": True, "source": "test"},
            {"key": "product:WATER", "free": True, "source": "test"},
        ],
        "carbon_accounting": {
            "content": {"feed:FEED": {"biogenic_fraction": fraction, "source": "fermentation"}},
            **accounting,
        },
    }


@pytest.fixture
def ethanol(tmp_path: Path) -> Path:
    root = tmp_path / "ethanol"
    shutil.copytree(EXAMPLE, root)
    _write(root, _bio_scope(1.0))
    return root


def test_bio_based_ethanol(ethanol: Path) -> None:
    report = _loaded(ethanol)
    carbon = report.inventory.carbon
    assert carbon.total("in", True) == pytest.approx(400 * C_ETOH, rel=1e-6)
    assert carbon.residual == pytest.approx(0, abs=0.01)
    pcf = report.pcf
    assert pcf.excluding == pytest.approx(1000 * 0.5 * 2.5)  # the feed's factor, 2.5 h
    assert pcf.product_carbon == pytest.approx(2.5 * 380 * C_ETOH, rel=1e-5)
    assert pcf.biogenic_carbon == pytest.approx(pcf.product_carbon)
    # the waste water leaves with 10.4 kg C/h of ethanol: its uptake is booked too
    water = 2.5 * carbon.flow("product:WATER").biogenic
    assert pcf.withdrawal_other == pytest.approx(-CO2_PER_C * water)
    assert pcf.including == pytest.approx(pcf.excluding - CO2_PER_C * (pcf.biogenic_carbon + water))
    md = outputs(report)["lca/results.md"]
    assert "biogenic carbon content of the product" in md
    # zero-zero states the PCF excluding biogenic CO2, and still reports the content
    _write(ethanol, _bio_scope(1.0, biogenic="zero-zero"))
    report = _loaded(ethanol)
    assert report.pcf.headline == report.pcf.excluding
    assert report.pcf.biogenic_carbon > 0


def test_a_mixed_feed_and_an_undeclared_one(ethanol: Path) -> None:
    _write(ethanol, _bio_scope(0.4))
    report = _loaded(ethanol)
    assert report.pcf.biogenic_carbon == pytest.approx(0.4 * report.pcf.product_carbon)
    scope = _bio_scope(1.0)
    scope["carbon_accounting"]["content"] = {}
    _write(ethanol, scope)
    report = _loaded(ethanol)
    assert report.pcf.biogenic_carbon == 0
    assert "cheme.lca-carbon-assumed-fossil" in {f.rule for f in report.findings}


def test_declared_product_content_that_the_inputs_cannot_give(ethanol: Path) -> None:
    scope = _bio_scope(0.2)
    scope["carbon_accounting"]["content"]["product:PROD"] = {"biogenic_fraction": 1.0}
    _write(ethanol, scope)
    report = _loaded(ethanol)
    assert "cheme.lca-carbon-biogenic" in {f.rule for f in report.findings}


# -- the carbon-flow matrix over a chain of datasets ---------------------------------------------


def _dataset(id_: str, exchanges: list[dict]) -> LciDataset:
    return LciDataset.model_validate(
        {"schema": "cheme/lci_dataset/v2", "kind": "lci_dataset", "id": id_,
         "exchanges": exchanges}
    )  # fmt: skip


def _co2(amount: float, origin: str = "fossil") -> dict:
    return {"key": "emission:CO2", "type": "emission", "amount": amount, "unit": "kg",
            "cas": "124-38-9", "link": {"elementary": {"compartment": "air", "origin": origin},
                                        "source": "test"}}  # fmt: skip


def test_trace_through_a_chain_with_a_loop() -> None:
    # A: biomass (50 kg C, biogenic) and 50 kg C of B's product -> its product (100 kg C)
    # B: 100 kg C of A's product, 100 kg C natural gas -> product (100 kg C) and CO2 (100 kg C)
    a = _dataset(
        "a",
        [
            {"key": "product:A", "type": "product", "amount": 100, "unit": "kg",
             "carbon": {"total": 1.0}},
            {"key": "feed:BIOMASS", "type": "input", "amount": 100, "unit": "kg",
             "carbon": {"total": 0.5, "biogenic_fraction": 1.0}},
            {"key": "feed:B", "type": "input", "amount": 50, "unit": "kg",
             "link": {"dataset": {"path": "b.yaml", "product": "B"}, "source": "test"}},
        ],
    )  # fmt: skip
    b = _dataset(
        "b",
        [
            {"key": "product:B", "type": "product", "amount": 100, "unit": "kg",
             "carbon": {"total": 1.0}},
            {"key": "feed:A", "type": "input", "amount": 100, "unit": "kg",
             "link": {"dataset": {"path": "a.yaml", "product": "A"}, "source": "test"}},
            {"key": "feed:GAS", "type": "input", "amount": 100, "unit": "kg",
             "carbon": {"total": 1.0}},
            _co2(100 * (44.009 / 12.011)),
        ],
    )  # fmt: skip
    datasets = {"a.yaml": a, "b.yaml": b}
    traced = trace(a, CarbonAccounting(), datasets.__getitem__, path="a.yaml")
    # r_a = (50 + 50 r_b) / 100, r_b = (100 r_a) / 200 -> r_a = 2/3, r_b = 1/3
    assert traced.fraction == pytest.approx(2 / 3)
    assert traced.upstream["b.yaml#B"] == pytest.approx(1 / 3)
    traced_b = trace(b, CarbonAccounting(), datasets.__getitem__, path="b.yaml")
    assert traced_b.fraction == pytest.approx(1 / 3)
    co2 = traced_b.flow("emission:CO2")
    assert co2.fraction == pytest.approx(1 / 3)
    assert traced_b.residual == pytest.approx(0, abs=1e-6)
    missing = trace(b, CarbonAccounting(), lambda p: f"no dataset {p}", path="b.yaml")
    assert missing.problems and missing.fraction == pytest.approx(0)


def test_pcf_lines_by_origin() -> None:
    """Background contributions are fossil; emissions count by their origin; biogenic CO2 is
    neither in the PCF excluding biogenic CO2 nor in the fossil line."""
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.carbon import pcf
    from chemeascode.domains.assessment.lca.schemas import Background, Elementary

    def emission(origin: str) -> Background:
        return Background(elementary=Elementary(compartment="air", origin=origin), source="test")

    dataset = _dataset(
        "d",
        [{"key": "product:P", "type": "product", "amount": 10, "unit": "kg",
          "carbon": {"total": 0.5, "biogenic_fraction": 0.6}}],
    )  # fmt: skip
    rows = [
        NS(key="emission:CH4", cas="74-82-8", kind="emission", phase="operation", quantity=1.0),
        NS(key="emission:CO2", cas="124-38-9", kind="emission", phase="operation", quantity=4.0),
        NS(key="emission:CO2.biogenic", cas="124-38-9", kind="emission", phase="operation",
           quantity=2.0),
        NS(key="emission:CO2.luc", cas="124-38-9", kind="emission", phase="operation",
           quantity=1.5),
        NS(key="feed:X", cas=None, kind="material", phase="operation", quantity=3.0),
    ]  # fmt: skip
    inventory = NS(
        functional_unit="10 kg P",
        rows=rows,
        amount=10.0,
        dataset=dataset,
        backgrounds={
            "emission:CH4": emission("biogenic"),
            "emission:CO2": emission("fossil"),
            "emission:CO2.biogenic": emission("biogenic"),
            "emission:CO2.luc": emission("land-use-change"),
            "feed:X": Background(factor="x", source="test"),
        },
    )
    impacts = [
        NS(key="emission:CH4", value=27.0),
        NS(key="emission:CO2", value=4.0),
        NS(key="emission:CO2.biogenic", value=0.0),
        NS(key="emission:CO2.luc", value=1.5),
        NS(key="feed:X", value=6.0),
    ]
    category = NS(id="climate", unit="kg CO2-eq")
    carbon = trace(dataset, CarbonAccounting())
    found = pcf(inventory, impacts, category, CarbonAccounting(), carbon, "P")
    assert found.fossil == pytest.approx(10.0) and found.background == ["feed:X"]
    assert found.other_biogenic == pytest.approx(27.0) and found.dluc == pytest.approx(1.5)
    assert found.excluding == pytest.approx(38.5)
    assert found.biogenic_co2_emitted == pytest.approx(2.0)
    assert found.biogenic_carbon == pytest.approx(3.0)  # 10 kg x 0.5 x 0.6, declared
    assert found.fossil_carbon == pytest.approx(2.0)
    assert found.including == pytest.approx(38.5 - 3.0 * CO2_PER_C)


# -- review fixes ---------------------------------------------------------------------------------


def _input(key: str, type_: str = "input", cas: str | None = None, **carbon) -> dict:
    found = {
        "key": key,
        "type": type_,
        "amount": 10,
        "unit": "kg",
        "carbon": {"total": 0.5, **carbon},
    }
    if cas:
        found["cas"] = cas
    return found


def _product(total: float = 0.5) -> dict:
    return {"key": "product:P", "type": "product", "amount": 10, "unit": "kg",
            "carbon": {"total": total}}  # fmt: skip


def test_a_declared_fraction_is_read_before_the_resource_branch() -> None:
    wood = _input("resource:WOOD", "resource", biogenic_fraction=1.0)
    traced = trace(_dataset("d", [_product(), wood]), CarbonAccounting())
    assert traced.fraction == pytest.approx(1.0)
    assert traced.flow("resource:WOOD").how == "declared" and not traced.assumed_fossil
    # a declared fossil resource stays fossil, even for CO2 in air
    air = _input("resource:CO2", "resource", cas="124-38-9", biogenic_fraction=0.0)
    assert trace(_dataset("d", [_product(), air]), CarbonAccounting()).fraction == 0.0


def test_only_co2_in_air_is_an_implicit_uptake() -> None:
    from chemeascode.domains.assessment.lca.carbon import findings

    air = _input("resource:CO2", "resource", cas="124-38-9")
    traced = trace(_dataset("d", [_product(), air]), CarbonAccounting())
    assert traced.fraction == pytest.approx(1.0) and traced.flow("resource:CO2").how == "uptake"
    gas = _input("resource:GAS", "resource", cas="74-82-8")
    dataset = _dataset("d", [_product(), gas])
    traced = trace(dataset, CarbonAccounting())
    assert traced.fraction == pytest.approx(0.0)
    assert traced.assumed_fossil == ["resource:GAS"]  # reported, not silently fossil
    found = findings(traced, dataset, CarbonAccounting(), "lca.yaml")
    assert "cheme.lca-carbon-assumed-fossil" in {f.rule for f in found}


def test_a_characterised_uptake_is_biogenic_and_the_removal_is_counted_once() -> None:
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.carbon import pcf, pcf_findings
    from chemeascode.domains.assessment.lca.schemas import Background

    dataset = _dataset("d", [_product(), _input("resource:CO2", "resource", cas="124-38-9")])
    rows = [NS(key="resource:CO2", cas="124-38-9", kind="resource", phase="operation",
               quantity=18.3)]  # fmt: skip
    inventory = NS(
        functional_unit="10 kg P",
        rows=rows,
        amount=10.0,
        dataset=dataset,
        backgrounds={"resource:CO2": Background(factor="uptake", source="test")},
    )
    impacts = [NS(key="resource:CO2", value=-18.3)]
    category = NS(id="climate", unit="kg CO2-eq")
    carbon = trace(dataset, CarbonAccounting())
    found = pcf(inventory, impacts, category, CarbonAccounting(), carbon, "P")
    assert found.fossil == 0 and found.background == []
    assert found.biogenic_co2_characterised == pytest.approx(-18.3)
    assert found.excluding == 0
    # the removal is the product's own biogenic carbon, once: not -18.3 on top of it
    assert found.withdrawal == pytest.approx(-5 * CO2_PER_C)
    assert found.including == pytest.approx(found.excluding + found.withdrawal)
    warned = pcf_findings(found, "lca.yaml")
    assert [f.rule for f in warned] == ["cheme.lca-pcf-biogenic"]
    found.biogenic_co2_characterised = 0.0
    assert pcf_findings(found, "lca.yaml") == []


# -- PACT export ---------------------------------------------------------------------------------

CREATED = dt.datetime(2026, 10, 25, tzinfo=dt.UTC)


def _loaded_with(root: Path, scope: dict):
    _write(root, scope)
    return _loaded(root)


def _export(root: Path, scope: dict):
    return footprint(_loaded_with(root, scope), CREATED)


def _ccs_scope(source: str, **accounting) -> dict:
    scope = _scope(source, **accounting)
    purge = next(f for f in scope["flows"] if f["key"] == "product:PURGE")
    purge.pop("emission")
    purge.update(factor="storage", storage={"permanence": "saline aquifer, monitored (test)"})
    scope["flows"] = [f for f in scope["flows"] if not f["key"].startswith("emission:")]
    return scope


def test_pact_biogenic_fields_are_consistent(methanol: Path) -> None:
    document, problems = _export(methanol, _scope())
    assert not problems, problems
    pcf = document["pcf"]
    assert float(pcf["pCfIncludingBiogenic"]) == pytest.approx(
        float(pcf["pCfExcludingBiogenic"]) + float(pcf["biogenicCarbonWithdrawal"]), abs=1e-8
    )
    assert "permanent storage" not in document["comment"]
    # with CCS of biogenic CO2: the stored term is in the comment with its amount
    document, problems = _export(methanol, _ccs_scope("biogenic-point-source"))
    assert not problems, problems
    pcf = document["pcf"]
    stored = -20.0 / 1000  # kg CO2e per declared unit (kg)
    # PACT v2 has no field for a technological removal: it stays out of pCfIncludingBiogenic,
    # so a recipient who adds the exported fields gets the exported figure
    assert float(pcf["pCfIncludingBiogenic"]) == pytest.approx(
        float(pcf["pCfExcludingBiogenic"]) + float(pcf["biogenicCarbonWithdrawal"]), abs=1e-8
    )
    assert f"(CCS): {stored:g} kg CO2e" in document["comment"]
    assert "NOT in pCfIncludingBiogenic" in document["comment"]


def test_ccs_emitted_pcf_arithmetic(methanol: Path) -> None:
    technosphere = _loaded_with(methanol, _ccs_scope("fossil-point-source")).pcf
    emitted = _loaded_with(methanol, _ccs_scope("fossil-point-source", ccs="emitted")).pcf
    # fossil CO2 to storage: not emitted with technosphere, emitted (+20 kg) with `emitted`
    assert emitted.fossil == pytest.approx(technosphere.fossil + 20.0, rel=1e-6)
    assert emitted.stored_biogenic == 0 and technosphere.stored_biogenic == 0
    assert emitted.including == pytest.approx(emitted.excluding)
    bio = _loaded_with(methanol, _ccs_scope("biogenic-point-source", ccs="emitted")).pcf
    assert bio.stored_co2 == pytest.approx(20.0, rel=1e-6) and bio.stored_biogenic == 0
    assert bio.biogenic_co2_emitted == pytest.approx(20.0, rel=1e-6)
    assert bio.fossil == pytest.approx(1393.5 * 0.15 + 192.0 + 23.25 * 0.02)  # + storage
    assert bio.including == pytest.approx(bio.excluding + bio.withdrawal)


def test_pact_geography(methanol: Path) -> None:
    from chemeascode.domains.assessment.lca.pact import _geography

    assert _geography("DE") == ({"geographyCountry": "DE"}, None)
    assert _geography("uk") == ({"geographyCountry": "GB"}, None)
    assert _geography("DE-BY") == ({"geographyCountrySubdivision": "DE-BY"}, None)
    assert _geography("western europe") == ({"geographyRegionOrSubregion": "Western Europe"}, None)
    assert _geography("") == ({}, None)  # only undefined everywhere is global
    for other in ("GLO", "Rhine valley", "RER"):
        assert _geography(other)[0] == {} and "not exported as global" in _geography(other)[1]
    for location, key in (
        ("DE-BY", "geographyCountrySubdivision"),
        ("Western Europe", "geographyRegionOrSubregion"),
    ):
        scope = _scope()
        scope["location"] = location
        document, problems = _export(methanol, scope)
        assert not problems, problems
        assert [k for k in document["pcf"] if k.startswith("geography")] == [key]
    scope = _scope()
    scope["location"] = "GLO"
    document, problems = _export(methanol, scope)
    assert document is None and any("not exported as global" in p for p in problems)
    good, _ = _export(methanol, _scope())
    good["pcf"].update({"geographyCountry": "DE", "geographyCountrySubdivision": "DE-BY"})
    assert any("only one geography" in p for p in validate(good))


def test_pact_declared_unit_map(methanol: Path) -> None:
    from chemeascode.domains.assessment.lca.pact import DECLARED_UNITS

    # a dataset counts its products in base units only, and the inventory amount is in the
    # product's unit: a functional unit of 1 t of a product in kg is 1000 kg, not 1000 * 1000
    assert {u: v[0] for u, v in DECLARED_UNITS.items()} == {
        "kg": "kilogram", "kWh": "kilowatt hour", "m3": "cubic meter", "m2": "square meter",
    }  # fmt: skip
    report = _loaded(methanol)
    base, _ = footprint(report, CREATED)
    assert base["pcf"]["declaredUnit"] == "kilogram"
    assert float(base["pcf"]["unitaryProductAmount"]) == 1000
    product = report.inventory.dataset.product("MEOH")
    try:
        for unit in ("t", "Nm3", "MJ"):
            product.unit = unit
            refused, problems = footprint(report, CREATED)
            assert refused is None and any("no PACT declaredUnit" in p for p in problems)
    finally:
        product.unit = "kg"


def test_pact_ipcc_is_declared_never_guessed(methanol: Path) -> None:
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.pact import _ipcc
    from chemeascode.domains.assessment.lca.schemas import IpccBasis

    titled = NS(id="gwp", method="IPCC 2021 GWP100 (AR6)", title="IPCC AR6 2021", elementary=None)
    assert _ipcc(titled, None)[0] is None and "not declared" in _ipcc(titled, None)[1]
    assert _ipcc(titled, IpccBasis(report="AR5", gwp_horizon=100)) == ("AR5", None)
    assert "GWP20" in _ipcc(titled, IpccBasis(report="AR6", gwp_horizon=20))[1]
    exact = NS(id="gwp", method="", title="", elementary="ipcc2021-gwp100")
    assert _ipcc(exact, None) == ("AR6", None)
    assert "says AR5" in _ipcc(exact, IpccBasis(report="AR5", gwp_horizon=100))[1]
    scope = _scope(ipcc={"report": "AR5", "gwp_horizon": 100})  # the packaged method is AR6
    document, problems = _export(methanol, scope)
    assert document is None and any("says AR5" in p for p in problems)
    document, problems = _export(methanol, _scope(ipcc={"report": "AR6", "gwp_horizon": 100}))
    assert not problems and document["pcf"]["ipccCharacterizationFactorsSources"] == ["AR6"]


def test_pact_id_follows_the_content(methanol: Path) -> None:
    first, _ = _export(methanol, _scope())
    again, _ = footprint(_loaded(methanol), dt.datetime(2030, 1, 1, tzinfo=dt.UTC))
    assert again["id"] == first["id"]  # same content, same id
    factors = json.loads(json.dumps(FACTORS))
    factors["factors"][1]["values"]["climate"] = 2.0  # hydrogen
    (methanol / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors))
    changed, _ = footprint(_loaded(methanol), CREATED)
    assert changed["version"] == first["version"] == 1
    assert changed["id"] != first["id"]
    assert changed["pcf"]["pCfExcludingBiogenic"] != first["pcf"]["pCfExcludingBiogenic"]


def test_tfs_rule_and_iso_methodology_only_for_minus_one_plus_one(methanol: Path) -> None:
    document, _ = _export(methanol, _scope())
    pcf = document["pcf"]
    rule = pcf["productOrSectorSpecificRules"][0]
    assert "Version 3.0" in rule["ruleNames"][0] and "December 2024" in rule["ruleNames"][0]
    assert pcf["biogenicAccountingMethodology"] == "ISO"
    document, problems = _export(methanol, _scope(biogenic="zero-zero"))
    assert not problems, problems
    assert "productOrSectorSpecificRules" not in document["pcf"]
    # required from 2025 on, whatever the method: PEF is our mapping of 0/0
    assert document["pcf"]["biogenicAccountingMethodology"] == "PEF"


def test_dqi_required_from_a_period_including_2025(methanol: Path) -> None:
    document, _ = _export(methanol, _scope())

    def check(start: int, end: int, drop: tuple[str, ...]) -> list[str]:
        copy = json.loads(json.dumps(document))
        copy["pcf"]["referencePeriodStart"] = f"{start}-01-01T00:00:00Z"
        copy["pcf"]["referencePeriodEnd"] = f"{end}-01-01T00:00:00Z"
        for key in drop:
            del copy["pcf"][key]
        return validate(copy)

    assert check(2024, 2025, ("dqi", "primaryDataShare")) != []  # one of them is needed
    assert check(2024, 2025, ("dqi",)) == []  # calendar 2024 ends at the beginning of 2025
    assert check(2024, 2025, ("primaryDataShare",)) == []
    assert check(2025, 2026, ("dqi",)) != [] and check(2025, 2026, ("primaryDataShare",)) != []
    assert check(2025, 2026, ()) == []


def test_pact_urns() -> None:
    from chemeascode.domains.assessment.lca.schemas import PactIdentity

    base = {"company_name": "X", "product_name": "Y"}
    ok = PactIdentity(
        **base,
        company_ids=["urn:pact:company:customcode:buyer-assigned:1"],
        product_ids=["urn:pact:cas.org:substance-number:67-56-1", "urn:gtin:4712345060507"],
    )
    assert ok.product_ids[0].startswith("urn:pact:")
    with pytest.raises(ValueError, match=r"urn:pact:<domain>:<type>:<id>"):
        PactIdentity(**base, company_ids=["urn:pact:company"], product_ids=["urn:gtin:1"])
    with pytest.raises(ValueError, match="not URNs"):
        PactIdentity(**base, company_ids=["company-1"], product_ids=["urn:gtin:1"])


def test_cli_pact_failure_exits_1(methanol: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    scope = _scope()
    del scope["carbon_accounting"]["pact"]
    _write(methanol, scope)
    monkeypatch.chdir(methanol)
    out = methanol / "pact.json"
    result = CliRunner().invoke(app, ["assess", "lca", "--pact", str(out)])
    assert result.exit_code == 1, result.output
    assert not out.exists() and "cheme.lca-pact" in result.output


# -- post-merge review -----------------------------------------------------------------------------


def _bio_inventory(dataset: LciDataset, rows: list, backgrounds: dict | None = None):
    from types import SimpleNamespace as NS

    return NS(
        functional_unit="10 kg P",
        rows=rows,
        amount=10.0,
        dataset=dataset,
        backgrounds=backgrounds or {},
    )


def test_uptake_of_biogenic_carbon_leaving_as_ch4_or_in_a_waste_is_booked() -> None:
    """Including = excluding + withdrawal only holds when all biogenic carbon leaves as product,
    storage or CO2: the uptake of biogenic carbon in CH4 or a waste output is not cancelled."""
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.carbon import ELEMENTARY_CARBON, pcf
    from chemeascode.domains.assessment.lca.schemas import Background, Elementary

    dataset = _dataset(
        "d",
        [
            _input("feed:BIOMASS", biogenic_fraction=1.0),
            {"key": "product:P", "type": "product", "amount": 5, "unit": "kg",
             "carbon": {"total": 0.5}},
            {"key": "emission:CH4", "type": "emission", "amount": 2, "unit": "kg",
             "cas": "74-82-8"},
            {"key": "output:WASTE", "type": "output", "amount": 4, "unit": "kg",
             "carbon": {"total": 0.25}},
        ],
    )  # fmt: skip
    ch4 = ELEMENTARY_CARBON["74-82-8"][1]
    carbon = trace(dataset, CarbonAccounting())
    assert carbon.fraction == pytest.approx(1.0)
    rows = [
        NS(key="emission:CH4", cas="74-82-8", kind="emission", phase="operation", quantity=2.0),
        NS(key="output:WASTE", cas=None, kind="material", phase="operation", quantity=4.0),
    ]
    methane = Background(elementary=Elementary(compartment="air", origin="biogenic"), source="test")
    inventory = _bio_inventory(dataset, rows, {"emission:CH4": methane})
    impacts = [NS(key="emission:CH4", value=2 * 27.0)]
    category = NS(id="climate", unit="kg CO2-eq")
    found = pcf(inventory, impacts, category, CarbonAccounting(), carbon, "P")
    assert found.other_biogenic == pytest.approx(54.0)
    assert found.withdrawal == pytest.approx(-CO2_PER_C * 5.0)  # 10 kg of P at 0.5 kg C/kg
    # the rows are per functional unit: 2 kg CH4 and 4 kg of waste at 0.25 kg C/kg
    assert found.withdrawal_other == pytest.approx(-CO2_PER_C * (2 * ch4 + 4 * 0.25))
    assert found.including == pytest.approx(
        found.excluding + found.withdrawal + found.withdrawal_other
    )


def test_foreground_dluc_co2_is_not_a_carbon_output() -> None:
    from chemeascode.domains.assessment.lca.carbon import findings

    def co2(key: str, kg: float, origin: str) -> dict:
        return {"key": key, "type": "emission", "amount": kg, "unit": "kg", "cas": "124-38-9",
                "link": {"elementary": {"compartment": "air", "origin": origin},
                         "source": "test"}}  # fmt: skip

    dataset = _dataset(
        "d",
        [
            _input("feed:SUGAR", biogenic_fraction=1.0) | {"amount": 80},  # 40 kg C
            {"key": "product:P", "type": "product", "amount": 20, "unit": "kg",
             "carbon": {"total": 1.0}},
            co2("emission:CO2", 20 * CO2_PER_C, "biogenic"),
            co2("emission:CO2.luc", 10, "land-use-change"),
        ],
    )  # fmt: skip
    traced = trace(dataset, CarbonAccounting())
    assert traced.flow("emission:CO2.luc") is None
    assert traced.residual == pytest.approx(0, abs=1e-9)
    assert traced.fraction == pytest.approx(1.0)
    rules = {f.rule for f in findings(traced, dataset, CarbonAccounting(), "lca.yaml")}
    assert not rules & {"cheme.lca-carbon-balance", "cheme.lca-carbon-biogenic"}


def test_a_negative_background_of_a_biogenic_input_is_reported() -> None:
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.carbon import pcf, pcf_findings
    from chemeascode.domains.assessment.lca.schemas import Background

    dataset = _dataset(
        "d", [_product(), _input("feed:WOOD", biogenic_fraction=1.0)]
    )  # 10 kg x 0.5 in, 10 kg x 0.5 out
    rows = [NS(key="feed:WOOD", cas=None, kind="material", phase="operation", quantity=10.0)]
    inventory = _bio_inventory(dataset, rows, {"feed:WOOD": Background(factor="w", source="test")})
    carbon = trace(dataset, CarbonAccounting())
    category = NS(id="climate", unit="kg CO2-eq")
    found = pcf(inventory, [NS(key="feed:WOOD", value=-9.0)], category, CarbonAccounting(),
                carbon, "P")  # fmt: skip
    assert found.background_uptake == ["feed:WOOD"]
    assert "cheme.lca-pcf-background-uptake" in {f.rule for f in pcf_findings(found, "l.yaml")}
    fine = pcf(inventory, [NS(key="feed:WOOD", value=2.0)], category, CarbonAccounting(),
               carbon, "P")  # fmt: skip
    assert fine.background_uptake == []


def test_material_in_gas_volume_is_listed_as_unknown() -> None:
    dataset = _dataset(
        "d",
        [_product(), _input("feed:GAS") | {"unit": "Nm3", "carbon": None},
         {"key": "feed:C", "type": "input", "amount": 10, "unit": "kg", "carbon": {"total": 0.5}}],
    )  # fmt: skip
    assert "feed:GAS" in trace(dataset, CarbonAccounting()).unknown


def test_carbon_content_from_captured_co2_is_reported_separately(methanol: Path) -> None:
    dac = _loaded_with(methanol, _scope("direct-air-capture")).pcf
    assert dac.ccu_carbon == pytest.approx(dac.product_carbon, rel=1e-6)
    assert dac.ccu_non_fossil_carbon == pytest.approx(dac.product_carbon, rel=1e-6)
    fossil = _loaded_with(methanol, _scope("fossil-point-source")).pcf
    assert fossil.ccu_carbon == pytest.approx(fossil.product_carbon, rel=1e-6)
    assert fossil.ccu_non_fossil_carbon == 0
    document, _ = _export(methanol, _scope())
    assert "captured CO2 (CCU)" in document["comment"] and "physical basis" in document["comment"]


def test_pact_exempted_emissions_are_stated_never_assumed_zero(methanol: Path) -> None:
    scope = _scope()
    scope["carbon_accounting"]["pact"] = {
        k: v for k, v in PACT.items() if not k.startswith("exempted")
    }
    document, problems = _export(methanol, scope)
    assert document is None and any("share of exempted emissions" in p for p in problems)
    document, problems = _export(methanol, _scope())
    assert not problems
    assert document["pcf"]["exemptedEmissionsPercent"] == 1.0
    assert document["pcf"]["dqi"]["coveragePercent"] == 99.0
    assert "ASSUMED" in document["pcf"]["exemptedEmissionsDescription"]
    gate = _scope()
    gate["boundary"] = "gate-to-gate"
    document, problems = _export(methanol, gate)
    assert document is None and any("cradle-to-gate" in p for p in problems)
    from chemeascode.domains.assessment.lca.schemas import PactIdentity

    with pytest.raises(ValueError, match="less than or equal to 5"):
        PactIdentity(**PACT | {"exempted_emissions_percent": 6.0})
    with pytest.raises(ValueError, match="exempted_emissions_description"):
        PactIdentity(**(PACT | {"exempted_emissions_description": ""}))


def test_pact_o_star_properties_are_required_from_2025(methanol: Path) -> None:
    document, problems = _export(methanol, _scope())
    assert not problems and document["pcf"]["landManagementGhgEmissions"] == "0"
    assert "land management emissions are not modelled (ASSUMED)" in document["comment"]
    assert validate(document) == []
    for name in ("landManagementGhgEmissions", "biogenicAccountingMethodology"):
        copy = json.loads(json.dumps(document))
        del copy["pcf"][name]
        assert any(name in p for p in validate(copy)), name
    copy = json.loads(json.dumps(document))
    copy["pcf"]["exemptedEmissionsPercent"] = 6.0
    assert validate(copy) != []


# -- post-merge review -----------------------------------------------------------------------------


def test_an_avoided_credit_carries_no_carbon() -> None:
    # substitution: the credit of a recycled output is a negative avoided:
    # input. It stands for production outside the plant; the carbon left with the output already.
    # Here 50 kg C biogenic and 50 fossil enter, 60 leave in the product and 40 in the recyclable.
    pet = _dataset("pet", [{"key": "product:PET", "type": "product", "amount": 1, "unit": "kg",
                            "carbon": {"total": 1.0}}])  # fmt: skip
    for link in (
        {"dataset": {"path": "pet.yaml", "product": "PET"}, "source": "test"},
        {"factor": "pet", "source": "test"},
    ):
        plant = LciDataset.model_validate(
            {"schema": "cheme/lci_dataset/v2", "kind": "lci_dataset", "id": "p",
             "system_model": "substitution", "exchanges": [
                {"key": "product:P", "type": "product", "amount": 60, "unit": "kg",
                 "carbon": {"total": 1.0}},
                {"key": "feed:BIO", "type": "input", "amount": 50, "unit": "kg",
                 "carbon": {"total": 1.0, "biogenic_fraction": 1.0}},
                {"key": "feed:GAS", "type": "input", "amount": 50, "unit": "kg",
                 "carbon": {"total": 1.0, "biogenic_fraction": 0.0}},
                {"key": "product:RECYC", "type": "output", "amount": 40, "unit": "kg",
                 "carbon": {"total": 1.0}},
                {"key": "avoided:product.RECYC", "type": "input", "amount": -40, "unit": "kg",
                 "link": link},
            ]}
        )  # fmt: skip
        traced = trace(plant, CarbonAccounting(), {"pet.yaml": pet}.__getitem__, path="p.yaml")
        assert traced.total("in") == pytest.approx(100)
        assert traced.residual == pytest.approx(0)
        assert traced.fraction == pytest.approx(0.5)  # not 50/60 with the credit as an input
        assert traced.unknown == [] and traced.upstream == {}
        assert traced.flow("avoided:product.RECYC") is None
