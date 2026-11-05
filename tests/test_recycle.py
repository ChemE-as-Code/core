"""Recycle convergence in ``cheme process propagate`` (ADR 0060): tear streams solved by
successive substitution or Wegstein, against the closed form of a loop reactor with a recycle
split (examples/process-purge-loop)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.model import load, stream_flows
from chemeascode.domains.process.propagate import derive
from chemeascode.domains.process.recycle import Q_MIN, _initial, _step, loop_inputs
from chemeascode.domains.process.schema import Flowsheet
from chemeascode.interfaces.cli import app

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/process-purge-loop"

# the closed form (kg/h; n-butane and isobutane have one molar mass, so mass is conserved per
# butane): feed F with n-butane F_A and propane F_I, a share r of the effluent recycled, a
# conversion X per pass
F_A, F_I, R, X = 950.0, 50.0, 0.75, 0.4
A_IN = F_A / (1 - R * (1 - X))  # n-butane into the reactor
B_OUT = X * A_IN / (1 - R)  # isobutane out of the reactor
CLOSED = {
    "S2": {"NC4": A_IN, "IC4": R * B_OUT, "C3": F_I / (1 - R)},
    "S5": {"NC4": R * (1 - X) * A_IN, "IC4": R * B_OUT, "C3": R * F_I / (1 - R)},
    "S4": {"NC4": (1 - R) * (1 - X) * A_IN, "IC4": X * A_IN, "C3": F_I},
}
#: With the reactor effluent, which any tear of the loop can be.
CLOSED_ALL = {**CLOSED, "S3": {"NC4": (1 - X) * A_IN, "IC4": B_OUT, "C3": F_I / (1 - R)}}
#: The example's convergence.tolerance (kg/h per component).
ABS, REL = 1e-4, 1e-7
#: The largest gain of the loop (propane's, whose only exit is the purge): an iterate within
#: the tolerance of g(x) is within tolerance / (1 - gain) of the fixed point.
GAIN = R


@pytest.fixture
def plant(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "plant"
    shutil.copytree(EXAMPLE, root, ignore=shutil.ignore_patterns("build"))
    monkeypatch.chdir(root)
    return root


def _edit(root: Path, change) -> None:
    path = root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _cli(*args: str):
    return CliRunner().invoke(app, list(args))


def _mass(root: Path, sid: str) -> dict[str, float]:
    process, _ = load(root)
    stream = next(s for s in process.flowsheet.streams if s.id == sid)
    return stream_flows(process, stream, "design").components or {}


def _stream(data, sid):
    return next(s for s in data["streams"] if s["id"] == sid)


def _unfilled(d) -> None:
    for sid in ("S2", "S3", "S4", "S5"):
        _stream(d, sid).pop("state", None)  # as before the example was filled


def _converged(root: Path, case: str = "design", scale: float = 1.0):
    """derive() of *root*: the loop converged, every tear at the closed form (times *scale*)
    within the tolerance the flowsheet declares."""
    process, _ = load(root)
    found = derive(process, case)
    recycle = found.recycle
    assert recycle.converged, recycle.problems
    fs = process.flowsheet
    tol = (fs.convergence.tolerance if fs.convergence else None) or fs.tolerance
    for sid, solution in recycle.solution.items():
        for name, value in CLOSED_ALL[sid].items():
            allowed = (tol.abs + tol.rel * scale * value) / (1 - GAIN)
            assert abs(solution[name] - scale * value) <= allowed, (sid, name, solution[name])
    return process, found


def test_the_closed_form_is_a_steady_state():
    # the reactor feed is the fresh feed over (1 - r); the product carries every kg of feed
    assert sum(CLOSED["S2"].values()) == pytest.approx(1000 / (1 - R))
    assert sum(CLOSED["S4"].values()) == pytest.approx(1000)
    assert CLOSED["S4"]["NC4"] + CLOSED["S4"]["IC4"] == pytest.approx(F_A)


def test_wegstein_reaches_a_linear_fixed_point_in_its_second_step():
    a, b = 950.0, 0.45  # the n-butane of the loop: g(x) = 0.45 (950 + x)
    x0 = {"A": 0.0}
    g0 = {"A": b * (a + x0["A"])}
    x1 = _step("wegstein", 1.0, x0, g0, None)  # a substitution
    assert x1["A"] == pytest.approx(g0["A"])
    g1 = {"A": b * (a + x1["A"])}
    x2 = _step("wegstein", 1.0, x1, g1, (x0, g0))
    assert x2["A"] == pytest.approx(a * b / (1 - b))
    # a gain above 5/6 would need q below the bound: it is clipped, and never negative flows
    steep = _step("wegstein", 1.0, {"A": 10.0}, {"A": 19.9}, ({"A": 0.0}, {"A": 10.0}))
    assert steep["A"] == pytest.approx(Q_MIN * 10.0 + (1 - Q_MIN) * 19.9)
    assert _step("substitution", 0.5, {"A": 10.0}, {"A": 20.0}, None) == {"A": 15.0}
    assert _step("substitution", 1.0, {"A": 10.0}, {"A": -5.0}, None) == {"A": 0.0}


def test_propagate_converges_the_purge_loop_to_the_closed_form(plant):
    # the converged tear is the closed form within the tolerance the example declares (the
    # iterations round nothing)
    _converged(plant)
    done = _cli("process", "propagate", "--fill")
    assert done.exit_code == 0, done.stdout
    assert "cheme.process-recycle" in done.stdout and "converged in" in done.stdout
    # written to six digits: the flows of the loop exactly
    data = yaml.safe_load((plant / "process/flowsheet.yaml").read_text())
    flows = {sid: _stream(data, sid)["state"]["design"]["flow"]["value"] for sid in CLOSED_ALL}
    assert flows == {"S2": 4000.0, "S3": 4000.0, "S4": 1000.0, "S5": 3000.0}
    for sid, expected in CLOSED.items():
        got = _mass(plant, sid)
        for name, value in expected.items():
            # to the six digits of the written mole fractions
            assert got[name] == pytest.approx(value, rel=2e-6, abs=1e-3), (sid, name)
    data = yaml.safe_load((plant / "process/flowsheet.yaml").read_text())
    tear = _stream(data, "S5")["state"]["design"]
    assert tear["flow"]["provenance"] == "calculated"
    assert tear["flow"]["source"] == "cheme process propagate: recycle X1 from S3 (tear, wegstein)"
    # fingerprinted on the loop's inputs, not on an iterate
    process, _ = load(plant)
    assert tear["flow"]["fingerprint"] == loop_inputs(process, "design", ["S5"])
    assert tear["composition"]["fingerprint"] == tear["flow"]["fingerprint"]


def test_a_converged_loop_is_not_stale(plant):
    assert _cli("process", "propagate", "--fill").exit_code == 0
    before = (plant / "process/flowsheet.yaml").read_text()
    again = _cli("process", "propagate", "--check")
    assert again.exit_code == 0, again.stdout
    assert "calculated-stale" not in again.stdout and "not-filled" not in again.stdout
    assert _cli("process", "propagate", "--fill").exit_code == 0
    assert (plant / "process/flowsheet.yaml").read_text() == before
    process, _ = load(plant)
    from chemeascode.domains.process.model import rules

    found = [f for f in rules(process) if f.level != "info"]
    assert not [
        f for f in found if f.rule in ("cheme.process-calculated-stale", "cheme.process-tear")
    ]
    assert not [f for f in found if f.rule == "cheme.process-balance"]


def test_a_changed_feed_makes_the_loop_stale(plant):
    assert _cli("process", "propagate", "--fill").exit_code == 0
    _edit(plant, lambda d: _stream(d, "S1")["state"]["design"]["flow"].update(value=1100))
    process, _ = load(plant)
    from chemeascode.domains.process.model import rules

    stale = {f.ids[0] for f in rules(process) if f.rule == "cheme.process-calculated-stale"}
    assert {"S2", "S3", "S4", "S5"} <= stale
    assert _cli("process", "propagate", "--check").exit_code == 1
    assert _cli("process", "propagate", "--fill").exit_code == 0
    assert sum(_mass(plant, "S5").values()) == pytest.approx(1.1 * 3000, rel=1e-5)


def test_wegstein_takes_fewer_iterations_than_substitution(plant):
    def iterations(method: str) -> int:
        def change(d):
            d["convergence"] = {
                "method": method,
                "max_iterations": 200,
                "tolerance": {"abs": 0.001, "rel": 1e-6},
            }

        _edit(plant, change)
        process, _ = load(plant)
        found = derive(process, "design")
        assert found.recycle.converged, method
        return found.recycle.iterations

    wegstein, substitution = iterations("wegstein"), iterations("substitution")
    assert wegstein < 10 < substitution
    # the damped substitution is slower still, and converges to the same point
    _edit(plant, lambda d: d["convergence"].update(method="substitution", damping=0.5))
    process, _ = load(plant)
    found = derive(process, "design")
    assert found.recycle.converged and found.recycle.iterations > substitution
    assert found.values[("S5", "flow")].value == pytest.approx(3000, abs=1.0)


def test_the_example_is_current():
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(EXAMPLE))
    assert not [f.format() for f in report.findings if f.level != "info"]
    for sid, expected in CLOSED.items():
        got = _mass(EXAMPLE, sid)
        for name, value in expected.items():
            assert got[name] == pytest.approx(value, rel=2e-6, abs=1e-3), (sid, name)


def test_an_unconverged_loop_writes_nothing_that_depends_on_it(plant):
    def change(d):
        d["convergence"].update(max_iterations=2)
        _unfilled(d)

    _edit(plant, change)
    done = _cli("process", "propagate", "--fill")
    assert done.exit_code == 0  # a warning; --check exits 1 on it
    (finding,) = [line for line in done.stdout.splitlines() if "process-recycle" in line]
    assert "warning" in finding and "not converged in 2 iteration(s)" in finding
    assert "worst residual" in finding and "against a tolerance of" in finding
    data = yaml.safe_load((plant / "process/flowsheet.yaml").read_text())
    for sid in ("S2", "S3", "S4", "S5"):
        assert "state" not in _stream(data, sid), sid
    done = _cli("process", "propagate", "--check", "--json")
    assert done.exit_code == 1
    result = json.loads(done.stdout)["results"][0]
    assert result["status"] == "not-converged" and result["iterations"] == 2
    assert any("not converged" in m for m in result["messages"])


def test_the_adapter_result_counts_the_loop_iterations(plant):
    done = _cli("process", "propagate", "--check", "--json")
    result = json.loads(done.stdout)["results"][0]
    assert result["status"] == "converged" and result["messages"] == []
    process, _ = load(plant)
    assert result["iterations"] == derive(process, "design").recycle.iterations
    streams = {s["id"]: s for s in result["streams"]}
    assert streams["S5"]["values"]["flow"]["value"] == pytest.approx(3000, abs=0.05)


def test_a_given_recycle_flow_stays_and_its_composition_is_iterated(plant):
    def change(d):
        step = next(s for s in d["steps"] if s["id"] == "X1")
        del step["split"]  # the product is the remainder of the given recycle
        _stream(d, "S5")["state"] = {
            "design": {"flow": {"value": 3000, "provenance": "assumed", "source": "spec"}}
        }

    _edit(plant, change)
    assert _cli("process", "propagate", "--fill").exit_code == 0
    data = yaml.safe_load((plant / "process/flowsheet.yaml").read_text())
    state = _stream(data, "S5")["state"]["design"]
    assert state["flow"] == {"value": 3000, "provenance": "assumed", "source": "spec"}
    assert state["composition"]["provenance"] == "calculated"
    for name, value in CLOSED["S4"].items():
        assert _mass(plant, "S4")[name] == pytest.approx(value, rel=1e-4, abs=0.05)


def test_tear_declarations_that_cannot_be_iterated(plant):
    def change(d):
        d["tears"] += [
            {"stream": "S9"},
            {"stream": "S1"},
            {"stream": "S5"},
            {"stream": "S2", "initial": {"flow": 1, "unit": "bbl/d", "composition": {"XX": 1}}},
        ]

    _edit(plant, change)
    process, _ = load(plant)
    from chemeascode.domains.process.model import rules

    found = [f for f in rules(process) if f.rule == "cheme.process-tear"]
    text = " | ".join(f.message for f in found)
    assert all(f.level == "error" and f.line for f in found)
    assert "S9: no such stream" in text and "S1: runs from FEED.out" in text
    assert "S5: named twice" in text and "unknown ['XX']" in text and "'bbl/d'" in text
    # propagate leaves them out and still converges the loop at S5
    done = _cli("process", "propagate", "--check")
    assert "left out of the iterations" in done.stdout and "converged in" in done.stdout


def test_a_fully_specified_tear_is_a_warning(plant):
    def change(d):
        _stream(d, "S5")["state"] = {
            "design": {
                "flow": {"value": 3000, "provenance": "assumed"},
                "composition": {
                    "basis": "mass_fraction",
                    "values": {"NC4": 0.26, "IC4": 0.69, "C3": 0.05},
                    "provenance": "assumed",
                },
            }
        }

    _edit(plant, change)
    process, _ = load(plant)
    from chemeascode.domains.process.model import rules

    (finding,) = [f for f in rules(process) if f.rule == "cheme.process-tear"]
    assert finding.level == "warning" and "nothing to converge" in finding.message
    # every node is solved: the adapter result is converged (the declaration is validate's)
    done = _cli("process", "propagate", "--check", "--json")
    result = json.loads(done.stdout)["results"][0]
    assert result["status"] == "converged" and result["messages"] == [], result["messages"]


def test_a_tear_left_out_does_not_make_the_run_unconverged(plant):
    _edit(plant, lambda d: d["tears"].append({"stream": "S9"}))  # a typo next to S5
    done = _cli("process", "propagate", "--check", "--json")
    result = json.loads(done.stdout)["results"][0]
    assert result["status"] == "converged" and result["messages"] == [], result["messages"]
    assert any("S9: no such stream" in f["message"] for f in result["findings"])


def test_a_flowsheet_without_tears_dumps_as_before():
    data = yaml.safe_load((EXAMPLE / "process/flowsheet.yaml").read_text())
    del data["tears"], data["convergence"]
    dumped = Flowsheet.model_validate(data).model_dump(mode="json", by_alias=True)
    assert "tears" not in dumped and "convergence" not in dumped
    data["tears"] = [{"stream": "S5"}]
    dumped = Flowsheet.model_validate(data).model_dump(mode="json", by_alias=True)
    assert dumped["tears"] == [{"stream": "S5"}] and "convergence" not in dumped


# -- tears elsewhere in the loop, guesses, several tears and cases --------------------------------


@pytest.mark.parametrize("tear", ["S2", "S3", "S5"])
def test_an_empty_guess_converges_wherever_the_loop_is_torn(plant, tear):
    # an empty guess at S2 runs a zero flow through the reactor, whose zero mole fractions are
    # zero component flows (not an unknown composition that leaves the loop open)
    def change(d):
        _unfilled(d)
        d["tears"] = [{"stream": tear}]

    _edit(plant, change)
    _, found = _converged(plant)
    assert not found.recycle.problems
    done = _cli("process", "propagate", "--fill")
    assert done.exit_code == 0 and "converged in" in done.stdout, done.stdout
    for sid, expected in CLOSED.items():
        for name, value in expected.items():
            assert _mass(plant, sid)[name] == pytest.approx(value, rel=2e-6, abs=1e-3)


def test_a_zero_flow_with_zero_mole_fractions_is_zero_component_flows(plant):
    process, _ = load(plant)
    stream = next(s for s in process.flowsheet.streams if s.id == "S3")
    empty = {
        "flow": {"value": 0.0, "provenance": "assumed"},
        "composition": {
            "basis": "mole_fraction",
            "values": {"NC4": 0.0, "IC4": 0.0, "C3": 0.0},
            "provenance": "assumed",
        },
    }

    def probe():
        data = stream.model_dump(mode="json", by_alias=True)
        return type(stream).model_validate({**data, "state": {"design": empty}})

    flows = stream_flows(process, probe(), "design")
    assert flows.total == 0.0 and flows.components == {"NC4": 0.0, "IC4": 0.0, "C3": 0.0}
    # a positive flow with no fraction stays an unknown composition
    empty["flow"]["value"] = 10.0
    assert stream_flows(process, probe(), "design").components is None


def test_the_initial_guess_is_where_the_iterations_start(plant):
    def change(d):
        _unfilled(d)
        d["tears"] = [
            {
                "stream": "S2",
                "initial": {
                    "flow": 4000,
                    "unit": "kg/h",
                    "basis": "mass_fraction",
                    "composition": {"NC4": 0.25, "IC4": 0.7, "C3": 0.05},
                },
            }
        ]

    _edit(plant, change)
    process, found = _converged(plant)
    tear = process.flowsheet.tears[0]
    stream = next(s for s in process.flowsheet.streams if s.id == "S2")
    start = _initial(process, stream, "design", tear)
    assert start == pytest.approx({"NC4": 1000.0, "IC4": 2800.0, "C3": 200.0})
    near = found.recycle.iterations
    _edit(plant, lambda d: d["tears"][0].pop("initial"))
    _, empty = _converged(plant)
    assert near < empty.recycle.iterations


def test_an_initial_composition_must_sum_to_one(plant):
    def change(d):
        d["tears"][0]["initial"] = {"flow": 140, "composition": {"NC4": 0.3, "IC4": 0.3}}

    _edit(plant, change)
    process, _ = load(plant)
    from chemeascode.domains.process.model import rules

    (finding,) = [f for f in rules(process) if f.rule == "cheme.process-tear"]
    assert finding.level == "error" and "mass_fraction sum 0.6, not 1" in finding.message
    # propagate leaves the tear out rather than start the loop at 0.6 of its guess
    found = derive(process, "design")
    assert found.recycle.declared and not found.recycle.tears


def test_an_initial_guess_that_cannot_be_converted_is_a_warning(plant):
    def change(d):
        _unfilled(d)
        d["tears"][0]["initial"] = {
            "flow": 50,
            "unit": "Nm3/h",  # the flowsheet has no units.normal_conditions
            "basis": "mole_fraction",
            "composition": {"NC4": 0.3, "IC4": 0.6, "C3": 0.1},
        }

    _edit(plant, change)
    process, _ = load(plant)
    found = derive(process, "design")
    ((_, sid, message),) = found.recycle.problems
    assert sid == "S5" and "cannot be converted to kg/h" in message
    assert ("S5", "flow") not in found.values


def _second_loop(d) -> None:
    """A second loop beside the purge loop, which cannot close: its product S9 is assumed at
    150 kg/h from a fresh feed of 100 kg/h, so the remainder recycled is negative."""
    d["feeds"].append({"id": "FEED2", "ports": [{"id": "out", "direction": "out"}]})
    d["products"].append({"id": "PROD2", "ports": [{"id": "in", "direction": "in"}]})
    d["blocks"].append(
        {
            "id": "LOOP2",
            "class": "SplittingMaterial",
            "ports": [{"id": "feed", "direction": "in"}, {"id": "product", "direction": "out"}],
        }
    )
    d["steps"] += [
        {
            "id": "M2",
            "block": "LOOP2",
            "class": "Mixing",
            "ports": [
                {"id": "feed", "direction": "in", "delegates": "feed"},
                {"id": "recycle", "direction": "in"},
                {"id": "out", "direction": "out"},
            ],
        },
        {
            "id": "X2",
            "block": "LOOP2",
            "class": "SplittingMaterial",
            "ports": [
                {"id": "in", "direction": "in"},
                {"id": "recycle", "direction": "out"},
                {"id": "product", "direction": "out", "delegates": "product"},
            ],
        },
    ]
    feed = _stream(d, "S1")["state"]["design"]
    d["streams"] += [
        {
            "id": "S6",
            "from": "FEED2.out",
            "to": "M2.feed",
            "template": "butanes",
            "state": {"design": {**feed, "flow": {"value": 100, "provenance": "assumed"}}},
        },
        {"id": "S7", "from": "M2.out", "to": "X2.in", "template": "butanes"},
        {
            "id": "S9",
            "from": "X2.product",
            "to": "PROD2.in",
            "template": "butanes",
            "state": {"design": {"flow": {"value": 150, "provenance": "assumed"}}},
        },
        {"id": "S8", "from": "X2.recycle", "to": "M2.recycle", "template": "butanes"},
    ]
    d["tears"].append({"stream": "S8"})


def test_a_tear_that_stays_open_stops_when_the_other_loops_converge(plant):
    def change(d):
        _unfilled(d)
        _second_loop(d)
        d["convergence"]["max_iterations"] = 100

    _edit(plant, change)
    process, _ = load(plant)
    found = derive(process, "design")
    recycle = found.recycle
    assert not recycle.converged
    ((_, sid, message),) = recycle.problems
    assert sid == "S8" and "the loop torn at S8 does not close" in message
    # the guess of an open tear never moves: no sweep beyond the purge loop's convergence
    assert recycle.iterations <= 10
    # nothing that depends on the loops is written
    assert not {k for k in found.values if k[0] in ("S2", "S3", "S4", "S5", "S7", "S8")}
    done = _cli("process", "propagate", "--check")
    assert "does not close" in done.stdout and "nothing that depends" in done.stdout


def test_two_loops_converge_together(plant):
    def change(d):
        _unfilled(d)
        _second_loop(d)
        # the second loop closes: half of M2's outlet is recycled, S8 = 0.5 (100 + S8)
        next(s for s in d["steps"] if s["id"] == "X2")["split"] = {"recycle": 0.5}
        _stream(d, "S9").pop("state")

    _edit(plant, change)
    process, _ = load(plant)
    found = derive(process, "design")
    recycle = found.recycle
    assert recycle.converged and recycle.tears == ["S5", "S8"], recycle.problems
    for name, value in CLOSED["S5"].items():
        assert abs(recycle.solution["S5"][name] - value) <= (ABS + REL * value) / (1 - GAIN)
    assert sum(recycle.solution["S8"].values()) == pytest.approx(100.0, abs=1e-3)
    assert found.values[("S9", "flow")].value == 100.0


def test_two_tears_in_one_loop_converge_to_the_closed_form(plant):
    # each tear's loop gives back what the other was given, so Wegstein's slope is 0 and it
    # steps as plain substitution does: slower than one tear, to the same point
    def change(d):
        _unfilled(d)
        d["tears"] = [{"stream": "S3"}, {"stream": "S5"}]
        d["convergence"]["max_iterations"] = 300

    _edit(plant, change)
    _, found = _converged(plant)
    assert set(found.recycle.solution) == {"S3", "S5"}
    assert _cli("process", "propagate", "--fill").exit_code == 0
    for name, value in CLOSED["S4"].items():
        assert _mass(plant, "S4")[name] == pytest.approx(value, rel=2e-6, abs=1e-3)


def test_every_case_converges_on_its_own(plant):
    def change(d):
        _unfilled(d)
        d["cases"].append({"id": "turndown", "description": "Half the feed"})
        feed = _stream(d, "S1")["state"]
        feed["turndown"] = {**feed["design"], "flow": {"value": 500, "provenance": "assumed"}}

    _edit(plant, change)
    _converged(plant, "design")
    _converged(plant, "turndown", scale=0.5)
    assert _cli("process", "propagate", "--fill").exit_code == 0
    assert _cli("process", "propagate", "--fill", "--case", "turndown").exit_code == 0
    process, _ = load(plant)
    s5 = next(s for s in process.flowsheet.streams if s.id == "S5")
    assert s5.state["design"].flow.value == 3000.0
    assert s5.state["turndown"].flow.value == 1500.0


def test_without_convergence_the_flowsheet_tolerance_applies(plant):
    def change(d):
        _unfilled(d)
        del d["convergence"]

    _edit(plant, change)
    _, found = _converged(plant)  # within the flowsheet's tolerance (abs 0.1, rel 1e-3)
    recycle = found.recycle
    assert recycle.method == "wegstein" and recycle.max_iterations == 100
    sid, name = recycle.where
    solution = recycle.solution[sid]
    value = sum(solution.values()) if name == "total" else solution[name]
    assert recycle.allowed == pytest.approx(0.1 + 1e-3 * value, rel=1e-3)
    assert recycle.residual <= recycle.allowed


def test_the_result_depends_on_neither_the_tear_nor_a_tighter_tolerance(plant):
    def solve(tears, tolerance):
        def change(d):
            _unfilled(d)
            d["tears"] = [{"stream": t} for t in tears]
            d["convergence"]["tolerance"] = tolerance

        _edit(plant, change)
        _, found = _converged(plant)
        return {k: v.value if k[1] == "flow" else v.values for k, v in found.values.items()}

    example = solve(["S5"], {"abs": 1e-4, "rel": 1e-7})
    assert solve(["S5"], {"abs": 0, "rel": 1e-9}) == example
    # torn elsewhere, the loop writes the same flows (to the six digits written)
    other = solve(["S2"], {"abs": 1e-4, "rel": 1e-7})
    assert {k: v for k, v in other.items() if k[1] == "flow"} == {
        k: v for k, v in example.items() if k[1] == "flow"
    }
