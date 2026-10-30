"""A line with battery limits at both ends (core#72): a header from a battery limit to a battery
limit along a rack, with branches teeing off it to their users."""

from __future__ import annotations

import pytest

from chemeascode.domains.piping.schemas.lines import LineList
from chemeascode.domains.spatial.geometry3d import point_at, split_at_many
from chemeascode.domains.spatial.model import _round
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.pid_network import End
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import Routing, SitePlan
from tests.test_layout_3d import item, nozzle, nz, pipe, seg


def plan(**extra):
    return SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 40},
            "racks": [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]}],
            **extra,
        }
    )


def model():
    """Two users south of the rack, at x 40 and 80."""
    return {
        "equipment": [
            item("A", (40, 10, 1), (2, 2, 2), [nozzle("A", "N1", [40, 11, 1], [0, 1, 0], ("S4",))]),
            item("B", (80, 10, 1), (2, 2, 2), [nozzle("B", "N1", [80, 11, 1], [0, 1, 0], ("S5",))]),
        ],
        "racks": [],
        "structures": [],
        "zones": [],
    }


def tee(ref, node):
    return End("tee", ref, node, None, ref, "PipeTee")


def opc(kind, ref):
    return End(kind, ref, None, None, ref, "OffPageConnector")


# the header CWS-1 from the battery limit (BL) past the tees T1 and T2 to its users' end
# (a dead end the line list names "CW users"); the branches CWS-2 and CWS-3 to A and B
SEGMENTS = [
    seg("S1", "CWS-1", opc("opc_in", "OPC1"), tee("T1", 0), dn=400.0),
    seg("S2", "CWS-1", tee("T1", 1), tee("T2", 0), dn=400.0),
    seg("S3", "CWS-1", tee("T2", 1), opc("opc_out", "OPC2"), dn=400.0),
    seg("S4", "CWS-2", tee("T1", 2), nz("A")),
    seg("S5", "CWS-3", tee("T2", 2), nz("B")),
]
LINES = LineList.model_validate(
    {
        "lines": [
            {
                "number": "CWS-1",
                "from": "BL",
                "to": "CW users",
                "nominal_diameter": "DN400",
                "fluid": "Water",
            },
            {"number": "CWS-2", "from": "CWS-1", "to": "A", "nominal_diameter": "DN100"},
            {"number": "CWS-3", "from": "CWS-1", "to": "B", "nominal_diameter": "DN100"},
        ]
    }
)


def route(routing=None, site=None, segments=SEGMENTS):
    routing = Routing.model_validate(routing or {})
    return route_model(model(), segments, LINES, routing, plan=site if site else plan())


def first(p):
    return tuple(p["points"][0])


def last(p):
    return tuple(p["points"][-1])


def test_a_header_between_two_battery_limits_runs_the_rack_with_its_branches():
    result = route()
    assert result.unrouted == []
    s1, s2, s3, s4, s5 = (pipe(result, f"S{k}") for k in range(1, 6))
    # from one end of the rack to the other, on its tier (DN 400: the lowest), in a lane
    assert first(s1)[0] == pytest.approx(10) and last(s3)[0] == pytest.approx(110)
    assert all(abs(p[1] - 20) <= 2 and p[2] > 6 for p in (first(s1), last(s3)))
    assert s1["reason"] == "rack: battery limit at a rack end" and s1["racks"] == ["PR"]
    # the tees where the branches leave, each branch from its tee to its user
    assert last(s1) == first(s2) == first(s4) and last(s2) == first(s3) == first(s5)
    assert last(s1)[0] == pytest.approx(40, abs=2) and last(s2)[0] == pytest.approx(80, abs=2)
    assert last(s4) == (40, 11, 1) and last(s5) == (80, 11, 1)
    assert result.stats["battery_limits"] == {"rack end": 2}
    assert route().pipes == result.pipes  # deterministic


def test_the_rule_places_its_end_and_the_branches_keep_their_order():
    # the rule names the east end: the header's other end is the west end, and the line runs
    # the way its tees come (T1 near A in the west, T2 near B in the east)
    rules = {"battery_limits": [{"lines": ["CWS-1"], "rack": "PR", "rack_end": "end"}]}
    result = route({"rules": rules})
    assert result.unrouted == []
    s1, s2, s3 = (pipe(result, f"S{k}") for k in range(1, 4))
    assert first(s1)[0] == pytest.approx(10) and last(s3)[0] == pytest.approx(110)
    assert last(s1)[0] == pytest.approx(40, abs=2) and last(s2)[0] == pytest.approx(80, abs=2)
    assert result.stats["battery_limits"] == {"battery limit rule": 1, "rack end": 1}


def test_two_rules_place_both_ends():
    rules = {
        "battery_limits": [
            {"id": "BL-W", "lines": ["CWS-1"], "point": [0, 30, 6.5]},
            {"id": "CW-end", "lines": ["CWS-1"], "point": [95, 30, 6.5]},
        ]
    }
    result = route({"rules": rules})
    assert result.unrouted == []
    assert first(pipe(result, "S1")) == (0, 30, 6.5) and last(pipe(result, "S3")) == (95, 30, 6.5)
    assert result.stats["battery_limits"] == {"battery limit rule": 2}


def test_the_rack_and_elevation_intent_of_the_header():
    site = plan(
        racks=[
            {"id": "PR", "points": [[10, 20], [110, 20]], "width": 4, "levels": [6]},
            {"id": "PR-2", "points": [[10, 36], [110, 36]], "width": 4, "levels": [8]},
        ]
    )
    # without intent: the rack nearest the branches
    s1 = pipe(route(site=site), "S1")
    assert s1["racks"] == ["PR"]
    # the rack the line's intent names, on its tier intent
    s1 = pipe(route({"lines": [{"line": "CWS-1", "rack": "PR-2", "tier": 8}]}, site), "S1")
    assert s1["racks"] == ["PR-2"] and abs(first(s1)[1] - 36) <= 2
    assert first(s1)[2] == pytest.approx(8 + s1["od"] / 2)
    # buried along the rack's line: the ends at the rack ends, at the elevation
    result = route({"lines": [{"line": "CWS-1", "elevation": -3.0}]})
    s1, s3 = pipe(result, "S1"), pipe(result, "S3")
    assert first(s1) == (10, 20, -3.0) and last(s3) == (110, 20, -3.0)
    assert s1["reason"] == "intent: elevation" and result.unrouted == []


def test_a_pinned_header_segment_stays_and_wins():
    pinned = [[40, 25, 7], [80, 25, 7]]
    lines = [{"line": "CWS-1", "segment": "S2", "route": pinned}]
    result = route({"lines": lines})
    assert result.unrouted == []
    s1, s2, s3 = (pipe(result, f"S{k}") for k in range(1, 4))
    assert s2["method"] == "pinned" and [tuple(p) for p in s2["points"]] == [
        (40, 25, 7),
        (80, 25, 7),
    ]
    # the rest of the header runs from the pinned ends to the battery limits
    assert last(s1) == (40, 25, 7) and first(s3) == (80, 25, 7)


def test_each_branch_starts_exactly_where_its_header_is_cut_for_the_tee():
    # core#95: the battery limits sit on the rack centreline (y 20), off the header's lane (a
    # jog), and the users at non-round x; the run's cut and the branch's start were computed
    # apart and rounded to the millimetre on either side (39.053 against 39.052), so the
    # branch did not leave its header at the tee and was a 0.00 m layout-clash-pipe
    xs = [37.0525, 39.0525, 41.0525, 58.2175]
    n = len(xs)
    equipment = [
        item(
            f"U{k}",
            (x, 10, 1),
            (1.5, 2, 2),
            [nozzle(f"U{k}", "N1", [x, 11, 1], [0, 1, 0], [f"B{k}"])],
        )
        for k, x in enumerate(xs)
    ]
    segments = [seg("H0", "CWS-1", opc("opc_in", "OPC1"), tee("T0", 0), dn=400.0)]
    segments += [
        seg(f"H{k}", "CWS-1", tee(f"T{k - 1}", 1), tee(f"T{k}", 0), dn=400.0) for k in range(1, n)
    ]
    segments.append(seg(f"H{n}", "CWS-1", tee(f"T{n - 1}", 1), opc("opc_out", "OPC2"), dn=400.0))
    segments += [seg(f"B{k}", f"CWS-{k + 2}", tee(f"T{k}", 2), nz(f"U{k}")) for k in range(n)]
    lines = LineList.model_validate(
        {
            "lines": [{"number": "CWS-1", "from": "BL", "to": "BL", "nominal_diameter": "DN400"}]
            + [
                {
                    "number": f"CWS-{k + 2}",
                    "from": "CWS-1",
                    "to": f"U{k}",
                    "nominal_diameter": "DN100",
                }
                for k in range(n)
            ]
        }
    )
    limits = [
        {"id": "W", "lines": ["CWS-1"], "point": [10, 20, 6.203]},
        {"id": "E", "lines": ["CWS-1"], "point": [110, 20, 6.203]},
    ]
    routing = Routing.model_validate({"rules": {"battery_limits": limits}})
    model_ = {"equipment": equipment, "racks": [], "structures": [], "zones": []}
    result = route_model(model_, segments, lines, routing, plan=plan())
    assert result.unrouted == []
    h0 = pipe(result, "H0")
    assert first(h0) == (10, 20, 6.203) and first(h0)[1] != h0["points"][-1][1]  # the jog
    model_["pipes"] = _round(result.pipes)  # as written to layout/plant-model.yaml
    written = {p["segment"]: p for p in model_["pipes"]}
    for k, x in enumerate(xs):
        header, after, branch = (
            pipe(result, f"H{k}"),
            pipe(result, f"H{k + 1}"),
            pipe(result, f"B{k}"),
        )
        assert last(header) == first(after) == first(branch)  # one point, before rounding
        assert last(header)[0] == pytest.approx(x)
        assert written[f"H{k}"]["points"][-1] == written[f"B{k}"]["points"][0]  # and after
    clashes = [f for f in model_rules(model_, routing) if f.rule == "cheme.layout-clash-pipe"]
    assert clashes == []


def test_split_at_many_shares_each_cut_point():
    route = [(20.0, 110.0, -3.8), (124.0, 110.0, -3.8), (124.0, 108.5, -3.8), (295.0, 108.5, -3.8)]
    cuts = [108.55676565, 201.1525, 203.1525, 205.1525, 223.205]
    pieces, points = split_at_many(route, cuts)
    assert len(pieces) == len(cuts) + 1 and pieces[0][0] == route[0] and pieces[-1][-1] == route[-1]
    for k, point in enumerate(points):
        assert pieces[k][-1] is point and pieces[k + 1][0] is point
    assert points[1] == point_at(route, cuts[1])[0]  # the tee where a branch starts (ammonia-1)
    assert pieces[0] == [route[0], route[1], route[2], points[0]]
    # a point another pipe already starts at, within 1 µm of the cut, is the cut point
    near = (points[2][0] + 4e-7, 108.5, -3.8)
    assert split_at_many(route, cuts, [None, None, near, None, None])[1][2] is near
    assert split_at_many(route, [], [])[0] == [route]


@pytest.mark.parametrize(
    ("routing", "site", "why"),
    [
        ({}, SitePlan.model_validate({"site": {"width": 120, "depth": 40}}), "no rack in the "),
        (
            {"rules": {"battery_limits": [{"lines": ["CWS-1"], "point": [5, 5, 3]}]}},
            SitePlan.model_validate({"site": {"width": 120, "depth": 40}}),
            "a battery_limits point for each end",
        ),
        (
            {
                "rules": {
                    "battery_limits": [
                        {"lines": ["CWS-1"], "rack": "PR", "rack_end": "start"},
                        {"fluids": ["water"], "rack": "PR", "rack_end": "start"},
                    ]
                }
            },
            None,
            "both placed at the same point",
        ),
        ({"lines": [{"line": "CWS-1", "rack": "PR-9"}]}, None, "rack intent PR-9 is not a rack"),
        (
            {"rules": {"battery_limits": [{"lines": ["CWS-1"], "rack": "PR-9"}]}},
            None,
            "rack PR-9 is not in the site plan",
        ),
    ],
)
def test_a_header_that_cannot_be_placed_says_why(routing, site, why):
    result = route(routing, site)
    header = [u for u in result.unrouted if u["line"] == "CWS-1"]
    assert len(header) == 3
    reason = header[0]["reason"]
    assert reason.startswith("battery limits at both ends (BL and CW users): ") and why in reason
    # the branches wait for the tees no route reaches
    assert {u["line"] for u in result.unrouted} == {"CWS-1", "CWS-2", "CWS-3"}
