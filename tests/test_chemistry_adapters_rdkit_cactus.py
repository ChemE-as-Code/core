"""validate_smiles (RDKit) and name_to_smiles (CACTUS), ported from LLM4ChemE
tests/tools/test_rdkit_tools.py and test_cactus.py; CACTUS is a fake transport."""

from __future__ import annotations

import pytest

from chemeascode.integrations.cactus import CACTUS_BASE_URL, name_to_smiles
from chemeascode.integrations.http import HttpClient, HttpError, Request, Response


class TestValidateSmiles:
    @pytest.fixture(autouse=True)
    def _rdkit(self):
        pytest.importorskip("rdkit")

    def test_canonicalizes_valid_smiles(self):
        from chemeascode.integrations.rdkit import validate_smiles

        assert validate_smiles("OCC") == "CCO"

    def test_raises_for_invalid_smiles(self):
        from chemeascode.integrations.rdkit import validate_smiles

        with pytest.raises(ValueError):
            validate_smiles("not a smiles")

    def test_normalizes_degenerate_hydrogen_notation(self):
        """PubChem writes H2 as "[HH]"; RMG and NIST as "[H][H]"."""
        from chemeascode.integrations.rdkit import validate_smiles

        assert validate_smiles("[HH]") == "[H][H]"
        assert validate_smiles("[H][H]") == "[H][H]"


class FakeCactus:
    def __init__(self, text: str = "CCO\n", status: int = 200, fail: bool = False) -> None:
        self.text, self.status, self.fail = text, status, fail
        self.urls: list[str] = []

    def __call__(self, request: Request) -> Response:
        self.urls.append(request.url)
        if self.fail:
            raise HttpError("boom", url=request.url)
        return Response(self.status, self.text, request.url)


def client(fake) -> HttpClient:
    return HttpClient(transport=fake, sleep=lambda _: None)


@pytest.mark.parametrize(
    ("identifier", "expected_path"),
    [
        ("ethanol", "ethanol"),
        ("acetic acid", "acetic%20acid"),
        ("C#C", "C%23C"),  # "#" would start a URL fragment
        ("[NH4+]", "%5BNH4%2B%5D"),
        ("C/C=C/C", "C/C%3DC/C"),  # CACTUS needs "/" literal
        ("InChI=1S/CH4/h1H4", "InChI%3D1S/CH4/h1H4"),
    ],
)
def test_name_to_smiles_encodes_identifier(identifier, expected_path):
    fake = FakeCactus()
    assert name_to_smiles(identifier, client=client(fake)) == "CCO"
    assert fake.urls == [f"{CACTUS_BASE_URL}{expected_path}/SMILES"]


def test_name_to_smiles_not_found_raises():
    fake = FakeCactus("Page not found (404)", status=404)
    with pytest.raises(ValueError, match="No 'unobtainium' in CACTUS"):
        name_to_smiles("unobtainium", client=client(fake))


def test_name_to_smiles_request_error_raises():
    with pytest.raises(ValueError, match="CACTUS request failed"):
        name_to_smiles("ethanol", client=client(FakeCactus(fail=True)))
