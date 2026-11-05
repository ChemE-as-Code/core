"""Batch models write and check their energy streams (ADR 0059): the year-average duty of an
isothermal batch and semi-batch, a batch still, a crystallizer and a conversion step against
their closed forms, how propagate writes it (and never over a given one), the comparison
cheme.process-duty, the energy port and its rules, and plants that do not use it."""

import math

import pytest
import yaml

from chemeascode.domains.process.duties import batch_duty, duty_model, target
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report, reactor_text
from chemeascode.domains.process.schema import Batch, Step
from chemeascode.domains.process.stirred_tank import Dose, solve_batch
from chemeascode.foundation.workspace import Workspace
from tests import test_batch_still as still
from tests import test_crystallization as crystal
from tests import test_semibatch as semi

DOSING = semi.DOSING
HEAT = semi.HEAT  # kJ/kmol, exothermic


# -- the models' heat, closed forms -------------------------------------------------------------


def test_an_isothermal_batch_removes_its_reaction_heat():
    """A -> B to 0.9 conversion: the heat into the batch is dHr x the extent, 0.9 kmol of A."""
    batch = Batch.model_validate(
        {"target": {"key": "A", "conversion": 0.9}, "provenance": "assumed"}
    )
    result = solve_batch(
        semi._reactions(1e-3),
        {"A": 1.0, "S": 5.0},
        300.0,
        101.325,
        batch,
        {},
        semi.Liquid(semi.V),
        semi.CP,
    )
    assert result.heat_terms == {"reaction": pytest.approx(HEAT * 0.9, rel=1e-6)}
    node = Step.model_validate(
        {"id": "R", "block": "B", "reactor": "batch", "reactions": ["R1"], "batch": batch}
    )
    duty = batch_duty(node, result)
    assert duty.heat_kW == pytest.approx(HEAT * 0.9 / 3600.0, rel=1e-6)
    assert duty.terms_kW == {"reaction": pytest.approx(HEAT * 0.9 / 3600.0, rel=1e-6)}


def test_a_semibatch_warms_its_doses_and_releases_the_extents_heat():
    """A dose 20 K colder than the batch takes n cp dT = 1 x 150 x 20 kJ; the reaction gives
    dHr x its extent (the reacted share of the dose, 1 - the closed-form accumulation)."""
    k = 1e-2
    result = semi._semibatch(k, doses=[Dose({"A": 1.0}, 280.0, [(0.0, DOSING, 1.0)])])
    exact = 1 - (1 - math.exp(-k * DOSING)) / (k * DOSING)
    assert result.extents["R1"] == pytest.approx(exact, rel=1e-6)
    assert result.heat_terms["reaction"] == pytest.approx(HEAT * exact, rel=1e-6)
    assert result.heat_terms["doses"] == pytest.approx(1.0 * 150.0 * 20.0, rel=1e-12)


def test_an_adiabatic_batch_has_no_duty_and_unknown_heat_says_why():
    adiabatic = semi._batch(heat="adiabatic")
    result = semi._semibatch(1e-2, batch=adiabatic)
    assert result.heat_terms is None
    node = Step.model_validate(
        {"id": "R", "block": "B", "reactor": "semibatch", "reactions": ["R1"], "batch": adiabatic}
    )
    assert batch_duty(node, result).heat_kW is None
    cold = semi._semibatch(
        1e-2, doses=[Dose({"A": 1.0}, 280.0, [(0.0, DOSING, 1.0)])], cp={"S": 150.0, "B": 150.0}
    )
    assert cold.heat_terms is None and "liquid_heat_capacity of dose 1" in cold.heat_missing[0]


# -- the semi-batch in a plant ------------------------------------------------------------------

CW = """\
  - id: CW
    category: utility
    utility: {kind: cooling_water}
    ports: [{id: r, direction: in, kind: energy}]
"""
POWER = """\
  - id: POWER
    category: utility
    utility: {kind: electricity}
    ports: [{id: r, direction: out, kind: energy}]
"""
PORTS = "{id: q, direction: out, kind: energy}, {id: power, direction: in, kind: energy}"


def _cooled(duty="", stream="from: R.q, to: CW.r", cooling=True):
    """The semi-batch with its agitator's power and (*cooling*) a cooling-water stream Q1."""
    text = (
        semi.FLOWSHEET.replace("products:\n", "products:\n" + CW)
        .replace("feeds:\n", "feeds:\n" + POWER)
        .replace("{id: out, direction: out}]", "{id: out, direction: out}, " + PORTS + "]")
    )
    if cooling:
        state = f", state: {{design: {{duty: {duty}}}}}" if duty else ""
        text += f"  - {{id: Q1, kind: energy, {stream}{state}}}\n"
    return text + "  - {id: P1, kind: energy, from: POWER.r, to: R.power}\n"


def _semi_plant(tmp_path, flowsheet=None):
    return semi._plant(tmp_path, flowsheet or _cooled())


def _streams(ws):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return {s["id"]: s for s in data["streams"]}


def _duty_findings(result):
    return [f for f in result.findings if f.rule == "cheme.process-duty"]


def _removed():
    """kW the fixture's semi-batch removes: dHr x the reacted share of its 1 kmol/h dose."""
    k = 0.01
    return -HEAT * (1 - (1 - math.exp(-k * DOSING)) / (k * DOSING)) / 3600.0


def test_propagate_writes_the_semibatchs_duty_on_its_cooling_stream(tmp_path):
    ws = _semi_plant(tmp_path)
    process, _ = load(ws.root)
    node = process.nodes["R"]
    goal, why = target(process, node)  # the cooling stream, not the agitator's power
    assert duty_model(node) == "semibatch" and goal.stream.id == "Q1" and not goal.into
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level != "info"], [
        f.format() for f in result.findings
    ]
    q1 = _streams(ws)["Q1"]["state"]["design"]["duty"]
    assert q1["provenance"] == "calculated"
    assert q1["source"] == "cheme process propagate: semibatch duty R from S1 S2"
    assert q1["value"] == pytest.approx(_removed(), rel=1e-5)  # out of the step: positive
    assert "state" not in _streams(ws)["P1"]  # the power stream is not touched
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert not _duty_findings(run(ws, process, "design", write=False))
    # a slower reaction makes the duty stale
    path = ws.root / "process/reactions.yaml"
    path.write_text(path.read_text().replace("value: -100000", "value: -90000"))
    process, _ = load(ws.root)
    stale = [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert any("Q1" in f.ids for f in stale), [f.format() for f in stale]
    run(ws, process, "design", write=True)
    q1 = _streams(ws)["Q1"]["state"]["design"]["duty"]
    assert q1["value"] == pytest.approx(_removed() * 0.9, rel=1e-5)
    # the reactors report shows the model's duty instead of ?
    text = reactor_text(reactor_report(ws.root))
    assert "duty ?" not in text and "(semibatch model, year average)" in text
    assert "on Q1 (out" in text


def test_a_given_duty_is_compared_never_overwritten(tmp_path):
    given = "{value: 30.0, provenance: assumed, source: hand}"
    ws = _semi_plant(tmp_path, _cooled(duty=given))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "warning" and finding.ids == ["R"] and finding.line
    assert "Q1 duty 30 kW (assumed)" in finding.message
    assert f"the model gives {_removed():.6g} kW" in finding.message
    assert _streams(ws)["Q1"]["state"]["design"]["duty"]["value"] == 30.0
    # cheme validate reports it too
    (checked,) = [f for f in rules(process) if f.rule == "cheme.process-duty"]
    assert checked.level == "warning" and checked.ids == ["R"] and checked.line
    assert checked.message == finding.message
    # within the flowsheet's relative tolerance (0.005): no finding
    close = f"{{value: {_removed() * 1.004:.6g}, provenance: given, source: test}}"
    ws = _semi_plant(tmp_path / "close", _cooled(duty=close))
    process, _ = load(ws.root)
    assert not _duty_findings(run(ws, process, "design", write=False))
    assert not [f for f in rules(process) if f.rule == "cheme.process-duty"]


def test_a_stream_against_the_models_heat_is_reported_not_written(tmp_path):
    ws = _semi_plant(
        tmp_path,
        _cooled(stream="from: CW.r, to: R.q")
        .replace("{id: q, direction: out, kind: energy}", "{id: q, direction: in, kind: energy}")
        .replace(
            "ports: [{id: r, direction: in, kind: energy}]",
            "ports: [{id: r, direction: out, kind: energy}]",
        ),
    )
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "warning" and "the model's heat flows out of it" in finding.message
    assert "state" not in _streams(ws)["Q1"]


def test_the_energy_port_chooses_among_heat_streams(tmp_path):
    # the power stream from a terminal that is a heat utility: two heat streams, ambiguous
    two = _cooled().replace("utility: {kind: electricity}", "utility: {kind: steam}")
    ws = _semi_plant(tmp_path / "two", two)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "2 heat streams (Q1, P1)" in finding.message
    assert "state" not in _streams(ws)["Q1"]
    named = two.replace("reactor: semibatch\n", "reactor: semibatch\n    energy_port: q\n")
    ws = _semi_plant(tmp_path / "named", named)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-energy-port"]
    run(ws, process, "design", write=True)
    assert _streams(ws)["Q1"]["state"]["design"]["duty"]["value"] == pytest.approx(
        _removed(), rel=1e-5
    )


def test_energy_port_rules(tmp_path):
    wrong = _cooled().replace("reactor: semibatch\n", "reactor: semibatch\n    energy_port: out\n")
    process, _ = load(_semi_plant(tmp_path / "a", wrong).root)
    (error,) = [f for f in rules(process) if f.rule == "cheme.process-energy-port"]
    assert error.level == "error" and "energy_port out is no energy port" in error.message
    assert error.line and error.hint
    # on a node no model gives a duty: a warning
    mixer = semi.FLOWSHEET.replace(
        "  - id: R\n",
        "  - id: M\n    class: Mixing\n    energy_port: q\n"
        "    ports: [{id: q, direction: in, kind: energy}]\n  - id: R\n",
    )
    process, _ = load(_semi_plant(tmp_path / "b", mixer).root)
    (warning,) = [f for f in rules(process) if f.rule == "cheme.process-energy-port"]
    assert warning.level == "warning" and "no model of it gives a duty" in warning.message


def test_a_plant_without_heat_streams_is_as_before(tmp_path):
    """No energy stream, or only the agitator's power: nothing written, nothing said, and a
    node's dump (its fingerprint) has no energy_port."""
    for name, flowsheet in (("plain", semi.FLOWSHEET), ("power", _cooled(cooling=False))):
        ws = semi._plant(tmp_path / name, flowsheet)
        process, _ = load(ws.root)
        result = run(ws, process, "design", write=True)
        assert not _duty_findings(result)
    assert "energy_port" not in Step.model_validate({"id": "S", "block": "B"}).model_dump()


# -- a batch still, a crystallizer, a conversion step -------------------------------------------

STEAM = """\
  - id: LPS
    category: utility
    utility: {kind: steam}
    ports: [{id: s, direction: out, kind: energy}]
"""


def test_a_stills_duty_is_the_latent_heat_of_its_distillate(tmp_path):
    """Q = sum_i dHvap_i D_i (kmol/h distilled), whatever the boil-up rate."""
    flowsheet = (
        still.FLOWSHEET.replace("feeds:\n", "feeds:\n" + STEAM).replace(
            "      - {id: bottom, direction: out}\n",
            "      - {id: bottom, direction: out}\n      - {id: heat, direction: in, "
            "kind: energy}\n",
        )
        + "  - id: Q\n    kind: energy\n    from: LPS.s\n    to: S.heat\n"
    )
    ws = still._plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    streams = _streams(ws)
    top = streams["S3"]["state"]["design"]
    x = top["composition"]["values"]
    kmol = top["flow"]["value"] / (x["A"] * 78.11 + x["B"] * 92.14)  # kg/h -> kmol/h
    exact = kmol * (x["A"] * 30720 + x["B"] * 33180) / 3600.0
    duty = streams["Q"]["state"]["design"]["duty"]
    assert duty["value"] == pytest.approx(exact, rel=1e-5)
    assert duty["source"] == "cheme process propagate: still duty S from S1 S2"
    # the boil-up rate changes the time, not the year-average duty: not stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("boilup: {value: 20,", "boilup: {value: 40,"))
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]


def test_a_crystallizers_duty_is_its_lumped_energy_balance(tmp_path):
    """Felder's evaporative crystallizer at 350 K: Q = m cp (T - T_feed) + crystals dHc +
    evaporated lambda, on the propagated outlets."""
    flowsheet = (
        crystal.FLOWSHEET.replace("feeds:\n", "feeds:\n" + STEAM)
        .replace(
            "      - {id: purge, direction: out}\n",
            "      - {id: purge, direction: out}\n      - {id: heat, direction: in, "
            "kind: energy}\n",
        )
        .replace(
            "      basis: solubility\n",
            "      basis: solubility\n      temperature: 350\n      energy: {heat_capacity: "
            "3.0, heat_of_crystallization: -50, latent_heat: 2300, provenance: assumed}\n",
        )
        + "  - id: Q\n    kind: energy\n    from: LPS.s\n    to: CR.heat\n"
    )
    ws = crystal._plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    streams = _streams(ws)
    vapour = streams["S2"]["state"]["design"]["flow"]["value"]
    from chemeascode.domains.process.crystallization import crystallizer_report

    (unit,) = crystallizer_report(ws.root).units
    formed = unit["solution"]["crystals_formed_kg_h"]
    assert vapour > 0 and formed > 0
    exact = (4500 * 3.0 * (350 - 300) + formed * -50 + vapour * 2300) / 3600.0
    duty = streams["Q"]["state"]["design"]["duty"]
    assert duty["value"] == pytest.approx(exact, rel=1e-5)
    assert duty["source"] == "cheme process propagate: crystallizer duty CR from S1"


CONVERSION_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_heat_capacity: 150}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_heat_capacity: 120}
templates:
  - {id: liquid, components: [A, B]}
"""

CONVERSION_REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     conversion: {key: A, value: 0.6, provenance: assumed},
     heat_of_reaction: {value: -80000, provenance: assumed}}
"""

CONVERSION = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - id: CW
    category: utility
    utility: {kind: cooling_water}
    ports: [{id: r, direction: in, kind: energy}]
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1]
    ports: [{id: in, direction: in}, {id: out, direction: out},
            {id: q, direction: out, kind: energy}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 290, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 10, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: liquid
    state:
      design:
        temperature: {value: 320, provenance: given}
  - {id: Q, kind: energy, from: R.q, to: CW.r}
"""


def _conversion_plant(tmp_path, flowsheet=CONVERSION, materials=None, reactions=None):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: conversion-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials or CONVERSION_MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(reactions or CONVERSION_REACTIONS)
    return Workspace(root)


#: kW into the fixture's conversion step (negative: removed): the inlet from 290 K to the
#: heat of reaction's 298.15 K, 6 kmol/h of A reacted there, the outlet (4 A, 6 B) to 320 K.
HESS = (6 * -80000 + 10 * 150 * 8.15 + (4 * 150 + 6 * 120) * 21.85) / 3600.0


def test_a_conversion_steps_duty_follows_hess_at_the_heats_temperature(tmp_path):
    """10 kmol/h of A at 290 K to 320 K, 60 % to B: the inlet brought to the heat of reaction's
    temperature, reacting there, the outlet brought to its own (exact for constant cp)."""
    ws = _conversion_plant(tmp_path)
    root = ws.root
    process, _ = load(root)
    result = run(ws, process, "design", write=True)
    assert not _duty_findings(result), [f.format() for f in result.findings]
    duty = _streams(ws)["Q"]["state"]["design"]["duty"]  # written into the flow mapping
    assert duty["value"] == pytest.approx(-HESS, rel=1e-5)
    assert "{id: Q, kind: energy, from: R.q, to: CW.r, state: {design: {duty: {value:" in (
        (root / "process/flowsheet.yaml").read_text()
    )
    (row,) = reactor_report(root).reactors
    assert row["model_duty"]["heat_in_kW"] == pytest.approx(HESS, rel=1e-9)
    assert row["model_duty"]["terms_kW"]["reaction"] == pytest.approx(6.0 * -80000 / 3600.0)
    # the hand value of that path agrees: no finding
    exact = f"state: {{design: {{duty: {{value: {-HESS:.6f}, provenance: assumed}}}}}}"
    hand = _conversion_plant(
        tmp_path / "hand", CONVERSION.replace("to: CW.r}", f"to: CW.r, {exact}}}")
    )
    process, _ = load(hand.root)
    assert not _duty_findings(run(hand, process, "design", write=False))
    assert not [f for f in rules(process) if f.rule == "cheme.process-duty"]
    # the heat given at 320 K: the inlet heated to it, nothing after; stale, and refilled
    path = root / "process/reactions.yaml"
    path.write_text(path.read_text().replace("value: -80000,", "value: -80000, temperature: 320,"))
    process, _ = load(root)
    assert [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    run(ws, process, "design", write=True)
    at_320 = (6 * -80000 + 10 * 150 * 30) / 3600.0
    assert _streams(ws)["Q"]["state"]["design"]["duty"]["value"] == pytest.approx(-at_320, rel=1e-5)
    # without a heat of reaction: nothing, and why
    root = tmp_path / "plant"
    (root / "process/reactions.yaml").write_text(NO_HEAT)
    path = root / "process/flowsheet.yaml"
    path.write_text(CONVERSION)
    process, _ = load(root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "heat_of_reaction of R1" in finding.message
    assert "duty" not in str(_streams(ws)["Q"])


NO_HEAT = CONVERSION_REACTIONS.replace(
    ",\n     heat_of_reaction: {value: -80000, provenance: assumed}", ""
)


# -- electricity, liquids, two models on one stream ---------------------------------------------

RECTIFIER = """\
  - id: T
    class: ProcessStep
    ports: [{id: dc, direction: out, kind: energy}]
"""


def _electrolyser(power="{design: {duty: {value: 50, provenance: given}}}", cooling=True):
    """The conversion step fed by a rectifier step T (energy stream E, DC power) and cooled
    by cooling water (Q)."""
    text = CONVERSION.replace("blocks:\n", "blocks:\n" + RECTIFIER).replace(
        "{id: q, direction: out, kind: energy}]",
        "{id: q, direction: out, kind: energy},\n            {id: power, direction: in, "
        "kind: energy}]",
    )
    if not cooling:
        text = text.replace("  - {id: Q, kind: energy, from: R.q, to: CW.r}\n", "")
    state = f", state: {power}" if power else ""
    return text + f"  - {{id: E, kind: energy, from: T.dc, to: R.power{state}}}\n"


def test_an_electrolysers_dc_power_is_work_not_its_heat_stream(tmp_path):
    """The rectifier's DC power into the cell is not heat: the cooling stream takes Q = H(out)
    - H(in) - W, the work W the power brings in subtracted."""
    ws = _conversion_plant(tmp_path, _electrolyser())
    process, _ = load(ws.root)
    goal, _ = target(process, process.nodes["R"])
    assert goal.stream.id == "Q"
    result = run(ws, process, "design", write=True)
    assert not [f for f in _duty_findings(result) if f.level != "info"], [
        f.format() for f in result.findings
    ]
    streams = _streams(ws)
    assert streams["Q"]["state"]["design"]["duty"]["value"] == pytest.approx(
        -(HESS - 50.0), rel=1e-5
    )
    assert streams["E"]["state"]["design"]["duty"]["value"] == 50  # not touched
    (row,) = reactor_report(ws.root).reactors
    assert row["model_duty"]["terms_kW"]["other energy streams"] == pytest.approx(-50.0)
    # more power: the duty goes stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("value: 50,", "value: 60,"))
    process, _ = load(ws.root)
    stale = [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert any("Q" in f.ids for f in stale), [f.format() for f in stale]
    # the power without a duty: the cell's heat is not known, nothing written
    ws = _conversion_plant(tmp_path / "unknown", _electrolyser(power=""))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "other energy stream(s) E" in finding.message
    assert "state" not in _streams(ws)["Q"]


def test_an_energy_stream_between_two_steps_is_heat_only_by_energy_port(tmp_path):
    """Without energy_port, a stream from another block or step is not taken as the heat
    stream (it may be power or work): said, not written."""
    ws = _conversion_plant(tmp_path, _electrolyser(power="", cooling=False))
    process, _ = load(ws.root)
    goal, why = target(process, process.nodes["R"])
    assert goal is None and "E joins another block or step" in why
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "energy_port" in finding.message
    assert "state" not in _streams(ws)["E"]
    # named in energy_port: the model's heat goes on it (here out of the step: reported)
    named = _electrolyser(power="", cooling=False).replace(
        "    reactions: [R1]\n", "    reactions: [R1]\n    energy_port: power\n"
    )
    ws = _conversion_plant(tmp_path / "named", named)
    process, _ = load(ws.root)
    goal, _ = target(process, process.nodes["R"])
    assert goal.stream.id == "E" and goal.chosen == "energy_port"


IDEAL_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05,
     ideal_gas: {dHf_298: -52600, S_298: 243, cp_R: [6.0]}}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05,
     ideal_gas: {dHf_298: -166000, S_298: 264, cp_R: [5.5]}}
templates:
  - {id: liquid, components: [A, B]}
"""


def test_a_liquid_conversion_step_does_not_take_the_ideal_gas_enthalpy(tmp_path):
    """Streams said to be liquid, a reaction without a phase, full ideal-gas data: H(out) -
    H(in) of ideal gases would leave out the latent heats; the declared heat is needed."""
    reactions = NO_HEAT.replace(" phase: liquid,", "")
    liquid = "        phase: {value: liquid, provenance: given}\n"
    flowsheet = CONVERSION.replace(
        "        temperature: {value: 290, provenance: given}\n",
        "        temperature: {value: 290, provenance: given}\n" + liquid,
    ).replace(
        "        temperature: {value: 320, provenance: given}\n",
        "        temperature: {value: 320, provenance: given}\n" + liquid,
    )
    ws = _conversion_plant(tmp_path, flowsheet, IDEAL_MATERIALS, reactions)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "heat_of_reaction of R1" in finding.message
    assert "state" not in _streams(ws)["Q"]
    # the same step in the gas phase takes it
    ws = _conversion_plant(tmp_path / "gas", CONVERSION, IDEAL_MATERIALS, reactions)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    assert _streams(ws)["Q"]["state"]["design"]["duty"]["value"] > 0


def test_a_component_changing_phase_across_a_conversion_step_leaves_its_duty_unknown(tmp_path):
    """A vapour inlet whose unreacted A leaves in a liquid outlet: its condensation is not in
    the declared-heat path, so the duty is not known (not a value without the latent heat)."""
    flowsheet = CONVERSION.replace(
        "        temperature: {value: 290, provenance: given}\n",
        "        temperature: {value: 290, provenance: given}\n"
        "        phase: {value: vapor, provenance: given}\n",
    ).replace(
        "        temperature: {value: 320, provenance: given}\n",
        "        temperature: {value: 320, provenance: given}\n"
        "        phase: {value: liquid, provenance: given}\n",
    )
    ws = _conversion_plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "the latent heat of A" in finding.message
    assert "state" not in _streams(ws)["Q"]


TWO_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_heat_capacity: 150}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_heat_capacity: 150}
  - {id: C, name: C, formula: C3H6O, molar_mass: 58.08, liquid_heat_capacity: 150}
  - {id: D, name: D, formula: C3H6O, molar_mass: 58.08, liquid_heat_capacity: 150}
templates:
  - {id: ab, components: [A, B]}
  - {id: cd, components: [C, D]}
"""

TWO_REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     conversion: {key: A, value: 0.5, provenance: assumed},
     heat_of_reaction: {value: -80000, provenance: assumed}}
  - {id: R2, stoichiometry: {C: -1, D: 1}, phase: liquid,
     conversion: {key: C, value: 0.5, provenance: assumed},
     heat_of_reaction: {value: HEAT, provenance: assumed}}
"""


def _feed(sid, frm, to, template, key=None):
    state = (
        "        flow: {value: 10, provenance: given}\n"
        f"        composition: {{basis: mole_fraction, values: {{{key}: 1.0}}, "
        "provenance: given}\n"
        if key
        else ""
    )
    return (
        f"  - id: {sid}\n    from: {frm}\n    to: {to}\n    template: {template}\n"
        "    state:\n      design:\n        temperature: {value: 298.15, provenance: given}\n"
        "        pressure: {value: 101.325, provenance: given}\n" + state
    )


TWO = (
    """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F1, ports: [{id: out, direction: out}]}
  - {id: F2, ports: [{id: out, direction: out}]}
products:
  - {id: P1, ports: [{id: in, direction: in}]}
  - {id: P2, ports: [{id: in, direction: in}]}
blocks:
  - id: H
    class: ReactingChemicals
    reactions: [R1]
    energy_port: q
    ports: [{id: in, direction: in}, {id: out, direction: out},
            {id: q, direction: out, kind: energy}]
  - id: R
    class: ReactingChemicals
    reactions: [R2]
    energy_port: q
    ports: [{id: in, direction: in}, {id: out, direction: out},
            {id: q, direction: in, kind: energy}]
streams:
"""
    + _feed("S1", "F1.out", "H.in", "ab", "A")
    + _feed("S2", "H.out", "P1.in", "ab")
    + _feed("S3", "F2.out", "R.in", "cd", "C")
    + _feed("S4", "R.out", "P2.in", "cd")
    + "  - {id: Q, kind: energy, from: H.q, to: R.q}\n"
)


def test_two_models_on_one_energy_stream_are_compared(tmp_path):
    """H releases 5 x 80000 kJ/h into Q, R takes 5 x 40000: neither is written, and both
    propagate and validate name the two; when they agree, the stream gets the duty."""
    ws = _conversion_plant(tmp_path, TWO, TWO_MATERIALS, TWO_REACTIONS.replace("HEAT", "40000"))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    findings = [f for f in _duty_findings(result) if f.level == "warning"]
    assert {tuple(f.ids) for f in findings} == {("H",), ("R",)}, [f.format() for f in findings]
    assert "H (conversion) 111.111 kW, R (conversion) 55.5556 kW" in findings[0].message
    assert "state" not in _streams(ws)["Q"]
    (found,) = [f for f in rules(process) if f.rule == "cheme.process-duty"][:1]
    assert found.level == "warning" and "neither is written" in found.message
    ws = _conversion_plant(
        tmp_path / "agree", TWO, TWO_MATERIALS, TWO_REACTIONS.replace("HEAT", "80000")
    )
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in _duty_findings(result) if f.level != "info"]
    duty = _streams(ws)["Q"]["state"]["design"]["duty"]
    assert duty["value"] == pytest.approx(5 * 80000 / 3600.0, rel=1e-5)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-duty"]


def test_a_conversion_step_without_heat_or_stream_has_no_model_duty_entry(tmp_path):
    """process reactors --json adds model_duty only where the model knows a duty or a stream
    wants one."""
    plain = CONVERSION.replace("  - {id: Q, kind: energy, from: R.q, to: CW.r}\n", "")
    ws = _conversion_plant(tmp_path, plain, reactions=NO_HEAT)
    (row,) = reactor_report(ws.root).reactors
    assert "model_duty" not in row
