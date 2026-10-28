"""Publication policy, the run manifest and public snapshots of an LCA (pre-release issue 138).

The plant is ``examples/process-blocks`` with the factors of ``test_lca_coverage``.
"""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import (
    MANIFEST_FILE,
    lca_report,
    manifest,
    outputs,
    results_markdown,
)
from chemeascode.domains.assessment.lca.scenarios import records
from chemeascode.interfaces.api.export_static import LCA_RESULT_FILES, export_static
from tests.conftest import git
from tests.test_lca_coverage import EXAMPLE, FACTORS, SCOPE, _write


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    _write(root, SCOPE, FACTORS)
    return root


def _with(policy: str | None = None, registered: bool = True, file_policy: str | None = None):
    factors = copy.deepcopy(FACTORS)
    if policy is not None:
        factors["sources"][0]["publication"] = policy
    if not registered:
        for f in factors["factors"]:
            f.pop("source_id")
        factors["sources"] = []
    if file_policy is not None:
        factors["publication"] = file_policy
    return factors


def _report(root: Path, factors: dict, scope: dict | None = None):
    _write(root, scope or SCOPE, factors)
    report = lca_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    return report


def test_public_sources_are_publishable(blocks: Path) -> None:
    report = _report(blocks, FACTORS)
    assert (report.publication, report.publishable, report.restricted_by) == ("public", True, [])
    assert "- publication: public\n" in results_markdown(report)
    assert report.payload()["publication"] == {
        "policy": "public",
        "publishable": True,
        "restricted_by": [],
    }
    assert lca_gate(blocks, ["publishable"]) == []


def test_unregistered_factors_are_restricted_by_default(blocks: Path) -> None:
    report = _report(blocks, _with(registered=False))
    assert report.publication == "restricted"
    assert report.restricted_by == ["unregistered factors"]
    assert not report.publishable
    assert "**not for publication**" in results_markdown(report)
    (problem,) = lca_gate(blocks, ["publishable"])
    assert "restricted sources (unregistered factors)" in problem
    # the project states its own numbers may be published
    assert _report(blocks, _with(registered=False, file_policy="public")).publishable


def test_a_reviewed_decision_allows_restricted_but_never_local(blocks: Path) -> None:
    decision = {
        "allow_restricted": True,
        "review": "reviews/2026-10-24-lca-terms.md",
        "approved_by": "A. Person",
    }
    scope = {**copy.deepcopy(SCOPE), "publication": decision}
    restricted = _report(blocks, _with("restricted"), scope)
    assert restricted.publication == "restricted" and restricted.publishable
    local = _report(blocks, _with("local"), scope)
    assert local.publication == "local" and not local.publishable
    assert local.restricted_by == ["open-test"]


def test_the_most_restrictive_source_wins(blocks: Path) -> None:
    factors = _with()
    factors["sources"].append({**factors["sources"][0], "id": "vendor", "publication": "local"})
    factors["factors"][1]["source_id"] = "vendor"
    report = _report(blocks, factors)
    assert report.publication == "local"
    assert report.restricted_by == ["vendor"]


def test_inventory_only_draws_on_no_background(blocks: Path) -> None:
    _write(blocks, SCOPE, None)
    report = lca_report(blocks, inventory_only=True)
    assert report.publication == "public" and report.publishable


# -- manifest ------------------------------------------------------------------------------


def test_manifest_records_what_the_results_rest_on(blocks: Path) -> None:
    report = _report(blocks, FACTORS)
    data = manifest(report)
    assert data["schema"] == "cheme/lca-manifest/v1"
    assert data["functional_unit"] == "1 t PROD"
    assert set(data["inputs"]) >= {"lca/lca.yaml", "lca/factors.yaml", "process/flowsheet.yaml"}
    assert all(v.startswith("sha256:") for v in data["inputs"].values())
    assert data["mapping"].startswith("sha256:")
    import hashlib

    text = outputs(report)["lca/results.csv"]
    assert data["results"] == "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    assert data["background"]["sources"] == [
        {
            "id": "open-test",
            "title": "Open test factors",
            "provider": "Test agency",
            "version": "1.0",
            "url": "",
            "licence": "CC0-1.0",
            "attribution": "",
            "checksum": "",
            "publication": "public",
        }
    ]
    assert data["categories"][0] == {"id": "gwp", "unit": "kg CO2-eq", "method": "IPCC 2021 GWP100"}
    assert data["result"] == {
        "classification": "complete",
        "label": "LCA, complete within the declared boundary",
        "gaps": 0,
        "publication": "public",
        "publishable": True,
        "factors_published": True,
        "factor_status": {
            "feed:FEED": "PUBLISHED",
            "feed:STEAM": "PUBLISHED",
            "product:PROD": "none",
            "product:WATER": "PUBLISHED",
        },
    }
    assert data["software"]["cheme-as-code"]
    text = outputs(report)[MANIFEST_FILE]
    assert str(blocks) not in text  # no absolute path
    assert text == outputs(lca_report(blocks))[MANIFEST_FILE]  # deterministic


def test_the_manifest_detects_results_written_by_another_run(blocks: Path) -> None:
    import hashlib

    report = _report(blocks, FACTORS)
    files = outputs(report)
    recorded = json.loads(files[MANIFEST_FILE])["results"]

    def sha(text: str) -> str:
        return "sha256:" + hashlib.sha256(text.encode()).hexdigest()

    assert recorded == sha(files["lca/results.csv"])
    assert recorded != sha(files["lca/results.csv"].replace("kg CO2-eq", "kg CO2e"))


def test_a_changed_input_or_mapping_invalidates_the_results(blocks: Path) -> None:
    report = _report(blocks, FACTORS)
    for path, text in outputs(report).items():
        (blocks / path).write_text(text)
    assert lca_gate(blocks, ["lca-current"]) == []
    before = manifest(report)
    factors = copy.deepcopy(FACTORS)
    factors["sources"][0]["version"] = "1.1"  # a new background version, same numbers
    _write(blocks, SCOPE, factors)
    # the scores are the same; the record of what they rest on is not
    assert lca_gate(blocks, ["lca-current"]) == [
        "lca/results.md is not current; run cheme assess lca --write",
        "lca/manifest.json is not current; run cheme assess lca --write",
    ]
    scope = copy.deepcopy(SCOPE)
    scope["flows"][2]["source"] = "another reason"
    _write(blocks, scope, FACTORS)
    after = manifest(lca_report(blocks))
    assert after["mapping"] != before["mapping"]


def test_profiles_are_fingerprinted(blocks: Path) -> None:
    factors = {
        "schema": "cheme/lca/v1",
        "kind": "lca_factors",
        "include": ["desnz-ghg-2026"],
        "categories": [{"id": "climate-change", "unit": "kg CO2-eq"}],
    }
    scope = copy.deepcopy(SCOPE)
    scope["flows"] = [
        {"key": "feed:FEED", "free": True, "source": "test"},
        {"key": "feed:STEAM", "factor": "desnz-ghg-2026:natural-gas-gb", "source": "test"},
        {"key": "product:WATER", "free": True, "source": "test"},
    ]
    report = _report(blocks, factors, scope)
    background = manifest(report)["background"]
    assert [p["id"] for p in background["profiles"]] == ["desnz-ghg-2026"]
    assert background["profiles"][0]["fingerprint"].startswith("sha256:")
    assert background["sources"][0]["checksum"].startswith("sha256:a9a455ab")
    # what a consumer must show with the numbers travels with them
    assert "Open Government Licence v3.0" in background["sources"][0]["attribution"]
    assert background["sources"][0]["url"].startswith("https://www.gov.uk/")
    assert report.publishable  # OGL-3.0: public


# -- public snapshots ----------------------------------------------------------------------


def _committed(root: Path, factors: dict) -> Path:
    _write(root, SCOPE, factors)
    report = lca_report(root)
    for path, text in {**outputs(report), **records(report)}.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text)
    git(root, "init", "-q")
    # an identity of its own: CI runners have none
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "plant")
    return root


def test_a_public_lca_is_in_the_snapshot(blocks: Path, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    data = export_static(_committed(blocks, FACTORS), out)
    assert data["entries"]["lca"]["status"] == 200
    assert data["withheld"] == []
    assert not set(LCA_RESULT_FILES) & set(data["excluded"])
    assert "file?path=lca/results.csv" in data["entries"]
    assert "file?path=lca/scenarios/baseline.json" in data["entries"]


def test_a_restricted_lca_is_withheld_from_the_snapshot(blocks: Path, tmp_path: Path) -> None:
    out = tmp_path / "snap"
    data = export_static(_committed(blocks, _with("restricted")), out)
    assert "lca" not in data["entries"]
    assert data["withheld"] == [
        {
            "endpoint": "lca",
            "reason": "restricted sources: open-test",
            "files": list(LCA_RESULT_FILES),
        }
    ]
    assert set(LCA_RESULT_FILES) <= set(data["excluded"])
    keys = set(data["entries"])
    assert not any(k.startswith(("file?path=lca/results", "file?path=lca/gaps")) for k in keys)
    # the per-scenario records hold the scores too (pre-release issue 172)
    assert not any("lca/scenarios/" in k for k in keys)
    # the foreground stays publishable
    assert "file?path=lca/dataset.yaml" in keys or "yaml?path=lca/dataset.yaml" in keys
    tree = json.loads((out / "data" / data["entries"]["tree"]["file"]).read_text())
    paths = {entry["path"] for entry in tree}
    assert "lca/results.csv" not in paths and "lca/dataset.yaml" in paths
    # no score anywhere in the snapshot
    total = f"{lca_report(blocks).totals()['gwp']:.6g}"
    for entry in data["entries"].values():
        assert total not in (out / "data" / entry["file"]).read_text(errors="replace")
    assert data["entries"]["status"]["status"] == 200


def test_excluding_the_scope_leaves_the_lca_out(blocks: Path, tmp_path: Path) -> None:
    data = export_static(_committed(blocks, FACTORS), tmp_path / "snap", exclude=["lca/**"])
    assert "lca" not in data["entries"]
    assert data["withheld"][0]["reason"] == "an LCA input is excluded"


# -- review fixes (leaks found by the independent review) ------------------------------------


def test_comparison_credits_count_for_the_policy(blocks: Path) -> None:
    from tests.test_lca_coverage import _factor

    factors = copy.deepcopy(FACTORS)
    factors["sources"].append({**factors["sources"][0], "id": "vendor", "publication": "local"})
    factors["factors"].append(
        _factor("water-avoided", "kg", {"gwp": 0.001, "water": 0.002}, source_id="vendor")
    )
    scope = copy.deepcopy(SCOPE)
    scope["allocation"] = {
        "method": "none",
        "coproducts": ["PROD", "WATER"],
        "substitution": {"WATER": {"factor": "water-avoided", "source": "test"}},
    }
    scope["flows"] = scope["flows"][:2]
    report = _report(blocks, factors, scope)
    entry = next(e for e in report.comparison if e["method"] == "substitution")
    assert entry["totals"] is not None
    assert report.publication == "local" and not report.publishable
    assert report.restricted_by == ["vendor"]


def test_an_unregistered_factor_inside_a_dataset_stays_restricted(blocks: Path) -> None:
    dataset = {
        "schema": "cheme/lca/v1",
        "kind": "lci_dataset",
        "id": "x",
        "exchanges": [
            {"key": "product:A", "type": "product", "amount": 1, "unit": "kg"},
            {
                "key": "feed:E",
                "type": "input",
                "amount": 2,
                "unit": "kg",
                "link": {"factor": "secret", "source": "test"},
            },
            {
                "key": "feed:F",
                "type": "input",
                "amount": 2,
                "unit": "kg",
                "link": {"factor": "feed", "source": "test"},
            },
        ],
    }
    (blocks / "lca" / "x.yaml").write_text(yaml.safe_dump(dataset))
    factors = copy.deepcopy(FACTORS)
    factors["factors"].append(
        {
            "id": "secret",
            "unit": "kg",
            "values": {"gwp": 7.0, "water": 1.0},
            "status": "PUBLISHED",
            "source": "vendor sheet",
            "year": 2025,
            "location": "GB",
        }
    )
    scope = copy.deepcopy(SCOPE)
    scope["flows"][0] = {
        "key": "feed:FEED",
        "dataset": {"path": "lca/x.yaml", "product": "A"},
        "source": "test",
    }
    report = _report(blocks, factors, scope)
    assert not report.publishable
    assert "unregistered factors" in report.restricted_by


def test_a_snapshot_fails_closed_when_the_lca_does_not_compute(
    blocks: Path, tmp_path: Path
) -> None:
    root = _committed(blocks, _with("local"))
    # the committed results came from a run with a local source; here the factors are absent
    git(root, "rm", "-q", "lca/factors.yaml")
    git(root, "commit", "-q", "-m", "factors kept private")
    data = export_static(root, tmp_path / "snap")
    assert not any(k.startswith("file?path=lca/results") for k in data["entries"])
    assert data["withheld"][0]["reason"].startswith("the LCA does not compute here")


def test_committed_results_of_another_run_are_withheld(blocks: Path, tmp_path: Path) -> None:
    # results committed from a restricted run, the current inputs public
    root = _committed(blocks, _with("restricted"))
    _write(root, SCOPE, FACTORS)
    git(root, "commit", "-q", "-am", "now public factors, outputs not rewritten")
    data = export_static(root, tmp_path / "snap")
    assert data["entries"]["lca"]["status"] == 200  # this run's answer is publishable
    assert "file?path=lca/results.csv" not in data["entries"]
    assert "committed lca/manifest.json" in data["withheld"][0]["reason"]


def test_excluding_the_factors_withholds_the_lca(blocks: Path, tmp_path: Path) -> None:
    data = export_static(
        _committed(blocks, FACTORS), tmp_path / "snap", exclude=["lca/factors.yaml"]
    )
    assert "lca" not in data["entries"]
    assert data["withheld"][0]["reason"] == "an LCA input is excluded"
    assert not any(k.startswith("file?path=lca/results") for k in data["entries"])


def test_an_lca_built_from_an_excluded_file_is_withheld(blocks: Path, tmp_path: Path) -> None:
    """pre-release issue 230: not an LCA input of LCA_INPUTS, but the LCA reads the flowsheet."""
    from chemeascode.interfaces.api.export_static import LCA_RESULT_FILES

    data = export_static(
        _committed(blocks, FACTORS), tmp_path / "snap", exclude=["process/flowsheet.yaml"]
    )
    assert "lca" not in data["entries"]
    assert data["withheld"][0] == {
        "endpoint": "lca",
        "reason": "built from files matching --exclude process/flowsheet.yaml",
        "files": list(LCA_RESULT_FILES),
    }
    assert [w["endpoint"] for w in data["withheld"]].count("lca") == 1
    assert not any(k.startswith("file?path=lca/results") for k in data["entries"])
