"""Two revisions of a P&ID side by side, with what changed highlighted.

The change list comes from pyDEXPI's semantic diff (objects matched by id, which ``cheme fmt``
keeps stable). Each changed object is mapped to the drawing that shows it -- the object itself if
a RepresentationGroup represents it, else the nearest represented object around it -- and that
drawing's ``<g>`` is coloured: removed in the old pane, added in the new, modified in both.
"""

from __future__ import annotations

import difflib
import html
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lxml import etree

from chemeascode.domains.piping.render import load_model, render_svg


def git_show(root: Path, rev: str, path: str) -> bytes | None:
    """The bytes of *path* (relative to *root*) at *rev*, or ``None`` when it is not there.

    A *rev* starting with ``-`` is never passed to git (it would be read as an option).
    """
    if not rev or rev.startswith("-"):
        return None
    result = subprocess.run(
        ["git", "show", f"{rev}:./{path}"], cwd=root, capture_output=True, check=False
    )
    return result.stdout if result.returncode == 0 else None


def resolve_rev(root: Path, rev: str) -> str | None:
    """The commit sha *rev* names in the repository at *root*, or ``None`` when it names none."""
    if not rev or rev.startswith("-") or any(c in rev for c in "\0\r\n"):
        return None
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def sheets_at(root: Path, rev: str) -> list[str]:
    """The ``pid/*.xml`` and ``process/*.xml`` sheets (relative to *root*) committed at *rev*
    (a resolved sha)."""
    result = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", rev, "--", "pid", "process"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [
        name
        for name in result.stdout.splitlines()
        if name.startswith(("pid/", "process/")) and name.count("/") == 1 and name.endswith(".xml")
    ]


#: Objects that stand for the whole sheet or model. Nothing is drawn "for" them, so an ancestor
#: walk stops there instead of highlighting everything under them.
_CONTAINER_TYPES = (
    "Diagram.Diagram",
    "/PlantModel",
    "/ProcessModel",
    "/EngineeringModel",
    "/Plant",
)


def _is_container(element: etree._Element) -> bool:
    return element.get("type", "").endswith(_CONTAINER_TYPES)


def _represents(element: etree._Element) -> str | None:
    reference = element.find("References[@property='Represents']")
    if reference is None or not reference.get("objects"):
        return None
    return reference.get("objects").split()[0].lstrip("#")


def _sheet_drawings(root: etree._Element) -> dict[str, etree._Element]:
    """The diagram's own drawings by id: groups directly under a ``Diagram.Diagram`` that
    represent nothing (the title block Label, the Border). ``cheme render`` gives their
    ``<g>`` these ids (:func:`chemeascode.domains.piping.render.name_sheet_drawings`)."""
    found: dict[str, etree._Element] = {}
    for diagram in root.iter("Object"):
        if not diagram.get("type", "").endswith("Diagram.Diagram"):
            continue
        groups = [c for c in diagram if c.tag == "Object"]
        for components in diagram.findall("Components[@property='Groups']"):
            groups.extend(c for c in components if c.tag == "Object")
        for group in groups:
            if group.get("id") and _represents(group) is None:
                found[group.get("id")] = group
    return found


def _represented_by(root: etree._Element) -> tuple[set[str], dict[str, str]]:
    """Ids drawn by a RepresentationGroup, and every object id mapped to its nearest drawn one.

    The drawn ids are the ids the SVG export gives a ``<g>``. What a ``Diagram.Diagram``
    represents (the plant model) is not one of them: it is the whole sheet. The sheet's own
    drawings (title block, border) are drawn ids too, and an object whose attributes only they
    show (the plant metadata in the title block) maps to the drawing showing it. Other objects
    with no drawn object around them below the plant model (loop functions) map to nothing.
    """
    sheet_drawings = _sheet_drawings(root)
    sheet_targets = {
        target
        for element in root.iter("Object")
        if element.get("type", "").endswith("Diagram.Diagram")
        for target in [_represents(element)]
        if target
    }
    drawn = {
        target.lstrip("#")
        for reference in root.iter("References")
        if reference.get("property") == "Represents"
        for target in reference.get("objects", "").split()
    } - sheet_targets
    drawn |= set(sheet_drawings)
    owner: dict[str, str] = {}
    for element in root.iter("Object"):
        element_id = element.get("id")
        if not element_id or _is_container(element) or element_id in sheet_targets:
            continue
        if element_id in drawn:
            owner[element_id] = element_id
            continue
        # A RepresentationGroup stands for the object it represents.
        target = _represents(element)
        if target in drawn:
            owner[element_id] = target
            continue
        for ancestor in element.iterancestors("Object"):
            if _is_container(ancestor) or ancestor.get("id") in sheet_targets:
                break
            target = _represents(ancestor)
            if target in drawn:
                owner[element_id] = target
                break
            if ancestor.get("id") in drawn:
                owner[element_id] = ancestor.get("id")
                break
    # Objects shown only through a sheet drawing's text fields (AttributeRepresentation).
    for drawing_id, drawing in sheet_drawings.items():
        for reference in drawing.iter("References"):
            if reference.get("property") != "Object":
                continue
            for target in reference.get("objects", "").split():
                owner.setdefault(target.lstrip("#"), drawing_id)
    return drawn, owner


def _plant_item(
    element: etree._Element, by_id: dict[str, etree._Element], sheet_targets: set[str]
) -> str | None:
    """The id of the plant item *element* belongs to, or ``None``.

    A drawing element belongs to the item of the object its RepresentationGroup represents (the
    sheet's title block and frame to the plant model). A conceptual object belongs to the piping
    component it is part of (a valve, a tee), else to its line (piping network system), else to
    the top-level object it is part of (an equipment item, an instrument function, an actuating
    system).
    """
    chain = [element, *element.iterancestors("Object")]
    if any(c.get("type", "").endswith("Diagram.Diagram") for c in chain):
        for candidate in chain:
            target = _represents(candidate)
            if target is None:
                continue
            if target in sheet_targets:
                return target
            represented = by_id.get(target)
            return (
                _plant_item(represented, by_id, sheet_targets) if represented is not None else None
            )
        return None
    for candidate in chain:
        holder = candidate.getparent()
        if (
            holder is not None
            and holder.get("property") == "Items"
            and holder.getparent() is not None
            and holder.getparent().get("type", "").endswith("PipingNetworkSegment")
        ):
            return candidate.get("id")
    for candidate in chain:
        if candidate.get("type", "").endswith("PipingNetworkSystem"):
            return candidate.get("id")
    top = None
    for candidate in chain:
        if _is_container(candidate) or candidate.get("id") in sheet_targets:
            break
        top = candidate
    return top.get("id") if top is not None else None


def plant_items(root: etree._Element) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Every object id mapped to its plant item's id, and each plant item's class and tag."""
    from chemeascode.domains.piping.show import (
        TAG_PROPERTIES,
        data_value,
        instrument_tag,
        short_class,
    )

    by_id = {e.get("id"): e for e in root.iter("Object") if e.get("id")}
    sheet_targets = {
        target
        for element in root.iter("Object")
        if element.get("type", "").endswith("Diagram.Diagram")
        for target in [_represents(element)]
        if target
    }
    owner: dict[str, str] = {}
    info: dict[str, dict[str, str]] = {}
    for object_id, element in by_id.items():
        item = _plant_item(element, by_id, sheet_targets)
        if item is None or item not in by_id:
            continue
        owner[object_id] = item
        if item not in info:
            holder = by_id[item]
            tags = [instrument_tag(holder)] + [data_value(holder, p) for p in TAG_PROPERTIES]
            info[item] = {
                "class": short_class(holder),
                "tag": next((t for t in tags if t), ""),
            }
    return owner, info


@dataclass
class Change:
    kind: str  # added, removed, modified, moved
    object_type: str
    object_id: str
    tag: str | None
    domain: str
    detail: str = ""
    #: The id of the plant item the changed object belongs to (``""`` when none).
    item: str = ""


@dataclass
class SheetDiff:
    path: str
    old_rev: str
    new_rev: str
    changes: list[Change] = field(default_factory=list)
    old_svg: str = ""
    new_svg: str = ""
    old_highlight: dict[str, str] = field(default_factory=dict)
    new_highlight: dict[str, str] = field(default_factory=dict)
    projection_diff: str = ""
    #: The sheet exists on one side only: ``added`` or ``removed`` (``""`` when on both).
    status: str = ""
    #: Each changed object id mapped to the drawn id (a ``<g id>`` of that side's SVG) showing it.
    old_owner: dict[str, str] = field(default_factory=dict)
    new_owner: dict[str, str] = field(default_factory=dict)
    #: The plant items that ``Change.item`` names: id -> ``{"class", "tag"}``.
    items: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Why the sheet could not be compared or a side not drawn, ``; ``-separated (``""`` when
    #: all went well). A side that does not load leaves ``changes`` and ``projection_diff`` empty.
    error: str = ""


def _reason(failure: Exception) -> str:
    """*failure* on one line: ``XMLSyntaxError: Premature end of data ...``."""
    return f"{type(failure).__name__}: {failure}".splitlines()[0]


def diff_sheet(old: bytes | None, new: bytes | None, path: str, old_rev: str, new_rev: str):
    """Compare two revisions of one sheet (either may be absent).

    A side that does not load (malformed XML, a document pyDEXPI refuses) or does not draw is
    recorded in ``error`` instead of raised, so one broken sheet does not stop a multi-sheet diff.
    """
    from pydexpi.diff import id_diff

    from chemeascode.integrations.git import readable_projection

    result = SheetDiff(path, old_rev, new_rev)
    errors: list[str] = []
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    loaded: list[tuple[Any, Any]] = []
    for content, rev in ((old, old_rev), (new, new_rev)):
        if not content:
            loaded.append((None, None))
            continue
        try:
            loaded.append((load_model(content), etree.fromstring(content, parser)))
        except Exception as failure:  # noqa: BLE001 - whatever pyDEXPI or lxml raise for a broken document
            loaded.append((None, None))
            errors.append(f"cannot compare: {rev} does not load: {_reason(failure)}")
    (old_model, old_root), (new_model, new_root) = loaded
    unloaded = bool(errors)
    if bool(old) != bool(new):
        result.status = "added" if not old else "removed"
    old_owner = _represented_by(old_root)[1] if old_root is not None else {}
    new_owner = _represented_by(new_root)[1] if new_root is not None else {}

    if not unloaded and (old_model is not None or new_model is not None):
        if old_model is None or new_model is None:
            # A sheet on one side only: every object of it is added (or removed).
            present = new_model if old_model is None else old_model
            empty = type(present)()
            pair = (empty, present) if old_model is None else (present, empty)
            diff = id_diff(*pair)
            diff.added_objects = [e for e in diff.added_objects if e.object_id != empty.id]
            diff.removed_objects = [e for e in diff.removed_objects if e.object_id != empty.id]
            diff.modified_objects = []
            diff.moved_objects = []
        else:
            diff = id_diff(old_model, new_model)
        for entry in diff.added_objects:
            result.changes.append(
                Change("added", entry.object_type, entry.object_id, entry.tag, entry.domain)
            )
            if entry.object_id in new_owner:
                result.new_highlight[new_owner[entry.object_id]] = "added"
        for entry in diff.removed_objects:
            result.changes.append(
                Change("removed", entry.object_type, entry.object_id, entry.tag, entry.domain)
            )
            if entry.object_id in old_owner:
                result.old_highlight[old_owner[entry.object_id]] = "removed"
        for entry in diff.modified_objects:
            names = ", ".join(c.attribute_name for c in entry.changes)
            result.changes.append(
                Change(
                    "modified", entry.object_type, entry.object_id_2, entry.tag, entry.domain, names
                )
            )
            for owner, highlight in (
                (old_owner, result.old_highlight),
                (new_owner, result.new_highlight),
            ):
                target = owner.get(entry.object_id_2) or owner.get(entry.object_id_1)
                if target:
                    highlight.setdefault(target, "modified")
        for entry in diff.moved_objects:
            object_id = getattr(entry, "object_id", None) or entry.object_id_2
            result.changes.append(
                Change("moved", entry.object_type, object_id, entry.tag, entry.domain)
            )
            if object_id in new_owner:
                result.new_highlight.setdefault(new_owner[object_id], "modified")
        for change in result.changes:
            for owner, owners in ((old_owner, result.old_owner), (new_owner, result.new_owner)):
                if change.object_id in owner:
                    owners[change.object_id] = owner[change.object_id]
        old_items, old_info = plant_items(old_root) if old_root is not None else ({}, {})
        new_items, new_info = plant_items(new_root) if new_root is not None else ({}, {})
        for change in result.changes:
            sides = [(old_items, old_info), (new_items, new_info)]
            if change.kind != "removed":
                sides.reverse()
            for items, info in sides:
                if change.object_id in items:
                    change.item = items[change.object_id]
                    result.items[change.item] = dict(info[change.item])
                    break
        for change in result.changes:
            # The item's own change names its tag as pyDEXPI reads it; the header must agree.
            if change.item and change.object_id == change.item and change.tag:
                result.items[change.item]["tag"] = change.tag

    svgs = []
    for model, rev in ((old_model, old_rev), (new_model, new_rev)):
        try:
            svgs.append(render_svg(model) if model is not None and model.diagram else "")
        except Exception as failure:  # noqa: BLE001 - pyDEXPI's export of a drawing it cannot follow
            svgs.append("")
            errors.append(f"cannot draw {rev}: {_reason(failure)}")
    result.old_svg, result.new_svg = svgs
    result.error = "; ".join(errors)
    if unloaded:
        return result  # nothing to compare the loaded side's projection with

    old_text = readable_projection(old_model) if old_model else ""
    new_text = readable_projection(new_model) if new_model else ""
    result.projection_diff = "".join(
        difflib.unified_diff(
            old_text.splitlines(keepends=True),
            new_text.splitlines(keepends=True),
            f"{path}@{old_rev}",
            f"{path}@{new_rev}",
            n=2,
        )
    )
    return result


_COLOURS = {"added": "#1a9e3f", "removed": "#d0312d", "modified": "#e08a00"}


def _highlight_css(pane: str, highlight: dict[str, str]) -> str:
    rules = []
    for object_id, kind in sorted(highlight.items()):
        colour = _COLOURS[kind]
        selector = f'#{pane} [id="{html.escape(object_id, quote=True)}"]'
        rules.append(
            f"{selector} *{{stroke:{colour}!important;stroke-width:0.8!important}}"
            f"{selector} text{{fill:{colour}!important}}"
        )
    return "\n".join(rules)


def render_html(sheets: list[SheetDiff]) -> str:
    """A self-contained HTML page for one or more sheet diffs."""
    sections = []
    css = []
    for index, sheet in enumerate(sheets):
        old_pane, new_pane = f"old{index}", f"new{index}"
        css.append(_highlight_css(old_pane, sheet.old_highlight))
        css.append(_highlight_css(new_pane, sheet.new_highlight))
        counts = {k: sum(c.kind == k for c in sheet.changes) for k in _COLOURS | {"moved": ""}}
        rows = "".join(
            f"<tr class='{c.kind}'><td>{c.kind}</td><td>{html.escape(c.domain)}</td>"
            f"<td>{html.escape(c.object_type)}</td><td>{html.escape(c.tag or '')}</td>"
            f"<td><code>{html.escape(c.object_id)}</code></td>"
            f"<td>{html.escape(c.detail)}</td></tr>"
            for c in sorted(sheet.changes, key=lambda c: (c.domain != "conceptual", c.kind))
        )
        sections.append(
            f"""<section>
<h2>{html.escape(sheet.path)} <small>{html.escape(sheet.old_rev)} &rarr;
{html.escape(sheet.new_rev)}</small></h2>
{f'<p class="error">{html.escape(sheet.error)}</p>' if sheet.error else ""}
<p class="counts">{counts["added"]} added &middot; {counts["removed"]} removed &middot;
{counts["modified"]} modified &middot; {counts["moved"]} moved</p>
<div class="panes">
  <figure id="{old_pane}"><figcaption>{html.escape(sheet.old_rev)}</figcaption>
  {sheet.old_svg or '<p class="none">(not present)</p>'}</figure>
  <figure id="{new_pane}"><figcaption>{html.escape(sheet.new_rev)}</figcaption>
  {sheet.new_svg or '<p class="none">(not present)</p>'}</figure>
</div>
<details open><summary>Changes ({len(sheet.changes)})</summary>
<table><tr><th>change</th><th>domain</th><th>class</th><th>tag</th><th>id</th>
<th>attributes</th></tr>{rows}</table></details>
<details><summary>Review text (pyDEXPI projection)</summary>
<pre>{html.escape(sheet.projection_diff) or "(no difference)"}</pre></details>
</section>"""
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>P&amp;ID diff</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;margin:16px;color:#222;background:#fff}}
h2 small{{font-weight:normal;color:#666}}
.panes{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media (max-width:900px){{.panes{{grid-template-columns:1fr}}}}
figure{{margin:0;border:1px solid #ccc;overflow:auto;max-height:80vh;background:#fff}}
figcaption{{position:sticky;top:0;background:#f4f4f4;padding:4px 8px;font-weight:600}}
figure svg{{width:100%;height:auto}}
table{{border-collapse:collapse;width:100%;margin-top:8px}}
td,th{{border-bottom:1px solid #eee;padding:3px 6px;text-align:left;vertical-align:top}}
tr.added td:first-child{{color:{_COLOURS["added"]}}}
tr.removed td:first-child{{color:{_COLOURS["removed"]}}}
tr.modified td:first-child,tr.moved td:first-child{{color:{_COLOURS["modified"]}}}
pre{{background:#f7f7f7;padding:8px;overflow:auto;max-height:60vh}}
.none{{padding:16px;color:#888}}
.error{{color:{_COLOURS["removed"]};font-weight:600}}
{"".join(css)}
</style></head><body>
<h1>P&amp;ID diff</h1>
<p>Green: added &middot; red: removed &middot; orange: modified.</p>
{"".join(sections)}
</body></html>
"""
