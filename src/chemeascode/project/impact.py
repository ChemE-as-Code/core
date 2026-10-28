"""Change impact: which artifacts rest on sources that changed since they were made.

``cheme impact`` (read-only). Every finding is ``cheme.review-needed`` at level info and
names the artifact, the changed source and both revisions or fingerprints. It is conservative:
a changed source means a person or agent should look again, not that the artifact is wrong.
Nothing is regenerated, rewritten or marked invalid, and ``validate``, ``check`` and ``status``
are unaffected.

The signals are the ones plant repositories already record:

- **review records**: files of a record's ``scope`` changed since its ``reviewed_commit`` (or
  that cannot be told: git fails, the commit is unknown here), unless a later record of the
  same topic, whose commit is known, covers the file (it supersedes the earlier review for that
  file); the ``basis`` of the latest record of each topic;
- **review basis**: an entry of the optional ``basis:`` (``{path, revision, relation}``) whose
  path changed since its revision (a commit, or ``sha256:<hex>``);
- **generated sheets**: a BFD/PFD whose recorded ``source_sha256`` no longer matches
  ``process/*.yaml`` (what ``validate`` reports as ``cheme.generated-outdated``);
- **calculated stream values** whose input fingerprint no longer matches their inputs
  (``cheme.process-calculated-stale``);
- **the generated 3D model** ``layout/plant-model.yaml`` whose recorded input fingerprints no
  longer match (what ``validate`` reports as ``cheme.layout-model-outdated``);
- **HAZOP studies**: an analysed input changed since the revision the study records
  (``cheme.hazop-input-changed``), or a band looked up from a rating or matrix that changed
  since (``cheme.hazop-band-stale``).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from chemeascode.foundation import gitinfo, provenance
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace

RULE = "cheme.review-needed"


def _shown(paths: list[str]) -> str:
    return ", ".join(paths[:6]) + (f" and {len(paths) - 6} more" if len(paths) > 6 else "")


def _review_findings(workspace: Workspace) -> list[Finding]:
    from chemeascode.foundation.reviews import _covers, load_records, scope_changes, scope_path

    found = []
    records = [r for r in load_records(workspace) if r.front is not None]  # oldest first
    latest = {r.front.topic: r for r in records}
    commits = {r.name: gitinfo.resolve(workspace.root, r.front.reviewed_commit) for r in records}
    for position, record in enumerate(records):
        front = record.front
        # a later record of the same topic supersedes this one for the files it covers, when
        # its own commit is known here
        later = [
            r.front.scope
            for r in records[position + 1 :]
            if r.front.topic == front.topic and commits[r.name] is not None
        ]

        def superseded(path: str, later: list[list[str]] = later) -> bool:
            return any(_covers(scope, path) for scope in later)

        commit = commits[record.name]
        if all(superseded(scope_path(e)) for e in front.scope):
            changed: list[str] | None = []
        elif commit is None:
            changed = None
            what = (
                f"reviewed_commit {front.reviewed_commit[:12]} cannot be resolved here: cannot "
                "tell whether its scope changed"
            )
        else:
            changed = scope_changes(workspace.root, commit, front.scope)
            if changed is None:
                what = (
                    "cannot tell whether its scope changed since the reviewed commit "
                    f"{front.reviewed_commit[:12]} (git failed)"
                )
            else:
                changed = [p for p in changed if p != record.name and not superseded(p)]
                what = (
                    f"{_shown(changed)} changed since the reviewed commit "
                    f"{front.reviewed_commit[:12]} (now "
                    f"{(gitinfo.head(workspace.root) or 'uncommitted')[:12]})"
                )
        if changed is None or changed:
            found.append(
                Finding(
                    record.name,
                    "info",
                    RULE,
                    f"{front.topic} review: {what}",
                    line=record.front_lines.get("reviewed_commit"),
                    key="scope",
                    hint="review the changes and write a new record (skill review); the "
                    "record itself stays as it is",
                )
            )
        if latest[front.topic] is not record:
            continue  # the basis of a topic is the latest record's
        for i, basis in enumerate(front.basis):
            changed = provenance.changed_since(workspace.root, basis.path, basis.revision)
            if changed == []:
                continue
            what = (
                f"{_shown(changed)} changed since {basis.revision[:19]}"
                if changed
                else f"revision {basis.revision[:19]} of {basis.path} cannot be resolved here"
            )
            found.append(
                Finding(
                    record.name,
                    "info",
                    RULE,
                    f"{front.topic} review {basis.relation} {basis.path}: {what}",
                    line=record.front_lines.get("basis"),
                    key=f"basis[{i}]:{basis.path}",
                    hint="check whether the review still holds for the current "
                    f"{basis.path}; record a new review with an updated basis",
                )
            )
    return found


def _process_findings(workspace: Workspace) -> list[Finding]:
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process import provenance as sheet_provenance
    from chemeascode.domains.process.model import has_process, load
    from chemeascode.domains.process.props import stale
    from chemeascode.domains.process.sheets import meta_for, process_entries

    if not has_process(workspace.root):
        return []
    process, findings = load(workspace.root)
    if process is None or any(f.level == "error" for f in findings):
        return []  # validate reports why; nothing can be compared
    found = []
    for entry in process_entries(workspace):
        path = workspace.sheet_path(entry.file)
        if path is None or not path.is_file():
            continue
        record = sheet_provenance.read(path.read_bytes())
        if record is None:
            continue  # not generated by cheme-as-code: validate reports generated-edited
        expected = sheet_provenance.source_fingerprint(
            process, entry.kind, meta_for(workspace, entry, process)
        )
        recorded = record.get("source_sha256") or ""
        if recorded != expected:
            found.append(
                Finding(
                    workspace.relative(path),
                    "info",
                    RULE,
                    f"{entry.kind} sheet {entry.id} is derived from process/*.yaml, which "
                    f"changed since it was generated (source {recorded[:12]}, now "
                    f"{expected[:12]})",
                    ids=[entry.id],
                    key="source",
                    hint=f"rebuild with cheme process build {entry.id} when the change is "
                    "meant, then review the sheet and the P&IDs drawn from it",
                )
            )
    for stream in process.flowsheet.streams:
        for case in stream.state:
            names = stale(process, stream, case)
            if names:
                found.append(
                    Finding(
                        FLOWSHEET_FILE,
                        "info",
                        RULE,
                        f"stream {stream.id} ({case}): calculated {', '.join(names)} were "
                        "calculated from inputs that have changed since",
                        ids=[stream.id],
                        key=f"{stream.id}:{case}",
                        hint="recalculate with cheme process propagate --fill, "
                        "cheme process simulate --fill or cheme process props --fill",
                    )
                )
    return found


def _layout_findings(workspace: Workspace) -> list[Finding]:
    """The generated 3D model when one of its recorded inputs changed since it was built."""
    from chemeascode.domains.spatial.model import changed_inputs, read

    path = workspace.layout_model_file()
    if path is None:
        return []
    document = read(path.read_text(encoding="utf-8"))
    record = document.get("provenance") if document else None
    if not isinstance(record, dict) or not isinstance(record.get("sources"), dict):
        return []  # not generated by cheme-as-code: validate reports layout-model-edited
    changed = changed_inputs(workspace, record["sources"])
    if not changed:
        return []
    return [
        Finding(
            workspace.relative(path),
            "info",
            RULE,
            f"the 3D model is derived from {_shown(changed)}, which changed since it was built",
            key="sources",
            hint="rebuild with cheme layout build when the change is meant, then review the layout",
        )
    ]


def _hazop_findings(workspace: Workspace) -> list[Finding]:
    """HAZOP studies whose analysed inputs changed, or whose bands are stale."""
    from chemeascode.domains.safety.hazop import (
        input_findings,
        rating_rows,
        workspace_studies,
    )

    found = []
    for loaded in workspace_studies(workspace):
        if loaded.model is None:
            continue
        for finding in input_findings(workspace, loaded):
            found.append(
                Finding(
                    finding.file,
                    "info",
                    RULE,
                    f"HAZOP study {loaded.model.id}: {finding.message}",
                    line=finding.line,
                    ids=finding.ids,
                    key=finding.key,
                    hint=finding.hint,
                )
            )
        stale = sorted(
            {
                r.scenario
                for r in rating_rows(loaded)
                if r.state in ("stale", "edited")
                or (r.state == "unresolved" and r.rating.band is not None)
            }
        )
        if stale:
            found.append(
                Finding(
                    loaded.path,
                    "info",
                    RULE,
                    f"HAZOP study {loaded.model.id}: bands of {_shown(stale)} were looked up "
                    "from ratings or a matrix that changed since",
                    ids=stale[:6],
                    key="bands",
                    hint=f"reassess, then cheme safety hazop rate {loaded.model.id} --write",
                )
            )
    return found


def review_needed(workspace: Workspace) -> list[Finding]:
    """Every artifact whose recorded source revision or fingerprint no longer matches the
    current source, as ``cheme.review-needed`` findings (info), sorted by file."""
    found = _review_findings(workspace) + _process_findings(workspace)
    found += _layout_findings(workspace)
    found += _hazop_findings(workspace)
    return sorted(found, key=lambda f: (f.file, f.key))


def impact_report(workspace: Workspace) -> dict[str, Any]:
    """``cheme impact --json`` and ``GET /api/impact``: the HEAD commit and the
    :func:`review_needed` findings, each with its stable ``id``."""
    return {
        "commit": gitinfo.head(workspace.root),
        "findings": [{**asdict(f), "id": f.id} for f in review_needed(workspace)],
    }
