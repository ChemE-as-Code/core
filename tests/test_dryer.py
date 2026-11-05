"""The filter-dryer (ADR 0057): a dryer step to a residual moisture with its energy duty, the
drying time from a drying rate and the heated area of the recipe's vessel, the filtration time
(Ruth) and a recipe unit procedure that spans several steps in one vessel.

Every expected value is a hand calculation from the inputs (the closed forms of the module
docstring of :mod:`chemeascode.domains.process.dryer`), not a value computed with the code:

- the cake of a filter with complete recovery and 0.25 kg liquid per kg solid from 1000 kg/h of
  40 wt% crystals, 1 wt% dissolved product, 4 wt% NaBr and 55 wt% water: 400 kg/h crystals and
  1/6 of the liquor (100 kg/h);
- dried to 0.2 wt% water: the non-volatile M = 400 + 10/6 + 40/6 kg/h, the water kept
  0.002 / 0.998 M, the rest evaporated;
- the duty (m cp dT + W lambda + C_v dT / h) / eta.

Latent heats from critical constants (Pitzer's corresponding states, Poling, Prausnitz and
O'Connell, *The Properties of Gases and Liquids*, 5th ed. (2001), eq. 7-9.4) are checked
against measured heats of vaporization at the normal boiling point: water 40.65 kJ/mol, benzene
30.72 kJ/mol (NIST Chemistry WebBook), critical constants from the same book's Appendix A.
"""

from __future__ import annotations

import copy
import json
import math
from types import SimpleNamespace as N

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.crystallization import crystallizer_report, report_text
from chemeascode.domains.process.dryer import (
    DryerError,
    dry_mass,
    pitzer_latent_heat,
    ruth_hours,
)
from chemeascode.domains.process.model import balances, load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import (
    Recipe,
    UnitProcedure,
    Vessel,
    recipe_report,
    recipe_text,
    wetted_area,
)
from chemeascode.domains.process.schema import Dryer, SolidSeparation, Step
from chemeascode.foundation.workspace import Workspace

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: X_s, name: product crystals, formula: C4H4BrNO2, molar_mass: 177.98, phase: solid}
  - {id: X, name: product (dissolved), formula: C4H4BrNO2, molar_mass: 177.98}
  - {id: NaBr, name: sodium bromide (dissolved), formula: NaBr, molar_mass: 102.89}
  - {id: H2O, name: water, formula: H2O, molar_mass: 18.015, liquid_molar_volume: 0.018015,
     critical: {Tc: 647.14, Pc: 22064, omega: 0.344, source: "Poling et al. 2001, App. A"}}
templates:
  - {id: slurry, components: [X_s, X, NaBr, H2O]}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {temperature: K, pressure: kPa(a), flow: kg/h, duty: kW}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
  - {id: STEAM, category: utility, ports: [{id: out, direction: out, kind: energy}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
  - {id: L, ports: [{id: in, direction: in}]}
  - {id: V, ports: [{id: in, direction: in}]}
blocks:
  - id: ISO
    ports:
      - {id: in, direction: in}
      - {id: filtrate, direction: out}
      - {id: product, direction: out}
      - {id: vapour, direction: out}
      - {id: heat, direction: in, kind: energy}
steps:
  - id: F1
    block: ISO
    class: Filtering
    ports:
      - {id: in, direction: in, delegates: in}
      - {id: cake, direction: out}
      - {id: filtrate, direction: out, delegates: filtrate}
    solid_separation:
      solid_recovery: 1.0
      cake_liquid: {value: 0.25, basis: per_kg_solid}
      outlets: {cake: cake, filtrate: filtrate}
      provenance: assumed
      filtration:
        specific_cake_resistance: 1.0e+9
        medium_resistance: 1.0e+10
        pressure_difference: 100
        viscosity: 1.0
        filtrate_density: 1000
        provenance: assumed
  - id: D1
    block: ISO
    class: Drying
    ports:
      - {id: in, direction: in}
      - {id: product, direction: out, delegates: product}
      - {id: vapour, direction: out, delegates: vapour}
      - {id: heat, direction: in, kind: energy, delegates: heat}
    dryer:
      volatiles: [H2O]
      residual_moisture: {value: 0.002, basis: mass_fraction, provenance: assumed}
      temperature: 333.15
      energy:
        heat_capacity: 1.6
        latent_heat: {H2O: 2358.0}
        vessel_heat_capacity: 2000
        efficiency: 0.7
        port: heat
        provenance: assumed
      drying_rate: {value: 5.0, provenance: assumed}
      cake_density: {value: 1250, provenance: assumed}
      outlets: {product: product, vapour: vapour}
streams:
  - id: S1
    from: F.out
    to: F1.in
    template: slurry
    state:
      design:
        temperature: {value: 278.15, provenance: given, source: test}
        flow: {value: 1000, provenance: given, source: test}
        composition: {basis: mass_fraction, values: {X_s: 0.40, X: 0.01, NaBr: 0.04, H2O: 0.55},
                      provenance: given, source: test}
  - id: S2
    from: F1.cake
    to: D1.in
    template: slurry
    state:
      design:
        temperature: {value: 278.15, provenance: given, source: test}
  - id: S3
    from: F1.filtrate
    to: L.in
    template: slurry
  - id: S4
    from: D1.product
    to: P.in
    template: slurry
  - id: S5
    from: D1.vapour
    to: V.in
    template: slurry
  - id: Q1
    kind: energy
    from: STEAM.out
    to: D1.heat
    state: {design: {duty: {value: 100.0, provenance: assumed}}}
"""

# hand calculation (module docstring)
CAKE = {"X_s": 400.0, "X": 10 / 6, "NaBr": 40 / 6, "H2O": 550 / 6}
SOLID = 400.0 + 10 / 6 + 40 / 6
KEPT = 0.002 / 0.998 * SOLID
VAPOUR = 550 / 6 - KEPT
HOURS = 5.0  # of flows per batch: the batch size is 5 h of the product's flow
DUTY = (500 * 1.6 * 55.0 + VAPOUR * 2358.0 + 2000 * 55.0 / HOURS) / 0.7 / 3600  # kW


def _hours(value, unit="h"):
    return {"value": value, "unit": unit, "provenance": "assumed"}


RECIPE = {
    "schema": "cheme/recipe/v1",
    "kind": "recipe",
    "batch_size": {
        "value": (SOLID + KEPT) * HOURS,
        "unit": "kg",
        "stream": "S4",
        "provenance": "assumed",
    },
    "hours_per_year": {"value": 8000, "provenance": "assumed"},
    "unit_procedures": [
        {
            "id": "ISOLATE",
            "units": ["F1", "D1"],
            "title": "Filter, wash and dry in one filter-dryer",
            "vessel": {"fill_fraction": 0.5, "provenance": "assumed"},
            "operations": [
                {"id": "filter", "kind": "filter", "from": "F1"},
                {"id": "wash", "kind": "other", "duration": _hours(1.0)},
                {"id": "dry", "kind": "dry", "from": "D1"},
                {"id": "discharge", "kind": "transfer", "duration": _hours(0.5)},
            ],
        }
    ],
}


def _plant(tmp_path, flowsheet=FLOWSHEET, recipe=RECIPE, propagate=True):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: dryer-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    if recipe is not None:
        (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    ws = Workspace(root)
    if propagate:
        process, found = load(root)
        assert process is not None, [f.format() for f in found]
        result = run(ws, process, "design", write=True)
        assert not [f for f in result.findings if f.level != "info"], [
            f.format() for f in result.findings
        ]
    return ws


def _streams(ws):
    from chemeascode.domains.process.model import stream_flows

    process, _ = load(ws.root)
    return {s.id: stream_flows(process, s, "design").components for s in process.flowsheet.streams}


# -- the dryer's mass and energy balance ----------------------------------------------------------


def test_dry_mass_closes_on_the_residual_moisture():
    moisture = N(value=0.002, basis="mass_fraction")
    product, vapour = dry_mass(CAKE, ["H2O"], moisture)
    assert product["H2O"] == pytest.approx(KEPT, rel=1e-12)
    assert vapour == {"H2O": pytest.approx(VAPOUR, rel=1e-12)}
    assert product["H2O"] / sum(product.values()) == pytest.approx(0.002, rel=1e-12)
    # the dissolved salt and product stay in the dried product
    assert product["NaBr"] == pytest.approx(40 / 6) and product["X"] == pytest.approx(10 / 6)
    assert sum(product.values()) + sum(vapour.values()) == pytest.approx(500.0, rel=1e-12)
    per_kg = N(value=0.01, basis="per_kg_solid")
    product, _ = dry_mass(CAKE, ["H2O"], per_kg)
    assert product["H2O"] == pytest.approx(0.01 * SOLID, rel=1e-12)
    with pytest.raises(DryerError, match="nothing to dry"):
        dry_mass(CAKE, ["H2O"], N(value=0.5, basis="per_kg_solid"))


def test_propagate_fills_the_dryer_and_the_report_closes_the_balance(tmp_path):
    ws = _plant(tmp_path)
    process, found = load(ws.root)
    assert not [f.format() for f in found + rules(process) if f.level == "error"]
    flows = _streams(ws)
    assert flows["S2"] == pytest.approx(CAKE, rel=1e-5)
    assert flows["S4"]["H2O"] == pytest.approx(KEPT, rel=1e-5)
    assert flows["S5"]["H2O"] == pytest.approx(VAPOUR, rel=1e-5)
    for node in ("F1", "D1", "ISO"):
        (balance,) = [b for b in balances(process, "design") if b.node == node]
        assert balance.status == "ok", (node, balance.failing)
    report = crystallizer_report(ws.root)
    (unit,) = [u for u in report.units if u["model"] == "dryer"]
    sol = unit["solution"]
    assert sol["evaporated_kg_h"] == pytest.approx(VAPOUR, rel=1e-5)
    assert sol["moisture_mass_fraction"] == pytest.approx(0.002, rel=1e-5)
    assert abs(sol["mass_residual_kg_h"]) < 1e-6
    assert sol["batch_hours"] == pytest.approx(HOURS, rel=1e-5)
    energy = sol["energy"]
    assert energy["sensible_kJ_h"] == pytest.approx(500 * 1.6 * 55.0, rel=1e-5)
    assert energy["evaporation_kJ_h"] == pytest.approx(VAPOUR * 2358.0, rel=1e-5)
    assert energy["vessel_kJ_h"] == pytest.approx(2000 * 55.0 / HOURS, rel=1e-5)
    assert energy["duty_kW"] == pytest.approx(DUTY, rel=1e-5)
    assert sol["per_batch"]["evaporated_kg"] == pytest.approx(VAPOUR * HOURS, rel=1e-5)
    # the heating stream Q1 says 100 kW, the model gives 111.2 kW: a duty finding of its own,
    # not an outlet's (propagate writes the outlets, never the energy stream)
    assert unit["differences"] == []
    (differ,) = unit["duty_differences"]
    assert differ.startswith("Q1 duty: 100 kW written")
    assert not any(f.rule == "cheme.process-crystallizer-outlet" for f in report.findings)
    (duty,) = [f for f in report.findings if f.rule == "cheme.process-dryer-duty"]
    assert duty.level == "warning" and "Q1 duty" in duty.message
    assert "write the model's duty on the heating stream" in duty.hint
    assert "dryer.energy" in duty.hint and "propagate" not in duty.hint
    # the product's moisture is the dryer's: the dissolved salt and product are dry solid
    product = unit["outlets"]["product"]
    assert product["moisture_mass_fraction"] == pytest.approx(
        sol["moisture_mass_fraction"], rel=1e-9
    )
    assert product["dry_solid_kg_h"] == pytest.approx(SOLID, rel=1e-5)
    assert product["liquid_kg_h"] == pytest.approx(KEPT, rel=1e-5)
    vapour = unit["outlets"]["vapour"]
    assert vapour["dry_solid_kg_h"] == 0 and vapour["liquid_kg_h"] == pytest.approx(
        VAPOUR, rel=1e-5
    )
    text = report_text(report)
    (line,) = [x for x in text.splitlines() if x.startswith("  product: ")]
    assert line.endswith("moisture 0.002")
    assert "dryer D1: basis residual-moisture" in text and "latent heat of H2O: 2358" in text
    (unit,) = [u for u in model_bases(process) if u.id == "D1"]
    assert (unit.basis, unit.predictive, unit.sourced) == ("residual-moisture", False, False)


def test_latent_heat_from_the_critical_constants_and_what_is_missing(tmp_path):
    water = N(Tc=647.14, omega=0.344)
    benzene = N(Tc=562.05, omega=0.210)
    assert pitzer_latent_heat(water, 18.015, 373.15) * 18.015 == pytest.approx(40650, rel=0.04)
    assert pitzer_latent_heat(benzene, 78.114, 353.2) * 78.114 == pytest.approx(30720, rel=0.03)
    with pytest.raises(DryerError, match="critical temperature"):
        pitzer_latent_heat(water, 18.015, 650.0)
    # without a declared latent heat the dryer takes Pitzer's from H2O's critical constants
    flowsheet = FLOWSHEET.replace("        latent_heat: {H2O: 2358.0}\n", "")
    ws = _plant(tmp_path, flowsheet)
    (unit,) = [u for u in crystallizer_report(ws.root).units if u["model"] == "dryer"]
    heat = unit["solution"]["latent_heat"]["H2O"]
    assert heat["kJ_kg"] == pytest.approx(pitzer_latent_heat(water, 18.015, 333.15), rel=1e-6)
    assert "Pitzer" in heat["basis"]
    # neither: the duty is missing, said so
    ws = _plant(tmp_path / "b", flowsheet)
    materials = (ws.root / "process/materials.yaml").read_text()
    (ws.root / "process/materials.yaml").write_text(
        materials.replace(
            ',\n     critical: {Tc: 647.14, Pc: 22064, omega: 0.344, source: "Poling et al. 2001, '
            'App. A"}',
            "",
        )
    )
    (unit,) = [u for u in crystallizer_report(ws.root).units if u["model"] == "dryer"]
    energy = unit["solution"]["energy"]
    assert energy["duty_kW"] is None and "latent_heat of H2O" in energy["missing"][0]


def test_dryer_rules(tmp_path):
    flowsheet = (
        FLOWSHEET.replace("volatiles: [H2O]", "volatiles: [H2O, X_s, MEOH]")
        .replace("port: heat\n", "port: product\n")
        .replace("latent_heat: {H2O: 2358.0}", "latent_heat: {H2O: 2358.0, WATER: 2358.0}")
    )
    ws = _plant(tmp_path, flowsheet, propagate=False)
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    messages = [f.message for f in rules(process) if f.rule == "cheme.process-dryer"]
    assert any("'MEOH' is not a component" in m for m in messages)
    assert any("X_s is a solid component" in m for m in messages)
    assert any("energy.port product is no energy inlet port" in m for m in messages)
    # a latent heat keyed by a component that is not a volatile (a typo) is an error
    (typo,) = [
        f for f in rules(process) if f.rule == "cheme.process-dryer" and "'WATER'" in f.message
    ]
    assert typo.level == "error" and "not one of its volatiles" in typo.message
    assert typo.line is not None and "volatiles' component ids" in typo.hint
    # the declared volatiles' latent heats raise nothing
    ws = _plant(tmp_path / "b", propagate=False)
    process, _ = load(ws.root)
    assert not [f for f in rules(process) if "latent_heat" in f.message]
    with pytest.raises(ValueError, match="product and vapour"):
        Dryer.model_validate(
            {
                "volatiles": ["H2O"],
                "temperature": 300,
                "outlets": {"product": "a"},
                "residual_moisture": {
                    "value": 0.01,
                    "basis": "mass_fraction",
                    "provenance": "assumed",
                },
            }
        )
    with pytest.raises(ValueError, match="one of crystallizer, solid_separation or dryer"):
        Step.model_validate(
            {
                "id": "X",
                "block": "B",
                "solid_separation": {
                    "solid_recovery": 1,
                    "cake_liquid": {"value": 0.1, "basis": "per_kg_solid"},
                    "provenance": "assumed",
                },
                "dryer": yaml.safe_load(FLOWSHEET.split("    dryer:\n")[1].split("streams:")[0]),
            }
        )


# -- the recipe: drying and filtration times, several steps in one vessel ------------------------


def test_drying_and_filtration_times_and_one_vessel_for_several_steps(tmp_path):
    ws = _plant(tmp_path)
    result = recipe_report(ws.root)
    # the batch is 5 h of flows and the cycle another time: only the basis check speaks
    assert {f.rule for f in result.findings} == {"cheme.recipe-basis"}
    # the vessel: 5 h of 500 kg/h of wet cake at 1250 kg/m3, half full, rounded up (R10)
    (vessel,) = result.vessels
    assert vessel.unit == "F1+D1"
    assert vessel.working_volume == pytest.approx(2.0, rel=1e-6)
    assert vessel.volume == pytest.approx(4.0)
    d = (16 / math.pi) ** (1 / 3)
    assert vessel.diameter == pytest.approx(d, rel=1e-9)
    area = wetted_area(2.0, d)
    assert area == pytest.approx(8 / d + math.pi * d**2 / 4, rel=1e-12)
    assert vessel.jacket_area == pytest.approx(area, rel=1e-6)
    times = {s.operation: s.end - s.start for s in result.steps}
    # drying: one batch's vapour over the rate times the heated area
    assert times["dry"] == pytest.approx(VAPOUR * HOURS / (5.0 * area), rel=1e-5)
    # filtration (Ruth): 2000 kg of solid, 500 kg/h x 5 h = 2.5 m3 of filtrate on the plate
    plate = math.pi * d**2 / 4
    seconds = 1e-3 * (1e9 * 2000 * 2.5 / (2 * plate**2) + 1e10 * 2.5 / plate) / 1e5
    assert times["filter"] == pytest.approx(seconds / 3600, rel=1e-5)
    # one vessel, one occupancy: the four operations in turn
    (unit,) = result.units
    total = times["filter"] + 1.0 + times["dry"] + 0.5
    assert unit.unit == "F1+D1" and unit.occupancy == pytest.approx(total, rel=1e-9)
    assert result.cycle_time == pytest.approx(total, rel=1e-9)
    assert {s.basis for s in result.steps if s.kind in ("dry", "filter")} == {"calculated"}
    assert "heated area" in recipe_text(result)


def test_the_vessel_holds_the_slurry_and_the_wash_not_only_the_cake(tmp_path):
    """A filter-dryer's vessel takes the slurry its filter takes in (5 h of 1000 kg/h at
    1000 kg/m3: 5 m3), larger than the dried cake's 2 m3: the slurry sizes it and fills a given
    vessel; the heated area stays the cake's wetted area."""
    ws = _plant(tmp_path)
    materials = (ws.root / "process/materials.yaml").read_text()
    # every component 1000 kg/m3 as a liquid: V = M / 1000 m3/kmol
    for name, molar_mass in (("X_s", "177.98"), ("X", "177.98"), ("NaBr", "102.89")):
        tag = f"{{id: {name}, "
        line = next(x for x in materials.splitlines() if tag in x)
        volume = float(molar_mass) / 1000
        materials = materials.replace(
            line,
            line.replace(
                f"molar_mass: {molar_mass}",
                f"molar_mass: {molar_mass}, liquid_molar_volume: {volume:g}",
            ),
        )
    (ws.root / "process/materials.yaml").write_text(materials)
    result = recipe_report(ws.root)
    (vessel,) = result.vessels
    assert vessel.working_volume == pytest.approx(5.0, rel=1e-6)
    assert vessel.volume == pytest.approx(10.0) and vessel.rounded
    assert vessel.fill == pytest.approx(0.5, rel=1e-6)
    d = (40 / math.pi) ** (1 / 3)
    assert vessel.diameter == pytest.approx(d, rel=1e-9)
    # the cake (2 m3 at its cake_density) sets the heated area, not the slurry
    assert vessel.jacket_area == pytest.approx(wetted_area(2.0, d), rel=1e-6)
    dry = next(s for s in result.steps if s.operation == "dry")
    assert dry.end - dry.start == pytest.approx(
        VAPOUR * HOURS / (5.0 * wetted_area(2.0, d)), rel=1e-5
    )
    # a given vessel that holds the cake (4 m3: half full) but not the slurry
    recipe = yaml.safe_load((ws.root / "process/recipe.yaml").read_text())
    recipe["unit_procedures"][0]["vessel"] |= {"volume": 4.0, "heated_area": 8.0}
    (ws.root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    result = recipe_report(ws.root)
    (over,) = [f for f in result.findings if f.rule == "cheme.recipe-vessel"]
    assert over.level == "warning" and "5 m3 of batch in the 4 m3 vessel" in over.message
    assert "125% full" in over.message


def test_a_given_volume_without_cake_density_says_what_is_missing(tmp_path):
    flowsheet = FLOWSHEET.replace("      cake_density: {value: 1250, provenance: assumed}\n", "")
    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][0]["vessel"] |= {"volume": 4.0}
    result = recipe_report(_plant(tmp_path, flowsheet, recipe).root)
    (failure,) = [f for f in result.findings if f.rule == "cheme.recipe-duration"]
    assert "no heated area: give vessel.heated_area (or jacket.area)" in failure.message
    assert "cake_density so the cake's wetted area can be calculated" in failure.message
    assert "or a volume" not in failure.message
    text = recipe_text(result)
    assert "batch volume not known, 4 m3, fill not known, D" in text and "0% full" not in text


def test_the_gantt_label_column_fits_a_units_list(tmp_path):
    from chemeascode.domains.process.recipe import gantt_svg

    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][0]["id"] = "ISOLATE_AND_DRY_THE_CRYSTALS"
    result = recipe_report(_plant(tmp_path, recipe=recipe).root)
    svg = gantt_svg(result)
    name = "ISOLATE_AND_DRY_THE_CRYSTALS (F1+D1)"
    x = float(svg.split(f">{name}</text>")[0].rsplit('x="', 1)[1].split('"')[0])
    # right-aligned at x: 11 px semibold capitals and digits are about 7 px a character
    assert x - 7 * len(name) >= 0
    # the bars and the axis keep their width
    (view,) = [part for part in svg.split('"') if part.startswith("0 0 ")]
    assert float(view.split()[2]) >= 760 + (x + 8 - 170) - 1
    # a short label keeps the old column
    short = gantt_svg(recipe_report(_plant(tmp_path / "b").root))
    assert 'x="162"' in short


def test_ruth_closed_form():
    filtration = N(
        specific_cake_resistance=2e10,
        medium_resistance=0.0,
        pressure_difference=200,
        viscosity=1.0,
    )
    # no medium resistance: t = mu alpha M V / (2 A^2 dP) = 1e-3 2e10 100 1 / (2 4 2e5) s
    assert ruth_hours(filtration, 100.0, 1.0, 2.0) * 3600 == pytest.approx(1250.0, rel=1e-12)


def test_a_given_drying_time_a_heated_area_and_the_references(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "drying_rate: {value: 5.0, provenance: assumed}",
        "drying_time: {value: 90, unit: min, provenance: assumed}",
    )
    result = recipe_report(_plant(tmp_path, flowsheet).root)
    assert {s.operation: s.end - s.start for s in result.steps}["dry"] == pytest.approx(1.5)
    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][0]["vessel"] |= {"volume": 6.3, "heated_area": 8.0}
    result = recipe_report(_plant(tmp_path / "b", recipe=recipe).root)
    (vessel,) = result.vessels
    assert vessel.volume == 6.3 and not vessel.rounded and vessel.jacket_area == 8.0
    dry = next(s for s in result.steps if s.operation == "dry")
    assert dry.end - dry.start == pytest.approx(VAPOUR * HOURS / (5.0 * 8.0), rel=1e-5)
    # a step in two vessels, a dry from a step that is no dryer, a filter without filtration
    recipe = copy.deepcopy(RECIPE)
    recipe["unit_procedures"][0]["operations"][2]["from"] = "F1"
    recipe["unit_procedures"].append(
        {"id": "AGAIN", "unit": "D1", "operations": [{"id": "f", "kind": "filter", "from": "D1"}]}
    )
    messages = [
        f.message for f in recipe_report(_plant(tmp_path / "c", recipe=recipe).root).findings
    ]
    assert any("D1 is in the vessel of ISOLATE already" in m for m in messages)
    assert any("F1 is no dryer" in m for m in messages)
    assert any("D1 is no solid_separation with filtration" in m for m in messages)
    with pytest.raises(ValueError, match="give unit or units"):
        UnitProcedure.model_validate(
            {
                "id": "U",
                "unit": "D1",
                "units": ["F1"],
                "operations": [{"id": "a", "kind": "hold", "duration": _hours(1)}],
            }
        )


def test_a_plain_recipe_and_a_plain_filter_dump_as_before():
    """Fingerprints (datasheets fill's recipe: input, propagate's outlets) read model dumps:
    the new optional fields leave them as they were."""
    up = UnitProcedure.model_validate(
        {
            "id": "U",
            "unit": "R",
            "operations": [{"id": "a", "kind": "hold", "duration": _hours(1)}],
            "vessel": {"provenance": "assumed"},
        }
    )
    dumped = up.model_dump(mode="json", by_alias=True)
    assert "units" not in dumped and "heated_area" not in dumped["vessel"]
    assert dumped["unit"] == "R"
    sep = SolidSeparation.model_validate(
        {
            "solid_recovery": 1,
            "cake_liquid": {"value": 0.1, "basis": "per_kg_solid"},
            "provenance": "assumed",
        }
    )
    assert "filtration" not in sep.model_dump(mode="json")
    step = Step.model_validate({"id": "S", "block": "B"})
    assert "dryer" not in step.model_dump(mode="json")
    assert "heated_area" not in Vessel.model_validate({"provenance": "assumed"}).model_dump()
    assert Recipe.model_validate(RECIPE).unit_procedures[0].label == "F1+D1"


def test_the_crystallizers_command_shows_the_dryer(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path)
    monkeypatch.chdir(ws.root)
    result = CliRunner().invoke(app, ["process", "crystallizers", "--json"])
    assert result.exit_code == 0, result.output
    units = json.loads(result.output)["units"]
    assert [u["model"] for u in units] == ["solid_separation", "dryer"]
