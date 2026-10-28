"""Reactions as code: process/reactions.yaml, element balances, reactive balances and the
conversion reactor of cheme process propagate."""

import shutil
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.chemistry.reactions import (
    Reaction,
    Reactions,
    convert,
    fit_extents,
    molar_mass,
    parse_formula,
)
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.domains.process.model import balance_of, load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, formula: N2, molar_mass: 28.014}
  - {id: H2, name: Hydrogen, formula: H2, molar_mass: 2.016}
  - {id: NH3, name: Ammonia, formula: NH3, molar_mass: 17.031}
  - {id: N2H4, name: Hydrazine, formula: N2H4, molar_mass: 32.045}
templates:
  - {id: gas, components: [N2, H2, NH3, N2H4]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: SYN
    stoichiometry: {N2: -1, H2: -3, NH3: 2}
    conversion: {key: N2, value: 0.2, provenance: assumed}
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
  - {id: B, class: ReactingChemicals, ports: [{id: in, direction: in}, {id: out, direction: out}]}
steps:
  - id: R
    block: B
    class: ReactingChemicals
    reactions: [SYN]
    ports: [{id: in, direction: in, delegates: in}, {id: out, direction: out, delegates: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: gas
    state:
      design:
        flow: {value: 100, provenance: given}
        composition: {basis: mole_fraction, values: {N2: 0.25, H2: 0.75}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: gas
    state:
      design:
        flow: {value: 90, provenance: assumed}
        composition:
          basis: mole_fraction
          values: {N2: 0.2222222, H2: 0.6666667, NH3: 0.1111111}
          provenance: assumed
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, reactions=REACTIONS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: reactions-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    if reactions is not None:
        (root / "process/reactions.yaml").write_text(reactions)
    return Workspace(root)


def _rules(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def _errors(ws):
    return [f for f in _rules(ws) if f.level == "error"]


def _reaction(**kw):
    return Reaction.model_validate({"id": "R", **kw})


# -- chemistry ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("formula", "atoms"),
    [
        ("C2H6O", {"C": 2, "H": 6, "O": 1}),
        ("Ca(OH)2", {"Ca": 1, "O": 2, "H": 2}),
        ("Ar", {"Ar": 1}),
        ("CH3COOH", {"C": 2, "H": 4, "O": 2}),
        ("Xy2", None),
        ("H3O+", None),
        ("(OH", None),
        ("", None),
    ],
)
def test_parse_formula(formula, atoms):
    assert parse_formula(formula) == atoms


def test_molar_mass_from_formula():
    assert molar_mass("NH3") == pytest.approx(17.031, abs=1e-3)


def test_reaction_needs_both_sides_and_no_zero():
    with pytest.raises(ValueError, match="reactants"):
        _reaction(stoichiometry={"N2": -1, "H2": -3})
    with pytest.raises(ValueError, match="is 0"):
        _reaction(stoichiometry={"N2": -1, "H2": 0, "NH3": 2})


def test_reaction_rules():
    formulas = {"N2": "N2", "H2": "H2", "NH3": "NH3", "X": ""}
    reactions = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {"id": "OK", "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2}},
                {"id": "BAD", "stoichiometry": {"N2": -1, "H2": -2, "NH3": 2}},
                {"id": "UNK", "stoichiometry": {"N2": -1, "Y": 1}},
                {"id": "NOF", "stoichiometry": {"N2": -1, "X": 1}},
                {
                    "id": "KEY",
                    "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2},
                    "conversion": {"key": "NH3", "value": 0.5, "provenance": "assumed"},
                },
                {"id": "OK", "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2}},
            ],
        }
    )
    found = {(f.rule, f.ids[0]) for f in reaction_rules(reactions, None, formulas)}
    assert found == {
        ("cheme.reaction-element-balance", "BAD"),
        ("cheme.reaction-component", "UNK"),
        ("cheme.reaction-element-balance-not-evaluable", "NOF"),
        ("cheme.reaction-conversion", "KEY"),
        ("cheme.reaction-duplicate-id", "OK"),
    }
    bad = next(f for f in reaction_rules(reactions, None, formulas) if f.ids == ["BAD"])
    assert "H +2" in bad.message


def test_fit_extents_recovers_independent_reactions():
    smr = _reaction(id="SMR", stoichiometry={"CH4": -1, "H2O": -1, "CO": 1, "H2": 3})
    wgs = _reaction(id="WGS", stoichiometry={"CO": -1, "H2O": -1, "CO2": 1, "H2": 1})
    change = {"CH4": -10, "H2O": -14, "CO": 6, "CO2": 4, "H2": 34}
    extents, residual = fit_extents([smr, wgs], change)
    assert extents == pytest.approx({"SMR": 10, "WGS": 4})
    assert max(abs(v) for v in residual.values()) < 1e-9
    # a linear combination of the two adds nothing: extent 0, still explained
    overall = _reaction(id="ALL", stoichiometry={"CH4": -1, "H2O": -2, "CO2": 1, "H2": 4})
    extents, residual = fit_extents([smr, wgs, overall], change)
    assert extents["ALL"] == 0
    assert max(abs(v) for v in residual.values()) < 1e-9


def test_convert_simultaneous_on_inlet_and_refuses_overconsumption():
    syn = _reaction(
        id="SYN",
        stoichiometry={"N2": -1, "H2": -3, "NH3": 2},
        conversion={"key": "N2", "value": 0.1, "provenance": "assumed"},
    )
    out, extents = convert([syn], {"SYN": 0.25}, {"N2": 100, "H2": 300})
    assert out == pytest.approx({"N2": 75, "H2": 225, "NH3": 50})
    assert extents == {"SYN": 25}
    with pytest.raises(ValueError, match="H2"):
        convert([syn], {"SYN": 0.5}, {"N2": 100, "H2": 100})


# -- flowsheet balances -------------------------------------------------------------------------


def test_reactor_step_balances_reactively(tmp_path):
    ws = _plant(tmp_path)
    assert not _errors(ws), [f.format() for f in _errors(ws)]
    process, _ = load(ws.root)
    for node in ("R", "B"):  # the block holds the reactor: reactive too
        result = balance_of(process, node, "design")
        assert result.status == "ok", result.failing
        assert result.extents["SYN"] == pytest.approx(5, rel=1e-5)
        assert result.entry()["extents_kmol_h"]["SYN"] == pytest.approx(5, rel=1e-5)


def test_without_reactions_the_reactor_is_a_component_imbalance(tmp_path):
    ws = _plant(tmp_path, FLOWSHEET.replace("    reactions: [SYN]\n", ""))
    found = [f for f in _errors(ws) if f.rule == "cheme.process-balance"]
    assert {f.ids[0] for f in found} == {"R", "B"}
    assert "NH3" in found[0].message


def test_element_imbalance(tmp_path):
    ws = _plant(tmp_path, FLOWSHEET.replace("NH3: 0.1111111}", "NH3: 0.0555556, N2H4: 0.0555556}"))
    found = [f for f in _errors(ws) if f.rule == "cheme.process-balance"]
    assert found and "element H" in found[0].message


def test_change_not_explained_by_the_reactions(tmp_path):
    # 10 kmol/h NH3 -> 5 N2H4 + 5 H2: elements balance, the declared reaction does not explain it
    text = FLOWSHEET.replace(
        "{N2: 0.2222222, H2: 0.6666667, NH3: 0.1111111}",
        "{N2: 0.2222222, H2: 0.7222222, N2H4: 0.0555556}",
    )
    ws = _plant(tmp_path, text)
    found = [f for f in _errors(ws) if f.rule == "cheme.process-balance"]
    assert found
    assert "element" not in found[0].message
    assert "not explained by reactions SYN" in found[0].message


def test_reactive_scope_without_reactions_checks_elements(tmp_path):
    text = FLOWSHEET.replace("    reactions: [SYN]\n", "").replace(
        "  - {id: B, class: ReactingChemicals,",
        "  - {id: B, class: ReactingChemicals, balance_scope: reactive,",
    )
    ws = _plant(tmp_path, text)
    process, _ = load(ws.root)
    assert balance_of(process, "B", "design").status == "ok"
    assert balance_of(process, "R", "design").status == "imbalance"  # a step of its own


def test_unknown_reaction_and_misplaced_conversion(tmp_path):
    text = FLOWSHEET.replace(
        "    reactions: [SYN]\n",
        "    reactions: [SYN, NOPE]\n    conversion: {OTHER: 0.5}\n",
    )
    ws = _plant(tmp_path, text)
    found = {(f.rule, f.ids[1]) for f in _errors(ws) if f.rule == "cheme.process-reaction"}
    assert found == {
        ("cheme.process-reaction", "NOPE"),
        ("cheme.process-reaction", "OTHER"),
    }
    assert all(f.line for f in _errors(ws) if f.rule == "cheme.process-reaction")


def test_missing_reactions_file(tmp_path):
    ws = _plant(tmp_path, reactions=None)
    found = [f for f in _errors(ws) if f.rule == "cheme.process-reaction"]
    assert found and "does not exist" in found[0].message


def test_reactions_schema_error_has_a_line(tmp_path):
    ws = _plant(tmp_path, reactions=REACTIONS.replace("H2: -3,", "H2: 0,"))
    found = [f for f in _rules(ws) if f.rule == "cheme.reaction-schema"]
    assert found and found[0].line == 4 and found[0].file == "process/reactions.yaml"


# -- propagate ----------------------------------------------------------------------------------


def _without_outlet(text):
    head, _, _ = text.partition("    state:\n      design:\n        flow: {value: 90")
    return head


def test_propagate_solves_the_conversion_reactor(tmp_path):
    ws = _plant(tmp_path, _without_outlet(FLOWSHEET))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written == 1
    s2 = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1]
    comp = s2["state"]["design"]["composition"]
    assert comp["source"] == "cheme process propagate: reactor R from S1"
    moles = {"N2": 20, "H2": 60, "NH3": 10}
    assert comp["values"]["NH3"] == pytest.approx(moles["NH3"] / 90, rel=1e-5)
    assert comp["values"]["N2"] == pytest.approx(moles["N2"] / 90, rel=1e-5)
    assert not _errors(ws)
    # the step's own conversion wins over the reaction's, and a change makes the outlet stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "    reactions: [SYN]\n", "    reactions: [SYN]\n    conversion: {SYN: 0.4}\n"
        )
    )
    stale = [f for f in _rules(ws) if f.rule == "cheme.process-calculated-stale"]
    assert stale and stale[0].ids == ["S2"]
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    s2 = yaml.safe_load(path.read_text())["streams"][1]
    assert s2["state"]["design"]["composition"]["values"]["NH3"] == pytest.approx(20 / 80, rel=1e-5)


def test_propagate_reports_overconsumption(tmp_path):
    ws = _plant(
        tmp_path, _without_outlet(FLOWSHEET).replace("{N2: 0.25, H2: 0.75}", "{N2: 0.5, H2: 0.5}")
    )
    process, _ = load(ws.root)
    reactions = REACTIONS.replace("value: 0.2,", "value: 0.9,")
    (ws.root / "process/reactions.yaml").write_text(reactions)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=False)
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "H2" in found[0].message and found[0].level == "warning"


def test_propagate_leaves_a_reactor_without_conversion_unsolved(tmp_path):
    ws = _plant(
        tmp_path,
        _without_outlet(FLOWSHEET),
        REACTIONS.replace("    conversion: {key: N2, value: 0.2, provenance: assumed}\n", ""),
    )
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=False)
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-not-solved"]
    assert [f.ids for f in found] == [["R"]] and "conversion:" in found[0].hint


# -- the ammonia example ------------------------------------------------------------------------


@pytest.fixture
def ammonia(tmp_path):
    shutil.copytree(
        EXAMPLES / "process-ammonia", tmp_path / "nh3", ignore=shutil.ignore_patterns("build")
    )
    return Workspace(tmp_path / "nh3")


def test_ammonia_example_validates_clean_and_is_propagated(ammonia):
    report = validate_workspace(ammonia)
    assert not [f.format() for f in report.findings if f.level != "info"]
    process, _ = load(ammonia.root)
    check = run(ammonia, process, "design", write=False)
    assert not [f.format() for f in check.findings if f.level != "info"]
    assert not [f for f in check.findings if f.rule == "cheme.process-propagate-not-filled"]
    r1 = balance_of(process, "R1", "design")
    loop = balance_of(process, "LOOP", "design")
    # the converter at equilibrium (K at 763.15 K, Peng-Robinson): the loop closed at that extent
    assert r1.extents["NH3_SYN"] == pytest.approx(222.942, rel=1e-4)
    assert loop.extents["NH3_SYN"] == pytest.approx(222.942, rel=1e-4)


# -- review fixes -------------------------------------------------------------------------------


def test_convert_refuses_a_key_that_is_no_reactant():
    absent = _reaction(
        id="R",
        stoichiometry={"A": -1, "B": 1},
        conversion={"key": "C", "value": 0.5, "provenance": "assumed"},
    )
    product = _reaction(
        id="R",
        stoichiometry={"A": -1, "B": 1},
        conversion={"key": "B", "value": 0.3, "provenance": "assumed"},
    )
    for reaction in (absent, product):
        with pytest.raises(ValueError, match="not a reactant"):
            convert([reaction], {"R": 0.5}, {"A": 10, "B": 10})


def test_propagate_with_a_bad_conversion_key_reports_instead_of_crashing(tmp_path):
    ws = _plant(tmp_path, _without_outlet(FLOWSHEET), REACTIONS.replace("key: N2", "key: NH3"))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "not a reactant" in found[0].message
    assert any(f.rule == "cheme.reaction-conversion" for f in _rules(ws))


def test_irreversible_reaction_running_backwards_is_an_imbalance(tmp_path):
    # outlet richer in N2/H2 and poorer in NH3 than the feed: a negative extent
    text = (
        FLOWSHEET.replace("{N2: 0.25, H2: 0.75}", "{N2: 0.2222222, H2: 0.6666667, NH3: 0.1111111}")
        .replace("value: 100, provenance: given", "value: 90, provenance: given")
        .replace(
            "flow: {value: 90, provenance: assumed}", "flow: {value: 100, provenance: assumed}"
        )
        .replace(
            "{N2: 0.2222222, H2: 0.6666667, NH3: 0.1111111}\n          provenance: assumed",
            "{N2: 0.25, H2: 0.75}\n          provenance: assumed",
        )
    )
    ws = _plant(tmp_path, text)
    found = [f for f in _errors(ws) if f.rule == "cheme.process-balance"]
    assert found and "runs backwards" in found[0].message
    reversible = REACTIONS.replace("    stoichiometry:", "    reversible: true\n    stoichiometry:")
    (ws.root / "process/reactions.yaml").write_text(reversible)
    assert not [f for f in _errors(ws) if f.rule == "cheme.process-balance"]


def test_reaction_species_without_molar_mass_makes_the_balance_not_evaluable(tmp_path):
    ws = _plant(tmp_path)
    path = ws.root / "process/materials.yaml"
    text = yaml.safe_load(path.read_text())
    text["components"].append({"id": "X", "name": "By-product", "formula": "N2"})
    text["templates"][0]["components"].append("X")
    path.write_text(yaml.safe_dump(text, sort_keys=False))
    (ws.root / "process/reactions.yaml").write_text(
        REACTIONS + "  - id: SIDE\n    stoichiometry: {N2: -1, X: 1}\n"
    )
    flowsheet = ws.root / "process/flowsheet.yaml"
    flowsheet.write_text(
        flowsheet.read_text().replace("reactions: [SYN]", "reactions: [SYN, SIDE]")
    )
    process, _ = load(ws.root)
    result = balance_of(process, "R", "design")
    assert "molar_mass of X" in result.missing and not result.extents


def test_propagate_reports_a_missing_molar_mass(tmp_path):
    ws = _plant(tmp_path, _without_outlet(FLOWSHEET))
    path = ws.root / "process/materials.yaml"
    path.write_text(path.read_text().replace("formula: NH3, molar_mass: 17.031", "formula: NH3"))
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=False)
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "no molar_mass for NH3" in found[0].message


def test_changed_molar_mass_makes_the_reactor_outlet_stale(tmp_path):
    ws = _plant(tmp_path, _without_outlet(FLOWSHEET))
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    assert not [f for f in _rules(ws) if f.rule == "cheme.process-calculated-stale"]
    path = ws.root / "process/materials.yaml"
    path.write_text(path.read_text().replace("molar_mass: 17.031", "molar_mass: 17.5"))
    stale = [f for f in _rules(ws) if f.rule == "cheme.process-calculated-stale"]
    assert stale and stale[0].ids == ["S2"]
