"""Fixed-bed reactors (reactor: pfr): the bed model against analytic results, propagate,
the rules, the reactor report, the datasheet fill and the catalyst fill of the estimate."""

from __future__ import annotations

import math
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from chemeascode.domains.assessment.equipment_cost import equipment_estimate
from chemeascode.domains.chemistry.reactions import Reaction
from chemeascode.domains.chemistry.thermochemistry import IdealGas
from chemeascode.domains.equipment.fill import fill_datasheets
from chemeascode.domains.process.fixed_bed import BedError, solve_bed
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.schema import Bed
from chemeascode.project.datasheets import draft_missing

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
R = 8.314462618


def _first_order(A: float = 1e-6, **law) -> Reaction:
    rate = {
        "form": "power_law",
        "basis": "catalyst_mass",
        "driving": "partial_pressure",
        "k": {"A": A},
        "orders": {"A": 1},
        "provenance": "assumed",
    }
    return Reaction.model_validate(
        {"id": "R", "stoichiometry": {"A": -1, "B": 1}, "rate": rate | law}
    )


def _catalyst(**physical):
    base = {
        "bulk_density": 1000.0,
        "particle_diameter": None,
        "bed_voidage": None,
        "sphericity": None,
    }
    return SimpleNamespace(physical=SimpleNamespace(**(base | physical)))


GAS = {
    "A": IdealGas(dHf_298=0.0, S_298=200.0, cp_R=[4.0]),
    "B": IdealGas(dHf_298=-50000.0, S_298=200.0, cp_R=[4.0]),
}


def test_isothermal_first_order_against_the_analytic_solution():
    bed = Bed(catalyst_mass=1000, heat="isothermal", provenance="assumed")
    result = solve_bed(
        [_first_order()], {"A": 36.0}, 600, 500, bed, _catalyst(), {}, {"A": 30, "B": 30}
    )
    # dF_A/dW = -k y_A P/100 with F constant: F_A = F0 exp(-k P W / (100 F0))
    exact = 36.0 * math.exp(-1e-6 * 5 * 1000 / 0.01)
    assert result.outlet["A"] == pytest.approx(exact, rel=1e-9)
    assert result.extents["R"] == pytest.approx(36.0 - exact, rel=1e-9)
    assert result.temperature == 600 and result.pressure == 500
    assert len(result.profile) == 51 and result.profile[-1][0] == pytest.approx(1000)


def test_adiabatic_temperature_rise_closes_the_energy_balance():
    bed = Bed(catalyst_mass=1000, heat="adiabatic", provenance="assumed")
    result = solve_bed(
        [_first_order()], {"A": 36.0}, 600, 500, bed, _catalyst(), GAS, {"A": 30, "B": 30}
    )
    converted = 36.0 - result.outlet["A"]
    # constant cp: T rise = conversion x (-dHr) / (F cp)
    rise = converted * 50000.0 / (36.0 * 4.0 * R)
    assert result.temperature - 600 == pytest.approx(rise, rel=1e-6)
    assert result.hot_spot == pytest.approx(result.temperature)


def test_a_cooled_bed_stays_near_its_coolant():
    bed = Bed(
        catalyst_mass=1000,
        heat="cooled",
        diameter=0.05,
        coolant_temperature=600,
        heat_transfer_coefficient=500,
        provenance="assumed",
    )
    hot = solve_bed(
        [_first_order()],
        {"A": 36.0},
        600,
        500,
        Bed(catalyst_mass=1000, provenance="assumed"),
        _catalyst(),
        GAS,
        {"A": 30, "B": 30},
    )
    cooled = solve_bed(
        [_first_order()], {"A": 36.0}, 600, 500, bed, _catalyst(), GAS, {"A": 30, "B": 30}
    )
    assert abs(cooled.temperature - 600) < 0.1 * (hot.temperature - 600)


def test_ergun_pressure_drop_by_hand():
    # no reaction to speak of: the pressure drop of a gas through the bed
    bed = Bed(
        catalyst_mass=1000, diameter=1.0, heat="isothermal", viscosity=2e-5, provenance="assumed"
    )
    catalyst = _catalyst(particle_diameter=0.005, bed_voidage=0.4, sphericity=1.0)
    result = solve_bed(
        [_first_order(A=1e-30)], {"A": 360.0}, 600, 2000, bed, catalyst, {}, {"A": 30, "B": 30}
    )
    area = math.pi / 4
    flux = 0.1 * 30 / area  # kg/(m2 s)
    rho = 2000 * 30 / (R * 600)
    length = 1000 / (1000 * area)
    e, dp = 0.4, 0.005
    gradient = flux / (rho * dp) * (1 - e) / e**3 * (150 * (1 - e) * 2e-5 / dp + 1.75 * flux)
    expected = gradient * length / 1000  # kPa, at the inlet density (a small drop)
    assert result.pressure_drop == pytest.approx(expected, rel=0.01)
    assert not result.notes


def test_what_a_bed_needs():
    bed = Bed(catalyst_mass=1000, heat="adiabatic", provenance="assumed")
    no_rate = Reaction.model_validate({"id": "R", "stoichiometry": {"A": -1, "B": 1}})
    with pytest.raises(BedError, match="no rate law"):
        solve_bed([no_rate], {"A": 1.0}, 600, 500, bed, _catalyst(), GAS, {"A": 30, "B": 30})
    with pytest.raises(BedError, match="ideal_gas"):
        solve_bed([_first_order()], {"A": 1.0}, 600, 500, bed, _catalyst(), {}, {"A": 30, "B": 30})
    sized = Bed(volume=2.0, heat="isothermal", provenance="assumed")
    with pytest.raises(BedError, match="bulk density"):
        solve_bed(
            [_first_order()],
            {"A": 1.0},
            600,
            500,
            sized,
            _catalyst(bulk_density=None),
            {},
            {"A": 30, "B": 30},
        )
    cooled = Bed(catalyst_mass=1, heat="cooled", provenance="assumed")
    with pytest.raises(BedError, match="coolant"):
        solve_bed(
            [_first_order()], {"A": 1.0}, 600, 500, cooled, _catalyst(), GAS, {"A": 30, "B": 30}
        )


def test_a_bed_with_an_empty_feed_is_refused_not_divided_by_zero():
    """With Ergun data, a zero flow has no gas density to divide by."""
    bed = Bed(
        catalyst_mass=1000, diameter=1.0, heat="isothermal", viscosity=2e-5, provenance="assumed"
    )
    catalyst = _catalyst(particle_diameter=0.005, bed_voidage=0.4, sphericity=1.0)
    with pytest.raises(BedError, match="the feed is empty"):
        solve_bed([_first_order()], {"A": 0.0}, 600, 2000, bed, catalyst, {}, {"A": 30, "B": 30})


# -- the shift example --------------------------------------------------------------------------


@pytest.fixture
def shift(tmp_path):
    root = tmp_path / "shift"
    shutil.copytree(EXAMPLES / "process-shift", root, ignore=shutil.ignore_patterns("build"))
    return root


def _rules(root):
    process, found = load(root)
    assert process is not None, [f.format() for f in found]
    return found + rules(process)


def _outlet(root):
    data = yaml.safe_load((root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == "S2")["state"]["design"]


def test_the_example_is_propagated_and_clean(shift):
    assert not [f.format() for f in _rules(shift) if f.level != "info"]
    process, _ = load(shift)
    check = run(SimpleNamespace(root=shift), process, "design", write=False)
    assert not [f.format() for f in check.findings if f.level != "info"]
    out = _outlet(shift)
    assert out["temperature"]["provenance"] == "calculated"
    assert out["temperature"]["value"] == pytest.approx(704.4, abs=0.5)
    assert out["pressure"]["value"] < 3000
    report = reactor_report(shift)
    r1 = next(r for r in report.reactors if r["node"] == "R1")
    assert r1["model"] == "pfr"
    assert abs(r1["duty_kW"]) < 1.0  # adiabatic: H(out) = H(in)
    assert r1["reactions"][0]["ln_q_over_k"] == pytest.approx(0.0, abs=1e-3)  # at equilibrium
    bed = r1["bed"]
    assert bed["catalyst_mass_kg"] == 40000
    assert bed["catalyst_volume_m3"] == pytest.approx(40000 / 1130)
    assert bed["pressure_drop_kPa"] > 0 and len(bed["profile"]) == 51


def test_a_smaller_bed_makes_the_outlet_stale_and_converts_less(shift):
    path = shift / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("catalyst_mass: 40000", "catalyst_mass: 4000"))
    assert any(f.rule == "cheme.process-calculated-stale" for f in _rules(shift))
    process, _ = load(shift)
    run(SimpleNamespace(root=shift), process, "design", write=True)
    assert _outlet(shift)["temperature"]["value"] < 704.0
    r1 = next(r for r in reactor_report(shift).reactors if r["node"] == "R1")
    assert r1["reactions"][0]["ln_q_over_k"] < -0.1  # short of equilibrium


def test_pfr_rules(shift):
    path = shift / "process/flowsheet.yaml"
    text = path.read_text()
    path.write_text(text.replace("    catalyst: FE_CR\n", "", 1))
    assert any(
        f.rule == "cheme.process-reactor" and "no catalyst" in f.message for f in _rules(shift)
    )
    path.write_text(text.replace("    reactor: pfr\n", "    reactor: equilibrium\n"))
    found = [f for f in _rules(shift) if f.rule == "cheme.process-reactor"]
    assert any("bed is used by reactor: pfr only" in f.message for f in found)
    reactions = shift / "process/reactions.yaml"
    path.write_text(text)
    rx = reactions.read_text()
    reactions.write_text(rx[: rx.index("    rate:")] + rx[rx.index("    sources:") :])
    assert any(
        f.rule == "cheme.process-reactor" and "no rate law" in f.message for f in _rules(shift)
    )


# -- datasheet and estimate ---------------------------------------------------------------------


def test_reactor_datasheet_and_catalyst_fill(plant: Path):
    for name in ("materials", "reactions", "catalysts", "flowsheet"):
        shutil.copy(EXAMPLES / "process-shift" / "process" / f"{name}.yaml", plant / "process")
    path = plant / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "    catalyst: FE_CR\n",
            "    catalyst: FE_CR\n    links: [{target: equipment, ref: R-1}]\n",
            1,
        )
    )
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump(
            {
                "equipment": [
                    {
                        "tag": "R-1",
                        "type": "PressureVessel",
                        "dimensions": {"diameter": 3.0, "height": 6.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    draft_missing(plant)
    result = fill_datasheets(plant, ["R-1"])
    assert not [f.format() for f in result.findings if f.level == "error"]
    sheet = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())
    specific = sheet["type_specific"]
    assert specific["catalyst_mass_kg"]["value"] == 40000
    assert specific["catalyst_volume_m3"]["value"] == pytest.approx(35.4, rel=1e-3)
    # the draft took the vessel volume from the list's dimensions, which holds the bed
    assert specific["volume_m3"]["value"] == pytest.approx(math.pi / 4 * 9 * 6, rel=1e-3)
    assert not [f for f in result.findings if f.rule == "cheme.datasheet-reactor-volume"]
    assert specific["pressure_drop_kpa"]["value"] > 0
    assert abs(specific["duty_kw"]["value"]) < 1.0
    estimate = equipment_estimate(plant)
    fill = next(line for line in estimate.lines if line.tag == "R-1/catalyst")
    assert fill.purchased == pytest.approx(40000 * 12)
    assert fill.status == "catalyst price" and "not escalated" in fill.notes
    vessel = next(line for line in estimate.lines if line.tag == "R-1")
    assert vessel.correlation == "vessel_vertical"


def test_a_vessel_smaller_than_its_bed_is_a_finding(plant: Path):
    for name in ("materials", "reactions", "catalysts", "flowsheet"):
        shutil.copy(EXAMPLES / "process-shift" / "process" / f"{name}.yaml", plant / "process")
    path = plant / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace(
            "    catalyst: FE_CR\n",
            "    catalyst: FE_CR\n    links: [{target: equipment, ref: R-1}]\n",
            1,
        )
    )
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump(
            {
                "equipment": [
                    {
                        "tag": "R-1",
                        "type": "PressureVessel",
                        "dimensions": {"diameter": 2.0, "height": 6.0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    draft_missing(plant)
    result = fill_datasheets(plant, ["R-1"])
    assert any(f.rule == "cheme.datasheet-reactor-volume" for f in result.findings)


# -- review fixes -------------------------------------------------------------------------------


def _reactor_plant(plant: Path, item: dict, flowsheet_change=None) -> Path:
    for name in ("materials", "reactions", "catalysts", "flowsheet"):
        shutil.copy(EXAMPLES / "process-shift" / "process" / f"{name}.yaml", plant / "process")
    path = plant / "process/flowsheet.yaml"
    text = path.read_text().replace(
        "    catalyst: FE_CR\n",
        f"    catalyst: FE_CR\n    links: [{{target: equipment, ref: {item['tag']}}}]\n",
        1,
    )
    path.write_text(flowsheet_change(text) if flowsheet_change else text)
    (plant / "equipment" / "equipment-list.yaml").write_text(
        yaml.safe_dump({"equipment": [item]}), encoding="utf-8"
    )
    draft_missing(plant)
    return plant


def test_a_bed_that_cannot_be_evaluated_is_reported_not_raised(shift):
    reactions = shift / "process/reactions.yaml"
    # CH3OH has an inhibiting order, and the feed carries none: the rate is not defined
    text = reactions.read_text().replace("H2: -0.09}", "H2: -0.09, CH4: -1}")
    reactions.write_text(text)
    feed = shift / "process/flowsheet.yaml"
    feed.write_text(feed.read_text().replace("H2: 0.47, CH4: 0.03}", "H2: 0.50, CH4: 0.0}"))
    r1 = next(r for r in reactor_report(shift).reactors if r["node"] == "R1")
    assert r1["bed"] is None and any("CH4 is absent" in m for m in r1["missing"])


def test_the_vessel_volume_comes_from_the_bed_without_a_spurious_warning(plant: Path):
    _reactor_plant(
        plant,
        {"tag": "R-1", "type": "PressureVessel"},
        lambda t: t.replace("catalyst_mass: 40000", "catalyst_mass: 40001.7"),
    )
    result = fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    assert "catalyst bed's volume" in specific["volume_m3"]["source"]
    assert not [f for f in result.findings if f.rule == "cheme.datasheet-reactor-volume"]


def test_an_exchanger_linked_to_a_reactor_keeps_its_own_fill(plant: Path):
    _reactor_plant(plant, {"tag": "E-1", "type": "TubularHeatExchanger"})
    fill_datasheets(plant, ["E-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/E-1.yaml").read_text())[
        "type_specific"
    ]
    assert "catalyst_mass_kg" not in specific


def test_space_velocity_sizing_refuses_a_missing_molar_mass(plant: Path):
    _reactor_plant(
        plant,
        {"tag": "R-1", "type": "PressureVessel"},
        lambda t: t.replace("    reactor: pfr\n", "    reactor: equilibrium\n"),
    )
    materials = plant / "process/materials.yaml"
    materials.write_text(materials.read_text().replace("    molar_mass: 16.043\n", ""))
    result = fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    assert specific["catalyst_volume_m3"]["value"] == "TBD"
    assert "GHSV" in specific["catalyst_volume_m3"]["source"]  # refused, not raised
    assert not [f for f in result.findings if f.level == "error"]


def test_a_given_outlet_temperature_that_contradicts_the_bed(shift):
    path = shift / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["streams"][1]["state"] = {
        "design": {"temperature": {"value": 650.0, "provenance": "assumed"}}
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    process, _ = load(shift)
    result = run(SimpleNamespace(root=shift), process, "design", write=False)
    found = [f for f in result.findings if f.rule == "cheme.process-propagate-reactor"]
    assert found and "the bed gives 704" in found[0].message


def test_a_catalyst_price_does_not_make_the_bed_stale(shift):
    cats = shift / "process/catalysts.yaml"
    cats.write_text(cats.read_text().replace("value: 12, unit: USD/kg", "value: 20, unit: USD/kg"))
    assert not [f for f in _rules(shift) if f.rule == "cheme.process-calculated-stale"]


def test_the_viewer_estimate_has_the_catalyst_fill_too(plant: Path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    _reactor_plant(plant, {"tag": "R-1", "type": "PressureVessel"})
    fill_datasheets(plant, ["R-1"])
    payload = (
        TestClient(create_app(plant, allowed_hosts=["testserver"]))
        .get("/api/estimate/equipment")
        .json()
    )
    fill = next(line for line in payload["lines"] if line["tag"] == "R-1/catalyst")
    assert fill["purchased"] == pytest.approx(40000 * 12)
    cli = equipment_estimate(plant).payload()
    assert payload["source"]["fingerprints"] == cli["source"]["fingerprints"]


def test_a_plain_number_vessel_volume_is_kept_and_compared(plant: Path):
    # volume_m3 written as a plain number (no unit, no source) is a
    # hand-written value: the fill keeps it and compares it with the bed (40000 kg / 1130 kg/m3 =
    # 35.4 m3)
    _reactor_plant(plant, {"tag": "R-1", "type": "PressureVessel"})
    path = plant / "equipment/datasheets/R-1.yaml"
    data = yaml.safe_load(path.read_text())
    data["type_specific"]["volume_m3"] = 50.0
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    result = fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load(path.read_text())["type_specific"]
    assert specific["volume_m3"] == 50.0
    assert specific["catalyst_volume_m3"]["value"] == pytest.approx(35.4, rel=1e-3)
    assert not [f for f in result.findings if f.rule == "cheme.datasheet-reactor-volume"]
    data["type_specific"]["volume_m3"] = 20.0  # smaller than the bed
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    result = fill_datasheets(plant, ["R-1"])
    assert yaml.safe_load(path.read_text())["type_specific"]["volume_m3"] == 20.0
    assert any(f.rule == "cheme.datasheet-reactor-volume" for f in result.findings)


def test_space_velocity_sizing_on_the_catalysts_gas_basis(plant: Path):
    # FE_CR's GHSV is quoted on dry gas (gas: dry). The feed S1 is 1000
    # kmol/h with
    # 35 % H2O: dry 650 kmol/h x 22.414 Nm3/kmol (273.15 K, 101.325 kPa) = 14569 Nm3/h, at the
    # middle GHSV 4000 1/h a bed of 3.642 m3; wet (the water counted) 22414 / 4000 = 5.603 m3
    _reactor_plant(
        plant,
        {"tag": "R-1", "type": "PressureVessel"},
        lambda t: t.replace("    reactor: pfr\n", "    reactor: equilibrium\n"),
    )
    sheet = plant / "equipment/datasheets/R-1.yaml"
    fill_datasheets(plant, ["R-1"])
    bed = yaml.safe_load(sheet.read_text())["type_specific"]["catalyst_volume_m3"]
    assert bed["value"] == pytest.approx(3.642, abs=2e-3)
    assert "dry gas (H2O 350 kmol/h left out)" in bed["source"] and bed["assumed"] is True
    catalysts = plant / "process/catalysts.yaml"
    catalysts.write_text(catalysts.read_text().replace("gas: dry, ", ""))
    fill_datasheets(plant, ["R-1"])
    bed = yaml.safe_load(sheet.read_text())["type_specific"]["catalyst_volume_m3"]
    assert bed["value"] == pytest.approx(5.603, abs=2e-3)
    assert "wet gas" in bed["source"]


def test_a_dry_basis_is_for_a_ghsv_only():
    from pydantic import ValidationError

    from chemeascode.domains.chemistry.catalysts import SpaceVelocity

    velocity = {"basis": "GHSV", "range": [2000, 6000], "provenance": "assumed"}
    assert SpaceVelocity.model_validate(velocity).gas == "wet"
    assert "gas" not in SpaceVelocity.model_validate(velocity).model_dump()  # dumps unchanged
    assert SpaceVelocity.model_validate({**velocity, "gas": "dry"}).model_dump()["gas"] == "dry"
    with pytest.raises(ValidationError, match="gas: dry applies to a GHSV"):
        SpaceVelocity.model_validate({**velocity, "basis": "WHSV", "gas": "dry"})


def test_a_changed_catalyst_makes_its_bed_stale(plant: Path):
    # a bed sized from the catalyst's space velocity and bulk density names
    # the catalyst as an input: changing either is cheme.datasheet-stale until a refill
    from chemeascode.domains.equipment.fill import stale_findings
    from chemeascode.foundation.workspace import Workspace

    def stale() -> str:
        return " ".join(f.message for f in stale_findings(Workspace(plant)))

    _reactor_plant(
        plant,
        {"tag": "R-1", "type": "PressureVessel"},
        lambda t: t.replace("    reactor: pfr\n", "    reactor: equilibrium\n"),
    )
    sheet = plant / "equipment/datasheets/R-1.yaml"
    fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load(sheet.read_text())["type_specific"]
    for key in ("catalyst_volume_m3", "catalyst_mass_kg", "volume_m3"):
        assert specific[key]["inputs"] == ["catalyst:FE_CR"], key
    assert stale() == ""
    catalysts = plant / "process/catalysts.yaml"
    text = catalysts.read_text()
    catalysts.write_text(text.replace("range: [2000, 6000]", "range: [500, 1500]"))
    found = stale()
    for key in ("catalyst_volume_m3", "catalyst_mass_kg", "volume_m3"):
        assert f"type_specific.{key}" in found, key
    fill_datasheets(plant, ["R-1"])  # 4x the bed: 3.642 x 4000 / 1000 = 14.57 m3
    bed = yaml.safe_load(sheet.read_text())["type_specific"]["catalyst_volume_m3"]
    assert bed["value"] == pytest.approx(14.57, abs=1e-2)
    assert stale() == ""
    catalysts.write_text(catalysts.read_text().replace("bulk_density: 1130", "bulk_density: 1000"))
    found = stale()
    assert "type_specific.catalyst_mass_kg" in found
    # a changed source text is no changed input
    fill_datasheets(plant, ["R-1"])
    catalysts.write_text(catalysts.read_text().replace("dry gas basis, typical", "vendor V-3"))
    assert stale() == ""


def test_a_changed_catalyst_makes_a_pfr_bed_stale(plant: Path):
    # the pfr bed's volume and pressure drop read the catalyst's densities
    from chemeascode.domains.equipment.fill import stale_findings
    from chemeascode.foundation.workspace import Workspace

    _reactor_plant(plant, {"tag": "R-1", "type": "PressureVessel"})
    fill_datasheets(plant, ["R-1"])
    specific = yaml.safe_load((plant / "equipment/datasheets/R-1.yaml").read_text())[
        "type_specific"
    ]
    for key in ("catalyst_mass_kg", "catalyst_volume_m3", "pressure_drop_kpa", "volume_m3"):
        assert specific[key]["inputs"] == ["catalyst:FE_CR"], key
    assert not stale_findings(Workspace(plant))
    catalysts = plant / "process/catalysts.yaml"
    catalysts.write_text(catalysts.read_text().replace("bulk_density: 1130", "bulk_density: 1000"))
    (found,) = stale_findings(Workspace(plant))
    for key in ("catalyst_volume_m3", "pressure_drop_kpa", "volume_m3"):
        assert f"type_specific.{key}" in found.message, key
