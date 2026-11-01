"""0.5 follow-up fixes: gates, exit codes, provenance, version check, thermo
noise."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.sheets import build
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.checks import run_checks
from chemeascode.project.validate import validate_workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
TEMPLATE_CHECKS = (
    Path(__file__).resolve().parents[1] / "src/chemeascode/templates/project/checks/checks.yaml"
)


@pytest.fixture
def recycle(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-recycle", tmp_path / "plant", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "plant")


def _plant_yaml(ws, sheets):
    data = yaml.safe_load((ws.root / "plant.yaml").read_text())
    data["sheets"] = sheets
    (ws.root / "plant.yaml").write_text(yaml.safe_dump(data, sort_keys=False))


def _props_yaml():
    """The props test plant's flowsheet and materials (tests/test_process_props.py)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_props_plant", Path(__file__).parent / "test_process_props.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.FLOWSHEET, module.MATERIALS


def _gate(ws, **extra):
    gate = {"id": "g", "title": "g", "stage": "basic", "kind": "validate", **extra}
    (ws.root / "checks").mkdir(exist_ok=True)
    (ws.root / "checks/checks.yaml").write_text(yaml.safe_dump({"checks": [gate]}))
    return run_checks(ws)[0]


# -- 1. process-basic needs a built PFD ---------------------------------------------------------


def test_generated_gate_fails_without_a_declared_and_built_pfd(recycle):
    _plant_yaml(recycle, [{"id": "BFD", "kind": "bfd"}])
    build(recycle, force=True)
    result = _gate(recycle, generated=["pfd"], rules=["cheme.none"])
    assert result.status == "fail" and "no kind: pfd sheet declared" in result.detail
    _plant_yaml(recycle, [{"id": "BFD", "kind": "bfd"}, {"id": "PFD", "kind": "pfd"}])
    (recycle.root / "process/PFD.xml").unlink(missing_ok=True)
    result = _gate(recycle, generated=["pfd"], rules=["cheme.none"])
    assert result.status == "fail" and "process/PFD.xml not built" in result.detail
    build(recycle, force=True)
    assert _gate(recycle, generated=["pfd"], rules=["cheme.none"]).status == "pass"


def test_template_basic_gate_requires_the_pfd():
    checks = yaml.safe_load(TEMPLATE_CHECKS.read_text())["checks"]
    basic = next(c for c in checks if c["id"] == "process-basic")
    assert basic["generated"] == ["pfd"]


# -- 2. props --fill exits non-zero when it refused a stream ------------------------------------


def test_props_fill_exits_3_and_names_refused_streams(tmp_path, monkeypatch):
    pytest.importorskip("thermo")
    FLOWSHEET, MATERIALS = _props_yaml()

    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: t\nsheets:\n  - {id: P-01}\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    # S1 at 500 K is outside the method's range: refused
    (root / "process/flowsheet.yaml").write_text(
        FLOWSHEET.replace("temperature: {value: 293.15", "temperature: {value: 500.0")
    )
    monkeypatch.chdir(root)
    result = CliRunner().invoke(app, ["process", "props", "--fill"])
    assert result.exit_code == 3, result.output
    assert "1 stream(s) refused, nothing written for them: S1" in result.output
    check = CliRunner().invoke(app, ["process", "props", "--check"])
    assert check.exit_code == 1


# -- 3. streams --json resolves links like /api/streams -----------------------------------------


def test_streams_json_resolves_links_like_the_api(recycle, monkeypatch):
    from chemeascode.domains.process.model import load
    from chemeascode.domains.process.streams import link_context, stream_table

    path = recycle.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["streams"][0]["links"] = [{"target": "equipment", "ref": "K-9999"}]
    data["blocks"][0]["links"] = [{"target": "sheet", "ref": "NOPE"}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    monkeypatch.chdir(recycle.root)
    result = CliRunner().invoke(app, ["process", "streams", "--json"])
    assert result.exit_code == 0, result.output
    shown = json.loads(result.output)
    link = shown["streams"][0]["links"][0]
    assert link["resolved"] is False and "K-9999" in link["problem"]
    process, _ = load(recycle.root)
    api = stream_table(process, shown["case"], *link_context(recycle))
    assert [s["links"] for s in api["streams"]] == [s["links"] for s in shown["streams"]]
    assert [n["links"] for n in api["nodes"]] == [n["links"] for n in shown["nodes"]]
    assert (
        shown["nodes"][[n["id"] for n in shown["nodes"]].index(data["blocks"][0]["id"])]["links"][
            0
        ]["resolved"]
        is False
    )


# -- 4. a generator code change is reported -----------------------------------------------------


def test_generator_code_change_is_reported(recycle, monkeypatch):
    from chemeascode.domains.process import provenance

    build(recycle, force=True)
    record = provenance.read((recycle.root / "process/BFD.xml").read_bytes())
    assert record["generator_sha256"] == provenance.generator_fingerprint()
    assert not [f for f in validate_workspace(recycle).findings if f.rule.startswith("cheme.gen")]
    monkeypatch.setattr(provenance, "generator_fingerprint", lambda: "0" * 64)
    found = [f for f in validate_workspace(recycle).findings if f.rule == "cheme.generated-version"]
    assert found and "other process generator code" in found[0].message and found[0].hint


def test_sheet_without_generator_hash_is_compared_by_version(recycle):
    from chemeascode.domains.process import provenance

    build(recycle, force=True)
    path = recycle.root / "process/BFD.xml"
    path.write_bytes(
        path.read_bytes().replace(
            f'"generator_sha256": "{provenance.generator_fingerprint()}", '.encode(), b""
        )
    )
    assert provenance.read(path.read_bytes()).get("generator_sha256") is None
    rules = {f.rule for f in validate_workspace(recycle).findings}
    assert "cheme.generated-version" not in rules


# -- 5. a component balance without compositions has its own rule ------------------------------


def test_component_balance_not_evaluable_has_its_own_rule(recycle):
    from fnmatch import fnmatchcase

    from chemeascode.domains.process.model import load, rules

    path = recycle.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    for stream in data["streams"]:
        for state in stream.get("state", {}).values():
            flow = state.get("flow")
            if flow is not None:
                flow["basis"] = "mass"
                flow.pop("unit", None)
            state.pop("composition", None)
    data["units"]["flow"] = "kg/h"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    process, found = load(recycle.root)
    assert process is not None, [f.format() for f in found]
    ids = {f.rule for f in rules(process)}
    assert "cheme.process-component-balance-not-evaluable" in ids
    assert "cheme.process-balance-not-evaluable" not in ids
    checks = yaml.safe_load(TEMPLATE_CHECKS.read_text())["checks"]
    concept = next(c for c in checks if c["id"] == "process-balances")["rules"]
    basic = next(c for c in checks if c["id"] == "process-basic")["rules"]
    rule = "cheme.process-component-balance-not-evaluable"
    assert not any(fnmatchcase(rule, r) for r in concept)
    assert any(fnmatchcase(rule, r) for r in basic)


# -- 6. requires: cheme-as-code>=X.Y --------------------------------------------------------------


def test_older_cheme_says_upgrade_before_any_schema_error(tmp_path, monkeypatch):
    (tmp_path / "plant.yaml").write_text(
        "name: t\nrequires: cheme-as-code>=99.1\nkind: a-key-this-cheme-does-not-know\n"
    )
    monkeypatch.chdir(tmp_path)
    for args in (["validate"], ["process", "streams"], ["status"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 2, (args, result.output)
        assert "plant.yaml:2" in result.output and "cheme.version-required" in result.output
        assert "needs cheme-as-code >= 99.1, you have" in result.output
        assert "uv tool upgrade cheme-as-code" in result.output
        assert "extra" not in result.output.lower()  # no schema error


def test_the_old_package_name_in_requires_is_refused_with_the_new_one(tmp_path, monkeypatch):
    (tmp_path / "plant.yaml").write_text("name: t\nrequires: plantcode>=0.6\n")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["validate"])
    assert result.exit_code == 2, result.output
    assert "plant.yaml:2" in result.output and "cheme.version-required" in result.output
    assert "write `requires: cheme-as-code>=0.7`" in result.output
    assert "docs/framework/rename.md" in result.output


def test_an_old_schema_id_is_refused_with_the_new_one():
    from pydantic import ValidationError

    from chemeascode.domains.process.schema import Versioned

    assert Versioned.model_validate({"schema": "cheme/process/v1"})
    with pytest.raises(ValidationError, match="write `schema: cheme/process/v1`"):
        Versioned.model_validate({"schema": "plantcode/process/v1"})
    with pytest.raises(ValidationError, match="not supported: this cheme-as-code reads"):
        Versioned.model_validate({"schema": "cheme/process/v9"})


def test_an_old_rates_or_cost_basis_schema_id_is_refused():
    from pydantic import ValidationError

    from chemeascode.domains.assessment.schemas import CostBasis, RateFile

    rates = {"currency": "XXX", "cost_year": 2026}
    assert RateFile.model_validate(rates)  # schema: stays optional
    assert RateFile.model_validate({**rates, "schema": "cheme/rates/v1"})
    with pytest.raises(ValidationError, match="write `schema: cheme/rates/v1`"):
        RateFile.model_validate({**rates, "schema": "plantcode/rates/v1"})
    with pytest.raises(ValidationError, match="not supported: this cheme-as-code reads"):
        RateFile.model_validate({**rates, "schema": "bogus/v9"})
    assert CostBasis.model_validate({"schema": "cheme/cost_basis/v1"})
    with pytest.raises(ValidationError, match="write `schema: cheme/cost_basis/v1`"):
        CostBasis.model_validate({"schema": "plantcode/cost_basis/v1"})


def test_init_writes_a_satisfied_requirement(tmp_path, monkeypatch):
    from chemeascode.foundation.workspace import installed_version, requirement_problem
    from chemeascode.templates.install import init

    init(tmp_path / "p", "p")
    config = Workspace(tmp_path / "p").config()
    have = ".".join(map(str, installed_version()[:2]))
    assert config.requires == f"cheme-as-code>={have}"
    assert requirement_problem(tmp_path / "p") is None


# -- 7. no ResourceWarning from thermo at exit --------------------------------------------------


def test_thermo_leaves_no_unclosed_database_at_exit(tmp_path):
    pytest.importorskip("thermo")
    script = (
        "from chemeascode.domains.process.model import load\n"
        "from chemeascode.domains.process.props import Adapter, Inputs\n"
        "import sys\n"
        "from pathlib import Path\n"
        "process, _ = load(Path(sys.argv[1]))\n"
        "Adapter(process).flash(Inputs(293.15, 101.325, {'N2': 0.79, 'O2': 0.21}))\n"
    )
    FLOWSHEET, MATERIALS = _props_yaml()

    (tmp_path / "process").mkdir()
    (tmp_path / "process/materials.yaml").write_text(MATERIALS)
    (tmp_path / "process/flowsheet.yaml").write_text(FLOWSHEET)
    run = subprocess.run(
        [sys.executable, "-X", "dev", "-W", "always::ResourceWarning", "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert run.returncode == 0, run.stderr
    assert "unclosed database" not in run.stderr


def test_generator_fingerprint_covers_only_the_sheet_generating_modules():
    from pathlib import Path

    from chemeascode.domains.process import provenance

    here = Path(provenance.__file__).parent
    assert all((here / name).is_file() for name in provenance.GENERATOR_MODULES)
    # Reports and YAML-writing commands change no sheet, so editing them must not flag
    # every plant's generated sheets as built by another generator version.
    for report in ("streams.py", "summary.py", "sheets.py", "fill.py", "propagate.py"):
        assert report not in provenance.GENERATOR_MODULES
