"""Line routes over racks, declared separations and ``show --layout``."""

import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.spatial.layout_distances import (
    RackNetwork,
    polygon_distance,
    shape_distance,
)
from chemeascode.domains.spatial.layout_validate import (
    box_polygon,
    building_corners,
    check_layout,
    strip,
)
from chemeascode.domains.spatial.schemas import Building, SitePlan
from chemeascode.interfaces.cli import app
from chemeascode.schemas import EquipmentList, LineList
from tests.conftest import git

runner = CliRunner()

SITE = """\
site: {width: 300, depth: 200}
areas:
  - {id: A1, box: [0, 0, 100, 100]}
  - {id: A2, box: [100, 0, 200, 100]}
  - {id: V1, box: [250, 150, 290, 190], kind: reserved}
"""
RACKS = """\
racks:
  - {id: PR1, points: [[10, 50], [190, 50]], width: 6, levels: [6, 8]}
"""
PLACEMENT = """\
equipment:
  - {tag: K-1, position: [20, 40, 0], size: [4, 4, 4]}
  - {tag: K-2, position: [180, 40, 0], size: [4, 4, 4]}
  - {tag: K-3, position: [30, 40, 0], size: [2, 2, 2]}
  - {tag: S-1, position: [270, 170, 0], shape: vertical_cylinder, size: {diameter: 2, height: 6}}
  - {tag: C-1, position: [60, 80, 0], shape: vertical_cylinder, size: {diameter: 4, height: 50}}
"""
EQUIPMENT = "equipment:\n" + "".join(
    f"  - {{tag: {t}, type: Vessel}}\n" for t in ("K-1", "K-2", "K-3", "S-1", "C-1", "P-9")
)


def run(
    lines: str,
    site: str = SITE + RACKS,
    placement: str = PLACEMENT,
    drawn_tags: set[str] | None = None,
):
    texts = {"site_plan": ("layout/site-plan.yaml", site)}
    texts["placement"] = ("layout/equipment-placement.yaml", placement)
    listed = EquipmentList.model_validate(yaml.safe_load(EQUIPMENT))
    line_list = LineList.model_validate(yaml.safe_load(lines))
    return check_layout(
        texts,
        listed,
        ("equipment/equipment-list.yaml", EQUIPMENT),
        lines=line_list,
        lines_text=("piping/line-list.yaml", lines),
        drawn_tags=drawn_tags,
    )


def found(layout, rule):
    return [f for f in layout.findings if f.rule == f"cheme.layout-{rule}"]


# -- geometry ---------------------------------------------------------------------------------


def test_point_polygon_and_polygon_strip_distances():
    square = box_polygon((0, 0, 10, 10))
    assert polygon_distance([(13, 14)], square) == pytest.approx(5.0)
    assert polygon_distance([(5, 5)], square) == 0.0
    road = strip([(20, -10), (20, 30)], 4)  # x 18..22
    assert shape_distance([square], road) == pytest.approx(8.0)
    diagonal = strip([(20, 0), (40, 20)], 2)
    assert shape_distance([square], diagonal) == pytest.approx(10 - 1 / math.sqrt(2) + 0, abs=0.75)
    assert shape_distance([square], strip([(5, -5), (5, 15)], 2)) == 0.0


def test_rotated_building_distance():
    building = Building(id="B", origin=(10, 0), width=20, depth=4, rotation_deg=90)
    corners = building_corners(building)  # x 6..10, y 0..20
    assert polygon_distance([(0, 10)], corners) == pytest.approx(6.0)


# -- routes ---------------------------------------------------------------------------------


def test_same_area_short_line_needs_no_rack():
    layout = run("lines:\n  - {number: L1, from: K-1, to: K-3}\n")
    assert not found(layout, "line-route") and not found(layout, "line-length")
    assert layout.lines[0].distance == pytest.approx(7.0)


def test_line_across_areas_on_a_rack():
    layout = run("lines:\n  - {number: L1, from: K-1/N1, to: K-2}\n")
    assert not found(layout, "line-route")
    info = found(layout, "line-length")
    assert info and info[0].level == "info" and "along racks PR1" in info[0].message
    route = layout.lines[0]
    assert route.racks == ["PR1"] and route.length_est == pytest.approx(176, abs=4)
    assert route.as_dict()["finding"] == "cheme.layout-line-length"


def test_connected_racks_and_a_missing_rack():
    lines = "lines:\n  - {number: V1, from: K-2, to: S-1}\n"
    layout = run(lines)
    warning = found(layout, "line-route")
    assert warning and warning[0].level == "warning"
    assert warning[0].file == "piping/line-list.yaml" and warning[0].line == 2
    assert "nearest rack to S-1 is PR1" in warning[0].message
    connected = RACKS + "  - {id: PR2, points: [[190, 50], [265, 160]], width: 3, levels: [6]}\n"
    layout = run(lines, site=SITE + connected)
    assert not found(layout, "line-route")
    assert "PR2" in layout.lines[0].racks
    apart = RACKS + "  - {id: PR2, points: [[230, 100], [265, 160]], width: 3, levels: [6]}\n"
    layout = run(lines, site=SITE + apart)
    assert "are not connected" in found(layout, "line-route")[0].message
    layout = run(lines, site=SITE)
    assert "no racks" in found(layout, "line-route")[0].message


def test_line_to_line_end_and_area_end():
    lines = (
        "lines:\n"
        "  - {number: L1, from: K-1, to: K-2}\n"
        "  - {number: L2, from: L1, to: X-9, to_area: V1}\n"
    )
    layout = run(lines)
    route = found(layout, "line-route")
    assert route and route[0].ids == ["L2"] and "area V1" in route[0].message
    assert layout.lines[1].from_point is not None


def test_unplaced_end_is_info_only_for_listed_tags():
    layout = run(
        "lines:\n  - {number: L1, from: K-1, to: P-9}\n  - {number: L2, from: K-1, to: BL}\n"
    )
    unrouted = found(layout, "line-unrouted")
    assert [f.ids for f in unrouted] == [["L1"]] and unrouted[0].level == "info"


def test_unplaced_end_drawn_on_a_sheet_is_info_without_the_piping_items_list():
    lines = "lines:\n  - {number: VNT-1, from: K-2, to: S-9}\n  - {number: L2, from: K-1, to: BL}\n"
    assert not found(run(lines), "line-unrouted")
    unrouted = found(run(lines, drawn_tags={"S-9"}), "line-unrouted")
    assert [f.ids for f in unrouted] == [["VNT-1"]]
    assert "S-9 is not placed" in unrouted[0].message


def test_an_end_further_from_a_rack_than_the_unsupported_length_is_not_carried():
    """The run from an end to the rack is unsupported: the reach defaults to the 30 m limit."""
    placement = PLACEMENT + "  - {tag: K-4, position: [150, 12, 0], size: [4, 4, 4]}\n"
    lines = "lines:\n  - {number: L1, from: K-1, to: K-4}\n"  # K-4 36 m from PR1
    warning = found(run(lines, placement=placement), "line-route")
    assert warning and "nearest rack to K-4 is PR1, 36 m away (reach 30 m)" in warning[0].message
    site = SITE.replace(
        "site: {width: 300, depth: 200}", "site: {width: 300, depth: 200}\nrack_reach: 40"
    )
    layout = run(lines, site=site + RACKS, placement=placement)
    assert not found(layout, "line-route") and found(layout, "line-length")
    longer = SITE.replace(
        "site: {width: 300, depth: 200}",
        "site: {width: 300, depth: 200}\nmax_unsupported_length: 40",
    )
    layout = run(lines, site=longer + RACKS, placement=placement)
    assert not found(layout, "line-route")


def test_max_unsupported_length_from_the_site_plan():
    lines = "lines:\n  - {number: L1, from: K-1, to: C-1}\n"  # same area, about 37 m
    assert found(run(lines), "line-length")
    site = SITE.replace(
        "site: {width: 300, depth: 200}",
        "site: {width: 300, depth: 200}\nmax_unsupported_length: 60",
    )
    assert not found(run(lines, site=site + RACKS), "line-length")


def rack(id_, *points, width=4.0):
    return SimpleNamespace(id=id_, points=[list(p) for p in points], width=width, levels=[6])


def test_racks_crossing_mid_segment_join_at_the_crossing():
    # pre-release issue 192: no vertex of either rack is near the crossing
    network = RackNetwork([rack("PR-A", (0, 20), (40, 20)), rack("PR-B", (20, 0), (20, 40))])
    assert network.joints == [("PR-A", 20.0, "PR-B", 20.0, 0.0)]
    assert network.path_length("PR-A", 20.0, "PR-B", 20.0) == pytest.approx(0.0)
    assert network.path_length("PR-A", 25.0, "PR-B", 25.0) == pytest.approx(10.0)
    assert network.path("PR-A", 25.0, "PR-B", 25.0) == [
        ("PR-A", [(25.0, 20.0), (20.0, 20.0)]),
        ("PR-B", [(20.0, 20.0), (20.0, 25.0)]),
    ]
    # a rack crossing another twice is joined at both crossings
    loop = rack("PR-C", (10, 10), (10, 30), (30, 30), (30, 10))
    twice = RackNetwork([rack("PR-A", (0, 20), (40, 20)), loop])
    assert [(j[1], j[3], j[4]) for j in twice.joints] == [(10.0, 10.0, 0.0), (30.0, 50.0, 0.0)]
    assert twice.path_length("PR-C", 0.0, "PR-C", 60.0) == pytest.approx(40.0)


def test_t_junctions_and_corners_still_join_where_the_racks_meet():
    tee = RackNetwork([rack("PR-A", (0, 20), (40, 20)), rack("PR-B", (25, 20), (25, 50))])
    assert tee.joints == [("PR-A", 25.0, "PR-B", 0.0, 0.0)]
    corner = RackNetwork([rack("PR-A", (0, 20), (40, 20)), rack("PR-B", (40, 20), (40, 50))])
    assert corner.joints == [("PR-A", 40.0, "PR-B", 0.0, 0.0)]
    # a branch ending at the edge of the main rack's strip, short of its centreline
    edge = RackNetwork([rack("PR-A", (0, 20), (40, 20)), rack("PR-B", (25, 22), (25, 50))])
    assert edge.joints == [("PR-A", 25.0, "PR-B", 0.0, 2.0)]


def test_a_rack_touching_another_and_crossing_it_elsewhere_is_joined_at_both():
    main = rack("PR-A", (0, 0), (100, 0))
    # a loop rack starting on PR-A's strip edge at x 20 and crossing PR-A at x 80
    loop = RackNetwork([main, rack("PR-B", (20, 2), (20, 30), (80, 30), (80, -10))])
    assert loop.joints == [("PR-A", 80.0, "PR-B", 118.0, 0.0), ("PR-A", 20.0, "PR-B", 0.0, 2.0)]
    assert loop.path_length("PR-A", 20.0, "PR-B", 0.0) == pytest.approx(2.0)  # not 178 m
    # side by side along PR-A from x 0, then crossing it past x 80
    beside = RackNetwork([main, rack("PR-B", (0, 3), (80, 3), (90, -10))])
    assert len(beside.joints) == 2
    assert beside.path_length("PR-A", 0.0, "PR-B", 0.0) == pytest.approx(3.0)  # not 166 m


def test_line_length_over_crossing_racks_turns_at_the_crossing():
    site = """\
site: {width: 300, depth: 300}
racks:
  - {id: PR-A, points: [[50, 100], [150, 100]], width: 6, levels: [6]}
  - {id: PR-B, points: [[100, 50], [100, 150]], width: 6, levels: [6]}
"""
    placement = """\
equipment:
  - {tag: K-1, position: [60, 105, 0], size: [2, 2, 2]}
  - {tag: K-2, position: [105, 145, 0], size: [2, 2, 2]}
"""
    layout = run("lines:\n  - {number: L1, from: K-1, to: K-2}\n", site, placement)
    # 4 m onto PR-A, 40 m to the crossing, 45 m along PR-B, 4 m off it (was 111 m)
    assert layout.lines[0].length_est == pytest.approx(93, abs=1)


def test_a_zero_length_rack_or_road_is_a_schema_error_not_a_crash():
    # pre-release issue 236
    for kind in ("racks", "roads"):
        extra = ", levels: [6]" if kind == "racks" else ""
        site = (
            "site: {width: 300, depth: 300}\n"
            f"{kind}:\n"
            f"  - {{id: X-1, points: [[50, 100], [150, 100]], width: 6{extra}}}\n"
            f"  - {{id: X-2, points: [[20, 20], [20, 20]], width: 6{extra}}}\n"
        )
        layout = run("lines:\n  - {number: L1, from: K-1, to: K-2}\n", site)
        (error,) = [f for f in layout.findings if f.rule == "yaml.schema"]
        assert error.line == 4 and "points 1 and 2 are the same (20, 20)" in error.message
        assert not layout.ruled
    with pytest.raises(ValueError, match="points 2 and 3 are the same"):
        SitePlan.model_validate(
            {
                "site": {"width": 50, "depth": 50},
                "racks": [{"id": "R", "points": [[0, 0], [10, 0], [10, 0], [10, 9]], "width": 3}],
            }
        )
    # the geometry does not fail on such a rack either, should one get past the schema
    network = RackNetwork([rack("PR-A", (0, 20), (40, 20)), rack("PR-Z", (5, 5), (5, 5))])
    assert network.joints == [] and network.path_length("PR-A", 0.0, "PR-Z", 0.0) is None
    assert shape_distance([], [box_polygon((0, 0, 1, 1))]) == math.inf


# -- separations ------------------------------------------------------------------------------


def sep(*rows: str) -> str:
    return SITE + RACKS + "separations:\n" + "".join(f"  - {row}\n" for row in rows)


def test_separation_by_height_factor():
    layout = run(
        "lines: []\n",
        site=sep(
            "{from: C-1, to: K-3, min_factor_of_height: 1, reason: toppling, basis: D-026}",
            "{from: C-1, to: K-1, min_factor_of_height: 1.2, measure: centre}",
            "{from: C-1, to: K-3, min_factor_of_height: 0.5, height_of: to}",
        ),
    )
    messages = [f.message for f in found(layout, "separation")]
    assert messages == [
        # measured from the round C-1 (D 4 m), not from the square around it
        "C-1 to K-3: 46.6 m < 50.0 m (1 x height 50 m; D-026; toppling)",
        "C-1 to K-1: 56.6 m < 60.0 m (1.2 x height 50 m)",
    ]
    assert found(layout, "separation")[0].line == 9


def test_separation_min_m_boundary_road_rack_and_unknown_ids():
    layout = run(
        "lines: []\n",
        site=sep(
            "{from: K-1, to: site-boundary, min_m: 20}",
            "{from: K-1, to: PR1, min_m: 5}",
            "{from: K-1, to: NOPE, min_m: 5}",
            "{from: K-1, to: K-2, min_m: 5}",
        ),
    )
    messages = [f.message for f in found(layout, "separation")]
    assert any(m.startswith("K-1 to site-boundary: 18.0 m < 20.0 m") for m in messages)
    assert any(m.startswith("K-1 to PR1: 5.0 m") for m in messages) is False
    assert any("names NOPE" in m for m in messages)
    assert len(messages) == 2


def test_separation_schema():
    result = runner.invoke(app, ["schema", "site-plan"])
    assert "separations" in result.output and "max_unsupported_length" in result.output
    with pytest.raises(ValueError, match="exactly one"):
        from chemeascode.domains.spatial.schemas import Separation

        Separation.model_validate({"from": "a", "to": "b"})


# -- show --layout and the API ----------------------------------------------------------------


def write_layout(root: Path) -> None:
    (root / "layout" / "site-plan.yaml").write_text(SITE + RACKS)
    (root / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    (root / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)
    (root / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: L1, from: K-1, to: K-2}\n  - {number: V1, from: K-2, to: S-1}\n"
        "  - {number: R1, from: K-1, to: SV 104.01}\n"  # a safety valve drawn on P-01 only
    )


def test_show_layout(plant: Path, monkeypatch):
    monkeypatch.chdir(plant)
    write_layout(plant)
    result = runner.invoke(app, ["show", "K-1", "--layout"])
    assert result.exit_code == 0, result.output
    assert "nearest items: K-3 7.0 m (centres 10.0 m)" in result.output
    assert "racks: PR1" in result.output and "site boundary: 18.0 m" in result.output
    assert runner.invoke(app, ["show", "NOPE", "--layout"]).exit_code == 1


def test_api_layout_lines(plant: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    write_layout(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "layout")
    data = TestClient(create_app(plant, None, allowed_hosts=["testserver"])).get("/api/layout")
    lines = {line["number"]: line for line in data.json()["lines"]}
    assert lines["L1"]["racks"] == ["PR1"] and lines["L1"]["length_est"] > 150
    assert lines["V1"]["finding"] == "cheme.layout-line-route"
    assert lines["R1"]["finding"] == "cheme.layout-line-unrouted"
    assert set(lines["V1"]) == {
        "number",
        "from",
        "to",
        "from_point",
        "to_point",
        "distance",
        "length_est",
        "racks",
        "finding",
    }


def test_validate_reports_an_unplaced_drawn_end(plant: Path, monkeypatch):
    import json

    monkeypatch.chdir(plant)
    write_layout(plant)
    result = runner.invoke(app, ["validate", "--json"])
    unrouted = [
        f
        for f in json.loads(result.output)["findings"]
        if f["rule"] == "cheme.layout-line-unrouted"
    ]
    assert [f["ids"] for f in unrouted] == [["R1"]]
