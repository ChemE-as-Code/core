"""Units: every unit conversion in the package goes through this module.

The convention of the plant files (standard library only):

- a pressure says whether it is absolute or gauge, ``kPa(a)``, ``bar(g)``, ... (``PRESSURE_UNITS``);
  a bare ``kPa`` is ambiguous in a plant file and ``cheme validate`` refuses it there;
- a temperature is in ``K`` or ``°C`` (``TEMPERATURE_UNITS``).

:func:`convert_units` converts a value between any two units. The units of the convention and
``K``, ``°C``, ``Pa``, ``kPa``, ``MPa``, ``bar`` need nothing beyond the standard library; every
other unit goes through Pint (extra ``units``). The spellings tools and agents produce are
accepted: ``Celsius``, ``BAR``, ``degrees Fahrenheit``, ``1e5 Pa`` (a numeric factor in the source
unit), ``m3/h``, ``kg/m3``, ``cm3`` (a power of a length written as a digit). ``Nm3`` (a normal
cubic metre) is an amount of gas at the normal state the plant declares (the flowsheet's
``units.normal_conditions``), so it converts only to other Nm3 units (``Nm3/d`` to ``Nm3/h``),
never to ``m3`` or ``kmol``; the process model converts it with those conditions. ``Sm3`` is
refused: its reference state (15 °C, 20 °C, 60 °F) is not fixed. A pressure without
``(a)``/``(g)`` counts as absolute; a gauge pressure converts to an absolute one only with the
ambient pressure given.
"""

from __future__ import annotations

import functools
import itertools
import re
import tokenize
from collections.abc import Callable
from typing import Any

#: Pressure units of the plant files: factor to kPa and whether absolute or gauge.
PRESSURE_UNITS = {
    "Pa(a)": (0.001, "absolute"),
    "kPa(a)": (1.0, "absolute"),
    "bar(a)": (100.0, "absolute"),
    "MPa(a)": (1000.0, "absolute"),
    "Pa(g)": (0.001, "gauge"),
    "kPa(g)": (1.0, "gauge"),
    "bar(g)": (100.0, "gauge"),
    "MPa(g)": (1000.0, "gauge"),
}
#: Temperature units of the plant files.
TEMPERATURE_UNITS = ("K", "°C")

#: Units converted without Pint: dimension, factor and offset to K or kPa.
_LINEAR = {
    "K": ("temperature", 1.0, 0.0),
    "°C": ("temperature", 1.0, 273.15),
    "degC": ("temperature", 1.0, 273.15),
    "Pa": ("pressure", 0.001, 0.0),
    "kPa": ("pressure", 1.0, 0.0),
    "MPa": ("pressure", 1000.0, 0.0),
    "bar": ("pressure", 100.0, 0.0),
}
_KIND = re.compile(r"^(?P<unit>.+?)\s*\((?P<kind>[ag])\)$")


# -- LCA inventory units ------------------------------------------------------------------------

#: Units of life cycle inventory amounts (``domains/assessment/lca``), by quantity kind, with the
#: factor to the kind's base unit (:data:`LCI_BASE_UNITS`). The one table every LCA amount, factor
#: and functional unit is converted with; plain factors, so no Pint is needed.
LCI_UNITS: dict[str, tuple[str, float]] = {
    "kg": ("mass", 1.0),
    "g": ("mass", 0.001),
    "t": ("mass", 1000.0),
    "kWh": ("energy", 1.0),
    "MWh": ("energy", 1000.0),
    "MJ": ("energy", 1 / 3.6),
    "GJ": ("energy", 1000 / 3.6),
    "m": ("length", 1.0),
    "km": ("length", 1000.0),
    "m2": ("area", 1.0),
    # land occupation: area x time (m2*a, square metre-year)
    "m2*a": ("land-occupation", 1.0),
    "m3": ("volume", 1.0),
    "L": ("volume", 0.001),
    # gas volume at a stated reference state (GAS_REFERENCE_STATES), ideal gas
    "Nm3": ("normal-volume", 1.0),
    "Sm3": ("normal-volume", 273.15 / 288.15),
    "ea": ("count", 1.0),
    # use of rented or shared equipment: items x time (a year of 8760 h, 365 d)
    "ea*h": ("item-time", 1.0),
    "ea*a": ("item-time", 8760.0),
    "tkm": ("transport", 1.0),
    "kBq": ("radioactivity", 1.0),
}
#: The unit an inventory counts each quantity kind in.
LCI_BASE_UNITS: dict[str, str] = {
    "mass": "kg",
    "energy": "kWh",
    "length": "m",
    "area": "m2",
    "land-occupation": "m2*a",
    "volume": "m3",
    "normal-volume": "Nm3",
    "count": "ea",
    "item-time": "ea*h",
    "transport": "tkm",
    "radioactivity": "kBq",
}
#: The reference state of each gas-volume unit: temperature (K) and absolute pressure (kPa).
#: Nm3: 0 °C and 1.01325 bar (DIN 1343); Sm3: 15 °C and 1.01325 bar (ISO 13443).
GAS_REFERENCE_STATES: dict[str, tuple[float, float]] = {
    "Nm3": (273.15, 101.325),
    "Sm3": (288.15, 101.325),
}
#: Molar volume of an ideal gas at 273.15 K and 101.325 kPa, m3/kmol (CODATA 2018).
MOLAR_VOLUME_NORMAL = 22.41396954


def lci_convert(value: float, from_unit: str, to_unit: str) -> float:
    """*value* in the LCI unit *from_unit* expressed in *to_unit* of the same kind.

    Raises :class:`UnitError` for an unknown unit or another kind."""
    try:
        kind, factor = LCI_UNITS[from_unit]
        target, per = LCI_UNITS[to_unit]
    except KeyError as missing:
        raise UnitError(f"not an LCI unit: {missing.args[0]!r}") from None
    if kind != target:
        raise UnitError(f"{from_unit} ({kind}) -> {to_unit} ({target})")
    return value * factor / per


def gas_volume_to_kg(value: float, unit: str, molar_mass: float) -> float:
    """The mass (kg) of *value* *unit* (Nm3 or Sm3) of an ideal gas of *molar_mass* (kg/kmol)."""
    return lci_convert(value, unit, "Nm3") / MOLAR_VOLUME_NORMAL * molar_mass


class UnitError(ValueError):
    """A unit is unknown, malformed or incompatible with the other one, or Pint is missing."""


def to_kpa_abs(value: float, unit: str) -> float | None:
    """Absolute pressure in kPa, None for a gauge value (no ambient stated) or unknown unit."""
    factor, kind = PRESSURE_UNITS.get(unit, (None, None))
    if factor is None or kind != "absolute":
        return None
    return value * factor


def to_kelvin(value: float, unit: str) -> float | None:
    if unit == "K":
        return value
    if unit == "°C":
        return value + 273.15
    return None


def pressure_kind(unit: str) -> tuple[str, str | None]:
    """``("kPa", "gauge")`` for ``kPa(g)``, ``("bar", "absolute")`` for ``bar(a)``,
    ``(unit, None)`` for a unit without the suffix."""
    match = _KIND.match(unit.strip())
    if not match:
        return unit, None
    return match["unit"], "absolute" if match["kind"] == "a" else "gauge"


def convert_units(
    value: float, from_unit: str, to_unit: str, *, ambient_kpa: float | None = None
) -> float:
    """*value* in *from_unit* expressed in *to_unit*.

    Each unit is read as written first; if the conversion fails, the source and the target are
    read case-insensitively one at a time (:func:`parse_unit`). A unit that is valid as written
    keeps its meaning as long as the conversion works with it. *ambient_kpa* is the absolute
    ambient pressure in kPa, needed only between a gauge and an absolute pressure.

    Raises :class:`UnitError` (a ``ValueError``) for an unknown or incompatible unit, a gauge
    conversion without *ambient_kpa*, or a unit that needs Pint when Pint is not installed.
    """
    source, source_kind = pressure_kind(from_unit)
    target, target_kind = pressure_kind(to_unit)
    if (source_kind == "gauge") == (target_kind == "gauge"):
        return _convert(value, source, target)
    if ambient_kpa is None:
        raise UnitError(
            f"{from_unit} -> {to_unit}: a gauge pressure converts to an absolute one only with "
            "the ambient pressure (ambient_kpa)"
        )
    kpa = _convert(value, source, "kPa") + (ambient_kpa if source_kind == "gauge" else 0.0)
    if target_kind == "gauge":
        kpa -= ambient_kpa
    return _convert(kpa, "kPa", target)


def _convert(value: float, source: str, target: str) -> float:
    a, b = _LINEAR.get(source), _LINEAR.get(target)
    if a and b:
        if a[0] != b[0]:
            raise UnitError(f"Incompatible or invalid units: {source} -> {target}")
        return (value * a[1] + a[2] - b[2]) / b[1]
    return _convert_pint(value, source, target)


# -- Pint ---------------------------------------------------------------------------------------


@functools.cache
def registry() -> Any:
    """The one Pint unit registry of the package (extra ``units``)."""
    try:
        import pint
    except ImportError as err:
        raise UnitError(
            "this unit needs Pint: pip install 'cheme-as-code[units]' (K, °C, Pa, kPa, MPa, bar "
            "and the (a)/(g) pressure units work without it)"
        ) from err
    ureg = pint.UnitRegistry()
    # a dimension of its own: the amount it stands for depends on the plant's normal conditions
    ureg.define("normal_cubic_meter = [normal_volume]")
    return ureg


# Spellings that Pint does not understand (or reads differently), as Pint unit names.
_UNIT_ALIASES = {
    "kg": "kilogram",
    "g": "gram",
    "l": "liter",
    "L": "liter",
    "Celsius": "degree_Celsius",
    "Fahrenheit": "degree_Fahrenheit",
    "Kelvin": "kelvin",
    "m3/s": "meter**3/second",
    "m^3/s": "meter**3/second",
    "m³/s": "meter**3/second",
    "kg/s": "kilogram/second",
    "percentage": "percent",
    "%": "percent",
    "kJ/kg": "kilojoule/kilogram",
    "kJ / kg": "kilojoule/kilogram",
    "Pascal": "pascal",
    "kPa": "kilopascal",
    "MPa": "megapascal",
}

# Whole unit strings written as words, compared lower-cased with collapsed whitespace. Pint would
# read "degree Celsius" as angle degree times Celsius.
_PHRASE_ALIASES = {
    phrase: unit
    for scale, unit in (("celsius", "degree_Celsius"), ("fahrenheit", "degree_Fahrenheit"))
    for phrase in (f"degree {scale}", f"degrees {scale}", f"{scale} degree", f"{scale} degrees")
}

# Prefixed symbols accepted in any capitalisation, because their usual reading is the only
# plausible one for process quantities. Pint's prefixes are case-sensitive, so it would read
# "MMHG" as megameter of mercury and "MBAR" as megabar, and it cannot read "KG" or "KMOL" at all.
# Deliberately absent: "mpa", because "MPa" and "mPa" are both plausible.
_ANY_CASE_UNITS = {
    "mmhg": "millimeter_Hg",
    "mbar": "millibar",
    "kpa": "kilopascal",
    "kg": "kilogram",
    "kmol": "kilomole",
    "kj": "kilojoule",
}

# Units written with a digit for the power of a length, "m3", "cm3", "mm2", read as "m**3", ...
# Only lengths of process units: a digit after another name ("kg3") or "nm3", a frequent
# misspelling of Nm3 rather than a cubic nanometre, is left for Pint to refuse.
_LENGTH_POWER = re.compile(r"^(?P<length>[kdcm]?m|ft)(?P<power>[23])$")
# Unit names Pint does not know. "Nm3" is case-sensitive: "nm3" is a cubic nanometre.
_NAME_ALIASES = {"Nm3": "normal_cubic_meter", "Nm³": "normal_cubic_meter"}

# Numbers and unit names inside a unit expression such as "kJ/kg", "1e5 Pa" or "m**3/s". Numbers
# are matched first so that exponents ("1e5") are not taken for unit names.
_TOKEN = re.compile(r"(?P<number>(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)|(?P<name>[^\W\d]\w*|°\w*)")


def _parse_errors() -> tuple[type[BaseException], ...]:
    """The errors Pint raises for unknown or malformed unit strings."""
    from pint import OffsetUnitCalculusError, UndefinedUnitError

    return (
        UndefinedUnitError,
        OffsetUnitCalculusError,
        ValueError,
        AssertionError,  # a trailing operator, "Pa/"
        tokenize.TokenError,  # unbalanced parentheses
    )


def _resolve_case_insensitive(token: str) -> str:
    """The unit name for *token*, ignoring its capitalisation. A name that matches without a
    prefix wins over a prefixed reading, so ``PA`` is pascal rather than petaampere. Ambiguous
    tokens and non-units are returned unchanged and fail in the parse that follows."""
    ureg = registry()
    exact = ureg.parse_unit_name(token)
    if any(not prefix for prefix, _, _ in exact):
        return token
    loose = set(ureg.parse_unit_name(token, case_sensitive=False))
    unprefixed = {candidate for candidate in loose if not candidate[0]}
    if len(unprefixed) == 1:
        return "".join(next(iter(unprefixed)))
    if exact:
        return token
    if len(loose) == 1:
        return "".join(next(iter(loose)))
    return token


def _normalise(unit: str, case_insensitive: bool) -> str:
    """*unit* rewritten into names Pint reads as intended."""
    unit = _UNIT_ALIASES.get(unit, unit)
    phrase = " ".join(unit.split()).lower()
    if phrase in _PHRASE_ALIASES:
        return _PHRASE_ALIASES[phrase]

    def replace(match: re.Match[str]) -> str:
        name = match["name"]
        if name is None:
            return match[0]
        if name.lower() in _ANY_CASE_UNITS:
            return _ANY_CASE_UNITS[name.lower()]
        if name in _NAME_ALIASES:
            return _NAME_ALIASES[name]
        if power := _LENGTH_POWER.match(name):
            return f"{power['length']}**{power['power']}"
        return _resolve_case_insensitive(name) if case_insensitive else name

    return _TOKEN.sub(replace, unit)


def parse_unit(unit: str, case_insensitive: bool = False) -> Any:
    """*unit* as a ``pint.Unit`` of :func:`registry`.

    With *case_insensitive*, names whose capitalisation matches no Pint unit are resolved
    ignoring case (``PA``, ``BAR``, ``DEGC``); names valid as written keep their meaning, so
    ``T`` stays tesla and is never read as tonne. In both modes ``mmHg``, ``mbar``, ``kPa``,
    ``kg``, ``kmol`` and ``kJ`` are accepted in any capitalisation. Raises Pint's
    ``UndefinedUnitError`` for an unknown unit and ``ValueError`` for a numeric factor.
    """
    return registry().parse_units(_normalise(unit, case_insensitive))


def _parse_source_unit(unit: str, case_insensitive: bool) -> tuple[float, Any]:
    """The numeric factor (1 if none) and the unit of a source unit, ``(100000.0, pascal)`` for
    ``"1e5 Pa"``."""
    import pint

    ureg = registry()
    normalised = _normalise(unit, case_insensitive)
    try:
        return 1, ureg.parse_units(normalised)
    except ValueError:
        # parse_units refuses factors; the factor is applied to the value (not by quantity
        # arithmetic), which keeps offset units such as degC usable.
        expression = ureg.parse_expression(normalised)
        if not isinstance(expression, pint.Quantity):
            expression = ureg.Quantity(expression)
        return expression.magnitude, expression.units


def _parse_both_ways[T](parse: Callable[[bool], T]) -> list[T]:
    """Parsed as written, then case-insensitively; the distinct results."""
    errors = _parse_errors()
    results: list[T] = []
    for case_insensitive in (False, True):
        try:
            result = parse(case_insensitive)
        except errors:
            continue
        if result not in results:
            results.append(result)
    return results


def _convert_pint(value: float, from_unit: str, to_unit: str) -> float:
    ureg = registry()  # first: names the extra when Pint is missing
    from pint import DimensionalityError, OffsetUnitCalculusError

    sources = _parse_both_ways(lambda ci: _parse_source_unit(from_unit, ci))
    if not sources:
        raise UnitError(f"Invalid source unit: '{from_unit}'")
    targets = _parse_both_ways(lambda ci: parse_unit(to_unit, ci))
    # Both as written, then only the target re-read, then only the source, then both.
    last_error: Exception | None = None
    for (factor, source), target in itertools.product(sources, targets):
        try:
            return ureg.Quantity(value * factor, source).to(target).magnitude
        except (DimensionalityError, OffsetUnitCalculusError) as err:
            last_error = err
    raise UnitError(f"Incompatible or invalid units: {from_unit} -> {to_unit}") from last_error
