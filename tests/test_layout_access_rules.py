"""Access rules that see what the fifth independent layout review found invisible:
headroom over stairs and platforms, stairs in the standing space in front of
valves and hatches, the open end of a pinned vent route, the clear width beside a stacked stair's
next flight, ladder heads in vent zones, the tray hint for inert zones; and the operators declared
for valves and transmitters out of reach."""

from __future__ import annotations

import yaml

from chemeascode.domains.spatial.access_rules import walk_owner
from chemeascode.domains.spatial.model_rules import model_rules, zone_findings
from chemeascode.domains.spatial.pid_network import End
from chemeascode.domains.spatial.piping_detail import apply_operators
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import Routing, SitePlan, StructureList, ZoneList
from chemeascode.domains.spatial.structures import frame_structure
from chemeascode.domains.spatial.zones import zone_entries
from tests.test_layout_3d import a_pipe, item, nz, pipe, seg, two_items
from tests.test_layout_engineering_rules import base, valve


def structure(text: str) -> dict:
    (entry,) = StructureList.model_validate(yaml.safe_load(text)).structures
    return frame_structure(entry, "layout/structures.yaml")


def found(model, rule, **kw):
    return [f for f in model_rules(model, **kw) if f.rule == f"cheme.layout-{rule}"]


# a frame with a 10 m platform and a stair to it on the north side
FRAME = """\
structures:
  - id: S
    origin: [0, 0]
    spans_x: [12]
    spans_y: [6]
    levels:
      - {id: P10, elevation: 10, kind: platform}
    stairs:
      - {id: ST1, from: grade, to: P10, side: north, offset: 2}
"""


def test_walk_owner_groups_treads_and_landings():
    assert walk_owner("S/ST1/flight-0/tread-3") == "S/ST1"
    assert walk_owner("S/ST1/landing-2") == "S/ST1"
    assert walk_owner("T-1/stair-tread-12") == "T-1/stair"
    assert walk_owner("T-1/stair-landing") == "T-1/stair"
    assert walk_owner("T-1/roof-platform") == "T-1/roof-platform"
    assert walk_owner("S/P10") == "S/P10"


# -- 1. headroom over walking surfaces ---------------------------------------------------------


def test_pipes_lower_than_the_headroom_over_a_platform_or_a_stair():
    s = structure(FRAME)
    low = a_pipe("LOW", [[1, 3, 11.5], [11, 3, 11.5]], od=0.2)  # 1.4 m clear over P10
    high = a_pipe("HIGH", [[1, 2, 12.5], [11, 2, 12.5]], od=0.2)  # 2.4 m clear
    under = a_pipe("UNDER", [[1, 4, 9.5], [11, 4, 9.5]], od=0.2)  # under the grating
    stair = s["stairs"][0]
    x0, y0, _, x1, y1, _ = stair["box"]
    through = a_pipe("THROUGH", [[x0 - 1, (y0 + y1) / 2, 5], [x1 + 1, (y0 + y1) / 2, 5]])
    model = base(structures=[s], pipes=[low, high, under, through])
    keys = {f.key: f for f in found(model, "headroom")}
    assert set(keys) == {"LOW+S/P10", "THROUGH+S/ST1"}
    assert "1.40 m above the floor S/P10" in keys["LOW+S/P10"].message
    assert "the stair S/ST1" in keys["THROUGH+S/ST1"].message
    # a plant may ask for more headroom
    plan = SitePlan.model_validate(
        {"site": {"width": 50, "depth": 50}, "criteria": {"access_headroom_m": 2.5}}
    )
    keys = {f.key for f in found(model, "headroom", plan=plan)}
    assert "HIGH+S/P10" in keys


def test_a_riser_through_a_grating_is_no_headroom_finding_but_through_a_stair_it_is():
    s = structure(FRAME)
    riser = a_pipe("RISER", [[6, 3, 5], [6, 3, 15]])
    stair = s["stairs"][0]
    x0, y0, _, x1, y1, _ = stair["box"]
    in_stair = a_pipe(
        "STAIR", [[(x0 + x1) / 2, (y0 + y1) / 2, 0.5], [(x0 + x1) / 2, (y0 + y1) / 2, 12]]
    )
    model = base(structures=[s], pipes=[riser, in_stair])
    assert {f.key for f in found(model, "headroom")} == {"STAIR+S/ST1"}


def test_the_run_at_a_nozzle_and_a_proposed_step_over_are_left_out():
    s = structure(FRAME)
    tank = item("T-1", (6, 3, 13), (2, 2, 2))
    tank["nozzles"] = [
        {
            "id": "T-1/N1",
            "name": "N1",
            "point": [6, 3, 11.0],
            "direction": [0, 0, -1],
            "refs": {},
        }
    ]
    leg = a_pipe("LEG", [[6, 3, 11.0], [2, 3, 11.0], [2, 3, 15]])  # its first run over P10
    model = base(structures=[s], equipment=[tank], pipes=[leg])
    assert not found(model, "headroom")
    over = a_pipe("OVER", [[1, 3, 10.3], [11, 3, 10.3]])
    stepped = base(
        structures=[s],
        pipes=[over],
        step_overs=[{"id": "step-over-1", "pipe": "OVER", "walkway": "S/P10", "parts": []}],
    )
    assert not found(stepped, "headroom")


# -- 2. the operator's standing space ----------------------------------------------------------


def test_a_valve_needs_a_free_standing_space_within_reach():
    free = valve("V1", 1.2, x=5, y=5)
    assert not found(base(inline=[free]), "operability")
    # an item all round the valve leaves no room to stand at grade
    block = item("K-1", (5, 5, 1.0), (4, 4, 1.8))
    (f,) = found(base(inline=[free], equipment=[block]), "operability")
    assert "no free standing space" in f.message and "K-1" in f.message
    # a small item beside it leaves room
    small = item("K-2", (5, 6.2, 1.0), (0.6, 0.6, 1.8))
    assert not found(base(inline=[free], equipment=[small]), "operability")


def test_a_stair_flight_is_no_operating_position():
    s = structure(FRAME)
    (stair,) = s["stairs"]
    tread = next(
        p for p in stair["parts"] if "/flight-0/tread-" in p["id"] and 1.5 < p["centre"][2] < 2.0
    )
    x, y, z = tread["centre"]
    v = valve("V2", z + 1.0, x=x, y=y)
    (f,) = found(base(structures=[s], inline=[v]), "operability")
    assert "only a stair flight reaches it" in f.message


def test_a_stair_flight_in_front_of_a_casing_hatch_blocks_it():
    text = """\
structures:
  - id: CB
    origin: [0, 0]
    spans_x: [15]
    spans_y: [9]
    levels:
      - {id: P20, elevation: 20, kind: platform, extent: [0, 9.2, 15, 10.7]}
      - {id: P30, elevation: 30, kind: platform, extent: [0, 9.2, 15, 10.7]}
    stairs:
      - {id: ST3, from: P20, to: P30, side: north, offset: 0.5, out: 0.2}
    enclosure:
      walls: all
      height: 40
      material: casing
      openings:
        - {id: H1, side: north, offset: OFFSET, width: 1.2, height: 1.2, sill: 20.3, kind: hatch}
"""
    cb = structure(text.replace("OFFSET", "1.0"))  # from the east end: behind the flight
    (stair,) = [st for st in cb["stairs"] if st["id"] == "CB/ST3"]
    low = [p for p in stair["parts"] if "/flight-0/tread-" in p["id"]]
    x = min(p["centre"][0] for p in low if p["centre"][2] < 21.3)
    jt = valve("LV-1", 21.1, x=x + 0.3, y=8.6)
    (f,) = found(base(structures=[cb], inline=[jt]), "operability")
    assert "hatch H1" in f.message and "CB/ST3" in f.message
    # the hatch at the west end, away from the stair: free
    cb = structure(text.replace("OFFSET", "12.5"))
    ok = valve("LV-1", 21.1, x=2.0, y=8.6)
    assert not found(base(structures=[cb], inline=[ok]), "operability")


# -- 3. the free end of a pinned vent route ----------------------------------------------------


def test_a_pinned_vent_route_keeps_its_open_end_and_its_zone():
    model = two_items()
    vent = End("item", "VENT", None, "VNT-1", "VENT", "Vent")
    pinned = [[3, 5, 1], [3, 5, 6], [5, 5, 6]]
    routing = Routing.model_validate({"lines": [{"line": "L-1", "segment": "S1", "route": pinned}]})
    result = route_model(model, [seg("S1", "L-1", nz("A"), vent)], routing=routing)
    route = pipe(result, "S1")
    assert route["method"] == "pinned" and route["open_ends"] == ["end"]
    model["pipes"] = result.pipes
    zones = ZoneList.model_validate(
        {
            "zones": [
                {
                    "id": "Z-N2",
                    "kind": "oxygen_deficient",
                    "sources": [
                        {"item": "L-1", "release_grade": "primary", "substance": "nitrogen"}
                    ],
                }
            ]
        }
    )
    entries, problems = zone_entries(zones, model)
    assert not problems
    (volume,) = entries[0]["volumes"]
    assert volume["centre"] == (5, 5, 6)
    # a source that cannot be placed is reported from the committed model too (validate)
    model["pipes"][0].pop("open_ends")
    (f,) = zone_findings(model, zones)
    assert f.rule == "cheme.layout-zone-source" and "no open end" in f.message


# -- 4. landing clear width --------------------------------------------------------------------

STACKED = """\
structures:
  - id: S
    origin: [0, 0]
    spans_x: [15]
    spans_y: [9]
    levels:
      - {id: P9, elevation: 9, kind: platform, extent: [0, 9.2, 15, EDGE]}
      - {id: P18, elevation: 18, kind: platform, extent: [0, 9.2, 15, EDGE]}
    stairs:
      - {id: ST1, from: grade, to: P9, side: north, offset: 0.5, out: 0.2}
      - {id: ST2, from: P9, to: P18, side: north, offset: 0.5, out: 0.2}
"""


def test_stacked_stairs_need_the_stair_width_beside_the_next_flight():
    narrow = structure(STACKED.replace("EDGE", "10.7"))
    (f,) = found(base(structures=[narrow]), "landing-width")
    assert f.key == "S/ST1+S/ST2" and "less than the stair width 0.9 m" in f.message
    wide = structure(STACKED.replace("EDGE", "12.0"))
    assert not found(base(structures=[wide]), "landing-width")


# -- 5. ladder heads in vent zones; the tray hint ---------------------------------------------


def test_a_ladder_head_inside_an_inert_zone_is_a_finding():
    text = """\
structures:
  - id: S
    origin: [0, 0]
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: RF, elevation: 12, kind: platform}
    ladders:
      - {id: LD1, from: grade, to: RF, at: [0.5, 6.5], facing: north}
"""
    s = structure(text)
    (ladder,) = [ld for ld in s["ladders"] if ld["id"] == "S/LD1"]
    x, y, z = ladder["top"]
    zone = {
        "id": "Z-N2",
        "kind": "oxygen_deficient",
        "volumes": [
            {"shape": "sphere", "source": "declared", "centre": [x + 2, y, z], "radius": 3}
        ],
    }
    keys = {f.key for f in found(base(structures=[s], zones=[zone]), "egress-zone")}
    assert "S/LD1+Z-N2" in keys
    zone["volumes"][0]["centre"] = [x + 20, y, z]
    assert not found(base(structures=[s], zones=[zone]), "egress-zone")


def test_trays_in_an_inert_zone_get_a_hint_to_avoid_it():
    from chemeascode.domains.spatial.trays import tray_findings
    from tests.test_layout_enclosure_rules import a_tray

    zone = {
        "id": "Z-N2",
        "kind": "oxygen_deficient",
        "volumes": [{"shape": "sphere", "source": "declared", "centre": [5, 0, 5], "radius": 3}],
    }
    tray = a_tray("IT-1", [[0, 0, 5], [10, 0, 5]])
    model = base(zones=[zone], trays=[tray], cabling={"rules": {}})
    (f,) = [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-zone"]
    assert f.level == "info" and "add oxygen_deficient to avoid_zones" in f.hint
    model["cabling"]["rules"]["avoid_zones"] = ["oxygen_deficient"]
    (f,) = [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-zone"]
    assert f.level == "warning"


# -- 6. declared operators ---------------------------------------------------------------------


def routing(*operators):
    return Routing.model_validate({"operators": list(operators)})


def test_a_chainwheel_serves_an_infrequent_valve_up_to_its_height():
    high = valve("V-3", 5.0)
    model = base(inline=[high])
    (f,) = found(model, "operability")
    assert "the floor below it is 5.0 m down" in f.message
    apply_operators(model, routing({"item": "V-3", "kind": "chainwheel", "use": "infrequent"}))
    assert model["inline"][0]["operator"] == {"kind": "chainwheel", "use": "infrequent"}
    assert not found(model, "operability")
    # regular use, or too high: the finding stays and says why
    apply_operators(model, routing({"item": "V-3", "kind": "chainwheel"}))
    (f,) = found(model, "operability")
    assert "declared chainwheel does not answer it" in f.message and "infrequent" in f.message
    model = base(inline=[valve("V-4", 7.5)])
    apply_operators(model, routing({"item": "V-4", "kind": "chainwheel", "use": "infrequent"}))
    (f,) = found(model, "operability")
    assert "more than 6 m" in f.message
    # just over the limit: the height is shown rounded up, never reads as the limit itself
    model = base(inline=[valve("V-8", 6.05)])
    apply_operators(model, routing({"item": "V-8", "kind": "chainwheel", "use": "infrequent"}))
    (f,) = found(model, "operability")
    assert "chain wheel is 6.05 m above the floor (more than 6 m)" in f.message
    model = base(inline=[valve("V-9", 6.0)])
    apply_operators(model, routing({"item": "V-9", "kind": "chainwheel", "use": "infrequent"}))
    assert not found(model, "operability")
    # a lever takes no chain wheel
    model = base(inline=[valve("V-5", 4.0, parts=("stem", "lever"))])
    apply_operators(model, routing({"item": "V-5", "kind": "chainwheel", "use": "infrequent"}))
    (f,) = found(model, "operability")
    assert "needs a handwheel" in f.message


def test_extension_spindles_and_remote_mounted_transmitters_have_length_limits():
    model = base(inline=[valve("V-6", 5.0)])
    apply_operators(model, routing({"item": "V-6", "kind": "extension_spindle"}))
    assert not found(model, "operability")  # 4.0 m to a pedestal 1 m above grade
    model = base(inline=[valve("V-7", 9.0)])
    apply_operators(model, routing({"item": "V-7", "kind": "remote_operator"}))
    (f,) = found(model, "operability")
    assert "8.0 m long" in f.message and "more than 6 m" in f.message
    transmitter = valve("FT-1", 6.0, parts=("transmitter",))
    transmitter["kind"] = "instrument"
    model = base(inline=[transmitter])
    apply_operators(model, routing({"item": "FT-1", "kind": "remote_mount", "via": "impulse"}))
    assert not found(model, "operability")  # 4.8 m to a stand at grade
    transmitter = valve("FT-2", 12.0, parts=("transmitter",))
    transmitter["kind"] = "instrument"
    model = base(inline=[transmitter])
    apply_operators(model, routing({"item": "FT-2", "kind": "remote_mount", "via": "capillary"}))
    (f,) = found(model, "operability")
    assert "capillary run would be 10.8 m" in f.message


def test_an_operator_naming_nothing_is_reported():
    model = base(inline=[valve("V-8", 1.2)])
    plan = routing({"item": "V-99", "kind": "chainwheel", "use": "infrequent"})
    (f,) = [f for f in model_rules(model, plan) if f.rule == "cheme.layout-operator-unknown"]
    assert f.ids == ["V-99"]


# -- 7. ladders and risers through ring platforms --------------------------------------------


def ring_platform(with_ladder=True):
    """C-1 at the origin: a ring platform r 2.1..3.1 at 6.3 m over 345..195 deg, its caged
    ladder on the north side (rails y 3.35, cage centre y 3.7)."""
    grating = {
        "id": "C-1/platform-1/grating",
        "kind": "annulus",
        "material": "grating",
        "centre": [0, 0, 6.3],
        "radius": 2.1,
        "radius_end": 3.1,
        "depth": 0.03,
        "arc_deg": [345, 195],
    }
    rail = {"kind": "member", "material": "steel", "profile": [0.012, 0.07]}
    ladder = {
        "id": "C-1/platform-1/ladder",
        "base": [0, 3.35, 0],
        "top": [0, 3.35, 6.3],
        "parts": [
            {
                **rail,
                "id": "C-1/platform-1/ladder/rail-0",
                "start": [0.225, 3.35, 0],
                "end": [0.225, 3.35, 7.4],
            },
            {
                **rail,
                "id": "C-1/platform-1/ladder/rail-1",
                "start": [-0.225, 3.35, 0],
                "end": [-0.225, 3.35, 7.4],
            },
            {
                "id": "C-1/platform-1/ladder/cage",
                "kind": "cylinder",
                "material": "cage",
                "start": [0, 3.7, 2.3],
                "end": [0, 3.7, 7.4],
                "radius": 0.35,
            },
        ],
    }
    platform = {"id": "C-1/platform-1", "tag": "C-1", "parts": [grating]}
    if with_ladder:
        platform["ladder"] = ladder
    return platform


def test_pipes_keep_clear_of_ladder_rails_and_cages():
    p = ring_platform()
    # through the cage at 5 m (the climb from grade), and 0.07 m behind the rails
    through = a_pipe("P1", [[0, 3.0, 5.0], [0, 10, 5.0]], od=0.61)
    behind = a_pipe("P2", [[-2, 3.15, 4.0], [2, 3.15, 4.0]], od=0.2)
    clear = a_pipe("P3", [[-2, 2.8, 4.0], [2, 2.8, 4.0]], od=0.2)
    found_ = {
        f.key: f
        for f in found(base(platforms=[p], pipes=[through, behind, clear]), "ladder-clearance")
    }
    assert set(found_) == {"P1+C-1/platform-1/ladder", "P2+C-1/platform-1/ladder"}
    assert "through its cage" in found_["P1+C-1/platform-1/ladder"].message
    assert "0.07 m from its rails (less than 0.2 m)" in found_["P2+C-1/platform-1/ladder"].message
    # a structure's ladder and a rack's are found too
    from chemeascode.domains.spatial.access_rules import _ladder_parts

    s = structure(
        FRAME
        + "    ladders:\n      - {id: LD1, from: grade, to: P10, at: [0.5, 6.5], facing: north}\n"
    )
    assert {name for name, _ in _ladder_parts(base(structures=[s]))} == {"S/LD1"}


LADDER_NAMES = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: L1, elevation: 4, kind: platform}
    stairs: [{id: LDS, from: grade, to: L1, side: east}]
    ladders:
      - {id: LD1, from: grade, to: L1, at: [0.5, 0.5]}
      - {id: ACC2, from: grade, to: L1, at: [5.5, 5.5], facing: north}
"""


def test_ladders_are_found_where_they_are_not_by_their_name():
    """A ladder named ACC2 and a rack ladder named west are ladders; a stair named LDS
    is not."""
    from chemeascode.domains.spatial.access_rules import _ladder_parts
    from chemeascode.domains.spatial.schemas import Rack
    from chemeascode.domains.spatial.structures import rack_ladders

    s = structure(LADDER_NAMES)
    rack = Rack.model_validate(
        {
            "id": "PR",
            "points": [[0, 20], [30, 20]],
            "width": 4,
            "levels": [5],
            "ladders": [{"id": "west", "end": "start"}],
        }
    )
    pr = {"id": "PR", "width": 4.0, "points": [[0, 20], [30, 20]], "levels": [5.0], "parts": []}
    pr["ladders"] = rack_ladders(rack, [], "x")
    model = base(structures=[s], racks=[pr])
    assert {name for name, _ in _ladder_parts(model)} == {"S1/LD1", "S1/ACC2", "PR/west"}
    # a pipe through the cage of ACC2 (north of it, 0.35 m out) and of the rack's ladder
    (acc2,) = [lad for lad in s["ladders"] if lad["id"] == "S1/ACC2"]
    (cage,) = [p for p in acc2["parts"] if p["material"] == "cage"]
    cx, cy, _ = cage["start"]
    (west,) = pr["ladders"]
    (rack_cage,) = [p for p in west["parts"] if p["material"] == "cage"]
    rx, ry, _ = rack_cage["start"]
    stringer = next(p for p in s["stairs"][0]["parts"] if "stringer" in p["id"])
    mx, my, mz = (sum(c) / 2 for c in zip(stringer["start"], stringer["end"], strict=True))
    pipes = [
        a_pipe("P1", [[cx - 2, cy, 3.5], [cx + 2, cy, 3.5]], od=0.1),
        a_pipe("P2", [[rx, ry - 2, 4.0], [rx, ry + 2, 4.0]], od=0.1),
        # through a stringer of the stair LDS: no ladder there
        a_pipe("P3", [[mx - 2, my, mz], [mx + 2, my, mz]], od=0.1),
    ]
    keys = {f.key for f in found(base(structures=[s], racks=[pr], pipes=pipes), "ladder-clearance")}
    assert {"P1+S1/ACC2", "P2+PR/west"} <= keys
    assert not any("LDS" in key for key in keys)


def test_a_riser_through_a_ring_platform_leaves_its_walkway_and_handrail_free():
    p = ring_platform()
    # in the middle of the walkway: 0.42 m either side (r 2.6, od 0.168)
    middle = a_pipe("P1", [[2.6, 0, 1.0], [2.6, 0, 9.0]], od=0.168)
    # through the handrail on the north side
    edge = a_pipe("P2", [[0, 3.0, 1.0], [0, 3.0, 9.0]], od=0.61)
    # beside the shell: 0.75 m of walkway left outside it
    shell = a_pipe("P3", [[2.25, 0, 1.0], [2.25, 0, 9.0]], od=0.168)
    # in the gap of the arc (270 deg), outside the handrail, ending below the platform
    gap = a_pipe("P4", [[0, -2.6, 1.0], [0, -2.6, 9.0]], od=0.168)
    out = a_pipe("P5", [[3.8, 0, 1.0], [3.8, 0, 9.0]], od=0.61)
    low = a_pipe("P6", [[2.6, 0.5, 1.0], [2.6, 0.5, 6.0]], od=0.168)
    pipes = [middle, edge, shell, gap, out, low]
    hits = {f.key: f.message for f in found(base(platforms=[p], pipes=pipes), "walkway-riser")}
    assert set(hits) == {"P1+C-1/platform-1", "P2+C-1/platform-1"}
    assert "leaving 0.42 m of walkway beside it (less than 0.6 m)" in hits["P1+C-1/platform-1"]
    assert "through its handrail" in hits["P2+C-1/platform-1"]
