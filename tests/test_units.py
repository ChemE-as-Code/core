"""foundation.units: the one unit converter (ported from LLM4ChemE's unit conversion tests).

Unit strings often come from tool calls, so the converter accepts the usual spellings and
capitalisation variants of temperature and pressure units. The tests that need Pint skip without
the ``units`` extra; the plant-file convention ((a)/(g) pressures, K, °C) works without it.
"""

import subprocess
import sys

import pytest

from chemeascode.foundation.units import (
    PRESSURE_UNITS,
    UnitError,
    convert_units,
    parse_unit,
    pressure_kind,
    registry,
    to_kelvin,
    to_kpa_abs,
)

pytest.importorskip("pint")

TEMPERATURE_UNITS_25 = {
    # Spelling -> 25 <spelling> expressed in kelvin
    "K": 25.0,
    "Kelvin": 25.0,
    "kelvin": 25.0,
    "KELVIN": 25.0,
    "degK": 25.0,
    "Celsius": 298.15,
    "celsius": 298.15,
    "CELSIUS": 298.15,
    "degC": 298.15,
    "degc": 298.15,
    "DEGC": 298.15,
    "°C": 298.15,
    "°c": 298.15,
    "degree_Celsius": 298.15,
    "Fahrenheit": 269.2611111111111,
    "fahrenheit": 269.2611111111111,
    "degF": 269.2611111111111,
    "°F": 269.2611111111111,
    "Rankine": 13.88888888888889,
    "degR": 13.88888888888889,
}

PRESSURE_UNITS_1 = {
    # Spelling -> 1 <spelling> expressed in pascal
    "Pa": 1.0,
    "pa": 1.0,
    "PA": 1.0,
    "Pascal": 1.0,
    "pascal": 1.0,
    "N/m^2": 1.0,
    "hPa": 100.0,
    "kPa": 1e3,
    "kpa": 1e3,
    "MPa": 1e6,
    "Mpa": 1e6,
    "MPA": 1e6,
    "GPa": 1e9,
    "bar": 1e5,
    "Bar": 1e5,
    "BAR": 1e5,
    "mbar": 100.0,
    "mBar": 100.0,
    "atm": 101325.0,
    "ATM": 101325.0,
    "Atm": 101325.0,
    "psi": 6894.7572931683635,
    "PSI": 6894.7572931683635,
    "torr": 133.32236842105263,
    "Torr": 133.32236842105263,
    "mmHg": 133.322387415,
    "mmhg": 133.322387415,
}


@pytest.mark.parametrize(("unit", "expected"), TEMPERATURE_UNITS_25.items())
def test_temperature_spellings_to_kelvin(unit: str, expected: float) -> None:
    assert convert_units(25.0, unit, "Kelvin") == pytest.approx(expected)


@pytest.mark.parametrize(("unit", "expected"), PRESSURE_UNITS_1.items())
def test_pressure_spellings_to_pascal(unit: str, expected: float) -> None:
    assert convert_units(1.0, unit, "Pascal") == pytest.approx(expected)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("bar", 1.0),
        ("Pa", 1e-5),
        ("kPa", 0.01),
        ("MPa", 10.0),
        ("atm", 1.01325),
        ("psi", 0.06894757293168365),
    ],
)
def test_pressure_to_bar(unit: str, expected: float) -> None:
    # Target used by the thermo model selection tool.
    assert convert_units(1.0, unit, "bar") == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (1.0, "degC", "K", 274.15),
        (1.0, "bar", "Pa", 1e5),
        (1.0, "degC", "kelvin", 274.15),
        (1.0, "bar", "pascal", 1e5),
        (300, "K", "degC", 26.85),
    ],
)
def test_target_unit_spellings(value: float, from_unit: str, to_unit: str, expected: float) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (1.0, "kg", "gram", 1000.0),
        (1000.0, "g", "kg", 1.0),
        (1.0, "t", "kg", 1000.0),
        (1.0, "tonne", "kg", 1000.0),
        (1.0, "l", "m^3", 1e-3),
        (1.0, "L", "m^3", 1e-3),
        (1.0, "m3/s", "L/s", 1000.0),
        (1.0, "m^3/s", "L/s", 1000.0),
        (1.0, "m³/s", "L/s", 1000.0),
        (1.0, "kg/s", "kg/h", 3600.0),
        (50.0, "%", "dimensionless", 0.5),
        (50.0, "percentage", "dimensionless", 0.5),
        (1.0, "kJ/kg", "J/kg", 1000.0),
        (1.0, "kJ / kg", "J/kg", 1000.0),
    ],
)
def test_other_normalised_spellings(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


def test_integer_input() -> None:
    assert convert_units(2, "bar", "Pa") == pytest.approx(2e5)


def test_invalid_source_unit_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Invalid source unit"):
        convert_units(1.0, "not_a_unit", "Pa")


def test_invalid_target_unit_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Incompatible or invalid units"):
        convert_units(1.0, "Pa", "not_a_unit")


def test_incompatible_units_raise_value_error() -> None:
    with pytest.raises(ValueError, match="Incompatible or invalid units"):
        convert_units(1.0, "bar", "Kelvin")


def test_capital_t_is_not_read_as_tonne() -> None:
    # "T" is the SI symbol for tesla; tonne is "t".
    with pytest.raises(ValueError, match="Incompatible or invalid units"):
        convert_units(1.0, "T", "kg")


def test_parse_unit_uses_shared_registry() -> None:
    # Quantities built from the parsed unit combine with others of the package's registry.
    ureg = registry()
    unit = parse_unit("BAR", case_insensitive=True)
    assert unit._REGISTRY is ureg
    total = ureg.Quantity(1.0, unit) + ureg.Quantity(1.0, "bar")
    assert total.to("Pa").magnitude == pytest.approx(2e5)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (2, "1e5 Pa", "Pa", 2e5),
        (2, "1E5 Pa", "Pa", 2e5),
        (2, "10^5 Pa", "Pa", 2e5),
        (2, "10**5 Pa", "Pa", 2e5),
        (2, "100 kPa", "Pa", 2e5),
        (2, "0.5 bar", "kPa", 100.0),
        (1, "1e5 PA", "bar", 1.0),
    ],
)
def test_numeric_factor_in_source_unit(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize("unit", ["mmHg", "mmhg", "MMHG", "MmHg", "mmHG"])
def test_mmhg_in_any_capitalisation(unit: str) -> None:
    # Pint's prefixes are case-sensitive; "MMHG"/"MmHg" would be megameter_Hg.
    assert convert_units(1.0, unit, "Pa") == pytest.approx(133.322387415)


@pytest.mark.parametrize("unit", ["mbar", "mBar", "MBAR", "Mbar"])
def test_mbar_in_any_capitalisation_is_millibar(unit: str) -> None:
    # Megabar (1e11 Pa) is not a plausible process pressure; millibar is.
    assert convert_units(1.0, unit, "Pa") == pytest.approx(100.0)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (1.0, "KG", "g", 1000.0),
        (1.0, "KPA", "Pa", 1000.0),
        (1.0, "KJ/KG", "J/kg", 1000.0),
        (3.6, "KMOL/h", "mol/s", 1.0),
    ],
)
def test_common_prefixed_symbols_in_upper_case(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("unit", "expected"),
    [
        ("degree Celsius", 298.15),
        ("degrees Celsius", 298.15),
        ("Celsius degree", 298.15),
        ("degrees celsius", 298.15),
        ("degree Fahrenheit", 269.2611111111111),
        ("degrees Fahrenheit", 269.2611111111111),
        ("Fahrenheit degrees", 269.2611111111111),
    ],
)
def test_temperature_scales_written_as_words(unit: str, expected: float) -> None:
    assert convert_units(25.0, unit, "K") == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        # Only the target needs the case-insensitive reading; the source keeps
        # its exact meaning (kN is kilonewton, not knot; cP is centipoise, not cup).
        (1.0, "kN/m^2", "PA", 1000.0),
        (1.0, "cP", "pa*s", 1e-3),
        # Only the source needs it.
        (1.0, "PA", "kN/m^2", 1e-3),
        (1.0, "pa*s", "cP", 1000.0),
    ],
)
def test_case_insensitive_fallback_is_per_side(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (1.0, "J/(kg*degC)", "J/(kg*K)", 1.0),
        (1.0, "kJ/(kg*degF)", "J/(kg*K)", 1800.0),
        (1.0, "W/(m^2*degC)", "W/(m^2*K)", 1.0),
        (1.0, "J/(mol*K)", "J/(mol*degC)", 1.0),
    ],
)
def test_compound_units_with_offset_temperature(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    # In compound units an offset temperature means a temperature difference.
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (3.6, "kmol/h", "mol/s", 1.0),
        (1.0, "mol/s", "kmol/h", 3.6),
        (1.0, "kmol/s", "mol/min", 60000.0),
        (1.0, "t/h", "kg/s", 1000.0 / 3600.0),
    ],
)
def test_flow_rates(value: float, from_unit: str, to_unit: str, expected: float) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (3600.0, "m3/h", "m3/s", 1.0),
        (1.0, "m3/h", "m3/h", 1.0),
        (1.0, "m3/min", "m3/h", 60.0),
        (1.0, "kg/m3", "g/L", 1.0),
        (1.0, "m3", "L", 1000.0),
        (1.0, "cm3", "mL", 1.0),
        (1.0, "dm3", "L", 1.0),
        (1.0, "mm2", "m^2", 1e-6),
        (1.0, "km2", "m2", 1e6),
        (1.0, "W/m2", "kW/m^2", 1e-3),
        (1.0, "ft3", "L", 28.316846592),
    ],
)
def test_length_powers_written_as_a_digit(
    value: float, from_unit: str, to_unit: str, expected: float
) -> None:
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


def test_normal_cubic_metres_convert_only_among_themselves() -> None:
    """The amount a Nm3 stands for depends on the plant's normal conditions."""
    assert convert_units(24.0, "Nm3/d", "Nm3/h") == pytest.approx(1.0)
    for other in ("kmol/h", "m3/h"):
        with pytest.raises(UnitError, match="Incompatible"):
            convert_units(1.0, "Nm3/h", other)


@pytest.mark.parametrize("unit", ["Sm3/h", "kg3", "M3", "nm3/h"])
def test_other_digit_suffixes_are_refused(unit: str) -> None:
    with pytest.raises(UnitError, match="Invalid source unit"):
        convert_units(1.0, unit, "m^3/h")


@pytest.mark.parametrize("unit", ["Pa/", "((Pa", ""])
def test_malformed_source_unit_raises_value_error(unit: str) -> None:
    with pytest.raises(ValueError):
        convert_units(1.0, unit, "Pa")


# -- the plant-file convention -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "from_unit", "to_unit", "expected"),
    [
        (1.0, "bar(a)", "kPa(a)", 100.0),
        (2.0, "bar(g)", "kPa(g)", 200.0),
        (1.0, "bar(a)", "Pa", 1e5),  # an unsuffixed pressure counts as absolute
        (1.0, "MPa(a)", "psi", 145.03773773),
        (25.0, "°C", "K", 298.15),
    ],
)
def test_suffixed_pressures(value, from_unit, to_unit, expected):
    assert convert_units(value, from_unit, to_unit) == pytest.approx(expected)


def test_gauge_to_absolute_needs_the_ambient_pressure():
    with pytest.raises(UnitError, match="ambient"):
        convert_units(1.0, "bar(g)", "bar(a)")
    assert convert_units(1.0, "bar(g)", "kPa(a)", ambient_kpa=101.325) == pytest.approx(201.325)
    assert convert_units(201.325, "kPa(a)", "bar(g)", ambient_kpa=101.325) == pytest.approx(1.0)
    assert convert_units(1.0, "bar(g)", "Pa", ambient_kpa=100.0) == pytest.approx(2e5)


def test_the_convention_table_matches_the_converter():
    for unit, (factor, kind) in PRESSURE_UNITS.items():
        assert pressure_kind(unit)[1] == kind
        if kind == "absolute":
            assert to_kpa_abs(3.0, unit) == pytest.approx(convert_units(3.0, unit, "kPa"))
        else:
            assert to_kpa_abs(3.0, unit) is None
            assert convert_units(3.0, unit, "kPa(g)") == pytest.approx(3.0 * factor)
    assert to_kelvin(25.0, "°C") == pytest.approx(convert_units(25.0, "°C", "K"))
    assert to_kelvin(25.0, "degF") is None


def test_the_process_domain_reexports_the_convention():
    from chemeascode.domains.process import model, schema

    assert schema.PRESSURE_UNITS is PRESSURE_UNITS
    assert model.to_kpa_abs is to_kpa_abs and model.to_kelvin is to_kelvin


def test_the_convention_needs_no_pint():
    """K, °C and the (a)/(g) pressures convert without Pint; another unit names the extra."""
    code = (
        "import sys; sys.modules['pint'] = None\n"
        "from chemeascode.foundation.units import UnitError, convert_units\n"
        "assert abs(convert_units(1, 'bar(a)', 'Pa') - 1e5) < 1e-6\n"
        "assert abs(convert_units(300, 'K', '°C') - 26.85) < 1e-9\n"
        "try:\n"
        "    convert_units(1, 'psi', 'Pa')\n"
        "except UnitError as err:\n"
        "    print(err)\n"
    )
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", code], check=False, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert "cheme-as-code[units]" in result.stdout
