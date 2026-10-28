"""Rules that see what an independent layout review found invisible: access inside a casing and
stairs that serve nothing, vent outlets under generated walking surfaces, in-line items inside a
casing, trays in lifting lanes and in zones, unsupported tray spans, buildings too close, crane
pads on racks."""

from __future__ import annotations

from pathlib import Path

import yaml

from chemeascode.domains.spatial.floors import casing_volumes, in_casing, walking_levels
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.pins import access_ids, pin
from chemeascode.domains.spatial.schemas import SitePlan, StructureList
from chemeascode.domains.spatial.structures import (
    CONNECT,
    frame_structure,
    rect_gap,
    stair_landings,
)
from chemeascode.domains.spatial.trays import tray_findings
from tests.test_layout_3d import a_pipe, item
from tests.test_layout_engineering_rules import base, building, heavy, pad, valve

# a cold box: platforms along its north face inside the casing, a roof walkway on top, a stair
# tower outside its east face (reaching no platform) and ladders inside the casing
COLD_BOX = """\
structures:
  - id: CB
    origin: [100, 100]
    spans_x: [15]
    spans_y: [9]
    levels:
      - {id: P10, elevation: 10, kind: platform, extent: [0, 7.2, 15, 9]}
      - {id: RF, elevation: 20, kind: platform, extent: [0, 7.2, 15, 9]}
    stairs:
      - {id: ST1, from: grade, to: P10, side: east, offset: 0.5}
      - {id: ST2, from: P10, to: RF, side: east, offset: 0.5}
    ladders:
      - {id: LD0, from: grade, to: P10, at: [0.5, 8.6], facing: north}
    enclosure: {walls: all, height: 20, material: casing}
"""


def entry(text: str = COLD_BOX) -> dict:
    (found,) = StructureList.model_validate(yaml.safe_load(text)).structures
    return frame_structure(found, "layout/structures.yaml")


def found(model, rule, **kw):
    return [f for f in model_rules(model, **kw) if f.rule == f"cheme.layout-{rule}"]


# -- 1. access and escape ----------------------------------------------------------------------


def test_levels_inside_a_casing_are_no_walking_levels_and_get_platforms_outside():
    cb = entry()
    levels = {lv["id"]: lv for lv in cb["levels"]}
    out = levels["P10-out"]
    assert out["source"] == "generated" and out["review_needed"] and out["serves"] == "P10"
    assert out["extent"][1] == 9.2 and out["extent"][3] == 10.7  # outside the 0.2 m wall
    assert levels["RF-out"]["source"] == "generated"  # the roof's landing on that side
    # a declared roof landing on that side, and another roof level sorting before it: no
    # second proposed landing (the plant's own counts, whatever its id)
    declared = COLD_BOX.replace(
        "      - {id: RF, elevation: 20",
        "      - {id: P10-out, elevation: 10, kind: platform, extent: [0, 9.2, 15, 10.7]}\n"
        "      - {id: LAND, elevation: 20, kind: platform, extent: [0, 9.2, 15, 10.7]}\n"
        "      - {id: RB, elevation: 20, kind: platform, extent: [13.8, 1.6, 15, 7.2]}\n"
        "      - {id: RF, elevation: 20",
    )
    ids = {lv["id"] for lv in entry(declared)["levels"] if lv.get("source") == "generated"}
    assert not {i for i in ids if i.startswith(("RB-", "RF-", "LAND-"))}, ids
    assert "P10" not in {lv["id"] for lv in cb["levels"] if lv.get("source")}
    floors = {f.id for f in walking_levels(base(structures=[cb]))}
    assert "CB/P10" not in floors and "CB/P10-out" in floors and "CB/RF" in floors
    volumes = casing_volumes(base(structures=[cb]))
    assert volumes == [("CB", (100.0, 100.0, 115.0, 109.0), 20.0)]
    assert in_casing((105, 108, 10), volumes) == "CB" and in_casing((105, 108, 21), volumes) is None


def test_proposed_stairs_reach_the_platforms_they_serve():
    cb = entry()
    proposed = {s["id"]: s for s in cb["stairs"] if s["source"] == "generated"}
    rects = {}
    for part in cb["parts"]:
        if part["id"].endswith("/grating"):
            from chemeascode.domains.spatial.structures import part_rect

            rects[part["id"].split("/")[1]] = part_rect(part)
    to_out = proposed["CB/stair-to-P10-out"]
    assert to_out["from"] == "grade" and to_out["side"] == "north" and to_out["out"] == 1.7
    base_rect, top = stair_landings(to_out)
    assert rect_gap(top, rects["P10-out"]) <= CONNECT
    roof = proposed["CB/stair-to-RF"]  # from the platform below it, outside the casing
    assert roof["from"] == "P10-out"
    foot, head = stair_landings(roof)
    assert rect_gap(foot, rects["P10-out"]) <= CONNECT
    assert rect_gap(head, rects["RF-out"]) <= CONNECT
    # the declared stairs on the walled east side stand outside the wall
    declared = {s["id"]: s for s in cb["stairs"] if s["source"] == "declared"}
    assert declared["CB/ST1"]["out"] == 0.2 and declared["CB/ST1"]["box"][0] >= 115.2 - 1e-6
    # ladders proposed outside the casing only
    volumes = casing_volumes(base(structures=[cb]))
    for ladder in cb["ladders"]:
        if ladder["source"] == "generated":
            assert in_casing(ladder["base"], volumes) is None


def test_access_inside_a_casing_and_unconnected_stairs_are_findings():
    cb = entry()
    model = base(structures=[cb])
    enclosed = {f.key for f in found(model, "access-enclosed")}
    assert enclosed == {"CB/P10", "CB/LD0"}
    unconnected = {f.key: f for f in found(model, "access-unconnected")}
    assert set(unconnected) == {"CB/ST1", "CB/ST2"}
    assert "P10 at 10 m is inside the casing" in unconnected["CB/ST1"].message
    (ways,) = found(model, "escape-ways")
    assert ways.key == "CB/RF" and "0 connected way(s) down to grade" in ways.message
    assert "CB/stair-to-RF" in ways.message


def test_a_stair_whose_landing_misses_the_floor_serves_nothing():
    text = """\
structures:
  - id: S
    origin: [0, 0]
    spans_x: [6]
    spans_y: [12]
    levels: [{id: L1, elevation: 8, kind: platform, extent: [0, 8, 6, 12]}]
    stairs: [{id: ST1, from: grade, to: L1, side: east, offset: 0}]
    ladders: [{id: LD1, from: grade, to: L1, at: [0.5, 11.5]}]
"""
    model = base(structures=[entry(text)])
    (f,) = found(model, "access-unconnected")
    assert f.key == "S/ST1" and "its top is" in f.message
    (ways,) = found(model, "escape-ways")
    assert "1 connected way(s)" in ways.message  # the ladder only
    # the proposal reaches the platform
    stair = next(s for s in entry(text)["stairs"] if s["source"] == "generated")
    _, top = stair_landings(stair)
    assert rect_gap(top, (0.0, 8.0, 6.0, 12.0)) <= CONNECT
    # moved along the side, the declared stair lands on the platform (three flights of 2.67 m:
    # its top landing is a landing and a run of 4.1 m on from the offset)
    fixed = text.replace("side: east, offset: 0}", "side: east, offset: 3}")
    model = base(structures=[entry(fixed)])
    assert not found(model, "access-unconnected") and not found(model, "escape-ways")


def test_pin_a_platform_outside_the_casing(tmp_path: Path):
    (tmp_path / "layout").mkdir()
    (tmp_path / "layout" / "structures.yaml").write_text(COLD_BOX, encoding="utf-8")
    model = base(structures=[entry()])
    assert "CB/P10-out" in access_ids(model)
    pin(tmp_path, model, "CB/P10-out")
    text = (tmp_path / "layout" / "structures.yaml").read_text()
    pinned = entry(text)
    level = next(lv for lv in pinned["levels"] if lv["id"] == "P10-out")
    assert level.get("source") is None and list(level["extent"]) == [0.0, 9.2, 15.0, 10.7]
    # no second proposal at that elevation; the stair now pins with its out distance
    assert sum(1 for lv in pinned["levels"] if lv.get("source") == "generated") == 1
    pin(tmp_path, base(structures=[pinned]), "CB/stair-to-P10-out")
    data = yaml.safe_load((tmp_path / "layout" / "structures.yaml").read_text())
    stair = next(s for s in data["structures"][0]["stairs"] if s["id"] == "stair-to-P10-out")
    assert stair["side"] == "north" and stair["out"] == 1.7


# -- 2. vent outlets under walking surfaces -----------------------------------------------------


def tank_with_landing(z=10.0):
    tank = item("T-1", (20, 20, 4.5), (6, 6, 9))
    tank["parts"].append(
        {
            "id": "T-1/stair-landing",
            "kind": "box",
            "material": "grating",
            "centre": [24.0, 20.0, z],
            "size": [1.0, 1.0, 0.04],
            "rotation_deg": 353.7,
        }
    )
    return tank


def test_generated_walking_surfaces_count_for_vent_outlets():
    tank = tank_with_landing()
    floors = {f.id: f for f in walking_levels(base(equipment=[tank]))}
    assert floors["T-1/stair-landing"].kind == "item"
    # an outlet 0.6 m under the landing, beside it in plan: it discharges into it
    tail = a_pipe("VNT", [[24.3, 20.4, 5.0], [24.3, 20.4, 9.4]], line="VNT-1", open_ends=["end"])
    (f,) = found(base(equipment=[tank], pipes=[tail]), "vent-outlet")
    assert "T-1/stair-landing" in f.message and "0.62 m below" in f.message
    # 3 m off in plan: clear
    away = a_pipe("VNT", [[27.3, 20.4, 5.0], [27.3, 20.4, 9.4]], line="VNT-1", open_ends=["end"])
    assert not found(base(equipment=[tank], pipes=[away]), "vent-outlet")
    # a zone sphere reaching the landing (no other walking level near)
    zone = {
        "id": "Z",
        "kind": "oxygen_enriched",
        "volumes": [
            {
                "shape": "sphere",
                "source": "generated",
                "centre": [27.0, 20.0, 16.0],
                "radius": 5.0,
                "item": "VNT-1",
                "source_kind": "vent",
            }
        ],
    }
    (f,) = found(base(equipment=[tank], zones=[zone]), "vent-outlet")
    assert "T-1/stair-landing" in f.message


def test_a_vent_outlet_beside_a_walking_surface_discharges_where_people_stand():
    tank = tank_with_landing()
    # the landing (24, 20) +-0.5 m at 10 m: an outlet 1 m above its floor, 1 m out from its edge
    tail = a_pipe("VNT", [[25.5, 20.0, 5.0], [25.5, 20.0, 11.0]], line="VNT-1", open_ends=["end"])
    (f,) = found(base(equipment=[tank], pipes=[tail]), "vent-outlet")
    assert "beside" in f.message and "T-1/stair-landing" in f.message
    assert "within 1.5 m in plan" in f.message and f.key == "VNT+end+beside"
    # farther out than vent_side_clearance_m (1.5 m): clear
    far = a_pipe("VNT", [[26.5, 20.0, 5.0], [26.5, 20.0, 11.0]], line="VNT-1", open_ends=["end"])
    assert not found(base(equipment=[tank], pipes=[far]), "vent-outlet")
    # above the walkway headroom over the floor: clear of the people on it
    high = a_pipe("VNT", [[25.5, 20.0, 5.0], [25.5, 20.0, 12.5]], line="VNT-1", open_ends=["end"])
    assert not found(base(equipment=[tank], pipes=[high]), "vent-outlet")


# -- 3. in-line items inside a casing ----------------------------------------------------------


def test_items_inside_a_casing_need_a_hatch_and_a_platform_outside():
    cb = entry()
    inside = valve("XV-1", 4.0, ("yoke", "actuator-lower"), x=105.0, y=104.0)
    (f,) = found(base(structures=[cb], inline=[inside]), "operability")
    assert "inside the casing of CB" in f.message and f.ids == ["XV-1", "CB"]
    # at the north face with a hatch, worked from the platform outside
    hatch = COLD_BOX.replace(
        "material: casing}",
        "material: casing, openings: [{id: H1, side: north, offset: 9, width: 1, height: 1, "
        "sill: 10.5, kind: hatch}]}",
    )
    face = valve("XV-2", 11.0, ("yoke", "actuator-lower"), x=105.5, y=108.5)
    face["point"] = [105.5, 108.5, 11.0]
    assert not found(base(structures=[entry(hatch)], inline=[face]), "operability")
    # the hatch with no platform outside at its height
    high = hatch.replace("sill: 10.5", "sill: 15")
    face["point"] = [105.5, 108.5, 15.5]
    (f,) = found(base(structures=[entry(high)], inline=[face]), "operability")
    assert "worked through hatch H1" in f.message


# -- 4. trays and ducts in lifting lanes --------------------------------------------------------


def a_tray(tid, points, tag=None, width=0.3, **extra):
    return {
        "id": tid,
        "refs": {"tag": tag} if tag else {},
        "system": "power",
        "kind": "branch",
        "points": points,
        "width": width,
        "depth": 0.1,
        "cables": [],
        "fill": 0.1,
        "fill_max": 0.3,
        **extra,
    }


def test_trays_and_ducts_block_a_crane_lane():
    near = pad([20, 2, 0, 28, 10, 5])
    laydown = {
        "id": "LD",
        "kind": "laydown",
        "volumes": [{"shape": "box", "source": "declared", "box": [30, 10, 0, 36, 16, 3]}],
    }
    over = a_tray("PT-9", [[10, 13, 6], [30, 13, 6]])
    (f,) = found(base(equipment=[heavy()], zones=[near, laydown], trays=[over]), "lifting")
    assert "PT-9" in f.message
    duct = {
        "id": "SA-1",
        "system": "supply",
        "kind": "main",
        "unit": "AHU-1",
        "points": [[10, 13, 6], [30, 13, 6]],
        "width": 0.5,
        "height": 0.4,
        "velocity_m_s": 5.0,
        "velocity_max_m_s": 8.0,
        "method": "astar",
    }
    (f,) = found(base(equipment=[heavy()], zones=[near, laydown], ducts=[duct]), "lifting")
    assert "SA-1" in f.message
    # the item's own tray: its last drop onto the item does not count, a run over it does
    own = a_tray("PT-K", [[20, 0, 6], [20, 19, 6], [20, 19, 3.1]], tag="K-1")
    drop = a_tray("PT-K", [[20, 30, 3.1], [20, 30, 2.0], [20, 21, 2.0], [20, 21, 3.1]], tag="K-1")
    (f,) = found(base(equipment=[heavy()], zones=[near, laydown], trays=[own]), "lifting")
    assert "PT-K" in f.message
    assert not found(base(equipment=[heavy()], zones=[near, laydown], trays=[drop]), "lifting")


# -- 5. trays in zones -------------------------------------------------------------------------


def test_trays_inside_oxygen_enriched_zones_are_findings():
    zone = {
        "id": "Z-O2",
        "kind": "oxygen_enriched",
        "volumes": [{"shape": "sphere", "source": "generated", "centre": [5, 0, 5], "radius": 3}],
    }
    tray = a_tray("IT-1", [[0, 0, 5], [5, 0, 5]], rack="PR")
    model = {"trays": [tray], "zones": [zone], "cabling": {"missing": []}}
    (f,) = [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-zone"]
    assert f.ids == ["IT-1", "Z-O2"] and "oxygen-enriched" in f.message
    # configurable per zone kind
    model["cabling"]["rules"] = {"avoid_zones": ["hazardous"]}
    assert not [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-zone"]
    zone["kind"] = "oxygen_deficient"
    model["cabling"]["rules"] = {"avoid_zones": ["oxygen_deficient"]}
    assert [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-zone"]


# -- 6. buildings too close --------------------------------------------------------------------


def two_buildings(gap, use_a=None, use_b=None):
    texts = []
    for bid, x, use in (("B1", 0, use_a), ("B2", 10 + gap, use_b)):
        texts.append(
            building(
                f"buildings:\n  - id: {bid}\n    origin: [{x}, 0]\n    width: 10\n    depth: 10\n"
                "    walls: all\n    levels: [{id: G, elevation: 0, height: 5}]\n"
                + (f"    use: {use}\n" if use else "")
            )
        )
    return texts


def test_buildings_closer_than_the_spacing_table():
    (f,) = found(base(buildings=two_buildings(2.0)), "building-spacing")
    assert "2.0 m apart < 6 m" in f.message and f.ids == ["B1", "B2"]
    assert not found(base(buildings=two_buildings(8.0)), "building-spacing")
    # an occupied building near a process building: 15 m
    (f,) = found(base(buildings=two_buildings(8.0, "control", "compressor")), "building-spacing")
    assert "< 15 m" in f.message
    # a declared separation names the pair
    plan = SitePlan.model_validate(
        {
            "site": {"width": 100, "depth": 100},
            "separations": [{"from": "B1", "to": "B2", "min_m": 2.0, "basis": "fire wall"}],
        }
    )
    assert not found(base(buildings=two_buildings(2.0)), "building-spacing", plan=plan)


# -- 7. crane pads and laydown on racks --------------------------------------------------------


def test_crane_pads_on_a_rack_are_findings():
    rack = {"id": "PR", "points": [[0, 20], [40, 20]], "width": 6.0, "parts": []}
    on = pad([10, 15, 0, 20, 19, 1])  # the rack's strip is y 17..23
    (f,) = found(base(racks=[rack], zones=[on]), "pad-overlap")
    assert "overlaps rack PR by 2.0 m" in f.message
    assert not found(base(racks=[rack], zones=[pad([10, 5, 0, 20, 16, 1])]), "pad-overlap")


# -- 8. unsupported tray spans -----------------------------------------------------------------


def test_a_tray_run_with_no_steel_within_its_span():
    tray = a_tray("PT-1", [[0, 0, 5], [20, 0, 5]])
    model = {"trays": [tray], "cabling": {"missing": []}}
    (f,) = [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-span"]
    assert "20.0 m level" in f.message
    posts = {
        "id": "S",
        "parts": [
            {
                "id": f"S/col-{k}",
                "kind": "member",
                "material": "steel",
                "start": [x, 0.0, 0.0],
                "end": [x, 0.0, 4.8],
                "profile": [0.2, 0.2],
            }
            for k, x in enumerate((0, 5, 10, 15, 20))
        ],
    }
    model["structures"] = [posts]
    assert not [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-span"]
    # on a rack's tray tier: carried by the bents
    model = {"trays": [{**tray, "rack": "PR"}], "cabling": {"missing": []}}
    assert not [f for f in tray_findings(model) if f.rule == "cheme.layout-tray-span"]
