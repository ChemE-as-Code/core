"""Execute the local A2/O worker in its numerical environment, without importing QSDsan."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORKER = "wwtp_a2o.interfaces.cli.cheme"


def local_path(root: Path, name: str) -> Path:
    """A project-relative path, confined even when the file is a symlink."""
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or any(p.lower() == ".git" for p in path.parts):
        raise ValueError(f"Expected a project-relative path: {name}")
    target = (root / path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the process project: {name}")
    return target


def recipe_path(path: str, input_path: str) -> bool:
    """Source files staged for --check and fingerprinted by the command and viewer."""
    p = Path(path)
    return (
        path in {input_path, "requirements.lock.txt", "pyproject.toml", "plant.yaml"}
        or (len(p.parts) == 1 and p.suffix == ".py")
        or (p.parts[0] == "wwtp_a2o" and p.suffix in {".py", ".html"})
        or (p.parts[0] == "licenses" and p.suffix == ".txt")
        or path
        in {
            "process/flowsheet.yaml",
            "process/materials.yaml",
            "process/simulation.yaml",
            "process/case-inputs.json",
        }
    )


def recipe_files(root: Path, input_path: str) -> list[str]:
    candidates = [*root.glob("*"), *root.joinpath("process").glob("*")]
    for folder in ("wwtp_a2o", "licenses"):
        candidates.extend(root.joinpath(folder).rglob("*"))
    candidates.append(local_path(root, input_path))
    names = {p.relative_to(root).as_posix() for p in candidates if p.is_file()}
    selected = sorted(p for p in names if recipe_path(p, input_path))
    for name in selected:
        local_path(root, name)
    return selected


@dataclass
class WorkerResult:
    payload: dict[str, Any]
    stdout: str
    stderr: str
    returncode: int


def execute(
    root: Path,
    *,
    environment: str,
    input_path: str,
    case: str,
    timeout: float,
    write: bool,
) -> WorkerResult:
    """Launch only the supported worker. --check operates on a disposable project copy."""
    python = local_path(root, environment) / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    if not python.is_file():
        raise ValueError(f"QSDsan environment is missing: {python}; see the process README")
    local_path(root, input_path)
    if not (root / "wwtp_a2o/interfaces/cli/cheme.py").is_file():
        raise ValueError("This project does not contain the wwtp-a2o ChemE worker")
    with tempfile.TemporaryDirectory(prefix="cheme-qsdsan-") as temporary:
        temp = Path(temporary)
        target = root
        if not write:
            # Three parent levels also preserve the existing example's repository layout.
            target = temp / "library/processes/wwtp-a2o"
            target.mkdir(parents=True)
            for name in recipe_files(root, input_path):
                dest = target / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(local_path(root, name), dest)
        response = temp / "response.json"
        env = os.environ.copy()
        env.update(
            PYTHONUTF8="1",
            PYTHONDONTWRITEBYTECODE="1",
            OPENBLAS_NUM_THREADS="1",
            OMP_NUM_THREADS="1",
            CHEME_CORE_PYTHON=sys.executable,
        )
        command = [
            str(python),
            "-m",
            WORKER,
            "--root",
            str(target),
            "--input",
            input_path,
            "--case",
            case,
            "--response",
            str(response),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=target,
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as failure:
            payload = json.loads(response.read_text(encoding="utf-8")) if response.exists() else {}
            raise ValueError(
                f"QSDsan worker exceeded {timeout:g} seconds; "
                f"evidence: {payload.get('run', 'no run created')}. No result was accepted."
            ) from failure
        if not response.is_file():
            raise ValueError("QSDsan worker produced no response: " + completed.stderr[-2000:])
        payload = json.loads(response.read_text(encoding="utf-8"))
        return WorkerResult(payload, completed.stdout, completed.stderr, completed.returncode)
