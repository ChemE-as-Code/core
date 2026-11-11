"""Precipitation from a mixed liquor (ADR 0056): spectator solutes in the crystallizer, the
solubility measured in that liquor or corrected by Setschenow salting-out coefficients, a
reslurry wash as a crystallizer fed by the cake and the wash, and phase changes kept out of
the reaction-hazard screening.

The closed forms are worked by hand in each test (the numbers written out), not taken from the
code: ``C = (S - s (W + P)) / a`` per kg of solute-free liquor, ``C = S - s W`` per kg of
solvent for an anhydrous crystal, and ``s = s0 10^(-sum k_i m_i)`` (Setschenow, molal scale).
"""

from __future__ import annotations

from types import SimpleNamespace as N

import pytest
import yaml

from chemeascode.domains.chemistry.reactions import Reaction, phase_change
from chemeascode.domains.process.crystallization import (
    CrystallizationError,
    Liquor,
    Slurry,
    crystal_form,
    crystallizer_report,
    report_text,
    solubility_at,
    solve_train,
)
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.schema import Crystallizer, Solubility
from chemeascode.domains.safety.reaction_hazards import screen
from chemeascode.foundation.workspace import Workspace

NACL = 58.44  # kg/kmol, as the Liquor below states it


def _separation(value, basis="per_kg_solid", recovery=1.0):
    return N(solid_recovery=recovery, cake_liquid=N(value=value, basis=basis))


# -- the model, against hand calculations --------------------------------------------------------


def test_spectators_pass_unchanged_and_the_liquor_leaves_saturated_per_kg_of_liquor():
    # 100 kg/h solute, 800 solvent, 100 NaCl; solubility 0.05 kg per kg of solute-free liquor
    # (solvent + NaCl): C = 100 - 0.05 (800 + 100) = 55 kg/h, the liquor 45 + 800 + 100
    form = crystal_form("C4H4BrNO2", "H2O", "C4H4BrNO2")
    feed = Slurry(solute=100.0, solvent=800.0, spectators={"NaCl": 100.0})
    liquor = Liquor(molar_mass={"NaCl": NACL}, atoms={"NaCl": {"Na": 1, "Cl": 1}}, basis="liquor")
    result = solve_train(feed, form, solubility=0.05, liquor=liquor)
    slurry = result.streams["slurry"]
    assert result.crystals_formed == pytest.approx(55.0, rel=1e-12)
    assert (slurry.solute, slurry.solvent) == pytest.approx((45.0, 800.0))
    assert slurry.spectators == pytest.approx({"NaCl": 100.0})
    # per kg of solvent alone it would be C = 100 - 0.05 x 800 = 60 kg/h
    per_solvent = solve_train(feed, form, solubility=0.05, liquor=Liquor(molar_mass={"NaCl": NACL}))
    assert per_solvent.crystals_formed == pytest.approx(60.0, rel=1e-12)
    for name in ("mass", "solute", "solvent"):
        assert abs(result.balances[name]["residual"]) < 1e-9
    assert result.balances["spectators"]["NaCl"]["residual"] == pytest.approx(0.0, abs=1e-12)
    for element in ("Na", "Cl", "Br", "N"):
        assert abs(result.balances["elements_kmol_h"][element]["residual"]) < 1e-12
    assert result.liquor["solubility_basis"] == "kg/kg_liquor"
    # the report's per-kg-solvent value is the mother liquor's: 45 / 800 = 0.05625, not the
    # declared 0.05 per kg of liquor (kept as declared_solubility)
    assert result.entry()["solubility_kg_per_kg_solvent"] == pytest.approx(45 / 800, rel=1e-12)
    assert result.liquor["declared_solubility"] == 0.05
    assert result.liquor["solubility"] == 0.05
    assert result.entry()["streams"]["slurry"]["spectators"] == {"NaCl": 100.0}
    # without spectators nothing of this appears in the report
    plain = solve_train(Slurry(100.0, 800.0), form, solubility=0.05).entry()
    assert plain["solubility_kg_per_kg_solvent"] == 0.05
    assert "mother_liquor" not in plain and "spectators" not in plain["streams"]["slurry"]
    assert "spectators" not in plain["balances"]


def test_a_mass_fraction_in_the_liquor_is_per_kg_of_solute_free_liquor():
    # x = 0.2 in the saturated liquor: 0.25 kg per kg of solute-free liquor
    sol = Solubility(
        unit="mass_fraction", value=0.2, measured_in="mother_liquor", provenance="given"
    )
    s = solubility_at(sol, None)
    assert s == pytest.approx(0.25)
    form = crystal_form("KCl", "H2O", "KCl")
    feed = Slurry(solute=500.0, solvent=1000.0, spectators={"NaCl": 200.0})
    result = solve_train(
        feed, form, solubility=s, liquor=Liquor(molar_mass={"NaCl": NACL}, basis="liquor")
    )
    # C = 500 - 0.25 (1000 + 200) = 200; the liquor: 300 / (300 + 1000 + 200) = 0.2
    assert result.crystals_formed == pytest.approx(200.0)
    assert result.liquor["solute_mass_fraction"] == pytest.approx(0.2)


def test_a_solubility_table_in_the_liquor_is_interpolated_and_never_extrapolated():
    sol = Solubility(
        unit="kg/kg_liquor",
        points=[(278.15, 0.010), (288.15, 0.016), (298.15, 0.030)],
        measured_in="mother_liquor",
        provenance="given",
        source="a table measured in the liquor",
    )
    # 283.15 K: halfway between 0.010 and 0.016; 293.15 K: halfway between 0.016 and 0.030
    assert solubility_at(sol, 283.15) == pytest.approx(0.013)
    assert solubility_at(sol, 293.15) == pytest.approx(0.023)
    assert solubility_at(sol, 278.15) == pytest.approx(0.010)
    with pytest.raises(CrystallizationError, match="no extrapolation"):
        solubility_at(sol, 300.0)
    with pytest.raises(ValueError, match="measured_in: mother_liquor"):
        Solubility(unit="kg/kg_liquor", value=0.1, provenance="given")


def test_setschenow_salting_out_against_a_hand_calculation():
    # 1 kmol/h NaCl (58.44 kg/h) in 1000 kg/h water: m = 1.000 mol/kg; k = 0.15 kg/mol;
    # s = 0.020 x 10^(-0.15) = 0.020 x 0.707946 = 0.0141589 kg/kg;
    # C = 50 - 0.0141589 x 1000 = 35.8411 kg/h (an anhydrous crystal)
    form = crystal_form("C4H4BrNO2", "H2O", "C4H4BrNO2")
    feed = Slurry(solute=50.0, solvent=1000.0, spectators={"NaCl": 58.44})
    liquor = Liquor(molar_mass={"NaCl": NACL}, salting_out={"NaCl": 0.15})
    result = solve_train(feed, form, solubility=0.020, liquor=liquor)
    assert result.liquor["solubility"] == pytest.approx(0.0141589, rel=1e-5)
    assert result.liquor["salting_out_factor"] == pytest.approx(0.707946, rel=1e-5)
    # reported per kg of solvent with the correction; the declared 0.020 kept apart
    entry = result.entry()
    assert entry["solubility_kg_per_kg_solvent"] == pytest.approx(0.0141589, rel=1e-5)
    slurry = result.streams["slurry"]
    assert entry["solubility_kg_per_kg_solvent"] == pytest.approx(
        slurry.solute / slurry.solvent, rel=1e-12
    )
    assert entry["mother_liquor"]["declared_solubility"] == 0.020
    assert result.liquor["molality_mol_per_kg_solvent"]["NaCl"] == pytest.approx(1.0)
    assert result.crystals_formed == pytest.approx(35.8411, rel=1e-5)
    # the same coefficient on the natural-log scale: k_ln = 0.15 ln 10 = 0.345388
    spec = _crystallizer_spec(
        salting_out={"coefficients": {"NaCl": 0.345388}, "log": "ln", "provenance": "assumed"}
    )
    from chemeascode.domains.process.crystallization import liquor_of

    process = N(components=lambda: {"NaCl": N(molar_mass=NACL, formula="NaCl")})
    ln_liquor = liquor_of(process, spec)
    assert ln_liquor.salting_out["NaCl"] == pytest.approx(0.15, rel=1e-6)


def test_setschenow_with_a_hydrate_takes_the_free_solvent_the_hydrate_leaves():
    # Na2CO3.10H2O from 3000 kg/h Na2CO3 in 7000 water with 584.4 kg/h NaCl (10 kmol/h);
    # k = 0.1 kg/mol: the liquor at the solution satisfies s = s0 10^(-k m) with m the NaCl
    # molality in the free water left, and S - aC = s (W - (1 - a) C)
    form = crystal_form("Na2CO3", "H2O", "Na2CO3(H2O)10")
    feed = Slurry(solute=3000.0, solvent=7000.0, spectators={"NaCl": 584.4})
    liquor = Liquor(molar_mass={"NaCl": NACL}, salting_out={"NaCl": 0.1})
    result = solve_train(feed, form, solubility=0.215, liquor=liquor)
    ml = result.streams["slurry"]
    m = 10_000.0 / ml.solvent
    assert ml.solute / ml.solvent == pytest.approx(0.215 * 10 ** (-0.1 * m), rel=1e-10)
    a = form.solute_fraction
    assert ml.solute + a * ml.crystal == pytest.approx(3000.0)
    assert ml.solvent + (1 - a) * ml.crystal == pytest.approx(7000.0)
    # salting out precipitates more than the 6370 kg/h of the salt-free case (Geankoplis)
    assert ml.crystal > solve_train(Slurry(3000.0, 7000.0), form, solubility=0.215).crystals_formed


def test_spectators_accumulate_in_the_recycle_and_leave_with_the_purge_and_the_cake():
    form = crystal_form("KCl", "H2O", "KCl")
    feed = Slurry(solute=300.0, solvent=1000.0, spectators={"NaCl": 20.0})
    liquor = Liquor(molar_mass={"NaCl": NACL}, basis="liquor")
    result = solve_train(
        feed,
        form,
        solubility=0.25,
        separation=_separation(0.1),
        recycle=0.8,
        liquor=liquor,
    )
    s = result.streams
    assert s["mother_liquor"].spectators["NaCl"] + s["cake"].spectators["NaCl"] == pytest.approx(
        20.0, rel=1e-9
    )
    assert s["combined_feed"].spectators["NaCl"] > 20.0
    assert abs(result.balances["mass"]["residual"]) < 1e-6


def test_a_reslurry_wash_dissolves_crystals_to_saturation():
    # a cake of 100 kg/h crystals with 30 kg/h liquor (1 solute, 25 water, 4 NaCl), reslurried
    # in 150 kg/h water at s = 0.0147 kg/kg water (no salting out): the liquid takes up
    # 0.0147 x 175 = 2.5725 kg/h, so 2.5725 - 1 = 1.5725 kg/h of crystals dissolve
    form = crystal_form("C4H4BrNO2", "H2O", "C4H4BrNO2")
    cake = Slurry(solute=1.0, solvent=25.0, crystal=100.0, spectators={"NaCl": 4.0})
    feed = cake + Slurry(solvent=150.0)
    liquor = Liquor(molar_mass={"NaCl": NACL}, salting_out={"NaCl": 0.0})
    result = solve_train(feed, form, solubility=0.0147, liquor=liquor)
    assert result.crystals_formed == pytest.approx(-1.5725, rel=1e-9)
    assert result.streams["slurry"].crystal == pytest.approx(98.4275, rel=1e-12)
    # so much water that every crystal dissolves: undersaturated
    flood = solve_train(cake + Slurry(solvent=10_000.0), form, solubility=0.0147, liquor=liquor)
    assert flood.undersaturated and flood.streams["slurry"].crystal == 0.0


def _crystallizer_spec(**solubility):
    return Crystallizer.model_validate(
        {
            "solute": "NBS",
            "solvent": "H2O",
            "crystal": "NBS_S",
            "basis": "solubility",
            "solubility": {"unit": "kg/kg_solvent", "value": 0.0147, "provenance": "assumed"}
            | solubility,
            "spectators": ["NaCl"],
            "outlets": {"slurry": "out"},
        }
    )


def test_the_schema_ties_salting_out_to_the_spectators():
    with pytest.raises(ValueError, match="one coefficient for each spectator"):
        _crystallizer_spec(salting_out={"coefficients": {"KCl": 0.1}, "provenance": "assumed"})
    with pytest.raises(ValueError, match="salting_out corrects pure-solvent data"):
        _crystallizer_spec(
            measured_in="mother_liquor",
            salting_out={"coefficients": {"NaCl": 0.1}, "provenance": "assumed"},
        )
    with pytest.raises(ValueError, match="spectators: each once"):
        Crystallizer.model_validate(
            _crystallizer_spec().model_dump(by_alias=True) | {"spectators": ["H2O"]}
        )


def test_a_single_solute_crystallizer_dumps_and_fingerprints_as_before():
    spec = Crystallizer.model_validate(
        {
            "solute": "A",
            "solvent": "H2O",
            "crystal": "A_s",
            "basis": "solubility",
            "solubility": {"unit": "kg/kg_solvent", "value": 0.1, "provenance": "given"},
            "outlets": {"slurry": "out"},
        }
    )
    dumped = spec.model_dump(mode="json")
    assert "spectators" not in dumped
    assert set(dumped["solubility"]) == {"unit", "points", "value", "provenance", "source"}
    reaction = Reaction.model_validate(
        {"id": "PPT", "stoichiometry": {"A": -1, "A_s": 1}, "kind": "phase-change"}
    )
    assert "kind" not in reaction.inputs_dump()
    assert (
        "kind"
        not in Reaction.model_validate({"id": "R", "stoichiometry": {"A": -1, "B": 1}}).model_dump()
    )


# -- in a plant repository: the NBS precipitation and reslurry wash, without reactions -----------

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

SALTING = (
    "salting_out: {coefficients: {NABR: 0.1, NAOH: 0.1}, provenance: assumed, source: test value}"
)

FLOWSHEET = f"""\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {{id: L, ports: [{{id: out, direction: out}}]}}
  - {{id: WW, ports: [{{id: out, direction: out}}]}}
products:
  - {{id: ML, ports: [{{id: in, direction: in}}]}}
  - {{id: WF, ports: [{{id: in, direction: in}}]}}
  - {{id: P, ports: [{{id: in, direction: in}}]}}
blocks:
  - id: CR
    class: Crystallizing
    ports: [{{id: in, direction: in}}, {{id: out, direction: out}}]
    crystallizer:
      solute: NBS
      solvent: H2O
      crystal: NBS_S
      basis: solubility
      temperature: 278.15
      solubility: {{unit: kg/kg_solvent, value: 0.0147, provenance: assumed,
                    source: "14.7 g NBS per kg water at 278 K (test value)", {SALTING}}}
      spectators: [NABR, NAOH]
      outlets: {{slurry: out}}
  - id: F1
    class: Filtering
    ports:
      - {{id: in, direction: in}}
      - {{id: cake, direction: out}}
      - {{id: filtrate, direction: out}}
    solid_separation:
      solid_recovery: 1.0
      cake_liquid: {{value: 0.3, basis: per_kg_solid}}
      outlets: {{cake: cake, filtrate: filtrate}}
      provenance: assumed
  - id: W
    class: Crystallizing
    ports:
      - {{id: cake, direction: in}}
      - {{id: wash, direction: in}}
      - {{id: out, direction: out}}
      - {{id: cake_out, direction: out}}
    crystallizer:
      solute: NBS
      solvent: H2O
      crystal: NBS_S
      basis: solubility
      temperature: 278.15
      solubility: {{unit: kg/kg_solvent, value: 0.0147, provenance: assumed,
                    source: "as CR", {SALTING}}}
      spectators: [NABR, NAOH]
      separation:
        solid_recovery: 1.0
        cake_liquid: {{value: 0.3, basis: per_kg_solid}}
        provenance: assumed
      outlets: {{cake: cake_out, mother_liquor: out}}
streams:
  - id: S1
    from: L.out
    to: CR.in
    template: liquor
    state:
      design:
        temperature: {{value: 278.15, provenance: given}}
        flow: {{value: 1000, provenance: given}}
        composition: {{basis: mass_fraction, values: {{NBS: 0.05, H2O: 0.918, NABR: 0.03,
                      NAOH: 0.002}}, provenance: given}}
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
    to: W.cake
    template: liquor
  - id: S5
    from: WW.out
    to: W.wash
    template: liquor
    state:
      design:
        temperature: {{value: 278.15, provenance: given}}
        flow: {{value: 60, provenance: given}}
        composition: {{basis: mass_fraction, values: {{H2O: 1.0}}, provenance: given}}
  - id: S6
    from: W.out
    to: WF.in
    template: liquor
  - id: S7
    from: W.cake_out
    to: P.in
    template: liquor
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, reactions=None, materials=MATERIALS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: precipitation-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    if reactions is not None:
        (root / "process/reactions.yaml").write_text(reactions)
    return Workspace(root)


def _mass(ws, stream_id):
    process, _ = load(ws.root)
    from chemeascode.domains.process.model import stream_flows

    stream = next(s for s in process.flowsheet.streams if s.id == stream_id)
    return stream_flows(process, stream, "design").components


def test_the_nbs_precipitation_and_reslurry_wash_propagate_and_balance(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert not [f.format() for f in result.findings if f.level == "error"]
    # CR by hand: m_NaBr = 30 / 102.894 x 1000 / 918 = 0.317613, m_NaOH = 2 / 39.997 x 1000
    # / 918 = 0.054471 mol/kg; s = 0.0147 x 10^(-0.1 x 0.372084) = 0.0134931 kg/kg;
    # C = 50 - 0.0134931 x 918 = 37.6133 kg/h
    m = 30 / 102.894 * 1000 / 918 + 2 / 39.997 * 1000 / 918
    s = 0.0147 * 10 ** (-0.1 * m)
    assert s == pytest.approx(0.0134931, rel=1e-5)
    slurry = _mass(ws, "S2")
    assert slurry["NBS_S"] == pytest.approx(50 - s * 918, rel=1e-5)
    assert slurry["NBS_S"] == pytest.approx(37.6133, rel=1e-5)
    assert (slurry["NABR"], slurry["NAOH"]) == pytest.approx((30.0, 2.0), rel=1e-5)
    # W: the cake (37.61 crystals with 0.3 kg/kg of saturated liquor) and 60 kg/h of water
    cake, wash_out, product = _mass(ws, "S4"), _mass(ws, "S6"), _mass(ws, "S7")
    assert product["NBS_S"] < cake["NBS_S"]  # some crystals dissolve in the wash
    assert wash_out["NABR"] + product["NABR"] == pytest.approx(cake["NABR"], rel=1e-5)
    water = wash_out["H2O"] + product["H2O"]
    m_w = (cake["NABR"] / 102.894 + cake["NAOH"] / 39.997) * 1000 / water
    s_w = 0.0147 * 10 ** (-0.1 * m_w)
    assert (wash_out["NBS"] + product["NBS"]) / water == pytest.approx(s_w, rel=1e-4)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level in ("error", "warning")]
    for b in balances(process, "design"):
        assert b.status == "ok", (b.node, b.failing)
    report = crystallizer_report(ws.root)
    assert report.loaded and not [f for f in report.findings if f.level == "error"]
    w = next(u for u in report.units if u["node"] == "W")
    assert w["solution"]["mother_liquor"]["spectators"] == ["NABR", "NAOH"]
    cr = next(u for u in report.units if u["node"] == "CR")
    assert cr["solution"]["solubility_kg_per_kg_solvent"] == pytest.approx(s, rel=1e-5)
    # the text output shows the liquor and its spectators, as the --json does
    text = report_text(report)
    assert "mother liquor: solubility 0.01349 kg/kg_solvent (declared 0.0147, salting-out" in text
    assert "spectators: NABR 0.3176 mol/kg, NAOH 0.05447 mol/kg; max residual" in text
    bases = {u.id: u for u in model_bases(process)}
    assert "spectators NABR, NAOH (pure-solvent solubility with Setschenow" in bases["CR"].detail
    assert any("spectator solutes stay dissolved" in a for a in bases["CR"].assumptions)


IN_THE_REACTOR = """\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: L, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: REACT
    class: ReactingChemicals
    ports: [{id: in, direction: in}, {id: out, direction: out}]
steps:
  - id: R1
    block: REACT
    class: ReactingChemicals
    reactions: [HYD]
    reactor: conversion
    ports: [{id: in, direction: in, delegates: in}, {id: out, direction: out}]
  - id: CR
    block: REACT
    class: Crystallizing
    ports: [{id: in, direction: in}, {id: out, direction: out, delegates: out}]
    crystallizer:
      solute: NBS
      solvent: H2O
      crystal: NBS_S
      basis: solubility
      temperature: 278.15
      solubility: {unit: kg/kg_solvent, value: 0.0147, provenance: assumed, source: test value,
                   salting_out: {coefficients: {NABR: 0.1, NAOH: 0.1, HBR: 0.0},
                                 provenance: assumed, source: test value}}
      spectators: [NABR, NAOH, HBR]
      outlets: {slurry: out}
streams:
  - id: S1
    from: L.out
    to: R1.in
    template: liquor
    state:
      design:
        temperature: {value: 278.15, provenance: given}
        flow: {value: 1000, provenance: given}
        composition: {basis: mass_fraction, values: {NBS: 0.05, H2O: 0.913, NABR: 0.03,
                      NAOH: 0.005, HBR: 0.002}, provenance: given}
  - id: S2
    from: R1.out
    to: CR.in
    template: liquor
  - id: S3
    from: CR.out
    to: P.in
    template: liquor
"""

NEUTRALISATION = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: HYD
    stoichiometry: {NAOH: -1, HBR: -1, NABR: 1, H2O: 1}
    phase: liquid
    conversion: {key: HBR, value: 1.0, provenance: assumed}
"""


def test_a_crystallizer_in_a_block_with_a_reaction_balances(tmp_path):
    # the precipitation in the reactor vessel: REACT holds the neutralisation R1 and the
    # crystallizer CR; the NBS -> NBS_S change is the crystallizer's, not a reaction's
    materials = MATERIALS.replace(
        "templates:",
        "  - {id: HBR, name: hydrogen bromide, formula: HBr, molar_mass: 80.912}\ntemplates:",
    ).replace("NABR, NAOH]}", "NABR, NAOH, HBR]}")
    ws = _plant(tmp_path, IN_THE_REACTOR, NEUTRALISATION, materials)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert not [f.format() for f in result.findings if f.level == "error"]
    process, found = load(ws.root)
    assert not [
        f.format()
        for f in found + rules(process)
        if f.level == "error" and f.rule == "cheme.process-balance"
    ]
    by_node = {b.node: b for b in balances(process, "design")}
    assert by_node["REACT"].status == "ok", by_node["REACT"].failing
    assert by_node["CR"].status == "ok", by_node["CR"].failing
    # 2 kg/h HBr (0.024718 kmol/h) neutralised; the crystallization is no reported extent
    assert by_node["REACT"].extents == pytest.approx({"HYD": 2 / 80.912}, rel=1e-4)
    assert _mass(ws, "S3")["NBS_S"] > 30.0


def test_a_pure_water_solubility_in_a_mixed_liquor_is_refused(tmp_path):
    flowsheet = FLOWSHEET.replace(f", {SALTING}", "", 1)
    ws = _plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    (finding,) = [
        f for f in rules(process) if f.rule == "cheme.process-crystallizer" and "CR" in f.ids
    ]
    assert finding.level == "error" and "pure solvent's" in finding.message
    assert finding.line and "measured_in: mother_liquor" in finding.hint
    report = crystallizer_report(ws.root)
    assert not report.loaded  # validate's error stops the report
    result = run(ws, process, "design", write=False)
    assert any(
        f.rule == "cheme.process-propagate-crystallizer" and "pure-solvent" in f.message
        for f in result.findings
    )
    (unit,) = [u for u in model_bases(process) if u.id == "CR"]
    assert not unit.sourced and "a solubility in the mixed liquor" in unit.detail


def test_an_undeclared_solute_is_still_refused(tmp_path):
    one = SALTING.replace("NABR: 0.1, NAOH: 0.1", "NABR: 0.1")
    flowsheet = FLOWSHEET.replace(SALTING, one, 1).replace(
        "spectators: [NABR, NAOH]", "spectators: [NABR]", 1
    )
    ws = _plant(tmp_path, flowsheet)
    process, found = load(ws.root)
    assert not [f.format() for f in found if f.level == "error"]
    result = run(ws, process, "design", write=False)
    (finding,) = [f for f in result.findings if f.rule == "cheme.process-propagate-crystallizer"]
    assert "NAOH" in finding.message and "spectators" in finding.message


# -- phase changes and the thermal screening -----------------------------------------------------

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: PPT
    equation: C4H4BrNO2(aq) -> C4H4BrNO2(s)
    stoichiometry: {NBS: -1, NBS_S: 1}
    phase: liquid
    conversion: {key: NBS, value: 0.9, provenance: assumed}
  - id: DISS
    stoichiometry: {NBS_S: -1, NBS: 1}
    phase: liquid
    kind: phase-change
    conversion: {key: NBS_S, value: 0.02, provenance: assumed}
  - id: HYD
    stoichiometry: {NAOH: -1, HBR: -1, NABR: 1, H2O: 1}
    phase: liquid
    conversion: {key: NAOH, value: 0.5, provenance: assumed}
"""

WORKAROUND = """\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: L, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: Q, ports: [{id: in, direction: in}]}
blocks:
  - id: CR101
    class: ReactingChemicals
    reactions: [PPT]
    reactor: conversion
    ports: [{id: in, direction: in}, {id: out, direction: out}]
  - id: R2
    class: ReactingChemicals
    reactions: [HYD, DISS]
    reactor: conversion
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: L.out
    to: CR101.in
    template: liquor
    state:
      design:
        temperature: {value: 278.15, provenance: given}
        flow: {value: 1000, provenance: given}
        composition: {basis: mass_fraction, values: {NBS: 0.05, H2O: 0.918, NABR: 0.03,
                      NAOH: 0.002}, provenance: given}
  - id: S2
    from: CR101.out
    to: R2.in
    template: liquor
  - id: S3
    from: R2.out
    to: Q.in
    template: liquor
"""


def test_phase_changes_are_declared_or_detected_by_their_formula():
    formulas = {"NBS": "C4H4BrNO2", "NBS_S": "C4H4BrNO2", "NAOH": "NaOH", "NABR": "NaBr"}
    by_id = {r["id"]: Reaction.model_validate(r) for r in yaml.safe_load(REACTIONS)["reactions"]}
    solids = {"NBS_S"}
    assert phase_change(by_id["PPT"], formulas, solids) == "same formula"
    assert phase_change(by_id["DISS"], formulas, solids) == "declared"
    assert phase_change(by_id["HYD"], formulas, solids) is None
    # the same formula without a solid is an isomerisation, a reaction
    assert phase_change(by_id["PPT"], formulas) is None
    hydrate = Reaction.model_validate(
        {"id": "H", "stoichiometry": {"CUSO4": -1, "H2O": -5, "CUSO4_5": 1}}
    )
    assert phase_change(hydrate, {"CUSO4": "CuSO4", "H2O": "H2O", "CUSO4_5": "CuSO4(H2O)5"}) is None


def test_the_hazard_screening_skips_a_phase_change_step(tmp_path):
    materials = MATERIALS.replace(
        "templates:",
        "  - {id: HBR, name: hydrogen bromide, formula: HBr, molar_mass: 80.912}\ntemplates:",
    ).replace("NABR, NAOH]}", "NABR, NAOH, HBR]}")
    ws = _plant(tmp_path, WORKAROUND, REACTIONS, materials)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    report = screen(ws.root)
    # CR101 holds only a phase change: not screened, an info finding instead
    assert [e.node for e in report.entries] == ["R2"]
    (skipped,) = report.phase_changes
    assert (skipped.node, skipped.reactions) == ("CR101", {"PPT": "same formula"})
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-phase-change"]
    assert finding.level == "info" and finding.ids == ["CR101"] and finding.line and finding.hint
    assert finding.id == "process/flowsheet.yaml#reactor-hazard-phase-change:CR101"
    assert not [f for f in report.findings if "CR101" in f.ids and f.rule != finding.rule]
    # R2 is screened on HYD alone, its phase change named
    (r2,) = report.entries
    assert any("phase changes not screened as reactions: DISS" in n for n in r2.notes)
    assert '"phase_changes"' in report.to_json()


# -- a single-solute crystallizer fingerprints as it did in core 1.7.0 ---------------------------

#: The outlet fingerprints of tests/test_crystallization.py's Felder 4.5-2 plant written by
#: core 1.7.0 (origin/main 5688bc2), basis solubility and basis yield.
FINGERPRINTS_1_7_0 = {"solubility": "b65e9ca59148f8d1", "yield": "e6a0c6c281ed19a8"}


@pytest.mark.parametrize("basis", ["solubility", "yield"])
def test_an_old_crystallizer_keeps_its_outlet_fingerprints(tmp_path, basis):
    from tests import test_crystallization as old

    flowsheet = old.FLOWSHEET
    if basis == "yield":
        flowsheet = flowsheet.replace(
            "basis: solubility\n", "basis: yield\n      yield: {value: 0.5, provenance: assumed}\n"
        )
    ws = old._plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    doc = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    for stream in doc["streams"][1:]:
        state = stream["state"]["design"]
        assert state["flow"]["fingerprint"] == FINGERPRINTS_1_7_0[basis], stream["id"]
        assert state["composition"]["fingerprint"] == FINGERPRINTS_1_7_0[basis], stream["id"]


CAUSTIC_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: NAOH_S, name: sodium hydroxide pellets, formula: NaOH, molar_mass: 39.997,
     phase: solid, liquid_heat_capacity: 80}
  - {id: NAOH, name: sodium hydroxide (dissolved), formula: NaOH, molar_mass: 39.997,
     liquid_heat_capacity: 80}
  - {id: H2O, name: water, formula: H2O, molar_mass: 18.015, liquid_heat_capacity: 75.3,
     normal_boiling_point: 373.15}
templates:
  - {id: caustic, components: [NAOH_S, NAOH, H2O]}
"""

CAUSTIC_FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: M1
    class: ReactingChemicals
    reactions: [DISSOLVE]
    reactor: conversion
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: M1.in
    template: caustic
    state:
      design:
        temperature: {value: 298.15, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 1000, provenance: given}
        composition: {basis: mass_fraction, values: {NAOH_S: 0.5, H2O: 0.5}, provenance: given}
  - id: S2
    from: M1.out
    to: P.in
    template: caustic
"""


def _caustic(heat: str, kind: str = "") -> str:
    return f"""\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - id: DISSOLVE
    stoichiometry: {{NAOH_S: -1, NAOH: 1}}
    phase: liquid
    conversion: {{key: NAOH_S, value: 1.0, provenance: assumed}}
{heat}{kind}"""


def test_an_exothermic_dissolution_detected_by_its_formula_is_still_screened(tmp_path):
    # NaOH pellets dissolving, -44500 kJ/kmol declared: no kind: phase-change, so the formula
    # heuristic must not drop it. 1000 kg/h at 50 wt%: 12.5009 kmol/h NaOH, 27.7546 kmol/h
    # water; dT_ad = 44500 x 12.5009 / (12.5009 x 80 + 27.7546 x 75.3) = 179.6 K, MTSR 477.7 K
    # above the MTT 373.15 K (water's boiling point)
    heat = "    heat_of_reaction: {value: -44500, provenance: given, source: test value}\n"
    ws = _plant(tmp_path, CAUSTIC_FLOWSHEET, _caustic(heat), CAUSTIC_MATERIALS)
    report = screen(ws.root)
    assert not report.phase_changes
    (entry,) = report.entries
    n, w = 500 / 39.997, 500 / 18.015
    rise = 44500 * n / (n * 80 + w * 75.3)
    assert entry.adiabatic_rise == pytest.approx(rise, rel=1e-6)
    assert entry.mtsr == pytest.approx(298.15 + rise, rel=1e-6)
    assert any("declared heat of reaction" in note and "DISSOLVE" in note for note in entry.notes)
    rules_found = {f.rule for f in report.findings}
    assert "cheme.reactor-hazard-mtsr" in rules_found
    assert "cheme.reactor-hazard-phase-change" not in rules_found
    # without a heat it is a phase change with no heat to run away
    ws = _plant(tmp_path / "noheat", CAUSTIC_FLOWSHEET, _caustic(""), CAUSTIC_MATERIALS)
    report = screen(ws.root)
    assert not report.entries
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-phase-change"]
    assert "no reaction heat declared" in finding.message
    # declared kind: phase-change with its heat: the author's choice, the message says so
    ws = _plant(
        tmp_path / "declared",
        CAUSTIC_FLOWSHEET,
        _caustic(heat, "    kind: phase-change\n"),
        CAUSTIC_MATERIALS,
    )
    report = screen(ws.root)
    assert not report.entries
    (finding,) = [f for f in report.findings if f.rule == "cheme.reactor-hazard-phase-change"]
    assert "no reaction heat" not in finding.message
    assert "DISSOLVE -44500 kJ/kmol" in finding.message
