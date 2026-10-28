"""Resolve and validate the SMILES of a reaction's species.

The seven diatomic elements are resolved without a network call. Other identifiers (names,
formulas, ...) go to PubChem's name search first and to CACTUS when PubChem does not resolve
them (e.g. a formula such as "N2O5"). Every SMILES is canonicalised by RDKit
(:func:`chemeascode.integrations.rdkit.validate_smiles`); a SMILES given where a name is
expected is canonicalised directly, unless it is also the molecular formula of another
compound ("CO" is methanol as a SMILES, carbon monoxide as a formula): such an entry is
refused as ambiguous (give a name or an explicit SMILES), and ``smiles:CO`` forces the
SMILES reading.
"""

from __future__ import annotations

import re

from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.integrations import cactus, pubchem
from chemeascode.integrations.http import HttpClient, HttpError
from chemeascode.integrations.rdkit import smiles_identity, validate_smiles

from .records import ReactionIdentification

# The elements that are diatomic in their standard state. CACTUS resolves several of these
# names to a wrong species ("oxygen" -> "O", i.e. water; "nitrogen" -> "[NH2]"), so they are
# answered here, before any lookup.
DIATOMIC_ELEMENT_SMILES = {
    "hydrogen": "[H][H]",
    "nitrogen": "N#N",
    "oxygen": "O=O",
    "fluorine": "FF",
    "chlorine": "ClCl",
    "bromine": "BrBr",
    "iodine": "II",
}

# The prefix that makes an entry a SMILES even when it also reads as a formula ("smiles:CO").
SMILES_PREFIX = "smiles:"


def pubchem_name_to_smiles(compound_name: str, *, client: HttpClient | None = None) -> str:
    """The isomeric (else canonical) SMILES of the best PubChem match of *compound_name*.

    Raises ``ValueError`` when PubChem does not know the name or the request fails.
    """
    try:
        cids = pubchem.search_cids(compound_name, "name", max_records=1, client=client)
        if not cids:
            raise ValueError(f"No '{compound_name}' in PubChem")
        found = pubchem.get_properties(
            cids[:1], ("CanonicalSMILES", "IsomericSMILES"), client=client
        )
    except HttpError as failure:
        raise ValueError(f"No '{compound_name}' in PubChem: {failure}") from failure
    smiles = (found[0].isomeric_smiles or found[0].canonical_smiles) if found else None
    if not smiles:
        raise ValueError(f"PubChem returned no SMILES for '{compound_name}'")
    return smiles


def name_to_smiles(compound_name: str, *, client: HttpClient | None = None) -> str:
    """The SMILES of a name, formula, CAS number or other identifier (not canonicalised).

    Raises ``ValueError`` naming both errors when neither PubChem nor CACTUS resolves it.
    """
    diatomic = DIATOMIC_ELEMENT_SMILES.get(compound_name.strip().lower())
    if diatomic is not None:
        return diatomic
    try:
        return pubchem_name_to_smiles(compound_name, client=client)
    except ValueError as pubchem_error:
        try:
            return cactus.name_to_smiles(compound_name, client=client)
        except ValueError as cactus_error:
            raise ValueError(
                f"Could not resolve '{compound_name}': "
                f"PubChem: {pubchem_error}; CACTUS: {cactus_error}"
            ) from cactus_error


def _ambiguous_formula(name: str) -> str | None:
    """The formula of *name* read as a SMILES when *name* is also a molecular formula of
    another compound ("CO": CH4O as a SMILES, carbon monoxide as a formula; "NO", "N", "O",
    "C", "Cl"), else None. Only a formula naming each element once counts: "CCO" is a SMILES,
    not C2O."""
    elements = re.findall(r"[A-Z][a-z]?", name)
    formula = parse_formula(name)
    if formula is None or len(elements) != len(set(elements)):
        return None
    try:
        as_smiles = smiles_identity(name)[1]
    except ValueError:
        return None  # no SMILES: nothing to confuse it with
    return as_smiles if parse_formula(as_smiles) != formula else None


def _resolve_one(name: str, client: HttpClient | None) -> str:
    """The canonical SMILES of one entry (see :func:`resolve_smiles`)."""
    if name.startswith(SMILES_PREFIX):
        smiles = name[len(SMILES_PREFIX) :].strip()
        if not smiles:
            raise ValueError(f"'{name}' gives no SMILES after '{SMILES_PREFIX}'")
        return validate_smiles(smiles)
    as_smiles = _ambiguous_formula(name)
    if as_smiles is not None:
        # Not looked up: PubChem's name search ignores case ("CO" is cobalt, "NO" nobelium).
        raise ValueError(
            f"'{name}' is ambiguous: a molecular formula, but the SMILES of {as_smiles}. Give a "
            f"name (e.g. 'carbon monoxide'), its SMILES (e.g. [C-]#[O+]) or "
            f"'{SMILES_PREFIX}{name}' for the SMILES"
        )
    try:
        return validate_smiles(name)
    except ValueError:
        return validate_smiles(name_to_smiles(name, client=client))


def resolve_smiles(names: list[str], *, client: HttpClient | None = None) -> list[str]:
    """The canonical SMILES of each entry: a valid SMILES directly, anything else looked up.

    An entry that is also the formula of another compound ("CO", "NO", "O", "C") raises
    ``ValueError`` (ambiguous) without a lookup; ``smiles:<SMILES>`` is always taken as a
    SMILES."""
    return [_resolve_one(name, client) for name in names]


def make_smiles(
    reaction: ReactionIdentification, *, client: HttpClient | None = None
) -> ReactionIdentification:
    """*reaction* with ``reactant_smiles``/``product_smiles`` resolved where they are empty."""
    update = {}
    if not reaction.reactant_smiles:
        update["reactant_smiles"] = resolve_smiles(reaction.reactants, client=client)
    if not reaction.product_smiles:
        update["product_smiles"] = resolve_smiles(reaction.products, client=client)
    return reaction.model_copy(update=update)


def reconcile_smiles(
    names: list[str], given_smiles: list[str], *, client: HttpClient | None = None
) -> list[str]:
    """The SMILES of each species, checked against its name.

    For each pair the name's own resolution (:func:`resolve_smiles`) wins over the given
    SMILES when they differ; the given SMILES (canonicalised) is kept when the name does not
    resolve or is ambiguous (a formula that is also another compound's SMILES, such as "CO"),
    and the name's resolution is used when the given SMILES is invalid. A differing molecular
    formula is not required: isomers ("CCO", "COC") share one.

    Raises ``ValueError`` when the lists differ in length, or a species has neither a valid
    SMILES nor a resolvable name.
    """
    if len(names) != len(given_smiles):
        raise ValueError(
            "SMILES list length mismatch: "
            f"got {len(given_smiles)} SMILES for {len(names)} compound names"
        )
    reconciled = []
    for name, smiles in zip(names, given_smiles, strict=True):
        try:
            given = validate_smiles(smiles)
        except ValueError:
            given = None
        if given is not None and _ambiguous_formula(name) is not None:
            reconciled.append(given)
            continue
        try:
            looked_up = _resolve_one(name, client)
        except ValueError:
            looked_up = None
        if given is None and looked_up is None:
            raise ValueError(
                f"Could not resolve a valid SMILES for '{name}': the given SMILES "
                f"'{smiles}' is invalid and the name lookup failed"
            )
        reconciled.append(looked_up if looked_up is not None else given)
    return reconciled


def check_smiles_list(
    reaction: ReactionIdentification, *, client: HttpClient | None = None
) -> ReactionIdentification:
    """*reaction* with every SMILES checked by :func:`reconcile_smiles`."""
    return reaction.model_copy(
        update={
            "reactant_smiles": reconcile_smiles(
                reaction.reactants, reaction.reactant_smiles, client=client
            ),
            "product_smiles": reconcile_smiles(
                reaction.products, reaction.product_smiles, client=client
            ),
        }
    )


def smiles_checker(
    reaction: ReactionIdentification | dict, *, client: HttpClient | None = None
) -> ReactionIdentification:
    """Resolve the missing SMILES of *reaction* (:func:`make_smiles`) and check them all
    (:func:`check_smiles_list`). Returns a new object; *reaction* is not changed."""
    if isinstance(reaction, dict):
        reaction = ReactionIdentification(**reaction)
    return check_smiles_list(make_smiles(reaction, client=client), client=client)
