"""Pure-component properties from the ``thermo`` package (extra ``props``, the same pinned thermo
as ``cheme process props``). Local correlations, no network. thermo is imported inside the
function."""

from __future__ import annotations

import functools
import math
import warnings
from typing import Any

#: thermo's ``Chemical.phase`` code -> phase name.
_PHASES = {"l": "liquid", "g": "gas", "s": "solid"}


def _number(value: Any) -> float | None:
    if isinstance(value, list | tuple):
        value = value[0] if value else None
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def chemical_properties(
    identifier: str, temperature_K: float = 298.15, pressure_Pa: float = 101325.0
) -> dict[str, Any]:
    """Properties of *identifier* (name, CAS number, SMILES) at T and P, each as
    ``{"value": float | None, "units": str}``, plus ``name``, ``formula``, ``cas``,
    ``molar_mass_g_mol`` and ``phase``. A property thermo cannot give has value None.

    ``liquid_viscosity`` is the liquid's at (T, P), else, where the compound is vapour at P, the
    saturated liquid's at T. Molar heat capacities (J/mol/K): ``cp_ideal_gas`` at any T, and
    ``cp_liquid`` or ``cp_solid`` only for the phase thermo predicts at (T, P). Raises
    ``ValueError`` when thermo does not know the compound.
    """
    from thermo import Chemical

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            chem = Chemical(identifier, T=temperature_K, P=pressure_Pa)
    except Exception as failure:
        raise ValueError(f"thermo does not know {identifier!r}: {failure}") from failure

    def read(attribute: str, scale: float = 1.0) -> float | None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                value = _number(getattr(chem, attribute, None))
        except Exception:  # noqa: BLE001 - a correlation that cannot evaluate: no value
            return None
        return None if value is None else value * scale

    phase = _PHASES.get(getattr(chem, "phase", None) or "")
    found: dict[str, Any] = {
        "name": getattr(chem, "name", None) or identifier,
        "formula": getattr(chem, "formula", None),
        "cas": getattr(chem, "CAS", None),
        "molar_mass_g_mol": read("MW"),
        "phase": phase,
        "temperature_K": temperature_K,
        "pressure_Pa": pressure_Pa,
    }
    try:
        vapor_pressure = _number(chem.VaporPressure(T=temperature_K))
    except Exception:  # noqa: BLE001 - a correlation that cannot evaluate: no value
        vapor_pressure = None
    # the liquid at (T, P), else on the saturation line at T: thermo's pressure-dependent
    # method (CoolProp when installed) gives none for a state that is vapour at P
    liquid_viscosity = read("mul", 1e3)
    if liquid_viscosity is None:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                mu = _number(chem.ViscosityLiquid.T_dependent_property(temperature_K))
        except Exception:  # noqa: BLE001 - a correlation that cannot evaluate: no value
            mu = None
        liquid_viscosity = None if mu is None else mu * 1e3
    values = {
        "boiling_point": (read("Tb"), "K"),
        "melting_point": (read("Tm"), "K"),
        "flash_point": (read("Tflash"), "K"),
        "critical_temperature": (read("Tc"), "K"),
        "critical_pressure": (read("Pc"), "Pa"),
        "vapor_pressure": (vapor_pressure, "Pa"),
        "heat_of_vaporization": (read("Hvapm", 1e-3), "kJ/mol"),
        "heat_of_fusion": (read("Hfusm", 1e-3), "kJ/mol"),
        "liquid_viscosity": (liquid_viscosity, "mPa*s"),
        "cp_ideal_gas": (read("Cpgm"), "J/mol/K"),
        "cp_liquid": (read("Cpm") if phase == "liquid" else None, "J/mol/K"),
        "cp_solid": (read("Cpm") if phase == "solid" else None, "J/mol/K"),
    }
    found.update({k: {"value": v, "units": u} for k, (v, u) in values.items()})
    return found


def ideal_gas_formation(identifier: str) -> dict[str, Any]:
    """Standard ideal-gas formation data of *identifier* (name or CAS number) from
    ``chemicals``: ``cas``, ``name``, ``formula``, ``molar_mass`` (kg/kmol), ``dHf_298``
    (kJ/kmol), ``S_298`` (kJ/(kmol K)), ``cp_R`` (Poling's Cp/R polynomial), ``temperature_range``
    (K, None: every temperature; ``cp_R`` None where chemicals has no Poling coefficients) and
    ``sources`` (the method of each). Raises ValueError when a formation value is not known."""
    from chemicals import heat_capacity, identifiers, reaction

    try:
        cas = identifiers.CAS_from_any(identifier)
    except Exception as failure:
        raise ValueError(f"chemicals does not know {identifier!r}: {failure}") from failure
    meta = identifiers.search_chemical(cas)
    hf_method = (reaction.Hfg_methods(cas) or [None])[0]
    s_method = (reaction.S0g_methods(cas) or [None])[0]
    hf = reaction.Hfg(cas, method=hf_method) if hf_method else None
    s0 = reaction.S0g(cas, method=s_method) if s_method else None
    if hf is None or s0 is None:
        raise ValueError(f"{identifier}: no ideal-gas formation enthalpy or entropy in chemicals")
    table = heat_capacity.Cp_data_Poling
    coefficients: list[float] | None = None
    lo = hi = math.nan
    if cas in table.index:
        row = table.loc[cas]
        coefficients = [float(row[f"a{k}"]) for k in range(5)]
        lo, hi = float(row["Tmin"]), float(row["Tmax"])
        if any(math.isnan(c) for c in coefficients):
            coefficients, lo, hi = None, math.nan, math.nan
    while coefficients and len(coefficients) > 1 and coefficients[-1] == 0.0:
        coefficients.pop()
    return {
        "cas": cas,
        "name": meta.common_name,
        "formula": meta.formula,
        "molar_mass": meta.MW,
        "dHf_298": float(hf),  # J/mol = kJ/kmol
        "S_298": float(s0),  # J/(mol K) = kJ/(kmol K)
        "cp_R": coefficients,
        "temperature_range": None if math.isnan(lo) or math.isnan(hi) else (lo, hi),
        "sources": {
            "dHf_298": hf_method,
            "S_298": s_method,
            "cp_R": "Poling (5th ed.)" if coefficients else None,
        },
    }


def critical_constants(identifier: str) -> dict[str, Any]:
    """Tc (K), Pc (kPa) and the acentric factor of *identifier* from ``chemicals``, with the
    method of each. Raises ValueError when one is not known."""
    from chemicals import acentric, critical, identifiers

    try:
        cas = identifiers.CAS_from_any(identifier)
    except Exception as failure:
        raise ValueError(f"chemicals does not know {identifier!r}: {failure}") from failure
    tc, pc, omega = critical.Tc(cas), critical.Pc(cas), acentric.omega(cas)
    if tc is None or pc is None or omega is None:
        raise ValueError(f"{identifier}: no critical constants or acentric factor in chemicals")
    return {
        "Tc": float(tc),
        "Pc": float(pc) / 1000.0,
        "omega": float(omega),
        "sources": {
            "Tc": (critical.Tc_methods(cas) or ["?"])[0],
            "Pc": (critical.Pc_methods(cas) or ["?"])[0],
            "omega": (acentric.omega_methods(cas) or ["?"])[0],
        },
    }


def fitted_cp_R(
    cas: str, temperature_range: tuple[float, float], narrower: bool = False
) -> dict[str, Any]:
    """Poling's polynomial form ``Cp/R = a0 + ... + a4 T^4`` fitted to thermo's ideal-gas heat
    capacity (its first method valid over the whole range, e.g. TRC to 3000 K) in
    *temperature_range* K: ``cp_R``, ``method``, ``max_deviation`` (relative) and ``range``
    (K). With *narrower*, the method covering most of the range is fitted over the part it
    covers (at least 200 K). Raises ValueError when no method covers it."""
    import numpy as np
    from thermo import HeatCapacityGas

    lo, hi = temperature_range
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = HeatCapacityGas(CASRN=cas)
    # all_methods is a set: rank it (thermo's ranking, then by name), so a fit is reproducible
    ranked = [m for m in getattr(model, "ranked_methods", []) if m in model.all_methods]
    order = ranked + sorted(m for m in model.all_methods if m not in ranked)
    method = next(
        (
            m
            for m in order
            if model.T_limits.get(m, (math.inf, 0))[0] <= lo
            and model.T_limits.get(m, (0, 0))[1] >= hi
        ),
        None,
    )
    if method is None and narrower:
        spans = {
            m: (max(lo, model.T_limits[m][0]), min(hi, model.T_limits[m][1]))
            for m in order
            if m in model.T_limits
        }
        spans = {m: span for m, span in spans.items() if span[1] - span[0] >= 200.0}
        if spans:
            method = max(spans, key=lambda m: spans[m][1] - spans[m][0])
            lo, hi = spans[method]
    if method is None:
        raise ValueError(f"{cas}: no ideal-gas heat capacity in thermo covers {lo:g} to {hi:g} K")
    temperatures = np.linspace(lo, hi, 60)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        values = np.array([model.calculate(t, method) for t in temperatures]) / 8.314462618
    coefficients = np.polynomial.polynomial.polyfit(temperatures, values, 4)
    fitted = np.polynomial.polynomial.polyval(temperatures, coefficients)
    return {
        "cp_R": [float(f"{c:.6g}") for c in coefficients],
        "method": method,
        "max_deviation": float(np.max(np.abs(fitted - values) / values)),
        "range": (float(lo), float(hi)),
    }


def unifac_activity_coefficients(
    cas: list[str], temperature: float, fractions: list[float]
) -> list[float]:
    """UNIFAC (original, DDBST group assignments) activity coefficients of the components
    *cas* (CAS numbers) at *temperature* K and mole *fractions* (normalised here), from
    ``thermo``. Raises ValueError naming a component without UNIFAC groups."""
    try:
        from thermo.unifac import UFIP, UFSG, UNIFAC, UNIFAC_group_assignment_DDBST
    except ImportError as failure:
        raise ValueError(
            "activity coefficients need thermo: pip install 'cheme-as-code[props]'"
        ) from failure
    groups = []
    for number in cas:
        found = _unifac_groups(number, UNIFAC_group_assignment_DDBST)
        if not found:
            raise ValueError(f"no UNIFAC groups for CAS {number}")
        groups.append(dict(found))
    total = sum(fractions)
    if total <= 0:
        raise ValueError("the mole fractions are empty")
    if len(cas) == 1:
        return [1.0]
    model = UNIFAC.from_subgroups(
        T=temperature,
        xs=[x / total for x in fractions],
        chemgroups=groups,
        subgroups=UFSG,
        interaction_data=UFIP,
        version=0,
    )
    return [float(g) for g in model.gammas()]


@functools.cache
def _unifac_groups(cas: str, lookup: Any) -> tuple[tuple[int, int], ...]:
    """The DDBST UNIFAC groups of *cas*, looked up once per process."""
    return tuple(sorted((lookup(cas, "UNIFAC") or {}).items()))


def nrtl_ln_gammas(
    temperature: float,
    tau_a: list[list[float]],
    tau_b: list[list[float]],
    alpha: list[list[float]],
    tau_e: list[list[float]] | None = None,
    tau_f: list[list[float]] | None = None,
) -> Any:
    """NRTL (Renon and Prausnitz) from ``thermo`` at *temperature* K, with
    ``tau_ij = tau_a[i][j] + tau_b[i][j] / T + tau_e[i][j] ln(T) + tau_f[i][j] T`` and the
    non-randomness ``alpha[i][j]``: a function of the mole fractions (normalised here) that
    returns ``(ln gamma_i, gE/RT)``. The parameters are the caller's; nothing is read from a
    database. Raises ValueError without thermo."""
    try:
        from thermo import NRTL
        from thermo.activity import R
    except ImportError as failure:
        raise ValueError(
            "the NRTL model needs thermo: pip install 'cheme-as-code[props]'"
        ) from failure
    n = len(tau_b)
    base = NRTL(
        T=temperature,
        xs=[1.0 / n] * n,
        tau_as=tau_a,
        tau_bs=tau_b,
        tau_es=tau_e,
        tau_fs=tau_f,
        alpha_cs=alpha,
    )

    def evaluate(fractions: Any) -> tuple[list[float], float]:
        total = float(sum(fractions))
        model = base.to_T_xs(temperature, [float(x) / total for x in fractions])
        gamma = model.gammas()
        return [math.log(g) for g in gamma], model.GE() / (R * temperature)

    return evaluate
