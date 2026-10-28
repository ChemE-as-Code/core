"""Accepted findings: the ``accept:`` entries of ``checks/checks.yaml``."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import ValidationError

from chemeascode.foundation.findings import Finding

if TYPE_CHECKING:
    from chemeascode.foundation.workspace import Workspace


def accept_matches(pattern: str, finding_id: str) -> bool:
    """Whether an ``accept:`` id (exact, or with ``*`` / ``?`` wildcards) names *finding_id*."""
    from fnmatch import fnmatchcase

    return pattern == finding_id or fnmatchcase(finding_id, pattern)


def _check_list(workspace: Workspace) -> tuple[Any, str | None]:
    """checks/checks.yaml parsed (``None`` when missing or invalid), and that file's name."""
    from chemeascode.foundation.schemas.checks import CheckList

    path = workspace.list_file("checks")
    if path is None:
        return None, None
    try:
        checks = CheckList.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except (OSError, yaml.YAMLError, ValidationError):
        return None, workspace.relative(path)
    return checks, workspace.relative(path)


def accepted_entries(workspace: Workspace) -> tuple[list[Any], str | None]:
    """The repository-wide ``accept:`` entries of checks/checks.yaml, and that file's name."""
    checks, name = _check_list(workspace)
    return (list(checks.accept) if checks is not None else []), name


#: A length quoted in an acceptance's reason: a number followed by ``m`` (not mm, m2, m3/h).
_LENGTH = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\s?m(?![\w\u00b2\u00b3/])")
#: How far a quoted length may differ from the finding's measured one: 0.1 m, or 2 % of it,
#: whichever is larger (the messages round to 0.1 m; ASSUMED).
STALE_ABS_M = 0.1
STALE_REL = 0.02


def stale_quote(reason: str, finding: Finding) -> float | None:
    """The length *reason* quotes for *finding* when it is out of date: the finding measures a
    length (``measured``), the reason quotes lengths, and none of them is within
    :data:`STALE_ABS_M` or :data:`STALE_REL` of it; then the quoted length nearest the
    measured one. ``None`` when the reason quotes the current length, quotes none, or the
    finding measures none."""
    value = finding.measured
    if value is None:
        return None
    quoted = [float(m) for m in _LENGTH.findall(reason or "")]
    if not quoted:
        return None
    tolerance = max(STALE_ABS_M, STALE_REL * abs(value))
    if any(abs(q - value) <= tolerance + 1e-9 for q in quoted):
        return None
    return min(quoted, key=lambda q: abs(q - value))


def acceptance(entries: list[Any], finding: Finding) -> Any:
    """The first of *entries* that accepts *finding*, or ``None``.

    Errors are never accepted: an entry can only turn a warning or an info into an accepted
    info, so ``validate``, the pre-commit hook, CI and the gates still fail on every error.
    """
    if finding.level == "error":
        return None
    return next((e for e in entries if accept_matches(e.id, finding.id)), None)
