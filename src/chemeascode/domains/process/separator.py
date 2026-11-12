"""Component separators solved from their specified split (``recovery:``, ADR 0070).

A block or step without another model (no reactions, crystallizer, filter, dryer or still) and
of a separating or generic class may give ``recovery:``: per outlet port, the share of each
component's inlet flow (all its material inlets together) that leaves by it. One material
outlet may be left out and takes the rest. ``cheme process propagate`` writes the outlets'
flows and compositions (provenance calculated, rule ``separator``); their temperatures and
pressures stay as given. The split is specified, not predicted (as a ``component_separator``
of ``process/simulation.yaml``): ``provenance`` and ``source`` say where it comes from.

Rules (``cheme.process-recovery``, :func:`rules`): a ``recovery:`` on a node with another model
or of a mixing, splitting, pass-through or reacting class; a listed port that is no material
outlet of the node; more than one material outlet left out; an undeclared component; a
fraction outside [0, 1]; the fractions of a component summing beyond 1, or (every outlet
listed) to other than 1.
"""

from __future__ import annotations

from typing import Any

#: The fractions of a component sum to 1 (or at most 1) within this.
SUM_TOLERANCE = 1e-9
#: Behaviours (:func:`.propagate.behaviour`) that are no component separator.
NOT_SEPARATING = ("pass-through", "mixer", "splitter", "reactor")
#: The other models a block or step can carry; a component separator has none of them.
OTHER_MODELS = ("crystallizer", "solid_separation", "dryer", "still", "reactor")


def other_model(node: Any) -> str | None:
    """The model *node* has besides ``recovery:`` (None when it has none)."""
    if getattr(node, "reactions", None):
        return "reactions"
    return next((n for n in OTHER_MODELS if getattr(node, n, None) is not None), None)


def outlets(recovery: Any, mass: dict[str, float], ports: list[str]) -> dict[str, dict[str, float]]:
    """kg/h by component of each outlet port in *ports* from the inlets' *mass* (kg/h by
    component). Raises ValueError when the split does not fit the ports or the components."""
    listed = recovery.outlets
    unknown = [p for p in listed if p not in ports]
    if unknown:
        raise ValueError(f"recovery names {unknown}, no material outlet(s) of it")
    rest = [p for p in ports if p not in listed]
    if len(rest) > 1:
        raise ValueError(f"outlets {rest} are not in recovery: leave out one outlet at most")
    out: dict[str, dict[str, float]] = {p: {} for p in ports}
    for name, value in mass.items():
        shares = {p: fractions.get(name, 0.0) for p, fractions in listed.items()}
        total = sum(shares.values())
        if total > 1.0 + SUM_TOLERANCE:
            raise ValueError(f"{name}: the fractions sum to {total:.6g}, more than 1")
        if not rest and abs(total - 1.0) > SUM_TOLERANCE and value > 0:
            raise ValueError(
                f"{name}: the fractions sum to {total:.6g}, not 1, and every outlet is listed"
            )
        for port, share in shares.items():
            out[port][name] = value * share
        if rest:
            out[rest[0]][name] = value * max(0.0, 1.0 - total)
    return out


def rules(process: Any) -> list[Any]:
    """``cheme.process-recovery`` findings (see the module docstring)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.propagate import behaviour
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    findings: list[Any] = []
    fs = process.flowsheet
    comps = process.components()
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    hint = (
        "give recovery: on a separator without another model: per outlet port, component -> "
        "the fraction of its inlet flow, one outlet left out for the rest"
    )
    for key, index, node in nodes:
        recovery = getattr(node, "recovery", None)
        if recovery is None:
            continue
        line = _yaml_line(process.flowsheet_doc, [key, index, "recovery"])

        def add(message: str, node: Any = node, line: Any = line) -> None:
            findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    "error",
                    "cheme.process-recovery",
                    f"{node.id}: {message}",
                    line=line,
                    ids=[node.id],
                    hint=hint,
                )
            )

        other = other_model(node)
        kind = behaviour(node.class_)
        if other is not None:
            add(f"recovery: beside {other}: a component separator has no other model")
            continue
        if kind in NOT_SEPARATING:
            add(f"recovery: on a {kind} (class {node.class_}); a separator's class separates")
            continue
        if key == "blocks" and process.inside(node.id):
            add("recovery: on a block with steps inside; give it to the step that separates")
            continue
        outs = [p.id for p in node.ports if p.direction == "out" and p.kind == "material"]
        bad = [p for p in recovery.outlets if p not in outs]
        if bad:
            add(f"recovery names {bad}, no material outlet port(s) of it")
        rest = [p for p in outs if p not in recovery.outlets]
        if len(rest) > 1:
            add(f"outlets {rest} are not in recovery: leave out one outlet at most")
        names = sorted({n for fractions in recovery.outlets.values() for n in fractions})
        unknown = [n for n in names if n not in comps]
        if unknown:
            add(f"recovery names undeclared component(s) {unknown}")
        for port, fractions in recovery.outlets.items():
            outside = sorted(n for n, v in fractions.items() if not 0.0 <= v <= 1.0)
            if outside:
                add(f"recovery {port}: fraction(s) of {outside} outside [0, 1]")
        for name in names:
            total = sum(f.get(name, 0.0) for f in recovery.outlets.values())
            if total > 1.0 + SUM_TOLERANCE:
                add(f"recovery: the fractions of {name} sum to {total:.6g}, more than 1")
            elif not rest and abs(total - 1.0) > SUM_TOLERANCE:
                add(
                    f"recovery: every outlet is listed, and the fractions of {name} sum to "
                    f"{total:.6g}, not 1"
                )
    return findings
