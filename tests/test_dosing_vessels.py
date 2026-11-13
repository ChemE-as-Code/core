"""Dosing and vessels (ADR 0073, core#184 part A): the shortest dosing the jacket allows against
the closed form of a first-order semi-batch, a vessel over several batch steps and over a step
that adds a second portion, a transfer timed by the next vessel's dose, coupled vessels whose
vent doses another, and a dosed gas passing through without ideal-gas data."""

import copy
import json
import math

import pytest
import yaml

from chemeascode.domains.process.dosing import (
    SCALE_MAX,
    SCALE_MIN,
    SCALE_TOLERANCE,
    deviation,
    shortest_factor,
)
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import recipe_report, recipe_text
from chemeascode.domains.process.schema import Dosing
from chemeascode.domains.process.stirred_tank import solve_node, tank_inlet
from tests import test_recipe as plain
from tests import test_semibatch_vent as vented

HEAT = 1e5  # kJ/kmol released by R1 in the fixtures
K = 0.01  # 1/s, R1's rate constant
BATCH = 4.5  # h of flows per batch in test_recipe's RECIPE


# -- the shortest dosing ------------------------------------------------------------------------


def test_the_shortest_factor_brackets_and_bisects():
    # a peak inversely proportional to the dosing time: P0 / s against R
    found = shortest_factor(lambda s: 120.0 / s, 50.0)
    assert found.factor == pytest.approx(2.4, rel=SCALE_TOLERANCE)
    assert found.peak <= 50.0 and found.runs > 3
    found = shortest_factor(lambda s: 120.0 / s, 500.0)
    assert found.factor == pytest.approx(0.24, rel=SCALE_TOLERANCE)
    # a jacket that removes any peak, and one no dosing helps (a floor of 80 kW)
    assert shortest_factor(lambda s: 1.0 / s, 1e6).factor is None
    assert f"{SCALE_MIN:g} of the dosing time" in shortest_factor(lambda s: 1 / s, 1e6).reason
    none = shortest_factor(lambda s: 80.0 + 1.0 / s, 50.0)
    assert none.factor is None and f"{SCALE_MAX:g} times" in none.reason
    assert shortest_factor(lambda s: None, 50.0).reason == "the model gives no peak duty"


def _shortest_recipe(coolant=280.0):
    recipe = plain._jacketed(coolant=coolant)
    recipe["unit_procedures"][0]["vessel"]["jacket"]["shortest_dosing"] = True
    return recipe


def test_the_shortest_dosing_the_jacket_allows_meets_its_removable_duty(tmp_path):
    """First order, A dosed at a constant rate over t_d into an isothermal charge: the heat
    rate is largest when the dosing ends, ``Q = -dH F (1 - exp(-k t_d)) / t_d`` with F the kmol
    of A one batch doses; the shortest t_d is where Q equals what the jacket removes."""
    result = recipe_report(plain._plant(tmp_path, _shortest_recipe()).root)
    (vessel,) = result.vessels
    (limit,) = result.dosing
    assert (limit.procedure, limit.unit, limit.declared) == ("UP1", "R", pytest.approx(1.0))
    assert limit.removable == pytest.approx(vessel.removable, rel=1e-12)
    dosed = 1.0 * BATCH  # kmol of A per batch: 1 kmol per hour of flows

    def closed(hours):
        t = hours * 3600.0
        return HEAT * dosed * (1 - math.exp(-K * t)) / t

    # the declared hour is too short for the jacket (the recipe's warning), the shortest longer
    assert closed(1.0) > vessel.removable
    assert limit.shortest > 1.0
    assert closed(limit.shortest) == pytest.approx(vessel.removable, rel=3e-3)
    assert limit.peak_duty == pytest.approx(closed(limit.shortest), rel=3e-3)
    assert limit.peak_duty <= vessel.removable
    assert any(f.rule == "cheme.recipe-jacket" and f.level == "warning" for f in result.findings)
    text = recipe_text(result)
    assert "shortest dosing of R (UP1) the jacket allows: " in text
    assert json.loads(json.dumps(result.as_dict()))["dosing"][0]["shortest"] == limit.shortest
    # a colder coolant: the declared dosing could be shorter
    cold = recipe_report(plain._plant(tmp_path / "cold", _shortest_recipe(200.0)).root)
    assert cold.dosing[0].shortest < 1.0


def test_without_the_option_a_recipe_reports_as_before(tmp_path):
    result = recipe_report(plain._plant(tmp_path, plain._jacketed()).root)
    found = result.as_dict()
    assert "dosing" not in found and "steps" not in found["vessels"][0]
    from chemeascode.domains.process.recipe import Jacket

    jacket = Jacket.model_validate({"u": 400, "provenance": "assumed"})
    assert "shortest_dosing" not in jacket.model_dump()


def test_the_shortest_dosing_says_why_there_is_none(tmp_path):
    recipe = _shortest_recipe()
    del recipe["unit_procedures"][0]["vessel"]["jacket"]["coolant_temperature"]
    result = recipe_report(plain._plant(tmp_path, recipe).root)
    (limit,) = result.dosing
    assert limit.shortest is None and limit.reason == "no vessel.jacket.coolant_temperature"
    assert "none: no vessel.jacket.coolant_temperature" in recipe_text(result)


# -- a vessel over several steps ----------------------------------------------------------------

#: R (semi-batch) then C, a batch of R's outlet, in one vessel
TWO_BATCHES = plain.TWO_UNITS.replace(
    "  - id: C\n    class: Cooling\n",
    "  - id: C\n    class: ReactingChemicals\n    reactions: [R1]\n    reactor: batch\n"
    "    batch: {time: 600, provenance: assumed}\n",
)


def _one_pot(**vessel):
    recipe = plain._jacketed(**vessel)
    up = recipe["unit_procedures"][0]
    up.pop("unit")
    up["units"] = ["R", "C"]
    up["operations"] = [
        {"id": "heat", "kind": "heat", "temperatures": [290.0, 300.0]},
        {"id": "dose", "kind": "dose", "from": "R"},
        {"id": "react", "kind": "react", "from": "R"},
        {"id": "warm", "kind": "heat", "temperatures": [300.0, 310.0]},
        {"id": "react2", "kind": "react", "from": "C"},
        {"id": "cool", "kind": "cool", "temperatures": [300.0, 280.0]},
    ]
    recipe["unit_procedures"].pop(1)
    return recipe


def _two_batches(tmp_path, recipe, flowsheet=TWO_BATCHES):
    ws = plain._plant(tmp_path, recipe, propagate=False)
    (ws.root / "process/flowsheet.yaml").write_text(flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    return ws


def test_a_vessel_over_two_batch_steps_is_sized_and_checked_for_each(tmp_path):
    from chemeascode.domains.process.recipe import _content_of, load_recipe

    ws = _two_batches(tmp_path, _one_pot(coolant=280.0))
    result = recipe_report(ws.root)
    assert not [f for f in result.findings if f.rule == "cheme.recipe-reference"]
    (vessel,) = result.vessels
    assert [s["step"] for s in vessel.steps] == ["R", "C"]
    process, _ = load(ws.root)
    recipe, _, _ = load_recipe(ws.root)
    contents = {s: _content_of(process, recipe, s, "design") for s in ("R", "C")}
    largest = max(max(c.charge_volume, c.end_volume) for c in contents.values())
    assert vessel.working_volume == pytest.approx(largest, rel=1e-12)
    for own in vessel.steps:
        c = contents[own["step"]]
        assert own["charge_volume"] == pytest.approx(c.charge_volume, rel=1e-12)
        area = (
            plain.math.pi * vessel.diameter * c.charge_volume / (math.pi * vessel.diameter**2 / 4)
            + math.pi * vessel.diameter**2 / 4
        )
        assert own["jacket_area"] == pytest.approx(area, rel=1e-9)
        assert own["peak_duty"] == pytest.approx(c.peak_duty, rel=1e-12)
    # R's dosing is too fast for the jacket, C's batch of what is left is not: one warning
    jackets = [f for f in result.findings if f.rule == "cheme.recipe-jacket"]
    assert [f.level for f in jackets] == ["warning"] and "UP1 (R):" in jackets[0].message
    # the heat-up before R's dose takes R's charge, the warming before C's batch C's charge
    # (R's end), the cool-down C's end
    times = {s.operation: s.end - s.start for s in result.steps}
    ua = 0.4 * vessel.steps[0]["jacket_area"]
    heat = contents["R"].charge_capacity / ua * math.log((350 - 290) / (350 - 300)) / 3600
    assert times["heat"] == pytest.approx(heat, rel=1e-9)
    ua = 0.4 * vessel.steps[1]["jacket_area"]
    warm = contents["C"].charge_capacity / ua * math.log((350 - 300) / (350 - 310)) / 3600
    assert times["warm"] == pytest.approx(warm, rel=1e-9)
    assert "    R: " in recipe_text(result) and "    C: " in recipe_text(result)
    # datasheets fill finds each step's own peak duty
    from chemeascode.domains.process.recipe import batch_vessel, evaluate

    evaluated = evaluate(process, recipe)
    for step in ("R", "C"):
        own = batch_vessel(process, recipe, evaluated, step)
        assert own.peak_duty == pytest.approx(contents[step].peak_duty, rel=1e-12)


def test_each_vented_step_of_a_vessel_reports_its_vent(tmp_path):
    flowsheet = vented.FLOWSHEET.replace(
        "  - id: S3\n    from: R.out\n    to: P.in\n    template: liquid\n",
        "  - id: S3\n    from: R.out\n    to: C.in\n    template: liquid\n"
        "  - id: S5\n    from: C.out\n    to: P.in\n    template: liquid\n"
        "  - id: S6\n    from: C.gas\n    to: OFFGAS.in\n    template: gas\n",
    ).replace(
        "streams:\n",
        "  - id: C\n    class: ReactingChemicals\n    reactions: [R1]\n    reactor: batch\n"
        "    batch: {time: 600, vent: {stream: S6, components: [G]}, provenance: assumed}\n"
        "    ports: [{id: in, direction: in}, {id: out, direction: out}, "
        "{id: gas, direction: out}]\n"
        "streams:\n",
        1,
    )
    ws = vented._plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    s5 = vented._states(ws)["S5"]["flow"]["value"]
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {"value": 2 * s5, "unit": "kg", "stream": "S5", "provenance": "assumed"},
        "hours_per_year": {"value": 8000, "provenance": "assumed"},
        "unit_procedures": [
            {
                "id": "POT",
                "units": ["R", "C"],
                "operations": [
                    {"id": "dose", "kind": "dose", "from": "R"},
                    {"id": "react", "kind": "react", "from": "C"},
                ],
            }
        ],
    }
    (ws.root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe))
    result = recipe_report(ws.root)
    assert not [f for f in result.findings if f.level == "error"], result.findings
    assert [(v.unit, v.stream) for v in result.vents] == [("R", "S4"), ("C", "S6")]
    # what R left of A reacts in C and vents there: together the whole kmol per hour of flows
    total = sum(v.kmol["G"] for v in result.vents)
    left = (1 - math.exp(-K * 3600)) / (K * 3600)
    assert result.vents[0].kmol["G"] == pytest.approx(2 * (1 - left), rel=1e-5)
    assert total == pytest.approx(2 * (1 - left * math.exp(-K * 600)), rel=1e-5)


def test_a_step_that_takes_in_more_than_the_batch_is_a_finding_or_sizes_the_vessel(tmp_path):
    """TsCl L-1: a step after the batch in the same vessel adds a second portion (3 kmol/h of S
    into C): 0.9 m3/h, 4.05 m3 per batch against the semi-batch's 2.7 m3."""
    flowsheet = (
        plain.TWO_UNITS.replace(
            "  - id: C\n    class: Cooling\n    ports: [{id: in, direction: in}, ",
            "  - id: C\n    class: Mixing\n    ports: [{id: in, direction: in}, "
            "{id: second, direction: in}, ",
        ).replace("feeds:\n", "feeds:\n  - {id: H, ports: [{id: out, direction: out}]}\n")
        + "  - id: S5\n    from: H.out\n    to: C.second\n    template: liquid\n"
        "    state:\n      design:\n"
        "        temperature: {value: 300, provenance: given}\n"
        "        pressure: {value: 101.325, provenance: given}\n"
        "        flow: {value: 3, provenance: given}\n"
        "        composition: {basis: mole_fraction, values: {S: 1.0}, provenance: given}\n"
    )
    recipe = plain._jacketed()
    up = recipe["unit_procedures"][0]
    up.pop("unit")
    up["units"] = ["R", "C"]
    recipe["unit_procedures"].pop(1)
    recipe["batch_size"]["value"] = 9 * 44.05 * BATCH  # S4 carries the 9 kmol/h
    recipe["batch_size"]["stream"] = "S4"
    ws = _two_batches(tmp_path, recipe, flowsheet)
    result = recipe_report(ws.root)
    (vessel,) = result.vessels
    assert vessel.working_volume == pytest.approx(2.7, rel=1e-6)  # as before: R's batch
    (finding,) = [f for f in result.findings if f.rule == "cheme.recipe-vessel"]
    assert finding.level == "warning" and "C takes in 4.05 m3 per batch" in finding.message
    assert finding.line is not None
    recipe["unit_procedures"][0]["vessel"]["size_from"] = "steps"
    (ws.root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    result = recipe_report(ws.root)
    (vessel,) = result.vessels
    assert vessel.working_volume == pytest.approx(4.05, rel=1e-6)
    assert vessel.volume == pytest.approx(6.3)  # 4.05 / 0.8 = 5.06, rounded up to R10
    assert not [f for f in result.findings if f.rule == "cheme.recipe-vessel"]
    # the jacket is still checked against R's peak, at R's charge in the larger vessel
    d = vessel.diameter
    bottom = math.pi * d**2 / 4
    assert vessel.jacket_area == pytest.approx(math.pi * d * 2.25 / bottom + bottom, rel=1e-9)


# -- a transfer timed by the next vessel's dose -------------------------------------------------

#: R's product S3 dosed into a second semi-batch Q over 2 h (its charge S6 from feed H)
INTO_Q = (
    plain.FLOWSHEET.replace(
        "dosing: [{stream: S2, time: 3600}], ", "dosing: [{stream: S2, time: 3600}], time: 1800, "
    )
    .replace(
        "  - id: S3\n    from: R.out\n    to: P.in\n    template: liquid\n",
        "  - id: S3\n    from: R.out\n    to: Q.dose\n    template: liquid\n"
        "  - id: S4\n    from: Q.out\n    to: P.in\n    template: liquid\n"
        "  - id: S6\n    from: H.out\n    to: Q.in\n    template: liquid\n"
        "    state:\n      design:\n"
        "        temperature: {value: 300, provenance: given}\n"
        "        pressure: {value: 101.325, provenance: given}\n"
        "        flow: {value: 2, provenance: given}\n"
        "        composition: {basis: mole_fraction, values: {S: 1.0}, provenance: given}\n",
    )
    .replace("feeds:\n", "feeds:\n  - {id: H, ports: [{id: out, direction: out}]}\n")
    .replace(
        "streams:\n",
        "  - id: Q\n    class: ReactingChemicals\n    reactions: [R1]\n    reactor: semibatch\n"
        "    batch: {dosing: [{stream: S3, time: 1800, start: 600}], time: 600, "
        "provenance: assumed}\n"
        "    ports: [{id: in, direction: in}, {id: dose, direction: in}, "
        "{id: out, direction: out}]\n"
        "streams:\n",
        1,
    )
)


def _into_q(tmp_path, transfer):
    recipe = copy.deepcopy(plain.RECIPE)
    recipe["batch_size"]["stream"] = "S4"
    recipe["batch_size"]["value"] = 8 * 44.05 * BATCH
    reactor, second = recipe["unit_procedures"]
    reactor["operations"][3] = transfer
    second["unit"] = "Q"
    second["operations"] = [
        {"id": "dose", "kind": "dose", "from": "Q"},
        {"id": "react", "kind": "react", "from": "Q"},
    ]
    return _two_batches(tmp_path, recipe, INTO_Q)


def test_a_transfer_takes_the_time_of_the_next_vessels_dose(tmp_path):
    ws = _into_q(tmp_path, {"id": "transfer", "kind": "transfer", "from": "Q"})
    result = recipe_report(ws.root)
    assert not [f for f in result.findings if f.level == "error"], result.findings
    step = next(s for s in result.steps if s.operation == "transfer")
    # Q doses S3 from 600 s for 1800 s: the transfer lasts 0.5 h, from the model
    assert step.end - step.start == pytest.approx(0.5) and step.basis == "calculated"
    assert Dosing.model_validate({"stream": "S3", "time": 1800, "start": 600}).segments() == [
        (600.0, 2400.0, 1.0)
    ]


def test_a_transfer_from_a_step_without_its_dose_is_a_reference_finding(tmp_path):
    ws = _into_q(tmp_path, {"id": "transfer", "kind": "transfer", "from": "R"})
    result = recipe_report(ws.root)
    (finding,) = [f for f in result.findings if f.rule == "cheme.recipe-reference"]
    assert "no dose of R takes what R makes" in finding.message and finding.level == "error"
    with pytest.raises(ValueError, match="from: gives"):
        from chemeascode.domains.process.recipe import Operation

        Operation.model_validate({"id": "x", "kind": "clean", "from": "Q"})


# -- coupled vessels ----------------------------------------------------------------------------

#: the vented semi-batch R of test_semibatch_vent: its vent S4 doses G into a second semi-batch
#: R2 (its charge S5 of S from feed H), where G reacts to B
COUPLED_MATERIALS = vented.MATERIALS.replace(
    "  - {id: G, name: G, formula: O, molar_mass: 16.0, normal_boiling_point: 188}",
    "  - {id: G, name: G, formula: O, molar_mass: 16.0, normal_boiling_point: 188,\n"
    "     liquid_molar_volume: 0.05, liquid_heat_capacity: 80}",
)
COUPLED_REACTIONS = vented.REACTIONS + (
    "  - {id: R2, stoichiometry: {G: -1, B: 1}, phase: liquid,\n"
    "     heat_of_reaction: {value: -50000, provenance: assumed},\n"
    "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.05},\n"
    "            orders: {G: 1}, provenance: assumed}}\n"
)
COUPLED = (
    vented.FLOWSHEET.replace(
        "    to: OFFGAS.in\n    template: gas\n", "    to: R2.dose\n    template: gas\n"
    )
    .replace("feeds:\n", "feeds:\n  - {id: H, ports: [{id: out, direction: out}]}\n")
    .replace(
        "  - {id: OFFGAS, ports: [{id: in, direction: in}]}\n",
        "  - {id: P2, ports: [{id: in, direction: in}]}\n",
    )
    .replace(
        "streams:\n",
        "  - id: R2\n    class: ReactingChemicals\n    reactions: [R2]\n    reactor: semibatch\n"
        "    batch: {dosing: [{stream: S4, time: 3600}], provenance: assumed}\n"
        "    ports: [{id: in, direction: in}, {id: dose, direction: in}, "
        "{id: out, direction: out}]\n"
        "streams:\n",
        1,
    )
    + "  - id: S5\n    from: H.out\n    to: R2.in\n    template: liquid\n"
    "    state:\n      design:\n"
    "        temperature: {value: 300, provenance: given}\n"
    "        pressure: {value: 101.325, provenance: given}\n"
    "        flow: {value: 5, provenance: given}\n"
    "        composition: {basis: mole_fraction, values: {S: 1.0}, provenance: given}\n"
    "  - id: S6\n    from: R2.out\n    to: P2.in\n    template: liquid\n"
)


def _coupled(tmp_path, flowsheet=COUPLED, recipe=None):
    ws = vented._plant(tmp_path, flowsheet, recipe)
    (ws.root / "process/materials.yaml").write_text(COUPLED_MATERIALS)
    (ws.root / "process/reactions.yaml").write_text(COUPLED_REACTIONS)
    return ws


def _coupling(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [f for f in rules(process) if f.rule == "cheme.process-coupled-dosing"]


def test_a_dose_of_another_vessels_vent_is_checked_against_its_gas(tmp_path):
    """R doses A at a constant rate q = 1/t_d (kmol per hour of flows) and vents G as A
    reacts: what has left by t is ``t/t_d - (1 - exp(-k t)) / (k t_d)``. R2 doses it at a
    constant rate over the same t_d, so the shares differ by ``t/t_d - V(t)/V(t_d)`` at most."""
    ws = _coupled(tmp_path)
    (finding,) = _coupling(ws)
    assert finding.level == "info" and finding.ids == ["R2", "R", "S4"]
    td = 3600.0

    def left(t):
        return t / td - (1 - math.exp(-K * t)) / (K * td)

    # largest where d/dt (t/t_d - V(t)/V(t_d)) = 0: exp(-k t) = 1 - V(t_d)
    at = -math.log(1 - left(td)) / K
    exact = at / td - left(at) / left(td)
    process, _ = load(ws.root)
    node = process.nodes["R"]
    inlets = [s for s in process.flowsheet.streams if process.ends(s)[1].node == "R"]
    solved, _ = solve_node(process, node, tank_inlet(node, inlets), "design")
    dose = process.nodes["R2"].batch.dosing[0]
    gap, when = deviation(solved.vent_profile, dose)
    assert gap == pytest.approx(exact, rel=1e-3)  # at the integrator's points
    assert when == pytest.approx(at, rel=0.05)
    assert f"differ by {exact:.3g} at most (at {when / 3600:.4g} h" in finding.message


def test_a_dose_on_another_schedule_than_its_generator_is_a_warning(tmp_path):
    slow = COUPLED.replace(
        "dosing: [{stream: S4, time: 3600}]", "dosing: [{stream: S4, time: 7200}]"
    )
    findings = _coupling(_coupled(tmp_path, slow))
    (warning,) = [f for f in findings if f.level == "warning"]
    assert "over 0-2 h (1), but R's dosing runs 0-1 h (1)" in warning.message
    assert warning.line is not None and warning.hint
    late = COUPLED.replace(
        "dosing: [{stream: S4, time: 3600}]", "dosing: [{stream: S4, time: 3600, start: 60}]"
    )
    assert [f.level for f in _coupling(_coupled(tmp_path / "late", late))] == ["warning", "info"]


def test_the_deviation_of_a_profile_from_a_dose():
    dose = Dosing.model_validate({"stream": "D", "time": 100})
    # a generator that gives its gas off at the dose's rate, and one that gives it all at once
    assert deviation([(0.0, 0.0), (50.0, 0.5), (100.0, 1.0)], dose)[0] == pytest.approx(0.0)
    assert deviation([(0.0, 0.0), (1e-9, 1.0), (100.0, 1.0)], dose)[0] == pytest.approx(1.0)
    assert deviation([(0.0, 0.0)], dose) is None


def test_the_recipe_starts_coupled_doses_together(tmp_path):
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {"value": 100.0, "unit": "kg", "stream": "S6", "provenance": "assumed"},
        "hours_per_year": {"value": 8000, "provenance": "assumed"},
        "unit_procedures": [
            {
                "id": "MAKE",
                "unit": "R",
                "operations": [
                    {"id": "charge", "kind": "charge", "duration": plain._hours(1.0)},
                    {"id": "dose", "kind": "dose", "from": "R"},
                ],
            },
            {
                "id": "TAKE",
                "unit": "R2",
                "start": {"after": "MAKE", "operation": "charge"},
                "operations": [
                    {"id": "charge", "kind": "charge", "duration": plain._hours(1.0)},
                    {"id": "dose", "kind": "dose", "from": "R2"},
                ],
            },
        ],
    }
    ws = _coupled(tmp_path, recipe=recipe)
    assert not [f for f in recipe_report(ws.root).findings if f.rule == "cheme.recipe-coupling"]
    recipe["unit_procedures"][1]["operations"][0]["duration"] = plain._hours(0.5)
    (ws.root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe))
    (finding,) = [f for f in recipe_report(ws.root).findings if f.rule == "cheme.recipe-coupling"]
    assert finding.level == "warning"
    assert "the dose of R2 starts at 0.5 h, but R, whose vent it doses, starts at 1 h" in (
        finding.message
    )


# -- a gas passing through without ideal-gas data -----------------------------------------------


def test_a_gas_passing_through_without_ideal_gas_data_is_a_warning(tmp_path):
    flowsheet = vented.FLOWSHEET.replace("time: 3600}]", "time: 3600, absorbed: 0.8}]")
    ws = vented._plant(tmp_path, flowsheet)
    (ws.root / "process/materials.yaml").write_text(
        vented.MATERIALS.replace("{id: gas, components: [G]}", "{id: gas, components: [A, G]}")
    )
    warnings = vented._messages(ws, "warning")
    assert warnings == [
        "block R: the gas A of the dose S2 passes through to the vent without ideal_gas data: "
        "its warming to the vessel's temperature is left out of the duty, the peak cooling duty "
        "and the adiabatic balance"
    ]
    # with A's ideal-gas data no warning
    (ws.root / "process/materials.yaml").write_text(
        vented.MATERIALS.replace(
            "{id: gas, components: [G]}", "{id: gas, components: [A, G]}"
        ).replace(
            "liquid_heat_capacity: 150, normal_boiling_point: 400}\n  - {id: B",
            "liquid_heat_capacity: 150, normal_boiling_point: 400,\n"
            "     ideal_gas: {dHf_298: -166000, S_298: 264, cp_R: [5.5]}}\n  - {id: B",
            1,
        )
    )
    assert not vented._messages(ws, "warning")
    # a fully absorbed dose passes nothing
    assert not vented._messages(vented._plant(tmp_path / "b"), "warning")


def test_an_inert_passing_through_without_ideal_gas_data_is_a_warning(tmp_path):
    """copper-i-chloride-1 L-3 (ADR 0071): N2 of a dosed air passes through a vent whose
    components no reaction forms; it needs no formed gas, but its warming needs its data."""
    materials = vented.MATERIALS.replace(
        "templates:\n",
        "  - {id: N2, name: nitrogen, formula: N2, molar_mass: 28.0134}\ntemplates:\n",
    ).replace("{id: gas, components: [G]}", "{id: gas, components: [G, N2]}")
    flowsheet = vented.FLOWSHEET.replace(
        "vent: {stream: S4, components: [G]}", "vent: {stream: S4, components: [G], inerts: [N2]}"
    ).replace("values: {A: 1.0}", "values: {A: 0.5, N2: 0.5}")
    ws = vented._plant(tmp_path, flowsheet)
    (ws.root / "process/materials.yaml").write_text(materials)
    (warning,) = vented._messages(ws, "warning")
    assert "the gas N2 of the dose S2 passes through" in warning
