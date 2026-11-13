"""Dosing and the vessels around it (ADR 0073): the shortest dosing time a jacket's cooling
allows, vessels coupled by a dose, and a dosed gas passing through without ideal-gas data.

- **The shortest dosing** (:func:`shortest_factor`, :func:`peak_at`): a semi-batch's dosing
  schedule stretched in time by a factor ``s`` from its first dose's start (every dose's
  segments and lag behind the first; the wait before it, the shares and the post-reaction
  kept), its peak cooling duty for one batch ``Q(s)`` from the model, and the
  smallest ``s`` with ``Q(s) <= U A (T - T_coolant)`` of the recipe vessel's jacket at the
  charge. ``Q(s)`` falls as the dosing slows for a reaction the dosing controls, so the factor
  is bracketed by halving or doubling from the declared schedule (``s = 1``) and bisected in
  ``ln s`` to :data:`SCALE_TOLERANCE`. Between :data:`SCALE_MIN` and :data:`SCALE_MAX` only: a
  jacket that removes the peak at the smallest factor does not limit the dosing, and one that
  removes it at no factor up to the largest cannot be helped by dosing more slowly (the
  charge's own reaction, the post-reaction). The recipe reports it (``vessel.jacket.
  shortest_dosing``) as the dosing time from the first dose's start to the last's end
  (:func:`dosing_time`); the model keeps the declared dosing.
- **Coupled vessels** (:func:`couplings`, ``cheme.process-coupled-dosing``): a semi-batch dose
  fed by another batch or semi-batch step's vent, directly or through steps with one material
  inlet each. Its dosing schedule is compared with the generator's: a semi-batch generator's
  doses (the absorber's dose from the first dose's start to the last's end, segment by segment
  when the generator has one dose), a batch's ``time`` (from 0 to it). A difference is a
  warning. Where the generator solves, the share of its vent gas that has left by each moment,
  ``F_g(t)`` (:attr:`.stirred_tank.TankResult.vent_profile`), is compared with the share the
  absorber has dosed, ``F_d(t)``; the largest ``|F_g - F_d|`` over the batch is reported as
  info: how far the gas the generator gives off runs ahead of or behind the dose that takes it
  (both clocks start with the charge, as the recipe's coupled operations start together).
- **A gas passing through a dose without ideal-gas data** (``cheme.process-reactor``,
  warning): a dose with ``absorbed`` below 1 passes the rest of its components to the vent, a
  vent's inerts pass whole, each warmed to the vessel's temperature with its ideal-gas heat
  capacity (ADR 0054). Without it the warming is left out of the duty and the adiabatic
  balance, which the model's note said only.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from chemeascode.foundation.findings import Finding

#: The dosing schedule's stretch factors :func:`shortest_factor` tries: no shorter than this
#: share of the declared schedule, no longer than this multiple of it.
SCALE_MIN = 1e-3
SCALE_MAX = 1e3
#: :func:`shortest_factor` stops when its bracket is within this share.
SCALE_TOLERANCE = 1e-4
#: The upstream steps :func:`couplings` passes through to a dose's generator at most.
TRACE_DEPTH = 10


def dosing_time(node: Any) -> float:
    """s of semi-batch *node*'s dosing: from its first dose's start to its last dose's end (the
    schedule :func:`stretched` stretches)."""
    batch = node.batch
    return batch.dosing_end() - min((d.start for d in batch.dosing), default=0.0)


def stretched(node: Any, factor: float) -> Any:
    """Batch step *node* with its dosing schedule stretched in time by *factor* from its first
    dose's start: every dose's time and profile durations and its start's lag behind the first
    (the wait before the first dose, the shares, the post-reaction and the rest kept)."""
    first = min((d.start for d in node.batch.dosing), default=0.0)
    doses = [
        dose.model_copy(
            update={
                "start": first + (dose.start - first) * factor,
                "time": dose.time * factor if dose.time is not None else None,
                "profile": [(duration * factor, share) for duration, share in dose.profile],
            }
        )
        for dose in node.batch.dosing
    ]
    return node.model_copy(update={"batch": node.batch.model_copy(update={"dosing": doses})})


def peak_at(process: Any, node: Any, inlets: list[Any], case: str, hours: float) -> Callable:
    """``Q(s)``: kW to remove at the peak of one batch (*hours* of the flowsheet's flows) of
    isothermal semi-batch *node* with its dosing stretched by ``s`` (its model's peak cooling
    duty times its content at the end, as the recipe's jacket check takes it); None where the
    model gives none. Raises TankError when the model does not solve."""
    from chemeascode.domains.process.stirred_tank import solve_node, tank_inlet

    def peak(factor: float) -> float | None:
        trial = stretched(node, factor)
        solved, _ = solve_node(process, trial, tank_inlet(trial, inlets), case)
        if solved.peak_cooling_duty is None or not solved.volume:
            return None
        return solved.peak_cooling_duty * solved.volume * hours

    return peak


@dataclass
class Shortest:
    """The smallest stretch factor of a dosing schedule whose peak duty the jacket removes
    (:func:`shortest_factor`): None with the reason when there is none in range."""

    factor: float | None
    peak: float | None  # kW at that factor (at the declared schedule without one)
    runs: int  # models solved
    reason: str = ""


def shortest_factor(peak: Callable[[float], float | None], removable: float) -> Shortest:
    """The smallest factor ``s`` in [:data:`SCALE_MIN`, :data:`SCALE_MAX`] with ``peak(s) <=
    removable`` (kW), bracketed from ``s = 1`` by halving (it is removed) or doubling (it is
    not) and bisected in ``ln s``. Raises what *peak* raises."""
    runs = 0

    def fits(factor: float) -> tuple[bool, float | None]:
        nonlocal runs
        runs += 1
        found = peak(factor)
        return found is not None and found <= removable, found

    ok, declared = fits(1.0)
    if declared is None:
        return Shortest(None, None, runs, "the model gives no peak duty")
    low, high, at_high = (None, 1.0, declared) if ok else (1.0, None, None)
    while ok and low is None:
        trial = high / 2.0
        if trial < SCALE_MIN:
            return Shortest(
                None,
                declared,
                runs,
                f"the jacket removes the peak even at {SCALE_MIN:g} of the dosing time: the "
                "dosing is not limited by the jacket",
            )
        fits_now, found = fits(trial)
        if fits_now:
            high, at_high = trial, found
        else:
            low = trial
    while high is None:
        trial = low * 2.0
        if trial > SCALE_MAX:
            return Shortest(
                None,
                declared,
                runs,
                f"no dosing up to {SCALE_MAX:g} times as long lets the jacket remove the peak "
                "(the charge's own reaction or the post-reaction sets it)",
            )
        fits_now, found = fits(trial)
        if fits_now:
            high, at_high = trial, found
        else:
            low = trial
    while high / low > 1.0 + SCALE_TOLERANCE:
        trial = math.sqrt(low * high)
        fits_now, found = fits(trial)
        if fits_now:
            high, at_high = trial, found
        else:
            low = trial
    return Shortest(high, at_high, runs)


@dataclass
class Coupling:
    """A semi-batch dose fed by another batch step's vent (:func:`couplings`)."""

    absorber: Any  # the semi-batch node that doses
    index: int  # of its dose in batch.dosing
    location: list[Any]  # of the absorber in the flowsheet: [key, index]
    generator: Any  # the batch or semi-batch node whose vent feeds it
    via: list[str]  # the steps between them


def _material(stream: Any) -> bool:
    return getattr(stream, "kind", "material") == "material"


def couplings(process: Any) -> list[Coupling]:
    """Every semi-batch dose of *process* fed by another batch or semi-batch step's vent
    stream, directly or through steps with one material inlet each (at most
    :data:`TRACE_DEPTH`)."""
    fs = process.flowsheet
    inlets: dict[str, list[Any]] = {}
    for s in fs.streams:
        end = process.ends(s)[1]
        if end is not None and _material(s):
            inlets.setdefault(end.node, []).append(s)
    found = []
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        if getattr(node, "reactor", None) != "semibatch" or node.batch is None:
            continue
        streams = {s.id: s for s in fs.streams}
        for k, dose in enumerate(node.batch.dosing):
            stream = streams.get(dose.stream)
            via: list[str] = []
            while stream is not None and len(via) <= TRACE_DEPTH:
                start = process.ends(stream)[0]
                source = process.nodes.get(start.node) if start is not None else None
                if source is None or source.id == node.id:
                    break
                vent = getattr(getattr(source, "batch", None), "vent", None)
                if getattr(source, "reactor", None) in ("batch", "semibatch") and vent is not None:
                    if vent.stream == stream.id:
                        found.append(Coupling(node, k, [key, index], source, via))
                    break
                upstream = inlets.get(source.id, [])
                if len(upstream) != 1:
                    break
                via.append(source.id)
                stream = upstream[0]
    return found


def _window(generator: Any) -> tuple[list[tuple[float, float, float]] | None, str]:
    """The schedule the generator's gas follows: its one dose's segments, else (start, end, 1)
    of its doses together, or of a batch's time; None (with why) when it is not declared."""
    batch = generator.batch
    if generator.reactor == "semibatch":
        segments = [d.segments() for d in batch.dosing]
        if len(segments) == 1:
            return segments[0], f"{generator.id}'s dosing"
        start = min(a for s in segments for a, _, _ in s)
        return [(start, batch.dosing_end(), 1.0)], f"{generator.id}'s doses together"
    if batch.time is not None:
        return [(0.0, batch.time, 1.0)], f"{generator.id}'s batch time"
    return None, f"{generator.id} ends at its target conversion"


def _same(a: list[tuple[float, float, float]], b: list[tuple[float, float, float]]) -> bool:
    if len(a) != len(b):
        return False
    scale = max((abs(x) for seg in a for x in seg[:2]), default=1.0) or 1.0
    return all(
        abs(x0 - y0) <= 1e-9 * scale and abs(x1 - y1) <= 1e-9 * scale and abs(xs - ys) <= 1e-9
        for (x0, x1, xs), (y0, y1, ys) in zip(a, b, strict=True)
    )


def _schedule(segments: list[tuple[float, float, float]]) -> str:
    return ", ".join(f"{a / 3600:.4g}-{b / 3600:.4g} h ({s:.3g})" for a, b, s in segments)


def deviation(profile: list[tuple[float, float]], dose: Any) -> tuple[float, float] | None:
    """The largest ``|F_g(t) - F_d(t)|`` and its time s: *profile* (time s, kmol left by the
    generator's vent so far) as shares of its end, against the share *dose* (a Dosing) has fed
    by then; at the profile's points and the dose's break points (``F_g`` linear between its
    points, 1 after its end). None when nothing left."""
    if not profile or profile[-1][1] <= 0:
        return None
    total = profile[-1][1]
    times = [t for t, _ in profile]

    def generated(t: float) -> float:
        if t >= times[-1]:
            return 1.0
        k = next(i for i, x in enumerate(times) if x >= t)
        if k == 0:
            return profile[0][1] / total
        (t0, v0), (t1, v1) = profile[k - 1], profile[k]
        share = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
        return (v0 + share * (v1 - v0)) / total

    def fed(t: float) -> float:
        return sum(s * min(max((t - a) / (b - a), 0.0), 1.0) for a, b, s in dose.segments())

    points = sorted({*times, *(x for a, b, _ in dose.segments() for x in (a, b))})
    return max(((abs(generated(t) - fed(t)), t) for t in points), key=lambda p: p[0])


def rules(process: Any) -> list[Finding]:
    """``cheme.process-coupled-dosing`` (a dose fed by another vessel's vent on another
    schedule: warning; how closely it follows the gas: info) and ``cheme.process-reactor`` (a
    dosed gas passing through without ideal-gas data: warning)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.foundation.yamlsource import _yaml_line

    findings: list[Finding] = []

    def add(level: str, rule: str, message: str, loc: list[Any], ids: list[str], hint: str):
        findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                f"cheme.process-{rule}",
                message,
                line=_yaml_line(process.flowsheet_doc, loc),
                ids=ids,
                hint=hint,
            )
        )

    _passing_gas_rules(process, add)
    for c in couplings(process):
        _coupling_rules(process, c, add)
    return findings


def _passing_gas_rules(process: Any, add: Callable) -> None:
    """A vented batch's dose that passes gas through (absorbed below 1, or a vent's inerts)
    whose components have no ideal-gas data: its warming is left out (warning)."""
    from chemeascode.domains.process.model import _carried

    fs = process.flowsheet
    streams = {s.id: s for s in fs.streams}
    data = process.ideal_gas()
    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        batch = getattr(node, "batch", None)
        if getattr(node, "reactor", None) != "semibatch" or batch is None or batch.vent is None:
            continue
        inerts = set(batch.vent.inerts)
        for k, dose in enumerate(batch.dosing):
            stream = streams.get(dose.stream)
            if stream is None:
                continue  # the dosing rules say so
            carried = _carried(process, stream)
            passing = carried if dose.absorbed is not None and dose.absorbed < 1 else set()
            passing |= carried & inerts
            if lack := sorted(n for n in passing if data.get(n) is None):
                add(
                    "warning",
                    "reactor",
                    f"{key[:-1]} {node.id}: the gas {', '.join(lack)} of the dose {dose.stream} "
                    "passes through to the vent without ideal_gas data: its warming to the "
                    "vessel's temperature is left out of the duty, the peak cooling duty and "
                    "the adiabatic balance",
                    [key, index, "batch", "dosing", k],
                    [node.id, dose.stream, *lack],
                    "give the component's ideal_gas data (process/materials.yaml), or say in "
                    "DESIGN.md why its warming does not matter",
                )


def _coupling_rules(process: Any, c: Coupling, add: Callable) -> None:
    """One coupled dose: its schedule against its generator's (warning), and its dosed share
    against the share of the generator's vent gas that has left over time (info)."""
    from chemeascode.domains.process.stirred_tank import TankError, solve_node, tank_inlet

    dose = c.absorber.batch.dosing[c.index]
    where = [*c.location, "batch", "dosing", c.index]
    ids = [c.absorber.id, c.generator.id, dose.stream]
    through = f" (through {', '.join(c.via)})" if c.via else ""
    hint = (
        "dose the gas over the schedule its generator gives it off on (the generator's dosing "
        "time and profile), and start both together in process/recipe.yaml"
    )
    window, what = _window(c.generator)
    if window is not None and not _same(dose.segments(), window):
        add(
            "warning",
            "coupled-dosing",
            f"{c.absorber.id} doses {dose.stream}, the vent of {c.generator.id}{through}, over "
            f"{_schedule(dose.segments())}, but {what} runs {_schedule(window)}: the gas leaves "
            "on another schedule than it is dosed",
            where,
            ids,
            hint,
        )
    inlets = [
        s
        for s in process.flowsheet.streams
        if (end := process.ends(s)[1]) is not None and end.node == c.generator.id
    ]
    case = process.flowsheet.default_case()
    try:
        solved, _ = solve_node(process, c.generator, tank_inlet(c.generator, inlets), case)
    except TankError:
        return  # the generator's own findings say why
    found = deviation(solved.vent_profile, dose)
    if found is None:
        return
    gap, at = found
    add(
        "info",
        "coupled-dosing",
        f"{c.absorber.id} doses {dose.stream}, the vent of {c.generator.id}{through}: the share "
        f"of the gas {c.generator.id} has given off and the share {c.absorber.id} has dosed "
        f"differ by {gap:.3g} at most (at {at / 3600:.4g} h, case {case})",
        where,
        ids,
        "a large difference: the gas forms on another profile than it is dosed (an accumulating "
        "generator, a post-reaction); a dose profile closer to the generator's gas, or a buffer",
    )
