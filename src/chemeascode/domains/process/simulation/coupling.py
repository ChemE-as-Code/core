"""Kinetic reactors in the DWSIM solve: a fixed bed coupled as an external unit.

DWSIM 9.0.5 has a kinetic plug-flow reactor (``Reactor_PFR``, kinetic and heterogeneous
catalytic reactions through ``CreateKineticReaction``/``CreateHetCatReaction``), but a rate
law of ``process/reactions.yaml`` does not map onto it without loss: the ``(1 - Q/K)``
approach to equilibrium has no counterpart (DWSIM takes a separate reverse Arrhenius term),
neither has ``(T/T_ref)^n`` in ``k``, and DWSIM evaluates partial pressures, concentrations and
the energy balance with its property package where :mod:`chemeascode.domains.process.fixed_bed`
takes the ideal gas and the components' ideal-gas data. The flowsheet would then solve another
bed than ``cheme process propagate`` and ``cheme process reactors`` report.

So a step with ``reactor: pfr`` (translated as ``kinetic_pfr``) is solved by cheme-as-code and
seen by DWSIM as a conversion reactor:

1. the bed is solved at a first inlet: the inlet stream's values in the flowsheet, else no
   conversion at the inlet temperature;
2. DWSIM solves the flowsheet (recycles included) with the bed as a conversion reactor: each
   reaction's conversion of an inlet reactant (``extent |nu| / inlet flow``; a reaction that ran
   backwards is written reversed), the bed's outlet temperature and its pressure drop;
3. the bed is solved again at the reactor inlet DWSIM found; the residual is the largest
   difference between that bed's outlet and the outlet DWSIM has (component molar flows and
   pressure relative to the outlet's total molar flow and pressure, temperature in K);
4. within ``coupling.tolerance`` and ``coupling.temperature_tolerance`` the solve is
   converged; else 2 and 3 again with the new conversions (successive substitution), at most
   ``coupling.max_iterations`` DWSIM solves.

The run is then converged only when DWSIM converged and every coupled bed did; the residuals
of every iteration go to the run record. DWSIM's duty of the conversion reactor (outlet
temperature mode) is the heat its property package needs between the inlet and the bed's
outlet temperature: for an adiabatic bed it should vanish, and what is left measures how far the
ideal-gas bed and the property package disagree on the enthalpies (``energy_residual_kW``).

Limits (the bed model's, :mod:`.fixed_bed`): steady state, pseudo-homogeneous (rate laws are
effective particle rates), ideal gas, no axial dispersion, Ergun pressure drop only with the
bed's diameter, the gas viscosity and the catalyst's particle data.

A stirred tank (series) or batch (``reactor: cstr`` / ``batch``, :mod:`.stirred_tank`) is
coupled the same way (``_Tank``): its extents over the series or the batch give the conversions;
it is isothermal in DWSIM when its outlet stays at the inlet's temperature, else DWSIM takes
its outlet temperature; a batch's outlet keeps the inlet pressure.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.process.simulation.translate import KINETIC

#: What the run record says of each unit's coupling to the DWSIM solve.
NATIVE = "native"
EXTERNAL = "external-unit"
#: Extents below this share of the inlet's molar flow count as no reaction.
NO_EXTENT = 1e-12


class CouplingError(ValueError):
    """The bed cannot be represented in, or coupled to, the DWSIM solve."""


def kinetic_units(model: dict[str, Any]) -> list[dict[str, Any]]:
    return [u for u in model.get("units", []) if u["type"] == KINETIC]


def molar_flows(stream: dict[str, Any], mw: dict[str, float]) -> dict[str, float]:
    """kmol/h by component of a solved stream (mass flow, mole fractions) or a feed of the
    model, with the molar masses of ``process/materials.yaml``."""
    fractions = stream.get("mole_fractions") or {}
    mean = sum(y * mw[n] for n, y in fractions.items() if y > 0)
    if not mean or stream.get("mass_flow_kg_s") is None:
        return {}
    total = stream["mass_flow_kg_s"] * 3600.0 / mean
    return {n: y * total for n, y in fractions.items()}


def as_conversions(
    unit: dict[str, Any],
    reactions: list[Any],
    inlet: dict[str, float],
    outlet: dict[str, float],
    extents: dict[str, float],
    temperature: float | None,
    pressure_drop_kpa: float,
) -> dict[str, Any]:
    """The conversion reactor DWSIM solves in place of kinetic unit *unit*: per reaction the
    conversion of the inlet reactant it converts least of, so that the *extents* (kmol/h) on
    the *inlet* (kmol/h) give the bed's *outlet*; the outlet *temperature* (K; None:
    isothermal) and the pressure drop. Raises :class:`CouplingError` when conversions of inlet
    components cannot give the outlet."""
    total = sum(inlet.values()) or 1.0
    entries = []
    for r in reactions:
        extent = extents.get(r.id, 0.0)
        stoich = dict(r.stoichiometry)
        if extent < 0:  # ran backwards: the reverse reaction, forwards
            stoich = {n: -nu for n, nu in stoich.items()}
            extent = -extent
        reactants = [n for n, nu in stoich.items() if nu < 0]
        present = [n for n in reactants if inlet.get(n, 0.0) > 0]
        if abs(extent) <= NO_EXTENT * total:
            base = (present or reactants)[0]
            conversion = 0.0
        else:
            if not present:
                raise CouplingError(
                    f"reaction {r.id}: none of its reactants ({', '.join(reactants)}) enters "
                    "the bed, so DWSIM cannot convert it (a series reaction is not a conversion "
                    "of the inlet)"
                )
            base = min(present, key=lambda n: extent * abs(stoich[n]) / inlet[n])
            conversion = extent * abs(stoich[base]) / inlet[base]
            if conversion > 1.0 + 1e-9:
                raise CouplingError(
                    f"reaction {r.id}: converts {conversion:.4g} of the inlet's {base} (more "
                    "than it carries, the rest formed in the bed): not a conversion of the inlet"
                )
        entries.append(
            {
                "id": r.id,
                "stoichiometry": stoich,
                "phase": "liquid" if getattr(r, "phase", None) == "liquid" else "vapor",
                "base": base,
                "type": "conversion",
                "conversion": min(conversion, 1.0),
            }
        )
    # the extents must explain the bed's outlet (they are fitted to it)
    names = set(inlet) | set(outlet) | {n for r in reactions for n in r.stoichiometry}
    scale = max(sum(outlet.values()), total)
    for n in names:
        made = inlet.get(n, 0.0) + sum(
            r.stoichiometry.get(n, 0.0) * extents.get(r.id, 0.0) for r in reactions
        )
        if abs(made - outlet.get(n, 0.0)) > 1e-7 * scale:
            raise CouplingError(
                f"the reactions' extents do not reproduce the bed's outlet flow of {n} "
                "(reactions that depend on each other?)"
            )
    spec = {
        "mode": "isothermal" if temperature is None else "outlet_temperature",
        "pressure_drop_Pa": max(pressure_drop_kpa, 0.0) * 1000.0,
        "reactions": entries,
    }
    if temperature is not None:
        spec["outlet_temperature_K"] = temperature
    return {
        **{k: v for k, v in unit.items() if k != "spec"},
        "type": "conversion_reactor",
        "spec": spec,
    }


def worker_model(model: dict[str, Any], replaced: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """*model* with each kinetic unit replaced by its conversion reactor (*replaced*)."""
    return {
        **model,
        "units": [replaced.get(u["id"], u) if u["type"] == KINETIC else u for u in model["units"]],
    }


class _Bed:
    """One coupled bed: its definition and the solves of it."""

    def __init__(self, process: Any, unit: dict[str, Any]) -> None:
        from chemeascode.domains.process.fixed_bed import bed_of

        self.unit = unit
        self.node = process.nodes[unit["id"]]
        self.reactions, self.catalyst = bed_of(process, self.node)
        self.data = process.ideal_gas()
        self.mw = {c.id: c.molar_mass for c in process.components().values() if c.molar_mass}
        self.heat = self.node.bed.heat

    def first(self, process: Any, stream: Any, case: str) -> tuple[Any, dict[str, float], float]:
        """The bed at the flowsheet's inlet stream: (result, inlet kmol/h, inlet kPa)."""
        from chemeascode.domains.process.fixed_bed import solve_node
        from chemeascode.domains.process.model import stream_flows

        result, inputs = solve_node(process, self.node, stream, case)
        flows = stream_flows(process, stream, case).components or {}
        return result, {n: kg / self.mw[n] for n, kg in flows.items()}, inputs["P_in"]

    def solve(self, inlet: dict[str, float], temperature: float, pressure: float) -> Any:
        from chemeascode.domains.process.fixed_bed import solve_bed

        return solve_bed(
            self.reactions,
            inlet,
            temperature,
            pressure,
            self.node.bed,
            self.catalyst,
            self.data,
            self.mw,
        )

    def replacement(self, result: Any, inlet: dict[str, float], pressure: float) -> dict:
        isothermal = self.heat == "isothermal"
        return as_conversions(
            self.unit,
            self.reactions,
            inlet,
            result.outlet,
            result.extents,
            None if isothermal else result.temperature,
            pressure - result.pressure,
        )

    def reaction_heat(self, extents: dict[str, float], temperature: float) -> float | None:
        """kW the reactions release at *temperature* (ideal-gas data), None without them."""
        from chemeascode.domains.chemistry.thermochemistry import missing, reaction_enthalpy

        names = [n for r in self.reactions for n in r.stoichiometry]
        if missing(names, self.data):
            return None
        return sum(
            -reaction_enthalpy(r.stoichiometry, self.data, temperature)
            * extents.get(r.id, 0.0)
            / 3600.0
            for r in self.reactions
        )


class _Tank(_Bed):
    """One coupled stirred tank (series) or batch: solved by :mod:`.stirred_tank`."""

    def __init__(self, process: Any, unit: dict[str, Any], case: str) -> None:
        from chemeascode.domains.process.stirred_tank import TankError
        from chemeascode.foundation.units import to_kelvin

        self.unit = unit
        self.process = process
        self.node = process.nodes[unit["id"]]
        self.reactions, _ = process.reactions_of(self.node.id)
        self.data = process.ideal_gas()
        self.mw = {c.id: c.molar_mass for c in process.components().values() if c.molar_mass}
        spec = self.node.tank if self.node.reactor == "cstr" else self.node.batch
        if spec is None:
            raise TankError(f"reactor {self.node.reactor} without tank: or batch:")
        self.heat = spec.heat
        self.liquid = any(r.phase == "liquid" for r in self.reactions)
        # an isothermal tank held at its outlet's given temperature, every iteration
        self.outlet_t = None
        fs = process.flowsheet
        for s in fs.streams:
            if s.id in unit.get("outlets", []):
                given = getattr(s.state.get(case), "temperature", None)
                if given is not None and given.provenance != "calculated":
                    self.outlet_t = to_kelvin(given.value, given.unit or fs.units.temperature)

    def solve(self, inlet: dict[str, float], temperature: float, pressure: float) -> Any:
        from chemeascode.domains.process.stirred_tank import solve_moles

        result, _ = solve_moles(
            self.process, self.node, inlet, temperature, pressure, self.outlet_t
        )
        return _as_bed(result, temperature, pressure)

    def first(self, process: Any, stream: Any, case: str) -> tuple[Any, dict[str, float], float]:
        from chemeascode.domains.process.model import stream_flows
        from chemeascode.domains.process.stirred_tank import solve_node

        result, inputs = solve_node(process, self.node, stream, case)
        flows = stream_flows(process, stream, case).components or {}
        inlet = {n: kg / self.mw[n] for n, kg in flows.items()}
        return _as_bed(result, inputs["T_in"], inputs["P_in"]), inlet, inputs["P_in"]

    def replacement(self, result: Any, inlet: dict[str, float], pressure: float) -> dict:
        # isothermal at the inlet's temperature: DWSIM's isothermal mode; any other outlet
        # temperature (adiabatic, or held at a given one) is DWSIM's outlet temperature
        same = abs(result.temperature - result.inlet_temperature) < 1e-6
        return as_conversions(
            self.unit,
            self.reactions,
            inlet,
            result.outlet,
            result.extents,
            None if same else result.temperature,
            pressure - result.pressure,
        )

    def reaction_heat(self, extents: dict[str, float], temperature: float) -> float | None:
        # on the tank model's own basis: a liquid's heats of reaction, a gas's ideal-gas data
        if self.liquid and all(r.heat_of_reaction is not None for r in self.reactions):
            return sum(
                -r.heat_of_reaction.value * extents.get(r.id, 0.0) / 3600.0 for r in self.reactions
            )
        return super().reaction_heat(extents, temperature)


def _as_bed(result: Any, t_in: float, p_in: float) -> Any:
    """A tank's result in the shape the loop reads of a bed: the outlet pressure is the
    inlet's (a liquid; a closed gas batch's pressure is its vessel's, not the outlet stream's),
    the hot spot the hottest tank or point of the batch."""
    from types import SimpleNamespace

    temps = [t["temperature_K"] for t in result.tanks] + [p[1] for p in result.profile]
    return SimpleNamespace(
        outlet=result.outlet,
        extents=result.extents,
        temperature=result.temperature,
        pressure=p_in if result.kind == "batch" else result.pressure,
        inlet_temperature=t_in,
        hot_spot=max([result.temperature, *temps]),
        catalyst_mass=None,
        notes=result.notes,
    )


def _unit(process: Any, unit: dict[str, Any], case: str) -> _Bed:
    node = process.nodes[unit["id"]]
    if node.reactor in ("cstr", "batch"):
        return _Tank(process, unit, case)
    return _Bed(process, unit)


def _state(out: dict[str, Any], model: dict[str, Any], sid: str) -> dict[str, Any] | None:
    """A stream as the worker solved it, else the model's feed."""
    solved = (out.get("streams") or {}).get(sid)
    if solved:
        return solved
    for s in model["streams"]:
        if s["id"] == sid and s.get("feed"):
            return s["feed"]
    return None


def _first(process: Any, bed: _Bed, case: str) -> dict[str, Any]:
    """The conversion reactor of the first DWSIM solve: the bed at the inlet stream's values
    in the flowsheet, else no conversion at the inlet temperature (no pressure drop)."""
    sid = bed.unit["inlets"][0]
    stream = next((s for s in process.flowsheet.streams if s.id == sid), None)
    if stream is not None:
        try:
            result, inlet, pressure = bed.first(process, stream, case)
            return bed.replacement(result, inlet, pressure)
        except (ValueError, KeyError):  # BedError, TankError, CouplingError
            pass
    return as_conversions(bed.unit, bed.reactions, {}, {}, {}, None, 0.0)


def solve(
    process: Any,
    model: dict[str, Any],
    case: str,
    solver: Any,
    save: Any = None,
) -> dict[str, Any]:
    """Solve *model* with *solver* (``chemeascode.integrations.dwsim.solve``), its kinetic
    units coupled by the outer loop of the module docstring. Returns the worker's result of
    the last DWSIM solve, with ``coupling`` (unit id -> how it was coupled: iterations,
    residuals, converged, the bed's outlet) and ``converged`` false, a message saying why,
    when a bed did not converge or could not be coupled."""
    units = kinetic_units(model)
    beds = {}
    for u in units:
        try:
            beds[u["id"]] = _unit(process, u, case)
        except ValueError as failure:  # BedError, TankError
            return _failed({}, f"{u['id']}: {failure}", {})
    limit = max(u["spec"]["max_iterations"] for u in units)
    current = {uid: _first(process, bed, case) for uid, bed in beds.items()}
    info: dict[str, dict[str, Any]] = {
        u["id"]: {
            "coupling": EXTERNAL,
            "model": u["spec"]["model"],
            "dwsim_unit": "conversion_reactor",
            "tolerance": u["spec"]["tolerance"],
            "temperature_tolerance": u["spec"]["temperature_tolerance"],
            "max_iterations": u["spec"]["max_iterations"],
            "iterations": 0,
            "converged": False,
            "residuals": [],
        }
        for u in units
    }
    out: dict[str, Any] = {}
    for iteration in range(1, limit + 1):
        out = solver(worker_model(model, current), save)
        for uid in info:
            info[uid]["iterations"] = iteration
        if not out.get("converged", False):
            return _failed(
                out,
                f"the DWSIM solve of coupling iteration {iteration} did not converge",
                info,
            )
        done = True
        following = {}
        for uid, bed in beds.items():
            u = bed.unit
            inlet_state = _state(out, model, u["inlets"][0])
            outlet_state = _state(out, model, u["outlets"][0])
            if not inlet_state or not outlet_state:
                return _failed(out, f"{uid}: DWSIM returned no inlet or outlet stream", info)
            inlet = molar_flows(inlet_state, bed.mw)
            t_in = inlet_state["temperature_K"]
            p_in = inlet_state["pressure_Pa"] / 1000.0
            try:
                result = bed.solve(inlet, t_in, p_in)
                following[uid] = bed.replacement(result, inlet, p_in)
            except ValueError as failure:  # BedError, TankError, CouplingError
                return _failed(out, f"{uid}: {failure}", info)
            dwsim = molar_flows(outlet_state, bed.mw)
            total = sum(result.outlet.values()) or 1.0
            flow = max(
                abs(result.outlet.get(n, 0.0) - dwsim.get(n, 0.0))
                for n in set(result.outlet) | set(dwsim)
            )
            p_out = outlet_state["pressure_Pa"] / 1000.0
            residual = {
                "iteration": iteration,
                "flow": flow / total,
                "pressure": abs(result.pressure - p_out) / result.pressure,
                "temperature_K": abs(result.temperature - outlet_state["temperature_K"]),
            }
            info[uid]["residuals"].append(residual)
            ok = (
                residual["flow"] <= u["spec"]["tolerance"]
                and residual["pressure"] <= u["spec"]["tolerance"]
                and residual["temperature_K"] <= u["spec"]["temperature_tolerance"]
            )
            info[uid]["converged"] = ok
            info[uid]["bed"] = _bed_values(bed, result, inlet, t_in, p_in, out, uid)
            done &= ok
        if done:
            return {**out, "coupling": info}
        stopped = [
            uid for uid, bed in beds.items() if iteration >= bed.unit["spec"]["max_iterations"]
        ]
        if stopped:
            break
        current = following
    worst = ", ".join(
        f"{uid} (flow residual {info[uid]['residuals'][-1]['flow']:.3g}, temperature "
        f"{info[uid]['residuals'][-1]['temperature_K']:.3g} K)"
        for uid in info
        if not info[uid]["converged"] and info[uid]["residuals"]
    )
    return _failed(
        out,
        f"the kinetic reactor coupling did not converge in {info[next(iter(info))]['iterations']} "
        f"DWSIM solves: {worst}",
        info,
    )


def _bed_values(
    bed: _Bed,
    result: Any,
    inlet: dict[str, float],
    t_in: float,
    p_in: float,
    out: dict[str, Any],
    uid: str,
) -> dict[str, Any]:
    """What the run record keeps of the bed at the last inlet."""
    duty = ((out.get("units") or {}).get(uid) or {}).get("duty_kW")
    values: dict[str, Any] = {
        "heat": bed.heat,
        "inlet_temperature_K": t_in,
        "inlet_pressure_kPa": p_in,
        "outlet_temperature_K": result.temperature,
        "outlet_pressure_kPa": result.pressure,
        "pressure_drop_kPa": p_in - result.pressure,
        "hot_spot_K": result.hot_spot,
        "catalyst_mass_kg": result.catalyst_mass,
        "extents_kmol_h": dict(result.extents),
        "outlet_kmol_h": dict(result.outlet),
        "inlet_kmol_h": dict(inlet),
        "notes": list(result.notes),
    }
    heat = bed.reaction_heat(result.extents, t_in)
    if heat is not None:
        values["reaction_heat_kW"] = heat
    if bed.heat == "adiabatic" and duty is not None:
        # the heat DWSIM's property package needs for the ideal-gas bed's outlet temperature
        values["energy_residual_kW"] = duty
    return values


def _failed(out: dict[str, Any], message: str, info: dict[str, Any]) -> dict[str, Any]:
    return {
        **out,
        "converged": False,
        "messages": [*(out.get("messages") or []), message],
        "coupling": info,
    }
