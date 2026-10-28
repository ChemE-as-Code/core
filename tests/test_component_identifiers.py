"""Component identifiers (pre-release issue 114): CAS check digit, SMILES against InChIKey and
formula, and the reaction SMILES ``GET /api/reactions`` derives from the stoichiometry."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.chemistry.reactions import Reaction
from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.reaction_view import reactions_payload
from chemeascode.domains.process.schema import Component
from chemeascode.foundation.schema_base import cas_check_digit_ok
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
RULES = ("cheme.component-cas", "cheme.component-identity")


def _edit(path: Path, edit) -> None:
    data = yaml.safe_load(path.read_text())
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _found(root: Path) -> list:
    return [f for f in validate_workspace(Workspace(root)).findings if f.rule in RULES]


@pytest.fixture
def shift(tmp_path):
    shutil.copytree(EXAMPLES / "process-shift", tmp_path / "plant")
    return tmp_path / "plant"


def _component(data: dict, cid: str) -> dict:
    return next(c for c in data["components"] if c["id"] == cid)


def test_cas_check_digit():
    assert all(cas_check_digit_ok(c) for c in ("630-08-0", "7732-18-5", "74-82-8", "7440-37-1"))
    assert not cas_check_digit_ok("74-82-9")


def test_inchikey_has_the_standard_shape():
    Component(id="CH4", name="Methane", inchikey="VNWKTOKETHGBQD-UHFFFAOYSA-N")
    with pytest.raises(ValidationError, match="inchikey"):
        Component(id="CH4", name="Methane", inchikey="VNWKTOKETHGBQD-UHFFFAOYSA")


def test_identified_example_is_clean(shift):
    assert _found(shift) == []


def test_wrong_cas_check_digit_warns(shift):
    _edit(shift / "process/materials.yaml", lambda d: _component(d, "CH4").update(cas="74-82-9"))
    (found,) = _found(shift)
    assert (found.rule, found.level, found.ids) == ("cheme.component-cas", "warning", ["CH4"])
    assert "check digit" in found.message and found.line is not None


def test_smiles_that_names_another_compound_warns(shift):
    pytest.importorskip("rdkit")

    def edit(data):
        _component(data, "CH4").update(smiles="CC")  # ethane: InChIKey and formula differ
        _component(data, "H2O").update(smiles="not a smiles")

    _edit(shift / "process/materials.yaml", edit)
    found = _found(shift)
    assert {f.rule for f in found} == {"cheme.component-identity"}
    assert {f.level for f in found} == {"warning"}
    messages = sorted((f.ids[0], f.message) for f in found)
    assert [cid for cid, _ in messages] == ["CH4", "CH4", "H2O"]
    assert "InChIKey VNWKTOKETHGBQD-UHFFFAOYSA-N differs" in messages[0][1] + messages[1][1]
    assert "formula CH4 differs from C2H6" in messages[0][1] + messages[1][1]
    assert "does not parse" in messages[2][1]


def test_smiles_is_not_checked_without_rdkit(shift, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "rdkit", None)
    _edit(shift / "process/materials.yaml", lambda d: _component(d, "CH4").update(smiles="CC"))
    assert _found(shift) == []


def test_reaction_smiles():
    wgs = Reaction(id="WGS", stoichiometry={"CO": -1, "H2O": -1, "CO2": 1, "H2": 1})
    smiles = {"CO": "[C-]#[O+]", "H2O": "O", "CO2": "O=C=O", "H2": "[H][H]"}
    assert wgs.reaction_smiles(smiles) == "[C-]#[O+].O>>O=C=O.[H][H]"
    assert wgs.reaction_smiles({**smiles, "H2": None}) is None
    smr = Reaction(id="SMR", stoichiometry={"CH4": -1, "H2O": -1, "CO": 1, "H2": 3})
    assert smr.reaction_smiles({**smiles, "CH4": "C"}) == "C.O>>[C-]#[O+].[H][H].[H][H].[H][H]"
    half = Reaction(id="OX", stoichiometry={"H2": -1, "O2": -0.5, "H2O": 1})
    assert half.reaction_smiles({**smiles, "O2": "O=O"}) is None


def test_api_reactions_carries_the_reaction_smiles(shift):
    process, _ = load_process(shift)
    (wgs,) = reactions_payload(process, "design")["reactions"]
    assert wgs["reaction_smiles"] == "[C-]#[O+].O>>O=C=O.[H][H]"
    process, _ = load_process(EXAMPLES / "process-ammonia")
    payload = reactions_payload(process, "design")
    assert payload["reactions"] and all(r["reaction_smiles"] is None for r in payload["reactions"])


def test_examples_and_asu_test_plant_raise_no_identifier_findings():
    for root in [*sorted(EXAMPLES.glob("process-*")), ROOT / "tests/data/process-asu"]:
        if (root / "process/materials.yaml").is_file():
            assert _found(root) == [], root
