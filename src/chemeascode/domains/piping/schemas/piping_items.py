"""``piping/special-items.yaml``: tagged piping components (safety valves, silencers, ...)."""

from pydantic import Field

from chemeascode.foundation.schema_base import Identifier, Strict, optional_schema


class PipingItem(Strict):
    """One tagged piping component. ``tag`` as the P&ID prints it (PipingComponentNumber, else
    PositionNumber, else PipingComponentName; a segment-local C1 is no tag), e.g. PSV-4122 or
    S-4101."""

    tag: Identifier
    type: str = Field(description="DEXPI class, e.g. SpringLoadedGlobeSafetyValve, Silencer.")
    line: Identifier | None = Field(default=None, description="Line number it sits on.")
    sheet: str | None = Field(default=None, description="Sheet id it is drawn on.")
    set_pressure_barg: float | None = Field(default=None, description="Relief devices.")
    relief_case: str = Field(default="", description="Governing relief case, for relief devices.")
    notes: str = ""


class PipingItemList(Strict, optional_schema("piping_items")):
    """Tagged piping components: relief devices, silencers, other special items."""

    piping_items: list[PipingItem] = Field(default_factory=list)
