"""Stirred tanks and batches: textbook cases of the CSTR (in series)
and the batch, isothermal and adiabatic, liquid and gas, and their place in cheme process propagate,
cheme validate and cheme process reactors."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.thermochemistry import IdealGas
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.schema import Batch, Tank
from chemeascode.domains.process.stirred_tank import TankError, solve_batch, solve_cstr
from chemeascode.foundation.workspace import Workspace

K = 0.002  # 1/s, first order
V = {"A": 0.1, "B": 0.1, "C": 0.2, "S": 0.1}  # m3/kmol: no volume change on reaction


def _reactions(*items):
    return Reactions.model_validate(
        {"schema": "cheme/reactions/v1", "kind": "reactions", "reactions": list(items)}
    ).reactions


def _first_order(k=K, phase="liquid", reverse=False, **extra):
    law = {
        "form": "power_law",
        "basis": "volume",
        "driving": "concentration",
        "k": {"A": k},
        "orders": {"A": 1},
        "provenance": "assumed",
    }
    if reverse:
        law["reverse"] = "equilibrium"
    return {
        "id": "R1",
        "stoichiometry": {"A": -1, "B": 1},
        "phase": phase,
        "reversible": reverse,
        "rate": law,
    } | extra


def _tank(**kw):
    return Tank.model_validate({"provenance": "assumed"} | kw)


def _batch(**kw):
    return Batch.model_validate({"provenance": "assumed"} | kw)


LIQUID = Liquid(V)
FEED = {"A": 3600.0 * 0.01}  # kmol/h: 0.01 kmol/s, Q0 = 0.001 m3/s


# -- CSTR ---------------------------------------------------------------------------------------


def test_first_order_cstr_and_tanks_in_series():
    tau = 500.0
    one = solve_cstr(
        _reactions(_first_order()), FEED, 350.0, 101.325, _tank(residence_time=tau), {}, LIQUID
    )
    x = K * tau / (1 + K * tau)
    assert one.outlet["A"] == pytest.approx(FEED["A"] * (1 - x), rel=1e-9)
    assert one.volume == pytest.approx(tau * 0.001)
    assert one.time == pytest.approx(tau)
    three = solve_cstr(
        _reactions(_first_order()),
        FEED,
        350.0,
        101.325,
        _tank(residence_time=tau / 3, count=3),
        {},
        LIQUID,
    )
    assert three.outlet["A"] == pytest.approx(FEED["A"] / (1 + K * tau / 3) ** 3, rel=1e-9)
    assert len(three.tanks) == 3
    assert three.tanks[-1]["conversion"]["A"] > one.tanks[-1]["conversion"]["A"]


def test_a_gas_cstr_with_a_change_in_moles():
    """A -> 2 B, first order in c_A = y P / (R T): tau k = X (1 + eps X) / (1 - X), eps = 1
    (Fogler, Elements of Chemical Reaction Engineering, the CSTR with variable volume)."""
    reaction = _first_order(phase="vapor") | {"stoichiometry": {"A": -1, "B": 2}}
    tau = 400.0
    result = solve_cstr(_reactions(reaction), FEED, 500.0, 200.0, _tank(residence_time=tau), {})
    x = 1 - result.outlet["A"] / FEED["A"]
    assert tau * K == pytest.approx(x * (1 + x) / (1 - x), rel=1e-8)


def test_adiabatic_liquid_cstr_closes_its_energy_balance():
    reaction = _first_order(heat_of_reaction={"value": -60000.0, "provenance": "assumed"})
    reaction["rate"]["k"] = {"A": 5.0e6, "Ea": 60000.0}
    cp = {"A": 150.0, "B": 150.0, "S": 80.0}
    feed = {"A": 3600 * 0.002, "S": 3600 * 0.008}
    result = solve_cstr(
        _reactions(reaction),
        feed,
        300.0,
        101.325,
        _tank(volume=0.5, heat="adiabatic"),
        {},
        LIQUID,
        cp,
    )
    x = 1 - result.outlet["A"] / feed["A"]
    rise = 60000.0 * x * 0.002 / (0.002 * 150 + 0.008 * 80)
    assert result.temperature == pytest.approx(300.0 + rise, rel=1e-8)
    # the conversion is the rate's at the outlet temperature
    k = 5.0e6 * math.exp(-60000.0 / (8.314462618 * result.temperature))
    tau = 0.5 / (0.01 * 0.1)
    assert x == pytest.approx(k * tau / (1 + k * tau), rel=1e-6)
    assert any("several" in n for n in result.notes)
    with pytest.raises(TankError, match="liquid_heat_capacity"):
        solve_cstr(
            _reactions(reaction),
            feed,
            300.0,
            101.325,
            _tank(volume=0.5, heat="adiabatic"),
            {},
            LIQUID,
            {},
        )


def test_a_rate_per_kg_needs_the_catalyst_loading():
    reaction = _first_order()
    reaction["rate"]["basis"] = "catalyst_mass"
    with pytest.raises(TankError, match="catalyst_loading"):
        solve_cstr(_reactions(reaction), FEED, 350.0, 101.325, _tank(volume=1.0), {}, LIQUID)
    loaded = solve_cstr(
        _reactions(reaction),
        FEED,
        350.0,
        101.325,
        _tank(volume=0.25, catalyst_loading=2.0),
        {},
        LIQUID,
    )
    per_volume = solve_cstr(
        _reactions(_first_order()), FEED, 350.0, 101.325, _tank(volume=0.5), {}, LIQUID
    )
    assert loaded.outlet["A"] == pytest.approx(per_volume.outlet["A"], rel=1e-9)


# -- batch --------------------------------------------------------------------------------------


def test_first_and_second_order_batches():
    result = solve_batch(
        _reactions(_first_order()),
        {"A": 1.0, "S": 1.0},
        350.0,
        101.325,
        _batch(time=600.0),
        {},
        LIQUID,
    )
    assert result.outlet["A"] == pytest.approx(math.exp(-K * 600.0), rel=1e-7)
    assert result.profile[-1][0] == pytest.approx(600.0)
    second = _first_order() | {"stoichiometry": {"A": -2, "C": 1}}
    second["rate"] = second["rate"] | {"orders": {"A": 2}, "k": {"A": 0.01}}
    result = solve_batch(
        _reactions(second), {"A": 1.0, "S": 1.0}, 350.0, 101.325, _batch(time=100.0), {}, LIQUID
    )
    # constant volume (equal molar volumes): -dcA/dt = 2 k cA^2 per extent written with 2 A
    c0 = 1.0 / (2 * 0.1)
    c = result.outlet["A"] / (result.volume or 1.0)
    assert 1 / c - 1 / c0 == pytest.approx(2 * 0.01 * 100.0, rel=1e-6)


def test_a_batch_to_a_target_conversion_and_its_equilibrium_limit():
    result = solve_batch(
        _reactions(_first_order()),
        {"A": 1.0},
        350.0,
        101.325,
        _batch(target={"key": "A", "conversion": 0.9}),
        {},
        LIQUID,
    )
    assert result.time == pytest.approx(math.log(10) / K, rel=1e-6)
    reversible = _first_order(
        reverse=True,
        equilibrium_constant={"basis": "mole_fraction", "a": 0.0, "provenance": "assumed"},
    )  # K = 1: X_eq = 0.5
    with pytest.raises(TankError, match="not reached: the batch stops at 0.5"):
        solve_batch(
            _reactions(reversible),
            {"A": 1.0},
            350.0,
            101.325,
            _batch(target={"key": "A", "conversion": 0.6}),
            {},
            LIQUID,
        )


def test_an_adiabatic_batch_heats_up_by_its_heat_of_reaction():
    reaction = _first_order(heat_of_reaction={"value": -80000.0, "provenance": "assumed"})
    reaction["rate"]["k"] = {"A": 2.0e5, "Ea": 50000.0}
    cp = {"A": 160.0, "B": 160.0, "S": 100.0}
    charge = {"A": 1.0, "S": 4.0}
    result = solve_batch(
        _reactions(reaction),
        charge,
        300.0,
        101.325,
        _batch(time=7200.0, heat="adiabatic"),
        {},
        LIQUID,
        cp,
    )
    x = 1 - result.outlet["A"]
    assert result.temperature == pytest.approx(300.0 + 80000.0 * x / (160.0 + 400.0), rel=1e-6)
    assert result.heat_released == pytest.approx(80000.0 * x / 5.0, rel=1e-5)
    assert result.peak_heat_rate and result.peak_heat_rate > 0
    temperatures = [p[1] for p in result.profile]
    assert temperatures == sorted(temperatures)


def test_a_gas_batch_keeps_its_volume():
    reaction = _first_order(phase="vapor") | {"stoichiometry": {"A": -1, "B": 2}}
    result = solve_batch(_reactions(reaction), {"A": 1.0}, 500.0, 200.0, _batch(time=300.0), {})
    assert result.outlet["A"] == pytest.approx(math.exp(-K * 300.0), rel=1e-7)
    moles = sum(result.outlet.values())
    assert result.pressure == pytest.approx(200.0 * moles, rel=1e-7)


def test_tanks_refuse_what_they_cannot_solve():
    gas, liquid = _first_order(phase="vapor"), _first_order() | {"id": "R2"}
    with pytest.raises(TankError, match="not both"):
        solve_cstr(_reactions(gas, liquid), FEED, 350.0, 101.325, _tank(volume=1.0), {}, LIQUID)
    without = {"id": "R1", "stoichiometry": {"A": -1, "B": 1}}
    with pytest.raises(TankError, match="no rate law"):
        solve_cstr(_reactions(without), FEED, 350.0, 101.325, _tank(volume=1.0), {}, LIQUID)
    with pytest.raises(ValueError, match="volume or residence_time"):
        _tank(volume=1.0, residence_time=2.0)
    with pytest.raises(ValueError, match="time or target"):
        _batch()


# -- the flowsheet ------------------------------------------------------------------------------

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
templates:
  - {id: liquid, components: [A, B]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},
            orders: {A: 1}, provenance: assumed}}
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
    reactions: [R1]
    reactor: cstr
    tank: {residence_time: 500, count: 2, provenance: assumed}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 350, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 36, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: liquid
"""


def _plant(tmp_path, flowsheet=FLOWSHEET):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: tank-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    return Workspace(root)


def test_propagate_solves_a_cstr_series_and_reports_it(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert result.written >= 1, [f.format() for f in result.findings]
    state = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1]["state"][
        "design"
    ]
    assert state["composition"]["values"]["A"] == pytest.approx(
        1 / (1 + 0.002 * 500) ** 2, rel=1e-5
    )
    assert state["temperature"]["value"] == pytest.approx(350.0)
    (row,) = reactor_report(ws.root).reactors
    assert row["tank"]["kind"] == "cstr" and len(row["tank"]["tanks"]) == 2
    # a longer space time makes the outlet stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("residence_time: 500", "residence_time: 600"))
    process, _ = load(ws.root)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_propagate_solves_a_batch(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace("reactor: cstr", "reactor: batch").replace(
            "tank: {residence_time: 500, count: 2, provenance: assumed}",
            "batch: {time: 600, provenance: assumed}",
        ),
    )
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    state = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"][1]["state"][
        "design"
    ]
    assert state["composition"]["values"]["A"] == pytest.approx(math.exp(-1.2), rel=1e-5)


def test_tank_rules(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace("    tank: {residence_time: 500, count: 2, provenance: assumed}\n", ""),
    )
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("reactor cstr with no tank" in m for m in messages)
    ws = _plant(tmp_path / "b", FLOWSHEET.replace("reactor: cstr", "reactor: equilibrium"))
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("tank is used by reactor: cstr only" in m for m in messages)


def test_ideal_gas_data_for_a_gas_cstr_duty():
    gas = {
        "A": IdealGas(dHf_298=-100000.0, S_298=200.0, cp_R=[4.0]),
        "B": IdealGas(dHf_298=-120000.0, S_298=200.0, cp_R=[4.0]),
    }
    result = solve_cstr(
        _reactions(_first_order(phase="vapor")), FEED, 500.0, 200.0, _tank(volume=1.0), gas
    )
    extent = (FEED["A"] - result.outlet["A"]) / 3600.0
    assert result.duty == pytest.approx(-20000.0 * extent, rel=1e-6)


# -- review fixes -------------------------------------------------------------------------------


def test_an_adiabatic_gas_batch_conserves_internal_energy():
    """A rigid vessel: U(end) = U(start), U = H - R T per kmol (ideal gas)."""
    gas = {
        "A": IdealGas(dHf_298=-100000.0, S_298=200.0, cp_R=[4.0]),
        "B": IdealGas(dHf_298=-80000.0, S_298=200.0, cp_R=[4.0]),
    }
    reaction = _first_order(phase="vapor") | {"stoichiometry": {"A": -1, "B": 2}}
    result = solve_batch(
        _reactions(reaction), {"A": 1.0}, 500.0, 200.0, _batch(time=300.0, heat="adiabatic"), gas
    )
    r = 8.314462618

    def internal(moles, t):
        return sum(n * (gas[c].enthalpy(t) - r * t) for c, n in moles.items())

    assert internal(result.outlet, result.temperature) == pytest.approx(
        internal({"A": 1.0}, 500.0), rel=1e-7
    )
    assert result.temperature > 500.0  # dH = -60000 kJ/kmol of extent: exothermic


def test_a_time_batch_that_stops_converting_is_noted_not_refused():
    reversible = _first_order(
        reverse=True,
        equilibrium_constant={"basis": "mole_fraction", "a": 0.0, "provenance": "assumed"},
    )
    result = solve_batch(
        _reactions(reversible), {"A": 1.0}, 350.0, 101.325, _batch(time=1e6), {}, LIQUID
    )
    assert result.outlet["A"] == pytest.approx(0.5, rel=1e-6)
    assert result.time == pytest.approx(1e6)
    # charged mostly with the product: no target, the batch runs backwards to equilibrium
    back = solve_batch(
        _reactions(reversible),
        {"A": 0.01, "B": 1.0},
        350.0,
        101.325,
        _batch(time=1e6),
        {},
        LIQUID,
    )
    assert back.outlet["A"] == pytest.approx(0.505, rel=1e-6)


def test_an_isothermal_batch_runs_at_its_given_temperature():
    reaction = _first_order()
    reaction["rate"]["k"] = {"A": 2.0e5, "Ea": 50000.0}
    hot = solve_batch(
        _reactions(reaction),
        {"A": 1.0},
        300.0,
        101.325,
        _batch(time=60.0),
        {},
        LIQUID,
        isothermal_at=350.0,
    )
    k = 2.0e5 * math.exp(-50000.0 / (8.314462618 * 350.0))
    assert hot.outlet["A"] == pytest.approx(math.exp(-k * 60.0), rel=1e-6)


def test_tanks_report_problems_instead_of_crashing(tmp_path):
    ws = _plant(
        tmp_path,
        FLOWSHEET.replace("reactor: cstr", "reactor: batch").replace(
            "tank: {residence_time: 500, count: 2, provenance: assumed}",
            "batch: {time: 600, provenance: assumed}",
        ),
    )
    path = ws.root / "process/materials.yaml"
    path.write_text(path.read_text().replace(", liquid_molar_volume: 0.1}", "}"))
    (row,) = reactor_report(ws.root).reactors
    assert row["tank"] is None
    assert any("liquid_molar_volume" in m for m in row["missing"])


def test_more_tank_rules(tmp_path):
    flowsheet = FLOWSHEET.replace("    reactions: [R1]\n", "")
    process, _ = load(_plant(tmp_path, flowsheet).root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("reactor cstr names no reactions" in m for m in messages)
    ws = _plant(
        tmp_path / "b",
        FLOWSHEET.replace(
            "tank: {residence_time: 500, count: 2, provenance: assumed}",
            "tank: {residence_time: 500, heat: adiabatic, provenance: assumed}",
        ),
    )
    process, _ = load(ws.root)
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-reactor"]
    assert any("without heat_of_reaction of R1" in m for m in messages)
    assert any("without liquid_heat_capacity of A, B" in m for m in messages)


# -- model basis -----------------------------------------------------------------------------------

BATCH_FLOWSHEET = FLOWSHEET.replace("reactor: cstr", "reactor: batch").replace(
    "tank: {residence_time: 500, count: 2, provenance: assumed}",
    "batch: {time: 600, provenance: assumed}",
)


@pytest.mark.parametrize("flowsheet", [FLOWSHEET, BATCH_FLOWSHEET], ids=["cstr", "batch"])
def test_a_stirred_tank_is_kinetic_and_unsourced_with_an_assumed_rate_law(tmp_path, flowsheet):
    """A tank's basis is its rate laws, before and after propagate fills its outlet: the
    calculated outlet is not a sourced specification."""
    ws = _plant(tmp_path, flowsheet)
    for solved in (False, True):
        process, _ = load(ws.root)
        (unit,) = model_bases(process)
        assert (unit.basis, unit.predictive, unit.sourced) == ("kinetic", True, False), solved
        assert "rate law of R1 assumed" in unit.detail
        assert unit.assumptions and "ideally mixed" in " ".join(unit.assumptions)
        run(ws, process, "design", write=True)
    path = ws.root / "process/reactions.yaml"
    path.write_text(path.read_text().replace("provenance: assumed", "provenance: given, source: X"))
    process, _ = load(ws.root)
    (unit,) = model_bases(process)
    assert unit.sourced and unit.sources == ["X"]


def test_a_kinetic_reactor_without_reactions_is_not_sourced(tmp_path):
    process, _ = load(_plant(tmp_path, FLOWSHEET.replace("    reactions: [R1]\n", "")).root)
    (unit,) = model_bases(process)
    assert unit.basis == "kinetic" and not unit.sourced and "no reactions" in unit.detail


def test_a_selectivity_reactor_is_a_sourced_conversion(tmp_path):
    spec = "selectivity: {key: A, conversion: 0.5, products: {B: 1.0}, provenance: given, "
    flowsheet = FLOWSHEET.replace("reactor: cstr", "reactor: conversion").replace(
        "tank: {residence_time: 500, count: 2, provenance: assumed}",
        spec + "source: 'Smith 2020'}",
    )
    process, _ = load(_plant(tmp_path, flowsheet).root)
    (unit,) = model_bases(process)
    assert (unit.basis, unit.predictive, unit.sourced) == ("conversion", False, True)
    assert "no conversion" not in unit.detail and unit.sources == ["Smith 2020"]
    flowsheet = flowsheet.replace("provenance: given, source: 'Smith 2020'", "provenance: assumed")
    process, _ = load(_plant(tmp_path / "b", flowsheet).root)
    (unit,) = model_bases(process)
    assert not unit.sourced and "selectivity (assumed)" in unit.detail


def test_a_gibbs_reactor_without_ideal_gas_data_is_not_sourced(tmp_path):
    """Before its outlet is calculated, the components come from its streams' templates and the
    feed's composition."""
    flowsheet = (
        FLOWSHEET.replace("reactor: cstr", "reactor: gibbs")
        .replace("    reactions: [R1]\n", "")
        .replace("    tank: {residence_time: 500, count: 2, provenance: assumed}\n", "")
    )
    process, _ = load(_plant(tmp_path, flowsheet).root)
    (unit,) = model_bases(process)
    assert (unit.basis, unit.predictive, unit.sourced) == ("equilibrium", True, False)
    assert "no ideal-gas data for A, B" in unit.detail
    # nothing known about its streams at all: still no data, never sourced
    bare = flowsheet.replace("    template: liquid\n", "").replace(
        "        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}\n", ""
    )
    process, _ = load(_plant(tmp_path / "b", bare).root)
    (unit,) = model_bases(process)
    assert not unit.sourced and "no ideal-gas data" in unit.detail
