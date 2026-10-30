"""``cheme serve`` on a folder of plants (a process library): every plant under ``/p/<id>/``.

A library is a folder without ``plant.yaml`` with plants below it, such as process-library's
``processes/*/plant.yaml``, or a folder of separate plant repositories. :func:`discover_plants`
finds them; :func:`create_library_app` serves:

- ``GET /api/plants``: the plants (id, path, name, stage, sheets, the recorded maturity, and the
  ``title``, ``summary`` and ``families`` of a ``process.yaml`` when there is one; the viewer
  never depends on those);
- ``/p/<id>/...``: the plant's own app (:func:`..serve.create_app`, unchanged), created when it
  is first asked for, with the request's path below the prefix (``/p/asu-1/api/repo`` is
  ``/api/repo`` of ``asu-1``); a plant in a subfolder of a git repository reads its history from
  that repository, as ``cheme serve`` in the plant does;
- the viewer at ``/`` (its library index) and at every ``/p/<id>/`` page.

The same guards apply as for one plant (see :mod:`.serve`): the ``Host`` header check, the
refusal of cross-site requests to ``/api/*``, and the per-plant session token of ``POST
/api/checks/run``. A plant id is only ever looked up among the discovered plants, so a URL cannot
name a path. See ADR 0034.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from pydantic import ValidationError

from chemeascode.foundation.workspace import PLANT_FILE
from chemeascode.interfaces.api.serve import (
    _UI_HEADERS,
    LOCAL_HOSTS,
    _cross_site,
    _host_name,
    create_app,
    import_pydexpi,
)
from chemeascode.schemas import PlantConfig

#: How deep below the library root plants are looked for (``processes/<id>/plant.yaml`` is 2).
MAX_DEPTH = 3
#: Folders never searched for plants.
SKIPPED_DIRS = {"node_modules", "build", "dist", "site", "venv", "__pycache__"}
#: The recorded maturity report of a plant (``cheme maturity --write``).
MATURITY_FILE = "checks/maturity.json"
#: A process-library manifest beside ``plant.yaml``: the optional title, summary and families.
PROCESS_FILE = "process.yaml"

_PLANT_PATH = re.compile(r"^/p/([^/]+)(/.*)?$")


@dataclass(frozen=True)
class Plant:
    """A plant of the library: *id* in URLs, *root* its folder, *path* relative to the library."""

    id: str
    root: Path
    path: str


def _plant_dirs(root: Path) -> list[Path]:
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if (directory / PLANT_FILE).is_file():
            found.append(directory)
            return  # a plant's own folders are the plant's
        if depth >= MAX_DEPTH:
            return
        try:
            children = sorted(p for p in directory.iterdir() if p.is_dir())
        except OSError:
            return
        for child in children:
            if child.name.startswith(".") or child.name in SKIPPED_DIRS or child.is_symlink():
                continue
            walk(child, depth + 1)

    walk(root, 0)
    return found


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", text.lower()).strip("-") or "plant"


def discover_plants(root: Path) -> list[Plant]:
    """The plants below *root* (not *root* itself), at most :data:`MAX_DEPTH` folders down,
    by id. The id is the plant's folder name; when two share it, their relative paths."""
    root = root.resolve()
    dirs = [d for d in _plant_dirs(root) if d != root]
    names: dict[str, int] = {}
    for d in dirs:
        names[_slug(d.name)] = names.get(_slug(d.name), 0) + 1
    plants = []
    for d in dirs:
        path = d.relative_to(root).as_posix()
        name = _slug(d.name)
        plants.append(Plant(name if names[name] == 1 else _slug(path.replace("/", "-")), d, path))
    return sorted(plants, key=lambda p: p.id)


def _yaml(path: Path) -> dict[str, Any] | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def plant_entry(plant: Plant) -> dict[str, Any]:
    """One plant of ``GET /api/plants``, read from its working tree. A ``plant.yaml`` that does
    not validate still lists the plant (``error`` says why); nothing is evaluated live."""
    entry: dict[str, Any] = {
        "id": plant.id,
        "path": plant.path,
        "name": None,
        "stage": None,
        "sheets": 0,
        "maturity": None,
        "maturity_checked": None,
        "title": None,
        "summary": None,
        "families": [],
        "error": None,
    }
    try:
        config = PlantConfig.model_validate(_yaml(plant.root / PLANT_FILE) or {})
    except ValidationError as failure:
        entry["error"] = f"{PLANT_FILE}: {str(failure).splitlines()[0]}"
    else:
        entry["name"] = config.name or None
        entry["stage"] = config.stage
        entry["sheets"] = len(config.sheets)
    try:
        report = json.loads((plant.root / MATURITY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        report = None
    if isinstance(report, dict):
        level = report.get("level")
        entry["maturity"] = level if isinstance(level, str) else None
        checked = report.get("checked_at")
        entry["maturity_checked"] = checked if isinstance(checked, str) else None
    process = _yaml(plant.root / PROCESS_FILE)
    if process:
        entry["title"] = _text(process.get("title"))
        entry["summary"] = _text(process.get("summary"))
        families = process.get("families")
        if isinstance(families, list):
            entry["families"] = [f for f in families if isinstance(f, str)]
    return entry


def _json_error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def create_library_app(
    library_root: Path,
    ui_dir: Path | None = None,
    allowed_hosts: list[str] | None = None,
    run_checks_allowed: bool = True,
    plant_app: Callable[..., Any] = create_app,
) -> Any:
    """The ASGI app serving every plant below *library_root* (see the module docstring).

    *ui_dir*, *allowed_hosts* and *run_checks_allowed* as for :func:`..serve.create_app`, and
    passed on to each plant's app. :class:`ValueError` when there is no plant below the root."""
    root = library_root.resolve()
    plants = {p.id: p for p in discover_plants(root)}
    if not plants:
        raise ValueError(f"no {PLANT_FILE} below {root} (looked {MAX_DEPTH} folders deep)")
    ui = ui_dir.resolve() if ui_dir else None
    if ui is not None and not (ui / "index.html").is_file():
        raise FileNotFoundError(f"{ui} has no index.html")
    import_pydexpi()
    hosts = {name.lower() for name in allowed_hosts or LOCAL_HOSTS}
    apps: dict[str, Any] = {}
    lock = threading.Lock()

    def app_for(plant: Plant) -> Any:
        with lock:
            if plant.id not in apps:
                apps[plant.id] = plant_app(
                    plant.root,
                    ui_dir,
                    allowed_hosts=allowed_hosts,
                    run_checks_allowed=run_checks_allowed,
                )
            return apps[plant.id]

    index = FastAPI(title="cheme-as-code library", docs_url=None, redoc_url=None, openapi_url=None)
    index.state.plants = plants

    @index.middleware("http")
    async def _check_host(request: Request, call_next):
        host = request.headers.get("host", "")
        if "*" not in hosts and _host_name(host).lower() not in hosts:
            return _json_error(400, "invalid Host header")
        if request.url.path.startswith("/api/"):
            refusal = _cross_site(request, host)
            if refusal:
                return _json_error(403, refusal)
        return await call_next(request)

    @index.get("/api/plants")
    def get_plants() -> dict[str, Any]:
        return {
            "root_name": root.name,
            "plants": [plant_entry(p) for p in plants.values()],
        }

    @index.get("/p/{plant_id}")
    def get_plant_root(plant_id: str) -> Response:
        if plant_id not in plants:
            return _json_error(404, f"no plant {plant_id!r} in this library")
        return RedirectResponse(f"/p/{plant_id}/", status_code=307)

    @index.get("/{full_path:path}", include_in_schema=False)
    def get_ui(full_path: str) -> Response:
        if full_path == "api" or full_path.startswith(("api/", "p/")):
            return _json_error(404, f"no endpoint /{full_path}")
        if ui is None:
            return _json_error(404, "no viewer: start `cheme serve --ui DIST_DIR`; API at /api/")
        candidate = (ui / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(ui):
            return FileResponse(candidate, headers=_UI_HEADERS)
        if full_path.startswith("assets/"):
            return _json_error(404, f"no file /{full_path}")
        return FileResponse(ui / "index.html", headers=_UI_HEADERS)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] in ("http", "websocket"):
            match = _PLANT_PATH.match(scope["path"])
            if match and match.group(2) is not None:
                plant = plants.get(match.group(1))
                if plant is None:
                    response = _json_error(404, f"no plant {match.group(1)!r} in this library")
                    await response(scope, receive, send)
                    return
                rest = match.group(2)
                # The plant's app sees its own paths (`/api/repo`). The prefix is not added to
                # root_path: Starlette builds request.url from root_path + path, and the plant
                # app's guards test request.url.path for `/api/`.
                inner = {**scope, "path": rest, "raw_path": rest.encode()}
                await app_for(plant)(inner, receive, send)
                return
        await index(scope, receive, send)

    app.plants = plants  # type: ignore[attr-defined]
    return app
