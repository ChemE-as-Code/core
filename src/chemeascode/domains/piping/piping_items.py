"""``piping/special-items.yaml`` against the P&IDs: tagged piping components.

Safety valves, rupture discs, breather valves, flame arrestors and silencers are DEXPI piping
components, not equipment or instrument functions, and carry their tag as
``PipingComponentNumber`` (or ``PositionNumber`` / ``PipingComponentName``; see
``sheet_query.component_tag``). The list holds them so that a listed relief
device that is not drawn, or a drawn one that is not listed, is reported.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.piping.sheet_index import SheetIndex
from chemeascode.domains.piping.sheet_query import DrawnItem, sheet_items
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace
from chemeascode.foundation.yamlsource import _duplicates, _entries

#: Classes whose drawn, tagged instances must be in the list (``piping-item-not-listed``).
MUST_LIST = ("SafetyValveOrFitting", "Silencer")


def must_list(item: DrawnItem) -> bool:
    return any(name in item.classes for name in MUST_LIST)


def drawn_piping_items(sheets: dict[str, tuple[Any, SheetIndex]]) -> dict[str, list[DrawnItem]]:
    """Every tagged piping component on the loaded sheets, by tag."""
    found: dict[str, list[DrawnItem]] = {}
    for name, (model, _) in sheets.items():
        for item in sheet_items(model, name):
            if item.kind == "piping":
                found.setdefault(item.tag, []).append(item)
    return found


def cross_check_piping_items(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, SheetIndex]],
    piping_list: Any,
    scope: Any = None,
) -> list[Finding]:
    """``cheme.piping-item-*``: the list against the tagged piping components drawn.

    *scope* (``validate._Scope``) holds back the not-on-pid findings of items whose sheet is
    planned or not loaded, as for the other lists.
    """
    list_path = workspace.list_file("piping_items")
    assert list_path is not None
    list_name = workspace.relative(list_path)
    items = list(piping_list.piping_items)
    entries = _entries(list_path, "piping_items", len(items))
    drawn = drawn_piping_items(sheets)
    tags = [item.tag.strip() for item in items]
    findings = _duplicates(list_name, "piping item", "cheme.piping-item-duplicate", tags, entries)
    for item, tag, entry in zip(items, tags, entries, strict=True):
        found = drawn.get(tag)
        if not found:
            missing = Finding(
                list_name,
                "warning",
                "cheme.piping-item-not-on-pid",
                f"{tag} is in the piping item list and no P&ID has a piping component "
                "with that tag (PipingComponentNumber / PositionNumber / PipingComponentName)",
                line=entry.line,
                ids=[tag],
                hint="draw it, fix the tag, or remove it from the list",
            )
            findings += [missing] if scope is None else scope.missing(missing, item.sheet)
            continue
        drawn_item = found[0]
        if item.type and not any(item.type in d.classes for d in found):
            findings.append(
                Finding(
                    list_name,
                    "warning",
                    "cheme.piping-item-type-mismatch",
                    f"{tag} is listed as {item.type} and drawn as {drawn_item.cls} "
                    f"({drawn_item.sheet})",
                    line=entry.line,
                    ids=[tag],
                    hint="use the DEXPI class the P&ID draws, or redraw the item",
                )
            )
        if item.line and not any((d.line or "") == item.line.strip() for d in found):
            where = ", ".join(f"{d.line or 'no line'} ({d.sheet})" for d in found)
            findings.append(
                Finding(
                    list_name,
                    "warning",
                    "cheme.piping-item-line-mismatch",
                    f"{tag} is listed on line {item.line} and drawn on {where}",
                    line=entry.line,
                    ids=[tag],
                    hint="fix the list's line, or the segment the item sits in",
                )
            )
    listed = set(tags)
    for tag in sorted(set(drawn) - listed):
        item = drawn[tag][0]
        if not must_list(item):
            continue
        index = sheets[item.sheet][1]
        findings.append(
            Finding(
                item.sheet,
                "warning",
                "cheme.piping-item-not-listed",
                f"{item.cls} {tag} ({item.id}) is on the P&ID and not in the piping item list",
                line=index.line(item.id),
                ids=[tag, item.id],
                hint=f"add it to {list_name} with its type, line and sheet",
            )
        )
    return findings
