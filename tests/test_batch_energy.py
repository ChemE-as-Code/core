"""The rest of a batch's energy balance (ADR 0075, core#191): a recipe heat or cool operation's
heat written on its energy stream, a batch's heat-up on its own stream apart from its cooling, a
charged solid's heat of solution, an agitator's power, a conversion step's vessel metal, a
dryer's metal heated from the temperature its vessel was left at and a cool-down in a dryer's
vessel, and a still's sensible rise while it boils and its heat losses; each against a closed
form, and plants that use none of it."""

import copy
import math

import pytest
import yaml

from chemeascode.domains.process.batch_still import solve_still, still_report
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.recipe import recipe_report
from chemeascode.domains.process.schema import Batch, Step, Still, VapourPressure
from tests import test_batch_still as still
from tests import test_dryer as dryers
from tests import test_duties as duties
from tests import test_heats_and_heat_up as heats
from tests import test_recipe as recipes
from tests import test_semibatch as semi

#: h of the flowsheet's flows one batch of the recipe fixture makes
HOURS = 4.5

STEAM = """\
  - id: STEAM
    category: utility
    utility: {kind: steam}
    ports: [{id: s, direction: out, kind: energy}]
"""


def _two_streams(ws, heat_up_port=None, batch_extra=""):
    """The recipe fixture's semi-batch R held at 300 K from a 290 K charge, its duty on the
    cooling water Q1 (``energy_port: q``), and a steam stream Q2 into its port h; with
    *heat_up_port* the heat-up goes on it. *batch_extra*: more of the batch's flow mapping."""
    path = ws.root / "process/flowsheet.yaml"
    text = path.read_text()
    text = text.replace("feeds:\n", "feeds:\n" + STEAM, 1).replace(
        "{id: q, direction: out, kind: energy}]",
        "{id: q, direction: out, kind: energy}, {id: h, direction: in, kind: energy}]",
    )
    text = text.replace("    reactor: semibatch\n", "    reactor: semibatch\n    energy_port: q\n")
    extra = (f"heat_up_port: {heat_up_port}, " if heat_up_port else "") + batch_extra
    text = text.replace("time: 1800, heat_up: true, ", f"time: 1800, heat_up: true, {extra}")
    text = text.replace("time: 1800, provenance", f"time: 1800, {extra}provenance")
    text = text.rstrip("\n") + "\n  - {id: Q2, kind: energy, from: STEAM.s, to: R.h}\n"
    path.write_text(text)
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    result = run(ws, process, "design", write=True)
    return result


def _duty(ws, stream):
    return duties._streams(ws)[stream]["state"]["design"].get("duty")


def _row(ws):
    (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "R"]
    return row


# -- a batch's heat-up on its own stream ----------------------------------------------------------


def test_the_heat_up_goes_on_its_own_stream_the_rest_on_the_cooling_water(tmp_path):
    """The charge from 290 to 300 K (5 x 150 x 10 kJ/h) and the vessel's 1000 kJ/K metal (10 K
    a batch of 4.5 h) on the steam Q2; the reaction's heat on the cooling water Q1, as the
    duty without heat_up has it."""
    recipe = recipes._jacketed(metal_heat_capacity=1000.0)
    plain = heats._held_at_300(tmp_path / "plain", recipe, heat_up=False, cooling=True)
    removed = _duty(plain, "Q1")["value"]
    ws = heats._held_at_300(tmp_path, recipe, cooling=True)
    result = _two_streams(ws, heat_up_port="h")
    assert not [f for f in result.findings if f.level != "info"], [
        f.format() for f in result.findings
    ]
    q2 = _duty(ws, "Q2")
    heat_up = 5 * 150.0 * 10.0 / 3600.0 + 1000.0 * 10.0 / HOURS / 3600.0
    assert q2["provenance"] == "calculated" and q2["value"] == pytest.approx(heat_up, rel=1e-5)
    assert _duty(ws, "Q1")["value"] == pytest.approx(removed, rel=1e-5)
    duty = _row(ws)["model_duty"]
    assert set(duty["terms_kW"]) == {"reaction", "doses"}
    assert duty["stream"]["id"] == "Q1"
    assert duty["heat_up"]["stream"]["id"] == "Q2"
    assert duty["heat_up"]["heat_in_kW"] == pytest.approx(heat_up, rel=1e-6)
    # one net duty without the port: on Q1 alone the heat-up would be netted (KOtBu L-11)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-energy-port"]


def test_the_heat_up_port_rules(tmp_path):
    with pytest.raises(ValueError, match="heat_up_port"):
        Batch.model_validate({"time": 5, "heat_up_port": "h", "provenance": "assumed"})
    ws = heats._held_at_300(tmp_path, recipes._jacketed(), cooling=True)
    _two_streams(ws, heat_up_port="x")
    process, _ = load(ws.root)
    (finding,) = [f for f in rules(process) if f.rule == "cheme.process-energy-port"]
    assert finding.level == "error" and "heat_up_port x is no energy port" in finding.message


# -- the agitator's power and a charged solid's heat of solution ----------------------------------


def test_the_agitators_power_is_heat_the_cooling_water_removes(tmp_path):
    """2 kW over the model's 1 h of dosing and 0.5 h of post-reaction, a batch of 4.5 h of
    flows: -2 x 1.5 / 4.5 kW in the duty; the recipe's peak duty takes the 2 kW too."""
    recipe = recipes._jacketed()
    plain = heats._held_at_300(tmp_path / "plain", recipe, heat_up=False, cooling=True)
    ws = heats._held_at_300(tmp_path, recipe, heat_up=False, cooling=True)
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "time: 1800, provenance",
            "time: 1800, agitator_power: {value: 2, provenance: assumed}, provenance",
        )
    )
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    terms = _row(ws)["model_duty"]["terms_kW"]
    assert terms["agitation"] == pytest.approx(-2.0 * 1.5 / HOURS, rel=1e-12)
    assert _duty(ws, "Q1")["value"] == pytest.approx(
        _duty(plain, "Q1")["value"] + 2.0 * 1.5 / HOURS, rel=1e-5
    )
    (before,) = recipe_report(plain.root).vessels
    (after,) = recipe_report(ws.root).vessels
    assert after.peak_duty == pytest.approx(before.peak_duty + 2.0, rel=1e-12)
    # without a recipe the batch's hours are not known: the duty says what it lacks
    (ws.root / "process/recipe.yaml").unlink()
    duty = _row(ws)["model_duty"]
    assert duty["heat_in_kW"] is None and "agitator's power" in duty["missing"][0]
    with pytest.raises(ValueError, match="agitator_power: an isothermal batch"):
        Batch.model_validate(
            {
                "time": 5,
                "heat": "adiabatic",
                "agitator_power": {"value": 1, "provenance": "assumed"},
                "provenance": "assumed",
            }
        )


def test_a_charged_solids_heat_of_solution_is_a_term_of_the_duty():
    """5 kmol of S charged, dissolving with +4000 kJ/kmol (endothermic): 20000 kJ in the term
    solution; the reaction's term, the outlet and the peak cooling duty as without it."""
    plain = semi._semibatch(1e-2)
    charged = semi._semibatch(
        1e-2,
        semi._batch(heat_of_solution={"values": {"S": 4000.0}, "provenance": "assumed"}),
    )
    assert charged.heat_terms["solution"] == pytest.approx(5 * 4000.0, rel=1e-12)
    assert charged.heat_terms["reaction"] == plain.heat_terms["reaction"]
    assert charged.outlet == plain.outlet
    assert charged.peak_cooling_duty == plain.peak_cooling_duty
    assert "solution" not in plain.heat_terms


def test_a_charged_heat_of_solution_in_a_plant_and_its_rules(tmp_path):
    flowsheet = duties._cooled().replace(
        "batch: {dosing: [{stream: S2, time: 3600}], ",
        "batch: {dosing: [{stream: S2, time: 3600}], heat_of_solution: {values: {S: 4000}, "
        "provenance: assumed}, ",
    )
    ws = semi._plant(tmp_path, flowsheet)
    plain = semi._plant(tmp_path / "plain", duties._cooled())
    for w in (ws, plain):
        process, _ = load(w.root)
        run(w, process, "design", write=True)
    q, q0 = _duty(ws, "Q1"), _duty(plain, "Q1")
    assert q0["value"] - q["value"] == pytest.approx(5 * 4000.0 / 3600.0, rel=1e-5)
    assert q["fingerprint"] != q0["fingerprint"]
    # the outlet's fingerprint is as without it: the heat changes the duty only
    s3 = duties._streams(ws)["S3"]["state"]["design"]["flow"]["fingerprint"]
    assert s3 == duties._streams(plain)["S3"]["state"]["design"]["flow"]["fingerprint"]
    bad = flowsheet.replace("values: {S: 4000}", "values: {Z: 4000, A: 1}")
    process, _ = load(semi._plant(tmp_path / "bad", bad).root)
    messages = {f.level: f.message for f in rules(process) if f.rule == "cheme.process-reactor"}
    assert "undeclared component(s) Z" in messages["error"]
    assert "A, which the charge" in messages["warning"]


# -- a recipe operation's heat on its stream ------------------------------------------------------


def _heated(tmp_path, stream="Q2", metal=1000.0, **kw):
    """The fixture held at 300 K without heat_up, its recipe heating the charge 290 -> 300 K
    on the steam Q2 (*stream*)."""
    recipe = recipes._jacketed(metal_heat_capacity=metal) if metal else recipes._jacketed()
    recipe["unit_procedures"][0]["operations"].insert(
        1, {"id": "heatup", "kind": "heat", "temperatures": [290, 300], "stream": stream} | kw
    )
    ws = heats._held_at_300(tmp_path, recipe, heat_up=False, cooling=True)
    return ws, _two_streams(ws)


def test_a_recipe_heat_up_is_written_on_its_stream(tmp_path):
    """The charge (5 kmol/h x 150 kJ/(kmol K) x 4.5 h) and the metal (1000 kJ/K) by 10 K, over
    the batch's 4.5 h of flows."""
    ws, result = _heated(tmp_path)
    # the heat-up lengthens the cycle: the fixture's batch basis is off, nothing else
    assert {f.rule for f in result.findings if f.level != "info"} <= {"cheme.recipe-basis"}
    q2 = _duty(ws, "Q2")
    exact = (5 * 150.0 * HOURS * 10.0 + 1000.0 * 10.0) / (HOURS * 3600.0)
    assert q2["provenance"] == "calculated" and q2["value"] == pytest.approx(exact, rel=1e-5)
    assert "recipe heat duty" in q2["source"]
    (heat,) = recipe_report(ws.root).heats
    assert heat.stream == "Q2" and recipe_report(ws.root).as_dict()["heats"][0]["stream"] == "Q2"
    assert heat.kJ == pytest.approx(exact * HOURS * 3600.0, rel=1e-9)
    process, _ = load(ws.root)
    assert {f.rule for f in rules(process) if f.level != "info"} <= {"cheme.recipe-basis"}
    # a change of the operation makes the duty stale; propagate writes it again
    path = ws.root / "process/recipe.yaml"
    path.write_text(path.read_text().replace("- 290\n", "- 295\n", 1))
    process, _ = load(ws.root)
    assert [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    run(ws, process, "design", write=True)
    assert _duty(ws, "Q2")["value"] == pytest.approx(exact / 2, rel=1e-5)


def test_without_metal_the_heat_is_the_contents_and_a_given_duty_is_compared(tmp_path):
    ws, _ = _heated(tmp_path, metal=None)
    exact = 5 * 150.0 * 10.0 / 3600.0
    assert _duty(ws, "Q2")["value"] == pytest.approx(exact, rel=1e-5)
    (heat,) = recipe_report(ws.root).heats  # reported, being on a stream
    assert heat.metal_kJ == 0.0
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    (q2,) = [s for s in data["streams"] if s["id"] == "Q2"]
    q2["state"] = {"design": {"duty": {"value": 5.0, "provenance": "assumed"}}}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    process, _ = load(ws.root)
    (finding,) = [f for f in rules(process) if f.rule == "cheme.process-duty"]
    assert finding.level == "warning" and "Q2 duty 5 kW (assumed)" in finding.message


def test_an_operations_stream_must_be_an_energy_stream_of_the_unit_no_model_writes(tmp_path):
    with pytest.raises(ValueError, match="stream: the heat of a heat or cool with temperatures"):
        recipes.Recipe.model_validate(
            recipes.RECIPE
            | {
                "unit_procedures": [
                    {
                        "id": "UP",
                        "unit": "R",
                        "operations": [
                            {
                                "id": "h",
                                "kind": "heat",
                                "duration": recipes._hours(1),
                                "stream": "Q2",
                            }
                        ],
                    }
                ]
            }
        )
    for stream, why in (
        ("Q1", "R's model writes the duty of Q1 already"),
        ("S1", "S1 is no energy stream"),
    ):
        ws, _ = _heated(tmp_path / stream, stream=stream)
        messages = [f.message for f in recipes._recipe_findings(ws) if f.level == "error"]
        assert any(why in m for m in messages), messages


# -- a conversion step's vessel metal -------------------------------------------------------------

CONVERSION = """\
  - {id: R2, stoichiometry: {A: -1, B: 1}, phase: liquid,
     conversion: {key: A, value: 0.5, provenance: assumed},
     heat_of_reaction: {value: -100000, provenance: assumed}}
"""


def test_a_conversion_step_with_vessel_metal_heats_the_metal_from_its_inlet_to_its_outlet(
    tmp_path,
):
    """C, a conversion step after R in R's vessel (1000 kJ/K), heated on steam, takes S3 at
    300 K to 310 K: its duty holds 1000 x 10 kJ a batch of 4.5 h of flows with vessel_metal,
    none without."""
    recipe = recipes._jacketed(metal_heat_capacity=1000.0)
    recipe["unit_procedures"] = [recipe["unit_procedures"][0] | {"unit": None, "units": ["R", "C"]}]
    recipe["unit_procedures"][0].pop("unit")

    def plant(path, metal):
        ws = recipes._plant(path, recipe, propagate=False)
        text = (ws.root / "process/flowsheet.yaml").read_text()
        text = text.replace(
            "  - id: C\n    class: Cooling\n",
            "  - id: C\n    class: ReactingChemicals\n    reactions: [R2]\n"
            + ("    vessel_metal: true\n" if metal else ""),
        ).replace(
            "  - id: S4\n    from: C.out\n    to: P.in\n    template: liquid\n",
            "  - id: S4\n    from: C.out\n    to: P.in\n    template: liquid\n"
            "    state:\n      design:\n        temperature: {value: 310, provenance: given}\n",
        )
        text = text.replace("feeds:\n", "feeds:\n" + STEAM).replace(
            "    ports: [{id: in, direction: in}, {id: out, direction: out}]\nstreams:\n",
            "    ports: [{id: in, direction: in}, {id: out, direction: out},"
            " {id: q, direction: in, kind: energy}]\nstreams:\n",
        )
        text = text.rstrip("\n") + "\n  - {id: Q3, kind: energy, from: STEAM.s, to: C.q}\n"
        (ws.root / "process/flowsheet.yaml").write_text(text)
        (ws.root / "process/reactions.yaml").write_text(semi.REACTIONS + CONVERSION)
        process, found = load(ws.root)
        assert process is not None, [f.format() for f in found]
        run(ws, process, "design", write=True)
        (row,) = [r for r in reactor_report(ws.root).reactors if r["node"] == "C"]
        return ws, row["model_duty"]

    ws, with_metal = plant(tmp_path, True)
    _, without = plant(tmp_path / "plain", False)
    assert "vessel metal" not in without["terms_kW"]
    assert with_metal["terms_kW"]["vessel metal"] == pytest.approx(
        1000.0 * 10.0 / HOURS / 3600.0, rel=1e-6
    )
    assert with_metal["heat_in_kW"] == pytest.approx(
        without["heat_in_kW"] + 1000.0 * 10.0 / HOURS / 3600.0, rel=1e-9
    )
    assert _duty(ws, "Q3")["value"] == pytest.approx(with_metal["heat_in_kW"], rel=1e-5)
    # on a node that is no conversion step it changes nothing, and says so
    node = Step.model_validate(
        {"id": "X", "block": "B", "class": "Mixing", "vessel_metal": True, "ports": []}
    )
    assert node.vessel_metal
    process, _ = load(ws.root)
    process.flowsheet.steps.append(node)
    from chemeascode.domains.process.duties import rules as duty_rules

    (finding,) = [f for f in duty_rules(process) if "vessel_metal" in f.message]
    assert finding.level == "warning" and "no conversion step" in finding.message


# -- a dryer's metal and a cool-down in its vessel ------------------------------------------------

DRYER_MATERIALS = (
    dryers.MATERIALS.replace("phase: solid}", "phase: solid, liquid_heat_capacity: 200}")
    .replace("molar_mass: 177.98}", "molar_mass: 177.98, liquid_heat_capacity: 200}")
    .replace("molar_mass: 102.89}", "molar_mass: 102.89, liquid_heat_capacity: 50}")
    .replace(
        "liquid_molar_volume: 0.018015,", "liquid_molar_volume: 0.018015, liquid_heat_capacity: 75,"
    )
)
CW = """\
  - {id: CW, category: utility, utility: {kind: cooling_water},
     ports: [{id: r, direction: in, kind: energy}]}
"""


def _dryer_plant(tmp_path, metal=True, cool=True):
    """The filter-dryer of test_dryer with its vessel's 2000 kJ/K metal given on the recipe's
    vessel (not the dryer's), and (*cool*) the product cooled in it 333.15 -> 303.15 K on a
    jacket of 3 kW/K at 293.15 K before the discharge, its heat on Q2."""
    flowsheet = dryers.FLOWSHEET
    if metal:
        flowsheet = flowsheet.replace("        vessel_heat_capacity: 2000\n", "")
    flowsheet = (
        flowsheet.replace("products:\n", "products:\n" + CW)
        .replace(
            "      - {id: heat, direction: in, kind: energy, delegates: heat}\n",
            "      - {id: heat, direction: in, kind: energy, delegates: heat}\n"
            "      - {id: cool, direction: out, kind: energy}\n",
        )
        .rstrip("\n")
        + "\n  - {id: Q2, kind: energy, from: D1.cool, to: CW.r}\n"
    )
    recipe = copy.deepcopy(dryers.RECIPE)
    up = recipe["unit_procedures"][0]
    if metal:
        up["vessel"]["metal_heat_capacity"] = 2000.0
    if cool:
        up["vessel"]["jacket"] = {
            "u": 600,
            "area": 5.0,
            "coolant_temperature": 293.15,
            "provenance": "assumed",
        }
        up["operations"].insert(
            3,
            {
                "id": "cool",
                "kind": "cool",
                "temperatures": [333.15, 303.15],
                "stream": "Q2",
            },
        )
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: dryer-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(DRYER_MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    from chemeascode.foundation.workspace import Workspace

    ws = Workspace(root)
    process, _ = load(root)
    run(ws, process, "design", write=True)
    return ws


def _product_capacity():
    """kJ/K of one batch's dried product: X_s and X at 200, NaBr at 50, the water kept at 75
    kJ/(kmol K)."""
    kg = {"X_s": 400.0, "X": 10 / 6, "NaBr": 40 / 6, "H2O": dryers.KEPT}
    mw = {"X_s": 177.98, "X": 177.98, "NaBr": 102.89, "H2O": 18.015}
    cp = {"X_s": 200.0, "X": 200.0, "NaBr": 50.0, "H2O": 75.0}
    return sum(kg[n] / mw[n] * cp[n] for n in kg) * dryers.HOURS


def _dryer_entry(ws):
    from chemeascode.domains.process.crystallization import crystallizer_report

    (entry,) = [u for u in crystallizer_report(ws.root).units if u["node"] == "D1"]
    return entry["solution"]["energy"]


def test_the_dryer_heats_its_metal_from_the_temperature_the_cool_down_left_it_at(tmp_path):
    """The recipe vessel's 2000 kJ/K from the cool-down's 303.15 K, not the wet cake's 278.15 K,
    to 333.15 K each batch of 5 h of flows; without the cool-down, from the wet cake's."""
    energy = _dryer_entry(_dryer_plant(tmp_path))
    assert energy["vessel_kJ_h"] == pytest.approx(2000 * 30.0 / dryers.HOURS, rel=1e-5)
    assert energy["vessel_metal"]["start_temperature_K"] == 303.15
    uncooled = _dryer_entry(_dryer_plant(tmp_path / "uncooled", cool=False))
    assert uncooled["vessel_kJ_h"] == pytest.approx(2000 * 55.0 / dryers.HOURS, rel=1e-5)
    assert uncooled["duty_kW"] == pytest.approx(dryers.DUTY, rel=1e-5)  # as the dryer's own
    plain = _dryer_entry(_dryer_plant(tmp_path / "plain", metal=False, cool=False))
    assert "vessel_metal" not in plain
    assert plain["duty_kW"] == pytest.approx(dryers.DUTY, rel=1e-5)


def test_a_cool_down_in_the_dryers_vessel_has_a_jacket_time_and_its_heat_on_a_stream(tmp_path):
    """The product and the metal from 333.15 to 303.15 K on UA 3 kW/K with the coolant at
    293.15 K: t = (C + C_m) / UA ln(40 / 10); its heat (C + C_m)(-30) on Q2, over 5 h."""
    ws = _dryer_plant(tmp_path)
    result = recipe_report(ws.root)
    assert not [f.format() for f in result.findings if f.level == "error"]
    capacity = _product_capacity() + 2000.0
    (step,) = [s for s in result.steps if s.operation == "cool"]
    assert step.end - step.start == pytest.approx(capacity / 3.0 * math.log(4.0) / 3600, rel=1e-5)
    (heat,) = result.heats
    assert heat.kJ == pytest.approx(-capacity * 30.0, rel=1e-5)
    assert _duty(ws, "Q2")["value"] == pytest.approx(capacity * 30.0 / 5.0 / 3600.0, rel=1e-5)
    # both metals given: refused
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "        efficiency: 0.7\n",
            "        vessel_heat_capacity: 2000\n        efficiency: 0.7\n",
        )
    )
    messages = [f.message for f in recipe_report(ws.root).findings if f.level == "error"]
    assert any("both give the dryer's metal" in m for m in messages)
    assert "not both" in _dryer_entry(ws)["missing"][0]


# -- a still's sensible rise while it boils and its heat losses -----------------------------------

CP_A, CP_P = 136.0, 200.0  # kJ/(kmol K): the test's benzene-like A and non-volatile P


def _still(**extra):
    return Still.model_validate(
        {
            "volatility": {"model": "raoult", "provenance": "assumed"},
            "nonvolatile": ["P"],
            "boilup": {"value": 2.0, "unit": "kmol/h", "provenance": "assumed"},
            "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
            "outlets": {"distillate": "d", "residue": "r"},
            "provenance": "assumed",
        }
        | extra
    )


def _components():
    from types import SimpleNamespace

    vp = VapourPressure.model_validate(still.BENZENE | {"provenance": "given"})
    return {
        "A": SimpleNamespace(
            vapour_pressure=vp, heat_of_vaporization=30720.0, liquid_heat_capacity=CP_A
        ),
        "P": SimpleNamespace(
            vapour_pressure=None, heat_of_vaporization=None, liquid_heat_capacity=CP_P
        ),
    }


def _bubble(x):
    vp = VapourPressure.model_validate(still.BENZENE | {"provenance": "given"})
    lo, hi = 250.0, 600.0
    for _ in range(200):
        t = (lo + hi) / 2
        lo, hi = (lo, t) if x * vp.kpa(t) > 101.325 else (t, hi)
    return (lo + hi) / 2


def _quadrature(f, a, b, n=4000):
    h = (b - a) / n
    return (
        h / 3 * sum((1 if i in (0, n) else 4 if i % 2 else 2) * f(a + i * h) for i in range(n + 1))
    )


def test_the_stills_sensible_rise_and_heat_loss_follow_their_integrals():
    """0.8 kmol A over 0.2 kmol P boiled to x_A 0.2 (1 h of flows): the pot's sensible rise
    int (n_A cp_A + n_P cp_P) dT along the bubble point, n_A = n_P x / (1 - x); the heat lost,
    UA int (T - T_amb) dt with dt = 3600 / 2 dn_A s; the agitator's -P t."""
    loss = {"ua": 500.0, "ambient_temperature": 293.15, "provenance": "assumed"}
    power = {"value": 3.0, "provenance": "assumed"}
    spec = _still(sensible_heat=True, heat_loss=loss, agitator_power=power)
    comps = _components()
    result = solve_still(spec, {"A": 0.8, "P": 0.2}, None, comps, 101.325)
    plain = solve_still(_still(), {"A": 0.8, "P": 0.2}, None, comps, 101.325)
    assert result.residue == plain.residue and result.time == plain.time  # beside the model

    def n_a(x):
        return 0.2 * x / (1 - x)

    # in x: dT = T'(x) dx; integrate C(x) T'(x) by parts-free quadrature on T(x)
    def sensible_x(x, dx=1e-6):
        slope = (_bubble(x + dx) - _bubble(x - dx)) / (2 * dx)
        return (n_a(x) * CP_A + 0.2 * CP_P) * slope

    exact = -_quadrature(sensible_x, 0.2, 0.8, 400)
    assert result.sensible_rise == pytest.approx(exact, rel=1e-6)

    def lost_x(x):  # (T - T_amb) dt / dx, dn_A/dx = 0.2 / (1 - x)^2
        return (_bubble(x) - 293.15) * 1800.0 * 0.2 / (1 - x) ** 2

    assert result.heat_loss == pytest.approx(0.5 * _quadrature(lost_x, 0.2, 0.8, 400), rel=1e-6)
    from types import SimpleNamespace

    from chemeascode.domains.process.duties import still_duty

    node = SimpleNamespace(id="ST", still=spec)
    duty = still_duty(node, result)
    assert duty.terms_kW["sensible rise"] == pytest.approx(result.sensible_rise / 3600.0)
    assert duty.terms_kW["heat losses"] == pytest.approx(result.heat_loss / 3600.0)
    assert duty.terms_kW["agitation"] == pytest.approx(-3.0 * result.time / 3600.0, rel=1e-12)
    assert duty.heat_kW == pytest.approx(sum(duty.terms_kW.values()), rel=1e-12)
    assert still_duty(SimpleNamespace(id="ST", still=_still()), plain).terms_kW == {
        "boil-up": plain.energy / 3600.0
    }
    with pytest.raises(ValueError, match="sensible_heat and heat_loss need volatility raoult"):
        _still(
            volatility={"model": "constant", "alpha": {"A": 2.0}, "provenance": "assumed"},
            sensible_heat=True,
        )
    # without a heat capacity the duty is not known, and says why
    comps["P"].liquid_heat_capacity = None
    lacking = solve_still(_still(sensible_heat=True), {"A": 0.8, "P": 0.2}, None, comps, 101.325)
    duty = still_duty(SimpleNamespace(id="ST", still=_still(sensible_heat=True)), lacking)
    assert duty.heat_kW is None and "liquid_heat_capacity of P" in duty.missing[0]


def test_a_stills_new_terms_in_its_report_its_heat_up_time_and_its_fingerprints(tmp_path):
    flowsheet = heats.STILL_FLOWSHEET.replace(
        "    still:\n",
        "    still:\n      sensible_heat: true\n      heat_up_time: true\n"
        "      heat_loss: {ua: 200, ambient_temperature: 293.15, provenance: assumed}\n",
    )
    ws = still._plant(tmp_path, flowsheet=flowsheet, materials=heats.STILL_CP, recipe=still.RECIPE)
    plain = still._plant(
        tmp_path / "plain",
        flowsheet=heats.STILL_FLOWSHEET.replace(
            "    still:\n", "    still:\n      heat_up_time: true\n"
        ),
        materials=heats.STILL_CP,
        recipe=still.RECIPE,
    )
    for w in (ws, plain):
        process, _ = load(w.root)
        run(w, process, "design", write=True)
    (unit,) = still_report(ws.root).units
    (base,) = still_report(plain.root).units
    sol = unit["solution"]
    terms = sol["duty_terms_kW"]
    assert terms["sensible rise"] > 0 and terms["heat losses"] > 0
    assert sol["sensible_rise_kWh_per_batch"] == pytest.approx(terms["sensible rise"] * 4.0)
    assert sol["heat_loss_kWh_per_batch"] == pytest.approx(terms["heat losses"] * 4.0)
    # the heat-up time takes them at the boil-up's heat input
    rate = base["solution"]["duty_kW"]
    extra = (terms["sensible rise"] + terms["heat losses"]) * 4.0 * 3600.0
    assert sol["heat_up_time_h"] == pytest.approx(
        base["solution"]["heat_up_time_h"] + extra / rate / 3600.0, rel=1e-6
    )
    assert any(a.startswith("sensible_heat:") for a in unit["assumptions"])
    assert not any("no sensible heat" in a for a in unit["assumptions"])
    # the outlets' fingerprints are as without them
    fp = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    fp0 = yaml.safe_load((plain.root / "process/flowsheet.yaml").read_text())

    def flows(data):
        return {
            s["id"]: s["state"]["design"]["flow"]["fingerprint"]
            for s in data["streams"]
            if s.get("state", {}).get("design", {}).get("flow", {}).get("provenance")
            == "calculated"
        }

    assert flows(fp) == flows(fp0) and flows(fp)


# -- plants that use none of it -------------------------------------------------------------------


def test_the_new_fields_are_left_out_of_the_dumps():
    assert not {"heat_up_port", "heat_of_solution", "agitator_power"} & set(
        Batch.model_validate({"time": 5, "provenance": "assumed"}).model_dump()
    )
    assert not {"sensible_heat", "heat_loss", "agitator_power"} & set(_still().model_dump())
    node = Step.model_validate({"id": "X", "block": "B", "ports": []})
    assert "vessel_metal" not in node.model_dump()
    op = recipes.Recipe.model_validate(recipes.RECIPE).unit_procedures[0].operations[0]
    assert "stream" not in op.model_dump()
