"""PubChem PUG REST (https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest): identifiers and computed
properties of compounds.

Identifiers go in the POST body, not the URL path, so stereo SMILES and InChI (which contain
"/") work. "Not found" (HTTP 404) gives an empty result; other failures raise
:class:`~chemeascode.integrations.http.HttpError`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from chemeascode.foundation.schema_base import CAS_RE
from chemeascode.integrations.http import HttpClient, HttpError

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SearchType = Literal["name", "smiles", "inchi", "sdf", "cid", "formula"]


class PubChemProperties(BaseModel):
    """Properties of one compound; field names are PubChem's, in snake_case."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cid: int | None = Field(default=None, description="PubChem Compound Identifier")
    cas_rn: str | None = Field(default=None, description="CAS number, from the synonyms")
    molecular_formula: str | None = None
    molecular_weight: float | None = Field(default=None, description="g/mol")
    canonical_smiles: str | None = None
    isomeric_smiles: str | None = None
    iupac_name: str | None = None
    inchi: str | None = None
    inchi_key: str | None = None
    xlogp: float | None = Field(default=None, description="Computed octanol-water log P")
    exact_mass: float | None = None
    monoisotopic_mass: float | None = None
    tpsa: float | None = Field(default=None, description="Topological polar surface area, Å²")
    complexity: float | None = None
    charge: int | None = None
    h_bond_donor_count: int | None = None
    h_bond_acceptor_count: int | None = None
    rotatable_bond_count: int | None = None
    heavy_atom_count: int | None = None
    isotope_atom_count: int | None = None
    atom_stereo_count: int | None = None
    defined_atom_stereo_count: int | None = None
    undefined_atom_stereo_count: int | None = None
    bond_stereo_count: int | None = None
    defined_bond_stereo_count: int | None = None
    undefined_bond_stereo_count: int | None = None
    covalent_unit_count: int | None = None
    volume_3d: float | None = None
    conformer_rmsd_3d: float | None = None
    conformer_model_rmsd_3d: float | None = None
    x_steric_quadrupole_3d: float | None = None
    y_steric_quadrupole_3d: float | None = None
    z_steric_quadrupole_3d: float | None = None
    feature_count_3d: int | None = None
    feature_acceptor_count_3d: int | None = None
    feature_donor_count_3d: int | None = None
    feature_anion_count_3d: int | None = None
    feature_cation_count_3d: int | None = None
    feature_ring_count_3d: int | None = None
    feature_hydrophobe_count_3d: int | None = None
    effective_rotor_count_3d: int | None = None
    conformer_count_3d: int | None = None


#: PubChem property name -> field of :class:`PubChemProperties`.
PROPERTY_MAPPING = {
    "CID": "cid",
    "MolecularFormula": "molecular_formula",
    "MolecularWeight": "molecular_weight",
    "CanonicalSMILES": "canonical_smiles",
    "ConnectivitySMILES": "canonical_smiles",  # PubChem's newer name for it
    "IsomericSMILES": "isomeric_smiles",
    "SMILES": "isomeric_smiles",  # PubChem's newer name for it
    "IUPACName": "iupac_name",
    "InChI": "inchi",
    "InChIKey": "inchi_key",
    "XLogP": "xlogp",
    "ExactMass": "exact_mass",
    "MonoisotopicMass": "monoisotopic_mass",
    "TPSA": "tpsa",
    "Complexity": "complexity",
    "Charge": "charge",
    "HBondDonorCount": "h_bond_donor_count",
    "HBondAcceptorCount": "h_bond_acceptor_count",
    "RotatableBondCount": "rotatable_bond_count",
    "HeavyAtomCount": "heavy_atom_count",
    "IsotopeAtomCount": "isotope_atom_count",
    "AtomStereoCount": "atom_stereo_count",
    "DefinedAtomStereoCount": "defined_atom_stereo_count",
    "UndefinedAtomStereoCount": "undefined_atom_stereo_count",
    "BondStereoCount": "bond_stereo_count",
    "DefinedBondStereoCount": "defined_bond_stereo_count",
    "UndefinedBondStereoCount": "undefined_bond_stereo_count",
    "CovalentUnitCount": "covalent_unit_count",
    "Volume3D": "volume_3d",
    "ConformerModelRMSD3D": "conformer_model_rmsd_3d",
    "ConformerRMSD3D": "conformer_rmsd_3d",
    "XStericQuadrupole3D": "x_steric_quadrupole_3d",
    "YStericQuadrupole3D": "y_steric_quadrupole_3d",
    "ZStericQuadrupole3D": "z_steric_quadrupole_3d",
    "FeatureCount3D": "feature_count_3d",
    "FeatureAcceptorCount3D": "feature_acceptor_count_3d",
    "FeatureDonorCount3D": "feature_donor_count_3d",
    "FeatureAnionCount3D": "feature_anion_count_3d",
    "FeatureCationCount3D": "feature_cation_count_3d",
    "FeatureRingCount3D": "feature_ring_count_3d",
    "FeatureHydrophobeCount3D": "feature_hydrophobe_count_3d",
    "EffectiveRotorCount3D": "effective_rotor_count_3d",
    "ConformerCount3D": "conformer_count_3d",
}

BASIC_PROPERTIES = ("MolecularFormula", "MolecularWeight", "CanonicalSMILES", "IUPACName")
EXTENDED_PROPERTIES = (
    *BASIC_PROPERTIES,
    "IsomericSMILES",
    "InChI",
    "InChIKey",
    "XLogP",
    "ExactMass",
    "TPSA",
    "Complexity",
    "Charge",
    "HBondDonorCount",
    "HBondAcceptorCount",
    "RotatableBondCount",
)


def parse_properties(row: dict[str, Any]) -> PubChemProperties:
    """One ``PropertyTable.Properties`` entry as :class:`PubChemProperties`; a value of the wrong
    type becomes None rather than failing the whole row."""
    fields = PubChemProperties.model_fields
    data: dict[str, Any] = {}
    for api_name, name in PROPERTY_MAPPING.items():
        if api_name not in row or row[api_name] is None or data.get(name) is not None:
            continue
        annotation = str(fields[name].annotation)
        cast = int if "int" in annotation else float if "float" in annotation else str
        try:
            data[name] = cast(row[api_name])
        except (TypeError, ValueError):
            data[name] = None
    return PubChemProperties(**data)


def _json_or_none(response_call) -> Any:
    try:
        return response_call().json()
    except HttpError as failure:
        if failure.status == 404:
            return None
        raise


def search_cids(
    query: str,
    search_type: SearchType = "name",
    *,
    max_records: int = 100,
    client: HttpClient | None = None,
) -> list[int]:
    """CIDs matching *query*, best first; empty when PubChem knows none."""
    if not query.strip():
        raise ValueError("query must be a non-empty string")
    if not 1 <= max_records <= 10000:
        raise ValueError("max_records must be between 1 and 10000")
    client = client or HttpClient()
    data = _json_or_none(
        lambda: client.post_form(
            f"{PUBCHEM_BASE}/compound/{search_type}/cids/JSON",
            {search_type: query},
            {"MaxRecords": max_records},
        )
    )
    return list((data or {}).get("IdentifierList", {}).get("CID", []))


def get_properties(
    cids: list[int],
    properties: tuple[str, ...] | list[str] = BASIC_PROPERTIES,
    *,
    client: HttpClient | None = None,
) -> list[PubChemProperties]:
    """The *properties* (PubChem names) of each CID, in PubChem's order."""
    if not cids:
        return []
    client = client or HttpClient()
    path = f"/compound/cid/{','.join(map(str, cids))}/property/{','.join(properties)}/JSON"
    data = _json_or_none(lambda: client.get(PUBCHEM_BASE + path))
    rows = (data or {}).get("PropertyTable", {}).get("Properties", [])
    return [parse_properties(row) for row in rows]


def cas_from_synonyms(cid: int, *, client: HttpClient | None = None) -> str | None:
    """The first synonym of *cid* that has the form of a CAS number, or None."""
    client = client or HttpClient()
    data = _json_or_none(lambda: client.get(f"{PUBCHEM_BASE}/compound/cid/{cid}/synonyms/JSON"))
    info = (data or {}).get("InformationList", {}).get("Information", [{}])
    return next((s for s in (info[0] if info else {}).get("Synonym", []) if CAS_RE.match(s)), None)


def search_compounds(
    query: str,
    search_type: SearchType = "name",
    *,
    max_records: int = 10,
    client: HttpClient | None = None,
) -> list[PubChemProperties]:
    """The basic properties of the (up to ten) best matches; the first also gets its CAS number
    from the synonyms (one extra request, to spare PubChem's rate limit)."""
    client = client or HttpClient()
    cids = search_cids(query, search_type, max_records=max_records, client=client)
    compounds = get_properties(cids[:10], BASIC_PROPERTIES, client=client)
    for compound, cid in zip(compounds, cids, strict=False):
        compound.cid = compound.cid or cid
    if compounds and compounds[0].cid is not None:
        compounds[0].cas_rn = cas_from_synonyms(compounds[0].cid, client=client)
    return compounds


def similar_cids(
    smiles: str,
    *,
    threshold: int = 90,
    max_records: int = 100,
    client: HttpClient | None = None,
) -> list[int]:
    """CIDs whose 2D Tanimoto similarity to *smiles* is at least *threshold* (0-100)."""
    if not 0 <= threshold <= 100:
        raise ValueError("threshold must be between 0 and 100")
    client = client or HttpClient()
    # fastsimilarity_2d is synchronous; plain "similarity" is asynchronous and refused here.
    data = _json_or_none(
        lambda: client.post_form(
            f"{PUBCHEM_BASE}/compound/fastsimilarity_2d/smiles/cids/JSON",
            {"smiles": smiles},
            {"Threshold": threshold, "MaxRecords": max_records},
        )
    )
    return list((data or {}).get("IdentifierList", {}).get("CID", []))


def get_record(cid: int, *, client: HttpClient | None = None) -> dict[str, Any] | None:
    """The full JSON record of *cid*, or None if PubChem does not know it."""
    client = client or HttpClient()
    return _json_or_none(lambda: client.get(f"{PUBCHEM_BASE}/compound/cid/{cid}/JSON"))
