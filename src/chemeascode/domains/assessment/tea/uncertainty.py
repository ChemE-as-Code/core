"""Uncertainty of a TEA: Monte Carlo (P10, P50, P90 and drivers) and the tornado.

The distributions are those of the LCA (:mod:`..lca.uncertainty`): relative multipliers of a
deterministic value. :func:`monte_carlo` samples one multiplier per input id, evaluates every
sample at once (:func:`.model.evaluate`) and ranks the inputs by their Spearman rank correlation
with each metric. P10 and P90 are the 10th and 90th percentiles (the industry's low and high
case); an IRR that does not exist in a sample is left out of its statistics, and a metric that
fewer than half the samples have gets none.

:func:`tornado` moves one input at a time to its low and its high multiplier (its ``swing``,
else the P10 and P90 of its distribution, else the analysis' default swing) and records the
metric at each end, largest swing first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from chemeascode.domains.assessment.lca.uncertainty import pedigree_gsd2, sample, spearman
from chemeascode.domains.assessment.tea.model import Premises, evaluate

#: The standard normal quantile of the 90th percentile.
Z90 = 1.2815515655446004


def p10_p90(spec) -> tuple[float, float]:
    """The 10th and 90th percentile multipliers of the distribution *spec*."""
    kind = spec.distribution
    if kind == "lognormal":
        gsd2 = spec.gsd2 if spec.gsd2 is not None else pedigree_gsd2(spec.pedigree, spec.basic)
        sigma = math.log(gsd2) / 2.0
        return math.exp(-Z90 * sigma), math.exp(Z90 * sigma)
    if kind == "normal":
        return 1.0 - Z90 * spec.cv, 1.0 + Z90 * spec.cv
    low, high = spec.low, spec.high
    if kind == "uniform":
        return low + 0.1 * (high - low), low + 0.9 * (high - low)
    width = high - low
    if width == 0:
        return 1.0, 1.0
    mode = (1.0 - low) / width

    def quantile(q: float) -> float:
        if q < mode:
            return low + math.sqrt(q * width * (1.0 - low))
        return high - math.sqrt((1.0 - q) * width * (high - 1.0))

    return quantile(0.1), quantile(0.9)


@dataclass
class Statistic:
    """The distribution of one metric over the samples."""

    metric: str
    unit: str
    deterministic: float
    mean: float
    p10: float
    p50: float
    p90: float
    #: The samples in which the metric exists (an IRR may not).
    valid: int
    #: Inputs by |rank correlation| with the metric, largest first: (input id, rho).
    sensitivity: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class MonteCarlo:
    iterations: int
    seed: int
    statistics: list[Statistic] = field(default_factory=list)
    #: The input ids that vary.
    varied: list[str] = field(default_factory=list)
    #: The probability that the decision metric meets its threshold (None without a decision).
    probability: float | None = None


def monte_carlo(
    p: Premises,
    specs: dict,
    iterations: int,
    seed: int,
    units: dict[str, tuple[str, float]],
    deterministic: dict[str, float],
    decision: tuple[str, float] | None = None,
    scale: dict | None = None,
    top: int = 8,
) -> MonteCarlo:
    """Sample the inputs of *specs* (input id -> distribution) around *p* (and its *scale*).

    *units* gives each reported metric (fixed_capital, npv, irr, lcop) its unit and the factor
    from the model's value to it; *decision* is (metric, threshold in the reported unit)."""
    rng = np.random.default_rng(seed)
    n = iterations
    inputs = {name: sample(spec, n, rng) for name, spec in specs.items()}
    draws = dict(scale or {})
    for name, values in inputs.items():
        draws[name] = values * draws.get(name, 1.0)
    need = "lcop" in units or (decision is not None and decision[0] == "lcop")
    outcome = evaluate(p, draws, n, lcop=need)
    result = MonteCarlo(n, seed, varied=sorted(inputs))
    for metric, (unit, factor) in units.items():
        values = getattr(outcome, metric) * factor
        ok = np.isfinite(values)
        kept = values[ok]
        if ok.sum() < n / 2:
            continue  # e.g. an IRR that most samples do not have: no meaningful statistics
        ranked = sorted(
            ((name, spearman(sampled[ok], kept)) for name, sampled in inputs.items()),
            key=lambda item: -abs(item[1]),
        )
        result.statistics.append(
            Statistic(
                metric,
                unit,
                deterministic[metric],
                float(kept.mean()),
                float(np.percentile(kept, 10)),
                float(np.percentile(kept, 50)),
                float(np.percentile(kept, 90)),
                int(ok.sum()),
                [(name, rho) for name, rho in ranked[:top] if abs(rho) >= 0.01],
            )
        )
    if decision is not None:
        metric, threshold = decision
        values = getattr(outcome, metric) * units[metric][1]
        meets = values <= threshold if metric in ("lcop", "cash_cost") else values >= threshold
        result.probability = float(np.mean(np.where(np.isfinite(values), meets, False)))
    return result


@dataclass
class Bar:
    """One input of the tornado: its low and high multiplier and the metric at each."""

    input: str
    low: float
    high: float
    #: Where the swing comes from: swing, P10/P90, default.
    basis: str
    at_low: float
    at_high: float

    @property
    def width(self) -> float:
        if not (math.isfinite(self.at_low) and math.isfinite(self.at_high)):
            return 0.0  # e.g. no IRR at one end: ranked last
        return abs(self.at_high - self.at_low)


def tornado(
    p: Premises,
    swings: dict[str, tuple[float, float, str]],
    metric: str,
    factor: float,
    scale: dict | None = None,
) -> list[Bar]:
    """Each input of *swings* (id -> low, high, basis) at its low and high multiplier, the
    others at their value; largest effect on *metric* (times *factor*) first."""
    base = dict(scale or {})
    bars = []
    for name, (low, high, basis) in swings.items():
        own = base.get(name, 1.0)
        outcome = evaluate(
            p, {**base, name: np.array([low * own, high * own])}, 2, lcop=metric == "lcop"
        )
        values = outcome.metric(metric) * factor
        bars.append(Bar(name, low, high, basis, float(values[0]), float(values[1])))
    return sorted(bars, key=lambda bar: (-bar.width, bar.input))
