"""The builder of a :class:`~.report.TeaReport`: premises, lines and findings.

:class:`Builder` reads the inputs of a TEA and fills the report step by step. Every problem is a
finding, never an exception: an error stops the evaluation (``loaded`` is then False), a warning
or an info is reported with it.

What the plant buys and sells becomes the :class:`~.model.Line` list of the premises:

- every priced feed and product of the flowsheet (a component of one: ``<key>@<component>``),
  in the case of the file or as the share-weighted sum of its ``cases`` (a flow with a price of
  its own in a case: one line per case, ``<key>~<case>``, sharing the flow's rate and price
  inputs);
- the main product, priced or not (its price is what the LCOP solves for);
- the ``variable_opex`` items (``variable:<id>``), per a flow, per operating hour or per batch;
- the emissions (``emission:<id>``) and the free allowance (``allowance:carbon``), all priced by
  ``price:carbon``.

Each input id is registered once (:class:`Reg`: its value, unit, status, source, uncertainty
and swing); the input list, the Monte Carlo, the tornado and the scenarios read the registry.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.flows import Terminal, boundary_gaps, terminals
from chemeascode.domains.assessment.lca.schemas import Allocation as LcaAllocation
from chemeascode.domains.assessment.lca.schemas import Operation as LcaOperation
from chemeascode.domains.assessment.lca.schemas import Uncertainty
from chemeascode.domains.assessment.tea import model
from chemeascode.domains.assessment.tea.model import Line, Premises, break_even, evaluate
from chemeascode.domains.assessment.tea.schemas import (
    PRICE_UNITS,
    RATE_UNITS,
    Fraction,
    Path,
    Price,
    TeaFile,
    Value,
)
from chemeascode.domains.assessment.tea.uncertainty import monte_carlo, p10_p90
from chemeascode.domains.assessment.tea.uncertainty import tornado as tornado_bars
from chemeascode.domains.process import FLOWSHEET_FILE
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace

_ORDER = ("given", "calculated", "assumed")
#: How far the TEA's relative product prices may be from the LCA's allocation prices.
PRICE_RATIO_TOLERANCE = 0.05


#: The section of tea.yaml whose list holds the entries of an id needle (``variable:<id>``).
_SECTIONS = {
    "variable": "variable_opex",
    "emission": "emissions",
    "event": "events",
    "scenario": "scenarios",
}


def _line(text: str | None, needle: str) -> int | None:
    """The line of *needle* in *text*: an entry of a list by its id (``variable:<id>``,
    ``emission:<id>``, ``event:<id>``, ``scenario:<id>``: its ``id: <id>`` in that section), a
    component's price (``<key>@<component>``, a case's ``~<case>`` dropped: its ``component``
    in the entry of the key), else the first line that contains it."""
    if not text:
        return None
    lines = text.splitlines()
    kind, _, rest = needle.partition(":")
    if kind in _SECTIONS and rest:
        start = next(
            (i for i, line in enumerate(lines) if line.startswith(f"{_SECTIONS[kind]}:")), 0
        )
        entry = re.compile(rf"\bid:\s*['\"]?{re.escape(rest)}(?![\w.\-])")
        for number in range(start, len(lines)):
            if entry.search(lines[number]):
                return number + 1
    key, at, component = needle.split("~")[0].partition("@")
    if at and kind in ("feed", "product"):
        named = re.compile(rf"component:\s*['\"]?{re.escape(component)}(?![\w.\-])")
        keyed = re.compile(rf"{re.escape(key)}(?![\w.\-])")
        for i, line in enumerate(lines):
            if not keyed.search(line):
                continue
            # the component in the same flow-style entry or in the block entry's next lines
            for j in range(i, min(i + 12, len(lines))):
                if named.search(lines[j]):
                    return j + 1
                if j > i and lines[j].lstrip().startswith("- "):
                    break
        needle = key
    for number, line in enumerate(lines, 1):
        if needle in line:
            return number
    return None


def _weakest(values: list[str]) -> str:
    known = [v for v in values if v in _ORDER]
    return max(known, key=_ORDER.index) if known else "assumed"


def _unit_factor(unit: str, kind: str, conversion: Value | None) -> float:
    """Per kg or kWh of a flow of *kind*, per one *unit* (no findings: see ``_per_base``)."""
    unit_kind, factor = PRICE_UNITS[unit]
    if unit_kind == kind and factor is not None:
        return 1.0 / factor
    return conversion.value if conversion is not None else 1.0


def _v(value: Fraction | Value | None) -> float:
    return value.value if value is not None else 0.0


def path_profile(path: Path | None, life: int) -> tuple[float, ...]:
    """The multipliers of a price path by operating year (empty: none)."""
    if path is None:
        return ()
    if path.profile is not None:
        return tuple(path.profile)
    if path.escalation is not None:
        return tuple((1.0 + path.escalation) ** t for t in range(life))
    return ()


@dataclass
class Reg:
    """An input id: its base value as a reader knows it, and how it may vary."""

    value: float
    unit: str
    status: str = ""
    source: str = ""
    #: Its own distribution (None: the defaults by status apply, when ``defaults``).
    uncertainty: Uncertainty | None = None
    swing: Any = None
    defaults: bool = True


@dataclass
class Merged:
    """A feed or product over the cases of the analysis: the share-weighted rates."""

    key: str
    title: str
    kind: str
    per_hour: float = 0.0
    components: dict[str, float] = field(default_factory=dict)
    provenance: list[str] = field(default_factory=list)
    #: The rate of each case (unweighted), and of each component in each case.
    by_case: dict[str, float] = field(default_factory=dict)
    components_by_case: dict[str, dict[str, float]] = field(default_factory=dict)
    #: Why its rate cannot be fully split into components, by case: a component's rate would
    #: miss what flows without a composition.
    unsplit: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


class Builder:
    """Fills a :class:`~.report.TeaReport`; see the module docstring."""

    def __init__(self, report: Any, file: str) -> None:
        self.report = report
        self.root = report.root
        self.file = file
        self.text: str | None = None
        self.registry: dict[str, Reg] = {}
        #: Per line key: units of its displayed price per base unit (for scenario prices).
        self.price_factor: dict[str, float] = {}
        self.shares: dict[str, float] = {}
        self.merged: dict[str, Merged] = {}

    # -- findings ----------------------------------------------------------------------------

    def problem(
        self,
        level: str,
        rule: str,
        message: str,
        hint: str,
        needle: str | None = None,
        ids: list[str] | None = None,
        file: str | None = None,
    ) -> None:
        file = file or self.file
        self.report.findings.append(
            Finding(
                file,
                level,  # type: ignore[arg-type]
                rule,
                message,
                line=_line(self.text, needle) if needle and file == self.file else None,
                ids=list(ids or []),
                hint=hint,
            )
        )

    def errors(self) -> bool:
        return any(f.level == "error" for f in self.report.findings)

    def register(self, name: str, value: Value | None, number: float, unit: str, **extra) -> None:
        if name in self.registry:
            return
        self.registry[name] = Reg(
            number,
            unit,
            value.status if value is not None else "",
            value.source if value is not None else "",
            value.uncertainty if value is not None else None,
            value.swing if value is not None else None,
            **extra,
        )

    # -- steps -------------------------------------------------------------------------------

    def run(self) -> None:
        tea = self.load()
        if tea is None:
            return
        r = self.report
        r.tea, r.currency, r.cost_year, r.example = tea, tea.currency, tea.cost_year, tea.example
        self.stage(tea)
        operation = self.operation(tea)
        flows = self.flows(tea)
        if operation is None or flows is None or self.errors():
            return
        self.merged = flows
        lines = self.lines(tea, flows, operation)
        isbl = self.isbl(tea, flows, operation)
        if lines is None or isbl is None or self.errors():
            return
        premises = self.premises(tea, operation, lines, isbl)
        r.premises = premises
        r.baseline = evaluate(premises)
        # a flow's per_year: the net income of its lines, revenue positive, cost negative
        for row in r.flows:
            keyed = [x for x in premises.lines if x.key.split("@")[0].split("~")[0] == row.key]
            if keyed and (row.price is not None or row.key == premises.main):
                row.per_year = float(
                    sum(
                        (1.0 if x.revenue else -1.0) * float(r.baseline.amounts[x.key][0])
                        for x in keyed
                    )
                )
        self.capex_lines(tea)
        self.opex_lines(tea)
        self.event_lines(tea)
        self.decision(tea)
        self.describe(tea, premises)
        self.scenarios(tea)
        self.sensitivity(tea)
        self.unsubsidised()
        self.unused(tea)
        if tea.example:
            self.problem(
                "warning",
                "cheme.tea-example",
                "the premises are an example (example: true): the results evaluate nothing real",
                "replace every value with the project's own, each with its status, source and "
                "year, and remove example: true",
                "example:",
            )

    def load(self) -> TeaFile | None:
        path = self.root / self.file
        if not path.is_file():
            self.problem(
                "error",
                "cheme.tea-no-premises",
                f"no {self.file}",
                "write the premises there (cheme schema tea; the skill tea, "
                ".claude/skills/tea/SKILL.md, has a complete example)",
            )
            return None
        try:
            self.text = path.read_text(encoding="utf-8")
            return TeaFile.model_validate(yaml.safe_load(self.text) or {})
        except (OSError, UnicodeDecodeError, ValidationError, yaml.YAMLError) as failure:
            first = " ".join(str(failure).splitlines()[:3])
            self.problem(
                "error",
                "cheme.tea-premises",
                f"{self.file} does not load: {first}",
                "cheme validate names the line",
            )
            return None

    def stage(self, tea: TeaFile) -> None:
        r = self.report
        try:
            r.stage = Workspace(self.root).config().stage
        except (OSError, ValidationError, yaml.YAMLError):
            r.stage = ""
        r.expected_class = tea.class_by_stage.get(r.stage)
        claimed = tea.capex.isbl.estimate_class
        if claimed is None and tea.capex.isbl.source == "equipment":
            from chemeascode.domains.assessment.equipment_cost import BASIS_FILE, load_basis

            path = self.root / BASIS_FILE
            basis, _ = load_basis(path.read_text(encoding="utf-8") if path.is_file() else None)
            claimed = basis.estimate_class if basis is not None else None
        r.claimed_class = claimed or 5
        expected = r.expected_class
        if expected is None:
            self.problem(
                "info",
                "cheme.tea-class-stage",
                f"stage {r.stage or '(none)'} has no expected estimate class in class_by_stage",
                "add the stage to class_by_stage",
                "class_by_stage",
            )
        elif r.claimed_class < expected:
            self.problem(
                "warning",
                "cheme.tea-class-stage",
                f"the capital cost claims AACE class {r.claimed_class}, finer than a {r.stage} "
                f"stage supports (class {expected}): the scope is not defined that far yet",
                "claim the class the scope supports (isbl.estimate_class)",
                "estimate_class",
            )
        elif r.claimed_class > expected:
            self.problem(
                "warning",
                "cheme.tea-class-stage",
                f"the capital cost is AACE class {r.claimed_class}; stage {r.stage} expects "
                f"class {expected} before its decision",
                "define the scope further (sizes, quotations) and update the estimate's class",
                "estimate_class",
            )

    def operation(self, tea: TeaFile) -> dict[str, Any] | None:
        """Hours, life, ramp-up, utilisation and batch of the plant."""
        r = self.report
        lca = None
        path = self.root / self.report_lca_file
        if path.is_file():
            try:
                data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("operation")
                lca = LcaOperation.model_validate(data) if data else None
            except (OSError, UnicodeDecodeError, ValidationError, yaml.YAMLError, AttributeError):
                lca = None
        own = tea.operation
        if own is None and lca is None:
            self.problem(
                "error",
                "cheme.tea-no-operation",
                "no operation: hours per year and life are given neither here nor in "
                f"{self.report_lca_file}",
                "give operation: {hours_per_year, life_years, source}",
            )
            return None
        if own is None:
            r.hours, r.life = lca.hours_per_year, round(lca.life_years)
            r.operation_source = f"{self.report_lca_file}: {lca.source}".rstrip(": ")
            self.problem(
                "info",
                "cheme.tea-operation-from-lca",
                f"operation taken from {self.report_lca_file}: {lca.hours_per_year:g} h/a, "
                f"{r.life} years",
                "give operation: here to state it for the TEA",
            )
            return {
                "hours": r.hours,
                "life": r.life,
                "ramp": [],
                "utilisation": None,
                "batch": None,
            }
        r.hours, r.life, r.operation_source = own.hours_per_year, own.life_years, own.source
        if lca is not None and (
            lca.hours_per_year != own.hours_per_year or round(lca.life_years) != own.life_years
        ):
            self.problem(
                "warning",
                "cheme.tea-basis-mismatch",
                f"operation differs from {self.report_lca_file}: {own.hours_per_year:g} h/a, "
                f"{own.life_years} years here, {lca.hours_per_year:g} h/a, "
                f"{lca.life_years:g} years there",
                "state one operating basis for the plant, or say why they differ",
                "hours_per_year",
            )
        batch = None
        if own.batch is not None:
            b = own.batch
            batch = model.Batch(
                cycle_time=b.cycle_time.value,
                basis_hours=b.basis_hours,
                trains=b.trains,
                batches_per_year=b.batches_per_year.value if b.batches_per_year else None,
                success_rate=b.success_rate.value if b.success_rate else 1.0,
            )
            batches = (
                batch.batches_per_year
                if batch.batches_per_year is not None
                else own.hours_per_year * b.trains / b.cycle_time.value
            )
            r.batches = batches
            if batch.batches_per_year is None:
                self.problem(
                    "info",
                    "cheme.tea-batch-basis",
                    f"{batches:.4g} batches per year from {own.hours_per_year:g} h x {b.trains} "
                    f"trains / {b.cycle_time.value:g} h per batch",
                    "give batches_per_year when the schedule says otherwise",
                    "batch:",
                )
            elif batches * b.cycle_time.value > own.hours_per_year * b.trains * (1 + 1e-9):
                self.problem(
                    "warning",
                    "cheme.tea-batch-overbooked",
                    f"{batches:g} batches of {b.cycle_time.value:g} h need "
                    f"{batches * b.cycle_time.value:.4g} h, more than {own.hours_per_year:g} h x "
                    f"{b.trains} trains",
                    "fewer batches, more trains or a shorter cycle",
                    "batches_per_year",
                )
            self.register(
                "operation:cycle_time", b.cycle_time, b.cycle_time.value, "h/batch"
            ) if b.batches_per_year is None else self.register(
                "operation:batches_per_year", b.batches_per_year, b.batches_per_year.value, "1/a"
            )
            if b.success_rate is not None:
                self.register(
                    "operation:success_rate", b.success_rate, b.success_rate.value, "fraction"
                )
        if own.utilisation is not None:
            self.register(
                "operation:utilisation", own.utilisation, own.utilisation.value, "fraction"
            )
        return {
            "hours": own.hours_per_year,
            "life": own.life_years,
            "ramp": list(own.ramp_up),
            "utilisation": own.utilisation.value if own.utilisation else None,
            "batch": batch,
        }

    @property
    def report_lca_file(self) -> str:
        from chemeascode.foundation.workspace import LIST_FILES

        return LIST_FILES["lca"]

    def flows(self, tea: TeaFile) -> dict[str, Merged] | None:
        """The flowsheet's feeds and products, share-weighted over the cases."""
        from chemeascode.domains.process.model import load

        r = self.report
        process, found = load(self.root)
        r.findings += [f for f in found if f.level == "error"]
        if process is None:
            self.problem(
                "error",
                "cheme.tea-no-flowsheet",
                f"no loadable {FLOWSHEET_FILE}: the operating cost and revenue are its feeds "
                "and products",
                "cheme process streams shows what is missing",
                file=FLOWSHEET_FILE,
            )
            return None
        # what the terminals leave out: reported, the rates are not changed
        r.boundary = boundary_gaps(process)
        r.findings += r.boundary.findings
        fs = process.flowsheet
        known = [c.id for c in fs.cases]
        if tea.cases is not None:
            plan = [(c.case, c.share.value) for c in tea.cases]
        else:
            plan = [(tea.case or fs.default_case(), 1.0)]
        r.case = ", ".join(f"{c} ({s:.0%})" if len(plan) > 1 else c for c, s in plan)
        r.cases = [{"case": c, "share": s} for c, s in plan]
        for case, _ in plan:
            if case not in known:
                self.problem(
                    "error",
                    "cheme.tea-case",
                    f"case {case!r} is not a case of {FLOWSHEET_FILE}",
                    f"use one of {', '.join(known)}",
                    "case",
                )
        if self.errors():
            return None
        self.shares = dict(plan)
        merged: dict[str, Merged] = {}
        for case, share in plan:
            for t in terminals(process, case):
                self._check_terminal(t, case)
                m = merged.setdefault(t.key, Merged(t.key, t.title, t.kind))
                m.per_hour += share * t.per_hour
                m.by_case[case] = t.per_hour
                m.components_by_case[case] = dict(t.components)
                for name, value in t.components.items():
                    m.components[name] = m.components.get(name, 0.0) + share * value
                m.provenance += t.provenance
                if t.unsplit or (t.per_hour > 0 and not t.components):
                    m.unsplit.append(f"case {case}: {'; '.join(t.unsplit) or 'no composition'}")
                m.missing += t.missing
        if len(plan) > 1:
            for m in merged.values():
                flowing = [c for c, v in m.by_case.items() if v > 0]
                if flowing and len(flowing) < len(plan):
                    self.problem(
                        "info",
                        "cheme.tea-case-terminal",
                        f"{m.key} flows only in {', '.join(flowing)}",
                        "check that the other cases are meant to have none",
                        m.key,
                        [m.key],
                    )
        main = merged.get(f"product:{tea.basis.product}")
        if main is None or main.per_hour <= 0:
            self.problem(
                "error",
                "cheme.tea-product",
                f"basis.product {tea.basis.product!r} is not a product with a flow in "
                f"{FLOWSHEET_FILE} ({r.case})",
                "name the main product of the flowsheet",
                "product:",
            )
            return None
        return merged

    def _rate_id(self, key: str, component: str | None) -> str:
        """The rate input a line per *key* (or its *component*) scales with: the component's
        own when a price line carries it, so one input drives one physical rate."""
        if component is not None and f"{key}@{component}" in self.price_factor:
            return f"rate:{key}@{component}"
        return f"rate:{key}"

    def _unsplit(self, m: Merged, what: str, rule: str, needle: str) -> bool:
        """An error when a line per a component of *m* would miss the part of its rate that
        has no composition; True when there is one."""
        if not m.unsplit:
            return False
        self.problem(
            "error",
            rule,
            f"{what}: {m.key} cannot be split into components ({'; '.join(m.unsplit)}), so "
            "a component's rate would leave out what flows without a composition",
            f"give the compositions of its streams in {FLOWSHEET_FILE}, or price the whole flow",
            needle,
            [what],
        )
        return True

    def _check_terminal(self, terminal: Terminal, case: str) -> None:
        if len(terminal.kinds) > 1 or terminal.invalid:
            self.problem(
                "error",
                "cheme.tea-flow-invalid",
                f"{terminal.key}: cannot count its streams in case {case} "
                f"({'; '.join(terminal.invalid) or 'material and energy mixed'})",
                f"correct the streams in {FLOWSHEET_FILE} (case {case})",
                ids=[terminal.key],
                file=FLOWSHEET_FILE,
            )
        elif terminal.missing:
            self.problem(
                "warning",
                "cheme.tea-flow-incomplete",
                f"{terminal.key}: the flowsheet lacks {', '.join(terminal.missing[:4])} in case "
                f"{case}; the rest is counted",
                f"complete the stream state in {FLOWSHEET_FILE} (case {case})",
                ids=[terminal.key],
                file=FLOWSHEET_FILE,
            )

    # -- lines -------------------------------------------------------------------------------

    def _per_base(
        self, value: float, unit: str, kind: str, conversion: Value | None, what: str
    ) -> float | None:
        """*value* per *unit* as per kg (material) or kWh (energy) of the flow; None (and an
        error) when the unit cannot be converted."""
        unit_kind, factor = PRICE_UNITS[unit]
        if unit_kind == kind and factor is not None:
            if conversion is not None:
                self.problem(
                    "warning",
                    "cheme.tea-conversion-unused",
                    f"{what}: per {unit} of a {kind} flow needs no conversion; it is not used",
                    "remove the conversion",
                    what,
                    [what],
                )
            return value / factor
        if conversion is None:
            self.problem(
                "error",
                "cheme.tea-price-unit",
                f"{what} is a {kind} flow (per {RATE_UNITS[kind]}); per {unit} needs a "
                f"conversion ({unit} per {RATE_UNITS[kind]})",
                f"give conversion: {{value, source}} in {unit} per {RATE_UNITS[kind]}, or price "
                f"it per {'kg or t' if kind == 'material' else 'kWh, MWh, MJ or GJ'}",
                what,
                [what],
            )
            return None
        return value * conversion.value

    def lines(
        self, tea: TeaFile, flows: dict[str, Merged], operation: dict[str, Any]
    ) -> list[Line] | None:
        r = self.report
        life = operation["life"]
        cur = tea.currency
        main_key = f"product:{tea.basis.product}"
        free = {f.key: f.reason for f in tea.free}
        by_key: dict[str, list[Price]] = {}
        for price in tea.prices:
            by_key.setdefault(price.key, []).append(price)
        for key in [*by_key, *free]:
            if key not in flows:
                self.problem(
                    "error",
                    "cheme.tea-price-unknown",
                    f"{key} is not a feed or product of {FLOWSHEET_FILE}",
                    "use the keys of the flowsheet's terminals (feed:<id>, product:<id>)",
                    key,
                    [key],
                )
        case_prices: dict[str, dict[str, float]] = {}
        for c in tea.cases or []:
            for key, value in c.prices.items():
                case_prices.setdefault(key, {})[c.case] = value
        lines: list[Line] = []
        unpriced = []
        #: each product's price per kg (kWh) of the whole flow, for the LCA's allocation prices
        product_prices: dict[str, float] = {}
        for key, m in flows.items():
            unit = RATE_UNITS[m.kind]
            provenance = _weakest(m.provenance)
            prices = by_key.get(key, [])
            row = r.FlowLine(key, m.title, m.kind, m.per_hour, f"{unit}/h", provenance)
            row.per_case = dict(m.by_case) if len(self.shares) > 1 else {}
            r.flows.append(row)
            if not prices:
                if key in free:
                    row.free = free[key]
                elif key == main_key:
                    lines.append(self._flow_line(key, m, None, 0.0, life))
                elif m.per_hour > 0 and key not in tea.costed_elsewhere():
                    unpriced.append(key)
                continue
            for price in prices:
                line_key = key + (f"@{price.component}" if price.component else "")
                if price.component is not None:
                    if key == main_key:
                        self.problem(
                            "error",
                            "cheme.tea-price-component",
                            f"{key} is the main product: price it as a whole",
                            "remove component from its price",
                            key,
                            [key],
                        )
                        continue
                    if self._unsplit(m, line_key, "cheme.tea-price-component", line_key):
                        continue
                    if m.kind != "material" or price.component not in m.components:
                        self.problem(
                            "error",
                            "cheme.tea-price-component",
                            f"{line_key}: {key} has no component {price.component} in "
                            f"{FLOWSHEET_FILE} (or no composition to split it by)",
                            "give the streams' compositions, or price the whole flow",
                            key,
                            [line_key],
                        )
                        continue
                kind = "material" if price.component else m.kind
                per_base = self._per_base(price.value, price.unit, kind, price.conversion, line_key)
                if per_base is None:
                    continue
                self.price_factor[line_key] = _unit_factor(price.unit, kind, price.conversion)
                if key.startswith("product:") and m.per_hour > 0:
                    # per kg (kWh) of the whole flow: a component's price weighted by its share
                    share = m.components[price.component] / m.per_hour if price.component else 1.0
                    product_prices[key] = product_prices.get(key, 0.0) + per_base * share
                row.price, row.price_unit = price.value, price.unit
                row.component = price.component or ""
                row.prices.append(
                    {"component": price.component or "", "price": price.value, "unit": price.unit}
                )
                row.status, row.source, row.year = price.status, price.source, price.year
                if price.year is None:
                    self.problem(
                        "info",
                        "cheme.tea-no-year",
                        f"{line_key}: the price gives no year",
                        "give its year: it is checked against cost_year",
                        line_key,
                        [line_key],
                    )
                else:
                    self._year(price, line_key, line_key)
                self.register(f"price:{line_key}", price, price.value, f"{cur}/{price.unit}")
                if (
                    price.conversion is not None
                    and PRICE_UNITS[price.unit][0] != kind
                    and key != main_key
                ):
                    self.register(
                        f"conversion:{line_key}",
                        price.conversion,
                        price.conversion.value,
                        f"{price.unit}/{RATE_UNITS[kind]}",
                    )
                overrides = case_prices.get(line_key, {})
                if overrides and key != main_key:
                    merged_rate = m.components[price.component] if price.component else m.per_hour
                    self.registry.setdefault(
                        f"rate:{line_key}",
                        Reg(
                            merged_rate,
                            f"{RATE_UNITS[kind]}/h",
                            _weakest(m.provenance),
                            FLOWSHEET_FILE,
                            defaults=False,
                        ),
                    )
                if overrides and key == main_key:
                    self.problem(
                        "error",
                        "cheme.tea-case-price",
                        f"{key} is the main product: its LCOP needs one price for all cases",
                        "remove its price from cases[].prices",
                        key,
                        [key],
                    )
                    continue
                lines += self._priced(line_key, m, price, per_base, overrides, life, main_key)
        if unpriced:
            self.problem(
                "warning",
                "cheme.tea-price-missing",
                f"{len(unpriced)} feeds and products have no price and count as free: "
                f"{', '.join(unpriced)}",
                "give each a price (status, source, year), or list it under free: with why",
                "prices:",
                unpriced,
            )
        main_price = next((p for p in by_key.get(main_key, []) if p.component is None), None)
        self._main_unit(tea, flows[main_key], main_price)
        if (
            tea.decision is not None
            and tea.decision.metric in ("npv", "irr")
            and main_price is None
        ):
            self.problem(
                "warning",
                "cheme.tea-price-missing",
                f"the decision is taken on {tea.decision.metric}, but the main product {main_key} "
                "has no price: its revenue counts as 0",
                "price the main product, or take the decision on lcop",
                "decision:",
            )
        self.lca_prices(tea, product_prices)
        lines += self._variable(tea, flows, operation)
        lines += self._emissions(tea, flows, life)
        for c in tea.cases or []:
            for key in c.prices:
                base = key.split("@")[0]
                if base not in flows:
                    self.problem(
                        "error",
                        "cheme.tea-price-unknown",
                        f"case {c.case}: {key} is not a feed or product of {FLOWSHEET_FILE}",
                        "use the keys of the flowsheet's terminals (feed:<id>, product:<id>)",
                        c.case,
                        [key],
                    )
                elif key not in self.price_factor:
                    self.problem(
                        "warning",
                        "cheme.tea-case-price",
                        f"case {c.case}: {key} has no baseline price; its case price is ignored",
                        "price the flow in prices: first (the case keeps its unit)",
                        c.case,
                        [key],
                    )
        return None if self.errors() else lines

    def _flow_line(self, key: str, m: Merged, price: Price | None, per_base: float, life: int):
        """The line of a flow. A product with a negative price (a disposal, rejected heat) is a
        cost line with the positive price: the same cash flow, counted with the costs."""
        main = key == self.main_key
        revenue = key.startswith("product:") and (main or per_base >= 0)
        cost_product = key.startswith("product:") and not revenue
        if price is not None and price.category is not None:
            category = price.category
        elif key.startswith("feed:"):
            category = "feed" if m.kind == "material" else "utility"
        elif cost_product:
            category = "disposal" if m.kind == "material" else "utility"
        else:
            category = "byproduct"
        return Line(
            key,
            m.per_hour,
            -per_base if cost_product else per_base,
            revenue,
            unit=RATE_UNITS[m.kind],
            category=category,
            profile=path_profile(price, life),
            saleable=revenue,
        )

    @property
    def main_key(self) -> str:
        return f"product:{self.report.tea.basis.product}"

    def _priced(self, line_key, m, price, per_base, overrides, life, main_key) -> list[Line]:
        """The line of a priced flow (or component), split by case where a case prices it."""
        rate = m.components[price.component] if price.component else m.per_hour
        kind = "material" if price.component else m.kind
        conv = (f"conversion:{line_key}",) if f"conversion:{line_key}" in self.registry else ()
        base = self._flow_line(m.key, m, price, per_base, life)
        common = dict(
            revenue=base.revenue,
            unit=RATE_UNITS[kind],
            category=base.category,
            profile=base.profile,
            saleable=base.saleable,
        )
        # a product that costs (negative price) is carried as a cost line with the price negated
        sign = -1.0 if m.key.startswith("product:") and not base.revenue else 1.0
        if sign < 0:
            self.price_factor[line_key] = -self.price_factor[line_key]
        if not overrides:
            return [Line(line_key, rate, sign * per_base, prices=conv, **common)]
        out = []
        for case, share in self.shares.items():
            if price.component:
                case_rate = m.components_by_case.get(case, {}).get(price.component, 0.0)
            else:
                case_rate = m.by_case.get(case, 0.0)
            value = overrides.get(case)
            case_price = sign * per_base if value is None else value * self.price_factor[line_key]
            out.append(
                Line(
                    f"{line_key}~{case}",
                    share * case_rate,
                    case_price,
                    prices=conv,
                    rate_id=f"rate:{line_key}",
                    price_id=f"price:{line_key}",
                    **common,
                )
            )
        return out

    def _main_unit(self, tea: TeaFile, m: Merged, price: Price | None) -> None:
        """The unit the LCOP is reported in, and the factor from per kg / kWh to it."""
        r = self.report
        unit = tea.basis.unit or (price.unit if price else ("t" if m.kind == "material" else "MWh"))
        kind, factor = PRICE_UNITS[unit]
        if kind == m.kind and factor is not None:
            r.lcop_unit, r.lcop_factor = unit, factor
            return
        conversion = tea.basis.conversion or (
            price.conversion if price is not None and price.unit == unit else None
        )
        if conversion is None or conversion.value <= 0:
            self.problem(
                "error",
                "cheme.tea-product-unit",
                f"the main product is a {m.kind} flow; its cost per {unit} needs a conversion",
                f"give basis.conversion ({unit} per {RATE_UNITS[m.kind]}) with its source",
                "basis:",
            )
            return
        r.lcop_unit, r.lcop_factor = unit, 1.0 / conversion.value

    def _variable(self, tea: TeaFile, flows: dict[str, Merged], operation) -> list[Line]:
        out = []
        cur = tea.currency
        for item in tea.variable_opex:
            what = f"variable:{item.id}"
            if item.per == "hour":
                rate, scales, per_unit = item.amount.value, (), "h"
            elif item.per == "batch":
                batch = operation["batch"]
                if batch is None:
                    self.problem(
                        "error",
                        "cheme.tea-variable-per",
                        f"{what} is per batch, but operation gives no batch",
                        "give operation.batch, or put it per hour or per a flow",
                        f"variable:{item.id}",
                        [what],
                    )
                    continue
                rate, scales, per_unit = item.amount.value / batch.basis_hours, (), "batch"
            else:
                parent = flows.get(item.per)
                if parent is None:
                    self.problem(
                        "error",
                        "cheme.tea-variable-per",
                        f"{what}: {item.per} is not a feed or product of {FLOWSHEET_FILE}",
                        "name a terminal of the flowsheet, hour or batch",
                        f"variable:{item.id}",
                        [what],
                    )
                    continue
                if item.component is not None:
                    if self._unsplit(
                        parent, what, "cheme.tea-price-component", f"variable:{item.id}"
                    ):
                        continue
                    if item.component not in parent.components:
                        self.problem(
                            "error",
                            "cheme.tea-price-component",
                            f"{what}: {item.per} has no component {item.component}",
                            "give the streams' compositions, or drop component",
                            f"variable:{item.id}",
                            [what],
                        )
                        continue
                    base = parent.components[item.component]
                    per_unit = f"kg {item.component}"
                else:
                    base = parent.per_hour
                    per_unit = RATE_UNITS[parent.kind]
                rate, scales = item.amount.value * base, (self._rate_id(item.per, item.component),)
            self.register(f"price:{what}", item, item.value, f"{cur}/{item.unit}")
            self.register(f"rate:{what}", item.amount, item.amount.value, f"{item.unit}/{per_unit}")
            if item.year is None:
                self.problem(
                    "info",
                    "cheme.tea-no-year",
                    f"{what}: the price gives no year",
                    "give its year: it is checked against cost_year",
                    f"variable:{item.id}",
                    [what],
                )
            else:
                self._year(item, what, item.id)
            self.price_factor[what] = 1.0
            out.append(
                Line(
                    what,
                    rate,
                    item.value,
                    False,
                    unit=item.unit,
                    category=item.category,
                    scales=scales,
                    profile=path_profile(item, operation["life"]),
                )
            )
            self.report.variable.append(
                {
                    "id": item.id,
                    "title": item.title or item.id,
                    "per": item.per,
                    "component": item.component or "",
                    "amount": item.amount.value,
                    "unit": item.unit,
                    "price": item.value,
                    "category": item.category,
                    "rate": rate,
                    "status": item.status,
                    "source": item.source,
                    "year": item.year,
                }
            )
        return out

    def _emissions(self, tea: TeaFile, flows: dict[str, Merged], life: int) -> list[Line]:
        e = tea.emissions
        lca_emissions = self._lca_emission_keys()
        if e is None:
            if lca_emissions:
                self.problem(
                    "info",
                    "cheme.tea-emission-unpriced",
                    f"{self.report_lca_file} maps {', '.join(sorted(lca_emissions))} as emissions; "
                    "the TEA prices no emissions",
                    "give emissions: {price, sources} when a carbon price applies",
                )
            return []
        cur = tea.currency
        out = []
        profile = path_profile(e, life)
        self.register("price:carbon", e.price, e.price.value, f"{cur}/t CO2-eq")
        self.price_factor["carbon"] = 1.0
        sourced = set()
        for source in e.sources:
            what = f"emission:{source.id}"
            m = flows.get(source.key)
            if m is None:
                self.problem(
                    "error",
                    "cheme.tea-emission-source",
                    f"{what}: {source.key} is not a feed or product of {FLOWSHEET_FILE}",
                    "name a terminal of the flowsheet",
                    f"emission:{source.id}",
                    [what],
                )
                continue
            sourced.add(source.key)
            if source.component is not None:
                if self._unsplit(m, what, "cheme.tea-emission-components", f"emission:{source.id}"):
                    continue
                if source.component not in m.components:
                    self.problem(
                        "error",
                        "cheme.tea-emission-components",
                        f"{what}: {source.key} has no component {source.component} (or no "
                        "composition)",
                        "give the streams' compositions, or a factor per the whole flow",
                        f"emission:{source.id}",
                        [what],
                    )
                    continue
                qty, kind = m.components[source.component], "material"
            else:
                qty, kind = m.per_hour, m.kind
            per_base = self._per_base(
                source.factor.value, source.unit, kind, source.conversion, what
            )
            if per_base is None:
                continue
            kept = 1.0 - (source.captured.value if source.captured else 0.0)
            self.register(
                f"rate:{what}", source.factor, source.factor.value, f"t CO2-eq/{source.unit}"
            )
            out.append(
                Line(
                    what,
                    qty * per_base * kept,
                    e.price.value,
                    False,
                    unit="t CO2-eq",
                    category="emission",
                    scales=(self._rate_id(source.key, source.component),),
                    profile=profile,
                    price_id="price:carbon",
                )
            )
        if e.allocation is not None:
            a = e.allocation
            m = flows.get(a.per)
            if m is None:
                self.problem(
                    "error",
                    "cheme.tea-emission-source",
                    f"allowance: {a.per} is not a product of {FLOWSHEET_FILE}",
                    "name a product of the flowsheet",
                    "allocation",
                )
            else:
                per_base = self._per_base(
                    a.benchmark.value, a.unit, m.kind, a.conversion, "allowance:carbon"
                )
                if per_base is not None:
                    fraction = path_profile(a, life)
                    carbon = profile or (1.0,) * life
                    combined = tuple(
                        carbon[min(i, len(carbon) - 1)]
                        * (fraction[min(i, len(fraction) - 1)] if fraction else 1.0)
                        for i in range(life)
                    )
                    self.register(
                        "rate:allowance:carbon", a.fraction, a.fraction.value, "fraction free"
                    )
                    out.append(
                        Line(
                            "allowance:carbon",
                            -m.per_hour * per_base * a.fraction.value,
                            e.price.value,
                            False,
                            unit="t CO2-eq",
                            category="emission",
                            scales=(f"rate:{a.per}",),
                            profile=combined,
                            price_id="price:carbon",
                        )
                    )
        if missing := lca_emissions - sourced:
            self.problem(
                "warning",
                "cheme.tea-emission-unpriced",
                f"{self.report_lca_file} maps {', '.join(sorted(missing))} as emissions; no "
                "emission source prices them",
                "add them to emissions.sources, or say why they carry no charge",
                "emissions",
                sorted(missing),
            )
        return out

    def _lca_emission_keys(self) -> set[str]:
        path = self.root / self.report_lca_file
        if not path.is_file():
            return set()
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            return set()
        flows = data.get("flows") if isinstance(data, dict) else None
        return {
            f["key"]
            for f in flows or []
            if isinstance(f, dict) and f.get("emission") is True and isinstance(f.get("key"), str)
        }

    def lca_prices(self, tea: TeaFile, prices: dict[str, float]) -> None:
        """Compare the products' relative prices with those of the LCA's economic allocation.

        ``lca/lca.yaml`` prices the co-products for an economic allocation (any one currency:
        only their ratios count). The same plant sold at other price ratios gives the TEA's
        revenue and the LCA's shares of the burdens different premises: a finding names them.
        """
        path = self.root / self.report_lca_file
        if not path.is_file():
            return
        try:
            data = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("allocation")
            allocation = LcaAllocation.model_validate(data) if data else None
        except (OSError, UnicodeDecodeError, ValidationError, yaml.YAMLError, AttributeError):
            return  # cheme assess lca and cheme validate report it
        if allocation is None:
            return
        theirs = {
            product: price
            for product in [*allocation.prices, *allocation.properties]
            if (price := allocation.product_properties(product).price) is not None
        }
        if not theirs:
            return
        ours = {name: prices.get(f"product:{name}") for name in theirs}
        both = [n for n in theirs if ours[n] and theirs[n]]
        main = tea.basis.product
        reference = main if main in both else (both[0] if both else None)
        differences = []
        for name in theirs:
            here, there = ours[name], theirs[name]
            if not here and not there:
                continue
            if not here or not there:
                differences.append(
                    f"{name} {there:g} in {self.report_lca_file}, free or unpriced here"
                    if not here
                    else f"{name} 0 in {self.report_lca_file}, {here:g} {tea.currency}/kg here"
                )
                continue
            if name == reference:
                continue
            ratio_here = here / ours[reference]
            ratio_there = there / theirs[reference]
            if abs(ratio_here / ratio_there - 1.0) > PRICE_RATIO_TOLERANCE:
                differences.append(
                    f"{name}/{reference} {ratio_here:.3g} here, {ratio_there:.3g} in "
                    f"{self.report_lca_file}"
                )
        if not differences:
            return
        economic = allocation.method == "economic"
        self.problem(
            "warning" if economic else "info",
            "cheme.tea-lca-price-mismatch",
            "the product prices differ from the LCA's "
            + ("economic allocation" if economic else "allocation prices (compared there)")
            + ": "
            + "; ".join(differences),
            f"price the products alike in both (allocation.prices of {self.report_lca_file}, "
            "prices: here), or say in their sources why they differ",
            "prices:",
            [f"product:{n}" for n in theirs],
        )

    def _year(self, value: Value, what: str, needle: str) -> None:
        tea = self.report.tea
        if value.year is not None and value.year != tea.cost_year:
            self.problem(
                "info",
                "cheme.tea-price-year",
                f"{what} is of {value.year}, the TEA of {tea.cost_year}: not escalated",
                "escalate it to the cost year, or say in its source why it holds",
                needle,
                [what],
            )

    # -- capital -----------------------------------------------------------------------------

    def isbl(self, tea: TeaFile, flows: dict[str, Merged], operation) -> float | None:
        """The ISBL cost in the file's currency and cost year, and its build-up lines."""
        spec = tea.capex.isbl
        r = self.report
        CapexLine = r.CapexLine
        lines: list = []
        if spec.source == "given":
            v = spec.value
            value = v.value
            lines.append(
                CapexLine("isbl", "ISBL (given)", "given", v.value, v.status, v.source, v.year)
            )
            currency, year = tea.currency, v.year or tea.cost_year
            if spec.scaling is not None:
                value = self._scaled(tea, spec, flows, operation, value, lines)
                if value is None:
                    return None
            # a given value states its own currency only through exchange_rate
            if spec.exchange_rate is not None:
                currency = "estimate"
                for line in lines:
                    line.currency = "value currency"
        elif spec.source == "mto":
            from chemeascode.domains.assessment.estimate import RATES_FILE, estimate_report

            found = estimate_report(self.root)
            est = found.estimate
            if not found.loaded or not est.lines:
                self.problem(
                    "error",
                    "cheme.tea-capex-source",
                    "isbl.source mto, but cheme assess estimate gives no estimate",
                    "run cheme assess estimate and fix what it reports",
                    "source:",
                )
                return None
            totals = est.totals()
            value = totals["direct"] + totals["indirect"]
            currency, year = est.currency, est.cost_year
            lines.append(
                CapexLine(
                    "isbl-mto",
                    f"Take-off estimate, direct + indirect, {currency} {year} (its contingency "
                    "left out)",
                    f"cheme assess estimate, {RATES_FILE}",
                    value,
                    "example" if est.example else "",
                    RATES_FILE,
                    year,
                    currency=currency,
                )
            )
            if est.example:
                self.problem(
                    "warning",
                    "cheme.tea-example-rates",
                    f"the ISBL is priced with example rates ({RATES_FILE}, example: true)",
                    "price the take-off with the project's rates",
                    "source:",
                )
            unpriced = [line.id for line in est.lines if line.cost is None]
            if unpriced:
                shown = ", ".join(unpriced[:5]) + (
                    f" and {len(unpriced) - 5} more" if len(unpriced) > 5 else ""
                )
                if spec.uncovered_allowance is None:
                    self.problem(
                        "warning",
                        "cheme.tea-capex-uncovered",
                        f"{len(unpriced)} take-off rows have no rate and count as 0, and no "
                        f"allowance is made for them: {shown}",
                        f"give isbl.uncovered_allowance (a fraction of the costed ISBL) with its "
                        f"source, or price them in {RATES_FILE}",
                        "isbl:",
                        unpriced,
                    )
                else:
                    self.problem(
                        "info",
                        "cheme.tea-capex-uncovered",
                        f"{len(unpriced)} take-off rows have no rate; an allowance of "
                        f"{spec.uncovered_allowance.value:.0%} of the costed ISBL stands for "
                        f"them: {shown}",
                        f"price them in {RATES_FILE}",
                        "uncovered_allowance",
                        unpriced,
                    )
        else:
            value, currency, year = self._equipment(tea, spec, lines)
            if value is None:
                return None
        # conversion to the file's currency and cost year
        factor = 1.0
        escalation = 1.0
        if currency == tea.currency and spec.exchange_rate is not None:
            self.problem(
                "warning",
                "cheme.tea-conversion-unused",
                f"isbl.exchange_rate is given, but the estimate is already in {currency}: it is "
                "not used",
                "remove it",
                "exchange_rate",
            )
        if currency != tea.currency:
            if spec.exchange_rate is None:
                self.problem(
                    "error",
                    "cheme.tea-currency",
                    f"the estimate is in {currency}, the TEA in {tea.currency}: no exchange rate",
                    f"give isbl.exchange_rate ({tea.currency} per {currency}) with its source "
                    "and year",
                    "currency:",
                )
                return None
            factor *= spec.exchange_rate.value
            lines.append(
                CapexLine(
                    "isbl-exchange",
                    f"Exchange rate {tea.currency} per "
                    f"{currency if currency != 'estimate' else 'the value currency'}"
                    f": x {spec.exchange_rate.value:g}",
                    "exchange_rate",
                    0.0,
                    spec.exchange_rate.status,
                    spec.exchange_rate.source,
                    spec.exchange_rate.year,
                )
            )
        if year != tea.cost_year:
            if spec.escalation is None:
                self.problem(
                    "warning" if spec.source != "given" else "info",
                    "cheme.tea-cost-year",
                    f"the {'estimate' if spec.source != 'given' else 'given ISBL'} is of {year}, "
                    f"the TEA of {tea.cost_year}: not escalated",
                    "give isbl.escalation (e.g. the CEPCI ratio) with its source",
                    "cost_year:",
                )
            else:
                escalation = spec.escalation.value
                lines.append(
                    CapexLine(
                        "isbl-escalation",
                        f"Escalation {year} to {tea.cost_year}: x {spec.escalation.value:g}",
                        "escalation",
                        0.0,
                        spec.escalation.status,
                        spec.escalation.source,
                        spec.escalation.year,
                    )
                )
        elif spec.escalation is not None:
            self.problem(
                "warning",
                "cheme.tea-conversion-unused",
                f"isbl.escalation is given, but the "
                f"{'estimate' if spec.source != 'given' else 'value'} is already of "
                f"{tea.cost_year}: it is not used",
                "remove it, or give the value's year",
                "escalation",
            )
        # catalyst fills of another year than the estimate's: the escalation is not theirs
        stray = sorted(
            line.year
            for line in lines
            if line.id.startswith("isbl-catalyst-") and line.year not in (year, tea.cost_year)
        )
        if stray:
            self.problem(
                "warning",
                "cheme.tea-cost-year",
                f"catalyst first fills priced in {', '.join(map(str, stray))}, neither the "
                f"estimate's {year} nor the TEA's {tea.cost_year}: not escalated",
                "price the catalysts in the cost index's or the TEA's year "
                "(process/catalysts.yaml)",
                "cost_year:",
            )
        location = spec.location_factor.value if spec.location_factor is not None else 1.0

        def converted(line) -> float:
            if line.id.startswith("isbl-own-"):
                return line.value  # already in the file's currency and year
            if line.id.startswith("isbl-catalyst-") and line.year != year:
                # its own year: the estimate's escalation is not applied
                return line.value * factor * location
            return line.value * factor * escalation * location

        total = sum(converted(line) for line in lines)
        if spec.location_factor is not None:
            lines.append(
                CapexLine(
                    "isbl-location",
                    f"Location factor: x {spec.location_factor.value:g}",
                    "location_factor",
                    0.0,
                    spec.location_factor.status,
                    spec.location_factor.source,
                    spec.location_factor.year,
                )
            )
        if spec.source in ("equipment", "mto") and spec.uncovered_allowance is not None:
            allowance = spec.uncovered_allowance
            extra = total * allowance.value
            lines.append(
                CapexLine(
                    "isbl-uncovered",
                    f"Allowance for what the estimate does not cost: {allowance.value:.0%} of the "
                    "costed ISBL",
                    "uncovered_allowance",
                    extra,
                    allowance.status,
                    allowance.source,
                    allowance.year,
                )
            )
            total += extra
        for line in lines:
            if line.id == "isbl-uncovered":
                line.tea_value = line.value
            elif line.value:
                line.tea_value = converted(line)
        r.capex = lines
        r.isbl_conversion = factor * escalation
        return total

    def _scaled(self, tea, spec, flows, operation, value, lines) -> float | None:
        """The given ISBL scaled from its reference capacity to the plant's."""
        s = spec.scaling
        main = flows[self.main_key]
        kind, factor = PRICE_UNITS[s.unit]
        hours = operation["hours"]
        if operation["batch"] is not None:
            b = operation["batch"]
            batches = b.batches_per_year or hours * b.trains / b.cycle_time
            hours = batches * b.basis_hours
        # the design capacity: the largest case, not the share-weighted average
        per_year = max(main.by_case.values(), default=main.per_hour) * hours
        if kind == main.kind and factor is not None:
            capacity = per_year / factor
        elif s.unit == self.report.lcop_unit:
            capacity = per_year / self.report.lcop_factor
        else:
            self.problem(
                "error",
                "cheme.tea-product-unit",
                f"isbl.scaling is per {s.unit}; the main product is a {main.kind} flow",
                f"give the capacity per {'t' if main.kind == 'material' else 'MWh'}, or "
                "basis.unit and basis.conversion",
                "scaling",
            )
            return None
        ratio = capacity / s.reference.value
        scaled = value * ratio**s.exponent.value
        lines.append(
            self.report.CapexLine(
                "isbl-scaling",
                f"Scaled to {capacity:.4g} {s.unit}/a from {s.reference.value:.4g} {s.unit}/a, "
                f"exponent {s.exponent.value:g}: x {ratio**s.exponent.value:.4g}",
                "scaling",
                scaled - value,
                s.exponent.status,
                f"{s.reference.source}; exponent: {s.exponent.source}",
                s.reference.year,
            )
        )
        return scaled

    def _equipment(self, tea, spec, lines) -> tuple[float | None, str, int]:
        from chemeascode.domains.assessment.equipment_cost import BASIS_FILE, equipment_estimate

        CapexLine = self.report.CapexLine
        result = equipment_estimate(self.root)
        if any(f.level == "error" for f in result.findings):
            first = next(f for f in result.findings if f.level == "error")
            self.problem(
                "error",
                "cheme.tea-capex-source",
                f"isbl.source equipment, but the equipment estimate fails: {first.message}",
                "run cheme assess equipment and fix what it reports",
                "source:",
            )
            return None, "", 0
        currency = result.currency
        year = result.index["year"] if result.index else result.base_year
        # a catalyst's first fill is priced in its price's year, not the cost index's: kept
        # apart so that only what is of the index's year is escalated with it
        fills: dict[int, list] = {}
        for line in result.lines:
            if line.price_year is not None and line.bare_module is not None:
                fills.setdefault(line.price_year, []).append(line)
        indexed = [line for line in result.lines if line.price_year is None]
        bare = sum(line.bare_module or 0.0 for line in indexed)
        value = bare
        lines.append(
            CapexLine(
                "isbl-bare-module",
                f"Bare module cost, {sum(1 for x in indexed if x.bare_module)} items "
                f"({currency} {year})",
                "cheme assess equipment (Turton et al., CAPCOST)",
                bare,
                "",
                BASIS_FILE,
                year,
                currency=currency,
            )
        )
        for fill_year, fill in sorted(fills.items()):
            cost = sum(line.bare_module for line in fill)
            value += cost
            lines.append(
                CapexLine(
                    f"isbl-catalyst-{fill_year}",
                    f"Catalyst first fill, {len(fill)} items ({currency} {fill_year})",
                    "cheme assess equipment, process/catalysts.yaml",
                    cost,
                    "",
                    "process/catalysts.yaml",
                    fill_year,
                    currency=currency,
                )
            )
        purchased_only = [
            line for line in result.lines if line.bare_module is None and line.purchased
        ]
        if purchased_only:
            purchased = sum(line.purchased for line in purchased_only)
            install = spec.purchased_installation
            if install is None:
                self.problem(
                    "warning",
                    "cheme.tea-capex-uncovered",
                    f"{len(purchased_only)} items have a purchased cost but no bare module "
                    f"cost ({purchased:,.0f} {currency} purchased); they count as 0",
                    "give isbl.purchased_installation (installed / purchased), or complete "
                    "their factors in estimate/cost-basis.yaml",
                    "isbl:",
                    [line.tag for line in purchased_only],
                )
            else:
                installed = purchased * install.value
                value += installed
                lines.append(
                    CapexLine(
                        "isbl-purchased-installed",
                        f"Purchased-only items x {install.value:g}, {len(purchased_only)} items",
                        f"{purchased:,.0f} {currency} purchased",
                        installed,
                        install.status,
                        install.source,
                        install.year,
                        currency=currency,
                    )
                )
        own_tags = set()
        for own in result.own_costs:
            own_tags.add(own["tag"])
            if own["currency"] == tea.currency and own["year"] == tea.cost_year:
                lines.append(
                    CapexLine(
                        f"isbl-own-{own['tag']}",
                        f"{own['tag']}: the project's own cost",
                        BASIS_FILE,
                        own["cost"],
                        own["status"] or "",
                        own["source"],
                        own["year"],
                        currency=own["currency"],
                    )
                )
            elif own["currency"] == currency and own["year"] == year:
                # in the estimate's basis: converted with it
                value += own["cost"]
                lines.append(
                    CapexLine(
                        f"isbl-estimate-own-{own['tag']}",
                        f"{own['tag']}: the project's own cost ({currency} {year})",
                        BASIS_FILE,
                        own["cost"],
                        own["status"] or "",
                        own["source"],
                        own["year"],
                        currency=currency,
                    )
                )
            else:
                self.problem(
                    "warning",
                    "cheme.tea-capex-own-cost",
                    f"{own['tag']}: its own cost is in {own['currency']} {own['year']}, neither "
                    f"the TEA's ({tea.currency} {tea.cost_year}) nor the estimate's ({currency} "
                    f"{year}); it is left out",
                    "state it in the TEA's or the estimate's currency and year",
                    "isbl:",
                    [own["tag"]],
                    file=BASIS_FILE,
                )
        # a catalyst fill priced in another currency than the estimate's: counted as it is
        # when that is the TEA's currency and year, as the project's own costs are
        for line in result.lines:
            if line.own_cost is None:
                continue
            own_tags.add(line.tag)
            if line.currency == tea.currency and line.price_year == tea.cost_year:
                lines.append(
                    CapexLine(
                        f"isbl-own-{line.tag}",
                        f"{line.tag}: first fill priced in {line.currency}",
                        "cheme assess equipment, process/catalysts.yaml",
                        line.own_cost,
                        "",
                        "process/catalysts.yaml",
                        line.price_year,
                        currency=line.currency,
                    )
                )
            else:
                self.problem(
                    "warning",
                    "cheme.tea-capex-own-cost",
                    f"{line.tag}: the catalyst first fill is priced in {line.currency} "
                    f"{line.price_year}, the TEA is in {tea.currency} {tea.cost_year} and "
                    f"the estimate in {currency}; it is left out",
                    "price the catalyst in the TEA's currency and cost year, or in "
                    f"{currency} (process/catalysts.yaml)",
                    "isbl:",
                    [line.tag],
                    file="process/catalysts.yaml",
                )
        uncovered = [line.tag for line in result.lines if line.status == "not covered"]
        if uncovered:
            allowance = spec.uncovered_allowance
            self.problem(
                "warning" if allowance is None else "info",
                "cheme.tea-capex-uncovered",
                f"{len(uncovered)} items are not costed (no correlation covers them)"
                + (
                    f"; an allowance of {allowance.value:.0%} of the costed ISBL stands for them"
                    if allowance
                    else " and no allowance is made for them"
                ),
                "cost them in estimate/cost-basis.yaml when their sizes are known"
                + ("" if allowance else ", or give isbl.uncovered_allowance with its source"),
                "isbl:",
                uncovered,
            )
        dropped = [
            line.tag
            for line in result.lines
            if line.bare_module is None
            and not line.purchased
            and line.status != "not covered"
            and not line.status.startswith("excluded")
            and line.tag not in own_tags
        ]
        if dropped:
            self.problem(
                "warning",
                "cheme.tea-capex-uncovered",
                f"{len(dropped)} items carry no cost the ISBL can take: {', '.join(dropped)}",
                "see cheme assess equipment for why",
                "isbl:",
                dropped,
            )
        return value, currency, year

    # -- premises ----------------------------------------------------------------------------

    def premises(self, tea: TeaFile, operation, lines: list[Line], isbl: float) -> Premises:
        fx = tea.fixed_opex
        f = tea.finance
        labour = 0.0
        if fx.labour is not None:
            labour = fx.labour.operators.value * fx.labour.cost_per_operator.value
            if fx.labour.supervision is not None:
                labour *= 1.0 + fx.labour.supervision.value
        events = []
        for e in tea.events:
            first = e.first_year
            if first is None:
                first = max(1, round(e.every_years)) if e.every_years else 1
            events.append(
                model.Event(
                    e.id,
                    e.cost.value if e.cost is not None else e.fraction_of_isbl.value,
                    of_isbl=e.cost is None,
                    every_years=e.every_years,
                    every_hours=e.every_hours,
                    first=first,
                    anchored=e.every_hours is not None and e.first_year is not None,
                    downtime_days=e.downtime_days or 0.0,
                    capital=e.treatment == "capital",
                    skip_last=e.skip_last,
                )
            )
            if first > operation["life"]:
                self.problem(
                    "info",
                    "cheme.tea-event-beyond-life",
                    f"event {e.id} first occurs in operating year {first}, after the "
                    f"{operation['life']} years of the analysis",
                    "check first_year and every_years",
                    f"event:{e.id}",
                    [e.id],
                )
            if e.downtime_days and e.kind == "turnaround":
                self.problem(
                    "info",
                    "cheme.tea-turnaround-hours",
                    f"event {e.id} stops the plant {e.downtime_days:g} days; hours_per_year "
                    "must not count that downtime again",
                    "state in operation.source whether hours_per_year includes turnarounds",
                    f"event:{e.id}",
                    [e.id],
                )
        days = None
        if f.working_capital_days is not None:
            d = f.working_capital_days
            days = model.WorkingCapitalDays(
                feed_inventory=_v(d.feed_inventory),
                product_inventory=_v(d.product_inventory),
                receivables=_v(d.receivables),
                payables=_v(d.payables),
            )
        if f.depreciation_years is not None and f.depreciation_years > operation["life"]:
            self.problem(
                "info",
                "cheme.tea-depreciation",
                f"depreciation over {f.depreciation_years} years, longer than the "
                f"{operation['life']} operating years: the book value left is written off in "
                "the last year",
                "check depreciation_years against life_years",
                "depreciation_years",
            )
        return Premises(
            throughput=tea.uncertainty is not None and tea.uncertainty.rate_mode == "throughput",
            isbl=isbl,
            main=self.main_key,
            hours=operation["hours"],
            life=operation["life"],
            discount_rate=f.discount_rate.value,
            lines=lines,
            osbl=_v(tea.capex.osbl),
            owners_cost=_v(tea.capex.owners_cost),
            contingency=_v(tea.capex.contingency),
            ramp_up=operation["ramp"],
            utilisation=operation["utilisation"],
            batch=operation["batch"],
            maintenance=_v(fx.maintenance),
            labour=labour,
            insurance_tax=_v(fx.insurance_tax),
            overheads=_v(fx.overheads),
            items={item.id: item.value for item in fx.items},
            item_profiles={item.id: path_profile(item, operation["life"]) for item in fx.items},
            events=events,
            tax_rate=_v(f.tax_rate),
            losses=f.losses,
            depreciation_years=f.depreciation_years,
            depreciation=list(f.depreciation) if f.depreciation is not None else None,
            construction=list(f.construction),
            working_capital=_v(f.working_capital),
            working_capital_days=days,
            salvage=_v(f.salvage),
        )

    def describe(self, tea: TeaFile, p: Premises) -> None:
        """Register every remaining input id, then the report's input list in their order."""
        r = self.report
        cur = tea.currency
        for line in p.lines:
            for name in line.scales:
                key = name.removeprefix("rate:")
                m = self.merged.get(key) if name.startswith("rate:") else None
                if m is not None and name not in self.registry:
                    self.registry[name] = Reg(
                        m.per_hour,
                        f"{RATE_UNITS[m.kind]}/h",
                        _weakest(m.provenance),
                        FLOWSHEET_FILE,
                        defaults=False,
                    )
        for line in p.lines:
            if line.rate_input not in self.registry:
                provenance = self._provenance(line.key)
                self.registry[line.rate_input] = Reg(
                    line.rate, f"{line.unit}/h", provenance, FLOWSHEET_FILE, defaults=False
                )
            if line.price_input not in self.registry:
                self.registry[line.price_input] = Reg(
                    line.price, f"{cur}/{line.unit}", "", "", defaults=False
                )
        isbl = tea.capex.isbl
        self.registry["capex:isbl"] = Reg(
            p.isbl,
            cur,
            isbl.value.status if isbl.value else "ASSUMED",
            isbl.value.source
            if isbl.value
            else {"equipment": "cheme assess equipment", "mto": "cheme assess estimate"}[
                isbl.source
            ],
            isbl.uncertainty,
            isbl.swing,
            defaults=False,
        )
        for name, value in (
            ("capex:osbl", tea.capex.osbl),
            ("capex:owners_cost", tea.capex.owners_cost),
            ("capex:contingency", tea.capex.contingency),
            ("opex:maintenance", tea.fixed_opex.maintenance),
            ("opex:insurance_tax", tea.fixed_opex.insurance_tax),
            ("opex:overheads", tea.fixed_opex.overheads),
        ):
            if value is not None:
                self.register(name, value, value.value, "fraction")
        if tea.fixed_opex.labour is not None:
            self.register(
                "opex:labour", tea.fixed_opex.labour.cost_per_operator, p.labour, f"{cur}/a"
            )
        for item in tea.fixed_opex.items:
            self.register(f"opex:{item.id}", item, item.value, f"{cur}/a")
        for e in tea.events:
            amount = e.cost or e.fraction_of_isbl
            self.register(f"event:{e.id}", amount, amount.value, cur if e.cost else "x ISBL")
        op = tea.operation
        self.registry.setdefault(
            "operation:hours_per_year",
            Reg(
                r.hours or 0.0,
                "h/a",
                "",
                r.operation_source,
                op.uncertainty if op else None,
                op.swing if op else None,
                defaults=False,
            ),
        )
        rate = tea.finance.discount_rate
        self.register("finance:discount_rate", rate, rate.value, "fraction", defaults=False)
        d = tea.finance.working_capital_days
        if d is not None:
            for name in ("feed_inventory", "product_inventory", "receivables", "payables"):
                value = getattr(d, name)
                if value is not None:
                    self.register(f"finance:wc:{name}", value, value.value, "days")
        u = tea.uncertainty
        if u is not None and u.rate_mode == "throughput":
            self.registry["operation:throughput"] = Reg(
                1.0, "x the flowsheet", "", "uncertainty.throughput", u.throughput, None, False
            )
        for name in p.inputs():
            reg = self.registry.get(name)
            if reg is not None:
                r.inputs[name] = r.Input(name, reg.value, reg.unit, reg.status, reg.source)

    def _provenance(self, key: str) -> str:
        base = key.split("@")[0].split("~")[0]
        row = next((f for f in self.report.flows if f.key == base), None)
        return row.provenance if row is not None else ""

    def capex_lines(self, tea: TeaFile) -> None:
        r = self.report
        b = r.baseline
        for name, title, basis, value, spec in (
            ("osbl", "OSBL (offsites, utilities)", "x ISBL", b.osbl[0], tea.capex.osbl),
            (
                "owners_cost",
                "Owner's cost",
                "x (ISBL + OSBL)",
                b.owners_cost[0],
                tea.capex.owners_cost,
            ),
            (
                "contingency",
                "Contingency",
                "x (ISBL + OSBL + owner's cost)",
                b.contingency[0],
                tea.capex.contingency,
            ),
        ):
            if spec is None:
                self.problem(
                    "info",
                    "cheme.tea-capex-missing",
                    f"no {name}: the fixed capital holds none",
                    f"give capex.{name} with its source, or 0 with why",
                    "capex:",
                )
                continue
            line = r.CapexLine(
                name,
                title,
                f"{spec.value:g} {basis}",
                float(value),
                spec.status,
                spec.source,
                spec.year,
                currency=tea.currency,
            )
            line.tea_value = float(value)
            r.capex.append(line)

    def opex_lines(self, tea: TeaFile) -> None:
        r = self.report
        b = r.baseline
        p = r.premises
        fc = float(b.fixed_capital[0])
        fx = tea.fixed_opex
        OpexLine = r.OpexLine
        if fx.maintenance is not None:
            m = fx.maintenance
            r.opex.append(
                OpexLine(
                    "maintenance",
                    "Maintenance",
                    f"{m.value:g} x fixed capital",
                    fc * m.value,
                    m.status,
                    m.source,
                    m.year,
                )
            )
        if fx.labour is not None:
            lab = fx.labour
            basis = f"{lab.operators.value:g} operators x {lab.cost_per_operator.value:g}"
            if lab.supervision is not None:
                basis += f" x (1 + {lab.supervision.value:g} supervision)"
            r.opex.append(
                OpexLine(
                    "labour",
                    "Operating labour",
                    basis,
                    p.labour,
                    lab.cost_per_operator.status,
                    lab.cost_per_operator.source,
                    lab.cost_per_operator.year,
                )
            )
        if fx.insurance_tax is not None:
            v = fx.insurance_tax
            r.opex.append(
                OpexLine(
                    "insurance_tax",
                    "Insurance and local taxes",
                    f"{v.value:g} x fixed capital",
                    fc * v.value,
                    v.status,
                    v.source,
                    v.year,
                )
            )
        if fx.overheads is not None:
            v = fx.overheads
            base = p.labour + fc * p.maintenance
            r.opex.append(
                OpexLine(
                    "overheads",
                    "Overheads",
                    f"{v.value:g} x (labour + maintenance)",
                    base * v.value,
                    v.status,
                    v.source,
                    v.year,
                )
            )
        for item in fx.items:
            r.opex.append(
                OpexLine(
                    item.id,
                    item.title or item.id,
                    "per year" + (" (with a price path)" if path_profile(item, 2) else ""),
                    item.value,
                    item.status,
                    item.source,
                    item.year,
                )
            )
        if not r.opex and not tea.variable_opex:
            self.problem(
                "warning",
                "cheme.tea-no-fixed-opex",
                "no fixed operating cost (maintenance, labour, insurance): the cash flow holds "
                "only the flows' cost",
                "give fixed_opex with sources",
                "fixed_opex",
            )

    def event_lines(self, tea: TeaFile) -> None:
        r = self.report
        periodic = r.baseline.flows["periodic"][0]
        capital = r.baseline.flows["capital"][0]
        c = r.baseline.construction_years
        for e, spec in zip(tea.events, r.premises.events, strict=True):
            amount = (
                e.cost.value
                if e.cost is not None
                else e.fraction_of_isbl.value * float(r.baseline.isbl[0])
            )
            r.events.append(
                {
                    "id": e.id,
                    "title": e.title or e.id,
                    "kind": e.kind,
                    "amount": amount,
                    "every_years": e.every_years,
                    "every_hours": e.every_hours,
                    "first_year": spec.first,
                    "downtime_days": e.downtime_days or 0.0,
                    "treatment": e.treatment,
                    "status": (e.cost or e.fraction_of_isbl).status,
                    "source": e.source,
                }
            )
        r.events_total = float(periodic.sum() + capital[c:].sum())

    def decision(self, tea: TeaFile) -> None:
        r = self.report
        d = tea.decision
        if d is None:
            self.problem(
                "warning",
                "cheme.tea-no-decision",
                "no decision: what the analysis must support is not stated, so its detail "
                "cannot be judged against it",
                "give decision: {question, metric, threshold}",
            )
            r.metric, r.threshold = "npv", 0.0
            return
        r.metric = d.metric
        if d.threshold is not None:
            r.threshold = d.threshold
        elif d.metric == "irr":
            r.threshold = tea.finance.discount_rate.value
        else:
            r.threshold = 0.0

    def _target(self) -> float:
        """The decision's threshold in the model's unit."""
        r = self.report
        return r.threshold / r.lcop_factor if r.metric in ("lcop", "cash_cost") else r.threshold

    def _factor(self, metric: str) -> float:
        return self.report.lcop_factor if metric in ("lcop", "cash_cost") else 1.0

    def scenarios(self, tea: TeaFile) -> None:
        r = self.report
        p = r.premises
        known = set(p.inputs()) | {"operation:throughput"}
        for scenario in tea.scenarios:
            scale: dict[str, float] = {}
            prices: dict[str, float] = {}
            for key, value in scenario.prices.items():
                if key == "carbon":
                    targets = [x for x in p.lines if x.price_input == "price:carbon"]
                    if targets:
                        prices.update({x.key: value for x in targets})
                        continue
                targets = [x for x in p.lines if x.key == key or x.price_input == f"price:{key}"]
                factor = self.price_factor.get(key)
                if not targets or factor is None:
                    self.problem(
                        "warning",
                        "cheme.tea-scenario",
                        f"scenario {scenario.id}: {key} is not a priced line; ignored",
                        "use a key of prices: (a flow, flow@component), variable:<id> or carbon",
                        f"scenario:{scenario.id}",
                        [scenario.id],
                    )
                    continue
                for x in targets:
                    prices[x.key] = value * factor
            for name, multiplier in scenario.scale.items():
                if name not in known:
                    self.problem(
                        "warning",
                        "cheme.tea-scenario",
                        f"scenario {scenario.id}: {name} is not an input of the analysis; ignored",
                        f"use one of {', '.join(p.inputs())}",
                        f"scenario:{scenario.id}",
                        [scenario.id],
                    )
                    continue
                scale[name] = scale.get(name, 1.0) * multiplier
            outcome = evaluate(model.with_prices(p, prices) if prices else p, scale)
            values = {
                metric: float(outcome.metric(metric)[0]) * self._factor(metric)
                for metric in ("npv", "irr", "lcop", "cash_cost")
            }
            r.scenarios.append(
                r.ScenarioResult(
                    scenario.id,
                    scenario.title,
                    scenario.source,
                    float(outcome.fixed_capital[0]),
                    values["npv"],
                    values["irr"] if math.isfinite(values["irr"]) else None,
                    values["lcop"] if math.isfinite(values["lcop"]) else None,
                    r.meets(r.metric, values[r.metric])
                    if math.isfinite(values[r.metric])
                    else None,
                    values["cash_cost"] if math.isfinite(values["cash_cost"]) else None,
                )
            )

    def specs(self, tea: TeaFile) -> dict[str, Uncertainty]:
        """The distribution of each input id that has one (its own, else the defaults)."""
        r = self.report
        p = r.premises
        settings = tea.uncertainty
        defaults = settings.defaults if settings else {}
        throughput = settings is not None and settings.rate_mode == "throughput"
        found: dict[str, Uncertainty] = {}
        inputs = set(p.inputs())
        for name in inputs:
            reg = self.registry.get(name)
            if reg is None:
                continue
            if name.startswith("rate:") and reg.source == FLOWSHEET_FILE:
                if throughput:
                    continue
                spec = settings.rates.get(reg.status) if settings else None
            elif reg.uncertainty is not None:
                spec = reg.uncertainty
            else:
                spec = defaults.get(reg.status) if reg.defaults else None
            if spec is not None:
                found[name] = spec
        if throughput and settings.throughput is not None:
            found["operation:throughput"] = settings.throughput
        isbl = tea.capex.isbl
        if isbl.uncertainty is None:
            (wide_low, _), (_, wide_high) = AACE_BOUNDS[r.claimed_class]
            found["capex:isbl"] = Uncertainty(
                distribution="triangular",
                low=1 + wide_low,
                high=1 + wide_high,
                source=f"AACE 18R-97 class {r.claimed_class} accuracy range",
            )
        order = [*p.inputs(), "operation:throughput"]
        return {name: found[name] for name in order if name in found}

    def swings(self, specs: dict[str, Uncertainty], tea: TeaFile) -> dict[str, tuple]:
        default = tea.sensitivity.swing if tea.sensitivity else None
        found = {}
        for name in self.report.premises.inputs():
            reg = self.registry.get(name)
            swing = reg.swing if reg is not None else None
            if swing is not None:
                found[name] = (swing.low, swing.high, "swing")
            elif name in specs:
                low, high = p10_p90(specs[name])
                found[name] = (low, high, "P10/P90")
            elif default is not None:
                found[name] = (default.low, default.high, "default")
        return found

    def sensitivity(self, tea: TeaFile) -> None:
        r = self.report
        p = r.premises
        target = self._target()
        for name in p.inputs():
            if r.metric in ("lcop", "cash_cost") and name == f"price:{p.main}":
                continue  # the LCOP does not depend on the main product's own price
            base = r.inputs.get(name)
            multiplier = break_even(p, name, r.metric, target)
            r.turns.append(
                r.Turn(
                    name,
                    base.value if base else 1.0,
                    base.unit if base else "",
                    multiplier,
                    None if multiplier is None or base is None else base.value * multiplier,
                )
            )
        specs = self.specs(tea)
        swings = self.swings(specs, tea)
        if swings:
            top = tea.sensitivity.top if tea.sensitivity else 10
            bars = tornado_bars(p, swings, r.metric, self._factor(r.metric))
            r.tornado = bars[:top]
        if tea.uncertainty is None:
            return
        units = {
            "fixed_capital": (tea.currency, 1.0),
            "npv": (tea.currency, 1.0),
            "irr": ("fraction", 1.0),
            "lcop": (f"{tea.currency}/{r.lcop_unit}", r.lcop_factor),
            "cash_cost": (f"{tea.currency}/{r.lcop_unit}", r.lcop_factor),
        }
        main = p.line(p.main)
        priced = main is not None and main.price != 0
        if not priced:  # without the main product's revenue they mean nothing
            del units["npv"], units["irr"]
        deterministic = {k: (r.value(k) if r.value(k) is not None else math.nan) for k in units}
        decision = (r.metric, r.threshold) if tea.decision is not None else None
        if decision is not None and decision[0] not in units:
            decision = None
            self.problem(
                "info",
                "cheme.tea-confidence",
                f"no probability of meeting the decision: {tea.decision.metric} needs the main "
                "product's price",
                "price the main product, or take the decision on lcop",
                "decision:",
            )
        r.uncertainty = monte_carlo(
            p,
            specs,
            tea.uncertainty.iterations,
            tea.uncertainty.seed,
            units,
            deterministic,
            decision,
        )
        capital = next((s for s in r.uncertainty.statistics if s.metric == "fixed_capital"), None)
        if capital is not None and capital.p50 > 0:
            (_, narrow_low), (narrow_high, _) = AACE_BOUNDS[r.claimed_class]
            low, high = capital.p10 / capital.p50 - 1, capital.p90 / capital.p50 - 1
            if low > narrow_low or high < narrow_high:
                self.problem(
                    "warning",
                    "cheme.tea-capex-range",
                    f"the fixed capital's P10 to P90 ({low:+.0%} to {high:+.0%} of P50) is "
                    f"narrower than an AACE class {r.claimed_class} estimate can claim "
                    f"({narrow_low:+.0%} to {narrow_high:+.0%} at best)",
                    "widen the capital uncertainty, or define the scope to a finer class",
                    "uncertainty",
                )
        if decision is not None and tea.decision.confidence is not None:
            probability = r.uncertainty.probability or 0.0
            if probability < tea.decision.confidence:
                self.problem(
                    "info",
                    "cheme.tea-confidence",
                    f"P({r.metric} meets {r.threshold:.6g}) = {probability:.1%}, below the "
                    f"{tea.decision.confidence:.1%} the decision asks for",
                    "see the drivers and the break-even values: which evidence would move it",
                    "confidence",
                )

    def unsubsidised(self) -> None:
        """The LCOP without the incentive lines (category incentive)."""
        r = self.report
        p = r.premises
        incentives = [x for x in p.lines if x.category == "incentive"]
        if not incentives:
            return
        outcome = evaluate(p, {x.price_input: 0.0 for x in incentives})
        value = float(outcome.lcop[0]) * r.lcop_factor
        r.lcop_unsubsidised = value if math.isfinite(value) else None

    def unused(self, tea: TeaFile) -> None:
        """Uncertainties and swings given where nothing samples them."""
        paths = []
        isbl = tea.capex.isbl
        for name in (
            "exchange_rate",
            "escalation",
            "location_factor",
            "purchased_installation",
            "uncovered_allowance",
        ):
            v = getattr(isbl, name)
            if v is not None and (v.uncertainty is not None or v.swing is not None):
                paths.append(f"capex.isbl.{name}")
        if isbl.value is not None and (isbl.value.uncertainty or isbl.value.swing):
            paths.append("capex.isbl.value")
        if tea.fixed_opex.labour is not None:
            lab = tea.fixed_opex.labour
            for name in ("operators", "supervision"):
                v = getattr(lab, name)
                if v is not None and (v.uncertainty is not None or v.swing is not None):
                    paths.append(f"fixed_opex.labour.{name}")
        e = tea.emissions
        if e is not None:
            for source in e.sources:
                v = source.captured
                if v is not None and (v.uncertainty is not None or v.swing is not None):
                    paths.append(f"emissions.sources.{source.id}.captured")
            a = e.allocation
            if a is not None and (a.benchmark.uncertainty is not None or a.benchmark.swing):
                paths.append("emissions.allocation.benchmark")
        if isbl.scaling is not None:
            for name in ("reference", "exponent"):
                v = getattr(isbl.scaling, name)
                if v.uncertainty is not None or v.swing is not None:
                    paths.append(f"capex.isbl.scaling.{name}")
        if paths:
            self.problem(
                "info",
                "cheme.tea-uncertainty-unused",
                f"uncertainty or swing given on {', '.join(paths)}: nothing samples them (they "
                "are part of a composite input)",
                "give it on the composite input instead: capex.isbl.uncertainty, "
                "fixed_opex.labour.cost_per_operator",
            )


#: AACE 18R-97 accuracy by class: (low wide, low narrow), (high narrow, high wide), as
#: fractions (the text of :data:`..equipment_cost.AACE_RANGES`).
AACE_BOUNDS = {
    5: ((-0.50, -0.20), (0.30, 1.00)),
    4: ((-0.30, -0.15), (0.20, 0.50)),
    3: ((-0.20, -0.10), (0.10, 0.30)),
    2: ((-0.15, -0.05), (0.05, 0.20)),
    1: ((-0.10, -0.03), (0.03, 0.15)),
}
