"""Portable project-relative paths used in executable recipes."""

from pathlib import Path, PurePosixPath, PureWindowsPath


def project_name(name: str) -> str:
    windows = PureWindowsPath(name)
    if (
        not name
        or name == "."
        or "\\" in name
        or ":" in name
        or "\0" in name
        or PurePosixPath(name).is_absolute()
        or windows.drive
        or windows.root
        or any(part.casefold() in {"", ".", "..", ".git"} for part in name.split("/"))
    ):
        raise ValueError(f"Expected a project-relative path: {name}")
    return name


def local_path(root: Path, name: str) -> Path:
    target = (root / project_name(name)).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"Path leaves the process project: {name}")
    if any(part.casefold() == ".git" for part in target.relative_to(root.resolve()).parts):
        raise ValueError(f"Path enters Git metadata: {name}")
    return target
