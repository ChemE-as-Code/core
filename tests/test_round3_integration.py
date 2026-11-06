"""The three features of round 3 together: a dose's heat of solution and the charge's heat-up
(ADR 0063), a batch still's column and its condenser (ADR 0061), a batch's vent vapour and its
vent condenser (ADR 0062). A vented semi-batch with a dosed heat of solution and a vent
condenser holds both terms in its duty, its vent condenser's duty goes on its own stream and
the energy over the vessel and the condenser closes; an adiabatic one takes both into its
balance; a still with a column, heat_up, the vessel's metal and a condenser_port gives its
reboiler the boil-up, the heat-up and the metal, its condenser the boil-up's latent heat only.
(A node cannot be both a still and a batch: ``cheme.process-still`` refuses a still that is
also a reactor, so no node has both condensers.)"""

import shutil

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.thermochemistry import R
from chemeascode.domains.process.batch_still import still_report
from chemeascode.domains.process.duties import (
    still_condenser_target,
    target,
    vent_condenser_target,
)
from chemeascode.domains.process.model import balance_of, load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.schema import Batch
from chemeascode.domains.process.stirred_tank import Dose, solve_batch
from chemeascode.foundation.workspace import Workspace
from tests import test_batch_rectification as rectification
from tests import test_vent_vapour as vapour
from tests.test_semibatch_vent import CP, DOSING, HEAT, V, _reactions

P = vapour.P
DHVAP = vapour.DHVAP
SOLUTION = 20000.0  # kJ/kmol of A released as it mixes in (heat_of_solution -20000)
T_C = 270.0  # K, the vent condenser's outlet


def _dose(solution=SOLUTION, t=300.0):
    return Dose({"A": 1.0}, t, [(0.0, DOSING, 1.0)], {}, solution)


# -- the semi-batch with a heat of solution, the vent's vapour and its condenser ----------------


def test_a_semibatchs_heat_of_solution_and_vent_vapour_close_with_its_vent_condenser():
    """Isothermal at 300 K, S volatile, a vent condenser at 270 K returning its condensate:
    the duty holds the reaction, the dose's heat of solution, the latent heat the gas carries
    off and the condensate warmed back; the heat of solution changes neither the vapour nor
    the condensate. Over the vessel and the condenser together, jacket plus condenser is
    H(out) - H(in): the reactions, the heat of solution, the vapour past the condenser
    (condensed at 300 K, cooled as liquid to 270 K, evaporated again: dHvap + cp (T_c - T))
    and the gas G cooled to 270 K."""
    phase = vapour._phase("S", vapour._clausius(50.0, 4000.0), condenser=T_C)
    vent = vapour.VAPOUR | {"condenser": {"temperature": T_C, "provenance": "assumed"}}
    mixed = vapour._run(vent, phase, doses=[_dose()])
    plain = vapour._run(vent, phase, doses=[_dose(None)])
    terms = mixed.heat_terms
    assert terms["solution"] == pytest.approx(-SOLUTION, rel=1e-12)
    assert "solution" not in plain.heat_terms
    carried, condensed = mixed.vapour["S"], mixed.condensate["S"]
    assert carried > 0 and condensed > 0
    assert terms["vent vapour"] == pytest.approx(DHVAP * carried, rel=1e-12)
    assert terms["condensate return"] == pytest.approx(condensed * 150.0 * (300.0 - T_C))
    # the heat of solution of an isothermal batch changes its heat only
    assert mixed.vapour == plain.vapour and mixed.condensate == plain.condensate
    assert mixed.extents == plain.extents and mixed.condenser_heat == plain.condenser_heat
    for name in ("reaction", "vent vapour", "condensate return"):
        assert terms[name] == pytest.approx(plain.heat_terms[name], rel=1e-12)
    assert sum(terms.values()) == pytest.approx(sum(plain.heat_terms.values()) - SOLUTION)
    # the energy over the vessel and its condenser closes
    extent = mixed.extents["R1"]
    assert terms["reaction"] == pytest.approx(HEAT * extent, rel=1e-2)
    past = mixed.vent["S"]
    gas = mixed.vent["G"]
    assert past == pytest.approx(carried - condensed, rel=1e-12)
    jacket = sum(terms.values())
    cooled = -mixed.condenser_heat
    h_out_less_in = (
        terms["reaction"]
        - SOLUTION
        + past * (DHVAP + 150.0 * (T_C - 300.0))
        + gas * 3.5 * R * (T_C - 300.0)
    )
    assert jacket + cooled == pytest.approx(h_out_less_in, rel=1e-9)


def test_an_adiabatic_semibatch_takes_the_heat_of_solution_and_the_vapour_into_its_balance():
    """A fast reaction (k 1/s against 3600 s of dosing) consumes A as it is dosed: a heat of
    solution released at the dose's rate heats the content as a heat of reaction that much
    larger would, with the vapour's evaporative cooling in both. Without the vapour the batch
    runs hotter, without the heat of solution colder."""
    phase = vapour._phase("ABS", vapour._constant(30.0))

    def adiabatic(heat, solution, vented=vapour.VAPOUR, vent_phase=phase):
        return solve_batch(
            _reactions(1.0, heat),
            {"S": 5.0},
            300.0,
            P,
            Batch.model_validate(
                {
                    "provenance": "assumed",
                    "heat": "adiabatic",
                    "dosing": [{"stream": "D", "time": DOSING}],
                    "vent": vented,
                }
            ),
            {"G": vapour.GAS},
            Liquid(V),
            CP,
            doses=[_dose(solution)],
            vent_phase=vent_phase,
        )

    both = adiabatic(HEAT, SOLUTION)
    folded = adiabatic(HEAT - SOLUTION, None)
    assert sum(both.vapour.values()) > 0
    assert both.temperature == pytest.approx(folded.temperature, abs=0.05)
    dry = adiabatic(HEAT, SOLUTION, {"stream": "V", "components": ["G"]}, None)
    unmixed = adiabatic(HEAT, None)
    assert dry.temperature > both.temperature + 5
    assert unmixed.temperature < both.temperature - 5
    # without the vapour, the closed form: C_end T_end = C_0 T_0 + C_d T_d + (-dH) xi + Q_sol
    expected = (5.0 * 150.0 * 300.0 + 150.0 * 300.0 - HEAT * dry.extents["R1"] + SOLUTION) / (
        6.0 * 150.0
    )
    assert dry.temperature == pytest.approx(expected, rel=1e-6)


JACKET = (
    "  - id: CW2\n    category: utility\n    utility: {kind: cooling_water}\n"
    "    ports: [{id: r, direction: in, kind: energy}]\n"
)
MIXING = "{stream: S2, time: 3600, heat_of_solution: {values: {A: -20000}, provenance: assumed}}"


def _vented_mixed_plant(tmp_path):
    """The vented semi-batch of the vent tests with its vent condenser on QC (port qc), a
    jacket Q1 (port q) to its own cooling water and a dose with its heat of solution."""
    text = (
        vapour._vapour_flowsheet()
        .replace("{stream: S2, time: 3600}", MIXING)
        .replace("products:\n", "products:\n" + JACKET)
        .replace(
            "{id: qc, direction: out, kind: energy}",
            "{id: qc, direction: out, kind: energy}, {id: q, direction: out, kind: energy}",
        )
    )
    text += "  - {id: Q1, kind: energy, from: R.q, to: CW2.r}\n"
    assert MIXING in text and "R.q," in text
    return vapour._plant(tmp_path, text)


def test_propagate_writes_the_jacket_with_both_terms_and_the_vent_condenser_on_its_own(tmp_path):
    ws = _vented_mixed_plant(tmp_path)
    assert not vapour._errors(ws), vapour._errors(ws)
    process, _ = load(ws.root)
    node = process.nodes["R"]
    # the jacket's default is its one heat stream once the vent condenser's is set apart
    jacket, why = target(process, node)
    assert jacket is not None and jacket.stream.id == "Q1", why
    cold, _ = vent_condenser_target(process, node)
    assert cold.stream.id == "QC" and cold.chosen == "vent.condenser.energy_port"
    assert still_condenser_target(process, node) == (None, "")
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level != "info"], [
        f.format() for f in result.findings
    ]
    states = vapour._states(ws)
    q1, qc = states["Q1"]["duty"], states["QC"]["duty"]
    assert q1["provenance"] == qc["provenance"] == "calculated"
    assert "semibatch duty R" in q1["source"] and "vent condenser duty R" in qc["source"]
    (row,) = reactor_report(ws.root).reactors
    duty = row["model_duty"]
    terms = duty["terms_kW"]
    assert terms["solution"] == pytest.approx(-SOLUTION / 3600.0, rel=1e-9)
    assert terms["vent vapour"] > 0 and terms["condensate return"] > 0
    assert "heat of solution as they mix in" in duty["basis"]
    assert "the vapour the vent gas carries off" in duty["basis"]
    # out of R to the cooling water: the jacket removes minus the duty into the vessel
    assert q1["value"] == pytest.approx(-sum(terms.values()), rel=1e-5)
    assert duty["stream"]["id"] == "Q1"
    vent = row["tank"]["vent"]["condenser_duty"]
    assert vent["stream"]["id"] == "QC"
    assert qc["value"] == pytest.approx(-vent["heat_in_kW"], rel=1e-5) and qc["value"] > 0
    # the vent condenser's duty is not in the jacket's
    assert "condensation" not in terms and "condensation" in vent["terms_kW"]
    process, _ = load(ws.root)
    assert balance_of(process, "R", "design").status == "ok"
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    # a changed heat of solution makes the jacket's duty stale, not the vent condenser's
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("A: -20000", "A: -30000"))
    process, _ = load(ws.root)
    stale = [f.message for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert any("Q1" in m for m in stale), stale
    assert not any("QC" in m for m in stale), stale


# -- the still with a column, heat_up, the vessel's metal and a condenser_port ------------------

CP_ADDED = {"ACCL": 117.0, "PCL3": 120.0, "ACOH": 123.0}


def _rectifier(tmp_path, metal=True):
    """The batch-rectification example with heat_up, condenser_port: condenser, liquid heat
    capacities and (*metal*) a still pot with metal_heat_capacity; its duties cleared."""
    root = tmp_path / "plant"
    shutil.copytree(rectification.EXAMPLE, root)
    flowsheet = root / "process/flowsheet.yaml"
    lines = []
    for line in flowsheet.read_text().splitlines():
        if line.startswith("  - {id: Q"):
            line = line.split(", state:")[0] + "}"
        lines.append(line)
        if line == "    still:":
            lines += ["      heat_up: true", "      condenser_port: condenser"]
    flowsheet.write_text("\n".join(lines) + "\n")
    materials = root / "process/materials.yaml"
    text = materials.read_text()
    for name, cp in CP_ADDED.items():
        head = f"  - id: {name}\n"
        at = text.index(head)
        end = text.index("    heat_of_vaporization:", at)
        text = text[:end] + f"    liquid_heat_capacity: {cp}\n" + text[end:]
    text = text.replace("molar_mass: 81.995}", "molar_mass: 81.995, liquid_heat_capacity: 100}")
    materials.write_text(text)
    if metal:
        path = root / "process/recipe.yaml"
        recipe = yaml.safe_load(path.read_text())
        recipe["unit_procedures"][0]["vessel"] = {
            "volume": 3.0,
            "metal_heat_capacity": 2000.0,
            "provenance": "assumed",
        }
        path.write_text(yaml.safe_dump(recipe, sort_keys=False))
    return Workspace(root)


@pytest.mark.parametrize("metal", [False, True])
def test_a_rectifiers_reboiler_takes_the_heat_up_its_condenser_the_boil_up_only(tmp_path, metal):
    ws = _rectifier(tmp_path, metal)
    process, _ = load(ws.root)
    assert not [f.format() for f in rules(process) if f.level == "error"]
    node = process.nodes["ST1"]
    reboiler, _ = target(process, node)
    condenser, _ = still_condenser_target(process, node)
    assert reboiler.stream.id == "Q1" and condenser.stream.id == "Q2"
    assert condenser.chosen == "condenser_port"
    assert vent_condenser_target(process, node) == (None, "")  # a still has no vent condenser
    result = run(ws, process, "design", write=True)
    assert not [f for f in result.findings if f.level != "info"], [
        f.format() for f in result.findings
    ]
    (unit,) = still_report(ws.root).units
    sol = unit["solution"]
    terms = sol["duty_terms_kW"]
    assert terms["charge heat-up"] > 0 and terms["boil-up"] > 0
    assert ("vessel metal" in terms) is metal
    if metal:  # the metal follows the content from the charge's temperature (heat_up)
        assert terms["vessel metal"] > 0
        assert any(
            "the vessel's metal (DISTIL, 2000 kJ/K) heated with the content from its charge's" in a
            for a in unit["assumptions"]
        )
    # the column's assumptions say what the reboiler's duty holds, and the condenser's not
    assumptions = unit["assumptions"]
    assert not any(a.startswith("constant boil-up from the start: no heat-up") for a in assumptions)
    assert any(a.startswith("heat_up: the charge heated") for a in assumptions)
    (reboiler,) = [a for a in assumptions if a.startswith("the reboiler's duty")]
    assert "and the heat-up" in reboiler
    assert reboiler.endswith("the condenser's the latent heat of the vapour condensed only")
    streams = {s.id: s for s in load(ws.root)[0].flowsheet.streams}
    q1 = streams["Q1"].state["design"].duty
    q2 = streams["Q2"].state["design"].duty
    assert q1.provenance == q2.provenance == "calculated"
    # the reboiler: the boil-up, the charge's heat-up (and the metal)
    assert q1.value == pytest.approx(sum(terms.values()), rel=1e-5)
    assert q1.value == pytest.approx(sol["year_average_duty_kW"], rel=1e-5)
    # the condenser: the boil-up's latent heat only (out of the still to the cooling water)
    assert q2.value == pytest.approx(terms["boil-up"], rel=1e-5)
    assert q1.value - q2.value == pytest.approx(
        terms["charge heat-up"] + terms.get("vessel metal", 0.0), rel=1e-4
    )
    assert "still condenser duty ST1" in q2.source and "still duty ST1" in q1.source
