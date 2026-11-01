"""Engineering rules on the 3D model: wall penetrations (and their pins), rack tiers, vent
outlets and risers, pipe spans, operability, escape, lifting and equipment spacing."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.piping.pipe_data import is_liquid, max_span
from chemeascode.domains.spatial.criteria import criteria, spacing_rows
from chemeascode.domains.spatial.floors import Floor, clear_height, walking_levels
from chemeascode.domains.spatial.layout_validate import building_footprint, building_heights
from chemeascode.domains.spatial.model_rules import model_rules
from chemeascode.domains.spatial.penetrations import crossings
from chemeascode.domains.spatial.pid_network import End, InlineItem
from chemeascode.domains.spatial.pins import PinError, pin
from chemeascode.domains.spatial.routing import route_model
from chemeascode.domains.spatial.schemas import (
    BuildingList,
    LayoutModelFile,
    Routing,
    SitePlan,
    StructureList,
    ZoneList,
)
from chemeascode.domains.spatial.structures import building_parts, frame_structure
from chemeascode.domains.spatial.zones import line_radii
from tests import test_hvac_ducts, test_layout_3d
from tests.test_layout_3d import a_pipe, item, nz, pipe, seg, two_items

plant3d = test_layout_3d.plant3d  # the fixture: a plant with a vessel, a pump and a rack
vented = test_hvac_ducts.vented  # the fixture: the same with a ventilated building


def found(model, rule, **kw):
    return [f for f in model_rules(model, **kw) if f.rule == f"cheme.layout-{rule}"]


def base(**extra):
    model = {
        "equipment": [],
        "racks": [],
        "structures": [],
        "zones": [],
        "pipes": [],
        "inline": [],
        "platforms": [],
        "buildings": [],
        "supports": [],
    }
    model.update(extra)
    return model


def structure(text):
    (entry,) = StructureList.model_validate(yaml.safe_load(text)).structures
    return frame_structure(entry, "layout/structures.yaml")


def building(text):
    (entry,) = BuildingList.model_validate(yaml.safe_load(text)).buildings
    heights = building_heights(entry)
    data = entry.model_dump(mode="json")
    return {
        **data,
        "refs": {"file": "layout/building.yaml"},
        "source": "declared",
        "footprint": building_footprint(entry),
        "heights": heights,
        "parts": building_parts(entry, heights[1]),
    }


CASING = """\
structures:
  - id: CB
    origin: [10, 10]
    spans_x: [6]
    spans_y: [4]
    levels: [{id: L1, elevation: 4}]
    enclosure: {walls: all, height: 8, material: casing}
  - id: FW
    origin: [30, 10]
    spans_x: [4]
    spans_y: [4]
    enclosure: {walls: [west, south, north], height: 5, material: fire_wall, thickness: 0.3}
"""


def walled():
    (cb, fw) = [
        frame_structure(s, "layout/structures.yaml")
        for s in StructureList.model_validate(yaml.safe_load(CASING)).structures
    ]
    return cb, fw


# -- wall penetrations -------------------------------------------------------------------------


def test_enclosure_walls_are_cut_around_their_openings():
    text = CASING.replace(
        "{walls: all, height: 8, material: casing}",
        "{walls: all, height: 8, material: casing, openings: [{id: P1, side: south, "
        "offset: 2, width: 1, height: 1, sill: 3, kind: opening}]}",
    )
    (cb, _) = [
        frame_structure(s, "f")
        for s in StructureList.model_validate(yaml.safe_load(text)).structures
    ]
    ids = [w["id"] for w in cb["walls"]]
    assert "CB/wall-south" not in ids and "CB/wall-south-0" in ids and "CB/wall-east" in ids
    south = [w for w in cb["walls"] if w["id"].startswith("CB/wall-south")]
    assert len(south) == 4  # left, below, above, right of the opening
    assert cb["openings"][0]["id"] == "P1"
    # a pipe through the opening meets no wall
    through = a_pipe("P", [[12.5, 5, 3.5], [12.5, 12, 3.5]], od=0.2)
    assert crossings(base(structures=[cb], pipes=[through])) == []
    # without the opening it would
    plain, _ = walled()
    (pen,) = crossings(base(structures=[plain], pipes=[through]))
    assert pen["owner"] == "CB" and pen["opening"]["side"] == "south"
    assert pen["end_inside"] and pen["opening"]["offset"] == pytest.approx(2.35)


def test_wall_penetrations_by_kind_and_the_opening_proposed():
    cb, fw = walled()
    pipes = [
        # into the casing from the south: a casing penetration (info)
        a_pipe("IN", [[13, 5, 3], [13, 12, 3]], od=0.2, line="L-IN"),
        # straight through the casing, no end inside: passing (warning)
        a_pipe("PASS", [[13, 5, 6], [13, 20, 6]], od=0.2, line="L-PASS"),
        # into the fire wall enclosure through its west wall (warning)
        a_pipe("FIRE", [[25, 12, 2], [32, 12, 2]], od=0.2, line="L-FIRE"),
        # into it through its open east side: no wall
        a_pipe("OPEN", [[40, 12, 2], [33, 12, 2]], od=0.2, line="L-OPEN"),
    ]
    model = base(structures=[cb, fw], pipes=pipes)
    pens = {p["id"]: p for p in crossings(model)}
    assert set(pens) == {"CB/L-IN", "CB/L-PASS", "CB/L-PASS-2", "FW/L-FIRE"}
    fire = pens["FW/L-FIRE"]
    assert fire["material"] == "fire_wall" and fire["opening"]["side"] == "west"
    # 0.2 m pipe + 2 x 0.05 m gap, rounded out to 0.05 m: 0.3 m square around z 2
    assert fire["opening"]["sill"] == pytest.approx(1.85)
    assert fire["opening"]["height"] == pytest.approx(0.3)
    by = {}
    for f in found(model, "wall-penetration"):
        by[f.key] = f.level
    assert by == {
        "CB/L-IN": "info",
        "CB/L-PASS": "warning",
        "CB/L-PASS-2": "warning",
        "FW/L-FIRE": "warning",
    }
    # a run in the wall's plane is a warning even into a casing
    along = a_pipe("ALONG", [[10.0, 9.9, 3], [10.0, 9.9, 1], [15.0, 9.9, 1], [13, 12, 1]])
    (pen,) = crossings(base(structures=[cb], pipes=[along]))
    assert pen["length"] > 4
    (f,) = found(base(structures=[cb], pipes=[along], penetrations=[pen]), "wall-penetration")
    assert f.level == "warning" and "running" in f.message


def test_building_cladding_penetration_and_pin(tmp_path: Path):
    text = """\
buildings:
  - id: B1
    origin: [0, 0]
    width: 10
    depth: 8
    walls: all
    levels: [{id: G, elevation: 0, height: 6}]
    openings: [{id: D1, side: south, offset: 1, width: 2, height: 3}]
"""
    b1 = building(text)
    line = a_pipe("CW", [[5, -5, 4], [5, 4, 4]], od=0.3, line="CW-1")
    model = base(buildings=[b1], pipes=[line])
    (pen,) = crossings(model)
    assert pen["id"] == "B1/CW-1" and pen["opening"]["side"] == "south"
    (f,) = found(model, "wall-penetration")
    assert f.level == "warning" and "cheme layout pin B1/CW-1" in f.hint
    model["penetrations"] = [pen]
    (tmp_path / "layout").mkdir()
    (tmp_path / "layout/building.yaml").write_text(text)
    done = pin(tmp_path, model, "B1/CW-1")
    assert done.file == "layout/building.yaml"
    pinned = BuildingList.model_validate(
        yaml.safe_load((tmp_path / "layout/building.yaml").read_text())
    )
    opening = pinned.buildings[0].openings[-1]
    assert opening.id == "CW-1" and opening.kind == "opening"
    # rebuilt with the pinned opening, the pipe passes the wall in it
    again = building((tmp_path / "layout/building.yaml").read_text())
    assert crossings(base(buildings=[again], pipes=[line])) == []


def test_a_pipe_through_a_building_roof_is_a_penetration(tmp_path: Path):
    text = """\
buildings:
  - id: B1
    origin: [0, 0]
    width: 10
    depth: 8
    walls: all
    levels: [{id: G, elevation: 0, height: 3}]
"""
    b1 = building(text)
    # down from a rack at 5 m through the roof slab (3 .. 3.2 m) to an item inside
    drop = a_pipe("DROP", [[20, 4, 5], [6, 4, 5], [6, 4, 1]], od=0.2, line="L-DROP")
    model = base(buildings=[b1], pipes=[drop])
    (pen,) = crossings(model)
    assert pen["id"] == "B1/L-DROP" and pen["wall"] == "B1/roof" and pen["end_inside"]
    assert pen["material"] == "roof" and "roof of building B1" in pen["reason"]
    # the opening seen from above: 0.2 m pipe + 2 x 0.05 m gap around x 6, y 4
    assert pen["opening"] == {
        "side": "roof",
        "offset": pytest.approx(5.85),
        "width": pytest.approx(0.3),
        "height": pytest.approx(0.3),
        "sill": pytest.approx(3.85),
        "kind": "opening",
    }
    (f,) = found(model, "wall-penetration")
    assert f.level == "warning" and "through a wall" in f.hint
    # a roof opening cannot be declared: the pin refuses it
    model["penetrations"] = [pen]
    (tmp_path / "layout").mkdir()
    (tmp_path / "layout/building.yaml").write_text(text)
    with pytest.raises(PinError, match="roof"):
        pin(tmp_path, model, "B1/L-DROP")
    assert (tmp_path / "layout/building.yaml").read_text() == text
    # a pipe over the roof meets no slab
    over = a_pipe("OVER", [[20, 4, 5], [-5, 4, 5]], od=0.2, line="L-OVER")
    assert crossings(base(buildings=[b1], pipes=[over])) == []
    # through the roof and out through a wall, no end inside: route it around the building
    through = a_pipe("THRU", [[6, 4, 5], [6, 4, 1], [20, 4, 1]], od=0.2, line="L-THRU")
    model = base(buildings=[b1], pipes=[through])
    pens = {p["wall"]: p for p in crossings(model)}
    assert set(pens) == {"B1/roof", "B1/wall-east-0"}
    assert not pens["B1/roof"]["end_inside"]
    assert pens["B1/roof"]["reason"] == "passes through the roof of B1"
    hints = [f.hint for f in found(model, "wall-penetration")]
    assert len(hints) == 2 and all(
        h == "route it around B1 (via points in piping/routing.yaml)" for h in hints
    )
    # in through a wall just under the eaves: the outside diameter grazes the slab, the axis
    # stays under it: a wall penetration only
    eaves = a_pipe("EAVES", [[20, 4, 2.95], [6, 4, 2.95]], od=0.2, line="L-EAVES")
    (pen,) = crossings(base(buildings=[b1], pipes=[eaves]))
    assert pen["wall"] == "B1/wall-east-0"
    # a rotated building: the opening in its own plan frame (x north, y west)
    turned = building(text.replace("origin: [0, 0]", "origin: [0, 0]\n    rotation_deg: 90"))
    drop = a_pipe("DROP", [[-4, 20, 5], [-4, 6, 5], [-4, 6, 1]], od=0.2, line="L-DROP")
    (pen,) = crossings(base(buildings=[turned], pipes=[drop]))
    assert pen["wall"] == "B1/roof"
    assert (pen["opening"]["offset"], pen["opening"]["sill"]) == (
        pytest.approx(5.85),
        pytest.approx(3.85),
    )


def test_a_rack_line_dropped_into_a_low_building_is_found(vented: Path):
    """A pump in a building lower than the rack: its line drops from the rack through the
    roof, which the build reports as a penetration."""
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.foundation.workspace import Workspace

    (vented / "layout" / "hvac.yaml").unlink()
    text = (vented / "layout" / "building.yaml").read_text()
    text = text.replace("height: 6", "height: 3").replace("sill: 3", "sill: 1")
    (vented / "layout" / "building.yaml").write_text(text)
    (vented / "layout" / "equipment-placement.yaml").write_text(
        "equipment:\n"
        "  - {tag: V-101, position: [10, 10, 0]}\n"
        "  - {tag: P-101, position: [26, 7, 0], rotation_deg: 90}\n"
    )
    model = build_model(Workspace(vented))
    pens = {p["refs"]["lines"][0]: p for p in model.document["penetrations"]}
    assert pens["50-P-102"]["wall"] == "H-1/roof"
    assert pens["50-P-102"]["opening"]["side"] == "roof"
    assert any(
        f.rule == "cheme.layout-wall-penetration"
        and "50-P-102" in f.message
        and "roof" in f.message
        for f in model.findings
    )


def test_pin_a_casing_penetration_into_the_enclosure(tmp_path: Path):
    cb, _ = walled()
    model = base(structures=[cb], pipes=[a_pipe("IN", [[13, 5, 3], [13, 12, 3]], line="L-IN")])
    model["penetrations"] = crossings(model)
    (tmp_path / "layout").mkdir()
    (tmp_path / "layout/structures.yaml").write_text(CASING)
    pin(tmp_path, model, "CB/L-IN")
    data = yaml.safe_load((tmp_path / "layout/structures.yaml").read_text())
    (opening,) = data["structures"][0]["enclosure"]["openings"]
    assert opening["id"] == "L-IN" and opening["side"] == "south"
    (cb2, _) = [
        frame_structure(s, "f")
        for s in StructureList.model_validate(data).structures  # still valid
    ]
    assert crossings(base(structures=[cb2], pipes=model["pipes"])) == []


# -- tiers -----------------------------------------------------------------------------------


RACK = {"id": "PR", "points": [[0, 20], [60, 20]], "width": 4, "levels": [5, 7, 9]}


def tier_routing(**lines):
    return Routing.model_validate(
        {
            "rules": {"tiers": [{"rack": "PR", "elevation": 9, "fluids": ["Oxygen"]}]},
            "lines": [{"line": k, "tier": v} for k, v in lines.items()],
        }
    )


def on_rack(pid, z, line="O-1", length=20.0):
    r = 0.05
    return a_pipe(pid, [[5, 20, z + r], [5 + length, 20, z + r]], line=line, fluid="Oxygen")


def test_a_line_off_the_tier_its_rule_assigns():
    routing = tier_routing()
    assert not found(base(racks=[RACK], pipes=[on_rack("A", 9)]), "tier", routing=routing)
    (f,) = found(base(racks=[RACK], pipes=[on_rack("B", 7)]), "tier", routing=routing)
    assert "tier 7 m" in f.message and "says 9 m" in f.message
    # between the tiers (on no tier's steel)
    (f,) = found(base(racks=[RACK], pipes=[on_rack("C", 6.2)]), "tier", routing=routing)
    assert "between its tiers" in f.message
    # a short jog onto the rack is no finding; nor a run over the top tier (passing it)
    assert not found(
        base(racks=[RACK], pipes=[on_rack("D", 7, length=2.0)]), "tier", routing=routing
    )
    assert not found(base(racks=[RACK], pipes=[on_rack("E", 11)]), "tier", routing=routing)
    # the line's own tier intent wins over the rule
    routing = tier_routing(**{"O-1": 7})
    assert not found(base(racks=[RACK], pipes=[on_rack("B", 7)]), "tier", routing=routing)


# -- vents -----------------------------------------------------------------------------------


def vent_zone(z, radius=5.0, kind="vent"):
    return {
        "id": "Z",
        "kind": "oxygen_deficient",
        "volumes": [
            {
                "shape": "sphere",
                "source": "generated",
                "centre": [20, 20, z],
                "radius": radius,
                "item": "VNT-1",
                "source_kind": kind,
            }
        ],
    }


def test_walking_levels_and_the_height_a_vent_needs():
    floors = [Floor("grade", "grade", 0.0, ("all",))]
    assert clear_height((0, 0, 1), 5.0, floors, 2.2) == pytest.approx(7.2, abs=1e-5)
    # a platform 3 m away at 10 m: the sphere must clear 10 + 2.2 + sqrt(25 - 9)
    floors.append(Floor("P", "structure", 10.0, ("rect", 3, -1, 6, 1)))
    assert clear_height((0, 0, 9), 5.0, floors, 2.2) == pytest.approx(16.2, abs=1e-5)
    ring = Floor("R", "platform", 5.0, ("ring", 0, 0, 1.0, 2.0, 0.0, 90.0))
    assert ring.distance(1.5, 0.1) == 0.0 and ring.distance(-1.5, 0.0) > 1.0
    cb, _ = walled()
    levels = walking_levels(base(structures=[cb]))
    grade = levels[0]
    assert grade.id == "grade" and grade.distance(13, 12) > 0  # inside the closed casing
    # the level inside the casing is no walking level; the platform proposed outside it is
    assert not any(f.id == "CB/L1" for f in levels)
    assert any(f.id == "CB/L1-out" and f.z == 4 for f in levels)


def test_vent_outlets_clear_of_the_walking_levels():
    (f,) = found(base(zones=[vent_zone(4.6)]), "vent-outlet")
    assert "grade" in f.message and "needs 7.2 m" in f.message
    assert not found(base(zones=[vent_zone(8.0)]), "vent-outlet")
    # a structure floor at 10 m next to the outlet
    deck = structure(
        "structures: [{id: S, origin: [18, 18], spans_x: [4], spans_y: [4], "
        "levels: [{id: D, elevation: 10}]}]"
    )
    (f,) = found(base(zones=[vent_zone(11.0)], structures=[deck]), "vent-outlet")
    assert "S/D" in f.message
    # a pump seal cylinder is no outlet
    assert not found(base(zones=[vent_zone(1.0, kind="pump_seal")]), "vent-outlet")


def test_vent_rules_raise_the_open_riser():
    model = two_items()
    psv = InlineItem("PSV1", "SpringLoadedGlobeSafetyValve", "PSV-1", "safety_valve")
    end = End("item", "PSV1", None, "PSV-1", "PSV1", "SpringLoadedGlobeSafetyValve")
    segments = [seg("S1", "VNT-1", nz("A"), end, items=(psv,))]
    plain = pipe(route_model(model, segments), "S1")["points"]
    assert plain[-1][2] - plain[-2][2] == pytest.approx(1.0)  # the default rise
    routing = Routing.model_validate({"rules": {"vent_rise_m": 2.0}})
    route = pipe(route_model(model, segments, routing=routing), "S1")["points"]
    assert route[-1][2] - route[-2][2] == pytest.approx(2.0)
    # a vents rule with the line's zone radius: the outlet clears grade + 2.2 m + 5 m
    routing = Routing.model_validate({"rules": {"vents": [{"lines": ["VNT-*"]}]}})
    route = pipe(route_model(model, segments, routing=routing, vent_radii={"VNT-1": 5.0}), "S1")
    assert route["points"][-1][2] >= 7.2 - 1e-6
    assert route["open_ends"] == ["end"]
    # capped by max_rise_m
    routing = Routing.model_validate(
        {"rules": {"vents": [{"fluids": ["water"], "radius_m": 50, "max_rise_m": 3}]}}
    )
    route = pipe(route_model(model, segments, routing=routing), "S1")["points"]
    assert route[-1][2] - route[-2][2] == pytest.approx(3.0)


def test_line_radii_from_the_zone_sources():
    zones = ZoneList.model_validate(
        {
            "zones": [
                {
                    "id": "Z",
                    "kind": "oxygen_deficient",
                    "sources": [
                        {"item": "VNT-1", "release_grade": "continuous", "substance": "nitrogen"},
                        {"item": "T-1/N1", "release_grade": "continuous", "substance": "nitrogen"},
                    ],
                }
            ]
        }
    )
    assert line_radii(zones) == {"VNT-1": 5.0}


# -- spans -----------------------------------------------------------------------------------


def test_span_table():
    assert max_span(100, liquid=False) == 5.2 and max_span(100, liquid=True) == 4.3
    assert max_span(125, liquid=True) == 4.3  # the next smaller row
    assert max_span(10, liquid=True) == 1.5 and max_span(None, liquid=False) == 4.0
    assert is_liquid("Cooling water return") and is_liquid("Liquid oxygen")
    assert not is_liquid("Gaseous nitrogen") and not is_liquid(None)


def support(pid, x, y=0.0, z=3.0):
    return {"id": f"{pid}/support-{x}", "pipe": pid, "point": [x, y, z], "kind": "shoe"}


def test_free_spans_between_supports():
    run = a_pipe("P", [[0, 0, 3.05], [20, 0, 3.05]], dn=100, fluid="Air")
    ok = [support("P", x) for x in (0, 5, 10, 15, 20)]
    assert not found(base(pipes=[run], supports=ok), "free-span")
    wide = [support("P", x) for x in (0, 4, 10, 15, 20)]
    (f,) = found(base(pipes=[run], supports=wide), "free-span")
    assert "6.0 m" in f.message and "5.2 m" in f.message
    # liquid: 4.3 m
    wet = {**run, "fluid": "Water"}
    assert found(base(pipes=[wet], supports=ok), "free-span")
    # the span from the last support to a bend counts
    bent = a_pipe("P", [[0, 0, 3.05], [20, 0, 3.05], [20, 0, 9]], dn=100, fluid="Air")
    short = [support("P", x) for x in (0, 5, 10, 13)]
    (f,) = found(base(pipes=[bent], supports=short), "free-span")
    assert "7.0 m" in f.message
    # no support at all: info
    (f,) = found(base(pipes=[run]), "support-missing")
    assert f.level == "info" and "20.0 m" in f.message


# -- operability -----------------------------------------------------------------------------


def valve(vid, z, parts=("stem", "handwheel"), x=5.0, y=5.0):
    return {
        "id": vid,
        "kind": "valve",
        "dexpi_class": "GateValve",
        "tag": vid,
        "point": [x, y, z - 0.4],
        "direction": [1, 0, 0],
        "line": "L-1",
        "segment": "S1",
        "pipe": "P",
        "parts": [
            {
                "id": f"{vid}/{name}",
                "kind": "box",
                "material": "valve",
                "centre": [x, y, z],
                "size": [0.1, 0.1, 0.1],
                "lod": 2,
            }
            for name in parts
        ],
    }


def test_valves_and_instruments_within_reach_of_a_floor():
    model = base(
        inline=[
            valve("HV-1", 1.5),
            valve("HV-2", 3.0),
            valve("FV-3", 3.0, ("yoke", "actuator-lower", "handwheel")),
        ]
    )
    flagged = {f.ids[0] for f in found(model, "operability")}
    assert flagged == {"HV-2"}  # within 1.8 m of grade; the control valve is remote
    # a platform 1.5 m below it, within reach
    deck = structure(
        "structures: [{id: S, origin: [4, 3], spans_x: [3], spans_y: [3], "
        "levels: [{id: D, elevation: 1.5, kind: platform}]}]"
    )
    assert not found(base(inline=[valve("HV-2", 3.0)], structures=[deck]), "operability")
    # the project's criteria
    plan = SitePlan.model_validate(
        {"site": {"width": 50, "depth": 50}, "criteria": {"operator_max_height_m": 3.5}}
    )
    assert not found(base(inline=[valve("HV-2", 3.0)]), "operability", plan=plan)
    # inside a closed casing: not operable from outside (no hatch declared)
    cb, _ = walled()
    (f,) = found(base(inline=[valve("HV-9", 3.0, x=13.0, y=12.0)], structures=[cb]), "operability")
    assert "inside the casing of CB" in f.message
    # a transmitter on an item's tapping
    tank = item("T-1", (30, 30, 5), (4, 4, 10))
    tank["parts"].append(
        {
            "id": "T-1/N3/transmitter",
            "kind": "box",
            "material": "instrument",
            "centre": [32.2, 30, 6.0],
            "size": [0.12, 0.12, 0.16],
            "lod": 2,
        }
    )
    (f,) = found(base(equipment=[tank]), "operability")
    assert f.ids == ["T-1/N3"] and "2 m" in f.message


# -- escape ----------------------------------------------------------------------------------


TOWER = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [8]
    levels:
      - {id: L1, elevation: 4}
      - {id: L2, elevation: 8, kind: platform}
    stairs: [{id: ST1, from: grade, to: L1, side: east}, {id: ST2, from: L1, to: L2, side: east}]
    ladders: [{id: LD1, from: grade, to: L1, at: [0.5, 0.5]}]
"""


def test_two_declared_ways_down_and_a_stair_within_reach():
    entry = structure(TOWER)
    ways = {f.key: f for f in found(base(structures=[entry]), "escape-ways")}
    # L1 has its stair and ladder; L2 one stair (the proposed ladder does not count)
    assert set(ways) == {"S1/L2"} and "proposed: S1/ladder-to-L2" in ways["S1/L2"].message
    assert not found(base(structures=[entry]), "escape-travel")
    # a floor at 8 m with ladders only: no stair
    ladders = TOWER.replace(", {id: ST2, from: L1, to: L2, side: east}]", "]").replace(
        "ladders: [{id: LD1, from: grade, to: L1, at: [0.5, 0.5]}]",
        "ladders: [{id: LD1, from: grade, to: L1, at: [0.5, 0.5]}, "
        "{id: LD2, from: L1, to: L2, at: [0.5, 0.5]}, {id: LD3, from: L1, to: L2, at: [5.5, 3.5]}]",
    )
    entry = structure(ladders)
    assert not found(base(structures=[entry]), "escape-ways")
    (f,) = found(base(structures=[entry]), "escape-travel")
    assert "no connected declared stair" in f.message and "S1/stair-to-L2" in f.message
    # a long floor: its far end beyond the travel limit from the one stair
    long = TOWER.replace("spans_x: [6]", "spans_x: [10, 10, 10]")
    far = found(base(structures=[structure(long)]), "escape-travel")
    assert {f.key for f in far} == {"S1/L1", "S1/L2"}  # L1 is a deck in regular use
    assert all("30.2 m from its nearest stair" in f.message for f in far)


def test_a_platform_with_one_ladder_and_a_long_walk():
    def platform(radius, arc=None):
        part = {
            "id": "C/platform-1/grating",
            "kind": "annulus",
            "material": "grating",
            "centre": [0, 0, 10],
            "radius": radius,
            "radius_end": radius + 1,
            "depth": 0.03,
        }
        if arc:
            part["arc_deg"] = arc
        return {
            "id": "C/platform-1",
            "tag": "C",
            "parts": [part],
            "ladder": {"base": [radius + 0.5, 0, 0], "top": [radius + 0.5, 0, 11]},
        }

    (f,) = found(base(platforms=[platform(2.0)]), "escape-ways")
    assert "7.9 m" in f.message  # half way round at 2.5 m
    assert not found(base(platforms=[platform(1.0)]), "escape-ways")
    assert not found(base(platforms=[platform(2.0, [0, 120])]), "escape-ways")


# -- lifting ---------------------------------------------------------------------------------


def heavy(tag="K-1", weight=12.0, centre=(20, 20, 1.5)):
    machine = item(tag, centre, (4, 2, 3), family="compressor")
    machine["dimensions"]["weight"] = weight
    return machine


def pad(box, reach=None):
    zone = {
        "id": "PAD",
        "kind": "crane_pad",
        "volumes": [{"shape": "box", "source": "declared", "box": box}],
    }
    if reach:
        zone["reach_m"] = reach
    return zone


LAYDOWN = {
    "id": "LD",
    "kind": "laydown",
    "volumes": [{"shape": "box", "source": "declared", "box": [30, 10, 0, 36, 16, 3]}],
}


def test_heavy_items_need_a_crane_pad_a_clear_lane_and_laydown():
    (f,) = found(base(equipment=[heavy()], zones=[LAYDOWN]), "lifting")
    assert "no crane pad" in f.message
    near = pad([20, 2, 0, 28, 10, 5])
    assert not found(base(equipment=[heavy()], zones=[near, LAYDOWN]), "lifting")
    assert not found(base(equipment=[heavy()], zones=[near, LAYDOWN]), "laydown")
    # light items need none
    assert not found(base(equipment=[heavy(weight=2.0)]), "lifting")
    # a pipe over the lane, higher than the item's top
    over = a_pipe("OVER", [[10, 13, 6], [30, 13, 6]], line="L-9")
    (f,) = found(base(equipment=[heavy()], zones=[near, LAYDOWN], pipes=[over]), "lifting")
    assert "OVER" in f.message
    # a pipe lower than the item's top does not block it
    low = a_pipe("LOW", [[10, 13, 1], [30, 13, 1]], line="L-9")
    assert not found(base(equipment=[heavy()], zones=[near, LAYDOWN], pipes=[low]), "lifting")
    # a pad out of reach
    far = pad([80, 80, 0, 90, 90, 5], reach=20)
    (f,) = found(base(equipment=[heavy()], zones=[far, LAYDOWN]), "lifting")
    assert "PAD too far" in f.message
    # a laydown too small
    small = {
        **LAYDOWN,
        "volumes": [{"shape": "box", "source": "declared", "box": [30, 10, 0, 32, 12, 3]}],
    }
    (f,) = found(base(equipment=[heavy()], zones=[near, small]), "laydown")
    assert "4.0 x 2.0" in f.message


def test_a_crane_lane_is_the_items_width_across_its_travel_and_takes_a_clear_pad():
    """The load keeps its orientation: lifted east along its 4 m length, a 4 x 2 m item needs
    a lane 2 m + 2 x 1 m wide, not its largest dimension (the ASU's K-4101 out of the open
    side of its fire wall). Of two pads within reach the nearest with a clear lane is taken."""
    east = pad([30, 18, 0, 36, 22, 1])
    beside = a_pipe("BESIDE", [[10, 23, 6], [30, 23, 6]], line="L-9")  # 3 m off the axis
    assert not found(base(equipment=[heavy()], zones=[east, LAYDOWN], pipes=[beside]), "lifting")
    inside = a_pipe("IN", [[10, 21.5, 6], [30, 21.5, 6]], line="L-9")
    (f,) = found(base(equipment=[heavy()], zones=[east, LAYDOWN], pipes=[inside]), "lifting")
    assert "IN" in f.message
    # lifted north across its 2 m width, the lane is 4 m + 2 m wide: the pipe 3 m off blocks it
    north = pad([18, 30, 0, 22, 36, 1])
    side = a_pipe("SIDE", [[22.8, 10, 6], [22.8, 30, 6]], line="L-9")
    (f,) = found(base(equipment=[heavy()], zones=[north, LAYDOWN], pipes=[side]), "lifting")
    assert "SIDE" in f.message
    # the nearer pad's lane is blocked, a farther one is clear: no finding
    near = {**pad([23, 18, 0, 26, 22, 1]), "id": "NEAR"}
    far = {**pad([10, 18, 0, 14, 22, 1]), "id": "FAR"}
    over = a_pipe("OVER", [[22.5, 10, 6], [22.5, 30, 6]], line="L-9")
    assert not found(base(equipment=[heavy()], zones=[near, far, LAYDOWN], pipes=[over]), "lifting")
    (f,) = found(base(equipment=[heavy()], zones=[near, LAYDOWN], pipes=[over]), "lifting")
    assert "NEAR" in f.message and "OVER" in f.message


def test_heavy_items_in_a_building_need_its_crane():
    text = """\
buildings:
  - id: B1
    origin: [10, 10]
    width: 20
    depth: 20
    walls: all
    levels: [{id: G, elevation: 0, height: 10}]
"""
    b1 = building(text)
    (f,) = found(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN]), "lifting")
    assert "no overhead crane" in f.message
    b1["crane"] = {"capacity_t": 10.0}
    (f,) = found(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN]), "lifting")
    assert "lifts 10 t" in f.message
    b1["crane"] = {"capacity_t": 20.0}
    assert not found(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN]), "lifting")
    # the crane carries the gross load (12 t x 1.1 x 1.05 = 13.86 t), not the bare weight
    b1["crane"] = {"capacity_t": 12.0}
    (f,) = found(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN]), "lifting")
    assert "13.9 t gross" in f.message and "lifts 12 t" in f.message
    b1["crane"] = {"capacity_t": 13.86}
    assert not found(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN]), "lifting")


# -- spacing ---------------------------------------------------------------------------------


def pump(tag, x):
    return item(tag, (x, 5, 0.5), (1.5, 0.8, 1.0), family="pump")


def test_equipment_spacing_table():
    assert spacing_rows({"family": "pump"}, {"family": "pump"})[0]["min_m"] == 1.0
    fired = {"family": "generic", "type": "FiredHeater"}
    assert spacing_rows(fired, {"family": "vessel"})[0]["min_m"] == 15.0
    assert not spacing_rows({"family": "generic", "type": "ElectricHeater"}, {"family": "vessel"})
    close = base(equipment=[pump("P-1A", 0), pump("P-1B", 2.0)])  # 0.5 m apart
    (f,) = found(close, "spacing")
    assert f.ids == ["P-1A", "P-1B"] and "0.5 m < 1 m" in f.message
    assert not found(base(equipment=[pump("P-1A", 0), pump("P-1B", 3.0)]), "spacing")
    plan = SitePlan.model_validate(
        {
            "site": {"width": 50, "depth": 50},
            "separations": [{"from": "P-1A", "to": "P-1B", "min_m": 0.4, "reason": "pair"}],
        }
    )
    assert not found(close, "spacing", plan=plan)
    plan = SitePlan.model_validate(
        {"site": {"width": 50, "depth": 50}, "criteria": {"spacing_table": False}}
    )
    assert not found(close, "spacing", plan=plan)
    # stacked items (one above the other) are not compared
    upper = pump("P-1B", 2.0)
    upper["bbox"][2], upper["bbox"][5] = 5.0, 6.0
    assert not found(base(equipment=[pump("P-1A", 0), upper]), "spacing")


def test_spacing_of_turned_items_is_measured_to_their_turned_outline():
    # two 3 x 1 m pumps at 45 degrees side by side: their boxes overlap, their outlines do not
    def turned_pump(tag, offset):
        x, y = -offset / math.sqrt(2), offset / math.sqrt(2)  # across their common axis
        pump_ = item(tag, (x, y, 0.5), (3.0, 1.0, 1.0), family="pump")
        pump_["rotation_deg"] = 45.0
        h = 4.0 / 2 / math.sqrt(2)
        pump_["bbox"] = [x - h, y - h, 0.0, x + h, y + h, 1.0]
        return pump_

    assert not found(base(equipment=[turned_pump("P-1A", 0), turned_pump("P-1B", 2.2)]), "spacing")
    (f,) = found(base(equipment=[turned_pump("P-1A", 0), turned_pump("P-1B", 1.8)]), "spacing")
    assert "0.8 m < 1 m" in f.message


def test_criteria_defaults_and_overrides():
    found_ = criteria()
    assert found_.operator_max_height_m == 1.8 and "package default" in found_.basis["dead_end_m"]
    plan = SitePlan.model_validate(
        {"site": {"width": 5, "depth": 5}, "criteria": {"dead_end_m": 10}}
    )
    assert criteria(plan).dead_end_m == 10.0
    with pytest.raises(ValueError):
        SitePlan.model_validate({"site": {"width": 5, "depth": 5}, "criteria": {"dead_end_m": 0}})
    with pytest.raises(ValueError):
        ZoneList.model_validate(
            {
                "zones": [
                    {
                        "id": "Z",
                        "kind": "laydown",
                        "shape": "box",
                        "box": [0, 0, 0, 1, 1, 1],
                        "reach_m": 5,
                    }
                ]
            }
        )


def test_the_model_schema_takes_penetrations_and_weights():
    cb, _ = walled()
    model = base(structures=[cb], pipes=[a_pipe("IN", [[13, 5, 3], [13, 12, 3]], line="L-IN")])
    (pen,) = crossings(model)
    document = {
        "schema": "cheme/layout_model/v1",
        "kind": "layout_model",
        "provenance": {
            "generator": "g",
            "generator_version": "2",
            "generator_sha256": "x",
            "sources": {},
            "output_sha256": "",
        },
        "penetrations": [pen],
    }
    LayoutModelFile.model_validate(document)


def test_the_build_carries_weights_and_penetrations(plant3d: Path):
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.foundation.workspace import Workspace
    from tests.test_layout_3d import EQUIPMENT

    (plant3d / "equipment" / "equipment-list.yaml").write_text(
        EQUIPMENT.replace("{diameter: 2, height: 8}", "{diameter: 2, height: 8, weight: 12}")
    )
    model = build_model(Workspace(plant3d))
    document = model.document
    LayoutModelFile.model_validate(document)
    vessel = next(e for e in document["equipment"] if e["tag"] == "V-101")
    assert vessel["dimensions"]["weight"] == 12
    assert document["penetrations"] == []  # no walls
    rules = {f.rule for f in model.findings}
    assert "cheme.layout-lifting" in rules  # 12 t and no crane pad


def test_walls_are_cut_around_overlapping_openings():
    text = """\
buildings:
  - id: B1
    origin: [0, 0]
    width: 10
    depth: 8
    walls: all
    levels: [{id: G, elevation: 0, height: 6}]
    openings:
      - {id: L, side: south, offset: 1, width: 6, height: 1, sill: 4, kind: louvre}
      - {id: P, side: south, offset: 5, width: 0.5, height: 0.5, sill: 2}
"""
    b1 = building(text)
    line = a_pipe("CW", [[5.25, -5, 2.25], [5.25, 4, 2.25]], od=0.2, line="CW-1")
    assert crossings(base(buildings=[b1], pipes=[line])) == []
    south = [p for p in b1["parts"] if p["id"].startswith("B1/wall-south-")]
    # 0..1 full; 1..5 under and over the louvre; 5..5.5 under the pipe, between, over the
    # louvre; 5.5..7 as 1..5; 7..10 full
    assert len(south) == 1 + 2 + 3 + 2 + 1


def test_the_router_sees_the_declared_platforms(plant3d: Path, monkeypatch):
    """Declared platforms exist before routing: vent risers keep their zones off them."""
    from chemeascode.domains.spatial import routing
    from chemeascode.domains.spatial.model import build_model
    from chemeascode.foundation.workspace import Workspace
    from tests.test_layout_3d import PLACEMENT

    placement = plant3d / "layout" / "equipment-placement.yaml"
    placement.write_text(
        PLACEMENT.replace(
            "{tag: V-101, position: [10, 10, 0]}",
            "{tag: V-101, position: [10, 10, 0], access: {platforms: [{elevation: 6}]}}",
        )
    )
    seen = []
    real = routing.route_model

    def spy(document, *args, **kwargs):
        seen.append([p["id"] for p in document["platforms"]])
        return real(document, *args, **kwargs)

    monkeypatch.setattr(routing, "route_model", spy)
    model = build_model(Workspace(plant3d))
    assert seen == [["V-101/platform-1"]]
    assert [p["id"] for p in model.document["platforms"]] == ["V-101/platform-1"]
    floors = {f.id for f in walking_levels(model.document)}
    assert "V-101/platform-1" in floors


def test_a_smaller_line_keeps_its_bottom_on_the_tier():
    """A chain routed at the lane of its largest pipe: the smaller pieces are lowered onto the
    tier where they run along the rack, with a step at the junction (flat bottom)."""
    from chemeascode.domains.spatial.routing import _flat_bottom

    # lane of a DN900 (r 0.457) on a 7 m tier; the second piece is DN600 (r 0.305)
    z = 7.457
    on_rack = [(0.0, 0.0, z), (40.0, 0.0, z)]
    pieces = [
        [(0.0, -5.0, 3.0), (0.0, 0.0, 3.0), (0.0, 0.0, z), (10.0, 0.0, z)],
        [(10.0, 0.0, z), (40.0, 0.0, z), (40.0, 0.0, 3.0)],
    ]
    sizes = [(900.0, 0.914, 0.0), (600.0, 0.61, 0.0)]
    first, second = _flat_bottom(pieces, sizes, on_rack, [z])
    assert first == pieces[0]  # the largest stays
    low = 7.0 + 0.305
    assert second[0] == (10.0, 0.0, z)  # the step at the junction
    assert second[1] == pytest.approx((10.0, 0.0, low))
    assert second[2] == pytest.approx((40.0, 0.0, low))
    assert second[3] == (40.0, 0.0, 3.0)  # off the rack: unchanged
    # a piece off the lanes, or a chain of one size, is unchanged
    same = [(600.0, 0.61, 0.0), (600.0, 0.61, 0.0)]
    assert _flat_bottom(pieces, same, on_rack, [z]) == pieces
    assert _flat_bottom(pieces, sizes, on_rack, [9.0]) == pieces
