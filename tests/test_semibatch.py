"""The semi-batch (``reactor: semibatch``): the accumulation of a dosed reactant against its
closed form, fast and slow reactions in the thermal screening, the energy balance of an
adiabatic dosing, and its place in cheme process propagate, cheme validate and process
reactors (ADR 0048)."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report, reactor_text
from chemeascode.domains.process.schema import Batch, Dosing
from chemeascode.domains.process.stirred_tank import Dose, TankError, solve_batch
from chemeascode.domains.safety.reaction_hazards import screen
from chemeascode.foundation.workspace import Workspace

V = {"A": 0.1, "B": 0.1, "S": 0.1}  # m3/kmol
CP = {"A": 150.0, "B": 150.0, "S": 150.0}  # kJ/(kmol K)
HEAT = -100000.0  # kJ/kmol
DOSING = 3600.0  # s


def _reactions(k, heat=HEAT):
    return Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1},
                    "phase": "liquid",
                    "heat_of_reaction": {"value": heat, "provenance": "assumed"},
                    "rate": {
                        "form": "power_law",
                        "basis": "volume",
                        "driving": "concentration",
                        "k": {"A": k},
                        "orders": {"A": 1},
                        "provenance": "assumed",
                    },
                }
            ],
        }
    ).reactions


def _batch(**kw):
    return Batch.model_validate(
        {"provenance": "assumed", "dosing": [{"stream": "D", "time": DOSING}]} | kw
    )


def _semibatch(k, batch=None, doses=None, charge=None, t=300.0, cp=CP):
    return solve_batch(
        _reactions(k),
        charge or {"S": 5.0},
        t,
        101.325,
        batch or _batch(),
        {},
        Liquid(V),
        cp,
        doses=doses or [Dose({"A": 1.0}, t, [(0.0, DOSING, 1.0)])],
    )


@pytest.mark.parametrize("k", [1e-2, 1e-3, 1e-4])
def test_first_order_constant_dosing_accumulates_as_its_closed_form(k):
    """dn_A/dt = q - k n_A (first order in c_A: the volume cancels), so n_A = (q/k)(1 -
    exp(-k t)) and the accumulation n_A / F is largest when the dosing ends:
    (1 - exp(-k t_d)) / (k t_d)."""
    result = _semibatch(k)
    exact = (1 - math.exp(-k * DOSING)) / (k * DOSING)
    assert result.kind == "semibatch"
    assert result.max_accumulation == pytest.approx(exact, rel=1e-6)
    assert result.max_accumulation_time == pytest.approx(DOSING)
    assert result.outlet["A"] == pytest.approx(exact, rel=1e-6)
    assert result.outlet["B"] == pytest.approx(1 - exact, rel=1e-6)
    assert result.extents["R1"] == pytest.approx(1 - exact, rel=1e-6)
    # the profile of the accumulation follows the closed form too
    for t, x in result.accumulation[1:]:
        assert x == pytest.approx((1 - math.exp(-k * t)) / (k * DOSING), rel=1e-5, abs=1e-12)
    assert result.charge_volume == pytest.approx(0.5)
    assert result.volume == pytest.approx(0.6)  # the dose adds its volume
    assert result.dosing_time == pytest.approx(DOSING)


def test_a_post_reaction_after_the_dosing():
    k = 1e-3
    result = _semibatch(k, _batch(time=1800.0))
    at_end = (1 - math.exp(-k * DOSING)) / (k * DOSING)
    assert result.outlet["A"] == pytest.approx(at_end * math.exp(-k * 1800.0), rel=1e-6)
    assert result.time == pytest.approx(DOSING + 1800.0)
    target = _semibatch(k, _batch(target={"key": "A", "conversion": 0.99}))
    assert target.outlet["A"] == pytest.approx(0.01, rel=1e-6)
    assert target.time > DOSING


def test_a_dosing_profile_and_a_delayed_start():
    k = 1e-3
    steady = _semibatch(k)
    halves = _semibatch(
        k, doses=[Dose({"A": 1.0}, 300.0, [(0.0, 1800.0, 0.5), (1800.0, 3600.0, 0.5)])]
    )
    assert halves.outlet["A"] == pytest.approx(steady.outlet["A"], rel=1e-6)
    # all of it in the first quarter of the time: more accumulates, earlier
    fast = _semibatch(k, doses=[Dose({"A": 1.0}, 300.0, [(0.0, 900.0, 1.0)])])
    assert fast.max_accumulation > steady.max_accumulation
    assert fast.max_accumulation_time == pytest.approx(900.0)
    later = Dosing.model_validate({"stream": "D", "time": 600, "start": 300})
    assert later.segments() == [(300.0, 900.0, 1.0)]
    profile = Dosing.model_validate({"stream": "D", "profile": [[600, 0.25], [1200, 0.75]]})
    assert profile.segments() == [(0.0, 600.0, 0.25), (600.0, 1800.0, 0.75)]


def test_the_schema_of_dosing():
    with pytest.raises(ValueError, match="time or profile"):
        Dosing.model_validate({"stream": "D"})
    with pytest.raises(ValueError, match="add up to 1"):
        Dosing.model_validate({"stream": "D", "profile": [[600, 0.5]]})
    # a semi-batch may end with its dosing; a batch needs its time or target
    assert Batch.model_validate({"provenance": "assumed", "dosing": [{"stream": "D", "time": 1}]})
    with pytest.raises(ValueError, match="time or target"):
        Batch.model_validate({"provenance": "assumed"})
    # a batch's dump (its outlet's fingerprint) is as it was
    assert "dosing" not in Batch.model_validate({"time": 5, "provenance": "assumed"}).model_dump()


def test_fast_and_slow_reactions_accumulate_little_and_much():
    fast, slow = _semibatch(1e-2), _semibatch(1e-4)
    assert fast.max_accumulation < 0.03 < 0.8 < slow.max_accumulation
    # the cooling failure: the accumulated reactant's heat over the content's heat capacity
    t_fast, t_slow = fast.cooling_failure[2], slow.cooling_failure[2]
    assert t_fast - 300.0 < 10.0 < 80.0 < t_slow - 300.0
    # at the end of the slow dosing: 0.84 kmol of A in 6 kmol of liquid
    x = slow.max_accumulation
    assert t_slow == pytest.approx(300.0 + x * 100000.0 / (6.0 * 150.0), rel=1e-6)
    # isothermal and fast: the reaction keeps up with the dosing, q (-dH) over the end volume
    assert fast.peak_cooling_duty == pytest.approx(
        (1.0 / DOSING) * 100000.0 * (1 - math.exp(-1e-2 * DOSING)) / 0.6, rel=1e-3
    )


def test_a_cold_dose_takes_up_heat():
    hot = _semibatch(1e-2)
    cold = _semibatch(1e-2, doses=[Dose({"A": 1.0}, 280.0, [(0.0, DOSING, 1.0)])])
    warming = (1.0 / DOSING) * 150.0 * 20.0 / 0.6  # kW/m3 the cold dose takes up
    assert cold.peak_cooling_duty == pytest.approx(hot.peak_cooling_duty - warming, rel=1e-3)


def test_an_adiabatic_semibatch_closes_its_energy_balance():
    """Equal heat capacities: C_end T_end = C_charge T_0 + C_dose T_dose + (-dH) extent."""
    result = _semibatch(
        1e-3,
        _batch(heat="adiabatic"),
        doses=[Dose({"A": 1.0}, 290.0, [(0.0, DOSING, 1.0)])],
    )
    extent = result.extents["R1"]
    expected = (5.0 * 150.0 * 300.0 + 1.0 * 150.0 * 290.0 - HEAT * extent) / (6.0 * 150.0)
    assert result.temperature == pytest.approx(expected, rel=1e-7)
    assert result.peak_cooling_duty is None  # nothing is removed


def test_a_semibatch_refuses_a_gas_and_an_empty_charge():
    from chemeascode.domains.chemistry.thermochemistry import IdealGas

    gas = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1},
                    "phase": "vapor",
                    "rate": {
                        "form": "power_law",
                        "basis": "volume",
                        "driving": "concentration",
                        "k": {"A": 1e-3},
                        "orders": {"A": 1},
                        "provenance": "assumed",
                    },
                }
            ],
        }
    ).reactions
    data = {n: IdealGas(dHf_298=-1e5, S_298=200.0, cp_R=[4.0]) for n in ("A", "B", "S")}
    with pytest.raises(TankError, match="liquid-phase"):
        solve_batch(
            gas,
            {"S": 1.0},
            300.0,
            101.325,
            _batch(),
            data,
            doses=[Dose({"A": 1.0}, 300.0, [(0.0, 1.0, 1.0)])],
        )
    with pytest.raises(TankError, match="the charge is empty"):
        _semibatch(1e-3, charge={"S": 0.0})


# -- in a plant ---------------------------------------------------------------------------------

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
  - {id: S, name: S, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
templates:
  - {id: liquid, components: [A, B, S]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     heat_of_reaction: {value: -100000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.01},
            orders: {A: 1}, provenance: assumed}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
  - {id: G, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1]
    reactor: semibatch
    batch: {dosing: [{stream: S2, time: 3600}], provenance: assumed}
    hazard: {mtt: 380, td24: 390, provenance: assumed}
    ports: [{id: in, direction: in}, {id: dose, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 300, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 5, provenance: given}
        composition: {basis: mole_fraction, values: {S: 1.0}, provenance: given}
  - id: S2
    from: G.out
    to: R.dose
    template: liquid
    state:
      design:
        temperature: {value: 300, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 1, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S3
    from: R.out
    to: P.in
    template: liquid
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, reactions=REACTIONS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: semibatch-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(reactions)
    return Workspace(root)


def _messages(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [f.message for f in found + rules(process) if f.rule == "cheme.process-reactor"]


def test_propagate_solves_a_semibatch_and_reports_it(tmp_path):
    ws = _plant(tmp_path)
    assert not _messages(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 1, [f.format() for f in result.findings]
    state = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][2]["state"][
        "design"
    ]
    exact = (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    assert state["flow"]["value"] == pytest.approx(6 * 44.05, rel=1e-6)  # kg/h: all of it
    assert state["composition"]["values"]["A"] == pytest.approx(exact / 6, rel=1e-4)
    (row,) = reactor_report(ws.root).reactors
    tank = row["tank"]
    assert tank["kind"] == "semibatch"
    assert tank["max_accumulation"] == pytest.approx(exact, rel=1e-6)
    assert tank["cooling_failure"]["mtsr_K"] < 310.0
    text = reactor_text(reactor_report(ws.root))
    assert "semibatch:" in text and "accumulation of the dosed reactant at most" in text
    # a slower dosing makes the outlet stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("time: 3600}", "time: 7200}"))
    process, _ = load(ws.root)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_the_screening_tells_a_dosing_controlled_semibatch_from_an_accumulating_one(tmp_path):
    """The same reaction and dose: fast, the dosing controls it (low accumulation, class 1);
    slow, the reactant accumulates (the MTSR beyond the TD24, class 4)."""
    (fast,) = screen(_plant(tmp_path / "fast").root).entries
    assert fast.model == "semibatch"
    assert fast.accumulation == pytest.approx(0.02778, rel=1e-3)
    assert fast.mtsr < 310.0 and fast.criticality == 1
    slow_plant = _plant(tmp_path / "slow", reactions=REACTIONS.replace("0.01", "1e-4"))
    (slow,) = screen(slow_plant.root).entries
    assert slow.accumulation > 0.8 and slow.mtsr > 390.0 and slow.criticality == 4
    assert any("worst moment" in n for n in slow.notes)
    assert slow.adiabatic_rise == pytest.approx(100000.0 / (6 * 150.0), rel=1e-6)


def test_semibatch_rules(tmp_path):
    batch = FLOWSHEET.replace("reactor: semibatch", "reactor: batch")
    assert any("a batch with dosing" in m for m in _messages(_plant(tmp_path / "a", batch)))
    stray = FLOWSHEET.replace("stream: S2", "stream: S9")
    messages = _messages(_plant(tmp_path / "b", stray))
    assert any("the dosed stream(s) S9 are no inlet" in m for m in messages)
    none = FLOWSHEET.replace("dosing: [{stream: S2, time: 3600}], ", "time: 60, ")
    messages = _messages(_plant(tmp_path / "c", none))
    assert any("reactor semibatch with no dosing" in m for m in messages)
    # a batch's own rules hold for a semi-batch
    ws = _plant(tmp_path / "d", FLOWSHEET.replace("batch: {", "batch: {heat: adiabatic, "))
    path = ws.root / "process/materials.yaml"
    path.write_text(path.read_text().replace("liquid_heat_capacity: 150, ", ""))
    assert any(
        "reactor semibatch with an adiabatic liquid without liquid_heat_capacity" in m
        for m in _messages(ws)
    )


def test_reactor_uncertainty_samples_a_semibatch(tmp_path):
    from chemeascode.domains.process.reactor_uncertainty import sample_node

    uncertain = REACTIONS.replace(
        "orders: {A: 1}, provenance: assumed}",
        "orders: {A: 1}, provenance: assumed, uncertainty: {A: {gsd2: 2.0}}}",
    )
    found = sample_node(_plant(tmp_path, reactions=uncertain).root, "R", samples=20)
    assert found.model == "semibatch" and found.key == "A" and not found.failed
    exact = 1 - (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    assert found.conversion.deterministic == pytest.approx(exact, rel=1e-6)
    assert found.conversion.p5 < exact < found.conversion.p95


def test_the_semibatch_example_is_current_and_screens_low():
    from pathlib import Path

    from chemeascode.project.validate import validate_workspace

    example = Path(__file__).parents[1] / "examples/process-semibatch"
    report = validate_workspace(Workspace(example))
    assert not [f.format() for f in report.findings if f.level != "info"]
    process, _ = load(example)
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    (entry,) = screen(example).entries
    # dosed over 2 h the anhydride hardly accumulates; all at once it would boil the water
    assert entry.accumulation < 0.1 and entry.mtsr < entry.mtt
    assert entry.process_temperature + entry.adiabatic_rise > entry.mtt


def test_an_energy_stream_into_the_semibatch_is_no_charge(tmp_path):
    """An agitator's power into the reactor (an energy stream) is neither the charge nor a dose
    (found by the NBS pilot, process-library#370)."""
    powered = (
        FLOWSHEET.replace(
            "  - {id: G, ports: [{id: out, direction: out}]}\n",
            "  - {id: G, ports: [{id: out, direction: out}]}\n"
            "  - {id: PWR, ports: [{id: q, direction: out, kind: energy}]}\n",
        )
        .replace(
            "{id: dose, direction: in}, ",
            "{id: dose, direction: in}, {id: power, direction: in, kind: energy}, ",
        )
        .replace(
            "  - id: S3\n",
            "  - {id: Q1, from: PWR.q, to: R.power, kind: energy}\n  - id: S3\n",
        )
    )
    ws = _plant(tmp_path, powered)
    assert not _messages(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 1, [f.format() for f in result.findings]
    (entry,) = screen(ws.root).entries
    assert entry.accumulation == pytest.approx(0.02778, rel=1e-3)
