"""The reactions of a plant as the viewer shows them (``GET /api/reactions``).

Nothing is calculated here that a command does not already calculate: each reaction as
``process/reactions.yaml`` declares it (with the provenance of its conversion, heat of reaction
and equilibrium constant), what the flowsheet says about it (the reactors it takes place in,
their model and the conversion they use), its ``reaction_smiles`` (the reaction's external
identifier, :meth:`Reaction.reaction_smiles`; None unless every component has a SMILES), its
element balance (``reactions.element_change``), the rows of ``cheme process reactors``
(:func:`reactors.reactor_entry`) and the reactive balances with their findings (``cheme
validate``'s reaction, reactor and balance rules).

Kinetics: each reaction entry carries its ``rate`` as declared (form, basis, driving force,
``k`` with A/Ea/n/T_ref, orders, adsorption terms, catalyst, temperature range, provenance and
source; and whatever else the schema of a reaction gives, e.g. a microkinetic ``mechanism``),
and ``rate_law`` derived from it (:func:`rate_law_view`): the expression as text, the units of
the rate and of ``k``, the catalyst it holds for, and ``k(T)`` over its temperature range (the
rate law's, else its catalyst's window). ``kinetics`` is ``process/catalysts.yaml``: every
catalyst as declared plus the reactions it catalyses and the blocks and steps holding it (with
their bed), and the ``cheme.catalyst-*`` findings (``catalyst-unknown`` too: the catalysts the
reactions name) and ``cheme.process-catalyst``. The solved fixed beds (catalyst mass, outlet,
hot spot, pressure drop and the W/T/P profile) are the ``bed`` of the ``reactors`` rows.

A reaction with a microkinetic ``mechanism`` gets its ``microkinetics``
(:func:`microkinetics_view`): the analysis of ``cheme chemistry microkinetics`` (coverages, TOF,
degree of rate control, apparent activation energy, orders) at the outlet of the first reactor
it takes place in (its temperature and the mechanism's partial pressures there), or what is
missing to make it.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from chemeascode.domains.chemistry.catalysts import CATALYSTS_FILE
from chemeascode.domains.chemistry.rates import RateLaw
from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, element_change, key_component
from chemeascode.domains.process.model import Process, balance_of, rules
from chemeascode.domains.process.reactors import _model, reactor_entry

#: The ``cheme validate`` rules about reactions and reactors, beside ``cheme.reaction-*``.
REACTION_RULES = (
    "cheme.process-reaction",
    "cheme.process-reactor",
    "cheme.process-heat-of-reaction",
    "cheme.process-condenser-freezing",
)
#: Balance rules, kept for the reactive blocks and steps.
BALANCE_RULES = (
    "cheme.process-balance",
    "cheme.process-balance-not-evaluable",
    "cheme.process-balance-unsupported",
    "cheme.process-component-balance-not-evaluable",
)
#: Points of ``k(T)`` in a rate law's ``k_profile``.
K_PROFILE_POINTS = 21


def _findings(process: Process) -> list[Any]:
    """``cheme validate``'s process findings with its catalyst references."""
    from chemeascode.domains.process.sheets import catalyst_reference_findings

    return rules(process) + catalyst_reference_findings(process)


def _power(name: str, exponent: float) -> str:
    return name if exponent == 1 else f"{name}^{exponent:g}"


def rate_law_view(law: RateLaw, window: tuple[float, float] | None = None) -> dict[str, Any]:
    """What the viewer shows of a rate law beside its parameters: the expression, the units of
    the rate and of ``k``, and ``k(T)`` at :data:`K_PROFILE_POINTS` temperatures over its
    ``temperature_range`` (else *window*, the catalyst's; neither: no profile)."""
    symbol = "p" if law.driving == "partial_pressure" else "c"
    driving_unit = "bar" if law.driving == "partial_pressure" else "kmol/m3"
    rate_unit = "kmol/(kg s)" if law.basis == "catalyst_mass" else "kmol/(m3 s)"
    terms = [_power(f"{symbol}_{n}", a) for n, a in law.orders.items() if a != 0]
    text = " · ".join(["k(T)", *terms])
    if law.reverse == "equilibrium":
        text += " · (1 - Q/K)"
    if law.form == "lhhw":
        den = []
        for i, term in enumerate(law.adsorption, start=1):
            parts = [f"K{i}(T)", *(_power(f"{symbol}_{n}", b) for n, b in term.exponents.items())]
            den.append(" · ".join(parts))
        bottom = f"(1 + {' + '.join(den)})"
        text = f"{text} / {bottom if law.power == 1 else f'{bottom}^{law.power:g}'}"
    order = sum(law.orders.values())
    base = f"({driving_unit})" if "/" in driving_unit else driving_unit
    k_unit = rate_unit if order == 0 else f"{rate_unit} / {base}^{order:g}"
    span, frm = law.temperature_range, "temperature_range"
    if span is None and window is not None:
        span, frm = window, "catalyst window"
    profile = []
    if span is not None:
        lo, hi = span
        for i in range(K_PROFILE_POINTS):
            t = lo + (hi - lo) * i / (K_PROFILE_POINTS - 1)
            profile.append({"temperature_K": t, "k": law.k.k(t)})
    return {
        "expression": f"r = {text}",
        "k_expression": "k(T) = A (T/T_ref)^n exp(-Ea/(R T))",
        "rate_unit": rate_unit,
        "driving_unit": driving_unit,
        "k_unit": k_unit,
        "catalyst": law.catalyst or None,
        "k_profile": profile,
        "k_profile_from": frm if span is not None else None,
    }


def kinetics_payload(process: Process, found: list[Any] | None = None) -> dict[str, Any]:
    """``kinetics`` of ``GET /api/reactions`` (see the module docstring); *found*: the
    findings of :func:`rules` when they are at hand."""
    fs = process.flowsheet
    declared = process.reactions.reactions if process.reactions else []
    catalysts = process.catalysts.catalysts if process.catalysts else []
    holders: dict[str, list[dict[str, Any]]] = {}
    for item in [*fs.blocks, *fs.steps]:
        name = getattr(item, "catalyst", None)
        if name:
            bed = getattr(item, "bed", None)
            holders.setdefault(name, []).append(
                {
                    "unit": item.id,
                    "kind": process.kinds.get(item.id),
                    "reactor": getattr(item, "reactor", None),
                    "reactions": list(getattr(item, "reactions", []) or []),
                    "bed": bed.model_dump(mode="json") if bed is not None else None,
                }
            )
    entries = []
    for cat in catalysts:
        catalysed = [
            r.id
            for r in declared
            if r.catalyst == cat.id or (r.rate is not None and r.rate.catalyst == cat.id)
        ]
        entries.append(
            {
                **cat.model_dump(mode="json", by_alias=True),
                "reactions": catalysed,
                "units": holders.get(cat.id, []),
            }
        )
    findings = [
        f
        for f in (_findings(process) if found is None else found)
        if f.rule.startswith("cheme.catalyst-") or f.rule == "cheme.process-catalyst"
    ]
    return {
        "file": CATALYSTS_FILE if process.catalysts is not None else None,
        "catalysts": entries,
        "findings": [{**asdict(f), "id": f.id} for f in findings],
    }


def microkinetics_view(
    process: Process, reaction: str, places: list[dict[str, Any]], case: str
) -> dict[str, Any]:
    """The mechanism of *reaction* analysed at the outlet of its first reactor in *places* with
    one outlet (see the module docstring): ``conditions`` (unit, stream, temperature, partial
    pressures) and the analysis, or ``missing`` naming why there is none."""
    from chemeascode.domains.process.microkinetic_report import NotAvailable, microkinetic_report
    from chemeascode.domains.process.reactors import equilibrium_conditions

    if not places:
        return {"conditions": None, "missing": "the reaction takes place in no block or step"}
    streams = {s.id: s for s in process.flowsheet.streams}
    single = [
        (p["unit"], b)
        for p in places
        if len((b := balance_of(process, p["unit"], case)).streams_out) == 1
    ]
    if not single:
        units = ", ".join(p["unit"] for p in places)
        return {"conditions": None, "missing": f"no reactor of it ({units}) has a single outlet"}
    unit, balance = single[0]
    out = streams[balance.streams_out[0]]
    ins = [streams[s] for s in balance.streams_in]
    try:
        t, p = equilibrium_conditions(process.flowsheet.units, case, ins, out)
    except ValueError as failure:
        return {"conditions": None, "missing": str(failure)}
    from chemeascode.domains.process.reactors import _moles

    moles = _moles(process, out, case)
    if not moles:
        return {"conditions": None, "missing": f"no composition and flow of {out.id}"}
    total = sum(moles.values())
    mech = process.reactions.by_id()[reaction].mechanism  # type: ignore[union-attr]
    gas = sorted({n for s in mech.steps for n in s.gas()})  # type: ignore[union-attr]
    pressures = {n: moles.get(n, 0.0) / total * p / 100.0 for n in gas}
    conditions = {"unit": unit, "stream": out.id, "temperature_K": t, "pressures_bar": pressures}
    try:
        result = microkinetic_report(process.root, reaction, t, pressures, chemistry=process)
    except (NotAvailable, ValueError, ArithmeticError, LookupError, StopIteration) as failure:
        # one mechanism that does not solve leaves the rest of the page
        return {"conditions": conditions, "missing": str(failure) or type(failure).__name__}
    return {"conditions": conditions, "missing": None, **result}


def reactions_payload(process: Process, case: str) -> dict[str, Any]:
    """``GET /api/reactions`` without ``rev`` (see the module docstring)."""
    fs = process.flowsheet
    formulas = process.formulas()
    smiles = {c.id: c.smiles for c in (process.materials.components if process.materials else [])}
    declared = process.reactions.reactions if process.reactions else []
    reactive = [n.id for n in [*fs.blocks, *fs.steps] if process.reactive(n.id)]

    # where each reaction takes place: the blocks and steps naming it themselves
    places: dict[str, list[dict[str, Any]]] = {}
    for item in [*fs.blocks, *fs.steps]:
        own = list(getattr(item, "reactions", []) or [])
        if not own:
            continue
        found, _ = process.reactions_of(item.id)
        model = _model(item)
        for name in own:
            reaction = next((r for r in found if r.id == name), None)
            given = (getattr(item, "conversion", {}) or {}).get(name)
            if given is not None:
                conversion = {"value": given, "from": f"flowsheet {item.id}"}
            elif reaction is not None and reaction.conversion is not None:
                conversion = {"value": reaction.conversion.value, "from": REACTIONS_FILE}
            else:
                conversion = None
            places.setdefault(name, []).append(
                {
                    "unit": item.id,
                    "kind": process.kinds.get(item.id),
                    "model": model,
                    "approach_K": getattr(item, "approach", 0.0) or 0.0,
                    "conversion": conversion,
                }
            )

    windows = {
        c.id: c.window.temperature
        for c in (process.catalysts.catalysts if process.catalysts else [])
        if c.window is not None and c.window.temperature is not None
    }
    reactions = []
    for reaction in declared:
        data = reaction.model_dump(mode="json", by_alias=True)
        unknown = [n for n in reaction.stoichiometry if n not in formulas]
        change = None if unknown else element_change(reaction, formulas)
        models = sorted({p["model"] for p in places.get(reaction.id, []) if p["model"]})
        reactions.append(
            {
                **data,
                "key_component": key_component(reaction),
                "reaction_smiles": reaction.reaction_smiles(smiles),
                "type": models[0] if len(models) == 1 else ("mixed" if models else None),
                "units": places.get(reaction.id, []),
                "rate_law": None
                if reaction.rate is None
                else rate_law_view(
                    reaction.rate,
                    windows.get(reaction.rate.catalyst or reaction.catalyst),
                ),
                "microkinetics": None
                if reaction.mechanism is None
                else microkinetics_view(process, reaction.id, places.get(reaction.id, []), case),
                "element_balance": {
                    "evaluable": change is not None,
                    "balanced": None if change is None else not change,
                    "change": change or {},
                },
            }
        )

    reactors = [reactor_entry(process, node, case) for node in reactive]
    balances = [balance_of(process, node, case).entry() for node in reactive]
    names = {r.id for r in declared}
    everything = _findings(process)
    findings = [
        f
        for f in everything
        if f.rule.startswith("cheme.reaction-")
        or f.rule in REACTION_RULES
        or (f.rule in BALANCE_RULES and set(f.ids) & set(reactive))
        or (f.file == REACTIONS_FILE)
        or (f.rule.startswith("cheme.process-") and set(f.ids) & names)
    ]
    return {
        "file": REACTIONS_FILE,
        "case": case,
        "cases": [c.id for c in fs.cases],
        "reactions": reactions,
        "reactors": reactors,
        "balance": {
            "balances": balances,
            "findings": [{**asdict(f), "id": f.id} for f in findings],
        },
        "kinetics": kinetics_payload(process, everything),
    }
