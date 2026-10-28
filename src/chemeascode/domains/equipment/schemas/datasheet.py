"""``equipment/datasheets/<TAG>.yaml``: the datasheet of one equipment-list item."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from chemeascode.foundation.schema_base import Identifier, Origin, Strict, optional_schema


class Quantity(Strict):
    """A value with its unit, marked when it is assumed rather than known. A field without a
    value yet holds ``TBD`` (with the reason in ``source``), ``supplier`` (waiting for the
    supplier's data, the source or reason saying what is awaited) or ``not_applicable`` (with a
    ``reason``); a sheet whose only open fields are ``supplier`` and ``not_applicable`` can be
    final (no ``draft``)."""

    value: float | str
    unit: str = ""
    assumed: bool = Field(default=False, description="True: an assumption, not data.")
    source: str = Field(default="", description="Where it comes from, e.g. DESIGN.md D-012.")
    reason: str = Field(
        default="",
        description="With value supplier: what is awaited from the supplier; with value "
        "not_applicable (required): why the field does not apply to this item.",
    )
    fingerprint: str | None = Field(
        default=None,
        description="Values cheme datasheets fill calculated: the fingerprint of their inputs "
        "(the streams at the item's linked nodes, and what inputs names); a mismatch is "
        "cheme.datasheet-stale.",
    )
    inputs: list[str] | None = Field(
        default=None,
        description="Values cheme datasheets fill calculated: the inputs besides the streams "
        "that the fingerprint covers, as catalyst:<id> (process/catalysts.yaml), pipe:<id> and "
        "nozzle:<TAG>/<N> (layout/plant-model.yaml), residence_time:<TAG> "
        "(process/design-basis.yaml), condenser:<step> (process/simulation.yaml), "
        "datasheet:<section>.<key> (this sheet), param:<name> (a declared parameter: "
        "type_specific, else the --param recorded in sizing_basis) and table:<table>/<row> (a "
        "row of a table cheme-as-code ships).",
    )
    origin: Origin | None = Field(
        default=None,
        description="What kind of figure it is (as on a process quantity), e.g. vendor; "
        "cheme datasheets fill writes correlation on the values it calculates from the "
        "streams, cheme datasheets draft carries the stream value's over.",
    )


#: A number or text, or a :class:`Quantity` with unit and ``assumed`` marking.
Value = float | str | Quantity


class Operating(BaseModel):
    """The operating conditions, each a value (``pressure_barg``, ``temperature_degc``,
    ``flow_kg_h``, ...), and the flowsheet case and streams they are for. ``cheme validate``
    resolves ``case`` and ``streams`` against ``process/flowsheet.yaml``
    (``cheme.contract-ref``)."""

    model_config = ConfigDict(extra="allow")
    __pydantic_extra__: dict[str, Value] = Field(init=False)

    case: Identifier | None = Field(
        default=None,
        description="The flowsheet case (cases[].id) the conditions are for; cheme datasheets "
        "fill writes the case it filled from.",
    )
    streams: list[Identifier] = Field(
        default_factory=list,
        description="The flowsheet stream ids the conditions come from; cheme datasheets fill "
        "writes the streams at the item's linked nodes.",
    )

    def __contains__(self, key: object) -> bool:
        return key in (self.model_extra or {})

    def __getitem__(self, key: str) -> Value:
        return (self.model_extra or {})[key]


class SizingItem(Strict):
    """One line of the sizing basis."""

    parameter: str
    value: Value
    reference: str = Field(
        default="", description="Design basis or DESIGN.md decision it rests on."
    )


class DatasheetNozzle(Strict):
    """One nozzle of the item, as its P&ID draws it."""

    name: str = Field(description="SubTagName on the P&ID (N1), else its DEXPI id.")
    dn: float | str | None = Field(default=None, description="Nominal diameter (DN).")
    lines: list[str] = Field(default_factory=list, description="Line numbers ending at it.")
    service: str = ""
    rating: str = ""
    source: str = Field(default="", description="Where it comes from, e.g. pid/P-01.xml.")
    orientation_deg: float | None = Field(
        default=None,
        description="Plan direction, deg from site east (x) counter-clockwise, as the "
        "placement's angle_deg: of the nozzle axis for a side nozzle; of its offset from the "
        "item's centre for a top or bottom nozzle off the centre.",
    )
    offset_m: float | None = Field(
        default=None,
        description="A top or bottom nozzle's plan distance from the item's centre, m (a roof "
        "nozzle, a nozzle along a horizontal shell).",
    )
    face: str = Field(default="", description="top, bottom or side (the shell).")
    elevation_m: float | None = Field(
        default=None,
        description="Nozzle centre above the item's base (its placement elevation), m.",
    )
    location_source: str = Field(
        default="",
        description="Where orientation, face and elevation come from, e.g. "
        "layout/equipment-placement.yaml (DESIGN.md D-039).",
    )
    mark: str = Field(
        default="",
        description="The mark on the outline drawing and the nozzle schedule when it differs "
        "from name (M1 for a manway, N1A); default the name.",
    )
    facing: str = Field(default="", description="Flange facing: RF, FF, RTJ, ... ")
    standard: str = Field(default="", description="Flange standard, e.g. ASME B16.5, EN 1092-1.")
    projection_m: float | None = Field(
        default=None,
        description="Flange face from the item's axis (a side nozzle of a vertical item) or "
        "from the shell or head surface it leaves (any other nozzle), m.",
    )
    axial_m: float | None = Field(
        default=None,
        description="A nozzle of a horizontal item or a machine: its position along the item's "
        "own axis from the item's centre, m, positive towards the rear head (the outline "
        "drawing places it there).",
    )
    assumed: bool = Field(default=False, description="True: the schedule entry is an assumption.")


#: Material classes a datasheet part is matched by elsewhere (the material take-off, the LCA
#: construction inventory, the cost material factor).
MaterialClass = Literal[
    "carbon_steel",
    "low_temperature_carbon_steel",
    "low_alloy_steel",
    "stainless_steel",
    "duplex_stainless_steel",
    "nickel_alloy",
    "aluminium",
    "copper_alloy",
    "titanium",
    "cast_iron",
    "plastic",
    "fibre_reinforced_plastic",
    "lined_steel",
    "concrete",
    "other",
]


class Material(Strict):
    """The material of one part (``materials.shell``, ``materials.tubes``) with its class, so it
    can be matched elsewhere. A plain value (``shell: SA-516-70``) is still accepted."""

    value: str = Field(description="The designation: SA-516-70, 1.4404, Aluminium 5083, TBD.")
    material_class: MaterialClass | None = Field(
        default=None, description="The class it belongs to (carbon_steel, stainless_steel, ...)."
    )
    standard: str = Field(default="", description="Material standard, e.g. ASME II A, EN 10028.")
    assumed: bool = Field(default=False, description="True: an assumption, not data.")
    source: str = Field(default="", description="Where it comes from.")
    reason: str = Field(default="", description="As for a value: with supplier/not_applicable.")


class Support(Strict):
    """How the item stands: type and height, and what it stands on when not on grade."""

    type: Value | None = Field(
        default=None, description="skirt, legs, saddles, lugs, base_plate or none."
    )
    height: Value | None = Field(
        default=None,
        description="m: from the base to the bottom tangent line (skirt, legs, lugs), or to the "
        "underside of the shell (saddles).",
    )
    count: Value | None = Field(default=None, description="Legs, saddles or lugs.")
    stands_on: Value | None = Field(
        default=None,
        description="Tag of the item this one stands on, when not on grade (an LP column "
        "stacked on the HP column): the outline drawing labels its base with it.",
    )
    elevation: Value | None = Field(
        default=None,
        description="m: the base above grade (the placement's z), when not on grade.",
    )


class ColumnSection(Strict):
    """One section of a column: trays or packing, from the bottom tangent line up."""

    id: str = Field(description="Section name, e.g. stripping, rectifying, bed 1.")
    internals: Value | None = Field(
        default=None, description="sieve trays, valve trays, structured packing Mellapak 250Y, ..."
    )
    bottom: Value | None = Field(
        default=None, description="Bottom of the section above the bottom tangent line, m."
    )
    height: Value | None = Field(default=None, description="Section height, m.")
    count: Value | None = Field(default=None, description="Number of trays (or beds).")
    spacing: Value | None = Field(default=None, description="Tray spacing, m.")
    notes: str = ""


class Tubes(Strict):
    """The tube bundle of a shell-and-tube exchanger."""

    count: Value | None = None
    outside_diameter: Value | None = Field(default=None, description="Tube OD (m or mm).")
    length: Value | None = Field(default=None, description="Tube length, m.")
    passes: Value | None = Field(default=None, description="Tube passes.")
    pitch: Value | None = Field(default=None, description="Tube pitch (m or mm).")


class Plates(Strict):
    """The plate pack of a plate exchanger."""

    height: Value | None = Field(default=None, description="Plate height, m.")
    width: Value | None = Field(default=None, description="Plate width, m.")
    count: Value | None = Field(default=None, description="Number of plates.")


class Baseplate(Strict):
    """The baseplate (skid) of a machine."""

    length: Value | None = Field(default=None, description="m, along the shaft.")
    width: Value | None = Field(default=None, description="m, across.")


class DatasheetDimensions(Strict):
    """The main dimensions of the item, each a value with its unit (m unless stated) and
    source. Give those of the item's family: vessels, columns and tanks (diameters, tangent
    length, head, support, column sections), shell-and-tube exchangers (the shell's inside
    diameter, tube bundle, passes), plate exchangers (plates), machines (baseplate, shaft
    height). ``overall_*`` are the overall sizes the equipment list's ``dimensions`` give."""

    orientation: Literal["vertical", "horizontal"] | None = Field(
        default=None, description="Of the axis of a round item (vessel, column, exchanger)."
    )
    inside_diameter: Value | None = Field(default=None, description="Shell ID, m.")
    outside_diameter: Value | None = Field(default=None, description="Shell OD, m.")
    tangent_length: Value | None = Field(
        default=None, description="Tangent to tangent (T-T), m: the cylindrical shell."
    )
    head: Value | None = Field(
        default=None,
        description="Head (or roof) type: ellipsoidal_2_1, hemispherical, torispherical, flat, "
        "cone, cone_roof, dome_roof.",
    )
    support: Support | None = None
    sections: list[ColumnSection] = Field(
        default_factory=list, description="A column's sections (trays, packed beds)."
    )
    shell_passes: Value | None = Field(default=None, description="Shell-and-tube: shell passes.")
    tubes: Tubes | None = None
    plates: Plates | None = None
    baseplate: Baseplate | None = None
    shaft_height: Value | None = Field(
        default=None,
        description="A machine's shaft centre line above the baseplate's underside, m.",
    )
    axis_deg: Value | None = Field(
        default=None,
        description="Plan direction of a horizontal item's (or machine's) own axis, deg from "
        "site east counter-clockwise (the placement's angle): turns the nozzles' "
        "orientation_deg into the item's frame on the outline drawing.",
    )
    housed_in: Value | None = Field(
        default=None,
        description="Tag of the item that houses this one (a condenser in a column sump), "
        "when it has no main dimensions of its own: the outline drawing says so.",
    )
    overall_height: Value | None = Field(default=None, description="Overall height, m.")
    overall_length: Value | None = Field(default=None, description="Overall length, m.")
    overall_width: Value | None = Field(default=None, description="Overall width, m.")


class Weights(Strict):
    """Weights of the item, t."""

    empty: Value | None = Field(default=None, description="Empty (erection) weight, t.")
    operating: Value | None = Field(default=None, description="Operating weight, t.")
    test: Value | None = Field(default=None, description="Full of water (hydrotest), t.")


class Datasheet(Strict, optional_schema("datasheet")):
    """One equipment item's datasheet. ``tag`` must be in the equipment list."""

    tag: Identifier = Field(description="Equipment-list tag; the file is named <tag>.yaml.")
    type: str | None = Field(default=None, description="DEXPI class, as in the equipment list.")
    service: str = ""
    operating: Operating = Field(
        default_factory=Operating,
        description="Operating conditions: pressure_barg, temperature_degc, flow_kg_h, ...; "
        "and the flowsheet case and streams they are for.",
    )
    design: dict[str, Value] = Field(
        default_factory=dict,
        description="Design conditions; pressure_barg and temperature_degc must match the "
        "equipment list's design_pressure_barg / design_temperature_degc.",
    )
    materials: dict[str, Value | Material] = Field(
        default_factory=dict,
        description="Material per part: casing, impeller, shell, ...; a value, or a mapping "
        "with value, material_class and standard.",
    )
    dimensions: DatasheetDimensions | None = Field(
        default=None, description="Main dimensions (the outline drawing is drawn from them)."
    )
    weights: Weights | None = None
    nozzles: list[DatasheetNozzle] = Field(
        default_factory=list, description="The item's nozzles (from the P&ID)."
    )
    sizing_basis: list[SizingItem] = Field(default_factory=list)
    type_specific: dict[str, Any] = Field(
        default_factory=dict, description="Fields of the equipment type (pump: NPSHr, ...)."
    )
    draft: bool = Field(
        default=False,
        description="A generated draft (cheme datasheets draft): every value says where it "
        "comes from, TBD values are not known yet; the datasheets gate does not count it.",
    )
    notes: str = ""
