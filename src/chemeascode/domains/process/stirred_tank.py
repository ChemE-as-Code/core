"""Stirred tanks: the continuous stirred tank (``reactor: cstr``) and the batch
(``reactor: batch``), from the reactions' rate laws (:mod:`.chemistry.rates`).

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
    #: batch: kJ released per kmol of charge (positive: exothermic), and the largest rate of
    #: heat release per m3 of the batch (kW/m3)
    heat_released: float | None = None
    peak_heat_rate: float | None = None
    notes: list[str] = field(default_factory=list)
    #: kmol/h of extent of each reaction over the whole tank series or batch (per hour of
    #: charge): what a conversion reactor needs to give the same outlet
    extents: dict[str, float] = field(default_factory=dict)


@dataclass
class _Mixture:
    """How compositions become rates, volumes and enthalpies in one phase."""

    reactions: list[Any]
    names: list[str]
    data: Mapping[str, Any]
    liquid: Any  # a chemistry.liquid.Liquid, or None for a gas
    heat_capacity: Mapping[str, float | None]
    loading: float | None

    def nu(self) -> list[list[float]]:
        return [[r.stoichiometry.get(n, 0.0) for r in self.reactions] for n in self.names]

    def rates(self, moles: Sequence[float], t: float, p: float) -> list[float]:
        """kmol/(m3 s) or kmol/(kg s) per reaction at the composition *moles*."""
        total = sum(moles)
        # a trace instead of zero: an integrator's trial stage may empty a reactant, where a
        # (1 - Q/K) law is not defined; the trace gives a large reverse rate the step rejects
        x = {n: max(v / total, 1e-30) for n, v in zip(self.names, moles, strict=True)}
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
) -> TankResult:
    """The composition of the *charge* (kmol, or kmol/h of charge) at *temperature* K and
    *pressure* kPa after *batch* (a :class:`~.schema.Batch`): its ``time``, or its ``target``
    conversion. Raises TankError, also when the target is not reached (the batch stops
    converting first, at equilibrium or when a reactant is used up)."""
    names = list(dict.fromkeys([*charge, *(n for r in reactions for n in r.stoichiometry)]))
    mix = _mixture(reactions, names, data, liquid, heat_capacity or {}, batch.catalyst_loading)
    nu = mix.nu()
    m = len(reactions)
    n0 = [max(charge.get(n, 0.0), 0.0) for n in names]
    total0 = sum(n0)
    if total0 <= 0:
        raise TankError("the charge is empty")
    charged = [n for n in names if charge.get(n, 0.0) > 0]
    if batch.target is not None:
        key = batch.target.key
        if key not in names or charge.get(key, 0.0) <= 0:
            raise TankError(f"the target's key component {key} is not charged")
    else:  # the profile's conversion: of the first charged reactant, else of a charged one
        key = next(
            (n for n in charged if any(r.stoichiometry.get(n, 0) < 0 for r in reactions)),
            charged[0],
        )
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

    def volume_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is not None:
            return gas_volume
        return mix.volume_flow(dict(zip(names, moles, strict=True)), t, pressure)

    def pressure_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is None:
            return pressure
        return sum(moles) * R * t / gas_volume

    def derivatives(state: list[float]) -> list[float]:
        moles, t = state[:-2], state[-2]
        v = volume_of(moles, t)
        mult = mix.multipliers(v)
        rates = mix.rates(moles, t, pressure_of(moles, t))
        extent = [mult[j] * rates[j] for j in range(m)]
        dn = [sum(nu[i][j] * extent[j] for j in range(m)) for i in range(len(names))]
        dt = 0.0
        if adiabatic:
            cap = mix.capacity(dict(zip(names, moles, strict=True)), t)
            heats = energies(t)
            dt = sum(-h * e for h, e in zip(heats, extent, strict=True)) / cap
        return [*dn, dt, 0.0]

    def conversion(state: list[float]) -> float:
        return 1.0 - state[ki] / n0[ki]

    state = [*n0, temperature, pressure]
    t_end = batch.time
    target = batch.target.conversion if batch.target else None
    clock, h = 0.0, (t_end or 1.0) / 1000.0
    result = TankResult({}, temperature, pressure, "batch")
    result.profile.append((0.0, temperature, pressure, 0.0))
    heat = 0.0
    peak = 0.0
    try:
        energies(temperature)
        known = True
    except TankError:
        known = False
    stalled = 0
    while True:
        if t_end is not None:
            h = min(h, t_end - clock)
        new, error = _dopri_step(derivatives, state, h)
        scale = [
            max(abs(a), abs(b), 1e-9 * total0) for a, b in zip(state[:-2], new[:-2], strict=True)
        ] + [max(abs(state[-2]), 1.0), 1.0]
        err = max(abs(e) / s for e, s in zip(error, scale, strict=True))
        if err > 1e-7 and h > 1e-12:
            h *= max(0.2, 0.9 * (1e-7 / err) ** 0.2)
            continue
        if target is not None and conversion(new) >= target:
            # the target lies inside this step: bisect the step size
            lo, hi = 0.0, h
            for _ in range(60):
                mid = (lo + hi) / 2
                trial, _ = _dopri_step(derivatives, state, mid)
                if conversion(trial) >= target:
                    hi = mid
                else:
                    lo = mid
            new, _ = _dopri_step(derivatives, state, hi)
            h = hi
        new[:-2] = [max(v, 0.0) for v in new[:-2]]
        d_moles = [b - a for a, b in zip(state[:-2], new[:-2], strict=True)]
        if known:
            # the extents of this step from its change of moles, at the step's temperature
            released = _released(mix, nu, d_moles, energies(state[-2]))
            heat += released
            v = volume_of(new[:-2], new[-2])
            if h > 0 and v > 0:
                peak = max(peak, released / h / v)
        clock += h
        progress = abs(conversion(new) - conversion(state))
        state = new
        result.profile.append(
            (clock, state[-2], pressure_of(state[:-2], state[-2]), conversion(state))
        )
        if t_end is not None and clock >= t_end * (1 - 1e-12):
            break
        if target is not None and conversion(state) >= target - 1e-12:
            break
        stalled = stalled + 1 if progress < 1e-12 else 0
        if target is None and stalled > 50:
            result.notes.append(
                f"converts no further after {clock:.4g} s (equilibrium, or a reactant used up)"
            )
            clock = t_end  # type: ignore[assignment]
            break
        if stalled > 50 or clock > 1e9:
            raise TankError(
                f"the target conversion {target:g} of {key} is not reached: the batch stops at "
                f"{conversion(state):.4g} (equilibrium, or a reactant used up)"
            )
        h = min(h * 2, max(clock, h) * 10)
    result.outlet = dict(zip(names, state[:-2], strict=True))
    change = [b - a for a, b in zip(n0, state[:-2], strict=True)]
    gram = [
        [sum(nu[i][j] * nu[i][k] for i in range(len(names))) for k in range(m)] for j in range(m)
    ]
    fitted = _solve(gram, [sum(nu[i][j] * change[i] for i in range(len(names))) for j in range(m)])
    result.extents = {r.id: x for r, x in zip(reactions, fitted, strict=True)}
    # the outlet the extents give: the integrator clips a reactant at zero now and then, and a
    # conversion reactor (the DWSIM coupling) must reproduce the outlet from the extents
    result.outlet = {
        n: max(n0[i] + sum(nu[i][j] * fitted[j] for j in range(m)), 0.0)
        for i, n in enumerate(names)
    }
    result.temperature = state[-2]
    result.pressure = pressure_of(state[:-2], state[-2])
    result.time = clock
    result.volume = volume_of(n0, temperature)
    if known:
        result.heat_released = heat / total0
        result.peak_heat_rate = peak
    for r in reactions:
        hottest = max(p[1] for p in result.profile)
        if not r.rate.covers(hottest) or not r.rate.covers(temperature):
            result.notes.append(f"the batch leaves the rate's temperature range of {r.id}")
    if len(result.profile) > PROFILE_POINTS:
        step = len(result.profile) / PROFILE_POINTS
        kept = [result.profile[int(k * step)] for k in range(PROFILE_POINTS)]
        result.profile = [*kept, result.profile[-1]]
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


def solve_node(process: Any, node: Any, inlet: Any, case: str) -> tuple[TankResult, dict[str, Any]]:
    """:func:`_solve_node`, every problem a :class:`TankError` (a rate law, a liquid measure or
    an activity model may raise a plain ValueError), so that callers report it."""
    try:
        return _solve_node(process, node, inlet, case)
    except TankError:
        raise
    except ValueError as failure:
        raise TankError(str(failure)) from failure


def _solve_node(
    process: Any, node: Any, inlet: Any, case: str
) -> tuple[TankResult, dict[str, Any]]:
    """The tank (``reactor: cstr``) or batch (``reactor: batch``) *node* fed by stream *inlet*
    in *case*, and what it was solved from (the inputs of the outlet's fingerprint). Raises
    :class:`TankError` naming what is missing. One function for ``cheme process propagate`` and
    ``process reactors``."""
    from chemeascode.domains.process.model import stream_flows
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    fs = process.flowsheet
    state = inlet.state.get(case)
    t = getattr(state, "temperature", None)
    p = getattr(state, "pressure", None)
    kelvin = to_kelvin(t.value, t.unit or fs.units.temperature) if t is not None else None
    kpa = to_kpa_abs(p.value, p.unit or fs.units.pressure) if p is not None else None
    if kelvin is None or kpa is None:
        raise TankError(f"no inlet temperature and absolute pressure ({inlet.id})")
    flows = stream_flows(process, inlet, case)
    if flows.components is None:
        raise TankError(f"no composition and flow of {inlet.id}: " + ", ".join(flows.missing))
    comps = process.components()
    lacking = sorted(n for n in flows.components if not getattr(comps.get(n), "molar_mass", None))
    if lacking:
        raise TankError("no molar_mass for " + ", ".join(lacking))
    moles = {n: kg / comps[n].molar_mass for n, kg in flows.components.items()}
    outlet_t = None
    for stream in fs.streams:
        ends = process.ends(stream)
        if ends and ends[0] is not None and ends[0].node == node.id:
            q = stream.state.get(case)
            given = getattr(q, "temperature", None)
            if given is not None and given.provenance != "calculated":
                outlet_t = to_kelvin(given.value, given.unit or fs.units.temperature)
    return solve_moles(process, node, moles, kelvin, kpa, outlet_t)


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
        kind: spec.model_dump(mode="json"),
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
) -> tuple[TankResult, dict[str, Any]]:
    """The tank or batch *node* fed with *moles* (kmol/h) at *kelvin* K and *kpa* kPa(a), an
    isothermal one held at *outlet_t* where given, and what it was solved from (its inputs
    besides the inlet). For ``cheme process propagate`` (through :func:`solve_node`) and the
    coupling to the DWSIM solve, which brings its own inlet. Raises ValueError (TankError)."""
    from chemeascode.domains.process.liquid_phase import liquid_of

    kind = node.reactor
    spec = node.tank if kind == "cstr" else node.batch
    if spec is None:
        raise TankError(f"reactor {kind} without {'tank' if kind == 'cstr' else 'batch'}:")
    reactions, unknown = process.reactions_of(node.id)
    if unknown:
        raise TankError("undeclared reactions " + ", ".join(unknown))
    if not reactions:
        raise TankError("no reactions")
    comps = process.components()
    names = list(dict.fromkeys([*moles, *(n for r in reactions for n in r.stoichiometry)]))
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
    if lack := [n for n in names if not mw[n]]:
        raise TankError("no molar_mass for " + ", ".join(lack))
    data = process.ideal_gas()
    is_liquid = any(r.phase == "liquid" for r in reactions)
    liquid = liquid_of(process) if is_liquid else None
    capacity = {n: getattr(comps.get(n), "liquid_heat_capacity", None) for n in names}
    inputs = {"T_in": kelvin, "P_in": kpa, **tank_inputs(process, node, reactions, names)}
    inputs["T_out_given"] = outlet_t
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
        result = solve_batch(reactions, moles, kelvin, kpa, spec, data, liquid, capacity, outlet_t)
    return result, inputs
