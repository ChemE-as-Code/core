"""Tags named in literal texts: trip notes and off-page connector texts against the plant.

A literal drawn text (no template) often names other objects: ``from P-03 LIN-3001``,
``LALL-4108 / TSLL-4114 trip P-4102A/B, XV-4137``. No template ties such a text to the object it
names, so a wrong tag there misleads silently. Two cross-sheet rules check them:

``cheme.label-tag-unknown`` (warning)
    a tag-like token that no list entry, drawn tag or declared sheet has. A token is tag-like when
    it has the shape of a known tag: the same letters and number of digits as a tag of the lists
    or sheets (``P-4199A`` like ``P-4102A``), or of an instrument loop (``LALL-4108`` is a
    function of level loop 4108, which ``LIA-4108`` is). ``P-4102A/B`` names ``P-4102A`` and
    ``P-4102B``.
``cheme.offpage-mismatch`` (warning)
    an off-page connector whose texts name another line than the connector's own -- one that
    differs only in its code (``LN-3001`` on line ``LIN-3001``), is not on the named sheet, or is
    not joined to the connector's line there -- or name a sheet that does not carry the line.

What the texts name and resolve is reported once per text as ``cheme.label-tag`` (info).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

#: A tag-like token: letters, a hyphen, digits, an optional letter suffix with ``/B`` siblings,
#: an optional ``.02`` loop suffix.
TAG_TOKEN = re.compile(
    r"(?<![\w.\-/])([A-Z]{1,6}-\d{2,6}[A-Z]?(?:/[A-Z])*(?:\.\d{1,3})?)(?![\w\-])"
)
_SHAPE = re.compile(r"^([A-Z]+)-(\d+)([A-Z]?)(\.\d+)?$")


def expand(token: str) -> list[str]:
    """``P-4102A/B`` -> ``P-4102A``, ``P-4102B``; any other token -> itself."""
    head, *more = token.split("/")
    if not more or len(head) < 2 or not head[-1].isalpha():
        return [token] if not more else [head]
    return [head, *(head[:-1] + m for m in more)]


def shape(tag: str) -> tuple[str, int] | None:
    """``("P", 4)`` for ``P-4102A``: the letters and the number of digits."""
    match = _SHAPE.match(tag)
    return (match.group(1), len(match.group(2))) if match else None


def instrument_loop(tag: str) -> tuple[str, str] | None:
    """``("L", "4108")`` for ``LIA-4108`` or ``LALL-4108``: measured variable and loop number.

    None for tags that are not instrument functions: one letter (equipment, ``P-4102A``) or
    letters ending in V (a valve, ``PV-4112``, ``PSV-3114``).
    """
    match = _SHAPE.match(tag)
    if match is None:
        return None
    letters = match.group(1)
    if len(letters) < 2 or letters.endswith("V"):
        return None
    return letters[0], match.group(2) + match.group(3) + (match.group(4) or "")


# ---------------------------------------------------------------------------
# What the repository names
# ---------------------------------------------------------------------------


@dataclass
class _Sheet:
    name: str
    sheet_id: str
    root: etree._Element
    by_id: dict[str, etree._Element]
    #: LineNumber -> PipingNetworkSystem elements.
    lines: dict[str, list[etree._Element]] = field(default_factory=dict)


@dataclass
class Known:
    """Every tag the lists and sheets have, by kind."""

    #: tag -> what it is (``equipment``, ``line``, ``instrument``, ``valve``, ...).
    tags: dict[str, str] = field(default_factory=dict)
    sheets: set[str] = field(default_factory=set)

    def add(self, tag: str | None, kind: str) -> None:
        tag = (tag or "").strip()
        if tag:
            self.tags.setdefault(tag, kind)

    def shapes(self) -> set[tuple[str, int]]:
        return {s for t in [*self.tags, *self.sheets] if (s := shape(t))}

    def loops(self) -> set[tuple[str, str]]:
        return {
            loop
            for t, kind in self.tags.items()
            if kind == "instrument" and (loop := instrument_loop(t))
        }

    def resolve(self, token: str) -> str | None:
        """What *token* names (``equipment``, ``sheet``, ``instrument loop``...) or None."""
        if token in self.sheets:
            return "sheet"
        if token in self.tags:
            return self.tags[token]
        loop = instrument_loop(token)
        if loop is not None and loop in self.loops():
            return "instrument loop"
        return None


def _kind(element: etree._Element) -> str:
    kind = element.get("type", "")
    short = kind.rsplit(".", 1)[-1]
    if kind.startswith(("Plant/ProcessEquipment.", "Plant/Equipment")):
        return "equipment"
    if short == "PipingNetworkSystem":
        return "line"
    if short == "ProcessInstrumentationFunction":
        return "instrument"
    if "Valve" in short:
        return "valve"
    if short == "ActuatingSystem":
        return "valve"
    return short[:1].lower() + short[1:]


def _load(path: Path, name: str, sheet_id: str) -> _Sheet | None:
    try:
        root = etree.parse(
            str(path), etree.XMLParser(resolve_entities=False, no_network=True)
        ).getroot()
    except (OSError, etree.XMLSyntaxError):
        return None
    sheet = _Sheet(name, sheet_id, root, {})
    from chemeascode.domains.piping.show import data_value

    for element in root.iter("Object"):
        if element.get("id"):
            sheet.by_id.setdefault(element.get("id"), element)
        if element.get("type", "").endswith("PipingNetworkSystem"):
            number = (data_value(element, "LineNumber") or "").strip()
            if number:
                sheet.lines.setdefault(number, []).append(element)
    return sheet


def _sheet_tags(sheet: _Sheet, known: Known) -> None:
    from chemeascode.domains.piping.show import TAG_PROPERTIES, data_value, instrument_tag

    for element in sheet.root.iter("Object"):
        kind = _kind(element)
        known.add(instrument_tag(element), "instrument")
        for prop in TAG_PROPERTIES[:5]:
            known.add(data_value(element, prop), "line" if prop == "LineNumber" else kind)


def _list_tags(parsed: dict[str, Any], known: Known) -> None:
    for item in getattr(parsed.get("equipment"), "equipment", None) or ():
        known.add(item.tag, "equipment")
    for line in getattr(parsed.get("lines"), "lines", None) or ():
        known.add(line.number, "line")
    for item in getattr(parsed.get("instruments"), "instruments", None) or ():
        known.add(item.tag, "instrument")


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


def _line_of(element: etree._Element) -> str | None:
    from chemeascode.domains.piping.show import data_value

    for holder in element.iterancestors("Object"):
        if holder.get("type", "").endswith("PipingNetworkSystem"):
            return (data_value(holder, "LineNumber") or "").strip() or None
    return None


def _number(tag: str) -> str | None:
    match = _SHAPE.match(tag)
    return match.group(2) + match.group(3) if match else None


def _items_of(system: etree._Element) -> set[str]:
    """Ids of the items and nodes in the segments of *system*."""
    found: set[str] = set()
    for segment in system.iter("Object"):
        if not segment.get("type", "").endswith("PipingNetworkSegment"):
            continue
        for item in segment.findall("Components[@property='Items']/Object"):
            if item.get("id"):
                found.add(item.get("id"))
            for node in item.iter("Object"):
                if node.get("id"):
                    found.add(node.get("id"))
    return found


def _joined(sheet: _Sheet, line: str, other: str) -> bool:
    """Whether a segment of *line* on *sheet* ends at an item of *other* (or the reverse)."""
    if line not in sheet.lines or other not in sheet.lines:
        return False
    for a, b in ((line, other), (other, line)):
        items = set().union(*(_items_of(s) for s in sheet.lines[b]))
        for system in sheet.lines[a]:
            for reference in system.iter("References"):
                if reference.get("property") not in (
                    "SourceItem",
                    "TargetItem",
                    "SourceNode",
                    "TargetNode",
                ):
                    continue
                targets = {t.lstrip("#") for t in reference.get("objects", "").split()}
                if targets & items:
                    return True
    return False


def cross_check_tags(
    sheets: list[tuple[Path, str, str]], parsed: dict[str, Any], sheet_ids: Iterable[str]
) -> list[Any]:
    """``label-tag-unknown``, ``offpage-mismatch`` and ``label-tag`` findings.

    *sheets*: (path, repository-relative name, sheet id) of every sheet; *parsed*: the lists
    that passed their schema; *sheet_ids*: every sheet plant.yaml declares.
    """
    from chemeascode.domains.piping.drawing import literal_texts
    from chemeascode.domains.piping.sheet_index import _drawn_for
    from chemeascode.foundation.findings import Finding

    loaded = [s for path, name, sid in sheets if (s := _load(path, name, sid))]
    known = Known(sheets={s.strip() for s in sheet_ids if s})
    _list_tags(parsed, known)
    for sheet in loaded:
        _sheet_tags(sheet, known)
    shapes = known.shapes()
    loops = known.loops()
    by_sheet_id = {s.sheet_id: s for s in loaded}
    findings: list[Finding] = []
    for sheet in loaded:
        lines = {
            (round(float(x), 6), round(float(y), 6), text): text_element
            for text_element, text, x, y in _texts(sheet.root)
        }
        for content, x, y, tokens in literal_texts(sheet.root):
            element = lines.get((x, y, content))
            line_no = element.sourceline if element is not None else None
            owner = _drawn_for(element) if element is not None else None
            resolved: list[str] = []
            for token in dict.fromkeys(tokens):
                kind = known.resolve(token)
                if kind is not None:
                    resolved.append(f"{token} ({kind})")
                    continue
                token_shape = shape(token)
                loop = instrument_loop(token)
                if token_shape not in shapes and not (
                    loop and any(loop[0] == first for first, _ in loops)
                ):
                    continue  # not tag-like here: no known tag has its shape
                what = (
                    "sheet"
                    if token_shape in {shape(s) for s in known.sheets}
                    and token_shape not in {shape(t) for t in known.tags}
                    else "tag"
                )
                findings.append(
                    Finding(
                        sheet.name,
                        "warning",
                        "cheme.label-tag-unknown",
                        f"the text {content!r} names {what} {token}, which "
                        + (
                            "plant.yaml does not declare"
                            if what == "sheet"
                            else "no list and no sheet has"
                        ),
                        line=line_no,
                        ids=[i for i in (owner, token) if i],
                        hint="correct the tag in the text; a note that names an external tag "
                        "can be accepted with a reason in checks/checks.yaml (accept:)",
                        key=f"{owner or ''}:{token}",
                    )
                )
            if resolved:
                findings.append(
                    Finding(
                        sheet.name,
                        "info",
                        "cheme.label-tag",
                        f"the text {content!r} names " + ", ".join(resolved),
                        line=line_no,
                        ids=[owner] if owner else [],
                        hint="no template follows these names: change the text with them",
                        key=f"{owner or ''}:{content[:40]}",
                    )
                )
            if element is not None and owner and owner in sheet.by_id:
                findings += _offpage(
                    sheet, sheet.by_id[owner], content, tokens, known, by_sheet_id, line_no
                )
    return findings


def _texts(root: etree._Element) -> Iterable[tuple[etree._Element, str, str, str]]:
    from chemeascode.domains.piping.sheet_index import _POSITION

    for text in root.iter("Object"):
        if text.get("type") != "Core/Diagram.Text":
            continue
        cached = text.find("Data[@property='Text']/String")
        x, y = text.find(_POSITION.format("X")), text.find(_POSITION.format("Y"))
        if cached is None or x is None or y is None:
            continue
        try:
            float(x.text or ""), float(y.text or "")
        except ValueError:
            continue
        yield cached, (cached.text or "").strip(), x.text or "", y.text or ""


def _offpage(
    sheet: _Sheet,
    connector: etree._Element,
    content: str,
    tokens: list[str],
    known: Known,
    by_sheet_id: dict[str, _Sheet],
    line_no: int | None,
) -> list[Any]:
    """``offpage-mismatch`` for one literal text of an off-page connector."""
    from chemeascode.foundation.findings import Finding

    if "OffPageConnector" not in connector.get("type", ""):
        return []
    line = _line_of(connector)
    if not line:
        return []
    connector_id = connector.get("id", "")
    named_lines = [t for t in tokens if known.tags.get(t) == "line"]
    named_sheets = [
        t for t in tokens if t in known.sheets and t != sheet.sheet_id and t in by_sheet_id
    ]
    problems: list[str] = []
    if named_lines and line not in named_lines:
        for other in named_lines:
            if _number(other) == _number(line):
                problems.append(
                    f"it names line {other}, but the connector is on line {line} (same number, "
                    "another code)"
                )
                continue
            where = [by_sheet_id[s] for s in named_sheets] or [sheet]
            places = ", ".join(w.sheet_id or w.name for w in where)
            if not any(other in w.lines for w in where):
                problems.append(
                    f"it names line {other}, which is not on {places}; the connector is on "
                    f"line {line}"
                )
            elif not any(_joined(w, line, other) for w in where):
                problems.append(
                    f"it names line {other}, which line {line} does not join on {places}"
                )
    for named in named_sheets:
        if line not in by_sheet_id[named].lines:
            problems.append(f"it names sheet {named}, which does not carry line {line}")
    return [
        Finding(
            sheet.name,
            "warning",
            "cheme.offpage-mismatch",
            f"off-page connector {connector_id} on line {line}: the text {content!r}: {problem}",
            line=line_no,
            ids=[connector_id, line],
            hint=f"name line {line} and the sheet that continues it in the text",
            key=f"{connector_id}:{content[:40]}",
        )
        for problem in problems
    ]
