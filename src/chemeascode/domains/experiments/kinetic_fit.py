"""Kinetic data and the rate laws fitted to them.

A kinetic data file (``experiments/kinetics/<name>.yaml``, schema ``cheme/kinetic-data/v1``)
holds measured (or calculated) rates of one reaction: per point the temperature, the partial
pressures in bar and the rate per kg of catalyst or per m3 (kmol/(kg s), kmol/(m3 s)), with the
data set's provenance and source. :func:`fit_power_law` fits
``ln r = ln A - Ea / (R T) + sum a_i ln p_i`` (divided by ``1 - Q/K`` for a reversible
reaction) by linear least squares; :func:`fit_lhhw` fits an LHHW law by Levenberg-Marquardt on
``ln r``, started from the power law. Both return the rate law (:class:`~chemeascode.domains.
chemistry.rates.RateLaw`, provenance ``calculated``) with the standard error and the 95 %
interval of every parameter, the residuals and R^2 of ``ln r``. :func:`sample_mechanism` makes a
data set from a mean-field mechanism (the TOF times the sites per kg), so a microkinetic model
can be lumped into a rate law for a fixed bed. Pure Python.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import Field, model_validator

from chemeascode.domains.chemistry.microkinetics import NoSteadyState
from chemeascode.domains.chemistry.microkinetics import _solve_linear as _solve_exact
from chemeascode.domains.chemistry.rates import R, RateLaw
from chemeascode.foundation.schema_base import Provenance, Strict, unsupported_schema

SCHEMA = "cheme/kinetic-data/v1"


class Point(Strict):
    temperature: float = Field(gt=0, description="K")
    partial_pressures: dict[str, float] = Field(min_length=1, description="bar, by component id")
    rate: float = Field(gt=0, description="kmol/(kg s) or kmol/(m3 s), by the data set's basis")


class IntegralPoint(Strict):
    """A conversion measured in an isothermal reactor of constant density: a plug-flow or batch
    reactor after a (space) ``time``, or a stirred tank of that space time."""

    reactor: Literal["pfr", "batch", "cstr"]
    temperature: float = Field(gt=0, description="K")
    time: float = Field(gt=0, description="s: the batch time, or the space time V / Q0")
    concentrations: dict[str, float] = Field(
        min_length=1, description="kmol/m3 of the feed or charge, by component id"
    )
    conversion: float = Field(gt=0, lt=1, description="of the data set's key component")


class KineticData(Strict):
    """Rates of one reaction, or conversions measured in reactors (``integral``)."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["kinetic-data"]
    reaction: str = Field(description="The reaction id of process/reactions.yaml.")
    catalyst: str = ""
    basis: Literal["catalyst_mass", "volume"]
    points: list[Point] = Field(default_factory=list, description="Measured rates.")
    # integral data: left out of dumps when unset, so rate files are written as before
    key: str = Field(
        default="",
        description="The component the integral conversions are of.",
        exclude_if=lambda value: not value,
    )
    integral: list[IntegralPoint] = Field(
        default_factory=list,
        description="Measured conversions (instead of rates).",
        exclude_if=lambda value: not value,
    )
    catalyst_loading: float | None = Field(
        default=None,
        gt=0,
        description="kg/m3 in the reactor: integral data per kg of catalyst",
        exclude_if=lambda value: value is None,
    )
    provenance: Provenance
    source: str = ""

    @model_validator(mode="after")
    def _version(self) -> KineticData:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        if len(self.points) < 2 and len(self.integral) < 2:
            raise ValueError("give at least two points (rates) or two integral points")
        if self.points and self.integral:
            raise ValueError("give rates (points) or conversions (integral), not both")
        if self.integral and not self.key:
            raise ValueError("integral data name the key component their conversions are of")
        if self.integral and self.basis == "catalyst_mass" and self.catalyst_loading is None:
            raise ValueError("integral data per kg of catalyst need the catalyst_loading")
        return self


@dataclass
class Fit:
    """A rate law fitted to data, with its quality."""

    law: RateLaw
    #: parameter name -> (value, standard error); ln A, Ea (kJ/kmol), the orders, ...
    parameters: dict[str, tuple[float, float]]
    residuals: list[float]  # ln r measured - ln r fitted
    r_squared: float
    points: int
    notes: list[str] = field(default_factory=list)

    def interval(self, name: str) -> tuple[float, float]:
        """The 95 % interval of a parameter (t quantile of the degrees of freedom)."""
        value, error = self.parameters[name]
        t = _t95(self.points - len(self.parameters))
        return value - t * error, value + t * error


def _t95(dof: int) -> float:
    """Two-sided 95 % quantile of Student's t."""
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        15: 2.131,
        20: 2.086,
        30: 2.042,
        60: 2.000,
    }
    if dof <= 0:
        return math.inf
    # the nearest tabulated dof at or below: the larger quantile, so the interval is not narrow
    return table[max(k for k in table if k <= dof)]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    try:
        return _solve_exact(a, b)
    except NoSteadyState as failure:  # its "singular Jacobian"
        raise ValueError("the data do not determine every parameter (singular)") from failure


def _inverse(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    columns = [_solve(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)]
    return [[columns[j][i] for j in range(n)] for i in range(n)]


def _driving(
    data: KineticData,
    stoichiometry: Mapping[str, float],
    ln_k: Callable[[float], float] | None,
) -> list[float]:
    """ln(1 - Q/K) of every point (0 without *ln_k*); ValueError for a point at or beyond
    equilibrium."""
    out = []
    for i, point in enumerate(data.points):
        if ln_k is None:
            out.append(0.0)
            continue
        p = point.partial_pressures
        absent = [n for n, nu in stoichiometry.items() if nu < 0 and p.get(n, 0.0) <= 0]
        if absent:
            raise ValueError(
                f"point {i + 1}: reactant {', '.join(absent)} absent: (1 - Q/K) is not defined"
            )
        if any(p.get(n, 0.0) <= 0 for n in stoichiometry):
            out.append(0.0)  # a product absent: Q = 0
            continue
        ln_q = sum(nu * math.log(p[n]) for n, nu in stoichiometry.items())
        approach = 1.0 - math.exp(ln_q - ln_k(point.temperature))
        if approach <= 0:
            raise ValueError(f"point {i + 1} is at or beyond equilibrium (Q >= K)")
        out.append(math.log(approach))
    return out


def fit_power_law(
    data: KineticData,
    orders_of: Sequence[str],
    stoichiometry: Mapping[str, float] | None = None,
    ln_k: Callable[[float], float] | None = None,
    catalyst: str = "",
) -> Fit:
    """``r = A exp(-Ea/RT) prod p_i^a_i (1 - Q/K)`` fitted to *data* (*orders_of*: the
    components with an order; *ln_k*: ln K(T) for the reversible factor)."""
    if ln_k is not None and stoichiometry is None:
        raise ValueError("the reversible factor needs the stoichiometry")
    for i, point in enumerate(data.points):
        lacking = [n for n in orders_of if point.partial_pressures.get(n, 0.0) <= 0]
        if lacking:
            raise ValueError(f"point {i + 1}: no partial pressure of {', '.join(lacking)}")
    shift = _driving(data, stoichiometry or {}, ln_k)
    rows = [
        [
            1.0,
            -1.0 / (R * point.temperature),
            *(math.log(point.partial_pressures[n]) for n in orders_of),
        ]
        for point in data.points
    ]
    y = [math.log(point.rate) - s for point, s in zip(data.points, shift, strict=True)]
    names = ["ln_A", "Ea", *(f"order_{n}" for n in orders_of)]
    if len(data.points) <= len(names):
        raise ValueError(f"{len(data.points)} points for {len(names)} parameters: give more data")
    _determined(rows, names)
    ata = [[sum(r[i] * r[j] for r in rows) for j in range(len(names))] for i in range(len(names))]
    aty = [sum(r[i] * v for r, v in zip(rows, y, strict=True)) for i in range(len(names))]
    beta = _solve(ata, aty)
    fitted = [sum(c * b for c, b in zip(r, beta, strict=True)) for r in rows]
    residuals = [v - f for v, f in zip(y, fitted, strict=True)]
    dof = len(rows) - len(names)
    s2 = sum(e * e for e in residuals) / dof
    cov = _inverse(ata)
    mean = sum(y) / len(y)
    total = sum((v - mean) ** 2 for v in y)
    if beta[0] > 700:
        raise ValueError("the fitted pre-exponential factor overflows: check the rate units")
    law = RateLaw(
        form="power_law",
        basis=data.basis,
        driving="partial_pressure",
        k={"A": math.exp(beta[0]), "Ea": beta[1]},
        orders={n: beta[2 + i] for i, n in enumerate(orders_of)},
        reverse="equilibrium" if ln_k is not None else "none",
        catalyst=catalyst or data.catalyst,
        temperature_range=_range(data),
        provenance="calculated",
        source=f"fitted to {len(rows)} points ({data.provenance}: {data.source})",
    )
    return Fit(
        law,
        {n: (beta[i], math.sqrt(max(cov[i][i] * s2, 0.0))) for i, n in enumerate(names)},
        residuals,
        1.0 - sum(e * e for e in residuals) / total if total > 0 else 1.0,
        len(rows),
    )


def _determined(rows: list[list[float]], names: list[str]) -> None:
    """ValueError naming a parameter whose column does not vary (one temperature: no Ea; one
    pressure of a component: no order)."""
    for j, name in enumerate(names[1:], start=1):
        values = [r[j] for r in rows]
        if max(values) - min(values) <= 1e-12 * max(1.0, max(abs(v) for v in values)):
            what = "temperature" if name == "Ea" else f"partial pressure of {name.split('_', 1)[1]}"
            raise ValueError(f"the data have one {what} only: {name} is not determined")


def _range(data: KineticData) -> tuple[float, float] | None:
    temperatures = [p.temperature for p in data.points]
    lo, hi = min(temperatures), max(temperatures)
    return (lo, hi) if lo < hi else None


def fit_lhhw(
    data: KineticData,
    orders: Mapping[str, float],
    adsorbed: Sequence[str],
    power: float = 1.0,
    stoichiometry: Mapping[str, float] | None = None,
    ln_k: Callable[[float], float] | None = None,
    catalyst: str = "",
) -> Fit:
    """``r = A exp(-Ea/RT) prod p_i^a_i (1 - Q/K) / (1 + sum_j K_j p_j)^m`` fitted to *data*:
    the numerator *orders* and the denominator exponent *power* are fixed, the parameters are
    ln A, Ea and per adsorbed component ln A_j and dH_j (``K_j = A_j exp(-dH_j / RT)``);
    Levenberg-Marquardt on ln r."""
    shift = _driving(data, stoichiometry or {}, ln_k)
    orders = {n: a for n, a in orders.items() if a != 0}  # a zero order needs no pressure
    for i, point in enumerate(data.points):
        lacking = [n for n in orders if point.partial_pressures.get(n, 0.0) <= 0]
        if lacking:
            raise ValueError(f"point {i + 1}: no partial pressure of {', '.join(lacking)}")
    for n in adsorbed:
        if all(p.partial_pressures.get(n, 0.0) <= 0 for p in data.points):
            raise ValueError(f"{n} is adsorbed, but no point has a partial pressure of it")
    names = ["ln_A", "Ea", *(f"ln_K_{n}" for n in adsorbed), *(f"dH_{n}" for n in adsorbed)]
    if len(data.points) <= len(names):
        raise ValueError(f"{len(data.points)} points for {len(names)} parameters: give more data")
    y = [math.log(p.rate) - s for p, s in zip(data.points, shift, strict=True)]
    k = len(adsorbed)
    # start: the numerator as a power law with the given orders, no adsorption
    start_a = sum(
        v + 0.0 - sum(a * math.log(p.partial_pressures[n]) for n, a in orders.items())
        for v, p in zip(y, data.points, strict=True)
    ) / len(y)
    beta = [start_a, 0.0, *([0.0] * k), *([0.0] * k)]

    def model(b: list[float]) -> list[float]:
        out = []
        for p in data.points:
            t = p.temperature
            numerator = (
                b[0]
                - b[1] / (R * t)
                + sum(a * math.log(p.partial_pressures[n]) for n, a in orders.items())
            )
            terms = sum(
                math.exp(min(b[2 + j] - b[2 + k + j] / (R * t), 700.0))
                * p.partial_pressures.get(n, 0.0)
                for j, n in enumerate(adsorbed)
            )
            out.append(numerator - power * math.log(1.0 + terms))
        return out

    def cost(b):
        return sum((v - f) ** 2 for v, f in zip(y, model(b), strict=True))

    lam = 1e-3
    current = cost(beta)
    scales = [1.0, 1e4, *([1.0] * k), *([1e4] * k)]
    for _ in range(500):
        f0 = model(beta)
        jac = []
        for i in range(len(beta)):
            h = 1e-6 * scales[i]
            b = list(beta)
            b[i] += h
            fi = model(b)
            jac.append([(a - c) / h for a, c in zip(fi, f0, strict=True)])
        res = [v - f for v, f in zip(y, f0, strict=True)]
        jtj = [
            [sum(jac[i][n] * jac[j][n] for n in range(len(y))) for j in range(len(beta))]
            for i in range(len(beta))
        ]
        jtr = [sum(jac[i][n] * res[n] for n in range(len(y))) for i in range(len(beta))]
        improved = False
        while lam < 1e12:
            a = [
                [jtj[i][j] + (lam * jtj[i][i] if i == j else 0.0) for j in range(len(beta))]
                for i in range(len(beta))
            ]
            try:
                step = _solve(a, jtr)
            except ValueError:
                lam *= 10
                continue
            trial = [b + s for b, s in zip(beta, step, strict=True)]
            new = cost(trial)
            if new < current:
                change = current - new
                beta, current, lam, improved = trial, new, max(lam / 10, 1e-12), True
                break
            lam *= 10
        if not improved or change < 1e-14 * max(current, 1e-30):
            break
    f0 = model(beta)
    residuals = [v - f for v, f in zip(y, f0, strict=True)]
    dof = len(y) - len(beta)
    s2 = current / dof
    jac = []
    for i in range(len(beta)):
        h = 1e-6 * scales[i]
        b = list(beta)
        b[i] += h
        jac.append([(a - c) / h for a, c in zip(model(b), f0, strict=True)])
    jtj = [
        [sum(jac[i][n] * jac[j][n] for n in range(len(y))) for j in range(len(beta))]
        for i in range(len(beta))
    ]
    notes: list[str] = []
    try:
        cov = _inverse(jtj)
    except ValueError as failure:
        raise ValueError(
            "the data do not determine every LHHW parameter: give more conditions, or fit a "
            "power law"
        ) from failure
    errors = [math.sqrt(max(cov[i][i] * s2, 0.0)) for i in range(len(beta))]
    weak = [
        n
        for j, n in enumerate(adsorbed)
        if max(
            math.exp(min(beta[2 + j] - beta[2 + k + j] / (R * p.temperature), 700.0))
            * p.partial_pressures.get(n, 0.0)
            for p in data.points
        )
        < 1e-6
    ]
    if weak or not math.isfinite(beta[0]):
        raise ValueError(
            "the LHHW form does not fit these data (no adsorption term matters for "
            + (", ".join(weak) or "the rate")
            + "): fit a power law"
        )
    mean = sum(y) / len(y)
    total = sum((v - mean) ** 2 for v in y)
    law = RateLaw(
        form="lhhw",
        basis=data.basis,
        driving="partial_pressure",
        k={"A": math.exp(beta[0]), "Ea": beta[1]},
        orders=dict(orders),
        reverse="equilibrium" if ln_k is not None else "none",
        adsorption=[
            {"A": math.exp(beta[2 + j]), "dH": beta[2 + k + j], "exponents": {n: 1.0}}
            for j, n in enumerate(adsorbed)
        ],
        power=power,
        catalyst=catalyst or data.catalyst,
        temperature_range=_range(data),
        provenance="calculated",
        source=f"fitted to {len(y)} points ({data.provenance}: {data.source})",
    )
    return Fit(
        law,
        {n: (beta[i], errors[i]) for i, n in enumerate(names)},
        residuals,
        1.0 - current / total if total > 0 else 1.0,
        len(y),
        notes,
    )


def sample_mechanism(
    mech: Any,
    masses: Mapping[str, float],
    product: str,
    stoichiometric: float,
    temperatures: Sequence[float],
    pressures: Mapping[str, Sequence[float]],
    sites_per_kg: float,
    reaction: str,
) -> KineticData:
    """A data set of the steady state of *mech* over the grid of *temperatures* (K) and
    partial *pressures* (bar, every combination): the rate of the reaction as written, per kg,
    is the TOF of *product* divided by its *stoichiometric* coefficient, times *sites_per_kg*
    (kmol of sites per kg of catalyst)."""
    from itertools import product as combinations

    from chemeascode.domains.chemistry.microkinetics import steady_state

    names = list(pressures)
    points = []
    for t in temperatures:
        start = None
        for values in combinations(*(pressures[n] for n in names)):
            p = dict(zip(names, values, strict=True))
            state = steady_state(mech, t, p, masses, start=start)
            start = state.coverages
            tof = state.tof(product) / stoichiometric
            if tof > 0:
                points.append(Point(temperature=t, partial_pressures=p, rate=tof * sites_per_kg))
    return KineticData.model_validate(
        {
            "schema": SCHEMA,
            "kind": "kinetic-data",
            "reaction": reaction,
            "catalyst": mech.catalyst,
            "basis": "catalyst_mass",
            "points": [pt.model_dump() for pt in points],
            "provenance": "calculated",
            "source": f"the mechanism of {reaction} ({mech.provenance}: {mech.source}), "
            f"{sites_per_kg:g} kmol sites/kg",
        }
    )


# -- integral data ------------------------------------------------------------------------------


def _conversion(
    point: IntegralPoint,
    key: str,
    stoichiometry: Mapping[str, float],
    orders: Mapping[str, float],
    k: float,
    loading: float,
) -> float:
    """The conversion of *key* the power law ``k prod c_i^a_i`` (per m3, times *loading*) gives
    in *point*'s isothermal reactor of constant density."""
    c0 = point.concentrations
    nu_key = -stoichiometry[key]

    def rate(x: float) -> float:
        c = dict(c0)  # a fed species outside the reaction (an inhibitor) keeps its feed value
        c.update({n: c0.get(n, 0.0) + nu / nu_key * c0[key] * x for n, nu in stoichiometry.items()})
        return loading * k * math.prod(max(c.get(n, 0.0), 0.0) ** a for n, a in orders.items())

    if point.reactor == "cstr":
        # X c0 = nu tau r(X): the residual rises from below zero at X = 0 for a positive rate
        lo, hi = 0.0, 1.0
        for _ in range(100):
            mid = (lo + hi) / 2
            if mid * c0[key] - nu_key * point.time * rate(mid) < 0:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    # dX/dt = nu r(X) / c0: classic RK4 in 400 steps (smooth, monotone)
    x, steps = 0.0, 400
    h = point.time / steps
    f = lambda v: nu_key * rate(min(max(v, 0.0), 1.0)) / c0[key]  # noqa: E731
    for _ in range(steps):
        k1 = f(x)
        k2 = f(x + h * k1 / 2)
        k3 = f(x + h * k2 / 2)
        k4 = f(x + h * k3)
        x = min(x + h * (k1 + 2 * k2 + 2 * k3 + k4) / 6, 1.0)
    return x


def fit_integral(
    data: KineticData,
    stoichiometry: Mapping[str, float],
    orders: Mapping[str, float],
    fit_orders: Sequence[str] = (),
    catalyst: str = "",
) -> Fit:
    """A power law ``r = A exp(-Ea/RT) prod c_i^a_i`` (kmol/m3; per m3, or per kg of catalyst
    with the data's ``catalyst_loading``) fitted to the conversions of *data*'s ``integral``
    points by Levenberg-Marquardt: ln k at the mean temperature, Ea and the orders
    *fit_orders* (the others fixed at *orders*). The residuals are the conversions' (measured
    minus fitted); the 95 % intervals come from the covariance. Raises ValueError (also for
    data at one temperature, where Ea is not determined)."""
    points = data.integral
    key = data.key
    if stoichiometry.get(key, 0.0) >= 0:
        raise ValueError(f"the key {key} is not a reactant of {data.reaction}")
    if lacking := [i + 1 for i, p in enumerate(points) if p.concentrations.get(key, 0.0) <= 0]:
        raise ValueError(f"no feed concentration of {key} in point(s) {lacking}")
    temps = [p.temperature for p in points]
    t_ref = sum(temps) / len(temps)
    names = ["ln_k_ref", "Ea", *(f"order_{n}" for n in fit_orders)]
    if max(temps) - min(temps) <= 1e-9:  # Ea would be 0 and the law valid at any T
        raise ValueError("the data have one temperature only: Ea is not determined")
    if len(points) <= len(names):
        raise ValueError(f"{len(points)} points for {len(names)} parameters: give more data")
    loading = data.catalyst_loading if data.basis == "catalyst_mass" else 1.0

    def unpack(theta: list[float]) -> tuple[float, float, dict[str, float]]:
        values = dict(zip(names, theta, strict=True))
        found = dict(orders)
        for n in fit_orders:
            found[n] = values[f"order_{n}"]
        return values["ln_k_ref"], values["Ea"], found

    def residuals(theta: list[float]) -> list[float]:
        ln_k_ref, ea, found = unpack(theta)
        out = []
        for p in points:
            try:
                k = math.exp(ln_k_ref - ea / R * (1 / p.temperature - 1 / t_ref))
                x = _conversion(p, key, stoichiometry, found, k, loading)
            except (OverflowError, ZeroDivisionError):
                x = 2.0  # an unphysical trial step: a residual the fit steps back from
            out.append(p.conversion - x)
        return out

    # start: ln k from the mean point as if first order in a batch, Ea 50000 kJ/kmol
    guess = [
        math.log(sum(-math.log(1 - p.conversion) / p.time for p in points) / len(points))
        - math.log(loading or 1.0),
        50000.0,
        *(float(orders.get(n, 1.0)) for n in fit_orders),
    ]
    theta = list(guess)
    res = residuals(theta)
    cost = sum(r * r for r in res)
    lam = 1e-3
    steps = [1e-6] * len(names)  # relative finite-difference steps
    jac: list[list[float]] = []
    for _ in range(200):
        jac = []
        for j in range(len(names)):
            h = steps[j] * max(1.0, abs(theta[j]))
            trial = list(theta)
            trial[j] += h
            jac.append([(b - a) / h for a, b in zip(res, residuals(trial), strict=True)])
        jtj = [
            [sum(jac[i][k] * jac[j][k] for k in range(len(res))) for j in range(len(names))]
            for i in range(len(names))
        ]
        jtr = [sum(jac[i][k] * res[k] for k in range(len(res))) for i in range(len(names))]
        improved = False
        while lam < 1e12:
            damped = [
                [v + (lam * jtj[i][i] if i == j else 0.0) for j, v in enumerate(row)]
                for i, row in enumerate(jtj)
            ]
            step = _solve(damped, [-v for v in jtr])
            trial = [a + b for a, b in zip(theta, step, strict=True)]
            new = residuals(trial)
            new_cost = sum(r * r for r in new)
            if new_cost < cost:
                theta, res, cost = trial, new, new_cost
                lam = max(lam / 10, 1e-12)
                improved = True
                break
            lam *= 10
        if (
            not improved
            or max(abs(b) / max(1.0, abs(a)) for a, b in zip(theta, step, strict=True)) < 1e-10
        ):
            break
    dof = len(points) - len(names)
    s2 = cost / dof
    jac = []  # the covariance from the Jacobian at the final parameters
    for j in range(len(names)):
        h = steps[j] * max(1.0, abs(theta[j]))
        trial = list(theta)
        trial[j] += h
        jac.append([(b - a) / h for a, b in zip(res, residuals(trial), strict=True)])
    jtj = [
        [sum(jac[i][k] * jac[j][k] for k in range(len(res))) for j in range(len(names))]
        for i in range(len(names))
    ]
    cov = _inverse(jtj)
    ln_k_ref, ea, found = unpack(theta)
    ln_a = ln_k_ref + ea / (R * t_ref)
    if ln_a > 700:
        raise ValueError("the fitted pre-exponential factor overflows: check the units")
    measured = [p.conversion for p in points]
    mean = sum(measured) / len(measured)
    total = sum((v - mean) ** 2 for v in measured)
    notes = [
        f"fitted to conversions in isothermal reactors of constant density; k at {t_ref:.6g} K",
    ]
    law = RateLaw(
        form="power_law",
        basis=data.basis,
        driving="concentration",
        k={"A": math.exp(ln_a), "Ea": ea},
        orders=found,
        catalyst=catalyst or data.catalyst,
        temperature_range=(min(temps), max(temps)),
        provenance="calculated",
        source=f"fitted to {len(points)} conversions ({data.provenance}: {data.source})",
    )
    parameters = {
        n: (v, math.sqrt(max(cov[i][i] * s2, 0.0)))
        for i, (n, v) in enumerate(zip(names, theta, strict=True))
    }
    return Fit(law, parameters, res, 1.0 - cost / total if total > 0 else 1.0, len(points), notes)
