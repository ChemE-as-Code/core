"""Batch (Rayleigh) distillation and solvent swap (``still:`` on a block or step), shortcut
level: one equilibrium stage, total condenser, no reflux.

The still's content ``N_i`` (kmol) boils up at ``V`` (kmol/s) and the vapour leaves in
equilibrium with it::

    dN_i/dt = -V y_i (+ F z_i, a solvent swap's feed)

with ``y_i`` from Raoult's law, ``y_i = x_i P_i^sat(T) / P`` at the still's bubble point
(``sum_i x_i P_i^sat(T) = P``, each volatile component's Antoine ``vapour_pressure`` in
materials.yaml), or from a constant relative volatility, ``y_i = alpha_i x_i / sum_j alpha_j
x_j``. Components listed ``nonvolatile`` (and solid components) stay in the still. The
composition's path does not depend on ``V``: it is integrated over the moles boiled up ``s``
(``dN_i/ds = -y_i``, Dormand-Prince 5(4) as the batch reactor), and the time and heat follow
along it, ``dt/ds = 1/V``, ``dE/ds = lambda(y) = sum_i y_i dHvap_i``. Without feed this is
Rayleigh's equation; for a binary at constant relative volatility it integrates to::

    ln(W0/W) = 1/(alpha - 1) ln[x0 (1 - x) / (x (1 - x0))] + ln[(1 - x) / (1 - x0)]

``boilup`` is constant: a vapour rate of the still (kmol/h, kmol/s, kg/h), its heat input (kW,
``V = Q / lambda(y)``) or a specific rate (1/h, kmol of vapour per hour per kmol of the charge).
The still stops at its ``end`` (a share distilled, the residue's mole fraction of a key, a time
of boil-up, a temperature) or collects ``cuts`` in turn, each until its own end.

A solvent swap (``feed:``) feeds another inlet stream while it boils, ``constant_level`` (as
fast as it boils up: the content's moles stay at ``down_to`` of the charge's, after distilling
down to there) or in ``portions`` (put and take: distil down to the level, add a portion, and
again); the ends apply once all of it is in. At constant level and constant relative
volatility the old solvent ``A`` (``alpha`` to the new one) in a content of ``N`` kmol with a
non-volatile share ``x_P`` falls as::

    ((1 - x_P) / alpha) ln(x_A0 / x_A) + ((alpha - 1) / alpha) (x_A0 - x_A) = fed / N

The basis: the flowsheet's flows are amounts per hour of flows, as a semi-batch's charge and
doses (ADR 0050, 0051). One batch is the hours of flows the recipe's batch size makes
(``process/recipe.yaml``: batch size over the flowsheet's rate of its stream), else one hour.
A vapour rate or a duty is of the still in one batch, so the time and the energy per batch scale
with those hours; a specific boil-up (1/h) does not need them. Pure Python.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.domains.process.fixed_bed import _dopri_step
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import PLANT_FILE, NotAPlantRepository
from chemeascode.foundation.yamlsource import _yaml_line

REPORT_INPUTS = (MATERIALS_FILE, FLOWSHEET_FILE, PLANT_FILE, "process/recipe.yaml")

#: What the model takes for granted (reported by :mod:`.model_basis`).
ASSUMPTIONS = (
    "one equilibrium stage: the vapour leaves in equilibrium with the well-mixed still (no "
    "column, no reflux)",
    "total condenser: the distillate is the vapour condensed, no holdup in the condenser",
    "an ideal liquid (Raoult's law with Antoine vapour pressures) or a constant relative "
    "volatility",
    "constant boil-up from the start: no heat-up to the bubble point (a heat operation of the "
    "recipe), no sensible heat of the content, no heat losses",
    "the duty is the vapour's latent heat (heat_of_vaporization near the still's temperature)",
    "a swap's feed mixes in at once; constant level holds the content's moles, not its volume",
)

#: Points of a still's profile (beside the integrator's own).
PROFILE_POINTS = 50
#: Relative error per step of the integration.
TOLERANCE = 1e-9
#: K: the still's temperature is searched below this.
HOTTEST = 2000.0
#: kJ/kmol: a heat of vaporization below this is taken for one in kJ/mol (2 kJ/mol: only
#: cryogens such as hydrogen and helium are below).
LEAST_LATENT = 2000.0


class StillError(ValueError):
    """The still cannot be solved as declared."""


@dataclass
class Cut:
    """One distillate cut: kmol (per hour of flows) by component, when it ends (s of boil-up
    from the start, the still's temperature K), the heat per batch it took itself (kJ, from the
    end of the cut before; the cuts' sum to the still's energy) and the vapour leaving at its
    end (mole fractions: an empty cut's composition)."""

    outlet: str
    moles: dict[str, float]
    time: float
    temperature: float | None
    energy: float | None
    vapour: dict[str, float]


@dataclass
class StillResult:
    """A batch still's charge, feed, cuts and residue (kmol per hour of flows: the flowsheet's
    basis), and its time and heat per batch."""

    charge: dict[str, float]
    fed: dict[str, float]
    residue: dict[str, float]
    cuts: list[Cut]
    pressure: float | None  # kPa(a)
    hours: float  # h of flows per batch
    time: float = 0.0  # s of boil-up per batch
    energy: float | None = None  # kJ per batch (latent heat)
    peak_duty: float | None = None  # kW
    temperatures: tuple[float, float] | None = None  # K of the still at the start and end
    key: str = ""
    #: K of the charge as it enters; with ``heat_up`` (ADR 0063) the kJ per batch that heat
    #: the charge to its bubble point (None: not known, ``heat_up_missing`` why)
    charge_temperature: float | None = None
    heat_up: float | None = None
    heat_up_missing: str = ""
    #: (share of all charged and fed distilled, s, K or None, mole fraction of the key)
    profile: list[tuple[float, float, float | None, float]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def duty(self) -> float | None:
        """kW: the mean heat input over the boil-up."""
        if self.energy is None or self.time <= 0:
            return None
        return self.energy / self.time


class _Phase:
    """How the still's vapour follows from its content: the components, the volatile ones and
    their data."""

    def __init__(self, names, volatile, model, alpha, pressures, pressure, latent):
        self.names = names
        self.volatile = volatile  # bool per component
        self.model = model
        self.alpha = alpha  # per component (constant)
        self.pressures = pressures  # VapourPressure per component (raoult)
        self.pressure = pressure  # kPa
        self.latent = latent  # kJ/kmol per component, None where not known
        self.guess = 350.0

    def bubble(self, x: list[float]) -> float:
        """K: the still's bubble point, sum x_i P_i(T) = P: bracketed from the last one, then
        Newton on ln(sum x_i P_i / P), bisecting where a step leaves the bracket."""
        pressures = self.pressures

        def g(t: float) -> tuple[float, float]:
            """sum x_i P_i(T) (kPa) and its slope (kPa/K)."""
            total, slope = 0.0, 0.0
            for i, vp in enumerate(pressures):
                if vp is None or x[i] <= 0 or not self.volatile[i]:
                    continue
                p = x[i] * vp.kpa(t)
                total += p
                shift = (t - 273.15 if vp.temperature_unit == "degC" else t) + vp.c
                if p > 0 and shift > 0:
                    slope += p * vp.b / shift**2 * (math.log(10.0) if vp.form == "log10" else 1)
            return total, slope

        t = self.guess
        total, slope = g(t)
        lo, hi = (None, t) if total > self.pressure else (t, None)
        step = 10.0
        while lo is None or hi is None:
            t = hi - step if lo is None else lo + step
            if t > HOTTEST:
                raise StillError("no bubble point: the still boils dry (nothing volatile left)")
            if t <= 1.0:
                raise StillError("no bubble point above 1 K at the still's pressure")
            total, slope = g(t)
            if total > self.pressure:
                hi = t
            else:
                lo = t
            step *= 2.0
        for _ in range(200):
            new = (lo + hi) / 2
            if total > 0 and slope > 0:
                trial = t - math.log(total / self.pressure) * total / slope
                if lo < trial < hi:
                    new = trial
            if abs(new - t) < 1e-11 * t or hi - lo < 1e-11 * t:
                t = new
                break
            t = new
            total, slope = g(t)
            if total > self.pressure:
                hi = t
            else:
                lo = t
        self.guess = t
        return t

    def vapour(self, moles: list[float]) -> tuple[list[float], float | None]:
        """The vapour's mole fractions over the still holding *moles*, and its temperature K
        (raoult; None at a constant relative volatility)."""
        total = sum(moles)
        if total <= 0:
            raise StillError("the still is empty")
        x = [n / total for n in moles]
        if sum(xi for xi, v in zip(x, self.volatile, strict=True) if v) <= 1e-14:
            raise StillError("the still boils dry: nothing volatile is left")
        if self.model == "constant":
            w = [
                a * xi if v else 0.0 for a, xi, v in zip(self.alpha, x, self.volatile, strict=True)
            ]
            s = sum(w)
            return [wi / s for wi in w], None
        t = self.bubble(x)
        p = [
            x[i] * vp.kpa(t) if vp is not None and self.volatile[i] else 0.0
            for i, vp in enumerate(self.pressures)
        ]
        s = sum(p)
        return [pi / s for pi in p], t

    def latent_heat(self, y: list[float]) -> float | None:
        """kJ/kmol of vapour *y*; None when a component in it has no heat of vaporization."""
        total = 0.0
        for yi, h in zip(y, self.latent, strict=True):
            if yi > 0:
                if h is None:
                    return None
                total += yi * h
        return total


def solve_still(
    spec: Any,
    charge: Mapping[str, float],
    feed: Mapping[str, float] | None,
    components: Mapping[str, Any],
    pressure: float | None,
    hours: float = 1.0,
    nonvolatile: set[str] | frozenset[str] = frozenset(),
) -> StillResult:
    """Still *spec* (a :class:`~.schema.Still`) charged with *charge* (kmol per hour of flows
    by component) and fed *feed* (its ``feed:``), at *pressure* kPa(a) (raoult), *hours* of
    flows per batch; *components* maps an id to its materials.yaml component (vapour_pressure,
    heat_of_vaporization, molar_mass). Raises StillError."""
    feed = dict(feed or {})
    if spec.feed is not None and sum(feed.values()) <= 0:
        raise StillError("the swap's feed is empty")
    names = [n for n in dict.fromkeys([*charge, *feed]) if charge.get(n, 0) + feed.get(n, 0) > 0]
    n0 = [max(charge.get(n, 0.0), 0.0) for n in names]
    z = [max(feed.get(n, 0.0), 0.0) for n in names]
    total0, total_feed = sum(n0), sum(z)
    if total0 <= 0:
        raise StillError("the charge is empty")
    model = spec.volatility.model
    stays = set(spec.nonvolatile) | set(nonvolatile)
    volatile = [n not in stays for n in names]
    lacking = []
    if model == "constant":
        lacking = [
            n for n, v in zip(names, volatile, strict=True) if v and n not in spec.volatility.alpha
        ]
        if lacking:
            raise StillError(
                "no relative volatility (volatility.alpha) of "
                + ", ".join(lacking)
                + ": give it, or list the component in nonvolatile"
            )
    pressures = [getattr(components.get(n), "vapour_pressure", None) for n in names]
    if model == "raoult":
        lacking = [
            n for n, v, vp in zip(names, volatile, pressures, strict=True) if v and vp is None
        ]
        if lacking:
            raise StillError(
                "no vapour_pressure of "
                + ", ".join(lacking)
                + " in materials.yaml: give it (Antoine), or list it in nonvolatile"
            )
        if pressure is None:
            raise StillError("no pressure: give still.pressure or the charge's pressure")
    latent = [
        getattr(components.get(n), "heat_of_vaporization", None) if v else 0.0
        for n, v in zip(names, volatile, strict=True)
    ]
    unit, rate = spec.boilup.unit, spec.boilup.value
    if unit == "kW" and (gaps := [n for n, h in zip(names, latent, strict=True) if h is None]):
        raise StillError("a boil-up in kW needs the heat_of_vaporization of " + ", ".join(gaps))
    mw = [getattr(components.get(n), "molar_mass", None) for n in names]
    needs_mass = unit == "kg/h" or any(
        e is not None and e.distilled and e.basis == "mass" for _, e in spec.ends()
    )
    if needs_mass and (gaps := [n for n, m in zip(names, mw, strict=True) if not m]):
        raise StillError("no molar_mass of " + ", ".join(gaps))
    phase = _Phase(
        names,
        volatile,
        model,
        [spec.volatility.alpha.get(n, 0.0) for n in names],
        pressures,
        pressure,
        latent,
    )
    k = len(names)
    feed_share = [v / total_feed for v in z] if total_feed > 0 else [0.0] * k
    result = StillResult(dict(zip(names, n0, strict=True)), {}, {}, [], pressure, hours)
    energy_known = all(h is not None for h in latent)

    def seconds_per_mole(y: list[float]) -> float:
        """s per kmol (per hour of flows) boiled up from vapour *y*."""
        if unit == "1/h":
            return 3600.0 / (rate * total0)
        if unit == "kmol/h":
            return hours * 3600.0 / rate
        if unit == "kmol/s":
            return hours / rate
        if unit == "kg/h":
            return hours * 3600.0 * sum(yi * (m or 0.0) for yi, m in zip(y, mw, strict=True)) / rate
        return hours * (phase.latent_heat(y) or 0.0) / rate  # kW

    def derivatives(feeding: bool) -> Callable[[list[float]], list[float]]:
        def f(state: list[float]) -> list[float]:
            y, _ = phase.vapour(state[:k])
            dn = [-yi + (feed_share[i] if feeding else 0.0) for i, yi in enumerate(y)]
            heat = phase.latent_heat(y) if energy_known else None
            return [*dn, seconds_per_mole(y), hours * (heat or 0.0)]

        return f

    # the state: kmol by component (per hour of flows), s of boil-up, kJ per batch
    state = [*n0, 0.0, 0.0]
    boiled = 0.0  # kmol per hour of flows boiled up so far
    fed = [0.0] * k
    removed = [0.0] * k  # distilled into the cuts closed so far
    energy_before = 0.0  # kJ per batch taken by the cuts closed so far
    peak = 0.0
    key = _profile_key(spec, names, phase, n0)
    ki = names.index(key) if key in names else None
    result.key = key
    seen_ranges: set[str] = set()

    def record(state: list[float]) -> None:
        moles = state[:k]
        total = sum(moles)
        y, t = phase.vapour(moles) if any(moles) else ([0.0] * k, None)
        if t is not None:
            for n, vp, x in zip(names, pressures, moles, strict=True):
                if vp is not None and x > 0 and not vp.covers(t) and n not in seen_ranges:
                    seen_ranges.add(n)
                    low, high = vp.temperature_range or (0.0, 0.0)
                    result.notes.append(
                        f"the still at {t:.5g} K is outside the vapour_pressure range of {n} "
                        f"({low:g}-{high:g} K)"
                    )
        share = boiled / (total0 + total_feed)
        x_key = moles[ki] / total if ki is not None and total > 0 else 0.0
        result.profile.append((share, state[k], t, x_key))

    def advance(
        feeding: bool, stop: Callable[[list[float], float], float] | None, limit: float | None
    ) -> None:
        """Boil up until *stop* (of the state and the kmol boiled up) is no longer negative,
        or *limit* kmol more are boiled up (feeding meanwhile with *feeding*). Raises
        StillError when the still boils dry first."""
        nonlocal state, boiled, peak
        f = derivatives(feeding)
        end = boiled + limit if limit is not None else None
        available = sum(n for n, v in zip(state[:k], volatile, strict=True) if v)
        cap = boiled + available + (limit if feeding and limit is not None else 0.0)
        target = min(end, cap) if end is not None else cap
        h = max(target - boiled, 1e-12) / 100.0
        while True:
            h = min(h, target - boiled)
            if h <= 1e-14 * (total0 + total_feed):
                if end is not None and boiled >= end * (1 - 1e-12):
                    return
                raise StillError("the still boils dry before its end")
            try:
                new, error = _dopri_step(f, state, h)
                new[:k] = [max(v, 0.0) for v in new[:k]]
                phase.vapour(new[:k])
            except StillError as failure:
                if h < 1e-9 * (total0 + total_feed):
                    if stop is not None and ("empty" in str(failure) or "dry" in str(failure)):
                        raise StillError(
                            f"the still boils dry before its end ({failure})"
                        ) from failure
                    raise
                h /= 4.0
                continue
            scale = [
                max(abs(a), abs(b), 1e-9 * total0) for a, b in zip(state[:k], new[:k], strict=True)
            ]
            scale += [max(abs(state[k]), abs(new[k]), 1.0), max(abs(state[k + 1]), 1.0)]
            err = max(abs(e) / s for e, s in zip(error, scale, strict=True))
            if err > TOLERANCE and h > 1e-12 * (total0 + total_feed):
                h *= max(0.1, 0.9 * (TOLERANCE / err) ** 0.2)
                continue
            if stop is not None and stop(new, boiled + h) >= 0:
                lo, hi = 0.0, h
                for _ in range(80):
                    mid = (lo + hi) / 2
                    trial, _ = _dopri_step(f, state, mid)
                    trial[:k] = [max(v, 0.0) for v in trial[:k]]
                    if stop(trial, boiled + mid) >= 0:
                        hi = mid
                    else:
                        lo = mid
                new, _ = _dopri_step(f, state, hi)
                new[:k] = [max(v, 0.0) for v in new[:k]]
                h = hi
            if h > 0:
                dt = new[k] - state[k]
                if dt > 0:
                    peak = max(peak, (new[k + 1] - state[k + 1]) / dt)
            if feeding:
                fed[:] = [a + share * h for a, share in zip(fed, feed_share, strict=True)]
            boiled += h
            state = new
            record(state)
            if stop is not None and stop(state, boiled) >= -1e-15:
                return
            if end is not None and boiled >= end * (1 - 1e-12):
                return
            grow = 5.0 if err == 0 else min(5.0, 0.9 * (TOLERANCE / err) ** 0.2)
            h *= max(grow, 1.0)

    def down_to(level: float) -> Callable[[list[float], float], float]:
        return lambda s, _b: level - sum(s[:k])

    record(state)
    start_t = result.profile[0][2]
    ends = spec.ends()
    level = (spec.feed.down_to if spec.feed is not None else 1.0) * total0
    if spec.feed is not None:
        if spec.feed.mode == "constant_level":
            if sum(state[:k]) > level * (1 + 1e-12):
                advance(False, down_to(level), None)
            advance(True, None, total_feed)
            fed[:] = list(z)  # what the integration fed, exactly
        else:
            portion = [v / spec.feed.portions for v in z]
            for _ in range(spec.feed.portions):
                if sum(state[:k]) > level * (1 + 1e-12):
                    advance(False, down_to(level), None)
                state[:k] = [a + b for a, b in zip(state[:k], portion, strict=True)]
                fed[:] = [a + b for a, b in zip(fed, portion, strict=True)]
                record(state)
            fed[:] = list(z)
    mass0 = sum((a + b) * (m or 0.0) for a, b, m in zip(n0, z, mw, strict=True))

    def stop_of(end: Any) -> Callable[[list[float], float], float]:
        if end.distilled is not None:
            if end.basis == "mole":
                return lambda s, b: b / (total0 + total_feed) - end.distilled
            return lambda s, b: (
                sum((a + f - x) * (m or 0.0) for a, f, x, m in zip(n0, z, s[:k], mw, strict=True))
                / mass0
                - end.distilled
            )
        if end.time is not None:
            return lambda s, b: s[k] - end.time
        if end.temperature is not None:
            return lambda s, b: phase.vapour(s[:k])[1] - end.temperature
        key, target = end.residue.key, end.residue.mole_fraction
        if key not in names:
            raise StillError(f"the residue's key {key} is not in the still")
        i = names.index(key)
        # the direction comes from the target: the key's share falls to a target below its
        # share now (an intermediate key may first rise, then fall; a target it never reaches
        # ends in "boils dry before its end"), and rises to one above it while it rises (the
        # vapour leaner in it than the liquid). A key falling already below its target (a
        # swap's old solvent once the feed is in) has reached it.
        x_now = state[i] / sum(state[:k])
        y, _ = phase.vapour(state[:k])
        sign = 1.0 if target > x_now and y[i] < x_now else -1.0
        return lambda s, b: sign * (s[i] / sum(s[:k]) - target) if sum(s[:k]) > 0 else 1.0

    for port, end in ends:
        if end is None:
            portions = spec.feed is not None and spec.feed.mode == "portions"
            if portions and sum(state[:k]) > level * (1 + 1e-12):
                advance(False, down_to(level), None)
        else:
            stop = stop_of(end)
            if stop(state, boiled) >= 0:
                result.notes.append(
                    f"cut {port}: its end is reached when it starts"
                    + (" (the feed is in)" if spec.feed is not None else "")
                )
            else:
                advance(False, stop, None)
        total_out = [a + f - x for a, f, x in zip(n0, fed, state[:k], strict=True)]
        moles = {n: max(t - r, 0.0) for n, t, r in zip(names, total_out, removed, strict=True)}
        removed = total_out
        y, t = phase.vapour(state[:k])
        result.cuts.append(
            Cut(
                port,
                moles,
                state[k],
                t,
                state[k + 1] - energy_before if energy_known else None,
                dict(zip(names, y, strict=True)),
            )
        )
        energy_before = state[k + 1]
    result.fed = dict(zip(names, fed, strict=True))
    result.residue = dict(zip(names, state[:k], strict=True))
    result.time = state[k]
    if energy_known:
        result.energy = state[k + 1]
        result.peak_duty = peak
    else:
        gaps = [n for n, h in zip(names, latent, strict=True) if h is None]
        result.notes.append("no duty: no heat_of_vaporization of " + ", ".join(gaps))
    end_t = result.profile[-1][2]
    if start_t is not None and end_t is not None:
        result.temperatures = (start_t, end_t)
    if len(result.profile) > PROFILE_POINTS:
        step = len(result.profile) / PROFILE_POINTS
        picked = [int(i * step) for i in range(PROFILE_POINTS)]
        result.profile = [*(result.profile[i] for i in picked), result.profile[-1]]
    return result


def _profile_key(spec: Any, names: list[str], phase: _Phase, n0: list[float]) -> str:
    """The component the profile follows: the first residue end's key, else the charge's most
    volatile component."""
    for _, end in spec.ends():
        if end is not None and end.residue is not None:
            return end.residue.key
    y, _ = phase.vapour(n0)
    total = sum(n0)
    ratios = [(yi / (n / total) if n > 0 else 0.0) for yi, n in zip(y, n0, strict=True)]
    return names[max(range(len(names)), key=lambda i: ratios[i])]


# -- in a flowsheet -----------------------------------------------------------------------------


def _material(streams: list[Any]) -> list[Any]:
    return [s for s in streams if getattr(s, "kind", "material") == "material"]


def split_inlets(node: Any, inlets: list[Any]) -> tuple[Any, Any]:
    """Still *node*'s charge stream and its swap's feed stream (None) among *inlets*. Raises
    StillError."""
    inlets = _material(inlets)
    spec = node.still
    feed = None
    if spec.feed is not None:
        feed = next((s for s in inlets if s.id == spec.feed.stream), None)
        if feed is None:
            raise StillError(f"the feed stream {spec.feed.stream} is no inlet of {node.id}")
    charges = [s for s in inlets if feed is None or s.id != feed.id]
    if len(charges) != 1:
        raise StillError(
            f"a still takes one charge stream besides its feed ({len(charges)} given): mix the "
            "charge before it"
        )
    return charges[0], feed


def _moles(process: Any, stream: Any, case: str) -> dict[str, float]:
    """kmol/h by component of *stream* in *case*. Raises StillError."""
    from chemeascode.domains.process.model import stream_flows

    flows = stream_flows(process, stream, case)
    if flows.components is None:
        raise StillError(f"no composition and flow of {stream.id}: " + ", ".join(flows.missing))
    comps = process.components()
    lacking = sorted(n for n in flows.components if not getattr(comps.get(n), "molar_mass", None))
    if lacking:
        raise StillError("no molar_mass for " + ", ".join(lacking))
    return {n: kg / comps[n].molar_mass for n, kg in flows.components.items()}


def _pressure(process: Any, stream: Any, case: str) -> float | None:
    from chemeascode.foundation.units import to_kpa_abs

    state = stream.state.get(case)
    p = getattr(state, "pressure", None)
    if p is None:
        return None
    return to_kpa_abs(p.value, p.unit or process.flowsheet.units.pressure)


def inlets_of(process: Any, node: Any) -> list[Any]:
    """The material streams into *node*."""
    return [
        s
        for s in _material(process.flowsheet.streams)
        if (end := process.ends(s)[1]) is not None and end.node == node.id
    ]


def batch_hours(process: Any, case: str) -> tuple[float, str]:
    """h of the flowsheet's flows one batch makes, and where that comes from: the recipe's
    batch size over the flowsheet's rate of its stream, else one hour."""
    from chemeascode.domains.process.recipe import hours_per_batch

    try:
        found = hours_per_batch(process, case)
    except ValueError as failure:
        return 1.0, f"one hour of flows ({failure})"
    if found is None:
        return 1.0, "one hour of flows (no process/recipe.yaml)"
    return found, "process/recipe.yaml batch size"


def outlets_need_hours(spec: Any) -> bool:
    """Whether still *spec*'s outlets depend on the hours of flows per batch: an end at a time
    with a boil-up of the still (not a specific rate, 1/h). Otherwise the hours scale only its
    time and energy per batch."""
    timed = any(e is not None and e.time is not None for _, e in spec.ends())
    return timed and spec.boilup.unit != "1/h"


def _downstream(process: Any, node: Any) -> set[str]:
    """The ids of the streams out of *node* and of every stream downstream of them."""
    found: set[str] = set()
    todo = [node.id]
    seen: set[str] = set()
    while todo:
        at = todo.pop()
        if at in seen:
            continue
        seen.add(at)
        for s in process.flowsheet.streams:
            a, b = process.ends(s)
            if a is not None and a.node == at and s.id not in found:
                found.add(s.id)
                if b is not None:
                    todo.append(b.node)
    return found


def hours_pending(process: Any, node: Any, case: str) -> str | None:
    """Why the hours of flows per batch still *node*'s outlets depend on are not known yet (the
    recipe's batch-size stream has no flow yet), else None. propagate waits for them."""
    from chemeascode.domains.process.recipe import hours_per_batch

    if not outlets_need_hours(node.still) or _circular_hours(process, node) is not None:
        return None  # a circular batch is refused when solved
    try:
        hours_per_batch(process, case)
    except ValueError as failure:
        return f"its end at a time needs the hours of flows per batch: {failure}"
    return None


def _circular_hours(process: Any, node: Any) -> str | None:
    """Why still *node*'s outlets cannot follow from the recipe's batch: its batch-size stream
    is an outlet of the still or downstream of it, while an end at a time makes the outlets
    depend on the hours of flows that stream gives."""
    from chemeascode.domains.process.recipe import load_recipe

    if not outlets_need_hours(node.still):
        return None
    try:
        recipe, _, _ = load_recipe(process.root)
    except (OSError, ValueError):
        return None
    if recipe is None:
        return None
    stream = recipe.batch_size.stream
    if stream in _downstream(process, node):
        return (
            f"its end at a time depends on the hours of flows per batch, and the recipe's "
            f"batch-size stream {stream} is the still's outlet or downstream of it: circular; "
            "put the batch size on its charge (or upstream), or end it otherwise"
        )
    return None


def solve_node(
    process: Any, node: Any, inlets: list[Any], case: str
) -> tuple[StillResult, dict[str, Any]]:
    """Still *node* fed by *inlets* (its charge and a swap's feed) in *case*, and what it was
    solved from (the inputs of its outlets' fingerprint: only what the outlets depend on).
    Raises StillError."""
    from chemeascode.domains.process.solids import solid_components

    spec = node.still
    charge, feed = split_inlets(node, inlets)
    if (circular := _circular_hours(process, node)) is not None:
        raise StillError(circular)
    moles = _moles(process, charge, case)
    fed = _moles(process, feed, case) if feed is not None else None
    pressure = spec.pressure if spec.pressure is not None else _pressure(process, charge, case)
    comps = process.components()
    hours, basis = batch_hours(process, case)
    nonvolatile = solid_components(process)
    try:
        result = solve_still(spec, moles, fed, comps, pressure, hours, nonvolatile)
    except StillError:
        raise
    except (ValueError, OverflowError, ZeroDivisionError) as failure:
        raise StillError(str(failure)) from failure
    if not basis.startswith("process/recipe.yaml"):
        result.notes.append(f"one batch: {basis}")
    result.charge_temperature = _temperature(process, charge, case)
    if spec.heat_up:
        _heat_up(result, comps)
    names = sorted({*moles, *(fed or {})})
    # the fingerprint holds what the outlets' flows and compositions depend on: not the
    # provenance and source texts, not the vapour pressures' fitted ranges (notes only), and
    # the boil-up only through an end at a time
    inputs: dict[str, Any] = {
        "still": spec.model_dump(
            mode="json",
            exclude={
                "boilup": True,
                "heat_up": True,  # the duty's, not the outlets'
                "provenance": True,
                "source": True,
                "volatility": _TEXTS,
            },
        ),
        "molar_mass": {n: getattr(comps.get(n), "molar_mass", None) for n in names},
        "nonvolatile": sorted(nonvolatile & set(names)),
    }
    if spec.volatility.model == "raoult":
        inputs["pressure"] = pressure
        inputs["vapour_pressure"] = {
            n: vp.model_dump(mode="json", exclude={*_TEXTS, "temperature_range"})
            if (vp := getattr(comps.get(n), "vapour_pressure", None))
            else None
            for n in names
        }
    if any(e is not None and e.time is not None for _, e in spec.ends()):
        inputs["boilup"] = spec.boilup.model_dump(mode="json", include={"value", "unit"})
        if spec.boilup.unit != "1/h":
            inputs["hours"] = hours
        if spec.boilup.unit == "kW":
            inputs["heat_of_vaporization"] = {
                n: getattr(comps.get(n), "heat_of_vaporization", None) for n in names
            }
    return result, inputs


def _temperature(process: Any, stream: Any, case: str) -> float | None:
    from chemeascode.foundation.units import to_kelvin

    q = getattr(stream.state.get(case), "temperature", None)
    return to_kelvin(q.value, q.unit or process.flowsheet.units.temperature) if q else None


def _heat_up(result: StillResult, comps: Mapping[str, Any]) -> None:
    """The charge's heat-up from its inlet temperature to its bubble point at the start, kJ per
    batch at the components' ``liquid_heat_capacity`` (``still.heat_up``, ADR 0063), or why it
    is not known. A charge at or above its bubble point takes none (its flash is not
    modelled: a note says so)."""
    t_in = result.charge_temperature
    bubble = result.temperatures[0] if result.temperatures else None
    if t_in is None or bubble is None:
        result.heat_up_missing = "the charge's temperature and its bubble point"
        return
    lacking = sorted(
        n for n, v in result.charge.items() if v > 0 and not comps[n].liquid_heat_capacity
    )
    if lacking:
        result.heat_up_missing = "the liquid_heat_capacity of " + ", ".join(lacking)
        return
    capacity = sum(v * comps[n].liquid_heat_capacity for n, v in result.charge.items() if v > 0)
    if t_in >= bubble:
        result.notes.append(
            f"heat_up: the charge enters at {t_in:.5g} K, at or above its bubble point "
            f"{bubble:.5g} K (its flash is not modelled): no heat-up"
        )
        result.heat_up = 0.0
        return
    result.heat_up = capacity * (bubble - t_in) * result.hours


#: Fields of a still's data that are text about it, not inputs of its outlets.
_TEXTS = {"provenance", "source"}


def node_outlets(process: Any, spec: Any, result: StillResult) -> dict[str, dict[str, float]]:
    """Outlet port -> kg/h by component (the flowsheet's basis)."""
    comps = process.components()

    def kg(moles: Mapping[str, float]) -> dict[str, float]:
        return {n: v * comps[n].molar_mass for n, v in moles.items()}

    found = {cut.outlet: kg(cut.moles) for cut in result.cuts}
    found[spec.outlets["residue"]] = kg(result.residue)
    return found


def outlet_shapes(process: Any, spec: Any, result: StillResult) -> dict[str, dict[str, float]]:
    """Outlet port -> a composition (kg/h by component, any scale) for an empty outlet: a
    cut's vapour at its end."""
    comps = process.components()
    return {
        cut.outlet: {n: y * comps[n].molar_mass for n, y in cut.vapour.items()}
        for cut in result.cuts
    }


# -- rules (cheme validate) ---------------------------------------------------------------------


def _ports(node: Any, direction: str) -> list[str]:
    return [p.id for p in node.ports if p.direction == direction and p.kind == "material"]


def _present(process: Any, streams: list[Any]) -> set[str]:
    """The components *streams* carry: those with a non-zero value in a composition of theirs
    (any case). A stream without a composition in any case yet (not propagated) can carry its
    template's: a template shared by many streams lists components a still never receives."""
    found: set[str] = set()
    templates = process.templates()
    for s in streams:
        own = {
            n
            for state in s.state.values()
            if (comp := getattr(state, "composition", None)) is not None
            for n, v in comp.values.items()
            if v
        }
        if not own and not any(getattr(st, "composition", None) for st in s.state.values()):
            template = templates.get(s.template or "")
            own = set(template.components if template else [])
        found |= own
    return found


def rules(process: Any) -> list[Finding]:
    """``cheme.process-still`` findings: a still's ports, inlets, references and the data its
    volatility and boil-up need."""
    from chemeascode.domains.process.solids import solid_components

    findings: list[Finding] = []
    fs = process.flowsheet
    doc = process.flowsheet_doc
    comps = process.components()
    solids = solid_components(process)

    def add(level: str, message: str, loc: list[Any], node: str, hint: str) -> None:
        findings.append(
            Finding(
                FLOWSHEET_FILE,
                level,  # type: ignore[arg-type]
                "cheme.process-still",
                message,
                line=_yaml_line(doc, loc),
                ids=[node],
                hint=hint,
            )
        )

    # kJ/kmol: a value in kJ/mol (NIST WebBook's, cheme chemistry props') is 1000 times too
    # small, and makes the duty 1000 times too small or a boil-up in kW 1000 times too fast
    for i, comp in enumerate(process.materials.components if process.materials else []):
        h = getattr(comp, "heat_of_vaporization", None)
        if h is not None and h < LEAST_LATENT:
            findings.append(
                Finding(
                    MATERIALS_FILE,
                    "warning",
                    "cheme.process-still",
                    f"{comp.id}: heat_of_vaporization {h:g} kJ/kmol is implausibly small "
                    f"(below {LEAST_LATENT:g} kJ/kmol: no process liquid but a cryogen)",
                    line=_yaml_line(
                        process.materials_doc, ["components", i, "heat_of_vaporization"]
                    ),
                    ids=[comp.id],
                    hint="the unit is kJ/kmol: NIST gives kJ/mol, multiply by 1000",
                )
            )

    nodes = [("steps", i, n) for i, n in enumerate(fs.steps)]
    nodes += [("blocks", i, n) for i, n in enumerate(fs.blocks)]
    for key, index, node in nodes:
        spec = node.still
        if spec is None:
            continue
        loc = [key, index, "still"]
        others = [
            what
            for what, value in (
                ("reactions", node.reactions or node.reactor),
                ("crystallizer", node.crystallizer),
                ("solid_separation", node.solid_separation),
                ("dryer", getattr(node, "dryer", None)),
            )
            if value
        ]
        if others:
            add(
                "error",
                f"{node.id}: a still is not also a {' or '.join(others)}",
                loc,
                node.id,
                "split the step: the reaction, crystallizer or dryer apart from the still",
            )
        outs = _ports(node, "out")
        mapped = [spec.outlets["residue"], *(port for port, _ in spec.ends())]
        wrong = sorted(set(mapped) - set(outs))
        unmapped = sorted(set(outs) - set(mapped))
        if wrong or unmapped or len(set(mapped)) != len(mapped):
            add(
                "error",
                f"{node.id}: the still's outlets and cuts must name each material outlet port "
                "once"
                + (f"; not outlet ports: {', '.join(wrong)}" if wrong else "")
                + (f"; not named: {', '.join(unmapped)}" if unmapped else ""),
                [*loc, "cuts" if spec.cuts else "outlets"],
                node.id,
                "outlets: {distillate: PORT, residue: PORT}, or cuts: [{outlet: PORT, end: ...}]",
            )
        inlets = inlets_of(process, node)
        try:
            split_inlets(node, inlets)
        except StillError as failure:
            add(
                "error",
                f"{node.id}: {failure}",
                [*loc, "feed"] if spec.feed is not None else [key, index, "ports"],
                node.id,
                "one charge stream into the still, and the feed: stream named by its id",
            )
        present = _present(process, inlets)
        for name in spec.nonvolatile:
            if name not in comps:
                add(
                    "error",
                    f"{node.id}: nonvolatile {name} is not a component",
                    [*loc, "nonvolatile"],
                    node.id,
                    f"declare {name} in process/materials.yaml, or remove it",
                )
        for name in spec.volatility.alpha:
            if name not in comps:
                add(
                    "error",
                    f"{node.id}: volatility.alpha names {name}, not a component",
                    [*loc, "volatility", "alpha"],
                    node.id,
                    f"declare {name} in process/materials.yaml, or remove it",
                )
        volatile = sorted(n for n in present if n not in spec.nonvolatile and n not in solids)
        if spec.volatility.model == "constant":
            lacking = [n for n in volatile if n not in spec.volatility.alpha]
            what = "a relative volatility (volatility.alpha)"
            hint = "give alpha for each volatile component (to a common reference), or list it "
            hint += "in nonvolatile"
        else:
            lacking = [
                n for n in volatile if getattr(comps.get(n), "vapour_pressure", None) is None
            ]
            what = "a vapour_pressure (materials.yaml)"
            hint = "give each volatile component its Antoine vapour_pressure with its source, "
            hint += "or list it in nonvolatile"
        if lacking:
            add(
                "error",
                f"{node.id}: the still's {', '.join(lacking)} lack {what}",
                [*loc, "volatility"],
                node.id,
                hint,
            )
        latent = [
            n for n in volatile if getattr(comps.get(n), "heat_of_vaporization", None) is None
        ]
        if latent:
            add(
                "error" if spec.boilup.unit == "kW" else "info",
                f"{node.id}: no heat_of_vaporization of {', '.join(latent)}"
                + (": the boil-up in kW is not known" if spec.boilup.unit == "kW" else ": no duty"),
                [*loc, "boilup"],
                node.id,
                "give heat_of_vaporization (kJ/kmol near the still's temperature) in "
                "materials.yaml with its source",
            )
        for i, (_, end) in enumerate(spec.ends()):
            if end is not None and end.residue is not None and end.residue.key not in comps:
                add(
                    "error",
                    f"{node.id}: the end's residue key {end.residue.key} is not a component",
                    [*loc, *(["cuts", i, "end"] if spec.cuts else ["end"]), "residue"],
                    node.id,
                    "name a component of the charge",
                )
    return findings


# -- the report: cheme process stills -----------------------------------------------------------


class UnknownCase(ValueError):
    """The case asked for is not declared in the flowsheet."""


@dataclass
class StillReport:
    root: Path
    case: str | None
    process: Any
    findings: list[Finding] = field(default_factory=list)
    units: list[dict[str, Any]] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def loaded(self) -> bool:
        return self.process is not None and not any(f.level == "error" for f in self.findings)

    def to_json(self) -> str:
        return json.dumps(
            {
                "case": self.case,
                "units": self.units,
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
                "source": self.source.as_dict(),
            },
            indent=2,
        )


def _amounts(process: Any, moles: Mapping[str, float], hours: float) -> dict[str, Any]:
    """kmol/h, kg/h, per batch (kmol, kg) and the mole fractions of *moles*."""
    comps = process.components()
    total = sum(moles.values())
    kg = sum(v * comps[n].molar_mass for n, v in moles.items())
    return {
        "kmol_h": total,
        "kg_h": kg,
        "kmol_per_batch": total * hours,
        "kg_per_batch": kg * hours,
        "mole_fractions": {n: v / total for n, v in moles.items() if v > 0} if total > 0 else {},
    }


def _flowsheet_differences(
    process: Any, node: Any, case: str, ports: dict[str, dict[str, float]]
) -> list[str]:
    """Where the flowsheet's given or assumed outlet values differ from the model's."""
    from chemeascode.domains.process.crystallization import _compare

    return _compare(process, node, case, ports)


def unit_entry(process: Any, node: Any, case: str) -> dict[str, Any]:
    """One still in *case*: its basis, charge, feed, cuts, residue, time, duty and energy per
    batch, temperatures, profile and notes (or why it is not solved)."""
    from chemeascode.domains.process.model_basis import still_basis

    basis = still_basis(process, node)
    spec = node.still
    entry: dict[str, Any] = {
        "node": node.id,
        "model": "still" if spec.feed is None else "solvent swap",
        "basis": basis.basis,
        "predictive": basis.predictive,
        "sourced": basis.sourced,
        "detail": basis.detail,
        "sources": basis.sources,
        "assumptions": basis.assumptions,
        "limitations": basis.limitations,
        "solution": None,
        "differences": [],
        "problem": None,
    }
    try:
        result, _ = solve_node(process, node, inlets_of(process, node), case)
    except StillError as failure:
        entry["problem"] = str(failure)
        return entry
    h = result.hours
    energy = result.energy
    entry["solution"] = {
        "hours_of_flows_per_batch": h,
        "pressure_kPa": result.pressure,
        "charge": _amounts(process, result.charge, h),
        "fed": _amounts(process, result.fed, h) if spec.feed is not None else None,
        "cuts": [
            {
                "outlet": c.outlet,
                **_amounts(process, c.moles, h),
                "end_time_h": c.time / 3600.0,
                "end_temperature_K": c.temperature,
                "energy_kWh_per_batch": c.energy / 3600.0 if c.energy is not None else None,
            }
            for c in result.cuts
        ],
        "residue": _amounts(process, result.residue, h),
        "boilup_time_h": result.time / 3600.0,
        "duty_kW": result.duty,
        "peak_duty_kW": result.peak_duty,
        "energy_kWh_per_batch": energy / 3600.0 if energy is not None else None,
        # the year average its energy stream carries (ADR 0059): per hour of flows
        "year_average_duty_kW": energy / (h * 3600.0) if energy is not None and h else None,
        "temperatures_K": list(result.temperatures) if result.temperatures else None,
        "key": result.key,
        "profile": [
            {"distilled": a, "time_h": t / 3600.0, "temperature_K": temp, "x_key": x}
            for a, t, temp, x in result.profile
        ],
        "notes": result.notes,
    }
    _heat_entry(process, node, case, result, entry["solution"])
    entry["differences"] = _flowsheet_differences(
        process, node, case, node_outlets(process, spec, result)
    )
    return entry


def _heat_entry(
    process: Any, node: Any, case: str, result: StillResult, solution: dict[str, Any]
) -> None:
    """With ``heat_up`` or a recipe vessel's metal (ADR 0063): the year-average duty its
    energy stream carries is the model's whole duty, with its terms (and the heat-up per
    batch); a still without them reports as before."""
    from chemeascode.domains.process.duties import still_duty
    from chemeascode.domains.process.recipe import metal_of

    try:
        metal = metal_of(process, node.id, case) is not None
    except ValueError:
        metal = True  # declared, its batch's hours not known: the duty says so
    if not node.still.heat_up and not metal:
        return
    duty = still_duty(node, result, process, case)
    solution["year_average_duty_kW"] = duty.heat_kW
    solution["duty_terms_kW"] = dict(duty.terms_kW)
    if duty.missing:
        solution["duty_missing"] = list(duty.missing)
    if node.still.heat_up:
        solution["heat_up_kWh_per_batch"] = (
            result.heat_up / 3600.0 if result.heat_up is not None else None
        )


def still_report(root: Path, case: str | None = None) -> StillReport:
    """Every still (``still:``) of the plant repository at *root* in *case* (default: the
    default case). Raises :class:`NotAPlantRepository` and :class:`UnknownCase`."""
    from chemeascode.domains.process.model import load

    root = Path(root)
    if not (root / PLANT_FILE).is_file():
        raise NotAPlantRepository(f"No {PLANT_FILE} in {root}.")
    source = source_revision(root, REPORT_INPUTS)
    process, findings = load(root)
    report = StillReport(root, None, process, findings, source=source)
    if not report.loaded:
        return report
    case = case or process.flowsheet.default_case()
    if case not in {c.id for c in process.flowsheet.cases}:
        raise UnknownCase(f"unknown case {case!r}")
    report.case = case
    fs = process.flowsheet
    keys = {n.id: ("steps", i) for i, n in enumerate(fs.steps)}
    keys |= {n.id: ("blocks", i) for i, n in enumerate(fs.blocks)}
    for node in [*fs.blocks, *fs.steps]:
        if node.still is None:
            continue
        entry = unit_entry(process, node, case)
        report.units.append(entry)
        line = _yaml_line(process.flowsheet_doc, [*keys[node.id], "still"])

        def add(
            level: str, rule: str, message: str, hint: str, node: Any = node, line: Any = line
        ) -> None:
            report.findings.append(
                Finding(
                    FLOWSHEET_FILE,
                    level,  # type: ignore[arg-type]
                    f"cheme.process-still-{rule}",
                    message,
                    line=line,
                    ids=[node.id],
                    hint=hint,
                )
            )

        if entry["problem"]:
            add(
                "error",
                "unsolved",
                f"{node.id} ({case}): {entry['problem']}",
                "correct the still's specification, the data or the inlet",
            )
        for text in entry["differences"]:
            add(
                "warning",
                "outlet",
                f"{node.id} ({case}): {text}",
                "let cheme process propagate --fill write the outlets, or correct the still",
            )
        for note in (entry["solution"] or {}).get("notes", []):
            add("info", "note", f"{node.id} ({case}): {note}", "check the still's data and basis")
    return report


def report_text(report: StillReport) -> str:
    """The report as ``cheme process stills`` prints it."""

    def num(v: float | None, unit: str = "", fmt: str = ".6g") -> str:
        return "?" if v is None else f"{v:{fmt}}{unit}"

    def comp(fractions: dict[str, float]) -> str:
        return ", ".join(f"{n} {x:.4g}" for n, x in fractions.items())

    lines = []
    for u in report.units:
        lines.append(
            f"{u['model']} {u['node']}: basis {u['basis']} "
            + ("(sourced)" if u["sourced"] else "(not sourced)")
            + f"; {u['detail']}"
        )
        if u["problem"]:
            lines.append(f"  not solved: {u['problem']}")
        sol = u["solution"]
        if sol:
            h = sol["hours_of_flows_per_batch"]
            lines.append(
                f"  per batch ({h:.4g} h of flows): boil-up {sol['boilup_time_h']:.4g} h, "
                f"duty {num(sol['duty_kW'], ' kW', '.4g')} (peak "
                f"{num(sol['peak_duty_kW'], ' kW', '.4g')}), "
                f"{num(sol['energy_kWh_per_batch'], ' kWh', '.4g')}"
                + (
                    f", year average {sol['year_average_duty_kW']:.6g} kW"
                    if sol.get("year_average_duty_kW") is not None
                    else ""
                )
                + (
                    f", still {sol['temperatures_K'][0]:.5g} -> {sol['temperatures_K'][1]:.5g} K"
                    if sol["temperatures_K"]
                    else ""
                )
            )
            if "duty_terms_kW" in sol:  # the heat-up and the vessel's metal (ADR 0063)
                terms = ", ".join(f"{k} {v:.6g}" for k, v in sol["duty_terms_kW"].items())
                lines.append(
                    f"  year-average duty {num(sol['year_average_duty_kW'], ' kW')}"
                    + (f" ({terms} kW)" if terms else "")
                    + (
                        f"; missing {'; '.join(sol['duty_missing'])}"
                        if "duty_missing" in sol
                        else ""
                    )
                )
            rows = [("charge", sol["charge"])]
            if sol["fed"] is not None:
                rows.append(("fed", sol["fed"]))
            rows += [(f"cut {c['outlet']}", c) for c in sol["cuts"]]
            rows.append(("residue", sol["residue"]))
            for label, a in rows:
                extra = ""
                if "end_time_h" in a:
                    extra = f", ends at {a['end_time_h']:.4g} h" + (
                        f", {a['end_temperature_K']:.5g} K" if a["end_temperature_K"] else ""
                    )
                lines.append(
                    f"  {label}: {a['kmol_per_batch']:.6g} kmol ({a['kg_per_batch']:.6g} kg) per "
                    f"batch, {a['kmol_h']:.6g} kmol/h{extra}; {comp(a['mole_fractions'])}"
                )
        for text in u["differences"]:
            lines.append(f"  differs: {text}")
    if not report.units:
        lines.append("no batch still (still:)")
    return "\n".join(lines)
