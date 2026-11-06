"""Recycle loops in ``cheme process propagate``: tear streams converged (ADR 0060).

A flowsheet names the streams at which its recycle loops are torn (``tears:``, each with an
optional first guess ``initial:``) and, optionally, how they are converged (``convergence:``).
:func:`converge` sets every tear stream to its guess, sweeps the flowsheet once
(:func:`.propagate._sweep`), compares what the loop gives back with the guess, component by
component in kg/h, and repeats with a new guess:

- **successive substitution**: ``x(k+1) = x(k) + d (g(x(k)) - x(k))``, the ``damping`` d
  (default 1, plain substitution);
- **Wegstein** (default): per component, ``s = (g(k) - g(k-1)) / (x(k) - x(k-1))``,
  ``q = s / (s - 1)`` bounded to [-5, 0], ``x(k+1) = q x(k) + (1 - q) g(k)`` (Wegstein 1958;
  the first step is a substitution). For a linear loop with a constant gain per component (a
  purge loop with conversion), it reaches the fixed point in its second step.

The iterating sweeps round nothing (``rounded=False``): with the six digits propagate writes,
g(x) would be a staircase, and the iterations would stop up to 1e-6/(1 - gain) from the fixed
point whatever the tolerance. The loop is converged when every component of every tear is
within the tolerance (``convergence.tolerance``, else the flowsheet's:
``|g - x| <= abs + rel max(g, x)``). The values written are those of one more sweep, rounded,
from the converged guess rounded to six digits, so the flowsheet as written is one evaluation
of the loop. The tear values are ``calculated`` and fingerprinted on the loop's inputs
(:func:`loop_inputs`), not on the iterates; the iterations always start from the declared
guess, never from values written earlier, so a converged plant derives the same values again
and is not stale. A loop that does not converge or close writes nothing that depends on it:
the values are those of a sweep without the tears, as propagate derived them before. A tear
whose loop gives nothing back (open) never moves its guess: the iterations stop once the other
tears are converged or no guess moves any more. A given or assumed flow or composition of a
tear stream stays fixed (a design specification), and only the other is iterated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.process.model import Process, stream_flows
from chemeascode.domains.process.schema import (
    FLOW_UNITS,
    CompositionValue,
    Convergence,
    Quantity,
    State,
    StreamDef,
)
from chemeascode.foundation.provenance import NOT_INPUTS, value_fingerprint

#: Wegstein's q is bounded to [Q_MIN, Q_MAX]: acceleration only, never damping (Aspen Plus's
#: defaults).
Q_MIN, Q_MAX = -5.0, 0.0
#: The fractions of an ``initial:`` guess sum to 1 within this (as a stream's composition,
#: ``cheme.process-composition-sum``).
COMPOSITION_SUM = 1e-3
#: What a node declares that no sweep reads, left out of the tear fingerprint
#: (:func:`loop_inputs`): names and links, the drawing symbol, the thermal screening (ADR 0058)
#: and the energy stream a model duty goes on (ADR 0059, written after the loop converged).
NOT_SWEPT = frozenset({"title", "links", "symbol", "hazard", "energy_port"})


@dataclass
class Recycle:
    """How the loops torn at ``tears:`` converged in one case."""

    tears: list[str] = field(default_factory=list)
    method: str = "wegstein"
    max_iterations: int = 100
    #: Sweeps of the flowsheet (evaluations of the loops).
    iterations: int = 0
    converged: bool = False
    #: The |g - x| (kg/h) of the last iteration nearest (or furthest beyond) its tolerance, and
    #: the tear and component it is of.
    residual: float | None = None
    where: tuple[str, str] | None = None
    #: What the tolerance allows there (kg/h).
    allowed: float | None = None
    #: Tear stream id -> its converged guess (kg/h by component, not rounded).
    solution: dict[str, dict[str, float]] = field(default_factory=dict)
    #: (index in tears, stream id, message): why the iterations stopped short.
    problems: list[tuple[int | None, str, str]] = field(default_factory=list)
    #: (index in tears, level, stream id, message): tears left out (:func:`tear_problems`).
    declared: list[tuple[int, str, str, str]] = field(default_factory=list)


def _nodes(process: Process) -> dict[str, Any]:
    fs = process.flowsheet
    return {n.id: n for n in [*fs.steps, *(b for b in fs.blocks if not process.inside(b.id))]}


def _given(value: Any) -> bool:
    from chemeascode.domains.process.propagate import ours

    return value is not None and not ours(value)


def tear_problems(process: Process, case: str | None = None) -> list[tuple[int, str, str]]:
    """(index in tears, level, message) for every tear that cannot be iterated: an unknown or
    energy stream, one that does not run between two nodes propagate solves, one named twice, a
    guess with an unknown component or flow unit, or fractions that do not sum to 1 (a mass
    flow is multiplied by its mass fractions as they are); in *case* (else every case), a
    stream whose flow and composition are both given or assumed (nothing to converge)."""
    fs = process.flowsheet
    streams = {s.id: s for s in fs.streams}
    nodes = _nodes(process)
    comps = process.components()
    seen: set[str] = set()
    out: list[tuple[int, str, str]] = []
    cases = [case] if case is not None else [c.id for c in fs.cases]
    for i, tear in enumerate(fs.tears):
        s = streams.get(tear.stream)
        if s is None:
            out.append((i, "error", f"tear {tear.stream}: no such stream"))
            continue
        if s.kind != "material":
            out.append((i, "error", f"tear {s.id}: a {s.kind} stream; tear a material stream"))
            continue
        if s.id in seen:
            out.append((i, "error", f"tear {s.id}: named twice"))
            continue
        seen.add(s.id)
        a, b = process.ends(s)
        if a is None or b is None or a.node not in nodes or b.node not in nodes:
            out.append(
                (
                    i,
                    "error",
                    f"tear {s.id}: runs from {s.from_} to {s.to}, not between two steps (or "
                    "blocks without steps); a recycle is torn inside its loop",
                )
            )
            continue
        guess = tear.initial
        if guess is not None:
            unknown = sorted(n for n in guess.composition if n not in comps)
            if unknown:
                out.append((i, "error", f"tear {s.id}: initial names unknown {unknown}"))
            if guess.unit is not None and guess.unit not in FLOW_UNITS:
                out.append(
                    (i, "error", f"tear {s.id}: initial unit {guess.unit!r} is not a flow unit")
                )
            total = sum(guess.composition.values())
            if guess.composition and abs(total - 1.0) > COMPOSITION_SUM:
                out.append(
                    (
                        i,
                        "error",
                        f"tear {s.id}: initial {guess.basis} sum {total:.6g}, not 1 (the "
                        f"guess would start at {total:.6g} of its flow)",
                    )
                )
            if any(v < 0 for v in guess.composition.values()):
                out.append((i, "error", f"tear {s.id}: initial has a negative fraction"))
        for c in cases:
            state = s.state.get(c)
            if state is not None and _given(state.flow) and _given(state.composition):
                out.append(
                    (
                        i,
                        "warning",
                        f"tear {s.id} ({c}): flow and composition are both "
                        f"{state.flow.provenance} (a design specification): nothing to converge",
                    )
                )
    return out


def _fixed(stream: StreamDef, case: str) -> set[str]:
    state = stream.state.get(case)
    if state is None:
        return set()
    return {name for name in ("flow", "composition") if _given(getattr(state, name))}


def _composition(process: Process, mass: dict[str, float]) -> CompositionValue:
    """The composition of *mass* (kg/h by component) on propagate's basis (mole fractions where
    every molar mass is known), not rounded: the iterations would stall at the six digits of a
    written value. An empty stream has mass fractions of 0 (which no conversion needs)."""
    if sum(mass.values()) > 0:
        comps = process.components()
        mw = {n: getattr(comps.get(n), "molar_mass", None) for n in mass}
        if all(mw.values()):
            moles = {n: v / (mw[n] or 1.0) for n, v in mass.items()}
            total = sum(moles.values())
            values = {n: v / total for n, v in moles.items()}
            return CompositionValue(basis="mole_fraction", values=values, provenance="calculated")
        total = sum(mass.values())
        values = {n: v / total for n, v in mass.items()}
        return CompositionValue(basis="mass_fraction", values=values, provenance="calculated")
    if mass:
        values = dict.fromkeys(mass, 0.0)
        return CompositionValue(basis="mass_fraction", values=values, provenance="calculated")
    return CompositionValue.model_construct(
        basis="mass_fraction",
        values={},
        provenance="calculated",
        source="",
        fingerprint=None,
        uncertainty=None,
        origin=None,
    )


def _guess(process: Process, stream: StreamDef, case: str, mass: dict[str, float]) -> State:
    """The iterated fields of tear *stream* at *mass* (kg/h by component): its flow (kg/h)
    unless given or assumed, its composition unless given or assumed."""
    fixed = _fixed(stream, case)
    state = State()
    if "flow" not in fixed:
        unit = None if process.flowsheet.units.flow == "kg/h" else "kg/h"
        total = sum(mass.values())
        state.flow = Quantity(value=total, unit=unit, provenance="calculated")
    if "composition" not in fixed:
        # a component the loop does not carry, and the stream's template does not name, is
        # left out (as a still's distillate leaves its non-volatiles at 0)
        template = process.templates().get(stream.template or "")
        names = set(template.components) if template else set()
        kept = {n: v for n, v in mass.items() if v > 0 or n in names}
        state.composition = _composition(process, kept)
    return state


def _initial(process: Process, stream: StreamDef, case: str, tear: Any) -> dict[str, float]:
    """The first guess of *tear* (kg/h by component): its ``initial:``, with the stream's given
    or assumed flow or composition in place of the guess's; an empty stream by default (or, at
    a fixed flow, equal mass fractions of the stream's template)."""
    guess = tear.initial
    own = stream.state.get(case) or State()
    fixed = _fixed(stream, case)
    flow = own.flow if "flow" in fixed else None
    composition = own.composition if "composition" in fixed else None
    if flow is None:
        value = guess.flow if guess is not None else 0.0
        flow = Quantity(value=value, unit=guess.unit if guess else None, provenance="assumed")
    if composition is None:
        values = dict(guess.composition) if guess is not None else {}
        basis = guess.basis if guess is not None else "mass_fraction"
        if not values:
            template = process.templates().get(stream.template or "")
            names = list(template.components) if template else []
            share = 1.0 / len(names) if names and flow.value > 0 else 0.0
            values = dict.fromkeys(names, share)
            basis = "mass_fraction"
        composition = CompositionValue.model_construct(
            basis=basis,
            values=values,
            provenance="assumed",
            source="",
            fingerprint=None,
            uncertainty=None,
            origin=None,
        )
    probe = stream.model_copy(update={"state": {case: State(flow=flow, composition=composition)}})
    flows = stream_flows(process, probe, case)
    if flows.components is None:
        if flows.total == 0 or flow.value == 0:
            return {}
        raise ValueError(
            f"tear {stream.id}: the first guess cannot be converted to kg/h ("
            + ", ".join(flows.missing)
            + "); give initial: a flow and composition"
        )
    return dict(flows.components)


def loop_inputs(process: Process, case: str, tears: list[str]) -> str:
    """The fingerprint of the tear values in *case*: what the loops depend on, never their
    iterates. The given and assumed flow, composition, temperature, pressure and phase of every
    material stream upstream of a tear's source (the loop and what feeds it), those nodes as
    declared but for what no sweep reads (:data:`NOT_SWEPT`), their reactions, the components,
    the catalysts, the tears and the convergence settings with the tolerance."""
    from chemeascode.domains.process.propagate import ours

    fs = process.flowsheet
    nodes = _nodes(process)
    into: dict[str, list[StreamDef]] = {}
    origin: dict[str, str | None] = {}
    by_id = {s.id: s for s in fs.streams if s.kind == "material"}
    for s in by_id.values():
        a, b = process.ends(s)
        if b is not None and b.node in nodes:
            into.setdefault(b.node, []).append(s)
        origin[s.id] = a.node if a is not None and a.node in nodes else None
    todo = [origin[t] for t in tears if origin.get(t)]
    seen: set[str] = set()
    streams: dict[str, StreamDef] = {}
    while todo:
        node = todo.pop()
        if node is None or node in seen:
            continue
        seen.add(node)
        for s in into.get(node, []):
            streams[s.id] = s
            todo.append(origin[s.id])
    values: dict[str, Any] = {}
    for sid in sorted(streams):
        state = streams[sid].state.get(case)
        values[sid] = {
            name: getattr(state, name).model_dump(mode="json", exclude=NOT_INPUTS)
            for name in ("composition", "flow", "temperature", "pressure", "phase")
            if state is not None
            and getattr(state, name) is not None
            and not ours(getattr(state, name))
        }
    reactions = {}
    for node in sorted(seen):
        declared, _ = process.reactions_of(node)
        reactions[node] = [r.model_dump(mode="json") for r in declared]
    materials = process.materials
    data = {
        "tears": [t.model_dump(mode="json") for t in fs.tears],
        "convergence": (fs.convergence or Convergence()).model_dump(mode="json"),
        "tolerance": fs.tolerance.model_dump(mode="json"),
        "streams": values,
        "nodes": {
            n: nodes[n].model_dump(mode="json", by_alias=True, exclude=_not_swept(nodes[n]))
            for n in sorted(seen)
        },
        "reactions": reactions,
        "components": [
            c.model_dump(mode="json") for c in (materials.components if materials else [])
        ],
        "catalysts": process.catalysts.model_dump(mode="json") if process.catalysts else None,
    }
    return value_fingerprint(data)


def _not_swept(node: Any) -> dict[str, Any]:
    """What of *node* no sweep reads, as a ``model_dump`` exclude: :data:`NOT_SWEPT`, and what
    changes only its duty (ADR 0063: a batch's or still's ``heat_up``, an isothermal batch's
    heats of solution; the energy ports a duty is written on: a still's ``condenser_port``,
    ADR 0061, and a vent condenser's ``energy_port``, ADR 0062), which is in the duty's own
    fingerprint."""
    from chemeascode.domains.process.stirred_tank import duty_only

    found: dict[str, Any] = dict.fromkeys(NOT_SWEPT, True)
    if getattr(node, "batch", None) is not None:
        found["batch"] = duty_only(node.batch)
    if getattr(node, "still", None) is not None:
        found["still"] = {"heat_up": True, "condenser_port": True}  # as batch_still.solve_node
    return found


def _step(
    method: str,
    damping: float,
    x: dict[str, float],
    g: dict[str, float],
    last: tuple[dict[str, float], dict[str, float]] | None,
) -> dict[str, float]:
    """The next guess of one tear (kg/h by component) from the guess *x*, what the loop gave
    back *g*, and the previous pair *last*."""
    new: dict[str, float] = {}
    for n in dict.fromkeys([*g, *x]):  # the order the loop gives back
        xk, gk = x.get(n, 0.0), g.get(n, 0.0)
        if method == "substitution" or last is None:
            value = xk + (damping if method == "substitution" else 1.0) * (gk - xk)
        else:
            x0, g0 = last[0].get(n, 0.0), last[1].get(n, 0.0)
            dx = xk - x0
            if abs(dx) <= 1e-12 * max(1.0, abs(xk)):
                value = gk
            else:
                s = (gk - g0) / dx
                q = Q_MIN if s == 1.0 else s / (s - 1.0)
                q = min(Q_MAX, max(Q_MIN, q))
                value = q * xk + (1.0 - q) * gk
        new[n] = max(0.0, value)
    return new


def converge(process: Process, case: str) -> Any:
    """:func:`.propagate.derive` of a flowsheet with ``tears:``: the loops converged, the tear
    values written as calculated (or, unconverged, the sweep without the tears)."""
    from chemeascode.domains.process.propagate import _sweep

    fs = process.flowsheet
    settings = fs.convergence or Convergence()
    tol = settings.tolerance or fs.tolerance
    recycle = Recycle(method=settings.method, max_iterations=settings.max_iterations)
    streams = {s.id: s for s in fs.streams}
    problems = tear_problems(process, case)
    bad = {i for i, _, _ in problems}
    recycle.declared += [(i, lvl, fs.tears[i].stream, text) for i, lvl, text in problems]
    tears = {t.stream: t for i, t in enumerate(fs.tears) if i not in bad}
    recycle.tears = list(tears)

    def plain() -> Any:
        found = _sweep(process, case)
        found.recycle = recycle
        return found

    if not tears:
        return plain()
    index = {t.stream: i for i, t in enumerate(fs.tears)}
    x: dict[str, dict[str, float]] = {}
    for sid, tear in tears.items():
        try:
            x[sid] = _initial(process, streams[sid], case, tear)
        except ValueError as failure:
            recycle.problems.append((index[sid], sid, str(failure)))
            return plain()

    def not_closing(open_: list[str]) -> Any:
        for sid in open_:
            a, _ = process.ends(streams[sid])
            node = a.node if a is not None else streams[sid].from_
            recycle.problems.append(
                (
                    index[sid],
                    sid,
                    f"the loop torn at {sid} does not close: {node} derives no flow and "
                    f"composition for {sid} (see the not-solved findings)",
                )
            )
        return plain()

    last: dict[str, tuple[dict[str, float], dict[str, float]]] = {}
    for k in range(settings.max_iterations):
        guesses = {sid: _guess(process, streams[sid], case, x[sid]) for sid in tears}
        # unrounded: g(x) is smooth, and the loop converges to the tolerance asked for
        found = _sweep(process, case, guesses, rounded=False)
        recycle.iterations = k + 1
        given: dict[str, dict[str, float]] = {}
        back: dict[str, dict[str, float]] = {}
        open_: list[str] = []
        for sid in tears:
            g, xa = found.torn.get(sid, (None, None))
            given[sid] = xa if xa is not None else x[sid]
            if g is None:
                open_.append(sid)  # this guess does not reach back to the tear (yet)
                g = given[sid]
            back[sid] = g
        if len(open_) == len(tears) or (open_ and k + 1 == settings.max_iterations):
            return not_closing(open_)
        # the worst residual: the largest share of its tolerance (abs 0 and rel 0 allowed)
        worst: tuple[float, float, float, str, str] | None = None
        for sid in tears:
            names = list(dict.fromkeys([*back[sid], *given[sid]]))
            pairs = [(given[sid].get(n, 0.0), back[sid].get(n, 0.0), n) for n in names]
            pairs.append((sum(given[sid].values()), sum(back[sid].values()), "total"))
            for a, b, n in pairs:
                allowed = tol.abs + tol.rel * max(abs(a), abs(b))
                residual = abs(a - b)
                share = residual / allowed if allowed > 0 else (0.0 if residual == 0 else 2.0)
                if worst is None or share > worst[0]:
                    worst = (share, residual, allowed, sid, n)
        assert worst is not None
        recycle.residual, recycle.allowed = worst[1], worst[2]
        recycle.where = (worst[3], worst[4])
        if worst[0] <= 1.0:
            if open_:
                # the closed loops are converged and an open tear's guess never moves (its
                # loop gives nothing back): it will not close in further iterations
                return not_closing(open_)
            recycle.converged = True
            recycle.solution = {sid: dict(given[sid]) for sid in tears}
            return _written(process, case, recycle, tears, guesses)
        nxt = {
            sid: _step(settings.method, settings.damping, given[sid], back[sid], last.get(sid))
            for sid in tears
        }
        if open_ and not any(_moved(given[sid], nxt[sid]) for sid in tears):
            return not_closing(open_)  # stalled: no guess changes any more
        last = {sid: (given[sid], back[sid]) for sid in tears}
        x = nxt
    return plain()


def _moved(old: dict[str, float], new: dict[str, float]) -> bool:
    return any(
        abs(new.get(n, 0.0) - old.get(n, 0.0)) > 1e-12 * max(1.0, abs(old.get(n, 0.0)))
        for n in dict.fromkeys([*old, *new])
    )


def _written(
    process: Process,
    case: str,
    recycle: Recycle,
    tears: dict[str, Any],
    guesses: dict[str, State],
) -> Any:
    """The derivation of a converged loop: the tear values of the converged guess *guesses*
    rounded to the six digits propagate writes, and one rounded sweep from them (so that the
    flowsheet as written is one evaluation of the loop), the tears calculated and
    fingerprinted on the loop's inputs."""
    from chemeascode.domains.process.fill import _sig
    from chemeascode.domains.process.propagate import SOURCE, _sweep

    fs = process.flowsheet
    settings = fs.convergence or Convergence()
    streams = {s.id: s for s in fs.streams}
    rounded: dict[str, State] = {}
    for sid, guess in guesses.items():
        state = State()
        if guess.flow is not None:
            state.flow = guess.flow.model_copy(update={"value": _sig(guess.flow.value)})
        if guess.composition is not None:
            values = {n: _sig(v) for n, v in guess.composition.values.items()}
            state.composition = guess.composition.model_copy(update={"values": values})
        rounded[sid] = state
    found = _sweep(process, case, rounded)
    inputs = loop_inputs(process, case, list(tears))
    for sid in tears:
        a, _ = process.ends(streams[sid])
        node = a.node if a is not None else "?"
        into = sorted(
            s.id
            for s in fs.streams
            if s.kind == "material" and (b := process.ends(s)[1]) is not None and b.node == node
        )
        for name in ("flow", "composition"):
            value = getattr(rounded[sid], name)
            if value is None:
                continue
            found.values[(sid, name)] = value.model_copy(
                update={
                    "provenance": "calculated",
                    "source": f"{SOURCE}: recycle {node} from {' '.join(into)} "
                    f"(tear, {settings.method})",
                    "fingerprint": inputs,
                }
            )
    found.recycle = recycle
    return found
