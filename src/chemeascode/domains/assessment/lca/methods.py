"""Packaged characterisation of direct emissions (``data/methods.yaml``), by CAS number.

A category of ``lca/factors.yaml`` names one (``elementary: ipcc2021-gwp100``): the plant's
emissions mapped ``elementary: {compartment, origin}`` are then characterised in it by the
factor of their component's CAS number. Supply-chain impacts stay with the factors.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import yaml

DATA = Path(__file__).with_name("data") / "methods.yaml"


@cache
def _table() -> dict:
    return yaml.safe_load(DATA.read_text(encoding="utf-8"))


def categories() -> dict[str, dict]:
    """Every packaged category by id (``<method>-<category>``): title, unit, method, source."""
    found = {}
    for method, entry in _table().items():
        for name, category in entry["categories"].items():
            found[f"{method}-{name}"] = {
                **category,
                "method": entry["title"],
                "source": " ".join(entry["source"].split()),
            }
    return found


def normalise_cas(text: object) -> str:
    """A CAS number without spaces and zero padding (000124-38-9 -> 124-38-9)."""
    value = str(text or "").strip().replace(" ", "")
    head, _, rest = value.partition("-")
    return f"{head.lstrip('0') or '0'}-{rest}" if rest else value


def factor(category: str, cas: str | None, compartment: str, origin: str) -> float | None:
    """The factor per kg of *cas* emitted to *compartment* with *origin* in the packaged
    *category* (None when the method has none: the emission is not characterised)."""
    method, _, name = category.partition("-")
    entry = _table().get(method)
    if entry is None or cas is None:
        return None
    cas = normalise_cas(cas)
    for row in entry["factors"]:
        if (
            row["cas"] == cas
            and row.get("compartment", "air") == compartment
            and row.get("origin", origin) == origin
            and name in row
        ):
            return float(row[name])
    return None


def listed(category: str, cas: str | None, compartment: str) -> bool:
    """Whether the packaged *category* characterises *cas* in *compartment* for some origin
    (an emission of another origin is then a gap, not outside the method)."""
    method, _, name = category.partition("-")
    entry = _table().get(method)
    if entry is None or cas is None:
        return False
    cas = normalise_cas(cas)
    return any(
        row["cas"] == cas and row.get("compartment", "air") == compartment and name in row
        for row in entry["factors"]
    )
