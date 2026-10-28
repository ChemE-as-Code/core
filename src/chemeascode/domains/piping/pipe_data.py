"""Pipe sizes for the 3D model: outside diameter by DN (package data, ``data/pipe-od.yaml``),
insulation thickness by the line list's ``insulation`` (``piping/pipe-specs.yaml``, else
assumed defaults), and the pipe class of a line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

DATA = Path(__file__).parent / "data" / "pipe-od.yaml"


@cache
def _table() -> dict[str, Any]:
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


def parse_dn(text: Any) -> float | None:
    """The number of a DN: ``DN80``, ``DN 80``, ``80``, 80 -> 80.0; None when there is none."""
    if text is None:
        return None
    if isinstance(text, int | float):
        return float(text) if text > 0 else None
    found = re.search(r"\d+(?:\.\d+)?", str(text))
    return float(found.group(0)) if found else None


def outside_diameter(dn: float | None) -> float:
    """Outside diameter of a pipe of nominal diameter *dn*, m: the table's value, the next
    larger DN's for a DN not in it, about 1.02 x DN above the table; 0.06 m (DN 50) when the
    DN is unknown."""
    if dn is None or dn <= 0:
        dn = 50.0
    table = {float(k): float(v) for k, v in _table()["od_mm"].items()}
    for size in sorted(table):
        if size >= dn - 1e-9:
            return table[size] / 1000.0
    return dn * 1.02 / 1000.0


@dataclass(frozen=True)
class Insulated:
    """Insulation of a line: thickness in m and where it comes from."""

    thickness: float
    basis: str


def insulation(text: str | None, dn: float | None, specs: Any = None) -> Insulated:
    """The insulation thickness of a line with the line list's *text* and *dn*: a rule of
    *specs* (a parsed ``piping/pipe-specs.yaml``) whose type is the text (any case), else the
    assumed defaults of the package table by keyword; none without text or for a text that
    says so (``none``, ``bare``, ``uninsulated``, ..., the table's ``no_insulation``)."""
    if not text or not str(text).strip():
        return Insulated(0.0, "")
    wanted = str(text).strip().lower()
    for entry in getattr(specs, "insulation", None) or ():
        if entry.type.strip().lower() != wanted:
            continue
        if entry.thickness_mm is not None:
            return Insulated(entry.thickness_mm / 1000.0, "piping/pipe-specs.yaml")
        for rule in entry.rules:
            if rule.dn_max is None or (dn is not None and dn <= rule.dn_max + 1e-9):
                return Insulated(rule.thickness_mm / 1000.0, "piping/pipe-specs.yaml")
        last = entry.rules[-1]
        return Insulated(last.thickness_mm / 1000.0, "piping/pipe-specs.yaml")
    if " ".join(wanted.split()) in {str(item).lower() for item in _table()["no_insulation"]}:
        return Insulated(0.0, "line list: no insulation")
    words = set(re.findall(r"[a-z]+", wanted))
    for row in _table()["insulation_defaults"]:
        if all(word in words for word in row["match"]):
            return Insulated(row["thickness_mm"] / 1000.0, f"ASSUMED: {row['basis']}")
    return Insulated(0.05, "ASSUMED")


def pipe_class(code: str | None, specs: Any = None) -> dict[str, Any]:
    """``{code, material?, colour?}`` of a line's pressure class, from *specs* where listed."""
    if not code:
        return {}
    found: dict[str, Any] = {"code": code}
    for entry in getattr(specs, "classes", None) or ():
        if entry.code.strip().lower() == code.strip().lower():
            if entry.material:
                found["material"] = entry.material
            if entry.colour:
                found["colour"] = entry.colour
            break
    return found


SPANS = Path(__file__).parent / "data" / "pipe-spans.yaml"


@cache
def span_table() -> dict[str, Any]:
    """The support span table (``data/pipe-spans.yaml``) as data."""
    return yaml.safe_load(SPANS.read_text(encoding="utf-8"))


def is_liquid(fluid: str | None) -> bool:
    """Whether a line's *fluid* counts as a liquid for :func:`max_span` (a word of the table's
    ``liquid_words`` in its name, any case)."""
    if not fluid:
        return False
    name = fluid.lower()
    words = set(re.findall(r"[a-z0-9]+", name))
    for word in span_table()["liquid_words"]:
        word = str(word).lower()
        if (" " in word and word in name) or word in words:
            return True
    return False


def max_span(dn: float | None, liquid: bool) -> float:
    """The longest span between supports of a pipe of nominal diameter *dn*, m (ASSUMED,
    package table): the row of the largest DN at or below *dn* (the smallest row below it;
    DN 50 when unknown), its ``liquid`` or ``gas`` column."""
    rows = sorted(span_table()["rows"], key=lambda row: row["dn"])
    dn = 50.0 if dn is None or dn <= 0 else dn
    chosen = rows[0]
    for row in rows:
        if row["dn"] <= dn + 1e-9:
            chosen = row
    return float(chosen["liquid" if liquid else "gas"])
