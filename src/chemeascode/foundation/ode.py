"""An adaptive integrator for ordinary differential equations ``dy/dt = f(t, y)``: the explicit
Dormand-Prince 5(4) pair with step-size control, its continuous extension of order 4 (dense
output) and the location of events on it. Pure Python on lists of floats: no engineering
knowledge, no numpy or scipy; the right-hand side and the event functions carry the subject.

:func:`solve` integrates from ``t0`` to ``t_end`` (forward in time). A step is accepted when
the root-mean-square of its error estimate, each component scaled by
``atol_i + rtol * max(|y_i|, |y_new_i|)``, is at most 1 (Hairer, Norsett and Wanner, Solving
Ordinary Differential Equations I, 2nd ed., Springer 1993, II.4 and II.6); the next step is
``h * min(10, max(0.2, 0.9 err**(-1/5)))``. A step whose right-hand side or error is not
finite is rejected and retried with a fifth of the step. With ``error_components`` only the
first that many components enter the error control (and the first step's estimate); the rest
are quadratures (running integrals) integrated on the same steps with the same stages, so a
linear combination of components the right-hand side keeps constant stays constant to
rounding, and adding a quadrature does not change the steps taken.

An :class:`Event` is a function ``g(t, y)`` whose zero is wanted. After every accepted step its
sign at both ends is compared; a change (in the event's ``direction``, if one is given) is
located on the dense output by the Illinois variant of regula falsi to ``event_tolerance`` in
time. A ``terminal`` event ends the integration there; the others are recorded. A zero at the
start of the interval is not a crossing.

The dense output of each accepted step is kept (``Solution.sample``), so a caller can evaluate
the solution anywhere in the integrated interval with the accuracy of the steps.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

Rhs = Callable[[float, Sequence[float]], Sequence[float]]

# Dormand-Prince 5(4): nodes, coupling, 5th-order weights, error weights (5th minus 4th order)
_C = (0.0, 1 / 5, 3 / 10, 4 / 5, 8 / 9, 1.0, 1.0)
_A = (
    (),
    (1 / 5,),
    (3 / 40, 9 / 40),
    (44 / 45, -56 / 15, 32 / 9),
    (19372 / 6561, -25360 / 2187, 64448 / 6561, -212 / 729),
    (9017 / 3168, -355 / 33, 46732 / 5247, 49 / 176, -5103 / 18656),
    (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84),
)
_B = (35 / 384, 0.0, 500 / 1113, 125 / 192, -2187 / 6784, 11 / 84, 0.0)
_E = (
    71 / 57600,
    0.0,
    -71 / 16695,
    71 / 1920,
    -17253 / 339200,
    22 / 525,
    -1 / 40,
)
#: The continuous extension of order 4 (Hairer et al., II.6; Shampine 1986): per stage the
#: coefficients of theta, theta^2, theta^3, theta^4 in y(t + theta h) = y + h sum K_s P_s(theta).
_P = (
    (1.0, -8048581381 / 2820520608, 8663915743 / 2820520608, -12715105075 / 11282082432),
    (0.0, 0.0, 0.0, 0.0),
    (
        0.0,
        131558114200 / 32700410799,
        -68118460800 / 10900136933,
        87487479700 / 32700410799,
    ),
    (0.0, -1754552775 / 470086768, 14199869525 / 1410260304, -10690763975 / 1880347072),
    (
        0.0,
        127303824393 / 49829197408,
        -318862633887 / 49829197408,
        701980252875 / 199316789632,
    ),
    (0.0, -282668133 / 205662961, 2019193451 / 616988883, -1453857185 / 822651844),
    (0.0, 40617522 / 29380423, -110615467 / 29380423, 69997945 / 29380423),
)


class IntegrationError(RuntimeError):
    """The integration cannot continue (step size underflow, too many steps)."""


@dataclass(frozen=True)
class Event:
    """A function ``g(t, y)`` whose zeros are located. ``direction`` +1 finds rising crossings
    only, -1 falling only, 0 both; ``terminal`` ends the integration at the first one."""

    function: Callable[[float, Sequence[float]], float]
    name: str = ""
    terminal: bool = False
    direction: Literal[-1, 0, 1] = 0


@dataclass(frozen=True)
class EventHit:
    name: str
    t: float
    y: tuple[float, ...]
    #: +1 rising, -1 falling
    direction: int


class _Step:
    """One accepted step and its dense output (the polynomial's coefficients are formed on
    first use)."""

    __slots__ = ("_q", "h", "stages", "t0", "y0")

    def __init__(self, t0: float, h: float, y0: list[float], stages: list[list[float]]) -> None:
        self.t0 = t0
        self.h = h
        self.y0 = y0
        self.stages = stages
        self._q: list[tuple[float, float, float, float]] | None = None

    def _coefficients(self) -> list[tuple[float, float, float, float]]:
        if self._q is None:
            h = self.h
            self._q = [
                tuple(h * sum(k[i] * _P[s][p] for s, k in enumerate(self.stages)) for p in range(4))
                for i in range(len(self.y0))
            ]  # type: ignore[misc]
        return self._q  # type: ignore[return-value]

    def at(self, t: float) -> list[float]:
        theta = (t - self.t0) / self.h if self.h else 0.0
        t2 = theta * theta
        t3 = t2 * theta
        t4 = t3 * theta
        return [
            y + q[0] * theta + q[1] * t2 + q[2] * t3 + q[3] * t4
            for y, q in zip(self.y0, self._coefficients(), strict=True)
        ]


@dataclass
class Solution:
    """The accepted steps (``t``, ``y``), the events found, why it ended and the work done."""

    t: list[float]
    y: list[list[float]]
    events: list[EventHit] = field(default_factory=list)
    status: Literal["end", "event", "failed"] = "end"
    message: str = ""
    steps: int = 0
    rejected: int = 0
    evaluations: int = 0
    _dense: list[_Step] = field(default_factory=list, repr=False)

    @property
    def t_final(self) -> float:
        return self.t[-1]

    @property
    def y_final(self) -> list[float]:
        return self.y[-1]

    def sample(self, t: float) -> list[float]:
        """The solution at *t* inside the integrated interval, from the dense output of the
        step that holds it (the step's own end values at its ends)."""
        if not self._dense or t <= self.t[0]:
            return list(self.y[0])
        if t >= self.t[-1]:
            return list(self.y[-1])
        lo, hi = 0, len(self._dense) - 1
        while lo < hi:  # the first step that ends at or after t
            mid = (lo + hi) // 2
            step = self._dense[mid]
            if step.t0 + step.h < t:
                lo = mid + 1
            else:
                hi = mid
        return self._dense[lo].at(t)


def _norm(error: Sequence[float], scale: Sequence[float]) -> float:
    total = 0.0
    for e, s in zip(error, scale, strict=True):
        total += (e / s) ** 2
    return math.sqrt(total / max(len(error), 1))


def _finite(values: Sequence[float]) -> bool:
    return math.isfinite(sum(values))  # an inf or nan makes the sum inf or nan


def _first_step(
    f: Rhs,
    t0: float,
    y0: list[float],
    f0: Sequence[float],
    atol: list[float],
    rtol: float,
    m: int | None = None,
) -> float:
    """Hairer et al. II.4: a first step from the size of y and of its first two derivatives
    (of the first *m* components, default all)."""
    m = len(y0) if m is None else m
    scale = [a + rtol * abs(y) for a, y in zip(atol[:m], y0[:m], strict=True)]
    d0 = _norm(y0[:m], scale)
    d1 = _norm(f0[:m], scale)
    h0 = 1e-6 if d0 < 1e-5 or d1 < 1e-5 else 0.01 * d0 / d1
    y1 = [y + h0 * k for y, k in zip(y0, f0, strict=True)]
    f1 = f(t0 + h0, y1)
    if not _finite(f1):
        return h0
    d2 = _norm([a - b for a, b in zip(f1[:m], f0[:m], strict=True)], scale) / h0
    h1 = max(1e-6, h0 * 1e-3) if max(d1, d2) <= 1e-15 else (0.01 / max(d1, d2)) ** 0.2
    return min(100 * h0, h1)


def _locate(
    g: Callable[[float, Sequence[float]], float],
    step: _Step,
    ga: float,
    gb: float,
    tolerance: float,
) -> tuple[float, list[float]]:
    """The zero of g on the step between its ends (ga, gb of opposite sign): Illinois."""
    a, b = step.t0, step.t0 + step.h
    side = 0
    for _ in range(200):
        if abs(b - a) <= tolerance:
            break
        t = b - gb * (b - a) / (gb - ga) if gb != ga else 0.5 * (a + b)
        if not a < t < b:
            t = 0.5 * (a + b)
        gt = g(t, step.at(t))
        if gt == 0.0:
            return t, step.at(t)
        if (gt > 0) == (gb > 0):
            b, gb = t, gt
            if side == -1:
                ga *= 0.5
            side = -1
        else:
            a, ga = t, gt
            if side == 1:
                gb *= 0.5
            side = 1
    t = b  # the side past the crossing: the event function has changed sign there
    return t, step.at(t)


def solve(
    f: Rhs,
    t0: float,
    y0: Sequence[float],
    t_end: float,
    *,
    rtol: float = 1e-8,
    atol: float | Sequence[float] = 1e-12,
    events: Sequence[Event] = (),
    max_step: float = math.inf,
    first_step: float | None = None,
    max_steps: int = 100_000,
    event_tolerance: float | None = None,
    error_components: int | None = None,
) -> Solution:
    """Integrate ``dy/dt = f(t, y)`` from *t0* to *t_end* (> *t0*) with the Dormand-Prince
    5(4) pair (see the module docstring). *atol* is one value or one per component. Ends at
    *t_end* (``status`` ``end``), at the first terminal event (``event``), or when a step
    becomes too small or *max_steps* are taken (``failed``, with the reason in ``message``,
    the solution up to there kept). *error_components*: only the first that many components
    enter the error control (default all; see the module docstring)."""
    if not t_end > t0:
        raise ValueError(f"t_end {t_end!r} must be after t0 {t0!r}")
    if not rtol > 0:
        raise ValueError("rtol must be positive")
    y = [float(v) for v in y0]
    n = len(y)
    tolerances = [float(atol)] * n if isinstance(atol, int | float) else [float(a) for a in atol]
    if len(tolerances) != n or any(not a > 0 for a in tolerances):
        raise ValueError("atol: one positive value, or one per component")
    m = n if error_components is None else error_components
    if not 1 <= m <= n:
        raise ValueError(f"error_components {error_components!r}: 1 to {n}")
    span = t_end - t0
    locate_to = event_tolerance if event_tolerance is not None else 1e-12 * max(span, abs(t_end))
    t = float(t0)
    solution = Solution([t], [list(y)])
    k1 = list(f(t, y))
    solution.evaluations += 1
    if len(k1) != n or not _finite(k1):
        solution.status = "failed"
        solution.message = f"the right-hand side at t = {t:.6g} is not finite"
        return solution
    h = first_step if first_step is not None else _first_step(f, t, y, k1, tolerances, rtol, m)
    solution.evaluations += 0 if first_step is not None else 1
    h = min(h, max_step, span)
    g_old = [e.function(t, y) for e in events]
    rejected_last = False
    while t < t_end:
        if solution.steps >= max_steps:
            solution.status = "failed"
            solution.message = f"more than {max_steps} steps before t = {t_end:.6g}"
            return solution
        last = t + h >= t_end - 1e-14 * max(abs(t_end), 1.0)
        if last:
            h = t_end - t
        if h <= 1e-14 * max(abs(t), span):
            solution.status = "failed"
            solution.message = f"the step size fell below the resolution of t at t = {t:.6g}"
            return solution
        a2, a3, a4, a5, a6, a7 = _A[1], _A[2], _A[3], _A[4], _A[5], _A[6]
        k1_ = k1
        k2 = list(f(t + _C[1] * h, [yi + h * a2[0] * p for yi, p in zip(y, k1_, strict=True)]))
        k3 = k4 = k5 = k6 = k7 = None
        ok = _finite(k2)
        if ok:
            k3 = list(
                f(
                    t + _C[2] * h,
                    [yi + h * (a3[0] * p + a3[1] * q) for yi, p, q in zip(y, k1_, k2, strict=True)],
                )
            )
            ok = _finite(k3)
        if ok:
            k4 = list(
                f(
                    t + _C[3] * h,
                    [
                        yi + h * (a4[0] * p + a4[1] * q + a4[2] * r)
                        for yi, p, q, r in zip(y, k1_, k2, k3, strict=True)
                    ],
                )
            )
            ok = _finite(k4)
        if ok:
            k5 = list(
                f(
                    t + _C[4] * h,
                    [
                        yi + h * (a5[0] * p + a5[1] * q + a5[2] * r + a5[3] * u)
                        for yi, p, q, r, u in zip(y, k1_, k2, k3, k4, strict=True)
                    ],
                )
            )
            ok = _finite(k5)
        if ok:
            k6 = list(
                f(
                    t + h,
                    [
                        yi + h * (a6[0] * p + a6[1] * q + a6[2] * r + a6[3] * u + a6[4] * v)
                        for yi, p, q, r, u, v in zip(y, k1_, k2, k3, k4, k5, strict=True)
                    ],
                )
            )
            ok = _finite(k6)
        y_new: list[float] = []
        if ok:
            y_new = [
                yi + h * (a7[0] * p + a7[2] * r + a7[3] * u + a7[4] * v + a7[5] * w)
                for yi, p, r, u, v, w in zip(y, k1_, k3, k4, k5, k6, strict=True)
            ]
            ok = _finite(y_new)
        if ok:
            k7 = list(f(t + h, y_new))
            ok = _finite(k7)
        solution.evaluations += 6
        if not ok:
            h *= 0.2
            solution.rejected += 1
            rejected_last = True
            continue
        e1, _, e3, e4, e5, e6, e7 = _E
        error = [
            h * (e1 * p + e3 * r + e4 * u + e5 * v + e6 * w + e7 * x)
            for p, r, u, v, w, x in zip(k1_, k3, k4, k5, k6, k7, strict=True)  # type: ignore[arg-type]
        ]
        total = 0.0
        for e, yi, yn, tol in zip(error[:m], y[:m], y_new[:m], tolerances[:m], strict=True):
            total += (e / (tol + rtol * max(abs(yi), abs(yn)))) ** 2
        if m < n and not _finite(error[m:]):
            total = math.inf
        err = math.sqrt(total / m) if math.isfinite(total) else math.inf
        if err > 1.0:
            factor = 0.2 if not math.isfinite(err) else max(0.2, 0.9 * err**-0.2)
            h *= factor
            solution.rejected += 1
            rejected_last = True
            continue
        stages = [k1_, k2, k3, k4, k5, k6, k7]
        step = _Step(t, h, list(y), stages)  # type: ignore[arg-type]
        t_new = t + h if not last else t_end
        # events on the step, the earliest first
        g_new = [e.function(t_new, y_new) for e in events]
        found: list[tuple[float, int, list[float], int]] = []
        for index, e in enumerate(events):
            ga, gb = g_old[index], g_new[index]
            if ga == 0:
                continue  # a zero at the start is not a crossing
            rising = ga < 0 <= gb
            falling = ga > 0 >= gb
            if (rising and e.direction >= 0) or (falling and e.direction <= 0):
                if gb == 0:
                    found.append((t_new, index, list(y_new), 1 if rising else -1))
                else:
                    at, y_at = _locate(e.function, step, ga, gb, locate_to)
                    found.append((at, index, y_at, 1 if rising else -1))
        found.sort(key=lambda hit: hit[0])
        stop = next((hit for hit in found if events[hit[1]].terminal), None)
        for at, index, y_at, sense in found:
            if stop is not None and at > stop[0]:
                break
            solution.events.append(EventHit(events[index].name, at, tuple(y_at), sense))
        solution._dense.append(step)
        solution.steps += 1
        if stop is not None:
            solution.t.append(stop[0])
            solution.y.append(list(stop[2]))
            solution.status = "event"
            return solution
        t, y = t_new, y_new
        k1 = k7  # first same as last
        g_old = g_new
        solution.t.append(t)
        solution.y.append(list(y))
        growth = 10.0 if err == 0 else min(10.0, max(0.2, 0.9 * err**-0.2))
        if rejected_last:
            growth = min(growth, 1.0)
        rejected_last = False
        h = min(h * growth, max_step)
    return solution
