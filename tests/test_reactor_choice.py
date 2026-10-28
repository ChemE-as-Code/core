"""Reactor choice (pre-release issue 157 item 11): yield and selectivity against conversion for an
ideal PFR, one CSTR and CSTRs in series, against the analytical results of Levenspiel (Chemical
Reaction Engineering, 3rd ed., ch. 7 and 8)."""

import json
import math

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.process.reactor_choice import ChoiceError, choice_svg, compare
from chemeascode.interfaces.cli import app

K1, K2 = 0.002, 0.001
LIQUID = Liquid({"A": 0.1, "B": 0.1, "C": 0.1})  # constant density
FEED = {"A": 36.0}  # kmol/h


def _law(k, orders):
    return {
        "form": "power_law",
        "basis": "volume",
        "driving": "concentration",
        "k": {"A": k},
        "orders": orders,
        "provenance": "assumed",
    }


def _reactions(*items):
    return Reactions.model_validate(
        {"schema": "cheme/reactions/v1", "kind": "reactions", "reactions": list(items)}
    ).reactions


SERIES = _reactions(
    {"id": "R1", "stoichiometry": {"A": -1, "B": 1}, "phase": "liquid", "rate": _law(K1, {"A": 1})},
    {"id": "R2", "stoichiometry": {"B": -1, "C": 1}, "phase": "liquid", "rate": _law(K2, {"B": 1})},
)


def _series():
    return compare(SERIES, FEED, 350.0, 101.325, "A", "B", {}, LIQUID, tanks=3)


def test_series_reaction_against_levenspiel():
    choice = _series()
    pfr, cstr, three = choice.curves
    assert [c.configuration for c in choice.curves] == ["PFR", "CSTR", "3 CSTRs"]
    for tau, _, _, y in pfr.points:
        exact = K1 / (K2 - K1) * (math.exp(-K1 * tau) - math.exp(-K2 * tau))
        assert y == pytest.approx(exact, rel=1e-6, abs=1e-9)
    for tau, _, _, y in cstr.points:
        assert y == pytest.approx(K1 * tau / ((1 + K1 * tau) * (1 + K2 * tau)), rel=1e-7)
    best_pfr, best_cstr, best_three = (c.best()[3] for c in choice.curves)
    pfr_max = (K1 / K2) ** (K2 / (K2 - K1))  # 0.5
    cstr_max = 1 / (1 + math.sqrt(K2 / K1)) ** 2  # 0.343
    assert pfr_max * 0.98 < best_pfr <= pfr_max + 1e-9
    assert cstr_max * 0.98 < best_cstr <= cstr_max + 1e-9
    # tanks in series lie between the two
    assert best_cstr < best_three < best_pfr
    # the PFR's instantaneous selectivity of B falls as B accumulates
    selectivity = [s for _, s in choice.instantaneous]
    assert selectivity[0] == pytest.approx(1.0, abs=1e-3)
    assert selectivity[-1] < 0


def test_parallel_reactions_of_different_orders():
    """A -> B (first order) and A -> C (second order): a low concentration of A favours B, so a
    CSTR beats a PFR in selectivity at the same conversion."""
    parallel = _reactions(
        {
            "id": "R1",
            "stoichiometry": {"A": -1, "B": 1},
            "phase": "liquid",
            "rate": _law(K1, {"A": 1}),
        },
        {
            "id": "R2",
            "stoichiometry": {"A": -1, "C": 1},
            "phase": "liquid",
            "rate": _law(K1 / 5, {"A": 2}),
        },
    )
    choice = compare(parallel, FEED, 350.0, 101.325, "A", "B", {}, LIQUID, tanks=1)
    pfr, cstr = choice.curves

    def at(curve, x):
        pts = sorted((p[1], p[2]) for p in curve.points if p[2] is not None)
        for (x0, s0), (x1, s1) in zip(pts, pts[1:], strict=False):
            if x0 <= x <= x1:
                return s0 + (s1 - s0) * (x - x0) / (x1 - x0)
        raise AssertionError(x)

    for x in (0.3, 0.5, 0.7):
        assert at(cstr, x) > at(pfr, x)
    selectivity = [s for _, s in choice.instantaneous]
    assert selectivity[-1] > selectivity[0]  # rises as A is used up


def test_what_cannot_be_compared():
    with pytest.raises(ChoiceError, match="the key X is not fed"):
        compare(SERIES, FEED, 350.0, 101.325, "X", "B", {}, LIQUID)
    with pytest.raises(ChoiceError, match="formed by none of the reactions"):
        compare(SERIES, FEED, 350.0, 101.325, "A", "D", {}, LIQUID)
    with pytest.raises(ChoiceError, match="the product is the key"):
        compare(SERIES, FEED, 350.0, 101.325, "A", "A", {}, LIQUID)
    no_rate = _reactions({"id": "R1", "stoichiometry": {"A": -1, "B": 1}})
    with pytest.raises(ChoiceError, match="no rate law"):
        compare(no_rate, FEED, 350.0, 101.325, "A", "B", {}, LIQUID)


def test_the_plot_is_svg_with_a_line_per_configuration():
    svg = choice_svg(_series())
    root = etree.fromstring(svg.encode())
    ns = {"s": "http://www.w3.org/2000/svg"}
    paths = root.findall(".//s:path", ns)
    assert len(paths) == 4  # three configurations and the instantaneous selectivity
    assert {p.findtext("s:title", namespaces=ns) for p in paths} == {"PFR", "CSTR", "3 CSTRs"}
    marks = root.findall(".//s:circle", ns)
    assert len(marks) == 3 and "largest yield" in marks[0].findtext("s:title", namespaces=ns)
    assert "prefers-color-scheme: dark" in svg


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
templates:
  - {id: mix, components: [A, B, C]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid,
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.002},
            orders: {A: 1}, provenance: assumed}}
  - {id: R2, stoichiometry: {B: -1, C: 1}, phase: liquid,
     rate: {form: power_law, basis: volume, driving: concentration, k: {A: 0.001},
            orders: {B: 1}, provenance: assumed}}
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
    reactions: [R1, R2]
    reactor: cstr
    tank: {residence_time: 700, provenance: assumed}
    ports: [{id: in, direction: in}, {id: out, direction: out}]
streams:
  - id: S1
    from: F.out
    to: R.in
    template: mix
    state:
      design:
        temperature: {value: 350, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 36, provenance: given}
        composition: {basis: mole_fraction, values: {A: 1.0}, provenance: given}
  - id: S2
    from: R.out
    to: P.in
    template: mix
"""


def test_cli(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: choice-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    monkeypatch.chdir(root)
    runner = CliRunner()
    result = runner.invoke(
        app, ["process", "reactor-choice", "R", "--product", "B", "--svg", "choice.svg"]
    )
    assert result.exit_code == 0, result.output
    assert "PFR: largest yield 0.49" in result.output  # sampled: the exact 0.5 lies between points
    assert (root / "choice.svg").read_text().startswith("<svg")
    result = runner.invoke(app, ["process", "reactor-choice", "R", "--product", "B", "--json"])
    data = json.loads(result.stdout)
    assert data["key"] == "A" and len(data["curves"]) == 3
    result = runner.invoke(app, ["process", "reactor-choice", "R", "--product", "Z"])
    assert result.exit_code == 2


def test_a_product_formed_twice_over_raises_the_axis():
    double = _reactions(
        {
            "id": "R1",
            "stoichiometry": {"A": -1, "B": 2},
            "phase": "liquid",
            "rate": _law(K1, {"A": 1}),
        }
    )
    choice = compare(double, FEED, 350.0, 101.325, "A", "B", {}, Liquid({"A": 0.1, "B": 0.05}))
    assert max(c.best()[3] for c in choice.curves) > 1.9
    svg = choice_svg(choice)
    assert ">2.0</text>" in svg  # the yield axis reaches 2


def test_cli_writes_into_a_new_directory_and_refuses_two_formats(tmp_path, monkeypatch):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: choice-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    monkeypatch.chdir(root)
    runner = CliRunner()
    args = ["process", "reactor-choice", "R", "--product", "B"]
    result = runner.invoke(app, [*args, "--svg", "build/plots/choice.svg"])
    assert result.exit_code == 0, result.output
    assert (root / "build/plots/choice.svg").is_file()
    assert runner.invoke(app, [*args, "--json", "--csv"]).exit_code == 2
