"""Zone volumes of the 3D model, from ``layout/zones.yaml``.

A zone is explicit (a ``box``, a ``cylinder`` from its base centre up, a ``sphere``) or derived
from release points (``sources``): each source is located in the model and the safety domain's
radius table (:mod:`chemeascode.domains.safety.area_classification`) gives the volumes around it
by source kind, release grade and substance class. The spatial side only places them.

Where a source is:

- a nozzle ``TAG/N1``: the nozzle's point (source kind ``flange``);
- a placed tag: a stack, silencer or vent: the top centre (``vent``); a pump: the centre of its
  casing end (``pump_seal``); a compressor, blower or turbine: its centre (``compressor_seal``);
  a safety valve (a special item): its top centre (``psv_outlet``); else its centre
  (``flange``);
- a line number: the open ends of its routes (``vent``; a safety valve there: ``psv_outlet``).

A source's ``source_kind`` and ``substance_class`` override what is derived.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.safety.area_classification import (
    SOURCE_KINDS,
    classify,
    substance_class,
)
from chemeascode.foundation.findings import Finding

ZONES_FILE = "layout/zones.yaml"


def _item_point(item: dict[str, Any]) -> tuple[tuple[float, float, float], str]:
    x0, y0, z0, x1, y1, z1 = item["bbox"]
    centre = ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2)
    family = item.get("family")
    type_name = (item.get("type") or "").lower()
    if family in ("stack", "silencer") or "vent" in type_name:
        return ((x0 + x1) / 2, (y0 + y1) / 2, z1), "vent"
    if "safetyvalve" in type_name or "reliefvalve" in type_name:
        return ((x0 + x1) / 2, (y0 + y1) / 2, z1), "psv_outlet"
    if family == "pump":
        return centre, "pump_seal"
    if family in ("compressor", "turbine"):
        return centre, "compressor_seal"
    return centre, "flange"


def locate(
    text: str, model: dict[str, Any]
) -> tuple[list[tuple[tuple[float, float, float], str]], str | None]:
    """The release points of a zone source *text* in *model* (``[(point, source kind)]``), or
    the reason it cannot be found."""
    equipment = {e["tag"]: e for e in model.get("equipment", [])}
    if "/" in text:
        tag, name = text.split("/", 1)
        item = equipment.get(tag)
        if item is not None:
            for nozzle in item["nozzles"]:
                if name in (nozzle["name"], nozzle["refs"].get("dexpi")):
                    return [(tuple(nozzle["point"]), "flange")], None
            return [], f"{tag} has no nozzle {name}"
    if text in equipment:
        point, kind = _item_point(equipment[text])
        return [(point, kind)], None
    ends = []
    for pipe in model.get("pipes", []):
        if pipe.get("line") != text:
            continue
        for end in pipe.get("open_ends", []):
            ends.append((tuple(pipe["points"][0 if end == "start" else -1]), "vent"))
    if ends:
        relief = {
            tuple(i["point"])
            for i in model.get("inline", [])
            if i.get("line") == text and i.get("kind") == "safety_valve"
        }
        found = []
        for point, kind in ends:
            near = any(
                sum((a - b) ** 2 for a, b in zip(point, r, strict=True)) < 1.0 for r in relief
            )
            found.append((point, "psv_outlet" if near else kind))
        return found, None
    if any(p.get("line") == text for p in model.get("pipes", [])):
        return [], f"line {text} has no open end (a vent or relief outlet)"
    return [], f"{text} is no placed tag, nozzle (TAG/N1) or routed line"


def zone_entries(zones: Any, model: dict[str, Any]) -> tuple[list[dict[str, Any]], list[Finding]]:
    """The model's ``zones`` for a parsed zone list, and findings for sources it cannot place
    or classify."""
    found: list[dict[str, Any]] = []
    findings: list[Finding] = []
    for zone in zones.zones if zones is not None else []:
        entry: dict[str, Any] = {
            "id": zone.id,
            "refs": {"file": ZONES_FILE},
            "source": "declared",
            "title": zone.title,
            "kind": zone.kind,
        }
        if zone.zone is not None:
            entry["zone"] = zone.zone
        volumes: list[dict[str, Any]] = []
        if zone.shape is not None:
            volume: dict[str, Any] = {"shape": zone.shape, "source": "declared"}
            if zone.shape == "box":
                volume["box"] = zone.box
            else:
                volume["centre"] = zone.centre
                volume["radius"] = zone.radius
                if zone.shape == "cylinder":
                    volume["height"] = zone.height
            volumes.append(volume)
        for source in zone.sources:
            points, problem = locate(source.item, model)
            if problem is not None:
                findings.append(
                    Finding(
                        ZONES_FILE,
                        "warning",
                        "cheme.layout-zone-source",
                        f"zone {zone.id}: source {source.item}: {problem}",
                        ids=[zone.id, source.item],
                        hint="name a placed tag, a nozzle as TAG/N1, or a routed line number",
                    )
                )
                continue
            cls = source.substance_class or substance_class(source.substance)
            if cls is None:
                findings.append(
                    Finding(
                        ZONES_FILE,
                        "warning",
                        "cheme.layout-zone-source",
                        f"zone {zone.id}: substance {source.substance!r} is not in the radius "
                        "table",
                        ids=[zone.id, source.item],
                        hint="give substance_class: oxygen, inert, flammable_gas or "
                        "flammable_liquid",
                    )
                )
                continue
            for point, derived in points:
                kind = source.source_kind or derived
                extents = [
                    e
                    for e in classify(kind, source.release_grade, cls)
                    if e.kind == zone.kind and (zone.zone is None or e.zone == zone.zone)
                ]
                if not extents:
                    findings.append(
                        Finding(
                            ZONES_FILE,
                            "warning",
                            "cheme.layout-zone-source",
                            f"zone {zone.id}: the radius table has no {zone.kind}"
                            + (f" zone {zone.zone}" if zone.zone is not None else "")
                            + f" row for a {kind} ({source.release_grade}, {cls})",
                            ids=[zone.id, source.item],
                            hint=f"set source_kind ({', '.join(SOURCE_KINDS)}), or give the "
                            "zone an explicit shape with its basis",
                        )
                    )
                    continue
                for extent in extents:
                    volume = {
                        "shape": extent.shape,
                        "source": "generated",
                        "centre": point if extent.shape == "sphere" else (point[0], point[1], 0.0),
                        "radius": extent.radius,
                        "item": source.item,
                        "source_kind": kind,
                        "release_grade": source.release_grade,
                        "substance_class": cls,
                        "basis": extent.basis,
                        "status": extent.status,
                    }
                    if extent.shape == "cylinder":
                        volume["height"] = point[2] + extent.radius
                    if extent.zone is not None and zone.zone is None and zone.kind == "hazardous":
                        volume["zone"] = extent.zone
                    volumes.append(volume)
        entry["volumes"] = volumes
        if zone.basis:
            entry["basis"] = zone.basis
        found.append(entry)
    return found, findings


def volume_box(volume: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    """The axis-aligned box of a zone volume."""
    if volume["shape"] == "box":
        return tuple(volume["box"])  # type: ignore[return-value]
    x, y, z = volume["centre"]
    r = volume["radius"]
    if volume["shape"] == "cylinder":
        return (x - r, y - r, z, x + r, y + r, z + volume["height"])
    return (x - r, y - r, z - r, x + r, y + r, z + r)


def volume_solid(volume: dict[str, Any], owner: str) -> Any:
    """The :mod:`~chemeascode.domains.spatial.geometry3d` solid of a zone volume."""
    from chemeascode.domains.spatial.geometry3d import Box, Cylinder, Sphere

    if volume["shape"] == "box":
        x0, y0, z0, x1, y1, z1 = volume["box"]
        return Box(
            owner, ((x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2), (x1 - x0, y1 - y0, z1 - z0)
        )
    x, y, z = volume["centre"]
    if volume["shape"] == "cylinder":
        return Cylinder(owner, (x, y, z), (x, y, z + volume["height"]), volume["radius"])
    return Sphere(owner, (x, y, z), volume["radius"])


def line_radii(zones: Any) -> dict[str, float]:
    """The largest sphere radius each zone source naming a line (no tag, no ``TAG/N1``) gets
    from the radius table, by line number: what a ``vents`` rule of ``routing.yaml`` keeps off
    the walking levels when it gives no ``radius_m`` (the router runs before the zones are
    placed). A source is taken as a ``vent`` unless it says its ``source_kind``."""
    found: dict[str, float] = {}
    for zone in zones.zones if zones is not None else []:
        for source in zone.sources:
            if "/" in source.item:
                continue
            cls = source.substance_class or substance_class(source.substance)
            if cls is None:
                continue
            for extent in classify(source.source_kind or "vent", source.release_grade, cls):
                if extent.shape == "sphere" and extent.kind == zone.kind:
                    found[source.item] = max(found.get(source.item, 0.0), extent.radius)
    return found
