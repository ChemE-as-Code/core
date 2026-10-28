"""``cheme copy``: duplicate an object with everything that draws it.

The copy is the object's ``<Object>`` block (with its parts: nozzles, nodes, chambers, ...) and
every ``RepresentationGroup`` that draws it or one of its parts (symbol, node positions, labels,
the equipment data table). Every id inside the copies is renamed deterministically:

- the copied object's own id becomes the prefix: ``CentrifugalPump1`` -> ``Pump_P4711B``;
- an id that starts with it keeps its suffix: ``CentrifugalPump1_Drawing1`` ->
  ``Pump_P4711B_Drawing1``;
- any other id gets the prefix in front: ``Nozzle1`` -> ``Pump_P4711B_Nozzle1``.

References between copied objects follow the renaming; references out of the copy (shapes in
the catalogue, a sensing location) are kept, except connections (``SourceItem``, ``TargetNode``,
a ``ConnectorLine``'s ``Source``, ...), which would join one node twice: they are dropped and
reported. Pipes and segments attached to the original are not copied; they are reported too.

Drawing coordinates move by the offset (sheet mm, Y down). An equipment data table
(``EquipmentBarLabel``) sits in the band of tables at the bottom of the sheet rather than next
to its symbol, so it goes into the nearest free slot of that band instead; only when there is
none does it move with the offset (and the output says so).

A pure text transform: the copies are inserted next to the originals and the rest of the file
is left byte for byte as it was. Run ``cheme fmt`` and ``cheme validate`` afterwards.
"""

from __future__ import annotations

import contextlib
import copy as _copy
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from lxml import etree

from chemeascode.domains.piping.authoring._xml import (
    ID_PATTERN,
    check_id,
    extent,
    fmt_num,
    indent_at,
    offsets_by_element,
    points_of,
    shift_point,
)
from chemeascode.domains.piping.authoring.edit import (
    TAG_DATA,
    EditError,
    assign,
    compact,
    retag_instrument_parts,
    split_instrument_tag,
    xml_label_text,
)
from chemeascode.domains.piping.show import (
    TAG_PROPERTIES,
    Sheet,
    data_value,
    instrument_tag,
    short_class,
)

#: Reference properties that connect piping or drawing lines; never copied pointing outside.
CONNECTIONS = frozenset(
    {"SourceItem", "SourceNode", "TargetItem", "TargetNode", "Source", "Target", "Node"}
)

BAR_LABEL = "Plant/Diagram.EquipmentBarLabel"
_BAND_GAP_X = 2.0
_BAND_GAP_Y = 2.5


class CopyError(Exception):
    """The copy cannot be made; the message says why and what to do."""


@dataclass
class Insertion:
    offset: int
    text: str
    root_ids: list[str]


@dataclass
class CopyResult:
    """What ``copy_object`` did (or, with ``write=False``, would do)."""

    path: Path
    source_id: str
    new_id: str
    renamed: dict[str, str]
    conceptual_ids: list[str]
    #: The id of each copied drawing's original, in the order of ``xml_drawings`` (None: no id).
    drawing_ids: list[str | None]
    xml_conceptual: str
    xml_drawings: list[str]
    old_tag: str | None = None
    new_tag: str | None = None
    tag_fields: list[str] = field(default_factory=list)
    texts_updated: int = 0
    table_note: str | None = None
    dropped: list[str] = field(default_factory=list)
    not_copied: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    #: Inner tags renamed (--rename/--renumber), values set (--set), ends connected (--connect,
    #: --sense-at): one line each.
    edits: list[str] = field(default_factory=list)
    #: Tags of the copy that other objects on the P&IDs carry too.
    duplicates: list[str] = field(default_factory=list)

    def report(self, name: str) -> list[str]:
        """The lines ``cheme copy`` prints."""
        tag = f" [{self.old_tag}]" if self.old_tag else ""
        new_tag = f" [{self.new_tag or self.old_tag}]" if (self.new_tag or self.old_tag) else ""
        lines = [f"copied {self.source_id}{tag} -> {self.new_id}{new_tag} in {name}"]
        if self.written:
            lines.append("written:")
            lines += [f"  {w}" for w in self.written]
        conceptual = [i for i in self.renamed if i in self.conceptual_ids]
        lines.append(f"new ids ({len(self.renamed)}; old -> new):")
        for old in conceptual:
            lines.append(f"  {old} -> {self.renamed[old]}")
        drawn = [old for old in self.drawing_ids if old]
        for old in drawn:
            lines.append(f"  {old} -> {self.renamed[old]} (drawing)")
        rest = len(self.renamed) - len(conceptual) - len(drawn)
        if rest:
            lines.append(f"  and {rest} id(s) inside the drawing(s), renamed the same way")
        if self.new_tag:
            fields = ", ".join(self.tag_fields)
            lines.append(
                f"tag: {self.old_tag or '(none)'} -> {self.new_tag} ({fields}); "
                f"{self.texts_updated} label text(s) updated"
            )
        lines += self.edits
        if self.table_note:
            lines.append(f"data table: {self.table_note}")
        if self.duplicates:
            lines.append(
                "duplicate tags (give each its own: copy again with --rename OLD=NEW or "
                "--renumber OLD:NEW, or cheme rename ID NEWTAG --tag after the copy):"
            )
            lines += [f"  {d}" for d in self.duplicates]
        else:
            lines.append("duplicate tags: none")
        for note in self.notes:
            lines.append(f"note: {note}")
        if self.not_copied or self.dropped:
            lines.append("not copied (connect or add by hand):")
            lines += [f"  {n}" for n in self.not_copied]
            lines += [f"  {d}" for d in self.dropped]
        else:
            lines.append("not copied: nothing (no references from outside the copy)")
        if self.written:
            lines.append(f"next: cheme fmt {name} && cheme validate")
        return lines


def new_id_for(old: str, source: str, prefix: str) -> str:
    if old == source:
        return prefix
    if old.startswith(source + "_"):
        return prefix + old[len(source) :]
    return f"{prefix}_{old}"


def _outermost(groups: list[etree._Element]) -> list[etree._Element]:
    chosen = set(groups)
    return [g for g in groups if not any(a in chosen for a in g.iterancestors())]


def _in_conceptual(element: etree._Element) -> bool:
    return not any(
        a.tag == "Components" and a.get("property") in ("Diagram", "ShapeCatalogues")
        for a in element.iterancestors()
    )


def _split_tag(tag: str) -> tuple[str, str, str] | None:
    match = re.fullmatch(r"([A-Za-z]*)[-\s]?(\d+)(.*)", tag)
    return (match.group(1), match.group(2), match.group(3)) if match else None


def _set_string(element: etree._Element, prop: str, value: str) -> bool:
    data = element.find(f"Data[@property='{prop}']")
    if data is None:
        return False
    string = data.find("String")
    if string is None:
        for child in list(data):
            data.remove(child)
        string = etree.SubElement(data, "String")
    string.text = value
    return True


_PIF_CATEGORY = "ProcessInstrumentationFunctionCategory"
_PIF_LETTERS = "ProcessInstrumentationFunctions"
_PIF_NUMBER = "ProcessInstrumentationFunctionNumber"


def _split_instrument_tag(original: etree._Element, tag: str) -> tuple[str | None, str | None, str]:
    """``PICSA-4713.02`` -> (``P``, ``ICSA``, ``4713.02``): see ``edit.split_instrument_tag``."""
    try:
        return split_instrument_tag(data_value(original, _PIF_CATEGORY), tag)
    except EditError as failure:
        raise CopyError(str(failure)) from failure


def _retag_instrument(
    original: etree._Element,
    conceptual: etree._Element,
    drawing_copies: list[etree._Element],
    tag: str,
    new_id: str,
    result: CopyResult,
) -> None:
    """Set an instrument's category, letters and number; follow its parts and labels."""
    category, letters, number = _split_instrument_tag(original, tag)
    values = {} if category is None else {_PIF_CATEGORY: category, _PIF_LETTERS: letters or ""}
    values[_PIF_NUMBER] = number
    for prop, value in values.items():
        if not value and conceptual.find(f"Data[@property='{prop}']") is None:
            continue
        if not _set_string(conceptual, prop, value):
            etree.SubElement(
                etree.SubElement(conceptual, "Data", property=prop), "String"
            ).text = value
        result.tag_fields.append(f"{prop} {value!r}")
    result.new_tag = instrument_tag(conceptual) or tag

    # The functions inside (sensor AT4149, actuator AV4149) carry the measured variable and the
    # loop number: an AI copied as FI gets the sensor FT4149.
    result.tag_fields += retag_instrument_parts(
        conceptual,
        data_value(original, _PIF_CATEGORY),
        data_value(original, _PIF_NUMBER),
        category,
        number,
    )

    # Labels whose template shows these attributes of the copy: their cached text follows.
    for copy_ in drawing_copies:
        for text_object in copy_.iter("Object"):
            if text_object.get("type") != "Core/Diagram.Text":
                continue
            string = text_object.find("Data[@property='Text']/String")
            fragments = text_object.findall(".//Components[@property='Fragments']/Object")
            if string is None or not fragments:
                continue
            shown = []
            for fragment in fragments:
                name = fragment.findtext("Data[@property='AttributeName']/String")
                target = fragment.find("References[@property='Object']")
                if (
                    fragment.get("type") != "Core/Diagram.AttributeRepresentation"
                    or target is None
                    or target.get("objects", "").lstrip("#") != new_id
                ):
                    shown = []
                    break
                shown.append(data_value(conceptual, name) or "")
            if shown and any(
                n in values
                for n in (f.findtext("Data[@property='AttributeName']/String") for f in fragments)
            ):
                text = "".join(shown)
                if text != string.text:
                    string.text = text
                    result.texts_updated += 1


def _pydexpi_class(element: etree._Element) -> type | None:
    from pydexpi.pydexpi_classes import pydexpi_classes

    return getattr(pydexpi_classes, short_class(element), None)


def _cannot_hold(parent: etree._Element, prop: str, child: etree._Element) -> str | None:
    """Why *parent* cannot hold *child* in ``Components property=prop`` (None: it can).

    Asks pyDEXPI's class of the parent for a composition field of that name and, where the
    field's item class is known, whether the child's class is one. pyDEXPI drops what it has
    no field for, and every reference to it breaks.
    """
    from pydexpi.pydexpi_classes import pydexpi_classes

    parent_class, child_class = _pydexpi_class(parent), _pydexpi_class(child)
    if parent_class is None:
        return None  # not a class pyDEXPI knows: leave it to validate
    name = prop[:1].lower() + prop[1:]
    fields = getattr(parent_class, "model_fields", {})
    compositions = [
        k
        for k, f in fields.items()
        if (f.json_schema_extra or {}).get("attribute_category") == "composition"
    ]
    if name not in compositions:
        holders = ", ".join(c[:1].upper() + c[1:] for c in compositions) or "none"
        return (
            f"a {short_class(parent)} has no {prop} (its compositions: {holders}); "
            f"{short_class(child)} {child.get('id')} lives in {prop}. Choose a parent of the "
            "kind that holds the original"
        )
    if child_class is not None:
        allowed = [
            getattr(pydexpi_classes, n, None)
            for n in re.findall(r"\b([A-Z][A-Za-z0-9]+)\b", str(fields[name].annotation))
        ]
        allowed = [a for a in allowed if isinstance(a, type)]
        if allowed and not any(issubclass(child_class, a) for a in allowed):
            kinds = ", ".join(a.__name__ for a in allowed)
            return f"{short_class(parent)}.{prop} holds {kinds}, not {short_class(child)}"
    return None


def _texts(element: etree._Element) -> list[etree._Element]:
    return [
        o.find("Data[@property='Text']/String")
        for o in element.iter("Object")
        if o.get("type") == "Core/Diagram.Text"
        and o.find("Data[@property='Text']/String") is not None
    ]


class _Band:
    """The equipment data tables' band: where a copied table can go."""

    def __init__(self, sheet: Sheet):
        self.occupied: list[tuple[float, float, float, float]] = []
        for element in sheet.root.iter("Object"):
            kind = element.get("type", "")
            parent = element.getparent()
            title_block = (
                kind == "Core/Diagram.Label"
                and parent is not None
                and parent.get("property") == "Groups"
                and parent.getparent() is not None
                and parent.getparent().get("type") == "Core/Diagram.Diagram"
            )
            if kind == BAR_LABEL or title_block:
                box = extent(element)
                if box:
                    self.occupied.append(box)
        diagram = sheet.root.find(".//Object[@type='Core/Diagram.Diagram']")
        self.limits = (0.0, 0.0, 420.0, 297.0)
        if diagram is not None:
            with contextlib.suppress(TypeError, ValueError):
                self.limits = tuple(  # type: ignore[assignment]
                    float(diagram.findtext(f"Data[@property='{p}']/Double"))
                    for p in ("MinX", "MinY", "MaxX", "MaxY")
                )
        border = sheet.root.find(".//Object[@type='Core/Diagram.Border']")
        if border is not None and extent(border):
            self.limits = extent(border)  # type: ignore[assignment]

    def free(self, x: float, y: float, w: float, h: float) -> bool:
        x0, y0, x1, y1 = self.limits
        if x < x0 or y < y0 or x + w > x1 or y + h > y1:
            return False
        eps = 1e-6
        return all(
            x + w <= a0 + eps or x >= a1 - eps or y + h <= b0 + eps or y >= b1 - eps
            for a0, b0, a1, b1 in self.occupied
        )

    def slot(self, box: tuple[float, float, float, float]) -> tuple[float, float] | None:
        """The free slot of the table grid nearest to *box* (its top-left corner)."""
        x0, y0, x1, y1 = box
        w, h = x1 - x0, y1 - y0
        rows = sorted({b[1] for b in self.occupied if abs((b[3] - b[1]) - h) < 0.5})
        if not rows:
            return None
        lx0, _, lx1, _ = self.limits
        candidates = []
        for row in rows:
            column = x0
            while column - (w + _BAND_GAP_X) >= lx0:
                column -= w + _BAND_GAP_X
            while column + w <= lx1:
                candidates.append((column, row))
                column += w + _BAND_GAP_X
        # A new row above the topmost one, when the band is full.
        top = rows[0] - h - _BAND_GAP_Y
        column = x0
        while column - (w + _BAND_GAP_X) >= lx0:
            column -= w + _BAND_GAP_X
        while column + w <= lx1:
            candidates.append((column, top))
            column += w + _BAND_GAP_X
        candidates.sort(key=lambda c: (c[1] == top, abs(c[1] - y0) + abs(c[0] - x0)))
        for cx, cy in candidates:
            if self.free(cx, cy, w, h):
                self.occupied.append((cx, cy, cx + w, cy + h))
                return cx, cy
        return None


def copy_object(
    path: Path,
    key: str,
    prefix: str,
    *,
    tag: str | None = None,
    offset: tuple[float, float] = (0.0, 0.0),
    into: str | None = None,
    write: bool = True,
    name: str | None = None,
    renames: list[tuple[str, str]] | None = None,
    renumbers: list[tuple[str, str]] | None = None,
    sets: list[tuple[str, str]] | None = None,
    sense_at: str | None = None,
    connects: list[tuple[str, str]] | None = None,
) -> CopyResult:
    """Copy the object *key* (an id or a unique tag) in *path*; write it unless not *write*.

    *renames* (``HV-4146``, ``HV-4147``) give inner tags new values, in their data, the label
    texts and the ids that spell them; *renumbers* (``4144``, ``4145``) replace a number the
    same way. *sets* (``FluidCode``, ``Liquid nitrogen``) set a data value on every copied
    object that has it. *sense_at* (``ID`` or ``ID:X,Y``) re-points an instrument's sensing
    location, and with X,Y draws the measuring line from a new node position there. *connects*
    (``PIPE`` or ``PIPE.source``/``PIPE.target``, ``ITEM:NODE``) connect a copied pipe's open
    end, with its segment's end and its drawn line.
    """
    check_id(prefix, "--prefix")
    renames, renumbers, sets, connects = renames or [], renumbers or [], sets or [], connects or []
    sheet_name = name or str(path)
    try:
        sheet = Sheet.load(path, sheet_name)
    except Exception as failure:  # ShowError: not well-formed
        raise CopyError(str(failure)) from failure
    text = path.read_bytes().decode("utf-8")
    offsets = offsets_by_element(sheet.root, text)

    matches = [m for m in sheet.find(key) if _in_conceptual(m)]
    if not matches:
        raise CopyError(f"{sheet_name}: no object with id or tag {key!r} in the plant model")
    if len(matches) > 1:
        names = ", ".join(sheet.label(m) for m in matches)
        raise CopyError(f"{key!r} names {len(matches)} objects ({names}): give the XML id")
    original = matches[0]
    source = original.get("id")
    if not source:
        raise CopyError(f"{sheet.label(original)} has no id: run cheme fmt first")
    if original.getparent() is None or original.getparent().tag != "Components":
        raise CopyError(f"{source} is not a part of another object; it cannot be copied")

    # What is copied: the object with its parts, and the outermost drawings of any of them.
    conceptual_ids = [o.get("id") for o in original.iter("Object") if o.get("id")]
    drawings = _outermost(
        [g for object_id in conceptual_ids for g in sheet.drawings.get(object_id, [])]
    )
    copied = {original, *drawings}
    ids = list(conceptual_ids)
    for drawing in drawings:
        ids += [o.get("id") for o in drawing.iter("Object") if o.get("id")]
    old_tag = sheet.tag(original)
    tag_rename = [(old_tag, tag)] if tag and old_tag and compact(old_tag) != compact(tag) else []
    # Ids inside that spell the tag follow it too (CV_LOX4004 of line LOX-4004 -> CV_LIN4004).
    substitutions = _id_substitutions(renames + tag_rename, renumbers)

    def derived(old: str) -> str:
        new = new_id_for(old, source, prefix)
        rest = new[len(prefix) :]
        for pattern, replacement in substitutions:
            rest = pattern.sub(replacement, rest)
        return prefix + rest

    renamed = {old: derived(old) for old in dict.fromkeys(ids)}
    clashes = sorted(new for new in renamed.values() if new in sheet.by_id)
    if clashes:
        raise CopyError(
            f"--prefix {prefix}: the copy's ids would clash with existing ones "
            f"({', '.join(clashes[:5])}{', ...' if len(clashes) > 5 else ''}); choose another"
        )
    bad = [new for new in renamed.values() if not ID_PATTERN.match(new)]
    if bad:
        raise CopyError(f"--prefix {prefix}: invalid id {bad[0]!r}")

    result = CopyResult(
        path=path,
        source_id=source,
        new_id=prefix,
        renamed=renamed,
        conceptual_ids=conceptual_ids,
        drawing_ids=[d.get("id") for d in drawings],
        xml_conceptual="",
        xml_drawings=[],
        old_tag=sheet.tag(original),
    )

    # What stays behind: references from outside the copy to what is copied.
    inside = {e for c in copied for e in c.iter()}
    left_behind = [
        (reference, prop, object_id)
        for object_id in conceptual_ids
        for reference, prop in sheet.incoming.get(object_id, [])
        if reference not in inside
    ]

    # Copy, rename, re-point.
    dropped: list[tuple[etree._Element, str, str]] = []  # (holder in the copy, property, target)

    def transform(element: etree._Element) -> etree._Element:
        clone = _copy.deepcopy(element)
        clone.tail = None
        for o in clone.iter("Object"):
            if o.get("id") in renamed:
                o.set("id", renamed[o.get("id")])
        for reference in list(clone.iter("References")):
            prop = reference.get("property", "")
            kept = []
            for target in reference.get("objects", "").split():
                bare = target.lstrip("#")
                if bare in renamed:
                    kept.append("#" + renamed[bare])
                elif prop in CONNECTIONS:
                    dropped.append((reference.getparent(), prop, bare))
                else:
                    kept.append(target)
            if kept:
                reference.set("objects", " ".join(kept))
            else:
                reference.getparent().remove(reference)
        return clone

    conceptual = transform(original)
    drawing_copies = [transform(d) for d in drawings]
    _apply_renames(conceptual, drawing_copies, renames, renumbers, result)

    # Tag.
    if tag and instrument_tag(original) is not None:
        result.new_tag = tag
        _retag_instrument(original, conceptual, drawing_copies, tag, renamed[source], result)
    elif tag:
        result.new_tag = tag
        prop = next(
            (
                p
                for p in TAG_PROPERTIES
                if p != "SubTagName" and conceptual.find(f"Data[@property='{p}']") is not None
            ),
            None,
        )
        if prop is None:
            result.notes.append(
                f"{short_class(original)} has no tag property to set; --tag {tag} only "
                "replaced label texts"
            )
        else:
            _set_string(conceptual, prop, tag)
            result.tag_fields.append(f"{prop} {tag}")
            parts = _split_tag(tag) if prop == "TagName" else None
            if parts:
                for field_name, value in zip(
                    ("TagNamePrefix", "TagNameSequenceNumber", "TagNameSuffix"), parts, strict=True
                ):
                    if _set_string(conceptual, field_name, value):
                        result.tag_fields.append(f"{field_name} {value!r}")
        old = result.old_tag
        if old:
            pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(old)}(?![A-Za-z0-9])")
            for copy_ in drawing_copies:
                for string in _texts(copy_):
                    if string.text and pattern.search(string.text):
                        string.text = pattern.sub(tag, string.text)
                        result.texts_updated += 1
    elif result.old_tag:
        result.notes.append(
            f"the copy keeps the tag {result.old_tag}: give it its own with --tag (tags are "
            "unique in the lists)"
        )

    _apply_sets(conceptual, drawing_copies, sets, result)
    sense_insertion = _sense_at(
        sheet, conceptual, drawing_copies, sense_at, prefix, dropped, result, offset
    )
    _connect(sheet, conceptual, drawing_copies, connects, renamed, dropped, result)
    for holder, prop, target in dropped:
        result.dropped.append(
            f"dropped {holder.get('id') or short_class(holder)} {prop} -> {target} "
            "(outside the copy; it would connect twice)"
        )
    if not sense_at and instrument_tag(original) is not None:
        for function in conceptual.iter("Object"):
            for target in _ref_ids(function, "SensingLocation"):
                result.notes.append(
                    f"{function.get('id')} SensingLocation -> {target} (the original's): "
                    "re-point it with --sense-at ID[:X,Y]"
                )
    result.duplicates = _duplicate_tags(path, sheet, conceptual)

    # Offset; equipment data tables go to a free slot of their band.
    dx, dy = offset
    band = _Band(sheet)
    for copy_ in drawing_copies:
        tables = [o for o in copy_.iter("Object") if o.get("type") == BAR_LABEL]
        in_tables = {p for t in tables for p in points_of(t)}
        for point_ in points_of(copy_):
            if point_ not in in_tables:
                shift_point(point_, dx, dy)
        for table in tables:
            box = extent(table)
            if box is None:
                continue
            slot = band.slot(box)
            if slot is not None:
                tx, ty = slot[0] - box[0], slot[1] - box[1]
                where = f"placed in a free slot of the data-table band at {fmt_num(slot[0])},"
                where += f"{fmt_num(slot[1])} (top left)"
            else:
                tx, ty = dx, dy
                where = (
                    "no free slot in the data-table band: moved with the offset to "
                    f"{fmt_num(box[0] + dx)},{fmt_num(box[1] + dy)}; place it by hand"
                )
            for point_ in points_of(table):
                shift_point(point_, tx, ty)
            result.table_note = where

    result.xml_conceptual = etree.tostring(conceptual, encoding="unicode")
    result.xml_drawings = [etree.tostring(d, encoding="unicode") for d in drawing_copies]

    # Where the copies go.
    insertions: list[Insertion] = []
    parent_object = sheet.by_id.get(into) if into else None
    if into:
        if parent_object is None or not _in_conceptual(parent_object):
            raise CopyError(f"--into {into}: no object with this id in the plant model")
        if parent_object is original or original in parent_object.iterancestors():
            raise CopyError(f"--into {into}: cannot copy {source} into itself")
        prop = original.getparent().get("property")
        target = parent_object.find(f"Components[@property='{prop}']")
        refusal = _cannot_hold(parent_object, prop, original)
        if refusal:
            raise CopyError(f"--into {into}: {refusal}")
        holders = target.findall("Object") if target is not None else []
        if holders:
            end = offsets[holders[-1]][1]
            insertions.append(
                Insertion(
                    end,
                    "\n" + indent_at(text, offsets[holders[-1]][0]) + result.xml_conceptual,
                    [prefix],
                )
            )
        else:
            start, end = offsets[parent_object]
            close = text.rfind("</", start, end)
            pad = indent_at(text, start) + "  "
            block = (
                f'{pad}<Components property="{prop}">\n{pad}  {result.xml_conceptual}\n'
                f"{pad}</Components>\n"
            )
            line_start = text.rfind("\n", 0, close) + 1
            insertions.append(Insertion(line_start, block, [prefix]))
    else:
        start, end = offsets[original]
        insertions.append(
            Insertion(end, "\n" + indent_at(text, start) + result.xml_conceptual, [prefix])
        )

    parent_drawing = None
    if parent_object is not None:
        candidates = _outermost(sheet.drawings.get(into or "", []))
        if candidates:
            groups = candidates[0].find("Components[@property='Groups']")
            if groups is not None and groups.findall("Object"):
                parent_drawing = groups.findall("Object")[-1]
    for drawing, xml in zip(drawings, result.xml_drawings, strict=True):
        anchor = parent_drawing if parent_drawing is not None else drawing
        start, end = offsets[anchor]
        new = renamed.get(drawing.get("id") or "", "")
        insertions.append(Insertion(end, "\n" + indent_at(text, start) + xml, [new]))

    if sense_insertion is not None:
        group, xml = sense_insertion
        insertions.append(_insertion_into(text, offsets, group, "NodePositions", xml))

    def report_left_behind(shifted: list[Insertion]) -> None:
        """One line per object left behind: what it references in the copied object."""
        by_holder: dict[etree._Element, list[tuple[etree._Element, str, str]]] = {}
        for reference, prop, object_id in left_behind:
            by_holder.setdefault(reference.getparent(), []).append((reference, prop, object_id))
        for holder, refs in by_holder.items():
            start, _ = sheet.span.get(holder, (holder.sourceline or 0, 0))
            begin = offsets[holder][0]
            start += sum(i.text.count("\n") for i in shifted if i.offset <= begin)
            what = ", ".join(f"{prop} -> {object_id}" for _, prop, object_id in refs)
            result.not_copied.append(f"{sheet.label(holder)} {sheet_name}:{start}: {what}")

    if not write:
        report_left_behind([])
        return result
    report_left_behind(insertions)

    for insertion in sorted(insertions, key=lambda i: i.offset, reverse=True):
        text = text[: insertion.offset] + insertion.text + text[insertion.offset :]
    path.write_bytes(text.encode("utf-8"))

    written = Sheet.load(path, sheet_name)
    for insertion in insertions:
        for object_id in insertion.root_ids:
            element = written.by_id.get(object_id)
            if element is None:
                continue
            kind = "drawing" if not _in_conceptual(element) else "object"
            line = f"{written.where(element)} {written.label(element)} ({kind})"
            box = extent(element) if kind == "drawing" else None
            if box:
                line += " at " + ",".join(fmt_num(v) for v in box) + " mm"
            result.written.append(line)
    if into and parent_drawing is None and drawings:
        result.notes.append(
            f"{into} has no drawing group with Groups: the drawing copies stay next to the "
            "originals"
        )
    return result


# -- options that adapt the copy: --rename, --renumber, --set, --sense-at, --connect ------------


def _ref_ids(element: etree._Element, prop: str) -> list[str]:
    reference = element.find(f"References[@property='{prop}']")
    if reference is None:
        return []
    return [t.lstrip("#") for t in reference.get("objects", "").split()]


def _set_ref(element: etree._Element, prop: str, target: str) -> None:
    reference = element.find(f"References[@property='{prop}']")
    if reference is None:
        reference = etree.Element("References", objects="", property=prop)
        element.insert(0, reference)
        reference.tail = element.text or "\n"
    reference.set("objects", f"#{target}")


def _number_pattern(number: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![0-9]){re.escape(number)}(?![0-9])")


def _tag_pattern(tag: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(tag)}(?![A-Za-z0-9])")


def _id_substitutions(
    renames: list[tuple[str, str]], renumbers: list[tuple[str, str]]
) -> list[tuple[re.Pattern[str], str]]:
    """How the ids derived from inner tags follow --rename and --renumber."""
    subs = []
    for old, new in renames:
        if compact(old) and compact(new):
            subs.append(
                (re.compile(rf"(?<![A-Za-z0-9]){re.escape(compact(old))}(?![0-9])"), compact(new))
            )
    for old, new in renumbers:
        if not (old.isdigit() and new.isdigit()):
            raise CopyError(f"--renumber {old}:{new}: give two numbers, e.g. 4144:4145")
        subs.append((_number_pattern(old), new))
    return subs


def _apply_renames(
    conceptual: etree._Element,
    drawing_copies: list[etree._Element],
    renames: list[tuple[str, str]],
    renumbers: list[tuple[str, str]],
    result: CopyResult,
) -> None:
    """New inner tags: in the copied data, and in the label texts of the copied drawings."""
    texts = [s for copy_ in drawing_copies for s in _texts(copy_)]
    for old, new in renames:
        fields = []
        for obj in conceptual.iter("Object"):
            for data in obj.findall("Data"):
                string = data.find("String")
                if string is not None and string.text == old:
                    string.text = new
                    fields.append(f"{obj.get('id')} {data.get('property')}")
        pattern = _tag_pattern(old)
        labels = 0
        for string in texts:
            if string.text and pattern.search(string.text):
                string.text = pattern.sub(new, string.text)
                labels += 1
        if not fields and not labels:
            raise CopyError(f"--rename {old}={new}: nothing in the copy has the tag {old!r}")
        result.edits.append(
            f"renamed: {old} -> {new} ({', '.join(fields) or 'no data'}; {labels} label text(s))"
        )
    for old, new in renumbers:
        pattern = _number_pattern(old)
        fields = []
        for obj in conceptual.iter("Object"):
            for prop in (*TAG_DATA, "TagNameSequenceNumber"):
                string = obj.find(f"Data[@property='{prop}']/String")
                if string is not None and string.text and pattern.search(string.text):
                    string.text = pattern.sub(new, string.text)
                    fields.append(f"{obj.get('id')} {prop} {string.text!r}")
        labels = 0
        for string in texts:
            if string.text and pattern.search(string.text):
                string.text = pattern.sub(new, string.text)
                labels += 1
        if not fields and not labels:
            raise CopyError(f"--renumber {old}:{new}: no tag or label in the copy has {old}")
        result.edits.append(
            f"renumbered: {old} -> {new} ({', '.join(fields) or 'no data'}; {labels} label text(s))"
        )


def _apply_sets(
    conceptual: etree._Element,
    drawing_copies: list[etree._Element],
    sets: list[tuple[str, str]],
    result: CopyResult,
) -> None:
    """--set PROP=VALUE on every copied object that has PROP, and the labels showing it."""
    lookup = {o.get("id"): o for o in conceptual.iter("Object") if o.get("id")}
    for prop, value in sets:
        holders = [
            o for o in conceptual.iter("Object") if o.find(f"Data[@property='{prop}']") is not None
        ]
        if not holders:
            raise CopyError(
                f"--set {prop}={value}: no copied object has {prop}; set it after the copy with "
                f"cheme set ID {prop}=..."
            )
        old_values = {o.get("id"): data_value(o, prop) for o in holders}
        for holder in holders:
            try:
                assign(holder, prop, value, f"--set {prop}={value}")
            except EditError as failure:
                raise CopyError(str(failure)) from failure
        held = {o.get("id") for o in holders}
        labels = 0
        for copy_ in drawing_copies:
            for text in copy_.iter("Object"):
                if text.get("type") != "Core/Diagram.Text":
                    continue
                shown = [
                    f
                    for f in text.iterfind(".//Components[@property='Fragments']/Object")
                    if f.findtext("Data[@property='AttributeName']/String") == prop
                    and set(_ref_ids(f, "Object")) & held
                ]
                string = text.find("Data[@property='Text']/String")
                if not shown or string is None:
                    continue
                rendered = xml_label_text(text, lookup)
                if rendered is None:
                    target = _ref_ids(shown[0], "Object")[0]
                    old = old_values.get(target) or ""
                    new = data_value(lookup[target], prop) or ""
                    rendered = (string.text or "").replace(old, new) if old else string.text
                if rendered != string.text:
                    string.text = rendered
                    labels += 1
        result.edits.append(
            f"set: {prop} = {value!r} on {', '.join(sorted(held))}; {labels} label text(s) updated"
        )


def _new_element_id(sheet: Sheet, wanted: str) -> str:
    candidate, n = wanted, 2
    while candidate in sheet.by_id:
        candidate, n = f"{wanted}{n}", n + 1
    return candidate


def _sense_at(
    sheet: Sheet,
    conceptual: etree._Element,
    drawing_copies: list[etree._Element],
    sense_at: str | None,
    prefix: str,
    dropped: list[tuple[etree._Element, str, str]],
    result: CopyResult,
    offset: tuple[float, float] = (0.0, 0.0),
) -> tuple[etree._Element, str] | None:
    """--sense-at ID[:X,Y]: the copy's sensing location, and the node its measuring line starts at.

    Returns the drawing group of ID and the XML of the new ``InstrumentationNodePosition`` to
    insert into it (None without X,Y).
    """
    if not sense_at:
        return None
    target, _, at = sense_at.partition(":")
    element = sheet.by_id.get(target)
    if element is None or not _in_conceptual(element):
        raise CopyError(
            f"--sense-at {sense_at}: no object with the id {target!r} in the plant model"
        )
    functions = [
        o
        for o in conceptual.iter("Object")
        if o.find("References[@property='SensingLocation']") is not None
    ]
    if not functions:
        functions = [
            o
            for o in conceptual.iter("Object")
            if o.get("type", "").endswith("ProcessSignalGeneratingFunction")
        ]
    if not functions:
        raise CopyError(f"--sense-at {sense_at}: the copy has no ProcessSignalGeneratingFunction")
    for function in functions:
        _set_ref(function, "SensingLocation", target)
        result.edits.append(f"sensing location: {function.get('id')} SensingLocation -> {target}")
    if not at:
        return None
    from chemeascode.domains.piping.authoring._xml import obj, parse_pair, point

    x, y = parse_pair(at, "--sense-at X,Y")
    groups = _outermost(sheet.drawings.get(target, []))
    if not groups:
        raise CopyError(
            f"--sense-at {sense_at}: {target} is not drawn; give --sense-at {target} alone and "
            "connect the measuring line by hand"
        )
    if _move_own_measuring_line(drawing_copies, (x, y), offset, groups[0].get("id"), result):
        return None
    position_id = _new_element_id(sheet, f"{prefix}_SensePosition")
    position = obj(
        position_id, "Plant/Diagram.InstrumentationNodePosition", point("Position", x, y)
    )
    # The measuring line: the ConnectorLine of the copy whose end at the old sensing node was
    # dropped.
    connected = False
    for holder, prop, old in list(dropped):
        old_element = sheet.by_id.get(old)
        if (
            holder.get("type") == "Core/Diagram.ConnectorLine"
            and old_element is not None
            and old_element.get("type", "").endswith("InstrumentationNodePosition")
            and any(holder in set(c.iter()) for c in drawing_copies)
        ):
            _set_ref(holder, prop, position_id)
            dropped.remove((holder, prop, old))
            result.edits.append(
                f"measuring line: {holder.get('id')} {prop} -> {position_id} at "
                f"{fmt_num(x)},{fmt_num(y)} (new, in {groups[0].get('id')})"
            )
            connected = True
    if not connected:
        result.notes.append(
            f"--sense-at: no measuring line of the copy was left open; {position_id} is drawn at "
            f"{fmt_num(x)},{fmt_num(y)}, connect a ConnectorLine to it by hand"
        )
    return groups[0], etree.tostring(position, encoding="unicode")


def _move_own_measuring_line(
    drawing_copies: list[etree._Element],
    at: tuple[float, float],
    offset: tuple[float, float],
    target_group: str | None,
    result: CopyResult,
) -> bool:
    """An instrument drawn by the authoring API carries both ends of its measuring line
    (``_SensePosition`` and ``_BubblePosition``) in its own drawing. Move the copy's sense end to
    *at* and its bubble end to the side of the bubble facing *at*, instead of adding a second
    sense position. The copy is shifted by *offset* afterwards, so the points written here are
    *at* minus the offset. False when the copy has no such line."""
    from chemeascode.domains.piping.authoring._xml import point
    from chemeascode.domains.piping.authoring.builders import _edge

    by_id = {e.get("id"): e for c in drawing_copies for e in c.iter("Object") if e.get("id")}

    def _position(element: etree._Element | None) -> etree._Element | None:
        if element is None:
            return None
        return element.find("Data[@property='Position']")

    for line in (e for e in by_id.values() if e.get("type") == "Core/Diagram.ConnectorLine"):
        source = by_id.get(next(iter(_ref_ids(line, "Source")), ""))
        target = by_id.get(next(iter(_ref_ids(line, "Target")), ""))
        if not all(
            e is not None and e.get("type", "").endswith("InstrumentationNodePosition")
            for e in (source, target)
        ):
            continue
        dx, dy = offset
        source.replace(_position(source), point("Position", at[0] - dx, at[1] - dy))
        message = (
            f"measuring line: {source.get('id')} moved to {fmt_num(at[0])},{fmt_num(at[1])} "
            f"(on {target_group})"
        )
        usages = [e for e in by_id.values() if e.get("type") == "Core/Diagram.ShapeUsage"]
        bubble = next((u for u in usages if u.get("id", "").endswith("BubbleShape")), None)
        bubble = bubble if bubble is not None else (usages[0] if usages else None)
        centre = _point_of(_position(bubble))
        old_end = _point_of(_position(target))
        if centre and old_end:
            radius = max(abs(old_end[0] - centre[0]), abs(old_end[1] - centre[1]))
            _, end = _edge((centre[0] + dx, centre[1] + dy), (radius, radius), at)
            target.replace(_position(target), point("Position", end[0] - dx, end[1] - dy))
            message += f"; {target.get('id')} to {fmt_num(end[0])},{fmt_num(end[1])}"
        result.edits.append(message)
        return True
    return False


def _point_of(data: etree._Element | None) -> tuple[float, float] | None:
    if data is None:
        return None
    from chemeascode.domains.piping.authoring._xml import point_xy

    value = data.find("AggregatedDataValue")
    return point_xy(value) if value is not None else None


def _position_of(sheet: Sheet, drawing_copies: list[etree._Element], node: str) -> str | None:
    """The id of the PipingNodePosition that draws *node* (on the sheet or in the copy)."""
    for reference, prop in sheet.incoming.get(node, []):
        holder = reference.getparent()
        if prop == "Node" and holder.get("id"):
            return holder.get("id")
    for copy_ in drawing_copies:
        for reference in copy_.iter("References"):
            if reference.get("property") == "Node" and reference.get("objects") == f"#{node}":
                return reference.getparent().get("id")
    return None


def _connect(
    sheet: Sheet,
    conceptual: etree._Element,
    drawing_copies: list[etree._Element],
    connects: list[tuple[str, str]],
    renamed: dict[str, str],
    dropped: list[tuple[etree._Element, str, str]],
    result: CopyResult,
) -> None:
    """--connect PIPE[.source|.target]=ITEM:NODE: close an end the copy left open."""
    in_copy = {o.get("id"): o for o in conceptual.iter("Object") if o.get("id")}
    for spec, end_text in connects:
        pipe_key, _, side = spec.partition(".")
        pipe_id = renamed.get(pipe_key, pipe_key)
        pipe = in_copy.get(pipe_id)
        if pipe is None:
            raise CopyError(f"--connect {spec}: no object {pipe_key!r} in the copy")
        item_id, sep, node_id = end_text.partition(":")
        if not sep:
            raise CopyError(f"--connect {spec}={end_text}: give the end as ITEM:NODE")
        item = in_copy.get(item_id) if item_id in in_copy else sheet.by_id.get(item_id)
        node = in_copy.get(node_id) if node_id in in_copy else sheet.by_id.get(node_id)
        if item is None or node is None:
            missing = item_id if item is None else node_id
            raise CopyError(f"--connect {spec}={end_text}: no object {missing!r}")
        owner = next(node.iterancestors("Object"), None)
        if owner is not item:
            hint = f" (it is a node of {owner.get('id')})" if owner is not None else ""
            raise CopyError(
                f"--connect {spec}={end_text}: {node_id} is not a node of {item_id}{hint}"
            )
        if node_id not in in_copy:
            # A node is the end of one pipe only (pydexpi_piping_node_single_connection).
            taken = [
                (reference.getparent(), prop)
                for reference, prop in sheet.incoming.get(node_id, [])
                if prop in ("SourceNode", "TargetNode")
            ]
            if taken:
                holder, prop = taken[0]
                raise CopyError(
                    f"--connect {spec}={end_text}: {node_id} is already the {prop} of "
                    f"{sheet.label(holder)}; connect to a free nozzle (a node no pipe ends at) "
                    "or re-point that pipe first"
                )
        open_ends = {
            prop[:6] for h, prop, _ in dropped if h is pipe and prop.endswith(("Item", "Node"))
        }
        if side:
            if side.lower() not in ("source", "target"):
                raise CopyError(f"--connect {spec}: the end is .source or .target")
            end = side.capitalize()
        elif len(open_ends) == 1:
            end = open_ends.pop()
        elif not open_ends:
            raise CopyError(
                f"--connect {spec}: {pipe_id} has no open end; name it ({pipe_key}.target=...)"
            )
        else:
            raise CopyError(
                f"--connect {spec}: both ends of {pipe_id} are open; name one "
                f"({pipe_key}.source=... or .target=...)"
            )
        old_targets = {
            prop: target
            for h, prop, target in dropped
            if h is pipe and prop in (f"{end}Item", f"{end}Node")
        }
        _set_ref(pipe, f"{end}Item", item_id)
        _set_ref(pipe, f"{end}Node", node_id)
        done = [f"{pipe_id} {end}Item/{end}Node -> {item_id}/{node_id}"]
        # The segment (or any other copied object) that ended where the pipe ended.
        for holder, prop, target in list(dropped):
            if prop in old_targets and old_targets[prop] == target:
                if holder is not pipe:
                    _set_ref(holder, prop, item_id if prop.endswith("Item") else node_id)
                    if prop.endswith("Item"):
                        done.append(f"{holder.get('id')} {end}Item/{end}Node")
                dropped.remove((holder, prop, target))
        # The drawn line that ended at the old node's position.
        old_node = old_targets.get(f"{end}Node")
        new_position = _position_of(sheet, drawing_copies, node_id)
        for holder, prop, target in list(dropped):
            old_position = sheet.by_id.get(target)
            if (
                prop in ("Source", "Target")
                and old_position is not None
                and old_node in _ref_ids(old_position, "Node")
            ):
                if new_position is None:
                    result.notes.append(
                        f"--connect: {node_id} has no PipingNodePosition; "
                        f"{holder.get('id')} {prop} stays open"
                    )
                    continue
                _set_ref(holder, prop, new_position)
                dropped.remove((holder, prop, target))
                done.append(f"{holder.get('id')} {prop} -> {new_position}")
        result.edits.append("connected: " + "; ".join(done))


def _sheet_tags(root: etree._Element) -> dict[str, list[etree._Element]]:
    from chemeascode.domains.piping.authoring.edit import in_conceptual

    found: dict[str, list[etree._Element]] = {}
    for element in root.iter("Object"):
        if not in_conceptual(element):
            continue
        tags = [instrument_tag(element)] + [
            data_value(element, p)
            for p in ("TagName", "LineNumber", "PipingComponentNumber", "PositionNumber")
        ]
        for tag in dict.fromkeys(t for t in tags if t):
            found.setdefault(tag, []).append(element)
    return found


def _duplicate_tags(path: Path, sheet: Sheet, conceptual: etree._Element) -> list[str]:
    """The copy's tags that objects on this sheet (and the workspace's other sheets) carry."""
    others: list[tuple[str, Sheet]] = [(sheet.name, sheet)]
    from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

    try:
        workspace = Workspace.find(path.parent)
        for other in workspace.pid_files():
            if other.resolve() != path.resolve() and other.is_file():
                with contextlib.suppress(Exception):
                    others.append((workspace.relative(other), Sheet.load(other)))
    # not in a plant repository, or a plant.yaml that does not load (validate reports it)
    except (NotAPlantRepository, OSError, ValueError, yaml.YAMLError):
        pass
    mine = _sheet_tags(conceptual)
    lines = []
    for tag, elements in mine.items():
        for name, other in others:
            for existing in _sheet_tags(other.root).get(tag, []):
                lines.append(
                    f"{tag}: {elements[0].get('id')} and {other.label(existing)} "
                    f"{name}:{other.span.get(existing, (existing.sourceline or 0,))[0]}"
                )
    return lines


def _insertion_into(
    text: str,
    offsets: dict[etree._Element, tuple[int, int]],
    group: etree._Element,
    prop: str,
    xml: str,
) -> Insertion:
    """Insert *xml* as a child of *group*'s ``Components property=prop`` (made if missing)."""
    holders = group.find(f"Components[@property='{prop}']")
    children = holders.findall("Object") if holders is not None else []
    if children:
        start, end = offsets[children[-1]]
        return Insertion(end, "\n" + indent_at(text, start) + xml, [])
    start, end = offsets[group]
    close = text.rfind("</", start, end)
    pad = indent_at(text, start) + "  "
    block = f'{pad}<Components property="{prop}">\n{pad}  {xml}\n{pad}</Components>\n'
    return Insertion(text.rfind("\n", 0, close) + 1, block, [])
