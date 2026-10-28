"""Choosing a thermodynamic model (property method) from facts about the mixture.

The knowledge base ``model_selection_rules.yml`` encodes the decision tree of E. C. Carlson,
"Don't Gamble With Physical Properties For Simulations", Chem. Eng. Prog. 92 (1996) 35-46, as used
in the Aspen Plus user guide; its ``meta.source`` is copied into every result. The result is a
recommendation with its reasoning and the rules that fired, not a validated choice: the property
method a process uses is recorded in ``process/materials.yaml`` by an engineer.

Every recommended model is resolved against the supported-method contract (``methods.yml``,
:mod:`chemeascode.domains.process.thermodynamics.methods`): the result says, per model, whether
phase.py and the DWSIM simulation route run it, and where a route does not, the nearest model
it runs, marked as a substitution with what it loses, or that there is none.

Moved from LLM4ChemE (``src/tools/thermo_model_selection``, ``src/llm_tools/wrapped_thermo_tools``).
"""

from __future__ import annotations

from importlib.resources import files
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from chemeascode.domains.process.thermodynamics.methods import (
    ROUTES,
    MethodSupport,
    method_support,
)
from chemeascode.domains.process.thermodynamics.rules import (
    FactDefinition,
    InferenceResult,
    InsufficientFactsError,
    KnowledgeBase,
)
from chemeascode.foundation.units import convert_units

#: The knowledge base, package data next to this module.
RULES_FILE = files("chemeascode.domains.process.thermodynamics") / "model_selection_rules.yml"

#: Pressure bands of the decision tree, in bar(a): below VACUUM_BAR vacuum, above HIGH_BAR high.
VACUUM_BAR = 1.0
HIGH_BAR = 10.0

# The knowledge-base fact ``pressure_band`` is derived from these inputs, so a missing-fact report
# names them instead of the internal fact.
_PRESSURE_INPUTS = {
    "pressure_value": FactDefinition(
        id="pressure_value", question="What is the operating pressure of the system?"
    ),
    "pressure_unit": FactDefinition(
        id="pressure_unit", question="Unit of the operating pressure (e.g. 'bar(a)', 'atm', 'Pa')."
    ),
}


class ThermoModelSelectionInput(BaseModel):
    """What is known about the mixture. Every field is optional: give what is known and leave
    the rest unset; if the decision tree needs a missing fact, :func:`select_thermo_model` raises
    :class:`InsufficientFactsError` naming it."""

    model_config = ConfigDict(extra="forbid")

    pressure_value: float | None = Field(None, description="Operating pressure")
    pressure_unit: str | None = Field(
        None, description="Unit of the operating pressure ('bar(a)', 'atm', 'Pa', ...); absolute"
    )
    is_polar: bool | None = Field(
        None,
        description=(
            "Whether any compound of the mixture is polar; false only if all are nonpolar. "
            "Alcohols, amines and carboxylic acids are polar; alkanes and most aromatics nonpolar; "
            "halogenated compounds weakly to moderately polar depending on symmetry."
        ),
    )
    is_electrolyte: bool | None = Field(None, description="Whether the mixture has electrolytes")
    interaction_parameters_available: bool | None = Field(
        None, description="Whether binary interaction parameters are available for the mixture"
    )
    vapor_association_expected: bool | None = Field(
        None, description="Whether vapour-phase association is expected (carboxylic acids)"
    )
    liquid_liquid_expected: bool | None = Field(
        None, description="Whether liquid-liquid separation is expected at the given pressure"
    )
    has_pseudocomponents: bool | None = Field(
        None, description="Whether the mixture has pseudocomponents"
    )
    polymerization_degree: Literal["hexamer", "dimer"] | None = Field(
        None, description="Association degree in case of vapour-phase association"
    )


class ThermoModelRecommendation(InferenceResult):
    """An :class:`InferenceResult` with each recommended model resolved against the
    supported-method contract."""

    methods: list[MethodSupport] = Field(
        default_factory=list,
        description="Per recommended model (same order as models): whether phase.py and the "
        "DWSIM route run it, else the explicit substitution or why there is none",
    )
    executable: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Route -> the recommended models it runs as recommended (no substitution)",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="What a route cannot run as recommended, and the substitutions it offers",
    )


def _resolve(result: InferenceResult) -> ThermoModelRecommendation:
    methods = [method_support(name) for name in result.models]
    executable = {
        route: [s.recommended for s in methods if getattr(s, route).executable] for route in ROUTES
    }
    notes = []
    for route in ROUTES:
        if executable[route]:
            continue
        offered = sorted(
            {
                getattr(s, route).substitution.name
                for s in methods
                if getattr(s, route).substitution is not None
            }
        )
        if offered:
            notes.append(
                f"No recommended model is executable by the {route} route; substitutions "
                f"(approval needed, each loses what its entry says): {', '.join(offered)}."
            )
        else:
            notes.append(
                f"No recommended model is executable by the {route} route and no model it runs "
                "stands in: this regime is unsupported there."
            )
    for s in methods:
        if s.electrolyte is not None:
            notes.append(
                f"{s.name}: the electrolyte route runs its liquid model for "
                f"{', '.join(s.electrolyte.systems)} only (cheme process electrolyte, inside the "
                "claimed range of electrolytes.yml); any other electrolyte is unsupported."
            )
    return ThermoModelRecommendation(
        **result.model_dump(), methods=methods, executable=executable, notes=notes
    )


def knowledge_base() -> KnowledgeBase:
    """The packaged knowledge base."""
    return KnowledgeBase.from_dict(yaml.safe_load(RULES_FILE.read_text(encoding="utf-8")))


def pressure_band(pressure_bar: float) -> str:
    """``vacuum`` below 1 bar(a), ``high`` above 10 bar(a), else ``not_extreme``."""
    if pressure_bar > HIGH_BAR:
        return "high"
    if pressure_bar < VACUUM_BAR:
        return "vacuum"
    return "not_extreme"


def select_thermo_model(
    provided_facts: ThermoModelSelectionInput | dict,
) -> ThermoModelRecommendation:
    """The recommended thermodynamic models for *facts*, with the reasoning, the rules that
    fired, the facts used (``pressure_band`` derived from the pressure), the sources, and per
    model whether phase.py and the DWSIM route execute it (``methods``, ``executable``,
    ``notes``; a model a route does not run comes with an explicit substitution or none).
    *provided_facts* is a :class:`ThermoModelSelectionInput` or a dict of its fields.

    Raises :class:`InsufficientFactsError` when the decision tree needs a fact that is not given
    (its ``missing_facts`` name the inputs, e.g. ``pressure_value`` and ``pressure_unit``), and
    ``ValueError`` for an unknown input, a value outside a fact's possible values, or a pressure
    without its unit.
    """
    kb = knowledge_base()
    given = ThermoModelSelectionInput.model_validate(provided_facts)
    known = given.model_dump(exclude_none=True, exclude={"pressure_value", "pressure_unit"})
    if given.pressure_value is not None:
        if given.pressure_unit is None:
            raise ValueError("pressure_unit is required when pressure_value is given.")
        known["pressure_band"] = pressure_band(
            convert_units(given.pressure_value, given.pressure_unit, "bar")
        )
    try:
        return _resolve(kb.infer(known))
    except InsufficientFactsError as err:
        if "pressure_band" not in err.missing_facts:
            raise
        missing = [fact for fact in err.missing_facts if fact != "pressure_band"]
        missing += [name for name in _PRESSURE_INPUTS if getattr(given, name) is None]
        raise InsufficientFactsError(missing, {**kb.fact_definitions, **_PRESSURE_INPUTS}) from err
