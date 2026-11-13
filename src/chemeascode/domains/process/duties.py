"""The duty a block's or step's model gives its energy stream (ADR 0059).

Four models know the heat they exchange, per hour of the flowsheet's flows (the year average a
batch plant's flowsheet holds, ADR 0050, 0051), as heat into the block or step (positive:
supplied, negative: removed):

- an isothermal **batch or semi-batch** (``reactor: batch`` or ``semibatch``,
  :mod:`.stirred_tank`): minus the heat its reactions release over the batch, plus each dose
  warmed from its own temperature to the batch's (and a dosed gas passing through to the vent,
  where its ideal-gas data are known), ``Q = -sum_j dHr_j xi_j + sum_d C_d (T - T_d)``; the
  charge's heat-up to the batch temperature is a heat operation of the recipe, not included (the
  model holds the batch at its temperature from the start);
- a **batch still** (``still:``, :mod:`.batch_still`): the boil-up's latent heat, ``Q =
  sum_i dHvap_i D_i``, D_i the kmol/h distilled (the energy per batch over the batch's hours
  of flows); with a column (``still.column``, ADR 0061) the reboiler boils up ``(R + 1)`` times
  the distillate, ``Q = integral (R + 1) lambda(x_D) dD``, and the condenser removes as much
  (total condenser, constant molar overflow) on its own stream (``still.condenser_port``, by
  default the column's one heat stream out; the reboiler's is then its one heat stream in);
- a **crystallizer** with ``energy:`` (:mod:`.crystallization`): its lumped duty (the feed's
  sensible heat, the heat of crystallization, the solvent evaporated);
- a **conversion step** (``reactions:`` with conversions, ``reactor: conversion`` or a
  ``selectivity:``): with every reaction's ``heat_of_reaction``, the reactions at its declared
  temperature ``T_ref`` (one for all of them) and each stream's sensible heat to or from it,
  ``H(out) - H(in) = sum_j dHr_j xi_j + sum_in n cp (T_ref - T_in) + sum_out n cp (T_out -
  T_ref)`` (a liquid_heat_capacity, or the ideal-gas enthalpy for a stream said to be vapour or
  a component with no liquid one; heats at different temperatures, or a component in a vapour
  stream on one side and a liquid one on the other, leave it unknown); else, a gas-phase step
  (no stream said to hold a liquid, no reaction of phase liquid or mixed) whose components
  all have ideal-gas data, ``H(out) - H(in)`` on the elements basis; else nothing. Its heat
  is ``Q = H(out) - H(in) - W``, W the energy its other energy streams bring in (their
  duties, signed by their direction: an electrolyser's DC power, a shaft's work); an other
  energy stream without a duty leaves Q unknown.

ADR 0063 adds terms: a dose's heat of solution (``solution``), the charge's heat-up of a batch
or still with ``heat_up`` (``charge heat-up``), and ``vessel metal`` where the step runs in a
recipe vessel with ``metal_heat_capacity`` (:func:`with_metal`).

ADR 0075 adds a charged solid's heat of solution (``batch.heat_of_solution``, in ``solution``),
the agitator's power (``agitation``, a batch's or a still's ``agitator_power``), a still's
``sensible rise`` while it boils and its ``heat losses`` (``sensible_heat``, ``heat_loss``), a
conversion step's ``vessel metal`` (``vessel_metal``), a batch's heat-up on its own stream
(``batch.heat_up_port``: the terms ``charge heat-up`` and ``vessel metal`` there, the rest on the
model's stream) and a recipe heat or cool operation's heat on the stream it names
(:func:`.recipe.stream_heats`, written by propagate).

ADR 0062 adds, for a batch or semi-batch whose vent carries the liquid's vapour, the term
``vent vapour`` of its duty and its vent condenser's duty (:func:`vent_condenser_duty`) on the
condenser's own stream (``batch.vent.condenser.energy_port``). Two different condensers have
their own streams: a batch still's (ADR 0061, :func:`still_condenser_duty`, the boil-up's latent
heat) and a batch's vent condenser (ADR 0062); neither is the reboiler's or jacket's.

The duty goes on the energy stream at the node's ``energy_port``, else on its one heat stream:
an energy stream whose other end is a heating or cooling utility (steam, hot oil, fired heat,
cooling water, air cooling, refrigerant). An energy stream to or from another block or step
(a furnace heating a cracker, a rectifier feeding a cell) is heat only where ``energy_port``
names it; electricity, fuel and terminals without a utility are not heat. An energy stream's
``duty`` is positive in its own direction (:mod:`.energy`): a stream into the node carries
``Q``, a stream out of it ``-Q``. A model whose heat flows against the stream's direction is
reported, never written as a negative duty, and two models that give one stream different
duties are reported, neither written.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.foundation.provenance import NOT_INPUTS

#: The utilities whose energy streams are heat (the others: electricity, fuel, other).
HEAT_UTILITIES = frozenset(
    {"steam", "hot_oil", "fired_heat", "cooling_water", "air_cooling", "refrigerant"}
)
BATCH_BASIS = (
    "isothermal batch: the heat its reactions release over the batch and the doses warmed to "
    "the batch's temperature, per hour of the flowsheet's flows; the charge's heat-up, the "
    "heats of absorption and solution, agitation and heat losses not included"
)
STILL_BASIS = (
    "batch still: the latent heat of what boils up (heat_of_vaporization), per hour of the "
    "flowsheet's flows; the heat-up to the bubble point and heat losses not included"
)
STILL_CONDENSER_BASIS = (
    "batch still's condenser: the latent heat of the vapour it condenses (the distillate and "
    "the reflux, total condenser), per hour of the flowsheet's flows; no subcooling"
)
CONVERSION_BASIS = (
    "conversion step: the declared heats of reaction at their temperature, each stream "
    "brought to or from it at its heat capacity; heats of mixing not included"
)
VENT_CONDENSER_BASIS = (
    "vent condenser: the vapour condensed at the vessel's temperature (heat_of_vaporization), "
    "the vapour cooled as liquid to the condenser's outlet (liquid_heat_capacity) and the "
    "non-condensables cooled as ideal gases, per hour of the flowsheet's flows"
)
IDEAL_GAS_BASIS = "conversion step: H(out) - H(in) of ideal gases on the elements basis"
OTHER_BASIS = "; less the energy its other energy streams bring in (their duties)"


@dataclass
class ModelDuty:
    """The heat a model exchanges, kW into its block or step (per hour of the flowsheet's
    flows), by term, or what it lacks."""

    node: str
    model: str  # batch, semibatch, still, crystallizer, conversion
    heat_kW: float | None
    terms_kW: dict[str, float] = field(default_factory=dict)
    basis: str = ""
    missing: list[str] = field(default_factory=list)
    #: what the terms of ADR 0063 depend on besides the model's inputs (the heat-up, the
    #: vessel's metal): the duty's fingerprint; empty without them
    inputs: dict[str, Any] = field(default_factory=dict, repr=False)

    def entry(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "heat_in_kW": self.heat_kW,
            "terms_kW": dict(self.terms_kW),
            "basis": self.basis,
            "missing": list(self.missing),
        }


@dataclass
class Target:
    """The energy stream a model's duty goes on: at *port* of the node, *into* it or out."""

    stream: Any
    port: str
    into: bool
    chosen: str  # "energy_port" or "its one heat stream"

    def duty(self, heat_kw: float) -> float:
        """The stream's duty (positive in its direction) for *heat_kw* into the node."""
        return heat_kw if self.into else -heat_kw


def duty_model(node: Any) -> str | None:
    """The model that gives *node* its duty: batch, semibatch, still, crystallizer or
    conversion; None for any other (a dryer reports its own, ADR 0057)."""
    if getattr(node, "still", None) is not None:
        return "still"
    if getattr(node, "crystallizer", None) is not None:
        return "crystallizer"
    reactor = getattr(node, "reactor", None)
    if reactor in ("batch", "semibatch"):
        return reactor
    if getattr(node, "reactions", None) and reactor in (None, "conversion"):
        return "conversion"
    return None


def _energy_ends(process: Any, node: Any) -> list[tuple[Any, str, bool, str | None]]:
    """(stream, port, into the node, the other end's node) of every energy stream at *node*."""
    found = []
    for stream in process.flowsheet.streams:
        if stream.kind != "energy":
            continue
        a, b = process.ends(stream)
        if b is not None and b.node == node.id:
            found.append((stream, b.port, True, a.node if a is not None else None))
        elif a is not None and a.node == node.id:
            found.append((stream, a.port, False, b.node if b is not None else None))
    return found


def is_heat(process: Any, other: str | None) -> bool:
    """Whether an energy stream to or from *other* is heat by default: a terminal whose utility
    is a heating or cooling one. One to or from a block or step is heat only where
    ``energy_port`` names it (it may be a rectifier's DC power, a drive's shaft work)."""
    if other is None or process.kinds.get(other) in ("block", "step"):
        return False
    utility = getattr(process.nodes.get(other), "utility", None)
    return utility is not None and utility.kind in HEAT_UTILITIES


def still_condenser_target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream a batch still's condenser duty goes on: the one at
    ``still.condenser_port``, else (a still with a column) its one heat stream out; None and
    why ('' for a still without a column or a condenser_port, or no still: nothing to say)."""
    spec = getattr(node, "still", None)
    if spec is None:
        return None, ""
    ends = _energy_ends(process, node)
    port = spec.condenser_port
    if port is not None:
        at = [e for e in ends if e[1] == port]
        if not at:
            return None, f"no energy stream at its condenser_port {port}"
        stream, _, into, _ = at[0]
        return Target(stream, port, into, "condenser_port"), ""
    if spec.column is None:
        return None, ""
    out = [e for e in ends if not e[2] and is_heat(process, e[3])]
    if len(out) == 1:
        stream, at_port, into, _ = out[0]
        return Target(stream, at_port, into, "its one heat stream out"), ""
    if out:
        return None, (
            f"{len(out)} heat streams out of it ({', '.join(e[0].id for e in out)}): name the "
            "condenser's in still.condenser_port"
        )
    return None, (
        "no heat stream out of it to a cooling utility: give the condenser its energy stream "
        "(from the still to cooling water), or name it in still.condenser_port"
    )


def vent_condenser_port(node: Any) -> str | None:
    """The energy port of *node*'s vent condenser (ADR 0062): its own stream, never the
    jacket's."""
    vent = getattr(getattr(node, "batch", None), "vent", None)
    condenser = getattr(vent, "condenser", None)
    return getattr(condenser, "energy_port", None)


def vent_condenser_target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream *node*'s vent condenser's duty goes on (ADR 0062), or None and why
    ('' without a condenser)."""
    vent = getattr(getattr(node, "batch", None), "vent", None)
    if getattr(vent, "condenser", None) is None:
        return None, ""
    port = vent_condenser_port(node)
    if port is None:
        return None, "the vent condenser names no energy_port"
    at = [e for e in _energy_ends(process, node) if e[1] == port]
    if not at:
        return None, f"no energy stream at the vent condenser's energy_port {port}"
    stream, _, into, _ = at[0]
    return Target(stream, port, into, "vent.condenser.energy_port"), ""


def vent_condenser_duty(node: Any, result: Any) -> ModelDuty:
    """The duty of *node*'s vent condenser from its batch's solution (:class:`.TankResult`):
    the heat it removes, as heat into the node (negative), per hour of the flowsheet's flows."""
    label = "vent condenser"
    if result.condenser_heat is None:
        missing = result.condenser_missing or ["the vent's vapour (nothing condensed)"]
        return ModelDuty(node.id, label, None, basis=VENT_CONDENSER_BASIS, missing=missing)
    terms = {k: -v / 3600.0 for k, v in result.condenser_terms.items()}
    return ModelDuty(node.id, label, -result.condenser_heat / 3600.0, terms, VENT_CONDENSER_BASIS)


def target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream *node*'s model duty goes on, or None and why ('' when the node has no
    heat stream at all: nothing to say). A batch still's condenser stream
    (:func:`still_condenser_target`, ADR 0061) is not its reboiler's; with a column, the
    reboiler's default is its one heat stream in. A batch's vent condenser stream
    (:func:`vent_condenser_target`, ADR 0062) is the condenser's own, not the jacket's."""
    ends = _energy_ends(process, node)
    vent_port = vent_condenser_port(node)
    if vent_port is not None:
        ends = [e for e in ends if e[1] != vent_port]
    heat_up_port = getattr(getattr(node, "batch", None), "heat_up_port", None)
    if heat_up_port is not None:  # the heat-up's own stream (ADR 0075)
        ends = [e for e in ends if e[1] != heat_up_port]
    spec = getattr(node, "still", None)
    if spec is not None and (spec.condenser_port is not None or spec.column is not None):
        condenser, _ = still_condenser_target(process, node)
        if condenser is not None:
            ends = [e for e in ends if e[0].id != condenser.stream.id]
        if spec.column is not None and getattr(node, "energy_port", None) is None:
            ends = [e for e in ends if e[2]]
    port = getattr(node, "energy_port", None)
    if port is not None:
        at = [e for e in ends if e[1] == port]
        if not at:
            return None, f"no energy stream at its energy_port {port}"
        stream, _, into, _ = at[0]
        return Target(stream, port, into, "energy_port"), ""
    heat = [e for e in ends if is_heat(process, e[3])]
    if len(heat) == 1:
        stream, at_port, into, _ = heat[0]
        return Target(stream, at_port, into, "its one heat stream"), ""
    if heat:
        return None, (
            f"{len(heat)} heat streams ({', '.join(e[0].id for e in heat)}): name the one the "
            "model's duty goes on in energy_port"
        )
    joins = [e[0].id for e in ends if process.kinds.get(e[3]) in ("block", "step")]
    if joins:
        return None, (
            f"no heat stream to a heating or cooling utility; {', '.join(joins)} joins another "
            "block or step, heat only where energy_port names it"
        )
    return None, ""


def other_energy(process: Any, node: Any, case: str) -> tuple[float, dict[str, Any], list[str]]:
    """The kW *node*'s energy streams other than its heat stream bring into it (their duties,
    signed by their direction: an electrolyser's DC power, a shaft's work), what that depends
    on (the fingerprint) and the streams without a duty. Without a chosen heat stream, the
    streams that are not heat by default (:func:`is_heat`)."""
    goal, _ = target(process, node)
    ends = _energy_ends(process, node)
    if goal is not None:
        rest = [e for e in ends if e[0].id != goal.stream.id]
    else:
        rest = [e for e in ends if not is_heat(process, e[3])]
    total, used, lacking = 0.0, {}, []
    for stream, _, into, _ in rest:
        given = given_duty(process, stream, case)
        if given is None:
            lacking.append(stream.id)
            continue
        total += given[0] if into else -given[0]
        used[stream.id] = [given[0], into]
    return total, used, lacking


# -- the models' duties -------------------------------------------------------------------------


def _batch_basis(
    terms: dict[str, float],
    dosed: bool | None = None,
    charged: bool = False,
    agitated: bool = False,
) -> str:
    """The basis of a batch's duty: :data:`BATCH_BASIS`, or with the terms of ADR 0063 it
    holds (a heat of solution, the charge's heat-up) and those of ADR 0075 (*charged*: the
    charge's heat of solution; *agitated*: the agitator's power, its own text after it);
    with the vent's vapour (ADR 0062) :data:`VENT_VAPOUR_BASIS` after it. *dosed*: whether
    the doses' heat of solution is in the term ``solution`` (None: whether that term is)."""
    solution = "solution" in terms if dosed is None else dosed
    heat_up = "charge heat-up" in terms
    vent = VENT_VAPOUR_BASIS if "vent vapour" in terms else ""
    if not (solution or heat_up or charged or agitated):
        return BATCH_BASIS + vent
    held = "the heat its reactions release over the batch, the doses warmed to the batch's "
    held += "temperature"
    if solution:
        held += " and their heat of solution as they mix in"
    if charged:
        held += ", the charged components' heat of solution as they dissolve"
    if heat_up:
        held += ", the charge heated from its inlet temperature to the batch's"
    left = "" if heat_up else "the charge's heat-up, "
    if not solution:
        left += (
            "the heat of absorption and the doses' heat of solution, "
            if charged
            else "the heats of absorption and solution, "
        )
    return (
        f"isothermal batch: {held}, per hour of the flowsheet's flows; {left}"
        f"{'' if agitated else 'agitation and '}heat losses not included"
    ) + vent


#: What a batch's duty adds with its vent's vapour (ADR 0062).
VENT_VAPOUR_BASIS = (
    "; with the latent heat of the vapour the vent gas carries off and a returned "
    "condensate warmed back (ADR 0062)"
)


def batch_duty(node: Any, result: Any, process: Any = None, case: str | None = None) -> ModelDuty:
    """The duty of batch or semi-batch *node* from its solution (:class:`.TankResult`); with
    *process* and *case*, the vessel's metal too (ADR 0063, :func:`with_metal`)."""
    model = node.reactor
    if getattr(node.batch, "heat", "isothermal") == "adiabatic":
        return ModelDuty(node.id, model, None, missing=["an adiabatic batch exchanges no heat"])
    if result.heat_terms is None:
        return ModelDuty(node.id, model, None, basis=BATCH_BASIS, missing=result.heat_missing)
    terms = {k: v / 3600.0 for k, v in result.heat_terms.items()}
    solutions = [
        d.heat_of_solution.model_dump(mode="json", exclude=NOT_INPUTS)
        for d in getattr(node.batch, "dosing", ())
        if d.heat_of_solution is not None
    ]
    charged = getattr(node.batch, "heat_of_solution", None)
    power = getattr(node.batch, "agitator_power", None)
    basis = (
        _batch_basis(terms)
        if charged is None and power is None  # as in 1.12.0
        else _batch_basis(terms, bool(solutions), charged is not None, power is not None)
    )
    duty = ModelDuty(node.id, model, sum(terms.values()), terms, basis)
    if solutions:  # the duty's, not an isothermal batch's outlets (their fingerprint)
        duty.inputs["heat_of_solution"] = solutions
    if charged is not None:  # ADR 0075: the charge's, as it dissolved
        duty.inputs["charge_heat_of_solution"] = charged.model_dump(mode="json", exclude=NOT_INPUTS)
    if power is not None and _agitation(process, case, duty, power, result.time):
        return duty
    if not getattr(node.batch, "heat_up", False):
        # the model holds the batch at its temperature from the start: neither the content's
        # heat-up nor the metal's is in its duty (the recipe's heat operation holds both)
        return _metal_left_out(process, node, case, duty)
    duty.inputs["heat_up"] = True
    port = getattr(node.batch, "heat_up_port", None)
    if port is not None:  # it moves the heat-up off the rest's stream (ADR 0075)
        duty.inputs["heat_up_port"] = port
    temperatures = (getattr(result, "charge_temperature", None), result.temperature)
    return with_metal(process, node, case, duty, temperatures)


def _agitation(process: Any, case: str | None, duty: ModelDuty, power: Any, seconds: float) -> bool:
    """*duty* with the term ``agitation`` (ADR 0075): the agitator's *power* (kW) over the
    model's *seconds* per batch ends as heat in the content, over the batch's hours of flows
    (process/recipe.yaml). False when added; True when *duty* is left not known (no recipe,
    or its batch's hours not known)."""
    from chemeascode.domains.process.recipe import hours_per_batch

    try:
        hours = hours_per_batch(process, case) if process is not None and case else None
    except ValueError as failure:
        _unknown(duty, f"the batch's hours for the agitator's power: {failure}")
        return True
    if not hours:
        _unknown(duty, "the batch's hours of flows (process/recipe.yaml) for the agitator's power")
        return True
    term = -power.value * seconds / (hours * 3600.0)
    duty.terms_kW["agitation"] = term
    duty.heat_kW += term
    duty.basis += f"; the agitator's {power.value:g} kW over the model's {seconds / 3600:.4g} h"
    duty.inputs["agitator_power"] = {"kW": power.value, "hours": hours}
    return False


#: The terms of a batch's duty that go on its ``heat_up_port`` stream (ADR 0075).
HEAT_UP_TERMS = ("charge heat-up", "vessel metal")


def split_heat_up(duty: ModelDuty) -> tuple[ModelDuty, ModelDuty]:
    """*duty* of a batch with ``heat_up_port`` (ADR 0075) as (the rest, on its energy_port or
    one heat stream; the charge's heat-up and the vessel's metal, on the heat-up port's)."""
    if duty.heat_kW is None:
        missing = list(duty.missing)
        return duty, ModelDuty(duty.node, "heat-up", None, basis=duty.basis, missing=missing)
    up = {k: v for k, v in duty.terms_kW.items() if k in HEAT_UP_TERMS}
    rest = {k: v for k, v in duty.terms_kW.items() if k not in HEAT_UP_TERMS}
    basis = "the charge heated from its inlet temperature to the batch's"
    if "vessel metal" in up:
        basis += ", with the vessel's metal"
    first = ModelDuty(
        duty.node, duty.model, sum(rest.values()), rest, duty.basis, inputs=dict(duty.inputs)
    )
    first.basis += "; the heat-up on its own stream (heat_up_port)"
    second = ModelDuty(duty.node, "heat-up", sum(up.values()), up, basis, inputs=dict(duty.inputs))
    return first, second


def heat_up_target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream a batch's heat-up goes on (``batch.heat_up_port``, ADR 0075), or None
    and why ('' without the port)."""
    port = getattr(getattr(node, "batch", None), "heat_up_port", None)
    if port is None:
        return None, ""
    at = [e for e in _energy_ends(process, node) if e[1] == port]
    if not at:
        return None, f"no energy stream at its heat_up_port {port}"
    stream, _, into, _ = at[0]
    return Target(stream, port, into, "batch.heat_up_port"), ""


def dryer_target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream a dryer's duty is compared against (``dryer.energy.port``, ADR 0057),
    or None and why ('' without the port)."""
    port = getattr(getattr(getattr(node, "dryer", None), "energy", None), "port", None)
    if port is None:
        return None, ""
    at = [e for e in _energy_ends(process, node) if e[1] == port]
    if not at:
        return None, f"no energy stream at its energy.port {port}"
    stream, _, into, _ = at[0]
    return Target(stream, port, into, "dryer.energy.port"), ""


def _metal_left_out(
    process: Any,
    node: Any,
    case: str | None,
    duty: ModelDuty,
    why: str = "the batch is at its temperature from the start (heat_up)",
) -> ModelDuty:
    """*duty* of a batch without ``heat_up``, or of a still at constant volatility, in a recipe
    vessel with ``metal_heat_capacity``: its basis says the metal is not in it and *why*
    (ADR 0063); unchanged otherwise."""
    if process is None or case is None:
        return duty
    from chemeascode.domains.process.recipe import metal_of

    try:
        found = metal_of(process, node.id, case)
    except ValueError:
        return duty
    if found is not None:
        duty.basis += f"; the vessel's metal ({found[2]}) not included: {why}"
    return duty


#: What a still's duty holds with ``heat_up`` (ADR 0063).
STILL_HEAT_UP_BASIS = (
    "batch still: the latent heat of what boils up (heat_of_vaporization) and the charge heated "
    "from its inlet temperature to its bubble point (liquid_heat_capacity), per hour of the "
    "flowsheet's flows; the content's sensible rise while it boils and heat losses not included"
)
#: What a solvent swap's duty holds with ``heat_up`` (ADR 0063).
SWAP_HEAT_UP_BASIS = (
    "solvent swap: the latent heat of what boils up (heat_of_vaporization), the charge heated "
    "from its inlet temperature to its bubble point and the feed from its inlet temperature to "
    "the still's as it mixes in (liquid_heat_capacity), per hour of the flowsheet's flows; the "
    "content's sensible rise while it boils and heat losses not included"
)


def still_duty(node: Any, result: Any, process: Any = None, case: str | None = None) -> ModelDuty:
    """The duty of batch still *node* from its solution (:class:`.StillResult`): the energy of
    a batch over its hours of flows; with ``still.heat_up`` the charge's heat-up to its bubble
    point, and with *process* and *case* the vessel's metal (ADR 0063)."""
    heat_up = getattr(node.still, "heat_up", False)
    swap = getattr(node.still, "feed", None) is not None
    basis = (SWAP_HEAT_UP_BASIS if swap else STILL_HEAT_UP_BASIS) if heat_up else STILL_BASIS
    if result.energy is None or not result.hours:
        missing = [n for n in result.notes if n.startswith("no duty")] or [
            "the heat_of_vaporization of the volatile components"
        ]
        return ModelDuty(node.id, "still", None, basis=basis, missing=missing)
    heat = result.energy / (result.hours * 3600.0)
    duty = ModelDuty(node.id, "still", heat, {"boil-up": heat}, basis)
    if heat_up:
        feed_heat = getattr(result, "feed_heat_up", None)
        if result.heat_up is None or (swap and feed_heat is None):
            what = "the charge's and the feed's heat-up" if swap else "the charge's heat-up"
            missing = [f"{what} (still.heat_up): {result.heat_up_missing}"]
            return ModelDuty(node.id, "still", None, basis=basis, missing=missing)
        duty.terms_kW["charge heat-up"] = result.heat_up / (result.hours * 3600.0)
        if swap:
            duty.terms_kW["feed heat-up"] = feed_heat / (result.hours * 3600.0)
        duty.heat_kW = sum(duty.terms_kW.values())
        duty.inputs["heat_up"] = True
        if process is not None:
            comps = process.components()
            duty.inputs["liquid_heat_capacity"] = {
                n: getattr(comps.get(n), "liquid_heat_capacity", None)
                for n in sorted({*result.charge, *result.fed})
            }
    if lacking := _still_extras(node.still, result, duty, process):
        return _unknown(duty, lacking)
    if getattr(getattr(node.still, "volatility", None), "model", None) == "constant":
        # no temperature modelled (ADR 0063): the boil-up's duty, the metal left out
        return _metal_left_out(
            process, node, case, duty, "a still at constant volatility models no temperature"
        )
    # the metal follows the content: from the charge's temperature with its heat-up, else
    # from the bubble point the model starts at; a charge at or above its bubble point takes
    # no heat-up (its flash is not modelled), so neither does the metal
    start, end = result.temperatures or (None, None)
    if heat_up:
        charged = result.charge_temperature
        start = charged if charged is None or start is None else min(charged, start)
    return with_metal(process, node, case, duty, (start, end))


def _still_extras(spec: Any, result: Any, duty: ModelDuty, process: Any) -> str:
    """ADR 0075's terms of a still's *duty*: the content's ``sensible rise`` while it boils
    (``sensible_heat``), the ``heat losses`` over the boil-up (``heat_loss``) and the
    ``agitation`` its agitator's power puts in over the boil-up's time (``agitator_power``),
    each over the batch's hours of flows; what is missing ('' when nothing is)."""
    per_hour = result.hours * 3600.0
    if getattr(spec, "sensible_heat", False):
        if result.sensible_rise is None:
            return f"the content's sensible rise (still.sensible_heat): {result.sensible_missing}"
        duty.terms_kW["sensible rise"] = result.sensible_rise / per_hour
        duty.basis = duty.basis.replace(
            "the content's sensible rise while it boils and heat losses not included",
            "heat losses not included",
        )
        duty.basis += "; the content's sensible heat as its bubble point rises while it boils"
        duty.inputs["sensible_heat"] = True
        if process is not None:
            comps = process.components()
            duty.inputs["sensible_heat_capacity"] = {
                n: getattr(comps.get(n), "liquid_heat_capacity", None)
                for n in sorted({*result.charge, *result.fed})
            }
    loss = getattr(spec, "heat_loss", None)
    if loss is not None and result.heat_loss is not None:
        duty.terms_kW["heat losses"] = result.heat_loss / per_hour
        duty.basis = duty.basis.replace(" and heat losses not included", " not included")
        duty.basis = duty.basis.replace("; heat losses not included", "")
        duty.basis += (
            f"; heat lost over the boil-up, UA {loss.ua:g} W/K to {loss.ambient_temperature:g} K"
        )
        duty.inputs["heat_loss"] = loss.model_dump(mode="json", exclude=NOT_INPUTS)
    power = getattr(spec, "agitator_power", None)
    if power is not None:
        duty.terms_kW["agitation"] = -power.value * result.time / per_hour
        duty.basis += f"; the agitator's {power.value:g} kW over the boil-up's time"
        duty.inputs["agitator_power"] = power.value
    if {"sensible rise", "heat losses", "agitation"} & set(duty.terms_kW):
        duty.heat_kW = sum(duty.terms_kW.values())
    return ""


def still_condenser_duty(node: Any, result: Any) -> ModelDuty:
    """The duty of batch still *node*'s condenser from its solution: minus its boil-up's latent
    heat (what boils up is condensed, the reflux with the distillate); the charge's heat-up
    and the vessel's metal (ADR 0063) stay in the pot and are not condensed."""
    if result.energy is None or not result.hours:
        boil = still_duty(node, result)
        return ModelDuty(
            node.id, "condenser", None, basis=STILL_CONDENSER_BASIS, missing=boil.missing
        )
    heat = result.energy / (result.hours * 3600.0)
    return ModelDuty(node.id, "condenser", -heat, {"condensation": -heat}, STILL_CONDENSER_BASIS)


def crystallizer_duty(
    node: Any, result: Any, process: Any = None, case: str | None = None
) -> ModelDuty:
    """The duty of crystallizer *node* from its solution (:class:`.TrainResult`); with
    *process* and *case*, the vessel's metal too (ADR 0063)."""
    energy = result.energy
    if energy is None:
        return ModelDuty(node.id, "crystallizer", None, missing=["crystallizer.energy"])
    if energy.get("duty_kW") is None:
        return ModelDuty(
            node.id, "crystallizer", None, basis="", missing=list(energy.get("missing", []))
        )
    terms = {
        name: energy[f"{name}_kJ_h"] / 3600.0
        for name in ("sensible", "crystallization", "evaporation")
    }
    duty = ModelDuty(node.id, "crystallizer", energy["duty_kW"], terms, energy["basis"])
    temperatures = (energy.get("feed_temperature_K"), energy.get("temperature_K"))
    return with_metal(process, node, case, duty, temperatures)


def with_metal(
    process: Any,
    node: Any,
    case: str | None,
    duty: ModelDuty,
    temperatures: tuple[float | None, float | None],
) -> ModelDuty:
    """*duty* with the term ``vessel metal`` (ADR 0063) where *node* runs in a recipe vessel
    that gives ``metal_heat_capacity``: the metal follows the content over the model, from
    the first to the second of *temperatures* (K) each batch, ``C_m (T_1 - T_0)`` over the
    batch's hours of flows. Unchanged without *process*, without such a vessel, or with no
    change of temperature; not known (``missing``) when the temperatures or the batch's hours
    are not."""
    if process is None or case is None or duty.heat_kW is None:
        return duty
    from chemeascode.domains.process.recipe import metal_of

    try:
        found = metal_of(process, node.id, case)
    except ValueError as failure:
        return _unknown(duty, f"the batch's hours for the vessel's metal: {failure}")
    if found is None:
        return duty
    metal, hours, procedure = found
    start, end = temperatures
    if start is None or end is None:
        return _unknown(
            duty,
            f"the {duty.model}'s temperatures for the vessel's metal ({procedure}): its inlet's "
            "and its own" + (" (volatility raoult)" if duty.model == "still" else ""),
        )
    if abs(end - start) <= 1e-9:
        return duty
    term = metal * (end - start) / (hours * 3600.0)
    duty.terms_kW["vessel metal"] = term
    duty.heat_kW += term
    duty.basis += (
        f"; the vessel's metal ({procedure}, {metal:g} kJ/K) from {start:.5g} to {end:.5g} K "
        "each batch"
    )
    duty.inputs["vessel_metal"] = {
        "heat_capacity": metal,
        "hours": hours,
        "temperatures": [start, end],
    }
    return duty


def _unknown(duty: ModelDuty, missing: str) -> ModelDuty:
    duty.heat_kW, duty.terms_kW, duty.missing = None, {}, [missing]
    return duty


def _stream_temperature(process: Any, stream: Any, case: str) -> float | None:
    from chemeascode.foundation.units import to_kelvin

    q = getattr(stream.state.get(case), "temperature", None)
    return to_kelvin(q.value, q.unit or process.flowsheet.units.temperature) if q else None


def _sensible(
    process: Any, stream: Any, case: str, moles: dict[str, float], t_from: float, t_to: float
) -> tuple[float, list[str]]:
    """kJ/h to bring the *moles* (kmol/h) of *stream* from *t_from* to *t_to* K: each
    component's liquid_heat_capacity, or its ideal-gas enthalpy (a stream said to be vapour, or
    a component without a liquid one); and the components with neither."""
    if abs(t_to - t_from) <= 1e-9:
        return 0.0, []
    comps = process.components()
    phase = getattr(stream.state.get(case), "phase", None)
    vapour = phase is not None and phase.value == "vapor"
    total, lacking = 0.0, []
    for name, n in moles.items():
        if not n:
            continue
        c = comps.get(name)
        cp = getattr(c, "liquid_heat_capacity", None)
        gas = getattr(c, "ideal_gas", None)
        if gas is not None and (vapour or not cp):
            total += n * (gas.enthalpy(t_to) - gas.enthalpy(t_from))
        elif cp:
            total += n * cp * (t_to - t_from)
        else:
            lacking.append(name)
    return total, lacking


def conversion_duty(process: Any, node: Any, case: str) -> tuple[ModelDuty, dict[str, Any]]:
    """The duty of conversion step *node* from its streams in *case* (see the module
    docstring), and what it depends on besides the streams' values (the fingerprint)."""
    from chemeascode.domains.chemistry.thermochemistry import missing, mixture_enthalpy, outside
    from chemeascode.domains.process.model import balance_of
    from chemeascode.domains.process.reactors import _moles

    reactions, unknown = process.reactions_of(node.id)
    duty = ModelDuty(node.id, "conversion", None)
    if unknown:
        duty.missing = ["the undeclared reactions " + ", ".join(unknown)]
        return duty, {}
    balance = balance_of(process, node.id, case)
    streams = {s.id: s for s in process.flowsheet.streams}
    ins = [streams[s] for s in balance.streams_in]
    outs = [streams[s] for s in balance.streams_out]
    moles = {s.id: _moles(process, s, case) for s in ins + outs}
    temps = {s.id: _stream_temperature(process, s, case) for s in ins + outs}
    if not ins or not outs or any(m is None for m in moles.values()):
        duty.missing = ["the compositions, flows and molar masses of its streams"]
        return duty, {}
    if any(t is None for t in temps.values()):
        duty.missing = ["the temperature of every stream"]
        return duty, {}
    if len(balance.extents) != len(reactions):
        duty.missing = ["the extents of its reactions (" + balance.status + " balance)"]
        return duty, {}
    data = process.ideal_gas()
    names = sorted({n for m in moles.values() for n in m})  # type: ignore[union-attr]
    phases = {
        s.id: p.value if (p := getattr(s.state.get(case), "phase", None)) else None
        for s in ins + outs
    }
    work, others, no_duty = other_energy(process, node, case)
    if no_duty:
        duty.missing = [
            "the duty of its other energy stream(s) " + ", ".join(no_duty) + " (electricity, "
            "work: what they bring in is not heat; or name the heat stream in energy_port)"
        ]
        return duty, {}
    extra: dict[str, Any] = {"reactions": [r.inputs_dump() for r in reactions]}
    if others:
        extra["other_energy"] = others
    liquid = any(p in ("liquid", "two-phase") for p in phases.values()) or any(
        r.phase in ("liquid", "mixed") for r in reactions
    )
    if not liquid and not missing(names, data):
        beyond = [n for s in ins + outs for n in outside(list(moles[s.id]), data, temps[s.id])]  # type: ignore[arg-type]
        if beyond:
            duty.missing = ["a temperature inside the ideal_gas range of " + ", ".join(beyond)]
            return duty, {}
        h_out = sum(mixture_enthalpy(moles[s.id], data, temps[s.id]) for s in outs)  # type: ignore[arg-type]
        h_in = sum(mixture_enthalpy(moles[s.id], data, temps[s.id]) for s in ins)  # type: ignore[arg-type]
        extra["ideal_gas"] = {n: data[n].model_dump(mode="json") for n in names}
        extra["phases"] = phases
        duty.terms_kW = {"enthalpy": h_out - h_in}
        duty.basis = IDEAL_GAS_BASIS
        duty = _less_work(duty, work, others)
        return _conversion_metal(process, node, case, duty, ins, outs, moles, temps), extra  # type: ignore[arg-type]
    if lacking := [r.id for r in reactions if r.heat_of_reaction is None]:
        duty.missing = ["the heat_of_reaction of " + ", ".join(lacking)]
        return duty, {}
    at = {r.id: r.heat_of_reaction.temperature for r in reactions}  # type: ignore[union-attr]
    if len(set(at.values())) > 1:
        duty.missing = [
            "the heats of reaction at one temperature ("
            + ", ".join(f"{r} at {t:g} K" for r, t in at.items())
            + ")"
        ]
        return duty, {}
    t_r = next(iter(at.values()))
    if changing := _phase_changes(ins, outs, moles, phases):  # type: ignore[arg-type]
        duty.missing = [
            "the latent heat of " + ", ".join(changing) + " (vapour on one side of the step, "
            "liquid on the other: the model has no phase change; give the stream's duty)"
        ]
        return duty, {}
    reaction = sum(
        balance.extents[r.id] * r.heat_of_reaction.value  # type: ignore[union-attr]
        for r in reactions
    )
    sensible, lacking_cp = 0.0, []
    for s in ins + outs:
        into = s in ins
        heat, lack = _sensible(
            process,
            s,
            case,
            moles[s.id],  # type: ignore[arg-type]
            temps[s.id] if into else t_r,  # type: ignore[arg-type]
            t_r if into else temps[s.id],  # type: ignore[arg-type]
        )
        sensible += heat
        lacking_cp += [n for n in lack if n not in lacking_cp]
    if lacking_cp:
        duty.missing = [
            "the liquid_heat_capacity (or ideal_gas data) of " + ", ".join(sorted(lacking_cp))
        ]
        return duty, {}
    comps = process.components()
    extra["heat_capacity"] = {
        n: [
            getattr(comps.get(n), "liquid_heat_capacity", None),
            g.model_dump(mode="json") if (g := data.get(n)) is not None else None,
        ]
        for n in names
    }
    extra["phases"] = phases
    duty.terms_kW = {"reaction": reaction / 3600.0, "sensible": sensible / 3600.0}
    duty.basis = CONVERSION_BASIS + (f" ({t_r:g} K)" if abs(t_r - 298.15) > 1e-9 else "")
    duty = _less_work(duty, work, others)
    return _conversion_metal(process, node, case, duty, ins, outs, moles, temps), extra  # type: ignore[arg-type]


def _conversion_metal(
    process: Any,
    node: Any,
    case: str,
    duty: ModelDuty,
    ins: list[Any],
    outs: list[Any],
    moles: dict[str, dict[str, float]],
    temps: dict[str, float],
) -> ModelDuty:
    """A conversion step's *duty* with ``vessel_metal`` (ADR 0075): the recipe vessel's metal
    follows the content from its inlets' to its outlets' temperature (each side's mean by heat
    capacity); unchanged without it."""
    if not getattr(node, "vessel_metal", False):
        return duty
    start = _mixed_temperature(process, ins, case, moles, temps)
    end = _mixed_temperature(process, outs, case, moles, temps)
    return with_metal(process, node, case, duty, (start, end))


def _mixed_temperature(
    process: Any,
    streams: list[Any],
    case: str,
    moles: dict[str, dict[str, float]],
    temps: dict[str, float],
) -> float | None:
    """K: the mean temperature of *streams*, weighted by their heat capacities (as
    :func:`_sensible` takes them, at each stream's temperature); one stream's own, or None
    when a heat capacity is not known."""
    if len({temps[s.id] for s in streams}) == 1:
        return temps[streams[0].id]
    total = weighted = 0.0
    for s in streams:
        heat, lacking = _sensible(process, s, case, moles[s.id], temps[s.id], temps[s.id] + 1.0)
        if lacking:
            return None
        total += heat
        weighted += heat * temps[s.id]
    return weighted / total if total > 0 else None


def _phase_changes(
    ins: list[Any],
    outs: list[Any],
    moles: dict[str, dict[str, float]],
    phases: dict[str, str | None],
) -> list[str]:
    """The components in a stream said to be vapour on one side of the step and in one said
    to be liquid on the other (their latent heat is not in the declared-heat path)."""

    def held(streams: list[Any], phase: str) -> set[str]:
        return {n for s in streams if phases[s.id] == phase for n, v in moles[s.id].items() if v}

    return sorted(
        (held(ins, "vapor") & held(outs, "liquid")) | (held(ins, "liquid") & held(outs, "vapor"))
    )


def _less_work(duty: ModelDuty, work: float, others: dict[str, Any]) -> ModelDuty:
    """*duty* with its terms summed into its heat, less the *work* (kW) its other energy
    streams bring in."""
    if others:
        duty.terms_kW["other energy streams"] = -work
        duty.basis += OTHER_BASIS + " (" + ", ".join(others) + ")"
    duty.heat_kW = sum(duty.terms_kW.values())
    return duty


# -- the comparison -----------------------------------------------------------------------------


def given_duty(process: Any, stream: Any, case: str) -> tuple[float, str] | None:
    """(kW, provenance) of *stream*'s duty in *case*; None when it has none in a known unit."""
    from chemeascode.domains.process.schema import DUTY_UNITS

    q = getattr(stream.state.get(case), "duty", None)
    if q is None:
        return None
    factor = DUTY_UNITS.get(q.unit or process.flowsheet.units.duty)
    return (q.value * factor, q.provenance) if factor is not None else None


def differs(process: Any, given: float, model: float) -> bool:
    """Whether *given* and *model* kW differ beyond the flowsheet's relative tolerance (as
    ``cheme.process-dryer-duty``)."""
    tol = process.flowsheet.tolerance
    return abs(given - model) > 1e-6 + tol.rel * max(abs(given), abs(model))


def duty_text(duty: ModelDuty) -> str:
    """One line of *duty* for the reports."""
    if duty.heat_kW is None:
        return f"{duty.model} duty: not known ({'; '.join(duty.missing)})"
    terms = ", ".join(f"{k} {v:.6g}" for k, v in duty.terms_kW.items())
    return f"{duty.model} duty {duty.heat_kW:.6g} kW into the step, year average ({terms} kW)"


def report_entry(
    process: Any,
    node: Any,
    case: str,
    duty: ModelDuty,
    vent_condenser: bool = False,
    heat_up: bool = False,
) -> dict[str, Any]:
    """*duty* as ``cheme process reactors`` reports it: the model's duty and its energy stream
    (the stream's duty now, and what the model gives it in the stream's direction); with
    *vent_condenser*, a batch's vent condenser's on its own stream (ADR 0062); with *heat_up*,
    a batch's heat-up on its ``heat_up_port`` stream (ADR 0075)."""
    found = duty.entry()
    if vent_condenser:
        goal, why = vent_condenser_target(process, node)
    elif heat_up:
        goal, why = heat_up_target(process, node)
    else:
        goal, why = target(process, node)
    found["stream"] = None
    found["stream_note"] = why
    if goal is not None:
        given = given_duty(process, goal.stream, case)
        found["stream"] = {
            "id": goal.stream.id,
            "port": goal.port,
            "direction": "in" if goal.into else "out",
            "chosen": goal.chosen,
            "duty_kW": given[0] if given else None,
            "provenance": given[1] if given else None,
            "model_kW": goal.duty(duty.heat_kW) if duty.heat_kW is not None else None,
        }
    return found


def report_lines(entry: dict[str, Any]) -> list[str]:
    """The lines ``cheme process reactors`` prints for a model duty (:func:`report_entry`)."""
    duty = ModelDuty("", entry["model"], entry["heat_in_kW"], entry["terms_kW"])
    duty.missing = entry["missing"]
    stream = entry["stream"]
    if duty.heat_kW is None and stream is None and not entry["stream_note"]:
        return []  # no duty, and no stream wants one: nothing to say
    line = "  " + duty_text(duty)
    if stream is not None:
        now = (
            f"{stream['duty_kW']:.6g} kW {stream['provenance']}"
            if stream["duty_kW"] is not None
            else "no duty yet"
        )
        model = f", the model {stream['model_kW']:.6g} kW" if stream["model_kW"] is not None else ""
        line += f"; on {stream['id']} ({stream['direction']}, {now}{model})"
    elif entry["stream_note"]:
        line += f"; on no stream: {entry['stream_note']}"
    return [line]


# -- rules (cheme validate) ---------------------------------------------------------------------


def rules(process: Any) -> list[Any]:
    """``cheme.process-energy-port`` findings: an ``energy_port`` that names no energy port of
    its block or step (error), or sits on one no model gives a duty (warning); and
    ``cheme.process-duty`` (:func:`duty_rules`)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    findings = []
    fs = process.flowsheet
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        warm = getattr(getattr(node, "batch", None), "heat_up_port", None)
        if warm is not None:  # ADR 0075
            port = next((p for p in node.ports if p.id == warm), None)
            if port is None or port.kind != "energy" or warm == node.energy_port:
                findings.append(
                    Finding(
                        FLOWSHEET_FILE,
                        "error",
                        "cheme.process-energy-port",
                        f"{node.id}: batch.heat_up_port {warm} is no energy port of it"
                        if warm != node.energy_port
                        else f"{node.id}: batch.heat_up_port {warm} is its energy_port too",
                        line=_yaml_line(
                            process.flowsheet_doc, [key, index, "batch", "heat_up_port"]
                        ),
                        ids=[node.id],
                        hint="name the energy port of the heat-up's own stream (steam), apart "
                        "from the energy_port of the rest of the model's duty",
                    )
                )
        if getattr(node, "vessel_metal", False):  # ADR 0075
            findings += _vessel_metal_rules(process, node, [key, index, "vessel_metal"])
        port_id = getattr(node, "energy_port", None)
        if port_id is None:
            continue
        line = _yaml_line(process.flowsheet_doc, [key, index, "energy_port"])
        port = next((p for p in node.ports if p.id == port_id), None)
        if port is None or port.kind != "energy":
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "error",
                    "cheme.process-energy-port",
                    f"{node.id}: energy_port {port_id} is no energy port of it",
                    line=line,
                    ids=[node.id],
                    hint="name the port (kind: energy) of the stream that carries its heat",
                )
            )
        elif duty_model(node) is None or (key == "blocks" and process.inside(node.id)):
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "warning",
                    "cheme.process-energy-port",
                    f"{node.id}: energy_port {port_id}, but no model of it gives a duty",
                    line=line,
                    ids=[node.id],
                    hint="energy_port is for a batch or semi-batch reactor, a still:, a "
                    "crystallizer: or a conversion step (without steps inside); remove it",
                )
            )
    return findings + duty_rules(process)


def _vessel_metal_rules(process: Any, node: Any, at: list[Any]) -> list[Any]:
    """``vessel_metal`` (ADR 0075) on a node that is no conversion step, or in no recipe vessel
    with ``metal_heat_capacity`` (warnings: it changes nothing)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.recipe import vessel_metal
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    if duty_model(node) != "conversion":
        why = "it is no conversion step (a batch, still or crystallizer takes the metal itself)"
    elif vessel_metal(process, node.id) is None:
        why = "no recipe vessel with metal_heat_capacity holds it"
    else:
        return []
    return [
        Finding(
            FLOWSHEET_FILE,
            "warning",
            "cheme.process-duty",
            f"{node.id}: vessel_metal, but {why}",
            line=_yaml_line(process.flowsheet_doc, at),
            ids=[node.id],
            hint="vessel_metal is for a conversion step in a unit procedure's vessel with "
            "metal_heat_capacity (process/recipe.yaml); remove it",
        )
    ]


def _recipe_streams(process: Any, taken: dict[str, list[Any]]) -> dict[str, list[Any]]:
    """The energy streams recipe operations write their heat on (``stream:``, ADR 0075) that no
    model's duty goes on (*taken*), as :func:`duty_rules` groups them."""
    from chemeascode.domains.process.recipe import load_recipe

    recipe = load_recipe(process.root)[0]
    streams = {s.id: s for s in process.flowsheet.streams if s.kind == "energy"}
    found: dict[str, list[Any]] = {}
    for up in recipe.unit_procedures if recipe is not None else ():
        for op in up.operations:
            if op.stream in streams and op.stream not in taken:
                found.setdefault(op.stream, [streams[op.stream]])
    return found


def duty_rules(process: Any) -> list[Any]:
    """``cheme.process-duty`` warnings of ``cheme validate``, as ``cheme process propagate``
    gives them: a given or assumed duty the model differs from beyond the flowsheet's relative
    tolerance, and two models that give one stream different duties. Derived (propagate's
    :func:`~.propagate.derivation`, which the staleness check shares) only in a case where a
    modelled block's or step's energy stream holds a duty propagate did not write, or an
    energy stream joins two modelled nodes."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.propagate import derivation, ours
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    fs = process.flowsheet
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks) if not process.inside(n.id)]
    keys = {n.id: [key, i] for key, i, n in nodes}
    goals: dict[str, list[Any]] = {}
    for _, _, node in nodes:
        if duty_model(node) is not None:
            # the jacket's or reboiler's, a still's condenser's (ADR 0061) and a vent
            # condenser's (ADR 0062): each on its own stream
            for find in (target, still_condenser_target, vent_condenser_target, heat_up_target):
                goal, _ = find(process, node)
                if goal is not None:
                    goals.setdefault(goal.stream.id, []).append(goal.stream)
    goals |= _recipe_streams(process, goals)
    cases = [fs.default_case()] if any(len(g) > 1 for g in goals.values()) else []
    for group in goals.values():
        stream = group[0]
        for case, state in stream.state.items():
            q = getattr(state, "duty", None)
            if (len(group) > 1 or (q is not None and not ours(q))) and case not in cases:
                cases.append(case)
    findings = []
    default = fs.default_case()
    for case in cases:
        for node, level, message, hint, what in derivation(process, case).duties:
            if what not in ("given", "models"):
                continue
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    level,  # type: ignore[arg-type]
                    "cheme.process-duty",
                    message if case == default else f"{message} (case {case})",
                    line=_yaml_line(process.flowsheet_doc, keys.get(node, [])),
                    ids=[node],
                    hint=hint,
                )
            )
    return findings
