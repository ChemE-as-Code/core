"""A plant repository on disk: where its files are and what kind each one is.

A plant repository is any directory holding a ``plant.yaml``. Everything else is found by
convention, relative to that root, so a command run anywhere inside the repository works on the
whole plant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.schemas.plant import PlantConfig

PLANT_FILE = "plant.yaml"

#: Engineering lists by the schema they follow, at their conventional paths.
LIST_FILES = {
    "design_basis": "process/design-basis.yaml",
    "equipment": "equipment/equipment-list.yaml",
    "lines": "piping/line-list.yaml",
    "instruments": "control/instrument-list.yaml",
    "piping_items": "piping/special-items.yaml",
    "interlocks": "control/cause-effect.yaml",
    "loops": "control/loops.yaml",
    "sequences": "control/sequences.yaml",
    "checks": "checks/checks.yaml",
    "rates": "estimate/rates.yaml",
    "cost_basis": "estimate/cost-basis.yaml",
    "tea": "estimate/tea.yaml",
    "electrical": "electrical/electrical-list.yaml",
    "crane_chart": "layout/crane-chart.yaml",
    "lca": "lca/lca.yaml",
    "lca_factors": "lca/factors.yaml",
}

#: Layout files (site plan, buildings, equipment placement, steel structures, zones, routing
#: intent, pipe specs, cable tray rules, HVAC) by schema, at their paths.
LAYOUT_FILES = {
    "site_plan": "layout/site-plan.yaml",
    "building": "layout/building.yaml",
    "placement": "layout/equipment-placement.yaml",
    "structures": "layout/structures.yaml",
    "zones": "layout/zones.yaml",
    "routing": "piping/routing.yaml",
    "pipe_specs": "piping/pipe-specs.yaml",
    "trays": "electrical/tray-rules.yaml",
    "hvac": "layout/hvac.yaml",
}
#: Layout files that alone make no layout (piping, electrical and HVAC data the layout reads
#: when there is one).
LAYOUT_SUPPORT = ("routing", "pipe_specs", "trays", "hvac")

#: The 3D plant model ``cheme layout build`` generates from the layout files, the lists and
#: the P&IDs (kind ``layout_model``); never edited by hand.
LAYOUT_MODEL_FILE = "layout/plant-model.yaml"


class NotAPlantRepository(Exception):
    """No ``plant.yaml`` in the directory or any directory above it."""


def installed_version() -> tuple[int, ...]:
    """The running cheme-as-code's release numbers, e.g. (0, 7, 0); (0,) when unknown."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        text = version("cheme-as-code")
    except PackageNotFoundError:
        return (0,)
    found = re.match(r"\d+(\.\d+)*", text)
    return tuple(int(n) for n in found.group(0).split(".")) if found else (0,)


def schema_hint(hint: str, error: dict) -> str:
    """*hint* for a schema error, with, for an unknown field (``extra_forbidden``), that it may
    be one a newer cheme-as-code reads: a repository written with a newer release (a field it
    added) fails an older install with schema errors otherwise left unexplained."""
    if error.get("type") != "extra_forbidden":
        return hint
    have = ".".join(map(str, installed_version()))
    return (
        f"{hint}; an unknown field may be one a newer cheme-as-code reads (this is {have}): "
        "`uv tool upgrade cheme-as-code`, and raise `requires:` in plant.yaml"
    )


#: The guide for plant repositories written for the package under its old name, plantcode.
RENAME_GUIDE = "docs/framework/rename.md of cheme-as-code"


def requirement_problem(root: Path) -> str | None:
    """Why the running cheme-as-code cannot work with ``plant.yaml``'s
    ``requires: cheme-as-code>=X.Y`` (too old), or None. Read before the schema, so an older
    cheme-as-code says so instead of a schema error. ``requires: plantcode>=X.Y``, the name
    before 0.7.0, is refused with the new spelling."""
    try:
        data = yaml.safe_load((root / PLANT_FILE).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    requires = str(data.get("requires", "") or "").strip()
    if re.fullmatch(r"plantcode\s*>=\s*\d+(?:\.\d+)*", requires):
        return (
            f"`requires: {requires}` names the package by its old name: plantcode was renamed "
            f"cheme-as-code in 0.7.0; write `requires: cheme-as-code>=0.7`"
        )
    wanted = re.fullmatch(r"cheme-as-code\s*>=\s*(\d+(?:\.\d+)*)", requires)
    if wanted is None:
        return None
    need = tuple(int(n) for n in wanted.group(1).split("."))
    have = installed_version()
    if have >= need:
        return None
    return (
        f"this repository needs cheme-as-code >= {wanted.group(1)}, you have "
        f"{'.'.join(map(str, have))}: upgrade with `uv tool upgrade cheme-as-code`"
    )


def check_requirement(root: Path) -> None:
    """Print ``cheme.version-required`` and exit 2 when the running cheme-as-code cannot work
    with the repository at *root* (see :func:`requirement_problem`)."""
    problem = requirement_problem(root)
    if problem is None:
        return
    import typer

    from chemeascode.foundation.findings import Finding

    text = (root / PLANT_FILE).read_text(encoding="utf-8")
    line = next(
        (i for i, row in enumerate(text.splitlines(), 1) if row.startswith("requires:")), None
    )
    renamed = "old name" in problem
    finding = Finding(
        PLANT_FILE,
        "error",
        "cheme.version-required",
        problem,
        line=line,
        hint=(
            f"migrate the repository to the new names ({RENAME_GUIDE}); nothing was checked"
            if renamed
            else "the repository's files follow a newer schema; nothing was checked"
        ),
    )
    typer.echo(finding.format(), err=True)
    raise typer.Exit(2)


@dataclass(frozen=True)
class Workspace:
    """A plant repository, rooted at the directory holding ``plant.yaml``."""

    root: Path

    @classmethod
    def find(cls, start: Path | None = None) -> Workspace:
        """The repository containing *start* (default: the working directory)."""
        here = (start or Path.cwd()).resolve()
        for directory in (here, *here.parents):
            if (directory / PLANT_FILE).is_file():
                return cls(directory)
        raise NotAPlantRepository(f"No {PLANT_FILE} in {here} or any directory above it.")

    def config(self) -> PlantConfig:
        """``plant.yaml``, validated."""
        data = yaml.safe_load((self.root / PLANT_FILE).read_text(encoding="utf-8")) or {}
        return PlantConfig.model_validate(data)

    def contains(self, path: Path) -> bool:
        """Whether *path* (symlinks followed) lies inside the repository and outside ``.git``."""
        try:
            relative = path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        return not any(part.lower() == ".git" for part in relative.parts)

    def sheet_path(self, file: str) -> Path | None:
        """A sheet ``file`` of ``plant.yaml`` as a path; ``None`` when outside the repository."""
        if not file or Path(file).is_absolute() or ".." in Path(file.replace("\\", "/")).parts:
            return None
        path = self.root / file
        return path if self.contains(path) else None

    def outside_sheets(self) -> list[str]:
        """Sheet files ``plant.yaml`` lists that point outside the repository (never read)."""
        return [s.file for s in self.config().sheets if self.sheet_path(s.file) is None]

    def pid_files(self) -> list[Path]:
        """Every P&ID sheet: those ``plant.yaml`` lists (``kind: pid``), else every
        ``pid/*.xml``. Process sheets (``kind: bfd | pfd``) are not P&IDs: see
        :meth:`process_files`.

        A listed file outside the repository (absolute, ``..``, a symlink out) is left out; see
        :meth:`outside_sheets`.
        """
        sheets = self.config().sheets
        if any(sheet.kind == "pid" for sheet in sheets):
            paths = (self.sheet_path(sheet.file) for sheet in sheets if sheet.kind == "pid")
            return [path for path in paths if path is not None]
        return sorted(p for p in (self.root / "pid").glob("*.xml") if self.contains(p))

    def process_files(self) -> list[Path]:
        """The generated process sheets ``plant.yaml`` lists (``kind: bfd | pfd``)."""
        paths = (self.sheet_path(s.file) for s in self.config().sheets if s.kind != "pid")
        return [path for path in paths if path is not None]

    def sheet_files(self) -> list[Path]:
        """Every sheet, P&IDs and process sheets, for commands that treat them alike."""
        return [*self.pid_files(), *self.process_files()]

    def list_file(self, kind: str) -> Path | None:
        """The engineering list of *kind* (a key of :data:`LIST_FILES`), when the repo has one."""
        path = self.root / LIST_FILES[kind]
        return path if path.is_file() else None

    def parsed_lists(
        self, kinds: tuple[str, ...] = ("equipment", "lines", "instruments", "piping_items")
    ) -> dict[str, Any]:
        """The engineering lists of *kinds* that exist and follow their schema, parsed; a list
        that does not parse is left out (``cheme validate`` reports it)."""
        from pydantic import ValidationError

        from chemeascode.schemas import LIST_SCHEMAS

        parsed = {}
        for kind in kinds:
            path = self.list_file(kind)
            if path is None:
                continue
            try:
                parsed[kind] = LIST_SCHEMAS[kind].model_validate(
                    yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                )
            except (ValidationError, yaml.YAMLError, OSError, UnicodeDecodeError):
                continue
        return parsed

    def layout_file(self, kind: str) -> Path | None:
        """The layout file of *kind* (a key of :data:`LAYOUT_FILES`), when the repo has one."""
        path = self.root / LAYOUT_FILES[kind]
        return path if path.is_file() and self.contains(path) else None

    def layout_model_file(self) -> Path | None:
        """The generated :data:`LAYOUT_MODEL_FILE`, when the repo has one."""
        path = self.root / LAYOUT_MODEL_FILE
        return path if path.is_file() and self.contains(path) else None

    def build_dir(self) -> Path:
        """Where generated files go (git-ignored)."""
        path = self.root / "build"
        path.mkdir(exist_ok=True)
        return path

    def relative(self, path: Path) -> str:
        """*path* relative to the root, for messages."""
        resolved = path.resolve()
        for root in (self.root, self.root.resolve()):
            try:
                return resolved.relative_to(root).as_posix()
            except ValueError:
                continue
        return str(path)
