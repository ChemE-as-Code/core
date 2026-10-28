"""Git integration: readable P&ID diffs and a pre-commit hook."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ATTRIBUTES_LINE = "pid/*.xml diff=dexpi"

HOOK = """#!/bin/sh
# Installed by `cheme git-setup`: P&IDs must be formatted and valid before a commit.
set -e
cheme() {{ {cheme} "$@"; }}
# The plant root, relative to the top of the git repository (recorded by git-setup).
cd "$(git rev-parse --show-toplevel)"/{plant_dir}
staged=$(git diff --cached --name-only --relative --diff-filter=ACM -- 'pid/*.xml')
if [ -n "$staged" ]; then
  cheme fmt --check $staged || {{
    echo "Run: cheme fmt $staged && git add $staged" >&2; exit 1; }}
fi
cheme validate --quiet
"""

#: A projection token: ``Class@`` and 12 hex digits.
_TOKEN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*@[0-9a-f]{12}\b")


def cheme_command() -> str:
    """The command that runs this cheme-as-code, as an absolute path, quoted for a shell.

    Git runs a textconv driver and the hook through a shell that may not have cheme on its
    PATH (a GUI client, an IDE), so the command is resolved now: the cheme script this
    process was started from (the installation actually running, even when another one comes
    first on PATH), else the ``cheme`` on PATH, else ``<python> -m chemeascode``.
    """
    script = sys.argv[0] if sys.argv and sys.argv[0] else ""
    if Path(script).name == "cheme" and Path(script).is_file():
        return shlex.quote(os.path.abspath(script))
    found = shutil.which("cheme")
    if found:
        return shlex.quote(os.path.abspath(found))
    return f"{shlex.quote(sys.executable)} -m chemeascode"


def readable_projection(model: Any) -> str:
    """pyDEXPI's review text of *model*, with every token written with the id of the file.

    pyDEXPI names each object ``Class@<hash>``. An object whose id the file gives (every one,
    after ``cheme fmt``) is written ``Class@<id>`` instead -- ``PipeTee@PipeTee_47123_BypassIn``
    -- so the text can be searched for the ids in the XML. Objects without one (ids minted on
    load) keep pyDEXPI's stable anchored token.
    """
    from pydexpi.toolkits.base_model_utils import is_generated_id
    from pydexpi.versioning import model_to_projection

    text = model_to_projection(model, id_policy="source")
    try:
        from pydexpi.versioning._index import _ModelIndex
        from pydexpi.versioning.projection import _Tokens
    except ImportError:  # pragma: no cover - a pyDEXPI without them: hashes stay
        return text
    index = _ModelIndex(model)
    tokens = _Tokens(index, "source").of
    readable = {
        token: f"{type(index.objects[object_id]).__name__}@{object_id}"
        for object_id, token in tokens.items()
        if not is_generated_id(object_id)
    }
    return _TOKEN.sub(lambda match: readable.get(match.group(0), match.group(0)), text)


def textconv(path: Path) -> str:
    """The review text of a P&ID, which git shows in place of its XML. Never raises."""
    try:
        from chemeascode.domains.piping.render import load_model

        return readable_projection(load_model(path))
    except Exception as failure:  # noqa: BLE001 -- git must still show something
        reason = f"{type(failure).__name__}: {failure}".splitlines()[0]
        header = f"(cheme textconv could not load {path}, showing the XML: {reason})\n"
        try:
            return header + path.read_text(encoding="utf-8", errors="replace")
        except OSError as unreadable:
            return header + f"(and could not read it: {unreadable})\n"


def setup(root: Path, *, hook: bool = True) -> list[str]:
    """Register the textconv driver and the hook in the repository at *root*."""
    done = []
    command = cheme_command()
    attributes = root / ".gitattributes"
    existing = attributes.read_text(encoding="utf-8") if attributes.exists() else ""
    if ATTRIBUTES_LINE not in existing.splitlines():
        attributes.write_text(
            existing
            + ("" if existing.endswith("\n") or not existing else "\n")
            + ATTRIBUTES_LINE
            + "\n",
            encoding="utf-8",
        )
        done.append(f".gitattributes: {ATTRIBUTES_LINE}")
    driver = f"{command} textconv"
    subprocess.run(["git", "config", "diff.dexpi.textconv", driver], cwd=root, check=True)
    subprocess.run(["git", "config", "diff.dexpi.cachetextconv", "true"], cwd=root, check=True)
    done.append(f"git config diff.dexpi.textconv {shlex.quote(driver)}")
    if hook:
        hooks = Path(
            subprocess.run(
                ["git", "rev-parse", "--git-path", "hooks"],
                cwd=root,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        )
        hooks = hooks if hooks.is_absolute() else root / hooks
        hooks.mkdir(parents=True, exist_ok=True)
        target = hooks / "pre-commit"
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        plant_dir = Path(os.path.relpath(root.resolve(), Path(top).resolve())).as_posix()
        target.write_text(
            HOOK.format(cheme=command, plant_dir=shlex.quote(plant_dir)), encoding="utf-8"
        )
        target.chmod(target.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        done.append(f"pre-commit hook: {target}")
    return done
