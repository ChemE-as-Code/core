"""The liquid-liquid equilibrium search of ``separations.lle`` against thermo's own flash."""

from __future__ import annotations

import warnings

import pytest

from chemeascode.domains.process.separations import lle

pytest.importorskip("thermo")

WATER, ETHYL_ACETATE = "7732-18-5", "141-78-6"


def _chemsep_nrtl(temperature: float):
    """thermo's NRTL with the ChemSep parameters of water and ethyl acetate (tau = b/T), the
    same ones ``thermodynamics.phase`` reads."""
    from thermo.interaction_parameters import IPDB

    from chemeascode.integrations.thermo import nrtl_ln_gammas

    cas = [WATER, ETHYL_ACETATE]
    b = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", cas, "bij")
    alpha = IPDB.get_ip_asymmetric_matrix("ChemSep NRTL", cas, "alphaij")
    return nrtl_ln_gammas(temperature, [[0.0, 0.0], [0.0, 0.0]], b, alpha)


def test_the_split_matches_thermos_multiphase_flash():
    """Same model and parameters, two algorithms: thermo's FlashVLN (gas allowed, none found
    at 1 atm) and the liquid-only search here find the same two liquids."""
    from chemeascode.domains.process.thermodynamics.phase import phase_determination

    z = [0.9, 0.1]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        flash = phase_determination(
            ["water", "ethyl acetate"],
            z,
            298.15,
            "K",
            1.01325,
            "bar(a)",
            {"liquid_phase_model": "NRTL", "vapor_phase_model": "ideal_gas"},
            True,
        )
    assert flash.gas_count == 0 and flash.liquid_count == 2
    eq = lle.split(_chemsep_nrtl(298.15), z)
    assert eq.liquids == 2 and eq.converged
    ours = sorted([eq.x1, eq.x2])
    theirs = sorted(flash.liquid_compositions)
    for a, b in zip(ours, theirs, strict=True):
        assert a == pytest.approx(b, abs=1e-5)
    small = min(flash.liquids_betas)
    assert min(eq.beta, 1 - eq.beta) == pytest.approx(small, abs=1e-5)


def test_one_liquid_is_reported_as_one_liquid():
    model = _chemsep_nrtl(298.15)
    for z in ([0.99, 0.01], [0.2, 0.8]):
        eq = lle.split(model, z)
        assert eq.liquids == 1 and eq.beta == 0.0
        assert eq.x1 == pytest.approx(z) and eq.x2 == pytest.approx(z)
        assert eq.messages


def test_a_split_is_an_iso_activity_point_with_lower_gibbs_energy():
    model = _chemsep_nrtl(298.15)
    eq = lle.split(model, [0.9, 0.1])
    assert eq.residual < lle.RESIDUAL_TOLERANCE
    g_two = (1 - eq.beta) * lle.gibbs_of_mixing(model, eq.x1) + eq.beta * lle.gibbs_of_mixing(
        model, eq.x2
    )
    assert g_two < lle.gibbs_of_mixing(model, [0.9, 0.1])
    # the lever rule closes
    for k in range(2):
        assert (1 - eq.beta) * eq.x1[k] + eq.beta * eq.x2[k] == pytest.approx(
            [0.9, 0.1][k], abs=1e-12
        )


def test_a_failed_split_of_an_unstable_mixture_is_not_one_liquid(monkeypatch):
    """When the stability test finds two liquids but the search collapses onto the mixture,
    the result is not converged, never a stable single liquid (which extraction would report
    as no two-phase region)."""
    model = _chemsep_nrtl(298.15)
    z = [0.9, 0.1]
    # a trial phase equal to the mixture makes the substitution start (and stay) trivial
    monkeypatch.setattr(lle, "stability", lambda model, z: (-0.01, list(z)))
    eq = lle.split(model, z)
    assert eq.liquids == 1 and not eq.converged
    assert "stability test found two" in eq.messages[0]
