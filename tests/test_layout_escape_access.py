"""Stairs, ladders and their proposals against the escape rules (code audit 2026-10): the
proposals follow the rules the escape check applies (pre-release issue 231), stairs and ladders keep
ISO 14122-3/-4 flights and steps (pre-release issue 232), the ladder of an upper item platform
stands on the one below (pre-release issue 233), two ways down must be remote from each other
(pre-release issue 237), and guard rails open where a stair or ladder arrives and between joined
levels (pre-release issue 259)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.spatial.floors import Floor
from chemeascode.domains.spatial.pins import access_ids, pin
from chemeascode.domains.spatial.schemas import PlacementList, StructureList
from chemeascode.domains.spatial.structures import (
    LADDER_FLIGHT,
    LADDER_REACH,
    LADDER_SINGLE_FLIGHT,
    LADDER_STAGGER,
    MAX_FLIGHT_RISE,
    frame_structure,
    part_rect,
    platforms_for,
    stair_landings,
)
from tests.test_layout_engineering_rules import base, found


def structure(text: str) -> dict:
    (entry,) = StructureList.model_validate(yaml.safe_load(text)).structures
    return frame_structure(entry, "layout/structures.yaml")


ESCAPE_RULES = ("escape-ways", "escape-travel", "access-unconnected", "access-enclosed")


def escape(entry: dict) -> list:
    return [f for rule in ESCAPE_RULES for f in found(base(structures=[entry]), rule)]


def pin_all(tmp_path: Path, text: str) -> dict:
    """Pin every proposal of the structure until none is left (as a user following the
    findings would), and return the rebuilt structure."""
    path = tmp_path / "layout" / "structures.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    for _ in range(6):
        entry = structure(path.read_text())
        targets = list(access_ids(base(structures=[entry])))
        if not targets:
            return entry
        # platforms first: the stairs and ladders proposed for them reach them
        for target in sorted(targets, key=lambda t: ("stair" in t or "ladder" in t, t)):
            pin(tmp_path, base(structures=[entry]), target)
    raise AssertionError(f"still proposing after six rounds: {targets}")


# -- pre-release issue 232 flights and steps -------------------------------------------------------

TOWER = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: L6, elevation: 6}
      - {id: TOP, elevation: 20, kind: platform}
    stairs: [{id: ST1, from: grade, to: TOP, side: east}]
"""


def test_a_generated_stair_keeps_iso_14122_3_flights_and_steps():
    entry = structure(TOWER.replace("TOP, elevation: 20", "TOP, elevation: 26"))
    (stair,) = [s for s in entry["stairs"] if s["id"] == "S1/stair-to-L6"]
    assert stair["source"] == "generated" and stair["flights"] == 2  # 6 m: two flights of 3 m
    for stair in entry["stairs"]:
        rise = stair["box"][5] - 1.1 - stair["box"][2]
        assert rise / stair["flights"] <= MAX_FLIGHT_RISE + 1e-9
        treads = sorted(
            (p["centre"] for p in stair["parts"] if "/flight-0/tread-" in p["id"]),
            key=lambda c: c[2],
        )
        h = treads[1][2] - treads[0][2]
        g = math.dist(treads[0][:2], treads[1][:2])
        assert 0.600 <= g + 2 * h <= 0.660, (stair["id"], h, g)
        assert math.degrees(math.atan2(h, g)) <= 38.0
        assert g >= 0.241


def test_a_ladder_over_the_single_flight_limit_gets_staggered_flights_and_rest_landings():
    entry = structure(TOWER)
    (ladder,) = [lad for lad in entry["ladders"] if lad["to"] == "TOP"]
    rise = ladder["top"][2] - ladder["base"][2]
    assert rise == 14.0 > LADDER_SINGLE_FLIGHT  # from L6 at 6 m
    count = math.ceil(rise / LADDER_FLIGHT)  # three flights of 4.67 m
    for n in (0, 1):
        rails = sorted(
            (p for p in ladder["parts"] if p["id"].endswith(f"/rail-{n}")),
            key=lambda p: p["start"][2],
        )
        assert len(rails) == count
        for rail in rails:
            assert rail["end"][2] - rail["start"][2] <= LADDER_FLIGHT + 1.1 + 1e-9
    rests = [p for p in ladder["parts"] if "/rest-" in p["id"]]
    assert len(rests) == count - 1 and all(p["material"] == "grating" for p in rests)
    # the flights stand side by side, the top one at the ladder's own position
    pairs = [
        [p for p in ladder["parts"] if p["id"].startswith(f"{ladder['id']}/flight-{k}/rail-")]
        for k in range(count)
    ]
    mids = [tuple((a["start"][i] + b["start"][i]) / 2 for i in (0, 1)) for a, b in pairs]
    assert math.dist(mids[0], mids[1]) == pytest.approx(LADDER_STAGGER)
    assert math.dist(mids[-1], ladder["top"][:2]) == pytest.approx(0.0, abs=1e-9)
    # a short ladder stays one flight with the plain part ids
    (short,) = [lad for lad in entry["ladders"] if lad["to"] == "L6"]
    assert {p["id"].rsplit("/", 1)[-1] for p in short["parts"]} == {"rail-0", "rail-1", "cage"}


# -- pre-release issue 233 the ladder of an upper item platform ------------------------------------

COLUMN = {
    "tag": "C-1",
    "family": "column",
    "shape": "vertical_cylinder",
    "position": [0, 0, 0],
    "rotation_deg": 0.0,
    "dimensions": {"diameter": 2.0, "height": 30.0},
    "bbox": [-1, -1, 0, 1, 1, 30],
    "parts": [],
    "envelopes": [],
    "nozzles": [
        {"id": "C-1/N1", "point": [1, 0, 10], "direction": [1, 0, 0], "refs": {}},
        {"id": "C-1/N2", "point": [-1, 0, 20], "direction": [-1, 0, 0], "refs": {}},
    ],
}


def _ring(platform: dict) -> Floor:
    g = next(q for q in platform["parts"] if q["id"].endswith("/grating"))
    a0, a1 = g.get("arc_deg") or (0.0, 0.0)
    return Floor(
        platform["id"],
        "platform",
        g["centre"][2],
        ("ring", 0, 0, g["radius"], g["radius_end"], a0, a1),
    )


def test_the_ladder_of_an_upper_platform_stands_on_the_platform_below():
    low, high = platforms_for(COLUMN, None, [], "x")
    base_ = high["ladder"]["base"]
    top = high["ladder"]["top"]
    assert base_[2] == low["elevation"]
    assert _ring(low).distance(base_[0], base_[1]) == 0.0  # on the lower grating
    assert _ring(high).distance(top[0], top[1]) <= LADDER_REACH  # steps off beside the upper one
    model = base(equipment=[COLUMN], platforms=[low, high])
    assert not found(model, "access-unconnected")


def test_a_declared_platform_ladder_on_no_floor_is_a_finding():
    (placement,) = PlacementList.model_validate(
        {
            "equipment": [
                {
                    "tag": "C-1",
                    "position": [0, 0, 0],
                    "access": {
                        "platforms": [
                            {"elevation": 9, "arc_deg": [330, 30]},
                            {"elevation": 19, "arc_deg": [150, 210]},
                        ],
                        "ladder_side": 90,
                    },
                }
            ]
        }
    ).equipment
    platforms = platforms_for(COLUMN, placement.access, [], "x")
    # the ladder at 90 degrees misses both arcs: the lower one's top is off its platform, the
    # upper one's foot stands on nothing
    findings = {
        f.key: f.message
        for f in found(base(equipment=[COLUMN], platforms=platforms), "access-unconnected")
    }
    assert set(findings) == {"C-1/platform-1/ladder", "C-1/platform-2/ladder"}
    assert "stands on no walking level" in findings["C-1/platform-2/ladder"]
    assert "stands on no walking level" not in findings["C-1/platform-1/ladder"]
    # without a ladder side, and with a lower arc that reaches round under the upper one's
    # start, the upper ladder stands on the lower platform: no finding
    free = placement.access.model_copy(
        update={
            "ladder_side": None,
            "platforms": [
                placement.access.platforms[0].model_copy(update={"arc_deg": [100.0, 200.0]}),
                placement.access.platforms[1],
            ],
        }
    )
    platforms = platforms_for(COLUMN, free, [], "x")
    low, high = platforms
    b = high["ladder"]["base"]
    assert _ring(low).distance(b[0], b[1]) == 0.0
    assert not found(base(equipment=[COLUMN], platforms=platforms), "access-unconnected")


# -- pre-release issue 237 remote ways -------------------------------------------------------------

REMOTE = """\
structures:
  - id: S1
    origin: [22, 19]
    spans_x: [8]
    spans_y: [4]
    levels:
      - {id: L1, elevation: 4, kind: platform}
    ladders:
      - {id: LD1, from: grade, to: L1, at: [0.3, 0.3], facing: south}
      - {id: LD2, from: grade, to: L1, at: [AT, 0.3], facing: south}
"""


def test_two_ladders_side_by_side_are_not_two_ways_down():
    near = structure(REMOTE.replace("AT", "0.9"))
    remote, dead = sorted(
        found(base(structures=[near]), "escape-ways"), key=lambda f: "dead" in f.message
    )
    assert "arrive at most 0.6 m apart" in remote.message
    assert "one incident can block both" in remote.message
    assert "dead end > 7.5 m" in dead.message  # 7.7 m from the far corner (pre-release issue 295)
    # the proposal is a ladder at the far end
    (proposed,) = [lad for lad in near["ladders"] if lad["source"] == "generated"]
    assert proposed["at"][0] > 6 and "not remote" in proposed["reason"]
    far = structure(REMOTE.replace("AT", "7.7"))
    assert not found(base(structures=[far]), "escape-ways")
    assert not [lad for lad in far["ladders"] if lad["source"] == "generated"]


def test_the_remoteness_is_a_criterion_the_plant_overrides():
    from chemeascode.domains.spatial.criteria import criteria
    from chemeascode.domains.spatial.schemas import SitePlan
    from chemeascode.domains.spatial.structures import ESCAPE_REMOTE

    assert criteria().escape_remote_fraction == ESCAPE_REMOTE == 0.5  # one default
    assert "NFPA 101" in criteria().basis["escape_remote_fraction"]
    plan = SitePlan.model_validate(
        {
            "site": {"width": 50, "depth": 50},
            "criteria": {"escape_remote_fraction": 0.05, "dead_end_m": 8},
        }
    )
    near = structure(REMOTE.replace("AT", "0.9"))
    assert not found(base(structures=[near]), "escape-ways", plan=plan)


# -- pre-release issue 295 dead ends on every floor ------------------------------------------------

LONG = """\
structures:
  - id: S1
    origin: [10, 10]
    spans_x: [10, 10, 10]
    spans_y: [2]
    levels:
      - {id: L1, elevation: 4, kind: platform}
    ladders:
      - {id: LD1, from: grade, to: L1, at: [0.3, 0.3], facing: south}
      - {id: LD2, from: grade, to: L1, at: [AT], facing: FACING}
"""


def _long(at: str, facing: str = "south") -> dict:
    return structure(LONG.replace("AT", at).replace("FACING", facing))


def _dead_ends(entry: dict) -> list:
    return [f for f in found(base(structures=[entry]), "escape-ways") if "dead end" in f.message]


def test_a_long_platform_with_both_ways_at_one_end_has_a_dead_end(tmp_path):
    entry = _long("0.3, 1.7", "north")
    (f,) = _dead_ends(entry)
    assert "in one direction only" in f.message and "(dead end > 7.5 m)" in f.message
    assert f.hint and f.key == "S1/L1"
    walk = float(f.message.split("a walk of ")[1].split(" m")[0])
    assert 27.0 < walk < 30.0  # from the far end back to the two ladders
    # the proposals put a ladder at the far end; pinned, nothing is left
    proposed = [lad for lad in entry["ladders"] if lad["source"] == "generated"]
    assert proposed and max(lad["at"][0] for lad in proposed) > 25
    assert not escape(pin_all(tmp_path, LONG.replace("AT", "0.3, 1.7").replace("FACING", "north")))


def test_ways_at_both_ends_of_a_long_platform_leave_no_dead_end():
    entry = _long("29.7, 0.3")
    assert not found(base(structures=[entry]), "escape-ways")
    assert not [lad for lad in entry["ladders"] if lad["source"] == "generated"]


def test_remote_ways_can_still_leave_a_dead_end(tmp_path):
    # 15.2 m apart, more than half the 30 m diagonal: remote, but the far end is a dead end
    # (about 12.6 m to where the two ladders lie 45 degrees apart, 14.5 m to the nearer one)
    text = LONG.replace("AT", "15.5, 0.3").replace("FACING", "south")
    entry = structure(text)
    messages = [f.message for f in found(base(structures=[entry]), "escape-ways")]
    assert len(messages) == 1 and "dead end" in messages[0] and "arrive" not in messages[0]
    (proposed,) = [lad for lad in entry["ladders"] if lad["source"] == "generated"]
    assert proposed["at"][0] > 25 and "dead end longer than 7.5 m" in proposed["reason"]
    assert not escape(pin_all(tmp_path, text))


def test_the_dead_end_limit_is_a_criterion_the_plant_overrides():
    from chemeascode.domains.spatial.criteria import criteria
    from chemeascode.domains.spatial.schemas import SitePlan
    from chemeascode.domains.spatial.structures import DEAD_END

    assert criteria().dead_end_m == DEAD_END == 7.5  # one default
    assert "Approved Document B" in criteria().basis["dead_end_m"]
    plan = SitePlan.model_validate(
        {"site": {"width": 50, "depth": 50}, "criteria": {"dead_end_m": 15}}
    )
    entry = _long("15.5, 0.3")
    assert not found(base(structures=[entry]), "escape-ways", plan=plan)


def test_an_open_floor_with_ways_at_two_corners_is_no_dead_end():
    from chemeascode.domains.spatial.structures import dead_end_walk

    floor = [(0.0, 0.0, 40.0, 20.0)]
    # ways at the two ends of one long side: from every point they lie 45 degrees or more
    # apart (the far corners see them at 63 degrees)
    walk, _ = dead_end_walk([(0, 0, 0, 0), (40, 0, 40, 0)], floor)
    assert walk == pytest.approx(0.0, abs=1e-9)
    # both at one corner, 1 m apart: the dead end is nearly the whole diagonal
    walk, far = dead_end_walk([(0, 0, 0, 0), (1, 0, 1, 0)], floor)
    assert far == (40.0, 20.0) and 42.0 < walk < 44.7
    # one way: the walk to it from the farthest corner
    assert dead_end_walk([(0, 0, 0, 0)], floor) == (math.hypot(40, 20), (40.0, 20.0))
    assert dead_end_walk([], floor) is None


# -- pre-release issue 231 proposals that the escape check accepts once pinned ---------------------

CASING_ROOF = """\
structures:
  - {id: S1, origin: [22, 19], spans_x: [4, 4], spans_y: [4], levels: [{id: ROOF, elevation: 4}], enclosure: {walls: all, height: 4}}
"""  # noqa: E501
INNER = """\
structures:
  - {id: S1, origin: [22, 19], spans_x: [4, 4], spans_y: [4], levels: [{id: L0, elevation: 8, extent: [4.9, 0.5, 7.5, 2.5]}]}
"""  # noqa: E501


def test_a_casing_roof_gets_a_second_way_down_outside_the_casing(tmp_path):
    entry = structure(CASING_ROOF)
    ladders = [lad for lad in entry["ladders"] if lad["source"] == "generated"]
    assert ladders  # a ladder outside the casing wall
    for ladder in ladders:
        x, y, _ = ladder["base"]
        x0, y0, x1, y1 = entry["footprint"]
        assert not (x0 < x < x1 and y0 < y < y1)
    final = pin_all(tmp_path, CASING_ROOF)
    assert not escape(final)


def test_a_stair_that_cannot_reach_the_level_is_not_proposed(tmp_path):
    entry = structure(INNER)
    assert not [s for s in entry["stairs"] if s["source"] == "generated"]
    final = pin_all(tmp_path, INNER)
    findings = escape(final)
    assert not [f for f in findings if f.rule.endswith(("access-unconnected", "escape-ways"))]
    (travel,) = findings
    assert "no proposed stair reaches it: place one by hand" in travel.message
    ids = [w["id"] for w in [*final["stairs"], *final["ladders"]]]
    assert len(ids) == len(set(ids))


FRAMES = [
    TOWER,
    CASING_ROOF,
    """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [5, 5]
    spans_y: [6]
    levels:
      - {id: L1, elevation: 3}
      - {id: L2, elevation: 7, extent: [0, 0, 5, 6]}
      - {id: L3, elevation: 12, kind: platform, extent: [5, 0, 10, 6]}
""",
    """\
structures:
  - id: S1
    origin: [10, 5]
    rotation_deg: 90
    spans_x: [12]
    spans_y: [4]
    levels:
      - {id: D1, elevation: 5, use: regular}
      - {id: P1, elevation: 9, kind: platform, extent: [0, 0, 6, 4]}
      - {id: P2, elevation: 9, kind: platform, extent: [6, 0, 12, 4]}
""",
    """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: L1, elevation: 4}
      - {id: L2, elevation: 8}
    stairs: [{id: ST1, from: grade, to: L2, side: south}]
    ladders: [{id: LD1, from: L1, to: L2, at: [5.5, 5.5]}]
""",
]


@pytest.mark.parametrize("text", FRAMES)
def test_pinning_every_proposal_leaves_no_escape_finding(tmp_path, text):
    final = pin_all(tmp_path, text)
    findings = [f for f in escape(final) if "by hand" not in f.message]
    assert not findings, [f.message for f in findings]


def test_stair_and_ladder_ids_are_unique_within_a_structure():
    text = TOWER.replace(
        "stairs: [{id: ST1, from: grade, to: TOP, side: east}]",
        "stairs: [{id: ST1, from: grade, to: TOP, side: east}]\n"
        "    ladders: [{id: ST1, from: grade, to: L6, at: [0.5, 0.5]}]",
    )
    with pytest.raises(ValidationError, match="unique within a structure: ST1"):
        StructureList.model_validate(yaml.safe_load(text))


def test_a_proposal_takes_a_free_id():
    text = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: L1, elevation: 7}
    stairs: [{id: stair-to-L1, from: grade, to: L1, side: east, offset: 20}]
"""
    entry = structure(text)
    proposed = [s["id"] for s in entry["stairs"] if s["source"] == "generated"]
    assert proposed == ["S1/stair-to-L1-2"]


# -- pre-release issue 259 guard rails -------------------------------------------------------------

RAILS = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [8]
    levels:
      - {id: L1, elevation: 4}
      - {id: A, elevation: 8, kind: platform, extent: [0, 0, 3, 8]}
      - {id: B, elevation: 8, kind: platform, extent: [3, 0, 6, 8]}
    stairs: [{id: ST1, from: grade, to: L1, side: east}]
"""


def _top_rails(entry: dict, level: str) -> list[dict]:
    prefix = f"{entry['id']}/{level}/handrail-"
    return [
        p
        for p in entry["parts"]
        if p["id"].startswith(prefix) and p["id"][len(prefix) :].replace("-", "").isdigit()
    ]


def test_no_guard_rail_crosses_a_stair_landing_or_a_joined_edge():
    for rotation in (0, 90):
        entry = structure(
            RAILS.replace("origin: [0, 0]", f"origin: [0, 0]\n    rotation_deg: {rotation}")
        )
        for stair in entry["stairs"]:
            landing = stair_landings(stair)[1]
            level = stair["to"]
            for rail in _top_rails(entry, level):
                (ax, ay, _), (bx, by, _) = rail["start"], rail["end"]
                # a rail along an edge: its stretch inside the landing's span is empty
                lo_x, hi_x = sorted((ax, bx))
                lo_y, hi_y = sorted((ay, by))
                inside = (
                    lo_x < landing[2] - 1e-6
                    and hi_x > landing[0] + 1e-6
                    and lo_y <= landing[3] + 0.3
                    and hi_y >= landing[1] - 0.3
                    if abs(ay - by) < 1e-6
                    else lo_y < landing[3] - 1e-6
                    and hi_y > landing[1] + 1e-6
                    and lo_x <= landing[2] + 0.3
                    and hi_x >= landing[0] - 0.3
                )
                assert not inside, (rotation, stair["id"], rail["id"])
    entry = structure(RAILS)
    shared = [
        r
        for name in ("A", "B")
        for r in _top_rails(entry, name)
        if abs(r["start"][0] - 3.0) < 1e-6 and abs(r["end"][0] - 3.0) < 1e-6
    ]
    assert not shared
    # the outer edges keep their rails
    assert any(r["id"] == "S1/A/handrail-3" for r in _top_rails(entry, "A"))
    grating = next(p for p in entry["parts"] if p["id"] == "S1/A/grating")
    assert part_rect(grating) == (0.0, 0.0, 3.0, 8.0)


# -- review of pre-release PR 284: staggered flights, upper platform ladders, ladder-head openings -

CORNER_LADDER = """\
structures:
  - id: S1
    origin: [3, 2]
    rotation_deg: ROT
    spans_x: [6]
    spans_y: [6]
    levels:
      - {id: L1, elevation: 4, kind: platform}
      - {id: TOP, elevation: 16, kind: platform}
    ladders: [{id: LD1, from: LOWER, to: UPPER, at: [U, V], facing: FACING}]
"""
CORNERS = {
    "north": (0.5, 5.5),
    "west": (0.5, 0.5),
    "south": (5.5, 0.5),
    "east": (5.5, 5.5),
}


def corner_ladder(rotation: int, facing: str, at: tuple, low: str = "L1", high: str = "TOP"):
    text = (
        CORNER_LADDER.replace("ROT", str(rotation))
        .replace("FACING", facing)
        .replace("LOWER", low)
        .replace("UPPER", high)
        .replace("[U, V]", f"[{at[0]}, {at[1]}]")
    )
    if high != "TOP":  # no stair to TOP standing on L1
        text = text.replace("      - {id: TOP, elevation: 16, kind: platform}\n", "")
    return structure(text)


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize("facing", list(CORNERS))
def test_every_flight_of_a_staggered_ladder_stands_on_a_floor(rotation, facing):
    entry = corner_ladder(rotation, facing, CORNERS[facing])
    (ladder,) = [lad for lad in entry["ladders"] if lad["id"] == "S1/LD1"]
    grating = part_rect(next(p for p in entry["parts"] if p["id"] == "S1/L1/grating"))
    feet = [p for p in ladder["parts"] if "/flight-0/rail-" in p["id"]]
    assert len(feet) == 2
    for rail in feet:
        x, y, z = rail["start"]
        assert z == 4.0
        assert grating[0] - 1e-9 <= x <= grating[2] + 1e-9, (facing, rail["start"])
        assert grating[1] - 1e-9 <= y <= grating[3] + 1e-9, (facing, rail["start"])
    # the entry's base is the real foot of the lowest flight
    mid = [(feet[0]["start"][i] + feet[1]["start"][i]) / 2 for i in (0, 1)]
    assert ladder["base"][:2] == pytest.approx(mid)
    # a lower flight's cage ends at the rest landing
    (cage,) = [p for p in ladder["parts"] if p["id"].endswith("flight-0/cage")]
    (rest,) = [p for p in ladder["parts"] if p["id"].endswith("/rest-1")]
    assert cage["end"][2] == pytest.approx(rest["centre"][2] + rest["size"][2] / 2)


ROUND = {
    "tag": "C-1",
    "family": "column",
    "shape": "vertical_cylinder",
    "position": [0, 0, 0],
    "rotation_deg": 0.0,
    "dimensions": {"diameter": 2.0, "height": 30.0},
    "bbox": [-1, -1, 0, 1, 1, 30],
    "parts": [],
    "envelopes": [],
    "nozzles": [
        {
            "id": f"C-1/N{z}-{a}",
            "point": [math.cos(math.radians(a)), math.sin(math.radians(a)), z],
            "direction": [math.cos(math.radians(a)), math.sin(math.radians(a)), 0],
            "refs": {},
        }
        for z in (10, 20)
        for a in (0, 90, 180, 270)
    ],
}


def test_the_ladder_of_an_upper_platform_all_round_stays_outside_the_rings():
    low, high = platforms_for(ROUND, None, [], "x")
    assert low.get("arc_deg") is None and high.get("arc_deg") is None
    rings = [_ring(low), _ring(high)]
    ladder = high["ladder"]
    for rail in [p for p in ladder["parts"] if "/rail-" in p["id"]]:
        x, y, _ = rail["start"]
        assert all(ring.distance(x, y) > 0.1 for ring in rings), rail["id"]
    b, t = ladder["base"], ladder["top"]
    assert _ring(low).distance(b[0], b[1]) <= 0.3  # beside the platform below
    assert _ring(high).distance(t[0], t[1]) <= LADDER_REACH
    assert not found(base(equipment=[ROUND], platforms=[low, high]), "access-unconnected")


def test_the_ladder_of_an_upper_rectangular_platform_stays_outside_the_gratings():
    box = {
        **ROUND,
        "tag": "F-1",
        "family": "filter",
        "shape": "box",
        "dimensions": {"length": 2.0, "width": 2.0, "height": 30.0},
        "nozzles": [{**n, "id": n["id"].replace("C-1", "F-1")} for n in ROUND["nozzles"]],
    }
    low, high = platforms_for(box, None, [], "x")
    rects = [part_rect(p) for p in high["parts"] if p.get("material") == "grating"]
    for rail in [p for p in high["ladder"]["parts"] if "/rail-" in p["id"]]:
        x, y, _ = rail["start"]
        assert all(not (r[0] < x < r[2] and r[1] < y < r[3]) for r in rects), rail["id"]
    assert not found(base(equipment=[box], platforms=[low, high]), "access-unconnected")


def _rails_along(entry: dict, edge: int) -> list[tuple[float, float]]:
    """The stretches (frame coordinates along the edge) of the top rails of L1 on *edge*."""
    from chemeascode.domains.spatial.structures import Frame

    f = Frame(entry["origin"], entry["rotation_deg"])
    found_ = []
    for rail in _top_rails(entry, "L1"):
        if rail["id"].split("handrail-", 1)[1].split("-")[0] != str(edge):
            continue
        a, b = f.local(*rail["start"][:2]), f.local(*rail["end"][:2])
        axis = 0 if edge in (0, 2) else 1
        found_.append(tuple(sorted((a[axis], b[axis]))))
    return found_


@pytest.mark.parametrize("rotation", [0, 90])
@pytest.mark.parametrize(
    ("corner", "facing"),
    [
        ((0.5, 0.5), "south"),
        ((0.5, 0.5), "west"),
        ((5.5, 0.5), "south"),
        ((5.5, 0.5), "east"),
        ((5.5, 5.5), "north"),
        ((5.5, 5.5), "east"),
        ((0.5, 5.5), "north"),
        ((0.5, 5.5), "west"),
    ],
)
def test_the_guard_rail_opens_on_the_edge_a_ladder_faces(rotation, corner, facing):
    from chemeascode.domains.spatial.structures import EDGE_OF_SIDE

    entry = corner_ladder(rotation, facing, corner, low="grade", high="L1")
    edge = EDGE_OF_SIDE[facing]
    along = corner[0] if edge in (0, 2) else corner[1]
    covered = [r for r in _rails_along(entry, edge) if r[0] - 1e-6 <= along <= r[1] + 1e-6]
    assert not covered, (facing, corner)
    # the other edge at that corner keeps its rail past the ladder
    other = next(
        k
        for side, k in EDGE_OF_SIDE.items()
        if side != facing
        and k % 2 != edge % 2
        and side in (("west" if corner[0] < 3 else "east"), ("south" if corner[1] < 3 else "north"))
    )
    along = corner[1] if other in (1, 3) else corner[0]
    assert any(r[0] - 1e-6 <= along <= r[1] + 1e-6 for r in _rails_along(entry, other))


# -- review 2 of pre-release PR 284: tall item-platform ladders, a ladder side at an arc end -------


def _column(tag: str, diameter: float, groups: dict[float, list[float]], shape="vertical_cylinder"):
    r = diameter / 2
    return {
        "tag": tag,
        "family": "column" if shape == "vertical_cylinder" else "filter",
        "shape": shape,
        "position": [0, 0, 0],
        "rotation_deg": 0.0,
        "dimensions": {"diameter": diameter, "length": diameter, "width": diameter, "height": 40},
        "bbox": [-r, -r, 0, r, r, 40],
        "parts": [],
        "envelopes": [],
        "nozzles": [
            {
                "id": f"{tag}/N{z:g}-{a:g}",
                "point": [r * math.cos(math.radians(a)), r * math.sin(math.radians(a)), z],
                "direction": [math.cos(math.radians(a)), math.sin(math.radians(a)), 0],
                "refs": {},
            }
            for z, angles in groups.items()
            for a in angles
        ],
    }


def _floor_distance(platform: dict, x: float, y: float) -> float:
    gratings = [p for p in platform["parts"] if p.get("material") == "grating"]
    if gratings[0]["kind"] == "annulus":
        return _ring(platform).distance(x, y)
    return min(
        math.hypot(max(r[0] - x, 0.0, x - r[2]), max(r[1] - y, 0.0, y - r[3]))
        for r in (part_rect(g) for g in gratings)
    )


TALL = {
    "full round": _column("C-1", 2.0, {10: [0, 90, 180, 270], 22: [0, 90, 180, 270]}),
    "rectangular": _column("F-1", 2.0, {10: [0, 90, 180, 270], 22: [0, 90, 180, 270]}, "box"),
    "opposite arcs": _column("C-2", 2.0, {10: [0], 22: [180]}),
    "same side": _column("C-3", 1.0, {10: [0], 21.5: [0]}),
    "three platforms": _column("C-4", 2.0, {10: [0, 90, 180, 270], 22: [0, 90], 34: [270]}),
    # on the walkway below, two and three flights, small and large columns
    "walkway D1 two flights": _column("C-5", 1.0, {10: [0], 22: [180]}),
    "walkway D1 three flights": _column("C-6", 1.0, {10: [0], 28: [180]}),
    "walkway D3 two flights": _column("C-7", 3.0, {10: [0], 22: [180]}),
    "walkway D3 three flights": _column("C-8", 3.0, {10: [0], 28: [180]}),
    # small columns: the ladder's margin is wider than the arc margin
    "D0.6 opposite arcs": _column("C-9", 0.6, {10: [0], 22: [180]}),
    "D0.8 opposite arcs": _column("C-10", 0.8, {10: [0], 22: [180]}),
    "D0.8 adjacent arcs": _column("C-11", 0.8, {6.2: [90, 120], 11.37: [240]}),
    "D0.81 narrow lower arc": _column("C-12", 0.81, {10: [0, 30], 22: [200]}),
}


@pytest.mark.parametrize("name", list(TALL))
def test_a_tall_platform_ladder_keeps_its_lowest_flight_on_the_floor_below(name):
    """Review 2 of pre-release PR 284: a climb over 10 m between platforms is staggered, and its
    lowest flight still stands on (or beside, within CONNECT) the platform below."""
    from chemeascode.domains.spatial.structures import CONNECT

    item = TALL[name]
    platforms = platforms_for(item, None, [], "x")
    assert len(platforms) >= 2
    walkway = []
    for low, high in zip(platforms, platforms[1:], strict=False):
        ladder = high["ladder"]
        tall = high["elevation"] - low["elevation"] > 10
        feet = [
            p for p in ladder["parts"] if "/rail-" in p["id"] and p["start"][2] == low["elevation"]
        ]
        assert len(feet) == 2 and (not tall or all("/flight-0/" in p["id"] for p in feet))
        grating = next(p for p in low["parts"] if p.get("material") == "grating")
        bx, by, _ = ladder["base"]
        on_walkway = grating["kind"] == "annulus" and math.hypot(bx, by) < grating["radius_end"]
        walkway.append(on_walkway)
        if on_walkway and tall and grating.get("arc_deg"):
            # the lower flights step from beside the upper arc's end towards the middle of
            # the arc below, not away from it
            a0, a1 = grating["arc_deg"]
            middle = a0 + ((a1 - a0) % 360) / 2

            def ang(px: float, py: float) -> float:
                return math.degrees(math.atan2(py, px))

            def turn(a: float, b: float) -> float:
                return (b - a + 180) % 360 - 180

            head = ang(*ladder["top"][:2])
            step = turn(head, ang(bx, by))
            flights = {
                p["id"].split("/flight-")[1].split("/")[0]
                for p in ladder["parts"]
                if "/flight-" in p["id"]
            }
            if len(flights) % 2 == 0:  # the lowest flight is the stepped one
                assert step * turn(head, middle) > 0, name
            else:
                assert abs(step) < 1e-6, name

        for rail in feet:
            x, y, _ = rail["start"]
            # standing on the walkway below: on its grating; beside it: within CONNECT
            limit = 0.0 if on_walkway else CONNECT + 1e-6
            assert _floor_distance(low, x, y) <= limit, (name, rail["id"])
        t = ladder["top"]
        assert _floor_distance(high, t[0], t[1]) <= LADDER_REACH
    assert not found(base(equipment=[item], platforms=platforms), "access-unconnected")
    if name.startswith("walkway"):
        assert all(walkway)


@pytest.mark.parametrize("arc", [[5, 355], [10, 350], [181, 179]])
@pytest.mark.parametrize("side", [90, 180, 270, None])
def test_a_ladder_inside_a_near_full_arc_stays_outside_the_rings(arc, side):
    """Review 3 of pre-release PR 284: an arc whose gap is narrower than the ladder covers every
    side."""
    access = {"platforms": [{"elevation": 10}, {"elevation": 20, "arc_deg": arc}]}
    if side is not None:
        access["ladder_side"] = side
    (placement,) = PlacementList.model_validate(
        {"equipment": [{"tag": "C-1", "position": [0, 0, 0], "access": access}]}
    ).equipment
    low, high = platforms_for(COLUMN, placement.access, [], "x")
    upper = _ring(high)
    for rail in [p for p in high["ladder"]["parts"] if "/rail-" in p["id"]]:
        x, y, _ = rail["start"]
        assert upper.distance(x, y) > 0.035, (arc, side, rail["id"])


@pytest.mark.parametrize("side", [148, 150, 180, 210, 212, 215, 220, 240])
def test_a_declared_ladder_side_near_an_arc_end_never_runs_through_the_grating(side):
    (placement,) = PlacementList.model_validate(
        {
            "equipment": [
                {
                    "tag": "C-1",
                    "position": [0, 0, 0],
                    "access": {
                        "platforms": [
                            {"elevation": 10},
                            {"elevation": 20, "arc_deg": [150, 210]},
                        ],
                        "ladder_side": side,
                    },
                }
            ]
        }
    ).equipment
    low, high = platforms_for(COLUMN, placement.access, [], "x")
    upper = _ring(high)
    for rail in [p for p in high["ladder"]["parts"] if "/rail-" in p["id"]]:
        x, y, _ = rail["start"]
        # a rail as thick as its profile: clear of the upper grating
        assert upper.distance(x, y) > 0.035, (side, rail["id"])
