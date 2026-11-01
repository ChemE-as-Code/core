"""``cheme move``, ``rename`` and ``set``: change an object that is already on a sheet.

Pure transforms of the sheet's XML tree (never pyDEXPI's editor): the file is parsed, the
change is made on the element tree and the document is written back as it was read except for
the change, then ``cheme fmt`` runs over it. pyDEXPI is used read-only, to look up the type
of a DEXPI attribute and to render the label templates that show a changed value.

- **move** shifts every coordinate that draws an object (symbol, node positions, labels, the
  bends of lines drawn inside its group); the lines attached to its node positions follow by
  reference, their bends stay put and are reported as stretched.
- **rename** changes an id and every ``#id`` reference to it (with ``--children`` also the ids
  derived from it, ``OLD_*``), or, given a tag, the tag data and the label texts that show it.
- **set** changes one ``Data`` value by its DEXPI name, in the type the attribute has (String,
  Double, Integer, Boolean, enumeration, physical quantity), and the cached label texts that
  show it.
"""

from __future__ import annotations

import difflib
import enum
import re
import typing
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    ID_PATTERN,
    check_id,
    data_number,
    fmt_num,
    offsets_by_element,
    point_xy,
    points_of,
    shift_point,
)
from chemeascode.domains.piping.show import Sheet, data_value, instrument_tag, short_class

BAR_LABEL = "Plant/Diagram.EquipmentBarLabel"
TEXT = "Core/Diagram.Text"

#: Data properties that hold a piping component's or an item's tag (``show.TAG_PROPERTIES``,
#: which includes the ``PositionNumber`` a safety valve carries).
TAG_DATA = (
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


class EditError(Exception):
    """The edit cannot be made; the message says why and what to do."""


# -- the document ---------------------------------------------------------------------------------


@dataclass
class Document:
    """A sheet's XML tree, written back byte for byte except where it was changed."""

    path: Path
    name: str
    text: str
    sheet: Sheet
    prolog: str
    epilog: str

    @classmethod
    def load(cls, path: Path, name: str | None = None) -> Document:
        name = name or str(path)
        try:
            sheet = Sheet.load(path, name)
        except Exception as failure:  # ShowError: not well-formed
            raise EditError(str(failure)) from failure
        text = path.read_bytes().decode("utf-8")
        try:
            offsets = offsets_by_element(sheet.root, text)
        except ValueError as failure:
            raise EditError(f"{name}: {failure}") from failure
        for element, (_, end) in offsets.items():
            # Keep <String></String> as written (lxml would write <String/>).
            if element.text is None and len(element) == 0 and text[end - 2 : end] != "/>":
                element.text = ""
        start, end = offsets[sheet.root]
        return cls(path, name, text, sheet, text[:start], text[end:])

    @property
    def root(self) -> etree._Element:
        return self.sheet.root

    def render(self) -> str:
        return self.prolog + etree.tostring(self.root, encoding="unicode") + self.epilog

    def line(self, element: etree._Element) -> str:
        return self.sheet.line(element)


@dataclass
class EditResult:
    """What an edit did (or, not written, would do)."""

    name: str
    changes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diff: str = ""
    written: bool = False

    def report(self) -> list[str]:
        lines = list(self.changes)
        lines += [f"note: {n}" for n in self.notes]
        if self.written:
            lines.append(f"next: cheme validate && cheme render {self.name} --png --crop ...")
        return lines


def finish(doc: Document, result: EditResult, *, write: bool, fmt: bool = True) -> EditResult:
    """Write the changed document (and format it), or only compute the diff."""
    new = doc.render()
    result.diff = "".join(
        difflib.unified_diff(
            doc.text.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{doc.name}",
            tofile=f"b/{doc.name}",
            n=2,
        )
    )
    if not write:
        return result
    doc.path.write_bytes(new.encode("utf-8"))
    result.written = True
    if fmt:
        from chemeascode.domains.piping.fmt import FormatRefused, dropped_note, format_file

        try:
            formatted = format_file(doc.path)
        except FormatRefused as refusal:
            result.notes.append(f"cheme fmt refused the result ({refusal}); written unformatted")
        else:
            if formatted.dropped:
                result.notes.append(f"cheme fmt {dropped_note(formatted.dropped)}")
    return result


# -- finding objects ------------------------------------------------------------------------------


def in_conceptual(element: etree._Element) -> bool:
    return not any(
        a.tag == "Components" and a.get("property") in ("Diagram", "ShapeCatalogues")
        for a in element.iterancestors()
    )


def in_catalogue(element: etree._Element) -> bool:
    return any(
        a.tag == "Components" and a.get("property") == "ShapeCatalogues"
        for a in element.iterancestors()
    )


def _suggest(sheet: Sheet, key: str) -> str:
    close = difflib.get_close_matches(key, sheet.names(), n=3, cutoff=0.6)
    return f" (did you mean {', '.join(dict.fromkeys(close))}?)" if close else ""


def find_one(sheet: Sheet, key: str, *, conceptual_only: bool = False) -> etree._Element:
    """The one object *key* names (an id, else a tag); exit with a clear message otherwise."""
    matches = sheet.find(key)
    if conceptual_only:
        matches = [m for m in matches if in_conceptual(m)]
    if not matches:
        raise EditError(f"{sheet.name}: no object with id or tag {key!r}{_suggest(sheet, key)}")
    if len(matches) > 1:
        names = ", ".join(sheet.label(m) for m in matches[:6])
        raise EditError(f"{key!r} names {len(matches)} objects ({names}): give the XML id")
    return matches[0]


def outermost(groups: list[etree._Element]) -> list[etree._Element]:
    chosen = set(groups)
    return [g for g in dict.fromkeys(groups) if not any(a in chosen for a in g.iterancestors())]


def drawings_of(sheet: Sheet, element: etree._Element) -> list[etree._Element]:
    """The outermost groups that draw *element* or one of its parts."""
    ids = [o.get("id") for o in element.iter("Object") if o.get("id")]
    return outermost([g for object_id in ids for g in sheet.drawings.get(object_id, [])])


def _refs(element: etree._Element, prop: str) -> list[str]:
    reference = element.find(f"References[@property='{prop}']")
    if reference is None:
        return []
    return [t.lstrip("#") for t in reference.get("objects", "").split()]


def _xy(point: etree._Element) -> str:
    xy = point_xy(point)
    return ",".join(fmt_num(v) for v in xy) if xy else "?"


def _holder(sheet: Sheet, point: etree._Element) -> str:
    """``Inst_FQI4149_BubbleShape Position`` for a point."""
    data = point.getparent()
    prop = data.get("property", "") if data is not None else ""
    obj = next(point.iterancestors("Object"), None)
    while obj is not None and obj.get("type", "").endswith(("Point", "Stroke", "Color")):
        obj = next(obj.iterancestors("Object"), None)
    name = (obj.get("id") or short_class(obj)) if obj is not None else "?"
    return f"{name} {prop}"


# -- move -----------------------------------------------------------------------------------------


def move_object(
    path: Path,
    key: str,
    offset: tuple[float, float],
    *,
    write: bool = True,
    name: str | None = None,
    fmt: bool = True,
) -> EditResult:
    """Move everything that draws *key* by *offset* (sheet mm, Y down)."""
    doc = Document.load(path, name)
    sheet = doc.sheet
    target = find_one(sheet, key)
    if in_catalogue(target):
        raise EditError(
            f"{sheet.label(target)} is a symbol in the shape catalogue, not on the sheet"
        )
    if in_conceptual(target):
        drawings = drawings_of(sheet, target)
        if not drawings:
            raise EditError(f"{sheet.label(target)} is not drawn on {doc.name}: nothing to move")
    else:
        drawings = [target]
    dx, dy = offset
    result = EditResult(doc.name)
    what = ", ".join(d.get("id") or short_class(d) for d in drawings)
    result.changes.append(f"moved {sheet.label(target)} by {fmt_num(dx)},{fmt_num(dy)} mm ({what})")
    if not (dx or dy):
        result.notes.append("--offset 0,0 moves nothing")
        return finish(doc, result, write=False)

    inside = {e for d in drawings for e in d.iter()}
    inside_ids = {e.get("id") for e in inside if e.tag == "Object" and e.get("id")}
    keep: set[etree._Element] = set()
    stretched: list[str] = []
    follows: list[tuple[etree._Element, str]] = []
    for drawing in drawings:
        for table in (o for o in drawing.iter("Object") if o.get("type") == BAR_LABEL):
            keep.update(points_of(table))
            result.notes.append(
                f"{table.get('id') or 'the data table'} stays in the data-table band (move it "
                f"with cheme move {table.get('id') or '<its id>'} --offset ...)"
            )
        for line in (
            o for o in drawing.iter("Object") if o.get("type") == "Core/Diagram.ConnectorLine"
        ):
            ends = _refs(line, "Source") + _refs(line, "Target")
            outside = [end for end in ends if end not in inside_ids]
            if outside:
                inner = points_of(line)
                keep.update(inner)
                label = line.get("id") or f"ConnectorLine at {doc.line(line)}"
                if inner:
                    stretched.append(
                        f"{label} (to {', '.join(outside)} outside; its {len(inner)} bend(s) stay)"
                    )
                else:
                    follows.append((line, f"{label} (straight, to {', '.join(outside)} outside)"))
    moved_old: list[tuple[float, float]] = []
    for drawing in drawings:
        for point in points_of(drawing):
            if point in keep:
                continue
            before = _xy(point)
            xy = point_xy(point)
            if xy:
                moved_old.append(xy)
            shift_point(point, dx, dy)
            result.changes.append(
                f"  {doc.line(point)} {_holder(sheet, point)}: {before} -> {_xy(point)}"
            )

    # Lines outside the moved groups that attach to them.
    diagram = doc.root.find(".//Components[@property='Diagram']")
    for line in diagram.iter("Object") if diagram is not None else ():
        if line in inside:
            continue
        kind = line.get("type", "")
        if kind == "Core/Diagram.ConnectorLine":
            attached = [e for e in _refs(line, "Source") + _refs(line, "Target") if e in inside_ids]
            if not attached:
                continue
            bends = len(points_of(line))
            label = line.get("id") or f"ConnectorLine at {doc.line(line)}"
            if bends:
                stretched.append(f"{label} (to {', '.join(attached)}; its {bends} bend(s) stay)")
            else:
                follows.append((line, f"{label} (straight, to {', '.join(attached)})"))
        elif kind == "Core/Diagram.PolyLine" and moved_old:
            ends = points_of(line)
            for point in (ends[:1] + ends[-1:]) if len(ends) > 1 else []:
                xy = point_xy(point)
                if xy and any(
                    abs(xy[0] - x) < 1e-6 and abs(xy[1] - y) < 1e-6 for x, y in moved_old
                ):
                    before = _xy(point)
                    shift_point(point, dx, dy)
                    result.changes.append(
                        f"  {doc.line(point)} end of {line.get('id') or 'PolyLine'}: "
                        f"{before} -> {_xy(point)}"
                    )
    for line, text in follows:
        slant = _slanted(sheet, line, inside_ids, dx, dy)
        result.changes.append(f"  follows: {text}{slant}")
    result.changes += [f"  stretched: {line}" for line in stretched]
    return finish(doc, result, write=write, fmt=fmt)


def _slanted(sheet: Sheet, line: etree._Element, inside: set[str], dx: float, dy: float) -> str:
    """`` -- now slanted ...`` when a straight line that was horizontal or vertical is not."""
    ends = []
    for end in _refs(line, "Source") + _refs(line, "Target"):
        element = sheet.by_id.get(end)
        point = (
            element.find("Data[@property='Position']/AggregatedDataValue")
            if element is not None
            else None
        )
        xy = point_xy(point) if point is not None else None
        if xy is None:
            return ""
        ends.append((xy, end in inside))
    if len(ends) != 2 or ends[0][1] == ends[1][1]:
        return ""
    (a, a_in), (b, _) = ends
    old_a = (a[0] - dx, a[1] - dy) if a_in else a
    old_b = (b[0] - dx, b[1] - dy) if not a_in else b

    def aligned(p: tuple[float, float], q: tuple[float, float]) -> bool:
        return abs(p[0] - q[0]) < 1e-6 or abs(p[1] - q[1]) < 1e-6

    if aligned(old_a, old_b) and not aligned(a, b):
        return " -- now slanted: add a bend (InnerPoints) or move the other end too"
    return ""


# -- rename ---------------------------------------------------------------------------------------


def compact(tag: str) -> str:
    """A tag as ids spell it: ``HV-4146`` -> ``HV4146``."""
    return re.sub(r"[^A-Za-z0-9_]", "", tag)


def rename_ids(root: etree._Element, mapping: dict[str, str]) -> int:
    """Apply *mapping* to every id and ``#id`` reference; returns the references changed."""
    changed = 0
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        if element.get("id") in mapping:
            element.set("id", mapping[element.get("id")])
        if element.tag == "References":
            targets = element.get("objects", "").split()
            new = ["#" + mapping.get(t.lstrip("#"), t.lstrip("#")) for t in targets]
            if new != targets:
                changed += sum(a != b for a, b in zip(targets, new, strict=True))
                element.set("objects", " ".join(new))
    return changed


def rename(
    path: Path,
    old: str,
    new: str,
    *,
    children: bool = False,
    ids: bool = False,
    tag: bool = False,
    write: bool = True,
    name: str | None = None,
    fmt: bool = True,
) -> EditResult:
    """Rename the id *old* (and its references), or the tag *old* of one object.

    With *tag*, *new* is the new tag of the object *old* names (by id or tag): the way to
    retag one of two objects that share a tag.
    """
    doc = Document.load(path, name)
    sheet = doc.sheet
    result = EditResult(doc.name)
    if tag and children:
        raise EditError("--children renames ids; --tag gives the object a new tag")
    if old in sheet.by_id and not tag:
        if ids:
            raise EditError("--ids goes with a tag; for an id use --children")
        try:
            check_id(new, "the new id")
        except ValueError as failure:
            raise ValueError(
                f"{failure}; to give {old} the tag {new} instead, add --tag"
            ) from failure
        mapping = {old: new}
        if children:
            for object_id in sheet.by_id:
                if object_id.startswith(old + "_"):
                    mapping[object_id] = new + object_id[len(old) :]
        _rename_checked(doc, mapping, result)
        for before, after in mapping.items():
            element = sheet.by_id[before]
            for prop in TAG_DATA:
                value = data_value(element, prop)
                if value and compact(value) in before and compact(value) not in after:
                    result.notes.append(
                        f"{after} keeps its {prop} {value!r}: cheme set {after} {prop}=..."
                    )
        return finish(doc, result, write=write, fmt=fmt)
    if children:
        raise EditError(
            f"{doc.name}: no object has the id {old!r}{_suggest(sheet, old)}; "
            "--children renames ids (to rename a tag, leave it out)"
        )
    chain: list[etree._Element] | None = None
    if tag:
        target = find_one(sheet, old)
        if not in_conceptual(target):
            raise EditError(f"{sheet.label(target)} is a drawing element: it has no tag")
        old = sheet.tag(target) or ""
        if not old:
            raise EditError(
                f"{sheet.label(target)} has no tag to rename: cheme set {old or 'ID'} PROPERTY=TAG"
            )
    else:
        matches = [m for m in sheet.find(old) if in_conceptual(m)]
        chain = actuation_chain(matches) if len(matches) > 1 else None
        if chain is None:
            target = find_one(sheet, old, conceptual_only=True)
    if not tag and chain is not None:
        # One valve and its own actuation chain share the tag: retag them together.
        result.notes.append(
            f"{old} names {sheet.label(chain[0])} and its actuation chain: retagged together"
        )
        retagged = chain
        for member in sorted(chain, key=_chain_order):
            if not any(_same_tag(t, old) for t in sheet.tags(member)):
                continue  # retagged with its instrument function already
            retag(doc, member, old, new, result)
    else:
        retagged = [target]
        retag(doc, target, old, new, result)
    # Only the ids of the retagged objects, their parts and drawings count: another object may
    # spell the same tag (--tag) or contain it (FV104 for V-104).
    scope = [
        e.get("id")
        for member in retagged
        for part in [member, *drawings_of(sheet, member)]
        for e in part.iter("Object")
        if e.get("id")
    ]
    before, after = compact(old), compact(new)
    pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(before)}(?![0-9])")
    if ids:
        mapping = {
            object_id: pattern.sub(after, object_id)
            for object_id in dict.fromkeys(scope)
            if pattern.search(object_id)
        }
        if mapping:
            _rename_checked(doc, mapping, result)
        else:
            result.notes.append(f"no id contains {before}: no id renamed")
    else:
        derived = [i for i in dict.fromkeys(scope) if before and pattern.search(i)]
        if derived:
            result.notes.append(
                f"{len(derived)} id(s) still spell the old tag ({', '.join(derived[:3])}"
                f"{', ...' if len(derived) > 3 else ''}): add --ids to rename them too"
            )
    return finish(doc, result, write=write, fmt=fmt)


def _same_tag(a: str, b: str) -> bool:
    return a == b or (compact(a).upper() == compact(b).upper() and bool(compact(a)))


def actuation_chain(matches: list[etree._Element]) -> list[etree._Element] | None:
    """*matches* when they are one valve and its own actuation chain, the valve first.

    The chain: the ActuatingSystems that operate the valve (OperatedValveReference), the
    ActuatingFunctions that drive those systems and the instrument functions that hold such an
    ActuatingFunction. None when anything else is among *matches*.
    """
    valves = [m for m in matches if m.get("type", "").startswith("Plant/Piping.")]
    if len(valves) != 1 or not valves[0].get("id"):
        return None
    valve = valves[0]
    systems = [
        m
        for m in matches
        if short_class(m) == "ActuatingSystem"
        and any(
            valve.get("id") in _refs(r, "Valve")
            for r in m.iter("Object")
            if short_class(r) == "OperatedValveReference"
        )
    ]
    if not systems:
        return None
    system_ids = {s.get("id") for s in systems}

    def drives(function: etree._Element) -> bool:
        return short_class(function) == "ActuatingFunction" and bool(
            system_ids & set(_refs(function, "Systems"))
        )

    functions = [m for m in matches if drives(m)]
    instruments = [
        m
        for m in matches
        if short_class(m) == "ProcessInstrumentationFunction"
        and any(drives(part) for part in m.iter("Object"))
    ]
    chain = [valve, *systems, *functions, *instruments]
    if len({id(m) for m in chain}) != len(matches) or any(m not in chain for m in matches):
        return None
    return chain


def _chain_order(element: etree._Element) -> int:
    # The instrument function first: its retag renumbers the ActuatingFunction inside it.
    return 0 if short_class(element) == "ProcessInstrumentationFunction" else 1


def _rename_checked(doc: Document, mapping: dict[str, str], result: EditResult) -> None:
    sheet = doc.sheet
    bad = [n for n in mapping.values() if not ID_PATTERN.match(n)]
    if bad:
        raise EditError(f"{bad[0]!r} is not a valid id: letters, digits and _ only")
    taken = set(sheet.by_id) - set(mapping)
    clashes = sorted({n for n in mapping.values() if n in taken})
    if len(set(mapping.values())) != len(mapping):
        clashes += sorted({n for n in mapping.values() if list(mapping.values()).count(n) > 1})
    if clashes:
        raise EditError(
            f"cannot rename: {', '.join(clashes[:5])} already exist(s) in {doc.name}; "
            "choose another name or rename that object first"
        )
    references = rename_ids(doc.root, mapping)
    result.changes.append(f"renamed {len(mapping)} id(s), {references} reference(s) re-pointed:")
    result.changes += [f"  {a} -> {b}" for a, b in mapping.items()]
    # Nothing may point at the old ids any more.
    present = {e.get("id") for e in doc.root.iter("Object") if e.get("id")}
    dangling = [
        t.lstrip("#")
        for r in doc.root.iter("References")
        for t in r.get("objects", "").split()
        if t.lstrip("#") in mapping and t.lstrip("#") not in present
    ]
    if dangling:  # pragma: no cover - rename_ids re-points every reference
        raise EditError(f"references to {', '.join(dangling)} remain")


# -- tags -----------------------------------------------------------------------------------------

_PIF_CATEGORY = "ProcessInstrumentationFunctionCategory"
_PIF_LETTERS = "ProcessInstrumentationFunctions"
_PIF_NUMBER = "ProcessInstrumentationFunctionNumber"
#: The functions inside an instrument whose numbers carry its category and loop number.
PART_NUMBERS = (
    "ProcessSignalGeneratingFunctionNumber",
    "ActuatingFunctionNumber",
    "SignalConveyingFunctionNumber",
)


def split_instrument_tag(
    old_category: str | None, tag: str, what: str = "--tag"
) -> tuple[str | None, str | None, str]:
    """``PICSA-4713.02`` -> (``P``, ``ICSA``, ``4713.02``), in ``instrument_tag``'s format.

    The letters are optional (``4713.02`` changes the number only). The measured variable keeps
    its old length when the new letters start with it (``PD`` stays the category of ``PDI``),
    otherwise it is the first letter.
    """
    match = re.fullmatch(r"(?:([A-Za-z]+)[-\s])?(\S*\d\S*)", tag.strip())
    if not match:
        raise EditError(
            f"{what} {tag}: an instrument's tag is LETTERS-NUMBER as it is printed "
            "(for example PICSA-4713.02), or just the NUMBER"
        )
    letters, num = match.group(1), match.group(2)
    if not letters:
        return None, None, num
    category = old_category or ""
    if not (category and letters.startswith(category) and len(letters) >= len(category)):
        category = letters[0]
    return category, letters[len(category) :], num


def insert_child(parent: etree._Element, child: etree._Element) -> etree._Element:
    """Append *child* to *parent*, indented like its siblings."""
    depth = sum(1 for _ in parent.iterancestors())
    etree.indent(child, space="  ", level=depth + 1)
    if len(parent):
        last = parent[-1]
        child.tail = last.tail
        last.tail = "\n" + "  " * (depth + 1)
    else:
        parent.text = "\n" + "  " * (depth + 1)
        child.tail = "\n" + "  " * depth
    parent.append(child)
    return child


def set_string(element: etree._Element, prop: str, value: str, *, create: bool = False) -> bool:
    data = element.find(f"Data[@property='{prop}']")
    if data is None:
        if not create:
            return False
        data = insert_child(element, etree.Element("Data", property=prop))
    string = data.find("String")
    if string is None:
        for child in list(data):
            data.remove(child)
        string = etree.SubElement(data, "String")
    string.text = value
    return True


def retag_instrument_parts(
    instrument: etree._Element,
    old_category: str | None,
    old_number: str | None,
    category: str | None,
    num: str,
) -> list[str]:
    """Follow a new category and loop number in the functions inside *instrument*.

    The sensor ``AT4149`` of an instrument retagged from A to F becomes ``FT4149``, and the
    actuator ``AV4149`` ``FV4149`` (the functions' letters start with the measured variable).
    """
    fields = []
    number_pattern = (
        re.compile(rf"(?<![0-9.]){re.escape(old_number)}(?![0-9])")
        if old_number and old_number != num
        else None
    )
    letter_pattern = (
        re.compile(rf"^{re.escape(old_category)}(?=[A-Za-z]*[-\s]?\d)")
        if old_category and category and category != old_category
        else None
    )
    for part in instrument.iter("Object"):
        if part is instrument:
            continue
        for prop in TAG_DATA:
            string = part.find(f"Data[@property='{prop}']/String")
            if string is None or not string.text:
                continue
            text = string.text
            if letter_pattern is not None and prop in PART_NUMBERS:
                text = letter_pattern.sub(category, text)
            if number_pattern is not None:
                text = number_pattern.sub(num, text)
            if text != string.text:
                string.text = text
                fields.append(f"{part.get('id') or short_class(part)} {prop} {text!r}")
    return fields


def retag(doc: Document, target: etree._Element, old: str, new: str, result: EditResult) -> None:
    """Give *target* the tag *new* (it has *old*), and refresh the labels that show it."""
    sheet = doc.sheet
    before = render_labels(doc, [target])
    if instrument_tag(target) is not None:
        old_category = data_value(target, _PIF_CATEGORY)
        old_number = data_value(target, _PIF_NUMBER)
        category, letters, num = split_instrument_tag(old_category, new, "rename")
        values = {} if category is None else {_PIF_CATEGORY: category, _PIF_LETTERS: letters or ""}
        values[_PIF_NUMBER] = num
        fields = []
        for prop, value in values.items():
            if not value and target.find(f"Data[@property='{prop}']") is None:
                continue
            set_string(target, prop, value, create=True)
            fields.append(f"{prop} {value!r}")
        fields += retag_instrument_parts(target, old_category, old_number, category, num)
        new_tags = [instrument_tag(target) or new]
    else:
        prop = next(
            (p for p in TAG_DATA if data_value(target, p) == old),
            None,
        )
        if prop is None:  # found loosely (HV4146 for HV-4146)
            prop = next(p for p in TAG_DATA if data_value(target, p) is not None)
        set_string(target, prop, new)
        fields = [f"{prop} {new!r}"]
        new_tags = [new]
        if prop == "TagName":
            match = re.fullmatch(r"([A-Za-z]*)[-\s]?(\d+)(.*)", new)
            if match:
                for part, value in zip(
                    ("TagNamePrefix", "TagNameSequenceNumber", "TagNameSuffix"),
                    match.groups(),
                    strict=True,
                ):
                    if set_string(target, part, value):
                        fields.append(f"{part} {value!r}")
    from chemeascode.domains.piping.tag_rules import tag_clashes

    clashes = tag_clashes(doc.path, doc.root, target, doc.name, tags=new_tags)
    if clashes:
        raise EditError(
            f"cannot rename: {new_tags[0]} is already the tag of {clashes[0].split(': ', 1)[1]}"
            f"{f' (and {len(clashes) - 1} more)' if len(clashes) > 1 else ''}; "
            "choose another tag or retag that object first"
        )
    result.changes.append(f"tag of {sheet.label(target)}: {old} -> {new} ({', '.join(fields)})")
    result.changes += refresh_labels(doc, before)


# -- set ------------------------------------------------------------------------------------------


def _pydexpi_class(element: etree._Element) -> type | None:
    from pydexpi.pydexpi_classes import pydexpi_classes

    found = getattr(pydexpi_classes, short_class(element), None)
    return found if isinstance(found, type) else None


def _field_name(cls: type, prop: str) -> str | None:
    fields = getattr(cls, "model_fields", {})
    wanted = re.sub(r"[^a-z0-9]", "", prop.lower())
    for name in fields:
        if re.sub(r"[^a-z0-9]", "", name.lower()) == wanted:
            return name
    return None


def _data_fields(cls: type) -> list[str]:
    return [
        n[:1].upper() + n[1:]
        for n, f in getattr(cls, "model_fields", {}).items()
        if (f.json_schema_extra or {}).get("attribute_category") == "data"
    ]


def _value_kind(cls: type, name: str) -> tuple[str, type | None, str | None]:
    """What a field holds: (``String``|``Double``|``Integer``|``Boolean``|``DateTime``|``Enum``|
    ``Quantity``, the enum class, the unit enum's name)."""
    from pydexpi.pydexpi_classes import pydexpi_classes

    info = cls.model_fields[name]
    try:
        annotation = typing.get_type_hints(cls).get(name, info.annotation)
    except Exception:  # noqa: BLE001 - unresolvable string annotations: the raw one
        annotation = info.annotation
    members = typing.get_args(annotation) or (annotation,)
    for member in members:
        if member is type(None) or getattr(member, "__name__", "") == "Undefined":
            continue
        if member is bool:
            return "Boolean", None, None
        if member is int:
            return "Integer", None, None
        if member is float:
            return "Double", None, None
        if member is str:
            return "String", None, None
        if getattr(member, "__name__", "") == "datetime":
            return "DateTime", None, None
        if isinstance(member, type) and issubclass(member, enum.Enum):
            return "Enum", member, None
        if member is getattr(pydexpi_classes, "PhysicalQuantity", None):
            return "Quantity", None, (info.json_schema_extra or {}).get("unit_type")
    raise EditError(f"{cls.__name__}.{name} holds {annotation}; cheme set cannot write it")


def _enum_path(enum_class: type) -> str:
    from pydexpi.toolkits.base_model_utils import get_dexpi_package_mapping

    path = get_dexpi_package_mapping().get(enum_class.__name__)
    if path is None:
        raise EditError(f"no DEXPI name for the enumeration {enum_class.__name__}")
    return path.replace(".", "/", 1)


def _enum_member(enum_class: type, text: str, what: str) -> str:
    """The member *text* names (its value, case and separators ignored)."""
    wanted = re.sub(r"[^a-z0-9]", "", text.rsplit(".", 1)[-1].lower())
    for member in enum_class:  # type: ignore[attr-defined]
        if re.sub(r"[^a-z0-9]", "", str(member.value).lower()) == wanted:
            return str(member.value)
    options = ", ".join(str(m.value) for m in enum_class)  # type: ignore[attr-defined]
    raise EditError(f"{what}: {text!r} is not one of {options}")


def _unit_member(unit_type: str | None, text: str, what: str) -> str:
    """The unit enumeration's path for *text* (``barg``, ``Bar``, ``m3/h`` or a member name)."""
    from pydexpi.pydexpi_classes import pydexpi_classes

    from chemeascode.domains.piping.sheet_index import _UNIT_SPELLINGS

    spelled = {s: unit for unit, spellings in _UNIT_SPELLINGS.items() for s in spellings}
    candidates = (
        [getattr(pydexpi_classes, unit_type)]
        if unit_type and hasattr(pydexpi_classes, unit_type)
        else []
    )
    if not candidates:
        raise EditError(f"{what}: this attribute's unit kind is not known")
    unit_enum = candidates[0]
    name = spelled.get(text.lower(), text)
    member = _enum_member(unit_enum, name, what)
    return f"{_enum_path(unit_enum)}.{member}"


def _typed(kind: str, text: str, what: str) -> str:
    """*text* in the lexical form of an XML ``Double``/``Integer``/``Boolean``/``DateTime``."""
    try:
        if kind == "Double":
            return data_number(float(text))
        if kind == "Integer":
            return str(int(text))
    except ValueError as failure:
        raise EditError(f"{what}: {text!r} is not a number ({kind})") from failure
    if kind == "Boolean":
        lowered = text.strip().lower()
        if lowered in ("true", "yes", "1"):
            return "true"
        if lowered in ("false", "no", "0"):
            return "false"
        raise EditError(f"{what}: {text!r} is not true or false")
    return text


def _element(kind: str, value: str, enum_path: str | None = None) -> etree._Element:
    if kind == "Enum":
        return etree.Element("DataReference", data=f"{enum_path}.{value}")
    element = etree.Element(kind)
    element.text = value
    return element


def _quantity(value: str, unit_path: str) -> etree._Element:
    aggregate = etree.Element(
        "AggregatedDataValue", type="Core/PhysicalQuantities.PhysicalQuantity"
    )
    unit = etree.SubElement(aggregate, "Data", property="Unit")
    etree.SubElement(unit, "DataReference", data=unit_path)
    val = etree.SubElement(aggregate, "Data", property="Value")
    etree.SubElement(val, "Double").text = value
    return aggregate


def _show(data: etree._Element | None) -> str:
    if data is None:
        return "(not set)"
    child = next(iter(data), None)
    if child is None:
        return repr("")
    if child.tag == "DataReference":
        return child.get("data", "").rsplit(".", 1)[-1]
    if child.tag == "AggregatedDataValue":
        parts = []
        for sub in child.findall("Data"):
            parts.append(f"{sub.get('property')}={_show(sub)}")
        return "{" + ", ".join(parts) + "}"
    return repr(child.text or "")


def assign(owner: etree._Element, prop: str, value: str, what: str | None = None) -> str:
    """Set ``Data property=prop`` of *owner* (a dotted path into aggregated values) to *value*.

    The type follows the value already there, else the pyDEXPI class's attribute. An empty
    *value* removes the ``Data``. Returns ``old -> new`` for the report.
    """
    what = what or prop
    steps = prop.split(".")
    holder = owner
    for step in steps[:-1]:
        aggregate = holder.find(f"Data[@property='{step}']/AggregatedDataValue")
        if aggregate is None:
            raise EditError(f"{what}: {owner.get('id') or short_class(owner)} has no {step} value")
        holder = aggregate
    leaf = steps[-1]
    data = holder.find(f"Data[@property='{leaf}']")
    old = _show(data)
    if value == "":
        if data is None:
            raise EditError(f"{what}: not set, nothing to remove")
        holder.remove(data)
        return f"{old} -> (removed)"

    child = next(iter(data), None) if data is not None else None
    kind = child.tag if child is not None else None
    if kind == "DataReference":
        path_, _, _ = child.get("data", "").rpartition(".")
        enum_class = _enum_by_path(path_)
        member = _enum_member(enum_class, value, what) if enum_class else value.rsplit(".", 1)[-1]
        child.set("data", f"{path_}.{member}")
        return f"{old} -> {_show(data)}"
    if kind == "AggregatedDataValue" and child.get("type", "").endswith("PhysicalQuantity"):
        quantity, unit_text = _split_quantity(value, what)
        unit = child.find("Data[@property='Unit']/DataReference")
        if unit_text:
            unit_type = (
                unit.get("data", "").rpartition(".")[0].rsplit(".", 1)[-1]
                if unit is not None
                else None
            )
            unit_path = _unit_member(unit_type, unit_text, what)
            if unit is None:
                unit = etree.SubElement(
                    etree.SubElement(child, "Data", property="Unit"), "DataReference"
                )
            unit.set("data", unit_path)
        double = child.find("Data[@property='Value']/Double")
        if double is None:
            double = etree.SubElement(etree.SubElement(child, "Data", property="Value"), "Double")
        double.text = quantity
        return f"{old} -> {_show(data)}"
    if kind in ("String", "Double", "Integer", "Boolean", "DateTime"):
        child.text = _typed(kind, value, what)
        return f"{old} -> {_show(data)}"
    if kind is not None:
        raise EditError(f"{what}: holds a {kind}; cheme set cannot write it")

    # Not set yet: the pyDEXPI class says what the attribute holds.
    cls = _pydexpi_class(owner) if holder is owner else _aggregate_class(holder)
    if cls is None:
        raise EditError(f"{what}: {short_class(owner)} is not a DEXPI class pyDEXPI knows")
    name = _field_name(cls, leaf)
    if name is None or (cls.model_fields[name].json_schema_extra or {}).get(
        "attribute_category"
    ) not in ("data", None):
        options = _data_fields(cls)
        close = difflib.get_close_matches(leaf, options, n=3)
        hint = f"did you mean {', '.join(close)}?" if close else f"its data: {', '.join(options)}"
        raise EditError(f"{what}: a {cls.__name__} has no data attribute {leaf!r} ({hint})")
    kind, enum_class, unit_type = _value_kind(cls, name)
    data = etree.Element("Data", property=name[:1].upper() + name[1:])
    if kind == "Enum":
        member = _enum_member(enum_class, value, what)
        data.append(_element("Enum", member, _enum_path(enum_class)))
    elif kind == "Quantity":
        quantity, unit_text = _split_quantity(value, what)
        if not unit_text:
            raise EditError(
                f"{what}: give the value with its unit, e.g. '6 barg' or '26 MetreCubed'"
            )
        data.append(_quantity(quantity, _unit_member(unit_type, unit_text, what)))
    else:
        data.append(_element(kind, _typed(kind, value, what)))
    insert_child(holder, data)
    return f"{old} -> {_show(data)}"


def _split_quantity(value: str, what: str) -> tuple[str, str]:
    match = re.fullmatch(r"\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)\s*(.*?)\s*", value)
    if not match:
        raise EditError(f"{what}: {value!r} is not a quantity (a number, optionally a unit)")
    try:
        return data_number(float(match.group(1))), match.group(2)
    except ValueError as failure:  # 1e999
        raise EditError(f"{what}: {value!r} is not a finite number") from failure


def _enum_by_path(path: str) -> type | None:
    from pydexpi.pydexpi_classes import pydexpi_classes

    found = getattr(pydexpi_classes, path.rsplit(".", 1)[-1], None)
    return found if isinstance(found, type) and issubclass(found, enum.Enum) else None


def _aggregate_class(aggregate: etree._Element) -> type | None:
    from pydexpi.pydexpi_classes import pydexpi_classes

    found = getattr(pydexpi_classes, aggregate.get("type", "").rsplit(".", 1)[-1], None)
    return found if isinstance(found, type) else None


def set_values(
    path: Path,
    key: str,
    assignments: list[tuple[str, str]],
    *,
    write: bool = True,
    name: str | None = None,
    fmt: bool = True,
) -> EditResult:
    """Set data values of the object *key* and refresh the labels that show them."""
    doc = Document.load(path, name)
    sheet = doc.sheet
    target = find_one(sheet, key)
    if in_catalogue(target):
        raise EditError(f"{sheet.label(target)} is a symbol in the shape catalogue")
    result = EditResult(doc.name)
    before = render_labels(doc, [target])
    label = sheet.label(target)
    instrument = instrument_tag(target) is not None
    old_category, old_number = data_value(target, _PIF_CATEGORY), data_value(target, _PIF_NUMBER)
    tags_before = {data_value(target, p) for p in TAG_DATA} | {instrument_tag(target)}
    for prop, value in assignments:
        change = assign(target, prop, value, f"{prop}={value}")
        result.changes.append(f"{label} {prop}: {change}")
    if instrument and {p for p, _ in assignments} & {_PIF_CATEGORY, _PIF_NUMBER}:
        # The sensor and actuator numbers carry the category and number:
        # AT3104 -> FT4150.
        parts = retag_instrument_parts(
            target,
            old_category,
            old_number,
            data_value(target, _PIF_CATEGORY),
            data_value(target, _PIF_NUMBER) or old_number or "",
        )
        result.changes += [f"  follows: {p}" for p in parts]
    tags_after = {data_value(target, p) for p in TAG_DATA} | {instrument_tag(target)}
    new_tags = [t for t in tags_after - tags_before if t]
    if new_tags:
        from chemeascode.domains.piping.tag_rules import tag_clashes

        for clash in tag_clashes(doc.path, doc.root, target, doc.name, tags=new_tags):
            result.notes.append(
                f"tag {clash.split(': ', 1)[0]} is also the tag of {clash.split(': ', 1)[1]}: "
                "cheme validate reports cheme.duplicate-tag"
            )
    result.changes += refresh_labels(doc, before)
    return finish(doc, result, write=write, fmt=fmt)


def parse_assignment(text: str, what: str = "PROPERTY=VALUE") -> tuple[str, str]:
    prop, sep, value = text.partition("=")
    prop = prop.strip()
    if not sep or not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*", prop):
        raise EditError(f"{text!r}: expected {what} (the DEXPI name, e.g. FluidCode=Nitrogen)")
    return prop, value


# -- labels ---------------------------------------------------------------------------------------


@dataclass
class _Rendered:
    element: etree._Element
    rendered: str | None
    literal_tail: bool


def _texts_showing(doc: Document, objects: list[etree._Element]) -> list[etree._Element]:
    """The ``Text`` elements whose templates show an attribute of *objects* (or their parts)."""
    ids = {o.get("id") for obj in objects for o in obj.iter("Object") if o.get("id")}
    found = []
    for text in doc.root.iter("Object"):
        if text.get("type") != TEXT:
            continue
        for fragment in text.iterfind(".//Components[@property='Fragments']/Object"):
            if fragment.get("type", "").endswith("AttributeRepresentation") and any(
                t in ids for t in _refs(fragment, "Object")
            ):
                found.append(text)
                break
    return found


def _render_with_pydexpi(doc: Document) -> dict[etree._Element, tuple[str | None, bool]] | None:
    """Every Text's rendering, from the document as it is now (None: no load).

    A Text without an id (a sheet not yet through ``cheme fmt``) gets a temporary one for
    the load, so its rendering can be matched to it too.
    """
    from pydexpi.pydexpi_classes.core.diagram import LiteralText
    from pydexpi.toolkits.label_toolkit import iter_texts, render_text_template

    from chemeascode.domains.piping import dexpi_io

    texts = [t for t in doc.root.iter("Object") if t.get("type") == TEXT]
    taken = {e.get("id") for e in doc.root.iter("Object") if e.get("id")}
    by_id = {t.get("id"): t for t in texts if t.get("id")}
    temporary = []
    counter = 0
    for text in texts:
        if text.get("id"):
            continue
        while f"chemeUnnamedText{counter}" in taken:
            counter += 1
        text.set("id", f"chemeUnnamedText{counter}")
        by_id[text.get("id")] = text
        temporary.append(text)
        counter += 1
    try:
        xml = doc.render()
    finally:
        for text in temporary:
            del text.attrib["id"]
    try:
        loaded = dexpi_io.load(xml.encode("utf-8"), strict=False)
    except (ValueError, TypeError):
        return None
    rendered = {}
    for text in iter_texts(loaded.model.diagram):
        element = by_id.get(text.id)
        if element is None:
            continue
        fragments = list(getattr(text.template, "fragments", None) or ())
        tail = bool(fragments) and isinstance(fragments[-1], LiteralText)
        rendered[element] = (render_text_template(text.template), tail)
    return rendered


def render_labels(doc: Document, objects: list[etree._Element]) -> list[_Rendered]:
    """Snapshot, before a change, what each label of *objects* renders."""
    texts = _texts_showing(doc, objects)
    if not texts:
        return []
    rendered = _render_with_pydexpi(doc) or {}
    return [_Rendered(t, *rendered.get(t, (None, False))) for t in texts]


def refresh_labels(doc: Document, before: list[_Rendered]) -> list[str]:
    """Bring the cached text of each snapshotted label up to date; one line per label changed."""
    if not before:
        return []
    after = _render_with_pydexpi(doc)
    if after is None:
        return ["  labels not refreshed: pyDEXPI could not load the sheet (run cheme validate)"]
    lines = []
    for snap in before:
        string = snap.element.find("Data[@property='Text']/String")
        new, _ = after.get(snap.element, (None, False))
        if string is None or new is None:
            continue
        cached = string.text or ""
        old = snap.rendered
        if snap.literal_tail and old and cached.startswith(old) and cached != old:
            text = new + cached[len(old) :]  # "66KL21-80" from a template "66KL21" "-"
        else:
            text = new
        if text != cached:
            string.text = text
            lines.append(
                f"  label {snap.element.get('id') or 'Text'} {doc.line(snap.element)}: "
                f"{cached!r} -> {text!r}"
            )
    return lines


def xml_label_text(text: etree._Element, lookup: dict[str, etree._Element]) -> str | None:
    """A label's text from its template, for String attributes only (None: cannot say)."""
    parts = []
    for fragment in text.iterfind(".//Components[@property='Fragments']/Object"):
        kind = fragment.get("type", "")
        if kind.endswith("LiteralText"):
            parts.append(fragment.findtext("Data[@property='Text']/String") or "")
        elif kind.endswith("AttributeRepresentation"):
            targets = _refs(fragment, "Object")
            obj = lookup.get(targets[0]) if targets else None
            attribute = fragment.findtext("Data[@property='AttributeName']/String") or ""
            data = obj.find(f"Data[@property='{attribute}']") if obj is not None else None
            if data is None:
                return None
            child = next(iter(data), None)
            if child is None or child.tag != "String":
                return None
            parts.append(child.text or "")
        else:
            return None
    return "".join(parts) if parts else None
