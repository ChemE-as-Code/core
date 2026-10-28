"""Router and rule fixes found while applying the 3D layout to the ASU example."""

from __future__ import annotations

import math

from chemeascode.domains.spatial.geometry3d import Box, Capsule, segment_distance, simplify
from chemeascode.domains.spatial.layout_distances import point_segment
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.pid_network import End, InlineItem
from chemeascode.domains.spatial.routing import EndPoint, Router, route_model
from chemeascode.domains.spatial.schemas import Routing, SitePlan
from tests import test_layout_3d
from tests.test_layout_3d import a_pipe, item, model_with, nozzle, nz, pipe, seg, tee, two_items

plant3d = test_layout_3d.plant3d  # the fixture: a plant with a vessel, a pump and a rack


def points(p):
    return [tuple(q) for q in p["points"]]


def clearance(p, q):
    """Smallest gap between the axes of two routed pipes, minus both radii."""
    rp = p["od"] / 2 + p.get("insulation_mm", 0) / 1000
    rq = q["od"] / 2 + q.get("insulation_mm", 0) / 1000
    best = float("inf")
    for a, b in zip(points(p), points(p)[1:], strict=False):
        for c, d in zip(points(q), points(q)[1:], strict=False):
            best = min(best, segment_distance(a, b, Capsule("q", c, d, rq)) - rp)
    return best


# -- in-line items ---------------------------------------------------------------------------


def test_a_vent_line_ends_at_its_placed_silencer():
    model = two_items()
    model["equipment"].append(item("S-1", (20, 5, 2), (1, 1, 4)))
    silencer = InlineItem("S1", "Silencer", "S-1", "silencer")
    open_end = End("opc_out", "Opc_ATM1", None, None, "Opc_ATM1", "OffPageConnector")
    result = route_model(model, [seg("S1", "VNT-1", nz("A"), open_end, items=(silencer,))])
    route = pipe(result, "S1")
    assert route["method"] != "open" and "open_ends" not in route
    x0, y0, z0, x1, y1, z1 = 19.5, 4.5, 0, 20.5, 5.5, 4
    end = points(route)[-1]
    assert x0 <= end[0] <= x1 and y0 <= end[1] <= y1 and z0 <= end[2] <= z1
    (placed,) = result.inline
    assert placed["tag"] == "S-1" and tuple(placed["point"]) == end


def test_a_component_two_segments_share_is_one_inline_item():
    model = two_items()
    valve = InlineItem("V1", "GateValve", "HV-1", "valve")
    end = End("item", "V1", None, "HV-1", "V1", "GateValve")
    segments = [
        seg("S1", "L-1", nz("A"), end, items=(valve,)),
        seg("S2", "L-1", end, nz("B"), items=(valve,)),
    ]
    result = route_model(model, segments)
    (shared,) = result.inline
    assert shared["id"] == "P-01/V1" and shared["refs"]["segments"] == ["S1", "S2"]


# -- open ends -------------------------------------------------------------------------------


def test_an_open_vent_riser_steps_clear_of_a_pipe_routed_before():
    router = Router(two_items(), [])
    tip = (8.0, 5.0, 1.0)
    router.pipes_index.add(Capsule("P-X", (8.0, 0.0, 1.5), (8.0, 10.0, 1.5), 0.1), "pipe")
    fixed = EndPoint("fixed", (7.5, 5.0, 1.0), (1.0, 0.0, 0.0))
    route = router._open_route([fixed.point, tip], fixed, 0.05)
    assert route[-1][2] > route[0][2]
    other = Capsule("P-X", (8.0, 0.0, 1.5), (8.0, 10.0, 1.5), 0.1)
    assert all(
        segment_distance(a, b, other) >= 0.05 + 0.1 - 1e-6
        for a, b in zip(route[1:], route[2:], strict=False)
    )


# -- racks -----------------------------------------------------------------------------------


def rack_plot(**extra):
    return SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 40},
            "racks": [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]}],
            **extra,
        }
    )


def rack_model():
    return {
        "equipment": [
            item("A", (10, 10, 1), (2, 2, 2), [nozzle("A", "N1", [10, 11, 1], [0, 1, 0])]),
            item("B", (110, 10, 1), (2, 2, 2), [nozzle("B", "N1", [110, 11, 1], [0, 1, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }


def test_a_rack_lane_keeps_clear_of_a_pipe_routed_before():
    # a pinned pipe comes onto the rack from the south at the lanes' height and rises in it:
    # the lanes it crosses are not free there
    crossing = [[60, 12, 6.2], [60, 19, 6.2], [60, 19, 12]]
    routing = Routing.model_validate(
        {"lines": [{"line": "L-0", "segment": "S0", "route": crossing}]}
    )
    segments = [
        seg("S0", "L-0", nz("A", "N9"), nz("B", "N9"), dn=100.0),
        seg("S1", "L-1", nz("A"), nz("B"), dn=300.0),
    ]
    result = route_model(rack_model(), segments, routing=routing, plan=rack_plot())
    run, pinned = pipe(result, "S1"), pipe(result, "S0")
    assert run["racks"] == ["PR"]
    assert clearance(run, pinned) >= 0.1 - 1e-6


def test_ends_whose_rack_points_nearly_meet_stay_local():
    model = {
        "equipment": [
            item("A", (50, 10, 1), (2, 2, 2), [nozzle("A", "N1", [50, 11, 1], [0, 1, 0])]),
            item("B", (50.5, 30, 1), (2, 2, 2), [nozzle("B", "N1", [50.5, 29, 1], [0, -1, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    plan = rack_plot(
        areas=[{"id": "S", "box": [0, 0, 120, 19]}, {"id": "N", "box": [0, 21, 120, 40]}]
    )
    result = route_model(model, [seg("S1", "L-1", nz("A"), nz("B"))], plan=plan)
    route = pipe(result, "S1")
    assert "racks" not in route and route["reason"] == "local: rack run too short"


def test_a_route_over_crossing_racks_turns_at_the_crossing():
    # PR-B crosses PR-A mid-segment, 50 m from every rack vertex: the route turns from one onto
    # the other there instead of running to a rack end and jumping across open ground
    # (pre-release issue 192)
    racks = {"PR-A": [[10, 90], [10, 60], [110, 60]], "PR-B": [[60, 10], [60, 110]]}
    plan = SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 120},
            "racks": [
                {"id": rack, "points": p, "width": 4, "levels": [6]} for rack, p in racks.items()
            ],
        }
    )
    model = {
        "equipment": [
            item("A", (25, 54, 1), (2, 2, 2), [nozzle("A", "N1", [25, 55, 1], [0, 1, 0])]),
            item("B", (66, 100, 1), (2, 2, 2), [nozzle("B", "N1", [65, 100, 1], [-1, 0, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    route = pipe(route_model(model, [seg("S1", "L-1", nz("A"), nz("B"))], plan=plan), "S1")
    assert route["method"] == "rack" and route["racks"] == ["PR-A", "PR-B"]
    run = points(route)

    def off_racks(p):
        return min(
            point_segment(p, tuple(c), tuple(d))[0]
            for line in racks.values()
            for c, d in zip(line, line[1:], strict=False)
        )

    # every level run at the tier longer than the rack is wide lies on a rack strip: no hop
    # across open ground
    for a, b in zip(run, run[1:], strict=False):
        if a[2] > 5 and abs(a[2] - b[2]) < 1e-6 and math.dist(a, b) > 4:
            assert off_racks(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)) <= 2.0 + 1e-6, (a, b)
    plan_length = sum(math.dist(a[:2], b[:2]) for a, b in zip(run, run[1:], strict=False))
    assert plan_length < 6 + 35 + 40 + 6 + 8  # about along the racks through the crossing


# -- near the ends ---------------------------------------------------------------------------


def test_a_bottom_nozzle_under_its_item_leaves_the_outline_first():
    drum = item("D", (5, 5, 1.5), (4, 2, 1), [nozzle("D", "N1", [5, 5, 1.0], [0, 0, -1])])
    drum["bbox"] = [3, 4, 0, 7, 6, 2]  # saddles below the shell
    model = {
        "equipment": [
            drum,
            item("B", (20, 5, 1), (2, 2, 2), [nozzle("B", "N1", [19, 5, 1], [-1, 0, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    result = route_model(model, [seg("S1", "L-1", nz("D"), nz("B"))])
    route = points(pipe(result, "S1"))
    assert route[1][:2] == (5, 5) and route[1][2] < 1.0  # down under the shell
    exit_ = route[2]
    assert exit_[2] == route[1][2] and not (3 < exit_[0] < 7 and 4 < exit_[1] < 6)
    # the run that leaves the outline is no clash with the item it belongs to
    found = model_rules({**model, "pipes": result.pipes})
    assert not [f for f in found if f.rule == "cheme.layout-clash-pipe-equipment"]


def test_a_pipe_through_a_skirt_from_its_own_bottom_nozzle_is_no_clash():
    model = model_with([a_pipe("P1", [[2, 5, 0.5], [2, 5, 0.3], [5, 5, 0.3], [5, 5, 4]])])
    found = {f.rule for f in model_rules(model)}
    # the pipe starts inside A's outline (its bottom nozzle) and leaves it: not a clash
    assert "cheme.layout-clash-pipe-equipment" not in found
    through = model_with([a_pipe("P1", [[0, 5, 0.3], [20, 5, 0.3]])])
    assert "cheme.layout-clash-pipe-equipment" in {f.rule for f in model_rules(through)}


def test_a_lane_start_beside_a_lane_is_reached_with_the_spacing():
    segments = [
        seg("S1", "L-1", nz("A"), nz("B"), dn=300.0),
        seg("S2", "L-2", nz("A", "N2"), nz("B", "N2"), dn=100.0),
    ]
    model = rack_model()
    model["equipment"][0]["nozzles"].append(nozzle("A", "N2", [9, 11, 1], [0, 1, 0], ("S2",)))
    model["equipment"][1]["nozzles"].append(nozzle("B", "N2", [109, 11, 1], [0, 1, 0], ("S2",)))
    result = route_model(model, segments, plan=rack_plot())
    big, small = pipe(result, "S1"), pipe(result, "S2")
    assert big["method"] == "rack" and small["method"] == "rack"
    assert clearance(big, small) >= 0.1 - 1e-6


def test_simplify_cuts_spikes():
    spike = [(0, 0, 0), (0, 0, 5), (0, 0, 3), (4, 0, 3)]
    assert simplify(spike) == [(0, 0, 0), (0, 0, 3), (4, 0, 3)]
    back = [(0, 0, 0), (2, 0, 0), (0, 0, 0), (0, 2, 0)]
    assert simplify(back) == [(0, 0, 0), (0, 2, 0)]


def test_rack_fill_is_the_most_crowded_section_not_every_segment():
    # one line split into three segments on a 1 m rack: 0.4 m used, not 1.2 m
    pipes = [
        a_pipe(f"P{k}", [[k * 10, 0, 6], [k * 10 + 10, 0, 6]], od=0.3, racks=["R"], tier=6.0)
        for k in range(3)
    ]
    racks = [{"id": "R", "points": [[0, 0], [30, 0]], "width": 1.0, "levels": [6.0], "parts": []}]
    fill = [{"rack": "R", "tier": 6.0, "used_m": 0.4, "width_m": 1.0, "fill": 0.4}]
    model = model_with(pipes, racks=racks, routing={"rack_fill": fill})
    assert "cheme.layout-rack-fill" not in {f.rule for f in model_rules(model)}
    full = [{"rack": "R", "tier": 6.0, "used_m": 1.3, "width_m": 1.0, "fill": 1.3}]
    model = model_with(pipes, racks=racks, routing={"rack_fill": full})
    assert "cheme.layout-rack-fill" in {f.rule for f in model_rules(model)}


def test_a_line_crosses_a_road_on_a_rack_not_on_its_way_to_one():
    plan = SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 60},
            "rack_reach": 50,  # N is 40 m from rack B
            "roads": [{"id": "RD", "points": [[0, 30], [120, 30]], "width": 6}],
            "racks": [
                {"id": "A", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]},
                {"id": "B", "points": [[60, 20], [60, 50]], "width": 4, "levels": [7]},
            ],
        }
    )
    model = {
        "equipment": [
            item("N", (100, 45, 1), (2, 2, 2), [nozzle("N", "N1", [99, 45, 1], [-1, 0, 0])]),
            item("S", (20, 10, 1), (2, 2, 2), [nozzle("S", "N1", [21, 10, 1], [1, 0, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    result = route_model(model, [seg("S1", "L-1", nz("N"), nz("S"))], plan=plan)
    route = pipe(result, "S1")
    assert "B" in route["racks"]


def test_a_relief_valve_placed_on_a_structure_splits_its_line_there():
    model = two_items()
    model["equipment"].append(item("PSV-1", (8, 5, 6), (0.6, 0.6, 1)))
    psv = InlineItem("PSV1", "SpringLoadedGlobeSafetyValve", "PSV-1", "safety_valve")
    valve = End("item", "PSV1", None, "PSV-1", "PSV1", "SpringLoadedGlobeSafetyValve")
    outlet = End("opc_out", "Opc_ATM2", None, None, "Opc_ATM2", "OffPageConnector")
    segments = [
        seg("S1", "VNT-1", nz("A"), valve, items=(psv,)),
        seg("S2", "VNT-1", valve, outlet, items=(psv,)),
    ]
    result = route_model(model, segments)
    inlet, out = pipe(result, "S1"), pipe(result, "S2")
    for x, y, z in (points(inlet)[-1], points(out)[0]):  # both at the valve
        assert 7.7 <= x <= 8.3 and 4.7 <= y <= 5.3 and 5.5 <= z <= 6.5
    assert out["method"] == "open"
    assert points(out)[-1][2] > points(out)[0][2]


def test_a_line_passing_an_enclosure_goes_around_its_walls():
    model = two_items()
    wall = {
        "id": "W/wall-south",
        "kind": "box",
        "material": "casing",
        "centre": [8, 5, 3],
        "size": [0.3, 8, 6],
        "rotation_deg": 0.0,
    }
    model["structures"] = [
        {"id": "W", "footprint": [7.85, 1, 8.15, 9], "parts": [], "stairs": [], "walls": [wall]}
    ]
    result = route_model(model, [seg("S1", "L-1", nz("A"), nz("B"))])
    route = points(pipe(result, "S1"))
    panel = Box("wall", (8, 5, 3), (0.3, 8, 6))
    assert all(segment_distance(a, b, panel) > 0 for a, b in zip(route, route[1:], strict=False))


def test_a_route_that_doubles_back_under_itself_is_cut_short():
    """A run west on a tier, a drop and a run back east right under it (a lane run past the
    point where the line drops off the rack) is the shorter run and the drop where the two
    overlap; the rack points follow the moved point. A blocked drop leaves the route."""
    router = Router(two_items(), [])
    hairpin = [(100, 5, 1), (94, 5, 7.25), (89, 5, 7.25), (89, 5, 5.75), (91.5, 5, 5.75)]
    hairpin += [(91.5, 0, 5.75), (91.5, 0, 1)]
    extra = {"on_rack": [(94, 5, 7.25), (89, 5, 7.25)]}
    route = router._unhairpin(hairpin, 0.25, extra)
    assert route[:4] == [(100, 5, 1), (94, 5, 7.25), (91.5, 5, 7.25), (91.5, 5, 5.75)]
    assert extra["on_rack"] == [(94, 5, 7.25), (91.5, 5, 7.25)]
    # the other way round: a short run out, a riser and a long run back over it
    up = [(0, 50, 1), (2, 50, 1), (2, 50, 4), (-6, 50, 4), (-6, 50, 1)]
    assert router._unhairpin(up, 0.1, {}) == [(0, 50, 1), (0, 50, 4), (-6, 50, 4), (-6, 50, 1)]
    blocked = two_items()
    blocked["equipment"].append(item("X-1", (91.5, 5, 6.5), (0.6, 0.6, 1.0)))
    assert Router(blocked, [])._unhairpin(hairpin, 0.25, {}) == simplify(hairpin)


# -- a segment id repeated on two sheets ------------------------------------------------------


def test_a_pin_names_one_sheets_segment_when_the_id_repeats_on_another_sheet(tmp_path):
    """A line drawn on two sheets may repeat a DEXPI segment id (S1 on each): a pinned route
    keyed by the bare id would apply to both; ``<sheet stem>/<id>`` names one of them, and
    ``layout pin`` writes that form when the id repeats (the ASU's GOX-4001 on P-03/P-04)."""
    from chemeascode.domains.spatial.engineering_rules import EngineeringRules
    from chemeascode.domains.spatial.pins import pin_routes

    model = two_items()
    model["equipment"][0]["nozzles"].append(nozzle("A", "N2", [2, 6, 1], [0, 1, 0]))
    model["equipment"][1]["nozzles"].append(nozzle("B", "N2", [14, 6, 1], [0, 1, 0]))
    pinned = [[2, 6, 1], [2, 8, 1], [2, 8, 4], [14, 8, 4], [14, 8, 1], [14, 6, 1]]
    routing = Routing.model_validate(
        {"lines": [{"line": "L-1", "segment": "P-02/S1", "route": pinned}]}
    )
    segments = [
        seg("S1", "L-1", nz("A"), nz("B")),
        seg("S1", "L-1", nz("A", "N2"), nz("B", "N2"), sheet="pid/P-02.xml"),
    ]
    result = route_model(model, segments, routing=routing)
    by_id = {p["id"]: p for p in result.pipes}
    assert by_id["P-02/S1"]["source"] == "pinned" and points(by_id["P-02/S1"]) == [
        tuple(p) for p in pinned
    ]
    assert by_id["P-01/S1"]["source"] == "generated"
    # pinning: the repeated id is written with its sheet, a unique one stays bare
    model["pipes"] = [
        {"id": "P-01/S1", "line": "L-1", "segment": "S1", "points": [[0, 0, 1], [1, 0, 1]]},
        {"id": "P-02/S1", "line": "L-1", "segment": "S1", "points": [[0, 2, 1], [1, 2, 1]]},
        {"id": "P-02/S2", "line": "L-1", "segment": "S2", "points": [[1, 2, 1], [2, 2, 1]]},
    ]
    done = pin_routes(tmp_path, model, "L-1")
    assert done.what == ["L-1 P-01/S1", "L-1 P-02/S1", "L-1 S2"]
    pin_routes(tmp_path, model, "P-02/S1")  # again: replaced, not added
    text = (tmp_path / "piping" / "routing.yaml").read_text()
    entries = Routing.model_validate(__import__("yaml").safe_load(text)).lines
    assert [e.segment for e in entries] == ["P-01/S1", "P-02/S1", "S2"]
    # a tier intent by pipe id is that pipe's own
    tier = EngineeringRules._tier_rule(
        {"id": "P-02/S1", "line": "L-1", "segment": "S1"},
        "PR",
        {("L-1", "P-02/S1"): 9.0, ("L-1", "S1"): 7.0},
        Routing.model_validate({}).rules,
    )
    assert tier == (9.0, "its tier intent in piping/routing.yaml")


def test_a_pinned_run_segment_ends_its_chain_at_the_tee():
    """With one run segment of a tee pinned, the other run segment starts at the pinned end
    and the branch starts there too: the two are not chained through the tee as if the branch
    were the run (the ASU's LOX-3001 S2 started at the rack, and GOX-4004 S4 stopped short of
    its PSV tee, leaving a gap)."""
    model = two_items()
    model["equipment"].append(
        item("D", (8, 14, 1), (2, 2, 2), [nozzle("D", "N1", [8, 13, 1], [0, -1, 0], ("S3",))])
    )
    pinned = [[3, 5, 1], [3, 5, 3], [7, 5, 3]]
    routing = Routing.model_validate({"lines": [{"line": "L-1", "segment": "S1", "route": pinned}]})
    segments = [
        seg("S1", "L-1", nz("A"), tee(0)),
        seg("S2", "L-1", tee(1), nz("B")),
        seg("S3", "L-1", tee(2), nz("D")),
    ]
    result = route_model(model, segments, routing=routing)
    assert result.unrouted == []
    s2, s3 = pipe(result, "S2"), pipe(result, "S3")
    assert tuple(s2["points"][0]) == (7, 5, 3) and tuple(s3["points"][0]) == (7, 5, 3)
    assert tuple(s2["points"][-1]) == (13, 5, 1) and tuple(s3["points"][-1]) == (8, 13, 1)


def test_router_and_line_route_check_share_one_rack_reach():
    """pre-release issue 21: the site plan's rack_reach is the one value; routing.yaml's is
    deprecated."""
    from chemeascode.domains.spatial.schemas import RoutingRules, rack_reach

    site = {"site": {"width": 100, "depth": 100}}
    assert rack_reach(None) == 30.0
    assert rack_reach(SitePlan.model_validate(site), RoutingRules()) == 30.0
    plan = SitePlan.model_validate({**site, "max_unsupported_length": 40})
    assert rack_reach(plan, RoutingRules()) == 40.0 == plan.reach
    assert rack_reach(plan, RoutingRules(rack_reach_m=50)) == 50.0
    plan = SitePlan.model_validate({**site, "rack_reach": 20})
    assert rack_reach(plan, RoutingRules(rack_reach_m=50)) == 20.0
    # the router takes an end 40 m from rack B only within the reach
    far = {
        "site": {"width": 120, "depth": 60},
        "racks": [{"id": "B", "points": [[60, 20], [60, 50]], "width": 4, "levels": [7]}],
    }
    model = {
        "equipment": [
            item("N", (100, 45, 1), (2, 2, 2), [nozzle("N", "N1", [99, 45, 1], [-1, 0, 0])]),
            item("S", (20, 10, 1), (2, 2, 2), [nozzle("S", "N1", [21, 10, 1], [1, 0, 0])]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }
    segments = [seg("S1", "L-1", nz("N"), nz("S"))]
    short = route_model(model, segments, plan=SitePlan.model_validate(far))
    assert "B" not in (pipe(short, "S1").get("racks") or [])
    wide = route_model(model, segments, plan=SitePlan.model_validate({**far, "rack_reach": 50}))
    assert "B" in pipe(wide, "S1")["racks"]
