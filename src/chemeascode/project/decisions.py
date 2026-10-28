"""Decision references: a ``D-NNN`` in a YAML file names an entry of ``DESIGN.md``.

The repository's ``DESIGN.md`` is its register of decisions and assumptions, one heading per
entry (``## D-012 <title> (<date>)``). Values cite them in ``source``, ``basis``, ``reason`` or
a comment (``provenance: assumed, source: DESIGN.md D-012``). ``cheme validate`` reports
``cheme.decision-unknown`` (info) for a cited id with no heading, once per file and id.

Every ``*.yaml`` of the repository is read, generated ones included, but not hidden
directories, ``build``/``dist``, ``node_modules``, nested repositories or files outside the
root. A repository without ``DESIGN.md``, or whose ``DESIGN.md`` holds no entry yet (the
``cheme init`` template keeps its example in a comment), is not checked.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace

DESIGN_FILE = "DESIGN.md"

_HEADING = re.compile(r"^#+\s+(D-\d{3,})\b", re.MULTILINE)
#: Not part of a longer token (``ISO D-1234`` still matches; ``X-D-1001`` does not).
_CITED = re.compile(r"(?<![\w-])D-\d{3,}\b")
_HIDDEN = re.compile(r"<!--.*?-->|^```.*?^```", re.DOTALL | re.MULTILINE)
_SKIPPED = {"build", "dist", "node_modules", "__pycache__"}
#: Larger YAML files are data dumps, not inputs that cite decisions.
_MAX_BYTES = 5_000_000


def decisions(text: str) -> set[str]:
    """The decision ids *text* (a DESIGN.md) has headings for, outside comments and code."""
    return set(_HEADING.findall(_HIDDEN.sub("", text)))


def _yaml_files(workspace: Workspace, targets: set[Path] | None) -> Iterator[Path]:
    if targets is not None:
        yield from sorted(p for p in targets if p.suffix == ".yaml" and workspace.contains(p))
        return
    for top, dirs, files in os.walk(workspace.root):
        dirs[:] = sorted(
            d
            for d in dirs
            if not d.startswith(".")
            and d not in _SKIPPED
            and not os.path.lexists(os.path.join(top, d, ".git"))
        )
        for name in sorted(files):
            path = Path(top) / name
            if name.endswith(".yaml") and workspace.contains(path):
                yield path


def _read(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def decision_findings(workspace: Workspace, targets: set[Path] | None = None) -> list[Finding]:
    """``cheme.decision-unknown`` for each id a YAML file (of *targets*, when given) cites that
    DESIGN.md does not hold."""
    known = decisions(_read(workspace.root / DESIGN_FILE) or "")
    if not known:
        return []
    findings: list[Finding] = []
    for path in _yaml_files(workspace, targets):
        text = _read(path)
        if text is None:
            continue
        first: dict[str, int] = {}
        for n, line in enumerate(text.splitlines(), start=1):
            for cited in _CITED.findall(line):
                if cited not in known:
                    first.setdefault(cited, n)
        name = workspace.relative(path)
        findings += [
            Finding(
                name,
                "info",
                "cheme.decision-unknown",
                f"{cited} is cited, but {DESIGN_FILE} has no entry {cited}",
                line=n,
                ids=[cited],
                hint=f"add `## {cited} <title> (<date>)` to {DESIGN_FILE}, or correct the id",
            )
            for cited, n in first.items()
        ]
    return findings
