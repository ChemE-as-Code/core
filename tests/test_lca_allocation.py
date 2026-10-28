"""Allocation methods, the plant's unallocated LCI dataset, and datasets as backgrounds.

The plant is ``examples/process-blocks`` (see ``test_lca.py``): 1000 kg/h feed and 350 kW of
steam make 400 kg/h of product PROD and 600 kg/h of waste water WATER. Here WATER is a
co-product, so the burdens of 1 h (feed 500, steam 88.2 kg CO2-eq) are shared.
"""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.report import (
    dataset_paths,
    dataset_yaml,
    lca_report,
    results_markdown,
)
from chemeascode.domains.assessment.lca.schemas import LciDataset

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
BURDEN = 500 + 350 * 3.6 * 0.07  # one hour: feed and steam, kg CO2-eq
FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq"}],
    "factors": [
        {
            "id": i,
            "unit": u,
            "values": {"gwp": v},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        }
        for i, u, v in (
            ("feed", "kg", 0.5),
            ("steam", "MJ", 0.07),
            ("water", "kg", 0.01),
            ("power", "kWh", 0.4),
        )
    ],
}


def _scope(**allocation) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lca",
        "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
        "allocation": {"coproducts": ["WATER"], **allocation},
        "flows": [
            {"key": "feed:FEED", "factor": "feed", "source": "test"},
            {"key": "feed:STEAM", "factor": "steam", "source": "test"},
        ],
    }


def _write(root: Path, scope: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(FACTORS, sort_keys=False))


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    return root


def _total(report) -> float:
    return report.totals()["gwp"]


def _comparison(report) -> dict:
    return {e["method"]: e for e in report.comparison}


@pytest.mark.parametrize(
    ("allocation", "share"),
    [
        ({"method": "mass"}, 0.4),
        ({"method": "economic", "prices": {"PROD": 2.0, "WATER": 0.1}}, 800 / 860),
        (
            {
                "method": "energy",
                "properties": {"PROD": {"energy": 26000}, "WATER": {"energy": 1000}},
            },
            400 * 26000 / (400 * 26000 + 600 * 1000),
        ),
        (
            {
                "method": "exergy",
                "properties": {"PROD": {"exergy": 29000}, "WATER": {"exergy": 50}},
            },
            400 * 29000 / (400 * 29000 + 600 * 50),
        ),
        ({"method": "shares", "shares": {"PROD": 0.9, "WATER": 0.1}}, 0.9),
        ({"method": "none"}, 1.0),
    ],
)
def test_proportional_methods(blocks: Path, allocation: dict, share: float) -> None:
    _write(blocks, _scope(**allocation))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.inventory.shares["PROD"] == pytest.approx(share)
    # 1 t of PROD is 2.5 h; it carries its share of 2.5 h's burdens
    assert _total(report) == pytest.approx(BURDEN * 2.5 * share)
    used = _comparison(report)[allocation["method"]]
    assert used["current"] and used["totals"]["gwp"] == pytest.approx(_total(report))


def test_substitution_credits_the_coproduct(blocks: Path) -> None:
    substitute = {"WATER": {"factor": "water", "source": "avoided water supply"}}
    _write(blocks, _scope(method="substitution", substitution=substitute))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    rows = {r.key: r for r in report.inventory.rows}
    credit = rows["substitution:WATER"]
    assert credit.kind == "credit" and credit.quantity == pytest.approx(-1500)
    assert credit.mapping == "factor:water"
    # the whole burden of 2.5 h, less the avoided 1.5 t of water
    assert _total(report) == pytest.approx(BURDEN * 2.5 - 1500 * 0.01)


def test_every_method_is_compared(blocks: Path) -> None:
    substitute = {"WATER": {"factor": "water", "source": "avoided water supply"}}
    _write(blocks, _scope(prices={"PROD": 2.0, "WATER": 0.1}, substitution=substitute))
    report = lca_report(blocks)
    found = _comparison(report)
    assert found["mass"]["current"] and found["mass"]["share"] == pytest.approx(0.4)
    assert found["economic"]["totals"]["gwp"] == pytest.approx(BURDEN * 2.5 * 800 / 860)
    assert found["none"]["totals"]["gwp"] == pytest.approx(BURDEN * 2.5)
    assert found["substitution"]["totals"]["gwp"] == pytest.approx(BURDEN * 2.5 - 15)
    assert found["exergy"]["totals"] is None and "no exergy of PROD" in found["exergy"]["problem"]
    assert found["shares"]["totals"] is None
    markdown = results_markdown(report)
    assert "## Allocation (baseline)" in markdown and "| mass (used) | 40.0% |" in markdown
    assert "| exergy | | not applicable: no exergy of PROD |" in markdown
    # compare narrows the list (the method used stays)
    _write(blocks, _scope(compare=["none"]))
    assert [e["method"] for e in lca_report(blocks).comparison] == ["mass", "none"]


def test_missing_data_is_an_error(blocks: Path) -> None:
    _write(blocks, _scope(method="exergy"))
    report = lca_report(blocks)
    assert not report.loaded
    assert report.findings[0].rule == "cheme.lca-allocation"
    assert "exergy allocation: no exergy of PROD" in report.findings[0].message


def test_exergy_from_the_flowsheet(blocks: Path) -> None:
    """A product's exergy comes from its streams' calculated exergy (process props --fill)."""
    path = blocks / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    for stream in data["streams"]:
        if stream["id"] in ("S3", "S5"):
            stream["state"]["design"]["calculated"] = {
                "molar_mass": {"value": 40.0, "provenance": "calculated"},
                "exergy": {
                    "value": 800_000.0 if stream["id"] == "S3" else 2_000.0,
                    "provenance": "calculated",
                },
            }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    _write(blocks, _scope(method="exergy"))
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    # exergy per kg: 20000 (PROD) and 50 (WATER) kJ
    assert report.inventory.shares["PROD"] == pytest.approx(400 * 20000 / (400 * 20000 + 600 * 50))
    product = report.inventory.dataset.product("PROD")
    assert product.properties.exergy == pytest.approx(20000)


def test_dataset_yaml_round_trips(blocks: Path) -> None:
    _write(blocks, _scope())
    report = lca_report(blocks)
    text = dataset_yaml(report)
    assert text.startswith("# The plant's unallocated LCI dataset")
    data = yaml.safe_load(text)
    assert data["scope"] == "foreground" and data["basis"] == "1 h of operation"
    dataset = LciDataset.model_validate(data)
    assert [p.key for p in dataset.products()] == ["product:PROD", "product:WATER"]
    assert dataset.allocation.method == "mass"
    assert "process/flowsheet.yaml" in dataset.provenance.files
    assert "lca/factors.yaml" not in dataset.provenance.files
    feed = next(e for e in dataset.exchanges if e.key == "feed:FEED")
    assert (feed.amount, feed.unit, feed.link.factor) == (1000, "kg", "feed")


# -- datasets as backgrounds --------------------------------------------------------------------

#: A hand-written dataset: 2 kWh of power and 0.1 kg of water make 1 kg of feedstock and 0.5 kg
#: of a by-product (mass allocation by default: the feedstock carries 2/3).
FEEDSTOCK = {
    "schema": "cheme/lca/v1",
    "kind": "lci_dataset",
    "id": "feedstock",
    "scope": "foreground",
    "basis": "1 batch",
    "exchanges": [
        {"key": "product:FEEDSTOCK", "type": "product", "amount": 1.0, "unit": "kg"},
        {"key": "product:BY", "type": "product", "amount": 0.5, "unit": "kg"},
        {
            "key": "feed:POWER",
            "type": "input",
            "amount": 2.0,
            "unit": "kWh",
            "link": {"factor": "power", "source": "grid"},
        },
        {
            "key": "feed:WATER",
            "type": "input",
            "amount": 0.1,
            "unit": "kg",
            "link": {"factor": "water", "source": "tap"},
        },
    ],
}
PER_KG_MASS = (2 * 0.4 + 0.1 * 0.01) * (1.0 / 1.5)


def _with_dataset(root: Path, dataset: dict, ref: dict, name: str = "feedstock.yaml") -> None:
    (root / "lca" / "datasets").mkdir(parents=True, exist_ok=True)
    (root / "lca" / "datasets" / name).write_text(yaml.safe_dump(dataset, sort_keys=False))
    scope = _scope(method="none")
    scope["flows"][0] = {"key": "feed:FEED", "dataset": ref, "source": "upstream dataset"}
    _write(root, scope)


def test_a_dataset_as_background(blocks: Path) -> None:
    _with_dataset(
        blocks, FEEDSTOCK, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"}
    )
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    feed = next(i for i in report.impacts if i.key == "feed:FEED")
    assert feed.factor == pytest.approx(PER_KG_MASS)
    assert feed.basis == "dataset:lca/datasets/feedstock.yaml#FEEDSTOCK (mass)"
    assert _total(report) == pytest.approx(2500 * PER_KG_MASS + 350 * 2.5 * 3.6 * 0.07)
    # the reference chooses its own allocation
    _with_dataset(
        blocks,
        FEEDSTOCK,
        {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK", "allocation": "none"},
    )
    feed = next(i for i in lca_report(blocks).impacts if i.key == "feed:FEED")
    assert feed.factor == pytest.approx(2 * 0.4 + 0.1 * 0.01)


def test_datasets_chain_and_cycles_are_caught(blocks: Path) -> None:
    # feedstock's power comes from another dataset (0.5 kg CO2-eq per kWh)
    power = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "power",
        "exchanges": [
            {"key": "product:POWER", "type": "product", "amount": 1.0, "unit": "kWh"},
            {
                "key": "feed:FUEL",
                "type": "input",
                "amount": 1.25,
                "unit": "kWh",
                "link": {"factor": "power", "source": "fuel"},
            },
        ],
    }
    chained = yaml.safe_load(yaml.safe_dump(FEEDSTOCK))
    chained["exchanges"][2]["link"] = {
        "dataset": {"path": "lca/datasets/power.yaml", "product": "POWER"},
        "source": "own power plant",
    }
    (blocks / "lca" / "datasets").mkdir(parents=True)
    (blocks / "lca" / "datasets" / "power.yaml").write_text(yaml.safe_dump(power))
    _with_dataset(blocks, chained, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    feed = next(i for i in report.impacts if i.key == "feed:FEED")
    assert feed.factor == pytest.approx((2 * 0.5 + 0.1 * 0.01) / 1.5)
    lca_text = (blocks / "lca" / "lca.yaml").read_text()
    read = lambda path: (blocks / path).read_text() if (blocks / path).is_file() else None  # noqa: E731
    assert sorted(dataset_paths(lca_text, read)) == [
        "lca/datasets/feedstock.yaml",
        "lca/datasets/power.yaml",
    ]
    # power back to feedstock: a cycle
    power["exchanges"][1]["link"] = {
        "dataset": {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"},
        "source": "loop",
    }
    (blocks / "lca" / "datasets" / "power.yaml").write_text(yaml.safe_dump(power))
    report = lca_report(blocks)
    assert not report.loaded
    assert any("dataset cycle" in f.message for f in report.findings)


@pytest.mark.parametrize(
    ("ref", "message"),
    [
        ({"path": "lca/datasets/feedstock.yaml", "product": "NOPE"}, "has no product NOPE"),
        ({"path": "lca/datasets/missing.yaml", "product": "X"}, "no dataset lca/datasets/missing"),
        ({"path": "../outside.yaml", "product": "X"}, "outside the repository"),
    ],
)
def test_dataset_problems(blocks: Path, ref: dict, message: str) -> None:
    _with_dataset(blocks, FEEDSTOCK, ref)
    report = lca_report(blocks)
    assert not report.loaded
    assert any(f.rule == "cheme.lca-dataset" and message in f.message for f in report.findings)


def test_dataset_unit_mismatch(blocks: Path) -> None:
    _with_dataset(
        blocks, FEEDSTOCK, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"}
    )
    scope = yaml.safe_load((blocks / "lca" / "lca.yaml").read_text())
    scope["flows"][1] = {
        "key": "feed:STEAM",
        "dataset": {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"},
        "source": "wrong",
    }
    (blocks / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope))
    report = lca_report(blocks)
    assert any("counted in kWh" in f.message for f in report.findings)


def test_schema_rules() -> None:
    from pydantic import ValidationError

    from chemeascode.domains.assessment.lca.schemas import Allocation, FlowMap

    with pytest.raises(ValidationError, match="sum to"):
        Allocation(method="shares", shares={"A": 0.5, "B": 0.4})
    with pytest.raises(ValidationError, match="needs substitution"):
        Allocation(method="substitution")
    with pytest.raises(ValidationError, match="dataset excludes"):
        FlowMap(key="feed:X", factor="f", dataset={"path": "x", "product": "y"}, source="test")
    with pytest.raises(ValidationError, match="at least one product"):
        LciDataset.model_validate(
            {
                "schema": "cheme/lca/v1",
                "kind": "lci_dataset",
                "id": "x",
                "exchanges": [{"key": "feed:A", "type": "input", "amount": 1, "unit": "kg"}],
            }
        )


# -- review fixes -------------------------------------------------------------------------------


def test_unlinked_exchanges_of_a_dataset_warn_or_fail(blocks: Path) -> None:
    dataset = yaml.safe_load(yaml.safe_dump(FEEDSTOCK))
    del dataset["exchanges"][2]["link"]  # power without background
    _with_dataset(blocks, dataset, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    report = lca_report(blocks)
    unlinked = [f for f in report.findings if f.rule == "cheme.lca-dataset-unlinked"]
    assert len(unlinked) == 1 and "feed:POWER" in unlinked[0].message
    dataset["scope"] = "linked"
    _with_dataset(blocks, dataset, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    report = lca_report(blocks)
    assert not report.loaded
    assert any("scope linked" in f.message for f in report.findings)


def test_backgrounds_are_checked_everywhere() -> None:
    from pydantic import ValidationError

    from chemeascode.domains.assessment.lca.schemas import Allocation

    both = {"factor": "x", "dataset": {"path": "p", "product": "y"}, "source": "test"}
    with pytest.raises(ValidationError, match="dataset excludes"):
        Allocation(method="substitution", substitution={"B": both})
    with pytest.raises(ValidationError, match="give one of"):
        Allocation(method="substitution", substitution={"B": {"source": "nothing"}})
    exchange = {"key": "feed:A", "type": "input", "amount": 1, "unit": "kg", "link": both}
    product = {"key": "product:P", "type": "product", "amount": 1, "unit": "kg"}
    base = {"schema": "cheme/lca/v1", "kind": "lci_dataset", "id": "x"}
    with pytest.raises(ValidationError, match="dataset excludes"):
        LciDataset.model_validate({**base, "exchanges": [product, exchange]})
    with pytest.raises(ValidationError, match="not negative"):
        LciDataset.model_validate({**base, "exchanges": [{**product, "amount": -1}]})


def test_one_product_has_no_comparison(blocks: Path) -> None:
    scope = _scope(method="mass")
    scope["allocation"]["coproducts"] = []
    scope["flows"].append({"key": "product:WATER", "free": True, "source": "test"})
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded and report.comparison == []
    assert "## Allocation" not in results_markdown(report)


def test_stale_exergy_is_not_used(blocks: Path) -> None:
    path = blocks / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    for stream in data["streams"]:
        if stream["id"] in ("S3", "S5"):
            stream["state"]["design"]["calculated"] = {
                "molar_mass": {"value": 40.0, "provenance": "calculated", "fingerprint": "0" * 16},
                "exergy": {"value": 1000.0, "provenance": "calculated", "fingerprint": "0" * 16},
            }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    _write(blocks, _scope(method="exergy"))
    report = lca_report(blocks)
    assert any(f.rule == "cheme.lca-exergy-stale" for f in report.findings)
    assert not report.loaded  # no exergy left to allocate by


def test_dataset_fingerprints_ignore_line_endings(blocks: Path) -> None:
    _write(blocks, _scope())
    first = dataset_yaml(lca_report(blocks))
    lca = blocks / "lca" / "lca.yaml"
    lca.write_bytes(lca.read_bytes().replace(b"\n", b"\r\n"))
    assert dataset_yaml(lca_report(blocks)) == first


def _compat(report) -> list:
    return [f for f in report.findings if f.rule == "cheme.lca-link-compat"]


def test_a_compatible_dataset_link_is_not_reported(blocks: Path) -> None:
    dataset = yaml.safe_load(yaml.safe_dump(FEEDSTOCK))
    # its own inputs' transport is not a delivery of its product
    dataset["exchanges"].append(
        {"key": "transport:road", "type": "input", "amount": 0.05, "unit": "tkm", "free": True}
    )
    dataset["allocation"] = {"method": "economic", "prices": {"FEEDSTOCK": 1, "BY": 1}}
    _with_dataset(blocks, dataset, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    scope = yaml.safe_load((blocks / "lca" / "lca.yaml").read_text())
    scope["allocation"] = {"method": "mass"}  # WATER no co-product: the study shares nothing
    scope["transport"] = [
        {
            "id": "road",
            "applies_to": ["feed:*"],
            "distance_km": 100,
            "missing": "x",
            "source": "test",
        }
    ]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert not _compat(report)


def test_a_dataset_link_of_another_allocation_or_system_model(blocks: Path) -> None:
    dataset = yaml.safe_load(yaml.safe_dump(FEEDSTOCK))
    dataset["system_model"] = "apos"
    ref = {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK", "allocation": "none"}
    _with_dataset(blocks, dataset, ref)
    scope = yaml.safe_load((blocks / "lca" / "lca.yaml").read_text())
    scope["allocation"]["method"] = "mass"  # PROD and WATER share the burdens
    scope["flows"].insert(0, {"key": "feed:FEEDSTOCK", "free": True, "source": "a decoy"})
    _write(blocks, scope)
    report = lca_report(blocks)
    (finding,) = _compat(report)
    assert finding.level == "warning"
    assert finding.file == "lca/lca.yaml"
    text = (blocks / "lca" / "lca.yaml").read_text().splitlines()
    assert "key: feed:FEED" in text[finding.line - 1] and "FEEDSTOCK" not in text[finding.line - 1]
    assert finding.ids == ["feed:FEED", "lca/datasets/feedstock.yaml"]
    assert "feed:FEED links lca/datasets/feedstock.yaml#FEEDSTOCK" in finding.message
    assert "its 2 products are allocated by none, the study's by mass" in finding.message
    assert "it is modelled apos, the study cutoff" in finding.message
    assert finding.hint
    # a declared proxy says why the link stands: info, not a warning
    scope["flows"][1]["proxy"] = "the closest feedstock dataset; allocation and model differ"
    _write(blocks, scope)
    (finding,) = _compat(lca_report(blocks))
    assert finding.level == "info"


def test_a_dataset_product_of_another_substance_grade_or_pressure(blocks: Path) -> None:
    # the plant's FEED is water-rich (mass purity 0.6 H2O, CAS 7732-18-5) at 3 bar(a)
    dataset = yaml.safe_load(yaml.safe_dump(FEEDSTOCK))
    product = dataset["exchanges"][0]
    product["cas"] = "64-17-5"
    product["state"] = {"phase": "liquid", "pressure": 1.0, "purity": 0.5, "basis": "mass"}
    _with_dataset(blocks, dataset, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    report = lca_report(blocks)
    (finding,) = _compat(report)
    assert "another substance (CAS 64-17-5, the plant takes 7732-18-5)" in finding.message
    assert "a lower grade (mass purity 0.5, the plant takes 0.6)" in finding.message
    assert "delivered at 1 bar(a), the plant takes it at 3: the compression is in neither" in (
        finding.message
    )
    # the same substance, grade and pressure (zero-padded CAS, another purity basis): nothing
    product["cas"] = "0007732-18-5"
    product["state"] = {"pressure": 3.01, "purity": 0.1, "basis": "mole"}
    _with_dataset(blocks, dataset, {"path": "lca/datasets/feedstock.yaml", "product": "FEEDSTOCK"})
    assert not _compat(lca_report(blocks))
