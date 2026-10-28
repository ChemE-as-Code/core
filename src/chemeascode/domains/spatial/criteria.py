"""The layout criteria of the rules on the 3D model and the equipment and building spacing
tables.

Package data, every value ASSUMED with its basis: ``data/layout-criteria.yaml`` (operability,
escape, vent outlets, lifting), ``data/equipment-spacing.yaml`` (minimum distances between
items by family or DEXPI class) and ``data/building-spacing.yaml`` (between buildings by
``use``). A plant overrides the criteria in ``layout/site-plan.yaml`` under
``criteria:`` (:class:`~chemeascode.domains.spatial.schemas.LayoutCriteria`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).parent / "data"
CRITERIA = DATA / "layout-criteria.yaml"
SPACING = DATA / "equipment-spacing.yaml"


@cache
def _criteria_table() -> dict[str, Any]:
    return yaml.safe_load(CRITERIA.read_text(encoding="utf-8"))


@cache
def spacing_table() -> dict[str, Any]:
    """The equipment spacing table as data."""
    return yaml.safe_load(SPACING.read_text(encoding="utf-8"))


@dataclass
class Criteria:
    """The values in force: the package defaults with the plant's overrides; ``basis`` says
    where each comes from."""

    values: dict[str, float] = field(default_factory=dict)
    basis: dict[str, str] = field(default_factory=dict)
    spacing_table: bool = True

    def __getattr__(self, name: str) -> float:
        values = self.__dict__.get("values", {})
        if name in values:
            return values[name]
        raise AttributeError(name)


def criteria(plan: Any = None) -> Criteria:
    """The criteria for a parsed site plan *plan* (None: the package defaults)."""
    found = Criteria()
    for name, row in _criteria_table()["criteria"].items():
        found.values[name] = float(row["value"])
        found.basis[name] = f"{row['basis']} (package default)"
    given = getattr(plan, "criteria", None)
    if given is not None:
        for name, value in given:
            if name == "spacing_table":
                found.spacing_table = bool(value)
            elif value is not None:
                found.values[name] = float(value)
                found.basis[name] = "layout/site-plan.yaml criteria"
    return found


def _matches(side: dict[str, Any], item: dict[str, Any]) -> bool:
    if side.get("any"):
        return True
    families = side.get("family") or []
    if item.get("family") in families:
        return True
    cls = (item.get("type") or "").lower()
    return any(str(part).lower() in cls for part in side.get("class") or [])


def spacing_rows(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of the spacing table that apply to items *a* and *b* (either way round)."""
    return [
        row
        for row in spacing_table()["rows"]
        if (_matches(row["a"], a) and _matches(row["b"], b))
        or (_matches(row["a"], b) and _matches(row["b"], a))
    ]


BUILDING_SPACING = DATA / "building-spacing.yaml"


@cache
def building_spacing_table() -> dict[str, Any]:
    """The building spacing table as data."""
    return yaml.safe_load(BUILDING_SPACING.read_text(encoding="utf-8"))


def _building_matches(side: dict[str, Any], building: dict[str, Any]) -> bool:
    if side.get("any"):
        return True
    use = (building.get("use") or "").strip().lower()
    return bool(use) and use in {str(u).lower() for u in side.get("use") or []}


def building_spacing_rows(a: dict[str, Any], b: dict[str, Any]) -> list[dict[str, Any]]:
    """The rows of the building spacing table that apply to buildings *a* and *b*."""
    return [
        row
        for row in building_spacing_table()["rows"]
        if (_building_matches(row["a"], a) and _building_matches(row["b"], b))
        or (_building_matches(row["a"], b) and _building_matches(row["b"], a))
    ]
