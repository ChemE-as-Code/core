"""Equipment-list ``dimensions`` against the sizes a P&ID states for the same item.

A P&ID may carry sizing attributes on an equipment item: ``NominalCapacityVolume`` and
``CylinderLength`` (vessels, tanks), ``TubeLength`` of a tube bundle, ``InsideDiameter`` /
``NominalDiameter`` of a chamber (shell), ``PlateHeight`` / ``PlateWidth`` of a plate exchanger.
Where one is present and contradicts the item's ``dimensions``, the item gets
``cheme.equipment-dimension-mismatch`` (warning). Only attributes that exist are compared,
and the tolerances are wide on purpose: ``dimensions`` are overall sizes (over heads, supports
and channels), the P&ID values are inner or nominal ones.

- capacity: the volume ``pi/4 D^2 L`` over the overall ``height`` or ``length`` bounds the
  capacity from above (it may exceed it by :data:`FIT` for wall thickness rounding) and should
  not be more than :data:`LOOSE` times larger;
- a cylinder or tube length, a plate height or width: not longer than the overall size (times
  :data:`FIT`); a cylinder or tube length not shorter than :data:`SHORT` of it;
- a chamber diameter (inside or nominal, the largest chamber): within :data:`DIAMETER` of
  ``diameter``.

The DEXPI object is read by attribute name (a pyDEXPI model object as loaded), so this module
needs no import of the P&ID code.
"""

from __future__ import annotations

import math
from typing import Any

from chemeascode.domains.equipment.schemas.equipment import Dimensions

RULE = "cheme.equipment-dimension-mismatch"
#: A part may exceed the overall size by this factor (rounding, wall thickness).
FIT = 1.05
#: The overall cylinder volume may be at most this many times the stated capacity.
LOOSE = 2.0
#: A cylinder or tube length should be at least this fraction of the overall size.
SHORT = 0.5
#: Relative tolerance of a chamber diameter against ``diameter``.
DIAMETER = 0.15
#: Relative tolerance of an overall size or an empty weight stated twice (a datasheet and the
#: equipment list say the same thing: only rounding may differ).
SAME = FIT - 1

_LENGTH = {"Millimetre": 0.001, "Centimetre": 0.01, "Decimetre": 0.1, "Metre": 1.0}
_VOLUME = {"MetreCubed": 1.0, "Litre": 0.001, "DecimetreCubed": 0.001, "CentimetreCubed": 1e-6}


def _value(quantity: Any, units: dict[str, float]) -> float | None:
    """A DEXPI physical quantity in SI (m or m3); None when absent or in an unknown unit."""
    if quantity is None:
        return None
    value = getattr(quantity, "value", None)
    unit = getattr(quantity, "unit", None)
    unit = getattr(unit, "value", unit)
    if not isinstance(value, int | float) or not isinstance(unit, str) or unit not in units:
        return None
    return float(value) * units[unit]


def _main(dimensions: Dimensions) -> float | None:
    """The overall size along the item's axis: height (vertical) or length (horizontal)."""
    return dimensions.height if dimensions.height is not None else dimensions.length


def dimension_problems(dimensions: Dimensions, item: Any) -> list[str]:
    """What the DEXPI object *item* states that contradicts *dimensions*, one message each."""
    lengths = [("CylinderLength", _value(getattr(item, "cylinderLength", None), _LENGTH))]
    bundle = getattr(item, "tubeBundle", None)
    lengths.append(("TubeLength", _value(getattr(bundle, "tubeLength", None), _LENGTH)))
    diameters = []
    for chamber in getattr(item, "chambers", None) or ():
        for name in ("insideDiameter", "nominalDiameter"):
            value = _value(getattr(chamber, name, None), _LENGTH)
            if value is not None and value > 0:
                diameters.append((value, f"chamber {name[0].upper() + name[1:]}"))
    plates = [
        (name, _value(getattr(item, name[0].lower() + name[1:], None), _LENGTH))
        for name in ("PlateHeight", "PlateWidth")
    ]
    return size_problems(
        dimensions,
        capacity=_value(getattr(item, "nominalCapacityVolume", None), _VOLUME),
        lengths=lengths,
        diameters=diameters,
        plates=plates,
    )


def size_problems(
    dimensions: Dimensions,
    capacity: float | None = None,
    lengths: list[tuple[str, float | None]] | None = None,
    diameters: list[tuple[float, str]] | None = None,
    plates: list[tuple[str, float | None]] | None = None,
) -> list[str]:
    """What inner or nominal sizes (SI: m, m3) contradict the overall *dimensions*, by the
    rules of the module text: a *capacity*, *lengths* along the axis (a cylinder, tangent or
    tube length), inner *diameters* (``(value, name)``, the largest compared) and *plates*
    (``PlateHeight`` and ``PlateWidth``). Used for the P&ID's sizing attributes and for a
    datasheet's main dimensions alike."""
    found = []
    main = _main(dimensions)
    d = dimensions.diameter
    if capacity is not None and capacity > 0 and d is not None and main is not None:
        volume = math.pi / 4 * d * d * main
        if capacity > volume * FIT:
            found.append(
                f"NominalCapacityVolume {capacity:g} m3 does not fit in diameter {d:g} m x "
                f"{main:g} m ({volume:.1f} m3 overall)"
            )
        elif volume > capacity * LOOSE:
            found.append(
                f"diameter {d:g} m x {main:g} m holds {volume:.1f} m3, more than {LOOSE:g} times "
                f"the NominalCapacityVolume {capacity:g} m3"
            )
    for name, value in lengths or ():
        if value is None or main is None:
            continue
        if value > main * FIT:
            found.append(f"{name} {value:g} m is longer than the overall {main:g} m")
        elif value < main * SHORT:
            found.append(f"{name} {value:g} m is less than {SHORT:.0%} of the overall {main:g} m")
    if d is not None and diameters:
        value, name = max(diameters)
        if abs(value - d) > DIAMETER * d:
            found.append(f"{name} {value:g} m differs from diameter {d:g} m")
    plan = [v for v in (dimensions.across, dimensions.length, d) if v is not None]
    sizes = {"PlateHeight": dimensions.height, "PlateWidth": max(plan) if plan else None}
    for name, value in plates or ():
        size = sizes.get(name)
        if value is not None and size is not None and value > size * FIT:
            found.append(f"{name} {value:g} m is larger than the item ({size:g} m)")
    return found
