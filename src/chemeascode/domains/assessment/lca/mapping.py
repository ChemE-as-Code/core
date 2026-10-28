"""The background mapping workflow: candidates for the open exchanges, and an explicit apply.

``cheme assess lca-map`` lists every exchange of the inventory without a background (unmapped,
or declared ``missing:``) with the Brightway activities a search of the project finds for it,
numbered, with the query that found them. ``--apply KEY=N`` writes the chosen candidate as the
entry's ``activity:`` into ``lca/lca.yaml``, and nothing else: the edit keeps the file's other
text and comments, and is refused unless the file then parses to exactly the intended data and
still validates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from chemeascode.domains.assessment.lca.allocation import MISSING
from chemeascode.domains.assessment.lca.schemas import INVENTORY_UNITS
from chemeascode.integrations import brightway as bw

#: Key prefix -> the lca.yaml list holding its entry, and that entry's identifying field.
SECTIONS = {
    "feed": ("flows", "key"),
    "product": ("flows", "key"),
    "construction": ("construction", "id"),
    "consumable": ("consumables", "id"),
    "transport": ("transport", "id"),
    "end-of-life": ("end_of_life", "id"),
}
#: The inventory's units by kind (as impacts._KIND), to compare with a candidate's unit.
_KIND = {unit: kind for kind, unit in INVENTORY_UNITS.items()}


@dataclass
class OpenExchange:
    """An inventory row without a background, and what a search found for it."""

    key: str
    title: str
    unit: str
    #: ``unmapped`` or ``missing`` (with the declared reason in *detail*).
    reason: str
    detail: str = ""
    query: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Why ``--apply`` cannot write this key (empty when it can).
    unsupported: str = ""


def open_exchanges(inventory: Any) -> list[OpenExchange]:
    """The rows of *inventory* without a background: unmapped, or declared missing."""
    found = []
    for row in inventory.rows:
        if row.key in inventory.backgrounds:
            continue
        if row.mapping.startswith(MISSING):
            reason, detail = "missing", row.mapping.removeprefix(MISSING)
        elif not row.mapping:
            reason, detail = "unmapped", ""
        else:
            continue
        prefix = row.key.split(":", 1)[0]
        unsupported = ""
        if prefix not in SECTIONS:
            unsupported = (
                f"{prefix}: exchanges are mapped by hand (an emission or resource takes "
                "biosphere: or elementary:, a disposal its entry's disposal:)"
            )
        elif SECTIONS[prefix][0] != "flows" and reason == "unmapped":
            unsupported = "the entry has no background field to replace"
        found.append(
            OpenExchange(row.key, row.title, row.unit, reason, detail, unsupported=unsupported)
        )
    return found


def compatible(exchange: OpenExchange, candidate: dict[str, Any]) -> str:
    """Why *candidate* cannot be the background of *exchange* (empty when it can)."""
    if candidate.get("biosphere"):
        return "a biosphere flow, not an activity"
    kind = bw.UNITS.get(candidate.get("unit") or "", (None, 1.0))[0]
    if kind is None or kind != _KIND.get(exchange.unit):
        return f"per {candidate.get('unit')!r}, the exchange is counted in {exchange.unit}"
    return ""


def search(
    project: str,
    exchanges: list[OpenExchange],
    query: str | None = None,
    database: str | None = None,
    limit: int = 5,
) -> None:
    """Fill each exchange's candidates from a search of *project*: by *query*, else its title,
    else (when the title finds nothing) the id of its key."""
    for exchange in exchanges:
        texts = [query] if query else [exchange.title, exchange.key.split(":", 1)[1]]
        for text in (t for t in texts if t):
            exchange.query = text
            exchange.candidates = bw.search(project, text, database, limit)
            if exchange.candidates:
                break


def activity_entry(candidate: dict[str, Any]) -> dict[str, str]:
    """The ``activity:`` mapping of a search result, as ``cheme assess lca-search`` prints it."""
    return {
        k: candidate[k]
        for k in ("database", "name", "reference_product", "location")
        if candidate.get(k) is not None
    }


class ApplyRefused(ValueError):
    """The edit of lca/lca.yaml was not made (the message says why)."""


def _dump(data: Any, indent: int) -> list[str]:
    text = yaml.safe_dump(
        data, sort_keys=False, default_flow_style=False, width=1000, allow_unicode=True
    )
    return [" " * indent + line for line in text.splitlines()]


def _last_line(node: yaml.Node) -> int:
    """The 0-based last line holding content of *node* (a block collection's end mark lies
    after its trailing blank lines and comments; a scalar's does not)."""
    if isinstance(node, yaml.ScalarNode) or node.flow_style:
        return node.end_mark.line - (0 if node.end_mark.column else 1)
    children = (
        [n for pair in node.value for n in pair]
        if isinstance(node, yaml.MappingNode)
        else list(node.value)
    )
    return max((_last_line(n) for n in children), default=node.start_mark.line)


def _item(root: yaml.MappingNode, section: str, field_: str, value: str) -> Any:
    """The sequence node of *section* and its item whose *field_* is *value* (or None)."""
    for key, node in root.value:
        if key.value != section:
            continue
        if isinstance(node, yaml.ScalarNode) and node.tag.endswith(":null"):
            return None, None  # "flows:" with no value
        if not isinstance(node, yaml.SequenceNode):
            raise ApplyRefused(f"{section}: is not a list")
        if node.flow_style and not node.value:
            return None, None  # "flows: []"
        for item in node.value:
            if not isinstance(item, yaml.MappingNode):
                continue
            for k, v in item.value:
                if k.value == field_ and isinstance(v, yaml.ScalarNode) and v.value == value:
                    return node, item
        return node, None
    return None, None


def _end(node: yaml.Node) -> int:
    """The 0-based line after *node*'s last line of content."""
    return _last_line(node) + 1


def _comment(line: str, column: int) -> str:
    """The comment after *column* of *line* (with its leading space), or empty."""
    rest = line[column:].rstrip("\r\n")
    return rest if rest.lstrip().startswith("#") else ""


def _replace_field(
    lines: list[str], item: yaml.MappingNode, name: str, new_name: str, value: Any
) -> tuple:
    """The edit (first line, end line, new lines) putting ``new_name: value`` where the block
    mapping *item*'s field *name* is, keeping a comment after a scalar value."""
    k, v = next((k, v) for k, v in item.value if k.value == name)
    start, end = k.start_mark.line, _end(v)
    new = [line + "\n" for line in _dump({new_name: value}, k.start_mark.column)]
    if isinstance(v, yaml.ScalarNode) and end - 1 == v.end_mark.line:
        new[-1] = new[-1][:-1] + _comment(lines[end - 1], v.end_mark.column) + "\n"
    # "- missing: ..." opens the item: keep the dash
    new[0] = lines[start][: k.start_mark.column] + new[0][k.start_mark.column :]
    return start, end, new


def _apply(text: str, key: str, activity: dict[str, str], source: str) -> tuple[str, Any]:
    """The edited text and the data it must parse to."""
    prefix, _, ident = key.partition(":")
    if prefix not in SECTIONS:
        raise ApplyRefused(f"{key}: only {', '.join(SECTIONS)} exchanges take an activity:")
    section, field_ = SECTIONS[prefix]
    value = key if field_ == "key" else ident
    expected = yaml.safe_load(text)
    root = yaml.compose(text)
    if not isinstance(expected, dict) or not isinstance(root, yaml.MappingNode):
        raise ApplyRefused("lca/lca.yaml is not a mapping")
    lines = text.splitlines(keepends=True)
    sequence, item = _item(root, section, field_, value)
    if item is None:
        if section != "flows":
            raise ApplyRefused(f"{key}: no {section}: entry with {field_}: {ident}")
        entry = {"key": key, "activity": activity, "source": source}
        if not isinstance(expected.get("flows"), list):
            expected["flows"] = []
        expected["flows"].append(entry)
        block = [line + "\n" for line in _dump([entry], 0)]
        if sequence is None:  # no flows: (or flows: with no value, or [])
            head = next((k for k, _ in root.value if k.value == "flows"), None)
            if head is None:
                return text + "flows:\n" + "".join(block), expected
            if head.start_mark.column != 0:
                raise ApplyRefused("flows: is not at the top level; add the entry by hand")
            at = head.start_mark.line
            return "".join(lines[:at] + ["flows:\n", *block] + lines[_end(head) :]), expected
        if sequence.flow_style:
            raise ApplyRefused("flows: is written in flow style; add the entry by hand")
        first = sequence.value[0]
        dash = lines[first.start_mark.line].rfind("-", 0, first.start_mark.column)
        block = [" " * dash + line for line in block]
        at = _end(sequence)
        return "".join(lines[:at] + block + lines[at:]), expected
    fields = {k.value for k, _ in item.value}
    if "missing" not in fields:
        raise ApplyRefused(f"{key}: its entry is not declared missing:")
    index = next(i for i, e in enumerate(expected[section]) if str(e.get(field_)) == value)
    # activity: where missing: was, in the entry's own order
    target = {
        ("activity" if k == "missing" else k): (
            activity if k == "missing" else source if k == "source" else v
        )
        for k, v in expected[section][index].items()
    }
    target.setdefault("source", source)
    expected[section][index] = target
    if item.flow_style:  # - {key: ..., missing: ..., source: ...}: write the entry again
        flow = yaml.safe_dump(
            target, sort_keys=False, default_flow_style=True, width=100000, allow_unicode=True
        ).strip()
        start, end = item.start_mark.index, item.end_mark.index
        return text[:start] + flow + text[end:], expected
    edits = [_replace_field(lines, item, "missing", "activity", activity)]
    if "source" in fields:
        edits.append(_replace_field(lines, item, "source", "source", source))
    edits.sort(key=lambda e: e[0])
    if len(edits) == 2 and edits[0][1] > edits[1][0]:
        raise ApplyRefused(f"{key}: its missing: and source: share a line; edit by hand")
    new_lines = list(lines)
    for a, b, rep in reversed(edits):
        new_lines[a:b] = rep
    return "".join(new_lines), expected


def apply(text: str, key: str, activity: dict[str, str], source: str) -> str:
    """*text* (lca/lca.yaml) with *activity* as the background of *key*: in place of the
    entry's ``missing:`` (its ``source:`` replaced by *source*), or as a new ``flows:`` entry
    for an unmapped flow. The rest of the text, its comments and its line endings stay. Raises
    :class:`ApplyRefused` when the result would not be exactly that change, or would not
    validate."""
    from chemeascode.domains.assessment.lca.schemas import LcaFile

    if "\n" in source or "\r" in source:
        raise ApplyRefused(f"{key}: give the source on one line")
    crlf = "\r\n" in text
    plain = text.replace("\r\n", "\n")
    if plain and not plain.endswith("\n"):
        plain += "\n"
    new, expected = _apply(plain, key, activity, source)
    try:
        got = yaml.safe_load(new)
    except yaml.YAMLError as failure:
        raise ApplyRefused(f"{key}: the edit would not parse ({failure})") from failure
    if got != expected:
        raise ApplyRefused(f"{key}: the edit would change more than its mapping; edit by hand")
    try:
        LcaFile.model_validate(got)
    except ValueError as failure:
        lines = str(failure).splitlines()
        first = "; ".join(line.strip().split(" [type=")[0] for line in lines[1:3]) or lines[0]
        raise ApplyRefused(f"{key}: lca/lca.yaml would not validate ({first})") from failure
    return new.replace("\n", "\r\n") if crlf else new
