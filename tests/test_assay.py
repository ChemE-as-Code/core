"""Petroleum assays and pseudocomponents (thermodynamics/assay.py, pre-release issue 367).

Reference data, all independent of the code under test:

- published worked examples of the correlations: Riazi (2005, ASTM MNL50) Example 3.3 and the
  API Technical Data Book example of procedure 3A1.1 (D86 to TBP), Ahmed (Equations of State
  and PVT Analysis) Example 2.2 (Riazi-Daubert 1987 from Tb and SG), as transcribed in the
  doctests of pychemqt ``lib/petro.py`` (D86_TBP_Daubert, prop_Riazi_Daubert);
- the critical constants and molar masses of the n-alkanes in thermo/chemicals (measured,
  DIPPR/Yaws), for the accuracy of Riazi-Daubert on compounds of known identity;
- a published assay, TotalEnergies' Oman crude (2020): its TBP curve in wt % and vol % and the
  measured densities of its naphtha cuts, for mass basis, density and boiling behaviour;
- the flash benchmark (``assay.FLASH_CLAIM``): two defined naphtha surrogates, evaluated by
  CoolProp 8.0.0 (HEOS) with its reference equations of state and the mixture parameters of
  Kunz and Wagner (JCED 2012, GERG-2008) for the alkane pairs and Bell et al. (JCED 2016) for
  the pairs with cyclohexane or toluene. Each surrogate is characterised from its cuts (each
  compound's normal boiling point and specific gravity, taken from the same models), so the
  characterisation sees what an assay of the mixture would report and nothing of the
  compounds' identity.
"""

from __future__ import annotations

import ast
import json
import shutil
from itertools import pairwise
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.thermodynamics import assay as A

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SRC = Path(__file__).resolve().parents[1] / "src" / "chemeascode"
runner = CliRunner()


def _c(value: float) -> float:
    return value + 273.15


def _f(value: float) -> float:
    return (value + 459.67) / 1.8


# -- published worked examples ----------------------------------------------------------------


def test_d86_to_tbp_reproduces_riazi_example_3_3():
    # Riazi (2005) MNL50 Example 3.3, API 3A1.1: D86 at 0-90 % (degC) -> TBP (degC)
    volumes = [0.0, 10.0, 30.0, 50.0, 70.0, 90.0]
    d86 = dict(zip(volumes, [165.6, 173.7, 193.3, 206.7, 222.8, 242.8], strict=True))
    tbp = A.d86_to_tbp({v: _c(t) for v, t in d86.items()})
    expected = [133.5, 154.2, 189.2, 210.7, 232.9, 258.2]
    assert [round(t - 273.15, 1) for t in tbp.values()] == expected


def test_d86_to_tbp_reproduces_the_api_example():
    # API Technical Data Book procedure 3A1.1 example (degF), 10-90 %
    d86 = dict(zip([10.0, 30.0, 50.0, 70.0, 90.0], [350, 380, 404, 433, 469], strict=True))
    tbp = A.d86_to_tbp({v: _f(t) for v, t in d86.items()})
    assert [round(t * 1.8 - 459.67, 1) for t in tbp.values()] == [
        316.5,
        372.6,
        411.2,
        451.2,
        496.7,
    ]


def test_d86_to_tbp_refuses_what_it_cannot_convert():
    with pytest.raises(ValueError, match="include 50"):
        A.d86_to_tbp({0.0: 300.0, 10.0: 310.0})
    with pytest.raises(ValueError, match="contiguous"):
        A.d86_to_tbp({10.0: 300.0, 50.0: 320.0, 90.0: 340.0})
    with pytest.raises(ValueError, match="falls back"):
        A.d86_to_tbp({30.0: 330.0, 50.0: 320.0})
    # the 50 % correlation is a power law in degF: no real TBP at or below 0 degF
    with pytest.raises(ValueError, match="below 0 degF"):
        A.d86_to_tbp({30.0: _f(-40.0), 50.0: _f(-30.0)})


def test_a_d86_curve_below_0_degf_is_refused_not_crashed():
    points = [[0, -60], [10, -50], [30, -40], [50, -30], [70, -20], [90, -10], [100, 0]]
    c = A.characterize(
        _assay(temperature_unit="°F", distillation={"method": "D86", "points": points})
    )
    assert c.refused and [f.rule for f in c.findings] == ["cheme.assay-insufficient"]


def test_riazi_daubert_reproduces_ahmed_example_2_2():
    # Tb = 198 degF, SG = 0.7365: M 97, Tc 986 degR, Pc 466 psia
    p = A.riazi_daubert(_f(198.0), 0.7365)
    assert round(p["molar_mass"]) == 97
    assert round(p["critical_temperature_K"] * 1.8) == 986
    assert round(p["critical_pressure_Pa"] / 6894.757293168361) == 466


def test_riazi_daubert_against_measured_n_alkane_constants():
    """Accuracy on compounds of known identity: Tc within 1 %, Pc within 4 %, M within 4 %
    and the C/H weight ratio within 2 % for n-hexane to n-decane (the measured constants in
    chemicals; Tb and SG from CoolProp's reference equations of state)."""
    pytest.importorskip("chemicals")
    CP = pytest.importorskip("CoolProp.CoolProp")
    from chemicals.critical import Pc, Tc
    from chemicals.elements import molecular_weight, simple_formula_parser
    from chemicals.identifiers import search_chemical

    water = CP.PropsSI("D", "T", _f(60.0), "P", 101325, "Water")
    for name in ["n-Hexane", "n-Heptane", "n-Octane", "n-Nonane", "n-Decane"]:
        tb = CP.PropsSI("T", "P", 101325, "Q", 0, name)
        sg = CP.PropsSI("D", "T", _f(60.0), "P", 101325, name) / water
        known = search_chemical(name.removeprefix("n-").lower())
        atoms = simple_formula_parser(known.formula)
        p = A.riazi_daubert(tb, sg)
        assert p["critical_temperature_K"] == pytest.approx(Tc(known.CASs), rel=0.01), name
        assert p["critical_pressure_Pa"] == pytest.approx(Pc(known.CASs), rel=0.04), name
        assert p["molar_mass"] == pytest.approx(molecular_weight(atoms), rel=0.04), name
        ratio = atoms["C"] * 12.011 / (atoms["H"] * 1.008)
        assert p["carbon_hydrogen_ratio"] == pytest.approx(ratio, rel=0.02), name


# -- characterisation: mass basis, density, determinism ----------------------------------------

NAPHTHA = {
    "id": "HN-1",
    "title": "heavy naphtha (illustrative)",
    "source": "illustrative test data, not a measured assay",
    "temperature_unit": "°C",
    "distillation": {
        "method": "TBP",
        "points": [[0, 70], [10, 85], [30, 100], [50, 115], [70, 130], [90, 150], [100, 175]],
    },
    "specific_gravity": 0.745,
}


def _assay(**changes) -> A.Assay:
    data = json.loads(json.dumps(NAPHTHA))
    data.update(changes)
    return A.Assay.model_validate({k: v for k, v in data.items() if v is not None})


def test_a_curve_is_cut_into_equal_volumes_that_close_the_mass_basis():
    pytest.importorskip("chemicals")
    c = A.characterize(_assay())
    assert not c.findings and len(c.pseudocomponents) == A.DEFAULT_PSEUDOCOMPONENTS
    ps = c.pseudocomponents
    for key in ("volume_fraction", "mass_fraction", "mole_fraction"):
        assert sum(getattr(p, key) for p in ps) == pytest.approx(1.0, abs=1e-12)
    # the cut gravities reproduce the fraction's (ideal mixing by volume) and share one K
    assert sum(p.volume_fraction * p.specific_gravity for p in ps) == pytest.approx(0.745)
    assert c.bulk["specific_gravity"] == pytest.approx(0.745)
    assert {round(p.watson_k, 9) for p in ps} == {round(c.bulk["watson_k"], 9)}
    # mass fractions follow from volume and gravity, mole fractions from mass and molar mass
    for p in ps:
        assert p.mass_fraction == pytest.approx(p.volume_fraction * p.specific_gravity / 0.745)
        assert p.mole_fraction == pytest.approx(
            p.mass_fraction / p.molar_mass * c.bulk["molar_mass"]
        )
    # boiling points rise through the curve and stay inside its ends; the first cut's is the
    # mean of the curve over 0-12.5 %: 70-85 degC over 0-10 %, then 85-86.875 over 10-12.5 %
    tbs = [p.normal_boiling_point_K for p in ps]
    assert tbs == sorted(tbs) and _c(70) < tbs[0] and tbs[-1] < _c(175)
    assert tbs[0] == pytest.approx(_c((77.5 * 10 + 85.9375 * 2.5) / 12.5))
    assert ps[0].identity == f"pseudo:{c.fingerprint}:1" and ps[0].name == "HN-1:1"
    assert ps[0].provenance["molar_mass"] == "riazi-daubert-1987"
    assert set(c.correlations) <= set(A.CORRELATIONS)


def test_density_forms_and_watson_k_give_the_same_cuts():
    pytest.importorskip("chemicals")
    by_sg = A.characterize(_assay())
    api = 141.5 / 0.745 - 131.5
    by_api = A.characterize(_assay(specific_gravity=None, api_gravity=api))
    by_rho = A.characterize(_assay(specific_gravity=None, density_15C=0.745 * A.WATER_60F))
    by_k = A.characterize(_assay(specific_gravity=None, watson_k=by_sg.bulk["watson_k"]))
    for other in (by_api, by_rho, by_k):
        assert [p.specific_gravity for p in other.pseudocomponents] == pytest.approx(
            [p.specific_gravity for p in by_sg.pseudocomponents]
        )
    assert by_k.pseudocomponents[0].provenance["specific_gravity"].startswith("given watson_k")


def test_d86_curve_is_converted_before_cutting():
    pytest.importorskip("chemicals")
    points = [[0, 60], [10, 80], [30, 98], [50, 112], [70, 127], [90, 148], [100, 170]]
    c = A.characterize(_assay(distillation={"method": "D86", "points": points}))
    assert not c.refused and c.correlations[0] == "d86-tbp-api-3a1.1"
    assert c.tbp_K[0][1] < _c(60) and c.tbp_K[-1][1] > _c(170)  # TBP is wider than D86


def test_given_cuts_keep_their_data():
    pytest.importorskip("chemicals")
    c = A.characterize(_surrogate_assay(PARAFFINIC))
    assert [p.provenance["specific_gravity"] for p in c.pseudocomponents] == ["given"] * 5
    assert [p.name for p in c.pseudocomponents][0] == "n-Hexane"


def test_measured_molar_mass_is_checked_and_an_unused_watson_k_reported():
    pytest.importorskip("chemicals")
    c = A.characterize(_assay(molar_mass=130.0, watson_k=12.5))
    rules = {(f.rule, f.level) for f in c.findings}
    assert ("cheme.assay-inconsistent", "warning") in rules  # 108.6 vs 130 g/mol
    assert ("cheme.assay-inconsistent", "info") in rules
    assert not c.refused  # a check, not a refusal
    near = A.characterize(_assay(molar_mass=round(c.bulk["molar_mass"], 1)))
    assert not near.findings


# -- refusal: insufficient assays and extrapolation --------------------------------------------


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"specific_gravity": None}, "no density of the fraction"),
        ({"api_gravity": 58.0}, "give one density"),
        (
            {"distillation": {"method": "TBP", "points": [[0, 70], [50, 115], [100, 175]]}},
            "a TBP curve needs at least 5",
        ),
        (
            {
                "distillation": {
                    "method": "TBP",
                    "points": [[0, 70], [10, 85], [30, 100], [50, 115], [90, 150]],
                }
            },
            "not from 0 to 100 %",
        ),
        (
            {
                "distillation": {
                    "method": "TBP",
                    "points": [[0, 70], [10, 85], [30, 80], [50, 115], [100, 175]],
                }
            },
            "fall back",
        ),
        (
            {
                "distillation": {
                    "method": "D86",
                    "points": [[0, 70], [10, 85], [50, 115], [90, 150], [100, 175]],
                }
            },
            "a D86 curve needs the points",
        ),
        (
            {
                "cuts": [
                    {"liquid_volume_percent": 100, "boiling_point": 100, "specific_gravity": 0.7}
                ]
            },
            "not both",
        ),
        ({"distillation": None}, "not neither"),
    ],
)
def test_insufficient_assays_are_refused(changes, message):
    c = A.characterize(_assay(**changes))
    assert c.refused
    assert any(f.rule == "cheme.assay-insufficient" and message in f.message for f in c.findings)


def test_cuts_must_cover_the_fraction_and_carry_their_own_gravity():
    cuts = [{"liquid_volume_percent": 60, "boiling_point": 100, "specific_gravity": 0.7}]
    c = A.characterize(_assay(distillation=None, specific_gravity=None, cuts=cuts))
    assert c.refused and "add up to 60 %" in c.findings[0].message
    full = [{"liquid_volume_percent": 100, "boiling_point": 100, "specific_gravity": 0.7}]
    c = A.characterize(_assay(distillation=None, cuts=full))
    assert c.refused and "specific_gravity not used with cuts" in c.findings[0].message


def test_light_ends_and_heavy_fractions_are_not_extrapolated():
    # a full-range naphtha from 25 degC: its first cut lies below Riazi-Daubert's 80 degF /
    # M 70; a fraction ending at 420 degC: its last cut above 650 degF
    light = A.characterize(
        _assay(
            distillation={
                "method": "TBP",
                "points": [[0, 20], [10, 30], [30, 60], [50, 90], [70, 120], [90, 150], [100, 175]],
            },
            specific_gravity=0.70,
        )
    )
    heavy = A.characterize(
        _assay(
            distillation={
                "method": "TBP",
                "points": [[0, 150], [10, 200], [30, 250], [50, 300], [70, 350], [100, 420]],
            },
            specific_gravity=0.86,
        )
    )
    for c, what in ((light, "normal_boiling_point_K 2"), (heavy, "normal_boiling_point_K 6")):
        assert c.refused and not c.pseudocomponents
        assert any(f.rule == "cheme.assay-extrapolation" for f in c.findings)
        assert any(what in f.message for f in c.findings), [f.message for f in c.findings]
    with pytest.raises(ValueError, match="refused"):
        A.flash(light, 350.0, 101.325)


# -- a published naphtha: TotalEnergies' Oman crude assay ------------------------------------
# TotalEnergies Trading & Shipping, crude assay "OMAN" (assay date 10 October 2020, density at
# 15 degC 858.7 kg/m3), https://trading.totalenergies.com/wp-content/uploads/2025/11/OMAN.pdf:
# the crude's TBP curve (degC, wt % and vol % distilled, published to 0.1 %) and the measured
# densities at 15 degC of its heavy naphtha cuts 80-175 degC (742 kg/m3) and 80-150 degC
# (734 kg/m3) and of its vacuum distillate 375-550 degC (915 kg/m3).

OMAN_TBP = [  # degC, wt %, vol %
    (80, 5.3, 7.3),
    (90, 6.2, 8.2),
    (100, 7.2, 9.4),
    (120, 9.7, 12.4),
    (140, 12.9, 16.1),
    (160, 16.4, 20.1),
    (180, 19.6, 23.7),
    (360, 47.5, 52.6),
    (380, 50.7, 55.8),
    (400, 54.0, 58.9),
    (420, 57.1, 61.9),
    (440, 60.2, 64.8),
    (460, 63.2, 67.6),
    (480, 66.1, 70.3),
    (500, 68.9, 73.0),
    (520, 71.7, 75.5),
    (540, 74.3, 77.9),
    (560, 76.9, 80.2),
]


def _oman(column: int, x: float, by: int = 0) -> float:
    """The crude curve's ``column`` at ``x`` of column ``by``, linear between published points."""
    for a, b in pairwise(OMAN_TBP):
        if a[by] <= x <= b[by]:
            return a[column] + (b[column] - a[column]) * (x - a[by]) / (b[by] - a[by])
    raise ValueError(x)


def _oman_cut(lower: float, upper: float, **density) -> A.Assay:
    """The cut's own TBP curve: the crude's points inside it, rescaled to 0-100 vol %."""
    v0, v1 = _oman(2, lower), _oman(2, upper)
    temps = [lower, *(t for t, _, _ in OMAN_TBP if lower < t < upper), upper]
    points = [[round(100 * (_oman(2, t) - v0) / (v1 - v0), 6), t] for t in temps]
    return A.Assay.model_validate(
        {
            "id": f"OMAN-{lower}-{upper}",
            "source": "TotalEnergies crude assay OMAN (2020-10-10), TBP curve and cut density",
            "temperature_unit": "°C",
            "distillation": {"method": "TBP", "points": points},
            **density,
        }
    )


def test_published_naphtha_mass_basis_and_density():
    pytest.importorskip("chemicals")
    heavy = A.characterize(_oman_cut(80, 175, density_15C=742))
    assert not heavy.findings and not heavy.refused
    # mass basis: the cumulative mass fraction of the pseudocomponents at each cut boundary
    # against the assay's own wt % at the temperature of that vol %. Both columns are published
    # to 0.1 % of the crude over a cut of 13.5 wt % and 15.5 vol %: within 0.015
    v0, v1 = _oman(2, 80), _oman(2, 175)
    w0, w1 = _oman(1, 80), _oman(1, 175)
    cumulative, n = 0.0, len(heavy.pseudocomponents)
    for i, p in enumerate(heavy.pseudocomponents, 1):
        cumulative += p.mass_fraction
        t = _oman(0, v0 + (v1 - v0) * i / n, by=2)
        assert cumulative == pytest.approx((_oman(1, t) - w0) / (w1 - w0), abs=0.015), i
    # density behaviour: one Watson K per curve. The K of either cut predicts the other's
    # measured density within 2 kg/m3 (the densities are published to 1 kg/m3, and the 150 and
    # 175 degC ends are interpolated linearly in the curve)
    narrow = A.characterize(_oman_cut(80, 150, density_15C=734))
    assert not narrow.refused
    for char, (lower, upper), measured in ((heavy, (80, 150), 734), (narrow, (80, 175), 742)):
        other = A.characterize(_oman_cut(lower, upper, watson_k=char.bulk["watson_k"]))
        predicted = other.bulk["specific_gravity"] * A.WATER_60F
        assert predicted == pytest.approx(measured, abs=2.0), (lower, upper)


def test_published_naphtha_boils_inside_its_curve_and_flashes_inside_the_claim():
    pytest.importorskip("thermo")
    heavy = A.characterize(_oman_cut(80, 175, density_15C=742))
    # an equilibrium flash vaporisation curve is flatter than the TBP curve it comes from: at
    # one atmosphere the bubble point lies above the initial TBP point and below the 50 % point,
    # the dew point above the 50 % point and below the final one (Riazi 2005, MNL50, 3.2.4)
    s = A.saturation(heavy, 101.325)
    tbp50 = _c(_oman(0, (_oman(2, 80) + _oman(2, 175)) / 2, by=2))
    assert _c(80) < s["bubble_temperature_K"] < tbp50 < s["dew_temperature_K"] < _c(175)
    assert s["characterization"] == heavy.fingerprint and not s["outside_claim"]
    liquid, vapour = A.flash(heavy, 300.0, 101.325), A.flash(heavy, 500.0, 101.325)
    assert (liquid.phase, vapour.phase) == ("liquid", "vapour")
    assert not liquid.outside_claim and not vapour.outside_claim
    assert vapour.enthalpy_J_per_kg > liquid.enthalpy_J_per_kg


def test_published_heavy_cuts_are_refused():
    pytest.importorskip("chemicals")
    # the same crude's vacuum distillate lies above Riazi-Daubert's 650 degF
    vacuum = A.characterize(_oman_cut(375, 550, density_15C=915))
    assert vacuum.refused and not vacuum.pseudocomponents
    assert {f.rule for f in vacuum.findings} == {"cheme.assay-extrapolation"}
    # its 100-150 degC naphtha has four published curve points inside it: too few to cut
    narrow = A.characterize(_oman_cut(100, 150, density_15C=739))
    assert narrow.refused and [f.rule for f in narrow.findings] == ["cheme.assay-insufficient"]


# -- fingerprints, identities, comparability ---------------------------------------------------


def test_fingerprint_covers_the_inputs_and_the_method_not_the_names(monkeypatch):
    base = _assay()
    renamed = _assay(id="X", title="other title", source="other source")
    assert A.fingerprint(base) == A.fingerprint(renamed)
    assert A.fingerprint(base) != A.fingerprint(_assay(specific_gravity=0.75))
    assert A.fingerprint(base) != A.fingerprint(_assay(pseudocomponents=10))
    # the default number of cuts is part of the inputs: writing it out changes nothing
    assert A.fingerprint(base) == A.fingerprint(_assay(pseudocomponents=8))
    old = A.fingerprint(base)
    monkeypatch.setattr(A, "METHOD_VERSION", "2")
    assert A.fingerprint(base) != old


def test_comparability_names_what_differs():
    pytest.importorskip("chemicals")
    a = A.characterize(_assay())
    assert A.comparability(a, A.characterize(_assay(id="copy"))) == []
    b = A.characterize(_assay(specific_gravity=0.75))
    assert A.comparability(a, b) == ["input specific_gravity: 0.745 != 0.75"]
    c = A.characterize(_assay())
    c.method_version = "0"
    assert A.comparability(a, c)[0] == "method version 1 != 0"


# -- the flash benchmark against CoolProp ------------------------------------------------------

PARAFFINIC = [
    ("n-Hexane", 15.0),
    ("n-Heptane", 25.0),
    ("n-Octane", 25.0),
    ("n-Nonane", 20.0),
    ("n-Decane", 15.0),
]
#: paraffins, one naphthene and one aromatic (every pair has CoolProp mixture parameters)
PNA = [
    ("n-Hexane", 15.0),
    ("n-Heptane", 25.0),
    ("n-Octane", 15.0),
    ("n-Nonane", 10.0),
    ("Cyclohexane", 20.0),
    ("Toluene", 15.0),
]


def _reference(surrogate):
    CP = pytest.importorskip("CoolProp.CoolProp")
    t60 = _f(60.0)
    water = CP.PropsSI("D", "T", t60, "P", 101325, "Water")
    names = [n for n, _ in surrogate]
    tb = [CP.PropsSI("T", "P", 101325, "Q", 0, n) for n in names]
    rho = [CP.PropsSI("D", "T", t60, "P", 101325, n) for n in names]
    mw = [CP.PropsSI("M", n) * 1e3 for n in names]
    moles = [v * r / m for (_, v), r, m in zip(surrogate, rho, mw, strict=True)]
    zs = [x / sum(moles) for x in moles]
    state = CP.AbstractState("HEOS", "&".join(names))
    state.set_mole_fractions(zs)
    return {
        "names": names,
        "tb": tb,
        "sg": [r / water for r in rho],
        "molar_mass": sum(z * m for z, m in zip(zs, mw, strict=True)),
        "state": state,
        "CP": CP,
    }


def _surrogate_assay(surrogate) -> A.Assay:
    ref = _reference(surrogate)
    return A.Assay(
        id="SUR",
        source="defined surrogate; Tb and SG from CoolProp 8.0.0 reference equations of state",
        temperature_unit="K",
        cuts=[
            {"name": n, "liquid_volume_percent": v, "boiling_point": t, "specific_gravity": s}
            for (n, v), t, s in zip(surrogate, ref["tb"], ref["sg"], strict=True)
        ],
    )


@pytest.mark.parametrize("surrogate", [PARAFFINIC, PNA], ids=["paraffinic", "pna"])
def test_flash_benchmark_against_coolprop(surrogate):
    """The positive reference case of FLASH_CLAIM: molar mass, liquid density at 15 degC,
    bubble and dew temperatures at 50-500 kPa(a), and enthalpy differences from the liquid at
    300 K of liquid, saturated and vapour states up to 550 K, within the claimed tolerances."""
    pytest.importorskip("thermo")
    ref = _reference(surrogate)
    CP, state = ref["CP"], ref["state"]
    tol = A.FLASH_CLAIM["tolerances"]
    c = A.characterize(_surrogate_assay(surrogate))
    assert not c.refused and not c.findings
    assert A.outside_flash_claim(c, 400.0, 101.325) == []

    assert c.bulk["molar_mass"] == pytest.approx(ref["molar_mass"], rel=tol["molar_mass_rel"])
    state.update(CP.PT_INPUTS, 101325, _f(60.0))
    assert c.bulk["liquid_density_15C_kg_m3"] == pytest.approx(
        state.rhomass(), rel=tol["liquid_density_15C_rel"]
    )

    for p_kpa in (50.0, 101.325, 200.0, 500.0):
        sat = A.saturation(c, p_kpa)
        assert sat["outside_claim"] == [] and sat["characterization"] == c.fingerprint
        state.update(CP.PQ_INPUTS, p_kpa * 1e3, 0)
        bubble, h_bubble = state.T(), state.hmass()
        state.update(CP.PQ_INPUTS, p_kpa * 1e3, 1)
        dew, h_dew = state.T(), state.hmass()
        dt = tol["saturation_temperature_abs_K"]
        assert sat["bubble_temperature_K"] == pytest.approx(bubble, abs=dt), p_kpa
        assert sat["dew_temperature_K"] == pytest.approx(dew, abs=dt), p_kpa
        if p_kpa not in (101.325, 500.0):
            continue
        state.update(CP.PT_INPUTS, p_kpa * 1e3, 300.0)
        h0 = state.hmass()
        flasher, zs = A._flasher(c)
        h0_pr = flasher.flash(T=300.0, P=p_kpa * 1e3, zs=zs).H_mass()
        pairs = [
            (h_bubble - h0, flasher.flash(P=p_kpa * 1e3, VF=0.0, zs=zs).H_mass() - h0_pr),
            (h_dew - h0, flasher.flash(P=p_kpa * 1e3, VF=1.0, zs=zs).H_mass() - h0_pr),
        ]
        for t in (320.0, 350.0, 400.0, 450.0, 500.0, 550.0):
            if bubble - 5.0 < t < dew + 5.0:
                continue  # two-phase: CoolProp's TP flash of a mixture is not used
            state.update(CP.PT_INPUTS, p_kpa * 1e3, t)
            result = A.flash(c, t, p_kpa)
            assert result.outside_claim == []
            assert result.phase == ("liquid" if t < bubble else "vapour")
            pairs.append((state.hmass() - h0, result.enthalpy_J_per_kg - h0_pr))
        for reference, calculated in pairs:
            assert abs(calculated - reference) / 1e3 <= tol["enthalpy_difference_abs_kJ_per_kg"], (
                p_kpa,
                reference / 1e3,
                calculated / 1e3,
            )


def test_flash_reports_states_and_cuts_outside_the_claim():
    pytest.importorskip("thermo")
    c = A.characterize(_assay())  # HN-1: cuts 352-433 K, inside the claim
    result = A.flash(c, 600.0, 1000.0)
    assert result.outside_claim == [
        "600 K is outside 300-550 K",
        "1000 kPa(a) is outside 50-500 kPa(a)",
    ]
    assert result.characterization == c.fingerprint and result.solver["name"] == "thermo"
    lighter = A.characterize(
        _assay(
            distillation={
                "method": "TBP",
                "points": [[0, 40], [10, 50], [30, 70], [50, 90], [70, 110], [90, 130], [100, 150]],
            },
            specific_gravity=0.70,
        )
    )
    assert not lighter.refused
    assert any(
        "HN-1:1: normal boiling point" in r for r in A.outside_flash_claim(lighter, 350, 101)
    )


# -- the workspace: file, record, validate, CLI ------------------------------------------------


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLES / "process-simulation", root)
    surrogate = {
        "id": "SUR-1",
        "title": "naphtha surrogate",
        "source": "defined mixture (test)",
        "temperature_unit": "K",
        "cuts": [
            {
                "name": "C7",
                "liquid_volume_percent": 50,
                "boiling_point": 371.5,
                "specific_gravity": 0.6882,
            },
            {
                "name": "C8",
                "liquid_volume_percent": 50,
                "boiling_point": 398.8,
                "specific_gravity": 0.7069,
            },
        ],
    }
    data = {"schema": A.SCHEMA, "kind": "assays", "assays": [NAPHTHA, surrogate]}
    (root / A.ASSAYS_FILE).write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return root


def _edit(root: Path, edit) -> None:
    path = root / A.ASSAYS_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def test_file_findings_name_file_line_rule_and_hint(plant):
    assert A.check(plant) == []

    def bad(data):
        data["assays"][0].pop("specific_gravity")
        data["assays"][1]["id"] = "HN-1"

    _edit(plant, bad)
    found = A.check(plant)
    rules = {f.rule for f in found}
    assert rules == {"cheme.assay-duplicate-id", "cheme.assay-insufficient"}
    for f in found:
        assert f.file == A.ASSAYS_FILE and f.line and f.hint

    _edit(plant, lambda data: data["assays"][0].update(temperature_unit="C"))
    (schema,) = A.check(plant)
    assert schema.rule == "cheme.assay-schema" and schema.line


def test_record_fill_stale_missing_and_prune(plant):
    pytest.importorskip("chemicals")
    assert A.record_findings(plant) == []  # no record yet: nothing to be stale
    missing = A.record_findings(plant, missing=True)
    assert {f.rule for f in missing} == {"cheme.assay-record-missing"}

    report = A.assay_report(plant)
    assert A.fill(plant, report) == ["HN-1", "SUR-1"]
    record = json.loads((plant / A.RECORD_FILE).read_text(encoding="utf-8"))
    entry = record["assays"]["HN-1"]
    assert record["schema"] == A.RECORD_SCHEMA and entry["method_version"] == A.METHOD_VERSION
    assert entry["fingerprint"] == report.characterizations[0].fingerprint
    assert entry["pseudocomponents"][0]["identity"].startswith("pseudo:")
    assert entry["file_revision"]["fingerprints"][A.ASSAYS_FILE].startswith("sha256:")
    assert A.record_findings(plant, missing=True) == []

    _edit(plant, lambda data: data["assays"][0].update(specific_gravity=0.75))
    (stale,) = A.record_findings(plant)
    assert stale.rule == "cheme.assay-record-stale" and stale.ids == ["HN-1"] and stale.line

    _edit(plant, lambda data: data["assays"].pop(1))
    rules = [(f.file, f.rule) for f in A.record_findings(plant)]
    assert (A.RECORD_FILE, "cheme.assay-record-stale") in rules
    assert A.prune(plant) == ["SUR-1"]


def test_validate_reports_assay_findings(plant):
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(plant))
    assert A.ASSAYS_FILE in report.files
    assert not [f for f in report.findings if f.rule.startswith("cheme.assay")]
    _edit(plant, lambda data: data["assays"][0]["distillation"]["points"].pop())
    report = validate_workspace(Workspace(plant))
    found = [f for f in report.findings if f.rule == "cheme.assay-insufficient"]
    assert found and found[0].line


def test_cli_prints_characterisation_flash_and_record(plant, monkeypatch):
    pytest.importorskip("thermo")
    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(plant)
    shown = runner.invoke(app, ["process", "assay", "HN-1", "--pressure", "101.325"])
    assert shown.exit_code == 0, shown.output
    assert "assay HN-1: 8 pseudocomponents, fingerprint" in shown.output
    assert "at 101.325 kPa(a): bubble" in shown.output

    data = json.loads(
        runner.invoke(
            app,
            ["process", "assay", "--json", "--temperature", "400", "--pressure", "200"],
        ).output
    )
    assert [c["assay"] for c in data["characterizations"]] == ["HN-1", "SUR-1"]
    assert (
        data["states"]["HN-1"]["flash"]["characterization"]
        == (data["characterizations"][0]["fingerprint"])
    )

    checked = runner.invoke(app, ["process", "assay", "--check"])
    assert checked.exit_code == 0 and "cheme.assay-record-missing" in checked.output
    assert runner.invoke(app, ["process", "assay", "--fill"]).exit_code == 0
    _edit(plant, lambda d: d["assays"][0].update(specific_gravity=0.75))
    checked = runner.invoke(app, ["process", "assay", "--check"])
    assert checked.exit_code == 1 and "cheme.assay-record-stale" in checked.output
    assert runner.invoke(app, ["process", "assay", "nope"]).exit_code == 2

    methods = runner.invoke(app, ["process", "methods"])
    assert (
        "regime petroleum_pseudocomponents: phase unsupported, simulation unsupported, "
        "assay limited"
    ) in methods.output


# -- the pure-component routes stay independent ------------------------------------------------


def test_pure_component_routes_do_not_use_the_assay_module():
    """The phase route and the DWSIM simulation (the ethane-cracker/gas route) neither import
    the assay module nor accept a pseudocomponent: they keep their own scope."""
    modules = [SRC / "domains/process/thermodynamics/phase.py"]
    modules += sorted((SRC / "domains/process/simulation").glob("*.py"))
    modules += [SRC / "integrations/dwsim.py", SRC / "integrations/dwsim_worker.py"]
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + [
            a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names
        ]
        assert not [n for n in names if n.endswith("assay")], path


def test_an_assay_file_changes_nothing_in_the_simulation_model(plant):
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.translate import load, translate

    def fingerprint(root):
        process, _ = load_process(root)
        sim, doc, _ = load(root)
        return translate(process, sim, doc, process.flowsheet.default_case()).fingerprint

    with_assays = fingerprint(plant)
    (plant / A.ASSAYS_FILE).unlink()
    assert fingerprint(plant) == with_assays


def test_phase_route_still_refuses_a_pseudocomponent():
    pytest.importorskip("thermo")
    from chemeascode.domains.process.thermodynamics.phase import phase_determination

    with pytest.raises(ValueError):
        phase_determination(
            ["pseudo:0123456789abcdef:1", "ethane"],
            [0.5, 0.5],
            300.0,
            "K",
            101.325,
            "kPa",
            {"eos_model": "Peng-Robinson"},
            False,
        )
