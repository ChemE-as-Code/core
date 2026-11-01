"""Open data and transparent coverage: the source registry, packaged open
profiles, gaps instead of silent zeros, the result's classification, compatibility warnings and the
foreground exported without a background.

The plant is ``examples/process-blocks``: 1 t of product is 2.5 h of operation, 2500 kg feed,
875 kWh steam and 1500 kg waste water.
"""

import copy
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.backgrounds import profile, profiles, resolve
from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import (
    GAPS_CSV,
    gaps_csv,
    lca_report,
    outputs,
    results_markdown,
)
from chemeascode.domains.assessment.lca.schemas import Factor, FactorFile, FlowMap, LciDataset
from chemeascode.interfaces.cli import app

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"

SOURCE = {
    "id": "open-test",
    "title": "Open test factors",
    "provider": "Test agency",
    "version": "1.0",
    "licence": "CC0-1.0",
    "publication": "public",
    "redistribution": True,
    "geography": "GB",
    "method": "IPCC 2021 GWP100",
}


def _factor(fid: str, unit: str, values: dict, **extra) -> dict:
    return {
        "id": fid,
        "unit": unit,
        "values": values,
        "status": "PUBLISHED",
        "source": "test table",
        "source_id": "open-test",
        "year": 2025,
        "location": "GB",
        **extra,
    }


SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
    "location": "GB",
    "year": 2025,
    "allocation": {"method": "none"},
    "flows": [
        {"key": "feed:FEED", "factor": "feed", "source": "test"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
        {"key": "product:WATER", "factor": "wastewater", "source": "test"},
    ],
}
FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "sources": [SOURCE],
    "categories": [
        {"id": "gwp", "unit": "kg CO2-eq", "method": "IPCC 2021 GWP100"},
        {"id": "water", "unit": "m3"},
    ],
    "factors": [
        _factor("feed", "kg", {"gwp": 0.5, "water": 0.01}),
        _factor("steam", "kWh", {"gwp": 0.25, "water": 0.0}),
        _factor("wastewater", "t", {"gwp": 1.0, "water": -0.9}),
    ],
}


def _write(root: Path, scope: dict, factors: dict | None) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    path = root / "lca" / "factors.yaml"
    if factors is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(yaml.safe_dump(factors, sort_keys=False))


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    _write(root, SCOPE, FACTORS)
    return root


def _report(root: Path, scope: dict | None = None, factors: dict | None = FACTORS):
    _write(root, scope or SCOPE, factors)
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    return report


# -- classification ------------------------------------------------------------------------


def test_complete_with_published_data_in_every_category(blocks: Path) -> None:
    report = _report(blocks)
    assert report.classification == "complete", report.reasons
    assert report.reasons == []
    assert not report.climate_only
    assert report.label == "LCA, complete within the declared boundary"
    assert [s.id for s in report.sources] == ["open-test"]
    # 2500 x 0.5 + 875 x 0.25 + 1.5 x 1.0
    assert report.totals()["gwp"] == pytest.approx(1250 + 218.75 + 1.5)
    assert "- result: **LCA, complete within the declared boundary**" in results_markdown(report)


def test_climate_only_is_a_screening_carbon_footprint(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["categories"] = factors["categories"][:1]
    for f in factors["factors"]:
        f["values"].pop("water")
    report = _report(blocks, factors=factors)
    assert report.climate_only
    assert report.classification == "screening"
    assert report.label == "screening carbon footprint"
    assert any("climate categories only" in r for r in report.reasons)


def test_assumed_factors_make_a_screening_result(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["status"] = "ASSUMED"
    report = _report(blocks, factors=factors)
    assert report.classification == "screening"
    assert "factors ASSUMED" in report.reasons


def test_example_factors_are_screening(blocks: Path) -> None:
    factors = {**copy.deepcopy(FACTORS), "example": True}
    assert _report(blocks, factors=factors).classification == "screening"


def test_unavailable_when_it_does_not_compute(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0]["factor"] = "nothing"
    _write(blocks, scope, FACTORS)
    report = lca_report(blocks)
    assert not report.loaded
    assert report.classification == "unavailable"
    assert report.reasons == ["the LCA does not compute"]


# -- gaps ----------------------------------------------------------------------------------


def test_a_factor_without_a_category_is_a_gap_not_zero(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["values"].pop("water")
    report = _report(blocks, factors=factors)
    assert report.classification == "partial"
    assert report.label == "partial LCA"
    gaps = [g for g in report.gaps if g.scenario == "baseline"]
    assert [(g.category, g.key, g.reason) for g in gaps] == [
        ("water", "feed:STEAM", "factor-category")
    ]
    assert gaps[0].quantity == pytest.approx(875)
    assert gaps[0].unit == "kWh"
    # no zero contribution pretends to cover it
    assert not [i for i in report.impacts if i.key == "feed:STEAM" and i.category == "water"]
    text = gaps_csv(report)
    assert "baseline,water,feed:STEAM,factor-category,875,kWh,operation,steam" in text
    assert "## Gaps (baseline)" in results_markdown(report)
    assert "no coverage percentage" in results_markdown(report)


def test_an_unmapped_flow_is_a_gap_in_every_category(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["flows"] = scope["flows"][:2]
    report = _report(blocks, scope=scope)
    gaps = {(g.category, g.key, g.reason) for g in report.gaps}
    assert gaps == {("gwp", "product:WATER", "unmapped"), ("water", "product:WATER", "unmapped")}
    assert report.classification == "partial"
    assert lca_gate(blocks, ["no-gaps"]) == [
        "1 exchanges lack a burden in some category (lca/gaps.csv): product:WATER"
    ]


def test_gaps_csv_is_an_output_with_a_header_when_there_is_none(blocks: Path) -> None:
    report = _report(blocks)
    assert outputs(report)[GAPS_CSV] == "scenario,category,key,reason,quantity,unit,phase,detail\n"
    assert lca_gate(blocks, ["no-gaps"]) == []


def test_unlinked_dataset_exchanges_travel_as_gaps(blocks: Path) -> None:
    dataset = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "steam-boiler",
        "basis": "1 kWh of steam",
        "exchanges": [
            {"key": "product:STEAM", "type": "product", "amount": 1, "unit": "kWh"},
            {
                "key": "feed:GAS",
                "type": "input",
                "amount": 1.1,
                "unit": "kWh",
                "link": {"factor": "steam", "source": "gas"},
            },
            {"key": "feed:WATER", "type": "input", "amount": 2, "unit": "kg"},
        ],
    }
    (blocks / "lca" / "boiler.yaml").write_text(yaml.safe_dump(dataset, sort_keys=False))
    scope = copy.deepcopy(SCOPE)
    scope["flows"][1] = {
        "key": "feed:STEAM",
        "dataset": {"path": "lca/boiler.yaml", "product": "STEAM"},
        "source": "test",
    }
    report = _report(blocks, scope=scope)
    gaps = [g for g in report.gaps if g.scenario == "baseline"]
    assert {(g.category, g.key, g.reason) for g in gaps} == {
        ("gwp", "feed:STEAM < lca/boiler.yaml#feed:WATER", "dataset-unlinked"),
        ("water", "feed:STEAM < lca/boiler.yaml#feed:WATER", "dataset-unlinked"),
    }
    # 875 kWh steam x 2 kg water per kWh
    assert gaps[0].quantity == pytest.approx(1750)
    assert gaps[0].unit == "kg"
    assert report.classification == "partial"
    steam = [i for i in report.impacts if i.key == "feed:STEAM" and i.category == "gwp"]
    assert steam[0].value == pytest.approx(875 * 1.1 * 0.25)
    assert steam[0].source_id == "open-test"


# -- registry, proxies, compatibility -------------------------------------------------------


def test_a_proxy_or_estimate_states_basis_and_validity() -> None:
    base = _factor("x", "kg", {"gwp": 1.0})
    with pytest.raises(ValidationError, match="basis and validity"):
        Factor.model_validate({**base, "status": "PROXY"})
    Factor.model_validate(
        {**base, "status": "ESTIMATE", "basis": "stoichiometry", "validity": "pure feed"}
    )


def test_factor_source_ids_are_in_the_registry() -> None:
    bad = copy.deepcopy(FACTORS)
    bad["factors"][0]["source_id"] = "nowhere"
    with pytest.raises(ValidationError, match="not in sources"):
        FactorFile.model_validate(bad)


def test_dataset_exchange_sources_are_in_its_registry() -> None:
    data = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "x",
        "exchanges": [
            {"key": "product:X", "type": "product", "amount": 1, "unit": "kg"},
            {"key": "feed:Y", "type": "input", "amount": 1, "unit": "kg", "source_id": "vendor"},
        ],
    }
    with pytest.raises(ValidationError, match="vendor"):
        LciDataset.model_validate(data)
    LciDataset.model_validate({**data, "sources": [{**SOURCE, "id": "vendor"}]})


def test_a_proxy_mapping_marks_the_contribution_and_screens(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0]["proxy"] = "a similar aqueous feed"
    report = _report(blocks, scope=scope)
    feed = [i for i in report.impacts if i.key == "feed:FEED"]
    assert {i.status for i in feed} == {"PROXY"}
    assert report.classification == "screening"
    assert "factors PROXY" in report.reasons


def test_another_geography_is_flagged(blocks: Path) -> None:
    scope = {**copy.deepcopy(SCOPE), "location": "DE"}
    report = _report(blocks, scope=scope)
    assert any(f.rule == "cheme.lca-geography" for f in report.findings)
    assert report.classification == "screening"
    assert "geography mismatch" in report.reasons


def test_an_old_reference_year_is_flagged(blocks: Path) -> None:
    scope = {**copy.deepcopy(SCOPE), "year": 2040}
    report = _report(blocks, scope=scope)
    assert any(f.rule == "cheme.lca-reference-year" for f in report.findings)
    assert "reference year mismatch" in report.reasons


# -- packaged open profile ------------------------------------------------------------------


def test_the_open_profile_loads_and_permits_publication() -> None:
    assert "desnz-ghg-2026" in profiles()
    desnz = profile("desnz-ghg-2026")
    (source,) = desnz.sources
    assert source.licence == "OGL-3.0"
    assert source.publication == "public"
    assert source.redistribution
    assert source.attribution
    ids = {f.id: f for f in desnz.factors}
    assert ids["electricity-gb"].values["climate-change"] == pytest.approx(0.18436)
    assert ids["electricity-gb"].unit == "kWh"
    assert ids["lorry-hgv-gb"].unit == "tkm"
    assert all(f.source_id == "desnz-ghg-2026" and f.location == "GB" for f in desnz.factors)


def test_include_prefixes_the_profile_factors() -> None:
    study = FactorFile.model_validate(
        {"schema": "cheme/lca/v1", "kind": "lca_factors", "include": ["desnz-ghg-2026"]}
    )
    merged, problems = resolve(study)
    assert problems == []
    assert "desnz-ghg-2026:electricity-gb" in {f.id for f in merged.factors}
    assert [c.id for c in merged.categories] == ["climate-change"]
    bad, problems = resolve(study.model_copy(update={"include": ["nope"]}))
    assert problems and "no packaged profile nope" in problems[0]


def test_a_study_on_the_open_profile(blocks: Path) -> None:
    factors = {
        "schema": "cheme/lca/v1",
        "kind": "lca_factors",
        "include": ["desnz-ghg-2026"],
        "categories": [
            {"id": "climate-change", "unit": "kg CO2-eq", "elementary": "ipcc2021-gwp100"}
        ],
    }
    scope = copy.deepcopy(SCOPE)
    scope["flows"] = [
        {
            "key": "feed:FEED",
            "factor": "desnz-ghg-2026:water-supply-gb",
            "source": "test",
            "proxy": "the aqueous feed as mains water (per m3)",
        },
        {
            "key": "feed:STEAM",
            "factor": "desnz-ghg-2026:natural-gas-gb",
            "source": "test",
            "proxy": "steam as the gas burned for it, boiler efficiency 1",
        },
        {"key": "product:WATER", "factor": "desnz-ghg-2026:water-treatment-gb", "source": "test"},
    ]
    _write(blocks, scope, factors)
    report = lca_report(blocks)
    # kg feed against a factor per m3 is a unit-kind error, not a silent conversion
    assert not report.loaded
    assert any(f.rule == "cheme.lca-factor-unit" for f in report.findings)
    scope["flows"][0] = {"key": "feed:FEED", "free": True, "source": "test"}
    scope["flows"][2] = {"key": "product:WATER", "free": True, "source": "test"}
    report = _report(blocks, scope=scope, factors=factors)
    assert report.totals()["climate-change"] == pytest.approx(875 * 0.21252)
    assert [s.id for s in report.sources] == ["desnz-ghg-2026"]
    assert report.classification == "screening"
    assert report.label == "screening carbon footprint"
    text = results_markdown(report)
    assert "Open Government Licence v3.0" in text
    assert "| OGL-3.0 | public |" in text


def test_mixing_characterisation_methods_in_a_category_is_flagged(tmp_path: Path) -> None:
    from chemeascode.domains.assessment.lca.impacts import Impact
    from chemeascode.domains.assessment.lca.report import LcaReport, _compatibility, classify
    from chemeascode.domains.assessment.lca.schemas import Category, LcaFile

    desnz = profile("desnz-ghg-2026")
    report = LcaReport(
        tmp_path,
        categories=[Category(id="climate-change", unit="kg CO2-eq")],
        impacts=[
            Impact(
                "climate-change",
                "feed:E",
                "e",
                1,
                "kWh",
                1,
                1,
                "PUBLISHED",
                "",
                2026,
                source_id="desnz-ghg-2026",
            ),
            Impact(
                "climate-change",
                "emission:CO2",
                "m",
                1,
                "kg",
                1,
                1,
                "PUBLISHED",
                "",
                None,
                source_id="method:ipcc2021",
            ),
        ],
        sources=list(desnz.sources),
    )
    scope = LcaFile.model_validate(
        {"schema": "cheme/lca/v1", "kind": "lca", "functional_unit": {"product": "P"}}
    )
    found = [f for f in _compatibility(report, scope) if f.level == "warning"]
    assert [f.rule for f in found] == ["cheme.lca-method-mix"]
    assert found[0].message.endswith("methods: AR4/AR5; AR6")
    report.findings = found
    report.inventory = object()  # loaded
    classify(report)
    assert "method mix mismatch" in report.reasons


# -- foreground without a background --------------------------------------------------------


def test_the_foreground_exports_without_factors(blocks: Path, monkeypatch) -> None:
    _write(blocks, SCOPE, None)
    report = lca_report(blocks, inventory_only=True)
    assert report.loaded
    assert report.inventory_only and report.impacts == []
    monkeypatch.chdir(blocks)
    runner = CliRunner()
    dataset = runner.invoke(app, ["assess", "lca", "--dataset"])
    assert dataset.exit_code == 0, dataset.output
    loaded = LciDataset.model_validate(yaml.safe_load(dataset.stdout))
    assert loaded.location == "GB" and loaded.year == 2025
    assert runner.invoke(app, ["assess", "lca", "--inventory"]).exit_code == 0
    # the full LCA still needs its background
    assert runner.invoke(app, ["assess", "lca", "--write"]).exit_code == 1


def test_coverage_prints_the_classification_and_gaps(blocks: Path, monkeypatch) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["values"].pop("water")
    _write(blocks, SCOPE, factors)
    monkeypatch.chdir(blocks)
    shown = CliRunner().invoke(app, ["assess", "lca", "--coverage"])
    assert shown.exit_code == 0, shown.output
    assert "result: partial LCA" in shown.stdout
    assert "water: feed:STEAM 875 kWh: its factor has no value in this category" in shown.stdout
    assert "source: open-test (Test agency, 1.0, CC0-1.0, publication public)" in shown.stdout
    assert "limitation: construction (infrastructure, equipment) not included" in shown.stdout


# -- review fixes ------------------------------------------------------------------------------


def _boiler(root: Path, link: dict, **extra) -> None:
    dataset = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "steam-boiler",
        "exchanges": [
            {"key": "product:STEAM", "type": "product", "amount": 1, "unit": "kWh"},
            {"key": "feed:GAS", "type": "input", "amount": 1.1, "unit": "kWh", "link": link},
        ],
        **extra,
    }
    (root / "lca" / "boiler.yaml").write_text(yaml.safe_dump(dataset, sort_keys=False))


def _steam_from_boiler() -> dict:
    scope = copy.deepcopy(SCOPE)
    scope["flows"][1] = {
        "key": "feed:STEAM",
        "dataset": {"path": "lca/boiler.yaml", "product": "STEAM"},
        "source": "test",
    }
    return scope


def test_a_dataset_carries_its_inner_status_geography_and_year(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"][1]["status"] = "ASSUMED"
    _boiler(blocks, {"factor": "steam", "source": "gas"}, location="DE", year=1990)
    report = _report(blocks, scope=_steam_from_boiler(), factors=factors)
    steam = next(i for i in report.impacts if i.key == "feed:STEAM")
    assert (steam.status, steam.location, steam.year) == ("ASSUMED", "DE,GB", 1990)
    assert report.classification == "screening"
    assert "factors ASSUMED" in report.reasons
    assert "geography mismatch" in report.reasons
    assert "reference year mismatch" in report.reasons


def test_every_source_of_a_dataset_is_listed(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["sources"].append({**SOURCE, "id": "open-two", "attribution": "Two attribution"})
    factors["factors"][1]["source_id"] = "open-two"
    vendor = {**SOURCE, "id": "vendor", "title": "Vendor data", "attribution": "Vendor terms"}
    _boiler(blocks, {"factor": "steam", "source": "gas"}, sources=[vendor])
    data = yaml.safe_load((blocks / "lca" / "boiler.yaml").read_text())
    data["exchanges"][1]["source_id"] = "vendor"
    (blocks / "lca" / "boiler.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    report = _report(blocks, scope=_steam_from_boiler(), factors=factors)
    assert [s.id for s in report.sources] == ["open-test", "open-two", "vendor"]
    text = results_markdown(report)
    assert "Two attribution" in text and "Vendor terms" in text


def test_elementary_flows_outside_a_method_are_no_gaps(blocks: Path) -> None:
    from chemeascode.domains.assessment.lca.impacts import real_gaps

    factors = copy.deepcopy(FACTORS)
    factors["categories"][0]["elementary"] = "ipcc2021-gwp100"
    factors["categories"][1]["elementary"] = "none"
    scope = copy.deepcopy(SCOPE)
    scope["flows"][2] = {"key": "product:WATER", "emission": True, "source": "test"}
    scope["flows"] += [
        {"key": "emission:H2O", "free": True, "source": "test"},
        {"key": "emission:ETOH", "elementary": {"compartment": "air"}, "source": "test"},
    ]
    materials = blocks / "process" / "materials.yaml"
    data = yaml.safe_load(materials.read_text())
    for component in data["components"]:
        if component["id"] == "ETOH":
            component["cas"] = "64-17-5"
    materials.write_text(yaml.safe_dump(data, sort_keys=False))
    report = _report(blocks, scope=scope, factors=factors)
    gaps = [g for g in report.gaps if g.key == "emission:ETOH"]
    # gwp: IPCC lists no ethanol: outside the method; water: declared none: nothing at all
    assert [(g.category, g.reason) for g in gaps] == [("gwp", "elementary-uncharacterised")]
    assert real_gaps(report.gaps) == []
    assert report.classification == "complete"
    assert "## Outside the methods (baseline)" in results_markdown(report)
    assert lca_gate(blocks, ["no-gaps"]) == []


def test_substitution_with_a_credit_gap_does_not_apply(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"].append(_factor("water-avoided", "kg", {"gwp": 0.001}))
    scope = copy.deepcopy(SCOPE)
    scope["allocation"] = {
        "method": "none",
        "coproducts": ["PROD", "WATER"],
        "substitution": {"WATER": {"factor": "water-avoided", "source": "test"}},
    }
    scope["flows"] = scope["flows"][:2]
    report = _report(blocks, scope=scope, factors=factors)
    entry = next(e for e in report.comparison if e["method"] == "substitution")
    assert entry["totals"] is None
    assert "substitutes without a burden in some category: substitution:WATER" in entry["problem"]


def test_places_are_compared_as_regions(blocks: Path) -> None:
    from chemeascode.domains.assessment.lca.report import _within

    assert _within("GB", "UK") and _within("UK", "GB") and _within("GB", "GB-ENG")
    assert not _within("GB-ENG", "GB") and not _within("GLO", "GB") and not _within("DE", "GB")
    scope = {**copy.deepcopy(SCOPE), "location": "GB-SCT"}
    report = _report(blocks, scope=scope)
    assert not any(f.rule == "cheme.lca-geography" for f in report.findings)


def test_unchecked_geography_makes_a_result_screening(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    del scope["location"]
    report = _report(blocks, scope=scope)
    assert report.classification == "screening"
    assert report.reasons == ["geography or reference year not checked"]


def test_a_conflicting_profile_source_is_a_problem() -> None:
    study = FactorFile.model_validate(
        {
            "schema": "cheme/lca/v1",
            "kind": "lca_factors",
            "include": ["desnz-ghg-2026"],
            "sources": [{**SOURCE, "id": "desnz-ghg-2026"}],
        }
    )
    _, problems = resolve(study)
    assert any("source desnz-ghg-2026 of profile desnz-ghg-2026 differs" in p for p in problems)


def test_a_scenario_with_gaps_is_marked(blocks: Path) -> None:
    factors = copy.deepcopy(FACTORS)
    factors["factors"].append(_factor("steam-alt", "kWh", {"gwp": 0.1}))
    scope = {
        **copy.deepcopy(SCOPE),
        "scenarios": [{"id": "alt", "factors": {"steam": "steam-alt"}}],
    }
    report = _report(blocks, scope=scope, factors=factors)
    assert report.classification == "complete"  # the baseline
    assert "| category | unit | baseline | alt (with gaps) |" in results_markdown(report)


def test_a_declared_missing_background_is_a_gap_and_counts_as_mapped(blocks: Path) -> None:
    scope = copy.deepcopy(SCOPE)
    scope["flows"][2] = {
        "key": "product:WATER",
        "missing": "no open factor for this waste water treatment yet",
        "source": "test",
    }
    report = _report(blocks, scope=scope)
    rows = {r.key: r for r in report.inventory.rows}
    assert rows["product:WATER"].mapping.startswith("missing: no open factor")
    gaps = {(g.category, g.key, g.reason) for g in report.gaps}
    assert gaps == {("gwp", "product:WATER", "missing"), ("water", "product:WATER", "missing")}
    assert report.classification == "partial"
    # a decision was made for every flow: mapped holds, no-gaps does not
    assert lca_gate(blocks, ["mapped"]) == []
    assert lca_gate(blocks, ["no-gaps"]) != []
    with pytest.raises(ValidationError, match="missing take no factor"):
        FlowMap.model_validate({"key": "feed:X", "factor": "f", "missing": "why", "source": "test"})
