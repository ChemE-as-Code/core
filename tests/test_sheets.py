"""Sheets and title blocks: sheet new / sheet meta (pre-release issue 10), planned sheets
(pre-release issue 17), title-block rules (pre-release issue 19)."""

import json
from pathlib import Path

import pytest
import yaml
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.fmt import format_bytes
from chemeascode.domains.piping.sheets import (
    TEMPLATE_DIAGRAM_NAMES,
    TEMPLATE_METADATA,
    TEMPLATE_METADATA_KEPT,
    TEMPLATE_MODEL_NAMES,
    TEMPLATE_MODEL_URIS,
    read_title_block,
)
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from chemeascode.project.validate import validate_workspace

from .conftest import REFERENCE
from .test_snippets import SKILL, build_snippets

runner = CliRunner()
EMPTY_SHEET = SKILL / "snippets" / "empty-sheet.xml"


def _invoke(*args: str):
    return runner.invoke(app, list(args))


def _repo(tmp_path: Path, monkeypatch, project: bool = True) -> Path:
    root = tmp_path / "plant"
    assert _invoke("init", str(root), "--name", "ASU-1").exit_code == 0
    if project:
        text = (root / "plant.yaml").read_text()
        text = text.replace(
            "units: SI\n",
            "units: SI\nproject: {number: '24-017', client: Air Co, site: Leuna, revision: '0'}\n",
        )
        (root / "plant.yaml").write_text(text)
    monkeypatch.chdir(root)
    return root


def _findings(root: Path) -> list:
    return validate_workspace(Workspace(root)).findings


def _root(path: Path) -> etree._Element:
    return etree.fromstring(path.read_bytes())


def _texts(root: etree._Element) -> dict[str, str]:
    """Cached title-block text by the MetaData attribute its template shows."""
    found = {}
    label = root.find(".//Object[@type='Core/Diagram.Label']")
    for text in label.iter("Object"):
        attribute = text.findtext(".//Data[@property='AttributeName']/String")
        if text.get("type") == "Core/Diagram.Text" and attribute:
            found[attribute] = text.findtext("Data[@property='Text']/String") or ""
    return found


# ---------------------------------------------------------------------------
# The template sheet and the defaults constant
# ---------------------------------------------------------------------------


def _reference_metadata() -> dict[str, list[str]]:
    root = etree.fromstring(format_bytes(REFERENCE.read_bytes())[0])
    return {p: v for p, (v, _) in read_title_block(root).values.items()}


def test_template_defaults_are_in_sync_with_the_reference():
    """Every sample value of pyDEXPI's title block is a template default, or kept on purpose."""
    reference = _reference_metadata()
    for prop, values in reference.items():
        shown = {v for v in values if v}
        if not shown or prop in TEMPLATE_METADATA_KEPT:
            continue
        assert TEMPLATE_METADATA.get(prop) == shown, prop
    assert set(TEMPLATE_METADATA) <= set(reference)
    root = etree.fromstring(REFERENCE.read_bytes())
    block = read_title_block(root)
    assert block.model_name in TEMPLATE_MODEL_NAMES
    assert block.model_uri in TEMPLATE_MODEL_URIS
    assert block.diagram_name in TEMPLATE_DIAGRAM_NAMES


def test_template_sheet_has_no_sample_title_block():
    """#10: no fake approval, people, company, site, project or 2016 dates."""
    text = EMPTY_SHEET.read_text(encoding="utf-8")
    for sample in (
        "A. P. Prover",
        "A. Creator",
        "C. Hecker",
        "Oil &amp; Gas",
        "Dexpi City",
        "P3.1415",
        "DEXPI Example C01",
        ">approved<",
        "2016-",
    ):
        assert sample not in text, sample
    block = read_title_block(_root(EMPTY_SHEET))
    for prop, (values, _) in block.values.items():
        assert not set(values) & TEMPLATE_METADATA.get(prop, frozenset()), prop
    assert block.value("ApprovalDescription") == "for review"
    assert not block.value("ApproverName") and not block.value("CheckerName")
    # Its placeholders are template defaults, so a raw copy is reported.
    assert block.model_name in TEMPLATE_MODEL_NAMES
    assert block.model_uri in TEMPLATE_MODEL_URIS
    assert block.diagram_name in TEMPLATE_DIAGRAM_NAMES
    assert {"RevisionNumber", "ApprovalDescription"} <= set(_texts(_root(EMPTY_SHEET)))


def test_sample_title_block_gets_template_metadata_warnings(tmp_path, monkeypatch):
    """#19: a frame with pyDEXPI's sample title block (what the 0.3 snippet was)."""
    root = _repo(tmp_path, monkeypatch, project=False)
    formatted = etree.fromstring(format_bytes(REFERENCE.read_bytes())[0])
    frame = build_snippets.skeleton(formatted)
    (root / "pid" / "P-01.xml").write_bytes(
        format_bytes(etree.tostring(frame, xml_declaration=True, encoding="UTF-8"))[0]
    )
    named = {f.ids[0] for f in _findings(root) if f.rule == "cheme.template-metadata"}
    assert {
        "ApproverName",
        "CreatorName",
        "CheckerName",
        "ProjectNumber",
        "EnterpriseName",
        "SiteName",
        "ModelName",
        "ModelUri",
        "DiagramName",
    } <= named
    found = [f for f in _findings(root) if f.rule == "cheme.template-metadata"]
    assert all(f.line and f.hint for f in found)


def test_reference_sheet_warns_on_example_model_and_diagram_name(plant: Path):
    """#19 on the ASU sheets: Model name="example" and DEXPI Example C01 are reported."""
    named = {f.ids[0] for f in _findings(plant) if f.rule == "cheme.template-metadata"}
    assert {"ModelName", "ModelUri", "DiagramName"} <= named


# ---------------------------------------------------------------------------
# sheet new / sheet meta
# ---------------------------------------------------------------------------


def test_sheet_new_writes_a_clean_sheet_and_lists_it(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    result = _invoke("sheet", "new", "P-05", "--title", "X")
    assert result.exit_code == 0, result.output
    path = root / "pid" / "P-05.xml"
    assert path.is_file()
    config = yaml.safe_load((root / "plant.yaml").read_text())
    assert config["sheets"] == [{"id": "P-05", "file": "pid/P-05.xml", "title": "X"}]

    sheet = _root(path)
    block = read_title_block(sheet)
    assert (block.model_name, block.diagram_name) == ("ASU-1", "P-05")
    assert block.value("DrawingNumber") == "24-017-P-05"
    assert block.value("RevisionNumber") == "0"
    texts = _texts(sheet)
    assert texts["DrawingName"] == "X"
    assert texts["ProjectNumber"] == "24-017"
    assert texts["EnterpriseName"] == "Air Co"
    assert texts["SiteName"] == "Leuna"
    assert texts["ApprovalDescription"] == "for review"
    assert texts["ApproverName"] == texts["ApprovalDateRepresentation"] == ""
    assert texts["CheckerName"] == ""

    result = _invoke("validate", "--fail-on", "warning")
    assert result.exit_code == 0, result.output
    assert _invoke("fmt", "--check").exit_code == 0
    assert _invoke("sheet", "new", "P-05").exit_code == 2  # exists


def test_sheet_meta_sets_metadata_and_title_block(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    assert _invoke("sheet", "new", "P-05", "--title", "X").exit_code == 0
    result = _invoke("sheet", "meta", "P-05", "Revision=B", "Status=issued for design")
    assert result.exit_code == 0, result.output
    assert "RevisionNumber = 'B'" in result.output
    sheet = _root(root / "pid" / "P-05.xml")
    assert read_title_block(sheet).value("RevisionNumber") == "B"
    assert _texts(sheet)["RevisionNumber"] == "B"
    assert _texts(sheet)["ApprovalDescription"] == "issued for design"
    assert _invoke("fmt", "--check").exit_code == 0
    assert _invoke("render", "pid/P-05.xml").exit_code == 0
    svg = (root / "build" / "P-05.svg").read_text()
    assert ">B</text>" in svg and ">issued for design</text>" in svg
    shown = _invoke("sheet", "meta", "P-05")
    assert "RevisionNumber: B" in shown.output
    bad = _invoke("sheet", "meta", "P-05", "Colour=red")
    assert bad.exit_code == 2 and "unknown title-block key" in bad.output


def test_sheet_new_drafts_a_planned_sheet(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    text = (
        (root / "plant.yaml")
        .read_text()
        .replace(
            "sheets: []",
            "sheets:\n  - {id: P-01, file: pid/P-01.xml, title: Feed, status: planned}\n"
            "  - {id: P-02, title: Products, status: planned}",
        )
    )
    (root / "plant.yaml").write_text(text)
    result = _invoke("sheet", "new", "P-02")
    assert result.exit_code == 0, result.output
    config = Workspace(root).config()
    assert [(s.id, s.status) for s in config.sheets] == [("P-01", "planned"), ("P-02", "drafted")]
    assert _texts(_root(root / "pid" / "P-02.xml"))["DrawingName"] == "Products"
    assert "# P&ID sheets" in (root / "plant.yaml").read_text()  # comments kept


def test_sheet_new_keeps_existing_pid_files_listed(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    assert _invoke("sheet", "new", "P-01", "--title", "A").exit_code == 0
    # sheets: [] with a file already in pid/ (the glob default) -> both get listed.
    text = (root / "plant.yaml").read_text()
    start = text.index("sheets:")
    (root / "plant.yaml").write_text(text[:start] + "sheets: []\n")
    assert _invoke("sheet", "new", "P-02", "--title", "B").exit_code == 0
    ids = [s.id for s in Workspace(root).config().sheets]
    assert ids == ["P-01", "P-02"]


# ---------------------------------------------------------------------------
# Title-block approval and sheet rules
# ---------------------------------------------------------------------------


def _rules(root: Path, rule: str) -> list:
    return [f for f in _findings(root) if f.rule == rule]


def test_approval_needs_a_sign_off(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    assert _invoke("sheet", "new", "P-01", "--title", "A").exit_code == 0
    assert not _rules(root, "cheme.titleblock-approval")
    assert _invoke("sheet", "meta", "P-01", "Approver=J. Smith").exit_code == 0
    found = _rules(root, "cheme.titleblock-approval")
    assert len(found) == 1 and found[0].ids == ["ApproverName"] and found[0].line

    status = root / "checks" / "status.json"
    status.write_text(
        json.dumps({"checks": [{"id": "x", "title": "x", "stage": "concept", "status": "fail"}]})
    )
    assert _rules(root, "cheme.titleblock-approval")
    status.write_text(
        json.dumps({"checks": [{"id": "x", "title": "x", "stage": "concept", "status": "pass"}]})
    )
    assert not _rules(root, "cheme.titleblock-approval")
    status.write_text(json.dumps({"stages": {"concept": {"checks": []}}}))
    assert not _rules(root, "cheme.titleblock-approval")


def test_checker_needs_a_review_record(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    assert _invoke("sheet", "new", "P-01", "--title", "A").exit_code == 0
    assert _invoke("sheet", "meta", "P-01", "Checker=C. Reviewer").exit_code == 0
    assert [f.ids for f in _rules(root, "cheme.titleblock-approval")] == [["CheckerName"]]
    (root / "reviews" / "2026-10-18-design-review.md").write_text("# Review\n")
    assert not _rules(root, "cheme.titleblock-approval")


def test_titleblock_sheet_number_and_title(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    assert _invoke("sheet", "new", "P-01", "--title", "Feed and reaction").exit_code == 0
    assert not _rules(root, "cheme.titleblock-sheet")
    assert _invoke("sheet", "meta", "P-01", "SheetNumber=1").exit_code == 0
    assert not _rules(root, "cheme.titleblock-sheet")  # sheet 1 is P-01
    assert _invoke("sheet", "meta", "P-01", "SheetNumber=7", "Title=Utilities").exit_code == 0
    assert {f.ids[0] for f in _rules(root, "cheme.titleblock-sheet")} == {
        "SheetNumber",
        "DrawingName",
    }


# ---------------------------------------------------------------------------
# Planned sheets and sheet-scoped not-on-pid
# ---------------------------------------------------------------------------


def _lists(root: Path) -> None:
    (root / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n"
        "  - {tag: P-101, type: CentrifugalPump, sheet: P-01}\n"
        "  - {tag: T-301, type: Tank, sheet: P-03}\n"
        "  - {tag: E-999, type: PlateHeatExchanger}\n"
    )
    (root / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: L-301, from: T-301, to: P-101, sheet: P-03}\n"
    )
    (root / "control" / "instrument-list.yaml").write_text(
        "instruments:\n  - {tag: LI-301, sheet: P-03}\n  - {tag: PI-101, sheet: P-01}\n"
    )


def _sheets(root: Path, *entries: str) -> None:
    text = (root / "plant.yaml").read_text()
    (root / "plant.yaml").write_text(
        text.replace("sheets: []", "sheets:\n" + "".join(f"  - {e}\n" for e in entries))
    )


def test_planned_sheets_at_concept_stage_validate_clean(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _lists(root)
    _sheets(root, *(f"{{id: P-0{n}, status: planned}}" for n in range(1, 5)))
    report = validate_workspace(Workspace(root))
    assert not [f for f in report.findings if f.level != "info"], report.findings
    planned = [f for f in report.findings if f.rule == "cheme.sheet-planned"]
    assert len(planned) == 4 and all(f.file == "plant.yaml" and f.line for f in planned)
    assert report.compared["planned"] == ["P-01", "P-02", "P-03", "P-04"]
    assert _invoke("validate", "--fail-on", "warning").exit_code == 0
    assert _invoke("fmt", "--check").exit_code == 0


def test_not_on_pid_is_scoped_to_the_sheet(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _lists(root)
    _sheets(root, "{id: P-01, status: planned}", "{id: P-03, status: planned}")
    assert _invoke("sheet", "new", "P-01", "--title", "Pumps").exit_code == 0
    findings = _findings(root)
    warned = {i for f in findings if f.level == "warning" for i in f.ids}
    held = {i for f in findings if f.level == "info" and "not-on-pid" in f.rule for i in f.ids}
    assert {"P-101", "PI-101"} <= warned
    assert {"T-301", "L-301", "LI-301", "E-999"} <= held  # P-03 planned; no sheet at concept
    assert not {"T-301", "L-301", "LI-301", "E-999"} & warned

    # After the first stage an item without a sheet is a warning once every sheet is read.
    text = (root / "plant.yaml").read_text().replace("stage: concept", "stage: basic")
    (root / "plant.yaml").write_text(text)
    assert _invoke("sheet", "new", "P-03", "--title", "Tanks").exit_code == 0
    warned = {i for f in _findings(root) if f.level == "warning" for i in f.ids}
    assert {"E-999", "T-301", "L-301", "LI-301"} <= warned


def test_planned_sheet_with_a_file_is_validated(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _sheets(root, "{id: P-01, status: planned}")
    (root / "pid" / "P-01.xml").write_bytes(EMPTY_SHEET.read_bytes())
    findings = _findings(root)
    assert not [f for f in findings if f.rule == "cheme.sheet-planned"]
    assert [f for f in findings if f.rule == "cheme.template-metadata"]


def test_missing_drafted_sheet_is_an_error_with_a_hint(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _sheets(root, "{id: P-01}")
    found = [f for f in _findings(root) if f.rule == "cheme.missing-sheet"]
    assert len(found) == 1 and found[0].level == "error"
    assert "sheet new P-01" in found[0].hint and "planned" in found[0].hint


@pytest.mark.parametrize("as_json", [False, True])
def test_validate_ignore_and_only(plant: Path, monkeypatch, as_json: bool):
    monkeypatch.chdir(plant)
    (plant / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n  - {tag: X-1, type: Tank, sheet: P-01}\n"
    )
    extra = ["--json"] if as_json else []

    def rules(*args: str) -> set[str]:
        result = _invoke("validate", *extra, *args)
        if as_json:
            return {f["rule"] for f in json.loads(result.stdout)["findings"]}
        return {
            words[2]
            for words in (line.split() for line in result.output.splitlines())
            if len(words) > 2 and words[1] in ("error", "warning", "info")
        }

    everything = rules()
    assert "cheme.equipment-not-on-pid" in everything
    ignored = rules("--ignore", "cheme.equipment-not-on-pid")
    assert ignored == everything - {"cheme.equipment-not-on-pid"}
    assert rules("--only", "cheme.equipment-not-on-pid") == {"cheme.equipment-not-on-pid"}
    assert rules("--only", "cheme.template-*,cheme.equipment-*") <= {
        "cheme.template-metadata",
        "cheme.equipment-not-on-pid",
        "cheme.equipment-not-listed",
    }
    # --fail-on honours the filter.
    only = ["--only", "cheme.equipment-not-on-pid", "--fail-on", "warning"]
    assert _invoke("validate", *extra, *only).exit_code == 1
    assert _invoke("validate", *extra, "--only", "no.such-rule", "--fail-on", "info").exit_code == 0


def test_schema_plant_documents_status_and_project():
    result = _invoke("schema", "plant")
    schema = json.loads(result.stdout)
    sheet = schema["$defs"]["Sheet"]
    assert sheet["properties"]["status"]["enum"] == ["planned", "drafted"]
    assert "planned" in sheet["description"]
    assert {"number", "client", "site", "revision"} <= set(schema["$defs"]["Project"]["properties"])


# ---------------------------------------------------------------------------
# Review fixes
# ---------------------------------------------------------------------------


def test_planned_sheet_does_not_hide_items_without_a_sheet_after_the_first_stage(
    tmp_path, monkeypatch
):
    root = _repo(tmp_path, monkeypatch)
    text = (root / "plant.yaml").read_text().replace("stage: concept", "stage: basic")
    (root / "plant.yaml").write_text(text)
    _sheets(root, "{id: P-01}", "{id: P-02, status: planned}", "{id: P-03}")
    for sheet in ("P-01", "P-03"):
        (root / "pid" / f"{sheet}.xml").write_bytes(EMPTY_SHEET.read_bytes())
    (root / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n  - {tag: T-301, type: Tank}\n  - {tag: T-302, type: Tank, sheet: P-02}\n"
    )
    findings = _findings(root)
    warned = {i for f in findings if f.level == "warning" for i in f.ids}
    held = {i for f in findings if f.level == "info" and "not-on-pid" in f.rule for i in f.ids}
    assert "T-301" in warned and "T-301" not in held
    assert "T-302" in held and "T-302" not in warned
    assert _invoke("validate", "--fail-on", "warning").exit_code == 1


@pytest.mark.parametrize(
    "sheets, args, message",
    [
        ("sheets: [{id: P-01, file: pid/P-01.xml, status: planned}]", ["P-02"], "flow style"),
        (
            "sheets:\n  - {id: P-01, file: pid/P-01.xml, status: planned}",
            ["P-01", "--file", "pid/other.xml"],
            "not pid/other.xml",
        ),
    ],
)
def test_sheet_new_refused_by_plant_yaml_writes_no_file(
    tmp_path, monkeypatch, sheets, args, message
):
    root = _repo(tmp_path, monkeypatch)
    text = (root / "plant.yaml").read_text().replace("sheets: []", sheets)
    (root / "plant.yaml").write_text(text)
    before = sorted(p.name for p in (root / "pid").iterdir())
    result = _invoke("sheet", "new", *args)
    assert result.exit_code == 2 and message in result.output
    assert sorted(p.name for p in (root / "pid").iterdir()) == before
    assert (root / "plant.yaml").read_text() == text


def test_sheet_new_counts_itself_in_total_number_of_sheets(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    _sheets(root, "{id: P-01, status: planned}", "{id: P-02, status: planned}")
    assert _invoke("sheet", "new", "P-03", "--title", "Storage").exit_code == 0
    result = _invoke("sheet", "meta", "P-03")
    assert "TotalNumberOfSheets: 3" in result.output
    # A planned entry drafted keeps the count.
    assert _invoke("sheet", "new", "P-01", "--title", "Feed").exit_code == 0
    assert "TotalNumberOfSheets: 3" in _invoke("sheet", "meta", "P-01").output


def test_sheet_new_counts_listed_pid_files(tmp_path, monkeypatch):
    root = _repo(tmp_path, monkeypatch)
    (root / "pid" / "P-01.xml").write_bytes(EMPTY_SHEET.read_bytes())
    assert _invoke("sheet", "new", "P-02").exit_code == 0
    assert "TotalNumberOfSheets: 2" in _invoke("sheet", "meta", "P-02").output


@pytest.mark.parametrize("command", [["sheet", "new", "P-01"], ["sheet", "meta", "P-01"]])
def test_sheet_commands_report_an_invalid_plant_yaml_in_one_line(tmp_path, monkeypatch, command):
    root = _repo(tmp_path, monkeypatch)
    (root / "plant.yaml").write_text((root / "plant.yaml").read_text() + "bogus_key: 1\n")
    result = _invoke(*command)
    assert result.exit_code == 2
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "plant.yaml:" in result.output and "Traceback" not in result.output
    assert not (root / "pid" / "P-01.xml").exists()


def test_render_rev_skips_planned_sheets(tmp_path, monkeypatch):
    from .conftest import git

    root = _repo(tmp_path, monkeypatch)
    _sheets(root, *(f"{{id: P-0{n}, status: planned}}" for n in range(1, 5)))
    assert _invoke("sheet", "new", "P-01", "--title", "Feed").exit_code == 0
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "P-01")
    result = _invoke("render", "--rev", "HEAD")
    assert result.exit_code == 0, result.output
    assert "not in revision" not in result.output
    assert (root / "build" / "P-01@HEAD.svg").is_file()
    # A drafted sheet absent at the revision still fails.
    assert _invoke("sheet", "new", "P-02", "--title", "Columns").exit_code == 0
    result = _invoke("render", "--rev", "HEAD")
    assert result.exit_code == 1 and "pid/P-02.xml: not in revision HEAD" in result.output
