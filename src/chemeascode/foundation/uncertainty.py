"""The uncertainty of a value, relative to it: one model for every domain.

The LCA defined it first (``lca.yaml`` ``uncertainty:``, sampled by
:mod:`chemeascode.domains.assessment.lca.uncertainty`); the TEA's premises and the process
quantities (``process/flowsheet.yaml``, ``process/simulation.yaml``) give the same shape. A
value without one takes its study's default for its provenance (``StudyUncertainty.defaults``).
"""

from __future__ import annotations

import math
import random
from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from chemeascode.foundation.schema_base import Strict


class Uncertainty(Strict):
    """The uncertainty of a value, relative to it (see :mod:`.uncertainty`).

    ``lognormal`` with ``gsd2`` (95 % within value / gsd2 .. value x gsd2) or ``pedigree``
    scores (five, 1 to 5: reliability, completeness, temporal, geographical, technological)
    on a ``basic`` gsd2; ``normal`` with ``cv``; ``triangular`` or ``uniform`` with ``low`` and
    ``high`` multipliers (e.g. 0.8 and 1.2)."""

    distribution: Literal["lognormal", "normal", "triangular", "uniform"] = "lognormal"
    gsd2: FiniteFloat | None = Field(default=None, ge=1)
    pedigree: list[int] | None = Field(default=None, min_length=5, max_length=5)
    basic: FiniteFloat = Field(default=1.05, ge=1, description="Basic gsd2 under the pedigree.")
    cv: FiniteFloat | None = Field(default=None, ge=0)
    low: FiniteFloat | None = Field(default=None, ge=0)
    high: FiniteFloat | None = Field(default=None, ge=0)
    source: str = ""

    @model_validator(mode="after")
    def _parameters(self) -> Uncertainty:
        if self.pedigree is not None and not all(1 <= s <= 5 for s in self.pedigree):
            raise ValueError("pedigree scores are 1 to 5")
        if self.distribution == "lognormal" and (self.gsd2 is None) == (self.pedigree is None):
            raise ValueError("lognormal needs gsd2 or pedigree (one of them)")
        if self.distribution == "normal" and self.cv is None:
            raise ValueError("normal needs cv")
        bounded = self.low is not None and self.high is not None and self.low <= 1 <= self.high
        if self.distribution in ("triangular", "uniform") and not bounded:
            raise ValueError(f"{self.distribution} needs low <= 1 <= high")
        return self


#: Pedigree uncertainty factors (U, squared geometric standard deviations, combined as ln U in
#: quadrature as in ecoinvent v2): the empirically based factors of Ciroth, A., Muller, S.,
#: Weidema, B., Lesage, P. (2016), Int J Life Cycle Assess 21:1338-1348; scores 1 (best) to 5.
PEDIGREE = {
    "reliability": (1.00, 1.54, 1.61, 1.69, 1.69),
    "completeness": (1.00, 1.03, 1.04, 1.08, 1.08),
    "temporal": (1.00, 1.03, 1.10, 1.19, 1.29),
    "geographical": (1.00, 1.04, 1.08, 1.11, 1.11),
    "technological": (1.00, 1.18, 1.65, 2.08, 2.80),
}


def pedigree_gsd2(scores: list[int], basic: float = 1.05) -> float:
    """The squared geometric standard deviation of pedigree *scores* (five, 1 to 5) on top of
    the *basic* uncertainty."""
    terms = [math.log(basic) ** 2] + [
        math.log(factors[score - 1]) ** 2
        for factors, score in zip(PEDIGREE.values(), scores, strict=True)
    ]
    return math.exp(math.sqrt(sum(terms)))


def draw(spec: Uncertainty | None, rng: random.Random) -> float:
    """One multiplier of the distribution *spec* (None: 1), from the standard library's
    generator *rng* (the LCA's numpy sampler draws the same distributions)."""
    if spec is None:
        return 1.0
    kind = spec.distribution
    if kind == "lognormal":
        gsd2 = spec.gsd2 if spec.gsd2 is not None else pedigree_gsd2(spec.pedigree, spec.basic)
        sigma = math.log(gsd2) / 2.0
        return rng.lognormvariate(0.0, sigma) if sigma > 0 else 1.0
    if kind == "normal":
        return rng.gauss(1.0, spec.cv or 0.0)
    if spec.low == spec.high:
        return 1.0
    if kind == "uniform":
        return rng.uniform(spec.low, spec.high)
    return rng.triangular(spec.low, spec.high, 1.0)
