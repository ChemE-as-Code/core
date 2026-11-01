"""Selectivity as a design input: a conversion reactor given by the
key's per-pass conversion and the molar selectivities to its products; the extents of parallel and
series reactions follow."""

import pytest
import yaml

from chemeascode.domains.chemistry.reactions import Reactions, selectivity_extents
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.foundation.workspace import Workspace


def _reactions(*stoichiometries):
    items = [{"id": f"R{i + 1}", "stoichiometry": s} for i, s in enumerate(stoichiometries)]
    return Reactions.model_validate(
        {"schema": "cheme/reactions/v1", "kind": "reactions", "reactions": items}
    ).reactions


PARALLEL = _reactions({"A": -1, "B": 1}, {"A": -1, "C": 1})
SERIES = _reactions({"A": -1, "B": 1}, {"B": -1, "C": 1})


def test_parallel_and_series_reactions():
    found = selectivity_extents(PARALLEL, "A", 0.8, {"B": 0.9, "C": 0.1}, {"A": 100.0})
    assert found == pytest.approx({"R1": 72.0, "R2": 8.0})
    found = selectivity_extents(SERIES, "A", 0.8, {"B": 0.7, "C": 0.3}, {"A": 100.0})
    assert found == pytest.approx({"R1": 80.0, "R2": 24.0})
    # one selectivity is enough for two parallel reactions: the key's balance gives the other
    assert selectivity_extents(PARALLEL, "A", 0.8, {"B": 0.9}, {"A": 100.0}) == pytest.approx(
        {"R1": 72.0, "R2": 8.0}
    )
    # coefficients count: 2 A -> B forms at most 0.5 kmol B per kmol A converted
    dimer = _reactions({"A": -2, "B": 1})
    assert selectivity_extents(dimer, "A", 0.5, {"B": 0.5}, {"A": 10.0}) == {"R1": 2.5}


def test_selectivities_that_do_not_fit_the_reactions():
    three = _reactions({"A": -1, "B": 1}, {"A": -1, "C": 1}, {"B": -1, "C": 1})
    with pytest.raises(ValueError, match="do not determine the extent of"):
        selectivity_extents(three, "A", 0.8, {"B": 0.5}, {"A": 100.0})
    with pytest.raises(ValueError, match="cannot give these selectivities"):
        selectivity_extents(_reactions({"A": -1, "B": 1}), "A", 0.8, {"B": 0.5}, {"A": 1.0})
    with pytest.raises(ValueError, match="no A in the feed"):
        selectivity_extents(PARALLEL, "A", 0.8, {"B": 1.0}, {"B": 1.0})


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05}
  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05}
templates:
  - {id: mix, components: [A, B, C]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}}
  - {id: R2, stoichiometry: {B: -1, C: 1}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1, R2]
    selectivity: {key: A, conversion: 0.8, products: {B: 0.7, C: 0.3}, provenance: given,
                  source: "reaction-evidence O1"}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: mix
    state:
      design:
        flow: {value: 100, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: mix
"""


def _plant(tmp_path, flowsheet=FLOWSHEET):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: selectivity-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    return Workspace(root)


def test_propagate_solves_a_selectivity_reactor(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert result.written >= 1, [f.format() for f in result.findings]
    values = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1][
        "state"
    ]["design"]["composition"]["values"]
    assert values == pytest.approx({"A": 0.2, "B": 0.56, "C": 0.24})
    # the balance check of validate accepts the outlet
    process, _ = load(ws.root)
    assert not [f.format() for f in rules(process) if f.level == "error"]
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("conversion: 0.8", "conversion: 0.85"))
    process, _ = load(ws.root)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_selectivity_rules(tmp_path):
    flowsheet = FLOWSHEET.replace("products: {B: 0.7, C: 0.3}", "products: {B: 0.7, D: 0.3}")
    flowsheet = flowsheet.replace("key: A,", "key: C,")
    ws = _plant(
        tmp_path,
        flowsheet.replace(
            "    reactions: [R1, R2]\n", "    reactions: [R1, R2]\n    reactor: equilibrium\n"
        ),
    )
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("selectivity is for a conversion reactor, not equilibrium" in m for m in messages)
    assert any("the key C is a reactant of none of its reactions" in m for m in messages)
    assert any("D is formed by none of its reactions" in m for m in messages)


def test_an_irreversible_reaction_is_not_run_backwards():
    with pytest.raises(ValueError, match="R2 to run backwards"):
        selectivity_extents(PARALLEL, "A", 0.8, {"B": 1.1}, {"A": 100.0, "C": 50.0})


def test_validate_checks_the_selectivities_and_their_company(tmp_path):
    # one selectivity too few for three reactions: found by validate, not only by propagate
    reactions = REACTIONS + "  - {id: R3, stoichiometry: {A: -1, C: 1}}\n"
    flowsheet = FLOWSHEET.replace("reactions: [R1, R2]", "reactions: [R1, R2, R3]").replace(
        "products: {B: 0.7, C: 0.3}", "products: {B: 0.7}"
    )
    ws = _plant(tmp_path, flowsheet)
    (ws.root / "process/reactions.yaml").write_text(reactions)
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("do not determine the extent of" in m for m in messages)
    # a conversion in reactions.yaml next to the step's selectivity
    ws = _plant(tmp_path / "b")
    (ws.root / "process/reactions.yaml").write_text(
        REACTIONS.replace(
            "{id: R2, stoichiometry: {B: -1, C: 1}}",
            "{id: R2, stoichiometry: {B: -1, C: 1}, conversion: {key: B, value: 0.3, "
            "provenance: assumed}}",
        )
    )
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("not both (reactions.yaml gives one for R2)" in m for m in messages)


def test_dwsim_asks_for_conversions(tmp_path):
    from chemeascode.domains.process.simulation.translate import load as load_sim
    from chemeascode.domains.process.simulation.translate import translate

    ws = _plant(tmp_path)
    (ws.root / "process/simulation.yaml").write_text(
        "schema: cheme/simulation/v1\nkind: simulation\nproperty_package: Peng-Robinson\n"
    )
    process, _ = load(ws.root)
    sim, doc, _ = load_sim(ws.root)
    model = translate(process, sim, doc, "design")
    assert any("this step gives a selectivity" in f.message for f in model.findings)
