"""Findings: one thing wrong (or worth knowing) about one file, with a stable id.

Every check in cheme-as-code reports findings. Each names a file, a line where one is known, a rule
and a hint, so an agent can go straight to the place and fix it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Level = Literal["error", "warning", "info"]

_SEVERITY = {"error": 2, "warning": 1, "info": 0}

#: Rules that a rule pattern also matches when it matches the rule they stand in for: a generator
#: that cannot run (``generator-failed``) leaves the drift of its sheet unchecked, so whatever
#: would fail on ``generated-sheet-drift`` (``cheme.generated-*`` included) fails on it too.
_STANDS_IN_FOR = {"cheme.generator-failed": ("cheme.generated-sheet-drift",)}


def rule_matches(rule: str, pattern: str) -> bool:
    """Whether *pattern* (a rule id or a glob, ``cheme.generated-*``) matches *rule*, or a rule
    that *rule* stands in for (``cheme.generator-failed`` for ``cheme.generated-sheet-drift``)."""
    from fnmatch import fnmatchcase

    return any(fnmatchcase(r, pattern) for r in (rule, *_STANDS_IN_FOR.get(rule, ())))


@dataclass
class Finding:
    """One thing wrong (or worth knowing) about one file."""

    file: str
    level: Level
    rule: str
    message: str
    line: int | None = None
    ids: list[str] = field(default_factory=list)
    hint: str = ""
    #: What the finding is about, when ``ids`` alone do not make its id stable.
    key: str = ""
    #: The region of the sheet it is about, sheet mm, Y down: ``[x0, y0, x1, y1]``.
    box: list[float] | None = None
    #: ``X0,Y0,X1,Y1`` for ``cheme render --crop``: the box with a margin.
    crop: str | None = None
    #: Why it is accepted (an ``accept:`` entry of checks/checks.yaml), when it is.
    accepted: str | None = None
    #: The length (m) the finding measures (a span, a run, a distance), when it measures one:
    #: an acceptance whose reason quotes another length is stale (``cheme.accept-stale``).
    measured: float | None = None

    @property
    def id(self) -> str:
        """A stable id: ``<file>#<rule>:<subject>``, e.g. ``pid/P-03.xml#line-crossing:A+B``."""
        subject = self.key or "+".join(self.ids) or str(self.line or "")
        return f"{self.file}#{self.rule.removeprefix('cheme.')}:{subject}"

    def format(self) -> str:
        """``file:line: level rule [ids]: message (hint)``, one line."""
        where = f"{self.file}:{self.line}" if self.line else self.file
        subject = f" [{', '.join(self.ids)}]" if self.ids else ""
        hint = f" -- {self.hint}" if self.hint else ""
        extra = ""
        if self.crop:
            extra += f" [crop {self.crop}]"
        acceptable = self.crop or self.key or self.accepted or "accept" in self.hint
        if acceptable and not self.rule.startswith("cheme.accept-"):
            # The id an ``accept:`` entry names, wherever accepting is an option.
            extra += f" [id {self.id}]"
        if self.accepted:
            extra += f" (accepted: {self.accepted})"
        return f"{where}: {self.level} {self.rule}{subject}: {self.message}{hint}{extra}"
