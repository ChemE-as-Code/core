"""The kinetics of ``GET /api/reactions``: each reaction's rate law with its parameters,
provenance and ``rate_law`` (expression, units, k(T)), and ``kinetics`` (the catalysts of
``process/catalysts.yaml`` linked to their reactions and reactors, and their findings), served
and exported by ``cheme export-static``."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chemeascode.domains.chemistry.rates import Adsorption, Arrhenius, RateLaw
from chemeascode.domains.process.reaction_view import K_PROFILE_POINTS, rate_law_view
from chemeascode.interfaces.api.export_static import export_static
from chemeascode.interfaces.api.serve import create_app
from tests.conftest import git

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.fixture
def shift(tmp_path: Path) -> Path:
    root = tmp_path / "process-shift"
    shutil.copytree(EXAMPLES / "process-shift", root, ignore=shutil.ignore_patterns("build"))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "plant")
    return root


def client(root: Path) -> TestClient:
    return TestClient(create_app(root, allowed_hosts=["testserver"]))


def test_rate_law_and_catalysts_are_served(shift: Path):
    data = client(shift).get("/api/reactions").json()
    (wgs,) = data["reactions"]
    # the rate law as declared, with its provenance
    assert wgs["rate"]["form"] == "power_law" and wgs["rate"]["provenance"] == "assumed"
    assert wgs["rate"]["k"] == {"A": 1000.0, "Ea": 111000.0, "n": 0.0, "T_ref": 1.0}
    assert wgs["rate"]["orders"] == {"CO": 1.0, "CO2": -0.36, "H2": -0.09}
    assert "Hla" in wgs["rate"]["source"] and wgs["catalyst"] == "FE_CR"
    law = wgs["rate_law"]
    assert law["expression"] == "r = k(T) · p_CO · p_CO2^-0.36 · p_H2^-0.09 · (1 - Q/K)"
    assert law["rate_unit"] == "kmol/(kg s)" and law["k_unit"] == "kmol/(kg s) / bar^0.55"
    assert law["catalyst"] == "FE_CR" and law["k_profile_from"] == "temperature_range"
    profile = law["k_profile"]
    assert len(profile) == K_PROFILE_POINTS
    assert profile[0]["temperature_K"] == 573.15
    assert math.isclose(profile[-1]["temperature_K"], 773.15)
    assert profile[0]["k"] == pytest.approx(1000.0 * math.exp(-111000 / (8.314462618 * 573.15)))
    assert all(a["k"] < b["k"] for a, b in zip(profile, profile[1:], strict=False))

    kinetics = data["kinetics"]
    assert kinetics["file"] == "process/catalysts.yaml"
    (cat,) = kinetics["catalysts"]
    assert cat["id"] == "FE_CR" and cat["reactions"] == ["WGS"]
    assert cat["physical"]["bulk_density"] == 1130.0 and cat["physical"]["provenance"] == "assumed"
    assert cat["window"]["temperature"] == [583.15, 773.15]
    (unit,) = cat["units"]
    assert unit["unit"] == "R1" and unit["reactor"] == "pfr" and unit["reactions"] == ["WGS"]
    assert unit["bed"]["catalyst_mass"] == 40000.0 and unit["bed"]["heat"] == "adiabatic"
    assert {f["rule"] for f in kinetics["findings"]} == {"cheme.catalyst-poison"}
    # the solved bed is the reactor row's
    (r1,) = [r for r in data["reactors"] if r["node"] == "R1"]
    assert r1["bed"]["catalyst_mass_kg"] == 40000.0 and len(r1["bed"]["profile"]) > 2


def test_catalyst_findings_and_no_catalysts_file(shift: Path):
    path = shift / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("catalyst: FE_CR", "catalyst: NOPE"))
    data = client(shift).get("/api/reactions").json()
    rules = {f["rule"] for f in data["kinetics"]["findings"]}
    assert "cheme.process-catalyst" in rules
    assert data["kinetics"]["catalysts"][0]["units"] == []

    (shift / "process/catalysts.yaml").unlink()
    data = client(shift).get("/api/reactions").json()
    assert data["kinetics"]["file"] is None and data["kinetics"]["catalysts"] == []
    # no catalyst window either: the rate law's own range still gives k(T)
    assert len(data["reactions"][0]["rate_law"]["k_profile"]) == K_PROFILE_POINTS


def test_rate_law_view_lhhw_and_window():
    law = RateLaw(
        form="lhhw",
        basis="volume",
        driving="concentration",
        k=Arrhenius(A=2.0, Ea=50000),
        orders={"A": 1, "B": 0.5},
        adsorption=[Adsorption(A=1.0), Adsorption(A=0.1, dH=-20000, exponents={"A": 1})],
        power=2,
        provenance="given",
    )
    view = rate_law_view(law)
    assert view["expression"] == "r = k(T) · c_A · c_B^0.5 / (1 + K1(T) + K2(T) · c_A)^2"
    assert view["rate_unit"] == "kmol/(m3 s)" and view["k_unit"] == "kmol/(m3 s) / (kmol/m3)^1.5"
    assert view["k_profile"] == [] and view["k_profile_from"] is None and view["catalyst"] is None
    windowed = rate_law_view(law, (400.0, 500.0))
    assert windowed["k_profile_from"] == "catalyst window"
    assert windowed["k_profile"][-1] == {"temperature_K": 500.0, "k": law.k.k(500.0)}


def test_export_static_writes_the_kinetics(shift: Path, tmp_path: Path):
    manifest = export_static(shift, tmp_path / "out")
    entry = manifest["entries"]["reactions"]
    assert entry["status"] == 200
    stored = json.loads((tmp_path / "out" / "data" / entry["file"]).read_text())
    assert stored["kinetics"]["catalysts"][0]["id"] == "FE_CR"
    assert stored["reactions"][0]["rate_law"]["k_profile"]
