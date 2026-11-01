"""The examples' design bases (process/design-basis.yaml): they load, name
the flowsheet terminals they describe, cite a source for the capacity and agree with the flowsheet
values they restate."""

from pathlib import Path

import pytest
import yaml

from chemeascode.domains.requirements.schemas import DesignBasis
from chemeascode.foundation.workspace import Workspace
from chemeascode.project.validate import validate_workspace

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
#: examples with a cited design basis; the others have none
WITH_BASIS = ["process-ammonia", "process-double-column"]


def _yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _stream(root: Path, sid: str) -> dict:
    flowsheet = _yaml(root / "process" / "flowsheet.yaml")
    return next(s for s in flowsheet["streams"] if s["id"] == sid)


def test_only_the_cited_examples_have_a_design_basis():
    found = sorted(p.parents[1].name for p in EXAMPLES.glob("*/process/design-basis.yaml"))
    assert found == WITH_BASIS


@pytest.mark.parametrize("name", WITH_BASIS)
def test_the_design_basis_loads_and_names_flowsheet_terminals(name):
    root = EXAMPLES / name
    basis = DesignBasis.model_validate(_yaml(root / "process" / "design-basis.yaml"))
    assert basis.capacity and basis.feeds and basis.products
    assert basis.capacity.get("source")
    assert all(entry.get("terminal") for entry in basis.feeds + basis.products)
    findings = validate_workspace(Workspace(root)).findings
    assert not [f for f in findings if f.level == "error"]
    assert not [f for f in findings if f.rule == "cheme.contract-ref"]


def test_the_ammonia_capacity_is_the_flowsheet_product():
    root = EXAMPLES / "process-ammonia"
    basis = _yaml(root / "process" / "design-basis.yaml")
    product = _stream(root, "S6")["state"]["design"]
    assert product["composition"]["values"]["NH3"] == 1.0
    t_per_d = product["flow"]["value"] * 17.031 * 24 / 1000  # kmol/h of NH3 -> t/d
    assert basis["capacity"]["value"] == pytest.approx(t_per_d, abs=0.5)
    makeup = _stream(root, "S1")["state"]["design"]
    feed = basis["feeds"][0]
    values = makeup["composition"]["values"]
    assert values["H2"] / values["N2"] == pytest.approx(feed["h2_to_n2_molar"])
    assert values["AR"] * 100 == pytest.approx(feed["argon_mol_percent"])
    assert makeup["pressure"]["value"] == pytest.approx(feed["pressure"]["value"] * 100)  # kPa


def test_the_double_column_air_is_the_cited_dry_air():
    root = EXAMPLES / "process-double-column"
    basis = _yaml(root / "process" / "design-basis.yaml")
    # NASA Earth Fact Sheet: 78.08 % N2, 20.95 % O2, 9340 ppm Ar, normalised over the three
    cited = {"N2": 78.08, "O2": 20.95, "AR": 0.934}
    total = sum(cited.values())
    for feed, sid in zip(basis["feeds"], ("S1", "S6"), strict=True):
        state = _stream(root, sid)["state"]["design"]
        assert feed["composition_mol_fraction"] == state["composition"]["values"]
        assert feed["flow"]["value"] == state["flow"]["value"]
        for component, value in feed["composition_mol_fraction"].items():
            assert value == pytest.approx(cited[component] / total, abs=5e-5)
    # the capacity and the product rates are the simulation's specs
    specs = _yaml(root / "process" / "simulation.yaml")["specs"]
    rates = {
        "GOX": specs["C2"]["side_draws"]["gox"]["flow"]["value"],
        "GAN": specs["C1"]["vapor_flow"]["value"],
        "LIN": specs["C1"]["side_draws"]["lin"]["flow"]["value"],
        "LOX": specs["C2"]["reboiler_spec"]["flow"]["value"],
    }
    assert basis["capacity"]["value"] == rates["GOX"]
    for product in basis["products"]:
        if product["terminal"] in rates:
            assert product["flow"]["value"] == rates[product["terminal"]], product["terminal"]
