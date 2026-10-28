"""``kind: maturity`` gates of checks/checks.yaml and the read-only report payload.

The fixtures are copies of examples/process-ammonia with the test-only design basis of
tests/test_maturity.py in place of the example's own (no scientific data is added: the edit that
reaches ``balanced`` only relabels an existing value's provenance, as test_maturity.py does), or
without any design basis.
"""

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.foundation.schemas.checks import Check
from chemeascode.foundation.workspace import Workspace
from chemeascode.project import checks as checks_module
from chemeascode.project import validate as validate_module
from chemeascode.project.checks import run_checks
from chemeascode.project.maturity import (
    MATURITY_FILE,
    claim_level,
    maturity_gate,
    maturity_payload,
    maturity_report,
)
from tests.test_maturity import DESIGN_BASIS, EXAMPLES


def _ammonia(tmp_path: Path, *, sourced: bool = True, balanced: bool = False) -> Path:
    root = tmp_path / "process-ammonia"
    shutil.copytree(EXAMPLES / "process-ammonia", root)
    basis = root / "process" / "design-basis.yaml"
    if sourced:
        basis.write_text(DESIGN_BASIS, encoding="utf-8")
    else:
        basis.unlink()
    if balanced:
        flowsheet = root / "process" / "flowsheet.yaml"
        text = flowsheet.read_text(encoding="utf-8")
        flowsheet.write_text(
            text.replace(
                'provenance: assumed, source: "loop balance; all NH3 condensed"',
                'provenance: given, source: "test fixture: as if from a cited separator model"',
            ),
            encoding="utf-8",
        )
    return root


def _claim(root: Path, maturity: str) -> None:
    (root / "process.yaml").write_text(
        f"schema: cheme-as-code/process/v1\nid: x\nmaturity: {maturity}\n"
        "validation: {status: unreviewed}\n",
        encoding="utf-8",
    )


def _gate(**fields) -> dict:
    return {"id": "m", "title": "Maturity", "stage": "concept", "kind": "maturity", **fields}


def _run(root: Path, *gates: dict) -> dict:
    (root / "checks").mkdir(exist_ok=True)
    (root / "checks" / "checks.yaml").write_text(yaml.safe_dump({"checks": list(gates)}))
    return {r.id: r for r in run_checks(Workspace(root))}


def _count_validations(monkeypatch) -> list[int]:
    calls = [0]
    original = validate_module.validate_workspace

    def counted(workspace):
        calls[0] += 1
        return original(workspace)

    monkeypatch.setattr(checks_module, "validate_workspace", counted)
    monkeypatch.setattr(validate_module, "validate_workspace", counted)
    return calls


def test_the_gate_passes_at_the_level_and_fails_above_it_naming_the_requirements(
    tmp_path, monkeypatch
):
    root = _ammonia(tmp_path)
    calls = _count_validations(monkeypatch)
    found = _run(root, _gate(id="sourced", require=["sourced"]), _gate(require=["balanced"]))
    assert found["sourced"].status == "pass", found["sourced"].detail
    assert found["sourced"].evidence["level"] == "sourced"
    result = found["m"]
    assert result.status == "fail"
    assert result.detail.startswith("calculation maturity sourced below balanced: ")
    assert "cheme.maturity-balanced-model-basis fail" in result.detail
    assert "run `cheme maturity`" in result.detail
    failing = result.evidence["failing"]
    assert [f["rule"] for f in failing] == ["cheme.maturity-balanced-model-basis"]
    assert all(f["file"] and f["hint"] for f in failing)
    # only the levels the gate needs: no engineering level, no whole-repository validation
    assert result.evidence["evaluated_through"] == "balanced"
    assert calls[0] == 0
    assert not (root / MATURITY_FILE).exists() and not (root / "checks" / "status.json").exists()


def test_the_gate_passes_once_the_evidence_reaches_the_level(tmp_path):
    root = _ammonia(tmp_path, balanced=True)
    result = _run(root, _gate(require=["balanced"]))["m"]
    assert result.status == "pass", result.detail
    assert result.evidence["level"] == "balanced"
    assert result.evidence["library_maturity"] == "screening"


def test_no_design_basis_reaches_no_level(tmp_path):
    root = _ammonia(tmp_path, sourced=False)
    result = _run(root, _gate(require=["sourced"]))["m"]
    assert result.status == "fail"
    assert result.detail.startswith("calculation maturity none below sourced: ")
    assert "cheme.maturity-sourced-design-basis missing" in result.detail


def test_max_claim_fails_a_claim_above_the_evidence_and_passes_one_within_it(tmp_path):
    root = _ammonia(tmp_path)
    _claim(root, "screening")
    result = _run(root, _gate(max_claim=True))["m"]
    assert result.status == "fail"
    # the claim's finding as the requirements': file:line, rule, message, hint
    assert result.detail.startswith(
        "process.yaml:3: cheme.maturity-claim-exceeds design maturity screening claimed"
    )
    assert result.detail.endswith(
        "(lower the claim, or add the evidence the failing requirements name)"
    )
    assert result.evidence["claimed_maturity"] == "screening"
    claim = result.evidence["claim"]
    assert (claim["file"], claim["line"], claim["rule"]) == (
        "process.yaml",
        3,
        "cheme.maturity-claim-exceeds",
    )
    assert claim["message"] and claim["hint"]
    # screening is first supported by balanced: evaluated through it, not beyond
    assert result.evidence["evaluated_through"] == "balanced"
    _claim(root, "concept")
    assert _run(root, _gate(max_claim=True))["m"].status == "pass"
    # without a manifest there is no claim to exceed
    (root / "process.yaml").unlink()
    assert _run(root, _gate(max_claim=True))["m"].status == "pass"


def test_a_claim_no_level_supports_always_exceeds_without_the_engineering_level(tmp_path):
    root = _ammonia(tmp_path, balanced=True)
    _claim(root, "operating-reference")
    assert claim_level(root) == ("operating-reference", None)
    problems, evidence = maturity_gate(root, "balanced", max_claim=True)
    assert len(problems) == 1 and "operating-reference claimed" in problems[0]
    assert evidence["evaluated_through"] == "balanced"


def test_the_engineering_level_shares_the_runs_validation(tmp_path, monkeypatch):
    root = _ammonia(tmp_path, balanced=True)
    calls = _count_validations(monkeypatch)
    found = _run(
        root,
        {"id": "v", "title": "Valid", "stage": "concept", "kind": "validate"},
        _gate(require=["engineering"]),
        _gate(id="m2", require=["engineering"], max_claim=True),
    )
    assert calls[0] == 1
    result = found["m"]
    assert result.status == "fail"
    assert result.evidence["evaluated_through"] == "engineering"
    rules = {f["rule"] for f in result.evidence["failing"]}
    assert "cheme.maturity-engineering-equipment-list" in rules


@pytest.mark.parametrize(
    "fields, message",
    [
        ({"kind": "maturity"}, "needs require"),
        ({"kind": "maturity", "require": ["sourced", "balanced"]}, "one level"),
        ({"kind": "maturity", "require": ["site"]}, "one level"),
        ({"kind": "layout-model", "require": ["balanced"]}, "belong to a kind: maturity"),
        ({"kind": "files", "max_claim": True}, "max_claim belongs"),
    ],
)
def test_the_schema_refuses_a_malformed_maturity_gate(fields, message):
    with pytest.raises(ValidationError, match=message):
        Check.model_validate({"id": "m", "title": "M", "stage": "concept", **fields})


def test_the_payload_is_the_report_and_writes_nothing(tmp_path):
    root = _ammonia(tmp_path, balanced=True)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    data = maturity_payload(root, through="predictive")
    after = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    assert before == after
    expected = maturity_report(root, through="predictive").as_dict()
    data.pop("checked_at"), expected.pop("checked_at")
    assert data == expected
    assert data["evaluated_through"] == "predictive"
    levels = {lv["id"]: lv for lv in data["levels"]}
    assert levels["engineering"]["status"] == "not-evaluated"
    assert levels["engineering"]["requirements"] == []
    assert not any(r.startswith("cheme.maturity-engineering") for r in _rules(data))
    with pytest.raises(ValueError, match="unknown calculation maturity level"):
        maturity_report(root, through="detail")


def test_a_claim_above_an_undecided_cap_is_left_undecided(tmp_path):
    root = _ammonia(tmp_path, balanced=True)
    _claim(root, "basic-engineering")
    capped = maturity_report(root, through="balanced")
    assert capped.level == "balanced"
    assert capped.manifest["claim_exceeds_evidence"] is None
    assert not [f for f in capped.findings if f.rule == "cheme.maturity-claim-exceeds"]
    full = maturity_report(root)
    assert full.manifest["claim_exceeds_evidence"] is True
    assert full.as_dict()["evaluated_through"] == "engineering"


def _rules(data: dict) -> list[str]:
    return [f["rule"] for f in data["findings"]]
