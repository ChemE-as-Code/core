"""``control/cause-effect.yaml``: interlocks against the lists and sheets, and the C&E matrix.

Each interlock names a cause (an instrument tag and its condition) and its effects (a tag and an
action each). ``cheme validate`` reports

- ``cheme.interlock-unknown-tag``: a cause or effect tag, or a tag of the ``logic``, that no
  list holds and no sheet draws (equipment, instrument, piping item or line);
- ``cheme.instrument-no-interlock``: a trip instrument in no interlock, neither as its cause
  nor in its ``logic`` (a voter of a 2oo3 counts) -- an instrument whose function letters hold
  ``HH`` or ``LL`` (``TSHH``, ``LALL``), or whose instrument-list notes say it trips something.
  Info up to the concept stage, a warning from the ``basic`` stage on (by ``plant.yaml`` stage
  order);
- ``cheme.interlock-duplicate``: an id listed twice;
- ``cheme.interlock-duplicate-effect`` (warning): one interlock with two effects on one tag.

``cheme cause-effect`` writes the matrix (causes as rows, effect tags as columns, the action
in each cell; the actions of two effects on one tag joined as ``close + alarm``, in the order
given) to ``build/cause-effect.html`` and ``.csv``; ``GET /api/interlocks`` returns it.
"""

from __future__ import annotations

import csv
import html
import io
import re
from pathlib import Path
from typing import Any

from chemeascode.domains.piping.sheet_index import SheetIndex
from chemeascode.domains.piping.sheet_query import sheet_items
from chemeascode.foundation.findings import Finding, Level
from chemeascode.foundation.workspace import Workspace
from chemeascode.foundation.yamlsource import _duplicates, _entries, _yaml_line

_TRIP_NOTE = re.compile(r"\btrip(s|ped|ping)?\b|\bstops?\b|\bshuts? ?down\b", re.IGNORECASE)


def is_trip_tag(tag: str) -> bool:
    """Whether the printed instrument tag's letters say high-high or low-low (TSLL-4114)."""
    letters = tag.split("-", 1)[0] if "-" in tag else re.split(r"\d", tag, maxsplit=1)[0]
    return "HH" in letters[1:] or "LL" in letters[1:]


def stage_level(workspace: Workspace) -> Level:
    """``warning`` from the ``basic`` stage on, else ``info``."""
    config = workspace.config()
    ids = [s.id for s in config.stages]
    if "basic" in ids and config.stage in ids and ids.index(config.stage) >= ids.index("basic"):
        return "warning"
    return "info"


def known_tags(sheets: dict[str, tuple[Any, SheetIndex]], parsed: dict[str, Any]) -> dict[str, str]:
    """Every tag a list holds or a sheet draws, with where it comes from."""
    found: dict[str, str] = {}
    for name, (model, _) in sheets.items():
        for item in sheet_items(model, name):
            found.setdefault(item.tag, name)
    for kind, key, attribute in (
        ("equipment", "equipment", "tag"),
        ("instruments", "instruments", "tag"),
        ("piping_items", "piping_items", "tag"),
        ("lines", "lines", "number"),
    ):
        model = parsed.get(kind)
        for entry in getattr(model, key, None) or []:
            found.setdefault(str(getattr(entry, attribute)).strip(), kind)
    return found


def cross_check_interlocks(
    workspace: Workspace,
    sheets: dict[str, tuple[Any, SheetIndex]],
    parsed: dict[str, Any],
    partial: bool = False,
) -> list[Finding]:
    """The ``cheme.interlock-*`` and ``instrument-no-interlock`` findings.

    Without ``control/cause-effect.yaml`` only ``instrument-no-interlock`` can fire: a plant
    with trip instruments is asked for the file.
    """
    from chemeascode.domains.control.register import walk
    from chemeascode.foundation.workspace import LIST_FILES
    from chemeascode.foundation.yamlsource import _compose

    path = workspace.list_file("interlocks")
    name = workspace.relative(path) if path is not None else LIST_FILES["interlocks"]
    model = parsed.get("interlocks")
    interlocks = list(model.interlocks) if model is not None else []
    findings: list[Finding] = []
    if path is not None and model is not None:
        entries = _entries(path, "interlocks", len(interlocks))
        document = _compose(path)
        findings = _duplicates(
            name, "interlock", "cheme.interlock-duplicate", [i.id for i in interlocks], entries
        )
    tags = known_tags(sheets, parsed)
    if not partial and interlocks:
        for position, interlock in enumerate(interlocks):
            effects: dict[str, list[int]] = {}
            for i, effect in enumerate(interlock.effects):
                effects.setdefault(effect.tag, []).append(i)
            for tag, at in effects.items():
                if len(at) < 2:
                    continue
                actions = [interlock.effects[i].action for i in at]
                shown = " + ".join(dict.fromkeys(actions))
                what = (
                    f"is listed {len(at)} times with action {actions[0]}; the matrix shows it once"
                    if len(set(actions)) == 1
                    else f"has {len(at)} effects ({', '.join(actions)}); the matrix shows "
                    f"{shown} in its cell"
                )
                loc = ("interlocks", position, "effects", at[1], "tag")
                findings.append(
                    Finding(
                        name,
                        "warning",
                        "cheme.interlock-duplicate-effect",
                        f"interlock {interlock.id}: {tag} {what}",
                        line=_yaml_line(document, loc) or entries[position].line,
                        ids=[interlock.id, tag],
                        hint="give each tag one effect, the action the interlock takes on it "
                        "(an alarm on the alarm's own tag)",
                    )
                )
            ends = [("cause", interlock.cause.tag, ("interlocks", position, "cause", "tag"))]
            ends += [
                ("effect", effect.tag, ("interlocks", position, "effects", i, "tag"))
                for i, effect in enumerate(interlock.effects)
            ]
            ends += [
                ("logic", item.tag, ("interlocks", position, "logic", *where, "tag"))
                for item, where in walk(interlock.logic)
                if item.tag
            ]
            for role, tag, loc in ends:
                if tag.strip() in tags:
                    continue
                findings.append(
                    Finding(
                        name,
                        "warning",
                        "cheme.interlock-unknown-tag",
                        f"interlock {interlock.id}: {role} {tag} is in no list and on no sheet",
                        line=_yaml_line(document, loc) or entries[position].line,
                        ids=[interlock.id, tag],
                        hint="fix the tag (as printed on the P&ID), or draw / list the item",
                    )
                )
    covered = {interlock.cause.tag.strip() for interlock in interlocks}
    covered |= {
        item.tag.strip()
        for interlock in interlocks
        for item, _ in walk(interlock.logic)
        if item.tag
    }
    level = stage_level(workspace)
    instruments = parsed.get("instruments")
    candidates: dict[str, tuple[str, int | None, str]] = {}
    if instruments is not None:
        list_path = workspace.list_file("instruments")
        assert list_path is not None
        list_name = workspace.relative(list_path)
        list_entries = _entries(list_path, "instruments", len(instruments.instruments))
        for entry, where in zip(instruments.instruments, list_entries, strict=True):
            tag = entry.tag.strip()
            if is_trip_tag(tag):
                candidates.setdefault(tag, (list_name, where.line, "a high-high / low-low switch"))
            elif _TRIP_NOTE.search(entry.notes or ""):
                why = "its notes say it trips something"
                candidates.setdefault(tag, (list_name, where.line, why))
    for sheet, (sheet_model, index) in sheets.items():
        for item in sheet_items(sheet_model, sheet):
            if item.kind == "instrument" and is_trip_tag(item.tag):
                candidates.setdefault(
                    item.tag, (sheet, index.line(item.id), "a high-high / low-low switch")
                )
    for tag, (file, line, why) in sorted(candidates.items()):
        if tag in covered:
            continue
        findings.append(
            Finding(
                file,
                level,
                "cheme.instrument-no-interlock",
                f"{tag} ({why}) is in no interlock of {name}, as its cause or in its logic"
                + ("" if path is not None else " (the plant has no such file)"),
                line=line,
                ids=[tag],
                hint=f"add an interlock (cause {tag}, its effects) to {name}"
                + ("" if path is not None else " (schema: cheme schema interlocks)")
                + "; on the sheet refer to it ('see C&E I-..') instead of spelling out the trip",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


def matrix(model: Any) -> dict[str, Any]:
    """Causes as rows, effect tags as columns, each cell the action (or empty). Two effects
    of one interlock on one tag share the cell: their actions joined by `` + `` in the order
    given (``close + alarm``), never one of them dropped."""
    interlocks = list(model.interlocks) if model is not None else []
    columns: list[str] = []
    for interlock in interlocks:
        for effect in interlock.effects:
            if effect.tag not in columns:
                columns.append(effect.tag)
    rows = []
    for interlock in interlocks:
        cells: dict[str, list[str]] = {}
        for effect in interlock.effects:
            actions = cells.setdefault(effect.tag, [])
            if effect.action not in actions:
                actions.append(effect.action)
        rows.append(
            {
                "id": interlock.id,
                "title": interlock.title,
                "cause": interlock.cause.tag,
                "condition": interlock.cause.condition,
                "sheet": interlock.sheet,
                "sil": interlock.sil,
                "cells": [" + ".join(cells.get(column, [])) for column in columns],
            }
        )
    return {"columns": columns, "rows": rows}


def to_csv(table: dict[str, Any]) -> str:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", "cause", "condition", "sheet", "sil", *table["columns"]])
    for row in table["rows"]:
        writer.writerow(
            [
                row["id"],
                row["cause"],
                row["condition"],
                row["sheet"] or "",
                "" if row["sil"] is None else row["sil"],
                *row["cells"],
            ]
        )
    return out.getvalue()


def to_html(table: dict[str, Any], title: str) -> str:
    esc = html.escape
    head = "".join(f"<th class=v><div>{esc(c)}</div></th>" for c in table["columns"])
    body = []
    for row in table["rows"]:
        cells = "".join(
            f'<td class="{esc(c.replace(" + ", " ")) or "none"}">{esc(c)}</td>'
            for c in row["cells"]
        )
        cause = f"{esc(row['cause'])} {esc(row['condition'])}".strip()
        sil = "" if row["sil"] is None else str(row["sil"])  # SIL 0 is a screening result
        body.append(
            f"<tr><th>{esc(row['id'])}</th><td>{cause}</td><td>{esc(row['title'])}</td>"
            f"<td>{esc(row['sheet'] or '')}</td><td>{esc(sil)}</td>{cells}</tr>"
        )
    return (
        "<!doctype html><meta charset=utf-8>"
        f"<title>{esc(title)}</title>"
        "<style>body{font:13px system-ui,sans-serif;margin:16px}table{border-collapse:collapse}"
        "td,th{border:1px solid #bbb;padding:3px 6px;text-align:left}"
        "th.v{height:120px;vertical-align:bottom}th.v div{writing-mode:vertical-rl;"
        "transform:rotate(180deg)}td.trip,td.stop,td.close,td.depressurize{background:#fdd}"
        "td.open,td.start{background:#dfd}td.alarm{background:#ffd}</style>"
        f"<h1>{esc(title)}</h1><table><tr><th>id</th><th>cause</th><th>title</th><th>sheet</th>"
        f"<th>SIL</th>{head}</tr>{''.join(body)}</table>"
    )


def write_matrix(workspace: Workspace, model: Any, out: Path | None = None) -> list[Path]:
    """Write ``build/cause-effect.html`` and ``.csv`` (or *out* and its ``.csv`` sibling)."""
    table = matrix(model)
    html_path = out or workspace.build_dir() / "cause-effect.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = html_path.with_suffix(".csv")
    title = f"Cause and effect: {workspace.config().name}"
    html_path.write_text(to_html(table, title), encoding="utf-8")
    csv_path.write_text(to_csv(table), encoding="utf-8")
    return [html_path, csv_path]
