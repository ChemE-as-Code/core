"""``cheme show``: where an object is in a sheet, and what it is connected to.

Works on the XML alone (no pyDEXPI load), so it also helps with a sheet that does not load. An
object is found by its XML id or by a tag the file gives it: ``TagName``, the printed instrument
tag (``PICSA-4712.02``, also without the hyphen or with a space), ``LineNumber``,
``PipingComponentNumber``, ``PipingComponentName`` or a function number. Every location is
``file:line`` or ``file:start-end`` (the lines of the ``<Object>`` block).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.diffview import _represented_by
from chemeascode.domains.piping.sheet_query import component_tag

#: Data properties that hold a tag, in the order one is chosen to name an object (after the
#: printed tag of an instrument or a piping component).
TAG_PROPERTIES = (
    "TagName",
    "LineNumber",
    "PipingComponentNumber",
    "PositionNumber",
    "PipingComponentName",
    "ActuatingSystemNumber",
    "ProcessSignalGeneratingFunctionNumber",
    "ActuatingFunctionNumber",
    "SignalConveyingFunctionNumber",
    "ProcessInstrumentationFunctionNumber",
    "InstrumentationLoopFunctionNumber",
    "SubTagName",
    "SegmentNumber",
)

_DN_PROPERTIES = ("NominalDiameterRepresentation", "NominalDiameterNumericalValueRepresentation")

#: A start or end tag (attribute values may hold ``>``), or markup that is not an element.
_MARKUP = re.compile(
    r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<!DOCTYPE[^>]*>"
    r"|<(/?)([^\s/>!?]+)((?:[^>\"']|\"[^\"]*\"|'[^']*')*?)(/?)>",
    re.DOTALL,
)


class ShowError(Exception):
    """The sheet cannot be read as XML."""


def element_spans(content: bytes) -> list[tuple[int, int]]:
    """The first and last line of every element, in document order (as ``root.iter()``)."""
    text = content.decode("utf-8", errors="replace")
    spans: list[list[int]] = []
    stack: list[int] = []
    line, position = 1, 0
    for match in _MARKUP.finditer(text):
        line += text.count("\n", position, match.start())
        position = match.start()
        closing, name, _, empty = match.group(1, 2, 3, 4)
        if name is None:
            continue
        end_line = line + match.group(0).count("\n")
        if closing:
            if stack:
                spans[stack.pop()][1] = end_line
        else:
            spans.append([line, end_line])
            if not empty:
                stack.append(len(spans) - 1)
    return [(start, end) for start, end in spans]


def short_class(element: etree._Element) -> str:
    """``Plant/Piping.PipeTee`` -> ``PipeTee``."""
    return element.get("type", element.tag).rsplit("/", 1)[-1].rsplit(".", 1)[-1]


def data_value(element: etree._Element, prop: str) -> str | None:
    """The text of a direct ``<Data property=prop>`` (a String or a DataReference's literal)."""
    data = element.find(f"Data[@property='{prop}']")
    if data is None:
        return None
    for child in data:
        if child.tag == "DataReference" and child.get("data"):
            return child.get("data").rsplit(".", 1)[-1]
        text = "".join(child.itertext()).strip()
        if text:
            return text
    return None


def instrument_tag(element: etree._Element) -> str | None:
    """The printed tag of a ProcessInstrumentationFunction: ``PICSA-4712.02``."""
    if not element.get("type", "").endswith("ProcessInstrumentationFunction"):
        return None
    letters = "".join(
        v
        for v in (
            data_value(element, "ProcessInstrumentationFunctionCategory"),
            data_value(element, "ProcessInstrumentationFunctions"),
        )
        if v
    )
    number = data_value(element, "ProcessInstrumentationFunctionNumber")
    if letters and number:
        return f"{letters}-{number}"
    return letters or number


def piping_component_tag(element: etree._Element) -> str | None:
    """The printed tag of a piping component (:func:`sheet_query.component_tag`), else None."""
    return component_tag(
        *(
            data_value(element, p)
            for p in ("PipingComponentNumber", "PositionNumber", "PipingComponentName")
        )
    )


def _normal(text: str) -> str:
    return re.sub(r"[\s\-_]", "", text).upper()


@dataclass
class Sheet:
    """One sheet's XML with an index of ids, tags, references and drawings."""

    name: str
    root: etree._Element
    span: dict[etree._Element, tuple[int, int]]
    by_id: dict[str, etree._Element] = field(default_factory=dict)
    incoming: dict[str, list[tuple[etree._Element, str]]] = field(default_factory=dict)
    drawings: dict[str, list[etree._Element]] = field(default_factory=dict)
    owner: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path, name: str | None = None) -> Sheet:
        content = path.read_bytes()
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        try:
            root = etree.fromstring(content, parser)
        except etree.XMLSyntaxError as failure:
            raise ShowError(f"{name or path}: not well-formed XML: {failure}") from failure
        elements = [e for e in root.iter() if isinstance(e.tag, str)]
        spans = element_spans(content)
        if len(spans) != len(elements):  # unexpected markup: fall back to start lines
            spans = [(e.sourceline or 0, e.sourceline or 0) for e in elements]
        sheet = cls(name or str(path), root, dict(zip(elements, spans, strict=True)))
        for element in elements:
            if element.tag == "Object" and element.get("id"):
                sheet.by_id.setdefault(element.get("id"), element)
            if element.tag == "References":
                holder = element.getparent()
                prop = element.get("property", "")
                for target in element.get("objects", "").split():
                    target = target.lstrip("#")
                    if prop == "Represents":
                        sheet.drawings.setdefault(target, []).append(holder)
                    else:
                        sheet.incoming.setdefault(target, []).append((element, prop))
        sheet.owner = _represented_by(root)[1]
        return sheet

    # -- naming --------------------------------------------------------------------------------

    def tags(self, element: etree._Element) -> list[str]:
        """Every tag the file gives *element*, the one to show first."""
        found = [instrument_tag(element), piping_component_tag(element)]
        found += [data_value(element, prop) for prop in TAG_PROPERTIES]
        return list(dict.fromkeys(t for t in found if t))

    def tag(self, element: etree._Element) -> str | None:
        tags = self.tags(element)
        return tags[0] if tags else None

    def where(self, element: etree._Element) -> str:
        start, end = self.span.get(element, (element.sourceline or 0,) * 2)
        return f"{self.name}:{start}" + (f"-{end}" if end != start else "")

    def line(self, element: etree._Element) -> str:
        return f"{self.name}:{self.span.get(element, (element.sourceline or 0,))[0]}"

    def label(self, element: etree._Element) -> str:
        """``Pipe5 (Pipe)`` or ``ButterflyValve1 (ButterflyValve 66KL21)``."""
        tag = self.tag(element)
        object_id = element.get("id") or "(no id)"
        return f"{object_id} ({short_class(element)}{' ' + tag if tag else ''})"

    def ref_label(self, target: str) -> str:
        element = self.by_id.get(target)
        if element is None:
            return f"{target} (missing: no object has this id)"
        return f"{self.label(element)} {self.line(element)}"

    # -- finding --------------------------------------------------------------------------------

    def find(self, key: str) -> list[etree._Element]:
        """Objects whose id is *key*, else whose tag is *key* (exactly, then loosely)."""
        if key in self.by_id:
            return [self.by_id[key]]
        objects = list(self.root.iter("Object"))
        exact = [e for e in objects if key in self.tags(e)]
        if exact:
            return exact
        wanted = _normal(key)
        return [e for e in objects if wanted and any(_normal(t) == wanted for t in self.tags(e))]

    def names(self) -> list[str]:
        """Every id and tag, for suggestions."""
        names = list(self.by_id)
        for element in self.root.iter("Object"):
            names.extend(self.tags(element))
        return names


def _object_children(element: etree._Element, prop: str) -> list[etree._Element]:
    return [
        child
        for components in element.findall(f"Components[@property='{prop}']")
        for child in components.findall("Object")
    ]


def _dn(element: etree._Element) -> str:
    for prop in _DN_PROPERTIES:
        value = data_value(element, prop)
        if value:
            return value if not value.isdigit() else f"DN {value}"
    return "DN ?"


def _references(element: etree._Element) -> dict[str, str]:
    """The direct references of *element*: property -> first target id."""
    return {
        r.get("property", ""): r.get("objects", "").split()[0].lstrip("#")
        for r in element.findall("References")
        if r.get("objects", "").split()
    }


def _node_text(sheet: Sheet, item: str | None, node: str | None) -> str:
    if not item and not node:
        return "?"
    text = item or "?"
    if node:
        element = sheet.by_id.get(node)
        dn = f" {_dn(element)}" if element is not None else " (missing)"
        text += f".{node}{dn}"
    return text


def _piping(sheet: Sheet, element: etree._Element, indent: str) -> list[str]:
    """Segments, pipes, items and nodes (with DN) of a PipingNetworkSystem or segment."""
    lines: list[str] = []
    kind = short_class(element)
    if kind == "PipingNetworkSystem":
        lines.append(f"{indent}system {sheet.label(element)} {_dn(element)} {sheet.where(element)}")
        segments = _object_children(element, "Segments")
        lines.append(f"{indent}segments ({len(segments)}):")
        for segment in segments:
            lines += _piping(sheet, segment, indent + "  ")
        return lines
    refs = _references(element)
    ends = (
        f"{_node_text(sheet, refs.get('SourceItem'), refs.get('SourceNode'))} -> "
        f"{_node_text(sheet, refs.get('TargetItem'), refs.get('TargetNode'))}"
    )
    lines.append(f"{indent}{sheet.label(element)} {_dn(element)} {sheet.where(element)}")
    lines.append(f"{indent}  ends: {ends}")
    for pipe in _object_children(element, "Connections"):
        pipe_refs = _references(pipe)
        lines.append(
            f"{indent}  connection {pipe.get('id') or '(no id)'} ({short_class(pipe)}) "
            f"{sheet.where(pipe)}: "
            f"{_node_text(sheet, pipe_refs.get('SourceItem'), pipe_refs.get('SourceNode'))} -> "
            f"{_node_text(sheet, pipe_refs.get('TargetItem'), pipe_refs.get('TargetNode'))}"
        )
    for item in _object_children(element, "Items"):
        lines.append(f"{indent}  item {sheet.label(item)} {sheet.where(item)}")
        for node in _object_children(item, "Nodes"):
            lines.append(
                f"{indent}    node {node.get('id') or '(no id)'} {_dn(node)} {sheet.line(node)}"
            )
    return lines


def extent(drawing: etree._Element) -> str | None:
    """``X0,Y0,X1,Y1`` (sheet mm, Y down) of the points in *drawing*, for ``render --crop``."""
    xs: list[float] = []
    ys: list[float] = []
    for point in drawing.iter("AggregatedDataValue"):
        if point.get("type") != "Core/Diagram.Point":
            continue
        x, y = data_value(point, "X"), data_value(point, "Y")
        try:
            xs.append(float(x or ""))
            ys.append(float(y or ""))
        except ValueError:
            continue
    if not xs:
        return None
    return ",".join(f"{value:g}" for value in (min(xs), min(ys), max(xs), max(ys)))


def _instrumentation_once(
    sheet: Sheet, element: etree._Element, seen: set[tuple[str, ...]] | None
) -> list[str]:
    """:func:`instrumentation`, or a pointer back when *seen* holds the same block already
    (a valve, its actuating system and function share one tag and one control chain)."""
    block = instrumentation(sheet, element)
    if seen is None or not block:
        return block
    key = tuple(block)
    if key in seen:
        return ["  instrumentation: as above"]
    seen.add(key)
    return block


def describe(
    sheet: Sheet, element: etree._Element, seen: set[tuple[str, ...]] | None = None
) -> list[str]:
    """Everything ``cheme show`` prints about one object; *seen*: instrumentation blocks
    printed for other objects already."""
    object_id = element.get("id")
    tags = sheet.tags(element)
    lines = [
        f"{sheet.where(element)} {short_class(element)} {object_id or '(no id)'}"
        + (f" [{tags[0]}]" if tags else "")
    ]
    if len(tags) > 1:
        lines.append("  also tagged: " + ", ".join(tags[1:]))
    chain = [
        sheet.label(ancestor) + " " + sheet.line(ancestor)
        for ancestor in element.iterancestors("Object")
    ]
    lines.append("  owner: " + (" < ".join(chain) if chain else "(top level)"))

    drawings = sheet.drawings.get(object_id or "", [])
    if drawings:
        for drawing in drawings:
            region = extent(drawing)
            lines.append(
                f"  drawn by: {sheet.label(drawing)} {sheet.where(drawing)}"
                + (f" at {region} mm" if region else "")
            )
    elif object_id and object_id in sheet.owner:
        lines.append(f"  drawn as part of: {sheet.ref_label(sheet.owner[object_id])}")
    else:
        lines.append("  drawn by: nothing (no RepresentationGroup represents it)")

    outgoing = [
        (reference, target.lstrip("#"))
        for reference in element.findall("References")
        for target in reference.get("objects", "").split()
    ]
    lines.append(f"  references ({len(outgoing)}):")
    for reference, target in outgoing:
        lines.append(
            f"    {sheet.line(reference)} {reference.get('property', '')} -> "
            f"{sheet.ref_label(target)}"
        )
    incoming = sheet.incoming.get(object_id or "", [])
    lines.append(f"  referenced by ({len(incoming)}):")
    for reference, prop in incoming:
        holder = reference.getparent()
        lines.append(f"    {sheet.line(reference)} {sheet.label(holder)} {prop}")

    if short_class(element) in ("PipingNetworkSystem", "PipingNetworkSegment"):
        lines.append("  piping:")
        lines += _piping(sheet, element, "    ")
        lines += _instrumentation_once(sheet, element, seen)
        return lines
    parts = [
        (components.get("property", ""), child)
        for components in element.findall("Components")
        for child in components.findall("Object")
    ]
    if parts:
        lines.append(f"  parts ({len(parts)}):")
    for prop, part in parts:
        users = [
            f"{reference.getparent().get('id') or '(no id)'} {used_as}"
            for reference, used_as in sheet.incoming.get(part.get("id") or "", [])
            if used_as != "Object"  # a label printing one of its values
        ]
        lines.append(
            f"    {prop}: {sheet.label(part)} {sheet.where(part)}"
            + (" <- " + ", ".join(users) if users else "")
        )
    if is_equipment(element) or _is_nozzle(element):
        lines += connections(sheet, element)
    lines += _instrumentation_once(sheet, element, seen)
    return lines


# -- instrumentation ---------------------------------------------------------------------------


def _ancestor_or_self(element: etree._Element, kind: str) -> etree._Element | None:
    """The nearest of *element* and its ancestor objects whose class is *kind*."""
    for candidate in (element, *element.iterancestors("Object")):
        if candidate.tag == "Object" and short_class(candidate) == kind:
            return candidate
    return None


def _targets(sheet: Sheet, element: etree._Element, prop: str) -> list[etree._Element]:
    """The objects *element*'s ``References property=prop`` name (that exist)."""
    return [
        sheet.by_id[target.lstrip("#")]
        for reference in element.findall(f"References[@property='{prop}']")
        for target in reference.get("objects", "").split()
        if target.lstrip("#") in sheet.by_id
    ]


def _referrers(sheet: Sheet, element: etree._Element, prop: str) -> list[etree._Element]:
    """The objects whose ``References property=prop`` name *element*."""
    return [
        reference.getparent()
        for reference, used_as in sheet.incoming.get(element.get("id") or "", [])
        if used_as == prop
    ]


def drawn(sheet: Sheet, element: etree._Element) -> str:
    """``drawn by X file:a-b at X0,Y0,X1,Y1 mm``, ``drawn as part of X`` or ``not drawn``."""
    object_id = element.get("id") or ""
    drawings = sheet.drawings.get(object_id, [])
    if drawings:
        parts = []
        for drawing in drawings:
            region = extent(drawing)
            parts.append(
                f"{drawing.get('id') or '(no id)'} {sheet.where(drawing)}"
                + (f" at {region} mm" if region else "")
            )
        return "drawn by " + "; ".join(parts)
    if object_id in sheet.owner:
        return f"drawn as part of {sheet.owner[object_id]}"
    return "not drawn"


def _functions_of(sheet: Sheet, element: etree._Element) -> list[etree._Element]:
    """The ProcessInstrumentationFunctions *element* takes part in or is measured/actuated by."""
    found: list[etree._Element] = []
    kind = short_class(element)
    own = _ancestor_or_self(element, "ProcessInstrumentationFunction")
    if own is not None:
        found.append(own)
    if kind == "InstrumentationLoopFunction":
        found += _targets(sheet, element, "ProcessInstrumentationFunctions")
    systems = []
    system = _ancestor_or_self(element, "ActuatingSystem")
    if system is not None:
        systems.append(system)
    for reference in _referrers(sheet, element, "Valve"):
        system = _ancestor_or_self(reference, "ActuatingSystem")
        if system is not None:
            systems.append(system)
    for system in systems:
        for function in _referrers(sheet, system, "Systems"):
            owner = _ancestor_or_self(function, "ProcessInstrumentationFunction")
            if owner is not None:
                found.append(owner)
    # Measured at the object or at one of its parts (an equipment's nozzles, a line's items).
    for part in element.iter("Object"):
        for generating in _referrers(sheet, part, "SensingLocation"):
            owner = _ancestor_or_self(generating, "ProcessInstrumentationFunction")
            if owner is not None:
                found.append(owner)
    # Signals between functions (a cascade): the other function belongs to the chain too.
    for function in list(found):
        for signal in function.iter("Object"):
            for end in ("Source", "Target"):
                for target in _targets(sheet, signal, end):
                    other = _ancestor_or_self(target, "ProcessInstrumentationFunction")
                    if other is not None:
                        found.append(other)
        if function.get("id"):
            for reference, prop in sheet.incoming.get(function.get("id"), []):
                if prop in ("Source", "Target"):
                    other = _ancestor_or_self(
                        reference.getparent(), "ProcessInstrumentationFunction"
                    )
                    if other is not None:
                        found.append(other)
    return list(dict.fromkeys(found))


def _loops(sheet: Sheet, function: etree._Element) -> list[etree._Element]:
    return [
        loop
        for loop in sheet.root.iter("Object")
        if short_class(loop) == "InstrumentationLoopFunction"
        and function in _targets(sheet, loop, "ProcessInstrumentationFunctions")
    ]


def instrumentation(sheet: Sheet, element: etree._Element) -> list[str]:
    """The instrument chains *element* is part of: loop, sensing, signals, actuation, valve."""
    functions = _functions_of(sheet, element)
    if not functions:
        return []
    lines = [f"  instrumentation ({len(functions)} function(s)):"]
    for function in functions:
        lines.append(
            f"    {sheet.label(function)} {sheet.where(function)} {drawn(sheet, function)}"
        )
        loops = _loops(sheet, function)
        for loop in loops:
            lines.append(f"      loop: {sheet.label(loop)} {sheet.where(loop)}")
        if not loops:
            lines.append("      loop: none (no InstrumentationLoopFunction lists it)")
        for part in function.iter("Object"):
            kind = short_class(part)
            if kind == "ProcessSignalGeneratingFunction":
                where = [
                    f"{sheet.label(t)} {sheet.line(t)}"
                    for t in _targets(sheet, part, "SensingLocation")
                ]
                lines.append(
                    f"      senses: {sheet.label(part)} {sheet.where(part)} at "
                    + (", ".join(where) or "nothing (no SensingLocation)")
                )
            elif kind in ("SignalConveyingFunction", "MeasuringLineFunction"):
                ends = [
                    ", ".join(sheet.label(t) for t in _targets(sheet, part, end)) or "?"
                    for end in ("Source", "Target")
                ]
                name = "signal" if kind == "SignalConveyingFunction" else "measuring line"
                lines.append(
                    f"      {name}: {sheet.label(part)} {sheet.where(part)} "
                    f"{ends[0]} -> {ends[1]}, {drawn(sheet, part)}"
                )
            elif kind == "ActuatingFunction":
                lines.append(f"      actuates: {sheet.label(part)} {sheet.where(part)}")
                for system in _targets(sheet, part, "Systems"):
                    lines.append(
                        f"        system: {sheet.label(system)} {sheet.where(system)} "
                        f"{drawn(sheet, system)}"
                    )
                    for child in system.iter("Object"):
                        if short_class(child) == "ControlledActuator":
                            lines.append(
                                f"        actuator: {sheet.label(child)} {sheet.where(child)} "
                                f"{drawn(sheet, child)}"
                            )
                        elif short_class(child) == "OperatedValveReference":
                            for valve in _targets(sheet, child, "Valve"):
                                lines.append(
                                    f"        valve: {sheet.label(valve)} {sheet.where(valve)} "
                                    f"(OperatedValveReference {sheet.line(child)})"
                                )
                if not _targets(sheet, part, "Systems"):
                    lines.append("        system: none (no References Systems)")
    return lines


# -- equipment connections ---------------------------------------------------------------------

_EQUIPMENT_PREFIXES = ("Plant/ProcessEquipment.", "Plant/Equipment.")


def _is_nozzle(element: etree._Element) -> bool:
    return short_class(element).endswith("Nozzle")


def _equipment_of(element: etree._Element) -> etree._Element | None:
    """The outermost equipment object *element* is or is part of."""
    found = None
    for candidate in (element, *element.iterancestors("Object")):
        if candidate.get("type", "").startswith(_EQUIPMENT_PREFIXES):
            found = candidate
    return found


def is_equipment(element: etree._Element) -> bool:
    """A top-level equipment item (not one of its parts)."""
    return (
        element.get("type", "").startswith(_EQUIPMENT_PREFIXES)
        and _equipment_of(element) is element
        and not _is_nozzle(element)
    )


def _is_tee(element: etree._Element) -> bool:
    return short_class(element) in ("PipeTee", "PipeCross")


@dataclass
class _Piping:
    """The sheet's segments, which segment holds each item, and the items each one ends at."""

    segments: list[etree._Element]
    segment_of: dict[str, etree._Element]
    ends: dict[etree._Element, list[str]]
    ending_at: dict[str, list[etree._Element]]


def _piping_index(sheet: Sheet) -> _Piping:
    segments = [e for e in sheet.root.iter("Object") if short_class(e) == "PipingNetworkSegment"]
    segment_of: dict[str, etree._Element] = {}
    ends: dict[etree._Element, list[str]] = {}
    ending_at: dict[str, list[etree._Element]] = {}
    for segment in segments:
        for item in _object_children(segment, "Items"):
            if item.get("id"):
                segment_of[item.get("id")] = segment
        found: list[str] = []
        for holder in (segment, *_object_children(segment, "Connections")):
            for prop in ("SourceItem", "TargetItem"):
                found += [
                    t.lstrip("#")
                    for r in holder.findall(f"References[@property='{prop}']")
                    for t in r.get("objects", "").split()
                ]
        ends[segment] = list(dict.fromkeys(found))
        for item_id in ends[segment]:
            ending_at.setdefault(item_id, []).append(segment)
    return _Piping(segments, segment_of, ends, ending_at)


def _segment_label(sheet: Sheet, segment: etree._Element) -> str:
    system = _ancestor_or_self(segment, "PipingNetworkSystem")
    line = f" of line {sheet.tag(system) or system.get('id')}" if system is not None else ""
    return f"{sheet.label(segment)}{line} {sheet.where(segment)}"


def _own_ends(segment: etree._Element) -> list[str]:
    """The SourceItem and TargetItem ids of the segment itself."""
    return [
        target.lstrip("#")
        for prop in ("SourceItem", "TargetItem")
        for reference in segment.findall(f"References[@property='{prop}']")
        for target in reference.get("objects", "").split()
    ]


def _item_text(
    sheet: Sheet, piping: _Piping, item_id: str, segment: etree._Element | None = None
) -> str:
    element = sheet.by_id.get(item_id)
    if element is None:
        return f"{item_id} (missing)"
    equipment = _equipment_of(element)
    if equipment is not None and equipment is not element:
        return f"{sheet.label(equipment)} nozzle {sheet.label(element)}"
    holder = piping.segment_of.get(item_id)
    if holder is None:
        return sheet.label(element)
    if holder is segment:
        return f"{sheet.label(element)}, its own end item"
    return f"{sheet.label(element)} in {sheet.label(holder)}"


def connections(sheet: Sheet, element: etree._Element) -> list[str]:
    """What is piped to each nozzle of an equipment item, and what exists only for it."""
    equipment = _equipment_of(element)
    if equipment is None:
        equipment = element
    piping = _piping_index(sheet)
    nozzles = [e for e in element.iter("Object") if _is_nozzle(e)] or [element]
    lines = ["  connections:"]
    starts: list[etree._Element] = []
    for nozzle in nozzles:
        attached = piping.ending_at.get(nozzle.get("id") or "", []) if nozzle.get("id") else []
        if not attached:
            sensing = _referrers(sheet, nozzle, "SensingLocation")
            what = (
                "instrument " + ", ".join(sheet.label(s) for s in sensing) if sensing else "nothing"
            )
            lines.append(f"    {sheet.label(nozzle)}: {what}")
            continue
        for segment in attached:
            others = [
                _item_text(sheet, piping, i, segment)
                for i in _own_ends(segment)
                if sheet.by_id.get(i) is None or _equipment_of(sheet.by_id[i]) is not equipment
            ]
            if not others and len(_own_ends(segment)) < 2:
                others = ["open (the segment names no item there)"]
            lines.append(
                f"    {sheet.label(nozzle)}: segment {_segment_label(sheet, segment)}"
                + (f"; other end: {', '.join(others)}" if others else "")
            )
        starts += [s for s in attached if s not in starts]
    lines += _only_for(sheet, piping, equipment, starts)
    return lines


def _only_for(
    sheet: Sheet, piping: _Piping, equipment: etree._Element, starts: list[etree._Element]
) -> list[str]:
    """Segments, lines and branch tees that serve *equipment* alone (they dangle without it).

    From each segment at the equipment, the run is followed through items that are not tees;
    it is the equipment's own when it reaches no other equipment and no tee branches off it. A
    tee it starts from (on another segment) exists only for that branch.
    """
    lines: list[str] = []
    seen: set[etree._Element] = set()
    for start in starts:
        if start in seen:
            continue
        group = [start]
        tees: list[tuple[etree._Element, etree._Element]] = []
        shared = False
        index = 0
        while index < len(group):
            segment = group[index]
            index += 1
            neighbours: list[etree._Element] = []
            for item_id in piping.ends[segment]:
                item = sheet.by_id.get(item_id)
                if item is None:
                    continue
                owner = _equipment_of(item)
                if owner is not None:
                    shared = shared or owner is not equipment
                    continue
                holder = piping.segment_of.get(item_id)
                if holder is None or holder is segment:
                    continue
                if _is_tee(item):
                    tees.append((item, holder))
                    continue
                if short_class(item).endswith("OffPageConnector"):
                    shared = True  # the line goes on on another sheet
                    continue
                neighbours.append(holder)
            for item in _object_children(segment, "Items"):
                shared = shared or short_class(item).endswith("OffPageConnector")
                for other in piping.ending_at.get(item.get("id") or "", []):
                    if other is segment:
                        continue
                    if _is_tee(item):
                        shared = True
                        continue
                    neighbours.append(other)
            group += [n for n in neighbours if n not in group]
        seen.update(group)
        if shared:
            continue
        if not lines:
            lines.append(
                f"  only for {sheet.tag(equipment) or equipment.get('id')} "
                "(these dangle without it):"
            )
        for segment in group:
            items = _object_children(segment, "Items")
            names = ", ".join(sheet.label(i) for i in items)
            lines.append(
                f"    segment {_segment_label(sheet, segment)}"
                + (f", items: {names}" if names else "")
            )
            for item in items:
                for function in _functions_of(sheet, item):
                    name = sheet.tag(function) or function.get("id")
                    lines.append(
                        f"      {sheet.label(item)} is in the instrument chain of "
                        f"{sheet.label(function)} (cheme show {name})"
                    )
        systems = [
            s
            for s in dict.fromkeys(
                _ancestor_or_self(segment, "PipingNetworkSystem") for segment in group
            )
            if s is not None
        ]
        for system in systems:
            if all(s in group for s in _object_children(system, "Segments")):
                lines.append(
                    f"    line {sheet.label(system)} {sheet.where(system)}: all its segments"
                )
        for tee, holder in dict.fromkeys(tees):
            lines.append(
                f"    branch tee {sheet.label(tee)} {sheet.where(tee)} on "
                f"{_segment_label(sheet, holder)}: its branch serves only this"
            )
    return lines


def show(key: str, sheets: list[tuple[Path, str]]) -> tuple[list[str], bool]:
    """The description of every object *key* names in *sheets* (path, display name).

    Returns the lines to print and whether anything was found; when nothing was, the lines
    suggest close ids and tags.
    """
    lines: list[str] = []
    found = False
    names: list[str] = []
    for path, name in sheets:
        try:
            sheet = Sheet.load(path, name)
        except ShowError as failure:
            lines.append(f"{failure}")
            continue
        matches = sheet.find(key)
        names += sheet.names()
        seen: set[tuple[str, ...]] = set()
        for element in matches:
            if found:
                lines.append("")
            lines += describe(sheet, element, seen)
            found = True
    if not found:
        where = ", ".join(name for _, name in sheets) or "no sheets"
        lines.append(f"No object with id or tag {key!r} in {where}.")
        close = difflib.get_close_matches(key, list(dict.fromkeys(names)), n=5, cutoff=0.6)
        if close:
            lines.append("Did you mean: " + ", ".join(close) + "?")
    return lines, found
