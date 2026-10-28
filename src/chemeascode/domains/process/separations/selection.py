"""Separation method selection for distillation-type separations.

Implements the selection and decision matrix of Li, Somoza-Tornos and Kiss (2025), "A systematic
selection and decision matrix for energy-efficient intensified distillation technologies",
Chem. Prod. Process Model. 20(2): 293-307: the high-level pre-questions (Q1-Q6), the process
intensification (PI) matrix for binary separations and each binary sub-separation of a ternary,
the COP estimate for heat-pump assisted distillation and HIDiC, and the distillation sequence
efficiency (DSE, Plesu et al. 2015) of the direct and indirect ternary sequences.

The inputs (boiling points, relative volatilities, heats of vaporisation, viscosities,
diffusivities, and the screening flags) are given by the caller; the functions retrieve no
property. :func:`~chemeascode.domains.process.separations.inputs.select_with_retrieved_properties`
fills the numeric ones from the chemistry property sources first, with their provenance (the
flags stay the caller's). Units are stated per argument: K, bar (absolute), kJ/mol, mPa s, m2/s. The result
ranks candidate methods with their scores and the notes and guardrail corrections applied; it is
a screening, not a design decision. ``downstream_representation`` says for every method named
how core can represent it afterwards (:mod:`.coverage`: predictive, shortcut, specified split
or none).

Moved from LLM4ChemE (``src/tools/separation_selection/tools_separation_methods.py``); the
property aggregation it also held (thermo lookups, HANNA activity coefficients) is
``domains/chemistry/properties.py``, which :mod:`.inputs` connects to the screening.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from chemeascode.domains.process.separations.coverage import methods_named, representation_of

# ═══════════════════════════════════════════════════════════════════════
#  PI Matrix (Figure 3 from the paper) — Binary zeotrope technologies
# ═══════════════════════════════════════════════════════════════════════
#
# Marks: "A" = recommended (check), "B" = consider / further check (!)
#        "C" = not suitable (x), "Blank" = not relevant to decision
#
# This is the unified PI matrix from Figure 3, applicable to binary
# zeotropic separations AND to each binary sub-separation within ternary.

PI_MATRIX = {
    "ConvDist": {
        "dTb_lt_10": "B",
        "dTb_10_20": "B",
        "dTb_20_60": "A",
        "dTb_gt_60": "A",
        "RV_1_01_1_15": "C",
        "high_hvap": "Blank",
        "vacuum": "A",
        "high_recovery": "Blank",
        "high_purity": "Blank",
        "high_viscosity": "Blank",
        "low_diffusion": "Blank",
        "high_reflux": "Blank",
    },
    "HPAD": {
        "dTb_lt_10": "A",
        "dTb_10_20": "A",
        "dTb_20_60": "B",  # needs COP check
        "dTb_gt_60": "B",  # needs COP check
        "RV_1_01_1_15": "B",
        "high_hvap": "A",
        "vacuum": "B",
        "high_recovery": "Blank",
        "high_purity": "Blank",
        "high_viscosity": "Blank",
        "low_diffusion": "Blank",
        "high_reflux": "Blank",
    },
    "HIDiC": {
        "dTb_lt_10": "A",
        "dTb_10_20": "A",
        "dTb_20_60": "B",  # needs COP check
        "dTb_gt_60": "B",  # needs COP check
        "RV_1_01_1_15": "B",
        "high_hvap": "A",
        "vacuum": "C",  # vacuum not applicable for HIDiC
        "high_recovery": "Blank",
        "high_purity": "Blank",
        "high_viscosity": "Blank",
        "low_diffusion": "Blank",
        "high_reflux": "Blank",
    },
    "CyDist": {
        "dTb_lt_10": "B",
        "dTb_10_20": "A",
        "dTb_20_60": "A",
        "dTb_gt_60": "A",
        "RV_1_01_1_15": "A",
        "high_hvap": "Blank",
        "vacuum": "C",  # vacuum not applicable for CyDist
        "high_recovery": "A",
        "high_purity": "A",
        "high_viscosity": "Blank",
        "low_diffusion": "A",
        "high_reflux": "A",
    },
    "MAD": {
        "dTb_lt_10": "B",
        "dTb_10_20": "B",
        "dTb_20_60": "Blank",
        "dTb_gt_60": "Blank",
        "RV_1_01_1_15": "B",
        "high_hvap": "A",
        "vacuum": "Blank",
        "high_recovery": "Blank",
        "high_purity": "Blank",
        "high_viscosity": "C",
        "low_diffusion": "Blank",
        "high_reflux": "Blank",
    },
    "HiGee": {
        "dTb_lt_10": "C",
        "dTb_10_20": "B",
        "dTb_20_60": "A",
        "dTb_gt_60": "A",
        "RV_1_01_1_15": "C",
        "high_hvap": "Blank",
        "vacuum": "A",
        "high_recovery": "Blank",
        "high_purity": "Blank",
        "high_viscosity": "A",
        "low_diffusion": "A",
        "high_reflux": "Blank",
    },
}

# DWC and TCD rows from the PI matrix (ternary-specific technologies, Figure 3)
TERNARY_MATRIX = {
    "DWC": {
        "dTb_lt_10": "C",
        "dTb_10_20": "B",
        "dTb_20_60": "A",
        "dTb_gt_60": "B",
        "RV_1_01_1_15": "C",
        "high_hvap": "Blank",
        "vacuum": "A",
        "high_recovery": "A",
        "high_purity": "A",
        "high_viscosity": "Blank",
        "low_diffusion": "Blank",
        "high_reflux": "A",
    },
    "TCD": {
        "dTb_lt_10": "C",
        "dTb_10_20": "B",
        "dTb_20_60": "A",
        "dTb_gt_60": "B",
        "RV_1_01_1_15": "C",
        "high_hvap": "Blank",
        "vacuum": "A",
        "high_recovery": "A",
        "high_purity": "A",
        "high_viscosity": "Blank",
        "low_diffusion": "Blank",
        "high_reflux": "A",
    },
}


ATM = 1.01325  # bar ~ 1 atm


# ═══════════════════════════════════════════════════════════════════════
#  Helper functions
# ═══════════════════════════════════════════════════════════════════════


def _delta_tb_band(delta_tb: float | None) -> str:
    """Return the band label for delta Tb (deg C or K, same increment)."""
    if delta_tb is None:
        return "unknown"
    if delta_tb < 10.0:
        return "dTb_lt_10"
    if 10.0 <= delta_tb < 20.0:
        return "dTb_10_20"
    if 20.0 <= delta_tb <= 60.0:
        return "dTb_20_60"
    return "dTb_gt_60"


def _compute_cop(
    tb_light_K: float | None,
    tb_heavy_K: float | None,
    compressor_efficiency: float = 0.7,
    min_temp_diff_K: float = 5.0,
) -> float | None:
    """Estimate the COP of a heat pump (HPAD) or HIDiC from the split's temperature levels.

    The Carnot COP of a heat pump delivering heat at T_hot, times a compressor efficiency:
        COP_real ~ eta_compressor * T_hot / (T_hot - T_cold)

    with the reboiler side T_hot = Tb_heavy + dT_min and the condenser side
    T_cold = Tb_light - dT_min (the normal boiling points of the split's heavy and light key,
    K): the lift is delta_Tb + 2 dT_min and the level is the column's own, so a cryogenic
    split gets a far lower COP than one near 100 deg C at the same delta_Tb (pre-release issue 216). The
    callers compare it with the screening's threshold of 3 (favourable at or above). The
    form, eta = 0.7, dT_min = 5 K and the threshold are core's convention for this screening,
    not equations taken from Li et al. (2025).

    Limitations: the normal boiling points stand for the column's temperatures, so a column
    under pressure (cryogenic air separation at 5-6 bar) is evaluated at the wrong level; for
    an azeotrope (Q6) the entrainer's boiling point, which sets the real lift, is ignored; a
    direct vapour recompression has no condenser-side approach, so the estimate is slightly
    conservative for it.

    Returns None if a boiling point is missing or Tb_heavy is not above Tb_light.
    """
    if tb_light_K is None or tb_heavy_K is None or tb_heavy_K <= tb_light_K:
        return None
    t_hot = tb_heavy_K + min_temp_diff_K  # K, reboiler side
    t_cold = tb_light_K - min_temp_diff_K  # K, condenser side
    if t_cold <= 0:
        return None
    cop_carnot = t_hot / (t_hot - t_cold)
    cop_real = compressor_efficiency * cop_carnot
    return round(cop_real, 2)


def _compute_dse(
    component_boiling_points_K: list[float],
    component_molar_fractions: list[float],
    sequence: str = "direct",
    component_names: list[str] | None = None,
) -> dict[str, Any]:
    """Compute Distillation Sequence Efficiency (DSE) per Plesu et al. (2015).

    Uses the Carnot-cycle analogy for distillation columns:
        eta_C = (T_B - T_D) / T_B   (Carnot efficiency of column C)

    Per the Plesu convention (confirmed in follow-up publications):
      - Distillate products: multiply by the column Carnot efficiency eta_C
      - Bottom products: multiply by 1 (no efficiency penalty)

    DSE = sum_i (x_i * prod over columns in product i's path)

    For ternary ABC (sorted by ascending boiling point), two sequences:
      - direct:   A/BC then B/C
      - indirect: AB/C then A/B

    Args:
        component_boiling_points_K: [T_A, T_B, T_C] in Kelvin (sorted internally)
        component_molar_fractions: [x_A, x_B, x_C] matching same component order
        sequence: "direct" or "indirect"
        component_names: optional names for labeling (sorted with boiling points)

    Returns dict with DSE value and per-column Carnot efficiencies.
    """
    if len(component_boiling_points_K) < 3:
        return {"error": "DSE requires at least 3 components"}

    bps = list(component_boiling_points_K)
    xfs = list(component_molar_fractions)
    names = list(component_names) if component_names else []

    # Sort by boiling point (ascending: lightest first)
    if names and len(names) == len(bps):
        paired = sorted(zip(bps, xfs, names, strict=False), key=lambda p: p[0])
        bps = [p[0] for p in paired]
        xfs = [p[1] for p in paired]
        names = [p[2] for p in paired]
    else:
        paired = sorted(zip(bps, xfs, strict=False), key=lambda p: p[0])
        bps = [p[0] for p in paired]
        xfs = [p[1] for p in paired]
        names = []

    n = len(bps)

    if n == 3:
        T_A, T_B, T_C = bps[0], bps[1], bps[2]
        x_A, x_B, x_C = xfs[0], xfs[1], xfs[2]

        # Use component names if available, fallback to A/B/C
        nA = names[0] if names else "A"
        nB = names[1] if names else "B"
        nC = names[2] if names else "C"

        if sequence == "direct":
            # Column 1: A/BC -> distillate=A, bottom=BC
            # Heavy key = B (lightest in bottom), so reboiler T ≈ T_B
            eta_1 = (T_B - T_A) / T_B
            # Column 2: B/C -> distillate=B, bottom=C (pure C, reboiler at T_C)
            eta_2 = (T_C - T_B) / T_C

            # Product paths (Plesu convention: distillate=eta, bottoms=1):
            # A: distillate of col1 -> eta_1
            # B: bottoms of col1 (->1), distillate of col2 (->eta_2) -> 1 * eta_2
            # C: bottoms of col1 (->1), bottoms of col2 (->1) -> 1 * 1
            dse = x_A * eta_1 + x_B * eta_2 + x_C * 1.0
            return {
                "sequence": f"direct ({nA}/({nB}+{nC}) -> {nB}/{nC})",
                "column_efficiencies": {
                    f"column_1_{nA}_({nB}+{nC})": round(eta_1, 4),
                    f"column_2_{nB}_{nC}": round(eta_2, 4),
                },
                "DSE": round(dse, 4),
                "DSE_percent": f"{dse * 100:.2f}%",
            }
        else:  # indirect
            # Column 1: AB/C split -> LK=B, HK=C (key pair of the split)
            # Note: paper uses bubble-point of AB distillate which requires VLE;
            # key-pair shortcut approximates T_D ≈ T_B, T_reboiler = T_C
            eta_1 = (T_C - T_B) / T_C
            # Column 2: A/B split -> LK=A, HK=B
            eta_2 = (T_B - T_A) / T_B

            # Product paths (Plesu convention: distillate=eta, bottoms=1):
            # A: distillate of col1 (->eta_1), distillate of col2 (->eta_2) -> eta_1 * eta_2
            # B: distillate of col1 (->eta_1), bottoms of col2 (->1) -> eta_1
            # C: bottoms of col1 (->1) -> 1
            dse = x_A * (eta_1 * eta_2) + x_B * eta_1 + x_C * 1.0
            return {
                "sequence": f"indirect (({nA}+{nB})/{nC} -> {nA}/{nB})",
                "column_efficiencies": {
                    f"column_1_({nA}+{nB})_{nC}": round(eta_1, 4),
                    f"column_2_{nA}_{nB}": round(eta_2, 4),
                },
                "DSE": round(dse, 4),
                "DSE_percent": f"{dse * 100:.2f}%",
            }

    # Generic multicomponent: return per-pair Carnot efficiencies
    efficiencies = {}
    for i in range(n - 1):
        eta = (bps[i + 1] - bps[i]) / bps[i + 1]
        label = f"eta_{names[i]}_{names[i + 1]}" if names else f"eta_{i}_{i + 1}"
        efficiencies[label] = round(eta, 4)
    return {"sequence": "generic", "column_efficiencies": efficiencies}


def _identify_active_criteria(
    relative_volatility: float | None,
    heat_of_vaporization: list[float | None],
    pressure_bar: float | None,
    recovery: float | None,
    purity: float | None,
    viscosity_cp: list[float | None],
    diffusion_m2s: list[float | None],
    reflux_ratio: float | None,
) -> list[str]:
    """Identify which criteria in the PI matrix are active (met)."""
    active: list[str] = []

    # Low relative volatility (1.01-1.15)
    if relative_volatility is not None and 1.01 <= relative_volatility <= 1.15:
        active.append("RV_1_01_1_15")

    # High heat of vaporization (any component >= 40 kJ/mol)
    if isinstance(heat_of_vaporization, list) and any(
        h is not None and h >= 40.0 for h in heat_of_vaporization
    ):
        active.append("high_hvap")

    # Vacuum operation
    if pressure_bar is not None and pressure_bar < 0.95 * ATM:
        active.append("vacuum")

    # High recovery requirement
    if recovery is not None and recovery > 0.999:
        active.append("high_recovery")

    # High purity requirement
    if purity is not None and purity > 0.999:
        active.append("high_purity")

    # High viscosity (any component >= 2 cP)
    if isinstance(viscosity_cp, list) and any(v is not None and v >= 2.0 for v in viscosity_cp):
        active.append("high_viscosity")

    # Low diffusion coefficient (any component < 5e-10 m2/s)
    if isinstance(diffusion_m2s, list) and any(d is not None and d < 5e-10 for d in diffusion_m2s):
        active.append("low_diffusion")

    # High minimum reflux ratio
    if reflux_ratio is not None and reflux_ratio >= 1.8:
        active.append("high_reflux")

    return active


def _score_method(
    method_caps: dict[str, str], band: str, active_criteria: list[str]
) -> dict[str, Any]:
    """Score a single method against delta_Tb band + active criteria.

    Returns scoring dict with mark details.
    """
    marks = []
    mark_details = {}

    # delta_Tb band mark
    band_mark = method_caps.get(band, "Blank") if band != "unknown" else "Blank"
    marks.append(band_mark)
    mark_details["deltaTb_band"] = band_mark

    # Other active criteria
    for criterion in active_criteria:
        mark = method_caps.get(criterion, "Blank")
        marks.append(mark)
        mark_details[criterion] = mark

    # Scoring
    A_count = sum(1 for m in marks if m == "A")
    B_count = sum(1 for m in marks if m == "B")
    C_present = any(m == "C" for m in marks)
    raw_score = A_count * 1.0 + B_count * 0.5

    # Find veto factor if C present
    veto_factor = ""
    if C_present:
        if band_mark == "C":
            veto_factor = "deltaTb_band"
        else:
            for criterion in active_criteria:
                if method_caps.get(criterion, "Blank") == "C":
                    veto_factor = criterion
                    break

    final_score = 0.0 if C_present else round(raw_score, 3)

    return {
        "marks": marks,
        "mark_details": mark_details,
        "A_count": A_count,
        "B_count": B_count,
        "C_present": "YES" if C_present else "NO",
        "raw_score": round(raw_score, 3),
        "vetoed": "YES" if C_present else "NO",
        "veto_factor": veto_factor,
        "final_score": final_score,
    }


# ═══════════════════════════════════════════════════════════════════════
#  High-level pre-questions (Figure 2 from paper)
# ═══════════════════════════════════════════════════════════════════════


def _evaluate_high_level_questions(
    number_of_products: int,
    azeotrope: bool,
    pressure_sensitive_azeotrope: bool,
    has_solidification_risk: bool,
    has_non_condensable: bool,
    has_thermosensitive: bool,
    large_light_fraction: bool,
    large_heavy_fraction: bool,
    boiling_point_diff: float | None,
    middle_key_fraction: float | None = None,
    high_purity_middle: bool = False,
    pressure: float | None = None,
    boiling_points_K: list[float] | None = None,
) -> dict[str, Any]:
    """Evaluate Q1-Q7 from the paper's methodology (Figure 2/4). *boiling_points_K*, sorted
    ascending, give the binary's COP estimate (Q6).

    Implements a sequential decision tree per the paper:
      - Q1 (solidification): YES → RESOLVE (divert to crystallization)
      - Q2 (non-condensable): YES → RESOLVE (divert to membrane/partial condenser)
      - Q3 (thermosensitive): YES → RESOLVE (vacuum distillation; HIDiC/CyDist excluded)
      - Q6 (azeotrope):       YES → RESOLVE (azeotrope-specific methods, skip PI matrix)
      - Q4 (large light):     YES → RESOLVE (MAD / evaporation; skip PI matrix)
      - Q5 (large heavy):     YES → RESOLVE (stripping / adsorption; skip PI matrix)
      - All NO →               continue to PI matrix

    Returns dict with:
      resolved: bool — whether pre-screen determined the final answer
      resolved_by: str|None — which question resolved ("Q1", "Q2", "Q6")
      questions_evaluated: list — all Q/A pairs evaluated (up to resolution point)
      pre_recommendations: list — recommendations from resolving/additive questions
      front_end_recommendations: list — additive recommendations from Q3-Q5
      flags_for_pi_matrix: dict — constraints for PI matrix (from Q3)
      recommended_methods: list — final ranked method list if resolved
    """
    questions_evaluated: list[dict] = []
    front_end_recommendations: list[dict] = []
    flags_for_pi_matrix: dict[str, Any] = {}
    pre_recommendations: list[dict] = []

    # ── Q1: Risk of solidification? ── RESOLVING
    q1 = "YES" if has_solidification_risk else "NO"
    questions_evaluated.append({"Q1": "Risk of solidification (e.g., freezing)?", "answer": q1})
    if has_solidification_risk:
        rec = {
            "R1": "Crystallization; High pressure distillation column",
            "reason": "Increase column temperature to avoid solidification.",
        }
        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": [rec],
            "front_end_recommendations": [],
            "flags_for_pi_matrix": {},
            "resolved": True,
            "resolved_by": "Q1",
            "recommended_methods": [
                {
                    "method": "Crystallization",
                    "final_score": 1.0,
                    "reason": "Risk of solidification in feed.",
                },
                {
                    "method": "High pressure distillation column",
                    "final_score": 1.0,
                    "reason": "Increase column temperature to avoid solidification.",
                },
            ],
        }

    # ── Q2: Non-condensable components? ── RESOLVING
    q2 = "YES" if has_non_condensable else "NO"
    questions_evaluated.append({"Q2": "Non-condensable components?", "answer": q2})
    if has_non_condensable:
        rec = {
            "R2": "Membrane separation; Partial condenser",
            "reason": "Enable non-condensable removal in vapor phase.",
        }
        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": [rec],
            "front_end_recommendations": [],
            "flags_for_pi_matrix": {},
            "resolved": True,
            "resolved_by": "Q2",
            "recommended_methods": [
                {
                    "method": "Membrane separation",
                    "final_score": 1.0,
                    "reason": "Non-condensable components require vapor-phase separation.",
                },
                {
                    "method": "Partial condenser",
                    "final_score": 1.0,
                    "reason": "Enable non-condensable removal.",
                },
            ],
        }

    # ── Q3: Thermosensitive? ── RESOLVING
    q3 = "YES" if has_thermosensitive else "NO"
    questions_evaluated.append(
        {
            "Q3": "Thermosensitive components (polymerizing/decomposing)?",
            "answer": q3,
        }
    )
    if has_thermosensitive:
        rec = {
            "R3": "Vacuum column recommended; Two columns with second distillate recycled back. HIDiC and CyDist NOT applicable.",
            "reason": "Lower column temperature to protect sensitive compounds.",
        }
        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": [rec],
            "front_end_recommendations": [],
            "flags_for_pi_matrix": {},
            "resolved": True,
            "resolved_by": "Q3",
            "recommended_methods": [
                {
                    "method": "Vacuum distillation",
                    "final_score": 1.0,
                    "reason": "Thermosensitive components; lower column temperature via vacuum.",
                },
                {
                    "method": "Two columns with second distillate recycled back",
                    "final_score": 1.0,
                    "reason": "Feed non-thermosensitive component to normal pressure column; "
                    "thermosensitive component to smaller vacuum column with distillate recycled to first column.",
                },
            ],
        }

    # ── Q6: Azeotropic mixture? ── RESOLVING (checked before Q4/Q5)
    q6 = "YES" if azeotrope else "NO"
    questions_evaluated.append({"Q6": "Azeotropic mixture?", "answer": q6})
    if azeotrope:
        azeo_methods: list[dict[str, Any]] = []

        # PSD (only if pressure-sensitive)
        if pressure_sensitive_azeotrope:
            azeo_methods.append(
                {
                    "method": "PSD",
                    "final_score": 1.0,
                    "reason": "Azeotrope is pressure-sensitive.",
                }
            )

        azeo_methods.extend(
            [
                {
                    "method": "MAD",
                    "final_score": 1.0,
                    "reason": "Membrane can break azeotrope.",
                },
                {
                    "method": "ED/AD",
                    "final_score": 1.0,
                    "reason": "Extractive/Azeotropic distillation with entrainer.",
                },
                {
                    "method": "E-DWC",
                    "final_score": 1.0,
                    "reason": "Extractive DWC integrates ED with solvent recovery in single shell.",
                },
                {
                    "method": "A-DWC",
                    "final_score": 1.0,
                    "reason": "Azeotropic DWC integrates AD with solvent recovery in single shell.",
                },
            ]
        )

        # COP check for HPAD/HIDiC, at the binary's own temperature level
        cop = (
            _compute_cop(boiling_points_K[0], boiling_points_K[1])
            if boiling_points_K and len(boiling_points_K) >= 2
            else None
        )
        cop_note = ""

        hpad_entry: dict[str, Any] = {
            "method": "HPAD",
            "final_score": 1.0,
            "reason": "Heat pump assisted distillation for azeotrope with entrainer.",
        }
        hidic_entry: dict[str, Any] = {
            "method": "HIDiC",
            "final_score": 1.0,
            "reason": "Heat-integrated distillation column with entrainer.",
        }

        if cop is not None:
            hpad_entry["COP_estimated"] = cop
            hidic_entry["COP_estimated"] = cop
            if cop >= 3.0:
                hpad_entry["COP_recommendation"] = "FAVORABLE"
                hidic_entry["COP_recommendation"] = "FAVORABLE"
                cop_note = f"HPAD/HIDiC: COP ~ {cop} (>= 3.0) -> favorable."
            else:
                hpad_entry["final_score"] = 0.5
                hidic_entry["final_score"] = 0.5
                hpad_entry["COP_recommendation"] = "MARGINAL"
                hidic_entry["COP_recommendation"] = "MARGINAL"
                cop_note = f"HPAD/HIDiC: COP ~ {cop} (< 3.0) -> marginal; further check needed."
        else:
            hpad_entry["COP_recommendation"] = "UNABLE_TO_COMPUTE"
            hidic_entry["COP_recommendation"] = "UNABLE_TO_COMPUTE"
            cop_note = "HPAD/HIDiC: COP could not be computed. Further check with entrainer needed."

        # Q3 resolves early when thermosensitive, so HIDiC is always
        # available if we reach this point.
        azeo_methods.append(hpad_entry)
        azeo_methods.append(hidic_entry)

        # Sort by score descending
        azeo_methods.sort(key=lambda m: (-m["final_score"], m["method"]))

        # Build recommendation text
        if pressure_sensitive_azeotrope:
            rec_text = "; ".join(m["method"] for m in azeo_methods)
            rec = {
                "R6": rec_text,
                "reason": "Azeotrope is pressure-sensitive; PSD is recommended.",
                "note": "ED/AD adds solvent -> consider E-DWC/A-DWC for solvent recovery.",
            }
        else:
            rec_text = "; ".join(m["method"] for m in azeo_methods if m["method"] != "PSD")
            rec = {
                "R6": rec_text,
                "reason": "Azeotrope is NOT pressure-sensitive; PSD not recommended.",
                "note": "ED/AD adds solvent -> consider E-DWC/A-DWC for solvent recovery.",
            }
        pre_recommendations.append(rec)

        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": pre_recommendations,
            "front_end_recommendations": front_end_recommendations,
            "flags_for_pi_matrix": flags_for_pi_matrix,
            "resolved": True,
            "resolved_by": "Q6",
            "recommended_methods": azeo_methods,
            "cop_note": cop_note + " The COP is from the binary's normal boiling points; the "
            "entrainer chosen for ED/AD changes the temperature lift.",
        }

    # ── Q4: Large light fraction? ── RESOLVING
    q4 = "YES" if large_light_fraction else "NO"
    questions_evaluated.append({"Q4": "Large amount of light component in feed?", "answer": q4})
    if large_light_fraction:
        rec = {
            "R4": "Membrane assisted distillation (MAD); Evaporation",
            "reason": "Reduce high reboiler duty from evaporating large light fraction.",
        }
        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": pre_recommendations + [rec],
            "front_end_recommendations": front_end_recommendations,
            "flags_for_pi_matrix": flags_for_pi_matrix,
            "resolved": True,
            "resolved_by": "Q4",
            "recommended_methods": [
                {
                    "method": "Membrane assisted distillation (MAD)",
                    "final_score": 1.0,
                    "reason": "Large light fraction in feed; MAD reduces high reboiler duty.",
                },
                {
                    "method": "Evaporation",
                    "final_score": 1.0,
                    "reason": "Large light fraction in feed; evaporation reduces reboiler load.",
                },
            ],
        }

    # ── Q5: Large heavy fraction? ── RESOLVING
    q5 = "YES" if large_heavy_fraction else "NO"
    questions_evaluated.append({"Q5": "Large amount of heavy component in feed?", "answer": q5})
    if large_heavy_fraction:
        rec = {
            "R5": "(Steam) stripping; Adsorption; Preconcentration column",
            "reason": "Reduce high condenser duty from condensing large heavy fraction.",
        }
        return {
            "questions_evaluated": questions_evaluated,
            "pre_recommendations": pre_recommendations + [rec],
            "front_end_recommendations": front_end_recommendations,
            "flags_for_pi_matrix": flags_for_pi_matrix,
            "resolved": True,
            "resolved_by": "Q5",
            "recommended_methods": [
                {
                    "method": "(Steam) stripping",
                    "final_score": 1.0,
                    "reason": "Large heavy fraction in feed; stripping reduces high condenser duty.",
                },
                {
                    "method": "Adsorption",
                    "final_score": 1.0,
                    "reason": "Large heavy fraction in feed; adsorption as alternative.",
                },
                {
                    "method": "Preconcentration column",
                    "final_score": 1.0,
                    "reason": "Large heavy fraction in feed; preconcentration reduces condenser load.",
                },
            ],
        }

    # ── Q+: Number of outlet streams and ternary pre-screening ──
    # (not a resolving question — multicomponent evaluation is separate)
    if number_of_products == 3:
        questions_evaluated.append(
            {
                "Q+": f"Number of outlet streams = {number_of_products}",
                "answer": "3 products (ternary)",
            }
        )

        # Per paper Figure 4: three prerequisite questions for DWC/TCD
        mk_check = middle_key_fraction is not None and middle_key_fraction > 0.30
        purity_check = high_purity_middle
        suitable_pressure = (
            (pressure is not None and 0.5 * ATM <= pressure <= 5.0 * ATM)
            if pressure is not None
            else True
        )

        ternary_prereqs = {
            "MK_gt_30pct": mk_check,
            "high_purity_middle": purity_check,
            "suitable_column_pressure": suitable_pressure,
        }
        all_prereqs_met = all(ternary_prereqs.values())

        questions_evaluated.append(
            {
                "Q_ternary_prereqs": "DWC/TCD prerequisite check",
                "MK_component_gt_30mol%": "YES" if mk_check else "NO",
                "high_purity_middle_product": "YES" if purity_check else "NO",
                "suitable_column_pressure": "YES" if suitable_pressure else "NO",
                "all_met": "YES" if all_prereqs_met else "NO",
            }
        )

        if all_prereqs_met:
            pre_recommendations.append(
                {
                    "R+": "DWC; TCD -> proceed to PI matrix for DWC/TCD scoring",
                    "reason": "All three ternary prerequisites met: MK > 30%, "
                    "high purity middle required, suitable column pressure.",
                }
            )
            flags_for_pi_matrix["dwc_tcd_applicable"] = True
        else:
            failed = [k for k, v in ternary_prereqs.items() if not v]
            pre_recommendations.append(
                {
                    "R+": "Distillation sequences (direct/indirect) -> binary PI matrix on each sub-separation",
                    "reason": f"DWC/TCD prerequisites NOT met: {', '.join(failed)}. "
                    "Use conventional distillation sequences instead.",
                }
            )
            flags_for_pi_matrix["dwc_tcd_applicable"] = False

    elif number_of_products > 3:
        questions_evaluated.append(
            {
                "Q+": f"Number of outlet streams = {number_of_products}",
                "answer": f"{number_of_products} products (multicomponent)",
            }
        )
        pre_recommendations.append(
            {
                "R+": "Kaibel column; TCD; distillation sequences",
                "reason": f"For {number_of_products}-product separation, consider "
                "Kaibel column, thermally coupled distillation, or distillation sequences.",
            }
        )
        flags_for_pi_matrix["dwc_tcd_applicable"] = False

    # ── All Q1-Q6 NO → not resolved, continue to PI matrix ──
    return {
        "questions_evaluated": questions_evaluated,
        "pre_recommendations": pre_recommendations,
        "front_end_recommendations": front_end_recommendations,
        "flags_for_pi_matrix": flags_for_pi_matrix,
        "resolved": False,
        "resolved_by": None,
        "recommended_methods": [],
    }


# ═══════════════════════════════════════════════════════════════════════
#  Pydantic schemas
# ═══════════════════════════════════════════════════════════════════════


class SelectSeparationMethodsInput(BaseModel):
    number_of_products: int = Field(
        default=2, ge=2, le=10, description="2 for binary, >=3 for ternary+"
    )
    azeotrope: bool = Field(default=False, description="True if azeotropic mixture")
    pressure_sensitive_azeotrope: bool = Field(
        default=False, description="True if azeotrope is pressure-sensitive (for PSD)"
    )
    relative_volatility: float | list[float | None] | None = Field(
        default=1.5, description="Relative volatility alpha (None: not known)"
    )
    heat_of_vaporization: list[float | None] = Field(
        default=[], description="Component Hvap [kJ/mol]; None if unknown"
    )
    pressure: float = Field(default=1.01325, gt=0, description="Operating pressure [bar]")
    recovery: float = Field(default=0.9, ge=0, le=1, description="Overall recovery [0-1]")
    purity: float = Field(default=0.95, ge=0, le=1, description="Product purity [0-1]")
    viscosity: list[float | None] = Field(default=[], description="Component viscosity [cP]")
    diffusion_coefficient: list[float | None] = Field(
        default=[], description="Component diffusivity [m2/s]"
    )
    reflux_ratio: float = Field(default=1.5, ge=0, description="Minimum/operating reflux ratio")
    # High-level question inputs
    has_solidification_risk: bool = Field(default=False)
    has_non_condensable: bool = Field(default=False)
    has_thermosensitive: bool = Field(default=False)
    large_light_fraction: bool = Field(default=False)
    large_heavy_fraction: bool = Field(default=False)
    # Component data (boiling_points_K is REQUIRED)
    boiling_points_K: list[float] = Field(
        ...,
        description="Component boiling points [K], in the order of component_names (sorted "
        "by Tb internally). REQUIRED.",
    )
    molar_fractions: list[float] = Field(
        default=[], description="Component molar fractions for DSE calculation"
    )
    middle_key_fraction: float | None = Field(
        default=None, description="Middle key molar fraction (ternary)"
    )
    high_purity_middle: bool = Field(
        default=False, description="High purity required for middle product (ternary)"
    )
    component_names: list[str] = Field(
        default=[], description="Component names (same order as boiling_points_K)"
    )


class SeparationMethodSelectionOutput(BaseModel):
    """Output schema for separation method selection tool."""

    tool: str = Field(
        description="tool used to determine the separation method",
        default="select_separation_methods",
    )
    system_class: str = Field(description="system class description")
    high_level_assessment: dict = Field(
        default_factory=dict,
        description="Results from high-level pre-questions (Q1-Q7)",
    )
    cop_analysis: dict | None = Field(
        default=None, description="COP analysis for HPAD/HIDiC if applicable"
    )
    dse_analysis: dict | None = Field(default=None, description="DSE analysis for ternary+ systems")
    pi_matrix_results: dict = Field(default_factory=dict, description="PI matrix scoring results")
    ranked_methods: list = Field(default_factory=list, description="Methods ranked by score")
    additional_notes: list[str] = Field(
        default_factory=list, description="Additional notes and recommendations"
    )
    downstream_representation: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Every method the result names (ranked methods first, in rank order, then "
        "the high-level recommendations) -> how core can represent it downstream: representation "
        "(predictive, shortcut, specified_split, none or unknown), evidence (tested: a core "
        "test solves the arrangement; untested: the model form only, not validated) and "
        "status (separations.coverage)",
    )

    @model_validator(mode="after")
    def _representations(self) -> SeparationMethodSelectionOutput:
        if not self.downstream_representation:
            named = methods_named(self.ranked_methods)
            named += [m for m in methods_named(self.high_level_assessment) if m not in named]
            self.downstream_representation = {m: representation_of(m) for m in named}
        return self


class SeparationMethodSelectionReturn(BaseModel):
    """Return schema for separation method selection tool."""

    tool: str = Field(
        description="tool used to determine the separation method",
        default="select_separation_methods",
    )
    result: SeparationMethodSelectionOutput | None = Field(
        default=None, description="selection result, if successful"
    )
    errors: list[str] | None = Field(default=None, description="list of error messages, if any")
    provided_inputs: SelectSeparationMethodsInput = Field(
        description="Inputs provided to the selection tool"
    )
    assumptions: list[str] | None = Field(
        default=None, description="List of assumptions made during selection"
    )
    input_provenance: list[dict[str, Any]] | None = Field(
        default=None,
        description="With retrieved properties (separations.inputs): every input value with "
        "its source (caller, NIST, Thermo, GRAPPA, HANNA, Derived) and metadata",
    )
    missing_inputs: list[dict[str, Any]] | None = Field(
        default=None,
        description="With retrieved properties: the inputs no source gave, with the reason",
    )


# ═══════════════════════════════════════════════════════════════════════
#  Core PI matrix application for binary sub-separations
# ═══════════════════════════════════════════════════════════════════════


def _apply_pi_matrix_binary(
    boiling_point_diff: float | None,
    relative_volatility: float | None,
    heat_of_vaporization: list[float | None],
    pressure: float,
    recovery: float,
    purity: float,
    viscosity: list[float | None],
    diffusion_coefficient: list[float | None],
    reflux_ratio: float,
    exclude_methods: list[str] | None = None,
    boiling_points_K: list[float] | None = None,
) -> dict[str, Any]:
    """Apply the PI matrix (Figure 3) to a binary sub-separation.

    *boiling_points_K* are the light and the heavy key's normal boiling points (K) of this
    split, for the COP estimate; without them the COP is not computed. Returns scoring for all
    applicable technologies including COP analysis.
    """
    band = _delta_tb_band(boiling_point_diff)

    active_criteria = _identify_active_criteria(
        relative_volatility=relative_volatility,
        heat_of_vaporization=heat_of_vaporization,
        pressure_bar=pressure,
        recovery=recovery,
        purity=purity,
        viscosity_cp=viscosity,
        diffusion_m2s=diffusion_coefficient,
        reflux_ratio=reflux_ratio,
    )

    exclude = set(exclude_methods or [])
    per_method_scores = []
    notes = []

    for method_name, method_caps in PI_MATRIX.items():
        if method_name in exclude:
            per_method_scores.append(
                {
                    "method": method_name,
                    "vetoed": "YES",
                    "veto_factor": "excluded_by_high_level_question",
                    "final_score": 0.0,
                }
            )
            continue

        score_result = _score_method(method_caps, band, active_criteria)
        score_result["method"] = method_name

        # COP check for HPAD and HIDiC when delta_Tb band is 20-60 or >60
        if method_name in ("HPAD", "HIDiC") and band in ("dTb_20_60", "dTb_gt_60"):
            pair = boiling_points_K or []
            cop = _compute_cop(min(pair), max(pair)) if len(pair) == 2 else None
            if cop is not None:
                score_result["COP_estimated"] = cop
                if cop >= 3.0:
                    # COP is favorable -> upgrade from B to recommended
                    score_result["COP_recommendation"] = "FAVORABLE"
                    notes.append(
                        f"{method_name}: COP ~ {cop} (>= 3.0) -> recommended despite "
                        f"delta_Tb in {band} range."
                    )
                    # Upgrade the band mark contribution (only if not vetoed)
                    if (
                        score_result["mark_details"].get("deltaTb_band") == "B"
                        and score_result["vetoed"] == "NO"
                    ):
                        score_result["final_score"] += 0.5  # B->A equivalent bonus
                else:
                    score_result["COP_recommendation"] = "MARGINAL"
                    notes.append(
                        f"{method_name}: COP ~ {cop} (< 3.0) -> marginal; further "
                        f"detailed check needed."
                    )
            else:
                score_result["COP_recommendation"] = "UNABLE_TO_COMPUTE"

        per_method_scores.append(score_result)

    # Rank by final score, excluding vetoed
    ranked = sorted(
        [m for m in per_method_scores if m["final_score"] > 0.0],
        key=lambda r: (-r["final_score"], r["method"]),
    )

    return {
        "delta_Tb_band": band,
        "active_criteria": active_criteria,
        "per_method_scores": per_method_scores,
        "ranked_methods": [
            {
                "method": r["method"],
                "final_score": r["final_score"],
                **({k: r[k] for k in ("COP_estimated", "COP_recommendation") if k in r}),
            }
            for r in ranked
        ],
        "notes": notes,
    }


# ═══════════════════════════════════════════════════════════════════════
#  Core selection logic
# ═══════════════════════════════════════════════════════════════════════


def _compute_boiling_point_diffs(boiling_points_K: list[float]) -> list[float]:
    """Compute adjacent boiling-point differences from sorted boiling points.

    Parameters
    ----------
    boiling_points_K : list[float]
        Component boiling points in K, sorted ascending.

    Returns
    -------
    list[float]
        Adjacent-pair ΔTb values (len = n_components - 1).
    """
    sorted_bps = sorted(boiling_points_K)
    return [sorted_bps[i + 1] - sorted_bps[i] for i in range(len(sorted_bps) - 1)]


def select_separation_methods_core(
    number_of_products: int = 2,
    azeotrope: bool = False,
    pressure_sensitive_azeotrope: bool = False,
    boiling_points_K: list[float] | None = None,
    relative_volatilities: float | list[float] | None = 1.5,
    heat_of_vaporization: list[float | None] | None = None,
    pressure: float = 1.01325,
    recovery: float = 0.9,
    purity: float = 0.95,
    viscosity: list[float | None] | None = None,
    diffusion_coefficient: list[float | None] | None = None,
    reflux_ratio: float = 1.5,
    # High-level question flags
    has_solidification_risk: bool = False,
    has_non_condensable: bool = False,
    has_thermosensitive: bool = False,
    large_light_fraction: bool = False,
    large_heavy_fraction: bool = False,
    # Ternary-specific
    molar_fractions: list[float] | None = None,
    middle_key_fraction: float | None = None,
    high_purity_middle: bool = False,
    # Component identification
    component_names: list[str] | None = None,
) -> SeparationMethodSelectionOutput:
    """Core selection logic implementing the full paper methodology.

    boiling_points_K is REQUIRED — boiling-point differences are computed
    internally from adjacent pairs (sorted ascending). The per-component lists
    (component_names, heat_of_vaporization, viscosity, diffusion_coefficient,
    molar_fractions) are in the order of boiling_points_K, which need not be
    ascending: they are sorted by boiling point together, so that each sub-separation gets its own
    components' properties (pre-release issue 220). relative_volatilities are per adjacent
    pair in boiling order.
    """

    # -- Input validation --
    if number_of_products < 2:
        raise ValueError("Number of products must be at least 2")
    if not boiling_points_K or len(boiling_points_K) < 2:
        raise ValueError("boiling_points_K must be provided with at least 2 values")
    if isinstance(relative_volatilities, (int, float)) and relative_volatilities <= 0:
        raise ValueError("Relative volatility must be positive")
    if pressure <= 0:
        raise ValueError("Pressure must be positive")
    if not (0 <= recovery <= 1):
        raise ValueError("Recovery must be between 0 and 1")
    if not (0 <= purity <= 1):
        raise ValueError("Purity must be between 0 and 1")

    # one boiling order for every per-component list (a list of another length is left as is)
    order = sorted(range(len(boiling_points_K)), key=lambda i: boiling_points_K[i])

    def _by_boiling_point(values: list | None) -> list | None:
        if values is None or len(values) != len(order):
            return values
        return [values[i] for i in order]

    boiling_points_K = _by_boiling_point(boiling_points_K)
    component_names = _by_boiling_point(component_names)
    molar_fractions = _by_boiling_point(molar_fractions)
    heat_of_vaporization = _by_boiling_point(heat_of_vaporization) or []
    viscosity = _by_boiling_point(viscosity) or []
    diffusion_coefficient = _by_boiling_point(diffusion_coefficient) or []
    additional_notes: list[str] = []

    # Compute boiling-point differences from boiling_points_K
    boiling_point_diffs = _compute_boiling_point_diffs(boiling_points_K)
    additional_notes.append(
        f"Boiling-point differences computed from boiling_points_K: {boiling_point_diffs} K"
    )

    # Normalize for single-value binary case
    scalar_dtb = boiling_point_diffs[0] if boiling_point_diffs else None
    scalar_rv = (
        relative_volatilities
        if not isinstance(relative_volatilities, list)
        else (relative_volatilities[0] if relative_volatilities else None)
    )

    # -- Guardrail: auto-derive ternary DWC/TCD prerequisites when omitted --
    # The LLM agent often passes middle_key_fraction=None and
    # high_purity_middle=False even when the data is available to infer them.
    if number_of_products == 3:
        if (
            middle_key_fraction is None
            and molar_fractions
            and boiling_points_K
            and len(molar_fractions) == len(boiling_points_K) == 3
        ):
            # Middle key = component with the intermediate boiling point
            paired = sorted(zip(boiling_points_K, molar_fractions, strict=True), key=lambda t: t[0])
            middle_key_fraction = paired[1][1]  # fraction of the middle-boiler
            additional_notes.append(
                f"GUARDRAIL: middle_key_fraction auto-derived as {middle_key_fraction:.4f} "
                "from molar_fractions and boiling_points_K."
            )

        if not high_purity_middle and purity >= 0.99:
            high_purity_middle = True
            additional_notes.append(
                f"GUARDRAIL: high_purity_middle auto-set to True (purity={purity})."
            )

    # -- Step 1: High-level pre-questions (Figure 2) --
    high_level = _evaluate_high_level_questions(
        number_of_products=number_of_products,
        azeotrope=azeotrope,
        pressure_sensitive_azeotrope=pressure_sensitive_azeotrope,
        has_solidification_risk=has_solidification_risk,
        has_non_condensable=has_non_condensable,
        has_thermosensitive=has_thermosensitive,
        large_light_fraction=large_light_fraction,
        large_heavy_fraction=large_heavy_fraction,
        boiling_point_diff=scalar_dtb,
        middle_key_fraction=middle_key_fraction,
        high_purity_middle=high_purity_middle,
        pressure=pressure,
        boiling_points_K=boiling_points_K[:2] if number_of_products == 2 else None,
    )

    # -- Step 2: Check if pre-screen resolved the selection --
    if high_level.get("resolved"):
        resolved_by = high_level["resolved_by"]

        # Collect additional notes from front-end recommendations (Q3-Q5)
        resolved_notes: list[str] = [
            f"Selection resolved by pre-screening question {resolved_by}. PI matrix not evaluated.",
        ]
        for fr in high_level.get("front_end_recommendations", []):
            resolved_notes.append(
                f"Front-end ({fr['source']}): {fr['recommendation']} — {fr['reason']}"
            )

        cop_analysis = None
        cop_note = high_level.get("cop_note")
        if cop_note:
            cop_analysis = {"note": cop_note}
            resolved_notes.append(cop_note)

        system_class = f"prescreen_resolved_{resolved_by}"
        if resolved_by == "Q6":
            system_class = "binary_azeotrope"

        return SeparationMethodSelectionOutput(
            tool="select_separation_methods",
            system_class=system_class,
            high_level_assessment=high_level,
            cop_analysis=cop_analysis,
            pi_matrix_results={},
            ranked_methods=high_level["recommended_methods"],
            additional_notes=resolved_notes,
        )

    # -- Step 3: Not resolved — proceed to matrix evaluation --
    # Note: Q3 (thermosensitive) resolves early, so if we reach here,
    # no method exclusions from Q3 apply.
    exclude_methods: list[str] = []

    # Include front-end recommendations (Q3-Q5) as notes
    for fr in high_level.get("front_end_recommendations", []):
        additional_notes.append(
            f"Front-end ({fr['source']}): {fr['recommendation']} — {fr['reason']}"
        )

    # ══════════════════════════════════════════════════════════════
    #  BINARY ZEOTROPIC separation (Matrix A path); an azeotrope is
    #  resolved by Q6 in the pre-screen and never reaches the matrix
    # ══════════════════════════════════════════════════════════════
    if number_of_products == 2:
        pi_results = _apply_pi_matrix_binary(
            boiling_point_diff=scalar_dtb,
            relative_volatility=scalar_rv,
            heat_of_vaporization=heat_of_vaporization,
            pressure=pressure,
            recovery=recovery,
            purity=purity,
            viscosity=viscosity,
            diffusion_coefficient=diffusion_coefficient,
            reflux_ratio=reflux_ratio,
            exclude_methods=exclude_methods,
            boiling_points_K=boiling_points_K[:2],
        )

        return SeparationMethodSelectionOutput(
            tool="select_separation_methods",
            system_class="binary_zeotrope",
            high_level_assessment=high_level,
            cop_analysis={"included_in_pi_matrix_results": True},
            pi_matrix_results=pi_results,
            ranked_methods=pi_results["ranked_methods"],
            additional_notes=pi_results["notes"] + additional_notes,
        )

    # ══════════════════════════════════════════════════════════════
    #  MULTICOMPONENT (>3 products) — suggestion-only path
    #  For >3 components the PI matrix is not applied; we return
    #  high-level suggestions: Kaibel column, TCD, distillation
    #  sequences.
    # ══════════════════════════════════════════════════════════════
    if number_of_products > 3:
        additional_notes.append(
            f"System has {number_of_products} products (>3). "
            "Detailed sub-binary PI matrix evaluation is not supported. "
            "Returning high-level recommendations only."
        )
        return SeparationMethodSelectionOutput(
            tool="select_separation_methods",
            system_class=f"multicomponent ({number_of_products} products)",
            high_level_assessment=high_level,
            pi_matrix_results={},
            ranked_methods=[
                {
                    "method": "Kaibel column",
                    "final_score": 1.0,
                    "reason": (
                        f"For {number_of_products}-product separation, "
                        "Kaibel column can separate 4 products in a single shell."
                    ),
                },
                {
                    "method": "Thermally coupled distillation (TCD)",
                    "final_score": 1.0,
                    "reason": (
                        f"For {number_of_products}-product separation, "
                        "thermally coupled configurations reduce energy consumption."
                    ),
                },
                {
                    "method": "Distillation sequences",
                    "final_score": 1.0,
                    "reason": (
                        f"For {number_of_products}-product separation, "
                        "conventional distillation sequences (direct/indirect) "
                        "are the baseline approach."
                    ),
                },
            ],
            additional_notes=additional_notes,
        )

    # ══════════════════════════════════════════════════════════════
    #  TERNARY separation (exactly 3 products)
    #  Per paper Figure 4:
    #    - Check 3 prerequisites -> DWC/TCD or distillation sequences
    #    - Binary PI matrix on each sub-separation
    # ══════════════════════════════════════════════════════════════
    if number_of_products == 3:
        dse_results = None
        # Step 1: DSE evaluation if boiling points available
        if boiling_points_K and molar_fractions and len(boiling_points_K) >= 3:
            dse_direct = _compute_dse(boiling_points_K, molar_fractions, "direct", component_names)
            dse_indirect = _compute_dse(
                boiling_points_K, molar_fractions, "indirect", component_names
            )
            dse_results = {
                "direct_sequence": dse_direct,
                "indirect_sequence": dse_indirect,
                "preferred_sequence": (
                    "direct"
                    if dse_direct.get("DSE", 0) >= dse_indirect.get("DSE", 0)
                    else "indirect"
                ),
                "interpretation": (
                    "Higher DSE -> more efficient sequence. "
                    "Low DSE -> more room for PI improvement."
                ),
            }
            additional_notes.append(
                f"DSE direct: {dse_direct.get('DSE_percent', 'N/A')}, "
                f"DSE indirect: {dse_indirect.get('DSE_percent', 'N/A')}. "
                f"Preferred: {dse_results['preferred_sequence']} sequence."
            )

        # Step 2: Check if DWC/TCD are applicable (from high-level question flags)
        flags = high_level.get("flags_for_pi_matrix", {})
        dwc_tcd_applicable = flags.get("dwc_tcd_applicable", False)

        # For ternary, use the minimum delta_Tb among adjacent pairs
        min_dtb = min(boiling_point_diffs) if boiling_point_diffs else None
        if isinstance(relative_volatilities, list):
            known_rv = [a for a in relative_volatilities if a is not None]
            min_rv = min(known_rv) if known_rv else None
        else:
            min_rv = relative_volatilities

        band = _delta_tb_band(min_dtb)
        active_criteria = _identify_active_criteria(
            relative_volatility=min_rv,
            heat_of_vaporization=heat_of_vaporization,
            pressure_bar=pressure,
            recovery=recovery,
            purity=purity,
            viscosity_cp=viscosity,
            diffusion_m2s=diffusion_coefficient,
            reflux_ratio=reflux_ratio,
        )

        # Score DWC and TCD ONLY if prerequisites are met
        ternary_scores = {}
        if dwc_tcd_applicable:
            for tech_name, tech_caps in TERNARY_MATRIX.items():
                score = _score_method(tech_caps, band, active_criteria)
                score["method"] = tech_name
                ternary_scores[tech_name] = score
        else:
            additional_notes.append(
                "DWC/TCD not applicable: ternary prerequisites not met. "
                "Using distillation sequences with binary PI matrix on each sub-separation."
            )

        # Step 3: For each binary sub-separation, apply the full PI matrix
        # Sort component names by boiling point (ascending) to match boiling_point_diffs order
        # (every per-component list is in boiling order already, see the top)
        sorted_names = component_names if component_names and len(component_names) >= 3 else None

        binary_sub_results = {}
        sub_labels = [
            (
                f"{sorted_names[0]}/{sorted_names[1]}" if sorted_names else "split_light_middle",
                boiling_point_diffs[0],
            ),
            (
                f"{sorted_names[1]}/{sorted_names[2]}" if sorted_names else "split_middle_heavy",
                boiling_point_diffs[1],
            ),
        ]

        rv_list = (
            relative_volatilities
            if isinstance(relative_volatilities, list)
            else [relative_volatilities] * len(sub_labels)
        )

        def _pair_slice(lst: list | None, idx: int) -> list:
            if not lst or len(lst) < idx + 2:
                return lst or []
            return [lst[idx], lst[idx + 1]]

        for idx, (label, dtb) in enumerate(sub_labels):
            rv = rv_list[idx] if idx < len(rv_list) else None
            sub_result = _apply_pi_matrix_binary(
                boiling_point_diff=dtb,
                relative_volatility=rv,
                heat_of_vaporization=_pair_slice(heat_of_vaporization, idx),
                pressure=pressure,
                recovery=recovery,
                purity=purity,
                viscosity=_pair_slice(viscosity, idx),
                diffusion_coefficient=_pair_slice(diffusion_coefficient, idx),
                reflux_ratio=reflux_ratio,
                exclude_methods=exclude_methods,
                boiling_points_K=_pair_slice(boiling_points_K, idx),
            )
            binary_sub_results[label] = sub_result

        # Combine ranked methods — grouped by level so each binary
        # sub-pair has its own recommendation list instead of one flat list.
        grouped_ranked: list[dict[str, Any]] = []

        # Add DWC/TCD only if applicable
        if ternary_scores:
            ternary_methods = [
                {"method": tech_name, "final_score": score["final_score"]}
                for tech_name, score in ternary_scores.items()
                if score["final_score"] > 0
            ]
            if ternary_methods:
                ternary_methods.sort(key=lambda r: (-r["final_score"], r["method"]))
                grouped_ranked.append(
                    {
                        "group": "ternary_integration",
                        "description": "Technologies for integrated ternary separation (DWC/TCD)",
                        "methods": ternary_methods,
                    }
                )

        # Per binary sub-pair — each pair gets its own group
        for sub_label, sub_res in binary_sub_results.items():
            pair_methods = []
            for m in sub_res.get("ranked_methods", []):
                entry: dict[str, Any] = {
                    "method": m["method"],
                    "final_score": m["final_score"],
                }
                for k in ("COP_estimated", "COP_recommendation"):
                    if k in m:
                        entry[k] = m[k]
                pair_methods.append(entry)
            if pair_methods:
                pair_methods.sort(key=lambda r: (-r["final_score"], r["method"]))
                grouped_ranked.append(
                    {
                        "group": f"binary_sub ({sub_label})",
                        "description": (
                            f"Recommended methods for the {sub_label} binary sub-separation"
                        ),
                        "delta_Tb_band": sub_res["delta_Tb_band"],
                        "active_criteria": sub_res["active_criteria"],
                        "methods": pair_methods,
                    }
                )

        # Collect all binary sub-separation notes
        for sub_res in binary_sub_results.values():
            additional_notes.extend(sub_res.get("notes", []))

        sys_class = "ternary"
        if dwc_tcd_applicable:
            sys_class += " (DWC/TCD applicable)"
        else:
            sys_class += " (distillation sequences)"

        return SeparationMethodSelectionOutput(
            tool="select_separation_methods",
            system_class=sys_class,
            high_level_assessment=high_level,
            dse_analysis=dse_results,
            cop_analysis={"included_in_binary_sub_separation_results": True},
            pi_matrix_results={
                **(
                    {
                        "ternary_level_DWC_TCD": {
                            tech: {
                                "mark_details": s["mark_details"],
                                "final_score": s["final_score"],
                                "vetoed": s["vetoed"],
                            }
                            for tech, s in ternary_scores.items()
                        }
                    }
                    if ternary_scores
                    else {"ternary_level_DWC_TCD": "NOT_APPLICABLE (prerequisites not met)"}
                ),
                "binary_sub_separations": {
                    label: {
                        "delta_Tb_band": r["delta_Tb_band"],
                        "active_criteria": r["active_criteria"],
                        "ranked_methods": r["ranked_methods"],
                    }
                    for label, r in binary_sub_results.items()
                },
            },
            ranked_methods=grouped_ranked,
            additional_notes=additional_notes,
        )

    # Fallback (should not reach here)
    raise ValueError(f"Unsupported configuration: products={number_of_products}")


# ═══════════════════════════════════════════════════════════════════════
#  Selection tools (Tool 2 & 3) — public API
# ═══════════════════════════════════════════════════════════════════════


def _apply_binary_guardrails(
    large_light_fraction: bool,
    large_heavy_fraction: bool,
    molar_fractions: list[float] | None,
    boiling_points_K: list[float] | None,
    threshold: float = 0.80,
) -> tuple[bool, bool, list[str]]:
    """Validate molar_fractions and override large_light/heavy flags if needed.

    Returns (large_light_fraction, large_heavy_fraction, warnings).
    """
    warnings: list[str] = []

    # ── Validate molar_fractions ──
    fractions_valid = False
    if molar_fractions and len(molar_fractions) == 2:
        all_in_range = all(0.0 <= x <= 1.0 for x in molar_fractions)
        sum_ok = abs(sum(molar_fractions) - 1.0) < 0.05
        if all_in_range and sum_ok:
            fractions_valid = True
        else:
            warnings.append(
                f"WARNING: molar_fractions={molar_fractions} do not look like valid "
                f"mole fractions (each must be in [0,1] and sum to ~1.0, got "
                f"sum={sum(molar_fractions):.4f}). Skipping composition-based "
                f"overrides for large_light_fraction / large_heavy_fraction."
            )

    if not fractions_valid:
        return large_light_fraction, large_heavy_fraction, warnings

    assert molar_fractions is not None  # guaranteed by fractions_valid

    if boiling_points_K and len(boiling_points_K) == 2:
        # Identify lightest (lowest Tb) and heaviest (highest Tb) components
        if boiling_points_K[0] <= boiling_points_K[1]:
            x_light, x_heavy = molar_fractions[0], molar_fractions[1]
        else:
            x_light, x_heavy = molar_fractions[1], molar_fractions[0]

        computed_llf = x_light > threshold
        computed_lhf = x_heavy > threshold

        if large_light_fraction != computed_llf:
            warnings.append(
                f"GUARDRAIL OVERRIDE: large_light_fraction was {large_light_fraction} "
                f"but x_light={x_light:.4f} {'>' if computed_llf else '<='} "
                f"{threshold}. Corrected to {computed_llf}."
            )
            large_light_fraction = computed_llf

        if large_heavy_fraction != computed_lhf:
            warnings.append(
                f"GUARDRAIL OVERRIDE: large_heavy_fraction was {large_heavy_fraction} "
                f"but x_heavy={x_heavy:.4f} {'>' if computed_lhf else '<='} "
                f"{threshold}. Corrected to {computed_lhf}."
            )
            large_heavy_fraction = computed_lhf
    else:
        # No boiling points but have fractions — check if both are below threshold
        x_max = max(molar_fractions)
        if large_light_fraction and x_max <= threshold:
            warnings.append(
                f"GUARDRAIL OVERRIDE: large_light_fraction was True but max "
                f"molar fraction is {x_max:.4f} <= {threshold}. "
                f"Corrected to False."
            )
            large_light_fraction = False
        if large_heavy_fraction and x_max <= threshold:
            warnings.append(
                f"GUARDRAIL OVERRIDE: large_heavy_fraction was True but max "
                f"molar fraction is {x_max:.4f} <= {threshold}. "
                f"Corrected to False."
            )
            large_heavy_fraction = False

    return large_light_fraction, large_heavy_fraction, warnings


def select_binary_separation_methods(
    component_names: list[str],
    # Composition data for guardrail validation
    molar_fractions: list[float] | None,
    boiling_points_K: list[float],
    azeotrope: bool = False,
    pressure_sensitive_azeotrope: bool = False,
    relative_volatility: float = 1.5,
    heat_of_vaporization: list[float | None] | None = None,
    pressure: float = 1.01325,
    recovery: float = 0.9,
    purity: float = 0.95,
    viscosity: list[float | None] | None = None,
    diffusion_coefficient: list[float | None] | None = None,
    reflux_ratio: float = 1.5,
    # High-level question flags
    has_solidification_risk: bool = False,
    has_non_condensable: bool = False,
    has_thermosensitive: bool = False,
    large_light_fraction: bool = False,
    large_heavy_fraction: bool = False,
) -> SeparationMethodSelectionReturn:
    """Select separation methods for a BINARY mixture.

    boiling_points_K is REQUIRED (2 values). The boiling-point difference
    is computed internally from the two boiling points.

    Implements the full Li et al. (2025) methodology:
    1. High-level pre-questions (Q1-Q7)
    2. COP calculation for HPAD/HIDiC when delta_Tb >= 20 deg C, at the
       mixture's boiling points
    3. PI matrix scoring
    4. For azeotropes (Q6 resolves, the PI matrix is not evaluated): PSD (if
       pressure-sensitive), MAD, ED/AD, E-DWC and A-DWC at score 1.0, and HPAD
       and HIDiC at 1.0 with a COP of 3 or more, else 0.5

    The screening flags (Q1-Q6) must be decided by the caller from chemical
    knowledge and retrieved property data; the tool does not derive them.
    The tool then:
    - overrides large_light_fraction/large_heavy_fraction if molar_fractions
      contradict them (so always provide molar_fractions),
    - warns if azeotrope=true but relative_volatility is far from 1.0,
    - excludes HIDiC and CyDist when has_thermosensitive=true,
    - returns the azeotrope-specific methods (PSD if pressure-sensitive, MAD,
      ED/AD, E-DWC, A-DWC, HPAD/HIDiC with the COP check) when azeotrope=true,
    - includes pre-recommendations (crystallization, membrane,
      preconcentration, ...) in its output.

    All numeric inputs must be actual retrieved values; the numeric defaults
    are placeholders only.

    Parameters:
    -----------
    component_names: list[str]
        list of component names (for reporting only)
    molar_fractions: list[float] | None
        Feed molar fractions [x1, x2] — tool validates Q4/Q5 from these
    boiling_points_K: [float, float]
        Normal boiling points in K [Tb1, Tb2] — REQUIRED. Tool computes Delta Tb internally.
    azeotrope: boolean
        true if azeotropic behavior detected (from Q6), i.e. alpha crosses 1.0.
        Positive deviation from Raoult's law alone does not make a system azeotropic.
    pressure_sensitive_azeotrope: boolean
        true if azeotrope shifts significantly with pressure (from Q6 sub-check)
    relative_volatility: float
        alpha value, from retrieved vapor pressures + activity coefficients
        (alpha = gamma1*Psat1 / (gamma2*Psat2)); never estimated
    heat_of_vaporization: [float, float]
        Component Hvap values in kJ/mol
    pressure: float
        Operating pressure in bar
    recovery: float
        Target recovery (0-1)
    purity: float
        Target purity (0-1)
    viscosity: [float, float]
        Component viscosity values in mPa·s (= cP)
    diffusion_coefficient: [float, float]
        Component diffusivity values in m2/s
    reflux_ratio: float
        Minimum or operating reflux ratio
    has_solidification_risk: boolean
        from Q1: any component freezes at operating conditions?
    has_non_condensable: boolean
        from Q2: significant non-condensable components?
    has_thermosensitive: boolean
        from Q3: degradation/polymerization at operating T?
    large_light_fraction: boolean
        from Q4: lightest component x_feed > 0.80? (strict numeric comparison,
        e.g. 69.81 mol% -> 0.6981 -> false)
    large_heavy_fraction: boolean
        from Q5: heaviest component x_feed > 0.80?

    """
    # ── Guardrail: auto-compute Q4/Q5 from molar_fractions if provided ──
    large_light_fraction, large_heavy_fraction, guardrail_warnings = _apply_binary_guardrails(
        large_light_fraction=large_light_fraction,
        large_heavy_fraction=large_heavy_fraction,
        molar_fractions=molar_fractions,
        boiling_points_K=boiling_points_K,
    )

    # ── Guardrail: warn if azeotrope=True but relative_volatility is far from 1 ──
    if azeotrope and relative_volatility is not None and relative_volatility > 1.5:
        guardrail_warnings.append(
            f"WARNING: azeotrope=True but relative_volatility={relative_volatility:.2f} "
            f"is well above 1.0, suggesting the system may be zeotropic (not azeotropic). "
            f"An azeotrope requires alpha to cross 1.0 at some composition. "
            f"Verify azeotropy from VLE data."
        )

    provided_inputs = SelectSeparationMethodsInput(
        number_of_products=2,
        azeotrope=azeotrope,
        pressure_sensitive_azeotrope=pressure_sensitive_azeotrope,
        relative_volatility=relative_volatility,
        heat_of_vaporization=heat_of_vaporization or [],
        pressure=pressure,
        recovery=recovery,
        purity=purity,
        viscosity=viscosity or [],
        diffusion_coefficient=diffusion_coefficient or [],
        reflux_ratio=reflux_ratio,
        has_solidification_risk=has_solidification_risk,
        has_non_condensable=has_non_condensable,
        has_thermosensitive=has_thermosensitive,
        large_light_fraction=large_light_fraction,
        large_heavy_fraction=large_heavy_fraction,
        boiling_points_K=boiling_points_K,
        molar_fractions=molar_fractions or [],
        component_names=component_names,
    )
    try:
        result = select_separation_methods_core(
            number_of_products=2,
            azeotrope=azeotrope,
            pressure_sensitive_azeotrope=pressure_sensitive_azeotrope,
            boiling_points_K=boiling_points_K,
            relative_volatilities=relative_volatility,
            heat_of_vaporization=heat_of_vaporization,
            pressure=pressure,
            recovery=recovery,
            purity=purity,
            viscosity=viscosity,
            diffusion_coefficient=diffusion_coefficient,
            reflux_ratio=reflux_ratio,
            has_solidification_risk=has_solidification_risk,
            has_non_condensable=has_non_condensable,
            has_thermosensitive=has_thermosensitive,
            large_light_fraction=large_light_fraction,
            large_heavy_fraction=large_heavy_fraction,
        )
        return SeparationMethodSelectionReturn(
            tool="select_binary_separation_methods",
            result=result,
            provided_inputs=provided_inputs,
            assumptions=guardrail_warnings if guardrail_warnings else None,
        )
    except Exception as e:  # noqa: BLE001 - the tool returns any failure as an error  # pragma: no cover
        return SeparationMethodSelectionReturn(
            tool="select_binary_separation_methods",
            errors=[str(e)],
            result=None,
            provided_inputs=provided_inputs,
            assumptions=guardrail_warnings if guardrail_warnings else None,
        )


def select_multicomponent_separation_methods(
    # Component identification
    component_names: list[str],
    boiling_points_K: list[float],
    relative_volatilities: list[float],
    heat_of_vaporization: list[float | None] | None = None,
    pressure: float = 1.01325,
    recovery: float = 0.9,
    purity: float = 0.95,
    viscosity: list[float | None] | None = None,
    diffusion_coefficient: list[float | None] | None = None,
    reflux_ratio: float = 1.5,
    # High-level question flags
    has_solidification_risk: bool = False,
    has_non_condensable: bool = False,
    has_thermosensitive: bool = False,
    large_light_fraction: bool = False,
    large_heavy_fraction: bool = False,
    # DSE inputs
    molar_fractions: list[float] | None = None,
    middle_key_fraction: float | None = None,
    high_purity_middle: bool = False,
) -> SeparationMethodSelectionReturn:
    """
    Select separation methods for TERNARY zeotropic mixtures.

    boiling_points_K is REQUIRED. Boiling-point differences are computed internally from adjacent pairs (sorted ascending).

    For ternary (3 products):
      1. DSE evaluation for sequence pre-screening
      2. High-level pre-questions (Q1-Q7)
      3. DWC/TCD scoring at ternary level
      4. Binary PI matrix on EACH sub-separation
      5. COP calculation for HPAD/HIDiC on each sub-separation

    The screening flags (Q1-Q5) must be decided by the caller; unlike the
    binary tool, this tool trusts them as given and does not re-check Q4/Q5
    against molar_fractions. DSE is computed automatically when
    boiling_points_K and molar_fractions are provided. The tool always runs with
    azeotrope=False: azeotrope-specific methods (PSD, ED/AD, E-DWC, A-DWC) are
    only implemented for binary separations. All numeric inputs must be actual
    retrieved values; the numeric defaults are placeholders only.

    Parameters
    ----------
    component_names: list[str]:
        Components in the mixture. All per-component input lists (boiling points, Hvap,
        viscosity, diffusivity, molar fractions) MUST be in the same order as
        component_names; the tool sorts them together by boiling point.
    boiling_points_K: list[float]
        List of component boiling points in Kelvin. Tool computes Delta Tb internally.
    relative_volatilities: list[float]
        ADJACENT pair alpha values in boiling order (lightest pair first)
        [alpha_12, alpha_23, ...] (n-1 values), from
        retrieved vapor pressures + activity coefficients - never estimated from
        boiling point ratios. An incorrect alpha vetoes methods like DWC, TCD,
        ConvDist and HiGee.
    heat_of_vaporization: list[float | None] | None = None
        List of Hvap values in kJ/mol for all components
    pressure: float = 1.01325
        Operating pressure in bar
    recovery: float = 0.9
        Target recovery (0-1)
    purity: float = 0.95
        Target purity (0-1)
    viscosity: list[float | None] | None = None
        Component viscosity values in mPa·s (= cP)
    diffusion_coefficient: list[float | None] | None = None
        Component diffusivity values in m2/s
    reflux_ratio: float = 1.5
        Minimum or operating reflux ratio
    has_solidification_risk: bool = False
        Flag indicating if there is a risk of solidification during separation
    has_non_condensable: bool = False
        Flag indicating if non-condensable gases are present that could affect separation
    has_thermosensitive: bool = False
        Flag indicating if any components are thermosensitive and could degrade at high temperatures
    large_light_fraction: bool = False
        Flag indicating if the lightest component has a large molar fraction (e.g., >80%), which can impact method selection
    large_heavy_fraction: bool = False
        Flag indicating if the heaviest component has a large molar fraction (e.g., >80%), which can impact method selection
    molar_fractions: list[float] | None = None
        Component molar fractions for DSE calculation; must be in same order as component_names
    middle_key_fraction: float | None = None
        Molar fraction of the middle key component for ternary separation; required if high_purity_middle is True.
        Strongly preferred; if not provided for a ternary mixture, the tool derives it from molar_fractions and boiling_points_K.
    high_purity_middle: bool = False
        Whether high purity is required for the middle product, which can influence the preferred separation sequence and method.
        For a ternary mixture, the tool sets it to True when purity >= 0.99.

    Returns
    -------
    SeparationMethodSelectionReturn
        Contains the selected separation methods, provided inputs, assumptions, and any errors encountered during processing.
    """
    provided_inputs = SelectSeparationMethodsInput(
        relative_volatility=relative_volatilities,
        heat_of_vaporization=heat_of_vaporization or [],
        pressure=pressure,
        recovery=recovery,
        purity=purity,
        viscosity=viscosity or [],
        diffusion_coefficient=diffusion_coefficient or [],
        reflux_ratio=reflux_ratio,
        has_solidification_risk=has_solidification_risk,
        has_non_condensable=has_non_condensable,
        has_thermosensitive=has_thermosensitive,
        large_light_fraction=large_light_fraction,
        large_heavy_fraction=large_heavy_fraction,
        boiling_points_K=boiling_points_K,
        molar_fractions=molar_fractions or [],
        middle_key_fraction=middle_key_fraction,
        high_purity_middle=high_purity_middle,
        component_names=component_names or [],
    )

    assumptions = [
        "Boiling-point differences are computed internally from boiling_points_K.",
    ]
    # check if all lists are of correct length (if provided): an error in the return, as any
    # other invalid input
    n = len(component_names)
    errors = []
    # exactly n values: a list of another length cannot be sorted with the boiling points and
    # would be paired with the wrong sub-separation (pre-release issue 220)
    if not boiling_points_K or len(boiling_points_K) != n:
        errors.append(
            f"boiling_points_K must have {n} values for {n}-component separation, "
            f"got {len(boiling_points_K or [])}"
        )
    if relative_volatilities and len(relative_volatilities) != n - 1:
        errors.append(
            f"relative_volatilities must have {n - 1} values "
            f"for {n}-component separation, got {len(relative_volatilities)}"
        )
    for name, values in (
        ("heat_of_vaporization", heat_of_vaporization),
        ("viscosity", viscosity),
        ("diffusion_coefficient", diffusion_coefficient),
        ("molar_fractions", molar_fractions),
    ):
        if values and len(values) != n:
            errors.append(
                f"{name} must have {n} values for {n}-component separation, got {len(values)}"
            )
    if errors:
        return SeparationMethodSelectionReturn(
            tool="select_multicomponent_separation_methods",
            errors=errors,
            result=None,
            provided_inputs=provided_inputs,
            assumptions=assumptions,
        )

    try:
        result = select_separation_methods_core(
            number_of_products=len(component_names),
            azeotrope=False,
            boiling_points_K=boiling_points_K,
            relative_volatilities=relative_volatilities,
            heat_of_vaporization=heat_of_vaporization,
            pressure=pressure,
            recovery=recovery,
            purity=purity,
            viscosity=viscosity,
            diffusion_coefficient=diffusion_coefficient,
            reflux_ratio=reflux_ratio,
            has_solidification_risk=has_solidification_risk,
            has_non_condensable=has_non_condensable,
            has_thermosensitive=has_thermosensitive,
            large_light_fraction=large_light_fraction,
            large_heavy_fraction=large_heavy_fraction,
            molar_fractions=molar_fractions,
            middle_key_fraction=middle_key_fraction,
            high_purity_middle=high_purity_middle,
            component_names=component_names,
        )
        return SeparationMethodSelectionReturn(
            tool="select_multicomponent_separation_methods",
            result=result,
            provided_inputs=provided_inputs,
            assumptions=assumptions,
        )
    except Exception as e:  # noqa: BLE001 - the tool returns any failure as an error  # pragma: no cover
        return SeparationMethodSelectionReturn(
            tool="select_multicomponent_separation_methods",
            errors=[str(e)],
            result=None,
            provided_inputs=provided_inputs,
        )
