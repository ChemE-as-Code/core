"""Level plans and sections of the 3D model (``drawing2d``): the z range of a level, dished
heads in plan, and pipes, ducts and trays drawn by the piece that lies in the cut."""

import dataclasses
import math
import re

import pytest
import yaml

from chemeascode.domains.spatial.drawing2d import Sheet, level_range, render_plan, render_section
from chemeascode.domains.spatial.schemas import StructureList
from chemeascode.domains.spatial.shapes import Dims, body
from chemeascode.domains.spatial.structures import frame_structure

SITE = {"width": 60, "depth": 60}

# -- level_range ------------------------------------------------------------------------------

SPLIT = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [8]
    levels:
      - {id: L1, elevation: 4}
      - {id: L3, elevation: 12, kind: platform, extent: [0, 0, 3, 4]}
      - {id: L3B, elevation: 12, kind: platform, extent: [3, 0, 6, 4]}
      - {id: L4, elevation: 15}
"""


def _structures(svg: str) -> str:
    return re.search(r'<g id="structures">(.*?)</g>\s*<g id="equipment"', svg, re.S).group(1)


def test_levels_at_one_elevation_share_their_range():
    (structure,) = StructureList.model_validate(yaml.safe_load(SPLIT)).structures
    model = {"site": SITE, "structures": [frame_structure(structure, "layout/structures.yaml")]}
    assert level_range(model, "L1") == pytest.approx((3.9, 11.9))
    assert level_range(model, "L3") == pytest.approx((11.9, 14.9))
    assert level_range(model, "S1/L3B") == pytest.approx((11.9, 14.9))
    assert level_range(model, "L4") == pytest.approx((14.9, 18.9))
    # the plan of the first split platform draws its own steel and handrails
    first = _structures(render_plan(model, cut=level_range(model, "L3")))
    second = _structures(render_plan(model, cut=level_range(model, "L3B")))
    assert first == second and first.count("1,0.6") > 0


# -- caps -------------------------------------------------------------------------------------


def _item(kind: str, dims: Dims) -> dict:
    b = body(kind, dims, (20, 20, 0), 0.0, detail=False)
    parts = [{k: v for k, v in dataclasses.asdict(p).items() if v is not None} for p in b.parts()]
    return {"tag": "D-1", "bbox": list(b.bbox()), "parts": parts}


def _drawn_x(svg: str, group: str) -> tuple[float, float]:
    """The x extent (site m) of what a group of the plan draws."""
    g = re.search(rf'<g id="{group}">(.*?)</g>', svg, re.S).group(1)
    s = Sheet((0, 0, 60, 60), "t", {})
    xs = [(float(x) - s.ox) / s.k for x in re.findall(r"(-?\d+\.\d+),-?\d+\.\d+", g)]
    return min(xs), max(xs)


def test_a_horizontal_drum_spans_its_heads_in_plan():
    item = _item("horizontal_vessel", Dims(diameter=2, length=8))
    assert [p["kind"] for p in item["parts"]] == ["cap", "cylinder", "cap"]
    svg = render_plan({"site": SITE, "equipment": [item]})
    x0, x1 = _drawn_x(svg, "equipment-D-1")
    assert (x0, x1) == (pytest.approx(16.0, abs=0.05), pytest.approx(24.0, abs=0.05))
    # the shell and each head (a half ellipse beyond the shell)
    group = re.search(r'<g id="equipment-D-1">(.*?)</g>', svg, re.S).group(1)
    assert group.count("<polygon") == 3


def test_a_head_on_a_vertical_or_inclined_axis_in_plan():
    cap = {"id": "head", "kind": "cap", "radius": 1.0, "depth": 0.5}
    vertical = {**cap, "centre": (20, 20, 8), "axis": (0, 0, 1)}
    item = {"tag": "D-1", "bbox": [19, 19, 0, 21, 21, 8.5], "parts": [vertical]}
    group = re.search(
        r'<g id="equipment-D-1">(.*?)</g>', render_plan({"site": SITE, "equipment": [item]}), re.S
    ).group(1)
    assert group.count("<circle") == 1 and "<polygon" not in group
    # inclined 60 degrees up: the depth foreshortened to 0.25 m in plan
    s = math.sqrt(3) / 2
    inclined = {**cap, "centre": (20, 20, 1), "axis": (0.5, 0, s)}
    item = {"tag": "D-1", "bbox": [19, 19, 0, 21, 21, 2], "parts": [inclined]}
    svg = render_plan({"site": SITE, "equipment": [item]})
    assert _drawn_x(svg, "equipment-D-1") == (
        pytest.approx(20, abs=0.05),
        pytest.approx(20.25, abs=0.05),
    )


# -- runs by the piece in the cut ---------------------------------------------------------------

#: At 1 m along x, up to 20 m, then 30 m north at 20 m.
RISING = [[10, 10, 1], [30, 10, 1], [30, 10, 20], [30, 40, 20]]


def _runs(kind: str, points) -> dict:
    if kind == "pipe":
        return {"pipes": [{"id": "R", "line": "L-100", "od": 0.2, "points": points}]}
    if kind == "duct":
        run = {"id": "R", "system": "supply", "points": points, "width": 0.6, "height": 0.4}
        return {"ducts": [run]}
    return {"trays": [{"id": "R", "system": "power", "points": points, "width": 0.6, "depth": 0.1}]}


def _group(svg: str, kind: str) -> str:
    return re.search(rf'<g id="{kind}-R"[^>]*>(.*?)</g>', svg, re.S).group(1)


def _ys(element: str) -> list[float]:
    """The sheet y (mm) of an element's points."""
    return [float(y) for y in re.findall(r"-?\d+\.\d+,(-?\d+\.\d+)", element)]


@pytest.mark.parametrize("kind", ["pipe", "duct", "tray"])
def test_a_level_plan_draws_the_piece_of_a_run_in_its_range(kind):
    sheet = Sheet((0, 0, 60, 60), "t", {})
    north = sheet.p(30, 40)[1]  # the sheet y of the run at 20 m
    model = {"site": SITE, **_runs(kind, RISING)}
    # z 0 .. 4: the run at 1 m, solid; the 30 m run at 20 m left out
    level = _group(render_plan(model, cut=(0.0, 4.0)), kind)
    assert "dasharray" not in level
    assert min(_ys(level)) > north + 10
    # z 18 .. 22: the run at 20 m solid, the run at 1 m below it dashed
    high = _group(render_plan(model, cut=(18.0, 22.0)), kind)
    solid = [e for e in re.findall(r"<poly[^>]*>", high) if "dasharray" not in e]
    dashed = [e for e in re.findall(r"<poly[^>]*>", high) if "dasharray" in e]
    assert solid and dashed
    assert min(min(_ys(e)) for e in solid) <= north + 1
    assert all(min(_ys(e)) > north + 10 for e in dashed)
    # z 30 .. 34: all of it below
    above = _group(render_plan(model, cut=(30.0, 34.0)), kind)
    assert re.findall(r"<poly[^>]*>", above)
    assert all("dasharray" in e for e in re.findall(r"<poly[^>]*>", above))
    # the plot plan draws all of it solid
    assert "dasharray" not in _group(render_plan(model), kind)


def test_a_level_plan_shows_a_pipe_riser_in_its_range():
    riser = [[10, 10, 1], [10, 10, 20]]
    svg = render_plan({"site": SITE, **_runs("pipe", riser)}, cut=(4.0, 8.0))
    (circle,) = re.findall(r"<circle[^>]*>", _group(svg, "pipe"))  # once, not over its piece below
    assert "dasharray" not in circle
    # wholly below the cut: dashed
    svg = render_plan({"site": SITE, **_runs("pipe", riser)}, cut=(24.0, 28.0))
    (circle,) = re.findall(r"<circle[^>]*>", _group(svg, "pipe"))
    assert "dasharray" in circle


def test_a_level_plan_labels_a_run_on_its_longest_solid_piece():
    # 10 m at 1 m (in the cut), then 40 m at 20 m (above it): the label on the 10 m run
    points = [[10, 10, 1], [20, 10, 1], [20, 10, 20], [20, 50, 20]]
    svg = render_plan({"site": SITE, **_runs("pipe", points)}, cut=(0.0, 4.0))
    sheet = Sheet((0, 0, 60, 60), "t", {})
    label = re.search(r'<text[^>]*x="([\d.]+)" y="([\d.]+)"[^>]*>L-100<', svg)
    x, y = (float(v) for v in label.groups())
    assert x == pytest.approx(sheet.p(15, 0)[0], abs=0.5)
    assert y == pytest.approx(sheet.p(0, 10)[1], abs=3)


@pytest.mark.parametrize("kind", ["pipe", "duct", "tray"])
def test_a_section_draws_a_run_in_its_slab_that_stops_short_of_the_cut(kind):
    # section x = 20, 6 m deep (17 .. 23): runs along x from 21 (inside) and from 24 (outside)
    inside = render_section({"site": SITE, **_runs(kind, [[21, 10, 5], [40, 10, 5]])}, "x", 20.0)
    assert re.search(rf'<g id="{kind}-R"[^>]*>\s*<(circle|polygon)', inside)
    outside = render_section({"site": SITE, **_runs(kind, [[24, 10, 5], [40, 10, 5]])}, "x", 20.0)
    assert f'id="{kind}-R"' not in outside
    # a run that also climbs inside the slab: a band of the piece in the slab
    climbing = render_section({"site": SITE, **_runs(kind, [[21, 10, 5], [27, 10, 11]])}, "x", 20.0)
    assert re.search(rf'<g id="{kind}-R"[^>]*>\s*<poly', climbing)
