"""The ISO 10628-2 symbol library: the P&ID catalogue shapes and the PFD step symbols (ADR 0022)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pydexpi.pydexpi_classes.pydexpi_classes as C
import pytest
from lxml import etree

from chemeascode.domains.piping.authoring.fragment import (
    INLINE_HALF,
    VALVE_HALF,
    VALVE_SCALE,
    VALVE_SHAPES,
)
from chemeascode.domains.piping.authoring.shapes import (
    ADDED_SHAPES,
    BY_NAME,
    EQUIPMENT_SHAPES,
    LEGACY_NAMES,
    catalogue,
    normalise_name,
    template_sheet_path,
)
from chemeascode.domains.process.sheets import build
from chemeascode.domains.process.symbols import (
    BOX,
    JUNCTION,
    STEP_SYMBOLS,
    step_drawing,
    step_symbol,
    symbols,
)
from chemeascode.foundation.workspace import Workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REFERENCE = Path(__file__).resolve().parent / "data/reference_pid.xml"


def _names(root: etree._Element) -> list[str]:
    return [
        s.findtext("Data[@property='Name']/String")
        for s in root.iter("Object")
        if s.get("type") == "Core/Diagram.Shape"
    ]


def test_library_symbols_have_geometry_an_iso_number_and_their_extent_at_the_origin():
    for symbol in symbols().values():
        assert symbol.primitives, symbol.name
        x0, y0, x1, y1 = symbol.extent()
        assert abs(x0 + x1) < 0.1 and abs(y0 + y1) < 0.1, symbol.name
        shape = BY_NAME[symbol.name]
        assert shape.registration == f"ISO10628:2012-{symbol.iso}-A"
        assert shape.element().findtext("Data[@property='SymbolRegistrationNumber']/String") == (
            shape.registration
        )


#: Registration numbers cross-checked in review against the DEXPI 2.0.1 reference P&ID and the
#: Wikimedia Commons symbol files drawn from EN ISO 10628-2:2012 (ADR 0022).
CHECKED_NUMBERS = {
    "PUMP_SHAPE": "2301",
    "PUMP_CENTRIFUGAL_SHAPE": "2322",
    "PUMP_RECIPROCATING_SHAPE": "X8094",  # the annotations' X8095 is the diaphragm pump's
    "PUMP_DIAPHRAGM_SHAPE": "X8095",
    "COMPRESSOR_CENTRIFUGAL_SHAPE": "X8179",
    "BLOWER_SHAPE": "X8164",
    "TURBINE_SHAPE": "2571",  # not the annotations' 2517
    "VESSEL_DISHED_ENDS_SHAPE": "2062",
    "TANK_CONE_ROOF_SHAPE": "X2063",
    "COLUMN_TRAYS_SHAPE": "X8101",
    "CHECK_VALVE_SHAPE": "X8077",
    "SAFETY_VALVE_SPRING_LOADED_SHAPE": "X2124",
    "RUPTURE_DISC_SHAPE": "X8080",
    "STEAM_TRAP_SHAPE": "2181",
    "SIGHT_GLASS_ILLUMINATED_SHAPE": "X8089",
}


def test_cross_checked_registration_numbers():
    assert {name: symbols()[name].iso for name in CHECKED_NUMBERS} == CHECKED_NUMBERS


def test_added_shape_names_and_ids_are_unique_and_never_a_reference_shape():
    reference = set(_names(etree.parse(str(REFERENCE)).getroot()))
    assert len({s.name for s in ADDED_SHAPES}) == len(ADDED_SHAPES)
    assert len({s.shape_id for s in ADDED_SHAPES}) == len(ADDED_SHAPES)
    assert not reference & {s.name for s in ADDED_SHAPES}


def test_the_template_holds_only_template_shapes_and_the_catalogue_every_shape():
    in_template = set(_names(etree.fromstring(template_sheet_path().read_bytes())))
    for shape in ADDED_SHAPES:
        assert (shape.name in in_template) == shape.template, shape.name
        assert shape.name in catalogue()


def test_replaced_shape_names_resolve_to_their_library_symbol():
    for old, new in LEGACY_NAMES.items():
        assert normalise_name(old) == new
        assert new in BY_NAME
    assert normalise_name("flat-bottom-tank") == "TANK_CONE_ROOF_SHAPE"
    assert normalise_name("gate valve") == "GATE_VALVE_SHAPE"


def test_default_classes_are_dexpi_classes():
    for cls in EQUIPMENT_SHAPES:
        assert issubclass(getattr(C, cls), C.ProcessEquipment), cls
    for cls in VALVE_SHAPES:
        assert issubclass(getattr(C, cls), C.PipingComponent), cls


def test_inline_library_symbols_end_where_the_valve_fragment_puts_the_pipe():
    for cls, (name, _) in VALVE_SHAPES.items():
        shape = BY_NAME.get(name)
        if shape is None or not shape.ports:
            continue
        inlet, outlet = shape.ports
        half = INLINE_HALF.get(cls, VALVE_HALF / VALVE_SCALE)
        assert [inlet.x, inlet.y, outlet.x, outlet.y] == pytest.approx(
            [-half, 0, half, 0], abs=0.02
        )


def test_step_symbols_follow_the_step_class_and_its_bases():
    assert all(name in (None, JUNCTION) or name in symbols() for name in STEP_SYMBOLS.values())
    assert all(getattr(C, cls, None) is not None for cls in STEP_SYMBOLS)
    assert step_symbol("Pumping").name == "PUMP_CENTRIFUGAL_SHAPE"
    assert step_symbol("StrippingDistilling").name == "COLUMN_TRAYS_SHAPE"
    # junctions (mixing and splitting tees) have no equipment symbol; a step's symbol: wins
    assert step_drawing("Mixing") == step_drawing("SplittingMaterial") == JUNCTION
    assert step_symbol("Mixing") is None
    assert step_drawing("Mixing", "TANK_CONE_ROOF_SHAPE").name == "TANK_CONE_ROOF_SHAPE"
    assert step_drawing("Cooling", BOX) is None
    assert step_drawing("Cooling", "NO_SUCH_SHAPE").name == "HEAT_EXCHANGER_SHAPE"
    assert step_symbol("Cooling").name == "HEAT_EXCHANGER_SHAPE"
    assert step_symbol("MixingSimple") is None
    assert step_symbol("ProcessStep") is None
    assert step_symbol("NoSuchStep") is None


def test_pfd_draws_a_mapped_step_with_its_symbol_and_a_junction_as_a_box(tmp_path):
    from pydexpi.loaders.public import load_xml_with_report

    shutil.copytree(EXAMPLES / "process-recycle", tmp_path / "plant")
    ws = Workspace(tmp_path / "plant")
    assert not build(ws, force=True).failed
    pfd = load_xml_with_report((ws.root / "process/PFD.xml").read_bytes()).model
    groups = {}
    todo = list(pfd.diagram[0].groups if isinstance(pfd.diagram, list) else pfd.diagram.groups)
    while todo:
        group = todo.pop()
        groups[group.id] = group
        todo += [g for g in getattr(group, "groups", None) or [] if g.id]
    column = groups["Drawing_C1_Symbol_Static"]  # C1: Distilling
    assert len(column.elements) == len(symbols()["COLUMN_TRAYS_SHAPE"].primitives)
    assert "Drawing_C1_Static" not in groups
    assert "Drawing_M1_Static" in groups  # M1: MixingSimple, a junction
