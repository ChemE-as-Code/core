"""cheme process simulate with the optional IDAES backend (``simulator: idaes``, ADR 0039).

Without IDAES: the translation of examples/process-hda-idaes, the refusals of what the backend
does not run, the worker command, and a fill and check from a recorded worker response
(tests/data/idaes/hda-worker-response.json, recorded from idaes-pse 2.13.0 with IPOPT 3.13.2 on
the example). With ``CHEME_IDAES_TESTS=1`` and ``CHEME_IDAES_PYTHON`` (a Python with idaes-pse
and IPOPT) the example is solved in IDAES and checked independently of IDAES: the overall
material balance, the declared conversion, the splitter's fractions and the flash outlets.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation import backends, record
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations import idaes, idaes_worker

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
RECORDED = ROOT / "tests" / "data" / "idaes" / "hda-worker-response.json"
SOURCE = "cheme process simulate: IDAES 2.13.0, IDAES ideal VLE"
idaes_tests = pytest.mark.skipif(
    os.environ.get("CHEME_IDAES_TESTS") != "1",
    reason="needs IDAES (set CHEME_IDAES_TESTS=1 and CHEME_IDAES_PYTHON to a Python with "
    "idaes-pse and IPOPT)",
)


@pytest.fixture
def hda(tmp_path):
    shutil.copytree(EXAMPLES / "process-hda-idaes", tmp_path / "plant")
    return Workspace(tmp_path / "plant")


def _translate(ws: Workspace, case: str = "design"):
    process, _ = load_process(ws.root)
    sim, doc, found = load(ws.root)
    assert not found
    return translate(process, sim, doc, case)


def _edit(ws: Workspace, path: str, edit) -> None:
    file = ws.root / path
    data = yaml.safe_load(file.read_text())
    edit(data)
    file.write_text(yaml.safe_dump(data, sort_keys=False))


def _state(ws: Workspace, stream: str) -> dict:
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == stream).get("state", {}).get("design", {})


def _errors(found, rule: str) -> list:
    return [f for f in found.findings if f.level == "error" and f.rule == f"cheme.process-{rule}"]


def recorded(model, save=None):
    return json.loads(RECORDED.read_text(encoding="utf-8"))


# -- translation --------------------------------------------------------------------------------


def test_translate_the_hda_example(hda):
    found = _translate(hda)
    assert not [f for f in found.findings if f.level in ("error", "warning")]
    model = found.model
    assert model["simulator"] == "idaes"
    assert model["property_package"] == "IDAES ideal VLE"
    assert [(u["id"], u["type"]) for u in model["units"]] == [
        ("M1", "mixer"),
        ("H1", "heater"),
        ("R1", "conversion_reactor"),
        ("E1", "cooler"),
        ("F1", "flash"),
        ("X1", "splitter"),
    ]
    assert model["recycles"] == [{"stream": "S10", "guess": None}]
    rules = {f.rule: f.message for f in found.findings}
    assert "not predictive" in rules["cheme.process-sim-method-unbenchmarked"]
    assert "(IDAES tear stream)" in rules["cheme.process-sim-recycle"]


def test_the_simulator_is_part_of_the_fingerprint(hda):
    """Switching backend makes the filled values stale; a DWSIM model has no simulator key, so
    every DWSIM fingerprint stays what it was."""
    before = _translate(hda).fingerprint

    def dwsim(d):
        d["simulator"] = "dwsim"
        d["property_package"] = "Peng-Robinson (PR)"

    _edit(hda, "process/simulation.yaml", dwsim)
    found = _translate(hda)
    assert "simulator" not in found.model
    assert found.fingerprint != before


def test_a_dwsim_package_is_refused_with_idaes(hda):
    _edit(hda, "process/simulation.yaml", lambda d: d.update(property_package="NRTL"))
    found = _translate(hda)
    assert found.model is None
    (error,) = _errors(found, "sim-property-package")
    assert "not one the IDAES backend runs" in error.message
    assert "IDAES ideal VLE" in error.hint


def test_an_idaes_package_is_refused_with_dwsim(hda):
    _edit(hda, "process/simulation.yaml", lambda d: d.update(simulator="dwsim"))
    found = _translate(hda)
    assert found.model is None
    assert _errors(found, "sim-property-package")


def test_a_compound_outside_the_package_is_refused(hda):
    def water(d):
        ch4 = next(c for c in d["components"] if c["id"] == "CH4")
        ch4.update(name="Water", formula="H2O", cas="7732-18-5", molar_mass=18.015)

    _edit(hda, "process/materials.yaml", water)
    found = _translate(hda)
    assert found.model is None
    (error,) = _errors(found, "sim-backend-unsupported")
    assert "7732-18-5" in error.message and error.ids == ["CH4"]
    assert error.file == "process/simulation.yaml"


def test_a_unit_the_backend_does_not_build_is_refused(tmp_path):
    """The separation example (rigorous column, component separator) with simulator: idaes:
    each unbuilt step is named, and nothing runs."""
    shutil.copytree(EXAMPLES / "process-separation", tmp_path / "plant")
    ws = Workspace(tmp_path / "plant")
    _edit(
        ws,
        "process/simulation.yaml",
        lambda d: d.update(simulator="idaes", property_package="IDAES Peng-Robinson"),
    )
    found = _translate(ws)
    assert found.model is None
    refused = _errors(found, "sim-backend-unsupported")
    assert any("the IDAES backend has no" in f.message for f in refused)
    assert all(f.hint for f in refused)


def test_the_backend_tables_agree_with_the_worker():
    """backends.py refuses at translation exactly what idaes_worker.py does not build."""
    assert backends.IDAES_UNITS == idaes_worker.UNITS
    assert set(backends.IDAES_PACKAGES) == set(idaes_worker.PACKAGES)
    for name, package in backends.IDAES_PACKAGES.items():
        assert set(package["compounds"]) == set(idaes_worker.PACKAGES[name]["components"])
        assert package["eos"] == idaes_worker.PACKAGES[name]["eos"]
    assert set(backends.IDAES_REACTION_PHASES) == set(idaes_worker.REACTION_PHASES)


def test_the_tear_guess_mixes_the_feeds():
    """Without a first guess a tear starts from all feeds mixed, so a reactant fed in another
    stream than the first (hydrogen here) is present in the first pass."""
    model = {
        "streams": [
            {
                "id": "S1",
                "kind": "material",
                "feed": {
                    "mass_flow_kg_s": 0.092,
                    "mole_fractions": {"TOL": 1.0},
                    "temperature_K": 300.0,
                    "pressure_Pa": 3e5,
                },
            },
            {
                "id": "S2",
                "kind": "material",
                "feed": {
                    "mass_flow_kg_s": 0.002,
                    "mole_fractions": {"H2": 1.0},
                    "temperature_K": 310.0,
                    "pressure_Pa": 3e5,
                },
            },
        ]
    }
    names = {"TOL": "toluene", "H2": "hydrogen"}
    mws = {"TOL": 0.092, "H2": 0.002}
    mixed = idaes_worker._feed_mix(model, names, mws)
    assert mixed["flow_mol"] == pytest.approx(2.0)
    assert mixed["mole_fractions"] == pytest.approx({"TOL": 0.5, "H2": 0.5})
    guess = idaes_worker._tear_guess(None, mixed, names, mws)
    assert guess["flow_mol"][0] == pytest.approx(idaes_worker.TEAR_GUESS_FRACTION * 2.0)
    assert guess["mole_frac_comp"][(0, "hydrogen")] == pytest.approx(0.5)
    assert guess["temperature"][0] == 300.0
    own = idaes_worker._tear_guess({"mass_flow_kg_s": 0.046}, mixed, names, mws)
    assert own["flow_mol"][0] == pytest.approx(0.046 / 0.047)


# -- the worker command --------------------------------------------------------------------------


def test_no_idaes_python_is_a_finding(hda, monkeypatch):
    monkeypatch.delenv("CHEME_IDAES_PYTHON", raising=False)
    monkeypatch.delenv("CHEME_IDAES_COMMAND", raising=False)
    process, _ = load_process(hda.root)
    result = run(hda, process, "design", write=True)
    errors = [f for f in result.findings if f.level == "error"]
    assert [f.rule for f in errors] == ["cheme.process-sim-unavailable"]
    assert "CHEME_IDAES_PYTHON" in errors[0].message and "idaes-pse" in errors[0].hint
    assert not (hda.root / "process/simulation-run.json").exists()


def test_a_missing_idaes_python_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("CHEME_IDAES_COMMAND", raising=False)
    monkeypatch.setenv("CHEME_IDAES_PYTHON", str(tmp_path / "nowhere" / "python"))
    with pytest.raises(idaes.IdaesUnavailable, match="does not exist"):
        idaes.solve({})


def _command(monkeypatch, tmp_path, body: str) -> None:
    script = tmp_path / "worker.py"
    script.write_text(body)
    monkeypatch.delenv("CHEME_IDAES_PYTHON", raising=False)
    monkeypatch.setenv(
        "CHEME_IDAES_COMMAND", f'"{Path(sys.executable).as_posix()}" -I "{script.as_posix()}"'
    )


def test_the_worker_result_is_its_last_line(monkeypatch, tmp_path):
    """IDAES and Pyomo print on stdout in places: the result is the last line."""
    _command(
        monkeypatch,
        tmp_path,
        "import json, sys\nrequest = json.loads(sys.stdin.read())\n"
        "print('chatter')\n"
        "print(json.dumps({'ok': True, 'version': '0', 'details': request['details'], "
        "'converged': True, 'streams': {}}))\n",
    )
    out = idaes.solve({"units": []}, details=True)
    assert out["ok"] and out["details"] is True
    saved = idaes.solve({"units": []}, save=tmp_path / "x.dwxmz")
    assert "writes no flowsheet file" in saved["save_error"]


def test_a_worker_error_is_raised(monkeypatch, tmp_path):
    _command(
        monkeypatch,
        tmp_path,
        "import json\nprint(json.dumps({'ok': False, 'error': 'LookupError: no such unit'}))\n",
    )
    with pytest.raises(idaes.IdaesFailed, match="no such unit"):
        idaes.solve({})


def test_parse_takes_no_garbage():
    assert idaes.parse("") == {}
    assert idaes.parse("no json") == {}
    assert idaes.parse('x\n["a list"]') == {}
    assert idaes.parse('x\n{"ok": true}') == {"ok": True}


# -- fill and check from the recorded response ----------------------------------------------------


def test_fill_from_the_recorded_response_and_check_is_then_clean(hda):
    process, _ = load_process(hda.root)
    result = run(hda, process, "design", write=True, solver=recorded)
    assert not [f for f in result.findings if f.level in ("error", "warning")]
    assert not result.refused
    assert result.lines[0] == f"{SOURCE}; case design"
    s8 = _state(hda, "S8")
    for field in ("temperature", "pressure", "flow", "composition"):
        assert s8[field]["provenance"] == "calculated"
        assert s8[field]["origin"] == "simulated"
        assert s8[field]["source"] == SOURCE
        assert s8[field]["fingerprint"]
    assert s8["temperature"]["value"] == pytest.approx(325.0)
    assert s8["flow"]["value"] == pytest.approx(77.80, abs=0.01)
    assert _state(hda, "Q1")["duty"]["value"] == pytest.approx(48.84, abs=0.01)
    assert _state(hda, "S1")["flow"]["provenance"] == "assumed"  # a feed is never rewritten

    entry = record.entry_of(record.read(hda.root), "design")
    assert entry["simulator"] == {
        "name": "idaes",
        "version": "2.13.0",
        "method": "IDAES ideal VLE",
        "solver": "ipopt 3.13.2.0",
    }
    assert entry["converged"] and entry["status"] == "converged" and entry["iterations"] == 10
    assert entry["model_fingerprint"] == s8["flow"]["fingerprint"]
    r1 = next(u for u in entry["units"] if u["id"] == "R1")
    assert r1["results"]["extents_kmol_h"]["HDA"] == pytest.approx(0.8505, abs=1e-4)

    process, _ = load_process(hda.root)
    check = run(hda, process, "design", write=False, solver=recorded)
    assert not [f for f in check.findings if f.level != "info" or "not-filled" in f.rule]


def test_a_changed_spec_makes_the_values_stale(hda):
    process, _ = load_process(hda.root)
    run(hda, process, "design", write=True, solver=recorded)
    _edit(
        hda, "process/simulation.yaml", lambda d: d["specs"]["F1"]["temperature"].update(value=320)
    )
    process, _ = load_process(hda.root)
    check = run(hda, process, "design", write=False, solver=recorded)
    rules = {f.rule for f in check.findings}
    assert "cheme.process-sim-stale" in rules and "cheme.process-sim-run-stale" in rules


def test_a_run_that_did_not_converge_writes_no_value(hda):
    def failed(model, save=None):
        return {
            **recorded(model),
            "converged": False,
            "messages": ["IPOPT did not converge: maxIterations"],
            "notes": ["initialization did not finish (InitializationError: fs.u2)"],
        }

    process, _ = load_process(hda.root)
    result = run(hda, process, "design", write=True, solver=failed)
    assert result.refused == ["design"]
    warned = [f for f in result.findings if f.rule == "cheme.process-sim-not-converged"]
    assert "maxIterations" in warned[0].message
    assert "temperature" not in _state(hda, "S8")
    entry = record.entry_of(record.read(hda.root), "design")
    assert entry["status"] == "not-converged"
    assert entry["notes"] == ["initialization did not finish (InitializationError: fs.u2)"]


# -- IDAES itself (CHEME_IDAES_TESTS=1) -----------------------------------------------------------


@idaes_tests
def test_idaes_solves_the_hda_loop(hda):
    """The example in IDAES, checked without IDAES's own balance: what enters leaves (mass, and
    each element's atoms), the reactor converts 0.75 of the toluene it is fed (extent against
    the inlet's toluene flow), the purge is 0.2 of the flash vapour, the flash outlets are its
    vapour and liquid at 325 K."""
    process, _ = load_process(hda.root)
    found = _translate(hda)
    model = found.model
    out = idaes.solve(model, details=True)
    assert out["converged"], out["messages"]
    assert out["version"].startswith("2.")
    streams = out["streams"]
    mw = {"TOL": 92.1405, "H2": 2.016, "BZ": 78.1136, "CH4": 16.043}

    def kmol_h(sid: str) -> dict[str, float]:
        s = streams[sid]
        mean = sum(s["mole_fractions"][c] * mw[c] for c in mw)
        total = s["mass_flow_kg_s"] * 3600.0 / mean
        return {c: s["mole_fractions"][c] * total for c in mw}

    feeds = 100.0 + 3.4  # kg/h, S1 and S2
    leaving = (streams["S8"]["mass_flow_kg_s"] + streams["S9"]["mass_flow_kg_s"]) * 3600.0
    assert leaving == pytest.approx(feeds, rel=1e-6)

    s1 = {"TOL": 100.0 / mw["TOL"], "H2": 0.0, "BZ": 0.0, "CH4": 0.0}
    s2_mean = 0.95 * mw["H2"] + 0.05 * mw["CH4"]
    s2 = {"TOL": 0.0, "H2": 0.95 * 3.4 / s2_mean, "BZ": 0.0, "CH4": 0.05 * 3.4 / s2_mean}
    atoms = {
        "C": {"TOL": 7, "BZ": 6, "CH4": 1, "H2": 0},
        "H": {"TOL": 8, "BZ": 6, "CH4": 4, "H2": 2},
    }
    out_flows = {c: kmol_h("S8")[c] + kmol_h("S9")[c] for c in mw}
    for element, count in atoms.items():
        fed = sum(count[c] * (s1[c] + s2[c]) for c in mw)
        left = sum(count[c] * out_flows[c] for c in mw)
        assert left == pytest.approx(fed, rel=1e-5), element

    extent = out["units"]["R1"]["extents_kmol_h"]["HDA"]
    assert extent == pytest.approx(0.75 * kmol_h("S4")["TOL"], rel=1e-6)
    s5, s4 = kmol_h("S5"), kmol_h("S4")
    assert s5["BZ"] - s4["BZ"] == pytest.approx(extent, rel=1e-5)

    vapour = streams["S7"]["mass_flow_kg_s"]
    assert streams["S9"]["mass_flow_kg_s"] == pytest.approx(0.2 * vapour, rel=1e-6)
    assert streams["S7"]["vapor_fraction"] == 1.0 and streams["S8"]["vapor_fraction"] == 0.0
    assert streams["S7"]["temperature_K"] == pytest.approx(325.0)
    assert streams["S8"]["mole_fractions"]["H2"] < 1e-6  # hydrogen is vapour only
    assert out["units"]["R1"]["duty_kW"] == pytest.approx(0.0, abs=1e-6)  # adiabatic
    assert streams["S5"]["temperature_K"] > streams["S4"]["temperature_K"]  # exothermic

    result = run(hda, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")]
    assert _state(hda, "S8")["flow"]["source"].startswith("cheme process simulate: IDAES 2.")
