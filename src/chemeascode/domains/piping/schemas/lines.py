"""``piping/line-list.yaml`` and ``control/instrument-list.yaml``."""

from pydantic import Field

from chemeascode.foundation.schema_base import Identifier, Strict, optional_schema


class LineSegment(Strict):
    """One segment of a line, by the SegmentNumber its PipingNetworkSegment carries (e.g. S2)."""

    number: Identifier = Field(description="SegmentNumber on the P&ID, e.g. S2.")
    nominal_diameter: Identifier | None = Field(default=None, description="e.g. DN50.")
    notes: str = ""


class Line(Strict):
    """One piping line. ``number`` must match a line number on a P&ID.

    ``nominal_diameter`` is the line's DN; a line whose segments differ (after a reducer, a
    branch) lists them under ``segments``, each with its own DN.
    """

    number: Identifier
    from_: str = Field(alias="from", description="Equipment or nozzle tag the line starts at.")
    to: str
    nominal_diameter: Identifier | None = Field(default=None, description="e.g. DN80.")
    pressure_class: str | None = Field(default=None, description="e.g. PN16.")
    fluid: str | None = None
    insulation: str | None = None
    sheet: str | None = None
    notes: str = ""
    segments: list[LineSegment] = Field(
        default_factory=list, description="Segments with their own DN, by SegmentNumber."
    )
    from_area: str | None = Field(
        default=None,
        description="Layout area the start is in, when it is no placed item (e.g. a vent area).",
    )
    to_area: str | None = Field(
        default=None, description="Layout area the end is in, when it is no placed item."
    )


class LineList(Strict, optional_schema("lines")):
    """Every piping line of the plant."""

    lines: list[Line] = Field(default_factory=list)


class Instrument(Strict):
    """One instrument function. ``tag`` as printed, e.g. PICSA-4712.02."""

    tag: Identifier
    service: str = ""
    sheet: str | None = None
    notes: str = ""


class InstrumentList(Strict, optional_schema("instruments")):
    """Every instrument function of the plant."""

    instruments: list[Instrument] = Field(default_factory=list)
