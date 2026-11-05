import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from chemeascode.domains.piping.fmt import format_file
from chemeascode.interfaces.api.export_static import (
    NOT_IN_SNAPSHOT,
    SNAPSHOT_SCHEMA,
    ExportError,
    ExportWarning,
    case_insensitive,
    check_output,
    export_static,
    path_matches,
    snapshot_key,
)
from chemeascode.interfaces.api.serve import create_app
from chemeascode.interfaces.cli import app as cli_app
from tests.conftest import git

SHEET = "pid/P-01.xml"
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def committed(plant: Path) -> Path:
    format_file(plant / SHEET)
    # no background auto-gc: it repacks .git/objects while a test compares the file listing
    git(plant, "config", "gc.auto", "0")
    git(plant, "config", "maintenance.auto", "false")
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "initial plant")
    return plant


def read(out: Path, manifest: dict, key: str) -> bytes:
    return (out / "data" / manifest["entries"][key]["file"]).read_bytes()


def test_snapshot_key():
    assert snapshot_key("repo") == "repo"
    assert (
        snapshot_key("/api/pid.svg", {"path": "pid/P-01.xml", "rev": "abc"})
        == "pid.svg?path=pid/P-01.xml"
    )
    assert snapshot_key("log", {"path": None, "limit": 50}) == "log?limit=50"
    assert snapshot_key("layout/plan.svg", {"z": "", "level": "L0"}) == "layout/plan.svg?level=L0"
    assert snapshot_key("streams", {"rev": "x", "case": "design"}) == "streams?case=design"
    assert snapshot_key("/api/estimate/equipment", {"rev": "x"}) == "estimate/equipment"
    # raw values, not URL-encoded: the viewer builds the same string from its query object
    assert snapshot_key("file", {"path": "docs/a b&c.md"}) == "file?path=docs/a b&c.md"


def test_snapshot_answers_like_the_server(committed: Path, tmp_path: Path):
    out = tmp_path / "snap"
    manifest = export_static(committed, out)
    assert manifest["schema"] == SNAPSHOT_SCHEMA
    assert manifest["source"]["commit"] == git(committed, "rev-parse", "HEAD").strip()
    assert manifest["source"]["dirty"] is False
    assert json.loads((out / "manifest.json").read_text()) == manifest

    entries = manifest["entries"]
    for key in (
        "repo",
        "branches",
        "log?limit=50",
        "tree",
        "checks",
        "validate",
        "impact",
        "status",
        f"pid.svg?path={SHEET}",
    ):
        assert key in entries, key
        assert entries[key]["status"] == 200, key
    assert entries[f"pid.svg?path={SHEET}"]["type"] == "image/svg+xml"
    assert not any(key.startswith(("diff", "session", "checks/run")) for key in entries)
    assert entries["interlocks"]["status"] == 200
    # the template's equipment list is empty: nothing to estimate, not exported
    assert "estimate/equipment" not in entries
    assert all((out / "data" / e["file"]).is_file() for e in entries.values())

    server = TestClient(create_app(committed, allowed_hosts=["testserver"]))
    for key, url in [
        ("repo", "/api/repo"),
        ("tree", "/api/tree"),
        (f"pid.svg?path={SHEET}", f"/api/pid.svg?path={SHEET}"),
        ("yaml?path=plant.yaml", "/api/yaml?path=plant.yaml"),
        ("file?path=plant.yaml", "/api/file?path=plant.yaml"),
    ]:
        assert read(out, manifest, key) == server.get(url).content, key


def test_sheet_xml_is_drawn_not_copied(committed: Path, tmp_path: Path):
    manifest = export_static(committed, tmp_path / "snap")
    assert f"file?path={SHEET}" not in manifest["entries"]
    assert f"yaml?path={SHEET}" not in manifest["entries"]


def test_export_of_a_revision(committed: Path, tmp_path: Path):
    first = git(committed, "rev-parse", "HEAD").strip()
    plant_yaml = committed / "plant.yaml"
    plant_yaml.write_text(plant_yaml.read_text().replace("Test plant", "Renamed plant"))
    git(committed, "commit", "-qam", "rename")

    out = tmp_path / "snap"
    manifest = export_static(committed, out, rev=first)
    assert manifest["source"]["commit"] == first
    assert manifest["source"]["rev"] == first
    assert json.loads(read(out, manifest, "repo"))["name"] == "Test plant"
    # validate, impact and status read the working tree only: not in a revision snapshot
    for key in ("validate", "impact", "status"):
        assert key not in manifest["entries"], key
    assert "interlocks" in manifest["entries"]


def test_a_missing_interlock_list_is_recorded_as_404(committed: Path, tmp_path: Path):
    (committed / "control" / "cause-effect.yaml").unlink()
    git(committed, "commit", "-qam", "no interlocks")
    manifest = export_static(committed, tmp_path / "snap")
    assert manifest["entries"]["interlocks"]["status"] == 404


def test_equipment_estimate_is_exported(committed: Path, tmp_path: Path):
    (committed / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n  - {tag: V-1, type: PressureVessel, material: CS,"
        " dimensions: {diameter: 2.0, height: 3.2}}\n",
        encoding="utf-8",
    )
    git(committed, "commit", "-qam", "equipment")
    out = tmp_path / "snap"
    manifest = export_static(committed, out)
    entry = manifest["entries"]["estimate/equipment"]
    assert entry["status"] == 200 and entry["type"] == "application/json"
    server = TestClient(create_app(committed, allowed_hosts=["testserver"]))
    assert (
        read(out, manifest, "estimate/equipment") == server.get("/api/estimate/equipment").content
    )


def test_large_files_are_left_out(committed: Path, tmp_path: Path):
    (committed / "docs").mkdir(exist_ok=True)
    (committed / "docs" / "big.md").write_text("x" * 300_000)
    git(committed, "add", "-A")
    git(committed, "commit", "-qm", "big")
    manifest = export_static(committed, tmp_path / "snap", max_file_bytes=200_000)
    assert {"path": "docs/big.md", "bytes": 300_000} in manifest["skipped"]
    assert "file?path=docs/big.md" not in manifest["entries"]


def test_process_example_has_streams(tmp_path: Path):
    root = tmp_path / "recycle"
    shutil.copytree(EXAMPLES / "process-recycle", root)
    manifest = export_static(root, tmp_path / "snap")
    streams = [key for key in manifest["entries"] if key.split("?")[0] == "streams"]
    assert "streams" in streams
    assert all(manifest["entries"][key]["status"] == 200 for key in streams)
    sheets = json.loads(read(tmp_path / "snap", manifest, "repo"))["sheets"]
    for sheet in sheets:
        assert manifest["entries"][f"pid.svg?path={sheet['file']}"]["status"] == 200


def test_export_is_deterministic(committed: Path, tmp_path: Path):
    a = export_static(committed, tmp_path / "a")
    b = export_static(committed, tmp_path / "b")
    assert a == b
    for entry in a["entries"].values():
        assert (tmp_path / "a" / "data" / entry["file"]).read_bytes() == (
            tmp_path / "b" / "data" / entry["file"]
        ).read_bytes()


def test_cli(committed: Path, tmp_path: Path):
    out = tmp_path / "snap"
    result = CliRunner().invoke(cli_app, ["export-static", str(out), "--repo", str(committed)])
    assert result.exit_code == 0, result.output
    assert "responses written" in result.output
    assert (out / "manifest.json").is_file()


PRIVATE = {
    "PROGRESS.md": "progress\n",
    "AGENTS.md": "agents\n",
    ".claude/skills/x/SKILL.md": "skill\n",
    "reviews/r1.md": "review\n",
    "reviews/deep/r2.yaml": "a: 1\n",
    "docs/keep.md": "public\n",
    "docs/PROGRESS.md": "nested, not matched by the root name\n",
    "docs/.gitattributes": "* text\n",
    "notes/drafts/a.md": "draft\n",
}
GLOBS = [".claude/**", "AGENTS.md", "reviews/**", "PROGRESS.md", "**/.gitattributes"]


@pytest.fixture
def private(committed: Path) -> Path:
    for path, text in PRIVATE.items():
        (committed / path).parent.mkdir(parents=True, exist_ok=True)
        (committed / path).write_text(text)
    git(committed, "add", "-A")
    git(committed, "commit", "-qm", "private files")
    return committed


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("PROGRESS.md", "PROGRESS.md", True),
        ("docs/PROGRESS.md", "PROGRESS.md", False),  # a plain name is the root file
        ("reviews", "reviews/**", True),  # ** matches zero segments: the directory itself
        ("reviews/a/b/c.md", "reviews/**", True),
        ("reviewsX/a.md", "reviews/**", False),
        (".gitattributes", "**/.gitattributes", True),
        ("a/b/.gitattributes", "**/.gitattributes", True),
        ("docs/a.md", "docs/*", True),
        ("docs/sub/a.md", "docs/*", False),  # * stays within a segment
        ("docs/sub/a.md", "docs/**/*.md", True),
        ("docs/a.md", "docs/**/*.md", True),
        ("scripts/agent-run/x/y.py", "scripts/agent-run/**", True),
        ("scripts/build.py", "scripts/agent-run/**", False),
        ("a/x/b", "a/**/b", True),
        ("a/b", "a/**/b", True),
        ("Progress.md", "PROGRESS.md", False),  # case-sensitive, like git paths
    ],
)
def test_path_matches(path: str, pattern: str, expected: bool):
    assert path_matches(path, pattern) is expected


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("Progress.md", "PROGRESS.md", True),
        ("Reviews/a.md", "reviews/**", True),
        ("docs/PROGRESS.md", "progress.md", False),  # still anchored at the root
        ("docs/A.MD", "docs/[a-c].md", True),
    ],
)
def test_path_matches_ignoring_case(path: str, pattern: str, expected: bool):
    assert path_matches(path, pattern, ignore_case=True) is expected


def test_excluded_paths_are_left_out(private: Path, tmp_path: Path):
    out = tmp_path / "snap"
    manifest = export_static(private, out, exclude=[*GLOBS, "AGENTS.md"])
    assert manifest["excluded"] == sorted(set(GLOBS))
    assert json.loads((out / "manifest.json").read_text())["excluded"] == sorted(set(GLOBS))

    tree = {entry["path"] for entry in json.loads(read(out, manifest, "tree"))}
    gone = {"PROGRESS.md", "AGENTS.md", ".claude/skills/x/SKILL.md", "reviews/r1.md"}
    gone |= {"reviews/deep/r2.yaml", "docs/.gitattributes", "reviews", "reviews/deep"}
    gone |= {".claude", ".claude/skills", ".claude/skills/x"}
    assert not tree & gone
    assert {"docs/keep.md", "docs/PROGRESS.md", "plant.yaml", SHEET} <= tree

    keys = set(manifest["entries"])
    for path in gone:
        assert f"file?path={path}" not in keys and f"yaml?path={path}" not in keys
    assert "file?path=docs/keep.md" in keys and "file?path=docs/PROGRESS.md" in keys
    blob = b"".join((out / "data" / e["file"]).read_bytes() for e in manifest["entries"].values())
    assert b"SKILL.md" not in blob and b"reviews/r1.md" not in blob
    validate = json.loads(read(out, manifest, "validate"))
    assert not any(path_matches(f["file"], g) for f in validate["findings"] for g in GLOBS)


def test_pruned_tree_is_serialised_like_the_server(private: Path, tmp_path: Path):
    out = tmp_path / "snap"
    manifest = export_static(private, out, exclude=["docs/nothing/**"])  # matches nothing
    server = TestClient(create_app(private, allowed_hosts=["testserver"]))
    assert read(out, manifest, "tree") == server.get("/api/tree").content


def test_without_exclude_nothing_is_left_out(private: Path, tmp_path: Path):
    manifest = export_static(private, tmp_path / "snap")
    assert manifest["excluded"] == []
    assert "file?path=PROGRESS.md" in manifest["entries"]
    assert "file?path=.claude/skills/x/SKILL.md" in manifest["entries"]
    validate = json.loads(read(tmp_path / "snap", manifest, "validate"))
    assert "reviews/r1.md" in validate["files"]
    assert any(f["file"] == "reviews/r1.md" for f in validate["findings"])  # no front matter


def test_a_directory_left_empty_is_dropped(private: Path, tmp_path: Path):
    out = tmp_path / "snap"
    manifest = export_static(private, out, exclude=["notes/drafts/*"])
    tree = {entry["path"] for entry in json.loads(read(out, manifest, "tree"))}
    assert not {"notes", "notes/drafts", "notes/drafts/a.md"} & tree
    assert "docs" in tree


@pytest.mark.parametrize("glob", ["pid/**", "pid/P-01.xml", "**/*.xml"])
def test_excluding_a_sheet_is_an_error(committed: Path, tmp_path: Path, glob: str):
    out = tmp_path / "snap"
    with pytest.raises(ExportError, match="P-01.xml"):
        export_static(committed, out, exclude=[glob])
    assert not out.exists()


@pytest.mark.parametrize("glob", ["", "/abs/**", "a//b", "../x", "./PROGRESS.md"])
def test_unusable_globs_are_errors(committed: Path, tmp_path: Path, glob: str):
    with pytest.raises(ExportError, match="repo-relative"):
        export_static(committed, tmp_path / "snap", exclude=[glob])


def test_cli_exclude(private: Path, tmp_path: Path):
    out = tmp_path / "snap"
    args = ["export-static", str(out), "--repo", str(private)]
    result = CliRunner().invoke(
        cli_app, [*args, "--exclude", "reviews/**", "--exclude", "PROGRESS.md"]
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["excluded"] == ["PROGRESS.md", "reviews/**"]
    assert "file?path=reviews/r1.md" not in manifest["entries"]

    result = CliRunner().invoke(cli_app, [*args, "--exclude", "pid/**"])
    assert result.exit_code == 2
    assert "sheet" in result.output


def test_status_is_left_out_of_a_snapshot_with_excludes(committed: Path, tmp_path: Path):
    """status summarises review records and sign-offs, which a publication snapshot excludes."""
    plain = export_static(committed, tmp_path / "plain")
    assert "status" in plain["entries"]
    published = export_static(committed, tmp_path / "published", exclude=["reviews/**"])
    assert "status" not in published["entries"]


# -- the output directory --------------------------------------------------------------------------


def _intact(root: Path) -> None:
    assert (root / "plant.yaml").is_file() and (root / ".git").is_dir() and (root / SHEET).is_file()


@pytest.mark.parametrize("where", [".", "..", "pid", "docs/snap", ".git/snap"])
def test_the_repository_is_never_the_output(committed: Path, tmp_path: Path, where: str):
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    with pytest.raises(ExportError, match="plant repository"):
        export_static(committed, committed / where)
    _intact(committed)
    assert sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*")) == before


def test_cli_refuses_the_repository_as_output(committed: Path, monkeypatch):
    monkeypatch.chdir(committed)
    for out in (".", ".."):
        result = CliRunner().invoke(cli_app, ["export-static", out])
        assert result.exit_code == 2, result.output
        assert "plant repository" in result.output
    _intact(committed)


def test_a_snapshot_under_build_is_allowed(committed: Path):
    manifest = export_static(committed, committed / "build" / "snapshot")
    assert (committed / "build" / "snapshot" / "manifest.json").is_file()
    assert "repo" in manifest["entries"]


def test_build_itself_is_not_the_output(committed: Path):
    """The snapshot is staged next to OUT: for build/ that would be the exported working tree."""
    with pytest.raises(ExportError, match="below build/"):
        export_static(committed, committed / "build")
    assert not any(p.name.startswith(".build") for p in committed.iterdir())


def test_the_snapshot_gets_the_mode_of_a_new_directory(committed: Path, tmp_path: Path):
    import stat

    out = tmp_path / "out" / "snap"
    export_static(committed, out)
    (tmp_path / "out" / "new").mkdir()
    mode = stat.S_IMODE((tmp_path / "out" / "new").stat().st_mode)
    assert stat.S_IMODE(out.stat().st_mode) == mode
    assert stat.S_IMODE((out / "data").stat().st_mode) == mode


def test_a_directory_that_is_not_a_snapshot_is_not_replaced(committed: Path, tmp_path: Path):
    other = tmp_path / "work"
    other.mkdir()
    (other / "notes.md").write_text("mine\n")
    result = CliRunner().invoke(cli_app, ["export-static", str(other), "--repo", str(committed)])
    assert result.exit_code == 2, result.output
    assert "not a previous snapshot" in result.output
    assert [p.name for p in other.iterdir()] == ["notes.md"]
    # a snapshot with something else beside it is not replaced either
    export_static(committed, tmp_path / "snap")
    (tmp_path / "snap" / "notes.md").write_text("mine\n")
    with pytest.raises(ExportError, match="not a previous snapshot"):
        export_static(committed, tmp_path / "snap")
    assert (tmp_path / "snap" / "notes.md").is_file()
    # nor a file
    (tmp_path / "file").write_text("x")
    with pytest.raises(ExportError, match="not a directory"):
        export_static(committed, tmp_path / "file")


def test_a_previous_snapshot_and_an_empty_directory_are_replaced(committed: Path, tmp_path: Path):
    out = tmp_path / "out" / "snap"
    out.mkdir(parents=True)
    export_static(committed, out)  # empty: written
    stale = out / "data" / f"{'0' * 20}.json"  # named like a snapshot file, in no manifest
    stale.write_text("{}")
    manifest = export_static(committed, out)  # a previous snapshot: replaced
    assert not stale.exists()
    assert {p.name for p in (out / "data").iterdir()} == {
        e["file"] for e in manifest["entries"].values()
    }
    assert [p.name for p in out.parent.iterdir()] == ["snap"]  # no staging directory left


@pytest.mark.parametrize("planted", ["notes.md", "sub/", "0123456789abcdef0123.json/"])
def test_a_snapshot_with_foreign_data_is_not_replaced(
    committed: Path, tmp_path: Path, planted: str
):
    """data/ of a previous snapshot holds only the files the export names: anything else there
    is not the export's to delete."""
    out = tmp_path / "snap"
    export_static(committed, out)
    target = out / "data" / planted.rstrip("/")
    if planted.endswith("/"):
        target.mkdir()
        (target / "mine.md").write_text("mine\n")
    else:
        target.write_text("mine\n")
    with pytest.raises(ExportError, match="not a previous snapshot"):
        export_static(committed, out)
    assert target.exists()


def test_a_snapshot_with_symlinked_data_is_not_replaced(committed: Path, tmp_path: Path):
    out = tmp_path / "snap"
    export_static(committed, out)
    elsewhere = tmp_path / "elsewhere"
    (out / "data").rename(elsewhere)
    try:
        (out / "data").symlink_to(elsewhere, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks need privileges here")
    with pytest.raises(ExportError, match="not a previous snapshot"):
        export_static(committed, out)
    assert any(elsewhere.iterdir())


@pytest.mark.parametrize("where", ["{ROOT}", "{ROOT}/PID", "{ROOT}/Build", "{ROOT}/docs/Snap"])
def test_case_variants_of_the_repository_are_refused(committed: Path, where: str):
    """On a case-insensitive filesystem Plant/PID is plant/pid."""
    out = Path(where.replace("{ROOT}", str(committed.parent / committed.name.upper())))
    with pytest.raises(ExportError, match="plant repository"):
        check_output(out, committed, ignore_case=True)
    check_output(committed.parent / committed.name.upper() / "BUILD" / "snap", committed, True)


def test_a_previous_snapshot_that_cannot_be_removed_is_a_warning(
    committed: Path, tmp_path: Path, monkeypatch
):
    """Once the new snapshot is in place the export succeeded: a leftover is a warning."""
    import chemeascode.interfaces.api.export_static as module

    out = tmp_path / "out" / "snap"
    export_static(committed, out)
    rmtree = shutil.rmtree

    def failing(path, *args, **kwargs):
        if str(path).endswith(".old"):
            raise PermissionError(13, "Permission denied")
        return rmtree(path, *args, **kwargs)

    monkeypatch.setattr(module.shutil, "rmtree", failing)
    with pytest.warns(ExportWarning, match="could not be removed"):
        manifest = export_static(committed, out)
    assert json.loads((out / "manifest.json").read_text()) == manifest
    result = CliRunner().invoke(cli_app, ["export-static", str(out), "--repo", str(committed)])
    assert result.exit_code == 0, result.output
    assert "warning: the snapshot is in place" in result.output


def test_a_failed_export_keeps_the_previous_snapshot(committed: Path, tmp_path: Path, monkeypatch):
    import chemeascode.interfaces.api.export_static as module

    out = tmp_path / "out" / "snap"
    before = export_static(committed, out)

    def fail(*_: object) -> None:
        raise RuntimeError("export failed")

    monkeypatch.setattr(module, "_export", fail)
    with pytest.raises(RuntimeError):
        export_static(committed, out)
    assert json.loads((out / "manifest.json").read_text()) == before
    assert [p.name for p in out.parent.iterdir()] == ["snap"]


# -- answers built from excluded files are withheld ------------------------------------------------


def _withheld(manifest: dict) -> dict[str, str]:
    return {w["endpoint"]: w["reason"] for w in manifest["withheld"]}


def test_excluding_the_equipment_list_withholds_the_estimate(committed: Path, tmp_path: Path):
    (committed / "equipment" / "equipment-list.yaml").write_text(
        "equipment:\n  - {tag: V-1, type: PressureVessel, material: CS,"
        " dimensions: {diameter: 2.0, height: 3.2}}\n",
        encoding="utf-8",
    )
    git(committed, "commit", "-qam", "equipment")
    out = tmp_path / "snap"
    manifest = export_static(committed, out, exclude=["equipment/**"])
    assert "estimate/equipment" not in manifest["entries"]
    assert _withheld(manifest)["estimate/equipment"] == (
        "built from files matching --exclude equipment/**"
    )
    blob = b"".join((out / "data" / e["file"]).read_bytes() for e in manifest["entries"].values())
    assert b"PressureVessel" not in blob
    assert manifest["entries"]["repo"]["status"] == 200  # kept: it says only what exists


def test_excluding_the_tea_premises_withholds_the_tea(tmp_path: Path):
    from tests.test_assessment_tea import premises
    from tests.test_assessment_tea import write as write_tea

    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLES / "process-blocks", root)
    write_tea(root, premises())
    plain = export_static(root, tmp_path / "plain")
    assert plain["entries"]["tea"]["status"] == 200 and plain["withheld"] == []

    manifest = export_static(root, tmp_path / "snap", exclude=["estimate/tea.yaml"])
    assert "tea" not in manifest["entries"]
    assert _withheld(manifest) == {"tea": "built from files matching --exclude estimate/tea.yaml"}
    assert manifest["entries"]["streams"]["status"] == 200  # not built from the premises


SEPARATION_DRAWINGS = {"pid.svg?path=process/BFD.xml", "pid.svg?path=process/PFD.xml"}
SEPARATION_ANSWERS = {
    "estimate/equipment",
    "interlocks",
    "library",
    "simulation",
    "simulation?case=design",
    "streams",
    "streams?case=design",
} | SEPARATION_DRAWINGS


@pytest.mark.parametrize(
    ("glob", "withheld"),
    [
        ("equipment/equipment-list.yaml", {"estimate/equipment", "streams", "streams?case=design"}),
        ("control/instrument-list.yaml", {"streams", "streams?case=design"}),
        ("control/cause-effect.yaml", {"interlocks"}),
        ("process/simulation.yaml", SEPARATION_ANSWERS - {"interlocks"} - SEPARATION_DRAWINGS),
        ("process/materials.yaml", SEPARATION_ANSWERS - {"interlocks"}),
        ("process/flowsheet.yaml", SEPARATION_ANSWERS - {"interlocks"}),
        ("nothing/**", set()),
    ],
)
def test_each_answer_is_withheld_with_its_inputs(tmp_path: Path, glob: str, withheld: set[str]):
    root = tmp_path / "separation"
    shutil.copytree(EXAMPLES / "process-separation", root)
    manifest = export_static(root, tmp_path / "snap", exclude=[glob])
    # the answers per case are not even asked for when the answer of the default case is withheld
    assert set(_withheld(manifest)) == {
        key for key in withheld if "?" not in key or key in SEPARATION_DRAWINGS
    }
    assert not withheld & set(manifest["entries"])
    assert SEPARATION_ANSWERS - withheld <= set(manifest["entries"])


def test_excluding_the_flowsheet_withholds_the_bfd_and_pfd_drawings(tmp_path: Path):
    """The BFD and PFD are generated from the flowsheet: their drawings show its blocks and
    streams, so they are not published when it is excluded."""
    root = tmp_path / "separation"
    shutil.copytree(EXAMPLES / "process-separation", root)
    out = tmp_path / "snap"
    args = ["export-static", str(out), "--repo", str(root), "--exclude", "process/flowsheet.yaml"]
    result = CliRunner().invoke(cli_app, args)
    assert result.exit_code == 0, result.output
    assert "withheld: pid.svg?path=process/BFD.xml" in result.output
    manifest = json.loads((out / "manifest.json").read_text())
    reason = "a BFD/PFD drawing generated from files matching --exclude process/flowsheet.yaml"
    for key in SEPARATION_DRAWINGS:
        assert key not in manifest["entries"]
        assert _withheld(manifest)[key] == reason
    server = TestClient(create_app(root, allowed_hosts=["testserver"]))
    drawing = server.get("/api/pid.svg", params={"path": "process/BFD.xml"}).content
    assert not [p for p in (out / "data").iterdir() if p.read_bytes() == drawing]
    # the sheets are still listed (by plant.yaml), only their drawings are withheld
    assert "process/BFD.xml" in {e["path"] for e in json.loads(read(out, manifest, "tree"))}


def test_globs_ignore_case_on_a_case_insensitive_filesystem(
    private: Path, tmp_path: Path, monkeypatch
):
    """APFS and NTFS ignore case: there progress.md names PROGRESS.md and must exclude it."""
    import chemeascode.interfaces.api.export_static as module

    monkeypatch.setattr(module, "case_insensitive", lambda _: True)
    out = tmp_path / "snap"
    manifest = export_static(private, out, exclude=["progress.md", "REVIEWS/**"])
    assert manifest["excluded"] == ["REVIEWS/**", "progress.md"]  # as given
    tree = {entry["path"] for entry in json.loads(read(out, manifest, "tree"))}
    assert not {"PROGRESS.md", "reviews", "reviews/r1.md"} & tree
    assert "file?path=PROGRESS.md" not in manifest["entries"]
    assert "docs/PROGRESS.md" in tree  # still anchored at the root
    with pytest.raises(ExportError, match="P-01.xml"):
        export_static(private, tmp_path / "other", exclude=["PID/**"])


def test_case_insensitive_matches_the_filesystem(tmp_path: Path):
    (tmp_path / "probe.txt").write_text("x")
    assert case_insensitive(tmp_path) is (tmp_path / "PROBE.TXT").exists()
    empty = tmp_path / "123"  # no entry, no letters: probed through its parents
    empty.mkdir()
    assert case_insensitive(empty) is (tmp_path / "PROBE.TXT").exists()


def test_an_excluded_status_file_withholds_the_checks(committed: Path, tmp_path: Path):
    (committed / "checks" / "status.json").write_text('{"checks": [{"id": "secret"}]}')
    manifest = export_static(committed, tmp_path / "snap", exclude=["checks/status.json"])
    assert "checks" not in manifest["entries"] and "checks" in _withheld(manifest)


def test_checks_name_no_excluded_review(committed: Path, tmp_path: Path):
    """A sign-off's review record is excluded: the results stay, its path does not."""
    review = "reviews/2026-10-30-design.md"
    signed = {
        "id": "design-review",
        "status": "pass",
        "detail": f"{review}: agent review of 1f4df32436f4 (agent-reviewed only)",
        "evidence": {"path": review, "reviewer_kind": "agent"},
    }
    other = {"id": "docs", "status": "pass", "detail": "see docs/keep.md and PROGRESS.md."}
    status = {
        "stages": {"basic": {"stage": "basic", "review": review, "checks": [signed, other]}},
        "checks": [signed, other],
    }
    (committed / "checks" / "status.json").write_text(json.dumps(status))
    out = tmp_path / "snap"
    manifest = export_static(committed, out, exclude=["reviews/**", "PROGRESS.md"])
    checks = json.loads(read(out, manifest, "checks"))
    assert review.encode() not in read(out, manifest, "checks")
    first = checks["checks"][0]
    assert first["status"] == "pass"
    assert (
        first["detail"] == f"{NOT_IN_SNAPSHOT}: agent review of 1f4df32436f4 (agent-reviewed only)"
    )
    assert first["evidence"] == {"reviewer_kind": "agent"}
    assert checks["checks"][1]["detail"] == f"see docs/keep.md and {NOT_IN_SNAPSHOT}."
    assert checks["stages"]["basic"]["review"] is None
    assert checks["stages"]["basic"]["checks"] == checks["checks"]

    plain = export_static(committed, tmp_path / "plain")
    assert json.loads(read(tmp_path / "plain", plain, "checks")) == status


def test_a_failed_move_restores_the_previous_snapshot(committed: Path, tmp_path: Path, monkeypatch):
    out = tmp_path / "out" / "snap"
    before = export_static(committed, out)
    rename = Path.rename

    def failing(self: Path, target):
        if Path(target) == out and not self.name.endswith(".old"):
            raise OSError(28, "No space left on device")
        return rename(self, target)

    monkeypatch.setattr(Path, "rename", failing)
    with pytest.raises(ExportError, match="cannot move the snapshot into place"):
        export_static(committed, out)
    monkeypatch.undo()
    assert json.loads((out / "manifest.json").read_text()) == before
    assert [p.name for p in out.parent.iterdir()] == ["snap"]
