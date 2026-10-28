"""What the equipment sizing covers, per equipment class and engineering aspect.

:mod:`.sizing` and ``cheme datasheets fill`` (:mod:`.fill`) give *process* sizes (duty, area,
head, power, stages, volume) from the flowsheet streams and declared parameters. That is
preliminary sizing, not equipment engineering: the table below says, for each class of
:data:`~chemeascode.domains.equipment.datasheets.TYPE_FIELDS` and each aspect, whether core
supports it, does it preliminarily, or does not do it at all:

- ``supported``: calculated to the standard the aspect needs (nothing is, today);
- ``preliminary``: calculated by a short-cut method (typical coefficients, declared
  efficiencies, ideal or real gas through the property adapter) with its basis, for
  screening, the equipment estimate and enquiries; not a rating or a design to a code;
- ``unsupported``: not calculated; a value comes from a supplier, a specialist calculation or
  a decision recorded with its source.

The aspects:

- ``process_sizing``: the duty, area, head, power, stages, volume the fill writes;
- ``rating``: equipment-specific rating (exchanger geometry and film coefficients, pump curves
  and NPSH required, compressor maps, tray or packing hydraulics, separator droplet settling);
- ``mechanical_code``: mechanical design to a code (wall thickness, MAWP, nozzle loads; ASME
  VIII, EN 13445, API 610/617/650/660, TEMA);
- ``materials_corrosion``: material selection and corrosion allowance (core carries the
  material the equipment list gives, it does not select one);
- ``relief``: relief scenarios and device sizing (API 520/521, ISO 4126); the piping-items list
  holds a device's set pressure and relief case as given data, nothing sizes it;
- ``dynamics_controls``: dynamic behaviour and control (the process model is steady state;
  ``domains/control`` holds interlocks and the cause-and-effect matrix, not dynamics).

``field`` is the datasheet key (``type_specific``) that stands for an unsupported aspect: a
fill leaves it ``TBD`` with the reason, so a draft never looks complete where core did not
calculate. A fill also records the scope of what it wrote in the sheet's ``sizing_basis``
(:data:`SCOPE_PARAMETER`): its values are preliminary. :func:`status_of` reads a datasheet
value's status the same way for other tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Status = Literal["supported", "preliminary", "unsupported"]
ASPECTS = (
    "process_sizing",
    "rating",
    "mechanical_code",
    "materials_corrosion",
    "relief",
    "dynamics_controls",
)
#: The ``sizing_basis`` parameter a fill writes on every draft it fills.
SCOPE_PARAMETER = "sizing_scope"
#: Its value: what a fill writes is preliminary sizing.
SCOPE_VALUE = "preliminary"
DOC = "docs/framework/sizing.md"


@dataclass(frozen=True)
class AspectCoverage:
    """One cell of :data:`SIZING_COVERAGE`."""

    status: Status
    basis: str
    field: tuple[str, str] | None = None
    """``(type_specific key, unit)`` a fill leaves TBD while the aspect is unsupported."""

    def as_dict(self) -> dict[str, Any]:
        found: dict[str, Any] = {"status": self.status, "basis": self.basis}
        if self.field:
            found["field"] = self.field[0]
        return found


_MECHANICAL = AspectCoverage(
    "unsupported",
    "no mechanical design to a code (wall thickness, MAWP, nozzle loads): from the supplier or "
    "a mechanical calculation",
    ("mechanical_design", ""),
)
_MACHINE_MECHANICAL = AspectCoverage(
    "unsupported",
    "no mechanical design (casing, seals, bearings, API 610/617/611 scope): from the supplier",
    ("mechanical_design", ""),
)
_CORROSION = AspectCoverage(
    "unsupported",
    "no material selection or corrosion allowance: the material is the equipment list's, "
    "given; the allowance from a materials/corrosion review",
    ("corrosion_allowance_mm", "mm"),
)
_RELIEF = AspectCoverage(
    "unsupported",
    "no relief scenarios or device sizing (API 520/521, ISO 4126): from a relief study",
    ("relief_protection", ""),
)
_DYNAMICS = AspectCoverage(
    "unsupported",
    "steady state only: no dynamic model or control design (domains/control holds interlocks "
    "and the cause-and-effect matrix)",
)


def _rating(what: str, key: str = "rating", unit: str = "") -> AspectCoverage:
    return AspectCoverage("unsupported", f"no {what}: from the supplier's rating", (key, unit))


def _row(sizing: AspectCoverage, rating: AspectCoverage, mechanical=_MECHANICAL):
    return {
        "process_sizing": sizing,
        "rating": rating,
        "mechanical_code": mechanical,
        "materials_corrosion": _CORROSION,
        "relief": _RELIEF,
        "dynamics_controls": _DYNAMICS,
    }


#: Equipment class (the first word of its TYPE_FIELDS row) -> aspect -> coverage.
SIZING_COVERAGE: dict[str, dict[str, AspectCoverage]] = {
    "pump": _row(
        AspectCoverage(
            "preliminary",
            "differential head from the stream pressures, static head and Darcy-Weisbach line "
            "losses along the routed pipes; NPSH available; power for a declared efficiency",
        ),
        _rating("pump curve, NPSH required or selection", "npsh_required_m", "m"),
        _MACHINE_MECHANICAL,
    ),
    "compressor": _row(
        AspectCoverage(
            "preliminary",
            "stages for a declared maximum pressure ratio; isentropic or polytropic power for "
            "a declared efficiency (real gas through the property adapter, else ideal gas); "
            "intercooler duties without their pressure drop",
        ),
        _rating("performance map, surge or machine selection"),
        _MACHINE_MECHANICAL,
    ),
    "turbine": _row(
        AspectCoverage(
            "preliminary",
            "isentropic or polytropic power recovered for a declared efficiency",
        ),
        _rating("performance map or machine selection"),
        _MACHINE_MECHANICAL,
    ),
    "fan": _row(
        AspectCoverage("unsupported", "no fill calculation: flow and power stay TBD"),
        _rating("fan curve or selection"),
        _MACHINE_MECHANICAL,
    ),
    "exchanger": _row(
        AspectCoverage(
            "preliminary",
            "duty from the stream enthalpies, LMTD with F of a 1-2 shell, A = Q/(U F LMTD) "
            "with a declared or typical U (Sinnott Table 12.1, ASSUMED)",
        ),
        _rating(
            "thermal-hydraulic rating (tube count and layout, film coefficients, fouling, "
            "pressure drop, vibration; TEMA)"
        ),
    ),
    "heater": _row(
        AspectCoverage("preliminary", "duty from the stream enthalpies"),
        _rating("fired-heater or heater rating (radiant/convection sections, tube wall)"),
    ),
    "column": _row(
        AspectCoverage(
            "preliminary",
            "Fenske-Underwood-Gilliland stages, trays for a declared efficiency; volume from "
            "the dimensions",
        ),
        AspectCoverage(
            "unsupported",
            "no flooding or tray/packing hydraulics (the diameter): from a tray or packing "
            "supplier's hydraulic rating",
            ("flooding_diameter_m", "m"),
        ),
    ),
    "reactor": _row(
        AspectCoverage(
            "preliminary",
            "catalyst mass and bed volume of the linked fixed bed (or the catalyst's space "
            "velocity, ASSUMED), its pressure drop, the duty from cheme process reactors; the "
            "vessel volume as the bed's (a lower bound)",
        ),
        _rating("reactor internals, heat-transfer surface or distributor design"),
    ),
    "vessel": _row(
        AspectCoverage(
            "preliminary",
            "volume from the dimensions and the residence time against the design basis",
        ),
        _rating("separator rating (droplet settling, K-factor, demister, level settings)"),
    ),
}


def coverage_of(class_word: str) -> dict[str, AspectCoverage] | None:
    """The row of an equipment class (``pump``, ``exchanger``, ...; :func:`class_of` finds it
    from a DEXPI class)."""
    return SIZING_COVERAGE.get(class_word)


def class_of(type_: str | None) -> str | None:
    """The class word of DEXPI class *type_* (the first word of its TYPE_FIELDS row,
    :func:`~chemeascode.domains.equipment.datasheets.type_row`)."""
    from chemeascode.domains.equipment.datasheets import type_row

    row = type_row(type_)
    return row[0][0] if row else None


def unsupported_fields(class_word: str) -> list[tuple[str, str, str]]:
    """``(key, unit, reason)`` of the datasheet fields a fill leaves TBD for *class_word*."""
    row = SIZING_COVERAGE.get(class_word) or {}
    return [
        (cell.field[0], cell.field[1], f"unsupported in cheme-as-code: {cell.basis} ({DOC})")
        for cell in row.values()
        if cell.status == "unsupported" and cell.field is not None
    ]


def status_of(entry: Any) -> Status | None:
    """The status of one datasheet value: ``preliminary`` when ``cheme datasheets fill`` wrote
    it (its source starts with the fill's mark), None otherwise (a given or supplier value
    has the status its source gives it)."""
    from chemeascode.domains.equipment.fill import FILL_MARK

    source = entry.get("source") if isinstance(entry, dict) else None
    if isinstance(source, str) and source.startswith(FILL_MARK):
        value = entry.get("value")
        if isinstance(value, str) and value.strip().upper().startswith("TBD"):
            return None
        return "preliminary"
    return None


def coverage_table() -> dict[str, dict[str, dict[str, Any]]]:
    """The whole table as plain data (docs, tooling)."""
    return {
        cls: {aspect: cell.as_dict() for aspect, cell in row.items()}
        for cls, row in SIZING_COVERAGE.items()
    }
