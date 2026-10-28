"""``cheme assess tea``: the techno-economic analysis of the plant.

:func:`tea_report` is the Python entry point: an explicit repository root in, a
:class:`TeaReport` out. It reads ``estimate/tea.yaml`` (the premises), ``plant.yaml`` (the
stage), the flowsheet's feed and product rates in its case or cases (:mod:`..flows`), the capital
estimate it builds on (``cheme assess equipment`` or ``cheme assess estimate``) and, for the
operation when the file gives none and for the emissions it maps, ``lca/lca.yaml``. It writes
nothing. :mod:`.build` does the work.

The report answers what the analysis was asked (``decision``), shows the capital cost build-up
and the estimate class against the stage, what the plant buys and sells, the cost of production
per unit of the main product, the periodic events, the cash flow and its NPV, IRR, LCOP, cash
cost and payback, the scenarios, the inputs that dominate (tornado, Monte Carlo ranks) and the
value of each input at which the decision would turn (break-even). :func:`compare` lists what
two analyses do not share before their results are compared.

:func:`tea_markdown`, :func:`cashflow_csv`, :func:`sensitivity_csv` and :func:`uncertainty_csv`
give the generated files under ``estimate/`` (:func:`outputs`).
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from chemeascode.domains.assessment.flows import BoundaryReport
from chemeascode.domains.assessment.tea.model import CASHFLOW_COLUMNS, CATEGORIES, Outcome, Premises
from chemeascode.domains.assessment.tea.schemas import TeaFile
from chemeascode.domains.assessment.tea.uncertainty import Bar, MonteCarlo
from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import (
    LAYOUT_MODEL_FILE,
    LIST_FILES,
    PLANT_FILE,
    NotAPlantRepository,
    Workspace,
)

TEA_FILE = LIST_FILES["tea"]
TEA_MD = "estimate/tea.md"
CASHFLOW_CSV = "estimate/tea-cashflow.csv"
SENSITIVITY_CSV = "estimate/tea-sensitivity.csv"
UNCERTAINTY_CSV = "estimate/tea-uncertainty.csv"
LCA_FILE = LIST_FILES["lca"]
#: How far the TEA's relative product prices may be from the LCA's allocation prices.
PRICE_RATIO_TOLERANCE = 0.05
BASELINE = "baseline"


def _g(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.6g}"


def _g4(value: float | None) -> str:
    """Four significant digits: a sample's statistics, stable across platforms."""
    return "" if value is None or not math.isfinite(value) else f"{value:.4g}"


def _money(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:,.0f}"


def _pct(value: float | None) -> str:
    return "" if value is None or not math.isfinite(value) else f"{value:.1%}"


@dataclass
class CapexLine:
    """One line of the capital cost build-up: ``value`` in ``currency`` (the estimate's, or the
    TEA's when empty), ``tea_value`` its contribution in the TEA's currency and cost year."""

    id: str
    title: str
    basis: str
    value: float
    status: str = ""
    source: str = ""
    year: int | None = None
    currency: str = ""
    tea_value: float = 0.0


@dataclass
class FlowLine:
    """A feed or product of the flowsheet: its rate, price and annual value at full load."""

    key: str
    title: str
    kind: str
    rate: float
    rate_unit: str
    provenance: str
    price: float | None = None
    price_unit: str = ""
    per_year: float | None = None
    status: str = ""
    source: str = ""
    year: int | None = None
    free: str = ""
    #: The priced component, when only it is priced.
    component: str = ""
    #: The rate in each case (several cases only).
    per_case: dict[str, float] = field(default_factory=dict)
    #: Every price of the flow (several when components are priced): component, price, unit.
    prices: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class OpexLine:
    id: str
    title: str
    basis: str
    per_year: float
    status: str = ""
    source: str = ""
    year: int | None = None


@dataclass
class Input:
    """An input id with its base value, as a reader knows it."""

    id: str
    value: float
    unit: str
    status: str = ""
    source: str = ""


@dataclass
class Turn:
    """The value of one input at which the decision turns (break-even)."""

    input: str
    base: float
    unit: str
    multiplier: float | None
    value: float | None


@dataclass
class ScenarioResult:
    id: str
    title: str
    source: str
    fixed_capital: float
    npv: float
    irr: float | None
    lcop: float | None
    meets: bool | None
    cash_cost: float | None = None


@dataclass
class TeaReport:
    """The TEA of the plant. ``loaded`` is False when an input does not load or an error
    prevents the evaluation."""

    CapexLine = CapexLine
    FlowLine = FlowLine
    OpexLine = OpexLine
    Input = Input
    Turn = Turn
    ScenarioResult = ScenarioResult

    root: Path
    tea: TeaFile | None = None
    stage: str = ""
    expected_class: int | None = None
    claimed_class: int = 5
    currency: str = ""
    cost_year: int | None = None
    example: bool = False
    #: The case, or the cases with their shares, as text; and as data.
    case: str = ""
    cases: list[dict[str, Any]] = field(default_factory=list)
    hours: float | None = None
    life: int | None = None
    batches: float | None = None
    operation_source: str = ""
    premises: Premises | None = None
    baseline: Outcome | None = None
    capex: list[CapexLine] = field(default_factory=list)
    #: Currency and year conversion of the estimate to the TEA's basis.
    isbl_conversion: float = 1.0
    flows: list[FlowLine] = field(default_factory=list)
    variable: list[dict[str, Any]] = field(default_factory=list)
    opex: list[OpexLine] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    events_total: float = 0.0
    inputs: dict[str, Input] = field(default_factory=dict)
    #: The LCOP's unit (per t, per MWh, ...) and the factor from per kg / kWh to it.
    lcop_unit: str = "t"
    lcop_factor: float = 1000.0
    lcop_unsubsidised: float | None = None
    #: The decision's metric and threshold, in the reported unit (npv by default).
    metric: str = "npv"
    threshold: float = 0.0
    scenarios: list[ScenarioResult] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    tornado: list[Bar] = field(default_factory=list)
    uncertainty: MonteCarlo | None = None
    #: What the flowsheet's declared boundary leaves out (:func:`..flows.boundary_gaps`): the
    #: operating cost counts only the terminals, so a step's utility in none is not in it.
    boundary: BoundaryReport | None = None
    findings: list[Finding] = field(default_factory=list)
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def loaded(self) -> bool:
        return self.baseline is not None and not any(f.level == "error" for f in self.findings)

    # -- results -------------------------------------------------------------------------------

    def value(self, metric: str) -> float | None:
        """The baseline's *metric* (npv, irr, fixed_capital, and lcop and cash_cost in the
        reported unit)."""
        if self.baseline is None:
            return None
        found = float(getattr(self.baseline, metric)[0])
        if metric in ("lcop", "cash_cost"):
            found *= self.lcop_factor
        return found if math.isfinite(found) else None

    def meets(self, metric: str | None = None, value: float | None = None) -> bool | None:
        """Whether the baseline (or *value*) meets the decision's threshold."""
        metric = metric or self.metric
        baseline = value is None
        value = self.value(metric) if value is None else value
        if self.tea is None or self.tea.decision is None:
            return None
        if value is None and baseline and metric == "irr" and self.baseline is not None:
            # no IRR: the cash flow never changes sign, so its NPV at the threshold rate has
            # the sign it has at every rate, and decides
            from chemeascode.domains.assessment.tea.model import _present

            cash = self.baseline.flows["cash_flow"][:1]
            return bool(_present(cash, np.array([self.threshold]))[0] >= 0)
        if value is None:
            return None
        if metric in ("lcop", "cash_cost"):
            return value <= self.threshold
        return value >= self.threshold

    @property
    def main_priced(self) -> bool:
        if self.premises is None:
            return False
        main = self.premises.line(self.premises.main)
        return main is not None and main.price != 0

    def results(self) -> dict[str, Any]:
        b = self.baseline
        if b is None:
            return {}
        return {
            "isbl": float(b.isbl[0]),
            "osbl": float(b.osbl[0]),
            "owners_cost": float(b.owners_cost[0]),
            "contingency": float(b.contingency[0]),
            "fixed_capital": float(b.fixed_capital[0]),
            "working_capital": float(b.working_capital[0]),
            "revenue_per_year": float(b.revenue[0]),
            "variable_cost_per_year": float(b.variable_cost[0]),
            "fixed_cost_per_year": float(b.fixed_cost[0]),
            "main_per_year": float(b.main_per_year[0]),
            "main_unit": self._main_rate_unit(),
            "operating_hours": float(b.hours[0]),
            "npv": self.value("npv"),
            "irr": self.value("irr"),
            "lcop": self.value("lcop"),
            "cash_cost": self.value("cash_cost"),
            "lcop_unit": f"{self.currency}/{self.lcop_unit}",
            "lcop_unsubsidised": self.lcop_unsubsidised,
            "payback_years": b.payback(),
            "meets": self.meets(),
            "main_priced": self.main_priced,
        }

    def _main_rate_unit(self) -> str:
        line = self.premises.line(self.premises.main) if self.premises else None
        return f"{line.unit}/a" if line is not None else ""

    def cost_of_production(self) -> list[dict[str, Any]]:
        """Per unit of the main product, first full year: each category of the lines, the
        fixed cost, the events as an annuity, then capital and tax (what the LCOP holds beyond
        the cash cost), summing to the LCOP."""
        b = self.baseline
        if b is None or not math.isfinite(float(b.lcop[0])):
            return []
        f = self.lcop_factor
        rows = []
        per_year = float(b.main_per_year[0])
        for name in (*CATEGORIES, "fixed", "events"):
            value = float(b.breakdown[name][0]) * f
            if value:
                rows.append({"category": name, "per_unit": value, "per_year": value / f * per_year})
        known = sum(row["per_unit"] for row in rows)
        rest = float(b.lcop[0]) * f - known
        rows.append(
            {"category": "capital_and_tax", "per_unit": rest, "per_year": rest / f * per_year}
        )
        return rows

    def capex_range(self) -> dict[str, Any]:
        """The AACE accuracy range of the claimed class applied to the fixed capital."""
        from chemeascode.domains.assessment.tea.build import AACE_BOUNDS

        total = self.value("fixed_capital") or 0.0
        (wide_low, narrow_low), (narrow_high, wide_high) = AACE_BOUNDS[self.claimed_class]
        return {
            "class": self.claimed_class,
            "low": [total * (1 + wide_low), total * (1 + narrow_low)],
            "high": [total * (1 + narrow_high), total * (1 + wide_high)],
        }

    def lines(self) -> list[dict[str, Any]]:
        """Every priced line with its first full year's amount (a cost or revenue)."""
        if self.premises is None or self.baseline is None:
            return []
        out = []
        for line in self.premises.lines:
            out.append(
                {
                    "key": line.key,
                    "category": "main" if line.key == self.premises.main else line.category,
                    "revenue": line.revenue,
                    "rate": line.rate,
                    "unit": line.unit,
                    "price": line.price,
                    "per_year": float(self.baseline.amounts[line.key][0]),
                    "profile": list(line.profile),
                }
            )
        return out

    def emissions(self) -> dict[str, Any] | None:
        """The emissions per year (t CO2-eq), their cost and its share per unit of product."""
        if self.premises is None or self.baseline is None:
            return None
        lines = [x for x in self.premises.lines if x.price_input == "price:carbon"]
        if not lines:
            return None
        q = self.baseline.quantities
        emitted = sum(float(q[x.key][0]) for x in lines if x.key.startswith("emission:"))
        free = -sum(float(q[x.key][0]) for x in lines if x.key.startswith("allowance:"))
        cost = sum(float(self.baseline.amounts[x.key][0]) for x in lines)
        per = float(self.baseline.main_per_year[0])
        return {
            "t_per_year": emitted,
            "free_t_per_year": free,
            "cost_per_year": cost,
            "per_unit": cost / per * self.lcop_factor if per else None,
        }

    def premises_of_basis(self) -> dict[str, str]:
        """What another analysis must share with this one to be compared with it."""
        tea = self.tea
        if tea is None:
            return {}
        return {
            "product": tea.basis.product,
            "specification": tea.basis.specification,
            "boundary": tea.basis.boundary,
            "scale": tea.basis.scale,
            "location": tea.basis.location,
            "currency": tea.currency,
            "cost_year": str(tea.cost_year),
            "case": self.case,
            "operation": self._operation_text(),
            "discount_rate": _g(tea.finance.discount_rate.value),
            "tax_rate": _g(tea.finance.tax_rate.value if tea.finance.tax_rate else 0.0),
        }

    def _operation_text(self) -> str:
        tea = self.tea
        op = tea.operation if tea else None
        text = f"{_g(self.hours)} h/a, {self.life} a"
        if self.batches is not None:
            text += f", {self.batches:.4g} batches/a"
        if op is not None:
            if op.utilisation is not None:
                text += f", utilisation {op.utilisation.value:g}"
            if op.ramp_up:
                text += f", ramp-up {', '.join(f'{x:g}' for x in op.ramp_up)}"
            if op.batch is not None and op.batch.success_rate is not None:
                text += f", success rate {op.batch.success_rate.value:g}"
        return text

    def operation(self) -> dict[str, Any]:
        tea = self.tea
        op = tea.operation if tea else None
        return {
            "hours_per_year": self.hours,
            "life_years": self.life,
            "ramp_up": list(op.ramp_up) if op else [],
            "utilisation": op.utilisation.value if op and op.utilisation else None,
            "batches_per_year": self.batches,
            "cycle_time": op.batch.cycle_time.value if op and op.batch else None,
            "operating_hours": float(self.baseline.hours[0]) if self.baseline else None,
            "cases": self.cases,
        }

    def payload(self) -> dict[str, Any]:
        """The document ``--json`` prints; a number that does not exist (no IRR) is None."""
        return _finite(self._payload())

    def _payload(self) -> dict[str, Any]:
        tea = self.tea
        return {
            "currency": self.currency,
            "cost_year": self.cost_year,
            "example": self.example,
            "stage": self.stage,
            "estimate_class": self.claimed_class,
            "expected_class": self.expected_class,
            "decision": tea.decision.model_dump(mode="json") if tea and tea.decision else None,
            "metric": self.metric,
            "threshold": self.threshold,
            "basis": self.premises_of_basis(),
            "operation": self.operation() if tea else None,
            "capex": [asdict(line) for line in self.capex],
            "capex_range": self.capex_range() if self.baseline is not None else None,
            "flows": [asdict(line) for line in self.flows],
            "lines": self.lines(),
            "variable": list(self.variable),
            "emissions": self.emissions(),
            "opex": [asdict(line) for line in self.opex],
            "events": list(self.events),
            "results": self.results(),
            "cost_of_production": self.cost_of_production(),
            "cashflow": self.baseline.table() if self.baseline is not None else [],
            "scenarios": [asdict(s) for s in self.scenarios],
            "inputs": [asdict(i) for i in self.inputs.values()],
            "break_even": [asdict(t) for t in self.turns],
            "tornado": [{**asdict(bar), "width": bar.width} for bar in self.tornado],
            "uncertainty": asdict(self.uncertainty) if self.uncertainty is not None else None,
            "boundary": self.boundary_entry(),
        }

    def unclassified_products(self) -> tuple[list[str], list[str]]:
        """The products without a category: (those the TEA counts at no cost, having no price,
        no free entry, no disposal item or emission source and not being the main product; those
        it prices, costs that way or lists free as given)."""
        if self.boundary is None or self.tea is None:
            return [], []
        tea = self.tea
        costed = {p.key for p in tea.prices} | {f.key for f in tea.free} | tea.costed_elsewhere()
        costed.add(f"product:{tea.basis.product}")
        ids = [
            f.ids[0]
            for f in self.boundary.findings
            if f.rule == "cheme.boundary-unclassified" and f.level == "warning" and f.ids
        ]
        return (
            [i for i in ids if f"product:{i}" not in costed],
            [i for i in ids if f"product:{i}" in costed],
        )

    def boundary_entry(self) -> dict[str, Any] | None:
        """What the boundary check (:func:`..flows.boundary_gaps`) found: ``complete`` is
        True when *its rules* warn of no gap (``checked``; ``noted`` are info only), not that
        the inventory is complete (``not_checked``); the gaps by rule (the findings
        ``cheme.boundary-*``, also in :attr:`findings`); ``excluded_products``, the products
        without a category that the operating cost counts at no cost (no price, not free)."""
        if self.boundary is None:
            return None
        return {**self.boundary.payload(), "excluded_products": self.unclassified_products()[0]}

    def to_json(self) -> str:
        return json.dumps(
            {
                **self.payload(),
                "findings": [{**asdict(f), "id": f.id} for f in self.findings],
                "source": self.source.as_dict(),
            },
            indent=2,
        )


# -- loading -------------------------------------------------------------------------------------


#: The files a TEA report is computed from besides the datasheets, relative to the root.
REPORT_INPUTS = (
    PLANT_FILE,
    TEA_FILE,
    MATERIALS_FILE,
    FLOWSHEET_FILE,
    "process/catalysts.yaml",
    "process/simulation.yaml",
    "process/reactions.yaml",
    LCA_FILE,
    LIST_FILES["equipment"],
    LIST_FILES["cost_basis"],
    LIST_FILES["rates"],
    LAYOUT_MODEL_FILE,
)


def report_inputs(root: Path) -> list[str]:
    """The files a TEA report is computed from, relative to *root*: :data:`REPORT_INPUTS` and
    the equipment datasheets."""
    from chemeascode.domains.equipment.datasheets import datasheet_paths

    workspace = Workspace(Path(root))
    return [*REPORT_INPUTS, *(workspace.relative(p) for p in datasheet_paths(workspace))]


def tea_report(root: Path) -> TeaReport:
    """The TEA of the plant repository at *root*, independent of the working directory.

    Raises :class:`NotAPlantRepository` when *root* holds no ``plant.yaml``. Inputs that do not
    load are findings, and ``loaded`` is then False."""
    from chemeascode.domains.assessment.tea.build import Builder

    root = Path(root)
    if not (root / PLANT_FILE).is_file():
        raise NotAPlantRepository(f"No {PLANT_FILE} in {root}.")
    report = TeaReport(root, source=source_revision(root, report_inputs(root)))
    Builder(report, TEA_FILE).run()
    return report


# -- comparison ----------------------------------------------------------------------------------


@dataclass
class Comparison:
    """Two analyses side by side: what they do not share, then how their results differ."""

    #: (premise, this, other) where they differ.
    differences: list[tuple[str, str, str]] = field(default_factory=list)
    #: (result, this, other).
    results: list[tuple[str, float | None, float | None]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        return not self.differences


def compare(this: TeaReport, other: TeaReport, label: str = "the other revision") -> Comparison:
    """What *this* and *other* do not share (product, specification, boundary, scale, location,
    currency and cost year, case, operation, discount and tax rate), and their results."""
    found = Comparison()
    mine, theirs = this.premises_of_basis(), other.premises_of_basis()
    for key in mine:
        if mine.get(key) != theirs.get(key):
            found.differences.append((key, mine.get(key, ""), theirs.get(key, "")))
    for key in ("fixed_capital", "npv", "irr", "lcop", "cash_cost"):
        found.results.append((key, this.value(key), other.value(key)))
    if this.lcop_unit != other.lcop_unit:
        found.differences.append(("lcop unit", this.lcop_unit, other.lcop_unit))
    if found.differences:
        names = ", ".join(d[0] for d in found.differences)
        found.findings.append(
            Finding(
                TEA_FILE,
                "warning",
                "cheme.tea-not-comparable",
                f"the analyses differ in {names} from {label}: their results do not compare "
                "like for like",
                hint="align the basis (same product specification, boundary, scale, location "
                "and time basis) before reading the difference as the design's",
                key=names,
            )
        )
    return found


def comparison_markdown(found: Comparison, this: str, other: str) -> str:
    lines = [f"# TEA: {this} against {other}", ""]
    if found.differences:
        lines += ["**Not comparable like for like:** the premises differ.", ""]
        lines += [f"| premise | {this} | {other} |", "|---|---|---|"]
        lines += [f"| {k} | {a} | {b} |" for k, a, b in found.differences]
    else:
        lines.append("Same basis: product, specification, boundary, scale, location, time basis.")
    lines += ["", f"| result | {this} | {other} | difference |", "|---|---|---|---|"]
    for key, a, b in found.results:
        delta = a - b if a is not None and b is not None else None
        lines.append(f"| {key} | {_g(a)} | {_g(b)} | {_g(delta)} |")
    return "\n".join(lines) + "\n"


# -- formats -------------------------------------------------------------------------------------


def cashflow_csv(report: TeaReport) -> str:
    """The baseline's cash flow, one row per year (``estimate/tea-cashflow.csv``)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(CASHFLOW_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for row in report.baseline.table() if report.baseline is not None else []:
        writer.writerow({k: v if k in ("year", "phase") else _g(v) for k, v in row.items()})
    return buffer.getvalue()


SENSITIVITY_COLUMNS = (
    "input",
    "base",
    "unit",
    "low",
    "high",
    "basis",
    "metric",
    "at_low",
    "at_high",
    "break_even_multiplier",
    "break_even_value",
)


def sensitivity_csv(report: TeaReport) -> str:
    """The tornado and the break-even value of every input (``estimate/tea-sensitivity.csv``)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(SENSITIVITY_COLUMNS), lineterminator="\n")
    writer.writeheader()
    bars = {bar.input: bar for bar in report.tornado}
    for turn in report.turns:
        bar = bars.get(turn.input)
        writer.writerow(
            {
                "input": turn.input,
                "base": _g(turn.base),
                "unit": turn.unit,
                "low": _g(bar.low) if bar else "",
                "high": _g(bar.high) if bar else "",
                "basis": bar.basis if bar else "",
                "metric": report.metric,
                "at_low": _g(bar.at_low) if bar else "",
                "at_high": _g(bar.at_high) if bar else "",
                "break_even_multiplier": _g4(turn.multiplier),
                "break_even_value": _g4(turn.value),
            }
        )
    return buffer.getvalue()


UNCERTAINTY_COLUMNS = (
    "metric",
    "unit",
    "deterministic",
    "mean",
    "p10",
    "p50",
    "p90",
    "valid",
    "iterations",
    "seed",
)


def uncertainty_csv(report: TeaReport) -> str:
    """The Monte Carlo statistics per metric (``estimate/tea-uncertainty.csv``; empty without)."""
    mc = report.uncertainty
    if mc is None:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(UNCERTAINTY_COLUMNS), lineterminator="\n")
    writer.writeheader()
    for s in mc.statistics:
        writer.writerow(
            {
                "metric": s.metric,
                "unit": s.unit,
                "deterministic": _g4(s.deterministic),
                "mean": _g4(s.mean),
                "p10": _g4(s.p10),
                "p50": _g4(s.p50),
                "p90": _g4(s.p90),
                "valid": s.valid,
                "iterations": mc.iterations,
                "seed": mc.seed,
            }
        )
    return buffer.getvalue()


def _metric_text(report: TeaReport, metric: str, value: float | None) -> str:
    if value is None:
        return "none"
    if metric == "irr":
        return _pct(value)
    if metric in ("lcop", "cash_cost"):
        return f"{_g4(value)} {report.currency}/{report.lcop_unit}"
    return f"{_money(value)} {report.currency}"


def outputs(report: TeaReport) -> dict[str, str]:
    """The files ``cheme assess tea --write`` writes, by path (the uncertainty only with a
    Monte Carlo)."""
    found = {
        TEA_MD: tea_markdown(report),
        CASHFLOW_CSV: cashflow_csv(report),
        SENSITIVITY_CSV: sensitivity_csv(report),
    }
    if report.uncertainty is not None:
        found[UNCERTAINTY_CSV] = uncertainty_csv(report)
    return found


def _base(report: TeaReport, value: float, unit: str, short: bool = False) -> str:
    """An input's value with its unit, money as money (*short*: four significant digits)."""
    if unit == report.currency or unit == f"{report.currency}/a":
        return f"{_money(value)} {unit}"
    return f"{_g4(value) if short else _g(value)} {unit}"


_CRITERION = {"lcop": "at most", "cash_cost": "at most", "npv": "at least", "irr": "at least"}
_TITLES = {
    "feed": "feeds",
    "utility": "utilities",
    "chemical": "chemicals",
    "catalyst": "catalysts",
    "disposal": "disposal",
    "emission": "emissions",
    "incentive": "incentives",
    "byproduct": "co-product credits",
    "other": "other variable",
    "fixed": "fixed operating cost",
    "events": "periodic events (annuity)",
    "capital_and_tax": "capital and tax",
}


def tea_markdown(report: TeaReport) -> str:
    """The report as ``estimate/tea.md``."""
    tea = report.tea
    if tea is None or report.baseline is None:
        return ""
    cur = report.currency
    res = report.results()
    lines = [
        f"# Techno-economic analysis: {tea.basis.product} ({cur} {tea.cost_year}, real)",
        "",
        "Generated by `cheme assess tea --write` from estimate/tea.yaml and its inputs; do not "
        "edit.",
    ]
    if report.example:
        lines += ["", "**Example premises (example: true): these numbers evaluate nothing.**"]
    if report.boundary is not None and not report.boundary.complete:
        lines += [
            "",
            "**Incomplete boundary: the boundary check found gaps; the operating cost counts "
            "only the flowsheet's terminals (see the section Boundary).**",
        ]
    lines += ["", "## Decision", ""]
    if tea.decision is None:
        lines.append("No decision stated: the results below answer no question yet.")
    else:
        d = tea.decision
        verdict = {True: "meets it", False: "does not meet it", None: "cannot tell"}[report.meets()]
        lines += [
            f"- question: {d.question}",
            f"- criterion: {d.metric} {_CRITERION[d.metric]} "
            f"{_metric_text(report, d.metric, report.threshold)}",
            f"- baseline: {_metric_text(report, d.metric, report.value(d.metric))}, {verdict}",
        ]
        if report.uncertainty is not None and report.uncertainty.probability is not None:
            needed = f" (the decision asks for {d.confidence:.0%})" if d.confidence else ""
            lines.append(
                f"- probability of meeting it: {report.uncertainty.probability:.0%}{needed}"
            )
        if d.alternatives:
            lines.append(f"- alternatives: {'; '.join(d.alternatives)}")
    lines += ["", "## Basis", "", "| premise | value |", "|---|---|"]
    for key, value in report.premises_of_basis().items():
        lines.append(f"| {key} | {value} |")
    rng = report.capex_range()
    lines += [
        "",
        f"## Capital cost (AACE class {report.claimed_class}; stage {report.stage or '-'} "
        f"expects class {report.expected_class or '-'})",
        "",
        f"| item | basis | cost | in {cur} {tea.cost_year} | status | source | year |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in report.capex:
        cost = f"{_money(c.value)} {c.currency}".strip() if c.value else ""
        lines.append(
            f"| {c.title} | {c.basis} | {cost} | {_money(c.tea_value) if c.tea_value else ''} | "
            f"{c.status} | {c.source} | {c.year or ''} |"
        )
    lines += [
        f"| **ISBL** | | | **{_money(res['isbl'])}** | | | |",
        f"| **Fixed capital** | | | **{_money(res['fixed_capital'])}** | | | |",
        f"| Working capital | | | {_money(res['working_capital'])} | | | |",
        "",
        f"Class {rng['class']} accuracy: {_money(rng['low'][0])} to {_money(rng['low'][1])} "
        f"(low end), {_money(rng['high'][0])} to {_money(rng['high'][1])} (high end) {cur}.",
        "",
        "## Revenue and variable cost (per year at full load)",
        "",
        "| line | rate | provenance | price | net per year | status | source | year |",
        "|---|---|---|---|---|---|---|---|",
    ]
    amounts = {x["key"]: x for x in report.lines()}
    for f in report.flows:
        if f.free:
            price = f"free: {f.free}"
        elif f.price is None:
            price = "**no price**" if f.rate > 0 and f.key != report.premises.main else ""
        else:
            price = "; ".join(
                f"{_g(x['price'])} {cur}/{x['unit']}"
                + (f" ({x['component']})" if x["component"] else "")
                for x in f.prices
            )
        per_year = f.per_year
        lines.append(
            f"| {f.key} | {_g(f.rate)} {f.rate_unit} | {f.provenance} | {price} | "
            f"{_money(per_year)} | {f.status} | {f.source} | {f.year or ''} |"
        )
    for v in report.variable:
        key = f"variable:{v['id']}"
        per = v["per"] + (f" ({v['component']})" if v["component"] else "")
        lines.append(
            f"| {key} ({v['category']}) | {_g(v['amount'])} {v['unit']} per {per} | | "
            f"{_g(v['price'])} {cur}/{v['unit']} | {_money(_net(amounts[key]))} | "
            f"{v['status']} | {v['source']} | {v['year'] or ''} |"
        )
    em = report.emissions()
    if em is not None:
        lines += [
            "",
            f"Emissions: {_g4(em['t_per_year'])} t CO2-eq/a"
            + (f", {_g4(em['free_t_per_year'])} t free" if em["free_t_per_year"] else "")
            + f"; their cost {_money(em['cost_per_year'])} {cur}/a, "
            f"{_g4(em['per_unit'])} {cur}/{report.lcop_unit} of product.",
        ]
    lines += _boundary_lines(report)
    lines += [
        "",
        "## Fixed operating cost (per year)",
        "",
        "| item | basis | per year | status | source | year |",
        "|---|---|---|---|---|---|",
    ]
    for o in report.opex:
        lines.append(
            f"| {o.title} | {o.basis} | {_money(o.per_year)} | {o.status} | {o.source} | "
            f"{o.year or ''} |"
        )
    if report.events:
        lines += [
            "",
            "## Periodic events",
            "",
            "| event | kind | amount | every | first year | treatment | source |",
            "|---|---|---|---|---|---|---|",
        ]
        for e in report.events:
            every = (
                f"{e['every_years']:g} a"
                if e["every_years"]
                else f"{e['every_hours']:g} h"
                if e["every_hours"]
                else "once"
            )
            lines.append(
                f"| {e['title']} | {e['kind']} | {_money(e['amount'])} {cur} | {every} | "
                f"{e['first_year']} | {e['treatment']} | {e['source']} |"
            )
    cop = report.cost_of_production()
    if cop:
        lines += [
            "",
            f"## Cost of production ({cur}/{report.lcop_unit} of {tea.basis.product}, first "
            "full year)",
            "",
            f"| part | {cur}/{report.lcop_unit} | {cur}/a |",
            "|---|---|---|",
        ]
        for row in cop:
            lines.append(
                f"| {_TITLES.get(row['category'], row['category'])} | {_g4(row['per_unit'])} | "
                f"{_money(row['per_year'])} |"
            )
        lines.append(f"| **LCOP** | **{_g4(res['lcop'])}** | |")
    payback = res["payback_years"]
    unpriced = (
        f" (without revenue from {tea.basis.product}: it has no price)"
        if not report.main_priced
        else ""
    )
    lines += [
        "",
        "## Results (baseline)",
        "",
        "| result | value |",
        "|---|---|",
        f"| revenue per year | {_money(res['revenue_per_year'])} {cur} |",
        f"| variable cost per year | {_money(res['variable_cost_per_year'])} {cur} |",
        f"| fixed cost per year | {_money(res['fixed_cost_per_year'])} {cur} |",
        f"| NPV | {_metric_text(report, 'npv', res['npv'])}{unpriced} |",
        f"| IRR | {_metric_text(report, 'irr', res['irr'])}{unpriced} |",
        f"| LCOP of {tea.basis.product} | {_metric_text(report, 'lcop', res['lcop'])} |",
        f"| cash cost of {tea.basis.product} | "
        f"{_metric_text(report, 'cash_cost', res['cash_cost'])} |",
    ]
    if res["lcop_unsubsidised"] is not None:
        lines.append(
            f"| LCOP without incentives | "
            f"{_metric_text(report, 'lcop', res['lcop_unsubsidised'])} |"
        )
    lines += [
        f"| discounted payback | {'never' if payback is None else f'{payback:.1f} years'} |",
        "",
        f"Cash flow by year: {CASHFLOW_CSV}.",
    ]
    if report.scenarios:
        lines += [
            "",
            "## Scenarios",
            "",
            "| scenario | fixed capital | NPV | IRR | LCOP | meets |",
            "|---|---|---|---|---|---|",
            f"| baseline | {_money(res['fixed_capital'])} | {_money(res['npv'])} | "
            f"{_pct(res['irr'])} | {_g4(res['lcop'])} | {_yes(report.meets())} |",
        ]
        for s in report.scenarios:
            lines.append(
                f"| {s.id}{f' ({s.title})' if s.title else ''} | {_money(s.fixed_capital)} | "
                f"{_money(s.npv)} | {_pct(s.irr)} | {_g4(s.lcop)} | {_yes(s.meets)} |"
            )
    if report.tornado:
        lines += [
            "",
            f"## What dominates the outcome ({report.metric}, one input at a time)",
            "",
            "| input | base | low .. high | at low | at high | swing from |",
            "|---|---|---|---|---|---|",
        ]
        for bar in report.tornado:
            base = report.inputs.get(bar.input)
            shown = _base(report, base.value, base.unit) if base else ""
            lines.append(
                f"| {bar.input} | {shown} | x {_g4(bar.low)} .. "
                f"x {_g4(bar.high)} | {_metric_text(report, report.metric, _finite(bar.at_low))} "
                f"| {_metric_text(report, report.metric, _finite(bar.at_high))} | {bar.basis} |"
            )
    mc = report.uncertainty
    if mc is not None:
        lines += [
            "",
            f"## Uncertainty (Monte Carlo, {mc.iterations} iterations, seed {mc.seed})",
            "",
            "| metric | deterministic | P10 | P50 | P90 | mean |",
            "|---|---|---|---|---|---|",
        ]
        for s in mc.statistics:
            lines.append(
                f"| {s.metric} ({s.unit}) | {_g4(s.deterministic)} | {_g4(s.p10)} | "
                f"{_g4(s.p50)} | {_g4(s.p90)} | {_g4(s.mean)} |"
            )
        for s in mc.statistics:
            if s.metric == report.metric and s.sensitivity:
                lines += ["", f"Drivers of {s.metric} (Spearman rank correlation):", ""]
                lines += [f"- {name}: {rho:+.2f}" for name, rho in s.sensitivity]
    lines += [
        "",
        f"## What would change the decision ({report.metric} = "
        f"{_metric_text(report, report.metric, report.threshold)})",
        "",
        "| input | base | turns at | change |",
        "|---|---|---|---|",
    ]
    for turn in report.turns:
        if turn.multiplier is None:
            lines.append(f"| {turn.input} | {_base(report, turn.base, turn.unit)} | never | |")
        else:
            lines.append(
                f"| {turn.input} | {_base(report, turn.base, turn.unit)} | "
                f"{_base(report, turn.value, turn.unit, short=True)} "
                f"| {turn.multiplier - 1:+.0%} |"
            )
    if report.findings:
        lines += ["", "## Findings", ""] + [f"- {f.format()}" for f in report.findings]
    return "\n".join(lines) + "\n"


def _net(line: dict[str, Any]) -> float:
    """A line's net income per year, as the flows report theirs: revenue positive, cost
    negative."""
    return line["per_year"] if line["revenue"] else -line["per_year"]


def _boundary_lines(report: TeaReport) -> list[str]:
    """The section Boundary of ``estimate/tea.md``: what the operating cost leaves out."""
    gaps = report.boundary
    if gaps is None:
        return []
    lines = ["", "## Boundary", "", *gaps.coverage_lines()]
    uncosted, costed = report.unclassified_products()
    excluded = []
    if gaps.unassigned_duties:
        excluded.append(
            f"- the utilities (steam, cooling, refrigeration, power) of "
            f"{', '.join(gaps.unassigned_duties)}: no energy stream reaches them, so no rate "
            "is priced"
        )
    if uncosted:
        excluded.append(
            f"- any disposal or treatment cost of {', '.join(uncosted)}: no category, no "
            "price, no disposal item or emission source and not listed free"
        )
    if excluded:
        lines += ["", "The variable operating cost above excludes:", "", *excluded]
    if costed:
        lines += [
            "",
            f"Not classified (no category): {', '.join(costed)}. Each is priced, listed free, "
            "costed by a disposal item or an emission source, or the main product (whose "
            "price, or levelised cost, is the study's), but whether each is a product, "
            "wastewater, off-gas, solid waste or an emission is not stated.",
        ]
    return lines + gaps.table_lines()


def _yes(value: bool | None) -> str:
    return {True: "yes", False: "no", None: ""}[value]


def _finite(value: Any) -> Any:
    """*value* with every non-finite float (nan, inf) replaced by None, recursively."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_finite(v) for v in value]
    return value
