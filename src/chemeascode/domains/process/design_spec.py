"""Design specifications in ``cheme process propagate`` (``specs:``, ADR 0070).

A design specification adjusts one variable until a target on a stream is met:

- the variable (``vary:``): the flow of a feed stream (a stream from a feed terminal), with the
  feeds that follow it at fixed ratios (``with:``, charge ratios kept), or the fraction of a
  splitter's inlet that leaves by one of its outlets (a purge, a bypass);
- the target (``target:``): a stream's flow (or one component's) in a flow unit; its amount per
  year (the flow times the operating hours, by default the recipe's ``hours_per_year``: for a
  batch plant the batch product times the batches per year, the year average of ADR 0052); the
  ratio of its flow (or a component's) to another stream's (or component's), on moles or
  masses; or a component's fraction of it.

:func:`solve` meets every specification of a case together with the loops torn at ``tears:``
(ADR 0060). Each evaluation of the loops (:func:`.recycle.converge`) first meets the
specifications at the tears' current guesses, by Newton's method on the variables with a
Jacobian from finite differences (one sweep per variable, once) kept up to date by Broyden's
update, so that a loop iterates on a flowsheet whose specifications hold. A purge loop whose
make-up holds a charge ratio then converges in a few iterations: the specification fixes the
charge, so the loop's gain, 0.995 at a 0.5 % purge, no longer slows it. Without tears, the
specifications are met on one sweep per Newton step. The iterations round nothing; the
written values come from one more sweep, rounded to the six digits propagate writes, from the
variables rounded to six digits.

Provenance (ADR 0011): an adjusted flow (and the flows that follow it) is ``calculated``, with
source ``cheme process propagate: spec <id> (<target>)`` and the fingerprint of what the
specifications depend on (:func:`spec_inputs`): the specifications, the given and assumed
values upstream of their targets, the tears and the convergence settings, the recipe's hours
and batch size. A split fraction has no place in the file: the outlets it sets are written,
and the ``cheme.process-design-spec`` finding reports the fraction.

Findings: ``cheme.process-design-spec`` (propagate) is info for the specifications met, with
the variables and the targets reached, and a warning for one that cannot be met: its target
does not depend on its variable, is not derived, lies beyond the variable's bounds, or is not
met within the iterations (nothing that depends on the specifications is then written).
``cheme.process-spec`` (validate, :func:`spec_problems`) is an error for a specification that
cannot be solved as declared.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chemeascode.domains.process.model import GAS_CONSTANT, Process
from chemeascode.domains.process.schema import FLOW_UNITS, DesignSpec, Quantity
from chemeascode.foundation.provenance import value_fingerprint

#: The relative step of a finite difference.
STEP = 1e-6
#: Times a Newton step that does not reduce the residuals is halved (from a fresh Jacobian).
HALVINGS = 8
#: The most one step changes a split fraction, and the factor it changes a flow by at most.
MAX_SPLIT = 0.25
MAX_FACTOR = 10.0


class SpecFailure(Exception):
    """A specification cannot be met: (index in the active specifications or None, message)."""

    def __init__(self, index: int | None, message: str) -> None:
        super().__init__(message)
        self.index = index
        self.message = message


@dataclass
class SpecResult:
    """One specification in one case."""

    id: str
    index: int
    #: What is adjusted: ``S1 flow`` or ``SP1 purge``.
    variable: str
    unit: str
    target: float
    target_unit: str
    #: The adjusted value (rounded as written) and the target reached with it.
    value: float | None = None
    reached: float | None = None
    met: bool = False


@dataclass
class Specs:
    """How the design specifications of a case were met (:attr:`.Derivation.specs`)."""

    results: list[SpecResult] = field(default_factory=list)
    #: Sweeps of the flowsheet, the finite differences included.
    sweeps: int = 0
    converged: bool = False
    #: (index in specs or None, spec id or "", message): why they are not met.
    problems: list[tuple[int | None, str, str]] = field(default_factory=list)
    #: (index in specs, level, spec id, message): specifications left out (:func:`spec_problems`).
    declared: list[tuple[int, str, str, str]] = field(default_factory=list)


def _applies(spec: DesignSpec, case: str) -> bool:
    return not spec.cases or case in spec.cases


def _hours(process: Process, spec: DesignSpec) -> float | None:
    """Operating hours per year of an annual target: its own, else the recipe's."""
    if spec.target.hours is not None:
        return spec.target.hours
    from chemeascode.domains.process.recipe import load_recipe

    recipe, _, _ = load_recipe(process.root)
    return recipe.hours_per_year.value if recipe is not None else None


def _feed_streams(process: Process) -> dict[str, Any]:
    """Material streams that leave a feed terminal."""
    out = {}
    for s in process.flowsheet.streams:
        a, _ = process.ends(s)
        if s.kind == "material" and a is not None and process.kinds.get(a.node) == "feed":
            out[s.id] = s
    return out


def spec_problems(process: Process, case: str | None = None) -> list[tuple[int, str, str]]:
    """(index in specs, level, message) for every specification that cannot be solved as
    declared (``cheme.process-spec``): a duplicate id or variable, an unknown case, stream,
    component or unit; a varied stream that is no feed, is a tear, or whose flow (or a
    follower's) is given or assumed in a case it holds in; a split of no splitter, of a port
    that is no outlet of it or that its ``split:`` fixes, or that leaves the splitter no outlet
    for the remainder (with its ``split:`` and the other specifications in a case); a split's
    bounds or initial value outside [0, 1]; an initial value outside the bounds; an annual
    target without operating hours; a target on its own variable."""
    from chemeascode.domains.process.propagate import behaviour, ours

    fs = process.flowsheet
    streams = {s.id: s for s in fs.streams}
    feeds = _feed_streams(process)
    comps = process.components()
    torn = {t.stream for t in fs.tears}
    cases = {c.id for c in fs.cases}
    out: list[tuple[int, str, str]] = []
    ids: set[str] = set()
    varied: dict[str, str] = {}
    #: splitter -> (spec index, varied outlet, cases the spec holds in)
    splits: dict[str, list[tuple[int, str, list[str]]]] = {}
    for i, spec in enumerate(fs.specs):

        def err(message: str, spec: DesignSpec = spec, i: int = i) -> None:
            out.append((i, "error", f"spec {spec.id}: {message}"))

        if spec.id in ids:
            err("id named twice")
        ids.add(spec.id)
        unknown_cases = [c for c in spec.cases if c not in cases]
        if unknown_cases:
            err(f"cases {unknown_cases} are not declared")
        holds = [c for c in (spec.cases or sorted(cases)) if c in cases]
        if case is not None:
            holds = [c for c in holds if c == case]
        v = spec.vary
        low = v.low if v.low is not None else 0.0
        high = v.high if v.high is not None else (1.0 if v.node is not None else None)
        if v.node is not None and max(low, high or 0.0, v.initial) > 1.0:
            err(
                f"vary: a split's low, high and initial lie within [0, 1] (low {low:g}, "
                f"high {high:g}, initial {v.initial:g})"
            )
        elif high is not None and low >= high:
            err(f"vary: low {low:g} is not below high {high:g}")
        elif not (low <= v.initial and (high is None or v.initial <= high)):
            top = "inf" if high is None else f"{high:g}"
            err(f"vary: initial {v.initial:g} outside [{low:g}, {top}]")
        names: list[str] = []
        if v.stream is not None:
            names = [v.stream, *v.with_]
            if v.unit is not None and v.unit not in FLOW_UNITS:
                err(f"vary: unit {v.unit!r} is not a flow unit")
            for k, sid in enumerate(names):
                role = "vary" if k == 0 else "vary.with"
                s = streams.get(sid)
                if s is None or s.kind != "material":
                    err(f"{role} {sid}: no such material stream")
                    continue
                if sid not in feeds:
                    err(f"{role} {sid}: not a feed stream (from a feed terminal)")
                if sid in torn:
                    err(f"{role} {sid}: a tear stream")
                for c in holds:
                    state = s.state.get(c)
                    flow = state.flow if state is not None else None
                    if flow is not None and not ours(flow):
                        err(
                            f"{role} {sid} ({c}): its flow is {flow.provenance}; the spec "
                            "writes it (remove it, or give it as vary.initial)"
                        )
        else:
            node = process.nodes.get(v.node or "")
            if node is None or process.kinds.get(v.node or "") not in ("step", "block"):
                err(f"vary: node {v.node} is no step or block")
            elif behaviour(node.class_) != "splitter" or getattr(node, "recovery", None):
                err(f"vary: {v.node} is no splitter (class SplittingMaterial)")
            else:
                outs = [p.id for p in node.ports if p.direction == "out" and p.kind == "material"]
                if v.port not in outs:
                    err(f"vary: {v.port} is no material outlet port of {v.node}")
                elif v.port in node.split:  # type: ignore[attr-defined]
                    err(f"vary: {v.node}'s split: fixes {v.port}; leave it out of split:")
                else:
                    splits.setdefault(node.id, []).append((i, v.port, holds or [""]))
            names = [f"{v.node}.{v.port}"]
        for name in names:
            if name in varied:
                err(f"{name} is varied by spec {varied[name]} too")
            varied.setdefault(name, spec.id)
        t = spec.target
        for sid, component, role in (
            (t.stream, t.component, "target"),
            *([(t.per.stream, t.per.component, "target.per")] if t.per else []),
        ):
            s = streams.get(sid)
            if s is None or s.kind != "material":
                err(f"{role} {sid}: no such material stream")
            if component is not None and component not in comps:
                err(f"{role} component {component} is not declared")
        if t.quantity == "flow" and t.unit is not None and t.unit not in FLOW_UNITS:
            err(f"target: unit {t.unit!r} is not a flow unit")
        if t.quantity == "annual" and _hours(process, spec) is None:
            err("target: annual needs hours (or process/recipe.yaml's hours_per_year)")
        if v.stream is not None and t.stream in names and t.quantity in ("flow", "annual"):
            err(f"target: {t.stream}'s flow is the variable itself")
    # a splitter keeps one material outlet for the remainder of its mass balance in every case
    for nid, entries in splits.items():
        node = process.nodes[nid]
        outs = {p.id for p in node.ports if p.direction == "out" and p.kind == "material"}
        fixed = set(node.split)  # type: ignore[attr-defined]
        flagged: set[int] = set()
        for c in dict.fromkeys(c for _, _, holds in entries for c in holds):
            here = [(i, port) for i, port, holds in entries if c in holds]
            if not outs <= fixed | {port for _, port in here}:
                continue
            by = f"split: fixes {sorted(fixed)}, " if fixed else ""
            by += f"specs vary {sorted(port for _, port in here)}"
            for i, _ in here:
                if i not in flagged:
                    flagged.add(i)
                    out.append(
                        (
                            i,
                            "error",
                            f"spec {fs.specs[i].id}: vary: {nid} has no outlet left for the "
                            f"remainder{f' ({c})' if c else ''} ({by}); leave one outlet to "
                            "the mass balance",
                        )
                    )
    return out


def _amount(
    process: Process, mass: dict[str, float], component: str | None, basis: str
) -> float | None:
    """kg/h (mass) or kmol/h (mole) of *component* (None: all) in *mass* (kg/h by component);
    None without a molar mass it needs."""
    names = [component] if component is not None else list(mass)
    if basis == "mass":
        return sum(mass.get(n, 0.0) for n in names)
    comps = process.components()
    total = 0.0
    for n in names:
        value = mass.get(n, 0.0)
        if value == 0.0:
            continue
        mw = getattr(comps.get(n), "molar_mass", None)
        if not mw:
            return None
        total += value / mw
    return total


def target_text(process: Process, spec: DesignSpec) -> tuple[float, str]:
    """The target's value and how it reads (``S15 flow kg/h``)."""
    t = spec.target
    what = f"{t.stream}{' ' + t.component if t.component else ''}"
    if t.quantity == "flow":
        return t.value, f"{what} flow {t.unit or process.flowsheet.units.flow}"
    if t.quantity == "annual":
        return t.value, f"{what} {t.unit or 't'}/a"
    basis = t.basis or "mole"
    if t.quantity == "fraction":
        return t.value, f"{what} {basis} fraction"
    assert t.per is not None
    per = f"{t.per.stream}{' ' + t.per.component if t.per.component else ''}"
    return t.value, f"{what} per {per} ({basis})"


def measure(
    process: Process, spec: DesignSpec, measured: dict[str, dict[str, float] | None]
) -> float | None:
    """The target quantity of *spec* from the component flows *measured* (kg/h); None when the
    stream (or the ratio's denominator) has none or a molar mass is missing."""
    fs = process.flowsheet
    t = spec.target
    mass = measured.get(t.stream)
    if mass is None:
        return None
    if t.quantity in ("flow", "annual"):
        if t.quantity == "annual":
            hours = _hours(process, spec) or 0.0
            kg = _amount(process, mass, t.component, "mass")
            return None if kg is None else kg * hours / (1000.0 if (t.unit or "t") == "t" else 1.0)
        unit = t.unit or fs.units.flow
        basis, factor = FLOW_UNITS[unit]
        amount = _amount(process, mass, t.component, "mass" if basis == "mass" else "mole")
        if amount is None:
            return None
        if basis == "normal_volume":
            nc = fs.units.normal_conditions
            if nc is None:
                return None
            amount = amount * GAS_CONSTANT * nc.temperature / nc.pressure  # Nm3/h
        return amount / factor
    basis = t.basis or "mole"
    num = _amount(process, mass, t.component, basis)
    if t.quantity == "fraction":
        den = _amount(process, mass, None, basis)
    else:
        assert t.per is not None
        other = measured.get(t.per.stream)
        den = _amount(process, other, t.per.component, basis) if other is not None else None
    if num is None or not den:
        return None
    return num / den


def spec_inputs(process: Process, case: str) -> str:
    """The fingerprint of the values the specifications of *case* set: the specifications, the
    given and assumed values upstream of their targets (:func:`.recycle.upstream`) and of the
    target streams, the tears and the convergence settings, and the recipe's hours and batch
    size (they set an annual target and the batch models' hours of flows)."""
    from chemeascode.domains.process.propagate import ours
    from chemeascode.domains.process.recipe import load_recipe
    from chemeascode.domains.process.recycle import upstream
    from chemeascode.foundation.provenance import NOT_INPUTS

    fs = process.flowsheet
    ends = [s.target.stream for s in fs.specs]
    ends += [s.target.per.stream for s in fs.specs if s.target.per]
    data = upstream(process, case, ends)
    streams = {s.id: s for s in fs.streams}
    own: dict[str, Any] = {}
    for sid in sorted(set(ends)):
        state = streams[sid].state.get(case) if sid in streams else None
        own[sid] = {
            name: getattr(state, name).model_dump(mode="json", exclude=NOT_INPUTS)
            for name in ("composition", "flow")
            if state is not None
            and getattr(state, name) is not None
            and not ours(getattr(state, name))
        }
    data["targets"] = own
    data["specs"] = [s.model_dump(mode="json", by_alias=True) for s in fs.specs]
    recipe, _, _ = load_recipe(process.root)
    if recipe is not None:
        data["recipe"] = {
            "batch_size": recipe.batch_size.model_dump(mode="json", exclude=NOT_INPUTS),
            "hours_per_year": recipe.hours_per_year.value,
        }
    return value_fingerprint(data)


def _linear(a: list[list[float]], b: list[float]) -> list[float] | None:
    """x with a x = b (Gaussian elimination, partial pivoting); None when *a* is singular."""
    n = len(b)
    m = [[*row, rhs] for row, rhs in zip(a, b, strict=True)]
    scale = max((abs(v) for row in a for v in row), default=0.0)
    if scale == 0.0:
        return None
    for k in range(n):
        pivot = max(range(k, n), key=lambda r: abs(m[r][k]))
        if abs(m[pivot][k]) <= 1e-14 * scale:
            return None
        m[k], m[pivot] = m[pivot], m[k]
        for r in range(k + 1, n):
            f = m[r][k] / m[k][k]
            for c in range(k, n + 1):
                m[r][c] -= f * m[k][c]
    x = [0.0] * n
    for k in reversed(range(n)):
        x[k] = (m[k][n] - sum(m[k][c] * x[c] for c in range(k + 1, n))) / m[k][k]
    return x


def newton_step(jac: list[list[float]], f: list[float]) -> list[float] | None:
    """The step d with jac d = -f; where *jac* is singular (a tear whose flow or composition is
    fixed has a direction its residual does not see), the least-squares step with a vanishing
    Levenberg-Marquardt term, which takes no step along such a direction. None when nothing
    can be solved."""
    step = _linear(jac, [-v for v in f])
    if step is not None:
        return step
    n = len(f)
    normal = [
        [sum(jac[k][i] * jac[k][j] for k in range(len(f))) for j in range(n)] for i in range(n)
    ]
    rhs = [-sum(jac[k][i] * f[k] for k in range(len(f))) for i in range(n)]
    mu = 1e-10 * max((normal[i][i] for i in range(n)), default=0.0)
    if mu == 0.0:
        return None
    for i in range(n):
        normal[i][i] += mu
    return _linear(normal, rhs)


@dataclass
class _Point:
    """One evaluation of the flowsheet: the sweep, the tears' iterates (what each was given)
    and what their loops gave back (kg/h by component), and the specifications' residuals
    (relative to their targets)."""

    found: Any
    given: dict[str, dict[str, float]]
    back: dict[str, dict[str, float]]
    open_: list[str]
    r: list[float | None]


class _Solver:
    """The tears' component flows and the specifications' variables, solved together: Newton's
    method with a Jacobian from finite differences, kept up to date by Broyden's update."""

    def __init__(
        self,
        process: Process,
        case: str,
        active: list[tuple[int, DesignSpec]],
        tears: dict[str, Any],
    ):
        from chemeascode.domains.process.propagate import Settings
        from chemeascode.domains.process.schema import Convergence

        self.process, self.case, self.active, self.tears = process, case, active, tears
        fs = process.flowsheet
        settings = fs.convergence or Convergence()
        self.max_iterations = settings.max_iterations
        self.tol = settings.tolerance or fs.tolerance
        self.streams = {s.id: s for s in fs.streams}
        self.lows = [s.vary.low or 0.0 for _, s in active]
        self.highs = [
            s.vary.high
            if s.vary.high is not None
            else (1.0 if s.vary.node is not None else float("inf"))
            for _, s in active
        ]
        self.u = [s.vary.initial for _, s in active]
        self.targets = [s.target.value for _, s in active]
        self.scales = [abs(v) if v > 0 else 1.0 for v in self.targets]
        self.sweeps = 0
        self.iterations = 0
        measured = [s.target.stream for _, s in active]
        measured += [s.target.per.stream for _, s in active if s.target.per]
        self.measure = tuple(dict.fromkeys(measured))
        self.settings_type = Settings
        self.flow_unit = fs.units.flow
        #: (tear, component) of every iterated tear flow, in order.
        self.keys: list[tuple[str, str]] = []
        #: the worst residual's share of its tolerance, the residual, what it allows, where
        self.worst: tuple[float, float, float, str, str] | None = None
        #: the scale of each variable (the finite difference's step over STEP)
        self.colscale: list[float] = []
        #: the sweep of the last evaluation (its nodes' problems explain a failure)
        self.last: Any = None

    # -- one evaluation -----------------------------------------------------------------------

    def settings(self, u: list[float], rounded: bool = False) -> Any:
        from chemeascode.domains.process.fill import _sig

        st = self.settings_type(measure=self.measure)
        for (_, spec), value in zip(self.active, u, strict=True):
            v = spec.vary
            value = _sig(value) if rounded else value
            if v.stream is not None:
                unit = v.unit if v.unit not in (None, self.flow_unit) else None
                st.flows[v.stream] = Quantity(value=value, unit=unit, provenance="calculated")
                for sid, ratio in v.with_.items():
                    part = _sig(ratio * value) if rounded else ratio * value
                    st.flows[sid] = Quantity(value=part, unit=unit, provenance="calculated")
            else:
                st.splits[(v.node or "", v.port or "")] = value
        return st

    def sweep(self, guesses: Any, u: list[float], rounded: bool = False) -> Any:
        from chemeascode.domains.process.propagate import _sweep

        self.sweeps += 1
        return _sweep(
            self.process,
            self.case,
            guesses or None,
            rounded=rounded,
            settings=self.settings(u, rounded=rounded),
        )

    def guesses(self, x: dict[str, dict[str, float]]) -> dict[str, Any]:
        from chemeascode.domains.process.recycle import _guess

        return {sid: _guess(self.process, self.streams[sid], self.case, x[sid]) for sid in x}

    def evaluate(self, x: dict[str, dict[str, float]], u: list[float]) -> _Point:
        found = self.sweep(self.guesses(x), u)
        self.last = found
        given: dict[str, dict[str, float]] = {}
        back: dict[str, dict[str, float]] = {}
        open_: list[str] = []
        for sid in self.tears:
            g, xa = found.torn.get(sid, (None, None))
            given[sid] = dict(xa) if xa is not None else dict(x[sid])
            if g is None:
                open_.append(sid)
                g = given[sid]
            back[sid] = dict(g)
        r: list[float | None] = []
        for (_, spec), target, scale in zip(self.active, self.targets, self.scales, strict=True):
            value = measure(self.process, spec, found.measured)
            r.append(None if value is None else (value - target) / scale)
        return _Point(found, given, back, open_, r)

    def usable(self, p: _Point) -> bool:
        return not p.open_ and all(v is not None for v in p.r)

    # -- the residual vector ------------------------------------------------------------------

    def extend(self, p: _Point) -> bool:
        """Adds the components a loop newly carries to the iterated ones; whether any was."""
        known = set(self.keys)
        new = [
            (sid, n)
            for sid in self.tears
            for n in dict.fromkeys([*p.given[sid], *p.back[sid]])
            if (sid, n) not in known
        ]
        self.keys += new
        return bool(new)

    def vector(self, p: _Point) -> tuple[list[float], list[float]]:
        """The residuals g - x of every iterated tear flow and the specifications', each also
        over its tolerance (a share of 1 or less is converged)."""
        f: list[float] = []
        shares: list[float] = []
        worst: tuple[float, float, float, str, str] | None = None
        for sid, n in self.keys:
            a, b = p.given[sid].get(n, 0.0), p.back[sid].get(n, 0.0)
            allowed = self.tol.abs + self.tol.rel * max(abs(a), abs(b))
            f.append(b - a)
            share = abs(b - a) / allowed if allowed > 0 else (0.0 if a == b else 2.0)
            shares.append(share)
            if worst is None or share > worst[0]:
                worst = (share, abs(b - a), allowed, sid, n)
        for sid in self.tears:  # each tear's total too (as ADR 0060)
            a, b = sum(p.given[sid].values()), sum(p.back[sid].values())
            allowed = self.tol.abs + self.tol.rel * max(abs(a), abs(b))
            share = abs(b - a) / allowed if allowed > 0 else (0.0 if a == b else 2.0)
            if worst is None or share > worst[0]:
                worst = (share, abs(b - a), allowed, sid, "total")
        self.worst = worst
        for value, (_, spec) in zip(p.r, self.active, strict=True):
            f.append(value or 0.0)
            shares.append(abs(value or 0.0) / spec.tolerance)
        return f, shares

    def merit(self, p: _Point) -> float:
        """What a step must reduce: the squares of the tears' residuals relative to each tear's
        flow and of the specifications' relative residuals."""
        total = 0.0
        for sid in self.tears:
            names = dict.fromkeys([*p.given[sid], *p.back[sid]])
            size = max(sum(p.given[sid].values()), sum(p.back[sid].values()), 1e-9)
            total += sum(
                ((p.back[sid].get(n, 0.0) - p.given[sid].get(n, 0.0)) / size) ** 2 for n in names
            )
        return total + sum((v or 0.0) ** 2 for v in p.r)

    def converged(self, p: _Point) -> bool:
        _, shares = self.vector(p)
        tears_ok = self.worst is None or self.worst[0] <= 1.0
        return tears_ok and all(s <= 1.0 for s in shares[len(self.keys) :])

    # -- variables ----------------------------------------------------------------------------

    def z_of(self, x: dict[str, dict[str, float]], u: list[float]) -> list[float]:
        return [x[sid].get(n, 0.0) for sid, n in self.keys] + list(u)

    def split(self, z: list[float]) -> tuple[dict[str, dict[str, float]], list[float]]:
        """The tear flows (at least 0) and the variables (within their bounds) of *z*."""
        nt = len(z) - len(self.active)
        x: dict[str, dict[str, float]] = {sid: {} for sid in self.tears}
        for (sid, n), value in zip(self.keys[:nt], z[:nt], strict=True):
            x[sid][n] = max(0.0, value)
        u = z[nt:]
        return x, [min(h, max(lo, v)) for v, lo, h in zip(u, self.lows, self.highs, strict=True)]

    def describe(self, k: int, value: float) -> str:
        v = self.active[k][1].vary
        if v.stream is not None:
            return f"{v.stream} flow {value:.6g} {v.unit or self.flow_unit}"
        return f"{v.node}.{v.port} {value:.6g}"

    def jacobian(self, p: _Point, u: list[float], f: list[float]) -> list[list[float]]:
        """By finite differences at *p*: one sweep per variable, but for a tear flow that is 0
        and that its loop gives back as 0 (a component the loop does not carry), whose column
        is that of substitution."""
        z = self.z_of(p.given, u)
        n = len(z)
        jac = [[0.0] * n for _ in range(n)]
        totals = {
            sid: max(sum(p.given[sid].values()), sum(p.back[sid].values())) for sid in self.tears
        }
        self.colscale = [1.0] * n
        for j in range(n):
            if j < len(self.keys):
                sid, name = self.keys[j]
                back = p.back[sid].get(name, 0.0)
                if z[j] == 0.0 and back == 0.0:
                    jac[j][j] = -1.0
                    continue
                self.colscale[j] = max(abs(z[j]), abs(back), 1e-3 * totals[sid], 1e-9)
            else:
                k = j - len(self.keys)
                floor = 1e-3 if self.active[k][1].vary.node else 1e-6
                self.colscale[j] = max(abs(z[j]), floor)
            h = STEP * self.colscale[j]
            if j >= len(self.keys) and z[j] + h > self.highs[j - len(self.keys)]:
                h = -h
            probe = list(z)
            probe[j] += h
            x, uu = self.split(probe)
            q = self.evaluate(x, uu)
            if not self.usable(q):
                if j >= len(self.keys):
                    k = j - len(self.keys)
                    raise self._missing(q, k, uu)
                jac[j][j] = -1.0  # the loop does not close at the probe: substitution
                continue
            fq, _ = self.vector(q)  # a component only the probe carries is left out here
            for i in range(n):
                jac[i][j] = (fq[i] - f[i]) / h
        return jac

    # -- failures -----------------------------------------------------------------------------

    def _missing(self, p: _Point, k: int | None, u: list[float]) -> SpecFailure:
        if p.open_:
            return SpecFailure(
                None,
                f"the loop torn at {', '.join(p.open_)} does not close at "
                + ", ".join(self.describe(i, v) for i, v in enumerate(u))
                + " (see the not-solved findings)",
            )
        if k is None:
            k = next(i for i, v in enumerate(p.r) if v is None)
        spec = self.active[k][1]
        t = spec.target
        streams = t.stream + (f" or {t.per.stream}" if t.per else "")
        return SpecFailure(
            k,
            f"{streams} has no flow and composition at {self.describe(k, u[k])} (see the "
            "not-solved findings), or a molar mass the target needs is missing",
        )

    def _bound(self, k: int, u: list[float], r: float, at: list[int] | None = None) -> SpecFailure:
        """Spec *k* not met with the variables *at* (default its own) held at a bound."""
        spec = self.active[k][1]
        value, text = target_text(self.process, spec)
        reached = value + r * self.scales[k]
        at = [k] if at is None else at
        where = ", ".join(self.describe(j, u[j]) for j in at)
        whose = "its variable" if at == [k] else "the variables"
        return SpecFailure(
            k,
            f"cannot be met within the bounds of {whose}: at {where} "
            f"({'a bound' if len(at) == 1 else 'bounds'}) {text} is {reached:.6g}, the target "
            f"{value:.6g}",
        )

    def bounded(self, u: list[float]) -> list[int]:
        """The variables at a bound of theirs."""
        return [j for j, v in enumerate(u) if v in (self.lows[j], self.highs[j])]

    # -- the iterations -----------------------------------------------------------------------

    def solve(self, x0: dict[str, dict[str, float]]) -> tuple[_Point, dict, list[float]]:
        """The converged point, tear flows and variables from the tears' first guesses *x0*.
        Raises SpecFailure."""
        u = list(self.u)
        p = self.evaluate(x0, u)
        if not self.usable(p):
            raise self._missing(p, None, u)
        self.keys = []
        for sid in self.tears:  # the guess's components, then what the loop gives back
            self.keys += [(sid, n) for n in dict.fromkeys([*x0[sid], *p.back[sid]])]
        jac: list[list[float]] | None = None
        fresh = False
        pinned = [0] * len(u)
        while True:
            f, shares = self.vector(p)
            if self.converged(p):
                return p, p.given, u
            if self.iterations >= self.max_iterations:
                raise SpecFailure(None, self._unmet(p))
            self.iterations += 1
            if jac is None:
                jac = self.jacobian(p, u, f)
                fresh = True
            nt = len(self.keys)
            for k in range(len(u)):
                if abs(f[nt + k]) > self.active[k][1].tolerance and all(
                    abs(v) * c <= 1e-9 for v, c in zip(jac[nt + k], self.colscale, strict=True)
                ):
                    # at a bound the flowsheet can be degenerate (a split of 1 empties the loop
                    # torn after it, whose tear then gives back nothing): the bound is the cause
                    if at := self.bounded(u):
                        raise self._bound(k, u, f[nt + k], at=[k] if k in at else at)
                    raise SpecFailure(
                        k,
                        f"its target ({self.active[k][1].target.stream}) does not depend on "
                        "the variables at "
                        + ", ".join(self.describe(i, v) for i, v in enumerate(u)),
                    )
            step = newton_step(jac, f)
            if step is None:
                raise SpecFailure(None, "the variables do not move the targets (singular)")
            z = self.z_of(p.given, u)
            # a step moves a split by MAX_SPLIT at most and a flow by MAX_FACTOR, the whole
            # step shortened alike (its direction kept)
            nt = len(self.keys)
            limit = 1.0
            for k, d in enumerate(step[nt:]):
                if self.active[k][1].vary.node is not None:
                    bound = MAX_SPLIT
                else:
                    scale = max(u[k], 1e-6)
                    bound = (
                        (MAX_FACTOR - 1.0) * scale if d > 0 else (1.0 - 1.0 / MAX_FACTOR) * scale
                    )
                if abs(d) > bound:
                    limit = min(limit, bound / abs(d))
            wanted = [a + limit * b for a, b in zip(z, step, strict=True)]
            norm = self.merit(p)
            accepted = None
            lam = 1.0
            for _ in range(HALVINGS if fresh else 1):
                trial = [a + lam * (b - a) for a, b in zip(z, wanted, strict=True)]
                x, uu = self.split(trial)
                q = self.evaluate(x, uu)
                if self.usable(q):
                    grew = self.extend(q)
                    if grew or self.merit(q) < norm or self.converged(q):
                        accepted = (q, x, uu, trial)
                        break
                lam /= 2.0
            if accepted is None:
                if not fresh:
                    jac = None  # Broyden's Jacobian is off: differences again, then retry
                    continue
                raise SpecFailure(None, self._unmet(p, stalled=True))
            q, x, uu, trial = accepted
            for k in range(len(u)):
                # a variable held at its bound while its target is not met, twice running
                unmet = abs(q.r[k] or 0.0) > self.active[k][1].tolerance
                held = uu[k] == u[k] and uu[k] in (self.lows[k], self.highs[k])
                pinned[k] = pinned[k] + 1 if held and unmet else 0
                if pinned[k] >= 2:
                    raise self._bound(k, uu, q.r[k] or 0.0)
            if len(self.vector(q)[0]) != len(f):
                jac = None  # new components: differences again
            else:
                fq, _ = self.vector(q)
                dz = [b - a for a, b in zip(z, self.z_of(q.given, uu), strict=True)]
                df = [b - a for a, b in zip(f, fq, strict=True)]
                dd = sum(d * d for d in dz)
                if dd > 0:  # Broyden's (good) update
                    jdz = [sum(row[j] * dz[j] for j in range(len(dz))) for row in jac]
                    for i, row in enumerate(jac):
                        for j in range(len(dz)):
                            row[j] += (df[i] - jdz[i]) * dz[j] / dd
                fresh = False
            p, u = q, uu
            self.u = u

    def _unmet(self, p: _Point, stalled: bool = False) -> str:
        why = (
            "no step reduces the residuals"
            if stalled
            else (f"not met in {self.iterations} iteration(s)")
        )
        parts = []
        for value, (_, spec) in zip(p.r, self.active, strict=True):
            if value is not None and abs(value) > spec.tolerance:
                parts.append(f"{spec.id} {value:.3g} of its target")
        if self.worst is not None and self.worst[0] > 1.0:
            parts.append(
                f"tear {self.worst[3]} {self.worst[4]} {self.worst[1]:.3g} kg/h against "
                f"{self.worst[2]:.3g} kg/h"
            )
        return f"{why} (Newton-Broyden); residuals: " + (", ".join(parts) or "none")


def solve(process: Process, case: str) -> Any:
    """:func:`.propagate.derive` of a flowsheet with ``specs:``: the specifications met together
    with the tears, the adjusted flows written as calculated; when a specification cannot be
    met, the derivation without the specifications and tears (nothing that depends on them is
    written)."""
    from chemeascode.domains.process.propagate import SOURCE, _sweep
    from chemeascode.domains.process.recycle import Recycle, _initial, _written, tear_problems
    from chemeascode.domains.process.schema import Convergence

    fs = process.flowsheet
    result = Specs()
    problems = spec_problems(process, case)
    bad = {i for i, level, _ in problems if level == "error"}
    result.declared = [(i, lvl, fs.specs[i].id, text) for i, lvl, text in problems]
    active = [(i, s) for i, s in enumerate(fs.specs) if i not in bad and _applies(s, case)]
    settings = fs.convergence or Convergence()
    recycle = Recycle(method="broyden", max_iterations=settings.max_iterations)
    tear_bad = tear_problems(process, case)
    recycle.declared = [(i, lvl, fs.tears[i].stream, text) for i, lvl, text in tear_bad]
    skipped = {i for i, _, _ in tear_bad}
    tears = {t.stream: t for i, t in enumerate(fs.tears) if i not in skipped}
    recycle.tears = list(tears)
    streams = {s.id: s for s in fs.streams}

    def plain(problem: tuple[int | None, str, str] | None = None) -> Any:
        if problem is not None:
            result.problems.append(problem)
        if fs.tears and not active:
            from chemeascode.domains.process.recycle import converge

            found = converge(process, case)
        else:
            found = _sweep(process, case)
            found.recycle = recycle if fs.tears else None
        found.specs = result
        return found

    for k, spec in active:
        value, text = target_text(process, spec)
        v = spec.vary
        result.results.append(
            SpecResult(
                id=spec.id,
                index=k,
                variable=f"{v.stream} flow" if v.stream else f"{v.node}.{v.port}",
                unit=(v.unit or fs.units.flow) if v.stream else "",
                target=value,
                target_unit=text,
            )
        )
    if not active:
        return plain()
    solver = _Solver(process, case, active, tears)
    x0: dict[str, dict[str, float]] = {}
    for sid, tear in tears.items():
        try:
            x0[sid] = _initial(process, streams[sid], case, tear)
        except ValueError as failure:
            index = next(i for i, t in enumerate(fs.tears) if t.stream == sid)
            recycle.problems.append((index, sid, str(failure)))
            return plain((None, "", f"tear {sid}: {failure}"))
    try:
        point, x, u = solver.solve(x0)
    except SpecFailure as failure:
        index = active[failure.index][0] if failure.index is not None else None
        sid = fs.specs[index].id if index is not None else ""
        result.sweeps = solver.sweeps
        if tears:
            recycle.iterations = solver.iterations
            recycle.residual = solver.worst[1] if solver.worst else None
            recycle.allowed = solver.worst[2] if solver.worst else None
            recycle.where = (solver.worst[3], solver.worst[4]) if solver.worst else None
            recycle.problems.append(
                (None, ", ".join(tears), "not converged with the design specifications")
            )
        found = plain((index, sid, failure.message))
        _carry(found, solver.last)
        return found
    solver.u = u
    inputs = spec_inputs(process, case)

    def final(guesses: Any) -> Any:
        found = solver.sweep(guesses, u, rounded=True)
        rounded = solver.settings(u, rounded=True)
        for (_, spec), entry in zip(active, result.results, strict=True):
            v = spec.vary
            _, text = target_text(process, spec)
            label = f"{text} {spec.target.value:.6g}"
            if v.stream is not None:
                entry.value = rounded.flows[v.stream].value
                for sid in [v.stream, *v.with_]:
                    how = f"spec {spec.id} ({label})"
                    if sid != v.stream:
                        how = f"spec {spec.id} ({v.with_[sid]:.6g} x {v.stream})"
                    found.values[(sid, "flow")] = rounded.flows[sid].model_copy(
                        update={"source": f"{SOURCE}: {how}", "fingerprint": inputs}
                    )
            else:
                entry.value = rounded.splits[(v.node or "", v.port or "")]
            entry.reached = measure(process, spec, found.measured)
            entry.met = True
        return found

    result.converged = True
    if tears:
        recycle.converged = True
        recycle.iterations = solver.iterations
        recycle.solution = {sid: dict(x[sid]) for sid in tears}
        if solver.worst is not None:
            recycle.residual, recycle.allowed = solver.worst[1], solver.worst[2]
            recycle.where = (solver.worst[3], solver.worst[4])
        guesses = solver.guesses(x)
        found = _written(process, case, recycle, tears, guesses, final)
    else:
        found = final(None)
    result.sweeps = solver.sweeps
    found.specs = result
    return found


#: The node problems of a :class:`.propagate.Derivation` (node id first).
_NODE_PROBLEMS = ("problems", "solids", "stills", "separators")


def _carry(found: Any, last: Any) -> None:
    """The node problems of the evaluation a specification failed at (*last*) added to the
    derivation without the specifications (*found*), where the nodes may not be reached at all:
    they say why the target has no value."""
    if last is None:
        return
    for name in _NODE_PROBLEMS:
        into = getattr(found, name)
        into += [p for p in getattr(last, name) if p not in into]


def spec_findings(found: Any, case: str, *, declared: bool = True) -> list[tuple]:
    """(level, message, location, ids, hint) of the ``cheme.process-design-spec`` findings of
    *found*: a specification left out (unless not *declared*), one that cannot be met
    (warnings), and those met (info, with the variables and the targets reached)."""
    specs = found.specs
    if specs is None:
        return []
    out = []
    for i, _level, sid, message in specs.declared if declared else []:
        out.append(
            (
                "warning",
                f"{message} ({case}); left out",
                ["specs", i],
                [sid],
                "correct specs: (cheme validate reports it as cheme.process-spec)",
            )
        )
    for i, sid, message in specs.problems:
        out.append(
            (
                "warning",
                f"spec {sid or '(all)'} ({case}): {message}; nothing that depends on the "
                "specifications is written",
                ["specs", i] if i is not None else ["specs"],
                [sid] if sid else [],
                "check that the target depends on the variable, start from a closer "
                "vary.initial, widen low/high, or correct the target (a rate the feeds cannot "
                "reach, a ratio a recycle fixes)",
            )
        )
    if specs.problems:
        return out
    for entry in specs.results:
        if not entry.met:
            continue
        unit = f" {entry.unit}" if entry.unit else ""
        reached = f"{entry.reached:.6g}" if entry.reached is not None else "?"
        out.append(
            (
                "info",
                f"spec {entry.id} ({case}): {entry.variable} {entry.value:.6g}{unit} gives "
                f"{entry.target_unit} {reached} (target {entry.target:.6g}); "
                f"{specs.sweeps} sweep(s)",
                ["specs", entry.index],
                [entry.id],
                "the adjusted flows are calculated (cheme process propagate --fill writes "
                "them); a split's fraction is reported here only; with a recipe, "
                "cheme.recipe-basis gives the batch size whose cycle makes the rate",
            )
        )
    return out


def rules(process: Any) -> list[Any]:
    """``cheme.process-spec`` findings of validate (:func:`spec_problems`)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.foundation.findings import Finding
    from chemeascode.foundation.yamlsource import _yaml_line

    specs = process.flowsheet.specs
    return [
        Finding(
            FLOWSHEET_FILE,
            level,  # type: ignore[arg-type]
            "cheme.process-spec",
            message,
            line=_yaml_line(process.flowsheet_doc, ["specs", i]),
            ids=[specs[i].id],
            hint="vary a feed stream's flow (not given or assumed; vary.initial is the first "
            "guess) or a splitter outlet not in its split:, and target a material stream "
            "in declared components and units",
        )
        for i, level, message in spec_problems(process)
    ]
