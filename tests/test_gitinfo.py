"""foundation.gitinfo fails closed: a git error is "cannot tell", never "nothing changed", and
repository paths reach git as literal pathspecs."""

import os
import subprocess
from pathlib import Path

import pytest

from chemeascode.foundation import gitinfo
from chemeascode.foundation.provenance import source_revision
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.status import plant_status, status_lines
from tests.conftest import git


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")
    (tmp_path / "notes").mkdir()
    for name in ("ab.md", "a[b].md", "a.md"):
        (tmp_path / "notes" / name).write_text("one\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "one")
    return tmp_path


def corrupt_index(root: Path) -> None:
    """Make ``git status`` (and ``git diff``) exit 128 while HEAD still resolves."""
    (root / ".git" / "index").write_text("garbage\n")


def test_dirty_paths_is_unknown_when_git_fails(repo: Path, tmp_path_factory):
    assert gitinfo.dirty_paths(repo) == []
    corrupt_index(repo)
    assert gitinfo.head(repo) is not None  # still a repository with a commit
    assert gitinfo.dirty_paths(repo) is None
    assert gitinfo.repo_state(repo).dirty is None
    outside = tmp_path_factory.mktemp("outside")
    assert gitinfo.dirty_paths(outside) is None  # not a repository: cannot tell either


def test_dirty_paths_is_unknown_when_the_prefix_query_fails(repo: Path, monkeypatch):
    real = gitinfo.git

    def failing_prefix(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if "--show-prefix" in args:
            return subprocess.CompletedProcess(["git", *args], 128, "", "fatal")
        return real(root, *args)

    monkeypatch.setattr(gitinfo, "git", failing_prefix)
    assert gitinfo.dirty_paths(repo) is None


def test_dirty_paths_keeps_glob_characters(repo: Path):
    (repo / "notes" / "a[b].md").write_text("two\n")
    (repo / "notes" / "new [draft].md").write_text("new\n")
    assert sorted(gitinfo.dirty_paths(repo)) == ["notes/a[b].md", "notes/new [draft].md"]


def test_changed_since_takes_paths_literally(repo: Path):
    start = gitinfo.head(repo)
    (repo / "notes" / "ab.md").write_text("two\n")
    (repo / "notes" / "ac.md").write_text("untracked\n")
    # as globs, a[b].md, a?.md and a*.md would match the changed ab.md (and the new ac.md)
    for pattern in ("notes/a[b].md", "notes/a?.md", "notes/a*.md", "notes/a[bc].md"):
        assert gitinfo.changed_since(repo, start, [pattern]) == [], pattern
    assert gitinfo.changed_since(repo, start, ["notes/ab.md"]) == ["notes/ab.md"]
    (repo / "notes" / "a[b].md").write_text("two\n")
    assert gitinfo.changed_since(repo, start, ["notes/a[b].md"]) == ["notes/a[b].md"]
    assert gitinfo.changed_since(repo, start, ["notes"]) == [
        "notes/a[b].md",
        "notes/ab.md",
        "notes/ac.md",
    ]
    corrupt_index(repo)
    assert gitinfo.changed_since(repo, start, ["notes"]) is None


def test_first_added_takes_the_path_literally(tmp_path: Path):
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "user.name", "T")

    def add(name: str, epoch: int) -> None:
        (tmp_path / name).write_text("x\n")
        git(tmp_path, "add", name)
        date = {"GIT_COMMITTER_DATE": f"{epoch} +0000", "GIT_AUTHOR_DATE": f"{epoch} +0000"}
        subprocess.run(
            ["git", "commit", "-qm", name],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            env={**os.environ, **date},
        )

    add("ab.md", 1_600_000_000)
    add("a[b].md", 1_700_000_000)
    # as a glob, a[b].md also names ab.md, which was added earlier
    assert gitinfo.first_added(tmp_path, "a[b].md") == 1_700_000_000
    assert gitinfo.first_added(tmp_path, "ab.md") == 1_600_000_000


def test_source_revision_counts_every_input_dirty_when_git_cannot_tell(repo: Path):
    assert source_revision(repo, ["notes/a.md"]).committed
    corrupt_index(repo)
    found = source_revision(repo, ["notes/a.md", "notes/ab.md"])
    assert found.dirty == ("notes/a.md", "notes/ab.md") and not found.committed


def test_status_reports_unknown_uncommitted_changes(plant: Path, monkeypatch):
    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    monkeypatch.setattr(gitinfo, "dirty_paths", lambda root: None)
    data = plant_status(Workspace(plant), run_gates=False)
    assert data["git"]["dirty"] is None
    (line,) = [line for line in status_lines(data) if line.startswith("git:")]
    assert "uncommitted changes unknown" in line and "clean" not in line


def test_a_hazop_directory_revision_needs_git_to_tell(plant: Path):
    from chemeascode.domains.safety.hazop import current_revision

    git(plant, "add", "-A")
    git(plant, "commit", "-qm", "plant")
    workspace = Workspace(plant)
    assert current_revision(workspace, "pid") == gitinfo.head(plant)
    corrupt_index(plant)
    with pytest.raises(ValueError, match="cannot tell whether it has uncommitted changes"):
        current_revision(workspace, "pid")
