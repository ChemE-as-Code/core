"""The material take-off and the estimate (``domains/assessment``): counts against a small model
counted by hand, the factor method, the gate ``kind: mto``, ``cheme assess`` and
``GET /api/mto``."""

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.assessment.estimate import (
    RATES_FILE,
    estimate,
    estimate_csv,
    estimate_report,
)
from chemeascode.domains.assessment.gates import mto_gate
from chemeascode.domains.assessment.mto import (
    MTO_CSV,
    model_takeoff,
    mto_csv,
    mto_markdown,
    mto_report,
    section_masses,
    take_off,
)
from chemeascode.domains.assessment.schemas import RateFile
from chemeascode.foundation.schemas.checks import Check
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE
from chemeascode.interfaces.cli import app
from tests.conftest import git

runner = CliRunner()
TEMPLATE_RATES = (
    Path(__file__).resolve().parents[1] / "src/chemeascode/templates/project/estimate/rates.yaml"
)


def _pipe(pid, dn, points, cls="PN16", insulation=0.0, segment=None, od=None, jacket=None):
    pipe = {
        "id": f"P-01/{pid}",
        "line": pid,
        "segment": segment or pid,
        "dn": dn,
        "od": od if od is not None else {25: 0.0337, 50: 0.0603, 80: 0.0889, 100: 0.1143}[dn],
        "insulation_mm": insulation,
        "class": {"code": cls},
        "points": points,
        "length": 0.0,
    }
    if jacket:
        pipe["jacket"] = jacket
    return pipe


def _flange_parts(iid, *names):
    return [{"id": f"P-01/{iid}/{n}", "kind": "cylinder", "material": "flange"} for n in names]


def small_model() -> dict:
    """A model small enough to count by hand (see the expected values in the tests).

    Pipes: P1 DN100 insulated 50 mm, (0,0,1) -> (5,0,1) -> (5,4,1), 9 m, one elbow inside;
    P2 DN100 (5,4,1) -> (10,4,1), 5 m, meets P1 at a right angle (an elbow between pipes);
    P3 DN50 from (2,0,1) on P1's run, up 2 m and 3 m north (a tee on P1, one elbow);
    P4 DN80 PN40 (10,4,1) -> (12,4,1), on from P2 (a reducer 100 x 80), ends at nozzle E-1/N1;
    P5 DN100 (0,0,1) -> (-3,0,1) -> (-5,2,1), a 45 degree bend;
    P6 DN25 (0,0,1) -> (0,-2,1): three ends at (0,0,1) are a reducing tee 100 x 25.
    """
    s2 = math.sqrt(2)
    pipes = [
        _pipe("P1", 100, [[0, 0, 1], [5, 0, 1], [5, 4, 1]], insulation=50.0, jacket="cold"),
        _pipe("P2", 100, [[5, 4, 1], [10, 4, 1]]),
        _pipe("P3", 50, [[2, 0, 1], [2, 0, 3], [2, 3, 3]]),
        _pipe("P4", 80, [[10, 4, 1], [12, 4, 1]], cls="PN40"),
        _pipe("P5", 100, [[0, 0, 1], [-3, 0, 1], [-3 - s2, s2, 1]]),
        _pipe("P6", 25, [[0, 0, 1], [0, -2, 1]]),
    ]
    inline = [
        {
            "id": "P-01/V1",
            "kind": "valve",
            "dexpi_class": "BallValve",
            "pipe": "P-01/P2",
            "segment": "P2",
            "point": [7, 4, 1],
            "refs": {"segments": ["P2"]},
            "parts": _flange_parts("V1", "flange-1", "flange-2", "body", "handwheel"),
        },
        {
            "id": "P-01/PSV1",
            "kind": "safety_valve",
            "dexpi_class": "SpringLoadedGlobeSafetyValve",
            "pipe": "P-01/P3",
            "segment": "P3",
            "point": [2, 3, 3],
            "refs": {"segments": ["P3", "P6"]},
            "parts": _flange_parts("PSV1", "flange-1", "outlet-flange", "bonnet"),
        },
        {  # no parts: a check valve has two flanges
            "id": "P-01/CV1",
            "kind": "check_valve",
            "dexpi_class": "SwingCheckValve",
            "pipe": "P-01/P5",
            "segment": "P5",
            "point": [-1, 0, 1],
            "refs": {"segments": ["P5"]},
        },
        {  # the reducer at the joint of P2 and P4 is the one the joint counts
            "id": "P-01/R1",
            "kind": "reducer",
            "dexpi_class": "ConcentricReducer",
            "pipe": "P-01/P2",
            "segment": "P2",
            "point": [10, 4, 1],
            "refs": {"segments": ["P2", "P4"]},
        },
        {
            "id": "P-01/SL1",
            "kind": "silencer",
            "dexpi_class": "Silencer",
            "pipe": "P-01/P6",
            "segment": "P6",
            "point": [0, -2, 1],
            "refs": {"segments": ["P6"]},
        },
    ]
    equipment = [
        {
            "id": "E-1",
            "tag": "E-1",
            "nozzles": [
                {"id": "E-1/N1", "dn": 80, "point": [12, 4, 1]},
                {"id": "E-1/N2", "dn": 50, "point": [50, 50, 50]},  # not piped
            ],
            "parts": [
                {"id": "E-1/body", "kind": "box", "material": "shell", "size": [1, 1, 1]},
                {
                    "id": "E-1/plinth",
                    "kind": "box",
                    "material": "concrete",
                    "centre": [0, 0, 0],
                    "size": [2, 1, 0.5],
                },
                {
                    "id": "E-1/foundation",
                    "kind": "cylinder",
                    "material": "concrete",
                    "lod": 2,
                    "start": [0, 0, 0],
                    "end": [0, 0, 0.5],
                    "radius": 1.0,
                },
            ],
        }
    ]

    def member(mid, section, length, material="steel"):
        return {
            "id": mid,
            "kind": "member",
            "material": material,
            "section": section,
            "start": [0, 0, 0],
            "end": [0, 0, length],
            "profile": [0.3, 0.3],
        }

    structures = [
        {
            "id": "S-1",
            "parts": [
                member("S-1/col-0-0", "HEB300", 6.0),
                member("S-1/col-1-0", "HEB 300", 4.0),  # the same section, written apart
                member("S-1/odd", "XYZ1", 3.0),  # no mass per metre: left out, reported
                {
                    "id": "S-1/L1/grating",
                    "kind": "box",
                    "material": "grating",
                    "size": [6, 4, 0.03],
                },
            ],
            "stairs": [
                {
                    "id": "S-1/st1",
                    "parts": [
                        member("S-1/st1/stringer-a", "C200", 4.0),
                        {
                            "id": "S-1/st1/tread-1",
                            "kind": "box",
                            "material": "grating",
                            "size": [1, 0.3, 0.03],
                        },
                        {
                            "id": "S-1/st1/tread-2",
                            "kind": "box",
                            "material": "grating",
                            "size": [1, 0.3, 0.03],
                        },
                    ],
                }
            ],
        }
    ]
    platforms = [
        {
            "id": "C-1/platform-1",
            "parts": [
                {
                    "id": "C-1/platform-1/grating",
                    "kind": "annulus",
                    "material": "grating",
                    "centre": [0, 0, 5],
                    "radius": 1.0,
                    "radius_end": 2.0,
                    "depth": 0.03,
                    "arc_deg": [0, 180],
                }
            ],
        }
    ]
    areas = [
        {
            "id": "TANKS",
            "kind": "bund",
            "parts": [
                {
                    "id": "TANKS/wall-north",
                    "kind": "box",
                    "material": "concrete",
                    "size": [10, 0.3, 1.0],
                }
            ],
        }
    ]
    return {
        "schema": "cheme/layout_model/v1",
        "kind": "layout_model",
        "provenance": {"output_sha256": "abc"},
        "pipes": pipes,
        "inline": inline,
        "equipment": equipment,
        "structures": structures,
        "platforms": platforms,
        "areas": areas,
    }


def _rows(takeoff, category):
    return {
        (r.item, r.dn, r.dn2, r.pipe_class, r.spec, r.group): r
        for r in takeoff.rows
        if r.category == category
    }


def _qty(takeoff, category):
    return {k: v.quantity for k, v in _rows(takeoff, category).items()}


# -- the take-off, counted by hand ---------------------------------------------------------------


def test_pipe_lengths_by_dn_class_and_insulation():
    t = take_off(small_model())
    s2 = math.sqrt(2)
    assert _qty(t, "pipe") == {
        ("pipe", 25.0, None, "PN16", "bare", ""): 2.0,
        ("pipe", 50.0, None, "PN16", "bare", ""): 5.0,
        ("pipe", 80.0, None, "PN40", "bare", ""): 2.0,
        ("pipe", 100.0, None, "PN16", "bare", ""): round(5 + 3 + 2, 3),
        ("pipe", 100.0, None, "PN16", "insulation 50 mm cold", ""): 9.0,
    }
    assert s2  # the 45 degree leg of P5 is exactly 2 m long
    assert _rows(t, "pipe")[("pipe", 100.0, None, "PN16", "bare", "")].count == 2
    insulation = _qty(t, "insulation")
    assert insulation == {
        ("pipe insulation", 100.0, None, "", "insulation 50 mm cold", "pipe"): round(
            math.pi * (0.1143 + 0.1) * 9, 3
        )
    }


def test_fittings_from_bends_and_topology():
    t = take_off(small_model())
    assert _qty(t, "elbow") == {
        ("elbow 90", 50.0, None, "PN16", "", ""): 1,  # inside P3
        ("elbow 90", 100.0, None, "PN16", "", ""): 2,  # inside P1, and between P1 and P2
        ("elbow 45", 100.0, None, "PN16", "", ""): 1,  # inside P5
    }
    assert _qty(t, "tee") == {
        ("reducing tee", 100.0, 25.0, "PN16", "", ""): 1,  # P1, P5, P6 at (0,0,1)
        ("reducing tee", 100.0, 50.0, "PN16", "", ""): 1,  # P3 on P1's run
    }
    # the placed reducer at the P2-P4 joint is that joint's reducer, not a second one
    assert _qty(t, "reducer") == {("reducer", 100.0, 80.0, "PN16", "", ""): 1}


def test_flanges_valves_and_inline_items():
    t = take_off(small_model())
    assert _qty(t, "valve") == {
        ("BallValve", 100.0, None, "PN16", "", ""): 1,
        ("SwingCheckValve", 100.0, None, "PN16", "", ""): 1,
        ("SpringLoadedGlobeSafetyValve", 50.0, None, "PN16", "", ""): 1,
    }
    assert _qty(t, "inline") == {("Silencer", 25.0, None, "PN16", "", ""): 1}
    flanges = {
        ("weld neck flange", 100.0, None, "PN16", "", ""): 4,  # ball valve 2, check valve 2
        ("weld neck flange", 50.0, None, "PN16", "", ""): 1,  # safety valve inlet
        ("weld neck flange", 25.0, None, "PN16", "", ""): 1,  # its outlet, on P6
        ("weld neck flange", 80.0, None, "PN40", "", ""): 1,  # nozzle E-1/N1 (N2 is not piped)
    }
    assert _qty(t, "flange") == flanges
    gaskets = {("gasket and bolt set", *k[1:]): v for k, v in flanges.items()}
    assert _qty(t, "gasket") == gaskets


def test_outlet_flange_is_looked_up_on_the_valves_own_sheet():
    """Segment ids are unique per sheet only: another sheet's pipe with the outlet's segment
    id must not lend the safety valve's outlet flange its DN or class."""
    model = small_model()
    for entry in [*model["pipes"], *model["inline"]]:
        entry["refs"] = {**entry.get("refs", {}), "sheet": "pid/P-01.xml"}
    other = _pipe("P6", 100, [[50, 50, 1], [55, 50, 1]], cls="PN40")
    other.update(id="P-02/P6", refs={"segments": ["P6"], "sheet": "pid/P-02.xml"})
    model["pipes"].append(other)
    flanges = _qty(take_off(model), "flange")
    assert flanges[("weld neck flange", 25.0, None, "PN16", "", "")] == 1  # on P-01's P6
    assert ("weld neck flange", 100.0, None, "PN40", "", "") not in flanges


def test_steel_grating_and_concrete():
    t = take_off(small_model())
    masses = section_masses()
    steel = _rows(t, "steel")
    heb = steel[("HEB300", None, None, "", "steel", "structure")]
    assert (heb.count, heb.length_m) == (2, 10.0)
    assert heb.quantity == round(masses["HEB300"] * 10 / 1000, 3)
    channel = steel[("C200", None, None, "", "steel", "stair")]
    assert channel.quantity == round(masses["UPN200"] * 4 / 1000, 3)
    assert len(steel) == 2
    unknown = [f for f in t.findings if f.rule == "cheme.mto-section-unknown"]
    assert len(unknown) == 1 and unknown[0].ids == ["XYZ1"]
    assert _qty(t, "grating") == {
        ("grating", None, None, "", "", "structure"): 24.0,
        ("grating", None, None, "", "", "stair"): 0.6,
        ("grating", None, None, "", "", "platform"): round(math.pi * 3 / 2, 3),
    }
    assert _qty(t, "concrete") == {
        ("plinth", None, None, "", "", "equipment"): 1.0,
        ("foundation", None, None, "", "", "equipment"): round(math.pi * 0.5, 3),
        ("bund wall", None, None, "", "", "area"): 3.0,
    }


def test_the_overhead_crane_is_no_bulk_steel():
    model = small_model()
    crane = [
        {
            "id": "B1/crane/runway-1",
            "kind": "member",
            "material": "crane",
            "section": "HEB300",
            "start": [0, 0, 8],
            "end": [10, 0, 8],
            "profile": [0.3, 0.3],
        },
        {
            "id": "B1/crane/bridge",
            "kind": "member",
            "material": "crane",
            "section": "box",
            "start": [5, 0, 9],
            "end": [5, 6, 9],
            "profile": [0.5, 1.0],
            "lod": 2,
        },
    ]
    model["buildings"] = [{"id": "B1", "parts": crane}]
    t = take_off(model)
    unknown = [f for f in t.findings if f.rule == "cheme.mto-section-unknown"]
    assert unknown[0].ids == ["XYZ1"]  # the box girder is not reported
    runway = [r for r in t.rows if r.category == "steel" and r.group == "building"]
    assert [(r.item, r.length_m) for r in runway] == [("HEB300", 10.0)]


def test_takeoff_is_deterministic_and_formats():
    model = small_model()
    first = take_off(model)
    assert mto_csv(first.rows) == mto_csv(take_off(json.loads(json.dumps(model))).rows)
    text = mto_csv(first.rows)
    assert text.splitlines()[0] == (
        "category,item,dn,dn2,class,spec,group,count,quantity,unit,length_m"
    )
    assert "tee,reducing tee,100,25,PN16,,,1,1,ea," in text
    md = mto_markdown(first)
    assert "model output_sha256 `abc`" in md and "## steel" in md and "mto-section-unknown" in md


def test_missing_model_is_a_finding():
    t = model_takeoff(None)
    assert not t.rows and t.findings[0].rule == "cheme.mto-model-missing"
    listed = model_takeoff("- a list")
    assert not listed.rows and listed.findings[0].message == "not a YAML mapping"


def test_asu_fixture_takeoff_is_plausible():
    """The frozen ASU model: every routed pipe is in the take-off, every placed valve counted."""
    data = Path(__file__).parent / "data" / "api-layout-asu.json"
    model = json.loads(data.read_text(encoding="utf-8"))["model"]
    t = take_off(model)
    total_pipe = sum(r.quantity for r in t.rows if r.category == "pipe")
    assert total_pipe == pytest.approx(sum(p["length"] for p in model["pipes"]), rel=1e-3)
    valves = sum(r.count for r in t.rows if r.category == "valve")
    assert valves == sum(
        1 for i in model["inline"] if i["kind"] in ("valve", "check_valve", "safety_valve")
    )
    assert not [f for f in t.findings if f.level != "info"]  # every section has a mass
    assert sum(r.quantity for r in t.rows if r.category == "steel") > 100


# -- the estimate -------------------------------------------------------------------------------


def _rates(**extra) -> RateFile:
    data = {
        "currency": "XXX",
        "cost_year": 2026,
        "rates": [
            {
                "id": "pipe-small",
                "category": "pipe",
                "unit": "m",
                "rate": 1,
                "where": {"dn_max": 50},
                "status": "ASSUMED",
                "source": "test",
                "year": 2026,
            },
            {
                "id": "pipe",
                "category": "pipe",
                "unit": "m",
                "rate": 2,
                "status": "ASSUMED",
                "source": "test",
                "year": 2026,
            },
            {
                "id": "valve",
                "category": "valve",
                "unit": "ea",
                "rate": 10,
                "status": "QUOTED",
                "source": "test",
                "year": 2024,
            },
            {
                "id": "never",
                "category": "pipe",
                "unit": "m",
                "rate": 9,
                "status": "ASSUMED",
                "source": "test",
                "year": 2026,
            },
        ],
        "factors": [
            {
                "id": "erect",
                "kind": "direct",
                "factor": 0.5,
                "applies_to": ["pipe"],
                "source": "test",
                "year": 2026,
            },
            {"id": "eng", "kind": "indirect", "factor": 0.1, "source": "test", "year": 2026},
            {"id": "cont", "kind": "contingency", "factor": 0.2, "source": "test", "year": 2026},
        ],
    }
    data.update(extra)
    return RateFile.model_validate(data)


def test_estimate_factor_method():
    result = estimate(take_off(small_model()), _rates())
    pipe = 2 * 1 + 5 * 1 + 2 * 2 + 10 * 2 + 9 * 2  # DN25, DN50 at 1; DN80, DN100 at 2
    valves = 3 * 10
    direct = pipe + valves + 0.5 * pipe
    indirect = round(0.1 * direct, 2)
    contingency = round(0.2 * (direct + indirect), 2)
    totals = result.totals()
    assert totals["materials"] == pytest.approx(pipe + valves)
    assert totals["direct"] == pytest.approx(direct)
    assert totals["indirect"] == pytest.approx(indirect)
    assert totals["contingency"] == pytest.approx(contingency)
    assert totals["total"] == pytest.approx(direct + indirect + contingency)
    rules = {f.rule: f for f in result.findings}
    assert "cheme.estimate-unpriced" in rules  # fittings, steel, ... have no rate here
    assert rules["cheme.estimate-rate-unused"].ids == ["never"]  # "pipe" matches first
    assert rules["cheme.estimate-rate-year"].ids == ["valve"]
    assert "cheme.estimate-example-rates" not in rules
    lines = {line.id: line for line in result.lines}
    assert lines["valve BallValve DN100 PN16"].status == "QUOTED"
    assert estimate_csv(result).splitlines()[0].startswith("section,id,description,quantity")


def test_rates_schema_refuses_wrong_units_and_missing_sources():
    with pytest.raises(ValueError, match="per m"):
        RateFile.model_validate(
            {
                "currency": "EUR",
                "cost_year": 2026,
                "rates": [
                    {
                        "id": "p",
                        "category": "pipe",
                        "unit": "ea",
                        "rate": 1,
                        "status": "ASSUMED",
                        "source": "x y",
                        "year": 2026,
                    }
                ],
            }
        )
    with pytest.raises(ValueError):
        RateFile.model_validate(
            {
                "currency": "EUR",
                "cost_year": 2026,
                "rates": [{"id": "p", "category": "pipe", "unit": "m", "rate": 1, "year": 2026}],
            }
        )


def test_template_rates_are_an_example_without_currency():
    rates = RateFile.model_validate(yaml.safe_load(TEMPLATE_RATES.read_text(encoding="utf-8")))
    assert rates.example and rates.currency == "XXX"
    assert all("EXAMPLE" in r.source for r in rates.rates + rates.factors)
    result = estimate(take_off(small_model()), rates)
    assert "cheme.estimate-example-rates" in {f.rule for f in result.findings}
    assert result.totals()["unpriced_rows"] == 0  # the example covers every category


# -- gate, CLI, API -----------------------------------------------------------------------------


def _write_model(root: Path, model: dict) -> None:
    path = root / LAYOUT_MODEL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(model, sort_keys=False), encoding="utf-8")


def test_gate_mto(tmp_path):
    assert mto_gate(tmp_path, ["mto-current"]) == [
        f"no {LAYOUT_MODEL_FILE}; run cheme layout build"
    ]
    model = small_model()
    _write_model(tmp_path, model)
    assert "no estimate/mto.csv" in mto_gate(tmp_path, ["mto-current"])[0]
    (tmp_path / "estimate").mkdir()
    (tmp_path / MTO_CSV).write_text(mto_csv(take_off(model).rows), encoding="utf-8")
    assert mto_gate(tmp_path, ["mto-current"]) == []
    model["pipes"][1]["points"][1] = [11, 4, 1]  # P2 longer
    _write_model(tmp_path, model)
    assert "not the take-off of the current model" in mto_gate(tmp_path, ["mto-current"])[0]
    # rates: missing, an example, then the project's own but not covering every row
    assert "no estimate/rates.yaml" in mto_gate(tmp_path, ["rates"])[0]
    (tmp_path / RATES_FILE).write_text(TEMPLATE_RATES.read_text(encoding="utf-8"))
    assert "is an example" in mto_gate(tmp_path, ["rates"])[0]
    own = _rates().model_dump(by_alias=True, exclude_none=True)
    (tmp_path / RATES_FILE).write_text(yaml.safe_dump(own), encoding="utf-8")
    assert "take-off rows have no rate" in mto_gate(tmp_path, ["rates"])[0]
    assert "no estimate/estimate.csv" in mto_gate(tmp_path, ["estimate-current"])[0]
    report = estimate_report(tmp_path)
    (tmp_path / "estimate/estimate.csv").write_text(estimate_csv(report.estimate))
    assert mto_gate(tmp_path, ["estimate-current"]) == []


def test_check_schema_kind_mto():
    Check.model_validate(
        {"id": "m", "title": "t", "stage": "basic", "kind": "mto", "require": ["mto-current"]}
    )
    with pytest.raises(ValueError, match="mto check requires only"):
        Check.model_validate(
            {"id": "m", "title": "t", "stage": "basic", "kind": "mto", "require": ["routed"]}
        )
    with pytest.raises(ValueError, match="belong to a kind: mto"):
        Check.model_validate(
            {
                "id": "m",
                "title": "t",
                "stage": "basic",
                "kind": "layout-model",
                "require": ["rates"],
            }
        )


def _cli(root: Path, *args: str):
    cwd = os.getcwd()
    os.chdir(root)
    try:
        return runner.invoke(app, ["assess", *args])
    finally:
        os.chdir(cwd)


def test_cli_prints_the_report(plant):
    _write_model(plant, small_model())
    report = mto_report(plant)
    result = _cli(plant, "mto", "--csv")
    assert result.exit_code == 0, result.output
    assert result.stdout == mto_csv(report.rows)
    as_json = _cli(plant, "mto", "--json")
    assert json.loads(as_json.stdout) == report.payload()
    assert "XYZ1" in as_json.stderr  # findings go to stderr
    assert _cli(plant, "mto", "--check").exit_code == 1
    assert _cli(plant, "mto", "--write").exit_code == 0
    assert (plant / MTO_CSV).read_text() == mto_csv(report.rows)
    assert _cli(plant, "mto", "--check").exit_code == 0
    # the template's gate passes once the take-off is written
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.checks import run_checks

    checks = yaml.safe_load((plant / "checks/checks.yaml").read_text(encoding="utf-8"))
    template_gate = next(c for c in checks["checks"] if c["id"] == "mto")
    assert template_gate == {
        "id": "mto",
        "title": "Material take-off current with the 3D model",
        "stage": "basic",
        "kind": "mto",
        "require": ["mto-current"],
    }
    (plant / "checks/checks.yaml").write_text(yaml.safe_dump({"checks": [template_gate]}))
    gates = {g.id: g for g in run_checks(Workspace(plant), stage="basic")}
    assert gates["mto"].status == "pass", gates["mto"].detail
    # the estimate with the template's example rates: priced, with the example warning
    est = _cli(plant, "estimate")
    assert est.exit_code == 0, est.output
    assert "EXAMPLE RATES" in est.stdout and "estimate-example-rates" in est.stderr
    (plant / RATES_FILE).unlink()
    assert _cli(plant, "estimate").exit_code == 1


def test_mto_needs_no_cli_or_server():
    code = (
        "import sys, chemeascode.domains.assessment.mto, chemeascode.domains.assessment.estimate, "
        "chemeascode.domains.assessment.gates; "
        "bad = [m for m in ('typer', 'fastapi', 'uvicorn') if m in sys.modules]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_api_mto(plant):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from chemeascode.interfaces.api.serve import create_app

    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "plant")
    api = TestClient(create_app(plant, allowed_hosts=["testserver"]))
    assert api.get("/api/mto").status_code == 404  # no model yet
    _write_model(plant, small_model())
    git(plant, "add", "-A")
    git(plant, "commit", "-q", "-m", "model")
    data = api.get("/api/mto").json()
    assert data["model_sha256"] == "abc"
    assert data["rows"] == mto_report(plant).payload()["rows"]
    assert data["totals"]["tee"] == {"ea": 2}
    assert data["estimate"]["example"] is True  # the template's rates.yaml
    assert data["estimate"]["totals"]["unpriced_rows"] == 0
