"""Freeze ``GET /api/layout`` of a plant repository as a JSON fixture for the viewer.

Usage: uv run --extra serve python scripts/build_layout_fixture.py PLANT_DIR [OUT]

PLANT_DIR is copied into a temporary directory (it is never written to), ``cheme layout
build`` runs on the copy, and ``/api/layout`` of the copy's working tree is written to OUT
(default ``tests/data/api-layout-asu.json``) with ``rev`` left out, keys sorted, two-space
indent, so a rerun on the same inputs gives the same file. ``tests/test_layout_model.py``
checks the fixture against the ``layout_model`` schema; the viewer is built against it.

The fixture is built from the ASU example as it is (its layout files hold the structures,
zones, routing rules and pipe specs). PLANT_DIR is the plant root, the folder holding
``plant.yaml``: in a clone of the process-library repository that is its subfolder
``processes/asu-1`` (e.g. ``~/Developer/repos/plantcode-asu/processes/asu-1``). Given the
library's top instead, the script takes ``processes/asu-1`` under it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "tests" / "data" / "api-layout-asu.json"
#: The ASU's folder in the process-library repository.
ASU_FOLDER = "processes/asu-1"


def main(argv: list[str]) -> int:
    args = list(argv)
    if not args:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    source = Path(args[0]).expanduser().resolve()
    if not (source / "plant.yaml").is_file() and (source / ASU_FOLDER / "plant.yaml").is_file():
        source = source / ASU_FOLDER
    if not (source / "plant.yaml").is_file():
        print(
            f"{source}: no plant.yaml (give the plant root, e.g. .../{ASU_FOLDER})", file=sys.stderr
        )
        return 2
    out = Path(args[1]) if len(args) > 1 else DEFAULT_OUT
    from fastapi.testclient import TestClient

    from chemeascode.domains.spatial.model import build_model, write_model
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.interfaces.api.serve import create_app

    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / source.name
        shutil.copytree(source, copy, ignore=shutil.ignore_patterns(".git", "build"))
        workspace = Workspace(copy)
        model = build_model(workspace)
        write_model(workspace, model)
        client = TestClient(create_app(copy, None, allowed_hosts=["testserver"]))
        response = client.get("/api/layout")
        response.raise_for_status()
        data = response.json()
    data.pop("rev", None)
    out.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    nozzles = sum(len(item["nozzles"]) for item in data["model"]["equipment"])
    model = data["model"]
    print(
        f"wrote {out}: {len(data['equipment'])} items, {nozzles} nozzles, "
        f"{len(model['pipes'])} pipes, {len(model['inline'])} in-line items, "
        f"{len(model['structures'])} structures, {len(model['platforms'])} platforms, "
        f"{len(model['zones'])} zones, {len(model['unrouted'])} unrouted"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
