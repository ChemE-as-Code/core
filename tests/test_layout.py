"""The 3D layout: schemas, the ``cheme.layout-*`` rules, and ``/api/layout``."""

import os
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.spatial.layout_validate import (
    CIRCLE_SIDES,
    body_outline,
    building_heights,
    check_layout,
    clash_pieces,
    equipment_box,
    level_heights,
    polygons_overlap,
    resolve,
    strip,
)
from chemeascode.domains.spatial.schemas import Building, Placement
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from chemeascode.schemas import EquipmentList, PlacementList
from tests.conftest import git

SITE = """\
site: {name: Plot, width: 60, depth: 40}
areas:
  - {id: A-100, title: Process, box: [10, 18, 46, 38], kind: process}
  - {id: A-300, title: Storage, box: [48, 31, 58, 38], kind: storage}
  - {id: A-310, title: Bund, box: [48, 18, 58, 30], kind: storage}
roads:
  - {id: R-1, points: [[0, 13], [60, 13]], width: 6}
racks:
  - {id: PR-1, points: [[10, 20], [46, 20]], width: 4, levels: [5, 7]}
"""

BUILDING = """\
buildings:
  - id: B-1
    origin: [26, 26]
    width: 14
    depth: 10
    levels:
      - {id: GF, elevation: 0, height: 5}
      - {id: PF, elevation: 5, height: 4, kind: platform}
    frame: {grid_x: [0, 7, 14], grid_y: [0, 5, 10]}
"""

PLACEMENT = """\
equipment:
  - {tag: P4711, position: [16, 24.5, 0]}
  - {tag: P4712, position: [20, 24.5, 0]}
  - {tag: H1007, position: [29, 30, 0], mount: {building: B-1, level: GF}}
  - tag: H1008
    position: [34, 31, 5]
    mount: {building: B-1, level: PF}
  - {tag: T4750, position: [53, 24, 0]}
"""

#: The same items sized in the placement (the fallback for items without dimensions).
SIZED = """\
equipment:
  - {tag: P4711, position: [16, 24.5, 0], shape: box, size: [2.0, 0.8, 1.0]}
  - {tag: P4712, position: [20, 24.5, 0], shape: box, size: [2.5, 1.2, 1.2]}
  - {tag: H1007, position: [29, 30, 0], size: [1.2, 0.6, 1.8], mount: {building: B-1, level: GF}}
  - tag: H1008
    position: [34, 31, 5]
    shape: horizontal_cylinder
    size: {diameter: 0.8, length: 5}
    mount: {building: B-1, level: PF}
  - {tag: T4750, position: [53, 24, 0], shape: vertical_cylinder, size: {diameter: 6, height: 7}}
"""

EQUIPMENT = """\
equipment:
  - {tag: H1007, type: PlateHeatExchanger, sheet: P-01,
     dimensions: {length: 1.2, width: 0.6, height: 1.8}}
  - {tag: H1008, type: TubularHeatExchanger, sheet: P-01, dimensions: {diameter: 0.8, length: 5}}
  - {tag: P4711, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 2.0, width: 0.8, height: 1.0}}
  - {tag: P4712, type: ReciprocatingPump, sheet: P-01,
     dimensions: {length: 2.5, width: 1.2, height: 1.2}}
  - {tag: T4750, type: Tank, sheet: P-01, dimensions: {diameter: 6, height: 7}}
"""

#: The equipment list without dimensions, for :data:`SIZED`.
BARE = """\
equipment:
  - {tag: H1007, type: PlateHeatExchanger, sheet: P-01}
  - {tag: H1008, type: TubularHeatExchanger, sheet: P-01}
  - {tag: P4711, type: CentrifugalPump, sheet: P-01}
  - {tag: P4712, type: ReciprocatingPump, sheet: P-01}
  - {tag: T4750, type: Tank, sheet: P-01}
"""


def run(site=SITE, building=BUILDING, placement=PLACEMENT, equipment=EQUIPMENT):
    texts = {}
    for kind, name, text in (
        ("site_plan", "layout/site-plan.yaml", site),
        ("building", "layout/building.yaml", building),
        ("placement", "layout/equipment-placement.yaml", placement),
    ):
        if text is not None:
            texts[kind] = (name, text)
    listed = EquipmentList.model_validate(yaml.safe_load(equipment)) if equipment else None
    eq_text = ("equipment/equipment-list.yaml", equipment) if equipment else None
    return check_layout(texts, listed, eq_text)


FALLBACK = "cheme.layout-size-from-placement"


def rules(layout, level=None):
    """The rules of the findings, without the size-from-placement note (most tests place items
    by their size, without dimensions in the equipment list)."""
    return [
        f.rule
        for f in layout.findings
        if (level is None or f.level == level) and f.rule != FALLBACK
    ]


def place(*lines: str) -> str:
    """The placement file with *lines* appended (a YAML list entry each)."""
    return PLACEMENT + "".join(f"  - {line}\n" for line in lines)


def listed(*tags: str) -> str:
    return EQUIPMENT + "".join(f"  - {{tag: {tag}, type: Vessel}}\n" for tag in tags)


# -- schemas ---------------------------------------------------------------------------


def test_the_reference_layout_is_clean():
    layout = run()
    assert layout.findings == []
    assert layout.ruled and layout.present == ["site_plan", "building", "placement"]


@pytest.mark.parametrize(
    ("kind", "text", "line", "message"),
    [
        ("site", SITE.replace("[10, 18, 46, 38]", "[46, 18, 10, 38]"), 3, "x0 < x1"),
        ("site", SITE.replace("width: 6}", "width: 0}"), 7, "width must be greater"),
        ("site", SITE.replace("width: 60", "widht: 60"), 1, "Extra inputs"),
        (
            "building",
            BUILDING.replace("    depth: 10", "    depth: 10\n    rotation_deg: 45"),
            6,
            "",
        ),
        ("building", BUILDING.replace("[0, 7, 14]", "[0, 7, 15]"), 2, "outside 0..14"),
        ("placement", SIZED.replace("[2.0, 0.8, 1.0]", "{diameter: 1}"), 2, "box takes size"),
        ("placement", SIZED.replace("length: 5", "height: 5"), 5, "needs size.length"),
        ("placement", SIZED.replace("[16, 24.5, 0]", "[16, 24.5]"), 2, ""),
        ("placement", PLACEMENT.replace("building: B-1, level", "level"), 4, "a building or"),
    ],
)
def test_schema_errors_name_the_line(kind, text, line, message):
    layout = run(**{kind: text})
    errors = [f for f in layout.findings if f.rule == "yaml.schema"]
    assert errors, layout.findings
    assert errors[0].line == line, errors
    assert any(message in error.message for error in errors), errors
    assert not layout.ruled  # the cross rules wait for valid files


def test_union_branches_are_not_part_of_the_location():
    layout = run(placement=SIZED.replace("[2.0, 0.8, 1.0]", "[2.0, -1, 1.0]"))
    assert layout.findings[0].message.startswith("equipment.0")
    assert "tuple[" not in layout.findings[0].message


def test_yaml_syntax_error():
    layout = run(building="buildings: [\n")
    assert rules(layout) == ["yaml.syntax"]


def test_extents_of_each_shape():
    def box(entry: str):
        item = PlacementList.model_validate(yaml.safe_load(f"equipment:\n  - {entry}")).equipment
        return [round(v, 6) for v in equipment_box(item[0])]

    assert box("{tag: A, position: [5, 5, 1], size: [4, 2, 3]}") == [3, 4, 1, 7, 6, 4]
    assert box("{tag: A, position: [5, 5, 1], size: [4, 2, 3], rotation_deg: 90}") == [
        4,
        3,
        1,
        6,
        7,
        4,
    ]
    cylinder = "{tag: A, position: [5, 5, 0], shape: horizontal_cylinder, "
    assert box(cylinder + "size: {diameter: 2, length: 6}}") == [2, 4, 0, 8, 6, 2]
    vertical = "{tag: A, position: [5, 5, 0], shape: vertical_cylinder, "
    assert box(vertical + "size: {diameter: 2, height: 6}}") == [4, 4, 0, 6, 6, 6]
    sphere = "{tag: A, position: [5, 5, 0], shape: sphere, size: {diameter: 2}}"
    assert box(sphere) == [4, 4, 0, 6, 6, 2]


# -- layout-outside-site ---------------------------------------------------------------


def test_outside_site():
    layout = run(
        placement=place("{tag: V1, position: [59, 35, 0], size: [3, 1, 1]}"), equipment=listed("V1")
    )
    assert rules(layout) == ["cheme.layout-outside-site"]
    finding = layout.findings[0]
    assert finding.ids == ["V1"] and finding.line == 9
    assert finding.file == "layout/equipment-placement.yaml"


def test_touching_the_site_edge_is_inside():
    layout = run(
        placement=place("{tag: V1, position: [58.5, 35, 0], size: [3, 1, 1]}"),
        equipment=listed("V1"),
    )
    assert rules(layout) == []


def test_areas_roads_racks_and_buildings_outside_the_site():
    site = SITE.replace("[48, 31, 58, 38]", "[48, 31, 61, 38]").replace(
        "[[0, 13], [60, 13]]", "[[0, 38.5], [60, 38.5]]"
    )
    building = BUILDING.replace("origin: [26, 26]", "origin: [50, 26]")
    layout = run(site=site, building=building, placement=None)
    outside = sorted(f.ids[0] for f in layout.findings if f.rule.endswith("outside-site"))
    assert outside == ["A-300", "B-1", "R-1"]


# -- layout-clash -------------------------------------------------------------------------


def test_two_equipment_boxes_clash():
    layout = run(placement=PLACEMENT.replace("[20, 24.5, 0]", "[17.5, 24.5, 0]"))
    assert rules(layout) == ["cheme.layout-clash"]
    assert layout.findings[0].ids == ["P4711", "P4712"]
    assert layout.clashing == {"P4711", "P4712"}


def test_touching_or_stacked_boxes_do_not_clash():
    touching = run(placement=PLACEMENT.replace("[20, 24.5, 0]", "[18.25, 24.5, 0]"))
    assert rules(touching) == []
    stacked = place("{tag: V1, position: [16, 24.5, 1.0], size: [1, 0.5, 0.5]}")
    assert rules(run(placement=stacked, equipment=listed("V1"))) == []


def test_rotation_makes_a_clash():
    placement = place("{tag: V1, position: [16, 26.5, 0], size: [4, 1, 1]}")
    assert rules(run(placement=placement, equipment=listed("V1"))) == []
    rotated = place("{tag: V1, position: [16, 26.5, 0], size: [4, 1, 1], rotation_deg: 90}")
    assert rules(run(placement=rotated, equipment=listed("V1"))) == ["cheme.layout-clash"]


OPEN_SITE = "site: {name: P, width: 60, depth: 40}\n"
TANKS_AND_PUMPS = """\
equipment:
  - {tag: T1, type: Tank, sheet: P-01, dimensions: {diameter: 6, height: 7}}
  - {tag: T2, type: Tank, sheet: P-01, dimensions: {diameter: 6, height: 7}}
  - {tag: P1, type: CentrifugalPump, sheet: P-01, dimensions: {length: 3, width: 1, height: 1}}
  - {tag: P2, type: CentrifugalPump, sheet: P-01, dimensions: {length: 3, width: 1, height: 1}}
  - {tag: V1, type: Vessel, sheet: P-01}
"""


def clashes(*lines: str) -> list[str]:
    placement = "equipment:\n" + "".join(f"  - {line}\n" for line in lines)
    layout = run(site=OPEN_SITE, building=None, placement=placement, equipment=TANKS_AND_PUMPS)
    return [f.message for f in layout.findings if f.rule == "cheme.layout-clash"]


def test_round_items_clash_by_their_circles_not_their_boxes():
    # D 6 m tanks 7.07 m apart on the diagonal: 1.07 m clear, though their boxes overlap
    assert clashes("{tag: T1, position: [10, 10, 0]}", "{tag: T2, position: [15, 15, 0]}") == []
    (message,) = clashes("{tag: T1, position: [10, 10, 0]}", "{tag: T2, position: [14, 14, 0]}")
    assert message.startswith("T1 ") and "T2" in message


def test_turned_items_clash_by_their_turned_outlines():
    # two 3 x 1 m pumps at 45 degrees, 3.68 m apart along their common axis: no overlap
    p1 = "{tag: P1, position: [30, 10, 0], rotation_deg: 45}"
    assert clashes(p1, "{tag: P2, position: [32.6, 12.6, 0], rotation_deg: 45}") == []
    assert clashes(p1, "{tag: P2, position: [31.5, 11.5, 0], rotation_deg: 45}")
    # beside each other, 1.2 m apart across the axis: no overlap, though the boxes do
    assert clashes(p1, "{tag: P2, position: [29.2, 10.8, 0], rotation_deg: 45}") == []


def test_a_round_item_by_a_road_corner_is_tested_by_its_circle():
    site = SITE.replace("areas:\n", "areas:\n  - {id: A-R, box: [0, 30, 8, 34], kind: road}\n")
    # T4750 (D 6 m): its box takes in the road area's corner (8, 34), its circle (3.54 m from
    # the corner) does not
    clear = PLACEMENT.replace("[53, 24, 0]", "[10.5, 36.5, 0]")
    assert rules(run(site=site, placement=clear)) == []
    onto = PLACEMENT.replace("[53, 24, 0]", "[10, 36, 0]")  # 2.83 m from the corner
    layout = run(site=site, placement=onto)
    assert rules(layout) == ["cheme.layout-clash"] and layout.findings[0].ids == ["T4750", "A-R"]


def test_an_item_in_a_tanks_stair_clashes():
    # the stair winds up outside the tank's circle; its first treads are south-west of it
    tank = "{tag: T1, position: [10, 10, 0]}"
    (message,) = clashes(tank, "{tag: V1, position: [6.8, 8.6, 0], size: [0.4, 0.4, 1]}")
    assert "T1's stair-" in message
    assert clashes(tank, "{tag: V1, position: [6.8, 12.0, 0], size: [0.4, 0.4, 1]}") == []


def test_clash_pieces_are_the_outline_and_the_parts_standing_out():
    items = {
        i.tag: i for i in EquipmentList.model_validate(yaml.safe_load(TANKS_AND_PUMPS)).equipment
    }
    tank = resolve(Placement(tag="T1", position=(10, 10, 0)), items["T1"]).body
    outline, *parts = clash_pieces(tank)
    assert outline.part is None and len(outline.polygon) == CIRCLE_SIDES
    assert parts and all(piece.part.startswith("stair-") for piece in parts)
    pump = resolve(Placement(tag="P1", position=(0, 0, 0), rotation_deg=30), items["P1"]).body
    (only,) = clash_pieces(pump)  # its parts stay inside its turned rectangle
    assert only.polygon == body_outline(pump)


def test_equipment_in_a_building_it_is_not_placed_in():
    stray = place("{tag: V1, position: [38, 34, 0], size: [1, 1, 1]}")
    layout = run(placement=stray, equipment=listed("V1"))
    assert rules(layout) == ["cheme.layout-clash"]
    assert layout.findings[0].ids == ["V1", "B-1"]
    housed = place(
        "{tag: V1, position: [38, 34, 0], size: [1, 1, 1], mount: {building: B-1, level: GF}}"
    )
    assert rules(run(placement=housed, equipment=listed("V1"))) == []
    above = place("{tag: V1, position: [38, 34, 9], size: [1, 1, 1]}")
    assert rules(run(placement=above, equipment=listed("V1"))) == []


def test_equipment_on_a_road_or_under_a_rack():
    on_road = place("{tag: V1, position: [30, 15, 0], size: [1, 1, 1]}")
    layout = run(placement=on_road, equipment=listed("V1"))
    assert rules(layout) == ["cheme.layout-clash"] and layout.findings[0].ids == ["V1", "R-1"]
    tall_under_rack = place("{tag: V1, position: [30, 21, 0], size: [1, 1, 4.6]}")
    layout = run(placement=tall_under_rack, equipment=listed("V1"))
    assert rules(layout) == ["cheme.layout-clash"]
    assert (
        layout.findings[0].ids == ["V1", "PR-1"] and "tiers at 5, 7 m" in layout.findings[0].message
    )
    beside = place("{tag: V1, position: [30, 22.5, 0], size: [1, 1, 1]}")
    assert rules(run(placement=beside, equipment=listed("V1"))) == []


def test_a_road_area_counts_as_road():
    site = SITE.replace("areas:\n", "areas:\n  - {id: A-R, box: [0, 30, 8, 34], kind: road}\n")
    placement = place("{tag: V1, position: [4, 32, 0], size: [1, 1, 1]}")
    layout = run(site=site, placement=placement, equipment=listed("V1"))
    assert rules(layout) == ["cheme.layout-clash"] and "A-R" in layout.findings[0].ids


def test_a_diagonal_road_is_tested_as_a_strip_not_its_bounding_box():
    road = strip([(0, 0), (10, 10)], 1)
    corner = [(8, 0), (10, 0), (10, 2), (8, 2)]  # inside the road's bounding box, off the road
    assert not polygons_overlap(road[0], corner)
    assert polygons_overlap(road[0], [(4, 4), (6, 4), (6, 6), (4, 6)])


# -- layout-unknown-tag, layout-not-placed --------------------------------------------------


def test_unknown_tag():
    layout = run(placement=place("{tag: X999, position: [5, 30, 0], size: [1, 1, 1]}"))
    assert rules(layout) == ["cheme.layout-unknown-tag"]
    assert layout.findings[0].ids == ["X999"] and layout.findings[0].line == 9


def test_not_placed_is_info_on_the_equipment_list():
    layout = run(equipment=listed("V9"))
    assert rules(layout) == ["cheme.layout-not-placed"]
    finding = layout.findings[0]
    assert finding.level == "info" and finding.file == "equipment/equipment-list.yaml"
    assert finding.line == 10


def test_not_placed_needs_a_placement_file():
    assert rules(run(placement=None, equipment=listed("V9"))) == []


def test_tag_rules_need_the_equipment_list():
    layout = run(
        placement=place("{tag: X999, position: [5, 30, 0], size: [1, 1, 1]}"), equipment=None
    )
    assert rules(layout) == []


# -- layout-level ------------------------------------------------------------------------------


def test_level_elevation_must_match():
    layout = run(placement=PLACEMENT.replace("[34, 31, 5]", "[34, 31, 5.2]"))
    assert rules(layout) == ["cheme.layout-level"]
    assert "level PF of B-1 is at 5 m" in layout.findings[0].message
    assert layout.findings[0].line == 6  # the position line
    within = run(placement=PLACEMENT.replace("[34, 31, 5]", "[34, 31, 5.04]"))
    assert rules(within) == []


def test_unknown_level_or_building():
    assert rules(run(placement=PLACEMENT.replace("level: PF", "level: L9"))) == [
        "cheme.layout-level"
    ]
    other = PLACEMENT.replace("{building: B-1, level: PF}", "{building: B-9, level: PF}")
    layout = run(placement=other)
    # ... and H1008, now not placed in B-1, stands inside it.
    assert sorted(rules(layout)) == ["cheme.layout-clash", "cheme.layout-level"]
    assert any("B-9" in f.message for f in layout.findings)
    no_buildings = run(building=None)
    assert set(rules(no_buildings)) == {"cheme.layout-level"}


def test_placed_item_must_be_inside_its_building():
    layout = run(placement=PLACEMENT.replace("[29, 30, 0]", "[26.2, 30, 0]"))
    assert rules(layout) == ["cheme.layout-level"]
    assert "not inside building B-1" in layout.findings[0].message


def test_rotated_building_footprint():
    building = BUILDING.replace("origin: [26, 26]", "origin: [40, 27]\n    rotation_deg: 90")
    # Rotated 90 degrees about (40, 27): x 30..40, y 27..41 -> exceeds the site's 40 m depth.
    layout = run(building=building, placement=None)
    assert rules(layout) == ["cheme.layout-outside-site"]
    building = BUILDING.replace("origin: [26, 26]", "origin: [40, 24]\n    rotation_deg: 90")
    # x 30..40, y 24..38; H1007 at (29, 30) is outside, H1008 (31.5..36.5, 30.6..31.4) inside.
    layout = run(building=building)
    assert rules(layout) == ["cheme.layout-level"]
    assert layout.findings[0].ids == ["H1007", "B-1"]


# -- layout-area-overlap, duplicates ------------------------------------------------------------


def test_area_overlap():
    site = SITE.replace("[48, 18, 58, 30]", "[48, 18, 58, 32]")
    layout = run(site=site)
    assert rules(layout) == ["cheme.layout-area-overlap"]
    assert layout.findings[0].level == "warning"
    assert layout.findings[0].ids == ["A-300", "A-310"]


def test_road_areas_and_touching_areas_do_not_overlap():
    site = SITE.replace("areas:\n", "areas:\n  - {id: A-R, box: [9, 17, 47, 19], kind: road}\n")
    assert rules(run(site=site)) == []
    touching = SITE.replace("[48, 18, 58, 30]", "[48, 18, 58, 31]")
    assert rules(run(site=touching)) == []


def test_duplicates():
    layout = run(placement=PLACEMENT + "  - {tag: T4750, position: [53, 35, 0]}\n")
    assert rules(layout) == ["cheme.layout-duplicate"]


# -- the workspace -----------------------------------------------------------------------------


def write_layout(root: Path) -> None:
    (root / "layout" / "site-plan.yaml").write_text(SITE)
    (root / "layout" / "building.yaml").write_text(BUILDING)
    (root / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    (root / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)


def test_validate_workspace_runs_the_layout_rules(plant: Path):
    write_layout(plant)
    report = validate_workspace(Workspace(plant))
    found = [f.rule for f in report.findings if f.rule.startswith("cheme.layout")]
    assert found == ["cheme.layout-model-missing"]
    assert "layout" in report.compared["cross_checks"]
    assert {"site_plan", "building", "placement"} <= set(report.compared["lists"])
    assert "layout/site-plan.yaml" in report.files
    placement = plant / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[20, 24.5, 0]", "[17, 24.5, 0]"))
    report = validate_workspace(Workspace(plant))
    clash = [f for f in report.findings if f.rule == "cheme.layout-clash"]
    assert clash and clash[0].file == "layout/equipment-placement.yaml" and clash[0].line == 2
    assert report.failed()


def test_validate_only_a_layout_file_checks_its_schema(plant: Path):
    write_layout(plant)
    placement = plant / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[20, 24.5, 0]", "[17, 24.5, 0]"))
    report = validate_workspace(Workspace(plant), [placement])
    assert report.files == ["layout/equipment-placement.yaml"]
    assert report.findings == []
    assert "layout rules (only the files given)" in report.compared["skipped"]


def test_invalid_layout_file_skips_the_rules(plant: Path):
    write_layout(plant)
    (plant / "layout" / "building.yaml").write_text("buildings: 3\n")
    report = validate_workspace(Workspace(plant))
    assert [f.rule for f in report.findings if f.file.startswith("layout")] == ["yaml.schema"]
    assert "layout rules (a layout file is invalid)" in report.compared["skipped"]


def test_template_has_no_layout_files_and_a_skill(plant: Path):
    assert not (plant / "layout" / "site-plan.yaml").exists()
    assert (plant / "layout" / "README.md").read_text().count("cheme schema placement")
    skill = (plant / ".claude" / "skills" / "layout-yaml" / "SKILL.md").read_text()
    assert skill.startswith("---\nname: layout-yaml\n")
    report = validate_workspace(Workspace(plant))
    assert "layout" not in report.compared["cross_checks"]


def test_readme_example_is_valid():
    readme = (
        Path(__file__).parents[1] / "src/chemeascode/templates/project/layout/README.md"
    ).read_text()
    block = readme.split("```yaml\n", 1)[1].split("```", 1)[0]
    files: dict[str, list[str]] = {}
    current = None
    for line in block.splitlines():
        if line.startswith(("# layout/", "# equipment/")):
            current = line[2:].split(" ", 1)[0]
            files[current] = []
        elif current and line.startswith("# "):
            files[current].append(line[2:])
    texts = {
        kind: (name, "\n".join(files[name]))
        for kind, name in (
            ("site_plan", "layout/site-plan.yaml"),
            ("building", "layout/building.yaml"),
            ("placement", "layout/equipment-placement.yaml"),
        )
    }
    listed = "equipment:\n" + "\n".join(files["equipment/equipment-list.yaml"])
    equipment = EquipmentList.model_validate(yaml.safe_load(listed))
    assert all(item.dimensions for item in equipment.equipment)
    layout = check_layout(texts, equipment)
    assert layout.ruled and layout.findings == []


# -- the API -----------------------------------------------------------------------------------


@pytest.fixture
def api_plant(plant: Path) -> Path:
    write_layout(plant)
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "layout")
    return plant


def client(root: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    return TestClient(create_app(root, None, allowed_hosts=["testserver"]))


def test_api_layout_shape(api_plant: Path):
    api = client(api_plant)
    assert api.get("/api/repo").json()["has_layout"] is True
    data = api.get("/api/layout").json()
    assert set(data) >= {"site", "areas", "roads", "racks", "buildings", "equipment", "findings"}
    assert data["site"] == {"name": "Plot", "width": 60.0, "depth": 40.0}
    assert [a["id"] for a in data["areas"]] == ["A-100", "A-300", "A-310"]
    assert data["roads"][0]["points"] == [[0, 13], [60, 13]]
    assert data["racks"][0]["levels"] == [5, 7]
    building = data["buildings"][0]
    assert building["footprint"] == [26, 26, 40, 36]
    assert [lv["id"] for lv in building["levels"]] == ["GF", "PF"]
    by_tag = {e["tag"]: e for e in data["equipment"]}
    assert set(by_tag) == {"P4711", "P4712", "H1007", "H1008", "T4750"}
    h1008 = by_tag["H1008"]
    assert h1008["type"] == "TubularHeatExchanger" and h1008["sheet"] == "P-01"
    assert h1008["sheet_file"] == "pid/P-01.xml"
    assert h1008["shape"] == "horizontal_cylinder" and h1008["size"] == [5, 0.8, 0.8]
    assert h1008["position"] == [34, 31, 5] and h1008["building"] == "B-1"
    assert h1008["level"] == "PF" and h1008["clash"] is False
    assert by_tag["T4750"]["bbox"] == [50, 21, 0, 56, 27, 7]
    assert data["findings"] == []


def test_api_layout_at_a_revision_and_clashes(api_plant: Path):
    first = git(api_plant, "rev-parse", "HEAD").strip()
    placement = api_plant / "layout" / "equipment-placement.yaml"
    placement.write_text(PLACEMENT.replace("[20, 24.5, 0]", "[17, 24.5, 0]"))
    api = client(api_plant)
    now = api.get("/api/layout").json()
    assert [f["rule"] for f in now["findings"]] == ["cheme.layout-clash"]
    assert {e["tag"] for e in now["equipment"] if e["clash"]} == {"P4711", "P4712"}
    then = api.get("/api/layout", params={"rev": first}).json()
    assert then["findings"] == [] and then["rev"] == first
    assert api.get("/api/layout", params={"rev": "nosuchrev"}).status_code == 404
    assert api.get("/api/layout", params={"rev": "--all"}).status_code == 400


def test_api_layout_404_without_layout_files(plant: Path):
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "empty")
    first = git(plant, "rev-parse", "HEAD").strip()
    api = client(plant)
    assert api.get("/api/repo").json()["has_layout"] is False
    response = api.get("/api/layout")
    assert response.status_code == 404 and "error" in response.json()
    write_layout(plant)
    assert api.get("/api/layout").status_code == 200
    assert api.get("/api/repo").json()["has_layout"] is True
    assert api.get("/api/repo", params={"rev": first}).json()["has_layout"] is False
    assert api.get("/api/layout", params={"rev": first}).status_code == 404


def test_api_layout_invalid_file_reports_findings(api_plant: Path):
    (api_plant / "layout" / "building.yaml").write_text("buildings: [{id: B-1}]\n")
    data = client(api_plant).get("/api/layout").json()
    assert data["buildings"] == [] and data["equipment"]
    assert {f["rule"] for f in data["findings"]} == {"yaml.schema"}
    assert all(f["file"] == "layout/building.yaml" for f in data["findings"])


def test_api_layout_refuses_a_symlink_out_of_the_repository(plant: Path, tmp_path: Path):
    outside = tmp_path / "secret.yaml"
    outside.write_text(SITE)
    os.symlink(outside, plant / "layout" / "site-plan.yaml")
    api = client(plant)
    assert api.get("/api/repo").json()["has_layout"] is False
    response = api.get("/api/layout")
    assert response.status_code == 400 and "outside the repository" in response.json()["error"]
    report = validate_workspace(Workspace(plant))
    assert "layout/site-plan.yaml" not in report.files


def test_api_yaml_knows_the_layout_kinds(api_plant: Path):
    data = client(api_plant).get("/api/yaml", params={"path": "layout/building.yaml"}).json()
    assert data["kind"] == "building" and "Building" in data["schema"]["$defs"]


# -- regressions from the review -----------------------------------------------------------------

L_ROAD = SITE.replace(
    "roads:\n  - {id: R-1, points: [[0, 13], [60, 13]], width: 6}\n",
    "roads:\n  - {id: R-1, points: [[0, 13], [60, 13]], width: 6}\n"
    "  - {id: R-2, points: [[2, 2], [8, 2], [8, 8]], width: 2}\n",
)


def test_a_bent_road_covers_the_outside_of_its_corner():
    # R-2 bends at (8, 2); the corner square x 8..9, y 1..2 is on the road.
    corner = place("{tag: V1, position: [8.6, 1.5, 0], size: [0.6, 0.6, 1]}")
    layout = run(site=L_ROAD, placement=corner, equipment=listed("V1"))
    assert rules(layout) == ["cheme.layout-clash"] and layout.findings[0].ids == ["V1", "R-2"]
    # The polyline's own ends are not lengthened: just past the end at (2, 2) is off the road.
    past_end = place("{tag: V1, position: [1.5, 2, 0], size: [0.8, 0.8, 1]}")
    assert rules(run(site=L_ROAD, placement=past_end, equipment=listed("V1"))) == []
    polygons = strip([(10, 50), (50, 50), (50, 90)], 6)
    assert polygons_overlap(polygons[0], [(51, 48), (52, 48), (52, 49), (51, 49)])


def test_a_bent_road_corner_outside_the_site():
    site = SITE.replace(
        "roads:\n", "roads:\n  - {id: R-2, points: [[1, 30], [1, 39.5], [10, 39.5]], width: 1}\n"
    )
    layout = run(site=site)
    assert rules(layout) == []  # the corner reaches y 40 at most, the site edge
    site = site.replace("[1, 39.5], [10, 39.5]", "[1, 39.6], [10, 39.6]")
    layout = run(site=site)
    assert rules(layout) == ["cheme.layout-outside-site"] and layout.findings[0].ids == ["R-2"]


def test_turning_a_round_shape_does_not_grow_its_box():
    for shape, size in (
        ("vertical_cylinder", "{diameter: 2, height: 2}"),
        ("sphere", "{diameter: 2}"),
    ):
        placement = place(
            f"{{tag: V1, position: [10, 30, 0], shape: {shape}, size: {size}, rotation_deg: 45}}",
            f"{{tag: V2, position: [12.5, 30, 0], shape: {shape}, size: {size}, rotation_deg: 45}}",
        )
        layout = run(placement=placement, equipment=listed("V1", "V2"))
        assert rules(layout) == [], shape
    turned = Placement.model_validate(
        {
            "tag": "V",
            "position": [0, 0, 0],
            "shape": "horizontal_cylinder",
            "size": {"diameter": 1, "length": 4},
            "rotation_deg": 90,
        }
    )
    assert equipment_box(turned) == pytest.approx((-0.5, -2, 0, 0.5, 2, 1))


def test_a_level_without_height_is_not_infinitely_tall():
    building = BUILDING.replace(
        "      - {id: GF, elevation: 0, height: 5}\n      - {id: PF, elevation: 5, height: 4, "
        "kind: platform}\n",
        "      - {id: GF, elevation: 0}\n",
    )
    high_above = "equipment:\n  - {tag: V1, position: [38, 34, 20], size: [1, 1, 1]}\n"
    assert rules(run(building=building, placement=high_above, equipment=None)) == []
    inside = high_above.replace("[38, 34, 20]", "[38, 34, 3]")
    layout = run(building=building, placement=inside, equipment=None)
    assert rules(layout) == ["cheme.layout-clash"]  # a top floor is 4 m by default


def test_level_heights_fill_up_to_the_next_level_and_default():
    building = Building.model_validate(
        {
            "id": "B",
            "origin": [0, 0],
            "width": 5,
            "depth": 5,
            "levels": [
                {"id": "RF", "elevation": 8, "kind": "roof"},
                {"id": "GF", "elevation": 0},
                {"id": "PF", "elevation": 4.5, "kind": "platform", "height": 2},
            ],
        }
    )
    heights = [(level.id, height, known) for level, height, known in level_heights(building)]
    assert heights == [("GF", 4.5, True), ("PF", 2, True), ("RF", 0.3, False)]
    assert building_heights(building) == (0, 8.3)
    bare = Building.model_validate({"id": "B", "origin": [0, 0], "width": 5, "depth": 5})
    assert building_heights(bare) == (0, 6)


@pytest.mark.parametrize(
    "text",
    [
        "site: {width: .inf, depth: 40}\n",
        "site: {width: 60, depth: .nan}\n",
        "site: {width: 60, depth: 40}\nareas: [{id: '', box: [0, 0, 1, 1]}]\n",
        "site: {width: 60, depth: 40}\nroads: [{id: ' ', points: [[0, 0], [1, 1]], width: 1}]\n",
    ],
)
def test_site_plan_refuses_infinite_numbers_and_empty_ids(text):
    assert rules(run(site=text)) == ["yaml.schema"]


@pytest.mark.parametrize(
    "line",
    [
        "{tag: V1, position: [.nan, 30, 0], size: [1, 1, 1]}",
        "{tag: V1, position: [5, 30, 0], size: [1, .inf, 1]}",
        "{tag: '', position: [5, 30, 0], size: [1, 1, 1]}",
        "{tag: V1, position: [5, 30, 0], size: [1, 1, 1], mount: {building: ''}}",
        "{tag: V1, position: [5, 30, 0], shape: vertical_cylinder, size: [3, 8, 5]}",
        "{tag: V1, position: [5, 30, 0], shape: sphere, size: [2, 2, 2]}",
        "{tag: V1, position: [5, 30, 0], shape: horizontal_cylinder, size: [5, 1, 1]}",
    ],
)
def test_placement_refuses_bad_numbers_empty_ids_and_lists_for_round_shapes(line):
    layout = run(placement=place(line), equipment=listed("V1"))
    assert set(rules(layout)) == {"yaml.schema"}, layout.findings


def test_building_level_elevation_must_be_finite():
    building = BUILDING.replace("{id: GF, elevation: 0, height: 5}", "{id: GF, elevation: .inf}")
    assert rules(run(building=building)) == ["yaml.schema"]


def test_buildings_against_roads_racks_and_each_other():
    on_road = BUILDING.replace("origin: [26, 26]", "origin: [20, 9]")
    layout = run(building=on_road, placement=None)
    found = {(f.rule, tuple(f.ids)) for f in layout.findings}
    assert ("cheme.layout-clash", ("B-1", "R-1")) in found
    assert ("cheme.layout-clash", ("B-1", "PR-1")) in found  # PR-1 at y 18..22 runs through
    assert all(f.file == "layout/building.yaml" and f.line == 2 for f in layout.findings)
    assert ("building", "B-1") in layout.clash_refs and ("road", "R-1") in layout.clash_refs
    two = BUILDING + (
        "  - {id: B-2, origin: [38, 30], width: 6, depth: 4, levels: [{id: GF, elevation: 0}]}\n"
    )
    layout = run(building=two, placement=None)
    assert [(f.rule, f.ids) for f in layout.findings] == [("cheme.layout-clash", ["B-1", "B-2"])]
    touching = two.replace("origin: [38, 30]", "origin: [40, 30]")
    assert rules(run(building=touching, placement=None)) == []


def test_a_rack_above_a_building_is_fine():
    site = SITE.replace(
        "[[10, 20], [46, 20]], width: 4, levels: [5, 7]",
        "[[10, 31], [46, 31]], width: 4, levels: [10, 12]",
    )
    assert rules(run(site=site, placement=None)) == []  # B-1 is up to 9 m, the lowest tier at 10
    low = site.replace("levels: [10, 12]", "levels: [9.2, 12]")
    assert rules(run(site=low, placement=None)) == ["cheme.layout-clash"]


def test_pumps_under_a_rack_with_headroom():
    pump = place("{tag: V1, position: [16, 20, 0], size: [2, 0.8, 1]}")
    assert rules(run(placement=pump, equipment=listed("V1"))) == []
    on_tier = place("{tag: V1, position: [16, 20, 7], size: [1, 1, 0.3]}")
    assert rules(run(placement=on_tier, equipment=listed("V1"))) == ["cheme.layout-clash"]
    site = SITE.replace(", levels: [5, 7]", "")
    no_tiers = run(site=site, placement=pump, equipment=listed("V1"))
    assert rules(no_tiers) == ["cheme.layout-clash"]  # without tiers the whole height counts


def test_items_on_a_level_stay_below_the_level_above():
    tall = place(
        "{tag: V1, position: [38, 34, 0], size: [1, 1, 7], mount: {building: B-1, level: GF}}"
    )
    layout = run(placement=tall, equipment=listed("V1"))
    found = [(f.rule, f.level) for f in layout.findings if f.rule != FALLBACK]
    assert found == [("cheme.layout-level", "warning")]
    assert "above the 5 m clear height of level GF" in layout.findings[0].message
    fits = place(
        "{tag: V1, position: [38, 34, 0], size: [1, 1, 5], mount: {building: B-1, level: GF}}"
    )
    assert rules(run(placement=fits, equipment=listed("V1"))) == []


def test_building_without_level_is_a_warning():
    housed = place("{tag: V1, position: [38, 34, 0], size: [1, 1, 1], mount: {building: B-1}}")
    layout = run(placement=housed, equipment=listed("V1"))
    found = [(f.rule, f.level) for f in layout.findings if f.rule != FALLBACK]
    assert found == [("cheme.layout-level", "warning")]


def test_api_layout_skips_one_unreadable_file(plant: Path, tmp_path: Path):
    write_layout(plant)
    outside = tmp_path / "secret.yaml"
    outside.write_text(BUILDING)
    (plant / "layout" / "building.yaml").unlink()
    os.symlink(outside, plant / "layout" / "building.yaml")
    api = client(plant)
    assert api.get("/api/repo").json()["has_layout"] is True
    response = api.get("/api/layout")
    assert response.status_code == 200
    data = response.json()
    assert data["buildings"] == [] and len(data["equipment"]) == 5 and data["site"]
    found = [(f["file"], f["rule"]) for f in data["findings"]]
    assert found == [("layout/building.yaml", "cheme.layout-unreadable")]
    assert "outside the repository" in data["findings"][0]["message"]
    assert "grid_x" not in response.text  # nothing of the outside file is served


def test_api_layout_clash_flags_per_kind_and_level_heights(api_plant: Path):
    (api_plant / "layout" / "building.yaml").write_text(BUILDING.replace("[26, 26]", "[20, 9]"))
    data = client(api_plant).get("/api/layout").json()
    building = data["buildings"][0]
    assert building["clash"] is True and building["heights"] == [0, 9]
    assert [lv["clear_height"] for lv in building["levels"]] == [5, 4]
    assert [r["clash"] for r in data["roads"]] == [True]
    assert [r["clash"] for r in data["racks"]] == [True]
    assert not any(a["clash"] for a in data["areas"])


# -- sizes from the equipment list, on:, nozzle overrides ------------------------------------


def test_sizes_come_from_the_equipment_list():
    layout = run()
    sizes = {
        p.tag: r.body.extent
        for p, r in zip(layout.placement.equipment, layout.resolved, strict=True)
    }
    assert sizes["T4750"] == (6, 6, 7) and sizes["H1008"] == (5, 0.8, 0.8)
    assert sizes["P4711"] == (2.0, 0.8, 1.0)
    families = [r.body.family for r in layout.resolved]
    assert families == ["pump", "pump", "plate_exchanger", "shell_tube", "tank"]
    assert {r.size_from for r in layout.resolved} == {"list"}
    sized = run(placement=SIZED, equipment=BARE)
    assert [b.body.bbox() for b in sized.resolved] == [b.body.bbox() for b in layout.resolved]
    (note,) = [f for f in sized.findings if f.rule == FALLBACK]
    assert note.level == "info" and note.line == 2 and len(note.ids) == 5
    assert "5 items take their size from the placement" in note.message


def test_size_next_to_dimensions_is_ignored_and_no_size_at_all_is_assumed():
    both = run(placement=SIZED)
    assert rules(both) == ["cheme.layout-size-ignored"] * 5
    assert both.findings[0].line == 2
    neither = run(equipment=BARE)
    missing = [f for f in neither.findings if f.rule == "cheme.layout-size-missing"]
    assert len(missing) == 5 and missing[0].level == "warning"
    assert "assumed size of a pump [1.8, 0.8, 1]" in missing[0].message


def test_on_a_building_or_a_structure():
    item = Placement.model_validate(
        {"tag": "V1", "position": [0, 0, 0], "mount": {"building": "B-1", "level": "GF"}}
    )
    assert item.building == "B-1" and item.level == "GF" and item.mount.owner == "B-1"
    with pytest.raises(ValueError, match="a building or a structure"):
        Placement.model_validate(
            {"tag": "V1", "position": [0, 0, 0], "mount": {"building": "B", "structure": "S"}}
        )
    layout = run(
        placement=place("{tag: V1, position: [5, 30, 3], mount: {structure: S-1, level: L1}}"),
        equipment=listed("V1"),
    )
    (note,) = [f for f in layout.findings if f.rule == "cheme.layout-level"]
    assert note.level == "error" and "not in layout/structures.yaml" in note.message


def test_nozzle_overrides_schema_and_unknown_nozzles():
    good = (
        "{tag: V1, position: [5, 30, 0], nozzles: [{id: N1, angle_deg: 90, elevation: 2},"
        " {id: N2, face: top, offset: [0.5, 0]}, {id: N3, along: 1}]}"
    )
    layout = run(placement=place(good), equipment=listed("V1"))
    assert "yaml.schema" not in rules(layout)
    for bad, message in (
        ("[{id: N1}]", "give angle_deg/elevation, along or a face"),
        ("[{id: N1, face: top, angle_deg: 3}]", "not both"),
        ("[{id: N1, angle_deg: 3, offset: [1, 1]}]", "offset goes with a face"),
        ("[{id: N1, face: up}]", "Input should be"),
        ("[{id: N1, face: top}, {id: N1, face: bottom}]", "given twice"),
    ):
        entry = f"{{tag: V1, position: [5, 30, 0], nozzles: {bad}}}"
        found = run(placement=place(entry), equipment=listed("V1")).findings
        assert any(f.rule == "yaml.schema" and message in f.message for f in found), (bad, found)
    texts = {"placement": ("layout/equipment-placement.yaml", place(good))}
    equipment = EquipmentList.model_validate(yaml.safe_load(listed("V1")))
    checked = check_layout(texts, equipment, nozzles={"V1": {"N1", "N2"}})
    (unknown,) = [f for f in checked.findings if f.rule == "cheme.layout-nozzle-unknown"]
    assert unknown.level == "error" and "no nozzle N3" in unknown.message
    assert unknown.line == 9 and "N1, N2" in unknown.hint


def test_the_old_on_key_is_refused_with_a_hint():
    data = yaml.safe_load("equipment:\n  - {tag: V1, position: [0, 0, 0], on: {building: B}}\n")
    assert True in data["equipment"][0]  # what PyYAML makes of it
    with pytest.raises(ValueError, match="on: is now mount:"):
        PlacementList.model_validate(data)
    data = yaml.safe_load("equipment:\n  - {tag: V1, position: [0, 0, 0], mount: {building: B}}\n")
    assert PlacementList.model_validate(data).equipment[0].building == "B"
