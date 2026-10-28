"""``layout/*.yaml``: the 3D layout of the plant (site plan, buildings, equipment placement).

Every coordinate is in metres in the site frame: x east, y north, z up, origin at the south-west
corner of the site. Rotations are in degrees, counterclockwise seen from above.
"""

import math
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from chemeascode.domains.piping.schemas.pipe_specs import PipeSpecs
from chemeascode.foundation.schema_base import Strict, _identifier, optional_schema


class LayoutModel(Strict):
    """Unknown keys refused, and no ``.inf`` or ``.nan``: every number must be finite."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


#: An id of an area, road, rack, building or level: not empty.
Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
#: An equipment tag: as :data:`~chemeascode.foundation.schema_base.Identifier`, and not empty.
Tag = Annotated[str, StringConstraints(min_length=1), BeforeValidator(_identifier)]

Point = tuple[float, float]


def _section(name: str) -> str:
    from chemeascode.domains.spatial.structures import section_size

    if section_size(name) is None:
        raise ValueError(
            f"unknown steel section {name!r}: name an HEB (100 to 1000), HEA, IPE or UPN size, "
            "an equal angle (L100x10), a square hollow section (RHS50x50) or a flat bar "
            "(FL100x10) of the material take-off's table, e.g. HEB300 (its b x h sizes the "
            "steel in the model)"
        )
    return name


#: A rolled steel section by name (``HEB300``; blanks and case ignored).
Section = Annotated[str, AfterValidator(_section)]


def _positive(name: str, value: float) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0, not {value:g}")


#: Consecutive points of a road or rack closer than this are the same point, m.
SAME_POINT = 1e-6


def _path(name: str, points: list[Point], width: float) -> None:
    if len(points) < 2:
        raise ValueError(f"{name} needs at least two points")
    for k, (a, b) in enumerate(zip(points, points[1:], strict=False), start=1):
        if math.dist(a, b) <= SAME_POINT:
            raise ValueError(
                f"{name}'s points {k} and {k + 1} are the same ({a[0]:g}, {a[1]:g}): each "
                "segment needs a length; remove the repeated point"
            )
    _positive("width", width)


# ---------------------------------------------------------------------------
# layout/site-plan.yaml
# ---------------------------------------------------------------------------


class Site(LayoutModel):
    """The site boundary: a rectangle from (0, 0) to (width, depth)."""

    name: str = ""
    width: float = Field(description="Extent east (x), m.")
    depth: float = Field(description="Extent north (y), m.")

    @model_validator(mode="after")
    def _check(self) -> "Site":
        _positive("width", self.width)
        _positive("depth", self.depth)
        return self


#: Height of a bund wall when the area does not say, m (ASSUMED).
BUND_WALL_HEIGHT = 1.0


class Area(LayoutModel):
    """A plot area of the site. A ``bund`` (a containment around tanks, inside a storage
    area) has walls of ``wall_height`` (default 1 m, ASSUMED) along its box."""

    id: Id
    title: str = ""
    box: tuple[float, float, float, float] = Field(description="[x0, y0, x1, y1], m.")
    kind: Literal["process", "utilities", "storage", "road", "reserved", "building", "bund"] = (
        "process"
    )
    wall_height: float | None = Field(
        default=None, description="A bund's wall height above grade, m (default 1, ASSUMED)."
    )

    @model_validator(mode="after")
    def _check(self) -> "Area":
        x0, y0, x1, y1 = self.box
        if x1 <= x0 or y1 <= y0:
            raise ValueError("box must be [x0, y0, x1, y1] with x0 < x1 and y0 < y1")
        if self.wall_height is not None:
            if self.kind != "bund":
                raise ValueError("wall_height is for an area of kind bund")
            _positive("wall_height", self.wall_height)
        return self


class Road(LayoutModel):
    """A road along a polyline."""

    id: Id
    title: str = ""
    points: list[Point] = Field(description="Centreline [[x, y], ...], m.")
    width: float = Field(description="Carriageway width, m.")

    @model_validator(mode="after")
    def _check(self) -> "Road":
        _path("a road", self.points, self.width)
        return self


class RackLadder(LayoutModel):
    """A caged access ladder at an end of a rack, from grade to its top tier."""

    id: Id
    end: Literal["start", "end"] = Field(description="The rack end it stands at.")


class RackIntermediate(LayoutModel):
    """Intermediate steel of a rack between its bents, on the tiers given (default every
    tier): a stringer along each edge of the tier and a beam across every ``spacing_m``, top
    of steel at the tier. The pipes rest on those beams as on the bents' (shorter spans for the
    small lines). Absent: none (the rack has its bents only)."""

    spacing_m: float = Field(
        default=3.0, description="Beams across at most this far apart, bents included, m."
    )
    levels: list[float] | None = Field(default=None, description="Tiers with it; default all.")
    section: Section | None = Field(default=None, description="e.g. HEB200; default by span.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "RackIntermediate":
        _positive("spacing_m", self.spacing_m)
        return self


class Rack(LayoutModel):
    """A pipe rack along a polyline, with a tier at each level. ``ladders`` declares its
    access ladders (``[]``: none); without it, layout build proposes one at each free end.
    ``intermediate_supports`` adds steel between the bents (:class:`RackIntermediate`)."""

    id: Id
    title: str = ""
    points: list[Point] = Field(description="Centreline [[x, y], ...], m.")
    width: float = Field(description="Width across the rack, m.")
    levels: list[float] = Field(default_factory=list, description="Tier elevations, m.")
    ladders: list[RackLadder] | None = Field(
        default=None, description="Access ladders; absent: proposed by layout build."
    )
    intermediate_supports: RackIntermediate | None = Field(
        default=None, description="Steel between the bents; absent: none."
    )
    bent_spacing_m: float | None = Field(
        default=None,
        gt=0,
        description="Bents of this rack about this far apart (evenly along it), m; absent: "
        "the routing rules' rack_bent_spacing_m. Choose it so no bent stands in a road the "
        "rack crosses.",
    )

    @model_validator(mode="after")
    def _check(self) -> "Rack":
        _path("a rack", self.points, self.width)
        if any(level < 0 for level in self.levels):
            raise ValueError("rack levels must be at or above grade (0)")
        extra = self.intermediate_supports
        if extra is not None and extra.levels is not None:
            unknown = [z for z in extra.levels if all(abs(z - lv) > 1e-6 for lv in self.levels)]
            if unknown:
                raise ValueError(
                    f"rack {self.id}: intermediate_supports levels "
                    f"{', '.join(f'{z:g}' for z in unknown)} are no tiers of the rack"
                )
        return self


class Separation(LayoutModel):
    """A minimum horizontal distance between two things of the plot plan."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    from_: Id = Field(
        alias="from",
        description="A placed tag, or an area, building, road or rack id, or site-boundary.",
    )
    to: Id
    min_m: float | None = Field(default=None, description="Minimum distance, m.")
    min_factor_of_height: float | None = Field(
        default=None, description="Minimum distance as a multiple of the height (toppling)."
    )
    height_of: Literal["max", "from", "to"] = Field(
        default="max", description="Whose height min_factor_of_height multiplies."
    )
    measure: Literal["footprint", "centre"] = Field(
        default="footprint", description="Between footprints (default) or centres."
    )
    reason: str = ""
    basis: str = Field(default="", description="Where the criterion comes from, e.g. D-026.")

    @model_validator(mode="after")
    def _check(self) -> "Separation":
        if (self.min_m is None) == (self.min_factor_of_height is None):
            raise ValueError("give exactly one of min_m and min_factor_of_height")
        for name in ("min_m", "min_factor_of_height"):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        if self.from_ == self.to:
            raise ValueError("a separation needs two different things")
        return self


class LayoutCriteria(LayoutModel):
    """The project's values of the layout criteria the rules on the 3D model use; each one left
    out takes the package default (``domains/spatial/data/layout-criteria.yaml``, ASSUMED)."""

    operator_max_height_m: float | None = Field(
        default=None, description="Highest valve handwheel or lever above the floor, m."
    )
    operator_reach_m: float | None = Field(
        default=None, description="How far out from a floor's edge an operator may be, m."
    )
    instrument_max_height_m: float | None = Field(
        default=None, description="Highest transmitter head above the floor, m."
    )
    stair_travel_m: float | None = Field(
        default=None, description="Farthest point of a floor from its nearest stair, m."
    )
    dead_end_m: float | None = Field(
        default=None,
        description="Longest dead-end walk on a floor or platform (to its only way down, or "
        "to where two of its ways lie 45 degrees or more apart), m.",
    )
    escape_remote_fraction: float | None = Field(
        default=None,
        description="Two ways down a floor count as two when they arrive at least this "
        "fraction of the floor's diagonal apart in plan.",
    )
    heavy_lift_t: float | None = Field(
        default=None, description="Items this heavy or heavier need a crane lift, t."
    )
    crane_reach_m: float | None = Field(
        default=None, description="Working radius of a mobile crane on a crane pad, m."
    )
    lane_margin_m: float | None = Field(
        default=None, description="Clearance either side of a load in its crane lane, m."
    )
    lift_clearance_m: float | None = Field(
        default=None, description="Clearance of a load over what it passes, m."
    )
    vent_plan_clearance_m: float | None = Field(
        default=None,
        description="A walking surface this close in plan above a vent outlet is in its "
        "discharge, m.",
    )
    vent_overhead_m: float | None = Field(
        default=None,
        description="How far above a vent outlet a walking surface is in its discharge, m.",
    )
    vent_side_clearance_m: float | None = Field(
        default=None,
        description="A walking surface this close in plan beside a vent outlet (the outlet "
        "between its floor and the walkway headroom above it) is in its discharge, m.",
    )
    support_pipe_clearance_m: float | None = Field(
        default=None,
        description="A proposed support post keeps this clearance from the pipes it does not "
        "carry, m.",
    )
    support_stub_max_m: float | None = Field(
        default=None,
        description="The tallest support stub on steel (a proposal stands on steel only this "
        "close below; a declared stub taller than this is a finding), m.",
    )
    casing_reach_m: float | None = Field(
        default=None,
        description="An item inside a casing is worked through a declared hatch this close, m.",
    )
    access_headroom_m: float | None = Field(
        default=None,
        description="Clear height over structure floors, platforms, stair treads and landings, m.",
    )
    ladder_clearance_m: float | None = Field(
        default=None,
        description="Least clearance of a pipe from a ladder's rails (none through its cage), m.",
    )
    walkway_clear_m: float | None = Field(
        default=None,
        description="Least clear walkway width beside a riser through an item's ring platform, m.",
    )
    standing_space_m: float | None = Field(
        default=None,
        description="Side of the free square an operator stands in at a valve or hatch, m.",
    )
    chainwheel_max_height_m: float | None = Field(
        default=None,
        description="Highest handwheel above the floor a declared chain wheel may serve, m.",
    )
    extension_max_m: float | None = Field(
        default=None, description="Longest extension spindle or remote operator, m."
    )
    impulse_max_m: float | None = Field(
        default=None, description="Longest impulse line run of a remote-mounted transmitter, m."
    )
    capillary_max_m: float | None = Field(
        default=None, description="Longest capillary of a remote-mounted transmitter, m."
    )
    valve_platform_group_m: float | None = Field(
        default=None,
        description="Valves out of reach this close in plan share one proposed platform, m.",
    )
    valve_platform_operating_m: float | None = Field(
        default=None,
        description="A proposed valve platform's floor below the highest handwheel it serves, m.",
    )
    valve_platform_depth_m: float | None = Field(
        default=None, description="Width of a proposed valve platform out from the pipes, m."
    )
    lift_dynamic_factor: float | None = Field(
        default=None, description="Dynamic allowance on the weight of a crane lift (>= 1)."
    )
    lift_rigging_fraction: float | None = Field(
        default=None, description="Rigging and hook block weight as a fraction of the load."
    )
    lift_rigging_height_m: float | None = Field(
        default=None, description="Height of the rigging between hook and load top, m."
    )
    lift_chart_utilisation: float | None = Field(
        default=None, description="Highest fraction of the crane chart capacity a lift uses."
    )
    spacing_table: bool = Field(
        default=True,
        description="Check the package equipment and building spacing tables.",
    )

    @model_validator(mode="after")
    def _check(self) -> "LayoutCriteria":
        for name, value in self:
            if isinstance(value, float) and value <= 0:
                raise ValueError(f"{name} must be greater than 0, not {value:g}")
        if self.lift_dynamic_factor is not None and self.lift_dynamic_factor < 1:
            raise ValueError("lift_dynamic_factor must be at least 1")
        if self.lift_chart_utilisation is not None and self.lift_chart_utilisation > 1:
            raise ValueError("lift_chart_utilisation must be at most 1")
        if self.escape_remote_fraction is not None and self.escape_remote_fraction > 1:
            raise ValueError("escape_remote_fraction must be at most 1")
        return self


class SitePlan(LayoutModel, optional_schema("site_plan")):
    """The site plan: boundary, plot areas, roads and pipe racks."""

    site: Site
    areas: list[Area] = Field(default_factory=list)
    roads: list[Road] = Field(default_factory=list)
    racks: list[Rack] = Field(default_factory=list)
    max_unsupported_length: float = Field(
        default=30.0,
        description="Lines whose ends are further apart (or in different areas) need a rack, m.",
    )
    rack_reach: float | None = Field(
        default=None,
        description="How far a line's end may be from a rack centreline to be carried by it, m: "
        "the one value the pipe router and cheme validate's line-route check use (default: "
        "max_unsupported_length, since the run from the end to the rack is unsupported).",
    )

    @property
    def reach(self) -> float:
        """``rack_reach``, else ``max_unsupported_length``."""
        return self.rack_reach if self.rack_reach is not None else self.max_unsupported_length

    separations: list[Separation] = Field(
        default_factory=list, description="Minimum distances: spacing criteria, keep-clear radii."
    )
    criteria: LayoutCriteria | None = Field(
        default=None,
        description="Project values of the layout criteria (operability, escape, lifting); "
        "default: the package table (ASSUMED).",
    )
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "SitePlan":
        _positive("max_unsupported_length", self.max_unsupported_length)
        if self.rack_reach is not None:
            _positive("rack_reach", self.rack_reach)
        return self


# ---------------------------------------------------------------------------
# layout/building.yaml
# ---------------------------------------------------------------------------


class Level(LayoutModel):
    """A floor, platform or roof of a building."""

    id: Id
    title: str = ""
    elevation: float = Field(description="Top of floor, m above grade.")
    height: float = Field(default=0.0, description="Clear height to the next level, m.")
    kind: Literal["floor", "platform", "roof"] = "floor"

    @model_validator(mode="after")
    def _check(self) -> "Level":
        if self.height < 0:
            raise ValueError(f"height must not be negative, not {self.height:g}")
        return self


class Frame(LayoutModel):
    """The column grid, as offsets from the building origin along its own x and y."""

    grid_x: list[float] = Field(default_factory=list)
    grid_y: list[float] = Field(default_factory=list)


#: A side of a rectangle in its own frame: south = -y, north = +y, west = -x, east = +x.
Side = Literal["north", "south", "east", "west"]
SIDES: tuple[str, ...] = ("south", "east", "north", "west")


class Opening(LayoutModel):
    """A door, roller door, louvre or window in a wall: ``offset`` along the side (from its
    left end seen from outside), ``width``, ``height`` and ``sill`` above the floor. In a
    casing, a ``hatch`` is an access opening an item inside is worked through."""

    id: Id | None = None
    side: Side
    offset: float = Field(description="From the left end of the side seen from outside, m.")
    width: float
    height: float
    sill: float = Field(default=0.0, description="Bottom above the building's floor, m.")
    kind: Literal["door", "roller_door", "louvre", "window", "opening", "hatch"] = "door"

    @model_validator(mode="after")
    def _check(self) -> "Opening":
        _positive("width", self.width)
        _positive("height", self.height)
        if self.offset < 0 or self.sill < 0:
            raise ValueError("offset and sill must not be negative")
        return self


class Crane(LayoutModel):
    """An overhead travelling crane: its runway along the building's longer side, the bridge
    across it."""

    capacity_t: float = Field(description="Safe working load, t.")
    rail_elevation: float | None = Field(
        default=None, description="Top of rail, m above grade (default 1.5 m below the roof)."
    )
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Crane":
        _positive("capacity_t", self.capacity_t)
        if self.rail_elevation is not None:
            _positive("rail_elevation", self.rail_elevation)
        return self


class Building(LayoutModel):
    """A building or structure: a rectangle from its origin, rotated about that origin. A clad
    building gets a roof; ``crane`` declares an overhead crane."""

    id: Id
    title: str = ""
    origin: Point = Field(description="South-west corner before rotation [x, y], m.")
    width: float = Field(description="Extent along the building's x, m.")
    depth: float = Field(description="Extent along the building's y, m.")
    rotation_deg: Literal[0, 90, 180, 270] = 0
    levels: list[Level] = Field(default_factory=list)
    frame: Frame | None = None
    walls: Literal["all", "none"] | list[Side] = Field(
        default="none", description="Clad sides: all, none or a list of sides (own frame)."
    )
    wall_material: str = Field(default="cladding", description="Rendering hint of the walls.")
    openings: list[Opening] = Field(default_factory=list)
    crane: Crane | None = Field(default=None, description="An overhead travelling crane.")
    use: str | None = Field(
        default=None,
        description="What the building is for, the key of the building spacing table "
        "(domains/spatial/data/building-spacing.yaml): control, substation, office, "
        "process, compressor, workshop, warehouse, ...",
    )

    @model_validator(mode="after")
    def _check(self) -> "Building":
        _positive("width", self.width)
        _positive("depth", self.depth)
        ids = [level.id for level in self.levels]
        if len(ids) != len(set(ids)):
            raise ValueError("level ids must be unique within a building")
        if self.frame is not None:
            for name, grid, extent in (
                ("grid_x", self.frame.grid_x, self.width),
                ("grid_y", self.frame.grid_y, self.depth),
            ):
                outside = [g for g in grid if g < 0 or g > extent]
                if outside:
                    raise ValueError(f"frame.{name} {outside[0]:g} is outside 0..{extent:g}")
        return self


class BuildingList(LayoutModel, optional_schema("building")):
    """Buildings and structures with their levels and column grids."""

    buildings: list[Building] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/equipment-placement.yaml
# ---------------------------------------------------------------------------


class PlacementSize(LayoutModel):
    """Size of a round shape: a diameter, and a height (vertical) or length (horizontal)."""

    diameter: float
    height: float | None = None
    length: float | None = None


class Mount(LayoutModel):
    """What an item stands on: a level of a building (``layout/building.yaml``) or of a
    steel structure (``layout/structures.yaml``)."""

    building: Id | None = Field(default=None, description="Id in layout/building.yaml.")
    structure: Id | None = Field(default=None, description="Id in layout/structures.yaml.")
    level: Id | None = Field(default=None, description="Level id of that building or structure.")

    @model_validator(mode="after")
    def _check(self) -> "Mount":
        if (self.building is None) == (self.structure is None):
            raise ValueError("mount: give a building or a structure (one of them)")
        return self

    @property
    def owner(self) -> str:
        return self.building or self.structure or ""


Face = Literal["top", "bottom", "north", "south", "east", "west", "front", "back"]


class NozzlePlacement(LayoutModel):
    """Where one nozzle of the item sits, overriding the position derived from the P&ID.

    Either ``angle_deg`` with ``elevation`` (vertical items: degrees ccw from the item's own x,
    height above the item's bottom) or ``along`` (horizontal items: distance from the front end
    along the axis, with ``angle_deg`` about the axis, 0 = top, 90 = own +y), or a ``face`` of
    the item with an ``offset`` ``[u, v]`` from the face's centre (top and bottom: u along the
    item's x, v along its y; a side: u along the face, v up). Faces are in the item's own frame:
    north = +y, east = +x, front = the -x end, back = the +x end.
    """

    id: Id = Field(description="The nozzle's SubTagName on the P&ID (N1), or its DEXPI id.")
    angle_deg: float | None = None
    elevation: float | None = Field(default=None, description="Above the item's bottom, m.")
    along: float | None = Field(default=None, description="From the front end, m.")
    face: Face | None = None
    offset: tuple[float, float] | None = Field(default=None, description="[u, v] on the face, m.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "NozzlePlacement":
        polar = [n for n in ("angle_deg", "elevation", "along") if getattr(self, n) is not None]
        if self.face is not None and polar:
            raise ValueError(f"nozzle {self.id}: give a face or {', '.join(polar)}, not both")
        if self.face is None and not polar:
            raise ValueError(f"nozzle {self.id}: give angle_deg/elevation, along or a face")
        if self.offset is not None and self.face is None:
            raise ValueError(f"nozzle {self.id}: offset goes with a face")
        return self


class AccessPlatform(LayoutModel):
    """An access platform around a vertical item: its floor ``elevation`` above the item's
    bottom, the arc it covers (``arc_deg: [from, to]``, degrees ccw from the item's own x;
    none: all round) and its ``width`` out from the shell."""

    elevation: float = Field(description="Floor above the item's bottom, m.")
    arc_deg: tuple[float, float] | None = Field(default=None, description="[from, to], ccw.")
    width: float = Field(default=1.0, description="Out from the shell, m (ASSUMED default 1).")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "AccessPlatform":
        _positive("width", self.width)
        if self.elevation <= 0:
            raise ValueError("a platform's elevation must be above the item's bottom")
        return self


class Access(LayoutModel):
    """Declared access to an item: platforms and the side its ladder goes up. Declared access
    replaces the proposals; ``platforms: []`` declares that the item has no platforms of its
    own (reached from a structure, a building level or a mobile platform: say how in
    ``notes``)."""

    platforms: list[AccessPlatform] = Field(default_factory=list)
    ladder_side: float | None = Field(
        default=None,
        description="Angle of the ladders, degrees ccw from the item's own x; with several "
        "platforms it applies to every ladder (leave it out to let the build put each upper "
        "ladder beside the end of its platform's arc).",
    )
    notes: str = Field(default="", description="How the item is reached, why these platforms.")


class Placement(LayoutModel):
    """Where one equipment item stands. Its shape and size come from the equipment list
    (``type`` and ``dimensions``); ``shape`` overrides the shape, ``size`` is only for an item
    without ``dimensions`` (and for an item of ``piping/special-items.yaml``)."""

    tag: Tag = Field(description="Tag in equipment/equipment-list.yaml.")
    position: tuple[float, float, float] = Field(
        description="[x, y, z]: centre of the footprint, z = bottom elevation, m."
    )
    rotation_deg: float = Field(
        default=0.0,
        description="About the vertical axis, ccw; turns the item's own x (the axis of a "
        "horizontal item, a pump's shaft) away from east.",
    )
    mount: Mount | None = Field(
        default=None, description="{building, level} or {structure, level}."
    )
    plinth: float | None = Field(
        default=None,
        gt=0,
        description="Height of a concrete plinth (foundation block) under an item that stands "
        "on grade, m: the item's bottom is on its top (position z = plinth). The model draws "
        "the plinth 0.1 m wider than the footprint and a tank's stair from grade.",
    )
    nozzles: list[NozzlePlacement] = Field(
        default_factory=list, description="Nozzle positions that override the P&ID-derived ones."
    )
    shape: Literal["box", "vertical_cylinder", "horizontal_cylinder", "sphere"] | None = Field(
        default=None, description="Overrides the shape the equipment list's dimensions give."
    )
    access: Access | None = Field(
        default=None,
        description="Declared platforms and ladder; without it, layout build proposes them.",
    )
    size: tuple[float, float, float] | PlacementSize | None = Field(
        default=None,
        description="Only for an item without dimensions in the equipment list: [dx, dy, dz] "
        "(a box), {diameter, height} (vertical cylinder), {diameter, length} (horizontal "
        "cylinder, axis along x before rotation), {diameter} (sphere).",
    )
    notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _on_key(cls, data: Any) -> Any:
        """``on:`` was renamed ``mount:`` (YAML 1.1, which PyYAML reads, takes an unquoted key
        ``on`` for the boolean true)."""
        if isinstance(data, dict) and (True in data or "on" in data):
            raise ValueError("on: is now mount: {building | structure, level}")
        return data

    @model_validator(mode="after")
    def _check(self) -> "Placement":
        if self.plinth is not None:
            if self.mount is not None:
                raise ValueError("a plinth stands on grade: no mount with plinth")
            if abs(self.position[2] - self.plinth) > 1e-6:
                raise ValueError(
                    f"an item on a {self.plinth:g} m plinth stands at z {self.plinth:g} "
                    f"(position z is {self.position[2]:g})"
                )
        if isinstance(self.size, tuple):
            if self.shape not in (None, "box"):
                needs = {
                    "vertical_cylinder": "{diameter, height}",
                    "horizontal_cylinder": "{diameter, length}",
                }.get(self.shape, "{diameter}")
                raise ValueError(
                    f"a {self.shape} takes size {needs}; size [dx, dy, dz] is for a box only"
                )
            if any(d <= 0 for d in self.size):
                raise ValueError("every size [dx, dy, dz] must be greater than 0")
        elif self.size is not None:
            shape = self.shape or self.size_shape()
            needs = {
                "vertical_cylinder": ("height",),
                "horizontal_cylinder": ("length",),
                "sphere": (),
            }.get(shape)
            if needs is None:
                raise ValueError("a box takes size [dx, dy, dz]")
            for name in ("diameter", *needs):
                value = getattr(self.size, name)
                if value is None:
                    raise ValueError(f"a {shape} needs size.{name}")
                _positive(f"size.{name}", value)
        ids = [n.id for n in self.nozzles]
        if len(ids) != len(set(ids)):
            twice = sorted({i for i in ids if ids.count(i) > 1})
            raise ValueError(f"nozzle {', '.join(twice)} is given twice")
        return self

    def size_shape(self) -> str | None:
        """The shape ``size`` describes: a box for ``[dx, dy, dz]``, a cylinder by its keys."""
        if self.size is None:
            return None
        if isinstance(self.size, tuple):
            return "box"
        if self.size.height is not None:
            return "vertical_cylinder"
        if self.size.length is not None:
            return "horizontal_cylinder"
        return "sphere"

    @property
    def building(self) -> str | None:
        """The building the item stands in (``mount.building``)."""
        return self.mount.building if self.mount else None

    @property
    def level(self) -> str | None:
        return self.mount.level if self.mount else None

    @property
    def structure(self) -> str | None:
        """The steel structure the item stands on (``mount.structure``)."""
        return self.mount.structure if self.mount else None


class PlacementList(LayoutModel, optional_schema("placement")):
    """Where each equipment item of the equipment list stands, in 3D."""

    equipment: list[Placement] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/structures.yaml
# ---------------------------------------------------------------------------

#: The pseudo level at grade (elevation 0) that stairs and ladders may start from.
GRADE = "grade"


class StructureLevel(LayoutModel):
    """A level of a steel frame: a full ``deck`` or a ``platform`` (optionally only over
    ``extent`` [x0, y0, x1, y1] in the frame's own coordinates)."""

    id: Id
    title: str = ""
    elevation: float = Field(description="Top of grating, m above grade.")
    kind: Literal["deck", "platform"] = "deck"
    extent: tuple[float, float, float, float] | None = Field(
        default=None,
        description="[x0, y0, x1, y1] in the frame's own coordinates, m; it may reach up to "
        "3 m outside the frame (a cantilevered platform, e.g. outside a casing).",
    )
    use: Literal["regular", "occasional"] | None = Field(
        default=None,
        description="How often people work there (default: a deck regular, a platform "
        "occasional); a level in regular use is reached by a stair.",
    )

    @model_validator(mode="after")
    def _check(self) -> "StructureLevel":
        if self.elevation <= 0:
            raise ValueError(f"level {self.id}: elevation must be above grade")
        if self.extent is not None:
            x0, y0, x1, y1 = self.extent
            if x1 <= x0 or y1 <= y0:
                raise ValueError(f"level {self.id}: extent must be [x0, y0, x1, y1], x0 < x1")
        return self


class Stair(LayoutModel):
    """A stair outside one side of the frame, from one level (or ``grade``) to another."""

    id: Id
    from_: Id = Field(alias="from", description="Level id, or grade.")
    to: Id
    side: Side
    offset: float | None = Field(
        default=None,
        description="Where along the side it starts (from the left seen from "
        "outside), m; default: at the left end.",
    )
    width: float = Field(default=0.9, description="Clear width, m (ASSUMED default).")
    out: float | None = Field(
        default=None,
        description="How far out from the side its inner edge stands, m; default: outside the "
        "enclosure wall on that side, else at the side (a stair outside a platform along the "
        "side stands out by the platform's width).",
    )


class Ladder(LayoutModel):
    """A vertical ladder at ``at`` [x, y] (frame coordinates), from one level to another;
    a cage is drawn above 3 m."""

    id: Id
    from_: Id = Field(alias="from", description="Level id, or grade.")
    to: Id
    at: Point = Field(description="[x, y] in the frame's own coordinates, m.")
    facing: Side = Field(default="south", description="The side a climber faces away from.")


class Enclosure(LayoutModel):
    """Walls around the frame (a cold box casing, a fire wall)."""

    walls: Literal["all"] | list[Side] = "all"
    height: float = Field(description="Top of the walls above grade, m.")
    material: str = Field(default="casing", description="Rendering hint: casing, fire_wall, ...")
    thickness: float = Field(default=0.2, description="m (ASSUMED default).")
    openings: list[Opening] = Field(
        default_factory=list,
        description="Declared openings and pipe penetrations in the walls (offset along the "
        "side from its left end seen from outside, sill above grade); the walls are cut around "
        "them.",
    )

    @model_validator(mode="after")
    def _check(self) -> "Enclosure":
        _positive("height", self.height)
        _positive("thickness", self.thickness)
        return self


Bracing = Literal["none", "x", "k"]


class Structure(LayoutModel):
    """An open steel frame: bays ``spans_x`` by ``spans_y`` from ``origin`` (its south-west
    corner before rotation), columns at every grid point up to the top level."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    id: Id
    title: str = ""
    origin: Point = Field(description="South-west corner before rotation [x, y], m.")
    rotation_deg: Literal[0, 90, 180, 270] = 0
    spans_x: list[float] = Field(description="Bay widths along the frame's x, m.")
    spans_y: list[float] = Field(description="Bay widths along the frame's y, m.")
    levels: list[StructureLevel] = Field(default_factory=list)
    bracing: Bracing | dict[Side, Bracing] = Field(
        default="none", description="One kind for every side, or per side."
    )
    stairs: list[Stair] = Field(default_factory=list)
    ladders: list[Ladder] = Field(default_factory=list)
    enclosure: Enclosure | None = None
    serves: list[str] = Field(
        default_factory=list,
        description="The valves (in-line item ids or tags) a valve access platform is for: one "
        "way down is enough for it while no point is farther than dead_end_m from it.",
    )
    column_section: Section | None = Field(
        default=None, description="e.g. HEB300; default by span."
    )
    beam_section: Section | None = Field(default=None, description="e.g. HEB240; default by span.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Structure":
        for name in ("spans_x", "spans_y"):
            spans = getattr(self, name)
            if not spans:
                raise ValueError(f"{name} needs at least one bay")
            for span in spans:
                _positive(name, span)
        ids = [level.id for level in self.levels]
        if len(ids) != len(set(ids)):
            raise ValueError("level ids must be unique within a structure")
        ways = [way.id for way in (*self.stairs, *self.ladders)]
        twice = sorted({way for way in ways if ways.count(way) > 1})
        if twice:
            raise ValueError(
                f"stair and ladder ids must be unique within a structure: {', '.join(twice)}"
            )
        if GRADE in ids:
            raise ValueError(f"{GRADE} is the pseudo level at grade; give the level another id")
        known = {*ids, GRADE}
        for access in (*self.stairs, *self.ladders):
            for end in (access.from_, access.to):
                if end not in known:
                    raise ValueError(
                        f"{access.id}: no level {end} (levels: {', '.join(sorted(known))})"
                    )
        width, depth = sum(self.spans_x), sum(self.spans_y)
        out = CANTILEVER_MAX + EPS_IN
        for level in self.levels:
            if level.extent is not None:
                x0, y0, x1, y1 = level.extent
                if x0 < -out or y0 < -out or x1 > width + out or y1 > depth + out:
                    raise ValueError(
                        f"level {level.id}: extent is outside the frame 0..{width:g} x "
                        f"0..{depth:g} by more than {CANTILEVER_MAX:g} m (a cantilevered "
                        "platform)"
                    )
        return self

    @property
    def width(self) -> float:
        return sum(self.spans_x)

    @property
    def depth(self) -> float:
        return sum(self.spans_y)

    def elevation(self, level: str) -> float | None:
        """The elevation of *level* (``grade``: 0), None when there is no such level."""
        if level == GRADE:
            return 0.0
        return next((lv.elevation for lv in self.levels if lv.id == level), None)


#: Tolerance of an extent at the frame's edge, m.
EPS_IN = 1e-6
#: How far a level's extent may reach outside the frame (a cantilevered platform outside an
#: enclosure wall), m.
CANTILEVER_MAX = 3.0


class PipeSupport(LayoutModel):
    """Support steel under a pipe, declared where no frame or rack carries it: a ``t_post``
    (a column with a crossbar ``width`` long on top), a ``post`` (a column with a cap) or a
    ``stub`` (a short post standing on the steel below). ``at`` is the plan position, ``top``
    the top of steel; the foot stands on grade (``from: grade``) or on the steel below
    (``from: steel``: ``base``, else the highest horizontal member under it). The crossbar
    (cap) runs at ``rotation_deg`` (ccw from east): across the pipe."""

    id: Id
    kind: Literal["t_post", "post", "stub"] = "t_post"
    at: Point = Field(description="[x, y] in the site frame, m.")
    top: float = Field(description="Top of steel, m above grade.")
    from_: Literal["grade", "steel"] = Field(default="grade", alias="from")
    base: float | None = Field(default=None, description="Foot elevation from steel, m.")
    width: float = Field(default=1.0, description="A t_post's crossbar, m (ASSUMED default).")
    rotation_deg: float = 0.0
    section: Section | None = Field(default=None, description="e.g. HEB200 (ASSUMED default).")
    serves: list[str] = Field(default_factory=list, description="Pipe ids or lines it carries.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "PipeSupport":
        _positive("top", self.top)
        _positive("width", self.width)
        if self.base is not None and self.base >= self.top:
            raise ValueError(f"pipe support {self.id}: base must be below top")
        return self


class StructureList(LayoutModel, optional_schema("structures")):
    """Steel structures: open frames with decks, platforms, stairs, ladders and casings;
    ``pipe_supports``: posts and T-posts under single pipes."""

    structures: list[Structure] = Field(default_factory=list)
    pipe_supports: list[PipeSupport] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/zones.yaml
# ---------------------------------------------------------------------------

ZoneKind = Literal[
    "keep_clear",
    "laydown",
    "maintenance",
    "crane_pad",
    "escape",
    "hazardous",
    "oxygen_enriched",
    "oxygen_deficient",
]
#: Zones nothing may be routed or placed through.
FORBIDDEN_ZONES = ("keep_clear", "laydown", "maintenance", "escape", "crane_pad")


class ZoneSource(LayoutModel):
    """A release point a zone is derived from: a placed tag, a nozzle (``TAG/N1``) or a line
    number (its open ends), with its release grade and substance."""

    item: Id = Field(description="A placed tag, TAG/NOZZLE, or a line number.")
    release_grade: Literal["continuous", "primary", "secondary"] = "secondary"
    substance: str = Field(description="e.g. oxygen, nitrogen, hydrogen, methane.")
    source_kind: str | None = Field(
        default=None,
        description="Kind of release point in the radius table (vent, psv_outlet, pump_seal, "
        "compressor_seal, flange, valve, drain); default: from the item.",
    )
    substance_class: str | None = Field(
        default=None,
        description="Class in the radius table (oxygen, inert, flammable_gas, "
        "flammable_liquid); default: from the substance name.",
    )


class Zone(LayoutModel):
    """A zone: an explicit volume (``box``, ``cylinder``, ``sphere``) or the volumes the
    radius table gives around its ``sources``."""

    id: Id
    title: str = ""
    kind: ZoneKind
    zone: Literal[0, 1, 2, 20, 21, 22] | None = Field(
        default=None, description="Hazardous area zone (IEC 60079-10-1/-2 numbering)."
    )
    shape: Literal["box", "cylinder", "sphere"] | None = None
    box: tuple[float, float, float, float, float, float] | None = Field(
        default=None, description="[x0, y0, z0, x1, y1, z1], m."
    )
    centre: tuple[float, float, float] | None = Field(
        default=None, description="Cylinder: centre of its base; sphere: its centre."
    )
    radius: float | None = None
    height: float | None = Field(default=None, description="Cylinder height, m.")
    sources: list[ZoneSource] = Field(default_factory=list)
    reach_m: float | None = Field(
        default=None,
        description="A crane pad: the working radius of the crane standing on it, m (default: "
        "the layout criteria's crane_reach_m).",
    )
    basis: str = ""
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Zone":
        if self.reach_m is not None:
            _positive("reach_m", self.reach_m)
            if self.kind != "crane_pad":
                raise ValueError(f"zone {self.id}: reach_m belongs to a crane_pad zone")
        if (self.shape is None) == (not self.sources):
            raise ValueError(f"zone {self.id}: give a shape or sources (one of them)")
        if self.shape == "box":
            if self.box is None:
                raise ValueError(f"zone {self.id}: a box needs box: [x0, y0, z0, x1, y1, z1]")
            x0, y0, z0, x1, y1, z1 = self.box
            if x1 <= x0 or y1 <= y0 or z1 <= z0:
                raise ValueError(f"zone {self.id}: box must have x0 < x1, y0 < y1, z0 < z1")
        elif self.shape in ("cylinder", "sphere"):
            if self.centre is None or self.radius is None:
                raise ValueError(f"zone {self.id}: a {self.shape} needs centre and radius")
            _positive("radius", self.radius)
            if self.shape == "cylinder":
                if self.height is None:
                    raise ValueError(f"zone {self.id}: a cylinder needs height")
                _positive("height", self.height)
        if self.kind == "hazardous" and self.zone is None and self.shape is not None:
            raise ValueError(f"zone {self.id}: a hazardous zone needs zone: 0|1|2|20|21|22")
        return self


class ZoneList(LayoutModel, optional_schema("zones")):
    """Keep-clear, laydown, maintenance and escape zones, hazardous areas and oxygen-enriched
    or oxygen-deficient zones."""

    zones: list[Zone] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# piping/routing.yaml
# ---------------------------------------------------------------------------


class Tier(LayoutModel):
    """Which lines run on which rack tier: by fluid (the line list's ``fluid``) or by line
    number prefix; ``rack`` limits it to one rack."""

    rack: Id | None = None
    elevation: float = Field(description="Tier elevation (top of steel), m.")
    fluids: list[str] = Field(default_factory=list, description="Fluid names, any case.")
    lines: list[str] = Field(default_factory=list, description="Line number prefixes.")


Point3 = tuple[float, float, float]


class BatteryLimit(LayoutModel):
    """Where the lines leaving the plot end (a ``BL``, ``CW``, ``CWR`` ... end of the line
    list): a fixed ``point``, or an end of a ``rack``. Matched by line number pattern
    (``CW-*``; a pattern without ``*`` or ``?`` is a prefix) or by fluid."""

    id: Id | None = None
    lines: list[str] = Field(default_factory=list, description="Line number patterns.")
    fluids: list[str] = Field(default_factory=list, description="Fluid names, any case.")
    point: Point3 | None = Field(default=None, description="The battery limit point, m.")
    rack: Id | None = Field(default=None, description="End the line at an end of this rack.")
    rack_end: Literal["start", "end", "nearest"] = Field(
        default="nearest",
        description="Which end of the rack: its first point, its last, or the one nearest the "
        "line's other end.",
    )

    @model_validator(mode="after")
    def _check(self) -> "BatteryLimit":
        if (self.point is None) == (self.rack is None):
            raise ValueError("a battery limit needs exactly one of point or rack")
        if not self.lines and not self.fluids:
            raise ValueError("a battery limit needs lines or fluids to match")
        return self


class VentRule(LayoutModel):
    """How high the open end of a vent or relief line rises, for the lines it matches (line
    number pattern, as ``battery_limits``, or fluid): at least ``rise_m`` above its stub, and
    with a ``radius_m`` (default: the largest radius of the zones ``layout/zones.yaml`` derives
    from the line) so high that a sphere of that radius around the outlet stays clear of every
    walking level (grade, structure floors, building floors and roofs) up to the walkway
    headroom above it; at most ``max_rise_m``."""

    lines: list[str] = Field(default_factory=list, description="Line number patterns.")
    fluids: list[str] = Field(default_factory=list, description="Fluid names, any case.")
    rise_m: float | None = Field(
        default=None, description="Least rise above the stub, m (default: vent_rise_m)."
    )
    radius_m: float | None = Field(
        default=None,
        description="Keep a sphere of this radius around the outlet off the walking levels, m "
        "(default: the line's zone radius; none: only rise_m).",
    )
    max_rise_m: float = Field(default=20.0, description="Highest rise above the stub, m.")

    @model_validator(mode="after")
    def _check(self) -> "VentRule":
        if not self.lines and not self.fluids:
            raise ValueError("a vent rule needs lines or fluids to match")
        for name in ("rise_m", "radius_m", "max_rise_m"):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        return self


def rack_reach(plan: "SitePlan | None", rules: "RoutingRules | None" = None) -> float:
    """How far a line's end may be from a rack centreline to be carried by it (m).

    The single value behind the pipe router and ``cheme.layout-line-route``: the site plan's
    ``rack_reach``, else the deprecated ``routing.yaml`` ``rules.rack_reach_m``, else the site
    plan's ``max_unsupported_length`` (default 30 m).
    """
    if plan is not None and plan.rack_reach is not None:
        return plan.rack_reach
    if rules is not None and rules.rack_reach_m is not None:
        return rules.rack_reach_m
    if plan is not None:
        return plan.max_unsupported_length
    return SitePlan.model_fields["max_unsupported_length"].default


class RoutingRules(LayoutModel):
    tiers: list[Tier] = Field(default_factory=list)
    local_max_m: float = Field(
        default=15.0,
        description="Ends further apart than this (in plan) go over the rack, m (ASSUMED).",
    )
    local_elevation_m: float = Field(
        default=3.5,
        description="Elevation of local runs in an area (the pipe-way above grade), m "
        "(ASSUMED; typically 3.0 .. 4.5).",
    )
    grade_max_m: float = Field(
        default=3.0,
        description="Ends closer than this (in plan) stay at their own elevation, m.",
    )
    rack_reach_m: float | None = Field(
        default=None,
        description="Deprecated: set rack_reach in layout/site-plan.yaml, which wins over this. "
        "How far an end may be from a rack centreline to be carried by it, m; one value for the "
        "router and cheme validate's line-route check (see rack_reach()).",
    )
    rack_detour_factor: float = Field(
        default=2.5,
        description="A line that only goes to the rack for its length stays local when the rack "
        "route is longer than this many times the plan distance.",
    )
    battery_limits: list[BatteryLimit] = Field(
        default_factory=list,
        description="Battery limit points per line pattern or fluid (default: the nearest rack "
        "end, then the site edge).",
    )
    spacing_m: float = Field(default=0.1, description="Clear gap between pipes, m (ASSUMED).")
    headroom_road_m: float = Field(default=6.0, description="Under pipes over roads, m.")
    headroom_walkway_m: float = Field(default=2.2, description="Over escape routes, m.")
    grid_m: float = Field(default=0.5, description="Router grid, m (0.25 .. 1).")
    rack_bent_spacing_m: float = Field(default=6.0, description="Rack bents, m (ASSUMED).")
    gravity_fluids: list[str] = Field(
        default_factory=list, description="Fluids that drain by gravity (fall checked)."
    )
    vent_rise_m: float = Field(
        default=1.0, description="Rise of an open vent or relief end above its stub, m."
    )
    vents: list[VentRule] = Field(
        default_factory=list,
        description="Riser heights of open vent and relief ends per line pattern or fluid (the "
        "first rule that matches).",
    )

    @model_validator(mode="after")
    def _check(self) -> "RoutingRules":
        if not 0.25 - 1e-9 <= self.grid_m <= 1.0 + 1e-9:
            raise ValueError(f"grid_m must be 0.25 .. 1, not {self.grid_m:g}")
        for name in (
            "headroom_road_m",
            "headroom_walkway_m",
            "rack_bent_spacing_m",
            "local_max_m",
            "local_elevation_m",
            "rack_detour_factor",
            "vent_rise_m",
        ):
            _positive(name, getattr(self, name))
        if self.rack_reach_m is not None:
            _positive("rack_reach_m", self.rack_reach_m)
        if self.spacing_m < 0:
            raise ValueError("spacing_m must not be negative")
        return self


class LineRouting(LayoutModel):
    """Routing intent for a line, or one segment of it (its DEXPI id or segment number, or
    ``<sheet stem>/<DEXPI id>`` where the same segment id appears on more than one sheet)."""

    line: Id
    segment: Id | None = Field(
        default=None,
        description=(
            "DEXPI segment id or number (S2); `<sheet stem>/<DEXPI id>` (the pipe id, e.g."
            " P-03/Line_A_S1) for one sheet's segment when the line has the same segment id"
            " on several sheets."
        ),
    )
    rack: Id | None = None
    tier: float | None = Field(default=None, description="Tier elevation on the rack, m.")
    via: list[Point3] = Field(default_factory=list, description="Points to pass, in order.")
    elevation: float | None = Field(default=None, description="Run at this elevation, m.")
    route: list[Point3] | None = Field(
        default=None, description="A pinned polyline (from `cheme layout pin`)."
    )
    skip: str | None = Field(default=None, description="Do not route it, for this reason.")
    gravity: bool = False
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "LineRouting":
        if self.route is not None and len(self.route) < 2:
            raise ValueError(f"{self.line}: route needs at least two points")
        if self.route is not None and self.segment is None:
            raise ValueError(f"{self.line}: a pinned route belongs to one segment")
        return self


OperatorKind = Literal["chainwheel", "extension_spindle", "remote_operator", "remote_mount"]


class Operator(LayoutModel):
    """How a valve or a transmitter out of reach is operated: a ``chainwheel`` (a handwheel
    valve in infrequent use), an ``extension_spindle`` or ``remote_operator`` (to a pedestal at
    a floor), or a transmitter's ``remote_mount`` (on ``impulse`` lines or a ``capillary`` to a
    stand at a floor). The rules on the model check it against the layout criteria."""

    item: Id = Field(
        description="The valve's or instrument's tag, an in-line item id (<sheet>/<DEXPI id>), "
        "or TAG/NOZZLE for a transmitter on an equipment tapping."
    )
    kind: OperatorKind
    use: Literal["infrequent", "regular"] = Field(
        default="regular",
        description="How often it is operated; a chain wheel needs infrequent.",
    )
    via: Literal["impulse", "capillary"] | None = Field(
        default=None, description="remote_mount: impulse lines (default) or a capillary seal."
    )
    length_m: float | None = Field(
        default=None,
        description="The spindle's, operator's or line's length, m (default: to the nearest "
        "floor).",
    )
    basis: str = Field(default="", description="Why, e.g. a DESIGN.md decision.")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "Operator":
        if self.length_m is not None:
            _positive("length_m", self.length_m)
        if self.via is not None and self.kind != "remote_mount":
            raise ValueError(f"{self.item}: via belongs to a remote_mount")
        return self


class Routing(LayoutModel, optional_schema("routing")):
    """How the router runs pipes: tier rules, spacing, headroom, and intent per line."""

    rules: RoutingRules = Field(default_factory=RoutingRules)
    lines: list[LineRouting] = Field(default_factory=list)
    operators: list[Operator] = Field(
        default_factory=list,
        description="Chain wheels, extension spindles, remote operators and remote-mounted "
        "transmitters for the valves and instruments out of reach.",
    )
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/crane-chart.yaml
# ---------------------------------------------------------------------------


class ChartRow(LayoutModel):
    """One line of a crane's load chart: the capacity at a working radius."""

    radius_m: float = Field(description="Working radius, m.")
    capacity_t: float = Field(description="Rated capacity at that radius, t.")

    @model_validator(mode="after")
    def _check(self) -> "ChartRow":
        _positive("radius_m", self.radius_m)
        _positive("capacity_t", self.capacity_t)
        return self


class CraneChart(LayoutModel):
    """The load chart of one crane in one configuration (boom, counterweight, outriggers), as
    its supplier gives it. The lifting study takes the capacity at the smallest tabulated
    radius at or beyond the lift's radius (no interpolation)."""

    id: Id
    title: str = ""
    source: str = Field(min_length=3, description="The chart's source: supplier, document, page.")
    status: Literal["QUOTED", "ASSUMED"] = Field(
        description="QUOTED: from the crane supplier for this job; ASSUMED: a typical chart."
    )
    configuration: str = Field(default="", description="Boom length, counterweight, outriggers.")
    pads: list[Id] = Field(
        default_factory=list, description="The crane_pad zones it stands on (empty: every pad)."
    )
    max_hook_height_m: float | None = Field(
        default=None, description="Highest hook height in this configuration, m."
    )
    chart: list[ChartRow] = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "CraneChart":
        radii = [row.radius_m for row in self.chart]
        if radii != sorted(radii) or len(set(radii)) != len(radii):
            raise ValueError(f"crane {self.id}: give the chart rows by increasing radius")
        if self.max_hook_height_m is not None:
            _positive("max_hook_height_m", self.max_hook_height_m)
        return self


class CraneCharts(LayoutModel, optional_schema("crane_chart")):
    """``layout/crane-chart.yaml`` (kind ``crane_chart``): the load charts of the cranes the
    project plans to lift its heavy items with."""

    cranes: list[CraneChart] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _unique(self) -> "CraneCharts":
        ids = [c.id for c in self.cranes]
        if len(set(ids)) != len(ids):
            raise ValueError("crane ids must be unique")
        return self


# ---------------------------------------------------------------------------
# electrical/tray-rules.yaml
# ---------------------------------------------------------------------------


class TrayTier(LayoutModel):
    """The tray tier of a rack: where its power and instrument trays run along it."""

    rack: Id
    elevation: float = Field(description="Bottom of the trays (top of their steel), m.")


class TrayRuleSet(LayoutModel):
    """How the cable trays are sized and run (every default ASSUMED: check it against the
    project's electrical standard)."""

    widths_mm: list[float] = Field(
        default_factory=lambda: [100.0, 150.0, 200.0, 300.0, 450.0, 600.0, 750.0, 900.0],
        description="Standard tray widths, mm, smallest first.",
    )
    depth_mm: float = Field(default=100.0, description="Usable depth (side rail height), mm.")
    fill_max_power: float = Field(
        default=0.3, description="Fill of a power tray's cross-section at most (cables apart)."
    )
    fill_max_instrument: float = Field(
        default=0.4, description="Fill of an instrument tray's cross-section at most."
    )
    separation_m: float = Field(
        default=0.3,
        description="Clear distance between a power and an instrument tray at least, m "
        "(e.g. EN 50174-2 without a metal divider).",
    )
    spacing_m: float = Field(
        default=0.15, description="Clear gap to pipes, steel, items and other trays, m."
    )
    tier_gap_m: float = Field(
        default=1.5,
        description="A rack without a tiers rule carries its trays this far above its top "
        "tier, on steel of their own, m.",
    )
    tiers: list[TrayTier] = Field(default_factory=list)
    lane_fraction: float = Field(
        default=0.25,
        description="Power trays run this fraction of the rack width to one side of its "
        "centreline, instrument trays to the other.",
    )
    entry_elevation_m: float = Field(
        default=3.0, description="Where cables leave a room without a point, m above grade."
    )
    branch_elevation_m: float = Field(
        default=3.0,
        description="A branch runs at least this high (above the walkway headroom) to above "
        "its load and drops onto it there, m.",
    )
    rack_reach_m: float = Field(
        default=50.0, description="A load farther than this from every rack is fed directly, m."
    )
    jb_elevation_m: float = Field(
        default=1.2, description="A proposed junction box's centre above grade, m."
    )
    jb_reach_m: float = Field(
        default=30.0, description="An instrument takes a declared junction box within this, m."
    )
    termination_m: float = Field(
        default=1.5, description="Cable added at each end for its gland and termination, m."
    )
    slack: float = Field(default=0.05, description="Cable added for sag and bends, fraction.")
    grid_m: float = Field(default=0.5, description="Router grid of the tray legs, m.")
    avoid_zones: list[str] = Field(
        default_factory=lambda: ["oxygen_enriched", "hazardous"],
        description="Zone kinds (layout/zones.yaml) a tray may not run in: a tray inside one is "
        "finding layout-tray-zone (cable sheath and glands for the zone, or another lane).",
    )
    support_span_m: float = Field(
        default=6.0,
        description="Longest tray run between supports (heavy-duty cable ladder on rack bents, "
        "ASSUMED): a longer level run with no steel is finding layout-tray-span, m.",
    )
    support_reach_m: float = Field(
        default=1.0,
        description="Steel this close to a tray (a hanger, a bracket off a column or wall) "
        "supports it, m.",
    )

    @model_validator(mode="after")
    def _check(self) -> "TrayRuleSet":
        if not self.widths_mm or any(w <= 0 for w in self.widths_mm):
            raise ValueError("widths_mm needs positive widths")
        if self.widths_mm != sorted(self.widths_mm):
            raise ValueError("widths_mm must be ascending")
        for name in (
            "depth_mm",
            "tier_gap_m",
            "entry_elevation_m",
            "branch_elevation_m",
            "rack_reach_m",
            "grid_m",
            "support_span_m",
            "support_reach_m",
        ):
            _positive(name, getattr(self, name))
        for name in ("fill_max_power", "fill_max_instrument", "lane_fraction"):
            value = getattr(self, name)
            if not 0 < value <= 1:
                raise ValueError(f"{name} must be in (0, 1], not {value:g}")
        if self.separation_m < 0 or self.spacing_m < 0 or self.slack < 0:
            raise ValueError("separation_m, spacing_m and slack must not be negative")
        if not 0.25 - 1e-9 <= self.grid_m <= 1.0 + 1e-9:
            raise ValueError(f"grid_m must be 0.25 .. 1, not {self.grid_m:g}")
        return self


class TrayRules(LayoutModel, optional_schema("trays")):
    """``electrical/tray-rules.yaml``: how the cable trays are sized and run."""

    rules: TrayRuleSet = Field(default_factory=TrayRuleSet)
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/hvac.yaml
# ---------------------------------------------------------------------------

DuctKind = Literal["main", "header", "intake", "exhaust"]


class HvacUnit(LayoutModel):
    """An air handling unit standing on a floor of a building: a box ``size`` [length, width,
    height] centred on ``position``, its length along x at ``rotation_deg`` 0, with four ports on
    its top (outdoor air, exhaust, return and supply air, in that order along its length)."""

    id: Id
    title: str = ""
    building: Id = Field(description="Id in layout/building.yaml.")
    level: Id | None = Field(
        default=None, description="Level it stands on (default: the building's lowest floor)."
    )
    position: Point = Field(description="Centre of the unit in plan [x, y], site m.")
    rotation_deg: Literal[0, 90, 180, 270] = 0
    size: tuple[float, float, float] = Field(
        default=(4.0, 2.0, 2.2), description="[length, width, height], m (ASSUMED default)."
    )
    capacity_m3h: float | None = Field(
        default=None, description="Supply air the unit delivers at most, m3/h (vendor data)."
    )
    intake: Id | None = Field(
        default=None, description="Opening id of its building that outdoor air comes in by."
    )
    exhaust: Id | None = Field(
        default=None, description="Opening id of its building that the extract air leaves by."
    )
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "HvacUnit":
        for name, value in zip(("length", "width", "height"), self.size, strict=True):
            _positive(name, value)
        if self.capacity_m3h is not None:
            _positive("capacity_m3h", self.capacity_m3h)
        return self


class HvacRoom(LayoutModel):
    """A ventilated room of a building: the whole building (or the plan ``extent``) on one
    level, its air changes per hour (or its supply ``flow_m3h``), the unit that serves it and,
    optionally, its supply and extract terminals in plan (else generated in rows)."""

    id: Id
    title: str = ""
    building: Id = Field(description="Id in layout/building.yaml.")
    level: Id | None = Field(
        default=None, description="Level of the room (default: the building's lowest floor)."
    )
    extent: tuple[float, float, float, float] | None = Field(
        default=None, description="[x0, y0, x1, y1] in plan, site m (default: the building)."
    )
    height: float | None = Field(
        default=None, description="Room height, m (default: the level's clear height)."
    )
    air_changes_per_h: float | None = Field(
        default=None, description="Supply air changes per hour (of the room's volume)."
    )
    flow_m3h: float | None = Field(
        default=None, description="Supply air, m3/h (instead of air_changes_per_h)."
    )
    extract_fraction: float = Field(
        default=1.0,
        description="Extract air over supply air (below 1: the room is kept above ambient "
        "pressure; 0: no extract ducts, the air leaves by louvres and doors).",
    )
    unit: Id = Field(description="Id of the air handling unit (units:) that serves it.")
    supply: list[Point] = Field(
        default_factory=list, description="Supply terminals [[x, y], ...] in duct order."
    )
    extract: list[Point] = Field(
        default_factory=list, description="Extract terminals [[x, y], ...] in duct order."
    )
    duct_elevation_m: float | None = Field(
        default=None,
        description="Centreline of the room's supply ducts, m above grade (default: under the "
        "ceiling, see rules); the extract ducts run below them by both mains' envelopes and the "
        "spacing.",
    )
    basis: str = Field(default="", description="Why these air changes (heat load, gas, code).")
    notes: str = ""

    @model_validator(mode="after")
    def _check(self) -> "HvacRoom":
        if (self.air_changes_per_h is None) == (self.flow_m3h is None):
            raise ValueError("give either air_changes_per_h or flow_m3h")
        for name in ("air_changes_per_h", "flow_m3h", "height"):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        if not 0 <= self.extract_fraction <= 2:
            raise ValueError(f"extract_fraction must be 0 .. 2, not {self.extract_fraction:g}")
        if self.extent is not None:
            x0, y0, x1, y1 = self.extent
            if x1 <= x0 or y1 <= y0:
                raise ValueError("extent must be [x0, y0, x1, y1] with x1 > x0 and y1 > y0")
        return self


class VelocityLimit(LayoutModel):
    """A plant's own air velocity limit for one kind of duct (or the louvres)."""

    max_m_s: float
    basis: str = ""

    @model_validator(mode="after")
    def _check(self) -> "VelocityLimit":
        _positive("max_m_s", self.max_m_s)
        return self


class HvacRuleSet(LayoutModel):
    """How the ducts are sized and run. Velocity limits, standard sides, the aspect ratio and
    the terminal size default to the package table ``data/duct-sizing.yaml`` (ASSUMED); every
    other default is ASSUMED too."""

    velocities: dict[Literal["main", "header", "intake", "exhaust", "louvre"], VelocityLimit] = (
        Field(default_factory=dict, description="Overrides of the package velocity limits.")
    )
    sides_mm: list[float] | None = Field(
        default=None, description="Standard duct sides, mm, smallest first."
    )
    max_aspect: float | None = Field(default=None, description="Width over height at most.")
    max_height_mm: float = Field(
        default=1000.0, description="Tallest duct (the depth of the ceiling space), mm."
    )
    terminal_max_m3h: float | None = Field(
        default=None, description="Air one terminal takes at most, m3/h."
    )
    terminal_pitch_m: float = Field(
        default=4.0, description="Generated terminals stand at least this far apart in a row, m."
    )
    louvre_free_area: float | None = Field(
        default=None, description="Free area of a louvre over its face, fraction."
    )
    ceiling_gap_m: float = Field(
        default=0.3,
        description="Clear gap from the top of the supply ducts to the ceiling (the roof, or "
        "the underside of a crane runway), m.",
    )
    spacing_m: float = Field(
        default=0.15, description="Clear gap to items, steel, pipes, trays and other ducts, m."
    )
    grid_m: float = Field(default=0.5, description="Router grid of the ducts, m.")

    @model_validator(mode="after")
    def _check(self) -> "HvacRuleSet":
        if self.sides_mm is not None:
            if not self.sides_mm or any(s <= 0 for s in self.sides_mm):
                raise ValueError("sides_mm needs positive sides")
            if self.sides_mm != sorted(self.sides_mm):
                raise ValueError("sides_mm must be ascending")
        for name in ("max_aspect", "terminal_max_m3h"):
            value = getattr(self, name)
            if value is not None:
                _positive(name, value)
        if self.max_aspect is not None and self.max_aspect < 1:
            raise ValueError("max_aspect must be at least 1")
        for name in ("max_height_mm", "terminal_pitch_m", "grid_m"):
            _positive(name, getattr(self, name))
        if self.louvre_free_area is not None and not 0 < self.louvre_free_area <= 1:
            raise ValueError("louvre_free_area must be in (0, 1]")
        if self.ceiling_gap_m < 0 or self.spacing_m < 0:
            raise ValueError("ceiling_gap_m and spacing_m must not be negative")
        if not 0.25 - 1e-9 <= self.grid_m <= 1.0 + 1e-9:
            raise ValueError(f"grid_m must be 0.25 .. 1, not {self.grid_m:g}")
        return self


class Hvac(LayoutModel, optional_schema("hvac")):
    """``layout/hvac.yaml``: the air handling units, the ventilated rooms and the duct rules."""

    rules: HvacRuleSet = Field(default_factory=HvacRuleSet)
    units: list[HvacUnit] = Field(default_factory=list)
    rooms: list[HvacRoom] = Field(default_factory=list)
    notes: str = ""


# ---------------------------------------------------------------------------
# layout/plant-model.yaml (generated by `cheme layout build`)
# ---------------------------------------------------------------------------

Vec3 = tuple[float, float, float]
#: Where an object of the model comes from: derived by the generator, declared in an input
#: file, or pinned (a generated object copied into an input file to keep it as it is).
ObjectSource = Literal["generated", "declared", "pinned"]


class ModelRefs(LayoutModel):
    """What a model object refers to: a tag, DEXPI id, sheet, input file, lines, segments."""

    tag: str | None = None
    dexpi: str | None = Field(default=None, description="DEXPI id on the sheet.")
    sheet: str | None = Field(default=None, description="Sheet file, e.g. pid/P-01.xml.")
    file: str | None = Field(default=None, description="Input file that declares it.")
    lines: list[str] | None = Field(default=None, description="Line numbers.")
    segments: list[str] | None = Field(default=None, description="DEXPI segment ids.")


class ModelObject(LayoutModel):
    """Every object of the model has an id, references and a source."""

    id: str
    refs: ModelRefs = Field(default_factory=ModelRefs)
    source: ObjectSource


class ModelPart(ModelObject):
    """A primitive: ``cylinder`` (start, end, radius), ``cone`` (start, end, radius at the
    start, radius_end), ``cap`` (half an ellipsoid: centre of its base, outward axis, radius,
    depth), ``box`` (centre, size in the item's frame, rotation_deg about z), ``sphere``
    (centre, radius), ``member`` (a steel section from start to end: profile [b, h], section
    name; the web is vertical for a horizontal member), ``annulus`` (a ring or ring sector:
    centre of its top face, inner radius, outer radius_end, thickness depth, arc_deg [from, to]
    ccw from east; no arc_deg: all round), ``torus`` (centre, axis normal to its plane,
    radius to the tube's centre line, tube; a sector from the unit ref over arc_deg ccw about
    the axis), ``frustum`` (an upright rectangular one: centre of the bottom face, size [dx,
    dy, height] of the bottom, size_end [dx, dy] of the top, rotation_deg about z). ``lod``:
    absent at every level of detail, 1 the envelope only (drawn from afar; the solid of the
    clash checks and the router), 2 detail only (drawn close up). Site frame, m."""

    kind: Literal[
        "cylinder", "cone", "cap", "box", "sphere", "member", "annulus", "torus", "frustum"
    ]
    material: str = Field(description="shell, steel, casing, motor, plates, fan, ...")
    start: Vec3 | None = None
    end: Vec3 | None = None
    radius: float | None = None
    radius_end: float | None = None
    centre: Vec3 | None = None
    axis: Vec3 | None = None
    depth: float | None = None
    size: Vec3 | None = None
    rotation_deg: float | None = None
    profile: tuple[float, float] | None = Field(default=None, description="[b, h] of a member, m.")
    section: str | None = Field(default=None, description="e.g. HEB300 (ASSUMED defaults).")
    arc_deg: tuple[float, float] | None = None
    tube: float | None = Field(default=None, description="Tube radius of a torus, m.")
    ref: Vec3 | None = Field(default=None, description="Where a torus sector starts (unit).")
    size_end: tuple[float, float] | None = Field(
        default=None, description="[dx, dy] of a frustum's top face, m."
    )
    lod: Literal[1, 2] | None = Field(
        default=None, description="1: envelope only; 2: detail only; absent: both."
    )


class ModelOperator(LayoutModel):
    """A declared operator of a valve or transmitter (``piping/routing.yaml`` operators)."""

    kind: str
    use: str | None = None
    via: str | None = None
    length_m: float | None = None
    basis: str | None = None


class ModelNozzle(ModelObject):
    """A nozzle: its point on the surface, outward unit direction and DN."""

    name: str = Field(description="SubTagName on the P&ID (N1), else its DEXPI id.")
    dn: int | float | None = Field(default=None, description="Nominal diameter, from DEXPI.")
    point: Vec3 = Field(description="Where the pipe connects: the face of the flange.")
    direction: Vec3
    base: Vec3 | None = Field(
        default=None, description="Where the nozzle's neck leaves the shell (absent: at point)."
    )
    basis: Literal["pid", "default", "override"] = Field(
        description="pid: from the side the P&ID draws it on; default: no drawn position; "
        "override: from the placement's nozzles."
    )
    side: Literal["top", "bottom", "left", "right"] | None = Field(
        default=None, description="Side of the symbol the P&ID draws it on."
    )
    operator: ModelOperator | None = Field(
        default=None, description="A declared remote mount of the transmitter at it."
    )


class ModelEnvelope(ModelObject):
    """A maintenance or access space to keep free: a box (centre, size in the item's frame,
    rotation_deg about z)."""

    kind: Literal["bundle_pull", "motor_removal", "access"]
    centre: Vec3
    size: Vec3
    rotation_deg: float


class ModelEquipment(ModelObject):
    """A placed item with its parts, nozzles and envelopes."""

    tag: str
    type: str | None = Field(default=None, description="DEXPI class from the equipment list.")
    family: str
    shape: Literal["box", "vertical_cylinder", "horizontal_cylinder", "sphere"]
    size_from: Literal["list", "placement", "default"]
    dimensions: dict[str, float | str] = Field(description="The sizes used, m.")
    position: Vec3
    rotation_deg: float
    mount: dict[str, str] | None = None
    plinth: float | None = Field(
        default=None, description="Height of the concrete plinth it stands on, m (declared)."
    )
    bbox: tuple[float, float, float, float, float, float] = Field(
        description="[x0, y0, z0, x1, y1, z1] after rotation."
    )
    parts: list[ModelPart] = Field(default_factory=list)
    nozzles: list[ModelNozzle] = Field(default_factory=list)
    envelopes: list[ModelEnvelope] = Field(default_factory=list)


class ModelSite(ModelObject):
    name: str = ""
    width: float
    depth: float


class ModelArea(ModelObject):
    title: str = ""
    box: tuple[float, float, float, float]
    kind: str
    wall_height: float | None = Field(default=None, description="A bund's walls, m.")
    parts: list[ModelPart] = Field(default_factory=list, description="A bund's walls.")


class ModelRoad(ModelObject):
    title: str = ""
    points: list[Point]
    width: float


class ModelRack(ModelObject):
    title: str = ""
    points: list[Point]
    width: float
    levels: list[float] = Field(default_factory=list)
    parts: list[ModelPart] = Field(default_factory=list, description="Bents: columns, beams.")
    ladders: list["ModelLadder"] = Field(
        default_factory=list, description="Access ladders (declared or proposed)."
    )
    intermediate_supports: dict[str, Any] | None = Field(
        default=None, description="The declared steel between the bents (in parts)."
    )
    bent_spacing_m: float | None = Field(
        default=None, description="The rack's own bent spacing as declared (absent: the rule's)."
    )


class ModelLevel(LayoutModel):
    id: str
    title: str = ""
    elevation: float
    height: float
    clear_height: float
    kind: str


class ModelBuilding(ModelObject):
    title: str = ""
    origin: Point
    width: float
    depth: float
    rotation_deg: float
    footprint: tuple[float, float, float, float]
    heights: tuple[float, float] = Field(description="Bottom and top elevation, m.")
    levels: list[ModelLevel] = Field(default_factory=list)
    frame: Frame | None = None
    walls: str | list[str] = "none"
    wall_material: str = "cladding"
    openings: list[dict[str, Any]] = Field(default_factory=list)
    crane: dict[str, Any] | None = None
    use: str | None = Field(default=None, description="The building spacing table key.")
    parts: list[ModelPart] = Field(
        default_factory=list, description="Wall panels, roof, doors, louvres, crane."
    )


class ModelStructureLevel(LayoutModel):
    id: str
    title: str = ""
    elevation: float
    kind: str
    extent: tuple[float, float, float, float] | None = None
    use: str | None = Field(default=None, description="regular or occasional.")
    source: ObjectSource | None = Field(
        default=None, description="generated: a platform proposed outside a casing."
    )
    review_needed: bool | None = None
    reason: str | None = Field(default=None, description="Why a platform was proposed.")
    serves: str | None = Field(
        default=None, description="The level inside the casing a proposed platform replaces."
    )


class ModelStair(ModelObject):
    from_: str = Field(alias="from")
    to: str
    side: str
    offset: float | None = None
    width: float
    flights: int
    out: float | None = Field(
        default=None, description="Its inner edge out from the side, m (0 at the side)."
    )
    box: tuple[float, float, float, float, float, float]
    parts: list[ModelPart] = Field(default_factory=list)
    review_needed: bool | None = None
    reason: str | None = Field(default=None, description="Why a stair was proposed.")

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


class ModelLadder(ModelObject):
    base: Vec3
    top: Vec3
    cage: bool
    parts: list[ModelPart] = Field(default_factory=list)
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None
    at: Point | None = Field(default=None, description="Frame coordinates (a structure's).")
    facing: str | None = None
    end: Literal["start", "end"] | None = Field(default=None, description="A rack ladder's end.")
    review_needed: bool | None = None
    reason: str | None = Field(default=None, description="Why a ladder was proposed.")

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)


ModelRack.model_rebuild()


class ModelStructure(ModelObject):
    """A steel frame: members, gratings, handrails (``parts``), stairs, ladders, walls."""

    title: str = ""
    origin: Point
    rotation_deg: float
    width: float
    depth: float
    footprint: tuple[float, float, float, float]
    height: float
    grid_x: list[float]
    grid_y: list[float]
    levels: list[ModelStructureLevel] = Field(default_factory=list)
    sections: dict[str, str | bool] = Field(default_factory=dict)
    parts: list[ModelPart] = Field(default_factory=list)
    stairs: list[ModelStair] = Field(default_factory=list)
    ladders: list[ModelLadder] = Field(default_factory=list)
    walls: list[ModelPart] = Field(default_factory=list)
    openings: list[dict[str, Any]] | None = Field(
        default=None, description="The enclosure's declared openings (the walls are cut)."
    )
    serves: list[str] | None = Field(
        default=None, description="The valves a valve access platform is for."
    )
    review_needed: bool | None = None
    reason: str | None = Field(default=None, description="Why a structure was proposed.")


class ModelPlatform(ModelObject):
    """An access platform around a vertical item, with its ladder."""

    tag: str
    kind: Literal["circular", "rectangular"]
    elevation: float = Field(description="Floor, m above grade.")
    item_elevation: float = Field(description="Floor above the item's bottom, m.")
    width: float
    arc_deg: tuple[float, float] | None = None
    review_needed: bool | None = None
    serves: list[str] | None = Field(default=None, description="Nozzles and valves it serves.")
    parts: list[ModelPart] = Field(default_factory=list)
    ladder: ModelLadder


class ModelStepOver(ModelObject):
    """A step-over proposed where a low pipe crosses a walkway: flights and a deck over it."""

    pipe: str = Field(description="The pipe it crosses.")
    walkway: str = Field(description="The escape zone or structure level it is on.")
    point: Vec3 = Field(description="The middle of the crossing at the walkway's floor.")
    height: float = Field(description="Its deck above the floor, m.")
    box: tuple[float, float, float, float, float, float]
    review_needed: bool | None = None
    parts: list[ModelPart] = Field(default_factory=list)


class ModelZoneVolume(LayoutModel):
    shape: Literal["box", "cylinder", "sphere"]
    source: ObjectSource
    box: tuple[float, float, float, float, float, float] | None = None
    centre: Vec3 | None = None
    radius: float | None = None
    height: float | None = None
    zone: int | None = None
    item: str | None = None
    source_kind: str | None = None
    release_grade: str | None = None
    substance_class: str | None = None
    basis: str | None = None
    status: str | None = None


class ModelZone(ModelObject):
    title: str = ""
    kind: str
    zone: int | None = None
    volumes: list[ModelZoneVolume] = Field(default_factory=list)
    basis: str | None = None


class ModelPipeEnd(Strict):
    """What a pipe's end connects to, for the connectivity rule."""

    kind: Literal["nozzle", "junction", "open", "item", "battery_limit", "line"] = Field(
        description="nozzle (ref: its id), junction (a tee, a connector pair or a component "
        "two segments share; ref: its key), open (a vent or relief outlet), item (a placed "
        "component; ref: its tag), battery_limit, line (on another line; ref: its number)."
    )
    ref: str | None = None


class ModelPipe(ModelObject):
    """A routed DEXPI segment: polyline of the pipe's axis, sizes, how it was routed."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    line: str
    segment: str = Field(description="DEXPI segment id.")
    segment_number: str | None = None
    dn: float
    od: float = Field(description="Outside diameter, m.")
    insulation_mm: float
    class_: dict[str, str] | None = Field(default=None, alias="class")
    fluid: str | None = None
    points: list[Vec3]
    length: float
    method: str = Field(
        description="astar, astar_coarse, astar_fine, rack, via, open, direct, pinned, ..."
    )
    racks: list[str] | None = None
    tier: float | None = None
    open_ends: list[Literal["start", "end"]] | None = None
    ends: list[ModelPipeEnd] | None = Field(
        default=None, description="What the start and the end connect to (absent in older models)."
    )
    review_needed: bool | None = None
    reason: str | None = Field(
        default=None, description="Why the router took this way (rack, local, ...)."
    )
    jacket: Literal["cold", "hot", "personnel"] | None = Field(
        default=None, description="The cladding of an insulated pipe (a rendering hint)."
    )


class ModelInline(ModelObject):
    """A piping component placed along a pipe."""

    kind: str
    dexpi_class: str
    tag: str | None = None
    point: Vec3
    direction: Vec3
    line: str
    segment: str
    pipe: str
    operator: ModelOperator | None = None
    parts: list[ModelPart] = Field(
        default_factory=list, description="Body, flanges and operator (detail)."
    )


class ModelSupport(ModelObject):
    """A pipe shoe or guide where a pipe rests on a steel member."""

    kind: Literal["shoe", "guide"]
    pipe: str
    on: str = Field(description="The steel member's part id.")
    point: Vec3 = Field(description="On the member's top, under the pipe's axis.")
    parts: list[ModelPart] = Field(default_factory=list)


class ModelSupportSteel(ModelObject):
    """Support steel under a pipe: declared in ``layout/structures.yaml`` (``pipe_supports``)
    or proposed where a level run spans farther than its table allows (``source: generated``,
    ``review_needed``; ``cheme layout pin <id>`` declares it)."""

    kind: Literal["t_post", "post", "stub"]
    at: Point
    top: float = Field(description="Top of steel, m.")
    base: float = Field(description="Its foot, m (0: grade).")
    width: float
    rotation_deg: float
    serves: list[str] = Field(default_factory=list, description="Pipe ids it carries.")
    review_needed: bool | None = None
    reason: str | None = None
    parts: list[ModelPart] = Field(default_factory=list)


class ModelOpening(LayoutModel):
    side: str
    offset: float
    width: float
    height: float
    sill: float
    kind: str = "opening"


class ModelPenetration(ModelObject):
    """Where a pipe passes a building or enclosure wall (or a building's roof) outside its
    declared openings, with the opening that would take it (a proposal to declare)."""

    owner: str = Field(description="The building or structure whose wall it is.")
    wall: str = Field(description="The wall panel's (or roof slab's) part id.")
    pipe: str
    point: Vec3 = Field(description="Where the pipe's axis meets the wall (mid-plane).")
    material: str = Field(description="The wall's material (cladding, casing, fire_wall, ...).")
    end_inside: bool = Field(description="The pipe has an end inside the owner (else: passes).")
    length: float | None = Field(
        default=None, description="How far the pipe's axis runs in the wall's plane, m."
    )
    opening: ModelOpening = Field(
        description="The proposed opening in the owner's frame (on ``side: roof`` in its plan "
        "frame: offset and width along its x, sill and height along its y; cannot be pinned)."
    )
    review_needed: bool | None = None
    reason: str | None = None


class ModelTrayTier(ModelObject):
    """A rack's tray tier above its pipe tiers: the steel that carries the trays."""

    rack: str
    elevation: float
    parts: list[ModelPart] = Field(default_factory=list)


class ModelTray(ModelObject):
    """A cable tray run: its centreline (bottom of the tray), width and depth, the cables in
    it and how full it is."""

    system: Literal["power", "instrument"]
    kind: Literal["trunk", "room", "branch", "link"]
    points: list[Vec3]
    width: float = Field(description="m.")
    depth: float = Field(description="m.")
    length: float
    cables: list[str] = Field(default_factory=list)
    fill: float = Field(description="Cable cross-section over the tray's, fraction.")
    fill_max: float
    rack: str | None = None
    method: str | None = Field(default=None, description="How a leg was routed (astar, ...).")
    review_needed: bool | None = None
    parts: list[ModelPart] = Field(default_factory=list)


class ModelJunctionBox(ModelObject):
    """A field junction box: the instruments whose cables end there."""

    tag: str
    point: Vec3
    area: str | None = None
    instruments: list[str] = Field(default_factory=list)
    room: str | None = None
    review_needed: bool | None = None
    parts: list[ModelPart] = Field(default_factory=list)


class ModelCable(ModelObject):
    """A cable of the schedule: from, to, type, the trays it runs in and its length."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    tag: str
    system: Literal["power", "instrument"]
    kind: Literal["motor", "feeder", "field", "multipair"]
    from_: str = Field(alias="from")
    to: str
    from_point: Vec3
    to_point: Vec3
    size: str
    od_mm: float
    count: int = 1
    voltage_v: float | None = None
    power_kw: float | None = None
    current_a: float | None = None
    pairs: int | None = None
    trays: list[str] = Field(default_factory=list)
    route_length: float = Field(description="Along its trays and drops, m.")
    length: float = Field(description="With terminations and slack, m.")
    basis: str | None = Field(default=None, description="Where size and power come from.")
    review_needed: bool | None = None
    reason: str | None = None


class ModelHvacUnit(ModelObject):
    """An air handling unit: its casing, where it stands, the air it moves and its ports."""

    title: str = ""
    building: str
    level: str | None = None
    position: Vec3 = Field(description="Centre of the unit's base, m.")
    size: Vec3 = Field(description="[length, width, height], m.")
    rotation_deg: float
    capacity_m3h: float | None = None
    supply_m3h: float = Field(description="Supply air of the rooms it serves, m3/h.")
    extract_m3h: float = Field(description="Extract air of the rooms it serves, m3/h.")
    intake: str | None = Field(default=None, description="The opening outdoor air comes in by.")
    exhaust: str | None = Field(default=None, description="The opening extract air leaves by.")
    ports: dict[str, Vec3] = Field(
        default_factory=dict, description="outdoor, exhaust, return, supply: top of each port."
    )
    parts: list[ModelPart] = Field(default_factory=list)


class ModelTerminal(LayoutModel):
    """A supply or extract terminal (grille, diffuser) on a header duct."""

    id: str
    system: Literal["supply", "extract"]
    point: Vec3 = Field(description="On the header's centreline, m.")
    flow_m3h: float
    source: ObjectSource
    parts: list[ModelPart] = Field(default_factory=list)


class ModelHvacRoom(ModelObject):
    """A ventilated room: its volume, the air changes asked for, the air that is supplied and
    extracted, and its terminals."""

    title: str = ""
    building: str
    level: str | None = None
    unit: str
    extent: tuple[float, float, float, float]
    floor: float = Field(description="Floor elevation, m.")
    height: float = Field(description="Room height, m.")
    volume_m3: float
    air_changes_per_h: float
    supply_m3h: float
    extract_m3h: float
    basis: str | None = None
    terminals: list[ModelTerminal] = Field(default_factory=list)


class ModelDuct(ModelObject):
    """A rectangular duct run of constant air flow: its centreline, width (across, horizontal)
    and height, the air it carries and its velocity against the limit of its kind."""

    system: Literal["supply", "extract", "outdoor", "exhaust"]
    kind: DuctKind
    unit: str
    room: str | None = Field(default=None, description="The room of its row (mains, headers).")
    serves: list[str] | None = Field(default=None, description="The rooms whose air it carries.")
    points: list[Vec3]
    width: float = Field(description="m.")
    height: float = Field(description="m.")
    flow_m3h: float
    velocity_m_s: float
    velocity_max_m_s: float
    length: float
    method: str | None = Field(default=None, description="How it was routed (astar, ...).")
    review_needed: bool | None = None
    reason: str | None = None
    parts: list[ModelPart] = Field(default_factory=list)


class ModelUnrouted(LayoutModel):
    line: str
    segment: str
    segment_number: str | None = None
    sheet: str
    reason: str


class ModelProvenance(LayoutModel):
    """What the model was built from and by."""

    generator: str
    generator_version: str
    generator_sha256: str = Field(description="SHA-256 of the generating modules.")
    sources: dict[str, str] = Field(description="sha256:<hex> of each input file, by path.")
    output_sha256: str = Field(description="SHA-256 of the model's content (canonical JSON).")


class LayoutModelFile(LayoutModel):
    """The 3D plant model that cheme layout build derives (layout/plant-model.yaml)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, populate_by_name=True)

    schema_: Literal["cheme/layout_model/v1"] = Field(alias="schema")
    kind: Literal["layout_model"]
    provenance: ModelProvenance
    units: Literal["m"] = "m"
    site: ModelSite | None = None
    areas: list[ModelArea] = Field(default_factory=list)
    roads: list[ModelRoad] = Field(default_factory=list)
    racks: list[ModelRack] = Field(default_factory=list)
    buildings: list[ModelBuilding] = Field(default_factory=list)
    equipment: list[ModelEquipment] = Field(default_factory=list)
    pipes: list[ModelPipe] = Field(default_factory=list, description="Pipe routes.")
    structures: list[ModelStructure] = Field(default_factory=list, description="Steel.")
    support_steel: list[ModelSupportSteel] = Field(
        default_factory=list, description="Posts and T-posts under pipes (declared, proposed)."
    )
    zones: list[ModelZone] = Field(default_factory=list, description="Zones.")
    platforms: list[ModelPlatform] = Field(default_factory=list)
    inline: list[ModelInline] = Field(default_factory=list, description="In-line items.")
    step_overs: list[ModelStepOver] = Field(
        default_factory=list, description="Step-overs proposed over low pipes."
    )
    supports: list[ModelSupport] = Field(
        default_factory=list, description="Pipe shoes and guides on the steel."
    )
    penetrations: list[ModelPenetration] = Field(
        default_factory=list, description="Pipes through walls outside the declared openings."
    )
    unrouted: list[ModelUnrouted] = Field(default_factory=list)
    routing: dict[str, Any] = Field(
        default_factory=dict, description="Router summary: counts, methods, rack fill."
    )
    tray_tiers: list[ModelTrayTier] | None = Field(
        default=None, description="Rack tray tiers on steel of their own (with an electrical list)."
    )
    trays: list[ModelTray] | None = Field(
        default=None, description="Cable trays (with an electrical list)."
    )
    junction_boxes: list[ModelJunctionBox] | None = None
    cables: list[ModelCable] | None = Field(default=None, description="The cable schedule.")
    cabling: dict[str, Any] | None = Field(
        default=None,
        description="Cabling summary: counts, the tray rules used, cables missing.",
    )
    hvac_units: list[ModelHvacUnit] | None = Field(
        default=None, description="Air handling units (with layout/hvac.yaml)."
    )
    hvac_rooms: list[ModelHvacRoom] | None = Field(
        default=None, description="Ventilated rooms with their terminals (with layout/hvac.yaml)."
    )
    ducts: list[ModelDuct] | None = Field(
        default=None, description="HVAC ducts (with layout/hvac.yaml)."
    )
    hvac: dict[str, Any] | None = Field(
        default=None, description="HVAC summary: counts, air flows, the limits used, missing."
    )


#: Schema of each layout file, by the key ``workspace.LAYOUT_FILES`` files it under.
LAYOUT_SCHEMAS = {
    "site_plan": SitePlan,
    "building": BuildingList,
    "placement": PlacementList,
    "structures": StructureList,
    "zones": ZoneList,
    "routing": Routing,
    "pipe_specs": PipeSpecs,
    "trays": TrayRules,
    "hvac": Hvac,
}
