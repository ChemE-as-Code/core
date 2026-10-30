"""Buried lines (core#70): ``buried`` in piping/routing.yaml takes the runs below grade out of the
headroom, clash and span rules and checks their cover instead; the take-off tells them apart."""

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.mto import take_off
from chemeascode.domains.spatial.gates import CLASH_RULES
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.pins import pin
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import LineRouting, ModelPipe, Routing
from tests.test_layout_3d import a_pipe, model_with, nz, pipe, seg, two_items
from tests.test_layout_pins import _PIPES, _routing

ROAD = {"id": "R-5", "points": [[10, -10], [10, 30]], "width": 6}
#: A DN 1400 header (OD 1.422 m) crossing road R-5 at -3.0 m, as in ammonia-1.
HEADER = [[0, 5, -3.0], [20, 5, -3.0]]


def found(model, routing=None):
    return {(f.rule, f.key): f for f in model_rules(model, routing=routing)}


def header(**extra):
    return model_with([a_pipe("P-114/CWS", HEADER, od=1.422, line="CWS-1", **extra)], roads=[ROAD])


# -- schema --------------------------------------------------------------------------------------


def test_buried_intent_in_routing_yaml():
    assert LineRouting.model_validate({"line": "CW-1", "buried": True}).buried is not None
    assert LineRouting.model_validate({"line": "CW-1", "buried": False}).buried is None
    entry = LineRouting.model_validate(
        {"line": "CW-1", "elevation": -1.8, "buried": {"cover_m": 1.0, "basis": "D-038"}}
    )
    assert entry.buried.cover_m == 1.0 and entry.buried.basis == "D-038"
    for bad in (
        {"buried": {"cover_m": 0}},
        {"buried": {"depth": 1}},
        {"buried": True, "rack": "PR-1"},
        {"buried": True, "elevation": 3.5},
    ):
        with pytest.raises(ValidationError):
            LineRouting.model_validate({"line": "CW-1", **bad})
    assert Routing.model_validate({}).rules.road_cover_m == 1.2
    with pytest.raises(ValidationError):
        Routing.model_validate({"rules": {"road_cover_m": -1}})
    # the model's pipe carries it
    ModelPipe.model_validate(
        {
            "id": "P/S1",
            "source": "generated",
            "line": "CW-1",
            "segment": "S1",
            "dn": 100,
            "od": 0.114,
            "insulation_mm": 0,
            "points": [[0, 0, -1], [1, 0, -1]],
            "length": 1,
            "method": "via",
            "buried": {"cover_m": 1.0},
        }
    )


def test_the_router_copies_the_intent_onto_the_pipes():
    model = two_items()
    segments = [seg("S1", "CW-1", nz("A"), nz("B")), seg("S2", "CW-2", nz("A"), nz("B"))]
    routing = Routing.model_validate(
        {
            "lines": [
                {"line": "CW-1", "elevation": -1.8, "buried": {"cover_m": 1.0}},
                {"line": "CW-2", "segment": "S2", "buried": True},
            ]
        }
    )
    result = route_model(model, segments, routing=routing)
    assert pipe(result, "S1")["buried"] == {"cover_m": 1.0}
    assert pipe(result, "S2")["buried"] == {}
    # without the field the pipes are as before
    plain = route_model(model, segments)
    assert all("buried" not in p for p in plain.pipes)


def test_a_pinned_route_keeps_the_entrys_buried(tmp_path):
    path = _routing(
        tmp_path, "lines:\n  - {line: L-1, segment: S1, elevation: -1.5, buried: {cover_m: 1}}\n"
    )
    pin(tmp_path, _PIPES, "L-1")
    (entry,) = yaml.safe_load(path.read_text())["lines"]
    assert entry["buried"] == {"cover_m": 1} and "elevation" not in entry


# -- headroom and cover --------------------------------------------------------------------------


def test_a_buried_road_crossing_is_no_headroom_finding():
    before = found(header())
    assert ("cheme.layout-headroom", "P-114/CWS+R-5") in before  # -3.71 m clear
    after = found(header(buried={}))
    assert not any(rule == "cheme.layout-headroom" for rule, _ in after)
    assert not any(rule == "cheme.layout-buried-cover" for rule, _ in after)  # 2.29 m cover


def test_too_little_cover_under_a_road():
    shallow = model_with(
        [a_pipe("P1", [[0, 5, -0.5], [20, 5, -0.5]], od=0.3, line="CW-1", buried={})],
        roads=[ROAD],
    )
    finding = found(shallow)[("cheme.layout-buried-cover", "P1+R-5")]
    assert finding.level == "warning" and finding.ids == ["P1", "R-5"]
    assert finding.measured == pytest.approx(0.35)
    assert "less than 1.2 m (rules.road_cover_m, ASSUMED)" in finding.message
    assert "piping/routing.yaml" in finding.hint and finding.box[5] == 0.0
    assert finding.rule in CLASH_RULES  # the layout gates' clashes requirement
    # off the road nothing is declared: no finding there
    assert ("cheme.layout-buried-cover", "P1") not in found(shallow)
    # the site's own least cover replaces the ASSUMED one
    routing = Routing.model_validate({"rules": {"road_cover_m": 0.3}})
    assert ("cheme.layout-buried-cover", "P1+R-5") not in found(shallow, routing)
    # a declared cover applies along the whole buried run, and under the road if larger
    shallow["pipes"][0]["buried"] = {"cover_m": 1.5}
    findings = found(shallow, routing)
    assert "1.5 m (its declared cover_m)" in findings[("cheme.layout-buried-cover", "P1")].message
    assert ("cheme.layout-buried-cover", "P1+R-5") in findings


def test_risers_and_runs_above_grade_are_pipes_like_any_other():
    # a buried branch rising to its user: the riser through grade has no cover finding, the
    # run at grade over the road has the headroom finding
    points = [[0, 5, -1.8], [5, 5, -1.8], [5, 5, 0.5], [20, 5, 0.5]]
    model = model_with(
        [a_pipe("P1", points, od=0.3, line="CW-1", buried={"cover_m": 1.0})], roads=[ROAD]
    )
    rules = {rule for rule, _ in found(model)}
    assert "cheme.layout-headroom" in rules and "cheme.layout-buried-cover" not in rules


# -- clashes and spans ---------------------------------------------------------------------------


def column(x, y, z0=0.0):
    member = {
        "id": "S/col",
        "kind": "member",
        "material": "steel",
        "start": [x, y, z0],
        "end": [x, y, 6],
        "profile": [0.3, 0.3],
    }
    return [{"id": "S", "parts": [member]}]


def test_buried_runs_meet_no_steel_or_item_above_grade():
    # a pipe whose top is at grade, under a column standing on grade (its member reaches a
    # radius below its foot) and under an item standing on grade
    points = [[0, 8, -0.16], [20, 8, -0.16]]
    model = model_with([a_pipe("P1", points, od=0.3)], structures=column(8, 8))
    model["equipment"][0]["parts"][0].update(centre=[16, 8, 1], size=[2, 2, 2])
    assert ("cheme.layout-clash-pipe-steel", "P1+S/col") in found(model)
    model["pipes"][0]["buried"] = {}
    after = {rule for rule, _ in found(model)}
    assert "cheme.layout-clash-pipe-steel" not in after
    assert "cheme.layout-clash-pipe-equipment" not in after
    # a footing below grade still clashes
    model["structures"] = column(8, 8, z0=-1.0)
    assert ("cheme.layout-clash-pipe-steel", "P1+S/col") in found(model)


def test_buried_level_runs_need_no_supports():
    points = [[0, 5, -1.8], [40, 5, -1.8]]
    model = model_with([a_pipe("P1", points, od=0.3, dn=300, fluid="Cooling water")])
    assert ("cheme.layout-support-missing", "P1") in found(model)
    model["pipes"][0]["buried"] = {}
    assert ("cheme.layout-support-missing", "P1") not in found(model)


# -- take-off ------------------------------------------------------------------------------------


def test_the_takeoff_tells_buried_pipe():
    points = [[0, 0, -1.8], [10, 0, -1.8], [10, 0, 1.2], [12, 0, 1.2]]
    p = a_pipe("P1", points, od=0.3, dn=300)
    rows = {r.key: r.quantity for r in take_off({"pipes": [p]}).rows if r.category == "pipe"}
    assert rows == {"pipe DN300 bare": pytest.approx(15)}
    p["buried"] = {}
    rows = {r.key: r.quantity for r in take_off({"pipes": [p]}).rows if r.category == "pipe"}
    # 10 m level and the riser up to where its top reaches grade (1.8 - 0.15 m)
    assert rows == {
        "pipe DN300 bare buried": pytest.approx(11.65),
        "pipe DN300 bare": pytest.approx(3.35),
    }
