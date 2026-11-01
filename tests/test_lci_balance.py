"""Mass, element and energy balance gates of LCI datasets, with fossil and biogenic carbon.

Four cases:

- a non-reactive air separation (SYNTHETIC numbers, not a design): 1000 kg/h of air (N2 0.755,
  O2 0.2315, Ar 0.0135 by mass) gives 200 kg/h of GOX (O2 0.995, Ar 0.005) and an 800 kg/h vent
  released to air; 100 kW of electricity in, 90 kW of heat to cooling water;
- the reactive methanol plant of ``test_lca_carbon`` (CO2 + 3 H2 -> CH3OH + H2O), and the same
  plant with the purge's CO2 replaced by H2 (the same mass, no carbon): its carbon does not
  close and the publication gate names the residual;
- the Tier 0 ammonia estimate of ``test_lci_estimate`` (reactive, by construction);
- hand-written datasets: a methane burner whose CO2 does not match its carbon input, an
  emission declared biogenic from fossil carbon, a fuel in Nm3, and exchanges without a
  composition or excluded with a reason.
"""

import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from chemeascode.domains.assessment.lca.balance import (
    SIMULATED_TOLERANCE,
    SOURCED_TOLERANCE,
    dataset_balance,
    elements_per_kg,
)
from chemeascode.domains.assessment.lca.gates import lca_gate
from chemeascode.domains.assessment.lca.report import lca_report, manifest
from chemeascode.domains.assessment.lca.schemas import Composition, DatasetExchange, LciDataset
from chemeascode.foundation.schemas.checks import Check
from chemeascode.interfaces.cli import app
from tests import test_lca_carbon as meoh

GATES = ["lci-mass-balance", "lci-element-balance", "lci-carbon-origin"]

ASU_MATERIALS = {
    "schema": "cheme/process/v1",
    "kind": "materials",
    "components": [
        {"id": "N2", "name": "Nitrogen", "formula": "N2", "cas": "7727-37-9", "molar_mass": 28.014},
        {"id": "O2", "name": "Oxygen", "formula": "O2", "cas": "7782-44-7", "molar_mass": 31.998},
        {"id": "AR", "name": "Argon", "formula": "Ar", "cas": "7440-37-1", "molar_mass": 39.948},
    ],
    "templates": [{"id": "air", "title": "Air", "components": ["N2", "O2", "AR"]}],
}  # fmt: skip


def _material(id_: str, src: str, dst: str, flow: float, composition: dict) -> dict:
    return {
        "id": id_,
        "from": src,
        "to": dst,
        "template": "air",
        "state": {
            "design": {
                "flow": {"value": flow, "basis": "mass", "provenance": "assumed"},
                "composition": {
                    "basis": "mass_fraction",
                    "values": composition,
                    "provenance": "assumed",
                },
            }
        },
    }


def _duty(id_: str, src: str, dst: str, kw: float) -> dict:
    return {
        "id": id_,
        "kind": "energy",
        "from": src,
        "to": dst,
        "state": {"design": {"duty": {"value": kw, "provenance": "assumed"}}},
    }


ASU_FLOWSHEET = {
    "schema": "cheme/process/v1",
    "kind": "flowsheet",
    "title": "Synthetic air separation (balance fixture)",
    "units": {"pressure": "kPa(a)", "temperature": "K", "flow": "kg/h", "duty": "kW"},
    "cases": [{"id": "design", "description": "Design", "default": True}],
    "feeds": [
        {"id": "AIR", "title": "Air", "ports": [{"id": "out", "direction": "out"}]},
        {"id": "POWER", "title": "Power", "category": "utility",
         "utility": {"kind": "electricity"},
         "ports": [{"id": "q", "direction": "out", "kind": "energy"}]},
        {"id": "CW", "title": "Cooling water", "category": "utility",
         "utility": {"kind": "cooling_water"},
         "ports": [{"id": "q", "direction": "out", "kind": "energy"}]},
    ],
    "products": [
        {"id": "GOX", "title": "GOX", "ports": [{"id": "in", "direction": "in"}]},
        {"id": "VENT", "title": "Vent", "category": "off_gas",
         "ports": [{"id": "in", "direction": "in"}]},
    ],
    "blocks": [
        {
            "id": "ASU",
            "title": "Air separation",
            "class": "SeparatingByThermalProcess",
            "ports": [
                {"id": "air", "direction": "in"},
                {"id": "power", "direction": "in", "kind": "energy"},
                {"id": "cw", "direction": "in", "kind": "energy"},
                {"id": "gox", "direction": "out"},
                {"id": "vent", "direction": "out"},
            ],
        }
    ],
    "streams": [
        _material("S1", "AIR.out", "ASU.air", 1000, {"N2": 0.755, "O2": 0.2315, "AR": 0.0135}),
        _material("S2", "ASU.gox", "GOX.in", 200, {"O2": 0.995, "AR": 0.005}),
        _material("S3", "ASU.vent", "VENT.in", 800,
                  {"N2": 0.94375, "O2": 0.040625, "AR": 0.015625}),
        _duty("E1", "POWER.q", "ASU.power", 100),
        _duty("Q1", "CW.q", "ASU.cw", 90),
    ],
}  # fmt: skip

ASU_SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "GOX", "amount": 1, "unit": "t"},
    "year": 2026,
    "location": "DE",
    "flows": [
        {"key": "feed:AIR", "free": True, "source": "ambient air"},
        {"key": "feed:POWER", "factor": "power", "source": "test"},
        {"key": "feed:CW", "factor": "cw", "source": "test"},
        {"key": "product:VENT", "emission": True, "source": "test"},
        *[
            {"key": f"emission:{c}", "elementary": {"compartment": "air"}, "source": "test"}
            for c in ("N2", "O2", "AR")
        ],
    ],
}  # fmt: skip
ASU_FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "climate", "unit": "kg CO2-eq", "method": "IPCC 2021 GWP100",
                    "elementary": "ipcc2021-gwp100"}],
    "factors": [
        {"id": i, "unit": "kWh", "values": {"climate": 0.1}, "status": "ASSUMED",
         "source": "test", "year": 2026}
        for i in ("power", "cw")
    ],
}  # fmt: skip


@pytest.fixture
def asu(tmp_path: Path) -> Path:
    root = tmp_path / "asu"
    (root / "process").mkdir(parents=True)
    (root / "lca").mkdir()
    (root / "plant.yaml").write_text(yaml.safe_dump({"name": "asu"}))
    (root / "process" / "materials.yaml").write_text(yaml.safe_dump(ASU_MATERIALS))
    (root / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(ASU_FLOWSHEET, sort_keys=False))
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(ASU_SCOPE, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(ASU_FACTORS, sort_keys=False))
    return root


def _methanol(tmp_path: Path, broken: bool = False) -> Path:
    flowsheet = json.loads(json.dumps(meoh.FLOWSHEET))
    if broken:
        # the purge's 20 kg/h of CO2 becomes H2: the mass closes, the carbon does not
        purge = next(s for s in flowsheet["streams"] if s["id"] == "S5")
        purge["state"]["design"]["composition"]["values"] = {"H2": 1.0}
    root = tmp_path / ("broken" if broken else "methanol")
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text(yaml.safe_dump({"name": "methanol"}))
    (root / "process" / "materials.yaml").write_text(yaml.safe_dump(meoh.MATERIALS))
    (root / "process" / "flowsheet.yaml").write_text(yaml.safe_dump(flowsheet, sort_keys=False))
    meoh._write(root, meoh._scope())
    return root


def _report(root: Path, inventory_only: bool = False):
    report = lca_report(root, inventory_only=inventory_only)
    assert report.loaded, [f.format() for f in report.findings if f.level == "error"]
    return report


def test_a_non_reactive_plant_closes(asu: Path) -> None:
    report = _report(asu)
    balance = report.balance
    assert (balance.tolerance, balance.tolerance_basis) == (
        SIMULATED_TOLERANCE,
        "derived from a simulated flowsheet",
    )
    assert balance.mass.inputs == pytest.approx(1000) and balance.mass.closed
    assert sorted(balance.elements) == ["Ar", "N", "O"]
    assert all(c.closed for c in balance.elements.values())
    assert balance.elements["O"].inputs == pytest.approx(231.5)
    assert {r: balance.status(r)[0] for r in GATES} == dict.fromkeys(GATES, "closed")
    # the vent is counted by its emissions, the duties by the energy closure
    assert balance.excluded["product:VENT"].startswith("counted by its emission")
    assert balance.excluded["feed:POWER"] == "energy: in the energy closure"
    assert balance.energy.inputs == {"electricity": pytest.approx(100)}
    assert balance.energy.outputs == {"heat rejected": pytest.approx(90)}
    assert balance.energy.fraction == pytest.approx(0.9)
    assert not [f for f in report.findings if f.rule.startswith("cheme.lci-")]
    assert lca_gate(asu, GATES) == []
    # the closure results are in the run manifest and the JSON
    written = manifest(report)["balance"]
    assert written["status"] == dict.fromkeys(GATES, "closed")
    assert written["mass"]["in"] == pytest.approx(1000)
    assert written["energy"]["closure"] == pytest.approx(0.9)
    assert json.loads(report.to_json())["balance"]["elements"]["N"]["closed"] is True
    # the dataset records each exchange's composition from the stream table
    gox = report.inventory.dataset.product("GOX")
    assert gox.composition.fractions == {"O2": 0.995, "AR": 0.005}
    assert gox.composition.formulas == {"O2": "O2", "AR": "Ar"}


def test_cli_balance_table_and_json(asu: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(asu)
    result = CliRunner().invoke(app, ["assess", "lca", "--balance"])
    assert result.exit_code == 0, result.output
    assert "tolerance 1 %" in result.output.replace("1%", "1 %")
    assert "mass" in result.output and "closed" in result.output
    assert "product:VENT: counted by its emission" in result.output
    assert "closure 90.0%" in result.output
    result = CliRunner().invoke(app, ["assess", "lca", "--balance", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["status"]["lci-mass-balance"] == "closed"
    result = CliRunner().invoke(app, ["assess", "lca", "--coverage"])
    assert result.exit_code == 0, result.output
    assert "balance (1% tolerance" in result.output
    assert "carbon-origin closed; energy closure 90.0%" in result.output


def test_a_reactive_plant_closes_in_every_element(tmp_path: Path) -> None:
    report = _report(_methanol(tmp_path), inventory_only=True)
    balance = report.balance
    assert sorted(balance.elements) == ["C", "H", "O"]
    assert {r: balance.status(r)[0] for r in GATES} == dict.fromkeys(GATES, "closed")
    # captured from air: the input carbon is atmospheric; out in the methanol and the purge
    carbon = balance.carbon
    assert carbon.inputs["atmospheric"] == pytest.approx(1393.5 * meoh.C_CO2, rel=1e-6)
    assert carbon.inputs["fossil"] == 0
    assert carbon.outputs["products"] == pytest.approx(1000 * meoh.C_MEOH, rel=1e-6)
    assert carbon.outputs["emissions"] == pytest.approx(20 * meoh.C_CO2, rel=1e-6)


def test_carbon_that_does_not_match_fails_the_publication_gate(tmp_path: Path) -> None:
    """The acceptance criterion of the balance gates: CO2 out of step with the carbon fed fails
    the gate, naming the residual."""
    root = _methanol(tmp_path, broken=True)
    report = _report(root)
    balance = report.balance
    assert balance.mass.closed  # the mass alone does not show it
    assert balance.status("lci-carbon-origin")[0] == "open"
    residual = balance.carbon.closure.residual
    assert residual == pytest.approx(20 * meoh.C_CO2, rel=1e-2)
    warnings = [f for f in report.findings if f.rule == "cheme.lci-carbon-origin"]
    assert warnings and all(f.level == "warning" for f in warnings)
    problems = lca_gate(root, ["lci-carbon-origin"])
    assert len(problems) == 1
    assert f"residual {residual:+.6g} kg C" in problems[0]
    assert "tolerance 1%" in problems[0]
    # the element balance names C (and the H and O that moved with it)
    failing = lca_gate(root, ["lci-element-balance"])
    assert any(
        p.startswith("lca/dataset.yaml: element balance does not close: C:") for p in failing
    )
    assert lca_gate(root, ["lci-mass-balance"]) == []
    assert manifest(report)["balance"]["status"]["lci-carbon-origin"] == "open"


def test_gate_requirements_are_accepted_by_the_checks_schema() -> None:
    check = Check(id="lca", title="LCA", stage="basic", kind="lca", require=GATES)
    assert check.require == GATES
    with pytest.raises(ValidationError):
        Check(id="mto", title="MTO", stage="basic", kind="mto", require=["lci-mass-balance"])


def test_a_tier0_estimate_closes_at_the_screening_tolerance(tmp_path: Path) -> None:
    from chemeascode.domains.assessment.lca.estimate import lci_estimate
    from tests.test_lci_estimate import AMMONIA, _repo

    dataset = lci_estimate(_repo(tmp_path, "process-ammonia", AMMONIA)).dataset
    balance = dataset_balance(dataset)
    assert balance.tolerance == SOURCED_TOLERANCE
    assert balance.tolerance_basis.startswith("Tier 0")
    assert {"H", "N"} <= set(balance.elements)
    assert balance.status("lci-element-balance") == ("closed", [])
    assert balance.status("lci-mass-balance") == ("closed", [])


# -- hand-written datasets ------------------------------------------------------------------------


def _dataset(exchanges: list[dict], **extra) -> LciDataset:
    return LciDataset.model_validate(
        {
            "schema": "cheme/lci_dataset/v2",
            "kind": "lci_dataset",
            "id": "burner",
            "exchanges": exchanges,
            **extra,
        }
    )


HEAT = {"key": "product:HEAT", "type": "product", "amount": 1, "unit": "kWh"}
CH4 = {"key": "feed:CH4", "type": "input", "amount": 16.043, "unit": "kg",
       "composition": {"fractions": {"CH4": 1.0}}}  # fmt: skip
O2 = {"key": "resource:O2", "type": "resource", "amount": 63.996, "unit": "kg", "cas": "7782-44-7"}
H2O = {"key": "emission:H2O", "type": "emission", "amount": 36.03, "unit": "kg", "cas": "7732-18-5"}


def _co2(amount: float, origin: str = "fossil") -> dict:
    return {"key": "emission:CO2", "type": "emission", "amount": amount, "unit": "kg",
            "cas": "124-38-9",
            "link": {"elementary": {"compartment": "air", "origin": origin},
                     "source": "test"}}  # fmt: skip


def test_a_hand_written_burner_closes() -> None:
    """CH4 + 2 O2 -> CO2 + 2 H2O, per kmol of methane."""
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O]))
    assert balance.tolerance == SOURCED_TOLERANCE  # not derived from a flowsheet
    assert {r: balance.status(r)[0] for r in GATES} == dict.fromkeys(GATES, "closed")
    assert balance.carbon.declared == {"fossil": pytest.approx(12.011)}
    assert balance.excluded == {"product:HEAT": "energy: in the energy closure"}


def test_co2_that_does_not_match_the_carbon_input_is_named() -> None:
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(22.0), H2O]))
    state, problems = balance.status("lci-carbon-origin")
    assert state == "open"
    assert "residual +6.0" in problems[0] and "kg C" in problems[0]
    findings = balance.findings("lca/datasets/burner.yaml")
    assert {f.rule for f in findings} >= {"cheme.lci-carbon-origin", "cheme.lci-element-balance"}
    assert all(f.level == "warning" for f in findings)


def test_an_emission_declared_biogenic_from_fossil_carbon() -> None:
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009, "biogenic"), H2O]))
    state, problems = balance.status("lci-carbon-origin")
    assert state == "open"
    assert balance.carbon.closure.closed  # the total closes, the origin does not
    assert "declared biogenic (emission:CO2)" in problems[0]
    assert "inputs give 0 kg C of biogenic carbon" in problems[0]


def test_a_fuel_in_nm3_is_counted_by_its_molar_mass() -> None:
    gas = {**CH4, "amount": 22.41396954, "unit": "Nm3"}
    balance = dataset_balance(_dataset([HEAT, gas, O2, _co2(44.009), H2O]))
    assert balance.mass.inputs == pytest.approx(16.043 + 63.996, rel=1e-4)
    assert balance.status("lci-carbon-origin")[0] == "closed"


def test_missing_compositions_are_named_and_exclusions_stated() -> None:
    sieve = {"key": "input:sieve", "type": "input", "amount": 0.01, "unit": "kg"}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, sieve]))
    state, problems = balance.status("lci-element-balance")
    assert state == "not-assessable"
    assert "input:sieve (no composition)" in problems[0]
    assert balance.status("lci-carbon-origin")[0] == "not-assessable"
    assert [f.level for f in balance.findings("x.yaml")] == ["info"]
    excluded = {**sieve, "balance_exclusion": "adsorbent charge, replaced every 5 years"}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, excluded]))
    assert balance.status("lci-element-balance")[0] == "closed"
    assert balance.excluded["input:sieve"] == "adsorbent charge, replaced every 5 years"
    # construction is outside the operating balance
    steel = {"key": "construction:steel", "type": "input", "amount": 5, "unit": "kg",
             "phase": "construction"}  # fmt: skip
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, steel]))
    assert balance.excluded["construction:steel"].startswith("construction phase")


def test_fuel_lhv_and_product_energy_in_the_energy_closure() -> None:
    fuel = {**CH4, "carrier": {"kind": "fuel", "lhv": 50.0, "source": "test value"}}
    heat = {**HEAT, "amount": 200.0}
    balance = dataset_balance(_dataset([heat, fuel, O2, _co2(44.009), H2O]))
    # 16.043 kg x 50 MJ/kg / 3.6 = 222.8 kWh in; the heat product has no carrier
    assert balance.energy.inputs == {"fuel (LHV)": pytest.approx(16.043 * 50 / 3.6)}
    assert balance.energy.unclassified == ["product:HEAT"]


def test_composition_contract() -> None:
    assert Composition(elements={"C": 0.75, "H": 0.25}).elements["C"] == 0.75
    with pytest.raises(ValidationError, match="one of them"):
        Composition(fractions={"CH4": 1.0}, elements={"C": 1.0})
    with pytest.raises(ValidationError, match="sum above 1"):
        Composition(fractions={"CH4": 0.7, "CO2": 0.7})
    with pytest.raises(ValidationError, match="not in fractions"):
        Composition(fractions={"CH4": 1.0}, formulas={"X": "CO2"})
    with pytest.raises(ValidationError, match="material exchanges"):
        DatasetExchange(key="feed:E", type="input", amount=1, unit="kWh",
                        composition={"fractions": {"CH4": 1.0}})  # fmt: skip
    exchange = DatasetExchange(
        key="feed:X", type="input", amount=1, unit="kg",
        composition={"fractions": {"MEOH": 0.5, "H2O": 0.5}, "formulas": {"MEOH": "CH4O"}},
    )  # fmt: skip
    shares, molar, why = elements_per_kg(exchange)
    assert why == "" and sum(shares.values()) == pytest.approx(1)
    assert molar == pytest.approx(1 / (0.5 / 32.042 + 0.5 / 18.015), rel=1e-3)
    unknown = exchange.model_copy(update={"composition": Composition(fractions={"MEOH": 1.0})})
    assert elements_per_kg(unknown)[2] == "no readable formula for MEOH"
    partial = exchange.model_copy(update={"composition": Composition(fractions={"H2O": 0.9})})
    assert "covers 90" in elements_per_kg(partial)[2]


# -- review fixes ----------------------------------------------------------------------------------


def test_a_gaseous_fuel_in_nm3_counts_at_its_lhv() -> None:
    gas = {**CH4, "amount": 22.41396954, "unit": "Nm3",
           "carrier": {"kind": "fuel", "lhv": 50.0, "source": "test value"}}  # fmt: skip
    balance = dataset_balance(_dataset([HEAT, gas, O2, _co2(44.009), H2O]))
    # 1 kmol of CH4 is 16.043 kg: 16.043 x 50 MJ/kg / 3.6 kWh
    assert balance.energy.inputs == {"fuel (LHV)": pytest.approx(16.043 * 50 / 3.6, rel=1e-4)}
    # a fuel without its LHV is listed, never counted as 0
    unknown = {**gas, "carrier": {"kind": "fuel", "source": "test"}}
    balance = dataset_balance(_dataset([HEAT, unknown, O2, _co2(44.009), H2O]))
    assert "feed:CH4" in balance.energy.unclassified


def test_land_use_change_emissions_are_outside_the_operating_balance() -> None:
    luc = {**_co2(10.0, origin="land-use-change"), "key": "emission:CO2-luc"}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, luc]))
    assert {r: balance.status(r)[0] for r in GATES} == dict.fromkeys(GATES, "closed")
    assert balance.excluded["emission:CO2-luc"].startswith("land-use change")


def test_an_unresolved_carbon_origin_is_not_assessable() -> None:
    linked = {**CH4, "link": {"dataset": {"path": "lca/bg/biogas.yaml", "product": "CH4"},
                              "source": "test"}}  # fmt: skip
    exchanges = [HEAT, linked, O2, _co2(44.009), H2O]
    balance = dataset_balance(_dataset(exchanges), load=lambda path: f"no {path}")
    state, problems = balance.status("lci-carbon-origin")
    assert state == "not-assessable"
    assert problems and all(p.startswith("carbon balance not assessable") for p in problems)
    # mass and elements do not depend on the origin
    assert balance.status("lci-element-balance")[0] == "closed"


def test_water_in_m3_takes_part_in_the_mass_balance() -> None:
    water = {"key": "resource:water", "type": "resource", "amount": 0.1, "unit": "m3",
             "cas": "7732-18-5"}  # fmt: skip
    vapour = {**H2O, "key": "emission:H2O-evaporated", "amount": 100.0}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, water, vapour]))
    assert "resource:water" not in balance.excluded
    assert balance.mass.inputs == pytest.approx(16.043 + 63.996 + 100.0)
    assert balance.status("lci-mass-balance")[0] == "closed"
    assert balance.status("lci-element-balance")[0] == "closed"
    # another flow in m3 is still not a mass
    other = {"key": "input:sand", "type": "input", "amount": 1, "unit": "m3"}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, other]))
    assert balance.excluded["input:sand"] == "unit m3: not a mass"


def test_an_ultimate_analysis_with_ash() -> None:
    assert Composition(elements={"C": 0.5, "H": 0.06, "O": 0.42, "ash": 0.02})
    wood = {"key": "feed:wood", "type": "input", "amount": 100.0, "unit": "kg",
            "composition": {"elements": {"C": 0.5, "H": 0.06, "O": 0.42, "ash": 0.02}}}  # fmt: skip
    ash = {"key": "output:ash", "type": "output", "amount": 2.0, "unit": "kg",
           "composition": {"elements": {"ash": 1.0}}}  # fmt: skip
    balance = dataset_balance(_dataset([HEAT, wood, ash]))
    assert balance.elements_assessable
    assert balance.elements["C"].inputs == pytest.approx(50.0)
    assert "ash" not in balance.elements
    assert balance.mass.inputs == pytest.approx(100.0)
    with pytest.raises(ValidationError, match="element symbols"):
        Composition(elements={"C": 0.5, "dust": 0.5})


def test_co2_from_air_is_atmospheric_even_when_declared_biogenic() -> None:
    co2 = {"key": "resource:CO2", "type": "resource", "amount": 44.009, "unit": "kg",
           "cas": "124-38-9"}  # fmt: skip
    for extra in (
        {},
        {"carbon": {"biogenic_fraction": 1.0}},
        {"carbon": {"biogenic_fraction": 0.0}},
    ):
        balance = dataset_balance(_dataset([HEAT, {**co2, **extra}]))
        assert balance.carbon.inputs["atmospheric"] == pytest.approx(12.011, rel=1e-4)
        assert balance.carbon.inputs["biogenic"] == 0.0
        assert balance.carbon.inputs["fossil"] == 0.0


def test_water_in_m3_beside_an_uncounted_m3_return_is_excluded() -> None:
    water = {"key": "resource:water", "type": "resource", "amount": 1.0, "unit": "m3",
             "cas": "7732-18-5"}  # fmt: skip
    back = {"key": "output:wastewater", "type": "output", "amount": 1.0, "unit": "m3"}
    balance = dataset_balance(_dataset([HEAT, CH4, O2, _co2(44.009), H2O, water, back]))
    assert balance.excluded["output:wastewater"] == "unit m3: not a mass"
    assert "output:wastewater" in balance.excluded["resource:water"]
    assert {r: balance.status(r)[0] for r in GATES} == dict.fromkeys(GATES, "closed")


def test_an_excluded_gaseous_fuel_still_counts_in_the_energy_closure() -> None:
    gas = {**CH4, "amount": 22.41396954, "unit": "Nm3", "balance_exclusion": "test",
           "carrier": {"kind": "fuel", "lhv": 50.0, "source": "test value"}}  # fmt: skip
    balance = dataset_balance(_dataset([HEAT, gas]))
    assert balance.energy.inputs == {"fuel (LHV)": pytest.approx(16.043 * 50 / 3.6, rel=1e-4)}
