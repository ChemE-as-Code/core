"""Screening inputs from the chemistry property sources, each value with its provenance.

:mod:`.selection` takes its numbers from the caller. :func:`screening_inputs` fills them from
:class:`~chemeascode.domains.chemistry.properties.PropertyRetriever` (NIST WebBook, the
``thermo`` package, GRAPPA and HANNA where their endpoints are given) for the values the caller
leaves out; :func:`select_with_retrieved_properties` then runs the screening on them. A value
the caller gives always wins (``source: caller``); a value no source gives stays missing and is
listed in ``missing`` with the reason. Nothing is estimated here:

- normal boiling points (``temperature_boil``, K) and molar masses: temperature-independent;
- heats of vaporisation (kJ/mol): ``enthalpy_vaporization_average`` (NIST's average, else
  ``thermo`` at the component's own normal boiling point; the metadata says which);
- liquid viscosities (mPa s) and the relative volatility of each adjacent pair (in boiling
  order): only at a caller-stated ``temperature_K``, never at a default temperature; the
  relative volatility is ``gamma1 P1sat / (gamma2 P2sat)`` with HANNA activity coefficients
  where the endpoint is given, else the ideal ratio ``P1sat / P2sat``, marked ``ideal: true``
  (a warning: it ignores non-ideality, so an azeotrope is missed);
- melting points (K), for the caller's Q1 (solidification) answer; the screening flags stay the
  caller's decision;
- diffusion coefficients: no source in core gives them; always missing unless given.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.chemistry.properties import PropertyResult, PropertyRetriever
from chemeascode.foundation.units import UnitError, convert_units

#: Screening input -> (the retriever's property, the unit the screening takes).
PURE_INPUTS: dict[str, tuple[str, str]] = {
    "boiling_points_K": ("temperature_boil", "K"),
    "molar_masses_g_mol": ("molecular_weight", "g/mol"),
    "melting_points_K": ("temperature_fusion", "K"),
    "heat_of_vaporization": ("enthalpy_vaporization_average", "kJ/mol"),
    "viscosity": ("viscosity", "mPa*s"),
}
#: Inputs that depend on temperature: retrieved only at a stated ``temperature_K``.
NEEDS_TEMPERATURE = ("viscosity", "relative_volatilities")
NO_SOURCE = "diffusion_coefficient"
CALLER = "caller"


@dataclass
class ScreeningInputs:
    """The screening inputs in boiling order (``component_names`` sorted by normal boiling
    point when all are known, else in the order given), the provenance of every value and what
    stayed missing."""

    component_names: list[str]
    values: dict[str, list[Any]] = field(default_factory=dict)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    order: list[int] = field(default_factory=list)
    """Position in the caller's list of each component of ``component_names``."""

    def complete(self, name: str) -> bool:
        found = self.values.get(name) or []
        return bool(found) and all(v is not None for v in found)


def _caller(value: Any, i: int) -> Any:
    if value is None:
        return None
    if isinstance(value, list | tuple):
        return value[i] if i < len(value) else None
    return value


def _magnitude(result: PropertyResult, unit: str) -> float:
    value = result.value
    if isinstance(value, dict) and "value" in value:
        value = value["value"]
    number = float(value)
    if result.units and result.units != unit:
        number = float(convert_units(number, result.units, unit))
    return number


def screening_inputs(
    component_names: list[str],
    *,
    retriever: PropertyRetriever | None = None,
    temperature_K: float | None = None,
    pressure_bar: float = 1.01325,
    molar_fractions: list[float] | None = None,
    given: dict[str, Any] | None = None,
) -> ScreeningInputs:
    """Fill the screening inputs of *component_names* (names or CAS numbers the sources know).

    *given* holds the caller's values by input name (``boiling_points_K``,
    ``heat_of_vaporization``, ``viscosity``, ``diffusion_coefficient``, ``molar_masses_g_mol``,
    ``melting_points_K``: one per component, None where unknown; ``relative_volatilities``: one
    per adjacent pair in boiling order); each non-None entry wins over a retrieved one.
    *temperature_K* is where the viscosities and relative volatilities are evaluated; without
    it they stay missing. *molar_fractions* (in the caller's order) give HANNA the pseudo-binary
    composition ``x_i / (x_i + x_j)`` of each pair.
    """
    retriever = retriever or PropertyRetriever()
    given = dict(given or {})
    n = len(component_names)
    out = ScreeningInputs(list(component_names))
    pressure_pa = pressure_bar * 1e5
    values: dict[str, list[Any]] = {}

    def record(name: str, component: str, value: Any, unit: str, source: str, meta: dict) -> None:
        out.provenance.append(
            {
                "input": name,
                "component": component,
                "value": value,
                "unit": unit,
                "source": source,
                **({"metadata": meta} if meta else {}),
            }
        )

    def miss(name: str, component: str, reason: str) -> None:
        out.missing.append({"input": name, "component": component, "reason": reason})

    # -- pure-component values, in the caller's order
    names = [*PURE_INPUTS, NO_SOURCE]
    for name in names:
        column: list[Any] = []
        for i, comp in enumerate(component_names):
            mine = _caller(given.get(name), i)
            if mine is not None:
                unit = PURE_INPUTS[name][1] if name in PURE_INPUTS else "m2/s"
                column.append(float(mine))
                record(name, comp, float(mine), unit, CALLER, {})
                continue
            if name == NO_SOURCE:
                column.append(None)
                miss(name, comp, "no property source in core gives diffusion coefficients")
                continue
            prop, unit = PURE_INPUTS[name]
            if name in NEEDS_TEMPERATURE and temperature_K is None:
                column.append(None)
                miss(name, comp, f"temperature-dependent: give temperature_K to retrieve {prop}")
                continue
            t = temperature_K if temperature_K is not None else 298.15
            if name == "heat_of_vaporization":
                tb = values["boiling_points_K"][i]
                if tb is None:
                    column.append(None)
                    miss(name, comp, "needs the normal boiling point, which is missing")
                    continue
                t = tb
            found = retriever.get(comp, prop, t, pressure_pa)
            if not found.ok:
                column.append(None)
                miss(name, comp, found.error or f"{prop} not found")
                continue
            try:
                number = _magnitude(found, unit)
            except (UnitError, TypeError, ValueError) as failure:
                column.append(None)
                miss(name, comp, f"{prop} {found.value!r} {found.units} not in {unit}: {failure}")
                continue
            meta = dict(found.metadata)
            if name == "heat_of_vaporization" and found.source == "Thermo":
                meta["evaluated_at_K"] = t
            column.append(number)
            record(name, comp, number, unit, str(found.source), meta)
        values[name] = column

    # -- boiling order
    tb = values["boiling_points_K"]
    if all(v is not None for v in tb):
        order = sorted(range(n), key=lambda i: tb[i])
        if order != list(range(n)):
            out.warnings.append(
                "components reordered by normal boiling point: "
                + ", ".join(component_names[i] for i in order)
            )
    else:
        order = list(range(n))
        out.warnings.append(
            "normal boiling points incomplete: the screening needs all of them and is not run"
        )
    out.order = order
    out.component_names = [component_names[i] for i in order]
    out.values = {name: [col[i] for i in order] for name, col in values.items()}
    fractions = list(molar_fractions or [])
    if len(fractions) == n:
        out.values["molar_fractions"] = [fractions[i] for i in order]

    # -- relative volatility of each adjacent pair, light over heavy
    pairs: list[Any] = []
    given_alpha = given.get("relative_volatilities")
    if isinstance(given_alpha, int | float):
        given_alpha = [given_alpha]
    sorted_names = out.component_names
    for k in range(n - 1):
        light, heavy = sorted_names[k], sorted_names[k + 1]
        label = f"{light} / {heavy}"
        mine = _caller(given_alpha, k)
        if mine is not None:
            pairs.append(float(mine))
            record("relative_volatilities", label, float(mine), "", CALLER, {})
            continue
        if not all(v is not None for v in tb):
            pairs.append(None)
            miss("relative_volatilities", label, "boiling order unknown (boiling points missing)")
            continue
        if temperature_K is None:
            pairs.append(None)
            miss(
                "relative_volatilities",
                label,
                "temperature-dependent: give temperature_K (or the value) to retrieve it",
            )
            continue
        x1 = None
        if len(fractions) == n:
            xi, xj = fractions[order[k]], fractions[order[k + 1]]
            if xi + xj > 0:
                x1 = xi / (xi + xj)
        found = retriever.mixture(
            light,
            heavy,
            "relative_volatility",
            x1=x1,
            temperature_K=temperature_K,
            pressure_Pa=pressure_pa,
        )
        if not found.ok:
            pairs.append(None)
            miss("relative_volatilities", label, found.error or "not found")
            continue
        meta = {**found.metadata, "temperature_K": temperature_K}
        if x1 is not None and not meta.get("ideal"):
            meta["x1_basis"] = "pseudo-binary feed fraction x_i / (x_i + x_j)"
        if meta.get("ideal"):
            out.warnings.append(
                f"relative volatility {label} is the ideal ratio P1sat/P2sat at {temperature_K} K "
                "(no activity coefficients): it ignores non-ideality and cannot show an "
                "azeotrope; give the value from VLE data or a HANNA endpoint for a non-ideal "
                "mixture"
            )
        pairs.append(float(found.value))
        record("relative_volatilities", label, float(found.value), "", str(found.source), meta)
    out.values["relative_volatilities"] = pairs
    return out


#: Screening keywords of one function only, left out (with a note) for the other.
BINARY_ONLY = ("azeotrope", "pressure_sensitive_azeotrope")
MULTICOMPONENT_ONLY = ("middle_key_fraction", "high_purity_middle")

#: Inputs whose absence leaves a PI-matrix criterion unevaluated: input -> criterion.
CRITERIA = {
    "relative_volatilities": "RV_1_01_1_15 (low relative volatility)",
    "heat_of_vaporization": "high_hvap",
    "viscosity": "high_viscosity",
    "diffusion_coefficient": "low_diffusion",
}


def select_with_retrieved_properties(
    component_names: list[str],
    *,
    retriever: PropertyRetriever | None = None,
    temperature_K: float | None = None,
    pressure: float = 1.01325,
    molar_fractions: list[float] | None = None,
    given: dict[str, Any] | None = None,
    **screening: Any,
) -> Any:
    """Retrieve the screening inputs (:func:`screening_inputs`) and run the binary or the
    multicomponent screening of :mod:`.selection` on them.

    *screening* are the other keyword arguments of the selection functions (``azeotrope``,
    ``recovery``, ``purity``, ``reflux_ratio`` and the Q1-Q5 flags): the caller's decisions,
    never retrieved. The return is the selection's
    :class:`~.selection.SeparationMethodSelectionReturn` with ``input_provenance`` and
    ``missing_inputs`` set; when the normal boiling points are incomplete the screening is not
    run and ``errors`` says why. A missing value is passed as None (the criterion it feeds is
    then not evaluated, which ``assumptions`` says), never as the functions' placeholder
    default.

    The same *screening* keywords can be passed for any number of components: a keyword of
    the other screening only (:data:`BINARY_ONLY` or :data:`MULTICOMPONENT_ONLY`) is left out
    and ``assumptions`` says so; any other keyword the screening does not take (a misspelt
    flag) is an error, never run on the default. ``azeotrope=True`` for three or more
    components is not screened: the multicomponent screening assumes a zeotropic mixture, so
    ``errors`` says so instead.
    """

    from chemeascode.domains.process.separations.selection import (
        SelectSeparationMethodsInput,
        SeparationMethodSelectionReturn,
        select_binary_separation_methods,
        select_multicomponent_separation_methods,
    )

    found = screening_inputs(
        component_names,
        retriever=retriever,
        temperature_K=temperature_K,
        pressure_bar=pressure,
        molar_fractions=molar_fractions,
        given=given,
    )
    v = found.values
    notes = list(found.warnings)
    for name, criterion in CRITERIA.items():
        if not found.complete(name):
            notes.append(f"{name} incomplete: criterion {criterion} not evaluated from data")
    binary = len(component_names) == 2
    tool = (
        "select_binary_separation_methods" if binary else "select_multicomponent_separation_methods"
    )
    select = (
        select_binary_separation_methods if binary else select_multicomponent_separation_methods
    )
    takes = inspect.signature(select).parameters
    other_only = MULTICOMPONENT_ONLY if binary else BINARY_ONLY
    errors = []
    if not binary and screening.get("azeotrope"):
        errors.append(
            "azeotrope screening is binary-only: the multicomponent screening assumes a "
            "zeotropic mixture; screen the azeotropic pair as a binary"
        )
    for name in [k for k in screening if k not in takes]:
        value = screening.pop(name)
        if name not in other_only:
            errors.append(f"{name} is not an input of {tool}")
        elif name != "azeotrope":  # reported above when set
            notes.append(f"{name}={value!r} is not an input of {tool}: ignored")
    if not found.complete("boiling_points_K"):
        errors.append(
            "normal boiling points are missing for: "
            + ", ".join(m["component"] for m in found.missing if m["input"] == "boiling_points_K")
        )
    if errors:
        return SeparationMethodSelectionReturn(
            tool=tool,
            errors=errors,
            provided_inputs=SelectSeparationMethodsInput(
                boiling_points_K=[], component_names=list(component_names)
            ),
            assumptions=notes,
            input_provenance=found.provenance,
            missing_inputs=found.missing,
        )
    alphas = v["relative_volatilities"]
    common = dict(
        component_names=found.component_names,
        boiling_points_K=v["boiling_points_K"],
        heat_of_vaporization=v["heat_of_vaporization"],
        viscosity=v["viscosity"],
        diffusion_coefficient=v["diffusion_coefficient"],
        pressure=pressure,
        molar_fractions=v.get("molar_fractions"),
        **screening,
    )
    if binary:
        result = select_binary_separation_methods(relative_volatility=alphas[0], **common)
    else:
        # the multicomponent function takes a list; a missing pair stays None in it
        result = select_multicomponent_separation_methods(
            relative_volatilities=alphas if any(a is not None for a in alphas) else None,
            **common,
        )
    result.assumptions = [*(result.assumptions or []), *notes]
    result.input_provenance = found.provenance
    result.missing_inputs = found.missing
    return result
