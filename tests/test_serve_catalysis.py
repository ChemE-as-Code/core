"""The viewer API for catalysis: the reactors' gas model, the mechanisms analysed at their
reactor's outlet (/api/reactions), the kinetic data with their fits (/api/kinetics) and the
reaction library marked by what the plant has (/api/library), and export-static of them."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from chemeascode.domains.chemistry.equilibrium import reaction_ln_k
from chemeascode.domains.chemistry.rates import rate
from chemeascode.domains.process.model import load
from chemeascode.interfaces.api.export_static import export_static
from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _repo(tmp_path: Path, example: str) -> Path:
    root = tmp_path / example
    shutil.copytree(EXAMPLES / example, root, ignore=shutil.ignore_patterns("build"))
    return root


def _commit(root: Path) -> Path:
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "plant")
    return root


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def test_the_reactor_rows_say_their_gas_model(tmp_path):
    rows = (
        client(_commit(_repo(tmp_path, "process-ammonia"))).get("/api/reactions").json()["reactors"]
    )
    assert next(r for r in rows if r["node"] == "R1")["fugacity"] == "peng_robinson"
    rows = (
        client(_commit(_repo(tmp_path, "process-shift"))).get("/api/reactions").json()["reactors"]
    )
    assert next(r for r in rows if r["node"] == "R1")["fugacity"] == "ideal"


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


def _co_oxidation(tmp_path: Path) -> Path:
    root = tmp_path / "coox"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: coox\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(
        "schema: cheme/process/v1\nkind: materials\ncomponents:\n"
        "  - {id: CO, name: Carbon monoxide, formula: CO, cas: 630-08-0, molar_mass: 28.010}\n"
        "  - {id: O2, name: Oxygen, formula: O2, cas: 7782-44-7, molar_mass: 31.998}\n"
        "  - {id: CO2, name: Carbon dioxide, formula: CO2, cas: 124-38-9, molar_mass: 44.009}\n"
        "  - {id: N2, name: Nitrogen, formula: N2, cas: 7727-37-9, molar_mass: 28.014}\n"
    )
    reactions = {
        "schema": "cheme/reactions/v1",
        "kind": "reactions",
        "reactions": [
            {
                "id": "COOX",
                "stoichiometry": {"CO": -2, "O2": -1, "CO2": 2},
                "conversion": {"key": "CO", "value": 0.5, "provenance": "assumed"},
                "mechanism": CO_OX,
            },
            {"id": "UNUSED", "stoichiometry": {"CO": -2, "O2": -1, "CO2": 2}, "mechanism": CO_OX},
        ],
    }
    (root / "process/reactions.yaml").write_text(yaml.safe_dump(reactions, sort_keys=False))
    (root / "process/flowsheet.yaml").write_text(
        """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds: [{id: F, ports: [{id: out, direction: out}]}]
products: [{id: P, ports: [{id: in, direction: in}]}]
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [COOX]
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    state:
      design:
        temperature: {value: 480, provenance: given}
        pressure: {value: 100, provenance: given}
        flow: {value: 100, provenance: given}
        composition:
          basis: mole_fraction
          values: {CO: 0.02, O2: 0.1, CO2: 0.0, N2: 0.88}
          provenance: given
  - id: S2
    from: R.out
    to: P.in
    state:
      design:
        temperature: {value: 500, provenance: assumed}
        pressure: {value: 100, provenance: assumed}
        flow: {value: 99.5, provenance: assumed}
        composition:
          basis: mole_fraction
          values: {CO: 0.01005, O2: 0.09548, CO2: 0.01005, N2: 0.88442}
          provenance: assumed
"""
    )
    return root


def test_a_mechanism_is_analysed_at_its_reactors_outlet(tmp_path):
    data = client(_commit(_co_oxidation(tmp_path))).get("/api/reactions").json()
    coox = next(r for r in data["reactions"] if r["id"] == "COOX")
    mk = coox["microkinetics"]
    assert mk["missing"] is None
    assert mk["conditions"]["unit"] == "R" and mk["conditions"]["stream"] == "S2"
    assert mk["conditions"]["temperature_K"] == 500
    assert mk["conditions"]["pressures_bar"]["CO"] == pytest.approx(0.01005, rel=1e-6)
    assert mk["tof_per_s"] > 0
    assert sum(mk["rate_control"].values()) == pytest.approx(1.0, abs=1e-3)
    assert mk["orders"]["CO"] == pytest.approx(-2.0, abs=0.05)
    unused = next(r for r in data["reactions"] if r["id"] == "UNUSED")
    assert unused["microkinetics"] == {
        "conditions": None,
        "missing": "the reaction takes place in no block or step",
    }
    plain = _commit(_repo(tmp_path, "process-shift"))
    assert all(
        r["microkinetics"] is None for r in client(plain).get("/api/reactions").json()["reactions"]
    )


def _kinetic_data(root: Path) -> None:
    """Rates of the shift example's own rate law: the default fit must give it back."""
    process, _ = load(root)
    wgs = process.reactions.by_id()["WGS"]
    ideal = process.ideal_gas()
    points = []
    for t in (623.15, 653.15, 683.15):
        for co in (0.05, 0.1):
            for co2, h2o in ((0.03, 0.3), (0.06, 0.4)):
                y = {"CO": co, "H2O": h2o, "CO2": co2, "H2": 0.45}
                p = {n: v * 30 for n, v in y.items()}  # bar at 30 bar
                r = rate(wgs.rate, wgs.stoichiometry, y, t, 3000.0, reaction_ln_k(wgs, ideal, t))
                points.append({"temperature": t, "partial_pressures": p, "rate": r})
    data = {
        "schema": "cheme/kinetic-data/v1",
        "kind": "kinetic-data",
        "reaction": "WGS",
        "catalyst": "FE_CR",
        "basis": "catalyst_mass",
        "points": points,
        "provenance": "calculated",
        "source": "the example's rate law",
    }
    (root / "experiments/kinetics").mkdir(parents=True)
    (root / "experiments/kinetics/wgs.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    (root / "experiments/kinetics/broken.yaml").write_text(
        "schema: cheme/kinetic-data/v1\nkind: nope\n"
    )


def test_kinetic_data_and_their_fits(tmp_path):
    root = _repo(tmp_path, "process-shift")
    _kinetic_data(root)
    api = client(_commit(root))
    assert api.get("/api/repo").json()["has_kinetic_data"] is True
    data = api.get("/api/kinetics").json()
    files = {f["file"]: f for f in data["files"]}
    wgs = files["experiments/kinetics/wgs.yaml"]
    assert wgs["problem"] is None and wgs["fit"]["reverse"] is True
    assert len(wgs["data"]["points"]) == 12
    # the default orders are the reactants' (CO and H2O): CO 1 and Ea as in the example's law
    assert wgs["fit"]["rate"]["orders"]["CO"] == pytest.approx(1.0, abs=1e-6)
    assert wgs["fit"]["rate"]["k"]["Ea"] == pytest.approx(111000, rel=1e-6)
    problem = files["experiments/kinetics/broken.yaml"]["problem"]
    assert problem.startswith("experiments/kinetics/broken.yaml: kind: ") and "more)" in problem
    without = client(_commit(_repo(tmp_path / "x", "process-shift")))
    assert without.get("/api/repo").json()["has_kinetic_data"] is False
    assert without.get("/api/kinetics").status_code == 404


def test_the_library_is_marked_by_what_the_plant_has(tmp_path):
    data = client(_commit(_repo(tmp_path, "process-shift"))).get("/api/library").json()
    entries = {e["id"]: e for e in data["entries"]}
    assert len(entries) == 23
    shift = entries["ht_shift"]
    assert {c["id"]: c["in_plant"] for c in shift["components"]} == {
        "CO": "CO",
        "H2O": "H2O",
        "CO2": "CO2",
        "H2": "H2",
    }
    assert shift["reactions"][0]["in_plant"] is True  # WGS: the same stoichiometry
    assert shift["catalysts"][0]["in_plant"] is True  # FE_CR
    assert shift["catalysts"][0]["differs"] is True  # the example's has its own physical data
    assert entries["lt_shift"]["catalysts"][0]["differs"] is False  # not in the plant
    assert entries["ammonia"]["reactions"][0]["in_plant"] is False
    assert not any(c["in_plant"] for c in entries["sulfuric_acid"]["components"])


def test_export_static_writes_kinetics_and_library(tmp_path):
    root = _repo(tmp_path, "process-shift")
    _kinetic_data(root)
    manifest = export_static(_commit(root), tmp_path / "out")
    for endpoint in ("kinetics", "library"):
        entry = manifest["entries"][endpoint]
        assert entry["status"] == 200
        stored = json.loads((tmp_path / "out" / "data" / entry["file"]).read_text())
        assert stored["files" if endpoint == "kinetics" else "entries"]


def test_kinetics_and_library_without_a_flowsheet_that_loads(tmp_path):
    root = _repo(tmp_path, "process-shift")
    _kinetic_data(root)
    (root / "process/flowsheet.yaml").write_text(
        "schema: cheme/process/v1\nkind: flowsheet\nblocks: 3\n"
    )
    api = client(_commit(root))
    wgs = next(
        f for f in api.get("/api/kinetics").json()["files"] if f["file"].endswith("wgs.yaml")
    )
    assert wgs["fit"] is not None  # the fits need the materials and reactions only
    entries = {e["id"]: e for e in api.get("/api/library").json()["entries"]}
    assert entries["ht_shift"]["reactions"][0]["in_plant"] is True


def test_export_static_leaves_out_excluded_kinetic_data(tmp_path):
    root = _repo(tmp_path, "process-shift")
    _kinetic_data(root)
    manifest = export_static(
        _commit(root), tmp_path / "out", exclude=["experiments/kinetics/wgs.yaml"]
    )
    entry = manifest["entries"]["kinetics"]
    stored = json.loads((tmp_path / "out" / "data" / entry["file"]).read_text())
    assert [f["file"] for f in stored["files"]] == ["experiments/kinetics/broken.yaml"]
    assert "kinetics" not in {w["endpoint"] for w in manifest["withheld"]}


def test_export_static_withholds_kinetics_built_from_excluded_reactions(tmp_path):
    """The fits use the plant's reactions, so excluding them withholds the
    answer."""
    root = _repo(tmp_path, "process-shift")
    _kinetic_data(root)
    manifest = export_static(_commit(root), tmp_path / "out", exclude=["process/reactions.yaml"])
    withheld = {w["endpoint"]: w["reason"] for w in manifest["withheld"]}
    assert "kinetics" not in manifest["entries"]
    assert withheld["kinetics"] == "built from files matching --exclude process/reactions.yaml"
    assert {"reactions", "library"} <= set(withheld)
