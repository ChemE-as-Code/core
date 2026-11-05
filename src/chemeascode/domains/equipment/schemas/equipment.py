"""``equipment/equipment-list.yaml``."""

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from chemeascode.foundation.schema_base import Identifier, Strict, optional_schema

#: Head of a vessel or column, or roof of a tank.
Head = Literal[
    "ellipsoidal_2_1", "hemispherical", "torispherical", "flat", "cone", "cone_roof", "dome_roof"
]
#: How an item stands on its foundation or level.
Support = Literal["skirt", "legs", "saddles", "base_plate", "none"]
#: The variant of a machine's 3D shape (pumps, compressors, turbines).
Variant = Literal[
    "end_suction",
    "vertical_inline",
    "cryogenic",
    "integrally_geared",
    "blower",
    "compander",
    "expander",
    "machine",
]


class Dimensions(Strict):
    """Overall size of an item, in metres: the one source of its 3D shape.

    A round item gives ``diameter`` (outside of the shell) and ``height`` (vertical: from the
    bottom of its support to the top of its head) or ``length`` (horizontal, along its axis, over
    both heads or channels). A box-like item (pump, skid, plate exchanger, package) gives
    ``length`` (along its own x), ``width`` (or ``depth``, along its own y) and ``height``.
    """

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    diameter: float | None = Field(default=None, description="Outside shell diameter, m.")
    height: float | None = Field(default=None, description="Overall height, m.")
    length: float | None = Field(default=None, description="Overall length along the axis, m.")
    width: float | None = Field(default=None, description="Extent across (own y), m.")
    depth: float | None = Field(default=None, description="Same as width; give one of them.")
    head: Head | None = Field(default=None, description="Head or roof type.")
    support: Support | None = Field(default=None, description="Skirt, legs, saddles, ...")
    weight: float | None = Field(default=None, description="Empty weight, t (optional).")
    lift_weight: float | None = Field(
        default=None,
        description="The heaviest single maintenance lift of the item (a motor, rotor or "
        "bundle), t (optional): the lifting study lifts this instead of the weight.",
    )
    orientation: Literal["horizontal", "vertical"] | None = Field(
        default=None, description="A machine's shaft: horizontal (default) or vertical."
    )
    variant: Variant | None = Field(
        default=None,
        description="The machine's 3D shape: end_suction, vertical_inline or cryogenic "
        "(pumps), integrally_geared, blower or machine (compressors), compander, expander or "
        "machine (turbines); default by the DEXPI class.",
    )
    source: str = Field(
        default="",
        description="Where the sizes come from, when a tool calculated them (cheme process "
        "stack: ...); the datasheets carry it with each main dimension.",
    )
    assumed: bool = Field(
        default=False, description="The sizes rest on an assumption (marked ASSUMED)."
    )
    fingerprint: str | None = Field(
        default=None, description="Of the inputs a tool calculated the sizes from."
    )

    @model_validator(mode="after")
    def _check(self) -> "Dimensions":
        for name in ("diameter", "height", "length", "width", "depth", "weight", "lift_weight"):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be greater than 0, not {value:g}")
        if self.width is not None and self.depth is not None:
            raise ValueError("give width or depth, not both")
        if self.diameter is not None:
            if self.width is not None or self.depth is not None:
                raise ValueError("a round item takes diameter, not width or depth")
        elif self.height is None and self.length is None:
            raise ValueError("give diameter with height or length, or length, width and height")
        return self

    @property
    def across(self) -> float | None:
        """``width``, else ``depth``."""
        return self.width if self.width is not None else self.depth


class EquipmentItem(Strict):
    """One tagged equipment item. ``tag`` must match the TagName on its P&ID."""

    tag: Identifier
    type: str = Field(description="DEXPI class, e.g. CentrifugalPump, Tank, PlateHeatExchanger.")
    service: str = ""
    sheet: str | None = Field(default=None, description="Sheet id the item is drawn on.")
    design_pressure_barg: float | None = None
    design_temperature_degc: float | None = None
    material: str | None = None
    dimensions: Dimensions | None = Field(
        default=None,
        description="Overall size, m: shape and extent of the item in the 3D layout.",
    )
    notes: str = ""


class EquipmentList(Strict, optional_schema("equipment")):
    """Every tagged equipment item of the plant."""

    equipment: list[EquipmentItem] = Field(default_factory=list)
