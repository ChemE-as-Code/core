"""Pinch analysis by the problem table algorithm: energy targets, not an exchanger network.

Each stream has a supply and a target temperature in K and a heat profile: either one constant
heat capacity flow rate (mass flow times specific heat) in kW/K, or piecewise :class:`Segment`
s, each sensible (a heat capacity flow over a temperature range) or isothermal (a latent load in
kW at one temperature: a pure component condensing or boiling). A stream that cools is hot, one
that heats is cold; a stream made only of isothermal segments says which with ``side``. Hot
streams are shifted down and cold streams up by ``dt_min / 2``; the shifted temperatures bound
the intervals, each interval's surplus (hot minus cold heat capacity flow, times its width) is
cascaded from the top, and an isothermal load enters the cascade exactly at its shifted
temperature (an interval of zero width, ``isothermal``). The most negative cumulative value is
the minimum hot utility.

The result is a *target* (``PinchResult.basis == "targets"``): the minimum hot and cold
utility in kW at ``dt_min``, the pinch (as shifted, hot-side and cold-side temperatures) and the
grand composite curve. It is not a synthesized, rated or checked heat exchanger network: no
matches, areas, exchanger counts or utility levels are chosen, and an actual network reaches the
targets only if it is designed to. When one utility is zero the problem is a threshold problem
and has no pinch.

:func:`minimum_approach` is the check the other way round: the least temperature difference
between the hot and cold composite curves of streams that exchange heat in one counter-current
exchanger (or an exchanger against a utility); negative is a temperature cross.

This replaces the PyPinch-based tool of LLM4ChemE (``src/tools/heat_integration``) with the same
algorithm without pandas, matplotlib, printing or files written to the working directory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: Absolute tolerance for a zero heat flow in the cascade, kW.
TOLERANCE = 1e-9
UNITS = {"temperature": "K", "heat_capacity_flow": "kW/K", "heat": "kW"}
#: What a :class:`PinchResult` is, in its own words (``scope``).
TARGETS_SCOPE = (
    "energy targets at dt_min (minimum hot and cold utility, pinch temperatures, grand "
    "composite curve) by the problem table algorithm; not a synthesized, rated or checked heat "
    "exchanger network"
)


@dataclass(frozen=True)
class Segment:
    """One piece of a stream's heat profile: from *supply_temperature* to
    *target_temperature* (K) the stream gives (hot) or takes (cold) *duty* kW. Sensible when the
    temperatures differ (heat capacity flow ``duty / |target - supply|``), isothermal (a latent
    load) when they are equal."""

    supply_temperature: float  # K
    target_temperature: float  # K
    duty: float  # kW, positive

    @classmethod
    def sensible(cls, supply: float, target: float, heat_capacity_flow: float) -> Segment:
        """A sensible segment from its heat capacity flow (kW/K)."""
        return cls(supply, target, heat_capacity_flow * abs(supply - target))

    @classmethod
    def latent(cls, temperature: float, duty: float) -> Segment:
        """An isothermal segment: *duty* kW condensed or boiled at *temperature* K."""
        return cls(temperature, temperature, duty)

    @property
    def isothermal(self) -> bool:
        return self.supply_temperature == self.target_temperature

    @property
    def heat_capacity_flow(self) -> float | None:
        """kW/K; None for an isothermal segment."""
        if self.isothermal:
            return None
        return self.duty / abs(self.supply_temperature - self.target_temperature)


@dataclass(frozen=True)
class PinchStream:
    """A stream from *supply_temperature* to *target_temperature* (K): with a constant
    *heat_capacity_flow* (kW/K), or with *segments* (supply to target, in order; then
    *heat_capacity_flow* is not used). Use :meth:`piecewise` to build one from segments."""

    supply_temperature: float  # K
    target_temperature: float  # K
    heat_capacity_flow: float = 0.0  # kW/K; constant-CP streams
    name: str = ""
    segments: tuple[Segment, ...] = ()
    #: hot or cold; required when supply and target are equal (only isothermal segments).
    side: Literal["hot", "cold"] | None = None

    @classmethod
    def piecewise(
        cls,
        segments: list[Segment] | tuple[Segment, ...],
        name: str = "",
        side: Literal["hot", "cold"] | None = None,
    ) -> PinchStream:
        """A stream through *segments* in order (supply of the first to target of the last)."""
        if not segments:
            raise ValueError(f"{name or 'stream'}: give at least one segment")
        return cls(
            segments[0].supply_temperature,
            segments[-1].target_temperature,
            0.0,
            name,
            tuple(segments),
            side,
        )

    @property
    def kind(self) -> Literal["hot", "cold"]:
        if self.side is not None:
            return self.side
        return "hot" if self.supply_temperature > self.target_temperature else "cold"

    @property
    def profile(self) -> tuple[Segment, ...]:
        """The segments; a constant-CP stream is one sensible segment."""
        if self.segments:
            return self.segments
        return (
            Segment.sensible(
                self.supply_temperature, self.target_temperature, self.heat_capacity_flow
            ),
        )

    @property
    def duty(self) -> float:
        """Heat the stream gives (hot) or takes (cold), kW."""
        return sum(s.duty for s in self.profile)


@dataclass(frozen=True)
class TemperatureInterval:
    high: float  # shifted K
    low: float  # shifted K
    streams: list[int]  # indices into the input
    delta_cp: float  # kW/K, hot minus cold
    delta_h: float  # kW, positive = surplus
    status: Literal["surplus", "deficit", "balanced"]
    #: An isothermal load (high == low): latent heat entering the cascade at that temperature.
    isothermal: bool = False


@dataclass
class PinchResult:
    dt_min: float  # K
    min_hot_utility: float  # kW
    min_cold_utility: float  # kW
    pinch_shifted_temperature: float | None  # K; None for a threshold problem
    pinch_hot_temperature: float | None  # K
    pinch_cold_temperature: float | None  # K
    intervals: list[TemperatureInterval]
    #: (shifted temperature K, net heat flow kW) from the hottest point down; an isothermal
    #: load gives two points at the same temperature.
    grand_composite_curve: list[tuple[float, float]]
    units: dict[str, str] = field(default_factory=lambda: dict(UNITS))
    #: Always ``targets``: minimum utilities and the pinch, not a designed network.
    basis: Literal["targets"] = "targets"
    scope: str = TARGETS_SCOPE

    @property
    def threshold(self) -> bool:
        return self.pinch_shifted_temperature is None


def _check(streams: list[PinchStream]) -> None:
    for i, s in enumerate(streams):
        label = s.name or f"stream {i + 1}"
        if not s.segments:
            if s.heat_capacity_flow <= 0:
                raise ValueError(f"{label}: heat_capacity_flow must be greater than 0")
            if s.supply_temperature == s.target_temperature:
                raise ValueError(f"{label}: supply and target temperature must differ")
            if min(s.supply_temperature, s.target_temperature) < 0:
                raise ValueError(f"{label}: temperatures are in K and must not be negative")
            continue
        if s.supply_temperature == s.target_temperature and s.side is None:
            raise ValueError(f"{label}: an isothermal stream needs side (hot or cold)")
        hot = s.kind == "hot"
        if s.segments[0].supply_temperature != s.supply_temperature or (
            s.segments[-1].target_temperature != s.target_temperature
        ):
            raise ValueError(f"{label}: the segments must run from supply to target temperature")
        for k, seg in enumerate(s.segments):
            if seg.duty <= 0:
                raise ValueError(f"{label}: segment {k + 1} duty must be greater than 0")
            if min(seg.supply_temperature, seg.target_temperature) < 0:
                raise ValueError(f"{label}: temperatures are in K and must not be negative")
            if not seg.isothermal and (seg.supply_temperature > seg.target_temperature) != hot:
                raise ValueError(
                    f"{label}: segment {k + 1} runs the other way than the stream ({s.kind})"
                )
            if k and s.segments[k - 1].target_temperature != seg.supply_temperature:
                raise ValueError(f"{label}: segment {k + 1} does not start where {k} ends")


def pinch_analysis(streams: list[PinchStream], dt_min: float) -> PinchResult:
    """Minimum utilities, pinch and grand composite curve of *streams* at *dt_min* (K): the
    targets (see the module docstring), not a network.

    Raises ``ValueError`` for fewer than two streams, a non-positive heat capacity flow or
    segment duty, a constant-CP stream whose supply equals its target, segments that do not
    join up from supply to target or run against the stream, an isothermal stream without
    ``side``, a temperature below 0 K or a negative *dt_min*.
    """
    if len(streams) < 2:
        raise ValueError("pinch analysis needs at least 2 streams")
    if dt_min < 0:
        raise ValueError("dt_min must not be negative")
    _check(streams)

    shift = dt_min / 2
    #: (stream index, sign, shifted supply, shifted target, segment)
    pieces = []
    for i, s in enumerate(streams):
        sign, offset = (1, -shift) if s.kind == "hot" else (-1, shift)
        for seg in s.profile:
            a, b = seg.supply_temperature + offset, seg.target_temperature + offset
            pieces.append((i, sign, a, b, seg))
    bounds = sorted({t for _, _, a, b, _ in pieces for t in (a, b)}, reverse=True)

    def point_load(t: float) -> TemperatureInterval | None:
        at = [(i, sign, seg) for i, sign, a, _, seg in pieces if seg.isothermal and a == t]
        if not at:
            return None
        q = sum(sign * seg.duty for _, sign, seg in at)
        status = "surplus" if q > 0 else "deficit" if q < 0 else "balanced"
        return TemperatureInterval(t, t, sorted({i for i, _, _ in at}), 0.0, q, status, True)

    intervals = []
    first = point_load(bounds[0])
    if first is not None:
        intervals.append(first)
    for high, low in zip(bounds, bounds[1:], strict=False):
        inside = [
            (i, sign, seg)
            for i, sign, a, b, seg in pieces
            if not seg.isothermal and max(a, b) >= high and min(a, b) <= low
        ]
        delta_cp = sum(sign * (seg.heat_capacity_flow or 0.0) for _, sign, seg in inside)
        delta_h = delta_cp * (high - low)
        status = "surplus" if delta_h > 0 else "deficit" if delta_h < 0 else "balanced"
        ids = sorted({i for i, _, _ in inside})
        intervals.append(TemperatureInterval(high, low, ids, delta_cp, delta_h, status))
        load = point_load(low)
        if load is not None:
            intervals.append(load)

    cumulative, lowest = 0.0, 0.0
    for interval in intervals:
        cumulative += interval.delta_h
        lowest = min(lowest, cumulative)
    hot_utility = -lowest
    curve = [(bounds[0], hot_utility)]
    for interval in intervals:
        curve.append((interval.low, curve[-1][1] + interval.delta_h))
    cold_utility = curve[-1][1]

    # The pinch is where the feasible cascade carries no heat: its smallest flow, the first
    # (hottest) one on a tie. With a zero utility the problem is a threshold problem.
    pinch = None
    if hot_utility > TOLERANCE and cold_utility > TOLERANCE:
        pinch = min(curve, key=lambda point: abs(point[1]))[0]
    return PinchResult(
        dt_min=dt_min,
        min_hot_utility=hot_utility,
        min_cold_utility=cold_utility,
        pinch_shifted_temperature=pinch,
        pinch_hot_temperature=None if pinch is None else pinch + shift,
        pinch_cold_temperature=None if pinch is None else pinch - shift,
        intervals=intervals,
        grand_composite_curve=curve,
    )


# -- composite curves of one exchanger ---------------------------------------------------------


@dataclass(frozen=True)
class Approach:
    """The least temperature difference between the hot and the cold composite curve of one
    counter-current exchange (both curves start at their cold ends, so the hot outlet meets the
    cold inlet), and where it is."""

    minimum: float  # K; negative: a temperature cross
    hot_temperature: float  # K, the hot composite there
    cold_temperature: float  # K, the cold composite there
    heat: float  # kW from the cold end
    hot_duty: float  # kW
    cold_duty: float  # kW

    @property
    def crossed(self) -> bool:
        return self.minimum < 0


def _composite(streams: list[PinchStream]) -> list[tuple[float, float]]:
    """(heat kW from the cold end, temperature K) of the composite curve of *streams* (all on
    one side), ascending; an isothermal load is a run at constant temperature, a range no
    stream covers a jump at constant heat."""
    pieces = [seg for s in streams for seg in s.profile]
    temps = sorted({t for seg in pieces for t in (seg.supply_temperature, seg.target_temperature)})
    points: list[tuple[float, float]] = []
    heat = 0.0
    for k, t in enumerate(temps):
        points.append((heat, t))
        latent = sum(seg.duty for seg in pieces if seg.isothermal and seg.supply_temperature == t)
        if latent:
            heat += latent
            points.append((heat, t))
        if k + 1 < len(temps):
            hi = temps[k + 1]
            cp = sum(
                seg.heat_capacity_flow or 0.0
                for seg in pieces
                if not seg.isothermal
                and min(seg.supply_temperature, seg.target_temperature) <= t
                and max(seg.supply_temperature, seg.target_temperature) >= hi
            )
            heat += cp * (hi - t)
    return points


def _at(points: list[tuple[float, float]], heat: float, lowest: bool) -> float:
    """The temperature of a composite at *heat*: the lowest (hot side) or the highest (cold
    side) where the curve jumps there, so the approach found is never too large."""
    found = []
    for (h0, t0), (h1, t1) in zip(points, points[1:], strict=False):
        if h0 - TOLERANCE <= heat <= h1 + TOLERANCE:
            if h1 - h0 <= TOLERANCE:
                found += [t0, t1]
            else:
                found.append(t0 + (t1 - t0) * (min(max(heat, h0), h1) - h0) / (h1 - h0))
    if not found:
        found = [points[0][1] if heat <= points[0][0] else points[-1][1]]
    return min(found) if lowest else max(found)


def minimum_approach(streams: list[PinchStream]) -> Approach:
    """The least hot-minus-cold temperature difference of *streams* exchanging heat in one
    counter-current exchanger: the composite curves, both from their cold ends, compared at
    every break point up to the smaller of the two duties. Raises ``ValueError`` without at
    least one hot and one cold stream (or for the input :func:`pinch_analysis` refuses)."""
    if len(streams) < 2:
        raise ValueError("an exchanger needs at least 2 streams")
    _check(streams)
    hot = [s for s in streams if s.kind == "hot"]
    cold = [s for s in streams if s.kind == "cold"]
    if not hot or not cold:
        raise ValueError("an exchanger needs a hot and a cold stream")
    h, c = _composite(hot), _composite(cold)
    top = min(h[-1][0], c[-1][0])
    marks = sorted({0.0, top, *(q for q, _ in h + c if q <= top)})
    best: Approach | None = None
    for q in marks:
        th, tc = _at(h, q, lowest=True), _at(c, q, lowest=False)
        if best is None or th - tc < best.minimum:
            best = Approach(th - tc, th, tc, q, h[-1][0], c[-1][0])
    assert best is not None
    return best
