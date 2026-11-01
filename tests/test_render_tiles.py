"""``cheme render --tiles`` and ``--findings``."""

import json
from pathlib import Path

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.piping.render import Crop, parse_grid, render_tiles, sheet_box, tile_boxes
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()


def test_tile_boxes_overlap_and_cover_the_sheet():
    tiles = tile_boxes(420, 297, 4, 3)
    assert [name for name, _ in tiles] == [f"{r}{c}" for r in "ABC" for c in range(1, 5)]
    boxes = dict(tiles)
    assert boxes["A1"].x0 == 0 and boxes["A1"].y0 == 0
    assert boxes["C4"].x1 == 420 and boxes["C4"].y1 == 297
    # Neighbours overlap by about 10 % of a tile.
    overlap = boxes["A1"].x1 - boxes["A2"].x0
    assert overlap == pytest.approx(0.1 * boxes["A1"].width, abs=0.02)
    overlap = boxes["A1"].y1 - boxes["B1"].y0
    assert overlap == pytest.approx(0.1 * boxes["A1"].height, abs=0.02)
    # Every point of the sheet is in a tile.
    for x in range(0, 421, 7):
        for y in range(0, 298, 7):
            assert any(b.x0 <= x <= b.x1 and b.y0 <= y <= b.y1 for b in boxes.values())


def test_tile_boxes_and_sheet_box_follow_a_viewbox_origin():
    """A viewBox starting left of and above the sheet: the tiles span it, not 0..width."""
    svg = etree.fromstring('<svg viewBox="-41.25 -10 461.25 307" width="461.25" height="307"/>')
    sheet = sheet_box(svg)
    assert sheet == Crop(-41.25, -10, 420, 297)
    boxes = dict(tile_boxes(sheet.width, sheet.height, 2, 2, (sheet.x0, sheet.y0)))
    assert (boxes["A1"].x0, boxes["A1"].y0) == (-41.25, -10)
    assert (boxes["B2"].x1, boxes["B2"].y1) == (420, 297)
    assert boxes["A1"].x1 > boxes["A2"].x0 and boxes["A1"].y1 > boxes["B1"].y0
    assert sheet_box(etree.fromstring('<svg width="594" height="420"/>')) == Crop(0, 0, 594, 420)


def test_tiles_of_a_sheet_drawn_left_of_its_frame_cover_it(tmp_path: Path):
    from tests.test_drawing import tag_left_of_the_sheet

    path = tag_left_of_the_sheet(tmp_path)
    tiles = render_tiles(path, tmp_path, "left", "2x1", findings=True)
    assert min(t.crop.x0 for t in tiles) == -30 and max(t.crop.x1 for t in tiles) == 420
    assert [t.name for t in tiles if any("text-outside-frame" in f for f in t.findings)] == ["A1"]


def test_grid_parsing():
    assert parse_grid("4x3", 420, 297, 8) == (4, 3)
    assert parse_grid(" 2 X 2 ", 420, 297, 8) == (2, 2)
    assert parse_grid("auto", 420, 297, 8) == (3, 3)  # 2 mm text at 16 px, tiles <= 1600 px
    for bad in ("4by3", "0x3", "4x", "27x1", ""):
        with pytest.raises(ValueError):
            parse_grid(bad, 420, 297, 8)


def test_render_tiles_png_with_index(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--png", "--tiles", "4x3"])
    assert result.exit_code == 0, result.output
    build = plant / "build"
    tiles = sorted(build.glob("P-01_tile-*.png"))
    assert [p.stem.rsplit("-", 1)[1] for p in tiles] == sorted(
        f"{r}{c}" for r in "ABC" for c in range(1, 5)
    )
    index = json.loads((build / "P-01_tiles.json").read_text())
    assert index["scale"] == 8.0 and len(index["tiles"]) == 12
    entry = next(t for t in index["tiles"] if t["tile"] == "B3")
    assert "tile B3" in result.output and f"--crop {entry['crop']}" in result.output
    box = Crop.parse(entry["crop"])
    union = [
        min(Crop.parse(t["crop"]).x0 for t in index["tiles"]),
        min(Crop.parse(t["crop"]).y0 for t in index["tiles"]),
        max(Crop.parse(t["crop"]).x1 for t in index["tiles"]),
        max(Crop.parse(t["crop"]).y1 for t in index["tiles"]),
    ]
    assert union == [0, 0, 420, 297]
    # --crop with the index's box reproduces the tile.
    again = runner.invoke(
        app,
        [
            "render",
            "pid/P-01.xml",
            "--png",
            "--scale",
            "8",
            "--crop",
            entry["crop"],
            "-o",
            "b3.png",
        ],
    )
    assert again.exit_code == 0, again.output
    assert (plant / "b3.png").read_bytes() == (build / entry["file"]).read_bytes()
    assert box.width > 100


def test_render_tiles_svg_auto_and_rev(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "init")
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--tiles", "auto", "--rev", "HEAD"])
    assert result.exit_code == 0, result.output
    assert len(list((plant / "build").glob("P-01@HEAD_tile-*.svg"))) == 9
    assert (plant / "build" / "P-01@HEAD_tiles.json").is_file()


@pytest.mark.parametrize(
    "args",
    [
        ["--tiles", "4x3", "--crop", "0,0,100,100"],
        ["--tiles", "4by3"],
        ["--tiles", "0x2"],
        ["--tiles", "2x2", "-o", "x.png"],
    ],
)
def test_render_tiles_refuses_bad_use(plant: Path, monkeypatch, args):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--png", *args])
    assert result.exit_code == 2
    assert "--tiles" in result.output


def test_render_findings_marks_them(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--findings"])
    assert result.exit_code == 0, result.output
    svg = etree.parse(str(plant / "build" / "P-01.svg")).getroot()
    marks = [g for g in svg.iter("{*}g") if g.get("class") == "cheme-findings"]
    assert len(marks) == 1
    captions = [t.text for t in marks[0].iter("{*}text")]
    assert "1 line-crossing" in captions or "1 line-through-label" in captions
    assert len(list(marks[0].iter("{*}rect"))) == 5  # the reference's five drawing findings
    png = runner.invoke(app, ["render", "pid/P-01.xml", "--findings", "--png"])
    assert png.exit_code == 0, png.output
    assert (plant / "build" / "P-01.png").read_bytes()[:4] == b"\x89PNG"
    tiles = runner.invoke(app, ["render", "pid/P-01.xml", "--findings", "--tiles", "2x2"])
    assert tiles.exit_code == 0, tiles.output
    index = json.loads((plant / "build" / "P-01_tiles.json").read_text())
    assert sum(len(t["findings"]) for t in index["tiles"]) >= 5


def test_render_findings_show_accepted_ones_in_grey_with_ids(plant: Path, monkeypatch):
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(plant))
    drawn = [f for f in report.findings if f.crop]
    accepted = drawn[0].id
    (plant / "checks" / "checks.yaml").write_text(
        f"checks: []\naccept:\n  - {{id: '{accepted}', reason: 'kept, D-023'}}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--findings"])
    assert result.exit_code == 0, result.output
    svg = etree.parse(str(plant / "build" / "P-01.svg")).getroot()
    [marks] = [g for g in svg.iter("{*}g") if g.get("class") == "cheme-findings"]
    captions = [t.text for t in marks.iter("{*}text")]
    assert sum(c.endswith("(accepted)") for c in captions) == 1
    assert sum(r.get("stroke") == "rgb(130,130,130)" for r in marks.iter("{*}rect")) == 1
    tiles = runner.invoke(app, ["render", "pid/P-01.xml", "--findings", "--tiles", "1x1"])
    assert tiles.exit_code == 0, tiles.output
    assert "(accepted)" in tiles.output
    [tile] = json.loads((plant / "build" / "P-01_tiles.json").read_text())["tiles"]
    ids = {f["id"]: f for f in tile["findings"]}
    assert set(ids) == {f.id for f in drawn}
    assert ids[accepted]["accepted"] == "kept, D-023"


def test_render_tiles_prints_the_command_that_reproduces_a_tile(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    result = runner.invoke(app, ["render", "pid/P-01.xml", "--png", "--tiles", "2x1"])
    assert result.exit_code == 0, result.output
    line = next(x for x in result.output.splitlines() if "tile A1" in x)
    args = line.split("  tile A1  ", 1)[1].split()
    assert args[2:4] == ["--scale", "8"]
    again = runner.invoke(app, ["render", "pid/P-01.xml", "--png", *args, "-o", "a1.png"])
    assert again.exit_code == 0, again.output
    built = plant / "build" / "P-01_tile-A1.png"
    assert (plant / "a1.png").read_bytes() == built.read_bytes()
