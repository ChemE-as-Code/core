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
    # within the flowsheet's relative tolerance (0.005): no finding
    close = f"{{value: {_removed() * 1.004:.6g}, provenance: given, source: test}}"
    ws = _semi_plant(tmp_path / "close", _cooled(duty=close))
    process, _ = load(ws.root)
    assert not _duty_findings(run(ws, process, "design", write=False))


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


def test_a_conversion_steps_duty_follows_hess_at_the_outlet_temperature(tmp_path):
    """10 kmol/h of A at 290 K to 320 K, 60 % to B: Q = xi dHr + n_A cp_A (T_out - T_in), the
    inlet brought to the outlet's temperature and reacting there."""
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: conversion-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(CONVERSION_MATERIALS)
    (root / "process/flowsheet.yaml").write_text(CONVERSION)
    (root / "process/reactions.yaml").write_text(CONVERSION_REACTIONS)
    ws = Workspace(root)
    process, _ = load(root)
    result = run(ws, process, "design", write=True)
    assert not _duty_findings(result), [f.format() for f in result.findings]
    heat_in = (6.0 * -80000 + 10 * 150 * (320 - 290)) / 3600.0  # kW, negative: removed
    duty = _streams(ws)["Q"]["state"]["design"]["duty"]  # written into the flow mapping
    assert duty["value"] == pytest.approx(-heat_in, rel=1e-5)
    assert "{id: Q, kind: energy, from: R.q, to: CW.r, state: {design: {duty: {value:" in (
        (root / "process/flowsheet.yaml").read_text()
    )
    (row,) = reactor_report(root).reactors
    assert row["model_duty"]["heat_in_kW"] == pytest.approx(heat_in, rel=1e-9)
    assert row["model_duty"]["terms_kW"]["reaction"] == pytest.approx(6.0 * -80000 / 3600.0)
    # without a heat of reaction: nothing, and why
    (root / "process/reactions.yaml").write_text(
        CONVERSION_REACTIONS.replace(
            ",\n     heat_of_reaction: {value: -80000, provenance: assumed}", ""
        )
    )
    path = root / "process/flowsheet.yaml"
    path.write_text(CONVERSION)
    process, _ = load(root)
    result = run(ws, process, "design", write=True)
    (finding,) = _duty_findings(result)
    assert finding.level == "info" and "heat_of_reaction of R1" in finding.message
    assert "duty" not in str(_streams(ws)["Q"])
