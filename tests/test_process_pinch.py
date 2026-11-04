"""Whole-plant pinch targets: the thermal-stream extraction
(domains/process/heat_integration/streams.py), the report (heat_integration/report.py) and
``cheme process pinch``.

The extraction cases are hand-made simulator results (no DWSIM), chosen so that every class,
sum and target follows by hand (the arithmetic is in each test); they are bookkeeping numbers,
not property data. The utility-placement case is the four-stream example of Kemp, Pinch
Analysis and Process Integration (2nd ed.), as in tests/test_pinch.py (duties in kW): minimum
hot utility 20, cold 60, pinch 90/80 degC at dTmin 10 K. The end-to-end case is hda-1 of the
process library with its recorded DWSIM run (tests/data/README.md).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from chemeascode.domains.process.heat_integration import report as pinch_report_module
from chemeascode.domains.process.heat_integration.report import PinchReport, _targets
from chemeascode.domains.process.heat_integration.streams import (
    REACTOR_REASON,
    run_duties,
    thermal_streams,
)

C = 273.15
DATA = Path(__file__).resolve().parent / "data"


def _unit(uid, kind, inlets, outlets, energies=None, spec=None):
    return {
        "id": uid,
        "type": kind,
        "inlets": inlets,
        "outlets": outlets,
        "energies": energies or {},
        "spec": spec or {},
    }


def _out(units, temperatures):
    return {
        "converged": True,
        "units": units,
        "streams": {sid: {"temperature_K": t} for sid, t in temperatures.items()},
    }


def _terminal(tid, category="utility"):
    return SimpleNamespace(id=tid, category=category)


def _process(feeds, products, streams):
    """A flowsheet stand-in with terminals and the streams' ends (``from_``, ``to``)."""
    return SimpleNamespace(
        flowsheet=SimpleNamespace(
            feeds=feeds,
            products=products,
            streams=[SimpleNamespace(id=s, from_=a, to=b) for s, a, b in streams],
        )
    )


# -- Kemp's four streams on an existing plant: an exchanger and utilities --------------------


def kemp_plant():
    """Kemp's streams (H1 170 -> 60 degC at 3 kW/K, H2 150 -> 30 at 1.5, C1 20 -> 135 at 2, C2
    80 -> 140 at 4) as a plant with one exchanger E1 (H1 170 -> 130 against C1 75 -> 135:
    120 kW) and the rest on utilities: coolers K1 (H1 130 -> 60, 210 kW) and K2 (H2, 180 kW),
    heaters W1 (C1 20 -> 75, 110 kW) and W2 (C2, 240 kW). Current utility: hot 110 + 240 =
    350, cold 210 + 180 = 390 kW."""
    model = {
        "units": [
            _unit("E1", "heat_exchanger", ["h1a", "c1b"], ["h1b", "c1c"]),
            _unit("K1", "cooler", ["h1b"], ["h1c"], {"energy": "q1"}),
            _unit("K2", "cooler", ["h2a"], ["h2b"], {"energy": "q2"}),
            _unit("W1", "heater", ["c1a"], ["c1b"], {"energy": "q3"}),
            _unit("W2", "heater", ["c2a"], ["c2b"], {"energy": "q4"}),
        ]
    }
    out = _out(
        {
            "E1": {"duty_kW": 120.0},
            "K1": {"duty_kW": -210.0},
            "K2": {"duty_kW": -180.0},
            "W1": {"duty_kW": 110.0},
            "W2": {"duty_kW": 240.0},
        },
        {
            "h1a": 170 + C,
            "h1b": 130 + C,
            "h1c": 60 + C,
            "h2a": 150 + C,
            "h2b": 30 + C,
            "c1a": 20 + C,
            "c1b": 75 + C,
            "c1c": 135 + C,
            "c2a": 80 + C,
            "c2b": 140 + C,
        },
    )
    process = _process(
        [_terminal("STEAM")],
        [_terminal("CW")],
        [("q1", "K1.q", "CW.in"), ("q3", "STEAM.out", "W1.q")],
    )
    return model, out, process


def test_extraction_classes_and_no_double_counting_of_the_exchanger():
    model, out, process = kemp_plant()
    ex = thermal_streams(model, out, "design", process=process)
    by_id = {s.id: s for s in ex.streams}
    assert set(by_id) == {"E1:h1a", "E1:c1b", "K1", "K2", "W1", "W2"}
    assert {by_id["E1:h1a"].category, by_id["E1:c1b"].category} == {"recovery"}
    assert (by_id["E1:h1a"].side, by_id["E1:c1b"].side) == ("hot", "cold")
    # the exchanger's duty counts once: the hot side carries it, the cold side is the same heat
    assert (by_id["E1:h1a"].counted_kW, by_id["E1:c1b"].counted_kW) == (120.0, 0.0)
    assert all(by_id[u].category == "utility" for u in ("K1", "K2", "W1", "W2"))
    assert (by_id["K1"].utility, by_id["W1"].utility, by_id["K2"].utility) == ("CW", "STEAM", None)
    assert {s.quality for s in ex.streams} == {"linearised"}
    rec = ex.reconciliation
    assert rec.closed and rec.total_kW == pytest.approx(120 + 210 + 180 + 110 + 240)
    assert rec.by_class["recovery"] == pytest.approx(120.0)
    assert rec.by_class["utility"] == pytest.approx(740.0)
    assert rec.residual_kW == pytest.approx(0.0)


def test_violations_and_cross_pinch_explain_the_potential():
    """Targets of the same streams: 20 kW hot, 60 kW cold, pinch 90/80 degC; potential 350 - 20
    = 390 - 60 = 330 kW. Coolers above the hot pinch: K1 3 x (130 - 90) = 120, K2 1.5 x (150 -
    90) = 90; heaters below the cold pinch: W1 2 x (75 - 20) = 110, W2 none (it starts at the
    pinch). E1 heats C1 from 75 degC, 5 K below the cold pinch, with H1 above the hot pinch:
    2 x 5 = 10 kW across. 120 + 90 + 110 + 10 = 330."""
    model, out, process = kemp_plant()
    ex = thermal_streams(model, out, "design", process=process)
    report = PinchReport("design", 10.0, "ASSUMED", False, extraction=ex)
    _targets(report, ex.targeted())
    assert report.current == pytest.approx({"hot_kW": 350.0, "cold_kW": 390.0})
    assert report.minimum == pytest.approx({"hot_kW": 20.0, "cold_kW": 60.0})
    assert report.potential == pytest.approx({"hot_kW": 330.0, "cold_kW": 330.0})
    assert report.result.pinch_hot_temperature == pytest.approx(90 + C)
    assert report.result.pinch_cold_temperature == pytest.approx(80 + C)
    found = {v["stream"]: (v["kind"], v["kW"]) for v in report.violations}
    assert found == {
        "K1": ("cooler above the pinch", pytest.approx(120.0)),
        "K2": ("cooler above the pinch", pytest.approx(90.0)),
        "W1": ("heater below the pinch", pytest.approx(110.0)),
    }
    [cross] = report.cross_pinch
    assert cross["exchange"] == "E1" and cross["kW"] == pytest.approx(10.0)
    assert cross["minimum_approach_K"] == pytest.approx(35.0)  # 170 - 135 at the hot end
    assert report.explained_kW == pytest.approx(330.0)
    # the labels; "saving" and "recoverable" only where the note says what the potential is not
    text = pinch_report_module.pinch_text(report)
    assert "current utility demand: hot 350 kW" in text
    assert "theoretical minimum utility demand at dTmin 10 K: hot 20 kW" in text
    assert "theoretical energy-saving potential: hot 330 kW" in text
    rest = text.replace("neither a saving nor a quantity of recoverable heat", "")
    assert "savings" not in rest.lower() and "recoverable" not in rest.lower()


def test_waste_heat_boiler_is_one_hot_stream_and_its_steam_a_utility():
    """B1 cools process gas 700 -> 450 K (1000 kW) raising steam from boiler feed water (W1 from
    terminal BFW, W2 to terminal STEAM). The process side is one hot utility-class stream; the
    water side is the utility, not a second source; the duty is counted once, as utility."""
    model = {
        "units": [
            _unit("B1", "heat_exchanger", ["G1", "W1"], ["G2", "W2"]),
            _unit("H1", "heater", ["F1"], ["F2"], {"energy": "q"}),
        ]
    }
    out = _out(
        {"B1": {"duty_kW": 1000.0}, "H1": {"duty_kW": 400.0}},
        {"G1": 700.0, "G2": 450.0, "W1": 380.0, "W2": 420.0, "F1": 300.0, "F2": 500.0},
    )
    process = _process(
        [_terminal("BFW"), _terminal("FEED", "raw_material")],
        [_terminal("STEAM")],
        [("W1", "BFW.out", "B1.w"), ("W2", "B1.w", "STEAM.in"), ("F1", "FEED.out", "H1.in")],
    )
    ex = thermal_streams(model, out, "design", process=process)
    boiler = [s for s in ex.streams if s.unit == "B1"]
    assert [(s.id, s.category, s.side, s.utility) for s in boiler] == [
        ("B1:G1", "utility", "hot", "BFW")
    ]
    assert boiler[0].counted_kW == 1000.0 and boiler[0].supply_K == 700.0
    rec = ex.reconciliation
    assert rec.closed and rec.by_class == pytest.approx(
        {"utility": 1400.0, "recovery": 0.0, "constrained": 0.0, "excluded": 0.0}
    )
    # in the targets the boiler's gas heats the feed: 700 -> 450 at 4 kW/K against 300 -> 500 at
    # 2 kW/K (400 kW), dTmin 10: no hot utility, 600 kW cold
    report = PinchReport("design", 10.0, "ASSUMED", False, extraction=ex)
    _targets(report, ex.targeted())
    assert report.current == pytest.approx({"hot_kW": 400.0, "cold_kW": 1000.0})
    assert report.minimum == pytest.approx({"hot_kW": 0.0, "cold_kW": 600.0}, abs=1e-9)
    assert report.result.threshold and report.violations == [] and report.cross_pinch == []


def test_constrained_reactor_is_left_out_unless_included():
    model = {
        "units": [
            _unit("R1", "conversion_reactor", ["a"], ["b"], {"energy": "q"}),
            _unit("H1", "heater", ["c"], ["d"]),
            _unit("K1", "cooler", ["e"], ["f"]),
        ]
    }
    out = _out(
        {"R1": {"duty_kW": -500.0}, "H1": {"duty_kW": 100.0}, "K1": {"duty_kW": -50.0}},
        {"a": 600.0, "b": 600.0, "c": 300.0, "d": 400.0, "e": 350.0, "f": 320.0},
    )
    ex = thermal_streams(model, out, "design")
    reactor = next(s for s in ex.streams if s.unit == "R1")
    assert reactor.category == "constrained" and reactor.reason == REACTOR_REASON
    assert reactor.side == "hot" and reactor.segments[0].isothermal  # cooled at 600 K
    assert reactor not in ex.targeted()
    assert reactor in ex.targeted(include_constrained=True)
    assert ex.reconciliation.closed and ex.reconciliation.by_class["constrained"] == 500.0
    report = PinchReport("design", 10.0, "ASSUMED", True, extraction=ex)
    _targets(report, ex.targeted(include_constrained=True))
    # the reactor's 500 kW at 600 K cover the heater: no hot utility
    assert report.current == pytest.approx({"hot_kW": 100.0, "cold_kW": 550.0})
    assert report.minimum["hot_kW"] == pytest.approx(0.0, abs=1e-9)
    # overridable per unit (the plant's own constrained duties, PR 2's heat-integration file)
    free = thermal_streams(model, out, "design", constrained={})
    assert next(s for s in free.streams if s.unit == "R1").category == "utility"


def test_insufficient_and_unknown_duties():
    """A heater without its outlet temperature is excluded and still accounted for; a heat
    result of a unit kind the extraction does not know is left over (a finding)."""
    model = {
        "units": [
            _unit("H1", "heater", ["a"], ["b"]),
            _unit("X1", "evaporator", ["c"], ["d"]),
            _unit("F1", "flash", ["e"], ["g", "h"]),
        ]
    }
    out = _out(
        {"H1": {"duty_kW": 80.0}, "X1": {"duty_kW": 50.0}, "F1": {"duty_kW": 20.0}},
        {"a": 300.0, "e": 400.0, "g": 380.0, "h": 380.0},
    )
    ex = thermal_streams(model, out, "design")
    h1 = next(s for s in ex.streams if s.unit == "H1")
    assert (h1.category, h1.quality, h1.counted_kW) == ("excluded", "insufficient", 80.0)
    assert "no temperature of b" in h1.reason
    f1 = next(s for s in ex.streams if s.unit == "F1")  # heated while it cools: not one stream
    assert (f1.category, f1.quality) == ("excluded", "insufficient")
    assert "against the duty" in f1.reason
    rec = ex.reconciliation
    assert not rec.closed
    assert rec.leftover == [
        {
            "unit": "X1",
            "role": "duty",
            "kW": 50.0,
            "residual_kW": 50.0,
            "reason": "no stream accounts for it",
        }
    ]
    assert rec.by_class["excluded"] == 100.0 and rec.residual_kW == pytest.approx(50.0)


def test_condenser_heating_a_reboiler_counts_once():
    """Column A's condenser (300 kW at 400 K) heats column B's reboiler (300 kW at 380 K):
    one process/process exchange, both sides recovery, counted once; a condenser giving more
    than the reboiler takes leaves the excess over."""
    model = {
        "units": [
            _unit("A", "distillation_column", ["a"], ["a1", "a2"]),
            _unit(
                "B",
                "distillation_column",
                ["b"],
                ["b1", "b2"],
                spec={"heat_integration": {"condenser_of": "A"}},
            ),
        ]
    }
    results = {
        "A": {
            "condenser_kW": 300.0,
            "reboiler_kW": 350.0,
            "top_temperature_K": 400.0,
            "bottom_temperature_K": 450.0,
        },
        "B": {
            "condenser_kW": 280.0,
            "reboiler_kW": 300.0,
            "top_temperature_K": 330.0,
            "bottom_temperature_K": 380.0,
        },
    }
    ex = thermal_streams(model, _out(results, {}), "design")
    by_id = {s.id: s for s in ex.streams}
    assert by_id["A:condenser"].category == by_id["B:reboiler"].category == "recovery"
    assert by_id["A:condenser"].exchange == by_id["B:reboiler"].exchange == "A/B"
    assert by_id["A:condenser"].counted_kW == 0.0
    assert ex.reconciliation.closed and ex.reconciliation.by_class["recovery"] == 300.0
    assert [d["role"] for d in run_duties(model, _out(results, {})) if d["unit"] == "A"] == [
        "reboiler"
    ]
    results["A"]["condenser_kW"] = 340.0
    excess = thermal_streams(model, _out(results, {}), "design").reconciliation
    assert not excess.closed and excess.leftover[0]["role"] == "condenser-excess"
    assert excess.leftover[0]["residual_kW"] == pytest.approx(40.0)


def test_multi_stream_exchanger_counts_the_smaller_group_and_excludes_the_net():
    """Sides +100 (cold), -60 and -50 (hot) kW: 110 given, 100 taken; the exchange is 100
    (the cold side counts), the net 10 kW is excluded."""
    model = {"units": [_unit("M1", "multi_stream_exchanger", ["a", "b", "c"], ["d", "e", "f"])]}
    out = _out(
        {"M1": {"duty_kW": 100.0, "imbalance_kW": -10.0, "side_duties_kW": [100.0, -60.0, -50.0]}},
        {"a": 300.0, "d": 350.0, "b": 420.0, "e": 380.0, "c": 400.0, "f": 360.0},
    )
    ex = thermal_streams(model, out, "design")
    by_id = {s.id: s for s in ex.streams}
    assert by_id["M1:a"].counted_kW == 100.0 and by_id["M1:b"].counted_kW == 0.0
    assert by_id["M1:net"].category == "excluded" and by_id["M1:net"].duty_kW == 10.0
    assert ex.reconciliation.closed
    assert ex.reconciliation.by_class == pytest.approx(
        {"utility": 0.0, "recovery": 100.0, "constrained": 0.0, "excluded": 10.0}
    )


# -- end to end: hda-1 and its recorded DWSIM run --------------------------------------------


def _hda(tmp_path: Path) -> Path:
    """A copy of hda-1 whose recorded run carries the model fingerprint this core translates its
    inputs to. The duties are DWSIM's; only the stamp is renewed, so a change to the translation
    does not make the pinch tests stale (test_hda_needs_a_current_run covers the refusal)."""
    from chemeascode.domains.process.model import load as load_process
    from chemeascode.domains.process.simulation.translate import load, translate

    root = tmp_path / "hda-1"
    shutil.copytree(DATA / "process-hda-1", root)
    process, _ = load_process(root)
    sim, sim_doc, _ = load(root)
    fingerprint = translate(process, sim, sim_doc, "design").fingerprint
    _edit_run(root, lambda e: e.update(model_fingerprint=fingerprint))
    return root


def _fingerprint(root: Path) -> str:
    data = json.loads((root / "process" / "simulation-run.json").read_text())
    return data["cases"]["design"]["model_fingerprint"]


def _cli(root: Path, monkeypatch, *args: str):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    monkeypatch.chdir(root)
    return CliRunner().invoke(app, ["process", "pinch", *args])


def _edit_run(root: Path, edit) -> None:
    path = root / "process" / "simulation-run.json"
    data = json.loads(path.read_text())
    edit(data["cases"]["design"])
    path.write_text(json.dumps(data, indent=2))


def test_hda_end_to_end(tmp_path, monkeypatch):
    """hda-1 at dTmin 10 K from its recorded run: the reconciliation closes (42.64 MW of
    duties: 24.39 MW in the feed/effluent exchanger E101, counted once, the rest on utilities),
    the current utility demand equals the run's own utility classification (energy.utilities),
    and the targets are plausible: below the current demand, with the potential explained by
    E101's cross-pinch transfer."""
    root = _hda(tmp_path)
    shown = _cli(root, monkeypatch, "--dt-min", "10", "--json")
    assert shown.exit_code == 0, shown.output
    payload = json.loads(shown.output)
    recorded = json.loads((root / "process" / "simulation-run.json").read_text())
    audit = recorded["cases"]["design"]["energy"]["utilities"]["totals_kW"]
    rec = payload["reconciliation"]
    assert rec["closed"] and rec["leftover"] == []
    assert rec["total_kW"] == pytest.approx(42637.55, abs=0.01)
    assert rec["residual_kW"] == pytest.approx(0.0, abs=1e-6)
    assert rec["by_class_kW"]["recovery"] == pytest.approx(audit["recovered"])
    current = payload["current_utility_demand_kW"]
    assert current["hot_kW"] == pytest.approx(audit["hot_utility"])
    assert current["cold_kW"] == pytest.approx(audit["cold_utility"])
    minimum = payload["minimum_utility_demand_kW"]
    potential = payload["energy_saving_potential_kW"]
    assert 0 < minimum["hot_kW"] < current["hot_kW"] and 0 < minimum["cold_kW"] < current["cold_kW"]
    assert minimum["hot_kW"] == pytest.approx(5464.75, abs=0.01)
    assert minimum["cold_kW"] == pytest.approx(7056.03, abs=0.01)
    assert potential["hot_kW"] == pytest.approx(potential["cold_kW"])
    pinch = payload["pinch"]
    assert not pinch["threshold"]
    assert pinch["hot_side_K"] - pinch["cold_side_K"] == pytest.approx(10.0)
    assert pinch["cold_side_K"] == pytest.approx(404.396, abs=1e-3)  # C202's reboiler
    assert payload["utility_pinch_violations"] == []
    [cross] = payload["cross_pinch_transfer"]
    assert cross["exchange"] == "E101" and cross["kW"] == pytest.approx(potential["hot_kW"])
    assert payload["explained_kW"] == pytest.approx(potential["hot_kW"])
    streams = {s["id"]: s for s in payload["streams"]}
    assert {s["quality"] for s in streams.values()} == {"linearised"}
    assert streams["E101:S9"]["counted_kW"] > 0 and streams["E101:S5"]["counted_kW"] == 0
    assert any("changes phase" in n for n in streams["E101:S9"]["notes"])
    assert streams["C202:reboiler"]["utility"] == "LPS"
    assert payload["shares"]["quality"]["linearised"] == pytest.approx(1.0)
    assert payload["settings"]["dt_min"] == {"value": 10.0, "unit": "K", "source": "ASSUMED"}
    assert payload["simulation_run"]["model_fingerprint"] == _fingerprint(root)
    rules = {f["rule"] for f in payload["findings"]}
    assert rules == {"cheme.process-pinch-stream-linearised"}
    # text and Markdown carry the three labels
    text = _cli(root, monkeypatch, "--dt-min", "10").output
    for label in (
        "current utility demand",
        "theoretical minimum utility demand at dTmin 10 K",
        "theoretical energy-saving potential",
        "pinch: hot side 414.40 K, cold side 404.40 K, shifted 409.40 K",
        "reconciliation: closed",
    ):
        assert label in text
    assert (
        "theoretical energy-saving potential"
        in _cli(root, monkeypatch, "--dt-min", "10", "--md").output
    )


def test_hda_write_records_the_targets(tmp_path, monkeypatch):
    root = _hda(tmp_path)
    shown = _cli(root, monkeypatch, "--dt-min", "20", "--dt-min-source", "D-012", "--write")
    assert shown.exit_code == 0, shown.output
    assert "process/pinch-run.json: targets of case design recorded" in shown.output
    data = json.loads((root / "process" / "pinch-run.json").read_text())
    assert data["schema"] == "cheme/pinch-run/v1" and data["kind"] == "pinch-run"
    entry = data["cases"]["design"]
    assert entry["settings"] == {
        "engine": "native",
        "dt_min": {"value": 20.0, "unit": "K", "source": "D-012"},
        "include_constrained": False,
    }
    assert entry["tool"].startswith("cheme-as-code ")
    assert entry["simulation_run"]["model_fingerprint"] == _fingerprint(root)
    assert entry["simulation_run"]["entry_fingerprint"].startswith("sha256:")
    assert "process/simulation-run.json" in entry["inputs"]["fingerprints"]
    results = entry["results"]
    assert results["reconciliation"]["closed"]
    assert results["minimum_utility_demand_kW"]["hot_kW"] > 5464.75  # larger dTmin, more utility


def test_hda_reconciliation_finding_refuses_write(tmp_path, monkeypatch):
    """A heat result the extraction does not know (a mixer with a duty) is left over: exit 1
    without --write, 3 with it, and nothing is written."""
    root = _hda(tmp_path)

    def heat_the_mixer(entry):
        for row in entry["units"]:
            if row["id"] == "M100":
                row["results"]["duty_kW"] = 50.0

    _edit_run(root, heat_the_mixer)
    shown = _cli(root, monkeypatch, "--dt-min", "10")
    assert shown.exit_code == 1
    assert "cheme.process-pinch-reconciliation" in shown.output
    assert "reconciliation: NOT closed" in shown.output
    refused = _cli(root, monkeypatch, "--dt-min", "10", "--write")
    assert refused.exit_code == 3
    assert "refused" in refused.output
    assert not (root / "process" / "pinch-run.json").exists()


def test_hda_constrained_reactor_by_option(tmp_path, monkeypatch):
    """R101 is adiabatic in hda-1; with 500 kW added to it (S7 895.15 -> S8 937.9 K) it is a
    constrained cold stream: left out by default, in the targets and the current demand with
    --include-constrained."""
    root = _hda(tmp_path)

    def heat_the_reactor(entry):
        for row in entry["units"]:
            if row["id"] == "R101":
                row["results"]["duty_kW"] = 500.0

    _edit_run(root, heat_the_reactor)
    default = json.loads(_cli(root, monkeypatch, "--dt-min", "10", "--json").output)
    included = json.loads(
        _cli(root, monkeypatch, "--dt-min", "10", "--json", "--include-constrained").output
    )
    r101 = next(s for s in default["streams"] if s["unit"] == "R101")
    assert r101["class"] == "constrained" and r101["reason"] == REACTOR_REASON
    assert default["reconciliation"]["by_class_kW"]["constrained"] == pytest.approx(500.0)
    assert "cheme.process-pinch-stream-constrained" in {f["rule"] for f in default["findings"]}
    hot = default["current_utility_demand_kW"]["hot_kW"]
    assert included["current_utility_demand_kW"]["hot_kW"] == pytest.approx(hot + 500.0)
    assert (
        included["minimum_utility_demand_kW"]["hot_kW"]
        > default["minimum_utility_demand_kW"]["hot_kW"]
    )
    assert included["settings"]["include_constrained"] is True


def test_hda_needs_a_current_run(tmp_path, monkeypatch):
    root = _hda(tmp_path)
    _edit_run(root, lambda e: e.update(model_fingerprint="0000000000000000"))
    stale = _cli(root, monkeypatch, "--dt-min", "10")
    assert stale.exit_code == 1 and "cheme.process-pinch-run-stale" in stale.output
    (root / "process" / "simulation-run.json").unlink()
    missing = _cli(root, monkeypatch, "--dt-min", "10", "--write")
    assert missing.exit_code == 1 and "cheme.process-pinch-run-missing" in missing.output
    assert not (root / "process" / "pinch-run.json").exists()


def test_hda_invalid_input(tmp_path, monkeypatch):
    root = _hda(tmp_path)
    assert _cli(root, monkeypatch).exit_code == 2  # dTmin is required: no hidden default
    assert _cli(root, monkeypatch, "--dt-min", "-5").exit_code == 2
    assert _cli(root, monkeypatch, "--dt-min", "10", "--json", "--md").exit_code == 2
    assert _cli(root, monkeypatch, "--dt-min", "10", "--case", "nope").exit_code == 2
