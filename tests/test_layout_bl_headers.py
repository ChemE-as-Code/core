"""A line with battery limits at both ends (core#72): a header from a battery limit to a battery
limit along a rack, with branches teeing off it to their users."""

from __future__ import annotations

import pytest

from chemeascode.domains.piping.schemas.lines import LineList
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
