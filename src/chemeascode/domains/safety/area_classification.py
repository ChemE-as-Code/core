"""Zones around release points: which zone kind, hazardous zone number and indicative radius a
release point gets, from the package table ``data/release-radii.yaml``.

A screening classification for the 3D layout, not an area classification study: every row is
marked ASSUMED and carries its basis text; no dispersion is modelled. The spatial domain turns
the result into volumes around the release points (``domains/spatial/zones.py``).

Release point kinds: ``vent`` (an open vent, stack, silencer or line end to atmosphere),
``psv_outlet``, ``pump_seal``, ``compressor_seal``, ``flange``, ``valve``, ``drain``. Release
grades: ``continuous``, ``primary``, ``secondary`` (IEC 60079-10-1). Substance classes:
``oxygen``, ``inert``, ``flammable_gas``, ``flammable_liquid``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

TABLE = Path(__file__).parent / "data" / "release-radii.yaml"
SOURCE_KINDS = ("vent", "psv_outlet", "pump_seal", "compressor_seal", "flange", "valve", "drain")


@dataclass(frozen=True)
class ZoneExtent:
    """One volume around a release point."""

    kind: str  # hazardous, oxygen_enriched, oxygen_deficient
    zone: int | None
    radius: float
    shape: str  # sphere, cylinder (from grade up to the point plus the radius)
    basis: str
    status: str = "ASSUMED"


@cache
def table() -> dict[str, Any]:
    """The radius table as data."""
    return yaml.safe_load(TABLE.read_text(encoding="utf-8"))


def substance_class(substance: str) -> str | None:
    """The table's class of a substance name (any case, word match), None when unknown."""
    name = re.sub(r"\s+", " ", substance.strip().lower())
    for cls, names in table()["substances"].items():
        if name == cls or name in (n.lower() for n in names):
            return cls
    words = set(re.findall(r"[a-z0-9]+", name))
    for cls, names in table()["substances"].items():
        if any(n.lower() in words for n in names if " " not in n):
            return cls
    return None


def classify(source: str, grade: str, cls: str) -> list[ZoneExtent]:
    """The volumes of a release point of kind *source* and release *grade* for substance class
    *cls*; empty when the table has no row for it."""
    found = []
    for row in table()["rows"]:
        if row["source"] == source and row["grade"] == grade and row["substance"] == cls:
            found.append(
                ZoneExtent(
                    kind=row["kind"],
                    zone=row.get("zone"),
                    radius=float(row["radius_m"]),
                    shape=row.get("shape", "sphere"),
                    basis=row["basis"],
                    status=table().get("status", "ASSUMED"),
                )
            )
    return found
