"""Parametric 3D shapes of equipment, chosen by the DEXPI class of the equipment list ``type``.

Pure geometry: no files, no P&IDs, no randomness. Each item is a :class:`Body`, built in its own
frame and then turned about the vertical axis by ``rotation_deg`` (counterclockwise seen from
above) and moved to its ``position`` (centre of the footprint, bottom elevation), in metres.

**Own frame.** x is the item's main horizontal axis (a horizontal drum or exchanger lies along
it, a pump's shaft runs along it from the suction end at -x, the *front*, to the driver at +x,
the *back*), y is across, z is up from the item's bottom (z = 0).

**Sizes** are overall sizes (:class:`Dims`): a vertical item's ``height`` runs from the bottom
of its support to the top of its head, a horizontal item's ``length`` over both heads or
channels, and its optional ``height`` is the top of its shell above its bottom (saddles fill
the space below the shell). A box-like item is ``length`` x ``width`` x ``height``. The
:data:`FAMILIES` decide the parts inside that envelope: heads, skirt or legs, base plate,
casing and motor, plate pack, fans. The bounding box therefore never depends on the family,
only on the shape (``box``, ``vertical_cylinder``, ``horizontal_cylinder``, ``sphere``) and the
sizes, which keeps the layout rules simple.

**Parts** are primitives: ``cylinder`` (``start``, ``end``, ``radius``), ``cone`` (``start``,
``end``, ``radius`` at the start, ``radius_end``), ``cap`` (half an ellipsoid of revolution:
``centre`` on its base, ``axis`` pointing out, ``radius``, ``depth``), ``box`` (``centre``,
``size`` in the item's frame, ``rotation_deg``), ``sphere`` (``centre``, ``radius``), ``torus``
(``centre``, ``axis`` normal to its plane, ``radius`` to the tube's centre line, ``tube``; a
sector from the unit ``ref`` direction over ``arc_deg``), ``frustum`` (a rectangular one,
upright: ``centre`` of its bottom face, ``size`` [dx, dy, height] of the bottom and ``size_end``
[dx, dy] of the top, ``rotation_deg``) and ``annulus`` (a flat ring: ``centre`` of its top face,
``radius`` inner, ``radius_end`` outer, ``depth``). Each has a material hint (``shell``,
``steel``, ``motor``, ``casing``, ``plates``, ``fan``, ``concrete``, ``guard``, ``flange``,
``handrail``, ``grating``, ...).

**Level of detail.** A part's ``lod`` is None (drawn at every distance, and a solid for the
clash checks and the router), 1 (the envelope: a solid, drawn from afar only) or 2 (detail:
drawn close up only, never a solid). The detail stays inside or close to the envelope, so the
clash checks and the router see the same item whatever detail it carries; what stands well
outside it (a tank's stair, a column's top davit) is a solid of its own (``lod`` None). Items
at grade (``grade``) stand on concrete: machines on a plinth inside their envelope, everything
else on a foundation (detail) just below and around its supports.

**Families** with detail: an end-suction centrifugal pump (volute across the shaft, axial
suction and top tangential discharge flanges, bearing housing, coupling guard, motor with fan
cowl, cooling ribs, terminal box and feet, baseplate with drip rim on a plinth), a vertical
inline pump and a cryogenic pump (the end-suction pump with an insulated cold end), picked by
``dimensions.orientation`` and ``variant`` (:func:`variant_for`); an integrally geared compressor
(gearbox, stage volutes, intercoolers, motor, lube oil console), a compander or expander and a
blower; vessels and columns (base ring and anchor chairs, skirt opening, lifting lugs,
stiffening rings, manways with davits); shell-and-tube exchangers (bonnet, body flanges, saddle
feet), plate exchangers (tie bolts, carrying and guide bars), air coolers (plenum, fan rings,
blades, motors) and tanks (anchor chairs, ring wall, spiral stair with handrail, roof handrail
ring and roof platform). See :mod:`chemeascode.domains.spatial.shape_details`.

**Nozzles.** A machine's nozzles go on its real flanges (:attr:`Body.flanges`; the anchor's
``flange`` is True); :meth:`Body.anchor` turns a nozzle position into a point on the surface and the
outward direction: on a vertical shell ``angle_deg`` (ccw from the item's +x) and
``elevation`` (above the item's bottom); on a horizontal shell ``angle_deg`` about the axis
(0 top, 90 toward +y, 180 bottom) and ``along`` (from the front end); or a ``face`` (``top``,
``bottom``, ``north`` = +y, ``south`` = -y, ``east`` = +x, ``west`` = -x, ``front`` = -x,
``back`` = +x, all in the item's own frame) with an ``offset`` ``[u, v]`` from the face's
centre (top and bottom: u along x, v along y; a side: u along the face, v up).
:meth:`Body.pid_anchor` places a nozzle from where the P&ID draws it around the symbol.

**Envelopes** are maintenance spaces (``bundle_pull`` in front of a shell-and-tube exchanger,
as long as its tubes; ``motor_removal`` behind a pump or machine; ``access``, 1 m around a pump)
as boxes in the site frame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

Vec = tuple[float, float, float]

SHAPES = ("box", "vertical_cylinder", "horizontal_cylinder", "sphere")
FACES = ("top", "bottom", "north", "south", "east", "west", "front", "back")
#: Clear space kept around a pump for access, m.
PUMP_ACCESS = 1.0

#: The family of each DEXPI class (and of a few common names that are not DEXPI classes).
FAMILIES: dict[str, str] = {
    # vertical vessels and columns
    "Vessel": "vessel",
    "PressureVessel": "vessel",
    "VerticalVessel": "vessel",
    "Separator": "vessel",
    "GravitationalSeparator": "vessel",
    "MechanicalSeparator": "vessel",
    "ScrubbingSeparator": "vessel",
    "ElectricalSeparator": "vessel",
    "Silo": "vessel",
    "ProcessColumn": "column",
    "Column": "column",
    "TaggedColumnSection": "column",
    "Tank": "tank",
    "StorageTank": "tank",
    "HorizontalVessel": "horizontal_vessel",
    # heat exchangers
    "TubularHeatExchanger": "shell_tube",
    "ShellAndTubeHeatExchanger": "shell_tube",
    "PlateHeatExchanger": "plate_exchanger",
    "SpiralHeatExchanger": "plate_exchanger",
    "AirCoolingSystem": "air_cooler",
    "DryCoolingTower": "air_cooler",
    # machines
    "Pump": "pump",
    "CentrifugalPump": "pump",
    "ReciprocatingPump": "pump",
    "RotaryPump": "pump",
    "Compressor": "compressor",
    "CentrifugalCompressor": "compressor",
    "AxialCompressor": "compressor",
    "ReciprocatingCompressor": "compressor",
    "RotaryCompressor": "compressor",
    "Blower": "compressor",
    "AxialBlower": "compressor",
    "CentrifugalBlower": "compressor",
    "Fan": "compressor",
    "AxialFan": "compressor",
    "RadialFan": "compressor",
    "Turbine": "turbine",
    "GasTurbine": "turbine",
    "SteamTurbine": "turbine",
    # filters, silencers, stacks
    "Filter": "filter",
    "GasFilter": "filter",
    "LiquidFilter": "filter",
    "Silencer": "silencer",
    "Stack": "stack",
    "Chimney": "stack",
    "Flare": "stack",
    "WasteGasEmitter": "stack",
}
#: Name endings that pick a family for a class not in :data:`FAMILIES`.
_SUFFIXES = (
    ("Pump", "pump"),
    ("Compressor", "compressor"),
    ("Blower", "compressor"),
    ("Fan", "compressor"),
    ("Turbine", "turbine"),
    ("Filter", "filter"),
    ("Column", "column"),
    ("Tank", "tank"),
    ("Vessel", "vessel"),
    ("Separator", "vessel"),
    ("Silencer", "silencer"),
)

#: The shape a family takes when the dimensions do not say.
_NATURAL = {
    "vessel": "vertical_cylinder",
    "column": "vertical_cylinder",
    "tank": "vertical_cylinder",
    "filter": "vertical_cylinder",
    "silencer": "vertical_cylinder",
    "stack": "vertical_cylinder",
    "horizontal_vessel": "horizontal_cylinder",
    "shell_tube": "horizontal_cylinder",
}
#: Which shapes each family can draw; any other shape falls back to the plain ``generic`` one.
_SUPPORTS = {
    "vessel": {"vertical_cylinder", "horizontal_cylinder"},
    "column": {"vertical_cylinder"},
    "tank": {"vertical_cylinder", "horizontal_cylinder"},
    "filter": {"vertical_cylinder", "horizontal_cylinder"},
    "silencer": {"vertical_cylinder", "horizontal_cylinder"},
    "stack": {"vertical_cylinder"},
    "horizontal_vessel": {"horizontal_cylinder", "vertical_cylinder"},
    "shell_tube": {"horizontal_cylinder", "vertical_cylinder"},
    "plate_exchanger": {"box"},
    "air_cooler": {"box"},
    "pump": {"box"},
    "compressor": {"box"},
    "turbine": {"box"},
}


@dataclass(frozen=True)
class Dims:
    """Overall sizes in metres (see the module text); None where not given. ``orientation``
    (``horizontal``, ``vertical``) and ``variant`` pick the variant of a machine family."""

    diameter: float | None = None
    height: float | None = None
    length: float | None = None
    width: float | None = None
    head: str | None = None
    support: str | None = None
    orientation: str | None = None
    variant: str | None = None


#: The variants of each machine family, the first the default (:func:`variant_for`).
VARIANTS: dict[str, tuple[str, ...]] = {
    "pump": ("end_suction", "vertical_inline", "cryogenic"),
    "compressor": ("integrally_geared", "blower", "machine"),
    "turbine": ("compander", "expander", "machine"),
}
#: DEXPI classes (or name parts) that pick a variant.
_CLASS_VARIANTS = (
    ("Blower", "blower"),
    ("Fan", "blower"),
    ("AxialCompressor", "machine"),
    ("ReciprocatingCompressor", "machine"),
    ("RotaryCompressor", "machine"),
    ("SteamTurbine", "machine"),
    ("GasTurbine", "machine"),
    ("Expander", "expander"),
)


def variant_for(family: str, type_name: str | None, dims: Dims | None) -> str | None:
    """The variant of a machine *family*: ``dims.variant`` when it is one of the family's,
    else ``vertical_inline`` for a pump with ``orientation: vertical``, else by the DEXPI
    class (a blower or fan, an axial, reciprocating or rotary compressor, a steam or gas turbine
    as a plain machine), else the family's first. None for other families."""
    known = VARIANTS.get(family)
    if known is None:
        return None
    if dims is not None and dims.variant in known:
        return dims.variant
    if family == "pump" and dims is not None and dims.orientation == "vertical":
        return "vertical_inline"
    name = (type_name or "").strip().rsplit(".", 1)[-1]
    for part, variant in _CLASS_VARIANTS:
        if part in name and variant in known:
            return variant
    return known[0]


#: Sizes assumed for a family when neither the equipment list nor the placement gives any.
DEFAULT_DIMS: dict[str, Dims] = {
    "vessel": Dims(diameter=2.0, height=6.0),
    "column": Dims(diameter=2.0, height=20.0),
    "tank": Dims(diameter=6.0, height=8.0),
    "horizontal_vessel": Dims(diameter=2.0, length=6.0),
    "shell_tube": Dims(diameter=0.8, length=5.0),
    "plate_exchanger": Dims(length=1.5, width=0.8, height=1.8),
    "air_cooler": Dims(length=8.0, width=4.0, height=5.0),
    "pump": Dims(length=1.8, width=0.8, height=1.0),
    "compressor": Dims(length=6.0, width=3.0, height=3.0),
    "turbine": Dims(length=3.0, width=2.0, height=2.0),
    "filter": Dims(diameter=1.0, height=2.5),
    "silencer": Dims(diameter=1.0, height=3.0),
    "stack": Dims(diameter=1.0, height=15.0),
    "generic": Dims(length=1.0, width=1.0, height=1.0),
}


def family_for(type_name: str | None) -> str:
    """The family of a DEXPI class name: from :data:`FAMILIES`, else by its ending, else
    ``generic`` (a plain box or cylinder)."""
    name = (type_name or "").strip().rsplit(".", 1)[-1]
    if name in FAMILIES:
        return FAMILIES[name]
    for suffix, family in _SUFFIXES:
        if name.endswith(suffix):
            return family
    return "generic"


def shape_of(family: str, dims: Dims | None, override: str | None = None) -> str:
    """The shape of an item: *override*, else what the sizes say (a diameter with a height:
    vertical, with a length: horizontal, alone: a sphere; no diameter: a box), else the
    family's natural shape."""
    if override is not None:
        return override
    if dims is not None:
        if dims.diameter is not None:
            if dims.height is not None and dims.length is None:
                return "vertical_cylinder"
            if dims.length is not None:
                return "horizontal_cylinder"
            return "sphere" if family == "generic" else _NATURAL.get(family, "vertical_cylinder")
        if dims.length is not None or dims.width is not None or dims.height is not None:
            return "box"
    return _NATURAL.get(family, "box")


def _complete(family: str, shape: str, dims: Dims | None) -> Dims:
    """*dims* with every size *shape* needs, missing ones from the family's defaults."""
    given = dims or Dims()
    default = DEFAULT_DIMS.get(family, DEFAULT_DIMS["generic"])
    base = DEFAULT_DIMS["generic"]

    def pick(*values: float | None) -> float:
        return next(v for v in values if v is not None)

    if shape == "box":
        return replace(
            given,
            length=pick(given.length, given.diameter, default.length, default.diameter, 1.0),
            width=pick(given.width, given.diameter, default.width, default.diameter, 1.0),
            height=pick(given.height, default.height, base.height),
        )
    diameter = pick(given.diameter, given.width, default.diameter, default.width, 1.0)
    if shape == "sphere":
        return replace(given, diameter=diameter)
    if shape == "vertical_cylinder":
        return replace(
            given,
            diameter=diameter,
            height=pick(given.height, given.length, default.height, default.length, diameter),
        )
    return replace(
        given,
        diameter=diameter,
        length=pick(given.length, default.length, default.height, 3 * diameter),
    )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Part:
    """A primitive of a body: see the module text for what each kind uses."""

    id: str
    kind: str  # cylinder, cone, cap, box, sphere, torus, frustum, annulus
    material: str
    start: Vec | None = None
    end: Vec | None = None
    radius: float | None = None
    radius_end: float | None = None
    centre: Vec | None = None
    axis: Vec | None = None
    depth: float | None = None
    size: Vec | None = None
    rotation_deg: float | None = None
    tube: float | None = None
    ref: Vec | None = None
    arc_deg: tuple[float, float] | None = None
    size_end: tuple[float, float] | None = None
    #: None: every level of detail; 1: the envelope only; 2: detail only.
    lod: int | None = None


@dataclass(frozen=True)
class Envelope:
    """A maintenance or access space: a box in the site frame."""

    id: str
    kind: str  # bundle_pull, motor_removal, access
    centre: Vec
    size: Vec
    rotation_deg: float


@dataclass(frozen=True)
class Anchor:
    """A nozzle's point on the surface and its outward unit direction, site frame; ``flange``:
    the point is the face of a real flange of the body (a machine's), not the bare shell."""

    point: Vec
    direction: Vec
    flange: bool = False


def _cyl(pid: str, a: Vec, b: Vec, r: float, material: str, lod: int | None = None) -> Part:
    return Part(pid, "cylinder", material, start=a, end=b, radius=r, lod=lod)


def _cap(
    pid: str,
    c: Vec,
    axis: Vec,
    r: float,
    depth: float,
    material: str = "shell",
    lod: int | None = None,
) -> Part:
    return Part(pid, "cap", material, centre=c, axis=axis, radius=r, depth=depth, lod=lod)


def _box(
    pid: str, c: Vec, size: Vec, material: str, lod: int | None = None, rotation: float = 0.0
) -> Part:
    return Part(pid, "box", material, centre=c, size=size, rotation_deg=rotation, lod=lod)


def _head_depth(head: str | None, diameter: float) -> float:
    """Depth of a head of *diameter*: 2:1 ellipsoidal D/4, hemispherical D/2, torispherical
    about D/5, a cone (60 degrees) about D/3, flat 0."""
    return {
        "ellipsoidal_2_1": diameter / 4,
        "hemispherical": diameter / 2,
        "torispherical": diameter / 5,
        "cone": diameter / 3,
        "flat": 0.0,
        "cone_roof": diameter / 2 * math.tan(math.radians(10)),
        "dome_roof": diameter * 0.15,
    }.get(head or "ellipsoidal_2_1", diameter / 4)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Bodies
# ---------------------------------------------------------------------------


@dataclass
class Body:
    """One placed item: its parts, envelopes and nozzle anchors (see the module text)."""

    family: str
    shape: str
    dims: Dims
    position: Vec
    rotation_deg: float
    #: Parts, envelopes and the shell geometry in the item's own frame.
    local_parts: list[Part] = field(default_factory=list)
    local_envelopes: list[tuple[str, Vec, Vec]] = field(default_factory=list)
    #: z of the bottom and top of the cylindrical shell (vertical), or of the shell axis
    #: (horizontal: ``shell_bottom`` is the axis height); x of the tangent lines (horizontal).
    shell_bottom: float = 0.0
    shell_top: float = 0.0
    tangent: tuple[float, float] = (0.0, 0.0)
    #: x of the bases of the front and back heads (horizontal; a channel's flat cover).
    ends: tuple[float, float] = (0.0, 0.0)
    head_depths: tuple[float, float] = (0.0, 0.0)  # bottom/front, top/back
    #: For pumps and machines: the shaft axis height and the casing's x range and radius.
    casing: tuple[float, float, float, float] | None = None
    #: The machine variant (:data:`VARIANTS`), None for other families.
    variant: str | None = None
    #: Stands at grade (on concrete: a plinth or a foundation).
    grade: bool = False
    #: Height of a declared concrete plinth under the item (its bottom on the plinth's top).
    plinth: float = 0.0
    #: A machine's real flanges in its own frame: name -> (face centre, outward direction).
    #: ``inlet-<k>`` and ``outlet-<k>`` in order; ``suction``/``discharge`` for a pump.
    flanges: dict[str, tuple[Vec, Vec]] = field(default_factory=dict)

    # -- frame ----------------------------------------------------------------------------

    @property
    def extent(self) -> Vec:
        """``(dx, dy, dz)`` in the item's own frame."""
        d = self.dims
        if self.shape == "box":
            return (d.length or 0.0, d.width or 0.0, d.height or 0.0)
        diameter = d.diameter or 0.0
        if self.shape == "vertical_cylinder":
            return (diameter, diameter, d.height or 0.0)
        if self.shape == "horizontal_cylinder":  # the axis height plus the radius
            return (d.length or 0.0, diameter, self.shell_bottom + diameter / 2)
        return (diameter, diameter, diameter)

    def to_site(self, p: Vec) -> Vec:
        a = math.radians(self.rotation_deg)
        c, s = math.cos(a), math.sin(a)
        x, y, z = self.position
        return (x + p[0] * c - p[1] * s, y + p[0] * s + p[1] * c, z + p[2])

    def turn(self, v: Vec) -> Vec:
        a = math.radians(self.rotation_deg)
        c, s = math.cos(a), math.sin(a)
        return (v[0] * c - v[1] * s, v[0] * s + v[1] * c, v[2])

    def bbox(self) -> tuple[float, float, float, float, float, float]:
        """The axis-aligned box around the item after rotation (round in plan: not grown)."""
        dx, dy, dz = self.extent
        if self.shape in ("vertical_cylinder", "sphere"):
            hx, hy = dx / 2, dy / 2
        else:
            a = math.radians(self.rotation_deg)
            c, s = abs(math.cos(a)), abs(math.sin(a))
            hx, hy = (dx * c + dy * s) / 2, (dx * s + dy * c) / 2
        x, y, z = self.position
        return (x - hx, y - hy, z, x + hx, y + hy, z + dz)

    # -- parts ----------------------------------------------------------------------------

    def parts(self) -> list[Part]:
        """The parts in the site frame."""
        found = []
        for part in self.local_parts:
            moved = {}
            for name in ("start", "end", "centre"):
                value = getattr(part, name)
                if value is not None:
                    moved[name] = self.to_site(value)
            for name in ("axis", "ref"):
                value = getattr(part, name)
                if value is not None:
                    moved[name] = self.turn(value)
            if part.kind == "annulus" and part.arc_deg is not None:
                moved["arc_deg"] = tuple((a + self.rotation_deg) % 360 for a in part.arc_deg)
            if part.rotation_deg is not None:
                moved["rotation_deg"] = (part.rotation_deg + self.rotation_deg) % 360
            found.append(replace(part, **moved))
        return found

    def envelopes(self) -> list[Envelope]:
        return [
            Envelope(f"{kind}", kind, self.to_site(c), size, self.rotation_deg % 360)
            for kind, c, size in self.local_envelopes
        ]

    # -- nozzles ----------------------------------------------------------------------------

    def _out(self, p: Vec, d: Vec) -> Anchor:
        return Anchor(self.to_site(p), self.turn(d))

    def anchor(
        self,
        angle_deg: float | None = None,
        elevation: float | None = None,
        along: float | None = None,
        face: str | None = None,
        offset: tuple[float, float] = (0.0, 0.0),
    ) -> Anchor:
        """A nozzle's point and outward direction (see the module text)."""
        if face is not None:
            return self._face(face, offset)
        angle = angle_deg or 0.0
        a = math.radians(angle)
        r = (self.dims.diameter or 0.0) / 2
        if self.shape == "vertical_cylinder":
            h = self.dims.height or 0.0
            z = _clamp(elevation if elevation is not None else h / 2, 0.0, h)
            return self._out((r * math.cos(a), r * math.sin(a), z), (math.cos(a), math.sin(a), 0))
        if self.shape == "horizontal_cylinder":
            length = self.dims.length or 0.0
            x = _clamp(along if along is not None else length / 2, 0.0, length) - length / 2
            zc = self.shell_bottom
            return self._out(
                (x, r * math.sin(a), zc + r * math.cos(a)), (0.0, math.sin(a), math.cos(a))
            )
        if self.shape == "sphere":
            z = elevation if elevation is not None else r
            h = _clamp(z - r, -r, r)
            ring = math.sqrt(max(r * r - h * h, 0.0))
            p = (ring * math.cos(a), ring * math.sin(a), r + h)
            return self._out(p, _unit((p[0], p[1], h)))
        # a box: the ray from the axis at angle_deg, to the side it meets
        dx, dy, dz = self.extent
        z = _clamp(elevation if elevation is not None else dz / 2, 0.0, dz)
        c, s = math.cos(a), math.sin(a)
        tx = (dx / 2) / abs(c) if abs(c) > 1e-9 else math.inf
        ty = (dy / 2) / abs(s) if abs(s) > 1e-9 else math.inf
        t = min(tx, ty)
        if tx <= ty:
            normal: Vec = (math.copysign(1.0, c), 0.0, 0.0)
        else:
            normal = (0.0, math.copysign(1.0, s), 0.0)
        return self._out((t * c, t * s, z), normal)

    def _face(self, face: str, offset: tuple[float, float]) -> Anchor:
        u, v = offset
        dx, dy, dz = self.extent
        r = (self.dims.diameter or 0.0) / 2
        if face not in FACES:
            raise ValueError(f"unknown face {face!r}; one of {', '.join(FACES)}")
        side = {"front": "west", "back": "east"}.get(face, face)
        if self.shape == "vertical_cylinder":
            if side in ("top", "bottom"):
                rho = math.hypot(u, v)
                if rho > r:
                    u, v = u * r / rho, v * r / rho
                    rho = r
                if side == "top":
                    depth = self.head_depths[1]
                    base = self.shell_top
                    z = base + depth * math.sqrt(max(1 - (rho / r) ** 2, 0.0)) if r else base
                    if self.family == "tank" and self.dims.head == "cone_roof":
                        z = base + depth * (1 - rho / r) if r else base
                    return self._out((u, v, z), (0.0, 0.0, 1.0))
                depth = self.head_depths[0]
                base = self.shell_bottom
                z = base - depth * math.sqrt(max(1 - (rho / r) ** 2, 0.0)) if r else base
                return self._out((u, v, z), (0.0, 0.0, -1.0))
            angle = {"east": 0.0, "north": 90.0, "west": 180.0, "south": 270.0}[side]
            angle += math.degrees(u / r) if r else 0.0
            middle = (self.shell_bottom + self.shell_top) / 2
            return self.anchor(angle_deg=angle, elevation=middle + v)
        if self.shape == "horizontal_cylinder":
            length = self.dims.length or 0.0
            zc = self.shell_bottom
            if side in ("east", "west"):
                sign = 1.0 if side == "east" else -1.0
                rho = math.hypot(u, v)
                if rho > r:
                    u, v = u * r / rho, v * r / rho
                    rho = r
                depth = self.head_depths[1 if sign > 0 else 0]
                end = self.ends[1] if sign > 0 else self.ends[0]
                x = end + sign * depth * math.sqrt(max(1 - (rho / r) ** 2, 0.0)) if r else end
                return self._out((x, u, zc + v), (sign, 0.0, 0.0))
            angle = {"top": 0.0, "north": 90.0, "bottom": 180.0, "south": 270.0}[side]
            if side in ("top", "bottom"):
                angle += math.degrees(v / r) if r else 0.0
                return self.anchor(angle_deg=angle, along=length / 2 + u)
            angle += math.degrees(v / r) * (1 if side == "south" else -1) if r else 0.0
            return self.anchor(angle_deg=angle, along=length / 2 + u)
        if self.shape == "sphere":
            angle = {"east": 0.0, "north": 90.0, "west": 180.0, "south": 270.0}.get(side, 0.0)
            elevation = {"top": 2 * r, "bottom": 0.0}.get(side, r + v)
            return self.anchor(angle_deg=angle, elevation=elevation)
        hx, hy = dx / 2, dy / 2
        u_, v_ = u, v
        if side == "top":
            return self._out((_clamp(u_, -hx, hx), _clamp(v_, -hy, hy), dz), (0.0, 0.0, 1.0))
        if side == "bottom":
            return self._out((_clamp(u_, -hx, hx), _clamp(v_, -hy, hy), 0.0), (0.0, 0.0, -1.0))
        z = _clamp(dz / 2 + v_, 0.0, dz)
        if side in ("east", "west"):
            sign = 1.0 if side == "east" else -1.0
            return self._out((sign * hx, _clamp(u_, -hy, hy), z), (sign, 0.0, 0.0))
        sign = 1.0 if side == "north" else -1.0
        return self._out((_clamp(u_, -hx, hx), sign * hy, z), (0.0, sign, 0.0))

    def pid_anchor(self, side: str, u: float, v: float, spread: int = 0) -> Anchor:
        """Where a nozzle drawn on *side* (``top``, ``bottom``, ``left``, ``right`` of the
        symbol) at *u*, *v* goes: *u* is its position left to right across the symbol, *v* top
        to bottom, both scaled to -1..1 (sheet axes: x right, y down). *spread* (0, 1, 2, ...)
        moves the k-th nozzle at the same spot aside so that two never coincide."""
        u = _clamp(u, -1.0, 1.0)
        v = _clamp(v, -1.0, 1.0)
        shift = (0.0, 1.0, -1.0, 2.0, -2.0, 3.0, -3.0)[spread % 7] if spread else 0.0
        r = (self.dims.diameter or 0.0) / 2
        if self.flanges:
            return self._machine_anchor(side, abs(round(shift)))
        if self.shape == "vertical_cylinder":
            if side == "bottom" and self.shell_bottom <= 1e-9:
                # a flat bottom on its foundation: the nozzle leaves the shell just above it
                angle = (180.0 if u < 0 else 0.0 if u > 0 else 270.0) + 25.0 * shift
                height = min(0.5, 0.1 * (self.dims.height or 0.0))
                return self.anchor(angle_deg=angle, elevation=height)
            if side in ("top", "bottom"):
                return self._face(side, (0.6 * r * u, 0.35 * r * shift))
            elevation = self.shell_bottom + (1 - (v + 1) / 2) * (self.shell_top - self.shell_bottom)
            angle = (180.0 if side == "left" else 0.0) + 25.0 * shift
            return self.anchor(angle_deg=angle, elevation=elevation)
        if self.shape == "horizontal_cylinder":
            x0, x1 = self.tangent
            length = self.dims.length or 0.0
            span = x1 - x0
            if side in ("left", "right"):
                face = "front" if side == "left" else "back"
                return self._face(face, (0.35 * r * shift, -0.5 * r * v))
            along = (x0 + (u + 1) / 2 * span) + length / 2 + 0.3 * shift
            return self.anchor(angle_deg=0.0 if side == "top" else 180.0, along=along)
        if self.shape == "sphere":
            return self._face({"left": "west", "right": "east"}.get(side, side), (0.0, -r * v))
        dx, dy, dz = self.extent
        if side in ("top", "bottom"):
            return self._face(side, (0.4 * dx * u, 0.3 * dy * shift / 3))
        return self._face(
            "west" if side == "left" else "east", (0.3 * dy * shift / 3, -0.4 * dz * v)
        )

    def _machine_anchor(self, side: str, k: int) -> Anchor:
        """A machine nozzle drawn on *side*, the *k*-th at that spot: left on the inlets
        (a pump's suction), right and top on the outlets (its discharge), bottom on a drain;
        a nozzle beyond the flanges goes on top of the casing, spread along the shaft."""
        inlets = [v for n, v in self.flanges.items() if n == "suction" or n.startswith("inlet")]
        outlets = [v for n, v in self.flanges.items() if n == "discharge" or n.startswith("outlet")]
        if side == "bottom" and "drain" in self.flanges:
            point, direction = self.flanges["drain"]
            return Anchor(self.to_site(point), self.turn(direction), True)
        found = inlets if side == "left" else outlets
        if k < len(found):
            point, direction = found[k]
            return Anchor(self.to_site(point), self.turn(direction), True)
        axis_z, x0, x1, radius = self.casing or (self.extent[2] / 2, 0.0, 0.0, 0.1)
        step = (k - len(found) + 1) * 0.3 * radius
        x = _clamp((x0 + x1) / 2 + (step if side != "left" else -step), x0, x1)
        if side == "bottom":
            return self._out((x, 0.0, axis_z - radius), (0.0, 0.0, -1.0))
        return self._out((x, 0.0, axis_z + radius), (0.0, 0.0, 1.0))

    def default_anchor(self, index: int, count: int) -> Anchor:
        """Where the *index*-th of *count* nozzles goes when nothing says where."""
        fraction = (index + 1) / (count + 1)
        if self.flanges:
            return self._machine_anchor("left" if index == 0 else "top", max(index - 1, 0))
        if self.shape == "vertical_cylinder":
            elevation = self.shell_bottom + fraction * (self.shell_top - self.shell_bottom)
            return self.anchor(angle_deg=90.0 * index, elevation=elevation)
        if self.shape == "horizontal_cylinder":
            x0, x1 = self.tangent
            along = x0 + fraction * (x1 - x0) + (self.dims.length or 0.0) / 2
            return self.anchor(angle_deg=0.0, along=along)
        if self.shape == "sphere":
            return self.anchor(angle_deg=90.0 * index, elevation=(self.dims.diameter or 0) / 2)
        dx = self.extent[0]
        return self._face("top", ((fraction - 0.5) * dx, 0.0))


def _unit(v: Vec) -> Vec:
    n = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    return (v[0] / n, v[1] / n, v[2] / n) if n > 1e-12 else (0.0, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------


def body(
    family: str,
    dims: Dims | None,
    position: Vec = (0.0, 0.0, 0.0),
    rotation_deg: float = 0.0,
    shape: str | None = None,
    bundle_length: float | None = None,
    type_name: str | None = None,
    grade: bool | None = None,
    detail: bool = True,
    plinth: float = 0.0,
) -> Body:
    """The :class:`Body` of an item of *family* with sizes *dims* (missing sizes from
    :data:`DEFAULT_DIMS`), standing at *position*, turned by *rotation_deg*. *shape* overrides
    the shape the sizes give; a family that cannot draw that shape is drawn ``generic``.
    *bundle_length*: tube length of a shell-and-tube exchanger, for its bundle-pull envelope
    (default 85 % of its length). *type_name* (the DEXPI class) and the sizes pick a machine's
    variant (:func:`variant_for`); *grade*: the item stands at grade (default: its bottom is
    at 0); *detail*: add the level-2 detail parts; *plinth*: the height of a concrete plinth the
    item stands on (drawn as a solid under its footprint, 0.1 m wider)."""
    shape = shape_of(family, dims, shape)
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape!r}; one of {', '.join(SHAPES)}")
    if family in ("vessel", "column", "tank", "filter") and shape == "horizontal_cylinder":
        family = "horizontal_vessel"
    elif family not in _SUPPORTS or shape not in _SUPPORTS[family]:
        family = "generic"
    complete = _complete(family, shape, dims)
    item = Body(family, shape, complete, position, rotation_deg)
    item.variant = variant_for(family, type_name, complete)
    item.grade = position[2] <= 1e-6 if grade is None else grade
    item.plinth = max(plinth, 0.0)
    from chemeascode.domains.spatial import shape_details

    if shape == "vertical_cylinder":
        _vertical(item)
    elif shape == "horizontal_cylinder":
        _horizontal(item, bundle_length)
    elif shape == "sphere":
        r = (complete.diameter or 0.0) / 2
        item.local_parts = [Part("shell", "sphere", "shell", centre=(0.0, 0.0, r), radius=r)]
        item.shell_bottom, item.shell_top = r, r
    elif family in ("pump", "compressor", "turbine") and item.variant != "machine":
        shape_details.machine(item)
    else:
        _boxy(item)
    if detail:
        shape_details.detail(item)
    if item.plinth > 0:
        _plinth(item)
    return item


#: How far a declared plinth stands out beyond the item's footprint, m (ASSUMED).
PLINTH_MARGIN = 0.1


def _plinth(item: Body) -> None:
    """A concrete plinth from grade to the item's bottom, under its footprint."""
    h = item.plinth
    dx, dy, _ = item.extent
    if item.shape in ("vertical_cylinder", "sphere"):
        part = _cyl("plinth", (0.0, 0.0, -h), (0.0, 0.0, 0.0), dx / 2 + PLINTH_MARGIN, "concrete")
    else:
        part = _box(
            "plinth",
            (0.0, 0.0, -h / 2),
            (dx + 2 * PLINTH_MARGIN, dy + 2 * PLINTH_MARGIN, h),
            "concrete",
        )
    item.local_parts.append(part)


def _vertical(item: Body) -> None:
    d = item.dims
    D, H = d.diameter or 0.0, d.height or 0.0
    r = D / 2
    family = item.family
    defaults = {"column": "skirt", "vessel": "skirt", "filter": "legs", "tank": "none"}
    support = d.support or defaults.get(family, "none")
    if family == "vessel" and d.support is None and H < 3 * D:
        support = "legs"
    if family == "tank":
        top_head = d.head or "cone_roof"
        bottom_head = "flat"
    elif family in ("stack", "silencer", "generic"):
        top_head = d.head or "flat"
        bottom_head = "flat"
    else:
        top_head = bottom_head = d.head or "ellipsoidal_2_1"
    s = {
        "skirt": _clamp(0.12 * H, 1.0, 3.0),
        "legs": _clamp(0.15 * H, 0.5, 1.5),
        "base_plate": 0.05,
        "saddles": 0.0,
        "none": 0.0,
    }.get(support, 0.0)
    hb = _head_depth(bottom_head, D) if bottom_head != "flat" else 0.0
    ht = _head_depth(top_head, D)
    if top_head == "flat":
        ht = 0.0
    shell = H - s - hb - ht
    if shell < 0.2 * H:  # too squat for its heads and support: shrink them
        factor = 0.8 * H / max(s + hb + ht, 1e-9)
        s, hb, ht = s * factor, hb * factor, ht * factor
    z0, z1 = s + hb, H - ht
    item.shell_bottom, item.shell_top, item.head_depths = z0, z1, (hb, ht)
    parts: list[Part] = []
    if support == "skirt" and s > 0:
        parts.append(_cyl("skirt", (0.0, 0.0, 0.0), (0.0, 0.0, s), r, "steel"))
    elif support == "legs" and s > 0:
        leg = max(0.04, 0.05 * D)
        for k in range(4):
            a = math.radians(45 + 90 * k)
            x, y = 0.8 * r * math.cos(a), 0.8 * r * math.sin(a)
            parts.append(_cyl(f"leg-{k + 1}", (x, y, 0.0), (x, y, z0), leg, "steel"))
    elif support == "base_plate" and s > 0:
        parts.append(_box("base", (0.0, 0.0, s / 2), (1.2 * D, 1.2 * D, s), "steel"))
    if hb > 0:
        parts.append(_cap("head-bottom", (0.0, 0.0, z0), (0.0, 0.0, -1.0), r, hb))
    parts.append(_cyl("shell", (0.0, 0.0, z0), (0.0, 0.0, z1), r, "shell"))
    if ht > 0:
        if top_head == "cone_roof":
            parts.append(
                Part(
                    "roof",
                    "cone",
                    "shell",
                    start=(0.0, 0.0, z1),
                    end=(0.0, 0.0, H),
                    radius=r,
                    radius_end=0.0,
                )
            )
        else:
            name = "roof" if family == "tank" else "head-top"
            parts.append(_cap(name, (0.0, 0.0, z1), (0.0, 0.0, 1.0), r, ht))
    item.local_parts = parts


def _horizontal(item: Body, bundle_length: float | None) -> None:
    d = item.dims
    D, L = d.diameter or 0.0, d.length or 0.0
    r = D / 2
    lift = max((d.height or D) - D, 0.0)  # saddles below the shell
    zc = lift + r
    family = item.family
    head = d.head or ("flat" if family in ("generic", "silencer") else "ellipsoidal_2_1")
    h = _head_depth(head, D) if head != "flat" else 0.0
    parts: list[Part] = []
    if family == "shell_tube":
        channel = _clamp(0.12 * L, 0.3, 1.5)
        rear = h
        x0, x1 = -L / 2 + channel, L / 2 - rear
        if x1 - x0 < 0.3 * L:
            factor = 0.7 * L / max(channel + rear, 1e-9)
            channel, rear = channel * factor, rear * factor
            x0, x1 = -L / 2 + channel, L / 2 - rear
        bonnet = min(0.25 * r, 0.4 * channel)  # the channel's dished cover
        front = -L / 2 + bonnet
        if bonnet > 0:
            parts.append(_cap("bonnet", (front, 0.0, zc), (-1.0, 0.0, 0.0), r * 1.05, bonnet))
        parts.append(_cyl("channel", (front, 0.0, zc), (x0, 0.0, zc), r * 1.05, "casing"))
        parts.append(_cyl("shell", (x0, 0.0, zc), (x1, 0.0, zc), r, "shell"))
        if rear > 0:
            parts.append(_cap("head-back", (x1, 0.0, zc), (1.0, 0.0, 0.0), r, rear))
        item.tangent, item.head_depths = (x0, x1), (bonnet, rear)
        item.ends = (front, x1)
        pull = bundle_length if bundle_length is not None else 0.85 * L
        item.local_envelopes.append(
            ("bundle_pull", (-L / 2 - pull / 2, 0.0, zc), (pull, D, D)),
        )
    else:
        if 2 * h > 0.7 * L:
            h = 0.35 * L
        x0, x1 = -L / 2 + h, L / 2 - h
        if h > 0:
            parts.append(_cap("head-front", (x0, 0.0, zc), (-1.0, 0.0, 0.0), r, h))
        parts.append(_cyl("shell", (x0, 0.0, zc), (x1, 0.0, zc), r, "shell"))
        if h > 0:
            parts.append(_cap("head-back", (x1, 0.0, zc), (1.0, 0.0, 0.0), r, h))
        item.tangent, item.head_depths = (x0, x1), (h, h)
        item.ends = (x0, x1)
    if lift > 0:
        top = lift + 0.3 * r  # up into the shell's underside
        for k, x in enumerate((-0.3 * L, 0.3 * L)):
            parts.append(_box(f"saddle-{k + 1}", (x, 0.0, top / 2), (0.3, 0.9 * D, top), "steel"))
    item.shell_bottom = zc
    item.local_parts = parts


def _boxy(item: Body) -> None:
    d = item.dims
    L, W, H = d.length or 0.0, d.width or 0.0, d.height or 0.0
    family = item.family
    parts: list[Part] = []
    if family in ("pump", "compressor", "turbine"):
        plate = _clamp(0.12 * H, 0.08, 0.3)
        axis = plate + (H - plate) * 0.5
        radius = min(W, H - plate) * (0.4 if family == "pump" else 0.45)
        parts.append(_box("base", (0.0, 0.0, plate / 2), (L, W, plate), "steel"))
        casing_len = (0.35 if family == "pump" else 0.45) * L
        if family == "turbine":
            casing_len = 0.7 * L
        x0 = -L / 2 + 0.05 * L
        x1 = x0 + casing_len
        parts.append(_cyl("casing", (x0, 0.0, axis), (x1, 0.0, axis), radius, "casing"))
        item.casing = (axis, x0, x1, radius)
        if family != "turbine":
            m0 = L / 2 - 0.45 * L
            m1 = L / 2 - 0.02 * L
            motor_r = min(W, H - plate) * 0.35
            parts.append(_cyl("motor", (m0, 0.0, axis), (m1, 0.0, axis), motor_r, "motor"))
            parts.append(
                _cyl("coupling", (x1, 0.0, axis), (m0, 0.0, axis), 0.25 * motor_r, "steel")
            )
            pull = m1 - m0
            item.local_envelopes.append(
                ("motor_removal", (L / 2 + pull / 2, 0.0, axis), (pull, 2 * motor_r, 2 * motor_r))
            )
        if family == "pump":
            item.local_envelopes.append(
                ("access", (0.0, 0.0, H / 2), (L + 2 * PUMP_ACCESS, W + 2 * PUMP_ACCESS, H))
            )
    elif family == "plate_exchanger":
        frame = _clamp(0.08 * L, 0.05, 0.25)
        for name, x in (("frame-fixed", -L / 2 + frame / 2), ("frame-pressure", L / 2 - frame / 2)):
            parts.append(_box(name, (x, 0.0, H / 2), (frame, W, H), "steel"))
        pack = L - 2 * frame
        parts.append(_box("plates", (0.0, 0.0, H / 2), (pack, 0.85 * W, 0.9 * H), "plates"))
    elif family == "air_cooler":
        legs = 0.45 * H
        post = 0.15
        for k, (sx, sy) in enumerate(((-1, -1), (1, -1), (1, 1), (-1, 1))):
            c = (sx * (L / 2 - post / 2), sy * (W / 2 - post / 2), legs / 2)
            parts.append(_box(f"leg-{k + 1}", c, (post, post, legs), "steel"))
        parts.append(_box("bundle", (0.0, 0.0, legs + 0.1 * H), (L, W, 0.2 * H), "shell"))
        fans = max(1, round(L / W)) if W > 0 else 1
        fan_r = min(W, L / fans) * 0.4
        for k in range(fans):
            x = -L / 2 + (k + 0.5) * L / fans
            parts.append(
                _cyl(f"fan-{k + 1}", (x, 0.0, legs + 0.2 * H), (x, 0.0, H), fan_r, "fan", lod=1)
            )
    else:
        parts.append(_box("body", (0.0, 0.0, H / 2), (L, W, H), "shell"))
    item.shell_bottom, item.shell_top = 0.0, H
    item.local_parts = parts
