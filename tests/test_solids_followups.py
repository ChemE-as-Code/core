"""Crystallizer, filter and dryer follow-ups of ADRs 0056 and 0057 (ADR 0076): one solubility
point carried to the crystallizer's temperature, the mother liquor checked against the liquor a
solubility was measured in, a displacement wash with the wash's dissolution, a second liquid
phase, and the dryer's selective drying, sublimation, cooling and vacuum condenser.

Every expected value is a hand calculation written out in the test (the closed forms of the
module docstrings), not a value computed with the code. The vapour pressures in the plants are
test values (Antoine constants chosen for round numbers), not any substance's.
"""

from __future__ import annotations

import math
from types import SimpleNamespace as N

import pytest
import yaml

from chemeascode.domains.process.crystallization import (
    CrystallizationError,
    Liquor,
    Slurry,
    crystal_form,
    crystallizer_report,
    report_text,
    separate_solids,
    solubility_at,
    solve_train,
    transferred,
    wash_cake,
)
from chemeascode.domains.process.dryer import (
    DryerError,
    condense_vapour,
    dry_mass,
    flash,
    kept_by,
    ruth_hours,
    wash_hours,
)
from chemeascode.domains.process.model import balances, load, rules, stream_flows
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import recipe_report
from chemeascode.domains.process.schema import (
    Crystallizer,
    Dryer,
    SolidSeparation,
    Solubility,
)
from chemeascode.foundation.workspace import Workspace

R = 8.314462618  # kJ/(kmol K)
NBS, WATER = 177.985, 18.015  # kg/kmol, as the materials below state them


def _plant(tmp_path, materials, flowsheet, recipe=None):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: solids-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    if recipe is not None:
        (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    return Workspace(root)


def _propagated(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert not [f.format() for f in result.findings if f.level == "error"]
    process, _ = load(ws.root)
    return process


def _stream(process, stream_id):
    return next(s for s in process.flowsheet.streams if s.id == stream_id)


def _mass(process, stream_id):
    return stream_flows(process, _stream(process, stream_id), "design").components


# -- one solubility point, carried to the crystallizer's temperature -----------------------------


def test_one_point_is_carried_by_van_t_hoff_against_a_hand_calculation():
    # 0.0147 kg NBS per kg water at 298.15 K, carried to 278.15 K at 20 000 kJ/kmol:
    # r0 = 0.0147 x 18.015 / 177.985 = 0.00148788 kmol/kmol, x0 = r0 / (1 + r0) = 0.00148567,
    # exponent -20000 / R (1/278.15 - 1/298.15) = -0.580112, x = 0.000831731,
    # s = x / (1 - x) x 177.985 / 18.015 = 0.00822420 kg/kg
    s = transferred(0.0147, 298.15, 278.15, 20000.0, NBS, WATER)
    assert s == pytest.approx(0.00822420, rel=1e-5)
    r0 = 0.0147 * WATER / NBS
    x = r0 / (1 + r0) * math.exp(-20000 / R * (1 / 278.15 - 1 / 298.15))
    assert s == pytest.approx(x / (1 - x) * NBS / WATER, rel=1e-12)
    # no heat of solution: the point holds unchanged; a negative one raises it on cooling
    assert transferred(0.0147, 298.15, 278.15, 0.0, NBS, WATER) == pytest.approx(0.0147)
    assert transferred(0.0147, 298.15, 278.15, -20000.0, NBS, WATER) > 0.0147
    # a mass fraction is converted to kg per kg of solvent first: 0.2 -> 0.25
    spec = Solubility(
        unit="mass_fraction",
        points=[(298.15, 0.2)],
        transfer={"heat_of_solution": 0.0, "provenance": "assumed"},
        provenance="assumed",
    )
    assert solubility_at(spec, 278.15, (NBS, WATER)) == pytest.approx(0.25, rel=1e-12)
    with pytest.raises(CrystallizationError, match="needs the solute's and solvent's"):
        solubility_at(spec, 278.15)
    with pytest.raises(CrystallizationError, match="miscible"):
        transferred(0.0147, 298.15, 500.0, 2.0e6, NBS, WATER)


def test_the_schema_takes_a_transfer_of_one_pure_solvent_point_only():
    transfer = {"heat_of_solution": 1.0e4, "provenance": "assumed"}
    with pytest.raises(ValueError, match="carries one point"):
        Solubility(unit="kg/kg_solvent", value=0.01, transfer=transfer, provenance="assumed")
    with pytest.raises(ValueError, match="carries one point"):
        Solubility(
            unit="kg/kg_solvent",
            points=[(280.0, 0.01), (300.0, 0.02)],
            transfer=transfer,
            provenance="assumed",
        )
    with pytest.raises(ValueError, match="pure-solvent solubility"):
        Solubility(
            unit="kg/kg_solvent",
            points=[(298.15, 0.01)],
            measured_in="mother_liquor",
            transfer=transfer,
            provenance="assumed",
        )
    with pytest.raises(ValueError, match="measured_in: mother_liquor"):
        Solubility(
            unit="kg/kg_solvent",
            value=0.01,
            liquor={"mass_fraction": {"NaCl": 0.1}, "tolerance": 0.1, "provenance": "given"},
            provenance="assumed",
        )
    # left out of the dump when not given: an old crystallizer's fingerprint stays
    plain = Solubility(unit="kg/kg_solvent", points=[(298.15, 0.01)], provenance="assumed")
    assert set(plain.model_dump(mode="json")) == {"unit", "points", "value", "provenance", "source"}


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: NBS, name: N-bromosuccinimide (dissolved), formula: C4H4BrNO2, molar_mass: 177.985}
  - {id: NBS_S, name: N-bromosuccinimide crystals, formula: C4H4BrNO2, molar_mass: 177.985,
     phase: solid}
  - {id: H2O, name: water, formula: H2O, molar_mass: 18.015}
  - {id: NABR, name: sodium bromide, formula: NaBr, molar_mass: 102.894}
  - {id: NAOH, name: sodium hydroxide, formula: NaOH, molar_mass: 39.997}
templates:
  - {id: liquor, components: [NBS, NBS_S, H2O, NABR, NAOH]}
"""

SOLUBILITY = (
    "{unit: kg/kg_solvent, points: [[298.15, 0.0147]], provenance: given, "
    'source: "test value at 25 C", transfer: {heat_of_solution: 20000, provenance: assumed, '
    'source: "test value"}, salting_out: {coefficients: {NABR: 0, NAOH: 0}, '
    'provenance: assumed, source: "test: no correction"}}'
)

PRECIPITATION = """\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: L, ports: [{id: out, direction: out}]}
  - {id: WW, ports: [{id: out, direction: out}]}
products:
  - {id: ML, ports: [{id: in, direction: in}]}
  - {id: WF, ports: [{id: in, direction: in}]}
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: CR
    class: Crystallizing
    ports: [{id: in, direction: in}, {id: out, direction: out}]
    crystallizer:
      solute: NBS
      solvent: H2O
      crystal: NBS_S
      basis: solubility
      temperature: 278.15
      solubility: SOLUBILITY
      spectators: [NABR, NAOH]
      outlets: {slurry: out}
  - id: F1
    class: Filtering
    ports:
      - {id: in, direction: in}
      - {id: wash, direction: in}
      - {id: cake, direction: out}
      - {id: filtrate, direction: out}
      - {id: washings, direction: out}
    solid_separation:
      solid_recovery: 1.0
      cake_liquid: {value: 0.3, basis: per_kg_solid}
      outlets: {cake: cake, filtrate: filtrate, wash_filtrate: washings}
      provenance: assumed
      wash:
        port: wash
        efficiency: 0.6
        provenance: assumed
        dissolution:
          crystal: NBS_S
          solute: NBS
          temperature: 278.15
          solubility: {unit: kg/kg_solvent, value: 0.01, provenance: assumed}
          saturation: 0.5
          provenance: assumed
streams:
  - id: S1
    from: L.out
    to: CR.in
    template: liquor
    state:
      design:
        temperature: {value: 278.15, provenance: given}
        flow: {value: 1000, provenance: given}
        composition: {basis: mass_fraction, values: {NBS: 0.05, H2O: 0.918, NABR: 0.03,
                      NAOH: 0.002}, provenance: given}
  - id: S2
    from: CR.out
    to: F1.in
    template: liquor
  - id: S3
    from: F1.filtrate
    to: ML.in
    template: liquor
  - id: S4
    from: F1.cake
    to: P.in
    template: liquor
  - id: S5
    from: WW.out
    to: F1.wash
    template: liquor
    state:
      design:
        temperature: {value: 278.15, provenance: given}
        flow: {value: 60, provenance: given}
        composition: {basis: mass_fraction, values: {H2O: 1.0}, provenance: given}
  - id: S6
    from: F1.washings
    to: WF.in
    template: liquor
""".replace("SOLUBILITY", SOLUBILITY)

#: CR's saturated liquor at 278.15 K, no salting out: s from the transfer above
S_278 = 0.00822420


def test_a_transferred_point_solves_the_crystallizer_and_is_reported_as_such(tmp_path):
    ws = _plant(tmp_path, MATERIALS, PRECIPITATION)
    process = _propagated(ws)
    # C = 50 - s x 918 (per kg of solvent, the spectators carried)
    slurry = _mass(process, "S2")
    assert slurry["NBS_S"] == pytest.approx(50 - S_278 * 918, rel=1e-5)
    report = crystallizer_report(ws.root)
    cr = next(u for u in report.units if u["node"] == "CR")
    transfer = cr["solution"]["solubility_transfer"]
    assert transfer["from_temperature_K"] == 298.15 and transfer["temperature_K"] == 278.15
    assert transfer["kg_per_kg_solvent"] == pytest.approx(S_278, rel=1e-5)
    assert "not measured at the operating conditions" in transfer["basis"]
    (finding,) = [f for f in report.findings if f.rule == "cheme.process-crystallizer-transfer"]
    assert finding.level == "info" and "not a value at the operating conditions" in finding.message
    assert "solubility carried from 298.15 K" in report_text(report)
    (basis,) = [u for u in model_bases(process) if u.id == "CR"]
    assert "carried there (van 't Hoff" in basis.detail
    assert "not at the operating conditions" in basis.detail
    # the transfer is assumed: the basis is not sourced, though the point is
    assert basis.sourced is False and "transfer" in basis.detail
    # without the transfer the single point is refused, as before
    plain = PRECIPITATION.replace(
        ', transfer: {heat_of_solution: 20000, provenance: assumed, source: "test value"}', ""
    )
    ws = _plant(tmp_path / "plain", MATERIALS, plain)
    process, _ = load(ws.root)
    (outside,) = [f for f in rules(process) if "outside the solubility data" in f.message]
    assert outside.level == "error" and "transfer:" in outside.hint


# -- the mother liquor against the liquor the solubility was measured in --------------------------


def test_the_solved_liquor_is_compared_with_the_measured_one():
    # 100 kg/h solute, 800 solvent, 100 NaCl, 0.05 kg per kg of solute-free liquor: 45 kg/h stay
    # dissolved, the liquor 945 kg/h holds 100 / 945 = 0.10582 NaCl, 5.82 % above 0.1
    form = crystal_form("C4H4BrNO2", "H2O", "C4H4BrNO2")
    feed = Slurry(solute=100.0, solvent=800.0, spectators={"NaCl": 100.0})

    def liquor(tolerance):
        return Liquor(
            molar_mass={"NaCl": 58.44},
            basis="liquor",
            measured={"NaCl": 0.1},
            tolerance=tolerance,
        )

    check = solve_train(feed, form, solubility=0.05, liquor=liquor(0.05)).liquor["composition"]
    assert check["mass_fraction"]["NaCl"]["solved"] == pytest.approx(100 / 945, rel=1e-12)
    assert check["mass_fraction"]["NaCl"]["relative_difference"] == pytest.approx(
        100 / 945 / 0.1 - 1, rel=1e-12
    )
    assert check["outside"] == ["NaCl"]
    inside = solve_train(feed, form, solubility=0.05, liquor=liquor(0.06)).liquor["composition"]
    assert inside["outside"] == []
    # not asked for: not in the report
    plain = solve_train(feed, form, solubility=0.05, liquor=Liquor(molar_mass={"NaCl": 58.44}))
    assert "composition" not in plain.liquor


def test_a_liquor_beyond_its_tolerance_is_a_warning(tmp_path):
    # CR measured in its liquor at 0.0147 kg per kg of solute-free liquor: 0.0147 x 950 =
    # 13.965 kg/h stay dissolved, the liquor 963.965 kg/h holds NaBr 30 / 963.965 = 0.031121
    # (38 % below the 0.05 measured in) and NaOH 2 / 963.965 = 0.0020748 (3.7 % above 0.002)
    measured = (
        "{unit: kg/kg_liquor, value: 0.0147, measured_in: mother_liquor, provenance: given, "
        'source: "test", liquor: {mass_fraction: {NABR: 0.05, NAOH: 0.002}, tolerance: 0.1, '
        'provenance: given, source: "test"}}'
    )
    flowsheet = PRECIPITATION.replace(SOLUBILITY, measured)
    ws = _plant(tmp_path, MATERIALS, flowsheet)
    _propagated(ws)
    report = crystallizer_report(ws.root)
    cr = next(u for u in report.units if u["node"] == "CR")
    check = cr["solution"]["mother_liquor"]["composition"]
    assert check["mass_fraction"]["NABR"]["solved"] == pytest.approx(30 / 963.965, rel=1e-5)
    assert check["mass_fraction"]["NAOH"]["solved"] == pytest.approx(2 / 963.965, rel=1e-5)
    (finding,) = [f for f in report.findings if f.rule == "cheme.process-crystallizer-liquor"]
    assert finding.level == "warning" and "NABR" in finding.message
    assert "the solubility may not hold there" in finding.message
    assert "liquor NABR: 0.03112 (measured in 0.05) outside the tolerance" in report_text(report)


# -- a displacement wash and the wash's dissolution ------------------------------------------------


CAKE = {"X_s": 400.0, "X": 10 / 6, "NaBr": 40 / 6, "H2O": 550 / 6}  # 100 kg/h of liquor


def test_a_displacement_wash_against_a_hand_calculation():
    spec = N(efficiency=0.5, dissolution=None)
    held = N(value=0.25, basis="per_kg_solid")
    # n = 200 / 100 = 2, R = 0.5^2 = 0.25: 25 kg/h of the liquor stay, the cake holds 100 kg/h,
    # so 75 kg/h of the 200 kg/h of wash stay with it
    washed, filtrate, what = wash_cake(CAKE, {"H2O": 200.0}, {"X_s"}, spec, held)
    assert (what["wash_ratio"], what["remaining_fraction"]) == pytest.approx((2.0, 0.25))
    assert what["liquor_kept_kg_h"] == pytest.approx(25.0)
    assert washed["NaBr"] == pytest.approx(40 / 6 * 0.25, rel=1e-12)
    assert washed["H2O"] == pytest.approx(550 / 6 * 0.25 + 75.0, rel=1e-12)
    assert washed["X_s"] == 400.0 and "X_s" not in filtrate
    assert filtrate["NaBr"] == pytest.approx(40 / 6 * 0.75, rel=1e-12)
    assert filtrate["H2O"] == pytest.approx(550 / 6 * 0.75 + 125.0, rel=1e-12)
    for name in CAKE:
        assert washed[name] + filtrate.get(name, 0.0) == pytest.approx(
            CAKE[name] + (200.0 if name == "H2O" else 0.0), rel=1e-12
        )
    # a dissolution: 0.01 kg per kg of wash, saturation 0.6: 1.2 kg/h of crystals dissolve
    # (the wash brings none); the cake 398.8 kg/h holds 99.7 kg/h, 25 of them its liquor
    dissolving = N(saturation=0.6, crystal="X_s", solute="X")
    spec = N(efficiency=0.5, dissolution=dissolving)
    washed, filtrate, what = wash_cake(CAKE, {"H2O": 200.0}, {"X_s"}, spec, held, 0.01)
    assert what["dissolved_kg_h"] == pytest.approx(1.2, rel=1e-12)
    assert washed["X_s"] == pytest.approx(398.8, rel=1e-12)
    assert what["cake_liquid_kg_h"] == pytest.approx(99.7, rel=1e-12)
    assert what["wash_kept_kg_h"] == pytest.approx(74.7, rel=1e-12)
    share = 74.7 / 201.2  # of the wash with its dissolved solute
    assert washed["X"] == pytest.approx(10 / 6 * 0.25 + 1.2 * share, rel=1e-12)
    assert filtrate["X"] == pytest.approx(10 / 6 * 0.75 + 1.2 * (1 - share), rel=1e-12)
    # never more than the crystals there are
    _, _, what = wash_cake(CAKE, {"H2O": 200.0}, {"X_s"}, spec, held, 1e4)
    assert what["dissolved_kg_h"] == pytest.approx(400.0)
    with pytest.raises(CrystallizationError, match="wash liquid holds the solid"):
        wash_cake(CAKE, {"X_s": 1.0}, {"X_s"}, spec, held)
    with pytest.raises(CrystallizationError, match="the washed cake holds"):
        wash_cake(CAKE, {"H2O": 1.0}, {"X_s"}, N(efficiency=0.9, dissolution=None), held)


def test_a_washed_filter_propagates_balances_and_reports(tmp_path):
    ws = _plant(tmp_path, MATERIALS, PRECIPITATION)
    process = _propagated(ws)
    slurry, cake, filtrate, washings = (_mass(process, s) for s in ("S2", "S4", "S3", "S6"))
    crystals = 50 - S_278 * 918
    liquor = {n: v for n, v in slurry.items() if n != "NBS_S"}
    total = sum(liquor.values())
    # the unwashed cake holds 0.3 crystals of the slurry's liquor, divided as it is
    unwashed = 0.3 * crystals
    assert filtrate["NABR"] == pytest.approx(30.0 * (1 - unwashed / total), rel=1e-5)
    # the wash dissolves 0.5 x 0.01 x 60 = 0.3 kg/h; n = 60 / unwashed, R = 0.4^n
    remaining = 0.4 ** (60 / unwashed)
    assert cake["NBS_S"] == pytest.approx(crystals - 0.3, rel=1e-5)
    kept = remaining * unwashed
    assert cake["NABR"] == pytest.approx(30.0 * unwashed / total * kept / unwashed, rel=1e-4)
    assert washings["NBS"] + cake["NBS"] + filtrate["NBS"] == pytest.approx(
        slurry["NBS"] + 0.3, rel=1e-5
    )
    for b in balances(process, "design"):
        assert b.status == "ok", (b.node, b.failing)
    report = crystallizer_report(ws.root)
    f1 = next(u for u in report.units if u["node"] == "F1")
    wash = f1["solution"]["wash"]
    assert wash["dissolved_kg_h"] == pytest.approx(0.3, rel=1e-5)
    assert wash["remaining_fraction"] == pytest.approx(remaining, rel=1e-5)
    assert "wash 60 kg/h, ratio" in report_text(report)
    (basis,) = [u for u in model_bases(process) if u.id == "F1"]
    assert "displacement wash, efficiency 0.6 dissolving NBS_S" in basis.detail
    assert any("R = (1 - E)^n" in a for a in basis.assumptions)


def test_a_filter_is_not_sourced_while_its_wash_is_assumed(tmp_path):
    given = PRECIPITATION.replace(
        "      outlets: {cake: cake, filtrate: filtrate, wash_filtrate: washings}\n"
        "      provenance: assumed\n",
        "      outlets: {cake: cake, filtrate: filtrate, wash_filtrate: washings}\n"
        "      provenance: given\n      source: vendor test\n",
    )
    ws = _plant(tmp_path, MATERIALS, given)
    process = _propagated(ws)
    (basis,) = [u for u in model_bases(process) if u.id == "F1"]
    assert basis.sourced is False and basis.sources == ["vendor test"]
    assert basis.detail.endswith(
        "; not sourced: wash, wash.dissolution, wash.dissolution.solubility"
    )
    assert "solid_separation F1: basis solid-split (specified, not sourced)" in report_text(
        crystallizer_report(ws.root)
    )
    # every part given with a source: sourced, with each source
    sourced = (
        given.replace(
            "        efficiency: 0.6\n        provenance: assumed\n",
            "        efficiency: 0.6\n        provenance: given\n        source: wash test\n",
        )
        .replace(
            "solubility: {unit: kg/kg_solvent, value: 0.01, provenance: assumed}",
            'solubility: {unit: kg/kg_solvent, value: 0.01, provenance: given, source: "sol"}',
        )
        .replace(
            "          saturation: 0.5\n          provenance: assumed\n",
            "          saturation: 0.5\n          provenance: given\n          source: wash test\n",
        )
    )
    ws = _plant(tmp_path / "sourced", MATERIALS, sourced)
    process = _propagated(ws)
    (basis,) = [u for u in model_bases(process) if u.id == "F1"]
    assert basis.sourced is True and "not sourced" not in basis.detail
    assert basis.sources == ["vendor test", "wash test", "sol"]


def test_a_wash_without_its_port_or_with_a_wrong_dissolution_is_refused(tmp_path):
    flowsheet = PRECIPITATION.replace("        port: wash\n", "        port: other\n")
    ws = _plant(tmp_path, MATERIALS, flowsheet)
    process, _ = load(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.process-solid-separation"]
    assert any("takes two material inlets" in f.message for f in found)
    flowsheet = PRECIPITATION.replace("          crystal: NBS_S\n", "          crystal: NABR\n")
    ws = _plant(tmp_path / "b", MATERIALS, flowsheet)
    process, _ = load(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.process-solid-separation"]
    assert any("'NABR' must be a solid component" in f.message for f in found)
    with pytest.raises(ValueError, match="wash_filtrate: needs wash"):
        SolidSeparation(
            solid_recovery=1.0,
            cake_liquid={"value": 0.3, "basis": "per_kg_solid"},
            outlets={"cake": "c", "filtrate": "f", "wash_filtrate": "w"},
            provenance="assumed",
        )


def test_the_wash_time_is_the_final_filtration_rate():
    # 100 kg cake solid, 0.1 m3 of wash on 1 m2 at 100 kPa, 1 mPa s, alpha 1e10 m/kg, R_m 1e10:
    # t = 1e-3 x 0.1 x (1e10 x 100 / 1 + 1e10 / 1) / 1e5 = 1010 s
    filtration = N(
        viscosity=1.0,
        pressure_difference=100.0,
        specific_cake_resistance=1e10,
        medium_resistance=1e10,
    )
    assert wash_hours(filtration, 100.0, 0.1, 1.0) == pytest.approx(1010 / 3600, rel=1e-12)
    # twice the rate at the end of Ruth's filtration of V: dt/dV there is twice its mean
    # cake term, so the wash of V takes 2 t_cake + t_medium
    ruth = ruth_hours(filtration, 100.0, 0.1, 1.0)
    medium = 1e-3 * 1e10 * 0.1 / 1e5 / 3600
    assert wash_hours(filtration, 100.0, 0.1, 1.0) == pytest.approx(
        2 * (ruth - medium) + medium, rel=1e-12
    )


def _filtered(tmp_path, wash_kg_h):
    """The PRECIPITATION plant with a filtration on F1 (1000 kg/m3 for every component) and a
    recipe of one filter step from F1 in a vessel of fill 0.5, HOURS of flows a batch."""
    materials = MATERIALS
    for mm in ("177.985", "18.015", "102.894", "39.997"):
        materials = materials.replace(
            f"molar_mass: {mm}", f"molar_mass: {mm}, liquid_molar_volume: {float(mm) / 1000:g}"
        )
    flowsheet = PRECIPITATION.replace(
        "      provenance: assumed\n      wash:\n",
        "      provenance: assumed\n"
        "      filtration: {specific_cake_resistance: 1.0e+10, medium_resistance: 1.0e+10,\n"
        "                   pressure_difference: 100, viscosity: 1.0, filtrate_density: 1000,\n"
        "                   area: 1.0, provenance: assumed}\n"
        "      wash:\n",
    ).replace(
        "flow: {value: 60, provenance: given}", f"flow: {{value: {wash_kg_h}, provenance: given}}"
    )
    assert "filtration:" in flowsheet and f"value: {wash_kg_h}," in flowsheet
    ws = _plant(tmp_path, materials, flowsheet)
    process = _propagated(ws)
    recipe = {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {
            "value": sum(_mass(process, "S4").values()) * HOURS,
            "unit": "kg",
            "stream": "S4",
            "provenance": "assumed",
        },
        "hours_per_year": {"value": 8000, "provenance": "assumed"},
        "unit_procedures": [
            {
                "id": "ISO",
                "unit": "F1",
                "vessel": {"fill_fraction": 0.5, "provenance": "assumed"},
                "operations": [{"id": "filter", "kind": "filter", "from": "F1"}],
            }
        ],
    }
    (ws.root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    return process, recipe_report(ws.root)


def test_a_washed_filter_is_timed_and_sized_on_its_unwashed_cake(tmp_path):
    process, report = _filtered(tmp_path, 60)
    slurry, cake = _mass(process, "S2"), _mass(process, "S4")
    # Ruth's filtration builds the cake of the slurry's crystals, before the wash dissolves
    # 0.3 kg/h of them; the wash passes that cake at the final rate
    crystals = slurry["NBS_S"] * HOURS
    assert cake["NBS_S"] * HOURS == pytest.approx(crystals - 0.3 * HOURS, rel=1e-6)
    filtration = N(
        viscosity=1.0,
        pressure_difference=100.0,
        specific_cake_resistance=1e10,
        medium_resistance=1e10,
    )
    filtrate = sum(_mass(process, "S3").values()) * HOURS / 1000
    washings = sum(_mass(process, "S6").values()) * HOURS / 1000
    (step,) = [s for s in report.steps if s.kind == "filter"]
    assert step.end - step.start == pytest.approx(
        ruth_hours(filtration, crystals, filtrate, 1.0)
        + wash_hours(filtration, crystals, washings, 1.0),
        rel=1e-6,  # the streams as propagate wrote them
    )
    # the vessel holds the slurry (1000 kg/h), the wash only once its filtrate has drained
    (vessel,) = report.vessels
    assert vessel.working_volume == pytest.approx(1000 * HOURS / 1000, rel=1e-6)
    # a wash larger than the slurry: the unwashed cake (0.3 kg of liquor per kg) with the wash
    process, report = _filtered(tmp_path / "large", 2000)
    unwashed = _mass(process, "S2")["NBS_S"] * 1.3
    (vessel,) = report.vessels
    assert vessel.working_volume == pytest.approx((unwashed + 2000) * HOURS / 1000, rel=1e-6)


# -- a second liquid phase -------------------------------------------------------------------------


def test_a_second_liquid_is_held_by_its_own_cake_liquid():
    # 100 solid, 100 liquor, 20 oil: the cake holds 30 of the liquor and 5 of the oil
    second = N(components=["OIL"], cake_liquid=N(value=0.05, basis="per_kg_solid"))
    mass = {"S": 100.0, "W": 90.0, "D": 10.0, "OIL": 20.0}
    cake, filtrate = separate_solids(mass, {"S"}, 1.0, N(value=0.3, basis="per_kg_solid"), second)
    assert cake == pytest.approx({"S": 100.0, "W": 27.0, "D": 3.0, "OIL": 5.0})
    assert filtrate == pytest.approx({"S": 0.0, "W": 63.0, "D": 7.0, "OIL": 15.0})
    # without it the oil divides with the liquor: 30 of 120
    cake, _ = separate_solids(mass, {"S"}, 1.0, N(value=0.3, basis="per_kg_solid"))
    assert cake["OIL"] == pytest.approx(5.0) and cake["W"] == pytest.approx(22.5)
    with pytest.raises(CrystallizationError, match="of the second liquid"):
        separate_solids(
            mass,
            {"S"},
            1.0,
            N(value=0.3, basis="per_kg_solid"),
            N(components=["OIL"], cake_liquid=N(value=0.5, basis="per_kg_solid")),
        )


def test_a_second_liquid_is_not_in_the_mother_liquor():
    # per kg of solute-free liquor 0.05: with the oil apart C = 100 - 0.05 (800 + 100) = 55,
    # with it counted C = 100 - 0.05 (800 + 100 + 50) = 52.5
    form = crystal_form("C4H4BrNO2", "H2O", "C4H4BrNO2")
    feed = Slurry(solute=100.0, solvent=800.0, spectators={"NaCl": 100.0, "OIL": 50.0})
    masses = {"NaCl": 58.44, "OIL": 150.0}
    apart = Liquor(molar_mass=masses, basis="liquor", second_liquid=("OIL",))
    assert solve_train(feed, form, solubility=0.05, liquor=apart).crystals_formed == (
        pytest.approx(55.0, rel=1e-12)
    )
    counted = Liquor(molar_mass=masses, basis="liquor")
    assert solve_train(feed, form, solubility=0.05, liquor=counted).crystals_formed == (
        pytest.approx(52.5, rel=1e-12)
    )
    result = solve_train(feed, form, solubility=0.05, liquor=apart)
    assert result.liquor["second_liquid"] == ["OIL"]
    assert set(result.liquor["molality_mol_per_kg_solvent"]) == {"NaCl"}
    base = {
        "solute": "A",
        "solvent": "W",
        "crystal": "A_s",
        "basis": "solubility",
        "spectators": ["NaCl", "OIL"],
        "outlets": {"slurry": "out"},
    }
    sol = {"unit": "kg/kg_solvent", "value": 0.1, "provenance": "assumed"}
    second = {"components": ["OIL"], "provenance": "assumed"}
    with pytest.raises(ValueError, match="spectators of the crystallizer"):
        Crystallizer(**base, solubility=sol, second_liquid={**second, "components": ["X"]})
    salting = {"coefficients": {"NaCl": 0.1}, "provenance": "assumed"}
    spec = Crystallizer(**base, solubility={**sol, "salting_out": salting}, second_liquid=second)
    assert spec.second_liquid.components == ["OIL"]
    with pytest.raises(ValueError, match="not the second liquid's"):
        Crystallizer(
            **base,
            solubility={**sol, "salting_out": {**salting, "coefficients": {"NaCl": 0, "OIL": 0}}},
            second_liquid=second,
        )
    # the liquor the data were measured in holds the dissolved spectators, not the oil (its
    # solved fraction would always be 0, outside any tolerance)
    measured = {
        "unit": "kg/kg_liquor",
        "value": 0.05,
        "measured_in": "mother_liquor",
        "provenance": "assumed",
    }
    liquor = {"tolerance": 0.1, "provenance": "assumed"}
    with pytest.raises(ValueError, match="dissolved spectators, not the second liquid's"):
        Crystallizer(
            **base,
            solubility={
                **measured,
                "liquor": {**liquor, "mass_fraction": {"NaCl": 0.1, "OIL": 0.05}},
            },
            second_liquid=second,
        )
    spec = Crystallizer(
        **base,
        solubility={**measured, "liquor": {**liquor, "mass_fraction": {"NaCl": 0.1}}},
        second_liquid=second,
    )
    assert spec.solubility.liquor.mass_fraction == {"NaCl": 0.1}


def test_a_second_liquid_alone_takes_a_pure_solvent_solubility(tmp_path):
    # the only spectators form the second liquid: the mother liquor is solute and solvent, so
    # the pure solvent's point (carried by its transfer) holds there, as without spectators
    oil = PRECIPITATION.replace(
        ', salting_out: {coefficients: {NABR: 0, NAOH: 0}, provenance: assumed, source: "test: '
        'no correction"}',
        "",
    ).replace(
        "      spectators: [NABR, NAOH]\n",
        "      spectators: [NABR, NAOH]\n"
        "      second_liquid: {components: [NABR, NAOH], provenance: assumed}\n",
    )
    assert oil.count("second_liquid") == 1 and "salting_out" not in oil
    ws = _plant(tmp_path, MATERIALS, oil)
    process = _propagated(ws)
    assert _mass(process, "S2")["NBS_S"] == pytest.approx(50 - S_278 * 918, rel=1e-5)
    report = crystallizer_report(ws.root)
    assert not [f for f in report.findings if f.level == "error"]
    (basis,) = [u for u in model_bases(process) if u.id == "CR"]
    assert "pure-solvent solubility, the second liquid apart" in basis.detail
    assert "a solubility in the mixed liquor" not in basis.detail
    # the second liquid sets the liquor: assumed, it leaves the basis not sourced
    assert basis.sourced is False
    assert basis.detail.endswith("; not sourced: transfer, second_liquid")
    # a dissolved spectator beside the oil still needs a solubility in the liquor
    mixed = oil.replace("components: [NABR, NAOH], provenance", "components: [NAOH], provenance")
    ws = _plant(tmp_path / "mixed", MATERIALS, mixed)
    process, _ = load(ws.root)
    (refused,) = [f for f in rules(process) if "is the pure solvent's" in f.message]
    assert refused.level == "error" and refused.message.endswith("the spectators NABR")


# -- the dryer: selective drying, sublimation, cooling and the vacuum condenser -------------------


def test_selective_drying_by_raoult_against_a_hand_calculation():
    # A at 100 kPa, B at 50 kPa: n_A = 10 f, n_B = 10 f^0.5; 10 f + 10 f^0.5 = 5 gives
    # f^0.5 = (-10 + sqrt(300)) / 20 = 0.366025, f = 0.133975
    share = kept_by({"A": 10.0, "B": 10.0}, {"A": 100.0, "B": 50.0}, 5.0)
    assert share["A"] == pytest.approx(0.133975, rel=1e-5)
    assert share["B"] == pytest.approx(0.366025, rel=1e-5)
    mass = {"S": 95.0, "A": 10.0, "B": 10.0}
    product, vapour = dry_mass(
        mass, ["A", "B"], N(value=0.05, basis="mass_fraction"), {"A": 100.0, "B": 50.0}
    )
    assert product["A"] + product["B"] == pytest.approx(0.05 / 0.95 * 95.0, rel=1e-12)
    assert product["A"] == pytest.approx(10 * 0.133975, rel=1e-5)
    # in the inlet's ratio the two would stay alike
    product, _ = dry_mass(mass, ["A", "B"], N(value=0.05, basis="mass_fraction"))
    assert product["A"] == pytest.approx(product["B"])
    # B without a vapour pressure there cannot dry below its own amount
    with pytest.raises(DryerError, match="cannot dry"):
        kept_by({"A": 10.0, "B": 10.0}, {"A": 100.0, "B": 0.0}, 5.0)


def test_selective_drying_of_a_volatile_far_less_volatile_than_the_main_one():
    # B 100x less volatile: keeping 10 kg of it needs n_B / n_B0 = f^0.01 = 0.1, f = 1e-100,
    # far below a bisection on f over [0, 1] (2^-200); keeping 1 kg needs f = 1e-200
    for kept, b in ((10.0, 0.1), (1.0, 0.01)):
        share = kept_by({"A": 10.0, "B": 100.0}, {"A": 100.0, "B": 1.0}, kept)
        assert share["B"] == pytest.approx(b, rel=1e-9)
        assert 10.0 * share["A"] + 100.0 * share["B"] == pytest.approx(kept, rel=1e-9)
    # nothing left: both shares go to (practically) nothing
    share = kept_by({"A": 10.0, "B": 100.0}, {"A": 100.0, "B": 1.0}, 0.0)
    assert 10.0 * share["A"] + 100.0 * share["B"] == pytest.approx(0.0, abs=1e-9)
    # the product holds the 1 % specified, not more
    product, _ = dry_mass(
        {"P": 1000.0, "A": 10.0, "B": 100.0},
        ["A", "B"],
        N(value=0.01, basis="mass_fraction"),
        {"A": 100.0, "B": 1.0},
    )
    assert (product["A"] + product["B"]) / sum(product.values()) == pytest.approx(0.01, rel=1e-9)


def test_the_condenser_flash_against_a_hand_calculation():
    # z 0.5 / 0.5, K 2 and 0.5: 0.5 / (1 + b) = 0.25 / (1 - 0.5 b), b = 0.5; the gas holds
    # 2 x 0.5 x 0.5 / 1.5 x 2 = 0.6667 of A and 0.5 x 0.5 x 0.5 / 0.75 x 2 = 0.3333 of B
    gas = flash({"A": 1.0, "B": 1.0}, {"A": 2.0, "B": 0.5})
    assert gas["A"] == pytest.approx(2 / 3, rel=1e-9) and gas["B"] == pytest.approx(1 / 3, rel=1e-9)
    # below the bubble point all condenses, above the dew point nothing
    assert flash({"A": 1.0}, {"A": 0.9}) == {"A": 0.0}
    assert flash({"A": 1.0, "B": 1.0}, {"A": 3.0, "B": 2.5}) == {"A": 1.0, "B": 1.0}


class _Curve:
    def __init__(self, kpa):
        self.value = kpa

    def covers(self, temperature):
        return True

    def kpa(self, temperature):
        return self.value


def test_a_partial_condenser_cools_all_of_the_vapour_as_liquid():
    # A 10 kg/h (200 kmol/h at 0.05) and B 10 kg/h (333.3 kmol/h at 0.03), K 5/20 = 0.25 and
    # 50/20 = 2.5: between bubble and dew point, so part of it passes to the pump. The duty is
    # the latent heat of what condenses and all 20 kg/h cooled 50 K as liquid at 2 kJ/(kg K)
    # (what passes re-evaporated at the same latent heat), not the condensate's cooling alone
    comps = {
        "A": N(vapour_pressure=_Curve(5.0), molar_mass=0.05),
        "B": N(vapour_pressure=_Curve(50.0), molar_mass=0.03),
    }
    spec = N(condenser=N(temperature=280.0, heat_capacity=2.0), pressure=20.0, temperature=330.0)
    latent = {"A": (800.0, "given"), "B": (900.0, "given")}
    found = condense_vapour(N(components=lambda: comps), spec, {"A": 10.0, "B": 10.0}, latent)
    condensed, gas = found["condensate_kg_h"], found["gas_kg_h"]
    assert 0 < sum(condensed.values()) < 20.0 and 0 < sum(gas.values()) < 20.0
    for n in ("A", "B"):
        assert condensed[n] + gas[n] == pytest.approx(10.0, rel=1e-12)
    assert found["cooling_kJ_h"] == pytest.approx(20.0 * 2.0 * 50.0, rel=1e-12)
    assert found["duty_kJ_h"] == pytest.approx(
        condensed["A"] * 800.0 + condensed["B"] * 900.0 + 2000.0, rel=1e-12
    )


DRYER_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: X_s, name: product crystals, formula: C4H4BrNO2, molar_mass: 177.98, phase: solid,
     vapour_pressure: {a: 1.0, b: 1000.0, provenance: assumed, source: "test value"}}
  - {id: X, name: product (dissolved or vapour), formula: C4H4BrNO2, molar_mass: 177.98}
  - {id: NaBr, name: sodium bromide (dissolved), formula: NaBr, molar_mass: 102.89}
  - {id: H2O, name: water, formula: H2O, molar_mass: 18.015,
     vapour_pressure: {a: 5.0, b: 1750.0, provenance: assumed, source: "test value"}}
templates:
  - {id: slurry, components: [X_s, X, NaBr, H2O]}
"""

DRYER = """\
schema: cheme/process/v1
kind: flowsheet
units: {temperature: K, pressure: kPa(a), flow: kg/h, duty: kW}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
  - {id: STEAM, category: utility, ports: [{id: out, direction: out, kind: energy}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: V, ports: [{id: in, direction: in}]}
  - {id: C, ports: [{id: in, direction: in}]}
  - {id: CW, category: utility, ports: [{id: in, direction: in, kind: energy}]}
  - {id: BR, category: utility, ports: [{id: in, direction: in, kind: energy}]}
blocks:
  - id: D1
    class: Drying
    ports:
      - {id: in, direction: in}
      - {id: product, direction: out}
      - {id: vapour, direction: out}
      - {id: condensate, direction: out}
      - {id: heat, direction: in, kind: energy}
      - {id: cw, direction: out, kind: energy}
      - {id: cond, direction: out, kind: energy}
    dryer:
      volatiles: [H2O]
      residual_moisture: {value: 0.002, basis: mass_fraction, provenance: assumed}
      temperature: 333.15
      pressure: 10.0
      energy:
        heat_capacity: 1.6
        latent_heat: {H2O: 2358.0}
        vessel_heat_capacity: 2000
        efficiency: 0.7
        port: heat
        provenance: assumed
      sublimation:
        components: {X_s: X}
        heat: {X_s: 500.0}
        provenance: assumed
      cooling:
        product_temperature: 303.15
        heat_capacity: 1.2
        vessel_temperature: 288.15
        port: cw
        provenance: assumed
      condenser: {temperature: 283.15, heat_capacity: 4.2, port: cond, provenance: assumed}
      drying_time: {value: 4, provenance: assumed}
      outlets: {product: product, vapour: vapour, condensate: condensate}
streams:
  - id: S2
    from: F.out
    to: D1.in
    template: slurry
    state:
      design:
        temperature: {value: 278.15, provenance: given, source: test}
        flow: {value: 500, provenance: given, source: test}
        composition: {basis: mass_fraction, values: {X_s: 0.8, X: 0.0033333333333333335,
                      NaBr: 0.013333333333333334, H2O: 0.18333333333333332},
                      provenance: given, source: test}
  - id: S4
    from: D1.product
    to: P.in
    template: slurry
  - id: S5
    from: D1.vapour
    to: V.in
    template: slurry
  - id: S6
    from: D1.condensate
    to: C.in
    template: slurry
  - id: Q1
    kind: energy
    from: STEAM.out
    to: D1.heat
  - id: Q2
    kind: energy
    from: D1.cw
    to: CW.in
    state: {design: {duty: {value: 1.0, provenance: assumed}}}
  - id: Q3
    kind: energy
    from: D1.cond
    to: BR.in
"""

HOURS = 5.0


def _dryer_recipe(product_kg_h):
    return {
        "schema": "cheme/recipe/v1",
        "kind": "recipe",
        "batch_size": {
            "value": product_kg_h * HOURS,
            "unit": "kg",
            "stream": "S4",
            "provenance": "assumed",
        },
        "hours_per_year": {"value": 8000, "provenance": "assumed"},
        "unit_procedures": [
            {
                "id": "DRY",
                "unit": "D1",
                "vessel": {"volume": 2.0, "provenance": "assumed"},
                "operations": [{"id": "dry", "kind": "dry", "from": "D1"}],
            }
        ],
    }


def test_sublimation_cooling_and_the_condenser_against_hand_calculations(tmp_path):
    # the cake: 400 X_s, 5/3 X, 20/3 NaBr, 275/3 H2O kg/h at 278.15 K; the dryer at 333.15 K
    # and 10 kPa(a). X_s sublimes at 10^(1 - 1000/333.15) bar = 0.996206 kPa, so each kmol of
    # vapour carries 0.996206 / (10 - 0.996206) kmol of it: sigma = 19.6926 kg per kmol.
    # The moisture is 0.002 of the product: kept = k (M0 - S), k = 0.002 / 0.998, M0 = 400 +
    # 5/3 + 20/3, S = sigma (W - kept) / 18.015; so kept = k (M0 - sigma W / 18.015) / (1 - k
    # sigma / 18.015)
    p_sub = 10 ** (1 - 1000 / 333.15) * 100
    assert p_sub == pytest.approx(0.996206, rel=1e-5)
    sigma = p_sub / (10 - p_sub) * 177.98
    water = 275 / 3
    m0 = 400 + 5 / 3 + 20 / 3
    k = 0.002 / 0.998
    kept = k * (m0 - sigma * water / 18.015) / (1 - k * sigma / 18.015)
    evaporated = water - kept
    sublimed = sigma * evaporated / 18.015
    product_kg_h = m0 - sublimed + kept
    ws = _plant(tmp_path, DRYER_MATERIALS, DRYER, _dryer_recipe(product_kg_h))
    process = _propagated(ws)
    product, vapour, condensate = (_mass(process, s) for s in ("S4", "S5", "S6"))
    assert product["X_s"] == pytest.approx(400 - sublimed, rel=1e-5)
    assert product["H2O"] == pytest.approx(kept, rel=1e-5)
    # the condenser: water alone at 283.15 K has 10^(5 - 1750/283.15) bar = 6.5998 kPa < 10:
    # all of it condenses, the sublimate passes on to the pump
    assert condensate["H2O"] == pytest.approx(evaporated, rel=1e-5)
    assert vapour.get("H2O", 0.0) == pytest.approx(0.0, abs=1e-9)
    assert vapour["X"] == pytest.approx(sublimed, rel=1e-5)
    # propagate writes the outlets' temperatures (cooling: and condenser: given)
    temperature = {s: _stream(process, s).state["design"].temperature for s in ("S4", "S5", "S6")}
    assert {s: q.value for s, q in temperature.items()} == {
        "S4": 303.15,
        "S5": 283.15,
        "S6": 283.15,
    }
    assert all(q.provenance == "calculated" for q in temperature.values())
    for b in balances(process, "design"):
        assert b.status == "ok", (b.node, b.failing)
    report = crystallizer_report(ws.root)
    (unit,) = report.units
    sol = unit["solution"]
    assert sol["sublimed"]["X_s"] == pytest.approx(sublimed, rel=1e-5)
    assert sol["batch_hours"] == pytest.approx(HOURS, rel=1e-5)
    # the heat: the cake 500 x 1.6 x 55, the water 2358, the sublimate 500 kJ/kg, the vessel
    # heated from where the cooling leaves it, 2000 x (333.15 - 288.15) / 5, over 0.7
    energy = sol["energy"]
    assert energy["sublimation_kJ_h"] == pytest.approx(sublimed * 500.0, rel=1e-5)
    assert energy["vessel_kJ_h"] == pytest.approx(2000 * 45.0 / HOURS, rel=1e-5)
    assert energy["duty_kW"] == pytest.approx(
        (500 * 1.6 * 55 + evaporated * 2358 + sublimed * 500 + 2000 * 45 / HOURS) / 0.7 / 3600,
        rel=1e-5,
    )
    # the cooling: the product to 303.15 K at 1.2, the vessel back to 288.15 K
    cooling = sol["cooling"]
    assert cooling["duty_kW"] == pytest.approx(
        (product_kg_h * 1.2 * 30 + 2000 * 45 / HOURS) / 3600, rel=1e-5
    )
    # the condenser: 2358 kJ/kg of what condenses, the water cooled 50 K at 4.2
    condenser = sol["condenser"]
    assert condenser["duty_kW"] == pytest.approx(
        (evaporated * 2358 + evaporated * 4.2 * 50) / 3600, rel=1e-5
    )
    # Q2 says 1 kW: the cooling's duty is compared, as the heating's
    assert any(d.startswith("Q2 duty: 1 kW written") for d in unit["duty_differences"])
    text = report_text(report)
    assert "sublimed" in text and "cooling" in text and "condenser at 283.15 K, 10 kPa(a)" in text
    (basis,) = model_bases(process)
    assert "sublimation of X_s" in basis.detail and "vacuum condenser" in basis.detail
    # the parts that set the outlets are assumed: not sourced, and the basis states the
    # temperatures propagate writes
    assert basis.sourced is False
    assert basis.detail.endswith("; not sourced: sublimation, cooling, condenser")
    assert "cooled after drying, the product to 303.15 K" in basis.detail
    assert not any("product and vapour leave at the drying" in a for a in basis.assumptions)
    assert (
        "the product leaves at its discharge temperature; the vapour and the condensate leave "
        "at the condenser's temperature; constant heat capacity of the cake"
    ) in basis.assumptions


def test_a_dryer_with_a_condenser_that_evaporates_nothing_writes_its_outlets(tmp_path):
    """core#309 with ADR 0076: a cake already at its residual moisture (0.1 of 500 kg/h)
    evaporates nothing; the vapour past the condenser and the condensate have no flow, each
    written at the inlet's volatile composition and the condenser's temperature (the
    condensate's composition was empty: a ValidationError in propagate). The cooling still
    cools the product. A cake without the volatiles stays a dryer finding."""
    fs = DRYER.replace(
        """values: {X_s: 0.8, X: 0.0033333333333333335,
                      NaBr: 0.013333333333333334, H2O: 0.18333333333333332}""",
        "values: {X_s: 0.9, H2O: 0.1}",
    ).replace("residual_moisture: {value: 0.002,", "residual_moisture: {value: 0.1,")
    assert "{X_s: 0.9, H2O: 0.1}" in fs and "{value: 0.1," in fs
    ws = _plant(tmp_path, DRYER_MATERIALS, fs)
    process = _propagated(ws)
    for stream in ("S5", "S6"):
        state = _stream(process, stream).state["design"]
        assert state.flow.value == 0.0
        assert state.composition.values == {"H2O": 1.0}
        assert state.temperature.value == 283.15
    product = _stream(process, "S4").state["design"]
    assert product.flow.value == pytest.approx(500.0) and product.temperature.value == 303.15
    (unit,) = crystallizer_report(ws.root).units
    sol = unit["solution"]
    assert sol["evaporated_kg_h"] == 0.0
    assert sol["condenser"]["duty_kW"] == pytest.approx(0.0, abs=1e-12)
    assert sol["cooling"]["duty_kW"] != 0.0
    dry = fs.replace("values: {X_s: 0.9, H2O: 0.1}", "values: {X_s: 1.0}")
    ws = _plant(tmp_path / "dry", DRYER_MATERIALS, dry)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert any("none of the volatiles" in f.message for f in result.findings)


def test_the_dryer_refuses_what_it_cannot_decide(tmp_path):
    with pytest.raises(ValueError, match="need the dryer's pressure"):
        Dryer(
            volatiles=["H2O"],
            residual_moisture={"value": 0.01, "basis": "mass_fraction", "provenance": "assumed"},
            temperature=333.15,
            condenser={"temperature": 283.15, "heat_capacity": 4.2, "provenance": "assumed"},
            outlets={"product": "p", "vapour": "v"},
        )
    with pytest.raises(ValueError, match="needs condenser"):
        Dryer(
            volatiles=["H2O"],
            residual_moisture={"value": 0.01, "basis": "mass_fraction", "provenance": "assumed"},
            temperature=333.15,
            outlets={"product": "p", "vapour": "v", "condensate": "c"},
        )
    # sublimation into a solid, a cooling port that is an inlet
    flowsheet = DRYER.replace("components: {X_s: X}", "components: {X_s: X_s}").replace(
        "      - {id: cw, direction: out, kind: energy}",
        "      - {id: cw, direction: in, kind: energy}",
    )
    ws = _plant(tmp_path, DRYER_MATERIALS, flowsheet)
    process, _ = load(ws.root)
    found = [f.message for f in rules(process) if f.rule == "cheme.process-dryer"]
    assert any("a solid component into a component that is not solid" in m for m in found)
    assert any("cooling.port cw is no energy outlet port" in m for m in found)
    # the sublimation pressure reaching the dryer's: refused
    ws = _plant(tmp_path / "b", DRYER_MATERIALS, DRYER.replace("pressure: 10.0", "pressure: 0.9"))
    (unit,) = crystallizer_report(ws.root).units
    assert "would sublime whole" in unit["problem"]


def test_a_plain_dryer_and_filter_dump_and_report_as_before():
    dryer = Dryer(
        volatiles=["H2O"],
        residual_moisture={"value": 0.01, "basis": "mass_fraction", "provenance": "assumed"},
        temperature=333.15,
        outlets={"product": "p", "vapour": "v"},
    )
    assert set(dryer.model_dump(mode="json")) == {
        "volatiles",
        "residual_moisture",
        "temperature",
        "energy",
        "drying_rate",
        "drying_time",
        "cake_density",
        "outlets",
    }
    sep = SolidSeparation(
        solid_recovery=1.0,
        cake_liquid={"value": 0.3, "basis": "per_kg_solid"},
        outlets={"cake": "c", "filtrate": "f"},
        provenance="assumed",
    )
    assert set(sep.model_dump(mode="json")) == {
        "solid_recovery",
        "cake_liquid",
        "outlets",
        "provenance",
        "source",
    }


def test_a_wash_solubility_may_be_carried_too(tmp_path):
    # the wash's 0.01 kg/kg given at 298.15 K and carried to 278.15 K with no heat of
    # solution: the same 0.3 kg/h dissolve, and the report says it is not measured there
    flowsheet = PRECIPITATION.replace(
        "solubility: {unit: kg/kg_solvent, value: 0.01, provenance: assumed}",
        "solubility: {unit: kg/kg_solvent, points: [[298.15, 0.01]], provenance: assumed, "
        "transfer: {heat_of_solution: 0, provenance: assumed}}",
    )
    ws = _plant(tmp_path, MATERIALS, flowsheet)
    _propagated(ws)
    report = crystallizer_report(ws.root)
    f1 = next(u for u in report.units if u["node"] == "F1")
    assert f1["solution"]["wash"]["dissolved_kg_h"] == pytest.approx(0.3, rel=1e-5)
    assert f1["solution"]["wash"]["solubility_transfer"]["from_temperature_K"] == 298.15
    found = [f for f in report.findings if f.rule == "cheme.process-crystallizer-transfer"]
    assert {f.ids[0] for f in found} == {"CR", "F1"}
