"""``cheme export-static``: the viewer's API of one revision, written to files.

A static snapshot lets the viewer run without a server, for example embedded in the Process
Atlas: every ``GET`` the viewer makes is answered once by :func:`create_app` (the same code as
``cheme serve``, nothing re-implemented) and stored as a file. The viewer's static data source
looks requests up in ``manifest.json`` instead of calling ``/api``.

Contract with the viewer (``src/dataSource.ts``):

- :func:`snapshot_key` names a request: the endpoint without ``/api/``, then ``?`` and the
  query as ``key=value`` pairs, raw (not URL-encoded), sorted by key, joined with ``&``; empty
  values and ``rev`` are left out. ``pid.svg?path=pid/P-01.xml``, ``streams``, ``log?limit=50``.
- ``manifest.json`` maps each key to ``{"file", "status", "type"}``; files are named by a hash of
  the key. A request whose key is missing is not in the snapshot (the viewer says so).
- ``manifest.json`` also records the source: commit, whether the working tree had changes, the
  tool version, and the snapshot schema version, so a stale snapshot can be recognised.
- The LCA follows its publication policy, failing closed (:func:`_lca_withheld`): the ``lca``
  answer stays only when it computes and is publishable (no source ``restricted`` without the
  study's reviewed decision, none ``local``); the committed result files
  (:data:`LCA_RESULT_FILES`) only when, in addition, the committed ``lca/manifest.json`` says so.
  Excluding an LCA input (:data:`LCA_INPUTS`) withholds both. ``manifest.json`` records what is
  withheld and why under ``withheld``. The foreground (``lca/dataset.yaml``, ``inventory.csv``)
  and the run manifest stay.
- ``manifest.json`` records the ``excluded`` globs (sorted): paths matching one are absent from
  the ``tree`` answer, are not exported as ``file`` or ``yaml``, and are left out of the file
  list and findings of ``validate`` and ``impact`` and from the ``checks`` answer's sign-offs
  (:func:`_prune_checks`; see :func:`path_matches`). Every other
  answer built from an excluded file (the server records which files an answer reads) is
  withheld and listed under ``withheld`` (:meth:`_Exporter.get`), except ``repo``; ``kinetics``
  and ``datasheets`` leave the excluded data files and datasheets out instead. The drawing of a
  BFD or PFD sheet is withheld when an input it is generated from (:data:`PROCESS_INPUTS`) is
  excluded. On a case-insensitive filesystem (APFS, NTFS) the globs ignore case.
  A consumer publishing a snapshot can check them; the field is additive, so the schema stays v1.
- The output directory is replaced only when it is empty or holds a previous snapshot, and
  never when it is the plant repository, contains it, or lies inside it other than below
  ``build/`` (:func:`check_output`, ignoring case where the filesystem does). The snapshot is
  written next to it, with the mode a new directory gets, and then moved into place.

What is left out, because a snapshot is one revision and read-only: other revisions, diffs,
``POST /api/checks/run`` and the session token, per-file history, sections at arbitrary
coordinates, and files larger than ``max_file_bytes``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import warnings
from collections.abc import Iterable, Sequence
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlencode

from chemeascode.domains.equipment.datasheets import DATASHEET_DIR
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.project.kinetics import DATA_DIR as KINETICS_DIR

SNAPSHOT_SCHEMA = "cheme/viewer-snapshot/v1"
#: Files above this size are not exported as /api/file or /api/yaml (the P&ID XML is never
#: exported as text; its drawing is).
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024
LOG_LIMIT = 50
TEXT_KINDS = {"yaml", "markdown", "json", "other"}
#: Files derived from the LCA's background (scores, contributions, gaps, the per-scenario
#: records of ``cheme assess lca-scenarios``): withheld with the ``lca`` answer when the results
#: are not publishable. The LCA's policy is the most restrictive of every scenario's, so a
#: publishable LCA has publishable scenario records.
LCA_RESULT_FILES = (
    "lca/results.csv",
    "lca/results.md",
    "lca/gaps.csv",
    "lca/uncertainty.csv",
    "lca/scenarios/**",
)
#: What the BFD and PFD sheets are generated from (``cheme process build``): excluding one
#: withholds their drawings, which show its blocks, streams and materials.
PROCESS_INPUTS = (FLOWSHEET_FILE, MATERIALS_FILE)
#: The name of every file in ``data/`` (see :func:`_file_name`).
DATA_FILE = re.compile(r"[0-9a-f]{20}\.(json|svg|txt)")


class ExportError(ValueError):
    """The snapshot cannot be written as asked (for example, a sheet file is excluded)."""


class ExportWarning(UserWarning):
    """The snapshot was written, but something around it went wrong (for example, the previous
    snapshot could not be removed)."""


def case_insensitive(directory: Path) -> bool:
    """Whether the filesystem holding the existing *directory* ignores case (APFS and NTFS do by
    default): probed with a name that has letters, spelled with its case swapped. The first
    such entry of *directory* comes first (NTFS can set case sensitivity per directory), then
    *directory* itself and its parents."""
    try:
        inside = next((c for c in directory.iterdir() if c.name.swapcase() != c.name), None)
    except OSError:
        inside = None
    for path in (*([inside] if inside else []), directory, *directory.parents):
        swapped = path.with_name(path.name.swapcase()) if path.name else path
        if swapped.name != path.name:
            try:
                return swapped.exists() and os.path.samefile(swapped, path)
            except OSError:
                return False
    return False


def path_matches(path: str, pattern: str, ignore_case: bool = False) -> bool:
    """Whether the repo-relative POSIX *path* matches the glob *pattern*.

    Matched segment by segment: ``**`` matches zero or more whole segments, so ``reviews/**``
    matches ``reviews`` and everything below it and ``**/.gitattributes`` matches that name in
    any directory, the root included. Any other segment is an :func:`fnmatch.fnmatchcase`
    pattern (``*``, ``?``, ``[...]``) that never crosses a ``/``. A pattern without ``**`` and
    without a ``/`` is anchored at the root: ``PROGRESS.md`` is the root file only. With
    *ignore_case* (a case-insensitive filesystem, :func:`case_insensitive`) ``progress.md``
    matches ``PROGRESS.md`` too: the glob names the same file there.
    """
    if ignore_case:
        path, pattern = path.casefold(), pattern.casefold()
    parts = path.split("/")
    globs = pattern.split("/")

    def match(i: int, j: int) -> bool:
        if j == len(globs):
            return i == len(parts)
        if globs[j] == "**":
            return any(match(k, j + 1) for k in range(i, len(parts) + 1))
        return i < len(parts) and fnmatchcase(parts[i], globs[j]) and match(i + 1, j + 1)

    return match(0, 0)


def check_globs(patterns: Iterable[str]) -> list[str]:
    """*patterns* sorted and de-duplicated; :class:`ExportError` for one that cannot match a
    repo-relative path (empty, absolute, or with an empty, ``.`` or ``..`` segment)."""
    checked = set()
    for pattern in patterns:
        segments = pattern.split("/")
        if not pattern or pattern.startswith("/") or any(s in ("", ".", "..") for s in segments):
            raise ExportError(f"--exclude {pattern!r}: not a repo-relative glob like reviews/**")
        checked.add(pattern)
    return sorted(checked)


def _excluded(path: str, patterns: Sequence[str], ignore_case: bool = False) -> bool:
    return any(path_matches(path, pattern, ignore_case) for pattern in patterns)


def _prune_tree(
    tree: list[dict[str, Any]], patterns: Sequence[str], ignore_case: bool = False
) -> list[dict[str, Any]]:
    """*tree* without excluded paths, and without directories that held only excluded paths."""
    kept = [entry for entry in tree if not _excluded(entry["path"], patterns, ignore_case)]
    dropped = {entry["path"] for entry in tree} - {entry["path"] for entry in kept}
    emptied = {
        entry["path"]
        for entry in kept
        if entry["type"] == "dir"
        and any(path.startswith(entry["path"] + "/") for path in dropped)
        and not any(
            other["path"].startswith(entry["path"] + "/") and other["type"] == "file"
            for other in kept
        )
    }
    return [entry for entry in kept if entry["path"] not in emptied]


def _prune_report(
    report: dict[str, Any], patterns: Sequence[str], ignore_case: bool = False
) -> dict[str, Any]:
    """A ``validate`` or ``impact`` answer without excluded files in ``files`` and without
    findings on an excluded ``file`` (their messages may quote the file)."""
    pruned = dict(report)
    if isinstance(report.get("files"), list):
        pruned["files"] = [
            p for p in report["files"] if not _excluded(str(p), patterns, ignore_case)
        ]
    if isinstance(report.get("findings"), list):
        pruned["findings"] = [
            finding
            for finding in report["findings"]
            if not (
                isinstance(finding, dict)
                and _excluded(str(finding.get("file")), patterns, ignore_case)
            )
        ]
    return pruned


#: What a ``checks`` answer says instead of an excluded path in a check's ``detail``.
NOT_IN_SNAPSHOT = "(a file not in this snapshot)"
_PATH_TOKEN = re.compile(r"[^\s:,;()'\"]*[^\s:,;()'\".]")  # no sentence's full stop


def _prune_checks(
    answer: dict[str, Any], patterns: Sequence[str], ignore_case: bool = False
) -> dict[str, Any]:
    """A ``checks`` answer that names no excluded file: a sign-off's ``review`` becomes null, a
    check's ``evidence`` loses an excluded ``path`` and its ``detail`` says
    :data:`NOT_IN_SNAPSHOT` instead. The results themselves stay."""

    def hidden(value: Any) -> bool:
        return isinstance(value, str) and _excluded(value, patterns, ignore_case)

    def check(entry: Any) -> Any:
        if not isinstance(entry, dict):
            return entry
        entry = dict(entry)
        evidence = entry.get("evidence")
        if isinstance(evidence, dict) and hidden(evidence.get("path")):
            entry["evidence"] = {k: v for k, v in evidence.items() if k != "path"}
        if isinstance(entry.get("detail"), str):
            entry["detail"] = _PATH_TOKEN.sub(
                lambda m: NOT_IN_SNAPSHOT if hidden(m.group()) else m.group(), entry["detail"]
            )
        return entry

    def checks(entries: Any) -> Any:
        return [check(e) for e in entries] if isinstance(entries, list) else entries

    pruned = dict(answer)
    if "checks" in answer:
        pruned["checks"] = checks(answer["checks"])
    if isinstance(answer.get("stages"), dict):
        pruned["stages"] = {
            name: {
                **record,
                "checks": checks(record.get("checks")),
                **({"review": None} if hidden(record.get("review")) else {}),
            }
            if isinstance(record, dict)
            else record
            for name, record in answer["stages"].items()
        }
    return pruned


def snapshot_key(endpoint: str, query: dict[str, Any] | None = None) -> str:
    """The manifest key of a request (see the module docstring)."""
    name = endpoint.lstrip("/").removeprefix("api/")
    pairs = [
        f"{key}={value}"
        for key, value in sorted((query or {}).items())
        if key != "rev" and value is not None and value != ""
    ]
    return f"{name}?{'&'.join(pairs)}" if pairs else name


def _file_name(key: str, content_type: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    extension = ".svg" if "svg" in content_type else ".json" if "json" in content_type else ".txt"
    return f"{digest}{extension}"


async def _asgi_get(app: Any, path: str, query: dict[str, Any]) -> tuple[int, str, bytes]:
    """One GET through the ASGI app in process (no HTTP client, no network)."""
    body = bytearray()
    status = 0
    content_type = ""
    received = False

    async def receive() -> dict[str, Any]:
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)  # never asked again for a GET
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        nonlocal status, content_type
        if message["type"] == "http.response.start":
            status = message["status"]
            for name, value in message.get("headers", []):
                if name.lower() == b"content-type":
                    content_type = value.decode("latin-1")
        elif message["type"] == "http.response.body":
            body.extend(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode({k: v for k, v in query.items() if v is not None}).encode(),
        "headers": [(b"host", b"127.0.0.1")],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
        "root_path": "",
    }
    await app(scope, receive, send)
    return status, content_type, bytes(body)


#: Answers kept although they read an excluded file: ``repo`` says only which kinds of files
#: exist besides ``plant.yaml``'s name, stages and sheets, and ``tree`` is pruned.
UNFILTERED = ("repo", "tree")
#: Folders whose excluded files an answer leaves out itself (see :func:`export_static`): the
#: ``kinetics`` answer drops the excluded data files, the ``datasheets`` answers the excluded
#: datasheets and drawings.
PRUNED_FOLDERS = {"kinetics": KINETICS_DIR, "datasheets": DATASHEET_DIR}


class _Exporter:
    def __init__(
        self,
        app: Any,
        out: Path,
        rev: str | None,
        excluded: Sequence[str],
        ignore_case: bool = False,
    ) -> None:
        self.app = app
        self.out = out
        self.rev = rev
        #: The globs whose files no stored answer may be built from.
        self.excluded = excluded
        #: Whether the globs ignore case (a case-insensitive filesystem).
        self.ignore_case = ignore_case
        self.entries: dict[str, dict[str, Any]] = {}
        #: Answers built from an excluded file, by key: the ``withheld`` records.
        self.withheld: dict[str, dict[str, Any]] = {}
        self.loop = asyncio.new_event_loop()

    def _built_from_excluded(self, endpoint: str, reads: set[str]) -> list[str]:
        """The globs matching a file the answer to *endpoint* read (sorted), not counting the
        files its own filter leaves out (:data:`PRUNED_FOLDERS`)."""
        name = endpoint.split("/")[0]
        if name in UNFILTERED:
            return []
        pruned = PRUNED_FOLDERS.get(name)
        return sorted(
            {
                pattern
                for path in reads
                if not (pruned and path.startswith(pruned + "/"))
                for pattern in self.excluded
                if path_matches(path, pattern, self.ignore_case)
            }
        )

    def is_excluded(self, path: str) -> bool:
        """Whether *path* matches one of the excluded globs."""
        return _excluded(path, self.excluded, self.ignore_case)

    def _without_excluded_sources(self, endpoint: str, body: bytes) -> bytes:
        """*body* without the excluded paths in its ``source`` (fingerprints and dirty files).

        The pruned answers (:data:`PRUNED_FOLDERS`) are kept although they read excluded files;
        their ``source`` must not name those files or carry their hashes."""
        if endpoint.split("/")[0] not in PRUNED_FOLDERS:
            return body
        from starlette.responses import JSONResponse

        data = json.loads(body)
        source = data.get("source") if isinstance(data, dict) else None
        if not isinstance(source, dict):
            return body
        fingerprints = source.get("fingerprints")
        if isinstance(fingerprints, dict):
            source["fingerprints"] = {
                p: h for p, h in fingerprints.items() if not self.is_excluded(p)
            }
        dirty = source.get("dirty")
        if isinstance(dirty, list):
            source["dirty"] = [p for p in dirty if not self.is_excluded(p)]
        return JSONResponse(data).body

    def get(
        self, endpoint: str, query: dict[str, Any] | None = None, keep_errors: bool = True
    ) -> Any:
        """Request *endpoint*, store the answer under its key, return parsed JSON (or None).

        An answer (or error) built from a file matching an excluded glob is not stored: it is
        recorded in :attr:`withheld` instead, and None is returned."""
        query = dict(query or {})
        key = snapshot_key(endpoint, query)
        if key in self.entries or key in self.withheld:
            return None
        if self.rev:
            query["rev"] = self.rev
        repo = self.app.state.repo
        repo.reads = set()
        try:
            status, content_type, body = self.loop.run_until_complete(
                _asgi_get(self.app, f"/api/{endpoint}", query)
            )
            reads = repo.reads
        finally:
            repo.reads = None
        if status != 200 and not keep_errors:
            return None
        globs = self._built_from_excluded(endpoint, reads)
        if globs:
            self.withheld[key] = {
                "endpoint": key,
                "reason": f"built from files matching --exclude {', '.join(globs)}",
                "files": [],
            }
            return None
        if self.excluded and status == 200 and "json" in content_type:
            body = self._without_excluded_sources(endpoint, body)
        name = _file_name(key, content_type)
        (self.out / name).write_bytes(body)
        self.entries[key] = {"file": name, "status": status, "type": content_type.split(";")[0]}
        if status == 200 and "json" in content_type:
            return json.loads(body)
        return None

    def withhold(self, endpoint: str, query: dict[str, Any], reason: str) -> None:
        """Record the answer to *endpoint* as withheld for *reason*, without asking for it."""
        key = snapshot_key(endpoint, query)
        self.withheld[key] = {"endpoint": key, "reason": reason, "files": []}

    def drop(self, endpoint: str) -> None:
        """Remove the stored answer to *endpoint* (it is then not in the snapshot)."""
        entry = self.entries.pop(snapshot_key(endpoint))
        (self.out / entry["file"]).unlink()

    def replace(self, endpoint: str, data: Any) -> None:
        """Store *data* as the answer to *endpoint*, serialised as the server serialises JSON."""
        from starlette.responses import JSONResponse

        entry = self.entries[snapshot_key(endpoint)]
        (self.out / entry["file"]).write_bytes(JSONResponse(data).body)

    def close(self) -> None:
        self.loop.close()


#: The LCA's inputs: excluding one keeps its values private, so the answer and results go too.
LCA_INPUTS = ("lca/lca.yaml", "lca/factors.yaml")


def _lca_withheld(exporter: _Exporter) -> dict[str, Any] | None:
    """Export the ``lca`` answer if it may be published, and say what is withheld otherwise.

    Fails closed. The answer stays only when it computes here (200) and its policy is
    publishable. The committed result files (:data:`LCA_RESULT_FILES`) stay only when, in
    addition, the committed run manifest (``lca/manifest.json``) says they are publishable: they
    may come from another run (another backend, a licensed database) than this one. Excluding an
    LCA input (:data:`LCA_INPUTS`) withholds both."""
    if any(exporter.is_excluded(path) for path in LCA_INPUTS):
        return {
            "endpoint": "lca",
            "reason": "an LCA input is excluded",
            "files": list(LCA_RESULT_FILES),
        }
    lca = exporter.get("lca")
    built_from_excluded = exporter.withheld.pop(snapshot_key("lca"), None)
    if built_from_excluded is not None:
        return {**built_from_excluded, "files": list(LCA_RESULT_FILES)}
    status = exporter.entries.get(snapshot_key("lca"), {}).get("status")
    policy = (lca or {}).get("publication") if isinstance(lca, dict) else None
    reason = ""
    if status != 200:
        reason = "the LCA does not compute here, so its policy cannot be confirmed"
    elif not (policy or {}).get("publishable", False):
        reason = f"{(policy or {}).get('policy', 'unknown')} sources: " + ", ".join(
            (policy or {}).get("restricted_by", [])
        )
    if reason:
        if status == 200:
            exporter.drop("lca")
        return {"endpoint": "lca", "reason": reason, "files": list(LCA_RESULT_FILES)}
    code, _, body = exporter.loop.run_until_complete(
        _asgi_get(
            exporter.app,
            "/api/file",
            {"path": "lca/manifest.json", **({"rev": exporter.rev} if exporter.rev else {})},
        )
    )
    try:
        committed = (json.loads(body) or {}).get("result") or {} if code == 200 else None
    except ValueError:
        committed = None
    if committed is None or committed.get("publishable") is not True:
        # the answer of this run is publishable, the committed files are not shown to be
        return {
            "endpoint": None,
            "reason": "the committed lca/manifest.json does not say the committed results are "
            "publishable",
            "files": list(LCA_RESULT_FILES),
        }
    return None


def _levels(layout: dict[str, Any]) -> Iterable[str]:
    for building in layout.get("buildings") or []:
        for level in building.get("levels") or []:
            if level.get("id"):
                yield str(level["id"])
    for structure in (layout.get("model") or {}).get("structures") or []:
        for level in structure.get("levels") or []:
            if level.get("id"):
                yield str(level["id"])


def _is_previous_snapshot(out: Path, names: set[str]) -> bool:
    """Whether the directory *out*, holding *names*, is a snapshot written earlier: a
    ``manifest.json`` of :data:`SNAPSHOT_SCHEMA` and a real ``data/`` directory holding only
    regular files named as the export names them (:data:`DATA_FILE`)."""
    try:
        manifest = json.loads((out / "manifest.json").read_text("utf-8"))
    except (OSError, ValueError):
        return False
    data = out / "data"
    if not (
        isinstance(manifest, dict)
        and manifest.get("schema") == SNAPSHOT_SCHEMA
        and names <= {"manifest.json", "data"}
        and data.is_dir()
        and not data.is_symlink()
        and not data.is_junction()
    ):
        return False
    return all(
        DATA_FILE.fullmatch(child.name) and child.is_file() and not child.is_symlink()
        for child in data.iterdir()
    )


def check_output(out: Path, root: Path, ignore_case: bool | None = None) -> None:
    """:class:`ExportError` unless the snapshot may be written to *out* (resolved), for the
    plant repository at *root* (resolved).

    Refused: the repository itself, a directory containing it, one inside it other than below
    ``build/`` (it would be exported next time, or overwrite plant files; ``build/`` itself
    holds other outputs, and the snapshot is staged next to *out*, which must not be in the
    working tree the export walks), a file, and a directory that is neither empty nor a previous
    snapshot (:func:`_is_previous_snapshot`), since it is replaced. Paths are compared ignoring
    case when *ignore_case*, by default when *root*'s filesystem does (:func:`case_insensitive`):
    there ``Plant/PID`` is ``plant/pid``."""
    if ignore_case is None:
        ignore_case = case_insensitive(root)

    def fold(path: Path) -> Path:
        return type(path)(str(path).casefold()) if ignore_case else path

    folded_out, folded_root = fold(out), fold(root)
    if folded_root.is_relative_to(folded_out):
        raise ExportError(
            f"{out} is the plant repository or contains it; write the snapshot elsewhere, "
            "e.g. build/snapshot"
        )
    build = folded_root / "build"
    if folded_out.is_relative_to(folded_root) and (
        folded_out == build or not folded_out.is_relative_to(build)
    ):
        raise ExportError(
            f"{out} is inside the plant repository; write the snapshot below build/ "
            "(e.g. build/snapshot) or outside the repository"
        )
    if not out.exists():
        return
    if not out.is_dir():
        raise ExportError(f"{out} is not a directory")
    names = {child.name for child in out.iterdir()}
    if names and not _is_previous_snapshot(out, names):
        raise ExportError(
            f"{out} is not empty and not a previous snapshot (manifest.json of "
            f"{SNAPSHOT_SCHEMA}, data/ with only snapshot files); it is not replaced. Choose a "
            "new or empty directory"
        )


def export_static(
    root: Path,
    out: Path,
    rev: str | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    exclude: Iterable[str] = (),
) -> dict[str, Any]:
    """Write the viewer snapshot of the plant at *root* (working tree, or *rev*) into *out*.

    Paths matching an *exclude* glob (:func:`path_matches`) are left out of ``tree``, ``file``
    and ``yaml``, and the answers built from them are withheld; excluding a sheet file is an
    :class:`ExportError`, raised before *out* is touched. *out* must be new, empty or a previous
    snapshot, outside the repository (:func:`check_output`); it is replaced only once the new
    snapshot is complete. Returns the manifest. Globs and *out* ignore case where the
    repository's filesystem does (:func:`case_insensitive`). Warns (:class:`ExportWarning`) when
    the previous snapshot cannot be removed once the new one is in place.
    """
    from chemeascode.foundation.workspace import installed_version
    from chemeascode.interfaces.api.serve import ApiError, create_app

    version = ".".join(str(n) for n in installed_version())

    excluded = check_globs(exclude)
    app = create_app(root)
    repo = app.state.repo
    out = out.resolve()
    ignore_case = case_insensitive(repo.root)
    check_output(out, repo.root, ignore_case)
    if excluded:
        snapshot = repo.snapshot(rev)
        try:
            sheets = snapshot.sheets(snapshot.config())
        except ApiError:  # an invalid plant.yaml: the export records it in its answers
            sheets = []
        hidden = sorted(s["file"] for s in sheets if _excluded(s["file"], excluded, ignore_case))
        if hidden:
            raise ExportError(
                f"--exclude matches the sheet file(s) {', '.join(hidden)}: a snapshot without "
                "its drawings is not exported; narrow the glob"
            )
    out.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{out.name}.", dir=out.parent))
    try:
        # mkdtemp makes the directory private (0700); the snapshot is for static hosting, so
        # it gets the mode any new directory gets
        umask = os.umask(0)
        os.umask(umask)
        staging.chmod(0o777 & ~umask)
        manifest = _export(app, staging, rev, max_file_bytes, excluded, version, ignore_case)
        _move_into_place(staging, out)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def _move_into_place(staging: Path, out: Path) -> None:
    """Replace *out* by *staging*; :class:`ExportError`, with *out* as it was, when it fails.
    Once the new snapshot is in place, a previous one that cannot be removed is a warning
    (:class:`ExportWarning`): the export succeeded."""
    previous = staging.with_name(staging.name + ".old") if out.exists() else None
    try:
        if previous is not None:
            out.rename(previous)
        staging.rename(out)
    except OSError as failure:
        if previous is not None and previous.exists() and not out.exists():
            previous.rename(out)
        raise ExportError(f"cannot move the snapshot into place at {out}: {failure}") from failure
    if previous is not None:
        try:
            shutil.rmtree(previous)
        except OSError as failure:
            warnings.warn(
                f"the snapshot is in place at {out}, but the previous one could not be removed "
                f"from {previous} ({failure}); delete it by hand",
                ExportWarning,
                stacklevel=3,
            )


def _export(
    app: Any,
    out: Path,
    rev: str | None,
    max_file_bytes: int,
    excluded: list[str],
    version: str,
    ignore_case: bool = False,
) -> dict[str, Any]:
    """Write the snapshot into the new directory *out* (see :func:`export_static`)."""
    repo = app.state.repo
    data = out / "data"
    data.mkdir()
    exporter = _Exporter(app, data, rev, excluded, ignore_case)
    try:
        info = exporter.get("repo") or {}
        # the LCA first: what its publication policy withholds is excluded everywhere below
        chosen = list(excluded)
        withheld: list[dict[str, Any]] = []
        if info.get("has_lca"):
            found = _lca_withheld(exporter)
            if found is not None:
                withheld.append(found)
                excluded = sorted(set(excluded) | set(LCA_RESULT_FILES))
                exporter.excluded = excluded
        exporter.get("branches")
        exporter.get("log", {"limit": LOG_LIMIT})
        tree = exporter.get("tree") or []
        if excluded and exporter.entries["tree"]["status"] == 200:
            tree = _prune_tree(tree, excluded, ignore_case)
            exporter.replace("tree", tree)
        checks = exporter.get("checks")
        if excluded and isinstance(checks, dict):  # sign-offs name their review records
            exporter.replace("checks", _prune_checks(checks, excluded, ignore_case))
        exporter.get("interlocks")  # a 404 is recorded: the plant has no cause-and-effect list
        if not rev:  # these read the working tree only
            for endpoint in ("validate", "impact"):
                report = exporter.get(endpoint)
                if excluded and isinstance(report, dict):
                    exporter.replace(endpoint, _prune_report(report, excluded, ignore_case))
            # control records with their review status (reviewers, record paths): like status,
            # left out of a snapshot for publication (with excludes)
            if not excluded:
                exporter.get("control")  # a 404 is recorded: the plant has no control records
                # the plant's issues as they were at export (a 404 without issues:, a 503 offline)
                exporter.get("issues")
            # status summarises review records and sign-offs; a snapshot for publication (with
            # excludes) leaves it out rather than leak excluded content
            if not chosen:
                exporter.get("status")
                # maturity quotes evidence from across the repository (requirement details,
                # limitations, findings): like status, not in a snapshot with excludes. Its
                # engineering level runs the whole validation again (some 30 s on ASU-1).
                # checked_at is left null: a snapshot is deterministic, its manifest names
                # the source commit and whether the working tree had changes
                maturity = exporter.get("maturity")
                if isinstance(maturity, dict):
                    exporter.replace("maturity", {**maturity, "checked_at": None})

        sheet_files = {sheet["file"] for sheet in info.get("sheets", [])}
        # a BFD or PFD sheet is generated from the flowsheet and materials: its drawing shows
        # them, so it is withheld with them (the sheet file itself is never exported as text)
        hidden_inputs = sorted(
            {g for path in PROCESS_INPUTS for g in excluded if path_matches(path, g, ignore_case)}
        )
        generated = {s["file"] for s in info.get("sheets", []) if s.get("kind") in ("bfd", "pfd")}
        for sheet in sorted(sheet_files):
            if hidden_inputs and sheet in generated:
                exporter.withhold(
                    "pid.svg",
                    {"path": sheet},
                    "a BFD/PFD drawing generated from files matching --exclude "
                    + ", ".join(hidden_inputs),
                )
                continue
            exporter.get("pid.svg", {"path": sheet})
        if any(sheet.get("kind") in ("bfd", "pfd") for sheet in info.get("sheets", [])) or any(
            entry["path"] == "process/flowsheet.yaml" for entry in tree
        ):
            streams = exporter.get("streams") or {}
            for case in streams.get("cases") or []:
                case_id = case.get("id") if isinstance(case, dict) else case
                if case_id:
                    exporter.get("streams", {"case": case_id})

        if info.get("has_layout"):
            layout = exporter.get("layout") or {}
            exporter.get("mto")
            exporter.get("layout/plan.svg", keep_errors=False)
            for level in sorted(set(_levels(layout))):
                exporter.get("layout/plan.svg", {"level": level}, keep_errors=False)
        if info.get("has_tea"):
            exporter.get("tea")
        if info.get("has_equipment_estimate"):
            exporter.get("estimate/equipment")
        if info.get("has_kinetic_data"):
            kinetics = exporter.get("kinetics") or {}
            if excluded and kinetics:  # an excluded data file is not exported either
                files = [
                    f for f in kinetics.get("files") or [] if not exporter.is_excluded(f["file"])
                ]
                exporter.replace("kinetics", {**kinetics, "files": files})
        exporter.get("library")
        for flag, endpoint in (("has_simulation", "simulation"), ("has_reactions", "reactions")):
            if info.get(flag):
                answer = exporter.get(endpoint) or {}
                for case in answer.get("cases") or []:
                    exporter.get(endpoint, {"case": case})
        if info.get("has_datasheets"):
            index = exporter.get("datasheets") or {}
            shown = [
                sheet
                for sheet in index.get("datasheets") or []
                if not excluded
                or not (
                    exporter.is_excluded(sheet["file"]) or exporter.is_excluded(sheet["drawing"])
                )
            ]
            if excluded and index:  # an excluded datasheet is not listed either
                exporter.replace("datasheets", {**index, "datasheets": shown})
            for sheet in shown:
                exporter.get(f"datasheets/{sheet['tag']}")
                exporter.get(f"datasheets/{sheet['tag']}.svg", keep_errors=False)

        skipped = []
        snapshot = repo.snapshot(rev)
        for entry in tree:
            path = entry["path"]
            if entry["type"] != "file" or path in sheet_files or entry.get("kind") == "pid":
                continue
            size = snapshot.size(path) or 0
            if size > max_file_bytes:
                skipped.append({"path": path, "bytes": size})
                continue
            if PurePosixPath(path).suffix.lower() in (".yaml", ".yml"):
                exporter.get("yaml", {"path": path})
            if entry.get("kind") in TEXT_KINDS:
                exporter.get("file", {"path": path})
    finally:
        exporter.close()

    manifest = {
        "schema": SNAPSHOT_SCHEMA,
        "source": {
            "name": info.get("name"),
            "commit": info.get("head"),
            "rev": rev,
            "dirty": bool(info.get("dirty")) if not rev else False,
            "tool": f"cheme-as-code {version}",
        },
        "limits": {"max_file_bytes": max_file_bytes, "log_limit": LOG_LIMIT},
        "skipped": sorted(skipped, key=lambda s: s["path"]),
        "excluded": excluded,
        "withheld": withheld + list(exporter.withheld.values()),
        "entries": dict(sorted(exporter.entries.items())),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest
