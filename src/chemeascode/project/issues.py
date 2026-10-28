"""A plant's issues as engineering items: actions, holds, technical queries, design changes.

The issues live on GitHub (``plant.yaml`` ``issues: {repository, label}``). Their labels follow
an engineering vocabulary (docs/framework/issues.md), read here into :class:`Issue` records:

- ``type:action`` (from a review, a HAZOP or a design meeting), ``type:hold`` (an engineering
  hold: a value or decision the design does not have yet), ``type:tq`` (technical query),
  ``type:change`` (design change, management of change);
- ``gate:<stage>``: the stage gate it must be closed before;
- ``discipline:<d>``, ``source:<s>``;
- ``status:in-progress``, ``status:for-verification`` (an open issue without one is ``open``; a
  closed issue is ``closed``);
- ``waiting:input`` (vendor, client, HAZOP / LOPA) and ``waiting:work`` (another issue).

``kind: issues`` gates (checks.yaml) fail while an issue of the plant with a ``gate:`` at or
before the gate's stage is open, as an action tracker must be closed out before a stage sign-off.
An item with more than one ``gate:`` label counts at the earliest, and one with a ``gate:``
that is not a stage of the plant blocks every gate, so a stale or mistyped label never lets a
gate pass. The issues are read live (``integrations.github``, cached for :data:`CACHE_S` per
process, a failure too); without a token or network the gate fails as *not evaluated*.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote, urlencode

from chemeascode.foundation.workspace import Workspace

TYPES = ("action", "hold", "tq", "change")
CACHE_S = 120.0
_cache: dict[tuple[str, str], tuple[float, list[dict[str, Any]] | str]] = {}
TYPE_TITLES = {
    "action": "Action item",
    "hold": "Engineering hold",
    "tq": "Technical query",
    "change": "Design change",
}


@dataclass
class Issue:
    number: int
    title: str
    state: str  # open, closed
    status: str  # open, in-progress, for-verification, closed
    type: str | None
    gate: str | None
    """The earliest of *gates* (concept, basic, detail order; another label first)."""
    gates: list[str] = field(default_factory=list)
    disciplines: list[str] = field(default_factory=list)
    source: str | None = None
    waiting: str | None = None
    url: str = ""
    created: str = ""
    updated: str = ""
    closed: str | None = None


def _labelled(names: list[str], prefix: str) -> list[str]:
    return [n[len(prefix) :] for n in names if n.startswith(prefix)]


def issue_from_github(item: dict[str, Any]) -> Issue:
    """One issue of the GitHub API as an :class:`Issue`."""
    names = [
        label["name"] if isinstance(label, dict) else str(label) for label in item.get("labels", [])
    ]
    state = item.get("state", "open")
    statuses = _labelled(names, "status:")
    status = "closed" if state == "closed" else (statuses[0] if statuses else "open")
    types = [t for t in _labelled(names, "type:") if t in TYPES]
    gates = sorted(_labelled(names, "gate:"), key=_gate_rank)
    sources = _labelled(names, "source:")
    waiting = _labelled(names, "waiting:")
    return Issue(
        number=int(item["number"]),
        title=str(item.get("title", "")),
        state=state,
        status=status,
        type=types[0] if types else None,
        gate=gates[0] if gates else None,
        gates=gates,
        disciplines=sorted(_labelled(names, "discipline:")),
        source=sources[0] if sources else None,
        waiting=waiting[0] if waiting else None,
        url=str(item.get("html_url", "")),
        created=str(item.get("created_at", "") or ""),
        updated=str(item.get("updated_at", "") or ""),
        closed=item.get("closed_at"),
    )


def _gate_rank(gate: str) -> tuple[int, str]:
    order = ("concept", "basic", "detail")
    return (order.index(gate) + 1 if gate in order else 0, gate)


def clear_cache() -> None:
    _cache.clear()


class IssuesUnavailable(RuntimeError):
    """The plant declares issues, but they cannot be read now (no token, no network)."""


def plant_issues(workspace: Workspace, items: list[dict[str, Any]] | None = None) -> list[Issue]:
    """The plant's issues, newest first. *items* (raw API answers) skips the network (tests,
    snapshots). Raises :class:`IssuesUnavailable` when they cannot be read and LookupError when
    plant.yaml declares no ``issues``."""
    config = workspace.config().issues
    if config is None:
        raise LookupError("plant.yaml declares no issues: (repository and label)")
    if items is None:
        from chemeascode.integrations.github import GitHubError, list_issues

        key = (config.repository, config.label)
        at, cached = _cache.get(key, (0.0, ""))
        if not cached or time.monotonic() - at > CACHE_S:
            try:
                cached = list_issues(config.repository, config.label)
            except GitHubError as failure:
                cached = str(failure)
            _cache[key] = (time.monotonic(), cached)
        if isinstance(cached, str):
            raise IssuesUnavailable(cached)
        items = cached
    issues = [issue_from_github(item) for item in items]
    return sorted(issues, key=lambda i: -i.number)


def new_issue_links(workspace: Workspace, prefill: dict[str, str] | None = None) -> dict[str, str]:
    """A link to open a new issue of each type, the plant's label and the form's process field
    filled in (*prefill* adds form fields, e.g. ``{"refs": "P-04 PIC-4101"}``). Without
    ``forms`` in plant.yaml one link to the template chooser."""
    config = workspace.config().issues
    if config is None:
        return {}
    base = f"{config.web.rstrip('/')}/{config.repository}/issues/new"
    process = config.label.split(":", 1)[1] if ":" in config.label else ""
    fields = {"process": process} if process else {}
    fields.update(prefill or {})
    if not config.forms:
        return {"choose": f"{base}/choose"}
    links = {}
    for kind, form in config.forms.items():
        query = {"template": form, "labels": config.label, **fields}
        links[kind] = f"{base}?{urlencode(query, quote_via=quote)}"
    return links


def stage_order(workspace: Workspace) -> list[str]:
    return [s.id for s in workspace.config().stages]


def blocking(issues: list[Issue], stage: str, stages: list[str], types: list[str]) -> list[Issue]:
    """The open issues that block the gate of *stage*: a ``gate:`` at or before it (an item
    meant for an earlier stage that is still open blocks the later gates too), or a ``gate:``
    that is no stage of the plant (mistyped: it blocks rather than slip through)."""
    if stage not in stages:
        return []
    upto = set(stages[: stages.index(stage) + 1])
    return [
        issue
        for issue in issues
        if issue.state == "open"
        and any(g in upto or g not in stages for g in issue.gates)
        and (not types or issue.type in types)
    ]


def issues_gate(workspace: Workspace, check: Any) -> tuple[str, str]:
    """``kind: issues``: (status, detail) of the gate."""
    if workspace.config().issues is None:
        return "n/a", "plant.yaml declares no issues"
    try:
        issues = plant_issues(workspace)
    except IssuesUnavailable as failure:
        return "fail", f"not evaluated: {failure}"
    open_ = blocking(issues, check.stage, stage_order(workspace), list(check.types))
    if not open_:
        return "pass", f"no open item to close before {check.stage}"
    shown = ", ".join(f"#{i.number} ({i.type or 'untyped'})" for i in open_[:8])
    more = f" and {len(open_) - 8} more" if len(open_) > 8 else ""
    return "fail", f"{len(open_)} open item(s) to close before {check.stage}: {shown}{more}"


def issues_report(
    workspace: Workspace, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """``cheme issues --json`` and ``GET /api/issues``: the issues with the counts the gates use
    and the new-issue links."""
    config = workspace.config().issues
    assert config is not None
    issues = plant_issues(workspace, items)
    stages = stage_order(workspace)
    counts: dict[str, dict[str, int]] = {}
    for issue in issues:
        if issue.state != "open":
            continue
        row = counts.setdefault(issue.gate or "none", {})
        row[issue.type or "other"] = row.get(issue.type or "other", 0) + 1
    return {
        "repository": config.repository,
        "label": config.label,
        "web": f"{config.web.rstrip('/')}/{config.repository}/issues?q="
        + quote(f'is:issue label:"{config.label}"'),
        "new": new_issue_links(workspace),
        "stage": workspace.config().stage,
        "stages": stages,
        "open_by_gate": counts,
        "blocking": {s: [i.number for i in blocking(issues, s, stages, [])] for s in stages},
        "issues": [asdict(i) for i in issues],
    }
