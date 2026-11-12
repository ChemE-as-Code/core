"""Thermal screening of a cooling failure beyond the single largest reaction (ADR 0069, core#178):
the network potential of consecutive and competing reactions, what of each dosed reactant can
still react (a deliberate excess cannot), the largest gas release over a semi-batch, the gases
held in the liquid a cooling failure can release, the vapour load of a content boiling at the
MTSR, the products as candidates for the default MTT and the content's bubble point; each
against its closed form. A plant without the triggering inputs reports as in 1.11.0."""

import json
import math
from types import SimpleNamespace

import pytest

from chemeascode.domains.chemistry.thermochemistry import R
from chemeascode.domains.process.model import load
from chemeascode.domains.process.schema import ReactionHazard
from chemeascode.domains.process.stirred_tank import solve_node
from chemeascode.domains.safety.reaction_hazards import OPTIONAL, hazard_text, screen
from chemeascode.domains.safety.reaction_network import (
    bubble_point,
    consecutive,
    network_heat,
    reactive,
    simplex,
)
from tests import test_reaction_hazards as plain
from tests import test_semibatch as dosed
from tests import test_semibatch_screening as screening
from tests import test_semibatch_vent as vented
from tests import test_vent_vapour as vapour

Q = 1.0 / dosed.DOSING  # kmol/s dosed (1 kmol/h of charge over 3600 s)


def _r(rid, **nu):
    return SimpleNamespace(id=rid, stoichiometry={k: float(v) for k, v in nu.items()})


# -- the network potential ----------------------------------------------------------------------


def test_simplex_finds_the_vertex():
    """max 3x + 2y, x + y <= 4, x + 3y <= 6, x <= 3: (3, 1), 11."""
    value, x = simplex([3.0, 2.0], [[1, 1], [1, 3], [1, 0]], [4, 6, 3])
    assert value == pytest.approx(11.0) and x == pytest.approx([3.0, 1.0])
    assert simplex([1.0], [[-1.0]], [1.0]) is None  # unbounded


def test_the_network_heat_of_consecutive_competing_and_vented_reactions():
    # consecutive: A -> B, B -> C on 1 kmol A and 0.2 B: 100 + 50 (1 + 0.2)
    chain = [_r("R1", A=-1, B=1), _r("R2", B=-1, C=1)]
    heat, xi = network_heat(chain, {"A": 1.0, "B": 0.2}, {"R1": -100.0, "R2": -50.0})
    assert heat == pytest.approx(160.0) and xi == pytest.approx({"R1": 1.0, "R2": 1.2})
    assert consecutive(chain) == [("R2", "R1")]
    # competing for A: the more exothermic takes it
    rival = [_r("R1", A=-1, B=1), _r("R2", A=-1, C=1)]
    assert network_heat(rival, {"A": 1.0}, {"R1": -100.0, "R2": -300.0})[0] == pytest.approx(300)
    # A shared, B and D limit: R1 to its 0.6, R2 the 0.4 of A left: 60 + 32
    shared = [_r("R1", A=-1, B=-1, C=1), _r("R2", A=-1, D=-1, E=1)]
    found = network_heat(shared, {"A": 1, "B": 0.6, "D": 0.6}, {"R1": -100.0, "R2": -80.0})
    assert found[0] == pytest.approx(92.0)
    # a vented product feeds the consecutive reaction only with what the liquid keeps
    gas = [_r("R1", A=-1, G=1), _r("R2", G=-1, H=1)]
    heats = {"R1": -100.0, "R2": -50.0}
    assert network_heat(gas, {"A": 1.0}, heats, {"G": 1.0})[0] == pytest.approx(100.0)
    assert network_heat(gas, {"A": 1.0}, heats, {"G": 0.25})[0] == pytest.approx(137.5)
    # copper(I) chloride (copper-i-chloride-1 L-2): the chlorination and the comproportionation
    # on the copper(II) formed and already there, per kmol of chlorine 274.4 MJ
    cucl = [_r("CHL", CU=-1, CL2=-1, CUCL2=1), _r("COMP", CUCL2=-1, CU=-1, CUCL=2)]
    found = network_heat(
        cucl, {"CU": 10.0, "CL2": 1.0, "CUCL2": 0.5}, {"CHL": -220100.0, "COMP": -54300.0}
    )
    assert found[0] == pytest.approx(220100.0 + 54300.0 * 1.5)
    # a reaction without a heat takes no part; none at all releases nothing
    assert network_heat(chain, {"A": 1.0}, {"R1": -100.0})[0] == pytest.approx(100.0)
    assert network_heat(chain, {"A": 1.0}, {}) == (0.0, {})


def test_what_of_a_reactant_can_still_react():
    """A + B -> C with 2 kmol A and 0.5 B: 0.5 of A can react (the rest is an excess)."""
    rx = [_r("R1", A=-1, B=-1, C=1)]
    assert reactive(rx, {"A": 2.0, "B": 0.5}, "A") == pytest.approx(0.5)
    assert reactive(rx, {"A": 2.0}, "A") == 0.0
    assert reactive([_r("R1", A=-1, B=1)], {"A": 2.0}, "A") == pytest.approx(2.0)
    # B formed from A by a first reaction lets the excess react on
    rx = [_r("R1", A=-1, B=-1, C=1), _r("R2", C=-1, B=1, D=1)]
    assert reactive(rx, {"A": 2.0, "B": 0.5}, "A") == pytest.approx(2.0)
    assert reactive(rx, {"B": 1.0}, "A") == 0.0


# -- the bubble point ---------------------------------------------------------------------------


def _comp(**kw):
    return SimpleNamespace(**({"phase": None, "vapour_pressure": None} | kw))


def test_the_bubble_point_of_one_volatile_component_is_clausius_clapeyron():
    """x_S P_S(T) = P with P_S = 101.325 exp(-dH/R (1/T - 1/T_b)): 1/T = 1/T_b - R ln(P /
    (101.325 x_S)) / dH. A salt (no boiling point) does not boil."""
    comps = {
        "S": _comp(normal_boiling_point=373.0, heat_of_vaporization=40000.0),
        "SALT": _comp(),
    }
    for x, p in ((1.0, 101.325), (0.5, 101.325), (0.8, 50.0)):
        t, lack = bubble_point({"S": x, "SALT": 1 - x}, comps, p)
        exact = 1 / (1 / 373.0 - R * math.log(p / (101.325 * x)) / 40000.0)
        assert not lack and t == pytest.approx(exact, abs=1e-7)
    # a boiling point alone cannot be placed; a component left out does not boil
    comps["B"] = _comp(normal_boiling_point=350.0)
    assert bubble_point({"S": 0.5, "B": 0.5}, comps, 101.325) == (None, ["B"])
    t, _ = bubble_point({"S": 0.5, "B": 0.5}, comps, 101.325, left_out=["B"])
    assert t == pytest.approx(1 / (1 / 373.0 - R * math.log(2) / 40000.0), abs=1e-7)
    assert bubble_point({"SALT": 1.0}, comps, 101.325) == (None, [])


# -- in a plant: the network --------------------------------------------------------------------

CHAIN = dosed.REACTIONS + (
    "  - {id: R2, stoichiometry: {B: -1, C: 1}, phase: liquid,\n"
    "     heat_of_reaction: {value: -50000, provenance: assumed},\n"
    "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 1.0e-12},\n"
    "            orders: {B: 1}, provenance: assumed}}\n"
)


def _chain(tmp_path, hazard="hazard: {mtt: 380, td24: 390, provenance: assumed}"):
    flowsheet = dosed.FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, R2]", 1).replace(
        "hazard: {mtt: 380, td24: 390, provenance: assumed}", hazard
    )
    ws = dosed._plant(tmp_path, flowsheet, CHAIN)
    (ws.root / "process/materials.yaml").write_text(screening.WITH_C)
    return ws


def test_a_semibatch_screens_its_consecutive_reactions_as_a_network(tmp_path):
    """A dosed into S reacts to B (k 0.01, 100 MJ/kmol); B to C (50 MJ/kmol) is too slow to
    run: n_B = Q t - n_A. A cooling failure runs both to completion: at each step the network
    reaches 300 + (1e5 n_A + 5e4 (n_A + n_B)) / (150 (5 + Q t)), against 300 + max(1e5 n_A,
    5e4 n_B) / C for the largest single reaction. Reported without hazard.potential, counted
    with it."""
    ws = _chain(tmp_path / "a")
    (entry,) = screen(ws.root).entries
    grid = [i * dosed.DOSING / 20000 for i in range(20001)]

    def network(t):
        n_a = screening._n_a(0.01, t)
        return 300.0 + (1e5 * n_a + 5e4 * Q * t) / (150.0 * (5.0 + Q * t))

    def largest(t):
        n_a = screening._n_a(0.01, t)
        return 300.0 + max(1e5 * n_a, 5e4 * (Q * t - n_a)) / (150.0 * (5.0 + Q * t))

    best = max(network(t) for t in grid)
    net = entry.network
    assert net["mtsr_K"] == pytest.approx(best, rel=1e-6)
    assert net["consecutive"] == ["R2 on a product of R1"] and not net["in_mtsr"]
    # dT_ad of the whole batch: 1 kmol of A through both, over 6 kmol at 150 kJ/(kmol K)
    assert net["adiabatic_rise_K"] == pytest.approx(1.5e5 / 900.0, rel=1e-9)
    assert entry.mtsr == pytest.approx(max(largest(t) for t in grid), rel=1e-6)
    assert entry.adiabatic_rise == pytest.approx(1e5 / 900.0, rel=1e-9)
    assert any("hazard.potential: network counts it" in n for n in entry.notes)
    text = hazard_text(screen(ws.root))
    assert "  network of the counted reactions (R2 on a product of R1): dT_ad 166.7 K" in text
    # counted: the MTSR, its profile and dT_ad are the network's
    ws = _chain(
        tmp_path / "b", "hazard: {potential: network, mtt: 380, td24: 390, provenance: assumed}"
    )
    (counted,) = screen(ws.root).entries
    assert counted.mtsr == pytest.approx(best, rel=1e-6) and counted.network["in_mtsr"]
    assert counted.adiabatic_rise == pytest.approx(1.5e5 / 900.0, rel=1e-9)
    for q in counted.mtsr_profile:
        assert q["mtsr_K"] == pytest.approx(network(q["time_s"]), rel=1e-6)
    assert "(counted: hazard.potential: network)" in hazard_text(screen(ws.root))
    # the per-reaction values stay each reaction's alone
    assert counted.per_reaction == entry.per_reaction


def test_a_batch_screens_its_consecutive_reactions_as_a_network(tmp_path):
    """1 kmol A in 4 kmol S (560 kJ/K): R1 A -> B 80 MJ/kmol, R2 B -> C 40 MJ/kmol: the network
    120 MJ over 560 kJ/K, the largest single 80 MJ."""
    reactions = plain.REACTIONS + (
        "  - {id: R2, stoichiometry: {B: -1, C: 1}, phase: liquid,\n"
        "     heat_of_reaction: {value: -40000, provenance: assumed},\n"
        "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 1.0e-12},\n"
        "            orders: {B: 1}, provenance: assumed}}\n"
    )
    materials = plain.MATERIALS.replace(
        "templates:",
        "  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
        "     liquid_heat_capacity: 160, normal_boiling_point: 420}\ntemplates:",
    ).replace("components: [A, B, S]}", "components: [A, B, S, C]}")

    def run(hazard):
        flowsheet = plain.FLOWSHEET.replace("[R1]", "[R1, R2]").replace(
            "hazard: {td24: 420,", hazard
        )
        root = plain._plant(tmp_path / str(len(hazard)), flowsheet, materials)
        (root / "process/reactions.yaml").write_text(reactions)
        return screen(root).entries[0]

    entry = run("hazard: {td24: 420,")
    assert entry.adiabatic_rise == pytest.approx(80000 / 560)
    assert entry.network["adiabatic_rise_K"] == pytest.approx(120000 / 560)
    assert entry.network["mtsr_K"] == pytest.approx(330 + 120000 / 560)
    counted = run("hazard: {potential: network, td24: 420,")
    assert counted.adiabatic_rise == pytest.approx(120000 / 560)
    assert counted.mtsr == pytest.approx(330 + 120000 / 560)


# -- the accumulation of each dosed reactant ----------------------------------------------------

TWO_DOSED = dosed.REACTIONS + (
    "  - {id: R2, stoichiometry: {D: -1, C: 1}, phase: liquid,\n"
    "     heat_of_reaction: {value: -50000, provenance: assumed},\n"
    "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.001},\n"
    "            orders: {D: 1}, provenance: assumed}}\n"
)
WITH_C_D = screening.WITH_C.replace(
    "templates:",
    "  - {id: D, name: D, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
    "     liquid_heat_capacity: 150, normal_boiling_point: 400}\ntemplates:",
).replace("components: [A, B, S, C]}", "components: [A, B, S, C, D]}")


def test_each_dosed_reactant_accumulates_as_its_closed_form(tmp_path):
    """A and D dosed together (0.5 kmol each over 3600 s), each first order (k 0.01 and 0.001):
    each accumulates (1 - exp(-k t_d)) / (k t_d) of what is dosed at the end of the dosing.
    Nothing is in excess: what can still react is all of it."""
    flowsheet = dosed.FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, R2]", 1).replace(
        "values: {A: 1.0}", "values: {A: 0.5, D: 0.5}"
    )
    ws = dosed._plant(tmp_path, flowsheet, TWO_DOSED)
    (ws.root / "process/materials.yaml").write_text(WITH_C_D)
    (entry,) = screen(ws.root).entries
    found = entry.accumulations
    assert list(found) == ["A", "D"]
    for name, k in (("A", 0.01), ("D", 0.001)):
        exact = (1 - math.exp(-k * dosed.DOSING)) / (k * dosed.DOSING)
        assert found[name]["max"] == pytest.approx(exact, rel=1e-5)
        assert found[name]["time_s"] == pytest.approx(dosed.DOSING)
        assert found[name]["reactive_max"] == pytest.approx(found[name]["max"], rel=1e-9)
    assert entry.accumulation == pytest.approx(found["A"]["max"], rel=1e-12)  # the first's
    text = hazard_text(screen(ws.root))
    assert "  accumulation of each dosed reactant (largest; of it still able to react): A " in text


EXCESS = dosed.REACTIONS.replace(
    "stoichiometry: {A: -1, B: 1}", "stoichiometry: {A: -1, D: -1, B: 1}"
).replace("orders: {A: 1}", "orders: {A: 1, D: 1}")


def test_a_deliberate_excess_is_not_accumulated(tmp_path):
    """A + D -> B (second order) with 0.5 kmol D charged and 1 kmol A dosed: half of A is an
    excess. What of
    A can still react is min(n_A, n_D) at each step; the plain accumulation n_A keeps the
    excess (0.5 at the end)."""
    flowsheet = dosed.FLOWSHEET.replace("values: {S: 1.0}", "values: {S: 0.9, D: 0.1}")
    ws = dosed._plant(tmp_path, flowsheet, EXCESS)
    (ws.root / "process/materials.yaml").write_text(WITH_C_D)
    process, _ = load(ws.root)
    inlets = [s for s in process.flowsheet.streams if s.id in ("S1", "S2")]
    solved, _ = solve_node(process, process.nodes["R"], inlets, "design")
    points = solved.cooling_profile
    (entry,) = screen(ws.root).entries
    found = entry.accumulations["A"]
    assert found["max"] == pytest.approx(max(q.moles["A"] for q in points), rel=1e-12)
    assert found["max"] >= 0.5 - 1e-6  # the excess stays
    assert found["reactive_max"] == pytest.approx(
        max(min(q.moles["A"], q.moles["D"]) for q in points), rel=1e-9
    )
    assert found["reactive_max"] < 0.5 * found["max"]


# -- the gas release over the batch -------------------------------------------------------------


@pytest.mark.parametrize("ea", [0.0, 40000.0])
def test_the_largest_gas_release_over_the_batch(tmp_path, ea):
    """A -> B + G(g) vented: at each step the gas forms at k(T) n_A at that step's MTSR; the
    largest over the batch, per batch (two hours of flows), against the vent capacity."""
    flowsheet = vented.FLOWSHEET.replace(
        "hazard: {td24: 390,", "hazard: {vent_capacity: 5, td24: 390,"
    )
    ws = screening._vent_plant(tmp_path, flowsheet, screening.RECIPE, ea=ea)
    process, _ = load(ws.root)
    inlets = [s for s in process.flowsheet.streams if s.id in ("S1", "S2")]
    solved, _ = solve_node(process, process.nodes["R"], inlets, "design")

    def m3_h(q):
        t = q.mtsr()
        return 2 * 0.01 * math.exp(-ea / (R * t)) * q.moles["A"] * R * t / 101.325 * 3600

    best = max(solved.cooling_profile, key=m3_h)
    report = screen(ws.root)
    gas = report.entries[0].gas_release
    over = gas["largest_over_batch"]
    assert over["rate_m3_h"] == pytest.approx(m3_h(best), rel=1e-9)
    assert over["time_s"] == best.time and over["temperature_K"] == best.mtsr()
    assert over["by_component_kmol_s"] == {"G": pytest.approx(over["rate_kmol_s"], rel=1e-12)}
    assert over["capacity_ratio"] == pytest.approx(over["rate_m3_h"] / 5, rel=1e-12)
    assert over["rate_m3_h"] >= gas["rate_m3_h"] * (1 - 1e-9)
    assert "  largest gas release over the batch: " in hazard_text(report)


# -- the gases held in the liquid ---------------------------------------------------------------


def test_a_dissolved_gas_in_the_charge_is_a_release(tmp_path):
    """D (250 K), 2 % of a 5 kmol/h charge: 0.1 kmol (1.604 kg) a batch's hour of flows, held
    at the start (a batch's worst moment), boiling below the MTSR: an info finding."""
    entry = screening._charged(tmp_path, "{A: 0.2, S: 0.78, D: 0.02}")
    held = entry.dissolved_release
    row = held["components"]["D"]
    assert row["kmol"] == pytest.approx(0.1) and row["kg"] == pytest.approx(1.604)
    assert row["boiling_point_K"] == 250.0 and row["mtsr_above_boiling_point"]
    assert row["why"].startswith("dissolved gas") and "per hour" in held["basis"]


def test_a_dosed_gas_held_in_the_liquid_is_a_release(tmp_path):
    """A dosed as a gas, 0.8 absorbed, first order: the liquid holds 0.8 (Q/k)(1 - exp(-k t))
    of it, the most at the end of the dosing."""
    flowsheet = vented.FLOWSHEET.replace("time: 3600}]", "time: 3600, absorbed: 0.8}]")
    ws = vented._plant(tmp_path, flowsheet)
    report = screen(ws.root)
    row = report.entries[0].dissolved_release["components"]["A"]
    exact = 0.8 * Q / 0.01 * (1 - math.exp(-0.01 * dosed.DOSING))
    assert row["kmol"] == pytest.approx(exact, rel=1e-5) and row["why"] == "dosed gas"
    assert row["time_s"] == pytest.approx(dosed.DOSING)
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-dissolved"]
    assert finding.level == "info" and finding.line is not None and "A up to" in finding.message
    assert finding.hint


# -- the boil-up at the MTSR --------------------------------------------------------------------


def test_the_boil_up_of_a_content_boiling_at_the_mtsr(tmp_path):
    """S the only volatile component, ln P_S = a - b/T (kPa): the content boils at x_S P_S(T_b)
    = P, T_b = b / (a - ln(P / x_S)); there the reaction's heat 1e5 k n_A boils off
    1e5 k n_A / dHvap_S of S."""
    a = math.log(90.0) + 12000 / 300.0
    hot = vapour.VAPOUR_MATERIALS.replace(
        "a: %r, b: 4000" % (math.log(50.0) + 4000 / 300.0), f"a: {a!r}, b: 12000"
    )
    ws = vapour._plant(tmp_path, materials=hot)
    process, _ = load(ws.root)
    inlets = [s for s in process.flowsheet.streams if s.id in ("S1", "S2")]
    solved, _ = solve_node(process, process.nodes["R"], inlets, "design")
    worst = max(solved.cooling_profile, key=lambda q: q.mtsr())
    report = screen(ws.root)
    gas = report.entries[0].gas_release
    assert gas["boils"]
    boil = gas["boil_up"]
    total = sum(v for v in worst.moles.values() if v > 0)
    t_b = 12000 / (a - math.log(101.325 / (worst.moles["S"] / total)))
    assert boil["temperature_K"] == pytest.approx(t_b, abs=1e-6)
    heat = 1e5 * 0.01 * worst.moles["A"]
    assert boil["heat_kW"] == pytest.approx(heat, rel=1e-9)
    assert boil["vapour_kmol_s"] == pytest.approx(heat / 30000.0, rel=1e-9)
    assert boil["vapour_m3_h"] == pytest.approx(heat / 30000 * R * t_b / 101.325 * 3600, rel=1e-9)
    assert boil["by_component_kmol_s"] == {"S": pytest.approx(heat / 30000.0, rel=1e-9)}
    assert "  boil-up at the bubble point " in hazard_text(report)
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"]
    assert "its boil-up at the bubble point" in finding.message
    # over the batch the saturated vapour G Y / (1 - Y) diverges as Y nears 1: it is at most
    # what the reactions' heat at that step's MTSR evaporates, 1e5 k n_A / dHvap_S
    over = gas["largest_over_batch"]
    assert over["heat_limited"]
    (step,) = [q for q in solved.cooling_profile if q.time == over["time_s"]]
    assert over["by_component_kmol_s"]["S"] == pytest.approx(
        1e5 * 0.01 * step.moles["A"] / 30000.0, rel=1e-9
    )
    assert "the vapour limited by the reactions' heat" in hazard_text(report)


# -- the MTT: products and the bubble point -----------------------------------------------------


def test_a_product_boiling_lowest_sets_the_default_mtt(tmp_path):
    """B formed from A (20 % of the charge) boils at 350 K, below the solvent's 373 K: it sets
    the MTT (until 1.11.0 only what is charged and dosed did). A minor product (below 5 %) or
    one boiling below T_p (it leaves as it forms) does not."""
    low = plain.MATERIALS.replace("normal_boiling_point: 410}", "normal_boiling_point: 350}")
    entry = screening._at(tmp_path / "a", 101.325, low)
    assert (entry.mtt, entry.mtt_basis) == (
        350.0,
        "normal boiling point of B, a product (20% of the liquid after R1)",
    )
    minor = plain.FLOWSHEET.replace("values: {A: 0.2, S: 0.8}", "values: {A: 0.02, S: 0.98}")
    (entry,) = screen(plain._plant(tmp_path / "b", minor, low)).entries
    assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    gas = plain.MATERIALS.replace("normal_boiling_point: 410}", "normal_boiling_point: 320}")
    entry = screening._at(tmp_path / "c", 101.325, gas)
    assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    assert not entry.mtt_left_out


def test_the_mtt_from_the_contents_bubble_point(tmp_path):
    """hazard.mtt_from: bubble-point: the lower of the charge's bubble point and that once R1
    ran to completion, each where sum x_i P_i(T) = P (Clausius-Clapeyron from each component's
    boiling point and heat of vaporization)."""
    materials = screening._vaporization(A=35000, B=38000, S=30000)
    flowsheet = plain.FLOWSHEET.replace(
        "hazard: {td24: 420,", "hazard: {mtt_from: bubble-point, td24: 420,"
    )
    root = plain._plant(tmp_path / "a", flowsheet, materials)
    (entry,) = screen(root).entries
    process, _ = load(root)
    comps = process.components()
    contents = entry.bubble_point["contents"]
    assert list(contents) == ["the charge", "the content after R1"]
    for moles, t in (
        ({"A": 1, "S": 4}, contents["the charge"]),
        ({"B": 1, "S": 4}, contents["the content after R1"]),
    ):
        p = sum(
            v
            / 5
            * 101.325
            * math.exp(
                -comps[n].heat_of_vaporization / R * (1 / t - 1 / comps[n].normal_boiling_point)
            )
            for n, v in moles.items()
        )
        assert p == pytest.approx(101.325, rel=1e-9)
    assert entry.mtt == pytest.approx(min(contents.values()))
    assert entry.mtt_basis.startswith("bubble point of the charge at 101.3 kPa(a)")
    assert "  bubble point at 101.3 kPa(a): the charge " in hazard_text(screen(root))
    # without the data: the MTT is missing, the components named
    root = plain._plant(tmp_path / "b", flowsheet)
    (entry,) = screen(root).entries
    assert entry.mtt is None
    assert any("bubble point needs vapour_pressure" in m and "A, S" in m for m in entry.missing)


# -- unchanged without the inputs ---------------------------------------------------------------


def test_a_reactor_without_the_inputs_reports_as_before(tmp_path):
    """One dosed reactant without excess, one reaction, no vent: none of the new keys; the
    hazard's dump keeps its form."""
    report = screen(dosed._plant(tmp_path).root)
    data = json.loads(report.to_json())["reactors"][0]
    for key in ("network", "accumulations", "bubble_point", "dissolved_release"):
        assert key in OPTIONAL and key not in data
    assert not [f for f in report.findings if f.rule == "cheme.reactor-hazard-dissolved"]
    dump = ReactionHazard.model_validate({"mtt": 380, "provenance": "assumed"}).model_dump()
    assert "potential" not in dump and "mtt_from" not in dump
    with pytest.raises(ValueError):
        ReactionHazard.model_validate({"potential": "sum", "provenance": "assumed"})
