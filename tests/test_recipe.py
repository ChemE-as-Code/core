"""The batch recipe (``process/recipe.yaml``, ADR 0051): the cycle time from the unit
procedures, the bottleneck and parallel units, durations from a semi-batch's model, the basis
check against the flowsheet, the Gantt chart and the TEA's batch operation taken from it."""

import copy
import json
import math
import sys

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import Recipe, gantt_svg, recipe_report, recipe_text
from chemeascode.foundation.workspace import Workspace
from tests.test_semibatch import FLOWSHEET, MATERIALS, REACTIONS

# the semi-batch of test_semibatch (5 kmol S charged, 1 kmol A dosed over 1 h) with 30 min of
# post-reaction, then a cooler after it: two units
TWO_UNITS = (
    FLOWSHEET.replace(
        "dosing: [{stream: S2, time: 3600}], ", "dosing: [{stream: S2, time: 3600}], time: 1800, "
    )
    .replace(
        "  - id: S3\n    from: R.out\n    to: P.in\n    template: liquid\n",
        "  - id: S3\n    from: R.out\n    to: C.in\n    template: liquid\n"
        "  - id: S4\n    from: C.out\n    to: P.in\n    template: liquid\n",
    )
    .replace(
        "streams:\n",
        "  - id: C\n    class: Cooling\n"
        "    ports: [{id: in, direction: in}, {id: out, direction: out}]\nstreams:\n",
        1,
    )
)


def _hours(value, unit="h"):
    return {"value": value, "unit": unit, "provenance": "assumed"}


#: R: charge 0.5 h, dose 1 h and react 0.5 h (from the model), transfer 0.5 h, clean 2 h:
#: 4.5 h; C: 3 h of cooling and 1 h of holding: 4 h. The bottleneck is R: 8000 h / 4.5 h.
#: S3 is 6 kmol x 44.05 kg/kmol = 264.3 kg/h in the flowsheet, so a batch of 264.3 x 4.5 kg.
RECIPE = {
    "schema": "cheme/recipe/v1",
    "kind": "recipe",
    "title": "test batch",
    "batch_size": {"value": 264.3 * 4.5, "unit": "kg", "stream": "S3", "provenance": "assumed"},
    "hours_per_year": {"value": 8000, "provenance": "assumed"},
    "unit_procedures": [
        {
            "id": "UP1",
            "unit": "R",
            "operations": [
                {"id": "charge", "kind": "charge", "duration": _hours(30, "min")},
                {"id": "dose", "kind": "dose", "from": "R"},
                {"id": "react", "kind": "react", "from": "R"},
                {"id": "transfer", "kind": "transfer", "duration": _hours(0.5)},
                {"id": "clean", "kind": "clean", "duration": _hours(2.0)},
            ],
        },
        {
            "id": "UP2",
            "unit": "C",
            "operations": [
                {"id": "cool", "kind": "cool", "duration": _hours(3.0)},
                {"id": "hold", "kind": "hold", "duration": _hours(1.0)},
            ],
        },
    ],
}


def _plant(tmp_path, recipe=RECIPE, propagate=True):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: recipe-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(TWO_UNITS)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    if recipe is not None:
        (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    ws = Workspace(root)
    if propagate:
        process, _ = load(root)
        run(ws, process, "design", write=True)
    return ws


def _recipe_findings(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [f for f in rules(process) if f.rule.startswith("cheme.recipe-")]


def test_the_cycle_time_is_the_bottleneck_and_the_rates_agree(tmp_path):
    ws = _plant(tmp_path)
    result = recipe_report(ws.root)
    assert result.cycle_time == pytest.approx(4.5)
    assert result.bottleneck == "UP1"
    assert result.batches_per_year == pytest.approx(8000 / 4.5)
    occupancy = {u.procedure: u.occupancy for u in result.units}
    assert occupancy == pytest.approx({"UP1": 4.5, "UP2": 4.0})
    assert {u.procedure: u.utilisation for u in result.units}["UP2"] == pytest.approx(4 / 4.5)
    # the cooler takes the batch when the reactor starts to transfer it (at 2 h)
    cool = next(s for s in result.steps if s.operation == "cool")
    assert cool.start == pytest.approx(2.0)
    assert result.makespan == pytest.approx(6.0)
    dose = next(s for s in result.steps if s.operation == "dose")
    assert (dose.start, dose.end, dose.basis) == (
        pytest.approx(0.5),
        pytest.approx(1.5),
        "calculated",
    )
    assert result.rate == pytest.approx(264.3, rel=1e-9)
    assert result.flowsheet_rate == pytest.approx(264.3, rel=1e-6)
    assert not _recipe_findings(ws)
    text = recipe_text(result)
    assert "cycle time 4.5 h (bottleneck UP1)" in text and "(from the model)" in text


def test_parallel_units_move_the_bottleneck(tmp_path):
    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][0]["parallel"] = 2
    recipe["batch_size"]["value"] = 264.3 * 4.0
    result = recipe_report(_plant(tmp_path, recipe).root)
    assert result.bottleneck == "UP2" and result.cycle_time == pytest.approx(4.0)
    assert {u.procedure: u.cycle for u in result.units}["UP1"] == pytest.approx(2.25)


def test_a_flowsheet_on_another_basis_is_a_finding(tmp_path):
    recipe = copy.deepcopy(RECIPE)
    recipe["batch_size"]["value"] = 2000.0
    (finding,) = _recipe_findings(_plant(tmp_path, recipe))
    assert finding.rule == "cheme.recipe-basis" and finding.level == "warning"
    assert "264.3 kg/h in the flowsheet" in finding.message
    assert finding.line is not None
    # before propagate the outlet has no flow: nothing to compare, said as info
    (info,) = _recipe_findings(_plant(tmp_path / "b", recipe, propagate=False))
    assert info.level == "info" and "no flow" in info.message


def test_a_batch_size_in_m3_is_compared_on_the_liquid_volume(tmp_path):
    recipe = copy.deepcopy(RECIPE)
    recipe["batch_size"] = {
        "value": 0.6 * 4.5,
        "unit": "m3",
        "stream": "S3",
        "provenance": "assumed",
    }
    ws = _plant(tmp_path, recipe)
    result = recipe_report(ws.root)
    assert result.flowsheet_rate == pytest.approx(0.6, rel=1e-6)  # 6 kmol x 0.1 m3/kmol
    assert not _recipe_findings(ws)


def test_recipe_references(tmp_path):
    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][1]["unit"] = "X"
    recipe["unit_procedures"][1]["operations"][0] = {"id": "cool", "kind": "dose", "from": "C"}
    recipe["unit_procedures"][1]["start"] = {"after": "UP9"}
    messages = [f.message for f in _recipe_findings(_plant(tmp_path, recipe))]
    assert any("unit X is no block or step" in m for m in messages)
    assert any("C is no batch or semibatch" in m for m in messages)
    assert any("start.after UP9 is no earlier unit procedure" in m for m in messages)
    with pytest.raises(ValueError, match="duration, from or temperatures"):
        Recipe.model_validate(
            RECIPE
            | {
                "unit_procedures": [
                    {"id": "U", "unit": "R", "operations": [{"id": "a", "kind": "charge"}]}
                ]
            }
        )
    with pytest.raises(ValueError, match="dose's or a reaction's time only"):
        Recipe.model_validate(
            RECIPE
            | {
                "unit_procedures": [
                    {
                        "id": "U",
                        "unit": "R",
                        "operations": [{"id": "a", "kind": "cool", "from": "R"}],
                    }
                ]
            }
        )


def test_a_schema_error_in_the_recipe(tmp_path):
    ws = _plant(tmp_path, RECIPE | {"hours_per_year": {"value": 9999, "provenance": "assumed"}})
    (finding,) = _recipe_findings(ws)
    assert finding.rule == "cheme.recipe-schema"


def test_the_gantt_chart_and_the_command(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path)
    svg = gantt_svg(recipe_report(ws.root))
    assert svg.startswith("<svg") and "prefers-color-scheme: dark" in svg
    assert svg.count('<rect class="bar') >= 7 and "UP1 dose (dose): 0.5 to 1.5 h" in svg
    monkeypatch.chdir(ws.root)
    out = CliRunner().invoke(app, ["process", "recipe", "--svg", "gantt.svg"])
    assert out.exit_code == 0, out.output
    assert (ws.root / "gantt.svg").read_text().startswith("<svg")
    out = CliRunner().invoke(app, ["process", "recipe", "--json"])
    assert json.loads(out.output)["bottleneck"] == "UP1"
    (ws.root / "process/recipe.yaml").unlink()
    assert CliRunner().invoke(app, ["process", "recipe"]).exit_code == 2


def test_the_tea_takes_its_batches_from_the_recipe(tmp_path):
    from chemeascode.domains.assessment.tea.schemas import Batch

    assert Batch.model_validate({"recipe": True, "source": "the recipe"})
    with pytest.raises(ValueError, match="cycle_time and basis_hours, or recipe"):
        Batch.model_validate({"source": "the recipe"})
    with pytest.raises(ValueError, match="remove cycle_time"):
        Batch.model_validate(
            {"recipe": True, "cycle_time": {"value": 4, "source": "x" * 3}, "source": "abc"}
        )
    import shutil

    from chemeascode.domains.assessment.tea.report import tea_report
    from tests.test_assessment_tea import EXAMPLE, premises, write

    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    # the example's product S3 is 400 kg/h: 8 h per batch of 3200 kg, 1000 batches in 8000 h
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {"value": 3200, "unit": "kg", "stream": "S3", "provenance": "assumed"},
        "hours_per_year": {"value": 8000, "provenance": "assumed"},
        "unit_procedures": [
            {
                "id": "SEPARATE",
                "unit": "SEP",
                "operations": [
                    {"id": "charge", "kind": "charge", "duration": _hours(1)},
                    {"id": "run", "kind": "other", "duration": _hours(6)},
                    {"id": "clean", "kind": "clean", "duration": _hours(1)},
                ],
            }
        ],
    }
    (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    data = premises()
    data["operation"]["batch"] = {"recipe": True, "source": "process/recipe.yaml"}
    write(root, data)
    report = tea_report(root)
    assert report.loaded, [f.format() for f in report.findings]
    assert report.batches == pytest.approx(1000)
    assert report.results()["operating_hours"] == pytest.approx(8000)
    assert report.operation()["cycle_time"] == pytest.approx(8.0)
    assert not [f for f in report.findings if f.rule == "cheme.tea-batch-recipe"]
    # the recipe on 7000 h and the TEA on 8000 h: one basis, please
    recipe["hours_per_year"]["value"] = 7000
    recipe["batch_size"]["value"] = 3200 * 8 / 7
    (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    report = tea_report(root)
    assert any(f.rule == "cheme.tea-batch-recipe" for f in report.findings)
    # and without a recipe the TEA says so
    (root / "process/recipe.yaml").unlink()
    report = tea_report(root)
    assert any(f.rule == "cheme.tea-batch-recipe" and f.level == "error" for f in report.findings)


# -- vessels and jackets (core#158 package 3) ---------------------------------------------------


def _jacketed(coolant=250.0, **vessel):
    recipe = copy.deepcopy(RECIPE)
    up = recipe["unit_procedures"][0]
    up["vessel"] = {
        "fill_fraction": 0.8,
        "jacket": {
            "u": 400,
            "coolant_temperature": coolant,
            "heating_temperature": 350,
            "provenance": "assumed",
        },
        "provenance": "assumed",
    } | vessel
    return recipe


def test_the_vessel_is_the_batch_over_the_fill_fraction_rounded_to_a_preferred_size(tmp_path):
    from chemeascode.domains.process.recipe import preferred

    assert [preferred(v) for v in (0.07, 1.0, 3.375, 9.0, 63.1)] == [0.08, 1.0, 4.0, 10.0, 80.0]
    result = recipe_report(_plant(tmp_path, _jacketed()).root)
    (vessel,) = result.vessels
    # the batch is 4.5 h of the flowsheet's flows: 0.6 m3/h at the end of the dosing
    assert vessel.working_volume == pytest.approx(2.7, rel=1e-6)
    assert vessel.volume == pytest.approx(4.0) and vessel.rounded
    assert vessel.fill == pytest.approx(2.7 / 4.0, rel=1e-6)
    assert vessel.diameter == pytest.approx((16 / math.pi) ** (1 / 3), rel=1e-9)
    # the semi-batch's peak cooling duty per m3 times the batch's end volume
    assert vessel.peak_duty == pytest.approx(46.3 * 2.7, rel=2e-3)
    d = vessel.diameter
    bottom = math.pi * d**2 / 4
    area = math.pi * d * (2.25 / bottom) + bottom  # wetted at the charge, 2.25 m3
    assert vessel.jacket_area == pytest.approx(area, rel=1e-9)
    assert vessel.removable == pytest.approx(0.4 * area * 50.0, rel=1e-9)
    assert "preferred size" in recipe_text(result)


def test_a_jacket_too_small_for_the_peak_duty_is_a_finding(tmp_path):
    ws = _plant(tmp_path, _jacketed(coolant=280.0))
    (finding,) = _recipe_findings(ws)
    assert finding.rule == "cheme.recipe-jacket" and finding.level == "warning"
    assert "exceeds what the jacket removes" in finding.message
    ws = _plant(tmp_path / "b", _jacketed(volume=2.5))
    messages = [f.message for f in _recipe_findings(ws) if f.rule == "cheme.recipe-vessel"]
    assert messages and "108% full" in messages[0]


def test_a_programme_s_jacket_check_takes_its_lowest_temperature(tmp_path, monkeypatch):
    """Dosed at 300 K, held at 340 K (ADR 0074): the peak duty falls in the dosing, where the
    jacket removes least, so the check takes 300 K, not the programme's end."""
    program = "program: {points: [[0, 300], [3600, 300], [3700, 340]], provenance: assumed}, "
    monkeypatch.setattr(
        sys.modules[__name__], "TWO_UNITS", TWO_UNITS.replace("batch: {", "batch: {" + program, 1)
    )
    ws = _plant(tmp_path, _jacketed(coolant=280.0))
    (vessel,) = recipe_report(ws.root).vessels
    assert vessel.process_temperature == pytest.approx(300.0)
    assert vessel.removable == pytest.approx(0.4 * vessel.jacket_area * 20.0, rel=1e-9)
    (finding,) = _recipe_findings(ws)
    assert finding.rule == "cheme.recipe-jacket" and finding.level == "warning"


def test_heat_up_and_cool_down_times_from_the_jacket(tmp_path):
    recipe = _jacketed()
    ops = recipe["unit_procedures"][0]["operations"]
    ops.insert(1, {"id": "heatup", "kind": "heat", "temperatures": [290, 300]})
    ops.insert(4, {"id": "cooldown", "kind": "cool", "temperatures": [300, 290]})
    result = recipe_report(_plant(tmp_path, recipe).root)
    d = (16 / math.pi) ** (1 / 3)
    bottom = math.pi * d**2 / 4

    def time(capacity, volume, medium, start, end):
        ua = 0.4 * (math.pi * d * volume / bottom + bottom)
        return capacity / ua * math.log((medium - start) / (medium - end)) / 3600

    steps = {s.operation: s for s in result.steps if s.procedure == "UP1"}
    heat, cool = steps["heatup"], steps["cooldown"]
    # before the dose: the charge, 5 kmol/h x 150 kJ/(kmol K) x 4.5 h, in 2.25 m3
    assert heat.end - heat.start == pytest.approx(time(5 * 150 * 4.5, 2.25, 350, 290, 300))
    # after it: the end's content, 6 kmol/h, in 2.7 m3
    assert cool.end - cool.start == pytest.approx(time(6 * 150 * 4.5, 2.7, 250, 300, 290))
    assert heat.basis == cool.basis == "calculated"
    assert steps["dose"].start == pytest.approx(heat.end)
    # a medium that cannot reach the end temperature
    ops[1]["temperatures"] = [290, 360]
    messages = [f.message for f in _recipe_findings(_plant(tmp_path / "b", recipe))]
    assert any("cannot heat the content to 360 K" in m for m in messages)
    with pytest.raises(ValueError, match="rising to heat"):
        Recipe.model_validate(
            RECIPE
            | {
                "unit_procedures": [
                    {
                        "id": "U",
                        "unit": "R",
                        "operations": [{"id": "a", "kind": "heat", "temperatures": [300, 290]}],
                    }
                ]
            }
        )


def test_no_heat_of_reaction_means_no_jacket_check_said_as_info(tmp_path):
    ws = _plant(tmp_path, _jacketed(coolant=299.0))
    path = ws.root / "process/reactions.yaml"
    path.write_text(
        path.read_text().replace(
            "     heat_of_reaction: {value: -100000, provenance: assumed},\n", ""
        )
    )
    result = recipe_report(ws.root)
    (vessel,) = result.vessels
    assert vessel.peak_duty is None
    (finding,) = [f for f in result.findings if f.rule == "cheme.recipe-jacket"]
    assert finding.level == "info" and "no peak duty" in finding.message


def test_a_duplicate_operation_id_is_found_with_jacket_times(tmp_path):
    recipe = _jacketed()
    ops = recipe["unit_procedures"][0]["operations"]
    ops.insert(1, {"id": "charge", "kind": "heat", "temperatures": [290, 300]})
    messages = [f.message for f in _recipe_findings(_plant(tmp_path, recipe))]
    assert any("operation charge twice" in m for m in messages)


def test_a_vessel_of_several_steps_is_sized_from_its_one_batch_step(tmp_path):
    """units: [R, C] (ADR 0057): R's batch sizes the vessel, labelled R+C, and datasheets fill
    still finds it as R's."""
    from chemeascode.domains.equipment.fill import _recipe_vessel

    recipe = _jacketed()
    up = recipe["unit_procedures"][0]
    up.pop("unit")
    up["units"] = ["R", "C"]
    recipe["unit_procedures"].pop(1)
    ws = _plant(tmp_path, recipe)
    result = recipe_report(ws.root)
    (vessel,) = result.vessels
    assert vessel.unit == "R+C" and vessel.working_volume == pytest.approx(2.7, rel=1e-6)
    process, _ = load(ws.root)
    found = _recipe_vessel(process, "R", "design")
    assert found is not None and found.volume == pytest.approx(vessel.volume)
    assert _recipe_vessel(process, "C", "design") is None


def test_a_vessel_holding_two_batch_steps_says_which_one_is_not_named(tmp_path):
    """A block or units holding two batch or semibatch steps: the vessel is not sized from the
    first in YAML order, it is cheme.recipe-reference."""
    flowsheet = TWO_UNITS.replace(
        "  - id: C\n    class: Cooling\n",
        "  - id: C\n    class: ReactingChemicals\n    reactions: [R1]\n    reactor: batch\n"
        "    batch: {time: 600, provenance: assumed}\n",
    )
    assert flowsheet != TWO_UNITS
    recipe = _jacketed()
    up = recipe["unit_procedures"][0]
    up.pop("unit")
    up["units"] = ["R", "C"]
    recipe["unit_procedures"].pop(1)
    ws = _plant(tmp_path, recipe, propagate=False)
    (ws.root / "process/flowsheet.yaml").write_text(flowsheet)
    result = recipe_report(ws.root)
    assert not result.vessels
    (finding,) = [f for f in result.findings if f.rule == "cheme.recipe-reference"]
    assert finding.level == "error" and "R+C holds R, C: several batch" in finding.message
    assert finding.line is not None and finding.hint
