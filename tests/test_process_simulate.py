"""cheme process simulate: the simulator model (translate), fill and check with a stand-in
solver, and, with CHEME_DWSIM_TESTS=1, the real DWSIM (docker image or CHEME_DWSIM_PATH).

The integration test checks DWSIM against a hand calculation: ideal-gas compression of air,
T2 = T1 + T1 ((P2/P1)^((k-1)/k) - 1) / eta, k = 1.4, which Peng-Robinson follows within a few
kelvin at 8 bar(a) and ambient temperature.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from chemeascode.domains.process.model import load as load_process
from chemeascode.domains.process.simulation.run import run
from chemeascode.domains.process.simulation.translate import load, translate
from chemeascode.foundation.workspace import Workspace
from chemeascode.integrations import dwsim

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
dwsim_tests = pytest.mark.skipif(
    os.environ.get("CHEME_DWSIM_TESTS") != "1",
    reason="needs DWSIM (set CHEME_DWSIM_TESTS=1 with the docker image or a local install)",
)


@pytest.fixture
def plant(tmp_path):
    shutil.copytree(EXAMPLES / "process-simulation", tmp_path / "plant")
    return Workspace(tmp_path / "plant")


def _model(ws: Workspace, case: str = "design"):
    process, _ = load_process(ws.root)
    sim, doc, found = load(ws.root)
    assert not found
    return translate(process, sim, doc, case)


def _state(ws: Workspace, stream: str) -> dict:
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == stream).get("state", {}).get("design", {})


def _edit(ws: Workspace, path: str, edit) -> None:
    file = ws.root / path
    data = yaml.safe_load(file.read_text())
    edit(data)
    file.write_text(yaml.safe_dump(data, sort_keys=False))


AIR = {"N2": 0.7812, "O2": 0.2096, "AR": 0.0092}


def fake(model, save=None, *, converged=True, t2=598.0):
    """What DWSIM returns for the example, near enough for the bookkeeping."""
    feed = next(s["feed"] for s in model["streams"] if s["feed"])
    m = feed["mass_flow_kg_s"]
    split = next(u["spec"]["fractions"] for u in model["units"] if u["type"] == "splitter")

    def stream(t, p, flow):
        return {
            "temperature_K": t,
            "pressure_Pa": p,
            "mass_flow_kg_s": flow,
            "mole_fractions": dict(AIR),
            "vapor_fraction": 1.0,
        }

    return {
        "ok": True,
        "version": "9.0.5.0",
        "converged": converged,
        "iterations": 1,
        "messages": [] if converged else ["E1: not calculated"],
        "streams": {
            "S2": stream(t2, 800000.0, m),
            "S3": stream(308.15, 780000.0, m),
            "S4": stream(308.15, 780000.0, m * split[0]),
            "S5": stream(308.15, 780000.0, m * split[1]),
        },
        "energies": {"W1": {"duty_kW": 84.2}},
        "units": {"K1": {"duty_kW": 84.2}, "E1": {"duty_kW": -81.0}},
    }


# -- translate ----------------------------------------------------------------------------------


def test_translate_the_example(plant):
    found = _model(plant)
    assert not [f for f in found.findings if f.level == "error"]
    model = found.model
    assert [(u["id"], u["type"]) for u in model["units"]] == [
        ("K1", "compressor"),
        ("E1", "cooler"),
        ("X1", "splitter"),
    ]
    k1, e1, x1 = model["units"]
    assert k1["spec"] == {"outlet_pressure_Pa": 800000.0, "efficiency": 0.78}
    assert k1["energies"] == {"energy": "W1"} and found.energies == {"W1": ("K1", "duty_kW")}
    assert e1["spec"] == {"outlet_temperature_K": 308.15, "pressure_drop_Pa": 20000.0}
    assert x1["outlets"] == ["S4", "S5"] and x1["spec"]["fractions"] == [0.7, 0.3]
    feed = model["streams"][0]["feed"]
    assert feed["pressure_Pa"] == pytest.approx(101325.0)
    assert feed["mass_flow_kg_s"] == pytest.approx(1000 / 3600)
    assert [c["cas"] for c in model["compounds"]] == ["7727-37-9", "7782-44-7", "7440-37-1"]
    assert found.outlets == ["S2", "S3", "S4", "S5"]


def test_fingerprint_follows_the_specs(plant):
    before = _model(plant).fingerprint
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"]["K1"]["efficiency"].update(value=0.7),
    )
    assert _model(plant).fingerprint != before


def test_refusals_name_file_line_and_rule(plant):
    def spoil(d):
        d["specs"]["K1"].pop("efficiency")
        d["specs"]["E1"]["duty"] = {"value": -80, "provenance": "assumed"}

    _edit(plant, "process/simulation.yaml", spoil)
    _edit(plant, "process/flowsheet.yaml", lambda d: d["streams"][0]["state"]["design"].pop("flow"))
    found = _model(plant)
    assert found.model is None
    by_rule = {(f.rule, tuple(f.ids)): f for f in found.findings if f.level == "error"}
    assert ("cheme.process-sim-spec", ("K1",)) in by_rule
    assert (
        "exactly one of outlet_temperature, duty"
        in by_rule[("cheme.process-sim-spec", ("E1",))].message
    )
    feed = by_rule[("cheme.process-sim-feed-incomplete", ("S1",))]
    assert feed.file == "process/flowsheet.yaml" and feed.line and "flow" in feed.message
    assert all(f.line for f in by_rule.values())


def test_unmapped_class_and_unit_override(plant):
    _edit(plant, "process/flowsheet.yaml", lambda d: d["steps"][0].update({"class": "ProcessStep"}))
    found = _model(plant)
    assert found.model is None
    assert any(f.rule.endswith("sim-unmapped") and f.ids == ["K1"] for f in found.findings)
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["K1"].update(unit="compressor"))
    assert _model(plant).model is not None


def _anti_surge(d):
    """20 % of the compressed air back to the suction through a valve: 1250 kg/h compressed,
    750 and 250 kg/h to the users, 250 kg/h recycled."""
    k1 = d["steps"][0]
    k1["ports"][0] = {"id": "in", "direction": "in"}
    d["steps"].append(
        {
            "id": "M1",
            "block": "COMP",
            "class": "MixingSimple",
            "ports": [
                {"id": "feed", "direction": "in", "delegates": "in"},
                {"id": "recycle", "direction": "in"},
                {"id": "out", "direction": "out"},
            ],
        }
    )
    x1 = d["steps"][2]
    x1["ports"].append({"id": "c", "direction": "out"})
    x1["split"] = {"a": 0.6, "b": 0.2}
    d["steps"].append(
        {
            "id": "V2",
            "block": "DIST",
            "class": "RegulatingFlow",
            "ports": [{"id": "in", "direction": "in"}, {"id": "out", "direction": "out"}],
        }
    )
    d["streams"][0]["to"] = "M1.feed"
    d["streams"] += [
        {"id": "S0", "from": "M1.out", "to": "K1.in", "template": "air"},
        {"id": "S8", "from": "X1.c", "to": "V2.in", "template": "air"},
        {"id": "S9", "from": "V2.out", "to": "M1.recycle", "template": "air"},
    ]


def _with_recycle(ws: Workspace) -> None:
    _edit(ws, "process/flowsheet.yaml", _anti_surge)
    _edit(
        ws,
        "process/simulation.yaml",
        lambda d: d["specs"].update(
            V2={"outlet_pressure": {"value": 101.325, "provenance": "given"}}
        ),
    )


def test_recycle_is_torn(plant):
    _with_recycle(plant)
    found = _model(plant)
    assert found.model is not None, found.findings
    assert found.model["recycles"] == [{"stream": "S0", "guess": None}]
    info = [f for f in found.findings if f.rule.endswith("sim-recycle")]
    assert info[0].level == "info" and info[0].ids == ["S0"] and "chosen by" in info[0].message
    _edit(plant, "process/simulation.yaml", lambda d: d.update(tear_streams=["S9"]))
    assert _model(plant).model["recycles"][0]["stream"] == "S9"
    _edit(plant, "process/simulation.yaml", lambda d: d.update(tear_streams=["S4"]))
    refused = _errors(_model(plant), "sim-recycle")
    assert refused and "run between no two simulated units" in refused[0].message


def test_tear_streams_named_twice_are_refused(plant):
    _with_recycle(plant)
    _edit(plant, "process/simulation.yaml", lambda d: d.update(tear_streams=["S0", "S0"]))
    assert "names a stream twice" in _errors(_model(plant), "sim-recycle")[0].message


def test_fingerprint_without_a_loop_is_unchanged_by_recycles(plant):
    import hashlib

    found = _model(plant)
    assert found.model["recycles"] == []
    old = {k: v for k, v in found.model.items() if k != "recycles"}  # the M1 model
    m1 = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()[:16]
    assert found.fingerprint == m1


def test_guesses_in_the_simulation_file(plant):
    _with_recycle(plant)
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d.update(guesses={"S0": {"flow": {"value": 1300, "provenance": "assumed"}}}),
    )
    guess = _model(plant).model["recycles"][0]["guess"]
    assert guess == {"mass_flow_kg_s": pytest.approx(1300 / 3600)}


def test_column_spec_mixups(separation):
    def shortcut_with_stages(d):
        d["specs"]["C1"].update(unit="shortcut_column", stages=18)

    _edit(separation, "process/simulation.yaml", shortcut_with_stages)
    assert "rigorous column's spec" in _errors(_model(separation), "sim-spec")[0].message


def test_tear_guess_comes_from_the_flowsheet_and_leaves_the_fingerprint(plant):
    _with_recycle(plant)
    before = _model(plant).fingerprint

    def guess(d):
        s0 = next(s for s in d["streams"] if s["id"] == "S0")
        s0["state"] = {"design": {"flow": {"value": 1200, "provenance": "assumed"}}}

    _edit(plant, "process/flowsheet.yaml", guess)
    found = _model(plant)
    assert found.model["recycles"][0]["guess"] == {"mass_flow_kg_s": pytest.approx(1200 / 3600)}
    assert found.fingerprint == before


# -- fill and check ----------------------------------------------------------------------------


def test_fill_writes_what_streams_lack_and_check_is_then_clean(plant):
    text = (plant.root / "process/flowsheet.yaml").read_text()
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True, solver=fake)
    assert result.written == 5 and not result.refused
    assert not [f for f in result.findings if f.level in ("error", "warning")]
    s2 = _state(plant, "S2")
    assert s2["temperature"]["value"] == 598.0 and s2["pressure"]["value"] == 800.0
    assert s2["temperature"]["provenance"] == "calculated"
    assert s2["temperature"]["source"] == (
        "cheme process simulate: DWSIM 9.0.5.0, Peng-Robinson (PR)"
    )
    assert s2["composition"]["values"] == AIR
    assert _state(plant, "S4")["flow"]["value"] == pytest.approx(700.0)
    assert _state(plant, "W1")["duty"]["value"] == 84.2
    assert _state(plant, "S1")["flow"]["provenance"] == "given"
    after = (plant.root / "process/flowsheet.yaml").read_text()
    assert after.startswith(text.split("\n", 1)[0])  # the comments stay
    assert "# Regenerate the sheets" in after

    process, _ = load_process(plant.root)
    check = run(plant, process, "design", write=False, solver=fake)
    assert not [f for f in check.findings if f.level != "info" or "not-filled" in f.rule]


@pytest.mark.parametrize("entering", [True, False])
def test_duty_is_written_only_in_its_streams_direction(plant, entering):
    """E1 as a heater (either direction) with an energy stream W2: the stand-in solver gives it
    -81 kW, heat removed (pre-release issue 186). Out of E1 to a cooling water return W2 carries 81
    kW; into E1 from a steam supply it would say 81 kW added, so nothing is written and a warning
    says so."""

    def heater_with_w2(d):
        terminal = {"id": "UTIL", "title": "Utility", "ports": [{"id": "w", "kind": "energy"}]}
        terminal["ports"][0]["direction"] = "out" if entering else "in"
        d["feeds" if entering else "products"].append(terminal)
        e1 = next(s for s in d["steps"] if s["id"] == "E1")
        e1["ports"].append({"id": "w", "direction": "in" if entering else "out", "kind": "energy"})
        ends = {"from": "UTIL.w", "to": "E1.w"} if entering else {"from": "E1.w", "to": "UTIL.w"}
        d["streams"].append({"id": "W2", "title": "Duty", "kind": "energy", **ends})

    _edit(plant, "process/flowsheet.yaml", heater_with_w2)
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["E1"].update(unit="heater"))
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True, solver=fake)
    warned = [f for f in result.findings if f.rule == "cheme.process-sim-energy-direction"]
    if entering:
        assert [(f.level, f.ids) for f in warned] == [("warning", ["E1", "W2"])]
        assert "runs into E1, but the simulated duty is 81 kW out of it" in warned[0].message
        assert "duty" not in _state(plant, "W2")
    else:
        assert not warned
        assert _state(plant, "W2")["duty"]["value"] == 81.0
    assert _state(plant, "W1")["duty"]["value"] == 84.2  # into the compressor, as before


def test_wrong_sign_duty_of_an_earlier_simulate_is_reported(plant):
    """A flowsheet filled before the direction was checked holds W2 81 kW into E1, written by
    simulate and current by its fingerprint (pre-release issue 186): simulate no longer rewrites it,
    so the warning says it is wrong, with --fill and --check; a given duty is left to its owner."""

    def heater_with_w2(d, duty):
        d["feeds"].append(
            {
                "id": "STEAM",
                "title": "Steam",
                "ports": [{"id": "w", "direction": "out", "kind": "energy"}],
            }
        )
        e1 = next(s for s in d["steps"] if s["id"] == "E1")
        e1["ports"].append({"id": "w", "direction": "in", "kind": "energy"})
        d["streams"].append(
            {
                "id": "W2",
                "title": "Duty",
                "kind": "energy",
                "from": "STEAM.w",
                "to": "E1.w",
                "state": {"design": {"duty": duty}},
            }
        )

    earlier = {
        "value": 81.0,
        "provenance": "calculated",
        "origin": "simulated",
        "source": "cheme process simulate: DWSIM 9.0.5.0, Peng-Robinson (PR)",
        "fingerprint": "912bf32d6b53ff40",
    }
    _edit(plant, "process/flowsheet.yaml", lambda d: heater_with_w2(d, earlier))
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["E1"].update(unit="heater"))
    process, _ = load_process(plant.root)
    for write in (True, False):
        result = run(plant, process, "design", write=write, solver=fake)
        warned = [f for f in result.findings if f.rule == "cheme.process-sim-energy-direction"]
        assert len(warned) == 1
        assert "the duty W2 holds (81, written by an earlier simulate) is wrong" in (
            warned[0].message
        )
        assert warned[0].hint.startswith("delete state.design.duty of W2")

    shutil.rmtree(plant.root)
    shutil.copytree(EXAMPLES / "process-simulation", plant.root)
    given = {"value": 81.0, "provenance": "given", "source": "utility list"}
    _edit(plant, "process/flowsheet.yaml", lambda d: heater_with_w2(d, given))
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["E1"].update(unit="heater"))
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True, solver=fake)
    warned = [f for f in result.findings if f.rule == "cheme.process-sim-energy-direction"]
    assert len(warned) == 1 and "is wrong" not in warned[0].message
    assert _state(plant, "W2")["duty"] == given


def _duty_of(kind: str, key: str, duty: float, entering: bool):
    """The duty _values writes for one unit of *kind* whose result *key* is *duty*, its energy
    stream Q1 running into it or out of it, and the rules it reports."""
    from types import SimpleNamespace

    from chemeascode.domains.process.simulation.run import _values

    process = SimpleNamespace(
        flowsheet=SimpleNamespace(
            units=SimpleNamespace(duty="kW"), streams=[SimpleNamespace(id="Q1", state={})]
        ),
        templates=dict,
    )
    model = SimpleNamespace(
        model={"units": [{"id": "U1", "type": kind}]},
        energies={"Q1": ("U1", key)},
        entering={"Q1"} if entering else set(),
        outlets=[],
        fingerprint="f",
    )
    added = []
    out = {"units": {"U1": {key: duty}}}
    values = _values(process, model, out, "design", "test", lambda *a, **k: added.append(a[1]))
    written = values.get(("Q1", "duty"))
    return (written.value if written else None), added


@pytest.mark.parametrize(
    "kind, key, duty, entering, written",
    [
        ("compressor", "duty_kW", 84.2, True, 84.2),  # power taken
        ("pump", "duty_kW", 3.0, True, 3.0),
        ("expander", "duty_kW", 40.0, False, 40.0),  # power produced
        ("expander", "duty_kW", 40.0, True, None),
        ("compressor", "cooling_kW", 30.0, False, 30.0),  # intercooling: a magnitude, out
        ("compressor", "cooling_kW", -30.0, False, 30.0),
        ("distillation_column", "reboiler_kW", 350.0, True, 350.0),
        ("distillation_column", "condenser_kW", 300.0, False, 300.0),
        ("cooler", "duty_kW", -81.0, False, 81.0),  # heat added, negative: removed
        ("cooler", "duty_kW", 5.0, False, None),  # a cooler that heats: refused
        ("heater", "duty_kW", 81.0, True, 81.0),
        ("flash", "duty_kW", -12.0, False, 12.0),
        ("conversion_reactor", "duty_kW", -50.0, True, None),
        ("component_separator", "duty_kW", 5.0, False, None),  # EnergyImb: sign unknown
    ],
)
def test_duty_sign_against_the_stream_direction(kind, key, duty, entering, written):
    """Every result key's sign as energy into the unit (pre-release issue 186): written as a
    magnitude where it agrees with the stream's direction, refused with sim-energy-direction where
    not."""
    value, added = _duty_of(kind, key, duty, entering)
    assert value == written
    assert added == ([] if written is not None else ["sim-energy-direction"])


def test_check_reports_unfilled_stale_and_deviating_values(plant):
    process, _ = load_process(plant.root)
    found = run(plant, process, "design", write=False, solver=fake)
    assert {f.ids[0] for f in found.findings if f.rule.endswith("sim-not-filled")} == {
        "S2",
        "S3",
        "S4",
        "S5",
        "W1",
    }
    run(plant, process, "design", write=True, solver=fake)
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"]["K1"]["efficiency"].update(value=0.7),
    )

    def assume(d):
        s4 = next(s for s in d["streams"] if s["id"] == "S4")
        s4["state"]["design"]["temperature"] = {"value": 320.0, "provenance": "assumed"}

    _edit(plant, "process/flowsheet.yaml", assume)
    process, _ = load_process(plant.root)
    check = run(plant, process, "design", write=False, solver=fake)
    stale = {f.ids[0] for f in check.findings if f.rule.endswith("sim-stale")}
    assert {"S2", "S3", "S4", "S5", "W1"} <= stale
    deviation = [f for f in check.findings if f.rule.endswith("sim-deviation")]
    assert len(deviation) == 1 and deviation[0].ids == ["S4"]
    assert "simulated 308.15 K, assumed 320.00 K" in deviation[0].message
    run(plant, process, "design", write=True, solver=fake)
    assert _state(plant, "S4")["temperature"] == {"value": 320.0, "provenance": "assumed"}


def test_no_convergence_writes_nothing(plant):
    process, _ = load_process(plant.root)
    before = (plant.root / "process/flowsheet.yaml").read_text()
    result = run(
        plant,
        process,
        "design",
        write=True,
        solver=lambda m, s: fake(m, s, converged=False),
    )
    assert result.refused == ["design"]
    assert any(f.rule.endswith("sim-not-converged") for f in result.findings)
    assert (plant.root / "process/flowsheet.yaml").read_text() == before


def test_missing_simulation_file_and_missing_dwsim(plant, monkeypatch):
    (plant.root / "process/simulation.yaml").rename(plant.root / "process/other.yaml")
    process, _ = load_process(plant.root)
    found = run(plant, process, "design", write=False, solver=fake)
    assert [f.rule for f in found.findings] == ["cheme.process-sim-missing"]
    (plant.root / "process/other.yaml").rename(plant.root / "process/simulation.yaml")

    monkeypatch.delenv("CHEME_DWSIM_COMMAND", raising=False)
    monkeypatch.delenv("CHEME_DWSIM_PATH", raising=False)
    monkeypatch.setattr(dwsim.shutil, "which", lambda name: None)
    found = run(plant, process, "design", write=False)
    errors = [f for f in found.findings if f.level == "error"]
    assert [f.rule for f in errors] == ["cheme.process-sim-unavailable"]
    assert "docker" in errors[0].message


def test_cli_exit_codes(plant, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(plant.root)
    monkeypatch.setattr(dwsim, "solve", fake)
    runner = CliRunner()
    assert runner.invoke(app, ["process", "simulate"]).exit_code == 2
    check = runner.invoke(app, ["process", "simulate", "--check"])
    assert check.exit_code == 0 and "sim-not-filled" in check.output
    filled = runner.invoke(app, ["process", "simulate", "--fill"])
    assert filled.exit_code == 0 and "written for 5 stream(s)" in filled.output
    assert "K1: 84.2 kW" in filled.output
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["K1"].pop("efficiency"))
    refused = runner.invoke(app, ["process", "simulate", "--fill"])
    assert refused.exit_code == 1 and "sim-spec" in refused.output


def _errors(found, rule):
    return [f for f in found.findings if f.rule.endswith(rule) and f.level == "error"]


def test_splitter_fractions_follow_the_connected_ports(plant):
    def middle(d):
        x1 = d["steps"][2]
        x1["ports"].insert(2, {"id": "spare", "direction": "out"})
        x1["split"] = {"a": 0.3, "spare": 0.0}

    _edit(plant, "process/flowsheet.yaml", middle)
    x1 = next(u for u in _model(plant).model["units"] if u["id"] == "X1")
    assert x1["outlets"] == ["S4", "S5"] and x1["spec"]["fractions"] == [0.3, 0.7]
    _edit(plant, "process/flowsheet.yaml", lambda d: d["steps"][2].update(split={"spare": 0.2}))
    assert "unconnected" in _errors(_model(plant), "sim-spec")[0].message
    _edit(plant, "process/flowsheet.yaml", lambda d: d["steps"][2].update(split={"a": -0.1}))
    assert "negative" in _errors(_model(plant), "sim-spec")[0].message


def test_unit_shapes_energy_streams_and_cooler_duty(plant):
    def four(d):
        x1 = d["steps"][2]
        for k in ("c", "d"):
            x1["ports"].append({"id": k, "direction": "out"})
            d["products"][0]["ports"].append({"id": k, "direction": "in"})
            d["streams"].append({"id": f"S{k}", "from": f"X1.{k}", "to": f"HP.{k}"})

    _edit(plant, "process/flowsheet.yaml", four)
    shape = _errors(_model(plant), "sim-unmapped")
    assert shape and "2 to 3 out" in shape[0].message and shape[0].hint

    shutil.rmtree(plant.root)
    shutil.copytree(EXAMPLES / "process-simulation", plant.root)

    def power_to_cooler(d):
        d["steps"][1]["ports"].append({"id": "w", "direction": "in", "kind": "energy"})
        d["feeds"][1]["ports"].append({"id": "w2", "direction": "out", "kind": "energy"})
        d["steps"][2]["ports"].append({"id": "w", "direction": "in", "kind": "energy"})
        d["streams"].append({"id": "W2", "kind": "energy", "from": "POWER.w2", "to": "X1.w"})

    _edit(plant, "process/flowsheet.yaml", power_to_cooler)
    found = _model(plant)
    assert found.model is not None and "W2" not in found.energies
    assert [f.ids for f in found.findings if f.rule.endswith("sim-energy-ignored")] == [["W2"]]
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"].update(
            E1={"duty": {"value": 80, "provenance": "assumed"}},
        ),
    )
    assert "adds heat" in _errors(_model(plant), "sim-spec")[0].message


def test_a_failed_save_keeps_the_results(plant, tmp_path):
    process, _ = load_process(plant.root)

    def unsaved(model, save):
        return {**fake(model, save), "save_error": "IOException: read-only"}

    result = run(plant, process, "design", write=True, save=tmp_path / "x.dwxmz", solver=unsaved)
    assert result.written == 5
    assert [f.rule for f in result.findings if f.level == "warning"] == [
        "cheme.process-sim-not-saved"
    ]


def test_docker_states(monkeypatch, tmp_path):
    monkeypatch.delenv("CHEME_DWSIM_COMMAND", raising=False)
    monkeypatch.delenv("CHEME_DWSIM_PATH", raising=False)
    monkeypatch.setattr(dwsim.shutil, "which", lambda name: "/usr/bin/docker")

    def answer(code, stderr=""):
        return lambda docker, *a: subprocess.CompletedProcess(a, code, "", stderr)

    monkeypatch.setattr(dwsim, "_docker", answer(1, "Cannot connect to the Docker daemon"))
    with pytest.raises(dwsim.DwsimUnavailable, match="daemon is not running"):
        dwsim._command(None)
    monkeypatch.setattr(dwsim, "_docker", answer(1, "No such image"))
    with pytest.raises(dwsim.DwsimUnavailable, match="no Docker image"):
        dwsim._command(None)
    monkeypatch.setattr(dwsim, "_docker", answer(0))
    command, target, _, name = dwsim._command(tmp_path / "out" / "f.dwxmz")
    assert command[-1] == dwsim.IMAGE and name in command and target == "/out/f.dwxmz"
    assert f"{dwsim.WORKER.resolve()}:/opt/cheme/dwsim_worker.py:ro" in command
    monkeypatch.setenv("CHEME_DWSIM_PATH", "/opt/dwsim")
    command, target, env, name = dwsim._command(Path("rel/f.dwxmz"))
    assert Path(target).is_absolute() and name is None
    assert env["LD_LIBRARY_PATH"].startswith("/opt/dwsim:/opt/dwsim/ThermoCS")


def test_validate_reads_the_simulation_file(plant, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app
    from chemeascode.project.validate import validate_workspace

    def rename(d):
        d["specs"]["K2"] = d["specs"].pop("K1")
        d["specs"]["COMP"] = {"unit": "compressor"}

    _edit(plant, "process/simulation.yaml", rename)
    found = [f for f in validate_workspace(plant).findings if "sim-" in f.rule]
    assert [(f.rule, f.ids, f.file) for f in found] == [
        ("cheme.process-sim-unknown-step", ["K2"], "process/simulation.yaml"),
        ("cheme.process-sim-unknown-step", ["COMP"], "process/simulation.yaml"),
    ]
    assert "refined into steps" in found[1].message
    assert found[0].line
    monkeypatch.chdir(plant.root)
    shown = CliRunner().invoke(app, ["schema", "process-simulation"])
    assert shown.exit_code == 0 and "property_package" in shown.output


# -- the worker --------------------------------------------------------------------------------


def test_worker_reports_failures_as_json_on_stdout():
    done = subprocess.run(
        [sys.executable, "-I", str(dwsim.WORKER)],
        input="{}",
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert done.returncode == 1 and result["ok"] is False and "model" in result["error"]


@dwsim_tests
def test_dwsim_solves_the_example(plant, tmp_path):
    process, _ = load_process(plant.root)
    save = tmp_path / "out" / "example.dwxmz"
    result = run(plant, process, "design", write=True, save=save)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    assert save.is_file()
    t1, ratio, eta = 298.15, 800 / 101.325, 0.78
    ideal = t1 + t1 * (ratio ** (0.4 / 1.4) - 1) / eta
    assert _state(plant, "S2")["temperature"]["value"] == pytest.approx(ideal, abs=8.0)
    assert _state(plant, "S3")["temperature"]["value"] == pytest.approx(308.15, abs=0.01)
    assert _state(plant, "S3")["pressure"]["value"] == pytest.approx(780.0, rel=1e-6)
    flows = [_state(plant, s)["flow"]["value"] for s in ("S4", "S5")]
    assert flows == pytest.approx([700.0, 300.0], abs=0.01)
    # ideal-gas compressor power: m cp (T2 - T1), cp of air 1.005 kJ/kg/K
    power = 1000 / 3600 * 1.005 * (ideal - t1)
    assert _state(plant, "W1")["duty"]["value"] == pytest.approx(power, rel=0.05)
    # no recycle: one pass of the sequential solver
    entry = json.loads((plant.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["iterations"] == 1 and entry["status"] == "converged"


# -- separations: flash, heat exchanger, shortcut column ---------------------------------------


@pytest.fixture
def separation(tmp_path):
    shutil.copytree(EXAMPLES / "process-separation", tmp_path / "sep")
    return Workspace(tmp_path / "sep")


def test_translate_the_separation_example(separation):
    found = _model(separation)
    assert not [f for f in found.findings if f.level == "error"], found.findings
    units = {u["id"]: u for u in found.model["units"]}
    assert {k: u["type"] for k, u in units.items()} == {
        "V1": "valve",
        "D1": "flash",
        "E1": "heat_exchanger",
        "C1": "shortcut_column",
    }
    assert units["D1"]["outlets"] == ["S3", "S4"] and units["D1"]["spec"] == {}
    assert units["E1"]["inlets"] == ["S4", "H1"] and units["E1"]["outlets"] == ["S5", "H2"]
    assert units["E1"]["spec"]["cold_outlet_temperature_K"] == pytest.approx(343.15)
    assert units["E1"]["spec"]["hot_pressure_drop_Pa"] == pytest.approx(30000.0)
    c1 = units["C1"]
    assert c1["outlets"] == ["S6", "S7"]
    assert c1["energies"] == {"reboiler": "Q1", "condenser": "Q2"}
    assert found.energies == {"Q1": ("C1", "reboiler_kW"), "Q2": ("C1", "condenser_kW")}
    assert c1["spec"]["condenser_pressure_Pa"] == pytest.approx(520000.0)
    assert c1["spec"]["light_key"] == "C3" and c1["spec"]["condenser"] == "total"


def test_outlet_roles_and_pairs_by_spec_or_refused(separation):
    def rename(d):
        d["steps"][1]["ports"][1]["id"] = "a"
        d["steps"][1]["ports"][2]["id"] = "b"
        for s in d["streams"]:
            s["from"] = {"D1.vapour": "D1.a", "D1.liquid": "D1.b"}.get(s["from"], s["from"])
        d["steps"][2]["ports"][2]["id"] = "out1"
        for s in d["streams"]:
            s["from"] = {"E1.cold_out": "E1.out1"}.get(s["from"], s["from"])

    _edit(separation, "process/flowsheet.yaml", rename)
    _edit(
        separation, "process/flowsheet.yaml", lambda d: d["steps"][1]["ports"][1].pop("delegates")
    )
    found = _model(separation)
    why = {f.ids[0]: f for f in _errors(found, "sim-spec")}
    assert "which outlet is vapor" in why["D1"].message and "outlets:" in why["D1"].hint
    assert "belongs to inlet cold_in" in why["E1"].message and "pairs:" in why["E1"].hint

    def say(d):
        d["specs"]["D1"] = {"outlets": {"a": "liquid", "b": "vapor"}}
        d["specs"]["E1"]["pairs"] = {"cold_in": "out1", "hot_in": "hot_out"}

    _edit(separation, "process/simulation.yaml", say)
    found = _model(separation)
    units = {u["id"]: u for u in found.model["units"]}
    assert units["D1"]["outlets"] == ["S4", "S3"]  # vapour first, as DWSIM connects them
    assert units["E1"]["outlets"] == ["S5", "H2"]


def test_column_specs_are_checked(separation):
    def spoil(d):
        c1 = d["specs"]["C1"]
        c1.pop("reflux_ratio")
        c1["heavy_key"] = "C3"

    _edit(separation, "process/simulation.yaml", spoil)
    messages = " | ".join(f.message for f in _errors(_model(separation), "sim-spec"))
    assert "reflux_ratio not given" in messages and "the same component" in messages
    _edit(
        separation,
        "process/simulation.yaml",
        lambda d: d["specs"]["C1"].update(reflux_ratio=3.0, heavy_key="NC4", light_key="XX"),
    )
    assert "XX is not a component" in _errors(_model(separation), "sim-spec")[0].message


def test_two_stream_exchanger_class_without_spec_unit(separation):
    assert _model(separation).model["units"][2]["type"] == "heat_exchanger"
    from chemeascode.domains.process.simulation.translate import unit_of

    assert unit_of("ExchangingThermalEnergy") == "heater"
    assert unit_of("ExchangingThermalEnergy", 2) == "heat_exchanger"
    assert unit_of("SeparatingByGravity") == "flash"
    assert unit_of("VacuumDistilling") == "shortcut_column"


@dwsim_tests
def test_dwsim_solves_a_recycle(plant):
    _with_recycle(plant)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    flow = {k: _state(plant, k)["flow"]["value"] for k in ("S0", "S4", "S5", "S8", "S9")}
    assert flow["S0"] == pytest.approx(1250.0, abs=0.5)
    assert (flow["S4"], flow["S5"]) == pytest.approx((750.0, 250.0), abs=0.5)
    assert flow["S9"] == pytest.approx(flow["S8"], abs=1e-6)
    # the recycle, let down to 1 atm, mixes with the feed: S0 slightly warmer than ambient
    assert 298.15 < _state(plant, "S0")["temperature"]["value"] < 310.0
    # the recycle took several passes (DWSIM's Recycle.IterationsTaken)
    entry = json.loads((plant.root / "process/simulation-run.json").read_text())["cases"]["design"]
    assert entry["iterations"] > 1
    process, _ = load_process(plant.root)
    check = run(plant, process, "design", write=False)
    assert not [f for f in check.findings if f.level != "info"], check.findings


@dwsim_tests
def test_dwsim_expander_by_pressure_drop_and_outlet_pressure(plant):
    """K1 run backwards as an expander: 8 bar(a) air let down to 3 bar(a) does work and cools."""

    def as_expander(d):
        d["streams"][0]["state"]["design"]["pressure"]["value"] = 800

    _edit(plant, "process/flowsheet.yaml", as_expander)
    for spec in (
        {"pressure_drop": {"value": 5, "unit": "bar", "provenance": "assumed"}},
        {"outlet_pressure": {"value": 300, "provenance": "assumed"}},
    ):
        _edit(
            plant,
            "process/simulation.yaml",
            lambda d, spec=spec: d["specs"].update(
                K1={
                    "unit": "expander",
                    "efficiency": {"value": 0.8, "provenance": "assumed"},
                    **spec,
                }
            ),
        )
        process, _ = load_process(plant.root)
        result = run(plant, process, "design", write=False)
        assert not [f for f in result.findings if f.level == "error"], result.findings
        found = _model(plant)
        out = dwsim.solve(found.model)
        assert out["converged"], out["messages"]
        assert out["streams"]["S2"]["pressure_Pa"] == pytest.approx(300000.0)
        assert out["streams"]["S2"]["temperature_K"] < 298.15 - 50
        assert out["units"]["K1"]["duty_kW"] > 0


@dwsim_tests
def test_dwsim_solves_the_separation_example(separation):
    process, _ = load_process(separation.root)
    result = run(separation, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    s = {k: _state(separation, k) for k in ("S2", "S3", "S4", "S5", "S6", "S7", "H2")}
    flow = {k: v["flow"]["value"] for k, v in s.items()}
    # mass balances: flash, column; the exchanger keeps both flows
    assert flow["S3"] + flow["S4"] == pytest.approx(3600.0, abs=0.5)
    assert flow["S6"] + flow["S7"] == pytest.approx(flow["S4"], abs=0.5)
    assert flow["S5"] == pytest.approx(flow["S4"], abs=0.01)
    # the valve cools the feed (Joule-Thomson and flash), the flash is adiabatic at 6 bar(a)
    assert s["S2"]["pressure"]["value"] == pytest.approx(6.0)
    assert s["S2"]["temperature"]["value"] < 45.0
    assert s["S3"]["temperature"]["value"] == pytest.approx(s["S2"]["temperature"]["value"])
    assert s["S3"]["composition"]["values"]["C3"] > s["S4"]["composition"]["values"]["C3"]
    # the exchanger meets its spec and cools the pentane
    assert s["S5"]["temperature"]["value"] == pytest.approx(70.0, abs=0.01)
    assert s["S5"]["pressure"]["value"] == pytest.approx(5.7)
    assert s["H2"]["temperature"]["value"] < 150.0
    # the column meets its key specs; the distillate boils near propane's 5.2 bar(a) point
    assert s["S7"]["composition"]["values"]["C3"] == pytest.approx(0.01, abs=1e-4)
    assert s["S6"]["composition"]["values"]["NC4"] == pytest.approx(0.02, abs=1e-4)
    assert 0.0 < s["S6"]["temperature"]["value"] < 8.0
    assert _state(separation, "Q1")["duty"]["value"] > 0
    assert _state(separation, "Q2")["duty"]["value"] > 0
    assert any("minimum reflux ratio" in line for line in result.lines)


def _rigorous(d):
    d["specs"]["C1"] = {
        "stages": 18,
        "feed_stage": 9,
        "condenser_pressure": {"value": 5.2, "provenance": "assumed"},
        "reboiler_pressure": {"value": 5.5, "provenance": "assumed"},
        "condenser_spec": {"reflux_ratio": 3.5},
        "reboiler_spec": {"mole_fraction": {"C3": 0.01}},
    }


def test_rigorous_column_translation(separation):
    _edit(separation, "process/simulation.yaml", _rigorous)
    c1 = next(u for u in _model(separation).model["units"] if u["id"] == "C1")
    assert c1["type"] == "distillation_column"
    assert c1["spec"]["feed_stages"] == [9] and c1["spec"]["stages"] == 18
    assert c1["spec"]["condenser_spec"] == {
        "type": "Stream_Ratio",
        "value": 3.5,
        "unit": "",
        "component": None,
    }
    assert c1["spec"]["reboiler_spec"] == {
        "type": "Component_Fraction",
        "value": 0.01,
        "unit": "M",
        "component": "C3",
    }

    def spoil(d):
        c = d["specs"]["C1"]
        c["feed_stage"] = 18
        c["reboiler_spec"] = {"reflux_ratio": 2.0}
        c["condenser_spec"] = {"flow": {"value": 900, "provenance": "assumed"}, "reflux_ratio": 2}

    _edit(separation, "process/simulation.yaml", spoil)
    messages = " | ".join(f.message for f in _errors(_model(separation), "sim-spec"))
    assert "feed stage of in is not between 2 and 17" in messages
    assert "reflux_ratio is a condenser spec" in messages
    assert "condenser_spec: give exactly one" in messages


@dwsim_tests
def test_dwsim_solves_a_rigorous_column(separation):
    _edit(separation, "process/simulation.yaml", _rigorous)
    process, _ = load_process(separation.root)
    result = run(separation, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    s6, s7, s4 = (_state(separation, k) for k in ("S6", "S7", "S4"))
    assert s7["composition"]["values"]["C3"] == pytest.approx(0.01, abs=1e-5)
    assert s6["composition"]["values"]["C3"] > 0.9
    assert s6["flow"]["value"] + s7["flow"]["value"] == pytest.approx(s4["flow"]["value"], abs=0.5)
    assert s6["pressure"]["value"] == pytest.approx(5.2) and s7["pressure"][
        "value"
    ] == pytest.approx(5.5)
    assert any("reflux ratio 3.5" in line for line in result.lines)


# -- partial simulation, energy directions, component separator, multi-stream exchanger -------


def test_exclude_simulates_the_rest(plant):
    _edit(plant, "process/simulation.yaml", lambda d: d.update(exclude=["DIST"]))
    found = _model(plant)
    assert [u["id"] for u in found.model["units"]] == ["K1", "E1"]
    assert found.outlets == ["S2", "S3"]
    _edit(plant, "process/simulation.yaml", lambda d: d.update(exclude=["K1"]))
    found = _model(plant)
    assert any(f.ids == ["S2"] and f.rule.endswith("sim-feed-incomplete") for f in found.findings)


def test_second_service_energy_is_ignored(plant):
    def cooling_water(d):
        d["steps"][0]["ports"].append({"id": "cw", "direction": "out", "kind": "energy"})
        d["products"].append(
            {"id": "CW", "ports": [{"id": "q", "direction": "in", "kind": "energy"}]}
        )
        d["streams"].append({"id": "Q9", "kind": "energy", "from": "K1.cw", "to": "CW.q"})

    _edit(plant, "process/flowsheet.yaml", cooling_water)
    found = _model(plant)
    assert found.model is not None and found.energies == {"W1": ("K1", "duty_kW")}
    ignored = [f for f in found.findings if f.rule.endswith("sim-energy-ignored")]
    assert ignored[0].ids == ["Q9"] and "runs out of the unit" in ignored[0].message


COLD_BOX = {
    "plant.yaml": """\
name: cold-box
stage: concept
sheets: []
""",
    "process/materials.yaml": """\
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, cas: 7727-37-9, molar_mass: 28.014}
  - {id: O2, name: Oxygen, cas: 7782-44-7, molar_mass: 31.998}
  - {id: AR, name: Argon, cas: 7440-37-1, molar_mass: 39.948}
  - {id: H2O, name: Water, cas: 7732-18-5, molar_mass: 18.015}
templates:
  - {id: air, components: [N2, O2, AR, H2O]}
""",
    "process/flowsheet.yaml": """\
# Wet air dried, then cooled against waste nitrogen and gaseous oxygen
schema: cheme/process/v1
kind: flowsheet
units: {pressure: kPa(a), temperature: K, flow: kg/h, duty: kW, enthalpy: kJ/kmol}
feeds:
  - {id: AIR, ports: [{id: out, direction: out}]}
  - {id: WN2, ports: [{id: out, direction: out}]}
  - {id: GOX, ports: [{id: out, direction: out}]}
products:
  - id: P
    ports:
      - {id: air, direction: in}
      - {id: water, direction: in}
      - {id: wn2, direction: in}
      - {id: gox, direction: in}
blocks:
  - id: A1
    class: Adsorbing
    ports: [{id: in, direction: in}, {id: dry, direction: out}, {id: water, direction: out}]
  - id: E1
    class: ExchangingThermalEnergy
    ports:
      - {id: air_in, direction: in}
      - {id: wn2_in, direction: in}
      - {id: gox_in, direction: in}
      - {id: air_out, direction: out}
      - {id: wn2_out, direction: out}
      - {id: gox_out, direction: out}
streams:
  - id: S1
    from: AIR.out
    to: A1.in
    template: air
    state:
      design:
        pressure: {value: 600, provenance: given}
        temperature: {value: 300, provenance: given}
        flow: {value: 1000, provenance: given}
        composition:
          basis: mole_fraction
          values: {N2: 0.776, O2: 0.208, AR: 0.0093, H2O: 0.0067}
          provenance: given
  - id: S2
    from: A1.dry
    to: E1.air_in
    template: air
  - id: S3
    from: A1.water
    to: P.water
    template: air
  - id: S4
    from: E1.air_out
    to: P.air
    template: air
  - id: W1
    from: WN2.out
    to: E1.wn2_in
    template: air
    state:
      design:
        pressure: {value: 130, provenance: given}
        temperature: {value: 160, provenance: given}
        flow: {value: 700, provenance: given}
        composition: {basis: mole_fraction, values: {N2: 1.0}, provenance: given}
  - id: W2
    from: E1.wn2_out
    to: P.wn2
    template: air
  - id: G1
    from: GOX.out
    to: E1.gox_in
    template: air
    state:
      design:
        pressure: {value: 150, provenance: given}
        temperature: {value: 160, provenance: given}
        flow: {value: 250, provenance: given}
        composition: {basis: mole_fraction, values: {O2: 1.0}, provenance: given}
  - id: G2
    from: E1.gox_out
    to: P.gox
    template: air
""",
    "process/simulation.yaml": """\
schema: cheme/simulation/v1
kind: simulation
specs:
  A1:
    recoveries: {H2O: 1.0}
    recovery_outlet: water
    basis_source: test fixture (a full drying split, not data)
    operating_basis: TSA at the inlet conditions
  E1:
    outlet_temperatures:
      air_in: {value: 200, provenance: assumed}
      wn2_in: {value: 290, provenance: assumed}
    pressure_drops:
      air_in: {value: 10, unit: kPa, provenance: assumed}
""",
}


@pytest.fixture
def cold_box(tmp_path):
    root = tmp_path / "cold-box"
    for name, text in COLD_BOX.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    return Workspace(root)


def test_component_separator_and_multi_stream_exchanger_translation(cold_box):
    found = _model(cold_box)
    assert not [f for f in found.findings if f.level == "error"], found.findings
    a1, e1 = found.model["units"]
    assert (a1["type"], a1["outlets"], a1["spec"]) == (
        "component_separator",
        ["S2", "S3"],
        {"recoveries": {"H2O": 1.0}, "recovery_outlet": 1},
    )
    assert e1["type"] == "multi_stream_exchanger"
    assert e1["inlets"] == ["S2", "W1", "G1"] and e1["outlets"] == ["S4", "W2", "G2"]
    assert [s["outlet_temperature_K"] for s in e1["spec"]["sides"]] == [200.0, 290.0, None]
    assert e1["spec"]["sides"][0]["pressure_drop_Pa"] == pytest.approx(10000.0)

    _edit(
        cold_box, "process/simulation.yaml", lambda d: d["specs"]["E1"].pop("outlet_temperatures")
    )
    assert "at most one stream" in _errors(_model(cold_box), "sim-spec")[0].message


def test_specified_split_keeps_its_basis_apart_from_predictive_units(cold_box):
    from chemeascode.domains.process.simulation import record

    found = _model(cold_box)
    assert not [f for f in found.findings if f.level in ("error", "warning")], found.findings
    assert found.bases["A1"] == {
        "basis": "specified",
        "source": "test fixture (a full drying split, not data)",
        "operating_basis": "TSA at the inlet conditions",
    }
    assert found.bases["E1"] == {"basis": "predictive"}
    rows = {
        r["id"]: r for r in record.unit_rows(found.model, {"A1": {}}, True, [], [], {}, found.bases)
    }
    assert rows["A1"]["basis"] == "specified" and rows["A1"]["note"] == record.SPECIFIED_NOTE
    assert rows["A1"]["basis_source"].startswith("test fixture")
    assert rows["E1"]["basis"] == "predictive" and "note" not in rows["E1"]
    # the basis is not part of the model: its fingerprint stays
    fingerprint = found.fingerprint

    def unsourced(d):
        d["specs"]["A1"].pop("basis_source")
        d["specs"]["A1"].pop("operating_basis")

    _edit(cold_box, "process/simulation.yaml", unsourced)
    found = _model(cold_box)
    assert found.fingerprint == fingerprint
    warned = [f for f in found.findings if f.rule == "cheme.process-sim-specified-unsourced"]
    assert len(warned) == 1 and warned[0].level == "warning" and warned[0].line
    assert found.model is not None  # a warning, the model is still made

    _edit(
        cold_box, "process/simulation.yaml", lambda d: d["specs"]["A1"].update(basis="predictive")
    )
    errors = _errors(_model(cold_box), "sim-spec")
    assert "basis predictive, but a component_separator is specified" in errors[0].message
    _edit(cold_box, "process/simulation.yaml", lambda d: d["specs"]["A1"].update(basis="specified"))
    assert _model(cold_box).model is not None


@dwsim_tests
def test_dwsim_solves_the_cold_box(cold_box):
    process, _ = load_process(cold_box.root)
    result = run(cold_box, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    state = {k: _state(cold_box, k) for k in ("S2", "S3", "S4", "W2", "G2")}
    assert state["S2"]["composition"]["values"]["H2O"] == pytest.approx(0.0, abs=1e-9)
    assert state["S3"]["composition"]["values"]["H2O"] == pytest.approx(1.0)
    assert state["S2"]["flow"]["value"] + state["S3"]["flow"]["value"] == pytest.approx(1000.0)
    assert state["S4"]["temperature"]["value"] == pytest.approx(200.0)
    assert state["S4"]["pressure"]["value"] == pytest.approx(590.0)
    assert state["W2"]["temperature"]["value"] == pytest.approx(290.0)
    # the oxygen closes the balance: it warms, but less than the air cools it could
    assert 160.0 < state["G2"]["temperature"]["value"] < 300.0
    assert any("imbalance" in line for line in result.lines)
    line = next(line for line in result.lines if line.startswith("E1:"))
    imbalance = float(line.split("imbalance ")[1].split()[0])
    assert abs(imbalance) < 1e-3


@dwsim_tests
def test_dwsim_reports_an_unbalanced_exchanger(cold_box):
    def all_fixed(d):
        d["specs"]["E1"]["outlet_temperatures"]["gox_in"] = {"value": 295, "provenance": "assumed"}

    _edit(cold_box, "process/simulation.yaml", all_fixed)
    process, _ = load_process(cold_box.root)
    result = run(cold_box, process, "design", write=False)
    assert [f.rule for f in result.findings if f.level == "warning"] == [
        "cheme.process-sim-unbalanced"
    ]


def _intercooled(d):
    d["specs"]["K1"].update(
        stages=3,
        outlet_temperature={"value": 308.15, "provenance": "assumed"},
        pressure_drop={"value": 10, "unit": "kPa", "provenance": "assumed"},
    )


def test_intercooled_compressor_translation(plant):
    _edit(plant, "process/simulation.yaml", _intercooled)
    k1 = _model(plant).model["units"][0]
    assert k1["spec"]["stages"] == 3 and k1["spec"]["outlet_temperature_K"] == 308.15
    assert k1["spec"]["cooler_pressure_drop_Pa"] == pytest.approx(10000.0)
    assert k1["energies"] == {"energy": "W1", "cooling": None}
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["K1"].pop("outlet_temperature"))
    assert "stages without outlet_temperature" in _errors(_model(plant), "sim-spec")[0].message


@dwsim_tests
def test_dwsim_intercooled_compressor(plant):
    _edit(plant, "process/simulation.yaml", _intercooled)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    s2 = _state(plant, "S2")
    assert s2["temperature"]["value"] == pytest.approx(308.15)
    assert s2["pressure"]["value"] == pytest.approx(800.0, rel=1e-5)
    power = _state(plant, "W1")["duty"]["value"]
    # three stages of ratio ~2, ideal gas: about 3 x m cp dT = 70 kW, below one stage's 86 kW
    assert 60.0 < power < 80.0
    line = next(line for line in result.lines if line.startswith("K1:"))
    assert "cooling" in line


def test_review_fixes_m3(plant, separation):
    from chemeascode.domains.process.simulation.translate import unit_of

    assert unit_of("Evaporating") is None and unit_of("Drying") is None
    assert unit_of("Adsorbing") == "component_separator"
    assert unit_of("Filtering") == "component_separator"

    def heat_out(d):
        d["steps"][1]["class"] = "ExchangingThermalEnergy"
        d["steps"][1]["ports"].append({"id": "q", "direction": "out", "kind": "energy"})
        d["products"].append(
            {"id": "CW", "ports": [{"id": "q", "direction": "in", "kind": "energy"}]}
        )
        d["streams"].append({"id": "Q5", "kind": "energy", "from": "E1.q", "to": "CW.q"})

    _edit(plant, "process/flowsheet.yaml", heat_out)
    e1 = next(u for u in _model(plant).model["units"] if u["id"] == "E1")
    assert e1["type"] == "heater" and e1["energies"] == {"energy": "Q5"}

    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"]["E1"].update(pressure_drop={"value": -5, "provenance": "assumed"}),
    )
    assert "is negative" in _errors(_model(plant), "sim-spec")[0].message


def test_exclude_takes_values_of_an_earlier_simulation(plant):
    process, _ = load_process(plant.root)
    run(plant, process, "design", write=True, solver=fake)
    _edit(plant, "process/simulation.yaml", lambda d: d.update(exclude=["K1"]))
    found = _model(plant)
    assert found.model is not None, found.findings
    assert found.model["streams"][0]["id"] == "S2"
    assert found.model["streams"][0]["feed"]["temperature_K"] == pytest.approx(598.0)


def test_validate_points_at_exclude_entries_and_excluded_specs(plant):
    from chemeascode.project.validate import validate_workspace

    _edit(plant, "process/simulation.yaml", lambda d: d.update(exclude=["K1", "NOPE"]))
    found = [f for f in validate_workspace(plant).findings if "sim-" in f.rule]
    messages = {f.ids[0]: f for f in found}
    assert "no step or block NOPE" in messages["NOPE"].message
    assert "excluded; its specs are not used" in messages["K1"].message
    text = (plant.root / "process/simulation.yaml").read_text().splitlines()
    assert "NOPE" in text[messages["NOPE"].line - 1]


@dwsim_tests
def test_dwsim_intercooled_train_by_pressure_increase_and_unreachable_target(plant):
    def increase(d):
        _intercooled(d)
        d["specs"]["K1"].pop("outlet_pressure")
        d["specs"]["K1"]["pressure_increase"] = {
            "value": 698.675,
            "unit": "kPa",
            "provenance": "assumed",
        }

    _edit(plant, "process/simulation.yaml", increase)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    assert _state(plant, "S2")["pressure"]["value"] == pytest.approx(800.0, rel=1e-5)

    def unreachable(d):
        d["specs"]["K1"].pop("pressure_increase")
        d["specs"]["K1"]["outlet_pressure"] = {"value": 50, "provenance": "assumed"}

    _edit(plant, "process/simulation.yaml", unreachable)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=False)
    stuck = [f for f in result.findings if f.rule.endswith("sim-not-converged")]
    assert stuck and "below the inlet" in stuck[0].message


def test_drive_efficiency_gives_electric_power(plant):
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"]["K1"].update(
            drive_efficiency={"value": 0.95, "provenance": "assumed"}
        ),
    )
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True, solver=fake)
    assert _state(plant, "W1")["duty"]["value"] == pytest.approx(84.2 / 0.95, rel=1e-5)
    line = next(line for line in result.lines if line.startswith("K1:"))
    assert "shaft 84.2 kW" in line
    _edit(
        plant,
        "process/simulation.yaml",
        lambda d: d["specs"]["E1"].update(
            drive_efficiency={"value": 0.95, "provenance": "assumed"}
        ),
    )
    assert "drive_efficiency is for" in _errors(_model(plant), "sim-spec")[0].message


# -- the double column: partial condenser, no reboiler, no condenser, side draws ---------------


@pytest.fixture
def double(tmp_path):
    shutil.copytree(EXAMPLES / "process-double-column", tmp_path / "dc")
    return Workspace(tmp_path / "dc")


def test_translate_the_double_column(double):
    found = _model(double)
    assert not [f for f in found.findings if f.level == "error"], found.findings
    c1, c2 = found.model["units"]
    assert (c1["type"], c2["type"]) == ("distillation_column", "distillation_column")
    # vapour, distillate, bottoms, then the side draws
    assert c1["outlets"] == ["S2", "S4", "S5", "S3"]
    assert c1["spec"]["condenser"] == "partial" and c1["spec"]["reboiler"] is False
    assert c1["spec"]["vapor_flow"] == {"value": 12510.0, "basis": "mass"}
    assert c1["spec"]["side_draws"] == [
        {"stage": 2, "phase": "liquid", "value": 470.0, "basis": "mass"}
    ]
    assert c1["spec"].get("reboiler_spec") is None
    assert c2["outlets"] == ["S7", "S9", "S8"]
    assert c2["inlets"] == ["S4", "S5", "S6"] and c2["spec"]["feed_stages"] == [1, 22, 24]
    assert c2["spec"]["condenser"] == "none" and c2["spec"].get("condenser_spec") is None
    assert c2["spec"]["heat_integration"] == {"condenser_of": "C1", "min_approach_K": 1.0}


def test_double_column_specs_are_checked(double):
    def spoil(d):
        d["specs"]["C1"].pop("vapor_flow")
        d["specs"]["C1"]["reboiler_spec"] = {"reflux_ratio": 2}
        d["specs"]["C2"]["condenser_spec"] = {"reflux_ratio": 1}
        d["specs"]["C2"]["side_draws"]["gox"]["stage"] = 70

    _edit(double, "process/simulation.yaml", spoil)
    messages = " | ".join(f.message for f in _errors(_model(double), "sim-spec"))
    assert "vapor_flow not given" in messages
    assert "reboiler_spec is given, but the column has no reboiler" in messages
    assert "condenser_spec is given, but the column has no condenser" in messages
    assert "side draw gox at stage 70" in messages
    shutil.rmtree(double.root)
    shutil.copytree(EXAMPLES / "process-double-column", double.root)
    _edit(
        double,
        "process/simulation.yaml",
        lambda d: d["specs"]["C2"]["heat_integration"].update(condenser_of="C9"),
    )
    assert "condenser_of C9 is no other simulated" in _errors(_model(double), "sim-spec")[0].message


@dwsim_tests
def test_dwsim_solves_the_double_column(double):
    process, _ = load_process(double.root)
    result = run(double, process, "design", write=True)
    errors = [f for f in result.findings if f.level == "error" or "not-converged" in f.rule]
    assert not errors, result.findings
    # the condenser-reboiler: checked, warned about the duty difference, not the approach
    assert [f.rule for f in result.findings if f.level == "warning"] == [
        "cheme.process-sim-reboiler-unbalanced"
    ]
    s = {k: _state(double, k) for k in ("S2", "S3", "S4", "S5", "S7", "S8", "S9")}
    flow = {k: v["flow"]["value"] for k, v in s.items()}
    x = {k: v["composition"]["values"] for k, v in s.items()}
    assert flow["S2"] == pytest.approx(12510.0, rel=1e-3)  # GAN by mass, iterated
    assert flow["S3"] == pytest.approx(470.0, rel=1e-3)  # LIN side draw
    assert flow["S8"] == pytest.approx(20860.0, rel=1e-3)  # GOX side draw
    assert flow["S9"] == pytest.approx(470.0, rel=1e-3)  # LOX
    assert sum(flow[k] for k in ("S2", "S3", "S4", "S5")) == pytest.approx(83190.0, rel=1e-4)
    feed_lp = flow["S4"] + flow["S5"] + 14870.0
    assert flow["S7"] + flow["S8"] + flow["S9"] == pytest.approx(feed_lp, rel=1e-4)
    assert x["S2"]["N2"] > 0.998 and x["S4"]["N2"] > 0.998
    assert 0.35 < x["S5"]["O2"] < 0.42  # rich liquid
    assert x["S7"]["N2"] > 0.96 and x["S8"]["O2"] > 0.97
    # the HP column's top condenses above the LP sump's boiling point
    c1 = next(line for line in result.lines if line.startswith("C1:"))
    c2 = next(line for line in result.lines if line.startswith("C2:"))
    top = float(c1.split("top ")[1].split(" K")[0])
    bottom = float(c2.split("bottom ")[1].split(" K")[0])
    assert top - bottom > 1.0


@dwsim_tests
def test_dwsim_double_column_inside_the_balance_check(double):
    # 9 % more air: DWSIM's default column tolerances failed the HP column on a component
    # balance missing by 1.32e-4
    def more_air(d):
        s1 = next(s for s in d["streams"] if s["id"] == "S1")
        s1["state"]["design"]["flow"]["value"] = 91030

    _edit(double, "process/flowsheet.yaml", more_air)
    process, _ = load_process(double.root)
    result = run(double, process, "design", write=True)
    errors = [f for f in result.findings if f.level == "error" or "not-converged" in f.rule]
    assert not errors, result.findings
    assert _state(double, "S8")["composition"]["values"]["O2"] > 0.97  # GOX: a sensible column


KIJ_AR_O2 = {"components": ["AR", "O2"], "kij": {"value": 0.0143, "provenance": "assumed"}}


def test_interaction_parameters_translate(double):
    assert "interaction_parameters" not in _model(double).model  # the fingerprint stays
    _edit(double, "process/simulation.yaml", lambda d: d.update(interaction_parameters=[KIJ_AR_O2]))
    found = _model(double)
    assert found.model["interaction_parameters"] == [{"components": ["AR", "O2"], "kij": 0.0143}]
    # the pair in the other order: the same model, the same fingerprint
    reversed_ = KIJ_AR_O2 | {"components": ["O2", "AR"]}
    _edit(double, "process/simulation.yaml", lambda d: d.update(interaction_parameters=[reversed_]))
    assert _model(double).fingerprint == found.fingerprint

    def wrong(d):
        d["interaction_parameters"] = [
            KIJ_AR_O2 | {"components": ["AR", "AR"]},
            KIJ_AR_O2 | {"components": ["AR", "CO2"]},
            KIJ_AR_O2,
            reversed_,
        ]

    _edit(double, "process/simulation.yaml", wrong)
    messages = [f.message for f in _errors(_model(double), "sim-spec")]
    assert any("AR with itself" in m for m in messages)
    assert any("CO2 in no feed" in m for m in messages)
    assert any("O2 / AR: given twice" in m for m in messages)
    _edit(double, "process/simulation.yaml", lambda d: d.update(property_package="NRTL"))
    messages = [f.message for f in _errors(_model(double), "sim-spec")]
    assert sum("the NRTL package has none" in m for m in messages) == 4


@dwsim_tests
def test_dwsim_interaction_parameters(double):
    # the Ar/O2 kij fitted to the reference VLE (above DWSIM's 0.0107): argon is easier to
    # strip from the LP sump, so the same column makes purer GOX (a little: it is pinched)
    def gox():
        process, _ = load_process(double.root)
        result = run(double, process, "design", write=True)
        assert not [f for f in result.findings if f.level == "error"], result.findings
        return _state(double, "S8")["composition"]["values"]["O2"]

    default = gox()
    _edit(double, "process/simulation.yaml", lambda d: d.update(interaction_parameters=[KIJ_AR_O2]))
    assert gox() > default + 3e-4
    # SRK has no Ar/O2 entry: the pair is added
    _edit(
        double,
        "process/simulation.yaml",
        lambda d: d.update(property_package="Soave-Redlich-Kwong (SRK)"),
    )
    with_kij = gox()
    _edit(double, "process/simulation.yaml", lambda d: d.update(interaction_parameters=[]))
    assert with_kij > gox() + 3e-4


def test_rigorous_options_are_refused_elsewhere(double, separation):
    _edit(
        separation,
        "process/simulation.yaml",
        lambda d: d["specs"]["C1"].update(reboiler=False, heat_integration={"condenser_of": "C1"}),
    )
    message = _errors(_model(separation), "sim-spec")[0].message
    assert "reboiler: false, heat_integration: for rigorous columns only" in message
    _edit(
        double,
        "process/simulation.yaml",
        lambda d: d["specs"]["C1"].update(
            reboiler=True,
            reboiler_spec={"duty": {"value": 1, "provenance": "assumed"}},
            heat_integration={"condenser_of": "C1"},
        ),
    )
    assert any(
        "no other simulated rigorous column" in f.message
        for f in _errors(_model(double), "sim-spec")
    )


# -- condensate: coolers and intercooled compressors with a drain -------------------------------


def _wet(d_materials, d_flowsheet, d_simulation):
    d_materials["components"].append(
        {"id": "H2O", "name": "Water", "cas": "7732-18-5", "molar_mass": 18.015}
    )
    d_materials["templates"][0]["components"].append("H2O")
    s1 = d_flowsheet["streams"][0]["state"]["design"]
    s1["composition"]["values"] = {"N2": 0.7578, "O2": 0.2033, "AR": 0.0089, "H2O": 0.03}
    k1, e1 = d_flowsheet["steps"][0], d_flowsheet["steps"][1]
    k1["ports"].append({"id": "condensate", "direction": "out"})
    e1["ports"].append({"id": "drain", "direction": "out"})
    d_flowsheet["products"].append(
        {
            "id": "COND",
            "ports": [{"id": "k1", "direction": "in"}, {"id": "e1", "direction": "in"}],
        }
    )
    d_flowsheet["streams"] += [
        {"id": "C1", "from": "K1.condensate", "to": "COND.k1", "template": "air"},
        {"id": "C2", "from": "E1.drain", "to": "COND.e1", "template": "air"},
    ]
    d_simulation["specs"]["K1"].update(
        stages=2, outlet_temperature={"value": 313.15, "provenance": "assumed"}
    )


def _make_wet(ws):
    paths = ("process/materials.yaml", "process/flowsheet.yaml", "process/simulation.yaml")
    docs = [yaml.safe_load((ws.root / p).read_text()) for p in paths]
    _wet(*docs)
    for p, d in zip(paths, docs, strict=True):
        (ws.root / p).write_text(yaml.safe_dump(d, sort_keys=False))


def test_condensate_outlets_translate(plant):
    _make_wet(plant)
    units = {u["id"]: u for u in _model(plant).model["units"]}
    assert units["K1"]["outlets"] == ["S2", "C1"] and units["K1"]["roles"] == ["gas", "condensate"]
    assert units["E1"]["outlets"] == ["S3", "C2"] and units["E1"]["roles"] == ["gas", "condensate"]

    def uncooled(d):
        d["specs"]["K1"].pop("outlet_temperature")
        d["specs"]["K1"].pop("stages")

    _edit(plant, "process/simulation.yaml", uncooled)
    assert "needs coolers" in _errors(_model(plant), "sim-spec")[0].message


@dwsim_tests
def test_dwsim_condensate(plant):
    _make_wet(plant)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    s = {k: _state(plant, k) for k in ("S2", "S3", "C1", "C2")}
    flow = {k: v["flow"]["value"] for k, v in s.items()}
    assert flow["S3"] + flow["C1"] + flow["C2"] == pytest.approx(1000.0, abs=0.1)
    assert s["C1"]["composition"]["values"]["H2O"] > 0.99  # the drains are water
    assert flow["C1"] > 0 and flow["C2"] > 0
    # the gas leaves the aftercooler saturated: p_sat(35 C) 5.63 kPa at 780 kPa(a)
    assert s["S3"]["composition"]["values"]["H2O"] == pytest.approx(5.63 / 780, rel=0.1)


def _drains_only(ws):
    """The drains of _wet without the water: nothing condenses."""
    paths = ("process/materials.yaml", "process/flowsheet.yaml", "process/simulation.yaml")
    docs = [yaml.safe_load((ws.root / p).read_text()) for p in paths]
    _wet(*docs)
    docs[0]["components"] = [c for c in docs[0]["components"] if c["id"] != "H2O"]
    docs[0]["templates"][0]["components"].remove("H2O")
    docs[1]["streams"][0]["state"]["design"]["composition"]["values"] = {
        "N2": 0.7812,
        "O2": 0.2096,
        "AR": 0.0092,
    }
    for p, d in zip(paths, docs, strict=True):
        (ws.root / p).write_text(yaml.safe_dump(d, sort_keys=False))


def test_condensate_naming_and_limits(plant):
    _make_wet(plant)
    _edit(
        plant, "process/simulation.yaml", lambda d: d["specs"]["E1"].update(outlets={"out": "gas"})
    )
    e1 = next(u for u in _model(plant).model["units"] if u["id"] == "E1")
    assert e1["outlets"] == ["S3", "C2"]
    _edit(plant, "process/simulation.yaml", lambda d: d["specs"]["K1"].update(stages=7))
    found = _errors(_model(plant), "sim-spec")
    assert "at most six condensate drains" in found[0].message


def test_flash_models_keep_their_fingerprint(separation):
    flash = next(u for u in _model(separation).model["units"] if u["type"] == "flash")
    assert "roles" not in flash


@dwsim_tests
def test_dwsim_drains_without_condensate(plant):
    _drains_only(plant)
    process, _ = load_process(plant.root)
    result = run(plant, process, "design", write=True)
    assert not [f for f in result.findings if f.level in ("error", "warning")], result.findings
    assert _state(plant, "S3")["flow"]["value"] == pytest.approx(1000.0, abs=0.1)
    assert _state(plant, "C1")["flow"]["value"] == pytest.approx(0.0, abs=0.01)
