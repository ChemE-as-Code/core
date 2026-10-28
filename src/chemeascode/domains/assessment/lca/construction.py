"""The construction phase: bulk materials of the take-off and the equipment's weight.

:func:`construction` counts, for each ``construction:`` entry of ``lca/lca.yaml``, the rows of
``estimate/mto.csv`` (``takeoff: mto``) or the equipment-list items (``takeoff: equipment``) it
matches; a row or item is counted by the first entry that matches it, as a rate prices a row
in the estimate. Quantities are converted to the inventory's units (t to kg). What no entry
counts, and equipment without a weight, is reported.

The totals are the whole plant's; the inventory spreads them over the plant's output in its
life (``operation``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from fnmatch import fnmatchcase

from chemeascode.domains.assessment.estimate import rate_matches
from chemeascode.domains.assessment.lca.schemas import FACTOR_UNITS, INVENTORY_UNITS, Construction
from chemeascode.domains.assessment.mto import MtoRow
from chemeascode.domains.equipment.schemas.equipment import EquipmentItem


@dataclass
class Counted:
    """What one construction entry counts."""

    entry: Construction
    quantity: float = 0.0
    unit: str = ""
    #: Take-off row keys or equipment tags.
    items: list[str] = field(default_factory=list)


@dataclass
class ConstructionCount:
    counted: list[Counted] = field(default_factory=list)
    #: Take-off rows no entry counts, as ``key (quantity unit)``.
    rows_left: list[str] = field(default_factory=list)
    #: Equipment tags no entry counts.
    items_left: list[str] = field(default_factory=list)
    #: Equipment tags an entry matches but that have no ``dimensions.weight``.
    no_weight: list[str] = field(default_factory=list)
    #: (entry id, tag) of each item without a weight: a gap of that entry, never 0.
    no_weight_entries: list[tuple[str, str]] = field(default_factory=list)
    #: Entries whose rows come in different units, or in a unit the inventory has no kind for.
    unit_problems: list[str] = field(default_factory=list)


def _number(text: str) -> float | None:
    return float(text) if text not in ("", None) else None


def read_takeoff(text: str) -> list[MtoRow]:
    """The rows of an ``estimate/mto.csv`` text (``cheme assess mto --write``)."""
    rows = []
    for record in csv.DictReader(io.StringIO(text)):
        rows.append(
            MtoRow(
                record["category"],
                record["item"],
                _number(record.get("dn", "")),
                _number(record.get("dn2", "")),
                record.get("class", ""),
                record.get("spec", ""),
                record.get("group", ""),
                int(float(record.get("count") or 0)),
                float(record.get("quantity") or 0),
                record.get("unit", ""),
                _number(record.get("length_m", "")),
            )
        )
    return rows


def _equipment_matches(entry: Construction, item: EquipmentItem) -> bool:
    where = entry.equipment

    def glob(pattern: str | None, value: str | None) -> bool:
        return pattern is None or fnmatchcase(value or "", pattern)

    return (
        glob(where.tag, item.tag)
        and glob(where.type, item.type)
        and glob(where.material, item.material)
    )


def _add(counted: Counted, quantity: float, unit: str, name: str, problems: list[str]) -> None:
    kind, per = FACTOR_UNITS.get(unit, (None, 1.0))
    if kind is None:
        problems.append(f"{counted.entry.id}: {name} is in {unit!r}")
        return
    target = INVENTORY_UNITS[kind]
    if counted.unit and counted.unit != target:
        problems.append(
            f"{counted.entry.id}: {name} is in {target}, the entry counts {counted.unit}"
        )
        return
    counted.unit = target
    counted.quantity += quantity * per
    counted.items.append(name)


def construction(
    entries: list[Construction],
    rows: list[MtoRow] | None,
    equipment: list[EquipmentItem] | None,
) -> ConstructionCount:
    """What *entries* count of the take-off *rows* and the *equipment* (None: not available)."""
    result = ConstructionCount()
    counted = {entry.id: Counted(entry) for entry in entries}
    mto_entries = [e for e in entries if e.takeoff == "mto"]
    equipment_entries = [e for e in entries if e.takeoff == "equipment"]
    for row in rows or []:
        entry = next((e for e in mto_entries if rate_matches(e, row)), None)
        if entry is None:
            result.rows_left.append(f"{row.key} ({row.quantity:g} {row.unit})")
            continue
        _add(counted[entry.id], row.quantity, row.unit, row.key, result.unit_problems)
    for item in equipment or []:
        entry = next((e for e in equipment_entries if _equipment_matches(e, item)), None)
        if entry is None:
            result.items_left.append(item.tag)
            continue
        weight = item.dimensions.weight if item.dimensions else None
        if weight is None:
            result.no_weight.append(item.tag)
            result.no_weight_entries.append((entry.id, item.tag))
            continue
        _add(counted[entry.id], weight, "t", item.tag, result.unit_problems)
    result.counted = list(counted.values())
    return result
