import atexit
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from chemeascode.templates.install import init

# bw2data creates its data directory when it is imported, with os.makedirs without exist_ok: the
# workers of pytest -n collecting test_lca_backends.py at once race on the shared default
# (~/.local/share/Brightway3). Every test process (the controller and each worker, which
# inherits the controller's environment) gets a temporary one of its own, which also keeps the
# tests away from the user's Brightway projects; a BRIGHTWAY2_DIR the user set is kept.
_BRIGHTWAY_PREFIX = "cheme-tests-brightway-"
if Path(os.environ.get("BRIGHTWAY2_DIR", _BRIGHTWAY_PREFIX)).name.startswith(_BRIGHTWAY_PREFIX):
    os.environ["BRIGHTWAY2_DIR"] = tempfile.mkdtemp(prefix=_BRIGHTWAY_PREFIX)
    atexit.register(shutil.rmtree, os.environ["BRIGHTWAY2_DIR"], ignore_errors=True)

DATA = Path(__file__).parent / "data"
REFERENCE = DATA / "reference_pid.xml"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


#: The template's gates on the 3D layout and its take-off (a plant without a layout cannot pass
#: them).
LAYOUT_GATES = (
    "layout-plot-plan",
    "layout-3d",
    "mto",
    "layout-review",
    "lifting-study",
    "layout-detail",
    "electrical",
    "hvac",
)


def without_layout_gates(root: Path) -> None:
    """Mark the template's layout gates not applicable (``applies: false``) in *root*."""
    path = root / "checks" / "checks.yaml"
    text = path.read_text(encoding="utf-8")
    for gate in LAYOUT_GATES:
        line = f"  - id: {gate}\n"
        assert line in text, gate
        text = text.replace(line, line + "    applies: false\n")
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def plant(tmp_path: Path) -> Path:
    """A fresh plant repository holding the reference P&ID as pid/P-01.xml, in git."""
    root = tmp_path / "plant"
    init(root, "Test plant")
    shutil.copy(REFERENCE, root / "pid" / "P-01.xml")
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.org")
    git(root, "config", "user.name", "Test")
    # no background repacking after a commit: tests compare the repository before and after
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    return root


@pytest.fixture(autouse=True)
def _isolated_user_data_dir(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> Path:
    """Fetched datasets (``cheme data fetch``) never come from the developer's own data dir."""
    path = tmp_path_factory.mktemp("cheme-data")
    monkeypatch.setenv("CHEME_DATA_DIR", str(path))
    return path
