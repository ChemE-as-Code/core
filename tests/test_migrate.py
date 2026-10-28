"""``schema: cheme/<kind>/v1`` on every file kind, and ``cheme migrate`` (pre-release issue 113)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.foundation import migrate
from chemeascode.foundation.migrate import CURRENT, MIGRATIONS, MigrationRefused, add_schema, plan
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace
from chemeascode.schemas import LAYOUT_SCHEMAS, LIST_SCHEMAS, OTHER_SCHEMAS, PlantConfig

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()

#: The kinds that carry the optional field, with their models.
OPTIONAL = {
    "plant": PlantConfig,
    **{k: m for k, m in LIST_SCHEMAS.items() if k not in ("lca", "lca_factors", "tea")},
    **LAYOUT_SCHEMAS,
    **{k: OTHER_SCHEMAS[k][0] for k in ("datasheet", "review", "status")},
}


def _schema_errors(model, schema: str | None) -> list[dict]:
    """The errors of *model* on the ``schema`` field (other required fields aside)."""
    data = {} if schema is None else {"schema": schema}
    try:
        model.model_validate(data)
    except ValidationError as failure:
        return [e for e in failure.errors() if e["loc"][:1] == ("schema",)]
    return []


@pytest.mark.parametrize("kind", sorted(OPTIONAL))
def test_every_kind_takes_an_optional_schema(kind):
    model = OPTIONAL[kind]
    assert model.schema_id == f"cheme/{kind}/v1"
    assert _schema_errors(model, None) == []
    assert _schema_errors(model, f"cheme/{kind}/v1") == []
    (wrong,) = _schema_errors(model, f"cheme/{kind}/v2")
    assert "is not supported: this cheme-as-code reads" in wrong["msg"]
    (old,) = _schema_errors(model, f"plantcode/{kind}/v1")
    assert "rename of plantcode" in old["msg"]
    exported = model.model_json_schema(by_alias=True)
    assert next(iter(exported["properties"])) == "schema"
    assert "schema" not in exported.get("required", [])


def test_the_versioned_kinds_keep_their_ids():
    from chemeascode.schemas import CostBasis, RateFile

    assert RateFile.schema_id == "cheme/rates/v1"
    assert CostBasis.schema_id == "cheme/cost_basis/v1"
    for kind in ("process-materials", "process-flowsheet", "process-simulation", "kinetic-data"):
        assert not hasattr(OTHER_SCHEMAS[kind][0], "schema_id")


def test_every_list_and_layout_kind_has_a_v0_to_v1_transform():
    expected = {k for k in OPTIONAL if k not in ("review", "status")}  # a record, generated
    # the LCI dataset requires its schema: and has a v1 -> v2 transform instead
    # (pre-release issue 179)
    assert set(CURRENT) == expected | {"lci_dataset"}
    assert ("lci_dataset", "v0", "v1") not in MIGRATIONS
    for kind in expected:
        assert MIGRATIONS[(kind, "v0", "v1")] is add_schema
        assert OPTIONAL[kind].schema_id == f"cheme/{kind}/{CURRENT[kind]}"


def test_add_schema_inserts_the_first_key_as_text():
    text = "# Equipment list.\n\n# More.\nequipment:  # the items\n  - tag: P-1  # a pump\n"
    assert add_schema(text, "equipment") == (
        "# Equipment list.\n\n# More.\nschema: cheme/equipment/v1\n"
        "equipment:  # the items\n  - tag: P-1  # a pump\n"
    )
    # After the document start, with the file's own line endings.
    assert add_schema("---\r\nlines: []\r\n", "lines") == (
        "---\r\nschema: cheme/lines/v1\r\nlines: []\r\n"
    )
    assert add_schema("# nothing yet", "zones") == "# nothing yet\nschema: cheme/zones/v1\n"
    with pytest.raises(MigrationRefused):
        add_schema("{equipment: []}\n", "equipment")
    with pytest.raises(MigrationRefused):
        add_schema("- a\n", "equipment")


def test_a_later_version_chains_its_transform(tmp_path, monkeypatch):
    """The policy: a breaking change registers (kind, v1, v2); a v0 file goes v0 -> v1 -> v2."""
    path = tmp_path / "equipment-list.yaml"
    path.write_text("# list\nequipment: []\n")

    def v2(text: str, kind: str) -> str:
        return text.replace(f"cheme/{kind}/v1", f"cheme/{kind}/v2")

    monkeypatch.setitem(MIGRATIONS, ("equipment", "v1", "v2"), v2)
    migration = plan("equipment", path, "v2")
    assert (migration.found, migration.target, migration.problem) == ("v0", "v2", "")
    assert migration.text == "# list\nschema: cheme/equipment/v2\nequipment: []\n"
    assert (
        plan("equipment", path, "v1").text == "# list\nschema: cheme/equipment/v1\nequipment: []\n"
    )
    assert plan("equipment", path, "v3").problem == "no migration of equipment from v2 to v3"


@pytest.fixture
def plant(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLES / "process-ammonia", root)
    (root / "equipment").mkdir()
    (root / "equipment/equipment-list.yaml").write_text(
        "# Equipment list. Schema: `cheme schema equipment`.\n"
        "equipment:   # none yet\n"
        "  []\n"
        "# end\n"
    )
    (root / "process/design-basis.yaml").write_text(
        "capacity: {}  # t/d\nassumptions: [] # later\n"
    )
    monkeypatch.chdir(root)
    return root


def test_migrate_check_then_write_keeps_comments_and_is_idempotent(plant):
    before = {p: p.read_bytes() for p in sorted(plant.rglob("*")) if p.is_file()}
    errors = [f for f in validate_workspace(Workspace(plant)).findings if f.level == "error"]

    result = runner.invoke(app, ["migrate"])  # --check is the default
    assert result.exit_code == 1
    assert result.output.splitlines() == [
        "plant.yaml: would migrate plant v0 -> v1",
        "process/design-basis.yaml: would migrate design_basis v0 -> v1",
        "equipment/equipment-list.yaml: would migrate equipment v0 -> v1",
        "3 file(s) would change.",
    ]
    assert runner.invoke(app, ["migrate", "--check"]).exit_code == 1
    assert {p: p.read_bytes() for p in before} == before  # --check writes nothing

    result = runner.invoke(app, ["migrate", "--write"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[-1] == "3 file(s) migrated."
    assert (plant / "equipment/equipment-list.yaml").read_text() == (
        "# Equipment list. Schema: `cheme schema equipment`.\n"
        "schema: cheme/equipment/v1\n"
        "equipment:   # none yet\n"
        "  []\n"
        "# end\n"
    )
    assert (plant / "process/design-basis.yaml").read_bytes() == (
        b"schema: cheme/design_basis/v1\n" + before[plant / "process/design-basis.yaml"]
    )
    changed = [p for p, data in before.items() if p.read_bytes() != data]
    assert len(changed) == 3  # the process files already declare their schema

    for flag in ([], ["--check"], ["--write"]):
        again = runner.invoke(app, ["migrate", *flag])
        assert again.exit_code == 0
        assert again.output.startswith("Nothing to migrate")
    after = [f for f in validate_workspace(Workspace(plant)).findings if f.level == "error"]
    assert after == errors


def test_migrate_refuses_what_it_cannot_rewrite(plant):
    (plant / "piping").mkdir()
    (plant / "piping/line-list.yaml").write_text("schema: cheme/equipment/v1\nlines: []\n")
    (plant / "equipment/equipment-list.yaml").write_text("{equipment: []}\n")
    result = runner.invoke(app, ["migrate", "--write"])
    assert result.exit_code == 1
    assert "piping/line-list.yaml: refused: unknown schema 'cheme/equipment/v1'" in result.output
    assert "equipment/equipment-list.yaml: refused: v0 to v1:" in result.output
    assert (plant / "equipment/equipment-list.yaml").read_text() == "{equipment: []}\n"
    assert runner.invoke(app, ["migrate", "--check", "--write"]).exit_code == 2


def test_generated_files_are_not_inputs(plant):
    (plant / "layout").mkdir()
    (plant / "layout/plant-model.yaml").write_text("kind: layout_model\n")
    (plant / "layout/site-plan.yaml").write_text("site: {}\n")
    kinds = {kind for kind, _ in migrate.inputs(Workspace(plant))}
    assert kinds == {"plant", "design_basis", "equipment", "site_plan"}
