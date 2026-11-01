"""HAZOP studies: the risk matrix lookup, the study file, validation,
staleness, rating, the report, the review record and the gate. The plant is
``examples/safety-hazop``."""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.safety.hazop import (
    dump_study,
    load_study,
    rate,
    rating_rows,
    study_findings,
    write_bands,
)
from chemeascode.domains.safety.risk_matrix import EXAMPLE_MATRIX, load_matrix, lookup
from chemeascode.domains.safety.schemas import HazopStudy, RiskMatrix
from chemeascode.foundation.schemas.checks import Check
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.hazop import hazop_gate, review_draft, study_summaries
from chemeascode.project.impact import review_needed
from chemeascode.project.validate import validate_workspace
from chemeascode.templates.install import init
from tests.conftest import git

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "safety-hazop"
STUDY = "safety/hazop/H-01/study.yaml"
runner = CliRunner()


def _plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def example(tmp_path: Path) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build"))
    (root / "reviews").mkdir(exist_ok=True)  # git keeps no empty directory
    return root


def _rules(findings, file=STUDY):
    return {f.rule for f in findings if f.file == file}


def _study(root: Path):
    return study_findings(Workspace(root), load_study(root, STUDY))


def _edit(root: Path, old: str, new: str, path: str = STUDY) -> None:
    file = root / path
    text = file.read_text(encoding="utf-8")
    assert old in text, old
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# -- the matrix and its lookup ----------------------------------------------------------------


def test_every_cell_of_the_example_matrix_gives_its_configured_band():
    raw = yaml.safe_load(EXAMPLE_MATRIX.read_text(encoding="utf-8"))
    matrix = RiskMatrix.model_validate(raw)
    checked = 0
    for category in raw["categories"]:
        cells = category.get("cells") or raw["cells"]
        for severity, row in cells.items():
            for likelihood, band in row.items():
                found = lookup(matrix, category["id"], severity, likelihood)
                assert found.band == band and not found.problem
                assert found.rank == [b["id"] for b in raw["bands"]].index(band)
                checked += 1
    assert checked == 3 * 4 * 4


def test_missing_and_unknown_inputs_give_no_band():
    matrix = load_matrix(EXAMPLE_MATRIX.parent, EXAMPLE_MATRIX.name).model
    assert lookup(matrix, "people", None, "C").problem == "missing"
    assert lookup(matrix, "people", "3", None).problem == "missing"
    assert lookup(matrix, "people", "5", "C").problem == "unknown-severity"
    assert lookup(matrix, "people", "3", "E").problem == "unknown-likelihood"
    assert lookup(matrix, "safety", "3", "C").problem == "unknown-category"
    for result in (lookup(matrix, "people", "5", "C"), lookup(matrix, "people", None, "C")):
        assert result.band is None and result.rank is None


def _matrix(tmp_path: Path, text: str):
    (tmp_path / "m.yaml").write_text(text, encoding="utf-8")
    return load_matrix(tmp_path, "m.yaml")


SMALL = """\
schema: cheme/risk-matrix/v1
kind: risk-matrix
id: small
bands: [{id: low}, {id: high, requires_action: true}]
likelihood: [{code: A}, {code: B}]
severity: [{code: "1"}, {code: "2"}]
categories: [{id: people}]
cells:
  "1": {A: low, B: low}
  "2": {A: low, B: high}
"""


def test_matrix_rules_reject_duplicate_unknown_and_missing_cells(tmp_path):
    assert _matrix(tmp_path, SMALL).usable
    duplicate = _matrix(
        tmp_path, SMALL.replace('"2": {A: low, B: high}', '"2": {A: low, A: high, B: high}')
    )
    assert "cheme.risk-matrix-duplicate" in {f.rule for f in duplicate.findings}
    assert not duplicate.usable
    incomplete = _matrix(tmp_path, SMALL.replace('"2": {A: low, B: high}', '"2": {A: low}'))
    finding = next(f for f in incomplete.findings if f.rule == "cheme.risk-matrix-incomplete")
    assert "2/B" in finding.message and finding.line
    unknown = _matrix(
        tmp_path,
        SMALL.replace("B: high}", "B: extreme}").replace("{A: low, B: low}", "{A: low, C: low}"),
    )
    rules = {f.rule for f in unknown.findings}
    assert {"cheme.risk-matrix-unknown-band", "cheme.risk-matrix-unknown-code"} <= rules
    twice = _matrix(tmp_path, SMALL.replace("{code: B}]", "{code: B}, {code: B}]"))
    assert "cheme.risk-matrix-duplicate" in {f.rule for f in twice.findings}


def test_band_order_is_the_matrix_order_not_the_alphabet(tmp_path):
    reordered = SMALL.replace(
        "bands: [{id: low}, {id: high, requires_action: true}]",
        "bands: [{id: zz-minor}, {id: aa-major}]",
    )
    reordered = reordered.replace("low", "zz-minor").replace("high", "aa-major")
    matrix = _matrix(tmp_path, reordered).model
    assert lookup(matrix, "people", "2", "B").rank == 1
    assert lookup(matrix, "people", "1", "A").rank == 0


# -- the example ------------------------------------------------------------------------------


def test_the_example_loads_validates_and_renders(example):
    report = validate_workspace(Workspace(example))
    assert not [f for f in report.findings if f.level == "error"]
    assert not [f for f in report.findings if f.file == STUDY and f.level == "warning"]
    assert "hazop" in report.compared["lists"]
    (summary,) = study_summaries(Workspace(example), findings=report.findings)
    assert summary.state == "draft"  # example data and a proposal: never assessed
    assert "cheme.hazop-example" in _rules(summary.findings)


def test_cli_rate_check_report_on_the_example(example, monkeypatch):
    monkeypatch.chdir(example)
    out = runner.invoke(app, ["safety", "hazop", "rate", "H-01"])
    assert out.exit_code == 0, out.output
    assert "N2 S3 initial  people 3/C" in out.output and "-> high" in out.output
    out = runner.invoke(app, ["safety", "hazop", "check", "H-01"])
    assert out.exit_code == 0 and f"{STUDY}: draft" in _plain(out.output)
    out = runner.invoke(app, ["safety", "hazop", "report", "H-01"])
    assert out.exit_code == 0, out.output
    md = (example / "build" / "hazop" / "H-01.md").read_text(encoding="utf-8")
    page = (example / "build" / "hazop" / "H-01.html").read_text(encoding="utf-8")
    assert "EXAMPLE DATA" in md and "State: draft" in md
    assert "PROPOSED by agent (skill hazop-study)" in md  # S4 is not shown as accepted
    assert "people 3/C → high" in md and "people 3/B → medium" in md
    assert "example-4x4" in md and "sha256:" in md
    assert "class=proposed" in page


def test_the_skill_carries_the_example_study():
    skill = ROOT / "src/chemeascode/domains/safety/skills/hazop-study/examples/study.yaml"
    assert skill.read_bytes() == (EXAMPLE / STUDY).read_bytes()


def test_a_fresh_project_documents_the_study_location(tmp_path):
    root = tmp_path / "plant"
    init(root, "Fresh")
    readme = (root / "safety" / "README.md").read_text(encoding="utf-8")
    assert "safety/hazop/<study-id>/study.yaml" in readme and "## Workflow" in readme
    matrix = load_matrix(root, "safety/risk-matrix.yaml")
    assert matrix.usable and matrix.model.example  # the template's matrix says it is an example
    assert not (root / "safety" / "hazop").exists()  # no empty study to mistake for one
    for skill in ("hazop-study", "hazop-assessment", "hazop-review"):
        assert (root / ".claude" / "skills" / skill / "SKILL.md").is_file()
    assert not [f for f in validate_workspace(Workspace(root)).findings if "hazop" in f.rule]


def test_init_writes_a_draft_without_judgements(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    init(root, "Fresh")
    (root / "pid").mkdir(exist_ok=True)
    shutil.copy(EXAMPLE / "pid" / "P-01.xml", root / "pid" / "P-01.xml")
    monkeypatch.chdir(root)
    out = runner.invoke(
        app, ["safety", "hazop", "init", "H-02", "--title", "Feed: pump", "--input", "pid/P-01.xml"]
    )
    assert out.exit_code == 0, out.output
    loaded = load_study(root, "safety/hazop/H-02/study.yaml")
    assert (
        loaded.model.title == "Feed: pump" and loaded.model.risk_matrix == "safety/risk-matrix.yaml"
    )
    assert loaded.model.analysed[0].revision.startswith("sha256:") and not loaded.model.nodes
    (summary,) = study_summaries(Workspace(root), "H-02")
    assert summary.state == "draft"
    assert runner.invoke(app, ["safety", "hazop", "init", "H-02"]).exit_code == 2


# -- the study file ---------------------------------------------------------------------------


def test_load_dump_load_keeps_ids_references_and_judgements():
    study = load_study(EXAMPLE, STUDY).model
    text = dump_study(study)
    again = HazopStudy.model_validate(yaml.safe_load(text))
    assert again == study
    assert "status: proposed" in text  # a proposal says so, also where it is the default
    assert again.scenarios()[3][2].by == "agent (skill hazop-study)"


def test_reordering_keeps_identity_and_current_bands(example):
    data = yaml.safe_load((example / STUDY).read_text(encoding="utf-8"))
    data["nodes"].reverse()
    data["nodes"][1]["deviations"].reverse()
    data["safeguards"].reverse()
    (example / STUDY).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    loaded = load_study(example, STUDY)
    rows = rating_rows(loaded)
    assert {r.state for r in rows} == {"current"}
    assert [n.id for n in loaded.model.nodes] == ["N2", "N1"]
    assert not [f for f in _study(example) if f.level == "error"]


def test_invalid_references_give_actionable_findings(example):
    _edit(example, "safeguards: [SG3]", "safeguards: [SG3, SG9]")
    _edit(example, "refs: [PT-101]", "refs: [PT-109]")
    _edit(example, "interlock: I-01", "interlock: I-07")
    _edit(
        example,
        "members: [V-101, LT-102, PI-103, 80-P-101]",
        "members: [V-101, {tag: LT-102, sheet: P-09}, {tag: PI-103, sheet: P-01},"
        " {sheet: P-01, object: Nope-1}]",
    )
    _edit(example, "- id: S2", "- id: S1")
    _edit(
        example,
        "likelihood: C\n                  basis: Hot",
        "likelihood: E\n                  basis: Hot",
    )
    findings = validate_workspace(Workspace(example)).findings
    by_rule = {f.rule: f for f in findings if f.file == STUDY}
    assert {
        "cheme.hazop-unknown-ref",
        "cheme.hazop-unknown-tag",
        "cheme.hazop-unknown-interlock",
        "cheme.hazop-unknown-sheet",
        "cheme.hazop-not-on-sheet",
        "cheme.hazop-duplicate-id",
        "cheme.hazop-unknown-code",
    } <= set(by_rule)
    for finding in by_rule.values():
        assert finding.line and finding.hint
    assert "SG9" in by_rule["cheme.hazop-unknown-ref"].message
    assert "PT-109" in by_rule["cheme.hazop-unknown-tag"].message
    assert by_rule["cheme.hazop-not-on-sheet"].ids == ["node N1", "Nope-1"]
    (summary,) = study_summaries(Workspace(example), findings=findings)
    assert summary.state == "invalid"


def test_action_policy_and_states(example):
    _edit(example, "            actions: [A1]\n", "")
    _edit(example, "likelihood: B\n", "likelihood: C\n")  # S3 residual now high as well
    _edit(example, "status: open", "status: closed")
    rules = _rules(_study(example))
    assert "cheme.hazop-action-required" in rules  # S3 high, also residual, and no action
    messages = [f.message for f in _study(example) if f.rule == "cheme.hazop-action-state"]
    assert any("without a response" in m for m in messages)
    assert any("belongs to no scenario" in m for m in messages)


def test_unrated_and_incomplete_ratings_stay_explicit(example):
    _edit(example, 'severity: "2"', "severity: null")
    findings = _study(example)
    unresolved = [f.message for f in findings if f.rule == "cheme.hazop-unresolved"]
    assert any("S2 (initial, environment): no severity given" in m for m in unresolved)
    assert any("S4 has no initial risk rating" in m for m in unresolved)
    s2 = [r for r in rating_rows(load_study(example, STUDY)) if r.scenario == "S2"]
    assert s2[0].band is None and s2[0].state == "unresolved"  # never a default band


# -- rating, staleness, targeted writes -------------------------------------------------------


def test_a_rating_edit_makes_its_band_stale_and_a_targeted_rate_touches_nothing_else(example):
    before = (example / STUDY).read_text(encoding="utf-8")
    _edit(
        example,
        "likelihood: B\n                  basis: Operator",
        "likelihood: C\n                  basis: Operator",
    )
    stale = [f for f in _study(example) if f.rule == "cheme.hazop-band-stale"]
    assert [f.ids[0] for f in stale] == ["S3"]
    assert any("bands of S3" in f.message for f in review_needed(Workspace(example)))
    result = rate(Workspace(example), "H-01", "N2", write=False)
    assert [(r.scenario, r.which) for r in result.changes] == [("S3", "residual")]
    assert (example / STUDY).read_text(encoding="utf-8").count(
        "likelihood: C\n                  basis: Operator"
    ) == 1
    rate(Workspace(example), "H-01", "S3", write=True)
    after = (example / STUDY).read_text(encoding="utf-8")
    changed = [
        (a, b) for a, b in zip(before.splitlines(), after.splitlines(), strict=True) if a != b
    ]
    assert len(changed) == 2  # the edited likelihood and its band
    assert "value: high" in changed[1][1] and "value: medium" in changed[1][0]
    assert not [r for r in rating_rows(load_study(example, STUDY)) if r.state != "current"]


def test_a_matrix_edit_makes_every_band_stale(example):
    _edit(
        example,
        '"1": {A: low, B: low, C: low, D: medium}',
        '"1": {A: low, B: low, C: medium, D: medium}',
        "safety/risk-matrix.yaml",
    )
    assert {r.state for r in rating_rows(load_study(example, STUDY))} == {"stale"}
    result = rate(Workspace(example), "H-01", write=True)
    assert result.written
    s1 = [r for r in rating_rows(load_study(example, STUDY)) if r.scenario == "S1"]
    assert s1[0].band == "medium" and s1[0].state == "current"  # people 1/C now medium


def test_a_hand_edited_band_is_an_error(example):
    _edit(example, "band: {value: high", "band: {value: low")
    finding = next(f for f in _study(example) if f.rule == "cheme.hazop-band-edited")
    assert finding.level == "error" and finding.ids == ["S3", "people"]


def test_residual_risk_is_never_inferred_from_safeguards(example):
    # S1 lists two safeguards; S2 none: rating adds no residual rating to either.
    _edit(example, "safeguards: [SG1, SG2]", "safeguards: [SG1, SG2, SG3]")
    data_before = yaml.safe_load((example / STUDY).read_text(encoding="utf-8"))
    rate(Workspace(example), "H-01", write=True)
    data = yaml.safe_load((example / STUDY).read_text(encoding="utf-8"))
    s2 = data["nodes"][0]["deviations"][1]["scenarios"][0]
    assert "residual" not in s2["risk"]
    assert data == data_before


def test_flow_style_ratings_are_written_in_place(example):
    text = (example / STUDY).read_text(encoding="utf-8")
    block = re.search(
        r" {16}- category: environment\n(?: {18}.*\n)+?(?: {18}band: .*\n)", text
    ).group(0)
    flow = (
        '                - {category: environment, severity: "2", likelihood: D, basis: Spill, '
        "status: accepted}  # kept\n"
    )
    (example / STUDY).write_text(text.replace(block, flow), encoding="utf-8")
    rate(Workspace(example), "H-01", "S2", write=True)
    text = (example / STUDY).read_text(encoding="utf-8")
    assert re.search(r"status: accepted, band: \{value: medium, .*\}\}  # kept", text)
    assert not [r for r in rating_rows(load_study(example, STUDY)) if r.state != "current"]


def test_rate_exits_one_while_bands_are_missing(example, monkeypatch):
    monkeypatch.chdir(example)
    _edit(example, "band: {value: high", "bnd_removed: {value: high")
    assert runner.invoke(app, ["safety", "hazop", "rate", "H-01"]).exit_code == 2  # no load
    text = (example / STUDY).read_text(encoding="utf-8")
    removed = re.search(r"\n *bnd_removed: [^\n]*", text).group(0)
    (example / STUDY).write_text(text.replace(removed, ""), encoding="utf-8")
    out = runner.invoke(app, ["safety", "hazop", "rate", "H-01", "--target", "S3"])
    assert out.exit_code == 1 and "would write (missing)" in out.output
    out = runner.invoke(app, ["safety", "hazop", "rate", "H-01", "--target", "S3", "--write"])
    assert out.exit_code == 0, out.output
    assert runner.invoke(app, ["safety", "hazop", "rate", "H-01", "--target", "S9"]).exit_code == 2


# -- analysed inputs, review, gate ------------------------------------------------------------


def test_a_changed_analysed_input_asks_for_reassessment_an_unrelated_change_does_not(
    example, monkeypatch
):
    _edit(example, "service: Feed vessel", "service: Feed drum", "equipment/equipment-list.yaml")
    assert "cheme.hazop-input-changed" not in _rules(_study(example))
    _edit(
        example,
        "title: V-101 low-low level stops P-101",
        "title: V-101 low-low level trips P-101",
        "control/cause-effect.yaml",
    )
    changed = [f for f in _study(example) if f.rule == "cheme.hazop-input-changed"]
    assert [f.ids for f in changed] == [["control/cause-effect.yaml"]] and changed[0].line
    monkeypatch.chdir(example)
    out = runner.invoke(app, ["safety", "hazop", "stamp", "H-01", "--write"])
    assert "control/cause-effect.yaml: recorded (changed)" in out.output
    assert "cheme.hazop-input-changed" not in _rules(_study(example))


def _commit(root):
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "plant")


def test_review_record_draft_and_states(example):
    _commit(example)
    workspace = Workspace(example)
    (summary,) = study_summaries(workspace)
    text = review_draft(workspace, summary)
    assert "topic: hazop" in text and "scope: [safety/hazop/H-01/]" in text
    assert "relation: analyses" in text and "safety/risk-matrix.yaml" in text
    record = example / "reviews" / "2026-10-24-hazop-H-01.md"
    record.write_text(text, encoding="utf-8")
    review_findings = [
        f for f in validate_workspace(workspace).findings if f.file == workspace.relative(record)
    ]
    assert review_findings  # an empty reviewer does not pass as a review
    record.write_text(text.replace("reviewer: ''", "reviewer: A. Reviewer"), encoding="utf-8")
    git(example, "add", "-A")
    git(example, "commit", "-q", "-m", "review")
    (summary,) = study_summaries(workspace)
    assert summary.review.human and summary.review.current
    assert summary.state == "draft"  # a review does not complete an example study
    _edit(example, "Hold water at ambient", "Hold cold water at ambient")
    (summary,) = study_summaries(workspace)
    assert not summary.review.current


def _accept_everything(root: Path) -> None:
    """Make the example the plant's own, complete study (for the gate)."""
    _edit(root, "example: true\n", "")
    _edit(root, "example: true\n", "", "safety/risk-matrix.yaml")
    _edit(
        root,
        "status: proposed  #",
        "accepted_by: the team, procedure X\nstatus: accepted  #",
        "safety/risk-matrix.yaml",
    )
    text = (root / STUDY).read_text(encoding="utf-8")
    start = text.index("      - id: N2-RF")
    end = text.index("safeguards:\n  - id: SG1")
    (root / STUDY).write_text(text[:start] + text[end:], encoding="utf-8")


def test_the_hazop_gate(example):
    check = Check.model_validate(
        {
            "id": "h",
            "title": "HAZOP",
            "stage": "concept",
            "kind": "hazop",
            "require": ["assessed", "no-example", "actions-closed", "inputs-current"],
        }
    )
    findings = validate_workspace(Workspace(example)).findings
    problems = hazop_gate(Workspace(example), check, findings)
    assert any("not assessed" in p for p in problems)
    assert any("example" in p for p in problems)
    assert any("A1" in p for p in problems)
    _accept_everything(example)
    rate(Workspace(example), "H-01", write=True)
    _edit(
        example, "status: open", "status: closed\n    response: Recirculation line added (D-004)."
    )
    findings = validate_workspace(Workspace(example)).findings
    (summary,) = study_summaries(Workspace(example), findings=findings)
    assert summary.state == "assessed", [f.format() for f in summary.findings]
    assert hazop_gate(Workspace(example), check, findings) == []
    with pytest.raises(ValueError):
        Check.model_validate(
            {"id": "h", "title": "t", "stage": "s", "kind": "tea", "require": ["assessed"]}
        )


def test_the_domain_needs_neither_typer_nor_an_llm():
    code = (
        "import sys; import chemeascode.domains.safety.hazop;"
        "import chemeascode.domains.safety.hazop_report;"
        "bad = [m for m in ('typer', 'fastapi', 'anthropic', 'openai', 'langchain')"
        " if m in sys.modules];"
        "print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


# -- regressions from the review -------------------------------------------------------------------

BAND = {
    "value": "high",
    "provenance": "calculated",
    "source": "cheme safety hazop rate: m (f)",
    "fingerprint": "0123456789abcdef",
}


def _patch(text: str, loc: tuple, band) -> str:
    return write_bands(text, yaml.compose(text), {loc: band})


def test_block_bands_are_replaced_without_touching_the_next_lines():
    text = (
        "r:\n"
        "  - category: a\n"
        "    band:\n"
        "      value: low\n"
        "      source: x\n"
        "    basis: kept  # comment kept\n"
        "  - category: b\n"
        "    evidence:\n"
        "      - one\n"
        "    # a comment after the list\n"
        "  - category: c\n"
    )
    out = _patch(text, ("r", 0), BAND)
    assert "    basis: kept  # comment kept\n  - category: b\n" in out
    assert yaml.safe_load(out)["r"][0]["band"]["value"] == "high"
    out = _patch(out, ("r", 1), BAND)
    data = yaml.safe_load(out)
    assert data["r"][1]["band"]["value"] == "high" and "band" not in data["r"][2]
    assert "    # a comment after the list\n" in out
    removed = _patch(text, ("r", 0), None)
    assert yaml.safe_load(removed)["r"][0] == {"category": "a", "basis": "kept"}
    assert "basis: kept  # comment kept\n  - category: b\n" in removed


def test_flow_bands_first_key_and_trailing_commas():
    text = "a: [{x: 1}]\nr:\n  - {band: {value: low}, category: people, severity: '1'}\n"
    out = _patch(text, ("r", 0), None)
    assert out.startswith("a: [{x: 1}]\n") and yaml.safe_load(out)["r"][0] == {
        "category": "people",
        "severity": "1",
    }
    trailing = "r:\n  - {category: people, severity: '1',}\n"
    out = _patch(trailing, ("r", 0), BAND)
    assert yaml.safe_load(out)["r"][0]["band"]["value"] == "high"


def test_crlf_files_keep_their_line_endings(example):
    path = example / STUDY
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    text = path.read_bytes()
    _edit_bytes = text.replace(b"likelihood: B\r\n", b"likelihood: C\r\n")
    path.write_bytes(_edit_bytes)
    rate(Workspace(example), "H-01", "S3", write=True)
    after = path.read_bytes()
    assert b"\r\n" in after and b"\n" not in after.replace(b"\r\n", b"")


def test_an_empty_study_is_a_draft_even_with_a_real_matrix(example, monkeypatch):
    _edit(example, "example: true\n", "", "safety/risk-matrix.yaml")
    monkeypatch.chdir(example)
    out = runner.invoke(app, ["safety", "hazop", "init", "H-02", "--input", "pid/P-01.xml"])
    assert out.exit_code == 0, out.output
    (summary,) = study_summaries(Workspace(example), "H-02")
    assert summary.state == "draft"
    keys = {f.key for f in summary.findings if f.rule == "cheme.hazop-unresolved"}
    assert {"scope", "nodes", "assessment_basis"} <= keys


def _record(root: Path, name: str, topic: str, rows: str = "") -> None:
    head = git(root, "rev-parse", "HEAD").strip()
    (root / "reviews" / name).write_text(
        f"---\ntopic: {topic}\nreviewed_commit: {head}\nscope: [safety/]\n"
        "reviewer: A. Reviewer\nreviewer_kind: human\n---\n\n## Findings\n\n"
        "| id | finding | severity | status |\n|---|---|---|---|\n" + rows,
        encoding="utf-8",
    )
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", name)


def test_only_a_hazop_review_without_open_blocking_findings_counts(example):
    _commit(example)
    _record(example, "2026-10-24-layout.md", "layout")
    (summary,) = study_summaries(Workspace(example))
    assert summary.review.record is None
    stem = "2026-10-25-hazop"
    _record(example, f"{stem}.md", "hazop", f"| {stem}#1 | S4 not assessed | high | open |\n")
    (summary,) = study_summaries(Workspace(example))
    assert not summary.review.current and "open blocking" in summary.review.detail


def test_the_hazop_review_status_blocks_on_the_same_findings_as_sign_off(example):
    """A finding carried forward without a severity, or with a status outside the
    vocabulary, still blocks, as it does for sign-off and coverage."""
    from chemeascode.foundation.reviews import blocking_ids, load_records, open_blocking

    _commit(example)
    first = "2026-10-24-hazop"
    _record(example, f"{first}.md", "hazop", f"| {first}#1 | S4 not assessed | high | open |\n")
    second = "2026-10-25-hazop"
    _record(
        example,
        f"{second}.md",
        "hazop",
        f"| {second}#1 | S5 wording | low | in progress |\n\n## Previous findings\n\n"
        "| id | finding | status |\n|---|---|---|\n"
        f"| {first}#1 | S4 not assessed | in progress |\n",
    )
    (summary,) = study_summaries(Workspace(example))
    assert (
        not summary.review.current and f"open blocking findings {first}#1" in summary.review.detail
    )
    records = load_records(Workspace(example))
    assert (
        {r.id for r in open_blocking(records)} == blocking_ids(records, records) == {f"{first}#1"}
    )


def test_an_open_blocking_finding_with_a_malformed_id_still_blocks(example):
    """A row whose id is not <record>#<n> cannot be followed, so it
    blocks."""
    _commit(example)
    _record(example, "2026-10-25-hazop.md", "hazop", "| H-1 | S4 not assessed | high | open |\n")
    (summary,) = study_summaries(Workspace(example))
    assert not summary.review.current and "open blocking findings H-1" in summary.review.detail


def test_a_git_failure_keeps_the_hazop_review_from_being_current(example, monkeypatch):
    from chemeascode.foundation import gitinfo

    _commit(example)
    _record(example, "2026-10-25-hazop.md", "hazop")
    (summary,) = study_summaries(Workspace(example))
    assert summary.review.current
    monkeypatch.setattr(gitinfo, "changed_since", lambda *args: None)
    (summary,) = study_summaries(Workspace(example))
    assert not summary.review.current and "cannot tell" in summary.review.detail


def test_an_incomplete_residual_rating_does_not_hide_the_initial_band(example):
    _edit(example, "            actions: [A1]\n", "")
    _edit(example, "likelihood: B\n", "likelihood: null\n")
    assert "cheme.hazop-action-required" in _rules(_study(example))


def test_unquoted_no_is_the_guide_word_and_numeric_interlocks_are_ids(example):
    _edit(example, 'guide_word: "no"', "guide_word: no")
    loaded = load_study(example, STUDY)
    assert loaded.model is not None and loaded.model.nodes[1].deviations[0].guide_word == "no"
    _edit(example, "interlock: I-01", "interlock: 101")
    assert load_study(example, STUDY).model.safeguards[1].interlock == "101"


def test_a_band_another_tool_wrote_is_an_error_and_is_left_alone(example):
    _edit(example, "source: 'cheme safety hazop rate: example-4x4", "source: 'my tool: example-4x4")
    findings = [f for f in _study(example) if f.rule == "cheme.hazop-band-edited"]
    assert findings and "not written by" in findings[0].message
    before = (example / STUDY).read_text(encoding="utf-8")
    result = rate(Workspace(example), "H-01", write=True)
    assert (example / STUDY).read_text(encoding="utf-8") == before and result.findings


def test_dump_keeps_the_band_provenance():
    text = dump_study(load_study(EXAMPLE, STUDY).model)
    assert "provenance: calculated" in text


# -- follow-ups: tampered bands, directory inputs, validating some files ----------------------


def test_a_band_whose_fingerprint_does_not_match_its_inputs_is_an_error(example):
    text = (example / STUDY).read_text(encoding="utf-8")
    fingerprint = re.search(r"value: high, [^\n]*fingerprint: ([0-9a-f]+)", text).group(1)
    _edit(example, f"fingerprint: {fingerprint}", "fingerprint: deadbeefdeadbeef")
    finding = next(f for f in _study(example) if f.rule == "cheme.hazop-band-edited")
    assert finding.level == "error" and "inputs it records" in finding.message
    assert finding.ids == ["S3", "people"]


def test_a_stale_band_says_what_it_was_looked_up_from(example):
    _edit(example, "likelihood: B\n", "likelihood: C\n")
    stale = next(f for f in _study(example) if f.rule == "cheme.hazop-band-stale")
    assert "from severity 3, likelihood B" in stale.message


def test_a_band_without_inputs_is_still_read(example):
    # Bands written before `inputs` existed: checked by the fingerprint alone.
    text = (example / STUDY).read_text(encoding="utf-8")
    (example / STUDY).write_text(re.sub(r", inputs: \{[^}]*\}", "", text), encoding="utf-8")
    assert {r.state for r in rating_rows(load_study(example, STUDY))} == {"current"}
    assert not [f for f in _study(example) if f.level == "error"]


def test_a_changed_category_makes_the_band_stale_and_rate_rewrites_it(example):
    # The example's bands record no category in `inputs` (written before it did): the band
    # is still known as rate's own, looked up in the category whose fingerprint matches.
    s1_people = '- category: people\n                  severity: "1"'
    _edit(example, s1_people, s1_people.replace("people", "environment"))
    findings = [f for f in _study(example) if f.ids[:1] == ["S1"]]
    assert "cheme.hazop-band-edited" not in _rules(findings)
    stale = next(f for f in findings if f.rule == "cheme.hazop-band-stale")
    assert stale.level == "warning" and stale.ids == ["S1", "environment"]
    assert "from category people" in stale.message
    result = rate(Workspace(example), "H-01", "S1", write=True)
    assert [(r.which, r.rating.category) for r in result.changes] == [("initial", "environment")]
    assert "inputs: {matrix: b6caa11838fe6bc7, category: environment," in (
        example / STUDY
    ).read_text(encoding="utf-8")
    assert {r.state for r in rating_rows(load_study(example, STUDY))} == {"current"}
    # Now that the category is recorded, changing it back is stale again, never edited ...
    _edit(example, "- category: environment", "- category: people")
    assert [f.rule for f in _study(example) if f.ids[:1] == ["S1"]] == ["cheme.hazop-band-stale"]
    # ... and a hand-edited fingerprint with a recorded category still is an error.
    rate(Workspace(example), "H-01", "S1", write=True)
    assert "category: people, severity: '1'" in (example / STUDY).read_text(encoding="utf-8")
    band = next(r for r in rating_rows(load_study(example, STUDY)) if r.scenario == "S1")
    _edit(example, f"fingerprint: {band.fingerprint}", "fingerprint: deadbeefdeadbeef")
    edited = next(f for f in _study(example) if f.rule == "cheme.hazop-band-edited")
    assert edited.ids == ["S1", "people"] and "inputs it records" in edited.message


def test_a_directory_is_an_analysed_input_at_its_commit(example, monkeypatch):
    _commit(example)
    monkeypatch.chdir(example)
    out = runner.invoke(app, ["safety", "hazop", "stamp", "H-01", "--input", "control/", "--write"])
    assert out.exit_code == 0, out.output
    head = git(example, "rev-parse", "HEAD").strip()
    assert f"control: recorded (new) {head}" in out.output
    git(example, "commit", "-qam", "stamp")
    out = runner.invoke(app, ["safety", "hazop", "stamp", "H-01"])
    assert "control: unchanged" in out.output  # a later commit is no change of the directory
    assert "cheme.hazop-input-changed" not in _rules(_study(example))
    _edit(example, "condition: LALL", "condition: LLL", "control/cause-effect.yaml")
    changed = [f.ids for f in _study(example) if f.rule == "cheme.hazop-input-changed"]
    assert ["control"] in changed and ["control/cause-effect.yaml"] in changed
    out = runner.invoke(app, ["safety", "hazop", "stamp", "H-01", "--write"])
    assert out.exit_code == 2 and "uncommitted changes" in out.output
    out = runner.invoke(app, ["safety", "hazop", "init", "H-03", "--input", "pid/"])
    assert out.exit_code == 0, out.output
    assert load_study(example, "safety/hazop/H-03/study.yaml").model.analysed[0].path == "pid"


def test_validating_only_the_study_checks_it_without_the_plant(example):
    _edit(example, "safeguards: [SG3]", "safeguards: [SG3, SG9]")
    _edit(example, "refs: [PT-101]", "refs: [PT-109]")
    report = validate_workspace(Workspace(example), only=[example / STUDY])
    rules = {f.rule for f in report.findings}
    assert "cheme.hazop-unknown-ref" in rules and "cheme.hazop-unknown-tag" not in rules
    assert any("HAZOP references" in s for s in report.compared["skipped"])
    other = validate_workspace(Workspace(example), only=[example / "plant.yaml"])
    assert not [f for f in other.findings if f.rule.startswith("cheme.hazop")]
    matrix_only = validate_workspace(Workspace(example), only=[example / "safety/risk-matrix.yaml"])
    assert "cheme.hazop-unknown-ref" in {f.rule for f in matrix_only.findings}


def test_a_proposed_matrix_keeps_the_study_a_draft_and_accepting_it_changes_no_band(example):
    _edit(example, "example: true\n", "", "safety/risk-matrix.yaml")
    rate(Workspace(example), "H-01", write=True)  # the plant's own matrix now
    keys = {f.key for f in _study(example) if f.rule == "cheme.hazop-unresolved"}
    assert "matrix-proposed" in keys
    _edit(example, "status: proposed  #", "status: accepted  #", "safety/risk-matrix.yaml")
    keys = {f.key for f in _study(example) if f.rule == "cheme.hazop-unresolved"}
    assert "matrix-proposed" not in keys
    assert {r.state for r in rating_rows(load_study(example, STUDY))} == {"current"}
