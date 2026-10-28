"""The piping network of a P&ID, for routing pipes in 3D.

For every piping network system (a line number) of a loaded DEXPI model: its segments, each
with its DN and fluid, its two ends and the items along it in flow order. An end is

- ``nozzle``: a nozzle of a tagged equipment item (its DEXPI id, name and the item's tag);
- ``tee``: a node of a ``PipeTee`` (node 0 the inlet, 1 the run outlet, 2 the branch);
- ``opc_in`` / ``opc_out``: an off-page connector, joined with the other sheet's one of the
  same line number;
- ``item``: a piping component the line ends at (a safety valve or silencer discharging to
  atmosphere, a vent);
- ``none``: nothing.

The in-line items are the segment's piping components other than tees and off-page
connectors, in the order the segment's connections pass them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from chemeascode.domains.spatial.pid_nozzles import _number


@dataclass(frozen=True)
class End:
    kind: str  # nozzle, tee, opc_in, opc_out, item, none
    ref: str = ""  # DEXPI id of the nozzle, tee, connector or item
    node: int | None = None  # tee node index
    tag: str | None = None  # the equipment tag of a nozzle, the tag of an item
    name: str = ""  # a nozzle's name (SubTagName), else its DEXPI id
    cls: str = ""


@dataclass(frozen=True)
class InlineItem:
    dexpi_id: str
    cls: str
    tag: str | None
    kind: str


@dataclass(frozen=True)
class Segment:
    sheet: str
    line: str
    system: str
    id: str
    number: str
    dn: float | None
    fluid: str | None
    source: End
    target: End
    items: tuple[InlineItem, ...] = ()


def inline_kind(cls: str) -> str:
    """``safety_valve``, ``check_valve``, ``valve``, ``reducer``, ``silencer``, ``filter``,
    ``instrument``, ``item`` by DEXPI class name."""
    if re.search(r"Safety|Relief|RuptureDisc|BurstingDisc", cls):
        return "safety_valve"
    if "CheckValve" in cls:
        return "check_valve"
    if cls.endswith(("Valve", "Cock")):
        return "valve"
    if "Reducer" in cls:
        return "reducer"
    if "Silencer" in cls:
        return "silencer"
    if "Strainer" in cls or "Filter" in cls:
        return "filter"
    if any(word in cls for word in ("Flow", "Meter", "Orifice", "Measuring", "Sensor")):
        return "instrument"
    return "item"


def _tag(obj: Any) -> str | None:
    from pydexpi.toolkits.display_name import get_tag

    try:
        tag = get_tag(obj)
    except Exception:  # noqa: BLE001 - an item without tag data has no tag
        tag = None
    # a safety valve often carries its tag as its PositionNumber (PSV-3114)
    for name in ("pipingComponentNumber", "tagName", "positionNumber"):
        tag = tag or getattr(obj, name, None)
    return (str(tag).strip() or None) if tag else None


def _dn(obj: Any) -> float | None:
    for name in ("nominalDiameterNumericalValueRepresentation", "nominalDiameterRepresentation"):
        value = _number(getattr(obj, name, None))
        if value is not None:
            return float(value)
    return None


def sheet_network(model: Any, sheet: str) -> list[Segment]:
    """Every piping segment of a loaded *model* (sheet *sheet*), in file order."""
    from pydexpi.pydexpi_classes.pydexpi_classes import TaggedPlantItem
    from pydexpi.toolkits.model_toolkit import get_all_instances_in_model

    owners: dict[int, str] = {}
    for obj in get_all_instances_in_model(model):
        if isinstance(obj, TaggedPlantItem):
            tag = _tag(obj)
            for nozzle in getattr(obj, "nozzles", None) or ():
                if tag:
                    owners.setdefault(id(nozzle), tag)

    def end(item: Any, node: Any) -> End:
        if item is None:
            return End("none")
        cls = type(item).__name__
        ref = getattr(item, "id", None) or ""
        if id(item) in owners or cls.endswith("Nozzle"):
            name = (getattr(item, "subTagName", None) or "").strip() or ref
            return End("nozzle", ref, None, owners.get(id(item)), name, cls)
        if cls == "PipeTee" or cls.endswith("Tee"):
            nodes = list(getattr(item, "nodes", None) or ())
            index = next((i for i, n in enumerate(nodes) if n is node), None)
            return End("tee", ref, index, None, ref, cls)
        if "OffPageConnector" in cls:
            kind = "opc_in" if "FlowIn" in cls else "opc_out"
            return End(kind, ref, None, None, ref, cls)
        return End("item", ref, None, _tag(item), ref, cls)

    found: list[Segment] = []
    conceptual = model.conceptualModel
    for system in getattr(conceptual, "pipingNetworkSystems", None) or ():
        line = (getattr(system, "lineNumber", None) or "").strip() or (system.id or "")
        for segment in system.segments or ():
            ordered: list[Any] = []
            seen: set[int] = set()
            ends = {id(segment.sourceItem), id(segment.targetItem)}
            for connection in segment.connections or ():
                for item in (connection.sourceItem, connection.targetItem):
                    if item is None or id(item) in seen:
                        continue
                    seen.add(id(item))
                    ordered.append(item)
            for item in segment.items or ():
                if id(item) not in seen:
                    seen.add(id(item))
                    ordered.append(item)
            items = []
            for item in ordered:
                cls = type(item).__name__
                if cls.endswith("Nozzle") or cls == "PipeTee" or "OffPageConnector" in cls:
                    continue
                if cls == "Pipe" or (id(item) in ends and inline_kind(cls) == "item"):
                    continue
                items.append(InlineItem(item.id or "", cls, _tag(item), inline_kind(cls)))
            found.append(
                Segment(
                    sheet=sheet,
                    line=line,
                    system=system.id or "",
                    id=segment.id or "",
                    number=(getattr(segment, "segmentNumber", None) or "").strip(),
                    dn=_dn(segment) or _dn(system),
                    fluid=getattr(segment, "fluidCode", None) or getattr(system, "fluidCode", None),
                    source=end(segment.sourceItem, segment.sourceNode),
                    target=end(segment.targetItem, segment.targetNode),
                    items=tuple(items),
                )
            )
    return found
