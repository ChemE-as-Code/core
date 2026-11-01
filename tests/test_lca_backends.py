"""``cheme assess lca``: the construction phase, scenarios, and the Brightway backend.

The plant is ``examples/process-blocks`` (see ``test_lca.py``): 1 t of product is 2.5 h of
operation. The Brightway tests build a small project in a temporary ``BRIGHTWAY2_DIR`` and run in
a subprocess, so the environment variable reaches bw2data before it is imported.
"""

import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.assessment.lca.construction import read_takeoff
from chemeascode.domains.assessment.lca.report import lca_report, results_csv, results_markdown
from chemeascode.domains.assessment.mto import MtoRow, mto_csv
from chemeascode.integrations import brightway

EXAMPLE = Path(__file__).parents[1] / "examples" / "process-blocks"
SCOPE = {
    "schema": "cheme/lca/v1",
    "kind": "lca",
    "functional_unit": {"product": "PROD", "amount": 1, "unit": "t"},
    "allocation": {"method": "none"},
    "flows": [
        {"key": "feed:FEED", "factor": "feed", "source": "test"},
        {"key": "feed:STEAM", "factor": "steam", "source": "test"},
        {"key": "product:WATER", "factor": "wastewater", "source": "test"},
    ],
}


def _factor(id_: str, unit: str, gwp: float) -> dict:
    return {
        "id": id_,
        "unit": unit,
        "values": {"gwp": gwp},
        "status": "ASSUMED",
        "source": "test",
        "year": 2025,
    }


FACTORS = {
    "schema": "cheme/lca/v1",
    "kind": "lca_factors",
    "categories": [{"id": "gwp", "unit": "kg CO2-eq"}],
    "factors": [
        _factor("feed", "kg", 0.5),
        _factor("steam", "MJ", 0.07),
        _factor("steam-2050", "MJ", 0.01),
        _factor("wastewater", "t", 1.0),
        _factor("steel", "t", 2000),
        _factor("pipe", "m", 20),
        _factor("concrete", "m3", 300),
    ],
}
TAKEOFF = [
    MtoRow("steel", "HEB300", spec="S355", group="rack", count=12, quantity=10, unit="t"),
    MtoRow("pipe", "pipe", dn=100, pipe_class="PN16", count=3, quantity=100, unit="m"),
    MtoRow("concrete", "plinth", group="equipment", count=4, quantity=50, unit="m3"),
    MtoRow("elbow", "elbow 90", dn=100, pipe_class="PN16", count=4, quantity=4, unit="ea"),
]
EQUIPMENT = {
    "equipment": [
        {
            "tag": "V-1",
            "type": "Vessel",
            "material": "SS 304",
            "dimensions": {"diameter": 2, "height": 5, "weight": 5},
        },
        {
            "tag": "P-1",
            "type": "CentrifugalPump",
            "material": "CS",
            "dimensions": {"length": 1, "width": 0.5, "height": 0.6},
        },
    ]
}
CONSTRUCTION = [
    {"id": "steel", "takeoff": "mto", "category": "steel", "factor": "steel", "source": "test"},
    {"id": "pipe", "takeoff": "mto", "category": "pipe", "factor": "pipe", "source": "test"},
    {
        "id": "concrete",
        "takeoff": "mto",
        "category": "concrete",
        "factor": "concrete",
        "source": "test",
    },
    {
        "id": "vessels-ss",
        "takeoff": "equipment",
        "equipment": {"material": "*SS*"},
        "factor": "steel",
        "source": "test",
    },
    {
        "id": "machines-cs",
        "takeoff": "equipment",
        "equipment": {"material": "CS*"},
        "factor": "steel",
        "source": "test",
    },
]


def _write(root: Path, scope: dict, factors: dict | None = None) -> None:
    (root / "lca").mkdir(exist_ok=True)
    (root / "lca" / "lca.yaml").write_text(yaml.safe_dump(scope, sort_keys=False))
    (root / "lca" / "factors.yaml").write_text(yaml.safe_dump(factors or FACTORS, sort_keys=False))


@pytest.fixture
def blocks(tmp_path: Path) -> Path:
    root = tmp_path / "blocks"
    shutil.copytree(EXAMPLE, root)
    _write(root, SCOPE)
    return root


@pytest.fixture
def built(blocks: Path) -> Path:
    """The plant with a take-off and an equipment list, and construction entries."""
    (blocks / "estimate").mkdir()
    (blocks / "estimate" / "mto.csv").write_text(mto_csv(TAKEOFF))
    (blocks / "equipment").mkdir()
    (blocks / "equipment" / "equipment-list.yaml").write_text(yaml.safe_dump(EQUIPMENT))
    scope = {
        **SCOPE,
        "operation": {"hours_per_year": 8000, "life_years": 20},
        "construction": CONSTRUCTION,
    }
    _write(blocks, scope)
    return blocks


def test_read_takeoff_round_trips() -> None:
    assert read_takeoff(mto_csv(TAKEOFF)) == TAKEOFF


def test_construction_amortised_per_functional_unit(built: Path) -> None:
    report = lca_report(built)
    assert report.loaded, [f.format() for f in report.findings]
    rows = {row.key: row for row in report.inventory.rows}
    steel = rows["construction:steel"]
    assert (steel.plant, steel.plant_unit, steel.unit) == (10000, "kg", "kg")
    assert steel.phase == "construction" and steel.streams == ("steel HEB300 S355 rack",)
    # 1 t of product out of 400 kg/h x 8000 h x 20 a
    scale = 1000 / (400 * 8000 * 20)
    assert steel.quantity == pytest.approx(10000 * scale)
    assert rows["construction:vessels-ss"].plant == 5000
    construction = report.totals(phase="construction")["gwp"]
    assert construction == pytest.approx((20000 + 2000 + 15000 + 10000) * scale)
    assert report.totals()["gwp"] == pytest.approx(1472 + construction)
    rules = {f.rule: f for f in report.findings}
    assert "elbow elbow 90 DN100 PN16 (4 ea)" in rules["cheme.lca-construction-unmapped"].message
    assert rules["cheme.lca-equipment-weight"].ids == ["P-1"]
    # never 0: the item without a weight and the row no entry counts are gaps of unknown amount
    gaps = {(g.key, g.reason) for g in report.gaps if g.category == "gwp"}
    assert ("no-weight:machines-cs/P-1", "no-weight") in gaps
    assert any(k.startswith("unmatched:elbow") and r == "unmatched" for k, r in gaps)
    assert all(g.quantity is None for g in report.gaps if g.reason in ("no-weight", "unmatched"))
    assert report.classification == "partial"
    markdown = results_markdown(report)
    assert "| gwp | no-weight:machines-cs/P-1 | unknown |" in markdown
    assert "By phase (baseline):" in markdown and "| construction:steel" in markdown


def test_a_cut_off_entry_is_a_limitation_not_a_gap(built: Path) -> None:
    scope = yaml.safe_load((built / "lca" / "lca.yaml").read_text())
    scope["construction"].append(
        {
            "id": "fittings",
            "takeoff": "mto",
            "category": "elbow",
            "cutoff": "fittings below 1 % of the steel mass (ISO 14044 cut-off)",
            "source": "test",
        }
    )
    _write(built, scope)
    report = lca_report(built)
    assert report.loaded, [f.format() for f in report.findings]
    assert not any(g.key.startswith("unmatched:elbow") for g in report.gaps)
    assert "construction:fittings" not in {r.key for r in report.inventory.rows}
    assert any(
        "cut off by the study's criteria: construction fittings" in x for x in report.limitations
    )


def test_an_absent_takeoff_is_a_gap_of_its_entries(built: Path) -> None:
    (built / "estimate" / "mto.csv").unlink()
    report = lca_report(built)
    assert report.loaded, [f.format() for f in report.findings]
    keys = {g.key for g in report.gaps if g.reason == "no-takeoff"}
    assert keys == {"no-takeoff:steel"} or "no-takeoff:steel" in keys
    assert report.classification == "partial"
    assert not any(f.rule == "cheme.lca-construction-empty" for f in report.findings)


def test_construction_needs_operation_and_inputs(built: Path) -> None:
    from pydantic import ValidationError

    from chemeascode.domains.assessment.lca.schemas import LcaFile

    with pytest.raises(ValidationError, match="construction needs operation"):
        LcaFile.model_validate({**SCOPE, "construction": CONSTRUCTION})
    (built / "estimate" / "mto.csv").unlink()
    rules = {f.rule for f in lca_report(built).findings}
    # an absent input is a gap of its entries (no-takeoff), not an "empty" entry
    assert "cheme.lca-construction-input" in rules and "cheme.lca-construction-empty" not in rules


def test_construction_unit_mismatch(built: Path) -> None:
    scope = yaml.safe_load((built / "lca" / "lca.yaml").read_text())
    scope["construction"][0]["factor"] = "pipe"
    _write(built, scope)
    report = lca_report(built)
    assert any(f.rule == "cheme.lca-factor-unit" for f in report.findings)


def test_factor_scenario(blocks: Path) -> None:
    scope = {
        **SCOPE,
        "scenarios": [
            {"id": "2050", "factors": {"steam": "steam-2050"}, "source": "test"},
            {"id": "same", "source": "test"},
        ],
    }
    _write(blocks, scope)
    report = lca_report(blocks)
    assert report.scenarios == ["baseline", "2050", "same"]
    assert report.totals("2050")["gwp"] == pytest.approx(1250 + 875 * 3.6 * 0.01 + 1.5)
    assert report.totals("same") == report.totals()
    assert any(f.rule == "cheme.lca-scenario-empty" for f in report.findings)
    csv = results_csv(report)
    assert csv.splitlines()[0].startswith("scenario,category,")
    assert "2050,gwp,kg CO2-eq,total" in csv
    assert "| Gwp" not in results_markdown(report)
    scope["scenarios"][0]["factors"] = {"steam": "nope"}
    _write(blocks, scope)
    assert not lca_report(blocks).loaded


def test_backend_schema() -> None:
    from pydantic import ValidationError

    from chemeascode.domains.assessment.lca.schemas import FlowMap, LcaFile

    with pytest.raises(ValidationError, match="needs brightway"):
        LcaFile.model_validate({**SCOPE, "backend": "brightway"})
    with pytest.raises(ValidationError, match="activity or biosphere"):
        FlowMap.model_validate(
            {
                "key": "feed:X",
                "activity": {"database": "d", "name": "n"},
                "biosphere": {"database": "b", "name": "n"},
                "source": "test",
            }
        )
    with pytest.raises(ValidationError, match="free, emission, resource and missing take no"):
        FlowMap.model_validate({"key": "feed:X", "free": True, "factor": "f", "source": "test"})
    both = FlowMap.model_validate(
        {
            "key": "feed:X",
            "factor": "f",
            "activity": {"database": "d", "name": "n"},
            "source": "test",
        }
    )
    assert both.factor == "f" and both.activity.name == "n"


def test_brightway_missing_is_a_finding(blocks: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def unavailable(*args, **kwargs):
        raise brightway.BrightwayUnavailable("Brightway is not installed: " + brightway.EXTRA)

    monkeypatch.setattr(brightway, "unit_scores", unavailable)
    scope = {
        **SCOPE,
        "backend": "brightway",
        "brightway": {"project": "p", "categories": [{"id": "gwp", "method": ["m"]}]},
        "flows": [
            {**f, "activity": {"database": "tech", "name": f["factor"]}} for f in SCOPE["flows"]
        ],
    }
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    assert report.findings[0].rule == "cheme.lca-brightway"
    assert "cheme-as-code[lca]" in report.findings[0].message


# -- Brightway ----------------------------------------------------------------------------------

needs_brightway = pytest.mark.skipif(
    not brightway.available(), reason="extra lca (bw2data, bw2calc) not installed"
)


@needs_brightway
def test_brightway_calls_close_their_sqlite_connections(monkeypatch):
    """bw2data opens its SQLite connections per thread and never closes them;
    a call from a worker thread (cheme serve) left them to the garbage collector, an
    unclosed-database ResourceWarning in whichever test collected them. Each call closes them
    now."""
    import gc
    import threading

    import bw2data as bd
    from bw2data.configuration import config

    caught: list[str] = []
    monkeypatch.setattr(sys, "unraisablehook", lambda u: caught.append(str(u.exc_value)))
    still_open: list[bool] = []

    def call() -> None:
        brightway.unit_scores("no-such-project", [("m",)], {}, {})
        databases = (bd.projects.db, *(db for _, db in config.sqlite3_databases))
        still_open.extend(not database.db.is_closed() for database in databases)

    worker = threading.Thread(target=call)
    worker.start()
    worker.join()
    del worker
    gc.collect()
    assert still_open and not any(still_open)
    assert not [c for c in caught if "unclosed database" in c]


PROJECT = textwrap.dedent(
    """
    import warnings
    warnings.simplefilter("ignore")
    import bw2data as bd

    bd.projects.set_current("plant-test")
    bd.Database("bio").write({
        ("bio", "co2"): {"name": "Carbon dioxide, fossil", "categories": ("air",),
                         "type": "emission", "unit": "kilogram", "CAS number": "000124-38-9"},
        ("bio", "co2-bio"): {"name": "Carbon dioxide, non-fossil", "categories": ("air",),
                             "type": "emission", "unit": "kilogram", "CAS number": "000124-38-9"},
        ("bio", "etoh"): {"name": "Ethanol", "categories": ("air",), "type": "emission",
                          "unit": "kilogram", "CAS number": "000064-17-5"},
        ("bio", "etoh-urban"): {"name": "Ethanol",
                                "categories": ("air", "urban air close to ground"),
                                "type": "emission", "unit": "kilogram",
                                "CAS number": "000064-17-5"},
    })

    def tech(name, feed, steam):
        bd.Database(name).write({
            (name, "feed"): {"name": "feedstock production", "reference product": "feedstock",
                             "location": "GLO", "unit": "kilogram", "exchanges": [
                {"input": (name, "feed"), "amount": 1, "type": "production"},
                {"input": ("bio", "co2"), "amount": feed, "type": "biosphere"}]},
            (name, "steam"): {"name": "market for heat, from steam", "reference product": "heat",
                              "location": "DE", "unit": "megajoule", "exchanges": [
                {"input": (name, "steam"), "amount": 1, "type": "production"},
                {"input": ("bio", "co2"), "amount": steam, "type": "biosphere"}]},
            (name, "steam-ch"): {"name": "market for heat, from steam",
                                 "reference product": "heat", "location": "CH",
                                 "unit": "megajoule", "exchanges": [
                {"input": (name, "steam-ch"), "amount": 1, "type": "production"}]},
            (name, "ww"): {"name": "treatment of wastewater", "reference product": "wastewater",
                           "location": "GLO", "unit": "cubic meter", "exchanges": [
                {"input": (name, "ww"), "amount": -1, "type": "production"}]},
            (name, "waste"): {"name": "treatment of aqueous waste", "reference product": "waste",
                              "location": "GLO", "unit": "kilogram", "exchanges": [
                {"input": (name, "waste"), "amount": -1, "type": "production"},
                {"input": ("bio", "co2"), "amount": 2, "type": "biosphere"}]},
            (name, "grid"): {"name": "Electricity, at grid, US", "type": "process",
                             "categories": ("Utilities", "Fossil Fuel Electric Power"),
                             "location": "US", "unit": "kilowatt hour", "exchanges": [
                {"input": (name, "grid"), "amount": 1, "type": "production"}]},
        })

    tech("tech", 0.3, 0.07)
    tech("tech-2050", 0.1, 0.02)
    method = bd.Method(("test", "gwp"))
    method.register(unit="kg CO2-eq")
    method.write([(("bio", "co2"), 1.0), (("bio", "etoh"), 2.0)])
    regional = bd.Method(("test", "regional"))
    regional.register(unit="kg CO2-eq")
    regional.write([(("bio", "co2"), 3.0, "DE"), (("bio", "co2"), 4.0, "GLO")])
    """
)


def _run(code: str, env_dir: Path, cwd: Path | None = None) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, "BRIGHTWAY2_DIR": str(env_dir)}
    return subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=cwd, check=False, capture_output=True, text=True
    )


@pytest.fixture(scope="module")
def bw_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not brightway.available():
        pytest.skip("extra lca (bw2data, bw2calc) not installed")
    path = tmp_path_factory.mktemp("brightway")
    built = _run(PROJECT, path)
    assert built.returncode == 0, built.stderr
    return path


def _bw_scope(**extra) -> dict:
    activity = {"database": "tech", "name": "feedstock production"}
    return {
        **SCOPE,
        "backend": "brightway",
        "brightway": {
            "project": "plant-test",
            "categories": [{"id": "gwp", "title": "Climate change", "method": ["test", "gwp"]}],
        },
        "flows": [
            {"key": "feed:FEED", "activity": activity, "source": "test"},
            {
                "key": "feed:STEAM",
                "activity": {
                    "database": "tech",
                    "name": "market for heat, from steam",
                    "location": "DE",
                },
                "source": "test",
            },
            {"key": "product:WATER", "emission": True, "source": "test"},
            {
                "key": "emission:ETOH",
                "biosphere": {"database": "bio", "name": "Ethanol", "categories": ["air"]},
                "source": "test",
            },
            {"key": "emission:H2O", "free": True, "source": "test"},
        ],
        **extra,
    }


def _report(root: Path, env_dir: Path) -> dict:
    code = (
        "import json, sys\n"
        "from chemeascode.domains.assessment.lca.report import lca_report\n"
        f"r = lca_report({str(root)!r})\n"
        "print(json.dumps({'loaded': r.loaded, 'totals': {s: r.totals(s) for s in r.scenarios},"
        " 'findings': [f.format() for f in r.findings], 'categories':"
        " [c.unit for c in r.categories], 'basis': sorted({i.basis for i in r.impacts}),"
        " 'gaps': r.payload()['gaps'], 'impacts': r.payload()['impacts'],"
        " 'classification': r.classification}))\n"
    )
    done = _run(code, env_dir)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_brightway
def test_brightway_backend_by_hand(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _bw_scope())
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    assert result["categories"] == ["kg CO2-eq"]
    etoh = 600 * 0.0333333 * 2.5
    # 2500 kg x 0.3 + 875 kWh x 3.6 MJ/kWh x 0.07 + ETOH x 2.0 (method CF)
    assert result["totals"]["baseline"]["gwp"] == pytest.approx(750 + 220.5 + etoh * 2, rel=1e-6)
    assert "feedstock production [GLO]" in result["basis"]


@needs_brightway
def test_brightway_scenario_swaps_databases(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope(
        scenarios=[{"id": "2050", "databases": {"tech": "tech-2050"}, "source": "premise"}]
    )
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    etoh = 600 * 0.0333333 * 2.5
    assert result["totals"]["2050"]["gwp"] == pytest.approx(250 + 63 + etoh * 2, rel=1e-6)


@needs_brightway
def test_brightway_problems(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope()
    scope["flows"][1]["activity"].pop("location")  # DE and CH
    scope["flows"].append(
        {
            "key": "feed:XX",
            "activity": {"database": "tech", "name": "nothing"},
            "source": "test",
        }
    )
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    text = "\n".join(result["findings"])
    assert "2 activities 'market for heat, from steam'" in text
    assert "lca-flow-unknown" in text  # feed:XX is no flow of the plant
    scope = _bw_scope()
    scope["flows"][0] = {
        "key": "feed:FEED",
        "activity": {"database": "tech", "name": "treatment of wastewater"},
        "source": "test",
    }
    _write(blocks, scope)
    assert "lca-activity-unit" in "\n".join(_report(blocks, bw_dir)["findings"])
    scope = _bw_scope()
    scope["brightway"]["project"] = "nope"
    _write(blocks, scope)
    assert "no Brightway project 'nope'" in "\n".join(_report(blocks, bw_dir)["findings"])


@needs_brightway
def test_lca_search(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _bw_scope())
    code = (
        "from typer.testing import CliRunner\n"
        "from chemeascode.interfaces.cli import app\n"
        "r = CliRunner().invoke(app, ['assess', 'lca-search', 'steam'])\n"
        "print(r.exit_code); print(r.output)\n"
    )
    done = _run(code, bw_dir, cwd=blocks)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("0")
    assert "name: 'market for heat, from steam', reference_product: heat, location: DE" in (
        done.stdout
    )
    assert "# per megajoule" in done.stdout


@needs_brightway
def test_brightway_treatment_is_a_burden(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope()
    scope["flows"][2] = {
        "key": "product:WATER",
        "activity": {"database": "tech", "name": "treatment of aqueous waste"},
        "source": "test",
    }
    scope["flows"] = scope["flows"][:3]
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    # 1500 kg treated x 2 kg CO2 per kg treated: a burden, not a credit
    assert result["totals"]["baseline"]["gwp"] == pytest.approx(750 + 220.5 + 3000, rel=1e-6)


@needs_brightway
def test_brightway_regionalised_method(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope()
    scope["brightway"]["categories"] = [{"id": "gwp", "method": ["test", "regional"]}]
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    # the global CF (4.0) of CO2; ethanol has none in this method: outside its scope
    assert result["totals"]["baseline"]["gwp"] == pytest.approx(4 * (750 + 220.5), rel=1e-6)
    assert any("lca-biosphere-uncharacterised" in f for f in result["findings"])
    gaps = [g for g in result["gaps"] if g["scenario"] == "baseline"]
    assert [(g["category"], g["reason"]) for g in gaps] == [("gwp", "biosphere-uncharacterised")]
    assert gaps[0]["quantity"] > 0
    assert not [
        i for i in result["impacts"] if i["key"] == gaps[0]["key"] and i["category"] == "gwp"
    ]
    # outside the method's scope (an LCIA convention), not a gap: the result is not partial
    assert result["classification"] != "partial"
    # the ethanol flow (bio) is outside the method: only the tech database contributes
    assert {i["source_id"] for i in result["impacts"]} == {"brightway:plant-test/tech"}


@needs_brightway
def test_lca_search_tells_activities_with_categories_from_flows(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _bw_scope())
    code = (
        "from typer.testing import CliRunner\n"
        "from chemeascode.interfaces.cli import app\n"
        "r = CliRunner().invoke("
        "app, ['assess', 'lca-search', 'Electricity', '--database', 'tech'])\n"
        "print(r.output)\n"
        "r = CliRunner().invoke(app, ['assess', 'lca-search', 'Ethanol'])\n"
        "print(r.output)\n"
    )
    done = _run(code, bw_dir, cwd=blocks)
    assert done.returncode == 0, done.stderr
    assert "{activity: {database: tech, name: 'Electricity, at grid, US'" in done.stdout
    assert "{biosphere: {database: bio, name: Ethanol, categories: [air]}}" in done.stdout


def test_findings_are_not_repeated_per_scenario(blocks: Path) -> None:
    factors = json.loads(json.dumps(FACTORS))
    factors["categories"].append({"id": "acid", "unit": "mol H+-eq"})
    scope = {
        **SCOPE,
        "scenarios": [
            {"id": "a", "factors": {"steam": "steam-2050"}, "source": "test"},
            {"id": "b", "factors": {"steam": "steam-2050"}, "source": "test"},
        ],
    }
    _write(blocks, scope, factors)
    report = lca_report(blocks)
    lacking = [f for f in report.findings if f.rule == "cheme.lca-factor-category"]
    assert len(lacking) == len({f.message for f in lacking})


@needs_brightway
def test_brightway_elementary_by_cas(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope()
    scope["brightway"]["biosphere"] = "bio"
    scope["flows"][3] = {
        "key": "emission:ETOH",
        "elementary": {"compartment": "air", "origin": "fossil"},
        "source": "test",
    }
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    etoh = 600 * 0.0333333 * 2.5
    # the unspecified air compartment's ethanol (CF 2.0), found by CAS 64-17-5
    assert result["totals"]["baseline"]["gwp"] == pytest.approx(750 + 220.5 + etoh * 2, rel=1e-6)
    assert "Ethanol ['air']" in result["basis"]
    scope["brightway"].pop("biosphere")
    _write(blocks, scope)
    assert "brightway.biosphere names no" in "\n".join(_report(blocks, bw_dir)["findings"])


def _report_full(root: Path, env_dir: Path) -> dict:
    code = (
        "import json\n"
        "from chemeascode.domains.assessment.lca.report import lca_report, manifest\n"
        f"r = lca_report({str(root)!r})\n"
        "print(json.dumps({'loaded': r.loaded, 'findings': [f.format() for f in r.findings],"
        " 'rules': [f.rule for f in r.findings], 'publication': r.publication,"
        " 'publishable': r.publishable, 'restricted_by': r.restricted_by,"
        " 'manifest': manifest(r) if r.loaded else None}))\n"
    )
    done = _run(code, env_dir)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_brightway
def test_brightway_results_are_restricted_and_named_databases_unverified(
    blocks: Path, bw_dir: Path
) -> None:
    _write(blocks, _bw_scope())
    result = _report_full(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    assert result["publication"] == "restricted" and not result["publishable"]
    assert result["restricted_by"] == ["brightway:plant-test/bio", "brightway:plant-test/tech"]
    assert "cheme.lca-brightway-unverified" in result["rules"]
    background = result["manifest"]["background"]
    assert background["project"] == "plant-test"
    assert background["databases"]["tech"]["nodes"] > 0
    assert set(background["databases"]["tech"]) == {"provider", "version", "system_model", "nodes"}
    assert "bw2data" in result["manifest"]["software"]


@needs_brightway
def test_brightway_database_identity_is_checked(blocks: Path, bw_dir: Path) -> None:
    scope = _bw_scope()
    scope["brightway"]["expect"] = {"tech": {"provider": "ecoinvent", "version": "3.10"}}
    _write(blocks, scope)
    result = _report_full(blocks, bw_dir)
    assert not result["loaded"]
    assert result["rules"].count("cheme.lca-brightway-identity") == 2
    assert any(
        "database tech records version '(none)', the study expects '3.10'" in f
        for f in result["findings"]
    )


@needs_brightway
def test_an_open_brightway_database_can_be_public(
    blocks: Path, bw_dir: Path, tmp_path: Path
) -> None:
    # a copy of the project whose databases record their identity
    marked = tmp_path / "marked"
    shutil.copytree(bw_dir, marked)
    done = _run(
        "import bw2data as bd\n"
        "bd.projects.set_current('plant-test')\n"
        "for name in ('tech', 'bio'):\n"
        "    bd.databases[name]['provider'] = 'open-test'\n"
        "    bd.databases[name]['version'] = '1'\n"
        "bd.databases.flush()\n",
        marked,
    )
    assert done.returncode == 0, done.stderr
    scope = _bw_scope()
    scope["brightway"]["expect"] = {
        "tech": {"provider": "open-test", "version": "1"},
        "bio": {"provider": "open-test"},
    }
    scope["brightway"]["publication"] = "public"
    _write(blocks, scope)
    result = _report_full(blocks, marked)
    assert result["loaded"], result["findings"]
    assert "cheme.lca-brightway-unverified" not in result["rules"]
    assert result["publishable"]
    assert result["manifest"]["background"]["databases"]["tech"]["version"] == "1"
    methods = result["manifest"]["background"]["methods"]
    assert methods["test | gwp"].startswith("sha256:")  # the CF set is fingerprinted


def _profile(id_: str, entries: list) -> dict:
    return {
        "schema": "cheme/lca/v1",
        "kind": "lca_mapping_profile",
        "id": id_,
        "provider": "test",
        "version": "1",
        "system_model": "cutoff",
        "entries": entries,
    }


@needs_brightway
def test_a_provider_profile_maps_what_flows_leave_unmapped(blocks: Path, bw_dir: Path) -> None:
    feedstock = {"database": "tech", "name": "feedstock production"}
    steam = {"database": "tech", "name": "market for heat, from steam", "location": "CH"}
    profile = _profile(
        "tech-cutoff",
        [
            {"match": {"key": "feed:FEED"}, "activity": feedstock, "source": "test profile"},
            {"match": {"key": "feed:STEAM"}, "activity": steam, "source": "test profile"},
        ],
    )
    (blocks / "lca" / "mapping-profiles").mkdir(parents=True)
    path = blocks / "lca" / "mapping-profiles" / "tech.yaml"
    path.write_text(yaml.safe_dump(profile))
    scope = _bw_scope()
    scope["brightway"]["mapping_profiles"] = ["lca/mapping-profiles/tech.yaml"]
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "feed:FEED"]
    # the study's own entry wins over the profile, also a declared missing:
    scope["flows"][0] = {"key": "feed:STEAM", "missing": "steam not chosen yet", "source": "D-1"}
    _write(blocks, scope)
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    etoh = 600 * 0.0333333 * 2.5
    assert result["totals"]["baseline"]["gwp"] == pytest.approx(750 + etoh * 2, rel=1e-6)
    used = [f for f in result["findings"] if "cheme.lca-mapping-profile-used" in f]
    assert used and "feed:FEED (tech-cutoff)" in used[0] and "feed:STEAM" not in used[0]
    assert {g["key"] for g in result["gaps"]} == {"feed:STEAM"}
    # the profile is an input of the run: changing it makes the results stale
    code = (
        "import json\n"
        "from chemeascode.domains.assessment.lca.report import lca_report, manifest\n"
        f"print(json.dumps(manifest(lca_report({str(blocks)!r}))['inputs']))\n"
    )
    done = _run(code, bw_dir)
    assert done.returncode == 0, done.stderr
    assert "lca/mapping-profiles/tech.yaml" in json.loads(done.stdout.strip().splitlines()[-1])


def test_a_profile_that_does_not_load_is_an_error(blocks: Path) -> None:
    scope = _bw_scope()
    scope["brightway"]["mapping_profiles"] = ["lca/mapping-profiles/none.yaml"]
    _write(blocks, scope)
    report = lca_report(blocks)
    assert not report.loaded
    (error,) = [f for f in report.findings if f.rule == "cheme.lca-mapping-profile"]
    assert "no mapping profile lca/mapping-profiles/none.yaml" in error.message and error.hint
    (blocks / "lca" / "mapping-profiles").mkdir(parents=True)
    (blocks / "lca" / "mapping-profiles" / "none.yaml").write_text(
        yaml.safe_dump(_profile("x", [{"match": {}, "activity": {}, "source": "x"}]))
    )
    report = lca_report(blocks)
    assert any("does not load" in f.message for f in report.findings if f.level == "error")


def test_profile_matching_by_key_then_utility(tmp_path: Path) -> None:
    from types import SimpleNamespace as NS

    from chemeascode.domains.assessment.lca.mapping_profiles import profile_flows
    from chemeascode.domains.assessment.lca.schemas import LcaFile, ProfileMatch

    def node(id_: str, kind: str | None = None):
        return NS(id=id_, utility=NS(kind=kind) if kind else None)

    process = NS(
        flowsheet=NS(
            feeds=[
                node("POWER", "electricity"),
                node("AUX", "electricity"),
                node("CW", "cooling_water"),
            ],
            products=[
                node("PROD"),
                node("BY"),
                node("EXPORT", "electricity"),
                node("CWR", "cooling_water"),
            ],
        )
    )
    grid = {"database": "db", "name": "market for electricity"}
    special = {"database": "db", "name": "electricity, own turbine"}
    first = _profile(
        "a",
        [
            {"match": {"utility": "electricity"}, "activity": grid, "source": "grid"},
            {"match": {"key": "feed:AUX"}, "activity": special, "source": "own turbine"},
        ],
    )
    second = _profile(
        "b",
        [
            {"match": {"utility": "cooling_water"}, "activity": grid, "source": "pumps"},
            {"match": {"key": "product:BY"}, "activity": grid, "source": "never: a co-product"},
            {"match": {"key": "feed:POWER"}, "activity": special, "source": "never: a wins"},
        ],
    )
    (tmp_path / "a.yaml").write_text(yaml.safe_dump(first))
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(second))
    data = {
        **_bw_scope(),
        "allocation": {"method": "mass", "coproducts": ["BY"]},
        "flows": [],
        "brightway": {**_bw_scope()["brightway"], "mapping_profiles": ["a.yaml", "b.yaml"]},
    }
    added, files, findings = profile_flows(
        tmp_path, LcaFile.model_validate(data), process, "lca/lca.yaml"
    )
    by_key = {f.key: f for f in added}
    # products are matched by key only: an electricity product is an export, not a supply
    assert sorted(by_key) == ["feed:AUX", "feed:CW", "feed:POWER"]
    assert by_key["feed:POWER"].activity.name == "market for electricity"  # profile a first
    assert by_key["feed:AUX"].activity.name == "electricity, own turbine"  # a key before a kind
    assert by_key["feed:CW"].source == "mapping profile b (b.yaml): pumps"
    assert files == ["a.yaml", "b.yaml"]
    (info,) = findings
    assert info.rule == "cheme.lca-mapping-profile-used" and info.level == "info"
    # a gate-to-gate study takes no supply chain from a profile
    added, _, _ = profile_flows(
        tmp_path,
        LcaFile.model_validate({**data, "boundary": "gate-to-gate"}),
        process,
        "lca/lca.yaml",
    )
    assert added == []
    # a profile of another system model or release than the study's, an entry for no flow
    second["system_model"] = "apos"
    second["entries"].append({"match": {"key": "feed:NONE"}, "activity": grid, "source": "x" * 3})
    (tmp_path / "b.yaml").write_text(yaml.safe_dump(second))
    data["brightway"]["expect"] = {"db": {"provider": "test", "version": "2"}}
    _, _, findings = profile_flows(tmp_path, LcaFile.model_validate(data), process, "lca/lca.yaml")
    fit = {f.file: f for f in findings if f.rule == "cheme.lca-mapping-profile-fit"}
    assert "version 1, brightway.expect of db: 2" in fit["a.yaml"].message
    assert "system model apos, the study's cutoff" in fit["b.yaml"].message
    assert "entries for no flow of the flowsheet: feed:NONE" in fit["b.yaml"].message
    # a utility kind is one of the flowsheet's
    with pytest.raises(ValueError, match="utility"):
        ProfileMatch(utility="electricty")
    # unused under the factors backend
    _, _, (unused,) = profile_flows(
        tmp_path, LcaFile.model_validate({**data, "backend": "factors"}), process, "lca/lca.yaml"
    )
    assert unused.rule == "cheme.lca-mapping-profile-unused"


def _map(args: list[str], env_dir: Path, cwd: Path) -> tuple[int, str]:
    code = (
        "from typer.testing import CliRunner\n"
        "from chemeascode.interfaces.cli import app\n"
        f"r = CliRunner().invoke(app, {['assess', 'lca-map', *args]!r})\n"
        "print(r.exit_code); print(r.output)\n"
    )
    done = _run(code, env_dir, cwd=cwd)
    assert done.returncode == 0, done.stderr
    code_, _, output = done.stdout.partition("\n")
    return int(code_), output


def _open_scope() -> dict:
    """feed:FEED unmapped, feed:STEAM declared missing."""
    scope = _bw_scope()
    scope["flows"] = [f for f in scope["flows"] if f["key"] != "feed:FEED"]
    scope["flows"][0] = {"key": "feed:STEAM", "missing": "no steam background yet", "source": "D-1"}
    return scope


@needs_brightway
def test_lca_map_is_a_dry_run_with_numbered_candidates(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _open_scope())
    path = blocks / "lca" / "lca.yaml"
    path.write_text("# the study's own comment\n" + path.read_text())
    before = path.read_bytes()
    status, output = _map([], bw_dir, blocks)
    assert status == 0, output
    assert path.read_bytes() == before  # nothing written
    assert "feed:FEED (Aqueous feed, per kg): no background" in output
    assert "feed:STEAM (LP steam, per kWh): missing: no steam background yet" in output
    # the title finds nothing, the key's id does: the query is shown
    assert "query: 'STEAM' in project 'plant-test'" in output
    assert (
        "1. {activity: {database: tech, name: 'market for heat, from steam', "
        "reference_product: heat, location: DE}}  # per megajoule"
    ) in output
    assert "dry run: nothing written" in output
    status, output = _map(["feed:FEED", "--query", "wastewater"], bw_dir, blocks)
    assert "not applicable: per 'cubic meter', the exchange is counted in kg" in output


@needs_brightway
def test_lca_map_applies_only_the_approved_candidates(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _open_scope())
    path = blocks / "lca" / "lca.yaml"
    path.write_text("# the study's own comment\n" + path.read_text())
    status, output = _map(["--apply", "feed:STEAM=1", "--source", "lca-map, D-2"], bw_dir, blocks)
    assert status == 0, output
    assert "mapped feed:STEAM: activity: {database: tech, name: 'market for heat, from steam'" in (
        output
    )
    text = path.read_text()
    assert text.startswith("# the study's own comment\n")
    data = yaml.safe_load(text)
    steam = next(f for f in data["flows"] if f["key"] == "feed:STEAM")
    assert steam == {
        "key": "feed:STEAM",
        "activity": {
            "database": "tech",
            "name": "market for heat, from steam",
            "reference_product": "heat",
            "location": "DE",
        },
        "source": "lca-map, D-2",
    }
    assert "feed:FEED" not in text  # not approved: still unmapped
    status, output = _map(
        ["feed:FEED", "--query", "feedstock", "--apply", "feed:FEED=1", "--source", "D-3"],
        bw_dir,
        blocks,
    )
    assert status == 0, output
    result = _report(blocks, bw_dir)
    assert result["loaded"], result["findings"]
    assert not [g for g in result["gaps"] if g["key"] in ("feed:FEED", "feed:STEAM")]


@needs_brightway
def test_lca_map_refuses_without_writing(blocks: Path, bw_dir: Path) -> None:
    _write(blocks, _open_scope())
    path = blocks / "lca" / "lca.yaml"
    before = path.read_bytes()
    status, output = _map(["--apply", "feed:STEAM=1"], bw_dir, blocks)
    assert status == 2 and "--apply needs --source" in output
    status, output = _map(["--apply", "feed:STEAM=9", "--source", "x" * 3], bw_dir, blocks)
    assert status == 1 and "no candidate 9 (4 found)" in output
    # a unit of another kind is refused, and so is the whole run: the good mapping is not written
    status, output = _map(
        [
            "feed:FEED",
            "--query",
            "wastewater",
            "--apply",
            "feed:FEED=1",
            "--source",
            "test",
        ],
        bw_dir,
        blocks,
    )
    assert status == 1 and "cheme.lca-map-refused [feed:FEED]" in output
    # --query searches for one exchange only: the candidates of another were never listed
    status, output = _map(
        ["feed:STEAM", "--query", "feedstock", "--apply", "feed:FEED=1", "--source", "test"],
        bw_dir,
        blocks,
    )
    assert status == 2 and "--query searches for one exchange" in output
    status, output = _map(
        ["--apply", "feed:STEAM=1", "--apply", "feed:STEAM=2", "--source", "test"], bw_dir, blocks
    )
    assert status == 2 and "given twice" in output
    status, output = _map(["--apply", "product:PROD=1", "--source", "test"], bw_dir, blocks)
    assert status == 1 and "cheme.lca-map-key [product:PROD]" in output  # a co-product
    assert path.read_bytes() == before


def test_lca_map_edit_keeps_the_file_and_checks_itself() -> None:
    from chemeascode.domains.assessment.lca.mapping import ApplyRefused, apply

    activity = {"database": "db", "name": "steam production", "location": "DE"}
    text = textwrap.dedent(
        """\
        schema: cheme/lca/v1
        kind: lca
        functional_unit: {product: PROD, amount: 1, unit: t}  # one tonne
        allocation:
          method: none
        operation: {hours_per_year: 8000, life_years: 20}
        flows:
          # utilities
          - missing: >-
              no open background
              for LP steam
            key: feed:STEAM
            source: D-1  # the decision
          - key: feed:FEED
            factor: feed
            source: test

        # construction follows
        construction:
          - id: steel
            takeoff: mto
            category: steel
            missing: none yet
            source: D-9
        """
    )
    new = apply(text, "feed:STEAM", activity, "D-2")
    assert "functional_unit: {product: PROD, amount: 1, unit: t}  # one tonne" in new
    assert "# utilities\n  - activity:\n      database: db\n" in new
    assert yaml.safe_load(new)["flows"][0] == {
        "activity": activity,
        "key": "feed:STEAM",
        "source": "D-2",
    }
    new = apply(new, "feed:WATER", activity, "D-3")
    assert new.index("key: feed:WATER") < new.index("# construction follows")
    assert yaml.safe_load(new)["flows"][2]["key"] == "feed:WATER"
    new = apply(new, "construction:steel", activity, "D-4")
    assert yaml.safe_load(new)["construction"][0]["activity"] == activity
    assert new.endswith("    source: D-4\n")
    with pytest.raises(ApplyRefused, match="not declared missing"):
        apply(new, "feed:FEED", activity, "D-5")
    with pytest.raises(ApplyRefused, match="no construction: entry"):
        apply(new, "construction:pipe", activity, "D-5")
    inline = "schema: cheme/lca/v1\nkind: lca\nfunctional_unit: {product: P, amount: 1, unit: t}\n"
    inline += "flows: [{key: feed:A, missing: x, source: y}]\n"
    assert yaml.safe_load(apply(inline, "feed:A", activity, "D-5"))["flows"][0]["activity"]
    with pytest.raises(ApplyRefused, match="flow style"):
        apply(inline, "feed:Z", activity, "D-5")  # a new entry into a flow-style list
    with pytest.raises(ApplyRefused, match="only feed"):
        apply(text, "emission:CO2", activity, "D-5")
    head = "schema: cheme/lca/v1\nkind: lca\nfunctional_unit: {product: P, amount: 1, unit: t}\n"
    # a flow-style entry, as the template's README writes them
    flow = head + "flows:\n  - {key: feed:B, missing: none yet, source: D-1}  # B\n"
    new = apply(flow, "feed:B", activity, "D-7")
    assert new.endswith(
        "  - {key: 'feed:B', activity: {database: db, name: steam production, "
        "location: DE}, source: D-7}  # B\n"
    )
    # CRLF stays CRLF; a comment after the source stays; non-ASCII is written as such
    crlf = head + "flows:\r\n-   key: feed:C\r\n    missing: x\r\n    source: D-1  # why\r\n"
    new = apply(crlf, "feed:C", activity, "Prüfung")
    assert "\n" not in new.replace("\r\n", "")
    assert "    source: Prüfung  # why\r\n" in new
    # another dash indent, and no newline at the end
    new = apply(crlf.rstrip("\r\n"), "feed:D", activity, "D-8")
    assert "\r\n-   key: feed:D\r\n" in new or "\r\n- key: feed:D\r\n" in new
    assert yaml.safe_load(new)["flows"][1]["key"] == "feed:D"
    for empty in ("flows:\n", "flows: []\n"):
        new = apply(head + empty, "feed:E", activity, "D-9")
        assert yaml.safe_load(new)["flows"] == [
            {"key": "feed:E", "activity": activity, "source": "D-9"}
        ]
    with pytest.raises(ApplyRefused, match="one line"):
        apply(head, "feed:F", activity, "two\nlines")
    # no flows: yet
    new = apply(head + "allocation: {method: none}\n", "feed:A", activity, "D-6")
    assert yaml.safe_load(new)["flows"] == [
        {"key": "feed:A", "activity": activity, "source": "D-6"}
    ]
