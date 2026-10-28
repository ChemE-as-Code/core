"""``cheme run``: run a Python script in cheme-as-code's own interpreter.

A plant repository has no Python project of its own, so neither the system ``python3`` nor
``uv run python`` can import pyDEXPI there. ``cheme run`` executes the script in the
interpreter cheme-as-code is installed in, where ``pydexpi`` and ``chemeascode`` (with
``chemeascode.domains.piping.authoring``) are importable, with ``sys.argv`` set and the working
directory at the repository root, so relative paths in the script and its arguments mean the
same thing wherever it is started from.
"""

from __future__ import annotations

import os
import runpy
import sys
import traceback
from pathlib import Path


class ScriptNotFound(Exception):
    """The script to run does not exist."""


def resolve_script(script: Path, root: Path, cwd: Path | None = None) -> Path:
    """*script* as an absolute path: as given, relative to *cwd*, else to the repository root."""
    relative = [(cwd or Path.cwd()) / script, root / script]
    candidates = [script] if script.is_absolute() else relative
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ScriptNotFound(f"{script}: no such script (looked in {', '.join(map(str, candidates))})")


def _exit_code(code: object) -> int:
    """The process exit code ``sys.exit(code)`` gives, as Python itself computes it."""
    if code is None:
        return 0
    if isinstance(code, bool):
        return int(code)
    if isinstance(code, int):
        return code & 0xFF if code >= 0 else code % 256
    print(code, file=sys.stderr)
    return 1


def run_script(script: Path, args: list[str], root: Path) -> int:
    """Run *script* as ``__main__`` with *args*, cwd *root*; return its exit code.

    ``sys.argv``, ``sys.path`` and the working directory are restored afterwards. An uncaught
    exception prints its traceback (without cheme-as-code's own frames) and gives exit code 1, as
    ``python script.py`` would.
    """
    saved_argv, saved_path, saved_cwd = sys.argv[:], sys.path[:], os.getcwd()
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(script.parent))
    os.chdir(root)
    try:
        runpy.run_path(str(script), run_name="__main__")
    except SystemExit as stop:
        return _exit_code(stop.code)
    except BaseException as failure:  # noqa: BLE001 - report it as the interpreter would
        if isinstance(failure, KeyboardInterrupt):
            return 130
        frames = traceback.extract_tb(failure.__traceback__)
        own = [i for i, f in enumerate(frames) if Path(f.filename).resolve() == script]
        tb = failure.__traceback__
        for _ in range(own[0] if own else 0):
            tb = tb.tb_next if tb is not None else None
        traceback.print_exception(type(failure), failure, tb, file=sys.stderr)
        return 1
    finally:
        sys.stdout.flush()
        sys.argv, sys.path[:] = saved_argv, saved_path
        os.chdir(saved_cwd)
    return 0


def interpreter_line() -> str:
    """``python <version> at <sys.executable>``: the interpreter ``cheme run`` uses."""
    version = ".".join(str(v) for v in sys.version_info[:3])
    return f"python {version} at {sys.executable}"
