"""``cheme.duplicate-tag``: two piping components or two instruments with one tag.

A tag names one thing in the plant. Copying a line with its valves (``cheme copy``) and
forgetting to renumber them leaves two valves ``HV-4146`` on the P&IDs; nothing else notices,
because the lists only carry equipment, lines and instruments.

- **Piping components** (valves, safety valves, ... in a piping network segment) are compared
  by ``PipingComponentNumber`` and ``PositionNumber``. Only plant-wide tags count: a value with
  a separator or a number of three digits or more (``HV-4146``, ``TSV4144``). The DEXPI
  reference numbers components within their segment (``C1``, ``C2``); those repeat legitimately.
- **Instruments** are compared by the printed tag of their ProcessInstrumentationFunction
  (``FI-4148``).

Both within one sheet and across the sheets of the repository.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

import yaml
from lxml import etree

from chemeascode.domains.piping.show import data_value, instrument_tag, short_class
from chemeascode.foundation.findings import Finding

_COMPONENT_TAGS = ("PipingComponentNumber", "PositionNumber")
_PLANT_WIDE = re.compile(r"[A-Za-z]*\s*[-/.]\s*\w|[A-Za-z]*\d{3,}")
_NOT_COMPONENTS = (
    "Plant/Piping.PipingNetworkSystem",
    "Plant/Piping.PipingNetworkSegment",
    "Plant/Piping.Pipe",
    "Plant/Piping.PipingNode",
    "Plant/Piping.DirectPipingConnection",
)


def _conceptual(element: etree._Element) -> bool:
    return not any(
        a.tag == "Components" and a.get("property") in ("Diagram", "ShapeCatalogues")
        for a in element.iterancestors()
    )


def tagged(root: etree._Element) -> list[tuple[str, str, str, etree._Element]]:
    """``(kind, tag, property, element)`` for every tagged piping component and instrument."""
    found = []
    for element in root.iter("Object"):
        kind = element.get("type", "")
        if kind.startswith("Plant/Piping.") and not kind.startswith(_NOT_COMPONENTS):
            tags = {}
            for prop in _COMPONENT_TAGS:
                value = (data_value(element, prop) or "").strip()
                if value and _PLANT_WIDE.match(value):
                    tags.setdefault(value, prop)
            if tags and _conceptual(element):
                found += [("piping component", t, p, element) for t, p in tags.items()]
        elif kind.endswith("ProcessInstrumentationFunction"):
            tag = instrument_tag(element)
            if tag and "-" in tag and _conceptual(element):
                found.append(("instrument", tag, "", element))
    return found


def _hint(name: str, object_id: str, prop: str) -> str:
    if prop:
        return (
            f"give one its own tag: cheme rename {object_id} NEWTAG --tag --sheet {name} "
            f"(or cheme set {object_id} {prop}=NEWTAG)"
        )
    # An instrument: rename --tag also renumbers its sensor and actuator (FT4150, not AT3104).
    return (
        f"give one its own tag: cheme rename {object_id} LETTERS-NUMBER --tag --sheet {name} "
        "(it renumbers the sensor and actuator too), or copy again with --tag"
    )


def duplicate_tag_findings(
    sheets: Iterable[tuple[str, Path]], report_for: Iterable[str] | None = None
) -> list[Finding]:
    """One error per object that repeats a tag another object (any sheet) has.

    *sheets* are all the sheets whose tags count; with *report_for* (sheet names) only objects
    on those sheets get a finding, so validating one sheet still sees the tags of the others.
    """
    groups: dict[tuple[str, str], list[tuple[str, str, etree._Element]]] = {}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for name, path in sheets:
        try:
            root = etree.fromstring(path.read_bytes(), parser)
        except (OSError, etree.XMLSyntaxError):
            continue  # validate reports it
        for kind, tag, prop, element in tagged(root):
            groups.setdefault((kind, tag.upper()), []).append((name, prop, element))
    wanted = set(report_for) if report_for is not None else None
    findings = []
    for (kind, _), members in groups.items():
        if len(members) < 2:
            continue
        for index, (name, prop, element) in enumerate(members):
            if wanted is None and index == 0:
                continue  # the first one keeps the tag
            if wanted is not None and name not in wanted:
                continue
            other_name, _, other = members[1 if index == 0 else 0]
            where = f"{other_name}:{other.sourceline}" if other.sourceline else other_name
            object_id = element.get("id") or short_class(element)
            tag = next(t for k, t, _, e in tagged_one(element) if k == kind)
            findings.append(
                Finding(
                    name,
                    "error",
                    "cheme.duplicate-tag",
                    f"{kind} tag {tag} of {object_id} ({short_class(element)}) is also the tag "
                    f"of {other.get('id') or short_class(other)} ({short_class(other)}, {where})",
                    line=element.sourceline,
                    ids=[i for i in (element.get("id"), other.get("id")) if i],
                    hint=_hint(name, object_id, prop),
                )
            )
    findings.sort(key=lambda f: (f.file, f.line or 0))
    return findings


def tagged_one(element: etree._Element) -> list[tuple[str, str, str, etree._Element]]:
    """:func:`tagged` for one element (not its parts)."""
    return [t for t in tagged(element) if t[3] is element]


def tag_clashes(
    path: Path,
    root: etree._Element,
    element: etree._Element,
    name: str | None = None,
    *,
    tags: Iterable[str] | None = None,
) -> list[str]:
    """``TAG: ID (Class, sheet:line)`` for each object on this or another sheet of the
    workspace that has a tag *element* has (as :func:`tagged` counts tags; only *tags*)."""
    only = {t.upper() for t in tags} if tags is not None else None
    mine = {
        (kind, tag.upper()): tag
        for kind, tag, _, _ in tagged_one(element)
        if only is None or tag.upper() in only
    }
    if not mine:
        return []
    sheets: list[tuple[str, etree._Element]] = [(name or str(path), root)]
    from chemeascode.foundation.workspace import NotAPlantRepository, Workspace

    try:
        workspace = Workspace.find(path.parent)
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        for other in workspace.pid_files():
            if other.is_file() and other.resolve() != path.resolve():
                try:
                    sheets.append(
                        (workspace.relative(other), etree.fromstring(other.read_bytes(), parser))
                    )
                except (OSError, etree.XMLSyntaxError):
                    continue
    # not in a plant repository, or a plant.yaml that does not load: this sheet only
    except (NotAPlantRepository, OSError, ValueError, yaml.YAMLError):
        pass
    found = []
    for sheet_name, sheet_root in sheets:
        for kind, tag, _, other in tagged(sheet_root):
            if other is not element and (kind, tag.upper()) in mine:
                where = f"{sheet_name}:{other.sourceline}" if other.sourceline else sheet_name
                object_id = other.get("id") or short_class(other)
                found.append(f"{tag}: {object_id} ({short_class(other)}, {where})")
    return found
