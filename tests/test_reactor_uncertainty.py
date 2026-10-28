"""Uncertainty through reactors (pre-release issue 157 item 7): draws of the shared distributions,
Monte Carlo of a stirred tank and a fixed bed from their reactions' uncertainties, and that an
uncertainty never makes a calculated outlet stale."""

import json
import math
import random
import shutil
import statistics
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactor_uncertainty import (
    SamplingError,
    _unused,
    sample_node,
    uncertainty_text,
)
from chemeascode.foundation.uncertainty import Uncertainty, draw
from chemeascode.interfaces.cli import app

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_draws_follow_their_distributions():
    rng = random.Random(3)
    lognormal = [draw(Uncertainty(gsd2=4.0), rng) for _ in range(20000)]
    assert statistics.median(lognormal) == pytest.approx(1.0, abs=0.03)
    inside = sum(0.25 <= v <= 4.0 for v in lognormal) / len(lognormal)
    assert inside == pytest.approx(0.95, abs=0.01)  # gsd2: 95 % within value / 4 .. value x 4
    normal = [draw(Uncertainty(distribution="normal", cv=0.1), rng) for _ in range(20000)]
    assert statistics.stdev(normal) == pytest.approx(0.1, rel=0.03)
    uniform = [
        draw(Uncertainty(distribution="uniform", low=0.8, high=1.2), rng) for _ in range(1000)
    ]
    assert min(uniform) >= 0.8 and max(uniform) <= 1.2
    assert draw(None, rng) == 1.0


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
templates:
  - {id: liquid, components: [A, B]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},
            orders: {A: 1}, provenance: assumed}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1]
    reactor: cstr
    tank: {residence_time: 500, provenance: assumed}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: liquid
    state:
      design:
        temperature: {value: 350, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 36, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: liquid
"""


def _plant(tmp_path, reactions=REACTIONS):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: mc\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    (root / "process/reactions.yaml").write_text(reactions)
    return root


UNCERTAIN = REACTIONS.replace(
    "orders: {A: 1}, provenance: assumed}}",
    "orders: {A: 1}, provenance: assumed,\n            uncertainty: {A: {gsd2: 4.0}}}}",
)


def test_a_cstr_spreads_with_its_rate_constant(tmp_path):
    root = _plant(tmp_path, UNCERTAIN)
    result = sample_node(root, "R", samples=400, seed=5)
    assert result.sampled == ["R1.rate.A"] and result.failed == 0
    c = result.conversion
    assert c.deterministic == pytest.approx(0.5)  # k tau = 1
    # X = k tau / (1 + k tau) is monotone in k: its median is the deterministic one
    assert c.p50 == pytest.approx(0.5, abs=0.04)
    # 5 % and 95 % of a lognormal k: k / f and k f with f = exp(1.645 ln(4) / 2) = 3.13
    f = math.exp(1.645 * math.log(4.0) / 2)
    assert c.p5 == pytest.approx(1 / (1 + f), abs=0.03)
    assert c.p95 == pytest.approx(f / (1 + f), abs=0.03)
    assert (
        sample_node(root, "R", samples=50, seed=5).conversion
        == sample_node(root, "R", samples=50, seed=5).conversion
    )


def test_an_uncertainty_never_makes_an_outlet_stale(tmp_path):
    root = _plant(tmp_path)
    process, _ = load(root)
    run(SimpleNamespace(root=root), process, "design", write=True)
    (root / "process/reactions.yaml").write_text(UNCERTAIN)
    process, _ = load(root)
    assert not any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_what_is_not_sampled(tmp_path):
    root = _plant(tmp_path)
    with pytest.raises(SamplingError, match="nothing to sample"):
        sample_node(root, "R")
    path = root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("reactor: cstr", "reactor: equilibrium"))
    with pytest.raises(SamplingError, match="equilibrium reactor"):
        sample_node(root, "R")


def test_a_bed_spreads_its_temperatures(tmp_path, monkeypatch):
    root = tmp_path / "shift"
    shutil.copytree(EXAMPLES / "process-shift", root, ignore=shutil.ignore_patterns("build"))
    path = root / "process/reactions.yaml"
    data = yaml.safe_load(path.read_text())
    data["reactions"][0]["rate"]["uncertainty"] = {"Ea": {"distribution": "normal", "cv": 0.02}}
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    flowsheet = yaml.safe_load((root / "process/flowsheet.yaml").read_text())
    beds = [
        n["id"] for key in ("blocks", "steps") for n in flowsheet.get(key) or [] if n.get("bed")
    ]
    result = sample_node(root, beds[0], samples=40, seed=2)
    t, x = result.outlet_temperature, result.conversion
    assert result.failed == 0
    # the shift bed ends at equilibrium: a slower rate hardly moves its outlet, a narrow spread
    # that never exceeds the declared value by more than the solver's tolerance
    assert t.p5 < t.p95 <= t.deterministic + 1e-3
    assert x.p5 < x.p95 <= x.deterministic + 1e-6
    monkeypatch.chdir(root)
    out = CliRunner().invoke(app, ["process", "reactor-uncertainty", beds[0], "--samples", "20"])
    assert out.exit_code == 0, out.output
    assert "nothing is written" in out.output


def _shift_bed(tmp_path, **fields):
    """The shift example's adiabatic gas bed, its first reaction given *fields*."""
    root = tmp_path / "shift"
    shutil.copytree(EXAMPLES / "process-shift", root, ignore=shutil.ignore_patterns("build"))
    path = root / "process/reactions.yaml"
    data = yaml.safe_load(path.read_text())
    data["reactions"][0] |= fields
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    flowsheet = yaml.safe_load((root / "process/flowsheet.yaml").read_text())
    (bed,) = [
        n["id"] for key in ("blocks", "steps") for n in flowsheet.get(key) or [] if n.get("bed")
    ]
    return root, bed


HEAT = {
    "value": -41000,
    "provenance": "assumed",
    "uncertainty": {"distribution": "uniform", "low": 0.5, "high": 1.5},
}


def test_a_gas_bed_never_samples_a_heat_of_reaction_it_does_not_use(tmp_path):
    """A gas-phase bed's heat of reaction is the ideal-gas data's (pre-release issue 221): its
    uncertainty is reported as not used, never as sampled with a zero spread."""
    root, bed = _shift_bed(tmp_path, heat_of_reaction=HEAT)
    with pytest.raises(SamplingError, match=r"nothing to sample.*heat_of_reaction \(a fixed bed"):
        sample_node(root, bed, samples=5)
    data = yaml.safe_load((root / "process/reactions.yaml").read_text())
    rid = data["reactions"][0]["id"]
    data["reactions"][0]["rate"]["uncertainty"] = {"Ea": {"distribution": "normal", "cv": 0.02}}
    (root / "process/reactions.yaml").write_text(yaml.safe_dump(data, sort_keys=False))
    result = sample_node(root, bed, samples=5, seed=2)
    assert result.sampled == [f"{rid}.rate.Ea"]
    assert list(result.not_used) == [f"{rid}.heat_of_reaction"]
    assert f"not sampled, the model does not use {rid}.heat_of_reaction" in uncertainty_text(result)


def test_a_cstr_does_not_sample_a_conversion(tmp_path):
    conversion = "conversion: {key: A, value: 0.5, provenance: assumed, uncertainty: {gsd2: 4.0}},"
    only = REACTIONS.replace("phase: liquid,", f"phase: liquid, {conversion}")
    root = _plant(tmp_path, only)
    with pytest.raises(SamplingError, match=r"nothing to sample.*R1.conversion"):
        sample_node(root, "R")
    (root / "process/reactions.yaml").write_text(
        UNCERTAIN.replace("phase: liquid,", f"phase: liquid, {conversion}")
    )
    result = sample_node(root, "R", samples=5)
    assert result.sampled == ["R1.rate.A"]
    assert result.not_used == {"R1.conversion": "reactor cstr solves its rate laws"}


def test_an_adiabatic_liquid_tank_samples_its_heat_of_reaction(tmp_path):
    root = _plant(
        tmp_path,
        REACTIONS.replace(
            "phase: liquid,",
            "phase: liquid, heat_of_reaction: "
            "{value: -60000, provenance: assumed, uncertainty: {gsd2: 2.0}},",
        ),
    )
    materials = root / "process/materials.yaml"
    materials.write_text(materials.read_text().replace("0.1}", "0.1, liquid_heat_capacity: 150}"))
    path = root / "process/flowsheet.yaml"
    path.write_text(
        path.read_text().replace("residence_time: 500,", "residence_time: 500, heat: adiabatic,")
    )
    result = sample_node(root, "R", samples=20)
    assert result.sampled == ["R1.heat_of_reaction"] and not result.not_used
    assert result.outlet_temperature.p5 < result.outlet_temperature.p95
    path.write_text(path.read_text().replace(" heat: adiabatic,", ""))
    with pytest.raises(SamplingError, match="an isothermal tank's temperatures"):
        sample_node(root, "R")


def _reaction(phase="liquid", reverse=None):
    rate = SimpleNamespace(reverse=reverse)
    return SimpleNamespace(phase=phase, rate=rate)


@pytest.mark.parametrize(
    ("reaction", "name", "model", "heat", "why"),
    [
        (_reaction(), "equilibrium_constant", "cstr", "isothermal", "no reverse: equilibrium"),
        (_reaction(reverse="equilibrium"), "equilibrium_constant", "pfr", None, ""),
        (_reaction("vapor"), "heat_of_reaction", "cstr", "adiabatic", "gas-phase tank"),
        (_reaction(), "heat_of_reaction", "batch", "adiabatic", ""),
        (_reaction(), "heat_of_reaction", "batch", "isothermal", "isothermal batch's"),
        (_reaction(), "rate", "conversion", None, "does not use the rate law"),
    ],
)
def test_what_each_model_reads(reaction, name, model, heat, why):
    spec = SimpleNamespace(heat=heat)
    item = SimpleNamespace(tank=spec, batch=spec)
    found = _unused(reaction, name, model, item)
    assert (why in found) if why else found == ""


def test_not_used_is_in_the_json(tmp_path, monkeypatch):
    conversion = "conversion: {key: A, value: 0.5, provenance: assumed, uncertainty: {gsd2: 4.0}},"
    root = _plant(tmp_path, UNCERTAIN.replace("phase: liquid,", f"phase: liquid, {conversion}"))
    monkeypatch.chdir(root)
    out = CliRunner().invoke(
        app, ["process", "reactor-uncertainty", "R", "--samples", "10", "--json"]
    )
    assert out.exit_code == 0, out.output
    assert json.loads(out.output)["not_used"] == {
        "R1.conversion": "reactor cstr solves its rate laws"
    }


def test_a_tank_without_an_age_keeps_its_dump():
    from chemeascode.domains.process.schema import Tank

    assert "time_on_stream" not in Tank(volume=1.0, provenance="assumed").model_dump()


SELECTIVITY_MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05}
  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05}
templates:
  - {id: mix, components: [A, B, C]}
"""

SERIES = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}}
  - {id: R2, stoichiometry: {B: -1, C: 1}}
"""

SELECTIVITY_FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
products:
  - {id: P, ports: [{id: in, direction: in}]}
blocks:
  - id: R
    class: ReactingChemicals
    reactions: [R1, R2]
    selectivity: {key: A, conversion: 0.8, products: {B: 0.7}, provenance: given,
                  source: "reaction-evidence O1", UNCERTAINTY}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: mix
    state:
      design:
        flow: {value: 100, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: mix
"""


def _selectivity_plant(tmp_path, uncertainty="", reactions=SERIES):
    """A conversion reactor given by selectivity: (A -> B -> C, 80 % of A converted, 0.7 kmol B
    formed per kmol A converted), its selectivity given *uncertainty* (YAML of the block)."""
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: mc\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(SELECTIVITY_MATERIALS)
    flowsheet = SELECTIVITY_FLOWSHEET.replace(
        ", UNCERTAINTY", f",\n                  uncertainty: {uncertainty}" if uncertainty else ""
    )
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    (root / "process/reactions.yaml").write_text(reactions)
    return root


def test_a_selectivity_reactor_is_sampled_as_propagate_evaluates_it(tmp_path):
    """pre-release issue 300: the key's conversion and the selectivity are sampled and the outlet is
    evaluated from them as propagate does; the deterministic sample is propagate's outlet."""
    from chemeascode.domains.process.model import stream_flows

    root = _selectivity_plant(tmp_path, "{conversion: {gsd2: 1.1}, products: {B: {gsd2: 1.1}}}")
    result = sample_node(root, "R", samples=50, seed=3)
    assert result.model == "selectivity" and result.key == "A"
    assert result.sampled == ["selectivity.conversion", "selectivity.products.B"]
    assert result.failed == 0 and not result.not_used
    process, _ = load(root)
    found = run(SimpleNamespace(root=root), process, "design", write=True)
    assert found.written >= 1, [f.format() for f in found.findings]
    process, _ = load(root)
    (outlet,) = [s for s in process.flowsheet.streams if s.id == "S2"]
    kg = stream_flows(process, outlet, "design").components
    propagated = {n: v / 44.05 for n, v in kg.items()}
    deterministic = {n: s.deterministic for n, s in result.outlet.items()}
    assert deterministic == pytest.approx({"A": 20.0, "B": 56.0, "C": 24.0})
    assert deterministic == pytest.approx({n: propagated.get(n, 0.0) for n in deterministic})
    assert result.conversion.deterministic == pytest.approx(0.8)
    assert "outlet B: 56 kmol/h as declared" in uncertainty_text(result)
    # the selectivity's uncertainty is not part of the outlet's fingerprint
    assert not any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_the_spread_follows_the_selectivitys_uncertainty(tmp_path):
    def sampled(uncertainty):
        root = _selectivity_plant(tmp_path / str(len(list(tmp_path.iterdir()))), uncertainty)
        return sample_node(root, "R", samples=300, seed=4)

    narrow = sampled("{products: {B: {distribution: uniform, low: 0.95, high: 1.05}}}")
    wide = sampled("{products: {B: {distribution: uniform, low: 0.8, high: 1.2}}}")
    assert narrow.sampled == ["selectivity.products.B"] and narrow.failed == 0
    # only the selectivity varies: the conversion of A stays, B (and C with it) spread
    assert narrow.conversion.p5 == narrow.conversion.p95 == pytest.approx(0.8)
    b, wide_b = narrow.outlet["B"], wide.outlet["B"]
    assert 56 * 0.95 - 1e-9 <= b.p5 < b.p95 <= 56 * 1.05 + 1e-9
    assert wide_b.p95 - wide_b.p5 > 3 * (b.p95 - b.p5)
    assert wide.outlet["C"].p5 < wide.outlet["C"].p95
    # the key's conversion: A's outlet spreads, the selectivity holds B's yield per A converted
    converted = sampled("{conversion: {distribution: uniform, low: 0.9, high: 1.1}}")
    assert converted.outlet["A"].p5 < converted.outlet["A"].p95
    x = converted.conversion
    assert 0.72 - 1e-9 <= x.p5 < x.p95 <= 0.88 + 1e-9


def test_a_selectivity_reactor_does_not_use_its_reactions_figures(tmp_path):
    reactions = SERIES.replace(
        "{id: R1, stoichiometry: {A: -1, B: 1}}",
        "{id: R1, stoichiometry: {A: -1, B: 1}, heat_of_reaction: {value: -50000, "
        "provenance: assumed, uncertainty: {gsd2: 2.0}}}",
    )
    root = _selectivity_plant(tmp_path, reactions=reactions)
    with pytest.raises(
        SamplingError, match=r"nothing to sample.*R1.heat_of_reaction \(a selectivity reactor"
    ):
        sample_node(root, "R")
    with pytest.raises(SamplingError, match=r"give selectivity.uncertainty"):
        sample_node(_selectivity_plant(tmp_path / "plain"), "R")
    root = _selectivity_plant(tmp_path / "both", "{conversion: {gsd2: 1.1}}", reactions)
    result = sample_node(root, "R", samples=5)
    assert result.sampled == ["selectivity.conversion"]
    assert result.not_used == {
        "R1.heat_of_reaction": "a selectivity reactor solves no energy balance"
    }
    assert _unused(_reaction(), "conversion", "selectivity", None).startswith(
        "a selectivity reactor takes the key's conversion"
    )


def test_a_selectivity_uncertainty_names_given_products():
    from pydantic import ValidationError

    from chemeascode.domains.process.schema import Selectivity

    spec = {"key": "A", "conversion": 0.8, "products": {"B": 0.7}, "provenance": "given"}
    assert "uncertainty" not in Selectivity.model_validate(spec).model_dump()
    with pytest.raises(ValidationError, match="an uncertainty of a selectivity not given: C"):
        Selectivity.model_validate(spec | {"uncertainty": {"products": {"C": {"gsd2": 1.2}}}})
