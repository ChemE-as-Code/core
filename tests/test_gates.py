"""Gates of ``checks/checks.yaml`` beyond files and commands: on-sheet, review, sign-off."""

import re
from pathlib import Path

import yaml
from typer.testing import CliRunner

from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.checks import run_checks
from tests.conftest import git, without_layout_gates

runner = CliRunner()


def set_checks(root: Path, *checks: dict) -> None:
    (root / "checks" / "checks.yaml").write_text(yaml.safe_dump({"checks": list(checks)}))


def results(root: Path, stage: str | None = None) -> dict:
    return {r.id: r for r in run_checks(Workspace(root), stage)}


def on_sheet(check_id: str = "g", **fields) -> dict:
    return {"id": check_id, "title": "On sheet", "stage": "basic", "kind": "on-sheet", **fields}


# ---------------------------------------------------------------------------
# kind: on-sheet
# ---------------------------------------------------------------------------


def test_on_sheet_passes_on_printed_tags(plant: Path):
    set_checks(plant, on_sheet(sheet="P-01", tags=["PICSA-4712.02", "T4750", "47123"]))
    assert results(plant)["g"].status == "pass", results(plant)["g"].detail


def test_on_sheet_names_the_missing_tag(plant: Path):
    set_checks(plant, on_sheet(sheet="P-01", tags=["PICSA-4712.02", "AIA-9999"]))
    result = results(plant)["g"]
    assert result.status == "fail"
    assert result.detail == "P-01: AIA-9999 not drawn"


def test_on_sheet_wrong_sheet_fails(plant: Path):
    (plant / "pid" / "P-02.xml").write_bytes((plant / "pid" / "P-01.xml").read_bytes())
    text = (plant / "pid" / "P-02.xml").read_text(encoding="utf-8")
    (plant / "pid" / "P-02.xml").write_text(
        text.replace("<String>T4750</String>", "<String>T1</String>")
    )
    set_checks(
        plant,
        on_sheet("p1", sheet="P-01", tags=["T4750"]),
        on_sheet("p2", sheet="P-02", tags=["T4750"]),
        on_sheet("any", tags=["T4750"]),
        on_sheet("none", sheet="P-09", tags=["T4750"]),
    )
    found = results(plant)
    assert found["p1"].status == "pass"
    assert found["p2"].status == "fail" and "P-02: T4750 not drawn" in found["p2"].detail
    assert found["any"].status == "pass"
    assert found["none"].status == "fail" and "P-09: no such sheet" in found["none"].detail


def test_on_sheet_ignores_ids(plant: Path):
    """Renaming every id (not the printed tags) does not change the result."""
    set_checks(plant, on_sheet(sheet="P-01", tags=["PICSA-4712.02", "P4711"], connected=True))
    before = results(plant)["g"].status
    sheet = plant / "pid" / "P-01.xml"
    text = sheet.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', text))
    for old in sorted(ids, key=len, reverse=True):
        text = re.sub(rf'(id="|#){re.escape(old)}(?=["\s])', rf"\1Z{abs(hash(old))}", text)
    sheet.write_text(text, encoding="utf-8")
    assert "ProcessInstrumentationFunction2" not in text
    assert before == results(plant)["g"].status == "pass"


def test_on_sheet_class_count_and_connected(plant: Path):
    set_checks(
        plant,
        on_sheet("one", classes=["SafetyValve"], connected=True),
        on_sheet("two", classes=["SafetyValve"], min_count=2),
        on_sheet("valves", classes=["BallValve"], min_count=5),
    )
    found = results(plant)
    assert found["one"].status == "pass"
    assert found["two"].status == "fail" and "1 SafetyValve drawn, 2 needed" in found["two"].detail
    assert found["valves"].status == "pass"
    # Take the safety valve off its segment: no pipe and no segment end references it.
    sheet = plant / "pid" / "P-01.xml"
    text = sheet.read_text(encoding="utf-8")
    text = re.sub(
        r'\s*<References objects="#SpringLoadedGlobeSafetyValve1(_\w+)?" '
        r'property="(Source|Target)(Item|Node)"/>',
        "",
        text,
    )
    sheet.write_text(text, encoding="utf-8")
    set_checks(
        plant,
        on_sheet("one", classes=["SafetyValve"], connected=True),
        on_sheet("tag", tags=["SV 104.01"], connected=True),
        on_sheet("drawn", tags=["SV 104.01"]),
    )
    found = results(plant)
    assert found["one"].status == "fail"
    assert "0 connected SafetyValve" in found["one"].detail
    assert "SV 104.01 not connected" in found["one"].detail
    assert found["tag"].status == "fail"
    assert found["tag"].detail == "any sheet: SV 104.01 drawn but not connected"
    assert found["drawn"].status == "pass"


def test_on_sheet_schema(plant: Path):
    result = runner.invoke(app, ["schema", "checks"])
    assert "on-sheet" in result.output
    set_checks(plant, on_sheet())  # neither tags nor classes
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="needs tags or classes"):
        results(plant)


# ---------------------------------------------------------------------------
# kind: review, review records
# ---------------------------------------------------------------------------


def commit_all(root: Path, message: str = "change") -> str:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD").strip()


def write_record(
    root: Path,
    name: str = "2026-10-18-design",
    commit: str = "HEAD",
    kind: str = "agent",
    scope: tuple[str, ...] = ("pid/P-01.xml",),
    body: str = "",
    topic: str = "design",
    extra: str = "",
) -> Path:
    if commit == "HEAD":
        commit = git(root, "rev-parse", "HEAD").strip()
    path = root / "reviews" / f"{name}.md"
    path.write_text(
        "---\n"
        f"topic: {topic}\n"
        f"reviewed_commit: {commit}\n"
        f"scope: [{', '.join(scope)}]\n"
        "reviewer: Reviewer agent\n"
        f"reviewer_kind: {kind}\n"
        f"{extra}"
        "---\n"
        f"# Review: {topic}\n\n"
        "## Findings\n\n"
        "| id | sheet | item | finding | severity | status | proposed action |\n"
        "|---|---|---|---|---|---|---|\n"
        + (body or f"| {name}#1 | P-01 | T4750 | no vent | low | open | add one |\n"),
        encoding="utf-8",
    )
    return path


def review_gate(**fields) -> dict:
    return {
        "id": "review",
        "title": "Review",
        "stage": "basic",
        "kind": "review",
        "topic": "design",
        **fields,
    }


def test_review_gate_passes_for_a_current_agent_review(plant: Path):
    set_checks(plant, review_gate())
    commit_all(plant, "plant")
    write_record(plant)
    commit_all(plant, "review")
    result = results(plant)["review"]
    assert result.status == "pass", result.detail
    assert "agent-reviewed only" in result.detail
    assert result.evidence["reviewer_kind"] == "agent"
    assert result.evidence["path"] == "reviews/2026-10-18-design.md"
    assert len(result.evidence["reviewed_commit"]) == 40


def test_review_gate_fails_without_front_matter_or_record(plant: Path):
    set_checks(plant, review_gate(), review_gate(id="glob", topic=None, files=["reviews/2*.md"]))
    commit_all(plant)
    found = results(plant)
    assert found["review"].status == "fail" and "no review record" in found["review"].detail
    (plant / "reviews" / "2000-01-01-design.md").write_text("\n")
    commit_all(plant)
    found = results(plant)
    assert found["review"].status == "fail"
    assert "no front matter" in found["review"].detail
    assert found["glob"].status == "fail" and "no front matter" in found["glob"].detail


def test_review_gate_malformed_front_matter(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    set_checks(plant, review_gate())
    commit_all(plant)
    path = plant / "reviews" / "2026-10-18-design.md"
    path.write_text("---\ntopic: design\nreviewer: me\n---\n## Findings\n")
    commit_all(plant)
    result = results(plant)["review"]
    assert result.status == "fail"
    assert "reviewed_commit" in result.detail and "Field required" in result.detail
    malformed = [f for f in validate_findings(plant) if f["rule"] == "cheme.review-front-matter"]
    assert malformed and malformed[0]["level"] == "warning"


def test_review_gate_stale_when_a_scoped_sheet_changes(plant: Path):
    set_checks(plant, review_gate())
    commit_all(plant)
    write_record(plant, scope=("pid/P-01.xml", "DESIGN.md"))
    commit_all(plant, "review")
    assert results(plant)["review"].status == "pass"
    sheet = plant / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<String>T4750</String>", "<String>T4751</String>"))
    result = results(plant)["review"]  # uncommitted edits count too
    assert result.status == "fail" and "changed since" in result.detail
    assert "pid/P-01.xml" in result.detail
    commit_all(plant, "edit")
    result = results(plant)["review"]
    assert result.status == "fail" and "pid/P-01.xml" in result.detail
    assert results(plant)  # an unscoped change does not make it stale:
    set_checks(plant, review_gate(current=False))
    assert results(plant)["review"].status == "pass"


def test_a_digest_only_regeneration_keeps_a_review_current(plant: Path):
    from chemeascode.foundation.reviews import coverage

    study = plant / "layout" / "lifting-study.md"
    line = "Generated from `layout/plant-model.yaml` (model output_sha256 `{}`), commit {}.\n"
    study.write_text(line.format("a" * 64, "1" * 40) + "| K-1 | 12 t |\n", encoding="utf-8")
    set_checks(plant, review_gate())
    commit_all(plant)
    write_record(plant, scope=("pid/P-01.xml", "layout/lifting-study.md"))
    commit_all(plant, "review")
    # a regeneration whose only change is its fingerprints (uncommitted, committed, CRLF)
    study.write_bytes((line.format("b" * 64, "2" * 40) + "| K-1 | 12 t |\n").encode())
    assert results(plant)["review"].status == "pass", results(plant)["review"].detail
    commit_all(plant, "rebuilt")
    assert results(plant)["review"].status == "pass", results(plant)["review"].detail
    assert coverage(Workspace(plant), "layout/lifting-study.md")["status"] == "reviewed"
    study.write_bytes(study.read_bytes().replace(b"\n", b"\r\n"))
    assert results(plant)["review"].status == "pass"
    # a changed value is a change; so is a shorter hex run (a value fingerprint)
    study.write_text(line.format("b" * 64, "2" * 40) + "| K-1 | 13 t |\n", encoding="utf-8")
    result = results(plant)["review"]
    assert result.status == "fail" and "layout/lifting-study.md" in result.detail
    assert coverage(Workspace(plant), "layout/lifting-study.md")["status"] == "drafted"
    study.write_text(line.format("b" * 63, "2" * 40) + "| K-1 | 12 t |\n", encoding="utf-8")
    assert results(plant)["review"].status == "fail"
    study.unlink()  # a deleted file has changed
    assert results(plant)["review"].status == "fail"


def test_review_gate_reviewer_kind(plant: Path):
    set_checks(
        plant,
        review_gate(),
        review_gate(id="human", require_kind=["human"]),
        review_gate(id="self", require_kind=["self"]),
    )
    commit_all(plant)
    write_record(plant, kind="self")
    commit_all(plant, "review")
    found = results(plant)
    assert found["review"].status == "fail" and "reviewer_kind self" in found["review"].detail
    assert found["human"].status == "fail"
    assert found["self"].status == "pass"
    write_record(plant, kind="agent")
    commit_all(plant, "review")
    found = results(plant)
    assert found["human"].status == "fail" and "is not human" in found["human"].detail


def test_review_gate_not_an_ancestor(plant: Path):
    set_checks(plant, review_gate())
    commit_all(plant)
    git(plant, "checkout", "-qb", "side")
    (plant / "DESIGN.md").write_text("side\n")
    side = commit_all(plant, "side")
    git(plant, "checkout", "-q", "main")
    write_record(plant, commit=side)
    commit_all(plant, "review")
    result = results(plant)["review"]
    assert result.status == "fail" and "not an ancestor of HEAD" in result.detail


def test_review_gate_reads_a_scope_with_a_leading_slash(plant: Path, monkeypatch):
    """#190: '/pid/P-01.xml' made git fail, and the failure read as 'unchanged'."""
    monkeypatch.chdir(plant)
    set_checks(plant, review_gate())
    commit_all(plant)
    write_record(plant, scope=("/pid/P-01.xml",))
    commit_all(plant, "review")
    assert results(plant)["review"].status == "pass"
    sheet = plant / "pid" / "P-01.xml"
    sheet.write_text(sheet.read_text().replace("<String>T4750</String>", "<String>T4751</String>"))
    commit_all(plant, "edit")
    result = results(plant)["review"]
    assert result.status == "fail" and "changed since" in result.detail
    assert "pid/P-01.xml" in result.detail
    from chemeascode.foundation.reviews import coverage

    assert coverage(Workspace(plant), "pid/P-01.xml")["status"] == "drafted"
    form = [f for f in validate_findings(plant) if f["rule"] == "cheme.review-scope-missing"]
    assert len(form) == 1 and "it is read as 'pid/P-01.xml'" in form[0]["message"]
    assert form[0]["level"] == "warning"


def test_scope_entries_for_the_whole_repository(plant: Path, monkeypatch):
    """'.' is the whole repository; '/' and './' are read so too, and are reported."""
    from chemeascode.foundation.reviews import coverage

    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(plant, scope=(".", "/", "./", "./pid/P-01.xml"))
    commit_all(plant, "review")
    form = {
        f["message"].split(",")[0]: f["level"]
        for f in validate_findings(plant)
        if f["rule"] == "cheme.review-scope-missing"
    }
    assert form == {
        "scope names '/'": "warning",
        "scope names './'": "info",
        "scope names './pid/P-01.xml'": "info",
    }
    assert coverage(Workspace(plant), "DESIGN.md")["record"] == "reviews/2026-10-18-design.md"


def test_a_git_failure_never_makes_a_review_current(plant: Path, monkeypatch):
    from chemeascode.foundation import gitinfo
    from chemeascode.foundation.reviews import coverage

    set_checks(plant, review_gate())
    commit_all(plant)
    write_record(plant)
    commit_all(plant, "review")
    assert gitinfo.changed_since(plant, "0" * 40, ["pid"]) is None  # unknown commit
    assert gitinfo.changed_since(plant, "HEAD", ["/pid/P-01.xml"]) is None  # git exits 128
    monkeypatch.setattr(gitinfo, "changed_since", lambda *args: None)
    result = results(plant)["review"]
    assert result.status == "fail" and "cannot tell whether its scope changed" in result.detail
    found = coverage(Workspace(plant), "pid/P-01.xml")
    assert found["status"] == "drafted" and "cannot tell" in found["detail"]


def test_paths_with_spaces_stay_whole(plant: Path):
    from chemeascode.foundation import gitinfo

    set_checks(plant, review_gate(), review_gate(id="notes", topic="notes"))
    (plant / "notes").mkdir()
    (plant / "notes" / "design notes.md").write_text("first\n")
    start = commit_all(plant)
    write_record(plant, name="2026-10-18-notes", topic="notes", scope=("notes/design notes.md",))
    commit_all(plant, "notes review")
    # the record lies in its own scope: it must not count as a change to it
    write_record(plant, name="2026-10-18-design review", scope=("reviews/",))
    commit_all(plant, "review")
    found = results(plant)
    assert found["review"].status == "pass", found["review"].detail
    assert found["notes"].status == "pass", found["notes"].detail
    (plant / "notes" / "design notes.md").write_text("second\n")
    (plant / "notes" / "new file.md").write_text("untracked\n")
    assert gitinfo.changed_since(plant, start, ["notes"]) == [
        "notes/design notes.md",
        "notes/new file.md",
    ]
    found = results(plant)
    assert found["notes"].status == "fail" and "notes/design notes.md" in found["notes"].detail


def validate_findings(root: Path) -> list[dict]:
    import json

    result = runner.invoke(app, ["validate", "--json"])
    return [
        f for f in json.loads(result.output)["findings"] if f["rule"].startswith("cheme.review")
    ]


def test_validate_review_records(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    commit_all(plant)
    (plant / "reviews" / "2026-10-01-old.md").write_text("# Review\n")
    write_record(
        plant,
        name="2026-10-18-design",
        commit="0" * 40,
        scope=("pid/P-01.xml", "pid/P-99.xml"),
        body="| 7 | P-01 | x | y | high | partly closed | z |\n"
        "| 2026-10-18-design#2 | P-01 | x | y | serious | closed abcdef1 | z |\n",
    )
    rules = {(f["rule"], f["file"]) for f in validate_findings(plant)}
    assert ("cheme.review-front-matter", "reviews/2026-10-01-old.md") in rules
    record = "reviews/2026-10-18-design.md"
    for rule in (
        "cheme.review-unknown-commit",
        "cheme.review-scope-missing",
        "cheme.review-finding-id",
        "cheme.review-finding-status",
    ):
        assert (rule, record) in rules, rule
    messages = " ".join(f["message"] for f in validate_findings(plant))
    assert "status 'partly closed' is not open" in messages
    assert "abcdef1, which is not a commit" in messages
    assert "severity 'serious'" in messages


def test_previous_findings_must_be_carried_forward(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(
        plant,
        name="2026-10-01-design",
        body="| 2026-10-01-design#1 | P-01 | T4750 | no vent | high | open | add |\n"
        "| 2026-10-01-design#2 | P-01 | P4711 | no drain | low | accepted: via casing, A. P. |"
        " - |\n",
    )
    commit_all(plant, "first review")
    write_record(plant, name="2026-10-18-design")
    missing = [f for f in validate_findings(plant) if f["rule"] == "cheme.review-previous-missing"]
    assert len(missing) == 1 and missing[0]["ids"] == ["2026-10-01-design#1"]
    assert "no ## Previous findings section" in missing[0]["message"]
    path = plant / "reviews" / "2026-10-18-design.md"
    fix = commit_all(plant, "fix the vent")
    path.write_text(
        path.read_text()
        + "\n## Previous findings\n\n| id | finding | severity | status | evidence |\n"
        "|---|---|---|---|---|\n"
        f"| 2026-10-01-design#1 | no vent | high | closed {fix[:7]} | vent drawn |\n"
    )
    assert not [f for f in validate_findings(plant) if f["rule"] == "cheme.review-previous-missing"]
    from chemeascode.foundation.reviews import load_records, open_findings

    still_open = {row.id for row in open_findings(load_records(Workspace(plant)))}
    assert still_open == {"2026-10-18-design#1"}


def test_schema_review_and_hyphenated_kinds():
    assert "reviewer_kind" in runner.invoke(app, ["schema", "review"]).output
    assert runner.invoke(app, ["schema", "site-plan"]).exit_code == 0
    assert "review" in runner.invoke(app, ["schema"]).output


# ---------------------------------------------------------------------------
# sign-off (check --write)
# ---------------------------------------------------------------------------


def status_json(root: Path) -> dict:
    import json

    return json.loads((root / "checks" / "status.json").read_text())


def accept_reference_drawing(plant: Path) -> None:
    """Accept the reference sheet's crossings and labels, so the drawing-clean gate passes."""
    checks = plant / "checks" / "checks.yaml"
    accept = "accept:\n  - {id: 'pid/P-01.xml#*', reason: reference sheet as drawn by DEXPI}\n"
    text = checks.read_text().replace("accept: []\n", accept)
    # the reference plant's flowsheet is empty: no PFD to build, so process-basic does not apply
    text = text.replace("    generated: [pfd]", "    applies: false\n    generated: [pfd]")
    checks.write_text(text)


def signed_plant(plant: Path, monkeypatch) -> Path:
    """The plant with every concept and basic gate passing (the layout gates n/a), committed."""
    monkeypatch.chdir(plant)
    without_layout_gates(plant)
    basis = plant / "process" / "design-basis.yaml"
    basis.write_text(basis.read_text() + "# capacity ASSUMED\n")
    accept_reference_drawing(plant)
    commit_all(plant, "plant")
    write_record(plant)
    commit_all(plant, "review")
    return plant


def test_sign_off_records_provenance_per_stage(plant: Path, monkeypatch):
    signed_plant(plant, monkeypatch)
    result = runner.invoke(app, ["check", "--stage", "concept", "--write"])
    assert result.exit_code == 0, result.output
    git(plant, "add", "checks/status.json")
    git(plant, "commit", "-qm", "sign off concept")
    head = git(plant, "rev-parse", "HEAD").strip()
    result = runner.invoke(
        app,
        ["check", "--stage", "basic", "--write", "--review", "reviews/2026-10-18-design.md"],
    )
    assert result.exit_code == 0, result.output
    assert "[concept] design-basis" in result.output  # gates of earlier stages run too
    status = status_json(plant)
    assert set(status["stages"]) == {"concept", "basic"}
    basic = status["stages"]["basic"]
    assert basic["commit"] == head
    assert basic["signed_by"] == "Test"
    assert basic["branch"] == "main"
    assert basic["review"] == "reviews/2026-10-18-design.md"
    assert basic["reviewer_kind"] == "agent"
    assert basic["date"].endswith("Z")
    assert basic["stages"] == ["concept", "basic"]
    gates = {c["id"]: c for c in basic["checks"]}
    assert {"design-basis", "pids-valid", "design-review"} <= set(gates)
    assert gates["design-review"]["evidence"]["reviewer_kind"] == "agent"
    assert "evidence" not in gates["pids-valid"]
    assert status["checks"] == basic["checks"]
    assert runner.invoke(app, ["schema", "status"]).exit_code == 0
    from chemeascode.schemas import StatusFile

    StatusFile.model_validate(status)


def test_only_stage_keeps_the_old_selection(plant: Path, monkeypatch):
    signed_plant(plant, monkeypatch)
    result = runner.invoke(app, ["check", "--stage", "basic", "--only-stage"])
    assert "[concept]" not in result.output and "[basic] pids-valid" in result.output
    assert runner.invoke(app, ["check", "--stage", "nope"]).exit_code == 2


def test_sign_off_refuses_a_dirty_tree(plant: Path, monkeypatch):
    signed_plant(plant, monkeypatch)
    (plant / "DESIGN.md").write_text("changed\n")
    result = runner.invoke(app, ["check", "--stage", "concept", "--write"])
    assert result.exit_code == 1
    assert "uncommitted changes: DESIGN.md" in result.output
    assert not (plant / "checks" / "status.json").exists()


def test_sign_off_refuses_when_git_cannot_tell_whether_the_tree_is_clean(plant: Path, monkeypatch):
    from chemeascode.foundation import gitinfo

    signed_plant(plant, monkeypatch)
    monkeypatch.setattr(gitinfo, "dirty_paths", lambda root: None)
    result = runner.invoke(app, ["check", "--stage", "concept", "--write"])
    assert result.exit_code == 1
    assert "git cannot tell whether the working tree has uncommitted changes" in result.output
    assert not (plant / "checks" / "status.json").exists()


def test_sign_off_refuses_a_failing_gate(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    commit_all(plant)  # no review record: design-review fails
    result = runner.invoke(app, ["check", "--stage", "basic", "--write"])
    assert result.exit_code == 1
    assert (
        "failing gate(s): process-basic, assumptions-marked, drawing-clean, design-review"
        in result.output
    )
    assert not (plant / "checks" / "status.json").exists()


def test_sign_off_refuses_a_self_signed_review(plant: Path, monkeypatch):
    signed_plant(plant, monkeypatch)
    args = ["check", "--stage", "basic", "--write", "--review", "reviews/2026-10-18-design.md"]
    result = runner.invoke(app, [*args, "--by", "Reviewer agent"])
    assert result.exit_code == 1 and "is a self review" in result.output
    assert not (plant / "checks" / "status.json").exists()
    write_record(plant, kind="self")
    set_checks(plant, review_gate(require_kind=["self"]))
    commit_all(plant, "self review")
    result = runner.invoke(app, args)
    assert result.exit_code == 1 and "is a self review" in result.output
    write_record(plant, kind="self", extra="approved_by: A. Human\n")
    commit_all(plant, "approved")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert status_json(plant)["stages"]["basic"]["approved_by"] == "A. Human"


def test_sign_off_refuses_open_high_findings(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(
        plant, body="| 2026-10-18-design#1 | P-01 | T4750 | no PSV | high | open | add |\n"
    )
    commit_all(plant, "review")
    result = runner.invoke(app, ["check", "--stage", "basic", "--write"])
    assert result.exit_code == 1
    assert "open critical/high finding(s): 2026-10-18-design#1 (high)" in result.output


def test_a_high_finding_carried_forward_without_severity_still_blocks(plant: Path, monkeypatch):
    """#225: the latest row's empty severity cleared the 'high' of the first record."""
    from chemeascode.foundation.reviews import (
        blocking_ids,
        coverage,
        load_records,
        open_blocking,
        review_rules,
    )
    from chemeascode.project.signoff import SignOffRefused, sign_off

    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(
        plant,
        name="2026-10-01-design",
        body="| 2026-10-01-design#1 | P-01 | T4750 | no vent | high | open | add one |\n",
    )
    commit_all(plant, "first review")
    own = "| 2026-10-02-design#1 | P-01 | T4750 | font | low | accepted: cosmetic, A. P. | - |\n"
    path = write_record(plant, name="2026-10-02-design", body=own)
    first = path.read_text()
    path.write_text(
        first + "\n## Previous findings\n\n| id | finding | status |\n|---|---|---|\n"
        "| 2026-10-01-design#1 | T4750 has no vent | open |\n"
    )
    commit_all(plant, "second review")
    workspace = Workspace(plant)
    records = load_records(workspace)
    assert [(r.id, r.severity, r.record) for r in open_blocking(records)] == [
        ("2026-10-01-design#1", "high", "reviews/2026-10-02-design.md")
    ]
    try:
        sign_off(workspace, "concept", ["concept"], [], by="Carol")
    except SignOffRefused as refused:
        assert "open critical/high finding(s): 2026-10-01-design#1 (high)" in str(refused)
    else:
        raise AssertionError("signed off over an open high finding")
    # coverage names the same blocking finding
    found = coverage(workspace, "pid/P-01.xml", records)
    assert found["status"] == "reviewed" and "open 2026-10-01-design#1" in found["detail"]
    assert blocking_ids(records, records) == {"2026-10-01-design#1"}
    dropped = [f for f in review_rules(workspace, records) if f.ids == ["2026-10-01-design#1"]]
    assert [(f.level, f.rule, f.file) for f in dropped] == [
        ("warning", "cheme.review-finding-status", "reviews/2026-10-02-design.md")
    ]
    assert "earlier record rated it high" in dropped[0].message
    # a lower severity does not lower it either
    path.write_text(
        first + "\n## Previous findings\n\n| id | finding | severity | status |\n"
        "|---|---|---|---|\n| 2026-10-01-design#1 | T4750 has no vent | medium | open |\n"
    )
    assert [r.id for r in open_blocking(load_records(workspace))] == ["2026-10-01-design#1"]
    # cheme status and /api/status rate it as sign-off does
    path.write_text(
        first + "\n## Previous findings\n\n| id | finding | status |\n|---|---|---|\n"
        "| 2026-10-01-design#1 | T4750 has no vent | open |\n"
    )
    from chemeascode.project.status import plant_status

    shown = plant_status(workspace, run_gates=False)["reviews"]["open"]
    assert [(r["id"], r["severity"]) for r in shown] == [("2026-10-01-design#1", "high")]


def test_a_blocking_finding_with_a_malformed_id_refuses_and_is_shown(plant: Path, monkeypatch):
    """Review of pre-release PR 281: a row whose id is not <record>#<n> blocks the sign-off on its
    own, and cheme status and /api/status list it."""
    from chemeascode.project.signoff import SignOffRefused, sign_off
    from chemeascode.project.status import plant_status

    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(plant, body="| H-1 | P-01 | T4750 | no vent | high | open | add one |\n")
    commit_all(plant, "review")
    workspace = Workspace(plant)
    try:
        sign_off(workspace, "concept", ["concept"], [], by="Carol")
    except SignOffRefused as refused:
        assert "open critical/high finding(s): H-1 (high)" in str(refused)
    else:
        raise AssertionError("signed off over an open high finding with a malformed id")
    shown = plant_status(workspace, run_gates=False)["reviews"]["open"]
    assert [(r["id"], r["severity"], r["record"]) for r in shown] == [
        ("H-1", "high", "reviews/2026-10-18-design.md")
    ]


def test_a_high_finding_closed_without_severity_needs_a_real_commit(plant: Path, monkeypatch):
    """Review of pre-release PR 281: 'closed <sha not in history>' without a severity cell still
    refuses."""
    from chemeascode.project.signoff import SignOffRefused, sign_off

    monkeypatch.chdir(plant)
    commit_all(plant)
    write_record(
        plant,
        name="2026-10-01-design",
        body="| 2026-10-01-design#1 | P-01 | T4750 | no vent | high | open | add one |\n",
    )
    commit_all(plant, "first review")
    own = "| 2026-10-02-design#1 | P-01 | T4750 | font | low | accepted: cosmetic, A. P. | - |\n"
    path = write_record(plant, name="2026-10-02-design", body=own)
    path.write_text(
        path.read_text() + "\n## Previous findings\n\n| id | finding | status |\n|---|---|---|\n"
        "| 2026-10-01-design#1 | T4750 has no vent | closed deadbee |\n"
    )
    commit_all(plant, "second review")
    try:
        sign_off(Workspace(plant), "concept", ["concept"], [], by="Carol")
    except SignOffRefused as refused:
        assert "2026-10-01-design#1 (closed deadbee)" in str(refused)
    else:
        raise AssertionError("signed off over a high finding closed by an unknown commit")


def test_sign_off_refuses_a_high_finding_closed_by_an_unknown_commit(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    without_layout_gates(plant)
    basis = plant / "process" / "design-basis.yaml"
    basis.write_text(basis.read_text() + "# capacity ASSUMED\n")
    accept_reference_drawing(plant)
    fix = commit_all(plant, "plant")
    args = ["check", "--stage", "basic", "--write", "--review", "reviews/2026-10-18-design.md"]
    row = "| 2026-10-18-design#1 | P-01 | T4750 | no PSV | high | closed {} | added |\n"
    write_record(plant, body=row.format("deadbee"))
    commit_all(plant, "review")
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert "2026-10-18-design#1 (closed deadbee)" in result.output
    assert "cheme.review-* warning(s)" in result.output
    assert not (plant / "checks" / "status.json").exists()
    # a real commit that is not in HEAD's history does not close it either
    git(plant, "checkout", "-qb", "side")
    (plant / "side.txt").write_text("unmerged fix\n")
    side = commit_all(plant, "unmerged fix")
    git(plant, "checkout", "-q", "main")
    write_record(plant, body=row.format(side[:7]))
    commit_all(plant, "closed by a commit on another branch")
    result = runner.invoke(app, args)
    assert result.exit_code == 1 and f"(closed {side[:7]})" in result.output
    write_record(plant, body=row.format(fix[:7]))
    commit_all(plant, "closed by the real fix")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output


def test_sign_off_on_a_branch_says_merge(plant: Path, monkeypatch):
    signed_plant(plant, monkeypatch)
    git(plant, "checkout", "-qb", "stage/basic-closeout")
    result = runner.invoke(app, ["check", "--stage", "concept", "--write"])
    assert result.exit_code == 0, result.output
    assert "not main: merge to make the sign-off effective" in result.output
    assert status_json(plant)["stages"]["concept"]["branch"] == "stage/basic-closeout"


def test_a_gate_naming_an_unknown_stage_is_not_dropped(plant: Path, monkeypatch):
    """#222: 'stage: Concept' dropped the gate from check --stage concept and the sign-off."""
    monkeypatch.chdir(plant)
    command = {"title": "HAZOP done", "kind": "command", "command": "true"}
    set_checks(
        plant,
        {"id": "hazop-done", "stage": "Concept", **command},
        {"id": "ok", "stage": "concept", **command},
        {"id": "ok", "stage": "basic", **command},
    )
    commit_all(plant)
    result = runner.invoke(app, ["check", "--stage", "concept"])
    assert result.exit_code == 1
    assert "FAIL [Concept] hazop-done" in result.output
    assert "stage 'Concept' is not a stage of plant.yaml (concept, basic, detail)" in result.output
    assert "[basic]" not in result.output
    result = runner.invoke(app, ["check", "--stage", "concept", "--write", "--by", "Carol"])
    assert result.exit_code == 1 and "failing gate(s): hazop-done" in result.output
    assert not (plant / "checks" / "status.json").exists()
    import json

    findings = json.loads(runner.invoke(app, ["validate", "--json"]).output)["findings"]
    rules = {
        (f["rule"], f["level"], f["line"]) for f in findings if f["rule"].startswith("cheme.check-")
    }
    assert rules == {
        ("cheme.check-stage-unknown", "error", 5),  # its stage: line
        ("cheme.check-duplicate-id", "error", 13),  # the second id: line
    }


def test_validate_gate_fail_on_warning(plant: Path):
    set_checks(
        plant,
        {"id": "e", "title": "E", "stage": "basic", "kind": "validate"},
        {"id": "w", "title": "W", "stage": "basic", "kind": "validate", "fail_on": "warning"},
    )
    found = results(plant)
    assert found["e"].status == "pass"  # the reference P&ID has warnings, no errors
    assert found["w"].status == "fail" and "warning(s)" in found["w"].detail


# ---------------------------------------------------------------------------
# datasheets
# ---------------------------------------------------------------------------


def readme_example() -> dict:
    from chemeascode.templates.install import template_dir

    text = (template_dir() / "equipment" / "datasheets" / "README.md").read_text()
    return yaml.safe_load(text.split("```yaml\n", 1)[1].split("```", 1)[0])


def test_template_datasheet_example_validates():
    from chemeascode.schemas import Datasheet

    sheet = Datasheet.model_validate(readme_example())
    assert sheet.tag == "P-101A"
    assert runner.invoke(app, ["schema", "datasheet"]).exit_code == 0


def test_datasheets_gate_and_validate(plant: Path, monkeypatch):
    import json

    monkeypatch.chdir(plant)
    found = results(plant, None)
    assert {"concept-lists", "assumptions-marked", "datasheets"} <= set(found)
    assert found["datasheets"].status == "fail" and "empty" in found["datasheets"].detail
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        "  - {tag: P-101A, type: CentrifugalPump, design_pressure_barg: 10,"
        " design_temperature_degc: 80}\n"
        "  - {tag: T4750, type: Tank}\n"
    )
    found = results(plant)
    assert found["datasheets"].status == "fail"
    assert "for P-101A, T4750" in found["datasheets"].detail
    folder = plant / "equipment" / "datasheets"
    (folder / "P-101A.yaml").write_text(yaml.safe_dump(readme_example()))
    (folder / "T4750.yaml").write_text("tag: T4750\ntype: Tank\n")
    assert results(plant)["datasheets"].status == "pass"

    def datasheet_findings() -> list[dict]:
        report = json.loads(runner.invoke(app, ["validate", "--json"]).output)
        return [
            f
            for f in report["findings"]
            if "datasheet" in f["rule"] or f["file"].startswith("equipment/datasheets")
        ]

    assert datasheet_findings() == []
    example = readme_example()
    example["design"]["pressure_barg"] = 16
    (folder / "P-101A.yaml").write_text(yaml.safe_dump(example))
    (folder / "X-1.yaml").write_text("tag: X-1\n")
    (folder / "bad.yaml").write_text("tag: B-1\nflow: 3\n")
    rules = {(f["rule"], f["file"]) for f in datasheet_findings()}
    assert ("cheme.datasheet-mismatch", "equipment/datasheets/P-101A.yaml") in rules
    assert ("cheme.datasheet-not-listed", "equipment/datasheets/X-1.yaml") in rules
    assert ("yaml.schema", "equipment/datasheets/bad.yaml") in rules
