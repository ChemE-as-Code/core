"""Stirred tanks: the continuous stirred tank (``reactor: cstr``), the batch (``reactor:
batch``) and the semi-batch (``reactor: semibatch``), from the reactions' rate laws
(:mod:`.chemistry.rates`).

A CSTR is well mixed: the outlet is the tank's content. Per tank of ``count`` equal tanks in
series, the extents ``xi_j`` (kmol/s) solve::

    xi_j = M_j r_j(F_in + nu xi, T)                M_j = V (rate per m3) or W (per kg)
    adiabatic:  H_out(T) = H_in(T_in)              (one more unknown, T)

with ``V`` the tank's volume (or the space time times the inlet's volumetric flow) and ``W =
catalyst_loading V``. At a given temperature the extents come from Newton's method
(finite-difference Jacobian, steps cut back so no flow turns negative and the residual falls,
from the feed); an adiabatic tank's temperature is the zero of H(out) - H(in) nearest the inlet's
(scanned in 2 K steps, then bisected). A stirred tank can have several adiabatic steady
states: the one nearest the inlet is found, and the notes say so.

A batch integrates the moles of a charge over time::

    dn_i/dt = sum_j nu_ij M_j r_j(n, T)            liquid: V = sum n_i v_i; gas: V fixed, P varies
    adiabatic:  dT/dt = sum_j (-dHr_j) M_j r_j / C

to ``time`` or to the ``target`` conversion of its key component (Dormand-Prince 5(4), as the
fixed bed). Its result is intensive: the composition does not depend on the batch size.

A semi-batch (``reactor: semibatch``, liquid) is that batch with the dosed feeds as sources,
``F_d,i`` kmol/s while dose ``d`` runs (piecewise constant), and their sensible heat::

    dn_i/dt = sum_j nu_ij M_j r_j + sum_d F_d,i
    adiabatic:  dT/dt = [sum_j (-dHr_j) M_j r_j + sum_d C_d (T_d - T)] / C

integrated segment by segment, then over the post-reaction (``time`` or ``target``). It reports
the accumulation of the dosed reactant, ``X(t) = n_reagent(t) / (charged + dosed)``, its
maximum, the cooling-failure temperature ``T + max_j (-dHr_j) xi_j,max(n) / C(n)`` at its worst
moment (Stoessel's MTSR of a semi-batch, the dosing stopped) and, isothermal, the peak duty to
remove (the reaction's heat and the doses' warming), per m3 of the final content.

A liquid batch or semi-batch with a ``vent`` (ADR 0054) gives off the vent's components ``g``
as they form, a share ``f_g`` (default 1) of their gross formation, reaction by reaction::

    dn_g/dt = sum_j nu_gj M_j r_j - f_g G_g + sum_d F_d,g     G_g = sum_j max(nu_gj M_j r_j, 0)
    dv_g/dt = f_g G_g                                        (what has left by the vent)

so a reaction that consumes a vented component (or runs back) draws on the liquid's, charged,
dosed or the dissolved share ``1 - f_g`` of what formed, never on the gas that has left.

so a vented product does not accumulate in the liquid, nor count in its volume, concentrations
or heat capacity. Its ``heat_of_reaction`` is taken as forming it as a gas at the vessel's
temperature, where it leaves: the gas carries its own enthalpy away and the liquid's balance
keeps its form (no heat of desorption). A dose with ``absorbed`` dissolves that share on entry;
the rest passes through to the vent, warmed to the vessel's temperature (its ideal-gas heat
capacity, where known). The vent reports what left (kmol per hour of charge) and its peak
rate, kmol/s per m3 of the content at the end, for sizing the off-gas line and scrubber.

Phases: every reaction of a tank is gas-phase or every one liquid-phase (:mod:`.chemistry.liquid`
gives a liquid's mole fractions, activities or concentrations). A gas's enthalpies are the
ideal-gas data's; a liquid's are ``heat_of_reaction`` plus ``liquid_heat_capacity`` (both needed
for an adiabatic liquid, and for a liquid's duty). Pure Python.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.chemistry.equilibrium import reaction_ln_k
from chemeascode.domains.chemistry.rates import rate
from chemeascode.domains.chemistry.reactions import k_basis
from chemeascode.domains.chemistry.thermochemistry import R, missing, mixture_enthalpy
from chemeascode.domains.process.fixed_bed import _dopri_step

#: What the models take for granted (reported by :mod:`.model_basis`), as the fixed bed's
#: :data:`.fixed_bed.ASSUMPTIONS`.
ASSUMPTIONS = {
    "cstr": (
        "steady state",
        "ideally mixed: the outlet is the tank's content, each tank of the series alike",
        "rate laws taken as the effective rates in the tank (no mass transfer between phases)",
        "one phase: a gas as an ideal gas, a liquid with ideal-mixing volumes",
    ),
    "batch": (
        "ideally mixed: one composition and temperature in the vessel at each time",
        "rate laws taken as the effective rates in the vessel (no mass transfer between phases)",
        "one phase: a liquid keeps its composition's volume (ideal mixing), a gas its vessel's "
        "volume as an ideal gas (the pressure changes)",
        "no charging, heating-up or emptying time",
    ),
    "semibatch": (
        "ideally mixed: one composition and temperature in the vessel at each time",
        "rate laws taken as the effective rates in the vessel (no mass transfer between phases)",
        "liquid, ideal-mixing volumes: the volume grows with what is dosed",
        "each dose mixes in at once, at its stream's temperature",
        "a cooling failure stops the dosing (feed interlocked with the cooling): the "
        "cooling-failure temperature is the content's, reacting to completion adiabatically",
        "no charging, heating-up or emptying time",
    ),
    "vent": (
        "a vented component leaves the liquid as it forms (no mass-transfer limit, no "
        "saturation of the liquid), at the vessel's temperature and pressure",
        "a share of what each reaction forms leaves; a reaction consuming it takes it from the "
        "liquid",
        "its heat_of_reaction forms it as a gas: no heat of desorption or solution",
        "a dosed gas dissolves its absorbed share on entry; the rest passes straight through",
        "a dissolving dose adds no heat of absorption or condensation: its reactions' "
        "heat_of_reaction takes it as a gas, so that heat is released as it reacts (the cooling "
        "duty during dosing leaves out the absorption of the gas not yet reacted)",
    ),
}

#: Points of a batch's profile (beside the integrator's own).
PROFILE_POINTS = 50
MAX_NEWTON = 100


class TankError(ValueError):
    """The tank or batch cannot be solved as declared."""


@dataclass
class TankResult:
    """The outlet of a CSTR (series) or batch, and what happened in it."""

    outlet: dict[str, float]  # kmol/h by component
    temperature: float  # K
    pressure: float  # kPa(a)
    kind: str  # cstr or batch
    #: m3 per tank (CSTR) or of the charge per hour of charge (batch)
    volume: float | None = None
    #: s: the space time per tank (CSTR) or the batch time
    time: float | None = None
    #: kW: H(out) - H(in) (CSTR, isothermal); None when not known
    duty: float | None = None
    #: per tank: outlet temperature K and the conversion of each reactant so far
    tanks: list[dict[str, Any]] = field(default_factory=list)
    #: batch: (time s, temperature K, pressure kPa(a), conversion of the key or first reactant)
    profile: list[tuple[float, float, float, float]] = field(default_factory=list)
    #: batch: kJ released per kmol of charge, a semi-batch's charge and doses together
    #: (positive: exothermic), and the largest rate of heat release per m3 of the batch (kW/m3)
    heat_released: float | None = None
    peak_heat_rate: float | None = None
    notes: list[str] = field(default_factory=list)
    #: kmol/h of extent of each reaction over the whole tank series or batch (per hour of
    #: charge): what a conversion reactor needs to give the same outlet
    extents: dict[str, float] = field(default_factory=dict)
    #: semi-batch: s when the last dose ends; m3 of the charge (``volume``: of the content at
    #: the end, both per hour of charge)
    dosing_time: float | None = None
    charge_volume: float | None = None
    #: semi-batch: (time s, unreacted dosed reactant over all of it charged and dosed), its
    #: largest value and when
    accumulation: list[tuple[float, float]] = field(default_factory=list)
    max_accumulation: float | None = None
    max_accumulation_time: float | None = None
    #: semi-batch: the worst moment for a cooling failure, the dosing stopped: (time s,
    #: temperature K, the temperature the content then reaches adiabatically K)
    cooling_failure: tuple[float, float, float] | None = None
    #: semi-batch, isothermal: the largest duty to remove, kW per m3 of the content at the end
    #: (the reaction's heat and the doses' warming to the batch's temperature)
    peak_cooling_duty: float | None = None
    #: vented (ADR 0054): kmol by component that left by the vent (per hour of charge, as
    #: ``outlet``: what formed and a dosed gas's share that passed through), its largest rate in
    #: kmol/s per m3 of the content at the end, and when
    vent: dict[str, float] = field(default_factory=dict)
    peak_vent_rate: float | None = None
    peak_vent_time: float | None = None
    #: vented: the peak in kmol/s on the batch's basis (per hour of charge; times a batch's
    #: hours of flows, one batch's)
    peak_vent_flow: float | None = None


@dataclass
class _Mixture:
    """How compositions become rates, volumes and enthalpies in one phase."""

    reactions: list[Any]
    names: list[str]
    data: Mapping[str, Any]
    liquid: Any  # a chemistry.liquid.Liquid, or None for a gas
    heat_capacity: Mapping[str, float | None]
    loading: float | None
    #: components vented as they form (fraction 1): never in the liquid, so no trace of them
    gone: frozenset[str] = frozenset()

    def nu(self) -> list[list[float]]:
        return [[r.stoichiometry.get(n, 0.0) for r in self.reactions] for n in self.names]

    def rates(self, moles: Sequence[float], t: float, p: float) -> list[float]:
        """kmol/(m3 s) or kmol/(kg s) per reaction at the composition *moles*."""
        total = sum(moles)
        # a trace instead of zero: an integrator's trial stage may empty a reactant, where a
        # (1 - Q/K) law is not defined; the trace gives a large reverse rate the step rejects
        x = {
            n: 0.0 if n in self.gone else max(v / total, 1e-30)
            for n, v in zip(self.names, moles, strict=True)
        }
        found = []
        for r in self.reactions:
            law = r.rate
            basis = k_basis(r)
            ln_k = reaction_ln_k(r, self.data, t, basis) if law.reverse == "equilibrium" else None
            found.append(rate(law, r.stoichiometry, x, t, p, ln_k, self.liquid, basis))
        return found

    def multipliers(self, volume: float) -> list[float]:
        """M_j: the volume (rate per m3) or the catalyst mass (rate per kg) of each rate."""
        found = []
        for r in self.reactions:
            if r.rate.basis == "catalyst_mass":
                if self.loading is None:
                    raise TankError(
                        f"reaction {r.id}: a rate per kg of catalyst needs catalyst_loading"
                    )
                found.append(volume * self.loading)
            else:
                found.append(volume)
        return found

    def volume_flow(self, moles: Mapping[str, float], t: float, p: float) -> float:
        """m3/s of a flow of *moles* (kmol/s)."""
        if self.liquid is not None:
            total = sum(moles.values())
            if total <= 0:
                return 0.0
            return total * self.liquid.molar_volume({n: v / total for n, v in moles.items()})
        return sum(moles.values()) * R * t / p

    def heats(self, t: float) -> list[float]:
        """kJ/kmol of extent of each reaction: a liquid's heat_of_reaction, a gas's from the
        ideal-gas data. Raises TankError naming what is missing."""
        from chemeascode.domains.chemistry.thermochemistry import reaction_enthalpy

        found = []
        for r in self.reactions:
            if self.liquid is not None:
                if r.heat_of_reaction is None:
                    raise TankError(f"reaction {r.id}: no heat_of_reaction for the liquid")
                found.append(r.heat_of_reaction.value)
            else:
                if lack := missing(list(r.stoichiometry), self.data):
                    raise TankError("no ideal_gas data for " + ", ".join(lack))
                found.append(reaction_enthalpy(r.stoichiometry, self.data, t))
        return found

    def capacity(self, moles: Mapping[str, float], t: float) -> float:
        """kJ/K of the amounts *moles* (kmol): a liquid's liquid_heat_capacity, a gas's ideal-gas
        cp less R (a closed gas batch is at constant volume)."""
        if self.liquid is not None:
            lacking = [n for n, v in moles.items() if v > 0 and not self.heat_capacity.get(n)]
            if lacking:
                raise TankError("no liquid_heat_capacity for " + ", ".join(sorted(lacking)))
            return sum(v * (self.heat_capacity[n] or 0.0) for n, v in moles.items() if v > 0)
        lacking = missing([n for n, v in moles.items() if v > 0], self.data)
        if lacking:
            raise TankError("no ideal_gas data for " + ", ".join(lacking))
        return sum(v * (self.data[n].cp(t) - R) for n, v in moles.items() if v > 0)

    def duty(
        self,
        f_in: Mapping[str, float],
        t_in: float,
        f_out: Mapping[str, float],
        t: float,
        extents: Sequence[float],
    ) -> float:
        """kW: H(out) - H(in) of flows in kmol/s."""
        if self.liquid is not None:
            heat = sum(x * h for x, h in zip(extents, self.heats(t_in), strict=True))
            return heat + self.capacity(f_out, t) * (t - t_in)
        names = [n for n in set(f_in) | set(f_out) if f_in.get(n, 0) > 0 or f_out.get(n, 0) > 0]
        if lack := missing(names, self.data):
            raise TankError("no ideal_gas data for " + ", ".join(lack))
        hour = {n: v * 3600.0 for n, v in f_out.items()}
        return mixture_enthalpy(hour, self.data, t) - mixture_enthalpy(
            {n: v * 3600.0 for n, v in f_in.items()}, self.data, t_in
        )


def _adiabatic_temperature(energy: Callable[[float], float], t_in: float) -> float:
    """The temperature where *energy* (kW, H(out) - H(in)) is zero, nearest the inlet's: from
    *t_in* in the direction the inlet's imbalance says (up when the reactions release heat), in
    steps of 2 K to a sign change (at most 3000 K away), then by bisection. Raises TankError."""
    e0 = energy(t_in)
    if e0 == 0:
        return t_in
    direction = 1.0 if e0 < 0 else -1.0
    lo, e_lo = t_in, e0
    step = 2.0
    while True:
        hi = lo + direction * step
        if hi <= 1.0 or abs(hi - t_in) > 3000.0:
            raise TankError("no adiabatic steady state within 3000 K of the inlet")
        e_hi = energy(hi)
        if (e_hi < 0) != (e_lo < 0) or e_hi == 0:
            break
        lo, e_lo = hi, e_hi
    for _ in range(80):
        mid = (lo + hi) / 2
        e_mid = energy(mid)
        if (e_mid < 0) == (e_lo < 0):
            lo, e_lo = mid, e_mid
        else:
            hi = mid
        if abs(hi - lo) < 1e-9:
            break
    return (lo + hi) / 2


def _newton(
    residual: Callable[[list[float]], list[float]],
    x0: list[float],
    feasible: Callable[[list[float]], bool],
    scale: list[float],
) -> list[float]:
    """A zero of *residual* from *x0* (Newton, finite-difference Jacobian, damped so that
    *feasible* holds and the scaled residual falls). Raises TankError when it stalls."""
    x = list(x0)
    m = len(x)

    def size(res: list[float]) -> float:
        return max(abs(r) / s for r, s in zip(res, scale, strict=True))

    def norm(res: list[float]) -> float:
        # the Newton direction lowers the sum of squares (not always the largest residual)
        return sum((r / s) ** 2 for r, s in zip(res, scale, strict=True))

    res = residual(x)
    for _ in range(MAX_NEWTON):
        if size(res) < 1e-11:
            return x
        jac = [[0.0] * m for _ in range(m)]
        for k in range(m):
            h = 1e-7 * max(abs(x[k]), scale[k])
            trial = list(x)
            trial[k] += h
            if not feasible(trial):
                trial[k] = x[k] - h
                h = -h
            res_k = residual(trial)
            for i in range(m):
                jac[i][k] = (res_k[i] - res[i]) / h
        step = _solve(jac, [-v for v in res])
        alpha = 1.0
        while alpha > 1e-10:
            trial = [a + alpha * s for a, s in zip(x, step, strict=True)]
            if feasible(trial):
                new = residual(trial)
                if norm(new) < norm(res) or size(new) < 1e-11:
                    x, res = trial, new
                    break
            alpha /= 2
        else:
            raise TankError("the tank's balances did not converge (Newton stalled)")
    if size(res) < 1e-8:
        return x
    raise TankError(f"the tank's balances did not converge in {MAX_NEWTON} Newton steps")


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    from chemeascode.domains.chemistry.equilibrium import _solve as solve

    return solve(a, b)


def _mixture(
    reactions: list[Any],
    names: list[str],
    data: Mapping[str, Any],
    liquid: Any,
    heat_capacity: Mapping[str, float | None],
    loading: float | None,
) -> _Mixture:
    phases = {r.phase == "liquid" for r in reactions}
    if any(r.phase == "mixed" for r in reactions) or len(phases) > 1:
        raise TankError("a tank holds gas-phase or liquid-phase reactions, not both (or mixed)")
    if lacking := [r.id for r in reactions if r.rate is None]:
        raise TankError("no rate law for " + ", ".join(lacking))
    if intrinsic := [r.id for r in reactions if r.rate.scale == "intrinsic"]:
        raise TankError(
            "the intrinsic rate law(s) of " + ", ".join(intrinsic) + ": a stirred tank has no "
            "particle model; give the effective rate (scale: effective)"
        )
    is_liquid = phases == {True}
    return _Mixture(reactions, names, data, liquid if is_liquid else None, heat_capacity, loading)


def solve_cstr(
    reactions: list[Any],
    feed: Mapping[str, float],
    temperature: float,
    pressure: float,
    tank: Any,
    data: Mapping[str, Any],
    liquid: Any = None,
    heat_capacity: Mapping[str, float | None] | None = None,
    isothermal_at: float | None = None,
    activity: float = 1.0,
) -> TankResult:
    """The outlet of *feed* (kmol/h) at *temperature* K and *pressure* kPa through the
    ``count`` tanks of *tank* (a :class:`~.schema.Tank`). An isothermal tank is at
    *isothermal_at* (the outlet's given temperature), else at the inlet's. Raises TankError."""
    names = list(dict.fromkeys([*feed, *(n for r in reactions for n in r.stoichiometry)]))
    mix = _mixture(reactions, names, data, liquid, heat_capacity or {}, tank.catalyst_loading)
    nu = mix.nu()
    m = len(reactions)
    f = {n: feed.get(n, 0.0) / 3600.0 for n in names}  # kmol/s
    total0 = sum(f.values())
    if total0 <= 0:
        raise TankError("the feed is empty")
    volume = tank.volume
    if volume is None:
        volume = tank.residence_time * mix.volume_flow(f, temperature, pressure)
    t_in = temperature
    t = isothermal_at if (tank.heat == "isothermal" and isothermal_at) else temperature
    result = TankResult({}, t, pressure, "cstr", volume=volume)
    result.time = volume / mix.volume_flow(f, temperature, pressure)
    adiabatic = tank.heat == "adiabatic"
    if adiabatic:
        result.notes.append(
            "adiabatic: the steady state nearest the inlet temperature; a stirred tank can "
            "have several steady states"
        )
    duty = 0.0
    duty_known = True
    first = dict(f)
    multipliers = [activity * v for v in mix.multipliers(volume)]  # equal tanks
    for k in range(tank.count):
        warm: list[list[float]] = [[0.0] * m]  # the last extents: the next temperature's start

        def outlet(xi: list[float], f: dict[str, float] = f) -> list[float]:
            return [f[n] + sum(nu[i][j] * xi[j] for j in range(m)) for i, n in enumerate(names)]

        def isothermal(
            temp: float, outlet: Any = outlet, k: int = k, warm: list[list[float]] = warm
        ) -> list[float]:
            """The extents of this tank at *temp*: Newton from the feed, else by continuation
            in the tank's size (from a hundredth of it up, each solution the next start)."""

            def feasible(xi: list[float]) -> bool:
                return min(outlet(xi)) >= -1e-14 * total0

            def solve_at(share: float, start: list[float]) -> list[float]:
                def residual(xi: list[float]) -> list[float]:
                    rates = mix.rates([max(v, 0.0) for v in outlet(xi)], temp, pressure)
                    return [xi[j] - share * multipliers[j] * rates[j] for j in range(m)]

                return _newton(residual, start, feasible, [total0] * m)

            for start in (warm[0], [0.0] * m):
                try:
                    warm[0] = solve_at(1.0, start)
                    return warm[0]
                except ValueError:
                    pass
            xi = [0.0] * m
            try:
                for n in range(41):
                    xi = solve_at(10 ** (-2 + n / 20), xi)
            except ValueError as failure:
                raise TankError(f"tank {k + 1} at {temp:.6g} K: {failure}") from failure
            warm[0] = xi
            return xi

        def energy(temp: float, f: dict[str, float] = f, t_in: float = t_in) -> float:
            """kW: H(out) - H(in) with the extents at *temp*; zero at the adiabatic state."""
            found = isothermal(temp)
            out = {n: max(v, 0.0) for n, v in zip(names, outlet(found), strict=True)}
            return mix.duty(f, t_in, out, temp, found)

        temp = t
        if adiabatic:
            temp = _adiabatic_temperature(energy, t_in)
        extents = isothermal(temp)
        for j, r in enumerate(reactions):
            result.extents[r.id] = result.extents.get(r.id, 0.0) + extents[j] * 3600.0
        out = {n: max(v, 0.0) for n, v in zip(names, outlet(extents), strict=True)}
        if not adiabatic:
            try:
                duty += mix.duty(f, t_in, out, temp, extents)
            except TankError:
                duty_known = False
        reactants = [n for n in names if first.get(n, 0) > 0 and out.get(n, 0) < first[n]]
        result.tanks.append(
            {
                "temperature_K": temp,
                "conversion": {n: 1 - out[n] / first[n] for n in reactants},
            }
        )
        f, t_in = out, temp
    for k, tank_result in enumerate(result.tanks, start=1):
        for r in reactions:
            if not r.rate.covers(t_k := tank_result["temperature_K"]):
                result.notes.append(f"tank {k}: {t_k:.6g} K is outside the rate's range of {r.id}")
    result.outlet = {n: v * 3600.0 for n, v in f.items()}
    result.temperature = t_in
    result.duty = None if adiabatic else (duty if duty_known else None)
    if result.duty is None and not adiabatic:
        result.notes.append("no duty: enthalpy data missing")
    return result


@dataclass
class Dose:
    """A feed dosed into a semi-batch: kmol (on the charge's basis) by component, its
    temperature, and its segments (start s, end s, share of the feed) at constant rates."""

    moles: Mapping[str, float]
    temperature: float  # K
    segments: list[tuple[float, float, float]]
    #: kmol by component of a dosed gas that passes through to the vent (``absorbed`` < 1);
    #: ``moles`` is then the share that dissolves
    passing: Mapping[str, float] = field(default_factory=dict)

    def rate(self, t: float) -> float:
        """The share of the feed per second at time *t* s."""
        return sum(s / (b - a) for a, b, s in self.segments if a <= t < b)

    def fed(self, t: float) -> float:
        """The share of the feed dosed by time *t* s."""
        return sum(s * min(max((t - a) / (b - a), 0.0), 1.0) for a, b, s in self.segments)


def solve_batch(
    reactions: list[Any],
    charge: Mapping[str, float],
    temperature: float,
    pressure: float,
    batch: Any,
    data: Mapping[str, Any],
    liquid: Any = None,
    heat_capacity: Mapping[str, float | None] | None = None,
    isothermal_at: float | None = None,
    doses: Sequence[Dose] = (),
) -> TankResult:
    """The composition of the *charge* (kmol, or kmol/h of charge) at *temperature* K and
    *pressure* kPa after *batch* (a :class:`~.schema.Batch`): its ``time``, or its ``target``
    conversion. Raises TankError, also when the target is not reached (the batch stops
    converting first, at equilibrium or when a reactant is used up).

    With *doses* it is a semi-batch (liquid): the doses enter at their rates, and the batch's
    ``time`` or ``target`` is the post-reaction after the last dose. The result then has the
    accumulation of the dosed reactant over time, the worst cooling failure and the peak
    cooling duty.

    With ``batch.vent`` (liquid), the vent's components leave as they form (see the module
    docstring); the result's ``vent`` is what left, ``outlet`` the liquid."""
    doses = list(doses)
    vent = getattr(batch, "vent", None)
    shares = vent.shares() if vent is not None else {}
    names = list(
        dict.fromkeys(
            [
                *charge,
                *(n for d in doses for n in d.moles),
                *(n for d in doses for n in d.passing),
                *(n for r in reactions for n in r.stoichiometry),
                *shares,
            ]
        )
    )
    mix = _mixture(reactions, names, data, liquid, heat_capacity or {}, batch.catalyst_loading)
    nu = mix.nu()
    m = len(reactions)
    size = len(names)  # the liquid's components; a vent's running totals follow in the state
    n0 = [max(charge.get(n, 0.0), 0.0) for n in names]
    total0 = sum(n0)
    if total0 <= 0:
        raise TankError("the charge is empty")
    if not doses and batch.time is None and batch.target is None:
        raise TankError("a batch needs its time or target (batch.dosing makes a semibatch)")
    if doses and mix.liquid is None:
        raise TankError("a semi-batch holds liquid-phase reactions (phase: liquid)")
    passing = {n: sum(d.passing.get(n, 0.0) for d in doses) for n in names}
    passing = {n: v for n, v in passing.items() if v > 0}
    if (shares or passing) and mix.liquid is None:
        raise TankError("a vent takes its gas from a liquid: liquid-phase reactions only")
    if passing and vent is None:
        raise TankError("a dosed gas passes through (absorbed below 1) but there is no vent")
    dose_moles = [[max(d.moles.get(n, 0.0), 0.0) for n in names] for d in doses]
    dosed = [sum(d[i] for d in dose_moles) for i in range(len(names))]
    vented = [names.index(n) for n in shares]  # the vent's components, in the state's order
    vent_share = [shares[names[i]] for i in vented]
    # vented whole and never charged or dosed: no trace of it in the liquid's composition
    mix.gone = frozenset(
        names[i] for i, f in zip(vented, vent_share, strict=True) if f >= 1.0 and not n0[i]
    ) - {n for i, n in enumerate(names) if dosed[i] > 0}
    charged = [n for n in names if charge.get(n, 0.0) > 0]
    is_reactant = {n for r in reactions for n, v in r.stoichiometry.items() if v < 0}
    # the dosed reactant whose accumulation the semi-batch reports
    reagent = next((n for i, n in enumerate(names) if dosed[i] > 0 and n in is_reactant), None)
    if batch.target is not None:
        key = batch.target.key
        if key not in names or (charge.get(key, 0.0) <= 0 and dosed[names.index(key)] <= 0):
            raise TankError(f"the target's key component {key} is not charged")
    elif reagent is not None:
        key = reagent
    else:  # the profile's conversion: of the first charged reactant, else of a charged one
        key = next((n for n in charged if n in is_reactant), charged[0])
    ki = names.index(key)
    if batch.heat == "isothermal" and isothermal_at:
        temperature = isothermal_at  # the batch is held at its given temperature
    gas_volume = None if mix.liquid is not None else total0 * R * temperature / pressure
    adiabatic = batch.heat == "adiabatic"
    dnu = [sum(r.stoichiometry.values()) for r in reactions]

    def energies(t: float) -> list[float]:
        """kJ/kmol of extent released into the batch: a liquid's heat of reaction; a closed
        gas's internal energy of reaction at constant volume, dH - dnu R T."""
        found = mix.heats(t)
        if mix.liquid is None:
            found = [h - d * R * t for h, d in zip(found, dnu, strict=True)]
        return found

    if adiabatic:
        energies(temperature)  # a TankError names what is missing before the run
    # kJ/K of each whole dose (None: no liquid_heat_capacity): its sensible heat on entering
    dose_capacity: list[float | None] = []
    for d in doses:
        try:
            dose_capacity.append(mix.capacity(d.moles, d.temperature))
        except TankError:
            if adiabatic:
                raise
            dose_capacity.append(None)
    # kJ/K of the gas of each dose that passes through to the vent, warmed to the vessel's
    # temperature: its ideal-gas cp at the dose's temperature (None: no ideal_gas data)
    passing_capacity: list[float | None] = []
    no_gas_data: set[str] = set()
    for d in doses:
        through = {n: v for n, v in d.passing.items() if v > 0}
        if lack := missing(list(through), data):
            no_gas_data |= set(lack)
            passing_capacity.append(None)
        else:
            passing_capacity.append(
                sum(v * data[n].cp(d.temperature) for n, v in through.items()) or None
            )

    def volume_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is not None:
            return gas_volume
        return mix.volume_flow(dict(zip(names, moles, strict=True)), t, pressure)

    def pressure_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is None:
            return pressure
        return sum(moles) * R * t / gas_volume

    def feeding(t: float) -> tuple[list[float], list[tuple[float, float]]]:
        """kmol/s by component dosed at time *t*, and (kW/K, K) of each dose then: its heat
        capacity flow and temperature (of a dosed gas passing through to the vent too)."""
        found = [0.0] * len(names)
        sensible = []
        for d, amounts, cap, gas in zip(
            doses, dose_moles, dose_capacity, passing_capacity, strict=True
        ):
            if (share := d.rate(t)) > 0:
                found = [a + share * v for a, v in zip(found, amounts, strict=True)]
                if cap is not None:
                    sensible.append((share * cap, d.temperature))
                if gas is not None:
                    sensible.append((share * gas, d.temperature))
        return found, sensible

    def passing_rate(t: float) -> float:
        """kmol/s of dosed gas passing through to the vent at time *t*."""
        return sum(d.rate(t) * sum(d.passing.values()) for d in doses)

    def fed(t: float) -> list[float]:
        """kmol by component dosed by time *t*."""
        found = [0.0] * len(names)
        for d, amounts in zip(doses, dose_moles, strict=True):
            share = d.fed(t)
            found = [a + share * v for a, v in zip(found, amounts, strict=True)]
        return found

    def conversion(state: list[float], clock: float) -> float:
        given = n0[ki] + (fed(clock)[ki] if doses else 0.0)
        return 1.0 - state[ki] / given if given > 0 else 0.0

    def potential(moles: Sequence[float], t: float) -> float:
        """K: the rise if cooling fails now and the dosing stops: the largest heat of one
        reaction run to completion of what is in the vessel, over its heat capacity."""
        heats = energies(t)
        best = 0.0
        for j in range(m):
            if heats[j] < 0:
                extent = min(moles[i] / -nu[i][j] for i in range(len(names)) if nu[i][j] < 0)
                best = max(best, -heats[j] * extent)
        return best / mix.capacity(dict(zip(names, moles, strict=True)), t)

    try:
        energies(temperature)
        known = True
    except TankError:
        known = False
    worst_known = bool(doses) and known
    missing_cooling = ""
    if worst_known:
        # every component that can be in the vessel: charged, dosed or formed (and not vented)
        present = {
            n: 1.0
            for i, n in enumerate(names)
            if n0[i] > 0
            or dosed[i] > 0
            or (n not in mix.gone and any(nu[i][j] > 0 for j in range(m)))
        }
        try:
            mix.capacity(present, temperature)
        except TankError as failure:
            worst_known = False
            missing_cooling = str(failure)

    def run(
        state: list[float],
        clock: float,
        t_end: float | None,
        target: float | None,
        source: list[float],
        sensible: list[tuple[float, float]],
        post: bool,
    ) -> tuple[list[float], float]:
        """From *state* at *clock* s to *t_end* s or the *target* conversion, *source* kmol/s
        dosed meanwhile; the accepted steps go into the result."""
        nonlocal heat, peak, cooling, stalled

        def derivatives(state: list[float]) -> list[float]:
            moles, t = state[:size], state[-2]
            v = volume_of(moles, t)
            mult = mix.multipliers(v)
            rates = mix.rates(moles, t, pressure_of(moles, t))
            extent = [mult[j] * rates[j] for j in range(m)]
            dn = [
                sum(nu[i][j] * extent[j] for j in range(m)) + source[i] for i in range(len(names))
            ]
            leaving = []  # kmol/s of each vented component leaving as it forms
            for i, f in zip(vented, vent_share, strict=True):
                # a share of what the reactions form (each reaction's own), not of the net:
                # what another reaction consumes it takes from the liquid, never back from
                # the gas that has left
                out = f * sum(max(nu[i][j] * extent[j], 0.0) for j in range(m))
                dn[i] -= out
                leaving.append(out)
            dt = 0.0
            if adiabatic:
                cap = mix.capacity(dict(zip(names, moles, strict=True)), t)
                heats = energies(t)
                gain = sum(-h * e for h, e in zip(heats, extent, strict=True))
                gain += sum(c * (t_dose - t) for c, t_dose in sensible)
                dt = gain / cap
            return [*dn, *leaving, dt, 0.0]

        h = ((t_end - clock) if t_end is not None else 1.0) / 1000.0
        while True:
            if t_end is not None:
                h = min(h, t_end - clock)
            new, error = _dopri_step(derivatives, state, h)
            scale = [
                max(abs(a), abs(b), 1e-9 * total0)
                for a, b in zip(state[:-2], new[:-2], strict=True)
            ] + [max(abs(state[-2]), 1.0), 1.0]
            err = max(abs(e) / s for e, s in zip(error, scale, strict=True))
            if err > 1e-7 and h > 1e-12:
                h *= max(0.2, 0.9 * (1e-7 / err) ** 0.2)
                continue
            if target is not None and conversion(new, clock + h) >= target:
                # the target lies inside this step: bisect the step size
                lo, hi = 0.0, h
                for _ in range(60):
                    mid = (lo + hi) / 2
                    trial, _ = _dopri_step(derivatives, state, mid)
                    if conversion(trial, clock + mid) >= target:
                        hi = mid
                    else:
                        lo = mid
                new, _ = _dopri_step(derivatives, state, hi)
                h = hi
            new[:-2] = [max(v, 0.0) for v in new[:-2]]
            # what reacted in this step: the change of moles less what was dosed, and what left
            d_moles = [
                b - a - s * h for a, b, s in zip(state[:size], new[:size], source, strict=True)
            ]
            for k, i in enumerate(vented):
                d_moles[i] += new[size + k] - state[size + k]
            if known:
                # the extents of this step from its change of moles, at the step's temperature
                released = _released(mix, nu, d_moles, energies(state[-2]))
                heat += released
                v = volume_of(new[:size], new[-2])
                if h > 0 and v > 0:
                    peak = max(peak, released / h / v)
                if doses and h > 0 and not adiabatic:
                    # kW to remove: the reaction's heat and the doses' warming to the batch
                    warming = sum(c * (t_dose - new[-2]) for c, t_dose in sensible)
                    cooling = max(cooling, released / h + warming)
            previous = conversion(state, clock)
            clock += h
            progress = abs(conversion(new, clock) - previous)
            state = new
            record(state, clock)
            if t_end is not None and clock >= t_end * (1 - 1e-12):
                return state, clock
            if target is not None and conversion(state, clock) >= target - 1e-12:
                return state, clock
            if not post:
                h = min(h * 2, max(clock, h) * 10)
                continue
            stalled = stalled + 1 if progress < 1e-12 else 0
            if target is None and stalled > 50:
                result.notes.append(
                    f"converts no further after {clock:.4g} s (equilibrium, or a reactant used up)"
                )
                return state, t_end  # type: ignore[return-value]
            if stalled > 50 or clock > 1e9:
                raise TankError(
                    f"the target conversion {target:g} of {key} is not reached: the batch stops "
                    f"at {conversion(state, clock):.4g} (equilibrium, or a reactant used up)"
                )
            h = min(h * 2, max(clock, h) * 10)

    reagent_total = (n0[names.index(reagent)] + dosed[names.index(reagent)]) if reagent else 0.0
    worst: list[float] = []  # time s, temperature K, temperature after a cooling failure K

    def vent_rate(state: list[float]) -> float:
        """kmol/s leaving by the vent at *state*: what forms of the vented components, and the
        dosed gas passing through now."""
        moles, t = state[:size], state[-2]
        mult = mix.multipliers(volume_of(moles, t))
        rates = mix.rates(moles, t, pressure_of(moles, t))
        extent = [mult[j] * rates[j] for j in range(m)]
        formed = sum(
            f * sum(max(nu[i][j] * extent[j], 0.0) for j in range(m))
            for i, f in zip(vented, vent_share, strict=True)
        )
        return formed + passing_now

    def record(state: list[float], clock: float) -> None:
        nonlocal peak_vent, peak_vent_time
        moles, t = state[:size], state[-2]
        result.profile.append((clock, t, pressure_of(moles, t), conversion(state, clock)))
        if vent is not None and (rate_now := vent_rate(state)) > peak_vent:
            peak_vent, peak_vent_time = rate_now, clock
        if not doses:
            return
        if reagent is not None and reagent_total > 0:
            result.accumulation.append((clock, moles[names.index(reagent)] / reagent_total))
        if worst_known:
            try:
                reached = t + potential(moles, t)
            except TankError:
                return  # no heat capacity of what is there: no value at this step
            if not worst or reached > worst[2]:
                worst[:] = [clock, t, reached]

    state = [*n0, *(0.0 for _ in vented), temperature, pressure]
    result = TankResult({}, temperature, pressure, "semibatch" if doses else "batch")
    heat = 0.0
    peak = 0.0
    cooling = 0.0
    stalled = 0
    clock = 0.0
    peak_vent = 0.0
    peak_vent_time = 0.0
    breaks = sorted({0.0, *(x for d in doses for a, b, _ in d.segments for x in (a, b))})
    passing_now = passing_rate((breaks[0] + breaks[1]) / 2) if len(breaks) > 1 else 0.0
    record(state, clock)
    zero = [0.0] * len(names)
    for a, b in zip(breaks, breaks[1:], strict=False):
        source, sensible = feeding((a + b) / 2)
        passing_now = passing_rate((a + b) / 2)
        state, clock = run(state, clock, b, None, source, sensible, post=False)
    dosing_end = clock
    passing_now = 0.0
    target = batch.target.conversion if batch.target else None
    if not doses:
        state, clock = run(state, clock, batch.time, target, zero, [], post=True)
    elif target is not None and conversion(state, clock) >= target:
        result.notes.append(
            f"the target conversion {target:g} of {key} is reached when the dosing ends"
        )
    elif batch.time is not None or target is not None:
        t_end = clock + batch.time if batch.time is not None else None
        state, clock = run(state, clock, t_end, target, zero, [], post=True)
    result.outlet = dict(zip(names, state[:size], strict=True))
    change = [b - a - d for a, b, d in zip(n0, state[:size], dosed, strict=True)]
    for k, i in enumerate(vented):  # what formed and left by the vent formed all the same
        change[i] += state[size + k]
    gram = [
        [sum(nu[i][j] * nu[i][k] for i in range(len(names))) for k in range(m)] for j in range(m)
    ]
    fitted = _solve(gram, [sum(nu[i][j] * change[i] for i in range(len(names))) for j in range(m)])
    result.extents = {r.id: x for r, x in zip(reactions, fitted, strict=True)}
    # the outlet the extents give: the integrator clips a reactant at zero now and then, and a
    # conversion reactor (the DWSIM coupling) must reproduce the outlet from the extents
    result.outlet = {
        n: max(n0[i] + dosed[i] + sum(nu[i][j] * fitted[j] for j in range(m)), 0.0)
        for i, n in enumerate(names)
    }
    if vent is not None:
        # the liquid keeps what the run left in it; the vent takes the rest of what was charged,
        # dosed and formed (the two outlets close the balance on the extents), and the dosed gas
        # that passed through
        for i in vented:
            name = names[i]
            kept = max(state[i], 0.0)
            result.vent[name] = max(result.outlet[name] - kept, 0.0)
            result.outlet[name] = kept
        for name, amount in passing.items():
            result.vent[name] = result.vent.get(name, 0.0) + amount
        end_volume = volume_of(state[:size], state[-2])
        result.peak_vent_rate = peak_vent / end_volume if end_volume > 0 else None
        result.peak_vent_time = peak_vent_time
        result.peak_vent_flow = peak_vent
        unformed = [n for n in shares if not any(r.stoichiometry.get(n, 0) > 0 for r in reactions)]
        if unformed:
            result.notes.append(
                "vent: " + ", ".join(unformed) + " formed by no reaction: none of it vents"
            )
        if no_gas_data:
            result.notes.append(
                "vent: the sensible heat of the dosed gas passing through is left out (no "
                "ideal_gas data for " + ", ".join(sorted(no_gas_data)) + ")"
            )
    result.temperature = state[-2]
    result.pressure = pressure_of(state[:size], state[-2])
    result.time = clock
    result.volume = volume_of(n0, temperature)
    if known:
        result.heat_released = heat / (total0 + sum(dosed))
        result.peak_heat_rate = peak
    if doses:
        result.dosing_time = dosing_end
        result.volume = volume_of(state[:size], state[-2])
        result.charge_volume = volume_of(n0, temperature)
        if result.accumulation:
            result.max_accumulation_time, result.max_accumulation = max(
                result.accumulation, key=lambda p: p[1]
            )
        if worst:
            result.cooling_failure = (worst[0], worst[1], worst[2])
        elif known:
            result.notes.append(f"no cooling-failure temperature: {missing_cooling}")
        if known and not adiabatic and result.volume:
            result.peak_cooling_duty = cooling / result.volume
        if reagent is None:
            result.notes.append("no dosed reactant: no accumulation")
    for r in reactions:
        hottest = max(p[1] for p in result.profile)
        if not r.rate.covers(hottest) or not r.rate.covers(temperature):
            result.notes.append(f"the batch leaves the rate's temperature range of {r.id}")
    if len(result.profile) > PROFILE_POINTS:
        step = len(result.profile) / PROFILE_POINTS
        picked = [int(k * step) for k in range(PROFILE_POINTS)]
        result.profile = [*(result.profile[k] for k in picked), result.profile[-1]]
        if result.accumulation:
            result.accumulation = [
                *(result.accumulation[k] for k in picked),
                result.accumulation[-1],
            ]
    return result


def _released(
    mix: _Mixture, nu: list[list[float]], d_moles: list[float], heats: list[float]
) -> float:
    """kJ released by a change of the moles *d_moles*: its extents (least squares over the
    stoichiometry) times minus the heats of reaction; positive for an exothermic change."""
    m = len(mix.reactions)
    a = [[sum(nu[i][j] * nu[i][k] for i in range(len(nu))) for k in range(m)] for j in range(m)]
    b = [sum(nu[i][j] * d_moles[i] for i in range(len(nu))) for j in range(m)]
    extents = _solve(a, b)
    return -sum(x * h for x, h in zip(extents, heats, strict=True))


def tank_inlet(node: Any, inlets: Sequence[Any]) -> Any:
    """What :func:`solve_node` takes of tank or batch *node*'s inlet streams: the one inlet, or
    a semi-batch's every inlet (its charge and its doses). Energy and information streams (an
    agitator's power) are no inlet of the content. Raises TankError."""
    inlets = [s for s in inlets if getattr(s, "kind", "material") == "material"]
    if node.reactor == "semibatch":
        return inlets
    if len(inlets) != 1:
        raise TankError(f"a {node.reactor} takes one inlet stream (mix the feeds before it)")
    return inlets[0]


def split_inlets(node: Any, inlets: Sequence[Any]) -> tuple[Any, list[tuple[Any, Any]]]:
    """A semi-batch's charge stream and its (dosing, stream) pairs among *inlets*. Raises
    TankError when a dosed stream is no inlet, or the charge is not one stream. Energy and
    information streams are left out."""
    inlets = [s for s in inlets if getattr(s, "kind", "material") == "material"]
    by_id = {s.id: s for s in inlets}
    dosing = node.batch.dosing if node.batch is not None else []
    if lacking := [d.stream for d in dosing if d.stream not in by_id]:
        raise TankError(f"the dosed stream(s) {', '.join(lacking)} are no inlet of {node.id}")
    dosed = {d.stream for d in dosing}
    charges = [s for s in inlets if s.id not in dosed]
    if len(charges) != 1:
        raise TankError(
            f"a semibatch takes one charge stream besides its doses ({len(charges)} given)"
        )
    return charges[0], [(d, by_id[d.stream]) for d in dosing]


def solve_node(process: Any, node: Any, inlet: Any, case: str) -> tuple[TankResult, dict[str, Any]]:
    """:func:`_solve_node`, every problem a :class:`TankError` (a rate law, a liquid measure or
    an activity model may raise a plain ValueError), so that callers report it."""
    try:
        return _solve_node(process, node, inlet, case)
    except TankError:
        raise
    except ValueError as failure:
        raise TankError(str(failure)) from failure


def stream_moles(process: Any, stream: Any, case: str) -> tuple[dict[str, float], float, float]:
    """kmol/h by component, K and kPa(a) of *stream* in *case*. Raises TankError."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    state = stream.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    kelvin = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    kpa = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if kelvin is None or kpa is None:
        raise TankError(f"no inlet temperature and absolute pressure ({stream.id})")
    flows = stream_flows(process, stream, case)
    if flows.components is None:
        raise TankError(f"no composition and flow of {stream.id}: " + ", ".join(flows.missing))
    comps = process.components()
    lacking = sorted(n for n in flows.components if not getattr(comps.get(n), "molar_mass", None))
    if lacking:
        raise TankError("no molar_mass for " + ", ".join(lacking))
    return {n: kg / comps[n].molar_mass for n, kg in flows.components.items()}, kelvin, kpa


def _solve_node(
    process: Any, node: Any, inlet: Any, case: str
) -> tuple[TankResult, dict[str, Any]]:
    """The tank (``reactor: cstr``), batch (``reactor: batch``) or semi-batch (``reactor:
    semibatch``, *inlet* its inlet streams) *node* fed by stream *inlet* in *case*, and what it
    was solved from (the inputs of the outlet's fingerprint). Raises :class:`TankError` naming
    what is missing. One function for ``cheme process propagate`` and ``process reactors``."""
    from chemeascode.foundation.units import to_kelvin

    fs = process.flowsheet
    doses: list[Dose] = []
    if node.reactor == "semibatch":
        inlet, pairs = split_inlets(node, inlet if isinstance(inlet, list) else [inlet])
        for dosing, stream in pairs:
            moles, kelvin, _ = stream_moles(process, stream, case)
            share = 1.0 if dosing.absorbed is None else dosing.absorbed
            through = {n: v * (1.0 - share) for n, v in moles.items()} if share < 1 else {}
            if share < 1:
                moles = {n: v * share for n, v in moles.items()}
            doses.append(Dose(moles, kelvin, dosing.segments(), through))
    moles, kelvin, kpa = stream_moles(process, inlet, case)
    outlet_t = None
    vent = getattr(node.batch, "vent", None) if node.reactor != "cstr" else None
    for stream in fs.streams:
        ends = process.ends(stream)
        if vent is not None and stream.id == vent.stream:
            continue  # the liquid's outlet gives the batch's temperature, not the vent
        if ends and ends[0] is not None and ends[0].node == node.id:
            q = stream.state.get(case)
            given = getattr(q, "temperature", None)
            if given is not None and given.provenance != "calculated":
                outlet_t = to_kelvin(given.value, given.unit or fs.units.temperature)
    return solve_moles(process, node, moles, kelvin, kpa, outlet_t, doses)


def _deactivation(process: Any, node: Any) -> Any:
    """The deactivation law of *node*'s catalyst; TankError without one."""
    catalysts = process.catalysts.by_id() if process.catalysts else {}
    deactivation = getattr(catalysts.get(node.catalyst or ""), "deactivation", None)
    if deactivation is None or deactivation.law is None:
        raise TankError("time_on_stream needs the step's catalyst: with a deactivation law and kd")
    return deactivation


def tank_inputs(process: Any, node: Any, reactions: list[Any], names: list[str]) -> dict[str, Any]:
    """What a tank's or batch's solution depends on besides its inlet: the tank or batch, the
    reactions as solved, the ideal-gas data and molar masses, a liquid's volumes, heat
    capacities and activity inputs, an aged catalyst's law. One dict for the outlet's
    fingerprint (propagate) and the coupled unit's (simulate)."""
    from chemeascode.domains.process.liquid_phase import inputs_of

    kind = node.reactor
    spec = node.tank if kind == "cstr" else node.batch
    comps = process.components()
    data = process.ideal_gas()
    found: dict[str, Any] = {
        "batch" if kind == "semibatch" else kind: spec.model_dump(mode="json"),
        "reactions": [r.inputs_dump() for r in reactions],
        "ideal_gas": {n: data[n].model_dump(mode="json") if data.get(n) else None for n in names},
        "molar_mass": {n: getattr(comps.get(n), "molar_mass", None) for n in names},
    }
    if any(r.phase == "liquid" for r in reactions):
        bases = [k_basis(r) for r in reactions] + [r.rate.driving for r in reactions if r.rate]
        found |= inputs_of(process, names, bases)
        found["liquid_molar_volume"] = {
            n: getattr(comps.get(n), "liquid_molar_volume", None) for n in names
        }
        found["liquid_heat_capacity"] = {
            n: getattr(comps.get(n), "liquid_heat_capacity", None) for n in names
        }
    if kind == "cstr" and spec.time_on_stream:
        found["deactivation"] = _deactivation(process, node).model_dump(mode="json")
    return found


def solve_moles(
    process: Any,
    node: Any,
    moles: Mapping[str, float],
    kelvin: float,
    kpa: float,
    outlet_t: float | None = None,
    doses: Sequence[Dose] = (),
) -> tuple[TankResult, dict[str, Any]]:
    """The tank or batch *node* fed with *moles* (kmol/h) at *kelvin* K and *kpa* kPa(a), an
    isothermal one held at *outlet_t* where given, a semi-batch dosed with *doses*, and what it
    was solved from (its inputs besides the inlet). For ``cheme process propagate`` (through
    :func:`solve_node`) and the coupling to the DWSIM solve, which brings its own inlet. Raises
    ValueError (TankError)."""
    from chemeascode.domains.process.liquid_phase import liquid_of

    kind = node.reactor
    spec = node.tank if kind == "cstr" else node.batch
    if spec is None:
        raise TankError(f"reactor {kind} without {'tank' if kind == 'cstr' else 'batch'}:")
    if kind == "semibatch" and not doses:
        raise TankError("a semibatch without doses (batch.dosing: and their inlet streams)")
    if kind == "batch" and spec.dosing:
        raise TankError("a batch with dosing: set reactor: semibatch, or remove batch.dosing")
    if kind != "cstr" and spec.vent is None and any(d.passing for d in doses):
        raise TankError("a dose with absorbed below 1 passes gas through: give batch.vent")
    reactions, unknown = process.reactions_of(node.id)
    if unknown:
        raise TankError("undeclared reactions " + ", ".join(unknown))
    if not reactions:
        raise TankError("no reactions")
    comps = process.components()
    names = list(
        dict.fromkeys(
            [
                *moles,
                *(n for d in doses for n in d.moles),
                *(n for d in doses for n in d.passing),
                *(n for r in reactions for n in r.stoichiometry),
                *(spec.vent.components if getattr(spec, "vent", None) else ()),
            ]
        )
    )
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
    if lack := [n for n in names if not mw[n]]:
        raise TankError("no molar_mass for " + ", ".join(lack))
    data = process.ideal_gas()
    is_liquid = any(r.phase == "liquid" for r in reactions)
    liquid = liquid_of(process) if is_liquid else None
    capacity = {n: getattr(comps.get(n), "liquid_heat_capacity", None) for n in names}
    inputs = {"T_in": kelvin, "P_in": kpa, **tank_inputs(process, node, reactions, names)}
    inputs["T_out_given"] = outlet_t
    if doses:
        inputs["doses"] = [
            {"moles": dict(d.moles), "T": d.temperature, "segments": d.segments}
            | ({"passing": dict(d.passing)} if d.passing else {})
            for d in doses
        ]
    if kind == "cstr":
        activity = 1.0
        if spec.time_on_stream:
            activity = _deactivation(process, node).activity(spec.time_on_stream)
        result = solve_cstr(
            reactions, moles, kelvin, kpa, spec, data, liquid, capacity, outlet_t, activity
        )
        if activity != 1.0:
            result.notes.append(
                f"catalyst activity {activity:.4g} after {spec.time_on_stream:g} h on stream"
            )
    else:
        result = solve_batch(
            reactions, moles, kelvin, kpa, spec, data, liquid, capacity, outlet_t, doses
        )
    return result, inputs
