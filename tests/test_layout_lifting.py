"""The lifting study (``cheme layout lifting``): radius, load moment and capacity per heavy
lift, crane charts, and the ``lifting`` requirement of a layout gate; numbers checked by hand."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from chemeascode.domains.spatial.gates import layout_gate
from chemeascode.domains.spatial.lifting import study, study_csv, study_markdown
from chemeascode.domains.spatial.schemas import CraneCharts
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE, Workspace
from tests.test_layout_engineering_rules import LAYDOWN, base, heavy, pad


def charts(rows, **extra):
    return CraneCharts.model_validate(
        {
            "cranes": [
                {
                    "id": "MC-1",
                    "source": "example chart for the test",
                    "status": "ASSUMED",
                    "chart": [{"radius_m": r, "capacity_t": c} for r, c in rows],
                    **extra,
                }
            ]
        }
    )


def model():
    # K-1: 12 t, bbox [18, 19, 0, 22, 21, 3]; pad centre (24, 6)
    return base(equipment=[heavy()], zones=[pad([20, 2, 0, 28, 10, 5]), LAYDOWN])


def test_the_lift_by_hand():
    (lift,) = study(model()).lifts
    radius = math.hypot(20 - 24, 20 - 6)  # 14.560
    gross = 12 * 1.1 * 1.05  # 13.86 t
    assert lift.pad == "PAD" and lift.radius_m == pytest.approx(radius, abs=1e-3)
    assert lift.gross_t == pytest.approx(gross, abs=1e-3)
    assert lift.moment_tm == pytest.approx(gross * radius, abs=1e-2)  # 201.80 t m
    assert lift.required_t == pytest.approx(gross / 0.75, abs=1e-3)  # 18.48 t
    assert lift.lift_height_m == 0.5 and lift.hook_height_m == 6.5  # 0.5 + 3 + 3
    assert lift.laydown == "LD" and lift.status == "lane clear"


def test_a_building_crane_must_carry_the_gross_load():
    from tests.test_layout_engineering_rules import building

    b1 = building(
        "buildings:\n  - id: B1\n    origin: [10, 10]\n    width: 20\n    depth: 20\n"
        "    walls: all\n    levels: [{id: G, elevation: 0, height: 10}]\n"
    )
    b1["crane"] = {"capacity_t": 12.0}  # the item's weight, less than 13.86 t gross
    (lift,) = study(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN])).lifts
    assert lift.crane == "building B1" and lift.gross_t == pytest.approx(13.86)
    assert lift.building_crane_t == 12.0 and lift.status == "building crane 12 t short"
    # the capacity needed under an overhead crane is the gross load, not gross / utilisation
    assert lift.required_t == pytest.approx(13.86) and lift.chart_capacity_t == 12.0
    b1["crane"] = {"capacity_t": 14.0}
    (lift,) = study(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN])).lifts
    assert lift.status == "building crane 14 t carries it"
    assert lift.utilisation == pytest.approx(13.86 / 14, abs=1e-3)
    del b1["crane"]
    (lift,) = study(base(equipment=[heavy()], buildings=[b1], zones=[LAYDOWN])).lifts
    assert lift.status == "no crane" and lift.chart_capacity_t is None


def test_a_chart_carries_the_lift_at_the_next_tabulated_radius():
    result = study(model(), charts=charts([(10, 40), (15, 20), (20, 12)]))
    (lift,) = result.lifts
    assert (lift.chart_radius_m, lift.chart_capacity_t) == (15, 20)
    assert lift.utilisation == pytest.approx(13.86 / 20, abs=1e-3)
    assert not result.findings
    short = study(model(), charts=charts([(10, 40), (15, 18)]))
    (f,) = short.findings
    assert f.rule == "cheme.layout-lifting-capacity" and "MC-1 lifts 18 t at 15 m" in f.message
    beyond = study(model(), charts=charts([(10, 40), (12, 30)]))
    assert "beyond the chart" in beyond.findings[0].message
    low_hook = study(model(), charts=charts([(20, 40)], max_hook_height_m=6.0))
    assert "hook height 6.5 m" in low_hook.findings[0].message
    other_pad = study(model(), charts=charts([(20, 40)], pads=["ELSEWHERE"]))
    assert "no crane chart is for that pad" in other_pad.findings[0].message


def test_the_heaviest_part_is_lifted_when_given():
    # a machine train with no weight of its own but a 30 t motor: 30 x 1.1 x 1.05 = 34.65 t
    # gross under a 40 t building crane
    from tests.test_layout_engineering_rules import building

    b1 = building(
        "buildings:\n  - id: B1\n    origin: [10, 10]\n    width: 20\n    depth: 20\n"
        "    walls: all\n    levels: [{id: G, elevation: 0, height: 10}]\n"
    )
    b1["crane"] = {"capacity_t": 40.0}
    item = heavy()
    item["dimensions"] = {k: v for k, v in item["dimensions"].items() if k != "weight"}
    item["dimensions"]["lift_weight"] = 30.0
    result = study(base(equipment=[item], buildings=[b1], zones=[LAYDOWN]))
    (lift,) = result.lifts
    assert lift.part and lift.weight_t == 30.0 and lift.gross_t == pytest.approx(34.65)
    # the review's case: 46.2 t (gross / 0.75) was printed as needed under a 40 t crane
    assert lift.status == "building crane 40 t carries it" and lift.required_t == 34.65
    row = next(r for r in study_markdown(result).splitlines() if "K-1 (heaviest part)" in r)
    assert "| 34.65 |" in row and "| 40 | building crane 40 t carries it" in row
    assert "46.2" not in row


def test_the_report_states_its_basis():
    result = study(model())
    text = study_markdown(result)
    assert "No crane load chart is given" in text and "lift_dynamic_factor" in text
    assert study_csv(result).splitlines()[1].startswith("K-1,12,mobile,PAD,14.56,13.86,")


def test_the_lifting_requirement(tmp_path: Path):
    (tmp_path / "plant.yaml").write_text("project: {name: t}\n", encoding="utf-8")
    workspace = Workspace(tmp_path)
    lane = Finding(LAYOUT_MODEL_FILE, "warning", "cheme.layout-lifting", "x", key="K-1")
    (problem,) = layout_gate(workspace, ["lifting"], [lane])
    assert "1 lifting findings" in problem
    accept = [{"id": lane.id, "reason": "lifting plan LP-1"}]
    from chemeascode.foundation.schemas.checks import Accept

    assert not layout_gate(
        workspace, ["lifting"], [lane], accept=[Accept.model_validate(a) for a in accept]
    )
    (problem,) = layout_gate(workspace, ["lifting-current"], [])
    assert "no layout/lifting-study.csv" in problem
