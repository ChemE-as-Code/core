"""Hazard data of a chemical from the OSHA Occupational Chemical Database, in SI units with its
source: flash point in K, explosive limits in vol-%, NFPA ratings, exposure limits as given.

These are screening values from one public database. A HAZOP or a relief study takes them as
evidence to check, not as the design basis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.foundation.units import UnitError, convert_units
from chemeascode.integrations.http import HttpClient

_EXPOSURE = ("osha_twa", "niosh_twa", "acgih_twa", "cal_osha_twa")
_EXPOSURE += ("osha_stel", "niosh_stel", "acgih_stel", "cal_osha_stel", "idlh")


@dataclass(frozen=True)
class HazardData:
    cas: str
    name: str | None = None
    flash_point_K: float | None = None
    flash_point_range_K: tuple[float, float] | None = None
    """When OSHA gives a range; ``flash_point_K`` is then its lower end (the conservative one)."""
    lower_explosive_limit_vol_pct: float | None = None
    upper_explosive_limit_vol_pct: float | None = None
    nfpa_health: float | None = None
    nfpa_fire: float | None = None
    nfpa_reactivity: float | None = None
    exposure_limits: dict[str, dict[str, Any]] = field(default_factory=dict)
    """``osha_twa``, ``niosh_stel``, ``idlh``, ... as ``{"value", "units"}`` (ppm or mg/m³)."""
    source: str = "OSHA Occupational Chemical Database"
    source_url: str | None = None
    notes: tuple[str, ...] = ()


def _kelvin(value: float, units: str) -> float:
    return convert_units(value, units, "K") if units != "°F" else (value - 32) * 5 / 9 + 273.15


def _percent(entry: Any, field_name: str, notes: list[str]) -> float | None:
    if not entry:
        return None
    if entry.get("units") in ("%", None):
        return float(entry["value"])
    notes.append(f"{field_name}: unit {entry.get('units')!r} is not vol-%, value left out")
    return None


def from_osha_record(cas: str, record: dict[str, Any]) -> HazardData:
    """:class:`HazardData` from what :func:`chemeascode.integrations.osha.retrieve` returns."""
    notes: list[str] = []
    flash = record.get("flash_point")
    flash_K = flash_range = None
    if flash:
        try:
            flash_K = _kelvin(float(flash["value"]), flash["units"])
            if "range" in flash:
                low, high = (_kelvin(float(v), flash["units"]) for v in flash["range"])
                flash_range = (low, high)
        except (UnitError, KeyError, ValueError) as failure:
            notes.append(f"flash_point not converted: {failure}")
    return HazardData(
        cas=record.get("cas") or cas,
        name=record.get("name"),
        flash_point_K=flash_K,
        flash_point_range_K=flash_range,
        lower_explosive_limit_vol_pct=_percent(record.get("lower_explosive_limit"), "LEL", notes),
        upper_explosive_limit_vol_pct=_percent(record.get("upper_explosive_limit"), "UEL", notes),
        nfpa_health=record.get("nfpa_health_rating"),
        nfpa_fire=record.get("nfpa_fire_rating"),
        nfpa_reactivity=record.get("nfpa_reactivity_rating"),
        exposure_limits={k: record[k] for k in _EXPOSURE if k in record},
        source_url=record.get("source_url"),
        notes=tuple(notes),
    )


def hazard_data(cas: str, *, client: HttpClient | None = None) -> HazardData | None:
    """The OSHA hazard data of the chemical with CAS number *cas*, or None if it is not listed.
    Network access through :mod:`chemeascode.integrations.osha`."""
    from chemeascode.integrations.osha import retrieve

    record = retrieve(cas, client=client)
    return None if record is None else from_osha_record(cas, record)
