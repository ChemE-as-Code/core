"""A packed catalyst bed: the 1D pseudo-homogeneous plug-flow model of a fixed-bed reactor.

Along the catalyst mass W (kg) of a bed of ``tubes`` parallel tubes, steady state, ideal gas,
no axial dispersion, no gradients between gas and catalyst (the rate laws are taken as
effective rates of the particles)::

    dF_i/dW = sum_j nu_ij r_j                              F in kmol/s, r in kmol/(kg s)
    sum_i F_i cp_i dT/dW = sum_j (-dHr_j) r_j + q          adiabatic: q = 0
                                                           cooled: q = U a (T_c - T) / 1000
    dP/dW = -(G / (rho dp)) ((1 - e) / e^3) (150 (1 - e) mu / dp + 1.75 G) / (rho_b A) / 1000

with a rate per volume divided by the bulk density, ``a = 4 / (D rho_b)`` the tube wall area
per kg of catalyst, ``G`` the mass flux over the bed's cross-section ``A``, ``rho`` the gas
density, ``dp`` the particle diameter times its sphericity and ``e`` the bed voidage (Ergun,
Chem. Eng. Prog. 48 (1952) 89; the form of Fogler, *Elements of Chemical Reaction
Engineering*, eq. 5-21). Without the bed's diameter or the gas viscosity there is no pressure
drop (said in ``notes``). An isothermal bed keeps the inlet temperature.

The equations are integrated by the Dormand-Prince 5(4) pair with an adaptive step (pure
Python), every flow kept non-negative. :func:`solve_bed` raises :class:`BedError` naming what
is missing (a rate law, ideal-gas data, the bulk density, a coolant).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.chemistry.equilibrium import reaction_ln_k
from chemeascode.domains.chemistry.rates import rate
from chemeascode.domains.chemistry.thermochemistry import R, missing, reaction_enthalpy
from chemeascode.domains.process import bed_transport as transport

#: Steps the profile is reported at (beside the integrator's own).
PROFILE_POINTS = 50
#: What the model assumes, for reports and maturity checks (``cheme maturity``).
ASSUMPTIONS = (
    "steady state",
    "ideal gas",
    "pseudo-homogeneous: no concentration or temperature gradients between gas and catalyst",
    "rate laws taken as effective rates of the particles, unless scale: intrinsic (then times "
    "the effectiveness factor of an isothermal particle; the external film is checked, not "
    "modelled)",
    "plug flow, no axial dispersion",
)


def _pressure_drop_gap(bed: Any, catalyst: Any) -> str | None:
    """Why the bed has no Ergun pressure drop; None when it has one."""
    physical = getattr(catalyst, "physical", None)
    if physical is None or not physical.particle_diameter or not physical.bed_voidage:
        return "no pressure drop: the catalyst's particle_diameter or bed_voidage is not given"
    if not bed.diameter or bed.viscosity is None:
        return "no pressure drop: the bed's diameter or the gas viscosity is not given"
    return None


def _transport_gap(bed: Any, catalyst: Any) -> str | None:
    """Why the bed has no transport checks; None when it has them."""
    if missing_data := transport.lacking(catalyst, bed):
        return "no transport checks (Weisz-Prater, Mears): " + "; ".join(missing_data)
    return None


def bed_limitations(bed: Any, catalyst: Any) -> list[str]:
    """What the model of *bed* (holding *catalyst*) leaves out as declared, without solving it:
    the pressure drop (particle data, bed diameter or gas viscosity missing) and the transport
    checks (particle density, effective diffusivity missing)."""
    return [g for g in (_pressure_drop_gap(bed, catalyst), _transport_gap(bed, catalyst)) if g]


class BedError(ValueError):
    """The bed cannot be solved as declared."""


@dataclass
class BedResult:
    """The outlet of a bed and what happened along it."""

    outlet: dict[str, float]  # kmol/h by component
    temperature: float  # K
    pressure: float  # kPa(a)
    catalyst_mass: float  # kg
    catalyst_volume: float  # m3 of bed
    extents: dict[str, float]  # kmol/h by reaction
    hot_spot: float  # K, the highest temperature along the bed
    #: (W kg, T K, P kPa) along the bed
    profile: list[tuple[float, float, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Weisz-Prater and Mears per reaction at the inlet and the outlet (:mod:`.bed_transport`);
    #: empty without the particle data
    transport: dict[str, Any] = field(default_factory=dict)

    @property
    def pressure_drop(self) -> float:
        """kPa from the inlet."""
        return self.profile[0][2] - self.pressure if self.profile else 0.0


def bed_mass(bed: Any, catalyst: Any) -> tuple[float, float]:
    """The catalyst mass (kg) and bed volume (m3) of *bed*: its ``catalyst_mass``, else its
    ``volume``, else ``tubes`` times its diameter and length, with the catalyst's bulk
    density."""
    density = getattr(getattr(catalyst, "physical", None), "bulk_density", None)
    if bed.catalyst_mass is not None:
        if density:
            return bed.catalyst_mass, bed.catalyst_mass / density
        if bed.volume is not None:
            return bed.catalyst_mass, bed.volume
        raise BedError("the catalyst's bulk density is not given (physical.bulk_density)")
    volume = bed.volume
    if volume is None and bed.diameter and bed.length:
        volume = bed.tubes * math.pi / 4 * bed.diameter**2 * bed.length
    if volume is None:
        raise BedError("the bed gives no catalyst_mass, volume, or diameter and length")
    if not density:
        raise BedError("the catalyst's bulk density is not given (physical.bulk_density)")
    return volume * density, volume


def solve_bed(
    reactions: list[Any],
    feed: Mapping[str, float],
    temperature: float,
    pressure: float,
    bed: Any,
    catalyst: Any,
    data: Mapping[str, Any],
    molar_mass: Mapping[str, float],
) -> BedResult:
    """The outlet of *feed* (kmol/h by component) entering *bed* (holding *catalyst*) at
    *temperature* K and *pressure* kPa(a), through *reactions* (each with a ``rate``); *data*:
    the components' ideal-gas data, *molar_mass* in kg/kmol."""
    lacking = [r.id for r in reactions if r.rate is None]
    if lacking:
        raise BedError("no rate law for reaction " + ", ".join(lacking))
    if not reactions:
        raise BedError("the bed has no reactions")
    # as solve_cstr: no flow, no gas density for Ergun (pre-release issue 251)
    if sum(feed.values()) <= 0:
        raise BedError("the feed is empty")
    mass, volume = bed_mass(bed, catalyst)
    physical = getattr(catalyst, "physical", None)
    bulk = getattr(physical, "bulk_density", None) or mass / volume
    names = list(dict.fromkeys([*feed, *(n for r in reactions for n in r.stoichiometry)]))
    if lack := [n for n in names if not molar_mass.get(n)]:
        raise BedError("no molar_mass for " + ", ".join(lack))
    heat = bed.heat
    if heat != "isothermal" and (lack := missing(names, data)):
        raise BedError(
            "no ideal_gas data for " + ", ".join(lack) + " (a bed that is not isothermal)"
        )
    if heat == "cooled" and (
        bed.coolant_temperature is None or bed.heat_transfer_coefficient is None or not bed.diameter
    ):
        raise BedError(
            "a cooled bed needs coolant_temperature, heat_transfer_coefficient and diameter"
        )
    # the transport gaps are the maturity report's (bed_limitations); a solve notes only what
    # it found, not every check it could not make
    # the transport gap is the maturity report's (bed_limitations); a solve notes what it did
    # not calculate, and its transport checks only where it can make them
    pressure_gap = _pressure_drop_gap(bed, catalyst)
    transport_gap = _transport_gap(bed, catalyst)
    notes: list[str] = [pressure_gap] if pressure_gap else []
    ergun = None
    if pressure_gap is None:
        area = bed.tubes * math.pi / 4 * bed.diameter**2
        dp = physical.particle_diameter * (physical.sphericity or 1.0)
        ergun = (area, dp, physical.bed_voidage, bed.viscosity)
    for r in reactions:
        if not r.rate.covers(temperature):
            notes.append(f"the inlet temperature is outside the rate range of {r.id}")
        no_k = r.rate.reverse == "equilibrium" and r.equilibrium_constant is None
        if no_k and (lack := missing(list(r.stoichiometry), data)):
            raise BedError(
                f"reaction {r.id}: (1 - Q/K) needs an equilibrium_constant or ideal_gas data "
                "for " + ", ".join(lack)
            )
    n = len(names)
    activity = 1.0
    hours = getattr(bed, "time_on_stream", None)
    deactivation = getattr(catalyst, "deactivation", None)
    if hours:
        if deactivation is None or deactivation.law is None:
            raise BedError("time_on_stream needs the catalyst's deactivation law and kd")
        activity = deactivation.activity(hours)
        notes.append(f"catalyst activity {activity:.4g} after {hours:g} h on stream")

    intrinsic = [r.id for r in reactions if r.rate.scale == "intrinsic"]
    if intrinsic and transport_gap:
        raise BedError(
            "the intrinsic rate law(s) of "
            + ", ".join(intrinsic)
            + " need "
            + "; ".join(transport.lacking(catalyst, bed))
        )
    if keyless := [
        r.id
        for r in reactions
        if r.rate.scale == "intrinsic" and not transport.key_order(r.rate, r.stoichiometry)
    ]:
        raise BedError(
            "the intrinsic rate law(s) of " + ", ".join(keyless) + " have no reactant with a "
            "positive order: no effectiveness factor"
        )
    if intrinsic:
        de = transport.effective_diffusivity(catalyst, bed)
        rho_p, length = physical.particle_density, physical.particle_diameter / 6.0
        notes.append(
            "intrinsic rate law(s) of " + ", ".join(intrinsic) + " times the effectiveness "
            "factor tanh(phi)/phi"
        )

    def rates_at(y: Mapping[str, float], t: float, p: float) -> list[float]:
        """kmol/(kg s) of each reaction as the bed uses it (activity, effectiveness)."""
        found = []
        for r in reactions:
            law = r.rate
            k = reaction_ln_k(r, data, t) if law.reverse == "equilibrium" else None
            value = rate(law, r.stoichiometry, y, t, p, k)
            value = activity * (value / bulk if law.basis == "volume" else value)
            if law.scale == "intrinsic" and (key := transport.key_order(law, r.stoichiometry)):
                # the modulus from the forward rate: the net rate of a reversible law vanishes
                # at equilibrium, its diffusion limit does not
                forward = value
                if law.reverse == "equilibrium":
                    plain = law.model_copy(update={"reverse": "none"})
                    forward = rate(plain, r.stoichiometry, y, t, p) * activity
                    forward = forward / bulk if law.basis == "volume" else forward
                c = transport.concentration(y, key[0], t, p)
                value *= transport.effectiveness(
                    transport.thiele(forward, key[1], c, rho_p, length, de)  # type: ignore[arg-type]
                )
            found.append(value)
        return found

    def derivatives(state: list[float]) -> list[float]:
        flows = [max(v, 0.0) for v in state[:n]]
        t, p = state[n], state[n + 1]
        total = sum(flows)
        y = {names[i]: flows[i] / total for i in range(n)} if total > 0 else {}
        rates = rates_at(y, t, p)
        d_flows = [
            sum(r.stoichiometry.get(names[i], 0.0) * rates[j] for j, r in enumerate(reactions))
            for i in range(n)
        ]
        d_t = 0.0
        if heat != "isothermal":
            heat_flow = sum(flows[i] * data[names[i]].cp(t) for i in range(n))  # kW/K
            released = sum(
                -reaction_enthalpy(r.stoichiometry, data, t) * rates[j]
                for j, r in enumerate(reactions)
            )
            if heat == "cooled":
                wall = 4.0 / (bed.diameter * bulk)  # m2 per kg of catalyst
                released += (
                    bed.heat_transfer_coefficient / 1000.0 * wall * (bed.coolant_temperature - t)
                )
            d_t = released / heat_flow if heat_flow > 0 else 0.0
        d_p = 0.0
        if ergun is not None:
            area, dp, e, mu = ergun
            mass_flow = sum(flows[i] * molar_mass[names[i]] for i in range(n))  # kg/s
            flux = mass_flow / area
            mean = mass_flow / total if total > 0 else 0.0  # kg/kmol
            rho = p * mean / (R * t)  # kg/m3: kPa kg/kmol / (kJ/(kmol K) K)
            gradient = flux / (rho * dp) * (1 - e) / e**3 * (150 * (1 - e) * mu / dp + 1.75 * flux)
            d_p = -gradient / (bulk * area) / 1000.0  # Pa/m -> kPa per kg
        return [*d_flows, d_t, d_p]

    try:
        result = _integrate(
            derivatives, feed, names, temperature, pressure, mass, volume, reactions, notes
        )
    except ValueError as failure:  # a rate or an equilibrium constant that cannot be evaluated
        if isinstance(failure, BedError):
            raise
        raise BedError(f"along the bed: {failure}") from failure
    if transport_gap is None:
        try:  # a diagnostic: when it cannot be made, the solved bed stands
            result.transport = _transport_checks(
                result,
                feed,
                names,
                temperature,
                pressure,
                reactions,
                rates_at,
                catalyst,
                bed,
                bulk,
                molar_mass,
            )
        except ValueError as failure:
            result.notes.append(f"no transport checks: {failure}")
    return result


def _transport_checks(
    result: BedResult,
    feed: Mapping[str, float],
    names: list[str],
    temperature: float,
    pressure: float,
    reactions: list[Any],
    rates_at: Any,
    catalyst: Any,
    bed: Any,
    bulk: float,
    molar_mass: Mapping[str, float],
) -> dict[str, Any]:
    """Weisz-Prater and Mears at the inlet and the outlet (:func:`.bed_transport.criteria`),
    and a note for each that limits."""
    area = bed.tubes * math.pi / 4 * bed.diameter**2 if bed.diameter else None
    found: dict[str, Any] = {}
    for where, flows, t, p in (
        ("inlet", feed, temperature, pressure),
        ("outlet", result.outlet, result.temperature, result.pressure),
    ):
        total = sum(flows.values())
        if total <= 0:
            continue
        y = {n: flows.get(n, 0.0) / total for n in names}
        mean = sum(y[n] * molar_mass[n] for n in names)  # kg/kmol
        mass_flow = total / 3600.0 * mean  # kg/s
        flux = mass_flow / area if area else None
        density = p * mean / (R * t)
        found[where] = transport.criteria(
            reactions, rates_at(y, t, p), y, t, p, catalyst, bed, bulk, flux, density
        )
    scales = {r.id: r.rate.scale for r in reactions}
    for rid in scales:
        wp = {w: e[rid]["weisz_prater"] for w, e in found.items() if rid in e}
        if scales[rid] != "intrinsic" and any(v > transport.WEISZ_PRATER for v in wp.values()):
            where = ", ".join(f"{v:.3g} at the {w}" for w, v in wp.items())
            result.notes.append(
                f"Weisz-Prater {where} for {rid}: internal diffusion limits, the rate law is not "
                "the catalyst's own at this particle size (scale: intrinsic, with the "
                "effectiveness factor)"
            )
        mears = {w: e[rid]["mears"] for w, e in found.items() if rid in e and e[rid]["mears"]}
        if any(v > transport.MEARS for v in mears.values()):
            where = ", ".join(f"{v:.3g} at the {w}" for w, v in mears.items())
            result.notes.append(f"Mears {where} for {rid}: the external film limits the rate")
    return found


def _integrate(
    derivatives: Any,
    feed: Mapping[str, float],
    names: list[str],
    temperature: float,
    pressure: float,
    mass: float,
    volume: float,
    reactions: list[Any],
    notes: list[str],
) -> BedResult:
    n = len(names)
    state = [feed.get(name, 0.0) / 3600.0 for name in names] + [temperature, pressure]
    profile = [(0.0, temperature, pressure)]
    marks = [mass * (k + 1) / PROFILE_POINTS for k in range(PROFILE_POINTS)]
    w, h = 0.0, mass / 1000.0
    hot = temperature
    steps = 0
    while w < mass * (1 - 1e-12):
        mark = next(m for m in marks if m > w + 1e-12 * mass)  # the last mark is the bed's end
        h = min(h, mark - w)
        new, error = _dopri_step(derivatives, state, h)
        scale = [
            max(abs(a), abs(b), 1e-9 * sum(state[:n]) + 1e-30)
            for a, b in zip(state, new, strict=True)
        ]
        err = max(abs(e_) / s for e_, s in zip(error, scale, strict=True))
        steps += 1
        if steps > 200000:
            raise BedError("the bed's integration did not finish (too many steps)")
        if err <= 1e-7 or h < mass * 1e-12:
            w += h
            state = [max(v, 0.0) if i < n else v for i, v in enumerate(new)]
            if state[n + 1] <= 0:
                raise BedError(f"the pressure drop exceeds the inlet pressure at {w:.4g} kg")
            hot = max(hot, state[n])
            if abs(w - mark) <= 1e-12 * mass:
                w = mark
                profile.append((w, state[n], state[n + 1]))
            h *= min(5.0, 0.9 * (1e-7 / max(err, 1e-30)) ** 0.2)
        else:
            h *= max(0.1, 0.9 * (1e-7 / err) ** 0.25)
    outlet = {names[i]: state[i] * 3600.0 for i in range(n)}
    # the extents from the outlet: least squares of the component changes (independent rows)
    from chemeascode.domains.chemistry.reactions import fit_extents

    change = {nm: outlet[nm] - feed.get(nm, 0.0) for nm in names}
    extents, _ = fit_extents(reactions, change)
    t_out = state[n]
    for r in reactions:
        if (
            not r.rate.covers(t_out)
            and f"the outlet temperature is outside the rate range of {r.id}" not in notes
        ):
            notes.append(f"the outlet temperature is outside the rate range of {r.id}")
    return BedResult(
        outlet=outlet,
        temperature=t_out,
        pressure=state[n + 1],
        catalyst_mass=mass,
        catalyst_volume=volume,
        extents=extents,
        hot_spot=hot,
        profile=profile,
        notes=notes,
    )


# Dormand-Prince 5(4): nodes, weights of the 5th-order solution and of its error estimate
_C = (0.0, 1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0)
_A = (
    (),
    (1 / 5,),
    (3 / 40, 9 / 40),
    (44 / 45, -56 / 15, 32 / 9),
    (19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729),
    (9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656),
    (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84),
)
_B = (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84, 0.0)
_E = (
    71 / 57600,
    0.0,
    -71 / 16695,
    71 / 1920,
    -17253 / 339200,
    22 / 525,
    -1 / 40,
)


def _dopri_step(f: Any, y: list[float], h: float) -> tuple[list[float], list[float]]:
    """One Dormand-Prince step of size *h*: the new state and the error estimate."""
    k: list[list[float]] = []
    for stage in range(7):
        point = [
            yi + h * sum(a * k[s][i] for s, a in enumerate(_A[stage])) for i, yi in enumerate(y)
        ]
        if stage:
            point = [max(v, 0.0) if i < len(y) - 2 else v for i, v in enumerate(point)]
        k.append(f(point if stage else y))
    new = [yi + h * sum(b * k[s][i] for s, b in enumerate(_B)) for i, yi in enumerate(y)]
    error = [h * sum(e * k[s][i] for s, e in enumerate(_E)) for i in range(len(y))]
    return new, error


def bed_of(process: Any, node: Any) -> tuple[list[Any], Any]:
    """The reactions and the catalyst of reactor *node* (``reactor: pfr``); raises
    :class:`BedError` without a bed, a declared catalyst or declared reactions."""
    if node.bed is None:
        raise BedError("reactor pfr without a bed")
    catalysts = process.catalysts.by_id() if process.catalysts else {}
    catalyst = catalysts.get(node.catalyst or "")
    if catalyst is None:
        raise BedError(f"no declared catalyst ({node.catalyst or 'none named'})")
    reactions, unknown = process.reactions_of(node.id)
    if unknown:
        raise BedError("undeclared reactions " + ", ".join(unknown))
    if liquid := [r.id for r in reactions if r.phase in ("liquid", "mixed")]:
        raise BedError(
            f"the bed model is ideal gas; reaction {', '.join(liquid)} is not a vapour reaction"
        )
    return reactions, catalyst


def solve_node(process: Any, node: Any, inlet: Any, case: str) -> tuple[BedResult, dict[str, Any]]:
    """The bed of reactor *node* (``reactor: pfr``) fed by stream *inlet* in *case*, and what it
    was solved from (the inputs of the outlet's fingerprint). Raises :class:`BedError` naming
    what is missing. One function for ``cheme process propagate`` and ``process reactors``."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    state = inlet.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    kelvin = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    kpa = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if kelvin is None or kpa is None:
        raise BedError(f"no inlet temperature and absolute pressure ({inlet.id})")
    reactions, catalyst = bed_of(process, node)
    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise BedError(f"no composition and flow of {inlet.id}: " + ", ".join(flows.missing))
    comps = process.components()
    names = list(
        dict.fromkeys([*flows.components, *(n for r in reactions for n in r.stoichiometry)])
    )
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
    if lack := [n for n in names if not mw[n]]:
        raise BedError("no molar_mass for " + ", ".join(lack))
    moles = {n: kg / mw[n] for n, kg in flows.components.items()}  # type: ignore[operator]
    data = process.ideal_gas()
    inputs = {
        "T_in": kelvin,
        "P_in": kpa,
        "bed": node.bed.model_dump(mode="json"),
        # what the solution depends on (not the catalyst's price, poisons or lifetime)
        "catalyst": catalyst.physical.model_dump(mode="json") if catalyst.physical else None,
        # the mechanism does not enter the bed (its rates do)
        "reactions": [r.inputs_dump() for r in reactions],
        "ideal_gas": {n: data[n].model_dump(mode="json") if data.get(n) else None for n in names},
        "molar_mass": mw,
    }
    if node.bed.time_on_stream and catalyst.deactivation:
        # only when the bed is solved at an age: a fresh bed's fingerprint stays as it was
        inputs["deactivation"] = catalyst.deactivation.model_dump(mode="json")
    result = solve_bed(reactions, moles, kelvin, kpa, node.bed, catalyst, data, mw)  # type: ignore[arg-type]
    return result, inputs
