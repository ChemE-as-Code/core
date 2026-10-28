"""The engineering contract (docs/framework/contract.md): one provenance vocabulary and id
pattern, ids other files refer to, decision references, and the simulation run record as
``cheme validate`` sees it."""

from __future__ import annotations

import shutil
import typing
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.chemistry import catalysts, reactions
from chemeascode.domains.process import schema as process_schema
from chemeascode.domains.process.model import _ID
from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation.run import run
from chemeascode.foundation.schema_base import ID_PATTERN, Provenance
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.decisions import decision_findings, decisions
from chemeascode.project.validate import validate_workspace
from tests.test_process_simulate import fake

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _edit(path: Path, edit) -> None:
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _rules(ws: Workspace, rule: str) -> list:
    return [f for f in validate_workspace(ws).findings if f.rule == rule]


@pytest.fixture
def plant(tmp_path):
    shutil.copytree(EXAMPLES / "process-simulation", tmp_path / "plant")
    return Workspace(tmp_path / "plant")


def test_one_provenance_vocabulary_and_id_pattern():
    assert typing.get_args(Provenance) == ("given", "assumed", "calculated")
    # The process domain keeps its own names (the generator's fingerprint covers its
    # sources); they must stay the same as the shared ones.
    assert typing.get_args(process_schema.Provenance) == typing.get_args(Provenance)
    assert _ID.pattern == ID_PATTERN.pattern


@pytest.mark.parametrize(
    ("model", "schema"),
    [(reactions.Reactions, "cheme/reactions/v1"), (catalysts.Catalysts, "cheme/catalysts/v1")],
)
def test_versioned_files_share_the_schema_error(model, schema):
    kind = schema.split("/")[1]
    with pytest.raises(ValueError, match="not supported: this cheme-as-code reads"):
        model.model_validate({"schema": schema.replace("v1", "v9"), "kind": kind})
    with pytest.raises(ValueError, match="rename of plantcode"):
        model.model_validate({"schema": schema.replace("cheme/", "plantcode/"), "kind": kind})


def test_component_and_case_ids_that_are_no_stable_identifier_warn(plant):
    assert not _rules(plant, "cheme.contract-id")
    _edit(
        plant.root / "process/materials.yaml",
        lambda d: d["components"].append({"id": "water (liquid)", "name": "water"}),
    )
    found = _rules(plant, "cheme.contract-id")
    assert [(f.file, f.level, f.ids) for f in found] == [
        ("process/materials.yaml", "warning", ["water (liquid)"])
    ]
    assert found[0].line is not None


def test_decision_references_resolve_against_design_md(plant):
    assert not _rules(plant, "cheme.decision-unknown")  # no DESIGN.md: not checked
    (plant.root / "DESIGN.md").write_text(
        "# Design decisions\n\n## D-001 Compressor efficiency (2026-10-23)\nDecision: 0.78\n"
    )
    _edit(
        plant.root / "process/simulation.yaml",
        lambda d: d["specs"]["K1"]["efficiency"].update(source="DESIGN.md D-001; see D-002"),
    )
    found = _rules(plant, "cheme.decision-unknown")
    assert [(f.file, f.level, f.ids) for f in found] == [
        ("process/simulation.yaml", "info", ["D-002"])
    ]
    assert decision_findings(plant, targets=set()) == []
    assert decisions("## D-001 a\n### D-0123 b\nD-007 in text\n") == {"D-001", "D-0123"}


def test_validate_reports_a_stale_simulation_run(plant):
    process, _ = load_process(plant.root)
    run(plant, process, "design", write=True, solver=fake)
    assert not _rules(plant, "cheme.process-sim-run-stale")
    _edit(
        plant.root / "process/simulation.yaml",
        lambda d: d["specs"]["K1"]["efficiency"].update(value=0.7),
    )
    found = _rules(plant, "cheme.process-sim-run-stale")
    assert [(f.file, f.level, f.ids) for f in found] == [
        ("process/simulation-run.json", "warning", ["design"])
    ]


def test_decision_scan_survives_odd_files_and_stays_inside_the_repository(plant, tmp_path):
    root = plant.root
    (root / "DESIGN.md").write_text(
        "## D-001 Real\n<!--\n## D-002 Template example\n-->\n```\n## D-003 In code\n```\n"
    )
    assert decisions((root / "DESIGN.md").read_text()) == {"D-001"}
    (root / "notes").mkdir()
    (root / "notes/a.yaml").write_text("x: D-009\ny: ISO X-D-1234\n")
    (root / "notes/b.yaml").write_bytes(b"x: D-010 \xff\n")
    (root / "dangling.yaml").symlink_to(root / "missing.yaml")
    (root / "folder.yaml").mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("x: D-011\n")
    (root / "outside.yaml").symlink_to(outside)
    for skipped in ("build", ".cache", "nested"):
        (root / skipped).mkdir()
        (root / skipped / "c.yaml").write_text("x: D-012\n")
    (root / "nested/.git").write_text("gitdir: elsewhere\n")
    found = {(f.file, f.ids[0]) for f in decision_findings(plant)}
    assert found == {("notes/a.yaml", "D-009"), ("notes/b.yaml", "D-010")}
    assert decision_findings(plant, targets={(root / "notes/a.yaml").resolve()}) != []


def test_a_fresh_design_md_without_entries_is_not_checked(plant):
    (plant.root / "DESIGN.md").write_text("# Design decisions\n<!--\n## D-001 <title>\n-->\n")
    (plant.root / "x.yaml").write_text("reason: D-023\n")
    assert decision_findings(plant) == []


def test_stale_run_is_reported_when_only_the_flowsheet_is_validated(plant):
    process, _ = load_process(plant.root)
    run(plant, process, "design", write=True, solver=fake)

    def feed(d):
        s1 = next(s for s in d["streams"] if s["id"] == "S1")
        s1["state"]["design"]["flow"]["value"] *= 1.1

    _edit(plant.root / "process/flowsheet.yaml", feed)
    only = [plant.root / "process/flowsheet.yaml"]
    found = [
        f
        for f in validate_workspace(plant, only).findings
        if f.rule == "cheme.process-sim-run-stale"
    ]
    assert [f.ids for f in found] == [["design"]]
