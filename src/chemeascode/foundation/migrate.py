"""``cheme migrate``: bring the YAML inputs of a plant repository to the schema versions this
cheme-as-code reads.

Every file kind declares ``schema: cheme/<kind>/vN`` (docs/framework/contract.md, Versioning). A
file without the field is version ``v0``; the kinds of :func:`inputs` read it as ``v1``, the
version they all are at. :data:`MIGRATIONS` maps ``(kind, from, to)`` to a transform of the
file's text; ``cheme migrate`` chains them from a file's version to the reader's.

**Policy.** A breaking change to a kind bumps its ``N``, registers the ``(kind, vN-1, vN)``
transform here, reads both versions for one minor release, and is recorded in the changelog.
Adding an optional field is not a breaking change and needs no transform.

Two transforms edit the text, not a YAML round trip, so comments, key order and spacing stay
byte for byte: ``v0`` to ``v1`` (:func:`add_schema`) inserts the field as the first key, and the
LCI dataset's ``v1`` to ``v2`` (:func:`lci_dataset_v2`) rewrites its
``schema:`` line (v1 declared the LCA files' id, ``cheme/lca/v1``; every field v2 adds is optional).
The datasets in ``lca/datasets/*.yaml`` are inputs (hand-written, copied, estimated, and the
generated datasets of other design cases, which ``cheme assess lca --write --case`` rewrites
too); the generated ``lca/dataset.yaml``, the layout model, ``checks/status.json`` and review
records are not and are left alone. The process, simulation, reactions, catalysts, LCA and
kinetic-data files already require their ``schema:``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.workspace import LAYOUT_FILES, LIST_FILES, PLANT_FILE, Workspace

#: A file's text in, the text at the next version out (``kind`` is the file's kind).
Transform = Callable[[str, str], str]

#: A file without ``schema:``.
UNVERSIONED = "v0"


class MigrationRefused(Exception):
    """A transform cannot rewrite the file (its text is not what the transform expects)."""


def _version(schema_id: str) -> str:
    """``v1`` of ``cheme/<kind>/v1``."""
    return schema_id.rsplit("/", 1)[-1]


def _mapping(text: str) -> dict[str, Any]:
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MigrationRefused("the file is not a YAML mapping")
    return data


def add_schema(text: str, kind: str) -> str:
    """*text* with ``schema: cheme/<kind>/v1`` as its first key, before the first line that is
    not blank, a comment, a directive or the ``---`` document start. Nothing else changes."""
    schema_id = f"cheme/{kind}/v1"
    before = _mapping(text)
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    at = len(lines)
    for i, line in enumerate(lines):
        bare = line.strip()
        if not bare or bare.startswith(("#", "%")) or re.fullmatch(r"---\s*(#.*)?", bare):
            continue
        at = i
        break
    if at == len(lines) and lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += newline
    lines.insert(at, f"schema: {schema_id}{newline}")
    migrated = "".join(lines)
    try:
        after = _mapping(migrated)
    except yaml.YAMLError as failure:
        raise MigrationRefused("the first key is not a top-level block key") from failure
    if after != {"schema": schema_id, **before}:
        raise MigrationRefused("the first key is not a top-level block key")
    return migrated


#: The ids a kind declared before it had its own: ``(kind, id) -> version``. A v1 LCI dataset
#: declared the LCA files' id.
LEGACY_IDS = {("lci_dataset", "cheme/lca/v1"): "v1"}
#: Where the LCI datasets used as inputs are: hand-written, copied, estimated, and the design
#: cases' (``cheme assess lca --write --case``); the generated ``lca/dataset.yaml`` is rewritten
#: by ``cheme assess lca --write``.
DATASETS_GLOB = "lca/datasets/*.yaml"


def lci_dataset_v2(text: str, kind: str) -> str:
    """*text* of a v1 LCI dataset with ``schema: cheme/lci_dataset/v2``; nothing else changes."""
    before = _mapping(text)
    if before.get("schema") != "cheme/lca/v1" or before.get("kind") != "lci_dataset":
        raise MigrationRefused("not a v1 LCI dataset (schema: cheme/lca/v1, kind: lci_dataset)")
    pattern = re.compile(r"^(?P<key>schema:[ \t]*)(?P<q>[\"']?)cheme/lca/v1(?P=q)", re.MULTILINE)
    migrated, count = pattern.subn(r"\g<key>cheme/lci_dataset/v2", text, count=1)
    if count != 1 or _mapping(migrated) != {**before, "schema": "cheme/lci_dataset/v2"}:
        raise MigrationRefused("the schema: line is not a top-level block key")
    return migrated


#: The version this cheme-as-code reads of each kind ``cheme migrate`` looks at: the kinds whose
#: ``schema:`` is optional (``schema_base.optional_schema``), by the name ``cheme schema`` lists,
#: and the hand-written LCI datasets. The LCA and TEA files require theirs (``cheme/lca/v1``,
#: ``cheme/tea/v1``).
CURRENT = {
    **{
        kind: "v1"
        for kind in ("plant", *LIST_FILES, *LAYOUT_FILES, "datasheet")
        if kind not in ("lca", "lca_factors", "tea")
    },
    "lci_dataset": "v2",
}

#: The transforms by ``(kind, from version, to version)``.
MIGRATIONS: dict[tuple[str, str, str], Transform] = {
    **{(kind, UNVERSIONED, "v1"): add_schema for kind, v in CURRENT.items() if v == "v1"},
    ("lci_dataset", "v1", "v2"): lci_dataset_v2,
}


def inputs(workspace: Workspace, datasheets: Iterable[Path] = ()) -> list[tuple[str, Path]]:
    """The YAML inputs of *workspace* ``cheme migrate`` looks at, as ``(kind, path)``:
    ``plant.yaml``, the lists, the layout files, *datasheets* (the equipment domain finds
    them) and the LCI datasets of ``lca/datasets/``."""
    found = [("plant", workspace.root / PLANT_FILE)]
    for kind, file in {**LIST_FILES, **LAYOUT_FILES}.items():
        if kind in CURRENT:
            found.append((kind, workspace.root / file))
    found += [("datasheet", path) for path in datasheets]
    found += [("lci_dataset", path) for path in sorted(workspace.root.glob(DATASETS_GLOB))]
    return [(kind, path) for kind, path in found if path.is_file() and workspace.contains(path)]


@dataclass
class Migration:
    """What ``cheme migrate`` does (or would do) to one file."""

    path: Path
    kind: str
    found: str
    target: str
    #: The migrated text; None when the file cannot be migrated (see ``problem``).
    text: str | None = None
    problem: str = ""


def plan(kind: str, path: Path, target: str) -> Migration | None:
    """The migration of *path* (of *kind*) to version *target*; None when it is there."""
    try:
        text = path.read_bytes().decode("utf-8")
        data = _mapping(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, MigrationRefused) as failure:
        return Migration(path, kind, "?", target, problem=f"not read: {failure}")
    found = data.get("schema")
    if (kind, found) in LEGACY_IDS:
        version = LEGACY_IDS[(kind, found)]
    elif found is None:
        version = UNVERSIONED
    elif isinstance(found, str) and re.fullmatch(rf"cheme/{re.escape(kind)}/v\d+", found):
        version = _version(found)
    else:
        return Migration(path, kind, str(found), target, problem=f"unknown schema {found!r}")
    if version == target:
        return None
    migration = Migration(path, kind, version, target)
    current = version
    while current != target:
        following = f"v{int(current[1:]) + 1}"
        transform = MIGRATIONS.get((kind, current, following))
        if transform is None:
            migration.problem = f"no migration of {kind} from {current} to {target}"
            return migration
        try:
            text = transform(text, kind)
        except MigrationRefused as refusal:
            migration.problem = f"{current} to {following}: {refusal}"
            return migration
        current = following
    migration.text = text
    return migration


def migrate(
    workspace: Workspace, datasheets: Iterable[Path] = (), write: bool = False
) -> list[Migration]:
    """The migrations the inputs of *workspace* need; with *write*, applied."""
    migrations = []
    for kind, path in inputs(workspace, datasheets):
        migration = plan(kind, path, CURRENT[kind])
        if migration is None:
            continue
        if write and migration.text is not None:
            path.write_bytes(migration.text.encode("utf-8"))
        migrations.append(migration)
    return migrations
