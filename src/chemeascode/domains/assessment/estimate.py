"""The estimate of the bulk materials: the take-off priced with the project's unit rates, then
the factor method.

:func:`estimate` takes the take-off rows (:mod:`chemeascode.domains.assessment.mto`) and the
project's ``estimate/rates.yaml`` (:class:`~chemeascode.domains.assessment.schemas.RateFile`):

1. **materials**: each take-off row is priced by the first rate (in file order) of its category
   whose ``where:`` filters match it: ``quantity x rate``. A row no rate matches stays
   unpriced (``cheme.estimate-unpriced``);
2. **direct factors**: ``factor x`` the material cost of the categories in ``applies_to``
   (installation, erection, testing); direct cost = materials + direct factors;
3. **indirect factors**: ``factor x`` the direct cost (engineering, construction management);
4. **contingency**: ``factor x`` (direct + indirect).

cheme-as-code holds no prices: every number comes from the rates file, with its status, source and
year. Rates from another year than ``cost_year`` are used as they are (no escalation) and
reported. The estimate covers what the take-off counts: bulk materials of the 3D model, not
equipment, instruments, electrical or civil works beyond the counted concrete.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from chemeascode.domains.assessment.mto import (
    MtoRow,
    TakeOff,
    matches,
    model_takeoff,
)
from chemeascode.domains.assessment.schemas import Rate, RateFile
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

RATES_FILE = "estimate/rates.yaml"
ESTIMATE_CSV = "estimate/estimate.csv"
ESTIMATE_MD = "estimate/estimate.md"
COLUMNS = (
    "section",
    "id",
    "description",
    "quantity",
    "unit",
    "rate",
    "basis",
    "cost",
    "status",
    "source",
    "year",
)


@dataclass(frozen=True)
class EstimateLine:
    """One priced line: a take-off row times its rate, or a factor times its base."""

    #: ``material``, ``direct``, ``indirect`` or ``contingency``.
    section: str
    #: The take-off row's key, or the factor's id.
    id: str
    description: str
    #: The row's quantity, or the factor's base cost.
    quantity: float
    unit: str
    #: The unit rate, or the factor.
    rate: float | None
    #: The rate's or factor's id; empty for an unpriced row.
    basis: str
    cost: float | None
    status: str = ""
    source: str = ""
    year: int | None = None

    def csv_row(self) -> dict[str, str]:
        return {
            "section": self.section,
            "id": self.id,
            "description": self.description,
            "quantity": _money(self.quantity) if self.section != "material" else _q(self.quantity),
            "unit": self.unit,
            "rate": "" if self.rate is None else f"{self.rate:g}",
            "basis": self.basis,
            "cost": "" if self.cost is None else _money(self.cost),
            "status": self.status,
            "source": self.source,
            "year": "" if self.year is None else str(self.year),
        }


def _q(value: float) -> str:
    return f"{round(value, 3):g}"


def _money(value: float) -> str:
    return f"{value:.2f}"


@dataclass
class Estimate:
    """The priced take-off and the factor method's lines."""

    currency: str = ""
    cost_year: int | None = None
    example: bool = False
    lines: list[EstimateLine] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    model_sha256: str | None = None

    def total(self, *sections: str) -> float:
        return round(sum(line.cost or 0.0 for line in self.lines if line.section in sections), 2)

    def totals(self) -> dict[str, float]:
        materials = self.total("material")
        direct = self.total("material", "direct")
        indirect = self.total("indirect")
        contingency = self.total("contingency")
        return {
            "materials": materials,
            "direct": direct,
            "indirect": indirect,
            "contingency": contingency,
            "total": round(direct + indirect + contingency, 2),
            "unpriced_rows": sum(1 for line in self.lines if line.cost is None),
        }


def rate_matches(rate: Rate, row: MtoRow) -> bool:
    """Whether *rate* (anything with ``category`` and ``where``) counts take-off *row*."""
    if rate.category != row.category:
        return False
    where = rate.where
    if where.dn_min is not None and (row.dn is None or row.dn < where.dn_min):
        return False
    if where.dn_max is not None and (row.dn is None or row.dn > where.dn_max):
        return False
    return (
        matches(where.item, row.item)
        and matches(where.pipe_class, row.pipe_class)
        and matches(where.spec, row.spec)
        and matches(where.group, row.group)
    )


def estimate(takeoff: TakeOff, rates: RateFile, rates_file: str = RATES_FILE) -> Estimate:
    """Price *takeoff* with *rates* and apply its factors."""
    result = Estimate(rates.currency, rates.cost_year, rates.example, [], [], takeoff.model_sha256)
    used: set[str] = set()
    unpriced: list[str] = []
    material_by_category: dict[str, float] = {}
    for row in takeoff.rows:
        rate = next((r for r in rates.rates if rate_matches(r, row)), None)
        if rate is None:
            unpriced.append(row.key)
            result.lines.append(
                EstimateLine("material", row.key, row.item, row.quantity, row.unit, None, "", None)
            )
            continue
        used.add(rate.id)
        cost = round(row.quantity * rate.rate, 2)
        material_by_category[row.category] = material_by_category.get(row.category, 0.0) + cost
        result.lines.append(
            EstimateLine(
                "material",
                row.key,
                row.item,
                row.quantity,
                row.unit,
                rate.rate,
                rate.id,
                cost,
                rate.status,
                rate.source,
                rate.year,
            )
        )
    materials = sum(material_by_category.values())
    direct_extra = 0.0
    for factor in (f for f in rates.factors if f.kind == "direct"):
        base = (
            sum(material_by_category.get(c, 0.0) for c in factor.applies_to)
            if factor.applies_to
            else materials
        )
        cost = round(base * factor.factor, 2)
        direct_extra += cost
        result.lines.append(_factor_line(factor, base, cost, rates.currency))
    direct = materials + direct_extra
    indirect = 0.0
    for factor in (f for f in rates.factors if f.kind == "indirect"):
        cost = round(direct * factor.factor, 2)
        indirect += cost
        result.lines.append(_factor_line(factor, direct, cost, rates.currency))
    for factor in (f for f in rates.factors if f.kind == "contingency"):
        base = direct + indirect
        result.lines.append(
            _factor_line(factor, base, round(base * factor.factor, 2), rates.currency)
        )

    if rates.example:
        result.findings.append(
            Finding(
                rates_file,
                "warning",
                "cheme.estimate-example-rates",
                "the rates are an example (example: true): the estimate prices nothing real",
                hint="replace every rate and factor with the project's own, each with its "
                "status, source and year, and remove example: true",
            )
        )
    if unpriced:
        shown = ", ".join(unpriced[:5]) + (
            f" and {len(unpriced) - 5} more" if len(unpriced) > 5 else ""
        )
        result.findings.append(
            Finding(
                rates_file,
                "warning",
                "cheme.estimate-unpriced",
                f"{len(unpriced)} take-off rows have no rate: {shown}",
                hint="add a rate of that category whose where: matches them (category, item, "
                "DN range, class, spec, group)",
            )
        )
    other_year = sorted(
        {r.id for r in rates.rates if r.id in used and r.year != rates.cost_year}
        | {f.id for f in rates.factors if f.year != rates.cost_year}
    )
    if other_year:
        result.findings.append(
            Finding(
                rates_file,
                "info",
                "cheme.estimate-rate-year",
                f"priced in another year than cost_year {rates.cost_year}, used without "
                f"escalation: {', '.join(other_year)}",
                ids=other_year,
                hint="escalate the rate to the cost year by an index and record it in the "
                "rate's source, or accept the difference in the estimate's basis",
            )
        )
    unused = [r.id for r in rates.rates if r.id not in used]
    if unused:
        result.findings.append(
            Finding(
                rates_file,
                "info",
                "cheme.estimate-rate-unused",
                f"rates no take-off row uses: {', '.join(unused)}",
                ids=unused,
                hint="an earlier rate of the category may match first; order rates from the "
                "most specific to the most general",
            )
        )
    return result


def _factor_line(factor: Any, base: float, cost: float, currency: str) -> EstimateLine:
    on = f" on {', '.join(factor.applies_to)}" if factor.applies_to else ""
    return EstimateLine(
        factor.kind,
        factor.id,
        (factor.title or factor.id) + on,
        round(base, 2),
        currency,
        factor.factor,
        factor.id,
        cost,
        factor.status,
        factor.source,
        factor.year,
    )


# -- formatting ----------------------------------------------------------------------------------


def estimate_csv(result: Estimate) -> str:
    """The estimate as CSV: one line per priced row and factor (columns :data:`COLUMNS`)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(line.csv_row() for line in result.lines)
    return buffer.getvalue()


def estimate_markdown(result: Estimate, rates_file: str = RATES_FILE) -> str:
    """The estimate as a Markdown report: the totals, the factors, then every priced row."""
    cur = result.currency
    t = result.totals()
    lines = [
        "# Estimate (bulk materials, factor method)",
        "",
    ]
    if result.example:
        lines += [
            "> **EXAMPLE RATES.** `estimate/rates.yaml` is marked `example: true`: these "
            "numbers price nothing. Replace them with the project's own rates.",
            "",
        ]
    lines += [
        f"Generated by `cheme assess estimate` from the take-off of `{LAYOUT_MODEL_FILE}` "
        f"(model output_sha256 `{result.model_sha256 or 'unknown'}`) and `{rates_file}`. "
        f"Cost year {result.cost_year}, currency {cur}. Every rate and factor carries its "
        "status, source and year; the estimate is only as good as they are.",
        "",
        "## Summary",
        "",
        f"| | {cur} |",
        "|---|---:|",
        f"| materials | {_money(t['materials'])} |",
        f"| direct (materials and direct factors) | {_money(t['direct'])} |",
        f"| indirect | {_money(t['indirect'])} |",
        f"| contingency | {_money(t['contingency'])} |",
        f"| **total** | **{_money(t['total'])}** |",
        "",
        f"Unpriced take-off rows: {t['unpriced_rows']}.",
        "",
        "## Factors",
        "",
        f"| section | factor | description | base ({cur}) | cost ({cur}) | status | source "
        "| year |",
        "|---|---:|---|---:|---:|---|---|---|",
    ]
    for line in result.lines:
        if line.section == "material":
            continue
        lines.append(
            f"| {line.section} | {line.rate:g} | {line.description} | {_money(line.quantity)} | "
            f"{_money(line.cost or 0.0)} | {line.status} | {line.source} | {line.year} |"
        )
    lines += [
        "",
        "## Materials",
        "",
        f"| row | quantity | unit | rate ({cur}) | cost ({cur}) | rate id | status | year |",
        "|---|---:|---|---:|---:|---|---|---|",
    ]
    for line in result.lines:
        if line.section != "material":
            continue
        rate = "" if line.rate is None else f"{line.rate:g}"
        cost = "unpriced" if line.cost is None else _money(line.cost)
        lines.append(
            f"| {line.id} | {_q(line.quantity)} | {line.unit} | {rate} | {cost} | {line.basis} "
            f"| {line.status} | {line.year or ''} |"
        )
    if result.findings:
        lines += ["", "## Findings", ""] + [f"- {f.format()}" for f in result.findings]
    return "\n".join(lines) + "\n"


# -- the Python entry point ---------------------------------------------------------------------


def load_rates(text: str | None, rates_file: str = RATES_FILE) -> tuple[RateFile | None, list]:
    """The parsed rates file, or None with the finding that says why."""
    if text is None:
        return None, [
            Finding(
                rates_file,
                "error",
                "cheme.estimate-no-rates",
                f"no {rates_file}: nothing to price the take-off with",
                hint="write the project's unit rates and factors there (cheme schema rates; "
                "cheme init ships an example)",
            )
        ]
    try:
        return RateFile.model_validate(yaml.safe_load(text) or {}), []
    except (ValidationError, yaml.YAMLError) as failure:
        first = str(failure).splitlines()
        return None, [
            Finding(
                rates_file,
                "error",
                "cheme.estimate-no-rates",
                f"{rates_file} does not load: {' '.join(first[:3])}",
                hint="cheme validate names the line",
            )
        ]


def texts_estimate(model_text: str | None, rates_text: str | None) -> Estimate:
    """The estimate from a model file's and a rates file's texts (None: absent)."""
    takeoff = model_takeoff(model_text)
    rates, problems = load_rates(rates_text)
    if rates is None or any(f.level == "error" for f in takeoff.findings):
        return Estimate(findings=takeoff.findings + problems, model_sha256=takeoff.model_sha256)
    result = estimate(takeoff, rates)
    result.findings = takeoff.findings + result.findings
    return result


@dataclass
class EstimateReport:
    """The estimate of a plant repository, with what it was computed from."""

    root: Path
    estimate: Estimate
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def findings(self) -> list[Finding]:
        return self.estimate.findings

    @property
    def loaded(self) -> bool:
        return not any(f.level == "error" for f in self.findings)

    def payload(self) -> dict[str, Any]:
        """The document ``cheme assess estimate --json`` prints."""
        return estimate_payload(self.estimate) | {"source": self.source.as_dict()}

    def to_json(self) -> str:
        return json.dumps(self.payload(), indent=2)


def estimate_payload(result: Estimate) -> dict[str, Any]:
    return {
        "currency": result.currency,
        "cost_year": result.cost_year,
        "example": result.example,
        "model_sha256": result.model_sha256,
        "totals": result.totals() if result.lines else {},
        "lines": [asdict(line) for line in result.lines],
        "findings": [asdict(f) for f in result.findings],
    }


def _read(root: Path, name: str) -> str | None:
    path = root / name
    return path.read_text(encoding="utf-8") if path.is_file() else None


def estimate_report(root: Path) -> EstimateReport:
    """The estimate of the model and ``estimate/rates.yaml`` under *root*."""
    root = Path(root)
    result = texts_estimate(_read(root, LAYOUT_MODEL_FILE), _read(root, RATES_FILE))
    return EstimateReport(root, result, source_revision(root, [LAYOUT_MODEL_FILE, RATES_FILE]))
