"""The kinetics records, ported from the schema tests of LLM4ChemE
tests/tools/test_reaction_kinetics.py."""

from __future__ import annotations

from chemeascode.domains.chemistry.kinetics.records import (
    NIST_T_REF,
    RMG_T_REF,
    FilteredKinetics,
    KineticSource,
    NISTKineticsRecord,
    ReactionConditions,
    ReactionIdentification,
    RMGKineticsRecord,
)
from chemeascode.integrations.nist_kinetics import NistKineticsRow
from chemeascode.integrations.rmg import parse_match


def test_reaction_identification_creation():
    rxn = ReactionIdentification(
        reaction_equation="CH3COOH + C2H5OH ⇌ CH3COOC2H5 + H2O",
        reactants=["acetic acid", "ethanol"],
        products=["ethyl acetate", "water"],
        catalyst="H2SO4",
        reversible=True,
        reaction_type="esterification",
        conditions={"temperature": 343.15, "pressure": 1.0, "phase": "liquid"},
    )
    assert rxn.catalyst == "H2SO4"
    assert rxn.reversible is True
    assert len(rxn.reactants) == 2
    assert rxn.reactant_smiles == [] and rxn.product_smiles == []
    assert rxn.conditions == ReactionConditions(temperature=343.15, pressure=1.0, phase="liquid")


def test_nist_record_creation_and_reference_temperature():
    record = NISTKineticsRecord(
        reaction="N2O5 = NO2 + NO3",
        reactants=["O=[N+]([O-])O[N+](=O)[O-]"],
        products=["O=[N+][O-]", "[O]N(=O)=O"],
        A=1.0e13,
        n=0.0,
        Ea=103000.0,
        T_min=200.0,
        T_max=400.0,
        data_type="experimental",
    )
    assert record.Ea == 103000.0
    assert record.T_ref == NIST_T_REF == 298.0


def test_rmg_and_filtered_records_default_to_1_K():
    rmg = RMGKineticsRecord(reaction="A <=> B", reactants=["A"], products=["B"])
    assert rmg.T_ref == RMG_T_REF == 1.0
    assert rmg.reactant_stoichiometry == {}
    assert FilteredKinetics(reaction="A", reactants=[], products=[]).T_ref == 1.0


def test_records_from_adapter_rows():
    row = NistKineticsRow(
        reaction="A -> B",
        reactants=["A"],
        products=["B"],
        A=1.0,
        A_units="s^-1",
        T_ref=298.0,
        n=None,
        Ea=1.0,
        T_min=None,
        T_max=None,
        order=1.0,
        k_298K=None,
        data_type="Experiment",
        reference=None,
        squib="X",
    )
    assert NISTKineticsRecord.from_row(row).squib == "X"
    rmg = RMGKineticsRecord.from_row(parse_match({"reaction": "A <=> B", "Pmin": 1.0}))
    assert rmg.P_range == (1.0, None)
    assert rmg.reactants == []


def test_kinetic_source():
    assert KineticSource(database="NIST Kinetics", Ea_reported=1.0).Ea_reported == 1.0
