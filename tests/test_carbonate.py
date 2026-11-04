"""The anolyte model interface (domains/chemistry/anolyte.py) and its first model,
``well-mixed-carbonate`` v1 (domains/chemistry/carbonate.py): equilibrium speciation from the
charge balance, the conserved-quantity rates, degassing, the registry; and that the NaCl
electrolyte route stays free of KOH and carbonate.

Reference values are textbook carbonate chemistry with the model's own constants (Kw = 1e-14,
pK1 = 6.37, pK2 = 10.32): the pH of a strong base, the bicarbonate point (pK1 + pK2) / 2 and a
closed charge balance. The agreement with the authors' model of process-library#329 is in
tests/test_electrolysis_duty.py, where it runs through the duty.
"""

from __future__ import annotations

import itertools
import math

import pytest

from chemeascode.domains.chemistry.anolyte import (
    AnolyteModel,
    ReservoirFluxes,
    UnknownAnolyteModel,
    anolyte_model,
    anolyte_models,
)
from chemeascode.domains.chemistry.carbonate import (
    HENRY_CO2,
    PK1,
    PK2,
    WellMixedCarbonate,
    charge_closure,
)

F = 96485.33212


def _model(**kwargs) -> WellMixedCarbonate:
    return anolyte_model("well-mixed-carbonate", **kwargs)  # type: ignore[return-value]


def test_the_model_is_registered_and_implements_the_protocol():
    assert "well-mixed-carbonate" in anolyte_models()
    model = _model()
    assert isinstance(model, AnolyteModel)
    assert (model.id, model.version) == ("well-mixed-carbonate", 1)
    assert [name for name, _ in model.state] == ["cation", "carbon", "volume"]
    described = model.describe()
    assert described["constants"] == {
        "Kw": 1e-14,
        "pK1": 6.37,
        "pK2": 10.32,
        "henry_co2_mol_l_atm": 0.034,
    }
    assert described["validity"]["ionic_strength_mol_l"] == [0.0, 1.5]
    assert any("activities" in text for text in described["limitations"])


def test_an_unknown_model_is_refused_never_defaulted():
    with pytest.raises(UnknownAnolyteModel) as failure:
        anolyte_model("finite-rate-carbonate")
    assert failure.value.known == anolyte_models()
    with pytest.raises(ValueError, match="monovalent"):
        anolyte_model("well-mixed-carbonate", cation="Ca++")


# -- speciation ---------------------------------------------------------------------------------


def test_ph_of_1_m_koh_is_14():
    model = _model()
    s = model.speciate(model.initial({"hydroxide": 1.0}, 1.0))
    assert s.ph == pytest.approx(14.0, abs=1e-9)
    assert s.concentrations["OH-"] == pytest.approx(1.0, rel=1e-12)
    assert s.ionic_strength_mol_l == pytest.approx(1.0, rel=1e-12)


def test_ph_of_a_bicarbonate_solution_is_near_the_bicarbonate_point():
    """0.1 M of MHCO3: pH ~ (pK1 + pK2) / 2 = 8.345 (the exact root differs by the water and
    the small CO2 and CO3-2 terms, well below 0.01)."""
    model = _model(cation="Na+")
    s = model.speciate(model.initial({"bicarbonate": 0.1}, 2.0))
    assert s.ph == pytest.approx((PK1 + PK2) / 2, abs=0.01)
    assert s.concentrations["HCO3-"] == pytest.approx(0.1, rel=0.03)


def test_carbonate_and_co2_solutions():
    model = _model()
    # 0.1 M K2CO3: CO3-2 hydrolysis, [OH-] ~ sqrt(Kw / K2 * c) -> pH ~ 11.66
    s = model.speciate(model.initial({"carbonate": 0.1}, 1.0))
    assert s.ph == pytest.approx(14 + math.log10(math.sqrt(1e-14 / 10**-PK2 * 0.1)), abs=0.02)
    # 0.01 M dissolved CO2: a weak acid, [H+] ~ sqrt(K1 c) -> pH ~ 4.19
    s = model.speciate(model.initial({"co2": 0.01}, 1.0))
    assert s.ph == pytest.approx(-math.log10(math.sqrt(10**-PK1 * 0.01)), abs=0.01)
    # pure water
    assert model.speciate([0.0, 0.0, 1.0]).ph == pytest.approx(7.0, abs=1e-9)


@pytest.mark.parametrize(
    ("cation", "carbon"),
    list(itertools.product([0.0, 1e-9, 1e-4, 0.01, 0.5, 1.0, 3.0], [0.0, 1e-9, 1e-3, 0.3, 1.0])),
)
def test_the_charge_balance_closes(cation, carbon):
    model = _model()
    s = model.speciate([cation, carbon, 1.0])
    scale = cation + carbon + s.concentrations["H+"] + s.concentrations["OH-"]
    assert abs(s.charge_residual_mol_l) <= 1e-12 * scale
    c = s.concentrations
    assert c["CO2"] + c["HCO3-"] + c["CO3-2"] == pytest.approx(carbon, rel=1e-12, abs=1e-30)
    assert s.iterations < 60


def test_speciation_on_the_volume():
    """A state is amounts: the same amounts in ten times the volume are a tenth the
    concentration."""
    model = _model()
    one = model.speciate([0.5, 0.2, 1.0])
    ten = model.speciate([0.5, 0.2, 10.0])
    assert ten.concentrations["K+"] == pytest.approx(one.concentrations["K+"] / 10)
    assert model.speciate([0.5, 0.2, 1.0], 10.0).ph == ten.ph
    with pytest.raises(ValueError, match="empty"):
        model.speciate([0.5, 0.2, 0.0])


# -- the balance --------------------------------------------------------------------------------


def _bpm_fluxes(current: float, wde: float, cx: float) -> ReservoirFluxes:
    co = (1 - wde) * current / F
    return ReservoirFluxes(
        ions={"OH-": (wde - 1) * current / F, "K+": -(1 - cx) * co, "HCO3-": cx * co}
    )


def test_rates_from_the_cell_fluxes_on_conserved_quantities():
    model = _model()
    fluxes = _bpm_fluxes(1.0, 0.95, 0.66)
    assert charge_closure(fluxes, "K+") == pytest.approx(0.0, abs=1e-20)
    d = model.rates([1.0, 0.0, 1.0], fluxes, 0.0)
    co = 0.05 / F
    assert d == pytest.approx([-0.34 * co, 0.66 * co, 0.0], rel=1e-12)


def test_dosing_bleed_and_make_up():
    model = _model()
    fluxes = ReservoirFluxes(dosing={"K+": 2e-6, "OH-": 2e-6}, volume_in=1e-6 + 5e-7, bleed=2e-7)
    d = model.rates([0.8, 0.1, 2.0], fluxes, 0.0)
    assert d[0] == pytest.approx(2e-6 - 2e-7 * 0.8 / 2.0)
    assert d[1] == pytest.approx(-2e-7 * 0.1 / 2.0)
    assert d[2] == pytest.approx(1.5e-6 - 2e-7)
    with pytest.raises(ValueError, match="carries no Cl-"):
        model.rates([0.8, 0.1, 2.0], ReservoirFluxes(ions={"Cl-": 1.0}), 0.0)


def test_degassing_above_saturation_only():
    off = _model()
    assert off.losses([0.0, 0.01, 1.0]) == {"CO2": 0.0}
    model = _model(kla_per_s=1e-3, co2_partial_pressure_atm=1.0)
    state = [0.0, 0.1, 2.0]  # 0.05 M CO2 at pH ~ 4: above 0.034 M
    co2 = model.speciate(state).concentrations["CO2"]
    assert model.losses(state)["CO2"] == pytest.approx(1e-3 * 2.0 * (co2 - HENRY_CO2))
    below = [0.0, 0.02, 1.0]
    assert model.losses(below)["CO2"] == 0.0
    # an alkaline anolyte holds almost no CO2: nothing leaves
    assert model.losses([1.0, 0.3, 1.0])["CO2"] == 0.0


def test_initial_composition_and_its_refusals():
    model = _model()
    state = model.initial({"hydroxide": 1.0, "carbonate": 0.1, "bicarbonate": 0.05}, 0.5)
    assert state == pytest.approx([0.5 * (1.0 + 0.2 + 0.05), 0.5 * 0.15, 0.5])
    with pytest.raises(ValueError, match="chloride"):
        model.initial({"chloride": 1.0}, 1.0)
    with pytest.raises(ValueError, match="positive"):
        model.initial({"hydroxide": 1.0}, 0.0)


# -- the NaCl electrolyte route stays free of KOH and carbonate ---------------------------------


def test_the_nacl_route_does_not_list_or_run_koh_or_carbonate():
    """The KOH/carbonate anolyte lives in this model only: the qualified electrolyte route
    (electrolytes.yml) runs NaCl-H2O alone, lists KOH and the carbonates as apparent
    electrolytes it refuses, and has no system with potassium or carbon."""
    from chemeascode.domains.process.thermodynamics import electrolytes as el

    table = el.electrolyte_table()
    assert [s.id for s in table.systems] == ["NaCl-H2O"]
    for system in table.systems:
        elements = {e for sp in system.species for e in system.species_elements(sp.id)}
        assert not elements & {"K", "C"}
    for name in ("KOH-H2O", "K2CO3-H2O", "KHCO3-H2O", "carbonate"):
        with pytest.raises(el.ElectrolyteError) as failure:
            table.system(name)
        assert failure.value.rule == "cheme.process-electrolyte-system"
    with pytest.raises(el.ElectrolyteError):
        el.electrolyte_state(298.15, 101.325, system="KOH-H2O", molality=1.0)
    koh, k2co3, khco3 = "1310-58-3", "584-08-7", "298-14-6"
    found = el.dissolved_electrolytes(
        [el.WATER_CAS, koh, k2co3, khco3],
        formulas={k2co3: "K2CO3", khco3: "KHCO3"},
    )
    assert {e.cas for e in found} == {koh, k2co3, khco3}
    assert all(e.system is None for e in found)  # refused by the phase and simulation routes
