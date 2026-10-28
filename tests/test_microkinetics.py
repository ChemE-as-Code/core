"""Mean-field microkinetics: the mechanism schema and rules, the steady state against analytic
results and Cantera, the degree of rate control, and cheme chemistry microkinetics."""

import json
import math

import pytest
from typer.testing import CliRunner

from chemeascode.domains.chemistry.microkinetics import (
    Mechanism,
    analyse,
    cantera_yaml,
    steady_state,
)
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.reactions import rules as reaction_rules
from chemeascode.interfaces.cli import app

# CO oxidation on Pt, after Deutschmann et al. (1996): sticking of CO 0.84 and O2 0.07, CO and O
# desorption 125.5 and 213.2 kJ/mol, surface reaction 105 kJ/mol, per-site prefactors 1e13 1/s
CO_OX = {
    "site_density": 2.7063e-5,
    "adsorbates": ["CO*", "O*"],
    "provenance": "assumed",
    "source": "after Deutschmann et al. (1996)",
    "steps": [
        {
            "id": "S1",
            "stoichiometry": {"CO": -1, "*": -1, "CO*": 1},
            "sticking": {"s0": 0.84},
            "reverse": {"A": 1e13, "Ea": 125500},
        },
        {
            "id": "S2",
            "stoichiometry": {"O2": -1, "*": -2, "O*": 2},
            "sticking": {"s0": 0.07},
            "reverse": {"A": 1e13, "Ea": 213200},
        },
        {
            "id": "S3",
            "stoichiometry": {"CO*": -1, "O*": -1, "CO2": 1, "*": 2},
            "forward": {"A": 1e13, "Ea": 105000},
        },
    ],
}
MASSES = {"CO": 28.010, "O2": 31.998, "CO2": 44.009}
FORMULAS = {"CO": "CO", "O2": "O2", "CO2": "CO2"}


def _mech(**change) -> Mechanism:
    return Mechanism.model_validate({**CO_OX, **change})


def test_a_langmuir_isotherm():
    mech = Mechanism.model_validate(
        {
            "site_density": 1e-5,
            "adsorbates": ["CO*"],
            "provenance": "assumed",
            "steps": [
                {
                    "id": "A",
                    "stoichiometry": {"CO": -1, "*": -1, "CO*": 1},
                    "forward": {"A": 2.0},
                    "reverse": {"A": 5.0},
                }
            ],
        }
    )
    state = steady_state(mech, 500.0, {"CO": 3.0}, MASSES)
    k = 2.0 / 5.0
    assert state.coverages["CO*"] == pytest.approx(k * 3 / (1 + k * 3), rel=1e-9)
    assert state.coverages["*"] == pytest.approx(1 / (1 + k * 3), rel=1e-9)


def test_co_oxidation_is_co_poisoned_at_500_k():
    state = analyse(
        _mech(), 500.0, {"CO": 0.01, "O2": 0.1, "CO2": 0.0}, MASSES, "CO2", ["CO", "O2"]
    )
    assert state.coverages["CO*"] > 0.999
    # oxygen needs two free sites, which scale as 1/p_CO: rate ~ p_O2 / p_CO^2
    assert state.orders["CO"] == pytest.approx(-2.0, abs=1e-3)
    assert state.orders["O2"] == pytest.approx(1.0, abs=1e-3)
    # the rate is the O2 adsorption's, and the degrees of rate control sum to one
    assert state.rate_control["S2"] == pytest.approx(1.0, abs=1e-3)
    assert sum(state.rate_control.values()) == pytest.approx(1.0, abs=1e-3)
    # two CO desorptions free the sites: about 2 x 125.5 kJ/mol
    assert state.apparent_activation == pytest.approx(2 * 125500, rel=0.02)
    assert state.tof("CO2") == pytest.approx(-state.tof("CO"))


def test_the_steady_state_agrees_with_cantera():
    pytest.importorskip("cantera")
    from chemeascode.integrations.cantera import run

    text = cantera_yaml(_mech(), FORMULAS)
    assert json.loads(text)["reactions"][0]["sticking-coefficient"]["A"] == 0.84
    for temperature in (500.0, 650.0):
        p = {"CO": 0.01, "O2": 0.1, "CO2": 0.001}
        ours = steady_state(_mech(), temperature, p, MASSES)
        theirs = run(text, temperature, p)
        assert ours.tof("CO2") == pytest.approx(theirs["production"]["CO2"], rel=1e-6)
        for name, theta in ours.coverages.items():
            assert theta == pytest.approx(theirs["coverages"][name], rel=1e-5, abs=1e-12)


def test_readsorption_and_eley_rideal_steps_agree_with_cantera():
    pytest.importorskip("cantera")
    from chemeascode.integrations.cantera import run

    steps = [
        *CO_OX["steps"][:2],
        # the surface reaction to adsorbed CO2, its reversible desorption, and an Eley-Rideal
        # path: rate constants with a gas reactant
        {
            "id": "S3",
            "stoichiometry": {"CO*": -1, "O*": -1, "CO2*": 1, "*": 1},
            "forward": {"A": 1e13, "Ea": 105000},
        },
        {
            "id": "S4",
            "stoichiometry": {"CO2*": -1, "CO2": 1, "*": 1},
            "forward": {"A": 1e13, "Ea": 30000},
            "reverse": {"A": 1e8, "Ea": 0},
        },
        {
            "id": "ER",
            "stoichiometry": {"CO": -1, "O*": -1, "CO2": 1, "*": 1},
            "forward": {"A": 1e5, "Ea": 20000, "n": 0.5},
        },
    ]
    mech = _mech(adsorbates=["CO*", "O*", "CO2*"], steps=steps)
    text = cantera_yaml(mech, FORMULAS)
    for temperature in (550.0, 700.0):
        # N2 is a diluent: no species of the mechanism, ignored by both
        p = {"CO": 0.01, "O2": 0.1, "CO2": 0.05, "N2": 0.8}
        ours = steady_state(mech, temperature, p, MASSES)
        theirs = run(text, temperature, p)
        assert ours.tof("CO2") == pytest.approx(theirs["production"]["CO2"], rel=1e-6)
        assert ours.coverages["CO2*"] == pytest.approx(theirs["coverages"]["CO2*"], rel=1e-5)


def test_duplicate_steps_and_two_molecule_sticking_are_refused():
    with pytest.raises(ValueError, match="not unique"):
        _mech(steps=[CO_OX["steps"][0], CO_OX["steps"][0]])
    with pytest.raises(ValueError, match="one gas molecule"):
        _mech(
            steps=[
                {"id": "X", "stoichiometry": {"CO": -2, "*": -2, "CO*": 2}, "sticking": {"s0": 0.5}}
            ]
        )


def test_a_nearly_empty_surface_converges():
    # a weakly bound adsorbate at low pressure: coverage around 1e-10
    mech = Mechanism.model_validate(
        {
            "site_density": 1e-5,
            "adsorbates": ["CO*"],
            "provenance": "assumed",
            "steps": [
                {
                    "id": "A",
                    "stoichiometry": {"CO": -1, "*": -1, "CO*": 1},
                    "forward": {"A": 1.0},
                    "reverse": {"A": 1e4},
                }
            ],
        }
    )
    state = steady_state(mech, 500.0, {"CO": 1e-6}, MASSES)
    assert state.coverages["CO*"] == pytest.approx(1e-10, rel=1e-6)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"adsorbates": ["CO"]}, "end in"),
        ({"adsorbates": ["CO*"]}, "O\\* is no adsorbate"),
        (
            {
                "steps": [
                    {
                        "id": "X",
                        "stoichiometry": {"CO": -1, "O2": -1, "*": -1, "CO*": 1},
                        "sticking": {"s0": 0.5},
                    }
                ]
            },
            "one gas molecule",
        ),
        (
            {
                "steps": [
                    {
                        "id": "X",
                        "stoichiometry": {"CO": -1, "*": -1, "CO*": 1},
                        "sticking": {"s0": 0.5},
                        "forward": {"A": 1.0},
                    }
                ]
            },
            "forward or sticking",
        ),
    ],
)
def test_mechanism_schema(change, message):
    with pytest.raises(ValueError, match=message):
        _mech(**change)


def test_mechanism_rules():
    bad = {
        **CO_OX,
        "steps": [
            {"id": "B1", "stoichiometry": {"O2": -1, "*": -2, "O*": 1}, "sticking": {"s0": 0.1}},
            {
                "id": "B2",
                "stoichiometry": {"CO*": -1, "O*": -1, "CO2": 1, "*": 1},
                "forward": {"A": 1.0},
            },
            {"id": "B3", "stoichiometry": {"XX": -1, "*": -1, "CO*": 1}, "sticking": {"s0": 0.1}},
        ],
    }
    reactions = Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {"id": "COOX", "stoichiometry": {"CO": -2, "O2": -1, "CO2": 2}, "mechanism": bad}
            ],
        }
    )
    found = [
        f for f in reaction_rules(reactions, None, FORMULAS) if f.rule == "cheme.reaction-mechanism"
    ]
    messages = " | ".join(f.message for f in found)
    assert "step B1 does not balance: atoms created O -1" in messages
    assert "step B1 creates -1 sites" in messages
    assert "step B2 creates -1 sites" in messages
    assert "component XX is not declared" in messages


REACTIONS_FILE = (
    """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: COOX
    stoichiometry: {CO: -2, O2: -1, CO2: 2}
    mechanism:
"""
    + "\n".join("      " + line for line in json.dumps(CO_OX, indent=2).splitlines())
    + "\n"
)

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: CO, name: Carbon monoxide, formula: CO, molar_mass: 28.010}
  - {id: O2, name: Oxygen, formula: O2, molar_mass: 31.998}
  - {id: CO2, name: Carbon dioxide, formula: CO2, molar_mass: 44.009}
"""


def test_the_command(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: mkm\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/reactions.yaml").write_text(REACTIONS_FILE)
    monkeypatch.chdir(root)
    args = ["chemistry", "microkinetics", "COOX", "-T", "500", "-p", "CO=0.01", "-p", "O2=0.1"]
    shown = CliRunner().invoke(app, [*args, "--export", "mech.yaml"])
    assert shown.exit_code == 0, shown.output
    assert "TOF of CO2" in shown.output and "degree of rate control" in shown.output
    assert json.loads((root / "mech.yaml").read_text())["phases"][1]["name"] == "surface"
    data = json.loads(CliRunner().invoke(app, [*args, "--json"]).output)
    assert data["orders"]["CO"] == pytest.approx(-2.0, abs=1e-3)
    assert math.isclose(sum(data["rate_control"].values()), 1.0, abs_tol=1e-3)
    if pytest.importorskip("cantera", reason="optional") is not None:
        checked = json.loads(CliRunner().invoke(app, [*args, "--json", "--cantera"]).output)
        assert checked["cantera"]["tof_per_s"] == pytest.approx(data["tof_per_s"], rel=1e-6)
    negative = [a if a != "CO=0.01" else "CO=-1" for a in args]
    bad = CliRunner().invoke(app, negative)
    assert bad.exit_code == 2 and "not below 0" in bad.output
    cold = CliRunner().invoke(app, [a if a != "500" else "0" for a in args])
    assert cold.exit_code == 2 and "above 0" in cold.output
    missing = CliRunner().invoke(
        app, ["chemistry", "microkinetics", "NOPE", "-T", "500", "-p", "CO=1"]
    )
    assert missing.exit_code == 1 and "not declared" in missing.output


# -- steps from electronic energies (transition state theory) ------------------------------------


def _energy_mech() -> Mechanism:
    def e(reaction, barrier):
        return {"reaction_energy": reaction, "barrier": barrier, "provenance": "assumed"}

    return _mech(
        steps=[
            {**CO_OX["steps"][0], "reverse": None, "energies": e(-1.3, 0.0)},
            {**CO_OX["steps"][1], "reverse": None, "energies": e(-2.2, 0.0)},
            {
                "id": "S3",
                "stoichiometry": {"CO*": -1, "O*": -1, "CO2": 1, "*": 2},
                "energies": e(-0.5, 1.0),
            },
        ]
    )


def test_energies_give_transition_state_rate_constants():
    step = _energy_mech().steps[2]
    forward, reverse = step.constants()
    t = 600.0
    kt_h = 1.380649e-23 * t / 6.62607015e-34
    ev = 1.602176634e-19 / (1.380649e-23 * t)  # 1 eV / (k_B T)
    assert forward.k(t) == pytest.approx(kt_h * math.exp(-1.0 * ev), rel=1e-6)
    assert reverse.k(t) == pytest.approx(kt_h * math.exp(-1.5 * ev), rel=1e-6)
    # an adsorption keeps its sticking and desorbs over the binding energy
    adsorption = _energy_mech().steps[0]
    assert adsorption.constants()[0] is None
    assert adsorption.constants()[1].k(t) == pytest.approx(kt_h * math.exp(-1.3 * ev), rel=1e-6)


def test_energy_steps_agree_with_cantera():
    pytest.importorskip("cantera")
    from chemeascode.integrations.cantera import run

    p = {"CO": 0.01, "O2": 0.1, "CO2": 0.001}
    ours = steady_state(_energy_mech(), 550.0, p, MASSES)
    theirs = run(cantera_yaml(_energy_mech(), FORMULAS), 550.0, p)
    assert ours.tof("CO2") == pytest.approx(theirs["production"]["CO2"], rel=1e-4)


def test_energy_step_refusals():
    with pytest.raises(ValueError, match="reverse barrier would be negative"):
        _mech(
            steps=[
                {
                    "id": "X",
                    "stoichiometry": {"CO*": -1, "O*": -1, "CO2": 1, "*": 2},
                    "energies": {"reaction_energy": 0.5, "barrier": 0.2, "provenance": "assumed"},
                }
            ]
        )
    with pytest.raises(ValueError, match="replace forward and reverse"):
        _mech(
            steps=[
                {
                    **CO_OX["steps"][2],
                    "energies": {"reaction_energy": -0.5, "barrier": 1.0, "provenance": "assumed"},
                }
            ]
        )
