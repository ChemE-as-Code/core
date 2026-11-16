"""The vapour a batch's vent gas carries, its partial vent condenser and the dissolved share of
a vent gas by Henry's law (``batch.vent.vapour``, ``.condenser``, ``.henry``; ADR 0062).

**Vapour.** The gas leaving a vented batch or semi-batch (its vent components as they form,
and a dosed gas passing through: the non-condensables, ``G'`` kmol/s) leaves the vessel
saturated with the liquid's volatile components at the vessel's temperature ``T`` and pressure
``P``. With Raoult's law, ``y_i = gamma_i x_i P_i^sat(T) / P`` (an ideal liquid, ``gamma_i =
1``, unless ``vapour.activity`` gives a sourced constant) and ``Y = sum_i y_i``, the gas
carries off::

    s_i' = G' y_i / (1 - Y)                (kmol/s of each volatile component)

at each moment, from the liquid's composition then. ``Y >= 1`` is a boiling content: refused
(the vent is no still). The vapour's latent heat ``dHvap_i s_i'`` is the vessel's evaporative
cooling (a term of the isothermal duty; in an adiabatic batch it lowers the temperature).

**Condenser.** A partial condenser at ``T_c`` cools that gas and condenses what the gas cannot
hold at ``T_c``: an isothermal flash of the non-condensables ``G'`` (inerts: none of them
dissolves in the condensate) and the vapours ``s'`` with ``K_i = P_i^sat(T_c) / P`` (an ideal
condensate), the Rachford-Rice function with an inert::

    F(b) = sum_i s_i' (K_i - 1) / (1 + b (K_i - 1)) + G' / b = 0

monotone in the gas's share ``b`` of the feed; ``F(1) >= 0`` (``sum_i s_i'/K_i`` at most the
feed) condenses nothing. The gas passes on with ``v_i' = K_i s_i' b / (1 + b (K_i - 1))``, so
that one condensable with an inert leaves ``G' K / (1 - K)``, saturated at ``T_c``; the
condensate ``c_i' = s_i' - v_i'`` runs back to the vessel (the liquid then loses only ``v'``)
or leaves by a stream of the step. Its duty, the heat it removes at constant heats of
vaporization::

    Q_c = sum_i [c_i dHvap_i + s_i cp_i (T - T_c)] + sum_g [H_g(T) - H_g(T_c)]

(the vapour condensed at ``T``, the liquid cooled at ``liquid_heat_capacity``; what passes is
condensed, cooled and re-evaporated at ``T_c`` on the same path; the non-condensables cooled
as ideal gases). A returned condensate is warmed back to ``T`` in the vessel,
``c_i cp_i (T - T_c)``.

**Henry.** A vent component ``g`` with ``henry`` stays dissolved up to its solubility: the
liquid at the end of the run holds ``x_g = y_g P / H_g(T)``, ``y_g`` its share of the gas over
the liquid (the non-condensables in the ratio they form, with the vapour's ``Y``), and the vent
takes the rest of what formed. The share that leaves is found by successive substitution over
whole runs of the batch, so the dissolved gas counts in the liquid's volume and
concentrations as it forms. What was charged or dosed of ``g`` stays (the vent takes only what
forms): a liquid that starts above its solubility stays there, with a note.

**Degassing (ADR 0071).** A dissolved gas without a vapour pressure (``vapour.henry``) is
carried like a vapour at ``y_g = H_g(T) x_g / P`` (Henry's law instead of Raoult's), so the gas
through the vessel strips what was charged, dosed or formed of it; it never condenses (a vent
condenser passes it as a gas), and its heat of absorption, where given, is its heat of
desorption as it leaves. Any volatile component, by Raoult's law or Henry's, is degassed so:
the vapour needs only a carrier, which a formed gas, a dose's inerts and the head space's gas
(:mod:`.stirred_tank`) give.

Pure Python, deterministic (ADR 0010).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

#: What the vent's vapour, condenser and Henry split take for granted (reported by
#: :mod:`.model_basis`, beside :data:`.stirred_tank.ASSUMPTIONS`).
ASSUMPTIONS = (
    "the vent gas leaves the vessel saturated with the liquid's volatile components at its "
    "temperature and pressure (Raoult's law, Antoine vapour pressures; an ideal liquid unless "
    "vapour.activity gives sourced constants)",
    "the vapour's latent heat at a constant heat_of_vaporization, its liquid at a constant "
    "liquid_heat_capacity; no head space, no entrainment",
    "a vent condenser is one equilibrium stage at its outlet temperature over an ideal "
    "condensate; the vent's gases do not dissolve in it",
    "a henry component: the liquid at the end saturated at the gas's partial pressure over it "
    "(Henry's law), the same dissolved share of what forms over the run",
)

#: What a vent's inerts, head space, degassing and heat of absorption take for granted (ADR
#: 0071), reported beside :data:`ASSUMPTIONS` by a vent that declares them.
GAS_ASSUMPTIONS = (
    "the vent's inerts never dissolve: a dose's share of them passes straight through",
    "the head space is well mixed, at the vessel's temperature and pressure, saturated with "
    "the liquid's vapour; the gas it expels is the head space's; when it expands it draws back "
    "gas from the vent line, none of it vapour; its own vapour is not in the balance, and its "
    "inert left at the end leaves by the vent without vapour",
    "a dissolved gas with vapour.henry degasses at Henry's law in an ideal dilute solution and "
    "never condenses",
    "a vent gas's heat of absorption is constant: released as the formed gas's dissolved share "
    "forms, taken back as a degassing gas leaves",
)

#: Successive substitution of the Henry shares: at most this many runs of the batch.
HENRY_RUNS = 40
#: kmol of the Henry component's residual (kept less the solubility) relative to what formed.
HENRY_TOLERANCE = 1e-9


class VentError(ValueError):
    """The vent's vapour or condenser cannot be solved as declared."""


@dataclass
class VentPhase:
    """What the vapour, the condenser and the Henry split of one vented batch are solved from."""

    #: the volatile components the gas carries, each with its Antoine vapour_pressure
    volatile: list[str]
    vapour_pressure: Mapping[str, Any]
    activity: Mapping[str, float] = field(default_factory=dict)
    heat_of_vaporization: Mapping[str, float | None] = field(default_factory=dict)
    liquid_heat_capacity: Mapping[str, float | None] = field(default_factory=dict)
    #: ideal-gas data by component (the non-condensables' cooling in the condenser)
    gas: Mapping[str, Any] = field(default_factory=dict)
    #: K: the condenser's outlet temperature (None: no condenser)
    condenser: float | None = None
    #: the condensate runs back into the vessel (else it leaves by a stream)
    returns: bool = True
    henry: Mapping[str, Any] = field(default_factory=dict)
    #: ADR 0071: the dissolved gases that degas by Henry's law (``vapour.henry``), among
    #: ``volatile``: carried at ``H x / P``, never condensed
    degassing: Mapping[str, Any] = field(default_factory=dict)

    @property
    def condensable(self) -> list[str]:
        """The volatile components a vent condenser condenses (not a degassing gas)."""
        return [n for n in self.volatile if n not in self.degassing]

    def _pressure(self, name: str, t: float) -> float:
        """kPa: the Antoine vapour pressure, or a degassing gas's Henry constant, at *t* K."""
        if name in self.degassing:
            return self.degassing[name].kpa(t)[0]
        return self.vapour_pressure[name].kpa(t)

    def saturation(self, liquid: Mapping[str, float], t: float, p: float) -> dict[str, float]:
        """The vapour's mole fraction ``y_i`` of each volatile component over the *liquid*
        (kmol by component) at *t* K and *p* kPa(a). Raises VentError when the content boils
        (``sum y_i`` at least 1)."""
        total = sum(v for v in liquid.values() if v > 0)
        if total <= 0:
            return dict.fromkeys(self.volatile, 0.0)
        found = {
            n: self.activity.get(n, 1.0)
            * max(liquid.get(n, 0.0), 0.0)
            / total
            * self._pressure(n, t)
            / p
            for n in self.volatile
        }
        if sum(found.values()) >= 1.0:
            raise VentError(
                f"the content boils at {t:.6g} K and {p:.6g} kPa(a): its vapour pressure "
                f"{sum(found.values()) * p:.6g} kPa reaches the vessel's pressure (a vent carries "
                "the vapour of a liquid below its boiling point; a reflux or a still is not "
                "modelled)"
            )
        return found

    def k_values(self, t: float, p: float) -> dict[str, float]:
        """``K_i = gamma_i P_i^sat(T) / P`` (or ``H_i(T) / P`` of a degassing gas) of each
        volatile component at *t* K and *p* kPa(a): ``y_i = K_i x_i``."""
        return {n: self.activity.get(n, 1.0) * self._pressure(n, t) / p for n in self.volatile}

    def carried(self, liquid: Mapping[str, float], t: float, p: float) -> dict[str, float]:
        """kmol of each volatile component per kmol of non-condensable gas leaving the vessel:
        ``y_i / (1 - Y)``."""
        y = self.saturation(liquid, t, p)
        rest = 1.0 - sum(y.values())
        return {n: v / rest for n, v in y.items()}

    def condenser_k(self, p: float) -> dict[str, float]:
        """``K_i = P_i^sat(T_c) / P`` of each condensable component (an ideal condensate)."""
        assert self.condenser is not None
        return {n: self.vapour_pressure[n].kpa(self.condenser) / p for n in self.condensable}


def condense(gas: float, vapour: Mapping[str, float], k: Mapping[str, float]) -> dict[str, float]:
    """The vapour (kmol, or kmol/s) that passes a partial condenser with the non-condensable
    *gas* (same unit), by the Rachford-Rice function with an inert (see the module docstring);
    the rest condenses. No gas: nothing passes (a condensable alone condenses whole)."""
    feed = gas + sum(vapour.values())
    if feed <= 0 or not any(v > 0 for v in vapour.values()):
        return dict.fromkeys(vapour, 0.0)
    if gas <= 0:
        return dict.fromkeys(vapour, 0.0)

    def f(b: float) -> float:
        return gas / b + sum(z * (k[n] - 1.0) / (1.0 + b * (k[n] - 1.0)) for n, z in vapour.items())

    if all(k[n] > 0 for n, z in vapour.items() if z > 0):
        at_one = gas + sum(z * (1.0 - 1.0 / k[n]) for n, z in vapour.items() if z > 0)
        if at_one >= 0:
            return dict(vapour)  # the gas holds all of it at T_c: nothing condenses
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
    return {n: k[n] * z * b / (1.0 + b * (k[n] - 1.0)) for n, z in vapour.items()}


def condenser_heat(
    phase: VentPhase,
    t: float,
    evaporated: Mapping[str, float],
    condensed: Mapping[str, float],
    gases: Mapping[str, float],
) -> tuple[float | None, dict[str, float], list[str], list[str]]:
    """kJ (or kW) the condenser removes from the gas leaving the vessel at *t* K: the
    *evaporated* vapour (kmol by component, into the condenser), of which *condensed*
    condenses, and the non-condensable *gases*; by term (``condensation``, ``vapour cooled``,
    ``gas cooled``), or None and what is missing; and the gases whose cooling is left out (no
    ideal-gas data: a minor term, as a dosed gas's warming in ADR 0054)."""
    assert phase.condenser is not None
    tc = phase.condenser
    if phase.degassing:  # a degassing gas passes as a gas (ADR 0071)
        gases = {**gases, **{n: v for n, v in evaporated.items() if n in phase.degassing}}
        evaporated = {n: v for n, v in evaporated.items() if n not in phase.degassing}
    lacking = sorted(
        {n for n, v in condensed.items() if v > 0 and not phase.heat_of_vaporization.get(n)}
    )
    no_cp = sorted(
        {n for n, v in evaporated.items() if v > 0 and not phase.liquid_heat_capacity.get(n)}
    )
    no_gas = sorted({n for n, v in gases.items() if v > 0 and phase.gas.get(n) is None})
    missing = [f"the heat_of_vaporization of {', '.join(lacking)}"] * bool(lacking) + [
        f"the liquid_heat_capacity of {', '.join(no_cp)}"
    ] * bool(no_cp)
    if missing:
        return None, {}, missing, no_gas
    terms = {
        "condensation": sum(
            v * (phase.heat_of_vaporization[n] or 0.0) for n, v in condensed.items()
        ),
        "vapour cooled": sum(
            v * (phase.liquid_heat_capacity[n] or 0.0) * (t - tc) for n, v in evaporated.items()
        ),
        "gas cooled": sum(
            v * (phase.gas[n].enthalpy(t) - phase.gas[n].enthalpy(tc))
            for n, v in gases.items()
            if v > 0 and phase.gas.get(n) is not None
        ),
    }
    return sum(terms.values()), terms, [], no_gas


def phase_of(process: Any, vent: Any, names: list[str], gas: Mapping[str, Any]) -> VentPhase:
    """The :class:`VentPhase` of *vent* (a :class:`~.schema.Vent` with ``vapour``) in
    *process*, over the batch's components *names*. Raises VentError naming a volatile
    component without a vapour_pressure."""
    comps = process.components()
    spec = vent.vapour
    gases = {*vent.components, *vent.inerts}
    degassing = dict(spec.henry)
    if spec.components:
        volatile = list(spec.components)
        if lack := [
            n
            for n in volatile
            if n not in degassing and getattr(comps.get(n), "vapour_pressure", None) is None
        ]:
            raise VentError(
                "vent.vapour: no vapour_pressure (Antoine) for " + ", ".join(lack) + " in "
                "materials.yaml"
            )
    else:
        volatile = [
            n
            for n in names
            if n not in gases
            and n not in degassing
            and getattr(comps.get(n), "vapour_pressure", None) is not None
        ]
    volatile += [n for n in degassing if n not in volatile]
    # a degassing gas's heat of desorption: minus its heat of absorption (ADR 0071)
    absorption = vent.heat_of_absorption.values if vent.heat_of_absorption is not None else {}
    condenser = vent.condenser
    return VentPhase(
        volatile=volatile,
        vapour_pressure={n: comps[n].vapour_pressure for n in volatile if n not in degassing},
        activity=dict(spec.activity),
        heat_of_vaporization={
            n: (
                (-absorption[n] if n in absorption else None)
                if n in degassing
                else getattr(comps.get(n), "heat_of_vaporization", None)
            )
            for n in volatile
        },
        liquid_heat_capacity={
            n: getattr(comps.get(n), "liquid_heat_capacity", None) for n in volatile
        },
        gas=dict(gas),
        condenser=condenser.temperature if condenser is not None else None,
        returns=condenser is None or condenser.returns == "vessel",
        henry=dict(vent.henry),
        degassing=degassing,
    )


def henry_phase(vent: Any) -> VentPhase:
    """A :class:`VentPhase` with only *vent*'s Henry constants (a vent without vapour)."""
    return VentPhase(volatile=[], vapour_pressure={}, henry=dict(vent.henry))


def inputs(process: Any, vent: Any, phase: VentPhase | None) -> dict[str, Any]:
    """What the vapour and condenser depend on beyond the vent's own dump (for the outlets'
    fingerprint): the volatile components' Antoine constants and heats of vaporization."""
    if phase is None or vent.vapour is None:
        return {}
    return {
        "vent_vapour": {
            n: {
                "vapour_pressure": phase.vapour_pressure[n].model_dump(mode="json"),
                "heat_of_vaporization": phase.heat_of_vaporization.get(n),
            }
            for n in phase.volatile
            if n not in phase.degassing  # a degassing gas's constants are in the vent's dump
        }
    }
