"""``cheme process propagate --fill/--check``: compositions and flows through simple steps.

Derives missing stream values through steps (and blocks without steps inside) whose behaviour
is fully determined by their streams, by the DEXPI class:

- pass-through (compressing, cooling, heating, pumping, filtering, transporting, flow control;
  heat exchanging with one material stream in and one out): the outlet keeps the inlet's
  composition and flow, and the other way round;
- mixers (``Mixing`` and subclasses): the outlet flow is the sum of the inlet mass flows, its
  composition the flow-weighted mix (mole fractions where every molar mass is known);
- splitters (``SplittingMaterial``): every outlet keeps the inlet composition; an outlet's flow
  is the inlet flow times its ``split:`` fraction (step key, outlet port -> fraction), else the
  one missing flow is the remainder of the mass balance.

- conversion reactors (a step or block with ``reactions:``, each with a conversion: the node's
  ``conversion:`` or the reaction's own, and a key component): the outlet is the inlets'
  moles, every reaction converting its fraction of its key component's inlet flow at once
  (:func:`chemeascode.domains.chemistry.reactions.convert`); one material stream out.

- crystallizers and filters (a block or step with ``crystallizer:`` or ``solid_separation:``,
  one material stream in): the outlets from the inlet by
  :mod:`chemeascode.domains.process.crystallization` (solubility or imposed yield, the
  specified filter, the internal mother-liquor recycle).

- batch stills and solvent swaps (a block or step with ``still:``, its charge and a swap's
  feed in): the distillate cuts and the residue by :mod:`.batch_still` (Rayleigh).

Other separators, and reactors without conversions, are only checked (``cheme validate`` balances
them), never solved.
Derived values get provenance ``calculated``, source ``cheme process propagate: <rule>
<step> from <streams>`` and an input fingerprint. They never overwrite a given or assumed value
and become stale (``cheme.process-calculated-stale``) when their inputs change. The YAML is
edited in place: only the ``composition:`` and ``flow:`` entries of a state change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from chemeascode.domains.chemistry.equilibrium import (
    equilibrate,
    equilibrate_real,
    reaction_ln_k,
)
from chemeascode.domains.chemistry.reactions import convert
from chemeascode.domains.chemistry.thermochemistry import independent_reactions, missing, outside
from chemeascode.domains.chemistry.thermochemistry import ln_k as ln_k_of_stoichiometry
from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.domains.process.fill import PropsResult, _child, _dump, _flow, _last_line, _sig
from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.domains.process.reactors import equilibrium_conditions
from chemeascode.domains.process.schema import (
    FLOW_UNITS,
    CompositionValue,
    Quantity,
    State,
    StreamDef,
)
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import NOT_INPUTS, value_fingerprint, written_by
from chemeascode.foundation.schemas.run import AdapterResult, Solver, finding_dict
from chemeascode.foundation.units import to_kelvin, to_kpa_abs
from chemeascode.foundation.yamlsource import _yaml_line

SOURCE = "cheme process propagate"
FIELDS = ("composition", "flow")
#: What propagate writes: a fixed bed's outlet also gets its temperature and pressure.
WRITTEN = (*FIELDS, "temperature", "pressure")
#: DEXPI step classes (and their subclasses) by behaviour; the first match wins.
BEHAVIOUR = (
    ("reactor", ("ReactingChemicals",)),
    (
        "pass-through",
        (
            "Compressing",
            "Pumping",
            "Cooling",
            "RemovingThermalEnergy",
            "HeatingElectrical",
            "HeatingInFurnace",
            "ExchangingThermalEnergy",
            "Filtering",
            "TransportingMaterial",
            "RegulatingFlow",
            "LimitingFlow",
            "PreventingBackflow",
            "ShuttingOffFlow",
            "SteeringFlow",
            "GeneratingFlow",
        ),
    ),
    ("mixer", ("Mixing",)),
    ("splitter", ("SplittingMaterial",)),
    (
        "separator",
        (
            "Separating",
            "Absorbing",
            "Adsorbing",
            "Distilling",
            "Drying",
            "Evaporating",
            "Boiling",
            "Crystallizing",
            "Sieving",
            "Skimming",
        ),
    ),
)


def behaviour(class_name: str) -> str | None:
    """pass-through, mixer, splitter, separator or reactor for a DEXPI step class; None when
    the class does not say (e.g. ProcessStep)."""
    from chemeascode.domains.process.build import C, step_class

    cls = step_class(class_name)
    if cls is None:
        return None
    for kind, names in BEHAVIOUR:
        bases = tuple(b for b in (getattr(C, n, None) for n in names) if b is not None)
        if issubclass(cls, bases):
            return kind
    return None


def ours(value: Any) -> bool:
    """Whether *value* was written by propagate (and so may be rewritten)."""
    return written_by(value, SOURCE)


@dataclass
class Derivation:
    """What :func:`derive` found for one case."""

    #: (stream id, field) -> the derived value (provenance calculated, with fingerprint).
    values: dict[tuple[str, str], Any] = field(default_factory=dict)
    #: (node id, behaviour, streams lacking a value) for nodes it does not solve.
    unsolved: list[tuple[str, str, list[str]]] = field(default_factory=list)
    #: (node id, message) for reactors whose conversions cannot be applied.
    problems: list[tuple[str, str]] = field(default_factory=list)
    #: (node id, message) for crystallizers and filters that cannot be solved as declared.
    solids: list[tuple[str, str]] = field(default_factory=list)
    #: (node id, message) for batch stills that cannot be solved as declared.
    stills: list[tuple[str, str]] = field(default_factory=list)
    #: Sweeps through the nodes until nothing more could be derived (the last changed nothing).
    passes: int = 0


def _inputs(case: str, streams: list[StreamDef], extra: Any = None) -> str:
    data: dict[str, Any] = {"extra": extra}
    for s in streams:
        state = s.state.get(case)
        data[s.id] = {
            name: getattr(state, name).model_dump(mode="json", exclude=NOT_INPUTS)
            for name in FIELDS
            if state is not None and getattr(state, name) is not None
        }
    return value_fingerprint(data)


def _converted(
    process: Process, case: str, streams: list[StreamDef], components: list[str] | None = None
) -> dict[str, Any] | None:
    """What converting the flows of *streams* in *case* to kg/h (:func:`stream_flows`) took
    besides their own values, for the fingerprint of a value derived from the result: the molar
    masses of the components of every stream with a flow on a mole or normal-volume basis, and
    the normal conditions of a normal-volume flow. With *components* (a composition derived from
    the component mass flows, mixed in mole fractions by :func:`_mix`), also those of a mass flow
    with mole fractions and those of *components*. None when nothing was converted, so that a
    value derived from mass flows keeps the fingerprint it had before."""
    fs = process.flowsheet
    templates = process.templates()
    names: list[str] = list(components or [])
    normal = False
    for s in streams:
        state = s.state.get(case)
        if state is None or state.flow is None:
            continue
        basis = FLOW_UNITS.get(state.flow.unit or fs.units.flow, (None, 1.0))[0]
        comp = state.composition
        if basis not in ("mole", "normal_volume") and not (
            components is not None and comp is not None and comp.basis == "mole_fraction"
        ):
            continue
        normal |= basis == "normal_volume"
        template = templates.get(s.template or "")
        own = [*(template.components if template else []), *(comp.values if comp else [])]
        names += [n for n in own if n not in names]
    if not names and not normal:
        return None
    comps = process.components()
    extra: dict[str, Any] = {
        "molar_mass": {n: getattr(comps.get(n), "molar_mass", None) for n in sorted(names)}
    }
    if normal:
        nc = fs.units.normal_conditions
        extra["normal_conditions"] = nc.model_dump(mode="json") if nc is not None else None
    return extra


def derive(process: Process, case: str) -> Derivation:
    """Every value propagate derives in *case*, from the given and assumed values (values it
    wrote earlier are derived again, not used)."""
    fs = process.flowsheet.model_copy(deep=True)
    work = Process(process.root, process.materials, fs, reactions=process.reactions)
    work.catalysts = process.catalysts
    streams = {s.id: s for s in fs.streams if s.kind == "material"}
    for s in streams.values():
        state = s.state.get(case)
        if state is not None:
            for name in WRITTEN:
                if ours(getattr(state, name)):
                    setattr(state, name, None)
    nodes = [*fs.steps, *(b for b in fs.blocks if not work.inside(b.id))]
    at: dict[str, tuple[list[tuple[StreamDef, str]], list[tuple[StreamDef, str]]]] = {
        n.id: ([], []) for n in nodes
    }
    for s in streams.values():
        a, b = work.ends(s)
        if a is not None and a.node in at:
            at[a.node][1].append((s, a.port))
        if b is not None and b.node in at:
            at[b.node][0].append((s, b.port))
    found = Derivation()
    kinds = {
        n.id: "still"
        if n.still is not None
        else "crystallizer"
        if n.crystallizer is not None
        else "solid-separation"
        if n.solid_separation is not None
        else "reactor"
        if n.reactions or n.reactor
        else behaviour(n.class_)
        for n in nodes
    }

    def get(s: StreamDef, name: str) -> Any:
        state = s.state.get(case)
        return getattr(state, name) if state is not None else None

    def put(s: StreamDef, name: str, value: Any, rule: str, node: str, inputs, extra=None):
        if get(s, name) is not None:
            return False
        # a copied inlet value keeps neither its origin (a measurement, a vendor figure) nor its
        # uncertainty: the derived value is calculated, and correlated with the inlet
        value = value.model_copy(
            update={
                "provenance": "calculated",
                "source": f"{SOURCE}: {rule} {node} from {' '.join(i.id for i in inputs)}",
                "fingerprint": _inputs(case, inputs, extra),
                "origin": None,
                "uncertainty": None,
            }
        )
        s.state.setdefault(case, State())
        setattr(s.state[case], name, value)
        found.values[(s.id, name)] = value
        return True

    def kg_h(value: float) -> Quantity:
        unit = None if fs.units.flow == "kg/h" else "kg/h"
        return Quantity(value=_sig(value), unit=unit, provenance="calculated")

    comps = work.components()
    data = work.ideal_gas()

    def reactor(node: Any) -> tuple[str, list[Any], dict[str, float]] | None:
        """How reactor *node* is solved: its model, its reactions and (conversion) the
        conversion of each; None when it cannot be (an undeclared reaction, a conversion that
        is not known, an equilibrium without reactions)."""
        reactions, unknown = work.reactions_of(node.id)
        if unknown:
            return None
        model = getattr(node, "reactor", None)
        if model == "gibbs":
            return ("gibbs", [], {})
        if not reactions:
            return None
        if model in ("equilibrium", "pfr", "cstr", "batch", "semibatch"):
            return (model, reactions, {})
        if getattr(node, "selectivity", None) is not None:
            return ("selectivity", reactions, {})
        rates = {
            r.id: node.conversion.get(r.id, r.conversion.value if r.conversion else None)
            for r in reactions
        }
        if all(rates.values()):
            return ("conversion", reactions, rates)  # type: ignore[return-value]
        return None

    reactors = {n.id: reactor(n) for n in nodes if kinds[n.id] == "reactor"}

    def conditions(node: Any, ins: list[StreamDef], out: StreamDef) -> tuple[float, float]:
        """Temperature (K, the outlet's plus the approach) and pressure (kPa) of an
        equilibrium (:func:`equilibrium_conditions`)."""
        kelvin, kpa = equilibrium_conditions(fs.units, case, ins, out)
        return kelvin + (getattr(node, "approach", 0.0) or 0.0), kpa

    def species(node: Any, mass: dict[str, float]) -> list[str]:
        """The components a Gibbs reactor's streams can carry: their templates' and the feed's."""
        names = list(mass)
        for s, _ in at[node.id][0] + at[node.id][1]:
            template = work.templates().get(s.template or "")
            names += [n for n in (template.components if template else []) if n not in names]
        return names

    beds: dict[str, Any] = {}

    def bed(node, ins, extra):
        """The outlet of fixed bed *node* (:func:`.fixed_bed.solve_node`), its temperature and
        pressure kept in ``beds``."""
        from chemeascode.domains.process.fixed_bed import solve_node

        if len(ins) != 1:
            raise ValueError("a fixed bed takes one inlet stream (mix the feeds before it)")
        result, inputs = solve_node(work, node, ins[0], case)
        extra |= inputs
        beds[node.id] = result
        return result.outlet

    def liquid_equilibrium(node, reactions, moles, ins, out, extra):
        """The outlet of liquid-phase equilibrium reactor *node*
        (:func:`.chemistry.liquid.equilibrate_liquid`): K at the outlet temperature plus the
        approach on each reaction's basis, activity coefficients at the outlet temperature."""
        from chemeascode.domains.chemistry.liquid import equilibrate_liquid
        from chemeascode.domains.chemistry.reactions import k_basis
        from chemeascode.domains.process.liquid_phase import inputs_of, liquid_of

        kelvin, kpa = conditions(node, ins, out)
        bases = [k_basis(r) for r in reactions]
        if gas := [r.id for r, b in zip(reactions, bases, strict=True) if b == "partial_pressure"]:
            raise ValueError(
                "liquid-phase reaction(s) " + ", ".join(gas) + " need an equilibrium_constant on "
                "mole_fraction, activity or concentration"
            )
        stoich = [r.stoichiometry for r in reactions]
        ks = [reaction_ln_k(r, data, kelvin, b) for r, b in zip(reactions, bases, strict=True)]
        names = sorted(set(moles) | {n for r in stoich for n in r})
        extra |= {"T": kelvin, "P": kpa, "reactions": stoich, "ln_k": ks, "bases": bases}
        extra |= inputs_of(work, names, bases)
        liquid_t = kelvin - (getattr(node, "approach", 0.0) or 0.0)
        return equilibrate_liquid(stoich, ks, bases, moles, liquid_t, liquid_of(work))[0]

    def tank(node, ins, extra):
        """The outlet of stirred tank or (semi-)batch *node* (:func:`.stirred_tank.solve_node`), its
        temperature and pressure kept in ``beds`` (written as a bed's are)."""
        from chemeascode.domains.process.stirred_tank import solve_node as solve_tank
        from chemeascode.domains.process.stirred_tank import tank_inlet

        result, inputs = solve_tank(work, node, tank_inlet(node, ins), case)
        extra |= inputs
        beds[node.id] = result
        return result.outlet

    def solve(node, model, reactions, rates, names, mass, mw, ins, out, extra):
        """The outlet (kmol/h by component) of reactor *node*; ValueError when it cannot be
        computed. Records what it depends on in *extra* (the outlet's fingerprint)."""
        if lacking := [n for n in names if not mw[n]]:
            raise ValueError("no molar_mass for " + ", ".join(lacking))
        moles = {n: mass.get(n, 0.0) / (mw[n] or 1.0) for n in names}
        if model == "conversion":
            extra |= {
                r.id: [r.stoichiometry, r.conversion and r.conversion.key, rates[r.id]]
                for r in reactions
            }
            return convert(reactions, rates, moles)[0]
        if model == "selectivity":
            from chemeascode.domains.chemistry.reactions import selectivity_outlet

            spec = node.selectivity
            extra |= {
                "selectivity": spec.model_dump(
                    mode="json", exclude={"provenance", "source", "uncertainty"}
                ),
                "reactions": {r.id: r.stoichiometry for r in reactions},
            }
            return selectivity_outlet(reactions, spec.key, spec.conversion, spec.products, moles)
        if model == "pfr":
            return bed(node, ins, extra)
        if model in ("cstr", "batch", "semibatch"):
            return tank(node, ins, extra)
        mixed = [r.id for r in reactions if r.phase == "mixed"]
        if mixed:
            raise ValueError("no equilibrium of a mixed-phase reaction: " + ", ".join(mixed))
        liquid = [r for r in reactions if r.phase == "liquid"]
        if liquid:
            if len(liquid) != len(reactions):
                raise ValueError(
                    "an equilibrium reactor holds gas-phase or liquid-phase reactions, not both"
                )
            return liquid_equilibrium(node, reactions, moles, ins, out, extra)
        kelvin, kpa = conditions(node, ins, out)
        if model == "gibbs":
            # inerts take part in no reaction and need no ideal_gas data (inert_species)
            stoich = independent_reactions(names, work.formulas())
            used = list(dict.fromkeys(n for r in stoich for n in r))
            if lack := missing(used, data):
                raise ValueError("no ideal_gas data for " + ", ".join(lack))
            if beyond := outside(used, data, kelvin):
                raise ValueError(
                    f"{kelvin:.6g} K is outside the ideal_gas temperature_range of "
                    + ", ".join(beyond)
                )
            ks = [ln_k_of_stoichiometry(r, data, kelvin) for r in stoich]
        else:
            stoich = [r.stoichiometry for r in reactions]
            ks = [reaction_ln_k(r, data, kelvin) for r in reactions]
        extra |= {"T": kelvin, "P": kpa, "reactions": stoich, "ln_k": ks}
        if getattr(node, "fugacity", "ideal") == "peng_robinson":
            critical = {n: getattr(comps.get(n), "critical", None) for n in names}
            extra["critical"] = {
                n: c.model_dump(mode="json") if c else None for n, c in critical.items()
            }
            # phi at the gas's outlet temperature: the approach shifts K only
            gas_t = kelvin - (getattr(node, "approach", 0.0) or 0.0)
            return equilibrate_real(stoich, ks, moles, kpa, gas_t, critical)[0]
        return equilibrate(stoich, ks, moles, kpa)[0]

    def solids(node: Any, inlet: StreamDef, outs: list[tuple[StreamDef, str]]) -> bool:
        """The outlets of crystallizer or filter *node* (:mod:`.crystallization`)."""
        from chemeascode.domains.process.crystallization import (
            CrystallizationError,
            node_outlets,
            outlet_shape,
            separate_node,
            solve_node,
        )

        if stream_flows(work, inlet, case).components is None:
            return False
        shapes: dict[str, dict[str, float]] = {}
        try:
            if node.crystallizer is not None:
                result, extra = solve_node(work, node, inlet, case)
                ports = node_outlets(node.crystallizer, result)
                shapes = {
                    port: outlet_shape(node.crystallizer, role, result)
                    for role, port in node.crystallizer.outlets.items()
                }
            else:
                ports, extra = separate_node(work, node, inlet, case)
        except CrystallizationError as failure:
            if (node.id, str(failure)) not in found.solids:
                found.solids.append((node.id, str(failure)))
            return False
        changed = False
        kind = kinds[node.id]
        names = sorted({n for mass in ports.values() for n in mass})
        extra |= {"inlet": _converted(work, case, [inlet], components=names)}
        for s, port in outs:
            mass = ports.get(port)
            if mass is None:
                continue
            total = sum(mass.values())
            changed |= put(s, "flow", kg_h(total), kind, node.id, [inlet], extra)
            shape = mass if total > 0 else shapes.get(port) or mass
            changed |= put(s, "composition", _mix(work, shape), kind, node.id, [inlet], extra)
        return changed

    def still(node: Any, ins: list[StreamDef], outs: list[tuple[StreamDef, str]]) -> bool:
        """The cuts and the residue of batch still *node* (:mod:`.batch_still`)."""
        from chemeascode.domains.process.batch_still import (
            StillError,
            node_outlets,
            outlet_shapes,
            solve_node,
        )

        if any(stream_flows(work, s, case).components is None for s in ins):
            return False
        try:
            result, extra = solve_node(work, node, ins, case)
        except StillError as failure:
            if (node.id, str(failure)) not in found.stills:
                found.stills.append((node.id, str(failure)))
            return False
        ports = node_outlets(work, node.still, result)
        shapes = outlet_shapes(work, node.still, result)
        names = sorted({n for mass in ports.values() for n in mass})
        extra |= {"inlet": _converted(work, case, ins, components=names)}
        changed = False
        for s, port in outs:
            mass = ports.get(port)
            if mass is None:
                continue
            total = sum(mass.values())
            changed |= put(s, "flow", kg_h(total), "still", node.id, ins, extra)
            shape = mass if total > 0 else shapes.get(port) or mass
            changed |= put(s, "composition", _mix(work, shape), "still", node.id, ins, extra)
        return changed

    def step(node: Any) -> bool:
        kind = kinds[node.id]
        ins = [s for s, _ in at[node.id][0]]
        outs = at[node.id][1]
        changed = False
        if kind == "still":
            if ins and outs:
                changed |= still(node, ins, outs)
        elif kind in ("crystallizer", "solid-separation"):
            if len(ins) == 1 and outs:
                changed |= solids(node, ins[0], outs)
        elif kind == "pass-through" and len(ins) == 1 and len(outs) == 1:
            a, b = ins[0], outs[0][0]
            for name in FIELDS:
                if get(a, name) is not None:
                    changed |= put(b, name, get(a, name), kind, node.id, [a])
                elif get(b, name) is not None:
                    changed |= put(a, name, get(b, name), kind, node.id, [b])
        elif kind == "mixer" and ins and len(outs) == 1:
            out = outs[0][0]
            flows = [stream_flows(work, s, case) for s in ins]
            if all(f.total is not None for f in flows):
                total = sum(f.total or 0.0 for f in flows)
                converted = _converted(work, case, ins)
                changed |= put(out, "flow", kg_h(total), kind, node.id, ins, converted)
            if all(f.components is not None for f in flows):
                mass: dict[str, float] = {}
                for f in flows:
                    for n, v in (f.components or {}).items():
                        mass[n] = mass.get(n, 0.0) + v
                converted = _converted(work, case, ins, components=list(mass))
                changed |= put(out, "composition", _mix(work, mass), kind, node.id, ins, converted)
        elif kind == "reactor" and ins and len(outs) == 1 and reactors[node.id] is not None:
            out = outs[0][0]
            model, reactions, rates = reactors[node.id]  # type: ignore[misc]
            flows = [stream_flows(work, s, case) for s in ins]
            # mass is conserved whatever the reactions do: the outlet flow needs only the inlets
            if all(f.total is not None for f in flows):
                total = sum(f.total or 0.0 for f in flows)
                converted = _converted(work, case, ins)
                changed |= put(out, "flow", kg_h(total), kind, node.id, ins, converted)
            if get(out, "composition") is None and all(f.components is not None for f in flows):
                mass: dict[str, float] = {}
                for f in flows:
                    for n, v in (f.components or {}).items():
                        mass[n] = mass.get(n, 0.0) + v
                names = list(dict.fromkeys(n for r in reactions for n in r.stoichiometry))
                if model == "gibbs":
                    names = species(node, mass)
                names = [*mass, *(n for n in names if n not in mass)]
                mw = {n: getattr(comps.get(n), "molar_mass", None) for n in names}
                extra: dict[str, Any] = {"model": model, "molar_mass": mw}
                try:
                    outlet = solve(node, model, reactions, rates, names, mass, mw, ins, out, extra)
                except ValueError as failure:
                    if (node.id, str(failure)) not in found.problems:
                        found.problems.append((node.id, str(failure)))
                else:
                    result = {n: outlet.get(n, 0.0) * (mw[n] or 1.0) for n in names}
                    changed |= put(
                        out, "composition", _mix(work, result), kind, node.id, ins, extra
                    )
                    solved = beds.get(node.id)
                    if solved is not None:
                        for name, value, tol in (
                            ("temperature", solved.temperature, 1.0),
                            ("pressure", solved.pressure, 0.01 * solved.pressure),
                        ):
                            q = get(out, name)
                            if q is None or ours(q):
                                continue
                            given = (
                                to_kelvin(q.value, q.unit or fs.units.temperature)
                                if name == "temperature"
                                else to_kpa_abs(q.value, q.unit or fs.units.pressure)
                            )
                            if given is not None and abs(given - value) > tol:
                                text = (
                                    f"the outlet {name} is {q.provenance} as {given:.6g}, the "
                                    f"{'bed' if model == 'pfr' else model} gives {value:.6g}"
                                )
                                if (node.id, text) not in found.problems:
                                    found.problems.append((node.id, text))
                        t_unit = None if fs.units.temperature == "K" else "K"
                        p_unit = None if fs.units.pressure == "kPa(a)" else "kPa(a)"
                        for name, value, unit in (
                            ("temperature", solved.temperature, t_unit),
                            ("pressure", solved.pressure, p_unit),
                        ):
                            q = Quantity(value=_sig(value), unit=unit, provenance="calculated")
                            changed |= put(out, name, q, kind, node.id, ins, extra)
        elif kind == "splitter" and len(ins) == 1 and outs:
            src = ins[0]
            comp = get(src, "composition")
            if comp is not None:
                for s, _ in outs:
                    changed |= put(s, "composition", comp, kind, node.id, [src])
            else:
                known = next(
                    (get(s, "composition") for s, _ in outs if get(s, "composition")), None
                )
                origin = next((s for s, _ in outs if get(s, "composition")), None)
                if known is not None and origin is not None:
                    changed |= put(src, "composition", known, kind, node.id, [origin])
            split = getattr(node, "split", {}) or {}
            if get(src, "flow") is not None:
                q = get(src, "flow")
                for s, port in outs:
                    if port in split:
                        part = q.model_copy(update={"value": _sig(q.value * split[port])})
                        changed |= put(s, "flow", part, kind, node.id, [src], split)
            total = stream_flows(work, src, case).total
            parts = {s.id: stream_flows(work, s, case).total for s, _ in outs}
            lacking = [s for s, _ in outs if parts[s.id] is None]
            if total is not None and len(lacking) == 1:
                rest = total - sum(v or 0.0 for v in parts.values())
                if rest >= 0:
                    others = [src, *(s for s, _ in outs if s is not lacking[0])]
                    converted = _converted(work, case, others)
                    changed |= put(lacking[0], "flow", kg_h(rest), kind, node.id, others, converted)
            elif total is None and not lacking:
                total = sum(v or 0.0 for v in parts.values())
                others = [s for s, _ in outs]
                converted = _converted(work, case, others)
                changed |= put(src, "flow", kg_h(total), kind, node.id, others, converted)
        return changed

    for _ in range(len(streams) + 1):
        changed = False
        found.passes += 1
        for node in nodes:
            changed |= step(node)
        if not changed:
            break
    for node in nodes:
        kind = kinds[node.id]
        ends = [s for s, _ in at[node.id][0] + at[node.id][1]]
        lacking = [s.id for s in ends if any(get(s, n) is None for n in FIELDS)]
        if not lacking:
            continue
        solved = (
            (kind == "pass-through" and len(at[node.id][0]) == len(at[node.id][1]) == 1)
            or (kind == "mixer" and len(at[node.id][1]) == 1)
            or (kind == "splitter" and len(at[node.id][0]) == 1)
            or (
                # a reactor whose conversions failed is reported as such, not again here
                kind == "reactor"
                and len(at[node.id][1]) == 1
                and reactors[node.id] is not None
                and any(p[0] == node.id for p in found.problems)
            )
            or any(p[0] == node.id for p in found.solids)
            or any(p[0] == node.id for p in found.stills)
        )
        if not solved:
            label = kind or f"class {node.class_}"
            if kind in ("pass-through", "mixer", "splitter"):
                label += (
                    f" class, {len(at[node.id][0])} material stream(s) in, "
                    f"{len(at[node.id][1])} out"
                )
            found.unsolved.append((node.id, label, lacking))
    return found


def derivation(process: Process, case: str) -> Derivation:
    """:func:`derive`, once per loaded *process* and *case* (a staleness check of every stream
    would otherwise integrate every fixed bed once per stream)."""
    cache = process.__dict__.setdefault("_derivations", {})
    if case not in cache:
        cache[case] = derive(process, case)
    return cache[case]


def _mix(process: Process, mass: dict[str, float]) -> CompositionValue:
    """The composition of *mass* (kg/h by component): mole fractions where every molar mass is
    known, else mass fractions."""
    comps = process.components()
    mw = {n: getattr(comps.get(n), "molar_mass", None) for n in mass}
    if all(mw.values()):
        moles = {n: v / (mw[n] or 1.0) for n, v in mass.items()}
        total = sum(moles.values()) or 1.0
        values = {n: _sig(v / total) for n, v in moles.items()}
        return CompositionValue(basis="mole_fraction", values=values, provenance="calculated")
    total = sum(mass.values()) or 1.0
    values = {n: _sig(v / total) for n, v in mass.items()}
    return CompositionValue(basis="mass_fraction", values=values, provenance="calculated")


def stale_fields(process: Process, stream: StreamDef, case: str, found=None) -> list[str]:
    """The fields of *stream* in *case* propagate wrote whose inputs changed since (or that it
    can no longer derive)."""
    state = stream.state.get(case)
    mine = [n for n in WRITTEN if state is not None and ours(getattr(state, n))]
    if not mine:
        return []
    found = found or derivation(process, case)
    names = []
    for name in mine:
        new = found.values.get((stream.id, name))
        if new is None or new.fingerprint != getattr(state, name).fingerprint:
            names.append(name)
    return names


def _same(a: Any, b: Any) -> bool:
    return a is not None and b is not None and _dump(a) == _dump(b)


def run(workspace: Any, process: Process, case: str, *, write: bool) -> PropsResult:
    """Fill (*write*) or check the propagated compositions and flows in *case*."""
    result = PropsResult()
    doc = process.flowsheet_doc
    fs = process.flowsheet

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str = ""):
        result.findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    found = derive(process, case)
    edits: dict[int, dict[str, Any]] = {}
    for i, stream in enumerate(fs.streams):
        state = stream.state.get(case)
        loc = ["streams", i, "state", case]
        for name in WRITTEN:
            old = getattr(state, name) if state is not None else None
            new = found.values.get((stream.id, name))
            if new is None:
                if ours(old):
                    add(
                        "warning",
                        "calculated-stale",
                        f"stream {stream.id} ({case}): {name} propagated earlier, no longer "
                        "derivable; kept, stale",
                        loc,
                        [stream.id],
                        "give the inputs again, or remove the value",
                    )
                continue
            if _same(old, new):
                continue
            result.lines.append(f"{stream.id} {name}: {new.source[len(SOURCE) + 2 :]}")
            if write:
                edits.setdefault(i, {})[name] = new
            elif old is None:
                add(
                    "info",
                    "propagate-not-filled",
                    f"stream {stream.id} ({case}): {name} derivable, not filled",
                    loc,
                    [stream.id],
                    "run cheme process propagate --fill",
                )
            else:
                add(
                    "warning",
                    "calculated-stale",
                    f"stream {stream.id} ({case}): propagated {name} no longer matches its inputs",
                    loc,
                    [stream.id],
                    "run cheme process propagate --fill",
                )
    keys = {n.id: ("steps", j) for j, n in enumerate(fs.steps)}
    keys.update({n.id: ("blocks", j) for j, n in enumerate(fs.blocks)})
    for node, message in found.problems:
        add(
            "warning",
            "propagate-reactor",
            f"{node} (reactor): conversions not applied: {message}",
            list(keys.get(node, ())),
            [node],
            "correct the conversions, the stoichiometry or the feed",
        )
    for node, message in found.solids:
        add(
            "warning",
            "propagate-crystallizer",
            f"{node} (crystallizer or filter): not solved: {message}",
            list(keys.get(node, ())),
            [node],
            "correct the specification or the inlet; cheme process crystallizers shows the "
            "model's scope",
        )
    for node, message in found.stills:
        add(
            "warning",
            "propagate-still",
            f"{node} (still): not solved: {message}",
            list(keys.get(node, ())),
            [node],
            "correct the still's specification, its data or the inlets; cheme process stills "
            "reports it",
        )
    for node, kind, lacking in found.unsolved:
        how = (
            "only checked (cheme validate balances it), never solved"
            if kind in ("separator", "reactor")
            else "not determined by its streams"
        )
        add(
            "info",
            "propagate-not-solved",
            f"{node} ({kind}): {how}; streams lacking a composition or flow: " + ", ".join(lacking),
            list(keys.get(node, ())),
            [node],
            "give those values (provenance given or assumed)"
            + (
                ", or a conversion: for each of its reactions (one outlet stream)"
                if kind == "reactor"
                else ""
            ),
        )
    if write:
        if edits:
            _write(workspace.root / FLOWSHEET_FILE, doc, case, edits)
        result.written = len(edits)
        result.lines.append(
            f"{FLOWSHEET_FILE}: propagated values written for {len(edits)} stream(s)"
        )
    filled = {fs.streams[i].id: list(names) for i, names in edits.items()} if write else {}
    result.adapter = _adapter_result(workspace.root, process, case, found, filled, result)
    return result


def _solver() -> Solver:
    from chemeascode.foundation.workspace import installed_version

    return Solver(
        name=SOURCE,
        version=".".join(str(n) for n in installed_version()),
        method="rules by step class (pass-through, mixer, splitter, reactor)",
    )


def _inputs_of(root: Any) -> dict[str, Any]:
    """The files propagate reads, as they are now."""
    from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE
    from chemeascode.domains.chemistry.reactions import REACTIONS_FILE
    from chemeascode.domains.process import MATERIALS_FILE
    from chemeascode.foundation.provenance import source_revision

    paths = (MATERIALS_FILE, FLOWSHEET_FILE, REACTIONS_FILE, CATALYSTS_FILE)
    return source_revision(root, paths).as_dict()


def failed_result(root: Any, case: str, message: str) -> AdapterResult:
    """The adapter result of a run that broke off (:func:`run` raised *message*)."""
    return AdapterResult(
        case=case, status="failed", solver=_solver(), inputs=_inputs_of(root), messages=[message]
    )


def _adapter_result(
    root: Any,
    process: Process,
    case: str,
    found: Derivation,
    filled: dict[str, list[str]],
    result: PropsResult,
) -> AdapterResult:
    """The run as an adapter result: converged when every node is solved, else not-converged
    with the nodes left unsolved in ``messages`` and ``units``; ``iterations`` the sweeps."""
    from chemeascode.domains.process.simulation.record import stream_values

    units: list[dict[str, Any]] = []
    messages: list[str] = []
    for node, kind, lacking in found.unsolved:
        messages.append(f"{node} ({kind}): not solved; lacking " + ", ".join(lacking))
        units.append(
            {
                "id": node,
                "status": "not-solved",
                "converged": False,
                "behaviour": kind,
                "lacking": list(lacking),
            }
        )
    for node, message in found.problems:
        messages.append(f"{node} (reactor): conversions not applied: {message}")
        units.append({"id": node, "status": "not-solved", "converged": False, "reason": message})
    for node, message in found.solids:
        messages.append(f"{node} (crystallizer or filter): not solved: {message}")
        units.append({"id": node, "status": "not-solved", "converged": False, "reason": message})
    for node, message in found.stills:
        messages.append(f"{node} (still): not solved: {message}")
        units.append({"id": node, "status": "not-solved", "converged": False, "reason": message})
    shown = stream_values(process, found.values)
    return AdapterResult(
        case=case,
        status="not-converged" if messages else "converged",
        solver=_solver(),
        inputs=_inputs_of(root),
        iterations=found.passes,
        messages=messages,
        units=units,
        streams=[
            {"id": s.id, "values": shown[s.id], "filled": filled.get(s.id, [])}
            for s in process.flowsheet.streams
            if s.id in shown
        ],
        findings=[finding_dict(f) for f in result.findings],
    )


# -- writing ------------------------------------------------------------------------------------


def _write(path: Any, doc: Any, case: str, edits: dict[int, dict[str, Any]]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    streams = _child(doc, "streams")
    assert streams is not None
    changes: list[tuple[int, int, list[str]]] = []  # (start, end exclusive, new lines)

    def block(node: Any, what: str) -> Any:
        if not isinstance(node, yaml.MappingNode) or node.flow_style:
            raise ValueError(f"{FLOWSHEET_FILE}: {what} is not a block mapping; write it as one")
        return node

    for index, new in edits.items():
        stream = block(streams[1].value[index], f"stream {index + 1}")
        entries = {k: _flow(_dump(v)) for k, v in new.items()}
        indent = " " * stream.value[0][0].start_mark.column
        state = _child(stream, "state")
        if state is None:
            text = [f"{indent}state:\n", f"{indent}  {case}:\n"]
            text += [f"{indent}    {k}: {v}\n" for k, v in entries.items()]
            at = _last_line(stream) + 1
            changes.append((at, at, text))
            continue
        mapping = block(state[1], f"stream {index + 1} state")
        target = _child(mapping, case)
        if target is None:
            inner = " " * mapping.value[0][0].start_mark.column
            text = [f"{inner}{case}:\n"] + [f"{inner}  {k}: {v}\n" for k, v in entries.items()]
            at = _last_line(mapping) + 1
            changes.append((at, at, text))
            continue
        mapping = block(target[1], f"stream {index + 1} state.{case}")
        inner = " " * mapping.value[0][0].start_mark.column
        at = _last_line(mapping) + 1
        for key, value in entries.items():
            text = [f"{inner}{key}: {value}\n"]
            found = _child(mapping, key)
            if found is None:
                changes.append((at, at, text))
            else:
                changes.append((found[0].start_mark.line, _last_line(found[1]) + 1, text))
    for start, end, text in sorted(changes, key=lambda c: (c[0], c[1]), reverse=True):
        lines[start:end] = text
    path.write_text("".join(lines), encoding="utf-8")
