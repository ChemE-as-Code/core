"""Structures and access found while applying the 3D layout to the ASU example: building
walls cut around openings, a branch rack's joint with the main rack, items declared without
platforms of their own."""

from __future__ import annotations

from chemeascode.domains.spatial.schemas import Access, Building, Rack
from chemeascode.domains.spatial.structures import building_walls, platforms_for, rack_steel


def test_a_branch_rack_has_no_bent_inside_the_main_rack():
    main = Rack.model_validate(
        {"id": "M", "points": [[0, 10], [60, 10]], "width": 6, "levels": [5]}
    )
    branch = Rack.model_validate(
        {"id": "B", "points": [[30, 10], [30, 40]], "width": 4, "levels": [6]}
    )
    alone = rack_steel(branch, 6.0)
    joined = rack_steel(branch, 6.0, [main])
    assert any(p["id"].startswith("B/bent-0/") for p in alone)
    assert not any(p["id"].startswith("B/bent-0/") for p in joined)
    assert len(joined) == len(alone) - 3  # two columns and one beam


def test_declared_access_without_platforms_declares_none():
    column = {
        "tag": "C-1",
        "family": "column",
        "shape": "vertical_cylinder",
        "position": [0, 0, 0],
        "rotation_deg": 0.0,
        "dimensions": {"diameter": 2.0, "height": 30.0},
        "bbox": [-1, -1, 0, 1, 1, 30],
        "nozzles": [
            {"id": "C-1/N1", "point": [1, 0, 20], "direction": [1, 0, 0], "refs": {}},
        ],
    }
    assert platforms_for(column, None, [], "layout/equipment-placement.yaml")  # proposed
    none = Access(platforms=[], notes="reached from the cold box steel")
    assert platforms_for(column, none, [], "layout/equipment-placement.yaml") == []


def test_building_walls_are_cut_around_openings():
    building = Building.model_validate(
        {
            "id": "B",
            "origin": [0, 0],
            "width": 10,
            "depth": 6,
            "levels": [{"id": "L0", "elevation": 0, "height": 5}],
            "walls": ["south"],
            "openings": [{"side": "south", "offset": 2, "width": 3, "height": 3, "sill": 1}],
        }
    )
    walls = building_walls(building, 5.0)
    # left of the opening, below it, above it and right of it
    assert len(walls) == 4 and all(w["id"].startswith("B/wall-south-") for w in walls)
