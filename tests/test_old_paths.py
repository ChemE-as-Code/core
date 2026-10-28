"""The module paths from before the framework restructuring are gone, and stay gone.

There is no compatibility layer (docs/framework/migration-table.md): a shim or alias module for
an old name would be a second public path to maintain. This checks a representative set.
"""

import importlib
import subprocess
import sys

import pytest

OLD = [
    "chemeascode.cli",
    "chemeascode.validate",
    "chemeascode.workspace",
    "chemeascode.serve",
    "chemeascode.authoring",
    "chemeascode.process",
    "chemeascode.schemas.layout",
]


@pytest.mark.parametrize("name", OLD)
def test_old_module_path_does_not_import(name: str):
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(name)


def test_python_m_chemeascode_still_runs():
    result = subprocess.run(
        [sys.executable, "-m", "chemeascode", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "validate" in result.stdout
