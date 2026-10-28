"""The solid/slurry contract and the crystallizer + filter adapter (pre-release issue 365).

Reference cases, each an independently published worked example (the textbook's own answer,
not a value computed with this code):

- Geankoplis, *Transport Processes and Separation Process Principles*, 4th ed. (2003), Example
  12.11-1: 10 000 kg of 30 wt% Na2CO3 cooled to 293 K, crystallizing Na2CO3.10H2O, solubility
  21.5 kg Na2CO3 / 100 kg water; (a) no evaporation: 6370 kg crystals, 3630 kg solution;
  (b) 3 % of the solution's mass evaporated: 6630 kg crystals, 3070 kg solution.
- Geankoplis, Example 12.11-2: 2268 kg at 327.6 K with 48.2 kg MgSO4 / 100 kg water cooled to
  293.2 K, MgSO4.7H2O, solubility 35.5 kg / 100 kg water, cp 2.93 kJ/(kg K), heat of
  crystallization 13.31e3 kJ/kmol / 246.49 = 54.0 kJ/kg released: q = -261 909 kJ. The book's
  crystal yield (616.9 kg) does not satisfy its own two balances (it gives a mother liquor of
  26.4 wt%, the solubility is 26.2 wt%); 633.7 kg does. So the yield is checked against the
  balances, and the energy balance against the book's q and its terms at the book's own yield
  (616.9 kg, imposed): at 633.7 kg the heat of crystallization term is 2.7 % larger.
- Felder & Rousseau, *Elementary Principles of Chemical Processes*, 3rd ed. (2005), Example
  4.5-2: 4500 kg/h of 1/3 K2CrO4 joined by the recycled filtrate (36.4 wt%, saturated),
  evaporated to 49.4 wt%, crystallized and filtered (crystals 95 % of the cake, the rest
  filtrate), all filtrate recycled: 2950 kg/h evaporated, 1470 kg/h crystals, 10 150 kg/h to
  the evaporator, 7200 kg/h to the crystallizer, recycle ratio 1.26.

Tolerance 0.5 %: the books round their mass fractions and answers to three or four digits
(12.11-1 (a) is 0.15 % from the exact balances); molar masses are IUPAC 2021
(chemistry.formulas), the books' differ in the fourth digit.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace as N

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.crystallization import (
    CrystallizationError,
    Slurry,
    Unsupported,
    crystal_form,
    crystallize,
    crystallizer_report,
    separate_solids,
    solubility_at,
    solve_train,
)
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.schema import Crystallizer, Solubility, Step
from chemeascode.domains.process.solids import slurry_basis
from chemeascode.foundation.workspace import Workspace

REL = 5e-3


def _evaporation(**kw):
    base = {"flow": None, "feed_fraction": None, "solvent_fraction": None, "concentration": None}
    return N(**(base | kw))


def _separation(value, basis="mass_fraction", recovery=1.0):
    return N(solid_recovery=recovery, cake_liquid=N(value=value, basis=basis))


# -- reference cases -----------------------------------------------------------------------------


def test_geankoplis_12_11_1_decahydrate_yield():
    form = crystal_form("Na2CO3", "H2O", "Na2CO3(H2O)10")
    assert form.hydrate == 10
    feed = Slurry(solute=3000.0, solvent=7000.0)
    a = solve_train(feed, form, solubility=0.215)
    assert a.crystals_formed == pytest.approx(6370.0, rel=REL)
    assert a.streams["slurry"].liquid == pytest.approx(3630.0, rel=REL)
    b = solve_train(feed, form, solubility=0.215, evaporation=_evaporation(feed_fraction=0.03))
    assert b.streams["vapour"].solvent == pytest.approx(300.0)
    assert b.crystals_formed == pytest.approx(6630.0, rel=REL)
    assert b.streams["slurry"].liquid == pytest.approx(3070.0, rel=REL)
    # the mother liquor leaves saturated
    liquor = b.streams["slurry"]
    assert liquor.solute / liquor.solvent == pytest.approx(0.215, rel=1e-9)
    for result in (a, b):
        for name in ("mass", "solute", "solvent"):
            assert abs(result.balances[name]["residual"]) < 1e-9
        for element in result.balances["elements_kmol_h"].values():
            assert abs(element["residual"]) < 1e-9


def test_geankoplis_12_11_2_heat_balance():
    form = crystal_form("MgSO4", "H2O", "MgSO4(H2O)7")
    total = 2268.0
    solute = total * 48.2 / 148.2
    energy = N(
        heat_capacity=2.93, heat_of_crystallization=-54.0, latent_heat=None, feed_temperature=327.6
    )
    result = solve_train(
        Slurry(solute, total - solute), form, solubility=0.355, energy=energy, temperature=293.2
    )
    # the yield from the book's two balances (its printed 616.9 kg does not satisfy them)
    liquor = result.streams["slurry"]
    assert liquor.solute + form.solute_fraction * liquor.crystal == pytest.approx(solute)
    assert liquor.solute / liquor.solvent == pytest.approx(0.355)
    assert result.crystals_formed == pytest.approx(633.7, rel=1e-3)
    sensible = -2268 * 2.93 * 34.4
    assert result.energy["sensible_kJ_h"] == pytest.approx(sensible, rel=1e-9)
    assert result.energy["duty_kJ_h"] == pytest.approx(
        sensible - 54.0 * result.crystals_formed, rel=1e-9
    )
    # the energy balance against the book at the book's own yield (616.9 kg imposed): its
    # terms, 228 596 kJ sensible and 616.9 x 54.0 = 33 313 kJ released, and q = -261 909 kJ
    book = solve_train(
        Slurry(solute, total - solute),
        form,
        solubility=0.355,
        imposed_yield=616.9 * form.solute_fraction / solute,
        energy=energy,
        temperature=293.2,
    )
    assert book.crystals_formed == pytest.approx(616.9, rel=1e-9)
    assert book.energy["crystallization_kJ_h"] == pytest.approx(-33_313.0, rel=1e-4)
    assert book.energy["duty_kJ_h"] == pytest.approx(-261_909.0, rel=1e-5)


def test_felder_4_5_2_evaporative_crystallizer_filter_and_recycle():
    form = crystal_form("K2CrO4", "H2O", "K2CrO4")
    assert form.hydrate == 0
    result = solve_train(
        Slurry(1500.0, 3000.0),
        form,
        solubility=solubility_at(
            Solubility(unit="mass_fraction", value=0.364, provenance="given"), None
        ),
        evaporation=_evaporation(concentration=0.494),
        separation=_separation(0.05),
        recycle=1.0,
    )
    s = result.streams
    assert s["vapour"].solvent == pytest.approx(2950.0, rel=REL)
    assert s["cake"].crystal == pytest.approx(1470.0, rel=REL)
    # the evaporator feed (fresh feed and recycle) and the crystallizer feed (after evaporation)
    assert s["combined_feed"].total == pytest.approx(10150.0, rel=REL)
    assert s["slurry"].total == pytest.approx(7200.0, rel=REL)
    assert s["recycle"].total / 4500.0 == pytest.approx(1.26, rel=REL)
    assert s["cake"].crystal / s["cake"].total == pytest.approx(0.95)
    assert s["mother_liquor"].total == 0.0
    # everything fed leaves as crystals, cake liquid and vapour
    for name in ("mass", "solute", "solvent"):
        assert abs(result.balances[name]["residual"]) < 1e-5
    assert result.product_recovery == pytest.approx(1.0, rel=1e-8)
    assert result.recovery == pytest.approx(1 - s["cake"].solute / 1500.0, rel=1e-8)


# -- the model's behaviour and its refusals -------------------------------------------------------


def test_imposed_yield_is_specified_and_checked_against_the_solubility():
    form = crystal_form("KNO3", "H2O", "KNO3")
    feed = Slurry(600.0, 400.0)  # 1.5 kg/kg
    equilibrium = crystallize(feed, form, solubility=0.5)
    assert equilibrium.slurry.crystal == pytest.approx(400.0)
    imposed = solve_train(feed, form, solubility=0.5, imposed_yield=0.5)
    assert imposed.basis == "yield" and imposed.crystals_formed == pytest.approx(300.0)
    assert imposed.equilibrium_crystals == pytest.approx(400.0) and not imposed.notes
    beyond = solve_train(feed, form, solubility=0.5, imposed_yield=0.9)
    assert any("below its solubility" in n for n in beyond.notes)


def test_undersaturated_feed_gives_no_crystals_and_an_endless_recycle_is_refused():
    form = crystal_form("KNO3", "H2O", "KNO3")
    result = solve_train(Slurry(100.0, 900.0), form, solubility=0.5)
    assert result.crystals_formed == 0.0 and result.undersaturated
    with pytest.raises(CrystallizationError, match="without bound"):
        solve_train(
            Slurry(100.0, 900.0),
            form,
            solubility=0.5,
            separation=_separation(0.1),
            recycle=1.0,
        )


def test_solubility_points_are_interpolated_never_extrapolated():
    spec = Solubility(
        unit="kg/kg_solvent", points=[(273.15, 0.2), (293.15, 0.4)], provenance="given"
    )
    assert solubility_at(spec, 283.15) == pytest.approx(0.3)
    with pytest.raises(Unsupported, match="no extrapolation"):
        solubility_at(spec, 300.0)
    w = Solubility(unit="mass_fraction", value=0.2, provenance="given")
    assert solubility_at(w, None) == pytest.approx(0.25)


def test_crystal_formulas_and_cake_liquid_are_checked():
    with pytest.raises(CrystallizationError, match="not the solute"):
        crystal_form("Na2CO3", "H2O", "NaHCO3")
    with pytest.raises(CrystallizationError, match="no readable formula"):
        crystal_form("Na2CO3", "H2O", "")
    cake, filtrate = separate_solids(
        {"s": 100.0, "a": 30.0, "w": 70.0}, {"s"}, 0.9, N(value=0.5, basis="per_kg_solid")
    )
    assert cake == pytest.approx({"s": 90.0, "a": 13.5, "w": 31.5})
    assert filtrate == pytest.approx({"s": 10.0, "a": 16.5, "w": 38.5})
    with pytest.raises(CrystallizationError, match="cake holds"):
        separate_solids({"s": 100.0, "w": 10.0}, {"s"}, 1.0, N(value=0.5, basis="mass_fraction"))


def _spec(**kw):
    base = {
        "solute": "K",
        "solvent": "W",
        "crystal": "Ks",
        "basis": "solubility",
        "solubility": {"unit": "mass_fraction", "value": 0.364, "provenance": "given"},
        "outlets": {"slurry": "out"},
    }
    return base | kw


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"solubility": None}, "needs solubility"),
        ({"basis": "yield"}, "needs yield"),
        ({"recycle": {"fraction": 0.5, "provenance": "assumed"}}, "needs separation"),
        ({"outlets": {"cake": "a", "mother_liquor": "b"}}, "exactly slurry"),
        (
            {"evaporation": {"flow": 1, "concentration": 0.4, "provenance": "assumed"}},
            "one of flow",
        ),
        (
            {
                "solubility": {
                    "unit": "mass_fraction",
                    "points": [[300, 0.3]],
                    "provenance": "given",
                }
            },
            "temperature",
        ),
        ({"crystal": "K"}, "three different"),
    ],
)
def test_crystallizer_schema_refusals(change, message):
    with pytest.raises(ValueError, match=message):
        Crystallizer.model_validate(_spec(**change))


def test_crystallizer_and_solid_separation_are_exclusive():
    with pytest.raises(ValueError, match="not both"):
        Step.model_validate(
            {
                "id": "X",
                "block": "B",
                "crystallizer": _spec(),
                "solid_separation": {
                    "solid_recovery": 1,
                    "cake_liquid": {"value": 0.1, "basis": "mass_fraction"},
                    "outlets": {"cake": "a", "filtrate": "b"},
                    "provenance": "assumed",
                },
            }
        )


# -- in a plant repository ------------------------------------------------------------------------

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: K2CrO4, name: potassium chromate (dissolved), formula: K2CrO4, molar_mass: 194.19}
  - {id: K2CrO4_s, name: potassium chromate crystals, formula: K2CrO4, molar_mass: 194.19,
     phase: solid}
  - {id: H2O, name: water, formula: H2O, molar_mass: 18.015}
  - {id: NaCl, name: sodium chloride, formula: NaCl, molar_mass: 58.44}
templates:
  - {id: slurry, components: [K2CrO4, K2CrO4_s, H2O]}
"""

FELDER = "Felder & Rousseau, Elementary Principles of Chemical Processes, 3rd ed., Example 4.5-2"

FLOWSHEET = f"""\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {{id: F, ports: [{{id: out, direction: out}}]}}
products:
  - {{id: V, ports: [{{id: in, direction: in}}]}}
  - {{id: P, ports: [{{id: in, direction: in}}]}}
  - {{id: ML, ports: [{{id: in, direction: in}}]}}
blocks:
  - id: CR
    class: Crystallizing
    ports:
      - {{id: in, direction: in}}
      - {{id: vap, direction: out}}
      - {{id: cake, direction: out}}
      - {{id: purge, direction: out}}
    crystallizer:
      solute: K2CrO4
      solvent: H2O
      crystal: K2CrO4_s
      basis: solubility
      solubility: {{unit: mass_fraction, value: 0.364, provenance: given, source: "{FELDER}"}}
      evaporation: {{concentration: 0.494, provenance: given, source: "{FELDER}"}}
      separation:
        solid_recovery: 1.0
        cake_liquid: {{value: 0.05, basis: mass_fraction}}
        provenance: given
        source: "{FELDER}"
      recycle: {{fraction: 1.0, provenance: given, source: "{FELDER}"}}
      outlets: {{vapour: vap, cake: cake, mother_liquor: purge}}
streams:
  - id: S1
    from: F.out
    to: CR.in
    template: slurry
    state:
      design:
        temperature: {{value: 300, provenance: given}}
        flow: {{value: 4500, provenance: given, source: "{FELDER}"}}
        composition: {{basis: mass_fraction, values: {{K2CrO4: 0.333333, H2O: 0.666667}},
                      provenance: given, source: "{FELDER}"}}
  - id: S2
    from: CR.vap
    to: V.in
    template: slurry
  - id: S3
    from: CR.cake
    to: P.in
    template: slurry
  - id: S4
    from: CR.purge
    to: ML.in
    template: slurry
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, materials=MATERIALS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: crystallizer-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    return Workspace(root)


def _state(ws, index):
    doc = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return doc["streams"][index]["state"]["design"]


def test_propagate_fills_the_crystallizer_and_the_flowsheet_balances_on_elements(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    result = run(ws, process, "design", write=True)
    assert result.written == 3, [f.format() for f in result.findings]
    vapour, cake = _state(ws, 1), _state(ws, 2)
    assert vapour["flow"]["value"] == pytest.approx(2950.0, rel=REL)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level in ("error", "warning")]
    (balance,) = [b for b in balances(process, "design") if b.node == "CR"]
    assert balance.status == "ok", balance.failing
    # the cake as dry solid and moisture (the slurry contract)
    stream = next(s for s in process.flowsheet.streams if s.id == "S3")
    basis = slurry_basis(process, stream, "design")
    assert basis.solid == pytest.approx(1470.0, rel=REL)
    assert basis.moisture == pytest.approx(0.05, rel=1e-4)
    assert basis.liquid_composition["K2CrO4"] == pytest.approx(0.364, rel=1e-4)
    assert cake["composition"]["provenance"] == "calculated"
    (unit,) = model_bases(process)
    assert (unit.basis, unit.predictive, unit.sourced) == ("solubility-equilibrium", True, True)
    assert any("not part of a converged simulation" in t for t in unit.limitations)
    # a change of the solubility makes the propagated outlets stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("value: 0.364", "value: 0.36"))
    process, _ = load(ws.root)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_imposed_yield_is_a_specified_basis_and_unsourced_data_are_not_sourced(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "basis: solubility\n", "basis: yield\n      yield: {value: 0.5, provenance: assumed}\n"
    )
    ws = _plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    (unit,) = model_bases(process)
    assert (unit.basis, unit.predictive, unit.sourced) == ("imposed-yield", False, False)
    assert "not sourced: yield" in unit.detail
    run(ws, process, "design", write=True)
    report = crystallizer_report(ws.root)
    (entry,) = report.units
    assert entry["solution"]["basis"] == "yield"
    assert entry["solution"]["equilibrium_crystals_kg_h"] is not None


def test_report_and_cli(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path)
    report = crystallizer_report(ws.root)
    (entry,) = report.units
    assert entry["basis"] == "solubility-equilibrium" and entry["problem"] is None
    assert entry["solution"]["recovery"] == pytest.approx(0.9812, rel=1e-3)
    # outlets not written yet: nothing to compare
    assert entry["differences"] == []
    monkeypatch.chdir(ws.root)
    out = CliRunner().invoke(app, ["process", "crystallizers"])
    text = re.sub(r"\x1b\[[0-9;]*m", "", out.output)
    assert out.exit_code == 0, text
    assert "basis solubility-equilibrium (predictive, sourced)" in text
    assert "moisture 0.05" in text
    data = json.loads(CliRunner().invoke(app, ["process", "crystallizers", "--json"]).output)
    assert data["units"][0]["solution"]["crystals_formed_kg_h"] == pytest.approx(
        entry["solution"]["crystals_formed_kg_h"]
    )
    assert "process/flowsheet.yaml" in data["source"]["fingerprints"]


def test_written_outlets_that_disagree_are_reported(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "    to: V.in\n    template: slurry\n",
        "    to: V.in\n    template: slurry\n    state:\n      design:\n"
        "        flow: {value: 2000, provenance: given, source: plant data}\n"
        "        composition: {basis: mass_fraction, values: {H2O: 1.0}, provenance: given,"
        " source: plant data}\n",
    )
    ws = _plant(tmp_path, flowsheet)
    report = crystallizer_report(ws.root)
    assert report.loaded
    assert any(f.rule == "cheme.process-crystallizer-outlet" for f in report.findings)


def test_impurities_are_refused_as_unsupported(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    flowsheet = FLOWSHEET.replace(
        "values: {K2CrO4: 0.333333, H2O: 0.666667}",
        "values: {K2CrO4: 0.323333, H2O: 0.666667, NaCl: 0.01}",
    )
    ws = _plant(tmp_path, flowsheet)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=False)
    assert any(f.rule == "cheme.process-propagate-crystallizer" for f in result.findings)
    report = crystallizer_report(ws.root)
    (finding,) = [f for f in report.findings if f.rule == "cheme.process-crystallizer-unsupported"]
    assert "impurities" in finding.message and finding.line and finding.hint
    monkeypatch.chdir(ws.root)
    assert CliRunner().invoke(app, ["process", "crystallizers"]).exit_code == 1


def test_rules_name_file_line_rule_and_hint(tmp_path):
    materials = MATERIALS.replace("     phase: solid}", "     }")
    flowsheet = FLOWSHEET.replace(
        "solubility: {unit: mass_fraction, value: 0.364,",
        "temperature: 350\n      solubility: {unit: mass_fraction, points: [[273.15, 0.3], "
        "[323.15, 0.4]],",
    ).replace("mother_liquor: purge}", "mother_liquor: nowhere}")
    ws = _plant(tmp_path, flowsheet, materials)
    process, found = load(ws.root)
    assert not [f for f in found if f.level == "error"]
    findings = [f for f in rules(process) if f.rule == "cheme.process-crystallizer"]
    messages = " | ".join(f.message for f in findings)
    assert "must be a solid component" in messages
    assert "outside the solubility data" in messages
    assert "not outlet ports: nowhere" in messages
    assert all(f.file == "process/flowsheet.yaml" and f.line and f.hint for f in findings)


SLURRY_FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: L, ports: [{id: in, direction: in}]}
blocks:
  - id: FI
    class: Separating
    ports:
      - {id: in, direction: in}
      - {id: cake, direction: out}
      - {id: filtrate, direction: out}
    solid_separation:
      solid_recovery: 0.98
      cake_liquid: {value: 0.25, basis: per_kg_solid}
      outlets: {cake: cake, filtrate: filtrate}
      provenance: assumed
streams:
  - id: S1
    from: F.out
    to: FI.in
    template: slurry
    state:
      design:
        flow: {value: 1000, provenance: given, source: test}
        composition: {basis: mass_fraction, values: {K2CrO4_s: 0.4, K2CrO4: 0.2, H2O: 0.4},
                      provenance: given, source: test}
  - id: S2
    from: FI.cake
    to: P.in
    template: slurry
  - id: S3
    from: FI.filtrate
    to: L.in
    template: slurry
"""


def test_a_filter_on_its_own_is_a_specified_solid_split(tmp_path):
    ws = _plant(tmp_path, SLURRY_FLOWSHEET)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    run(ws, process, "design", write=True)
    process, _ = load(ws.root)
    streams = {s.id: s for s in process.flowsheet.streams}
    cake = slurry_basis(process, streams["S2"], "design")
    filtrate = slurry_basis(process, streams["S3"], "design")
    assert cake.solid == pytest.approx(392.0, rel=1e-5)
    assert cake.liquid_per_solid == pytest.approx(0.25, rel=1e-5)
    assert filtrate.solid == pytest.approx(8.0, rel=1e-4)
    assert filtrate.liquid_composition["K2CrO4"] == pytest.approx(1 / 3, rel=1e-5)
    (balance,) = [b for b in balances(process, "design") if b.node == "FI"]
    assert balance.status == "ok", balance.failing
    (unit,) = model_bases(process)
    assert (unit.basis, unit.predictive, unit.sourced) == ("solid-split", False, False)


def test_solid_components_are_never_flashed_or_simulated_as_fluids(tmp_path):
    """A stream holding a phase: solid component is refused by the property routes (props
    --fill) and by the simulation translation, not treated as a fluid."""
    import shutil
    from pathlib import Path

    from chemeascode.domains.process.props import gather
    from chemeascode.domains.process.simulation.translate import load as load_sim
    from chemeascode.domains.process.simulation.translate import translate

    root = tmp_path / "plant"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples/process-simulation", root)
    process, _ = load(root)
    feed = next(s for s in process.flowsheet.streams if s.id == "S1")
    assert gather(process, feed, "design").inputs is not None
    sim, doc, _ = load_sim(root)
    assert translate(process, sim, doc, "design").model is not None
    materials = root / "process/materials.yaml"
    materials.write_text(
        materials.read_text().replace("normal_boiling_point: 87.30}", "phase: solid}")
    )
    process, _ = load(root)
    feed = next(s for s in process.flowsheet.streams if s.id == "S1")
    gathered = gather(process, feed, "design")
    assert gathered.inputs is None
    ((rule, message),) = gathered.problems
    assert rule == "property-unsupported" and "solid AR" in message
    found = translate(process, sim, doc, "design")
    assert found.model is None
    (solid,) = [f for f in found.findings if f.rule == "cheme.process-sim-solid"]
    assert solid.level == "error" and solid.hint and "AR" in solid.message
