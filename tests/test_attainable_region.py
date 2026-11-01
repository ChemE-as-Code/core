"""The candidate attainable region: the convex hull of PFR, CSTR and
CSTR-then-PFR paths, checked on the textbook cases: first-order series reactions, where plug
flow is best, and Van de Vusse kinetics, where a CSTR followed by a PFR beats both."""

import json

import pytest
from lxml import etree
from typer.testing import CliRunner

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.process.attainable_region import RegionPoint, _hull, region, region_svg
from chemeascode.domains.process.reactor_choice import ChoiceError, compare
from chemeascode.interfaces.cli import app

LIQUID = Liquid({"A": 0.1, "B": 0.1, "C": 0.1, "D": 0.2})  # constant density
FEED = {"A": 36.0}


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
    {
        "id": "R1",
        "stoichiometry": {"A": -1, "B": 1},
        "phase": "liquid",
        "rate": _law(0.002, {"A": 1}),
    },
    {
        "id": "R2",
        "stoichiometry": {"B": -1, "C": 1},
        "phase": "liquid",
        "rate": _law(0.001, {"B": 1}),
    },
)
#: Van de Vusse: A -> B -> C (first order) and 2 A -> D (second order), c_A0 = 10 kmol/m3.
VDV = _reactions(
    {
        "id": "R1",
        "stoichiometry": {"A": -1, "B": 1},
        "phase": "liquid",
        "rate": _law(0.01, {"A": 1}),
    },
    {
        "id": "R2",
        "stoichiometry": {"B": -1, "C": 1},
        "phase": "liquid",
        "rate": _law(0.01, {"B": 1}),
    },
    {
        "id": "R3",
        "stoichiometry": {"A": -2, "D": 1},
        "phase": "liquid",
        "rate": _law(0.005, {"A": 2}),
    },
)


def test_the_hull_is_convex_and_drops_inner_points():
    pts = [RegionPoint(x, y, "") for x, y in ((0, 0), (1, 0), (1, 1), (0, 1), (0.5, 0.5), (0.5, 0))]
    hull = _hull(pts)
    assert {(p.x, p.y) for p in hull} == {(0, 0), (1, 0), (1, 1), (0, 1)}


def test_series_reactions_reach_their_best_in_plug_flow():
    found = region(SERIES, FEED, 350.0, 101.325, "A", "B", {}, LIQUID)
    best = found.best()
    assert best.y == pytest.approx(0.5, abs=2e-3)  # Levenspiel's PFR optimum
    assert best.origin.startswith("feed")  # plug flow from the feed
    # every PFR and CSTR point lies inside or on the region
    assert max(p.y for p in found.pfr + found.cstr) <= best.y + 2e-3


def test_van_de_vusse_needs_a_cstr_before_the_pfr():
    found = region(VDV, FEED, 350.0, 101.325, "A", "B", {}, LIQUID)
    best = found.best()
    pure = compare(VDV, FEED, 350.0, 101.325, "A", "B", {}, LIQUID, tanks=1)
    pfr, cstr = (c.best()[3] for c in pure.curves)
    assert best.y > max(pfr, cstr) * 1.05  # the series structure beats either reactor alone
    assert best.origin.startswith("CSTR") and ", PFR" in best.origin
    assert any("not proven complete" in n for n in found.notes)


def test_what_a_region_needs():
    with pytest.raises(ChoiceError, match="not fed"):
        region(SERIES, FEED, 350.0, 101.325, "X", "B", {}, LIQUID)
    with pytest.raises(ChoiceError, match="formed by none"):
        region(SERIES, FEED, 350.0, 101.325, "A", "A", {}, LIQUID)


def test_the_region_plot():
    svg = region_svg(region(VDV, FEED, 350.0, 101.325, "A", "B", {}, LIQUID))
    root = etree.fromstring(svg.encode())
    ns = {"s": "http://www.w3.org/2000/svg"}
    titles = {p.findtext("s:title", namespaces=ns) for p in root.findall(".//s:path", ns)}
    assert {"PFR", "CSTR", "CSTR then PFR"} <= titles
    (mark,) = root.findall(".//s:circle", ns)
    assert "highest yield" in mark.findtext("s:title", namespaces=ns)
    assert "prefers-color-scheme: dark" in svg


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {id: A, name: A, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: B, name: B, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: C, name: C, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1}
  - {id: D, name: D, formula: C4H8O2, molar_mass: 88.1, liquid_molar_volume: 0.2}
templates:
  - {id: mix, components: [A, B, C, D]}
"""

REACTIONS = """\
schema: cheme/reactions/v1
kind: reactions
reactions:
  - {id: R1, stoichiometry: {A: -1, B: 1}, phase: liquid, rate: {form: power_law, basis: volume,
     driving: concentration, k: {A: 0.01}, orders: {A: 1}, provenance: assumed}}
  - {id: R2, stoichiometry: {B: -1, C: 1}, phase: liquid, rate: {form: power_law, basis: volume,
     driving: concentration, k: {A: 0.01}, orders: {B: 1}, provenance: assumed}}
  - {id: R3, stoichiometry: {A: -2, D: 1}, phase: liquid, rate: {form: power_law, basis: volume,
     driving: concentration, k: {A: 0.005}, orders: {A: 2}, provenance: assumed}}
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
    reactions: [R1, R2, R3]
    reactor: cstr
    tank: {residence_time: 60, provenance: assumed}
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
    (root / "plant.yaml").write_text("name: region\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/reactions.yaml").write_text(REACTIONS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    monkeypatch.chdir(root)
    runner = CliRunner()
    args = ["process", "reactor-choice", "R", "--product", "B", "--region-svg", "build/region.svg"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "attainable region (candidate)" in result.output and "CSTR" in result.output
    assert (root / "build/region.svg").is_file()
    document = json.loads(runner.invoke(app, [*args, "--json"]).stdout)
    assert document["region"]["best"]["origin"].startswith("CSTR")


def test_product_in_the_feed_is_not_counted_as_yield():
    clean = region(SERIES, FEED, 350.0, 101.325, "A", "B", {}, LIQUID).best().y
    with_b = region(SERIES, {"A": 36.0, "B": 10.8}, 350.0, 101.325, "A", "B", {}, LIQUID)
    assert with_b.best().y < clean  # the B fed is consumed too; none of it counts as formed
    choice = compare(SERIES, {"A": 36.0, "B": 10.8}, 350.0, 101.325, "A", "B", {}, LIQUID)
    assert with_b.best().y == pytest.approx(choice.curves[0].best()[3], abs=5e-3)
