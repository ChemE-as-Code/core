"""Design specifications and component separators in ``cheme process propagate`` (ADR 0070):
feeds and splits solved for stream targets together with the tears, outlets from a specified
split, against closed forms (examples/process-design-spec, a two-feed mixer, a batch whose
cycle is linear in its size)."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.design_spec import newton_step, spec_problems
from chemeascode.domains.process.design_spec import rules as spec_rules
from chemeascode.domains.process.model import load, stream_flows
from chemeascode.domains.process.propagate import derive
from chemeascode.domains.process.schema import DesignSpec, Flowsheet, Step
from chemeascode.domains.process.separator import outlets
from chemeascode.domains.process.separator import rules as recovery_rules
from chemeascode.interfaces.cli import app

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples/process-design-spec"
SEMIBATCH = ROOT / "examples/process-semibatch"

# the example's closed form (mass; n-butane and isobutane are isomers): per kg/h of fresh feed
# (0.95 n-butane, 0.05 propane), a purge fraction p of the separator's recycle, the conversion X
# and the separator's shares to the product
X, P_N, P_I, P_C = 0.4, 0.02, 0.98, 0.1
RATE = 8000.0 * 1000.0 / 8000.0  # isobutane in the product, kg/h (8000 t/a in 8000 h)
INERT = 0.1  # propane's mass fraction in the reactor feed


def _into_reactor(p: float) -> tuple[float, float, float]:
    """n-butane, isobutane and propane into R1 (kg/h per kg/h of feed) at purge fraction p."""
    keep = 1.0 - p
    n = 0.95 / (1.0 - (1.0 - P_N) * keep * (1.0 - X))
    i = (1.0 - P_I) * keep * X * n / (1.0 - (1.0 - P_I) * keep)
    c = 0.05 / (1.0 - (1.0 - P_C) * keep)
    return n, i, c


def _closed() -> tuple[float, float]:
    """The purge fraction and the fresh feed (kg/h) that meet both targets."""
    lo, hi = 1e-6, 1.0
    for _ in range(200):  # the inert's fraction falls as the purge grows
        mid = (lo + hi) / 2
        n, i, c = _into_reactor(mid)
        if c / (n + i + c) > INERT:
            lo = mid
        else:
            hi = mid
    p = (lo + hi) / 2
    n, i, _ = _into_reactor(p)
    return p, RATE / (P_I * (i + X * n))


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


def _stream(data, sid):
    return next(s for s in data["streams"] if s["id"] == sid)


def _node(data, nid):
    return next(n for n in data.get("steps", []) + data.get("blocks", []) if n["id"] == nid)


def _unfilled(d) -> None:
    """The example as before propagate filled it."""
    for s in d["streams"]:
        state = s.get("state", {}).get("design")
        if state is None:
            continue
        for name in ("flow", "composition"):
            if state.get(name, {}).get("provenance") == "calculated":
                del state[name]
        if not state:
            del s["state"]


def _mass(root: Path, sid: str) -> dict[str, float]:
    process, _ = load(root)
    stream = next(s for s in process.flowsheet.streams if s.id == sid)
    return stream_flows(process, stream, "design").components or {}


# -- the example against its closed form ----------------------------------------------------


def test_the_closed_form_meets_both_targets():
    p, feed = _closed()
    n, i, c = _into_reactor(p)
    assert c / (n + i + c) == pytest.approx(INERT)
    assert feed * P_I * (i + X * n) == pytest.approx(RATE)
    # every kg of feed leaves by the product or the purge (the reaction keeps the mass)
    purge = feed * p * ((1 - P_N) * (1 - X) * n + (1 - P_I) * (i + X * n) + (1 - P_C) * c)
    product = feed * (P_N * (1 - X) * n + P_I * (i + X * n) + P_C * c)
    assert product + purge == pytest.approx(feed)


def test_propagate_solves_the_feed_and_the_purge_for_their_targets(plant):
    p, feed = _closed()
    _edit(plant, _unfilled)
    process, _ = load(plant)
    found = derive(process, "design")
    specs = found.specs
    assert specs.converged and not specs.problems
    rate, purge = specs.results
    assert purge.value == pytest.approx(p, rel=1e-5)
    assert rate.value == pytest.approx(feed, rel=1e-5)  # six digits written
    assert found.recycle.converged
    # the values written: the feed calculated by the spec, the targets met
    assert _cli("process", "propagate", "--fill").exit_code == 0
    s1 = next(s for s in load(plant)[0].flowsheet.streams if s.id == "S1").state["design"].flow
    assert s1.provenance == "calculated" and s1.source.endswith("spec rate (S4 IC4 t/a 8000)")
    assert s1.value == pytest.approx(feed, rel=1e-5)
    assert _mass(plant, "S4")["IC4"] * 8000 / 1000 == pytest.approx(8000, rel=1e-4)
    s2 = _mass(plant, "S2")
    assert s2["C3"] / sum(s2.values()) == pytest.approx(INERT, rel=1e-4)


def test_the_findings_report_the_variables_and_the_targets_reached(plant):
    result = _cli("process", "propagate", "--check")
    assert result.exit_code == 0, result.output
    assert "cheme.process-design-spec [rate]: spec rate (design): S1 flow 1321.13 kg/h" in (
        result.output
    )
    assert "spec purge (design): X1.purge 0.150497 gives S2 C3 mass fraction 0.1" in (result.output)
    assert "converged in" in result.output and "(broyden)" in result.output


def test_the_example_is_current():
    from chemeascode.foundation.workspace import Workspace
    from chemeascode.project.validate import validate_workspace

    report = validate_workspace(Workspace(EXAMPLE))
    assert not [f.format() for f in report.findings if f.level != "info"]


def test_a_changed_target_makes_the_adjusted_feed_stale(plant):
    _edit(plant, lambda d: d["specs"][0]["target"].update(value=9000))
    result = _cli("process", "propagate", "--check")
    assert "S1" in result.output and "stale" in result.output, result.output


def test_the_solution_does_not_depend_on_the_initial_values(plant):
    def far(d) -> None:
        _unfilled(d)
        d["specs"][0]["vary"]["initial"] = 50.0
        d["specs"][1]["vary"]["initial"] = 0.6

    _edit(plant, far)
    p, feed = _closed()
    found = derive(load(plant)[0], "design")
    assert found.specs.converged, found.specs.problems
    assert found.specs.results[0].value == pytest.approx(feed, rel=1e-5)
    assert found.specs.results[1].value == pytest.approx(p, rel=1e-5)


def test_the_adapter_result_is_converged(plant):
    result = _cli("process", "propagate", "--check", "--json")
    data = json.loads(result.output)["results"][0]
    assert data["status"] == "converged", data["messages"]


# -- failures -------------------------------------------------------------------------------


def test_a_target_beyond_the_bounds_is_a_warning_and_writes_nothing(plant):
    def capped(d) -> None:
        _unfilled(d)
        d["specs"][0]["vary"].update(initial=400.0, high=500.0)  # the target needs 1321 kg/h

    _edit(plant, capped)
    result = _cli("process", "propagate", "--fill")
    assert "warning cheme.process-design-spec [rate]" in result.output, result.output
    assert "cannot be met within the bounds of its variable" in result.output
    assert "nothing that depends on the specifications is written" in result.output
    process, _ = load(plant)
    s1 = next(s for s in process.flowsheet.streams if s.id == "S1")
    assert s1.state["design"].flow is None
    data = json.loads(_cli("process", "propagate", "--check", "--json").output)["results"][0]
    assert data["status"] == "not-converged"


def test_a_target_the_variable_does_not_move_is_a_warning(plant):
    def flat(d) -> None:
        _unfilled(d)
        d["specs"] = d["specs"][:1]
        # the propane fraction of the fresh feed does not depend on its flow
        d["specs"][0]["target"] = {
            "stream": "S1",
            "component": "C3",
            "quantity": "fraction",
            "basis": "mass",
            "value": 0.2,
        }
        _node(d, "X1")["split"] = {"purge": 0.15}

    _edit(plant, flat)
    found = derive(load(plant)[0], "design")
    assert not found.specs.converged
    (_, sid, message), *_ = found.specs.problems
    assert sid == "rate" and "does not depend on the variables" in message


def test_declarations_that_cannot_be_solved_are_validate_errors(plant):
    def bad(d) -> None:
        d["specs"].append(dict(d["specs"][0]))  # id named twice, S1 varied twice
        d["specs"].append(
            {
                "id": "s3",
                "vary": {"stream": "S3", "initial": 1.0},  # no feed
                "target": {"stream": "S4", "component": "XX", "value": 1.0},
                "provenance": "assumed",
            }
        )
        d["specs"].append(
            {
                "id": "split",
                "vary": {"node": "M1", "port": "out", "initial": 0.5},  # no splitter
                "target": {"stream": "S9", "value": 1.0},  # no stream
                "provenance": "assumed",
            }
        )
        d["specs"].append(
            {
                "id": "own",
                "vary": {"stream": "S1", "initial": 2000.0, "low": 3000.0},
                "target": {"stream": "S1", "quantity": "annual", "value": 1.0},
                "provenance": "assumed",
            }
        )
        _stream(d, "S1")["state"]["design"]["flow"] = {"value": 1000, "provenance": "assumed"}

    _edit(plant, bad)
    process, _ = load(plant)
    messages = [m for _, level, m in spec_problems(process) if level == "error"]
    expect = [
        "spec rate (design): its flow is assumed",
        "spec rate: id named twice",
        "spec rate: S1 is varied by spec rate too",
        "spec s3: vary S3: not a feed stream",
        "spec s3: target component XX is not declared",
        "spec split: vary: M1 is no splitter",
        "spec split: target S9: no such material stream",
        "spec own: vary: initial 2000 outside [3000, inf]",
        "spec own: target: annual needs hours",
        "spec own: target: S1's flow is the variable itself",
    ]
    for text in expect:
        assert any(text.split(" (design)")[0] in m for m in messages), (text, messages)
    findings = spec_rules(process)
    assert findings and all(f.rule == "cheme.process-spec" and f.line for f in findings)
    result = _cli("validate")
    assert "error cheme.process-spec" in result.output


def test_a_split_that_split_fixes_cannot_be_varied(plant):
    _edit(plant, lambda d: _node(d, "X1").update(split={"purge": 0.1}))
    process, _ = load(plant)
    assert any("X1's split: fixes purge" in m for _, _, m in spec_problems(process))


def test_the_spec_schema_refuses_contradictions():
    base = {"id": "a", "provenance": "assumed", "target": {"stream": "S", "value": 1}}
    with pytest.raises(ValueError, match="not both"):
        DesignSpec.model_validate(
            {**base, "vary": {"stream": "S", "node": "X", "port": "p", "initial": 1}}
        )
    with pytest.raises(ValueError, match="outlet port"):
        DesignSpec.model_validate({**base, "vary": {"node": "X", "initial": 0.1}})
    target = {"stream": "S", "value": 1, "quantity": "ratio"}
    with pytest.raises(ValueError, match="denominator"):
        DesignSpec.model_validate({**base, "vary": {"stream": "S", "initial": 1}, "target": target})
    target = {"stream": "S", "value": 1, "quantity": "fraction"}
    with pytest.raises(ValueError, match="name the component"):
        DesignSpec.model_validate({**base, "vary": {"stream": "S", "initial": 1}, "target": target})


def test_newton_steps_past_a_direction_the_residual_does_not_see():
    # a singular Jacobian: the least-squares step takes nothing along the null direction
    step = newton_step([[2.0, 0.0], [0.0, 0.0]], [4.0, 0.0])
    assert step is not None
    assert step[0] == pytest.approx(-2.0) and step[1] == pytest.approx(0.0, abs=1e-6)


# -- a flowsheet without tears: two feeds at a charge ratio ---------------------------------

MIXER = """\
schema: cheme/process/v1
kind: flowsheet
title: Two feeds at a charge ratio to one product
units: {pressure: kPa(a), temperature: K, flow: kg/h, duty: kW, enthalpy: kJ/kmol}
cases:
  - {id: design, description: Design, default: true}
tolerance: {abs: 0.01, rel: 0.0001}
specs:
  - id: rate
    vary: {stream: A, initial: 10, with: {B: 0.5}}
    target: {stream: P, quantity: flow, unit: kmol/h, value: 6.0}
    provenance: given
    source: test
feeds:
  - {id: FA, ports: [{id: out, direction: out}]}
  - {id: FB, ports: [{id: out, direction: out}]}
products:
  - {id: PR, ports: [{id: in, direction: in}]}
  - {id: PV, ports: [{id: in, direction: in}]}
steps: []
blocks:
  - id: M1
    class: Mixing
    ports:
      - {id: a, direction: in}
      - {id: b, direction: in}
      - {id: out, direction: out}
  - id: K1
    class: Separating
    recovery:
      outlets: {top: {C3: 0.9, NC4: 0.05}}
      provenance: assumed
      source: test split
    ports:
      - {id: in, direction: in}
      - {id: top, direction: out}
      - {id: bottom, direction: out}
streams:
  - id: A
    from: FA.out
    to: M1.a
    template: butanes
    state:
      design:
        composition: {basis: mass_fraction, values: {NC4: 1.0}, provenance: given}
  - id: B
    from: FB.out
    to: M1.b
    template: butanes
    state:
      design:
        composition: {basis: mass_fraction, values: {C3: 1.0}, provenance: given}
  - {id: M, from: M1.out, to: K1.in, template: butanes}
  - {id: P, from: K1.bottom, to: PR.in, template: butanes}
  - {id: V, from: K1.top, to: PV.in, template: butanes}
"""
MW_C3, MW_C4 = 44.096, 58.122


@pytest.fixture
def mixer(plant) -> Path:
    (plant / "process/flowsheet.yaml").write_text(MIXER)
    return plant


def _mixer_closed(target_kmol: float) -> float:
    """A (kg/h) for *target_kmol* kmol/h in the separator's bottoms P: B = 0.5 A, P takes
    95 % of the n-butane and 10 % of the propane."""
    per_a = 0.95 / MW_C4 + 0.1 * 0.5 / MW_C3
    return target_kmol / per_a


def test_a_feed_and_its_follower_are_solved_without_tears(mixer):
    process, _ = load(mixer)
    found = derive(process, "design")
    assert found.specs.converged, found.specs.problems
    a = found.values[("A", "flow")].value
    assert a == pytest.approx(_mixer_closed(6.0), rel=1e-5)
    b = found.values[("B", "flow")]
    assert b.value == pytest.approx(0.5 * a, rel=1e-5)  # the charge ratio kept
    assert b.source.endswith("spec rate (0.5 x A)") and b.provenance == "calculated"
    # the component separator's outlets from its recovery
    v = found.values[("V", "flow")]
    assert v.value == pytest.approx(0.05 * a + 0.9 * 0.5 * a, rel=1e-5)
    assert v.source == "cheme process propagate: separator K1 from M"


@pytest.mark.parametrize(
    ("target", "closed"),
    [
        ({"quantity": "flow", "value": 200.0}, lambda a: a * (0.95 + 0.05)),
        (
            {"quantity": "annual", "value": 1600.0, "unit": "t", "hours": 8000},
            lambda a: a * (0.95 + 0.05),
        ),
        (
            {
                "quantity": "ratio",
                "component": "C3",
                "basis": "mass",
                "per": {"stream": "V"},
                "value": 0.2,
            },
            None,
        ),
    ],
)
def test_flow_annual_and_ratio_targets(mixer, target, closed):
    def change(d) -> None:
        d["specs"][0]["target"] = {"stream": "P", **target}

    _edit(mixer, change)
    found = derive(load(mixer)[0], "design")
    if closed is None:
        # a ratio of two outlets of a fixed split does not depend on the feed's flow
        assert not found.specs.converged
        assert "does not depend on the variables" in found.specs.problems[0][2]
        return
    a = found.values[("A", "flow")].value
    p = found.values[("P", "flow")].value
    expected = target["value"] if target["quantity"] == "flow" else 1600.0 * 1000 / 8000
    assert p == pytest.approx(expected, rel=1e-5)
    assert closed(a) == pytest.approx(p, rel=1e-5)


def test_a_ratio_target_that_a_second_feed_moves(mixer):
    def change(d) -> None:
        d["specs"][0]["vary"]["with"] = {}
        _stream(d, "A")["state"]["design"]["flow"] = {"value": 100, "provenance": "given"}
        d["specs"][0]["vary"]["stream"] = "B"
        d["specs"][0]["target"] = {
            "stream": "M",
            "component": "C3",
            "quantity": "ratio",
            "per": {"stream": "M", "component": "NC4"},
            "value": 0.8,
        }

    _edit(mixer, change)
    found = derive(load(mixer)[0], "design")
    assert found.specs.converged, found.specs.problems
    b = found.values[("B", "flow")].value
    assert (b / MW_C3) / (100 / MW_C4) == pytest.approx(0.8, rel=1e-5)  # on moles


# -- component separators -----------------------------------------------------------------


def test_separator_outlets_from_their_recovery():
    from chemeascode.domains.process.schema import Recovery

    r = Recovery(outlets={"top": {"A": 0.9, "B": 0.25}}, provenance="assumed")
    out = outlets(r, {"A": 100.0, "B": 40.0, "C": 5.0}, ["top", "bottom"])
    assert out == {
        "top": {"A": 90.0, "B": 10.0, "C": 0.0},
        "bottom": {"A": pytest.approx(10.0), "B": 30.0, "C": 5.0},
    }
    with pytest.raises(ValueError, match="leave out one outlet at most"):
        outlets(r, {"A": 1.0}, ["top", "bottom", "side"])
    with pytest.raises(ValueError, match="not 1"):
        outlets(r, {"A": 1.0}, ["top"])


def test_recovery_declarations_that_do_not_fit_are_validate_errors(mixer):
    def bad(d) -> None:
        k1 = _node(d, "K1")
        k1["recovery"]["outlets"] = {
            "top": {"C3": 0.9, "XX": 0.1, "NC4": 1.2},
            "side": {"C3": 0.2},
        }
        m1 = _node(d, "M1")
        m1["recovery"] = {"outlets": {"out": {"C3": 1.0}}, "provenance": "assumed"}

    _edit(mixer, bad)
    process, _ = load(mixer)
    messages = [f.message for f in recovery_rules(process)]
    for text in (
        "M1: recovery: on a mixer (class Mixing); a separator's class separates",
        "K1: recovery names ['side'], no material outlet port(s) of it",
        "K1: recovery names undeclared component(s) ['XX']",
        "K1: recovery top: fraction(s) of ['NC4'] outside [0, 1]",
        "K1: recovery: the fractions of C3 sum to 1.1, more than 1",
    ):
        assert text in messages, (text, messages)
    assert all(f.rule == "cheme.process-recovery" for f in recovery_rules(process))


def test_a_recovery_beside_another_model_is_refused(plant):
    _edit(
        plant,
        lambda d: _node(d, "R1").update(
            recovery={"outlets": {"out": {"NC4": 1.0}}, "provenance": "assumed"}
        ),
    )
    process, _ = load(plant)
    assert any("beside reactions" in f.message for f in recovery_rules(process))


def test_a_separator_that_cannot_split_is_a_propagate_warning(mixer):
    # a recovery naming a port that is no outlet (validate's error) leaves the outlets open
    _edit(mixer, lambda d: _node(d, "K1")["recovery"]["outlets"].update(side={"C3": 0.05}))
    result = _cli("process", "propagate", "--check")
    assert "cheme.process-recovery [K1]" in result.output, result.output
    assert "not solved: recovery names ['side']" in result.output


# -- a plant without the new fields --------------------------------------------------------


def test_a_flowsheet_without_specs_or_recovery_dumps_as_before():
    fs = Flowsheet.model_validate(
        yaml.safe_load((ROOT / "examples/process-purge-loop/process/flowsheet.yaml").read_text())
    )
    dumped = fs.model_dump(mode="json", by_alias=True)
    assert "specs" not in dumped
    assert all("recovery" not in s for s in dumped["steps"] + dumped["blocks"])
    step = Step.model_validate({"id": "X", "block": "B"})
    assert "recovery" not in step.model_dump(mode="json", by_alias=True)


# -- the batch size that makes a rate (a cycle that grows with the batch) --------------------


@pytest.fixture
def jacketed(tmp_path, monkeypatch) -> Path:
    """The semi-batch example with a jacket-timed cool-down: the cycle is c0 + k batch."""
    root = tmp_path / "semibatch"
    shutil.copytree(SEMIBATCH, root, ignore=shutil.ignore_patterns("build"))
    monkeypatch.chdir(root)
    path = root / "process/recipe.yaml"
    data = yaml.safe_load(path.read_text())
    unit = data["unit_procedures"][0]
    cool = next(o for o in unit["operations"] if o["id"] == "cool")
    del cool["duration"]
    cool["temperatures"] = [330.0, 310.0]
    unit["vessel"]["jacket"] = {
        "u": 400,
        "area": 10.0,
        "coolant_temperature": 290.0,
        "provenance": "assumed",
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return root


def _cycle(process, recipe, batch: float) -> float:
    from chemeascode.domains.process import recipe as R

    trial = recipe.model_copy(
        update={"batch_size": recipe.batch_size.model_copy(update={"value": batch})}
    )
    token = R._TRIAL_BATCH.set(batch)
    try:
        return R.evaluate(process, trial, None, "design", check_basis=False).cycle_time
    finally:
        R._TRIAL_BATCH.reset(token)


def test_the_batch_that_makes_a_rate_against_a_linear_cycle(jacketed):
    from chemeascode.domains.process.recipe import batch_for_rate, load_recipe

    process, _ = load(jacketed)
    recipe, _, _ = load_recipe(jacketed)
    # the cooling time t = C / (U A) ln((T0 - Tc) / (T1 - Tc)) grows with the content's heat
    # capacity C, in proportion to the batch: cycle(b) = c0 + k b
    c1, c2, c3 = (_cycle(process, recipe, b) for b in (3000.0, 12000.0, 24000.0))
    k = (c2 - c1) / 9000.0
    c0 = c1 - 3000.0 * k
    assert c3 == pytest.approx(c0 + 24000.0 * k, rel=1e-9)  # linear indeed
    assert k > 0 and c0 > 0
    # b = r (c0 + k b): b = r c0 / (1 - r k), below the train's cap 1/k
    for rate in (800.0, 1500.0, 0.9 / k):
        fit = batch_for_rate(process, recipe, rate, "design")
        assert fit.batch == pytest.approx(rate * c0 / (1 - rate * k), rel=1e-6)
        assert fit.batch / fit.cycle == pytest.approx(rate, rel=1e-6)
    over = batch_for_rate(process, recipe, 1.2 / k, "design")
    assert over.batch is None and over.best_rate < 1 / k
    assert math.isfinite(over.best_batch)


def test_the_basis_finding_names_the_batch_that_closes_it(jacketed):
    path = jacketed / "process/recipe.yaml"
    data = yaml.safe_load(path.read_text())
    data["batch_size"]["value"] = 3000.0  # the flowsheet's rate needs a larger batch
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    result = _cli("process", "recipe")
    assert "cheme.recipe-basis [S3]" in result.output, result.output
    assert "closes it (cycle" in result.output and "batch = rate x cycle" in result.output
