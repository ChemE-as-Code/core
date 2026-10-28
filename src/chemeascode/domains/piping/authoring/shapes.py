"""Equipment and fitting symbols cheme-as-code adds to the reference shape catalogue.

The DEXPI 2.0.1 reference P&ID has 25 shapes: pumps, one vessel, two exchangers, valves,
fittings, arrows and bubbles. Plants also need compressors, turbines, columns, filters,
separators, coolers, tanks and more valves; without them agents invent symbols (with invented
registration numbers). ``scripts/build_snippets.py`` appends the shapes defined here to the
template's ``empty-sheet.xml`` and lists them in ``shapes.md``; ``cheme fragment`` prints one for
a sheet that lacks it (``fragment shape NAME``, or the SHAPE part of an equipment/valve fragment).

Most are the ISO 10628-2 symbols of :mod:`chemeascode.domains.process.symbols`, with their
ISO 10628-2 registration number (``ISO10628:2012-<number>-A``). A few markers and symbols not in
the library are drawn here, in the style of ISO 10628-2; their ISO number is not checked, so their
registration number is the shape's name, as the reference does for its own shapes without a number
(``CONTROLLED_ACTUATOR_SHAPE``). All are at scale 1 in sheet millimetres around (0, 0), Y down,
with the reference's stroke colours (equipment dark red, piping olive).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    _data,
    color,
    comps,
    double,
    enum,
    obj,
    point,
    points,
    string,
)
from chemeascode.domains.process.symbols import Port, Symbol, symbols

EQUIPMENT_RGB = (128, 0, 0)
PIPE_RGB = (128, 128, 0)


def _stroke(rgb: tuple[int, int, int], width: float, dash: str = "Solid") -> etree._Element:
    value = etree.Element("AggregatedDataValue", type="Core/Diagram.Stroke")
    value.extend(
        [
            color("Color", *rgb),
            enum("DashStyle", f"Core/Diagram.DashStyle.{dash}"),
            double("Width", width),
        ]
    )
    return _data("Stroke", value)


class _Pen:
    """Collects the primitives of one shape, numbering their ids."""

    def __init__(self, shape_id: str, rgb: tuple[int, int, int] = EQUIPMENT_RGB):
        self.shape_id = shape_id
        self.rgb = rgb
        self.items: list[etree._Element] = []

    def _id(self) -> str:
        return f"{self.shape_id}_Primitives{len(self.items) + 1}"

    def line(self, *xy: tuple[float, float], width: float = 0.3, dash: str = "Solid") -> None:
        self.items.append(
            obj(
                self._id(),
                "Core/Diagram.PolyLine",
                points("Points", list(xy)),
                _stroke(self.rgb, width, dash),
            )
        )

    def closed(self, *xy: tuple[float, float], width: float = 0.3) -> None:
        self.line(*xy, xy[0], width=width)

    def rect(self, x0: float, y0: float, x1: float, y1: float, width: float = 0.3) -> None:
        self.closed((x0, y0), (x1, y0), (x1, y1), (x0, y1), width=width)

    def ellipse(
        self,
        cx: float,
        cy: float,
        rx: float,
        ry: float | None = None,
        rotation: float = 0.0,
        width: float = 0.3,
        dash: str = "Solid",
    ) -> None:
        self.items.append(
            obj(
                self._id(),
                "Core/Diagram.Ellipse",
                point("Center", cx, cy),
                enum("FillStyle", "Core/Diagram.FillStyle.Transparent"),
                double("HorizontalSemiAxis", rx),
                double("Rotation", rotation),
                _stroke(self.rgb, width, dash),
                double("VerticalSemiAxis", ry if ry is not None else rx),
            )
        )


# -- the symbols drawn here ------------------------------------------------------------------------


def _axial_compressor(p: _Pen) -> None:
    p.closed((-10, -7.5), (10, -3.75), (10, 3.75), (-10, 7.5))
    for x in (-4.0, 2.0):
        y = 7.5 - (x + 10) * 3.75 / 20
        p.line((x, -y), (x, y), width=0.2)


def _packed_bed(p: _Pen) -> None:
    # 20 x 20 at scale 1; ScaleY sets the bed height (ScaleX 1 on a scale-1 column).
    p.line((-10, -10), (10, -10), width=0.2)
    p.line((-10, 10), (10, 10), width=0.2)
    p.line((-10, -10), (10, 10), width=0.2)
    p.line((-10, 10), (10, -10), width=0.2)


def _tray(p: _Pen) -> None:
    # One tray across a 20 mm column, the downcomer gap on the right.
    p.line((-10, 0), (6, 0), width=0.2)
    p.line((6, 0), (6, 3), width=0.2)


def _silencer(p: _Pen) -> None:
    # Inline: ends at x = -6 and 6 (scale 1), flow left to right.
    p.rect(-6, -4, 6, 4)
    p.line((-4.5, 0), (-3, -2.5), (-1, 2.5), (1, -2.5), (3, 2.5), (4.5, 0), width=0.2)


def _ambient_vaporizer(p: _Pen) -> None:
    p.rect(-8, -12.5, 8, 12.5)
    for x in (-4.0, 0.0, 4.0):
        p.line((x, -10.5), (x, 10.5), width=0.2)
    p.line((-8, -10.5), (8, -10.5), width=0.2)
    p.line((-8, 10.5), (8, 10.5), width=0.2)


def _plate_fin(p: _Pen) -> None:
    p.rect(-8, -15, 8, 15)
    for y in (-10.0, -5.0, 0.0, 5.0, 10.0):
        p.line((-8, y), (8, y), width=0.15)


def _library(symbol: Symbol) -> Callable[[_Pen], None]:
    """Draws *symbol*'s primitives."""

    def draw(p: _Pen) -> None:
        for item in symbol.primitives:
            if "line" in item:
                p.line(*(tuple(xy) for xy in item["line"]), width=item["width"], dash=item["dash"])
            else:
                p.ellipse(
                    *item["ellipse"],
                    item["rx"],
                    item["ry"],
                    rotation=item["rotation"],
                    width=item["width"],
                    dash=item["dash"],
                )

    return draw


@dataclass(frozen=True)
class ShapeDef:
    """One added symbol: its catalogue name and id, what it means, how big to draw it."""

    name: str
    shape_id: str
    meaning: str
    #: ScaleX/ScaleY to draw it at on an A3 sheet.
    scale: str
    draw: Callable[[_Pen], None]
    #: ISO 10628-2:2012 registration number (None: a symbol drawn here, named by its name).
    iso: str | None = None
    rgb: tuple[int, int, int] = EQUIPMENT_RGB
    #: Classes it is the default symbol for in ``fragment equipment``.
    classes: tuple[str, ...] = field(default_factory=tuple)
    #: Connection points at scale 1 (library symbols).
    ports: tuple[Port, ...] = ()
    #: In the template's ``empty-sheet.xml``; the others are added to a sheet on first use.
    template: bool = True

    @property
    def registration(self) -> str:
        return f"ISO10628:2012-{self.iso}-A" if self.iso else self.name

    def element(self, shape_id: str | None = None) -> etree._Element:
        shape_id = shape_id or self.shape_id
        pen = _Pen(shape_id, self.rgb)
        self.draw(pen)
        return obj(
            shape_id,
            "Core/Diagram.Shape",
            comps("Primitives", *pen.items),
            string("Name", self.name),
            string("SymbolRegistrationNumber", self.registration),
        )


def _shape_id(name: str) -> str:
    """``GATE_VALVE_SHAPE`` -> ``Shape_GateValve``."""
    return "Shape_" + "".join(part.capitalize() for part in name.removesuffix("_SHAPE").split("_"))


LIBRARY_SHAPES: tuple[ShapeDef, ...] = tuple(
    ShapeDef(
        s.name,
        _shape_id(s.name),
        s.meaning,
        s.scale,
        _library(s),
        iso=s.iso,
        rgb=PIPE_RGB if s.inline else EQUIPMENT_RGB,
        classes=s.classes,
        ports=s.ports,
        template=s.template,
    )
    for s in symbols().values()
)

DRAWN_SHAPES: tuple[ShapeDef, ...] = (
    ShapeDef(
        "AXIAL_COMPRESSOR_SHAPE",
        "Shape_AxialCompressor",
        "compressor, axial: wide inlet left, narrow outlet right",
        "1.0 (20 x 15 mm)",
        _axial_compressor,
        classes=("AxialCompressor",),
    ),
    ShapeDef(
        "COLUMN_PACKED_BED_SHAPE",
        "Shape_ColumnPackedBed",
        "packed bed (or adsorbent bed) marker inside a column or vessel: crossed box 20 x 20 mm",
        "ScaleX = column ScaleX, ScaleY = bed height / 20",
        _packed_bed,
    ),
    ShapeDef(
        "COLUMN_TRAY_SHAPE",
        "Shape_ColumnTray",
        "one tray inside a column (downcomer on the right); draw one per tray shown",
        "ScaleX = column ScaleX, ScaleY 1.0; IsMirrored for the downcomer on the left",
        _tray,
    ),
    ShapeDef(
        "SILENCER_SHAPE",
        "Shape_Silencer",
        "silencer (Plant/Piping.Silencer, an inline fitting): ends at x = -6 and 6",
        "0.5 inline (ends 3 mm from the centre: fragment valve --class Silencer)",
        _silencer,
        rgb=PIPE_RGB,
    ),
    ShapeDef(
        "AMBIENT_VAPORIZER_SHAPE",
        "Shape_AmbientVaporizer",
        "ambient-air vaporizer (finned tubes), class HeatExchanger or AirCoolingSystem",
        "1.0 (16 x 25 mm)",
        _ambient_vaporizer,
    ),
    ShapeDef(
        "PLATE_FIN_HEAT_EXCHANGER_SHAPE",
        "Shape_PlateFinHeatExchanger",
        "plate-fin (brazed aluminium) heat exchanger, class PlateHeatExchanger",
        "1.0-3.0 (16 x 30 mm at 1.0)",
        _plate_fin,
    ),
)

ADDED_SHAPES: tuple[ShapeDef, ...] = LIBRARY_SHAPES + DRAWN_SHAPES

BY_NAME: dict[str, ShapeDef] = {s.name: s for s in ADDED_SHAPES}

#: Names of shapes earlier versions drew here -> the library symbol that replaced them. Sheets
#: that have the old shape keep it (each sheet carries its catalogue); new fragments get the new.
LEGACY_NAMES: dict[str, str] = {
    "CENTRIFUGAL_COMPRESSOR_SHAPE": "COMPRESSOR_CENTRIFUGAL_SHAPE",
    "HEAT_EXCHANGER_GENERAL_SHAPE": "HEAT_EXCHANGER_SHAPE",
    "SHELL_AND_TUBE_HEAT_EXCHANGER_SHAPE": "HEAT_EXCHANGER_FIXED_TUBES_SHAPE",
    "FLAT_BOTTOM_TANK_SHAPE": "TANK_CONE_ROOF_SHAPE",
}

#: Equipment class -> the reference catalogue's shape for it (names; ids from the sheet).
REFERENCE_EQUIPMENT_SHAPES: dict[str, str] = {
    "CentrifugalPump": "CENTRIFUGAL_PUMP_SHAPE",
    "ReciprocatingPump": "RECIPROCATING_PUMP_SHAPE",
    "Pump": "CENTRIFUGAL_PUMP_SHAPE",
    "Tank": "VESSEL_WITH_DISHED_HEADS_SHAPE",
    "Vessel": "VESSEL_WITH_DISHED_HEADS_SHAPE",
    "PressureVessel": "VESSEL_WITH_DISHED_HEADS_SHAPE",
    "PlateHeatExchanger": "PLATE_TYPE_HEAT_EXCHANGER_SHAPE",
    "TubularHeatExchanger": "FLOATING_HEAD_TUBE_BUNDLE_HEAT_EXCHANGER_SHAPE",
}

#: Equipment class -> default shape name for ``fragment equipment`` (override with --shape).
EQUIPMENT_SHAPES: dict[str, str] = {
    **{cls: s.name for s in ADDED_SHAPES if s.rgb == EQUIPMENT_RGB for cls in s.classes},
    **REFERENCE_EQUIPMENT_SHAPES,
}


def normalise_name(name: str) -> str:
    """``compressor`` / ``centrifugal-compressor`` / ``COMPRESSOR_CENTRIFUGAL_SHAPE`` -> name;
    a name of a replaced shape (:data:`LEGACY_NAMES`) -> its replacement."""
    key = name.strip().upper().replace("-", "_").replace(" ", "_")
    key = key if key.endswith("_SHAPE") else f"{key}_SHAPE"
    return LEGACY_NAMES.get(key, key)


def template_sheet_path():
    """The template's ``empty-sheet.xml`` (its catalogue holds the reference and added shapes)."""
    from importlib.resources import files

    return files("chemeascode.domains.piping") / "skills/dexpi-xml/snippets/empty-sheet.xml"


_CATALOGUE: dict[str, etree._Element] | None = None


def catalogue() -> dict[str, etree._Element]:
    """Shape name -> its Shape element: the template catalogue's (reference and added shapes),
    then every added shape the template leaves out (``template=False``)."""
    global _CATALOGUE
    if _CATALOGUE is None:
        root = etree.fromstring(template_sheet_path().read_bytes())
        found: dict[str, etree._Element] = {}
        for shape in root.iter("Object"):
            if shape.get("type") == "Core/Diagram.Shape":
                name = shape.findtext("Data[@property='Name']/String")
                if name:
                    found.setdefault(name, shape)
        for added in ADDED_SHAPES:
            found.setdefault(added.name, added.element())
        _CATALOGUE = found
    return _CATALOGUE
