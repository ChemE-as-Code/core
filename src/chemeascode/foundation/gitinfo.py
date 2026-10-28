"""Read-only git queries for gates, sign-off and status. Git runs with argument lists only;
repository paths go to git as literal pathspecs (``--literal-pathspecs``: ``*``, ``?`` and ``[``
in a name match only themselves) and come back NUL-separated."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """``git *args`` at *root*; never raises for a git failure (see ``returncode``)."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError as failure:  # git missing
        return subprocess.CompletedProcess(["git", *args], 127, "", str(failure))


def _out(root: Path, *args: str) -> str | None:
    result = git(root, *args)
    return result.stdout.strip() if result.returncode == 0 else None


def is_repo(root: Path) -> bool:
    return _out(root, "rev-parse", "--is-inside-work-tree") == "true"


def head(root: Path) -> str | None:
    """The commit sha of HEAD (None: not a repository, or no commit yet)."""
    return _out(root, "rev-parse", "--verify", "--quiet", "HEAD")


def branch(root: Path) -> str | None:
    """The current branch (None when detached or not a repository)."""
    name = _out(root, "symbolic-ref", "--quiet", "--short", "HEAD")
    return name or None


def resolve(root: Path, rev: str) -> str | None:
    """The commit *rev* names, or None. *rev* may not start with ``-``."""
    if not rev or rev.startswith("-") or any(c in rev for c in "\0\r\n"):
        return None
    return _out(root, "rev-parse", "--verify", "--quiet", "--end-of-options", rev + "^{commit}")


def default_branch(root: Path) -> str | None:
    """The default branch: ``origin/HEAD``'s target, else ``main`` or ``master`` when it exists,
    else the current branch."""
    remote = _out(root, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if remote and "/" in remote:
        return remote.split("/", 1)[1]
    for name in ("main", "master"):
        if _out(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"):
            return name
    return branch(root)


def is_ancestor(root: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    return git(root, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def dirty_paths(root: Path) -> list[str] | None:
    """Paths with uncommitted changes or untracked (not ignored) files, relative to *root*;
    None when git cannot tell (not a repository, a git error). A caller treats None as "may
    have uncommitted changes", never as a clean tree."""
    result = git(
        root,
        "--literal-pathspecs",
        "status",
        "--porcelain",
        "-z",
        "--untracked-files=all",
        "--",
        ".",
    )
    if result.returncode != 0:
        return None
    found = []
    entries = result.stdout.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":  # a rename's source follows
            i += 1
        found.append(path)
    prefix = _out(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    return [p[len(prefix) :] if prefix and p.startswith(prefix) else p for p in found]


def changed_since(root: Path, commit: str, paths: list[str]) -> list[str] | None:
    """Files under *paths* that differ between *commit* and the working tree (committed or not),
    relative to *root*; None when git cannot tell (a git error: an unknown commit, a path
    outside the repository or not in repository-relative form). *paths* are relative to
    *root*."""
    if not paths:
        return []
    result = git(
        root, "--literal-pathspecs", "diff", "-z", "--name-only", "--relative", commit, "--", *paths
    )
    if result.returncode != 0:
        return None
    untracked = git(
        root,
        "--literal-pathspecs",
        "ls-files",
        "-z",
        "--others",
        "--exclude-standard",
        "--",
        *paths,
    )
    if untracked.returncode != 0:
        return None
    changed = {p for p in result.stdout.split("\0") + untracked.stdout.split("\0") if p}
    return sorted(changed)


def show(root: Path, commit: str, path: str) -> bytes | None:
    """The bytes of the file *path* (relative to *root*) at *commit*; None when it is not there
    or git fails."""
    try:
        result = subprocess.run(
            ["git", "show", f"{commit}:./{path}"],
            cwd=root,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except OSError:  # git missing
        return None
    return result.stdout if result.returncode == 0 else None


def user_name(root: Path) -> str | None:
    return _out(root, "config", "user.name") or None


def first_added(root: Path, path: str) -> int | None:
    """Commit time (epoch s) of the commit that added *path*, None when not committed."""
    out = _out(root, "--literal-pathspecs", "log", "--diff-filter=A", "--format=%ct", "--", path)
    lines = (out or "").split()
    return int(lines[-1]) if lines else None


@dataclass
class Divergence:
    ahead: int = 0
    behind: int = 0


def ahead_behind(root: Path, base: str, rev: str = "HEAD") -> Divergence | None:
    out = _out(root, "rev-list", "--left-right", "--count", f"{base}...{rev}")
    if not out:
        return None
    behind, ahead = (int(n) for n in out.split())
    return Divergence(ahead=ahead, behind=behind)


@dataclass
class RepoState:
    """Where the repository stands in git."""

    is_repo: bool = False
    head: str | None = None
    branch: str | None = None
    default_branch: str | None = None
    #: Uncommitted paths; None when git cannot tell (:func:`dirty_paths`).
    dirty: list[str] | None = field(default_factory=list)
    ahead: int | None = None
    behind: int | None = None


def repo_state(root: Path) -> RepoState:
    if not is_repo(root):
        return RepoState()
    state = RepoState(
        is_repo=True,
        head=head(root),
        branch=branch(root),
        default_branch=default_branch(root),
        dirty=dirty_paths(root),
    )
    if state.head and state.default_branch and state.default_branch != state.branch:
        found = ahead_behind(root, state.default_branch)
        if found is not None:
            state.ahead, state.behind = found.ahead, found.behind
    elif state.head:
        state.ahead, state.behind = 0, 0
    return state
