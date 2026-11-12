"""Semi-batch thermal screening (ADR 0058): the default MTT without vent components, dosed and
dissolved gases and at the vessel's pressure (Clausius-Clapeyron), the reactions that count
(``hazard.reactions``) with each reaction's dT_ad and MTSR, the MTSR profile over the batch and
the gas release at the MTSR against ``hazard.vent_capacity``; each against its closed form.
A reactor that uses none of it screens to the MTT, MTSR and class of 1.8.0; a reactor with more
than one reaction, a semi-batch and a vented batch report more (per_reaction, mtsr_profile,
gas_release), one reaction without dosing or vent reports as in 1.8.0."""

import json
import math

import pytest

from chemeascode.domains.chemistry.thermochemistry import R
from chemeascode.domains.process.model import load
from chemeascode.domains.process.schema import ReactionHazard
from chemeascode.domains.process.stirred_tank import solve_node
from chemeascode.domains.safety.reaction_hazards import (
    OPTIONAL,
    boiling_point,
    hazard_text,
    screen,
)
from tests import test_reaction_hazards as plain
from tests import test_semibatch as dosed
from tests import test_semibatch_vent as vented

Q = 1.0 / dosed.DOSING  # kmol/s of A dosed (1 kmol/h of charge over 3600 s)


def _n_a(k, t):
    """kmol of A in the vessel at t s, first order, dosed at Q from 0 to DOSING."""
    return Q / k * (1 - math.exp(-k * t))


def _mtsr(k, t, heat=1e5):
    """K: 300 K plus the heat of A run to completion over the content, 150 kJ/(kmol K) each."""
    return 300.0 + heat * _n_a(k, t) / (150.0 * (5.0 + Q * t))


# -- the MTSR profile ---------------------------------------------------------------------------


@pytest.mark.parametrize("k", [1e-2, 1e-3])
def test_the_cooling_profile_is_the_closed_form_at_every_step(k):
    """A -> B dosed at Q into 5 kmol of S, isothermal at 300 K: at each step the cooling-failure
    temperature is 300 + (-dH) n_A / C with n_A = (Q/k)(1 - exp(-k t)), C = 150 (5 + Q t)."""
    result = dosed._semibatch(k)
    points = result.cooling_profile
    assert len(points) > 20
    for q in points:
        if q.time <= dosed.DOSING:
            assert q.accumulation == pytest.approx(_n_a(k, q.time), rel=1e-6, abs=1e-12)
            assert q.mtsr() == pytest.approx(_mtsr(k, q.time), rel=1e-9, abs=1e-6)
            assert q.rises == {"R1": pytest.approx(q.mtsr() - 300.0, abs=1e-9)}
    # the model's worst moment is the profile's
    worst = max(points, key=lambda q: q.mtsr())
    assert result.cooling_failure == (worst.time, worst.temperature, worst.mtsr())


def test_the_screening_gives_the_mtsr_profile_over_the_batch(tmp_path):
    ws = dosed._plant(tmp_path, dosed.FLOWSHEET.replace("time: 3600}]", "time: 3600}], time: 1800"))
    (entry,) = screen(ws.root).entries
    profile = entry.mtsr_profile
    assert 10 <= len(profile) <= 22
    assert profile[0]["time_s"] == 0.0 and profile[-1]["time_s"] == pytest.approx(5400.0)
    times = [q["time_s"] for q in profile]
    assert times == sorted(times) and len(set(times)) == len(times)
    for q in profile:
        if q["time_s"] <= dosed.DOSING:
            assert q["mtsr_K"] == pytest.approx(_mtsr(0.01, q["time_s"]), rel=1e-9)
            assert q["accumulation"] == pytest.approx(_n_a(0.01, q["time_s"]), rel=1e-6)
    # the worst moment is in it and is the MTSR
    assert max(q["mtsr_K"] for q in profile) == pytest.approx(entry.mtsr, rel=1e-12)
    # after the dosing the accumulated A reacts away: exp(-k t) over the post-reaction
    last = profile[-1]
    assert last["accumulation"] == pytest.approx(_n_a(0.01, 3600) * math.exp(-18), rel=1e-4)
    line = next(x for x in hazard_text(screen(ws.root)).splitlines() if "MTSR over" in x)
    assert line.startswith("  MTSR over the batch (h: X_ac, MTSR K): 0: 0, 300.0; ")
    assert line.endswith("1.5: 4.23e-10, 300.0")
    data = json.loads(screen(ws.root).to_json())["reactors"][0]
    assert data["mtsr_profile"] == profile


# -- which reactions count ----------------------------------------------------------------------

TWO = (
    dosed.REACTIONS
    + """  - {id: R2, stoichiometry: {A: -1, C: 1}, phase: liquid,
     heat_of_reaction: {value: -300000, provenance: assumed},
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.01},
            orders: {A: 1}, provenance: assumed}}
"""
)
WITH_C = dosed.MATERIALS.replace(
    "templates:",
    "  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
    "     liquid_heat_capacity: 150, normal_boiling_point: 400}\ntemplates:",
).replace("components: [A, B, S]}", "components: [A, B, S, C]}")


def _two(tmp_path, flowsheet=dosed.FLOWSHEET):
    ws = dosed._plant(tmp_path, flowsheet.replace("reactions: [R1]", "reactions: [R1, R2]", 1), TWO)
    (ws.root / "process/materials.yaml").write_text(WITH_C)
    return ws


def test_a_semibatch_reports_each_reaction_and_counts_the_chosen_ones(tmp_path):
    """R1 and R2 consume A in parallel (k 0.01 each): n_A = (Q/2k)(1 - exp(-2 k t)). Each run
    to completion of n_A gives its heat over the content: R2's is three times R1's, at the same
    worst moment. By default the largest counts (R2), with hazard.reactions: [R1] only R1."""
    (both,) = screen(_two(tmp_path / "a").root).entries
    assert both.counted_reactions == ["R1", "R2"]
    assert both.counted_basis == "every reaction, the largest"
    one, two = both.per_reaction["R1"], both.per_reaction["R2"]
    # dT_ad of the whole batch: 1 kmol of A over 6 kmol at 150 kJ/(kmol K)
    assert one["adiabatic_rise"] == pytest.approx(1e5 / 900.0, rel=1e-9)
    assert two["adiabatic_rise"] == pytest.approx(3e5 / 900.0, rel=1e-9)
    assert both.adiabatic_rise == pytest.approx(3e5 / 900.0, rel=1e-9)
    assert two["mtsr"] - 300.0 == pytest.approx(3 * (one["mtsr"] - 300.0), rel=1e-9)
    assert two["time_s"] == one["time_s"]
    assert both.mtsr == pytest.approx(two["mtsr"], rel=1e-12)
    # the worst moment of n_A / (5 + Q t), n_A of the two parallel reactions
    grid = [i * dosed.DOSING / 20000 for i in range(20001)]
    best = max(Q / 0.02 * (1 - math.exp(-0.02 * t)) / (150 * (5 + Q * t)) for t in grid)
    assert both.mtsr == pytest.approx(300.0 + 3e5 * best, rel=1e-6)
    ws = _two(
        tmp_path / "b",
        dosed.FLOWSHEET.replace("hazard: {mtt: 380,", "hazard: {reactions: [R1], mtt: 380,"),
    )
    (main,) = screen(ws.root).entries
    assert main.counted_reactions == ["R1"] and main.counted_basis == "hazard.reactions"
    assert main.mtsr == pytest.approx(one["mtsr"], rel=1e-12)
    assert main.adiabatic_rise == pytest.approx(1e5 / 900.0, rel=1e-9)
    assert main.per_reaction == both.per_reaction
    assert all(q["mtsr_K"] - 300.0 <= one["mtsr"] - 300.0 + 1e-9 for q in main.mtsr_profile)
    assert any("of R1, hazard.reactions" in n for n in main.notes)
    text = hazard_text(screen(ws.root))
    assert "  reactions (hazard.reactions: R1): R1 dT_ad 111.1 K, MTSR " in text
    # a reaction the step does not hold: a warning, every reaction counts
    ws = _two(
        tmp_path / "c",
        dosed.FLOWSHEET.replace("hazard: {mtt: 380,", "hazard: {reactions: [R9], mtt: 380,"),
    )
    report = screen(ws.root)
    (stray,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-reactions"]
    assert stray.level == "warning" and "R9" in stray.message
    assert "(every reaction counts)" in stray.message and stray.line is not None
    assert report.entries[0].mtsr == pytest.approx(both.mtsr, rel=1e-12)


def test_a_batch_counts_the_chosen_reactions(tmp_path):
    """A batch of 1 kmol A in 4 kmol S (560 kJ/K): R1 80 MJ/kmol, R2 160 MJ/kmol, each alone
    run to completion of A: dT_ad 142.9 and 285.7 K."""
    reactions = plain.REACTIONS + (
        "  - {id: R2, stoichiometry: {A: -1, B: 1}, phase: liquid,\n"
        "     heat_of_reaction: {value: -160000, provenance: assumed},\n"
        "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.001},\n"
        "            orders: {A: 1}, provenance: assumed}}\n"
    )
    flowsheet = plain.FLOWSHEET.replace("reactions: [R1]", "reactions: [R1, R2]")
    root = plain._plant(tmp_path / "a", flowsheet)
    (root / "process/reactions.yaml").write_text(reactions)
    (entry,) = screen(root).entries
    assert entry.adiabatic_rise == pytest.approx(160000.0 / 560.0)
    assert entry.per_reaction == {
        "R1": {
            "adiabatic_rise": pytest.approx(80000 / 560),
            "mtsr": pytest.approx(330 + 80000 / 560),
        },
        "R2": {
            "adiabatic_rise": pytest.approx(160000 / 560),
            "mtsr": pytest.approx(330 + 160000 / 560),
        },
    }
    root = plain._plant(
        tmp_path / "b",
        flowsheet.replace("hazard: {td24: 420,", "hazard: {reactions: [R1], td24: 420,"),
    )
    (root / "process/reactions.yaml").write_text(reactions)
    (entry,) = screen(root).entries
    assert entry.adiabatic_rise == pytest.approx(80000.0 / 560.0)
    assert entry.mtsr == pytest.approx(330.0 + 80000.0 / 560.0)
    assert entry.counted_reactions == ["R1"]


def test_a_reactor_without_the_new_inputs_reports_as_before(tmp_path):
    """One reaction, no vent, no dosing: the JSON holds none of the new keys. With two
    reactions the values are those of 1.8.0 (the largest counts) and the JSON adds the
    reactions counted and each reaction alone, the text a line."""
    report = screen(plain._plant(tmp_path))
    (data,) = json.loads(report.to_json())["reactors"]
    assert not set(OPTIONAL) & set(data)
    assert set(data) == {
        "node", "model", "process_temperature", "adiabatic_rise", "accumulation", "mtsr", "mtt",
        "mtt_basis", "td24", "criticality", "sensitivity", "missing", "notes",
    }  # fmt: skip
    assert "reactions (" not in hazard_text(report)
    hazard = ReactionHazard.model_validate({"td24": 400, "provenance": "assumed"})
    assert hazard.model_dump(exclude_none=False).keys() == {"td24", "mtt", "provenance", "source"}
    root = plain._plant(tmp_path / "two", plain.FLOWSHEET.replace("[R1]", "[R1, R2]"))
    (root / "process/reactions.yaml").write_text(ENDO)
    report = screen(root)
    (data,) = json.loads(report.to_json())["reactors"]
    assert set(data) - set(OPTIONAL) == {
        "node", "model", "process_temperature", "adiabatic_rise", "accumulation", "mtsr", "mtt",
        "mtt_basis", "td24", "criticality", "sensitivity", "missing", "notes",
    }  # fmt: skip
    assert set(data) & set(OPTIONAL) == {"counted_reactions", "counted_basis", "per_reaction"}
    rise = 80000.0 / 560.0  # R1 alone, as in 1.8.0: R2 is endothermic
    assert (data["adiabatic_rise"], data["mtsr"]) == (
        pytest.approx(rise),
        pytest.approx(330 + rise),
    )
    assert (data["mtt"], data["criticality"]) == (373.0, 4)
    assert "  reactions (every reaction, the largest: R1, R2): " in hazard_text(report)


ENDO = plain.REACTIONS + (
    "  - {id: R2, stoichiometry: {A: -1, B: 1}, phase: liquid,\n"
    "     heat_of_reaction: {value: 50000, provenance: assumed},\n"
    "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.001},\n"
    "            orders: {A: 1}, provenance: assumed}}\n"
)


def test_an_endothermic_reaction_alone_does_not_cool_the_mtsr_below_t_p(tmp_path):
    """R1 exothermic (80 MJ/kmol), R2 endothermic (+50 MJ/kmol) on 1 kmol A over 560 kJ/K: R2's
    dT_ad is -89.3 K, its MTSR T_p 330 K (until this fix 240.7 K), as in the semi-batch."""
    root = plain._plant(tmp_path, plain.FLOWSHEET.replace("[R1]", "[R1, R2]"))
    (root / "process/reactions.yaml").write_text(ENDO)
    report = screen(root)
    (entry,) = report.entries
    assert entry.per_reaction["R2"] == {
        "adiabatic_rise": pytest.approx(-50000 / 560),
        "mtsr": 330.0,
    }
    assert entry.per_reaction["R1"]["mtsr"] == pytest.approx(330 + 80000 / 560)
    assert all(v["mtsr"] >= entry.process_temperature for v in entry.per_reaction.values())
    assert "R2 dT_ad -89.3 K (endothermic), MTSR 330.0 K" in hazard_text(report)


# -- the MTT ------------------------------------------------------------------------------------


@pytest.mark.parametrize("kpa", [20.0, 50.0, 101.325, 300.0, 1000.0])
def test_boiling_point_is_clausius_clapeyron(kpa):
    t = boiling_point(373.0, 40000.0, kpa)
    assert math.log(kpa / 101.325) == pytest.approx(-40000.0 / R * (1 / t - 1 / 373.0), rel=1e-12)


def _at(tmp_path, kpa, materials=plain.MATERIALS, temperature=330):
    flowsheet = plain.FLOWSHEET.replace(
        "pressure: {value: 101.325,", f"pressure: {{value: {kpa},"
    ).replace("temperature: {value: 330,", f"temperature: {{value: {temperature},")
    (entry,) = screen(plain._plant(tmp_path, flowsheet, materials)).entries
    return entry


def _vaporization(**heats):
    text = plain.MATERIALS
    for name, heat in heats.items():
        text = text.replace(
            f"{{id: {name}, name: ", f"{{id: {name}, heat_of_vaporization: {heat}, name: "
        )
    return text


def test_the_mtt_at_the_vessels_pressure(tmp_path):
    """A (390 K) and S (373 K) charged (B forms): at about atmospheric pressure S's normal
    boiling point, as in 1.8.0; above it, Clausius-Clapeyron with each one's heat of
    vaporization."""
    for kpa in (90.0, 101.325, 110.0):
        entry = _at(tmp_path / str(kpa), kpa, _vaporization(S=30000))
        assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    # 300 kPa: S at 420.1 K; A, without heat_of_vaporization, boils above 390 K, maybe lower
    entry = _at(tmp_path / "a", 300.0, _vaporization(S=30000))
    assert entry.mtt is None and "the MTT (hazard.mtt)" in entry.missing
    assert any("the MTT at 300 kPa(a) needs heat_of_vaporization of A" in n for n in entry.notes)
    entry = _at(tmp_path / "b", 300.0, _vaporization(S=30000, A=35000))
    s, a = boiling_point(373.0, 30000, 300.0), boiling_point(390.0, 35000, 300.0)
    assert s == pytest.approx(420.1, abs=0.1) and a > s  # A: 431.4 K
    assert entry.mtt == pytest.approx(min(s, a)) and entry.mtt_basis.startswith(
        "boiling point of S at 300 kPa(a), Clausius-Clapeyron"
    )
    # both known: no note
    assert not any("needs heat_of_vaporization" in n for n in entry.notes)
    # 120 kPa: S at 379.6 K; A, unknown, boils above its 390 K: it cannot set the MTT
    entry = _at(tmp_path / "e", 120.0, _vaporization(S=30000))
    assert entry.mtt == pytest.approx(boiling_point(373.0, 30000, 120.0))
    assert entry.mtt == pytest.approx(379.6, abs=0.05) and "of S at 120 kPa(a)" in entry.mtt_basis
    # under vacuum: S boils at 335.6 K; without its heat of vaporization a note says lower
    entry = _at(tmp_path / "c", 50.0, _vaporization(S=30000))
    assert entry.mtt == pytest.approx(boiling_point(373.0, 30000, 50.0))
    entry = _at(tmp_path / "d", 50.0)
    assert entry.mtt == 373.0
    assert any("at 50 kPa(a) A, S boil(s) below the normal" in n for n in entry.notes)


WITH_D = plain.MATERIALS.replace(
    "templates:",
    "  - {id: D, name: D, formula: CH4, molar_mass: 16.04, liquid_molar_volume: 0.05,\n"
    "     liquid_heat_capacity: 100, normal_boiling_point: 250}\ntemplates:",
).replace("components: [A, B, S]}", "components: [A, B, S, D]}")


def _charged(tmp_path, values, materials=WITH_D, temperature=330, kpa=101.325):
    flowsheet = (
        plain.FLOWSHEET.replace("values: {A: 0.2, S: 0.8}", f"values: {values}")
        .replace("temperature: {value: 330,", f"temperature: {{value: {temperature},")
        .replace("pressure: {value: 101.325,", f"pressure: {{value: {kpa},")
    )
    (entry,) = screen(plain._plant(tmp_path, flowsheet, materials)).entries
    return entry


def test_a_dissolved_gas_is_left_out_of_the_mtt(tmp_path):
    """D (250 K), 2 % of the charge at 330 K, is a dissolved gas: the solvent's 373 K is the
    MTT. At 6 % it is no minor share (DISSOLVED 5 %): it sets the MTT, below T_p."""
    entry = _charged(tmp_path / "a", "{A: 0.2, S: 0.78, D: 0.02}")
    assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    assert entry.mtt_left_out == {
        "D": "dissolved gas (2.00% of the liquid, boils at 250.0 K, below T_p 330.0 K)"
    }
    assert any(n.startswith("MTT: left out D (dissolved gas") for n in entry.notes)
    entry = _charged(tmp_path / "b", "{A: 0.2, S: 0.74, D: 0.06}")
    assert (entry.mtt, entry.mtt_basis) == (250.0, "normal boiling point of D")
    assert not entry.mtt_left_out
    # nothing else with a boiling point: the MTT needs hazard.mtt
    no_bp = WITH_D.replace(", normal_boiling_point: 390}", "}").replace(
        ", normal_boiling_point: 373}", "}"
    )
    # the product B (410 K) boils in the liquid it forms in (ADR 0069): it sets the MTT
    entry = _charged(tmp_path / "c", "{A: 0.2, S: 0.78, D: 0.02}", no_bp)
    assert (entry.mtt, entry.mtt_basis) == (
        410.0,
        "normal boiling point of B, a product (20% of the liquid after R1)",
    )
    no_bp = no_bp.replace(", normal_boiling_point: 410}", "}")
    entry = _charged(tmp_path / "d", "{A: 0.2, S: 0.78, D: 0.02}", no_bp)
    assert entry.mtt is None and set(entry.mtt_left_out) == {"D"}
    assert any("nothing else boils in the liquid" in m for m in entry.missing)


@pytest.mark.parametrize("temperature", [373.15, 380.0, 395.0])
def test_a_solvent_at_reflux_keeps_the_mtt_at_or_below_t_p(tmp_path, temperature):
    """S (373 K), 80 % of the charge, at or above its boiling point: the liquor boils (at
    reflux), the MTT is S's boiling point, below T_p (until this fix A's 390 K, or none), and
    the class is that of an MTSR above the MTT."""
    entry = _charged(tmp_path, "{A: 0.2, S: 0.8}", temperature=temperature)
    assert (entry.mtt, entry.mtt_basis) == (373.0, "normal boiling point of S")
    assert entry.mtt <= entry.process_temperature and not entry.mtt_left_out
    assert any(
        n.startswith(f"MTT 373.0 K (normal boiling point of S) below T_p {temperature:.1f} K")
        for n in entry.notes
    )
    assert entry.mtsr > entry.mtt and entry.criticality in (3, 4)


def test_above_atmospheric_every_unknown_that_could_set_the_mtt_is_named(tmp_path):
    """At 300 kPa S (373 K, 30 kJ/mol) boils at 420.1 K; A (330 K) and D (340 K) without a heat
    of vaporization both boil below that at 101 kPa, so either could set the MTT: both named."""
    materials = (
        _vaporization(S=30000)
        .replace("normal_boiling_point: 390}", "normal_boiling_point: 330}")
        .replace(
            "templates:",
            "  - {id: D, name: D, formula: CH4, molar_mass: 16.04, liquid_molar_volume: 0.05,\n"
            "     liquid_heat_capacity: 100, normal_boiling_point: 340}\ntemplates:",
        )
        .replace("components: [A, B, S]}", "components: [A, B, S, D]}")
    )
    entry = _charged(tmp_path, "{A: 0.2, S: 0.6, D: 0.2}", materials, kpa=300)
    assert entry.mtt is None
    assert any("needs heat_of_vaporization of A, D (" in n for n in entry.notes), entry.notes


# -- the gas release ----------------------------------------------------------------------------


def _vent_plant(tmp_path, flowsheet=vented.FLOWSHEET, recipe=None, ea=0.0):
    ws = vented._plant(tmp_path, flowsheet, recipe)
    if ea:
        path = ws.root / "process/reactions.yaml"
        path.write_text(path.read_text().replace("k: {A: 0.01}", f"k: {{A: 0.01, Ea: {ea}}}"))
    return ws


RECIPE = {
    "schema": "cheme/recipe/v1",
    "kind": "recipe",
    "batch_size": {"value": 2 * 5 * 44.05, "unit": "kg", "stream": "S1", "provenance": "assumed"},
    "hours_per_year": {"value": 8000, "provenance": "assumed"},
    "unit_procedures": [
        {"id": "UP1", "unit": "R", "operations": [{"id": "dose", "kind": "dose", "from": "R"}]}
    ],
}


@pytest.mark.parametrize("ea", [0.0, 40000.0])
def test_the_gas_release_at_the_mtsr(tmp_path, ea):
    """A -> B + G(g), first order in c_A: G forms at k(T) n_A (volume basis: V k c_A). At the
    MTSR it is k(MTSR) n_A of the worst moment, an upper bound; run to completion that n_A
    gives n_A of G. Without a recipe on the flowsheet's hour of flows, with one per batch."""
    ws = _vent_plant(tmp_path / "a", ea=ea)
    process, _ = load(ws.root)
    node = process.nodes["R"]
    inlets = [s for s in process.flowsheet.streams if s.id in ("S1", "S2")]
    solved, _ = solve_node(process, node, inlets, "design")
    worst = max(solved.cooling_profile, key=lambda q: q.mtsr())
    report = screen(ws.root)
    (entry,) = report.entries
    gas = entry.gas_release
    assert entry.mtsr == pytest.approx(worst.mtsr(), rel=1e-12)
    k = 0.01 * math.exp(-ea / (R * entry.mtsr))
    rate = k * worst.moles["A"]
    assert gas["rate_kmol_s"] == pytest.approx(rate, rel=1e-9)
    assert gas["rate_m3_h"] == pytest.approx(rate * R * entry.mtsr / 101.325 * 3600, rel=1e-9)
    assert (gas["temperature_K"], gas["pressure_kPa"]) == (entry.mtsr, 101.325)
    assert gas["formed_by"] == "R1"
    assert gas["formed_kmol"] == pytest.approx(worst.moles["A"], rel=1e-12)
    assert not gas["per_batch"] and "no process/recipe.yaml" in gas["basis"]
    if not ea:  # isothermal at 300 K: the closed form of n_A at the worst moment
        assert worst.moles["A"] == pytest.approx(_n_a(0.01, worst.time), rel=1e-6)
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"]
    assert finding.level == "warning" and "no vent capacity stated" in finding.message
    assert "hazard.vent_capacity" in finding.hint and finding.line is not None
    # with a recipe: two hours of the flowsheet's flows per batch
    ws = _vent_plant(tmp_path / "b", recipe=RECIPE, ea=ea)
    per_batch = screen(ws.root).entries[0].gas_release
    assert per_batch["per_batch"] and per_batch["basis"].startswith("per batch (2 h")
    assert per_batch["rate_kmol_s"] == pytest.approx(2 * rate, rel=1e-9)
    assert per_batch["formed_kmol"] == pytest.approx(2 * worst.moles["A"], rel=1e-9)


def test_the_gas_release_against_the_vent_capacity(tmp_path):
    def vent(capacity, recipe=RECIPE):
        flowsheet = vented.FLOWSHEET.replace(
            "hazard: {td24: 390,", f"hazard: {{vent_capacity: {capacity}, td24: 390,"
        )
        report = screen(_vent_plant(tmp_path / f"{capacity}{bool(recipe)}", flowsheet, recipe).root)
        (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"]
        return report.entries[0].gas_release, finding

    gas, finding = vent(1000.0)
    m3_h = gas["rate_m3_h"]
    assert gas["vent_capacity_m3_h"] == 1000.0
    assert gas["capacity_ratio"] == pytest.approx(m3_h / 1000.0, rel=1e-12)
    assert finding.level == "info" and "(within it)" in finding.message
    gas, finding = vent(round(m3_h / 2, 6))
    assert gas["capacity_ratio"] == pytest.approx(2.0, rel=1e-5)
    assert finding.level == "warning" and "(above it)" in finding.message
    gas, finding = vent(1000.0, recipe=None)
    assert "capacity_ratio" not in gas
    assert finding.level == "warning" and "not compared" in finding.message
    text = hazard_text(screen(_vent_plant(tmp_path / "t", recipe=RECIPE).root))
    assert "  gas release at the MTSR: " in text and "formed by R1 run to completion" in text


def test_an_unvented_semibatch_has_no_gas_release(tmp_path):
    report = screen(dosed._plant(tmp_path).root)
    assert report.entries[0].gas_release is None
    assert not [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"]


#: the vented plant as a batch: 1 kmol A in 5 kmol S charged (per hour of flows)
BATCH = (
    vented.FLOWSHEET.replace("reactor: semibatch", "reactor: batch")
    .replace("batch: {dosing: [{stream: S2, time: 3600}], ", "batch: {time: 3600, ")
    .replace("{id: dose, direction: in}, ", "")
    .replace("    from: G.out\n    to: R.dose", "    from: G.out\n    to: P2.in")
    .replace("products:\n", "products:\n  - {id: P2, ports: [{id: in, direction: in}]}\n")
    .replace("flow: {value: 5, provenance: given}", "flow: {value: 6, provenance: given}")
    .replace("values: {S: 1.0}", "values: {S: 0.8333333333333334, A: 0.16666666666666666}")
)


def test_a_vented_batch_has_its_gas_release_at_the_start(tmp_path):
    """A batch of 1 kmol A in 5 kmol S: cooling fails at the start, the MTSR is 300 + 1e5 /
    (6 x 150) K, and G forms at k n_A0 = 0.01 kmol/s (on the flowsheet's hour of flows)."""
    (entry,) = screen(_vent_plant(tmp_path, BATCH).root).entries
    assert entry.model == "batch"
    assert entry.mtsr == pytest.approx(300.0 + 1e5 / 900.0, rel=1e-9)
    assert entry.gas_release["rate_kmol_s"] == pytest.approx(0.01, rel=1e-9)
    assert entry.gas_release["formed_kmol"] == pytest.approx(1.0, rel=1e-9)
    assert entry.gas_release["rate_from"] == "the worst moment's content"


#: two hours of the batch's flows (6 kmol/h of A and S, 44.05 kg/kmol) per batch
BATCH_RECIPE = RECIPE | {"batch_size": RECIPE["batch_size"] | {"value": 2 * 6 * 44.05}}


def _gas_plant(tmp_path, reactions, flowsheet=BATCH, intermediate=False):
    flowsheet = flowsheet.replace("    reactions: [R1]", "    reactions: [R1, R2]")
    ws = _vent_plant(tmp_path, flowsheet, BATCH_RECIPE)
    (ws.root / "process/reactions.yaml").write_text(
        "schema: cheme/reactions/v1\nkind: reactions\nreactions:\n" + reactions
    )
    if intermediate:
        path = ws.root / "process/materials.yaml"
        path.write_text(
            path.read_text()
            .replace(
                "templates:",
                "  - {id: I, name: I, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,"
                "\n     liquid_heat_capacity: 150, normal_boiling_point: 400}\ntemplates:",
            )
            .replace("components: [A, B, S, G]}", "components: [A, B, S, G, I]}")
        )
    return screen(ws.root)


def _reaction(rid, stoichiometry, heat, order="A"):
    """A liquid reaction, first order in *order*, k 0.01 1/s (the pre-exponential factor A)."""
    return (
        f"  - {{id: {rid}, stoichiometry: {stoichiometry}, phase: liquid,\n"
        f"     heat_of_reaction: {{value: {heat}, provenance: assumed}},\n"
        "     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.01},\n"
        f"            orders: {{{order}: 1}}, provenance: assumed}}}}\n"
    )


def test_the_gas_release_counts_gas_formed_from_the_runaways_product(tmp_path):
    """R1: A -> I (100 MJ/kmol) forms no gas, R2: I -> B + G forms it from R1's product. The
    worst moment (the fresh charge) holds no I, so G forms at 0 there; once R1 ran to
    completion the vessel holds 1 kmol of I: G forms at k n_I = 0.01 kmol/s at the MTSR, and R2
    forms 1 kmol of it. Until this fix the release was about 0, 'within' any vent capacity."""
    reactions = _reaction("R1", "{A: -1, I: 1}", -100000) + _reaction(
        "R2", "{I: -1, B: 1, G: 1}", -1000, order="I"
    )
    flowsheet = BATCH.replace("hazard: {td24: 390,", "hazard: {vent_capacity: 100, td24: 390,")
    report = _gas_plant(tmp_path, reactions, flowsheet, intermediate=True)
    (entry,) = report.entries
    gas = entry.gas_release
    assert entry.mtsr == pytest.approx(300.0 + 1e5 / 900.0, rel=1e-9)
    # two hours of flows per batch (the recipe): 2 kmol of A
    assert gas["rate_kmol_s"] == pytest.approx(2 * 0.01, rel=1e-9)
    assert gas["rate_m3_h"] == pytest.approx(0.02 * R * entry.mtsr / 101.325 * 3600, rel=1e-9)
    assert gas["rate_from"] == "the content after R1"
    assert (gas["formed_by"], gas["formed_from"]) == ("R2", "the content after R1")
    assert gas["formed_kmol"] == pytest.approx(2.0, rel=1e-9)
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"]
    assert finding.level == "warning" and "(above it)" in finding.message
    assert "(the content after R1)" in hazard_text(report)


def test_the_gas_formed_counts_only_the_chosen_reactions(tmp_path):
    """R1: A -> B + G (100 MJ/kmol) and R2: A -> B + 2 G (50 MJ/kmol) in parallel: by default
    R2 forms the most gas, 2 kmol per kmol of A; with hazard.reactions: [R1] R1 alone counts,
    1 kmol (until this fix R2's 2 kmol, a reaction the user left out)."""
    reactions = _reaction("R1", "{A: -1, B: 1, G: 1}", -100000) + _reaction(
        "R2", "{A: -1, B: 1, G: 2}", -50000
    )
    (entry,) = _gas_plant(tmp_path / "a", reactions).entries
    assert entry.gas_release["formed_by"] == "R2"
    assert entry.gas_release["formed_kmol"] == pytest.approx(2 * 2.0, rel=1e-9)
    flowsheet = BATCH.replace("hazard: {td24: 390,", "hazard: {reactions: [R1], td24: 390,")
    (entry,) = _gas_plant(tmp_path / "b", reactions, flowsheet).entries
    assert entry.counted_reactions == ["R1"]
    assert entry.gas_release["formed_by"] == "R1"
    assert entry.gas_release["formed_kmol"] == pytest.approx(2 * 1.0, rel=1e-9)
    assert entry.gas_release["formed_from"] == "the worst moment's content"


def test_the_new_hazard_fields_load_and_keep_dumps(tmp_path):
    hazard = ReactionHazard.model_validate(
        {"reactions": ["R1"], "vent_capacity": 50, "provenance": "assumed"}
    )
    assert hazard.reactions == ["R1"] and hazard.vent_capacity == 50
    with pytest.raises(ValueError):
        ReactionHazard.model_validate({"vent_capacity": 0, "provenance": "assumed"})
    plain_dump = ReactionHazard.model_validate({"mtt": 300, "provenance": "assumed"}).model_dump()
    assert "reactions" not in plain_dump and "vent_capacity" not in plain_dump
