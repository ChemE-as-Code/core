"""``cheme layout pin``: copy a generated route, platform, stair or ladder into the intent
files.

A pinned route goes to ``piping/routing.yaml`` as ``{line, segment, route}`` (one entry per DEXPI
segment; an entry for the same line and segment is replaced); a pinned platform goes to the
item's placement in ``layout/equipment-placement.yaml`` as ``access: {platforms, ladder_side}``
(the item's existing ``access`` is replaced by the old platforms plus the pinned ones); a
proposed stair or ladder of a structure (``S/stair-to-L``, ``S/ladder-to-L``) goes to that
structure's ``stairs`` or ``ladders`` in ``layout/structures.yaml``, a platform proposed outside
a casing (``S/L-out``) to its ``levels`` (pin it before the stairs and ladders that reach it);
a proposed rack ladder (``RACK/ladder-start|end``) to the rack's ``ladders`` in
``layout/site-plan.yaml`` (with its declared ladders, the rack gets no more proposals); a
proposed wall opening of a pipe penetration (``OWNER/LINE``) to the building's ``openings`` in
``layout/building.yaml`` or the structure's ``enclosure: openings`` in
``layout/structures.yaml`` (the walls are then cut around it); proposed support steel under a
pipe (``PIPE/SP-<arc>``) to ``pipe_supports`` in ``layout/structures.yaml``; a proposed valve
access platform (``VP-<valve tag>``) as a structure of its own (with its ladder or stair and
the valves it ``serves``) to ``structures`` there. Pinned objects keep the id they had when
pinned: an older ``PIPE/post-N`` or ``VP-N`` stays valid as a declared id.

The files are edited as text at the spans the YAML parser reports, so comments and the rest of
the file stay as they are (block or flow style), except comments inside a replaced value (a
route entry, an item's ``access``); the edited text is written only when it is a valid file of
its schema whose data is the old data with the pinned entry where it belongs (a replaced route
entry keeps its ``gravity``, ``buried`` and ``notes``), and an id the structure already declares is
refused. The next ``layout build`` takes the pinned
objects as declared (``source: pinned`` for routes, ``declared`` for platforms).
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.workspace import LAYOUT_FILES

ROUTING_HEADER = (
    "# Routing intent. Schema: `cheme schema routing`. Routes pinned by `cheme layout\n"
    "# pin` are kept as they are by `cheme layout build`.\n"
)


class PinError(Exception):
    """Nothing to pin, or the target file cannot be edited."""


@dataclass
class Pinned:
    file: str
    what: list[str] = field(default_factory=list)


def _num(value: float) -> str:
    text = f"{round(value, 3):.3f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _flow(value: Any) -> str:
    """*value* as one line of YAML flow style."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {_flow(v)}" for k, v in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_flow(v) for v in value) + "]"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return _num(float(value))
    if value is None:
        return "null"
    text = str(value)
    plain = (
        text
        and all(c.isalnum() or c in "-_./" for c in text)
        and not text[0].isdigit()
        and text.lower() not in _YAML_WORDS
    )
    # a JSON string is a YAML double-quoted scalar with every escape (backslashes, newlines)
    return text if plain else json.dumps(text, ensure_ascii=False)


#: Plain words YAML reads as something other than a string.
_YAML_WORDS = {"true", "false", "yes", "no", "on", "off", "null", "y", "n", "nan", "inf"}


def _mapping_value(node: Any, key: str) -> tuple[Any, Any] | None:
    for k, v in node.value:
        if getattr(k, "value", None) == key:
            return k, v
    return None


def _splice(text: str, start: int, end: int, new: str) -> str:
    return text[:start] + new + text[end:]


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _content_end(node: Any, splice: bool = True) -> int:
    """The index just after the last character of *node*'s own text. PyYAML ends a block
    collection at the next token (the next key or item, after the indentation and any comments
    before it), so its end is taken from its last child instead. A block scalar's text ends
    with its newline (and, with ``|+``/``>+``, its kept blank lines); with *splice* the end is
    before that last newline, so text spliced in up to it still ends its line."""
    if isinstance(node, yaml.MappingNode) and not node.flow_style and node.value:
        return _content_end(node.value[-1][1], splice)
    if isinstance(node, yaml.SequenceNode) and not node.flow_style and node.value:
        return _content_end(node.value[-1], splice)
    block = isinstance(node, yaml.ScalarNode) and node.style in ("|", ">")
    if splice and block and node.end_mark.column == 0:
        return node.end_mark.index - 1
    return node.end_mark.index


def _line_end(text: str, index: int) -> int:
    """The index of the newline ending the line that holds the character before *index* (the
    last character of a node's content; a block scalar's content ends with its newline), or
    the end of the text."""
    end = text.find("\n", max(index - 1, 0))
    return len(text) if end < 0 else end


def _after_line(text: str, node: Any, line: str) -> str:
    """*text* with *line* (indentation included) on a new line after the last line of
    *node*'s content (a trailing comment on that line stays on it)."""
    # after a block scalar's kept blank lines: a line before them would drop them
    end = _line_end(text, _content_end(node, splice=False))
    return text[:end] + "\n" + line + text[end:]


def _replace_value(text: str, value: Any, new: str) -> str:
    """*text* with the value node *value* of a mapping key replaced by *new* (inserted after
    the colon when the value is empty)."""
    start, end = value.start_mark.index, _content_end(value)
    if start == end:  # nothing after the colon
        return _splice(text, start, start, f" {new}")
    return _splice(text, start, end, new)


def _append_item(text: str, root: Any, key: str, entry: str) -> str:
    """Append ``- entry`` to the block sequence under *key* of the document *root* (created
    when missing or empty)."""
    found = _mapping_value(root, key) if root is not None else None
    if found is None:
        sep = "" if not text or text.endswith("\n") else "\n"
        return text + f"{sep}{key}:\n  - {entry}\n"
    k, seq = found
    if not isinstance(seq, yaml.SequenceNode) or not seq.value:
        return _splice(text, k.start_mark.index, _content_end(seq), f"{key}:\n  - {entry}")
    if seq.flow_style:
        at = _content_end(seq.value[-1])
        return _splice(text, at, at, f", {entry}")
    indent = seq.value[-1].start_mark.column - 2
    return _after_line(text, seq, " " * indent + f"- {entry}")


def _save(
    path: Path,
    old: str,
    new: str,
    kind: str,
    expect: Callable[[Any], Any] | None = None,
    write: bool = True,
) -> None:
    """Write *new* to *path* if it is a valid layout file of *kind* (its schema, not only YAML)
    and, with *expect*, holds exactly what *expect* makes of the data of *old* (the pinned entry
    where it belongs and nothing else changed); else raise :class:`PinError`, writing nothing.
    Without *write*, only check."""
    from chemeascode.domains.spatial.layout_validate import parse

    name = LAYOUT_FILES[kind]
    findings, valid, _ = parse(new, kind, name)
    if valid is None:
        first = findings[0] if findings else None
        why = f": {first.message}" + (f" (line {first.line})" if first and first.line else "")
        raise PinError(f"pinning would leave {name} invalid{why if first else ''}; nothing written")
    if expect is not None:
        wanted = expect(copy.deepcopy(yaml.safe_load(old) or {}))
        if yaml.safe_load(new) != wanted:
            raise PinError(
                f"could not place the pinned entry in {name} as text (unusual layout of the "
                "file?); nothing written: add it by hand"
            )
    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new, encoding="utf-8")


def _entry_of(data: dict[str, Any], section: str, ident: str) -> dict[str, Any]:
    """The entry of the list *section* of a layout file's *data* with ``id`` (or ``tag``)
    *ident*."""
    found = next(
        (
            e
            for e in data.get(section) or []
            if isinstance(e, dict) and ident in (e.get("id"), e.get("tag"))
        ),
        None,
    )
    if found is None:
        raise PinError(f"{ident} is not in the {section} of the file; nothing written")
    return found


#: Keys of a routing entry a pinned route keeps (the route replaces the others: rack, tier,
#: via, elevation and skip only steer the router).
ROUTE_KEEPS = ("gravity", "buried", "notes")


def _route_edit(
    text: str, model: dict[str, Any], target: str
) -> tuple[str, list[str], Callable[[Any], Any]]:
    """*text* (``piping/routing.yaml``) with the routes of line *target* or pipe *target*
    pinned, what was pinned, and what the edit must make of the file's data."""
    pipes = [p for p in model.get("pipes", []) if target in (p["line"], p["id"])]
    if not pipes:
        raise PinError(f"no routed pipe or line {target} in the model")
    what: list[str] = []
    placed: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    # a segment id the line repeats on another sheet is pinned by its pipe id
    # (<sheet stem>/<DEXPI id>), so the pin applies to that sheet's segment only
    sheets_of: dict[tuple[str, str], int] = {}
    for p in model.get("pipes", []):
        sheets_of[(p["line"], p["segment"])] = sheets_of.get((p["line"], p["segment"]), 0) + 1

    def matches(entry: Any, line: str, same: tuple[Any, ...]) -> bool:
        return (
            isinstance(entry, dict)
            and entry.get("line") == line
            and entry.get("segment") is not None
            and str(entry.get("segment")) in {str(s) for s in same if s is not None}
        )

    for pipe in pipes:
        shared = sheets_of.get((pipe["line"], pipe["segment"]), 0) > 1
        segment = pipe["id"] if shared else pipe["segment"]
        # an entry naming the segment by its pipe id (with the sheet) is the same pin
        same = (segment,) if shared else (segment, pipe["id"], pipe.get("segment_number"))
        entry: dict[str, Any] = {
            "line": pipe["line"],
            "segment": segment,
            "route": [[round(c, 3) for c in p] for p in pipe["points"]],
        }
        data = yaml.safe_load(text) if text.strip() else None
        lines = data.get("lines") if isinstance(data, dict) else None
        old = next((e for e in lines or [] if matches(e, pipe["line"], same)), None)
        if old is not None:
            entry |= {k: old[k] for k in ROUTE_KEEPS if k in old}
        flow = _flow(entry)
        document = yaml.compose(text) if text.strip() else None
        replaced = False
        found = _mapping_value(document, "lines") if document is not None else None
        if found is not None and isinstance(found[1], yaml.SequenceNode):
            for item in found[1].value:
                if not isinstance(item, yaml.MappingNode):
                    continue
                values = {k.value: getattr(v, "value", None) for k, v in item.value}
                # matched as matches() does: a line-wide entry (no segment) is not this pin
                if matches(values, pipe["line"], same):
                    text = _splice(text, item.start_mark.index, _content_end(item), flow)
                    replaced = True
                    break
        if not replaced:
            text = _append_item(text, document, "lines", flow)
        placed.append((pipe["line"], same, entry))
        what.append(f"{pipe['line']} {segment}")

    def expect(data: Any) -> Any:
        if not isinstance(data, dict):
            data = {}
        lines = data["lines"] = list(data.get("lines") or [])
        for line, same, entry in placed:
            at = next((i for i, e in enumerate(lines) if matches(e, line, same)), None)
            if at is None:
                lines.append(entry)
            else:
                lines[at] = entry
        return data

    return text, what, expect


def pin_routes(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Pin the routes of line *target* (every routed segment) or of the pipe with id *target*."""
    name = LAYOUT_FILES["routing"]
    path = root / name
    text = path.read_text(encoding="utf-8") if path.is_file() else ROUTING_HEADER
    new, what, expect = _route_edit(text, model, target)
    _save(path, text, new, "routing", expect)
    return Pinned(name, what)


def pin_platforms(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Pin the proposed platform *target* (``TAG/platform-N``) or every platform of tag
    *target* into the item's placement ``access``."""
    platforms = [p for p in model.get("platforms", []) if target in (p["id"], p["tag"])]
    if not platforms:
        raise PinError(f"no platform {target} in the model")
    tag = platforms[0]["tag"]
    item = next((e for e in model.get("equipment", []) if e["tag"] == tag), None)
    if item is None:
        raise PinError(f"{tag} is not in the model")
    name = LAYOUT_FILES["placement"]
    path = root / name
    if not path.is_file():
        raise PinError(f"no {name}")
    text = path.read_text(encoding="utf-8")
    document = yaml.compose(text)
    found = _mapping_value(document, "equipment") if document is not None else None
    node = None
    for entry in found[1].value if found is not None else []:
        values = {k.value: getattr(v, "value", None) for k, v in entry.value}
        if values.get("tag") == tag:
            node = entry
            break
    if node is None:
        raise PinError(f"{tag} has no placement in {name}")
    rotation = item["rotation_deg"]
    every = [p for p in model.get("platforms", []) if p["tag"] == tag]
    keep = [p for p in every if p["source"] != "generated" or p in platforms]
    listed = []
    for platform in sorted(keep, key=lambda p: p["item_elevation"]):
        entry: dict[str, Any] = {"elevation": round(platform["item_elevation"], 3)}
        if platform.get("arc_deg"):
            a, b = platform["arc_deg"]
            entry["arc_deg"] = [round((a - rotation) % 360, 1), round((b - rotation) % 360, 1)]
        if abs(platform["width"] - 1.0) > 1e-6:
            entry["width"] = platform["width"]
        listed.append(entry)
    data: dict[str, Any] = {"platforms": listed}
    if len(listed) == 1:
        # one platform: its ladder's side; with more, each ladder stands where the build
        # puts it (an upper one on the platform below), as for the proposals
        base = keep[0]["ladder"]["base"]
        x, y, _ = item["position"]
        side = (math.degrees(math.atan2(base[1] - y, base[0] - x)) - rotation) % 360
        data["ladder_side"] = round(side, 1)
    # the other keys of a declared access (notes) stay
    before = _entry_of(yaml.safe_load(text) or {}, "equipment", tag).get("access")
    if isinstance(before, dict):
        data |= {k: v for k, v in before.items() if k not in ("platforms", "ladder_side")}
    access = _flow(data)
    original = text
    old = _mapping_value(node, "access")
    if old is not None:
        text = _replace_value(text, old[1], access)
    elif node.flow_style:
        at = _content_end(node.value[-1][1])
        text = _splice(text, at, at, f", access: {access}")
    else:
        indent = node.value[0][0].start_mark.column
        text = _after_line(text, node, " " * indent + f"access: {access}")

    def expect(old_data: Any) -> Any:
        _entry_of(old_data, "equipment", tag)["access"] = data
        return old_data

    _save(path, original, text, "placement", expect)
    return Pinned(name, [p["id"] for p in platforms])


def _append_nested(text: str, node: Any, key: str, entry: str) -> str:
    """Append ``entry`` to the sequence under *key* of the mapping *node* (block or flow
    style), creating the key when it is missing or empty."""
    found = _mapping_value(node, key)
    if found is not None and isinstance(found[1], yaml.SequenceNode) and found[1].value:
        seq = found[1]
        if seq.flow_style:
            at = _content_end(seq.value[-1])
            return _splice(text, at, at, f", {entry}")
        indent = seq.value[-1].start_mark.column - 2
        return _after_line(text, seq, " " * indent + f"- {entry}")
    if found is not None:  # [] or nothing
        return _replace_value(text, found[1], f"[{entry}]")
    if node.flow_style:
        if not node.value:
            inner = node.end_mark.index - 1
            return _splice(text, inner, inner, f"{key}: [{entry}]")
        at = _content_end(node.value[-1][1])
        return _splice(text, at, at, f", {key}: [{entry}]")
    column = node.value[0][0].start_mark.column
    return _after_line(text, node, " " * column + f"{key}: [{entry}]")


def _entry_node(text: str, key: str, ident: str) -> Any:
    document = yaml.compose(text)
    found = _mapping_value(document, key) if document is not None else None
    for entry in found[1].value if found is not None else []:
        values = {k.value: getattr(v, "value", None) for k, v in entry.value}
        if values.get("id") == ident:
            return entry
    return None


def access_ids(model: dict[str, Any]) -> dict[str, tuple[str, str, dict[str, Any]]]:
    """Every proposed stair and ladder of the structures and racks: id -> (owner kind, owner
    id, entry)."""
    found = {}
    for structure in model.get("structures", []):
        if structure.get("source") == "generated":
            continue  # a proposed structure is pinned as a whole (pin_structure)
        for level in structure.get("levels", []):
            if level.get("source") == "generated":
                found[f"{structure['id']}/{level['id']}"] = ("structure", structure["id"], level)
        for kind in ("stairs", "ladders"):
            for entry in structure.get(kind, []):
                if entry.get("source") == "generated":
                    found[entry["id"]] = ("structure", structure["id"], entry)
    for rack in model.get("racks", []):
        for entry in rack.get("ladders", []):
            if entry.get("source") == "generated":
                found[entry["id"]] = ("rack", rack["id"], entry)
    return found


def pin_access(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Pin the proposed stair or ladder *target* into ``layout/structures.yaml`` (a
    structure's) or ``layout/site-plan.yaml`` (a rack's)."""
    owner_kind, owner, entry = access_ids(model)[target]
    local = target.split("/", 1)[1]
    if owner_kind == "rack":
        name = LAYOUT_FILES["site_plan"]
        key, section = "ladders", "racks"
        rack = next(r for r in model["racks"] if r["id"] == owner)
        kept = [
            {"id": e["id"].split("/", 1)[1], "end": e["end"]}
            for e in rack.get("ladders", [])
            if e["source"] != "generated" or e["id"] == target
        ]
        flow = _flow(kept[-1])
    else:
        name = LAYOUT_FILES["structures"]
        section = "structures"
        if "elevation" in entry:
            key = "levels"
            data = {
                "id": local,
                "title": entry.get("title", ""),
                "elevation": entry["elevation"],
                "kind": entry.get("kind", "platform"),
                "extent": [round(c, 3) for c in entry["extent"]],
            }
        elif "flights" in entry:
            key = "stairs"
            data = {
                "id": local,
                "from": entry["from"],
                "to": entry["to"],
                "side": entry["side"],
                "offset": entry.get("offset", 0.0),
                "width": entry["width"],
                **({"out": entry["out"]} if entry.get("out") else {}),
            }
        else:
            key = "ladders"
            data = {
                "id": local,
                "from": entry["from"],
                "to": entry["to"],
                "at": [round(c, 3) for c in entry["at"]],
                "facing": entry["facing"],
            }
        flow = _flow(data)
    path = root / name
    if not path.is_file():
        raise PinError(f"no {name}")
    text = path.read_text(encoding="utf-8")
    node = _entry_node(text, section, owner)
    if node is None:
        raise PinError(f"{owner} is not in {name}")
    original = text
    if owner_kind == "rack":
        old = _mapping_value(node, "ladders")
        listed = "[" + ", ".join(_flow(k) for k in kept) + "]"
        if old is not None:
            text = _replace_value(text, old[1], listed)
        else:
            text = _append_nested(text, node, "ladders", flow)
            if len(kept) > 1:
                node = _entry_node(text, section, owner)
                old = _mapping_value(node, "ladders")
                text = _replace_value(text, old[1], listed)

        def expect(data: Any) -> Any:
            _entry_of(data, section, owner)["ladders"] = kept
            return data

    else:
        declared = yaml.safe_load(text) or {}
        listed_ids = {
            way.get("id")
            for kind in ("stairs", "ladders", "levels")
            for way in _entry_of(declared, section, owner).get(kind) or []
        }
        if local in listed_ids:
            raise PinError(f"{owner} already declares {local} in {name}; nothing written")
        text = _append_nested(text, node, key, flow)

        def expect(data: Any) -> Any:
            entry = _entry_of(data, section, owner)
            entry[key] = [*(entry.get(key) or []), yaml.safe_load(flow)]
            return data

    _save(path, original, text, "site_plan" if owner_kind == "rack" else "structures", expect)
    return Pinned(name, [target])


def pin_penetration(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Declare the opening the penetration *target* (``OWNER/LINE``) proposes: in its
    building's ``openings`` (``layout/building.yaml``) or its structure's ``enclosure:
    openings`` (``layout/structures.yaml``)."""
    pen = next(p for p in model.get("penetrations", []) if p["id"] == target)
    owner = pen["owner"]
    if pen["opening"]["side"] == "roof":
        raise PinError(
            f"{target} is a roof penetration: a roof opening cannot be declared; route the "
            f"line into {owner} through a wall (via points) and pin that opening"
        )
    local = target.split("/", 1)[1]
    flow = _flow({"id": local, **pen["opening"]})
    building = any(b["id"] == owner for b in model.get("buildings", []))
    name = LAYOUT_FILES["building" if building else "structures"]
    path = root / name
    if not path.is_file():
        raise PinError(f"no {name}")
    text = path.read_text(encoding="utf-8")
    node = _entry_node(text, "buildings" if building else "structures", owner)
    if node is None:
        raise PinError(f"{owner} is not in {name}")
    if not building:
        found = _mapping_value(node, "enclosure")
        if found is None or not isinstance(found[1], yaml.MappingNode):
            raise PinError(f"{owner} has no enclosure in {name}")
        node = found[1]
    original = text
    text = _append_nested(text, node, "openings", flow)

    def expect(data: Any) -> Any:
        entry = _entry_of(data, "buildings" if building else "structures", owner)
        holder = entry if building else entry["enclosure"]
        holder["openings"] = [*(holder.get("openings") or []), yaml.safe_load(flow)]
        return data

    _save(path, original, text, "building" if building else "structures", expect)
    return Pinned(name, [target])


STRUCTURES_HEADER = "# Steel structures. Schema: `cheme schema structures`.\n"


def pin_support(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Declare the proposed support steel *target* (``PIPE/SP-<arc>``) in ``pipe_supports`` of
    ``layout/structures.yaml`` (created when missing)."""
    entry = next(s for s in model.get("support_steel", []) if s["id"] == target)
    data: dict[str, Any] = {
        "id": entry["id"],
        "kind": entry["kind"],
        "at": [round(c, 3) for c in entry["at"]],
        "top": entry["top"],
        "from": "steel" if entry["kind"] == "stub" else "grade",
    }
    if entry["kind"] == "stub":
        data["base"] = entry["base"]
    if entry["kind"] == "t_post":
        data["width"] = entry["width"]
    data["rotation_deg"] = entry["rotation_deg"]
    data["serves"] = list(entry.get("serves", []))
    data["notes"] = "pinned proposal (ASSUMED: check the support with the stress engineer)"
    name = LAYOUT_FILES["structures"]
    path = root / name
    text = path.read_text(encoding="utf-8") if path.is_file() else STRUCTURES_HEADER
    document = yaml.compose(text) if text.strip() else None
    _save(
        path,
        text,
        _append_item(text, document, "pipe_supports", _flow(data)),
        "structures",
        lambda old: (
            old
            | {"pipe_supports": [*(old.get("pipe_supports") or []), yaml.safe_load(_flow(data))]}
        ),
    )
    return Pinned(name, [target])


def pin_structure(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """Declare the proposed structure *target* (a valve access platform ``VP-<valve tag>``) with its
    level, ladder or stair and the valves it serves in ``layout/structures.yaml``, and pin the
    routes of the pipes those valves sit on (``piping/routing.yaml``): the platform stands
    beside them, and its steel would otherwise move them on the next build."""
    entry = next(s for s in model.get("structures", []) if s["id"] == target)
    levels = [
        {
            "id": lv["id"],
            "elevation": lv["elevation"],
            "kind": lv.get("kind", "platform"),
            "use": lv.get("use", "occasional"),
        }
        for lv in entry["levels"]
    ]
    data: dict[str, Any] = {
        "id": entry["id"],
        "title": entry.get("title", ""),
        "origin": [round(c, 3) for c in entry["origin"]],
        "spans_x": [
            round(b - a, 3) for a, b in zip(entry["grid_x"], entry["grid_x"][1:], strict=False)
        ],
        "spans_y": [
            round(b - a, 3) for a, b in zip(entry["grid_y"], entry["grid_y"][1:], strict=False)
        ],
        "levels": levels,
    }
    stairs = [
        {"id": s["id"].split("/", 1)[-1], "from": s["from"], "to": s["to"], "side": s["side"]}
        | ({"offset": s["offset"]} if s.get("offset") else {})
        | ({"out": s["out"]} if s.get("out") else {})
        for s in entry.get("stairs", [])
    ]
    ladders = [
        {
            "id": ld["id"].split("/", 1)[-1],
            "from": ld["from"],
            "to": ld["to"],
            "at": [round(c, 3) for c in ld["at"]],
            "facing": ld["facing"],
        }
        for ld in entry.get("ladders", [])
    ]
    if stairs:
        data["stairs"] = stairs
    if ladders:
        data["ladders"] = ladders
    data["serves"] = list(entry.get("serves") or [])
    data["notes"] = "pinned valve access platform (ASSUMED sizes: check with the piping layout)"
    name = LAYOUT_FILES["structures"]
    path = root / name
    text = path.read_text(encoding="utf-8") if path.is_file() else STRUCTURES_HEADER
    document = yaml.compose(text) if text.strip() else None
    new = _append_item(text, document, "structures", _flow(data))

    def expect(old: Any) -> Any:
        return old | {"structures": [*(old.get("structures") or []), yaml.safe_load(_flow(data))]}

    done = Pinned(name, [target])
    inline = {i["id"]: i for i in model.get("inline", [])}
    pipes = sorted({inline[v]["pipe"] for v in data["serves"] if v in inline})
    routing = LAYOUT_FILES["routing"]
    route_path = root / routing
    route_old = route_path.read_text(encoding="utf-8") if route_path.is_file() else ROUTING_HEADER
    route_new, edits = route_old, []
    for pid in pipes:
        route_new, what, route_expect = _route_edit(route_new, model, pid)
        edits.append(route_expect)
        done.what += what

    def route_expects(old: Any) -> Any:
        for each in edits:
            old = each(old)
        return old

    # both files are checked before either is written
    _save(path, text, new, "structures", expect, write=False)
    if pipes:
        _save(route_path, route_old, route_new, "routing", route_expects, write=False)
    _save(path, text, new, "structures", expect)
    if pipes:
        _save(route_path, route_old, route_new, "routing", route_expects)
        done.file = f"{name} and {routing}"
    return done


def pin(root: Path, model: dict[str, Any], target: str) -> Pinned:
    """A proposed stair or ladder, a wall penetration (``OWNER/LINE``), a platform
    (``TAG/platform-N`` or a tag with platforms), proposed support steel (``PIPE/SP-<arc>``),
    else a line or pipe id."""
    if target in access_ids(model):
        return pin_access(root, model, target)
    if any(
        s["id"] == target and s.get("source") == "generated" for s in model.get("structures", [])
    ):
        return pin_structure(root, model, target)
    if any(
        s["id"] == target and s.get("source") == "generated" for s in model.get("support_steel", [])
    ):
        return pin_support(root, model, target)
    if any(p["id"] == target for p in model.get("penetrations", [])):
        return pin_penetration(root, model, target)
    if any(target in (p["id"], p["tag"]) for p in model.get("platforms", [])) and (
        "/platform-" in target or not any(p["line"] == target for p in model.get("pipes", []))
    ):
        return pin_platforms(root, model, target)
    return pin_routes(root, model, target)
