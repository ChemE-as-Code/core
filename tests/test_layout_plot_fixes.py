"""Plot plan fixes found while applying the 3D layout to the ASU example: show --layout
measures with the equipment list's sizes, an internal item without a placement of its own."""

from __future__ import annotations

from pathlib import Path

from chemeascode.domains.spatial.gates import layout_gate
from chemeascode.domains.spatial.layout_distances import show_layout
from chemeascode.domains.spatial.model import build_model, write_model
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace
from tests import test_layout_3d

plant3d = test_layout_3d.plant3d  # the fixture: a plant with a vessel, a pump and a rack


def test_show_layout_sizes_items_from_the_equipment_list(plant3d: Path):
    lines, found = show_layout(Workspace(plant3d), "V-101")
    assert found and "top 8 m" in lines[0]


def test_an_accepted_not_placed_item_counts_as_placed(plant3d: Path):
    placement = plant3d / "layout" / "equipment-placement.yaml"
    placement.write_text(placement.read_text().split("  - {tag: P-101")[0])
    ws = Workspace(plant3d)
    write_model(ws, build_model(ws))
    finding = Finding(
        "equipment/equipment-list.yaml",
        "info",
        "cheme.layout-not-placed",
        "P-101 has no placement",
        ids=["P-101"],
    )
    assert "not placed: P-101" in " ".join(layout_gate(ws, ["placed"], [finding]))
    accept = [{"id": finding.id, "reason": "internal of V-101"}]
    from chemeascode.foundation.schemas.checks import Accept

    entries = [Accept.model_validate(a) for a in accept]
    assert layout_gate(ws, ["placed"], [finding], accept=entries) == []
