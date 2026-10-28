"""SMILES validation and canonicalisation through RDKit (extra ``chemistry``). Local, no network.

RDKit is imported inside the functions.
"""

from __future__ import annotations

# RDKit parses "[HH]" as one hydrogen atom with one implicit hydrogen: a valid but degenerate
# notation for H2 that PubChem uses as its canonical SMILES. It does not match H2 as RMG or NIST
# write it ("[H][H]"), so every SMILES passing through validate_smiles is normalised.
_DEGENERATE_SMILES = {"[HH]": "[H][H]"}


def validate_smiles(smiles: str) -> str:
    """The canonical SMILES of *smiles*; ``ValueError`` if it does not parse or sanitise.

    Callers try this on strings that may be names or formulas before looking them up, so
    RDKit's own error log (written to stderr) is suppressed.
    """
    from rdkit import Chem, rdBase

    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles, sanitize=False)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        try:
            Chem.SanitizeMol(mol)
        except Exception as failure:
            raise ValueError(f"Could not sanitize SMILES {smiles!r}: {failure}") from failure
        canonical = Chem.MolToSmiles(mol)
    return _DEGENERATE_SMILES.get(canonical, canonical)


def canonical_or_raw(smiles: str) -> str:
    """The canonical SMILES, or *smiles* stripped when RDKit cannot parse it."""
    from rdkit import Chem, rdBase

    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        return Chem.MolToSmiles(mol) if mol is not None else smiles.strip()


def smiles_to_inchi(smiles: str) -> str:
    """The standard InChI of *smiles*; ``ValueError`` if it does not parse."""
    from rdkit import Chem, rdBase

    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return Chem.MolToInchi(mol)


def smiles_identity(smiles: str) -> tuple[str, str]:
    """The standard InChIKey and the molecular formula (Hill order) of *smiles*; ``ValueError``
    if it does not parse or sanitise."""
    from rdkit import Chem, rdBase
    from rdkit.Chem.rdMolDescriptors import CalcMolFormula

    with rdBase.BlockLogs():
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError(f"Invalid SMILES: {smiles}")
        return Chem.MolToInchiKey(mol), CalcMolFormula(mol)
