"""The techno-economic analysis: cash flow by hand, findings, uncertainty, command, gate, API.

The plant is ``examples/process-blocks``: per hour 1000 kg of feed and 350 kWh of steam in,
400 kg of product and 600 kg of waste water out.
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.schemas import Uncertainty
from chemeascode.domains.assessment.lca.uncertainty import sample
from chemeascode.domains.assessment.tea.gates import tea_gate
from chemeascode.domains.assessment.tea.model import Premises, break_even, evaluate
from chemeascode.domains.assessment.tea.report import (
    CASHFLOW_CSV,
    TEA_FILE,
    TEA_MD,
    UNCERTAINTY_CSV,
    compare,
    outputs,
    tea_report,
)
from chemeascode.domains.assessment.tea.uncertainty import p10_p90
from chemeascode.foundation.schemas.checks import Check
from chemeascode.interfaces.cli import app
from tests.conftest import git

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
FLOWSHEET = "process/flowsheet.yaml"
runner = CliRunner()


def _v(value: float, **extra) -> dict:
    return {"value": value, "source": "test", **extra}


def premises(**extra) -> dict:
    data = {
        "schema": "cheme/tea/v1",
        "kind": "tea",
        "currency": "EUR",
        "cost_year": 2025,
        "decision": {"question": "Proceed to basic engineering?", "metric": "npv"},
        "basis": {
            "product": "PROD",
            "specification": "95 wt% ethanol",
            "boundary": "feed to product tank",
            "location": "NL",
        },
        "capex": {
            "isbl": {"source": "given", "value": _v(5.0e6, year=2025)},
            "osbl": _v(0.3),
            "owners_cost": _v(0.1),
            "contingency": _v(0.2),
        },
        "operation": {"hours_per_year": 8000, "life_years": 20, "source": "test"},
        "prices": [
            {"key": "feed:FEED", "value": 50, "unit": "t", "source": "test", "year": 2025},
            {"key": "feed:STEAM", "value": 30, "unit": "MWh", "source": "test", "year": 2025},
            {"key": "product:PROD", "value": 900, "unit": "t", "source": "test", "year": 2025},
        ],
        "free": [{"key": "product:WATER", "reason": "to the site's treatment"}],
        "fixed_opex": {"maintenance": _v(0.03)},
        "finance": {"discount_rate": _v(0.08)},
    }
    data.update(extra)
    return data


def write(root: Path, data: dict) -> None:
    (root / "estimate").mkdir(exist_ok=True)
    (root / TEA_FILE).write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    write(root, premises())
    return root


def rules(report) -> set[str]:
    return {f.rule for f in report.findings}


# -- the cash flow -------------------------------------------------------------------------------


def simple(**extra) -> Premises:
    """1000 spent in one year, then 3 years of 500 (1 kg/h x 100 h x 5), at 10 %."""
    values = dict(
        isbl=1000.0,
        rates={"product:P": 1.0},
        prices={"product:P": 5.0},
        main="product:P",
        hours=100.0,
        life=3,
        discount_rate=0.1,
    )
    values.update(extra)
    return Premises(**values)


def test_npv_irr_lcop_and_payback_by_hand():
    outcome = evaluate(simple())
    annuity = sum(1.1**-t for t in (1, 2, 3))
    assert outcome.npv[0] == pytest.approx(-1000 + 500 * annuity)
    rate = outcome.irr[0]
    assert -1000 + sum(500 / (1 + rate) ** t for t in (1, 2, 3)) == pytest.approx(0, abs=1e-6)
    # the price at which the NPV is zero
    assert outcome.lcop[0] == pytest.approx(1000 / (100 * annuity))
    # cumulative: -1000, -545.5, -132.2, +243.4: zero 0.352 into the third year
    assert outcome.payback() == pytest.approx(2 + 132.2314 / (500 / 1.1**3), abs=1e-3)


def test_tax_depreciation_working_capital_and_schedule_by_hand():
    p = simple(
        tax_rate=0.25,
        construction=[0.4, 0.6],
        working_capital=0.1,
        salvage=0.05,
        maintenance=0.02,
        osbl=0.5,
    )
    o = evaluate(p)
    fc = 1500.0  # ISBL 1000 + OSBL 500
    assert o.fixed_capital[0] == pytest.approx(fc)
    fixed = 0.02 * fc
    depreciation = fc / 3
    after_tax = (500 - fixed) - 0.25 * (500 - fixed - depreciation)
    # the last year recovers the working capital and takes the salvage, taxed above the book
    # value (0 after full depreciation)
    last = after_tax + 0.1 * fc + 0.05 * fc - 0.25 * 0.05 * fc
    cash = [-0.4 * fc, -0.6 * fc - 0.1 * fc, after_tax, after_tax, last]
    assert o.flows["cash_flow"][0] == pytest.approx(cash)
    assert o.npv[0] == pytest.approx(sum(c / 1.1**t for t, c in enumerate(cash)))
    table = o.table()
    assert [row["phase"] for row in table] == ["construction"] * 2 + ["operation"] * 3
    # a tax loss counts as a credit: LCOP still makes the NPV zero
    at_lcop = evaluate(p, {"price:product:P": o.lcop[0] / 5.0})
    assert at_lcop.npv[0] == pytest.approx(0, abs=1e-6)


def test_ramp_up_scales_the_flows_of_the_first_years():
    o = evaluate(simple(ramp_up=[0.5]))
    assert o.flows["revenue"][0].tolist() == pytest.approx([0, 250, 500, 500])


def test_break_even_turns_the_metric():
    p = simple()
    m = break_even(p, "capex:isbl", "npv", 0.0)
    assert evaluate(p, {"capex:isbl": m}).npv[0] == pytest.approx(0, abs=1e-6)
    rate = break_even(p, "finance:discount_rate", "npv", 0.0) * 0.1
    assert rate == pytest.approx(evaluate(p).irr[0], rel=1e-6)
    # no price makes a plant without revenue pay
    assert break_even(simple(prices={}), "capex:isbl", "npv", 0.0) is None


def test_p10_p90_matches_the_sampled_percentiles():
    rng = np.random.default_rng(3)
    for spec in (
        Uncertainty(gsd2=1.5),
        Uncertainty(distribution="normal", cv=0.2),
        Uncertainty(distribution="triangular", low=0.5, high=2.0),
        Uncertainty(distribution="uniform", low=0.8, high=1.3),
    ):
        drawn = sample(spec, 200_000, rng)
        low, high = p10_p90(spec)
        assert np.percentile(drawn, 10) == pytest.approx(low, rel=0.01)
        assert np.percentile(drawn, 90) == pytest.approx(high, rel=0.01)


# -- the report ----------------------------------------------------------------------------------


def test_report_of_the_example(blocks: Path):
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    res = report.results()
    assert res["fixed_capital"] == pytest.approx(5e6 * 1.3 * 1.1 * 1.2)
    # 400 kg/h x 8000 h x 0.9 /kg; feed 1000 kg/h x 0.05; steam 350 kWh/h x 0.03
    assert res["revenue_per_year"] == pytest.approx(400 * 8000 * 0.9)
    assert res["variable_cost_per_year"] == pytest.approx(8000 * (1000 * 0.05 + 350 * 0.03))
    assert report.lcop_unit == "t"
    # the LCOP is where the product's price turns the NPV
    turn = next(t for t in report.turns if t.input == "price:product:PROD")
    assert turn.value == pytest.approx(res["lcop"], rel=1e-6)
    assert report.meets() is (res["npv"] >= 0)
    text = outputs(report)[TEA_MD]
    assert "## What would change the decision" in text
    assert "free: to the site's treatment" in text
    assert UNCERTAINTY_CSV not in outputs(report)


@pytest.mark.parametrize(
    ("change", "rule", "level"),
    [
        ({"free": []}, "cheme.tea-price-missing", "warning"),
        ({"decision": None}, "cheme.tea-no-decision", "warning"),
        ({"example": True}, "cheme.tea-example", "warning"),
        ({"fixed_opex": {}}, "cheme.tea-no-fixed-opex", "warning"),
        ({"operation": None}, "cheme.tea-no-operation", "error"),
        ({"case": "nope"}, "cheme.tea-case", "error"),
    ],
)
def test_findings(blocks: Path, change: dict, rule: str, level: str):
    write(blocks, premises(**change))
    found = [f for f in tea_report(blocks).findings if f.rule == rule]
    assert found and found[0].level == level
    assert found[0].file and found[0].hint


def test_a_price_must_fit_its_flow(blocks: Path):
    data = premises()
    data["prices"][1]["unit"] = "t"  # steam is an energy flow
    data["prices"].append({"key": "feed:NOPE", "value": 1, "unit": "kg", "source": "test"})
    write(blocks, data)
    report = tea_report(blocks)
    assert not report.loaded
    assert {"cheme.tea-price-unit", "cheme.tea-price-unknown"} <= rules(report)


def test_price_of_another_year_is_reported_not_escalated(blocks: Path):
    data = premises()
    data["prices"][0]["year"] = 2022
    write(blocks, data)
    found = [f for f in tea_report(blocks).findings if f.rule == "cheme.tea-price-year"]
    assert found[0].ids == ["feed:FEED"] and found[0].line


def test_estimate_class_against_the_stage(blocks: Path):
    data = premises()
    data["capex"]["isbl"]["estimate_class"] = 3  # the example plant is at concept
    write(blocks, data)
    report = tea_report(blocks)
    assert report.stage == "concept" and report.expected_class == 5
    assert "finer than a concept stage supports" in next(
        f.message for f in report.findings if f.rule == "cheme.tea-class-stage"
    )
    assert tea_gate(blocks, ["class-stage"])
    data["capex"]["isbl"]["estimate_class"] = 5
    write(blocks, data)
    assert "cheme.tea-class-stage" not in rules(tea_report(blocks))
    assert tea_gate(blocks, ["class-stage"]) == []


def test_operation_from_the_lca(blocks: Path):
    write(blocks, premises(operation=None))
    (blocks / "lca").mkdir(exist_ok=True)
    (blocks / "lca" / "lca.yaml").write_text(
        "schema: cheme/lca/v1\nkind: lca\nfunctional_unit: {product: PROD}\n"
        "operation: {hours_per_year: 8000, life_years: 20, source: test}\n",
        encoding="utf-8",
    )
    report = tea_report(blocks)
    assert report.loaded and report.hours == 8000 and report.life == 20
    assert "cheme.tea-operation-from-lca" in rules(report)
    write(blocks, premises(operation={"hours_per_year": 7000, "life_years": 20, "source": "test"}))
    assert "cheme.tea-basis-mismatch" in rules(tea_report(blocks))


def test_lcop_decision_and_scenarios(blocks: Path):
    data = premises(
        decision={"question": "Is the product cheap enough?", "metric": "lcop", "threshold": 2000},
        scenarios=[
            {"id": "dear-feed", "prices": {"feed:FEED": 100}},
            {"id": "overrun", "scale": {"capex:isbl": 1.3, "capex:nope": 2}},
        ],
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.metric == "lcop" and report.meets() is True
    dear, overrun = report.scenarios
    assert dear.lcop > report.value("lcop") and overrun.fixed_capital > report.value(
        "fixed_capital"
    )
    assert any("capex:nope" in f.message for f in report.findings if f.rule == "cheme.tea-scenario")
    # the LCOP does not depend on the product's own price: no break-even for it
    assert "price:product:PROD" not in {t.input for t in report.turns}


def test_monte_carlo_is_reproducible_and_ranks_the_drivers(blocks: Path):
    data = premises(
        uncertainty={"iterations": 400, "seed": 7, "defaults": {"ASSUMED": {"gsd2": 1.2}}},
        decision={"question": "Proceed to basic engineering?", "metric": "npv", "confidence": 0.9},
    )
    write(blocks, data)
    first, second = tea_report(blocks), tea_report(blocks)
    assert outputs(first)[UNCERTAINTY_CSV] == outputs(second)[UNCERTAINTY_CSV]
    stats = {s.metric: s for s in first.uncertainty.statistics}
    assert stats["npv"].p10 < stats["npv"].p50 < stats["npv"].p90
    # no isbl uncertainty given: the AACE class 5 range spreads it
    assert stats["fixed_capital"].p90 / stats["fixed_capital"].p10 > 1.5
    assert stats["npv"].sensitivity[0][0] in ("capex:isbl", "price:product:PROD")
    assert 0 <= first.uncertainty.probability <= 1
    assert first.tornado and first.tornado[0].width >= first.tornado[-1].width


def test_a_capital_range_narrower_than_the_class_is_reported(blocks: Path):
    data = premises(uncertainty={"iterations": 200})
    data["capex"]["isbl"]["uncertainty"] = {"gsd2": 1.05}
    write(blocks, data)
    assert "cheme.tea-capex-range" in rules(tea_report(blocks))


def test_isbl_from_the_equipment_estimate(blocks: Path):
    (blocks / "equipment").mkdir(exist_ok=True)
    items = [
        {
            "tag": "V-1",
            "type": "PressureVessel",
            "design_pressure_barg": 10,
            "material": "CS",
            "dimensions": {"diameter": 2.0, "height": 3.1830989},
        },
        {"tag": "X-1", "type": "Equipment"},
    ]
    (blocks / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": items}), encoding="utf-8"
    )
    (blocks / "estimate" / "cost-basis.yaml").write_text(
        "cost_index: {value: 794, year: 2025, source: test}\nestimate_class: 5\n",
        encoding="utf-8",
    )
    data = premises()
    data["capex"]["isbl"] = {"source": "equipment"}
    write(blocks, data)
    report = tea_report(blocks)
    assert "cheme.tea-currency" in rules(report) and not report.loaded  # USD, no rate

    data["capex"]["isbl"] = {
        "source": "equipment",
        "exchange_rate": _v(0.9),
        "uncovered_allowance": _v(0.5),
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    from chemeascode.domains.assessment.equipment_cost import equipment_estimate

    bare = sum(line.bare_module or 0 for line in equipment_estimate(blocks).lines)
    assert bare > 0
    assert report.results()["isbl"] == pytest.approx(bare * 0.9 * 1.5)
    uncovered = [f for f in report.findings if f.rule == "cheme.tea-capex-uncovered"]
    assert uncovered and "X-1" in uncovered[0].ids


def test_catalyst_fills_keep_their_price_year(blocks: Path, monkeypatch):
    from chemeascode.domains.assessment import equipment_cost
    from chemeascode.domains.assessment.equipment_cost import CostLine, EquipmentEstimate

    def estimate(_root):
        return EquipmentEstimate(
            lines=[
                CostLine("V-1", "PressureVessel", purchased=400.0, bare_module=1000.0),
                CostLine("R-1/catalyst", "catalyst fill", bare_module=100.0, price_year=2020),
                CostLine("R-2/catalyst", "catalyst fill", bare_module=10.0, price_year=2024),
                CostLine("R-3/catalyst", "catalyst fill", bare_module=1.0, price_year=2025),
            ],
            index={"value": 800, "year": 2024, "source": "test"},
        )

    monkeypatch.setattr(equipment_cost, "equipment_estimate", estimate)
    data = premises(currency="USD")
    data["capex"]["isbl"] = {"source": "equipment", "escalation": _v(1.1)}
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    # the bare module and the 2024 fill escalate with the index; the 2020 and 2025 fills do not
    assert report.results()["isbl"] == pytest.approx((1000 + 10) * 1.1 + 100 + 1)
    ids = {line.id: line for line in report.capex}
    assert ids["isbl-bare-module"].value == 1000 and ids["isbl-catalyst-2020"].year == 2020
    stray = [f for f in report.findings if f.rule == "cheme.tea-cost-year"]
    assert len(stray) == 1 and "2020" in stray[0].message and "2025" not in stray[0].message[:40]


def test_a_catalyst_fill_in_the_teas_currency_counts_as_it_is(blocks: Path, monkeypatch):
    # a fill priced in EUR is in none of the estimate's USD totals; a EUR TEA of the price's
    # year counts it unconverted, a USD TEA leaves it out with a warning
    from chemeascode.domains.assessment import equipment_cost
    from chemeascode.domains.assessment.equipment_cost import CostLine, EquipmentEstimate

    def estimate(_root):
        fill = CostLine("R-1/catalyst", "catalyst fill", status="own currency EUR")
        fill.own_cost, fill.currency, fill.price_year = 100000.0, "EUR", 2025
        return EquipmentEstimate(
            lines=[CostLine("V-1", "PressureVessel", purchased=4e5, bare_module=1e6), fill],
            index={"value": 800, "year": 2025, "source": "test"},
        )

    monkeypatch.setattr(equipment_cost, "equipment_estimate", estimate)
    data = premises()
    data["capex"]["isbl"] = {"source": "equipment", "exchange_rate": _v(0.9)}
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.results()["isbl"] == pytest.approx(1e6 * 0.9 + 100000)
    assert {line.id for line in report.capex} >= {"isbl-own-R-1/catalyst"}
    assert "cheme.tea-capex-own-cost" not in rules(report)

    data = premises(currency="USD")
    data["capex"]["isbl"] = {"source": "equipment"}
    write(blocks, data)
    report = tea_report(blocks)
    assert report.results()["isbl"] == pytest.approx(1e6)
    left_out = [f for f in report.findings if f.rule == "cheme.tea-capex-own-cost"]
    assert left_out and left_out[0].ids == ["R-1/catalyst"] and "EUR 2025" in left_out[0].message


def _takeoff(monkeypatch, *lines):
    from chemeascode.domains.assessment import estimate as estimate_module
    from chemeascode.domains.assessment.estimate import Estimate, EstimateReport

    def report(root):
        return EstimateReport(root, Estimate("EUR", 2025, False, list(lines)))

    monkeypatch.setattr(estimate_module, "estimate_report", report)


def test_mto_isbl_reports_the_take_off_rows_without_a_rate(blocks: Path, monkeypatch):
    # an unpriced row counts 0 in the estimate's totals: the TEA says so, and the allowance
    # stands for it as for the equipment source
    from chemeascode.domains.assessment.estimate import EstimateLine

    _takeoff(
        monkeypatch,
        EstimateLine("material", "pipe|DN100", "pipe", 100.0, "m", 50.0, "r1", 5000.0),
        EstimateLine("indirect", "eng", "engineering", 5000.0, "EUR", 0.2, "f1", 1000.0),
        EstimateLine("material", "valve|DN300", "BallValve", 20.0, "ea", None, "", None),
    )
    data = premises()
    data["capex"]["isbl"] = {"source": "mto"}
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.results()["isbl"] == pytest.approx(6000)
    uncovered = [f for f in report.findings if f.rule == "cheme.tea-capex-uncovered"]
    assert len(uncovered) == 1 and uncovered[0].level == "warning"
    assert uncovered[0].ids == ["valve|DN300"] and "valve|DN300" in uncovered[0].message

    data["capex"]["isbl"]["uncovered_allowance"] = _v(0.25)
    write(blocks, data)
    report = tea_report(blocks)
    assert report.results()["isbl"] == pytest.approx(6000 * 1.25)
    assert {line.id: line.value for line in report.capex}["isbl-uncovered"] == pytest.approx(1500)
    assert [f.level for f in report.findings if f.rule == "cheme.tea-capex-uncovered"] == ["info"]


def test_mto_isbl_with_every_row_priced_has_no_uncovered_finding(blocks: Path, monkeypatch):
    from chemeascode.domains.assessment.estimate import EstimateLine

    _takeoff(
        monkeypatch,
        EstimateLine("material", "pipe|DN100", "pipe", 100.0, "m", 50.0, "r1", 5000.0),
    )
    data = premises()
    data["capex"]["isbl"] = {"source": "mto"}
    write(blocks, data)
    report = tea_report(blocks)
    assert report.results()["isbl"] == pytest.approx(5000)
    assert "cheme.tea-capex-uncovered" not in rules(report)


def _lca_prices(root: Path, method: str, prices: dict) -> None:
    (root / "lca").mkdir(exist_ok=True)
    allocation = {"method": method, "coproducts": list(prices), "prices": prices}
    (root / "lca" / "lca.yaml").write_text(
        yaml.safe_dump(
            {
                "schema": "cheme/lca/v1",
                "kind": "lca",
                "functional_unit": {"product": "PROD"},
                "allocation": allocation,
            }
        ),
        encoding="utf-8",
    )


def test_product_prices_are_checked_against_the_lca_allocation(blocks: Path):
    data = premises(free=[])
    data["prices"].append(
        {"key": "product:WATER", "value": 450, "unit": "t", "source": "test", "year": 2025}
    )
    write(blocks, data)
    # the same ratio in another currency: no finding
    _lca_prices(blocks, "economic", {"PROD": 2.0, "WATER": 1.0})
    assert "cheme.tea-lca-price-mismatch" not in rules(tea_report(blocks))
    # a 50:1 ratio there, 2:1 here
    _lca_prices(blocks, "economic", {"PROD": 1.0, "WATER": 0.02})
    found = [f for f in tea_report(blocks).findings if f.rule == "cheme.tea-lca-price-mismatch"]
    assert found[0].level == "warning" and "WATER/PROD 0.5 here, 0.02" in found[0].message
    # priced in the LCA, free here; only compared there: info
    write(blocks, premises())
    _lca_prices(blocks, "mass", {"PROD": 1.0, "WATER": 0.5})
    found = [f for f in tea_report(blocks).findings if f.rule == "cheme.tea-lca-price-mismatch"]
    assert found[0].level == "info" and "WATER 0.5 in lca/lca.yaml, free or unpriced here" in (
        found[0].message
    )


# -- comparison, command, gate, API --------------------------------------------------------------


def test_compare_names_the_premises_not_shared(blocks: Path, tmp_path: Path):
    other = tmp_path / "other"
    shutil.copytree(blocks, other)
    data = premises()
    data["basis"]["boundary"] = "feed to loading"
    write(other, data)
    found = compare(tea_report(blocks), tea_report(other))
    assert [d[0] for d in found.differences] == ["boundary"]
    assert found.findings[0].rule == "cheme.tea-not-comparable"
    assert compare(tea_report(blocks), tea_report(blocks)).comparable


def test_command_write_check_and_json(blocks: Path, monkeypatch, tmp_path: Path):
    monkeypatch.chdir(blocks)
    result = runner.invoke(app, ["assess", "tea", "--check"])
    assert result.exit_code == 1
    assert runner.invoke(app, ["assess", "tea", "--write"]).exit_code == 0
    assert runner.invoke(app, ["assess", "tea", "--check"]).exit_code == 0
    shown = runner.invoke(app, ["assess", "tea", "--json"])
    payload = json.loads(shown.stdout)
    monkeypatch.chdir(tmp_path)  # the function does not depend on the working directory
    report = tea_report(blocks)
    assert payload["results"] == json.loads(json.dumps(report.results()))
    assert (blocks / CASHFLOW_CSV).read_text(encoding="utf-8") == outputs(report)[CASHFLOW_CSV]


# -- the boundary the operating cost counts -------------------------------------------------------


def test_boundary_gaps_are_reported_and_leave_the_costs_alone(tmp_path: Path, monkeypatch):
    # process-recycle: the blocks' terminals, its cooler E1 with no energy stream, no categories
    root = tmp_path / "recycle"
    shutil.copytree(EXAMPLE.parent / "process-recycle", root)
    write(root, premises())
    report = tea_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.boundary is not None and not report.boundary.complete
    assert report.boundary.unassigned_duties == ["E1"]
    boundary = report.payload()["boundary"]
    assert boundary["complete"] is False and boundary["unassigned_duties"] == ["E1"]
    gaps = {(g["rule"], tuple(g["ids"])) for g in boundary["gaps"]}
    assert ("cheme.boundary-utility-unassigned", ("E1",)) in gaps
    assert ("cheme.boundary-unclassified", ("WATER",)) in gaps
    assert all(g["file"] == "process/flowsheet.yaml" and g["line"] for g in boundary["gaps"])
    # the same findings, with file, line, rule and hint, are the report's (the command prints them)
    found = [f for f in report.findings if f.rule.startswith("cheme.boundary-")]
    assert len(found) == len(boundary["gaps"]) and all(f.line and f.hint for f in found)
    text = outputs(report)[TEA_MD]
    assert "**Incomplete boundary:" in text and "## Boundary" in text
    assert "the utilities (steam, cooling, refrigeration, power) of E1" in text
    # PROD is priced and WATER listed free: their category is missing, no cost is excluded
    assert boundary["excluded_products"] == [] and "any disposal or treatment cost" not in text
    assert "Not classified (no category): PROD, WATER." in text
    assert "It does not check:" in text and "step-to-step" in text
    assert boundary["checked"] and boundary["noted"] and boundary["not_checked"]
    # the variable cost is the terminals' as before: the gap is reported, not priced
    assert {f.key for f in report.flows} == {
        "feed:FEED",
        "feed:STEAM",
        "product:PROD",
        "product:WATER",
    }
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["assess", "tea"])
    assert result.exit_code == 0
    assert "process/flowsheet.yaml:" in result.stderr
    assert "cheme.boundary-utility-unassigned" in result.stderr and "E1" in result.stderr


def test_an_unclassified_product_without_price_is_excluded_from_the_cost(blocks: Path):
    data = premises()
    data["free"] = []
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.payload()["boundary"]["excluded_products"] == ["WATER"]
    text = outputs(report)[TEA_MD]
    assert "any disposal or treatment cost of WATER: no category, no price" in text
    assert "Not classified (no category): PROD." in text  # the main product: priced


def test_a_simulation_file_that_does_not_load_is_a_boundary_finding(blocks: Path, tmp_path):
    from chemeascode.domains.assessment.flows import boundary_gaps
    from chemeascode.domains.process.model import load

    # process-blocks has no reactor: nothing depends on the file, so it is only noted
    (blocks / "process" / "simulation.yaml").write_text("specs: [\n", encoding="utf-8")
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    unread = [f for f in report.findings if f.rule == "cheme.boundary-adiabatic-unread"]
    assert len(unread) == 1 and unread[0].level == "info" and unread[0].ids == []
    assert unread[0].file == "process/simulation.yaml" and unread[0].hint
    # process-ammonia's reactor R1 has no energy stream: mode: adiabatic could exempt it
    root = tmp_path / "ammonia"
    shutil.copytree(EXAMPLE.parent / "process-ammonia", root)
    (root / "process" / "simulation.yaml").write_text("specs: [\n", encoding="utf-8")
    process, _ = load(root)
    gaps = boundary_gaps(process)
    unread = [f for f in gaps.findings if f.rule == "cheme.boundary-adiabatic-unread"]
    assert len(unread) == 1 and unread[0].level == "warning" and unread[0].ids == ["R1"]
    assert "R1" in unread[0].message and not gaps.complete


def test_a_classified_boundary_has_no_gap(blocks: Path):
    path = blocks / FLOWSHEET
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["feeds"][0]["category"] = "raw_material"
    data["feeds"][1]["category"] = "utility"
    data["products"][0]["category"] = "product"
    data["products"][1]["category"] = "wastewater"
    before = tea_report(blocks).results()
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    report = tea_report(blocks)
    assert report.loaded and report.boundary.complete
    assert report.payload()["boundary"]["unassigned_duties"] == []
    assert not [
        f for f in report.findings if f.rule.startswith("cheme.boundary-") and f.level != "info"
    ]
    assert report.results() == before  # classifying changes what is reported, not the cost
    text = outputs(report)[TEA_MD]
    assert "Incomplete" not in text and "Complete" not in text
    assert "## Boundary\n\nNo warning from the boundary check" in text
    assert "It notes (info, not a gap):" in text and "every feed terminal has a category" in text
    assert "It does not check:" in text and "excludes" not in text


def test_command_compare_with_a_revision(blocks: Path, monkeypatch):
    git(blocks, "init", "-q", "-b", "main")
    git(blocks, "config", "user.email", "test@example.org")
    git(blocks, "config", "user.name", "Test")
    git(blocks, "add", "-A")
    git(blocks, "commit", "-q", "-m", "base")
    data = premises()
    data["basis"]["location"] = "DE"
    write(blocks, data)
    monkeypatch.chdir(blocks)
    result = runner.invoke(app, ["assess", "tea", "--compare", "HEAD"])
    assert result.exit_code == 0, result.output
    assert "| location | DE | NL |" in result.stdout
    assert "cheme.tea-not-comparable" in result.stderr


def test_gate(blocks: Path):
    assert tea_gate(blocks, ["prices", "no-example", "decision"]) == []
    assert "run cheme assess tea --write" in tea_gate(blocks, ["tea-current"])[0]
    for name, text in outputs(tea_report(blocks)).items():
        (blocks / name).write_text(text, encoding="utf-8")
    assert tea_gate(blocks, ["tea-current"]) == []
    write(blocks, premises(free=[], example=True))
    problems = tea_gate(blocks, ["prices", "no-example", "tea-current"])
    assert len(problems) >= 3 and "product:WATER" in problems[0]


def test_check_schema_keeps_tea_requirements_apart():
    Check(id="t", title="t", stage="basic", kind="tea", require=["prices", "tea-current"])
    with pytest.raises(ValueError, match="tea check requires only"):
        Check(id="t", title="t", stage="basic", kind="tea", require=["prices", "mto-current"])
    with pytest.raises(ValueError, match="belong to a kind: tea check"):
        Check(id="t", title="t", stage="basic", kind="layout-model", require=["site", "prices"])
    with pytest.raises(ValueError, match="needs require"):
        Check(id="t", title="t", stage="basic", kind="tea")


def test_api(blocks: Path):
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(blocks, "init", "-q", "-b", "main")
    git(blocks, "config", "user.email", "test@example.org")
    git(blocks, "config", "user.name", "Test")
    git(blocks, "add", "-A")
    git(blocks, "commit", "-q", "-m", "base")
    api = TestClient(create_app(blocks, allowed_hosts=["testserver"]))
    assert api.get("/api/repo").json()["has_tea"] is True
    assert api.get("/api/tea").json()["rev"] is None  # the working tree
    answer = api.get("/api/tea", params={"rev": "HEAD"})
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["rev"] == git(blocks, "rev-parse", "HEAD").strip()
    assert body["results"]["npv"] == pytest.approx(tea_report(blocks).value("npv"))
    assert {"capex", "flows", "cashflow", "break_even", "tornado", "findings"} <= set(body)
    git(blocks, "rm", "-q", TEA_FILE)
    git(blocks, "commit", "-q", "-m", "no tea")
    assert api.get("/api/tea", params={"rev": "HEAD"}).status_code == 404
    assert api.get("/api/repo").json()["has_tea"] is False


def test_validate_checks_the_premises(blocks: Path, monkeypatch):
    data = premises()
    data["finance"]["construction"] = [0.5, 0.6]
    write(blocks, data)
    monkeypatch.chdir(blocks)
    result = runner.invoke(app, ["validate"])
    assert TEA_FILE in result.output and "sum to 1.1" in result.output


def test_json_has_no_nan_where_there_is_no_irr(blocks: Path):
    data = premises(
        decision={"question": "Proceed to basic engineering?", "metric": "irr"},
        uncertainty={"iterations": 50},
    )
    data["prices"][2]["value"] = 1  # no price makes it pay: no IRR anywhere
    write(blocks, data)
    report = tea_report(blocks)
    assert report.value("irr") is None
    text = report.to_json()
    assert "NaN" not in text and "Infinity" not in text
    json.loads(text)
