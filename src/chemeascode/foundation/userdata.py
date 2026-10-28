"""The per-user data directory for data that cheme-as-code does not ship and a user fetches.

``$CHEME_DATA_DIR`` if set, else the platform's user data directory: ``~/Library/Application
Support/cheme-as-code`` (macOS), ``%LOCALAPPDATA%\\cheme-as-code`` (Windows),
``$XDG_DATA_HOME/cheme-as-code`` or ``~/.local/share/cheme-as-code`` (elsewhere). Nothing is
created here; the code that writes a dataset creates its directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "cheme-as-code"
ENV_VAR = "CHEME_DATA_DIR"


def user_data_dir() -> Path:
    """The directory fetched datasets are written to and read from."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / APP_NAME
