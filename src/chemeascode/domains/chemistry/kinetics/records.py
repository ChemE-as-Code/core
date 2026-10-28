"""Records of reaction kinetics: the identified reaction, the records of each source and the
filtered result.

Every source writes the modified Arrhenius expression k(T) = A (T/T_ref)^n exp(-Ea/(R T)) with
its own reference temperature, so two A values are comparable only at the same T_ref:
A(T_ref_new) = A(T_ref_old) (T_ref_new / T_ref_old)^n.

- NIST Chemical Kinetics Database: k = A (T/298 K)^n exp(-Ea/RT), :data:`NIST_T_REF`.
- RMG (Chemkin): k = A T^n exp(-Ea/RT), T_ref = 1 K, :data:`RMG_T_REF`.

A and k are in SI units (mol, m, s; see ``A_units``), Ea in J/mol, temperatures in K,
pressures in bar.
"""

from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel, Field

from chemeascode.integrations.nist_kinetics import NIST_T_REF, NistKineticsRow
from chemeascode.integrations.rmg import RMG_T_REF, RmgKineticsRow

__all__ = [
    "NIST_T_REF",
    "RMG_T_REF",
    "FilteredKinetics",
    "KineticSource",
    "NISTKineticsRecord",
    "RMGKineticsRecord",
    "ReactionConditions",
    "ReactionIdentification",
]


class ReactionConditions(BaseModel):
    """Operating conditions of a reaction."""

    temperature: float | None = Field(default=None, description="Temperature in K")
    pressure: float | None = Field(default=None, description="Pressure in bar")
    phase: str | None = Field(default=None, description="Phase: 'gas', 'liquid', or 'mixed'")
    solvent: str | None = Field(default=None, description="Solvent if applicable")
    notes: str | None = Field(
        default=None, description="Additional conditions, e.g. '1-5 wt% H2SO4, atmospheric'"
    )


class ReactionIdentification(BaseModel):
    """A reaction: its species by name (or SMILES) and, once resolved, by canonical SMILES."""

    reaction_equation: str = Field(
        ..., description="Balanced reaction equation, e.g. 'CH3COOH + C2H5OH ⇌ CH3COOC2H5 + H2O'"
    )
    reactants: list[str] = Field(..., description="Reactant names or SMILES strings")
    products: list[str] = Field(..., description="Product names or SMILES strings")
    catalyst: str | None = Field(default=None, description="Catalyst used, if any")
    reversible: bool = Field(default=False, description="Whether the reaction is reversible")
    reaction_type: str | None = Field(
        default=None,
        description=(
            "Reaction type, e.g. 'esterification', 'hydrogenation', 'oxidation', 'hydrolysis', "
            "'polymerization', 'decomposition'"
        ),
    )
    reactant_smiles: list[str] = Field(
        default_factory=list, description="Canonical SMILES of the reactants (RDKit-validated)"
    )
    product_smiles: list[str] = Field(
        default_factory=list, description="Canonical SMILES of the products (RDKit-validated)"
    )
    conditions: ReactionConditions | None = Field(
        default=None, description="Operating conditions of the reaction"
    )


class KineticSource(BaseModel):
    """Source reference of kinetic data."""

    doi: str | None = Field(default=None, description="DOI of the source paper")
    authors: str | None = Field(default=None, description="Author(s) of the source")
    year: int | None = Field(default=None, description="Publication year")
    journal: str | None = Field(default=None, description="Journal name")
    title: str | None = Field(default=None, description="Paper title")
    database: str | None = Field(
        default=None, description="Database name, e.g. 'NIST Kinetics', 'RMG'"
    )
    Ea_reported: float | None = Field(
        default=None, description="Activation energy as reported by the source, J/mol"
    )
    Ea_units_original: str | None = Field(
        default=None, description="Original units of Ea in the source"
    )
    notes: str | None = Field(default=None, description="Additional notes about this source")


class NISTKineticsRecord(BaseModel):
    """One record of the NIST Chemical Kinetics Database."""

    reaction: str = Field(..., description="Reaction string as reported by NIST")
    reactants: list[str] = Field(..., description="Reactant SMILES (as queried)")
    products: list[str] = Field(..., description="Product SMILES (as queried)")
    A: float | None = Field(
        default=None,
        description=(
            "Pre-exponential factor in SI units (see A_units) of k = A (T/T_ref)^n "
            "exp(-Ea/RT), with T_ref = 298 K as in the NIST database (not the Chemkin/RMG "
            "T_ref = 1 K when n != 0)"
        ),
    )
    A_units: str | None = Field(
        default=None, description="SI units of A and k_298K, e.g. 'm^3/(mol*s)' for order 2"
    )
    T_ref: float = Field(
        default=NIST_T_REF, description="Reference temperature (K) of the (T/T_ref)^n term"
    )
    n: float | None = Field(default=None, description="Temperature exponent")
    Ea: float | None = Field(default=None, description="Activation energy in J/mol")
    T_min: float | None = Field(default=None, description="Minimum temperature in K")
    T_max: float | None = Field(default=None, description="Maximum temperature in K")
    order: float | None = Field(default=None, description="Order of the reaction")
    k_298K: float | None = Field(
        default=None, description="Rate constant at 298 K, in the same SI units as A (A_units)"
    )
    data_type: str | None = Field(
        default=None, description="NIST's section heading, e.g. 'Experiment', 'Review'"
    )
    reference: str | None = Field(default=None, description="Literature reference")
    squib: str | None = Field(default=None, description="NIST squib identifier")

    @classmethod
    def from_row(cls, row: NistKineticsRow) -> NISTKineticsRecord:
        return cls(**asdict(row))


class RMGKineticsRecord(BaseModel):
    """One record of RMG (Reaction Mechanism Generator)."""

    reaction: str = Field(..., description="Reaction string as generated by RMG")
    reactants: list[str] = Field(..., description="Distinct reactant SMILES (no duplicates)")
    products: list[str] = Field(..., description="Distinct product SMILES (no duplicates)")
    reactant_stoichiometry: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Stoichiometric coefficient per distinct reactant SMILES, e.g. {'[H]': 2} for the "
            "self-reaction 2 H -> H2. RMG determines it from its reaction family templates."
        ),
    )
    product_stoichiometry: dict[str, int] = Field(
        default_factory=dict, description="Stoichiometric coefficient per distinct product SMILES"
    )
    family: str | None = Field(
        default=None,
        description="RMG reaction family, e.g. 'H_Abstraction', 'R_Addition_MultipleBond'",
    )
    A: float | None = Field(
        default=None,
        description=(
            "Pre-exponential factor in SI units (see A_units) of k = A (T/T_ref)^n "
            "exp(-Ea/RT), with T_ref = 1 K (Chemkin convention)"
        ),
    )
    A_units: str | None = Field(default=None, description="SI units of A")
    T_ref: float = Field(
        default=RMG_T_REF, description="Reference temperature (K) of the (T/T_ref)^n term"
    )
    n: float | None = Field(default=None, description="Temperature exponent")
    Ea: float | None = Field(default=None, description="Activation energy in J/mol")
    T_min: float | None = Field(default=None, description="Minimum temperature in K")
    T_max: float | None = Field(default=None, description="Maximum temperature in K")
    order: float | None = Field(default=None, description="Order of the reaction")
    P_range: tuple[float | None, float | None] | None = Field(
        default=None, description="Pressure range in bar"
    )
    kinetics_type: str | None = Field(default=None, description="Type of kinetic expression")
    data_type: str | None = Field(
        default=None, description="'rate_rule', 'library', 'training' or 'estimated'"
    )
    source_library: str | None = Field(default=None, description="RMG kinetics library name")
    reference: str | None = Field(default=None, description="Literature reference")
    family_exact_match: bool | None = Field(
        default=None,
        description="True if from an exact rate rule, False if estimated from several rules",
    )

    @classmethod
    def from_row(cls, row: RmgKineticsRow) -> RMGKineticsRecord:
        return cls(**asdict(row))


class FilteredKinetics(BaseModel):
    """The one record :func:`~chemeascode.domains.chemistry.kinetics.filter.filter_kinetics`
    keeps of the NIST and RMG records of a reaction."""

    reaction: str = Field(..., description="Reaction string as reported by NIST or RMG")
    reactants: list[str] = Field(..., description="Reactant SMILES")
    products: list[str] = Field(..., description="Product SMILES")
    reactant_stoichiometry: dict[str, int] = Field(
        default_factory=dict,
        description="Stoichiometric coefficient per reactant SMILES (RMG records; empty for NIST)",
    )
    product_stoichiometry: dict[str, int] = Field(
        default_factory=dict,
        description="Stoichiometric coefficient per product SMILES (RMG records; empty for NIST)",
    )
    A: float | None = Field(
        default=None,
        description=(
            "Pre-exponential factor in SI units (see A_units) of k = A (T/T_ref)^n "
            "exp(-Ea/RT); always at T_ref = 1 K (Chemkin convention), whichever the source"
        ),
    )
    A_units: str | None = Field(
        default=None, description="SI units of A and k_298K, e.g. 'm^3/(mol*s)'"
    )
    T_ref: float = Field(
        default=RMG_T_REF, description="Reference temperature (K) of the (T/T_ref)^n term"
    )
    n: float | None = Field(default=None, description="Temperature exponent")
    Ea: float | None = Field(default=None, description="Activation energy in J/mol")
    T_min: float | None = Field(default=None, description="Minimum temperature in K")
    T_max: float | None = Field(default=None, description="Maximum temperature in K")
    P_range: tuple[float | None, float | None] | None = Field(
        default=None, description="Pressure range in bar"
    )
    order: float | None = Field(default=None, description="Order of the reaction")
    k_298K: float | None = Field(
        default=None, description="Rate constant at 298 K (NIST records only), in A_units"
    )
    kinetics_type: str | None = Field(default=None, description="Type of kinetic expression")
    data_type: str | None = Field(
        default=None, description="'Experiment', 'Theory', 'Estimate', 'Library', 'Family', ..."
    )
    reference: str | None = Field(default=None, description="Literature reference")
    squib: str | None = Field(default=None, description="NIST squib identifier")
    family: str | None = Field(
        default=None,
        description="RMG reaction family, e.g. 'H_Abstraction', 'R_Addition_MultipleBond'",
    )
    source_library: str | None = Field(default=None, description="RMG kinetics library name")
    confidence: str | None = Field(
        default=None, description="'HIGH', 'MEDIUM' or 'LOW': agreement with the other records"
    )
