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
from chemeascode.domains.process.recycle import Q_MIN, _step, loop_inputs
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
    done = _cli("process", "propagate", "--fill")
    assert done.exit_code == 0, done.stdout
    assert "cheme.process-recycle" in done.stdout and "converged in" in done.stdout
    for sid, expected in CLOSED.items():
        got = _mass(plant, sid)
        for name, value in expected.items():
            assert got[name] == pytest.approx(value, rel=2e-5, abs=0.01), (sid, name)
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
            assert got[name] == pytest.approx(value, rel=2e-5, abs=0.01), (sid, name)


def test_an_unconverged_loop_writes_nothing_that_depends_on_it(plant):
    def change(d):
        d["convergence"].update(max_iterations=2)
        for sid in ("S2", "S3", "S4", "S5"):
            _stream(d, sid).pop("state", None)  # as before the example was filled

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


def test_a_flowsheet_without_tears_dumps_as_before():
    data = yaml.safe_load((EXAMPLE / "process/flowsheet.yaml").read_text())
    del data["tears"], data["convergence"]
    dumped = Flowsheet.model_validate(data).model_dump(mode="json", by_alias=True)
    assert "tears" not in dumped and "convergence" not in dumped
    data["tears"] = [{"stream": "S5"}]
    dumped = Flowsheet.model_validate(data).model_dump(mode="json", by_alias=True)
    assert dumped["tears"] == [{"stream": "S5"}] and "convergence" not in dumped
