"""``estimate/tea.yaml`` (kind ``tea``): the premises of the plant's techno-economic analysis.

The file states what the analysis is for (``decision``), what is compared (``basis``: the
product and its specification, the battery limits, the scale, the location, the time basis
``cost_year``), how the capital cost is built up from the estimate (ISBL from the equipment
estimate, the take-off estimate or a given value, scaled to the plant's capacity and moved to its
location, then OSBL, owner's cost and contingency), the prices of the flowsheet's feeds and
products (whole flows, their components, or per energy content), what the plant buys besides
(``variable_opex``), its emissions and their price, the fixed operating cost, periodic events
(replacements, turnarounds, grants), how it runs (continuous or batch, cases with their share of
the time, utilisation), the financial premises and the uncertainty of each value. cheme-as-code
ships no prices: every number is the project's, with its ``status`` (ASSUMED or QUOTED),
``source`` and ``year``.

Every value a result can be traced to has an input id, used by the scenarios (``scale:``), the
Monte Carlo, the tornado and the break-even:

- ``price:<line>``, ``rate:<line>``: a line is a flow of the flowsheet (``feed:X``,
  ``product:Y``), a priced component (``product:Y@CO2``) or a variable item
  (``variable:<id>``); a flow's lines in each case (``feed:X~summer``) share its ``price:`` and
  ``rate:`` inputs; an emission (``emission:<id>``) and the free allowance
  (``allowance:carbon``) have a ``rate:`` input only: ``price:carbon`` is the price of every
  emission; ``conversion:<line>`` a price's conversion;
- ``capex:isbl``, ``capex:osbl``, ``capex:owners_cost``, ``capex:contingency``;
- ``opex:maintenance``, ``opex:labour``, ``opex:insurance_tax``, ``opex:overheads``,
  ``opex:<item id>``; ``event:<id>``;
- ``operation:hours_per_year`` (batch: ``operation:cycle_time`` or
  ``operation:batches_per_year``, ``operation:success_rate``), ``operation:utilisation``,
  ``operation:throughput`` (every rate at once);
- ``finance:discount_rate``, ``finance:wc:<days>``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, FiniteFloat, model_validator

from chemeascode.domains.assessment.lca.schemas import Uncertainty
from chemeascode.domains.assessment.schemas import RateStatus
from chemeascode.foundation.schema_base import Strict, unsupported_schema

SCHEMA = "cheme/tea/v1"

#: Units a price may be per, by quantity kind, with the factor to the unit the flowsheet's
#: rates are counted in (kg for material, kWh for energy). A unit of kind ``other`` (and a unit
#: of the other kind than the flow) needs a ``conversion``: units per kg or kWh of the flow.
PRICE_UNITS: dict[str, tuple[str, float | None]] = {
    "kg": ("material", 1.0),
    "t": ("material", 1000.0),
    "lb": ("material", 0.45359237),
    "st": ("material", 907.18474),
    "kWh": ("energy", 1.0),
    "MWh": ("energy", 1000.0),
    "MJ": ("energy", 1 / 3.6),
    "GJ": ("energy", 1000 / 3.6),
    "MMBtu": ("energy", 293.07107),
    "therm": ("energy", 29.307107),
    "Nm3": ("other", None),
    "m3": ("other", None),
    "L": ("other", None),
    "gal": ("other", None),
    "bbl": ("other", None),
    "kmol": ("other", None),
    "ea": ("other", None),
}
PriceUnit = Literal[
    "kg",
    "t",
    "lb",
    "st",
    "kWh",
    "MWh",
    "MJ",
    "GJ",
    "MMBtu",
    "therm",
    "Nm3",
    "m3",
    "L",
    "gal",
    "bbl",
    "kmol",
    "ea",
]
#: The unit the flowsheet's rates are counted in, by kind (per hour).
RATE_UNITS = {"material": "kg", "energy": "kWh"}
#: The AACE 18R-97 class a stage's estimate is expected to reach (overridable in the file).
CLASS_BY_STAGE = {"concept": 5, "basic": 4, "detail": 3}
EstimateClass = Literal[1, 2, 3, 4, 5]
#: Where a line's cost or revenue goes in the cost of production.
Category = Literal[
    "feed",
    "utility",
    "chemical",
    "catalyst",
    "disposal",
    "emission",
    "incentive",
    "byproduct",
    "other",
]
_ID = r"^[A-Za-z0-9_.\-]+$"
_KEY = r"^(feed|product):[A-Za-z0-9_.\-]+$"


class Swing(Strict):
    """Low and high multipliers of a value for the tornado (one at a time), e.g. 0.8 and 1.2."""

    low: FiniteFloat = Field(ge=0)
    high: FiniteFloat = Field(ge=0)
    source: str = ""

    @model_validator(mode="after")
    def _order(self) -> Swing:
        if not self.low <= 1 <= self.high:
            raise ValueError("a swing needs low <= 1 <= high")
        return self


class Value(Strict):
    """One premise: a number with its status, source and year, how uncertain it is (Monte
    Carlo) and how far the tornado swings it."""

    value: FiniteFloat
    status: RateStatus = Field(default="ASSUMED", description="ASSUMED, or QUOTED.")
    source: str = Field(min_length=3, description="Where the number comes from.")
    year: int | None = Field(default=None, ge=1900, le=2200, description="Its year.")
    uncertainty: Uncertainty | None = Field(
        default=None, description="Relative distribution (default: uncertainty.defaults)."
    )
    swing: Swing | None = Field(
        default=None, description="Tornado multipliers (default: P10 and P90, or sensitivity)."
    )
    notes: str = ""


class Fraction(Value):
    """A factor on another cost (OSBL on ISBL, maintenance on the fixed capital, ...)."""

    value: FiniteFloat = Field(ge=0)


class Share(Fraction):
    """A fraction of a whole: 0 to 1 (captured, free, successful)."""

    value: FiniteFloat = Field(ge=0, le=1)


class Positive(Value):
    """A value that must be above 0 (a cycle time, a count, a conversion factor)."""

    value: FiniteFloat = Field(gt=0)


class Path(Strict):
    """How a price moves over the operating years: a ``profile`` (multipliers by operating
    year, the last holding after) or a real ``escalation`` per year (compounding)."""

    profile: list[FiniteFloat] | None = Field(
        default=None, description="Multipliers by operating year, e.g. [1, 1.2, 1.5]."
    )
    escalation: FiniteFloat | None = Field(
        default=None, gt=-1, description="Real change per year, e.g. 0.02 for +2 %/a."
    )

    @model_validator(mode="after")
    def _one_path(self) -> Path:
        if self.profile is not None and self.escalation is not None:
            raise ValueError("give profile or escalation, not both")
        if self.profile is not None and not self.profile:
            raise ValueError("a profile needs at least one multiplier")
        return self


class Price(Path, Value):
    """The price of a feed or product of the flowsheet (or of one ``component`` of it), per
    ``unit``, in the file's currency and ``cost_year``. A product with a disposal cost has a
    negative price."""

    key: str = Field(pattern=_KEY, description="feed:<id> or product:<id> of the flowsheet.")
    unit: PriceUnit = Field(description="The price is per it.")
    component: str | None = Field(
        default=None,
        description="Price only this component of the flow (its mass, e.g. H2 in an off-gas).",
    )
    conversion: Positive | None = Field(
        default=None,
        description="Units of `unit` per kg (material flow) or kWh (energy flow) of what is "
        "priced: e.g. 0.0455 MMBtu/kg (LHV) for natural gas priced per MMBtu, 1.25 Nm3/kg.",
    )
    category: Category | None = Field(
        default=None, description="In the cost of production (default from the flow)."
    )


class Free(Strict):
    """A feed or product of the flowsheet without a price, and why (a vent, rejected heat)."""

    key: str = Field(pattern=_KEY)
    reason: str = Field(min_length=3)


class VariableItem(Path, Value):
    """A variable cost (or credit, negative) the flowsheet does not carry: a chemical, a
    catalyst consumed, a utility, a disposal, a fee, an incentive. ``value`` is the price per
    ``unit``; ``amount`` the quantity of ``unit`` per kg or kWh of the flow ``per`` (or of one
    ``component`` of it), per operating hour (``per: hour``) or per batch (``per: batch``)."""

    id: str = Field(pattern=_ID)
    title: str = ""
    per: str = Field(
        pattern=r"^((feed|product):[A-Za-z0-9_.\-]+|hour|batch)$",
        description="feed:<id>, product:<id>, hour or batch.",
    )
    component: str | None = Field(default=None, description="Per kg of this component of per.")
    amount: Value = Field(description="Quantity of unit per kg/kWh of per, per hour or per batch.")
    unit: str = Field(min_length=1, description="What the price is per, e.g. kg NaOH, m3, ea.")
    category: Category = "chemical"

    @model_validator(mode="after")
    def _component(self) -> VariableItem:
        if self.component is not None and self.per in ("hour", "batch"):
            raise ValueError(f"variable item {self.id}: a component needs per a flow")
        return self


class Scaling(Strict):
    """The capacity rule: ISBL = value x (capacity / reference) ** exponent, the capacity being
    the main product made per year at full load, in ``unit`` per year."""

    reference: Positive = Field(description="The capacity the ISBL value is for, per year.")
    unit: PriceUnit = Field(description="Unit of the capacity per year, e.g. t (t/a) or MWh.")
    exponent: Value = Field(description="e.g. 0.6 (the six-tenths rule).")


class Isbl(Strict):
    """The inside-battery-limits cost: where it comes from and what completes it.

    ``equipment``: the bare module cost of ``cheme assess equipment`` (with the project's own
    costs), ``mto``: the direct and indirect cost of ``cheme assess estimate``, ``given``:
    ``value`` (scaled by ``scaling`` to the plant's capacity). Never both estimates: the bare
    module cost already holds installation and indirects."""

    source: Literal["equipment", "mto", "given"]
    value: Value | None = Field(default=None, description="source given: the ISBL cost.")
    scaling: Scaling | None = Field(
        default=None, description="source given: from the value's reference capacity."
    )
    exchange_rate: Positive | None = Field(
        default=None,
        description="Units of the file's currency per unit of the estimate's (equipment: USD) "
        "or of the given value's (its currency differs), when they differ.",
    )
    escalation: Positive | None = Field(
        default=None,
        description="Multiplier from the estimate's (or the given value's) year to cost_year, "
        "e.g. a CEPCI ratio.",
    )
    location_factor: Positive | None = Field(
        default=None, description="From the estimate's location to the plant's, e.g. 1.1."
    )
    purchased_installation: Fraction | None = Field(
        default=None,
        description="source equipment: factor on the purchased cost of the items costed without "
        "a bare module factor (installed = factor x purchased); without it they count as 0.",
    )
    uncovered_allowance: Fraction | None = Field(
        default=None,
        description="Fraction of the costed ISBL added for what the estimate leaves uncosted: "
        "the items no correlation covers (source equipment), the take-off rows without a rate "
        "(source mto).",
    )
    uncertainty: Uncertainty | None = Field(default=None, description="Of the ISBL.")
    swing: Swing | None = None
    estimate_class: EstimateClass | None = Field(
        default=None,
        description="AACE 18R-97 class the capital cost claims (default: the equipment "
        "estimate's class in estimate/cost-basis.yaml, else 5).",
    )

    @model_validator(mode="after")
    def _given(self) -> Isbl:
        if (self.source == "given") != (self.value is not None):
            raise ValueError("give isbl.value exactly when isbl.source is given")
        if self.source != "equipment" and self.purchased_installation is not None:
            raise ValueError("purchased_installation applies to isbl.source equipment only")
        if self.source == "given" and self.uncovered_allowance is not None:
            raise ValueError("uncovered_allowance applies to isbl.source equipment or mto")
        if self.source != "given" and self.scaling is not None:
            raise ValueError("scaling applies to isbl.source given")
        return self


class Capex(Strict):
    """The capital cost: ISBL, then OSBL (x ISBL), owner's cost (x ISBL + OSBL) and contingency
    (x ISBL + OSBL + owner's cost); their sum is the fixed capital."""

    isbl: Isbl
    osbl: Fraction | None = Field(default=None, description="Offsites, utilities: x ISBL.")
    owners_cost: Fraction | None = Field(
        default=None, description="Land, project team, start-up, first fills: x (ISBL + OSBL)."
    )
    contingency: Fraction | None = Field(
        default=None, description="x (ISBL + OSBL + owner's cost)."
    )


class Labour(Strict):
    """Operating staff: headcount times the cost per person and year, plus supervision."""

    operators: Fraction = Field(description="Headcount over all shifts (positions x crews).")
    cost_per_operator: Fraction = Field(description="Cost per person and year.")
    supervision: Fraction | None = Field(default=None, description="x the operators' cost.")


class OpexItem(Path, Value):
    """A fixed operating cost of its own, per year (licence fee, laboratory, a role)."""

    id: str = Field(pattern=_ID)
    title: str = ""


class FixedOpex(Strict):
    """Operating costs that do not scale with the throughput, per year."""

    maintenance: Fraction | None = Field(default=None, description="x fixed capital.")
    labour: Labour | None = None
    insurance_tax: Fraction | None = Field(
        default=None, description="Insurance and local taxes: x fixed capital."
    )
    overheads: Fraction | None = Field(default=None, description="x (labour + maintenance).")
    items: list[OpexItem] = Field(default_factory=list)


class EmissionSource(Strict):
    """An emission the plant pays for: the CO2-equivalent of a flow (or of a component of it),
    less what is captured."""

    id: str = Field(pattern=_ID)
    key: str = Field(pattern=_KEY, description="The flow, e.g. product:FLUE or feed:FUEL.")
    component: str | None = Field(default=None, description="e.g. CO2 in the flue gas.")
    factor: Value = Field(description="t CO2-eq per `unit` of the flow (or component).")
    unit: PriceUnit = Field(default="t", description="What the factor is per (t, MWh, ...).")
    conversion: Positive | None = Field(
        default=None, description="Units of `unit` per kg or kWh, when its kind differs."
    )
    captured: Share | None = Field(default=None, description="Fraction captured, 0 to 1.")


class Allocation(Path, Strict):
    """Free allowances: ``benchmark`` t CO2-eq per `unit` of the product ``per``, ``fraction``
    of it free (a profile phases it out)."""

    benchmark: Value
    per: str = Field(pattern=r"^product:[A-Za-z0-9_.\-]+$")
    unit: PriceUnit = "t"
    conversion: Positive | None = Field(
        default=None, description="Units of `unit` per kg or kWh of the product, when needed."
    )
    fraction: Share


class Emissions(Strict):
    """The price of emissions (``price``, per t CO2-eq, with its path) and their sources."""

    price: Value
    profile: list[FiniteFloat] | None = None
    escalation: FiniteFloat | None = Field(default=None, gt=-1)
    sources: list[EmissionSource] = Field(min_length=1)
    allocation: Allocation | None = None

    @model_validator(mode="after")
    def _unique(self) -> Emissions:
        ids = [s.id for s in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError("an emission source id appears twice")
        if self.profile is not None and self.escalation is not None:
            raise ValueError("give profile or escalation, not both")
        return self


class Event(Strict):
    """A cost that recurs (catalyst, membrane or stack replacement, turnaround) or happens once
    (a grant: negative), as an amount or a fraction of the ISBL."""

    id: str = Field(pattern=_ID)
    title: str = ""
    kind: Literal["replacement", "turnaround", "sustaining", "one_off"] = "replacement"
    cost: Value | None = Field(default=None, description="Currency (negative: a grant).")
    fraction_of_isbl: Fraction | None = None
    every_years: FiniteFloat | None = Field(default=None, gt=0)
    every_hours: FiniteFloat | None = Field(
        default=None, gt=0, description="Operating hours between occurrences (e.g. a stack life)."
    )
    first_year: int | None = Field(
        default=None,
        description="Operating year of the first occurrence (1: the first; 0, -1: the last "
        "construction years). Default: every_years, else 1. With every_hours, the next ones "
        "follow every every_hours of running after it; without first_year, the running hours "
        "count from start-up.",
    )
    downtime_days: FiniteFloat | None = Field(
        default=None, ge=0, description="Days the plant stands still at each occurrence."
    )
    treatment: Literal["expense", "capital"] = Field(
        default="expense", description="capital: depreciated until the next occurrence."
    )
    skip_last: bool = Field(
        default=True,
        description="A recurring event does not occur in the last operating year (a replacement "
        "nobody would make); a one-off is never skipped.",
    )
    source: str = Field(min_length=3)

    @model_validator(mode="after")
    def _amount(self) -> Event:
        if (self.cost is None) == (self.fraction_of_isbl is None):
            raise ValueError(f"event {self.id}: give cost or fraction_of_isbl (one)")
        if self.every_years is not None and self.every_hours is not None:
            raise ValueError(f"event {self.id}: give every_years or every_hours, not both")
        return self


class Batch(Strict):
    """Batch operation: the flowsheet's rates are those of one batch over ``basis_hours``."""

    cycle_time: Positive = Field(description="Hours per batch, cleaning and turnaround included.")
    basis_hours: FiniteFloat = Field(
        gt=0, description="Hours over which the flowsheet's rates make one batch."
    )
    trains: int = Field(default=1, ge=1)
    batches_per_year: Positive | None = Field(
        default=None, description="Else hours_per_year x trains / cycle_time."
    )
    success_rate: Share | None = Field(
        default=None, description="Share of batches sold (products only)."
    )
    source: str = Field(min_length=3)


class Operation(Strict):
    """How the plant runs over its life."""

    hours_per_year: float = Field(gt=0, le=8784)
    life_years: int = Field(gt=0, le=100, description="Operating years in the cash flow.")
    ramp_up: list[FiniteFloat] = Field(
        default_factory=list,
        description="Capacity fraction of the first operating years (e.g. [0.6, 0.9]).",
    )
    utilisation: Fraction | None = Field(
        default=None, description="Load after the ramp-up (default 1), e.g. 0.85."
    )
    batch: Batch | None = None
    source: str = Field(min_length=3)
    uncertainty: Uncertainty | None = Field(default=None, description="Of the hours.")
    swing: Swing | None = None

    @model_validator(mode="after")
    def _ramp(self) -> Operation:
        if not all(0 <= r <= 1 for r in self.ramp_up):
            raise ValueError("ramp_up fractions are 0 to 1")
        if len(self.ramp_up) > self.life_years:
            raise ValueError("ramp_up is longer than life_years")
        if self.utilisation is not None and self.utilisation.value > 1:
            raise ValueError("utilisation is a fraction, at most 1")
        return self


class CaseShare(Strict):
    """A case of the flowsheet with its share of the operating hours (and prices of its own)."""

    case: str
    share: Fraction
    prices: dict[str, FiniteFloat] = Field(
        default_factory=dict, description="Key -> price in that case, in the baseline unit."
    )
    source: str = Field(min_length=3)


class WorkingCapitalDays(Strict):
    """Working capital in days of the first full year's flows."""

    feed_inventory: Value | None = Field(default=None, description="Days of variable cost.")
    product_inventory: Value | None = Field(
        default=None, description="Days of variable and fixed cost."
    )
    receivables: Value | None = Field(default=None, description="Days of revenue.")
    payables: Value | None = Field(default=None, description="Days of variable cost, less.")
    source: str = Field(min_length=3)


class Finance(Strict):
    """The financial premises of the discounted cash flow (real terms, the file's cost year)."""

    discount_rate: Fraction = Field(description="Real discount rate, e.g. 0.08.")
    tax_rate: Fraction | None = Field(
        default=None, description="Income tax on the operating result (none: pre-tax)."
    )
    losses: Literal["credit", "carry_forward"] = Field(
        default="credit",
        description="A year's tax loss: credited against the owner's other income, or carried "
        "forward to later profits.",
    )
    depreciation_years: int | None = Field(
        default=None, gt=0, description="Straight line, from start-up (default: the life)."
    )
    depreciation: list[FiniteFloat] | None = Field(
        default=None,
        description="Fractions of the fixed capital per operating year (a tax schedule such as "
        "MACRS); what is left is written off in the last year.",
    )
    construction: list[FiniteFloat] = Field(
        default_factory=lambda: [1.0],
        description="Fraction of the fixed capital spent in each construction year (sums to 1).",
    )
    working_capital: Fraction | None = Field(
        default=None, description="x fixed capital, spent at start-up, recovered at the end."
    )
    working_capital_days: WorkingCapitalDays | None = None
    salvage: Fraction | None = Field(
        default=None, description="x fixed capital, at the end (taxed above the book value)."
    )

    @model_validator(mode="after")
    def _schedule(self) -> Finance:
        if not self.construction or any(f < 0 for f in self.construction):
            raise ValueError("construction needs at least one non-negative fraction")
        if abs(sum(self.construction) - 1.0) > 1e-6:
            raise ValueError(f"construction fractions sum to {sum(self.construction):g}, not 1")
        if self.discount_rate.value >= 1:
            raise ValueError("discount_rate is a fraction (0.08 for 8 %)")
        if self.depreciation is not None:
            if self.depreciation_years is not None:
                raise ValueError("give depreciation or depreciation_years, not both")
            if any(f < 0 for f in self.depreciation) or sum(self.depreciation) > 1 + 1e-6:
                raise ValueError("depreciation fractions are non-negative and sum to at most 1")
        if self.working_capital is not None and self.working_capital_days is not None:
            raise ValueError("give working_capital or working_capital_days, not both")
        return self


class Decision(Strict):
    """The decision the analysis supports: the question, the metric it is taken on and the
    threshold the metric must meet (npv and irr at least, lcop and cash_cost at most)."""

    question: str = Field(min_length=10, description="e.g. Proceed to FEED with the ASU?")
    metric: Literal["npv", "irr", "lcop", "cash_cost"]
    threshold: FiniteFloat | None = Field(
        default=None,
        description="npv: in currency (default 0); irr: a fraction (default the discount rate); "
        "lcop and cash_cost: per the main product's unit (basis.unit, else its price's unit, "
        "else t or MWh) (required).",
    )
    confidence: FiniteFloat | None = Field(
        default=None,
        gt=0,
        lt=1,
        description="With uncertainty: the probability of meeting the threshold the decision "
        "needs (e.g. 0.9).",
    )
    alternatives: list[str] = Field(default_factory=list, description="What else is on the table.")

    @model_validator(mode="after")
    def _threshold(self) -> Decision:
        if self.metric in ("lcop", "cash_cost") and self.threshold is None:
            raise ValueError(f"a {self.metric} decision needs a threshold (the price to beat)")
        return self


class Basis(Strict):
    """What is evaluated: the premises two analyses must share to be compared."""

    product: str = Field(description="Main product id of process/flowsheet.yaml (its LCOP).")
    unit: PriceUnit | None = Field(
        default=None,
        description="The unit the LCOP and cash cost are per (default: the main product's "
        "price unit, else t for a material, MWh for an energy product).",
    )
    conversion: Positive | None = Field(
        default=None, description="Units of `unit` per kg or kWh of the product, when needed."
    )
    specification: str = Field(min_length=3, description="Purity, pressure, temperature, state.")
    boundary: str = Field(min_length=3, description="Battery limits: what is in and out.")
    scale: str = Field(default="", description="Capacity, e.g. 500 t/d O2.")
    location: str = Field(min_length=2, description="Site or region the prices are for.")


class TeaUncertainty(Strict):
    """Monte Carlo of the analysis: how often, from which seed (results are reproducible), and
    the uncertainty of every value that gives none of its own."""

    iterations: int = Field(default=2000, ge=10, le=100_000)
    seed: int = 1
    defaults: dict[Literal["ASSUMED", "QUOTED"], Uncertainty] = Field(
        default_factory=dict, description="Of the values without their own, by status."
    )
    rates: dict[Literal["given", "calculated", "assumed"], Uncertainty] = Field(
        default_factory=dict,
        description="rate_mode independent: of each flowsheet rate, by its provenance.",
    )
    rate_mode: Literal["independent", "throughput"] = Field(
        default="independent",
        description="throughput: every rate moves together (operation:throughput), so the mass "
        "balance holds in every sample.",
    )
    throughput: Uncertainty | None = Field(
        default=None, description="rate_mode throughput: of the throughput."
    )


class Sensitivity(Strict):
    """The tornado: each input at its low and high value, one at a time."""

    swing: Swing | None = Field(
        default=None, description="For the inputs with neither a swing nor an uncertainty."
    )
    top: int = Field(default=10, ge=1, description="How many inputs to show.")


class Scenario(Strict):
    """Another set of premises: prices replaced, values scaled."""

    id: str = Field(pattern=_ID)
    title: str = ""
    prices: dict[str, FiniteFloat] = Field(
        default_factory=dict, description="Line -> price, in the baseline price's unit."
    )
    scale: dict[str, FiniteFloat] = Field(
        default_factory=dict, description="Input id -> multiplier, e.g. {capex:isbl: 1.3}."
    )
    source: str = ""


class TeaFile(Strict):
    """``estimate/tea.yaml``: the premises of the techno-economic analysis."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["tea"]
    example: bool = Field(
        default=False,
        description="True marks example numbers that evaluate nothing: the report warns, and a "
        "gate requiring no-example fails, until the project replaces them.",
    )
    currency: str = Field(
        min_length=3, max_length=3, description="ISO 4217 code (XXX: no currency, an example)."
    )
    cost_year: int = Field(ge=1900, le=2200, description="The year every cost is in (real).")
    decision: Decision | None = None
    basis: Basis
    case: str | None = Field(default=None, description="Flowsheet case; default its default.")
    cases: list[CaseShare] | None = Field(
        default=None, description="Several cases, each with its share of the operating hours."
    )
    capex: Capex
    operation: Operation | None = Field(
        default=None, description="Default: operation of lca/lca.yaml (a finding says so)."
    )
    prices: list[Price] = Field(default_factory=list)
    free: list[Free] = Field(
        default_factory=list, description="Feeds and products that carry no price, with why."
    )
    variable_opex: list[VariableItem] = Field(default_factory=list)
    emissions: Emissions | None = None
    fixed_opex: FixedOpex = Field(default_factory=FixedOpex)
    events: list[Event] = Field(default_factory=list)
    finance: Finance
    class_by_stage: dict[str, EstimateClass] = Field(
        default_factory=lambda: dict(CLASS_BY_STAGE),
        description="The AACE class each stage of plant.yaml is expected to reach.",
    )
    uncertainty: TeaUncertainty | None = None
    sensitivity: Sensitivity | None = None
    scenarios: list[Scenario] = Field(default_factory=list)

    def costed_elsewhere(self) -> set[str]:
        """The products whose disposal or treatment cost is carried without a price: a
        ``variable_opex`` item of category disposal per them, or an emission source on them."""
        keys = {v.per for v in self.variable_opex if v.category == "disposal"}
        if self.emissions is not None:
            keys |= {s.key for s in self.emissions.sources}
        return {k for k in keys if k.startswith("product:")}

    @model_validator(mode="after")
    def _check(self) -> TeaFile:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        priced = [p.key + (f"@{p.component}" if p.component else "") for p in self.prices]
        for what, ids in (
            ("price or free flow", priced + [f.key for f in self.free]),
            (
                "opex item, variable item or event",
                [i.id for i in self.fixed_opex.items]
                + [i.id for i in self.variable_opex]
                + [e.id for e in self.events],
            ),
            ("scenario", [s.id for s in self.scenarios]),
        ):
            seen: set[str] = set()
            for item in ids:
                if item in seen:
                    raise ValueError(f"{what} {item} appears twice")
                seen.add(item)
        whole = {p.key for p in self.prices if p.component is None}
        if clash := whole & {p.key for p in self.prices if p.component is not None}:
            raise ValueError(f"{sorted(clash)[0]}: a whole-flow price and component prices")
        if "baseline" in {s.id for s in self.scenarios}:
            raise ValueError("scenario id baseline is reserved for the premises as given")
        if clash := {p.key for p in self.prices} & {f.key for f in self.free}:
            raise ValueError(f"{sorted(clash)[0]}: priced (or a component of it) and listed free")
        main = f"product:{self.basis.product}"
        if main in {f.key for f in self.free}:
            raise ValueError(f"{main} is the main product: it cannot be free")
        reserved = {"maintenance", "labour", "insurance_tax", "overheads"}
        if clash := reserved & {i.id for i in self.fixed_opex.items}:
            raise ValueError(f"opex item id {sorted(clash)[0]} is reserved")
        if self.cases is not None:
            if self.case is not None:
                raise ValueError("give case or cases, not both")
            names = [c.case for c in self.cases]
            if len(set(names)) != len(names) or not names:
                raise ValueError("cases need at least one case, each once")
            total = sum(c.share.value for c in self.cases)
            if abs(total - 1.0) > 1e-6:
                raise ValueError(f"the shares of cases sum to {total:g}, not 1")
        return self
