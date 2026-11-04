"""The main dimensions of a datasheet: read in metres, and derived from the equipment list and
the layout model.

:func:`outline` reads a datasheet's ``dimensions`` (falling back to the ``type_specific``
``diameter_m`` / ``height_m`` / ``length_m`` / ``width_m`` that drafts before the typed
dimensions carried) into an :class:`Outline` in metres, with the family the outline drawing
uses (``vertical``, ``horizontal`` or ``box``). :func:`derived_dimensions` gives the
``dimensions`` and ``weights`` entries the equipment list and the generated layout model state
for an item, each with its source and ``assumed`` marking: ``cheme datasheets draft`` and
``cheme datasheets fill`` write them, and never invent a value neither file states.

The layout model is read as data (the parsed ``layout/plant-model.yaml``): this domain does
not import the spatial one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.equipment.schemas.datasheet import Datasheet, Quantity

#: Length units a dimension may be given in, to metres.
LENGTH_UNITS = {"": 1.0, "m": 1.0, "mm": 0.001, "cm": 0.01, "dm": 0.1}
#: Weight units, to tonnes.
WEIGHT_UNITS = {"": 1.0, "t": 1.0, "kg": 0.001}

#: Words of the DEXPI class that pick the drawing family, in order.
_KINDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("column", "tower"), "column"),
    (("tank", "silo"), "tank"),
    (("tubular", "shellandtube", "shell_tube"), "shell_tube"),
    (("plate", "spiral"), "plate"),
    (
        ("pump", "compressor", "blower", "fan", "turbine", "expander", "agitator", "mixer"),
        "machine",
    ),
    (("vessel", "drum", "separator", "filter", "adsorber", "reactor", "silencer"), "vessel"),
)
#: Families that contain pressure: their datasheet states a test (water-full) weight.
PRESSURE_KINDS = ("column", "tank", "vessel", "shell_tube")


def kind_of(type_: str | None) -> str:
    """``column``, ``tank``, ``shell_tube``, ``plate``, ``machine``, ``vessel`` or ``generic``
    by the words of the DEXPI class *type_*."""
    cls = (type_ or "").lower()
    for words, kind in _KINDS:
        if any(w in cls for w in words):
            return kind
    return "generic"


def _plain(entry: Any) -> tuple[Any, str, bool, str]:
    """value, unit, assumed, source of a datasheet value."""
    if isinstance(entry, Quantity):
        return entry.value, entry.unit, entry.assumed, entry.source
    if isinstance(entry, dict):
        return (
            entry.get("value"),
            str(entry.get("unit") or ""),
            bool(entry.get("assumed")),
            str(entry.get("source") or ""),
        )
    return entry, "", False, ""


def number(entry: Any, units: dict[str, float] | None = None) -> float | None:
    """The number of a datasheet value in the base unit of *units* (default: metres); None for
    TBD, a marker, text or an unknown unit."""
    value, unit, _, _ = _plain(entry)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            return None
    factor = (units or LENGTH_UNITS).get(unit.strip())
    if factor is None:
        return None
    return float(value) * factor


def unit_known(entry: Any, units: dict[str, float] | None = None) -> bool:
    """Whether a numeric datasheet value's unit is one of *units* (default: lengths)."""
    value, unit, _, _ = _plain(entry)
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return True  # text, TBD or a marker: no unit to read
    return unit.strip() in (units or LENGTH_UNITS)


def text(entry: Any) -> str:
    """The value of a datasheet value as text ("" when absent)."""
    value = _plain(entry)[0]
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def assumed(entry: Any) -> bool:
    return _plain(entry)[2]


@dataclass
class Length:
    """A dimension in metres and whether it is assumed."""

    value: float
    assumed: bool = False


@dataclass
class Outline:
    """What the outline drawing needs of a datasheet, in metres (None where not given)."""

    tag: str
    kind: str
    family: str  # vertical, horizontal, box
    od: Length | None = None
    id: Length | None = None
    tangent: Length | None = None
    height: Length | None = None
    length: Length | None = None
    width: Length | None = None
    head: str = ""
    support: str = ""
    support_height: Length | None = None
    #: The tag of the item it stands on, and its base above grade (None: on grade).
    support_on: str = ""
    support_elevation: Length | None = None
    #: The tag of the item that houses it (no main dimensions of its own).
    housed_in: str = ""
    shaft_height: Length | None = None
    base_length: Length | None = None
    base_width: Length | None = None
    axis_deg: float | None = None
    #: (id, bottom, height) of the column sections with a bottom and a height, m.
    sections: list[tuple[str, Length, Length]] = field(default_factory=list)
    #: Where the main sizes come from: ``dimensions`` or ``type_specific`` (an older draft).
    basis: str = "dimensions"

    @property
    def diameter(self) -> Length | None:
        return self.od or self.id


def _length(entry: Any) -> Length | None:
    value = number(entry)
    if value is None or value <= 0:
        return None
    return Length(value, assumed(entry))


def outline(sheet: Datasheet) -> Outline:
    """The outline of datasheet *sheet* (see the module text)."""
    d = sheet.dimensions
    kind = kind_of(sheet.type)
    result = Outline(sheet.tag.strip(), kind, "box")
    if d is not None:
        result.od = _length(d.outside_diameter)
        result.id = _length(d.inside_diameter)
        result.tangent = _length(d.tangent_length)
        result.height = _length(d.overall_height)
        result.length = _length(d.overall_length)
        result.width = _length(d.overall_width)
        result.head = text(d.head)
        if d.support is not None:
            result.support = text(d.support.type)
            result.support_height = _length(d.support.height)
            result.support_on = text(d.support.stands_on).strip()
            result.support_elevation = _length(d.support.elevation)
        result.housed_in = text(d.housed_in).strip()
        result.shaft_height = _length(d.shaft_height)
        if d.baseplate is not None:
            result.base_length = _length(d.baseplate.length)
            result.base_width = _length(d.baseplate.width)
        result.axis_deg = number(d.axis_deg, {"": 1.0, "deg": 1.0, "°": 1.0})
        for section in d.sections:
            bottom, height = _length(section.bottom), _length(section.height)
            if bottom is not None and height is not None:
                result.sections.append((section.id, bottom, height))
    if not any((result.od, result.id, result.tangent, result.height, result.length)):
        # an older draft: the equipment list's dimensions copied into type_specific
        specific = sheet.type_specific
        result.od = _length(specific.get("diameter_m"))
        result.height = _length(specific.get("height_m"))
        result.length = _length(specific.get("length_m"))
        result.width = _length(specific.get("width_m") or specific.get("depth_m"))
        if any((result.od, result.height, result.length, result.width)):
            result.basis = "type_specific"
    round_ = result.diameter is not None
    orientation = d.orientation if d is not None else None
    if kind in ("machine", "plate") or not round_:
        result.family = "box"
    elif orientation is not None:
        result.family = orientation
    elif kind in ("column", "tank"):
        result.family = "vertical"
    elif result.length is not None or kind == "shell_tube":
        result.family = "horizontal"
    else:
        result.family = "vertical"
    return result


# -- head depths for drawing ---------------------------------------------------------------------


def head_depth(head: str, diameter: float) -> float | None:
    """The depth of a head of type *head* on *diameter*, m, by its geometry (2:1 ellipsoidal
    D/4, hemispherical D/2, torispherical about 0.19 D for a 10 % knuckle, a 90 degree cone
    D/2, a tank's cone or dome roof D/10); None for an unknown head, 0 for a flat one."""
    depths = {
        "ellipsoidal_2_1": 0.25,
        "hemispherical": 0.5,
        "torispherical": 0.19,
        "cone": 0.5,
        "cone_roof": 0.1,
        "dome_roof": 0.1,
        "flat": 0.0,
    }
    factor = depths.get(head)
    return None if factor is None else factor * diameter


# -- what the lists and the layout model state ---------------------------------------------------


def _entry(value: Any, unit: str, source: str, is_assumed: bool) -> dict[str, Any]:
    found: dict[str, Any] = {"value": value, "unit": unit, "source": source}
    if is_assumed:
        found["assumed"] = True
    return found


def _round(value: float) -> float:
    return float(f"{value:.4g}")


def model_item(model: dict[str, Any] | None, tag: str) -> dict[str, Any] | None:
    """The item *tag* of the parsed layout model, or None."""
    for item in (model or {}).get("equipment") or ():
        if isinstance(item, dict) and str(item.get("tag") or item.get("id")) == tag:
            return item
    return None


def _part(item: dict[str, Any], name: str) -> dict[str, Any] | None:
    tag = str(item.get("tag") or item.get("id"))
    for part in item.get("parts") or ():
        if isinstance(part, dict) and part.get("id") == f"{tag}/{name}":
            return part
    return None


def _span(part: dict[str, Any]) -> float | None:
    start, end = part.get("start"), part.get("end")
    if not (isinstance(start, list) and isinstance(end, list) and len(start) == len(end) == 3):
        return None
    return math.dist([float(v) for v in start], [float(v) for v in end])


def _base(placed: dict[str, Any]) -> float:
    position = placed.get("position")
    if isinstance(position, list) and len(position) == 3:
        try:
            return float(position[2])
        except (TypeError, ValueError):
            return 0.0
    return 0.0


def _bbox(placed: dict[str, Any]) -> list[float] | None:
    box = placed.get("bbox")
    if not (isinstance(box, list) and len(box) == 6):
        return None
    try:
        return [float(v) for v in box]
    except (TypeError, ValueError):
        return None


#: The top of the item below within this of the base of the one above, m.
STACK_TOLERANCE = 0.05


def _standing_on(model: dict[str, Any] | None, placed: dict[str, Any]) -> str:
    """The tag of the model item whose top is at the base of *placed* (within
    :data:`STACK_TOLERANCE`) and whose plan box holds the centre of *placed*; "" when none (or
    more than one: then the drawing gives the elevation only)."""
    position = placed.get("position")
    if not (isinstance(position, list) and len(position) == 3):
        return ""
    try:
        x, y, z = (float(v) for v in position)
    except (TypeError, ValueError):
        return ""
    me = str(placed.get("tag") or placed.get("id"))
    found = []
    for other in (model or {}).get("equipment") or ():
        if not isinstance(other, dict) or str(other.get("tag") or other.get("id")) == me:
            continue
        box = _bbox(other)
        if box is None or abs(box[5] - z) > STACK_TOLERANCE:
            continue
        if box[0] <= x <= box[3] and box[1] <= y <= box[4]:
            found.append(str(other.get("tag") or other.get("id")))
    return found[0] if len(found) == 1 else ""


def derived_dimensions(
    item: Any,
    model: dict[str, Any] | None,
    list_file: str = "equipment/equipment-list.yaml",
    model_file: str = "layout/plant-model.yaml",
    mark: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ``dimensions`` and ``weights`` entries the equipment-list *item* and the layout
    *model* state for it: ``(dimensions, weights)``, plain data in datasheet form. The equipment
    list's sizes are overall sizes (its outside diameter, overall height or length, head and
    support types, empty weight); the model adds the tangent length and the support height of
    its generated shell (the 3D model's proportions: marked assumed), a horizontal item's
    axis direction and, for an item placed above grade, its base elevation and the item it
    stands on (``support.elevation``, ``support.stands_on``). *mark* starts every source
    (``cheme datasheets fill: ``). Sizes a tool wrote into the list (``dimensions.source``,
    ``assumed``: ``cheme process stack``) carry that source and marking. Nothing is given that
    neither file states."""
    prefix = f"{mark}: " if mark else ""
    dims: dict[str, Any] = {}
    weights: dict[str, Any] = {}
    d = getattr(item, "dimensions", None)
    if d is None:
        return dims, weights
    src = f"{prefix}{list_file} dimensions"
    # sizes a tool wrote into the list (cheme process stack) carry its source and marking
    told = getattr(d, "source", "") or ""
    listed_assumed = bool(getattr(d, "assumed", False))

    def listed(value: Any, unit: str, where: str) -> dict[str, Any]:
        return _entry(value, unit, f"{where}: {told}" if told else where, listed_assumed)

    kind = kind_of(getattr(item, "type", None))
    round_ = d.diameter is not None
    if round_:
        horizontal = kind not in ("column", "tank") and d.length is not None
        dims["orientation"] = "horizontal" if horizontal else "vertical"
        dims["outside_diameter"] = listed(d.diameter, "m", f"{src}.diameter")
        if horizontal:
            dims["overall_length"] = listed(d.length, "m", f"{src}.length")
            if d.height is not None:
                dims["overall_height"] = listed(
                    d.height, "m", f"{src}.height (top of the shell on its supports)"
                )
        elif d.height is not None:
            dims["overall_height"] = listed(d.height, "m", f"{src}.height")
        if d.head:
            dims["head"] = {"value": d.head, "source": f"{src}.head"}
    else:
        for name in ("length", "width", "height"):
            value = d.width if name == "width" and d.width is not None else getattr(d, name)
            if name == "width" and value is None:
                value = d.depth
            if value is not None:
                dims[f"overall_{name}"] = listed(value, "m", f"{src}.{name}")
    if d.support:
        dims["support"] = {"type": {"value": d.support, "source": f"{src}.support"}}
    if d.weight is not None:
        weights["empty"] = _entry(d.weight, "t", f"{src}.weight (empty)", False)

    placed = model_item(model, str(item.tag).strip())
    if placed is None:
        return dims, weights
    msrc = f"{prefix}{model_file}"
    tag = str(item.tag).strip()
    base = _base(placed)
    shape = placed.get("shape")
    if round_ and shape in ("vertical_cylinder", "horizontal_cylinder"):
        shell = _part(placed, "shell")
        span = _span(shell) if shell else None
        if span:
            dims["tangent_length"] = _entry(
                _round(span),
                "m",
                f"{msrc} part {tag}/shell: the generated shell between the heads (the 3D "
                "model's proportions, not a vessel design)",
                True,
            )
        start = (shell or {}).get("start")
        if shape == "vertical_cylinder":
            support = _part(placed, "skirt") or _part(placed, "leg-1")
            if support is not None and isinstance(start, list):
                lift = min(float(start[2]), float((shell or {}).get("end", start)[2])) - base
                if lift > 0:
                    dims.setdefault("support", {})["height"] = _entry(
                        _round(lift),
                        "m",
                        f"{msrc} parts {tag}/shell, {support['id']}: the bottom tangent line "
                        "above the base (the 3D model's proportions, not a design)",
                        True,
                    )
        else:
            radius = (shell or {}).get("radius")
            if isinstance(start, list) and radius and _part(placed, "saddle-1"):
                lift = float(start[2]) - float(radius) - base
                if lift > 0:
                    dims.setdefault("support", {})["height"] = _entry(
                        _round(lift),
                        "m",
                        f"{msrc} part {tag}/shell: underside of the shell above the base (the "
                        "3D model's proportions, not a design)",
                        True,
                    )
    if base > 0:
        support = dims.setdefault("support", {})
        support["elevation"] = _entry(
            _round(base),
            "m",
            f"{msrc} {tag} position z (layout/equipment-placement.yaml): the base above grade",
            False,
        )
        below = _standing_on(model, placed)
        if below:
            support["stands_on"] = {
                "value": below,
                "source": f"{msrc}: the top of {below} at the base of {tag}, under its plan "
                "outline",
            }
    rotation = placed.get("rotation_deg")
    if isinstance(rotation, int | float) and (
        shape == "horizontal_cylinder" or shape == "box" and kind in ("machine", "plate")
    ):
        dims["axis_deg"] = _entry(
            _round(float(rotation) % 360),
            "deg",
            f"{msrc} {tag} rotation_deg (layout/equipment-placement.yaml)",
            False,
        )
    return dims, weights
