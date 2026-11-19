"""A still's charge that enters above its bubble point at the still's pressure flashes to it
first (``still.flash``, ADR 0077, core#279): adiabatically and differentially, its vapour to the
first cut, the boil-up credited. Against the closed form of one volatile component, an
independent integration of a binary, the balances, and a still without the field as before."""

import math

import pytest
import yaml
from pydantic import ValidationError

from chemeascode.domains.process.batch_still import (
    StillError,
    report_text,
    solve_still,
    still_report,
)
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.model_basis import FLASH
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.schema import Component, Still, VapourPressure
from chemeascode.foundation.workspace import Workspace
from tests import test_batch_still as still

BENZENE = VapourPressure.model_validate(still.BENZENE | {"provenance": "given"})
TOLUENE = VapourPressure.model_validate(still.TOLUENE | {"provenance": "given"})
CP = {"A": 136.0, "B": 157.0, "P": 200.0}  # kJ/(kmol K)
LATENT = {"A": 30720.0, "B": 33180.0}  # kJ/kmol


def _components(cp=True):
    found = {}
    for n, vp, mw in (("A", still.BENZENE, 78.11), ("B", still.TOLUENE, 92.14)):
        data = {
            "id": n,
            "name": n,
            "molar_mass": mw,
            "heat_of_vaporization": LATENT[n],
            "vapour_pressure": vp | {"provenance": "given"},
        }
        if cp:
            data["liquid_heat_capacity"] = CP[n]
        found[n] = Component.model_validate(data)
    found["P"] = Component.model_validate(
        {"id": "P", "name": "product", "molar_mass": 128.17}
        | ({"liquid_heat_capacity": CP["P"]} if cp else {})
    )
    return found


def _still(**kw):
    spec = {
        "pressure": 30.0,
        "volatility": {"model": "raoult", "provenance": "given", "source": "NIST WebBook"},
        "nonvolatile": ["P"],
        "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
        "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
        "outlets": {"distillate": "top", "residue": "bottom"},
        "provenance": "assumed",
    }
    return Still.model_validate(spec | kw)


def _root(f, lo, hi):
    """x in [lo, hi] where f(x) changes sign (bisection, f(lo) < 0 < f(hi) or the reverse)."""
    flo = f(lo)
    for _ in range(200):
        mid = (lo + hi) / 2
        if (f(mid) > 0) == (flo > 0):
            lo, flo = mid, f(mid)
        else:
            hi = mid
    return (lo + hi) / 2


# -- the flash itself ---------------------------------------------------------------------------


def test_one_volatile_component_flashes_as_its_closed_form():
    """Benzene A over the non-volatile P: the vapour is pure A, so dN_A/dT = C/lambda with
    C = N_A cp_A + N_P cp_P, and C falls as exp(cp_A (T - T_in)/lambda). The flash ends where
    x_A P_A(T) = P; its heat is lambda times the A flashed. The boil-up from the flashed liquid
    to the same residue is short of the unflashed one's by exactly that heat (the credit)."""
    t_in, p = 360.0, 30.0
    n_a, n_p = 6.0, 4.0
    spec = _still(flash=True, pressure=p)
    comps = _components()
    result = solve_still(spec, {"A": n_a, "P": n_p}, None, comps, p, 2.0, charge_temperature=t_in)
    lam, cp_a, cp_p = LATENT["A"], CP["A"], CP["P"]
    c0 = n_a * cp_a + n_p * cp_p

    def a_left(t):
        return (c0 * math.exp(cp_a * (t - t_in) / lam) - n_p * cp_p) / cp_a

    t_end = _root(lambda t: a_left(t) / (a_left(t) + n_p) * BENZENE.kpa(t) - p, 300.0, t_in)
    flash = result.flash
    assert flash.outlet == "top" and flash.pressure == p
    assert flash.inlet_temperature == t_in
    assert flash.bubble_point == pytest.approx(
        _root(lambda t: n_a / (n_a + n_p) * BENZENE.kpa(t) - p, 250.0, t_in), abs=1e-8
    )
    assert flash.temperature == pytest.approx(t_end, abs=1e-8)
    assert flash.moles["A"] == pytest.approx(n_a - a_left(t_end), rel=1e-9)
    assert set(flash.moles) == {"A"}  # P stays
    assert flash.heat == pytest.approx(2.0 * lam * flash.moles["A"], rel=1e-9)  # per batch
    # the boil-up starts at the flashed liquid's bubble point: its own heat-up is none
    assert result.temperatures[0] == pytest.approx(t_end, abs=1e-8)
    # the first cut holds the flash's vapour; the boil-up's energy is credited by its heat
    plain = solve_still(_still(pressure=p), {"A": n_a, "P": n_p}, None, comps, p, 2.0)
    assert result.residue["A"] == pytest.approx(plain.residue["A"], rel=1e-9)
    assert result.cuts[0].moles["A"] == pytest.approx(plain.cuts[0].moles["A"], rel=1e-9)
    assert plain.energy - result.energy == pytest.approx(flash.heat, rel=1e-7)
    assert result.cuts[0].energy == pytest.approx(result.energy, rel=1e-12)
    assert result.time < plain.time
    # the profile starts at the flash's share distilled
    assert result.profile[0][0] == pytest.approx(flash.moles["A"] / (n_a + n_p), rel=1e-12)


def _independent_flash(n, t_in, p, step=0.01):
    """The binary's differential flash, by RK4 in T with a fixed *step*, the last step
    bisected to the bubble point: (kmol of A and B left, K)."""

    def rates(n, t):
        pa, pb = n[0] * BENZENE.kpa(t), n[1] * TOLUENE.kpa(t)
        ya, yb = pa / (pa + pb), pb / (pa + pb)
        c = n[0] * CP["A"] + n[1] * CP["B"]
        rate = c / (ya * LATENT["A"] + yb * LATENT["B"])
        return [ya * rate, yb * rate]  # kmol per K cooled

    def rk4(n, t, h):
        k1 = rates(n, t)
        k2 = rates([a - h / 2 * k for a, k in zip(n, k1, strict=True)], t - h / 2)
        k3 = rates([a - h / 2 * k for a, k in zip(n, k2, strict=True)], t - h / 2)
        k4 = rates([a - h * k for a, k in zip(n, k3, strict=True)], t - h)
        return [
            a - h / 6 * (q1 + 2 * q2 + 2 * q3 + q4)
            for a, q1, q2, q3, q4 in zip(n, k1, k2, k3, k4, strict=True)
        ]

    def above(n, t):
        return (n[0] * BENZENE.kpa(t) + n[1] * TOLUENE.kpa(t)) / (n[0] + n[1]) - p

    t = t_in
    while True:
        new = rk4(n, t, step)
        if above(new, t - step) <= 0:
            h = _root(lambda h, n=n, t=t: above(rk4(n, t, h), t - h), 0.0, step)
            return rk4(n, t, h), t - h
        n, t = new, t - step


def test_a_binary_flashes_as_an_independent_integration():
    """Benzene-toluene at 30 kPa(a) from 365 K: the flash's end against RK4 in T; it ends at the
    left liquid's bubble point, above the charge's, and its heat is the vapour's latent heat."""
    t_in, p = 365.0, 30.0
    charge = {"A": 5.0, "B": 5.0}
    result = solve_still(
        _still(flash=True), charge, None, _components(), p, charge_temperature=t_in
    )
    flash = result.flash
    left, t_end = _independent_flash([5.0, 5.0], t_in, p)
    assert flash.temperature == pytest.approx(t_end, abs=1e-6)
    assert flash.moles["A"] == pytest.approx(5.0 - left[0], rel=1e-7)
    assert flash.moles["B"] == pytest.approx(5.0 - left[1], rel=1e-7)
    assert flash.bubble_point < flash.temperature < t_in
    rest = {n: charge[n] - flash.moles[n] for n in charge}
    x = rest["A"] / sum(rest.values())
    bubble = _root(lambda t: x * BENZENE.kpa(t) + (1 - x) * TOLUENE.kpa(t) - p, 250.0, t_in)
    assert flash.temperature == pytest.approx(bubble, abs=1e-8)
    latent = sum(v * LATENT[n] for n, v in flash.moles.items())
    assert flash.heat == pytest.approx(latent, rel=1e-9)
    # the vapour is richer in benzene than the charge
    assert flash.moles["A"] / sum(flash.moles.values()) > 0.5
    # and each component balances over the flash, the cut and the residue
    for n, v in charge.items():
        assert result.cuts[0].moles[n] + result.residue[n] == pytest.approx(v, rel=1e-12)


def test_a_charge_below_its_bubble_point_does_not_flash():
    """Below its bubble point the charge solves exactly as without the field; the flash says
    it took nothing."""
    charge = {"A": 6.0, "P": 4.0}
    comps = _components()
    flashed = solve_still(_still(flash=True), charge, None, comps, 30.0, charge_temperature=300.0)
    plain = solve_still(_still(), charge, None, comps, 30.0)
    assert flashed.flash.moles == {} and flashed.flash.heat == 0.0
    assert flashed.flash.temperature == 300.0
    assert flashed.flash.bubble_point == pytest.approx(plain.temperatures[0], abs=1e-9)
    assert flashed.cuts[0].moles == plain.cuts[0].moles
    assert flashed.residue == plain.residue
    assert flashed.energy == plain.energy and flashed.time == plain.time
    assert flashed.profile == plain.profile


def test_the_flash_goes_to_the_first_cut_and_counts_as_distilled():
    """With cuts at the first cut's own pressure, the flash is to that pressure and into that
    cut; an end at a share distilled counts the flash's vapour."""
    cuts = [
        {"outlet": "fore", "pressure": 20.0, "end": {"distilled": 0.3}},
        {"outlet": "main", "end": {"residue": {"key": "A", "mole_fraction": 0.1}}},
    ]
    spec = _still(flash=True, end=None, cuts=cuts, outlets={"residue": "bottom"})
    charge = {"A": 5.0, "B": 5.0}
    result = solve_still(spec, charge, None, _components(), 30.0, charge_temperature=360.0)
    flash = result.flash
    assert flash.outlet == "fore" and flash.pressure == 20.0
    fore = result.cuts[0]
    assert sum(fore.moles.values()) == pytest.approx(0.3 * 10.0, rel=1e-9)
    assert all(fore.moles[n] >= flash.moles[n] for n in flash.moles)


def test_the_flash_is_refused_without_its_data_and_needs_raoult():
    charge = {"A": 6.0, "P": 4.0}
    with pytest.raises(StillError, match="charge's temperature"):
        solve_still(_still(flash=True), charge, None, _components(), 30.0)
    with pytest.raises(StillError, match="liquid_heat_capacity of A, P"):
        solve_still(
            _still(flash=True), charge, None, _components(cp=False), 30.0, charge_temperature=360
        )
    with pytest.raises(ValidationError, match="flash needs volatility raoult"):
        _still(
            flash=True,
            volatility={"model": "constant", "alpha": {"A": 2.0}, "provenance": "assumed"},
        )
    # a still without the field dumps as before
    assert "flash" not in _still().model_dump(mode="json")
    assert _still(flash=True).model_dump(mode="json")["flash"] is True


# -- in a plant: the report, propagate's duties, the fingerprint --------------------------------

MATERIALS = f"""\
schema: cheme/process/v1
kind: materials
components:
  - id: A
    name: benzene
    formula: C6H6
    molar_mass: 78.11
    heat_of_vaporization: 30720
    liquid_heat_capacity: 136
    vapour_pressure: {{a: {still.BENZENE["a"]}, b: {still.BENZENE["b"]}, c: {still.BENZENE["c"]},
      temperature_range: [287.7, 354.07], provenance: given, source: NIST WebBook}}
  - id: B
    name: toluene
    formula: C7H8
    molar_mass: 92.14
    heat_of_vaporization: 33180
    liquid_heat_capacity: 157
    vapour_pressure: {{a: {still.TOLUENE["a"]}, b: {still.TOLUENE["b"]}, c: {still.TOLUENE["c"]},
      temperature_range: [308.52, 384.66], provenance: given, source: NIST WebBook}}
templates:
  - {{id: liquid, components: [A, B]}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h, temperature: K, duty: kW}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
  - id: LPS
    category: utility
    utility: {kind: steam, level: LP}
    ports: [{id: q, direction: out, kind: energy}]
products:
  - {id: D, ports: [{id: in, direction: in}]}
  - {id: R, ports: [{id: in, direction: in}]}
  - id: CW
    category: utility
    utility: {kind: cooling_water}
    ports: [{id: q, direction: in, kind: energy}]
blocks:
  - id: S
    class: Distilling
    still:
      pressure: 30
      flash: true
      heat_up: true
      volatility: {model: raoult, provenance: given, source: NIST WebBook}
      boilup: {value: 20, unit: kmol/h, provenance: assumed, source: jacket estimate}
      end: {residue: {key: A, mole_fraction: 0.1}}
      outlets: {distillate: top, residue: bottom}
      condenser_port: condenser
      provenance: assumed
    ports:
      - {id: in, direction: in}
      - {id: top, direction: out}
      - {id: bottom, direction: out}
      - {id: steam, direction: in, kind: energy}
      - {id: condenser, direction: out, kind: energy}
streams:
  - id: S1
    from: F.out
    to: S.in
    template: liquid
    state:
      design:
        temperature: {value: 360, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 10, provenance: given}
        composition: {basis: mole_fraction, values: {A: 0.5, B: 0.5}, provenance: given}
  - id: S2
    from: S.top
    to: D.in
    template: liquid
  - id: S3
    from: S.bottom
    to: R.in
    template: liquid
  - id: Q1
    kind: energy
    from: LPS.q
    to: S.steam
  - id: Q2
    kind: energy
    from: S.condenser
    to: CW.q
"""


def _plant(tmp_path, flowsheet=FLOWSHEET):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: flash-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    return Workspace(root)


def _streams(ws):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return {s["id"]: s["state"]["design"] for s in data["streams"] if s.get("state")}


def test_the_report_and_propagate_carry_the_flash(tmp_path):
    ws = _plant(tmp_path)
    report = still_report(ws.root)
    (unit,) = report.units
    sol = unit["solution"]
    fl = sol["flash"]
    assert fl["outlet"] == "top" and fl["pressure_kPa"] == 30
    assert fl["inlet_temperature_K"] == 360
    assert fl["bubble_point_K"] < fl["temperature_K"] < 360
    assert fl["temperature_K"] == pytest.approx(sol["temperatures_K"][0], abs=1e-9)
    assert fl["kmol_h"] > 0 and fl["kmol_per_batch"] == fl["kmol_h"]  # one hour of flows
    assert fl["heat_kWh_per_batch"] == pytest.approx(fl["year_average_kW"], rel=1e-12)
    # the charge cools as it flashes: no heat-up, and no note that the flash is not modelled
    assert sol["heat_up_kWh_per_batch"] == 0.0
    assert not any("flash is not modelled" in n for n in sol["notes"])
    assert FLASH in unit["assumptions"]
    text = report_text(report)
    assert "flash at 30 kPa(a): the charge 360 -> " in text and "to cut top" in text
    # propagate writes the condenser's duty with the flash's vapour, the boil-up's without it
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    streams = _streams(ws)
    q1, q2 = streams["Q1"]["duty"], streams["Q2"]["duty"]
    boilup = sol["energy_kWh_per_batch"]  # one hour of flows: kWh per batch is kW
    assert q1["value"] == pytest.approx(boilup, rel=1e-5)
    assert q2["value"] == pytest.approx(boilup + fl["heat_kWh_per_batch"], rel=1e-5)
    top = streams["S2"]["flow"]["value"]
    assert top == pytest.approx(sol["cuts"][0]["kg_h"], rel=1e-5)  # the flash's vapour in it
    assert sol["cuts"][0]["kmol_h"] == pytest.approx(10.0 - sol["residue"]["kmol_h"], rel=1e-12)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    # the charge's temperature sets the outlets: a hotter one makes them stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace("temperature: {value: 360,", "temperature: {value: 362,")
    )
    process, _ = load(ws.root)
    stale = [f.message for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert any("S2" in m for m in stale), stale


def test_a_still_without_the_flash_reports_and_fingerprints_as_before(tmp_path):
    """Without the field, the charge above its bubble point keeps the note, no flash entry, and
    the charge's temperature stays out of the outlets' fingerprint."""
    ws = _plant(tmp_path, FLOWSHEET.replace("      flash: true\n", ""))
    (unit,) = still_report(ws.root).units
    sol = unit["solution"]
    assert "flash" not in sol and FLASH not in unit["assumptions"]
    assert any("(its flash is not modelled)" in n for n in sol["notes"])
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace("temperature: {value: 360,", "temperature: {value: 362,")
    )
    process, _ = load(ws.root)
    stale = [f.message for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert not any("S2" in m for m in stale), stale


def test_a_columns_first_cut_takes_the_flash_unrectified():
    """With a column, the flash's vapour joins the first cut as it flashed (the column has no
    reflux yet): the cut holds at least the flash's toluene, and the boil-up's column starts
    from the flashed liquid."""
    column = {"stages": 6, "reflux": "constant", "ratio": 3, "provenance": "assumed"}
    charge = {"A": 5.0, "B": 5.0}
    comps = _components()
    end = {"distilled": 0.4}
    spec = _still(flash=True, column=column, end=end)
    result = solve_still(spec, charge, None, comps, 30.0, charge_temperature=360.0)
    plain = solve_still(_still(column=column, end=end), charge, None, comps, 30.0)
    flash = result.flash
    (cut,) = result.cuts
    assert cut.moles["B"] >= flash.moles["B"] > 0
    assert sum(cut.moles.values()) == pytest.approx(4.0, rel=1e-9)
    # the unrectified flash takes more toluene to the cut than the column alone would
    assert cut.moles["B"] > plain.cuts[0].moles["B"]
    # and saves the reboiler (R + 1) times what it would boil up for the flash's vapour
    assert result.energy < plain.energy - flash.heat
