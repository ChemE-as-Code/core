"""``kind: validate`` gates with ``fail_on``, ``rules`` and ``accept``; accepted findings."""

import json
from pathlib import Path

from typer.testing import CliRunner

from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.checks import run_checks
from chemeascode.project.validate import validate_workspace

runner = CliRunner()

GATE = """\
checks:
  - id: drawing-clean
    title: No unaccepted drawing warnings
    stage: basic
    kind: validate
    fail_on: warning
    rules: [{rules}]
{accept}"""


def _gate(plant: Path, rules: str, accept: str = "", top: str = "") -> str:
    text = GATE.format(rules=rules, accept=accept) + top
    (plant / "checks" / "checks.yaml").write_text(text, encoding="utf-8")
    [result] = run_checks(Workspace(plant))
    return result.status + (f": {result.detail}" if result.detail else "")


def _crossings(plant: Path) -> list[str]:
    report = validate_workspace(Workspace(plant))
    return sorted(f.id for f in report.findings if f.rule == "cheme.line-crossing")


def test_gate_fails_on_a_selected_drawing_warning(plant: Path):
    status = _gate(plant, "cheme.line-crossing")
    assert status.startswith("fail: 3 cheme.line-crossing not accepted; first: pid/P-01.xml#")


def test_gate_ignores_rules_it_does_not_select(plant: Path):
    # The reference has crossings, and no label far from its owner.
    assert _gate(plant, "cheme.label-far-from-owner") == "pass"
    # Wildcards select rules too.
    assert _gate(plant, "cheme.label-*").startswith("pass")


def test_gate_passes_when_each_finding_is_accepted_with_a_reason(plant: Path):
    ids = _crossings(plant)
    assert len(ids) == 3
    accept = "    accept:\n" + "".join(
        f"      - {{id: '{i}', reason: 'reference drawing, crossing kept (A. Reviewer)'}}\n"
        for i in ids[:2]
    )
    status = _gate(plant, "cheme.line-crossing", accept)
    assert status.startswith("fail: 1 cheme.line-crossing"), status
    accept += f"      - {{id: '{ids[2]}', reason: 'kept as drawn in the reference'}}\n"
    assert _gate(plant, "cheme.line-crossing", accept) == "pass"
    # A pattern accepts several.
    wildcard = "    accept:\n      - {id: 'pid/P-01.xml#line-crossing:*', reason: 'all kept'}\n"
    assert _gate(plant, "cheme.line-crossing", wildcard) == "pass"


def test_default_validate_gate_still_fails_only_on_errors(plant: Path):
    (plant / "checks" / "checks.yaml").write_text(
        "checks:\n  - {id: v, title: valid, stage: basic, kind: validate}\n", encoding="utf-8"
    )
    [result] = run_checks(Workspace(plant))
    assert result.status == "pass"


def test_accept_without_a_reason_is_a_schema_error(plant: Path, monkeypatch):
    (plant / "checks" / "checks.yaml").write_text(
        "checks: []\naccept:\n  - {id: 'pid/P-01.xml#line-crossing:*'}\n", encoding="utf-8"
    )
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["validate"])
    assert "yaml.schema" in result.output and "reason" in result.output


def test_repository_accept_list_makes_findings_info(plant: Path, monkeypatch):
    ids = _crossings(plant)
    top = (
        "accept:\n"
        f"  - {{id: '{ids[0]}', reason: 'crossing kept, see D-023'}}\n"
        "  - {id: 'pid/P-01.xml#line-crossing:Nothing+Here', reason: 'stale entry'}\n"
    )
    status = _gate(plant, "cheme.line-crossing", top=top)
    assert status.startswith("fail: 2 cheme.line-crossing"), status
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["validate", "--json"])
    report = json.loads(result.output)
    by_id = {f["id"]: f for f in report["findings"]}
    assert by_id[ids[0]]["level"] == "info"
    assert by_id[ids[0]]["accepted"] == "crossing kept, see D-023"
    unused = [f for f in report["findings"] if f["rule"] == "cheme.accept-unused"]
    assert len(unused) == 1 and "Nothing+Here" in unused[0]["message"]
    text = runner.invoke(app, ["validate"]).output
    assert "(accepted: crossing kept, see D-023)" in text
    assert "drawing pid/P-01.xml: 2 line-through-label, 2 line-crossing (+1 accepted)" in text
    assert text.strip().splitlines()[-1].startswith("compared: 1 sheet(s)")


def test_accept_never_silences_an_error(plant: Path, monkeypatch):
    # A schema error plus a catch-all accept: the error stays an error, validate and the
    # default pids-valid gate still fail, and the entry is reported.
    lists = plant / "equipment" / "equipment-list.yaml"
    lists.write_text("equipment: []\nbogus: 1\n", encoding="utf-8")
    (plant / "checks" / "checks.yaml").write_text(
        "checks:\n"
        "  - {id: pids-valid, title: valid, stage: basic, kind: validate,\n"
        "     accept: [{id: '*', reason: 'gate silences everything'}]}\n"
        "accept:\n  - {id: '*', reason: 'silence everything'}\n",
        encoding="utf-8",
    )
    [result] = run_checks(Workspace(plant))
    assert result.status == "fail", result.detail
    monkeypatch.chdir(plant)
    run = runner.invoke(app, ["validate", "--json"])
    assert run.exit_code == 1, run.output
    report = json.loads(run.output)
    schema = [f for f in report["findings"] if f["rule"] == "yaml.schema"]
    assert schema and all(f["level"] == "error" and not f.get("accepted") for f in schema)
    refused = [f for f in report["findings"] if f["rule"] == "cheme.accept-error"]
    assert len(refused) == 2 and all(f["level"] == "warning" for f in refused)
    assert any("(gate pids-valid)" in f["message"] for f in refused)
    # The warnings it names are still accepted.
    crossings = [f for f in report["findings"] if f["rule"] == "cheme.line-crossing"]
    assert crossings and all(f["accepted"] == "silence everything" for f in crossings)


def test_unused_gate_accept_entry_is_reported(plant: Path, monkeypatch):
    accept = "    accept:\n      - {id: 'nothing-at-all', reason: 'gate unused'}\n"
    text = GATE.format(rules="cheme.line-crossing", accept=accept)
    (plant / "checks" / "checks.yaml").write_text(text, encoding="utf-8")
    monkeypatch.chdir(plant)
    report = json.loads(runner.invoke(app, ["validate", "--json"]).output)
    unused = [f for f in report["findings"] if f["rule"] == "cheme.accept-unused"]
    assert [f["message"] for f in unused] == [
        "accept: 'nothing-at-all' (gate drawing-clean) names no finding"
    ]


def test_text_output_prints_the_id_of_every_acceptable_finding():
    from chemeascode.project.validate import Finding

    finding = Finding(
        "pid/P-04.xml",
        "warning",
        "cheme.label-tag-unknown",
        "'FV-3111' names no instrument",
        line=12,
        ids=["OPC_LOX3001_in"],
        key="OPC_LOX3001_in:P-07",
        hint="fix the text, or it can be accepted with a reason in checks/checks.yaml (accept:)",
    )
    assert finding.format().endswith(" [id pid/P-04.xml#label-tag-unknown:OPC_LOX3001_in:P-07]")
    plain = Finding("pid/P-04.xml", "error", "dexpi.schema", "bad", line=3)
    assert "[id " not in plain.format()


def test_template_and_init_say_how_to_keep_the_reference_sheet(plant: Path, tmp_path: Path):
    """The reference sheet fails drawing-clean by design; the template's
    comment and the init output give the accept line, and that line makes the template's gate
    pass."""
    import re

    import yaml

    from chemeascode.schemas import CheckList

    result = runner.invoke(app, ["init", str(tmp_path / "fresh"), "--name", "Fresh"])
    assert result.exit_code == 0
    note = " ".join(result.output.split())
    assert "drawing-clean gate" in note and "DEXPI reference P&ID" in note
    line = re.search(r"`accept: (\[.*?\])`", note).group(1)
    checks = plant / "checks" / "checks.yaml"
    text = checks.read_text(encoding="utf-8")
    assert '#     - {id: "pid/P-01.xml#*", reason: "DEXPI reference sheet' in text
    gate = next(
        c for c in CheckList.model_validate(yaml.safe_load(text)).checks if c.id == "drawing-clean"
    )
    assert not gate.accept
    by_id = {r.id: r for r in run_checks(Workspace(plant), stage="basic")}
    assert by_id["drawing-clean"].status == "fail"
    marker = "            cheme.label-far-from-owner]\n"
    assert text.count(marker) == 1
    checks.write_text(text.replace(marker, f"{marker}    accept: {line}\n"), encoding="utf-8")
    by_id = {r.id: r for r in run_checks(Workspace(plant), stage="basic")}
    assert by_id["drawing-clean"].status == "pass", by_id["drawing-clean"].detail
