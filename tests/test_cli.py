import json
import re
import shlex
import shutil
import struct
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()


def test_init_gives_a_valid_empty_repository(tmp_path: Path, monkeypatch):
    root = tmp_path / "new-plant"
    assert runner.invoke(app, ["init", str(root), "--name", "Ethanol"]).exit_code == 0
    assert (root / ".claude" / "skills" / "dexpi-xml" / "SKILL.md").is_file()
    assert (root / ".gitattributes").read_text().strip() == "pid/*.xml diff=dexpi"
    assert "Ethanol" in (root / "plant.yaml").read_text()
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output


def test_empty_sheet_snippet_validates_clean(tmp_path: Path, monkeypatch):
    root = tmp_path / "p"
    runner.invoke(app, ["init", str(root)])
    snippet = root / ".claude/skills/dexpi-xml/snippets/empty-sheet.xml"
    (root / "pid" / "P-01.xml").write_bytes(snippet.read_bytes())
    monkeypatch.chdir(root)
    # A raw copy is clean but for its placeholders, which cheme sheet new replaces
    # (pre-release issue 19).
    result = runner.invoke(app, ["validate", "--json"])
    findings = json.loads(result.stdout)["findings"]
    assert {(f["rule"], f["ids"][0]) for f in findings if f["level"] != "info"} == {
        ("cheme.template-metadata", "ModelName"),
        ("cheme.template-metadata", "ModelUri"),
        ("cheme.template-metadata", "DiagramName"),
    }
    result = runner.invoke(
        app, ["validate", "--fail-on", "warning", "--ignore", "cheme.template-metadata"]
    )
    assert result.exit_code == 0, result.output
    assert runner.invoke(app, ["fmt", "--check"]).exit_code == 0


def test_validate_json_and_fmt_check(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    payload = json.loads(runner.invoke(app, ["validate", "--json"]).stdout)
    assert payload["files"][0] == "pid/P-01.xml"
    assert runner.invoke(app, ["fmt", "--check"]).exit_code == 1
    assert runner.invoke(app, ["fmt"]).exit_code == 0
    assert runner.invoke(app, ["fmt", "--check"]).exit_code == 0


def test_render_writes_svg_with_object_ids(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    assert runner.invoke(app, ["render"]).exit_code == 0
    svg = (plant / "build" / "P-01.svg").read_text()
    assert 'id="Tank1"' in svg


def test_diff_highlights_a_changed_valve(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    runner.invoke(app, ["fmt"])
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "P-01")
    sheet = plant / "pid" / "P-01.xml"
    text = sheet.read_text(encoding="utf-8")
    # Renumber valve C1 (GlobeValve2) and remove the tank's manhole drawing.
    assert "<String>C1</String>" in text
    sheet.write_text(text.replace("<String>C1</String>", "<String>C1A</String>", 1))
    result = runner.invoke(app, ["diff", "HEAD"])
    assert result.exit_code == 0, result.output
    assert "1 modified" in result.output
    html = (plant / "build" / "diff.html").read_text()
    assert '[id="GlobeValve2"]' in html and "GlobeValve2" in html


def test_check_reports_and_writes_status_only_with_write(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["check"])
    assert "FAIL [basic] design-review" in result.output
    assert result.exit_code == 1
    assert not (plant / "checks" / "status.json").exists()
    result = runner.invoke(app, ["check", "--write"])
    assert result.exit_code == 1
    assert "refused; nothing written" in result.output
    assert not (plant / "checks" / "status.json").exists()


def test_git_setup_textconv(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    assert runner.invoke(app, ["git-setup", "--no-hook"]).exit_code == 0
    driver = git(plant, "config", "diff.dexpi.textconv").strip()
    assert driver.endswith(" textconv")
    assert Path(shlex.split(driver)[0]).is_absolute()
    result = runner.invoke(app, ["textconv", "pid/P-01.xml"])
    assert "T4750" in result.stdout


def test_textconv_never_fails(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    (plant / "pid" / "broken.xml").write_text("<Model><Object", encoding="utf-8")
    result = runner.invoke(app, ["textconv", "pid/broken.xml"])
    assert result.exit_code == 0
    assert result.stdout.startswith("(cheme textconv could not load")
    assert "<Model><Object" in result.stdout
    result = runner.invoke(app, ["textconv", "pid/missing.xml"])
    assert result.exit_code == 0
    assert "could not read it" in result.stdout


def test_schema_command():
    result = runner.invoke(app, ["schema", "equipment"])
    assert json.loads(result.stdout)["title"] == "EquipmentList"


def _commit_formatted(plant: Path) -> Path:
    runner.invoke(app, ["fmt"])
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "P-01")
    return plant / "pid" / "P-01.xml"


def test_render_png_crop_and_rev(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    result = runner.invoke(app, ["render", "--png", "--scale", "2", "--crop", "300,180,150,50"])
    assert result.exit_code == 0, result.output
    assert not (plant / "build" / "P-01.png").exists()  # a crop never takes the sheet's name
    png = (plant / "build" / "P-01_crop-150-50-300-180.png").read_bytes()
    assert png.startswith(b"\x89PNG")
    width, height = struct.unpack(">II", png[16:24])
    assert (width, height) == (300, 260)  # 150 x 130 mm at 2 px/mm

    result = runner.invoke(app, ["render", "--crop", "300,180,150,50", "-o", "build/c.svg"])
    assert result.exit_code == 0, result.output
    assert 'viewBox="150 50 150 130"' in (plant / "build" / "c.svg").read_text()

    sheet.write_text(sheet.read_text().replace('id="Tank1"', 'id="TankRenamed"'))
    result = runner.invoke(app, ["render", "--rev", "HEAD"])
    assert result.exit_code == 0, result.output
    assert 'id="Tank1"' in (plant / "build" / "P-01@HEAD.svg").read_text()
    result = runner.invoke(app, ["render", "--rev", "HEAD", "--crop", "0,0,10.5,20"])
    assert result.output.strip().endswith("build/P-01@HEAD_crop-0-0-10.5-20.svg")
    assert (plant / "build" / "P-01@HEAD.svg").is_file()

    assert runner.invoke(app, ["render", "--crop", "1,2,3"]).exit_code == 2
    assert runner.invoke(app, ["render", "--rev=-x"]).exit_code == 2
    result = runner.invoke(app, ["render", "--rev", "nosuchrev"])
    assert result.exit_code == 2 and "unknown revision 'nosuchrev'" in result.output


def test_render_rejects_non_finite_and_huge_crops(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    for bad in ("nan,0,10,10", "0,0,inf,10", "-inf,0,1,1"):
        result = runner.invoke(app, ["render", "--crop", bad])
        assert result.exit_code == 2 and "finite" in result.output, bad
    assert not (plant / "build" / "P-01.svg").exists()
    result = runner.invoke(app, ["render", "--png", "--scale", "1", "--crop", "0,0,1e6,1e6"])
    assert result.exit_code == 2 and "Mpx" in result.output
    assert not (plant / "build" / "P-01.png").exists()


def test_render_png_without_resvg_names_the_extra(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    monkeypatch.setitem(sys.modules, "resvg_py", None)
    result = runner.invoke(app, ["render", "--png"])
    assert result.exit_code == 2
    assert "uv tool install 'cheme-as-code[png]'" in result.output
    assert "cheme-as-code[png] @ git+https://github.com/" in result.output


def test_diff_list_and_json(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    text = sheet.read_text(encoding="utf-8")
    sheet.write_text(text.replace("<String>C1</String>", "<String>C1A</String>", 1))

    result = runner.invoke(app, ["diff", "--list"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines() == [
        "pid/P-01.xml:",
        "modified GlobeValve GlobeValve2 [C1A]: 0 added, 0 removed, 1 modified",
    ]
    detail = (
        "modified GlobeValve GlobeValve2 [C1A] (conceptual) pipingComponentNumber"
        " -> drawn as GlobeValve2"
    )
    result = runner.invoke(app, ["diff", "--list", "--flat"])
    assert result.output.splitlines() == ["pid/P-01.xml:", detail]
    result = runner.invoke(app, ["diff", "--list", "--verbose"])
    assert result.output.splitlines()[1:] == [
        "modified GlobeValve GlobeValve2 [C1A]: 0 added, 0 removed, 1 modified",
        "  " + detail,
    ]
    assert runner.invoke(app, ["diff", "--flat"]).exit_code == 2
    assert not (plant / "build" / "diff.html").exists()

    result = runner.invoke(app, ["diff", "HEAD", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [s["path"] for s in payload] == ["pid/P-01.xml"]
    assert "old_svg" not in payload[0] and "new_svg" not in payload[0]
    assert payload[0]["changes"][0]["object_id"] == "GlobeValve2"
    assert payload[0]["new_owner"] == {"GlobeValve2": "GlobeValve2"}
    assert payload[0]["changes"][0]["item"] == "GlobeValve2"
    assert payload[0]["items"] == {"GlobeValve2": {"class": "GlobeValve", "tag": "C1A"}}
    assert "GlobeValve@GlobeValve2" in payload[0]["projection_diff"]

    result = runner.invoke(app, ["diff", "--json", "--html", "build/d.html"])
    assert json.loads(result.stdout)[0]["path"] == "pid/P-01.xml"
    assert (plant / "build" / "d.html").is_file()

    git(plant, "commit", "-qam", "C1A")
    assert json.loads(runner.invoke(app, ["diff", "--json"]).stdout) == []
    assert runner.invoke(app, ["diff", "--list"]).output.strip() == "No P&ID changed."


def test_diff_list_marks_added_sheet(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    _commit_formatted(plant)
    shutil.copy(plant / "pid" / "P-01.xml", plant / "pid" / "P-02.xml")
    result = runner.invoke(app, ["diff", "--list", "--path", "pid/P-02.xml"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "pid/P-02.xml: (sheet added)"
    tank = next(line for line in lines if line.startswith("added Tank Tank1 [T4750]: "))
    assert tank.endswith(" added, 0 removed, 0 modified")
    assert all(not line.startswith("  ") for line in lines)


def test_diff_reports_a_broken_sheet_and_compares_the_others(plant: Path, monkeypatch):
    """A truncated sheet is named with one line; the others are still compared
    (pre-release issue 209)."""
    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    content = sheet.read_bytes()
    (plant / "pid" / "P-03.xml").write_bytes(content[:5000])
    sheet.write_bytes(content.replace(b"<String>C1</String>", b"<String>C1A</String>", 1))
    paths = ["--path", "pid/P-03.xml", "--path", "pid/P-01.xml"]
    result = runner.invoke(app, ["diff", *paths, "--list"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)  # an exit, not a traceback
    assert "pid/P-03.xml: cannot compare: working tree does not load: XMLSyntaxError" in (
        result.stderr
    )
    assert "pid/P-01.xml:" in result.stdout and "C1A" in result.stdout
    result = runner.invoke(app, ["diff", *paths])
    assert result.exit_code == 1, result.output
    html = (plant / "build" / "diff.html").read_text()
    assert "pid/P-03.xml" in html and "does not load" in html and '[id="GlobeValve2"]' in html


def test_diff_and_render_survive_a_sheet_that_does_not_draw(plant: Path, monkeypatch):
    """A dangling Shape reference: diff lists the changes, render goes on to the next
    (pre-release issue 209)."""
    from tests.test_diffview import _dangling_shape

    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    broken = plant / "pid" / "P-02.xml"
    broken.write_bytes(_dangling_shape(sheet.read_bytes()))
    result = runner.invoke(app, ["diff", "--path", "pid/P-02.xml", "--list"])
    assert result.exit_code == 1, result.output
    assert "pid/P-02.xml: cannot draw working tree: AttributeError" in result.stderr
    assert result.stdout.startswith("pid/P-02.xml: (sheet added)")
    result = runner.invoke(app, ["render", "pid/P-02.xml", "pid/P-01.xml"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit)
    assert "pid/P-02.xml: cannot render: AttributeError" in result.stderr
    assert (plant / "build" / "P-01.svg").is_file() and not (plant / "build" / "P-02.svg").exists()


def test_show_by_id_and_tag(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["show", "Tank1"])
    assert result.exit_code == 0, result.output
    first = result.output.splitlines()[0]
    assert first.startswith("pid/P-01.xml:") and first.endswith("Tank Tank1 [T4750]")
    by_tag = runner.invoke(app, ["show", "T4750", "--sheet", "pid/P-01.xml"])
    assert by_tag.output == result.output

    result = runner.invoke(app, ["show", "nosuch-T4750"])
    assert result.exit_code == 1
    assert "No object with id or tag 'nosuch-T4750'" in result.output


def test_diff_reports_a_deleted_sheet_without_path(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    _commit_formatted(plant)
    git(plant, "rm", "-q", "pid/P-01.xml")
    result = runner.invoke(app, ["diff", "HEAD", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [(s["path"], s["status"]) for s in payload] == [("pid/P-01.xml", "removed")]
    result = runner.invoke(app, ["diff", "--list"])
    assert result.output.splitlines()[0] == "pid/P-01.xml: (sheet removed)"

    # Between two revisions, a sheet only in OLD is compared although the tree has none.
    git(plant, "commit", "-q", "-m", "drop P-01")
    result = runner.invoke(app, ["diff", "HEAD~1", "HEAD", "--json"])
    assert [s["status"] for s in json.loads(result.stdout)] == ["removed"]
    result = runner.invoke(app, ["diff", "HEAD", "HEAD~1", "--list"])
    assert result.output.splitlines()[0] == "pid/P-01.xml: (sheet added)"


def test_diff_unknown_revision_exits_2(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    _commit_formatted(plant)
    for args in (["nosuchrev", "--list"], ["nosuchrev", "--json"], ["HEAD", "nosuchrev"]):
        result = runner.invoke(app, ["diff", *args])
        assert result.exit_code == 2, args
        assert "unknown revision 'nosuchrev'" in result.output
        assert "added" not in result.output


def test_validate_ends_with_what_was_compared(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
    assert result.output.strip().splitlines()[-1].startswith("compared: 1 sheet(s)")


def test_schema_lists_kinds(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    kinds = [line.split()[0] for line in result.output.splitlines()]
    assert kinds == [
        "plant",
        "design_basis",
        "equipment",
        "lines",
        "instruments",
        "piping_items",
        "interlocks",
        "loops",
        "sequences",
        "checks",
        "rates",
        "cost_basis",
        "tea",
        "electrical",
        "crane_chart",
        "lca",
        "lca_factors",
        "site_plan",
        "building",
        "placement",
        "structures",
        "zones",
        "routing",
        "pipe_specs",
        "trays",
        "hvac",
        "datasheet",
        "review",
        "status",
        "process-materials",
        "process-flowsheet",
        "process-simulation",
        "process-reactions",
        "process-catalysts",
        "process-assays",
        "process-cells",
        "process-adsorption",
        "reaction-evidence",
        "process-extraction",
        "furnaces",
        "kinetic-data",
        "layout_model",
        "lci_dataset",
        "lci_estimate",
        "lca_mapping_profile",
        "adapter-result",
        "risk-matrix",
        "hazop-study",
        "failure-modes",
        "hazop-coverage",
        "frequencies",
        "narrative",
        "control_philosophy",
        "process-run",
    ]
    placement = json.loads(runner.invoke(app, ["schema", "placement"]).stdout)
    assert "position" in placement["$defs"]["Placement"]["properties"]
    lines = json.loads(runner.invoke(app, ["schema", "lines"]).stdout)
    assert "segments" in lines["$defs"]["Line"]["properties"]


def test_version_names_cheme_pydexpi_and_the_interpreter():
    import sys
    from importlib.metadata import version

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    first, second = result.output.strip().splitlines()
    assert first == f"cheme {version('cheme-as-code')} (pyDEXPI {version('pydexpi')})"
    assert second.startswith("python 3.") and second.endswith(f" at {sys.executable}")


def test_diff_list_groups_a_removal_by_plant_item(plant: Path, monkeypatch):
    from lxml import etree

    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    tree = etree.parse(str(sheet))
    for element in list(tree.getroot().iter("Object")):
        if element.get("id") in ("TubularHeatExchanger1", "TubularHeatExchanger1_Drawing1"):
            element.getparent().remove(element)
    tree.write(str(sheet))

    result = runner.invoke(app, ["diff", "--list"])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "pid/P-01.xml:"
    assert lines[1].startswith(
        "removed TubularHeatExchanger TubularHeatExchanger1 [H1008]: 0 added,"
    )
    assert lines[1].endswith(" removed, 0 modified")
    # The nozzles, chambers and the whole drawing are counted under the exchanger.
    assert int(lines[1].split(", ")[1].split()[0]) > 100
    assert all(line.startswith("changed PipingNetworkSystem ") for line in lines[2:])
    assert len(lines) < 10
    flat = runner.invoke(app, ["diff", "--list", "--flat"]).output.splitlines()
    assert len(flat) > 100
    verbose = runner.invoke(app, ["diff", "--list", "-v"]).output.splitlines()
    assert "  removed ProcessNozzle Nozzle10 [N1] (conceptual) -> drawn as Nozzle10" in verbose


def test_diff_list_header_and_flat_line_give_the_same_tag(plant: Path, monkeypatch):
    import copy

    from lxml import etree

    monkeypatch.chdir(plant)
    sheet = _commit_formatted(plant)
    tree = etree.parse(str(sheet))
    valve = next(e for e in tree.getroot().iter("Object") if e.get("id") == "BallValve1")
    clone = copy.deepcopy(valve)
    for element in clone.iter("Object"):
        element.set("id", "X" + element.get("id"))
    valve.addnext(clone)
    tree.write(str(sheet))

    grouped = runner.invoke(app, ["diff", "--list"]).output.splitlines()
    (header,) = [line for line in grouped if " XBallValve1 " in line]
    flat = runner.invoke(app, ["diff", "--list", "--flat"]).output.splitlines()
    (own,) = [line for line in flat if line.startswith("added BallValve XBallValve1 ")]
    tag = own.split("[", 1)[1].split("]", 1)[0]
    assert header.startswith(f"added BallValve XBallValve1 [{tag}]: "), (header, own)


def test_render_help_keeps_the_rev_part_of_the_file_name():
    result = runner.invoke(app, ["render", "--help"], env={"COLUMNS": "200", "NO_COLOR": "1"})
    assert result.exit_code == 0
    # CI forces colour and Rich may wrap or box the help: compare the text alone.
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    text = re.sub(r"[\s\u2500-\u257f]+", "", text)
    assert "build/<sheet>(@<rev>)(_crop-X0-Y0-X1-Y1)(_inline).svg|png" in text


def test_template_command_docs_describe_the_03_behaviour():
    from importlib import resources

    template = resources.files("chemeascode") / "templates" / "project"
    agents = (template / "AGENTS.md").read_text(encoding="utf-8")
    readme = (template / "README.md").read_text(encoding="utf-8")
    assert "one line per change " not in agents and "one line per change\n" not in readme
    assert "one line per changed plant item" in agents and "--flat" in agents
    assert "_crop-X0-Y0-X1-Y1" in agents and "_crop-X0-Y0-X1-Y1" in readme
    assert "instrumentation:" in agents and "at each nozzle" in agents


def test_init_says_settings_need_a_trusted_folder(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path / "p"), "--name", "P"])
    assert result.exit_code == 0
    assert "only once the folder is trusted" in result.output
    assert "--settings .claude/settings.json" in result.output


def test_template_settings_allow_reading_not_rewriting(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path / "p"), "--name", "P"])
    allow = json.loads((tmp_path / "p" / ".claude" / "settings.json").read_text())["permissions"][
        "allow"
    ]
    for wanted in ("ls", "wc", "head", "tail", "sed -n", "cat", "cmp", "git show"):
        assert f"Bash({wanted}:*)" in allow, wanted
    assert not [
        rule
        for rule in allow
        if rule.startswith(("Bash(sed:", "Bash(sed -i", "Bash(cp", "Bash(awk"))
    ]


def test_template_settings_record_each_session(tmp_path: Path):
    """The hooks leave a run record per interactive session (cheme runs, ADR 0029)."""
    runner.invoke(app, ["init", str(tmp_path / "p"), "--name", "P"])
    hooks = json.loads((tmp_path / "p" / ".claude" / "settings.json").read_text())["hooks"]
    commands = {
        event: [h["command"] for entry in entries for h in entry["hooks"]]
        for event, entries in hooks.items()
    }
    assert commands == {
        "SessionStart": ["cheme runs start --hook"],
        "SessionEnd": ["cheme runs record --hook"],
    }


def test_a_control_character_in_a_list_is_a_finding_not_a_crash(plant: Path, monkeypatch):
    """A character YAML does not allow (here BEL, pasted from a spreadsheet) is a yaml.syntax
    error on its line; the other files are still checked, and status does not crash
    (pre-release issue 223)."""
    (plant / "equipment" / "equipment-list.yaml").write_text(
        'equipment:\n  - tag: T4750\n    service: "Feed\x07vessel"\n', encoding="utf-8"
    )
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["validate", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    syntax = [f for f in payload["findings"] if f["rule"] == "yaml.syntax"]
    assert len(syntax) == 1
    assert syntax[0]["file"] == "equipment/equipment-list.yaml" and syntax[0]["line"] == 3
    assert "#x0007" in syntax[0]["message"]
    assert "pid/P-01.xml" in payload["files"]
    status = runner.invoke(app, ["status", "--json", "--no-gates"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)["validation"]["by_rule"]["yaml.syntax"] == 1


@pytest.mark.parametrize(
    ("example", "name"),
    [
        ("process-simulation", "process/flowsheet.yaml"),
        ("process-simulation", "process/materials.yaml"),
        ("process-simulation", "process/simulation.yaml"),
        ("process-shift", "process/reactions.yaml"),
        ("process-shift", "process/catalysts.yaml"),
        ("reaction-evidence-ethyl-acetate", "process/reaction-evidence.yaml"),
    ],
)
def test_a_control_character_in_a_process_file_is_a_finding(tmp_path, monkeypatch, example, name):
    """The process, simulation and evidence loaders report a character YAML does not allow as
    yaml.syntax on its line; status, maturity and impact still run (pre-release issue 223)."""
    root = tmp_path / example
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples" / example, root)
    path = root / name
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    lines.insert(2, "# pasted \x07 here\n")
    path.write_text("".join(lines), encoding="utf-8")
    monkeypatch.chdir(root)
    payload = json.loads(runner.invoke(app, ["validate", "--json"]).stdout)
    syntax = [f for f in payload["findings"] if f["rule"] == "yaml.syntax"]
    assert [(f["file"], f["line"]) for f in syntax] == [(name, 3)]
    assert "#x0007" in syntax[0]["message"]
    for command in (["status", "--json", "--no-gates"], ["maturity", "--json"], ["impact"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, (command, result.output)


def test_a_control_character_in_a_layout_file_is_a_finding():
    from chemeascode.domains.spatial.layout_validate import parse

    findings, model, _ = parse('schema: x\r\nitems:\r\n  - id: "a\x0cb"\r\n', "placement", "f.yaml")
    assert model is None
    assert [(f.rule, f.line) for f in findings] == [("yaml.syntax", 3)]


def test_the_syntax_line_counts_every_yaml_line_break():
    from chemeascode.foundation.yamlsource import syntax_finding

    for text in ("a: 1\nb: 2\nc: \x07\n", "a: 1\rb: 2\rc: \x07", "a: 1\r\nb: 2\u2028c: \x07"):
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as failure:
            assert syntax_finding("f.yaml", failure, text).line == 3, repr(text)
        else:
            raise AssertionError(repr(text))


@pytest.mark.parametrize("command", ["status", "impact", "maturity"])
def test_an_unparsable_plant_yaml_stops_with_one_line(plant: Path, monkeypatch, command):
    """validate reports a plant.yaml that does not parse; the commands that need it whole stop
    with one line and exit 2, without a traceback (pre-release issue 223)."""
    (plant / "plant.yaml").write_text("name: [x\n", encoding="utf-8")
    monkeypatch.chdir(plant)
    validated = runner.invoke(app, ["validate"])
    assert validated.exit_code == 1 and "plant.yaml" in validated.output
    result = runner.invoke(app, [command])
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit)
    lines = result.stderr.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("plant.yaml does not load ("), lines
    assert "Traceback" not in result.output


@pytest.mark.parametrize("value", ["warnings", "warn", "Error"])
def test_validate_fail_on_refuses_an_unknown_level(plant: Path, monkeypatch, value):
    """A misspelt --fail-on is a usage error naming the levels, also on a clean tree
    (pre-release issue 243)."""
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["validate", "--fail-on", value])
    assert result.exit_code == 2
    # unwrap Rich's error box (coloured where the environment forces colour, as in CI)
    message = re.sub(r"[\s│╭╮╰╯─]+", " ", re.sub(r"\x1b\[[0-9;]*m", "", result.output))
    assert f"'{value}' is not one of 'error', 'warning', 'info'" in message
    assert runner.invoke(app, ["validate", "--fail-on", "info"]).exit_code == 1


@pytest.mark.parametrize(
    "name",
    [
        'Acme "Ethanol" Plant',
        "C:\\new plant",
        "Plant: Stage 2",
        "# not a comment",
        "Müller's {plant} [B] & *x",
        "  padded  ",
        "{{cheme_minor}}",
        'a"{{plant_name}}',
    ],
)
def test_init_writes_the_plant_name_exactly(tmp_path: Path, monkeypatch, name):
    """The name is written as a YAML string, whatever characters it holds
    (pre-release issue 227)."""
    root = tmp_path / "p"
    assert runner.invoke(app, ["init", str(root), "--name", name]).exit_code == 0
    assert yaml.safe_load((root / "plant.yaml").read_text(encoding="utf-8"))["name"] == name
    assert (root / "README.md").read_text(encoding="utf-8").startswith(f"# {name}\n")
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output
