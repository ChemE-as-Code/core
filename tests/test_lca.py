"""``cheme assess lca``: the foreground inventory, allocation, factors and the lca gate.

The plant is ``examples/process-blocks``: 1000 kg/h feed and 350 kW of steam make 400 kg/h of
product and 600 kg/h of waste water (3.33 % ethanol).
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import (
    DATASET_FILE,
    GAPS_CSV,
    INVENTORY_CSV,
    MANIFEST_FILE,
    RESULTS_CSV,
    RESULTS_MD,
    dataset_yaml,
    gaps_csv,
    inventory_csv,
    lca_report,
    manifest_json,
    results_csv,
    results_markdown,
)
from chemeascode.foundation.schemas.checks import Check
from chemeascode.interfaces.cli import app

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"

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
}
FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [
        {"id": "gwp", "title": "Climate change", "unit": "kg CO2-eq", "method": "IPCC 2021"},
        {"id": "water", "unit": "m3"},
    ],
    "factors": [
        {
            "id": "feed",
            "unit": "kg",
            "values": {"gwp": 0.5, "water": 0.01},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
        {
            "id": "steam",
            "unit": "MJ",
            "values": {"gwp": 0.07, "water": 0},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
        {
            "id": "wastewater",
            "unit": "t",
            "values": {"gwp": 1.0, "water": -0.9},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
        {
            "id": "ethanol-air",
            "unit": "kg",
            "values": {"gwp": 2.0},
            "status": "ASSUMED",
            "source": "test",
            "year": 2025,
        },
    ],
}


def _write(root: Path, scope: dict, factors: dict | None = None) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors or FACTORS, sort_keys=False))


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    _write(root, SCOPE)
    return root


def _rows(report):
    return {row.key: row for row in report.inventory.rows}


def test_inventory_per_functional_unit(blocks: Path) -> None:
    report = lca_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    rows = _rows(report)
    # 1 t of product is 2.5 h of operation
    assert rows["feed:FEED"].quantity == pytest.approx(2500)
    assert rows["feed:STEAM"].quantity == pytest.approx(875)
    assert rows["feed:STEAM"].unit == "kWh"
    assert rows["feed:STEAM"].provenance == "assumed"
    assert rows["product:PROD"].mapping == "coproduct"
    assert rows["product:PROD"].quantity == pytest.approx(1000)
    assert rows["product:WATER"].quantity == pytest.approx(1500)
    assert report.inventory.shares == {"PROD": 1.0}


def test_impacts_by_hand(blocks: Path) -> None:
    report = lca_report(blocks)
    totals = report.totals()
    # 2500 kg x 0.5 + 875 kWh x 3.6 MJ/kWh x 0.07 + 1.5 t x 1.0
    assert totals["gwp"] == pytest.approx(1250 + 220.5 + 1.5)
    assert totals["water"] == pytest.approx(25 - 1.35)
    # the blocks' products have no category: the boundary check's warnings (reported, not
    # counted: test_boundary_gaps_are_reported_and_leave_the_inventory_alone)
    assert not [
        f for f in report.findings if f.level != "info" and not f.rule.startswith("cheme.boundary-")
    ], report.findings


def test_mass_allocation_shares(blocks: Path) -> None:
    scope = {**SCOPE, "allocation": {"method": "mass", "coproducts": ["WATER"]}}
    scope["flows"] = [f for f in SCOPE["flows"] if f["key"] != "product:WATER"]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.loaded
    assert report.inventory.shares == pytest.approx({"PROD": 0.4, "WATER": 0.6})
    assert sum(report.inventory.shares.values()) == pytest.approx(1)
    # the product carries 40 % of 1 h's burdens per 400 kg: 1 h per t
    assert report.totals()["gwp"] == pytest.approx(500 + 88.2)


def test_economic_allocation_needs_prices(blocks: Path) -> None:
    scope = {
        **SCOPE,
        "allocation": {
            "method": "economic",
            "coproducts": ["PROD", "WATER"],
            "prices": {"PROD": 1.0, "WATER": 0.0},
        },
    }
    scope["flows"] = SCOPE["flows"][:2]
    _write(blocks, scope)
    assert lca_report(blocks).inventory.shares == {"PROD": 1.0, "WATER": 0.0}
    del scope["allocation"]["prices"]["WATER"]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    assert "economic allocation needs prices of WATER" in report.findings[0].message


def test_emissions_split_into_components(blocks: Path) -> None:
    scope = {**SCOPE}
    scope["flows"] = SCOPE["flows"][:2] + [
        {"key": "product:WATER", "emission": True, "source": "test"},
        {"key": "emission:ETOH", "factor": "ethanol-air", "source": "test"},
    ]
    _write(blocks, scope)
    report = lca_report(blocks)
    rows = _rows(report)
    assert rows["emission:ETOH"].quantity == pytest.approx(600 * 0.0333333 * 2.5)
    assert rows["emission:H2O"].mapping == ""
    unmapped = [f for f in report.findings if f.rule == "cheme.lca-unmapped"]
    assert unmapped and unmapped[0].ids == ["emission:H2O"]
    assert unmapped[0].line is not None
    gwp = {i.key: i.value for i in report.impacts if i.category == "gwp"}
    assert gwp["emission:ETOH"] == pytest.approx(100, rel=1e-5)
    # ethanol-air has no water value
    assert any(f.rule == "cheme.lca-factor-category" for f in report.findings)


def test_factor_problems(blocks: Path) -> None:
    factors = json.loads(json.dumps(FACTORS))
    factors["factors"][1]["unit"] = "kg"
    factors["factors"] = [f for f in factors["factors"] if f["id"] != "wastewater"]
    _write(blocks, SCOPE, factors)
    report = lca_report(blocks)
    rules = {f.rule for f in report.findings}
    assert {"cheme.lca-factor-unit", "cheme.lca-factor-unknown"} <= rules
    assert not report.loaded


def test_wrong_functional_unit_and_case(blocks: Path) -> None:
    _write(blocks, {**SCOPE, "functional_unit": {"product": "STEAM"}})
    assert lca_report(blocks).findings[0].rule == "cheme.lca-functional-unit"
    _write(blocks, {**SCOPE, "case": "winter"})
    assert lca_report(blocks).findings[0].rule == "cheme.lca-case"


def test_missing_files(tmp_path: Path, blocks: Path) -> None:
    (blocks / "lca" / "factors.yaml").unlink()
    report = lca_report(blocks)
    assert not report.loaded
    assert report.findings[0].rule == "cheme.lca-no-factors"


def test_cli_matches_function_and_writes(blocks: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(blocks)
    runner = CliRunner()
    shown = runner.invoke(app, ["assess", "lca", "--csv"])
    assert shown.exit_code == 0, shown.output
    assert shown.stdout == results_csv(lca_report(blocks))
    check = runner.invoke(app, ["assess", "lca", "--check"])
    assert check.exit_code == 1
    assert runner.invoke(app, ["assess", "lca", "--write"]).exit_code == 0
    for name in (INVENTORY_CSV, RESULTS_CSV, RESULTS_MD):
        assert (blocks / name).is_file()
    assert runner.invoke(app, ["assess", "lca", "--check"]).exit_code == 0
    assert (blocks / INVENTORY_CSV).read_text() == inventory_csv(lca_report(blocks))
    markdown = (blocks / RESULTS_MD).read_text()
    assert "# LCA per 1 t PROD" in markdown
    payload = json.loads(runner.invoke(app, ["assess", "lca", "--json"]).stdout)
    assert payload["totals"]["gwp"] == pytest.approx(1472)
    assert "lca/lca.yaml" in payload["source"]["fingerprints"]


def test_gate(blocks: Path) -> None:
    assert lca_gate(blocks, ["mapped", "factors"]) == []
    problems = lca_gate(blocks, ["lca-current"])
    assert len(problems) == 6 and "run cheme assess lca --write" in problems[0]
    report = lca_report(blocks)
    (blocks / INVENTORY_CSV).write_text(inventory_csv(report))
    (blocks / RESULTS_CSV).write_text(results_csv(report))
    (blocks / RESULTS_MD).write_text(results_markdown(report))
    (blocks / DATASET_FILE).write_text(dataset_yaml(report))
    assert lca_gate(blocks, ["lca-current"]) == [
        "no lca/gaps.csv; run cheme assess lca --write",
        "no lca/manifest.json; run cheme assess lca --write",
    ]
    (blocks / GAPS_CSV).write_text(gaps_csv(report))
    (blocks / MANIFEST_FILE).write_text(manifest_json(report))
    assert lca_gate(blocks, ["lca-current"]) == []
    _write(blocks, {**SCOPE, "flows": SCOPE["flows"][:2]}, {**FACTORS, "example": True})
    problems = lca_gate(blocks, ["mapped", "factors", "lca-current"])
    assert any("product:WATER" in p for p in problems)
    assert any("is an example" in p for p in problems)
    assert any("not current" in p for p in problems)


def test_check_schema() -> None:
    Check(id="lca", title="LCA", stage="basic", kind="lca", require=["mapped", "lca-current"])
    with pytest.raises(ValueError, match="requires only"):
        Check(id="lca", title="LCA", stage="basic", kind="lca", require=["rates"])
    with pytest.raises(ValueError, match="kind: lca check"):
        Check(id="3d", title="3D", stage="basic", kind="layout-model", require=["mapped"])


def test_validate_reads_the_lca_files(blocks: Path) -> None:
    from chemeascode.project.validate import validate_list

    findings, model = validate_list(blocks / "lca" / "lca.yaml", "lca", "lca/lca.yaml")
    assert findings == [] and model.functional_unit.product == "PROD"
    (blocks / "lca" / "factors.yaml").write_text("schema: cheme/lca/v1\nkind: lca_factors\n")
    findings, model = validate_list(
        blocks / "lca" / "factors.yaml", "lca_factors", "lca/factors.yaml"
    )
    assert model is None and findings[0].rule == "yaml.schema"


def test_imports_without_cli() -> None:
    code = (
        "import sys; import chemeascode.domains.assessment.lca.report; "
        "assert 'typer' not in sys.modules and 'fastapi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def _edit_flowsheet(root: Path, old: str, new: str) -> None:
    path = root / "process" / "flowsheet.yaml"
    text = path.read_text()
    assert text.count(old) == 1, old
    path.write_text(text.replace(old, new))


def test_gate_fails_when_the_inventory_fails(blocks: Path) -> None:
    _write(blocks, {**SCOPE, "functional_unit": {"product": "BOGUS"}})
    problems = lca_gate(blocks, ["mapped"])
    assert problems and "BOGUS" in problems[0]
    _write(blocks, {**SCOPE, "allocation": {"method": "mass", "coproducts": ["NOPE"]}})
    assert "NOPE" in lca_gate(blocks, ["factors"])[0]


def test_emission_without_molar_mass_is_an_error(blocks: Path) -> None:
    _edit_flowsheet(
        blocks,
        "values: {ETOH: 0.0333333, H2O: 0.9666667}",
        "values: {ETOH: 0.0333333, H2O: 0.9666667, XYZ: 0.0}",
    )
    _edit_flowsheet(
        blocks,
        "        flow: {value: 600, provenance: assumed}\n"
        "        composition: {basis: mass_fraction",
        "        flow: {value: 600, provenance: assumed}\n"
        "        composition: {basis: mole_fraction",
    )
    materials = blocks / "process" / "materials.yaml"
    text = materials.read_text()
    assert "molar_mass" in text
    import re

    materials.write_text(re.sub(r"molar_mass: [0-9.]+", "molar_mass: null", text))
    scope = {**SCOPE}
    scope["flows"] = SCOPE["flows"][:2] + [
        {"key": "product:WATER", "emission": True, "source": "test"}
    ]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    rules = {f.rule for f in report.findings if f.level == "error"}
    assert "cheme.lca-emission-components" in rules


def test_economic_allocation_prices_the_functional_unit(blocks: Path) -> None:
    scope = {**SCOPE, "flows": SCOPE["flows"][:2]}
    scope["allocation"] = {"method": "economic", "coproducts": ["WATER"], "prices": {"WATER": 1}}
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    assert report.findings[0].rule == "cheme.lca-allocation"
    assert "no price of PROD" in report.findings[0].message
    scope["allocation"]["prices"] = {"WATER": 0, "PROD": 0}
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.findings[0].rule == "cheme.lca-allocation"
    assert lca_gate(blocks, ["mapped"])


def test_feed_to_product_bypass_counts_at_both_ends(blocks: Path) -> None:
    _edit_flowsheet(
        blocks,
        "  - {id: FEED, title: Aqueous feed, ports: [{id: out, direction: out}]}",
        "  - {id: FEED, title: Aqueous feed, ports: [{id: out, direction: out}, "
        "{id: by, direction: out}]}",
    )
    _edit_flowsheet(
        blocks,
        "  - {id: WATER, title: Waste water, ports: [{id: in, direction: in}]}",
        "  - {id: WATER, title: Waste water, ports: [{id: in, direction: in}, "
        "{id: by, direction: in}]}",
    )
    path = blocks / "process" / "flowsheet.yaml"
    path.write_text(
        path.read_text()
        + """  - id: B1
    title: Bypass
    from: FEED.by
    to: WATER.by
    template: aqueous
    state:
      design:
        flow: {value: 100, provenance: assumed}
        composition: {basis: mass_fraction, values: {ETOH: 0.4, H2O: 0.6}, provenance: assumed}
"""
    )
    report = lca_report(blocks)
    rows = _rows(report)
    assert rows["feed:FEED"].plant == pytest.approx(1100)
    assert rows["product:WATER"].plant == pytest.approx(700)


def test_duty_unit_and_sign(blocks: Path) -> None:
    _edit_flowsheet(
        blocks,
        "duty: {value: 350, provenance: assumed}",
        "duty: {value: 350, unit: kJ/h, provenance: assumed}",
    )
    report = lca_report(blocks)
    assert not report.loaded
    assert any(f.rule == "cheme.lca-flow-invalid" for f in report.findings)
    _edit_flowsheet(
        blocks,
        "duty: {value: 350, unit: kJ/h, provenance: assumed}",
        "duty: {value: -350, provenance: assumed}",
    )
    report = lca_report(blocks)
    assert any(
        f.rule == "cheme.lca-flow-invalid" and "negative" in f.message for f in report.findings
    )


def test_boundary_gaps_are_reported_and_leave_the_inventory_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The boundary check of the TEA, in the LCA:
    reported beside the scope's boundary, never added to the inventory or the classification."""
    # process-recycle: the blocks' terminals, its cooler E1 with no energy stream, no categories
    root = tmp_path / "recycle"
    shutil.copytree(EXAMPLE.parent / "process-recycle", root)
    _write(root, SCOPE)
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.boundary_check is not None and not report.boundary_check.complete
    assert report.boundary_check.unassigned_duties == ["E1"]
    payload = report.payload()
    assert payload["boundary"] == report.boundary  # the scope's statement, as before
    check = payload["boundary_check"]
    assert check["complete"] is False and check["unassigned_duties"] == ["E1"]
    assert check["checked"] and check["noted"] and check["not_checked"]
    gaps = {(g["rule"], tuple(g["ids"])) for g in check["gaps"]}
    assert ("cheme.boundary-utility-unassigned", ("E1",)) in gaps
    assert ("cheme.boundary-unclassified", ("WATER",)) in gaps
    assert all(g["file"] == "process/flowsheet.yaml" and g["line"] for g in check["gaps"])
    # the same findings, with file, line, rule and hint, are the report's, after its own
    found = [f for f in report.findings if f.rule.startswith("cheme.boundary-")]
    assert len(found) == len(check["gaps"]) and all(f.line and f.hint for f in found)
    assert report.findings[-len(found) :] == found
    text = results_markdown(report)
    assert "**Incomplete boundary:" in text and "## Boundary check" in text
    assert "the utilities (steam, cooling, refrigeration, power) of E1" in text
    assert "Not classified (no category): PROD, WATER." in text
    assert "It does not check:" in text and "step-to-step" in text
    # the inventory is the terminals' as before: the gap is reported, not inventoried
    assert set(_rows(report)) == {"feed:FEED", "feed:STEAM", "product:PROD", "product:WATER"}
    monkeypatch.chdir(root)
    runner = CliRunner()
    shown = runner.invoke(app, ["assess", "lca", "--coverage"])
    assert shown.exit_code == 0, shown.output
    assert "boundary check: gaps (cheme.boundary-unclassified, cheme.boundary-utility-" in (
        shown.stdout
    )
    assert "utilities in no exchange: E1" in shown.stdout
    assert "process/flowsheet.yaml:" in shown.stderr
    assert "cheme.boundary-utility-unassigned" in shown.stderr
    as_json = json.loads(runner.invoke(app, ["assess", "lca", "--json"]).stdout)
    assert as_json["boundary_check"] == json.loads(json.dumps(check))


def test_a_classified_boundary_has_no_gap_and_the_same_lca(blocks: Path) -> None:
    before = lca_report(blocks)
    path = blocks / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["feeds"][0]["category"] = "raw_material"
    data["feeds"][1]["category"] = "utility"
    data["products"][0]["category"] = "product"
    data["products"][1]["category"] = "wastewater"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = lca_report(blocks)
    assert report.loaded and report.boundary_check.complete
    assert not before.boundary_check.complete
    assert report.payload()["boundary_check"]["unassigned_duties"] == []
    assert not [
        f for f in report.findings if f.rule.startswith("cheme.boundary-") and f.level != "info"
    ]
    text = results_markdown(report)
    assert "Incomplete boundary" not in text
    assert "No warning from the boundary check" in text
    # classifying changes what is reported, not the inventory, the totals or the label
    assert report.totals() == before.totals()
    assert (report.classification, report.reasons) == (before.classification, before.reasons)


def test_mapped_coproduct_and_unconnected_feed_warn(blocks: Path) -> None:
    _edit_flowsheet(
        blocks,
        "  - {id: STEAM,",
        "  - {id: N2, title: Nitrogen, ports: [{id: out, direction: out}]}\n  - {id: STEAM,",
    )
    scope = {
        **SCOPE,
        "flows": [*SCOPE["flows"], {"key": "product:PROD", "free": True, "source": "test"}],
    }
    scope["flows"].append({"key": "feed:N2", "free": True, "source": "test"})
    _write(blocks, scope)
    rules = {f.rule for f in lca_report(blocks).findings}
    assert {"cheme.lca-coproduct-mapped", "cheme.lca-flow-none"} <= rules
