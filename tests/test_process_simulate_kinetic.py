"""cheme process simulate with a fixed bed (``reactor: pfr``): the bed is translated as a
``kinetic_pfr`` unit, solved by cheme-as-code (:mod:`chemeascode.domains.process.fixed_bed`) and
coupled to the DWSIM solve as an external unit (an outer loop around DWSIM, which sees a
conversion reactor), never presented as a native DWSIM kinetic reactor.

Without DWSIM: the translation, the refusals, the conversions DWSIM is given, and the outer
loop against a stand-in solver. With CHEME_DWSIM_TESTS=1: an ammonia-like synthesis loop
(reactor, flash, purge, recycle) whose converged reactor outlet must agree with the bed solved
at the converged inlet and close the element balances of the plant.

The rate law here is a TEST FIXTURE (provenance: assumed), chosen to make the bed kinetically
limited at the test's conditions: it is not ammonia synthesis kinetics. The components' ideal-gas
data and the reaction are those of tests/test_process_simulate_reactors.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chemeascode.domains.process.fixed_bed import solve_bed
from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation import coupling
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace
from tests.test_process_simulate_reactors import MATERIALS

dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

#: N2 + 3 H2 = 2 NH3 with a power law on partial pressures (bar) and the (1 - Q/K) approach to
#: equilibrium, K from the components' ideal-gas data. A and Ea are a test fixture.
REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: SYN
    stoichiometry: {N2: -1, H2: -3, NH3: 2}
    phase: vapor
    reversible: true
    catalyst: FE
    rate:
      form: power_law
      basis: catalyst_mass
      driving: partial_pressure
      k: {A: 6.0e-4, Ea: 80000}
      orders: {N2: 1, H2: 1}
      reverse: equilibrium
      provenance: assumed
      source: "test fixture (tests/test_process_simulate_kinetic.py), not real kinetics"
"""

CATALYSTS = """\
schema: cheme/catalysts/v1
kind: catalysts
catalysts:
  - id: FE
    active_phase: Fe
    physical:
      bulk_density: 2000
      provenance: assumed
      source: "test fixture"
"""

#: One bed between a feed and a product.
ONCE = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
steps:
  - id: R1
    block: B
    class: ReactingChemicals
    reactions: [SYN]
    reactor: pfr
    catalyst: FE
    bed: {catalyst_mass: 2000, heat: adiabatic, provenance: assumed, source: test fixture}
    ports: [{id: in, direction: in, delegates: in}, {id: out, direction: out, delegates: out}]
blocks:
  - {id: B, class: ReactingChemicals, ports: [{id: in, direction: in}, {id: out, direction: out}]}
streams:
  - id: S1
    from: F.out
    to: R1.in
    template: syngas
    state:
      design:
        temperature: {value: 673.15, provenance: given}
        pressure: {value: 10000, provenance: given}
        flow: {value: 460, provenance: given}
        composition:
          basis: mole_fraction
          values: {N2: 0.23913, H2: 0.71739, NH3: 0.02174, AR: 0.02174}
          provenance: given
  - id: S2
    from: R1.out
    to: P.in
    template: syngas
"""

SIMULATION = """\
schema: cheme/simulation/v1
kind: simulation
property_package: Peng-Robinson (PR)
"""

#: The synthesis loop: fresh feed + recycle -> heater -> bed -> flash (ammonia condensed) ->
#: purge 10 % of the gas, recycle the rest.
LOOP = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: W, ports: [{id: in, direction: in}]}
blocks:
  - id: L
    class: ReactingChemicals
    ports:
      - {id: in, direction: in}
      - {id: ammonia, direction: out}
      - {id: purge, direction: out}
steps:
  - id: M1
    block: L
    class: MixingSimple
    ports:
      - {id: feed, direction: in, delegates: in}
      - {id: recycle, direction: in}
      - {id: out, direction: out}
  - id: H1
    block: L
    class: SupplyingThermalEnergy
    ports: [{id: in, direction: in}, {id: out, direction: out}]
  - id: R1
    block: L
    class: ReactingChemicals
    reactions: [SYN]
    reactor: pfr
    catalyst: FE
    bed: {catalyst_mass: 2000, heat: adiabatic, provenance: assumed, source: test fixture}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
  - id: C1
    block: L
    class: SeparatingByFlash
    ports:
      - {id: in, direction: in}
      - {id: vapor, direction: out}
      - {id: liquid, direction: out, delegates: ammonia}
  - id: SP
    block: L
    class: SplittingMaterial
    split: {purge: 0.1}
    ports:
      - {id: in, direction: in}
      - {id: purge, direction: out, delegates: purge}
      - {id: recycle, direction: out}
streams:
  - id: S1
    from: F.out
    to: M1.feed
    template: syngas
    state:
      design:
        temperature: {value: 303.15, provenance: given}
        pressure: {value: 10000, provenance: given}
        flow: {value: 100, provenance: given}
        composition:
          basis: mole_fraction
          values: {N2: 0.2475, H2: 0.7425, NH3: 0.0, AR: 0.01}
          provenance: given
""" + "".join(
    f"  - id: {sid}\n    from: {a}\n    to: {b}\n    template: syngas\n"
    for sid, a, b in (
        ("S2", "M1.out", "H1.in"),
        ("S3", "H1.out", "R1.in"),
        ("S4", "R1.out", "C1.in"),
        ("S5", "C1.vapor", "SP.in"),
        ("S6", "C1.liquid", "P.in"),
        ("S7", "SP.purge", "W.in"),
        ("S8", "SP.recycle", "M1.recycle"),
    )
)

LOOP_SIMULATION = """\
schema: cheme/simulation/v1
kind: simulation
property_package: Peng-Robinson (PR)
specs:
  H1:
    outlet_temperature: {value: 673.15, provenance: assumed}
  C1:
    temperature: {value: 243.15, provenance: assumed}
    pressure: {value: 10000, provenance: assumed}
  R1:
    coupling: {tolerance: 1.0e-4, max_iterations: 40}
"""


def _plant(tmp_path: Path, flowsheet: str = ONCE, simulation: str = SIMULATION) -> Workspace:
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: kinetic-sim\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    (root / "process/catalysts.yaml").write_text(CATALYSTS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/simulation.yaml").write_text(simulation)
    return Workspace(root)


def _translate(ws: Workspace):
    process, found = load_process(ws.root)
    assert process is not None, found
    sim, doc, found = load(ws.root)
    assert not found, found
    return translate(process, sim, doc, "design")


def _errors(translation) -> list[str]:
    return [f.message for f in translation.findings if f.level == "error"]


def _unit(model: dict, node: str) -> dict:
    return next(u for u in model["units"] if u["id"] == node)


# -- translation --------------------------------------------------------------------------------


def test_a_fixed_bed_is_a_kinetic_unit_coupled_externally(tmp_path):
    t = _translate(_plant(tmp_path))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["type"] == "kinetic_pfr" and unit["roles"] == ["vapor"]
    spec = unit["spec"]
    assert spec["coupling"] == "external-unit"
    assert "ideal gas" in spec["model"]
    assert spec["reactions"] == [
        {"id": "SYN", "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2}, "phase": "vapor"}
    ]
    assert (spec["tolerance"], spec["temperature_tolerance"], spec["max_iterations"]) == (
        1e-4,
        0.05,
        30,
    )
    assert spec["bed_fingerprint"]


def test_the_rate_law_and_the_bed_are_in_the_fingerprint(tmp_path):
    ws = _plant(tmp_path)
    before = _translate(ws).fingerprint
    path = ws.root / "process/reactions.yaml"
    path.write_text(REACTIONS.replace("A: 6.0e-4", "A: 7.0e-4"))
    after = _translate(ws).fingerprint
    assert after != before
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(ONCE.replace("catalyst_mass: 2000", "catalyst_mass: 3000"))
    assert _translate(ws).fingerprint not in (before, after)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda f, s, r: (f, s + "specs:\n  R1:\n    mode: adiabatic\n", r),
            "mode: the bed model sets the outlet of a kinetic reactor",
        ),
        (
            lambda f, s, r: (
                f,
                s
                + "specs:\n  R1:\n    pressure_drop: {value: 1, unit: kPa, provenance: assumed}\n",
                r,
            ),
            "pressure_drop: the bed model sets",
        ),
        (
            lambda f, s, r: (f, s, r.split("    rate:\n")[0]),
            "no rate law for reaction SYN",
        ),
        (
            lambda f, s, r: (f.replace("    catalyst: FE\n", ""), s, r),
            "no declared catalyst",
        ),
        (
            lambda f, s, r: (f, s, r.replace("phase: vapor", "phase: liquid")),
            "not a vapour reaction",
        ),
    ],
)
def test_what_a_kinetic_unit_refuses(tmp_path, change, message):
    flowsheet, simulation, reactions = change(ONCE, SIMULATION, REACTIONS)
    ws = _plant(tmp_path, flowsheet, simulation)
    (ws.root / "process/reactions.yaml").write_text(reactions)
    t = _translate(ws)
    assert t.model is None
    assert any(message in m for m in _errors(t)), _errors(t)


def test_coupling_is_for_kinetic_units_only(tmp_path):
    lines = ONCE.replace("    reactor: pfr\n", "    reactor: equilibrium\n").splitlines(True)
    flowsheet = "".join(line for line in lines if not line.startswith("    bed:"))
    sim = SIMULATION + "specs:\n  R1:\n    coupling: {max_iterations: 5}\n"
    t = _translate(_plant(tmp_path, flowsheet, sim))
    assert any("coupling is for kinetic reactors" in m for m in _errors(t)), _errors(t)


# -- the conversions DWSIM is given -------------------------------------------------------------


def _reaction(rid: str, stoich: dict[str, float]):
    return SimpleNamespace(id=rid, stoichiometry=stoich)


def test_conversions_reproduce_the_extents_and_reverse_a_backward_reaction():
    syn = _reaction("SYN", {"N2": -1, "H2": -3, "NH3": 2})
    inlet = {"N2": 100.0, "H2": 300.0, "NH3": 10.0}
    # forward: N2 is converted least (10 of 100 against 30 of 300: equal; the first wins)
    unit = coupling.as_conversions(
        {"id": "R1", "inlets": ["a"], "outlets": ["b"], "spec": {}},
        [syn],
        inlet,
        {"N2": 90.0, "H2": 270.0, "NH3": 30.0},
        {"SYN": 10.0},
        700.0,
        5.0,
    )
    assert unit["type"] == "conversion_reactor"
    (entry,) = unit["spec"]["reactions"]
    assert entry["base"] in ("N2", "H2") and entry["conversion"] == pytest.approx(0.1)
    assert unit["spec"]["outlet_temperature_K"] == 700.0
    assert unit["spec"]["pressure_drop_Pa"] == 5000.0
    # backward: ammonia decomposes, written as 2 NH3 -> N2 + 3 H2 with NH3 converted
    back = coupling.as_conversions(
        {"id": "R1", "spec": {}},
        [syn],
        inlet,
        {"N2": 102.0, "H2": 306.0, "NH3": 6.0},
        {"SYN": -2.0},
        None,
        0.0,
    )
    (entry,) = back["spec"]["reactions"]
    assert entry["stoichiometry"] == {"N2": 1, "H2": 3, "NH3": -2}
    assert entry["base"] == "NH3" and entry["conversion"] == pytest.approx(0.4)
    assert back["spec"]["mode"] == "isothermal"


def test_a_series_reaction_cannot_be_an_inlet_conversion():
    a_b = _reaction("AB", {"A": -1, "B": 1})
    b_c = _reaction("BC", {"B": -1, "C": 1})
    with pytest.raises(coupling.CouplingError, match="none of its reactants"):
        coupling.as_conversions(
            {"id": "R1", "spec": {}},
            [a_b, b_c],
            {"A": 10.0},
            {"A": 5.0, "B": 3.0, "C": 2.0},
            {"AB": 5.0, "BC": 2.0},
            None,
            0.0,
        )


# -- the outer loop against a stand-in for DWSIM --------------------------------------------------


MW = {"N2": 28.014, "H2": 2.016, "NH3": 17.031, "AR": 39.948}


def _stream(flows: dict[str, float], t: float, p_pa: float) -> dict:
    total = sum(flows.values())
    y = {n: v / total for n, v in flows.items()}
    return {
        "temperature_K": t,
        "pressure_Pa": p_pa,
        "mass_flow_kg_s": sum(v * MW[n] for n, v in flows.items()) / 3600.0,
        "mole_fractions": y,
        "vapor_fraction": 1.0,
    }


def stand_in(model, save=None, *, drift=0.0, calls=None):
    """DWSIM for the single bed: the conversion reactor as DWSIM solves it (each reaction's
    conversion of its base compound in the inlet, in parallel). *drift* moves the inlet
    temperature on every call (a loop that never settles)."""
    if calls is not None:
        calls.append(model)
    feed = next(s for s in model["streams"] if s["id"] == "S1")["feed"]
    t = feed["temperature_K"] + drift * len(calls or [])
    inlet_stream = {**feed, "temperature_K": t}
    inlet = coupling.molar_flows(inlet_stream, MW)
    (unit,) = model["units"]
    assert unit["type"] == "conversion_reactor"  # never a kinetic unit
    spec = unit["spec"]
    outlet = dict(inlet)
    for r in spec["reactions"]:
        extent = r["conversion"] * inlet.get(r["base"], 0.0) / abs(r["stoichiometry"][r["base"]])
        for n, nu in r["stoichiometry"].items():
            outlet[n] = outlet.get(n, 0.0) + nu * extent
    t_out = spec.get("outlet_temperature_K", t)
    p_out = feed["pressure_Pa"] - spec["pressure_drop_Pa"]
    return {
        "ok": True,
        "version": "9.0.5.0",
        "converged": True,
        "iterations": 1,
        "messages": [],
        "streams": {
            "S1": _stream(inlet, t, feed["pressure_Pa"]),
            "S2": _stream(outlet, t_out, p_out),
        },
        "energies": {},
        "units": {"R1": {"duty_kW": 0.0, "extents_kmol_h": {}}},
    }


def test_the_outer_loop_converges_and_the_record_says_how(tmp_path):
    ws = _plant(tmp_path)
    process, _ = load_process(ws.root)
    calls: list = []
    result = run(
        ws,
        process,
        "design",
        write=True,
        solver=lambda m, s: stand_in(m, s, calls=calls),
    )
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    # the first DWSIM solve already has the bed at the feed (the inlet is a feed)
    assert 1 <= len(calls) <= 2
    info = [f for f in result.findings if f.rule == "cheme.process-sim-coupling"]
    assert info and "external unit" in info[0].message and "converged" in info[0].message
    data = json.loads((ws.root / "process/simulation-run.json").read_text())
    entry = data["cases"]["design"]
    assert entry["converged"] is True
    (row,) = [u for u in entry["units"] if u["id"] == "R1"]
    assert row["unit"] == "kinetic_pfr" and row["coupling"] == "external-unit"
    loop = row["outer_loop"]
    assert loop["converged"] and loop["dwsim_unit"] == "conversion_reactor"
    assert loop["residuals"][-1]["flow"] <= 1e-4
    assert "process/catalysts.yaml" in entry["inputs"]["fingerprints"]
    # the filled outlet is the bed at the feed, and says it was coupled
    out = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1]
    state = out["state"]["design"]
    assert "coupled as external unit" in state["temperature"]["source"]
    bed = loop["bed"]
    assert state["temperature"]["value"] == pytest.approx(bed["outlet_temperature_K"], abs=0.01)
    assert row["results"]["extents_kmol_h"]["SYN"] == pytest.approx(bed["extents_kmol_h"]["SYN"])


def test_a_loop_that_does_not_settle_is_not_converged_and_writes_nothing(tmp_path):
    ws = _plant(
        tmp_path, simulation=SIMULATION + "specs:\n  R1:\n    coupling: {max_iterations: 3}\n"
    )
    process, _ = load_process(ws.root)
    calls: list = []
    result = run(
        ws,
        process,
        "design",
        write=True,
        solver=lambda m, s: stand_in(m, s, drift=5.0, calls=calls),
    )
    assert len(calls) == 3
    assert any(
        f.rule == "cheme.process-sim-not-converged" and "did not converge in 3" in f.message
        for f in result.findings
    ), [f.format() for f in result.findings]
    assert result.written == 0
    out = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1]
    assert "state" not in out
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"] is False
    (row,) = [u for u in entry["units"] if u["id"] == "R1"]
    assert row["coupling"] == "external-unit" and row["outer_loop"]["converged"] is False
    assert len(row["outer_loop"]["residuals"]) == 3


# -- DWSIM: the synthesis loop ------------------------------------------------------------------


ELEMENTS = {"N2": {"N": 2}, "H2": {"H": 2}, "NH3": {"N": 1, "H": 3}, "AR": {"Ar": 1}}


def _flows(state: dict, mw: dict[str, float]) -> dict[str, float]:
    """kmol/h by component of a filled stream (flow kmol/h, mole fractions)."""
    total = state["flow"]["value"]
    unit = state["flow"].get("unit", "kmol/h")
    y = state["composition"]["values"]
    if unit == "kg/h":
        total /= sum(y[n] * mw[n] for n in y)
    return {n: x * total for n, x in y.items()}


@dwsim_tests
def test_dwsim_synthesis_loop_with_a_coupled_bed(tmp_path):
    ws = _plant(tmp_path, LOOP, LOOP_SIMULATION)
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"], entry["messages"]
    (row,) = [u for u in entry["units"] if u["id"] == "R1"]
    assert row["coupling"] == "external-unit"
    loop = row["outer_loop"]
    assert loop["converged"] and loop["residuals"][-1]["flow"] <= 1e-4
    assert {u["coupling"] for u in entry["units"] if u["id"] != "R1"} == {"native"}

    states = {
        s["id"]: s.get("state", {}).get("design", {})
        for s in yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    }
    flows = {sid: _flows(state, MW) for sid, state in states.items() if "composition" in state}
    # the plant's element balances: fresh feed in, liquid ammonia and purge out
    for element in ("N", "H", "Ar"):

        def atoms(f: dict[str, float], element: str = element) -> float:
            return sum(v * ELEMENTS[n].get(element, 0) for n, v in f.items())

        into = atoms(flows["S1"])
        out = atoms(flows["S6"]) + atoms(flows["S7"])
        assert out == pytest.approx(into, rel=2e-3), element
    # the loop made ammonia, most of it in the liquid
    assert flows["S6"]["NH3"] > 0.5 * (flows["S4"]["NH3"] - flows["S3"]["NH3"])

    # the coupled outlet is the bed at the converged inlet (cheme's bed model, re-solved here)
    process, _ = load_process(ws.root)
    reactions, _ = process.reactions_of("R1")
    node = process.nodes["R1"]
    catalyst = process.catalysts.by_id()["FE"]
    inlet = states["S3"]
    bed = solve_bed(
        reactions,
        flows["S3"],
        inlet["temperature"]["value"],
        inlet["pressure"]["value"],
        node.bed,
        catalyst,
        process.ideal_gas(),
        MW,
    )
    total = sum(bed.outlet.values())
    for n, v in bed.outlet.items():
        assert flows["S4"].get(n, 0.0) == pytest.approx(v, abs=2e-3 * total), n
    assert states["S4"]["temperature"]["value"] == pytest.approx(bed.temperature, abs=0.1)


# -- stirred tanks and batches, coupled the same way -----------------------------------------------

#: The single step as an adiabatic stirred tank holding the same catalyst (1000 kg per m3).
TANK = ONCE.replace(
    "    reactor: pfr\n    catalyst: FE\n"
    "    bed: {catalyst_mass: 2000, heat: adiabatic, provenance: assumed, source: test fixture}\n",
    "    reactor: cstr\n    catalyst: FE\n"
    "    tank: {volume: 2.0, catalyst_loading: 1000, heat: adiabatic, provenance: assumed,\n"
    "           source: test fixture}\n",
)


def test_a_stirred_tank_is_a_kinetic_unit_coupled_externally(tmp_path):
    assert "reactor: cstr" in TANK
    t = _translate(_plant(tmp_path, TANK))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["type"] == "kinetic_pfr"  # the external-unit type, whatever the model
    spec = unit["spec"]
    assert spec["coupling"] == "external-unit" and "stirred tank" in spec["model"]
    first = spec["bed_fingerprint"]
    ws = _plant(tmp_path / "b", TANK.replace("volume: 2.0", "volume: 3.0"))
    assert _unit(_translate(ws).model, "R1")["spec"]["bed_fingerprint"] != first
    batch = TANK.replace("reactor: cstr", "reactor: batch").replace(
        "tank: {volume: 2.0, catalyst_loading: 1000, heat: adiabatic, provenance: assumed,\n"
        "           source: test fixture}",
        "batch: {time: 5.0, catalyst_loading: 1000, provenance: assumed}",
    )
    spec = _unit(_translate(_plant(tmp_path / "c", batch)).model, "R1")["spec"]
    assert "batch" in spec["model"]


def test_the_outer_loop_converges_with_a_stirred_tank(tmp_path):
    from chemeascode.domains.process.stirred_tank import solve_node

    ws = _plant(tmp_path, TANK)
    process, _ = load_process(ws.root)
    calls: list = []
    result = run(ws, process, "design", write=True, solver=lambda m, s: stand_in(m, s, calls=calls))
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"] is True
    (row,) = [u for u in entry["units"] if u["id"] == "R1"]
    loop = row["outer_loop"]
    assert loop["converged"] and "stirred tank" in loop["model"]
    # the coupled outlet is the tank model's at the feed
    stream = next(s for s in process.flowsheet.streams if s.id == "S1")
    tank, _ = solve_node(process, process.nodes["R1"], stream, "design")
    assert loop["bed"]["outlet_temperature_K"] == pytest.approx(tank.temperature, abs=0.01)
    assert loop["bed"]["extents_kmol_h"]["SYN"] == pytest.approx(tank.extents["SYN"], rel=1e-6)
    assert tank.temperature > 673.15  # adiabatic and exothermic


@dwsim_tests
def test_dwsim_with_a_coupled_stirred_tank(tmp_path):
    from chemeascode.domains.process.stirred_tank import solve_moles

    ws = _plant(tmp_path, TANK)
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"], entry["messages"]
    states = {
        s["id"]: s.get("state", {}).get("design", {})
        for s in yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    }
    flows = {sid: _flows(state, MW) for sid, state in states.items() if "composition" in state}
    process, _ = load_process(ws.root)
    inlet = states["S1"]
    tank, _ = solve_moles(
        process,
        process.nodes["R1"],
        flows["S1"],
        inlet["temperature"]["value"],
        inlet["pressure"]["value"],
    )
    total = sum(tank.outlet.values())
    for n, v in tank.outlet.items():
        assert flows["S2"].get(n, 0.0) == pytest.approx(v, abs=2e-3 * total), n
    assert states["S2"]["temperature"]["value"] == pytest.approx(tank.temperature, abs=0.1)


def test_an_isothermal_tank_keeps_its_given_temperature_through_the_loop(tmp_path):
    held = TANK.replace("heat: adiabatic", "heat: isothermal").replace(
        "  - id: S2\n    from: R1.out\n    to: P.in\n    template: syngas\n",
        "  - id: S2\n    from: R1.out\n    to: P.in\n    template: syngas\n    state:\n"
        "      design:\n        temperature: {value: 700, provenance: assumed}\n",
    )
    assert "value: 700" in held
    ws = _plant(tmp_path, held)
    process, _ = load_process(ws.root)
    calls: list = []
    run(ws, process, "design", write=True, solver=lambda m, s: stand_in(m, s, calls=calls))
    for model in calls:  # every DWSIM solve had the tank at 700 K, not at the inlet's 673 K
        spec = _unit(model, "R1")["spec"]
        assert spec["mode"] == "outlet_temperature"
        assert spec["outlet_temperature_K"] == pytest.approx(700.0)


def test_the_tank_fingerprint_follows_its_catalysts_age(tmp_path):
    aged = TANK.replace("catalyst_loading: 1000,", "catalyst_loading: 1000, time_on_stream: 100,")
    catalysts = CATALYSTS.replace(
        "    physical:",
        "    deactivation: {law: first_order, kd: 0.001, provenance: assumed}\n    physical:",
    )
    ws = _plant(tmp_path, aged)
    (ws.root / "process/catalysts.yaml").write_text(catalysts)
    first = _unit(_translate(ws).model, "R1")["spec"]["bed_fingerprint"]
    (ws.root / "process/catalysts.yaml").write_text(catalysts.replace("kd: 0.001", "kd: 0.002"))
    assert _unit(_translate(ws).model, "R1")["spec"]["bed_fingerprint"] != first
