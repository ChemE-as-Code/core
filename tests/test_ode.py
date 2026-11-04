"""The adaptive Dormand-Prince 5(4) integrator (foundation/ode.py) on ODEs with analytic
solutions: accuracy that follows the tolerance, the dense output, event location, terminal
events, directions and the failure modes."""

from __future__ import annotations

import math

import pytest

from chemeascode.foundation.ode import Event, solve


def _oscillator(t, y):
    return [y[1], -y[0]]


@pytest.mark.parametrize("rtol", [1e-6, 1e-8, 1e-10])
def test_the_error_follows_the_tolerance(rtol):
    """y'' = -y, y(0) = 1, y'(0) = 0: y = cos t; at t = 20 the global error stays within a
    small multiple of rtol (about 20 periods' worth of local errors)."""
    s = solve(_oscillator, 0.0, [1.0, 0.0], 20.0, rtol=rtol, atol=1e-14)
    assert s.status == "end" and s.t_final == 20.0
    error = max(abs(s.y_final[0] - math.cos(20.0)), abs(s.y_final[1] + math.sin(20.0)))
    assert error < 20 * rtol
    assert error > 1e-3 * rtol  # an adaptive step, not an exact one


def test_fewer_steps_at_a_looser_tolerance():
    loose = solve(_oscillator, 0.0, [1.0, 0.0], 20.0, rtol=1e-5)
    tight = solve(_oscillator, 0.0, [1.0, 0.0], 20.0, rtol=1e-10)
    assert loose.steps < tight.steps
    # order 5: 10^5 tighter costs about 10^(5/5) = 10 times the steps
    assert 4 < tight.steps / loose.steps < 25


def test_dense_output_between_the_steps():
    s = solve(_oscillator, 0.0, [1.0, 0.0], 20.0, rtol=1e-9, atol=1e-14)
    worst = max(abs(s.sample(t)[0] - math.cos(t)) for t in [0.0137 * i for i in range(1460)])
    assert worst < 1e-7
    # at the step ends the dense output is the step's own value
    for t, y in zip(s.t[1:5], s.y[1:5], strict=True):
        assert s.sample(t) == pytest.approx(y, rel=1e-12, abs=1e-15)


def test_events_are_located_on_the_dense_output():
    """The zeros of cos t at pi/2 + k pi, both directions, not terminal."""
    s = solve(
        _oscillator, 0.0, [1.0, 0.0], 20.0, rtol=1e-10, events=[Event(lambda t, y: y[0], "zero")]
    )
    assert [e.name for e in s.events] == ["zero"] * 6
    for k, hit in enumerate(s.events):
        assert hit.t == pytest.approx(math.pi / 2 + k * math.pi, abs=1e-9)
        assert hit.direction == (-1 if k % 2 == 0 else 1)


def test_direction_filters_and_a_terminal_event_ends_it():
    rising = solve(
        _oscillator,
        0.0,
        [1.0, 0.0],
        20.0,
        events=[Event(lambda t, y: y[0], "up", direction=1)],
    )
    assert [round(e.t, 6) for e in rising.events] == [
        round(1.5 * math.pi + 2 * k * math.pi, 6) for k in range(3)
    ]
    # y' = -y: y = exp(-t) is 0.5 at ln 2
    s = solve(
        lambda t, y: [-y[0]],
        0.0,
        [1.0],
        5.0,
        events=[Event(lambda t, y: y[0] - 0.5, "half", terminal=True, direction=-1)],
    )
    assert s.status == "event"
    assert s.t_final == pytest.approx(math.log(2), abs=1e-9)
    assert s.y_final[0] == pytest.approx(0.5, abs=1e-9)


def test_a_zero_at_the_start_is_not_a_crossing():
    s = solve(lambda t, y: [1.0], 0.0, [0.0], 1.0, events=[Event(lambda t, y: y[0], "start")])
    assert s.events == []


def test_failures_are_reported_not_raised():
    s = solve(lambda t, y: [y[0] ** 2], 0.0, [1.0], 2.0)  # y = 1 / (1 - t): blows up at 1
    assert s.status == "failed" and "step size" in s.message
    assert s.t_final == pytest.approx(1.0, abs=1e-6)
    few = solve(_oscillator, 0.0, [1.0, 0.0], 100.0, max_steps=5)
    assert few.status == "failed" and "more than 5 steps" in few.message
    nan = solve(lambda t, y: [math.nan], 0.0, [1.0], 1.0)
    assert nan.status == "failed" and "not finite" in nan.message


def test_a_rejected_stage_shrinks_the_step():
    """The right-hand side is not finite beyond t = 0.5: the step that reaches past it is
    rejected and shortened until it ends."""

    def f(t, y):
        return [1.0 if t <= 0.5 else math.nan]

    s = solve(f, 0.0, [0.0], 1.0, first_step=0.4)
    assert s.status == "failed" and s.rejected > 0
    assert s.t_final == pytest.approx(0.5, abs=1e-6) and s.y_final[0] == pytest.approx(s.t_final)


def test_wrong_calls_raise():
    with pytest.raises(ValueError, match="after t0"):
        solve(_oscillator, 1.0, [1.0, 0.0], 1.0)
    with pytest.raises(ValueError, match="atol"):
        solve(_oscillator, 0.0, [1.0, 0.0], 1.0, atol=[1e-9])
    with pytest.raises(ValueError, match="rtol"):
        solve(_oscillator, 0.0, [1.0, 0.0], 1.0, rtol=0)


def test_quadratures_outside_the_error_control_leave_the_steps():
    """y' = -y with the running integral q' = y outside the error control
    (error_components=1): the same steps and y as without it, q = 1 - y (the linear invariant
    y + q = 1 to rounding) and close to 1 - exp(-t)."""
    alone = solve(lambda t, y: [-y[0]], 0.0, [1.0], 5.0, rtol=1e-8, atol=1e-12)
    both = solve(
        lambda t, y: [-y[0], y[0]],
        0.0,
        [1.0, 0.0],
        5.0,
        rtol=1e-8,
        atol=[1e-12, 1e-300],
        error_components=1,
    )
    assert both.t == alone.t and [y[0] for y in both.y] == [y[0] for y in alone.y]
    assert all(abs(y[0] + y[1] - 1.0) <= 1e-15 for y in both.y)
    assert both.y_final[1] == pytest.approx(1 - math.exp(-5.0), rel=1e-7)
    # with the quadrature in the error control, the steps change
    controlled = solve(
        lambda t, y: [-y[0], y[0]], 0.0, [1.0, 0.0], 5.0, rtol=1e-8, atol=[1e-12, 1e-12]
    )
    assert controlled.t != alone.t
    with pytest.raises(ValueError, match="error_components"):
        solve(lambda t, y: [-y[0], y[0]], 0.0, [1.0, 0.0], 1.0, error_components=3)


def test_a_quadrature_error_that_is_not_finite_rejects_the_step(monkeypatch):
    """Outside the error control a quadrature's error still has to be finite: an error
    estimate that overflows (here forced through the k7 weight, the stages and y finite)
    rejects the step rather than accepting it unchecked, so the integration fails instead of
    reporting a value it cannot vouch for."""
    from chemeascode.foundation import ode

    def f(t, y):
        return [0.0, 1e10]

    plain = solve(f, 0.0, [1.0, 0.0], 1.0, error_components=1)
    assert plain.status == "end" and plain.y_final[1] == pytest.approx(1e10)
    monkeypatch.setattr(ode, "_E", (*ode._E[:6], -1e308))
    forced = solve(f, 0.0, [1.0, 0.0], 1.0, error_components=1)
    assert forced.status == "failed" and forced.rejected > 0
    assert math.isfinite(forced.y_final[1])
