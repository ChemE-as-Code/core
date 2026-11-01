"""``cheme serve``: a read-only JSON API over a plant repository, for the viewer.

Every endpoint reads; nothing writes to the repository. The one exception to "only reads" is
``POST /api/checks/run``: it evaluates the gates without writing ``checks/status.json``, but a
``kind: command`` check runs a shell command from ``checks/checks.yaml``, which can do anything.
That endpoint therefore needs the per-launch token from ``GET /api/session`` in the
``X-Cheme-Token`` header, runs one evaluation at a time, and stops each command after
:data:`CHECK_TIMEOUT` seconds. A ``rev`` query parameter selects a git revision; without
one the working tree is read. Files at a revision come from git's object store (``git ls-tree``,
``git cat-file``), never from a checkout.

Security, since the API serves files from disk:

- every ``path`` is repo-relative POSIX, may not contain ``..``, ``.`` or empty segments, may not
  be absolute, may not name ``.git`` or anything under it, and in the working tree must resolve
  (symlinks followed) inside the repository and outside ``.git``;
- every ``rev`` is refused when it starts with ``-`` and is resolved with
  ``git rev-parse --verify --end-of-options <rev>^{commit}``; only the resulting sha is passed on;
- git runs with argument lists, never a shell;
- the server binds 127.0.0.1 by default and accepts only requests whose ``Host`` header names the
  address it serves (against DNS rebinding): the local names, a bound address that is not a
  wildcard, and the names given with ``--allow-host``, never any name (:func:`accepted_hosts`);
- bound to a non-local address, the server refuses ``GET /api/session`` and ``POST
  /api/checks/run`` unless started with ``--allow-remote-checks``;
- the viewer's pages may be framed only by the served origin (``frame-ancestors 'self'``), so
  another site cannot trick a click on "Run now" in a frame;
- ``/api/*`` refuses requests another site makes (``Sec-Fetch-Site: cross-site`` or
  ``same-site``, or an ``Origin`` that is not the served origin), so a web page the user visits
  cannot drive the API;
- files larger than :data:`MAX_FILE_BYTES` are not parsed, and YAML is converted to JSON with a
  node budget (aliases cannot blow it up) and only JSON types. The working-tree reports
  (``/api/validate``, ``/api/status``, ``/api/impact``, ``/api/control``, ``/api/maturity``) run
  the command modules on the repository as ``cheme validate`` and the others do, without that
  cap;
- an unexpected failure answers JSON ``{"error": "internal error"}`` with no internals.

Rendering a sheet takes a fraction of a second, so SVGs and diffs are cached in memory by the git
blob ids of their inputs.
"""

from __future__ import annotations

import contextlib
import datetime
import hashlib
import ipaddress
import json
import os
import secrets
import subprocess
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import yaml
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE, Catalysts
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, Reactions
from chemeascode.domains.piping.diffview import diff_sheet
from chemeascode.domains.piping.render import load_model, render_svg
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.schema import Flowsheet, Materials
from chemeascode.domains.spatial.layout_validate import (
    building_footprint,
    building_heights,
    check_layout,
    level_heights,
)
from chemeascode.foundation.workspace import (
    LAYOUT_FILES,
    LAYOUT_MODEL_FILE,
    LIST_FILES,
    PLANT_FILE,
    Workspace,
)
from chemeascode.project.checks import run_checks
from chemeascode.project.kinetics import DATA_DIR as KINETICS_DIR
from chemeascode.project.validate import validate_workspace
from chemeascode.schemas import (
    LAYOUT_SCHEMAS,
    LIST_SCHEMAS,
    EquipmentList,
    LayoutModelFile,
    PlantConfig,
)

#: Largest file the API reads (returns, parses or renders).
MAX_FILE_BYTES = 5 * 1024 * 1024
#: Most YAML nodes ``/api/yaml`` returns, counted after aliases are expanded.
MAX_YAML_NODES = 200_000
#: Seconds a ``kind: command`` check may run under ``POST /api/checks/run``.
CHECK_TIMEOUT = 120.0
#: Header carrying the per-launch token of ``GET /api/session``.
TOKEN_HEADER = "X-Cheme-Token"
#: Directories left out of ``/api/tree`` at the repository root (``.git`` is left out anywhere).
EXCLUDED_TOP_DIRS = {"build", ".venv"}
#: Host names accepted by default (the server binds 127.0.0.1 by default).
LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]
WORKING_TREE = "working tree"

_KIND_BY_LIST_PATH = {path: kind for kind, path in LIST_FILES.items()}
_KIND_BY_LAYOUT_PATH = {path: kind for kind, path in LAYOUT_FILES.items()}
_PROCESS_SCHEMAS = {
    MATERIALS_FILE: ("materials", Materials),
    FLOWSHEET_FILE: ("flowsheet", Flowsheet),
    REACTIONS_FILE: ("reactions", Reactions),
    CATALYSTS_FILE: ("catalysts", Catalysts),
}
_SVG_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
    "X-Content-Type-Options": "nosniff",
}
#: The viewer's pages: framed only by the served origin (against clickjacking "Run now").
_UI_HEADERS = {
    "Content-Security-Policy": "frame-ancestors 'self'",
    "X-Frame-Options": "SAMEORIGIN",
}


class ApiError(Exception):
    """An error answered as JSON ``{"error": message}`` with *status*."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Paths and revisions
# ---------------------------------------------------------------------------


def clean_path(path: str) -> str:
    """*path* when it is a safe repo-relative POSIX path, else :class:`ApiError` 400."""
    if not path or "\0" in path or "\\" in path:
        raise ApiError(400, f"invalid path {path!r}")
    if path.startswith("/") or PurePosixPath(path).is_absolute():
        raise ApiError(400, f"path must be relative to the repository: {path!r}")
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ApiError(400, f"path may not contain empty, '.' or '..' segments: {path!r}")
    if any(part.lower() == ".git" for part in parts):
        raise ApiError(400, "paths under .git are not served")
    return path


def blob_id(content: bytes) -> str:
    """The git blob id of *content* (what ``git hash-object`` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content, usedforsecurity=False).hexdigest()


@dataclass(frozen=True)
class Entry:
    """One file or directory of a snapshot."""

    path: str
    type: str  # file, dir
    blob: str | None = None  # git blob id, at a revision
    mode: str = ""


class Repo:
    """The plant repository and the git repository around it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.workspace = Workspace(self.root)
        prefix = self._git("rev-parse", "--show-prefix")
        self.is_git = prefix.returncode == 0
        #: The plant root relative to the git top level ("" or "sub/dir/").
        self.prefix = prefix.stdout.decode().strip() if self.is_git else ""
        self._trees = _LRU(32)
        #: When a set, the path of every file a snapshot reads the content of is added to it:
        #: ``cheme export-static`` withholds the answers built from an excluded file.
        self.reads: set[str] | None = None

    def _git(self, *args: str, input: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"}
        return subprocess.run(
            ["git", "-c", "core.fsmonitor=false", *args],
            cwd=self.root,
            capture_output=True,
            check=False,
            env=env,
            input=input,
        )

    def git(self, *args: str) -> bytes:
        """Run git; :class:`ApiError` 500 when it fails."""
        result = self._git(*args)
        if result.returncode != 0:
            message = result.stderr.decode(errors="replace").strip().splitlines()[:1]
            raise ApiError(500, f"git {args[0]} failed: {message[0] if message else ''}")
        return result.stdout

    # -- revisions ----------------------------------------------------------

    def resolve(self, rev: str) -> str:
        """The commit sha *rev* names; 400 when it is malformed, 404 when unknown."""
        if not rev or rev.startswith("-") or len(rev) > 256 or any(c in rev for c in "\0\r\n"):
            raise ApiError(400, f"invalid revision {rev!r}")
        if not self.is_git:
            raise ApiError(400, "the plant repository is not in git")
        result = self._git(
            "rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}"
        )
        if result.returncode != 0:
            raise ApiError(404, f"unknown revision {rev!r}")
        return result.stdout.decode().strip()

    def head(self) -> str | None:
        """The commit HEAD points at, or ``None`` (no git, or no commit yet)."""
        if not self.is_git:
            return None
        result = self._git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def snapshot(self, rev: str | None) -> Snapshot:
        """The working tree (``rev`` absent) or the tree of commit *rev*."""
        return Snapshot(self, self.resolve(rev) if rev else None)

    # -- trees at a commit ----------------------------------------------------

    def tree(self, commit: str) -> dict[str, Entry]:
        """Every entry under the plant root at *commit*, by repo-relative path."""

        def load() -> dict[str, Entry]:
            raw = self.git("ls-tree", "-r", "-t", "-z", "--full-tree", commit)
            entries: dict[str, Entry] = {}
            for record in raw.split(b"\0"):
                if not record:
                    continue
                meta, _, name = record.partition(b"\t")
                mode, kind, sha = meta.decode().split()
                full = name.decode("utf-8", errors="surrogateescape")
                if not full.startswith(self.prefix) or full == self.prefix.rstrip("/"):
                    continue
                path = full[len(self.prefix) :]
                if kind == "tree":
                    entries[path] = Entry(path, "dir", None, mode)
                elif kind == "blob":
                    entries[path] = Entry(path, "file", sha, mode)
            return entries

        return self._trees.get_or_compute(commit, load)

    def cat_blob(self, sha: str) -> bytes:
        return self.git("cat-file", "blob", sha)


class Snapshot:
    """The files of the repository at one commit, or in the working tree (``commit`` None)."""

    def __init__(self, repo: Repo, commit: str | None) -> None:
        self.repo = repo
        self.commit = commit

    @property
    def label(self) -> str:
        return self.commit or WORKING_TREE

    def _working_path(self, path: str) -> Path:
        """*path* in the working tree, resolved, after the confinement checks."""
        resolved = (self.repo.root / clean_path(path)).resolve()
        try:
            relative = resolved.relative_to(self.repo.root)
        except ValueError:
            raise ApiError(400, f"{path} resolves outside the repository") from None
        if any(part.lower() == ".git" for part in relative.parts):
            raise ApiError(400, "paths under .git are not served")
        return resolved

    def _entry(self, path: str) -> Entry | None:
        """The tree entry of a file at the commit, ``None`` when absent; 400 for a non-file."""
        entry = self.repo.tree(self.commit or "").get(clean_path(path))
        if entry is not None and (entry.type != "file" or entry.mode in ("120000", "160000")):
            raise ApiError(400, f"{path} is not a file at this revision")
        return entry

    def _working_file(self, path: str) -> Path | None:
        resolved = self._working_path(path)
        if not resolved.exists():
            return None
        if not resolved.is_file():
            raise ApiError(400, f"{path} is not a file")
        return resolved

    def size(self, path: str) -> int | None:
        """The size of file *path* in bytes, ``None`` when absent."""
        if self.commit is None:
            found = self._working_file(path)
            return found.stat().st_size if found else None
        entry = self._entry(path)
        if entry is None:
            return None
        return int(self.repo.git("cat-file", "-s", entry.blob or "").decode().strip())

    def read(self, path: str) -> bytes | None:
        """The bytes of *path*, or ``None`` when it does not exist."""
        found = self.read_with_id(path)
        return found[0] if found else None

    def read_with_id(self, path: str) -> tuple[bytes, str] | None:
        """The bytes of *path* and their git blob id, or ``None`` when it does not exist."""
        if self.commit is None:
            found = self._working_file(path)
            if found is None:
                return None
            content = found.read_bytes()
            sha = blob_id(content)
        else:
            entry = self._entry(path)
            if entry is None or entry.blob is None:
                return None
            content, sha = self.repo.cat_blob(entry.blob), entry.blob
        if self.repo.reads is not None:
            self.repo.reads.add(clean_path(path))
        return content, sha

    def entries(self) -> list[Entry]:
        """Every file and directory, sorted, without ``.git``, ``build/`` and ``.venv``."""
        if self.commit is not None:
            found = [
                entry
                for entry in self.repo.tree(self.commit).values()
                if entry.mode not in ("120000", "160000")
            ]
        else:
            found = self._walk()
        return sorted(
            (e for e in found if not _excluded(e.path)),
            key=lambda e: e.path,
        )

    def _walk(self) -> list[Entry]:
        root = self.repo.root
        found: list[Entry] = []
        for directory, dirnames, filenames in os.walk(root, followlinks=False):
            here = Path(directory)
            keep = []
            for name in sorted(dirnames):
                relative = (here / name).relative_to(root).as_posix()
                if _excluded(relative) or (here / name).is_symlink():
                    continue
                keep.append(name)
                found.append(Entry(relative, "dir"))
            dirnames[:] = keep
            for name in filenames:
                relative = (here / name).relative_to(root).as_posix()
                if _excluded(relative):
                    continue
                if (here / name).is_symlink():
                    try:
                        if not self._working_path(relative).is_file():
                            continue
                    except ApiError:
                        continue  # escapes the repository
                found.append(Entry(relative, "file"))
        return found

    # -- the plant -------------------------------------------------------------

    def config(self) -> PlantConfig:
        """``plant.yaml`` of this snapshot, validated (422 when it does not validate)."""
        content = self.read(PLANT_FILE)
        if content is None:
            raise ApiError(404, f"no {PLANT_FILE} at {self.label}")
        try:
            return PlantConfig.model_validate(yaml.safe_load(content) or {})
        except (ValidationError, yaml.YAMLError) as failure:
            raise ApiError(422, f"{PLANT_FILE}: {str(failure).splitlines()[0]}") from failure

    def sheets(self, config: PlantConfig) -> list[dict[str, str]]:
        """The P&ID sheets, as ``Workspace.pid_files`` finds them: listed, else ``pid/*.xml``."""
        if config.sheets:
            return [sheet.model_dump() for sheet in config.sheets]
        return [
            {"id": PurePosixPath(e.path).stem, "file": e.path, "title": "", "kind": "pid"}
            for e in self.entries()
            if e.type == "file" and PurePosixPath(e.path).parent.as_posix() == "pid"
            if e.path.endswith(".xml")
        ]


def _excluded(path: str) -> bool:
    parts = path.split("/")
    return parts[0] in EXCLUDED_TOP_DIRS or any(part.lower() == ".git" for part in parts)


def file_kind(path: str, sheet_files: set[str]) -> str:
    """``pid``, ``yaml``, ``markdown``, ``json`` or ``other``."""
    suffix = PurePosixPath(path).suffix.lower()
    if suffix == ".xml" and (path in sheet_files or path.startswith("pid/")):
        return "pid"
    return {
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
        ".markdown": "markdown",
        ".json": "json",
    }.get(suffix, "other")


def json_safe(data: Any, budget: int = MAX_YAML_NODES) -> Any:
    """*data* (from ``yaml.safe_load``) as plain JSON values, every alias expanded.

    :class:`ApiError` 422 when it holds more than *budget* nodes (an alias bomb), refers to
    itself, or holds a value JSON has no type for (``!!binary``, ``!!set``).
    """
    remaining = budget
    active: set[int] = set()

    def convert(value: Any) -> Any:
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise ApiError(422, f"the YAML expands to more than {budget} values")
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, (datetime.date, datetime.datetime)):
            return value.isoformat()
        if isinstance(value, (dict, list)):
            if id(value) in active:
                raise ApiError(422, "the YAML refers to itself (a recursive alias)")
            active.add(id(value))
            try:
                if isinstance(value, list):
                    return [convert(item) for item in value]
                converted = {}
                for key, item in value.items():
                    if not isinstance(key, (str, int, float, bool)) and key is not None:
                        raise ApiError(422, f"a YAML mapping key of type {type(key).__name__}")
                    converted[key if isinstance(key, str) else json.dumps(key)] = convert(item)
                return converted
            finally:
                active.discard(id(value))
        raise ApiError(422, f"a YAML value of type {type(value).__name__} has no JSON form")

    return convert(data)


def _first_line(failure: Exception) -> str:
    return (str(failure).splitlines() or [type(failure).__name__])[0]


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class _LRU:
    """A small thread-safe least-recently-used cache."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._items: OrderedDict[Any, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get_or_compute(self, key: Any, compute: Callable[[], Any]) -> Any:
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        value = compute()  # outside the lock: rendering is slow, a duplicate is harmless
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return value

    def __len__(self) -> int:
        return len(self._items)


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------


def _host_name(header: str) -> str:
    """The host part of a ``Host`` header: ``[::1]:8765`` gives ``::1``, ``a:80`` gives ``a``."""
    if header.startswith("["):
        return header[1:].split("]", 1)[0]
    return header.rsplit(":", 1)[0] if header.count(":") == 1 else header


def _cross_site(request: Request, host: str) -> str | None:
    """Why a request made by another web site is refused, ``None`` when it is not one."""
    site = request.headers.get("sec-fetch-site")
    if site in ("cross-site", "same-site"):
        return f"cross-site request refused (Sec-Fetch-Site: {site})"
    origin = request.headers.get("origin")
    if origin is not None:
        parts = urlsplit(origin)
        if origin == "null" or not parts.netloc or parts.netloc.lower() != host.lower():
            return f"cross-origin request refused (Origin: {origin})"
    return None


#: The pyDEXPI modules cheme-as-code imports where it uses them. :func:`create_app` imports them
#: all before the server answers requests in its thread pool: pyDEXPI's first import is not safe
#: from several threads at once (one of them sees a partially initialised module), and the P&ID a
#: concurrent request was drawing then answered 422 although it loads.
PYDEXPI_MODULES = (
    "pydexpi",
    "pydexpi.diff",
    "pydexpi.exports.svg_export",
    "pydexpi.loaders.compat",
    "pydexpi.loaders.error_registry",
    "pydexpi.loaders.public",
    "pydexpi.loaders.xml_serializer",
    "pydexpi.pydexpi_classes.core.diagram",
    "pydexpi.pydexpi_classes.plant",
    "pydexpi.pydexpi_classes.pydexpi_classes",
    "pydexpi.toolkits.base_model_utils",
    "pydexpi.toolkits.display_name",
    "pydexpi.toolkits.label_toolkit",
    "pydexpi.toolkits.model_summary",
    "pydexpi.toolkits.model_toolkit",
    "pydexpi.validation",
    "pydexpi.versioning",
    "pydexpi.versioning.projection",
)


def import_pydexpi() -> None:
    """Import :data:`PYDEXPI_MODULES` in this thread."""
    import importlib

    for name in PYDEXPI_MODULES:
        importlib.import_module(name)


def create_app(
    repo_root: Path,
    ui_dir: Path | None = None,
    allowed_hosts: list[str] | None = None,
    run_checks_allowed: bool = True,
) -> FastAPI:
    """The FastAPI app serving the plant repository at (or above) *repo_root*.

    *ui_dir*: a built single-page app served at ``/`` (unknown paths fall back to its
    ``index.html``). *allowed_hosts*: accepted ``Host`` headers (default: the local ones;
    ``["*"]`` accepts any, which :func:`serve` never passes). *run_checks_allowed*: whether
    ``GET /api/session`` hands out the token and ``POST /api/checks/run`` runs the checks
    (:func:`serve` turns it off on a non-local bind without ``--allow-remote-checks``).
    """
    repo = Repo(Workspace.find(repo_root).root)
    import_pydexpi()
    ui = ui_dir.resolve() if ui_dir else None
    if ui is not None and not (ui / "index.html").is_file():
        raise FileNotFoundError(f"{ui} has no index.html")
    svg_cache = _LRU(128)
    diff_cache = _LRU(64)
    tags_cache = _LRU(128)
    process_cache = _LRU(16)
    lca_cache = _LRU(8)
    tea_cache = _LRU(8)
    estimate_cache = _LRU(8)
    simulation_cache = _LRU(8)
    reactions_cache = _LRU(8)
    datasheet_cache = _LRU(8)
    brightway_lock = threading.Lock()
    maturity_lock = threading.Lock()

    app = FastAPI(
        title="cheme-as-code", docs_url=None, redoc_url=None, openapi_url="/api/openapi.json"
    )
    hosts = {name.lower() for name in allowed_hosts or LOCAL_HOSTS}
    token = secrets.token_urlsafe(32)
    check_run = threading.Lock()

    @app.middleware("http")
    async def _check_host(request: Request, call_next):
        host = request.headers.get("host", "")
        if "*" not in hosts and _host_name(host).lower() not in hosts:
            return JSONResponse({"error": "invalid Host header"}, status_code=400)
        if request.url.path.startswith("/api/"):
            refusal = _cross_site(request, host)
            if refusal:
                return JSONResponse({"error": refusal}, status_code=403)
        return await call_next(request)

    app.state.repo = repo
    app.state.svg_cache = svg_cache
    app.state.diff_cache = diff_cache

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse({"error": error.message}, status_code=error.status)

    @app.exception_handler(HTTPException)
    async def _http_error(_: Request, error: HTTPException) -> JSONResponse:
        return JSONResponse({"error": str(error.detail)}, status_code=error.status_code)

    @app.exception_handler(Exception)
    async def _internal_error(_: Request, error: Exception) -> JSONResponse:
        # Logged by the server; the client gets no internals.
        return JSONResponse({"error": "internal error"}, status_code=500)

    @app.exception_handler(RequestValidationError)
    async def _bad_request(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'][1:])}: {e['msg']}" for e in error.errors()
        )
        return JSONResponse({"error": problems or "bad request"}, status_code=400)

    def _record(path: str) -> None:
        """Record *path* as read for ``cheme export-static`` (see :attr:`Repo.reads`)."""
        if repo.reads is not None:
            # not a repository path (ApiError): it names no file of the plant
            with contextlib.suppress(ApiError):
                repo.reads.add(clean_path(path))

    def _uncommitted(snapshot: Snapshot, paths: Iterable[str]) -> tuple[str, ...]:
        """The *paths* (sorted) with uncommitted changes in the working tree *snapshot*
        serves: none for a commit or outside git, every one when git cannot tell."""
        from chemeascode.foundation.gitinfo import dirty_paths

        if snapshot.commit is not None or not repo.is_git:
            return ()
        found = dirty_paths(repo.root)
        return tuple(p for p in sorted(paths) if found is None or p in found)

    def _small(snapshot: Snapshot, path: str) -> tuple[bytes, str] | None:
        """``read_with_id``, refusing (400) a file larger than :data:`MAX_FILE_BYTES`."""
        try:
            size = snapshot.size(path)
        except ApiError:  # e.g. a symlink out of the repository: the refusal names the file
            _record(path)
            raise
        if size is None:
            return None
        _record(path)  # refused below or not, the answer is built from (or names) the file
        if size > MAX_FILE_BYTES:
            raise ApiError(400, f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        return snapshot.read_with_id(path)

    def _need(snapshot: Snapshot, path: str) -> tuple[bytes, str]:
        found = _small(snapshot, path)
        if found is None:
            raise ApiError(404, f"{path} does not exist at {snapshot.label}")
        return found

    # -- repository -------------------------------------------------------------

    def _has_layout(snapshot: Snapshot) -> bool:
        from chemeascode.foundation.workspace import LAYOUT_SUPPORT

        for kind, path in LAYOUT_FILES.items():
            if kind in LAYOUT_SUPPORT:
                continue
            try:
                if snapshot.size(path) is not None:
                    return True
            except ApiError:  # e.g. a symlink out of the repository: not served
                continue
        return False

    def _exists(snapshot: Snapshot, path: str) -> bool:
        try:
            return snapshot.size(path) is not None
        except ApiError:  # e.g. a symlink out of the repository: not served
            return False

    def _has_control(snapshot: Snapshot) -> bool:
        """Loops, sequences, or a narrative or philosophy changed from its template:
        ``GET /api/control`` has something to show."""
        from chemeascode.domains.control.report import CONTROL_FILES, has_control_texts

        texts = {}
        for kind, path in CONTROL_FILES.items():
            if kind == "interlocks":
                continue
            try:
                texts[path] = _text(snapshot, path)
            except ApiError:
                texts[path] = None
        return has_control_texts(texts)

    def _has_equipment(snapshot: Snapshot) -> bool:
        """The equipment list lists items (or does not load: the estimate then says why)."""
        try:
            found = _small(snapshot, LIST_FILES["equipment"])
        except ApiError:  # too large, or a symlink out of the repository: not served
            return False
        if found is None:
            return False
        try:
            data = yaml.safe_load(found[0])
        except yaml.YAMLError:
            return True
        return isinstance(data, dict) and bool(data.get("equipment"))

    def _datasheet_files(snapshot: Snapshot, suffixes: tuple[str, ...]) -> list[str]:
        """The files of ``equipment/datasheets/`` with one of *suffixes*, sorted."""
        from chemeascode.domains.equipment.datasheets import DATASHEET_DIR

        return _folder_files(snapshot, DATASHEET_DIR, suffixes)

    def _folder_files(snapshot: Snapshot, directory: str, suffixes: tuple[str, ...]) -> list[str]:
        """The files of the folder *directory* (not below it) with one of *suffixes*, sorted."""
        if snapshot.commit is None:  # the folder only, not a walk of the working tree
            folder = repo.root / directory
            names = sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []
            candidates = [
                path
                for name in names
                if PurePosixPath(name).suffix in suffixes
                and _exists(snapshot, path := f"{directory}/{name}")
            ]
        else:
            candidates = sorted(
                entry.path
                for entry in repo.tree(snapshot.commit).values()
                if entry.type == "file" and entry.mode not in ("120000", "160000")
            )
        return [
            path
            for path in candidates
            if PurePosixPath(path).parent.as_posix() == directory
            and PurePosixPath(path).suffix in suffixes
        ]

    @app.get("/api/repo")
    def get_repo(rev: str | None = None) -> dict[str, Any]:
        snapshot = repo.snapshot(rev)
        config = snapshot.config()
        branch = None
        if repo.is_git:
            branch = repo.git("branch", "--show-current").decode().strip() or None
        dirty = bool(repo.is_git and repo.git("status", "--porcelain=v1", "-z").strip(b"\0"))
        return {
            "name": config.name,
            "root_name": repo.root.name,
            "branch": branch,
            "head": snapshot.commit or repo.head(),
            "stage": config.stage,
            "stages": [stage.model_dump() for stage in config.stages],
            "sheets": snapshot.sheets(config),
            "dirty": dirty,
            "has_layout": _has_layout(snapshot),
            "has_lca": _exists(snapshot, "lca/lca.yaml"),
            "has_tea": _exists(snapshot, LIST_FILES["tea"]),
            "has_equipment_estimate": _has_equipment(snapshot),
            "has_simulation": _exists(snapshot, "process/simulation.yaml"),
            "has_reactions": _exists(snapshot, REACTIONS_FILE),
            "has_datasheets": bool(_datasheet_files(snapshot, (".yaml", ".yml"))),
            "has_kinetic_data": bool(_folder_files(snapshot, KINETICS_DIR, (".yaml", ".yml"))),
            "has_control": _has_control(snapshot),
            "has_issues": config.issues is not None,
        }

    @app.get("/api/branches")
    def get_branches() -> list[dict[str, Any]]:
        if not repo.is_git:
            return []
        raw = repo.git(
            "for-each-ref", "--format=%(refname:short)%00%(objectname)%00%(HEAD)", "refs/heads"
        )
        branches = []
        for line in raw.decode().splitlines():
            name, head, current = line.split("\0")
            branches.append({"name": name, "head": head, "current": current == "*"})
        return branches

    @app.get("/api/log")
    def get_log(
        limit: int = Query(50, ge=1, le=1000), path: str | None = None, rev: str | None = None
    ) -> list[dict[str, str]]:
        commit = repo.resolve(rev) if rev else repo.head()
        if commit is None:
            return []
        args = ["log", f"--max-count={limit}", "-z", "--format=%H%x1f%h%x1f%an%x1f%aI%x1f%s"]
        args += [commit, "--"]
        if path:
            args.append(f":(literal){clean_path(path)}")
        elif repo.prefix:
            args.append(".")  # the plant is a subdirectory: only commits that touch it
        entries = []
        for record in repo.git(*args).decode(errors="replace").split("\0"):
            if not record.strip():
                continue
            sha, short, author, date, subject = record.strip("\n").split("\x1f", 4)
            entries.append(
                {"sha": sha, "short": short, "author": author, "date": date, "subject": subject}
            )
        return entries

    @app.get("/api/tree")
    def get_tree(rev: str | None = None) -> list[dict[str, str]]:
        snapshot = repo.snapshot(rev)
        try:
            sheet_files = {s["file"] for s in snapshot.sheets(snapshot.config())}
        except ApiError:
            sheet_files = set()
        return [
            {
                "path": e.path,
                "type": e.type,
                "kind": file_kind(e.path, sheet_files) if e.type == "file" else "other",
            }
            for e in snapshot.entries()
        ]

    # -- files ---------------------------------------------------------------------

    @app.get("/api/file")
    def get_file(path: str, rev: str | None = None) -> Response:
        snapshot = repo.snapshot(rev)
        size = snapshot.size(path)
        if size is None:
            raise ApiError(404, f"{path} does not exist at {snapshot.label}")
        if size > MAX_FILE_BYTES:
            raise ApiError(400, f"{path} is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        content = snapshot.read(path) or b""
        if b"\0" in content[:8192]:
            raise ApiError(400, f"{path} is a binary file")
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(400, f"{path} is a binary file (not UTF-8)") from None
        return PlainTextResponse(text, headers={"X-Content-Type-Options": "nosniff"})

    def _svg(path: str, content: bytes, sha: str) -> str:
        def render() -> tuple[bool, str]:
            try:
                return True, render_svg(load_model(content))
            except Exception as failure:  # noqa: BLE001 - any load or drawing failure is the file's problem
                return False, f"{path}: {type(failure).__name__}: {failure}".splitlines()[0]

        ok, value = svg_cache.get_or_compute((path, sha), render)
        if not ok:
            raise ApiError(422, value)
        return value

    @app.get("/api/pid.svg")
    def get_pid_svg(path: str, rev: str | None = None) -> Response:
        snapshot = repo.snapshot(rev)
        content, sha = _need(snapshot, path)
        return Response(_svg(path, content, sha), media_type="image/svg+xml", headers=_SVG_HEADERS)

    @app.get("/api/diff")
    def get_diff(path: str, old: str = "HEAD", new: str | None = None) -> dict[str, Any]:
        clean_path(path)
        old = old or "HEAD"  # an empty old= means the default, never the working tree
        old_snapshot = repo.snapshot(old)
        new_snapshot = repo.snapshot(new)
        old_found = _small(old_snapshot, path)
        new_found = _small(new_snapshot, path)
        if old_found is None and new_found is None:
            raise ApiError(404, f"{path} exists in neither revision")
        new_label = new or WORKING_TREE
        key = (
            path,
            old_found[1] if old_found else None,
            new_found[1] if new_found else None,
            old,
            new_label,
        )

        def compute() -> tuple[bool, Any]:
            try:
                result = diff_sheet(
                    old_found[0] if old_found else None,
                    new_found[0] if new_found else None,
                    path,
                    old,
                    new_label,
                )
            except Exception as failure:  # noqa: BLE001 - a sheet pyDEXPI cannot load
                return False, f"{path}: {type(failure).__name__}: {failure}".splitlines()[0]
            if result.error:  # a side that does not load or draw: 422, as before
                return False, f"{path}: {result.error}"
            return True, asdict(result)

        ok, value = diff_cache.get_or_compute(key, compute)
        if not ok:
            raise ApiError(422, value)
        return value

    @app.get("/api/yaml")
    def get_yaml(path: str, rev: str | None = None) -> dict[str, Any]:
        if PurePosixPath(clean_path(path)).suffix.lower() not in (".yaml", ".yml"):
            raise ApiError(422, f"{path} is not a YAML file (.yaml or .yml)")
        snapshot = repo.snapshot(rev)
        content, _ = _need(snapshot, path)
        try:
            data = json_safe(yaml.safe_load(content))
        except yaml.YAMLError as failure:
            raise ApiError(422, f"{path}: {_first_line(failure)}") from failure
        except ApiError as failure:
            raise ApiError(failure.status, f"{path}: {failure.message}") from None
        if data is not None and not isinstance(data, (dict, list)):
            raise ApiError(
                422, f"{path} holds a single {type(data).__name__}, not a mapping or list"
            )
        if path == PLANT_FILE:
            kind, model = "plant", PlantConfig
        elif path in _PROCESS_SCHEMAS:
            kind, model = _PROCESS_SCHEMAS[path]
        elif path in _KIND_BY_LAYOUT_PATH:
            kind = _KIND_BY_LAYOUT_PATH[path]
            model = LAYOUT_SCHEMAS[kind]
        elif path == LAYOUT_MODEL_FILE:
            kind, model = "layout_model", LayoutModelFile
        else:
            kind = _KIND_BY_LIST_PATH.get(path)
            model = LIST_SCHEMAS.get(kind) if kind else None
        schema = model.model_json_schema(by_alias=True) if model else None
        return {"data": data, "kind": kind, "schema": schema}

    # -- layout ---------------------------------------------------------------------

    def _text(snapshot: Snapshot, path: str) -> str | None:
        found = _small(snapshot, path)
        if found is None:
            return None
        try:
            return found[0].decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError(422, f"{path} is not UTF-8 text") from None

    def _list_model(snapshot: Snapshot, kind: str) -> Any:
        """The parsed list of *kind* at *snapshot*, or None (absent or invalid)."""
        try:
            text = _text(snapshot, LIST_FILES[kind])
        except ApiError:
            return None
        if text is None:
            return None
        try:
            return LIST_SCHEMAS[kind].model_validate(yaml.safe_load(text) or {})
        except (ValidationError, yaml.YAMLError):
            return None

    def _drawn_tags(snapshot: Snapshot, files: list[str]) -> set[str]:
        """The tags drawn on the sheets (not line numbers), cached per file content."""
        from chemeascode.domains.piping.sheet_query import sheet_items

        tags: set[str] = set()
        for path in files:
            try:
                found = _small(snapshot, path)
            except ApiError:
                continue
            if found is None:
                continue
            content, sha = found

            def compute(content: bytes = content, path: str = path) -> frozenset[str]:
                try:
                    items = sheet_items(load_model(content), path)
                except Exception:  # noqa: BLE001 - an unloadable sheet draws nothing here; validate says why
                    return frozenset()
                return frozenset(i.tag.strip() for i in items if i.tag and i.kind != "line")

            tags |= tags_cache.get_or_compute((path, sha), compute)
        return tags

    def _nozzle_names(snapshot: Snapshot, files: list[str]) -> dict[str, set[str]]:
        """The nozzle names of each equipment tag on the sheets, cached per file content."""
        from chemeascode.domains.spatial.pid_nozzles import sheet_equipment

        found: dict[str, set[str]] = {}
        for path in files:
            try:
                small = _small(snapshot, path)
            except ApiError:
                continue
            if small is None:
                continue
            content, sha = small

            def compute(content: bytes = content, path: str = path) -> dict[str, frozenset]:
                try:
                    items = sheet_equipment(load_model(content), path)
                except Exception:  # noqa: BLE001 - an unloadable sheet draws nothing here; validate says why
                    return {}
                return {tag: item.names for tag, item in items.items()}

            for tag, names in tags_cache.get_or_compute(("nozzles", path, sha), compute).items():
                found.setdefault(tag, set(names))
        return found

    @app.get("/api/layout")
    def get_layout(rev: str | None = None) -> dict[str, Any]:
        snapshot = repo.snapshot(rev)
        texts = {}
        unreadable: dict[str, tuple[str, str]] = {}
        failures: list[ApiError] = []
        for kind, path in LAYOUT_FILES.items():
            try:
                text = _text(snapshot, path)
            except ApiError as failure:  # one bad file does not hide the others
                failures.append(failure)
                unreadable[kind] = (path, failure.message)
                continue
            if text is not None:
                texts[kind] = (path, text)
        if not texts:
            if failures:
                raise failures[0]
            raise ApiError(404, f"no layout files (layout/*.yaml) at {snapshot.label}")
        equipment_path = LIST_FILES["equipment"]
        equipment_text = _text(snapshot, equipment_path)
        equipment = None
        if equipment_text is not None:
            try:
                equipment = EquipmentList.model_validate(yaml.safe_load(equipment_text) or {})
            except (ValidationError, yaml.YAMLError):
                equipment = None
        piping_items = _list_model(snapshot, "piping_items")
        lines = _list_model(snapshot, "lines")
        lines_text = _text(snapshot, LIST_FILES["lines"]) if lines is not None else None
        try:
            listed_sheets = snapshot.sheets(snapshot.config())
        except ApiError:
            listed_sheets = []
        sheet_files = {s["id"]: s["file"] for s in listed_sheets}
        drawn = _drawn_tags(snapshot, list(sheet_files.values())) if lines is not None else None
        pid_files = [s["file"] for s in listed_sheets if s.get("kind", "pid") == "pid"]
        nozzles = _nozzle_names(snapshot, pid_files) if pid_files else None
        layout = check_layout(
            texts,
            equipment,
            (equipment_path, equipment_text) if equipment_text else None,
            unreadable,
            piping_items=piping_items,
            lines=lines,
            lines_text=(LIST_FILES["lines"], lines_text) if lines_text else None,
            drawn_tags=drawn,
            nozzles=nozzles,
        )
        refs = layout.clash_refs
        listed: dict[str, Any] = (
            {item.tag: item for item in equipment.equipment} if equipment else {}
        )
        for special in piping_items.piping_items if piping_items else []:
            listed.setdefault(special.tag, special)
        plan = layout.site_plan
        placed = []
        for index, item in enumerate(layout.placement.equipment if layout.placement else []):
            resolved = layout.resolved[index]
            entry = listed.get(item.tag)
            sheet = entry.sheet if entry else None
            service = ""
            if entry is not None:
                service = entry.service if hasattr(entry, "service") else entry.notes
            placed.append(
                {
                    "tag": item.tag,
                    "type": entry.type if entry else None,
                    "service": service,
                    "position": list(item.position),
                    "shape": resolved.body.shape,
                    "family": resolved.body.family,
                    "size": list(resolved.body.extent),
                    "size_from": resolved.size_from,
                    "rotation_deg": item.rotation_deg,
                    "mount": item.mount.model_dump(exclude_none=True) if item.mount else None,
                    "building": item.building,
                    "level": item.level,
                    "sheet": sheet,
                    "sheet_file": sheet_files.get(sheet) if sheet else None,
                    "bbox": list(layout.box(index)),
                    "clash": item.tag in layout.clashing,
                    "notes": item.notes,
                }
            )
        buildings = []
        for building in layout.buildings.buildings if layout.buildings else []:
            clear = {level.id: height for level, height, _ in level_heights(building)}
            dumped = building.model_dump()
            for level in dumped["levels"]:
                level["clear_height"] = clear[level["id"]]
            buildings.append(
                {
                    **dumped,
                    "footprint": list(building_footprint(building)),
                    "heights": list(building_heights(building)),
                    "clash": ("building", building.id) in refs,
                }
            )
        notes = [
            model.notes
            for model in (plan, layout.buildings, layout.placement)
            if model is not None and model.notes
        ]
        model = _layout_model(snapshot)
        model_findings = []
        if model is not None:
            from chemeascode.domains.spatial.model_rules import model_rules, zone_findings

            try:
                found = zone_findings(model, layout.zones) + model_rules(
                    model, layout.routing, plan
                )
            except (KeyError, TypeError, ValueError):  # a model of another shape: validate says
                found = []
            model_findings = [asdict(finding) for finding in found]
        return {
            "rev": snapshot.commit,
            "files": {kind: texts[kind][0] for kind in texts},
            "site": plan.site.model_dump() if plan else None,
            "areas": [
                {**area.model_dump(), "clash": area.kind == "road" and ("road", area.id) in refs}
                for area in (plan.areas if plan else [])
            ],
            "roads": [
                {**road.model_dump(), "clash": ("road", road.id) in refs}
                for road in (plan.roads if plan else [])
            ],
            "racks": [
                {**rack.model_dump(), "clash": ("rack", rack.id) in refs}
                for rack in (plan.racks if plan else [])
            ],
            "buildings": buildings,
            "equipment": placed,
            "notes": notes,
            "lines": [route.as_dict() for route in layout.lines],
            "separations": [
                rule.model_dump(by_alias=True, exclude_none=True)
                for rule in (plan.separations if plan else [])
            ],
            "model": model,
            "zones": (model or {}).get("zones", []),
            "model_findings": model_findings,
            "findings": [asdict(finding) for finding in layout.findings],
        }

    def _layout_model(snapshot: Snapshot) -> dict[str, Any] | None:
        """The generated ``layout/plant-model.yaml`` at *snapshot*, as data; None without one
        (or when it is not a YAML mapping: validate reports it)."""
        from chemeascode.domains.spatial.model import read

        try:
            text = _text(snapshot, LAYOUT_MODEL_FILE)
        except ApiError:
            return None
        return read(text) if text is not None else None

    def _drawing_meta(snapshot: Snapshot) -> dict[str, str]:
        try:
            config = snapshot.config()
        except ApiError:
            return {}
        meta = {"plant": config.name}
        if config.project is not None:
            project = config.project
            meta.update(
                project=" ".join(v for v in (project.number, project.name) if v),
                client=project.client,
                site=project.site,
                revision=project.revision,
            )
        return meta

    def _model_or_404(snapshot: Snapshot) -> dict[str, Any]:
        model = _layout_model(snapshot)
        if model is None:
            raise ApiError(404, f"no {LAYOUT_MODEL_FILE} at {snapshot.label}")
        return model

    @app.get("/api/layout/plan.svg")
    def get_layout_plan(
        rev: str | None = None, level: str | None = None, z: str | None = None
    ) -> Response:
        """The plot plan, or a level plan (``level=`` id, or ``z=a,b``), of the committed
        model at *rev*."""
        from chemeascode.domains.spatial.drawing2d import level_range, render_plan

        snapshot = repo.snapshot(rev)
        model = _model_or_404(snapshot)
        cut = None
        if level is not None:
            cut = level_range(model, level)
            if cut is None:
                raise ApiError(404, f"no structure or building level {level}")
        elif z is not None:
            try:
                low, high = (float(v) for v in z.split(","))
            except ValueError:
                raise ApiError(400, "z: give two numbers a,b") from None
            cut = (low, high)
        svg = render_plan(model, _drawing_meta(snapshot), cut)
        return Response(svg, media_type="image/svg+xml", headers=_SVG_HEADERS)

    @app.get("/api/mto")
    def get_mto(rev: str | None = None) -> dict[str, Any]:
        """The material take-off of the committed model at *rev* (``cheme assess mto
        --json`` without the source), and its estimate when ``estimate/rates.yaml`` exists."""
        from chemeascode.domains.assessment.estimate import (
            RATES_FILE,
            estimate_payload,
            texts_estimate,
        )
        from chemeascode.domains.assessment.mto import model_takeoff, mto_payload

        snapshot = repo.snapshot(rev)
        text = _text(snapshot, LAYOUT_MODEL_FILE)
        if text is None:
            raise ApiError(404, f"no {LAYOUT_MODEL_FILE} at {snapshot.label}")
        takeoff = model_takeoff(text)
        if any(f.level == "error" for f in takeoff.findings):
            raise ApiError(422, takeoff.findings[0].message)
        payload: dict[str, Any] = {"rev": snapshot.commit, **mto_payload(takeoff)}
        try:
            rates = _text(snapshot, RATES_FILE)
        except ApiError:
            rates = None
        payload["estimate"] = (
            estimate_payload(texts_estimate(text, rates)) if rates is not None else None
        )
        return payload

    @app.get("/api/estimate/equipment")
    def get_equipment_estimate(rev: str | None = None) -> dict[str, Any]:
        """The equipment estimate at *rev* (``cheme assess equipment --json``): the equipment
        list costed from the published correlations, with ``estimate/cost-basis.yaml`` and the
        datasheets. 404 without an equipment list or with no items; 422 for a list that does
        not load."""
        from chemeascode.domains.assessment.equipment_cost import (
            BASIS_FILE,
            CATALYST_INPUTS,
            EQUIPMENT_FILE,
            catalyst_fills_of,
            estimate_equipment,
            load_basis,
        )
        from chemeascode.domains.equipment.datasheets import DATASHEET_DIR
        from chemeascode.domains.equipment.schemas.datasheet import Datasheet
        from chemeascode.foundation.provenance import SourceRevision, content_fingerprint

        snapshot = repo.snapshot(rev)
        found = _small(snapshot, EQUIPMENT_FILE)
        if found is None:
            raise ApiError(404, f"no {EQUIPMENT_FILE} at {snapshot.label}")
        texts = {EQUIPMENT_FILE: found}
        sheet_paths = _datasheet_files(snapshot, (".yaml", ".yml"))
        for path in [BASIS_FILE, *CATALYST_INPUTS, *sheet_paths]:
            try:
                optional = _small(snapshot, path)
            except ApiError:
                continue  # an optional input that cannot be served counts as absent
            if optional is not None:
                texts[path] = optional

        def compute() -> tuple[dict[str, Any] | None, int, str]:
            try:
                equipment = LIST_SCHEMAS["equipment"].model_validate(
                    yaml.safe_load(texts[EQUIPMENT_FILE][0]) or {}
                )
            except (ValidationError, yaml.YAMLError) as failure:
                return None, 422, f"{EQUIPMENT_FILE}: {_first_line(failure)}"
            if not equipment.equipment:
                return None, 404, f"nothing to estimate: no items in {EQUIPMENT_FILE}"
            basis_text = texts.get(BASIS_FILE)
            basis, problems = load_basis(
                basis_text[0].decode("utf-8", errors="replace") if basis_text else None
            )
            sheets = {}
            for path, (content, _) in texts.items():
                if not path.startswith(DATASHEET_DIR + "/"):
                    continue
                try:
                    sheet = Datasheet.model_validate(yaml.safe_load(content) or {})
                except (ValidationError, yaml.YAMLError):
                    continue  # cheme validate reports it; the CLI leaves it out too
                sheets[sheet.tag.strip()] = sheet
            result = estimate_equipment(equipment, sheets, basis)
            # the reactors' first catalyst fills, as cheme assess equipment adds them
            try:
                process = _process(snapshot) if FLOWSHEET_FILE in texts else None
            except ApiError:
                process = None  # a process that does not load costs no catalyst
            lines, found = catalyst_fills_of(process, sheets, result.index)
            result.lines += lines
            result.findings = problems + result.findings + found
            return result.payload(), 200, ""

        key = tuple((path, sha) for path, (_, sha) in sorted(texts.items()))
        payload, status, problem = estimate_cache.get_or_compute(key, compute)
        if payload is None:
            raise ApiError(status, problem)
        # The source of these inputs as served (the cached payload is not changed).
        source = SourceRevision(
            commit=snapshot.commit or repo.head(),
            dirty=_uncommitted(snapshot, {EQUIPMENT_FILE, BASIS_FILE, *texts}),
            fingerprints={path: content_fingerprint(c) for path, (c, _) in sorted(texts.items())},
        )
        return {"rev": snapshot.commit, **payload, "source": source.as_dict()}

    # -- datasheets ------------------------------------------------------------------------

    def _datasheet_report(snapshot: Snapshot) -> tuple[Any, dict[str, Any]]:
        """``project.datasheets.datasheet_report`` of *snapshot* (computed on a private copy
        of its inputs, cached by their blob ids) and the source of the inputs as served."""
        from chemeascode.foundation.provenance import SourceRevision, content_fingerprint
        from chemeascode.project.datasheets import datasheet_report

        files = _datasheet_files(snapshot, (".yaml", ".yml", ".svg"))
        if not any(PurePosixPath(f).suffix in (".yaml", ".yml") for f in files):
            raise ApiError(404, f"no datasheets in equipment/datasheets at {snapshot.label}")
        texts: dict[str, tuple[bytes, str]] = {}
        try:
            sheets = [s["file"] for s in snapshot.sheets(snapshot.config()) if s.get("file")]
        except ApiError:
            sheets = []
        for path in (
            PLANT_FILE,
            LIST_FILES["equipment"],
            LIST_FILES["lines"],
            LAYOUT_MODEL_FILE,
            *sheets,
            *files,
        ):
            try:
                found = _small(snapshot, path)
            except ApiError:
                continue  # an input that cannot be served counts as absent
            if found is not None:
                texts[path] = found

        def compute() -> Any:
            # The report reads files: a private temporary copy, never the repository.
            with tempfile.TemporaryDirectory() as tmp:
                for path, (content, _) in texts.items():
                    target = Path(tmp, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                return datasheet_report(Path(tmp))

        key = tuple((path, sha) for path, (_, sha) in sorted(texts.items()))
        report = datasheet_cache.get_or_compute(key, compute)
        source = SourceRevision(
            commit=snapshot.commit or repo.head(),
            dirty=_uncommitted(snapshot, texts),
            fingerprints={path: content_fingerprint(c) for path, (c, _) in sorted(texts.items())},
        )
        return report, source.as_dict()

    def _datasheet_entry(snapshot: Snapshot, tag: str) -> tuple[Any, Any, dict[str, Any]]:
        report, source = _datasheet_report(snapshot)
        entry = report.entry(tag)
        if entry is None:
            raise ApiError(404, f"no datasheet of {tag} at {snapshot.label}")
        return report, entry, source

    @app.get("/api/datasheets")
    def get_datasheets(rev: str | None = None) -> dict[str, Any]:
        """The datasheets at *rev*: per datasheet its tag, class, service, draft, the counts of
        assumed, TBD, supplier and not_applicable fields, the outline drawing's state and the
        findings by level; the listed items without a datasheet. 404 without datasheets."""
        snapshot = repo.snapshot(rev)
        report, source = _datasheet_report(snapshot)
        return {"rev": snapshot.commit, **report.index(), "source": source}

    @app.get("/api/datasheets/{tag}.svg")
    def get_datasheet_drawing(
        tag: str, rev: str | None = None, generated: bool = False
    ) -> Response:
        """The outline drawing of *tag* at *rev*: the committed
        ``equipment/datasheets/<TAG>.svg``, or (when there is none, or with ``generated=true``)
        the one ``cheme datasheets drawing`` would write. ``X-Cheme-Drawing`` says which
        (``committed`` or ``generated``), ``X-Cheme-Drawing-Current`` whether the committed one
        is what the datasheet gives now."""
        snapshot = repo.snapshot(rev)
        _, entry, _ = _datasheet_entry(snapshot, tag)
        committed = None
        if not generated:
            try:
                committed = _small(snapshot, clean_path(entry.drawing))
            except ApiError:
                committed = None
        headers = dict(_SVG_HEADERS)
        if committed is not None:
            headers["X-Cheme-Drawing"] = "committed"
            headers["X-Cheme-Drawing-Current"] = str(entry.drawing_state == "current").lower()
            return Response(committed[0], media_type="image/svg+xml", headers=headers)
        if entry.drawing_text is None:
            raise ApiError(422, f"{entry.file} does not validate: no drawing (cheme validate)")
        headers["X-Cheme-Drawing"] = "generated"
        return Response(entry.drawing_text, media_type="image/svg+xml", headers=headers)

    @app.get("/api/datasheets/{tag}")
    def get_datasheet(tag: str, rev: str | None = None) -> dict[str, Any]:
        """One datasheet at *rev*: the file as data, the parsed datasheet (None when it does not
        validate), its summary as in ``/api/datasheets`` and the findings on it and its
        drawing (schema, markers, against the equipment list, the layout model, the P&IDs and
        the line list, drawing drift)."""
        snapshot = repo.snapshot(rev)
        _, entry, source = _datasheet_entry(snapshot, tag)
        return {
            "rev": snapshot.commit,
            "tag": entry.tag,
            "file": entry.file,
            "summary": entry.summary(),
            "datasheet": entry.sheet.model_dump(mode="json") if entry.sheet else None,
            "data": json_safe(entry.data) if entry.data is not None else None,
            "drawing": {
                "file": entry.drawing,
                "state": entry.drawing_state,
                "current": entry.drawing_state == "current",
            },
            "findings": [{**asdict(f), "id": f.id} for f in entry.findings],
            "source": source,
        }

    @app.get("/api/lca")
    def get_lca(rev: str | None = None) -> dict[str, Any]:
        """The LCA at *rev* (``cheme assess lca --json`` without the source): inventory,
        impacts by scenario, category, phase and contributor, and the findings. 404 without
        ``lca/lca.yaml``; 422 when the LCA does not compute (its first error)."""
        from chemeascode.domains.assessment.lca.inventory import LCA_FILE
        from chemeascode.domains.assessment.lca.report import (
            REPORT_INPUTS,
            dataset_paths,
            lca_report,
        )

        snapshot = repo.snapshot(rev)
        for path in (LCA_FILE, PLANT_FILE):
            if not _exists(snapshot, path):
                raise ApiError(404, f"no {path} at {snapshot.label}")
        texts = {}
        for path in (PLANT_FILE, *REPORT_INPUTS):
            try:
                found = _small(snapshot, path)
            except ApiError:
                if path in (LCA_FILE, PLANT_FILE):
                    raise
                continue  # an optional input that cannot be served counts as absent
            if found is not None:
                texts[path] = found

        def read(path: str) -> str | None:
            try:
                found = _small(snapshot, clean_path(path))
            except ApiError:
                return None  # outside the repository or too large: the report says so
            if found is None:
                return None
            texts[clean_path(path)] = found
            return found[0].decode("utf-8", errors="replace")

        # the LCI datasets the study references (recursively), so the copy resolves them
        dataset_paths(texts[LCA_FILE][0].decode("utf-8", errors="replace"), read)

        def compute() -> tuple[dict[str, Any] | None, str]:
            # The report reads files: a private temporary copy, never the repository.
            with tempfile.TemporaryDirectory() as tmp:
                for path, (content, _) in texts.items():
                    target = Path(tmp, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                report = lca_report(Path(tmp))
            findings = [{**asdict(f), "id": f.id} for f in report.findings]
            if not report.loaded:
                first = next((f for f in report.findings if f.level == "error"), None)
                if first is None:
                    return None, f"{LCA_FILE}: does not compute"
                where = f"{first.file}:{first.line}" if first.line else first.file
                message = first.message
                return None, message if message.startswith(where) else f"{where}: {message}"
            return {**report.payload(), "findings": findings}, ""

        try:
            backend = (yaml.safe_load(texts[LCA_FILE][0]) or {}).get("backend")
        except (yaml.YAMLError, UnicodeDecodeError, AttributeError):
            backend = None
        if backend == "brightway":
            # The impacts also depend on the Brightway project outside the repository: computed
            # every time (no cache), one at a time (bw2data's current project is global).
            with brightway_lock:
                payload, problem = compute()
        else:
            key = tuple((path, sha) for path, (_, sha) in sorted(texts.items()))
            payload, problem = lca_cache.get_or_compute(key, compute)
        if payload is None:
            raise ApiError(422, problem)
        return {"rev": snapshot.commit, **payload}

    @app.get("/api/tea")
    def get_tea(rev: str | None = None) -> dict[str, Any]:
        """The TEA at *rev* (``cheme assess tea --json`` without the source): premises, capital
        cost, flows, cash flow, results, scenarios, tornado, break-even values, the Monte Carlo
        and the findings. 404 without ``estimate/tea.yaml``; 422 when the TEA does not compute
        (its first error)."""
        from chemeascode.domains.assessment.tea.report import REPORT_INPUTS, TEA_FILE, tea_report

        snapshot = repo.snapshot(rev)
        for path in (TEA_FILE, PLANT_FILE):
            if not _exists(snapshot, path):
                raise ApiError(404, f"no {path} at {snapshot.label}")
        texts = {}
        for path in (*REPORT_INPUTS, *_datasheet_files(snapshot, (".yaml", ".yml"))):
            try:
                found = _small(snapshot, path)
            except ApiError:
                if path in (TEA_FILE, PLANT_FILE):
                    raise
                continue  # an optional input that cannot be served counts as absent
            if found is not None:
                texts[path] = found

        def compute() -> tuple[dict[str, Any] | None, str]:
            # The report reads files: a private temporary copy, never the repository.
            with tempfile.TemporaryDirectory() as tmp:
                for path, (content, _) in texts.items():
                    target = Path(tmp, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                report = tea_report(Path(tmp))
            findings = [{**asdict(f), "id": f.id} for f in report.findings]
            if not report.loaded:
                first = next((f for f in report.findings if f.level == "error"), None)
                if first is None:
                    return None, f"{TEA_FILE}: does not compute"
                where = f"{first.file}:{first.line}" if first.line else first.file
                message = first.message
                return None, message if message.startswith(where) else f"{where}: {message}"
            return {**report.payload(), "findings": findings}, ""

        key = tuple((path, sha) for path, (_, sha) in sorted(texts.items()))
        payload, problem = tea_cache.get_or_compute(key, compute)
        if payload is None:
            raise ApiError(422, problem)
        return {"rev": snapshot.commit, **payload}

    @app.get("/api/layout/section.svg")
    def get_layout_section(
        rev: str | None = None,
        x: float | None = None,
        y: float | None = None,
        depth: float = 6.0,
    ) -> Response:
        """A section at ``x=`` or ``y=`` (``depth`` m thick) of the committed model at *rev*."""
        from chemeascode.domains.spatial.drawing2d import render_section

        if (x is None) == (y is None):
            raise ApiError(400, "give x= or y= (one of them)")
        if not 0 < depth <= 1000:
            raise ApiError(400, "depth must be between 0 and 1000 m")
        snapshot = repo.snapshot(rev)
        model = _model_or_404(snapshot)
        axis, at = ("x", x) if x is not None else ("y", y)
        svg = render_section(model, axis, float(at), depth, _drawing_meta(snapshot))  # type: ignore[arg-type]
        return Response(svg, media_type="image/svg+xml", headers=_SVG_HEADERS)

    @app.get("/api/status")
    def get_status() -> dict[str, Any]:
        """``cheme status --json`` of the working tree, without running the gates (they may
        run commands); the gates are ``POST /api/checks/run``."""
        from chemeascode.project.status import plant_status

        try:
            return plant_status(repo.workspace, run_gates=False)
        except (ValidationError, yaml.YAMLError) as failure:
            raise ApiError(422, f"cannot summarize: {_first_line(failure)}") from failure

    @app.get("/api/impact")
    def get_impact() -> dict[str, Any]:
        """``cheme impact --json`` of the working tree: review-needed findings (info)."""
        from chemeascode.project.impact import impact_report

        return impact_report(repo.workspace)

    @app.get("/api/interlocks")
    def get_interlocks(rev: str | None = None) -> dict[str, Any]:
        from chemeascode.domains.control.interlocks import matrix

        snapshot = repo.snapshot(rev)
        path = LIST_FILES["interlocks"]
        text = _text(snapshot, path)
        if text is None:
            raise ApiError(404, f"no {path} at {snapshot.label}")
        try:
            model = LIST_SCHEMAS["interlocks"].model_validate(yaml.safe_load(text) or {})
        except (ValidationError, yaml.YAMLError) as failure:
            raise ApiError(422, f"{path}: {_first_line(failure)}") from failure
        return {
            "rev": snapshot.commit,
            "file": path,
            "interlocks": [i.model_dump(by_alias=True) for i in model.interlocks],
            **matrix(model),
        }

    @app.get("/api/issues")
    def get_issues() -> dict[str, Any]:
        """``cheme issues --json`` of the working tree's plant: its GitHub issues as engineering
        items (read-only, cached as for the gates: project.issues.CACHE_S); 404 when plant.yaml
        declares no issues, 503 when they cannot be read (no token, no network)."""
        from chemeascode.project.issues import IssuesUnavailable, issues_report

        if repo.workspace.config().issues is None:
            raise ApiError(404, "plant.yaml declares no issues")
        try:
            return issues_report(repo.workspace)
        except IssuesUnavailable as failure:
            raise ApiError(503, f"issues not read: {failure}") from failure

    @app.get("/api/control")
    def get_control() -> dict[str, Any]:
        """``cheme control report --json`` of the working tree: loops, sequences, the
        narrative and the control philosophy with their review status and findings; 404 when
        the plant has none of them (control documentation is optional)."""
        from chemeascode.domains.control.report import control_report

        try:
            report = control_report(repo.root)
        except (ValidationError, yaml.YAMLError, UnicodeDecodeError) as failure:
            raise ApiError(422, f"cannot report: {_first_line(failure)}") from failure
        if not report.present:
            raise ApiError(404, "no control records (loops, sequences, narrative, philosophy)")
        return json.loads(json.dumps(report.as_dict(), default=str))

    # -- process ---------------------------------------------------------------------

    def _process(snapshot: Snapshot) -> Any:
        """``process/*.yaml`` of *snapshot*, loaded as ``cheme process`` loads them (422 when
        the flowsheet does not load), cached by blob ids."""
        from chemeascode.domains.process.model import load
        from chemeascode.domains.process.simulation import SIMULATION_FILE
        from chemeascode.domains.process.simulation.translate import prime

        texts = {}
        for path in (
            MATERIALS_FILE,
            FLOWSHEET_FILE,
            REACTIONS_FILE,
            CATALYSTS_FILE,
            SIMULATION_FILE,
        ):
            found = _small(snapshot, path)
            if found is not None:
                texts[path] = found
        if FLOWSHEET_FILE not in texts:
            raise ApiError(404, f"no {FLOWSHEET_FILE} at {snapshot.label}")

        def compute() -> tuple[Any, str]:
            # The loader reads files: a private temporary copy, never the repository.
            with tempfile.TemporaryDirectory() as tmp:
                for path, (content, _) in texts.items():
                    target = Path(tmp, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                process, findings = load(Path(tmp))
                if process is not None:  # the staleness of simulated values reads simulation.yaml
                    prime(process)
            # reactions.yaml and catalysts.yaml are optional: their errors leave the
            # flowsheet without them
            optional = (REACTIONS_FILE, CATALYSTS_FILE)
            errors = [f for f in findings if f.level == "error" and f.file not in optional]
            if process is None or errors:
                first = errors[0] if errors else None
                where = f"{first.file}:{first.line}" if first and first.line else FLOWSHEET_FILE
                return None, f"{where}: {first.message if first else 'does not load'}"
            return process, ""

        key = tuple((path, sha) for path, (_, sha) in sorted(texts.items()))
        process, problem = process_cache.get_or_compute(key, compute)
        if process is None:
            raise ApiError(422, problem)
        return process

    @app.get("/api/streams")
    def get_streams(case: str | None = None, rev: str | None = None) -> dict[str, Any]:
        from chemeascode.domains.process.sheets import represented
        from chemeascode.domains.process.streams import stream_table

        snapshot = repo.snapshot(rev)
        process = _process(snapshot)
        cases = [c.id for c in process.flowsheet.cases]
        case = case or process.flowsheet.default_case()
        if case not in cases:
            raise ApiError(422, f"case {case} is not declared (cases: {', '.join(cases)})")
        try:
            sheet_ids = {s["id"] for s in snapshot.sheets(snapshot.config())}
        except ApiError:
            sheet_ids = set()
        lists = {
            k: m for k in ("equipment", "lines", "instruments") if (m := _list_model(snapshot, k))
        }
        table = stream_table(process, case, lists, sheet_ids)
        # the drill-down follows the drawn BFD: its connections' represents: lines, where built
        drawn: dict[str, list[str]] = {}
        try:
            for sheet in snapshot.sheets(snapshot.config()):
                file = sheet.get("file")
                if sheet.get("kind") != "bfd" or not file:
                    continue
                try:
                    found = _small(snapshot, file)
                except ApiError:  # too large, or not served: the drawn BFD is left out
                    continue
                if found is not None:
                    drawn.update(represented(found[0]))
        except ApiError:
            pass
        if drawn:
            table["bfd_connections"] = drawn
        table["bfd_connections_from"] = "sheet" if drawn else "flowsheet"
        return {"rev": snapshot.commit, **table}

    def _case_of(process: Any, case: str | None) -> str:
        cases = [c.id for c in process.flowsheet.cases]
        case = case or process.flowsheet.default_case()
        if case not in cases:
            raise ApiError(422, f"case {case} is not declared (cases: {', '.join(cases)})")
        return case

    @app.get("/api/simulation")
    def get_simulation(case: str | None = None, rev: str | None = None) -> dict[str, Any]:
        """``process/simulation.yaml`` parsed, the run ``cheme process simulate --fill``
        recorded in ``process/simulation-run.json`` (null without one), whether that record is
        stale against the inputs now, and one merged row per unit. 404 without the simulation
        file; 422 when it does not load or for an unknown case. A flowsheet that does not load
        leaves the spec and the record, with ``stale`` null and ``problem`` saying why."""
        from chemeascode.domains.process.simulation import SIMULATION_FILE, record
        from chemeascode.domains.process.simulation.translate import load as load_simulation
        from chemeascode.foundation.provenance import content_fingerprint

        snapshot = repo.snapshot(rev)
        sim_text = _need(snapshot, SIMULATION_FILE)
        texts = {}
        for path in (*record.RUN_INPUTS, record.RUN_FILE):
            try:
                found = _small(snapshot, path)
            except ApiError:
                continue  # too large or not served: counts as absent
            if found is not None:
                texts[path] = found
        try:
            process, problem = _process(snapshot), ""
        except ApiError as failure:
            process, problem = None, failure.message
        if process is not None:
            case = _case_of(process, case)

        def compute() -> tuple[Any, dict[str, Any] | None, str]:
            # The loader reads the file: a private temporary copy, never the repository.
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp, SIMULATION_FILE)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(sim_text[0])
                sim, doc, found = load_simulation(Path(tmp))
            if sim is None:
                first = found[0] if found else None
                where = (
                    f"{SIMULATION_FILE}:{first.line}" if first and first.line else SIMULATION_FILE
                )
                return process, None, f"{where}: {first.message if first else 'does not load'}"
            fingerprints = {
                p: content_fingerprint(c) for p, (c, _) in texts.items() if p != record.RUN_FILE
            }
            data = record.parse(texts[record.RUN_FILE][0]) if record.RUN_FILE in texts else None
            view = record.view(process, sim, doc, data, case, fingerprints, problem)
            return process, view, ""

        # the process object is cached by its blob ids: holding it keeps its id unique
        key = (id(process), case, tuple((p, sha) for p, (_, sha) in sorted(texts.items())))
        _, payload, failed = simulation_cache.get_or_compute((key, sim_text[1]), compute)
        if payload is None:
            raise ApiError(422, failed)
        return {"rev": snapshot.commit, **payload}

    def _chemistry(snapshot: Snapshot, lenient: bool = False) -> Any:
        """The plant's components, reactions and catalysts at *snapshot*: its process when it has a
        flowsheet, else its materials, reactions and catalysts alone (None: no process files)."""
        from chemeascode.domains.process.microkinetic_report import load_chemistry

        if _exists(snapshot, FLOWSHEET_FILE):
            try:
                return _process(snapshot)
            except ApiError:
                if not lenient:
                    raise
                # *lenient*: a flowsheet that does not load leaves the chemistry without it
        texts = {}
        for path in (MATERIALS_FILE, REACTIONS_FILE, CATALYSTS_FILE):
            found = _small(snapshot, path)
            if found is not None:
                texts[path] = found
        if not texts:
            return None

        def compute() -> tuple[Any, str]:
            with tempfile.TemporaryDirectory() as tmp:
                for path, (content, _) in texts.items():
                    target = Path(tmp, path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(content)
                return load_chemistry(Path(tmp)), ""

        key = ("chemistry", *((path, sha) for path, (_, sha) in sorted(texts.items())))
        chemistry, _ = process_cache.get_or_compute(key, compute)
        return chemistry

    @app.get("/api/kinetics")
    def get_kinetics(rev: str | None = None) -> dict[str, Any]:
        """The kinetic data files of ``experiments/kinetics/`` with their points and default
        fits (``cheme experiments fit-rate``). 404 without any."""
        from chemeascode.project.kinetics import kinetic_data_view

        snapshot = repo.snapshot(rev)
        paths = _folder_files(snapshot, KINETICS_DIR, (".yaml", ".yml"))
        if not paths:
            raise ApiError(404, f"no {KINETICS_DIR}/*.yaml at {snapshot.label}")
        texts = {}
        for path in paths:
            found = _small(snapshot, path)
            if found is not None:
                texts[path] = found
        chemistry = _chemistry(snapshot, lenient=True)  # the fits need no flowsheet
        if chemistry is None:
            raise ApiError(404, f"no process files at {snapshot.label}")

        def compute() -> tuple[Any, dict[str, Any]]:
            decoded = {p: c.decode("utf-8", errors="replace") for p, (c, _) in texts.items()}
            return chemistry, kinetic_data_view(chemistry, decoded)

        # the chemistry object is cached by its blob ids: holding it keeps its id unique
        key = ("kinetics", id(chemistry), *((p, sha) for p, (_, sha) in sorted(texts.items())))
        _, payload = reactions_cache.get_or_compute(key, compute)
        return {"rev": snapshot.commit, **payload}

    @app.get("/api/library")
    def get_library(rev: str | None = None) -> dict[str, Any]:
        """The reaction library (``cheme chemistry library``), each item marked when the plant
        has it."""
        from chemeascode.domains.process.reaction_library import library_view

        snapshot = repo.snapshot(rev)
        chemistry = _chemistry(snapshot, lenient=True)
        return {"rev": snapshot.commit, **library_view(chemistry)}

    @app.get("/api/reactions")
    def get_reactions(case: str | None = None, rev: str | None = None) -> dict[str, Any]:
        """``process/reactions.yaml`` with what the flowsheet says about each reaction, the
        ``cheme process reactors`` rows, the reactive balances with their findings, each
        rate law with its units and k(T), and the catalysts of ``process/catalysts.yaml``. 404
        without the reactions file or the flowsheet; 422 when either does not load or for an
        unknown case."""
        from chemeascode.domains.process.reaction_view import reactions_payload

        snapshot = repo.snapshot(rev)
        content, _ = _need(snapshot, REACTIONS_FILE)
        process = _process(snapshot)
        if process.reactions is None:
            try:
                Reactions.model_validate(yaml.safe_load(content) or {})
                problem = "does not load"
            except yaml.YAMLError as failure:
                problem = _first_line(failure)
            except ValidationError as failure:
                e = failure.errors()[0]
                problem = f"{'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}"
            raise ApiError(422, f"{REACTIONS_FILE}: {problem}")
        case = _case_of(process, case)
        # the process object is cached by its blob ids: holding it keeps its id unique
        _, payload = reactions_cache.get_or_compute(
            (id(process), case), lambda: (process, reactions_payload(process, case))
        )
        return {"rev": snapshot.commit, **payload}

    # -- checks ---------------------------------------------------------------------

    @app.get("/api/validate")
    def get_validate() -> dict[str, Any]:
        try:
            return json.loads(validate_workspace(repo.workspace).to_json())
        except (ValidationError, yaml.YAMLError) as failure:
            raise ApiError(422, f"cannot validate: {_first_line(failure)}") from failure

    @app.get("/api/maturity")
    def get_maturity(through: str | None = None) -> dict[str, Any]:
        """``cheme maturity --json`` of the working tree: the levels, requirement by
        requirement, the model basis, limitations and findings. Evaluated on every request
        (:func:`~chemeascode.project.maturity.maturity_payload`), one at a time; nothing is
        written (``checked_at`` is the time of this evaluation, in the answer only; ``cheme
        maturity --write`` writes ``checks/maturity.json``). Without *through* the engineering
        level runs the whole-repository validation, the dominant cost (some 30 s on a plant
        like ASU-1); ``through=predictive`` (or a lower level) skips it and reports the levels
        above as ``not-evaluated``. 400 for an unknown level; 422 when the plant does not load."""
        from chemeascode.project.maturity import LEVELS, maturity_payload

        ids = [level[0] for level in LEVELS]
        if through is not None and through not in ids:
            raise ApiError(400, f"through: one of {', '.join(ids)}")
        with maturity_lock:
            try:
                return maturity_payload(repo.workspace.root, through=through)
            except (ValidationError, yaml.YAMLError) as failure:
                raise ApiError(422, f"cannot evaluate: {_first_line(failure)}") from failure

    def _refuse_remote_checks() -> None:
        if not run_checks_allowed:
            raise ApiError(
                403,
                "running the checks is turned off: the server is reachable from the network "
                "(start cheme serve with --allow-remote-checks to allow it)",
            )

    @app.get("/api/session")
    def get_session() -> dict[str, str]:
        # Readable only by the served origin: no CORS headers, cross-site requests refused.
        _refuse_remote_checks()
        return {"token": token, "header": TOKEN_HEADER}

    @app.post("/api/checks/run")
    def post_checks_run(request: Request) -> dict[str, Any]:
        _refuse_remote_checks()
        if not secrets.compare_digest(request.headers.get(TOKEN_HEADER, ""), token):
            raise ApiError(403, f"missing or wrong {TOKEN_HEADER} (see GET /api/session)")
        if not check_run.acquire(blocking=False):
            raise ApiError(409, "the checks are already running")
        try:
            results = run_checks(repo.workspace, timeout=CHECK_TIMEOUT)
        except (ValidationError, yaml.YAMLError) as failure:
            raise ApiError(422, f"checks/checks.yaml: {_first_line(failure)}") from failure
        finally:
            check_run.release()
        return {"checks": [asdict(r) for r in results]}

    @app.get("/api/checks")
    def get_checks(run: bool = False, rev: str | None = None) -> Any:
        if run:
            # Running executes commands from checks.yaml: never on a plain GET.
            raise ApiError(405, "running the checks is POST /api/checks/run")
        found = _small(repo.snapshot(rev), "checks/status.json")
        if found is None:
            return {"checks": []}
        try:
            return json.loads(found[0])
        except ValueError as failure:
            raise ApiError(422, f"checks/status.json: {failure}") from failure

    # -- the viewer --------------------------------------------------------------------

    @app.get("/{full_path:path}", include_in_schema=False)
    def get_ui(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith("api/"):
            raise ApiError(404, f"no endpoint /{full_path}")
        if ui is None:
            raise ApiError(404, "no viewer: start `cheme serve --ui DIST_DIR`; API at /api/")
        candidate = (ui / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(ui):
            return FileResponse(candidate, headers=_UI_HEADERS)
        if full_path.startswith("assets/"):
            # A missing bundle file must not come back as index.html (a confusing MIME error).
            raise ApiError(404, f"no file /{full_path}")
        return FileResponse(ui / "index.html", headers=_UI_HEADERS)

    return app


def is_local_bind(host: str) -> bool:
    """Whether binding *host* keeps the server on this machine (a loopback address)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_wildcard(host: str) -> bool:
    """Whether binding *host* means every interface (``0.0.0.0``, ``::``): it names no host a
    request could use."""
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def accepted_hosts(host: str, extra: Iterable[str] = ()) -> list[str]:
    """The ``Host`` header names the server accepts when bound to *host*: the local names, the
    bound address unless it is a wildcard (:func:`_is_wildcard`), and the *extra* names
    (``--allow-host``, an IPv6 address with or without brackets). Never ``*``: a page whose
    own name was rebound to this machine must not be able to read the repository (DNS
    rebinding). :class:`ValueError` for an *extra* wildcard, or one with a port, which no
    ``Host`` header could match."""
    names = set(LOCAL_HOSTS)
    for name in extra:
        if not name or "*" in name:
            raise ValueError("--allow-host takes a host name or address, not a wildcard")
        bare = name[1:-1] if name.startswith("[") and name.endswith("]") else name
        if _host_name(name) != bare or "/" in bare:
            raise ValueError(f"--allow-host {name!r}: give the host name or address alone, no port")
        names.add(bare.lower())
    if not _is_wildcard(host):
        names.add(host.lower())
    return sorted(names)


def serve(
    repo_root: Path,
    host: str = "127.0.0.1",
    port: int = 8765,
    ui_dir: Path | None = None,
    allow_hosts: Iterable[str] = (),
    allow_remote_checks: bool = False,
    library: bool = False,
) -> None:
    """Run the API (and the viewer, with *ui_dir*) until interrupted.

    *allow_hosts*: further names the server accepts in the ``Host`` header (see
    :func:`accepted_hosts`). *allow_remote_checks*: let ``POST /api/checks/run`` run the checks
    although *host* is not a local address. *library*: *repo_root* is a folder of plants, each
    served under ``/p/<id>/`` (:mod:`.library`)."""
    import uvicorn

    make: Callable[..., Any] = create_app
    if library:
        from chemeascode.interfaces.api.library import create_library_app

        make = create_library_app
    app = make(
        repo_root,
        ui_dir,
        allowed_hosts=accepted_hosts(host, allow_hosts),
        run_checks_allowed=is_local_bind(host) or allow_remote_checks,
    )
    uvicorn.run(app, host=host, port=port, log_level="info")
