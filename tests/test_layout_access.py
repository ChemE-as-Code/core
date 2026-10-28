"""Access in the 3D model: stair and ladder proposals on structures, guard rail detail, rack
ladders, step-overs over low pipes, bunds, and pinning the proposals."""

from pathlib import Path

import yaml
from typer.testing import CliRunner

from chemeascode.domains.spatial.model import build_model, read, write_model
from chemeascode.domains.spatial.schemas import SitePlan, StructureList
from chemeascode.domains.spatial.structures import (
    frame_structure,
    rack_ladders,
    step_overs,
)
from chemeascode.foundation.workspace import Workspace
from chemeascode.interfaces.cli import app
from tests import test_layout_3d

plant3d = test_layout_3d.plant3d  # the fixture: a plant with a vessel, a pump and a rack
runner = CliRunner()

TOWER = """\
structures:
  - id: S1
    origin: [0, 0]
    spans_x: [6]
    spans_y: [8]
    levels:
      - {id: L1, elevation: 4}
      - {id: L2, elevation: 8, kind: platform}
      - {id: L3, elevation: 12, kind: platform, extent: [0, 0, 3, 4]}
      - {id: L3B, elevation: 12, kind: platform, extent: [3, 0, 6, 4]}
    stairs: [{id: ST1, from: grade, to: L1, side: east}]
    ladders: [{id: LD1, from: L1, to: L2, at: [0.5, 0.5]}]
"""


def structure(text=TOWER):
    (found,) = StructureList.model_validate(yaml.safe_load(text)).structures
    return frame_structure(found, "layout/structures.yaml")


def test_stairs_and_ladders_are_proposed_by_the_rules():
    entry = structure()
    proposed = {s["id"]: s for s in entry["stairs"] if s["source"] == "generated"}
    # L1 (a deck, regular use) has its stair; L2 (8 m) and L3 (12 m) need one
    assert set(proposed) == {"S1/stair-to-L2", "S1/stair-to-L3"}
    stair = proposed["S1/stair-to-L2"]
    assert stair["review_needed"] and "8 m" in stair["reason"] and stair["from"] == "L1"
    assert stair["side"] == "east" and stair["offset"] == 0.0  # stacked on ST1
    ladders = {lad["id"]: lad for lad in entry["ladders"] if lad["source"] == "generated"}
    # L1: one stair only -> a second way down; L2: ladder + stair = 2; L3 and L3B share a
    # floor (same elevation, touching): one stair -> a ladder
    assert set(ladders) == {"S1/ladder-to-L1", "S1/ladder-to-L3"}
    ladder = ladders["S1/ladder-to-L1"]
    assert ladder["from"] == "grade" and ladder["cage"] and ladder["review_needed"]
    assert ladder["facing"] in ("south", "north", "east", "west") and len(ladder["at"]) == 2
    levels = {lv["id"]: lv["use"] for lv in entry["levels"]}
    assert levels == {"L1": "regular", "L2": "occasional", "L3": "occasional", "L3B": "occasional"}


def test_a_low_occasional_platform_takes_a_ladder_not_a_stair():
    text = TOWER.replace("{id: L1, elevation: 4}", "{id: L1, elevation: 4, kind: platform}")
    text = text.replace("    stairs: [{id: ST1, from: grade, to: L1, side: east}]\n", "")
    entry = structure(text)
    ids = {s["id"] for s in entry["stairs"]}
    assert "S1/stair-to-L1" not in ids  # 4 m, occasional
    assert "S1/ladder-to-L1" in {lad["id"] for lad in entry["ladders"]}


def test_guard_rails_have_mid_rails_toe_plates_and_posts():
    parts = structure()["parts"]
    ids = {p["id"]: p for p in parts}
    assert ids["S1/L1/handrail-0"].get("lod") is None  # the top rail: envelope
    assert ids["S1/L1/handrail-0-mid"]["lod"] == 2
    assert ids["S1/L1/handrail-0-toe"]["material"] == "steel"
    posts = [i for i in ids if i.startswith("S1/L1/handrail-0-post-")]
    assert len(posts) == 5  # 6 m at most 1.8 m apart
    stair = structure()["stairs"][0]
    assert any("/handrail-a" in p["id"] and p["lod"] == 2 for p in stair["parts"])


def test_rack_ladders_at_free_ends_unless_declared():
    plan = SitePlan.model_validate(
        {
            "site": {"width": 100, "depth": 100},
            "racks": [
                {"id": "R1", "points": [[10, 10], [50, 10]], "width": 6, "levels": [5, 7]},
                {"id": "R2", "points": [[50, 10], [50, 40]], "width": 4, "levels": [6]},
                {
                    "id": "R3",
                    "points": [[0, 80], [20, 80]],
                    "width": 3,
                    "levels": [5],
                    "ladders": [],
                },
            ],
        }
    )
    r1, r2, r3 = plan.racks
    found = rack_ladders(r1, [r2, r3], "f")
    assert [lad["id"] for lad in found] == ["R1/ladder-start"]  # its end joins R2
    start = found[0]
    assert start["base"][0] < 10 and start["top"][2] == 7 and start["cage"]
    assert start["end"] == "start" and start["review_needed"]
    # R2 starts inside R1: that end is a joint too, reached from R1
    assert [lad["id"] for lad in rack_ladders(r2, [r1], "f")] == ["R2/ladder-end"]
    assert rack_ladders(r3, [], "f") == []  # declared: none


def test_a_low_pipe_across_an_escape_route_gets_a_step_over():
    model = {
        "zones": [
            {
                "id": "ESC",
                "kind": "escape",
                "volumes": [{"shape": "box", "source": "declared", "box": [0, 4, 0, 20, 6, 2.2]}],
            }
        ],
        "structures": [],
        "pipes": [
            {
                "id": "P/S1",
                "refs": {"sheet": "pid/P.xml"},
                "line": "L-1",
                "segment": "S1",
                "od": 0.1143,
                "insulation_mm": 0,
                "points": [[10, 0, 0.3], [10, 10, 0.3]],
            },
            {
                "id": "P/S2",
                "refs": {},
                "line": "L-2",
                "segment": "S2",
                "od": 0.1143,
                "insulation_mm": 0,
                "points": [[12, 0, 3.0], [12, 10, 3.0]],  # high: no step-over
            },
        ],
    }
    (step,) = step_overs(model)
    assert step["pipe"] == "P/S1" and step["walkway"] == "ESC-0" and step["review_needed"]
    assert step["point"] == (10, 5, 0) and step["height"] > 0.3 + 0.057
    deck = step["parts"][0]
    assert deck["id"] == "step-over-1/deck" and deck["material"] == "grating"
    assert any(p["id"].startswith("step-over-1/tread-") for p in step["parts"])
    assert step_overs(model) == step_overs(model)


def test_the_build_holds_proposals_bunds_and_pins_them(plant3d: Path, monkeypatch):
    site = (plant3d / "layout" / "site-plan.yaml").read_text()
    site = site.replace(
        "  - {id: A1, box: [2, 2, 38, 28]}\n",
        "  - {id: A1, box: [2, 2, 38, 28]}\n"
        "  - {id: BND, box: [25, 20, 35, 27], kind: bund, wall_height: 1.2}\n",
    )
    (plant3d / "layout" / "site-plan.yaml").write_text(site)
    workspace = Workspace(plant3d)
    model = build_model(workspace)
    document = model.document
    bund = next(a for a in document["areas"] if a["id"] == "BND")
    assert bund["wall_height"] == 1.2 and len(bund["parts"]) == 4
    assert bund["parts"][0]["material"] == "concrete" and bund["parts"][0]["size"][2] == 1.2
    assert "cheme.layout-area-overlap" not in {f.rule for f in model.findings}
    rack = document["racks"][0]
    assert [lad["id"] for lad in rack["ladders"]] == ["PR-1/ladder-start", "PR-1/ladder-end"]
    write_model(workspace, model)
    monkeypatch.chdir(plant3d)
    stairs = [s for s in document["structures"][0]["stairs"] if s["source"] == "generated"]
    ladders = [lad for lad in document["structures"][0]["ladders"] if lad["source"] == "generated"]
    assert stairs and ladders
    for target in (stairs[0]["id"], ladders[0]["id"], "PR-1/ladder-end"):
        result = runner.invoke(app, ["layout", "pin", target])
        assert result.exit_code == 0, result.output
    frames = yaml.safe_load((plant3d / "layout" / "structures.yaml").read_text())
    (frame,) = frames["structures"]
    local = stairs[0]["id"].split("/", 1)[1]
    assert any(s["id"] == local for s in frame["stairs"])
    assert any(lad["id"] == ladders[0]["id"].split("/", 1)[1] for lad in frame["ladders"])
    plan = yaml.safe_load((plant3d / "layout" / "site-plan.yaml").read_text())
    assert plan["racks"][0]["ladders"] == [{"id": "ladder-end", "end": "end"}]
    assert runner.invoke(app, ["layout", "build"]).exit_code == 0
    rebuilt = read((plant3d / "layout" / "plant-model.yaml").read_text())
    sources = {s["id"]: s["source"] for s in rebuilt["structures"][0]["stairs"]}
    assert sources[stairs[0]["id"]] == "declared"
    assert [lad["source"] for lad in rebuilt["racks"][0]["ladders"]] == ["declared"]


def test_a_clad_building_has_a_roof_doors_louvres_and_its_crane():
    from chemeascode.domains.spatial.schemas import BuildingList
    from chemeascode.domains.spatial.structures import building_parts

    (building,) = BuildingList.model_validate(
        {
            "buildings": [
                {
                    "id": "B1",
                    "origin": [10, 10],
                    "width": 30,
                    "depth": 20,
                    "walls": "all",
                    "crane": {"capacity_t": 32},
                    "openings": [
                        {"id": "D1", "side": "south", "offset": 2, "width": 1.2, "height": 2.2},
                        {
                            "id": "R1",
                            "side": "west",
                            "offset": 5,
                            "width": 5,
                            "height": 5,
                            "kind": "roller_door",
                        },
                        {
                            "id": "L1",
                            "side": "north",
                            "offset": 3,
                            "width": 6,
                            "height": 1.5,
                            "sill": 4,
                            "kind": "louvre",
                        },
                    ],
                }
            ]
        }
    ).buildings
    parts = {p["id"]: p for p in building_parts(building, 12.0)}
    roof = parts["B1/roof"]
    assert roof["material"] == "roof" and roof.get("lod") is None
    assert roof["centre"][2] == 12.1 and roof["size"][:2] == (30, 20)
    assert parts["B1/roof-ridge"]["kind"] == "frustum" and parts["B1/roof-ridge"]["lod"] == 2
    leaf = parts["B1/D1/leaf"]
    assert leaf["material"] == "door" and leaf["lod"] == 2 and leaf["size"][2] == 2.2
    assert {"B1/R1/shutter", "B1/R1/drum"} <= set(parts)
    assert sum(i.startswith("B1/L1/blade-") for i in parts) == 10
    runway = [p for i, p in parts.items() if i.startswith("B1/crane/runway-")]
    assert len(runway) == 2 and runway[0]["section"] == "HEB600"  # above 20 t
    assert runway[0]["start"][2] == runway[0]["end"][2] < 12  # along the long side
    assert runway[0]["start"][1] == runway[0]["end"][1]
    assert {"B1/crane/bridge", "B1/crane/crab", "B1/crane/hook-block"} <= set(parts)
    assert all(parts[i]["lod"] == 2 for i in ("B1/crane/bridge", "B1/crane/crab"))


def test_plans_draw_the_envelope_with_stairs_handrails_and_flanges(plant3d: Path):
    from chemeascode.domains.spatial.drawing2d import in_plan, level_range, render_plan

    workspace = Workspace(plant3d)
    write_model(workspace, build_model(workspace))
    model = read((plant3d / "layout" / "plant-model.yaml").read_text())
    plan = render_plan(model)
    assert 'id="stair-S1/stair-to-L2"' in plan  # a proposal, dashed
    assert 'id="ladder-PR-1/ladder-start"' in plan
    level = render_plan(model, cut=level_range(model, "L1"))
    assert "1,0.6" in level  # the handrails of the cut level
    pump = next(e for e in model["equipment"] if e["tag"] == "P-101")
    drawn = [p["id"] for p in pump["parts"] if in_plan(p)]
    assert "P-101/suction-flange" in drawn and "P-101/discharge-flange" in drawn
    assert "P-101/rib-1" not in drawn and "P-101/casing" in drawn


def test_a_leg_along_the_face_of_the_item_a_pipe_ends_at_is_no_clash():
    from chemeascode.domains.spatial.model_rules import model_rules

    psv = test_layout_3d.item("PSV", (10, 5, 1), (0.8, 0.6, 1.5))
    model = {
        "equipment": [psv],
        "racks": [],
        "structures": [],
        "zones": [],
        "areas": [],
        "pipes": [
            {
                "id": "P/S1",
                "line": "L-1",
                "segment": "S1",
                "od": 0.06,
                "insulation_mm": 0,
                "points": [[5, 5.2, 1.2], [9.6, 5.2, 1.2], [9.6, 5.2, 1.0], [9.6, 4.7, 1.0]],
                "method": "astar",
            }
        ],
    }
    rules = {f.rule for f in model_rules(model, None, None)}
    assert "cheme.layout-clash-pipe-equipment" not in rules
    model["pipes"][0]["points"] = [[5, 5.0, 1.0], [11, 5.0, 1.0], [12, 5.0, 1.0]]  # through it
    rules = {f.rule for f in model_rules(model, None, None)}
    assert "cheme.layout-clash-pipe-equipment" in rules
