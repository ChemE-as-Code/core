"""Validation of a plant repository: P&IDs, YAML lists, and the two against each other.

Every finding names a file, a line where one is known, a rule and a hint, so an agent can go
straight to the place and fix it. A P&ID is checked in layers, each only once the one before
passed:

1. the XML is well-formed;
2. pyDEXPI loads it as DEXPI 2.0.1, and reports what it could not represent;
3. pyDEXPI's validation rules run on the model (its two rules on segment ends are reported as
   one ``cheme.segment-ends`` finding per segment);
4. cheme-as-code's own rules run on the document: unique ids, an id on every object, every plant
   item drawn;
5. cheme-as-code's rules on the loaded model: the pipes join nodes of one DN, and labels show what
   their templates render.

A YAML list is parsed and checked against its schema, then the tags it names are compared with
the tags the P&IDs hold: equipment tags and classes, line numbers and DNs, printed instrument
tags.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from lxml import etree
from pydantic import ValidationError

from chemeascode.domains.piping.sheet_index import (  # noqa: F401 (also imported from here)
    _POSITION,
    _UNIT_SPELLINGS,
    SheetIndex,
    _drawn_for,
    _id_lines,
    _index,
)
from chemeascode.foundation.acceptance import (  # noqa: F401 (also imported from here)
    _check_list,
    accept_matches,
    acceptance,
    accepted_entries,
    stale_quote,
)
from chemeascode.foundation.findings import _SEVERITY, Finding, Level
from chemeascode.foundation.workspace import LIST_FILES, Workspace, schema_hint
from chemeascode.foundation.yamlsource import (  # also imported from here
    _compose,
    _duplicates,
    _entries,
    _Entry,
    _yaml_line,
    syntax_finding,
)
from chemeascode.integrations.pydexpi import _LOADER_LEVELS, _RULE_LEVELS
from chemeascode.schemas import LIST_SCHEMAS

#: Conceptual classes a P&ID is expected to draw: an item of one of these that no
#: RepresentationGroup represents is invisible on the sheet.
_DRAWN_PREFIXES = (
    "Plant/ProcessEquipment.",
    "Plant/Piping.PipingNetworkSystem",
    "Plant/Instrumentation.ProcessInstrumentationFunction",
)
#: Classes under those prefixes that are parts of an item rather than items.
_UNDRAWN_PARTS = ("Chamber", "Nozzle", "Impeller", "TubeBundle", "Agitator", "Displacer")


@dataclass
class Report:
    """Every finding of one run, and what it covered."""

    findings: list[Finding] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    #: What was compared: ``sheets`` (loaded), ``not_loaded`` (sheets missing or failing to
    #: load), ``planned`` (sheet ids planned and not drawn yet),
    #: ``lists`` (kinds), ``cross_checks`` run and ``skipped`` (cross-checks, or parts of them,
    #: not run, each with the reason).
    compared: dict[str, list[str]] = field(
        default_factory=lambda: {
            "sheets": [],
            "not_loaded": [],
            "planned": [],
            "lists": [],
            "cross_checks": [],
            "skipped": [],
        }
    )
    #: The generated BFD/PFD sheets among ``compared["sheets"]``.
    process_sheets: list[str] = field(default_factory=list)

    def compared_line(self) -> str:
        """One line naming the sheets, lists and cross-checks this run covered."""
        sheets = self.compared["sheets"]
        lists = self.compared["lists"]
        parts = [
            f"{len(sheets)} sheet(s)"
            + (f" ({', '.join(sheets)})" if sheets else "")
            + (
                f", not loaded: {', '.join(self.compared['not_loaded'])}"
                if self.compared["not_loaded"]
                else ""
            )
            + (
                f", planned: {', '.join(self.compared['planned'])}"
                if self.compared.get("planned")
                else ""
            ),
            f"{len(lists)} list(s)" + (f" ({', '.join(lists)})" if lists else ""),
            "cross-checks: " + (", ".join(self.compared["cross_checks"]) or "none"),
        ]
        if self.compared["skipped"]:
            parts.append("skipped: " + ", ".join(self.compared["skipped"]))
        return "compared: " + "; ".join(parts)

    def filter_rules(self, ignore: Iterable[str] = (), only: Iterable[str] = ()) -> Report:
        """Drop the findings of the rules in *ignore*, or keep only those in *only*.

        Each entry is a rule id or a glob (``cheme.*-not-on-pid``), or several separated by
        commas, matched as a ``kind: validate`` gate's ``rules`` are (``cheme.generator-failed``
        goes with ``cheme.generated-sheet-drift``). Changes this report in place and returns it.
        """
        from chemeascode.foundation.findings import rule_matches

        def split(patterns: Iterable[str]) -> list[str]:
            return [p.strip() for group in patterns for p in group.split(",") if p.strip()]

        ignored, kept = split(ignore), split(only)
        self.findings = [
            f
            for f in self.findings
            if not any(rule_matches(f.rule, p) for p in ignored)
            and (not kept or any(rule_matches(f.rule, p) for p in kept))
        ]
        return self

    def drawing_lines(self) -> list[str]:
        """Per sheet checked, the count of each drawing-geometry finding (accepted apart)."""
        from chemeascode.domains.piping.drawing import RULES

        lines = []
        for sheet in self.compared["sheets"]:
            if sheet in self.process_sheets:  # no P&ID drawing lint on a BFD or PFD
                continue
            found = [f for f in self.findings if f.file == sheet and f.rule in RULES]
            if any(f.rule == "cheme.drawing-not-checked" for f in self.findings if f.file == sheet):
                continue
            parts = []
            for rule in RULES:
                of_rule = [f for f in found if f.rule == rule]
                accepted = sum(f.accepted is not None for f in of_rule)
                part = f"{len(of_rule) - accepted} {rule.removeprefix('cheme.')}"
                parts.append(part + (f" (+{accepted} accepted)" if accepted else ""))
            lines.append(f"drawing {sheet}: " + ", ".join(parts))
        return lines

    def failed(self, fail_on: Level = "error") -> bool:
        """Whether any finding is at *fail_on* or above."""
        return any(_SEVERITY[f.level] >= _SEVERITY[fail_on] for f in self.findings)

    def to_json(self) -> str:
        return json.dumps(
            {
                "files": self.files,
                "compared": self.compared,
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
            },
            indent=2,
        )


# ---------------------------------------------------------------------------
# P&IDs
# ---------------------------------------------------------------------------


def _document_rules(name: str, root: etree._Element) -> list[Finding]:
    """cheme-as-code's rules on the XML itself, which the model no longer shows."""
    findings: list[Finding] = []

    seen: dict[str, int] = {}
    for element in root.iter():
        element_id = element.get("id") if isinstance(element.tag, str) else None
        if element_id is None:
            continue
        if element_id in seen:
            findings.append(
                Finding(
                    name,
                    "error",
                    "cheme.duplicate-id",
                    f"id {element_id!r} is used twice (first on line {seen[element_id]})",
                    line=element.sourceline,
                    ids=[element_id],
                    hint="every id in a document must be unique; rename one and its references",
                )
            )
        else:
            seen[element_id] = element.sourceline or 0

    missing = [e for e in root.iter("Object") if e.get("id") is None]
    if missing:
        findings.append(
            Finding(
                name,
                "warning",
                "cheme.object-without-id",
                f"{len(missing)} object(s) have no id; pyDEXPI mints a new one on every load, "
                "so their diffs are not stable",
                line=missing[0].sourceline,
                hint="run `cheme fmt` to give each a readable id",
            )
        )

    for imported in root.iterchildren("Import"):
        source = imported.get("source", "")
        if "/models/" in source and "/models/2.0.1/" not in source:
            findings.append(
                Finding(
                    name,
                    "warning",
                    "cheme.dexpi-version",
                    f"imports {source}; this repository keeps DEXPI 2.0.1",
                    line=imported.sourceline,
                    hint="`cheme fmt` converts the document to 2.0.1",
                )
            )
            break

    represented = {
        target.lstrip("#")
        for reference in root.iter("References")
        if reference.get("property") == "Represents"
        for target in reference.get("objects", "").split()
    }
    if root.find(".//Components[@property='Diagram']") is not None:
        for element in root.iter("Object"):
            kind = element.get("type", "")
            element_id = element.get("id")
            if (
                element_id
                and kind.startswith(_DRAWN_PREFIXES)
                and not kind.rsplit(".", 1)[-1].endswith(_UNDRAWN_PARTS)
                and element_id not in represented
            ):
                findings.append(
                    Finding(
                        name,
                        "warning",
                        "cheme.not-drawn",
                        f"{kind.rsplit('.', 1)[-1]} {element_id!r} is in the model but no "
                        "RepresentationGroup represents it, so it is not on the sheet",
                        line=element.sourceline,
                        ids=[element_id],
                        hint="add a RepresentationGroup with References Represents to it "
                        "(see the dexpi-xml skill)",
                    )
                )
    return findings


#: Every "DN <n>" in a text, with "/<n>" continuations ("DN = 25/50", "DN25/DN50", "DN 25 x DN 50").
_DN_IN_TEXT = re.compile(r"\bDN\s*=?\s*(\d+(?:\s*/\s*\d+)*)", re.IGNORECASE)
_BARE_NUMBERS = re.compile(r"^\s*\d+(?:\s*/\s*\d+)*\s*$")
_QUANTITY_IN_TEXT = re.compile(r"(-?\d+(?:[.,]\d+)?)\s*([A-Za-z°][A-Za-z0-9°/^()\-]*)")
#: The metric DN series (EN ISO 6708); a bare number outside it is not read as a DN.
_DN_SERIES = frozenset(
    (6, 8, 10, 15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150, 175, 200, 250, 300, 350, 400)
    + (450, 500, 600, 700, 800, 900, 1000, 1100, 1200, 1400, 1500, 1600, 1800, 2000)
)


def _unit_token(unit: str) -> str:
    """*unit* without trailing punctuation that closes the text around it ("(6 barg)")."""
    while unit and unit[-1] in ")],;:." and not unit.endswith(("(g)", "(a)")):
        unit = unit[:-1]
    return unit


def _data_text(element: etree._Element, prop: str) -> str | None:
    value = element.find(f"Data[@property='{prop}']/*")
    if value is None:
        return None
    return value.get("data") if value.tag == "DataReference" else (value.text or "").strip()


def _object_dns(element: etree._Element) -> list[float]:
    """The numerical DNs of *element* and its nodes (a valve's two ports, a nozzle's one)."""
    found: list[float] = []
    for holder in (element, *element.findall("Components[@property='Nodes']/Object")):
        for prop in (
            "NominalDiameterNumericalValueRepresentation",
            "NominalDiameterRepresentation",
        ):
            number = _number(_data_text(holder, prop))
            if number is not None:
                found.append(number)
                break
    return list(dict.fromkeys(found))


def _quantities(element: etree._Element) -> list[tuple[str, float, str]]:
    """``(attribute, value, unit)`` of each physical quantity *element* holds directly."""
    found = []
    for data in element.findall("Data"):
        quantity = data.find(
            "AggregatedDataValue[@type='Core/PhysicalQuantities.PhysicalQuantity']"
        )
        if quantity is None:
            continue
        value = _number(_data_text(quantity, "Value"))
        unit = (_data_text(quantity, "Unit") or "").rsplit(".", 1)[-1]
        if value is not None and unit:
            found.append((data.get("property", ""), value, unit))
    return found


def _literal_label_values(
    text: str, element: etree._Element
) -> tuple[list[str], list[str], list[str]]:
    """What a literal *text* repeats of *element*'s data, contradicts, and may contradict.

    The last list holds bare numbers that differ from the DN data but may not be a DN at all.
    """
    same: list[str] = []
    wrong: list[str] = []
    unsure: list[str] = []
    dns = _object_dns(element)
    said = [n for group in _DN_IN_TEXT.findall(text) for n in re.findall(r"\d+", group)]
    bare = not said and bool(_BARE_NUMBERS.match(text))
    if bare:
        said = re.findall(r"\d+", text)
    if said and dns:
        shown = {float(n) for n in said}
        have = "/".join(f"DN{d:g}" for d in sorted(dns))
        if shown <= set(dns):
            same.append(have)
        elif not bare:
            wrong.append(f"DN {'/'.join(said)}, but the data says {have}")
        elif shown <= _DN_SERIES:
            # A bare number may be a nozzle number or a count rather than a size: info only.
            unsure.append(f"DN {'/'.join(said)}, but the data says {have}")
    quantities = _quantities(element)
    for number, unit in _QUANTITY_IN_TEXT.findall(text):
        unit = _unit_token(unit)
        spelt = unit.lower().replace("³", "3").replace("²", "2")
        kinds = [k for k, spellings in _UNIT_SPELLINGS.items() if spelt in spellings]
        candidates = [q for q in quantities if q[2] in kinds]
        if not candidates:
            continue
        value = float(number.replace(",", "."))
        equal = [q for q in candidates if abs(q[1] - value) < 1e-9]
        if equal:
            same.append(f"{equal[0][0]} {number} {unit}")
        else:
            data = ", ".join(f"{q[0]} = {q[1]:g} {q[2]}" for q in candidates)
            wrong.append(f"{number} {unit}, but the data says {data}")
    for data in element.findall("Data"):
        value = data.find("String")
        word = (value.text or "").strip() if value is not None else ""
        if len(word) >= 2 and re.search(rf"(?<![\w.]){re.escape(word)}(?![\w])", text):
            same.append(f"{data.get('property')} {word}")
    return same, wrong, unsure


def _label_literal_rules(name: str, root: etree._Element) -> list[Finding]:
    """Drawn texts made of literal text only that repeat, or contradict, the object's data.

    No template ties them to an attribute, so ``cheme.label-stale`` cannot follow them.
    """
    by_id = {e.get("id"): e for e in root.iter("Object") if e.get("id")}
    containers = {
        target
        for element in root.iter("Object")
        if element.get("type", "").endswith("Diagram.Diagram")
        for target in [_drawn_for(element)]
        if target
    }
    findings: list[Finding] = []
    for text in root.iter("Object"):
        if text.get("type") != "Core/Diagram.Text":
            continue
        fragments = text.findall("Components[@property='Template']/Object/Components/Object")
        if any(f.get("type") != "Core/Diagram.LiteralText" for f in fragments):
            continue
        cached = text.find("Data[@property='Text']/String")
        content = (cached.text or "").strip() if cached is not None else ""
        target = _drawn_for(text)
        if not content or target is None or target in containers or target not in by_id:
            continue
        element = by_id[target]
        same, wrong, unsure = _literal_label_values(content, element)
        if not same and not wrong and not unsure:
            continue
        kind = element.get("type", "").rsplit(".", 1)[-1]
        line = cached.sourceline if cached is not None else text.sourceline
        if wrong:
            level: Level = "warning"
            message = f"literal label {content!r} of {kind} {target} says " + "; ".join(wrong)
            hint = "correct the text, or show the attribute through an AttributeRepresentation"
        elif unsure:
            level = "info"
            message = (
                f"literal label {content!r} of {kind} {target}, if it is a size, says "
                + "; ".join(unsure)
            )
            hint = "a nozzle number or count needs no change; a size should match the data"
        else:
            level = "info"
            message = f"literal label {content!r} of {kind} {target} repeats " + ", ".join(same)
            hint = "no check follows a literal: change it with the data"
        findings.append(
            Finding(
                name,
                level,
                "cheme.label-literal",
                message,
                line=line,
                ids=[target],
                hint=hint,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Model rules
# ---------------------------------------------------------------------------


def _ref(obj: Any) -> str:
    return getattr(obj, "id", None) or "none"


def _end(item: Any, node: Any) -> str:
    return f"{_ref(item)}/{_ref(node)}"


def _segments(model: Any) -> Iterator[tuple[Any, Any]]:
    """Every (PipingNetworkSystem, PipingNetworkSegment) of the model."""
    for system in getattr(model.conceptualModel, "pipingNetworkSystems", None) or ():
        for segment in system.segments or ():
            yield system, segment


#: pyDEXPI's Mandatory rules on where a segment starts and ends. Both read the segment's ends
#: from its connections, not their list order (DEXPI 2.0.1 does not order them), and accept the
#: reference P&ID's segments that end at the outlet of a valve or the branch of a tee. cheme-as-code
#: reports what they find on one segment as one ``cheme.segment-ends`` finding.
_SEGMENT_END_RULES = (
    "pydexpi_segment_connectivity",
    "pydexpi_segment_reference_nodes_and_items_match",
)


def _segment_end_findings(index: SheetIndex, model: Any, issues: list[Any]) -> list[Finding]:
    """One ``cheme.segment-ends`` finding per segment that *issues* (pyDEXPI's) report."""
    segments = {segment.id: segment for _, segment in _segments(model)}
    by_segment: dict[str, list[Any]] = {}
    for issue in issues:
        by_segment.setdefault(issue.affected_component_ids[0], []).append(issue)
    findings: list[Finding] = []
    for segment_id, found in by_segment.items():
        segment = segments.get(segment_id)
        text = " ".join(f"{i.short_description} {i.long_description}" for i in found).lower()
        sides = [side for side in ("Source", "Target") if side.lower() in text] or ["Source"]
        line = next(
            (
                index.references[(segment_id, f"{side}{part}")]
                for side in sides
                for part in ("Node", "Item")
                if (segment_id, f"{side}{part}") in index.references
            ),
            None,
        )
        ends = ", ".join(
            f"{side}Item/{side}Node "
            + _end(
                getattr(segment, f"{side.lower()}Item", None),
                getattr(segment, f"{side.lower()}Node", None),
            )
            for side in sides
        )
        rules = ", ".join(dict.fromkeys(i.applied_rule_id for i in found))
        where = " and ".join(
            f"its pipes {'start' if side == 'Source' else 'end'}" for side in sides
        )
        findings.append(
            Finding(
                index.name,
                "error",
                "cheme.segment-ends",
                f"segment {segment_id} has {ends}, which is not where {where}: "
                + " ".join(dict.fromkeys(i.long_description for i in found))
                + f" (pyDEXPI: {rules})",
                line=line or index.line(segment_id),
                ids=[segment_id],
                hint=f"point the segment's {' and '.join(sides)}Item/Node References at the item "
                f"and node where {where} (the outlet of its own end valve or the branch of its "
                "own tee is fine); the node must be one of that item's",
            )
        )
    return findings


def _dn(node: Any) -> float | None:
    """The numerical DN of a piping node (or segment, system), when it has one."""
    if node is None:
        return None
    for value in (
        getattr(node, "nominalDiameterNumericalValueRepresentation", None),
        getattr(node, "nominalDiameterRepresentation", None),
    ):
        number = _number(value)
        if number is not None:
            return number
    return None


def _number(value: Any) -> float | None:
    """The first number in *value* (``80``, ``"80"``, ``"DN 80"``, ``"DN80"``), or None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(match.group().replace(",", ".")) if match else None


def _dn_text(number: float) -> str:
    return f"DN{number:g}"


def _dn_rules(index: SheetIndex, model: Any) -> list[Finding]:
    """Pipes joining nodes of different DN.

    A reducer changes the DN between its own two nodes, inside the item, which no pipe joins: a
    pipe from a reducer port to a node of another DN is as wrong as any other, so reducers are
    not exempt.
    """
    findings: list[Finding] = []
    for _, segment in _segments(model):
        for pipe in segment.connections or ():
            source, target = _dn(pipe.sourceNode), _dn(pipe.targetNode)
            if source is None or target is None or source == target:
                continue
            findings.append(
                Finding(
                    index.name,
                    "warning",
                    "cheme.dn-mismatch",
                    f"{type(pipe).__name__} {_ref(pipe)} joins "
                    f"{_end(pipe.sourceItem, pipe.sourceNode)} ({_dn_text(source)}) to "
                    f"{_end(pipe.targetItem, pipe.targetNode)} ({_dn_text(target)})",
                    line=index.line(pipe, segment),
                    ids=[
                        i
                        for i in (_ref(pipe), _ref(pipe.sourceNode), _ref(pipe.targetNode))
                        if i != "none"
                    ],  # fmt: skip
                    hint="give both nodes the same NominalDiameter, or put a reducer between them",
                )
            )
    return findings


def _label_rules(index: SheetIndex, model: Any) -> list[Finding]:
    """Texts whose template, rendered from the model now, no longer gives their cached text."""
    from pydexpi.pydexpi_classes.core.diagram import AttributeRepresentation, LiteralText
    from pydexpi.toolkits.label_toolkit import iter_texts, render_text_template

    findings: list[Finding] = []
    for text in iter_texts(model.diagram):
        template = text.template
        fragments = list(getattr(template, "fragments", None) or ())
        shown = [f for f in fragments if isinstance(f, AttributeRepresentation)]
        if not shown:
            continue
        rendered = render_text_template(template)
        cached = text.text or ""
        if rendered is None:
            findings += _unrenderable(index, text, shown)
            continue
        if rendered == cached:
            continue
        if isinstance(fragments[-1], LiteralText) and cached.startswith(rendered):
            # A template that stops short of its text: the DEXPI reference P&ID labels valves
            # "66KL21-80" from a template of PipingComponentName and "-" only. The text agrees
            # with everything the template shows.
            continue
        sources = ", ".join(f"{_ref(f.object)}.{f.attributeName}" for f in shown)
        objects = list(dict.fromkeys(_ref(f.object) for f in shown if f.object is not None))
        findings.append(
            Finding(
                index.name,
                "warning",
                "cheme.label-stale",
                f"label text {cached!r} is out of date: its template ({sources}) renders "
                f"{rendered!r}",
                line=_text_line(index, text, *objects),
                ids=objects,
                hint=f'set the Text\'s cached <Data property="Text"> to {rendered!r}, or fix the '
                "attribute it shows",
            )
        )
    return findings


def _text_line(index: SheetIndex, text: Any, *objects: Any) -> int | None:
    position = text.position
    key = (
        text.text or "",
        round(float(getattr(position, "x", 0.0) or 0.0), 6),
        round(float(getattr(position, "y", 0.0) or 0.0), 6),
    )
    return index.texts.get(key) or index.line(text, *objects)


def _unrenderable(index: SheetIndex, text: Any, shown: list[Any]) -> list[Finding]:
    """A label whose template pyDEXPI cannot render: say which attribute fragment is why."""
    from pydexpi.toolkits.label_toolkit import resolve_attribute_field, split_attribute_name

    reasons = []
    for fragment in shown:
        obj, name = fragment.object, fragment.attributeName
        if obj is None:
            reasons.append(f"an AttributeRepresentation of {name!r} references no object")
            continue
        split = split_attribute_name(name or "")
        if split is None:
            reasons.append(f"attribute name {name!r} cannot be read")
        elif resolve_attribute_field(obj, split[0]) is None:
            reasons.append(f"{_ref(obj)}.{name} is not an attribute of {type(obj).__name__}")
    if not reasons:
        reasons.append("a fragment's value has no text rendering")
    objects = list(dict.fromkeys(_ref(f.object) for f in shown if f.object is not None))
    return [
        Finding(
            index.name,
            "warning",
            "cheme.label-stale",
            f"label text {text.text or ''!r}: its template cannot be rendered: "
            + "; ".join(reasons),
            line=_text_line(index, text, *objects),
            ids=objects,
            hint="fix the AttributeName (the attribute's DEXPI name, e.g. TagName) or the "
            "Object it references",
        )
    ]


def _model_rules(index: SheetIndex, model: Any) -> list[Finding]:
    """cheme-as-code's rules on the loaded model."""
    return _dn_rules(index, model) + _label_rules(index, model)


def validate_pid(path: Path, name: str | None = None) -> tuple[list[Finding], Any]:
    """Findings for one P&ID, and the loaded model (``None`` when it could not be loaded)."""
    findings, model, _ = _validate_pid(path, name)
    return findings, model


def _validate_pid(
    path: Path, name: str | None = None
) -> tuple[list[Finding], Any, SheetIndex | None]:
    from pydexpi.loaders.compat import ConversionRefusedError
    from pydexpi.validation import validate

    from chemeascode.domains.piping import dexpi_io

    name = name or str(path)
    content = path.read_bytes()
    try:
        root = etree.fromstring(content, etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as failure:
        line, _ = failure.position
        return (
            [
                Finding(
                    name,
                    "error",
                    "xml.syntax",
                    f"not well-formed XML: {failure.msg}",
                    line=line,
                    hint="fix the XML before anything else can be checked",
                )
            ],
            None,
            None,
        )

    from chemeascode.domains.piping.sheets import read_title_block, template_findings

    findings = _document_rules(name, root) + _label_literal_rules(name, root)
    index = _index(name, root)
    index.title_block = read_title_block(root)
    findings += template_findings(name, index.title_block)
    id_lines = index.ids

    try:
        loaded = dexpi_io.load(content, strict=True)
    except (ConversionRefusedError, ValueError) as failure:
        findings.append(
            Finding(name, "error", "dexpi.load", f"pyDEXPI could not load it: {failure}")
        )
        return findings, None, index

    for entry in loaded.errors:
        level = _LOADER_LEVELS.get(str(entry.level), "warning")
        if level == "info":
            continue
        ids = [entry.object_id] if entry.object_id else []
        if entry.object_id and entry.line:
            id_lines.setdefault(entry.object_id, entry.line)
        findings.append(
            Finding(
                name,
                level,
                "dexpi.load",
                entry.message,
                line=entry.line,
                ids=ids,
                hint="the loader dropped or defaulted this; the model does not hold it"
                if level == "error"
                else "",
            )
        )

    issues = list(validate(loaded.model))
    segment_end_issues = [
        i for i in issues if i.applied_rule_id in _SEGMENT_END_RULES and i.affected_component_ids
    ]
    findings += _segment_end_findings(index, loaded.model, segment_end_issues)
    merged = {id(i) for i in segment_end_issues}
    for issue in issues:
        if id(issue) in merged:
            continue
        lines = [id_lines[i] for i in issue.affected_component_ids if i in id_lines]
        findings.append(
            Finding(
                name,
                _RULE_LEVELS.get(issue.level_of_recommendation.value, "warning"),
                issue.applied_rule_id,
                issue.short_description,
                line=lines[0] if lines else None,
                ids=list(issue.affected_component_ids),
                hint=issue.long_description
                if issue.long_description != issue.short_description
                else "",
            )
        )
    findings += _model_rules(index, loaded.model)
    findings += _drawing_rules(index, root, loaded.model)
    return findings, loaded.model, index


def _drawing_rules(index: SheetIndex, root: etree._Element, model: Any) -> list[Finding]:
    """The drawing-geometry rules (``domains.piping.drawing``) on the sheet as the export draws
    it."""
    from chemeascode.domains.piping.drawing import crop_text, lint_model
    from chemeascode.domains.piping.render import NothingToDraw

    try:
        found, drawing = lint_model(model, root)
    except NothingToDraw:
        return []
    except Exception as failure:  # noqa: BLE001 - an export failure must not stop validation
        return [
            Finding(
                index.name,
                "info",
                "cheme.drawing-not-checked",
                f"the drawing rules did not run: the SVG export failed ({failure})",
                hint="`cheme render` this sheet to see the failure",
            )
        ]
    findings = []
    for item in found:
        line = None
        if item.text is not None:
            line = index.texts.get((item.text.text, round(item.text.x, 6), round(item.text.y, 6)))
        findings.append(
            Finding(
                index.name,
                item.level,  # type: ignore[arg-type]
                item.rule,
                item.message,
                line=line or index.line(*item.ids),
                ids=item.ids,
                hint=item.hint,
                key=item.key,
                box=[round(v, 2) for v in item.box],
                crop=crop_text(item.crop(drawing.box)),
            )
        )
    return findings


# ---------------------------------------------------------------------------
# YAML lists
# ---------------------------------------------------------------------------


def validate_list(path: Path, kind: str, name: str) -> tuple[list[Finding], Any]:
    """Findings for one YAML list, and the parsed model (``None`` when it is invalid)."""
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except UnicodeDecodeError as failure:
        message = f"cannot be read as UTF-8 text: {failure}"
        return [Finding(name, "error", "yaml.syntax", message, line=1)], None
    except yaml.YAMLError as failure:
        return [syntax_finding(name, failure, text)], None
    try:
        return [], LIST_SCHEMAS[kind].model_validate(data)
    except ValidationError as failure:
        document = _compose(path)
        return [
            Finding(
                name,
                "error",
                "yaml.schema",
                f"{'.'.join(str(p) for p in error['loc'])}: {error['msg']}",
                line=_yaml_line(document, error["loc"]),
                hint=schema_hint(f"see `cheme schema {kind}`", error),
            )
            for error in failure.errors()
        ], None


# ---------------------------------------------------------------------------
# Cross-checks
# ---------------------------------------------------------------------------


@dataclass
class _Scope:
    """Which sheets are not drawn or not read, so a listed item missing from the P&IDs is
    expected there rather than wrong.

    A missing item assigned (``sheet:``) to a planned or unloaded sheet, one without a sheet
    at the first stage, and one without a sheet while some sheet failed to load are info, one
    summary line per list, rule and reason; every other missing item stays a warning (a
    planned sheet alone does not hold back items without a sheet after the first stage).
    """

    #: Sheet id -> why it is not on the P&IDs read ("planned", "not loaded").
    unavailable: dict[str, str] = field(default_factory=dict)
    first_stage: bool = False
    _held: dict[tuple[str, str, str], list[Finding]] = field(default_factory=dict)

    def missing(self, finding: Finding, sheet: str | None) -> list[Finding]:
        """*finding* (a warning that an item is not on a P&ID), or nothing when it is held."""
        sheet = (sheet or "").strip()
        if sheet and sheet in self.unavailable:
            reason = f"assigned to sheet {sheet}, which is {self.unavailable[sheet]}"
        elif sheet:
            return [finding]
        elif self.first_stage:
            reason = "no sheet: given, and the plant is at its first stage"
        elif unread := sorted(s for s, why in self.unavailable.items() if why != "planned"):
            # A planned sheet does not hold back items without a sheet after the first stage:
            # they would stay hidden until the last sheet is drafted. A sheet that failed to
            # load might well hold them, so they wait for it.
            reason = (
                "no sheet: given, and "
                + ", ".join(f"{s} ({self.unavailable[s]})" for s in unread)
                + " may hold it"
            )
        else:
            return [finding]
        self._held.setdefault((finding.file, finding.rule, reason), []).append(finding)
        return []

    def summaries(self) -> list[Finding]:
        """One info finding per held group."""
        found = []
        for (file, rule, reason), held in self._held.items():
            ids = [i for f in held for i in f.ids[:1]]
            found.append(
                Finding(
                    file,
                    "info",
                    rule,
                    f"{len(held)} listed item(s) not on a P&ID yet, {reason}",
                    line=held[0].line,
                    ids=ids,
                    hint="expected until the sheet is drawn; give each item its `sheet:` so it "
                    "is checked once that sheet is drafted",
                )
            )
        self._held.clear()
        return found


def _cross_check_lines(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, SheetIndex]],
    line_list: Any,
    scope: _Scope | None = None,
) -> list[Finding]:
    """Line numbers, DNs and ``from``/``to`` of the line list against the PipingNetworkSystems.

    A line or segment missing from the P&IDs is reported through *scope*, which holds back
    what is expected on a sheet not drawn or not read.
    """
    scope = scope or _Scope()
    list_path = workspace.list_file("lines")
    list_name = workspace.relative(list_path)  # type: ignore[arg-type]
    lines = list(line_list.lines)
    entries = _entries(list_path, "lines", len(lines))  # type: ignore[arg-type]

    drawn: dict[str, list[tuple[SheetIndex, Any]]] = {}
    for model, index in sheets.values():
        for system in getattr(model.conceptualModel, "pipingNetworkSystems", None) or ():
            number = (system.lineNumber or "").strip() if isinstance(system.lineNumber, str) else ""
            if number:
                drawn.setdefault(number, []).append((index, system))

    numbers = [line.number.strip() for line in lines]
    findings = _duplicates(list_name, "line", "cheme.line-duplicate", numbers, entries)
    for number in sorted(set(drawn) - set(numbers)):
        index, system = drawn[number][0]
        findings.append(
            Finding(
                index.name,
                "warning",
                "cheme.line-not-listed",
                f"line {number} ({system.id}) is on the P&ID and not in the line list",
                line=index.line(system),
                ids=[number, system.id],
                hint=f"add it to {list_name}",
            )
        )
    for line, number, entry in zip(lines, numbers, entries, strict=True):
        if number not in drawn:
            findings += scope.missing(
                Finding(
                    list_name,
                    "warning",
                    "cheme.line-not-on-pid",
                    f"line {number} is in the line list and no PipingNetworkSystem on a "
                    "P&ID has that LineNumber",
                    line=entry.line,
                    ids=[number],
                    hint="draw it, fix the number, or remove it from the list",
                ),
                line.sheet,
            )
            continue
        findings += _line_dn_findings(list_name, number, line, entry, drawn[number], scope)
    findings += _line_endpoint_findings(sheets, list_name, lines, numbers, entries)
    return findings


def _base_tag(text: str | None) -> str:
    """``K-4101`` of ``K-4101/N2`` (a nozzle of it)."""
    return (text or "").split("/", 1)[0].strip()


def _line_endpoint_findings(
    sheets: dict[str, tuple[Any, SheetIndex]],
    list_name: str,
    lines: list[Any],
    numbers: list[str],
    entries: list[_Entry],
) -> list[Finding]:
    """``cheme.line-endpoint-mismatch``: a listed ``from``/``to`` tag the drawn line does not
    reach, while the line ends at a nozzle of equipment the list does not name.

    The ends of a line are the ends of its segments on every loaded sheet: nozzles (their
    equipment's tag) and the tagged piping items a segment ends at. A listed end that is not a
    tag drawn on a loaded sheet (``BL``, ``ATM``, a line number, an area) is not compared, and a
    line whose other ends are tees, off-page connectors or open ends only may reach the listed
    item beyond them, so only a drawn equipment end the list does not name makes a finding.
    """
    from chemeascode.domains.piping.sheet_query import sheet_items
    from chemeascode.domains.spatial.pid_network import sheet_network

    drawn_tags: set[str] = set()
    ends: dict[str, tuple[set[str], set[str], list[str]]] = {}
    for name, (model, _) in sheets.items():
        try:
            drawn_tags |= {i.tag for i in sheet_items(model, name) if i.kind != "line"}
            segments = sheet_network(model, name)
        except Exception:  # noqa: BLE001 - a sheet the model cannot walk is reported elsewhere
            continue
        for segment in segments:
            tags, equipment, where = ends.setdefault(segment.line, (set(), set(), []))
            for end in (segment.source, segment.target):
                if end.tag and end.kind in ("nozzle", "item"):
                    tags.add(end.tag)
                    if end.kind == "nozzle":
                        equipment.add(end.tag)
            tags.update(item.tag for item in segment.items if item.tag)
            if name not in where:
                where.append(name)
    drawn_tags -= set(numbers) | set(ends)  # a line number is an end at another line
    findings: list[Finding] = []
    for line, number, entry in zip(lines, numbers, entries, strict=True):
        if number not in ends:
            continue
        tags, equipment, where = ends[number]
        listed = {side: _base_tag(value) for side, value in (("from", line.from_), ("to", line.to))}
        missing = {
            side: tag
            for side, tag in listed.items()
            if tag and tag in drawn_tags and tag not in tags
        }
        extra = sorted(equipment - set(listed.values()))
        if not missing or not extra:
            continue
        said = " and ".join(f"{side} {tag}" for side, tag in missing.items())
        findings.append(
            Finding(
                list_name,
                "warning",
                "cheme.line-endpoint-mismatch",
                f"line {number} is listed {said}; on the P&ID ({', '.join(where)}) it ends at "
                f"{', '.join(sorted(tags))}, not at {', '.join(missing.values())}",
                line=entry.line,
                ids=[number, *missing.values(), *extra],
                hint="connect the line to the listed equipment on the sheet, or fix `from`/`to` "
                "in the line list",
            )
        )
    return findings


def _line_dn_findings(
    list_name: str,
    number: str,
    line: Any,
    entry: _Entry,
    drawn: list[tuple[SheetIndex, Any]],
    scope: _Scope,
) -> list[Finding]:
    """One listed line against the PipingNetworkSystems drawn with its number."""
    findings: list[Finding] = []
    wanted = _number(line.nominal_diameter)
    if wanted is not None:
        for index, system in drawn:
            actual = _dn(system)
            if actual is not None and actual != wanted:
                findings.append(
                    Finding(
                        list_name,
                        "warning",
                        "cheme.line-dn-mismatch",
                        f"line {number} is listed as {line.nominal_diameter} and drawn as "
                        f"{_dn_text(actual)} ({index.name}, {system.id})",
                        line=entry.line,
                        ids=[number, system.id],
                        hint="align the list and the PipingNetworkSystem's NominalDiameter; "
                        "list segments of another DN under `segments`",
                    )
                )
    for position, listed_segment in enumerate(line.segments):
        segment_number = listed_segment.number.strip()
        found = [
            (index, segment)
            for index, system in drawn
            for segment in system.segments or ()
            if (segment.segmentNumber or "").strip() == segment_number
        ]
        where = (entry.segments[position] if position < len(entry.segments) else None) or entry.line
        key = f"{number}/{segment_number}"
        if not found:
            findings += scope.missing(
                Finding(
                    list_name,
                    "warning",
                    "cheme.line-not-on-pid",
                    f"segment {segment_number} of line {number} is in the line list and "
                    f"line {number} has no segment with that SegmentNumber",
                    line=where,
                    ids=[key],
                    hint="fix the segment number, or remove the segment from the list",
                ),
                line.sheet,
            )
            continue
        wanted = _number(listed_segment.nominal_diameter)
        for index, segment in found:
            actual = _dn(segment)
            if wanted is None or actual is None or actual == wanted:
                continue
            findings.append(
                Finding(
                    list_name,
                    "warning",
                    "cheme.line-dn-mismatch",
                    f"segment {segment_number} of line {number} is listed as "
                    f"{listed_segment.nominal_diameter} and drawn as {_dn_text(actual)} "
                    f"({index.name}, {segment.id})",
                    line=where,
                    ids=[key, segment.id],
                    hint="align the list and the PipingNetworkSegment's NominalDiameter",
                )
            )
    return findings


def _cross_check_instruments(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, SheetIndex]],
    instrument_list: Any,
    scope: _Scope | None = None,
) -> list[Finding]:
    from pydexpi.toolkits.model_summary import summarize_model

    list_path = workspace.list_file("instruments")
    list_name = workspace.relative(list_path)  # type: ignore[arg-type]
    instruments = list(instrument_list.instruments)
    entries = _entries(list_path, "instruments", len(instruments))  # type: ignore[arg-type]
    drawn: dict[str, tuple[SheetIndex, str]] = {}
    for model, index in sheets.values():
        for summary in summarize_model(model).instruments:
            if summary.tag:
                drawn.setdefault(summary.tag.strip(), (index, summary.id))
    tags = [item.tag.strip() for item in instruments]
    findings = _duplicates(list_name, "instrument", "cheme.instrument-duplicate", tags, entries)
    scope = scope or _Scope()
    reported: set[str] = set()
    for item, tag, entry in zip(instruments, tags, entries, strict=True):
        if tag in drawn or tag in reported:
            continue
        reported.add(tag)
        findings += scope.missing(
            Finding(
                list_name,
                "warning",
                "cheme.instrument-not-on-pid",
                f"{tag} is in the instrument list and no P&ID prints that instrument tag",
                line=entry.line,
                ids=[tag],
                hint="draw it, fix the tag (category + function letters, '-', number), or "
                "remove it",
            ),
            item.sheet,
        )
    for tag in sorted(set(drawn) - set(tags)):
        index, object_id = drawn[tag]
        findings.append(
            Finding(
                index.name,
                "warning",
                "cheme.instrument-not-listed",
                f"instrument {tag} ({object_id}) is on the P&ID and not in the instrument list",
                line=index.line(object_id),
                ids=[tag, object_id],
                hint=f"add it to {list_name}",
            )
        )
    return findings


def _cross_check_equipment(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, SheetIndex]],
    equipment_list: Any,
    scope: _Scope | None = None,
) -> list[Finding]:
    from pydexpi.toolkits.model_summary import summarize_model

    list_path = workspace.list_file("equipment")
    list_name = workspace.relative(list_path)  # type: ignore[arg-type]
    items = list(equipment_list.equipment)
    entries = _entries(list_path, "equipment", len(items))  # type: ignore[arg-type]
    from chemeascode.domains.equipment.dimensions import RULE as DIMENSION_RULE
    from chemeascode.domains.equipment.dimensions import dimension_problems

    drawn: dict[str, tuple[SheetIndex, str, str]] = {}
    objects: dict[str, Any] = {}  # tag -> the DEXPI object, for the dimension check
    for model, index in sheets.values():
        by_id = {
            getattr(obj, "id", None): obj
            for obj in getattr(model.conceptualModel, "taggedPlantItems", None) or ()
        }
        for summary in summarize_model(model).equipment:
            if summary.tag:
                drawn.setdefault(summary.tag.strip(), (index, summary.type, summary.id))
                if summary.id in by_id:
                    objects.setdefault(summary.tag.strip(), by_id[summary.id])

    tags = [item.tag.strip() for item in items]
    findings = _duplicates(list_name, "equipment item", "cheme.equipment-duplicate", tags, entries)
    scope = scope or _Scope()
    reported: set[str] = set()
    for item, tag, entry in zip(items, tags, entries, strict=True):
        if tag not in drawn:
            if tag not in reported:
                reported.add(tag)
                findings += scope.missing(
                    Finding(
                        list_name,
                        "warning",
                        "cheme.equipment-not-on-pid",
                        f"{tag} is in the equipment list and on no P&ID",
                        line=entry.line,
                        ids=[tag],
                        hint="draw it, or remove it from the list",
                    ),
                    item.sheet,
                )
            continue
        drawn_type = drawn[tag][1]
        if item.dimensions is not None and tag in objects:
            for problem in dimension_problems(item.dimensions, objects[tag]):
                findings.append(
                    Finding(
                        list_name,
                        "warning",
                        DIMENSION_RULE,
                        f"{tag}: {problem} (P&ID {drawn[tag][0].name})",
                        line=entry.line,
                        ids=[tag],
                        key=f"{tag}:{problem.split(' ', 1)[0]}",
                        hint="correct dimensions or the P&ID attribute, whichever is wrong",
                    )
                )
        if item.type and item.type != drawn_type:
            findings.append(
                Finding(
                    list_name,
                    "warning",
                    "cheme.equipment-type-mismatch",
                    f"{tag} is listed as {item.type} and drawn as {drawn_type}",
                    line=entry.line,
                    ids=[tag],
                    hint="use the DEXPI class the P&ID draws, or redraw the item",
                )
            )
    findings += [
        Finding(
            drawn[tag][0].name,
            "warning",
            "cheme.equipment-not-listed",
            f"{drawn[tag][1]} {tag} is on the P&ID and not in the equipment list",
            line=drawn[tag][0].line(drawn[tag][2]),
            ids=[tag],
            hint=f"add it to {list_name}",
        )
        for tag in sorted(set(drawn) - set(tags))
    ]
    return findings


# ---------------------------------------------------------------------------
# Whole repository
# ---------------------------------------------------------------------------


def validate_workspace(
    workspace: Workspace, only: Iterable[Path] | None = None, *, generators: bool = False
) -> Report:
    """Validate the repository, or only the files in *only* (cross-checks then skipped).

    *generators* also runs the generator of each generated sheet (``plant.yaml``
    ``generator:``) to report ``cheme.generated-sheet-drift``.
    """
    report = Report()
    targets = {p.resolve() for p in only} if only else None

    try:
        config = workspace.config()
    except (ValidationError, yaml.YAMLError, UnicodeDecodeError) as failure:
        report.findings.append(
            Finding("plant.yaml", "error", "yaml.schema", str(failure).splitlines()[0])
        )
        return report

    from chemeascode.domains.piping.sheets import titleblock_findings

    sheets: dict[str, tuple[Any, SheetIndex]] = {}
    entries = {}
    for position, entry in enumerate(config.sheets):
        path = workspace.sheet_path(entry.file)
        if path is not None:
            entries.setdefault(path.resolve(), (position, entry))
    plant_yaml = _compose(workspace.root / "plant.yaml")
    scope = _Scope(first_stage=bool(config.stages) and config.stage == config.stages[0].id)
    if targets is None:
        for file in workspace.outside_sheets():
            report.findings.append(
                Finding(
                    "plant.yaml",
                    "error",
                    "cheme.sheet-outside-repo",
                    f"sheet file {file!r} is outside the repository; it is not read",
                    hint="list sheets by a path relative to the repository root, without '..'",
                )
            )
    for path in workspace.pid_files():
        if targets is not None and path.resolve() not in targets:
            continue
        name = workspace.relative(path)
        position, entry = entries.get(path.resolve(), (None, None))
        sheet_id = entry.id if entry is not None else path.stem
        where = _yaml_line(plant_yaml, ["sheets", position]) if position is not None else None
        if not path.is_file():
            if entry is not None and entry.status == "planned":
                report.findings.append(
                    Finding(
                        "plant.yaml",
                        "info",
                        "cheme.sheet-planned",
                        f"sheet {sheet_id} ({name}) is planned and not drawn yet",
                        line=where,
                        ids=[sheet_id],
                        hint=f"`cheme sheet new {sheet_id}` starts it",
                    )
                )
                report.compared["planned"].append(sheet_id)
                scope.unavailable[sheet_id] = "planned"
                continue
            report.files.append(name)
            report.findings.append(
                Finding(
                    "plant.yaml",
                    "error",
                    "cheme.missing-sheet",
                    f"sheet file {name} does not exist",
                    line=where,
                    ids=[sheet_id],
                    hint=f"start it with `cheme sheet new {sheet_id}`, or mark the sheet "
                    "`status: planned` until it is drawn",
                )
            )
            report.compared["not_loaded"].append(name)
            scope.unavailable[sheet_id] = "not loaded"
            continue
        report.files.append(name)
        findings, model, index = _validate_pid(path, name)
        report.findings += findings
        if index is not None and index.title_block is not None:
            report.findings += titleblock_findings(workspace, name, index.title_block, entry)
        if model is not None and index is not None:
            sheets[name] = (model, index)
            report.compared["sheets"].append(name)
        else:
            report.compared["not_loaded"].append(name)
            scope.unavailable[sheet_id] = "not loaded"

    from chemeascode.domains.piping.generators import generator_findings

    report.findings += generator_findings(workspace, targets, run=generators)
    # Tags that two piping components or two instruments share, on one sheet or across sheets.
    from chemeascode.domains.piping.tag_rules import duplicate_tag_findings

    every_sheet = [(workspace.relative(p), p) for p in workspace.pid_files() if p.is_file()]
    report.findings += duplicate_tag_findings(
        every_sheet,
        None if targets is None else [name for name, p in every_sheet if p.resolve() in targets],
    )

    parsed: dict[str, Any] = {}
    for kind in LIST_SCHEMAS:
        path = workspace.list_file(kind)
        if path is None or (targets is not None and path.resolve() not in targets):
            continue
        name = workspace.relative(path)
        report.files.append(name)
        report.compared["lists"].append(kind)
        findings, model = validate_list(path, kind, name)
        report.findings += findings
        if model is not None:
            parsed[kind] = model

    # Process YAML and the generated BFD/PFD sheets: pyDEXPI rules, process rules, provenance;
    # the P&ID drawing lint and cross-checks do not apply to them.
    from chemeascode.domains.process.sheets import workspace_findings

    found, files, loaded = workspace_findings(workspace, parsed, targets)
    report.findings += found
    report.files += files
    report.compared["sheets"] += loaded
    report.process_sheets = loaded
    if files:
        report.compared["lists"].append("process")

    # Petroleum assays: insufficient or extrapolated assays, a stale characterisation record.
    from chemeascode.domains.process.thermodynamics.assay import ASSAYS_FILE
    from chemeascode.domains.process.thermodynamics.assay import (
        workspace_findings as assay_findings,
    )

    found, read = assay_findings(workspace.root, targets)
    report.findings += found
    if read:
        report.files.append(ASSAYS_FILE)

    from chemeascode.domains.piping.piping_items import cross_check_piping_items

    cross_checks = {
        "equipment": _cross_check_equipment,
        "lines": _cross_check_lines,
        "instruments": _cross_check_instruments,
        "piping_items": cross_check_piping_items,  # optional list
    }
    optional = {"piping_items"}
    for kind, cross_check in cross_checks.items():
        if kind in optional and workspace.list_file(kind) is None:
            continue
        if targets is not None:
            reason = "only the files given"
        elif not sheets:
            reason = "no P&ID loaded"
        elif workspace.list_file(kind) is None:
            reason = f"no {LIST_FILES[kind]}"
        elif kind not in parsed:
            reason = f"{LIST_FILES[kind]} invalid"
        else:
            report.findings += cross_check(workspace, sheets, parsed[kind], scope)
            report.findings += scope.summaries()
            report.compared["cross_checks"].append(f"{kind} list vs P&IDs")
            if scope.unavailable:
                held = ", ".join(f"{s} {why}" for s, why in sorted(scope.unavailable.items()))
                report.compared["skipped"].append(
                    f"{kind} on unavailable sheets not reported missing ({held})"
                )
            continue
        report.compared["skipped"].append(f"{kind} list vs P&IDs ({reason})")

    if targets is None:
        _cross_check_tags(workspace, report, parsed)
    else:
        report.compared["skipped"].append("tags named in texts (only the files given)")

    # Cause and effect; without the file, trip instruments still ask for it.
    has_file = workspace.list_file("interlocks") is not None
    if targets is None and sheets and ("interlocks" in parsed or not has_file):
        from chemeascode.domains.control.interlocks import cross_check_interlocks

        partial = bool(report.compared["not_loaded"])
        report.findings += cross_check_interlocks(workspace, sheets, parsed, partial)
        report.compared["cross_checks"].append("interlocks vs lists and P&IDs")

    # Loops, sequences, the narrative and the control philosophy.
    if targets is None:
        from chemeascode.domains.control.documents import load_documents
        from chemeascode.domains.control.register import control_findings, has_records

        documents = load_documents(workspace)
        if has_records(workspace, parsed, documents):
            partial = bool(report.compared["not_loaded"])
            report.findings += control_findings(workspace, sheets, parsed, partial, documents)
            report.files += [d.name for d in documents.values() if d.started]
            report.compared["cross_checks"].append(
                "control records vs lists, P&IDs, C&E and operating cases"
            )
    elif any(getattr(parsed.get(k), k, None) for k in ("loops", "sequences")):
        report.compared["skipped"].append("control records (only the files given)")
    if targets is None and "interlocks" in parsed:  # C&E delays are times
        from chemeascode.domains.control.register import interlock_time_findings

        report.findings += interlock_time_findings(workspace, parsed)

    if targets is None and "electrical" in parsed:  # the electrical list (motors, rooms, JBs)
        from chemeascode.domains.control.electrical import cross_check_electrical

        report.findings += cross_check_electrical(workspace, parsed)
        report.compared["cross_checks"].append("electrical list vs equipment list")

    # HAZOP studies: against themselves, their matrix and (all files) the plant.
    from chemeascode.domains.safety.hazop import hazop_findings

    found, files = hazop_findings(workspace, sheets, parsed, targets)
    if files:
        report.findings += found
        report.files += files
        report.compared["lists"].append("hazop")
        if targets is not None:
            report.compared["skipped"].append(
                "HAZOP references to tags, sheets and interlocks (only the files given)"
            )
        else:
            report.compared["cross_checks"].append("HAZOP studies vs lists, P&IDs and C&E")
            if report.compared["not_loaded"]:
                report.compared["skipped"].append(
                    "HAZOP tags on sheets not loaded are checked against the lists only"
                )

    _validate_layout(workspace, report, targets, parsed, sheets)

    if targets is None:  # equipment datasheets against the equipment list
        from chemeascode.domains.equipment.datasheets import (
            check_datasheets,
            datasheet_paths,
            reference_findings,
        )
        from chemeascode.domains.equipment.fill import stale_findings

        sheets_found = datasheet_paths(workspace)
        if sheets_found:
            report.files += [workspace.relative(p) for p in sheets_found]
            report.findings += check_datasheets(workspace, parsed.get("equipment"))
            report.findings += stale_findings(workspace)
            report.findings += reference_findings(workspace)
            report.compared["lists"].append("datasheet")
            if "equipment" in parsed:
                report.compared["cross_checks"].append("datasheets vs equipment list")
            report.findings += _datasheet_nozzles(workspace, report)
            report.findings += _datasheet_schedule(workspace, report, parsed, sheets)

    # Reaction evidence: sources, observations, routes and the model basis.
    from chemeascode.domains.chemistry.evidence import EVIDENCE_FILE
    from chemeascode.project.evidence import evidence_findings

    found, present = evidence_findings(workspace.root, targets)
    report.findings += found
    if present and (targets is None or (workspace.root / EVIDENCE_FILE).resolve() in targets):
        report.files.append(EVIDENCE_FILE)

    # Electrochemical cells: Faraday balance, refusals and the flowsheet link.
    from chemeascode.domains.process.electrochemical_cell import CELLS_FILE, cell_report

    cells_path = workspace.root / CELLS_FILE
    if cells_path.is_file() and (targets is None or cells_path.resolve() in targets):
        report.findings += cell_report(workspace.root).findings
        report.files.append(CELLS_FILE)

    # Measured electrochemical series: schema, units, Faradaic and charge balances.
    from chemeascode.domains.experiments.electrochemistry import (
        measurement_files,
        measurement_report,
    )

    for name in measurement_files(workspace.root):
        if targets is None or (workspace.root / name).resolve() in targets:
            report.findings += measurement_report(workspace.root, name).findings
            report.files.append(name)

    # Liquid-liquid extractors: the schema only; `cheme process extract` solves them.
    from chemeascode.domains.process.separations import extraction

    extraction_path = workspace.root / extraction.EXTRACTION_FILE
    if extraction_path.is_file() and (targets is None or extraction_path.resolve() in targets):
        report.files.append(extraction.EXTRACTION_FILE)
        report.findings += extraction.load(workspace.root)[2]

    # Decision references (D-NNN) against the DESIGN.md register.
    from chemeascode.project.decisions import decision_findings

    report.findings += decision_findings(workspace, targets)

    # review records: front matter, finding ids and statuses
    if targets is None:
        from chemeascode.foundation.reviews import load_records, review_rules

        records = load_records(workspace)
        if records:
            report.findings += review_rules(workspace, records)
            report.files += [r.name for r in records]
            report.compared["cross_checks"].append("review records")

    # gates naming no plant.yaml stage, duplicate gate ids
    if "checks" in parsed:
        from chemeascode.project.checks import checklist_findings

        report.findings += checklist_findings(workspace, parsed["checks"], LIST_FILES["checks"])

    # Last, so that checks.yaml's accept: entries see every finding.
    _accept(workspace, report, full=targets is None)

    report.findings.sort(key=lambda f: (f.file, f.line or 0, -_SEVERITY[f.level]))
    return report


def _datasheet_schedule(
    workspace: Workspace,
    report: Report,
    parsed: dict[str, Any],
    sheets: dict[str, tuple[Any, SheetIndex]],
) -> list[Finding]:
    """Datasheet main dimensions against the equipment list and the layout model, the nozzle
    schedules against the loaded P&IDs and the line list, and the outline drawings' drift."""
    from chemeascode.domains.equipment.datasheets import (
        dimension_findings,
        drawing_findings,
        nozzle_findings,
    )
    from chemeascode.domains.spatial.model import read
    from chemeascode.project.datasheets import nozzles_of, title_meta

    model = None
    path = workspace.layout_model_file()
    if path is not None:
        model = read(path.read_text(encoding="utf-8"))
    findings = dimension_findings(workspace, parsed.get("equipment"), model)
    report.compared["cross_checks"].append("datasheet dimensions vs equipment list")
    # every sheet loaded: a sheet that did not could draw more nozzles of an item
    pid = None
    if not report.compared["not_loaded"]:
        pid, _ = nozzles_of([(name, loaded) for name, (loaded, _) in sorted(sheets.items())])
        report.compared["cross_checks"].append("datasheet nozzles vs P&IDs")
    findings += nozzle_findings(workspace, pid, parsed.get("lines"))
    findings += drawing_findings(workspace, title_meta(workspace))
    return findings


def _datasheet_nozzles(workspace: Workspace, report: Report) -> list[Finding]:
    """Datasheet nozzle locations against the layout model, only when a datasheet gives one
    and the model exists (the model is read only then)."""
    from chemeascode.domains.equipment.datasheets import (
        declares_nozzle_locations,
        nozzle_location_findings,
    )
    from chemeascode.domains.spatial.model import read

    path = workspace.layout_model_file()
    if path is None or not declares_nozzle_locations(workspace):
        return []
    model = read(path.read_text(encoding="utf-8"))
    if model is None:
        return []
    report.compared["cross_checks"].append("datasheet nozzle locations vs layout model")
    return nozzle_location_findings(workspace, model)


def _validate_layout(
    workspace: Workspace,
    report: Report,
    targets: set[Path] | None,
    parsed: dict[str, Any],
    sheets: dict[str, tuple[Any, SheetIndex]] | None = None,
) -> None:
    """The layout files: each against its schema, then the ``cheme.layout-*`` rules."""
    from chemeascode.domains.spatial.layout_validate import parse, workspace_layout
    from chemeascode.foundation.workspace import LAYOUT_FILES

    present = [kind for kind in LAYOUT_FILES if workspace.layout_file(kind) is not None]
    if not present:
        return
    if targets is not None:
        for kind in present:
            path = workspace.layout_file(kind)
            assert path is not None
            if path.resolve() not in targets:
                continue
            name = workspace.relative(path)
            report.files.append(name)
            report.compared["lists"].append(kind)
            report.findings += parse(path.read_text(encoding="utf-8"), kind, name)[0]
        if any(kind in report.compared["lists"] for kind in present):
            report.compared["skipped"].append("layout rules (only the files given)")
        return
    from chemeascode.domains.piping.sheet_query import sheet_items
    from chemeascode.domains.spatial.model import model_findings
    from chemeascode.domains.spatial.pid_nozzles import sheet_equipment

    drawn = {
        item.tag.strip()
        for name, (model, _) in (sheets or {}).items()
        for item in sheet_items(model, name)
        if item.tag and item.kind != "line"
    }
    nozzles: dict[str, set[str]] = {}
    for name, (model, _) in (sheets or {}).items():
        for tag, item in sheet_equipment(model, name).items():
            nozzles.setdefault(tag, set(item.names))
    layout = workspace_layout(
        workspace,
        parsed.get("equipment"),
        parsed.get("piping_items"),
        parsed.get("lines"),
        drawn_tags=drawn,
        nozzles=nozzles,
    )
    for kind in present:
        path = workspace.layout_file(kind)
        assert path is not None
        report.files.append(workspace.relative(path))
        report.compared["lists"].append(kind)
    report.findings += layout.findings
    report.findings += [
        f
        for f in model_findings(workspace)
        if layout.ruled or f.rule != "cheme.layout-model-missing"
    ]
    if workspace.layout_model_file() is not None:
        report.files.append(workspace.relative(workspace.layout_model_file()))  # type: ignore[arg-type]
        if layout.ruled:
            from contextlib import suppress

            from chemeascode.domains.spatial.model_rules import workspace_model_rules

            with suppress(KeyError, TypeError, ValueError):  # another shape: -version says so
                report.findings += workspace_model_rules(workspace)
            from chemeascode.domains.spatial.lifting import study_findings

            with suppress(KeyError, TypeError, ValueError):
                report.findings += study_findings(workspace)
    if layout.ruled:
        report.compared["cross_checks"].append("layout")
        if "placement" in present and "equipment" not in parsed:
            report.compared["skipped"].append(
                f"layout tags vs equipment list (no valid {LIST_FILES['equipment']})"
            )
    else:
        report.compared["skipped"].append("layout rules (a layout file is invalid)")


def _cross_check_tags(workspace: Workspace, report: Report, parsed: dict[str, Any]) -> None:
    """Tags named in literal texts and off-page texts (``chemeascode.domains.piping.tagrefs``)."""
    from chemeascode.domains.piping.tagrefs import cross_check_tags

    config = workspace.config()
    files = {workspace.relative(p): p for p in workspace.pid_files()}
    sheets = [
        (files[sheet.file], sheet.file, sheet.id)
        for sheet in config.sheets
        if sheet.file in files and files[sheet.file].is_file()
    ]
    known = {name for _, name, _ in sheets}
    sheets += [(p, n, "") for n, p in files.items() if n not in known and p.is_file()]
    if not sheets:
        return
    report.findings += cross_check_tags(sheets, parsed, [s.id for s in config.sheets])
    report.compared["cross_checks"].append("tags named in texts")


def _accept(workspace: Workspace, report: Report, full: bool) -> None:
    """Mark the findings the ``accept:`` list of checks/checks.yaml names: info, with the reason.

    An entry that names an error does not accept it, and is reported (warning,
    ``cheme.accept-error``). On a full run an entry, top-level or of a ``kind: validate``
    gate, that names no finding is reported (info), so stale ones are removed. An entry whose
    reason quotes a length the finding no longer measures (a span, a run, a distance) is
    reported as out of date (warning, ``cheme.accept-stale``).
    """
    checks, name = _check_list(workspace)
    if checks is None or name is None:
        return
    entries = list(checks.accept)
    used: set[int] = set()
    refused: dict[int, list[str]] = {}
    stale: list[tuple[str | None, Any, Finding]] = []
    for finding in report.findings:
        for position, entry in enumerate(entries):
            if not accept_matches(entry.id, finding.id):
                continue
            if finding.level == "error":
                refused.setdefault(position, []).append(finding.id)
                continue
            finding.accepted = entry.reason
            finding.level = "info"
            used.add(position)
            stale.append((None, entry, finding))
            break
    gates = [
        (check.id, entry)
        for check in checks.checks
        if check.kind == "validate"
        for entry in check.accept
    ]
    for gate, entry in gates:
        hits = [f for f in report.findings if accept_matches(entry.id, f.id)]
        errors = [f.id for f in hits if f.level == "error"]
        if errors:
            report.findings.append(_accept_error(name, entry.id, errors, gate))
        stale += [(gate, entry, f) for f in hits if f.level != "error"]
    for gate, entry, finding in stale:
        quoted = stale_quote(entry.reason, finding)
        if quoted is None:
            continue
        where = f" (gate {gate})" if gate else ""
        key = f"{gate}:{entry.id}" if gate else entry.id
        which, ids = "the finding", [entry.id]
        if finding.id != entry.id:  # a wildcard entry: one finding each, named
            key, which, ids = f"{key}@{finding.id}", finding.id, [entry.id, finding.id]
        report.findings.append(
            Finding(
                name,
                "warning",
                "cheme.accept-stale",
                f"accept: {entry.id!r}{where} quotes {quoted:g} m, but {which} now "
                f"measures {finding.measured:.2f} m: the reason is out of date",
                ids=ids,
                key=key,
                measured=finding.measured,
                hint="check that the acceptance still holds at the current value and quote it "
                "in the reason, or fix the finding",
            )
        )
    for position, ids in sorted(refused.items()):
        report.findings.append(_accept_error(name, entries[position].id, ids, None))
    if not full:
        return
    unused = [(None, e) for p, e in enumerate(entries) if p not in used and p not in refused]
    unused += [
        (gate, entry)
        for gate, entry in gates
        if not any(accept_matches(entry.id, f.id) for f in report.findings)
    ]
    for gate, entry in unused:
        where = f" (gate {gate})" if gate else ""
        report.findings.append(
            Finding(
                name,
                "info",
                "cheme.accept-unused",
                f"accept: {entry.id!r}{where} names no finding",
                ids=[entry.id],
                key=f"{gate}:{entry.id}" if gate else entry.id,
                hint="remove the entry when the finding is fixed, or correct its id "
                "(`cheme validate --json` lists each finding's id)",
            )
        )


def _accept_error(name: str, pattern: str, ids: list[str], gate: str | None) -> Finding:
    where = f" (gate {gate})" if gate else ""
    shown = ", ".join(ids[:3]) + (f" and {len(ids) - 3} more" if len(ids) > 3 else "")
    return Finding(
        name,
        "warning",
        "cheme.accept-error",
        f"accept: {pattern!r}{where} names {len(ids)} error(s), which cannot be accepted: {shown}",
        ids=[pattern],
        key=f"{gate}:{pattern}" if gate else pattern,
        hint="fix the error; accept: only turns warnings and infos into accepted infos",
    )
