"""The benchmark of DWSIM's "Soave-Redlich-Kwong (SRK)" package for nitrogen, oxygen and argon,
each alone: the claim ``methods.yml`` records for it (``thermodynamics.methods.simulation_claim``).

The same flowsheet, grid, reference (CoolProp 8.0.0, evaluated by the test, no reference value
typed in) and tolerances as the Peng-Robinson benchmark, whose helpers this module reuses
(``tests/test_process_simulate_property_package.py``). The claim holds the pure fluids only
(``mixtures: false``): DWSIM 9.0.5's SRK database has no interaction parameters for the three
pairs, and every tested mixture but nitrogen-argon 90/10 misses the saturation-temperature or
phase-composition tolerance (:func:`test_what_the_claim_leaves_out_fails`); that one meets them
narrowly and is not claimed either. The pure fluids hold the Peng-Robinson boxes. The numbers
``methods.yml`` quotes for what the claim leaves out are pinned by
:func:`test_what_the_claim_leaves_out_is_as_recorded`.

Live: needs CHEME_DWSIM_TESTS=1 and the DWSIM image (or CHEME_DWSIM_PATH).
"""

from __future__ import annotations

import os

import pytest

from chemeascode.domains.process.thermodynamics.methods import outside_claim, simulation_claim

CP = pytest.importorskip("CoolProp.CoolProp")

import tests.test_process_simulate_property_package as pr  # noqa: E402

pytestmark = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)

PACKAGE = "Soave-Redlich-Kwong (SRK)"
CLAIM = simulation_claim(PACKAGE)
TOL = CLAIM.tolerances if CLAIM else {}
MIXED = [name for name, x in pr.MIXTURES.items() if len(pr._ids(x)) > 1]


@pytest.fixture(scope="module")
def solved():
    from chemeascode.integrations import dwsim

    out = dwsim.solve(pr._model(PACKAGE), details=True)
    assert out["converged"], out["messages"][:5]
    return out


@pytest.fixture(scope="module")
def compared(solved):
    """Mixture -> (single-phase rows, saturation rows), as in the Peng-Robinson benchmark."""
    streams = solved["streams"]
    return {
        name: (
            pr.single_phase_deviations(streams, name, CLAIM),
            pr.saturation_deviations(streams, name, CLAIM),
        )
        for name in pr.MIXTURES
    }


def test_the_claim_is_recorded_for_the_pure_fluids_inside_the_reference_equations():
    assert CLAIM is not None
    assert CLAIM.benchmark.test == "tests/test_process_simulate_property_package_srk.py"
    assert set(CLAIM.components) == set(pr.CAS.values())
    assert CLAIM.mixtures is False
    assert CLAIM.tolerances == pr.TOL  # the Peng-Robinson benchmark's tolerances
    for cid, (cas, fluid) in pr.FLUIDS.items():
        for box in CLAIM.regions[cas]:
            assert box.temperature_K[0] >= CP.PropsSI("Tmin", fluid), cid
            assert box.pressure_kPa[1] * 1e3 <= CP.PropsSI("pmax", fluid), cid
            assert {*box.temperature_K} <= set(pr.TEMPERATURES), (cid, box)
            assert {*box.pressure_kPa} <= set(pr.PRESSURES), (cid, box)
    # every mixture state is outside, wherever it lies
    assert outside_claim(CLAIM, 300.0, 100.0, {pr.CAS["N2"], pr.CAS["O2"]})


def test_dwsim_version_parameters_and_settings_are_the_claimed(solved):
    assert solved["version"].startswith(CLAIM.simulator_version + ".") or (
        solved["version"] == CLAIM.simulator_version
    )
    # DWSIM's SRK database has no kij for the three pairs: none is read, none is recorded
    assert [p["kij"] for p in solved["interaction_parameters"]] == [None, None, None]
    assert CLAIM.interaction_parameters.kij == {}
    assert solved["package_settings"] == CLAIM.package_settings


@pytest.mark.parametrize("name", list(pr.FLUIDS))
def test_single_phase_states_inside_the_claim(compared, name):
    rows = [r for r in compared[name][0] if r[3]]
    assert [r[:2] for r in rows if r[2] is None] == [], name
    assert len(rows) > 100
    for t, p, phase, _, d_rho, d_h in rows:
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"], (name, t, p, phase, d_h)
        if phase == "liquid":
            assert abs(d_rho) <= TOL["liquid_density_rel_pure"], (name, t, p, d_rho)


@pytest.mark.parametrize("name", list(pr.FLUIDS))
def test_saturation_states_inside_the_claim(compared, name):
    rows = [r for r in compared[name][1] if r[2]]
    assert len(rows) >= 2 * len(pr.QUALITIES)
    for p, q, _, d_t, d_h, _ in rows:
        assert abs(d_t) <= TOL["saturation_temperature_abs_K"], (name, p, q, d_t)
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"], (name, p, q, d_h)


def test_what_the_claim_leaves_out_fails(compared):
    """The near-critical region outside the boxes (pure fluids), and the mixtures: without
    interaction parameters their bubble and dew temperatures or equilibrium compositions miss
    the tolerances, and no mixture state counts as inside."""
    outside = [
        r
        for name in pr.FLUIDS
        for r in compared[name][0]
        if not r[3] and 100 < r[0] < 170 and r[2] is not None
    ]
    assert max(abs(r[5]) for r in outside) > TOL["enthalpy_difference_abs_kJ_per_kmol"]
    assert max(abs(r[4]) for r in outside if r[2] == "liquid") > TOL["liquid_density_rel_pure"]
    for name in MIXED:
        single, saturation = compared[name]
        assert not any(r[3] for r in single) and not any(r[2] for r in saturation), name
    # every tested mixture but nitrogen-argon 90/10 misses a tolerance; that one only narrowly
    # meets them (bubble and dew temperatures within 0.3 K, by a few hundredths)
    for name in MIXED:
        saturation = compared[name][1]
        d_t = max(abs(r[3]) for r in saturation)
        d_x = max(r[5] for r in saturation)
        missed = (
            d_t > TOL["saturation_temperature_abs_K"] or d_x > TOL["equilibrium_mole_fraction_abs"]
        )
        assert missed == (name != "N2-AR-90"), (name, d_t, d_x)
        if name == "N2-AR-90":
            assert d_t > 0.8 * TOL["saturation_temperature_abs_K"], d_t


def _row(compared, name, state):
    return next(r for r in compared[name][0] if r[:2] == state)


def test_what_the_claim_leaves_out_is_as_recorded(compared):
    """The figures methods.yml quotes in the SRK claim's comment and ``not_claimed``."""
    # near-critical argon, outside the boxes: 322 kJ/kmol and -9 % liquid density
    _, _, phase, inside, d_rho, d_h = _row(compared, "AR", (150, 5000))
    assert not inside and phase == "liquid"
    assert 300 < d_h < 345 and -0.10 < d_rho < -0.08
    # mixtures: up to 0.72 K (N2-O2 50/50, bubble point at 2000 kPa(a)) and 0.0115 mole fraction
    # (N2-O2 50/50, 100 kPa(a))
    saturation = [(name, r) for name in MIXED for r in compared[name][1]]
    name, worst = max(saturation, key=lambda nr: abs(nr[1][3]))
    assert (name, worst[0], worst[1]) == ("N2-O2-50", 2000, 0.0) and 0.70 < abs(worst[3]) < 0.75
    name, worst = max(saturation, key=lambda nr: nr[1][5])
    assert (name, worst[0], worst[1]) == ("N2-O2-50", 100, 0.5) and 0.011 < worst[5] < 0.012
    # gas density (not claimed): within 0.8 % of the reference up to 2000 kPa(a) for the pure
    # fluids, -4.7 % for nitrogen at 170 K, 10000 kPa(a); supercritical oxygen and argon there
    # get a liquid (Rackett) density wrong by orders of magnitude, while the enthalpy holds
    for cid in pr.FLUIDS:
        gas = [r for r in compared[cid][0] if r[3] and r[2] == "gas" and r[1] <= 2000]
        assert max(abs(r[4]) for r in gas) < 0.008, cid
    assert -0.05 < _row(compared, "N2", (170, 10000))[4] < -0.04
    for cid in ("O2", "AR"):
        _, _, phase, inside, d_rho, d_h = _row(compared, cid, (170, 10000))
        assert inside and phase == "gas" and d_rho > 100
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"]
