"""Semi-batch kinetics beyond one temperature and one liquid (ADR 0074): an initiation with its
induction period and the doses that wait for it, the uninitiated scenario; a solid phase with a
rate per m2 of its shrinking particles; a temperature programme and a reactor at reflux; the
light of a photochemical rate law. Each against its closed form."""

import math

import pytest

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.rates import RateLaw
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.thermochemistry import R
from chemeascode.domains.process.batch_kinetics import (
    AVOGADRO,
    LIGHT_SPEED,
    PLANCK,
    breaks,
    photon_flux,
)
from chemeascode.domains.process.model import load, rules, stream_flows
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report, reactor_text
from chemeascode.domains.process.schema import Batch, Component, Tank, Vent
from chemeascode.domains.process.stirred_tank import Dose, TankError, solve_batch, solve_cstr
from chemeascode.domains.process.vent_vapour import henry_phase
from chemeascode.domains.safety.reaction_hazards import hazard_text, screen
from tests import test_semibatch as dosed
from tests import test_semibatch_vent as vented
from tests import test_vent_vapour as vapour
from tests.test_vent_vapour import GAS

V = {"A": 0.1, "B": 0.1, "C": 0.1, "S": 0.1, "M": 0.01, "P": 0.1}  # m3/kmol
CP = {"A": 150.0, "B": 150.0, "C": 150.0, "S": 150.0, "M": 25.0, "P": 150.0}  # kJ/(kmol K)
HEAT = -100000.0  # kJ/kmol


def _reactions(rate, stoichiometry=None, heat=HEAT):
    return Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": stoichiometry or {"A": -1, "B": 1},
                    "phase": "liquid",
                    "heat_of_reaction": {"value": heat, "provenance": "assumed"},
                    "rate": {"basis": "volume", "driving": "concentration", "provenance": "assumed"}
                    | rate,
                }
            ],
        }
    ).reactions


def _first_order(k, ea=0.0):
    return _reactions({"form": "power_law", "k": {"A": k, "Ea": ea}, "orders": {"A": 1}})


def _batch(**kw):
    return Batch.model_validate({"provenance": "assumed"} | kw)


def _solve(reactions, batch, charge, t=300.0, doses=(), components=None, isothermal_at=None):
    return solve_batch(
        reactions,
        charge,
        t,
        101.325,
        batch,
        {},
        Liquid(V),
        CP,
        isothermal_at,
        doses,
        components=components,
    )


# -- the initiation -----------------------------------------------------------------------------


@pytest.mark.parametrize("factor", [0.0, 0.1])
def test_an_induction_period_holds_the_rate_back_until_it_initiates(factor):
    """First order, ``dn/dt = -f k n`` before the initiation and ``-k n`` after it: ``n =
    n0 exp(-k (f t_i + t - t_i))``."""
    k, t_i, end = 1e-3, 1200.0, 3000.0
    batch = _batch(time=end, initiation={"time": t_i, "factor": factor, "provenance": "assumed"})
    result = _solve(_first_order(k), batch, {"A": 1.0, "S": 4.0})
    assert result.outlet["A"] == pytest.approx(math.exp(-k * (factor * t_i + end - t_i)), rel=1e-6)
    plain = _solve(_first_order(k), _batch(time=end), {"A": 1.0, "S": 4.0})
    assert plain.outlet["A"] == pytest.approx(math.exp(-k * end), rel=1e-6)
    assert result.initiation == {
        "time_s": t_i,
        "factor": factor,
        "reactions": ["R1"],
        "doses_waiting": 0,
    }
    assert not plain.initiation  # only where declared


def test_a_dose_into_an_uninitiated_charge_accumulates_until_it_initiates():
    """Dosed at q from 0, initiated at t_i (factor 0): ``n = q t`` to t_i, then ``q/k + (q t_i
    - q/k) exp(-k (t - t_i))`` while the dosing goes on."""
    k, t_i, t_d, q = 1e-2, 600.0, 3600.0, 1.0 / 3600.0
    batch = _batch(
        dosing=[{"stream": "D", "time": t_d}],
        initiation={"time": t_i, "provenance": "assumed"},
    )
    dose = Dose({"A": 1.0}, 300.0, [(0.0, t_d, 1.0)])
    result = _solve(_first_order(k), batch, {"S": 5.0}, doses=[dose])
    at_end = q / k + (q * t_i - q / k) * math.exp(-k * (t_d - t_i))
    assert result.outlet["A"] == pytest.approx(at_end, rel=1e-6)
    # the largest accumulation is at the initiation: all that was dosed by then
    assert result.max_accumulation == pytest.approx(q * t_i, rel=1e-6)
    assert result.max_accumulation_time == pytest.approx(t_i)
    # the cooling failure then: q t_i of A reacting in 5 + q t_i kmol of liquid
    rise = -HEAT * q * t_i / (150.0 * (5.0 + q * t_i))
    assert result.cooling_failure[2] == pytest.approx(300.0 + rise, rel=1e-9)
    # without the induction the dose reacts as it comes (the closed form of ADR 0050)
    plain = _solve(
        _first_order(k), _batch(dosing=[{"stream": "D", "time": t_d}]), {"S": 5.0}, doses=[dose]
    )
    assert plain.max_accumulation < 0.03 < result.max_accumulation


def test_a_dose_that_waits_for_the_initiation_and_the_uninitiated_scenario():
    """An initiation charge (5 % of A over 300 s) and the main dose interlocked on the
    initiation: the main dose starts at t_i. The uninitiated scenario (the initiation never
    comes) accumulates the initiation charge only; without the interlock, the whole dose."""
    k, t_i = 1e-2, 900.0
    spec = {
        "dosing": [
            {"stream": "I", "time": 300},
            {"stream": "D", "time": 3600, "after_initiation": True},
        ],
        "initiation": {"time": t_i, "provenance": "assumed"},
    }
    batch = _batch(**spec)
    first, main = batch.dosing
    assert batch.segments(main) == [(t_i, t_i + 3600.0, 1.0)]
    assert batch.segments(first) == first.segments() == [(0.0, 300.0, 1.0)]
    assert batch.dosing_end() == t_i + 3600.0
    assert breaks(batch) == [t_i]
    with pytest.raises(ValueError, match="give batch.initiation"):
        _batch(dosing=[{"stream": "D", "time": 60, "after_initiation": True}])
    doses = [
        Dose({"A": 0.05}, 300.0, batch.segments(first)),
        Dose({"A": 0.95}, 300.0, batch.segments(main), waits=True),
    ]
    result = _solve(_first_order(k), batch, {"S": 5.0}, doses=doses)
    assert result.dosing_time == pytest.approx(t_i + 3600.0)
    assert result.initiation["doses_waiting"] == 1
    scenario = result.initiation["uninitiated"]
    assert scenario["until_s"] == t_i
    # nothing reacts uninitiated: the initiation charge is all there, 0.05 of A in 5.05 kmol
    assert scenario["max_accumulation"] == pytest.approx(1.0)
    rise = -HEAT * 0.05 / (150.0 * 5.05)
    assert scenario["cooling_failure"]["mtsr_K"] == pytest.approx(300.0 + rise, rel=1e-9)
    # not interlocked: the main dose runs into the uninitiated charge from the start
    open_doses = [doses[0], Dose({"A": 0.95}, 300.0, [(0.0, 3600.0, 1.0)])]
    open_batch = _batch(
        dosing=[{"stream": "I", "time": 300}, {"stream": "D", "time": 3600}],
        initiation={"time": t_i, "provenance": "assumed"},
    )
    unlocked = _solve(_first_order(k), open_batch, {"S": 5.0}, doses=open_doses)
    scenario = unlocked.initiation["uninitiated"]
    assert scenario["until_s"] == 3600.0
    rise = -HEAT * 1.0 / (150.0 * 6.0)
    assert scenario["cooling_failure"]["mtsr_K"] == pytest.approx(300.0 + rise, rel=1e-9)


# -- a solid phase ------------------------------------------------------------------------------

M_MASS = 24.305  # kg/kmol of the test's solid (any value: the test's own)
DENSITY = 1738.0  # kg/m3 (the test's own)


def _components():
    return {
        n: Component(id=n, name=n, molar_mass=M_MASS if n == "M" else 50.0)
        for n in ("A", "B", "S", "M", "P")
    }


def _surface_reactions(k, orders=None):
    return _reactions(
        {
            "form": "power_law",
            "basis": "surface",
            "solid": "M",
            "k": {"A": k},
            "orders": orders or {},
        },
        {"M": -1, "A": -1, "P": 1},
    )


def test_a_surface_rate_on_shrinking_particles_follows_the_shrinking_sphere():
    """Zero order in the liquid, ``dn/dt = -k A_0 (n/n_0)^(2/3)`` with ``A_0 = 6 m_0 / (rho
    d)``: the particles shrink at a constant rate, ``1 - (1 - X)^(1/3) = t / tau``, ``tau = 3
    n_0 / (k A_0)``."""
    k, d, n0, end = 1e-6, 1e-4, 0.5, 1800.0
    batch = _batch(
        time=end,
        solids={"M": {"density": DENSITY, "diameter": d, "provenance": "assumed"}},
    )
    result = _solve(
        _surface_reactions(k), batch, {"M": n0, "A": 2.0, "S": 3.0}, components=_components()
    )
    area = 6.0 * n0 * M_MASS / (DENSITY * d)
    tau = 3.0 * n0 / (k * area)
    assert result.outlet["M"] == pytest.approx(n0 * (1.0 - end / tau) ** 3, rel=1e-6)
    assert result.solids["M"]["area_start_m2"] == pytest.approx(area, rel=1e-12)
    assert result.solids["M"]["area_end_m2"] == pytest.approx(area * (1 - end / tau) ** 2, rel=1e-6)
    # the content's volume: the liquid's and the solid's at its density, not a molar volume
    liquid = 0.1 * (result.outlet["A"] + result.outlet["S"] + result.outlet["P"])
    assert result.volume == pytest.approx(0.1 * 5.0 + n0 * M_MASS / DENSITY, rel=1e-12)
    end_volume = liquid + result.outlet["M"] * M_MASS / DENSITY
    assert end_volume > liquid
    # the same particles given by their specific area
    by_area = _batch(
        time=end,
        solids={
            "M": {"density": DENSITY, "specific_area": 6.0 / (DENSITY * d), "provenance": "assumed"}
        },
    )
    again = _solve(
        _surface_reactions(k), by_area, {"M": n0, "A": 2.0, "S": 3.0}, components=_components()
    )
    assert again.outlet["M"] == pytest.approx(result.outlet["M"], rel=1e-9)


def test_a_solid_phase_is_out_of_the_liquid():
    """A product precipitating as it forms (P carried as a solid): the rate per m3 is per m3 of
    the liquid, so first order in c_A stays ``n_A = n_0 exp(-k t)`` however dense the solid."""
    k, end = 1e-3, 2000.0
    reactions = _reactions(
        {"form": "power_law", "k": {"A": k}, "orders": {"A": 1}}, {"A": -1, "P": 1}
    )
    batch = _batch(time=end, solids={"P": {"density": 500.0, "provenance": "assumed"}})
    result = _solve(reactions, batch, {"A": 1.0, "S": 1.0}, components=_components())
    assert result.outlet["A"] == pytest.approx(math.exp(-k * end), rel=1e-6)
    assert result.solids["P"]["end_kmol_h"] == pytest.approx(1 - math.exp(-k * end), rel=1e-6)
    assert result.volume == pytest.approx(
        0.1 * (result.outlet["A"] + 1.0) + result.outlet["P"] * 50.0 / 500.0, rel=1e-6
    )
    # an order in a solid phase's concentration is refused: it has none in the liquid
    in_solid = _reactions(
        {"form": "power_law", "k": {"A": k}, "orders": {"A": 1, "P": 1}}, {"A": -1, "P": 1}
    )
    with pytest.raises(TankError, match="solid phase's concentration"):
        _solve(in_solid, batch, {"A": 1.0, "S": 1.0}, components=_components())


def test_a_surface_rate_refuses_what_it_cannot_take():
    k = 1e-5
    sized = {"M": {"density": DENSITY, "diameter": 1e-4, "provenance": "assumed"}}
    charge = {"M": 0.5, "A": 2.0, "S": 3.0}
    with pytest.raises(TankError, match="give it in batch.solids"):
        _solve(_surface_reactions(k), _batch(time=60), charge, components=_components())
    unsized = {"M": {"density": DENSITY, "provenance": "assumed"}}
    with pytest.raises(TankError, match="diameter or specific_area"):
        _solve(
            _surface_reactions(k), _batch(time=60, solids=unsized), charge, components=_components()
        )
    with pytest.raises(TankError, match="needs M charged"):
        _solve(
            _surface_reactions(k),
            _batch(time=60, solids=sized),
            {"A": 2.0, "S": 3.0},
            components=_components(),
        )
    dosed_batch = _batch(dosing=[{"stream": "D", "time": 60}], solids=sized)
    with pytest.raises(TankError, match="M is dosed"):
        _solve(
            _surface_reactions(k),
            dosed_batch,
            charge,
            components=_components(),
            doses=[Dose({"M": 0.1}, 300.0, [(0.0, 60.0, 1.0)])],
        )
    tank = Tank.model_validate({"volume": 1.0, "provenance": "assumed"})
    with pytest.raises(TankError, match="solid phase"):
        solve_cstr(_surface_reactions(k), charge, 300.0, 101.325, tank, {}, Liquid(V), CP)
    with pytest.raises(ValueError, match="solid:"):
        RateLaw.model_validate(
            {
                "form": "power_law",
                "basis": "surface",
                "driving": "concentration",
                "k": {"A": 1},
                "provenance": "assumed",
            }
        )


# -- the temperature -----------------------------------------------------------------------------


def _simpson(f, a, b, n=2000):
    h = (b - a) / n
    return (
        h / 3 * sum((1 if i in (0, n) else 4 if i % 2 else 2) * f(a + i * h) for i in range(n + 1))
    )


def test_a_temperature_programme_moves_the_rate_and_takes_the_content_s_heat():
    """Held at 300 K, ramped to 320 K over 100 s, held there: ``ln(n/n0) = -int k(T(t)) dt``
    (Arrhenius); the content's sensible heat ``C (320 - 300)``."""
    k, ea, end = 1e-4, 60000.0, 3000.0
    points = [(0.0, 300.0), (1000.0, 300.0), (1100.0, 320.0)]
    batch = _batch(time=end, program={"points": points, "provenance": "assumed"})
    result = _solve(_first_order(k, ea), batch, {"A": 1.0, "S": 4.0}, t=290.0)
    law = _first_order(k, ea)[0].rate

    def temperature(t):
        return 300.0 if t < 1000 else min(300.0 + 0.2 * (t - 1000.0), 320.0)

    exposure = _simpson(lambda t: law.k.k(temperature(t)), 0.0, 1000.0)
    exposure += _simpson(lambda t: law.k.k(temperature(t)), 1000.0, 1100.0)
    exposure += law.k.k(320.0) * (end - 1100.0)
    assert result.outlet["A"] == pytest.approx(math.exp(-exposure), rel=1e-6)
    assert result.temperature == pytest.approx(320.0)
    assert result.temperatures == {
        "mode": "program",
        "start_K": 300.0,
        "end_K": 320.0,
        "max_K": pytest.approx(320.0),
    }
    # the heat into the content: the reaction's and its sensible heat, 5 kmol at 150 kJ/(kmol K)
    assert result.heat_terms["content"] == pytest.approx(5 * 150.0 * 20.0, rel=1e-9)
    assert result.heat_terms["reaction"] == pytest.approx(HEAT * (1 - result.outlet["A"]), rel=1e-6)
    with pytest.raises(ValueError, match="first at 0 s"):
        _batch(time=1, program={"points": [(5.0, 300.0)], "provenance": "assumed"})
    with pytest.raises(ValueError, match="isothermal"):
        _batch(time=1, heat="adiabatic", program={"points": [(0, 300)], "provenance": "assumed"})
    # an outlet temperature given elsewhere than the programme's end is refused
    with pytest.raises(TankError, match="not the end of batch.program"):
        _solve(_first_order(k, ea), batch, {"A": 1.0, "S": 4.0}, isothermal_at=300.0)


def test_a_semibatch_doses_at_one_temperature_and_holds_at_another():
    """The doses warm to the temperature they meet: dosed at 300 K into 300 K, nothing; the
    programme then heats the content to 320 K for the post-reaction."""
    k, t_d = 1e-3, 1800.0
    points = [(0.0, 300.0), (t_d, 300.0), (t_d + 600.0, 320.0)]
    batch = _batch(
        dosing=[{"stream": "D", "time": t_d}],
        time=3600.0,
        program={"points": points, "provenance": "assumed"},
    )
    dose = Dose({"A": 1.0}, 300.0, [(0.0, t_d, 1.0)])
    result = _solve(_first_order(k), batch, {"S": 5.0}, doses=[dose])
    assert result.heat_terms["doses"] == pytest.approx(0.0, abs=1e-6)
    assert result.heat_terms["content"] == pytest.approx(6 * 150.0 * 20.0, rel=1e-9)
    assert result.temperature == pytest.approx(320.0)
    # a dose at 290 K into the content at 300 K: 1 kmol at 150 kJ/(kmol K) warmed by 10 K
    cold = _solve(
        _first_order(k), batch, {"S": 5.0}, doses=[Dose({"A": 1.0}, 290.0, [(0.0, t_d, 1.0)])]
    )
    assert cold.heat_terms["doses"] == pytest.approx(1500.0, rel=1e-9)


ANTOINE = {"a": 4.0, "b": 1200.0, "c": -50.0, "provenance": "assumed"}  # the test's own


def _reflux_components():
    found = {n: Component(id=n, name=n, molar_mass=50.0) for n in ("A", "B", "C")}
    found["S"] = Component(id="S", name="S", molar_mass=50.0, vapour_pressure=ANTOINE)
    return found


def _antoine_t(p_kpa):
    """K where the solvent's vapour pressure is *p_kpa* (log10 bar)."""
    return 1200.0 / (4.0 - math.log10(p_kpa / 100.0)) + 50.0


def test_a_reactor_at_reflux_follows_the_content_s_bubble_point():
    """A -> B + C, only the solvent volatile: ``x_S P_S(T) = P`` as the moles grow, the
    temperature rising with the conversion."""
    k = 1e-3
    reactions = _reactions(
        {"form": "power_law", "k": {"A": k}, "orders": {"A": 1}}, {"A": -1, "B": 1, "C": 1}
    )
    batch = _batch(time=3000.0, heat="reflux")
    result = _solve(reactions, batch, {"A": 2.0, "S": 3.0}, components=_reflux_components())
    start = _antoine_t(101.325 / (3.0 / 5.0))
    total = sum(result.outlet.values())
    assert result.temperatures["start_K"] == pytest.approx(start, rel=1e-9)
    assert result.temperature == pytest.approx(_antoine_t(101.325 / (3.0 / total)), rel=1e-9)
    assert result.temperature > start
    temps = [t for _, t, _, _ in result.profile]
    assert temps == sorted(temps)
    # the duty holds the content at its rising bubble point: its sensible heat counts
    assert result.heat_terms["content"] > 0
    with pytest.raises(TankError, match="no vapour_pressure"):
        comps = _reflux_components() | {
            "A": Component(id="A", name="A", molar_mass=50.0, normal_boiling_point=350.0)
        }
        _solve(reactions, batch, {"A": 2.0, "S": 3.0}, components=comps)
    with pytest.raises(TankError, match="bubble point"):
        _solve(
            reactions,
            batch,
            {"A": 2.0, "S": 3.0},
            components=_reflux_components(),
            isothermal_at=330.0,
        )
    with pytest.raises(ValueError, match="heat_up"):
        _batch(time=1, heat="reflux", heat_up=True)


# -- the light ------------------------------------------------------------------------------------


def _photo(quantum_yield, orders=None):
    return _reactions({"form": "photochemical", "k": {"A": quantum_yield}, "orders": orders or {}})


def test_the_photon_flux_of_a_lamp():
    # 1 W at 500 nm: lambda / (h c N_A) mol/s
    assert photon_flux(1.0, 500.0) == pytest.approx(
        500e-9 / (PLANCK * LIGHT_SPEED * AVOGADRO) / 1000.0, rel=1e-15
    )
    assert photon_flux(1.0, 500.0) == pytest.approx(4.1795e-9, rel=1e-4)  # kmol/s


def test_a_photochemical_rate_is_the_quantum_yield_times_the_photons_absorbed():
    """All the light absorbed, zero order: ``dn_A/dt = -Phi q_0``, ``q_0`` the lamp's photons;
    its power heats the content. A lamp on for half the batch converts half as much."""
    phi, watts_m3, nm, end = 0.5, 2000.0, 400.0, 1200.0
    light = {"power": watts_m3, "wavelength": nm, "provenance": "assumed"}
    batch = _batch(time=end, light=light)
    result = _solve(_photo(phi), batch, {"A": 1.0, "S": 4.0})
    q0 = photon_flux(watts_m3 * 0.5, nm)  # the charge: 5 kmol at 0.1 m3/kmol
    assert result.outlet["A"] == pytest.approx(1.0 - phi * q0 * end, rel=1e-9)
    assert result.light["photons_absorbed_kmol_h"] == pytest.approx(q0 * end, rel=1e-9)
    assert result.heat_terms["light"] == pytest.approx(-watts_m3 * 0.5 / 1000.0 * end, rel=1e-9)
    half = _solve(
        _photo(phi), _batch(time=end, light=light | {"on": [(0.0, 600.0)]}), {"A": 1.0, "S": 4.0}
    )
    assert 1.0 - half.outlet["A"] == pytest.approx(phi * q0 * 600.0, rel=1e-9)
    assert half.heat_terms["light"] == pytest.approx(-watts_m3 * 0.5 / 1000.0 * 600.0, rel=1e-9)


def test_beer_lambert_absorption_by_the_absorber():
    """The absorber A at ``c`` takes ``1 - 10^(-eps c l)`` of the light: first order at low
    absorbance, ``dn/dt = -Phi q_0 ln(10) eps l n / V``; an optically thick content takes it
    all (zero order)."""
    phi, nm, end = 1.0, 365.0, 600.0
    thin = {
        "power": 1000.0,
        "wavelength": nm,
        "absorber": "A",
        "absorptivity": 1e-3,
        "path_length": 0.01,
        "provenance": "assumed",
    }
    result = _solve(_photo(phi), _batch(time=end, light=thin), {"A": 1.0, "S": 4.0})
    q0 = photon_flux(1000.0 * 0.5, nm)
    # exact: d(n)/dt = -Phi q0 (1 - 10^(-eps n l / V)), V = 0.5 m3 constant; integrate it
    eps_l_v = 1e-3 * 0.01 / 0.5
    n, steps = 1.0, 20000
    h = end / steps
    for _ in range(steps):  # RK4
        f = lambda m: -phi * q0 * (1.0 - 10.0 ** (-eps_l_v * m))  # noqa: E731
        k1 = f(n)
        k2 = f(n + h / 2 * k1)
        k3 = f(n + h / 2 * k2)
        k4 = f(n + h * k3)
        n += h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    assert result.outlet["A"] == pytest.approx(n, rel=1e-8)
    thick = thin | {"absorptivity": 1e5}
    deep = _solve(_photo(phi), _batch(time=end, light=thick), {"A": 1.0, "S": 4.0})
    assert deep.outlet["A"] == pytest.approx(1.0 - phi * q0 * end, rel=1e-9)


def test_a_photochemical_rate_needs_its_light():
    with pytest.raises(TankError, match="need batch.light"):
        _solve(_photo(0.5), _batch(time=60), {"A": 1.0, "S": 4.0})
    tank = Tank.model_validate({"volume": 1.0, "provenance": "assumed"})
    with pytest.raises(ValueError, match="photochemical rate needs the light"):
        solve_cstr(_photo(0.5), {"A": 1.0}, 300.0, 101.325, tank, {}, Liquid(V), CP)
    with pytest.raises(ValueError, match="photochemical"):
        RateLaw.model_validate(
            {
                "form": "photochemical",
                "basis": "catalyst_mass",
                "driving": "concentration",
                "k": {"A": 1},
                "provenance": "assumed",
            }
        )
    with pytest.raises(ValueError, match="absorptivity"):
        _batch(
            time=1, light={"power": 1, "wavelength": 400, "absorber": "A", "provenance": "assumed"}
        )


def test_a_batch_without_adr_0074_terms_dumps_as_before():
    """A batch's dump is its outlet's fingerprint: none of the new keys unless given."""
    batch = _batch(time=5, dosing=[{"stream": "D", "time": 1}])
    assert set(batch.model_dump()) == {
        "time",
        "target",
        "heat",
        "catalyst_loading",
        "dosing",
        "provenance",
        "source",
    }
    assert set(batch.dosing[0].model_dump()) == {"stream", "time", "start"}


# -- in a plant -----------------------------------------------------------------------------------

INITIATED = dosed.FLOWSHEET.replace(
    "batch: {dosing: [{stream: S2, time: 3600}], provenance: assumed}",
    "batch: {dosing: [{stream: S2, time: 3600}], provenance: assumed,\n"
    "           initiation: {time: 1800, provenance: assumed}}",
)


def test_the_screening_reports_the_uninitiated_dosing(tmp_path):
    """The dose runs on into the uninitiated charge: half of it before the initiation, held
    back, and the whole dose in the uninitiated scenario; a warning where that scenario's
    MTSR is above the MTT."""
    ws = dosed._plant(tmp_path, INITIATED)
    assert not dosed._messages(ws)
    (row,) = reactor_report(ws.root).reactors
    assert row["tank"]["initiation"]["uninitiated"]["until_s"] == 3600.0
    assert "initiation at 1800 s" in reactor_text(reactor_report(ws.root))
    report = screen(ws.root)
    (entry,) = report.entries
    rise = 100000.0 / (6 * 150.0)
    assert entry.initiation["mtsr_K"] == pytest.approx(300.0 + rise, rel=1e-9)
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-initiation"]
    assert finding.level == "warning" and "uninitiated" in finding.message
    assert "uninitiated" in hazard_text(report)
    # interlocked on the initiation, nothing accumulates uninitiated
    waiting = INITIATED.replace("time: 3600}]", "time: 3600, after_initiation: true}]")
    report = screen(dosed._plant(tmp_path / "w", waiting).root)
    (entry,) = report.entries
    assert entry.initiation["mtsr_K"] is None
    assert not [f for f in report.findings if f.rule == "cheme.reactor-hazard-initiation"]


def test_the_rules_name_an_initiation_s_unknown_reaction(tmp_path):
    stray = INITIATED.replace("time: 1800, provenance", "time: 1800, reactions: [R9], provenance")
    process, found = load(dosed._plant(tmp_path, stray).root)
    messages = [f.message for f in found + rules(process) if f.rule == "cheme.process-reactor"]
    assert any("initiation" in m and "R9" in m for m in messages)


# -- a solid phase with the liquid, the vent and the reports -------------------------------------


def test_a_solid_charged_alone_waits_for_its_liquid():
    """The solid charged, the liquid dosed later: nothing reacts while the liquid is empty.
    First order in c_A per m3 of the liquid, ``dn_A/dt = q - k n_A``, ``n_A = q/k (1 -
    exp(-k t))`` whatever the solid; a surface rate zero order in the liquid shrinks the
    particles as when the liquid is there from the start."""
    k, t_d, q = 1e-3, 600.0, 2.0 / 600.0
    solids = {"M": {"density": DENSITY, "diameter": 1e-4, "provenance": "assumed"}}
    batch = _batch(dosing=[{"stream": "D", "time": t_d}], solids=solids)
    dose = Dose({"A": 2.0, "S": 3.0}, 300.0, [(0.0, t_d, 1.0)])
    inert = _solve(_first_order(k), batch, {"M": 0.5}, doses=[dose], components=_components())
    assert inert.outlet["A"] == pytest.approx(q / k * (1.0 - math.exp(-k * t_d)), rel=1e-6)
    assert inert.outlet["M"] == pytest.approx(0.5, rel=1e-12)
    ks, n0 = 1e-6, 0.5
    shrinking = _solve(
        _surface_reactions(ks), batch, {"M": n0}, doses=[dose], components=_components()
    )
    tau = 3.0 * n0 / (ks * 6.0 * n0 * M_MASS / (DENSITY * 1e-4))
    assert shrinking.outlet["M"] == pytest.approx(n0 * (1.0 - t_d / tau) ** 3, rel=1e-6)


def test_a_solid_the_batch_never_holds_is_refused():
    batch = _batch(time=60, solids={"P": {"density": 500.0, "provenance": "assumed"}})
    with pytest.raises(TankError, match="P is not in the batch"):
        _solve(_first_order(1e-3), batch, {"A": 1.0, "S": 4.0}, components=_components())


def test_a_solid_phase_is_no_solvent_for_a_henry_gas():
    """A -> B + G, G at its Henry solubility at the end, ``x_G = P / H`` of the liquid: an inert
    solid charged with it leaves the dissolved G as it is."""
    vent = {
        "stream": "V",
        "components": ["G"],
        "henry": {"G": {"points": [[300.0, 2000.0]], "provenance": "assumed"}},
    }
    solids = {"M": {"density": DENSITY, "provenance": "assumed"}}
    found = {}
    for solid in (1e-9, 10.0):
        batch = vented._batch(vent, solids=solids)
        result = solve_batch(
            vented._reactions(1e-3),
            {"S": 5.0, "M": solid},
            300.0,
            101.325,
            batch,
            {"G": GAS},
            Liquid(vented.V | {"G": 0.05}),
            vented.CP | {"G": 60.0, "M": 25.0},
            doses=[Dose({"A": 1.0}, 300.0, [(0.0, vented.DOSING, 1.0)])],
            vent_phase=henry_phase(Vent.model_validate(vent)),
            components=_components(),
        )
        liquid = {n: v for n, v in result.outlet.items() if n != "M"}
        assert result.outlet["G"] / sum(liquid.values()) == pytest.approx(
            101.325 / 2000.0, rel=1e-8
        )
        assert result.henry["G"]["state"] == "saturated"
        found[solid] = result.outlet["G"]
    assert found[10.0] == pytest.approx(found[1e-9], rel=1e-8)


# -- the duty with a moving temperature, the vent's peak -----------------------------------------


def _gas_dosed(program=None, light=None):
    """1 kmol A and 1 kmol of the inert N dosed at 280 K over 1 h into 5 kmol S at 300 K; N
    passes through to the vent (ideal-gas cp 3.5 R)."""
    spec = {"vent": {"stream": "V", "components": ["G"], "inerts": ["N"]}}
    if program is not None:
        spec["program"] = {"points": program, "provenance": "assumed"}
    if light is not None:
        spec["light"] = light
    return solve_batch(
        vented._reactions(1e-3),
        {"S": 5.0},
        300.0,
        101.325,
        vented._batch(**spec),
        {"G": GAS, "N": GAS},
        Liquid(vented.V),
        vented.CP,
        doses=[Dose({"A": 1.0, "N": 1.0}, 280.0, [(0.0, vented.DOSING, 1.0)])],
    )


def test_the_gas_passing_through_warms_once_to_the_temperature_it_met():
    """The passing gas's warming is the ``vent gas`` term alone, ``c (T - T_d)``, as without
    a programme; along a ramp 300 to 320 K over the dosing it meets 310 K on average."""
    cp_gas = 3.5 * R
    plain = _gas_dosed()
    assert plain.heat_terms["doses"] == pytest.approx(150.0 * 20.0, rel=1e-12)
    assert plain.heat_terms["vent gas"] == pytest.approx(cp_gas * 20.0, rel=1e-12)
    flat = _gas_dosed([(0.0, 300.0)])
    for term in ("doses", "vent gas", "reaction"):
        assert flat.heat_terms[term] == pytest.approx(plain.heat_terms[term], rel=1e-9)
    lamp = _gas_dosed(light={"power": 1.0, "wavelength": 400.0, "provenance": "assumed"})
    assert lamp.heat_terms["vent gas"] == pytest.approx(cp_gas * 20.0, rel=1e-9)
    ramp = _gas_dosed([(0.0, 300.0), (vented.DOSING, 320.0)])
    assert ramp.heat_terms["vent gas"] == pytest.approx(cp_gas * 30.0, rel=1e-9)
    assert ramp.heat_terms["doses"] == pytest.approx(150.0 * 30.0, rel=1e-9)


def test_a_lamp_alone_keeps_the_temperature_for_the_duty():
    """A dose at the batch's temperature needs no heat capacity: with a lamp the temperature
    does not move, so its duty is known as without one."""
    cp = {n: c for n, c in CP.items() if n != "C"}
    light = {"power": 100.0, "wavelength": 400.0, "provenance": "assumed"}
    dose = Dose({"A": 0.9, "C": 0.1}, 300.0, [(0.0, 3600.0, 1.0)])
    found = []
    for spec in ({}, {"light": light}):
        batch = _batch(dosing=[{"stream": "D", "time": 3600}], **spec)
        result = solve_batch(
            _first_order(1e-3),
            {"A": 0.1, "S": 4.0},
            300.0,
            101.325,
            batch,
            {},
            Liquid(V),
            cp,
            doses=[dose],
        )
        assert result.heat_missing == []
        assert result.heat_terms["doses"] == pytest.approx(0.0, abs=1e-9)
        found.append(result)
    assert "light" in found[1].heat_terms
    moved = _batch(
        dosing=[{"stream": "D", "time": 3600}],
        program={"points": [(0.0, 300.0), (3600.0, 310.0)], "provenance": "assumed"},
    )
    result = solve_batch(
        _first_order(1e-3),
        {"A": 0.1, "S": 4.0},
        300.0,
        101.325,
        moved,
        {},
        Liquid(V),
        cp,
        doses=[dose],
    )
    assert result.heat_terms is None
    assert "the batch's temperature moves" in result.heat_missing[0]


@pytest.mark.parametrize("factor", [0.0, 0.1])
def test_the_vent_s_peak_waits_for_the_initiation(factor):
    """A -> B + G vented, first order, held at *factor* until 1000 s: the gas peaks just after
    the initiation at ``k n_A``, ``n_A = exp(-factor k t_i - k (t - t_i))``, not at the
    start."""
    k, t_i = 1e-3, 1000.0
    batch = Batch.model_validate(
        {
            "time": 3000.0,
            "vent": {"stream": "V", "components": ["G"]},
            "initiation": {"time": t_i, "factor": factor, "provenance": "assumed"},
            "provenance": "assumed",
        }
    )
    result = solve_batch(
        vented._reactions(k), {"A": 1.0, "S": 4.0}, 300.0, 101.325, batch, {}, Liquid(V), CP
    )
    after = result.peak_vent_time - t_i  # the first step after the initiation
    assert 0.0 < after < 10.0
    assert result.peak_vent_flow == pytest.approx(
        k * math.exp(-factor * k * t_i - k * after), rel=1e-6
    )


def test_a_programme_returns_the_condensate_at_the_temperature_it_met():
    """A vent condenser at 270 K returning its condensate: held at 310 K from 10 s, the
    condensate comes back to 310 K, as at 310 K throughout."""
    pressure = vapour._clausius(50.0, 4000.0)
    phase = vapour._phase("S", pressure, condenser=270.0)
    vent = vapour.VAPOUR | {"condenser": {"temperature": 270.0, "provenance": "assumed"}}

    def returned(points):
        program = {"points": points, "provenance": "assumed"}
        result = vapour._run(vent, phase, batch=vented._batch(vent, time=7200, program=program))
        condensed = result.condensate["S"]
        return result.heat_terms["condensate return"], condensed, result

    held, condensed, flat = returned([(0.0, 310.0)])
    assert held == pytest.approx(condensed * 150.0 * 40.0, rel=1e-9)
    ramped, condensed, ramp = returned([(0.0, 300.0), (10.0, 310.0)])
    assert ramped == pytest.approx(condensed * 150.0 * 40.0, rel=1e-3)
    # the condenser's duty integrated over the run, as at 310 K throughout
    assert ramp.condenser_heat == pytest.approx(flat.condenser_heat, rel=1e-3)


PRODUCT_P = (
    "  - {id: P, name: P, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
    "     liquid_heat_capacity: 150, phase: solid}\ntemplates:"
)


def test_process_reactors_rates_the_liquid_without_its_solid(tmp_path, monkeypatch):
    """A -> P with P precipitating (batch.solids): the outlet's rate is ``k c_A`` of the
    liquid, ``x_A`` of A, B and S over their molar volume, the solid left out."""
    monkeypatch.setattr(
        dosed,
        "MATERIALS",
        dosed.MATERIALS.replace("templates:", PRODUCT_P).replace("[A, B, S]", "[A, B, S, P]"),
    )
    reactions = dosed.REACTIONS.replace("{A: -1, B: 1}", "{A: -1, P: 1}").replace("0.01", "3e-4")
    flowsheet = dosed.FLOWSHEET.replace(
        "provenance: assumed}\n    hazard",
        "time: 7200, provenance: assumed,\n"
        "           solids: {P: {density: 1200, provenance: assumed}}}\n    hazard",
    )
    ws = dosed._plant(tmp_path, flowsheet, reactions)
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written
    (row,) = reactor_report(ws.root).reactors
    (entry,) = row["reactions"]
    process, _ = load(ws.root)
    flows = stream_flows(process, process.flowsheet.streams[2], "design").components
    liquid = {n: kg / 44.05 for n, kg in flows.items() if n != "P" and kg}
    assert flows["P"] > 0.5 * 44.05  # a good part of it solid
    assert entry["rate"] == pytest.approx(3e-4 * liquid["A"] / (0.1 * sum(liquid.values())))


def test_process_reactors_leaves_a_photochemical_rate_to_the_tank(tmp_path):
    """The light is the tank's: no outlet rate of a photochemical law, and no light reported
    as missing."""
    reactions = dosed.REACTIONS.replace(
        "form: power_law, basis: volume, driving: concentration, k: {A: 0.01},\n"
        "            orders: {A: 1}",
        "form: photochemical, basis: volume, driving: concentration, k: {A: 0.5}",
    )
    flowsheet = dosed.FLOWSHEET.replace(
        "provenance: assumed}\n    hazard",
        "provenance: assumed,\n"
        "           light: {power: 2000, wavelength: 400, provenance: assumed}}\n    hazard",
    )
    ws = dosed._plant(tmp_path, flowsheet, reactions)
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written
    (row,) = reactor_report(ws.root).reactors
    (entry,) = row["reactions"]
    assert entry["rate"] is None and "photochemical" in entry["rate_note"]
    assert not [m for m in row["missing"] if "light" in m]
    assert row["tank"]["light"]["photons_absorbed_kmol_h"] > 0
