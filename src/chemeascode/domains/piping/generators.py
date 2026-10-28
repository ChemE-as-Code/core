"""Generated sheets: ``generator:`` in ``plant.yaml``, ``cheme regen`` and the drift check.

A sheet is in one of two states:

- **generated**: its ``plant.yaml`` entry names a ``generator`` (a script and the frame it starts
  from). The script is the source; the XML is its output and is not edited by hand. ``cheme
  regen`` rebuilds it: frame -> ``cheme run SCRIPT FILE`` -> ``fmt``.
- **hand-maintained**: no ``generator``. The XML is the source; a script in ``scripts/`` is
  provenance only.

``regen`` refuses to overwrite a generated sheet someone edited by hand: it compares the sheet
with what the generator, as committed at ``HEAD``, makes from the frame, and names the plant
items that differ. ``validate`` reports ``cheme.generated-sheet-drift`` when the declared
generator no longer reproduces the sheet, and an info note for each ``scripts/draft_<sheet>.py``
of a sheet that declares none.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any

import yaml
from lxml import etree

from chemeascode.foundation.schemas.plant import Generator
from chemeascode.foundation.schemas.plant import Sheet as SheetEntry
from chemeascode.foundation.workspace import PLANT_FILE, Workspace

#: How long one generator run may take, in seconds.
TIMEOUT = 600


class GeneratorError(Exception):
    """A generator cannot be run, or failed; the message says why."""


@dataclass
class Drift:
    """How a sheet differs from its generator's output: plant items by kind of change."""

    added: list[str] = field(default_factory=list)  # in the sheet, not in the output
    removed: list[str] = field(default_factory=list)  # in the output, not in the sheet
    modified: list[str] = field(default_factory=list)
    other: int = 0  # differences outside any plant item (title block, catalogue)

    def summary(self, limit: int = 8) -> str:
        parts = []
        for words, items in (
            ("only in the sheet", self.added),
            ("only in the generator output", self.removed),
            ("changed", self.modified),
        ):
            if items:
                shown = ", ".join(items[:limit]) + (", ..." if len(items) > limit else "")
                parts.append(f"{len(items)} item(s) {words} ({shown})")
        if self.other:
            parts.append(f"{self.other} other object(s) changed")
        return "; ".join(parts) or "the files differ in formatting only"


# -- plant.yaml ---------------------------------------------------------------------------------


def sheet_entries(workspace: Workspace) -> list[SheetEntry]:
    return list(workspace.config().sheets)


def find_entry(workspace: Workspace, key: str) -> SheetEntry:
    """The ``plant.yaml`` sheet named by *key*: its id (``P-04``) or its file (``pid/P-04.xml``)."""
    entries = sheet_entries(workspace)
    wanted = key.replace("\\", "/")
    for entry in entries:
        if entry.id == key or entry.file == wanted:
            return entry
    if Path(key).exists():
        relative = workspace.relative(Path(key))
        for entry in entries:
            if entry.file == relative:
                return entry
    known = ", ".join(e.id for e in entries) or "none (plant.yaml lists no sheets)"
    raise GeneratorError(f"{key}: no such sheet in {PLANT_FILE}; sheets: {known}")


def generated_entries(workspace: Workspace) -> list[SheetEntry]:
    """Sheets with a generator: a script (P&IDs) or the flowsheet (bfd/pfd sheets)."""
    return [e for e in sheet_entries(workspace) if e.generator is not None]


# -- running a generator ------------------------------------------------------------------------


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=check)


def frame_bytes(workspace: Workspace, entry: SheetEntry, root: Path | None = None) -> bytes:
    """The frame the generator of *entry* starts from: a file, else the sheet at a revision."""
    generator = entry.generator
    assert generator is not None
    base = root or workspace.root
    candidate = workspace.sheet_path(generator.frame)
    if candidate is not None and (base / generator.frame).is_file():
        return (base / generator.frame).read_bytes()
    if generator.frame.startswith("-") or not generator.frame.strip():
        raise GeneratorError(f"{entry.id}: generator frame {generator.frame!r} is not a revision")
    # ``rev:./path`` resolves against the working directory, so this also works when the plant
    # repository is a subdirectory of a larger git repository.
    shown = _git(workspace.root, "show", f"{generator.frame}:./{entry.file}", check=False)
    if shown.returncode != 0:
        raise GeneratorError(
            f"{entry.id}: generator frame {generator.frame!r} is neither a file in the repository "
            f"nor a git revision holding {entry.file}"
        )
    return shown.stdout


#: Directories never copied into the scratch copy a generator runs in (outside git).
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "build", ".ruff_cache"}


def _working_copy(root: Path, into: Path) -> None:
    """Copy the working tree of *root* into *into*: in git the tracked and untracked files that
    are not ignored, else every file outside build and tool directories."""
    listed = _git(
        root,
        "ls-files",
        "-z",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        ".",
        check=False,
    )
    if listed.returncode == 0:
        names = [n for n in listed.stdout.decode().split("\0") if n]
    else:
        names = [
            str(p.relative_to(root))
            for p in root.rglob("*")
            if p.is_file() and not _SKIP_DIRS & set(p.relative_to(root).parts[:-1])
        ]
    for name in names:
        source = root / name
        if not source.is_file():  # deleted in the working tree, or a submodule
            continue
        target = into / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def produce(workspace: Workspace, entry: SheetEntry, root: Path | None = None) -> bytes:
    """What the generator of *entry* makes from its frame, formatted.

    The script runs in a separate ``cheme run`` process, with the path of a scratch copy of
    the frame as its argument, in a scratch copy of the repository: the working tree (default)
    or the tree at *root*. Whatever else the script writes stays in that copy, so ``validate``
    and ``regen`` never change the working tree through it.
    """
    generator = entry.generator
    if generator is None:
        raise GeneratorError(f"{entry.id}: no generator in {PLANT_FILE}")
    if root is not None:
        return _produce_in(workspace, entry, root)
    with tempfile.TemporaryDirectory(prefix="cheme-copy-") as copy:
        _working_copy(workspace.root, Path(copy))
        return _produce_in(workspace, entry, Path(copy))


def _produce_in(workspace: Workspace, entry: SheetEntry, base: Path) -> bytes:
    from chemeascode.domains.piping.fmt import FormatRefused, format_bytes

    generator = entry.generator
    assert generator is not None
    script = base / generator.script
    if workspace.sheet_path(generator.script) is None or not script.is_file():
        raise GeneratorError(f"{entry.id}: generator script {generator.script} does not exist")
    frame = frame_bytes(workspace, entry, base)
    with tempfile.TemporaryDirectory(prefix="cheme-regen-") as scratch:
        out = Path(scratch) / Path(entry.file).name
        out.write_bytes(frame)
        command = [sys.executable, "-m", "chemeascode", "run", generator.script, str(out)]
        try:
            done = subprocess.run(
                command, cwd=base, capture_output=True, text=True, timeout=TIMEOUT, check=False
            )
        except subprocess.TimeoutExpired as failure:
            raise GeneratorError(
                f"{entry.id}: {generator.script} ran longer than {TIMEOUT} s"
            ) from failure
        if done.returncode != 0:
            tail = (done.stderr or done.stdout).strip().splitlines()[-3:]
            raise GeneratorError(
                f"{entry.id}: {generator.script} failed (exit {done.returncode})"
                + (": " + " / ".join(tail) if tail else "")
            )
        try:
            return format_bytes(out.read_bytes())[0]
        except FormatRefused as refusal:
            raise GeneratorError(
                f"{entry.id}: the output of {generator.script} cannot be formatted: {refusal}"
            ) from refusal


def _prefix(root: Path) -> str:
    """The path of *root* inside its git repository (``""`` at the top, else ``"plant/"``)."""
    done = _git(root, "rev-parse", "--show-prefix", check=False)
    return done.stdout.decode().strip() if done.returncode == 0 else ""


def _committed_tree(root: Path, into: Path) -> bool:
    """Extract the plant directory as committed at ``HEAD`` into *into*; False without one.

    Run in a subdirectory of the git repository, ``git archive`` holds that subdirectory only,
    with paths relative to it."""
    archive = _git(root, "archive", "--format=tar", "HEAD", check=False)
    if archive.returncode != 0:
        return False
    with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
        tar.extractall(into, filter="data")
    return True


def _clean_except(root: Path, file: str) -> bool:
    """Whether the working tree equals ``HEAD`` for every tracked file other than *file*."""
    done = _git(root, "status", "--porcelain", "--untracked-files=no", check=False)
    if done.returncode != 0:
        return False
    prefix = _prefix(root)  # porcelain paths are relative to the top of the git repository
    changed = [line[3:].strip() for line in done.stdout.decode().splitlines() if line.strip()]
    return all(path in (prefix + file, prefix + PLANT_FILE) for path in changed)


def previous_output(workspace: Workspace, entry: SheetEntry, output: bytes) -> bytes | None:
    """What the generator, as committed at ``HEAD``, makes; None when there is no commit.

    The declared generator (script path and frame) is the one in the working ``plant.yaml``, so
    declaring a generator for an existing sheet works before the declaration is committed.
    *output* is what the generator makes from the working tree: the same when nothing but the
    sheet and ``plant.yaml`` changed since ``HEAD``.
    """
    if _git(workspace.root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0:
        return None
    if _clean_except(workspace.root, entry.file):
        return output
    with tempfile.TemporaryDirectory(prefix="cheme-head-") as scratch:
        if not _committed_tree(workspace.root, Path(scratch)):
            return None
        return produce(workspace, entry, Path(scratch))


# -- comparing ----------------------------------------------------------------------------------


def _signatures(root: etree._Element) -> dict[str, str]:
    """Each identified object's own content (its identified children by id only), hashed."""
    found: dict[str, str] = {}

    def walk(element: etree._Element) -> str:
        parts = [
            str(element.tag),
            repr(sorted(element.attrib.items())),
            (element.text or "").strip(),
        ]
        for child in element:
            if not isinstance(child.tag, str):
                continue
            if child.tag == "Object" and child.get("id"):
                walk(child)
                parts.append(f"#{child.get('id')}")
            else:
                parts.append(walk(child))
        digest = hashlib.sha1("\x00".join(parts).encode()).hexdigest()
        if element.tag == "Object" and element.get("id"):
            found[element.get("id")] = digest
        return digest

    walk(root)
    return found


def drift(output: bytes, sheet: bytes) -> Drift:
    """How *sheet* differs from the generator *output*, by plant item (id and tag)."""
    from chemeascode.domains.piping.diffview import plant_items

    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=True)
    old, new = etree.fromstring(output, parser), etree.fromstring(sheet, parser)
    old_sig, new_sig = _signatures(old), _signatures(new)
    old_owner, old_info = plant_items(old)
    new_owner, new_info = plant_items(new)
    result = Drift()
    kinds: dict[str, set[str]] = {"added": set(), "removed": set(), "modified": set()}
    for object_id in sorted(set(old_sig) | set(new_sig)):
        if old_sig.get(object_id) == new_sig.get(object_id):
            continue
        item = new_owner.get(object_id) or old_owner.get(object_id)
        if item is None:
            result.other += 1
        elif item in old_sig and item in new_sig:
            kinds["modified"].add(item)
        else:
            kinds["added" if item in new_sig else "removed"].add(item)

    def name(item: str) -> str:
        info = new_info.get(item) or old_info.get(item) or {}
        return f"{item} [{info['tag']}]" if info.get("tag") else item

    result.added = [name(i) for i in sorted(kinds["added"])]
    result.removed = [name(i) for i in sorted(kinds["removed"])]
    result.modified = [name(i) for i in sorted(kinds["modified"])]
    return result


# -- regen --------------------------------------------------------------------------------------


def _is_frame(workspace: Workspace, entry: SheetEntry, current: bytes) -> bool:
    """Whether *current* is the generator's frame itself (nothing drawn yet, nothing to lose)."""
    from chemeascode.domains.piping.fmt import FormatRefused, format_bytes

    try:
        frame = frame_bytes(workspace, entry)
        return current in (frame, format_bytes(frame)[0])
    except (GeneratorError, FormatRefused):
        return False


@dataclass
class RegenResult:
    entry: SheetEntry
    status: str  # "written", "unchanged"
    lines: list[str] = field(default_factory=list)


class RegenRefused(GeneratorError):
    """The sheet was edited by hand since the generator last wrote it."""


def regenerate(workspace: Workspace, entry: SheetEntry, *, force: bool = False) -> RegenResult:
    """Rebuild *entry* from its generator; refuse over hand edits unless *force*."""
    if entry.kind != "pid":  # a BFD/PFD: built from process/*.yaml
        from chemeascode.domains.process.sheets import build

        built = build(workspace, [entry.id], force=force)
        if built.failed:
            raise GeneratorError("; ".join(built.lines))
        return RegenResult(entry, "written", built.lines)
    if not isinstance(entry.generator, Generator):
        raise GeneratorError(
            f"{entry.id} is hand-maintained (no generator in {PLANT_FILE}): edit the XML, or "
            f"declare generator: {{script: ..., frame: ...}} for it"
        )
    path = workspace.sheet_path(entry.file)
    if path is None:
        raise GeneratorError(f"{entry.id}: sheet file {entry.file} is outside the repository")
    output = produce(workspace, entry)
    current = path.read_bytes() if path.is_file() else None
    script = entry.generator.script
    if current == output:
        return RegenResult(entry, "unchanged", [f"{entry.file}: up to date with {script}"])
    if current is not None and not force and not _is_frame(workspace, entry, current):
        previous = previous_output(workspace, entry, output)
        if previous is None:
            raise RegenRefused(
                f"{entry.file} differs from what {script} makes and there is no commit to tell "
                "whether it was edited by hand: commit first, or pass --force to overwrite"
            )
        if previous != current:
            found = drift(previous, current)
            raise RegenRefused(
                f"{entry.file} was edited by hand: it differs from what {script} (as committed) "
                f"makes from frame {entry.generator.frame}: {found.summary()}. Regenerating "
                "would discard that. Move the edits into the script and pass --force, or keep "
                f"the XML as the source: cheme regen --detach {entry.id}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)
    lines = [f"{entry.file}: regenerated by {script} from frame {entry.generator.frame}"]
    if current is not None:
        lines.append(f"  {drift(current, output).summary()} (old sheet -> new output)")
    return RegenResult(entry, "written", lines)


# -- detach -------------------------------------------------------------------------------------


def _mapping_value(node: Any, key: str) -> tuple[Any, Any] | None:
    if not isinstance(node, yaml.MappingNode):
        return None
    for k, v in node.value:
        if isinstance(k, yaml.ScalarNode) and k.value == key:
            return k, v
    return None


def remove_generator(text: str, sheet_id: str) -> str:
    """``plant.yaml`` *text* without the ``generator`` of sheet *sheet_id*, comments kept."""
    root = yaml.compose(text)
    found = _mapping_value(root, "sheets")
    if found is None or not isinstance(found[1], yaml.SequenceNode):
        raise GeneratorError(f"{PLANT_FILE} has no sheets list")
    for entry in found[1].value:
        ident = _mapping_value(entry, "id")
        if ident is None or ident[1].value != sheet_id:
            continue
        generator = _mapping_value(entry, "generator")
        if generator is None:
            raise GeneratorError(f"{sheet_id} has no generator in {PLANT_FILE}")
        key, value = generator
        start, end = key.start_mark.index, value.end_mark.index
        if entry.flow_style:
            comma = text.rfind(",", entry.start_mark.index, start)
            if comma != -1:
                start = comma
            else:
                after = re.match(r"\s*,\s*", text[end:])
                end += after.end() if after else 0
        else:
            start = text.rfind("\n", 0, start) + 1
            last = text[:end].rstrip()
            newline = text.find("\n", len(last))
            end = len(text) if newline == -1 else newline + 1
        new = text[:start] + text[end:]
        before = yaml.safe_load(text)
        after_data = yaml.safe_load(new)
        for sheet in before.get("sheets", []):
            if isinstance(sheet, dict) and sheet.get("id") == sheet_id:
                sheet.pop("generator", None)
        if before != after_data:
            raise GeneratorError(
                f"cannot remove the generator of {sheet_id} from {PLANT_FILE} safely: delete its "
                "generator: entry by hand"
            )
        return new
    raise GeneratorError(f"{sheet_id}: no such sheet in {PLANT_FILE}")


def detach(workspace: Workspace, entry: SheetEntry) -> list[str]:
    """Make *entry* hand-maintained: drop its ``generator`` from ``plant.yaml``."""
    if entry.generator is None:
        raise GeneratorError(f"{entry.id} is hand-maintained already (no generator)")
    if entry.kind != "pid":
        raise GeneratorError(f"{entry.id} is a {entry.kind}: its source is process/*.yaml")
    plant = workspace.root / PLANT_FILE
    plant.write_text(remove_generator(plant.read_text(encoding="utf-8"), entry.id), "utf-8")
    return [
        f"{PLANT_FILE}: {entry.id} is hand-maintained now (generator removed); {entry.file} is "
        "the source, edit it (skill pid-edit)",
        f"  {entry.generator.script} is provenance only: keep it unchanged or delete it",
    ]


# -- validate -----------------------------------------------------------------------------------


def _draft_script(workspace: Workspace, entry: SheetEntry) -> Path | None:
    path = workspace.root / "scripts" / f"draft_{entry.id}.py"
    return path if path.is_file() else None


def generator_findings(
    workspace: Workspace, targets: set[Path] | None, *, run: bool = True
) -> list[Any]:
    """``generated-sheet-drift`` per drifting generated sheet (when *run*), an info note per
    undeclared ``scripts/draft_<sheet>.py``, ``generator-failed`` per generator that fails."""
    from chemeascode.foundation.findings import Finding

    findings: list[Finding] = []
    try:
        entries = sheet_entries(workspace)
    except Exception:  # noqa: BLE001 - plant.yaml errors are reported elsewhere
        return findings
    if not entries:
        # No sheets listed: every pid/*.xml is a sheet, named after its file.
        entries = [SheetEntry(id=p.stem, file=workspace.relative(p)) for p in workspace.pid_files()]
    for entry in entries:
        path = workspace.sheet_path(entry.file)
        if path is None or (targets is not None and path.resolve() not in targets):
            continue
        if entry.kind != "pid":  # process sheets: provenance rules in domains.process.sheets
            continue
        if entry.generator is None:
            script = _draft_script(workspace, entry)
            if script is not None:
                findings.append(
                    Finding(
                        workspace.relative(script),
                        "info",
                        "cheme.generator-undeclared",
                        f"{workspace.relative(script)} looks like the generator of {entry.id}, "
                        f"but {PLANT_FILE} declares none: {entry.file} is hand-maintained and "
                        "the script is provenance only",
                        hint=f"if the script is the source, add generator: {{script: "
                        f"{workspace.relative(script)}, frame: <commit or file>}} to {entry.id} "
                        "in plant.yaml; otherwise never rerun it over the sheet",
                    )
                )
            continue
        if not run or not path.is_file():
            continue
        try:
            output = produce(workspace, entry)
        except GeneratorError as failure:
            findings.append(
                Finding(
                    entry.file,
                    "warning",
                    "cheme.generator-failed",
                    str(failure),
                    hint=f"fix the generator or its frame in {PLANT_FILE}, then cheme regen "
                    f"{entry.id}",
                )
            )
            continue
        current = path.read_bytes()
        if output != current:
            findings.append(
                Finding(
                    entry.file,
                    "warning",
                    "cheme.generated-sheet-drift",
                    f"{entry.file} is declared generated by {entry.generator.script}, which no "
                    f"longer reproduces it: {drift(output, current).summary()}",
                    hint=f"script changed: cheme regen {entry.id}; XML edited by hand: move "
                    f"the edit into the script, or cheme regen --detach {entry.id} to keep "
                    "the XML as the source",
                )
            )
    return findings


def describe(entry: SheetEntry) -> str:
    """``P-04 pid/P-04.xml: generated by scripts/draft_P-04.py from frame 9aa9b38``."""
    if entry.generator is None:
        return f"{entry.id} {entry.file}: hand-maintained"
    if not isinstance(entry.generator, Generator):
        return f"{entry.id} {entry.file}: {entry.kind}, generated by cheme process build"
    generator: Generator = entry.generator
    return f"{entry.id} {entry.file}: generated by {generator.script} from frame {generator.frame}"
