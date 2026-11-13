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
remove (the reaction's heat and the doses' warming), per m3 of the final content. Each accepted
step records its cooling-failure rise per reaction and its content (``cooling_profile``), from
which the thermal screening takes its MTSR profile and the reactions that count (ADR 0058);
:func:`vent_gas_rate` gives a vented batch's gas rate at any content and temperature.

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
With ``vent.vapour`` the gas also carries the liquid's volatile components, saturated at the
vessel's temperature and pressure, past an optional partial ``vent.condenser``; ``vent.henry``
sets a gas's dissolved share from its solubility (ADR 0062, :mod:`.vent_vapour`).

A dose's ``heat_of_solution`` (ADR 0063) is released as it mixes in, at the dose's rate: in the
adiabatic balance, the peak cooling duty and the heat term ``solution``; it is not accumulated,
so the cooling-failure potentials leave it out. With ``batch.heat_up`` the charge's heat-up
from its inlet temperature to the batch's is the heat term ``charge heat-up``.

ADR 0074 (:mod:`.batch_kinetics`), each only where declared: an initiation holds its reactions
back until it initiates (and a semi-batch's uninitiated scenario runs it never initiating), a
temperature programme or reflux moves the temperature (the heat terms ``content`` and ``doses``
warmed to the temperature each met), a solid phase leaves the liquid's composition (a rate per
m2 of its shrinking particles, ``M_j = A_0 (n / n_0)^(2/3)``), and a photochemical rate law
takes the photons the liquid absorbs of the batch's light (its power the heat term ``light``).

Phases: every reaction of a tank is gas-phase or every one liquid-phase (:mod:`.chemistry.liquid`
gives a liquid's mole fractions, activities or concentrations). A gas's enthalpies are the
ideal-gas data's; a liquid's are ``heat_of_reaction`` plus ``liquid_heat_capacity`` (both needed
for an adiabatic liquid, and for a liquid's duty). Pure Python.
"""

from __future__ import annotations

import contextlib
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
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
    #: isothermal batch or semi-batch (ADR 0059): the heat into the content over the batch, kJ
    #: per hour of charge by term (``reaction``: minus the heat released; ``doses``: the doses
    #: warmed to the batch's temperature; ``vent gas``: a dosed gas passing through, warmed),
    #: None with ``heat_missing`` what it lacks
    heat_terms: dict[str, float] | None = None
    heat_missing: list[str] = field(default_factory=list)
    #: K of the charge as it enters (the batch may be held at another temperature: its
    #: heat-up, ``batch.heat_up``, ADR 0063)
    charge_temperature: float | None = None
    #: vented with ``vent.vapour`` (ADR 0062): kmol by component of the volatile components the
    #: gas carried off the liquid (per hour of charge), what of it a vent condenser condensed,
    #: the condenser's heat removed (kJ per hour of charge) by term or what it lacks, and the
    #: vapour's share of the gas over the liquid at the end (``Y``)
    vapour: dict[str, float] = field(default_factory=dict)
    condensate: dict[str, float] = field(default_factory=dict)
    condenser_heat: float | None = None
    condenser_terms: dict[str, float] = field(default_factory=dict)
    condenser_missing: list[str] = field(default_factory=list)
    vapour_share: float | None = None
    #: K the vent gas leaves at: the condenser's outlet, else the batch's end temperature
    vent_temperature: float | None = None
    #: vented with ``vent.henry`` (ADR 0062): component -> its solubility at the end and the
    #: share of what formed that left
    henry: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: vented with ``vent.head_space`` (ADR 0071): the vessel's volume and the head space's at
    #: the start and the end (m3 per hour of charge), its gas at the start and the end and what
    #: it expelled meanwhile (kmol by component), the gas it drew back
    head_space: dict[str, Any] = field(default_factory=dict)
    #: semi-batch, every accepted step (the thermal screening's MTSR profile, ADR 0058): the
    #: cooling-failure potential of each reaction then
    cooling_profile: list[CoolingPoint] = field(default_factory=list, repr=False)
    #: semi-batch: kmol (per hour of charge) of each dosed reactant charged and dosed, the
    #: liquid's share of a dosed gas (the denominator of its accumulation, ADR 0069)
    dosed_reactants: dict[str, float] = field(default_factory=dict, repr=False)
    #: ADR 0074, each only where declared: the initiation and the uninitiated scenario (the
    #: dosing going on into a charge that never initiates: its largest accumulation and worst
    #: cooling failure), the solid phase (kmol by component at the start and the end, a surface
    #: rate's solid's area m2 then), the light (kmol of photons and kJ absorbed, per hour of
    #: charge), the temperature programme or reflux (the temperature at the start and the end)
    initiation: dict[str, Any] = field(default_factory=dict)
    solids: dict[str, Any] = field(default_factory=dict)
    light: dict[str, Any] = field(default_factory=dict)
    temperatures: dict[str, Any] = field(default_factory=dict)
    #: kmol by component charged (the batch's basis): a surface rate's particles at the start
    charged: dict[str, float] = field(default_factory=dict, repr=False)


@dataclass
class CoolingPoint:
    """A moment of a semi-batch for a cooling failure, the dosing stopped (ADR 0058): its time
    s, temperature K and accumulation of the dosed reactant (None without one), the rise K each
    exothermic reaction gives run to completion of what is in the vessel then, over the
    content's heat capacity, and what is in the vessel (kmol by component, the batch's basis).
    ADR 0069: each reaction's heat of reaction then (kJ/kmol of extent, negative: exothermic)
    and the content's heat capacity (kJ/K), for the potential of a reaction network."""

    time: float
    temperature: float
    accumulation: float | None
    rises: dict[str, float]
    moles: dict[str, float]
    heats: dict[str, float] = field(default_factory=dict)
    capacity: float | None = None

    def mtsr(self, counted: Sequence[str] | None = None) -> float:
        """K: the temperature a cooling failure now reaches, the largest of the *counted*
        reactions (default: every one) run to completion."""
        picked = (
            self.rises.values() if counted is None else [self.rises.get(r, 0.0) for r in counted]
        )
        return self.temperature + max(picked, default=0.0)


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
    #: ADR 0074: the components carried as a solid phase, m3/kmol of each (M / density): out
    #: of the liquid's composition, in the content's volume
    solids: Mapping[str, float] = field(default_factory=dict)
    #: a surface rate's solid -> (m2 of its particles at the charge, kmol of it charged)
    surfaces: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    #: the light of photochemical rate laws: (kmol/s of photons into the content, kW of its
    #: radiant power, the :class:`~.schema.Light`), on the batch's basis
    light: tuple[float, float, Any] | None = None

    def nu(self) -> list[list[float]]:
        return [[r.stoichiometry.get(n, 0.0) for r in self.reactions] for n in self.names]

    def rates(self, moles: Sequence[float], t: float, p: float) -> list[float]:
        """kmol/(m3 s), kmol/(kg s) or kmol/(m2 s) per reaction at the composition *moles*."""
        solid = self.solids
        x = self.fractions(moles)
        photons = self.absorbed(moles, x)[0] if self.light is not None else None
        found = []
        for r in self.reactions:
            law = r.rate
            basis = k_basis(r)
            ln_k = reaction_ln_k(r, self.data, t, basis) if law.reverse == "equilibrium" else None
            stoich = r.stoichiometry
            if solid:  # a solid's activity is 1: no part of Q (ADR 0074)
                stoich = {n: v for n, v in stoich.items() if n not in solid}
            value = rate(law, stoich, x, t, p, ln_k, self.liquid, basis, photons)
            if solid and value:
                # a solid that is not there neither reacts nor dissolves
                held = dict(zip(self.names, moles, strict=True))
                side = [n for n, v in r.stoichiometry.items() if n in solid and v * value < 0]
                if any(held.get(n, 0.0) <= 0 for n in side):
                    value = 0.0
            found.append(value)
        return found

    def fractions(self, moles: Sequence[float]) -> dict[str, float]:
        """The liquid's mole fractions at *moles*: a vented gas (``gone``) and a solid phase
        (ADR 0074) at 0."""
        solid = self.solids
        if solid:  # a solid phase is no part of the liquid's composition (ADR 0074)
            total = sum(v for n, v in zip(self.names, moles, strict=True) if n not in solid)
        else:
            total = sum(moles)
        # a trace instead of zero: an integrator's trial stage may empty a reactant, where a
        # (1 - Q/K) law is not defined; the trace gives a large reverse rate the step rejects
        return {
            n: 0.0 if n in self.gone or n in solid else max(v / total, 1e-30)
            for n, v in zip(self.names, moles, strict=True)
        }

    def absorbed(
        self, moles: Sequence[float], x: Mapping[str, float] | None = None
    ) -> tuple[float, float, float]:
        """The light the content of *moles* (mole fractions *x* of its liquid) absorbs: kmol/(m3
        s) of photons per m3 of the content, the kW of radiant power and the kmol/s of photons
        (ADR 0074)."""
        from chemeascode.domains.process.batch_kinetics import absorbed_share

        if x is None:
            x = self.fractions(moles)
        flux, power, light = self.light  # type: ignore[misc]
        concentration = 0.0
        if light.absorber is not None:
            liquid = {n: v for n, v in x.items() if v > 0 and n not in self.gone}
            concentration = x.get(light.absorber, 0.0) / self.liquid.molar_volume(liquid)
        share = absorbed_share(light, concentration)
        volume = self.liquid_volume(moles)
        return (flux * share / volume if volume > 0 else 0.0), power * share, flux * share

    def liquid_volume(self, moles: Sequence[float]) -> float:
        """m3 of the liquid of *moles*: the content less a solid phase (ADR 0074)."""
        held = {n: v for n, v in zip(self.names, moles, strict=True) if n not in self.solids}
        return self.volume_flow(held, 0.0, 0.0)

    def multipliers(self, volume: float, moles: Sequence[float] | None = None) -> list[float]:
        """M_j: the volume (rate per m3), the catalyst mass (rate per kg) or the solid's surface
        at *moles* (rate per m2, ADR 0074) of each rate. With a solid phase a rate per m3 is
        per m3 of the liquid: the content's *volume* less the solid's."""
        if self.solids and moles is not None:
            volume = self.liquid_volume(moles)
        found = []
        for r in self.reactions:
            if r.rate.basis == "catalyst_mass":
                if self.loading is None:
                    raise TankError(
                        f"reaction {r.id}: a rate per kg of catalyst needs catalyst_loading"
                    )
                found.append(volume * self.loading)
            elif r.rate.basis == "surface":
                found.append(self.surface(r, moles))
            else:
                found.append(volume)
        return found

    def surface(self, reaction: Any, moles: Sequence[float] | None) -> float:
        """m2 of the surface of *reaction*'s solid at *moles*: its particles at the charge,
        shrinking at a constant number, ``A_0 (n / n_0)^(2/3)`` (ADR 0074)."""
        solid = reaction.rate.solid
        if solid not in self.surfaces or moles is None:
            raise TankError(
                f"reaction {reaction.id}: a rate per m2 of {solid}'s surface needs a liquid "
                f"batch or semi-batch that charges {solid} as a solid phase (batch.solids) with "
                "its particles' diameter or specific_area"
            )
        area, charged = self.surfaces[solid]
        held = max(moles[self.names.index(solid)], 0.0)
        return area * (held / charged) ** (2.0 / 3.0)

    def volume_flow(self, moles: Mapping[str, float], t: float, p: float) -> float:
        """m3/s of a flow of *moles* (kmol/s); a solid phase at its own density (ADR 0074)."""
        if self.liquid is not None and self.solids:
            solid = sum(max(v, 0.0) * self.solids[n] for n, v in moles.items() if n in self.solids)
            liquid = {n: v for n, v in moles.items() if n not in self.solids}
            total = sum(liquid.values())
            if total <= 0:
                return solid
            fractions = {n: v / total for n, v in liquid.items()}
            return total * self.liquid.molar_volume(fractions) + solid
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


def _solid_phase(
    mix: _Mixture,
    batch: Any,
    reactions: list[Any],
    charge: Mapping[str, float],
    doses: Sequence[Any],
    components: Mapping[str, Any],
) -> None:
    """*mix* with *batch*'s solid phase (``batch.solids``, ADR 0074): each solid's volume per
    kmol (``M / density``) and, for a rate law per m2 of its surface, its particles' area at the
    *charge*. Raises TankError: a surface rate without its solid charged as a phase with a
    size, a dosed one (the surface of a dosed solid needs the particles' population), a rate
    law on a solid phase's concentration, a gas batch."""
    solids = dict(getattr(batch, "solids", None) or {})
    surface = [r for r in reactions if r.rate is not None and r.rate.basis == "surface"]
    if lacking := sorted({r.rate.solid for r in surface} - set(solids)):
        raise TankError(
            "a rate per m2 of the surface of " + ", ".join(lacking) + ": give it in "
            "batch.solids (its density and its particles' diameter or specific_area)"
        )
    if not solids:
        return
    if mix.liquid is None:
        raise TankError("batch.solids: a solid phase in a liquid batch (liquid-phase reactions)")
    if lacking := sorted(n for n in solids if not getattr(components.get(n), "molar_mass", None)):
        raise TankError("batch.solids: no molar_mass for " + ", ".join(lacking))
    named = [
        r.id
        for r in reactions
        if r.rate is not None
        and (
            any(n in solids for n in r.rate.orders)
            or any(n in solids for a in r.rate.adsorption for n in a.exponents)
        )
    ]
    if named:
        raise TankError(
            "the rate law(s) of " + ", ".join(named) + " take a solid phase's concentration "
            "(an order in it): a solid is out of the liquid; give the rate per m2 of its surface "
            "(basis: surface, solid:)"
        )
    mix.solids = {n: components[n].molar_mass / spec.density for n, spec in solids.items()}
    surfaces: dict[str, tuple[float, float]] = {}
    for r in surface:
        name = r.rate.solid
        per_kg = solids[name].area()
        if per_kg is None:
            raise TankError(
                f"batch.solids.{name}: its particles' diameter or specific_area (reaction "
                f"{r.id}'s rate per m2 of its surface)"
            )
        charged = charge.get(name, 0.0)
        if charged <= 0:
            raise TankError(
                f"reaction {r.id}: a rate per m2 of {name}'s surface needs {name} charged "
                "(its particles at the start)"
            )
        if any(getattr(d, "moles", {}).get(name, 0.0) > 0 for d in doses):
            raise TankError(
                f"{name} is dosed: the surface of a dosed solid needs its particles' population "
                "(not modelled); charge it"
            )
        surfaces[name] = (per_kg * charged * components[name].molar_mass, charged)
    mix.surfaces = surfaces


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
    #: kJ the whole dose releases as it mixes into the liquid (its ``heat_of_solution``,
    #: ADR 0063; positive: exothermic), released at its rate; None: none declared
    solution: float | None = None
    #: kJ/kmol by component of its ``heat_of_solution`` (negative: exothermic); a component
    #: the vent's vapour takes off the liquid takes it back in (ADR 0063, ADR 0062)
    solution_by: Mapping[str, float] = field(default_factory=dict)
    #: it waits for the initiation (``after_initiation``, ADR 0074): its segments start then
    waits: bool = False

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
    vent_phase: Any = None,
    head_space: Mapping[str, float] | None = None,
    components: Mapping[str, Any] | None = None,
) -> TankResult:
    """:func:`_solve_batch`; with a ``vent.henry`` component the share of what forms that
    leaves is found by successive substitution over whole runs, so that the liquid at the end
    holds its solubility (:mod:`.vent_vapour`, ADR 0062). *vent_phase* is the vent's
    :class:`~.vent_vapour.VentPhase` (its vapour, condenser and Henry constants); *head_space*
    the inert gas (kmol by component, the charge's basis) that pads the vessel's head space
    (``vent.head_space``, ADR 0071); *components* the materials' components (a solid phase's
    molar mass, a reflux's vapour pressures, ADR 0074). A semi-batch with an initiation also
    runs its uninitiated scenario (:func:`_uninitiated`). Raises TankError."""
    from chemeascode.domains.process.vent_vapour import HENRY_RUNS, VentError

    vent = getattr(batch, "vent", None)
    henry = dict(getattr(vent, "henry", None) or {})
    args = (reactions, charge, temperature, pressure, batch, data, liquid, heat_capacity)
    pad = dict(head_space or {})
    doses = _inert_doses(set(getattr(vent, "inerts", None) or ()), charge, doses)
    shares: dict[str, float] | None = None
    try:
        if not henry:
            result = _solve_batch(*args, isothermal_at, doses, vent_phase, None, pad, components)
        else:
            shares = vent.shares()
            for _ in range(HENRY_RUNS):
                result = _solve_batch(
                    *args, isothermal_at, doses, vent_phase, shares, pad, components
                )
                if _henry_step(result, reactions, doses, henry, shares, vent_phase, pressure):
                    break
            else:
                result.notes.append(
                    f"vent: the Henry split did not converge in {HENRY_RUNS} runs of the batch"
                )
        if getattr(batch, "initiation", None) is not None:
            run = (*args, isothermal_at, doses, vent_phase, shares, pad, components)
            _uninitiated(result, batch, reactions, doses, run)
        return result
    except VentError as failure:
        raise TankError(str(failure)) from failure


def _uninitiated(
    result: TankResult, batch: Any, reactions: list[Any], doses: Sequence[Dose], run: tuple
) -> None:
    """The initiation of *batch* (ADR 0074) into *result*: its time, factor and reactions and,
    for a semi-batch, the uninitiated scenario: the run again with the initiation never coming,
    the doses that wait for it left out, until the initiation was due or the last other dose
    ends; its largest accumulation of the dosed reactant and its worst cooling failure (the
    content then reacting to completion adiabatically, the dosing stopped)."""
    start = batch.initiation
    held = start.reactions or [r.id for r in reactions]
    result.initiation = {
        "time_s": start.time,
        "factor": start.factor,
        "reactions": list(held),
        "doses_waiting": sum(1 for d in doses if d.waits),
    }
    if not doses:
        return
    kept = [d for d in doses if not d.waits]
    until = max([start.time, *(b for d in kept for _, b, _ in d.segments)])
    scenario: dict[str, Any] = {"until_s": until}
    try:
        found = _solve_batch(*run[:9], kept, *run[10:], uninitiated=True)
    except TankError as failure:
        scenario["missing"] = str(failure)
        result.initiation["uninitiated"] = scenario
        return
    worst = found.cooling_failure
    scenario |= {
        "max_accumulation": found.max_accumulation,
        "max_accumulation_time_s": found.max_accumulation_time,
        "cooling_failure": (
            {"time_s": worst[0], "temperature_K": worst[1], "mtsr_K": worst[2]} if worst else None
        ),
    }
    result.initiation["uninitiated"] = scenario


def _inert_doses(
    inerts: set[str], charge: Mapping[str, float], doses: Sequence[Dose]
) -> list[Dose]:
    """*doses* with what they bring of the vent's *inerts* passing straight through (ADR
    0071): an inert never dissolves. Raises TankError for an inert in the *charge*."""
    if not inerts:
        return list(doses)
    if charged := sorted(n for n in inerts if charge.get(n, 0.0) > 0):
        raise TankError(
            "the inert(s) " + ", ".join(charged) + " in the charge: an inert is no liquid; pad "
            "the head space with it (vent.head_space.stream)"
        )
    return [
        replace(
            d,
            moles={n: v for n, v in d.moles.items() if n not in inerts},
            passing={
                **d.passing,
                **{n: d.passing.get(n, 0.0) + v for n, v in d.moles.items() if n in inerts},
            },
        )
        if any(n in inerts and v > 0 for n, v in d.moles.items())
        else d
        for d in doses
    ]


def _henry_step(
    result: TankResult,
    reactions: list[Any],
    doses: Sequence[Dose],
    henry: Mapping[str, Any],
    shares: dict[str, float],
    phase: Any,
    pressure: float,
) -> bool:
    """One substitution of the Henry shares (in place in *shares*) from the run *result*:
    each component's share that leaves moved so that the liquid at the end holds its
    solubility ``x_g = y_g P / H_g(T)``; True when every one holds (or is bound at 0 or 1), and
    then ``result.henry`` reports them."""
    from chemeascode.domains.process.vent_vapour import HENRY_TOLERANCE

    t_end, p = result.temperature, pressure
    stoich = {r.id: r.stoichiometry for r in reactions}
    gross: dict[str, float] = {}  # kmol of each non-condensable formed or passed through
    for name in [*shares, *(n for d in doses for n in d.passing)]:
        formed = sum(
            max(stoich[r].get(name, 0.0) * x, 0.0) for r, x in result.extents.items() if r in stoich
        )
        gross[name] = formed + sum(d.passing.get(name, 0.0) for d in doses)
    total_gas = sum(gross.values())
    vapour = 0.0
    if phase is not None and phase.volatile:
        vapour = sum(phase.saturation(result.outlet, t_end, p).values())
    # with a head space (ADR 0071) the gas over the liquid at the end is the head space's
    over = result.head_space.get("end_kmol") if result.head_space else None
    over_total = sum(over.values()) if over else 0.0
    done = True
    report: dict[str, dict[str, Any]] = {}
    for g, constant in henry.items():
        formed = gross.get(g, 0.0) - sum(d.passing.get(g, 0.0) for d in doses)
        h, extrapolated = constant.kpa(t_end)
        if over is not None:
            y = (1.0 - vapour) * (over.get(g, 0.0) / over_total if over_total > 0 else 0.0)
        else:
            y = (1.0 - vapour) * (gross.get(g, 0.0) / total_gas if total_gas > 0 else 1.0)
        x = min(y * p / h, 1.0)
        others = sum(v for n, v in result.outlet.items() if n != g and v > 0)
        soluble = x / (1.0 - x) * others if x < 1.0 else math.inf
        kept = result.outlet.get(g, 0.0)
        share = shares[g]
        state = "saturated"
        if formed <= 0:
            state = "nothing formed"
        else:
            residual = kept - soluble
            new = min(max(share + residual / formed, 0.0), 1.0)
            off = abs(residual) > HENRY_TOLERANCE * formed + 1e-15
            if off and new != share:
                done = False
            elif off and residual > 0:
                state = "above its solubility (charged or dosed; the vent takes only what forms)"
            elif off:
                state = "below its solubility: all that formed stays dissolved"
            shares[g] = new
        report[g] = {
            "henry_kPa": h,
            "extrapolated": extrapolated,
            "partial_pressure_kPa": y * p,
            "solubility_mole_fraction": x,
            "dissolved_kmol_h": kept,
            "formed_kmol_h": max(formed, 0.0),
            "share_vented": share,
            "state": state,
        }
    if done:
        result.henry = report
        for g, entry in report.items():
            if entry["extrapolated"]:
                result.notes.append(f"vent: the Henry constant of {g} is extrapolated")
            if entry["state"] not in ("saturated", "nothing formed"):
                result.notes.append(f"vent: {g} {entry['state']}")
    return done


def _solve_batch(
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
    vent_phase: Any = None,
    vent_shares: Mapping[str, float] | None = None,
    head_space: Mapping[str, float] | None = None,
    components: Mapping[str, Any] | None = None,
    uninitiated: bool = False,
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
    docstring); the result's ``vent`` is what left, ``outlet`` the liquid. A vent's inerts
    pass through (ADR 0071); *head_space* (kmol of inert by component) pads its head space.

    ADR 0074 (:mod:`.batch_kinetics`): ``batch.initiation`` holds its reactions back until it
    initiates (*uninitiated*: for good, the run ending when the initiation was due or the last
    dose ends), ``batch.program`` or ``heat: reflux`` move the temperature, ``batch.solids``
    carries a solid phase (a surface rate law on its shrinking particles), ``batch.light``
    drives the photochemical rate laws; the run is split where these change."""
    from chemeascode.domains.process import batch_kinetics

    doses = list(doses)
    vent = getattr(batch, "vent", None)
    shares = vent.shares() if vent is not None else {}
    if vent_shares is not None:
        shares = {n: vent_shares.get(n, f) for n, f in shares.items()}
    inerts = set(getattr(vent, "inerts", None) or ()) if vent is not None else set()
    doses = _inert_doses(inerts, charge, doses)
    pad = {n: v for n, v in (head_space or {}).items() if v > 0}
    if pad and getattr(vent, "head_space", None) is None:
        raise TankError("a head space's gas without vent.head_space")
    if stray := sorted(set(pad) - inerts):
        raise TankError(
            "the head space holds only the vent's inerts: " + ", ".join(stray) + " is none"
        )
    absorption = getattr(getattr(vent, "heat_of_absorption", None), "values", None) or {}
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
    _solid_phase(mix, batch, reactions, charge, doses, components or {})
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
    mix.gone = (
        frozenset(
            names[i] for i, f in zip(vented, vent_share, strict=True) if f >= 1.0 and not n0[i]
        )
        - {n for i, n in enumerate(names) if dosed[i] > 0}
    ) | (inerts & set(names))  # an inert never dissolves (ADR 0071)
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
    charge_temperature = temperature
    if batch.heat == "isothermal" and isothermal_at:
        temperature = isothermal_at  # the batch is held at its given temperature
    program = getattr(batch, "program", None)
    reflux = batch.heat == "reflux"
    if program is not None:  # ADR 0074: the programme sets the temperature
        if isothermal_at is not None and abs(isothermal_at - program.points[-1][1]) > 1e-6:
            raise TankError(
                f"the outlet's given temperature {isothermal_at:.6g} K is not the end of "
                f"batch.program, {program.points[-1][1]:.6g} K"
            )
        temperature = program.points[0][1]
    if reflux:
        if mix.liquid is None:
            raise TankError("heat: reflux: a liquid batch (liquid-phase reactions)")
        if isothermal_at is not None:
            raise TankError(
                f"heat: reflux follows the content's bubble point: the outlet's given "
                f"temperature {isothermal_at:.6g} K is not the model's (leave it to propagate)"
            )
        if vent is not None and (vent.vapour is not None or vent.head_space is not None):
            raise TankError(
                "heat: reflux with vent.vapour or vent.head_space: the gas over a boiling liquid "
                "is its vapour, which the total reflux returns (not modelled; leave them out)"
            )
        activity = dict(getattr(getattr(vent, "vapour", None), "activity", None) or {})

        def boiling(moles: Sequence[float]) -> float:
            """K: the bubble point of the liquid of *moles* at the vessel's pressure."""
            held = {
                names[i]: moles[i]
                for i in range(size)
                if names[i] not in mix.gone and names[i] not in mix.solids
            }
            found, lacking = batch_kinetics.bubble_point(held, components or {}, pressure, activity)
            if lacking:
                raise TankError(
                    "heat: reflux: no vapour_pressure (or heat_of_vaporization with the "
                    "normal_boiling_point) of " + ", ".join(lacking)
                )
            if found is None:
                raise TankError(f"heat: reflux: the liquid does not boil at {pressure:.6g} kPa")
            return found

        temperature = boiling(n0)
    gas_volume = None if mix.liquid is not None else total0 * R * temperature / pressure
    adiabatic = batch.heat == "adiabatic"
    light = getattr(batch, "light", None)
    photochemical = [r.id for r in reactions if r.rate.form == "photochemical"]
    if photochemical and light is None:
        raise TankError(
            "the photochemical rate law(s) of " + ", ".join(photochemical) + " need "
            "batch.light (the lamp's power and wavelength, the absorber)"
        )
    if light is not None:
        if mix.liquid is None:
            raise TankError("batch.light: a liquid batch or semi-batch")
        if light.absorber is not None and light.absorber not in names:
            raise TankError(f"batch.light.absorber {light.absorber} is not in the batch")
        watts = light.power * mix.volume_flow(dict(zip(names, n0, strict=True)), 0.0, 0.0)
        mix.light = (batch_kinetics.photon_flux(watts, light.wavelength), watts / 1000.0, light)
    # ADR 0074: the content's temperature moves (a programme, reflux) or a lamp heats it
    varying = program is not None or reflux or light is not None
    extra_breaks = batch_kinetics.breaks(batch)

    def regime_of(a: float, b: float | None) -> batch_kinetics.Regime:
        return batch_kinetics.regime(batch, reactions, a, b, uninitiated)

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
    # the vent's vapour (ADR 0062, :mod:`.vent_vapour`): the volatile components the gas carries
    # off the liquid, a condenser on it; their running totals follow the vent's in the state
    from chemeascode.domains.process.vent_vapour import condense

    phase = vent_phase if vent is not None and vent_phase is not None else None
    asked = list(phase.volatile) if phase is not None else []
    volatile = [names.index(n) for n in asked if n in names and n not in mix.gone]
    nv = len(volatile)
    condensing = nv > 0 and phase.condenser is not None
    returns = condensing and phase.returns
    tc = phase.condenser if condensing else None
    k_condenser = phase.condenser_k(pressure) if condensing else {}
    gas_names = list(dict.fromkeys([*shares, *passing, *pad]))  # the non-condensables
    base = size + len(vented)  # the vapour's totals: carried off, past the condenser, heats
    degassing = set(getattr(phase, "degassing", None) or ()) if nv else set()
    # the condenser condenses the condensables; a degassing gas passes it (ADR 0071)
    cond_k = [k for k, i in enumerate(volatile) if names[i] not in degassing]
    # ADR 0071: the head space's gas (each non-condensable held, and what left by the vent)
    # and the heat of absorption released, after the vapour's totals in the state
    ng = len(gas_names) if pad else 0
    head_at = base + (nv * (2 if condensing else 1) + 2 if nv else 0)
    absorb = [absorption.get(names[i], 0.0) for i in vented]
    absorbing = any(absorb)
    absorb_at = head_at + 2 * ng
    molar_volume = (
        [mix.solids.get(n) or (mix.liquid.molar_volumes.get(n) or 0.0) for n in names]
        if mix.liquid is not None
        else []
    )
    dhvap = [phase.heat_of_vaporization.get(names[i]) or 0.0 for i in volatile] if nv else []
    cp_vap = [phase.liquid_heat_capacity.get(names[i]) or 0.0 for i in volatile] if nv else []
    # kJ/kmol each volatile component takes in as it leaves the solution again (ADR 0063): minus
    # its doses' heat of solution, the mean over all of it that enters the liquid (the charged
    # share released none), so only what the doses brought in gives back its heat
    demix = []
    for i in volatile:
        entered = n0[i] + dosed[i]
        bound = sum(
            a[i] * d.solution_by.get(names[i], 0.0) for d, a in zip(doses, dose_moles, strict=True)
        )
        demix.append(-bound / entered if entered > 0 else 0.0)

    def vapour_rates(
        moles: Sequence[float], t: float, gas_flows: Mapping[str, float]
    ) -> tuple[list[float], list[float], float, float]:
        """kmol/s of each volatile component the gas (*gas_flows*, kmol/s of each
        non-condensable) carries off the liquid at *moles* and *t* K, of it what passes the
        condenser, the kW into the content for it (the latent heat; a returned condensate
        warmed back) and the kW the condenser removes."""
        zero = [0.0] * nv
        gas_now = sum(gas_flows.values())
        if not nv or gas_now <= 0:
            return zero, zero, 0.0, 0.0
        held = {
            names[i]: moles[i]
            for i in range(size)
            if names[i] not in mix.gone and names[i] not in mix.solids
        }
        carry = phase.carried(held, t, pressure)
        s = [gas_now * carry[names[i]] for i in volatile]
        qv = sum(a * h for a, h in zip(s, dhvap, strict=True))
        if not condensing:
            return s, s, qv + sum(a * h for a, h in zip(s, demix, strict=True)), 0.0
        if degassing:  # a degassing gas passes the condenser as a gas (ADR 0071)
            inert = gas_now + sum(a for k, a in enumerate(s) if k not in cond_k)
            through = condense(inert, {names[volatile[k]]: s[k] for k in cond_k}, k_condenser)
            v = [through.get(names[i], a) for i, a in zip(volatile, s, strict=True)]
        else:
            through = condense(
                gas_now, {names[i]: a for i, a in zip(volatile, s, strict=True)}, k_condenser
            )
            v = [through[names[i]] for i in volatile]
        c = [a - b for a, b in zip(s, v, strict=True)]
        warm = sum(a * cp * (t - tc) for a, cp in zip(c, cp_vap, strict=True))
        if returns:
            qv += warm
        # what leaves the liquid for good takes its heat of solution back (ADR 0063)
        qv += sum(a * h for a, h in zip(v if returns else s, demix, strict=True))
        qc = sum(a * h for a, h in zip(c, dhvap, strict=True))
        if degassing:  # a degassing gas is cooled as a gas, with the non-condensables
            qc += sum(s[k] * cp_vap[k] * (t - tc) for k in cond_k)
            flows = dict(gas_flows)
            for k, i in enumerate(volatile):
                if k not in cond_k:
                    flows[names[i]] = flows.get(names[i], 0.0) + s[k]
        else:
            qc += sum(a * cp * (t - tc) for a, cp in zip(s, cp_vap, strict=True))
            flows = gas_flows
        qc += sum(
            f * (phase.gas[n].enthalpy(t) - phase.gas[n].enthalpy(tc))
            for n, f in flows.items()
            if f > 0 and phase.gas.get(n) is not None
        )
        return s, v, qv, qc

    def lost(state: Sequence[float]) -> list[float]:
        """kmol of each volatile component the liquid has lost by *state*: what passed the
        condenser when its condensate returns, else what the gas carried off."""
        at = base + nv if returns else base
        return list(state[at : at + nv])

    def gas_flows_of(leaving: Sequence[float]) -> dict[str, float]:
        """kmol/s of each non-condensable now: the vent's components as they form (*leaving*)
        and the dosed gas passing through."""
        found = {names[i]: f for i, f in zip(vented, leaving, strict=True)}
        for n, f in passing_by.items():
            found[n] = found.get(n, 0.0) + f
        return found

    def volume_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is not None:
            return gas_volume
        return mix.volume_flow(dict(zip(names, moles, strict=True)), t, pressure)

    def head_room(moles: Sequence[float], t: float, clock: float | None = None) -> float:
        """m3 of the head space (ADR 0071): the vessel's volume less the liquid's."""
        room = vessel - volume_of(moles, t)
        if room <= 0:
            when = f" at {clock:.6g} s" if clock is not None else ""
            raise TankError(
                f"the liquid fills the vessel{when}: its head space's pad (vent.head_space."
                "stream) is too small for what the batch holds; give the vessel's empty volume "
                "at the start as the pad gas"
            )
        return room

    def head_rate(moles: Sequence[float], t: float, dn: Sequence[float], dt: float) -> float:
        """kmol/s: the rate of change of the non-condensables the head space holds, ``H = (1 -
        Y) P (V_vessel - V) / (R T)``, along a change *dn* (kmol/s) and *dt* (K/s) of the
        content (ADR 0071): the liquid's volume grows into it, the vapour's share ``Y`` rises,
        or it warms."""
        room = head_room(moles, t)
        dv = sum(v * d for v, d in zip(molar_volume, dn, strict=False))
        y = dy = 0.0
        if nv:
            liquid = [i for i in range(size) if names[i] not in mix.gone | set(mix.solids)]
            total = sum(max(moles[i], 0.0) for i in liquid)
            d_total = sum(dn[i] for i in liquid)
            k = phase.k_values(t, pressure)
            if total > 0:
                for i in volatile:
                    x = max(moles[i], 0.0) / total
                    y += k[names[i]] * x
                    dy += k[names[i]] * (dn[i] - x * d_total) / total
                if dt:
                    up, down = (
                        phase.k_values(t + 1e-3, pressure),
                        phase.k_values(t - 1e-3, pressure),
                    )
                    dy += dt * sum(
                        max(moles[i], 0.0) / total * (up[names[i]] - down[names[i]]) / 2e-3
                        for i in volatile
                    )
        held = (1.0 - y) * pressure * room / (R * t)
        return pressure / (R * t) * (-(1.0 - y) * dv - room * dy) - held / t * dt

    def pressure_of(moles: Sequence[float], t: float) -> float:
        if gas_volume is None:
            return pressure
        return sum(moles) * R * t / gas_volume

    def feeding(t: float) -> tuple[list[float], list[tuple[float, float]], float]:
        """kmol/s by component dosed at time *t*, (kW/K, K) of each dose then: its heat
        capacity flow and temperature (of a dosed gas passing through to the vent too), and the
        kW the doses release as they mix in (their heat of solution, ADR 0063)."""
        found = [0.0] * len(names)
        sensible = []
        mixing = 0.0
        for d, amounts, cap, gas in zip(
            doses, dose_moles, dose_capacity, passing_capacity, strict=True
        ):
            if (share := d.rate(t)) > 0:
                found = [a + share * v for a, v in zip(found, amounts, strict=True)]
                if cap is not None:
                    sensible.append((share * cap, d.temperature))
                if gas is not None:
                    sensible.append((share * gas, d.temperature))
                mixing += share * (d.solution or 0.0)
        return found, sensible, mixing

    def passing_rate(t: float) -> float:
        """kmol/s of dosed gas passing through to the vent at time *t*."""
        return sum(d.rate(t) * sum(d.passing.values()) for d in doses)

    def passing_of(t: float) -> dict[str, float]:
        """kmol/s of each component of the dosed gas passing through at time *t*."""
        found: dict[str, float] = {}
        for d in doses:
            for n, v in d.passing.items():
                if (f := d.rate(t) * v) > 0:
                    found[n] = found.get(n, 0.0) + f
        return found

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

    def potentials(moles: Sequence[float], t: float) -> tuple[list[float], list[float], float]:
        """K of each reaction: the rise if cooling fails now and the dosing stops, its heat
        run to completion of what is in the vessel, over the content's heat capacity (0 for
        an endothermic one); the largest is the cooling-failure potential. With the heats of
        reaction (kJ/kmol) and the content's heat capacity (kJ/K) they come from."""
        heats = energies(t)
        capacity = mix.capacity(dict(zip(names, moles, strict=True)), t)
        found = []
        for j in range(m):
            if heats[j] < 0:
                extent = min(moles[i] / -nu[i][j] for i in range(len(names)) if nu[i][j] < 0)
                found.append(-heats[j] * extent / capacity)
            else:
                found.append(0.0)
        return found, heats, capacity

    unknown_heat = ""
    try:
        energies(temperature)
        known = True
    except TankError as failure:
        known = False
        unknown_heat = str(failure)
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

    def make_derivatives(
        source: list[float],
        sensible: list[tuple[float, float]],
        mixing: float = 0.0,
        regime: batch_kinetics.Regime = batch_kinetics.PLAIN,
    ) -> Callable[[list[float]], list[float]]:
        """The state's derivatives, *source* kmol/s dosed and *mixing* kW released as it mixes
        in (a heat of solution), in the ADR 0074 *regime* (the reactions' factors, the lamp,
        the programme's slope)."""

        def derivatives(state: list[float]) -> list[float]:
            moles, t = state[:size], state[-2]
            if reflux:
                t = boiling(moles)
            v = volume_of(moles, t)
            mult = mix.multipliers(v, moles)
            rates = mix.rates(moles, t, pressure_of(moles, t))
            extent = [mult[j] * rates[j] for j in range(m)]
            if regime.factors is not None:
                extent = [e * f for e, f in zip(extent, regime.factors, strict=True)]
            dn = [
                sum(nu[i][j] * extent[j] for j in range(m)) + source[i] for i in range(len(names))
            ]
            leaving = []  # kmol/s of each vented component leaving as it forms
            dissolving = 0.0  # kW its dissolved share releases (a heat of absorption, ADR 0071)
            for i, f, h_abs in zip(vented, vent_share, absorb, strict=True):
                # a share of what the reactions form (each reaction's own), not of the net:
                # what another reaction consumes it takes from the liquid, never back from
                # the gas that has left
                formed = sum(max(nu[i][j] * extent[j], 0.0) for j in range(m))
                out = f * formed
                dn[i] -= out
                leaving.append(out)
                if h_abs:
                    dissolving -= (1.0 - f) * formed * h_abs
            cap = gain = 0.0
            if adiabatic:
                cap = mix.capacity(dict(zip(names, moles, strict=True)), t)
                heats = energies(t)
                gain = sum(-h * e for h, e in zip(heats, extent, strict=True))
                gain += sum(c * (t_dose - t) for c, t_dose in sensible) + mixing
                gain += dissolving
                if mix.light is not None and regime.lit:  # the light it absorbs (ADR 0074)
                    gain += mix.absorbed(moles)[1]
            extra: list[float] = []
            head: list[float] = []
            qv = 0.0
            if ng:
                head, qv, extra = head_space_rates(state, dn, leaving, gain, cap)
            elif nv:
                s, v, qv, qc = vapour_rates(moles, t, gas_flows_of(leaving))
                for k, i in enumerate(volatile):
                    dn[i] -= v[k] if returns else s[k]
                extra = [*s, *(v if condensing else ()), qv, qc]
            dt = regime.slope  # a temperature programme's (ADR 0074)
            if adiabatic:
                # the vapour the gas carries off cools the content (ADR 0062)
                dt = (gain - qv) / cap
            return [*dn, *leaving, *extra, *head, *([dissolving] if absorbing else ()), dt, 0.0]

        return derivatives

    def head_space_rates(
        state: list[float], dn: list[float], leaving: list[float], gain: float, cap: float
    ) -> tuple[list[float], float, list[float]]:
        """ADR 0071: the head space's gas, of the non-condensables formed and passing through
        into it, expels ``F = In - dH/dt`` of its own composition, which carries the vapour;
        ``dH/dt`` depends on the vapour the gas takes off the liquid (``F`` times it per kmol),
        linearly, so ``F = (In - D_a) / (1 + D_b)``. A head space that expands (``F`` below 0)
        draws back the gas of the vent line, without vapour. *dn* (the liquid's change) takes
        the vapour off in place; returns the head space's and the vent's rates, the vapour's
        kW into the content and the vapour's rates."""
        moles, t = state[:size], state[-2]
        inflow = gas_flows_of(leaving)
        held = state[head_at : head_at + ng]
        total = sum(max(x, 0.0) for x in held)
        if total > 0:
            comp = [max(x, 0.0) / total for x in held]
        else:
            entering = sum(inflow.values())
            comp = [inflow.get(g, 0.0) / entering if entering > 0 else 1.0 / ng for g in gas_names]
        zero = [0.0] * nv
        s1, v1, q1, c1 = zero, zero, 0.0, 0.0
        if nv:
            s1, v1, q1, c1 = vapour_rates(moles, t, dict(zip(gas_names, comp, strict=True)))
        loss = v1 if returns else s1
        dn_b = [0.0] * size
        for k, i in enumerate(volatile):
            dn_b[i] = -loss[k]
        d_a = head_rate(moles, t, dn, gain / cap if adiabatic else 0.0)
        d_b = head_rate(moles, t, dn_b, -q1 / cap if adiabatic else 0.0)
        entering = sum(inflow.values())
        flow = (entering - d_a) / (1.0 + d_b)
        scale = 0.0
        if flow > 0:
            scale = flow
        else:
            flow = entering - d_a  # drawn back from the vent line: no vapour leaves
        out = [flow * c for c in comp]
        s = [scale * a for a in s1]
        v = [scale * a for a in v1]
        for k, i in enumerate(volatile):
            dn[i] -= v[k] if returns else s[k]
        extra = [*s, *(v if condensing else ()), scale * q1, scale * c1] if nv else []
        rates = [inflow.get(g, 0.0) - o for g, o in zip(gas_names, out, strict=True)]
        return [*rates, *out], scale * q1, extra

    active: list[Callable[[list[float]], list[float]]] = []  # the derivatives now
    current = [batch_kinetics.PLAIN]  # the ADR 0074 regime now
    # ADR 0074, with a moving temperature or a lamp: the heat into the content over the batch,
    # kJ by term (the content's sensible heat, the doses warmed to the temperature they met,
    # minus the light absorbed), the photons absorbed (kmol), and what lacks a heat capacity
    moving = {"content": 0.0, "doses": 0.0, "light": 0.0, "photons": 0.0}
    moving_missing: list[str] = []

    def account(
        state: Sequence[float],
        new: Sequence[float],
        h: float,
        sensible: Sequence[tuple[float, float]],
        regime: batch_kinetics.Regime,
    ) -> None:
        """One accepted step of *h* s from *state* to *new* into :data:`moving` (trapezoids)."""
        t0, t1 = state[-2], new[-2]
        if t1 != t0:
            try:
                c0 = mix.capacity(dict(zip(names, state[:size], strict=True)), t0)
                c1 = mix.capacity(dict(zip(names, new[:size], strict=True)), t1)
                moving["content"] += 0.5 * (c0 + c1) * (t1 - t0)
            except TankError as failure:
                if str(failure) not in moving_missing:
                    moving_missing.append(str(failure))
        moving["doses"] += sum(c * (0.5 * (t0 + t1) - t_d) * h for c, t_d in sensible)
        if mix.light is not None and regime.lit:
            a, b = mix.absorbed(state[:size]), mix.absorbed(new[:size])
            moving["light"] += 0.5 * (a[1] + b[1]) * h
            moving["photons"] += 0.5 * (a[2] + b[2]) * h

    def run(
        state: list[float],
        clock: float,
        t_end: float | None,
        target: float | None,
        source: list[float],
        sensible: list[tuple[float, float]],
        post: bool,
        mixing: float = 0.0,
        regime: batch_kinetics.Regime = batch_kinetics.PLAIN,
    ) -> tuple[list[float], float]:
        """From *state* at *clock* s to *t_end* s or the *target* conversion, *source* kmol/s
        dosed meanwhile and *mixing* kW released as it mixes in (a heat of solution), in the
        ADR 0074 *regime*; the accepted steps go into the result."""
        nonlocal heat, peak, cooling, stalled

        derivatives = make_derivatives(source, sensible, mixing, regime)
        active[:] = [derivatives]
        current[:] = [regime]

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
            if reflux:  # the content at its bubble point (ADR 0074)
                new[-2] = boiling(new[:size])
            # what reacted in this step: the change of moles less what was dosed, and what left
            d_moles = [
                b - a - s * h for a, b, s in zip(state[:size], new[:size], source, strict=True)
            ]
            for k, i in enumerate(vented):
                d_moles[i] += new[size + k] - state[size + k]
            for k, (a, b) in enumerate(zip(lost(state), lost(new), strict=True)):
                d_moles[volatile[k]] += b - a  # what the gas carried off is not a reaction's
            if known:
                # the extents of this step from its change of moles, at the step's temperature
                released = _released(mix, nu, d_moles, energies(state[-2]))
                heat += released
                v = volume_of(new[:size], new[-2])
                if h > 0 and v > 0:
                    peak = max(peak, released / h / v)
                if doses and h > 0 and not adiabatic:
                    # kW to remove: the reaction's heat, the doses' warming to the batch and
                    # their heat of solution as they mix in (ADR 0063), a formed gas's heat of
                    # absorption (ADR 0071)
                    warming = sum(c * (t_dose - new[-2]) for c, t_dose in sensible)
                    if absorbing:
                        warming += (new[absorb_at] - state[absorb_at]) / h
                    if varying:  # the content's warming and the light it absorbs (ADR 0074)
                        warming += _kinetic_rate(mix, names, state, new, h, regime)
                    cooling = max(cooling, released / h + warming + mixing)
            if varying:
                account(state, new, h, sensible, regime)
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
        dosed gas passing through now; with a head space what it expels (ADR 0071)."""
        if ng:
            rates = active[0](state)
            out = sum(rates[head_at + ng : head_at + 2 * ng])
            at = base + nv if condensing else base
            return max(out, 0.0) + (sum(rates[at : at + nv]) if nv else 0.0)
        moles, t = state[:size], state[-2]
        mult = mix.multipliers(volume_of(moles, t), moles)
        rates = mix.rates(moles, t, pressure_of(moles, t))
        extent = [mult[j] * rates[j] for j in range(m)]
        if (factors := current[0].factors) is not None:  # ADR 0074
            extent = [e * f for e, f in zip(extent, factors, strict=True)]
        leaving = [
            f * sum(max(nu[i][j] * extent[j], 0.0) for j in range(m))
            for i, f in zip(vented, vent_share, strict=True)
        ]
        _, past, _, _ = vapour_rates(moles, t, gas_flows_of(leaving)) if nv else ([], [], 0, 0)
        return sum(leaving) + passing_now + sum(past)

    def record(state: list[float], clock: float) -> None:
        nonlocal peak_vent, peak_vent_time
        moles, t = state[:size], state[-2]
        result.profile.append((clock, t, pressure_of(moles, t), conversion(state, clock)))
        if vent is not None and (rate_now := vent_rate(state)) > peak_vent:
            peak_vent, peak_vent_time = rate_now, clock
        if not doses:
            return
        accumulated = None
        if reagent is not None and reagent_total > 0:
            accumulated = moles[names.index(reagent)] / reagent_total
            result.accumulation.append((clock, accumulated))
        if worst_known:
            try:
                rises, heats, capacity = potentials(moles, t)
            except TankError:
                return  # no heat capacity of what is there: no value at this step
            reached = t + max(rises, default=0.0)
            if not worst or reached > worst[2]:
                worst[:] = [clock, t, reached]
            result.cooling_profile.append(
                CoolingPoint(
                    clock,
                    t,
                    accumulated,
                    {r.id: x for r, x in zip(reactions, rises, strict=True)},
                    dict(zip(names, moles, strict=True)),
                    {r.id: h for r, h in zip(reactions, heats, strict=True)},
                    capacity,
                )
            )

    totals = len(vented) + (nv * (2 if condensing else 1) + 2 if nv else 0)
    totals += 2 * ng + (1 if absorbing else 0)
    state = [*n0, *(0.0 for _ in range(totals)), temperature, pressure]
    vessel = 0.0
    room0 = 0.0
    if ng:
        # the vessel: the charge's volume and the head space its pad fills, saturated (ADR 0071)
        held0 = {
            names[i]: n0[i]
            for i in range(size)
            if names[i] not in mix.gone and names[i] not in mix.solids
        }
        y0 = sum(phase.saturation(held0, temperature, pressure).values()) if nv else 0.0
        room0 = sum(pad.values()) * R * temperature / ((1.0 - y0) * pressure)
        vessel = volume_of(n0, temperature) + room0
        for k, g in enumerate(gas_names):
            state[head_at + k] = pad.get(g, 0.0)
    result = TankResult({}, temperature, pressure, "semibatch" if doses else "batch")
    heat = 0.0
    peak = 0.0
    cooling = 0.0
    stalled = 0
    clock = 0.0
    peak_vent = 0.0
    peak_vent_time = 0.0
    breaks = sorted({0.0, *(x for d in doses for a, b, _ in d.segments for x in (a, b))})
    if extra_breaks and len(breaks) > 1:  # ADR 0074: split the dosing where a regime changes
        breaks = sorted({*breaks, *(x for x in extra_breaks if x < breaks[-1])})
    passing_now = passing_rate((breaks[0] + breaks[1]) / 2) if len(breaks) > 1 else 0.0
    passing_by = passing_of((breaks[0] + breaks[1]) / 2) if len(breaks) > 1 else {}
    if ng:  # the head space's expelled gas at the start: the first segment's derivatives
        first = feeding((breaks[0] + breaks[1]) / 2) if len(breaks) > 1 else ([0.0] * size, [], 0)
        active[:] = [
            make_derivatives(*first, regime_of(0.0, breaks[1] if len(breaks) > 1 else None))
        ]
    record(state, clock)
    zero = [0.0] * len(names)
    for a, b in zip(breaks, breaks[1:], strict=False):
        source, sensible, mixing = feeding((a + b) / 2)
        passing_now = passing_rate((a + b) / 2)
        passing_by = passing_of((a + b) / 2)
        state, clock = run(state, clock, b, None, source, sensible, False, mixing, regime_of(a, b))
    dosing_end = clock
    passing_now = 0.0
    passing_by = {}
    target = batch.target.conversion if batch.target else None

    def finish(t_end: float | None, target: float | None) -> None:
        """The post-reaction to *t_end* s or the *target*, split where an ADR 0074 regime
        changes (one run without them)."""
        nonlocal state, clock
        for x in extra_breaks:
            if x <= clock + 1e-9 * max(clock, 1.0) or (t_end is not None and x >= t_end):
                continue
            state, clock = run(state, clock, x, target, zero, [], False, 0.0, regime_of(clock, x))
            if target is not None and conversion(state, clock) >= target - 1e-12:
                return
        state, clock = run(
            state, clock, t_end, target, zero, [], True, 0.0, regime_of(clock, t_end)
        )

    if uninitiated and not doses:
        result.notes.append("every dose waits for the initiation: none accumulates uninitiated")
    elif uninitiated:  # ADR 0074: until the initiation was due, or the last dose not waiting ends
        stop = max([batch.initiation.time, dosing_end])
        if stop > clock:
            finish(stop, None)
    elif not doses:
        finish(batch.time, target)
    elif target is not None and conversion(state, clock) >= target:
        result.notes.append(
            f"the target conversion {target:g} of {key} is reached when the dosing ends"
        )
    elif batch.time is not None or target is not None:
        finish(clock + batch.time if batch.time is not None else None, target)
    result.outlet = dict(zip(names, state[:size], strict=True))
    change = [b - a - d for a, b, d in zip(n0, state[:size], dosed, strict=True)]
    for k, i in enumerate(vented):  # what formed and left by the vent formed all the same
        change[i] += state[size + k]
    gone_by_gas = lost(state)  # the vapour the liquid lost is no reaction's (ADR 0062)
    for k, i in enumerate(volatile):
        change[i] += gone_by_gas[k]
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
    for k, i in enumerate(volatile):
        result.outlet[names[i]] = max(result.outlet[names[i]] - gone_by_gas[k], 0.0)
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
        if ng:
            # the head space's pad leaves by the vent too: what it expelled over the batch and
            # what it holds at the end, with the next charge or the purge (ADR 0071)
            for name, amount in pad.items():
                result.vent[name] = result.vent.get(name, 0.0) + amount
            _head_space_results(
                result,
                state,
                gas_names,
                head_at,
                vessel,
                room0,
                pad,
                head_room(state[:size], state[-2]),
            )
        gases = {n: result.vent.get(n, 0.0) for n in gas_names}  # the non-condensables
        result.vent_temperature = tc if condensing else state[-2]
        if phase is not None:
            _vapour_results(
                result, phase, state, names, volatile, base, condensing, gases, adiabatic
            )
            if lacking := [n for n in asked if n not in names]:
                result.notes.append(
                    "vent: " + ", ".join(lacking) + " not in the batch: no vapour of it"
                )
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
        result.dosed_reactants = {
            n: n0[i] + dosed[i]
            for i, n in enumerate(names)
            if dosed[i] > 0 and n in is_reactant and n0[i] + dosed[i] > 0
        }
    result.charge_temperature = charge_temperature
    result.charged = {n: v for n, v in zip(names, n0, strict=True) if v > 0}
    _kinetic_results(result, mix, batch, names, n0, state, moving, temperature)
    if not adiabatic:
        _heat_terms(result, known, unknown_heat, heat, temperature, doses, dose_capacity)
        if result.heat_terms is not None and varying:
            _moving_terms(result, moving, moving_missing, doses, dose_capacity, program, reflux)
        if result.heat_terms is not None:
            gas = sum(
                c * (temperature - d.temperature)
                for d, c in zip(doses, passing_capacity, strict=True)
                if c is not None
            )
            if gas:
                result.heat_terms["vent gas"] = gas
            if any(d.solution is not None for d in doses):
                # every dose has mixed in by the end: its whole heat of solution (ADR 0063),
                # less that of what the vent's vapour took off the liquid again (ADR 0062)
                result.heat_terms["solution"] = -sum(d.solution or 0.0 for d in doses) + sum(
                    a * h for a, h in zip(gone_by_gas, demix, strict=True)
                )
            if absorbing:
                # a formed gas's dissolved share released its heat of absorption (ADR 0071)
                result.heat_terms["absorption"] = -state[absorb_at]
            if getattr(batch, "heat_up", False):
                _heat_up(result, mix, charge, charge_temperature, temperature)
        if nv:
            _vapour_heat(result, phase, temperature, condensing and phase.returns)
    elif nv and (
        no_heat := [
            n
            for n, v in result.vapour.items()
            if v > 0 and n not in degassing and not phase.heat_of_vaporization.get(n)
        ]
    ):
        result.notes.append(
            "vent: the evaporative cooling of " + ", ".join(no_heat) + " is left out (no "
            "heat_of_vaporization)"
        )
    if nv and (
        cold := [
            n
            for n, v in result.vapour.items()
            if v > 0 and n in degassing and phase.heat_of_vaporization.get(n) is None
        ]
    ):
        result.notes.append(
            "vent: the heat of desorption of " + ", ".join(cold) + " is left out (no "
            "vent.heat_of_absorption)"
        )
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


def _kinetic_rate(
    mix: _Mixture,
    names: Sequence[str],
    state: Sequence[float],
    new: Sequence[float],
    h: float,
    regime: Any,
) -> float:
    """kW the content's cooling duty changes by over a step of *h* s from *state* to *new*
    (ADR 0074): less the heat its warming takes up, more the light it absorbs."""
    size = len(names)
    found = 0.0
    t0, t1 = state[-2], new[-2]
    if t1 != t0:
        with contextlib.suppress(TankError):  # the heat terms say what is missing
            found -= mix.capacity(dict(zip(names, new[:size], strict=True)), t1) * (t1 - t0) / h
    if mix.light is not None and regime.lit:
        found += mix.absorbed(new[:size])[1]
    return found


def _moving_terms(
    result: TankResult,
    moving: Mapping[str, float],
    missing_now: Sequence[str],
    doses: Sequence[Dose],
    capacity: Sequence[float | None],
    program: Any,
    reflux: bool,
) -> None:
    """An isothermal batch's heat terms with a temperature that moves or a lamp (ADR 0074):
    ``doses`` warmed to the temperature each met, ``content`` the content's sensible heat as
    its temperature follows the programme or the bubble point, minus the ``light`` absorbed."""
    lacking = [
        f"the liquid_heat_capacity of dose {k + 1} (the batch's temperature moves)"
        for k, c in enumerate(capacity)
        if c is None
    ]
    if program is not None or reflux:
        lacking += [f"the content's heat capacity: {m}" for m in missing_now]
    if lacking:
        result.heat_terms = None
        result.heat_missing = lacking
        return
    terms = result.heat_terms or {}
    if doses:
        terms["doses"] = moving["doses"]
    if program is not None or reflux:
        terms["content"] = moving["content"]
    if result.light:
        terms["light"] = -moving["light"]


def _kinetic_results(
    result: TankResult,
    mix: _Mixture,
    batch: Any,
    names: Sequence[str],
    n0: Sequence[float],
    state: Sequence[float],
    moving: Mapping[str, float],
    start: float,
) -> None:
    """The ADR 0074 terms of a run into *result*, each only where declared: the solid phase,
    the light, a programme's or a reflux's temperatures."""
    size = len(names)
    for name in mix.solids:
        i = names.index(name)
        found: dict[str, Any] = {"start_kmol_h": n0[i], "end_kmol_h": max(state[i], 0.0)}
        if name in mix.surfaces:
            found["area_start_m2"] = mix.surfaces[name][0]
            charged = mix.surfaces[name][1]
            found["area_end_m2"] = mix.surfaces[name][0] * (max(state[i], 0.0) / charged) ** (
                2.0 / 3.0
            )
        result.solids[name] = found
    if mix.light is not None:
        flux, power, light = mix.light
        result.light = {
            "power_kW": power,
            "photons_kmol_s": flux,
            "absorbed_share_end": mix.absorbed(state[:size])[1] / power if power else None,
            "photons_absorbed_kmol_h": moving["photons"],
            "absorbed_kJ_h": moving["light"],
            "on": [list(w) for w in light.on] or None,
        }
    if getattr(batch, "program", None) is not None or batch.heat == "reflux":
        hottest = max(p[1] for p in result.profile) if result.profile else start
        result.temperatures = {
            "mode": "reflux" if batch.heat == "reflux" else "program",
            "start_K": start,
            "end_K": state[-2],
            "max_K": hottest,
        }


def _vapour_results(
    result: TankResult,
    phase: Any,
    state: Sequence[float],
    names: Sequence[str],
    volatile: Sequence[int],
    base: int,
    condensing: bool,
    gases: Mapping[str, float],
    adiabatic: bool,
) -> None:
    """A vented batch's vapour (ADR 0062) into *result*: what the gas carried off the liquid,
    what a condenser condensed of it, what passed by the vent, the condenser's heat, and the
    vapour's share of the gas over the liquid at the end."""
    from chemeascode.domains.process.vent_vapour import condenser_heat

    nv = len(volatile)
    carried = {names[i]: max(state[base + k], 0.0) for k, i in enumerate(volatile)}
    past = (
        {names[i]: max(state[base + nv + k], 0.0) for k, i in enumerate(volatile)}
        if condensing
        else dict(carried)
    )
    result.vapour = carried
    for name, amount in past.items():
        result.vent[name] = result.vent.get(name, 0.0) + amount
    t_end, p = state[-2], result.pressure
    if nv:
        held = {n: v for n, v in result.outlet.items() if v > 0}
        result.vapour_share = sum(phase.saturation(held, t_end, p).values())
    if not condensing:
        return
    result.condensate = {n: max(carried[n] - past[n], 0.0) for n in carried}
    heat, terms, lacking, no_gas = condenser_heat(phase, t_end, carried, result.condensate, gases)
    if lacking:
        result.condenser_missing = lacking
        return
    if no_gas:
        result.notes.append(
            "vent: the condenser's duty leaves out the cooling of " + ", ".join(no_gas) + " (no "
            "ideal_gas data)"
        )
    integrated = state[base + 2 * nv + 1]
    if adiabatic:
        # the temperature changed over the run: the integral, not the end's terms
        result.condenser_heat, result.condenser_terms = integrated, {"total": integrated}
    else:
        result.condenser_heat, result.condenser_terms = heat, terms


def _head_space_results(
    result: TankResult,
    state: Sequence[float],
    gases: Sequence[str],
    at: int,
    vessel: float,
    room0: float,
    pad: Mapping[str, float],
    room: float,
) -> None:
    """The head space (ADR 0071) into *result*: the vessel's volume, the head space's at the
    start and the end (m3 per hour of charge), its gas then and what it expelled (kmol)."""
    n = len(gases)
    end = {g: max(state[at + k], 0.0) for k, g in enumerate(gases)}
    expelled = {g: state[at + n + k] for k, g in enumerate(gases)}
    result.head_space = {
        "vessel_m3": vessel,
        "start_m3": room0,
        "end_m3": room,
        "start_kmol": dict(pad),
        "end_kmol": end,
        "expelled_kmol": expelled,
    }
    if any(v < 0 for v in expelled.values()):
        result.notes.append(
            "vent: the head space drew back more gas from the vent line than it had expelled"
        )


def _vapour_heat(result: TankResult, phase: Any, temperature: float, returned: bool) -> None:
    """The isothermal batch's heat terms for its vent's vapour (ADR 0062): the latent heat of
    what the gas carried off (``vent vapour``) and a returned condensate warmed back from the
    condenser's temperature (``condensate return``); or what they lack."""
    if result.heat_terms is None:
        return  # its own terms lack data already
    degassing = getattr(phase, "degassing", None) or {}
    lacking = [
        n
        for n, v in result.vapour.items()
        if v > 0 and n not in degassing and not phase.heat_of_vaporization.get(n)
    ]
    cold = [
        n
        for n, v in result.condensate.items()
        if returned and v > 0 and not phase.liquid_heat_capacity.get(n)
    ]
    if lacking or cold:
        result.heat_terms = None
        result.heat_missing = [
            *(
                [f"the heat_of_vaporization of {', '.join(lacking)} (the vent's vapour)"]
                * bool(lacking)
            ),
            *(
                [f"the liquid_heat_capacity of {', '.join(cold)} (the condensate returned)"]
                * bool(cold)
            ),
        ]
        return
    result.heat_terms["vent vapour"] = sum(
        v * (phase.heat_of_vaporization[n] or 0.0) for n, v in result.vapour.items()
    )
    if returned and result.condensate:
        result.heat_terms["condensate return"] = sum(
            v * (phase.liquid_heat_capacity[n] or 0.0) * (temperature - phase.condenser)
            for n, v in result.condensate.items()
        )


def _heat_terms(
    result: TankResult,
    known: bool,
    unknown: str,
    heat: float,
    temperature: float,
    doses: Sequence[Dose],
    capacity: Sequence[float | None],
) -> None:
    """The isothermal batch's heat into the content by term (:attr:`TankResult.heat_terms`):
    minus the *heat* released (kJ), each dose warmed from its temperature to the batch's at its
    heat *capacity* (kJ/K, None: not known), or what is missing."""
    if not known:
        result.heat_missing = [f"the heat of reaction: {unknown}"]
        return
    lacking = [
        f"the liquid_heat_capacity of dose {k + 1} ({d.temperature:g} K, the batch at "
        f"{temperature:g} K)"
        for k, (d, c) in enumerate(zip(doses, capacity, strict=True))
        if c is None and abs(d.temperature - temperature) > 1e-9
    ]
    if lacking:
        result.heat_missing = lacking
        return
    terms = {"reaction": -heat}
    warming = sum(
        (c or 0.0) * (temperature - d.temperature) for d, c in zip(doses, capacity, strict=True)
    )
    if doses:
        terms["doses"] = warming
    result.heat_terms = terms


def _heat_up(
    result: TankResult,
    mix: _Mixture,
    charge: Mapping[str, float],
    t_charge: float,
    temperature: float,
) -> None:
    """The charge's heat-up from *t_charge* to the batch's *temperature* K (``batch.heat_up``,
    ADR 0063) as the heat term ``charge heat-up``: a liquid's ``liquid_heat_capacity``, a closed
    gas's ideal-gas cv at the mean temperature; what is missing otherwise (the duty then is
    not known)."""
    moles = {n: v for n, v in charge.items() if v > 0}
    try:
        capacity = mix.capacity(moles, (t_charge + temperature) / 2)
    except TankError as failure:
        result.heat_terms = None
        result.heat_missing = [f"the charge's heat-up (batch.heat_up): {failure}"]
        return
    if result.heat_terms is not None:
        result.heat_terms["charge heat-up"] = capacity * (temperature - t_charge)


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
    pad = pad_stream(node)
    if pad is not None and any(s.id == pad for s in inlets):
        # the charge and the head space's pad (ADR 0071)
        if len(inlets) != 2:
            raise TankError(
                f"a {node.reactor} takes one inlet stream besides its head space's pad (mix the "
                "feeds before it)"
            )
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
    pad = pad_stream(node)
    charges = [s for s in inlets if s.id not in dosed and s.id != pad]
    if len(charges) != 1:
        raise TankError(
            f"a {node.reactor} takes one charge stream besides its doses and its head space's "
            f"pad ({len(charges)} given)"
        )
    return charges[0], [(d, by_id[d.stream]) for d in dosing]


def pad_stream(node: Any) -> str | None:
    """The inlet stream that pads batch *node*'s head space (``vent.head_space.stream``, ADR
    0071), else None."""
    vent = getattr(getattr(node, "batch", None), "vent", None)
    head = getattr(vent, "head_space", None)
    return head.stream if head is not None else None


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
    doses: list[Dose] = []
    pad: dict[str, float] | None = None
    if (pad_id := pad_stream(node)) is not None and node.reactor != "cstr":
        streams = inlet if isinstance(inlet, list) else [inlet]
        found = [s for s in streams if s.id == pad_id]
        if not found:
            # a caller that passed the material inlets without the pad (the charge alone, as
            # the hazard screening and the sampling take it): the pad is an inlet of the node
            found = [
                s
                for s in process.flowsheet.streams
                if s.id == pad_id
                and (ends := process.ends(s))
                and ends[1] is not None
                and ends[1].node == node.id
            ]
        if not found:
            raise TankError(f"the head space's pad {pad_id} is no inlet stream of {node.id}")
        pad, _, _ = stream_moles(process, found[0], case)
        if node.reactor == "batch":
            inlet = split_inlets(node, streams)[0]
    if node.reactor == "semibatch":
        inlet, pairs = split_inlets(node, inlet if isinstance(inlet, list) else [inlet])
        for dosing, stream in pairs:
            moles, kelvin, _ = stream_moles(process, stream, case)
            share = 1.0 if dosing.absorbed is None else dosing.absorbed
            through = {n: v * (1.0 - share) for n, v in moles.items()} if share < 1 else {}
            if share < 1:
                moles = {n: v * share for n, v in moles.items()}
            heat = getattr(dosing, "heat_of_solution", None)
            doses.append(
                Dose(
                    moles,
                    kelvin,
                    node.batch.segments(dosing),  # after the initiation where it waits (ADR 0074)
                    through,
                    _solution(dosing, moles),
                    dict(heat.values) if heat is not None else {},
                    dosing.after_initiation,
                )
            )
    moles, kelvin, kpa = stream_moles(process, inlet, case)
    held = outlet_temperature(process, node, case)
    return solve_moles(process, node, moles, kelvin, kpa, held[0] if held else None, doses, pad)


def outlet_temperature(process: Any, node: Any, case: str) -> tuple[float, str] | None:
    """K and stream id of the given or assumed (not calculated) temperature of tank or batch
    *node*'s liquid outlet in *case*, which an isothermal one is held at; None without one. The
    vent's stream and a vent condenser's condensate stream are no liquid outlet (ADR 0062).
    One lookup for the model (:func:`solve_node`) and the vent condenser's rule."""
    from chemeascode.foundation.units import to_kelvin

    fs = process.flowsheet
    found = None
    vent = getattr(node.batch, "vent", None) if node.reactor != "cstr" else None
    condenser = getattr(vent, "condenser", None)
    for stream in fs.streams:
        if vent is not None and stream.id == vent.stream:
            continue  # the liquid's outlet gives the batch's temperature, not the vent
        if condenser is not None and stream.id == condenser.returns:
            continue  # nor a vent condenser's condensate (ADR 0062)
        ends = process.ends(stream)
        if ends and ends[0] is not None and ends[0].node == node.id:
            q = stream.state.get(case)
            given = getattr(q, "temperature", None)
            if given is not None and given.provenance != "calculated":
                found = (to_kelvin(given.value, given.unit or fs.units.temperature), stream.id)
    return found


def _solution(dosing: Any, moles: Mapping[str, float]) -> float | None:
    """kJ a dose of *moles* (kmol, its dissolving share) releases as it mixes in: minus its
    components' ``heat_of_solution`` (kJ/kmol) times their amounts; None without one."""
    heat = getattr(dosing, "heat_of_solution", None)
    if heat is None:
        return None
    return -sum(moles.get(n, 0.0) * h for n, h in heat.values.items())


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
        "batch" if kind == "semibatch" else kind: spec.model_dump(
            mode="json", exclude=duty_only(spec)
        ),
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


def duty_only(spec: Any) -> dict[str, Any]:
    """What of batch or tank *spec* changes its duty and not its outlets, as a ``model_dump``
    exclude (ADR 0063): the charge's heat-up, and an isothermal batch's heats of solution
    (held at its temperature: an adiabatic batch's outlet temperature takes them). They are in
    the duty's fingerprint (:func:`.duties.batch_duty`). A vent condenser's ``energy_port``
    (ADR 0062) only picks the stream its duty is written on."""
    found: dict[str, Any] = {"heat_up": True}
    if getattr(spec, "heat", None) == "isothermal" and getattr(spec, "dosing", None):
        found["dosing"] = {"__all__": {"heat_of_solution": True}}
    if getattr(getattr(spec, "vent", None), "condenser", None) is not None:
        found["vent"] = {"condenser": {"energy_port": True}}
    return found


def solve_moles(
    process: Any,
    node: Any,
    moles: Mapping[str, float],
    kelvin: float,
    kpa: float,
    outlet_t: float | None = None,
    doses: Sequence[Dose] = (),
    pad: Mapping[str, float] | None = None,
) -> tuple[TankResult, dict[str, Any]]:
    """The tank or batch *node* fed with *moles* (kmol/h) at *kelvin* K and *kpa* kPa(a), an
    isothermal one held at *outlet_t* where given, a semi-batch dosed with *doses*, its head
    space padded with *pad* (kmol/h of inert, ADR 0071), and what it was solved from (its
    inputs besides the inlet). For ``cheme process propagate`` (through
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
    phase = None
    vent = getattr(spec, "vent", None) if kind != "cstr" else None
    if vent is not None and (vent.vapour is not None or vent.henry):
        # the vent's vapour, condenser and Henry split (ADR 0062); its inputs join the
        # fingerprint only when declared, so a vent without them fingerprints as in 1.9.0
        from chemeascode.domains.process import vent_vapour

        if vent.vapour is not None:
            phase = vent_vapour.phase_of(process, vent, names, data)
            inputs |= vent_vapour.inputs(process, vent, phase)
        else:
            phase = vent_vapour.henry_phase(vent)
    if kind != "cstr" and spec.heat == "reflux":  # its bubble point's data (ADR 0074)
        inputs["reflux"] = {
            n: [
                c.vapour_pressure.model_dump(mode="json") if c.vapour_pressure else None,
                c.normal_boiling_point,
                c.heat_of_vaporization,
            ]
            if (c := comps.get(n)) is not None
            else None
            for n in names
        }
    if doses:
        mixing = "dosing" not in duty_only(spec)  # the heat of solution: an outlet's input
        vapour = phase is not None and bool(getattr(phase, "volatile", None))
        inputs["doses"] = [
            {"moles": dict(d.moles), "T": d.temperature, "segments": d.segments}
            | ({"passing": dict(d.passing)} if d.passing else {})
            | ({"solution": d.solution} if mixing and d.solution is not None else {})
            # a vapour takes each component's own heat of solution back (ADR 0063)
            | ({"solution_by": dict(d.solution_by)} if mixing and vapour and d.solution_by else {})
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
        if pad:
            inputs["head_space"] = dict(pad)  # only with a head space (ADR 0071)
        result = solve_batch(
            reactions,
            moles,
            kelvin,
            kpa,
            spec,
            data,
            liquid,
            capacity,
            outlet_t,
            doses,
            phase,
            pad,
            comps,
        )
    return result, inputs


def _charged_kinetics(
    process: Any, node: Any, mix: _Mixture, reactions: list[Any], comps: Any, case: str
) -> None:
    """*mix* with batch *node*'s solid phase and light from its charge in *case* (ADR 0074),
    as :func:`_solve_batch` sets them."""
    from chemeascode.domains.process import batch_kinetics

    inlets = [
        s
        for s in process.flowsheet.streams
        if (ends := process.ends(s)) and ends[1] is not None and ends[1].node == node.id
    ]
    stream = tank_inlet(node, inlets)
    if isinstance(stream, list):
        stream = split_inlets(node, stream)[0]
    charge, _, _ = stream_moles(process, stream, case)
    _solid_phase(mix, node.batch, reactions, charge, (), comps)
    light = node.batch.light
    if light is not None:
        watts = light.power * mix.volume_flow(charge, 0.0, 0.0)
        mix.light = (batch_kinetics.photon_flux(watts, light.wavelength), watts / 1000.0, light)


def vent_gas_rate(
    process: Any,
    node: Any,
    moles: Mapping[str, float],
    temperature: float,
    pressure: float,
    case: str | None = None,
) -> float:
    """kmol/s of the vent's gas forming in the vented batch or semi-batch *node* with *moles*
    (kmol by component, the batch's basis) in it at *temperature* K and *pressure* kPa(a): the
    share ``f_g`` of what each reaction forms of each vent component ``g``, every reaction at
    its rate law (the thermal screening's gas release at the MTSR, ADR 0058). The dosing has
    stopped: no dosed gas passes through. With *case*, a surface rate's particles and the light
    come from its charge (ADR 0074). Raises TankError (a ValueError of a rate law too)."""
    found = vent_gas_rates(process, node, list(moles), case)(moles, temperature, pressure)
    return sum(found.values())


def vent_gas_rates(
    process: Any, node: Any, names: Sequence[str], case: str | None = None
) -> Callable[[Mapping[str, float], float, float], dict[str, float]]:
    """:func:`vent_gas_rate` by vent component (kmol/s), for many contents over *names*: the
    mixture is built once (the screening's gas release over the batch, ADR 0069)."""
    shares = node.batch.vent.shares()
    rates = extent_rates(process, node, names, case)
    reactions, _ = process.reactions_of(node.id)

    def gas(moles: Mapping[str, float], temperature: float, pressure: float) -> dict[str, float]:
        extents = rates(moles, temperature, pressure)
        return {
            g: f * sum(max(r.stoichiometry.get(g, 0.0) * extents[r.id], 0.0) for r in reactions)
            for g, f in shares.items()
        }

    return gas


def extent_rates(
    process: Any, node: Any, names: Sequence[str], case: str | None = None
) -> Callable[[Mapping[str, float], float, float], dict[str, float]]:
    """A function of a content (kmol by component, the batch's basis), *temperature* K and
    *pressure* kPa(a) giving each reaction's rate of extent ``M_j r_j`` (kmol/s) in the liquid
    batch or semi-batch *node*, every reaction at its rate law; *names* the components the
    contents may hold. A vent's components that were never in the liquid are gone, as in the
    run. With *case*, a solid phase's particles and the light are those of its charge in that
    case (ADR 0074); without it a surface or photochemical rate law raises. Raises TankError (a
    ValueError of a rate law too)."""
    from chemeascode.domains.process.liquid_phase import liquid_of

    vent = node.batch.vent
    reactions, unknown = process.reactions_of(node.id)
    if unknown:
        raise TankError("undeclared reactions " + ", ".join(unknown))
    shares = vent.shares() if vent is not None else {}
    names = list(dict.fromkeys([*names, *(n for r in reactions for n in r.stoichiometry), *shares]))
    comps = process.components()
    capacity = {n: getattr(comps.get(n), "liquid_heat_capacity", None) for n in names}
    mix = _mixture(
        reactions,
        names,
        process.ideal_gas(),
        liquid_of(process),
        capacity,
        node.batch.catalyst_loading,
    )
    if mix.liquid is None:
        raise TankError(
            "a vent takes its gas from a liquid: liquid-phase reactions only"
            if vent is not None
            else "the rates of a liquid batch: liquid-phase reactions only"
        )
    batch = node.batch
    if case is not None and (batch.solids or batch.light is not None):
        _charged_kinetics(process, node, mix, reactions, comps, case)

    # an inert never dissolves (ADR 0071): none of it in the content's volume
    inerts = frozenset(getattr(vent, "inerts", None) or ()) & set(names)

    def rates(moles: Mapping[str, float], temperature: float, pressure: float) -> dict[str, float]:
        mix.gone = frozenset(n for n, f in shares.items() if f >= 1.0 and not moles.get(n))
        mix.gone |= inerts
        state = [max(moles.get(n, 0.0), 0.0) for n in names]
        try:
            volume = mix.volume_flow(dict(zip(names, state, strict=True)), temperature, pressure)
            mult = mix.multipliers(volume, state)
            found = mix.rates(state, temperature, pressure)
        except TankError:
            raise
        except (ValueError, OverflowError, ZeroDivisionError) as failure:
            raise TankError(str(failure)) from failure
        return {r.id: x * k for r, x, k in zip(reactions, mult, found, strict=True)}

    return rates
