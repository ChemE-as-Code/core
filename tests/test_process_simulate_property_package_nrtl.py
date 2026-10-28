"""The benchmark of DWSIM's "NRTL" package for ethanol + water at 101.3 kPa(a): the claim
``methods.yml`` records for it (``thermodynamics.methods.simulation_claim``), the first
activity-coefficient package with one.

The reference is measured vapour-liquid equilibrium, two independent isobaric data sets at
101.3 kPa (Kamihama et al. 2012, Lai et al. 2014; ``tests/data/vle_ethanol_water.yaml``, copied
from the NIST ThermoML files with their combined expanded uncertainties). DWSIM is run as
``cheme process simulate`` runs it (``integrations.dwsim.solve`` with ``details``): one feed per
measured liquid composition at its bubble point (vapour fraction 0), whose temperature and
incipient vapour are compared with the measured temperature and vapour composition. thermo
(the phase route's NRTL with an ideal gas, ``thermodynamics.phase``) evaluates the same bubble
points with the same parameters (ChemSep's NRTL table, which DWSIM's database holds too):
a second implementation, compared with the data and with DWSIM.

Tolerances are the claim's (``claim.tolerances``); at a point whose measured expanded
uncertainty is larger, that uncertainty is the tolerance (no model is held closer to a
measurement than the measurement is known). DWSIM's own pure-ethanol boiling point lies 0.35 K
above the measured one (:func:`test_pure_component_vapour_pressures`), which sets most of its
deviation at the ethanol end. What the claim leaves out is checked so that a change in DWSIM
shows (:func:`test_what_the_claim_leaves_out`): the azeotropic composition, and DWSIM's flash at a
vapour fraction between 0 and 1 near the azeotrope, which returns Raoult's law.

The DWSIM tests are live: they need CHEME_DWSIM_TESTS=1 and the DWSIM image (or
CHEME_DWSIM_PATH). The thermo tests run without DWSIM.
"""

from __future__ import annotations

import gc
import math
import os
import warnings
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chemeascode.domains.process.thermodynamics.methods import outside_claim, simulation_claim

pytest.importorskip("thermo")

dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

PACKAGE = "NRTL"
CLAIM = simulation_claim(PACKAGE)
TOL = CLAIM.tolerances if CLAIM else {}
CAS = {"ETOH": "64-17-5", "H2O": "7732-18-5"}
DATA = yaml.safe_load(
    (Path(__file__).parent / "data" / "vle_ethanol_water.yaml").read_text(encoding="utf-8")
)
SETS = ("kamihama-2012", "lai-2014")
P_KPA = 101.3
#: Bubble points around the azeotrope, to locate DWSIM's (liquid ethanol mole fractions).
AZEOTROPE_SCAN = [round(0.85 + 0.005 * i, 3) for i in range(11)]
#: Pure-component saturation pressures (kPa(a)) besides the measured ones: bracketing the
#: vapour pressures at the near-azeotrope flash temperatures (354-356 K), for Raoult's law.
EXTRA_SATURATION = {"ETOH": [110.0, 120.0], "H2O": [45.0, 50.0]}
#: Liquid compositions flashed at vapour fraction 0.5: one far from the azeotrope, two near it.
TWO_PHASE = (0.5, 0.835, 0.869)
#: Same parameters, two implementations: how closely DWSIM and thermo agree on a bubble point
#: (their pure-component vapour pressures differ, ethanol's by 0.2-0.3 K near 101.3 kPa).
AGREE_K, AGREE_Y = 0.3, 0.005


def _points(name: str) -> list[dict]:
    return DATA[name]["points"]


def _tol(key: str, uncertainty: float | None) -> float:
    return max(TOL[key], uncertainty or 0.0)


def _feed(x: float, p_kpa: float, q: float) -> dict:
    return {
        "pressure_Pa": p_kpa * 1e3,
        "mass_flow_kg_s": 1.0,
        "mole_fractions": {"ETOH": x, "H2O": round(1 - x, 10)},
        "vapor_fraction": q,
    }


def _saturation_pressures() -> dict[str, list[float]]:
    measured = DATA["kamihama-2012"]["vapour_pressure"]
    return {
        "ETOH": [r["P"] for r in measured["ethanol"]] + [P_KPA] + EXTRA_SATURATION["ETOH"],
        "H2O": [r["P"] for r in measured["water"]] + [P_KPA] + EXTRA_SATURATION["H2O"],
    }


def _model() -> dict:
    streams = {}
    bubbles = {p["x"] for name in SETS for p in _points(name)} | {*AZEOTROPE_SCAN, *TWO_PHASE}
    for x in sorted(bubbles):
        streams[f"B|{x}"] = _feed(x, P_KPA, 0.0)
    for x in TWO_PHASE:
        streams[f"Q|{x}"] = _feed(x, P_KPA, 0.5)
        streams[f"D|{x}"] = _feed(x, P_KPA, 1.0)
    for cid, pressures in _saturation_pressures().items():
        for p in pressures:
            streams[f"P|{cid}|{p}"] = _feed(1.0 if cid == "ETOH" else 0.0, p, 0.0)
    return {
        "compounds": [{"id": cid, "cas": cas} for cid, cas in CAS.items()],
        "property_package": PACKAGE,
        "streams": [{"id": sid, "kind": "material", "feed": f} for sid, f in streams.items()],
        "units": [],
    }


@pytest.fixture(scope="module")
def solved():
    from chemeascode.integrations import dwsim

    out = dwsim.solve(_model(), details=True)
    assert out["converged"], out["messages"][:5]
    return out["streams"] | {"_result": out}


def _dwsim_bubble(streams: dict, x: float) -> tuple[float, float]:
    """DWSIM's bubble temperature (K) and incipient vapour ethanol mole fraction at *x*."""
    got = streams[f"B|{x}"]
    assert got["incipient"]["phase"] == "vapor"
    return got["temperature_K"], got["incipient"]["mole_fractions"]["ETOH"]


# -- thermo -------------------------------------------------------------------------------------


@cache
def _constants():
    from chemeascode.domains.process.thermodynamics.coverage import load_constants

    return load_constants(list(CAS.values()))


@cache
def _thermo_bubble(x: float) -> tuple[float, float]:
    """thermo's bubble temperature (K) and vapour ethanol mole fraction at *x*: the phase
    route's NRTL (ChemSep parameters) with an ideal gas; the pure components from their vapour
    pressure."""
    from thermo import FlashVL

    from chemeascode.domains.process.thermodynamics.phase import ActivityCoefficientHandler

    with warnings.catch_warnings():
        # thermo leaves the data files it loads open: finalise them here, not in a later test
        warnings.simplefilter("ignore", ResourceWarning)
        constants, correlations = _constants()
        if x in (0.0, 1.0):
            i = 0 if x == 1.0 else 1
            found = correlations.VaporPressures[i].solve_property(P_KPA * 1e3), x
        else:
            zs = [x, 1 - x]
            handler = ActivityCoefficientHandler("NRTL", "ideal_gas")
            gas, liquid = handler.get_vapor_liquid_models(
                350.0, P_KPA * 1e3, zs, constants, correlations
            )
            state = FlashVL(constants, correlations, gas=gas, liquid=liquid).flash(
                P=P_KPA * 1e3, VF=0, zs=zs
            )
            found = state.T, state.gas.zs[0]
        gc.collect()
    return found


# -- what the worker reports (no DWSIM: stand-ins for its objects) ------------------------------


class _Table(dict):
    """A .NET dictionary as the worker uses it."""

    def ContainsKey(self, key):  # the .NET name
        return key in self

    @property
    def Keys(self):
        return list(self)


def _phase(fraction, x_ethanol):
    compounds = _Table(
        Ethanol=SimpleNamespace(MoleFraction=x_ethanol),
        Water=SimpleNamespace(MoleFraction=1 - x_ethanol),
    )
    properties = SimpleNamespace(
        density=900.0, molar_enthalpy=-40000.0, molarfraction=fraction, molecularWeight=20.0
    )
    return SimpleNamespace(Properties=properties, Compounds=compounds)


def test_the_worker_reports_the_incipient_phase_of_a_saturation_feed():
    from chemeascode.integrations.dwsim_worker import _details

    by_name = {"Ethanol": "ETOH", "Water": "H2O"}
    # DWSIM's phases: 0 the mixture, 2 vapour, 3 liquid; at a bubble point the vapour has no
    # fraction but holds the incipient composition
    bubble = SimpleNamespace(
        Phases={0: _phase(1.0, 0.1), 2: _phase(None, 0.44), 3: _phase(1.0, 0.1), 4: _phase(0, 0)}
    )
    found = _details(bubble, by_name, {"vapor_fraction": 0.0})
    assert set(found["phases"]) == {"liquid"}
    assert found["incipient"] == {
        "phase": "vapor",
        "mole_fractions": {"ETOH": 0.44, "H2O": pytest.approx(0.56)},
    }
    dew = SimpleNamespace(
        Phases={0: _phase(1.0, 0.4), 2: _phase(1.0, 0.4), 3: _phase(None, 0.05), 4: _phase(0, 0)}
    )
    assert _details(dew, by_name, {"vapor_fraction": 1})["incipient"]["phase"] == "liquid"
    assert "incipient" not in _details(dew, by_name, {"vapor_fraction": 0.5})
    assert "incipient" not in _details(dew, by_name, {"temperature_K": 300.0})
    assert "incipient" not in _details(dew, by_name)


def test_the_worker_reports_an_activity_package_entry_and_settings():
    from chemeascode.integrations.dwsim_worker import ACTIVITY_SETTINGS, _package

    names = {"H2O": "Water", "ETOH": "Ethanol", "MEOH": "Methanol"}
    entry = SimpleNamespace(A12=-57.9601, A21=1241.7396, B12=0, B21=0, C12=0, C21=0, alpha12=0.29)
    nrtl = SimpleNamespace(
        m_pr=SimpleNamespace(InteractionParameters=_Table()),
        m_uni=SimpleNamespace(InteractionParameters=_Table(Ethanol=_Table(Water=entry))),
        LiquidDensityCalculationMode_Subcritical="COSTALD",
        VaporPhaseFugacityCalculationMode="Ideal",
        LiquidFugacity_UsePoyntingCorrectionFactor=True,
        AutoEstimateMissingNRTLUNIQUACParameters=True,
        ActivityCoefficientModels_IgnoreMissingInteractionParameters=False,
    )
    found = _package(nrtl, names)
    pairs = {tuple(p["components"]): p for p in found["interaction_parameters"]}
    # stored as ethanol -> water: reported in that order, whichever order the model has
    assert pairs[("H2O", "ETOH")] == {
        "components": ["H2O", "ETOH"],
        "kij": None,
        "activity": {
            "components": ["ETOH", "H2O"],
            **{k: float(v) for k, v in vars(entry).items()},
        },
    }
    assert pairs[("H2O", "MEOH")]["activity"] is None
    assert set(found["package_settings"]) == {
        "LiquidDensityCalculationMode_Subcritical",
        *ACTIVITY_SETTINGS,
    }
    # an equation-of-state package: no activity entry, no activity settings
    pr = SimpleNamespace(
        m_pr=SimpleNamespace(InteractionParameters=_Table()),
        LiquidDensityCalculationMode_Subcritical="Rackett_and_ExpData",
        VaporPhaseFugacityCalculationMode="Ideal",
    )
    found = _package(pr, names)
    assert all(set(p) == {"components", "kij"} for p in found["interaction_parameters"])
    assert found["package_settings"] == {
        "LiquidDensityCalculationMode_Subcritical": "Rackett_and_ExpData"
    }


# -- the claim ----------------------------------------------------------------------------------


def test_the_claim_is_recorded_on_the_measured_isobar():
    assert CLAIM is not None
    assert CLAIM.benchmark.test == "tests/test_process_simulate_property_package_nrtl.py"
    assert set(CLAIM.components) == set(CAS.values()) and CLAIM.mixtures
    assert set(TOL) == {"bubble_temperature_abs_K", "vapour_mole_fraction_abs"}
    # every measured point is inside the claim, and the claim reaches no further: one isobar,
    # 101.3 kPa as the papers give it (four digits), between the lowest and highest measured
    # boiling temperatures
    for name in SETS:
        assert DATA[name]["pressure_kPa"] == P_KPA
        for p in _points(name):
            assert not outside_claim(CLAIM, p["T"], P_KPA, set(CAS.values())), (name, p)
    for boxes in CLAIM.regions.values():
        assert [(b.temperature_K, b.pressure_kPa) for b in boxes] == [
            ((351.2, 373.2), (101.25, 101.35))
        ]
    assert outside_claim(CLAIM, 351.5, 101.325, set(CAS.values())) == []
    assert outside_claim(CLAIM, 330.0, 40.0, set(CAS.values()))
    # the parameters claimed are ChemSep's NRTL table, which thermo ships (b12 = A12 / R)
    from thermo.interaction_parameters import IPDB

    nrtl = CLAIM.interaction_parameters.activity["&".join(sorted(CAS.values()))]
    cas = sorted(CAS.values())
    bij = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", cas, "bij")
    alpha = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", cas, "alphaij")
    r_cal = 1.98721  # cal/(mol K): DWSIM's NRTL takes A12 in cal/mol
    assert bij[0][1] == pytest.approx(nrtl["A12"] / r_cal, rel=1e-4)
    assert bij[1][0] == pytest.approx(nrtl["A21"] / r_cal, rel=1e-4)
    assert alpha[0][1] == alpha[1][0] == nrtl["alpha12"]
    assert nrtl["B12"] == nrtl["B21"] == nrtl["C12"] == nrtl["C21"] == 0.0


def test_the_two_data_sets_scatter_by_about_the_vapour_tolerance():
    """Why the vapour-composition tolerance is not tighter (methods.yml notes): the vapour's
    ethanol fraction rises with the liquid's, yet Lai et al.'s at 0.501 is below Kamihama et
    al.'s at 0.488, by more than Lai et al.'s stated uncertainty."""
    kamihama = {p["x"]: p for p in _points("kamihama-2012")}[0.488]
    lai = {p["x"]: p for p in _points("lai-2014")}[0.501]
    assert lai["y"] < kamihama["y"] and lai["U_y"] < 0.01 < TOL["vapour_mole_fraction_abs"]


@pytest.mark.parametrize("name", SETS)
def test_thermo_bubble_points_meet_the_claimed_tolerances(name):
    """The evidence is not DWSIM's alone: thermo, with the same parameters, meets the same
    tolerances against both data sets."""
    for p in _points(name):
        t, y = _thermo_bubble(p["x"])
        assert abs(t - p["T"]) <= _tol("bubble_temperature_abs_K", p["U_T"]), (name, p, t)
        if "U_y" in p:
            assert abs(y - p["y"]) <= _tol("vapour_mole_fraction_abs", p["U_y"]), (name, p, y)


@dwsim_tests
def test_dwsim_version_parameters_and_settings_are_the_claimed(solved):
    out = solved["_result"]
    assert out["version"].split(".")[:3] == CLAIM.simulator_version.split(".")
    [pair] = out["interaction_parameters"]
    assert pair["kij"] is None and CLAIM.interaction_parameters.kij == {}
    entry = dict(pair["activity"])
    order = [CAS[c] for c in entry.pop("components")]
    if order != sorted(order):  # the claim keys component 1 as the first CAS number
        swap = {f"{p}{i}{j}": f"{p}{j}{i}" for p in "ABC" for i, j in ("12", "21")}
        entry = {swap.get(k, k): v for k, v in entry.items()}
    assert entry == CLAIM.interaction_parameters.activity["&".join(sorted(order))]
    assert out["package_settings"] == CLAIM.package_settings


@dwsim_tests
@pytest.mark.parametrize("name", SETS)
def test_bubble_points_inside_the_claim(solved, name):
    for p in _points(name):
        t, y = _dwsim_bubble(solved, p["x"])
        assert abs(t - p["T"]) <= _tol("bubble_temperature_abs_K", p["U_T"]), (name, p, t)
        if "U_y" in p:
            assert abs(y - p["y"]) <= _tol("vapour_mole_fraction_abs", p["U_y"]), (name, p, y)


@dwsim_tests
def test_dwsim_and_thermo_agree(solved):
    """One model, one parameter set, two implementations: DWSIM's bubble points are thermo's
    within the differences of their pure-component vapour pressures."""
    for x in sorted({p["x"] for name in SETS for p in _points(name)}):
        t, y = _dwsim_bubble(solved, x)
        t_ref, y_ref = _thermo_bubble(x)
        assert abs(t - t_ref) <= AGREE_K and abs(y - y_ref) <= AGREE_Y, (x, t - t_ref, y - y_ref)


@dwsim_tests
def test_pure_component_vapour_pressures(solved):
    """DWSIM's pure-component boiling temperatures against the measured vapour pressures
    (Kamihama et al.) and boiling points (Lai et al.): water within 0.15 K; ethanol 0.1 K above
    at 40 kPa(a), 0.33-0.37 K above from 93 kPa(a), which carries into the bubble points at the
    ethanol end."""
    measured = DATA["kamihama-2012"]["vapour_pressure"]
    water = [solved[f"P|H2O|{r['P']}"]["temperature_K"] - r["T"] for r in measured["water"]]
    assert max(abs(d) for d in water) < 0.15, water
    ethanol = [solved[f"P|ETOH|{r['P']}"]["temperature_K"] - r["T"] for r in measured["ethanol"]]
    assert 0.05 < ethanol[0] < 0.15 and all(0.30 < d < 0.40 for d in ethanol[-2:]), ethanol
    lai = {p["x"]: p["T"] for p in _points("lai-2014")}
    assert abs(solved[f"P|H2O|{P_KPA}"]["temperature_K"] - lai[0.0]) < 0.05
    assert 0.30 < solved[f"P|ETOH|{P_KPA}"]["temperature_K"] - lai[1.0] < 0.40


def _clausius_clapeyron(solved: dict, cid: str, t: float) -> float:
    """DWSIM's vapour pressure (kPa) of *cid* at *t*, from its two saturation states that
    bracket *t* (ln p linear in 1/T)."""
    states = sorted(
        (solved[f"P|{cid}|{p}"]["temperature_K"], p) for p in _saturation_pressures()[cid]
    )
    (t1, p1), (t2, p2) = next(
        (a, b) for a, b in zip(states, states[1:], strict=False) if a[0] <= t <= b[0]
    )
    slope = math.log(p2 / p1) / (1 / t2 - 1 / t1)
    return p1 * math.exp(slope * (1 / t - 1 / t1))


@dwsim_tests
def test_what_the_claim_leaves_out(solved):
    """Pinned so that a change in DWSIM shows (methods.yml ``not_claimed``)."""
    lai = DATA["lai-2014"]["azeotrope"]
    # the azeotrope: DWSIM's NRTL puts it at x = 0.869, measured 0.891 +- 0.004; its
    # temperature is within the tolerance. From x = 0.86 to 0.875 DWSIM's bubble point returns
    # the trivial solution (vapour = liquid), so the azeotrope is located from either side.
    scan = [(x, *_dwsim_bubble(solved, x)) for x in AZEOTROPE_SCAN]
    trivial = [x for x, _, y in scan if y == pytest.approx(x, abs=1e-9)]
    assert trivial == [0.86, 0.865, 0.87, 0.875], trivial
    x1, _, y1 = [r for r in scan if r[2] > r[0] + 1e-9][-1]
    x2, _, y2 = next(r for r in scan if r[2] < r[0] - 1e-9)
    x_az = x1 + (y1 - x1) / ((y1 - x1) - (y2 - x2)) * (x2 - x1)
    t_az = min(t for _, t, _ in scan)
    assert 0.865 < x_az < 0.873 and lai["x"] - x_az > 3 * lai["U_x"], x_az
    assert abs(t_az - lai["T"]) <= _tol("bubble_temperature_abs_K", lai["U_T"]), t_az
    # a vapour fraction between 0 and 1: far from the azeotrope DWSIM's flash lies between its
    # bubble and dew temperatures; near it, it returns Raoult's law (DWSIM's own vapour
    # pressures, no activity coefficients) 2.7-2.9 K above both, and the solve reports nothing
    assert solved["_result"]["messages"] == []
    for x in TWO_PHASE:
        got = solved[f"Q|{x}"]
        t, bubble, dew = (solved[f"{k}|{x}"]["temperature_K"] for k in ("Q", "B", "D"))
        if x == 0.5:
            assert bubble < t < dew, (x, bubble, t, dew)
            continue
        assert t > max(bubble, dew) + 2.5, (x, bubble, t, dew)
        for cid in CAS:
            x_i = got["phases"]["liquid"]["mole_fractions"][cid]
            y_i = got["phases"]["vapor"]["mole_fractions"][cid]
            k_ideal = _clausius_clapeyron(solved, cid, t) / P_KPA
            assert y_i / x_i == pytest.approx(k_ideal, rel=0.005), (x, cid)
