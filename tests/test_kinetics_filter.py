"""KineticsFilter / filter_kinetics, ported from LLM4ChemE tests/tools/test_kinetics_filter.py
(the DataFrames there are lists of row dicts here). No network; RDKit canonicalises SMILES."""

from __future__ import annotations

import math

import pytest

pytest.importorskip("rdkit")

from chemeascode.domains.chemistry.kinetics.filter import (
    KineticsFilter,
    filter_kinetics,
)
from chemeascode.domains.chemistry.kinetics.records import (
    FilteredKinetics,
    NISTKineticsRecord,
    RMGKineticsRecord,
)


def make_nist(**overrides) -> dict:
    base = {
        "reaction": "A -> B",
        "reactants": ["A"],
        "products": ["B"],
        "A": 1e10,
        "n": None,
        "Ea": 100_000.0,
        "T_min": 300.0,
        "T_max": 1000.0,
        "order": 1.0,
        "k_298K": None,
        "data_type": "Experiment",
        "reference": "ref",
        "squib": "1990ABC",
    }
    base.update(overrides)
    return NISTKineticsRecord(**base).model_dump()


def make_rmg(**overrides) -> dict:
    base = {
        "reaction": "A <=> B",
        "reactants": ["A"],
        "products": ["B"],
        "family": "H_Abstraction",
        "A": 1e13,
        "A_units": "s^-1",
        "n": 0.0,
        "Ea": 100_000.0,
        "T_min": None,
        "T_max": None,
        "order": 1.0,
        "P_range": (None, None),
        "kinetics_type": "Arrhenius",
        "data_type": "training",
        "source_library": None,
        "reference": "matched training reaction",
        "family_exact_match": True,
    }
    base.update(overrides)
    return RMGKineticsRecord(**base).model_dump()


class TestClassifyRow:
    def test_uses_existing_data_type(self):
        row = {"data_type": "Experiment", "source_library": None, "family_exact_match": None}
        assert KineticsFilter.classify_row(row) == "Experiment"

    def test_none_data_type_falls_back_to_library(self):
        """str(None) == 'None' is truthy: None must not be classified as 'None'."""
        row = {"data_type": None, "source_library": "Kinetics Library X"}
        assert KineticsFilter.classify_row(row) == "Library"

    def test_nan_data_type_falls_back_to_family(self):
        row = {"data_type": math.nan, "source_library": "some_lib", "family_exact_match": True}
        assert KineticsFilter.classify_row(row) == "Family"

    def test_empty_string_data_type_falls_back(self):
        row = {"data_type": "", "source_library": "Kinetics Library Y"}
        assert KineticsFilter.classify_row(row) == "Library"

    def test_no_signal_defaults_to_estimate(self):
        row = {"data_type": None, "source_library": None, "family_exact_match": False}
        assert KineticsFilter.classify_row(row) == "Estimate"

    def test_missing_rmg_columns(self):
        assert KineticsFilter.classify_row({"data_type": None}) == "Estimate"


class TestIdentifyDataType:
    def test_classifies_every_row(self):
        rows = [
            {"data_type": "Experiment", "source_library": None},
            {"data_type": None, "source_library": "Kinetics Library Z"},
        ]
        result = KineticsFilter.identify_data_type(rows)
        assert [row["data_type"] for row in result] == ["Experiment", "Library"]
        assert rows[1]["data_type"] is None  # the input is not changed


class TestRemoveDupes:
    def test_removes_exact_duplicate_rows(self):
        rows = [{"A": 1.0, "Ea": 2.0}, {"A": 1.0, "Ea": 2.0}, {"A": 3.0, "Ea": 4.0}]
        assert len(KineticsFilter.remove_dupes(rows)) == 2

    def test_handles_list_valued_columns(self):
        rows = [{"reactants": ["A", "B"], "Ea": 1.0}, {"reactants": ["A", "B"], "Ea": 1.0}]
        result = KineticsFilter.remove_dupes(rows)
        assert len(result) == 1
        assert result[0]["reactants"] == ["A", "B"]

    def test_dict_columns_and_missing_values_compare_equal(self):
        rows = [
            {"stoich": {"a": 1, "b": 2}, "n": None},
            {"stoich": {"b": 2, "a": 1}, "n": math.nan},
            {"stoich": {"a": 1, "b": 2}},
        ]
        assert len(KineticsFilter.remove_dupes(rows)) == 1

    def test_keeps_first_occurrence_in_order(self):
        rows = [{"Ea": 2.0}, {"Ea": 1.0}, {"Ea": 2.0}]
        assert [row["Ea"] for row in KineticsFilter.remove_dupes(rows)] == [2.0, 1.0]


class TestFilterCompleteness:
    def test_keeps_complete_arrhenius_rows(self):
        result = KineticsFilter.filter_completeness([make_nist(A=1e10, Ea=1e5, n=None)])
        assert len(result) == 1
        assert result[0]["kinetics_type"] == "Arrhenius"

    def test_infers_modified_arrhenius_when_n_present(self):
        result = KineticsFilter.filter_completeness([make_nist(A=1e10, Ea=1e5, n=1.5)])
        assert result[0]["kinetics_type"] == "ModifiedArrhenius"

    def test_drops_incomplete_rows(self):
        rows = [make_nist(A=1e10, Ea=1e5), make_nist(A=None, Ea=1e5)]
        assert len(KineticsFilter.filter_completeness(rows)) == 1

    def test_raises_if_nothing_complete(self):
        with pytest.raises(ValueError, match="No complete kinetics"):
            KineticsFilter.filter_completeness([make_nist(A=None, Ea=None)])

    def test_groups_by_kinetics_type_and_drops_unsupported_types(self):
        rows = [
            make_rmg(kinetics_type="ModifiedArrhenius", n=1.0, Ea=1.0),
            make_rmg(kinetics_type="Chebyshev", Ea=2.0),
            make_rmg(kinetics_type="Arrhenius", Ea=3.0),
            make_rmg(kinetics_type="PDepArrhenius", n=1.0, Ea=4.0, P_range=(1.0, 10.0)),
        ]
        result = KineticsFilter.filter_completeness(rows)
        assert [row["Ea"] for row in result] == [3.0, 1.0, 4.0]


class TestNeighborConsistency:
    def test_flags_close_neighbors(self):
        rows = [{"Ea": 100.0}, {"Ea": 200.0}, {"Ea": 101.0}]
        result = KineticsFilter.neighbor_consistency(rows, "Ea", pct=5)
        assert [row["Ea"] for row in result] == [100.0, 101.0, 200.0]
        flags = {row["Ea"]: row["Ea_5_pct"] for row in result}
        assert flags == {100.0: True, 101.0: True, 200.0: False}

    def test_missing_values_sort_last_and_never_agree(self):
        rows = [{"Ea": None}, {"Ea": 100.0}, {"Ea": 100.0}]
        result = KineticsFilter.neighbor_consistency(rows, "Ea", pct=10)
        assert [row["Ea_10_pct"] for row in result] == [True, True, False]
        assert result[-1]["Ea"] is None

    def test_zero_mean_never_agrees(self):
        rows = [{"Ea": 0.0}, {"Ea": 0.0}, {"Ea": 5.0}]  # 0/0 is NaN
        result = KineticsFilter.neighbor_consistency(rows, "Ea", pct=10)
        assert [row["Ea_10_pct"] for row in result] == [False, False, False]
        rows = [{"Ea": -5.0}, {"Ea": 5.0}]  # 10/0 is +inf
        result = KineticsFilter.neighbor_consistency(rows, "Ea", pct=10)
        assert [row["Ea_10_pct"] for row in result] == [False, False]

    def test_negative_neighbours_agree_as_in_pandas(self):
        """The mean in the denominator is signed, so two negative values always agree."""
        rows = [{"Ea": -1000.0}, {"Ea": -100.0}]
        result = KineticsFilter.neighbor_consistency(rows, "Ea", pct=10)
        assert [row["Ea_10_pct"] for row in result] == [True, True]

    def test_sort_is_stable(self):
        rows = [{"Ea": 1.0, "id": "a"}, {"Ea": 0.5, "id": "b"}, {"Ea": 1.0, "id": "c"}]
        result = KineticsFilter.neighbor_consistency(rows, "Ea")
        assert [row["id"] for row in result] == ["b", "a", "c"]


class TestEaConsistency:
    def test_high_confidence_when_within_10_pct(self):
        rows = [make_nist(A=1e10, Ea=100_000.0), make_nist(A=1.02e10, Ea=101_000.0)]
        result = KineticsFilter.ea_consistency(rows)
        assert {row["confidence"] for row in result} == {"HIGH"}
        assert len(result) == 2

    def test_medium_confidence_when_within_30_pct(self):
        rows = [make_nist(A=1e10, Ea=100_000.0), make_nist(A=1.2e10, Ea=120_000.0)]
        result = KineticsFilter.ea_consistency(rows)
        assert {row["confidence"] for row in result} == {"MEDIUM"}

    def test_low_confidence_when_no_agreement(self):
        rows = [make_nist(A=1e10, Ea=50_000.0), make_nist(A=1e5, Ea=500_000.0)]
        result = KineticsFilter.ea_consistency(rows)
        assert {row["confidence"] for row in result} == {"LOW"}
        assert len(result) == 2


class TestDataTypeRank:
    def test_prefers_experiment_over_theory(self):
        result = KineticsFilter.data_type_rank(
            [{"data_type": "Theory"}, {"data_type": "Experiment"}]
        )
        assert [row["data_type"] for row in result] == ["Experiment"]

    def test_returns_unfiltered_if_no_priority_match(self):
        assert len(KineticsFilter.data_type_rank([{"data_type": "SomeUnknownType"}])) == 1


class TestMostNonNa:
    def test_keeps_most_complete_row(self):
        rows = [{"A": 1.0, "Ea": 2.0, "n": None}, {"A": 1.0, "Ea": 2.0, "n": 1.5}]
        result = KineticsFilter.most_non_na(rows)
        assert len(result) == 1
        assert result[0]["n"] == 1.5

    def test_does_not_crash_without_k_298k_column(self):
        assert len(KineticsFilter.most_non_na([{"A": 1.0, "Ea": 2.0}])) == 1

    def test_k_298k_is_not_counted_and_empty_containers_are(self):
        rows = [{"A": 1.0, "k_298K": 5.0, "stoich": None}, {"A": 1.0, "stoich": {}}]
        result = KineticsFilter.most_non_na(rows)
        assert result == [{"A": 1.0, "stoich": {}, "non_na_amount": 2}]


class TestMedianEaComp:
    def test_computes_absolute_distance_from_median(self):
        result = KineticsFilter.median_ea_comp([{"Ea": 90.0}, {"Ea": 110.0}], median=100.0)
        assert [row["MedianEaComp"] for row in result] == [10.0, 10.0]

    def test_median_of_even_count_is_mean_of_middle_two(self):
        assert KineticsFilter.median([1.0, None, 3.0, math.nan, 10.0, 4.0]) == 3.5


class TestKineticsFilterRun:
    def test_prefers_closest_to_median_experiment_value(self):
        rmg_records = [
            RMGKineticsRecord(
                **make_rmg(
                    Ea=203_007.68, A=2.95e9, source_library="Kinetics Library CF2BrCl", data_type=""
                )
            )
        ]
        nist_records = [
            NISTKineticsRecord(**make_nist(Ea=239_000.0, A=2.49e-08)),
            NISTKineticsRecord(**make_nist(Ea=176_000.0, A=1.79e8)),
            NISTKineticsRecord(**make_nist(Ea=167_000.0, A=2.73e8)),
        ]
        result = KineticsFilter(rmg_records, nist_records).run()
        # No two records agree within 30 % on both Ea and A: all LOW; Experiment outranks
        # Library; 176000 is closest to the median of all four Ea.
        assert result.data_type == "Experiment"
        assert result.confidence == "LOW"
        assert result.Ea == 176_000.0

    def test_rmg_only_input_does_not_crash(self):
        assert KineticsFilter([RMGKineticsRecord(**make_rmg())], []).run().Ea == 100_000.0

    def test_nist_only_input_does_not_crash(self):
        assert KineticsFilter([], [NISTKineticsRecord(**make_nist())]).run().Ea == 100_000.0

    def test_both_empty_raises(self):
        with pytest.raises(ValueError, match="No kinetics records provided"):
            KineticsFilter([], []).run()
        with pytest.raises(ValueError, match="No kinetics records provided"):
            KineticsFilter(None, None).run()

    def test_accepts_dict_wrapped_records(self):
        rmg_records = {"rmg_records": [RMGKineticsRecord(**make_rmg())]}
        nist_records = {"nist_records": [NISTKineticsRecord(**make_nist())]}
        assert KineticsFilter(rmg_records, nist_records).run().Ea == 100_000.0

    def test_accepts_plain_dict_records(self):
        assert KineticsFilter([make_rmg()], [make_nist()]).run().Ea == 100_000.0

    def test_result_is_filtered_kinetics(self):
        result = KineticsFilter([RMGKineticsRecord(**make_rmg())], []).run()
        assert isinstance(result, FilteredKinetics)
        assert FilteredKinetics(**result.model_dump()) == result

    def test_nist_result_has_empty_stoichiometry_and_no_pressure_range(self):
        result = KineticsFilter([], [make_nist()]).run()
        assert result.reactant_stoichiometry == {}
        assert result.P_range is None
        assert result.kinetics_type == "Arrhenius"

    def test_equal_distance_tie_goes_to_smaller_A(self):
        """Documented tie-breaking: equal distance to the median, first in ascending-A order."""
        nist = [make_nist(A=2.0e10, Ea=90_000.0), make_nist(A=1.0e10, Ea=110_000.0)]
        result = KineticsFilter([], nist).run()
        assert result.confidence == "LOW"
        assert result.A == 1.0e10

    def test_does_not_change_its_input(self):
        nist = [make_nist(n=1.0)]
        before = [dict(row) for row in nist]
        KineticsFilter([], nist).run()
        assert nist == before


class TestReferenceTemperature:
    """NIST writes k = A (T/298 K)^n exp(-Ea/RT), RMG k = A T^n exp(-Ea/RT): for n != 0 the
    raw A values of the same k(T) differ by 298^n and are put on T_ref = 1 K first."""

    R = 8.314472  # J/(mol K)
    # NIST CH4 + OH -> CH3 + H2O, 2021BUR/MAN023102: A = 3.38e-13 cm3/(molecule s) at 298 K
    NIST_A_SI = 3.38e-13 * 1e-6 * 6.022e23  # m3/(mol s)
    N = 2.23
    EA = 9840.0

    def k(self, A: float, T: float, T_ref: float) -> float:
        return A * (T / T_ref) ** self.N * math.exp(-self.EA / (self.R * T))

    def agreeing_pair(self) -> tuple[dict, dict]:
        nist = make_nist(
            reaction="CH4 + ·OH -> ·CH3 + H2O",
            A=self.NIST_A_SI,
            A_units="m^3/(mol*s)",
            n=self.N,
            Ea=self.EA,
            order=2.0,
        )
        rmg_A = self.k(self.NIST_A_SI, 1000.0, 298.0) / self.k(1.0, 1000.0, 1.0)
        rmg = make_rmg(
            reaction="CH4 + OH <=> CH3 + H2O",
            A=rmg_A,
            A_units="m^3/(mol*s)",
            n=self.N,
            Ea=self.EA,
            order=2.0,
        )
        return nist, rmg

    def test_schema_defaults_encode_source_conventions(self):
        nist, rmg = self.agreeing_pair()
        assert nist["T_ref"] == 298.0
        assert rmg["T_ref"] == 1.0

    def test_agreeing_pair_differs_in_raw_A(self):
        nist, rmg = self.agreeing_pair()
        assert nist["A"] / rmg["A"] == pytest.approx(298.0**self.N)

    def test_normalize_T_ref_rescales_nist_only(self):
        nist, rmg = self.agreeing_pair()
        rows = KineticsFilter.normalize_T_ref([nist, rmg])
        assert rows[0]["A"] == pytest.approx(rmg["A"])
        assert rows[1]["A"] == pytest.approx(rmg["A"])
        assert [row["T_ref"] for row in rows] == [1.0, 1.0]
        assert nist["T_ref"] == 298.0  # the input is not changed

    def test_normalize_T_ref_leaves_plain_arrhenius_unchanged(self):
        rows = KineticsFilter.normalize_T_ref([make_nist(A=1e10, n=None), make_nist(A=2e10, n=0.0)])
        assert [row["A"] for row in rows] == [1e10, 2e10]

    def test_agreeing_pair_is_high_confidence(self):
        nist, rmg = self.agreeing_pair()
        result = KineticsFilter([rmg], [nist]).run()
        assert result.confidence == "HIGH"
        assert result.data_type == "Experiment"

    def test_result_reports_A_at_1K_reproducing_nist_rate(self):
        nist, rmg = self.agreeing_pair()
        result = KineticsFilter([rmg], [nist]).run()
        assert result.T_ref == 1.0
        assert result.A_units == "m^3/(mol*s)"
        for T in (300.0, 1000.0, 2000.0):
            assert self.k(result.A, T, result.T_ref) == pytest.approx(
                self.k(self.NIST_A_SI, T, 298.0)
            )

    def test_records_without_T_ref_field_use_source_default(self):
        nist, rmg = self.agreeing_pair()
        del nist["T_ref"], rmg["T_ref"]
        result = KineticsFilter([rmg], [nist]).run()
        assert result.confidence == "HIGH"
        assert pytest.approx(rmg["A"]) == result.A


class TestSelectReaction:
    """Records of different reactions are never pooled, nor returned for another reaction."""

    CH4_R, CH4_P = ["C", "[OH]"], ["[CH3]", "O"]
    C2H6_R, C2H6_P = ["CC", "[OH]"], ["C[CH2]", "O"]

    def ch4_records(self) -> tuple[list[dict], list[dict]]:
        rmg = [
            make_rmg(
                reaction="CH4 + OH <=> CH3 + H2O",
                reactants=sorted(self.CH4_R),
                products=sorted(self.CH4_P),
                A=1.0e6,
                Ea=20_000.0,
            )
        ]
        # The same species written differently and in another order.
        nist = [
            make_nist(
                reaction="CH4 + ·OH -> ·CH3 + H2O",
                reactants=["[H][O]", "C"],
                products=["O", "[CH3]"],
                A=1.1e6,
                Ea=21_000.0,
            )
        ]
        return rmg, nist

    def c2h6_records(self) -> tuple[list[dict], list[dict]]:
        rmg = [
            make_rmg(
                reaction="C2H6 + OH <=> C2H5 + H2O",
                reactants=sorted(self.C2H6_R),
                products=sorted(self.C2H6_P),
                A=5.0e6,
                Ea=8_000.0,
            )
        ]
        nist = [
            make_nist(
                reaction="C2H6 + ·OH -> ·C2H5 + H2O",
                reactants=self.C2H6_R,
                products=self.C2H6_P,
                A=A,
                Ea=Ea,
            )
            for A, Ea in ((6.0e6, 7_000.0), (9.0e6, 6_000.0))
        ]
        return rmg, nist

    def two_reactions(self) -> tuple[list[dict], list[dict]]:
        ch4_rmg, ch4_nist = self.ch4_records()
        c2h6_rmg, c2h6_nist = self.c2h6_records()
        return ch4_rmg + c2h6_rmg, ch4_nist + c2h6_nist

    def test_two_reactions_retrieved_filter_one(self):
        rmg, nist = self.two_reactions()
        result = filter_kinetics(rmg, nist, self.CH4_R, self.CH4_P)
        assert result.reaction.startswith("CH4")
        assert result.Ea == 21_000.0

    def test_two_reactions_retrieved_filter_other(self):
        rmg, nist = self.two_reactions()
        result = filter_kinetics(rmg, nist, self.C2H6_R)
        assert result.reaction.startswith("C2H6")
        assert result.Ea == 7_000.0
        assert result.confidence == "MEDIUM"

    def test_only_other_reaction_retrieved_raises(self):
        rmg, nist = self.c2h6_records()
        with pytest.raises(ValueError, match="None of the retrieved kinetics records"):
            filter_kinetics(rmg, nist, self.CH4_R, self.CH4_P)

    def test_requested_reaction_not_retrieved_raises(self):
        rmg, nist = self.two_reactions()
        with pytest.raises(ValueError, match="retrieve kinetics for that reaction"):
            filter_kinetics(rmg, nist, ["CCC", "[OH]"])

    def test_mixed_reactions_without_selection_raise(self):
        rmg, nist = self.two_reactions()
        with pytest.raises(ValueError, match="more than one reaction"):
            KineticsFilter(rmg, nist).run()

    def test_different_product_channels_are_not_pooled(self):
        rmg = [
            make_rmg(reactants=["C", "[OH]"], products=["[CH3]", "O"], Ea=1.0),
            make_rmg(reactants=["C", "[OH]"], products=["CO", "[H]"], Ea=2.0),
        ]
        with pytest.raises(ValueError, match="more than one reaction"):
            filter_kinetics(rmg, [], ["C", "[OH]"])
        assert filter_kinetics(rmg, [], ["C", "[OH]"], ["CO", "[H]"]).Ea == 2.0

    def nist_without_products(self, reaction: str, Ea: float) -> dict:
        return make_nist(reaction=reaction, reactants=["C", "[OH]"], products=[], Ea=Ea)

    def test_record_without_products_not_used_for_requested_products(self):
        rmg = [
            make_rmg(reactants=["C", "[OH]"], products=["[CH3]", "O"], Ea=1.0),
            make_rmg(reactants=["C", "[OH]"], products=["CO", "[H]"], Ea=2.0),
        ]
        nist = [self.nist_without_products("CH4 + ·OH -> CH3OH + H", Ea=3.0)]
        result = filter_kinetics(rmg, nist, ["C", "[OH]"], ["[CH3]", "O"])
        assert result.Ea == 1.0
        assert result.data_type != "Experiment"

    def test_only_records_without_products_for_requested_products_raise(self):
        nist = [self.nist_without_products("CH4 + ·OH -> ·CH3 + H2O", Ea=1.0)]
        with pytest.raises(ValueError, match="retrieve kinetics with the product"):
            filter_kinetics([], nist, ["C", "[OH]"], ["[CH3]", "O"])

    def test_records_without_products_of_different_channels_are_not_pooled(self):
        nist = [
            self.nist_without_products("CH4 + ·OH -> ·CH3 + H2O", Ea=1.0),
            self.nist_without_products("CH4 + ·OH -> CH3OH + H", Ea=2.0),
        ]
        with pytest.raises(ValueError, match="more than one reaction") as error:
            filter_kinetics([], nist, ["C", "[OH]"])
        assert "CH3OH + H" in str(error.value)

    def test_record_without_products_not_pooled_with_known_channel(self):
        rmg = [make_rmg(reactants=["C", "[OH]"], products=["[CH3]", "O"])]
        nist = [self.nist_without_products("CH4 + ·OH -> CH3OH + H", Ea=2.0)]
        with pytest.raises(ValueError, match="more than one reaction"):
            filter_kinetics(rmg, nist, ["C", "[OH]"])

    def test_records_without_products_of_one_channel_are_pooled(self):
        nist = [
            self.nist_without_products("CH4 + ·OH -> ·CH3 + H2O", Ea=Ea) for Ea in (1.0, 1.05, 5.0)
        ]
        assert filter_kinetics([], nist, ["C", "[OH]"]).Ea in (1.0, 1.05)

    @pytest.mark.parametrize("reactant_smiles", [["C.[OH]"], ["[OH].C"], "C.[OH]", ["C", "[OH]"]])
    def test_dot_separated_smiles_are_split_into_species(self, reactant_smiles):
        rmg, nist = self.ch4_records()
        result = filter_kinetics(rmg, nist, reactant_smiles, ["O.[CH3]"])
        assert result.reaction.startswith("CH4")

    def test_species_key_splits_dot_separated_smiles(self):
        assert KineticsFilter._species_key(["C.[OH]"]) == frozenset({"C", "[OH]"})
        assert KineticsFilter._species_key(["C.[OH]", "C"]) == frozenset({"C", "[OH]"})
        assert KineticsFilter._species_key(None) == frozenset()
        assert KineticsFilter._species_key(math.nan) == frozenset()


class TestFilterKineticsFunction:
    def test_delegates_to_kinetics_filter_class(self):
        records = [RMGKineticsRecord(**make_rmg())]
        result = filter_kinetics(records, [], ["A"])
        assert result == KineticsFilter(records, [], reactant_smiles=["A"]).run()

    @pytest.mark.parametrize("reactant_smiles", [[], [""], ["  "], [" . "], ""])
    def test_empty_reactant_smiles_raises(self, reactant_smiles):
        with pytest.raises(ValueError, match="reactant_smiles must name the reaction"):
            filter_kinetics([make_rmg()], [], reactant_smiles)

    def test_no_records_raises(self):
        with pytest.raises(ValueError, match="No kinetics records provided"):
            filter_kinetics([], None, ["A"])

    def test_missing_source_behaves_like_empty_list(self):
        assert filter_kinetics([RMGKineticsRecord(**make_rmg())], None, ["A"]).Ea == 100_000.0

    def test_nist_only_records_without_data_type(self):
        nist = [NISTKineticsRecord(**make_nist(data_type=None))]
        assert filter_kinetics([], nist, ["A"]).data_type == "Estimate"
