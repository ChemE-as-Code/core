"""The energy audit's reacting closure on a liquid-phase reactor:
liquid-phase methyl tert-butyl ether (MTBE) synthesis, isobutene + methanol = MTBE, at 298.15 K and
2000 kPa(a), every stream liquid.

A liquid's stream enthalpy in DWSIM 9.0.5 (Peng-Robinson, PR78, SRK) is its equation of
state's departure from the ideal gas at the same temperature, on the closure's basis (each
component's ideal gas at 298.15 K = 0, without formation enthalpies,
tests/test_process_simulate_energy.py): at 298.15 K, about minus the heat of vaporization.
The closure (stream enthalpy flows plus ``sum (n_out - n_in) dHf`` on DWSIM's ideal-gas
formation enthalpies) then holds for liquid streams unchanged, and the liquid reaction heat is
the ideal-gas one plus the departures: about -65.5 kJ/mol as ideal gas, about -33 kJ/mol as
liquid here. Checked live (CHEME_DWSIM_TESTS=1):

- the pure liquids' enthalpies equal thermo's departure functions of the same equation of
  state (an independent implementation; critical constants from chemicals, not DWSIM's
  ChemSep), within :data:`DEPARTURE_TOLERANCE`;
- the liquid reactor's duty is reproduced on the formation basis (Peng-Robinson, PR78, SRK)
  within the duty tolerance of the vapour tests;
- the liquid reaction heat DWSIM simulates with Peng-Robinson, pure liquids to pure liquid
  (the plant's heat over the extent: the heater's demixing and the reactor's duty), against two
  independent liquid-phase values (:data:`CALORIMETRIC`, :data:`HESS`) within
  :data:`REACTION_HEAT_TOLERANCE`.

Reference values (NIST Chemistry WebBook, SRD 69, MTBE, isobutene and methanol pages):

- reaction calorimetry, liquid phase: -33.8 kJ/mol (L. Sola, M. A. Pericas, F. Cunill, M.
  Iborra, Reaction calorimetry study of the liquid-phase synthesis of tert-butyl methyl ether,
  Ind. Eng. Chem. Res. 33 (1994) 2578-2583);
- Hess's law on liquid formation enthalpies: MTBE(l) -313.6 +- 1.3 kJ/mol (J. O. Fenwick, D.
  Harrop, A. J. Head, J. Chem. Thermodyn. 7 (1975) 943-954), methanol(l) -239.5 +- 0.2 kJ/mol
  (J. Chao, F. D. Rossini, J. Chem. Eng. Data 10 (1965) 374-379), isobutene(l) = gas -17.9 +-
  1.1 kJ/mol (E. J. Prosen, F. W. Maron, F. D. Rossini, J. Res. NBS 46 (1951) 106-112) minus
  its heat of vaporization 20.6 kJ/mol (R. C. Wilhoit, B. J. Zwolinski, Handbook of vapor
  pressures and heats of vaporization of hydrocarbons and related compounds, 1971; NIST cites
  it as Reid, AIChE J. 18 (1972) 1278, a review of that handbook): -313.6 + 239.5 + 17.9 +
  20.6 = -35.6 +- 1.7 kJ/mol (the formation values' uncertainties in quadrature; the heat of
  vaporization has none listed).

A third published value disagrees with both and is not met: high-pressure heat-flow
calorimetry, 39.8 +- 0.4 kJ/mol for the decomposition at 319 K, i.e. -39.8 kJ/mol for the
synthesis (H. Arntz, K. Gottlieb, J. Chem. Thermodyn. 17 (1985) 967-972; NIST labels the entry
"gas phase" but derives MTBE's liquid formation enthalpy at 319 K, -315.4 kJ/mol, from it, so it
is a liquid-phase value; ``dCp`` of the reaction moves it by about 0.5 kJ/mol to 298.15 K). The
published liquid reaction heats therefore span about -33.8 to -39.8 kJ/mol; the simulated -33.1
kJ/mol lies at the low-magnitude end, about 17 % from :data:`ARNTZ_GOTTLIEB`, outside
:data:`REACTION_HEAT_TOLERANCE` (pinned in the recorded test so the documented gap stays true).

Two DWSIM behaviours found on the way, kept out of the reference case: a liquid-phase
reaction in DWSIM's conversion reactor converts the key component of the inlet's liquid phase
only (simulate now reports the conversion reached and an error,
``cheme.process-sim-conversion-mismatch``, when it falls short, asserted here per package);
and Peng-Robinson and SRK split the isobutene-methanol mixture at 278-298 K and 2000 kPa into a
"vapour" (not a real vapour, likely a second liquid: both pure components' vapour
pressures are far below 2000 kPa). The adiabatic mixer cools the feeds to 277.5 K, where
Peng-Robinson splits off 0.5 %: a heater takes the mixture back to 298.15 K, where it is one
liquid under Peng-Robinson, so the declared conversion (complete) is reached and the product is
pure MTBE. At 298.15 K PR78 still splits off 0.15 % (it converts 99.85 %) and SRK 17.6 % (it
converts about 81 %): their closures hold all the same; the reaction heat is compared for
Peng-Robinson only.
"""

from __future__ import annotations

import json
import os

import pytest

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation import energy
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.maturity import _energy_audit, _formation_data

dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

#: Liquid-phase reaction heat of isobutene + methanol = MTBE, kJ/mol (module docstring).
CALORIMETRIC = -33.8
HESS = -35.6
#: A third calorimetric value, at 319 K, that the simulation does not meet (module docstring).
ARNTZ_GOTTLIEB = -39.8
#: The simulated liquid reaction heat against each reference value, relative. The two
#: references differ by 1.8 kJ/mol (5 %), the Hess value is uncertain by 1.7 kJ/mol (5 %) and
#: the calorimetric value is not stated at 298.15 K: 10 % (3.4-3.6 kJ/mol) is what the data
#: support. The liquid departures change the reaction heat by about 32 kJ/mol (the ideal-gas
#: reaction heat misses both values by more than 80 %), so the check tells whether they are in.
REACTION_HEAT_TOLERANCE = 0.10
#: DWSIM's pure-liquid enthalpy against thermo's departure function of the same equation of
#: state, relative: the critical constants differ between DWSIM's ChemSep database and
#: chemicals (isobutene's give 0.7 %).
DEPARTURE_TOLERANCE = 0.015
#: DWSIM's duty reproduced on its own formation enthalpies (kW), as for the vapour reactors.
DUTY_TOLERANCE_KW = 1e-2
PACKAGES = ["Peng-Robinson (PR)", "Peng-Robinson 1978 (PR78)", "Soave-Redlich-Kwong (SRK)"]
#: Whether the package splits the reactor inlet at 298.15 K and so falls short of the declared
#: conversion: PR78 converts 99.85 %, SRK about 81 %, Peng-Robinson all of
#: it.
SPLITS = {
    "Peng-Robinson (PR)": False,
    "Peng-Robinson 1978 (PR78)": True,
    "Soave-Redlich-Kwong (SRK)": True,
}
SHORT = "cheme.process-sim-conversion-mismatch"
#: thermo's equation of state for each package.
EOS = {
    "Peng-Robinson (PR)": "PR",
    "Peng-Robinson 1978 (PR78)": "PR78",
    "Soave-Redlich-Kwong (SRK)": "SRK",
}

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: IB, name: Isobutene, formula: C4H8, cas: 115-11-7, molar_mass: 56.106}
  - {id: MEOH, name: Methanol, formula: CH4O, cas: 67-56-1, molar_mass: 32.042}
  - {id: MTBE, name: Methyl tert-butyl ether, formula: C5H12O, cas: 1634-04-4, molar_mass: 88.148}
templates:
  - {id: mix, components: [IB, MEOH, MTBE]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: ETH
    stoichiometry: {IB: -1, MEOH: -1, MTBE: 1}
    phase: liquid
    conversion: {key: IB, value: 1.0, provenance: assumed}
"""


def _pure(sid: str, to: str, component: str, flow: float = 100.0) -> str:
    values = {c: 1.0 if c == component else 0.0 for c in ("IB", "MEOH", "MTBE")}
    return f"""\
  - id: {sid}
    from: F{component}.out
    to: {to}
    template: mix
    state:
      design:
        temperature: {{value: 298.15, provenance: given}}
        pressure: {{value: 2000, provenance: given}}
        flow: {{value: {flow}, provenance: given}}
        composition:
          basis: mole_fraction
          values: {{IB: {values["IB"]}, MEOH: {values["MEOH"]}, MTBE: {values["MTBE"]}}}
          provenance: given
"""


#: Pure isobutene and methanol (100 kmol/h each, liquid, 298.15 K, 2000 kPa) -> adiabatic mixer
#: -> heater back to 298.15 K -> conversion reactor at 298.15 K (vapour and liquid outlets).
FLOWSHEET = (
    """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: FIB, ports: [{id: out, direction: out}]}
  - {id: FMEOH, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: PV, ports: [{id: in, direction: in}]}
blocks:
  - id: B
    class: ReactingChemicals
    ports:
      - {id: a, direction: in}
      - {id: b, direction: in}
      - {id: out, direction: out}
      - {id: vap, direction: out}
steps:
  - id: M1
    block: B
    class: MixingSimple
    ports:
      - {id: a, direction: in, delegates: a}
      - {id: b, direction: in, delegates: b}
      - {id: out, direction: out}
  - id: H1
    block: B
    class: SupplyingThermalEnergy
    ports: [{id: in, direction: in}, {id: out, direction: out}]
  - id: R1
    block: B
    class: ReactingChemicals
    reactions: [ETH]
    ports:
      - {id: in, direction: in}
      - {id: vapor, direction: out, delegates: vap}
      - {id: liquid, direction: out, delegates: out}
streams:
"""
    + _pure("S1", "M1.a", "IB")
    + _pure("S2", "M1.b", "MEOH")
    + """\
  - id: S3
    from: M1.out
    to: H1.in
    template: mix
  - id: S4
    from: H1.out
    to: R1.in
    template: mix
  - id: S5
    from: R1.liquid
    to: P.in
    template: mix
  - id: S6
    from: R1.vapor
    to: PV.in
    template: mix
"""
)

SIMULATION = """\
schema: cheme/simulation/v1
kind: simulation
property_package: Peng-Robinson (PR)
specs:
  H1:
    outlet_temperature: {value: 298.15, provenance: assumed}
    pressure_drop: {value: 0, unit: kPa, provenance: assumed}
  R1:
    outlet_temperature: {value: 298.15, provenance: assumed}
    pressure_drop: {value: 0, unit: kPa, provenance: assumed}
"""

#: The three pure liquids (298.15 K, 2000 kPa) mixed: their feed enthalpies.
PURE_LIQUIDS = (
    """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: FIB, ports: [{id: out, direction: out}]}
  - {id: FMEOH, ports: [{id: out, direction: out}]}
  - {id: FMTBE, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: B
    class: MixingSimple
    ports:
      - {id: a, direction: in}
      - {id: b, direction: in}
      - {id: c, direction: in}
      - {id: out, direction: out}
steps:
  - id: M1
    block: B
    class: MixingSimple
    ports:
      - {id: a, direction: in, delegates: a}
      - {id: b, direction: in, delegates: b}
      - {id: c, direction: in, delegates: c}
      - {id: out, direction: out, delegates: out}
streams:
"""
    + _pure("S1", "M1.a", "IB")
    + _pure("S2", "M1.b", "MEOH")
    + _pure("S3", "M1.c", "MTBE")
    + """\
  - id: S4
    from: M1.out
    to: P.in
    template: mix
"""
)


def _plant(tmp_path, flowsheet: str = FLOWSHEET, package: str = PACKAGES[0]) -> Workspace:
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: mtbe-liquid\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    simulation = SIMULATION.replace("Peng-Robinson (PR)", package)
    if flowsheet is PURE_LIQUIDS:
        simulation = simulation.split("specs:")[0]
    (root / "process/simulation.yaml").write_text(simulation)
    return Workspace(root)


def _row(audit: dict, uid: str) -> dict:
    return next(r for r in audit["closure"]["units"] if r["id"] == uid)


def _run(ws) -> tuple[dict, dict, list]:
    """The run's energy audit, DWSIM's result and the findings."""
    from chemeascode.integrations import dwsim

    seen = {}

    def solver(model, save):
        seen["out"] = dwsim.solve(model, save)
        return seen["out"]

    process, _ = load_process(ws.root)
    result = run(ws, process, "design", write=True, solver=solver)
    # a conversion short of the declared one is an error, asserted per
    # package
    assert not [f for f in result.findings if f.level == "error" and f.rule != SHORT], [
        f.format() for f in result.findings
    ]
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["converged"], entry["messages"]
    return entry["energy"], seen["out"], result.findings


def _molar_enthalpy(stream: dict) -> float:
    """kJ/mol (kJ/kg times kg/s over mol/s)."""
    return stream["mass_enthalpy_kJ_kg"] * stream["mass_flow_kg_s"] / stream["molar_flow_mol_s"]


def _reaction_heat(audit: dict) -> tuple[float, float, float]:
    """(extent mol/s, liquid reaction heat kJ/mol, ideal-gas reaction heat kJ/mol on DWSIM's
    formation enthalpies): pure liquids in, the plant's heat over the extent."""
    plant = audit["closure"]["plant"]
    extent = -_row(audit, "R1")["changes_mol_s"]["IB"]
    return extent, plant["heat_in_kW"] / extent, plant["formation_kW"] / extent


# -- the recorded run, replayed without DWSIM ---------------------------------------------------

#: DWSIM 9.0.5's result for FLOWSHEET with Peng-Robinson, recorded from
#: test_dwsim_liquid_reaction_heat_against_independent_values (unrounded).
RECORDED = {
    "converged": True,
    "streams": {
        "S1": {
            "temperature_K": 298.15,
            "mass_flow_kg_s": 1.5585,
            "molar_flow_mol_s": 27.777619348408525,
            "mass_enthalpy_kJ_kg": -373.8444929453534,
            "mole_fractions": {"IB": 1.0, "MEOH": 0.0, "MTBE": 0.0},
            "vapor_fraction": None,
        },
        "S2": {
            "temperature_K": 298.15,
            "mass_flow_kg_s": 0.8900555555555556,
            "molar_flow_mol_s": 27.777899146789718,
            "mass_enthalpy_kJ_kg": -1265.9861608706985,
            "mole_fractions": {"IB": 0.0, "MEOH": 1.0, "MTBE": 0.0},
            "vapor_fraction": None,
        },
        "S3": {
            "temperature_K": 277.49934057633163,
            "mass_flow_kg_s": 2.4485555555555556,
            "molar_flow_mol_s": 55.55551849519824,
            "mass_enthalpy_kJ_kg": -698.1400249095574,
            "mole_fractions": {"IB": 0.4999974818128894, "MEOH": 0.5000025181871106, "MTBE": 0.0},
            "vapor_fraction": 0.005168679847797862,
        },
        "S4": {
            "temperature_K": 298.15,
            "mass_flow_kg_s": 2.4485555555555556,
            "molar_flow_mol_s": 55.55551849519824,
            "mass_enthalpy_kJ_kg": -644.2390973215568,
            "mole_fractions": {"IB": 0.4999974818128894, "MEOH": 0.5000025181871106, "MTBE": 0.0},
            "vapor_fraction": None,
        },
        "S5": {
            "temperature_K": 298.15,
            "mass_flow_kg_s": 2.4485555555555556,
            "molar_flow_mol_s": 27.777899146789714,
            "mass_enthalpy_kJ_kg": -331.2428149443088,
            "mole_fractions": {
                "IB": 0.0,
                "MEOH": 1.0072697712469413e-05,
                "MTBE": 0.9999899273022875,
            },
            "vapor_fraction": None,
        },
        "S6": {
            "temperature_K": 298.15,
            "mass_flow_kg_s": 0.0,
            "molar_flow_mol_s": 0.0,
            "mass_enthalpy_kJ_kg": 0.0,
            "mole_fractions": {"IB": 0.0, "MEOH": 0.0, "MTBE": 0.0},
            "vapor_fraction": None,
        },
    },
    "units": {"H1": {"duty_kW": 131.97941569519665}, "R1": {"duty_kW": -1051.9341764637759}},
    "compounds": {
        "IB": {"dHf_298_kJ_kmol": -17100.0, "molar_mass": 56.10632, "database": "ChemSep"},
        "MEOH": {"dHf_298_kJ_kmol": -200940.0, "molar_mass": 32.04186, "database": "ChemSep"},
        "MTBE": {"dHf_298_kJ_kmol": -283500.0, "molar_mass": 88.14818, "database": "ChemSep"},
    },
}


def test_recorded_liquid_reactor_closes_on_the_formation_basis(tmp_path):
    """The audit on the recorded liquid run: every unit and the plant close, the reactor on the
    formation basis; the empty vapour outlet adds nothing. Hand check of R1: H in 2.44856 x
    -644.239 = -1577.44 kW, out 2.44856 x -331.243 = -811.07 kW, formation 27.7776 x (-283500 +
    17100 + 200940) / 1e3 = -1818.33 kW: -811.07 + 1577.44 - 1818.33 = -1051.96 kW, the duty."""
    ws = _plant(tmp_path)
    process, _ = load_process(ws.root)
    sim, doc, found = load(ws.root)
    assert not found
    model = translate(process, sim, doc, "design").model
    _, audit, _ = energy.audit(process, sim, doc, model, RECORDED)
    assert {r["id"]: r["status"] for r in audit["closure"]["units"]} == dict.fromkeys(
        ("M1", "H1", "R1"), "ok"
    )
    row = _row(audit, "R1")
    assert row["basis"] == "formation" and abs(row["residual_kW"]) < 1e-6
    assert row["formation_kW"] == pytest.approx(-1818.33, abs=0.01)
    plant = audit["closure"]["plant"]
    assert plant["status"] == "ok" and plant["basis"] == "formation"
    assert plant["feeds"] == ["S1", "S2"] and plant["products"] == ["S5", "S6"]
    extent, liquid, ideal_gas = _reaction_heat(audit)
    assert extent == pytest.approx(27.777619, rel=1e-6)  # all the isobutene
    assert ideal_gas == pytest.approx(-65.46, abs=1e-6)
    assert liquid == pytest.approx(-33.118, abs=1e-3)
    # the documented gap to the third published value (Arntz & Gottlieb): about 17 %
    assert liquid / ARNTZ_GOTTLIEB - 1 == pytest.approx(-0.168, abs=0.005)


# -- live ---------------------------------------------------------------------------------------


@dwsim_tests
@pytest.mark.parametrize("package", PACKAGES)
def test_dwsim_liquid_enthalpy_is_the_departure_from_the_ideal_gas(tmp_path, package):
    """Each pure liquid's enthalpy at 298.15 K and 2000 kPa against thermo's departure function
    of the same equation of state: the liquid is on the closure's ideal-gas basis, below it by
    the package's heat of vaporization."""
    thermo = pytest.importorskip("thermo")
    from chemicals import Pc, Tc, omega

    _, out, _ = _run(_plant(tmp_path, PURE_LIQUIDS, package))
    eos = getattr(thermo, EOS[package])
    for sid, cas in (("S1", "115-11-7"), ("S2", "67-56-1"), ("S3", "1634-04-4")):
        stream = out["streams"][sid]
        state = eos(Tc=Tc(cas), Pc=Pc(cas), omega=omega(cas), T=298.15, P=2.0e6)
        expected = state.H_dep_l / 1e3  # J/mol to kJ/mol
        got = _molar_enthalpy(stream)
        print(f"{package} {sid} ({cas}): DWSIM {got:.4f} kJ/mol, thermo {expected:.4f} kJ/mol")
        assert got == pytest.approx(expected, rel=DEPARTURE_TOLERANCE)
        assert got < -15.0  # a liquid, far below the ideal gas


@dwsim_tests
@pytest.mark.parametrize("package", PACKAGES)
def test_dwsim_liquid_phase_reactor_closes_on_the_formation_basis(tmp_path, package):
    ws = _plant(tmp_path, package=package)
    audit, out, findings = _run(ws)
    row = _row(audit, "R1")
    extent, liquid, ideal_gas = _reaction_heat(audit)
    fed = out["streams"]["S1"]["molar_flow_mol_s"]
    print(
        f"{package}: R1 duty {row['heat_in_kW']:.6g} kW, residual {row['residual_kW']:.3g} kW; "
        f"reactor inlet vapour fraction {out['streams']['S4']['vapor_fraction']}, conversion "
        f"{extent / fed:.4f}; plant heat over the extent {liquid:.4f} kJ/mol (ideal gas "
        f"{ideal_gas:.4f})"
    )
    assert row["basis"] == "formation" and row["status"] == "ok"
    assert abs(row["residual_kW"]) < DUTY_TOLERANCE_KW
    plant = audit["closure"]["plant"]
    assert plant["status"] == "ok" and abs(plant["residual_kW"]) < DUTY_TOLERANCE_KW
    assert out["streams"]["S6"]["mass_flow_kg_s"] < 1e-9  # all liquid: the vapour outlet empty
    assert extent > 0.5 * fed
    # the conversion reached is reported, and a shortfall is an error naming R1
    entry = json.loads((ws.root / "process/simulation-run.json").read_text())["cases"]["design"]
    results = next(u for u in entry["units"] if u["id"] == "R1")["results"]
    assert results["conversions"]["ETH"] == pytest.approx(extent / fed, abs=1e-6)
    short = [f for f in findings if f.rule == SHORT]
    assert bool(short) is SPLITS[package], [f.format() for f in short]
    assert all(f.ids == ["R1"] and "phase: mixed" in f.hint for f in short)


@dwsim_tests
def test_dwsim_liquid_reaction_heat_against_independent_values(tmp_path):
    """Peng-Robinson: pure isobutene and methanol to pure MTBE, all liquid at 298.15 K."""
    ws = _plant(tmp_path)
    audit, out, findings = _run(ws)
    extent, liquid, ideal_gas = _reaction_heat(audit)
    print(
        f"liquid reaction heat {liquid:.4f} kJ/mol (calorimetric {CALORIMETRIC}, Hess {HESS}: "
        f"{liquid / CALORIMETRIC - 1:+.2%}, {liquid / HESS - 1:+.2%}); ideal gas on DWSIM's "
        f"formation enthalpies {ideal_gas:.4f} kJ/mol"
    )
    print("streams:", {s: out["streams"][s] for s in ("S4", "S5")})
    # the declared conversion is reached (the reactor's inlet is one liquid): pure MTBE out
    assert extent == pytest.approx(out["streams"]["S1"]["molar_flow_mol_s"], rel=1e-6)
    assert out["streams"]["S5"]["mole_fractions"]["MTBE"] > 0.9999
    for reference in (CALORIMETRIC, HESS):
        assert liquid == pytest.approx(reference, rel=REACTION_HEAT_TOLERANCE)
        assert abs(ideal_gas / reference - 1) > 0.8  # without the liquid departures: far off
    # the project's formation enthalpies are chemicals' fallback here (none declared): within
    # the data tolerance of DWSIM's, a recorded limitation
    data = _row(audit, "R1")["formation_data"]
    assert data["status"] == "within-tolerance" and data["limitations"]
    process, _ = load_process(ws.root)
    record = json.loads((ws.root / "process/simulation-run.json").read_text())
    closure = {r.id: r for r in _energy_audit(process, record, ["design"])}
    assert closure["predictive.energy-closure"].status == "pass"
    assert _formation_data(process, record, ["design"]).status == "pass"
