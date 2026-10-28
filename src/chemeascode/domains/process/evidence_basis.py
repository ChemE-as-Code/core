"""A conversion reactor's specified values against the reaction evidence
(``process/reaction-evidence.yaml``, :mod:`chemeascode.domains.chemistry.evidence`).

A specified conversion counts as sourced in :mod:`.model_basis` when ``process/reactions.yaml``
gives it with a source. This adds the other way: the decided model basis of the evidence file
names the reaction and its cited observations cover the value
(:func:`~chemeascode.domains.chemistry.evidence.model_support`). Per reactor:

- a ``selectivity:`` (node) is judged on the spec itself (as :mod:`.model_basis` does without
  an evidence file):
  its own ``provenance: given`` with a source, the reactions' own (unused) conversions do not
  count. With a model basis naming all the node's reactions, the key's conversion and every
  product's molar selectivity are compared. The node gives kmol of product formed per kmol of
  key converted, the evidence a fraction: the node's value is divided by the product's over
  the key's coefficient in the step's reactions that form it from the key. A product formed
  from the key by none of them, or by several with different ratios, is not compared;
- else per reaction the model basis names: the reaction's own ``conversion`` (a node-level
  ``conversion:`` has no provenance and the evidence does not change that). A reaction whose
  key another reaction of the step also consumes is not compared: an observed conversion is
  the reactant's total, not one reaction's (give the node a ``selectivity:``).

The reactor's operating temperatures and pressures are those of its outlet streams in every
case (only these conditions are compared); a case without an outlet temperature leaves every
value unsupported. The basis catalyst's ``name`` in ``process/catalysts.yaml`` is passed on, as
an observation's ``catalyst_formulation`` may give it. A value the evidence supports counts as
sourced. One it *contradicts* (nothing else blocking, usable observations at the known outlet
temperature exclude it) is not sourced, its own source notwithstanding. One it cannot compare
(a route not selected, a conflict, unknown conditions, no usable observation, a shared
reactant, ...) keeps its own
source if it has one, with the reason as a limitation, and is otherwise unsourced. The basis
stays ``conversion``: specified, never predictive.
"""

from __future__ import annotations

from typing import Any

from chemeascode.domains.chemistry import evidence as ev
from chemeascode.domains.process.model import Process
from chemeascode.foundation.units import to_kelvin, to_kpa_abs


def _operating(process: Process, node_id: str) -> tuple[list[float], list[float], list[str]]:
    """The temperatures (K) and pressures (kPa(a)) of the outlets of *node_id* in every case,
    and the cases where no outlet gives a temperature this reads."""
    fs = process.flowsheet
    temperatures: list[float] = []
    pressures: list[float] = []
    known: set[str] = set()
    for stream in fs.streams:
        start, _ = process.ends(stream)
        if stream.kind != "material" or start is None or start.node != node_id:
            continue
        for case, state in stream.state.items():
            t, p = state.temperature, state.pressure
            if t is not None:
                kelvin = to_kelvin(t.value, t.unit or fs.units.temperature)
                if kelvin is not None:
                    known.add(case)
                    if kelvin not in temperatures:
                        temperatures.append(kelvin)
            if p is not None:
                kpa = to_kpa_abs(p.value, p.unit or fs.units.pressure)
                if kpa is not None and kpa not in pressures:
                    pressures.append(kpa)
    unknown = [c.id for c in fs.cases if c.id not in known] if known else []
    return temperatures, pressures, unknown


def _ratio(reactions: list[Any], key: str, product: str) -> tuple[float | None, str]:
    """kmol of *product* formed per kmol of *key* consumed by the reactions that form one from
    the other, and ""; None and why when none does, or several with different ratios."""
    ratios = {
        r.stoichiometry[product] / -r.stoichiometry[key]
        for r in reactions
        if r.stoichiometry.get(product, 0) > 0 and r.stoichiometry.get(key, 0) < 0
    }
    if not ratios:
        return None, f"no reaction of the step forms {product} from {key}"
    if len(ratios) > 1:
        shown = ", ".join(f"{x:g}" for x in sorted(ratios))
        return None, f"the step's reactions form {product} from {key} in different ratios ({shown})"
    return ratios.pop(), ""


def apply_evidence(
    unit: Any,
    process: Process,
    node: Any,
    evidence: ev.ReactionEvidence | None,
    errors: ev.Blocking | None = None,
) -> None:
    """Re-evaluate the ``conversion`` basis *unit* of *node* (:class:`.model_basis.UnitBasis`)
    against *evidence* (None: no evidence file), in place (see the module docstring). A
    ``selectivity:`` node is always judged here, on its spec; another node is unchanged when
    the model basis names none of its reactions. *errors*: the blocking error findings."""
    spec = getattr(node, "selectivity", None)
    basis = evidence.model_basis if evidence is not None else None
    if unit.basis != "conversion" or (spec is None and basis is None):
        return
    reactions, unknown = process.reactions_of(node.id)
    temperatures, pressures, unknown_cases = _operating(process, node.id)
    supports: list[ev.Support] = []
    problems = [f"undeclared reaction {', '.join(unknown)}"] if unknown else []
    unsourced: list[str] = []
    contradicted: list[ev.Support] = []
    uncompared: list[ev.Support] = []

    def judge(label: str, own: bool, support: ev.Support | None) -> None:
        if support is not None:
            supports.append(support)
            if support.supported:
                return
            if support.contradicted:
                contradicted.append(support)
                if own:  # the evidence contradicts the value: its own source does not stand
                    unsourced.append(
                        f"{label}: contradicted by {ev.EVIDENCE_FILE}: "
                        + "; ".join(support.reasons)
                    )
            elif own:
                uncompared.append(support)
        if not own:
            unsourced.append(label + (f": {'; '.join(support.reasons)}" if support else ""))

    # the reactor's catalyst, and the name in process/catalysts.yaml of the one the
    # observations must be on (the basis's, else the reactor's), as a formulation may give it
    declared = process.catalysts.by_id() if process.catalysts else {}
    held = getattr(node, "catalyst", None) or ""
    target = (basis.catalyst if basis is not None else "") or held
    named = declared.get(target) if target else None
    names = [named.name] if named is not None and named.name.strip() else []

    def support_of(quantity: Any, comp: str, value: float, key: str = "") -> ev.Support:
        assert evidence is not None
        return ev.model_support(
            evidence,
            quantity,
            comp,
            value,
            key,
            temperatures,
            pressures,
            errors,
            unknown_cases,
            names,
            held,
        )

    ids = [r.id for r in reactions]
    if spec is not None:
        # the spec's own provenance, never the reactions' unused conversions
        own = spec.provenance == "given" and bool(spec.source.strip())
        label = f"selectivity ({spec.provenance})"
        if evidence is None or not ev.covers(evidence, ids):
            judge(label, own, None)
        else:
            judge(f"{label} conversion", own, support_of("conversion", spec.key, spec.conversion))
            for product, given in spec.products.items():
                ratio, why = _ratio(reactions, spec.key, product)
                if ratio is None:
                    support = ev.Support("selectivity", product, given, key=spec.key)
                    support.route = basis.route if basis is not None else ""
                    support.reasons.append(why + ": the molar selectivity is not compared")
                else:
                    support = support_of("selectivity", product, given / ratio, spec.key)
                    if ratio != 1:
                        support.notes.append(
                            f"the flowsheet's {given:g} kmol {product}/kmol {spec.key} converted "
                            f"is the fraction {given / ratio:.4g} ({ratio:g} {product} per "
                            f"{spec.key} in its reactions)"
                        )
                judge(f"{label} {support.what}", own, support)
        unit.sources = [spec.source] if own else []
        head = f"specified conversion of {spec.key} and selectivities"
    else:
        assert evidence is not None and basis is not None
        for r in reactions:
            if r.id in node.conversion:
                unsourced.append(f"{r.id} (conversion on the node, no provenance)")
                continue
            if r.conversion is None:
                problems.append(f"no conversion for {r.id}")
                continue
            # the reactor basis counts a given conversion with a source on its own
            own = r.conversion.provenance == "given" and bool(r.conversion.source.strip())
            label = f"{r.id} (conversion {r.conversion.provenance})"
            if not ev.covers(evidence, [r.id]):
                judge(label, own, None)
                continue
            key = r.conversion.key
            consuming = [x.id for x in reactions if x.stoichiometry.get(key, 0) < 0]
            if len(consuming) > 1:
                support = ev.Support("conversion", key, r.conversion.value)
                support.route = basis.route
                support.reasons.append(
                    f"reactions {', '.join(consuming)} consume {key}: an observed conversion "
                    "is the reactant's total, not one reaction's (give a selectivity:)"
                )
            else:
                support = support_of("conversion", key, r.conversion.value)
            judge(f"{label} {support.what}", own, support)
        head = unit.detail.split(": ")[0]
    unit.evidence = [s.as_dict() for s in supports]
    if unsourced:
        problems.append("unsourced: " + ", ".join(unsourced))
    unit.sourced = not problems
    backed = [s.text() for s in supports if s.supported]
    unit.detail = head + (": " + "; ".join(problems) if problems else "")
    if backed:
        unit.detail += "; sourced by reaction evidence: " + "; ".join(backed)
    for support in supports:
        if support.supported:
            ref = f"{ev.EVIDENCE_FILE}: " + ", ".join(support.observations)
            if ref not in unit.sources:
                unit.sources.append(ref)
        elif support in contradicted:
            unit.limitations.append("contradicted by the evidence: " + support.text())
        elif support in uncompared:
            unit.limitations.append(
                "own source kept, not supported by the evidence: " + support.text()
            )
        else:
            unit.limitations.append(support.text())
        for note in support.notes:
            text = f"{support.what}: {note}"
            if text not in unit.limitations:
                unit.limitations.append(text)
