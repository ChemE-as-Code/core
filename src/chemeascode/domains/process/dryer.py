"""A batch (filter-)dryer or vacuum dryer, and the filtration time of a filter: the bounded
drying adapter (ADR 0057).

A block or step with a ``dryer:`` (schema :class:`~.schema.Dryer`) takes one wet cake and gives
the dried product and the vapour:

- **mass** (specified: the residual moisture is the design input): the ``volatiles`` leave as
  vapour down to the ``residual_moisture`` (kg per kg of dry solid, or the mass fraction of the
  product); the volatiles kept have the inlet's volatile composition (no selectivity between
  several solvents). Everything else, the solid and what the cake liquid held dissolved, stays
  in the product (dried onto the crystals). With M the non-volatile mass and W the volatiles:
  ``W_kept = x M`` (per kg solid) or ``x / (1 - x) M`` (mass fraction), ``W_out = W - W_kept``;
- **energy** (``energy:``), kJ/h over the efficiency: the wet cake from its inlet temperature
  to the drying temperature at a constant heat capacity, the latent heat of each volatile
  evaporated at the drying temperature (declared, else Pitzer's corresponding-states
  correlation from the component's critical constants, ``dH/(R Tc) = 7.08 (1 - Tr)^0.354 +
  10.95 omega (1 - Tr)^0.456``; Poling, Prausnitz and O'Connell 2001, eq. 7-9.4) and the
  vessel's heat capacity heated once per batch (with ``process/recipe.yaml``: the batch's hours
  of flows): ``Q = (m cp (T - T_in) + sum W_i lambda_i + C_v (T - T_in) / h_batch) / eta``;
- **drying time** (a recipe's ``dry`` ``from:`` the step): the vapour of one batch over the
  constant ``drying_rate`` (kg/(m2 h)) times the heated area of the recipe's vessel, or the
  given ``drying_time``;
- **filtration time** (a recipe's ``filter`` ``from:`` a ``solid_separation:`` with
  ``filtration:``): Ruth's constant-pressure cake filtration, ``t = mu (alpha M V / (2 A^2) +
  R_m V / A) / dP``, M the dry solid of one batch's cake, V its filtrate's volume; a cake wash
  (ADR 0072) then passes its filtrate at the final filtration rate, ``t_w = mu V_w (alpha M /
  A^2 + R_m / A) / dP``.

ADR 0072 adds, each only where the dryer asks for it:

- **selective drying** (``selectivity: raoult``): the cake liquid evaporates as an open
  (Rayleigh) evaporation of an ideal liquid at the drying temperature, ``dn_i / n_i = (P_i /
  P_j) dn_j / n_j`` (Raoult's law: the non-volatile components lower every volatile alike), so
  ``n_i = n_i0 f^(P_i / P_max)``, with ``f`` found so that the volatiles kept are the residual
  moisture; each volatile's Antoine ``vapour_pressure``;
- **sublimation** (``sublimation:``): the vapour leaves saturated with each subliming solid at
  the dryer's ``pressure`` P, ``n_j = n_vap P_j / (P - sum P_j)`` (``P_j`` the solid's
  sublimation pressure, its ``vapour_pressure``; an upper bound of the loss), the sublimate
  counted in the vapour as the component it maps to, its heat in the duty;
- **cooling** (``cooling:``): the product cooled to its discharge temperature and the vessel's
  metal back to ``vessel_temperature`` (the next batch heats it from there), ``Q_c = m_p cp_p
  (T - T_p) + C_v (T - T_v) / h_batch``; propagate then writes the outlets' temperatures;
- **the vacuum condenser** (``condenser:``): the vapour cooled to ``T_c`` at the dryer's
  pressure, an ideal condensate in equilibrium with what passes (Rachford-Rice with ``K_i =
  P_i(T_c) / P``), its duty ``Q = sum c_i lambda_i + sum v_i cp (T - T_c)`` (what condenses at
  the drying temperature's latent heat, all of the vapour cooled as liquid, what passes
  re-evaporated at the same latent heat, as a vent condenser's, ADR 0062).

Not modelled (and so never claimed): drying curves (no falling-rate period: the rate is a
mean over the drying), the moisture's equilibrium with the solid (no sorption isotherm), a
non-ideal cake liquid, the vacuum's boiling point, leaked air in the condenser, a sublimate's
deposit in it, heat losses beyond the efficiency, agitation power, compressible cakes.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from chemeascode.domains.chemistry.formulas import parse_formula
from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import NOT_INPUTS
from chemeascode.foundation.yamlsource import _yaml_line

#: kJ/(kmol K)
GAS_CONSTANT = 8.314462618
PITZER = "Pitzer's corresponding states (Poling, Prausnitz, O'Connell 2001, eq. 7-9.4)"
ASSUMPTIONS = (
    "the residual moisture is specified (no drying curve or sorption isotherm)",
    "the volatiles kept have the inlet's volatile composition",
    "the non-volatile components the cake liquid held stay in the product",
    "product and vapour leave at the drying temperature; constant heat capacity of the cake",
)


class DryerError(ValueError):
    """The dryer, or a drying or filtration time, cannot be solved as declared."""


def pitzer_latent_heat(critical: Any, molar_mass: float, temperature: float) -> float:
    """kJ/kg of vaporization at *temperature* K from the critical constants (Tc K, omega) by
    Pitzer's corresponding states; DryerError at or above the critical temperature."""
    tr = temperature / critical.Tc
    if not 0 < tr < 1:
        raise DryerError(f"{temperature:g} K is not below the critical temperature")
    reduced = 7.08 * (1 - tr) ** 0.354 + 10.95 * critical.omega * (1 - tr) ** 0.456
    return reduced * GAS_CONSTANT * critical.Tc / molar_mass


def dry_mass(
    mass: dict[str, float],
    volatiles: list[str],
    moisture: Any,
    pressures: dict[str, float] | None = None,
) -> tuple[dict[str, float], dict[str, float]]:
    """(product, vapour) kg/h by component of drying *mass* to *moisture*
    (:class:`~.schema.ResidualMoisture`); DryerError when the cake is already drier. The
    volatiles kept have the inlet's ratio, or with *pressures* (kPa of each volatile at the
    drying temperature) what an open evaporation of an ideal liquid leaves (:func:`kept_by`)."""
    solid = sum(v for n, v in mass.items() if n not in volatiles)
    wet = sum(v for n, v in mass.items() if n in volatiles)
    if solid <= 0:
        raise DryerError("the inlet holds nothing but volatiles: nothing is left to dry")
    x = moisture.value
    kept = x * solid if moisture.basis == "per_kg_solid" else x / (1 - x) * solid
    if kept > wet * (1 + 1e-12) + 1e-12:
        raise DryerError(
            f"the cake holds {wet:.6g} kg/h of volatiles, less than the residual moisture "
            f"leaves ({kept:.6g} kg/h): nothing to dry"
        )
    if pressures is not None:
        share = kept_by({n: v for n, v in mass.items() if n in volatiles}, pressures, kept)
    else:
        share = dict.fromkeys(volatiles, min(kept / wet, 1.0) if wet > 0 else 0.0)
    product = {n: (v * share[n] if n in volatiles else v) for n, v in mass.items()}
    vapour = {n: v * (1 - share[n]) for n, v in mass.items() if n in volatiles}
    return product, vapour


def kept_by(wet: dict[str, float], pressures: dict[str, float], kept: float) -> dict[str, float]:
    """The share of each volatile in *wet* (kg) that an open (Rayleigh) evaporation of an ideal
    liquid at constant temperature leaves when *kept* kg of them remain: ``n_i / n_i0 = f^(P_i
    / P_max)`` (*pressures* kPa), ``f`` by bisection. DryerError when the volatiles that do not
    evaporate (no vapour pressure there) are more than *kept*."""
    top = max((pressures[n] for n in wet), default=0.0)
    if top <= 0:
        raise DryerError("no volatile has a vapour pressure at the drying temperature")
    alpha = {n: pressures[n] / top for n in wet}

    def left(f: float) -> float:
        return sum(v * f ** alpha[n] if alpha[n] > 0 else v for n, v in wet.items())

    if left(0.0) > kept * (1 + 1e-12) + 1e-12:
        raise DryerError(
            "the volatiles without a vapour pressure at the drying temperature are more than "
            "the residual moisture: they cannot dry"
        )
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2
        if mid <= low or mid >= high:
            break
        if left(mid) > kept:
            high = mid
        else:
            low = mid
    f = (low + high) / 2
    return {n: f ** alpha[n] if alpha[n] > 0 else 1.0 for n in wet}


def flash(vapour: dict[str, float], k: dict[str, float]) -> dict[str, float]:
    """kmol (or kmol/h) of each component of *vapour* that passes a condenser where ``K_i``
    (*k*) is its vapour over liquid mole fraction, an ideal condensate and no inert gas
    (Rachford-Rice, ``sum z_i (K_i - 1) / (1 + b (K_i - 1)) = 0``): all condenses below the
    bubble point (``sum z_i K_i <= 1``), nothing above the dew point (``sum z_i / K_i <= 1``)."""
    total = sum(vapour.values())
    if total <= 0:
        return dict.fromkeys(vapour, 0.0)
    z = {n: v / total for n, v in vapour.items()}
    if sum(z[n] * k[n] for n in z) <= 1.0:
        return dict.fromkeys(vapour, 0.0)
    if all(k[n] > 0 for n in z) and sum(z[n] / k[n] for n in z) <= 1.0:
        return dict(vapour)

    def f(b: float) -> float:
        return sum(z[n] * (k[n] - 1.0) / (1.0 + b * (k[n] - 1.0)) for n in z)

    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2
        if mid <= low or mid >= high:
            break
        if f(mid) > 0:
            low = mid
        else:
            high = mid
    b = (low + high) / 2
    return {n: total * k[n] * z[n] * b / (1.0 + b * (k[n] - 1.0)) for n in z}


@dataclass
class DryerResult:
    """The solved dryer, per hour of the flowsheet's flows."""

    inlet_kg_h: float
    dry_solid_kg_h: float  # everything not volatile
    kept_kg_h: float  # volatiles in the product
    evaporated_kg_h: float
    product: dict[str, float]
    vapour: dict[str, float]
    temperature_K: float
    #: volatile -> (kJ/kg, basis: given or the correlation)
    latent_heat: dict[str, tuple[float, str]] = field(default_factory=dict)
    energy: dict[str, Any] | None = None
    batch_hours: float | None = None  # of flows one batch makes (process/recipe.yaml)
    #: ADR 0072, each left out of the entry when the dryer does not ask for it: solid -> kg/h
    #: sublimed (in ``vapour`` as the component it maps to), the cooling after drying, the
    #: vacuum condenser, and notes (a vapour pressure used outside its range)
    sublimed: dict[str, float] = field(default_factory=dict)
    cooling: dict[str, Any] | None = None
    condenser: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def moisture(self) -> float:
        """Volatiles over the product's mass."""
        total = self.dry_solid_kg_h + self.kept_kg_h
        return self.kept_kg_h / total if total > 0 else 0.0

    def entry(self) -> dict[str, Any]:
        found = asdict(self)
        found["moisture_mass_fraction"] = self.moisture
        found["moisture_per_kg_solid"] = (
            self.kept_kg_h / self.dry_solid_kg_h if self.dry_solid_kg_h > 0 else None
        )
        found["mass_residual_kg_h"] = (
            self.inlet_kg_h - sum(self.product.values()) - sum(self.vapour.values())
        )
        found["latent_heat"] = {
            n: {"kJ_kg": v, "basis": b} for n, (v, b) in self.latent_heat.items()
        }
        found["per_batch"] = (
            {
                "evaporated_kg": self.evaporated_kg_h * self.batch_hours,
                "heat_kJ": (self.energy or {}).get("duty_kJ_h", 0.0) * self.batch_hours
                if (self.energy or {}).get("duty_kJ_h") is not None
                else None,
            }
            if self.batch_hours
            else None
        )
        for name in ("sublimed", "cooling", "condenser", "notes"):
            if not found[name]:
                del found[name]  # a dryer without them reports as in 1.12.0
        return found


def latent_heats(
    process: Any, spec: Any, vapour: dict[str, float]
) -> tuple[dict[str, tuple[float, str]], list[str]]:
    """kJ/kg of each volatile evaporated (declared, else from its critical constants) and what
    is missing."""
    comps = process.components()
    declared = spec.energy.latent_heat if spec.energy is not None else {}
    found: dict[str, tuple[float, str]] = {}
    missing = []
    for n, kg in vapour.items():
        if not kg:
            continue
        if n in declared:
            found[n] = (declared[n], spec.energy.provenance)
            continue
        c = comps.get(n)
        critical = getattr(c, "critical", None)
        if critical is None or not getattr(c, "molar_mass", None):
            missing.append(f"energy.latent_heat of {n} (or its critical constants and molar_mass)")
            continue
        try:
            found[n] = (pitzer_latent_heat(critical, c.molar_mass, spec.temperature), PITZER)
        except DryerError as failure:
            missing.append(f"the latent heat of {n}: {failure}")
    return found, missing


def energy_balance(
    spec: Any,
    inlet_kg_h: float,
    vapour: dict[str, float],
    latent: dict[str, tuple[float, str]],
    missing: list[str],
    inlet_temperature: float | None,
    batch_hours: float | None,
    sublimed: dict[str, float] | None = None,
) -> dict[str, Any]:
    """The dryer's duty (kW, heat supplied) with its terms, or what is missing. With
    ``cooling.vessel_temperature`` the vessel is heated from there; *sublimed* (kg/h by solid)
    takes its ``sublimation.heat`` (ADR 0072)."""
    data = spec.energy
    missing = list(missing)
    t_in = data.inlet_temperature or inlet_temperature
    if t_in is None:
        missing.append("the wet cake's temperature (energy.inlet_temperature or the inlet's)")
    if data.vessel_heat_capacity is not None and not batch_hours:
        missing.append("the batch (process/recipe.yaml) for the vessel's heat per batch")
    heats = spec.sublimation.heat if spec.sublimation is not None else {}
    if lacking := sorted(n for n, kg in (sublimed or {}).items() if kg and n not in heats):
        missing.append("sublimation.heat of " + ", ".join(lacking))
    if missing:
        return {"duty_kW": None, "duty_kJ_h": None, "missing": missing}
    assert t_in is not None
    dt = spec.temperature - t_in
    sensible = inlet_kg_h * data.heat_capacity * dt
    evaporation = sum(kg * latent[n][0] for n, kg in vapour.items() if kg)
    t_vessel = (spec.cooling.vessel_temperature if spec.cooling else None) or t_in
    vessel = (
        (data.vessel_heat_capacity or 0.0) * (spec.temperature - t_vessel) / batch_hours
        if batch_hours
        else 0.0
    )
    sublimation = sum(kg * heats[n] for n, kg in (sublimed or {}).items() if kg)
    total = (sensible + evaporation + vessel + sublimation) / data.efficiency
    found = {
        "duty_kW": total / 3600.0,
        "duty_kJ_h": total,
        "sensible_kJ_h": sensible,
        "evaporation_kJ_h": evaporation,
        "vessel_kJ_h": vessel,
        "efficiency": data.efficiency,
        "inlet_temperature_K": t_in,
        "temperature_K": spec.temperature,
        "missing": [],
        "basis": "the wet cake heated at a constant heat capacity to the drying temperature, "
        "the volatiles evaporated at it, the vessel heated once per batch, over the "
        "efficiency; the vapour's superheat and the heats of desorption not included",
    }
    if spec.sublimation is not None:  # ADR 0072: only where asked for
        found["sublimation_kJ_h"] = sublimation
    if spec.cooling is not None:
        found["vessel_from_K"] = t_vessel
    return found


def cooling_duty(
    spec: Any, product_kg_h: float, inlet_temperature: float | None, batch_hours: float | None
) -> dict[str, Any]:
    """The heat (kW, removed) of cooling the product to its discharge temperature and the
    vessel's metal back for the next batch (:class:`~.schema.DryerCooling`, ADR 0072), or what
    is missing."""
    data = spec.cooling
    energy = spec.energy
    capacity = energy.vessel_heat_capacity if energy is not None else None
    t_in = (energy.inlet_temperature if energy is not None else None) or inlet_temperature
    t_vessel = data.vessel_temperature or t_in
    missing = []
    if capacity is not None and t_vessel is None:
        missing.append("the vessel's temperature (cooling.vessel_temperature or the cake's)")
    if capacity is not None and not batch_hours:
        missing.append("the batch (process/recipe.yaml) for the vessel's heat per batch")
    t_product = data.product_temperature or spec.temperature
    found: dict[str, Any] = {
        "product_temperature_K": t_product,
        "vessel_temperature_K": t_vessel,
        "missing": missing,
    }
    if missing:
        return found | {"duty_kW": None, "duty_kJ_h": None}
    product = product_kg_h * (data.heat_capacity or 0.0) * (spec.temperature - t_product)
    vessel = (
        capacity * (spec.temperature - (t_vessel or 0.0)) / batch_hours
        if capacity is not None and batch_hours
        else 0.0
    )
    total = product + vessel
    return found | {
        "duty_kW": total / 3600.0,
        "duty_kJ_h": total,
        "product_kJ_h": product,
        "vessel_kJ_h": vessel,
        "basis": "the dried product cooled in the vessel at a constant heat capacity, the "
        "vessel's metal (energy.vessel_heat_capacity) cooled back once per batch",
    }


def condense_vapour(
    process: Any, spec: Any, vapour: dict[str, float], latent: dict[str, tuple[float, str]]
) -> dict[str, Any]:
    """The vacuum condenser (:class:`~.schema.DryerCondenser`, ADR 0072) on the volatiles'
    *vapour* (kg/h): what condenses and what passes (``condensate_kg_h``, ``gas_kg_h``), its
    duty (kW, removed) or what is missing, and notes."""
    data = spec.condenser
    comps = process.components()
    pressure = spec.pressure
    found: dict[str, Any] = {"temperature_K": data.temperature, "pressure_kPa": pressure}
    missing = []
    names = [n for n, kg in vapour.items() if kg]
    curves = {n: getattr(comps.get(n), "vapour_pressure", None) for n in names}
    masses = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
    if lacking := [n for n in names if curves[n] is None or not masses[n]]:
        missing.append("the vapour_pressure and molar_mass of " + ", ".join(lacking))
        return found | {"duty_kW": None, "duty_kJ_h": None, "missing": missing, "notes": []}
    notes = [
        f"the condenser at {data.temperature:g} K is outside the vapour_pressure range of {n}"
        for n in names
        if not curves[n].covers(data.temperature)
    ]
    kmol = {n: vapour[n] / masses[n] for n in names}
    k = {n: curves[n].kpa(data.temperature) / pressure for n in names}
    passing = {n: v * masses[n] for n, v in flash(kmol, k).items()}
    condensed = {n: vapour[n] - passing[n] for n in names}
    found |= {"condensate_kg_h": condensed, "gas_kg_h": passing, "notes": notes}
    if lacking := [n for n, kg in condensed.items() if kg > 0 and n not in latent]:
        missing.append("the latent heat of " + ", ".join(lacking))
        return found | {"duty_kW": None, "duty_kJ_h": None, "missing": missing}
    condensation = sum(kg * latent[n][0] for n, kg in condensed.items() if kg > 0)
    cooled = (
        sum(vapour[n] for n in names) * data.heat_capacity * (spec.temperature - data.temperature)
    )
    total = condensation + cooled
    return found | {
        "duty_kW": total / 3600.0,
        "duty_kJ_h": total,
        "condensation_kJ_h": condensation,
        "cooling_kJ_h": cooled,
        "missing": [],
        "basis": "an ideal condensate in equilibrium with the gas to the vacuum pump at the "
        "condenser's temperature and the dryer's pressure (Raoult's law, no leaked air); the "
        "latent heat at the drying temperature, the vapour cooled as liquid at a constant heat "
        "capacity",
    }


def _inlet_mass(process: Any, inlet: Any, case: str) -> dict[str, float]:
    from chemeascode.domains.process.model import stream_flows

    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise DryerError(f"inlet {inlet.id}: no flow per component ({', '.join(flows.missing)})")
    return flows.components


def _pressures(process: Any, names: list[str], temperature: float, notes: list[str]) -> dict:
    """kPa of each component's ``vapour_pressure`` at *temperature*; DryerError without one."""
    comps = process.components()
    curves = {n: getattr(comps.get(n), "vapour_pressure", None) for n in names}
    if lacking := [n for n, c in curves.items() if c is None]:
        raise DryerError("no vapour_pressure (materials.yaml) of " + ", ".join(lacking))
    for n, curve in curves.items():
        if not curve.covers(temperature):
            notes.append(f"{temperature:g} K is outside the vapour_pressure range of {n}")
    return {n: c.kpa(temperature) for n, c in curves.items()}


def _sublime(
    process: Any,
    spec: Any,
    mass: dict[str, float],
    pressures: dict[str, float] | None,
    notes: list[str],
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """(product, vapour, kg/h sublimed by solid): the dried cake when the vapour leaves
    saturated with the subliming solids (``n_j = n_vap P_j / (P - sum P_j)``), by successive
    substitution on what sublimes (it lowers the product the moisture is a share of)."""
    comps = process.components()
    solids = spec.sublimation.components
    sub = _pressures(process, list(solids), spec.temperature, notes)
    rest = spec.pressure - sum(sub.values())
    if rest <= 0:
        raise DryerError(
            f"the solids' sublimation pressure {sum(sub.values()):.6g} kPa reaches the dryer's "
            f"{spec.pressure:g} kPa(a): the product would sublime whole"
        )
    masses = {n: getattr(comps.get(n), "molar_mass", None) for n in [*solids, *spec.volatiles]}
    if lacking := [n for n, m in masses.items() if not m]:
        raise DryerError("no molar_mass of " + ", ".join(lacking))
    removed = dict.fromkeys(solids, 0.0)
    tolerance = 1e-13 * max(sum(mass.values()), 1e-9)
    for _ in range(200):
        reduced = {n: v - removed.get(n, 0.0) for n, v in mass.items()}
        product, vapour = dry_mass(reduced, spec.volatiles, spec.residual_moisture, pressures)
        kmol = sum(kg / masses[n] for n, kg in vapour.items())
        new = {j: kmol * sub[j] / rest * masses[j] for j in solids}
        if beyond := [j for j, kg in new.items() if kg > mass.get(j, 0.0)]:
            raise DryerError(
                "the vapour would carry more of " + ", ".join(beyond) + " than the cake holds"
            )
        change = max(abs(new[j] - removed[j]) for j in solids)
        removed = new
        if change <= tolerance:
            break
    else:
        raise DryerError("the sublimation did not converge in 200 iterations")
    reduced = {n: v - removed.get(n, 0.0) for n, v in mass.items()}
    product, vapour = dry_mass(reduced, spec.volatiles, spec.residual_moisture, pressures)
    for solid, into in solids.items():
        vapour[into] = vapour.get(into, 0.0) + removed[solid]
    return product, vapour, removed


def solve_node(
    process: Any, node: Any, inlet: Any, case: str, batch_hours: float | None = None
) -> tuple[DryerResult, dict[str, Any]]:
    """Dryer *node* fed by stream *inlet* in *case*, and what its outlets depend on besides
    the inlet (their fingerprint). *batch_hours*: the hours of flows one batch makes (the
    vessel's heat per batch)."""
    from chemeascode.domains.process.crystallization import _temperature_of

    spec = node.dryer
    mass = _inlet_mass(process, inlet, case)
    notes: list[str] = []
    pressures = None
    if spec.selectivity == "raoult":
        pressures = _pressures(process, list(spec.volatiles), spec.temperature, notes)
    sublimed: dict[str, float] = {}
    if spec.sublimation is not None:
        product, vapour, sublimed = _sublime(process, spec, mass, pressures, notes)
    else:
        product, vapour = dry_mass(mass, spec.volatiles, spec.residual_moisture, pressures)
    volatile = {n: v for n, v in vapour.items() if n in spec.volatiles}
    kept = sum(v for n, v in product.items() if n in spec.volatiles)
    result = DryerResult(
        sum(mass.values()),
        sum(v for n, v in product.items() if n not in spec.volatiles),
        kept,
        sum(volatile.values()),
        product,
        vapour,
        spec.temperature,
        batch_hours=batch_hours,
        sublimed=sublimed,
        notes=notes,
    )
    t_in = _temperature_of(process, inlet, case)
    latent: dict[str, tuple[float, str]] = {}
    missing: list[str] = []
    if spec.energy is not None or spec.condenser is not None:
        latent, missing = latent_heats(process, spec, volatile)
    if spec.energy is not None:
        result.latent_heat = latent
        result.energy = energy_balance(
            spec, result.inlet_kg_h, volatile, latent, missing, t_in, batch_hours, sublimed
        )
    if spec.cooling is not None:
        result.cooling = cooling_duty(spec, sum(product.values()), t_in, batch_hours)
    if spec.condenser is not None:
        result.condenser = condense_vapour(process, spec, volatile, latent)
        result.notes += result.condenser.pop("notes", [])
        if any(sublimed.values()):
            result.notes.append(
                "the sublimate passes the condenser uncounted (its deposit there is not modelled)"
            )
        if "condensate" in spec.outlets and "condensate_kg_h" not in result.condenser:
            raise DryerError(
                "the condenser's condensate needs "
                + "; ".join(result.condenser["missing"])
                + " (materials.yaml)"
            )
    moisture = spec.residual_moisture
    extra = {
        "dryer": {
            "volatiles": list(spec.volatiles),
            "residual_moisture": [moisture.value, moisture.basis],
            "outlets": dict(spec.outlets),
        }
    }
    # ADR 0072: only what the dryer asks for, so that other dryers' fingerprints stay
    for name in ("pressure", "selectivity", "sublimation", "cooling", "condenser"):
        dumped = spec.model_dump(mode="json", include={name})
        if dumped:
            extra["dryer"][name] = dumped[name]
    used = [
        *(spec.volatiles if spec.selectivity == "raoult" or spec.condenser else []),
        *(spec.sublimation.components if spec.sublimation else []),
    ]
    comps = process.components()
    if used:
        extra["vapour_pressure"] = {
            n: vp.model_dump(mode="json", exclude=NOT_INPUTS)
            for n in dict.fromkeys(used)
            if (vp := getattr(comps.get(n), "vapour_pressure", None)) is not None
        }
    return result, extra


def node_outlets(spec: Any, result: DryerResult) -> dict[str, dict[str, float]]:
    """Outlet port -> kg/h by component; with a ``condensate`` outlet the vapour port takes
    what passes the condenser (and the sublimate)."""
    found = {spec.outlets["product"]: result.product, spec.outlets["vapour"]: result.vapour}
    if "condensate" in spec.outlets and result.condenser is not None:
        condensed = result.condenser["condensate_kg_h"]
        found[spec.outlets["vapour"]] = {
            n: v - condensed.get(n, 0.0) for n, v in result.vapour.items()
        }
        found[spec.outlets["condensate"]] = dict(condensed)
    return found


def outlet_temperatures(spec: Any) -> dict[str, float]:
    """Outlet port -> K that ``cheme process propagate`` writes (ADR 0072): with ``cooling:``
    or ``condenser:`` only, the product at its discharge temperature (else the drying
    temperature), the vapour at the drying temperature (past a condenser with a condensate
    outlet: the condenser's), the condensate at the condenser's."""
    if spec.cooling is None and spec.condenser is None:
        return {}
    product = (spec.cooling.product_temperature if spec.cooling else None) or spec.temperature
    found = {spec.outlets["product"]: product, spec.outlets["vapour"]: spec.temperature}
    if "condensate" in spec.outlets:
        found[spec.outlets["vapour"]] = spec.condenser.temperature
        found[spec.outlets["condensate"]] = spec.condenser.temperature
    return found


def _recipe_hours(process: Any, case: str) -> float | None:
    """The hours of flows one batch of the plant's recipe makes (None without one)."""
    from chemeascode.domains.process.recipe import batch_hours, load_recipe

    recipe = load_recipe(process.root)[0]
    if recipe is None:
        return None
    try:
        return batch_hours(process, recipe, case)
    except ValueError:
        return None


def _heat_duty(
    process: Any, node: Any, port: str, case: str, out: bool = False
) -> tuple[str, float] | None:
    """(stream id, kW) of the energy stream into *node*'s *port* (*out*: from it) in *case*,
    when it has one."""
    from chemeascode.domains.process.schema import DUTY_UNITS

    for stream in process.flowsheet.streams:
        end = process.ends(stream)[0 if out else 1]
        if stream.kind != "energy" or end is None or (end.node, end.port) != (node.id, port):
            continue
        state = stream.state.get(case)
        duty = getattr(state, "duty", None)
        unit = (duty.unit if duty is not None else None) or process.flowsheet.units.duty
        if duty is None or unit not in DUTY_UNITS:
            return None
        return stream.id, duty.value * DUTY_UNITS[unit]
    return None


def dryer_entry(
    process: Any, node: Any, inlet: Any, case: str
) -> tuple[dict[str, dict[str, float]], dict[str, Any], list[str]]:
    """Dryer *node* for ``cheme process crystallizers``: outlet port -> kg/h by component, its
    solution (with the recipe's batch, when there is one) and where the flowsheet's heating
    stream (``energy.port``) differs from the model's duty (``cheme.process-dryer-duty``: not an
    outlet, propagate does not write it)."""
    result, _ = solve_node(process, node, inlet, case, _recipe_hours(process, case))
    differ = []
    spec = node.dryer
    tol = process.flowsheet.tolerance
    # the heat in (energy.port), and (ADR 0072) the cooling's and the condenser's heat out
    for data, part, out in (
        (spec.energy, result.energy, False),
        (spec.cooling, result.cooling, True),
        (spec.condenser, result.condenser, True),
    ):
        duty = (part or {}).get("duty_kW")
        if data is None or data.port is None or duty is None:
            continue
        given = _heat_duty(process, node, data.port, case, out)
        if given is not None and abs(given[1] - duty) > 1e-6 + tol.rel * max(
            abs(given[1]), abs(duty)
        ):
            differ.append(f"{given[0]} duty: {given[1]:.6g} kW written, {duty:.6g} model")
    return node_outlets(spec, result), result.entry(), differ


def solution_lines(sol: dict[str, Any]) -> list[str]:
    """A dryer's solution as ``cheme process crystallizers`` prints it."""
    lines = [
        f"  evaporated {sol['evaporated_kg_h']:.6g} kg/h at {sol['temperature_K']:g} K, residual "
        f"moisture {sol['moisture_mass_fraction']:.4g} (mass fraction) of "
        f"{sol['dry_solid_kg_h']:.6g} kg/h dry solid, mass residual "
        f"{sol['mass_residual_kg_h']:.3g} kg/h"
    ]
    energy = sol["energy"]
    if energy and energy["duty_kW"] is None:
        lines.append("  energy: missing " + "; ".join(energy["missing"]))
    elif energy:
        lines.append(
            f"  duty {energy['duty_kW']:.6g} kW (sensible {energy['sensible_kJ_h']:.6g}, "
            f"evaporation {energy['evaporation_kJ_h']:.6g}, vessel {energy['vessel_kJ_h']:.6g} "
            f"kJ/h; efficiency {energy['efficiency']:g})"
        )
        for n, heat in sol["latent_heat"].items():
            lines.append(f"  latent heat of {n}: {heat['kJ_kg']:.6g} kJ/kg ({heat['basis']})")
    for solid, kg in (sol.get("sublimed") or {}).items():
        lines.append(f"  sublimed {kg:.6g} kg/h of {solid} (the vapour saturated with it)")
    if cooling := sol.get("cooling"):
        lines.append(
            "  cooling "
            + (
                f"{cooling['duty_kW']:.6g} kW (product to {cooling['product_temperature_K']:g} K "
                f"{cooling['product_kJ_h']:.6g}, vessel to {cooling['vessel_temperature_K']:g} K "
                f"{cooling['vessel_kJ_h']:.6g} kJ/h)"
                if cooling["duty_kW"] is not None
                else "? (" + "; ".join(cooling["missing"]) + ")"
            )
        )
    if condenser := sol.get("condenser"):
        condensed = sum((condenser.get("condensate_kg_h") or {}).values())
        lines.append(
            f"  condenser at {condenser['temperature_K']:g} K, {condenser['pressure_kPa']:g} "
            "kPa(a): "
            + (
                f"{condensed:.6g} kg/h condensed, {condenser['duty_kW']:.6g} kW"
                if condenser["duty_kW"] is not None
                else "? (" + "; ".join(condenser["missing"]) + ")"
            )
        )
    for note in sol.get("notes", []):
        lines.append(f"  note: {note}")
    batch = sol["per_batch"]
    if batch:
        lines.append(
            f"  per batch ({sol['batch_hours']:.4g} h of flows): {batch['evaporated_kg']:.6g} kg "
            "evaporated"
            + (f", {batch['heat_kJ'] / 1000:.6g} MJ" if batch["heat_kJ"] is not None else "")
        )
    return lines


# -- times of a batch (process/recipe.yaml) ------------------------------------------------------


def drying_hours(spec: Any, evaporated_kg: float, area: float | None) -> float:
    """h to dry one batch: its *evaporated_kg* over ``drying_rate`` x *area* m2, or the given
    ``drying_time``. DryerError without either, or without the area."""
    if spec.drying_time is not None:
        from chemeascode.domains.process.recipe import HOURS

        return spec.drying_time.value * HOURS[spec.drying_time.unit]
    if spec.drying_rate is None:
        raise DryerError("the dryer gives no drying_rate (kg/(m2 h)) and no drying_time")
    if not area:
        raise DryerError(
            "no heated area: give vessel.heated_area (or jacket.area), or the dryer's "
            "cake_density so the cake's wetted area can be calculated"
        )
    return evaporated_kg / (spec.drying_rate.value * area)


def ruth_hours(filtration: Any, solid_kg: float, filtrate_m3: float, area: float) -> float:
    """h of a constant-pressure cake filtration of one batch (Ruth): ``t = mu (alpha M V /
    (2 A^2) + R_m V / A) / dP``, *solid_kg* M the cake's dry solid, *filtrate_m3* V, *area* A
    m2; mu in Pa s, dP in Pa."""
    mu = filtration.viscosity * 1e-3
    dp = filtration.pressure_difference * 1e3
    cake = filtration.specific_cake_resistance * solid_kg * filtrate_m3 / (2 * area**2)
    medium = filtration.medium_resistance * filtrate_m3 / area
    return mu * (cake + medium) / dp / 3600.0


def wash_hours(filtration: Any, solid_kg: float, wash_m3: float, area: float) -> float:
    """h to pass *wash_m3* of wash filtrate through the cake of *solid_kg* at the pressure and
    the filtrate's viscosity of *filtration*: at the final filtration rate of Ruth's equation,
    ``dV/dt = A dP / (mu (alpha M / A + R_m))``, so ``t_w = mu V_w (alpha M / A^2 + R_m / A) /
    dP`` (ADR 0072)."""
    mu = filtration.viscosity * 1e-3
    dp = filtration.pressure_difference * 1e3
    cake = filtration.specific_cake_resistance * solid_kg * wash_m3 / area**2
    medium = filtration.medium_resistance * wash_m3 / area
    return mu * (cake + medium) / dp / 3600.0


def filtrate_volume(process: Any, filtrate: dict[str, float], filtration: Any) -> float:
    """m3 of *filtrate* (kg by component): over the given density, else from the components'
    liquid molar volumes (ideal mixing); DryerError without them."""
    from chemeascode.domains.process.solids import solid_components

    solids = solid_components(process)
    liquid = {n: v for n, v in filtrate.items() if n not in solids and v}
    if filtration.filtrate_density is not None:
        return sum(liquid.values()) / filtration.filtrate_density
    comps = process.components()
    total = 0.0
    for n, kg in liquid.items():
        c = comps.get(n)
        if not getattr(c, "molar_mass", None) or not getattr(c, "liquid_molar_volume", None):
            raise DryerError(
                f"no filtrate volume: give filtration.filtrate_density or {n}'s liquid_molar_volume"
            )
        total += kg / c.molar_mass * c.liquid_molar_volume
    return total


def filter_area(diameter: float) -> float:
    """m2 of a Nutsche's filter plate: the vessel's bottom."""
    return math.pi * diameter**2 / 4.0


# -- rules (cheme validate) ---------------------------------------------------------------------


def rules(process: Any) -> list[Finding]:
    """``cheme.process-dryer`` findings: the volatiles, ports and sources of every dryer."""
    from chemeascode.domains.process.solids import solid_components

    findings: list[Finding] = []
    fs = process.flowsheet
    comps = process.components()
    solids = solid_components(process)
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        spec = getattr(node, "dryer", None)
        if spec is None:
            continue
        loc = [key, index, "dryer"]

        def add(level: str, message: str, where: list[Any], hint: str, node=node) -> None:
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    level,  # type: ignore[arg-type]
                    "cheme.process-dryer",
                    f"{node.id}: {message}",
                    line=_yaml_line(process.flowsheet_doc, where),
                    ids=[node.id],
                    hint=hint,
                )
            )

        for n in spec.volatiles:
            if n not in comps:
                add(
                    "error",
                    f"dryer volatile {n!r} is not a component",
                    [*loc, "volatiles"],
                    f"declare {n} in process/materials.yaml",
                )
            elif n in solids:
                add(
                    "error",
                    f"dryer volatile {n} is a solid component",
                    [*loc, "volatiles"],
                    "the volatiles are the liquids that evaporate (the moisture)",
                )
        material = [p for p in node.ports if p.kind == "material"]
        outs = [p.id for p in material if p.direction == "out"]
        mapped = list(spec.outlets.values())
        if sorted(mapped) != sorted(outs) or len(set(mapped)) != len(spec.outlets):
            add(
                "error",
                "dryer outlets must be its "
                + (
                    "material outlet ports"
                    if "condensate" in spec.outlets
                    else "two material outlet ports"
                ),
                [*loc, "outlets"],
                "outlets: {product: PORT, vapour: PORT}"
                + (" and condensate: PORT" if "condensate" in spec.outlets else ""),
            )
        sublimation = spec.sublimation
        for solid, into in (sublimation.components if sublimation is not None else {}).items():
            if solid not in solids or into not in comps or into in solids:
                add(
                    "error",
                    f"dryer sublimation {solid} -> {into}: a solid component into a component "
                    "that is not solid",
                    [*loc, "sublimation", "components"],
                    "map each subliming solid (phase: solid) to the component its vapour is",
                )
            elif comps[solid].formula and parse_formula(comps[solid].formula) != parse_formula(
                comps[into].formula
            ):
                add(
                    "error",
                    f"dryer sublimation {solid} -> {into}: not the same formula",
                    [*loc, "sublimation", "components"],
                    "a sublimate's vapour is the same substance",
                )
        if len([p for p in material if p.direction == "in"]) != 1:
            add(
                "error",
                "a dryer takes one material inlet (the wet cake)",
                [key, index, "ports"],
                "mix the feeds in a Mixing step before it",
            )
        energy = spec.energy
        for n in energy.latent_heat if energy is not None else {}:
            if n not in spec.volatiles:
                add(
                    "error",
                    f"dryer energy.latent_heat names {n!r}, which is not one of its volatiles",
                    [*loc, "energy", "latent_heat"],
                    "key latent_heat by the volatiles' component ids",
                )
        for part, data, direction in (
            ("energy", energy, "in"),
            ("cooling", spec.cooling, "out"),
            ("condenser", spec.condenser, "out"),
        ):
            if data is None or data.port is None:
                continue
            port = next((p for p in node.ports if p.id == data.port), None)
            if port is None or port.kind != "energy" or port.direction != direction:
                add(
                    "error",
                    f"dryer {part}.port {data.port} is no energy "
                    + ("inlet" if direction == "in" else "outlet")
                    + " port",
                    [*loc, part, "port"],
                    "name the port the heating stream enters"
                    if direction == "in"
                    else "name the port the heat removed leaves by (cooling water, brine)",
                )
        parts = (
            "residual_moisture",
            "energy",
            "drying_rate",
            "drying_time",
            "cake_density",
            "sublimation",
            "cooling",
            "condenser",
        )
        for part in parts:
            value = getattr(spec, part)
            if value is not None and value.provenance == "given" and not value.source.strip():
                add(
                    "warning",
                    f"dryer {part} is given without a source",
                    [*loc, part],
                    "give the source (vendor or pilot test, handbook)",
                )
    return findings
