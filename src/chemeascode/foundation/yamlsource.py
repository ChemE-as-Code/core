"""Where things are in a YAML file: source lines for findings on parsed lists and documents."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.findings import Finding


def _compose(path: Path) -> Any:
    """The YAML node tree of *path* (with line marks), or None."""
    try:
        return yaml.compose(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None


def syntax_finding(name: str, failure: yaml.YAMLError, text: str) -> Finding:
    """The ``yaml.syntax`` error for a YAML file *name* (content *text*) that does not parse.

    A parser or scanner error carries a line mark. A character YAML does not allow (a control
    character pasted from a spreadsheet: ``ReaderError``) carries only its position in *text*;
    its line counts the line breaks before it as YAML and ``str.splitlines`` do (``\\r\\n``,
    ``\\r``, ``\\n``, NEL, LS, PS: the text before the position holds no other control
    character, or the reader would have stopped there).
    """
    if isinstance(failure, yaml.MarkedYAMLError):
        mark = failure.problem_mark
        line = mark.line + 1 if mark else None
        return Finding(name, "error", "yaml.syntax", str(failure.problem or failure), line=line)
    if isinstance(failure, yaml.reader.ReaderError):
        return Finding(
            name,
            "error",
            "yaml.syntax",
            f"character #x{failure.character:04x} is not allowed: {failure.reason}",
            line=len((text[: failure.position] + "x").splitlines()),
            hint="delete the character or write it as an escape in a double-quoted string",
        )
    message = (str(failure).splitlines() or [type(failure).__name__])[0]
    return Finding(name, "error", "yaml.syntax", message)


def _yaml_line(node: Any, loc: Iterable[Any]) -> int | None:
    """The line of the deepest YAML node on the path *loc* (a pydantic error location)."""
    line = None
    for step in loc:
        if node is None:
            break
        line = node.start_mark.line + 1
        if isinstance(node, yaml.MappingNode):
            node = next(
                (v for k, v in node.value if isinstance(k, yaml.ScalarNode) and k.value == step),
                None,
            )
        elif isinstance(node, yaml.SequenceNode) and isinstance(step, int):
            node = node.value[step] if 0 <= step < len(node.value) else None
        else:
            node = None
    if node is not None:
        line = node.start_mark.line + 1
    return line


@dataclass
class _Entry:
    """Where one list entry is: its line, and the line of each of its ``segments``."""

    line: int | None = None
    segments: list[int | None] = field(default_factory=list)


def _entries(path: Path, key: str, count: int) -> list[_Entry]:
    """Where each of the *count* entries of the list under *key* is, in list order.

    The schema accepted the list, so its entries and the parsed ones correspond by position.
    """
    document = _compose(path)
    found: list[_Entry] = []
    if isinstance(document, yaml.MappingNode):
        for k, v in document.value:
            if (
                isinstance(k, yaml.ScalarNode)
                and k.value == key
                and isinstance(v, yaml.SequenceNode)
            ):
                for entry in v.value:
                    fields = (
                        {f.value: n for f, n in entry.value if isinstance(f, yaml.ScalarNode)}
                        if isinstance(entry, yaml.MappingNode)
                        else {}
                    )
                    segments = fields.get("segments")
                    found.append(
                        _Entry(
                            entry.start_mark.line + 1,
                            [n.start_mark.line + 1 for n in segments.value]
                            if isinstance(segments, yaml.SequenceNode)
                            else [],
                        )
                    )
    if len(found) != count:
        return [_Entry() for _ in range(count)]
    return found


def _duplicates(
    list_name: str, what: str, rule: str, keys: list[str], entries: list[_Entry]
) -> list[Finding]:
    """A finding for every entry whose key an earlier entry already has."""
    first: dict[str, int] = {}
    findings: list[Finding] = []
    for position, key in enumerate(keys):
        if key not in first:
            first[key] = position
            continue
        earlier = entries[first[key]].line
        findings.append(
            Finding(
                list_name,
                "warning",
                rule,
                f"{what} {key} is listed twice"
                + (f" (first on line {earlier})" if earlier else ""),
                line=entries[position].line,
                ids=[key],
                hint="merge the two entries into one",
            )
        )
    return findings
