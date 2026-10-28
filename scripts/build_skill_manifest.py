"""Write the bundled-skills manifest: every file of every bundled skill with its hash history.

Usage: uv run python scripts/build_skill_manifest.py

For each file of each skill under ``domains/<d>/skills/<name>/`` and ``project/skills/<name>/``
the manifest lists the sha256 of the current file first, then of every earlier version this
repository's git history has of it, at its current path, at that path under the package's name
before 0.7.0 (``src/plantcode/...``) or at the earlier bundled location
``src/plantcode/template/dot-claude/skills/<name>/``. ``cheme skills status`` uses it to tell
an installed copy that is only out of date from one changed locally. Rerun it whenever a skill
changes; ``tests/test_skills.py`` fails until then.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from chemeascode.templates.install import MANIFEST_FILE, MANIFEST_SCHEMA, bundled_files

ROOT = Path(__file__).resolve().parents[1]
#: Where the skills were bundled before they moved to their domains.
EARLIER = ["src/plantcode/template/dot-claude/skills/{name}/{file}"]
#: The package directory before the rename to cheme-as-code (0.7.0).
OLD_PACKAGE = ("src/chemeascode/", "src/plantcode/")


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)


def history(paths: list[str]) -> list[str]:
    """sha256 of every committed version of *paths*, newest first, without repeats."""
    commits = _git("rev-list", "HEAD", "--", *paths).stdout.decode().split()
    found: list[str] = []
    for commit in commits:
        for path in paths:
            shown = _git("show", f"{commit}:{path}")
            if shown.returncode == 0:
                digest = hashlib.sha256(shown.stdout).hexdigest()
                if digest not in found:
                    found.append(digest)
    return found


def main() -> None:
    out = ROOT / "src/chemeascode/templates" / MANIFEST_FILE
    # The 0.8.0 history was squashed, so git no longer holds the earlier versions: keep the
    # hashes the manifest already lists after those git still knows.
    known = json.loads(out.read_text(encoding="utf-8"))["skills"] if out.is_file() else {}
    skills: dict[str, dict[str, list[str]]] = {}
    for name, files in bundled_files().items():
        entry = skills.setdefault(name, {})
        for relative, source in files.items():
            current = hashlib.sha256(source.read_bytes()).hexdigest()
            paths = [source.resolve().relative_to(ROOT).as_posix()]
            paths.append(paths[0].replace(*OLD_PACKAGE, 1))
            paths += [p.format(name=name, file=relative) for p in EARLIER]
            hashes = [current]
            for digest in history(paths) + known.get(name, {}).get(relative, []):
                if digest not in hashes:
                    hashes.append(digest)
            entry[relative] = hashes
    manifest = {"schema": MANIFEST_SCHEMA, "skills": skills}
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{out.relative_to(ROOT)}: {sum(len(f) for f in skills.values())} files")


if __name__ == "__main__":
    main()
