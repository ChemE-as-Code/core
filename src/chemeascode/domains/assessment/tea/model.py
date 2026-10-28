"""The discounted cash flow of a plant: capital, operating cost, NPV, IRR, LCOP, break-even.

:class:`Premises` holds the deterministic values of an analysis (every cost in one currency and
cost year, real terms). What the plant buys and sells is a list of :class:`Line`: a quantity per
operating hour at a price per unit of it -- a feed or product of the flowsheet, a component of
one, a consumable or utility not in the flowsheet, an emission charge, an allowance credit, the
part of a flow in one operating case. A line's quantity is scaled by its own rate input and by
those it hangs on (``scales``: the flow a consumable is per, the share of a case), its price by
its own price input and by ``prices`` (one price driver for every case of a flow), and both by a
price ``profile`` over the operating years.

:func:`evaluate` computes the outcome for ``n`` samples at once: each input id may be scaled by a
multiplier or an array of ``n`` multipliers, so one function serves the baseline, the scenarios,
the tornado, the break-even search and the Monte Carlo.

The cash flow, per year ``t`` (0 is the first construction year):

- construction years: the fixed capital times the year's fraction of ``construction``;
- working capital (a fraction of the fixed capital, or days of the first full year's flows)
  spent in the last construction year and recovered in the last operating year, with the
  salvage value;
- operating years, at the year's load (``ramp_up``, then ``utilisation``, less the downtime of
  events): revenue (product lines) minus the cost lines, minus the fixed operating cost and the
  periodic events (replacements, turnarounds) expensed that year, minus income tax on that
  result less depreciation. A loss reduces the tax (``losses: credit``, offset against other
  income of the owner) or is carried forward to later profits (``carry_forward``). In the last
  year the book value left is written off and a salvage above it is taxed;
- discounted by ``(1 + discount rate) ** t``.

The levelised cost of the main product (LCOP) is the price of its line at which the NPV is zero,
every other product a credit: the NPV is linear in that price unless losses are carried
forward, so two evaluations give it, else a bracketed search. The IRR is found by bisection;
there is none when the cash flow does not change sign.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np

#: The columns of a cash-flow year.
CASHFLOW_COLUMNS = (
    "year",
    "phase",
    "capacity",
    "capital",
    "working_capital",
    "revenue",
    "variable_cost",
    "fixed_cost",
    "periodic",
    "depreciation",
    "tax",
    "cash_flow",
    "discounted",
    "cumulative",
)
#: Categories of the cost of production, in the order a reader expects them.
CATEGORIES = (
    "feed",
    "utility",
    "chemical",
    "catalyst",
    "disposal",
    "emission",
    "incentive",
    "byproduct",
    "other",
)


@dataclass(frozen=True)
class Line:
    """A priced quantity per operating hour (see the module docstring)."""

    key: str
    #: Quantity per operating hour, in ``unit``.
    rate: float
    #: Price per ``unit`` (a revenue for a product line, a cost otherwise; negative: the reverse).
    price: float
    revenue: bool
    unit: str = ""
    category: str = "other"
    #: Further rate input ids that multiply the quantity (parents, case shares).
    scales: tuple[str, ...] = ()
    #: Further price input ids that multiply the price.
    prices: tuple[str, ...] = ()
    #: Price multipliers by operating year (empty: 1; the last value holds after).
    profile: tuple[float, ...] = ()
    #: Scaled by ``operation:success_rate`` (saleable output of a batch plant).
    saleable: bool = False
    #: The rate and price input ids (default ``rate:<key>``, ``price:<key>``): lines that share
    #: a driver (a flow split into cases, every emission and the carbon price) share an id.
    rate_id: str = ""
    price_id: str = ""

    @property
    def rate_input(self) -> str:
        return self.rate_id or f"rate:{self.key}"

    @property
    def price_input(self) -> str:
        return self.price_id or f"price:{self.key}"


@dataclass(frozen=True)
class Event:
    """A cost (or a grant, negative) that recurs or happens once."""

    id: str
    #: Currency, or a fraction of the ISBL (``of_isbl``).
    amount: float
    of_isbl: bool = False
    every_years: float | None = None
    every_hours: float | None = None
    #: Operating year of the first occurrence (1 is the first; 0 and less: construction years).
    first: int = 1
    #: every_hours: the first occurrence is in year ``first`` (a given first_year), the next
    #: ones every ``every_hours`` of running after it; else the running hours count from
    #: start-up and the first occurrence is when they reach ``every_hours``.
    anchored: bool = False
    #: Days the plant stands still per occurrence.
    downtime_days: float = 0.0
    capital: bool = False
    #: No occurrence in the last operating year (a replacement nobody would make).
    skip_last: bool = True


@dataclass(frozen=True)
class Batch:
    """Batch operation: the flowsheet's quantities are per ``basis_hours`` of one batch."""

    cycle_time: float
    basis_hours: float
    trains: int = 1
    #: Given batches per year; else hours x trains / cycle time.
    batches_per_year: float | None = None
    success_rate: float = 1.0


@dataclass(frozen=True)
class WorkingCapitalDays:
    """Working capital from the first full year's flows, in days of each."""

    feed_inventory: float = 0.0
    product_inventory: float = 0.0
    receivables: float = 0.0
    payables: float = 0.0


@dataclass
class Premises:
    """The deterministic values of an analysis (see the module docstring for the units).

    ``rates`` and ``prices`` (by key) are the short form of ``lines`` for the flows of the
    flowsheet: a key with a price, and the main product, becomes a line."""

    isbl: float
    main: str
    hours: float
    life: int
    discount_rate: float
    lines: list[Line] = field(default_factory=list)
    rates: dict[str, float] = field(default_factory=dict)
    prices: dict[str, float] = field(default_factory=dict)
    osbl: float = 0.0
    owners_cost: float = 0.0
    contingency: float = 0.0
    ramp_up: list[float] = field(default_factory=list)
    utilisation: float | None = None
    batch: Batch | None = None
    maintenance: float = 0.0
    labour: float = 0.0
    insurance_tax: float = 0.0
    overheads: float = 0.0
    #: Fixed operating costs of their own, per year, by item id.
    items: dict[str, float] = field(default_factory=dict)
    #: Price profiles of the fixed items, by id.
    item_profiles: dict[str, tuple[float, ...]] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    tax_rate: float = 0.0
    losses: str = "credit"
    depreciation_years: int | None = None
    #: Fractions of the fixed capital depreciated in each operating year (instead of a span).
    depreciation: list[float] | None = None
    construction: list[float] = field(default_factory=lambda: [1.0])
    working_capital: float = 0.0
    working_capital_days: WorkingCapitalDays | None = None
    salvage: float = 0.0
    #: ``operation:throughput`` is an input (every rate moves together).
    throughput: bool = False

    def __post_init__(self) -> None:
        if not self.lines and self.rates:
            self.lines = [
                Line(
                    key,
                    rate,
                    self.prices.get(key, 0.0),
                    key.startswith("product:"),
                    saleable=key == self.main,
                )
                for key, rate in self.rates.items()
                if key in self.prices or key == self.main
            ]

    def line(self, key: str) -> Line | None:
        return next((x for x in self.lines if x.key == key), None)

    def inputs(self) -> list[str]:
        """The input ids that move the outcome, in a stable order."""
        found = [x.price_input for x in self.lines if x.price != 0 or x.key == self.main]
        found += [x.rate_input for x in self.lines]
        for x in self.lines:
            found += [s for s in (*x.scales, *x.prices) if s not in found]
        found.append("capex:isbl")
        found += [
            f"capex:{name}"
            for name in ("osbl", "owners_cost", "contingency")
            if getattr(self, name) > 0
        ]
        found += [
            f"opex:{name}"
            for name in ("maintenance", "labour", "insurance_tax", "overheads")
            if getattr(self, name) > 0
        ]
        found += [f"opex:{item}" for item in self.items]
        found += [f"event:{e.id}" for e in self.events]
        if self.batch is None:
            found.append("operation:hours_per_year")
        elif self.batch.batches_per_year is not None:
            found.append("operation:batches_per_year")
        else:
            found += ["operation:hours_per_year", "operation:cycle_time"]
        if self.batch is not None and self.batch.success_rate < 1:
            found.append("operation:success_rate")
        if self.utilisation is not None:
            found.append("operation:utilisation")
        if self.throughput:
            found.append("operation:throughput")
        found.append("finance:discount_rate")
        if self.working_capital_days is not None:
            found += [
                f"finance:wc:{name}"
                for name in ("feed_inventory", "product_inventory", "receivables", "payables")
                if getattr(self.working_capital_days, name) > 0
            ]
        seen: set[str] = set()
        return [x for x in found if not (x in seen or seen.add(x))]


@dataclass
class Outcome:
    """What :func:`evaluate` gives, one value per sample (arrays of length ``n``)."""

    isbl: np.ndarray
    osbl: np.ndarray
    owners_cost: np.ndarray
    contingency: np.ndarray
    fixed_capital: np.ndarray
    working_capital: np.ndarray
    #: The first operating year at full load (``utilisation``), without ramp-up.
    revenue: np.ndarray
    variable_cost: np.ndarray
    fixed_cost: np.ndarray
    #: The main product made per year at full load (in its line's unit).
    main_per_year: np.ndarray
    #: Operating hours per year (batch: batches x hours per batch).
    hours: np.ndarray
    npv: np.ndarray
    irr: np.ndarray
    #: Per unit of the main product's line (nan when it is not made).
    lcop: np.ndarray
    #: Cash cost per unit of the main product: variable and fixed cost less the other products.
    cash_cost: np.ndarray
    #: Per unit of the main product, first full year: by category, ``fixed``, and the events
    #: as an annuity (``events``).
    breakdown: dict[str, np.ndarray] = field(default_factory=dict)
    #: Per line, the first full year's amount (a cost or revenue, per year).
    amounts: dict[str, np.ndarray] = field(default_factory=dict)
    #: Per line, the first full year's quantity (in the line's unit, per year).
    quantities: dict[str, np.ndarray] = field(default_factory=dict)
    #: Year by year (shape n x years), by :data:`CASHFLOW_COLUMNS` name.
    flows: dict[str, np.ndarray] = field(default_factory=dict)
    construction_years: int = 1

    def metric(self, name: str) -> np.ndarray:
        return {
            "npv": self.npv,
            "irr": self.irr,
            "lcop": self.lcop,
            "cash_cost": self.cash_cost,
            "fixed_capital": self.fixed_capital,
        }[name]

    def payback(self) -> float | None:
        """Discounted payback of the first sample: years from start-up until the cumulative
        discounted cash flow is no longer negative (interpolated within the year); None when
        it never is."""
        cumulative = self.flows["cumulative"][0]
        discounted = self.flows["discounted"][0]
        start = self.construction_years
        for t in range(start, len(cumulative)):
            if cumulative[t] >= 0:
                before = cumulative[t] - discounted[t]
                within = -before / discounted[t] if discounted[t] > 0 else 0.0
                return float(t - start + min(max(within, 0.0), 1.0))
        return None

    def table(self) -> list[dict[str, Any]]:
        """The cash flow of the first sample, one dict per year."""
        rows = []
        for t in range(self.flows["cash_flow"].shape[1]):
            row: dict[str, Any] = {"year": t}
            row["phase"] = "construction" if t < self.construction_years else "operation"
            for name in CASHFLOW_COLUMNS[2:]:
                row[name] = float(self.flows[name][0, t])
            rows.append(row)
        return rows


def _profile(values: tuple[float, ...], life: int) -> np.ndarray:
    """Multipliers for each operating year: *values*, the last one holding after."""
    if not values:
        return np.ones(life)
    out = np.empty(life)
    k = min(len(values), life)
    out[:k] = values[:k]
    out[k:] = values[-1]
    return out


class _Scale:
    """The multiplier arrays of the input ids of one evaluation."""

    def __init__(self, scale: dict[str, Any] | None, n: int) -> None:
        self.scale = scale or {}
        self.n = n
        self.ones = np.ones(n)

    def __call__(self, name: str) -> np.ndarray:
        value = self.scale.get(name)
        if value is None:
            return self.ones
        return np.broadcast_to(np.asarray(value, dtype=float), (self.n,)).astype(float)

    def all(self, names: tuple[str, ...]) -> np.ndarray:
        out = self.ones
        for name in names:
            out = out * self(name)
        return out


def evaluate(
    p: Premises, scale: dict[str, Any] | None = None, n: int = 1, lcop: bool = True
) -> Outcome:
    """The outcome of *p* with each input id of *scale* multiplied (a number or ``n``
    multipliers); see the module docstring. *lcop* False skips the LCOP (nan): it takes more
    evaluations, a search when losses are carried forward."""
    m = _Scale(scale, n)
    main = p.line(p.main)
    cash, parts = _cash(p, m, n, None)
    price = (
        main.price * m(main.price_input) * m.all(main.prices) if main is not None else np.zeros(n)
    )
    want = lcop
    lcop = _lcop(p, m, n, cash["npv"], price) if main is not None and want else np.full(n, np.nan)
    per = parts["main_per_year"]
    with np.errstate(divide="ignore", invalid="ignore"):
        coproducts = parts["revenue"] - parts["main_revenue"]
        cash_cost = np.where(
            per > 0, (parts["variable"] + parts["fixed"] - coproducts) / per, np.nan
        )
        breakdown = {k: np.where(per > 0, v / per, np.nan) for k, v in parts["by"].items()}
        breakdown["fixed"] = np.where(per > 0, parts["fixed"] / per, np.nan)
        breakdown["events"] = np.where(per > 0, parts["events_annuity"] / per, np.nan)
    return Outcome(
        isbl=parts["isbl"],
        osbl=parts["osbl"],
        owners_cost=parts["owners"],
        contingency=parts["contingency"],
        fixed_capital=parts["fixed_capital"],
        working_capital=parts["working"],
        revenue=parts["revenue"],
        variable_cost=parts["variable"],
        fixed_cost=parts["fixed"],
        main_per_year=per,
        hours=parts["hours"],
        npv=cash["npv"],
        irr=irr(cash["flows"]["cash_flow"]),
        lcop=lcop,
        cash_cost=cash_cost,
        breakdown=breakdown,
        amounts=parts["amounts"],
        quantities=parts["quantities"],
        flows=cash["flows"],
        construction_years=len(p.construction),
    )


def _lcop(p: Premises, m: _Scale, n: int, npv: np.ndarray, price: np.ndarray) -> np.ndarray:
    """The main line's price at which the NPV is zero (per sample)."""
    step = np.maximum(np.abs(price), 1.0)
    npv_up = _cash(p, m, n, price + step)[0]["npv"]
    with np.errstate(divide="ignore", invalid="ignore"):
        slope = (npv_up - npv) / step
        guess = np.where(slope > 0, price - npv / slope, np.nan)
    if p.losses != "carry_forward" or p.tax_rate == 0:
        return guess
    # Carried-forward losses make the NPV piecewise linear in the price: bracket and bisect.
    low, high = guess.copy(), guess.copy()
    f_low = _cash(p, m, n, low)[0]["npv"]
    for _ in range(60):
        widen = np.isfinite(low) & (f_low > 0)
        if not widen.any():
            break
        low = np.where(widen, low - np.maximum(np.abs(low), 1.0), low)
        f_low = _cash(p, m, n, low)[0]["npv"]
    f_high = _cash(p, m, n, high)[0]["npv"]
    for _ in range(60):
        widen = np.isfinite(high) & (f_high < 0)
        if not widen.any():
            break
        high = np.where(widen, high + np.maximum(np.abs(high), 1.0), high)
        f_high = _cash(p, m, n, high)[0]["npv"]
    for _ in range(50):
        mid = (low + high) / 2.0
        f_mid = _cash(p, m, n, mid)[0]["npv"]
        below = f_mid < 0
        low = np.where(below, mid, low)
        high = np.where(below, high, mid)
    ok = np.isfinite(guess) & (slope > 0)
    return np.where(ok, (low + high) / 2.0, np.nan)


def _plant_hours(p: Premises, m: _Scale) -> np.ndarray:
    """The hours the plant runs per year (given batches: batches x cycle time / trains): what
    events count against and what a downtime takes from."""
    if p.batch is None or p.batch.batches_per_year is None:
        return p.hours * m("operation:hours_per_year")
    b = p.batch
    batches = b.batches_per_year * m("operation:batches_per_year")
    return batches * b.cycle_time * m("operation:cycle_time") / b.trains


def _hours(p: Premises, m: _Scale) -> np.ndarray:
    """Hours of flowsheet operation per year: given, or batches x hours of one batch."""
    if p.batch is None:
        return p.hours * m("operation:hours_per_year")
    b = p.batch
    if b.batches_per_year is not None:
        batches = b.batches_per_year * m("operation:batches_per_year")
    else:
        batches = p.hours * m("operation:hours_per_year") * b.trains
        batches = batches / (b.cycle_time * m("operation:cycle_time"))
    return batches * b.basis_hours


def _cash(
    p: Premises, m: _Scale, n: int, main_price: np.ndarray | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The cash flow and its parts; *main_price* replaces the main line's price."""
    isbl = p.isbl * m("capex:isbl")
    osbl = isbl * p.osbl * m("capex:osbl")
    owners = (isbl + osbl) * p.owners_cost * m("capex:owners_cost")
    contingency = (isbl + osbl + owners) * p.contingency * m("capex:contingency")
    fixed_capital = isbl + osbl + owners + contingency
    hours = _hours(p, m)

    c = len(p.construction)
    life = p.life
    total = c + life
    years = np.arange(total)
    full = p.utilisation * m("operation:utilisation") if p.utilisation is not None else m.ones
    # load: capacity fraction per sample and year
    load = np.zeros((n, total))
    load[:, c:] = full[:, None]
    for i, r in enumerate(p.ramp_up[:life]):
        load[:, c + i] = r
    events = _occurrences(p, m, n, _plant_hours(p, m), load, isbl)
    load = load * events["uptime"]

    throughput = m("operation:throughput")
    saleable = (
        p.batch.success_rate * m("operation:success_rate")
        if p.batch is not None and p.batch.success_rate < 1
        else m.ones
    )
    revenue = np.zeros((n, total))
    variable = np.zeros((n, total))
    first_revenue = np.zeros(n)
    first_variable = np.zeros(n)
    main_revenue = np.zeros(n)
    main_per_year = np.zeros(n)
    by = {k: np.zeros(n) for k in CATEGORIES}
    amounts: dict[str, np.ndarray] = {}
    quantities: dict[str, np.ndarray] = {}
    for line in p.lines:
        qty = line.rate * m(line.rate_input) * m.all(line.scales) * throughput * hours
        if line.saleable:
            qty = qty * saleable
        price = line.price * m(line.price_input) * m.all(line.prices)
        if line.key == p.main and main_price is not None:
            price = main_price
        profile = _profile(line.profile, life)
        first = qty * price * profile[0] * full
        amounts[line.key] = first
        quantities[line.key] = qty * full
        yearly = np.zeros((n, total))
        yearly[:, c:] = (qty * price)[:, None] * profile[None, :]
        yearly = yearly * load
        if line.revenue:
            revenue += yearly
            first_revenue += first
        else:
            variable += yearly
            first_variable += first
        if line.key == p.main:
            main_revenue = first
            main_per_year = qty * full
        else:
            sign = -1.0 if line.revenue else 1.0
            category = line.category if line.category in by else "other"
            by[category] = by[category] + sign * first

    labour = p.labour * m("opex:labour")
    maintenance = fixed_capital * p.maintenance * m("opex:maintenance")
    fixed_year = np.zeros((n, total))
    base_fixed = (
        maintenance
        + labour
        + fixed_capital * p.insurance_tax * m("opex:insurance_tax")
        + (labour + maintenance) * p.overheads * m("opex:overheads")
    )
    fixed_year[:, c:] = base_fixed[:, None]
    first_fixed = base_fixed.copy()
    for item, cost in p.items.items():
        profile = _profile(p.item_profiles.get(item, ()), life)
        amount = cost * m(f"opex:{item}")
        fixed_year[:, c:] += amount[:, None] * profile[None, :]
        first_fixed = first_fixed + amount * profile[0]

    if p.working_capital_days is not None:
        d = p.working_capital_days
        working = (
            first_variable * (d.feed_inventory * m("finance:wc:feed_inventory"))
            - first_variable * (d.payables * m("finance:wc:payables"))
            + (first_variable + first_fixed)
            * (d.product_inventory * m("finance:wc:product_inventory"))
            + first_revenue * (d.receivables * m("finance:wc:receivables"))
        ) / 365.0
    else:
        working = fixed_capital * p.working_capital

    capital = np.zeros((n, total))
    capital[:, :c] = fixed_capital[:, None] * np.asarray(p.construction)
    capital += events["capital"]
    wc = np.zeros((n, total))
    wc[:, c - 1] -= working
    wc[:, -1] += working

    depreciation = np.zeros((n, total))
    if p.depreciation is not None:
        shares = np.asarray(p.depreciation[:life])
        depreciation[:, c : c + len(shares)] = fixed_capital[:, None] * shares[None, :]
    else:
        span = p.depreciation_years or life
        depreciation[:, c : c + min(span, life)] = (fixed_capital / span)[:, None]
    depreciation += events["depreciation"]
    depreciable = fixed_capital + events["capital"].sum(axis=1)
    book = depreciable - depreciation.sum(axis=1)
    salvage = fixed_capital * p.salvage
    # the last year writes the book value off and takes the salvage
    depreciation[:, -1] += book

    periodic = events["expense"]
    taxable = revenue - variable - fixed_year - periodic - depreciation
    taxable[:, -1] += salvage
    if p.losses == "carry_forward" and p.tax_rate:
        tax = np.zeros((n, total))
        pool = np.zeros(n)
        for t in range(total):
            base = taxable[:, t] + pool
            tax[:, t] = np.where(base > 0, base * p.tax_rate, 0.0)
            pool = np.where(base > 0, 0.0, base)
    else:
        tax = taxable * p.tax_rate
    cash = revenue - variable - fixed_year - periodic - tax - capital + wc
    cash[:, -1] += salvage

    rate = p.discount_rate * m("finance:discount_rate")
    discount = (1.0 + rate)[:, None] ** (-years[None, :])
    discounted = cash * discount
    npv = discounted.sum(axis=1)
    annuity = (discount[:, c:]).sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        events_annuity = np.where(
            annuity > 0, ((periodic + events["capital"]) * discount).sum(axis=1) / annuity, 0.0
        )
    flows = {
        "capacity": load,
        "capital": capital,
        "working_capital": wc,
        "revenue": revenue,
        "variable_cost": variable,
        "fixed_cost": fixed_year,
        "periodic": periodic,
        "depreciation": depreciation,
        "tax": tax,
        "cash_flow": cash,
        "discounted": discounted,
        "cumulative": discounted.cumsum(axis=1),
    }
    parts = {
        "isbl": isbl,
        "osbl": osbl,
        "owners": owners,
        "contingency": contingency,
        "fixed_capital": fixed_capital,
        "working": working,
        "hours": hours,
        "revenue": first_revenue,
        "variable": first_variable,
        "fixed": first_fixed,
        "main_revenue": main_revenue,
        "main_per_year": main_per_year,
        "by": by,
        "amounts": amounts,
        "quantities": quantities,
        "events_annuity": events_annuity,
    }
    return {"npv": npv, "flows": flows}, parts


def _occurrences(
    p: Premises, m: _Scale, n: int, hours: np.ndarray, load: np.ndarray, isbl: np.ndarray
) -> dict[str, np.ndarray]:
    """The events by year: expensed and capital amounts, their depreciation, and the uptime
    (1 less the downtime) of the years they occur in."""
    c = len(p.construction)
    total = c + p.life
    expense = np.zeros((n, total))
    capital = np.zeros((n, total))
    depreciation = np.zeros((n, total))
    uptime = np.ones((n, total))
    full = load[:, c:].max(axis=1) if p.life else np.ones(n)
    for event in p.events:
        amount = event.amount * m(f"event:{event.id}")
        if event.of_isbl:
            amount = amount * isbl
        recurring = event.every_hours is not None or event.every_years is not None
        count = np.zeros((n, total))
        last = total - (1 if event.skip_last and recurring else 0)
        start = max(c - 1 + event.first, 0)
        if event.every_hours is not None and start < total:
            # running hours counted from the start of year `start`
            run = np.cumsum(hours[:, None] * load[:, start:], axis=1)
            done = np.floor(run / event.every_hours)
            count[:, start + 1 :] = done[:, 1:] - done[:, :-1]
            count[:, start] = done[:, 0] + (1.0 if event.anchored else 0.0)
        elif event.every_years is not None:
            t = float(start)
            while t < total:
                count[:, int(math.floor(t + 0.5))] += 1.0
                t += event.every_years
        elif start < total:
            count[:, start] = 1.0
        count[:, last:] = 0.0
        if event.downtime_days:
            # each occurrence in a year stands the plant still for downtime_days
            lost = np.minimum(event.downtime_days * 24.0 / np.maximum(hours, 1e-9), 1.0)
            uptime = uptime * np.clip(1.0 - count * lost[:, None], 0.0, 1.0)
        spent = count * amount[:, None]
        if event.capital:
            capital += spent
            if event.every_years is not None:
                span = np.full(n, float(event.every_years))
            elif event.every_hours is not None:
                span = event.every_hours / np.maximum(hours * full, 1e-9)
            else:
                span = None
            for t in range(total):
                if not spent[:, t].any():
                    continue
                # from start-up: nothing is depreciated during construction
                lo = min(max(t + 1, c), total - 1)
                for k in range(n):
                    if span is None:
                        years = total - lo
                    else:
                        years = max(min(math.ceil(span[k]), total - lo), 1)
                    depreciation[k, lo : lo + years] += spent[k, t] / years
        else:
            expense += spent
    return {
        "expense": expense,
        "capital": capital,
        "depreciation": depreciation,
        "uptime": uptime,
    }


def _present(cash: np.ndarray, rate: np.ndarray) -> np.ndarray:
    years = np.arange(cash.shape[1])
    return (cash * (1.0 + rate)[:, None] ** (-years[None, :])).sum(axis=1)


def irr(cash: np.ndarray, iterations: int = 100) -> np.ndarray:
    """The internal rate of return of each row of *cash* (bisection between -99 % and
    1000 %); nan where the NPV does not change sign in that range."""
    n = cash.shape[0]
    low = np.full(n, -0.99)
    high = np.full(n, 10.0)
    f_low = _present(cash, low)
    f_high = _present(cash, high)
    valid = np.sign(f_low) * np.sign(f_high) < 0
    for _ in range(iterations):
        mid = (low + high) / 2.0
        f_mid = _present(cash, mid)
        left = np.sign(f_mid) == np.sign(f_low)
        low = np.where(left, mid, low)
        f_low = np.where(left, f_mid, f_low)
        high = np.where(left, high, mid)
    return np.where(valid, (low + high) / 2.0, np.nan)


def with_prices(p: Premises, prices: dict[str, float]) -> Premises:
    """*p* with the price of the lines named in *prices* replaced (absolute, per unit)."""
    lines = [replace(x, price=prices[x.key]) if x.key in prices else x for x in p.lines]
    return replace(p, lines=lines, rates={}, prices={})


def break_even(
    p: Premises, name: str, metric: str, target: float, scale: dict[str, Any] | None = None
) -> float | None:
    """The multiplier of input *name* at which *metric* (npv, irr, lcop, cash_cost) equals
    *target*, the sign change nearest to 1 between 0.001 and 1000; None when there is none."""
    base = dict(scale or {})
    grid = np.concatenate([np.geomspace(1e-3, 1e3, 241), [1.0]])
    grid.sort()
    need = metric == "lcop"
    values = evaluate(p, {**base, name: grid}, len(grid), lcop=need).metric(metric) - target
    best: tuple[float, float, float] | None = None
    for i in range(len(grid) - 1):
        a, b = values[i], values[i + 1]
        if np.isnan(a) or np.isnan(b) or np.sign(a) == np.sign(b):
            continue
        distance = min(abs(np.log(grid[i])), abs(np.log(grid[i + 1])))
        if best is None or distance < best[0]:
            best = (distance, grid[i], grid[i + 1])
    if best is None:
        return None
    low, high = best[1], best[2]
    f_low = evaluate(p, {**base, name: low}, lcop=need).metric(metric)[0] - target
    for _ in range(45):
        mid = (low + high) / 2.0
        f_mid = evaluate(p, {**base, name: mid}, lcop=need).metric(metric)[0] - target
        if np.sign(f_mid) == np.sign(f_low):
            low, f_low = mid, f_mid
        else:
            high = mid
    return float((low + high) / 2.0)
