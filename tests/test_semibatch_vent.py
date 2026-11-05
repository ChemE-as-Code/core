"""Gas evolution and gas dosing in a batch or semi-batch (``batch.vent``, ``dosing.absorbed``;
ADR 0054): the vent's rate against the closed form of a first-order reaction under constant
dosing, the balances of the liquid and the vent, the energy balance of an adiabatic vented
batch, a dosed gas that dissolves or passes through, and the vented step in cheme process
propagate, cheme validate, process reactors, the reaction-hazard screening and the recipe.
An unvented batch or semi-batch fingerprints as in 1.7.0."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.thermochemistry import IdealGas, R
from chemeascode.domains.process.model import balance_of, load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report, reactor_text
from chemeascode.domains.process.recipe import Recipe, evaluate, recipe_text
from chemeascode.domains.process.schema import Batch, Dosing, Vent
from chemeascode.domains.process.stirred_tank import Dose, TankError, solve_batch
from chemeascode.domains.safety.reaction_hazards import screen
from chemeascode.foundation.workspace import Workspace
from tests.test_semibatch import FLOWSHEET as UNVENTED
from tests.test_semibatch import _plant as _unvented_plant

V = {"A": 0.1, "B": 0.1, "S": 0.1}  # m3/kmol: none for the gas G
CP = {"A": 150.0, "B": 150.0, "S": 150.0}  # kJ/(kmol K): none for G
HEAT = -100000.0  # kJ/kmol, forming G as a gas at the vessel's temperature
DOSING = 3600.0  # s
Q = 1.0 / DOSING  # kmol/s of A dosed


def _reactions(k, heat=HEAT):
    return Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1, "G": 1},
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


def _batch(vent=None, **kw):
    spec = {"provenance": "assumed", "dosing": [{"stream": "D", "time": DOSING}]}
    if vent is not False:
        spec["vent"] = vent or {"stream": "V", "components": ["G"]}
    return Batch.model_validate(spec | kw)


def _vented(k, batch=None, doses=None, volumes=V, cp=CP, data=None, t=300.0):
    return solve_batch(
        _reactions(k),
        {"S": 5.0},
        t,
        101.325,
        batch or _batch(),
        data or {},
        Liquid(volumes),
        cp,
        doses=doses or [Dose({"A": 1.0}, t, [(0.0, DOSING, 1.0)])],
    )


@pytest.mark.parametrize("k", [1e-2, 1e-3, 1e-4])
def test_the_vent_rate_is_the_reaction_rate_under_constant_dosing(k):
    """A -> B + G(g), first order in c_A, A dosed at q: n_A = (q/k)(1 - exp(-k t)), and G
    leaves as it forms, at k n_A = q (1 - exp(-k t)): largest when the dosing ends."""
    result = _vented(k)
    left = (1 - math.exp(-k * DOSING)) / (k * DOSING)  # of A, when the dosing ends
    assert result.outlet["A"] == pytest.approx(left, rel=1e-6)
    assert result.outlet["B"] == pytest.approx(1 - left, rel=1e-6)
    # G is not in the liquid: all of what formed left by the vent
    assert result.outlet["G"] == 0.0
    assert result.vent == {"G": pytest.approx(1 - left, rel=1e-6)}
    assert result.peak_vent_time == pytest.approx(DOSING)
    assert result.peak_vent_flow == pytest.approx(Q * (1 - math.exp(-k * DOSING)), rel=1e-6)
    # per m3 of the content at the end: 6 kmol of A, B and S, G not counted
    assert result.volume == pytest.approx(0.6)
    assert result.peak_vent_rate == pytest.approx(result.peak_vent_flow / 0.6, rel=1e-12)
    # the accumulation and the cooling failure are those of the unvented liquid
    assert result.max_accumulation == pytest.approx(left, rel=1e-6)


def test_a_vented_batch_without_dosing():
    """All of A charged: G leaves at k n_A0 exp(-k t), largest at the start."""
    k, time = 1e-3, 1800.0
    result = solve_batch(
        _reactions(k),
        {"S": 5.0, "A": 1.0},
        300.0,
        101.325,
        Batch.model_validate(
            {"time": time, "vent": {"stream": "V", "components": ["G"]}, "provenance": "assumed"}
        ),
        {},
        Liquid(V),
        CP,
    )
    assert result.kind == "batch"
    assert result.vent["G"] == pytest.approx(1 - math.exp(-k * time), rel=1e-6)
    assert result.outlet["G"] == 0.0
    assert result.peak_vent_time == 0.0
    assert result.peak_vent_flow == pytest.approx(k * 1.0, rel=1e-9)


def test_the_two_outlets_close_the_balance_and_a_fraction_stays_dissolved():
    k = 1e-3
    half = _vented(
        k,
        _batch({"stream": "V", "components": ["G"], "fraction": {"G": 0.5}}),
        volumes=V | {"G": 0.05},
        cp=CP | {"G": 60.0},
    )
    extent = half.extents["R1"]
    # what is charged and dosed, and formed, leaves by one outlet or the other
    for name, given in (("A", 1.0), ("B", 0.0), ("S", 5.0), ("G", 0.0)):
        nu = {"A": -1, "B": 1, "G": 1}.get(name, 0)
        assert half.outlet[name] + half.vent.get(name, 0.0) == pytest.approx(
            given + nu * extent, rel=1e-9, abs=1e-12
        )
    assert half.vent["G"] == pytest.approx(0.5 * extent, rel=1e-6)
    assert half.outlet["G"] == pytest.approx(0.5 * extent, rel=1e-6)
    # first order in c_A: the dissolved G does not change the rate, only the volume
    assert extent == pytest.approx(1 - (1 - math.exp(-k * DOSING)) / (k * DOSING), rel=1e-6)
    assert half.volume == pytest.approx(0.6 + 0.05 * 0.5 * extent, rel=1e-6)


def test_an_adiabatic_vented_semibatch_closes_its_energy_balance():
    """The gas leaves at the vessel's temperature with its own enthalpy (heat_of_reaction
    forms it as a gas): C_end T_end = C_charge T_0 + C_dose T_dose + (-dH) extent, C_end over
    the liquid alone (G has no liquid_heat_capacity and needs none)."""
    result = _vented(
        1e-3,
        _batch(heat="adiabatic"),
        doses=[Dose({"A": 1.0}, 290.0, [(0.0, DOSING, 1.0)])],
    )
    extent = result.extents["R1"]
    expected = (5.0 * 150.0 * 300.0 + 1.0 * 150.0 * 290.0 - HEAT * extent) / (6.0 * 150.0)
    assert result.temperature == pytest.approx(expected, rel=1e-7)
    assert result.vent["G"] == pytest.approx(extent, rel=1e-9)


def test_unvented_the_gas_stays_dissolved_and_counts_in_the_liquid():
    """Without the vent G stays in the liquid (it then needs its liquid_molar_volume): first
    order in c_A the conversion is the same, the volume is not."""
    unvented = _vented(1e-3, _batch(False), volumes=V | {"G": 0.05}, cp=CP | {"G": 60.0})
    vented = _vented(1e-3)
    assert unvented.outlet["A"] == pytest.approx(vented.outlet["A"], rel=1e-6)
    assert unvented.outlet["G"] == pytest.approx(vented.vent["G"], rel=1e-6)
    assert unvented.volume == pytest.approx(0.6 + 0.05 * vented.vent["G"], rel=1e-6)
    assert not unvented.vent and unvented.peak_vent_rate is None


def test_a_dosed_gas_partly_absorbed_passes_the_rest_to_the_vent():
    """absorbed 0.8: the liquid takes up 0.8 q, so n_A = 0.8 (q/k)(1 - exp(-k t)); 0.2 of A
    passes straight to the vent, warmed to the vessel's temperature (its ideal-gas cp)."""
    k = 1e-2
    gas = {n: IdealGas(dHf_298=-1e5, S_298=200.0, cp_R=[4.0]) for n in ("A",)}

    def dosed(t_dose):
        return [Dose({"A": 0.8}, t_dose, [(0.0, DOSING, 1.0)], passing={"A": 0.2})]

    warm = _vented(k, doses=dosed(300.0), data=gas)
    left = 0.8 * (1 - math.exp(-k * DOSING)) / (k * DOSING)
    assert warm.outlet["A"] == pytest.approx(left, rel=1e-6)
    assert warm.vent["A"] == pytest.approx(0.2, rel=1e-12)
    assert warm.vent["G"] == pytest.approx(0.8 - left, rel=1e-6)
    peak = 0.8 * Q * (1 - math.exp(-k * DOSING)) + 0.2 * Q
    assert warm.peak_vent_flow == pytest.approx(peak, rel=1e-6)
    # a cold dose: its dissolved share and its passing gas both take up heat
    cold = _vented(k, doses=dosed(280.0), data=gas)
    taken = Q * (0.8 * 150.0 + 0.2 * 4.0 * R) * 20.0 / warm.volume
    assert cold.peak_cooling_duty == pytest.approx(warm.peak_cooling_duty - taken, rel=1e-3)
    # without ideal-gas data the passing gas's sensible heat is left out, and said
    bare = _vented(k, doses=dosed(280.0))
    assert any("passing through is left out" in n for n in bare.notes)
    with pytest.raises(TankError, match="no vent"):
        _vented(k, _batch(False), doses=dosed(300.0))


def _side_reactions(k2):
    """R1 forms G; R2 consumes it (G + S -> C, first order in c_G)."""

    def law(k, order):
        return {
            "form": "power_law",
            "basis": "volume",
            "driving": "concentration",
            "k": {"A": k},
            "orders": {order: 1},
            "provenance": "assumed",
        }

    return Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1, "G": 1},
                    "phase": "liquid",
                    "heat_of_reaction": {"value": HEAT, "provenance": "assumed"},
                    "rate": law(1e-3, "A"),
                },
                {
                    "id": "R2",
                    "stoichiometry": {"G": -1, "S": -1, "C": 1},
                    "phase": "liquid",
                    "heat_of_reaction": {"value": -1e4, "provenance": "assumed"},
                    "rate": law(k2, "G"),
                },
            ],
        }
    ).reactions


@pytest.mark.parametrize("k2", [1e-3, 1e-2])
def test_a_side_reaction_of_the_vented_gas_takes_it_from_the_liquid(k2):
    """The vent takes its share of what R1 forms, not of the net formation: R2 consumes only
    the dissolved rest, never gas that has already left."""
    volumes = dict.fromkeys("ABSCG", 0.1)
    cp = dict.fromkeys("ABSCG", 150.0)
    batch = Batch.model_validate(
        {
            "time": 3600,
            "vent": {"stream": "V", "components": ["G"], "fraction": {"G": 0.5}},
            "provenance": "assumed",
        }
    )
    charge = {"S": 5.0, "A": 1.0}
    result = solve_batch(
        _side_reactions(k2), charge, 300.0, 101.325, batch, {}, Liquid(volumes), cp
    )
    r1, r2 = result.extents["R1"], result.extents["R2"]
    assert r1 == pytest.approx(1 - math.exp(-1e-3 * 3600), rel=1e-6)  # first order in c_A
    assert result.vent["G"] == pytest.approx(0.5 * r1, rel=1e-6)
    assert 0.0 < r2 <= 0.5 * r1 * (1 + 1e-9)
    # closure over both outlets
    nu = {"A": {"R1": -1}, "B": {"R1": 1}, "G": {"R1": 1, "R2": -1}, "S": {"R2": -1}}
    nu["C"] = {"R2": 1}
    extents = {"R1": r1, "R2": r2}
    for name in "ABSCG":
        made = sum(v * extents[j] for j, v in nu[name].items())
        assert result.outlet[name] + result.vent.get(name, 0.0) == pytest.approx(
            charge.get(name, 0.0) + made, rel=1e-9, abs=1e-9
        ), name


def test_a_charged_vent_component_is_drawn_down_by_its_consumer():
    """G vented whole and also charged (a recycled liquor): all of what R1 forms leaves, and R2
    consumes the charged pool, even while R1 forms more than R2 consumes."""
    volumes = dict.fromkeys("ABSCG", 0.1)
    cp = dict.fromkeys("ABSCG", 150.0)
    batch = Batch.model_validate(
        {"time": 3600, "vent": {"stream": "V", "components": ["G"]}, "provenance": "assumed"}
    )
    charge = {"S": 5.0, "A": 1.0, "G": 0.2}
    result = solve_batch(
        _side_reactions(1e-4), charge, 300.0, 101.325, batch, {}, Liquid(volumes), cp
    )
    r1, r2 = result.extents["R1"], result.extents["R2"]
    assert r2 > 0.0
    assert result.vent["G"] == pytest.approx(r1, rel=1e-6)
    assert result.outlet["G"] == pytest.approx(0.2 - r2, rel=1e-6)


def test_the_schema_of_vent_and_absorbed():
    vent = Vent.model_validate({"stream": "V", "components": ["G", "H"], "fraction": {"H": 0.3}})
    assert vent.shares() == {"G": 1.0, "H": 0.3}
    with pytest.raises(ValueError, match="not in components"):
        Vent.model_validate({"stream": "V", "components": ["G"], "fraction": {"H": 0.3}})
    with pytest.raises(ValueError, match="at most 1"):
        Vent.model_validate({"stream": "V", "components": ["G"], "fraction": {"G": 1.5}})
    with pytest.raises(ValueError):
        Dosing.model_validate({"stream": "D", "time": 1, "absorbed": 0})
    # an unvented batch's and dose's dumps (their outlets' fingerprints) are as they were
    assert "vent" not in _batch(False).model_dump()
    assert "absorbed" not in Dosing.model_validate({"stream": "D", "time": 1}).model_dump()


def test_a_gas_batch_cannot_vent():
    gas = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "G": 1},
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
    data = {n: IdealGas(dHf_298=-1e5, S_298=200.0, cp_R=[4.0]) for n in ("A", "G")}
    batch = Batch.model_validate(
        {"time": 60, "vent": {"stream": "V", "components": ["G"]}, "provenance": "assumed"}
    )
    with pytest.raises(TankError, match="liquid-phase"):
        solve_batch(gas, {"A": 1.0}, 300.0, 101.325, batch, data)


# -- in a plant ---------------------------------------------------------------------------------

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
  - {id: B, name: B, formula: C2H4, molar_mass: 28.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
  - {id: S, name: S, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,
     liquid_heat_capacity: 150, normal_boiling_point: 400}
  - {id: G, name: G, formula: O, molar_mass: 16.0, normal_boiling_point: 188}
templates:
  - {id: liquid, components: [A, B, S, G]}
  - {id: gas, components: [G]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1, G: 1}, phase: liquid,
     heat_of_reaction: {value: -100000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.01},
            orders: {A: 1}, provenance: assumed}}
"""

FLOWSHEET = (
    UNVENTED.replace(
        "batch: {dosing: [{stream: S2, time: 3600}], provenance: assumed}",
        "batch: {dosing: [{stream: S2, time: 3600}], vent: {stream: S4, components: [G]}, "
        "provenance: assumed}",
    )
    .replace(
        "hazard: {mtt: 380, td24: 390, provenance: assumed}",
        "hazard: {td24: 390, provenance: assumed}",
    )
    .replace(
        "{id: out, direction: out}]\nstreams:",
        "{id: out, direction: out}, {id: gas, direction: out}]\nstreams:",
    )
    .replace(
        "products:\n",
        "products:\n  - {id: OFFGAS, ports: [{id: in, direction: in}]}\n",
    )
    + "  - id: S4\n    from: R.gas\n    to: OFFGAS.in\n    template: gas\n"
)


def _plant(tmp_path, flowsheet=FLOWSHEET, recipe=None):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: vent-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    if recipe is not None:
        (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe))
    return Workspace(root)


def _messages(ws, level=None):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [
        f.message
        for f in found + rules(process)
        if f.rule == "cheme.process-reactor" and (level is None or f.level == level)
    ]


def _states(ws):
    streams = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    return {s["id"]: s.get("state", {}).get("design", {}) for s in streams}


def test_propagate_writes_the_liquid_and_the_vent_and_the_balance_closes(tmp_path):
    ws = _plant(tmp_path)
    assert not _messages(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 2, [f.format() for f in result.findings]
    states = _states(ws)
    liquid, gas = states["S3"], states["S4"]
    left = (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    formed = 1 - left
    # kmol/h: S 5, A left, B formed in the liquid; G formed in the vent
    assert liquid["flow"]["value"] == pytest.approx(
        5 * 44.05 + left * 44.05 + formed * 28.05, rel=1e-5
    )
    assert "G" not in liquid["composition"]["values"] or not liquid["composition"]["values"]["G"]
    assert gas["flow"]["value"] == pytest.approx(formed * 16.0, rel=1e-5)
    assert gas["composition"]["values"] == {"G": 1.0}
    for name in ("temperature", "pressure"):
        assert gas[name]["value"] == liquid[name]["value"]
        assert gas[name]["provenance"] == "calculated"
    process, _ = load(ws.root)
    balance = balance_of(process, "R", "design")
    assert balance.status == "ok", balance.failing
    assert sorted(balance.streams_out) == ["S3", "S4"]
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert not [f.format() for f in rules(process) if f.level == "error"]
    # the vent and the reactors report
    (row,) = reactor_report(ws.root).reactors
    vent = row["tank"]["vent"]
    assert vent["stream"] == "S4" and vent["kmol_h"]["G"] == pytest.approx(formed, rel=1e-6)
    assert vent["peak_rate_kmol_s_m3"] == pytest.approx(
        Q * (1 - math.exp(-0.01 * DOSING)) / 0.6, rel=1e-6
    )
    assert row["temperature_out_K"] == pytest.approx(300.0)
    assert "vent S4: G" in reactor_text(reactor_report(ws.root))


def test_the_screening_leaves_the_vented_gas_out(tmp_path):
    """G (boiling at 188 K) leaves as it forms: it is not the MTT, nor part of the MTSR."""
    (entry,) = screen(_plant(tmp_path).root).entries
    assert entry.mtt == pytest.approx(400.0) and "G" not in entry.mtt_basis
    assert any("vent S4: G leave(s) as formed" in n and "peak gas rate" in n for n in entry.notes)
    assert entry.accumulation == pytest.approx(0.02778, rel=1e-3)
    assert entry.mtsr < 310.0 and entry.criticality == 2  # MTSR < TD24 (390) < MTT


def test_vent_rules(tmp_path):
    stray = FLOWSHEET.replace("vent: {stream: S4,", "vent: {stream: S9,")
    assert any("vent stream S9 is no outlet" in m for m in _messages(_plant(tmp_path / "a", stray)))
    only = FLOWSHEET.replace("vent: {stream: S4,", "vent: {stream: S3,").replace(
        "  - id: S4\n    from: R.gas\n    to: OFFGAS.in\n    template: gas\n", ""
    )
    assert any("is its only outlet" in m for m in _messages(_plant(tmp_path / "b", only)))
    unknown = FLOWSHEET.replace("components: [G]}", "components: [G, HCl]}")
    assert any("HCl not declared" in m for m in _messages(_plant(tmp_path / "c", unknown)))
    unformed = FLOWSHEET.replace("components: [G]}", "components: [G, S]}")
    warnings = _messages(_plant(tmp_path / "d", unformed), "warning")
    assert any("vent component(s) S formed by none" in m for m in warnings)
    passing = UNVENTED.replace("time: 3600}]", "time: 3600, absorbed: 0.5}]")
    ws = _unvented_plant(tmp_path / "e", passing)
    assert any("pass gas through" in m and "no batch.vent" in m for m in _messages(ws))
    three = FLOWSHEET.replace(
        "{id: gas, direction: out}]", "{id: gas, direction: out}, {id: gas2, direction: out}]"
    ) + ("  - id: S5\n    from: R.gas2\n    to: OFFGAS.in\n    template: gas\n")
    assert any("vent with 3 outlets" in m for m in _messages(_plant(tmp_path / "f", three)))
    # a vented batch on gas-phase reactions: one error, said once
    batch = FLOWSHEET.replace("reactor: semibatch", "reactor: batch").replace(
        "batch: {dosing: [{stream: S2, time: 3600}], ", "batch: {time: 3600, "
    )
    ws = _plant(tmp_path / "g", batch)
    path = ws.root / "process/reactions.yaml"
    path.write_text(REACTIONS.replace("phase: liquid", "phase: vapor"))
    phase = [m for m in _messages(ws, "error") if "not liquid-phase" in m or "is not" in m]
    assert phase == ["block R: a vent takes liquid-phase reactions only: R1 is not"]
    # a semi-batch says so by its own rule only
    ws = _plant(tmp_path / "h")
    (ws.root / "process/reactions.yaml").write_text(
        REACTIONS.replace("phase: liquid", "phase: vapor")
    )
    phase = [m for m in _messages(ws, "error") if "liquid-phase" in m]
    assert phase == ["block R: reactor semibatch with the reaction(s) R1 not liquid-phase"]
    # the vent stream's template holds the vent's components and what a dose passes through
    lacking = MATERIALS.replace("{id: gas, components: [G]}", "{id: gas, components: [A]}")
    ws = _plant(tmp_path / "i")
    (ws.root / "process/materials.yaml").write_text(lacking)
    assert any("vent stream S4's template gas lacks G" in m for m in _messages(ws, "error")), (
        _messages(ws)
    )
    ws = _plant(tmp_path / "j", FLOWSHEET.replace("time: 3600}]", "time: 3600, absorbed: 0.8}]"))
    assert any(
        "template gas lacks A" in m and "the dose S2 passes it through" in m
        for m in _messages(ws, "error")
    )


def test_a_dosed_gas_dissolves_on_entry_like_any_dose(tmp_path):
    """A gas dosed into the liquid (A boiling at 250 K, the vessel at 300 K) needs only its
    liquid_molar_volume and heat capacity: without absorbed it is a dose like any other. Boiling
    below T_p, it is a dissolved gas: the MTT leaves it out (ADR 0058)."""
    ws = _plant(tmp_path)
    path = ws.root / "process/materials.yaml"
    path.write_text(
        path.read_text().replace(
            "normal_boiling_point: 400}\n  - {id: B", "normal_boiling_point: 250}\n  - {id: B", 1
        )
    )
    assert not _messages(ws)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    left = (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    assert _states(ws)["S4"]["flow"]["value"] == pytest.approx((1 - left) * 16.0, rel=1e-5)
    (entry,) = screen(ws.root).entries
    assert entry.mtt == pytest.approx(400.0) and "A" not in entry.mtt_basis
    assert entry.mtt_left_out["A"].startswith("dissolved gas (boils at 250.0 K, below T_p")
    assert "G" not in entry.mtt_left_out  # it forms and leaves: never in the liquid
    assert any(n.startswith("MTT: left out ") and "A (dissolved gas" in n for n in entry.notes)


def test_a_partly_absorbed_gas_dose_in_a_plant(tmp_path):
    flowsheet = FLOWSHEET.replace("time: 3600}]", "time: 3600, absorbed: 0.8}]")
    ws = _plant(tmp_path, flowsheet)
    # the vent carries the passing A: its template holds it
    path = ws.root / "process/materials.yaml"
    path.write_text(
        MATERIALS.replace("{id: gas, components: [G]}", "{id: gas, components: [A, G]}")
    )
    assert not _messages(ws)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    process, found = load(ws.root)
    errors = [f.format() for f in found + rules(process) if f.level == "error"]
    assert not errors, errors
    gas = _states(ws)["S4"]
    left = 0.8 * (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    assert gas["flow"]["value"] == pytest.approx(0.2 * 44.05 + (0.8 - left) * 16.0, rel=1e-5)
    process, _ = load(ws.root)
    assert balance_of(process, "R", "design").status == "ok"
    (entry,) = screen(ws.root).entries
    # the dose counts with its absorbed share in the adiabatic rise: 0.8 kmol of A
    assert entry.adiabatic_rise == pytest.approx(0.8 * 100000.0 / (5.8 * 150.0), rel=1e-6)


def test_vent_components_and_dosed_gases_are_left_out_of_the_mtt(tmp_path):
    """A gas dose (absorbed, 99 % taken up) and a charged vent component (G boiling at 188 K,
    10 % of the charge) do not set the MTT (ADR 0058; until 1.8.0 they did): what else boils
    in the liquid does, and with nothing else left the MTT needs hazard.mtt."""
    low_a = MATERIALS.replace(
        "normal_boiling_point: 400}\n  - {id: B", "normal_boiling_point: 450}\n  - {id: B", 1
    ).replace("{id: gas, components: [G]}", "{id: gas, components: [A, G]}")
    ws = _plant(tmp_path / "a", FLOWSHEET.replace("time: 3600}]", "time: 3600, absorbed: 0.99}]"))
    (ws.root / "process/materials.yaml").write_text(low_a)
    (entry,) = screen(ws.root).entries
    # A (450 K) is a dosed gas: B and S (400 K) set it
    assert entry.mtt == pytest.approx(400.0) and "of A" not in entry.mtt_basis
    assert entry.mtt_left_out == {"A": "dosed gas"}
    charged = FLOWSHEET.replace(
        "composition: {basis: mole_fraction, values: {S: 1.0}",
        "composition: {basis: mole_fraction, values: {S: 0.9, G: 0.1}",
        1,
    )
    assert charged != FLOWSHEET
    ws = _plant(tmp_path / "b", charged)
    (ws.root / "process/materials.yaml").write_text(
        MATERIALS.replace(
            "normal_boiling_point: 188}",
            "normal_boiling_point: 188, liquid_molar_volume: 0.05, liquid_heat_capacity: 50}",
        )
    )
    (entry,) = screen(ws.root).entries
    assert entry.mtt == pytest.approx(400.0) and "of G" not in entry.mtt_basis
    assert entry.mtt_left_out == {"G": "vent component"}
    # nothing else boils: the MTT needs hazard.mtt
    ws = _plant(tmp_path / "c")
    (ws.root / "process/materials.yaml").write_text(
        MATERIALS.replace("normal_boiling_point: 400}", "normal_boiling_point: 290}")
    )
    (entry,) = screen(ws.root).entries
    assert entry.mtt is None
    assert any("the MTT (hazard.mtt): nothing else boils" in m for m in entry.missing)
    assert set(entry.mtt_left_out) == {"A", "S"}  # charged and dosed: B and G form


def test_a_semibatch_says_its_mtsr_includes_its_phase_changes(tmp_path):
    """dT_ad leaves a declared phase change out (ADR 0056), but the semi-batch's cooling-failure
    MTSR is its model's, the phase change's heat included: the screening says so."""
    materials = MATERIALS.replace(
        "templates:",
        "  - {id: B_s, name: B crystals, formula: C2H4, molar_mass: 28.05, phase: solid,\n"
        "     liquid_molar_volume: 0.1, liquid_heat_capacity: 150}\ntemplates:",
    ).replace("components: [A, B, S, G]}", "components: [A, B, S, G, B_s]}")
    entries = {}
    for heat in (0, -200000):
        ws = _plant(
            tmp_path / str(heat), FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, P1]")
        )
        (ws.root / "process/materials.yaml").write_text(materials)
        (ws.root / "process/reactions.yaml").write_text(
            REACTIONS
            + "  - {id: P1, kind: phase-change, stoichiometry: {B: -1, B_s: 1}, phase: liquid,\n"
            f"     heat_of_reaction: {{value: {heat}, provenance: assumed}},\n"
            "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.01},\n"
            "            orders: {B: 1}, provenance: assumed}}\n"
        )
        (entries[heat],) = screen(ws.root).entries
    plain, heated = entries[0], entries[-200000]
    assert plain.adiabatic_rise == pytest.approx(heated.adiabatic_rise)
    assert heated.mtsr > plain.mtsr + 1  # the heat of crystallization counts in the MTSR
    assert any("MTSR from the semibatch model includes" in n and "P1" in n for n in heated.notes)


def test_the_recipe_reports_the_vent_per_batch(tmp_path):
    ws = _plant(tmp_path)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    s3 = _states(ws)["S3"]["flow"]["value"]  # kg/h; a batch of 2 h of it
    recipe = Recipe.model_validate(
        {
            "schema": "cheme/recipe/v1",
            "kind": "recipe",
            "batch_size": {"value": 2 * s3, "unit": "kg", "stream": "S3", "provenance": "assumed"},
            "hours_per_year": {"value": 8000, "provenance": "assumed"},
            "unit_procedures": [
                {
                    "id": "UP1",
                    "unit": "R",
                    "operations": [{"id": "dose", "kind": "dose", "from": "R"}],
                }
            ],
        }
    )
    process, _ = load(ws.root)
    result = evaluate(process, recipe)
    (gas,) = result.vents
    peak = 2 * Q * (1 - math.exp(-0.01 * DOSING))  # kmol/s: two hours of charge per batch
    assert gas.stream == "S4" and gas.peak_rate == pytest.approx(peak, rel=1e-5)
    assert gas.peak_volume_flow == pytest.approx(peak * R * 300.0 / 101.325 * 3600, rel=1e-5)
    left = (1 - math.exp(-0.01 * DOSING)) / (0.01 * DOSING)
    assert gas.kmol["G"] == pytest.approx(2 * (1 - left), rel=1e-5)
    assert gas.kg == pytest.approx(2 * (1 - left) * 16.0, rel=1e-5)
    assert "vent of R (UP1) by S4: peak" in recipe_text(result)


#: The outlet fingerprints cheme-as-code 1.7.0 wrote for the unvented semi-batch of
#: test_semibatch (and its plain batch): the vent leaves them as they were.
FINGERPRINTS_1_7_0 = {
    "semibatch": {"composition": "4dcc40903fe76f29", "flow": "d43e49340b61492a"},
    "batch": {"composition": "8c025838eea22822", "flow": "8895ce04c5dceebd"},
}


def _plain_batch():
    """The semi-batch of test_semibatch as a batch of its charge (S2 to a product)."""
    return (
        UNVENTED.replace("reactor: semibatch", "reactor: batch")
        .replace("batch: {dosing: [{stream: S2, time: 3600}], ", "batch: {time: 3600, ")
        .replace(
            "{id: in, direction: in}, {id: dose, direction: in}, {id: out, direction: out}",
            "{id: in, direction: in}, {id: out, direction: out}",
        )
        .replace("    from: G.out\n    to: R.dose", "    from: G.out\n    to: P2.in")
        .replace("products:\n", "products:\n  - {id: P2, ports: [{id: in, direction: in}]}\n")
        .replace("values: {S: 1.0}", "values: {S: 0.8, A: 0.2}")
    )


@pytest.mark.parametrize("kind", ["semibatch", "batch"])
def test_an_unvented_batch_fingerprints_as_before(tmp_path, kind):
    flowsheet = UNVENTED if kind == "semibatch" else _plain_batch()
    ws = _unvented_plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    outlet = _states(ws)["S3"]
    assert {
        name: outlet[name]["fingerprint"] for name in ("composition", "flow")
    } == FINGERPRINTS_1_7_0[kind]


def test_process_simulate_refuses_a_vented_batch(tmp_path):
    """Its reactors give one outlet: the vented batch's two are not coupled to DWSIM."""
    import tests.test_process_simulate_kinetic as kinetic

    batch = kinetic.TANK.replace("reactor: cstr", "reactor: batch").replace(
        "tank: {volume: 2.0, catalyst_loading: 1000, heat: adiabatic, provenance: assumed,\n"
        "           source: test fixture}",
        "batch: {time: 5.0, catalyst_loading: 1000, vent: {stream: S2, components: [NH3]},\n"
        "           provenance: assumed}",
    )
    assert "vent:" in batch
    errors = kinetic._errors(kinetic._translate(kinetic._plant(tmp_path, batch)))
    assert any("a vented batch's two outlets" in e for e in errors), errors
