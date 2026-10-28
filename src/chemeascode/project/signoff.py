"""Stage sign-off: ``cheme check --stage S --write`` records provenance in ``status.json``.

A sign-off is refused (nothing is written) when the working tree has changes other than
``checks/status.json``, when a gate fails, when the review record it names is the signer's own
(reviewer kind ``self``, or the reviewer is the signer) without a human ``approved_by``, or when
a critical or high finding of any review record is open (rated so by any record that lists it:
:func:`~chemeascode.foundation.reviews.open_blocking`). Each stage gets its own entry, so an
earlier stage's sign-off is kept.
"""

from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation import gitinfo
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.checks import CheckStatus, result_dict

STATUS_FILE = "checks/status.json"


class SignOffRefused(Exception):
    """The sign-off would not be trustworthy; ``reasons`` says why."""

    def __init__(self, reasons: list[str]) -> None:
        super().__init__("; ".join(reasons))
        self.reasons = reasons


@dataclass
class SignOffResult:
    entry: dict[str, Any]
    notes: list[str] = field(default_factory=list)


def read_status(workspace: Workspace) -> dict[str, Any]:
    """``checks/status.json`` as a dict with ``stages`` and ``checks`` (empty when absent).

    A 0.3 file (only ``checks``) is read with no stage entries.
    """
    path = workspace.root / STATUS_FILE
    if not path.is_file():
        return {"stages": {}, "checks": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"stages": {}, "checks": []}
    if not isinstance(data, dict):
        return {"stages": {}, "checks": []}
    stages = data.get("stages") if isinstance(data.get("stages"), dict) else {}
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    return {**data, "stages": stages, "checks": checks}


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and a.strip().casefold() == b.strip().casefold()  # type: ignore[union-attr]


def _review(workspace: Workspace, review: Path, signer: str, reasons: list[str]) -> dict[str, Any]:
    from chemeascode.foundation.reviews import load_records

    path = review if review.is_absolute() else workspace.root / review
    if not path.is_file() or not workspace.contains(path):
        reasons.append(f"review record {review} does not exist in the repository")
        return {}
    name = workspace.relative(path)
    records = list(load_records(workspace, [path]))
    record = records[0]
    if record.front is None:
        why = "no front matter" if not record.has_front else "invalid front matter"
        reasons.append(f"{name}: {why} (see `cheme schema review`)")
        return {"review": name}
    front = record.front
    approver = (front.approved_by or "").strip()
    own = front.reviewer_kind == "self" or _same(front.reviewer, signer)
    if own and (not approver or _same(approver, signer)):
        reasons.append(
            f"{name} is a self review ({front.reviewer}, reviewer_kind {front.reviewer_kind}) "
            f"and the signer is {signer}: an independent reviewer, or approved_by naming a human "
            "other than the signer, is needed"
        )
    return {
        "review": name,
        "review_commit": front.reviewed_commit,
        "reviewer": front.reviewer,
        "reviewer_kind": front.reviewer_kind,
        **({"approved_by": approver} if approver else {}),
    }


def sign_off(
    workspace: Workspace,
    stage: str,
    stages: list[str],
    results: list[CheckStatus],
    review: Path | None = None,
    by: str | None = None,
    now: datetime.datetime | None = None,
) -> SignOffResult:
    """Record the sign-off of *stage* in ``checks/status.json`` or raise :class:`SignOffRefused`.

    *results*: the gates of every stage in *stages* (up to *stage*), evaluated now.
    """
    from chemeascode.foundation.reviews import (
        BLOCKING,
        closing_commit,
        latest_rows,
        load_records,
        open_blocking,
        review_rules,
        worst_severities,
    )

    root = workspace.root
    reasons: list[str] = []
    head = gitinfo.head(root) if gitinfo.is_repo(root) else None
    if head is None:
        raise SignOffRefused(["a sign-off needs a git repository with at least one commit"])
    status_name = STATUS_FILE
    found = gitinfo.dirty_paths(root)
    dirty = [p for p in found or [] if p != status_name]
    if found is None:
        reasons.append(
            "git cannot tell whether the working tree has uncommitted changes (git status "
            "failed); run `git status` and fix the repository first"
        )
    elif dirty:
        shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
        reasons.append(f"the working tree has uncommitted changes: {shown}; commit them first")
    failing = [r.id for r in results if r.status == "fail"]
    if failing:
        reasons.append("failing gate(s): " + ", ".join(failing))
    signer = (by or gitinfo.user_name(root) or "").strip()
    if not signer:
        reasons.append("no signer: pass --by NAME or set git user.name")
    review_info: dict[str, Any] = {}
    if review is not None:
        review_info = _review(workspace, review, signer, reasons)
    records = load_records(workspace)
    blocking = open_blocking(records)
    if blocking:
        reasons.append(
            "open critical/high finding(s): "
            + ", ".join(f"{row.id} ({row.severity})" for row in blocking[:8])
        )
    worst = worst_severities(records)
    unproven = [
        (row, commit)
        for row in latest_rows(records).values()
        if row.kind == "closed" and worst.get(row.id) in BLOCKING
        for commit in [closing_commit(row.status)]
        if not _fixed_in_history(root, commit)
    ]
    if unproven:
        reasons.append(
            "critical/high finding(s) closed by a commit that is not in this branch's history: "
            + ", ".join(f"{row.id} (closed {commit})" for row, commit in unproven[:8])
            + "; name the commit that fixed it, or reopen the finding"
        )
    if review is not None and review_info.get("review"):
        warned = [
            f
            for f in review_rules(workspace, records)
            if f.file == review_info["review"] and f.level in ("warning", "error")
        ]
        if warned:
            reasons.append(
                f"{review_info['review']} has {len(warned)} cheme.review-* warning(s), "
                f"first: {warned[0].message} (run `cheme validate`)"
            )
    if reasons:
        raise SignOffRefused(reasons)

    branch = gitinfo.branch(root)
    default = gitinfo.default_branch(root)
    moment = (now or datetime.datetime.now(datetime.UTC)).replace(microsecond=0)
    entry: dict[str, Any] = {
        "stage": stage,
        "commit": head,
        "date": moment.isoformat().replace("+00:00", "Z"),
        "signed_by": signer,
        "branch": branch,
        "default_branch": default,
        "review": None,
        **review_info,
        "stages": stages,
        "checks": [result_dict(r) for r in results],
    }
    data = read_status(workspace)
    data["stages"][stage] = entry
    data["checks"] = entry["checks"]
    path = root / STATUS_FILE
    path.parent.mkdir(exist_ok=True)
    ordered = {
        **{k: v for k, v in data.items() if k not in ("stages", "checks")},
        "stages": dict(
            sorted(data["stages"].items(), key=lambda kv: _stage_index(workspace, kv[0]))
        ),
        "checks": data["checks"],
    }
    path.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8", newline="")
    notes = []
    if branch and default and branch != default:
        notes.append(
            f"note: signed off on branch {branch}, not {default}: merge to make the sign-off "
            "effective (a stage is reached when its sign-off is on the default branch)"
        )
    if review is None:
        notes.append("note: no --review: the sign-off names no review record")
    return SignOffResult(entry, notes)


def _fixed_in_history(root: Path, commit: str | None) -> bool:
    """*commit* is a commit and an ancestor of (or equal to) HEAD."""
    sha = gitinfo.resolve(root, commit) if commit else None
    return sha is not None and gitinfo.is_ancestor(root, sha)


def _stage_index(workspace: Workspace, stage: str) -> tuple[int, str]:
    ids = [s.id for s in workspace.config().stages]
    return (ids.index(stage) if stage in ids else len(ids), stage)
