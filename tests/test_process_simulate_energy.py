"""The energy audit's reacting closure against the real DWSIM (CHEME_DWSIM_TESTS=1).

DWSIM 9.0.5 reports stream enthalpies on each component's ideal gas at 298.15 K = 0, without
formation enthalpies, for Peng-Robinson, PR78 and SRK (checked here; NRTL is shown not to be);
its reactor duty takes the formation enthalpies of its own compound database (ChemSep). On that
basis the audit's closure (stream enthalpy flows plus ``sum (n_out - n_in) dHf`` on DWSIM's
values) must reproduce DWSIM's duty, and the project's formation enthalpies are compared with
DWSIM's separately (``sim-formation-data``).

The components and the reaction are those of tests/test_process_simulate_reactors.py. There
dHf_298 of ammonia is declared as -45558 kJ/kmol (chemicals' ATcT value); DWSIM's is -45898
kJ/kmol, 0.74 % of the reaction heat apart: within the data tolerance (1 %), so a recorded
limitation. One loop test declares -45898 kJ/kmol instead, the NIST-JANAF value (M. W. Chase,
NIST-JANAF Thermochemical Tables, 4th ed., J. Phys. Chem. Ref. Data Monograph 9, 1998; ammonia,
ideal gas, 298.15 K), equal to DWSIM's. The failing path uses a value marked as a deliberately
wrong test fixture (``OFF``), never presented as data.
"""

from __future__ import annotations

import json
import os

import pytest

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation.run import run
from chemeascode.integrations import dwsim
from chemeascode.project.maturity import _energy_audit, _formation_data
from tests import test_process_simulate_kinetic as kinetic
from tests import test_process_simulate_reactors as reactors

dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

#: Ammonia's formation enthalpy as NIST-JANAF gives it (see the module docstring).
JANAF = reactors.MATERIALS.replace(
    "ideal_gas: {dHf_298: -45558.0,",
    "ideal_gas: {dHf_298: -45898.0,",
).replace(
    "temperature_range: [50, 1000], provenance: given}}\n  - {id: AR",
    "temperature_range: [50, 1000], provenance: given,\n"
    "                 source: 'NIST-JANAF Thermochemical Tables, 4th ed. (Chase 1998): "
    "dHf_298'}}\n  - {id: AR",
)
#: DWSIM's reactor duty reproduced on its own formation enthalpies within this (kW); found
#: below 1e-3 kW for each reactor model (about 1600 kW of reaction heat).
DUTY_TOLERANCE_KW = 1e-2
#: The property packages the closure's basis is claimed for (simulation/energy.py).
PACKAGES = ["Peng-Robinson (PR)", "Peng-Robinson 1978 (PR78)", "Soave-Redlich-Kwong (SRK)"]


def _simulation(package: str, text: str = reactors.SIMULATION) -> str:
    return text.replace("property_package: Peng-Robinson (PR)", f"property_package: {package}")


def _run(ws, solver=None) -> tuple[dict, list]:
    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True, solver=solver)
    assert not [f for f in result.findings if f.level == "error"], [
        f.format() for f in result.findings
    ]
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"], entry["messages"]
    return entry["energy"], result.findings


def _row(audit: dict, uid: str) -> dict:
    return next(r for r in audit["closure"]["units"] if r["id"] == uid)


#: The conversion reactor isothermal at 298.15 K and 1 kPa (near the ideal gas).
AT_298 = (
    reactors.FLOWSHEET.replace(
        "value: 523.15, provenance: given", "value: 298.15, provenance: given"
    )
    .replace(
        "pressure: {value: 1000, provenance: given}", "pressure: {value: 1, provenance: given}"
    )
    .rsplit("    state:\n      design:\n", 1)[0]
)


@dwsim_tests
@pytest.mark.parametrize("package", PACKAGES)
def test_dwsim_enthalpy_reference_is_the_ideal_gas_at_298_without_formation(tmp_path, package):
    """Both streams' enthalpies vanish, so DWSIM's duty is the formation term on its own data."""
    ws = reactors._plant(tmp_path, AT_298, _simulation(package))
    assert reactors._translate(ws).model["units"][0]["spec"]["mode"] == "isothermal"
    audit, _ = _run(ws)
    row = _row(audit, "R1")
    print(
        f"{package}: H in {row['enthalpy_in_kW']:.4g} kW, H out {row['enthalpy_out_kW']:.4g} kW, "
        f"duty {row['heat_in_kW']:.6g} kW, formation on DWSIM's dHf {row['formation_kW']:.6g}"
    )
    # stream enthalpy flows next to the formation term (about 1580 kW): within 0.05 kW of zero
    assert abs(row["enthalpy_in_kW"]) < 0.05 and abs(row["enthalpy_out_kW"]) < 0.05
    assert row["heat_in_kW"] == pytest.approx(row["formation_kW"], abs=0.1)
    assert abs(row["formation_kW"]) > 1000


@dwsim_tests
def test_dwsim_nrtl_is_not_on_the_ideal_gas_basis(tmp_path):
    """The same streams with NRTL: their enthalpies at 298.15 K and 1 kPa are far from 0, so
    the reactor's closure stays unsupported."""
    seen = {}

    def solver(model, save):
        seen["out"] = dwsim.solve(model, save)
        return seen["out"]

    ws = reactors._plant(tmp_path, AT_298, _simulation("NRTL"))
    audit, _ = _run(ws, solver)
    enthalpies = {s: seen["out"]["streams"][s]["mass_enthalpy_kJ_kg"] for s in ("S1", "S2")}
    print("NRTL at 298.15 K, 1 kPa:", enthalpies, "kJ/kg")
    assert all(abs(h) > 100.0 for h in enthalpies.values()), enthalpies
    row = _row(audit, "R1")
    assert row["status"] == "unsupported" and "'NRTL' is not verified" in row["reason"]


EQUILIBRIUM = reactors.FLOWSHEET.replace(
    "    reactions: [SYN]\n", "    reactions: [SYN]\n    reactor: equilibrium\n"
)
GIBBS = reactors.FLOWSHEET.replace("    reactions: [SYN]\n", "    reactor: gibbs\n")
AT_743 = reactors.SIMULATION + "    outlet_temperature: {value: 743.15, provenance: assumed}\n"


@dwsim_tests
@pytest.mark.parametrize(
    ("flowsheet", "simulation"),
    [
        *[(reactors.FLOWSHEET, _simulation(p)) for p in PACKAGES],
        (EQUILIBRIUM, AT_743),
        (GIBBS, AT_743),
    ],
    ids=["conversion-PR", "conversion-PR78", "conversion-SRK", "equilibrium-PR", "gibbs-PR"],
)
def test_dwsim_reactor_duty_on_the_formation_basis(tmp_path, flowsheet, simulation):
    ws = reactors._plant(tmp_path, flowsheet, simulation)
    audit, findings = _run(ws)
    row = _row(audit, "R1")
    data = row["formation_data"]
    print(
        f"R1 duty {row['heat_in_kW']:.6g} kW, residual {row['residual_kW']:.3g} kW (DWSIM's dHf, "
        f"tolerance {row['tolerance_kW']:.4g} kW); declared data differ by "
        f"{data['declared_difference_kW']:.4g} kW ({data['status']})"
    )
    # DWSIM's own formation enthalpies reproduce its duty: the basis is what it is said to be
    assert row["basis"] == "formation" and row["status"] == "ok"
    assert abs(row["residual_kW"]) < DUTY_TOLERANCE_KW
    # the declared ammonia (-45558 kJ/kmol, ATcT) against DWSIM's (-45898, JANAF): 340 kJ/kmol,
    # 0.74 % of the reaction heat, within the data tolerance (1 %): a limitation, not a failure
    made = row["changes_mol_s"]["NH3"]
    assert made > 0
    assert data["declared_difference_kW"] == pytest.approx(made * 340.0 / 1e3, rel=1e-6)
    assert data["status"] == "within-tolerance" and data["limitations"]
    (nh3,) = [x for x in data["components"] if x["id"] == "NH3"]
    assert nh3["difference_kJ_kmol"] == pytest.approx(340.0, abs=0.01)
    warned = [f for f in findings if f.rule == "cheme.process-sim-formation-data"]
    assert [f.level for f in warned] == ["info"]
    reqs = _maturity(ws)
    assert reqs["predictive.energy-closure"].status == "pass"
    assert reqs["predictive.formation-data"].status == "pass"
    assert reqs["predictive.formation-data"].evidence["limitations"]
    nh3 = audit["formation"]["components"]["NH3"]
    assert nh3["simulator_dHf_298_kJ_kmol"] == pytest.approx(-45898.0, abs=1.0)
    assert nh3["simulator_database"] == "ChemSep"


#: The synthesis loop of tests/test_process_simulate_kinetic.py with a conversion reactor (25 %
#: of the nitrogen, isothermal) in place of the bed.
CONVERSION_LOOP = kinetic.LOOP.replace(
    "    reactor: pfr\n    catalyst: FE\n"
    "    bed: {catalyst_mass: 2000, heat: adiabatic, provenance: assumed, source: test fixture}\n",
    "",
)


def _closes(audit: dict) -> dict:
    plant = audit["closure"]["plant"]
    print(
        "plant:",
        {k: plant.get(k) for k in ("status", "basis", "residual_kW", "tolerance_kW")},
        "formation on DWSIM's dHf",
        plant.get("formation_kW"),
        "on the project's",
        plant.get("project_formation_kW"),
    )
    for row in audit["closure"]["units"]:
        print(row["id"], row["status"], row.get("basis"), row.get("residual_kW"))
    assert {r["id"]: r["status"] for r in audit["closure"]["units"]} == dict.fromkeys(
        ("M1", "H1", "R1", "C1", "SP"), "ok"
    )
    assert plant["status"] == "ok" and plant["basis"] == "formation"
    assert plant["feeds"] == ["S1"] and plant["products"] == ["S6", "S7"]
    assert plant["formation_kW"] < 0  # ammonia made
    return plant


def _maturity(ws) -> dict:
    process, _ = load_process(ws.root)
    data = json.loads((ws.root / "process/simulation-run.json").read_text())
    reqs = [*_energy_audit(process, data, ["design"]), _formation_data(process, data, ["design"])]
    return {r.id: r for r in reqs}


@dwsim_tests
@pytest.mark.parametrize("materials", ["declared-atct", "declared-janaf"])
def test_dwsim_ammonia_loop_closes_with_a_conversion_reactor(tmp_path, materials):
    assert "reactor: pfr" not in CONVERSION_LOOP
    ws = kinetic._plant(tmp_path, CONVERSION_LOOP, kinetic.LOOP_SIMULATION.rsplit("  R1:", 1)[0])
    janaf = materials == "declared-janaf"
    (ws.root / "process/materials.yaml").write_text(JANAF if janaf else reactors.MATERIALS)
    (ws.root / "process/reactions.yaml").write_text(reactors.REACTIONS)
    audit, findings = _run(ws)
    _closes(audit)
    data = _row(audit, "R1")["formation_data"]
    print("R1 formation data:", data)
    reqs = _maturity(ws)
    # the simulation conserves energy: predictive.energy-closure passes either way
    assert reqs["predictive.energy-closure"].status == "pass", reqs["predictive.energy-closure"]
    warned = [f for f in findings if f.rule == "cheme.process-sim-formation-data"]
    if janaf:
        assert "NIST-JANAF" in audit["formation"]["components"]["NH3"]["source"]
        assert data["status"] == "consistent" and not data["limitations"] and not warned
        assert reqs["predictive.formation-data"].status == "pass"
        assert "limitations" not in reqs["predictive.formation-data"].evidence
    else:
        # ATcT's ammonia: 340 kJ/kmol, 0.74 % of the loop's reaction heat (3.6 of 485 kW)
        assert data["status"] == "within-tolerance"
        assert data["declared_difference_kW"] == pytest.approx(
            0.0074 * abs(_row(audit, "R1")["formation_kW"]), rel=0.01
        )
        assert [f.level for f in warned] == ["info"]
        assert reqs["predictive.formation-data"].status == "pass"
        assert reqs["predictive.formation-data"].evidence["limitations"]


#: Ammonia's formation enthalpy deliberately off: a TEST FIXTURE (provenance assumed), not data,
#: 602 kJ/kmol (1.3 %) from DWSIM's value, beyond the data tolerance.
OFF = reactors.MATERIALS.replace(
    "ideal_gas: {dHf_298: -45558.0,",
    "ideal_gas: {dHf_298: -46500.0,",
).replace(
    "temperature_range: [50, 1000], provenance: given}}\n  - {id: AR",
    "temperature_range: [50, 1000], provenance: assumed,\n"
    "                 source: 'test fixture: deliberately off, not data'}}\n  - {id: AR",
)
ADIABATIC = reactors.SIMULATION + "    mode: adiabatic\n"
WITHOUT_OUTLET = reactors.FLOWSHEET.replace(
    "        temperature: {value: 743.15, provenance: assumed}\n", ""
).rsplit("    state:\n      design:\n", 1)[0]


@dwsim_tests
@pytest.mark.parametrize("mode", ["outlet-temperature", "adiabatic"])
def test_dwsim_declared_formation_data_that_differ_fail_in_any_mode(tmp_path, mode):
    """The declared-mismatch path end to end, the same verdict for a cooled reactor (outlet
    temperature 743.15 K) and an adiabatic one (duty 0): the energy is conserved
    (``predictive.energy-closure`` passes), the formation data fail."""
    adiabatic = mode == "adiabatic"
    ws = reactors._plant(
        tmp_path,
        WITHOUT_OUTLET if adiabatic else reactors.FLOWSHEET,
        ADIABATIC if adiabatic else reactors.SIMULATION,
    )
    (ws.root / "process/materials.yaml").write_text(OFF)
    audit, findings = _run(ws)
    row = _row(audit, "R1")
    data = row["formation_data"]
    print(
        f"{mode}: duty {row['heat_in_kW']:.4g} kW, residual {row['residual_kW']:.3g} kW; declared "
        f"data differ by {data['declared_difference_kW']:.4g} kW (data tolerance "
        f"{data['data_tolerance_kW']:.4g} kW)"
    )
    assert row["status"] == "ok" and abs(row["residual_kW"]) < DUTY_TOLERANCE_KW
    assert (abs(row["heat_in_kW"]) < 1e-6) == adiabatic
    assert data["status"] == "declared-differs"
    (nh3,) = [x for x in data["components"] if x["id"] == "NH3"]
    assert nh3["difference_kJ_kmol"] == pytest.approx(-602.0, abs=0.01)
    warned = [f for f in findings if f.rule == "cheme.process-sim-formation-data"]
    assert [f.level for f in warned] == ["warning"]
    assert "-46500 kJ/kmol declared in process/materials.yaml (assumed" in warned[0].message
    reqs = _maturity(ws)
    assert reqs["predictive.energy-closure"].status == "pass"
    assert reqs["predictive.formation-data"].status == "fail"


@dwsim_tests
def test_dwsim_ammonia_loop_closes_with_a_coupled_bed(tmp_path):
    """The kinetic_pfr: its duty is DWSIM's conversion reactor's (pre-release PR 151's coupling),
    which closes on the streams DWSIM solved; the bed's own ideal-gas balance is the coupling's."""
    ws = kinetic._plant(tmp_path, kinetic.LOOP, kinetic.LOOP_SIMULATION)
    audit, _ = _run(ws)
    _closes(audit)
    row = _row(audit, "R1")
    assert row["unit"] == "kinetic_pfr" and row["basis"] == "formation"
    assert abs(row["residual_kW"]) < DUTY_TOLERANCE_KW
    assert _maturity(ws)["predictive.energy-closure"].status == "pass"
