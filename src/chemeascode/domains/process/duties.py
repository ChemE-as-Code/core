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
  of flows);
- a **crystallizer** with ``energy:`` (:mod:`.crystallization`): its lumped duty (the feed's
  sensible heat, the heat of crystallization, the solvent evaporated);
- a **conversion step** (``reactions:`` with conversions, ``reactor: conversion`` or a
  ``selectivity:``): with every reaction's ``heat_of_reaction``, the reactions at the outlet's
  temperature (the heat as declared, as the batch models take it) and each stream's sensible
  heat to or from it, ``Q = sum_j dHr_j xi_j + sum_in n cp (T_r - T_in) + sum_out n cp (T_out -
  T_r)`` (a liquid_heat_capacity, or the ideal-gas enthalpy for a stream said to be vapour or a
  component with no liquid one); else, a gas-phase step whose components all have ideal-gas
  data, ``H(out) - H(in)`` on the elements basis; else nothing.

The duty goes on the energy stream at the node's ``energy_port``, else on its one heat stream:
an energy stream whose other end is a heating or cooling utility (steam, hot oil, fired heat,
cooling water, air cooling, refrigerant) or another block or step; electricity, fuel and
terminals without a utility are not heat. An energy stream's ``duty`` is positive in its own
direction (:mod:`.energy`): a stream into the node carries ``Q``, a stream out of it ``-Q``.
A model whose heat flows against the stream's direction is reported, never written as a
negative duty.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
CONVERSION_BASIS = (
    "conversion step: the declared heats of reaction at the outlet's temperature, each stream "
    "brought to or from it at its heat capacity; heats of mixing not included"
)
IDEAL_GAS_BASIS = "conversion step: H(out) - H(in) of ideal gases on the elements basis"


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
    """Whether an energy stream to or from *other* is heat: a block or step, or a terminal
    whose utility is a heating or cooling one."""
    if other is None:
        return False
    if process.kinds.get(other) in ("block", "step"):
        return True
    utility = getattr(process.nodes.get(other), "utility", None)
    return utility is not None and utility.kind in HEAT_UTILITIES


def target(process: Any, node: Any) -> tuple[Target | None, str]:
    """The energy stream *node*'s model duty goes on, or None and why ('' when the node has no
    heat stream at all: nothing to say)."""
    ends = _energy_ends(process, node)
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
    return None, ""


# -- the models' duties -------------------------------------------------------------------------


def batch_duty(node: Any, result: Any) -> ModelDuty:
    """The duty of batch or semi-batch *node* from its solution (:class:`.TankResult`)."""
    model = node.reactor
    if getattr(node.batch, "heat", "isothermal") == "adiabatic":
        return ModelDuty(node.id, model, None, missing=["an adiabatic batch exchanges no heat"])
    if result.heat_terms is None:
        return ModelDuty(node.id, model, None, basis=BATCH_BASIS, missing=result.heat_missing)
    terms = {k: v / 3600.0 for k, v in result.heat_terms.items()}
    return ModelDuty(node.id, model, sum(terms.values()), terms, BATCH_BASIS)


def still_duty(node: Any, result: Any) -> ModelDuty:
    """The duty of batch still *node* from its solution (:class:`.StillResult`): the energy of
    a batch over its hours of flows."""
    if result.energy is None or not result.hours:
        missing = [n for n in result.notes if n.startswith("no duty")] or [
            "the heat_of_vaporization of the volatile components"
        ]
        return ModelDuty(node.id, "still", None, basis=STILL_BASIS, missing=missing)
    heat = result.energy / (result.hours * 3600.0)
    return ModelDuty(node.id, "still", heat, {"boil-up": heat}, STILL_BASIS)


def crystallizer_duty(node: Any, result: Any) -> ModelDuty:
    """The duty of crystallizer *node* from its solution (:class:`.TrainResult`)."""
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
    return ModelDuty(node.id, "crystallizer", energy["duty_kW"], terms, energy["basis"])


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
    gas_phase = all(r.phase != "liquid" for r in reactions)
    extra: dict[str, Any] = {"reactions": [r.inputs_dump() for r in reactions]}
    if gas_phase and not missing(names, data):
        beyond = [n for s in ins + outs for n in outside(list(moles[s.id]), data, temps[s.id])]  # type: ignore[arg-type]
        if beyond:
            duty.missing = ["a temperature inside the ideal_gas range of " + ", ".join(beyond)]
            return duty, {}
        h_out = sum(mixture_enthalpy(moles[s.id], data, temps[s.id]) for s in outs)  # type: ignore[arg-type]
        h_in = sum(mixture_enthalpy(moles[s.id], data, temps[s.id]) for s in ins)  # type: ignore[arg-type]
        extra["ideal_gas"] = {n: data[n].model_dump(mode="json") for n in names}
        duty.heat_kW, duty.basis = h_out - h_in, IDEAL_GAS_BASIS
        duty.terms_kW = {"enthalpy": h_out - h_in}
        return duty, extra
    if lacking := [r.id for r in reactions if r.heat_of_reaction is None]:
        duty.missing = ["the heat_of_reaction of " + ", ".join(lacking)]
        return duty, {}
    t_out = {temps[s.id] for s in outs}
    t_r = temps[outs[0].id]
    assert t_r is not None
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
    extra["phases"] = {
        s.id: p.value if (p := getattr(s.state.get(case), "phase", None)) else None
        for s in ins + outs
    }
    duty.heat_kW = (reaction + sensible) / 3600.0
    duty.terms_kW = {"reaction": reaction / 3600.0, "sensible": sensible / 3600.0}
    duty.basis = CONVERSION_BASIS + (
        "" if len(t_out) == 1 else f"; the reactions at {t_r:g} K, the first outlet's"
    )
    return duty, extra


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


def report_entry(process: Any, node: Any, case: str, duty: ModelDuty) -> dict[str, Any]:
    """*duty* as ``cheme process reactors`` reports it: the model's duty and its energy stream
    (the stream's duty now, and what the model gives it in the stream's direction)."""
    found = duty.entry()
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
    its block or step (error), or sits on one no model gives a duty (warning)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    findings = []
    fs = process.flowsheet
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
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
    return findings
