"""Phase determination through thermo (ported from LLM4ChemE tests/tools/test_phase_tools.py)."""

from pathlib import Path

import pytest

from chemeascode.domains.process.thermodynamics.phase import (
    ActivityCoefficientModel,
    EOSHandler,
    EOSModel,
    EOSModelMapping,
    MissingInteractionParametersWarning,
    phase_determination,
)

pytest.importorskip("thermo")


def test_eos_model():
    eos_model = EOSModel(eos_model=EOSModelMapping.PR)
    assert eos_model.eos_model == EOSModelMapping.PR
    assert eos_model.type == "eos_model"


def test_eos_model_str():
    eos_model = EOSModel(eos_model="Peng-Robinson")
    assert eos_model.eos_model == EOSModelMapping.PR
    assert eos_model.type == "eos_model"


def test_eos_handler_initialization():
    eos_handler = EOSHandler(thermodynamic_model="Peng-Robinson")
    assert eos_handler.eos_model == EOSModelMapping.PR


def test_wrapper_function_input_validation():
    result = phase_determination(
        components=["water", "ethanol"],
        overall_composition=[0.5, 0.5],
        temperature_value=298.15,
        temperature_unit="K",
        pressure_value=101325,
        pressure_unit="Pa",
        thermodynamic_model=EOSModel(eos_model="Peng-Robinson"),
        allow_two_liquids=False,
    )
    assert result is not None
    assert result.gas_count == 0
    assert result.liquid_count == 1


def test_wrapper_function_input_validation_SRK():
    # without `cheme data fetch chemsep-srk` (the tests' data dir is empty): kij = 0, a warning
    with pytest.warns(MissingInteractionParametersWarning):
        result = phase_determination(
            components=["water", "ethanol"],
            overall_composition=[0.5, 0.5],
            temperature_value=298.15,
            temperature_unit="K",
            pressure_value=101325,
            pressure_unit="Pa",
            thermodynamic_model=EOSModel(eos_model="Redlich-Kwong-Soave"),
            allow_two_liquids=False,
        )
    assert result is not None
    assert result.gas_count == 0
    assert result.liquid_count == 1


def test_wrapper_function_SRK_outside_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The installed ChemSep RKS database is found whatever the working directory.
    import io
    import zipfile

    from chemeascode.domains.process.thermodynamics.chemsep_srk import install_srk

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ipd/srk.ipd", "[IPD]\n64-17-5 7732-18-5 -.05 Ethanol/Water (test)\n")
    install_srk(buffer.getvalue(), source="test", expected_sha256=None)
    monkeypatch.chdir(tmp_path)
    result = phase_determination(
        components=["water", "ethanol"],
        overall_composition=[0.5, 0.5],
        temperature_value=298.15,
        temperature_unit="K",
        pressure_value=101325,
        pressure_unit="Pa",
        thermodynamic_model=EOSModel(eos_model="Redlich-Kwong-Soave"),
        allow_two_liquids=False,
    )
    assert result.liquid_count == 1
    assert result.notes == []


def test_wrapper_for_activity_coeff_method():
    # Define input parameters for the flash calculation
    components = ["water", "ethanol"]
    temperature = 360.0  # in Kelvin
    pressure = 101325.0  # in Pa
    overall_composition = [0.7, 0.3]

    # Perform the flash calculation
    results = phase_determination(
        components=components,
        overall_composition=overall_composition,
        temperature_value=temperature,
        temperature_unit="K",
        pressure_value=pressure,
        pressure_unit="Pa",
        thermodynamic_model=ActivityCoefficientModel(
            liquid_phase_model="Wilson", vapor_phase_model="Peng-Robinson"
        ),
        allow_two_liquids=False,
    )
    assert results is not None
    assert results.flash_convergence_error is not None and results.flash_convergence_error < 1e-6
    assert results.liquid_count == 1
    assert results.gas_count == 1


def test_pure_component():
    result = phase_determination(
        components=["water"],
        temperature_value=90,
        temperature_unit="Celsius",
        pressure_value=1.0135,
        pressure_unit="bar",
        overall_composition=None,
        thermodynamic_model=ActivityCoefficientModel(
            liquid_phase_model="UNIFAC", vapor_phase_model="ideal_gas"
        ),
        allow_two_liquids=False,
    )
    assert result is not None
    assert result.gas_count == 0
    assert result.liquid_count == 1


def test_nrtl_ethanol_water():
    result = phase_determination(
        components=["ethanol", "water"],
        temperature_value=343.15,
        temperature_unit="K",
        pressure_value=1,
        pressure_unit="MPa",
        overall_composition=[0.252, 0.748],
        thermodynamic_model=ActivityCoefficientModel(
            liquid_phase_model="NRTL", vapor_phase_model="ideal_gas"
        ),
        allow_two_liquids=False,
    )
    assert result is not None
    assert result.gas_count == 0
    assert result.liquid_count == 1


def test_unifac_ethanol_hexane():
    result = phase_determination(
        components=["ethanol", "hexane"],
        temperature_value=298.15,
        temperature_unit="K",
        pressure_value=101325,
        pressure_unit="Pa",
        overall_composition=[0.5, 0.5],
        thermodynamic_model=ActivityCoefficientModel(
            liquid_phase_model="UNIFAC", vapor_phase_model="ideal_gas"
        ),
        allow_two_liquids=False,
    )
    assert result is not None
    assert result.gas_count == 0
    assert result.liquid_count == 1


def test_result_states_units_and_source():
    result = phase_determination(
        components=["water"],
        overall_composition=None,
        temperature_value=150,
        temperature_unit="°C",
        pressure_value=1.0,
        pressure_unit="bar(a)",
        thermodynamic_model={"eos_model": "Peng-Robinson"},
        allow_two_liquids=False,
    )
    assert result.temperature_K == pytest.approx(423.15)
    assert result.pressure_Pa == pytest.approx(1e5)
    assert result.gas_count == 1 and result.liquid_count == 0
    assert "thermo" in result.source


def test_gauge_pressure_is_refused():
    with pytest.raises(ValueError, match="ambient"):
        phase_determination(
            components=["water"],
            overall_composition=None,
            temperature_value=300,
            temperature_unit="K",
            pressure_value=1.0,
            pressure_unit="bar(g)",
            thermodynamic_model={"eos_model": "Peng-Robinson"},
            allow_two_liquids=False,
        )


def test_unknown_model_is_refused():
    with pytest.raises(ValueError, match="Invalid thermodynamic model"):
        phase_determination(
            components=["water"],
            overall_composition=None,
            temperature_value=300,
            temperature_unit="K",
            pressure_value=1.0,
            pressure_unit="bar",
            thermodynamic_model={"eos_model": "peng-robinson"},
            allow_two_liquids=False,
        )
