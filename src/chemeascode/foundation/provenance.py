"""Where a result came from, and whether its sources have changed since.

The convention of docs/framework/architecture.md ("Identity, relationships, provenance"), kept
small and built on what plant repositories already record:

- an artifact is identified by its path from the repository root (``pid/P-03.xml``);
- a source revision is a git commit sha (review ``reviewed_commit``, sign-off ``commit``) or a
  content fingerprint ``sha256:<hex>`` of one file (:func:`file_fingerprint`); generated sheets
  keep their own fingerprints in the ``cheme-process`` comment;
- a value a tool calculated carries the 16-hex :func:`value_fingerprint` of its inputs, and the
  tool's name at the start of its ``source`` (:func:`written_by`);
- a typed relationship is one of :data:`RELATIONS`, recorded as an optional ``basis:`` entry
  ``{path, revision, relation}`` (:class:`chemeascode.foundation.schemas.reviews.Basis`) on the
  artifacts that need it, starting with review records.

A result computed from files carries a :class:`SourceRevision`, so whoever applies it later can
check that it still describes the files it was computed from. :func:`changed_since` is the one
comparison the change-impact check (:mod:`chemeascode.project.impact`) builds on; a review's
scope is compared by :func:`content_changes`, which does not count a file whose only change is
a digest (a regenerated output with a new source fingerprint) as changed. Nothing here
decides that an artifact is wrong: a changed source only means its dependants need review.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, get_args

from chemeascode.foundation import gitinfo
from chemeascode.foundation.schemas.reviews import Basis, Relation

__all__ = [
    "DIGEST",
    "FINGERPRINT_PREFIX",
    "NOT_INPUTS",
    "RELATIONS",
    "Basis",
    "Relation",
    "VALUE_FINGERPRINT_LENGTH",
    "SourceRevision",
    "changed_since",
    "content_changes",
    "content_fingerprint",
    "digest_only",
    "file_fingerprint",
    "source_revision",
    "value_fingerprint",
    "without_digests",
    "written_by",
]

#: The typed relationships an artifact can record to its sources.
RELATIONS: tuple[str, ...] = get_args(Relation)
#: How a content fingerprint is written where a revision is expected.
FINGERPRINT_PREFIX = "sha256:"
_HEX = re.compile(r"^[0-9a-f]{64}$")
#: A digest a generator writes as provenance into its output: a sha256 (64 hex digits, with or
#: without ``sha256:``) or a full git commit id (40). Shorter hex runs (value fingerprints,
#: abbreviated commits) are content: :func:`digest_only` does not ignore them.
DIGEST = re.compile(rb"(?<![0-9A-Za-z])(?:sha256:)?(?:[0-9a-f]{64}|[0-9a-f]{40})(?![0-9A-Za-z])")
#: Hex digits of a :func:`value_fingerprint`.
VALUE_FINGERPRINT_LENGTH = 16
#: The fields of a value that describe it rather than state it: no :func:`value_fingerprint`
#: of a value calculated from it includes them, so adding or changing one marks nothing stale.
NOT_INPUTS = frozenset({"provenance", "source", "fingerprint", "uncertainty", "origin"})


def value_fingerprint(data: Any) -> str:
    """The input fingerprint a calculated value carries (``fingerprint:``): the first 16 hex
    digits of the sha256 of *data* (JSON-serialisable) as JSON with sorted keys. Values in plant
    repositories carry it already: the format is fixed."""
    digest = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    return digest[:VALUE_FINGERPRINT_LENGTH]


def written_by(value: Any, tool_source: str) -> bool:
    """Whether *value* was written by the tool whose sources start with *tool_source* (and so
    that tool may rewrite it): its ``source`` starts with *tool_source* and its ``provenance``
    is ``calculated``. *value* is a parsed value (a process ``Quantity``) or a mapping as read
    from YAML; a mapping without ``provenance`` (a datasheet entry) is judged by its source
    alone. None and plain numbers or texts are never written by a tool."""
    if isinstance(value, Mapping):
        provenance, source = value.get("provenance", "calculated"), value.get("source")
    else:
        provenance, source = getattr(value, "provenance", None), getattr(value, "source", None)
    return provenance == "calculated" and str(source or "").startswith(tool_source)


def content_fingerprint(data: bytes) -> str:
    """``sha256:<hex>`` of *data*, line endings normalised to ``\\n``."""
    return FINGERPRINT_PREFIX + hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def file_fingerprint(path: Path) -> str:
    """``sha256:<hex>`` of the bytes of *path*, line endings normalised to ``\\n``."""
    return content_fingerprint(path.read_bytes())


@dataclass(frozen=True)
class SourceRevision:
    """The state of the input files of a result when it was computed."""

    #: ``HEAD`` of the git repository holding the root; None outside git or before a commit.
    commit: str | None
    #: The input files with changes not in ``commit`` (uncommitted or untracked).
    dirty: tuple[str, ...] = ()
    #: :func:`file_fingerprint` of each input file that exists, by its path from the root.
    fingerprints: dict[str, str] = field(default_factory=dict)

    @property
    def committed(self) -> bool:
        """True when ``commit`` alone identifies the inputs."""
        return self.commit is not None and not self.dirty

    def as_dict(self) -> dict[str, Any]:
        return {
            "commit": self.commit,
            "dirty": list(self.dirty),
            "fingerprints": dict(self.fingerprints),
        }


def source_revision(root: Path, paths: Iterable[str]) -> SourceRevision:
    """The :class:`SourceRevision` of the files *paths* (from *root*) as they are now. When git
    cannot tell which files are uncommitted, every input counts as dirty (never committed)."""
    paths = sorted(set(paths))
    dirty: set[str] = set()
    if paths:
        found = gitinfo.dirty_paths(root)
        if found is not None:
            dirty = set(found)
        elif gitinfo.is_repo(root):
            dirty = set(paths)
    return SourceRevision(
        commit=gitinfo.head(root),
        dirty=tuple(p for p in paths if p in dirty),
        fingerprints={p: file_fingerprint(root / p) for p in paths if (root / p).is_file()},
    )


def changed_since(root: Path, path: str, revision: str) -> list[str] | None:
    """The files under *path* that changed since *revision*: a commit (compared with the working
    tree, so uncommitted changes count) or a ``sha256:`` fingerprint of the file *path*.

    None when that cannot be told: the commit is unknown here, git fails, or the fingerprint is
    malformed.
    A file that no longer exists has changed."""
    if revision.startswith(FINGERPRINT_PREFIX):
        if not _HEX.match(revision[len(FINGERPRINT_PREFIX) :]):
            return None
        target = root / path
        if not target.is_file():
            return [path]
        return [] if file_fingerprint(target) == revision else [path]
    commit = gitinfo.resolve(root, revision)
    if commit is None:
        return None
    return gitinfo.changed_since(root, commit, [path])


def without_digests(data: bytes) -> bytes:
    """*data* with line endings normalised to ``\\n`` and every :data:`DIGEST` replaced by
    ``<digest>``: what :func:`digest_only` compares."""
    return DIGEST.sub(b"<digest>", data.replace(b"\r\n", b"\n"))


def digest_only(root: Path, commit: str, path: str) -> bool:
    """Whether the file *path* (from *root*) differs from its version at *commit* in nothing but
    digests (:data:`DIGEST`): a regenerated output whose only change is the fingerprint of its
    sources or of the model it was made from. False when the file was added or deleted since, or
    git cannot tell."""
    target = root / path
    if not target.is_file():
        return False
    old = gitinfo.show(root, commit, path)
    return old is not None and without_digests(old) == without_digests(target.read_bytes())


def content_changes(root: Path, commit: str, paths: list[str]) -> list[str] | None:
    """:func:`gitinfo.changed_since` without the files whose change is :func:`digest_only`: the
    files under *paths* whose content changed since *commit*; None when git cannot tell."""
    changed = gitinfo.changed_since(root, commit, paths)
    if changed is None:
        return None
    return [path for path in changed if not digest_only(root, commit, path)]
