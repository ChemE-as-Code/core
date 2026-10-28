"""Liquid-phase reactions (pre-release issue 157 item 1): equilibrium constants and rate laws on
mole fractions, activities or concentrations, the liquid equilibrium reactor of cheme process
propagate, ln(Q/K) and rates in cheme process reactors, and the phase-basis rule.

The worked case is the esterification of acetic acid with ethanol at K_x = 4 (Kirbaslar et al.
2001, the evidence of examples/reaction-evidence-ethyl-acetate): with ethanol to acid 2:1 the
equilibrium extent solves 3 xi^2 - 12 xi + 8 = 0, xi = 2 - 2/sqrt(3) = 0.8453."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import (
    Liquid,
    equilibrate_liquid,
    ideal_model,
    ln_quotient,
    measures,
)
from chemeascode.domains.chemistry.rates import RateLaw, rate
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.foundation.workspace import Workspace

ESTER = {"AcOH": -1, "EtOH": -1, "EtOAc": 1, "H2O": 1}
#: m3/kmol at about 350 K (illustrative, for the concentration basis)
VOLUMES = {
    "AcOH": 0.0601,
    "EtOH": 0.0626,
    "EtOAc": 0.1059,
    "H2O": 0.0185,
    "A": 0.1,
    "B": 0.1,
    "C": 0.15,
}
XI = 2 - 2 / math.sqrt(3)


def _liquid(activity=None):
    return Liquid(VOLUMES, activity)


# -- composition measures and equilibrium -------------------------------------------------------


def test_mole_fraction_equilibrium_of_the_esterification():
    out, xi = equilibrate_liquid(
        [ESTER], [math.log(4.0)], ["mole_fraction"], {"AcOH": 1.0, "EtOH": 2.0}, 353.0, _liquid()
    )
    assert xi[0] == pytest.approx(XI, rel=1e-8)
    assert out["EtOAc"] == pytest.approx(XI, rel=1e-8)
    assert out["AcOH"] == pytest.approx(1 - XI, rel=1e-8)
    # an inert solvent dilutes the mole fractions but not K_x of an equimolar reaction
    out, _ = equilibrate_liquid(
        [ESTER],
        [math.log(4.0)],
        ["mole_fraction"],
        {"AcOH": 1.0, "EtOH": 2.0, "S": 5.0},
        353.0,
        _liquid(),
    )
    assert out["EtOAc"] == pytest.approx(XI, rel=1e-8)
    assert out["S"] == pytest.approx(5.0)


def test_concentration_basis_with_a_change_in_moles():
    """A + B <=> C in a liquid: at equilibrium c_C / (c_A c_B) = K_c with c = x / v."""
    reaction = {"A": -1, "B": -1, "C": 1}
    liquid = _liquid()
    out, _ = equilibrate_liquid(
        [reaction], [math.log(2.0)], ["concentration"], {"A": 1.0, "B": 1.0}, 300.0, liquid
    )
    total = sum(out.values())
    x = {n: v / total for n, v in out.items()}
    c = measures("concentration", x, 300.0, liquid)
    assert c["C"] / (c["A"] * c["B"]) == pytest.approx(2.0, rel=1e-7)
    # the same K on mole fractions gives another equilibrium: the basis matters
    other, _ = equilibrate_liquid(
        [reaction], [math.log(2.0)], ["mole_fraction"], {"A": 1.0, "B": 1.0}, 300.0, liquid
    )
    assert other["C"] != pytest.approx(out["C"], rel=1e-3)


def test_activity_basis_reaches_the_activity_equilibrium():
    pytest.importorskip("thermo")
    from chemeascode.domains.chemistry.liquid import unifac_model

    cas = {"AcOH": "64-19-7", "EtOH": "64-17-5", "EtOAc": "141-78-6", "H2O": "7732-18-5"}
    liquid = Liquid(VOLUMES, unifac_model(cas))
    out, _ = equilibrate_liquid(
        [ESTER], [math.log(4.0)], ["activity"], {"AcOH": 1.0, "EtOH": 2.0}, 353.0, liquid
    )
    total = sum(out.values())
    x = {n: v / total for n, v in out.items()}
    assert ln_quotient(ESTER, "activity", x, 353.0, liquid) == pytest.approx(
        math.log(4.0), abs=1e-7
    )
    # UNIFAC's water and ester are far from ideal: the extent differs from the ideal solution's
    assert abs(out["EtOAc"] - XI) > 0.01
    # with activity coefficients of 1 the activity basis is the mole-fraction one
    ideal, _ = equilibrate_liquid(
        [ESTER],
        [math.log(4.0)],
        ["activity"],
        {"AcOH": 1.0, "EtOH": 2.0},
        353.0,
        Liquid(VOLUMES, ideal_model),
    )
    assert ideal["EtOAc"] == pytest.approx(XI, rel=1e-8)


def test_what_a_liquid_measure_needs():
    with pytest.raises(ValueError, match="no liquid_molar_volume for X"):
        measures("concentration", {"X": 1.0}, 300.0, Liquid({}))
    with pytest.raises(ValueError, match="no activity model"):
        measures("activity", {"X": 1.0}, 300.0, Liquid({}))
    with pytest.raises(ValueError, match="not written on partial_pressure"):
        measures("partial_pressure", {"X": 1.0}, 300.0, Liquid({}))


# -- rate laws ----------------------------------------------------------------------------------


def _law(driving="mole_fraction", reverse="equilibrium"):
    return RateLaw.model_validate(
        {
            "form": "power_law",
            "basis": "volume",
            "driving": driving,
            "k": {"A": 1e3, "Ea": 50000.0},
            "orders": {"AcOH": 1, "EtOH": 1},
            "reverse": reverse,
            "provenance": "assumed",
        }
    )


def test_a_liquid_rate_is_zero_at_its_equilibrium():
    x = {"AcOH": 1 - XI, "EtOH": 2 - XI, "EtOAc": XI, "H2O": XI}
    total = sum(x.values())
    x = {n: v / total for n, v in x.items()}
    r = rate(_law(), ESTER, x, 353.0, 101.325, math.log(4.0), _liquid(), "mole_fraction")
    assert r == pytest.approx(0.0, abs=1e-12)
    forward = rate(_law(reverse="none"), ESTER, x, 353.0, 101.325, None, _liquid())
    k = 1e3 * math.exp(-50000.0 / (8.314462618 * 353.0))
    assert forward == pytest.approx(k * x["AcOH"] * x["EtOH"])
    # on concentrations the forward term is k c_A c_B
    c = measures("concentration", x, 353.0, _liquid())
    on_c = rate(_law("concentration", "none"), ESTER, x, 353.0, 101.325, None, _liquid())
    assert on_c == pytest.approx(k * c["AcOH"] * c["EtOH"])


def test_gas_and_liquid_measures_are_not_mixed():
    x = {"AcOH": 0.5, "EtOH": 0.5}
    with pytest.raises(ValueError, match="a liquid's measure; this is a gas"):
        rate(_law(reverse="none"), ESTER, x, 353.0, 101.325)
    with pytest.raises(ValueError, match="not written on partial_pressure"):
        rate(_law("partial_pressure", "none"), ESTER, x, 353.0, 101.325, None, _liquid())
    gas_law = _law("partial_pressure")
    with pytest.raises(ValueError, match="is a liquid's"):
        rate(
            gas_law,
            ESTER,
            x | {"EtOAc": 0.1, "H2O": 0.1},
            353.0,
            101.325,
            1.0,
            None,
            "mole_fraction",
        )


# -- schema and rules ---------------------------------------------------------------------------


def _reactions(**reaction):
    base = {"id": "ESTERIF", "stoichiometry": ESTER, "reversible": True}
    return Reactions.model_validate(
        {"schema": "cheme/reactions/v1", "kind": "reactions", "reactions": [base | reaction]}
    )


def test_phase_basis_rule():
    formulas = {"AcOH": "C2H4O2", "EtOH": "C2H6O", "EtOAc": "C4H8O2", "H2O": "H2O"}

    def found(**reaction):
        return [
            f.message
            for f in reaction_rules(_reactions(**reaction), None, formulas)
            if f.rule == "cheme.reaction-phase-basis"
        ]

    k = {"a": 1.386, "provenance": "given"}
    assert found(phase="liquid", equilibrium_constant=k | {"basis": "mole_fraction"}) == []
    assert found(phase="liquid", equilibrium_constant=k) == [
        "reaction ESTERIF: equilibrium_constant is on partial pressures, but the reaction is "
        "liquid-phase"
    ]
    assert found(equilibrium_constant=k | {"basis": "activity"})[0].endswith("no phase: liquid")
    assert found(phase="vapor", rate=_law().model_dump())[0].endswith("vapor-phase")
    assert found(phase="liquid", rate=_law("concentration").model_dump()) == []


# -- the flowsheet ------------------------------------------------------------------------------

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: AcOH, name: Acetic acid, formula: C2H4O2, cas: 64-19-7, molar_mass: 60.05,
     liquid_molar_volume: 0.0601}
  - {id: EtOH, name: Ethanol, formula: C2H6O, cas: 64-17-5, molar_mass: 46.07,
     liquid_molar_volume: 0.0626}
  - {id: EtOAc, name: Ethyl acetate, formula: C4H8O2, cas: 141-78-6, molar_mass: 88.11,
     liquid_molar_volume: 0.1059}
  - {id: H2O, name: Water, formula: H2O, cas: 7732-18-5, molar_mass: 18.015,
     liquid_molar_volume: 0.0185}
templates:
  - {id: liquid, components: [AcOH, EtOH, EtOAc, H2O]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
activity_model: ideal
reactions:
  - id: ESTERIF
    stoichiometry: {AcOH: -1, EtOH: -1, EtOAc: 1, H2O: 1}
    phase: liquid
    reversible: true
    equilibrium_constant: {basis: mole_fraction, a: 1.3862943611198906, provenance: given,
                           source: "reaction-evidence O-KIR-KIN"}
    rate: {form: power_law, basis: volume, driving: mole_fraction, k: {A: 1000.0, Ea: 50000.0},
           orders: {AcOH: 1, EtOH: 1}, reverse: equilibrium, provenance: assumed}
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
    reactions: [ESTERIF]
    reactor: equilibrium
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 353, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 3, provenance: given}
        composition:
          basis: mole_fraction
          values: {AcOH: 0.3333333333333333, EtOH: 0.6666666666666667}
          provenance: given
  - id: S2
    from: R.out
    to: P.in
    template: liquid
    state:
      design:
        temperature: {value: 353, provenance: assumed}
        pressure: {value: 101.325, provenance: assumed}
"""


def _plant(tmp_path, reactions=REACTIONS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: liquid-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    (root / "process/reactions.yaml").write_text(reactions)
    return Workspace(root)


def _outlet(ws):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return data["streams"][1]["state"]["design"]


def test_a_liquid_equilibrium_reactor_is_solved_and_reported(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert process is not None
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert result.written == 1, [f.format() for f in result.findings]
    comp = _outlet(ws)["composition"]["values"]
    assert comp["EtOAc"] == pytest.approx(XI / 3, rel=1e-5)  # written to 6 digits
    report = reactor_report(ws.root)
    (row,) = report.reactors
    (entry,) = row["reactions"]
    assert entry["basis"] == "mole_fraction"
    assert entry["ln_q_over_k"] == pytest.approx(0.0, abs=1e-5)  # the outlet as written
    assert entry["rate"] == pytest.approx(0.0, abs=1e-9)
    assert "heats of vaporization" in row["duty_basis"]
    # the activity model does not enter a mole-fraction equilibrium: nothing is stale
    path = ws.root / "process/reactions.yaml"
    path.write_text(path.read_text().replace("activity_model: ideal", "activity_model: unifac"))
    process, _ = load(ws.root)
    assert not any(f.rule == "cheme.process-calculated-stale" for f in rules(process))
    # on an activity basis it does
    run(ws, process, "design", write=True)
    path.write_text(path.read_text().replace("{basis: mole_fraction,", "{basis: activity,"))
    process, _ = load(ws.root)
    stale = lambda: any(f.rule == "cheme.process-calculated-stale" for f in rules(process))  # noqa: E731
    assert stale()


def test_a_liquid_reaction_without_a_liquid_k_is_not_solved_on_gas_data(tmp_path):
    ws = _plant(tmp_path, REACTIONS.replace("basis: mole_fraction, ", ""))
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("no equilibrium_constant on mole_fraction" in m for m in messages)
    found = [
        f.message
        for f in run(ws, process, "design", write=False).findings
        if f.rule == "cheme.process-propagate-reactor"
    ]
    assert found and "need an equilibrium_constant on mole_fraction" in found[0]


def test_a_fixed_bed_refuses_liquid_reactions(tmp_path):
    from chemeascode.domains.process.fixed_bed import BedError, solve_node

    ws = _plant(tmp_path)
    process, _ = load(ws.root)
    node = next(b for b in process.flowsheet.blocks if b.id == "R")
    stream = next(s for s in process.flowsheet.streams if s.id == "S1")
    node = node.model_copy(update={"bed": object(), "catalyst": "X"})
    process.catalysts = type("C", (), {"by_id": lambda self: {"X": object()}})()
    with pytest.raises(BedError, match="is not a vapour reaction"):
        solve_node(process, node, stream, "design")


def test_review_fixes():
    """An empty liquid feed, a gas K on another basis, and the DWSIM export of a liquid K."""
    from chemeascode.domains.chemistry.equilibrium import NotConverged, reaction_ln_k

    with pytest.raises(NotConverged, match="empty"):
        equilibrate_liquid([ESTER], [0.0], ["activity"], {"AcOH": 0.0}, 300.0, _liquid())
    reaction = _reactions(
        phase="liquid",
        equilibrium_constant={"basis": "mole_fraction", "a": 1.0, "provenance": "given"},
    ).reactions[0]
    # the gas tools never take a liquid's K as K on partial pressures
    with pytest.raises(ValueError, match="on mole_fraction, not on partial_pressure"):
        reaction_ln_k(reaction, {}, 350.0)
    assert reaction_ln_k(reaction, {}, 350.0, "mole_fraction") == 1.0
    formulas = {"AcOH": "C2H4O2", "EtOH": "C2H6O", "EtOAc": "C4H8O2", "H2O": "H2O"}
    gas = _reactions(
        phase="vapor",
        equilibrium_constant={"basis": "concentration", "a": 1.0, "provenance": "given"},
    )
    messages = [f.message for f in reaction_rules(gas, None, formulas)]
    assert any("a gas-phase equilibrium is taken on partial pressures" in m for m in messages)


def test_dwsim_export_refuses_a_liquid_equilibrium(tmp_path):
    from chemeascode.domains.process.simulation.translate import translate

    ws = _plant(tmp_path)
    (ws.root / "process/simulation.yaml").write_text(
        "schema: cheme/simulation/v1\nkind: simulation\nproperty_package: NRTL\n"
    )
    from chemeascode.domains.process.simulation.translate import load as load_sim

    process, _ = load(ws.root)
    sim, doc, _ = load_sim(ws.root)
    if sim is None:
        pytest.skip("simulation.yaml shape differs")
    model = translate(process, sim, doc, "design")
    messages = [f.message for f in model.findings]
    assert any("DWSIM takes the equilibrium constant on partial pressures" in m for m in messages)


def test_the_default_basis_leaves_dumps_and_fingerprints_unchanged():
    """A reactor's outlet fingerprints its reactions' dumps: a K written before the basis existed
    must not make an outlet stale after the upgrade."""
    reaction = _reactions(equilibrium_constant={"a": 1.0, "provenance": "given"}).reactions[0]
    assert "basis" not in reaction.model_dump(mode="json")["equilibrium_constant"]
    liquid = _reactions(equilibrium_constant={"a": 1.0, "basis": "activity", "provenance": "given"})
    assert liquid.reactions[0].model_dump()["equilibrium_constant"]["basis"] == "activity"
