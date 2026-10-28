"""The TEA beyond one continuous case: lines, cases, components, conversions, variable items,
emissions, events, price paths, batch operation, working capital, tax, capital scaling, the cost
of production, and the review fixes of the first increment.

The plant is ``examples/process-blocks`` (see ``test_assessment_tea.py``): per hour 1000 kg of
feed (400 kg ETOH, 600 kg H2O) and 350 kWh of steam in; 400 kg of product (380 kg ETOH) and
600 kg of waste water (20 kg ETOH) out.
"""

import re
import shutil
from pathlib import Path

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.tea import model
from chemeascode.domains.assessment.tea.model import Event, Line, Premises, evaluate
from chemeascode.domains.assessment.tea.report import REPORT_INPUTS, TEA_FILE, tea_report
from chemeascode.domains.assessment.tea.schemas import TeaFile
from chemeascode.interfaces.cli import app
from tests.conftest import git
from tests.test_assessment_tea import EXAMPLE, _v, premises, write

runner = CliRunner()
HOURS = 8000
SKILL = Path(__file__).parents[1] / "src/chemeascode/domains/assessment/skills/tea/SKILL.md"


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    write(root, premises())
    return root


def rules(report) -> set[str]:
    return {f.rule for f in report.findings}


def one(report, rule):
    return next(f for f in report.findings if f.rule == rule)


def amount(report, key: str) -> float:
    return float(report.baseline.amounts[key][0])


def add_case(root: Path, case: str, factor: float) -> None:
    """A second flowsheet case with every flow and duty times *factor*."""
    path = root / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["cases"].append({"id": case, "description": "test case"})
    for stream in data["streams"]:
        state = dict(stream["state"]["design"])
        for name in ("flow", "duty"):
            if name in state:
                state[name] = {**state[name], "value": state[name]["value"] * factor}
        stream["state"][case] = state
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


# -- the model -----------------------------------------------------------------------------------


def base(**extra) -> Premises:
    values = dict(
        isbl=1000.0,
        main="product:P",
        hours=100.0,
        life=4,
        discount_rate=0.1,
        lines=[Line("product:P", 1.0, 5.0, True, unit="kg")],
    )
    values.update(extra)
    return Premises(**values)


def npv_of(cash: list[float], rate: float = 0.1) -> float:
    return sum(c / (1 + rate) ** t for t, c in enumerate(cash))


def test_events_every_years_expensed_and_capital():
    p = base(events=[Event("cat", 100.0, every_years=2, first=2)])
    o = evaluate(p)
    # operating years are t = 1..4; years 2 and 4 of operation, the last one skipped
    assert o.flows["periodic"][0].tolist() == [0, 0, 100, 0, 0]
    assert o.npv[0] == pytest.approx(npv_of([-1000, 500, 400, 500, 500]))
    grant = evaluate(base(events=[Event("grant", -200.0, first=0)]))
    assert grant.flows["periodic"][0][0] == -200  # the construction year
    capital = evaluate(base(events=[Event("rep", 120.0, every_years=2, first=2, capital=True)]))
    assert capital.flows["capital"][0].tolist() == [1000, 0, 120, 0, 0]
    # depreciated over the two years until the next occurrence (no tax here: cash unchanged)
    assert capital.flows["depreciation"][0][3:].tolist() == pytest.approx([250 + 60, 250 + 60])


def test_events_every_hours_follow_the_operating_hours():
    p = base(hours=4000.0, events=[Event("stack", 50.0, every_hours=8000.0, skip_last=False)])
    assert evaluate(p).flows["periodic"][0].tolist() == [0, 0, 50, 0, 50]
    slow = evaluate(p, {"operation:hours_per_year": 0.5})
    assert slow.flows["periodic"][0].tolist() == [0, 0, 0, 0, 50]


def test_downtime_lowers_the_load_of_its_year():
    p = base(hours=8000.0, events=[Event("ta", 0.0, every_years=2, first=2, downtime_days=50)])
    load = evaluate(p).flows["capacity"][0]
    assert load[2] == pytest.approx(1 - 50 * 24 / 8000)
    assert load[1] == load[3] == 1.0


def test_profile_moves_the_price_by_year():
    p = base(lines=[Line("product:P", 1.0, 5.0, True, unit="kg", profile=(1.0, 2.0))])
    assert evaluate(p).flows["revenue"][0].tolist() == [0, 500, 1000, 1000, 1000]


def test_loss_carry_forward_and_lcop():
    p = base(tax_rate=0.5, losses="carry_forward", life=3, ramp_up=[0.1])
    o = evaluate(p)
    # year 1: 50 revenue - 333.3 depreciation = -283.3: no tax, carried; year 2: 500 - 333.3
    # - 283.3 < 0: no tax, 116.7 carried; year 3: 500 - 333.3 - 116.7 = 50 taxed at 0.5
    assert o.flows["tax"][0].tolist() == pytest.approx([0, 0, 0, 25])
    lcop = o.lcop[0]
    at = evaluate(model.with_prices(p, {"product:P": lcop}))
    assert at.npv[0] == pytest.approx(0, abs=1e-4)


def test_write_off_when_depreciation_outlasts_the_life():
    p = base(tax_rate=0.5, depreciation_years=8)
    o = evaluate(p)
    assert o.flows["depreciation"][0].sum() == pytest.approx(1000)
    assert o.flows["depreciation"][0][-1] == pytest.approx(125 + 500)
    schedule = evaluate(base(tax_rate=0.5, depreciation=[0.5, 0.3]))
    assert schedule.flows["depreciation"][0][1:].tolist() == pytest.approx([500, 300, 0, 200])


def test_batch_hours_and_success_rate():
    batch = model.Batch(cycle_time=10.0, basis_hours=5.0, trains=2, success_rate=0.9)
    p = base(
        hours=1000.0,
        batch=batch,
        lines=[
            Line("product:P", 1.0, 5.0, True, unit="kg", saleable=True),
            Line("feed:F", 2.0, 1.0, False, unit="kg"),
        ],
    )
    o = evaluate(p)
    # 1000 h x 2 trains / 10 h = 200 batches of 5 h: 1000 operating hours
    assert o.hours[0] == pytest.approx(1000)
    assert o.revenue[0] == pytest.approx(1000 * 5 * 0.9)
    assert o.variable_cost[0] == pytest.approx(2000)
    assert evaluate(p, {"operation:cycle_time": 2.0}).hours[0] == pytest.approx(500)


def test_working_capital_days_and_utilisation():
    days = model.WorkingCapitalDays(feed_inventory=36.5, receivables=73.0)
    p = base(
        utilisation=0.8,
        working_capital_days=days,
        lines=[Line("product:P", 1.0, 5.0, True), Line("feed:F", 1.0, 2.0, False)],
    )
    o = evaluate(p)
    assert o.revenue[0] == pytest.approx(400) and o.variable_cost[0] == pytest.approx(160)
    assert o.working_capital[0] == pytest.approx(160 * 0.1 + 400 * 0.2)


def test_cost_of_production_sums_to_the_lcop():
    p = base(
        maintenance=0.02,
        events=[Event("cat", 30.0, every_years=2, first=2)],
        lines=[
            Line("product:P", 1.0, 5.0, True),
            Line("feed:F", 1.0, 1.0, False, category="feed"),
            Line("product:B", 1.0, 0.5, True, category="byproduct"),
        ],
    )
    o = evaluate(p)
    total = sum(float(v[0]) for v in o.breakdown.values())
    assert total < o.lcop[0]  # the rest is capital and tax
    assert o.breakdown["feed"][0] == pytest.approx(1.0)
    assert o.breakdown["byproduct"][0] == pytest.approx(-0.5)
    assert o.cash_cost[0] == pytest.approx((100 + 20 - 50) / 100)


# -- the report ----------------------------------------------------------------------------------


def test_cases_weight_the_flows_and_price_by_case(blocks: Path):
    add_case(blocks, "turndown", 0.5)
    data = premises(
        cases=[
            {"case": "design", "share": _v(0.6), "source": "test"},
            {
                "case": "turndown",
                "share": _v(0.4),
                "prices": {"feed:STEAM": 60},
                "source": "test",
            },
        ]
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    feed = next(f for f in report.flows if f.key == "feed:FEED")
    assert feed.rate == pytest.approx(0.6 * 1000 + 0.4 * 500)
    assert feed.per_case == {"design": 1000, "turndown": 500}
    # steam: 0.6 x 350 at 30 + 0.4 x 175 at 60 (per MWh), 8000 h
    expected = HOURS * (0.6 * 350 * 0.03 + 0.4 * 175 * 0.06)
    steam = amount(report, "feed:STEAM~design") + amount(report, "feed:STEAM~turndown")
    assert steam == pytest.approx(expected)
    # one price driver for both cases
    doubled = model.evaluate(report.premises, {"price:feed:STEAM": 2.0})
    assert float(doubled.variable_cost[0] - report.baseline.variable_cost[0]) == pytest.approx(
        expected
    )
    write(blocks, premises(cases=[{"case": "design", "share": _v(0.5), "source": "t1t"}]))
    assert "cheme.tea-premises" in rules(tea_report(blocks))  # shares sum to 0.5


def test_component_price_and_conversion(blocks: Path):
    data = premises()
    data["free"] = []
    data["prices"].append(
        {"key": "product:WATER", "component": "ETOH", "value": -200, "unit": "t", "source": "t3t"}
    )
    # steam priced per t of steam with 1.5 kg of steam per kWh of duty
    data["prices"][1] = {
        "key": "feed:STEAM",
        "value": 20,
        "unit": "t",
        "source": "test",
        "conversion": {"value": 0.0015, "source": "1.5 kg/kWh"},
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    # a product with a negative price is a cost line (category disposal)
    assert amount(report, "product:WATER@ETOH") == pytest.approx(0.2 * 20 * HOURS)
    line = report.premises.line("product:WATER@ETOH")
    assert not line.revenue and line.category == "disposal"
    assert amount(report, "feed:STEAM") == pytest.approx(350 * 0.0015 * 20 * HOURS)
    assert "conversion:feed:STEAM" in report.premises.inputs()
    data["prices"][1].pop("conversion")
    write(blocks, data)
    assert "cheme.tea-price-unit" in rules(tea_report(blocks))
    data["prices"][1] = {"key": "feed:STEAM", "value": 1, "unit": "MMBtu", "source": "test"}
    write(blocks, data)
    report = tea_report(blocks)
    assert amount(report, "feed:STEAM") == pytest.approx(350 / 293.07107 * HOURS)
    data["prices"][-1]["component"] = "NOPE"
    write(blocks, data)
    assert "cheme.tea-price-component" in rules(tea_report(blocks))


def test_variable_items_follow_their_flow(blocks: Path):
    data = premises(
        variable_opex=[
            {
                "id": "naoh",
                "per": "feed:FEED",
                "amount": _v(0.002),
                "unit": "kg NaOH",
                "value": 0.5,
                "source": "test",
                "year": 2025,
            },
            {
                "id": "fee",
                "per": "hour",
                "amount": _v(1),
                "unit": "h",
                "value": 10,
                "category": "other",
                "source": "test",
            },
            {
                "id": "credit",
                "per": "product:PROD",
                "amount": _v(1),
                "unit": "kg",
                "value": -0.1,
                "category": "incentive",
                "profile": [1, 0],
                "source": "test",
            },
        ]
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert amount(report, "variable:naoh") == pytest.approx(1000 * 0.002 * 0.5 * HOURS)
    assert amount(report, "variable:fee") == pytest.approx(10 * HOURS)
    # the credit stops after the first operating year
    assert report.lcop_unsubsidised is not None
    assert report.lcop_unsubsidised > report.value("lcop") - 1e-9
    moved = model.evaluate(report.premises, {"rate:feed:FEED": 2.0})
    assert float(moved.amounts["variable:naoh"][0]) == pytest.approx(
        2 * amount(report, "variable:naoh")
    )
    assert "cheme.tea-no-year" in rules(report)  # fee and credit give no year
    write(blocks, premises(variable_opex=[{**data["variable_opex"][0], "per": "batch"}]))
    assert "cheme.tea-variable-per" in rules(tea_report(blocks))


def test_emissions_with_capture_and_free_allocation(blocks: Path):
    data = premises(
        emissions={
            "price": _v(80, year=2025),
            "sources": [
                {
                    "id": "etoh",
                    "key": "product:WATER",
                    "component": "ETOH",
                    "factor": _v(1.91),
                    "captured": _v(0.5),
                }
            ],
            "allocation": {
                "benchmark": _v(0.05),
                "per": "product:PROD",
                "fraction": _v(0.4),
            },
        }
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    emitted = 20 / 1000 * 1.91 * 0.5 * HOURS  # t CO2-eq/a
    free = 400 / 1000 * 0.05 * 0.4 * HOURS
    em = report.emissions()
    # the flowsheet's mass fraction 0.0333333 gives 19.99998 kg/h of ETOH
    assert em["t_per_year"] == pytest.approx(emitted, rel=1e-5)
    assert em["free_t_per_year"] == pytest.approx(free)
    assert em["cost_per_year"] == pytest.approx((emitted - free) * 80, rel=1e-5)
    assert "price:carbon" in report.premises.inputs()
    breakdown = {row["category"] for row in report.cost_of_production()}
    assert "emission" in breakdown


def test_events_capacity_scaling_location_and_wc_days_in_the_report(blocks: Path):
    data = premises(
        events=[
            {
                "id": "catalyst",
                "cost": _v(50_000),
                "every_years": 3,
                "source": "test",
            }
        ]
    )
    data["capex"]["isbl"] = {
        "source": "given",
        "value": _v(5e6, year=2025),
        "scaling": {
            "reference": _v(1600.0),
            "unit": "t",
            "exponent": _v(0.6),
        },
        "location_factor": _v(1.1),
    }
    data["finance"]["working_capital_days"] = {
        "feed_inventory": _v(30),
        "receivables": _v(45),
        "source": "test",
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    # 400 kg/h x 8000 h = 3200 t/a against 1600: x 2 ** 0.6, then x 1.1
    assert report.results()["isbl"] == pytest.approx(5e6 * 2**0.6 * 1.1)
    periodic = report.baseline.flows["periodic"][0]
    c = report.baseline.construction_years
    assert periodic[c + 2] == 50_000 and periodic[c + 5] == 50_000
    res = report.results()
    wc = (res["variable_cost_per_year"] * 30 + res["revenue_per_year"] * 45) / 365
    assert res["working_capital"] == pytest.approx(wc)
    assert report.events[0]["first_year"] == 3


def test_cash_cost_decision_and_main_unit(blocks: Path):
    data = premises(
        decision={"question": "Is the cash cost low enough?", "metric": "cash_cost", "threshold": 2}
    )
    data["basis"]["unit"] = "kg"
    write(blocks, data)
    report = tea_report(blocks)
    assert report.lcop_unit == "kg" and report.lcop_factor == 1
    assert report.meets() is (report.value("cash_cost") <= 2)
    cop = report.cost_of_production()
    assert sum(row["per_unit"] for row in cop) == pytest.approx(report.value("lcop"))


def test_throughput_mode_moves_every_rate_together(blocks: Path):
    data = premises(
        uncertainty={
            "iterations": 200,
            "rate_mode": "throughput",
            "throughput": {"distribution": "normal", "cv": 0.05},
            "rates": {"given": {"gsd2": 1.5}},
        }
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert "operation:throughput" in report.uncertainty.varied
    assert not any(v.startswith("rate:") for v in report.uncertainty.varied)


def test_batch_plant_in_the_report(blocks: Path):
    data = premises()
    data["operation"]["batch"] = {
        "cycle_time": _v(16),
        "basis_hours": 12,
        "success_rate": _v(0.95),
        "source": "test",
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.batches == pytest.approx(8000 / 16)
    assert report.results()["operating_hours"] == pytest.approx(500 * 12)
    assert "cheme.tea-batch-basis" in rules(report)
    assert "operation:cycle_time" in report.premises.inputs()


# -- the review of the first increment -----------------------------------------------------------


def test_no_crash_without_the_main_price_on_an_npv_decision(blocks: Path):
    data = premises(uncertainty={"iterations": 50})
    data["prices"] = data["prices"][:2]  # PROD unpriced
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded
    assert report.uncertainty.probability is None
    assert {s.metric for s in report.uncertainty.statistics} == {
        "fixed_capital",
        "lcop",
        "cash_cost",
    }


def test_given_isbl_is_converted_and_escalated(blocks: Path):
    data = premises()
    data["capex"]["isbl"] = {
        "source": "given",
        "value": _v(1e6, year=2020),
        "exchange_rate": _v(0.9),
        "escalation": _v(1.2),
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert report.results()["isbl"] == pytest.approx(1e6 * 0.9 * 1.2)
    assert "cheme.tea-cost-year" not in rules(report)


def test_scenario_replaces_a_price_of_zero(blocks: Path):
    data = premises(scenarios=[{"id": "dear", "prices": {"feed:FEED": 50}}])
    data["prices"][0]["value"] = 0
    write(blocks, data)
    report = tea_report(blocks)
    assert report.scenarios[0].npv < report.value("npv")


def test_allowance_only_where_it_applies():
    with pytest.raises(ValueError, match="uncovered_allowance"):
        TeaFile.model_validate(
            {
                **premises(),
                "capex": {
                    "isbl": {
                        "source": "given",
                        "value": _v(1),
                        "uncovered_allowance": _v(0.1),
                    }
                },
            }
        )


def test_reactions_are_an_input():
    assert "process/reactions.yaml" in REPORT_INPUTS


def test_compare_with_a_revision_without_the_plant(blocks: Path, tmp_path: Path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.org")
    git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("empty\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "before the plant")
    shutil.copytree(blocks, repo / "plant")
    monkeypatch.chdir(repo / "plant")
    result = runner.invoke(app, ["assess", "tea", "--compare", "HEAD"])
    assert result.exit_code == 1
    assert "no plant at HEAD" in result.stderr


def test_the_skill_example_loads():
    text = SKILL.read_text(encoding="utf-8")
    block = re.search(r"```yaml\n(.*?)```", text, re.S).group(1)
    data = yaml.safe_load("\n".join(line[2:] for line in block.splitlines()))
    TeaFile.model_validate(data)


def test_the_no_premises_hint_does_not_promise_a_template(blocks: Path):
    (blocks / TEA_FILE).unlink()
    found = one(tea_report(blocks), "cheme.tea-no-premises")
    assert "cheme init ships" not in found.hint


def test_breakdown_is_finite_per_sample():
    p = base(lines=[Line("product:P", 1.0, 5.0, True), Line("feed:F", 1.0, 1.0, False)])
    o = evaluate(p, {"price:feed:F": np.array([1.0, 2.0])}, 2)
    assert o.breakdown["other"].tolist() == pytest.approx([1.0, 2.0])


def add_power(root: Path, kw: float = 100.0) -> None:
    """An energy product POWER: 100 kW from the separator."""
    path = root / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["products"].append(
        {
            "id": "POWER",
            "title": "Power",
            "ports": [{"id": "in", "direction": "in", "kind": "energy"}],
        }
    )
    sep = next(b for b in data["blocks"] if b["id"] == "SEP")
    sep["ports"].append({"id": "gen", "direction": "out", "kind": "energy"})
    data["streams"].append(
        {
            "id": "Q2",
            "title": "Power",
            "kind": "energy",
            "from": "SEP.gen",
            "to": "POWER.in",
            "state": {"design": {"duty": {"value": kw, "provenance": "assumed"}}},
        }
    )
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def test_an_energy_main_product(blocks: Path):
    add_power(blocks)
    data = premises(
        decision={"question": "Is the power cheap enough?", "metric": "lcop", "threshold": 500}
    )
    data["basis"]["product"] = "POWER"
    data["prices"][2]["key"] = "product:PROD"  # the ethanol becomes a co-product
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.lcop_unit == "MWh" and report.lcop_factor == 1000
    lcop = report.value("lcop")
    assert report.results()["lcop_unit"] == "EUR/MWh"
    data["prices"].append({"key": "product:POWER", "value": lcop, "unit": "MWh", "source": "test"})
    write(blocks, data)
    assert tea_report(blocks).value("npv") == pytest.approx(0, abs=1e-3)
    data["basis"]["unit"] = "t"  # a mass unit for an energy product needs a conversion
    write(blocks, data)
    assert "cheme.tea-product-unit" in rules(tea_report(blocks))


def test_cash_cost_probability_counts_lower_as_better(blocks: Path):
    data = premises(
        decision={
            "question": "Is the cash cost low enough?",
            "metric": "cash_cost",
            "threshold": 1e6,
        },
        uncertainty={"iterations": 100},
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.meets() is True
    assert report.uncertainty.probability == 1.0


# -- the review of the generalised TEA -----------------------------------------------------------


def test_batch_events_count_plant_hours():
    batch = model.Batch(cycle_time=10.0, basis_hours=1.0, batches_per_year=800.0)
    p = base(
        hours=8000.0,
        life=3,
        batch=batch,
        events=[Event("ta", 0.0, every_years=2, first=2, downtime_days=30)],
    )
    # 800 batches of 10 h: the plant runs 8000 h; 30 days take 720 h of them
    assert evaluate(p).flows["capacity"][0][2] == pytest.approx(1 - 720 / 8000)


def test_one_off_events_in_and_beyond_the_last_year():
    assert evaluate(base(events=[Event("x", 100.0, first=4)])).flows["periodic"][0][4] == 100
    assert evaluate(base(events=[Event("x", 100.0, first=9)])).flows["periodic"][0].sum() == 0


def test_capital_event_in_construction_is_depreciated_from_start_up():
    o = evaluate(base(events=[Event("first-fill", 100.0, first=0, capital=True)]))
    assert o.flows["depreciation"][0][0] == 0
    assert o.flows["depreciation"][0][1:].sum() == pytest.approx(1100)


def test_lcop_only_when_asked():
    p = base(tax_rate=0.3, losses="carry_forward")
    assert np.isnan(evaluate(p, lcop=False).lcop[0])
    assert np.isfinite(evaluate(p).lcop[0])


def test_case_split_rate_is_the_flow_rate(blocks: Path):
    add_case(blocks, "turndown", 0.5)
    data = premises(
        cases=[
            {"case": "design", "share": _v(0.5), "source": "test"},
            {
                "case": "turndown",
                "share": _v(0.5),
                "prices": {"feed:STEAM": 60, "feed:NOPE": 1},
                "source": "test",
            },
        ]
    )
    write(blocks, data)
    assert "cheme.tea-price-unknown" in rules(tea_report(blocks))
    data["cases"][1]["prices"].pop("feed:NOPE")
    write(blocks, data)
    report = tea_report(blocks)
    assert report.inputs["rate:feed:STEAM"].value == pytest.approx(0.5 * 350 + 0.5 * 175)


def test_emission_tonnes_follow_the_utilisation(blocks: Path):
    data = premises(
        emissions={
            "price": _v(80),
            "sources": [{"id": "w", "key": "product:WATER", "factor": _v(0.1)}],
        }
    )
    data["operation"]["utilisation"] = _v(0.5)
    write(blocks, data)
    em = tea_report(blocks).emissions()
    assert em["t_per_year"] == pytest.approx(600 / 1000 * 0.1 * HOURS * 0.5)
    assert em["cost_per_year"] == pytest.approx(em["t_per_year"] * 80)


@pytest.mark.parametrize(
    "change",
    [
        {
            "emissions": {
                "price": _v(1),
                "sources": [{"id": "x", "key": "feed:FEED", "factor": _v(1), "captured": _v(1.2)}],
            }
        },
        {
            "operation": {
                "hours_per_year": 8000,
                "life_years": 20,
                "source": "test",
                "batch": {"cycle_time": _v(0), "basis_hours": 1, "source": "test"},
            }
        },
        {
            "variable_opex": [
                {
                    "id": "x",
                    "per": "hour",
                    "component": "ETOH",
                    "amount": _v(1),
                    "unit": "kg",
                    "value": 1,
                    "source": "test",
                }
            ]
        },
        {"free": [{"key": "product:PROD", "reason": "nothing"}]},
    ],
)
def test_impossible_premises_are_refused(change: dict):
    with pytest.raises(ValueError):
        TeaFile.model_validate(premises(**change))


def test_throughput_and_batch_hours_are_inputs(blocks: Path):
    data = premises(uncertainty={"iterations": 20, "rate_mode": "throughput"})
    data["operation"]["batch"] = {"cycle_time": _v(16), "basis_hours": 12, "source": "test"}
    write(blocks, data)
    inputs = tea_report(blocks).premises.inputs()
    assert "operation:throughput" in inputs
    assert {"operation:hours_per_year", "operation:cycle_time"} <= set(inputs)


def test_flow_per_year_is_the_net_income(blocks: Path):
    report = tea_report(blocks)
    rows = {f.key: f for f in report.flows}
    assert rows["feed:FEED"].per_year == pytest.approx(-1000 * 0.05 * HOURS)
    assert rows["product:PROD"].per_year == pytest.approx(400 * 0.9 * HOURS)
    assert rows["product:PROD"].prices == [{"component": "", "price": 900, "unit": "t"}]


def test_compare_sees_the_utilisation(blocks: Path, tmp_path: Path):
    other = tmp_path / "other"
    shutil.copytree(blocks, other)
    data = premises()
    data["operation"]["utilisation"] = _v(0.8)
    write(other, data)
    from chemeascode.domains.assessment.tea.report import compare

    found = compare(tea_report(blocks), tea_report(other))
    assert [d[0] for d in found.differences] == ["operation"]


def test_unused_exchange_rate_and_composite_uncertainty(blocks: Path):
    data = premises()
    data["capex"]["isbl"]["exchange_rate"] = _v(1.1)
    data["capex"]["isbl"]["scaling"] = {
        "reference": _v(3200.0),
        "unit": "t",
        "exponent": {**_v(0.6), "uncertainty": {"gsd2": 1.2}},
    }
    write(blocks, data)
    report = tea_report(blocks)
    assert "cheme.tea-uncertainty-unused" in rules(report)
    assert "capex.isbl.scaling.exponent" in one(report, "cheme.tea-uncertainty-unused").message


# -- the review of the port onto main ------------------------------------------------------------


def _disposal(per: str = "product:WATER", **extra) -> dict:
    return {
        "id": "ww",
        "per": per,
        "amount": _v(1),
        "unit": "kg",
        "value": 0.01,
        "category": "disposal",
        "source": "test",
        "year": 2025,
        **extra,
    }


def test_a_disposal_item_or_emission_source_costs_a_product(blocks: Path):
    data = premises(variable_opex=[_disposal()])
    data["free"] = []
    write(blocks, data)
    report = tea_report(blocks)
    assert report.loaded, [f.format() for f in report.findings]
    assert "cheme.tea-price-missing" not in rules(report)
    assert "WATER" not in report.boundary_entry()["excluded_products"]
    assert "WATER" not in report.unclassified_products()[0]
    # a consumable per the product (not disposal) does not cost it
    write(blocks, {**data, "variable_opex": [_disposal(category="chemical")]})
    assert "product:WATER" in one(tea_report(blocks), "cheme.tea-price-missing").ids


def test_lca_prices_compare_a_component_priced_product(blocks: Path):
    data = premises()
    data["free"] = []
    data["prices"].append(
        {"key": "product:WATER", "component": "ETOH", "value": 0.5, "unit": "kg", "source": "test"}
    )
    write(blocks, data)
    (blocks / "lca").mkdir(exist_ok=True)
    # 20 kg ETOH in 600 kg/h of WATER at 0.5 /kg ETOH: 1/60 per kg of the whole flow
    allocation = {"method": "economic", "coproducts": ["WATER"]}
    for water, mismatch in ((0.5 * 20 / 600, False), (0.04, True)):
        allocation["prices"] = {"PROD": 0.9, "WATER": water}
        (blocks / "lca" / "lca.yaml").write_text(
            yaml.safe_dump({"allocation": allocation}), encoding="utf-8"
        )
        report = tea_report(blocks)
        found = [f for f in report.findings if f.rule == "cheme.tea-lca-price-mismatch"]
        assert bool(found) is mismatch, [f.message for f in found]
        assert not any("unpriced here" in f.message for f in found)


def test_downtime_counts_each_occurrence_of_a_year():
    p = base(hours=8000.0, events=[Event("clean", 10.0, every_hours=2000, downtime_days=5)])
    o = evaluate(p)
    assert o.flows["periodic"][0][1] == pytest.approx(40)
    assert o.flows["capacity"][0][1] == pytest.approx(1 - 4 * 5 * 24 / 8000)


def test_a_first_year_starts_an_every_hours_series():
    stack = Event("stack", 10.0, every_hours=16000, first=5, anchored=True)
    o = evaluate(base(hours=8000.0, life=8, events=[stack]))
    # first in year 5, then after 16000 h of running (end of year 6); year 8 is the last
    assert o.flows["periodic"][0].tolist() == [0, 0, 0, 0, 0, 10, 10, 0, 0]
    # without a first year the hours count from start-up
    o = evaluate(base(hours=8000.0, life=8, events=[Event("stack", 10.0, every_hours=16000)]))
    assert o.flows["periodic"][0].tolist() == [0, 0, 10, 0, 10, 0, 10, 0, 0]


def test_a_component_line_needs_the_whole_flow_split(blocks: Path):
    add_case(blocks, "low", 1.0)
    path = blocks / "process" / "flowsheet.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for stream in data["streams"]:
        if stream.get("to") == "WATER.in":
            stream["state"]["low"].pop("composition", None)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    shares = [
        {"case": "design", "share": _v(0.5), "source": "test"},
        {"case": "low", "share": _v(0.5), "source": "test"},
    ]
    tea = premises(cases=shares)
    tea["free"] = []
    tea["prices"].append(
        {"key": "product:WATER", "component": "ETOH", "value": 200, "unit": "t", "source": "test"}
    )
    write(blocks, tea)
    report = tea_report(blocks)
    found = one(report, "cheme.tea-price-component")
    assert not report.loaded and "case low" in found.message and found.line is not None


def test_success_rate_is_an_input_with_given_batches(blocks: Path):
    data = premises()
    data["operation"]["batch"] = {
        "cycle_time": _v(16),
        "basis_hours": 12,
        "batches_per_year": _v(400),
        "success_rate": _v(0.9),
        "source": "test",
    }
    write(blocks, data)
    assert "operation:success_rate" in tea_report(blocks).premises.inputs()


def test_a_component_item_follows_the_components_rate(blocks: Path):
    data = premises(variable_opex=[_disposal(component="ETOH", category="chemical")])
    data["free"] = []
    data["prices"].append(
        {"key": "product:WATER", "component": "ETOH", "value": 200, "unit": "t", "source": "test"}
    )
    write(blocks, data)
    report = tea_report(blocks)
    assert report.premises.line("variable:ww").scales == ("rate:product:WATER@ETOH",)


def test_findings_name_the_entry_line(blocks: Path):
    from chemeascode.domains.assessment.tea.build import _line

    text = (
        "basis:\n  specification: 95 wt%\nprices:\n  - key: product:WATER\n    value: 1\n"
        "    component: ETOH\nvariable_opex:\n  - {id: catalyst, per: hour}\n  - id: cat\n"
    )
    assert _line(text, "variable:cat") == 9
    assert _line(text, "variable:catalyst") == 8
    assert _line(text, "product:WATER@ETOH") == 6
    assert _line(text, "product:WATER@ETOH~low") == 6
    data = premises(variable_opex=[_disposal(year=None)])
    write(blocks, data)
    found = one(tea_report(blocks), "cheme.tea-no-year")
    assert "id: ww" in (blocks / TEA_FILE).read_text().splitlines()[found.line - 1]


def test_gate_without_a_probability_does_not_crash(blocks: Path):
    from chemeascode.domains.assessment.tea.gates import tea_gate

    data = premises(uncertainty={"iterations": 50})
    data["decision"]["confidence"] = 0.9
    data["free"] = []
    data["prices"] = [
        *data["prices"][:2],
        {"key": "product:WATER", "value": 500, "unit": "t", "source": "test", "year": 2025},
    ]
    write(blocks, data)
    problems = tea_gate(blocks, ["decision"])
    assert any("no P(meets)" in p for p in problems)


def test_an_irr_decision_without_an_irr_is_not_met(blocks: Path):
    from chemeascode.domains.assessment.tea.gates import tea_gate

    data = premises()
    data["decision"]["metric"] = "irr"
    data["prices"][2]["value"] = 10
    write(blocks, data)
    report = tea_report(blocks)
    assert report.value("irr") is None and report.meets() is False
    assert tea_gate(blocks, ["decision"]) == [
        "the baseline does not meet the decision's irr threshold"
    ]


@pytest.mark.parametrize(
    "change",
    [
        {
            "capex": {
                "isbl": {
                    "source": "given",
                    "value": _v(1e6),
                    "scaling": {"reference": _v(0), "unit": "t", "exponent": _v(0.6)},
                }
            }
        },
        {"capex": {"isbl": {"source": "equipment", "location_factor": _v(0)}}},
        {
            "prices": [
                {
                    "key": "feed:STEAM",
                    "value": 30,
                    "unit": "Nm3",
                    "source": "test",
                    "conversion": _v(-2),
                }
            ]
        },
        {
            "prices": [
                {
                    "key": "product:WATER",
                    "component": "ETOH",
                    "value": 1,
                    "unit": "t",
                    "source": "test",
                }
            ]
        },
    ],
)
def test_impossible_conversions_and_free_prices_are_refused(change: dict):
    with pytest.raises(ValueError):
        TeaFile.model_validate(premises(**change))


def test_markdown_variable_rows_are_net_income(blocks: Path):
    from chemeascode.domains.assessment.tea.report import tea_markdown

    credit = _disposal(id="credit", per="product:PROD", value=-0.05, category="incentive")
    write(blocks, premises(variable_opex=[_disposal(per="feed:FEED", category="chemical"), credit]))
    text = tea_markdown(tea_report(blocks))
    row = {line.split("|")[1].split()[0]: line for line in text.splitlines() if "variable:" in line}
    assert "| -80,000 |" in row["variable:ww"]  # 1000 kg/h x 0.01 x 8000 h, a cost
    assert "| 160,000 |" in row["variable:credit"]  # 400 kg/h x 0.05 x 8000 h, an income
