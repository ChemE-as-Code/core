"""Uncertainty of an LCA by Monte Carlo: distributions, pedigree scores, sampling, sensitivity.

A distribution (:class:`~.schemas.Uncertainty`) is relative to the deterministic value: the
sampled multiplier ``m`` has median (lognormal) or mean (normal, uniform) or mode (triangular) 1.

An exchange without an ``uncertainty`` takes the study's default for its origin or provenance
(``uncertainty.defaults``), else the lognormal of its pedigree (:mod:`.quality`): every
exchange has one, so none goes unsampled silently; :attr:`Result.bases` says which applied.

- ``lognormal``: ``gsd2`` (the squared geometric standard deviation: 95 % of the values lie
  within ``value / gsd2`` and ``value x gsd2``), or ``pedigree`` scores (reliability,
  completeness, temporal, geographical and further technological correlation, 1 to 5) with a
  ``basic`` gsd2, combined as in ecoinvent: ``gsd2 = exp(sqrt(sum(ln U_i ** 2)))`` with the
  empirically based uncertainty factors of Ciroth et al. (2016);
- ``normal``: ``cv``, the coefficient of variation (negative draws are kept: the value can
  change sign only if the study says so);
- ``triangular`` and ``uniform``: ``low`` and ``high`` multipliers.

:func:`monte_carlo` samples the exchanges of the plant's dataset (each its own multiplier; the
products' too, so allocation shares move) and the factors (one multiplier per factor, shared by
every row that uses it), recomputes the impacts per functional unit for each iteration, and
ranks the inputs by their Spearman rank correlation with each category's total.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# the pedigree factors are shared with the reactors' sampling: one table, in foundation
from chemeascode.foundation.uncertainty import PEDIGREE as PEDIGREE
from chemeascode.foundation.uncertainty import pedigree_gsd2


def sample(spec, size: int, rng: np.random.Generator) -> np.ndarray:
    """*size* multipliers of the distribution *spec* (None: all 1)."""
    if spec is None:
        return np.ones(size)
    kind = spec.distribution
    if kind == "lognormal":
        gsd2 = spec.gsd2 if spec.gsd2 is not None else pedigree_gsd2(spec.pedigree, spec.basic)
        sigma = math.log(gsd2) / 2.0
        return rng.lognormal(0.0, sigma, size) if sigma > 0 else np.ones(size)
    if kind == "normal":
        return rng.normal(1.0, spec.cv, size)
    if spec.low == spec.high:
        return np.ones(size)  # no spread
    if kind == "uniform":
        return rng.uniform(spec.low, spec.high, size)
    return rng.triangular(spec.low, 1.0, spec.high, size)


def _ranks(values: np.ndarray) -> np.ndarray:
    """Average ranks (ties share the mean of their positions)."""
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    ends = np.cumsum(counts)
    return ((ends - counts + ends - 1) / 2.0)[inverse]


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    """Spearman's rank correlation of *x* and *y* (0 when either is constant)."""
    if np.ptp(x) == 0 or np.ptp(y) == 0:
        return 0.0
    return float(np.corrcoef(_ranks(x), _ranks(y))[0, 1])


@dataclass
class Statistics:
    """The distribution of one category's total per functional unit."""

    category: str
    deterministic: float
    mean: float
    median: float
    sd: float
    low: float  # 2.5th percentile
    high: float  # 97.5th percentile
    #: Inputs by |rank correlation| with the total, largest first: (name, rho).
    sensitivity: list[tuple[str, float]] = field(default_factory=list)


def statistics(
    category: str,
    deterministic: float,
    totals: np.ndarray,
    inputs: dict[str, np.ndarray],
    top: int = 8,
) -> Statistics:
    ranked = sorted(
        ((name, spearman(values, totals)) for name, values in inputs.items()),
        key=lambda item: -abs(item[1]),
    )
    return Statistics(
        category,
        deterministic,
        float(totals.mean()),
        float(np.median(totals)),
        float(totals.std(ddof=1)) if len(totals) > 1 else 0.0,
        float(np.percentile(totals, 2.5)),
        float(np.percentile(totals, 97.5)),
        [(name, rho) for name, rho in ranked[:top] if abs(rho) >= 0.01],
    )


def _derived(exchange, by_key, multiplier, one) -> np.ndarray | None:
    """The multiplier an exchange inherits from what it is derived from (None: independent):
    maintenance from its construction entry; transport, end of life, disposal and avoided
    production from the masses of their source exchanges (mass-weighted). Sources are sampled
    first (dataset order)."""
    if exchange.key.startswith("maintenance:"):
        source = "construction:" + exchange.key.split(":", 1)[1]
        return multiplier.get(source, one) if source in by_key else None
    if exchange.key.split(":", 1)[0] in ("transport", "end-of-life", "disposal", "avoided") and (
        exchange.streams
    ):
        sources = [by_key[s] for s in exchange.streams if s in by_key]
        total = sum(s.amount for s in sources)
        if total <= 0:
            return None
        return sum(s.amount * multiplier.get(s.key, one) for s in sources) / total
    return None


def _spec(exchange, settings) -> tuple[Any, str]:
    """The distribution of an independent exchange and where it comes from: its own; else the
    study's default for its origin (the more specific), then its provenance; else the lognormal
    of its pedigree. No exchange with a pedigree goes unsampled."""
    from chemeascode.domains.assessment.lca.quality import gsd2
    from chemeascode.foundation.uncertainty import Uncertainty

    if exchange.uncertainty is not None:
        return exchange.uncertainty, "given"
    default = settings.defaults.get(exchange.origin or "") or settings.defaults.get(
        exchange.provenance
    )
    if default is not None:
        return default, "study default"
    spread = gsd2(exchange)
    if spread is None:
        return None, ""
    return Uncertainty(gsd2=spread, source="pedigree"), "pedigree"


@dataclass
class Result:
    """The Monte Carlo of a study's baseline."""

    iterations: int
    seed: int
    statistics: list[Statistics] = field(default_factory=list)
    #: The inputs that vary (exchange amounts ``amount:<key>``, factors ``factor:<id>``).
    varied: list[str] = field(default_factory=list)
    #: Where each varied input's distribution comes from: ``given`` (its own), ``study
    #: default`` (lca.yaml uncertainty.defaults or factors) or ``pedigree`` (the exchange's
    #: pedigree on its basic uncertainty, pre-release issue 178).
    bases: dict[str, str] = field(default_factory=dict)


def monte_carlo(inventory, impacts, categories, scope, factors, fu_kg: float) -> Result:
    """Sample the baseline of *inventory* (the plant's dataset, allocated by the study's
    method) and its *impacts*; see the module docstring."""
    from chemeascode.domains.assessment.lca.allocation import PROPORTIONAL, properties

    settings = scope.uncertainty
    n = settings.iterations
    rng = np.random.default_rng(settings.seed)
    dataset = inventory.dataset
    method = inventory.method
    target = scope.functional_unit.product
    inputs: dict[str, np.ndarray] = {}
    #: Where each sampled amount's distribution comes from (given, study default, pedigree).
    bases: dict[str, str] = {}
    multiplier: dict[str, np.ndarray] = {}
    one = np.ones(n)
    by_key = {e.key: e for e in dataset.exchanges}
    fu_key = f"product:{target}"
    for exchange in dataset.exchanges:
        # the reference product is the basis the others are per: not sampled; what carries no
        # burden (free, released, unlinked) cannot move the result: not sampled either
        if exchange.key == fu_key or (exchange.type != "product" and exchange.link is None):
            continue
        derived = _derived(exchange, by_key, multiplier, one)
        if derived is not None:
            spec, basis = exchange.uncertainty, "given"
        else:
            spec, basis = _spec(exchange, settings)
        if derived is None and spec is None:
            continue
        sampled = sample(spec, n, rng) if spec is not None else one
        multiplier[exchange.key] = sampled * (derived if derived is not None else one)
        if spec is not None and np.ptp(sampled) > 0:  # a distribution without spread: fixed
            inputs[f"amount:{exchange.key}"] = sampled
            bases[f"amount:{exchange.key}"] = basis

    def amount(key: str) -> np.ndarray:
        exchange = next(e for e in dataset.exchanges if e.key == key)
        return exchange.amount * multiplier.get(key, one)

    if method in PROPORTIONAL:
        weights = {}
        for product in dataset.products():
            name = product.key.split(":", 1)[1]
            if method == "shares":
                weights[name] = np.full(n, scope.allocation.shares[name])
                continue
            props = properties(product, scope.allocation)
            per = {
                "mass": 1.0,
                "economic": props.price,
                "energy": props.energy,
                "exergy": props.exergy,
            }
            weights[name] = amount(product.key) * per[method]
        share = weights[target] / sum(weights.values())
    else:
        share = one
    scale = share * fu_kg / amount(fu_key)

    by_id = {f.id: f for f in factors.factors} if factors is not None else {}
    background: dict[str, np.ndarray] = {}
    for impact in impacts:
        factor = by_id.get(impact.basis)
        if factor is None or impact.basis in background:
            continue
        spec = factor.uncertainty or settings.factors
        if spec is not None:
            background[impact.basis] = sample(spec, n, rng)
            inputs[f"factor:{impact.basis}"] = background[impact.basis]
            bases[f"factor:{impact.basis}"] = "given" if factor.uncertainty else "study default"

    totals = {c.id: np.zeros(n) for c in categories}
    for impact in impacts:
        if impact.key.startswith("substitution:"):
            other = f"product:{impact.key.split(':', 1)[1]}"
            quantity = -amount(other) * fu_kg / amount(fu_key)
        else:
            quantity = amount(impact.key) * scale
        totals[impact.category] += quantity * impact.factor * background.get(impact.basis, one)
    deterministic = {c.id: 0.0 for c in categories}
    for impact in impacts:
        deterministic[impact.category] += impact.value
    result = Result(n, settings.seed, varied=sorted(inputs), bases=dict(sorted(bases.items())))
    for category in categories:
        result.statistics.append(
            statistics(category.id, deterministic[category.id], totals[category.id], inputs)
        )
    return result
