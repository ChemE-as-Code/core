"""The NCI Chemical Identifier Resolver (CACTUS): identifier to SMILES.

CACTUS accepts more identifier strings than PubChem's name search: common and IUPAC names,
formulas ("H2O", "N2O5"), CAS numbers, InChI and SMILES. It is not always right: it has read
condensed structural formulas such as "CH3COOH" as another compound without an error. Prefer
PubChem, fall back to CACTUS only when PubChem does not resolve the input, and treat its result
as lower confidence.
"""

from __future__ import annotations

from urllib.parse import quote

from chemeascode.integrations.http import HttpClient, HttpError

CACTUS_BASE_URL = "https://cactus.nci.nih.gov/chemical/structure/"


def name_to_smiles(identifier: str, *, client: HttpClient | None = None) -> str:
    """The SMILES CACTUS reports for *identifier* (name, formula, CAS number, ...).

    Raises ``ValueError`` when CACTUS does not know the identifier or the request fails.
    """
    client = client or HttpClient()
    # "#" (triple bond) must be encoded, "/" must not: CACTUS resolves it inside the path
    # (stereo SMILES, InChI) but answers 404 for "%2F".
    url = f"{CACTUS_BASE_URL}{quote(identifier, safe='/')}/SMILES"
    try:
        response = client.get(url, timeout_s=10.0, raise_for_status=False)
    except HttpError as failure:
        raise ValueError(f"CACTUS request failed for {identifier!r}: {failure}") from failure
    text = response.text.strip()
    if response.status != 200 or "Page not found" in text or not text:
        raise ValueError(f"No {identifier!r} in CACTUS")
    return text.splitlines()[0].strip()
