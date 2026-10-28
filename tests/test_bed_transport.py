"""Transport in fixed beds (pre-release issue 157 item 4): the effectiveness factor of an intrinsic
rate law, the Weisz-Prater and Mears criteria, and what the bed and catalyst must give for them."""

import math
from types import SimpleNamespace

import pytest

from chemeascode.domains.chemistry.reactions import Reaction
from chemeascode.domains.process.bed_transport import effectiveness, thiele
from chemeascode.domains.process.fixed_bed import BedError, bed_limitations, solve_bed
from chemeascode.domains.process.schema import Bed

MW = {"A": 30, "B": 30}


def _law(A, **extra):
    rate = {
        "form": "power_law",
        "basis": "catalyst_mass",
        "driving": "concentration",
        "k": {"A": A},
        "orders": {"A": 1},
        "provenance": "assumed",
    } | extra
    return Reaction.model_validate({"id": "R", "stoichiometry": {"A": -1, "B": 1}, "rate": rate})


def _catalyst(**physical):
    base = {
        "bulk_density": 1000.0,
        "particle_density": 1600.0,
        "particle_diameter": 0.006,
        "bed_voidage": 0.4,
        "sphericity": 1.0,
        "porosity": 0.5,
        "tortuosity": 4.0,
        "effective_diffusivity": None,
    }
    return SimpleNamespace(physical=SimpleNamespace(**(base | physical)), deactivation=None)


def _bed(**extra):
    return Bed.model_validate(
        {
            "catalyst_mass": 500,
            "heat": "isothermal",
            "diameter": 1.0,
            "viscosity": 3e-5,
            "diffusivity": 4e-5,
            "provenance": "assumed",
        }
        | extra
    )


def test_effectiveness_limits():
    assert effectiveness(0.0) == 1.0
    assert effectiveness(1e-4) == pytest.approx(1.0, abs=1e-8)
    assert effectiveness(50.0) == pytest.approx(1 / 50.0, rel=1e-6)
    # first order: phi = L sqrt(k rho_p / De), independent of the concentration
    assert thiele(2.0, 1.0, 1.0, 1600, 0.001, 1e-6) == pytest.approx(
        thiele(4.0, 1.0, 2.0, 1600, 0.001, 1e-6)
    )


def test_an_intrinsic_first_order_law_is_the_effective_one_times_eta():
    k = 0.05  # m3/(kg s) on concentrations
    catalyst, bed = _catalyst(), _bed()
    intrinsic = solve_bed(
        [_law(k, scale="intrinsic")], {"A": 36.0}, 600, 500, bed, catalyst, {}, MW
    )
    de = 4e-5 * 0.5 / 4.0
    phi = 0.006 / 6 * math.sqrt(k * 1600 / de)
    eta = math.tanh(phi) / phi
    assert 0.1 < eta < 0.9  # a real limitation
    effective = solve_bed([_law(k * eta)], {"A": 36.0}, 600, 500, bed, catalyst, {}, MW)
    assert intrinsic.outlet["A"] == pytest.approx(effective.outlet["A"], rel=1e-6)
    assert any("effectiveness factor" in n for n in intrinsic.notes)


def test_weisz_prater_flags_an_effective_law_on_large_particles():
    k = 0.05
    small = solve_bed(
        [_law(k)], {"A": 36.0}, 600, 500, _bed(), _catalyst(particle_diameter=1e-4), {}, MW
    )
    large = solve_bed(
        [_law(k)], {"A": 36.0}, 600, 500, _bed(), _catalyst(particle_diameter=0.01), {}, MW
    )
    wp_small = small.transport["inlet"]["R"]["weisz_prater"]
    wp_large = large.transport["inlet"]["R"]["weisz_prater"]
    assert wp_large == pytest.approx(wp_small * 100**2, rel=1e-9)  # L^2
    assert not any("Weisz-Prater" in n for n in small.notes)
    assert any("Weisz-Prater" in n and "inlet" in n for n in large.notes)
    assert large.transport["inlet"]["R"]["mears"] is not None


def test_what_transport_needs():
    catalyst = _catalyst(porosity=None, tortuosity=None)
    with pytest.raises(BedError, match="intrinsic rate law"):
        solve_bed([_law(0.05, scale="intrinsic")], {"A": 36.0}, 600, 500, _bed(), catalyst, {}, MW)
    limits = bed_limitations(_bed(), catalyst)
    assert any(m.startswith("no transport checks") for m in limits)
    # without the data an effective law solves as before, without checks or notes about them
    result = solve_bed([_law(0.05)], {"A": 36.0}, 600, 500, _bed(), catalyst, {}, MW)
    assert result.transport == {} and not any("transport" in n for n in result.notes)
    # the new fields leave dumps unchanged while unset
    assert "diffusivity" not in Bed(catalyst_mass=1, provenance="assumed").model_dump()
    assert "scale" not in _law(1.0).rate.model_dump()


def test_more_refusals_and_both_gaps():
    from chemeascode.domains.chemistry.liquid import Liquid
    from chemeascode.domains.process.schema import Tank
    from chemeascode.domains.process.stirred_tank import TankError, solve_cstr

    zero = Reaction.model_validate(
        {
            "id": "R",
            "stoichiometry": {"A": -1, "B": 1},
            "rate": {
                "form": "power_law",
                "basis": "catalyst_mass",
                "driving": "concentration",
                "k": {"A": 1.0},
                "orders": {},
                "scale": "intrinsic",
                "provenance": "assumed",
            },
        }
    )
    with pytest.raises(BedError, match="no reactant with a positive order"):
        solve_bed([zero], {"A": 36.0}, 600, 500, _bed(), _catalyst(), {}, MW)
    tank = Tank(volume=1.0, catalyst_loading=10.0, provenance="assumed")
    with pytest.raises(TankError, match="no particle model"):
        solve_cstr(
            [_law(0.05, scale="intrinsic")],
            {"A": 36.0},
            600,
            500,
            tank,
            {},
            Liquid({"A": 0.1, "B": 0.1}),
        )
    both = bed_limitations(_bed(diameter=None), _catalyst(bed_voidage=None, porosity=None))
    assert [m.split(":")[0] for m in both] == [
        "no pressure drop",
        "no transport checks (Weisz-Prater, Mears)",
    ]


def test_a_reversible_intrinsic_law_keeps_its_diffusion_limit():
    """eta from the forward rate: near equilibrium the bed still runs below the intrinsic law."""
    gas = {"A": SimpleNamespace(), "B": SimpleNamespace()}
    k = 0.05
    law = {"reverse": "equilibrium", "scale": "intrinsic"}
    reaction = Reaction.model_validate(
        {
            "id": "R",
            "stoichiometry": {"A": -1, "B": 1},
            "reversible": True,
            "equilibrium_constant": {"a": 0.0, "provenance": "assumed"},
            "rate": {
                "form": "power_law",
                "basis": "catalyst_mass",
                "driving": "concentration",
                "k": {"A": k},
                "orders": {"A": 1},
                "provenance": "assumed",
            }
            | law,
        }
    )
    plain = reaction.model_copy(
        update={"rate": reaction.rate.model_copy(update={"scale": "effective"})}
    )
    limited = solve_bed(
        [reaction], {"A": 36.0}, 600, 500, _bed(catalyst_mass=50), _catalyst(), gas, MW
    )
    free = solve_bed([plain], {"A": 36.0}, 600, 500, _bed(catalyst_mass=50), _catalyst(), gas, MW)
    assert free.outlet["A"] < limited.outlet["A"] < 36.0
