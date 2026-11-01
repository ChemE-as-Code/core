"""Screening inputs from the property sources (separations/inputs.py) and the coverage table
(separations/coverage.py).

The stub records below are test fixtures, not property data: they check the plumbing
(precedence, provenance, missing values, ordering). The test against real values takes its
reference from the pinned ``thermo`` package itself (an authoritative computable reference),
not from numbers written here.
"""

from __future__ import annotations

import pytest

from chemeascode.domains.chemistry.properties import PropertyRetriever, Source
from chemeascode.domains.process.separations import coverage
from chemeascode.domains.process.separations.inputs import (
    screening_inputs,
    select_with_retrieved_properties,
)
from chemeascode.domains.process.separations.selection import select_binary_separation_methods


def _stub(records: dict[str, dict]) -> PropertyRetriever:
    """A thermo-only retriever over fixture records (never the network)."""
    return PropertyRetriever(
        fetchers={Source.THERMO: lambda ident, t, p: records.get(ident)},
        sources={Source.THERMO},
    )


# fixture records (plumbing only; not data)
HEAVY = {
    "boiling_point": {"value": 400.0, "units": "K"},
    "molar_mass_g_mol": 100.0,
    "heat_of_vaporization": {"value": 35.0, "units": "kJ/mol"},
    "liquid_viscosity": {"value": 0.5, "units": "mPa*s"},
    "vapor_pressure": {"value": 1000.0, "units": "Pa"},
}
LIGHT = {
    "boiling_point": {"value": 350.0, "units": "K"},
    "molar_mass_g_mol": 50.0,
    "liquid_viscosity": {"value": 0.3, "units": "mPa*s"},
    "vapor_pressure": {"value": 3.0, "units": "kPa"},
}


def test_values_carry_provenance_and_the_boiling_order():
    found = screening_inputs(
        ["heavy", "light"],
        retriever=_stub({"heavy": HEAVY, "light": LIGHT}),
        temperature_K=330.0,
        molar_fractions=[0.4, 0.6],
    )
    assert found.component_names == ["light", "heavy"]
    assert found.order == [1, 0]
    assert found.values["boiling_points_K"] == [350.0, 400.0]
    assert found.values["molar_fractions"] == [0.6, 0.4]
    assert found.values["relative_volatilities"] == [pytest.approx(3.0)]
    tb = [p for p in found.provenance if p["input"] == "boiling_points_K"]
    assert {p["source"] for p in tb} == {"Thermo"} and {p["unit"] for p in tb} == {"K"}
    alpha = next(p for p in found.provenance if p["input"] == "relative_volatilities")
    assert alpha["source"] == "Derived" and alpha["metadata"]["ideal"] is True
    assert any("ideal ratio" in w for w in found.warnings)
    # the light component has no heat of vaporisation: missing, never filled in
    assert found.values["heat_of_vaporization"] == [None, 35.0]
    hvap = next(p for p in found.provenance if p["input"] == "heat_of_vaporization")
    assert hvap["metadata"]["evaluated_at_K"] == 400.0  # thermo at its own boiling point
    missing = {(m["input"], m["component"]) for m in found.missing}
    assert ("heat_of_vaporization", "light") in missing
    assert ("diffusion_coefficient", "light") in missing


def test_caller_values_win_and_temperature_dependent_values_need_a_temperature():
    found = screening_inputs(
        ["heavy", "light"],
        retriever=_stub({"heavy": HEAVY, "light": LIGHT}),
        given={"boiling_points_K": [None, 345.0], "heat_of_vaporization": [36.0, 30.0]},
    )
    assert found.values["boiling_points_K"] == [345.0, 400.0]
    light_tb = next(
        p
        for p in found.provenance
        if p["input"] == "boiling_points_K" and p["component"] == "light"
    )
    assert light_tb["source"] == "caller"
    assert found.values["heat_of_vaporization"] == [30.0, 36.0]
    # no temperature: neither viscosity nor relative volatility is retrieved at a default
    assert found.values["viscosity"] == [None, None]
    assert found.values["relative_volatilities"] == [None]
    reasons = [m["reason"] for m in found.missing if m["input"] == "relative_volatilities"]
    assert "give temperature_K" in reasons[0]


def test_screening_runs_on_retrieved_values_and_reports_what_is_missing():
    ret = select_with_retrieved_properties(
        ["heavy", "light"],
        retriever=_stub({"heavy": HEAVY, "light": LIGHT}),
        temperature_K=330.0,
        molar_fractions=[0.5, 0.5],
    )
    assert ret.errors is None and ret.result is not None
    assert ret.provided_inputs.boiling_points_K == [350.0, 400.0]
    assert ret.provided_inputs.relative_volatility == pytest.approx(3.0)
    assert ret.input_provenance and ret.missing_inputs
    assert any("low_diffusion" in a for a in ret.assumptions)
    # every ranked method says how core represents it downstream
    top = ret.result.ranked_methods[0]["method"]
    assert ret.result.downstream_representation[top]["representation"] in coverage.REPRESENTATIONS


def test_screening_is_refused_without_boiling_points():
    ret = select_with_retrieved_properties(["heavy", "unknown"], retriever=_stub({"heavy": HEAVY}))
    assert ret.result is None
    assert ret.errors == ["normal boiling points are missing for: unknown"]
    assert any(m["component"] == "unknown" for m in ret.missing_inputs)


def test_missing_relative_volatility_is_not_the_placeholder():
    ret = select_with_retrieved_properties(
        ["heavy", "light"], retriever=_stub({"heavy": HEAVY, "light": LIGHT})
    )
    assert ret.provided_inputs.relative_volatility is None
    assert any("RV_1_01_1_15" in a for a in ret.assumptions)


def test_multicomponent_with_a_missing_pair():
    middle = {**HEAVY, "boiling_point": {"value": 375.0, "units": "K"}}
    ret = select_with_retrieved_properties(
        ["heavy", "light", "middle"],
        retriever=_stub({"heavy": HEAVY, "light": LIGHT, "middle": middle}),
        given={"relative_volatilities": [2.5, None]},
        molar_fractions=[0.3, 0.4, 0.3],
    )
    assert ret.errors is None, ret.errors
    assert ret.provided_inputs.component_names == ["light", "middle", "heavy"]
    assert ret.provided_inputs.relative_volatility == [2.5, None]


class _NoRetrieval:
    def get(self, *args, **kwargs):
        raise AssertionError("no retrieval expected")


GIVEN_TERNARY = {
    "boiling_points_K": [300, 350, 400],
    "molar_masses_g_mol": [50, 60, 70],
    "melting_points_K": [100, 110, 120],
    "heat_of_vaporization": [30, 30, 30],
    "relative_volatilities": [2, 2],
}


def test_binary_only_flags_do_not_crash_a_ternary():
    """The same flags for any number of components: azeotrope=False is left
    out with a note, azeotrope=True is refused, never a TypeError."""
    ret = select_with_retrieved_properties(
        ["a", "b", "c"],
        retriever=_NoRetrieval(),
        given=GIVEN_TERNARY,
        azeotrope=False,
        pressure_sensitive_azeotrope=False,
    )
    assert ret.errors is None and ret.result is not None
    assert any("pressure_sensitive_azeotrope=False is not an input" in a for a in ret.assumptions)
    ret = select_with_retrieved_properties(
        ["a", "b", "c"], retriever=_NoRetrieval(), given=GIVEN_TERNARY, azeotrope=True
    )
    assert ret.result is None
    assert ret.errors and "azeotrope screening is binary-only" in ret.errors[0]


def test_a_misspelt_flag_is_an_error_and_a_multicomponent_flag_is_left_out_for_a_binary():
    """Only the other screening's own keywords are left out; a misspelt flag never runs on the
    function's default."""
    given = {k: v[:2] for k, v in GIVEN_TERNARY.items() if k != "relative_volatilities"}
    given["relative_volatilities"] = [2]
    ret = select_with_retrieved_properties(
        ["a", "b"], retriever=_NoRetrieval(), given=given, has_thermosensitve=True
    )
    assert ret.result is None
    assert ret.errors == ["has_thermosensitve is not an input of select_binary_separation_methods"]
    ret = select_with_retrieved_properties(
        ["a", "b", "c"], retriever=_NoRetrieval(), given=GIVEN_TERNARY, purty=0.999
    )
    assert ret.result is None and "purty is not an input" in ret.errors[0]
    ret = select_with_retrieved_properties(
        ["a", "b"], retriever=_NoRetrieval(), given=given, middle_key_fraction=0.3
    )
    assert ret.errors is None and ret.result is not None
    assert any("middle_key_fraction=0.3 is not an input" in a for a in ret.assumptions)


def test_retrieved_values_match_the_thermo_package():
    """Benzene/toluene through the real thermo adapter, checked against thermo's own
    Chemical objects (the reference is the pinned package, not numbers in this test)."""
    thermo = pytest.importorskip("thermo")
    t = 360.0
    found = screening_inputs(
        ["toluene", "benzene"],
        retriever=PropertyRetriever(sources={Source.THERMO}),
        temperature_K=t,
    )
    benzene, toluene = thermo.Chemical("benzene", T=t), thermo.Chemical("toluene", T=t)
    assert found.component_names == ["benzene", "toluene"]
    assert found.values["boiling_points_K"] == [
        pytest.approx(benzene.Tb),
        pytest.approx(toluene.Tb),
    ]
    assert found.values["relative_volatilities"][0] == pytest.approx(
        benzene.Psat / toluene.Psat, rel=1e-6
    )
    # benzene is vapour at 360 K and 1 atm: the saturated liquid's viscosity at T
    liquid = benzene.ViscosityLiquid.T_dependent_property(t)
    assert found.values["viscosity"][0] == pytest.approx(liquid * 1e3, rel=1e-6)
    assert found.values["molar_masses_g_mol"] == [
        pytest.approx(benzene.MW),
        pytest.approx(toluene.MW),
    ]


def test_coverage_names_every_method_the_screening_can_rank():
    from chemeascode.domains.process.separations import selection

    named = [*selection.PI_MATRIX, *selection.TERNARY_MATRIX, "ED/AD"]
    named += [
        "PSD",
        "E-DWC",
        "A-DWC",
        "Crystallization",
        "High pressure distillation column",
        "Membrane separation",
        "Partial condenser",
        "Vacuum distillation",
        "Two columns with second distillate recycled back",
        "Membrane assisted distillation (MAD)",
        "Evaporation",
        "(Steam) stripping",
        "Adsorption",
        "Preconcentration column",
        "Kaibel column",
        "Thermally coupled distillation (TCD)",
        "Distillation sequences",
    ]
    for method in named:
        assert coverage.coverage_of(method) is not None, method
    assert coverage.representation_of("Something new")["representation"] == "unknown"
    rows = {r["technique"]: r for r in coverage.coverage_table()}
    for technique in ("Adsorption", "Membrane separation", "Drying"):
        assert rows[technique]["representation"] == "specified_split"
        assert rows[technique]["units"] == ["component_separator"]
    assert rows["Crystallization"]["representation"] == "predictive"
    assert rows["Crystallization"]["units"] == ["crystallizer"]
    assert rows["Solid-fluid separation"]["units"] == ["solid_separation"]
    assert rows["HIDiC"]["representation"] == "none"
    assert rows["HPAD"]["energy_integration"] == "screening_only"


def test_skill_table_matches_the_coverage_table():
    from pathlib import Path

    import chemeascode

    skill = Path(chemeascode.__file__).parent / (
        "domains/process/skills/separation-method-selection/SKILL.md"
    )
    rows = {
        cells[1].strip(): (cells[2].strip(), cells[3].strip())
        for line in skill.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and len(cells := line.split("|")) > 4
    }
    for row in coverage.coverage_table():
        expected = (row["representation"].replace("_", " "), row["evidence"].replace("_", " "))
        assert rows.get(row["technique"]) == expected, row


def test_untested_arrangements_do_not_read_as_established():
    rows = {r["technique"]: r for r in coverage.coverage_table()}
    for row in rows.values():
        assert row["evidence"] == ("tested" if row["tested"] else "untested") or (
            row["representation"] == "none" and row["evidence"] == "not_applicable"
        )
        if row["evidence"] == "untested":
            assert row["status"] == f"{row['representation']} (untested arrangement)"
    for technique in ("DWC", "Kaibel column", "E-DWC", "A-DWC", "HiGee", "HPAD"):
        assert rows[technique]["evidence"] == "untested", technique
    assert rows["ConvDist"]["status"] == "predictive"
    assert "heat pump: screening estimate only" in rows["HPAD"]["notes"]


def test_plain_screening_reports_representations_too():
    ret = select_binary_separation_methods(
        component_names=["a", "b"],
        molar_fractions=[0.5, 0.5],
        boiling_points_K=[350.0, 400.0],
        relative_volatility=2.0,
        has_non_condensable=True,
    )
    reps = ret.result.downstream_representation
    assert reps["Membrane separation"]["representation"] == "specified_split"
    assert reps["Partial condenser"]["representation"] == "predictive"
    assert reps["Partial condenser"]["evidence"] == "tested"
    assert reps["Membrane separation"]["evidence"] == "untested"
    assert all("evidence" in r and "status" in r for r in reps.values())
