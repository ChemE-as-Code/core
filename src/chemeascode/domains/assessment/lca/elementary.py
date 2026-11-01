"""Elementary-flow identities from the packaged crosswalk (``data/elementary-flows.yaml``).

An emission or resource of a dataset is identified by a UUID in a named reference list, not by
its CAS number: CAS distinguishes neither the compartment nor the origin, and many flows (PM2.5,
NMVOC) have none. :func:`identities` gives an elementary flow's identity in every list the
crosswalk holds, the primary list (EF 3.1) first: by its crosswalk id when the study names one
(``elementary.flow``), else by CAS number, compartment and origin among the default entries.
The crosswalk is small and curated: a flow it does not hold has no identity yet (a finding),
and an identity whose UUID is not verified is recorded with ``uuid: null`` (a finding).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.assessment.lca.methods import normalise_cas
from chemeascode.domains.assessment.lca.schemas import Elementary, FlowIdentity

DATA = Path(__file__).with_name("data") / "elementary-flows.yaml"
#: The primary list (docs/framework/lca.md, Direct emissions and resources).
PRIMARY = "ef-3.1"
#: Each sub-compartment's categories in biosphere3.
BIOSPHERE3_CATEGORIES: dict[tuple[str, str], tuple[str, ...]] = {
    ("air", "unspecified"): ("air",),
    ("air", "urban-close-to-ground"): ("air", "urban air close to ground"),
    ("air", "non-urban-high-stack"): ("air", "non-urban air or from high stacks"),
    ("air", "lower-stratosphere"): ("air", "lower stratosphere + upper troposphere"),
    ("water", "unspecified"): ("water",),
    ("water", "fresh-surface"): ("water", "surface water"),
    ("water", "ground"): ("water", "ground-"),
    ("water", "sea"): ("water", "ocean"),
    ("soil", "unspecified"): ("soil",),
    ("soil", "agricultural"): ("soil", "agricultural"),
    ("soil", "industrial"): ("soil", "industrial"),
    ("resource", "in-air"): ("natural resource", "in air"),
    ("resource", "in-water"): ("natural resource", "in water"),
    ("resource", "in-ground"): ("natural resource", "in ground"),
    ("resource", "land"): ("natural resource", "land"),
}
#: A resource's sub-compartment when the study gives none, by the crosswalk entry's.
_RESOURCE_SUB = ("in-air", "in-water", "in-ground", "land")


@cache
def crosswalk() -> dict[str, Any]:
    """The packaged crosswalk: ``source`` and ``flows`` (by id)."""
    data = yaml.safe_load(DATA.read_text(encoding="utf-8"))
    return {"source": data["source"], "flows": {f["id"]: f for f in data["flows"]}}


def _entry(cas: str | None, spec: Elementary) -> tuple[dict | None, str]:
    flows = crosswalk()["flows"]
    if spec.flow is not None:
        entry = flows.get(spec.flow)
        if entry is None:
            return None, f"no crosswalk flow {spec.flow!r}"
        if entry["compartment"] != spec.compartment:
            return None, f"crosswalk flow {spec.flow} is {entry['compartment']}"
        return entry, ""
    if cas is None:
        return None, "no CAS number and no crosswalk id (elementary.flow)"
    cas = normalise_cas(cas)
    found = [
        f
        for f in flows.values()
        if f.get("cas") == cas
        and f["compartment"] == spec.compartment
        and f.get("default", True)
        and f.get("origin", spec.origin) == spec.origin
    ]
    if len(found) != 1:
        return None, f"CAS {cas} {spec.compartment} {spec.origin} is not in the crosswalk"
    return found[0], ""


def identities(cas: str | None, spec: Elementary) -> tuple[list[FlowIdentity], str]:
    """The identities of the elementary flow of *cas* as *spec* maps it, the primary list's
    first; or ``([], why not)`` when the crosswalk does not hold it."""
    entry, problem = _entry(cas, spec)
    if entry is None:
        return [], problem
    bio = entry["biosphere3"]
    sub = spec.subcompartment
    if spec.compartment == "resource" and sub == "unspecified":
        sub = next(s for s in _RESOURCE_SUB if s in bio["uuid"])
    if sub not in bio["uuid"]:
        return [], f"{entry['id']} has no {spec.compartment}/{sub} flow in the crosswalk"
    found = [_primary(entry, sub)]
    found.append(
        FlowIdentity(
            list="biosphere3",
            uuid=bio["uuid"][sub],
            name=bio["name"],
            categories=list(BIOSPHERE3_CATEGORIES[(spec.compartment, sub)]),
            unit=bio["unit"],
            per_unit=bio.get("per_kg", 1.0),
        )
    )
    return found, ""


def _primary(entry: dict, sub: str) -> FlowIdentity:
    """The EF 3.1 identity of *entry* in *sub*: ``uuid: null`` until the crosswalk records the
    UUID read from the reference package (``scripts/fill_ef31_uuids.py``)."""
    ef = entry.get(PRIMARY) or {}
    uuid = (ef.get("uuid") or {}).get(sub)
    if uuid is None:
        return FlowIdentity(list=PRIMARY, uuid=None)
    return FlowIdentity(
        list=PRIMARY,
        uuid=uuid,
        name=ef.get("name", ""),
        categories=list((ef.get("categories") or {}).get(sub, [])),
        unit=ef.get("unit", ""),
        per_unit=ef.get("per_kg", 1.0),
    )


def unverified(flow: list[FlowIdentity]) -> bool:
    """Whether the primary list's identity of *flow* lacks its UUID."""
    return not flow or flow[0].list != PRIMARY or flow[0].uuid is None


#: CAS number of water.
WATER_CAS = "7732-18-5"
#: kg of water per m3 (the LCI convention, as in the crosswalk's ``per_kg``).
WATER_KG_PER_M3 = 1000.0


def _compartment(exchange: Any) -> str | None:
    if exchange.link is not None and exchange.link.elementary is not None:
        return exchange.link.elementary.compartment
    bio = next((f for f in exchange.flow if f.list == "biosphere3" and f.categories), None)
    if bio is None:
        return None
    return "resource" if bio.categories[0] == "natural resource" else bio.categories[0]


def water_balance(dataset: Any) -> dict[str, float] | None:
    """The water of *dataset*'s elementary flows, m3 per its basis: ``withdrawal`` (resources),
    ``returned`` (emitted to water), ``evaporated`` (emitted to air) and ``consumption``
    (withdrawal minus returned); None when it has no water flow. Water in kg counts at
    1000 kg/m3."""
    found = {"withdrawal": 0.0, "returned": 0.0, "evaporated": 0.0}
    seen = False
    for exchange in dataset.exchanges:
        if exchange.type not in ("emission", "resource"):
            continue
        if normalise_cas(exchange.cas or "") != WATER_CAS:
            continue
        m3 = exchange.amount / WATER_KG_PER_M3 if exchange.unit == "kg" else exchange.amount
        if exchange.unit not in ("kg", "m3"):
            continue
        compartment = _compartment(exchange)
        key = {"resource": "withdrawal", "water": "returned", "air": "evaporated"}.get(
            compartment or ("resource" if exchange.type == "resource" else "")
        )
        if key is None:
            continue
        found[key] += m3
        seen = True
    if not seen:
        return None
    found["consumption"] = found["withdrawal"] - found["returned"]
    return found
