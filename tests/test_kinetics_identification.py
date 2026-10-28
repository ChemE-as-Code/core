"""Reaction identification, ported from LLM4ChemE tests/tools/test_reaction_identifier.py:
PubChem and CACTUS are a fake transport answering as they did when the tests were written."""

from __future__ import annotations

import json
import os
import urllib.parse

import pytest

pytest.importorskip("rdkit")

from chemeascode.domains.chemistry.kinetics.identification import (
    check_smiles_list,
    make_smiles,
    name_to_smiles,
    reconcile_smiles,
    resolve_smiles,
    smiles_checker,
)
from chemeascode.domains.chemistry.kinetics.records import ReactionIdentification
from chemeascode.integrations.cactus import CACTUS_BASE_URL
from chemeascode.integrations.http import HttpClient, Request, Response
from chemeascode.integrations.pubchem import PUBCHEM_BASE

# name -> (CID, SMILES) as PubChem answers.
PUBCHEM = {
    "ethanol": (702, "CCO"),
    "acetic acid": (176, "CC(=O)O"),
    "ethyl acetate": (8857, "CCOC(=O)C"),
    "water": (962, "O"),
    "methane": (297, "C"),
    "carbon dioxide": (280, "C(=O)=O"),
    "carbon monoxide": (281, "[C-]#[O+]"),
    "cobalt": (104730, "[Co]"),
}
# PubChem's name search ignores case: "CO" finds cobalt, "NO" nobelium.
PUBCHEM_SYNONYMS = {"co": "cobalt"}
CACTUS = {"H2O": "O", "N2O5": "O=[N+]([O-])O[N+](=O)[O-]"}
UNKNOWN = "totallymadeupchemicalxyz123notreal"


class FakeResolvers:
    def __init__(self, pubchem_down: bool = False) -> None:
        self.pubchem_down = pubchem_down
        self.urls: list[str] = []

    def __call__(self, request: Request) -> Response:
        self.urls.append(request.url)
        url = request.url
        if url.startswith(PUBCHEM_BASE):
            if self.pubchem_down:
                return Response(500, "", url)
            if "/compound/name/cids/" in url:
                name = urllib.parse.parse_qs(request.body.decode())["name"][0].lower()
                name = PUBCHEM_SYNONYMS.get(name, name)
                if name not in PUBCHEM:
                    return Response(404, '{"Fault": {}}', url)
                return Response(
                    200, json.dumps({"IdentifierList": {"CID": [PUBCHEM[name][0]]}}), url
                )
            cid = int(url.split("/compound/cid/")[1].split("/")[0])
            smiles = next(s for c, s in PUBCHEM.values() if c == cid)
            row = {"CID": cid, "SMILES": smiles, "ConnectivitySMILES": smiles}
            return Response(200, json.dumps({"PropertyTable": {"Properties": [row]}}), url)
        if url.startswith(CACTUS_BASE_URL):
            name = urllib.parse.unquote(url[len(CACTUS_BASE_URL) :].rsplit("/SMILES", 1)[0])
            if name in CACTUS:
                return Response(200, CACTUS[name] + "\n", url)
            return Response(404, "<h1>Page not found (404)</h1>", url)
        raise AssertionError(f"unexpected request {url}")

    def asked(self, service: str) -> bool:
        return any(url.startswith(service) for url in self.urls)


@pytest.fixture
def fake() -> FakeResolvers:
    return FakeResolvers()


def client(fake) -> HttpClient:
    return HttpClient(transport=fake, sleep=lambda _: None)


class TestNameToSmiles:
    def test_known_compound(self, fake):
        assert name_to_smiles("ethanol", client=client(fake)) == "CCO"
        assert not fake.asked(CACTUS_BASE_URL)

    def test_formula_falls_back_to_cactus(self, fake):
        assert name_to_smiles("N2O5", client=client(fake)) == "O=[N+]([O-])O[N+](=O)[O-]"
        assert fake.asked(PUBCHEM_BASE) and fake.asked(CACTUS_BASE_URL)

    def test_pubchem_failure_falls_back_to_cactus(self):
        fake = FakeResolvers(pubchem_down=True)
        assert name_to_smiles("H2O", client=client(fake)) == "O"

    def test_unknown_compound_names_both_sources(self, fake):
        with pytest.raises(ValueError, match=f"{UNKNOWN}.*PubChem.*CACTUS"):
            name_to_smiles(UNKNOWN, client=client(fake))

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("hydrogen", "[H][H]"),
            ("nitrogen", "N#N"),
            ("oxygen", "O=O"),
            ("fluorine", "FF"),
            ("chlorine", "ClCl"),
            ("bromine", "BrBr"),
            ("iodine", "II"),
            ("  Oxygen  ", "O=O"),
        ],
    )
    def test_diatomic_elements_without_any_request(self, fake, name, expected):
        assert name_to_smiles(name, client=client(fake)) == expected
        assert fake.urls == []


class TestMakeSmiles:
    def test_fills_missing_smiles(self, fake):
        rxn = ReactionIdentification(
            reaction_equation="CH3COOH + C2H5OH -> CH3COOC2H5 + H2O",
            reactants=["acetic acid", "ethanol"],
            products=["ethyl acetate", "water"],
        )
        result = make_smiles(rxn, client=client(fake))
        assert result.reactant_smiles == ["CC(=O)O", "CCO"]
        assert result.product_smiles == ["CCOC(C)=O", "O"]
        assert rxn.reactant_smiles == []  # the input is not changed

    def test_does_not_overwrite_existing_reactant_smiles(self, fake):
        rxn = ReactionIdentification(
            reaction_equation="A -> B",
            reactants=["ethanol"],
            products=["water"],
            reactant_smiles=["XX"],
        )
        result = make_smiles(rxn, client=client(fake))
        assert result.reactant_smiles == ["XX"]
        assert result.product_smiles == ["O"]

    def test_raises_for_unresolvable_reactant(self, fake):
        rxn = ReactionIdentification(reaction_equation="A -> B", reactants=[UNKNOWN], products=[])
        with pytest.raises(ValueError):
            make_smiles(rxn, client=client(fake))

    def test_handles_smiles_given_in_name_field(self, fake):
        rxn = ReactionIdentification(
            reaction_equation="H2 + O2 -> HO2 + H",
            reactants=["[H][H]", "O=O"],
            products=["[O]O", "[H]"],
        )
        result = make_smiles(rxn, client=client(fake))
        assert result.reactant_smiles == ["[H][H]", "O=O"]
        assert result.product_smiles == ["[O]O", "[H]"]
        assert fake.urls == []


def reaction(reactant_smiles, reactants=("ethanol",)) -> ReactionIdentification:
    return ReactionIdentification(
        reaction_equation="A -> B",
        reactants=list(reactants),
        products=["water"],
        reactant_smiles=reactant_smiles,
        product_smiles=["O"],
    )


class TestCheckSmilesList:
    def test_canonicalizes_matching_smiles(self, fake):
        result = check_smiles_list(reaction(["OCC"]), client=client(fake))
        assert result.reactant_smiles == ["CCO"]
        assert result.product_smiles == ["O"]

    def test_corrects_wrong_smiles(self, fake):
        assert check_smiles_list(reaction(["CC"]), client=client(fake)).reactant_smiles == ["CCO"]

    def test_corrects_wrong_smiles_same_formula_isomer(self, fake):
        """Dimethyl ether and ethanol share C2H6O: the formula does not tell them apart."""
        assert check_smiles_list(reaction(["COC"]), client=client(fake)).reactant_smiles == ["CCO"]

    def test_falls_back_for_unresolvable_name(self, fake):
        result = check_smiles_list(reaction(["CCO"], [UNKNOWN]), client=client(fake))
        assert result.reactant_smiles == ["CCO"]

    def test_falls_back_to_lookup_for_invalid_smiles(self, fake):
        result = check_smiles_list(reaction(["not_a_smiles("]), client=client(fake))
        assert result.reactant_smiles == ["CCO"]

    def test_raises_when_neither_smiles_nor_name_resolve(self, fake):
        with pytest.raises(ValueError, match="Could not resolve a valid SMILES"):
            check_smiles_list(reaction(["not_a_smiles("], [UNKNOWN]), client=client(fake))

    def test_length_mismatch_raises(self, fake):
        with pytest.raises(ValueError, match="length mismatch"):
            check_smiles_list(reaction(["CCO", "O"]), client=client(fake))


class TestSmilesChecker:
    def test_with_model_input(self, fake):
        rxn = ReactionIdentification(
            reaction_equation="CH3COOH + C2H5OH -> CH3COOC2H5 + H2O",
            reactants=["acetic acid", "ethanol"],
            products=["ethyl acetate", "water"],
        )
        result = smiles_checker(rxn, client=client(fake))
        assert isinstance(result, ReactionIdentification)
        assert result.reactant_smiles == ["CC(=O)O", "CCO"]
        assert result.product_smiles == ["CCOC(C)=O", "O"]

    def test_with_dict_input(self, fake):
        result = smiles_checker(
            {
                "reaction_equation": "CH4 + 2O2 -> CO2 + 2H2O",
                "reactants": ["methane", "oxygen"],
                "products": ["carbon dioxide", "water"],
            },
            client=client(fake),
        )
        assert result.reactant_smiles == ["C", "O=O"]
        assert result.product_smiles == ["O=C=O", "O"]

    def test_diatomic_species_given_as_smiles_in_name_field(self, fake):
        result = smiles_checker(
            {
                "reaction_equation": "H2 + O2 -> HO2 + H",
                "reactants": ["[H][H]", "O=O"],
                "products": ["[O]O", "[H]"],
                "catalyst": None,
                "reversible": False,
                "reaction_type": None,
            },
            client=client(fake),
        )
        assert result.reactant_smiles == ["[H][H]", "O=O"]
        assert result.product_smiles == ["[O]O", "[H]"]

    def test_idempotent_on_already_checked_reaction(self, fake):
        rxn = ReactionIdentification(
            reaction_equation="A -> B", reactants=["ethanol"], products=["water"]
        )
        once = smiles_checker(rxn, client=client(fake))
        twice = smiles_checker(once, client=client(fake))
        assert (once.reactant_smiles, once.product_smiles) == (
            twice.reactant_smiles,
            twice.product_smiles,
        )


class TestFormulasThatAreAlsoSmiles:
    """pre-release issue 198: "CO" parses as the SMILES of methanol, "NO" of hydroxylamine, "O" of
    water, "C" of methane; as entries they may be formulas (carbon monoxide, nitric oxide, atomic
    oxygen and carbon). They are refused without a lookup: PubChem's name search ignores case
    and answers cobalt for "CO"."""

    @pytest.mark.parametrize("name", ["CO", "NO", "O", "C", "N", "Cl", "CN"])
    def test_an_ambiguous_formula_is_refused_without_a_lookup(self, fake, name):
        with pytest.raises(ValueError, match=f"'{name}' is ambiguous.*smiles:{name}"):
            resolve_smiles([name], client=client(fake))
        assert fake.urls == []

    def test_the_name_resolves_carbon_monoxide(self, fake):
        assert resolve_smiles(["carbon monoxide"], client=client(fake)) == ["[C-]#[O+]"]

    def test_the_fake_pubchem_ignores_case_like_the_real_one(self, fake):
        assert name_to_smiles("CO", client=client(fake)) == "[Co]"

    def test_the_prefix_forces_the_smiles_reading(self, fake):
        assert resolve_smiles(["smiles:CO", "smiles:O"], client=client(fake)) == ["CO", "O"]
        assert fake.urls == []

    @pytest.mark.parametrize("entry", ["smiles:", "smiles:  "])
    def test_the_prefix_needs_a_smiles(self, fake, entry):
        with pytest.raises(ValueError, match="gives no SMILES"):
            resolve_smiles([entry], client=client(fake))
        assert fake.urls == []

    def test_unambiguous_smiles_are_taken_directly(self, fake):
        smiles = ["CCO", "[OH]", "OCC", "O=O", "[C-]#[O+]", "[N]=O", "[CH4]"]
        assert resolve_smiles(smiles, client=client(fake)) == [
            "CCO",
            "[OH]",
            "CCO",
            "O=O",
            "[C-]#[O+]",
            "[N]=O",
            "C",
        ]
        assert fake.urls == []

    def test_reconcile_keeps_the_given_smiles_of_an_ambiguous_name(self, fake):
        given = ["[C-]#[O+]", "[N]=O", "[O]"]
        assert reconcile_smiles(["CO", "NO", "O"], given, client=client(fake)) == given
        assert fake.urls == []


@pytest.mark.skipif(
    os.environ.get("CHEME_NETWORK_TESTS") != "1", reason="set CHEME_NETWORK_TESTS=1"
)
def test_live_name_to_smiles():
    assert name_to_smiles("ethanol") == "CCO"
    assert name_to_smiles("H2O") == "O"
