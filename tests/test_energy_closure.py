"""Energy checks: the simulation's energy audit (domains/process/simulation/energy.py), the
flowsheet's energy balances (domains/process/energy.py), boundary completeness
(domains/assessment/flows.py boundary_gaps) and ``cheme process energy``.

The simulator results here are hand-made stand-ins (no DWSIM): flows, enthalpies and duties are
chosen so that every balance can be checked by hand (the arithmetic is in each test). They are
bookkeeping numbers, not property data. The live DWSIM tests (test_process_simulate.py,
CHEME_DWSIM_TESTS=1) run the same audit on real results.
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chemeascode.domains.assessment.flows import boundary_gaps, terminals
from chemeascode.domains.process.energy import energy_balances, energy_report
from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.model import rules
from chemeascode.domains.process.simulation import energy
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _copy(tmp_path: Path, name: str) -> Workspace:
    shutil.copytree(EXAMPLES / name, tmp_path / name)
    return Workspace(tmp_path / name)


def _edit(ws: Workspace, path: str, edit) -> None:
    file = ws.root / path
    data = yaml.safe_load(file.read_text())
    edit(data)
    file.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))


def _translate(ws: Workspace):
    process, _ = load_process(ws.root)
    sim, doc, found = load(ws.root)
    assert not found
    model = translate(process, sim, doc, "design").model
    assert model is not None
    return process, sim, doc, model


def _s(t: float, m: float, h: float | None, vf: float = 0.0) -> dict:
    return {"temperature_K": t, "mass_flow_kg_s": m, "mass_enthalpy_kJ_kg": h, "vapor_fraction": vf}


# -- simulation audit: the depropanizer -------------------------------------------------------


def separation_out(**changes) -> dict:
    """The depropanizer, 1 kg/s of feed. Valve and flash adiabatic (S1, S2 at 0 kJ/kg; S3 0.2
    kg/s at 50, S4 0.8 kg/s at -12.5: 10 - 10 = 0). E1 exchanges 100 kW: S4 300 -> 350 K
    (h 112.5 = -12.5 + 100 / 0.8); hot oil 2 kg/s 420 -> 380 K (h 200 -> 150). C1 reboils 300
    kW, condenses 280: 0.8 x 112.5 = 90 in, S6 0.3 kg/s at 100 (30) and S7 0.5 kg/s at 160 (80)
    out = 90 + 300 - 280. Plant: 400 in (S1 0, H1 400), 420 out (S3 10, S6 30, S7 80, H2 300) =
    20 kW net heat."""
    streams = {
        "S1": _s(310, 1.0, 0.0),
        "S2": _s(305, 1.0, 0.0, 0.2),
        "S3": _s(305, 0.2, 50.0, 1.0),
        "S4": _s(300, 0.8, -12.5),
        "S5": _s(350, 0.8, 112.5),
        "S6": _s(290, 0.3, 100.0),
        "S7": _s(360, 0.5, 160.0),
        "H1": _s(420, 2.0, 200.0),
        "H2": _s(380, 2.0, 150.0),
    }
    for sid, values in changes.items():
        streams[sid] = {**streams[sid], **values}
    return {
        "converged": True,
        "streams": streams,
        "units": {
            "V1": {},
            "D1": {"duty_kW": 0.0},
            "E1": {"duty_kW": 100.0},
            "C1": {"condenser_kW": 280.0, "reboiler_kW": 300.0},
        },
    }


def test_closure_per_unit_and_plant(tmp_path):
    process, sim, doc, model = _translate(_copy(tmp_path, "process-separation"))
    findings, entry, lines = energy.audit(process, sim, doc, model, separation_out())
    units = {r["id"]: r for r in entry["closure"]["units"]}
    assert {k: r["status"] for k, r in units.items()} == dict.fromkeys(
        ("V1", "D1", "E1", "C1"), "ok"
    )
    assert units["C1"]["heat_in_kW"] == pytest.approx(20.0)
    plant = entry["closure"]["plant"]
    assert plant["status"] == "ok" and plant["residual_kW"] == pytest.approx(0.0, abs=1e-9)
    assert plant["feeds"] == ["H1", "S1"] and plant["products"] == ["H2", "S3", "S6", "S7"]
    assert (plant["enthalpy_in_kW"], plant["enthalpy_out_kW"]) == pytest.approx((400.0, 420.0))
    assert entry["reference"]["formation_enthalpy_included"] is False
    assert any(line.startswith("energy closure (plant): ok") for line in lines)
    assert not [f for f in findings if f.level == "warning"]


def test_unit_and_plant_imbalance_is_reported(tmp_path):
    """S7 at 170 instead of 160 kJ/kg: C1 and the plant are 5 kW off (0.5 kg/s x 10)."""
    process, sim, doc, model = _translate(_copy(tmp_path, "process-separation"))
    findings, entry, _ = energy.audit(
        process, sim, doc, model, separation_out(S7={"mass_enthalpy_kJ_kg": 170.0})
    )
    warned = [f for f in findings if f.rule == "cheme.process-sim-energy-unbalanced"]
    assert [f.ids for f in warned] == [["C1"], []]
    assert entry["closure"]["plant"]["residual_kW"] == pytest.approx(5.0)
    assert "C1" in warned[0].message and warned[0].file == "process/simulation.yaml"


def test_no_enthalpies_is_not_evaluable(tmp_path):
    process, sim, doc, model = _translate(_copy(tmp_path, "process-separation"))
    out = separation_out()
    for values in out["streams"].values():
        values["mass_enthalpy_kJ_kg"] = None
    findings, entry, _ = energy.audit(process, sim, doc, model, out)
    assert entry["closure"]["plant"]["status"] == "not-evaluable"
    assert [f.rule for f in findings if f.level != "info"] == []
    assert "cheme.process-sim-energy-not-evaluable" in {f.rule for f in findings}


def test_recovered_heat_is_not_counted_as_utility(tmp_path):
    """E1 is process to process: its 100 kW are recovered; the utilities are C1's reboiler
    (300, hot) and condenser (280, cold). With the hot oil declared a utility, E1's duty is hot
    utility instead and nothing is recovered."""
    ws = _copy(tmp_path, "process-separation")
    process, sim, doc, model = _translate(ws)
    _, entry, _ = energy.audit(process, sim, doc, model, separation_out())
    totals = entry["utilities"]["totals_kW"]
    assert totals == pytest.approx(
        {
            "hot_utility": 300.0,
            "cold_utility": 280.0,
            "power_in": 0.0,
            "power_out": 0.0,
            "recovered": 100.0,
        }
    )
    duties = {(d["id"], d["role"]): d for d in entry["utilities"]["duties"]}
    assert duties[("C1", "reboiler")]["terminal"] == "STEAM"
    assert duties[("C1", "condenser")]["terminal"] == "CW"
    assert duties[("E1", "exchange")]["class"] == "recovered"

    _edit(ws, "process/flowsheet.yaml", lambda d: d["feeds"][1].update(category="utility"))
    process, sim, doc, model = _translate(ws)
    _, entry, _ = energy.audit(process, sim, doc, model, separation_out())
    totals = entry["utilities"]["totals_kW"]
    assert totals["recovered"] == 0.0 and totals["hot_utility"] == pytest.approx(400.0)


def test_condenser_reboiler_duty_is_recovered():
    """A reboiler heated by another column's condenser: both duties are recovered heat."""
    model = {
        "units": [
            {
                "id": "HP",
                "type": "distillation_column",
                "inlets": [],
                "outlets": [],
                "energies": {},
                "spec": {},
            },
            {
                "id": "LP",
                "type": "distillation_column",
                "inlets": [],
                "outlets": [],
                "energies": {},
                "spec": {"heat_integration": {"condenser_of": "HP"}},
            },
        ]
    }
    units = {"HP": {"condenser_kW": 500.0}, "LP": {"reboiler_kW": 500.0}}
    found = energy._utilities(model, {"streams": {}}, units, {}, {})
    assert found["totals_kW"]["recovered"] == pytest.approx(500.0)
    assert found["totals_kW"]["hot_utility"] == found["totals_kW"]["cold_utility"] == 0.0


# -- simulation audit: specified splits (component separators) ---------------------------------
#
# A component separator splits by given recoveries: nothing in it conserves energy. Its
# imbalance is stated (enthalpy out minus in), never judged, and the plant closes with it
# (ADR 0038). Bookkeeping numbers, not property data.


def _specified_split(ws: Workspace) -> None:
    """The depropanizer with D1 as a component separator (specified split) instead of a flash."""

    def separator(d):
        for step in d["steps"]:
            if step["id"] == "D1":
                step["class"] = "SeparatingByPhysicalProcess"

    def recoveries(d):
        d["specs"]["D1"] = {
            "recoveries": {"C3": 0.9, "NC4": 0.05, "NC5": 0.01},
            "recovery_outlet": "vapour",
            "basis_source": "test bookkeeping",
        }

    _edit(ws, "process/flowsheet.yaml", separator)
    _edit(ws, "process/simulation.yaml", recoveries)


def test_specified_split_is_stated_and_the_plant_closes(tmp_path):
    """D1 a specified split; S3 at 100 kJ/kg instead of 50: D1's outlets carry 0.2 x 100 + 0.8 x
    -12.5 = 10 kW, its inlet S2 0 kW, so it states +10 kW (enthalpy out minus in). DWSIM's
    EnergyImb given as -10 kW is the opposite sign (in minus out). Plant: 400 kW in (S1 0, H1
    400), 430 out (S3 20, S6 30, S7 80, H2 300); C1's net heat 20 kW plus D1's stated 10 kW:
    residual 0. Tolerance 0.1 + 0.01 x (20 + 10) + 1e-4 x 430 = 0.443 kW."""
    ws = _copy(tmp_path, "process-separation")
    _specified_split(ws)
    process, sim, doc, model = _translate(ws)
    assert {u["id"]: u["type"] for u in model["units"]}["D1"] == "component_separator"
    out = separation_out(S3={"mass_enthalpy_kJ_kg": 100.0})
    out["units"]["D1"] = {"duty_kW": -10.0}
    findings, entry, lines = energy.audit(process, sim, doc, model, out)
    units = {r["id"]: r for r in entry["closure"]["units"]}
    d1 = units["D1"]
    assert d1["status"] == "stated" and "residual_kW" not in d1
    assert d1["imbalance_kW"] == pytest.approx(10.0) and d1["heat_in_kW"] == pytest.approx(10.0)
    assert d1["sign_convention"] == energy.STATED_SIGN
    assert d1["simulator_imbalance_kW"] == -10.0 and d1["simulator_convention"] == "in-minus-out"
    plant = entry["closure"]["plant"]
    assert plant["status"] == "ok"
    assert plant["residual_kW"] == pytest.approx(0.0, abs=1e-9)
    assert plant["heat_in_kW"] == pytest.approx(20.0)  # the units' heat, without D1
    assert plant["stated_kW"] == pytest.approx(10.0)
    assert plant["stated"] == pytest.approx({"D1": 10.0})
    assert plant["tolerance_kW"] == pytest.approx(0.443)
    stated = [f for f in findings if f.rule == "cheme.process-sim-energy-stated"]
    assert [(f.level, f.ids) for f in stated] == [("info", ["D1"])]
    assert "enthalpy out minus in 10 kW" in stated[0].message
    assert not [f for f in findings if f.level == "warning"]
    assert not [f for f in findings if f.rule == "cheme.process-sim-energy-unsupported"]
    (plant_line,) = [x for x in lines if x.startswith("energy closure (plant)")]
    assert plant_line.startswith("energy closure (plant): ok") and "(D1 10;" in plant_line
    # the stated imbalance is no utility
    assert not [d for d in entry["utilities"]["duties"] if d["id"] == "D1"]


SPLIT = {
    "units": [
        {
            "id": "X1",
            "type": "component_separator",
            "inlets": ["A"],
            "outlets": ["B", "C"],
            "energies": {},
            "spec": {},
        }
    ]
}


def _split_out(b: float = 10.0, c: float | None = 10.0) -> dict:
    """A 1 kg/s at 0 kJ/kg; B and C 0.5 kg/s each at *b* and *c* kJ/kg: imbalance 0.5 (b + c)."""
    return {"streams": {"A": _s(300, 1.0, 0.0), "B": _s(300, 0.5, b), "C": _s(300, 0.5, c)}}


@pytest.mark.parametrize(
    ("simulator", "convention"),
    [(10.0, "out-minus-in"), (-10.0, "in-minus-out"), (3.0, "differs"), (None, "not-reported")],
)
def test_the_simulators_sign_is_recorded_not_relied_on(simulator, convention):
    """X1 states +10 kW (B and C 5 kW each, A 0) whatever DWSIM's EnergyImb says; the unit
    tolerance is 0.1 + 1e-4 x 10 = 0.101 kW, which decides how EnergyImb is read."""
    units = {"X1": {} if simulator is None else {"duty_kW": simulator}}
    closure, findings = energy._closure(SPLIT, _split_out(), units, lambda *a: None)
    (row,) = closure["units"]
    assert row["imbalance_kW"] == pytest.approx(10.0)
    assert row["tolerance_kW"] == pytest.approx(0.101)
    assert row["simulator_convention"] == convention
    assert closure["plant"]["status"] == "ok"
    assert closure["plant"]["stated_kW"] == pytest.approx(10.0)
    assert [f.rule for f in findings] == ["cheme.process-sim-energy-stated"]


def test_a_negligible_imbalance_is_stated_without_a_finding():
    closure, findings = energy._closure(
        SPLIT, _split_out(0.0, 0.0), {"X1": {"duty_kW": 0.05}}, lambda *a: None
    )
    (row,) = closure["units"]
    assert row["status"] == "stated" and row["simulator_convention"] == "negligible"
    assert closure["plant"]["status"] == "ok" and not findings


def test_a_split_without_enthalpies_leaves_the_plant_not_evaluable():
    closure, findings = energy._closure(SPLIT, _split_out(c=None), {"X1": {}}, lambda *a: None)
    (row,) = closure["units"]
    assert row["status"] == "not-evaluable" and row["missing"] == ["C"]
    plant = closure["plant"]
    assert plant["status"] == "not-evaluable" and "residual_kW" not in plant
    assert "X1" in plant["reasons"][0] and "no enthalpy for C" in plant["reasons"][0]
    assert not findings


def test_a_plant_imbalance_with_a_stated_split_names_it():
    """A heater H1 before X1 claims 5 kW but A0 and A carry the same enthalpy: H1 and the plant
    are 5 kW off (residual -5); X1's stated 10 kW is named and not part of the residual."""
    model = copy.deepcopy(SPLIT)
    model["units"].insert(
        0,
        {"id": "H1", "type": "heater", "inlets": ["A0"], "outlets": ["A"], "energies": {}},
    )
    out = _split_out()
    out["streams"]["A0"] = _s(300, 1.0, 0.0)
    units = {"H1": {"duty_kW": 5.0}, "X1": {"duty_kW": 10.0}}
    closure, findings = energy._closure(model, out, units, lambda *a: None)
    plant = closure["plant"]
    assert plant["status"] == "imbalance" and plant["residual_kW"] == pytest.approx(-5.0)
    unbalanced = [f for f in findings if f.rule == "cheme.process-sim-energy-unbalanced"]
    (warned,) = [f for f in unbalanced if not f.ids]
    assert "plus 10 kW stated by specified splits (X1)" in warned.message


def _audit_of(plant: dict, units: list[dict]) -> dict:
    return {
        "reference": dict(energy.REFERENCE),
        "closure": {"units": units, "plant": plant},
        "exchangers": [],
        "utility_levels": [],
        "utilities": {
            "totals_kW": dict.fromkeys(
                ("hot_utility", "cold_utility", "power_in", "power_out", "recovered"), 0.0
            )
        },
    }


def test_energy_text_shows_stated_splits_and_old_records():
    from chemeascode.domains.process.energy import (
        SEPARATOR_SIGN_UNKNOWN,
        EnergyReport,
        energy_text,
    )

    closure, _ = energy._closure(SPLIT, _split_out(), {"X1": {"duty_kW": 10.0}}, lambda *a: None)
    text = energy_text(EnergyReport("design", [], _audit_of(closure["plant"], closure["units"])))
    assert "plant closure ok" in text and "10 kW stated by specified splits" in text
    assert "X1: stated, imbalance 10 kW (enthalpy out minus in" in text
    old = {"status": "unsupported", "reasons": [f"X1: {SEPARATOR_SIGN_UNKNOWN}"]}
    row = {"id": "X1", "status": "unsupported", "reason": SEPARATOR_SIGN_UNKNOWN}
    text = energy_text(EnergyReport("design", [], _audit_of(old, [row])))
    assert "plant closure unsupported" in text and "simulate --fill again" in text


def test_maturity_passes_a_closure_with_stated_splits():
    from chemeascode.project.maturity import _energy_audit

    closure, _ = energy._closure(SPLIT, _split_out(), {"X1": {}}, lambda *a: None)
    data = {"cases": {"design": {"energy": _audit_of(closure["plant"], closure["units"])}}}
    req, _ = _energy_audit(object(), data, ["design"])
    assert req.status == "pass" and "stated" in req.detail and "X1" in req.detail


# -- simulation audit: reacting units on a heat-of-formation basis ------------------------------
#
# N2 + 3 H2 = 2 NH3 at an extent of 1 mol/s: inlet A 10 mol/s (2.5 N2, 7.5 H2), outlet B 8 mol/s
# (1.5 N2, 4.5 H2, 2 NH3). The formation term is 2 mol/s x dHf(NH3). With DWSIM's dHf(NH3) =
# -45898 kJ/kmol the term is -91.796 kW; A carries 100 kW and the reactor takes -50 kW (cooled),
# so a closing B carries 100 - 50 + 91.796 = 141.796 kW. The tolerance is 0.1 + 0.01 x 50 +
# 1e-4 x 141.796 (enthalpy out) + 1e-4 x 91.796 (formation) = 0.6233592 kW. Bookkeeping
# numbers, not property data.

REACTOR = {
    "property_package": "Peng-Robinson (PR)",
    "units": [
        {
            "id": "R1",
            "type": "conversion_reactor",
            "inlets": ["A"],
            "outlets": ["B"],
            "energies": {},
            "spec": {"reactions": [{"id": "SYN", "stoichiometry": {"N2": -1, "H2": -3, "NH3": 2}}]},
        }
    ],
}
TOLERANCE = 0.1 + 0.5 + 0.0141796 + 0.0091796


def _reacting(h_out: float = 141.796, n_in: float = 10.0) -> dict:
    a = {**_s(500, 1.0, 100.0, 1.0), "molar_flow_mol_s": n_in}
    a["mole_fractions"] = {"N2": 0.25, "H2": 0.75, "NH3": 0.0, "AR": 0.0}
    b = {**_s(600, 1.0, h_out, 1.0), "molar_flow_mol_s": 8.0}
    b["mole_fractions"] = {"N2": 1.5 / 8, "H2": 4.5 / 8, "NH3": 2 / 8, "AR": 0.0}
    return {"streams": {"A": a, "B": b}}


def _formation(
    nh3: float | None = -45898.0, dwsim: float | None = -45898.0, origin="declared", **changes
) -> dict:
    """Formation data as :func:`energy._formation_data` gives it (kJ/kmol): the project's
    (*nh3*, declared or chemicals' fallback) and DWSIM's (*dwsim*)."""
    source = {
        "declared": "declared in process/materials.yaml (given)",
        "chemicals": "chemicals fallback (nothing declared): dHf_298 ATCT_G (7664-41-7)",
    }[origin]
    components = {
        c: {
            "dHf_298_kJ_kmol": 0.0,
            "source": source,
            "origin": origin,
            "simulator_dHf_298_kJ_kmol": 0.0,
            "simulator_database": "ChemSep",
            "molar_mass": m,
        }
        for c, m in (("N2", 28.0), ("H2", 2.0), ("AR", 40.0))
    }
    components["NH3"] = {
        **components["N2"],
        "dHf_298_kJ_kmol": nh3,
        "simulator_dHf_298_kJ_kmol": dwsim,
        "molar_mass": 17.0,
    }
    if nh3 is None:
        components["NH3"].update(origin=None, source=None, missing="no ideal_gas in materials")
    return {
        "property_package": "Peng-Robinson (PR)",
        "reference_verified": True,
        "components": components,
        **changes,
    }


def _closure(out: dict, formation: dict | None, duty: float = -50.0, model: dict = REACTOR):
    return energy._closure(model, out, {"R1": {"duty_kW": duty}}, lambda *a: None, formation)


def test_reactor_closes_on_dwsims_formation_enthalpies():
    closure, findings = _closure(_reacting(), _formation())
    (row,) = closure["units"]
    assert row["status"] == "ok" and row["basis"] == "formation"
    assert row["formation_kW"] == pytest.approx(-91.796)
    assert row["residual_kW"] == pytest.approx(0.0, abs=1e-9)
    assert row["changes_mol_s"] == pytest.approx({"N2": -1.0, "H2": -3.0, "NH3": 2.0})
    assert row["tolerance_kW"] == pytest.approx(TOLERANCE)
    assert row["formation_data"]["status"] == "consistent"
    assert row["formation_data"]["difference_kW"] == pytest.approx(0.0, abs=1e-12)
    plant = closure["plant"]
    assert plant["basis"] == "formation" and plant["status"] == "ok"
    assert plant["formation_kW"] == pytest.approx(-91.796)
    assert not findings


def test_a_simulator_imbalance_is_an_imbalance():
    """B at 145 kW: 145 - 100 - 91.796 + 50 = 3.204 kW off."""
    closure, findings = _closure(_reacting(h_out=145.0), _formation())
    assert closure["units"][0]["status"] == "imbalance"
    assert closure["units"][0]["residual_kW"] == pytest.approx(3.204)
    assert [f.ids for f in findings if f.rule == "cheme.process-sim-energy-unbalanced"] == [
        ["R1"],
        [],
    ]


#: The data tolerance of this reactor: max(1 % of |-91.796| kW, 0.1 kW).
DATA_TOL = 0.91796


def test_declared_formation_enthalpies_that_differ_from_dwsims_are_a_warning():
    """Declared dHf(NH3) -45400 kJ/kmol against DWSIM's -45898 (bookkeeping numbers): the
    energy closes on DWSIM's (residual 0); the reaction heat on the declared values differs by
    2 x 498 / 1000 = 0.996 kW, above the data tolerance 0.918 kW: a warning, not an energy
    imbalance."""
    closure, findings = _closure(_reacting(), _formation(nh3=-45400.0))
    (row,) = closure["units"]
    assert row["status"] == "ok" and row["residual_kW"] == pytest.approx(0.0, abs=1e-9)
    data = row["formation_data"]
    assert data["status"] == "declared-differs"
    assert data["declared_difference_kW"] == pytest.approx(0.996)
    assert data["data_tolerance_kW"] == pytest.approx(DATA_TOL)
    assert data["project_formation_kW"] == pytest.approx(-90.8)
    (nh3,) = [x for x in data["components"] if x["id"] == "NH3"]
    assert nh3["difference_kJ_kmol"] == pytest.approx(498.0)
    assert nh3["share_kW"] == pytest.approx(0.996)
    assert closure["plant"]["status"] == "ok"
    (found,) = findings
    assert found.rule == "cheme.process-sim-formation-data" and found.level == "warning"
    assert "NH3 -45400 kJ/kmol declared in process/materials.yaml (given)" in found.message
    assert "-45898 in DWSIM (ChemSep): +498 kJ/kmol" in found.message


def test_a_nonzero_difference_within_the_data_tolerance_is_a_limitation():
    """-45558 declared (ATcT's value against DWSIM's JANAF one): 2 x 340 / 1000 = 0.68 kW,
    below 0.918 kW: not a failure, but never silently consistent."""
    closure, findings = _closure(_reacting(), _formation(nh3=-45558.0))
    data = closure["units"][0]["formation_data"]
    assert data["status"] == "within-tolerance"
    assert data["difference_kW"] == pytest.approx(0.68)
    assert data["limitations"] and "0.68 kW" in data["limitations"][0]
    (found,) = findings
    assert found.level == "info" and "+340 kJ/kmol" in found.message


@pytest.mark.parametrize(
    ("nh3", "verdict"), [(-45400.0, "declared-differs"), (-45558.0, "within-tolerance")]
)
def test_the_verdict_does_not_depend_on_the_reactors_duty(nh3, verdict):
    """The same data in an adiabatic reactor (duty 0, B at 100 + 91.796 kW) and a cooled one
    (duty -50 kW): the same verdict, the data tolerance depends on the reaction heat only."""
    adiabatic, _ = _closure(_reacting(h_out=191.796), _formation(nh3=nh3), duty=0.0)
    cooled, _ = _closure(_reacting(), _formation(nh3=nh3))
    for closure in (adiabatic, cooled):
        row = closure["units"][0]
        assert row["status"] == "ok"
        assert row["formation_data"]["status"] == verdict
        assert row["formation_data"]["data_tolerance_kW"] == pytest.approx(DATA_TOL)


def test_fallback_formation_enthalpies_that_differ_are_info():
    closure, findings = _closure(_reacting(), _formation(nh3=-45400.0, origin="chemicals"))
    data = closure["units"][0]["formation_data"]
    assert data["status"] == "fallback-differs" and data["limitations"]
    (found,) = findings
    assert found.rule == "cheme.process-sim-formation-data" and found.level == "info"
    assert "chemicals fallback (nothing declared)" in found.message
    assert "declared in" not in found.message


def test_equal_values_are_consistent():
    closure, findings = _closure(_reacting(), _formation())
    data = closure["units"][0]["formation_data"]
    assert data["status"] == "consistent" and not data["limitations"] and not findings


def test_a_component_without_a_project_value_leaves_the_declared_ones_compared():
    """H2 has no project value: NH3's declared -45400 is still compared (0.996 kW, a
    warning); H2 is a limitation. With no project value at all: not compared."""
    formation = _formation(nh3=-45400.0)
    formation["components"]["H2"].update(
        dHf_298_kJ_kmol=None, origin=None, source=None, missing="no ideal_gas in materials"
    )
    closure, findings = _closure(_reacting(), formation)
    (row,) = closure["units"]
    data = row["formation_data"]
    assert row["status"] == "ok" and data["status"] == "declared-differs"
    assert data["missing"] == ["H2"] and "project_formation_kW" not in data
    assert data["declared_difference_kW"] == pytest.approx(0.996)
    assert [f.level for f in findings] == ["warning", "info"]
    assert "no project formation enthalpy for H2" in findings[1].message
    for c in ("N2", "H2", "NH3"):
        formation["components"][c].update(dHf_298_kJ_kmol=None, origin=None, missing="none")
    closure, _ = _closure(_reacting(), formation)
    data = closure["units"][0]["formation_data"]
    assert data["status"] == "not-compared" and data["missing"] == ["N2", "H2", "NH3"]


def test_molar_flows_from_mass_flow_and_molar_masses():
    """Without the simulator's molar flow: A is 1 kg/s at 0.25 x 28 + 0.75 x 2 = 8.5 kg/kmol,
    117.647 mol/s; B keeps 8 mol/s. The formation term follows the flows: 2 mol/s of NH3 is
    still made (B's 2 mol/s, A has none)."""
    out = _reacting()
    del out["streams"]["A"]["molar_flow_mol_s"]
    closure, _ = _closure(out, _formation())
    row = closure["units"][0]
    assert row["changes_mol_s"]["N2"] == pytest.approx(1.5 - 0.25 * 1000 / 8.5)
    assert row["formation_kW"] == pytest.approx(-91.796)


@pytest.mark.parametrize(
    ("formation", "reason"),
    [
        (None, "no formation data"),
        (
            _formation(property_package="NRTL", reference_verified=False),
            "DWSIM's enthalpy reference for 'NRTL' is not verified",
        ),
        (_formation(dwsim=None), "DWSIM's formation enthalpy of NH3 was not reported"),
    ],
)
def test_reactor_closure_unsupported_says_why(formation, reason):
    closure, findings = _closure(_reacting(), formation)
    (row,) = closure["units"]
    assert row["status"] == "unsupported" and reason in row["reason"], row["reason"]
    assert closure["plant"]["status"] == "unsupported" and "residual_kW" not in closure["plant"]
    assert [f.rule for f in findings] == ["cheme.process-sim-energy-unsupported"]


def _with_argon(drift: float) -> dict:
    """1 mol/s of argon added to A, 1 + *drift* mol/s in B (what a recycle's tolerance
    leaves); the other flows as before."""
    out = _reacting()
    for sid, n, ar in (("A", 10.0, 1.0), ("B", 8.0, 1.0 + drift)):
        x = out["streams"][sid]["mole_fractions"]
        total = n + ar
        out["streams"][sid]["molar_flow_mol_s"] = total
        x.update({c: v * n / total for c, v in x.items()}, AR=ar / total)
    return out


def test_a_component_no_reaction_names_does_not_change():
    """Argon drifts by 1e-6 mol/s and has no formation enthalpy anywhere: the reactor names
    N2, H2 and NH3 only, so argon does not count; a reactor whose spec names no reaction
    counts every component that changes, and then needs argon's."""
    formation = _formation()
    formation["components"]["AR"].update(dHf_298_kJ_kmol=None, simulator_dHf_298_kJ_kmol=None)
    closure, _ = _closure(_with_argon(1e-6), formation)
    assert closure["units"][0]["status"] == "ok" and closure["plant"]["status"] == "ok"
    assert "AR" not in closure["units"][0]["changes_mol_s"]
    bare = {**REACTOR, "units": [{**REACTOR["units"][0], "spec": {}}]}
    closure, _ = _closure(_with_argon(1e-6), formation, model=bare)
    assert closure["units"][0]["status"] == "unsupported"
    assert "AR" in closure["units"][0]["reason"]


def test_formation_data_takes_materials_with_their_source(tmp_path):
    from tests.test_process_simulate_reactors import _plant
    from tests.test_process_simulate_reactors import _translate as translate_reactors

    ws = _plant(tmp_path)
    model = translate_reactors(ws).model
    process, _ = load_process(ws.root)
    out = {"compounds": {"NH3": {"dHf_298_kJ_kmol": -45898.0, "database": "ChemSep"}}}
    data = energy._formation_data(process, model, out)
    assert data["reference_verified"] and data["property_package"] == "Peng-Robinson (PR)"
    nh3 = data["components"]["NH3"]
    assert nh3["dHf_298_kJ_kmol"] == -45558.0 and nh3["origin"] == "declared"
    assert nh3["source"] == "declared in process/materials.yaml (given)"
    assert nh3["simulator_dHf_298_kJ_kmol"] == -45898.0 and nh3["molar_mass"] == 17.031
    assert energy._reacting(model["units"][0]) == {"N2", "H2", "NH3"}


def test_formation_data_falls_back_to_chemicals():
    pytest.importorskip("chemicals")
    process = SimpleNamespace(materials=None)
    model = {"compounds": [{"id": "NH3", "cas": "7664-41-7"}, {"id": "XX", "cas": "0-00-0"}]}
    data = energy._formation_data(process, model, {})
    nh3, xx = data["components"]["NH3"], data["components"]["XX"]
    assert nh3["origin"] == "chemicals" and nh3["dHf_298_kJ_kmol"] < 0
    assert nh3["source"].startswith("chemicals fallback (nothing declared): dHf_298 ")
    assert xx["dHf_298_kJ_kmol"] is None and "chemicals" in xx["missing"]


def _maturity_of(formation_data: dict | None, unit: str = "conversion_reactor"):
    from chemeascode.project.maturity import _formation_data as requirement

    row = {"id": "R1", "unit": unit, "status": "ok"}
    if formation_data is not None:
        row["formation_data"] = formation_data
    else:
        row.update(status="unsupported", reason="package not verified")
    audit = {"closure": {"units": [row], "plant": {}}}
    return requirement(object(), {"cases": {"design": {"energy": audit}}}, ["design"])


def test_declared_and_fallback_shares_are_judged_together():
    """NH3 declared 300 kJ/kmol below DWSIM's (2 mol/s: -0.6 kW) and H2 from chemicals'
    fallback 200 kJ/kmol above DWSIM's 0 (-3 mol/s: -0.6 kW), bookkeeping numbers: each share
    within the data tolerance 0.918 kW, together -1.2 kW beyond it. Not a failure (the declared
    share is within), but never "within the tolerance"."""
    formation = _formation(nh3=-46198.0)
    formation["components"]["H2"].update(
        dHf_298_kJ_kmol=200.0, origin="chemicals", source="chemicals fallback (nothing declared)"
    )
    closure, findings = _closure(_reacting(), formation)
    data = closure["units"][0]["formation_data"]
    assert data["declared_difference_kW"] == pytest.approx(-0.6)
    assert data["fallback_difference_kW"] == pytest.approx(-0.6)
    assert data["status"] == "fallback-differs"
    (text,) = data["limitations"]
    assert "differs by -1.2 kW" in text and "beyond the data tolerance 0.918 kW" in text
    assert "declared values' share is -0.6 kW (within it)" in text
    assert [f.level for f in findings] == ["info"]


def test_maturity_compares_with_materials_as_they_are_now(tmp_path):
    """The run recorded DWSIM's -45898 kJ/kmol and 2 mol/s of NH3 made (formation term -91.796
    kW); the declared value is edited after the run, nothing is simulated again: -45558 is
    0.68 kW off (a limitation), -45400 0.996 kW (fails), -45898 equal (passes clean)."""
    from chemeascode.project.maturity import _formation_data as requirement
    from tests.test_process_simulate_reactors import MATERIALS
    from tests.test_process_simulate_reactors import _plant as reactor_plant

    ws = reactor_plant(tmp_path)
    closure, _ = _closure(_reacting(), _formation(nh3=-45558.0))
    recorded = _formation(nh3=-45558.0)["components"]  # the comparison at simulate time
    run_record = {
        "cases": {"design": {"energy": {"closure": closure, "formation": {"components": recorded}}}}
    }
    path = ws.root / "process/materials.yaml"

    def verdict(nh3: str):
        path.write_text(MATERIALS.replace("dHf_298: -45558.0", f"dHf_298: {nh3}"))
        process, _ = load_process(ws.root)
        req = requirement(process, run_record, ["design"])
        return req.status, req.evidence["design"]["R1"]["status"], req

    status, found, req = verdict("-45558.0")
    assert (status, found) == ("pass", "within-tolerance") and req.evidence["limitations"]
    status, found, req = verdict("-45400.0")
    assert (status, found) == ("fail", "declared-differs") and "NH3 +498 kJ/kmol" in req.detail
    status, found, req = verdict("-45898.0")
    assert (status, found) == ("pass", "consistent") and "limitations" not in req.evidence


def test_maturity_formation_data():
    def data(nh3: float, origin: str = "declared") -> dict:
        closure, _ = _closure(_reacting(), _formation(nh3=nh3, origin=origin))
        return closure["units"][0]["formation_data"]

    req = _maturity_of(data(-45400.0))
    assert req.status == "fail" and "NH3 +498 kJ/kmol" in req.detail
    for limited in (data(-45558.0), data(-45400.0, "chemicals")):
        req = _maturity_of(limited)
        assert req.status == "pass" and req.evidence["limitations"], req.detail
    req = _maturity_of(data(-45898.0))
    assert req.status == "pass" and "limitations" not in req.evidence
    assert _maturity_of(None).status == "unsupported"
    req = _maturity_of({"status": "consistent"}, unit="heater")
    assert req.status == "pass" and "no reacting unit" in req.detail


# -- simulation audit: exchanger temperatures and utility levels -------------------------------


def test_exchanger_approach_cross_and_min_approach(tmp_path):
    """E1: hot 420 -> 380 K, cold 300 -> 350 K: terminal differences 70 and 80 K. With the hot
    outlet at 290 K the cold end crosses by 10 K. min_approach 75 K: 70 is below it."""
    ws = _copy(tmp_path, "process-separation")
    process, sim, doc, model = _translate(ws)
    findings, entry, _ = energy.audit(process, sim, doc, model, separation_out())
    row = entry["exchangers"][0]
    assert row["status"] == "ok" and row["approach_K"] == pytest.approx(70.0)
    assert "cheme.process-sim-approach-undeclared" in {f.rule for f in findings}

    findings, entry, _ = energy.audit(
        process, sim, doc, model, separation_out(H2={"temperature_K": 290.0})
    )
    crossed = [f for f in findings if f.rule == "cheme.process-sim-temperature-cross"]
    assert len(crossed) == 1 and crossed[0].ids == ["E1"] and crossed[0].line
    assert entry["exchangers"][0]["approach_K"] == pytest.approx(-10.0)

    _edit(
        ws,
        "process/simulation.yaml",
        lambda d: d.update(min_approach={"value": 75, "provenance": "assumed"}),
    )
    process, sim, doc, model = _translate(ws)
    findings, entry, _ = energy.audit(process, sim, doc, model, separation_out())
    assert entry["exchangers"][0]["status"] == "below-min-approach"
    assert "cheme.process-sim-exchanger-approach" in {f.rule for f in findings}
    assert "cheme.process-sim-approach-undeclared" not in {f.rule for f in findings}
    # the spec's own min_approach overrides the simulation's
    _edit(
        ws,
        "process/simulation.yaml",
        lambda d: d["specs"]["E1"].update(min_approach={"value": 60, "provenance": "assumed"}),
    )
    process, sim, doc, model = _translate(ws)
    findings, entry, _ = energy.audit(process, sim, doc, model, separation_out())
    assert entry["exchangers"][0]["status"] == "ok"


def test_phase_change_in_exchanger_is_flagged(tmp_path):
    process, sim, doc, model = _translate(_copy(tmp_path, "process-separation"))
    findings, entry, _ = energy.audit(
        process, sim, doc, model, separation_out(S5={"vapor_fraction": 0.3})
    )
    zones = [f for f in findings if f.rule == "cheme.process-sim-exchanger-zones"]
    assert zones and "S4" in zones[0].message and entry["exchangers"][0]["phase_change"] == ["S4"]


def _with_cooling_water(d, supply=303.15, back=313.15, approach=10):
    d["products"].append(
        {
            "id": "CW",
            "title": "Cooling water",
            "category": "utility",
            "utility": {
                "kind": "cooling_water",
                "supply_temperature": {"value": supply, "provenance": "given"},
                "return_temperature": {"value": back, "provenance": "given"},
                "min_approach": {"value": approach, "provenance": "assumed"},
            },
            "ports": [{"id": "q", "direction": "in", "kind": "energy"}],
        }
    )
    e1 = next(s for s in d["steps"] if s["id"] == "E1")
    e1["ports"].append({"id": "q", "direction": "out", "kind": "energy"})
    d["streams"].append(
        {"id": "Q1", "title": "Cooling", "kind": "energy", "from": "E1.q", "to": "CW.q"}
    )


def compression_out(**changes) -> dict:
    """The compressed-air example: 1000 kg/h; K1 84.2 kW; E1 removes 81 kW (598 -> 308.15 K)."""
    m = 1000 / 3600
    streams = {
        "S1": _s(298.15, m, 0.0, 1.0),
        "S2": _s(598.0, m, 84.2 / m, 1.0),
        "S3": _s(308.15, m, 3.2 / m, 1.0),
        "S4": _s(308.15, 0.7 * m, 3.2 / m, 1.0),
        "S5": _s(308.15, 0.3 * m, 3.2 / m, 1.0),
    }
    streams.update(changes)
    return {
        "converged": True,
        "streams": streams,
        "units": {"K1": {"duty_kW": 84.2}, "E1": {"duty_kW": -81.0}, "X1": {}},
    }


def test_utility_level_is_checked(tmp_path):
    """Cooling water 303.15 -> 313.15 K against air cooled 598 -> 308.15 K: 5 K at the cold
    end, below the declared 10 K; with 293.15 -> 303.15 K, 15 K: feasible."""
    ws = _copy(tmp_path, "process-simulation")
    _edit(ws, "process/flowsheet.yaml", _with_cooling_water)
    process, sim, doc, model = _translate(ws)
    findings, entry, _ = energy.audit(process, sim, doc, model, compression_out())
    level = entry["utility_levels"][0]
    assert (level["id"], level["terminal"], level["status"]) == ("E1", "CW", "infeasible")
    assert level["approach_K"] == pytest.approx(5.0)
    warned = [f for f in findings if f.rule == "cheme.process-sim-utility-level"]
    assert warned and warned[0].ids == ["E1", "CW"]
    # the plant closes: 84.2 kW in, 81 out, 3.2 kW more enthalpy leaves than enters
    assert entry["closure"]["plant"]["status"] == "ok"
    assert entry["utilities"]["totals_kW"]["cold_utility"] == pytest.approx(81.0)

    _edit(
        ws,
        "process/flowsheet.yaml",
        lambda d: d["products"][-1]["utility"].update(
            supply_temperature={"value": 293.15, "provenance": "given"},
            return_temperature={"value": 303.15, "provenance": "given"},
        ),
    )
    process, sim, doc, model = _translate(ws)
    findings, entry, _ = energy.audit(process, sim, doc, model, compression_out())
    assert entry["utility_levels"][0]["status"] == "ok"
    assert entry["utility_levels"][0]["approach_K"] == pytest.approx(15.0)


def test_simulate_records_the_audit(tmp_path):
    ws = _copy(tmp_path, "process-simulation")
    process, _ = load_process(ws.root)
    result = run(
        ws,
        process,
        "design",
        write=True,
        solver=lambda m, s: {
            "ok": True,
            "version": "9.0.5.0",
            "iterations": 1,
            "messages": [],
            "energies": {"W1": {"duty_kW": 84.2}},
            **compression_out(),
        },
    )
    assert any(line.startswith("energy closure (plant): ok") for line in result.lines)
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["energy"]["closure"]["plant"]["status"] == "ok"
    report = energy_report(ws.root, load_process(ws.root)[0])
    assert report.simulation == entry["energy"]


# -- flowsheet energy balances ------------------------------------------------------------------


def _enthalpies(d, w1=50.0, state="ideal_gas", source="test bookkeeping"):
    """1000 kg/h at 36 kg/kmol = 27.78 kmol/h; S1 at 0 kJ/kmol, S2 at 6480 (50 kW), S3 to S5 at
    0; W1 w1 kW into K1."""
    d["units"]["enthalpy_reference"] = {"state": state, "temperature": 298.15}
    for s in d["streams"]:
        state_ = s.setdefault("state", {}).setdefault("design", {})
        if s["id"] == "W1":
            state_["duty"] = {"value": w1, "provenance": "assumed"}
            continue
        flow = 1000.0 if s["id"] in ("S1", "S2", "S3") else 700.0 if s["id"] == "S4" else 300.0
        state_["flow"] = {"value": flow, "provenance": "assumed"}
        state_["calculated"] = {
            "enthalpy": {
                "value": 6480.0 if s["id"] == "S2" else 0.0,
                "unit": "kJ/kmol",
                "provenance": "assumed",
                "source": source,
            },
            "molar_mass": {
                "value": 36.0,
                "unit": "kg/kmol",
                "provenance": "assumed",
                "source": source,
            },
        }


def test_flowsheet_energy_balance(tmp_path):
    ws = _copy(tmp_path, "process-simulation")
    _edit(ws, "process/flowsheet.yaml", _enthalpies)
    process, found = load_process(ws.root)
    assert process is not None, found
    balances = {b.node: b for b in energy_balances(process)}
    k1 = balances["K1"]
    assert k1.status == "ok" and k1.energy_in == pytest.approx(50.0)
    assert k1.enthalpy_out - k1.enthalpy_in == pytest.approx(50.0)
    # the cooler has no energy stream: its duty is implied, not an imbalance
    assert balances["E1"].status == "no-energy-streams"
    assert balances["E1"].residual == pytest.approx(-50.0)
    assert balances["X1"].status == "no-energy-streams" and balances["X1"].residual == 0.0
    assert not [f for f in rules(process) if "energy" in f.rule]


def test_flowsheet_energy_imbalance_is_a_warning(tmp_path):
    """W1 60 kW against 50 kW of enthalpy rise: 10 kW off (tolerance 0.1 + 0.6 + 0.005)."""
    ws = _copy(tmp_path, "process-simulation")
    _edit(ws, "process/flowsheet.yaml", lambda d: _enthalpies(d, w1=60.0))
    process, _ = load_process(ws.root)
    warned = [f for f in rules(process) if f.rule == "cheme.process-energy-balance"]
    assert [f.ids for f in warned] == [["K1"]]
    found = {b.node: b for b in energy_balances(process)}
    assert found["K1"].status == "imbalance" and found["K1"].residual == pytest.approx(-10.0)
    # the block holds the cooler, whose duty has no energy stream: not evaluable, not imbalanced
    assert found["COMP"].status == "not-evaluable"
    assert "the duty of step E1" in found["COMP"].missing[0]


def test_flowsheet_energy_imbalance_in_another_case(tmp_path):
    """A second case is balanced too (pre-release issue 185): design closes (W1 50 kW), turndown has
    W1 60 kW against the same 50 kW of enthalpy rise."""
    ws = _copy(tmp_path, "process-simulation")

    def turndown(d):
        _enthalpies(d)
        d["cases"].append({"id": "turndown", "description": "Turndown"})
        for s in d["streams"]:
            s["state"]["turndown"] = copy.deepcopy(s["state"]["design"])
            if s["id"] == "W1":
                s["state"]["turndown"]["duty"]["value"] = 60.0

    _edit(ws, "process/flowsheet.yaml", turndown)
    process, _ = load_process(ws.root)
    warned = [f for f in rules(process) if f.rule == "cheme.process-energy-balance"]
    assert [f.ids for f in warned] == [["K1"]] and "K1 (turndown)" in warned[0].message


def test_enthalpy_in_another_unit_is_not_read_as_kj_per_kmol(tmp_path):
    """S2's enthalpy per mass (pre-release issue 215): 180 kJ/kg is the same 50 kW at 1000 kg/h, but
    read as kJ/kmol it would be 1.39 kW and K1 would seem 48.6 kW off. Never converted: K1 is not
    evaluable and the unit is an error; likewise a molar mass not in kg/kmol."""
    ws = _copy(tmp_path, "process-simulation")

    def per_mass(d):
        _enthalpies(d)
        s2 = next(s for s in d["streams"] if s["id"] == "S2")
        s2["state"]["design"]["calculated"]["enthalpy"].update(value=180.0, unit="kJ/kg")

    _edit(ws, "process/flowsheet.yaml", per_mass)
    process, _ = load_process(ws.root)
    k1 = next(b for b in energy_balances(process) if b.node == "K1")
    assert k1.status == "not-evaluable" and k1.residual is None
    assert k1.missing == ["S2 enthalpy in kJ/kmol (it is in kJ/kg)"]
    # the cooler E1 (no energy stream) has S2 too: its duty is unknown, so is the block's balance
    comp = next(b for b in energy_balances(process) if b.node == "COMP")
    assert comp.status == "not-evaluable" and "the duty of step E1" in comp.missing[0]
    found = rules(process)
    assert not [f for f in found if f.rule == "cheme.process-energy-balance"]
    unit = [f for f in found if f.rule == "cheme.process-unit"]
    assert [(f.level, f.ids) for f in unit] == [("error", ["S2"])]
    assert "calculated enthalpy in 'kJ/kg', must be kJ/kmol" in unit[0].message

    def molar_mass_in_g(d):
        _enthalpies(d)
        s1 = next(s for s in d["streams"] if s["id"] == "S1")
        s1["state"]["design"]["calculated"]["molar_mass"].update(value=0.036, unit="kg/mol")

    _edit(ws, "process/flowsheet.yaml", molar_mass_in_g)
    process, _ = load_process(ws.root)
    k1 = next(b for b in energy_balances(process) if b.node == "K1")
    assert k1.status == "not-evaluable"
    assert k1.missing == ["S1 molar mass in kg/kmol (it is in kg/mol)"]
    assert [f.ids for f in rules(process) if f.rule == "cheme.process-unit"] == [["S1"]]


def test_unsupported_reference_is_not_repeated_per_case(tmp_path):
    """The info findings come from the default case only (pre-release issue 185): a reactive COMP is
    unsupported in design and turndown, reported once."""
    ws = _copy(tmp_path, "process-simulation")

    def two_cases(d):
        _enthalpies(d)
        d["blocks"][0]["balance_scope"] = "reactive"
        d["cases"].append({"id": "turndown", "description": "Turndown"})
        for s in d["streams"]:
            s["state"]["turndown"] = copy.deepcopy(s["state"]["design"])

    _edit(ws, "process/flowsheet.yaml", two_cases)
    process, _ = load_process(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.process-energy-balance-unsupported"]
    assert [f.ids for f in found] == [["COMP"]] and "(design)" in found[0].message


@pytest.mark.parametrize(
    "name, unit, want",
    [
        ("enthalpy", "kJ/kg", "kJ/kmol"),
        ("molar_mass", "g/mol", "kg/kmol"),
        ("density", "g/cm3", "kg/m3"),
        ("exergy", "MJ/kmol", "kJ/kmol"),
    ],
)
def test_calculated_unit_rule(tmp_path, name, unit, want):
    """Every calculated property read as a number has one unit (pre-release issue 215)."""
    ws = _copy(tmp_path, "process-simulation")

    def other_unit(d):
        _enthalpies(d)
        s3 = next(s for s in d["streams"] if s["id"] == "S3")
        s3["state"]["design"]["calculated"][name] = {
            "value": 1.0,
            "unit": unit,
            "provenance": "assumed",
        }

    _edit(ws, "process/flowsheet.yaml", other_unit)
    process, _ = load_process(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.process-unit"]
    assert [(f.level, f.ids) for f in found] == [("error", ["S3"])]
    assert f"calculated {name} in {unit!r}, must be {want}" in found[0].message


def test_block_with_an_unevaluable_step_without_energy_stream(tmp_path):
    """A step inside a block without an energy stream whose own balance is not evaluable (S2,
    between K1 and E1, has no enthalpy): E1's duty is unknown, so the block's energy streams
    cannot close it; not evaluable rather than balanced as if E1 were adiabatic."""
    ws = _copy(tmp_path, "process-simulation")

    def no_s2_enthalpy(d):
        _enthalpies(d)
        s2 = next(s for s in d["streams"] if s["id"] == "S2")
        del s2["state"]["design"]["calculated"]["enthalpy"]

    _edit(ws, "process/flowsheet.yaml", no_s2_enthalpy)
    process, _ = load_process(ws.root)
    found = {b.node: b for b in energy_balances(process)}
    assert found["E1"].status == "not-evaluable" and not found["E1"].energy_streams
    comp = found["COMP"]
    assert comp.status == "not-evaluable"
    assert comp.missing == [
        "the duty of step E1 (no energy stream; not evaluable, missing S2 enthalpy)"
    ]
    assert not [f for f in rules(process) if f.rule == "cheme.process-energy-balance"]


def test_exergy_in_another_unit_is_not_summed(tmp_path):
    """A terminal's exergy flow reads exergy as kJ/kmol and molar mass as kg/kmol only
    (pre-release issue 215)."""
    ws = _copy(tmp_path, "process-simulation")

    def exergy(d, unit):
        _enthalpies(d)
        s1 = next(s for s in d["streams"] if s["id"] == "S1")
        s1["state"]["design"]["calculated"]["exergy"] = {
            "value": 3600.0,
            "unit": unit,
            "provenance": "assumed",
        }

    _edit(ws, "process/flowsheet.yaml", lambda d: exergy(d, "kJ/kmol"))
    process, _ = load_process(ws.root)
    air = next(t for t in terminals(process, "design") if t.key == "feed:AIR")
    assert air.exergy == pytest.approx(1000.0 / 36.0 * 3600.0) and not air.no_exergy
    _edit(ws, "process/flowsheet.yaml", lambda d: exergy(d, "kJ/kg"))
    process, _ = load_process(ws.root)
    air = next(t for t in terminals(process, "design") if t.key == "feed:AIR")
    assert air.exergy == 0.0 and air.no_exergy == ["S1"]


def test_reactive_or_inconsistent_reference_is_unsupported(tmp_path):
    ws = _copy(tmp_path, "process-simulation")

    def reactive(d):
        _enthalpies(d)
        d["blocks"][0]["balance_scope"] = "reactive"

    _edit(ws, "process/flowsheet.yaml", reactive)
    process, _ = load_process(ws.root)
    comp = next(b for b in energy_balances(process) if b.node == "COMP")
    assert comp.status == "unsupported" and "heat-of-formation" in comp.reason
    assert comp.residual is None
    assert "cheme.process-energy-balance-unsupported" in {f.rule for f in rules(process)}

    # values from cheme process props (thermo, ideal gas) under a declared elements reference
    _edit(
        ws,
        "process/flowsheet.yaml",
        lambda d: _enthalpies(d, state="elements", source="cheme process props: thermo"),
    )
    process, _ = load_process(ws.root)
    k1 = next(b for b in energy_balances(process) if b.node == "K1")
    assert k1.status == "unsupported" and "inconsistent reference" in k1.reason


# -- boundary completeness ----------------------------------------------------------------------


def test_boundary_gaps(tmp_path):
    ws = _copy(tmp_path, "process-simulation")
    process, _ = load_process(ws.root)
    before = [(t.key, t.per_hour) for t in terminals(process, "design")]
    report = boundary_gaps(process)
    rules_found = {(f.rule, tuple(f.ids)) for f in report.findings}
    assert ("cheme.boundary-utility-unassigned", ("E1",)) in rules_found
    assert ("cheme.boundary-unclassified", ("HP",)) in rules_found
    assert report.unassigned_duties == ["E1"] and not report.complete
    assert all(f.file == "process/flowsheet.yaml" and f.line and f.hint for f in report.findings)
    # the compressor's power stream counts: K1 is not unassigned
    assert ("cheme.boundary-utility-unassigned", ("K1",)) not in rules_found

    def classify(d):
        _with_cooling_water(d)
        d["feeds"][0]["category"] = "raw_material"
        d["feeds"][1].update(category="utility", utility={"kind": "electricity"})
        for p in d["products"][:2]:
            p["category"] = "product"

    _edit(ws, "process/flowsheet.yaml", classify)
    process, _ = load_process(ws.root)
    report = boundary_gaps(process)
    assert report.complete and not report.findings, report.findings
    assert report.categories == {
        "raw_material": ["AIR"],
        "utility": ["POWER", "CW"],
        "product": ["HP", "PLANT"],
    }
    # the terminal rates the TEA and LCA read are unchanged by the check
    assert [(t.key, t.per_hour) for t in terminals(process, "design")][:4] == before


def test_utility_on_a_non_utility_terminal_is_an_error(tmp_path):
    ws = _copy(tmp_path, "process-simulation")
    _edit(
        ws,
        "process/flowsheet.yaml",
        lambda d: d["feeds"][1].update(utility={"kind": "electricity"}),
    )
    process, _ = load_process(ws.root)
    assert "cheme.process-terminal" in {f.rule for f in rules(process) if f.level == "error"}


def test_cli_energy(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    ws = _copy(tmp_path, "process-simulation")
    monkeypatch.chdir(ws.root)
    shown = CliRunner().invoke(app, ["process", "energy"])
    assert shown.exit_code == 1  # the unassigned cooler duty is a warning
    assert "cheme.boundary-utility-unassigned" in shown.output
    assert "no energy audit recorded" in shown.output
    payload = json.loads(CliRunner().invoke(app, ["process", "energy", "--json"]).output)
    assert payload["boundary"]["unassigned_duties"] == ["E1"]
    assert payload["simulation"] is None and payload["case"] == "design"


def test_audit_runs_without_flowsheet_terminals():
    """The audit on a bare model: nothing to check but nothing raised."""
    process = SimpleNamespace(
        flowsheet=SimpleNamespace(
            feeds=[], products=[], streams=[], units=SimpleNamespace(temperature="K")
        )
    )
    sim = SimpleNamespace(specs={}, min_approach=None)
    findings, entry, lines = energy.audit(process, sim, None, {"units": []}, {"streams": {}})
    assert entry["closure"]["plant"]["status"] == "not-evaluable" and lines
