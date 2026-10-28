"""Review records in ``reviews/``: front matter, finding ids and statuses, review gates.

A review record is ``reviews/<YYYY-MM-DD>-<topic>.md`` with YAML front matter (schema
:class:`~chemeascode.foundation.schemas.reviews.ReviewRecord`, ``cheme schema review``) and
Markdown tables of findings. A findings table is any table with an ``id`` and a ``status``
column. Ids are ``<record file stem>#<n>`` (``2026-10-18-o2-safety#3``), unique across the
repository. A status is one of

- ``open``;
- ``closed <commit>``: the commit that fixed it;
- ``accepted: <reason, by whom>``;
- ``superseded by <id>``.

Each record is a snapshot and is not edited after it is committed: a later record lists the
earlier findings that are still open under ``## Previous findings`` with their current status. A
finding's status is the one in the latest record that lists it (records ordered by date, then by
the commit that added them, then by name).
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.foundation import gitinfo
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import content_changes
from chemeascode.foundation.schemas.reviews import ReviewRecord
from chemeascode.foundation.workspace import Workspace

REVIEWS_DIR = "reviews"
#: Severities that block a sign-off while open.
BLOCKING = frozenset({"critical", "high", "major"})
SEVERITIES = frozenset({"critical", "high", "major", "medium", "minor", "low", "info", "note"})

_DATE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_ID = re.compile(r"^(?P<stem>[^\s#|]+)#(?P<n>\d+)$")
_STATUS = (
    ("open", re.compile(r"^open$", re.IGNORECASE)),
    ("closed", re.compile(r"^closed\s+(?P<commit>[0-9a-f]{7,40})\b", re.IGNORECASE)),
    ("accepted", re.compile(r"^accepted:\s*\S", re.IGNORECASE)),
    ("superseded", re.compile(r"^superseded\s+by\s+(?P<by>\S+#\d+)", re.IGNORECASE)),
)


def status_kind(status: str) -> str | None:
    """``open``, ``closed``, ``accepted`` or ``superseded``; None when not in the vocabulary."""
    text = status.strip().strip("`").strip()
    for kind, pattern in _STATUS:
        if pattern.match(text):
            return kind
    return None


def closing_commit(status: str) -> str | None:
    match = _STATUS[1][1].match(status.strip().strip("`").strip())
    return match.group("commit") if match else None


@dataclass
class FindingRow:
    """One row of a findings table."""

    id: str
    severity: str
    status: str
    finding: str
    section: str  # "findings" or "previous" (## Previous findings), else the heading
    line: int
    record: str

    @property
    def kind(self) -> str | None:
        return status_kind(self.status)

    @property
    def is_open(self) -> bool:
        return self.kind in ("open", None)


@dataclass
class Record:
    """One review record."""

    name: str  # repo-relative path
    stem: str
    text: str
    has_front: bool = False
    front: ReviewRecord | None = None
    #: ``(message, line)`` for each front matter problem.
    front_errors: list[tuple[str, int | None]] = field(default_factory=list)
    front_lines: dict[str, int] = field(default_factory=dict)
    body_start: int = 1
    sections: list[str] = field(default_factory=list)
    rows: list[FindingRow] = field(default_factory=list)
    order: tuple[Any, ...] = ()
    committed: bool = False

    @property
    def date(self) -> str:
        if self.front is not None and self.front.date is not None:
            return self.front.date.isoformat()
        match = _DATE.match(self.stem)
        return match.group(1) if match else ""

    def has_section(self, title: str) -> bool:
        return any(s.lower() == title.lower() for s in self.sections)


def _front_matter(record: Record) -> None:
    lines = record.text.splitlines()
    if not lines or lines[0].strip() != "---":
        return
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in ("---", "...")), None)
    record.has_front = True
    if end is None:
        record.front_errors.append(("front matter has no closing '---' line", 1))
        return
    record.body_start = end + 2
    block = "\n".join(lines[1:end])
    try:
        data = yaml.safe_load(block)
        node = yaml.compose(block)
    except yaml.YAMLError as failure:
        mark = getattr(failure, "problem_mark", None)
        line = mark.line + 2 if mark else 1
        record.front_errors.append((f"front matter is not YAML: {failure}".splitlines()[0], line))
        return
    if isinstance(node, yaml.MappingNode):
        for key, _ in node.value:
            if isinstance(key, yaml.ScalarNode):
                record.front_lines[key.value] = key.start_mark.line + 2
    if not isinstance(data, dict):
        record.front_errors.append(("front matter must be a mapping", 1))
        return
    try:
        record.front = ReviewRecord.model_validate(data)
    except ValidationError as failure:
        for error in failure.errors():
            key = str(error["loc"][0]) if error["loc"] else ""
            where = ".".join(str(p) for p in error["loc"])
            record.front_errors.append((f"{where}: {error['msg']}", record.front_lines.get(key, 1)))


def _cells(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|"):
        body = body[:-1]
    return [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]


_SEPARATOR = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?$")


def _tables(record: Record) -> None:
    lines = record.text.splitlines()
    section = ""
    i = record.body_start - 1
    while i < len(lines):
        line = lines[i]
        heading = re.match(r"^#{2,6}\s+(.*?)\s*#*\s*$", line)
        if heading:
            section = heading.group(1).strip()
            record.sections.append(section)
            i += 1
            continue
        if (
            line.lstrip().startswith("|")
            and i + 1 < len(lines)
            and _SEPARATOR.match(lines[i + 1].strip())
        ):
            header = [h.lower().strip("*_ ") for h in _cells(line)]
            i += 2
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append((i + 1, _cells(lines[i])))
                i += 1
            if "id" not in header or "status" not in header:
                continue
            kind = "previous" if section.lower().startswith("previous") else "findings"
            if kind == "findings" and section and not section.lower().startswith("finding"):
                kind = section.lower()
            for number, cells in rows:
                row = dict(zip(header, cells + [""] * (len(header) - len(cells)), strict=False))
                record.rows.append(
                    FindingRow(
                        id=row.get("id", "").strip("`"),
                        severity=row.get("severity", "").strip("`*_ ").lower(),
                        status=row.get("status", "").strip(),
                        finding=row.get("finding", ""),
                        section=kind,
                        line=number,
                        record=record.name,
                    )
                )
            continue
        i += 1


def parse_record(name: str, text: str) -> Record:
    record = Record(name=name, stem=PurePosixPath(name).stem, text=text)
    _front_matter(record)
    _tables(record)
    return record


def record_paths(workspace: Workspace) -> list[Path]:
    """The review records: ``reviews/*.md`` except ``README.md``."""
    folder = workspace.root / REVIEWS_DIR
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in folder.glob("*.md")
        if p.is_file() and p.name.lower() != "readme.md" and workspace.contains(p)
    )


def load_records(workspace: Workspace, paths: list[Path] | None = None) -> list[Record]:
    """Every review record (or those of *paths*), oldest first."""
    in_git = gitinfo.is_repo(workspace.root)
    records = []
    for path in record_paths(workspace) if paths is None else paths:
        name = workspace.relative(path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        record = parse_record(name, text)
        added = gitinfo.first_added(workspace.root, name) if in_git else None
        record.committed = added is not None
        record.order = (record.date, added if added is not None else float("inf"), name)
        records.append(record)
    records.sort(key=lambda r: r.order)
    return records


def latest_rows(records: list[Record]) -> dict[str, FindingRow]:
    """Each finding id with the row of the latest record (*records* oldest first) listing it."""
    latest: dict[str, FindingRow] = {}
    for record in records:
        for row in record.rows:
            if _ID.match(row.id):
                latest[row.id] = row
    return latest


def open_findings(records: list[Record]) -> list[FindingRow]:
    """Findings whose latest status is open (or not in the vocabulary)."""
    return [row for row in latest_rows(records).values() if row.is_open]


#: Severities from the most severe; the blocking ones first.
_RANK = ("critical", "high", "major", "medium", "minor", "low", "info", "note")


def worst_severities(records: list[Record]) -> dict[str, str]:
    """Each finding id with the most severe severity any row of *records* gives it.

    A later record that carries a finding forward without a severity, or with a lower one, does
    not lower it: a finding stays as severe as it was first rated until it is closed, accepted
    or superseded."""
    worst: dict[str, str] = {}
    for record in records:
        _rate(worst, record)
    return worst


def _rate(worst: dict[str, str], record: Record) -> None:
    """Raise the severities in *worst* to those *record*'s rows give."""
    for row in record.rows:
        if not _ID.match(row.id) or row.severity not in SEVERITIES:
            continue
        known = worst.get(row.id)
        if known is None or _RANK.index(row.severity) < _RANK.index(known):
            worst[row.id] = row.severity


def open_blocking(records: list[Record]) -> list[FindingRow]:
    """The findings that block a sign-off: latest status open (or not in the vocabulary), and a
    blocking severity in any row that lists it (:func:`worst_severities`). Each is the latest
    row, with that severity. Sign-off, :func:`coverage` and the HAZOP review status use this.

    A row whose id is not ``<record>#<n>`` cannot be followed into later records, so an open one
    of a blocking severity blocks on its own, for as long as its record lists it
    (``cheme.review-finding-id`` asks for a proper id)."""
    worst = worst_severities(records)
    blocking = [
        replace(row, severity=worst[row.id])
        for row in open_findings(records)
        if worst.get(row.id) in BLOCKING
    ]
    blocking += [
        row
        for record in records
        for row in record.rows
        if not _ID.match(row.id) and row.is_open and row.severity in BLOCKING
    ]
    return blocking


def scope_path(entry: str) -> str:
    """A ``scope`` entry in repository-relative form: without surrounding blanks, leading
    ``./`` or ``/`` and trailing ``/``; ``""`` for the whole repository."""
    path = entry.strip()
    while path.startswith(("/", "./")):
        path = path.removeprefix("./").removeprefix("/")
    path = path.rstrip("/")
    return "" if path == "." else path


def scope_changes(root: Path, commit: str, scope: list[str]) -> list[str] | None:
    """The files of *scope* (entries as :func:`scope_path` reads them) that changed since
    *commit*; None when git cannot tell, which never counts as unchanged. A file whose only
    change is a digest (a regenerated output with a new source or model fingerprint,
    :func:`~chemeascode.foundation.provenance.digest_only`) has not changed."""
    return content_changes(root, commit, [scope_path(entry) or "." for entry in scope])


def _overlaps(a: list[str], b: list[str]) -> bool:
    for x in map(scope_path, a):
        for y in map(scope_path, b):
            if x == y or x.startswith(y + "/") or y.startswith(x + "/") or not x or not y:
                return True
    return False


# ---------------------------------------------------------------------------
# validate: cheme.review-*
# ---------------------------------------------------------------------------


def review_rules(workspace: Workspace, records: list[Record] | None = None) -> list[Finding]:
    """The ``cheme.review-*`` findings of every review record."""
    records = load_records(workspace) if records is None else records
    in_git = gitinfo.is_repo(workspace.root)
    findings: list[Finding] = []
    stems = {r.stem for r in records}
    for record in records:
        if not record.has_front:
            findings.append(
                Finding(
                    record.name,
                    "info",
                    "cheme.review-front-matter",
                    "review record without front matter: no `kind: review` gate accepts it",
                    line=1,
                    hint="start it with --- topic, reviewed_commit, scope, reviewer, "
                    "reviewer_kind --- (see `cheme schema review`)",
                )
            )
        for message, line in record.front_errors:
            findings.append(
                Finding(
                    record.name,
                    "warning",
                    "cheme.review-front-matter",
                    message,
                    line=line,
                    hint="see `cheme schema review` and reviews/README.md",
                )
            )
        front = record.front
        if front is not None:
            line = record.front_lines.get("reviewed_commit")
            if in_git and gitinfo.resolve(workspace.root, front.reviewed_commit) is None:
                findings.append(
                    Finding(
                        record.name,
                        "warning",
                        "cheme.review-unknown-commit",
                        f"reviewed_commit {front.reviewed_commit} is not a commit of this "
                        "repository",
                        line=line,
                        hint="give the sha of the commit you reviewed (`git rev-parse HEAD` "
                        "before writing the record)",
                    )
                )
            for path in front.scope:
                raw, clean = path.strip(), scope_path(path)
                if raw and raw != "." and (not clean or raw.rstrip("/") != clean):
                    # a leading / used to make git fail (a warning); ./ always worked (info)
                    findings.append(
                        Finding(
                            record.name,
                            "warning" if raw.startswith("/") else "info",
                            "cheme.review-scope-missing",
                            f"scope names {path!r}, which is not a path from the repository "
                            f"root; it is read as {clean or '.'!r}"
                            + ("" if clean else " (the whole repository)"),
                            line=record.front_lines.get("scope"),
                            hint=f"write {clean or '.'} (no leading / or ./)",
                        )
                    )
                target = workspace.root / clean
                if not raw or ".." in PurePosixPath(clean).parts or not target.exists():
                    findings.append(
                        Finding(
                            record.name,
                            "warning",
                            "cheme.review-scope-missing",
                            f"scope names {path!r}, which is not in the repository",
                            line=record.front_lines.get("scope"),
                            hint="list the files or directories reviewed, from the repository "
                            "root (e.g. pid/P-03.xml)",
                        )
                    )
        findings += _row_rules(workspace, record, stems, in_git)
    findings += _previous_rules(records)
    findings += _severity_rules(records)
    return findings


def _severity_rules(records: list[Record]) -> list[Finding]:
    """An open finding without a severity, and one carried forward with less than the blocking
    severity an earlier row gave it (which still counts: :func:`worst_severities`)."""
    findings = []
    newest = records[-1].name if records else None
    earlier: dict[str, str] = {}
    for record in records:
        # a committed record is not edited: only the newest and uncommitted ones can be fixed
        rows = record.rows if not record.committed or record.name == newest else []
        for row in rows:
            if not row.is_open or not _ID.match(row.id):
                continue
            before = earlier.get(row.id)
            if before in BLOCKING and (
                row.severity not in SEVERITIES or _RANK.index(row.severity) > _RANK.index(before)
            ):
                given = f"severity {row.severity!r}" if row.severity else "no severity"
                findings.append(
                    Finding(
                        record.name,
                        "warning",
                        "cheme.review-finding-status",
                        f"finding {row.id} is listed with {given}, but an earlier record rated "
                        f"it {before}: it still counts as {before} and blocks a sign-off while "
                        "open",
                        line=row.line,
                        ids=[row.id],
                        hint=f"carry the severity forward ({before}); to lower it, close, "
                        "accept or supersede the finding",
                    )
                )
            elif not row.severity and before is None:
                findings.append(
                    Finding(
                        record.name,
                        "info",
                        "cheme.review-finding-status",
                        f"finding {row.id} is open and has no severity",
                        line=row.line,
                        ids=[row.id],
                        hint="give it a severity column (critical, high, medium, low): "
                        "sign-off refuses while a critical or high finding is open",
                    )
                )
        _rate(earlier, record)
    return findings


def _row_rules(
    workspace: Workspace, record: Record, stems: set[str], in_git: bool
) -> list[Finding]:
    findings = []
    for row in record.rows:
        match = _ID.match(row.id)
        if match is None or (row.section == "findings" and match.group("stem") != record.stem):
            findings.append(
                Finding(
                    record.name,
                    "warning",
                    "cheme.review-finding-id",
                    f"finding id {row.id!r} is not <record>#<n>"
                    + (f" with this record's name ({record.stem}#1, ...)" if match else ""),
                    line=row.line,
                    hint=f"number the findings {record.stem}#1, {record.stem}#2, ...; under "
                    "Previous findings keep the earlier record's id",
                )
            )
        elif match.group("stem") not in stems:
            findings.append(
                Finding(
                    record.name,
                    "warning",
                    "cheme.review-finding-id",
                    f"finding {row.id} names record {match.group('stem')}, which is not in "
                    "reviews/",
                    line=row.line,
                    hint="copy the id exactly as the earlier record gives it",
                )
            )
        kind = row.kind
        if kind is None:
            findings.append(
                Finding(
                    record.name,
                    "warning",
                    "cheme.review-finding-status",
                    f"finding {row.id}: status {row.status!r} is not open, closed <commit>, "
                    "accepted: <reason>, or superseded by <id>",
                    line=row.line,
                    ids=[row.id],
                    hint="'partly closed' is not a status: split the finding into a closed and "
                    "an open one",
                )
            )
        elif kind == "closed" and in_git:
            commit = closing_commit(row.status)
            if commit and gitinfo.resolve(workspace.root, commit) is None:
                findings.append(
                    Finding(
                        record.name,
                        "warning",
                        "cheme.review-finding-status",
                        f"finding {row.id} is closed by {commit}, which is not a commit",
                        line=row.line,
                        ids=[row.id],
                        hint="name the commit that fixed it",
                    )
                )
        if row.severity and row.severity not in SEVERITIES:
            findings.append(
                Finding(
                    record.name,
                    "info",
                    "cheme.review-finding-status",
                    f"finding {row.id}: severity {row.severity!r} is not critical, high, medium "
                    "or low",
                    line=row.line,
                    ids=[row.id],
                    hint="sign-off refuses while a critical or high (major) finding is open",
                )
            )
    return findings


def _previous_rules(records: list[Record]) -> list[Finding]:
    """The newest record (and any uncommitted one) must carry earlier open findings forward."""
    findings = []
    newest = records[-1].name if records else None
    for position, record in enumerate(records):
        if record.front is None or (record.committed and record.name != newest):
            continue
        earlier = records[:position]
        scopes = {r.stem: r.front.scope for r in earlier if r.front is not None}
        carried = {row.id for row in record.rows}
        missing = []
        for row in open_findings(earlier):
            origin = _ID.match(row.id)
            scope = scopes.get(origin.group("stem")) if origin else None
            if scope is not None and not _overlaps(scope, record.front.scope):
                continue
            if row.id not in carried:
                missing.append(row.id)
        if not missing:
            continue
        has = record.has_section("Previous findings")
        findings.append(
            Finding(
                record.name,
                "warning",
                "cheme.review-previous-missing",
                (
                    "its Previous findings section does not list "
                    if has
                    else "no ## Previous "
                    "findings section, though earlier reviews of its scope have open findings: "
                )
                + ", ".join(missing),
                line=record.body_start,
                ids=missing,
                hint="list each under ## Previous findings with its current status (open, "
                "closed <commit>, accepted: <reason>, superseded by <id>) and the evidence",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# kind: review
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    status: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


def _candidates(workspace: Workspace, check: Any, records: list[Record]) -> list[Record]:
    found = records
    if check.files:
        found = [
            r for r in found if any(fnmatch.fnmatch(r.name, pattern) for pattern in check.files)
        ]
    if check.topic:
        topic = check.topic.strip().lower()
        found = [
            r
            for r in found
            if r.front is not None
            and r.front.topic.lower() == topic
            or r.front is None
            and topic in r.stem.lower()
        ]
    return found


def _record_problems(workspace: Workspace, check: Any, record: Record) -> list[str]:
    if not record.has_front:
        return ["no front matter"]
    if record.front is None:
        return ["front matter: " + "; ".join(m for m, _ in record.front_errors)]
    front = record.front
    problems = []
    if front.reviewer_kind not in check.require_kind:
        problems.append(
            f"reviewer_kind {front.reviewer_kind} ({front.reviewer}) is not "
            + " or ".join(check.require_kind)
        )
    if not record.has_section("Findings"):
        problems.append("no ## Findings section")
    commit = gitinfo.resolve(workspace.root, front.reviewed_commit)
    if commit is None:
        problems.append(f"reviewed_commit {front.reviewed_commit} is not a commit")
        return problems
    if not gitinfo.is_ancestor(workspace.root, commit):
        problems.append(f"reviewed_commit {front.reviewed_commit[:12]} is not an ancestor of HEAD")
    elif check.current:
        found = scope_changes(workspace.root, commit, front.scope)
        if found is None:
            problems.append(
                f"cannot tell whether its scope changed since {front.reviewed_commit[:12]} "
                "(git failed; check that scope lists paths from the repository root)"
            )
            return problems
        changed = [path for path in found if path != record.name]
        if changed:
            shown = ", ".join(changed[:6]) + (
                f" and {len(changed) - 6} more" if len(changed) > 6 else ""
            )
            problems.append(f"changed since {front.reviewed_commit[:12]}: {shown}")
    return problems


def evaluate_review_gate(
    workspace: Workspace, check: Any, records: list[Record] | None = None
) -> GateResult:
    """``kind: review``: a record for the topic (or files) that is current and of an allowed
    reviewer kind."""
    if not gitinfo.is_repo(workspace.root) or gitinfo.head(workspace.root) is None:
        return GateResult("fail", "a review gate needs a git repository with a commit")
    records = load_records(workspace) if records is None else records
    candidates = _candidates(workspace, check, records)
    what = f"topic {check.topic}" if check.topic else ", ".join(check.files)
    if not candidates:
        return GateResult("fail", f"no review record for {what}")
    failures = []
    for record in reversed(candidates):  # newest first
        problems = _record_problems(workspace, check, record)
        if not problems:
            front = record.front
            assert front is not None
            evidence = {
                "path": record.name,
                "reviewed_commit": front.reviewed_commit,
                "reviewer": front.reviewer,
                "reviewer_kind": front.reviewer_kind,
            }
            detail = f"{record.name}: {front.reviewer_kind} review of {front.reviewed_commit[:12]}"
            if front.reviewer_kind != "human":
                detail += " (agent-reviewed only)"
            return GateResult("pass", detail, evidence)
        failures.append(f"{record.name}: " + "; ".join(problems))
    shown = failures[:3]
    more = f" (and {len(failures) - 3} more record(s))" if len(failures) > 3 else ""
    return GateResult("fail", " | ".join(shown) + more)


# ---------------------------------------------------------------------------
# Review status of one file
# ---------------------------------------------------------------------------


def blocking_ids(records: list[Record], of: list[Record]) -> set[str]:
    """The ids of :func:`open_blocking` (judged on all *records*) that a record of *of* lists."""
    listed = {row.id for record in of for row in record.rows}
    names = {record.name for record in of}
    return {
        row.id
        for row in open_blocking(records)
        if (row.id in listed if _ID.match(row.id) else row.record in names)
    }


def _covers(scope: list[str], path: str) -> bool:
    for entry in map(scope_path, scope):
        if not entry or path == entry or path.startswith(entry + "/"):
            return True
    return False


def coverage(workspace: Workspace, path: str, records: list[Record] | None = None) -> dict:
    """Whether the file *path* is ``drafted``, ``reviewed`` or ``accepted``, by the latest
    review record whose ``scope`` covers it (*records* oldest first).

    ``drafted``: no record covers it, or it changed since the record's ``reviewed_commit`` (or
    that cannot be told, or the commit is not an ancestor of HEAD). ``reviewed``: the record is
    current. ``accepted``: current, by a human (``reviewer_kind: human``, or a review
    ``approved_by`` one), and no finding of a blocking severity of a record covering the file is
    still open. The status says what the records show, not
    that the content is correct; a record is never written or changed here."""
    records = load_records(workspace) if records is None else records
    covering = [r for r in records if r.front is not None and _covers(r.front.scope, path)]
    if not covering:
        return {"status": "drafted", "record": None, "detail": "no review record covers it"}
    record = covering[-1]
    front = record.front
    assert front is not None
    found = {
        "record": record.name,
        "reviewed_commit": front.reviewed_commit,
        "reviewer": front.reviewer,
        "reviewer_kind": front.reviewer_kind,
    }
    commit = gitinfo.resolve(workspace.root, front.reviewed_commit)
    if commit is None:
        detail = f"reviewed_commit {front.reviewed_commit[:12]} cannot be resolved here"
        return {**found, "status": "drafted", "detail": detail}
    if not gitinfo.is_ancestor(workspace.root, commit):
        detail = f"reviewed_commit {front.reviewed_commit[:12]} is not an ancestor of HEAD"
        return {**found, "status": "drafted", "detail": detail}
    changed = content_changes(workspace.root, commit, [path])
    if changed is None:
        detail = f"cannot tell whether it changed since {front.reviewed_commit[:12]} (git failed)"
        return {**found, "status": "drafted", "detail": detail}
    if changed:
        detail = f"changed since the review of {front.reviewed_commit[:12]}"
        return {**found, "status": "drafted", "detail": detail}
    blocking = sorted(blocking_ids(records, covering))
    human = front.reviewer_kind == "human" or bool(front.approved_by)
    if human and not blocking:
        return {**found, "status": "accepted", "detail": f"{record.name}: accepted"}
    why = f"open {', '.join(blocking)}" if blocking else "not reviewed or approved by a human"
    return {**found, "status": "reviewed", "detail": f"{record.name}: {why}"}
