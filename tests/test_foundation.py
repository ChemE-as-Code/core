"""The foundation layer on its own: findings, YAML source lines and acceptance."""

from __future__ import annotations

from types import SimpleNamespace

import yaml

import chemeascode.project.validate as validate
from chemeascode.domains.piping import sheet_index
from chemeascode.foundation import acceptance, findings, yamlsource
from chemeascode.integrations import pydexpi


def test_validate_reexports_the_same_objects():
    assert validate.Finding is findings.Finding
    assert validate._SEVERITY is findings._SEVERITY
    assert validate._yaml_line is yamlsource._yaml_line
    assert validate._duplicates is yamlsource._duplicates
    assert validate.acceptance is acceptance.acceptance
    assert validate.accepted_entries is acceptance.accepted_entries
    assert validate.SheetIndex is sheet_index.SheetIndex
    assert validate._LOADER_LEVELS is pydexpi._LOADER_LEVELS


def test_finding_id_and_format():
    finding = findings.Finding(
        "pid/P-01.xml", "warning", "cheme.line-crossing", "lines cross", line=12, ids=["A", "B"]
    )
    assert finding.id == "pid/P-01.xml#line-crossing:A+B"
    assert finding.format() == ("pid/P-01.xml:12: warning cheme.line-crossing [A, B]: lines cross")


def test_yaml_line_follows_a_pydantic_location(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("equipment:\n  - tag: P-101\n  - tag: P-102\n    class: Pump\n")
    node = yamlsource._compose(path)
    assert yamlsource._yaml_line(node, ("equipment", 1, "class")) == 4
    assert yamlsource._compose(tmp_path / "missing.yaml") is None


def test_duplicates_name_the_first_line(tmp_path):
    path = tmp_path / "list.yaml"
    path.write_text("lines:\n  - number: L1\n  - number: L2\n  - number: L1\n")
    entries = yamlsource._entries(path, "lines", 3)
    [duplicate] = yamlsource._duplicates(
        "list.yaml", "line", "cheme.duplicate-line", ["L1", "L2", "L1"], entries
    )
    assert (duplicate.line, duplicate.ids) == (4, ["L1"])
    assert "first on line 2" in duplicate.message


def test_acceptance_never_accepts_an_error():
    entry = SimpleNamespace(id="a.yaml#rule:*", reason="known")
    warning = findings.Finding("a.yaml", "warning", "cheme.rule", "m", ids=["X"])
    error = findings.Finding("a.yaml", "error", "cheme.rule", "m", ids=["X"])
    assert acceptance.acceptance([entry], warning) is entry
    assert acceptance.acceptance([entry], error) is None


def test_accepted_entries_read_checks_yaml(tmp_path):
    from chemeascode.foundation.workspace import Workspace

    (tmp_path / "plant.yaml").write_text("name: T\n")
    (tmp_path / "checks").mkdir()
    (tmp_path / "checks" / "checks.yaml").write_text(
        yaml.safe_dump({"accept": [{"id": "pid/P-01.xml#x:A", "reason": "why"}]})
    )
    entries, name = acceptance.accepted_entries(Workspace(tmp_path))
    assert name == "checks/checks.yaml"
    assert [e.id for e in entries] == ["pid/P-01.xml#x:A"]
