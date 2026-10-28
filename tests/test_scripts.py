"""cheme run (pre-release issue 6), the authoring API (pre-release issue 13), generated sheets and
regen (pre-release issue 16)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from chemeascode.templates.install import bundled_skills, init, template_dir
from tests.conftest import git

runner = CliRunner()
TEMPLATE = Path(str(template_dir()))
EMPTY = Path(str(bundled_skills()["dexpi-xml"])) / "snippets" / "empty-sheet.xml"
#: A local clone of the process-library repository. Since the move into the library the ASU is in
#: its subfolder ``processes/asu-1``; older revisions have the plant at the repository's top.
ASU = Path(os.environ.get("CHEME_PROCESS_LIBRARY", "~/Developer/repos/plantcode-asu")).expanduser()
ASU_FOLDER = "processes/asu-1"


def plant_root(checkout: Path) -> Path:
    """The ASU plant root in a checkout of any revision: the top, or ``processes/asu-1``."""
    return checkout if (checkout / "plant.yaml").is_file() else checkout / ASU_FOLDER


@pytest.fixture
def fresh(tmp_path: Path, monkeypatch) -> Path:
    """A fresh `cheme init` repository in git, cwd at its root."""
    root = tmp_path / "plant"
    init(root, "Test plant")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    monkeypatch.chdir(root)
    return root


def invoke(*args: str):
    return runner.invoke(app, list(args))


# -- cheme run (pre-release issue 6) ---------------------------------------------------------------


def test_run_loads_and_saves_the_empty_sheet_with_pydexpi(fresh: Path):
    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    (fresh / "scripts" / "x.py").write_text(
        "import sys\n"
        "import chemeascode\n"
        "from pydexpi.loaders.public import load_xml_file\n"
        "from pydexpi.loaders.xml_serializer import DexpiXmlSerializer\n"
        "model = load_xml_file(sys.argv[1])\n"
        "DexpiXmlSerializer().save(model, 'pid', 'P-02')\n"
        "print('saved', model.conceptualModel.metaData is not None)\n"
    )
    result = invoke("run", "scripts/x.py", "pid/P-01.xml")
    assert result.exit_code == 0, result.output
    assert "saved True" in result.output
    assert (fresh / "pid" / "P-02.xml").is_file()
    assert invoke("fmt", "pid/P-02.xml").exit_code == 0
    assert invoke("validate", "pid/P-02.xml").exit_code == 0


def test_run_passes_arguments_and_exit_code_and_resolves_against_the_root(fresh: Path, monkeypatch):
    (fresh / "scripts" / "x.py").write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        "Path('out.txt').write_text(' '.join(sys.argv[1:]) + '|' + os.getcwd())\n"
        "sys.exit(int(sys.argv[1]))\n"
    )
    (fresh / "pid" / "deep").mkdir(parents=True)
    monkeypatch.chdir(fresh / "pid" / "deep")
    result = invoke("run", "scripts/x.py", "3", "--flag", "-v")
    assert result.exit_code == 3
    args, cwd = (fresh / "out.txt").read_text().split("|")
    assert args == "3 --flag -v"
    assert Path(cwd).resolve() == fresh.resolve()
    assert Path.cwd().resolve() == (fresh / "pid" / "deep").resolve()  # restored


def test_run_reports_an_exception_with_exit_1_and_a_missing_script_with_2(fresh: Path):
    (fresh / "scripts" / "boom.py").write_text("raise ValueError('boom')\n")
    result = invoke("run", "scripts/boom.py")
    assert result.exit_code == 1
    assert invoke("run", "scripts/nothing.py").exit_code == 2


def test_run_in_a_separate_process_passes_the_exit_code(fresh: Path):
    (fresh / "scripts" / "x.py").write_text("import sys, pydexpi\nsys.exit(len(sys.argv))\n")
    done = subprocess.run(
        [sys.executable, "-m", "chemeascode", "run", "scripts/x.py", "a", "b"],
        cwd=fresh,
        capture_output=True,
        check=False,
    )
    assert done.returncode == 3, done.stderr


def test_run_fmt_formats_the_sheet_after_the_script(fresh: Path):
    sheet = fresh / "pid" / "P-01.xml"
    shutil.copy(EMPTY, sheet)
    (fresh / "scripts" / "x.py").write_text(
        "from pathlib import Path\n"
        "p = Path('pid/P-01.xml')\n"
        "p.write_bytes(p.read_bytes().replace(b'  <', b'<'))\n"
    )
    assert invoke("run", "--fmt", "pid/P-01.xml", "scripts/x.py").exit_code == 0
    assert invoke("fmt", "--check", "pid/P-01.xml").exit_code == 0


def test_run_warns_about_fmt_after_the_script(fresh: Path):
    (fresh / "scripts" / "x.py").write_text("import sys\nprint(sys.argv[1:])\n")
    result = invoke("run", "scripts/x.py", "3", "--fmt", "pid/P-01.xml")
    assert result.exit_code == 0
    assert "['3', '--fmt', 'pid/P-01.xml']" in result.output
    assert "--fmt after SCRIPT goes to the script" in result.output
    agents = (TEMPLATE / "AGENTS.md").read_text()
    assert "cheme run [--fmt SHEET] SCRIPT" in agents


def test_template_permissions_and_skills_name_cheme_run():
    settings = json.loads((TEMPLATE / "dot-claude" / "settings.json").read_text())
    allow = settings["permissions"]["allow"]
    assert "Bash(cheme:*)" in allow
    assert not any("uv run python" in rule for rule in allow)
    hooks = json.dumps(settings["hooks"])
    assert "cheme runs start --hook" in hooks and "cheme runs record --hook" in hooks
    draft = (Path(str(bundled_skills()["pid-draft"])) / "SKILL.md").read_text()
    agents = (TEMPLATE / "AGENTS.md").read_text()
    for text in (draft, agents):
        assert "cheme run" in text
        assert "chemeascode.domains.piping.authoring" in text
    assert "own XML" in draft


# -- the authoring API (pre-release issue 13) ------------------------------------------------------


def _example(fresh: Path) -> Path:
    started = invoke("sheet", "new", "P-99", "--title", "Example")
    assert started.exit_code == 0, started.output
    result = invoke("run", "scripts/example_draft.py", "pid/P-99.xml")
    assert result.exit_code == 0, result.output
    return fresh / "pid" / "P-99.xml"


def test_template_example_passes_fmt_and_validate(fresh: Path):
    _example(fresh)
    assert invoke("fmt", "--check", "pid/P-99.xml").exit_code == 0
    report = invoke("validate", "--json")
    assert report.exit_code == 0
    findings = json.loads(report.output)["findings"]
    assert not [f for f in findings if f["level"] == "error"], findings
    sheet_rules = {f["rule"] for f in findings if f["file"] == "pid/P-99.xml"}
    # The lists are empty: the sheet's items, and the tags its trip note names, are not listed.
    assert sheet_rules <= {
        "cheme.line-not-listed",
        "cheme.instrument-not-listed",
        "cheme.equipment-not-listed",
        "cheme.label-tag-unknown",
        "cheme.label-tag",
    }, sheet_rules


def test_example_control_valve_is_found_from_the_instrument(fresh: Path):
    _example(fresh)
    shown = invoke("show", "FV101")
    assert shown.exit_code == 0
    assert "Inst_FIC101" in shown.output
    assert "OperatedValveReference" in shown.output


def _fragment_part(output: str, title: str) -> str:
    text = output.split(f"<!-- {title}:", 1)[1].split("-->", 1)[1]
    return text.split("<!--", 1)[0].strip()


def _canonical(xml: str | etree._Element) -> bytes:
    element = etree.fromstring(xml) if isinstance(xml, str) else xml
    parser = etree.XMLParser(remove_blank_text=True)
    return etree.tostring(etree.fromstring(etree.tostring(element), parser))


def test_api_and_fragment_cli_write_the_same_valve_and_tee(fresh: Path):
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line, tee, valve

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80)],
    )
    b = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    line(
        sheet,
        "80-A-1",
        dn=80,
        route=[
            a["N1"],
            valve("V1", "BallValve", at=(100, 100), tag="V-1"),
            tee("Tee1", at=(150, 100)),
            b["N1"],
        ],
    )
    for kind, args in (
        ("valve", ["--class", "BallValve", "--at", "100,100", "--tag", "V-1"]),
        ("tee", ["--at", "150,100"]),
    ):
        object_id = "V1" if kind == "valve" else "Tee1"
        cli = invoke(
            "fragment", kind, "--id", object_id, "--dn", "80", *args, "--sheet", str(EMPTY)
        )
        assert cli.exit_code == 0, cli.output
        for title, element in (
            ("CONCEPTUAL", sheet.find(object_id)),
            ("DRAWING", sheet.find(f"{object_id}_Drawing")),
        ):
            assert _canonical(_fragment_part(cli.output, title)) == _canonical(element), kind


def test_api_refuses_ids_that_exist(fresh: Path):
    from chemeascode.domains.piping.authoring import AuthoringError, Sheet, equipment

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    equipment(sheet, "Tank", "T-1", shape="VESSEL_WITH_DISHED_HEADS_SHAPE", at=(60, 100))
    with pytest.raises(AuthoringError, match="exists already"):
        equipment(sheet, "Vessel", "T-1", shape="VESSEL_WITH_DISHED_HEADS_SHAPE", at=(90, 100))
    with pytest.raises(AuthoringError, match="no shape"):
        equipment(sheet, "Tank", "T-3", shape="NO_SUCH_SHAPE", at=(90, 100))


def _label_boxes(sheet, made):
    from chemeascode.domains.piping.authoring.sheet import LABEL_SIZE, text_box

    texts = [
        made.number,
        sheet.find(made.id).findtext("Data[@property='NominalDiameterRepresentation']/String"),
    ]
    spots = [made.labels["LineNumber"], made.labels["NominalDiameterRepresentation"]]
    return [text_box(t, xy, LABEL_SIZE) for t, xy in zip(texts, spots, strict=True)]


@pytest.mark.parametrize(
    "route",
    [
        [(40.0, 100.0), (240.0, 100.0)],  # horizontal
        [(120.0, 40.0), (120.0, 220.0)],  # vertical
        [(40.0, 60.0), (100.0, 60.0), (100.0, 160.0), (240.0, 160.0)],  # bent
    ],
    ids=["horizontal", "vertical", "bent"],
)
def test_line_labels_are_never_on_their_own_route(fresh: Path, route):
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line, valve
    from chemeascode.domains.piping.authoring.sheet import segment_hits_box

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    start, end = route[0], route[-1]
    a = equipment(
        sheet,
        "Vessel",
        "V-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(start[0] - 15, start[1] - 15),
        nozzles=[Nozzle("N1", (15, 15), 100)],
    )
    b = equipment(
        sheet,
        "Vessel",
        "V-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(end[0] + 15, end[1] + 15),
        nozzles=[Nozzle("N1", (-15, -15), 100)],
    )
    made = line(
        sheet,
        "100-LONG-NUMBER-4711",
        dn=100,
        fluid="Air",
        route=[a["N1"], *route[1:-1], valve("XV1"), b["N1"]],
    )
    assert made.labels and not made.notes
    legs = list(zip(made.route, made.route[1:], strict=False))
    for box in _label_boxes(sheet, made):
        assert not any(segment_hits_box(p, q, box) for p, q in legs), (box, legs)
    sheet.save()
    assert invoke("validate", "pid/P-01.xml").exit_code == 0


def test_place_line_labels_reports_when_there_is_no_room():
    from chemeascode.domains.piping.authoring import place_line_labels

    spots, clear = place_line_labels([(0.0, 0.0), (10.0, 0.0)], ["A"])
    assert clear and spots[0][1] < 0


def test_line_refuses_a_valve_off_its_leg(fresh: Path):
    from chemeascode.domains.piping.authoring import (
        AuthoringError,
        Nozzle,
        Sheet,
        equipment,
        line,
        valve,
    )

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    a = equipment(
        sheet,
        "Tank",
        "T-1",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(60, 100),
        nozzles=[Nozzle("N1", (10, 0), 80)],
    )
    b = equipment(
        sheet,
        "Tank",
        "T-2",
        shape="VESSEL_WITH_DISHED_HEADS_SHAPE",
        at=(200, 100),
        nozzles=[Nozzle("N1", (-10, 0), 80)],
    )
    with pytest.raises(AuthoringError, match="not on the leg"):
        line(sheet, "80-A-1", dn=80, route=[a["N1"], valve("V1", at=(100, 120)), b["N1"]])


def test_line_is_atomic_a_failed_line_leaves_nothing_behind(fresh: Path):
    from chemeascode.domains.piping.authoring import (
        AuthoringError,
        Sheet,
        line,
        offpage,
        tee,
        valve,
    )
    from chemeascode.domains.piping.authoring.sheet import Tee

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    before = etree.tostring(sheet.root)
    ids = set(sheet.index.by_id)
    with pytest.raises(AuthoringError, match="sideways"):
        tee("T1", branch="sideways")  # refused before any line is built
    ends = (offpage("in", at=(40, 100)), offpage("out", at=(140, 100)))
    # Fails halfway: the valve and the off-page connector are built, the tee is not.
    for bad in (Tee("T1", branch_side="sideways"), valve("V1")):
        with pytest.raises(AuthoringError):
            line(sheet, "50-W-1", dn=50, route=[ends[0], valve("V1"), bad, ends[1]])
        assert etree.tostring(sheet.root) == before
        assert set(sheet.index.by_id) == ids
    made = line(
        sheet,
        "50-W-1",
        dn=50,
        route=[offpage("in", at=(40, 100)), valve("V1"), offpage("out", at=(140, 100))],
    )
    assert made.id == "Line_50W1"
    sheet.save()
    assert invoke("validate", "pid/P-01.xml").exit_code == 0


def test_line_labels_keep_clear_of_symbols_and_other_lines(fresh: Path):
    """The review case: a staircase line starting next to T-1 put its labels on the vessel."""
    from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line
    from chemeascode.domains.piping.authoring.sheet import segment_hits_box

    shutil.copy(EMPTY, fresh / "pid" / "P-01.xml")
    sheet = Sheet.load(fresh / "pid" / "P-01.xml")
    shape = "VESSEL_WITH_DISHED_HEADS_SHAPE"
    a = equipment(
        sheet, "Tank", "T-1", shape=shape, at=(50, 50), nozzles=[Nozzle("N1", (0, 10), 50)]
    )
    b = equipment(
        sheet, "Tank", "T-2", shape=shape, at=(70, 90), nozzles=[Nozzle("N1", (0, -10), 50)]
    )
    route: list = [a["N1"]]
    x, y = 50, 60
    while y < 78:
        x += 3
        route.append((x, y))
        y += 3
        route.append((x, y))
    route += [(70, y), b["N1"]]
    symbols = sheet.symbol_boxes()
    assert any(x0 <= 50 <= x1 and y0 <= 50 <= y1 for x0, y0, x1, y1 in symbols)  # T-1
    made = line(sheet, "50-N-1000-ABCDEFGH", dn=50, route=route)
    boxes = _label_boxes(sheet, made)
    assert not any(
        bx0 < x1 and x0 < bx1 and by0 < y1 and y0 < by1
        for bx0, by0, bx1, by1 in boxes
        for x0, y0, x1, y1 in sheet.symbol_boxes()
    ), (boxes, made.labels)
    # A second line's labels keep off the first line's pipes.
    c = equipment(
        sheet, "Tank", "T-3", shape=shape, at=(30, 120), nozzles=[Nozzle("N1", (10, 0), 50)]
    )
    d = equipment(
        sheet, "Tank", "T-4", shape=shape, at=(130, 120), nozzles=[Nozzle("N1", (-10, 0), 50)]
    )
    second = line(sheet, "50-N-1001", dn=50, route=[c["N1"], d["N1"]])
    paths = sheet.line_paths()
    assert len(paths) >= 2
    for box in _label_boxes(sheet, second):
        for path in paths:
            legs = zip(path, path[1:], strict=False)
            assert not any(segment_hits_box(p, q, box) for p, q in legs), box


# -- generated sheets (pre-release issue 16) -------------------------------------------------------

GENERATOR = """\
import sys
from chemeascode.domains.piping.authoring import Nozzle, Sheet, equipment, line
sheet = Sheet.load(sys.argv[1])
a = equipment(sheet, "Tank", "T-1", shape="VESSEL_WITH_DISHED_HEADS_SHAPE", at=(60, 100),
              nozzles=[Nozzle("N1", (10, 0), 80)])
b = equipment(sheet, "Tank", "T-2", shape="VESSEL_WITH_DISHED_HEADS_SHAPE", at=(200, 100),
              nozzles=[Nozzle("N1", (-10, 0), 80)])
line(sheet, "80-A-1", dn=80, fluid="Air", route=[a["N1"], b["N1"]])
sheet.save()
"""

PLANT = """\
# The plant.
name: Test plant
sheets:
  # the generated one
  - {id: P-01, file: pid/P-01.xml, title: One,
     generator: {script: scripts/draft_P-01.py, frame: pid/frame.xml}}
  - id: P-02
    file: pid/P-02.xml
    generator:
      script: scripts/draft_P-02.py
      frame: pid/frame.xml
    title: Two   # kept
"""


@pytest.fixture
def generated(fresh: Path) -> Path:
    shutil.copy(EMPTY, fresh / "pid" / "frame.xml")
    for sheet in ("P-01", "P-02"):
        (fresh / "scripts" / f"draft_{sheet}.py").write_text(GENERATOR)
    (fresh / "plant.yaml").write_text(PLANT)
    assert invoke("regen").exit_code == 0
    git(fresh, "add", "-A")
    git(fresh, "commit", "-q", "-m", "generated")
    return fresh


def test_schema_describes_the_generator():
    schema = json.loads(invoke("schema", "plant").output)
    assert "Generator" in schema["$defs"]
    assert set(schema["$defs"]["Generator"]["properties"]) == {"script", "frame"}


def test_regen_reproduces_and_refuses_hand_edits(generated: Path):
    sheet = generated / "pid" / "P-01.xml"
    written = sheet.read_bytes()
    result = invoke("regen", "P-01")
    assert result.exit_code == 0 and "up to date" in result.output
    assert sheet.read_bytes() == written
    # A hand edit, committed: regen refuses and names the item.
    sheet.write_bytes(written.replace(b"<String>T-2</String>", b"<String>T-9</String>"))
    git(generated, "commit", "-q", "-am", "hand edit")
    refused = invoke("regen", "P-01")
    assert refused.exit_code == 1
    assert "edited by hand" in refused.output and "T2 [T-9]" in refused.output
    assert invoke("regen", "P-01", "--force").exit_code == 0
    assert sheet.read_bytes() == written


def test_regen_writes_a_script_change(generated: Path):
    script = generated / "scripts" / "draft_P-01.py"
    script.write_text(GENERATOR.replace('"T-2"', '"T-3"'))
    result = invoke("regen", "P-01")
    assert result.exit_code == 0, result.output
    assert b"T-3" in (generated / "pid" / "P-01.xml").read_bytes()


def test_validate_reports_drift_for_the_drifting_sheet_only(generated: Path):
    sheet = generated / "pid" / "P-02.xml"
    sheet.write_bytes(sheet.read_bytes().replace(b"<String>T-2</String>", b"<String>T-9</String>"))
    findings = json.loads(invoke("validate", "--json").output)["findings"]
    drift = [f for f in findings if f["rule"] == "cheme.generated-sheet-drift"]
    assert [f["file"] for f in drift] == ["pid/P-02.xml"]
    assert "T2 [T-9]" in drift[0]["message"]
    skipped = json.loads(invoke("validate", "--json", "--skip-generators").output)["findings"]
    assert not [f for f in skipped if f["rule"] == "cheme.generated-sheet-drift"]


def test_a_validate_gate_sees_generator_drift(generated: Path, monkeypatch):
    """#228: the gates validated without the generators, so drift never failed one."""
    gate = "{id: no-drift, title: generated sheets reproduce, stage: concept, kind: validate"
    (generated / "checks" / "checks.yaml").write_text(
        "schema: cheme/checks/v1\nchecks:\n"
        f"  - {gate}, fail_on: info, rules: ['cheme.generated-*']}}\n"
        f"  - {gate.replace('no-drift', 'errors')}}}\n"  # fail_on error: drift is a warning
    )
    from chemeascode.project import checks

    runs = []
    real = checks.validate_workspace

    def recorded(workspace, *args, generators=False, **kwargs):
        runs.append(generators)
        return real(workspace, *args, generators=generators, **kwargs)

    monkeypatch.setattr(checks, "validate_workspace", recorded)
    result = invoke("check")
    assert result.exit_code == 0, result.output
    assert sorted(runs) == [False, True]  # the fail_on: error gate does not run the generators
    sheets = {p.name: p.read_bytes() for p in (generated / "pid").glob("*.xml")}
    sheet = generated / "pid" / "P-02.xml"
    sheet.write_bytes(sheet.read_bytes().replace(b"<String>T-2</String>", b"<String>T-9</String>"))
    result = invoke("check")
    assert result.exit_code == 1
    assert "FAIL [concept] no-drift" in result.output
    assert "1 cheme.generated-sheet-drift not accepted" in result.output
    assert "ok   [concept] errors" in result.output
    edited = {p.name: p.read_bytes() for p in (generated / "pid").glob("*.xml")}
    assert edited == {**sheets, "P-02.xml": sheet.read_bytes()}  # the gates wrote nothing


def test_a_validate_gate_fails_on_a_generator_that_raises(generated: Path):
    """#305: cheme.generated-* did not match cheme.generator-failed, so a generator that crashed
    (the sheet not reproduced at all) passed the gate that drift fails."""
    (generated / "checks" / "checks.yaml").write_text(
        "schema: cheme/checks/v1\nchecks:\n"
        "  - {id: no-drift, title: generated sheets reproduce, stage: concept, kind: validate, "
        "fail_on: warning, rules: ['cheme.generated-*']}\n"
        "  - {id: drift-only, title: drift only, stage: concept, kind: validate, "
        "fail_on: warning, rules: [cheme.generated-sheet-drift]}\n"
        "  - {id: failed-only, title: generators run, stage: concept, kind: validate, "
        "fail_on: warning, rules: [cheme.generator-failed]}\n"
        "  - {id: other, title: other rules, stage: concept, kind: validate, "
        "fail_on: warning, rules: [cheme.generated-edited]}\n"
    )
    script = generated / "scripts" / "draft_P-02.py"
    script.write_text(GENERATOR + "raise RuntimeError('generator broke')\n")
    found = json.loads(invoke("validate", "--json").output)["findings"]
    failed = [f for f in found if f["rule"] == "cheme.generator-failed"]
    assert [(f["file"], f["level"]) for f in failed] == [("pid/P-02.xml", "warning")]
    assert not [f for f in found if f["rule"] == "cheme.generated-sheet-drift"]
    result = invoke("check")
    assert result.exit_code == 1
    assert "FAIL [concept] no-drift" in result.output
    assert "FAIL [concept] drift-only" in result.output
    assert "FAIL [concept] failed-only" in result.output
    assert "ok   [concept] other" in result.output
    assert "cheme.generator-failed" in result.output
    # cheme validate agrees with the gate: the same rules, at the same level, fail it
    only = invoke("validate", "--only", "cheme.generated-*", "--fail-on", "warning", "--json")
    assert only.exit_code == 1
    assert [f["rule"] for f in json.loads(only.output)["findings"]] == ["cheme.generator-failed"]
    assert invoke("validate", "--only", "cheme.generated-*", "--fail-on", "warning").exit_code == 1
    ignored = invoke("validate", "--ignore", "cheme.generated-*", "--json").output
    assert not [f for f in json.loads(ignored)["findings"] if f["rule"].startswith("cheme.gener")]
    # fixed: both pass again
    script.write_text(GENERATOR)
    fixed = invoke("check")
    assert fixed.exit_code == 0, fixed.output
    fixed = invoke("validate", "--only", "cheme.generated-*", "--fail-on", "warning")
    assert fixed.exit_code == 0, fixed.output


def test_rule_patterns_match_generator_failed_with_drift():
    from chemeascode.foundation.findings import rule_matches

    assert rule_matches("cheme.generator-failed", "cheme.generated-*")
    assert rule_matches("cheme.generator-failed", "cheme.generated-sheet-drift")
    assert rule_matches("cheme.generator-failed", "cheme.generator-failed")
    assert not rule_matches("cheme.generator-failed", "cheme.generated-edited")
    assert not rule_matches("cheme.generated-sheet-drift", "cheme.generator-failed")


def test_validate_notes_undeclared_draft_scripts(generated: Path):
    plant = generated / "plant.yaml"
    assert invoke("regen", "--detach", "P-01", "P-02").exit_code == 0
    findings = json.loads(invoke("validate", "--json").output)["findings"]
    notes = [f for f in findings if f["rule"] == "cheme.generator-undeclared"]
    assert sorted(f["file"] for f in notes) == ["scripts/draft_P-01.py", "scripts/draft_P-02.py"]
    assert all(f["level"] == "info" for f in notes)
    text = plant.read_text()
    assert "generator" not in text
    assert "# the generated one" in text and "title: Two   # kept" in text
    assert "{id: P-01, file: pid/P-01.xml, title: One}" in text
    assert invoke("regen", "P-01").exit_code == 1  # hand-maintained now


def test_validate_and_regen_never_change_the_working_tree(generated: Path):
    """A generator that writes more than its scratch file (here: the sheet itself, as the old
    pid-draft recipe did) runs in a copy: validate leaves the working tree as it was."""
    script = generated / "scripts" / "draft_P-01.py"
    script.write_text(
        GENERATOR
        + "side = Sheet.load('pid/P-01.xml')\n"
        + "from chemeascode.domains.piping.authoring import note\n"
        + "note(side, 'side effect', at=(10, 10))\n"
        + "side.save()\n"
        + "open('stray.txt', 'w').write('x')\n"
    )
    git(generated, "commit", "-q", "-am", "generator with side effects")
    sheet = generated / "pid" / "P-01.xml"
    committed = sheet.read_bytes()
    for _ in range(2):
        findings = json.loads(invoke("validate", "--json").output)["findings"]
        assert not [f for f in findings if f["rule"] == "cheme.generated-sheet-drift"]
    assert sheet.read_bytes() == committed
    assert not (generated / "stray.txt").exists()
    assert git(generated, "status", "--porcelain").strip() == ""
    assert "up to date" in invoke("regen", "P-01").output
    assert sheet.read_bytes() == committed and not (generated / "stray.txt").exists()


def test_regen_in_a_plant_below_the_top_of_the_git_repository(tmp_path: Path, monkeypatch):
    top = tmp_path / "mono"
    plant = top / "plant"
    init(plant, "Test plant")
    git(top, "init", "-q", "-b", "main")
    git(top, "config", "user.email", "test@example.org")
    git(top, "config", "user.name", "Test")
    shutil.copy(EMPTY, plant / "pid" / "P-01.xml")
    git(top, "add", "-A")
    git(top, "commit", "-q", "-m", "empty sheet")
    frame = git(top, "rev-parse", "--short", "HEAD").strip()
    (plant / "scripts" / "draft_P-01.py").write_text(GENERATOR)
    (plant / "plant.yaml").write_text(
        "name: Test plant\nsheets:\n  - {id: P-01, file: pid/P-01.xml, title: One, "
        f"generator: {{script: scripts/draft_P-01.py, frame: '{frame}'}}}}\n"
    )
    monkeypatch.chdir(plant)
    result = invoke("regen", "P-01")
    assert result.exit_code == 0, result.output
    written = (plant / "pid" / "P-01.xml").read_bytes()
    assert b"T-2" in written
    git(top, "add", "-A")
    git(top, "commit", "-q", "-m", "generated")
    assert "up to date" in invoke("regen", "P-01").output
    # A hand edit is told apart from the committed generator's output (archive of plant/).
    (plant / "pid" / "P-01.xml").write_bytes(
        written.replace(b"<String>T-2</String>", b"<String>T-9</String>")
    )
    (plant / "scripts" / "draft_P-01.py").write_text(GENERATOR.replace('"T-1"', '"T-5"'))
    refused = invoke("regen", "P-01")
    assert refused.exit_code == 1 and "edited by hand" in refused.output, refused.output
    findings = json.loads(invoke("validate", "--json").output)["findings"]
    assert [f["file"] for f in findings if f["rule"] == "cheme.generated-sheet-drift"] == [
        "pid/P-01.xml"
    ]


def test_remove_generator_keeps_everything_else():
    from chemeascode.domains.piping.generators import remove_generator

    text = "sheets:\n  - {id: A, generator: {script: s.py, frame: f.xml}, file: a.xml}\n"
    assert remove_generator(text, "A") == "sheets:\n  - {id: A, file: a.xml}\n"


def _migrate_from_plantcode(root: Path) -> None:
    """The steps of docs/framework/rename.md for the YAML and the scripts of a plant repository
    written for plantcode (the package's name before 0.7.0); the XML is left alone."""
    for path in [*root.rglob("*.yaml"), *root.rglob("*.py")]:
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        new = re.sub(r"\bplantcode(\s*)>=\s*[\d.]+", "cheme-as-code>=0.7", text)
        new = re.sub(r"\bplantcode/([a-z_-]+/v\d)", r"cheme/\1", new)
        new = re.sub(r"\b(from|import) plantcode\b", r"\1 chemeascode", new)
        if new != text:
            path.write_text(new, encoding="utf-8")


@pytest.mark.skipif(not (ASU / ".git").exists(), reason="the ASU-1 evidence repository is local")
def test_asu_p04_reproduces_at_s5_and_refuses_at_head(tmp_path: Path, monkeypatch):
    template = (
        '  - {{id: P-04, file: pid/P-04.xml, title: "Products, storage and backup supply", '
        "generator: {{script: scripts/draft_P-04.py, frame: {frame}}}}}"
    )
    # both revisions are pinned: 48d4e4c is the S5 state (the committed sheet equals the script's
    # output), d6f7e5f the last revision before D-095/D-096 changed P-04 by hand (LOX-4004 and
    # FI-4148 were still tags there). A moving HEAD made this test fail as the sheet evolved
    # (pre-release issue 314).
    for rev, expect in (("48d4e4c", 0), ("d6f7e5f", 1)):
        top = tmp_path / rev
        subprocess.run(["git", "clone", "-q", str(ASU), str(top)], check=True)
        subprocess.run(["git", "checkout", "-q", rev], cwd=top, check=True)
        copy = plant_root(top)
        frame = "9aa9b38"
        if copy != top:
            # the frame revision has the plant at the top: hand the frame over as a file
            shown = subprocess.run(
                ["git", "show", "9aa9b38:pid/P-04.xml"], cwd=top, capture_output=True, check=True
            )
            (copy / "scripts").mkdir(exist_ok=True)
            (copy / "scripts" / "frame-P-04.xml").write_bytes(shown.stdout)
            frame = "scripts/frame-P-04.xml"
        declared = template.format(frame=frame)
        _migrate_from_plantcode(copy)
        plant = copy / "plant.yaml"
        lines = [
            declared if line.startswith("  - {id: P-04") else line
            for line in plant.read_text().splitlines()
        ]
        plant.write_text("\n".join(lines) + "\n")
        committed = (copy / "pid" / "P-04.xml").read_bytes()
        monkeypatch.chdir(copy)
        result = invoke("regen", "P-04")
        assert result.exit_code == expect, result.output
        assert (copy / "pid" / "P-04.xml").read_bytes() == committed
        if expect:
            assert "LOX-4004" in result.output and "FI-4148" in result.output
            findings = json.loads(invoke("validate", "--json").output)["findings"]
            drift = [f["file"] for f in findings if f["rule"] == "cheme.generated-sheet-drift"]
            assert drift == ["pid/P-04.xml"]
