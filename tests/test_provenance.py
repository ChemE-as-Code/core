"""foundation.provenance: source revisions, fingerprints and the optional basis convention."""

import hashlib
import json
import subprocess

import pytest
from pydantic import ValidationError

from chemeascode.foundation.provenance import (
    RELATIONS,
    changed_since,
    file_fingerprint,
    source_revision,
    value_fingerprint,
    written_by,
)
from chemeascode.schemas import ReviewRecord


def _git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    (tmp_path / "a.yaml").write_text("a: 1\n")
    (tmp_path / "b.yaml").write_text("b: 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "one")
    return tmp_path


def test_fingerprint_ignores_line_endings(tmp_path):
    (tmp_path / "unix").write_bytes(b"x\ny\n")
    (tmp_path / "dos").write_bytes(b"x\r\ny\r\n")
    assert file_fingerprint(tmp_path / "unix") == file_fingerprint(tmp_path / "dos")
    assert file_fingerprint(tmp_path / "unix").startswith("sha256:")


def test_source_revision_names_commit_dirty_inputs_and_fingerprints(repo):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    clean = source_revision(repo, ["a.yaml", "b.yaml", "missing.yaml"])
    assert clean.commit == head and clean.committed
    assert set(clean.fingerprints) == {"a.yaml", "b.yaml"}
    (repo / "a.yaml").write_text("a: 2\n")
    edited = source_revision(repo, ["a.yaml", "b.yaml"])
    assert edited.dirty == ("a.yaml",) and not edited.committed
    assert edited.fingerprints["a.yaml"] != clean.fingerprints["a.yaml"]
    assert edited.as_dict()["commit"] == head


def test_source_revision_outside_git(tmp_path):
    (tmp_path / "a.yaml").write_text("a: 1\n")
    found = source_revision(tmp_path, ["a.yaml"])
    assert found.commit is None and not found.committed
    assert "a.yaml" in found.fingerprints


def test_changed_since_commit_and_fingerprint(repo):
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    fingerprint = file_fingerprint(repo / "a.yaml")
    assert changed_since(repo, "a.yaml", head) == []
    assert changed_since(repo, "a.yaml", fingerprint) == []
    (repo / "a.yaml").write_text("a: 2\n")
    assert changed_since(repo, "a.yaml", head) == ["a.yaml"]
    assert changed_since(repo, "a.yaml", fingerprint) == ["a.yaml"]
    assert changed_since(repo, "b.yaml", head) == []
    assert changed_since(repo, "a.yaml", "0" * 40) is None
    assert changed_since(repo, "a.yaml", "sha256:nothex") is None
    (repo / "a.yaml").unlink()
    assert changed_since(repo, "a.yaml", fingerprint) == ["a.yaml"]


FRONT = {
    "topic": "design",
    "reviewed_commit": "abc123",
    "scope": ["pid/P-01.xml"],
    "reviewer": "R",
    "reviewer_kind": "human",
}


def test_review_record_basis_is_optional_and_typed():
    assert ReviewRecord.model_validate(FRONT).basis == []
    record = ReviewRecord.model_validate(
        {**FRONT, "basis": [{"path": "process/flowsheet.yaml", "revision": "abc123"}]}
    )
    assert record.basis[0].relation == "depends-on"
    assert set(RELATIONS) == {"derived-from", "represents", "analyses", "depends-on"}
    with pytest.raises(ValidationError):
        ReviewRecord.model_validate(
            {**FRONT, "basis": [{"path": "x", "revision": "abc", "relation": "causes"}]}
        )


# -- value fingerprints and the tool-ownership test (pre-release issue 117) ------------------------


def _old_fingerprint(data):
    # what props.py, propagate.py and simulation/translate.py each computed before
    # pre-release issue 117
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]


@pytest.mark.parametrize(
    "data",
    [
        {"T_K": 300.0, "P_kPa": 101.325, "x": {"N2": 0.79, "O2": 0.21}, "method": "ab12"},
        {"extra": None, "S1": {"flow": {"value": 12.5, "unit": "kg/h"}}},
        {"units": [{"id": "K1", "spec": {"dp": 1}}], "recycles": [{"guess": None}]},
        [],
        "text",
    ],
)
def test_value_fingerprint_is_the_old_16_hex_form(data):
    assert value_fingerprint(data) == _old_fingerprint(data)
    assert len(value_fingerprint(data)) == 16


def test_value_fingerprint_format_is_fixed():
    # committed in plant repositories: a change here marks every calculated value stale
    assert value_fingerprint({"T_K": 300.0, "x": {"N2": 1.0}}) == "5b1397bf46bd256b"


def test_props_method_fingerprint_agrees():
    from chemeascode.domains.process.props import method_fingerprint
    from chemeascode.domains.process.schema import PropertyMethod

    method = PropertyMethod()
    # the fields added with property packages (package, benchmark, unset range fields) stay out
    data = method.model_dump(mode="json", exclude={"status", "package", "benchmark"})
    assert method_fingerprint(method) == value_fingerprint(data)
    # committed in plant repositories before packages: unchanged
    assert method_fingerprint(method) == "0ed85fac76ba1b70"


def test_written_by_matches_the_old_ownership_tests():
    from chemeascode.domains.equipment.fill import FILL_MARK, _ours
    from chemeascode.domains.process import propagate
    from chemeascode.domains.process.schema import Quantity
    from chemeascode.domains.process.simulation import SOURCE as SIM
    from chemeascode.domains.process.simulation import translate

    def old_propagate(v):
        return (
            v is not None and v.provenance == "calculated" and v.source.startswith(propagate.SOURCE)
        )

    def old_translate(v):
        return (
            v is not None
            and getattr(v, "provenance", None) == "calculated"
            and v.source.startswith(SIM)
        )

    values = [None] + [
        Quantity(value=1.0, provenance=p, source=s)
        for p in ("given", "assumed", "calculated")
        for s in ("", propagate.SOURCE + ": mixer M1", SIM + ": K1", "D-012")
    ]
    for value in values:
        assert propagate.ours(value) == old_propagate(value) == written_by(value, propagate.SOURCE)
        assert translate.ours(value) == old_translate(value) == written_by(value, SIM)
    # datasheet entries: a mapping without provenance, judged by its source
    for entry in (
        {"value": 1.0, "source": FILL_MARK + ": duty"},
        {"value": 1.0, "source": "vendor quote"},
        {"value": "TBD"},
        {"value": 1.0, "source": None},
        2.5,
        "TBD",
        None,
    ):
        old = isinstance(entry, dict) and str(entry.get("source") or "").startswith(FILL_MARK)
        assert _ours(entry) == old == written_by(entry, FILL_MARK)
