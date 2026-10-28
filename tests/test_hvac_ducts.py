"""HVAC: ``layout/hvac.yaml`` (air handling units, ventilated rooms), the terminals and ducts of
the 3D model, their sizes against the velocity table, the rules ``hvac-capacity``,
``duct-unrouted`` and ``clash-duct``, validate's ``layout-hvac-ref``, the drawings and the gate
requirement ``hvac``."""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.spatial.drawing2d import render_plan, render_section
from chemeascode.domains.spatial.gates import layout_gate
from chemeascode.domains.spatial.hvac import Limits, hvac_findings, sizing_table, velocity
from chemeascode.domains.spatial.model import build_model, model_findings, write_model
from chemeascode.domains.spatial.schemas import Hvac, HvacRuleSet, LayoutModelFile
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace
from tests.conftest import DATA

SHEET = DATA / "layout_cabling.xml"

EQUIPMENT = """\
equipment:
  - {tag: V-101, type: PressureVessel, sheet: P-01, dimensions: {diameter: 2, height: 8}}
  - {tag: P-101, type: CentrifugalPump, sheet: P-01,
     dimensions: {length: 1.6, width: 0.7, height: 1.0}}
"""
LINES = """\
lines:
  - {number: 80-P-101, from: V-101, to: P-101, nominal_diameter: DN80, fluid: Water}
  - {number: 50-P-102, from: P-101, to: BL, nominal_diameter: DN50, fluid: Water}
"""
SITE = """\
site: {name: Test, width: 40, depth: 30}
areas:
  - {id: A1, box: [2, 2, 38, 28]}
racks:
  - {id: PR-1, points: [[5, 15], [35, 15]], width: 3, levels: [5]}
"""
PLACEMENT = """\
equipment:
  - {tag: V-101, position: [10, 10, 0]}
  - {tag: P-101, position: [14, 10, 0], rotation_deg: 90}
"""
BUILDING = """\
buildings:
  - id: H-1
    origin: [18, 2]
    width: 16
    depth: 10
    levels: [{id: GF, elevation: 0, height: 6}]
    walls: all
    openings:
      - {id: LV1, side: west, offset: 3, width: 2, height: 1.5, sill: 3, kind: louvre}
      - {id: LV2, side: east, offset: 3, width: 2, height: 1.5, sill: 3, kind: louvre}
      - {id: D1, side: south, offset: 8, width: 1.2, height: 2.2, kind: door}
"""
HVAC = """\
units:
  - {id: AHU-1, building: H-1, position: [21, 7], rotation_deg: 90, capacity_m3h: 8000,
     intake: LV1, exhaust: LV2}
rooms:
  - {id: HALL, building: H-1, unit: AHU-1, air_changes_per_h: 6,
     basis: "heat load of the machines (ASSUMED)"}
"""


@pytest.fixture
def vented(plant: Path) -> Path:
    shutil.copy(SHEET, plant / "pid" / "P-01.xml")
    (plant / "equipment" / "equipment-list.yaml").write_text(EQUIPMENT)
    (plant / "piping" / "line-list.yaml").write_text(LINES)
    (plant / "layout" / "site-plan.yaml").write_text(SITE)
    (plant / "layout" / "equipment-placement.yaml").write_text(PLACEMENT)
    (plant / "layout" / "building.yaml").write_text(BUILDING)
    (plant / "layout" / "hvac.yaml").write_text(HVAC)
    return plant


def _by_id(entries):
    return {e["id"]: e for e in entries}


# -- sizes ------------------------------------------------------------------------------------


def test_the_sizing_table_and_the_overrides():
    table = sizing_table()
    assert table["status"] == "ASSUMED"
    assert all(row["basis"] for row in table["velocities"].values())
    limits = Limits.of(HvacRuleSet())
    assert limits.velocities["main"] == 8.0 and limits.max_height == 1.0
    # 5760 m3/h at 8 m/s needs 0.2 m2: 500 x 400 is the smallest standard rectangle
    assert limits.size(5760, "main") == (0.5, 0.4)
    assert velocity(5760, 0.5, 0.4) == pytest.approx(8.0)
    # no rectangle is taller than max_height_mm, none wider than max_aspect x its height
    assert all(h <= 1.0 and w <= 4 * h + 1e-9 for w, h in limits.rectangles())
    # too much air: the largest, above the limit
    w, h = limits.size(200000, "main")
    assert (w, h) == (2.5, 1.0) and velocity(200000, w, h) > 8.0
    own = Limits.of(
        HvacRuleSet.model_validate(
            {"velocities": {"main": {"max_m_s": 5, "basis": "noise"}}, "max_height_mm": 400}
        )
    )
    assert own.velocities["main"] == 5 and own.bases["main"] == "noise"
    assert own.size(5760, "main") == (0.8, 0.4)
    with pytest.raises(ValueError):
        Hvac.model_validate({"rooms": [{"id": "R", "building": "B", "unit": "U"}]})
    with pytest.raises(ValueError):
        Hvac.model_validate(
            {
                "rooms": [
                    {"id": "R", "building": "B", "unit": "U", "flow_m3h": 1, "air_changes_per_h": 2}
                ]
            }
        )
    with pytest.raises(ValueError):
        HvacRuleSet.model_validate({"sides_mm": [400, 200]})


# -- the build --------------------------------------------------------------------------------


def test_the_build_ventilates_the_room(vented: Path):
    model = build_model(Workspace(vented))
    document = model.document
    LayoutModelFile.model_validate(document)
    (unit,) = document["hvac_units"]
    (room,) = document["hvac_rooms"]
    ducts = _by_id(document["ducts"])
    # 16 x 10 x 6 m at 6 air changes: 5760 m3/h in and out
    assert room["volume_m3"] == 960 and room["supply_m3h"] == 5760 == room["extract_m3h"]
    assert unit["supply_m3h"] == 5760 and unit["level"] == "GF" and unit["position"][2] == 0
    assert set(unit["ports"]) == {"outdoor", "exhaust", "return", "supply"}
    # three supply terminals of 2500 m3/h at most, on one row under the ceiling (the gap and
    # the envelope of the 500 x 400 main), and three extract terminals lower by both envelopes
    # and the spacing
    supply = [t for t in room["terminals"] if t["system"] == "supply"]
    extract = [t for t in room["terminals"] if t["system"] == "extract"]
    assert len(supply) == 3 == len(extract)
    assert {t["point"][2] for t in supply} == {6 - 0.3 - 0.25}
    assert {t["point"][2] for t in extract} == {4.8}
    assert all(t["flow_m3h"] == 1920 and t["source"] == "generated" for t in supply)
    assert {t["point"][1] for t in supply} == {4.5} and {t["point"][1] for t in extract} == {9.5}
    # the supply tree: a main from the port to the row, headers both ways, flows adding up
    main = ducts["SA-HALL-1-1"]
    assert main["kind"] == "main" and main["flow_m3h"] == 5760
    assert main["points"][0] == unit["ports"]["supply"]
    assert (main["width"], main["height"]) == (0.5, 0.4)
    headers = [d for d in document["ducts"] if d["system"] == "supply" and d["kind"] == "header"]
    assert sorted(d["flow_m3h"] for d in headers) == [1920, 1920, 3840]
    # the intake starts at the louvre on the west wall, the exhaust ends at the east one
    intake, exhaust = ducts["OA-AHU-1"], ducts["XA-AHU-1"]
    assert (
        intake["points"][0] == [18.0, 8.0, 3.75]
        and intake["points"][-1] == unit["ports"]["outdoor"]
    )
    assert exhaust["points"][-1] == [34.0, 6.0, 3.75]
    assert intake["flow_m3h"] == 5760 == exhaust["flow_m3h"]
    for duct in document["ducts"]:
        assert duct["method"].startswith("astar"), duct["id"]
        assert duct["velocity_m_s"] <= duct["velocity_max_m_s"] + 1e-9
        assert all(18 <= p[0] <= 34 and 2 <= p[1] <= 12 and 0 < p[2] < 6 for p in duct["points"])
        assert duct["parts"] and all(
            p["material"] == f"duct_{duct['system']}" for p in duct["parts"]
        )
    (louvre_in, louvre_out) = document["hvac"]["louvres"]
    assert louvre_in["opening"] == "LV1" and louvre_in["free_area_m2"] == 1.5
    assert louvre_in["velocity_m_s"] == pytest.approx(5760 / 3600 / 1.5, abs=1e-3)
    # recorded as an input, rebuilt byte-identical, and no HVAC finding
    assert "layout/hvac.yaml" in document["provenance"]["sources"]
    assert build_model(Workspace(vented)).text() == model.text()
    assert not [f for f in model.findings if "hvac" in f.rule or "duct" in f.rule]


def test_no_hvac_file_no_ducts(vented: Path):
    (vented / "layout" / "hvac.yaml").unlink()
    document = build_model(Workspace(vented)).document
    assert not {"hvac_units", "hvac_rooms", "ducts", "hvac"} & set(document)


def test_a_changed_hvac_file_outdates_the_model(vented: Path):
    workspace = Workspace(vented)
    write_model(workspace, build_model(workspace))
    assert model_findings(workspace) == []
    (vented / "layout" / "hvac.yaml").write_text(
        HVAC.replace("air_changes_per_h: 6", "air_changes_per_h: 4")
    )
    assert [f.rule for f in model_findings(workspace)] == ["cheme.layout-model-outdated"]


def test_declared_terminals_and_capacity_findings(vented: Path):
    (vented / "layout" / "hvac.yaml").write_text(
        """\
rules: {max_height_mm: 300}
units:
  - {id: AHU-1, building: H-1, position: [21, 7], rotation_deg: 90, capacity_m3h: 5000}
rooms:
  - {id: HALL, building: H-1, unit: AHU-1, air_changes_per_h: 12, extract_fraction: 0,
     supply: [[30, 4], [30, 10]]}
"""
    )
    model = build_model(Workspace(vented))
    document = model.document
    (room,) = document["hvac_rooms"]
    assert [t["point"][:2] for t in room["terminals"]] == [[30, 4], [30, 10]]
    assert all(t["source"] == "declared" for t in room["terminals"])
    assert not [d for d in document["ducts"] if d["system"] in ("extract", "exhaust")]
    found = {(f.rule, f.key) for f in model.findings}
    # 11520 m3/h in ducts at most 300 mm deep, a 5000 m3/h unit, no intake
    assert ("cheme.layout-hvac-capacity", "SA-HALL-1-1") in found
    assert ("cheme.layout-hvac-capacity", "AHU-1") in found
    missing = [f for f in model.findings if f.key.startswith("AHU-1:no intake")]
    assert missing and missing[0].level == "warning"


def test_validate_checks_the_hvac_references(vented: Path):
    (vented / "layout" / "hvac.yaml").write_text(
        """\
units:
  - {id: AHU-1, building: H-1, position: [21, 7], intake: LV9}
  - {id: AHU-2, building: H-9, position: [5, 5]}
  - {id: AHU-3, building: H-1, position: [50, 7]}
rooms:
  - {id: HALL, building: H-1, unit: AHU-2, air_changes_per_h: 6, supply: [[40, 4]]}
  - {id: R2, building: H-1, unit: AHU-7, flow_m3h: 100, extent: [18, 2, 40, 12]}
"""
    )
    report = validate_workspace(Workspace(vented))
    found = [f for f in report.findings if f.rule == "cheme.layout-hvac-ref"]
    assert all(f.file == "layout/hvac.yaml" and f.level == "error" for f in found)
    messages = " | ".join(f.message for f in found)
    for text in (
        "intake LV9 is not an opening of H-1",
        "building H-9",
        "AHU-3 at [50.0, 7.0] stands outside",
        "served by unit AHU-2 in H-9",
        "supply terminal [40.0, 4.0] lies outside",
        "unit AHU-7",
        "extent [18.0, 2.0, 40.0, 12.0] reaches outside",
    ):
        assert text in messages, text
    assert next(f for f in found if "LV9" in f.message).line == 2


def test_duct_clash_and_unrouted_rules():
    duct = {
        "id": "SA-R-1-1",
        "system": "supply",
        "kind": "main",
        "unit": "AHU-1",
        "room": "R",
        "points": [[0, 0, 5], [10, 0, 5]],
        "width": 0.5,
        "height": 0.4,
        "flow_m3h": 1000,
        "velocity_m_s": 1.4,
        "velocity_max_m_s": 8,
        "method": "direct",
        "reason": "found no clear way",
    }
    model = {
        "pipes": [
            {"id": "P-1", "od": 0.1, "points": [[5, -3, 5], [5, 3, 5]], "insulation_mm": 0},
        ],
        "ducts": [duct, {**duct, "id": "EA-R-1-1", "system": "extract", "method": "astar"}],
        "hvac": {"missing": [], "louvres": []},
    }
    found = {(f.rule, tuple(f.ids)) for f in hvac_findings(model)}
    assert ("cheme.layout-clash-duct", ("SA-R-1-1", "P-1")) in found
    assert ("cheme.layout-duct-unrouted", ("SA-R-1-1",)) in found
    # two systems' ducts in one place: one finding for the pair
    pair = [f for f in hvac_findings(model) if set(f.ids) == {"SA-R-1-1", "EA-R-1-1"}]
    assert len(pair) == 1
    assert hvac_findings({"pipes": []}) == []
    # a unit standing in an item
    model["equipment"] = [
        {
            "tag": "X",
            "parts": [
                {
                    "id": "X/body",
                    "kind": "box",
                    "material": "shell",
                    "centre": [20, 0, 1],
                    "size": [2, 2, 2],
                    "rotation_deg": 0,
                }
            ],
        }
    ]
    model["hvac_units"] = [
        {
            "id": "AHU-1",
            "supply_m3h": 0,
            "parts": [
                {
                    "id": "AHU-1/casing",
                    "kind": "box",
                    "material": "ahu",
                    "centre": [21, 0, 1],
                    "size": [3, 1, 2],
                    "rotation_deg": 0,
                }
            ],
        }
    ]
    found = {(f.rule, tuple(f.ids)) for f in hvac_findings(model)}
    assert ("cheme.layout-clash-duct", ("AHU-1", "X")) in found


# -- drawings and gates -----------------------------------------------------------------------


def test_drawings_show_units_ducts_and_terminals(vented: Path):
    document = build_model(Workspace(vented)).document
    plan = render_plan(document)
    assert 'id="ahu-AHU-1"' in plan and 'id="duct-SA-HALL-1-1"' in plan
    assert 'id="terminal-HALL/supply-1"' in plan and 'data-system="exhaust"' in plan
    section = render_section(document, "x", 26.0)
    assert 'id="duct-SA-HALL-1-H1"' in section and 'id="duct-EA-HALL-1-H1"' in section


def test_hvac_gate(vented: Path):
    from chemeascode.foundation.schemas.checks import Accept

    workspace = Workspace(vented)
    write_model(workspace, build_model(workspace))
    assert layout_gate(workspace, ["hvac"], validate_workspace(workspace).findings) == []
    # a clad building without layout/hvac.yaml
    hvac = (vented / "layout" / "hvac.yaml").read_text()
    (vented / "layout" / "hvac.yaml").unlink()
    write_model(workspace, build_model(workspace))
    (problem,) = layout_gate(workspace, ["hvac"], validate_workspace(workspace).findings)
    assert "H-1" in problem and "layout/hvac.yaml" in problem
    # a unit too small: named until accepted
    (vented / "layout" / "hvac.yaml").write_text(
        hvac.replace("capacity_m3h: 8000", "capacity_m3h: 4000")
    )
    write_model(workspace, build_model(workspace))
    findings = validate_workspace(workspace).findings
    (problem,) = layout_gate(workspace, ["hvac"], findings)
    assert "AHU-1" in problem
    accept = [
        Accept.model_validate(
            {"id": "layout/plant-model.yaml#layout-hvac-capacity:AHU-1", "reason": "vendor"}
        )
    ]
    assert layout_gate(workspace, ["hvac"], findings, accept=accept) == []


def test_the_template_gate_and_skill():
    from chemeascode.templates.install import bundled_skills

    template = Path(__file__).parents[1] / "src/chemeascode/templates/project"
    checks = yaml.safe_load((template / "checks/checks.yaml").read_text())
    (gate,) = [c for c in checks["checks"] if c["id"] == "hvac"]
    assert gate["stage"] == "detail" and set(gate["require"]) == {"model-current", "hvac"}
    skill = Path(str(bundled_skills()["hvac-ducts"])) / "SKILL.md"
    assert skill.parent.parent.parent.name == "spatial"
    assert "cheme schema hvac" in skill.read_text()
