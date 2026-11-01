"""The engineered 3D model: router, structures, platforms, zones, model rules, 2D drawings,
``cheme layout route|pin|render|report`` and the drawing endpoints."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.piping.pipe_data import insulation, outside_diameter, parse_dn
from chemeascode.domains.safety.area_classification import classify, substance_class
from chemeascode.domains.spatial.drawing2d import level_range, render_plan, render_section
from chemeascode.domains.spatial.geometry3d import (
    Box,
    Capsule,
    Cylinder,
    dist,
    point_segment,
    polyline_length,
    segment_distance,
)
from chemeascode.domains.spatial.layout_validate import check_layout
from chemeascode.domains.spatial.model import build_model, read, write_model
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.pid_network import End, InlineItem, Segment
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import (
    LayoutModelFile,
    Placement,
    PlacementList,
    Routing,
    SitePlan,
    StructureList,
    ZoneList,
)
from chemeascode.domains.spatial.structures import frame_structure, platforms_for
from chemeascode.domains.spatial.zones import zone_entries
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from tests.conftest import DATA, git

runner = CliRunner()
SHEET = DATA / "layout_nozzles.xml"

# -- a synthetic model: two items, nozzles facing each other ----------------------------------


def nozzle(tag, name, point, direction, segments=("S1",), dn=100):
    return {
        "id": f"{tag}/{name}",
        "refs": {"tag": tag, "dexpi": f"{tag}_{name}", "segments": list(segments)},
        "source": "generated",
        "name": name,
        "dn": dn,
        "point": point,
        "direction": direction,
        "basis": "pid",
    }


def item(tag, centre, size, nozzles=(), family="generic"):
    x, y, z = centre
    dx, dy, dz = size
    return {
        "id": tag,
        "tag": tag,
        "family": family,
        "shape": "box",
        "position": [x, y, z - dz / 2],
        "rotation_deg": 0.0,
        "dimensions": {"length": dx, "width": dy, "height": dz},
        "bbox": [x - dx / 2, y - dy / 2, z - dz / 2, x + dx / 2, y + dy / 2, z + dz / 2],
        "parts": [
            {
                "id": f"{tag}/body",
                "kind": "box",
                "material": "shell",
                "centre": list(centre),
                "size": list(size),
                "rotation_deg": 0.0,
            }
        ],
        "nozzles": list(nozzles),
        "envelopes": [],
    }


def two_items(obstacle=False):
    equipment = [
        item("A", (2, 5, 1), (2, 2, 2), [nozzle("A", "N1", [3, 5, 1], [1, 0, 0])]),
        item("B", (14, 5, 1), (2, 2, 2), [nozzle("B", "N1", [13, 5, 1], [-1, 0, 0])]),
    ]
    if obstacle:
        equipment.append(item("C", (8, 5, 1.5), (2, 4, 3)))
    return {"equipment": equipment, "racks": [], "structures": [], "zones": []}


def seg(sid, line, source, target, items=(), dn=100.0, sheet="pid/P-01.xml"):
    return Segment(sheet, line, line, sid, sid, dn, "Water", source, target, tuple(items))


def nz(tag, name="N1"):
    return End("nozzle", f"{tag}_{name}", None, tag, name, "ProcessNozzle")


def tee(node):
    return End("tee", "T1", node, None, "T1", "PipeTee")


def pipe(result, sid):
    return next(p for p in result.pipes if p["segment"] == sid)


# -- router ----------------------------------------------------------------------------------


def test_router_is_deterministic_and_avoids_obstacles():
    model = two_items(obstacle=True)
    segments = [seg("S1", "L-1", nz("A"), nz("B"))]
    first = route_model(model, segments)
    second = route_model(model, segments)
    assert first.pipes == second.pipes and first.unrouted == []
    route = pipe(first, "S1")
    assert route["points"][0] == [3, 5, 1] or tuple(route["points"][0]) == (3, 5, 1)
    assert tuple(route["points"][-1]) == (13, 5, 1)
    assert route["method"] in ("astar", "astar_coarse")
    # goes around C: longer than the straight 10 m and no clash with it
    assert polyline_length([tuple(p) for p in route["points"]]) > 10.5
    obstacle = Box("C", (8, 5, 1.5), (2, 4, 3))
    r = route["od"] / 2
    points = [tuple(p) for p in route["points"]]
    assert all(
        segment_distance(a, b, obstacle) >= r - 1e-6
        for a, b in zip(points, points[1:], strict=False)
    )
    # every run is orthogonal
    assert all(
        sum(abs(a[i] - b[i]) > 1e-9 for i in range(3)) <= 1
        for a, b in zip(points, points[1:], strict=False)
    )


def test_a_tee_branch_starts_on_its_run_and_inline_items_follow_dexpi_order():
    model = two_items()
    model["equipment"].append(
        item("D", (8, 14, 1), (2, 2, 2), [nozzle("D", "N1", [8, 13, 1], [0, -1, 0], ("S3",))])
    )
    valves = (
        InlineItem("V1", "GateValve", "HV-1", "valve"),
        InlineItem("V2", "CheckValve", None, "check_valve"),
    )
    segments = [
        seg("S1", "L-1", nz("A"), tee(0)),
        seg("S2", "L-1", tee(1), nz("B")),
        seg("S3", "L-1", tee(2), nz("D"), items=valves),
    ]
    result = route_model(model, segments)
    assert result.unrouted == []
    s1, s2, s3 = (pipe(result, s) for s in ("S1", "S2", "S3"))
    assert s1["points"][-1] == s2["points"][0]  # the tee
    run = [tuple(p) for p in s1["points"]] + [tuple(p) for p in s2["points"]]
    start = tuple(s3["points"][0])
    assert min(point_segment(start, a, b)[0] for a, b in zip(run, run[1:], strict=False)) < 1e-6
    v1, v2 = (i for i in result.inline if i["segment"] == "S3")
    assert v1["id"].endswith("/V1") and v1["tag"] == "HV-1" and v2["kind"] == "check_valve"
    along = [tuple(p) for p in s3["points"]]

    def arc(p):
        best, run_, found = 1e9, 0.0, 0.0
        for a, b in zip(along, along[1:], strict=False):
            d, t = point_segment(tuple(p), a, b)
            if d < best:
                best, found = d, run_ + t * dist(a, b)
            run_ += dist(a, b)
        return found

    assert arc(v1["point"]) < arc(v2["point"])  # in DEXPI order from the start


def test_long_routes_take_the_rack_in_lanes_large_lines_outboard():
    plan = SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 40},
            "racks": [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]}],
        }
    )
    model = {
        "equipment": [
            item(
                "A",
                (10, 10, 1),
                (2, 2, 2),
                [
                    nozzle("A", "N1", [10, 11, 1], [0, 1, 0], ("S1",)),
                    nozzle("A", "N2", [9, 11, 1], [0, 1, 0], ("S2",)),
                ],
            ),
            item(
                "B",
                (110, 10, 1),
                (2, 2, 2),
                [
                    nozzle("B", "N1", [110, 11, 1], [0, 1, 0], ("S1",)),
                    nozzle("B", "N2", [109, 11, 1], [0, 1, 0], ("S2",)),
                ],
            ),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    segments = [
        seg("S1", "L-1", nz("A"), nz("B"), dn=300.0),
        seg("S2", "L-2", nz("A", "N2"), nz("B", "N2"), dn=100.0),
    ]
    result = route_model(model, segments, plan=plan)
    big, small = pipe(result, "S1"), pipe(result, "S2")
    assert big["racks"] == ["PR"] and big["tier"] == 6 and big["method"].startswith("rack")
    assert small["racks"] == ["PR"]

    # the run on the rack: a lane across the width, z on top of the tier
    def lane(p):
        pts = [tuple(q) for q in p["points"]]
        a, b = max(zip(pts, pts[1:], strict=False), key=lambda s: abs(s[1][0] - s[0][0]))
        assert a[1] == b[1] and a[2] == b[2] and a[2] > 6  # along the rack, on the tier
        return a[1]

    y_big, y_small = lane(big), lane(small)
    # lanes from the rack's edge on the side the lines come from (south, the right of the
    # rack's drawn direction) inward in routing order (largest first): the big line outboard;
    # each lane's centre on the millimetre, rounded inward (away from the edge or lane it is
    # placed against)
    edge_big = -2 + (big["od"] + 0.1) / 2
    assert y_big - 20 == pytest.approx(edge_big, abs=0.001) and y_big - 20 >= edge_big - 1e-9
    edge_small = y_big - 20 + (big["od"] + 0.1) / 2 + (small["od"] + 0.1) / 2
    assert y_small - 20 == pytest.approx(edge_small, abs=0.001)
    assert y_small - 20 >= edge_small - 1e-9
    fill = {(f["rack"], f["tier"]): f for f in result.stats["rack_fill"]}
    assert fill[("PR", 6.0)]["used_m"] == pytest.approx(big["od"] + small["od"] + 0.2)
    # the top tier is reached from above: the drop onto the lane is vertical, over it
    pts = [tuple(q) for q in big["points"]]
    z = 6 + big["od"] / 2
    start = next(i for i, p in enumerate(pts) if p[2] == pytest.approx(z))
    assert pts[start - 1][:2] == pts[start][:2] and pts[start - 1][2] > z
    assert result.stats["reasons"] == {"rack: longer than local_max_m": 2}


def test_lanes_are_shared_along_the_rack():
    plan = SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 40},
            "racks": [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]}],
        }
    )
    model = {
        "equipment": [
            item("A", (10, 10, 1), (2, 2, 2), [nozzle("A", "N1", [10, 11, 1], [0, 1, 0])]),
            item("B", (40, 10, 1), (2, 2, 2), [nozzle("B", "N1", [40, 11, 1], [0, 1, 0])]),
            item("C", (70, 10, 1), (2, 2, 2), [nozzle("C", "N1", [70, 11, 1], [0, 1, 0], ("S2",))]),
            item(
                "D", (100, 10, 1), (2, 2, 2), [nozzle("D", "N1", [100, 11, 1], [0, 1, 0], ("S2",))]
            ),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    segments = [
        seg("S1", "L-1", nz("A"), nz("B")),
        seg("S2", "L-2", nz("C"), nz("D")),
    ]
    result = route_model(model, segments, plan=plan)
    one, two = pipe(result, "S1"), pipe(result, "S2")
    assert one["racks"] == two["racks"] == ["PR"]
    # the two runs do not overlap along the rack: both take the outboard lane
    (fill,) = result.stats["rack_fill"]
    assert fill["used_m"] == pytest.approx(one["od"] + 0.1)


def plot(**rules):
    """A plot with two areas west and east of a road, a rack along the north."""
    return SitePlan.model_validate(
        {
            "site": {"width": 100, "depth": 60},
            "areas": [
                {"id": "W", "box": [0, 0, 45, 60]},
                {"id": "E", "box": [55, 0, 100, 60]},
            ],
            "roads": [{"id": "R", "points": [[50, 0], [50, 40]], "width": 6}],
            "racks": [{"id": "PR", "points": [[5, 50], [95, 50]], "width": 4, "levels": [6, 8]}],
            **rules,
        }
    )


def test_lines_across_areas_take_the_rack_and_local_lines_the_pipe_way():
    model = {
        "equipment": [
            item("A", (30, 30, 1), (2, 2, 2), [nozzle("A", "N1", [31, 30, 1], [1, 0, 0])]),
            item("B", (70, 30, 1), (2, 2, 2), [nozzle("B", "N1", [69, 30, 1], [-1, 0, 0])]),
            item(
                "C",
                (20, 30, 1),
                (2, 2, 2),
                [nozzle("C", "N1", [20, 31, 1], [0, 1, 0], ("S2",))],
            ),
            item(
                "D",
                (20, 40, 1),
                (2, 2, 2),
                [nozzle("D", "N1", [20, 39, 1], [0, -1, 0], ("S2",))],
            ),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    model["equipment"][2]["family"] = "vessel"
    segments = [seg("S1", "L-1", nz("A"), nz("B")), seg("S2", "L-2", nz("C"), nz("D"))]
    result = route_model(model, segments, plan=plot())
    across, local = pipe(result, "S1"), pipe(result, "S2")
    assert across["racks"] == ["PR"] and across["reason"] == "rack: across areas"
    # the local line runs at the pipe-way elevation (3.5 m to the bottom of the pipe), not at
    # grade
    assert local["reason"] == "local: pipe-way" and "racks" not in local
    r = local["od"] / 2
    runs = [
        (a, b)
        for a, b in zip(local["points"], local["points"][1:], strict=False)
        if abs(a[2] - b[2]) < 1e-9 and dist(tuple(a), tuple(b)) > 2
    ]
    assert runs and all(a[2] == pytest.approx(3.5 + r) for a, _ in runs)
    assert result.stats["reasons"] == {"local: pipe-way": 1, "rack: across areas": 1}


def test_a_pump_run_stays_at_grade_and_a_road_crossing_takes_the_rack():
    pump = item("P", (20, 30, 0.5), (1.5, 1, 1), [nozzle("P", "N1", [20, 30.5, 0.5], [0, 1, 0])])
    pump["family"] = "pump"
    model = {
        "equipment": [
            pump,
            item("V", (20, 38, 1), (2, 2, 2), [nozzle("V", "N1", [20, 37, 1], [0, -1, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    result = route_model(model, [seg("S1", "L-1", nz("P"), nz("V"))], plan=plot())
    run = pipe(result, "S1")
    assert run["reason"] == "local: pump run at grade"
    assert max(p[2] for p in run["points"]) < 3.0
    # a short line whose straight run would cross the road (no areas there) goes over the rack
    model = {
        "equipment": [
            item("A", (46, 20, 1), (1, 1, 2), [nozzle("A", "N1", [46.5, 20, 1], [1, 0, 0])]),
            item("B", (54, 20, 1), (1, 1, 2), [nozzle("B", "N1", [53.5, 20, 1], [-1, 0, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    plan = plot()
    plan.areas.clear()
    result = route_model(model, [seg("S1", "L-1", nz("A"), nz("B"))], plan=plan)
    assert pipe(result, "S1")["reason"] == "rack: crosses a road"


def test_battery_limits_from_rules_rack_ends_and_the_site_edge():
    from chemeascode.domains.piping.schemas.lines import LineList

    model = {
        "equipment": [
            item("A", (30, 30, 1), (2, 2, 2), [nozzle("A", "N1", [30, 31, 1], [0, 1, 0])]),
            item(
                "B",
                (30, 20, 1),
                (2, 2, 2),
                [nozzle("B", "N1", [30, 21, 1], [0, 1, 0], ("S2",))],
            ),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    opc = End("opc_out", "OPC1", None, None, "OPC1", "OffPageConnector")
    segments = [seg("S1", "CW-1", nz("A"), opc), seg("S2", "CWR-1", nz("B", "N1"), opc)]
    lines = LineList.model_validate(
        {
            "lines": [
                {"number": "CW-1", "from": "A", "to": "BL", "nominal_diameter": "DN100"},
                {"number": "CWR-1", "from": "B", "to": "CWR", "fluid": "Water"},
            ]
        }
    )
    routing = Routing.model_validate(
        {"rules": {"battery_limits": [{"lines": ["CW-*"], "point": [0, 50, 6.5]}]}}
    )
    result = route_model(model, segments, lines, routing, plan=plot())
    cw, cwr = pipe(result, "S1"), pipe(result, "S2")
    assert tuple(cw["points"][-1]) == (0, 50, 6.5)  # the declared point
    # CWR-1 has no rule: the free rack end nearest it (west), in its lane on the tier
    end = cwr["points"][-1]
    assert end[0] == pytest.approx(5) and abs(end[1] - 50) <= 2 and end[2] > 6
    assert cwr["reason"] == "rack: battery limit at a rack end"
    assert result.stats["battery_limits"] == {"battery limit rule": 1, "rack end": 1}
    # without racks: the nearest site edge
    plan = plot()
    plan.racks.clear()
    result = route_model(model, segments, lines, routing, plan=plan)
    edge = pipe(result, "S2")["points"][-1]
    assert edge[1] == 0  # the south edge, nearest B
    assert result.stats["battery_limits"]["site edge"] == 1
    # a rule naming a rack end
    routing = Routing.model_validate(
        {"rules": {"battery_limits": [{"fluids": ["water"], "rack": "PR", "rack_end": "end"}]}}
    )
    segments = [
        Segment("pid/P-01.xml", "CWR-1", "CWR-1", "S2", "S2", 100.0, "Water", nz("B"), opc, ())
    ]
    result = route_model(model, segments, lines, routing, plan=plot())
    assert pipe(result, "S2")["points"][-1][0] == pytest.approx(95)


def test_pins_vias_skips_and_unroutable_reasons():
    model = two_items()
    pinned = [[3, 5, 1], [3, 5, 4], [13, 5, 4], [13, 5, 1]]
    routing = Routing.model_validate(
        {
            "lines": [
                {"line": "L-1", "segment": "S1", "route": pinned},
                {"line": "L-2", "via": [[8, 9, 3]]},
                {"line": "L-3", "skip": "field run"},
            ]
        }
    )
    model["equipment"][0]["nozzles"].append(nozzle("A", "N2", [2, 6, 1], [0, 1, 0], ("S2",)))
    model["equipment"][1]["nozzles"].append(nozzle("B", "N2", [14, 6, 1], [0, 1, 0], ("S2",)))
    segments = [
        seg("S1", "L-1", nz("A"), nz("B")),
        seg("S2", "L-2", nz("A", "N2"), nz("B", "N2")),
        seg("S3", "L-3", nz("A"), nz("B")),
        seg("S4", "L-4", nz("X"), nz("B")),
    ]
    result = route_model(model, segments, routing=routing)
    s1 = pipe(result, "S1")
    assert (
        s1["method"] == "pinned"
        and s1["source"] == "pinned"
        and s1["points"] == [tuple(p) for p in pinned]
    )
    s2 = pipe(result, "S2")
    assert (8, 9, 3) in [tuple(p) for p in s2["points"]] and s2["method"].startswith("via")
    reasons = {u["segment"]: u["reason"] for u in result.unrouted}
    assert reasons == {"S3": "skipped: field run", "S4": "X is not placed"}


def test_open_ends_vent_upwards():
    model = two_items()
    psv = InlineItem("PSV1", "SpringLoadedGlobeSafetyValve", "PSV-1", "safety_valve")
    end = End("item", "PSV1", None, "PSV-1", "PSV1", "SpringLoadedGlobeSafetyValve")
    result = route_model(model, [seg("S1", "L-1", nz("A"), end, items=(psv,))])
    route = pipe(result, "S1")
    assert route["method"] == "open" and route["open_ends"] == ["end"]
    assert route["points"][-1][2] > route["points"][0][2]
    (valve,) = result.inline
    assert valve["point"] == route["points"][-1]


# -- rules -----------------------------------------------------------------------------------


def model_with(pipes, **extra):
    base = two_items()
    base.update(pipes=pipes, **extra)
    return base


def a_pipe(pid, points, od=0.1, line="L", **extra):
    return {
        "id": pid,
        "line": line,
        "segment": pid,
        "od": od,
        "insulation_mm": 0.0,
        "points": points,
        "method": "astar",
        "source": "generated",
        **extra,
    }


def rules_of(model, **kw):
    return sorted({f.rule for f in model_rules(model, **kw)})


def test_clash_rules():
    crossing = model_with(
        [a_pipe("P1", [[5, 0, 3], [5, 10, 3]]), a_pipe("P2", [[0, 5, 3], [10, 5, 3]])]
    )
    found = model_rules(crossing)
    (clash,) = [f for f in found if f.rule == "cheme.layout-clash-pipe"]
    assert clash.ids == ["P1", "P2"] and len(clash.box) == 6
    # meeting at a tee is no clash
    tee_ = model_with([a_pipe("P1", [[0, 5, 3], [10, 5, 3]]), a_pipe("P2", [[5, 5, 3], [5, 9, 3]])])
    assert "cheme.layout-clash-pipe" not in rules_of(tee_)
    through = model_with([a_pipe("P1", [[0, 5, 1], [20, 5, 1]])])
    assert "cheme.layout-clash-pipe-equipment" in rules_of(through)
    # the run at the item a pipe connects to is not a clash
    connected = model_with([a_pipe("P1", [[3, 5, 1], [4, 5, 1], [4, 5, 5]])])
    assert "cheme.layout-clash-pipe-equipment" not in rules_of(connected)


def test_steel_headroom_access_zone_and_rack_fill_rules():
    model = model_with(
        [a_pipe("P1", [[6, -2, 3], [6, 12, 3]], racks=["R"], tier=6.0, od=3.0)],
        roads=[{"id": "RD", "points": [[0, 0], [20, 0]], "width": 4}],
        racks=[{"id": "R", "width": 2.0, "points": [[0, 0], [1, 0]], "levels": [6]}],
        structures=[
            {
                "id": "S",
                "parts": [
                    {
                        "id": "S/col",
                        "kind": "member",
                        "material": "steel",
                        "start": [6, 8, 0],
                        "end": [6, 8, 6],
                        "profile": [0.3, 0.3],
                    },
                    {
                        "id": "S/col2",
                        "kind": "member",
                        "material": "steel",
                        "start": [2, 5, 0],
                        "end": [2, 5, 6],
                        "profile": [0.3, 0.3],
                    },
                ],
            }
        ],
        zones=[
            {
                "id": "KC",
                "kind": "keep_clear",
                "volumes": [{"shape": "box", "source": "declared", "box": [5, 2, 0, 7, 3, 5]}],
            }
        ],
    )
    model["equipment"][1]["envelopes"] = [
        {
            "id": "B/bundle_pull",
            "kind": "bundle_pull",
            "centre": [6, 5, 3],
            "size": [2, 2, 2],
            "rotation_deg": 0,
        }
    ]
    found = rules_of(model)
    for rule in (
        "cheme.layout-clash-pipe-steel",
        "cheme.layout-clash-equipment-steel",
        "cheme.layout-headroom",
        "cheme.layout-access-blocked",
        "cheme.layout-zone-crossing",
        "cheme.layout-rack-fill",
    ):
        assert rule in found, rule


def test_unconnected_nozzles_and_gravity_lines():
    model = model_with([a_pipe("P1", [[0, 0, 1], [5, 0, 1]], line="DR-1")])
    model["unrouted"] = [{"line": "L-1", "segment": "S1", "sheet": "x", "reason": "why"}]
    routing = Routing.model_validate({"lines": [{"line": "DR-1", "gravity": True}]})
    found = {f.rule: f for f in model_rules(model, routing=routing)}
    assert "why" in found["cheme.layout-nozzle-unconnected"].message
    assert found["cheme.layout-gravity-fall"].level == "info"


# -- zones -----------------------------------------------------------------------------------


def test_zone_radii_come_from_the_table():
    (o2,) = classify("vent", "continuous", "oxygen")
    assert o2.kind == "oxygen_enriched" and o2.radius == 5.0 and o2.status == "ASSUMED"
    assert "ASSUMED" in o2.basis
    assert substance_class("Waste nitrogen") == "inert" and substance_class("GOX") == "oxygen"
    assert substance_class("unobtainium") is None
    model = two_items()
    model["equipment"][0]["family"] = "stack"
    zones = ZoneList.model_validate(
        {
            "zones": [
                {
                    "id": "Z1",
                    "kind": "oxygen_enriched",
                    "sources": [
                        {"item": "A", "release_grade": "continuous", "substance": "oxygen"}
                    ],
                },
                {"id": "Z2", "kind": "keep_clear", "shape": "box", "box": [0, 0, 0, 1, 1, 1]},
                {
                    "id": "Z3",
                    "kind": "oxygen_deficient",
                    "sources": [
                        {"item": "A/N1", "release_grade": "secondary", "substance": "nitrogen"},
                        {"item": "nowhere", "substance": "nitrogen"},
                    ],
                },
            ]
        }
    )
    entries, findings = zone_entries(zones, model)
    z1, z2, z3 = entries
    (volume,) = z1["volumes"]
    assert (
        volume["radius"] == 5.0
        and volume["centre"] == (2, 5, 2)
        and volume["source"] == "generated"
    )
    assert z2["volumes"][0]["box"] == (0, 0, 0, 1, 1, 1)
    assert z3["volumes"][0]["radius"] == 1.0 and z3["volumes"][0]["source_kind"] == "flange"
    assert [f.rule for f in findings] == ["cheme.layout-zone-source"]


# -- structures, mounts, platforms -------------------------------------------------------------

STRUCTURES = """\
structures:
  - id: S1
    origin: [10, 10]
    spans_x: [6, 6]
    spans_y: [5]
    levels:
      - {id: L1, elevation: 6}
      - {id: L2, elevation: 12, kind: platform, extent: [0, 0, 6, 5]}
    bracing: {north: x, south: k}
    stairs: [{id: ST1, from: grade, to: L1, side: south}]
    ladders: [{id: LD1, from: L1, to: L2, at: [1, 1]}]
    enclosure: {walls: [north], height: 14, material: casing}
"""


def test_a_frame_has_columns_beams_bracing_stairs_ladders_and_walls():
    (structure,) = StructureList.model_validate(yaml.safe_load(STRUCTURES)).structures
    entry = frame_structure(structure, "layout/structures.yaml")
    ids = [p["id"] for p in entry["parts"]]
    assert sum("/col-" in i for i in ids) == 6  # 3 x 2 grid points
    assert any("/L1/beam-x" in i for i in ids) and any("/L2/grating" in i for i in ids)
    assert any("brace-north" in i for i in ids) and any("brace-south" in i for i in ids)
    assert entry["footprint"] == (10.0, 10.0, 22.0, 15.0)
    (stair,) = [s for s in entry["stairs"] if s["source"] == "declared"]
    assert stair["flights"] == 2 and stair["box"][5] > 6
    (ladder,) = [lad for lad in entry["ladders"] if lad["source"] == "declared"]
    assert ladder["cage"] is True and ladder["base"][2] == 6
    (wall,) = entry["walls"]
    assert wall["material"] == "casing" and wall["size"][2] == 14
    assert entry["sections"]["assumed"] is True


def test_mount_on_a_structure_is_checked():
    def run(z, level="L1", x=12):
        texts = {
            "structures": ("layout/structures.yaml", STRUCTURES),
            "placement": (
                "layout/equipment-placement.yaml",
                f"equipment:\n  - {{tag: V1, position: [{x}, 12, {z}], size: [1, 1, 1], "
                f"mount: {{structure: S1, level: {level}}}}}\n",
            ),
        }
        return [f for f in check_layout(texts).findings if f.rule == "cheme.layout-level"]

    assert run(6) == []
    (wrong,) = run(5)
    assert "level L1 of S1 is at 6 m" in wrong.message
    (unknown,) = run(6, level="L9")
    assert "no level L9" in unknown.message
    (outside,) = run(6, x=40)
    assert "is not inside structure S1" in outside.message


def test_platforms_are_proposed_for_high_nozzles_and_declared_ones_win():
    vessel = item("V", (5, 5, 6), (2, 2, 12), family="vessel")
    vessel["shape"] = "vertical_cylinder"
    vessel["dimensions"] = {"diameter": 2, "height": 12}
    vessel["nozzles"] = [
        nozzle("V", "N1", [6, 5, 8], [1, 0, 0]),
        nozzle("V", "N2", [5, 6, 8.5], [0, 1, 0]),
        nozzle("V", "N3", [4, 5, 1], [-1, 0, 0]),
    ]
    (proposal,) = platforms_for(vessel, None, [], "layout/equipment-placement.yaml")
    assert proposal["source"] == "generated" and proposal["review_needed"] is True
    assert proposal["elevation"] == 7.0 and proposal["serves"] == ["V/N1", "V/N2"]
    assert proposal["ladder"]["cage"] is True and proposal["arc_deg"] is not None
    placement = PlacementList.model_validate(
        {
            "equipment": [
                {
                    "tag": "V",
                    "position": [5, 5, 0],
                    "access": {
                        "platforms": [{"elevation": 4}, {"elevation": 9, "arc_deg": [0, 90]}],
                        "ladder_side": 180,
                    },
                }
            ]
        }
    )
    access = placement.equipment[0].access
    low, high = platforms_for(vessel, access, [], "f")
    assert low["source"] == "declared" and low["elevation"] == 4 and "arc_deg" not in low
    assert high["ladder"]["base"][2] == 4 and high["arc_deg"] == (0, 90)


# -- sizes -----------------------------------------------------------------------------------


def test_pipe_sizes_and_insulation():
    assert outside_diameter(100) == pytest.approx(0.1143)
    assert outside_diameter(90) == pytest.approx(0.1143)  # next larger
    assert parse_dn("DN 1400") == 1400 and parse_dn(None) is None
    assert insulation("cold box (perlite)", 100).thickness == 0
    assert insulation("cold (PUR)", 100).thickness == pytest.approx(0.08)
    assert insulation(None, 100).thickness == 0


@pytest.mark.parametrize(
    "text", ["none", "None", "no", "N/A", "-", "bare", "uninsulated", "Not  insulated", "0"]
)
def test_no_insulation_text_is_zero(text):
    """A line list that says the line is bare gets no insulation, not the 50 mm default."""
    found = insulation(text, 80)
    assert found.thickness == 0 and "no insulation" in found.basis


def test_unknown_insulation_text_keeps_assumed_default():
    found = insulation("acoustic", 80)
    assert found.thickness == pytest.approx(0.05) and found.basis.startswith("ASSUMED")
    assert insulation("not known", 80).thickness == pytest.approx(0.05)


# -- the build, the commands, the API -------------------------------------------------------------

EQUIPMENT = """\
equipment:
  - {tag: V-101, type: PressureVessel, sheet: P-01, dimensions: {diameter: 2, height: 8}}
  - {tag: P-101, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 1.6, width: 0.7, height: 1.0}}
"""
SITE = """\
site: {name: Test, width: 40, depth: 30}
areas:
  - {id: A1, box: [2, 2, 38, 28]}
roads:
  - {id: RD, points: [[0, 1], [40, 1]], width: 1.5}
racks:
  - {id: PR-1, points: [[5, 15], [35, 15]], width: 3, levels: [5]}
separations:
  - {from: Z-O2, to: P-101, min_m: 50, basis: test}
"""
PLACEMENT = """\
equipment:
  - {tag: V-101, position: [10, 10, 0]}
  - {tag: P-101, position: [14, 10, 0], rotation_deg: 90}
"""
ZONES = """\
zones:
  - id: Z-O2
    kind: oxygen_enriched
    sources: [{item: V-101, release_grade: continuous, substance: oxygen, source_kind: vent}]
"""


@pytest.fixture
def plant3d(plant: Path) -> Path:
    shutil.copy(SHEET, plant / "pid" / "P-01.xml")
    (plant / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)
    (plant / "layout" / "site-plan.yaml").write_text(SITE)
    (plant / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    (plant / "layout" / "zones.yaml").write_text(ZONES)
    (plant / "layout" / "structures.yaml").write_text(STRUCTURES.replace("[10, 10]", "[20, 20]"))
    return plant


def test_the_build_holds_pipes_inline_structures_platforms_and_zones(plant3d: Path):
    model = build_model(Workspace(plant3d))
    document = model.document
    LayoutModelFile.model_validate(document)
    (pipe_,) = document["pipes"]
    assert pipe_["line"] == "80-P-101" and pipe_["refs"]["sheet"] == "pid/P-01.xml"
    assert pipe_.get("class") is None or "code" in pipe_["class"]
    assert document["structures"][0]["id"] == "S1" and document["racks"][0]["parts"]
    assert document["zones"][0]["volumes"][0]["radius"] == 5.0
    assert document["platforms"] and document["routing"]["routed"] == 1
    rules = {f.rule for f in model.findings}
    assert "cheme.layout-separation" in rules  # measured to the zone
    # every sheet reference is relative to the repository
    assert "pid/P-01.xml" in document["provenance"]["sources"]
    assert build_model(Workspace(plant3d)).text() == model.text()  # byte-identical


def test_sheet_references_are_relative_even_through_a_symlinked_root(plant3d: Path, tmp_path):
    link = tmp_path / "linked"
    link.symlink_to(plant3d)
    document = build_model(Workspace(link)).document
    sheets = {
        ref
        for section in ("equipment", "pipes", "inline")
        for obj in document[section]
        for ref in [obj["refs"].get("sheet")]
        if ref
    }
    assert sheets == {"pid/P-01.xml"}


def test_layout_commands(plant3d: Path, monkeypatch):
    monkeypatch.chdir(plant3d)
    assert runner.invoke(app, ["layout", "report"]).exit_code == 1  # no model yet
    result = runner.invoke(app, ["layout", "build"])
    assert "1 of 1 segments routed" in result.output, result.output
    report = runner.invoke(app, ["layout", "report"])
    assert report.exit_code == 0 and "80-P-101: routed, 1 segments" in report.output
    data = json.loads(runner.invoke(app, ["layout", "report", "--json"]).output)
    assert data["lines"][0]["status"] == "routed"
    assert sum(data["methods"].values()) == sum(data["reasons"].values()) == 1
    assert data["lines"][0]["reasons"] == data["reasons"]
    assert "reasons (chains):" in report.output and "methods (chains):" in report.output
    for args, name in (
        (["--plan"], "layout-plan.svg"),
        (["--z", "0,3"], "layout-plan-z0-3.svg"),
        (["--level", "L1"], "layout-level-L1.svg"),
        (["--section", "y=10"], "layout-section-y10.svg"),
        (["--section", "x=10", "--crop", "0,0,20,10"], "layout-section-x10_crop-0-0-20-10.svg"),
    ):
        result = runner.invoke(app, ["layout", "render", *args])
        assert result.exit_code == 0 and name in result.output, result.output
        assert (plant3d / "build" / name).read_text().startswith("<svg")
    assert runner.invoke(app, ["layout", "render", "--section", "z=1"]).exit_code == 2
    # pin the route: the rebuild keeps it
    result = runner.invoke(app, ["layout", "pin", "80-P-101"])
    assert result.exit_code == 0 and "piping/routing.yaml" in result.output
    routing = yaml.safe_load((plant3d / "piping" / "routing.yaml").read_text())
    assert routing["lines"][0]["line"] == "80-P-101" and len(routing["lines"][0]["route"]) >= 2
    runner.invoke(app, ["layout", "build"])
    (pinned,) = read((plant3d / "layout" / "plant-model.yaml").read_text())["pipes"]
    assert pinned["source"] == "pinned"
    # pinning again replaces the entry
    runner.invoke(app, ["layout", "pin", "80-P-101"])
    assert len(yaml.safe_load((plant3d / "piping" / "routing.yaml").read_text())["lines"]) == 1
    # pin a proposed platform into the placement
    platforms = read((plant3d / "layout" / "plant-model.yaml").read_text())["platforms"]
    first = platforms[0]["id"]
    result = runner.invoke(app, ["layout", "pin", first])
    assert result.exit_code == 0, result.output
    placement = yaml.safe_load((plant3d / "layout" / "equipment-placement.yaml").read_text())
    access = next(e for e in placement["equipment"] if e["tag"] == first.split("/")[0])["access"]
    assert access["platforms"] and "ladder_side" in access
    runner.invoke(app, ["layout", "build"])
    rebuilt = read((plant3d / "layout" / "plant-model.yaml").read_text())["platforms"]
    assert rebuilt[0]["source"] == "declared"
    # route only one line: the rest is kept
    assert runner.invoke(app, ["layout", "route", "--line", "80-P-101"]).exit_code == 0


def test_drawings_hold_their_key_elements(plant3d: Path):
    workspace = Workspace(plant3d)
    write_model(workspace, build_model(workspace))
    model = read((plant3d / "layout" / "plant-model.yaml").read_text())
    plan = render_plan(model, {"plant": "Test", "project": "24-001"})
    for needle in (
        'id="north-arrow"',
        'id="scale-bar"',
        'id="title-block"',
        'id="pipe-P-01/',
        "V-101",
        "80-P-101",
        'id="zone-Z-O2-0"',
        "hatch-oxygen_enriched",
        "24-001",
        'id="road-RD-0"',
        'id="rack-PR-1"',
        "S1",
    ):
        assert needle in plan, needle
    assert level_range(model, "L1") == (5.9, 11.9)
    level = render_plan(model, cut=level_range(model, "L1"))
    assert "stroke-dasharray" in level  # what lies below is dashed
    section = render_section(model, "y", 10.0, 4.0)
    assert 'id="grade"' in section and "<circle" in section and "north-arrow" not in section
    with pytest.raises(ValueError):
        render_section(model, "z", 1.0)


def client(root: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    return TestClient(create_app(root, None, allowed_hosts=["testserver"]))


def test_drawing_endpoints_and_model_findings(plant3d: Path):
    workspace = Workspace(plant3d)
    git(plant3d, "add", "-A")
    git(plant3d, "commit", "-q", "-m", "layout")
    api = client(plant3d)
    assert api.get("/api/layout/plan.svg").status_code == 404  # no model yet
    write_model(workspace, build_model(workspace))
    response = api.get("/api/layout/plan.svg")
    assert response.status_code == 200 and response.headers["content-type"].startswith("image/svg")
    assert "north-arrow" in response.text
    assert "Level plan" in api.get("/api/layout/plan.svg", params={"level": "L1"}).text
    assert api.get("/api/layout/plan.svg", params={"z": "0,3"}).status_code == 200
    assert api.get("/api/layout/plan.svg", params={"level": "nope"}).status_code == 404
    assert api.get("/api/layout/plan.svg", params={"z": "x"}).status_code == 400
    section = api.get("/api/layout/section.svg", params={"y": 10, "depth": 4})
    assert section.status_code == 200 and "Section y = 10" in section.text
    assert api.get("/api/layout/section.svg").status_code == 400
    assert api.get("/api/layout/section.svg", params={"rev": "HEAD", "x": 1}).status_code == 404
    data = api.get("/api/layout").json()
    assert data["model"]["pipes"] and data["zones"] == data["model"]["zones"]
    assert any(f["rule"] == "cheme.layout-separation" for f in data["model_findings"])


def test_validate_runs_the_model_rules(plant3d: Path):
    from chemeascode.project.validate import validate_workspace

    workspace = Workspace(plant3d)
    write_model(workspace, build_model(workspace))
    report = validate_workspace(workspace)
    assert any(
        f.rule == "cheme.layout-separation" and f.file == "layout/plant-model.yaml"
        for f in report.findings
    )


def test_capsule_and_solid_distances():
    assert segment_distance((0, 0, 0), (10, 0, 0), Box("b", (5, 2, 0), (2, 2, 2))) == pytest.approx(
        1
    )
    assert segment_distance(
        (0, 0, 5), (10, 0, 5), Cylinder("c", (5, 0, 0), (5, 0, 3), 1)
    ) == pytest.approx(2)
    assert segment_distance(
        (0, 0, 0), (1, 0, 0), Capsule("p", (0, 3, 0), (1, 3, 0), 1)
    ) == pytest.approx(2)


def test_the_frozen_fixture_holds_every_section_with_relative_sheets():
    data = json.loads((DATA / "api-layout-asu.json").read_text())
    model = data["model"]
    LayoutModelFile.model_validate(model)
    for section in ("pipes", "inline", "structures", "platforms", "zones", "unrouted"):
        assert model[section], section
    text = json.dumps(model)
    assert "/var/" not in text and "/private/" not in text and "/Users/" not in text
    sheets = {p["refs"]["sheet"] for p in model["pipes"]}
    assert all(s.startswith("pid/") and s.endswith(".xml") for s in sheets)
    # every pipe says why it went that way; the battery limit rule of the ASU's routing.yaml
    # takes the cooling water to the west end of PR1, and most lines run on the racks
    assert all(p.get("reason") for p in model["pipes"])
    routing = model["routing"]
    assert sum(routing["reasons"].values()) == sum(routing["methods"].values())
    assert routing["battery_limits"].get("battery limit rule", 0) > 0
    # pinned runs carry none: the ASU pins the lines of its valve platforms (D-047)
    assert sum(1 for p in model["pipes"] if p.get("racks")) > 10
    # in-line item ids are unique (a component two segments share is one item)
    ids = [i["id"] for i in model["inline"]]
    assert len(ids) == len(set(ids))
    # the ASU's layout is routed without clashes or direct fallbacks
    assert not [f for f in data["model_findings"] if "clash" in f["rule"]]
    assert "direct" not in model["routing"]["methods"]


# -- stage gates on the layout ----------------------------------------------------------------


def layout_gates(plant: Path, **basic) -> dict:
    from chemeascode.project.checks import run_checks

    gates = {
        "checks": [
            {
                "id": "plot",
                "title": "Plot plan",
                "stage": "concept",
                "kind": "layout-model",
                "require": ["site", "areas", "roads", "racks", "placed", "separations"],
            },
            {
                "id": "3d",
                "title": "3D",
                "stage": "basic",
                "kind": "layout-model",
                "require": ["model-current", "nozzles", "mounted", "routed", "clashes", "zones"],
                # the test vessel's bottom nozzle sits inside its skirt
                "accept": [
                    {
                        "id": "layout/plant-model.yaml#layout-clash-pipe-equipment:P-01/*",
                        "reason": "bottom nozzle inside the skirt (test data)",
                    }
                ],
                **basic,
            },
        ]
    }
    (plant / "checks" / "checks.yaml").write_text(yaml.safe_dump(gates, sort_keys=False))
    return {r.id: r for r in run_checks(Workspace(plant))}


def test_layout_gates(plant3d: Path):
    found = layout_gates(plant3d)
    assert found["plot"].status == "pass", found["plot"].detail
    assert found["3d"].status == "fail" and "run cheme layout build" in found["3d"].detail
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    found = layout_gates(plant3d)
    assert found["3d"].status == "pass", found["3d"].detail
    # an item above grade on nothing, a line left unrouted, a missing placement
    placement = plant3d / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[10, 10, 0]", "[10, 10, 3]"))
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    detail = layout_gates(plant3d)["3d"].detail
    assert "1 elevated items on nothing: V-101" in detail
    # on a declared plinth it stands on something
    placement.write_text(PLACEMENT.replace("[10, 10, 0]}", "[10, 10, 0.5], plinth: 0.5}"))
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    assert "elevated items on nothing" not in layout_gates(plant3d)["3d"].detail
    # a plinth must carry the item: position z is its height, and no mount
    with pytest.raises(ValueError, match="stands at z 0.5"):
        Placement.model_validate({"tag": "V-101", "position": [10, 10, 0.4], "plinth": 0.5})
    with pytest.raises(ValueError, match="no mount with plinth"):
        Placement.model_validate(
            {
                "tag": "V-101",
                "position": [10, 10, 0.5],
                "plinth": 0.5,
                "mount": {"building": "B", "level": "L"},
            }
        )
    placement.write_text(PLACEMENT.split("  - {tag: P-101")[0])
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    found = layout_gates(plant3d)
    assert "1 equipment-list items not placed: P-101" in found["plot"].detail
    assert "1 lines neither routed nor skipped: 80-P-101 (P-101 is not placed)" in (
        found["3d"].detail
    )
    # skipped with a reason, below min_dn (the line list's DN) or excluded: passes
    (plant3d / "piping" / "line-list.yaml").write_text(
        "lines:\n  - {number: 80-P-101, from: V-101, to: P-101, nominal_diameter: DN80}\n"
    )
    assert "neither routed" in layout_gates(plant3d, min_dn=80)["3d"].detail
    assert "neither routed" not in layout_gates(plant3d, min_dn=100)["3d"].detail
    assert "neither routed" not in layout_gates(plant3d, exclude_lines=["80-P-*"])["3d"].detail
    (plant3d / "piping" / "routing.yaml").write_text(
        "lines:\n  - {line: 80-P-101, skip: pump not placed yet}\n"
    )
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    assert "neither routed" not in layout_gates(plant3d)["3d"].detail
    # an outdated model fails model-current
    placement.write_text(PLACEMENT)
    assert "layout-model-outdated" in layout_gates(plant3d)["3d"].detail


def test_the_drawings_requirement_reads_the_layout_review(plant3d: Path):
    found = layout_gates(plant3d, require=["drawings"])
    assert "no review record of topic layout" in found["3d"].detail
    record = plant3d / "reviews" / "2026-11-01-layout.md"
    front = (
        "---\ntopic: layout\nreviewed_commit: 0000000\nscope: [layout]\nreviewer: R\n"
        "reviewer_kind: agent\n---\n# Review: layout\n"
    )
    record.write_text(front + "Plan build/layout-plan.png, section build/layout-section-x10.png\n")
    found = layout_gates(plant3d, require=["drawings"])
    assert "cites a plot plan and 1 section(s)" in found["3d"].detail
    record.write_text(record.read_text() + "and build/layout-section-y12.5.png\n")
    assert layout_gates(plant3d, require=["drawings"])["3d"].status == "pass"


def test_clashes_fail_the_gate_unless_accepted(plant3d: Path):
    write_model(Workspace(plant3d), build_model(Workspace(plant3d)))
    from chemeascode.foundation.findings import Finding

    clash = Finding(
        "layout/plant-model.yaml",
        "warning",
        "cheme.layout-clash-pipe",
        "pipes A and B are 0.00 m apart",
        ids=["A", "B"],
        key="A+B",
    )
    from chemeascode.domains.spatial.gates import layout_gate

    ws = Workspace(plant3d)
    assert "1 cheme.layout-clash-pipe not accepted" in layout_gate(ws, ["clashes"], [clash])[0]
    from chemeascode.foundation.schemas.checks import Accept

    accept = [Accept(id="layout/plant-model.yaml#layout-clash-pipe:A+*", reason="ok, R")]
    assert layout_gate(ws, ["clashes"], [clash], accept=accept) == []
    assert layout_gate(ws, ["clashes"], [clash], rules=["cheme.layout-headroom"]) == []
