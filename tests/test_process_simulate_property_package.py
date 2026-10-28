"""The benchmark of DWSIM's "Peng-Robinson (PR)" package for nitrogen, oxygen and argon: the claim
``methods.yml`` records for the simulation route (``thermodynamics.methods.simulation_claim``).

DWSIM is run as ``cheme process simulate`` runs it (``integrations.dwsim.solve``, the worker with
``details``): one flowsheet of feed streams, each a flash at a given temperature and pressure or a
saturation state at a given pressure and vapour fraction, solved in one worker call. The
reference is CoolProp 8.0.0 (pinned in the ``props`` extra), evaluated by the test: the reference
equations of state of the pure fluids (Span-JPCRD-2000 N2, Schmidt-FPE-1985/Stewart-JPCRD-1991
O2, Tegeler-JPCRD-1999 Ar) and, for the mixtures, the Gernert-Thesis-2013 (EOS-CG) reducing
functions of the three pairs. No reference value is typed in. Compositions are chosen for the
test (pure fluids, each pair at 10/50/90 %, and three ternaries resembling air, crude oxygen and
an argon-column feed), not data.

Tolerances are the claim (``claim.tolerances``): a point that fails narrows the claimed boxes,
never the tolerance. The boxes leave out the near-critical region (100-170 K above 2000 kPa(a)),
where enthalpy differences miss the tolerance, DWSIM's liquid density (Rackett) is applied beyond
the critical point and its pressure-vapour fraction flash fails for nitrogen-rich mixtures;
:func:`test_what_the_claim_leaves_out_fails` shows it. Densities other than the pure liquids'
are not claimed (``claim.not_claimed``); :func:`test_densities_left_out_of_the_claim` keeps the
reasons checked, so a change in DWSIM shows. ``tests/test_maturity.py`` covers how ``cheme
maturity`` uses the claim.

Live: needs CHEME_DWSIM_TESTS=1 and the DWSIM image (or CHEME_DWSIM_PATH).
"""

from __future__ import annotations

import itertools
import os
from functools import cache

import pytest

from chemeascode.domains.process.thermodynamics.methods import outside_claim, simulation_claim

CP = pytest.importorskip("CoolProp.CoolProp")

pytestmark = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

PACKAGE = "Peng-Robinson (PR)"
CLAIM = simulation_claim(PACKAGE)
TOL = CLAIM.tolerances if CLAIM else {}
#: component id -> (CAS, CoolProp fluid)
FLUIDS = {
    "N2": ("7727-37-9", "Nitrogen"),
    "O2": ("7782-44-7", "Oxygen"),
    "AR": ("7440-37-1", "Argon"),
}
CAS = {cid: cas for cid, (cas, _) in FLUIDS.items()}
#: Compositions chosen for the test (mole fractions), not data.
MIXTURES = {
    "N2": {"N2": 1.0},
    "O2": {"O2": 1.0},
    "AR": {"AR": 1.0},
    **{
        f"{a}-{b}-{round(100 * x)}": {a: x, b: round(1 - x, 10)}
        for a, b in itertools.combinations(FLUIDS, 2)
        for x in (0.1, 0.5, 0.9)
    },
    "air": {"N2": 0.7812, "O2": 0.2096, "AR": 0.0092},
    "crude oxygen": {"N2": 0.60, "O2": 0.38, "AR": 0.02},
    "argon-column feed": {"N2": 0.01, "O2": 0.89, "AR": 0.10},
}
TEMPERATURES = [*range(65, 150, 5), *range(150, 321, 10)]
PRESSURES = [100, 200, 300, 500, 700, 1000, 1500, 2000, 2500, 3000, 4000, 5000, 6000, 8000, 10000]
#: Saturation states (kPa(a)) at vapour fractions 0, 0.5 and 1: up to the claim's highest
#: two-phase pressure (DWSIM's PV flash fails nearer the critical point, which stops the solve)
SATURATION = [100, 150, 200, 300, 400, 500, 600, 800, 1000, 1200, 1500, 2000]
QUALITIES = (0.0, 0.5, 1.0)
#: Where the enthalpy differences start: every mixture's gas at 300 K, 100 kPa(a).
ANCHOR = (300, 100)
#: States closer than this to the reference phase boundary are compared as saturation states
#: only (DWSIM's boundary lies within the saturation-temperature tolerance of the reference's).
MARGIN_K = 1.0


def _feed(x: dict[str, float], p_kpa: float, **state) -> dict:
    return {"pressure_Pa": p_kpa * 1e3, "mass_flow_kg_s": 1.0, "mole_fractions": x, **state}


def _model(package: str = PACKAGE) -> dict:
    streams = []
    for name, x in MIXTURES.items():
        for t, p in itertools.product(TEMPERATURES, PRESSURES):
            feed = _feed(x, p, temperature_K=float(t))
            streams.append({"id": f"{name}|T|{t}|{p}", "kind": "material", "feed": feed})
        for p, q in itertools.product(SATURATION, QUALITIES):
            feed = _feed(x, p, vapor_fraction=q)
            streams.append({"id": f"{name}|Q|{q}|{p}", "kind": "material", "feed": feed})
    return {
        "compounds": [{"id": cid, "cas": cas} for cid, cas in CAS.items()],
        "property_package": package,
        "streams": streams,
        "units": [],
    }


@pytest.fixture(scope="module")
def solved():
    from chemeascode.integrations import dwsim

    out = dwsim.solve(_model(), details=True)
    assert out["converged"], out["messages"][:5]
    return out


# -- the reference ------------------------------------------------------------------------------


def _ids(x):
    return [c for c in FLUIDS if x.get(c, 0.0) > 0]


def _state(x):
    """A fresh CoolProp state (no history: a reused state starts from its last solution)."""
    ids = _ids(x)
    state = CP.AbstractState("HEOS", "&".join(FLUIDS[c][1] for c in ids))
    if len(ids) > 1:
        state.set_mole_fractions([x[c] for c in ids])
    return state


#: Above this pressure (kPa(a)) the claim holds one phase only (subcooled liquid at or below
#: 100 K, gas from 170 K), and a mixture's phase there is set from the critical temperatures:
#: CoolProp's mixture saturation search is not used above it (above the cricondenbar it fails
#: or returns a spurious envelope, e.g. O2/Ar 90/10 at 10000 kPa(a): 256 K, a hundred kelvin
#: above both critical temperatures).
TWO_PHASE_MAX_KPA = 2000


class NoReference(Exception):
    """CoolProp gave no reference value for a state the test does not expect it to miss."""


@cache
def _envelope(name: str, p_kpa: float):
    """Bubble and dew temperatures (K) of mixture *name* at *p_kpa*; None for a pure fluid at
    or above its critical pressure and a mixture above :data:`TWO_PHASE_MAX_KPA`. A failed
    search below raises :class:`NoReference`."""
    x = MIXTURES[name]
    ids = _ids(x)
    if len(ids) == 1 and p_kpa * 1e3 >= CP.PropsSI("pcrit", FLUIDS[ids[0]][1]):
        return None
    if len(ids) > 1 and p_kpa > TWO_PHASE_MAX_KPA:
        return None
    try:
        state = _state(x)
        state.update(CP.PQ_INPUTS, p_kpa * 1e3, 0)
        bubble = state.T()
        state.update(CP.PQ_INPUTS, p_kpa * 1e3, 1)
        return bubble, state.T()
    except ValueError as failure:
        raise NoReference(f"{name} at {p_kpa} kPa(a): no bubble/dew point ({failure})") from None


def _single_phase(name: str, t: float, p_kpa: float):
    """(phase, density kg/m3, molar enthalpy J/mol) of the reference at (t, p); None for a state
    within MARGIN_K of the phase boundary or inside it, or below the melting line of a pure
    fluid (the only reference failures expected). Any other failure raises
    :class:`NoReference`."""
    x = MIXTURES[name]
    ids = _ids(x)
    if t < max(CP.PropsSI("Tmin", FLUIDS[c][1]) for c in ids):
        return None
    envelope = _envelope(name, p_kpa)
    if envelope is not None:
        bubble, dew = envelope
        if bubble - MARGIN_K <= t <= dew + MARGIN_K:
            return None
        phase = "liquid" if t < bubble else "gas"
    else:
        phase = "liquid" if t < min(CP.PropsSI("Tcrit", FLUIDS[c][1]) for c in ids) else "gas"
    state = _state(x)
    if len(ids) > 1:  # CoolProp's mixture PT flash has no phase-stability test: impose it
        state.specify_phase(CP.iphase_liquid if phase == "liquid" else CP.iphase_gas)
    try:
        state.update(CP.PT_INPUTS, p_kpa * 1e3, t)
    except ValueError as failure:
        if len(ids) == 1 and "Tmelt" in str(failure):
            return None  # a solid in the reference
        raise NoReference(f"{name} at {t} K, {p_kpa} kPa(a): {failure}") from None
    return phase, state.rhomass(), state.hmolar()


def _saturation(name: str, p_kpa: float, q: float):
    """(temperature K, molar enthalpy J/mol, liquid and vapour mole fractions by id) of the
    reference at (p, q)."""
    x = MIXTURES[name]
    ids = _ids(x)
    state = _state(x)
    state.update(CP.PQ_INPUTS, p_kpa * 1e3, q)
    if len(ids) > 1:
        liquid = dict(zip(ids, state.mole_fractions_liquid(), strict=True))
        vapour = dict(zip(ids, state.mole_fractions_vapor(), strict=True))
    else:
        liquid = vapour = {ids[0]: 1.0}
    return state.T(), state.hmolar(), liquid, vapour


def _inside(x, t, p_kpa, claim=CLAIM) -> bool:
    return not outside_claim(claim, t, p_kpa, {CAS[c] for c in _ids(x)})


# -- the comparison -----------------------------------------------------------------------------


def _anchor(name: str) -> float:
    """The reference's molar enthalpy (J/mol) of mixture *name* at :data:`ANCHOR`."""
    state = _state(MIXTURES[name])
    state.update(CP.PT_INPUTS, ANCHOR[1] * 1e3, ANCHOR[0])
    return state.hmolar()


def single_phase_deviations(streams: dict, name: str, claim=CLAIM):
    """Every temperature-pressure state of mixture *name*, compared where the reference is one
    phase: rows ``(t, p, phase, inside the claim, density deviation (relative), enthalpy
    difference deviation kJ/kmol)``; a state the reference fails at has phase and deviations
    None."""
    h0, h0_ref = (
        streams[f"{name}|T|{ANCHOR[0]}|{ANCHOR[1]}"]["molar_enthalpy_kJ_kmol"],
        _anchor(name),
    )
    rows = []
    for t, p in itertools.product(TEMPERATURES, PRESSURES):
        inside = _inside(MIXTURES[name], t, p, claim)
        try:
            ref = _single_phase(name, float(t), float(p))
        except NoReference:
            rows.append((t, p, None, inside, None, None))  # counted, never covered
            continue
        if ref is None:
            continue
        phase, rho, h = ref
        got = streams[f"{name}|T|{t}|{p}"]
        d_rho = got["density_kg_m3"] / rho - 1
        d_h = (got["molar_enthalpy_kJ_kmol"] - h0) - (h - h0_ref)  # J/mol = kJ/kmol
        rows.append((t, p, phase, inside, d_rho, d_h))
    return rows


def saturation_deviations(streams: dict, name: str, claim=CLAIM):
    """Every saturation state of mixture *name*: rows ``(p, q, inside the claim (at the
    reference temperature), temperature deviation K, enthalpy difference deviation kJ/kmol,
    largest equilibrium mole-fraction deviation)``."""
    h0, h0_ref = (
        streams[f"{name}|T|{ANCHOR[0]}|{ANCHOR[1]}"]["molar_enthalpy_kJ_kmol"],
        _anchor(name),
    )
    rows = []
    for p, q in itertools.product(SATURATION, QUALITIES):
        got = streams[f"{name}|Q|{q}|{p}"]
        t, h, liquid, vapour = _saturation(name, float(p), q)
        d_x = 0.0
        if 0 < q < 1:
            phases = got["phases"]
            d_x = max(
                abs(phases[side]["mole_fractions"][c] - ref[c])
                for side, ref in (("liquid", liquid), ("vapor", vapour))
                for c in ref
            )
        d_h = (got["molar_enthalpy_kJ_kmol"] - h0) - (h - h0_ref)
        inside = _inside(MIXTURES[name], t, p, claim)
        rows.append((p, q, inside, got["temperature_K"] - t, d_h, d_x))
    return rows


@pytest.fixture(scope="module")
def compared(solved):
    """Mixture -> (single-phase rows, saturation rows)."""
    streams = solved["streams"]
    return {
        name: (single_phase_deviations(streams, name), saturation_deviations(streams, name))
        for name in MIXTURES
    }


# -- the claim ----------------------------------------------------------------------------------


def test_the_claim_is_recorded_and_inside_the_reference_equations():
    assert CLAIM is not None
    assert CLAIM.benchmark.test == "tests/test_process_simulate_property_package.py"
    assert set(CLAIM.components) == set(CAS.values())
    pairs = set(CP.get_global_param_string("mixture_binary_pairs_list").split(","))
    for a, b in itertools.combinations(sorted(CAS.values()), 2):
        assert f"{a}&{b}" in pairs or f"{b}&{a}" in pairs
    for cid, (cas, fluid) in FLUIDS.items():
        for box in CLAIM.regions[cas]:
            assert box.temperature_K[0] >= CP.PropsSI("Tmin", fluid), cid
            assert box.pressure_kPa[1] * 1e3 <= CP.PropsSI("pmax", fluid), cid
            # inside the grid: every claimed box edge is a grid point
            assert {*box.temperature_K} <= set(TEMPERATURES), (cid, box)
            assert {*box.pressure_kPa} <= set(PRESSURES), (cid, box)


def test_dwsim_version_parameters_and_settings_are_the_claimed(solved):
    assert solved["version"].startswith(CLAIM.simulator_version + ".") or (
        solved["version"] == CLAIM.simulator_version
    )
    kij = {
        "&".join(sorted(CAS[c] for c in p["components"])): p["kij"]
        for p in solved["interaction_parameters"]
    }
    assert kij == CLAIM.interaction_parameters.kij
    assert solved["package_settings"] == CLAIM.package_settings


@pytest.mark.parametrize("name", list(MIXTURES))
def test_single_phase_states_inside_the_claim(compared, name):
    rows = [r for r in compared[name][0] if r[3]]
    # every claimed state has a reference value: none is counted as covered without one
    assert [r[:2] for r in rows if r[2] is None] == [], name
    assert len(rows) > 100
    for t, p, phase, _, d_rho, d_h in rows:
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"], (name, t, p, phase, d_h)
        if len(_ids(MIXTURES[name])) == 1 and phase == "liquid":
            assert abs(d_rho) <= TOL["liquid_density_rel_pure"], (name, t, p, d_rho)


@pytest.mark.parametrize("name", list(MIXTURES))
def test_saturation_states_inside_the_claim(compared, name):
    rows = [r for r in compared[name][1] if r[2]]
    assert len(rows) >= 2 * len(QUALITIES)
    for p, q, _, d_t, d_h, d_x in rows:
        assert abs(d_t) <= TOL["saturation_temperature_abs_K"], (name, p, q, d_t)
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"], (name, p, q, d_h)
        assert d_x <= TOL["equilibrium_mole_fraction_abs"], (name, p, q, d_x)


def test_what_the_claim_leaves_out_fails(compared):
    """The near-critical region outside the boxes (pure fluids: no imposed phase in the
    reference): enthalpy differences beyond the tolerance, and densities wrong by orders of
    magnitude where DWSIM labels a supercritical state liquid."""
    outside = [
        r
        for name in FLUIDS
        for r in compared[name][0]
        if not r[3] and 100 < r[0] < 170 and r[2] is not None
    ]
    assert max(abs(r[5]) for r in outside) > TOL["enthalpy_difference_abs_kJ_per_kmol"]
    assert max(abs(r[4]) for r in outside) > 1.0


def test_densities_left_out_of_the_claim(compared):
    """Why densities other than the pure liquids' are not claimed (claim.not_claimed): DWSIM's
    liquid mixture density misses by more than the pure-liquid tolerance, its vapour density is
    wrong at isolated states where the enthalpy agrees, and supercritical oxygen at 170 K and
    10000 kPa(a) gets a liquid density."""
    liquid = max(
        abs(r[4]) for r in compared["N2-AR-50"][0] if r[3] and r[2] == "liquid" and r[0] < 110
    )
    assert 2 * TOL["liquid_density_rel_pure"] < liquid < 0.1
    for name, state in (
        ("air", (260, 200)),
        ("N2-O2-50", (250, 700)),
        ("crude oxygen", (190, 300)),
    ):
        t, p, phase, inside, d_rho, d_h = next(r for r in compared[name][0] if r[:2] == state)
        assert phase == "gas" and inside and d_rho < -0.03 and abs(d_h) < 20, (name, d_rho, d_h)
    t, p, phase, inside, d_rho, d_h = next(r for r in compared["O2"][0] if r[:2] == (170, 10000))
    assert inside and d_rho > 1.0 and abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"]
