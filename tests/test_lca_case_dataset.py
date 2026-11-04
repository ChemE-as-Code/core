"""A design case's unallocated LCI dataset: ``cheme assess lca --dataset|--write|--check --case``
(ADR 0045).

The plant is ``tests/data/lca-scenarios-asu`` (SYNTHETIC): the default case ``design`` with
10,000 kW of power and 9,000 kW to cooling water, and the separately computed case ``hot`` with
11,000 kW and 9,900 kW. ``tests/data/lca-case-dataset/asu-design-dataset.yaml`` is the
``lca/dataset.yaml`` that ``cheme assess lca --write`` wrote for it before ``--case`` existed:
the default case must stay byte-identical. When a deliberate change to the dataset format
changes it, regenerate it (``cheme assess lca --dataset`` in a copy of the fixture) in that
change, never in this feature's.
"""

from __future__ import annotations

import ast
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.case_dataset import (
    UnknownCase,
    case_dataset,
    case_dataset_path,
    case_slug,
    case_uuid,
    variant_case,
)
from chemeascode.domains.assessment.lca.report import lca_report
from chemeascode.interfaces.cli import app

FIXTURE = Path(__file__).parent / "data" / "lca-scenarios-asu"
SNAPSHOT = Path(__file__).parent / "data" / "lca-case-dataset" / "asu-design-dataset.yaml"
BASE_ID = "synthetic-asu-scenario-fixture"
HOT_FILE = f"lca/datasets/{BASE_ID}-hot.yaml"


@pytest.fixture
def asu(tmp_path: Path) -> Path:
    root = tmp_path / "asu"
    shutil.copytree(FIXTURE, root)
    return root


def _cli(root: Path, monkeypatch, *args: str):
    monkeypatch.chdir(root)
    return CliRunner().invoke(app, ["assess", "lca", *args])


def _edit(root: Path, name: str, change) -> None:
    path = root / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _amounts(text: str) -> dict[str, float]:
    data = yaml.safe_load(text)
    return {e["key"]: e["amount"] for e in data["exchanges"]}


# -- two cases, two datasets -------------------------------------------------------------------


def test_two_cases_give_two_datasets_with_their_own_identity_and_flows(asu: Path) -> None:
    design, hot = case_dataset(asu, "design"), case_dataset(asu, "hot")
    assert design.loaded and hot.loaded, [f.format() for f in hot.findings]
    assert design.path == "lca/dataset.yaml"
    assert hot.path == HOT_FILE
    a, b = yaml.safe_load(design.text), yaml.safe_load(hot.text)
    # the identity names the case: id, title, uuid all differ
    assert (a["id"], b["id"]) == (BASE_ID, f"{BASE_ID}-hot")
    assert a["title"] == "Synthetic ASU (scenario fixture)"
    assert b["title"] == "Synthetic ASU (scenario fixture), case hot"
    assert a["uuid"] != b["uuid"]
    assert b["uuid"] == str(uuid.uuid5(uuid.UUID(a["uuid"]), "case:hot"))
    assert b["provenance"]["case"] == "hot" and a["provenance"]["case"] == "design"
    assert b["provenance"]["generator"] == "cheme assess lca"
    assert b["provenance"]["files"] == a["provenance"]["files"]
    # the flows are the case's own
    assert _amounts(design.text)["feed:POWER"] == 10000.0
    assert _amounts(hot.text)["feed:POWER"] == 11000.0
    assert _amounts(design.text)["product:CW"] == 9000.0
    assert _amounts(hot.text)["product:CW"] == 9900.0
    assert set(_amounts(design.text)) == set(_amounts(hot.text))
    # reference product, basis, documentation and functional unit unchanged
    for key in ("schema", "kind", "scope", "basis", "year", "technology", "rights", "allocation"):
        assert a.get(key) == b.get(key), key
    assert a["valid_until"] == b["valid_until"] and a["modelling"] == b["modelling"]
    assert hot.report.inventory.functional_unit == design.report.inventory.functional_unit
    assert hot.report.inventory.case == "hot"
    # a generated file that says so
    assert hot.text.startswith("# The unallocated LCI dataset of design case hot")
    assert "cheme assess lca --write --case hot" in hot.text.splitlines()[1]


def test_the_case_uuid_derives_from_a_pinned_base_uuid(asu: Path) -> None:
    pinned = "0f1e2d3c-4b5a-4968-8776-655443322110"
    _edit(asu, "lca/lca.yaml", lambda d: d.update({"dataset": {"uuid": pinned}}))
    base = yaml.safe_load(case_dataset(asu, "design").text)
    hot = yaml.safe_load(case_dataset(asu, "hot").text)
    assert base["uuid"] == pinned
    assert hot["uuid"] == case_uuid(pinned, "hot") != pinned
    # deterministic: the same base and case give the same uuid
    assert case_uuid(pinned, "hot") == case_uuid(pinned, "hot") != case_uuid(pinned, "cold")


def test_the_studys_review_and_lineage_are_not_the_case_datasets(asu: Path) -> None:
    pinned = "0f1e2d3c-4b5a-4968-8776-655443322110"
    grandparent = "11111111-2222-4333-8444-555555555555"
    documentation = {
        "uuid": pinned,
        "parent": grandparent,
        "review": [{"type": "independent-external", "reviewer": "Jane Doe"}],
        "superseded_by": {"id": "other", "version": "2.0.0"},
    }
    _edit(asu, "lca/lca.yaml", lambda d: d.update({"dataset": documentation}))
    base = yaml.safe_load(case_dataset(asu, "design").text)
    hot = case_dataset(asu, "hot")
    data = yaml.safe_load(hot.text)
    # the study's dataset keeps what lca.yaml records of it
    assert base["review"][0]["reviewer"] == "Jane Doe"
    assert base["superseded_by"] == {"id": "other", "version": "2.0.0"}
    assert base["parent"] == grandparent
    # the case dataset: nobody reviewed it, nothing supersedes it, it is a variant of the base
    assert data["review"] == [{"type": "none"}]
    assert "superseded_by" not in data
    assert data["parent"] == pinned
    dataset = hot.report.inventory.dataset
    assert [r.type for r in dataset.review] == ["none"] and dataset.superseded_by is None
    # still stated (unreviewed), so the documentation check counts review as given
    from chemeascode.domains.assessment.lca.documentation import missing

    assert "review" not in missing(dataset)


def test_a_case_dataset_without_a_stated_review_states_none(asu: Path) -> None:
    data = yaml.safe_load(case_dataset(asu, "hot").text)
    assert not data.get("review")
    assert data["parent"] == yaml.safe_load(case_dataset(asu, "design").text)["uuid"]


def test_two_case_ids_giving_one_identifier_are_refused(asu: Path, monkeypatch) -> None:
    def add_upper_hot(data: dict) -> None:
        data["cases"].append({**next(c for c in data["cases"] if c["id"] == "hot"), "id": "HOT"})
        for stream in data["streams"]:
            if "hot" in stream.get("state", {}):
                stream["state"]["HOT"] = stream["state"]["hot"]

    _edit(asu, "process/flowsheet.yaml", add_upper_hot)
    for case in ("hot", "HOT"):
        result = case_dataset(asu, case)
        assert not result.loaded and result.path == ""
        clash = [f for f in result.findings if f.rule == "cheme.lca-case-id-clash"]
        assert clash and set(clash[0].ids) == {"hot", "HOT"}, [f.format() for f in result.findings]
    for flags in (["--write"], ["--check"], ["--dataset"]):
        result = _cli(asu, monkeypatch, *flags, "--case", "HOT")
        assert result.exit_code == 1, (flags, result.output)
        assert "cheme.lca-case-id-clash" in result.output
    assert not (asu / "lca/datasets").exists()
    # the study's own case never clashes: it is lca/dataset.yaml
    _edit(asu, "lca/lca.yaml", lambda d: d.update({"case": "HOT"}))
    assert case_dataset(asu, "hot").loaded


def test_a_case_id_is_made_an_identifier() -> None:
    assert case_slug("Skid B / 1000 h") == "skid-b-1000-h"
    assert case_dataset_path("plant-skid-b") == "lca/datasets/plant-skid-b.yaml"


def test_the_study_case_named_in_lca_yaml_is_the_plant_dataset(asu: Path) -> None:
    _edit(asu, "lca/lca.yaml", lambda d: d.update({"case": "hot"}))
    assert variant_case(asu, "hot") is None
    assert variant_case(asu, "design") == "design"
    design = case_dataset(asu, "design")
    assert design.path == f"lca/datasets/{BASE_ID}-design.yaml"
    assert _amounts(design.text)["feed:POWER"] == 10000.0
    assert case_dataset(asu, "hot").path == "lca/dataset.yaml"


def test_an_undeclared_case_is_refused(asu: Path) -> None:
    with pytest.raises(UnknownCase) as caught:
        case_dataset(asu, "2000-t-d")
    assert caught.value.cases == ["design", "hot"]
    with pytest.raises(UnknownCase):
        lca_report(asu, case="2000-t-d")
    with pytest.raises(UnknownCase):
        variant_case(asu, "2000-t-d")


def _drop_state(root: Path, stream_id: str, case: str) -> None:
    def drop(data: dict) -> None:
        for stream in data["streams"]:
            if stream["id"] == stream_id:
                del stream["state"][case]

    _edit(root, "process/flowsheet.yaml", drop)


def test_a_case_inventory_finding_names_the_case(asu: Path) -> None:
    _drop_state(asu, "E1", "hot")
    hot = case_dataset(asu, "hot")
    assert hot.loaded
    incomplete = [f for f in hot.findings if f.rule == "cheme.lca-flow-incomplete"]
    assert incomplete and "(case hot)" in incomplete[0].hint
    assert case_dataset(asu, "design").loaded


def test_a_case_without_its_reference_product_gives_no_dataset(asu: Path, monkeypatch) -> None:
    _drop_state(asu, "S2", "hot")
    hot = case_dataset(asu, "hot")
    assert not hot.loaded and hot.text == "" and hot.path == ""
    assert any(f.level == "error" for f in hot.findings)
    result = _cli(asu, monkeypatch, "--write", "--case", "hot")
    assert result.exit_code == 1
    assert "no LCI dataset for case hot" in result.output
    assert not (asu / "lca/datasets").exists()


# -- the default case is unchanged -------------------------------------------------------------


def test_the_default_dataset_is_byte_identical_to_the_snapshot(asu: Path, monkeypatch) -> None:
    snapshot = SNAPSHOT.read_text(encoding="utf-8")
    result = _cli(asu, monkeypatch, "--write")
    assert result.exit_code == 0, result.output
    assert (asu / "lca/dataset.yaml").read_text(encoding="utf-8") == snapshot
    assert not (asu / "lca/datasets").exists()
    result = _cli(asu, monkeypatch, "--dataset")
    assert result.exit_code == 0, result.output
    assert result.stdout == snapshot
    # --case naming the study's case is the same as no --case
    result = _cli(asu, monkeypatch, "--dataset", "--case", "design")
    assert result.exit_code == 0, result.output
    assert result.stdout == snapshot
    (asu / "lca/dataset.yaml").unlink()
    result = _cli(asu, monkeypatch, "--write", "--case", "design")
    assert result.exit_code == 0, result.output
    assert (asu / "lca/dataset.yaml").read_text(encoding="utf-8") == snapshot
    assert (asu / "lca/results.md").is_file()
    assert not (asu / "lca/datasets").exists()
    assert case_dataset(asu, "design").text == snapshot


# -- the command -------------------------------------------------------------------------------


def test_cli_dataset_and_write_match_the_function(asu: Path, monkeypatch) -> None:
    expected = case_dataset(asu, "hot")
    result = _cli(asu, monkeypatch, "--dataset", "--case", "hot")
    assert result.exit_code == 0, result.output
    assert result.stdout == expected.text
    result = _cli(asu, monkeypatch, "--write", "--case", "hot")
    assert result.exit_code == 0, result.output
    assert f"wrote {HOT_FILE}" in result.stdout
    assert (asu / HOT_FILE).read_text(encoding="utf-8") == expected.text
    # only the case's dataset: the study's outputs are not written
    assert not (asu / "lca/dataset.yaml").exists()
    assert not (asu / "lca/results.md").exists()


def test_check_current_and_stale(asu: Path, monkeypatch) -> None:
    result = _cli(asu, monkeypatch, "--check", "--case", "hot")
    assert result.exit_code == 1
    assert f"{HOT_FILE}: error cheme.lca-dataset-stale [hot]: {HOT_FILE} is not written" in (
        result.output
    )
    assert "rerun cheme assess lca --write --case hot" in result.output
    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    result = _cli(asu, monkeypatch, "--check", "--case", "hot")
    assert result.exit_code == 0, result.output
    assert f"{HOT_FILE} current" in result.stdout

    # an input of the case changes: the written file is stale
    def more_power(data: dict) -> None:
        for stream in data["streams"]:
            if stream["id"] == "E1":
                stream["state"]["hot"]["duty"]["value"] = 11500

    _edit(asu, "process/flowsheet.yaml", more_power)
    result = _cli(asu, monkeypatch, "--check", "--case", "hot")
    assert result.exit_code == 1
    assert "cheme.lca-dataset-stale" in result.output
    assert f"{HOT_FILE} differs from the dataset of case hot generated now" in result.output
    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    assert _cli(asu, monkeypatch, "--check", "--case", "hot").exit_code == 0
    # a hand edit is stale too
    path = asu / HOT_FILE
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert _cli(asu, monkeypatch, "--check", "--case", "hot").exit_code == 1


def test_check_without_case_is_the_study_gate(asu: Path, monkeypatch) -> None:
    assert _cli(asu, monkeypatch, "--write").exit_code == 0
    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    result = _cli(asu, monkeypatch, "--check")
    assert result.exit_code == 0, result.output
    assert HOT_FILE not in result.stdout
    (asu / "lca/dataset.yaml").write_text("stale\n", encoding="utf-8")
    result = _cli(asu, monkeypatch, "--check")
    assert result.exit_code == 1
    assert "lca/dataset.yaml is not current; run cheme assess lca --write" in result.stdout
    # the stale dataset is the finding --check --case reports, with the plain rerun hint
    assert "lca/dataset.yaml: error cheme.lca-dataset-stale [design]" in result.output
    assert "rerun cheme assess lca --write and commit it" in result.output
    # the same through --case naming the study's case
    result = _cli(asu, monkeypatch, "--check", "--case", "design")
    assert result.exit_code == 1
    assert "lca/dataset.yaml: error cheme.lca-dataset-stale [design]" in result.output
    # the case's file is checked by its own gate, and is current
    assert _cli(asu, monkeypatch, "--check", "--case", "hot").exit_code == 0


def test_an_undeclared_case_is_a_usage_error(asu: Path, monkeypatch) -> None:
    for flags in (["--dataset"], ["--write"], ["--check"]):
        result = _cli(asu, monkeypatch, *flags, "--case", "skid-c")
        assert result.exit_code == 2, result.output
        assert "unknown case skid-c; cases of process/flowsheet.yaml: design, hot" in (
            result.output
        )
    assert not (asu / "lca/datasets").exists()


def test_case_goes_with_dataset_write_or_check_only(asu: Path, monkeypatch) -> None:
    for flags in (["--json"], ["--inventory"], ["--coverage"], ["--strict", "--write"], []):
        result = _cli(asu, monkeypatch, *flags, "--case", "hot")
        assert result.exit_code == 2, (flags, result.output)
        assert "--case goes with --dataset, --write or --check only" in result.output


def test_write_never_replaces_a_dataset_it_did_not_generate(asu: Path, monkeypatch) -> None:
    path = asu / HOT_FILE
    path.parent.mkdir(parents=True)
    hand = "# a hand-written dataset that happens to have this id\nschema: x\n"
    path.write_text(hand, encoding="utf-8")
    result = _cli(asu, monkeypatch, "--write", "--case", "hot")
    assert result.exit_code == 1
    assert "cheme.lca-dataset-not-generated" in result.output
    assert path.read_text(encoding="utf-8") == hand
    # the generated file of the case is replaced
    path.unlink()
    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    assert path.read_text(encoding="utf-8") == case_dataset(asu, "hot").text


def test_the_written_case_dataset_loads_as_an_lci_dataset(asu: Path, monkeypatch) -> None:
    """The schema check of the written file (``cheme validate`` does not read lca/datasets/:
    ``--check --case`` is the gate of a committed case dataset)."""
    from chemeascode.domains.assessment.lca.report import load_dataset
    from chemeascode.domains.assessment.lca.schemas import LciDataset

    assert _cli(asu, monkeypatch, "--write", "--case", "hot").exit_code == 0
    path = asu / HOT_FILE
    loaded = load_dataset(asu, HOT_FILE)
    assert not isinstance(loaded, str), loaded
    assert loaded.id == f"{BASE_ID}-hot"
    assert LciDataset.model_validate(yaml.safe_load(path.read_text(encoding="utf-8"))) == loaded
    # the check has teeth: a broken file does not load
    path.write_text(path.read_text(encoding="utf-8") + "bogus: 1\n", encoding="utf-8")
    assert isinstance(load_dataset(asu, HOT_FILE), str)


# -- import boundaries -------------------------------------------------------------------------


def test_the_domain_module_imports_no_interface() -> None:
    import chemeascode.domains.assessment.lca.case_dataset as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }
    assert not any(
        name
        and (
            name.startswith(("chemeascode.interfaces", "chemeascode.project"))
            or name in {"typer", "fastapi"}
        )
        for name in imported
    ), imported
    code = (
        "import sys, chemeascode.domains.assessment.lca.case_dataset as m; "
        "m.case_uuid('0f1e2d3c-4b5a-4968-8776-655443322110', 'hot'); "
        "assert 'typer' not in sys.modules and 'chemeascode.interfaces' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
