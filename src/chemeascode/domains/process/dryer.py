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
  in a recipe vessel with ``metal_heat_capacity`` (instead of ``vessel_heat_capacity``, ADR
  0075) the metal is heated from the temperature the vessel was left at, the end of the last
  operation with ``temperatures`` before the drying (a cool-down before the discharge), else
  from the wet cake's; a recipe ``heat`` or ``cool`` with ``temperatures`` before the ``dry``
  in the dryer's vessel brings the wet cake to its end temperature (its heat is the recipe
  operation's), and the dryer heats the cake from there;
- **drying time** (a recipe's ``dry`` ``from:`` the step): the vapour of one batch over the
  constant ``drying_rate`` (kg/(m2 h)) times the heated area of the recipe's vessel, or the
  given ``drying_time``;
- **filtration time** (a recipe's ``filter`` ``from:`` a ``solid_separation:`` with
  ``filtration:``): Ruth's constant-pressure cake filtration, ``t = mu (alpha M V / (2 A^2) +
  R_m V / A) / dP``, M the dry solid of one batch's cake, V its filtrate's volume.

Not modelled (and so never claimed): drying curves (no falling-rate period: the rate is a
mean over the drying), the moisture's equilibrium with the vapour or the solid (no sorption
isotherm), the vacuum's boiling point, the condenser, heat losses beyond the efficiency,
agitation power, compressible cakes, washing efficiency.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.foundation.findings import Finding
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
    mass: dict[str, float], volatiles: list[str], moisture: Any
) -> tuple[dict[str, float], dict[str, float]]:
    """(product, vapour) kg/h by component of drying *mass* to *moisture*
    (:class:`~.schema.ResidualMoisture`); DryerError when the cake is already drier."""
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
    share = min(kept / wet, 1.0) if wet > 0 else 0.0
    product = {n: (v * share if n in volatiles else v) for n, v in mass.items()}
    vapour = {n: v * (1 - share) for n, v in mass.items() if n in volatiles}
    return product, vapour


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
    metal: tuple[float, float | None, str] | None = None,
    cake: tuple[float, str] | None = None,
) -> dict[str, Any]:
    """The dryer's duty (kW, heat supplied) with its terms, or what is missing. *metal*: the
    recipe vessel's (:func:`.recipe.dryer_metal`, ADR 0075), heated from the temperature the
    vessel was left at (else the wet cake's) instead of ``vessel_heat_capacity``. *cake*: (K,
    the operation) the recipe heated or cooled the wet cake to before the drying
    (:func:`.recipe.dryer_cake`): the wet cake is heated from there, that operation's heat
    being its own."""
    data = spec.energy
    missing = list(missing)
    t_in = data.inlet_temperature or inlet_temperature
    if t_in is None:
        missing.append("the wet cake's temperature (energy.inlet_temperature or the inlet's)")
    if (data.vessel_heat_capacity is not None or metal is not None) and not batch_hours:
        missing.append("the batch (process/recipe.yaml) for the vessel's heat per batch")
    if metal is not None and data.vessel_heat_capacity is not None:
        missing.append(
            "one vessel metal: energy.vessel_heat_capacity or the recipe vessel's "
            f"metal_heat_capacity ({metal[2]}), not both"
        )
    if missing:
        return {"duty_kW": None, "duty_kJ_h": None, "missing": missing}
    assert t_in is not None
    dt = spec.temperature - t_in
    sensible = inlet_kg_h * data.heat_capacity * (spec.temperature - (cake or (t_in,))[0])
    evaporation = sum(kg * latent[n][0] for n, kg in vapour.items() if kg)
    vessel = (data.vessel_heat_capacity or 0.0) * dt / batch_hours if batch_hours else 0.0
    start = t_in
    if metal is not None and batch_hours:
        start = metal[1] if metal[1] is not None else t_in
        vessel = metal[0] * (spec.temperature - start) / batch_hours
    total = (sensible + evaporation + vessel) / data.efficiency
    extra = (
        {
            "vessel_metal": {
                "procedure": metal[2],
                "heat_capacity_kJ_K": metal[0],
                "start_temperature_K": start,
            }
        }
        if metal is not None
        else {}
    )
    if cake is not None:
        extra["recipe_heat"] = {"operation": cake[1], "cake_temperature_K": cake[0]}
    return extra | {
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
        "the volatiles evaporated at it, the vessel heated once per batch"
        + (
            f" (the recipe vessel's metal from {start:.5g} K, the temperature it was left at)"
            if metal is not None
            else ""
        )
        + (
            f" (the wet cake from {cake[0]:.5g} K, the end of the recipe's {cake[1]})"
            if cake is not None
            else ""
        )
        + ", over the efficiency; the vapour's superheat and the heats of desorption not "
        "included",
    }


def _inlet_mass(process: Any, inlet: Any, case: str) -> dict[str, float]:
    from chemeascode.domains.process.model import stream_flows

    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise DryerError(f"inlet {inlet.id}: no flow per component ({', '.join(flows.missing)})")
    return flows.components


def solve_node(
    process: Any, node: Any, inlet: Any, case: str, batch_hours: float | None = None
) -> tuple[DryerResult, dict[str, Any]]:
    """Dryer *node* fed by stream *inlet* in *case*, and what its outlets depend on besides
    the inlet (their fingerprint). *batch_hours*: the hours of flows one batch makes (the
    vessel's heat per batch)."""
    from chemeascode.domains.process.crystallization import _temperature_of

    spec = node.dryer
    mass = _inlet_mass(process, inlet, case)
    product, vapour = dry_mass(mass, spec.volatiles, spec.residual_moisture)
    kept = sum(v for n, v in product.items() if n in spec.volatiles)
    result = DryerResult(
        sum(mass.values()),
        sum(v for n, v in product.items() if n not in spec.volatiles),
        kept,
        sum(vapour.values()),
        product,
        vapour,
        spec.temperature,
        batch_hours=batch_hours,
    )
    if spec.energy is not None:
        latent, missing = latent_heats(process, spec, vapour)
        result.latent_heat = latent
        from chemeascode.domains.process.recipe import dryer_cake, dryer_metal

        result.energy = energy_balance(
            spec,
            result.inlet_kg_h,
            vapour,
            latent,
            missing,
            _temperature_of(process, inlet, case),
            batch_hours,
            dryer_metal(process, node.id),
            dryer_cake(process, node.id),
        )
    moisture = spec.residual_moisture
    extra = {
        "dryer": {
            "volatiles": list(spec.volatiles),
            "residual_moisture": [moisture.value, moisture.basis],
            "outlets": dict(spec.outlets),
        }
    }
    return result, extra


def node_outlets(spec: Any, result: DryerResult) -> dict[str, dict[str, float]]:
    """Outlet port -> kg/h by component."""
    return {spec.outlets["product"]: result.product, spec.outlets["vapour"]: result.vapour}


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


def _heat_duty(process: Any, node: Any, port: str, case: str) -> tuple[str, float] | None:
    """(stream id, kW) of the energy stream into *node*'s *port* in *case*, when it has one."""
    from chemeascode.domains.process.schema import DUTY_UNITS

    for stream in process.flowsheet.streams:
        end = process.ends(stream)[1]
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
    energy = node.dryer.energy
    duty = (result.energy or {}).get("duty_kW")
    if energy is not None and energy.port is not None and duty is not None:
        given = _heat_duty(process, node, energy.port, case)
        tol = process.flowsheet.tolerance
        if given is not None and abs(given[1] - duty) > 1e-6 + tol.rel * max(
            abs(given[1]), abs(duty)
        ):
            differ.append(f"{given[0]} duty: {given[1]:.6g} kW written, {duty:.6g} model")
    return node_outlets(node.dryer, result), result.entry(), differ


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
        if sorted(mapped) != sorted(outs) or len(set(mapped)) != 2:
            add(
                "error",
                "dryer outlets must be its two material outlet ports",
                [*loc, "outlets"],
                "outlets: {product: PORT, vapour: PORT}",
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
        if energy is not None and energy.port is not None:
            port = next((p for p in node.ports if p.id == energy.port), None)
            if port is None or port.kind != "energy" or port.direction != "in":
                add(
                    "error",
                    f"dryer energy.port {energy.port} is no energy inlet port",
                    [*loc, "energy", "port"],
                    "name the port the heating stream enters",
                )
        parts = ("residual_moisture", "energy", "drying_rate", "drying_time", "cake_density")
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
