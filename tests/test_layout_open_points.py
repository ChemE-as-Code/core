"""Open points of the layout reviews: pipe ends that do not meet their connection, lane
stability under pins, stale acceptances, rack intermediate steel and valve access platforms."""

from __future__ import annotations

import math

import pytest

from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import Routing, SitePlan
from tests import test_layout_3d
from tests.test_layout_3d import a_pipe, item, model_with, nozzle, nz, pipe, seg, tee, two_items

plant3d = test_layout_3d.plant3d  # the fixture: a plant with a vessel, a pump and a rack


def found(model, rule, **kw):
    return [f for f in model_rules(model, **kw) if f.rule == f"cheme.layout-{rule}"]


# -- 1. pipe ends meet their connections -----------------------------------------------------


def test_a_pipe_end_off_its_nozzle_is_an_error():
    ends = [{"kind": "nozzle", "ref": "A/N1"}, {"kind": "nozzle", "ref": "B/N1"}]
    good = a_pipe("P1", [[3, 5, 1], [8, 5, 1], [13, 5, 1]], ends=ends, source="pinned")
    assert found(model_with([good]), "pipe-disconnected") == []
    off = a_pipe("P1", [[3, 5, 1], [8, 5, 1], [12.5, 5, 1]], ends=ends, source="pinned")
    (finding,) = found(model_with([off]), "pipe-disconnected")
    assert finding.level == "error" and finding.ids == ["P1"]
    assert "pinned pipe P1" in finding.message and "0.500 m from nozzle B/N1" in finding.message
    assert finding.key == "P1+end" and "layout pin" in finding.hint


def test_a_branch_that_does_not_start_on_its_run_is_an_error():
    run_ends = [{"kind": "nozzle", "ref": "A/N1"}, {"kind": "junction", "ref": "pid/P-01.xml:T1"}]
    run2_ends = [{"kind": "junction", "ref": "pid/P-01.xml:T1"}, {"kind": "nozzle", "ref": "B/N1"}]
    branch_ends = [{"kind": "junction", "ref": "pid/P-01.xml:T1"}, {"kind": "open"}]
    run = [
        a_pipe("R1", [[3, 5, 1], [8, 5, 1]], ends=run_ends),
        a_pipe("R2", [[8, 5, 1], [13, 5, 1]], ends=run2_ends),
    ]
    on = a_pipe("BR", [[8, 5, 1], [8, 5, 4]], ends=branch_ends)
    assert found(model_with([*run, on]), "pipe-disconnected") == []
    away = a_pipe("BR", [[8, 5.6, 1], [8, 5.6, 4]], ends=branch_ends)
    (finding,) = found(model_with([*run, away]), "pipe-disconnected")
    assert finding.ids == ["BR"] and "T1 on P-01" in finding.message
    assert finding.key == "BR+start"


def test_a_model_without_pipe_ends_has_no_connectivity_findings():
    off = a_pipe("P1", [[3, 5, 1], [12.5, 5, 1]])
    assert found(model_with([off]), "pipe-disconnected") == []


def test_the_router_records_what_each_pipe_end_meets():
    model = two_items()
    model["equipment"].append(
        item("D", (8, 14, 1), (2, 2, 2), [nozzle("D", "N1", [8, 13, 1], [0, -1, 0], ("S3",))])
    )
    segments = [
        seg("S1", "L-1", nz("A"), tee(0)),
        seg("S2", "L-1", tee(1), nz("B")),
        seg("S3", "L-1", tee(2), nz("D")),
    ]
    result = route_model(model, segments)
    assert pipe(result, "S1")["ends"] == [
        {"kind": "nozzle", "ref": "A/N1"},
        {"kind": "junction", "ref": "pid/P-01.xml:T1"},
    ]
    built = model_with(result.pipes)
    built["equipment"] = model["equipment"]
    assert found(built, "pipe-disconnected") == []


def test_a_pinned_branch_off_the_run_is_found_and_one_on_it_is_met():
    """A pinned branch whose start is not on the run's route is an error; one whose start
    lies on it gets its tee there (the run is cut at the pinned start)."""
    model = two_items()
    model["equipment"].append(
        item("D", (8, 14, 1), (2, 2, 2), [nozzle("D", "N1", [8, 13, 1], [0, -1, 0], ("S3",))])
    )
    segments = [
        seg("S1", "L-1", nz("A"), tee(0)),
        seg("S2", "L-1", tee(1), nz("B")),
        seg("S3", "L-1", tee(2), nz("D")),
    ]
    free = route_model(model, segments)
    run = [tuple(p) for p in pipe(free, "S1")["points"]] + [
        tuple(p) for p in pipe(free, "S2")["points"][1:]
    ]
    # the middle of the run's longest level piece
    a, b = max(zip(run, run[1:], strict=False), key=lambda ab: abs(ab[0][0] - ab[1][0]))
    start = ((a[0] + b[0]) / 2, a[1], a[2])
    for branch_start, broken in ((start, False), ((start[0], start[1] + 0.7, start[2]), True)):
        x, y, z = branch_start
        route = [[x, y, z], [x, 12.0, z], [8, 12.0, z], [8, 12.0, 1], [8, 13, 1]]
        routing = Routing.model_validate(
            {"lines": [{"line": "L-1", "segment": "S3", "route": route}]}
        )
        result = route_model(model, segments, routing=routing)
        built = model_with(result.pipes)
        built["equipment"] = model["equipment"]
        findings = found(built, "pipe-disconnected")
        assert bool(findings) is broken, findings
        if broken:
            assert findings[0].ids == ["P-01/S3"] and "pinned pipe" in findings[0].message


# -- 2. lane stability -----------------------------------------------------------------------


def lane_plot():
    return SitePlan.model_validate(
        {
            "site": {"width": 120, "depth": 40},
            "racks": [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 6, "levels": [6]}],
        }
    )


def lane_model():
    """Four items south of a 100 m rack, four on the north side at the far end: four lines
    over the rack."""
    equipment = []
    for k in range(4):
        west = nozzle(f"W{k}", "N1", [8 + 4 * k, 11, 1], [0, 1, 0], (f"S{k}",))
        east = nozzle(f"E{k}", "N1", [100 + 4 * k, 29, 1], [0, -1, 0], (f"S{k}",))
        equipment.append(item(f"W{k}", (8 + 4 * k, 10, 1), (2, 2, 2), [west]))
        equipment.append(item(f"E{k}", (100 + 4 * k, 30, 1), (2, 2, 2), [east]))
    return {"equipment": equipment, "racks": [], "structures": [], "zones": []}


def lane_segments():
    sizes = (300.0, 200.0, 150.0, 100.0)
    return [seg(f"S{k}", f"L-{k}", nz(f"W{k}"), nz(f"E{k}"), dn=dn) for k, dn in enumerate(sizes)]


def same(a, b):
    """Two routes with the same points to the millimetre (a pin is written to the mm)."""
    return len(a) == len(b) and all(
        abs(u - v) <= 0.0015 for p, q in zip(a, b, strict=True) for u, v in zip(p, q, strict=True)
    )


def test_pinning_a_route_leaves_the_other_lanes_as_they_were():
    plan = lane_plot()
    free = route_model(lane_model(), lane_segments(), plan=plan)
    assert all(p["racks"] == ["PR"] for p in free.pipes)
    before = {p["segment"]: p for p in free.pipes}
    for k in range(4):
        route = [[round(v, 3) for v in p] for p in before[f"S{k}"]["points"]]
        pinned = {"line": f"L-{k}", "segment": f"S{k}", "route": route}
        routing = Routing.model_validate({"lines": [pinned]})
        result = route_model(lane_model(), lane_segments(), routing=routing, plan=plan)
        assert pipe(result, f"S{k}")["source"] == "pinned"
        for p in result.pipes:
            old = before[p["segment"]]
            # the pinned pipe keeps its racks and tier (its rack steel carries it)
            assert (p["tier"], p["racks"]) == (old["tier"], old["racks"])
            if p["segment"] == f"S{k}":
                continue
            # not a hair: the pinned lane is the lane the router took, on the millimetre
            assert p["points"] == old["points"], f"pinning S{k} moved {p['segment']}"
        # the pinned pipe's lane still counts in the rack fill
        fill = result.stats["rack_fill"]
        assert [(f["rack"], f["tier"]) for f in fill] == [("PR", 6.0)]
        assert abs(fill[0]["used_m"] - free.stats["rack_fill"][0]["used_m"]) < 0.002


def test_rack_lanes_are_on_the_millimetre_and_keep_their_spacing():
    free = route_model(lane_model(), lane_segments(), plan=lane_plot())
    runs = []
    for p in free.pipes:
        (run,) = [
            (a, b)
            for a, b in zip(p["points"], p["points"][1:], strict=False)
            if abs(a[0] - b[0]) > 50
        ]
        offset = run[0][1] - 20
        assert abs(offset * 1000 - round(offset * 1000)) < 1e-6
        runs.append((offset, p["od"] / 2 + p.get("insulation_mm", 0) / 1000))
    runs.sort()
    for (y0, r0), (y1, r1) in zip(runs, runs[1:], strict=False):
        assert y1 - y0 >= r0 + r1 + 0.1 - 1e-6  # spacing_m kept between neighbours


def test_a_junction_cut_is_exact_and_does_not_jump_with_a_hair_of_length():
    from chemeascode.domains.spatial.routing import _project

    # a 10.5 m run: as routed, and as a pinned copy rounded a hair longer
    target = (5.0, 7.3, 0.0)
    for end in (10.5, 10.5000004, 10.4999996):
        route = [(5.0, 0.0, 3.0), (5.0, end, 3.0)]
        assert abs(_project(route, target) - 7.3) < 1e-6  # exact, not a 0.5 m sample
    # a level run past the target: where it passes the target's x (an orthogonal branch)
    assert _project([(0.0, 0.0, 3.0), (10.0, 0.0, 3.0), (10.0, 8.0, 3.0)], (3.7, 5.0, 1.0)) == 3.7


def test_a_pinned_rack_run_gets_no_post_from_grade():
    """A pinned route keeps the racks it runs on: its tier run is carried by the rack's
    intermediate steel, as the routed one was, not by a post from grade inside the rack."""
    from chemeascode.domains.spatial.piping_detail import support_proposals

    plan = lane_plot()
    free = route_model(lane_model(), lane_segments(), plan=plan)
    racks = [{"id": "PR", "points": [[10, 20], [110, 20]], "width": 6, "levels": [6.0]}]
    small = {p["segment"]: p for p in free.pipes}["S3"]
    route = [[round(v, 3) for v in p] for p in small["points"]]
    routing = Routing.model_validate({"lines": [{"line": "L-3", "segment": "S3", "route": route}]})
    result = route_model(lane_model(), lane_segments(), routing=routing, plan=plan)
    lane_y = next(a[1] for a, b in zip(route, route[1:], strict=False) if abs(a[0] - b[0]) > 50)
    found_ = []
    for pipes in (free.pipes, result.pipes):
        model = {"pipes": pipes, "racks": racks, "supports": [], "support_steel": []}
        posts = [s for s in support_proposals(model) if s["serves"] == ["P-01/S3"]]
        # none under the 90 m lane run on the tier (posts under its cross-overs stay)
        assert not [s for s in posts if abs(s["at"][1] - lane_y) < 0.01 and 21 < s["at"][0] < 109]
        found_.append([(s["at"], s["top"]) for s in posts])
    assert len(found_[0]) == len(found_[1])
    for (a, top_a), (b, top_b) in zip(*found_, strict=True):  # the pin is written to the mm
        assert math.dist(a, b) < 0.002 and abs(top_a - top_b) < 0.002


def test_a_pinned_route_in_the_way_of_a_larger_line_is_still_avoided():
    """A pin routed before nothing (a smaller line) that crosses where a larger line would
    run is an obstacle for it all the same: the larger line keeps the spacing."""
    plan = lane_plot()
    crossing = [[60, 12, 6.2], [60, 19, 6.2], [60, 19, 12]]
    routing = Routing.model_validate(
        {"lines": [{"line": "L-3", "segment": "S3", "route": crossing}]}
    )
    result = route_model(lane_model(), lane_segments(), routing=routing, plan=plan)
    from tests.test_layout_router_fixes import clearance

    pinned = pipe(result, "S3")
    for k in range(3):
        assert clearance(pipe(result, f"S{k}"), pinned) >= 0.1 - 0.011


# -- 3. stale acceptances --------------------------------------------------------------------


def tray_finding(length):
    from chemeascode.foundation.findings import Finding

    return Finding(
        "layout/plant-model.yaml",
        "warning",
        "cheme.layout-tray-span",
        f"power tray PT-1 runs {length:.1f} m level with no steel",
        ids=["PT-1"],
        key="PT-1",
        measured=length,
    )


def test_a_quoted_length_off_the_measured_one_is_stale():
    from chemeascode.foundation.acceptance import stale_quote

    reason = "6.6 m branch tray: 2 posts at no more than 3 m spacing (ASSUMED)"
    assert stale_quote(reason, tray_finding(6.6)) is None
    assert stale_quote(reason, tray_finding(6.65)) is None  # within 0.1 m
    assert stale_quote(reason, tray_finding(6.1)) == 6.6
    # a reason that quotes no length, a finding that measures none: nothing to compare
    assert stale_quote("hung from the roof steel", tray_finding(6.1)) is None
    unmeasured = tray_finding(6.1)
    unmeasured.measured = None
    assert stale_quote(reason, unmeasured) is None
    # millimetres, areas and flows are no lengths in metres
    assert stale_quote("a 6 mm plate, 4 m2, 300 m3/h", tray_finding(6.1)) is None
    # 2 % of a long run
    assert stale_quote("19.8 m branch", tray_finding(20.1)) is None
    assert stale_quote("19.8 m branch", tray_finding(20.5)) == 19.8


ID = "layout/plant-model.yaml#layout-tray-span:"


def test_validate_reports_a_stale_acceptance(plant, monkeypatch):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project import validate as v

    (plant / "checks" / "checks.yaml").write_text(
        "checks: []\naccept:\n"
        f"  - {{id: '{ID}PT-1', reason: '6.6 m tray on posts'}}\n"
        f"  - {{id: '{ID}PT-2', reason: '6.1 m tray on posts'}}\n",
        encoding="utf-8",
    )
    current = tray_finding(6.1)
    other = tray_finding(6.1)
    other.ids, other.key = ["PT-2"], "PT-2"
    report = v.Report(findings=[current, other])
    v._accept(Workspace(plant), report, full=False)
    assert current.level == "info" and other.level == "info"  # still accepted
    (stale,) = [f for f in report.findings if f.rule == "cheme.accept-stale"]
    assert stale.level == "warning" and stale.file == "checks/checks.yaml"
    assert stale.ids == ["layout/plant-model.yaml#layout-tray-span:PT-1"]
    assert "quotes 6.6 m" in stale.message and "6.10 m" in stale.message


def test_a_stale_wildcard_acceptance_names_each_finding(plant, monkeypatch):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project import validate as v

    (plant / "checks" / "checks.yaml").write_text(
        f"checks: []\naccept:\n  - {{id: '{ID}PT-*', reason: 'runs up to 7.0 m on posts'}}\n",
        encoding="utf-8",
    )
    one, two = tray_finding(13.75), tray_finding(30.75)
    two.ids, two.key = ["PT-2"], "PT-2"
    report = v.Report(findings=[one, two])
    v._accept(Workspace(plant), report, full=False)
    stale = [f for f in report.findings if f.rule == "cheme.accept-stale"]
    # one finding each, with its own id (accepted or fixed one by one), naming the finding
    assert len({f.id for f in stale}) == 2
    assert [f.ids for f in stale] == [[f"{ID}PT-*", one.id], [f"{ID}PT-*", two.id]]
    assert one.id in stale[0].message and "13.75 m" in stale[0].message
    assert stale[1].id.endswith(f"@{two.id}")


def test_span_and_tray_findings_carry_their_measured_length():
    span = a_pipe("P1", [[0, 0, 3], [20, 0, 3]], dn=50.0)
    (missing,) = found(model_with([span]), "support-missing")
    assert missing.measured == 20.0


# -- 4. intermediate rack steel and support steel --------------------------------------------


def a_rack(**extra):
    from chemeascode.domains.spatial.schemas import Rack

    data = {"id": "R", "points": [[0, 0], [24, 0]], "width": 2.0, "levels": [5.0, 7.0], **extra}
    return Rack.model_validate(data)


def test_a_rack_has_no_intermediate_steel_unless_declared():
    from chemeascode.domains.spatial.structures import rack_steel

    plain = [p["id"] for p in rack_steel(a_rack(), 6.0)]
    assert not any("/bay-" in i for i in plain)
    parts = rack_steel(a_rack(intermediate_supports={"spacing_m": 3.0, "levels": [7.0]}), 6.0)
    ids = [p["id"] for p in parts]
    # bents every 6 m (5 of them), plain parts unchanged
    assert [i for i in ids if "/bay-" not in i] == plain
    mids = [p for p in parts if "/mid-" in p["id"]]
    assert [p["id"] for p in mids] == [f"R/bay-{k}/mid-1/beam-7" for k in range(4)]
    for beam in mids:  # across the rack, top of steel at the tier
        assert abs(beam["start"][2] + beam["profile"][1] / 2 - 7.0) < 1e-9
        assert abs(beam["start"][0] - beam["end"][0]) < 1e-9
    stringers = [p for p in parts if "/stringer-" in p["id"]]
    assert len(stringers) == 4 * 2 * 2  # bays x sides x pieces
    assert all("-5-" not in p["id"].split("/")[-1] for p in stringers)  # only the 7 m tier


def test_no_intermediate_steel_across_a_branch_rack_joint():
    """Where a branch rack joins, its lanes cross this rack's edge below its tiers: the edge
    stringers and mid beams there are left out (as the branch's first bent is), else the
    branch's lines run through them (the ASU's PR2 under the PR1 north edge)."""
    from chemeascode.domains.spatial.schemas import Rack
    from chemeascode.domains.spatial.structures import rack_steel

    main = a_rack(intermediate_supports={"spacing_m": 3.0})
    branch = Rack.model_validate(
        {"id": "B", "points": [[9, 0], [9, 20]], "width": 2.0, "levels": [4.5, 6.5]}
    )
    alone = {p["id"] for p in rack_steel(main, 6.0)}
    joined = {p["id"] for p in rack_steel(main, 6.0, others=[branch])}
    gone = alone - joined
    # the north edge stringers of bay 1 (6 .. 12 m) where B (x 8 .. 10, from y 0 north)
    # crosses, and the mid beam at 9 m reaching into B's strip; the south edge stays
    assert gone and all("/bay-1/" in i for i in gone)
    assert "R/bay-1/mid-1/beam-7" in gone
    # a tier with no branch tier just below it keeps its steel across the joint
    high = Rack.model_validate(
        {"id": "B", "points": [[9, 0], [9, 20]], "width": 2.0, "levels": [6.5]}
    )
    kept = {p["id"] for p in rack_steel(main, 6.0, others=[high])}
    assert "R/bay-1/mid-1/beam-5" in kept and "R/bay-1/mid-1/beam-7" not in kept
    for part in rack_steel(main, 6.0, others=[branch]):
        if "/stringer-" in part["id"] and part["start"][1] > 0:
            xs = (part["start"][0], part["end"][0])
            assert max(xs) <= 8.0 + 1e-6 or min(xs) >= 10.0 - 1e-6


def test_a_joint_keeps_the_main_racks_bent():
    """A branch rack joining in the middle of a main rack: the main rack's bent there stays
    (it was left out with the branch's first one, so nothing carried the main rack's lines
    across the joint, the ASU's PR1 at PR2); the branch's first bent is left out."""
    from chemeascode.domains.spatial.schemas import Rack
    from chemeascode.domains.spatial.structures import rack_steel

    def bents(rack, others):
        ids = {p["id"].split("/")[1] for p in rack_steel(rack, 6.0, others)}
        return sorted(i for i in ids if i.startswith("bent-"))

    main = a_rack()  # x 0 .. 24, bents at 0, 6, 12, 18, 24
    tee = Rack.model_validate(
        {"id": "T", "points": [[12, 0], [12, 12]], "width": 2.0, "levels": [6.5]}
    )
    assert bents(main, [tee]) == [f"bent-{k}" for k in range(5)]
    assert bents(tee, [main]) == ["bent-1", "bent-2"]


def test_intermediate_levels_must_be_tiers_of_the_rack():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="no tiers of the rack"):
        a_rack(intermediate_supports={"levels": [6.0]})


def rack_document(rack, pipe_points, dn=50.0):
    from chemeascode.domains.spatial.structures import rack_steel

    return {
        "racks": [
            {
                "id": "R",
                "points": rack.points,
                "width": 2.0,
                "levels": rack.levels,
                "parts": rack_steel(rack, 6.0),
            }
        ],
        "structures": [],
        "pipes": [
            a_pipe("P-01/S1", pipe_points, od=0.0603, dn=dn, fluid="Air", racks=["R"], segment="S1")
        ],
    }


def test_intermediate_rack_steel_shortens_the_spans_of_small_lines():
    from chemeascode.domains.spatial.piping_detail import support_proposals, supports

    run = [[0.5, 0.0, 7.03015], [23.5, 0.0, 7.03015]]  # DN 50 on the 7 m tier
    plain = rack_document(a_rack(), run)
    plain["supports"] = supports(plain)
    assert [round(s["point"][0], 3) for s in plain["supports"]] == [6, 12, 18]
    assert found(as_model(plain), "free-span")  # 6 m > 4 m (gas)
    # no support steel is proposed on a rack tier: intermediate steel answers it
    assert support_proposals(plain) == []
    steel = rack_document(a_rack(intermediate_supports={"spacing_m": 3.0}), run)
    steel["supports"] = supports(steel)
    assert len(steel["supports"]) == 7
    assert found(as_model(steel), "free-span") == []


def as_model(document):
    return model_with(document["pipes"], **{k: v for k, v in document.items() if k != "pipes"})


def long_run_document():
    pipe = a_pipe("P-01/S1", [[0, 20, 3.0], [12, 20, 3.0]], od=0.0603, dn=50.0, fluid="Air")
    pipe["segment"] = "S1"
    return {"racks": [], "structures": [], "pipes": [pipe], "supports": []}


def test_support_steel_is_proposed_under_a_bare_run():
    from chemeascode.domains.spatial.piping_detail import support_proposals

    document = long_run_document()
    proposals = support_proposals(document)
    # 12 m of DN 50 gas (4 m span): two posts at 4 and 8 m, T-posts from grade
    assert [p["id"] for p in proposals] == ["P-01/S1/SP-4.0", "P-01/S1/SP-8.0"]
    assert [p["at"] for p in proposals] == [(4.0, 20.0), (8.0, 20.0)]
    first = proposals[0]
    assert first["kind"] == "t_post" and first["base"] == 0.0 and first["review_needed"]
    assert first["top"] == round(3.0 - 0.0603 / 2 - 0.1, 3)  # under a 100 mm shoe
    assert first["rotation_deg"] == 90.0  # across the pipe
    assert "spans 12.0 m" in first["reason"]


def test_a_support_proposal_does_not_take_the_id_of_a_declared_post():
    from chemeascode.domains.spatial.piping_detail import support_proposals

    document = long_run_document()
    # the post at 4 m is declared (pinned under its id): it is not proposed again, and the
    # other keeps its own id (ids come from the pipe and the place, not a count)
    document["support_steel"] = [{"id": "P-01/S1/SP-4.0", "source": "declared"}]
    ids = [p["id"] for p in support_proposals(document)]
    assert ids == ["P-01/S1/SP-8.0"]
    # an id pinned under the older numbering stays a declared id and takes nothing from them
    document["support_steel"] = [{"id": "P-01/S1/post-1", "source": "declared"}]
    assert [p["id"] for p in support_proposals(document)] == ["P-01/S1/SP-4.0", "P-01/S1/SP-8.0"]


def test_support_proposal_ids_are_stable_across_builds():
    from chemeascode.domains.spatial.piping_detail import post_id, support_proposals

    first = [p["id"] for p in support_proposals(long_run_document())]
    again = [p["id"] for p in support_proposals(long_run_document())]
    assert first == again == [post_id("P-01/S1", 4.0), post_id("P-01/S1", 8.0)]


def test_a_support_proposal_keeps_clear_of_pipes_it_does_not_carry():
    from chemeascode.domains.spatial.piping_detail import support_proposals

    document = long_run_document()
    # a low pipe crossing under the run right where the post at 4 m would stand
    document["pipes"].append(
        a_pipe("P-01/S9", [[4.0, 15.0, 1.0], [4.0, 25.0, 1.0]], od=0.1143, dn=100.0)
    )
    first = support_proposals(document)[0]
    assert first["id"] == "P-01/S1/SP-4.0"  # named by its nominal place
    x = first["at"][0]
    assert abs(x - 4.0) - 0.1143 / 2 - 0.1 >= 0.1 - 1e-9  # column clear of S9 by 0.1 m
    assert "moved" in first["reason"] and "0.1 m" in first["reason"]
    # a larger clearance moves it farther
    wide = support_proposals(document, clearance=0.4)[0]
    assert abs(wide["at"][0] - 4.0) > abs(x - 4.0)
    # with no clear place in its span it stays and says so
    for k in range(-8, 9):
        document["pipes"].append(
            a_pipe(f"P-01/X{k}", [[4.0 + k * 0.2, 15, 1.0], [4.0 + k * 0.2, 25, 1.0]], od=0.06)
        )
    blocked = support_proposals(document, clearance=0.1)[0]
    assert blocked["at"] == (4.0, 20.0) and "place it by hand" in blocked["reason"]


def test_a_proposal_over_steel_is_a_stub_on_it():
    from chemeascode.domains.spatial.piping_detail import support_proposals
    from chemeascode.domains.spatial.structures import Frame

    document = long_run_document()
    beam = Frame((0.0, 0.0), 0.0).member(
        "S/L1/beam-y1", (4.0, 15.0, 1.4), (4.0, 25.0, 1.4), ("HEB200", 0.2, 0.2)
    )
    document["structures"] = [{"id": "S", "parts": [beam]}]
    first = support_proposals(document)[0]
    assert first["kind"] == "stub" and first["base"] == 1.5


def _support(sid, kind, at, top, base, serves, rotation=0.0):
    from types import SimpleNamespace

    from chemeascode.domains.spatial.structures import support_steel

    entry = {
        "id": sid,
        "refs": {"file": "layout/structures.yaml"},
        "source": "declared",
        "kind": kind,
        "at": list(at),
        "top": top,
        "base": base,
        "width": 1.0,
        "rotation_deg": rotation,
        "serves": serves,
    }
    entry["parts"] = support_steel(SimpleNamespace(**{**entry, "section": None}), base)
    return entry


def test_a_proposal_stands_on_steel_only_close_below_and_not_on_another_lines_post():
    from chemeascode.domains.spatial.piping_detail import support_proposals

    # the review's case: a T-post of another line 3.3 m up under a run at about 10.4 m
    document = long_run_document()
    for p in document["pipes"][0]["points"]:
        p[2] = 10.5
    document["support_steel"] = [
        _support("CW/post-1", "t_post", (4.0, 20.0), 3.3, 0.0, ["P-01/CW"], rotation=90.0)
    ]
    first = support_proposals(document)[0]
    assert first["id"] == "P-01/S1/SP-4.0"
    assert first["kind"] == "t_post" and first["base"] == 0.0  # not a 7 m stub on CW's post
    # the run's own post: a stub on it when close below
    document["support_steel"] = [
        _support("S1/post-1", "t_post", (4.0, 20.0), 9.5, 0.0, ["P-01/S1"], rotation=90.0)
    ]
    assert support_proposals(document)[0]["kind"] == "stub"
    # structure steel farther below than support_stub_max_m: a T-post from grade
    from chemeascode.domains.spatial.structures import Frame

    beam = Frame((0.0, 0.0), 0.0).member(
        "S/L1/beam-y1", (4.0, 15.0, 7.0), (4.0, 25.0, 7.0), ("HEB200", 0.2, 0.2)
    )
    document["support_steel"] = []
    document["structures"] = [{"id": "S", "parts": [beam]}]
    assert support_proposals(document)[0]["kind"] == "t_post"
    assert support_proposals(document, stub_max=4.0)[0]["kind"] == "stub"


def test_a_tall_stub_or_one_on_another_lines_post_is_a_finding():
    document = long_run_document()
    for p in document["pipes"][0]["points"]:
        p[2] = 10.5
    cw = _support("CW/post-1", "t_post", (4.0, 20.0), 3.3, 0.0, ["P-01/CW"], rotation=90.0)
    stub = _support("S1/SP-4.0", "stub", (4.0, 20.0), 10.37, 3.3, ["P-01/S1"])
    document["support_steel"] = [cw, stub]
    rules = found(as_model(document), "support-stub")
    assert len(rules) == 2
    tall = next(f for f in rules if "tall" in f.message)
    assert "7.07 m tall" in tall.message and tall.measured == pytest.approx(7.07)
    on = next(f for f in rules if "stands on" in f.message)
    assert "CW/post-1" in on.message and "P-01/CW" in on.message
    # a short stub on the post of another segment of its own line: none
    other = a_pipe("P-01/S2", [[4.0, 15.0, 9.9], [4.0, 25.0, 9.9]], od=0.0603, dn=50.0)
    other["line"] = document["pipes"][0]["line"]
    document["pipes"].append(other)
    own = _support("S2/post-1", "t_post", (4.0, 20.0), 9.8, 0.0, ["P-01/S2"])
    short = _support("S1/SP-4.0", "stub", (4.0, 20.0), 10.37, 9.8, ["P-01/S1"])
    document["support_steel"] = [own, short]
    assert found(as_model(document), "support-stub") == []
    document["pipes"].pop()
    # a short stub on structure steel: none
    from chemeascode.domains.spatial.structures import Frame

    beam = Frame((0.0, 0.0), 0.0).member(
        "S/L1/beam-y1", (4.0, 15.0, 9.4), (4.0, 25.0, 9.4), ("HEB200", 0.2, 0.2)
    )
    document["structures"] = [{"id": "S", "parts": [beam]}]
    document["support_steel"] = [_support("S1/SP-4.0", "stub", (4.0, 20.0), 10.37, 9.5, [])]
    assert found(as_model(document), "support-stub") == []


def test_a_proposal_to_place_by_hand_is_not_offered_for_pin():
    from types import SimpleNamespace

    from chemeascode.domains.spatial.piping_detail import support_proposals
    from chemeascode.domains.spatial.structures import support_steel

    document = long_run_document()
    for k in range(-8, 9):
        document["pipes"].append(
            a_pipe(f"P-01/X{k}", [[4.0 + k * 0.2, 15, 1.0], [4.0 + k * 0.2, 25, 1.0]], od=0.06)
        )
    proposals = support_proposals(document)
    for p in proposals:
        p["parts"] = support_steel(SimpleNamespace(**{**p, "section": None}), p["base"])
    document["support_steel"] = proposals
    (missing,) = [f for f in found(as_model(document), "support-missing") if f.ids == ["P-01/S1"]]
    pinnable, _, by_hand = missing.message.partition("no place clear")
    assert "P-01/S1/SP-8.0" in pinnable and "layout pin" in pinnable
    assert "P-01/S1/SP-4.0" not in pinnable
    assert "P-01/S1/SP-4.0" in by_hand and "by hand, not by pin" in by_hand


def test_declared_support_steel_carries_shoes_and_the_rules_count_it():
    from types import SimpleNamespace

    from chemeascode.domains.spatial.piping_detail import support_proposals, supports
    from chemeascode.domains.spatial.structures import support_steel

    document = long_run_document()
    proposals = support_proposals(document)
    for p in proposals:
        p["parts"] = support_steel(SimpleNamespace(**{**p, "section": None}), p["base"])
    # proposals carry no shoes: the finding stays, naming them
    document["support_steel"] = proposals
    document["supports"] = supports(document)
    assert document["supports"] == []
    (missing,) = found(as_model(document), "support-missing")
    assert "P-01/S1/SP-4.0" in missing.message and "layout pin" in missing.message
    # declared (pinned) they do
    for p in proposals:
        p["source"] = "declared"
    document["supports"] = supports(document)
    assert [s["on"] for s in document["supports"]] == [
        "P-01/S1/SP-4.0/crossbar",
        "P-01/S1/SP-8.0/crossbar",
    ]
    model = as_model(document)
    assert found(model, "support-missing") == [] and found(model, "free-span") == []
    assert found(model, "clash-pipe-steel") == []  # the pipe rests on its crossbar


def test_pipe_supports_build_pin_and_draw(plant3d):
    import yaml as yaml_

    from chemeascode.domains.spatial.drawing2d import render_plan
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.domains.spatial.pins import pin
    from chemeascode.domains.spatial.schemas import LayoutModelFile
    from chemeascode.foundation.workspace import Workspace

    site = plant3d / "layout" / "site-plan.yaml"
    site.write_text(
        site.read_text().replace("levels: [5]}", "levels: [5], intermediate_supports: {}}")
    )
    structures = plant3d / "layout" / "structures.yaml"
    structures.write_text(
        structures.read_text()
        + "pipe_supports:\n"
        + "  - {id: PS-1, kind: t_post, at: [30, 8], top: 2.5, rotation_deg: 90}\n"
        + "  - {id: PS-2, kind: stub, from: steel, at: [26, 22.5], top: 7.5}\n"
    )
    document = build_model(Workspace(plant3d)).document
    LayoutModelFile.model_validate(document)
    assert any("/mid-" in p["id"] for p in document["racks"][0]["parts"])
    declared = {s["id"]: s for s in document["support_steel"] if s["source"] == "declared"}
    assert declared["PS-1"]["base"] == 0.0 and declared["PS-2"]["base"] == 6.0  # on L1
    ids = [p["id"] for p in declared["PS-1"]["parts"]]
    assert ids == ["PS-1/column", "PS-1/crossbar", "PS-1/footing"]
    svg = render_plan(document)
    assert 'id="support-steel-PS-1"' in svg
    # a proposal pinned is declared in layout/structures.yaml and built as such
    from chemeascode.domains.spatial.piping_detail import support_proposals

    proposal = support_proposals(long_run_document())[0]
    document["support_steel"].append(proposal)
    done = pin(plant3d, document, proposal["id"])
    assert done.file == "layout/structures.yaml" and done.what == ["P-01/S1/SP-4.0"]
    listed = yaml_.safe_load(structures.read_text())["pipe_supports"]
    assert listed[-1]["id"] == "P-01/S1/SP-4.0" and listed[-1]["from"] == "grade"
    rebuilt = build_model(Workspace(plant3d)).document
    pinned = next(s for s in rebuilt["support_steel"] if s["id"] == "P-01/S1/SP-4.0")
    assert pinned["source"] == "declared" and pinned["at"] == [4.0, 20.0]


# -- 5. valve access platforms ---------------------------------------------------------------


def valve(vid, x, z=4.0, y=10.0, direction=(1, 0, 0), operator=None):
    entry = {
        "id": vid,
        "refs": {"dexpi": vid, "sheet": "pid/P-01.xml", "lines": ["L"], "segments": ["S1"]},
        "source": "generated",
        "kind": "valve",
        "dexpi_class": "GateValve",
        "tag": vid.split("/")[-1],
        "line": "L",
        "segment": "S1",
        "pipe": "P-01/S1",
        "point": [x, y, z],
        "direction": list(direction),
        "parts": [
            {
                "id": f"{vid}/handwheel",
                "kind": "torus",
                "material": "handwheel",
                "centre": [x, y, z + 0.45],
                "axis": [0, 0, 1],
                "radius": 0.15,
                "tube": 0.01,
                "lod": 2,
            }
        ],
    }
    if operator:
        entry["operator"] = operator
    return entry


def valve_model(*valves, z=4.0):
    pipe = a_pipe("P-01/S1", [[0, 10, z], [30, 10, z]], od=0.1143, dn=100.0)
    model = model_with([pipe], inline=list(valves))
    model["equipment"] = []
    return model


def proposals_of(model):
    from chemeascode.domains.spatial.criteria import criteria
    from chemeascode.domains.spatial.structures import valve_platform_proposals

    return valve_platform_proposals(model, criteria(), "layout/structures.yaml")


def test_a_valve_out_of_reach_gets_a_platform_beside_its_pipe():
    from chemeascode.domains.spatial.structures import frame_structure

    (found_,) = proposals_of(valve_model(valve("P-01/HV-1", 10.0)))
    structure, reason, _ = found_
    assert structure.id == "VP-HV-1" and structure.serves == ["P-01/HV-1"]
    (level,) = structure.levels
    assert level.elevation == round(4.45 - 1.2, 2) and level.use == "occasional"
    # beside the pipe (north of it, its insulation plus 0.1 m off), 1.2 m wide, 1 m past the
    # handwheel either way
    assert structure.origin == (9.0, round(10 + 0.1143 / 2 + 0.1, 2))
    assert (structure.spans_x, structure.spans_y) == ([2.0], [1.2])
    assert "HV-1" in reason and "no declared operator" in reason
    # below 6 m a caged ladder on the far edge (one way down is enough: nothing more proposed)
    (ladder,) = structure.ladders
    assert ladder.at == (1.6, 0.8) and ladder.facing == "north"
    entry = frame_structure(structure, "layout/structures.yaml")
    assert [ld["id"] for ld in entry["ladders"]] == ["VP-HV-1/ladder-to-P1"]
    assert entry["stairs"] == [] and entry["serves"] == ["P-01/HV-1"]


def test_a_valve_platform_keeps_its_columns_out_of_the_pipes_below_it():
    """The columns stand from grade to the floor: a pipe they would run through counts, so the
    platform goes to the side where none does, and the reason names one it cannot avoid."""
    model = valve_model(valve("P-01/HV-1", 10.0))
    # a low pipe across the north side's west corners (the platform's floor is at 3.25 m)
    model["pipes"].append(a_pipe("P-01/S9", [[9.0, 10.5, 1.5], [9.0, 14.0, 1.5]], od=0.1143))
    ((structure, reason, blockers),) = proposals_of(model)
    assert structure.origin[1] < 10  # south of the pipe, clear of P-01/S9
    assert "P-01/S9" not in reason and blockers == []
    # pipes under both sides: the north one (first) is kept, its column blocker named
    model["pipes"].append(a_pipe("P-01/S8", [[9.0, 6.0, 1.5], [9.0, 9.5, 1.5]], od=0.1143))
    ((structure, reason, blockers),) = proposals_of(model)
    assert structure.origin[1] > 10
    assert "its columns from grade stand in: P-01/S9" in reason and blockers == ["P-01/S9"]


def test_valves_close_together_share_a_platform_and_far_ones_do_not():
    close = proposals_of(valve_model(valve("P-01/HV-1", 10.0), valve("P-01/HV-2", 12.0)))
    assert [s.serves for s, _, _ in close] == [["P-01/HV-1", "P-01/HV-2"]]
    assert close[0][0].spans_x == [4.0]
    far = proposals_of(valve_model(valve("P-01/HV-1", 10.0), valve("P-01/HV-2", 20.0)))
    assert [s.serves for s, _, _ in far] == [["P-01/HV-1"], ["P-01/HV-2"]]


def test_a_high_valve_platform_gets_a_stair():
    from chemeascode.domains.spatial.structures import frame_structure

    ((structure, _, _),) = proposals_of(valve_model(valve("P-01/HV-1", 10.0, z=8.0), z=8.0))
    entry = frame_structure(structure, "layout/structures.yaml")
    assert [s["id"] for s in entry["stairs"]] == ["VP-HV-1/stair-to-P1"]


def test_a_high_valve_platform_stair_tops_out_on_the_platform_and_holds_once_pinned(tmp_path):
    import yaml as yaml_

    from chemeascode.domains.spatial.pins import pin
    from chemeascode.domains.spatial.schemas import StructureList
    from chemeascode.domains.spatial.structures import frame_structure, rect_gap, stair_landings

    # 8 m: two flights (top at the start of the run); 11 m: three (top at its far end, so it
    # starts back by one run and a landing)
    for z in (8.0, 11.0):
        model = valve_model(valve("P-01/HV-1", 10.0, z=z), z=z)
        ((structure, reason, _),) = proposals_of(model)
        entry = frame_structure(structure, "layout/structures.yaml")
        (stair,) = entry["stairs"]
        _, top = stair_landings(stair)
        platform = tuple(entry["footprint"])
        assert rect_gap(top, platform) <= 0.3, (z, top, platform)
        # pinned, the declared stair is the platform's connected way down: nothing more
        # proposed, and the rules find its floor reached and served
        for way in entry["stairs"]:
            way["source"] = "generated"
        entry.update(source="generated", review_needed=True, reason=reason)
        model["structures"] = [entry]
        root = tmp_path / str(z)
        (root / "layout").mkdir(parents=True)
        (root / "piping").mkdir()
        pin(root, model, "VP-HV-1")
        text = (root / "layout" / "structures.yaml").read_text()
        (declared,) = StructureList.model_validate(yaml_.safe_load(text)).structures
        built = frame_structure(declared, "layout/structures.yaml")
        assert [s.get("source") for s in built["stairs"]] == ["declared"]
        model["structures"] = [built]
        assert found(model, "operability") == []
        assert found(model, "access-unconnected") == []
        assert found(model, "escape-travel") == [] and found(model, "escape-ways") == []


def test_a_proposed_valve_platform_does_not_take_the_id_of_a_pinned_one():
    from chemeascode.domains.spatial.structures import frame_structure, valve_platform_id

    model = valve_model(valve("P-01/HV-1", 10.0), valve("P-01/HV-2", 20.0))
    first, second = proposals_of(model)
    assert (first[0].id, second[0].id) == ("VP-HV-1", "VP-HV-2")  # named by the valve served
    assert [s.id for s, _, _ in proposals_of(model)] == ["VP-HV-1", "VP-HV-2"]  # stable
    # VP-HV-1 pinned (declared) reaches HV-1: the other proposal keeps its id (no renumbering
    # into the gap, as VP-<n> did)
    model["structures"] = [frame_structure(first[0], "layout/structures.yaml")]
    assert [s.id for s, _, _ in proposals_of(model)] == ["VP-HV-2"]
    # a declared structure that has the id already: the proposal takes a suffix
    assert valve_platform_id(["HV-1"], {"VP-HV-1"}) == "VP-HV-1-2"
    assert valve_platform_id(["XV-2", "PV 1/A"]) == "VP-PV_1_A"


def test_no_platform_for_a_valve_in_reach_or_with_a_declared_operator():
    assert proposals_of(valve_model(valve("P-01/HV-1", 10.0, z=1.0), z=1.0)) == []
    chain = {"kind": "chainwheel", "use": "infrequent"}
    assert proposals_of(valve_model(valve("P-01/HV-1", 10.0, operator=chain))) == []


def test_a_proposed_platform_is_named_by_the_operability_finding_until_pinned(tmp_path):
    import yaml as yaml_

    from chemeascode.domains.spatial.pins import pin
    from chemeascode.domains.spatial.schemas import StructureList
    from chemeascode.domains.spatial.structures import frame_structure

    model = valve_model(valve("P-01/HV-1", 10.0))
    ((structure, reason, _),) = proposals_of(model)
    entry = frame_structure(structure, "layout/structures.yaml")
    for way in entry["ladders"]:
        way["source"] = "generated"
    entry.update(source="generated", review_needed=True, reason=reason)
    model["structures"] = [entry]
    (finding,) = found(model, "operability")
    assert "proposed: valve access platform VP-HV-1" in finding.message
    # the proposal is no walking level, steel or floor of the other rules yet
    assert found(model, "escape-ways") == [] and found(model, "headroom") == []
    # pinned: the platform, its ladder and the route of the valve's pipe
    (tmp_path / "layout").mkdir()
    (tmp_path / "piping").mkdir()
    done = pin(tmp_path, model, "VP-HV-1")
    assert done.what[0] == "VP-HV-1" and "piping/routing.yaml" in done.file
    text = (tmp_path / "layout" / "structures.yaml").read_text()
    (declared,) = StructureList.model_validate(yaml_.safe_load(text)).structures
    assert declared.serves == ["P-01/HV-1"] and [ld.id for ld in declared.ladders] == [
        "ladder-to-P1"
    ]
    routing = yaml_.safe_load((tmp_path / "piping" / "routing.yaml").read_text())
    assert [(e["line"], e["segment"]) for e in routing["lines"]] == [("L", "P-01/S1")]
    # declared, it is a floor: the valve is reached, and one ladder is enough for it
    built = frame_structure(declared, "layout/structures.yaml")
    model["structures"] = [built]
    assert found(model, "operability") == []
    assert found(model, "escape-ways") == []


def test_the_take_off_counts_support_steel_once_pinned():
    from types import SimpleNamespace

    from chemeascode.domains.assessment.mto import take_off
    from chemeascode.domains.spatial.piping_detail import support_proposals
    from chemeascode.domains.spatial.structures import support_steel

    document = long_run_document()
    proposals = support_proposals(document)
    for p in proposals:
        p["parts"] = support_steel(SimpleNamespace(**{**p, "section": None}), p["base"])
    document["support_steel"] = proposals

    def steel(model):
        return take_off(model).totals().get("steel", {}).get("t", 0.0)

    assert steel(document) == 0.0  # proposed: not counted
    for p in proposals:
        p["source"] = "declared"
    groups = {r.group for r in take_off(document).rows if r.category == "steel"}
    assert steel(document) > 0.0 and groups == {"support-steel"}


def test_pinning_again_replaces_a_pin_written_with_its_sheet(tmp_path):
    """A plant may name a unique segment by its pipe id (``P-02/S2``); pinning the line again
    replaces that entry instead of adding a second pin of the same segment."""
    import yaml as yaml_

    from chemeascode.domains.spatial.pins import pin_routes

    (tmp_path / "piping").mkdir()
    (tmp_path / "piping" / "routing.yaml").write_text(
        "lines:\n  - {line: L-1, segment: P-02/S2, route: [[0, 0, 1], [5, 0, 1]]}\n",
        encoding="utf-8",
    )
    model = {
        "pipes": [
            {"id": "P-02/S2", "line": "L-1", "segment": "S2", "points": [[0, 0, 1], [6, 0, 1]]}
        ]
    }
    pin_routes(tmp_path, model, "L-1")
    lines = yaml_.safe_load((tmp_path / "piping" / "routing.yaml").read_text())["lines"]
    assert lines == [{"line": "L-1", "segment": "S2", "route": [[0, 0, 1], [6, 0, 1]]}]


# -- 6. steel where it should not stand (review7) ----------------------------------------------


def member(pid, a, b, size=0.2):
    return {
        "id": pid,
        "kind": "member",
        "material": "steel",
        "start": a,
        "end": b,
        "profile": [size, size],
    }


def post(pid, x, y, top, cross_along="y"):
    """A declared T-post: a column from grade and a 1 m crossbar."""
    dx, dy = (0.0, 0.5) if cross_along == "y" else (0.5, 0.0)
    return {
        "id": pid,
        "source": "declared",
        "kind": "t_post",
        "at": [x, y],
        "parts": [
            member(f"{pid}/column", [x, y, 0.0], [x, y, top - 0.2]),
            member(f"{pid}/crossbar", [x - dx, y - dy, top - 0.1], [x + dx, y + dy, top - 0.1]),
        ],
    }


ROAD = {"id": "R2", "points": [[0, 78.5], [200, 78.5]], "width": 6.0}


def steel_found(model):
    from tests.test_layout_engineering_rules import base

    return [f for f in model_rules(base(**model)) if f.rule == "cheme.layout-steel-in-way"]


def test_a_rack_bent_in_a_road_is_found_and_bent_spacing_spans_the_road():
    from chemeascode.domains.spatial.schemas import Rack
    from chemeascode.domains.spatial.structures import rack_stations, rack_steel

    data = {"id": "PR2", "points": [[143, 68], [143, 104]], "width": 4, "levels": [6.5, 8.5]}
    rack = Rack.model_validate(data)
    assert rack_stations(rack, 6.0)[0][2] == 12.0  # y 80: in the road (75.5 .. 81.5)
    entry = {**data, "parts": rack_steel(rack, 6.0)}
    (f,) = steel_found({"roads": [ROAD], "racks": [entry]})
    assert f.ids == ["PR2", "R2"] and "below its 6 m headroom" in f.message
    # the rack's own spacing: 5 bents 7.2 m apart, at y 75.2 and 82.4, either side of it
    wide = Rack.model_validate({**data, "bent_spacing_m": 7.2})
    assert [round(68 + s, 2) for s in rack_stations(wide, 6.0)[0]][1:3] == [75.2, 82.4]
    assert not steel_found({"roads": [ROAD], "racks": [{**data, "parts": rack_steel(wide, 6.0)}]})


def test_a_platform_and_its_stair_in_a_road_are_found():
    from tests.test_layout_engineering_rules import structure

    vp = structure(
        "structures:\n  - {id: VP-8, origin: [179.7, 76.62], spans_x: [1.2], spans_y: [2.0], "
        "levels: [{id: P1, elevation: 8.6, kind: platform}], "
        "stairs: [{id: stair-to-P1, from: grade, to: P1, side: west}]}\n"
    )
    (f,) = steel_found({"roads": [ROAD], "structures": [vp]})
    assert f.ids == ["VP-8", "R2"]
    # the beams of a rack over the road, above the headroom, are no finding
    over = {
        "id": "PR",
        "points": [[140, 70], [140, 90]],
        "width": 3.0,
        "parts": [member("PR/beam", [140, 76, 6.4], [140, 81, 6.4], 0.3)],
    }
    assert not steel_found({"roads": [ROAD], "racks": [over]})


def test_support_posts_in_zones_items_and_ladders_are_found():
    zone = {
        "id": "Z-PAD",
        "kind": "crane_pad",
        "volumes": [{"shape": "box", "source": "declared", "box": [174, 23, 0, 184, 35, 1]}],
    }
    machine = {
        "tag": "K-1",
        "bbox": [130.1, 34.3, 0.0, 134.1, 37.3, 3.0],
        "parts": [],
        "nozzles": [],
        "envelopes": [],
    }
    cage = {
        "id": "CB/LD1",
        "parts": [
            {
                "id": "CB/LD1/cage",
                "kind": "member",
                "material": "cage",
                "start": [127.5, 48.55, 10.0],
                "end": [127.5, 48.55, 20.0],
                "profile": [0.7, 0.7],
            }
        ],
    }
    ladder_owner = {"id": "CB", "parts": [], "ladders": [cage], "stairs": []}
    posts = [
        post("P/on-pad", 175.93, 32.44, 3.4),
        post("P/in-item", 132.108, 37.55, 1.42),
        post("P/at-ladder", 127.375, 49.25, 12.18),
        post("P/clear", 160.0, 10.0, 3.0),
        {**post("P/proposed", 176.0, 30.0, 3.0), "source": "generated"},  # not yet pinned
    ]
    findings = steel_found(
        {
            "support_steel": posts,
            "zones": [zone],
            "equipment": [machine],
            "structures": [ladder_owner],
        }
    )
    assert sorted(tuple(f.ids) for f in findings) == [
        ("P/at-ladder", "CB/LD1"),
        ("P/in-item", "K-1"),
        ("P/on-pad", "Z-PAD"),
    ]
    by = {f.ids[0]: f for f in findings}
    assert "crane-pad zone Z-PAD" in by["P/on-pad"].message
    assert "P/in-item/crossbar" in by["P/in-item"].message
