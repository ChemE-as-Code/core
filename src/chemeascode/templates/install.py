"""``cheme init``: a new plant repository from the template shipped with the package.

The project template is ``templates/project/``. The bundled skills live with the code that owns
them, in ``domains/<domain>/skills/<name>/`` and ``project/skills/<name>/``, and are installed
into the repository's ``.claude/skills/<name>/``.

``skills-manifest.json`` records the hash of every bundled skill file and of its earlier
versions, so an installed copy is known to be current, outdated (an earlier bundled version) or
modified (changed locally). ``cheme skills update`` replaces only missing and outdated files;
neither it nor ``cheme init`` replaces a modified one without ``--force``, and both report it.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from contextlib import ExitStack
from dataclasses import dataclass
from importlib.resources import as_file, files
from importlib.resources.abc import Traversable
from pathlib import Path, PurePosixPath

from chemeascode.foundation.findings import Finding

#: Where an installed skill goes, relative to the template (``dot-`` becomes ``.``).
SKILLS_DIR = PurePosixPath("dot-claude/skills")
#: The licence notice of the installed skills, in the skills directory itself and shipped with the
#: template. It belongs to no one skill: its key in the manifest and in ``SkillFile.skill`` is "".
SKILLS_NOTICE = "NOTICE.md"


def template_dir():
    """The project template inside the installed package (the bundled skills apart)."""
    return files("chemeascode") / "templates" / "project"


def bundled_skills() -> dict[str, Traversable]:
    """Each bundled skill directory by name: ``<owner>/skills/<name>/`` holding a ``SKILL.md``,
    for every domain and the project layer. Two skills of one name are an error."""
    package = files("chemeascode")
    owners = [d for d in (package / "domains").iterdir() if d.is_dir()]
    owners.append(package / "project")
    found: dict[str, Traversable] = {}
    for owner in sorted(owners, key=lambda d: d.name):
        skills = owner / "skills"
        if not skills.is_dir():
            continue
        for skill in sorted(skills.iterdir(), key=lambda d: d.name):
            if not (skill / "SKILL.md").is_file():
                continue
            if skill.name in found:
                raise ValueError(f"two bundled skills are named {skill.name!r}")
            found[skill.name] = skill
    return found


def bundled_files() -> dict[str, dict[str, Path]]:
    """Each bundled skill's files by their path inside the skill (POSIX), by skill name; the
    notice of the skills directory under the name ""."""
    found: dict[str, dict[str, Path]] = {}
    for name, skill in bundled_skills().items():
        root = Path(str(skill))
        found[name] = {
            path.relative_to(root).as_posix(): path
            for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts
        }
    found[""] = {SKILLS_NOTICE: Path(str(template_dir())) / SKILLS_DIR / SKILLS_NOTICE}
    return found


# -- the installed skills of a repository -------------------------------------------------------

#: The manifest of the bundled skills, next to this module (``scripts/build_skill_manifest.py``).
MANIFEST_FILE = "skills-manifest.json"
MANIFEST_SCHEMA = "cheme/skills-manifest/v1"
#: Where skills are installed in a plant repository.
INSTALLED_SKILLS = PurePosixPath(".claude/skills")

#: An installed skill file is the bundled one (current), an earlier bundled version (outdated),
#: neither (modified: changed locally), or absent (missing).
SKILL_STATES = ("current", "outdated", "modified", "missing")


def skills_manifest() -> dict:
    """``{"schema": ..., "skills": {name: {file: [sha256 now, earlier ...]}}}``."""
    import json

    text = (files("chemeascode") / "templates" / MANIFEST_FILE).read_text(encoding="utf-8")
    return json.loads(text)


@dataclass(frozen=True)
class SkillFile:
    """One file of one bundled skill, as installed in a plant repository."""

    #: The skill; "" for the notice of the skills directory.
    skill: str
    #: Its path inside the skill directory.
    name: str
    state: str
    #: Its path from the repository root (``.claude/skills/<skill>/<name>``).
    path: str


def skill_status(target: Path, names: list[str] | None = None) -> list[SkillFile]:
    """The state of every file of the bundled skills (or of *names*) installed under *target*.

    Files a repository adds to a skill are its own and are not listed."""
    known = skills_manifest()["skills"]
    found = []
    for skill, skill_files in bundled_files().items():
        if names and skill not in names:
            continue
        for name, source in skill_files.items():
            relative = INSTALLED_SKILLS / skill / name
            installed = target / relative
            if not installed.is_file():
                state = "missing"
            else:
                digest = hashlib.sha256(installed.read_bytes()).hexdigest()
                if digest == hashlib.sha256(source.read_bytes()).hexdigest():
                    state = "current"
                elif digest in known.get(skill, {}).get(name, []):
                    state = "outdated"
                else:
                    state = "modified"
            found.append(SkillFile(skill, name, state, relative.as_posix()))
    return found


def modified_finding(item: SkillFile, replaced: bool = False) -> Finding:
    """``cheme.skill-modified`` for an installed skill file changed locally."""
    action = "replaced by the bundled version (--force)" if replaced else "kept"
    owner = f"skill {item.skill}" if item.skill else "skills directory"
    return Finding(
        item.path,
        "warning",
        "cheme.skill-modified",
        f"{owner}: {item.name} was changed locally and differs from every bundled "
        f"version; {action}",
        ids=[item.skill] if item.skill else [],
        hint="compare it with the bundled skill in the cheme-as-code package and merge by hand"
        if not replaced
        else "the local version is in git history if it was committed",
    )


def update_skills(
    target: Path, names: list[str] | None = None, *, force: bool = False
) -> tuple[list[SkillFile], list[Finding]]:
    """Install the bundled version of every missing or outdated skill file under *target*
    (only of *names*, when given). A locally modified file is kept and reported, unless
    *force*: then it is replaced and still reported. Returns the files written and the
    findings."""
    sources = bundled_files()
    written: list[SkillFile] = []
    findings: list[Finding] = []
    for item in skill_status(target, names):
        if item.state == "current":
            continue
        if item.state == "modified":
            findings.append(modified_finding(item, replaced=force))
            if not force:
                continue
        destination = target / item.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(sources[item.skill][item.name].read_bytes())
        written.append(item)
    return written, findings


def _minor_version() -> str:
    """``X.Y`` of the running cheme-as-code: what a new repository's ``requires:`` names."""
    from chemeascode.foundation.workspace import installed_version

    return ".".join(str(n) for n in installed_version()[:2])


#: The placeholders of plant.yaml and README.md (the quoted name first: plant.yaml's).
_PLACEHOLDER = re.compile(rb'"\{\{plant_name\}\}"|\{\{plant_name\}\}|\{\{cheme_minor\}\}')


def _yaml_string(value: str) -> bytes:
    """*value* as a double-quoted YAML scalar on one line, read back exactly as given."""
    import yaml

    dumped = yaml.safe_dump(value, default_style='"', allow_unicode=True, width=float("inf"))
    return dumped.rstrip("\n").encode("utf-8")


def _sources(stack: ExitStack) -> list[tuple[PurePosixPath, Path]]:
    """Every file to install, by its path in the template tree (skills under ``SKILLS_DIR``),
    sorted by that path."""
    roots = [(PurePosixPath(), template_dir())]
    roots += [(SKILLS_DIR / name, skill) for name, skill in bundled_skills().items()]
    found = []
    for prefix, root in roots:
        source = Path(stack.enter_context(as_file(root)))
        for path in source.rglob("*"):
            if path.is_dir() or "__pycache__" in path.parts:
                continue
            found.append((prefix / path.relative_to(source).as_posix(), path))
    return sorted(found, key=lambda item: item[0].parts)


def init(target: Path, name: str, *, force: bool = False) -> list[Path]:
    """Copy the template and the bundled skills into *target*, naming the plant *name*.
    Returns the files written."""
    target.mkdir(parents=True, exist_ok=True)
    if (target / "plant.yaml").exists() and not force:
        raise FileExistsError(f"{target / 'plant.yaml'} exists; pass --force to overwrite")
    # In plant.yaml the name is a YAML string: quotes, backslashes, a colon or a leading '#'
    # in it must not change the document. One pass, so a name that holds a placeholder is not
    # substituted again.
    values = {
        b'"{{plant_name}}"': _yaml_string(name),
        b"{{plant_name}}": name.encode("utf-8"),
        b"{{cheme_minor}}": _minor_version().encode(),
    }
    written = []
    with ExitStack() as stack:
        for relative, path in _sources(stack):
            # Files git would treat specially are stored under a safe name in the package.
            relative = Path(
                *(p.replace("dot-", ".", 1) if p.startswith("dot-") else p for p in relative.parts)
            )
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() and not force:
                continue
            text = path.read_bytes()
            if destination.name in {"plant.yaml", "README.md"}:
                text = _PLACEHOLDER.sub(lambda match: values[match.group(0)], text)
            destination.write_bytes(text)
            written.append(destination)
    shutil.os.makedirs(target / "pid", exist_ok=True)
    return written
