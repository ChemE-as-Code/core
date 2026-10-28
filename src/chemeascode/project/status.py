"""``cheme status``: where a plant repository stands, in one read-only summary.

The JSON (``cheme status --json``, ``GET /api/status``) has these keys, kept stable for
scripts (new keys may be added):

``plant``
    ``{name, stage, stages: [ids]}`` from ``plant.yaml``.
``sheets``
    One entry per sheet in ``plant.yaml`` order (else every ``pid/*.xml``): ``{id, file, state,
    drawn: {equipment, lines, instruments}, assigned: {...}, missing: {...}}``. ``state`` is
    ``drawn`` (it draws a tagged item), ``empty`` (it loads but draws none: an empty frame),
    ``missing`` (declared, no file: planned) or ``not-loaded`` (pyDEXPI cannot load it).
    ``assigned`` counts the list entries whose ``sheet:`` names it, ``missing`` lists those of
    them it does not draw.
``next_sheet``
    The first sheet whose state is ``empty`` or ``missing`` (the next one to draw), or null.
``validation``
    ``{errors, warnings, infos, by_rule: {rule: count}, not_on_pid: {sheet id or "unassigned":
    count}}``; ``not_on_pid`` counts listed items, also those validate folds into one finding.
``gates``
    ``{stage: [{id, title, status, detail}]}`` for every stage of ``plant.yaml``; nothing is
    written.
``signoffs``
    ``{stage: {commit, date, signed_by, branch, review, on_default_branch}}`` from
    ``checks/status.json`` (empty when there is none); ``on_default_branch`` is false when the
    signed-off commit is not on the default branch (the sign-off has not taken effect).
``legacy_status``
    For a 0.3 ``checks/status.json`` (gates only): ``{commit (that wrote it), stages, checks,
    passed, on_default_branch}``; else null.
``reviews``
    ``{records, open: [{id, severity, record, finding}]}``: the open review findings.
``git``
    ``{is_repo, branch, head, default_branch, dirty: [paths], ahead, behind}``; ``dirty`` is
    null when git cannot tell which paths are uncommitted.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from chemeascode.foundation import gitinfo
from chemeascode.foundation.workspace import Workspace

_NOT_ON_PID = (
    "cheme.equipment-not-on-pid",
    "cheme.line-not-on-pid",
    "cheme.instrument-not-on-pid",
    "cheme.piping-item-not-on-pid",
)
_LISTS = (
    ("equipment", "equipment", "tag", "equipment"),
    ("lines", "lines", "number", "lines"),
    ("instruments", "instruments", "tag", "instruments"),
)


def _lists(workspace: Workspace) -> dict[str, Any]:
    return workspace.parsed_lists()


def plant_status(workspace: Workspace, run_gates: bool = True) -> dict[str, Any]:
    """The summary described in the module docstring."""
    from chemeascode.domains.piping.sheet_query import load_sheets, sheet_items
    from chemeascode.foundation.reviews import (
        latest_rows,
        load_records,
        open_blocking,
        open_findings,
        worst_severities,
    )
    from chemeascode.project.signoff import read_status
    from chemeascode.project.validate import validate_workspace

    config = workspace.config()
    parsed = _lists(workspace)
    loaded = load_sheets(workspace)

    sheets = []
    for sheet in loaded:
        entry: dict[str, Any] = {"id": sheet.sheet_id, "file": sheet.name}
        drawn_tags: dict[str, set[str]] = {kind: set() for _, _, _, kind in _LISTS}
        if sheet.model is None:
            missing_file = not (workspace.root / sheet.name).is_file()
            entry["state"] = "missing" if missing_file else "not-loaded"
            if not missing_file:
                entry["error"] = sheet.error
        else:
            for item in sheet_items(sheet.model, sheet.name):
                kind = {"equipment": "equipment", "line": "lines", "instrument": "instruments"}
                if item.kind in kind:
                    drawn_tags[kind[item.kind]].add(item.tag)
            entry["state"] = "drawn" if any(drawn_tags.values()) else "empty"
        assigned: dict[str, int] = {}
        missing: dict[str, list[str]] = {}
        for kind, key, attribute, label in _LISTS:
            model = parsed.get(kind)
            tags = [
                str(getattr(e, attribute)).strip()
                for e in getattr(model, key, None) or []
                if (e.sheet or "").strip() in (sheet.sheet_id, sheet.name)
            ]
            assigned[label] = len(tags)
            missing[label] = [t for t in tags if t not in drawn_tags[label]]
        entry["drawn"] = {label: len(tags) for label, tags in drawn_tags.items()}
        entry["assigned"] = assigned
        entry["missing"] = missing
        sheets.append(entry)
    next_sheet = next((s["id"] for s in sheets if s["state"] in ("empty", "missing")), None)

    report = validate_workspace(workspace)
    levels = Counter(f.level for f in report.findings)
    by_rule = Counter(f.rule for f in report.findings)
    sheet_of: dict[str, str] = {}
    for kind, key, attribute, _ in (*_LISTS, ("piping_items", "piping_items", "tag", "")):
        for e in getattr(parsed.get(kind), key, None) or []:
            sheet_of.setdefault(str(getattr(e, attribute)).strip(), (e.sheet or "").strip())
    not_on_pid: Counter[str] = Counter()
    for finding in report.findings:
        if finding.rule in _NOT_ON_PID:
            # One id per item: a single item's warning has one, the info finding that folds
            # the items held for an undrawn sheet lists them all (each counts on its own sheet).
            for item in finding.ids:
                tag = item.split("/", 1)[0]
                not_on_pid[sheet_of.get(tag) or "unassigned"] += 1

    gates: dict[str, list[dict[str, Any]]] = {s.id: [] for s in config.stages}
    if run_gates:
        from chemeascode.project.checks import run_checks

        for result in run_checks(workspace):
            gates.setdefault(result.stage, []).append(
                {
                    "id": result.id,
                    "title": result.title,
                    "status": result.status,
                    "detail": result.detail,
                }
            )

    git = gitinfo.repo_state(workspace.root)
    signoffs = {}
    for stage, entry in read_status(workspace)["stages"].items():
        if not isinstance(entry, dict):
            continue
        commit = str(entry.get("commit") or "")
        on_default = None
        if git.is_repo and commit and git.default_branch:
            on_default = gitinfo.resolve(workspace.root, commit) is not None and (
                gitinfo.is_ancestor(workspace.root, commit, git.default_branch)
            )
        signoffs[stage] = {
            "commit": commit,
            "date": entry.get("date"),
            "signed_by": entry.get("signed_by"),
            "branch": entry.get("branch"),
            "review": entry.get("review"),
            "reviewer_kind": entry.get("reviewer_kind"),
            "on_default_branch": on_default,
        }

    status_file = read_status(workspace)
    path = workspace.root / "checks" / "status.json"
    legacy = None
    if path.is_file() and not status_file["stages"] and status_file["checks"]:
        # A 0.3 file: gates only. Name the commit that wrote it.
        last = None
        if git.is_repo:
            found = gitinfo.git(
                workspace.root, "log", "-1", "--format=%H", "--", "checks/status.json"
            )
            last = found.stdout.strip() or None
        on_default = None
        if last and git.default_branch:
            on_default = gitinfo.is_ancestor(workspace.root, last, git.default_branch)
        stages_named = sorted(
            {str(c.get("stage", "")) for c in status_file["checks"] if isinstance(c, dict)}
        )
        legacy = {
            "commit": last,
            "stages": stages_named,
            "checks": len(status_file["checks"]),
            "passed": sum(
                isinstance(c, dict) and c.get("status") == "pass" for c in status_file["checks"]
            ),
            "on_default_branch": on_default,
        }

    records = load_records(workspace)
    worst = worst_severities(records)  # as sign-off rates them
    open_rows = [
        {
            "id": r.id,
            "severity": worst.get(r.id, r.severity),
            "record": r.record,
            "finding": r.finding,
        }
        for r in open_findings(records)
    ]
    # rows whose id is not <record>#<n> block a sign-off on their own (open_blocking)
    followed = latest_rows(records)
    open_rows += [
        {"id": r.id, "severity": r.severity, "record": r.record, "finding": r.finding}
        for r in open_blocking(records)
        if r.id not in followed
    ]
    return {
        "plant": {
            "name": config.name,
            "stage": config.stage,
            "stages": [s.id for s in config.stages],
        },
        "sheets": sheets,
        "process": _process_summary(workspace),
        "next_sheet": next_sheet,
        "validation": {
            "errors": levels["error"],
            "warnings": levels["warning"],
            "infos": levels["info"],
            "by_rule": dict(sorted(by_rule.items())),
            "not_on_pid": dict(sorted(not_on_pid.items())),
        },
        "gates": gates,
        "signoffs": signoffs,
        "legacy_status": legacy,
        "reviews": {"records": len(records), "open": open_rows},
        "git": {
            "is_repo": git.is_repo,
            "branch": git.branch,
            "head": git.head,
            "default_branch": git.default_branch,
            "dirty": git.dirty,
            "ahead": git.ahead,
            "behind": git.behind,
        },
    }


def _process_summary(workspace: Workspace) -> dict[str, Any] | None:
    from chemeascode.domains.process.summary import status_summary

    try:
        return status_summary(workspace)
    except Exception:  # noqa: BLE001 - validate reports what is wrong with the process files
        return None


def status_lines(data: dict[str, Any]) -> list[str]:
    """``cheme status`` as text."""
    plant = data["plant"]
    lines = [f"{plant['name']}: stage {plant['stage']} ({' > '.join(plant['stages'])})"]
    git = data["git"]
    if git["is_repo"]:
        where = git["branch"] or "detached HEAD"
        extra = ""
        if git["branch"] and git["default_branch"] and git["branch"] != git["default_branch"]:
            extra = f", {git['ahead']} ahead / {git['behind']} behind {git['default_branch']}"
        if git["dirty"] is None:
            dirty = ", uncommitted changes unknown (git status failed)"
        else:
            dirty = f", {len(git['dirty'])} uncommitted path(s)" if git["dirty"] else ", clean"
        lines.append(f"git: {where} at {(git['head'] or 'no commit')[:12]}{extra}{dirty}")
    else:
        lines.append("git: not a repository")
    lines.append("sheets:")
    for sheet in data["sheets"]:
        drawn = sheet["drawn"]
        missing = {k: v for k, v in sheet["missing"].items() if v}
        text = (
            f"  {sheet['id']} {sheet['file']}: {sheet['state']}; drawn {drawn['equipment']} "
            f"equipment, {drawn['lines']} lines, {drawn['instruments']} instruments"
        )
        if missing:
            count = sum(len(v) for v in missing.values())
            shown = ", ".join(t for v in missing.values() for t in v[:4])
            text += f"; {count} listed for it not drawn ({shown}{', ...' if count > 4 else ''})"
        lines.append(text)
    if not data["sheets"]:
        lines.append("  none")
    process = data.get("process")
    if process:
        balance = ", ".join(f"{n} {s}" for s, n in sorted(process["block_balances"].items()))
        lines.append(
            f"process: {process['blocks']} block(s), {process['steps']} step(s), "
            f"{process['streams']} stream(s); block balances ({process['case']}): "
            f"{balance or 'none'}"
        )
    lines.append(f"next sheet to draw: {data['next_sheet'] or 'none'}")
    v = data["validation"]
    lines.append(f"validate: {v['errors']} error(s), {v['warnings']} warning(s), {v['infos']} info")
    if v["not_on_pid"]:
        lines.append(
            "  not on a P&ID, by assigned sheet: "
            + ", ".join(f"{k} {n}" for k, n in v["not_on_pid"].items())
        )
    top = sorted(v["by_rule"].items(), key=lambda kv: -kv[1])[:6]
    if top:
        lines.append("  by rule: " + ", ".join(f"{rule} {n}" for rule, n in top))
    lines.append("gates:")
    for stage, gates in data["gates"].items():
        counts = Counter(g["status"] for g in gates)
        failing = [g["id"] for g in gates if g["status"] == "fail"]
        summary = f"{counts['pass']} ok, {counts['fail']} fail, {counts['n/a']} n/a"
        lines.append(f"  {stage}: {summary}" + (f" ({', '.join(failing)})" if failing else ""))
    legacy = data.get("legacy_status")
    none = " none (no checks/status.json entry)" if not legacy else ""
    lines.append("sign-offs:" + ("" if data["signoffs"] else none))
    if legacy:
        flag = ""
        if legacy["on_default_branch"] is False:
            flag = " -- NOT on the default branch"
        lines.append(
            f"  checks/status.json in the 0.3 format (no stage, commit or signer): "
            f"{legacy['passed']}/{legacy['checks']} gates passed of stage(s) "
            f"{', '.join(legacy['stages'])}, written in {str(legacy['commit'] or '?')[:12]}{flag}"
        )
    for stage, entry in data["signoffs"].items():
        flag = ""
        if entry["on_default_branch"] is False:
            flag = " -- NOT on the default branch: merge to make it effective"
        lines.append(
            f"  {stage}: {str(entry['commit'])[:12]} {entry['date']} by {entry['signed_by']}"
            f" on {entry['branch']}"
            + (f", review {entry['review']}" if entry["review"] else "")
            + flag
        )
    reviews = data["reviews"]
    lines.append(f"reviews: {reviews['records']} record(s), {len(reviews['open'])} open finding(s)")
    for row in reviews["open"][:10]:
        lines.append(f"  {row['id']} ({row['severity'] or '?'}): {row['finding']}")
    return lines


def to_json(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2)
