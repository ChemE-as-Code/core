"""cheme process simulate with reactors: the translation of conversion, equilibrium and Gibbs
reactors (reactions from process/reactions.yaml), and, with CHEME_DWSIM_TESTS=1, DWSIM's
reactors against cheme process propagate on the same flowsheet."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.propagate import run as propagate
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace

dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, formula: N2, cas: 7727-37-9, molar_mass: 28.014,
     ideal_gas: {dHf_298: 0.0, S_298: 191.6, cp_R: [3.539, -0.000261, 7e-08, 1.57e-09, -9.9e-13],
                 temperature_range: [50, 1000], provenance: given}}
  - {id: H2, name: Hydrogen, formula: H2, cas: 1333-74-0, molar_mass: 2.016,
     ideal_gas: {dHf_298: 0.0, S_298: 130.7,
                 cp_R: [2.883, 0.003681, -7.72e-06, 6.92e-09, -2.13e-12],
                 temperature_range: [50, 1000], provenance: given}}
  - {id: NH3, name: Ammonia, formula: NH3, cas: 7664-41-7, molar_mass: 17.031,
     ideal_gas: {dHf_298: -45558.0, S_298: 192.8,
                 cp_R: [4.238, -0.004215, 2.041e-05, -2.126e-08, 7.61e-12],
                 temperature_range: [50, 1000], provenance: given}}
  - {id: AR, name: Argon, formula: Ar, cas: 7440-37-1, molar_mass: 39.948,
     ideal_gas: {dHf_298: 0.0, S_298: 154.8, cp_R: [2.5], provenance: given}}
templates:
  - {id: syngas, components: [N2, H2, NH3, AR]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: SYN
    stoichiometry: {N2: -1, H2: -3, NH3: 2}
    reversible: true
    conversion: {key: N2, value: 0.25, provenance: assumed}
    # ln K of N2 + 3 H2 = 2 NH3 at 763.15 K from the ideal-gas data above (bar)
    equilibrium_constant: {a: -10.9563, provenance: assumed}
"""

FLOWSHEET = """\
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
        temperature: {value: 523.15, provenance: given}
        pressure: {value: 1000, provenance: given}
        flow: {value: 1000, provenance: given}
        composition:
          basis: mole_fraction
          values: {N2: 0.2475, H2: 0.7425, NH3: 0.0, AR: 0.01}
          provenance: given
  - id: S2
    from: R1.out
    to: P.in
    template: syngas
    state:
      design:
        temperature: {value: 743.15, provenance: assumed}
"""

SIMULATION = """\
schema: cheme/simulation/v1
kind: simulation
property_package: Peng-Robinson (PR)
specs:
  R1:
    pressure_drop: {value: 0, unit: kPa, provenance: assumed}
"""


def _plant(tmp_path: Path, flowsheet: str = FLOWSHEET, simulation: str = SIMULATION) -> Workspace:
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: reactor-sim\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/simulation.yaml").write_text(simulation)
    return Workspace(root)


def _translate(ws: Workspace):
    process, found = load_process(ws.root)
    assert process is not None, found
    sim, doc, found = load(ws.root)
    assert not found, found
    return translate(process, sim, doc, "design")


def _unit(model: dict, node: str) -> dict:
    return next(u for u in model["units"] if u["id"] == node)


def _errors(translation) -> list[str]:
    return [f.message for f in translation.findings if f.level == "error"]


def _outlet(ws: Workspace) -> dict:
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == "S2")["state"]["design"]


# -- translation --------------------------------------------------------------------------------


def test_a_step_with_reactions_is_a_conversion_reactor(tmp_path):
    t = _translate(_plant(tmp_path))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["type"] == "conversion_reactor" and unit["roles"] == ["vapor"]
    # the outlet temperature of the flowsheet (743.15 K, assumed) fixes the mode
    assert unit["spec"]["mode"] == "outlet_temperature"
    assert unit["spec"]["outlet_temperature_K"] == 743.15
    assert any(
        f.rule == "cheme.process-sim-default" and "flowsheet's outlet temperature" in f.message
        for f in t.findings
    )
    (reaction,) = unit["spec"]["reactions"]
    assert reaction == {
        "id": "SYN",
        "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2},
        "phase": "vapor",
        "base": "N2",
        "type": "conversion",
        "conversion": 0.25,
    }
    # the product is a compound of the model, though no feed carries it
    assert "NH3" in {c["id"] for c in t.model["compounds"]}


def test_equilibrium_reactor_takes_the_approach_and_the_equilibrium_constant(tmp_path):
    text = FLOWSHEET.replace(
        "    reactions: [SYN]\n",
        "    reactions: [SYN]\n    reactor: equilibrium\n    approach: 20\n",
    )
    sim = SIMULATION + "    outlet_temperature: {value: 743.15, provenance: assumed}\n"
    t = _translate(_plant(tmp_path, text, sim))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["type"] == "equilibrium_reactor"
    assert unit["spec"]["mode"] == "outlet_temperature"
    assert unit["spec"]["outlet_temperature_K"] == 743.15
    reaction = unit["spec"]["reactions"][0]
    assert reaction["type"] == "equilibrium" and reaction["approach_K"] == 20
    assert reaction["ln_k"].startswith("-10.9563 + 0.0/T")


def test_gibbs_reactor_takes_the_template_components(tmp_path):
    text = FLOWSHEET.replace("    reactions: [SYN]\n", "    reactor: gibbs\n")
    t = _translate(_plant(tmp_path, text))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["type"] == "gibbs_reactor"
    assert unit["spec"]["components"] == ["N2", "H2", "NH3", "AR"]


@pytest.mark.parametrize(
    ("flowsheet", "simulation", "message"),
    [
        (
            FLOWSHEET.replace("    reactions: [SYN]\n", "    reactor: gibbs\n    approach: 5\n"),
            SIMULATION,
            "takes no approach",
        ),
        (
            FLOWSHEET,
            SIMULATION + "    mode: outlet_temperature\n",
            "mode outlet_temperature without outlet_temperature",
        ),
        (
            FLOWSHEET,
            SIMULATION
            + "    mode: adiabatic\n    outlet_temperature: {value: 700, provenance: assumed}\n",
            "outlet_temperature with mode adiabatic",
        ),
    ],
)
def test_reactor_specs_that_do_not_fit_are_refused(tmp_path, flowsheet, simulation, message):
    t = _translate(_plant(tmp_path, flowsheet, simulation))
    assert any(message in m for m in _errors(t)), _errors(t)
    assert t.model is None


def test_two_outlets_are_vapour_and_liquid_by_port(tmp_path):
    text = (
        FLOWSHEET.replace(
            "{id: out, direction: out, delegates: out}]",
            "{id: vapour, direction: out, delegates: out}, {id: liquid, direction: out}]",
        ).replace("from: R1.out", "from: R1.vapour")
        + """  - id: S3
    from: R1.liquid
    to: Q.in
    template: syngas
"""
    ).replace("products:\n", "products:\n  - {id: Q, ports: [{id: in, direction: in}]}\n")
    t = _translate(_plant(tmp_path, text))
    assert not _errors(t), _errors(t)
    unit = _unit(t.model, "R1")
    assert unit["outlets"] == ["S2", "S3"] and unit["roles"] == ["vapor", "liquid"]


def test_without_an_outlet_temperature_the_reactor_is_isothermal(tmp_path):
    text = FLOWSHEET.replace("        temperature: {value: 743.15, provenance: assumed}\n", "")
    text = text.replace('    template: syngas\n    state:\n      design:\n"""', "")
    t = _translate(_plant(tmp_path, text.rsplit("    state:\n      design:\n", 1)[0]))
    assert not _errors(t), _errors(t)
    assert _unit(t.model, "R1")["spec"]["mode"] == "isothermal"


def test_gibbs_reactor_behind_block_ports(tmp_path):
    text = (
        FLOWSHEET.replace("    reactions: [SYN]\n", "    reactor: gibbs\n")
        .replace("to: R1.in", "to: B.in")
        .replace("from: R1.out", "from: B.out")
    )
    t = _translate(_plant(tmp_path, text))
    assert not _errors(t), _errors(t)
    assert _unit(t.model, "R1")["spec"]["components"] == ["N2", "H2", "NH3", "AR"]


def test_a_product_missing_from_materials_is_a_finding(tmp_path):
    ws = _plant(tmp_path)
    (ws.root / "process/reactions.yaml").write_text(
        REACTIONS.replace("{N2: -1, H2: -3, NH3: 2}", "{N2: -1, H2: -3, NH3: 2, XX: 0.5}")
    )
    t = _translate(ws)
    assert any("component XX is not in process/materials.yaml" in m for m in _errors(t))


def test_mode_is_for_reactors_only_and_the_constant_range_is_checked(tmp_path):
    sim = SIMULATION + (
        "  X1:\n    mode: adiabatic\n    outlet_temperature: {value: 523.15, provenance: assumed}\n"
    )
    text = (
        FLOWSHEET.replace(
            "steps:\n",
            "steps:\n  - id: X1\n    block: B\n    class: Cooling\n"
            "    ports: [{id: in, direction: in, delegates: in}, {id: out, direction: out}]\n",
        )
        .replace(
            "{id: in, direction: in, delegates: in}, {id: out, direction: out, delegates: out}]",
            "{id: in, direction: in}, {id: out, direction: out, delegates: out}]",
        )
        .replace("    to: R1.in\n", "    to: X1.in\n", 1)
        + "  - id: S3\n    from: X1.out\n    to: R1.in\n    template: syngas\n"
    )
    t = _translate(_plant(tmp_path, text, sim))
    assert any("mode is for reactors only" in m for m in _errors(t))
    reactions = REACTIONS.replace(
        "{a: -10.9563, provenance: assumed}",
        "{a: -10.9563, temperature_range: [500, 700], provenance: assumed}",
    )
    eq = FLOWSHEET.replace(
        "    reactions: [SYN]\n", "    reactions: [SYN]\n    reactor: equilibrium\n"
    )
    ws = _plant(tmp_path / "range", eq)
    (ws.root / "process/reactions.yaml").write_text(reactions)
    assert any("outside its equilibrium_constant" in m for m in _errors(_translate(ws)))


# -- DWSIM --------------------------------------------------------------------------------------


@dwsim_tests
def test_dwsim_conversion_reactor_matches_propagate(tmp_path):
    ws = _plant(tmp_path)
    process, _ = load_process(ws.root)
    propagate(ws, process, "design", write=True)
    expected = _outlet(ws)["composition"]["values"]
    # simulate fills what propagate left (temperature, pressure) and checks the rest
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=False)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    deviations = [f for f in result.findings if f.rule == "cheme.process-sim-deviation"]
    assert not [f for f in deviations if "composition" in f.message], [
        f.message for f in deviations
    ]
    assert any(line.startswith("R1:") for line in result.lines), result.lines
    assert expected["NH3"] == pytest.approx(2 * 0.25 * 0.2475 / (1 - 2 * 0.25 * 0.2475), rel=1e-4)


@dwsim_tests
def test_dwsim_equilibrium_reactor_with_the_given_constant(tmp_path):
    text = FLOWSHEET.replace(
        "    reactions: [SYN]\n", "    reactions: [SYN]\n    reactor: equilibrium\n"
    )
    sim = SIMULATION + "    outlet_temperature: {value: 743.15, provenance: assumed}\n"
    ws = _plant(
        tmp_path,
        text.replace("value: 743.15, provenance: assumed", "value: 763.15, provenance: assumed"),
        sim,
    )
    process, _ = load_process(ws.root)
    # cheme at 763.15 K with ln K -10.9563 (constant): the same K DWSIM is given at 743.15 K
    propagate(ws, process, "design", write=True)
    ours = _outlet(ws)["composition"]["values"]["NH3"]
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["streams"][1]["state"]["design"].pop("composition")
    data["streams"][1]["state"]["design"]["temperature"]["value"] = 743.15
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    simulated = _outlet(ws)["composition"]["values"]["NH3"]
    # Peng-Robinson at 10 bar against the ideal gas: within 2 % of the ammonia
    assert simulated == pytest.approx(ours, rel=0.02)


@dwsim_tests
def test_dwsim_gibbs_reactor_balances_the_elements(tmp_path):
    text = FLOWSHEET.replace("    reactions: [SYN]\n", "    reactor: gibbs\n")
    sim = SIMULATION + "    outlet_temperature: {value: 743.15, provenance: assumed}\n"
    ws = _plant(tmp_path, text, sim)
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    x = _outlet(ws)["composition"]["values"]
    assert x["NH3"] > 0.01  # 1.7 % at 743 K and 10 bar
    nitrogen = 2 * x["N2"] + x["NH3"]
    hydrogen = 2 * x["H2"] + 3 * x["NH3"]
    assert hydrogen / nitrogen == pytest.approx(3.0, rel=1e-4)  # the feed's H/N


@dwsim_tests
def test_dwsim_parallel_conversions_match_propagate(tmp_path):
    reactions = REACTIONS + (
        "  - id: SYN2\n    stoichiometry: {N2: -1, H2: -3, NH3: 2}\n"
        "    conversion: {key: N2, value: 0.5, provenance: assumed}\n"
    )
    text = FLOWSHEET.replace("reactions: [SYN]", "reactions: [SYN, SYN2]")
    ws = _plant(tmp_path, text)
    (ws.root / "process/reactions.yaml").write_text(reactions)
    process, _ = load_process(ws.root)
    propagate(ws, process, "design", write=True)
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=False)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    deviations = [f.message for f in result.findings if f.rule == "cheme.process-sim-deviation"]
    assert not [m for m in deviations if "composition" in m], deviations
