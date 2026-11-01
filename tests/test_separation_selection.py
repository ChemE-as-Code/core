"""Separation method selection (ported from LLM4ChemE tests/tools/test_separation_method.py).

Validates the helpers, DSE, the pre-questions, the PI matrix, the core selection, the public
functions and the case studies of Li, Somoza-Tornos & Kiss (2025), CPPM 20(2): 293-307.
"""

from chemeascode.domains.process.separations.selection import (
    PI_MATRIX,
    TERNARY_MATRIX,
    _apply_pi_matrix_binary,
    _compute_cop,
    _compute_dse,
    _delta_tb_band,
    _evaluate_high_level_questions,
    _identify_active_criteria,
    _score_method,
    select_binary_separation_methods,
    select_multicomponent_separation_methods,
    select_separation_methods_core,
)

# ═══════════════════════════════════════════════════════════════════════
#  1. Helper function tests
# ═══════════════════════════════════════════════════════════════════════


class TestDeltaTbBand:
    """Test _delta_tb_band classification."""

    def test_none_returns_unknown(self):
        assert _delta_tb_band(None) == "unknown"

    def test_below_10(self):
        assert _delta_tb_band(0.0) == "dTb_lt_10"
        assert _delta_tb_band(5.0) == "dTb_lt_10"
        assert _delta_tb_band(9.99) == "dTb_lt_10"

    def test_10_to_20(self):
        assert _delta_tb_band(10.0) == "dTb_10_20"
        assert _delta_tb_band(15.0) == "dTb_10_20"
        assert _delta_tb_band(19.99) == "dTb_10_20"

    def test_20_to_60(self):
        assert _delta_tb_band(20.0) == "dTb_20_60"
        assert _delta_tb_band(35.5) == "dTb_20_60"
        assert _delta_tb_band(60.0) == "dTb_20_60"

    def test_above_60(self):
        assert _delta_tb_band(60.1) == "dTb_gt_60"
        assert _delta_tb_band(100.0) == "dTb_gt_60"

    def test_negative(self):
        assert _delta_tb_band(-5.0) == "dTb_lt_10"

    def test_exact_boundaries(self):
        """Verify boundary values match the paper's classification."""
        assert _delta_tb_band(10.0) == "dTb_10_20"  # 10 is in 10-20 range
        assert _delta_tb_band(20.0) == "dTb_20_60"  # 20 is in 20-60 range
        assert _delta_tb_band(60.0) == "dTb_20_60"  # 60 is in 20-60 range (inclusive)


class TestComputeCOP:
    """Test _compute_cop: eta T_hot / (T_hot - T_cold), T_hot = Tb_heavy + 5 K and
    T_cold = Tb_light - 5 K."""

    def test_missing_or_unordered_input(self):
        assert _compute_cop(None, 373.15) is None
        assert _compute_cop(350.0, None) is None
        assert _compute_cop(350.0, 350.0) is None
        assert _compute_cop(373.15, 350.0) is None

    def test_small_delta_tb(self):
        """Small temperature lift -> high COP."""
        cop = _compute_cop(368.15, 373.15)
        assert cop is not None
        assert cop > 10.0  # Very favorable

    def test_large_delta_tb(self):
        """Large temperature lift -> low COP."""
        cop = _compute_cop(300.0, 473.15)
        assert cop is not None
        assert cop < 3.0  # Marginal

    def test_methanol_water_case(self):
        """MeOH/H2O (337.7/373.15 K): 0.7 * 378.15 / 45.45 = 5.82 -> favourable."""
        cop = _compute_cop(337.7, 373.15)
        assert cop == 5.82
        assert cop >= 3.0

    def test_ethanol_water_case(self):
        """EtOH/H2O: dTb=22°C -> COP should be high."""
        cop = _compute_cop(351.15, 373.15)
        assert cop is not None
        assert cop >= 3.0

    def test_the_temperature_level_counts_not_only_the_lift(self):
        """N2/O2 (77.4/90.2 K): 0.7 * 95.2 / 22.8 = 2.92, below the threshold of 3; the same
        12.8 K lift at a high level is favourable: 0.7 * 505 / 22.8 = 15.5."""
        assert _compute_cop(77.4, 90.2) == 2.92
        assert _compute_cop(487.2, 500.0) == 15.5

    def test_custom_efficiency(self):
        """Custom compressor efficiency changes COP proportionally."""
        cop_default = _compute_cop(350.0, 380.0, compressor_efficiency=0.7)
        cop_lower = _compute_cop(350.0, 380.0, compressor_efficiency=0.5)
        assert cop_default is not None
        assert cop_lower is not None
        assert cop_lower < cop_default
        assert abs(cop_lower / cop_default - 0.5 / 0.7) < 0.01


class TestIdentifyActiveCriteria:
    """Test _identify_active_criteria threshold logic."""

    def _call(self, **overrides):
        defaults = {
            "relative_volatility": None,
            "heat_of_vaporization": [],
            "pressure_bar": 1.01325,
            "recovery": 0.9,
            "purity": 0.95,
            "viscosity_cp": [],
            "diffusion_m2s": [],
            "reflux_ratio": 1.5,
        }
        defaults.update(overrides)
        return _identify_active_criteria(**defaults)

    def test_no_criteria_met(self):
        """Default values should trigger no active criteria."""
        assert self._call() == []

    def test_low_relative_volatility(self):
        result = self._call(relative_volatility=1.05)
        assert "RV_1_01_1_15" in result

    def test_rv_outside_range(self):
        assert "RV_1_01_1_15" not in self._call(relative_volatility=1.0)
        assert "RV_1_01_1_15" not in self._call(relative_volatility=1.16)
        assert "RV_1_01_1_15" not in self._call(relative_volatility=2.0)

    def test_high_hvap(self):
        result = self._call(heat_of_vaporization=[30.0, 41.0])
        assert "high_hvap" in result

    def test_hvap_below_threshold(self):
        result = self._call(heat_of_vaporization=[30.0, 39.9])
        assert "high_hvap" not in result

    def test_vacuum_operation(self):
        result = self._call(pressure_bar=0.5)
        assert "vacuum" in result

    def test_atmospheric_not_vacuum(self):
        result = self._call(pressure_bar=1.01325)
        assert "vacuum" not in result

    def test_high_recovery(self):
        result = self._call(recovery=0.9999)
        assert "high_recovery" in result

    def test_normal_recovery(self):
        result = self._call(recovery=0.999)
        assert "high_recovery" not in result

    def test_high_purity(self):
        result = self._call(purity=0.9999)
        assert "high_purity" in result

    def test_high_viscosity(self):
        result = self._call(viscosity_cp=[0.5, 2.5])
        assert "high_viscosity" in result

    def test_low_diffusion(self):
        result = self._call(diffusion_m2s=[1e-9, 4e-10])
        assert "low_diffusion" in result

    def test_high_reflux(self):
        result = self._call(reflux_ratio=2.0)
        assert "high_reflux" in result

    def test_multiple_criteria(self):
        """MeOH/H2O case: high_hvap + high_recovery + high_purity."""
        result = self._call(
            heat_of_vaporization=[40.7, 40.8],
            recovery=0.9998,
            purity=0.9999,
        )
        assert "high_hvap" in result
        assert "high_recovery" in result
        assert "high_purity" in result
        assert len(result) == 3


class TestScoreMethod:
    """Test _score_method scoring logic."""

    def test_all_A_marks(self):
        caps = {"dTb_20_60": "A", "high_hvap": "A"}
        result = _score_method(caps, "dTb_20_60", ["high_hvap"])
        assert result["A_count"] == 2
        assert result["final_score"] == 2.0
        assert result["vetoed"] == "NO"

    def test_mixed_A_B_marks(self):
        caps = {"dTb_20_60": "A", "high_hvap": "B"}
        result = _score_method(caps, "dTb_20_60", ["high_hvap"])
        assert result["A_count"] == 1
        assert result["B_count"] == 1
        assert result["final_score"] == 1.5

    def test_C_mark_vetoes(self):
        caps = {"dTb_lt_10": "C", "high_hvap": "A"}
        result = _score_method(caps, "dTb_lt_10", ["high_hvap"])
        assert result["C_present"] == "YES"
        assert result["vetoed"] == "YES"
        assert result["final_score"] == 0.0
        assert result["raw_score"] == 1.0  # A_count=1, but vetoed

    def test_c_from_criteria_not_band(self):
        caps = {"dTb_20_60": "A", "high_viscosity": "C"}
        result = _score_method(caps, "dTb_20_60", ["high_viscosity"])
        assert result["vetoed"] == "YES"
        assert result["veto_factor"] == "high_viscosity"

    def test_blank_marks_ignored(self):
        caps = {"dTb_20_60": "A", "vacuum": "Blank"}
        result = _score_method(caps, "dTb_20_60", ["vacuum"])
        assert result["A_count"] == 1
        assert result["final_score"] == 1.0

    def test_unknown_band(self):
        caps = {"dTb_20_60": "A"}
        result = _score_method(caps, "unknown", [])
        # Band mark should be Blank when band is unknown
        assert result["mark_details"]["deltaTb_band"] == "Blank"

    def test_no_active_criteria(self):
        caps = {"dTb_20_60": "B"}
        result = _score_method(caps, "dTb_20_60", [])
        assert result["B_count"] == 1
        assert result["final_score"] == 0.5


# ═══════════════════════════════════════════════════════════════════════
#  2. DSE calculation tests
# ═══════════════════════════════════════════════════════════════════════


class TestComputeDSE:
    """Test _compute_dse with Plesu's bottoms=1 convention."""

    def test_insufficient_components(self):
        result = _compute_dse([300, 350], [0.5, 0.5])
        assert "error" in result

    def test_direct_btx(self):
        """BTX direct: paper expects ~38.33%, ranking direct > indirect."""
        result = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="direct",
        )
        assert "DSE" in result
        dse = result["DSE"]
        # Should be ~40.27% with full spread Kelvin (paper 38.33%)
        assert 0.35 < dse < 0.45, f"DSE direct={dse}, expected ~0.40"

    def test_indirect_btx(self):
        """BTX indirect: should be lower than direct."""
        result = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="indirect",
        )
        dse = result["DSE"]
        assert 0.33 < dse < 0.42, f"DSE indirect={dse}, expected ~0.38"

    def test_direct_greater_than_indirect_btx(self):
        """Critical: direct sequence must be preferred for BTX per paper."""
        direct = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="direct",
        )
        indirect = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="indirect",
        )
        assert direct["DSE"] > indirect["DSE"], (
            f"Direct DSE ({direct['DSE']}) should be > indirect ({indirect['DSE']})"
        )

    def test_bottoms_product_gets_efficiency_1(self):
        """Verify heaviest product (bottoms in both columns) gets DSE close to its mole fraction."""
        # For direct: C is bottoms of both columns -> factor = 1
        # Its contribution to DSE = x_C * 1.0 = x_C
        T_A, T_B, T_C = 300.0, 400.0, 500.0  # wide spread in Kelvin
        x_A, x_B, x_C = 0.2, 0.3, 0.5
        result = _compute_dse([T_A, T_B, T_C], [x_A, x_B, x_C], "direct")
        dse = result["DSE"]
        # C contributes x_C * 1.0 = 0.5
        # A contributes x_A * eta_1, B contributes x_B * eta_2
        # DSE must be > x_C = 0.5
        assert dse > x_C

    def test_column_efficiencies_returned(self):
        result = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="direct",
        )
        assert "column_efficiencies" in result
        assert "column_1_A_(B+C)" in result["column_efficiencies"]
        assert "column_2_B_C" in result["column_efficiencies"]

    def test_dse_percent_format(self):
        result = _compute_dse(
            [353.25, 383.85, 411.55],
            [0.333, 0.334, 0.333],
            sequence="direct",
        )
        assert "DSE_percent" in result
        assert "%" in result["DSE_percent"]

    def test_sorting_invariant(self):
        """Component order shouldn't matter — sorted internally."""
        r1 = _compute_dse([411.55, 353.25, 383.85], [0.333, 0.333, 0.334], "direct")
        r2 = _compute_dse([353.25, 383.85, 411.55], [0.333, 0.334, 0.333], "direct")
        assert abs(r1["DSE"] - r2["DSE"]) < 0.001

    def test_equal_boiling_points(self):
        """Edge case: equal boiling points -> eta=0 for those columns."""
        result = _compute_dse([350.0, 350.0, 400.0], [0.333, 0.334, 0.333], "direct")
        assert result["DSE"] is not None


# ═══════════════════════════════════════════════════════════════════════
#  3. High-level questions tests
# ═══════════════════════════════════════════════════════════════════════


class TestHighLevelQuestions:
    """Test _evaluate_high_level_questions."""

    def _call(self, **overrides):
        defaults = {
            "number_of_products": 2,
            "azeotrope": False,
            "pressure_sensitive_azeotrope": False,
            "has_solidification_risk": False,
            "has_non_condensable": False,
            "has_thermosensitive": False,
            "large_light_fraction": False,
            "large_heavy_fraction": False,
            "boiling_point_diff": 35.0,
        }
        defaults.update(overrides)
        return _evaluate_high_level_questions(**defaults)

    def test_all_no(self):
        """All questions NO -> proceed to PI matrix."""
        result = self._call()
        assert result["resolved"] is False
        assert result["resolved_by"] is None
        assert result["pre_recommendations"] == []
        qs = result["questions_evaluated"]
        assert len(qs) >= 6  # Q1-Q6 all recorded
        assert all(q.get("answer") == "NO" for q in qs if "answer" in q)

    def test_solidification_risk(self):
        result = self._call(has_solidification_risk=True)
        assert result["resolved"] is True
        assert result["resolved_by"] == "Q1"
        qs = result["questions_evaluated"]
        assert any("Q1" in q for q in qs)
        recs = result["pre_recommendations"]
        assert any("Crystallization" in r.get("R1", "") for r in recs)
        assert len(result["recommended_methods"]) > 0

    def test_non_condensable(self):
        result = self._call(has_non_condensable=True)
        assert result["resolved"] is True
        assert result["resolved_by"] == "Q2"
        qs = result["questions_evaluated"]
        assert any("Q2" in q for q in qs)
        recs = result["pre_recommendations"]
        assert any("Membrane" in r.get("R2", "") for r in recs)
        assert len(result["recommended_methods"]) > 0

    def test_thermosensitive(self):
        result = self._call(has_thermosensitive=True)
        assert result["resolved"] is True  # Q3 is resolving
        assert result["resolved_by"] == "Q3"
        methods = [m["method"] for m in result["recommended_methods"]]
        assert any("vacuum" in m.lower() or "Vacuum" in m for m in methods)

    def test_large_light_fraction(self):
        result = self._call(large_light_fraction=True)
        assert result["resolved"] is True  # Q4 is resolving
        assert result["resolved_by"] == "Q4"
        qs = result["questions_evaluated"]
        assert any("Q4" in q for q in qs)
        methods = [m["method"] for m in result["recommended_methods"]]
        assert any("MAD" in m for m in methods)

    def test_large_heavy_fraction(self):
        result = self._call(large_heavy_fraction=True)
        assert result["resolved"] is True  # Q5 is resolving
        assert result["resolved_by"] == "Q5"
        qs = result["questions_evaluated"]
        assert any("Q5" in q for q in qs)
        methods = [m["method"] for m in result["recommended_methods"]]
        assert any("stripping" in m.lower() for m in methods)

    def test_azeotrope_pressure_sensitive(self):
        result = self._call(azeotrope=True, pressure_sensitive_azeotrope=True)
        assert result["resolved"] is True
        assert result["resolved_by"] == "Q6"
        qs = result["questions_evaluated"]
        assert any("Q6" in q for q in qs)
        recs = result["pre_recommendations"]
        rec_text = " ".join(str(r) for r in recs)
        assert "PSD" in rec_text
        method_names = {m["method"] for m in result["recommended_methods"]}
        assert "PSD" in method_names

    def test_azeotrope_not_pressure_sensitive(self):
        result = self._call(azeotrope=True, pressure_sensitive_azeotrope=False)
        assert result["resolved"] is True
        assert result["resolved_by"] == "Q6"
        recs = result["pre_recommendations"]
        rec_text = " ".join(str(r) for r in recs)
        assert "PSD not recommended" in rec_text
        method_names = {m["method"] for m in result["recommended_methods"]}
        assert "PSD" not in method_names

    def test_ternary_products(self):
        result = self._call(number_of_products=3, middle_key_fraction=0.35)
        qs = result["questions_evaluated"]
        assert any("Q+" in q for q in qs)
        recs = result["pre_recommendations"]
        rec_text = " ".join(str(r) for r in recs)
        assert "DWC" in rec_text


# ═══════════════════════════════════════════════════════════════════════
#  4. PI matrix application tests
# ═══════════════════════════════════════════════════════════════════════


class TestApplyPIMatrixBinary:
    """Test _apply_pi_matrix_binary."""

    def test_returns_all_methods(self):
        """All PI_MATRIX methods should appear in results."""
        result = _apply_pi_matrix_binary(
            boiling_point_diff=30.0,
            relative_volatility=2.0,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
        )
        method_names = {m["method"] for m in result["per_method_scores"]}
        for expected in PI_MATRIX:
            assert expected in method_names, f"{expected} missing from PI matrix results"

    def test_exclude_methods(self):
        result = _apply_pi_matrix_binary(
            boiling_point_diff=30.0,
            relative_volatility=2.0,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
            exclude_methods=["HIDiC", "CyDist"],
        )
        for m in result["per_method_scores"]:
            if m["method"] in ("HIDiC", "CyDist"):
                assert m["vetoed"] == "YES"
                assert m["veto_factor"] == "excluded_by_high_level_question"

    def test_cop_check_in_20_60_band(self):
        """HPAD/HIDiC in 20-60°C band should include COP analysis."""
        result = _apply_pi_matrix_binary(
            boiling_point_diff=35.0,
            relative_volatility=2.0,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
            boiling_points_K=[350.0, 385.0],
        )
        for m in result["per_method_scores"]:
            if m["method"] in ("HPAD", "HIDiC"):
                assert "COP_estimated" in m, f"{m['method']} missing COP in 20-60 band"
                assert "COP_recommendation" in m

    def test_a_cryogenic_split_is_not_favourable(self):
        """The COP follows the split's own temperatures: N2/O2 is marginal, and
        without the boiling points the COP is not computed rather than guessed."""
        kwargs = dict(
            relative_volatility=2.0,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
        )
        # a 25 K split (the 20-60 band, where the COP is checked) near 80 K
        result = _apply_pi_matrix_binary(25.0, boiling_points_K=[77.4, 102.4], **kwargs)
        hpad = next(m for m in result["per_method_scores"] if m["method"] == "HPAD")
        assert hpad["COP_estimated"] == round(0.7 * 107.4 / 35.0, 2)
        assert hpad["COP_recommendation"] == "MARGINAL"
        result = _apply_pi_matrix_binary(25.0, **kwargs)
        hpad = next(m for m in result["per_method_scores"] if m["method"] == "HPAD")
        assert "COP_estimated" not in hpad
        assert hpad["COP_recommendation"] == "UNABLE_TO_COMPUTE"

    def test_no_cop_in_lt_10_band(self):
        """HPAD/HIDiC in <10°C band: recommended directly, no COP check needed."""
        result = _apply_pi_matrix_binary(
            boiling_point_diff=5.0,
            relative_volatility=1.1,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
        )
        for m in result["per_method_scores"]:
            if m["method"] in ("HPAD", "HIDiC"):
                assert "COP_estimated" not in m

    def test_ranked_methods_excludes_vetoed(self):
        result = _apply_pi_matrix_binary(
            boiling_point_diff=5.0,
            relative_volatility=1.05,
            heat_of_vaporization=[],
            pressure=1.01325,
            recovery=0.9,
            purity=0.95,
            viscosity=[],
            diffusion_coefficient=[],
            reflux_ratio=1.5,
        )
        for m in result["ranked_methods"]:
            assert m["final_score"] > 0


# ═══════════════════════════════════════════════════════════════════════
#  5. Core selection logic tests
# ═══════════════════════════════════════════════════════════════════════


class TestSelectSeparationMethodsCore:
    """Test select_separation_methods_core for different system types."""

    def test_binary_zeotrope(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=False,
            boiling_points_K=[350.0, 380.0],
            relative_volatilities=2.0,
        )
        assert result.system_class == "binary_zeotrope"
        assert len(result.ranked_methods) > 0

    def test_binary_azeotrope_excludes_conv_dist(self):
        """Azeotropic: ConvDist, CyDist, HiGee must NOT appear in ranked methods."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=False,
            boiling_points_K=[350.0, 372.0],
            relative_volatilities=1.5,
        )
        assert result.system_class == "binary_azeotrope"
        method_names = {m["method"] for m in result.ranked_methods}
        assert "ConvDist" not in method_names, "ConvDist should not appear for azeotropic"
        assert "CyDist" not in method_names, "CyDist should not appear for azeotropic"
        assert "HiGee" not in method_names, "HiGee should not appear for azeotropic"

    def test_binary_azeotrope_includes_breaking_methods(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=True,
            boiling_points_K=[350.0, 372.0],
            relative_volatilities=1.5,
        )
        method_names = {m["method"] for m in result.ranked_methods}
        assert "PSD" in method_names
        assert "E-DWC" in method_names
        assert "A-DWC" in method_names
        assert "ED/AD" in method_names

    def test_binary_azeotrope_psd_excluded_when_not_pressure_sensitive(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=False,
            boiling_points_K=[350.0, 372.0],
            relative_volatilities=1.5,
        )
        method_names = {m["method"] for m in result.ranked_methods}
        assert "PSD" not in method_names

    def test_ternary_system_class(self):
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.0, 2.0],
            boiling_points_K=[353.0, 384.0, 412.0],
            molar_fractions=[0.333, 0.334, 0.333],
        )
        assert "ternary" in result.system_class

    def test_ternary_includes_dwc_tcd(self):
        result = select_separation_methods_core(
            number_of_products=3,
            boiling_points_K=[353.0, 384.0, 412.0],
            relative_volatilities=[2.0, 2.0],
            middle_key_fraction=0.35,
            high_purity_middle=True,
        )
        method_names = []
        for rank_entry in result.ranked_methods:
            for entry in rank_entry["methods"]:
                method_names.append(entry["method"])
        assert "DWC" in method_names or "TCD" in method_names

    def test_ternary_dse_analysis_present(self):
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.0, 2.0],
            boiling_points_K=[353.0, 384.0, 412.0],
            molar_fractions=[0.333, 0.334, 0.333],
        )
        dse = result.dse_analysis
        assert dse is not None
        assert "direct_sequence" in dse
        assert "indirect_sequence" in dse

    def test_thermosensitive_resolves_at_prescreen(self):
        """Q3 thermosensitive resolves at pre-screen; PI matrix not evaluated."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=False,
            boiling_points_K=[350.0, 380.0],
            relative_volatilities=2.0,
            has_thermosensitive=True,
        )
        assert result.high_level_assessment["resolved"] is True
        assert result.high_level_assessment["resolved_by"] == "Q3"
        method_names = [m["method"] for m in result.ranked_methods]
        assert any("vacuum" in m.lower() or "Vacuum" in m for m in method_names)
        # HIDiC and CyDist should not appear
        for m in result.ranked_methods:
            assert m["method"] not in ("HIDiC", "CyDist"), (
                f"{m['method']} should not appear for thermosensitive"
            )

    def test_invalid_products_raises(self):
        try:
            select_separation_methods_core(number_of_products=1, boiling_points_K=[350.0, 380.0])
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_invalid_recovery_raises(self):
        try:
            select_separation_methods_core(
                number_of_products=2, boiling_points_K=[350.0, 380.0], recovery=1.5
            )
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass

    def test_missing_boiling_points_raises(self):
        try:
            select_separation_methods_core(number_of_products=2)
            raise AssertionError("Should have raised ValueError")
        except ValueError:
            pass


# ═══════════════════════════════════════════════════════════════════════
#  6. Public API wrapper tests
# ═══════════════════════════════════════════════════════════════════════


class TestPublicAPIWrappers:
    """Test select_binary_separation_methods and select_multicomponent_separation_methods."""

    def test_binary_wrapper_returns_result(self):
        ret = select_binary_separation_methods(
            component_names=["water", "methanol"],
            molar_fractions=[0.5, 0.5],
            boiling_points_K=[350.0, 380.0],
        )
        assert ret.tool == "select_binary_separation_methods"
        assert ret.result is not None
        assert ret.errors is None

    def test_binary_wrapper_captures_inputs(self):
        ret = select_binary_separation_methods(
            component_names=["water", "methanol"],
            molar_fractions=[0.5, 0.5],
            boiling_points_K=[340.0, 365.0],
            relative_volatility=2.5,
            pressure=1.5,
        )
        assert ret.provided_inputs is not None

    def test_multicomponent_wrapper_returns_result(self):
        ret = select_multicomponent_separation_methods(
            component_names=["water", "methanol", "butanol"],
            molar_fractions=[0.4, 0.35, 0.25],
            boiling_points_K=[353.0, 384.0, 412.0],
            relative_volatilities=[2.0, 2.0],
        )
        assert ret.tool == "select_multicomponent_separation_methods"
        assert ret.result is not None

    def test_multicomponent_wrapper_has_assumptions(self):
        ret = select_multicomponent_separation_methods(
            component_names=["water", "methanol", "butanol"],
            molar_fractions=[0.4, 0.35, 0.25],
            boiling_points_K=[353.0, 384.0, 412.0],
            relative_volatilities=[2.0, 2.0],
        )
        assert ret.assumptions is not None
        assert len(ret.assumptions) > 0

    def test_multicomponent_gt3_returns_suggestions_only(self):
        """For >3 products, tool returns high-level suggestions without PI matrix."""
        ret = select_multicomponent_separation_methods(
            component_names=["water", "methanol", "butanol", "something_heavy"],
            molar_fractions=[0.4, 0.25, 0.25, 0.1],  # 4 products
            boiling_points_K=[337.7, 353.2, 383.8, 411.5],
            relative_volatilities=[2.0, 2.0, 2.0],
        )
        assert ret.tool == "select_multicomponent_separation_methods"
        assert ret.result is not None
        assert "multicomponent" in ret.result.system_class
        method_names = {m["method"] for m in ret.result.ranked_methods}
        assert "Kaibel column" in method_names
        assert "Thermally coupled distillation (TCD)" in method_names
        assert "Distillation sequences" in method_names
        # PI matrix should NOT be populated
        assert ret.result.pi_matrix_results == {}

    def test_binary_guardrail_overrides_large_light_fraction(self):
        """Guardrail should correct large_light_fraction when molar_fractions contradict it."""
        ret = select_binary_separation_methods(
            component_names=["water", "methanol"],
            boiling_points_K=[337.7, 373.15],
            relative_volatility=2.5,
            large_light_fraction=True,  # Wrong: 0.6981 < 0.80
            large_heavy_fraction=False,
            molar_fractions=[0.6981, 0.3019],
        )
        assert ret.result is not None
        # The corrected flag should be reflected in provided_inputs
        assert ret.provided_inputs.large_light_fraction is False
        # Should report the override
        assert ret.assumptions is not None
        assert any("GUARDRAIL OVERRIDE" in a for a in ret.assumptions)

    def test_binary_guardrail_warns_suspicious_azeotrope(self):
        """Guardrail should warn when azeotrope=True but alpha >> 1."""
        ret = select_binary_separation_methods(
            component_names=["water", "methanol"],
            molar_fractions=[0.6981, 0.3019],
            boiling_points_K=[337.7, 373.15],
            azeotrope=True,
            relative_volatility=2.5,  # Well above 1.0 → likely zeotropic
        )
        assert ret.assumptions is not None
        assert any("azeotrope=True but relative_volatility" in a for a in ret.assumptions)

    def test_binary_guardrail_no_override_when_correct(self):
        """Guardrail should not trigger when flags match composition data."""
        ret = select_binary_separation_methods(
            component_names=["water", "methanol"],
            molar_fractions=[0.6981, 0.3019],
            boiling_points_K=[337.7, 373.15],
            relative_volatility=2.5,
            large_light_fraction=False,
            large_heavy_fraction=False,
        )
        assert ret.result is not None
        assert ret.assumptions is None


# ═══════════════════════════════════════════════════════════════════════
#  7. Paper case study validation
#     Li, Somoza-Tornos & Kiss (2025), CPPM 20(2): 293-307
# ═══════════════════════════════════════════════════════════════════════


class TestPaperCaseStudies:
    """Validate against the four case studies in the paper."""

    @staticmethod
    def _get_method_names(result):
        return {m.get("method", "") for m in result.ranked_methods}

    # -- Case 1: Methanol/Water (binary zeotrope, §5.1, Figure 5) --

    def test_case1_methanol_water_system_class(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=False,
            boiling_points_K=[337.7, 373.15],
            relative_volatilities=2.98,
            heat_of_vaporization=[40.7, 40.8],
            recovery=0.9998,
            purity=0.9999,
            reflux_ratio=0.87,
        )
        assert result.system_class == "binary_zeotrope"

    def test_case1_methanol_water_all_methods(self):
        """Paper Figure 5: ConvDist, HPAD, HIDiC, CyDist, MAD, HiGee."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=False,
            boiling_points_K=[337.7, 373.15],
            relative_volatilities=2.98,
            heat_of_vaporization=[40.7, 40.8],
            recovery=0.9998,
            purity=0.9999,
            reflux_ratio=0.87,
        )
        names = self._get_method_names(result)
        for expected in ["ConvDist", "HPAD", "HIDiC", "CyDist", "MAD", "HiGee"]:
            assert expected in names, f"Missing {expected} for MeOH/H2O"

    def test_case1_methanol_water_cop_favorable(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=False,
            boiling_points_K=[337.7, 373.15],
            relative_volatilities=2.98,
            heat_of_vaporization=[40.7, 40.8],
            recovery=0.9998,
            purity=0.9999,
            reflux_ratio=0.87,
        )
        for m in result.ranked_methods:
            if m["method"] in ("HPAD", "HIDiC") and "COP_recommendation" in m:
                assert m["COP_recommendation"] == "FAVORABLE"

    # -- Case 2: Ethanol/Water (binary azeotrope, NOT pressure-sensitive, §5.2) --

    def test_case2_ethanol_water_methods(self):
        """Paper Figure 6a: MAD, ED/AD, E-DWC, A-DWC, HPAD, HIDiC. No PSD."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=False,
            boiling_points_K=[351.15, 373.15],
            relative_volatilities=1.5,
            heat_of_vaporization=[39.2, 40.8],
        )
        names = self._get_method_names(result)
        for expected in ["MAD", "ED/AD", "E-DWC", "A-DWC", "HPAD", "HIDiC"]:
            assert expected in names, f"Missing {expected} for EtOH/H2O"

    def test_case2_ethanol_water_no_zeotropic_methods(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=False,
            boiling_points_K=[351.15, 373.15],
            relative_volatilities=1.5,
            heat_of_vaporization=[39.2, 40.8],
        )
        names = self._get_method_names(result)
        assert "ConvDist" not in names
        assert "CyDist" not in names
        assert "HiGee" not in names

    def test_case2_ethanol_water_psd_excluded(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=False,
            boiling_points_K=[351.15, 373.15],
            relative_volatilities=1.5,
        )
        names = self._get_method_names(result)
        assert "PSD" not in names

    # -- Case 3: ACN/Water (binary azeotrope, pressure-sensitive, large heavy, §5.2) --

    def test_case3_acn_water_methods(self):
        """Paper Figure 6b: PSD, MAD, ED/AD, E-DWC, A-DWC, HPAD, HIDiC."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=True,
            boiling_points_K=[354.65, 378.15],
            relative_volatilities=1.5,
            heat_of_vaporization=[33.2, 40.8],
            purity=0.999,
            large_heavy_fraction=True,
        )
        names = self._get_method_names(result)
        for expected in ["PSD", "MAD", "ED/AD", "E-DWC", "A-DWC", "HPAD", "HIDiC"]:
            assert expected in names, f"Missing {expected} for ACN/H2O"

    def test_case3_acn_water_q6_takes_priority_over_q5(self):
        """When both azeotrope and large_heavy_fraction are true, Q6 resolves first."""
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=True,
            boiling_points_K=[354.65, 378.15],
            relative_volatilities=1.5,
            large_heavy_fraction=True,
        )
        hlq = result.high_level_assessment
        assert hlq["resolved"] is True
        assert hlq["resolved_by"] == "Q6"
        qs = hlq["questions_evaluated"]
        assert any("Q6" in q for q in qs)

    def test_case3_acn_water_psd_included(self):
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=True,
            pressure_sensitive_azeotrope=True,
            boiling_points_K=[354.65, 378.15],
            relative_volatilities=1.5,
        )
        names = self._get_method_names(result)
        assert "PSD" in names

    # -- Case 4: BTX (ternary zeotrope, §5.3, Figures 7-8) --

    def test_case4_btx_system_class(self):
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.39, 2.19],
            heat_of_vaporization=[30.9, 33.6, 36.8],
            viscosity=[0.652, 0.590, 0.620],
            reflux_ratio=1.92,
            boiling_points_K=[353.25, 383.85, 411.55],
            molar_fractions=[0.333, 0.334, 0.333],
        )
        assert "ternary" in result.system_class

    def test_case4_btx_methods(self):
        """Paper Figure 8: DWC, ConvDist, HPAD, HIDiC, CyDist, HiGee."""
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.39, 2.19],
            heat_of_vaporization=[30.9, 33.6, 36.8],
            viscosity=[0.652, 0.590, 0.620],
            reflux_ratio=1.92,
            boiling_points_K=[353.25, 383.85, 411.55],
            molar_fractions=[0.333, 0.334, 0.333],
            middle_key_fraction=0.334,
            high_purity_middle=True,
        )
        method_names = []
        for rank_entry in result.ranked_methods:
            for entry in rank_entry["methods"]:
                method_names.append(entry["method"])
        # names = self._get_method_names(result)
        for expected in ["DWC", "ConvDist", "HPAD", "HIDiC", "CyDist", "HiGee"]:
            assert expected in method_names, f"Missing {expected} for BTX"

    def test_case4_btx_dse_direct_preferred(self):
        """Paper: DSE direct > indirect for BTX."""
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.39, 2.19],
            boiling_points_K=[353.25, 383.85, 411.55],
            molar_fractions=[0.333, 0.334, 0.333],
        )
        dse = result.dse_analysis
        assert dse is not None
        assert dse["preferred_sequence"] == "direct"

    def test_case4_btx_dse_values_reasonable(self):
        """DSE values should be in 35-45% range (paper: 38.33%/37.42%)."""
        result = select_separation_methods_core(
            number_of_products=3,
            relative_volatilities=[2.39, 2.19],
            boiling_points_K=[353.25, 383.85, 411.55],
            molar_fractions=[0.333, 0.334, 0.333],
        )
        dse = result.dse_analysis
        assert dse is not None
        direct_dse = dse["direct_sequence"]["DSE"]
        indirect_dse = dse["indirect_sequence"]["DSE"]
        assert 0.35 < direct_dse < 0.45
        assert 0.33 < indirect_dse < 0.42


# ═══════════════════════════════════════════════════════════════════════
#  8. PI matrix consistency checks
# ═══════════════════════════════════════════════════════════════════════


class TestPIMatrixConsistency:
    """Verify PI matrix data structure integrity."""

    def test_all_methods_have_all_criteria(self):
        """Every method in PI_MATRIX should have all standard criteria keys."""
        expected_keys = {
            "dTb_lt_10",
            "dTb_10_20",
            "dTb_20_60",
            "dTb_gt_60",
            "RV_1_01_1_15",
            "high_hvap",
            "vacuum",
            "high_recovery",
            "high_purity",
            "high_viscosity",
            "low_diffusion",
            "high_reflux",
        }
        for method_name, caps in PI_MATRIX.items():
            for key in expected_keys:
                assert key in caps, f"{method_name} missing key '{key}'"

    def test_valid_marks_only(self):
        """All marks should be A, B, C, or Blank."""
        valid = {"A", "B", "C", "Blank"}
        for method_name, caps in PI_MATRIX.items():
            for key, mark in caps.items():
                assert mark in valid, f"{method_name}[{key}] = '{mark}' not in {valid}"

    def test_ternary_matrix_has_dwc_tcd(self):
        assert "DWC" in TERNARY_MATRIX
        assert "TCD" in TERNARY_MATRIX

    def test_all_pi_methods_present(self):
        """Paper Figure 3 lists these methods."""
        expected = {"ConvDist", "HPAD", "HIDiC", "CyDist", "MAD", "HiGee"}
        assert expected == set(PI_MATRIX.keys())


# ═══════════════════════════════════════════════════════════════════════
#  9. Edge cases and error handling
# ═══════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Edge cases and robustness checks."""

    def test_binary_with_none_hvap(self):
        """Should work with None values in heat_of_vaporization."""
        result = select_separation_methods_core(
            number_of_products=2,
            boiling_points_K=[350.0, 380.0],
            heat_of_vaporization=[None, None],
        )
        assert result is not None

    def test_binary_with_empty_lists(self):
        result = select_separation_methods_core(
            number_of_products=2,
            boiling_points_K=[350.0, 380.0],
            viscosity=[],
            diffusion_coefficient=[],
        )
        assert result is not None

    def test_very_small_delta_tb(self):
        """Very close boiling points: some methods should be vetoed."""
        result = select_separation_methods_core(
            number_of_products=2,
            boiling_points_K=[370.0, 372.0],
            relative_volatilities=1.05,
        )
        names = self._get_names(result)
        # HiGee should be vetoed for dTb < 10
        assert "HiGee" not in names

    def test_very_large_delta_tb(self):
        result = select_separation_methods_core(
            number_of_products=2,
            boiling_points_K=[300.0, 380.0],
            relative_volatilities=5.0,
        )
        assert result.system_class == "binary_zeotrope"
        assert len(result.ranked_methods) > 0

    def test_vacuum_operation(self):
        result = select_separation_methods_core(
            number_of_products=2,
            boiling_points_K=[350.0, 380.0],
            pressure=0.1,  # vacuum
        )
        # HIDiC should be vetoed under vacuum
        names = self._get_names(result)
        assert "HIDiC" not in names

    def test_ternary_single_dtb(self):
        """Ternary with scalar dTb should fall back gracefully."""
        result = select_separation_methods_core(
            number_of_products=3,
            boiling_points_K=[350.0, 380.0, 410.0],
            relative_volatilities=2.0,
        )
        assert result is not None

    @staticmethod
    def _get_names(result):
        return {m.get("method", "") for m in result.ranked_methods}


# ═══════════════════════════════════════════════════════════════════════
#  Audit regressions
# ═══════════════════════════════════════════════════════════════════════


def test_a_ternary_pairs_each_split_with_its_own_components():
    """The per-component lists follow the boiling order: only A (300 K) is viscous,
    so only A/B gets high_viscosity, in whatever order the components are given."""

    def screen(order):
        names, tb, mu, x = ["A", "B", "C"], [300.0, 350.0, 400.0], [5.0, 0.5, 0.5], [0.4, 0.2, 0.4]
        return select_multicomponent_separation_methods(
            [names[i] for i in order],
            [tb[i] for i in order],
            [2.0, 2.0],
            viscosity=[mu[i] for i in order],
            heat_of_vaporization=[[45.0, 30.0, 30.0][i] for i in order],
            molar_fractions=[x[i] for i in order],
        ).result

    given = screen([1, 0, 2])
    groups = {g["group"]: g["active_criteria"] for g in given.ranked_methods if "group" in g}
    assert groups["binary_sub (A/B)"] == ["high_hvap", "high_viscosity"]
    assert groups["binary_sub (B/C)"] == []
    sorted_ = screen([0, 1, 2])
    assert given.ranked_methods == sorted_.ranked_methods
    assert given.pi_matrix_results == sorted_.pi_matrix_results
    assert given.dse_analysis == sorted_.dse_analysis


def test_the_binary_azeotrope_result_is_pinned():
    """Q6 resolves an azeotrope; the PI matrix is not evaluated. EtOH/H2O (351.4 /
    373.15 K): COP 0.7 * 378.15 / 31.75 = 8.34, favourable."""
    result = select_binary_separation_methods(
        ["ethanol", "water"], [0.5, 0.5], [351.4, 373.15], azeotrope=True, relative_volatility=1.0
    ).result
    assert result.system_class == "binary_azeotrope"
    assert result.high_level_assessment["resolved_by"] == "Q6"
    assert result.pi_matrix_results == {}
    ranked = {m["method"]: m["final_score"] for m in result.ranked_methods}
    assert ranked == dict.fromkeys(["A-DWC", "E-DWC", "ED/AD", "HIDiC", "HPAD", "MAD"], 1.0)
    hpad = next(m for m in result.ranked_methods if m["method"] == "HPAD")
    assert (hpad["COP_estimated"], hpad["COP_recommendation"]) == (8.34, "FAVORABLE")
    sensitive = select_binary_separation_methods(
        ["a", "b"],
        [0.5, 0.5],
        [77.4, 90.2],
        azeotrope=True,
        pressure_sensitive_azeotrope=True,
        relative_volatility=1.0,
    ).result
    ranked = {m["method"]: m["final_score"] for m in sensitive.ranked_methods}
    # a cryogenic pair: COP 2.92 < 3, HPAD/HIDiC marginal at 0.5
    assert ranked["PSD"] == 1.0 and ranked["HPAD"] == ranked["HIDiC"] == 0.5


def test_multicomponent_length_errors_are_returned_not_raised():
    ret = select_multicomponent_separation_methods(
        ["a", "b", "c"], [300.0, 350.0, 400.0], [2.0, 2.0], viscosity=[1.0, 1.0]
    )
    assert ret.result is None
    assert ret.errors == ["viscosity must have 3 values for 3-component separation, got 2"]
    # a list that is too long cannot be sorted with the boiling points either
    ret = select_multicomponent_separation_methods(
        ["B", "A", "C"], [350.0, 300.0, 400.0], [2.0, 2.0], viscosity=[0.5, 5.0, 0.5, 9.9]
    )
    assert ret.result is None
    assert ret.errors == ["viscosity must have 3 values for 3-component separation, got 4"]


def test_an_unsorted_binary_gets_the_same_cop():
    def cop(tb):
        result = select_binary_separation_methods(
            ["a", "b"], [0.5, 0.5], tb, azeotrope=True, relative_volatility=1.0
        ).result
        return next(m for m in result.ranked_methods if m["method"] == "HPAD")["COP_estimated"]

    assert cop([373.15, 351.4]) == cop([351.4, 373.15]) == 8.34
