"""What a cooling failure can still do to a reactor's content (ADR 0069), for the thermal
screening (:mod:`.reaction_hazards`):

- the **network potential**: the largest heat any forward extents ``xi_j >= 0`` of a set of
  reactions together release from a content ``n`` (kmol by component)::

      max  sum_j (-dHr_j) xi_j      subject to  n_i + sum_j a_ij xi_j >= 0  for every i

  with ``a_ij = nu_ij`` for a reactant and ``nu_ij (1 - f_i)`` for a product, ``f_i`` the share
  of a vent component that leaves as it forms (a product that leaves feeds no consecutive
  reaction). One reaction alone gives its run to completion of its limiting reactant (the
  screening's per-reaction rise); a consecutive reaction on a product adds its heat (copper(I)
  chloride: the chlorination and the comproportionation on the copper(II) it forms), and of
  parallel reactions competing for a reactant the more exothermic takes it. A linear
  programme, solved by the simplex method with Bland's rule (exact at a vertex, no tolerance
  on the optimum beyond rounding);
- the **reactive amount** of a component: the most of it the reactions can still consume from
  the content (the same programme, its consumption as the objective), at most what is there.
  A dosed reagent's deliberate excess, with nothing left to react with, is not reactive;
- the **bubble point** of a liquid at a pressure: ``sum_i gamma_i x_i P_i^sat(T) = P`` over
  its volatile components (Raoult's law; ``P_i^sat`` the component's Antoine
  ``vapour_pressure``, else Clausius-Clapeyron from its ``normal_boiling_point`` and
  ``heat_of_vaporization``), by bisection. A component with neither a vapour pressure nor a
  boiling point (a salt, a solid) does not boil; one with a boiling point only cannot be
  placed and is named.

Pure Python, deterministic (ADR 0010).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# the bubble point moved to the process domain, where a batch at reflux follows it (ADR 0074)
from chemeascode.domains.process.batch_kinetics import (  # noqa: F401 - its callers import it here
    bubble_point,
    saturation_pressure,
)

#: Pivots of one simplex solve at most (Bland's rule terminates; this only guards the loop).
MAX_PIVOTS = 10000
#: Relative tolerance of a pivot's and a reduced cost's sign.
TOLERANCE = 1e-12


def simplex(
    c: Sequence[float], rows: Sequence[Sequence[float]], b: Sequence[float]
) -> tuple[float, list[float]] | None:
    """``max c x`` subject to ``rows x <= b``, ``x >= 0``, with every ``b_i >= 0`` (the origin
    is feasible): the optimum and its ``x``, None when it is unbounded. Bland's rule (the
    smallest index enters and leaves), so it does not cycle on a degenerate vertex."""
    n, m = len(c), len(rows)
    scale = max((abs(v) for v in c), default=0.0) or 1.0
    table = [
        [*row, *(1.0 if k == i else 0.0 for k in range(m)), max(bi, 0.0)]
        for i, (row, bi) in enumerate(zip(rows, b, strict=True))
    ]
    z = [*(-v / scale for v in c), *(0.0 for _ in range(m)), 0.0]
    basis = [n + i for i in range(m)]
    for _ in range(MAX_PIVOTS):
        col = next((j for j in range(n + m) if z[j] < -TOLERANCE), None)
        if col is None:
            break
        best: tuple[float, int] | None = None
        for i in range(m):
            a = table[i][col]
            if a > TOLERANCE:
                ratio = table[i][-1] / a
                if (
                    best is None
                    or ratio < best[0]
                    or (ratio == best[0] and basis[i] < basis[best[1]])
                ):
                    best = (ratio, i)
        if best is None:
            return None
        r = best[1]
        pivot = table[r][col]
        table[r] = [v / pivot for v in table[r]]
        for i in range(m):
            if i != r and (f := table[i][col]) != 0.0:
                table[i] = [a - f * p for a, p in zip(table[i], table[r], strict=True)]
        if (f := z[col]) != 0.0:
            z = [a - f * p for a, p in zip(z, table[r], strict=True)]
        basis[r] = col
    x = [0.0] * n
    for i, k in enumerate(basis):
        if k < n:
            x[k] = max(table[i][-1], 0.0)
    return sum(v * xi for v, xi in zip(c, x, strict=True)), x


def _programme(
    reactions: Sequence[Any],
    moles: Mapping[str, float],
    weights: Sequence[float],
    shares: Mapping[str, float] | None = None,
) -> tuple[float, dict[str, float]] | None:
    """``max sum_j w_j xi_j`` over the forward extents of *reactions* on the content *moles*
    (see the module docstring): the optimum and each reaction's extent (kmol), None when it is
    unbounded (a reaction without a reactant, or a cycle of declared heats that gains)."""
    shares = shares or {}
    names = list(dict.fromkeys(n for r in reactions for n in r.stoichiometry))
    rows: list[list[float]] = []
    b: list[float] = []
    for n in names:
        row = []
        for r in reactions:
            nu = r.stoichiometry.get(n, 0.0)
            row.append(-nu if nu < 0 else -nu * (1.0 - shares.get(n, 0.0)))
        if any(v > 0 for v in row):  # a component nothing consumes cannot bind
            rows.append(row)
            b.append(max(moles.get(n, 0.0), 0.0))
    solved = simplex(list(weights), rows, b)
    if solved is None:
        return None
    value, x = solved
    return value, {r.id: xi for r, xi in zip(reactions, x, strict=True)}


def network_heat(
    reactions: Sequence[Any],
    moles: Mapping[str, float],
    heats: Mapping[str, float],
    shares: Mapping[str, float] | None = None,
) -> tuple[float, dict[str, float]] | None:
    """kJ: the largest heat forward extents of *reactions* together release from *moles*
    (*heats*: kJ/kmol of extent, negative exothermic; a reaction without one takes no part),
    and those extents; None when unbounded."""
    picked = [r for r in reactions if r.id in heats]
    if not picked:
        return 0.0, {}
    return _programme(picked, moles, [-heats[r.id] for r in picked], shares)


def reactive(
    reactions: Sequence[Any],
    moles: Mapping[str, float],
    name: str,
    shares: Mapping[str, float] | None = None,
) -> float:
    """kmol of *name* in *moles* that *reactions* can still consume (at most what is there):
    a deliberate excess with nothing left to react with is not reactive."""
    there = max(moles.get(name, 0.0), 0.0)
    if there <= 0:
        return 0.0
    weights = [-r.stoichiometry.get(name, 0.0) for r in reactions]
    if not any(w > 0 for w in weights):
        return 0.0
    solved = _programme(reactions, moles, weights, shares)
    if solved is None:
        return there
    return min(max(solved[0], 0.0), there)


def after(
    reactions: Sequence[Any],
    moles: Mapping[str, float],
    extents: Mapping[str, float],
    shares: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """The content *moles* once *reactions* ran their *extents* (kmol): a vent component's
    vented share has left."""
    shares = shares or {}
    found = dict(moles)
    for r in reactions:
        xi = extents.get(r.id, 0.0)
        for n, nu in r.stoichiometry.items():
            kept = nu if nu < 0 else nu * (1.0 - shares.get(n, 0.0))
            found[n] = max(found.get(n, 0.0) + kept * xi, 0.0)
    return found


def consecutive(reactions: Sequence[Any]) -> list[tuple[str, str]]:
    """(reaction, the reaction whose product it consumes) of each consecutive pair."""
    found = []
    for j in reactions:
        for k in reactions:
            if j.id == k.id:
                continue
            products = {n for n, nu in k.stoichiometry.items() if nu > 0}
            if any(nu < 0 and n in products for n, nu in j.stoichiometry.items()):
                found.append((j.id, k.id))
    return found
