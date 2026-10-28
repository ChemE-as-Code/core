"""Phase identification: a flash at given temperature, pressure and composition through thermo.

:func:`phase_determination` runs thermo's flash (``FlashVL``, ``FlashVLN`` for two liquids,
``FlashPureVLS`` for one component) with either an equation of state for both phases or an
activity-coefficient model for the liquid and an equation of state or the ideal gas for the
vapour. Interaction parameters come from thermo's ChemSep databases (PR, NRTL, Wilson) and, for
Redlich-Kwong-Soave, from the ChemSep SRK file a user installs with ``cheme data fetch
chemsep-srk`` (``thermodynamics.chemsep_srk``; not shipped, pre-release issue 55); a missing binary
parameter counts as zero, as in thermo. Without the installed file every SRK ``kij`` is zero, as for
Redlich-Kwong: the result's ``notes`` say so and a :class:`MissingInteractionParametersWarning`
is issued. The result's ``interaction_parameters``
(:mod:`~chemeascode.domains.process.thermodynamics.coverage`) lists per pair whether its
parameter is sourced, missing (zero used) or a zero the caller accepted (``accepted_zeros``).

What the route does not model (``methods.yml``, route ``phase``): solids (no solid phase in the
flash; the result's ``limitations`` say so), electrolytes (a component with a charge is refused)
and pseudocomponents (a component thermo does not identify is refused).

The result is a calculation, not a validated design value: no application range is claimed
(``application_range``), unlike the stream properties of ``cheme process props``
(``domains/process/props``), which use one pinned, validated method.

Needs the ``props`` extra (thermo, chemicals); thermo is imported inside the functions.
Moved from LLM4ChemE (``src/tools/phase_calculations``, ``src/llm_tools/wrapped_phase_tool``).
"""

from __future__ import annotations

import json
import warnings
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter

from chemeascode.domains.process.thermodynamics.coverage import (
    InteractionCoverage,
    coverage_from_constants,
    load_constants,
)
from chemeascode.domains.process.thermodynamics.methods import (
    application_range,
    method_for_phase_model,
    route_limitations,
)
from chemeascode.foundation.units import convert_units

SOURCE = (
    "thermo Python package by C. Caleb Bell, Yoel Rene Cortes-Pena, Chemicals: Chemical "
    "properties component of Chemical Engineering Design Library (ChEDL)."
)


class MissingInteractionParametersWarning(UserWarning):
    """An optional interaction-parameter dataset is not installed; ``kij = 0`` is used."""


class IdealModelMapping(Enum):
    IDEAL_GAS = "ideal_gas"


class EOSModelMapping(Enum):
    RK = "Redlich-Kwong"
    PR = "Peng-Robinson"
    RKS = "Redlich-Kwong-Soave"


class ActivityCoefficientModelMapping(Enum):
    NRTL = "NRTL"
    WILSON = "Wilson"
    UNIFAC = "UNIFAC"


class EOSModel(BaseModel):
    """An equation of state for both phases."""

    eos_model: EOSModelMapping = Field(
        description=f"One of {[e.value for e in EOSModelMapping]} (exact, case-sensitive)"
    )

    @property
    def type(self) -> str:
        return "eos_model"


class ActivityCoefficientModel(BaseModel):
    """An activity-coefficient model for the liquid, an EOS or the ideal gas for the vapour."""

    liquid_phase_model: ActivityCoefficientModelMapping = Field(
        description=f"One of {[e.value for e in ActivityCoefficientModelMapping]}"
    )
    vapor_phase_model: EOSModelMapping | IdealModelMapping = Field(
        description=f'One of {[e.value for e in EOSModelMapping]} or "ideal_gas"; no default'
    )

    @property
    def type(self) -> str:
        return "activity_coefficient_model"


class FlashCalculationResult(BaseModel):
    """The phases found. Fractions are mole fractions; temperatures K, pressures Pa."""

    source: str = Field(default=SOURCE, description="Where the method comes from")
    provided_facts: dict[str, Any] = Field(default_factory=dict, description="The inputs")
    temperature_K: float = Field(description="Flash temperature [K]")
    pressure_Pa: float = Field(description="Flash pressure [Pa], absolute")
    flash_convergence_error: float | None = Field(default=None)
    no_iterations: int | None = Field(default=None)
    betas: list[float] = Field(description="Phase fractions [gas, liquid1, (liquid2)]")
    gas_count: int
    liquid_count: int
    gas_beta: float
    liquids_betas: list[float]
    component_cas_numbers: list[str] | None = None
    gas_composition: list[float] | None = None
    liquid_compositions: list[list[float]] | None = None
    notes: list[str] = Field(
        default_factory=list,
        description="Assumptions the calculation made, e.g. kij = 0 for a missing dataset",
    )
    method: str | None = Field(
        default=None, description="The model's id in the supported-method table (methods.yml)"
    )
    interaction_parameters: InteractionCoverage | None = Field(
        default=None,
        description="Per binary pair: sourced (with source), missing (zero used) or accepted zero",
    )
    limitations: list[str] = Field(
        default_factory=list, description="What the route does not model (methods.yml)"
    )
    application_range: str = Field(
        default="", description="The range claimed for the method ('no range claimed' if none)"
    )


class EOSHandler:
    """Vapour and liquid both from one cubic equation of state."""

    def __init__(self, thermodynamic_model: str) -> None:
        try:
            self.eos_model = EOSModelMapping(thermodynamic_model)
        except ValueError:
            raise ValueError(f"Unknown EOS model '{thermodynamic_model}'") from None
        self.notes: list[str] = []

    def eos_class(self) -> Any:
        from thermo import PRMIX, RKMIX, SRKMIX

        return {EOSModelMapping.RK: RKMIX, EOSModelMapping.PR: PRMIX, EOSModelMapping.RKS: SRKMIX}[
            self.eos_model
        ]

    def interaction_parameters(self, constants: Any) -> list[list[float]]:
        """``kij`` from ChemSep: thermo's PR set, the fetched SRK set, zeros for RK (and for SRK
        when ``cheme data fetch chemsep-srk`` has not run, with a note and a warning)."""
        from thermo.interaction_parameters import IPDB, InteractionParameterDB

        from chemeascode.domains.process.thermodynamics.chemsep_srk import (
            installed_srk_json,
            missing_srk_message,
        )

        if self.eos_model == EOSModelMapping.PR:
            return IPDB.get_ip_asymmetric_matrix("ChemSep PR", constants.CASs, "kij")
        n = len(constants.CASs)
        if self.eos_model == EOSModelMapping.RKS:
            path = installed_srk_json()
            if path is not None:
                # what thermo's load_json does, without leaving the file open
                table = json.loads(path.read_text(encoding="utf-8"))
                database = InteractionParameterDB()
                database.tables["ChemSep RKS"] = table["data"]
                database.metadata["ChemSep RKS"] = table["metadata"]
                return database.get_ip_symmetric_matrix("ChemSep RKS", constants.CASs, "kij")
            if n > 1:
                message = missing_srk_message()
                if message not in self.notes:
                    self.notes.append(message)
                    warnings.warn(message, MissingInteractionParametersWarning, stacklevel=2)
        return [[0.0] * n for _ in range(n)]

    def eos_kwargs(self, constants: Any) -> dict[str, Any]:
        return {
            "Tcs": constants.Tcs,
            "Pcs": constants.Pcs,
            "omegas": constants.omegas,
            "kijs": self.interaction_parameters(constants),
        }

    def get_vapor_liquid_models(self, temperature, pressure, zs, constants, correlations):
        from thermo import CEOSGas, CEOSLiquid

        kwargs = {**self.eos_kwargs(constants), "only_g": True}
        eos = self.eos_class()
        return (
            CEOSGas(eos, eos_kwargs=kwargs, T=temperature, P=pressure, zs=zs),
            CEOSLiquid(eos, eos_kwargs=kwargs, T=temperature, P=pressure, zs=zs),
        )


class ActivityCoefficientHandler:
    """Liquid from an activity-coefficient model, vapour from an EOS or the ideal gas."""

    def __init__(self, liquid_phase_ac_method: str, vapor_phase_fc_method: str) -> None:
        try:
            self.liquid_phase_ac_model = ActivityCoefficientModelMapping(liquid_phase_ac_method)
        except ValueError:
            raise ValueError(
                f"Unknown activity coefficient model {liquid_phase_ac_method}"
            ) from None
        if vapor_phase_fc_method == IdealModelMapping.IDEAL_GAS.value:
            self.vapor_phase_fc_model: EOSModelMapping | IdealModelMapping = (
                IdealModelMapping.IDEAL_GAS
            )
        else:
            try:
                self.vapor_phase_fc_model = EOSModelMapping(vapor_phase_fc_method)
            except ValueError:
                raise ValueError(
                    f"Unknown fugacity coefficient model {vapor_phase_fc_method}"
                ) from None
        self.notes: list[str] = []

    def liquid_model(self, constants: Any, temperature: float, zs: list[float]) -> Any:
        from thermo import NRTL, UNIFAC, Wilson
        from thermo.interaction_parameters import IPDB

        model = self.liquid_phase_ac_model
        if model == ActivityCoefficientModelMapping.UNIFAC:
            return UNIFAC.from_subgroups(temperature, xs=zs, chemgroups=constants.UNIFAC_groups)
        if model == ActivityCoefficientModelMapping.WILSON:
            return Wilson(
                T=temperature,
                xs=zs,
                lambda_as=IPDB.get_ip_asymmetric_matrix("ChemSep Wilson", constants.CASs, "aij"),
                lambda_bs=IPDB.get_ip_asymmetric_matrix("ChemSep Wilson", constants.CASs, "bij"),
            )
        # NRTL: ChemSep gives alpha_ij and b_ij (tau_ij = b_ij / T); the other terms are zero.
        n = len(zs)
        alphas = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", constants.CASs, "alphaij")
        bijs = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", constants.CASs, "bij")
        taus_b = [
            [bijs[i][j] if bijs[i][j] is not None else 0.0 for j in range(n)] for i in range(n)
        ]
        zero = [[0.0] * n for _ in range(n)]
        return NRTL(
            xs=zs, T=temperature, ABEFGHCD=(zero, taus_b, zero, zero, zero, zero, alphas, zero)
        )

    def get_vapor_liquid_models(self, temperature, pressure, zs, constants, correlations):
        from thermo import CEOSGas, GibbsExcessLiquid, IdealGas

        if self.vapor_phase_fc_model == IdealModelMapping.IDEAL_GAS:
            vapor = IdealGas(
                T=temperature, P=pressure, zs=zs, HeatCapacityGases=correlations.HeatCapacityGases
            )
        else:
            eos = EOSHandler(self.vapor_phase_fc_model.value)
            eos.notes = self.notes
            vapor = CEOSGas(eos.eos_class(), eos_kwargs=eos.eos_kwargs(constants), zs=zs)
        liquid = GibbsExcessLiquid(
            correlations.VaporPressures,
            VolumeLiquids=correlations.VolumeLiquids,
            HeatCapacityGases=correlations.HeatCapacityGases,
            GibbsExcessModel=self.liquid_model(constants, temperature, zs),
        )
        return vapor, liquid


def _flash(handler, constants, correlations, temperature, pressure, zs, allow_two_liquids) -> Any:
    from thermo import FlashPureVLS, FlashVL, FlashVLN

    components = constants.CASs
    vapor, liquid = handler.get_vapor_liquid_models(
        temperature, pressure, zs, constants, correlations
    )
    liquids = [liquid, liquid] if allow_two_liquids else [liquid]
    if len(components) == 1:
        flasher = FlashPureVLS(constants, correlations, gas=vapor, liquids=liquids, solids=[])
    elif allow_two_liquids:
        flasher = FlashVLN(constants, correlations, gas=vapor, liquids=liquids)
    else:
        flasher = FlashVL(constants, correlations, gas=vapor, liquid=liquid)
    return flasher.flash(T=temperature, P=pressure, zs=zs)


def phase_determination(
    components: list[str],
    overall_composition: list[float] | None,
    temperature_value: float,
    temperature_unit: str,
    pressure_value: float,
    pressure_unit: str,
    thermodynamic_model: EOSModel | ActivityCoefficientModel | dict,
    allow_two_liquids: bool,
    accepted_zeros: list[tuple[str, str]] | None = None,
) -> FlashCalculationResult:
    """The phases of *components* (names or CAS numbers) at the given state.

    *overall_composition* (mole fractions in the order of *components*) is required for a
    mixture and ignored for one component. Units go through :mod:`chemeascode.foundation.units`;
    the pressure is absolute (``bar(g)`` is refused, as no ambient pressure is given).
    *allow_two_liquids* should be set when liquid-liquid separation is expected, and is an
    assumption to state. *accepted_zeros* are binary pairs (component names as given, or CAS
    numbers; UNIFAC: main group names) whose missing parameter the caller accepts as zero; they
    are reported as ``accepted_zero`` instead of ``missing``. Raises ``ValueError`` for an
    invalid model, unit or composition, a pseudocomponent or an ion.
    """
    try:
        model: EOSModel | ActivityCoefficientModel = TypeAdapter(EOSModel).validate_python(
            thermodynamic_model
        )
    except ValueError:
        try:
            model = TypeAdapter(ActivityCoefficientModel).validate_python(thermodynamic_model)
        except ValueError as err:
            raise ValueError("Invalid thermodynamic model input.") from err
    if isinstance(model, EOSModel):
        handler: Any = EOSHandler(model.eos_model.value)
    else:
        handler = ActivityCoefficientHandler(
            model.liquid_phase_model.value, model.vapor_phase_model.value
        )
    temperature = convert_units(temperature_value, temperature_unit, "K")
    pressure = convert_units(pressure_value, pressure_unit, "Pa")
    if len(components) == 1:
        zs = [1.0]
    elif overall_composition is None:
        raise ValueError("Overall composition must be provided for multicomponent mixtures.")
    elif len(components) != len(overall_composition):
        raise ValueError("Inconsistent number of components and overall composition.")
    else:
        zs = list(overall_composition)
    try:
        import thermo  # noqa: F401
    except ImportError as err:
        raise ImportError(
            "phase calculations need thermo: pip install 'cheme-as-code[props]'"
        ) from err
    with warnings.catch_warnings():
        # thermo leaves its interaction-parameter files open while it loads them
        warnings.simplefilter("ignore", ResourceWarning)
        constants, correlations = load_constants(components)
        coverage = coverage_from_constants(
            model.model_dump(mode="json"), components, constants, accepted_zeros or ()
        )
        state = _flash(
            handler, constants, correlations, temperature, pressure, zs, allow_two_liquids
        )
    convergence = state.flash_convergence or {}
    notes = list(handler.notes)
    # the missing SRK dataset already has its note (every SRK kij zero)
    skip = ["Redlich-Kwong-Soave kij"] if handler.notes else []
    missing = coverage.missing_note(skip)
    notes += coverage.notes + ([missing] if missing else [])
    table_entry = method_for_phase_model(model.model_dump(mode="json"))
    return FlashCalculationResult(
        provided_facts={
            "components": components,
            "overall_composition": overall_composition,
            "temperature_value": temperature_value,
            "temperature_unit": temperature_unit,
            "pressure_value": pressure_value,
            "pressure_unit": pressure_unit,
            "thermodynamic_model": model.model_dump(mode="json"),
            "allow_two_liquids": allow_two_liquids,
            "accepted_zeros": [list(p) for p in accepted_zeros or []],
        },
        temperature_K=temperature,
        pressure_Pa=pressure,
        flash_convergence_error=convergence.get("err"),
        no_iterations=convergence.get("iterations"),
        betas=list(state.betas),
        gas_count=state.gas_count,
        liquid_count=state.liquid_count,
        gas_beta=state.gas_beta,
        liquids_betas=list(state.betas_liquids),
        component_cas_numbers=list(state.CASs) if state.CASs else None,
        gas_composition=list(state.gas.zs) if state.gas else None,
        liquid_compositions=[list(liquid.zs) for liquid in state.liquids] or None,
        notes=notes,
        method=table_entry.id if table_entry else None,
        interaction_parameters=coverage,
        limitations=route_limitations("phase"),
        application_range=application_range("phase"),
    )
