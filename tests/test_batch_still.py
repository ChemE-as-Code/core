"""The batch still (``still:``, ADR 0055): Rayleigh's closed form at a constant relative
volatility, Raoult's law against the Rayleigh integral, the mass balance, the solvent swap's
residual old solvent at constant level against its closed form and by put and take, the time
and energy per batch, and its place in cheme process propagate, cheme validate, process stills
and the recipe."""

import json
import math

import pytest
import yaml
from typer.testing import CliRunner

from chemeascode.domains.process.batch_still import StillError, solve_still, still_report
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.model_basis import model_bases
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.recipe import recipe_report
from chemeascode.domains.process.schema import Component, Step, Still, VapourPressure
from chemeascode.foundation.workspace import Workspace

ALPHA = 2.5


def _still(**kw):
    spec = {
        "volatility": {
            "model": "constant",
            "alpha": {"A": ALPHA, "B": 1.0},
            "provenance": "assumed",
        },
        "boilup": {"value": 10.0, "unit": "kmol/h", "provenance": "assumed"},
        "end": {"residue": {"key": "A", "mole_fraction": 0.2}},
        "outlets": {"distillate": "top", "residue": "bottom"},
        "provenance": "assumed",
    }
    return Still.model_validate(spec | kw)


def _rayleigh(x0, x, alpha=ALPHA):
    """ln(W0/W) of a binary at constant relative volatility."""
    return 1 / (alpha - 1) * math.log(x0 * (1 - x) / (x * (1 - x0))) + math.log((1 - x) / (1 - x0))


@pytest.mark.parametrize("x0, x", [(0.5, 0.2), (0.3, 0.05), (0.8, 0.6)])
def test_a_binary_at_constant_volatility_follows_rayleighs_closed_form(x0, x):
    result = solve_still(
        _still(end={"residue": {"key": "A", "mole_fraction": x}}),
        {"A": 100 * x0, "B": 100 * (1 - x0)},
        None,
        {},
        None,
    )
    w = sum(result.residue.values())
    assert result.residue["A"] / w == pytest.approx(x, rel=1e-9)
    assert math.log(100 / w) == pytest.approx(_rayleigh(x0, x), rel=1e-8)
    # the balance closes: charge = distillate + residue, by component
    (cut,) = result.cuts
    for n in ("A", "B"):
        assert cut.moles[n] + result.residue[n] == pytest.approx(100 * (x0 if n == "A" else 1 - x0))
    # 10 kmol/h boiled up from one hour of flows (no recipe): t = D / V
    assert result.time == pytest.approx((100 - w) / 10 * 3600, rel=1e-9)
    assert result.energy is None  # no heats of vaporization


def test_a_share_distilled_and_cuts_in_turn():
    whole = solve_still(_still(end={"distilled": 0.4}), {"A": 50, "B": 50}, None, {}, None)
    assert sum(whole.cuts[0].moles.values()) == pytest.approx(40, rel=1e-9)
    x = whole.residue["A"] / 60
    assert math.log(100 / 60) == pytest.approx(_rayleigh(0.5, x), rel=1e-8)
    cuts = solve_still(
        _still(
            end=None,
            cuts=[
                {"outlet": "c1", "end": {"distilled": 0.2}},
                {"outlet": "c2", "end": {"distilled": 0.4}},
            ],
            outlets={"residue": "bottom"},
        ),
        {"A": 50, "B": 50},
        None,
        {},
        None,
    )
    first, second = cuts.cuts
    assert sum(first.moles.values()) == pytest.approx(20, rel=1e-9)
    assert sum(second.moles.values()) == pytest.approx(20, rel=1e-9)
    # the first cut is richer in the light component, and the residue is the same either way
    assert first.moles["A"] > second.moles["A"]
    assert cuts.residue["A"] == pytest.approx(whole.residue["A"], rel=1e-8)
    assert first.time < second.time == pytest.approx(whole.time, rel=1e-9)


def test_an_end_at_a_time_and_a_specific_boilup():
    timed = solve_still(_still(end={"time": 3 * 3600}), {"A": 50, "B": 50}, None, {}, None)
    assert sum(timed.cuts[0].moles.values()) == pytest.approx(30, rel=1e-8)
    # 0.1 per hour of the charge: 10 kmol/h of 100 kmol
    specific = solve_still(
        _still(boilup={"value": 0.1, "unit": "1/h", "provenance": "assumed"}),
        {"A": 50, "B": 50},
        None,
        {},
        None,
        hours=7.0,
    )
    plain = solve_still(_still(), {"A": 50, "B": 50}, None, {}, None)
    assert specific.time == pytest.approx(plain.time, rel=1e-9)
    # a vapour rate of the still: a batch of 7 hours of flows takes 7 times as long
    big = solve_still(_still(), {"A": 50, "B": 50}, None, {}, None, hours=7.0)
    assert big.time == pytest.approx(7 * plain.time, rel=1e-9)
    assert big.residue == pytest.approx(plain.residue)


# benzene and toluene, NIST WebBook Antoine (log10 bar, K)
BENZENE = {"a": 4.72583, "b": 1660.652, "c": -1.461, "temperature_range": [287.7, 354.07]}
TOLUENE = {"a": 4.07827, "b": 1343.943, "c": -53.773, "temperature_range": [308.52, 384.66]}
LATENT = {"A": 30720.0, "B": 33180.0}  # kJ/kmol at the normal boiling points


def _components(latent=True):
    found = {}
    for n, vp, mw in (("A", BENZENE, 78.11), ("B", TOLUENE, 92.14)):
        data = {
            "id": n,
            "name": n,
            "molar_mass": mw,
            "vapour_pressure": vp | {"provenance": "given", "source": "NIST WebBook"},
        }
        if latent:
            data["heat_of_vaporization"] = LATENT[n]
        found[n] = Component.model_validate(data)
    return found


def _bubble(x, p=101.325):
    vb, vt = (
        VapourPressure.model_validate(d | {"provenance": "given"}) for d in (BENZENE, TOLUENE)
    )
    lo, hi = 300.0, 400.0
    for _ in range(100):
        t = (lo + hi) / 2
        if x * vb.kpa(t) + (1 - x) * vt.kpa(t) > p:
            hi = t
        else:
            lo = t
    return t, x * vb.kpa(t) / p


def test_raoult_follows_the_rayleigh_integral():
    """ln(W0/W) = integral from x to x0 of dx / (y(x) - x), y at the bubble point (Simpson)."""
    raoult = {"model": "raoult", "provenance": "given", "source": "NIST WebBook"}
    spec = _still(volatility=raoult, pressure=101.325)
    result = solve_still(spec, {"A": 50, "B": 50}, None, _components(), 101.325)
    w = sum(result.residue.values())
    x = result.residue["A"] / w
    assert x == pytest.approx(0.2, rel=1e-9)
    n = 2000
    h = (0.5 - x) / n
    f = [1 / (_bubble(x + i * h)[1] - (x + i * h)) for i in range(n + 1)]
    integral = h / 3 * (f[0] + f[-1] + 4 * sum(f[1:-1:2]) + 2 * sum(f[2:-1:2]))
    assert math.log(100 / w) == pytest.approx(integral, rel=1e-6)
    start, end = result.temperatures
    assert start == pytest.approx(_bubble(0.5)[0], abs=1e-6)
    assert end == pytest.approx(_bubble(0.2)[0], abs=1e-6)
    # the latent heat of what boiled up, per batch (one hour of flows): between the pure ones'
    distilled = 100 - w
    assert LATENT["A"] * distilled < result.energy < LATENT["B"] * distilled
    assert result.duty == pytest.approx(result.energy / result.time)
    # a boil-up in kW: V = Q / lambda(y), the same path in another time
    duty = solve_still(
        spec.model_copy(
            update={"boilup": spec.boilup.model_copy(update={"value": 100.0, "unit": "kW"})}
        ),
        {"A": 50, "B": 50},
        None,
        _components(),
        101.325,
    )
    assert duty.residue == pytest.approx(result.residue, rel=1e-8)
    assert duty.time == pytest.approx(duty.energy / 100.0, rel=1e-9)
    # an end at the still's temperature
    hot = solve_still(
        _still(volatility=raoult, end={"temperature": end}),
        {"A": 50, "B": 50},
        None,
        _components(),
        101.325,
    )
    assert hot.residue["A"] / sum(hot.residue.values()) == pytest.approx(0.2, rel=1e-6)


def test_missing_data_is_refused():
    raoult = {"model": "raoult", "provenance": "assumed"}
    with pytest.raises(StillError, match="no vapour_pressure of C"):
        solve_still(_still(volatility=raoult), {"A": 1, "C": 1}, None, _components(), 101.325)
    with pytest.raises(StillError, match="no relative volatility"):
        solve_still(_still(), {"A": 1, "C": 1}, None, {}, None)
    with pytest.raises(StillError, match="heat_of_vaporization"):
        kw = {"value": 100.0, "unit": "kW", "provenance": "assumed"}
        solve_still(
            _still(volatility=raoult, boilup=kw),
            {"A": 1, "B": 1},
            None,
            _components(False),
            101.325,
        )
    with pytest.raises(StillError, match="no pressure"):
        solve_still(_still(volatility=raoult), {"A": 1, "B": 1}, None, _components(), None)
    # a non-volatile component stays in the still; boiling past the volatile ones is refused
    with pytest.raises(StillError, match="boils dry"):
        solve_still(
            _still(end={"distilled": 0.9}, nonvolatile=["P"]),
            {"A": 10, "B": 10, "P": 80},
            None,
            {},
            None,
        )


def test_the_schema_of_a_still():
    with pytest.raises(ValueError, match="give one of"):
        _still(end={"distilled": 0.2, "time": 5})
    with pytest.raises(ValueError, match="when the still stops"):
        _still(end=None)
    with pytest.raises(ValueError, match="raoult"):
        _still(end={"temperature": 360})
    with pytest.raises(ValueError, match="outlets names the residue only"):
        _still(end=None, cuts=[{"outlet": "c1", "end": {"distilled": 0.2}}])
    with pytest.raises(ValueError, match="down_to below 1"):
        _still(feed={"stream": "F", "mode": "portions", "portions": 3})
    # a step's and a component's dump (their fingerprints) are as they were without a still
    assert "still" not in Step.model_validate({"id": "S", "block": "B"}).model_dump()
    comp = Component.model_validate({"id": "A", "name": "A"}).model_dump()
    assert "vapour_pressure" not in comp and "heat_of_vaporization" not in comp


# -- solvent swap -------------------------------------------------------------------------------


def _swap(mode="constant_level", **feed):
    return _still(
        end=None,
        nonvolatile=["P"],
        feed={"stream": "F", "mode": mode, **feed},
    )


def test_a_constant_level_swap_leaves_the_old_solvent_of_its_closed_form():
    """At constant level the content N and the product's share x_P stay; the old solvent A
    (alpha to the new one, B) falls as ((1 - x_P)/alpha) ln(x0/x) + ((alpha - 1)/alpha)(x0 - x)
    = fed / N."""
    result = solve_still(_swap(), {"A": 80, "P": 20}, {"B": 150}, {}, None)
    assert sum(result.residue.values()) == pytest.approx(100, rel=1e-9)
    assert result.residue["P"] == pytest.approx(20)
    x = result.residue["A"] / 100
    lhs = (0.8 / ALPHA) * math.log(0.8 / x) + ((ALPHA - 1) / ALPHA) * (0.8 - x)
    assert lhs == pytest.approx(1.5, rel=1e-8)
    (cut,) = result.cuts
    assert cut.moles["A"] + result.residue["A"] == pytest.approx(80)
    assert cut.moles["B"] + result.residue["B"] == pytest.approx(150)
    assert result.fed == {"A": 0.0, "P": 0.0, "B": 150.0}
    assert result.time == pytest.approx(150 / 10 * 3600, rel=1e-9)
    # concentrating first (down to half the charge), then the swap at that level, leaves less
    lower = solve_still(_swap(down_to=0.5), {"A": 80, "P": 20}, {"B": 150}, {}, None)
    assert sum(lower.residue.values()) == pytest.approx(50, rel=1e-9)
    assert lower.residue["A"] < result.residue["A"]


def test_put_and_take_needs_more_solvent_than_constant_level():
    level = solve_still(_swap(down_to=0.5), {"A": 80, "P": 20}, {"B": 150}, {}, None)
    few = solve_still(
        _swap("portions", portions=3, down_to=0.5), {"A": 80, "P": 20}, {"B": 150}, {}, None
    )
    many = solve_still(
        _swap("portions", portions=60, down_to=0.5), {"A": 80, "P": 20}, {"B": 150}, {}, None
    )
    # back at the level after the last portion, by default
    assert sum(few.residue.values()) == pytest.approx(50, rel=1e-9)
    assert level.residue["A"] < many.residue["A"] < few.residue["A"]
    # more portions come closer to constant level
    more = solve_still(
        _swap("portions", portions=120, down_to=0.5), {"A": 80, "P": 20}, {"B": 150}, {}, None
    )
    assert level.residue["A"] < more.residue["A"] < many.residue["A"]
    # one portion: distil A alone down to 50 kmol (30 kmol of A left), add the 150 kmol of B,
    # distil down to 50 again. At constant alpha, N_A / N_A0 = (N_B / N_B0)^alpha (the
    # product P does not change the vapour), with N_A + N_B = 30.
    one = solve_still(
        _swap("portions", portions=1, down_to=0.5),
        {"A": 80, "B": 0.0, "P": 20},
        {"B": 150},
        {},
        None,
    )
    assert sum(one.residue.values()) == pytest.approx(50, rel=1e-9)
    lo, hi = 0.0, 30.0
    for _ in range(200):
        nb = (lo + hi) / 2
        if 30 * (nb / 150) ** ALPHA + nb > 30:
            hi = nb
        else:
            lo = nb
    assert one.residue["B"] == pytest.approx(nb, rel=1e-8)
    assert one.residue["A"] == pytest.approx(30 - nb, rel=1e-8)
    for result in (few, many, one):
        assert sum(c for cut in result.cuts for c in cut.moles.values()) == pytest.approx(200)
    # an end after the swap: the old solvent's share in the residue
    target = solve_still(
        _still(
            nonvolatile=["P"],
            end={"residue": {"key": "A", "mole_fraction": 1e-7}},
            feed={"stream": "F", "mode": "constant_level", "down_to": 0.5},
        ),
        {"A": 80, "P": 20},
        {"B": 150},
        {},
        None,
    )
    assert target.residue["A"] / sum(target.residue.values()) == pytest.approx(1e-7, rel=1e-6)


# -- in a plant ---------------------------------------------------------------------------------

MATERIALS = f"""\
schema: cheme/process/v1
kind: materials
components:
  - id: A
    name: benzene
    formula: C6H6
    molar_mass: 78.11
    heat_of_vaporization: 30720
    vapour_pressure: {{a: {BENZENE["a"]}, b: {BENZENE["b"]}, c: {BENZENE["c"]},
      temperature_range: [287.7, 354.07], provenance: given, source: NIST WebBook}}
  - id: B
    name: toluene
    formula: C7H8
    molar_mass: 92.14
    heat_of_vaporization: 33180
    vapour_pressure: {{a: {TOLUENE["a"]}, b: {TOLUENE["b"]}, c: {TOLUENE["c"]},
      temperature_range: [308.52, 384.66], provenance: given, source: NIST WebBook}}
  - {{id: P, name: product, formula: C10H8, molar_mass: 128.17}}
templates:
  - {{id: liquid, components: [A, B, P]}}
"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {flow: kmol/h}
feeds:
  - {id: F, ports: [{id: out, direction: out}]}
  - {id: G, ports: [{id: out, direction: out}]}
products:
  - {id: D, ports: [{id: in, direction: in}]}
  - {id: R, ports: [{id: in, direction: in}]}
blocks:
  - id: S
    class: Distilling
    still:
      volatility: {model: raoult, provenance: given, source: NIST WebBook}
      nonvolatile: [P]
      boilup: {value: 20, unit: kmol/h, provenance: assumed, source: jacket estimate}
      feed: {stream: S2, mode: constant_level}
      end: {residue: {key: A, mole_fraction: 0.01}}
      outlets: {distillate: top, residue: bottom}
      provenance: assumed
    ports:
      - {id: in, direction: in}
      - {id: swap, direction: in}
      - {id: top, direction: out}
      - {id: bottom, direction: out}
streams:
  - id: S1
    from: F.out
    to: S.in
    template: liquid
    state:
      design:
        temperature: {value: 300, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 100, provenance: given}
        composition: {basis: mole_fraction, values: {A: 0.8, P: 0.2}, provenance: given}
  - id: S2
    from: G.out
    to: S.swap
    template: liquid
    state:
      design:
        temperature: {value: 300, provenance: given}
        pressure: {value: 101.325, provenance: given}
        flow: {value: 120, provenance: given}
        composition: {basis: mole_fraction, values: {B: 1.0}, provenance: given}
  - id: S3
    from: S.top
    to: D.in
    template: liquid
  - id: S4
    from: S.bottom
    to: R.in
    template: liquid
"""


def _plant(tmp_path, flowsheet=FLOWSHEET, materials=MATERIALS, recipe=None):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: still-test\nstage: concept\nsheets: []\n")
    (root / "process/materials.yaml").write_text(materials)
    (root / "process/flowsheet.yaml").write_text(flowsheet)
    if recipe is not None:
        (root / "process/recipe.yaml").write_text(yaml.safe_dump(recipe, sort_keys=False))
    return Workspace(root)


def _findings(ws, rule="cheme.process-still"):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [f for f in found + rules(process) if f.rule == rule]


def test_propagate_writes_both_outlets_of_a_solvent_swap(tmp_path):
    ws = _plant(tmp_path)
    assert not _findings(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written == 2, [f.format() for f in result.findings]
    streams = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    top, bottom = (s["state"]["design"] for s in streams[2:])
    charge = 80 * 78.11 + 20 * 128.17 + 120 * 92.14
    assert top["flow"]["value"] + bottom["flow"]["value"] == pytest.approx(charge, rel=1e-5)
    assert bottom["composition"]["values"]["A"] == pytest.approx(0.01, rel=1e-4)
    assert top["composition"]["values"]["P"] == 0
    assert top["flow"]["provenance"] == "calculated"
    assert top["flow"]["source"].startswith("cheme process propagate: still S from S1 S2")
    # the step balances, nothing is stale or unsolved
    process, _ = load(ws.root)
    found = rules(process)
    assert not [
        f for f in found if f.rule.startswith("cheme.process-balance") and f.level != "info"
    ]
    assert not [f for f in found if f.rule == "cheme.process-calculated-stale"]
    # a larger swap feed makes the outlets stale
    path = ws.root / "process/flowsheet.yaml"
    path.write_text(path.read_text().replace("value: 120,", "value: 250,"))
    process, _ = load(ws.root)
    assert any(f.rule == "cheme.process-calculated-stale" for f in rules(process))


def test_the_report_and_the_command(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    (unit,) = still_report(ws.root).units
    assert unit["model"] == "solvent swap" and unit["basis"] == "rayleigh" and unit["sourced"]
    sol = unit["solution"]
    assert sol["residue"]["mole_fractions"]["A"] == pytest.approx(0.01, rel=1e-6)
    assert sol["fed"]["kmol_per_batch"] == pytest.approx(120)
    assert sol["boilup_time_h"] > 120 / 20  # the swap, then down to the end
    assert sol["duty_kW"] == pytest.approx(
        sol["energy_kWh_per_batch"] / sol["boilup_time_h"], rel=1e-9
    )
    assert not unit["differences"]
    monkeypatch.chdir(ws.root)
    out = CliRunner().invoke(app, ["process", "stills"])
    assert out.exit_code == 0, out.output
    assert "solvent swap S: basis rayleigh (sourced)" in out.output
    assert "cut top:" in out.output and "residue:" in out.output
    assert "cheme.process-still-note" in out.output  # one batch: one hour of flows
    data = json.loads(CliRunner().invoke(app, ["process", "stills", "--json"]).output)
    assert data["units"][0]["node"] == "S"
    (basis,) = [b for b in model_bases(process) if b.id == "S"]
    assert basis.predictive and basis.basis == "rayleigh"


def test_rules_for_missing_data_and_references(tmp_path):
    start = MATERIALS.index(f"    vapour_pressure: {{a: {TOLUENE['a']}")
    end = MATERIALS.index("NIST WebBook}\n", start) + len("NIST WebBook}\n")
    no_vp = MATERIALS[:start] + MATERIALS[end:]
    ws = _plant(tmp_path / "a", materials=no_vp)
    (finding,) = _findings(ws)
    assert finding.level == "error" and "B lack a vapour_pressure" in finding.message
    assert finding.line is not None and finding.hint
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=False)
    assert any(f.rule == "cheme.process-propagate-still" for f in result.findings)
    # a feed stream that is no inlet, and an outlet that is no port
    wrong = FLOWSHEET.replace("feed: {stream: S2,", "feed: {stream: S9,").replace(
        "outlets: {distillate: top,", "outlets: {distillate: head,"
    )
    messages = [f.message for f in _findings(_plant(tmp_path / "b", flowsheet=wrong))]
    assert any("S9 is no inlet" in m for m in messages)
    assert any("not outlet ports: head" in m and "not named: top" in m for m in messages)
    # a boil-up in kW without heats of vaporization is an error; otherwise only no duty
    no_latent = MATERIALS.replace("    heat_of_vaporization: 30720\n", "")
    (info,) = _findings(_plant(tmp_path / "c", materials=no_latent))
    assert info.level == "info" and "no heat_of_vaporization of A" in info.message
    kw = FLOWSHEET.replace("value: 20, unit: kmol/h", "value: 200, unit: kW")
    (error,) = _findings(_plant(tmp_path / "d", flowsheet=kw, materials=no_latent))
    assert error.level == "error"
    # constant volatility: every volatile component needs its alpha
    alpha = FLOWSHEET.replace(
        "volatility: {model: raoult,", "volatility: {model: constant, alpha: {A: 2.5},"
    )
    (missing,) = _findings(_plant(tmp_path / "e", flowsheet=alpha))
    assert "B lack a relative volatility" in missing.message


RECIPE = {
    "schema": "cheme/recipe/v1",
    "kind": "recipe",
    "batch_size": {"value": 100 * 4.0, "unit": "kg", "stream": "S1", "provenance": "assumed"},
    "hours_per_year": {"value": 8000, "provenance": "assumed"},
    "unit_procedures": [
        {
            "id": "UP1",
            "unit": "S",
            "operations": [
                {
                    "id": "charge",
                    "kind": "charge",
                    "duration": {"value": 1, "unit": "h", "provenance": "assumed"},
                },
                {"id": "swap", "kind": "distil", "from": "S"},
            ],
        }
    ],
}


def test_the_recipe_takes_the_boilup_time_per_batch(tmp_path):
    """The batch is 4 hours of the flowsheet's flows (400 kg of S1 at 100 kg/h): a still
    boiling 20 kmol/h takes 4 times as long as on the one-hour basis."""
    flowsheet = FLOWSHEET.replace("units: {flow: kmol/h}", "units: {flow: kg/h}")
    plain = _plant(tmp_path / "plain", flowsheet=flowsheet)
    (alone,) = still_report(plain.root).units
    ws = _plant(tmp_path / "recipe", flowsheet=flowsheet, recipe=RECIPE)
    (unit,) = still_report(ws.root).units
    one, four = alone["solution"], unit["solution"]
    assert four["hours_of_flows_per_batch"] == pytest.approx(4.0)
    assert four["boilup_time_h"] == pytest.approx(4 * one["boilup_time_h"], rel=1e-9)
    assert four["energy_kWh_per_batch"] == pytest.approx(4 * one["energy_kWh_per_batch"], rel=1e-9)
    assert four["duty_kW"] == pytest.approx(one["duty_kW"], rel=1e-9)
    result = recipe_report(ws.root)
    swap = next(s for s in result.steps if s.operation == "swap")
    assert swap.kind == "distil" and swap.basis == "calculated"
    assert swap.end - swap.start == pytest.approx(four["boilup_time_h"], rel=1e-9)
    assert result.cycle_time == pytest.approx(1 + four["boilup_time_h"], rel=1e-9)
    # from: a still on a react, and a distil from no still, are references the recipe refuses
    bad = json.loads(json.dumps(RECIPE))
    bad["unit_procedures"][0]["operations"][1]["kind"] = "react"
    ws = _plant(tmp_path / "bad", flowsheet=flowsheet, recipe=bad)
    process, _ = load(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.recipe-reference"]
    assert any("is a still" in f.message for f in found)
    nostill = json.loads(json.dumps(RECIPE))
    nostill["unit_procedures"][0]["operations"][1]["from"] = "F"
    ws = _plant(tmp_path / "nostill", flowsheet=flowsheet, recipe=nostill)
    process, _ = load(ws.root)
    found = [f for f in rules(process) if f.rule == "cheme.recipe-reference"]
    assert any("F is no still" in f.message for f in found), [f.format() for f in found]


# -- review fixes ---------------------------------------------------------------------------------


def _ternary(end):
    return _still(
        volatility={
            "model": "constant",
            "alpha": {"L": 4.0, "M": 2.0, "H": 1.0},
            "provenance": "assumed",
        },
        end=end,
    )


def test_a_residue_end_takes_its_direction_from_the_target():
    """An intermediate key first rises (its vapour leaner than the liquid), then falls: a
    target below its share now is reached on the way down, not at once."""
    charge = {"L": 30, "M": 30, "H": 40}
    result = solve_still(
        _ternary({"residue": {"key": "M", "mole_fraction": 0.2}}), charge, None, {}, None
    )
    assert result.residue["M"] / sum(result.residue.values()) == pytest.approx(0.2, rel=1e-8)
    distilled = sum(result.cuts[0].moles.values())
    assert distilled == pytest.approx(82.305, rel=1e-4)
    assert not any("reached when it starts" in n for n in result.notes)
    # the same still in two steps: a first cut, then the same residue end
    two = solve_still(
        Still.model_validate(
            _ternary({"distilled": 0.3}).model_dump(mode="json", exclude={"end", "outlets"})
            | {
                "outlets": {"residue": "bottom"},
                "cuts": [
                    {"outlet": "c1", "end": {"distilled": 0.3}},
                    {"outlet": "c2", "end": {"residue": {"key": "M", "mole_fraction": 0.2}}},
                ],
            }
        ),
        charge,
        None,
        {},
        None,
    )
    assert sum(two.residue.values()) == pytest.approx(100 - distilled, rel=1e-7)
    # the heaviest key never falls: a target below its share now boils the still dry
    with pytest.raises(StillError, match="boils dry before its end"):
        solve_still(
            _ternary({"residue": {"key": "H", "mole_fraction": 0.3}}), charge, None, {}, None
        )
    # it rises to a target above its share now
    rich = solve_still(
        _ternary({"residue": {"key": "H", "mole_fraction": 0.8}}), charge, None, {}, None
    )
    assert rich.residue["H"] / sum(rich.residue.values()) == pytest.approx(0.8, rel=1e-8)
    # a key falling already below its target has reached it (a swap's old solvent)
    done = solve_still(
        _ternary({"residue": {"key": "L", "mole_fraction": 0.5}}), charge, None, {}, None
    )
    assert sum(done.cuts[0].moles.values()) == 0
    assert any("reached when it starts" in n for n in done.notes)


def test_each_cut_takes_its_own_heat():
    raoult = {"model": "raoult", "provenance": "given", "source": "NIST WebBook"}
    spec = _still(
        volatility=raoult,
        end=None,
        outlets={"residue": "bottom"},
        cuts=[
            {"outlet": "c1", "end": {"distilled": 0.3}},
            {"outlet": "c2", "end": {"distilled": 0.6}},
        ],
    )
    result = solve_still(spec, {"A": 50, "B": 50}, None, _components(), 101.325)
    first, second = result.cuts
    assert first.energy + second.energy == pytest.approx(result.energy, rel=1e-12)
    # each cut's heat is its 30 kmol's latent heat, between the pure components'
    for cut in (first, second):
        assert LATENT["A"] * 30 < cut.energy < LATENT["B"] * 30


TEMPLATE_W = MATERIALS.replace(
    "  - {{id: P, name: product, formula: C10H8, molar_mass: 128.17}}".replace("{{", "{").replace(
        "}}", "}"
    ),
    "  - {id: P, name: product, formula: C10H8, molar_mass: 128.17}\n"
    "  - {id: W, name: water, formula: H2O, molar_mass: 18.015}",
).replace("components: [A, B, P]}", "components: [A, B, P, W]}")


def test_a_template_component_no_inlet_carries_is_not_the_stills(tmp_path):
    assert "W, name: water" in TEMPLATE_W and "[A, B, P, W]" in TEMPLATE_W
    ws = _plant(tmp_path, materials=TEMPLATE_W)
    assert not _findings(ws)
    process, _ = load(ws.root)
    (basis,) = [b for b in model_bases(process) if b.id == "S"]
    assert basis.sourced, basis.detail
    # a stream without a composition in any case yet can carry its template's
    flowsheet = FLOWSHEET.replace(
        "        composition: {basis: mole_fraction, values: {B: 1.0}, provenance: given}\n", ""
    )
    messages = [f.message for f in _findings(_plant(tmp_path / "b", flowsheet, TEMPLATE_W))]
    assert any("W lack a vapour_pressure" in m for m in messages), messages


def _stale(ws):
    process, _ = load(ws.root)
    return [f.ids for f in rules(process) if f.rule == "cheme.process-calculated-stale"]


def test_the_boilup_makes_the_outlets_stale_only_through_an_end_at_a_time(tmp_path):
    for name, flowsheet, stale in (
        ("residue", FLOWSHEET, False),
        (
            "time",
            FLOWSHEET.replace(
                "end: {residue: {key: A, mole_fraction: 0.01}}", "end: {time: 30000}"
            ),
            True,
        ),
    ):
        ws = _plant(tmp_path / name, flowsheet=flowsheet)
        process, _ = load(ws.root)
        assert run(ws, process, "design", write=True).written == 2
        assert not _stale(ws)
        path = ws.root / "process/flowsheet.yaml"
        text = path.read_text()
        # the source texts and provenance are no inputs
        text = text.replace("source: jacket estimate", "source: vendor figure")
        text = text.replace(
            "source: NIST WebBook}\n      nonvolatile", "source: DDB}\n      nonvolatile"
        )
        path.write_text(text)
        assert not _stale(ws), name
        path.write_text(text.replace("value: 20, unit: kmol/h", "value: 25, unit: kmol/h"))
        assert bool(_stale(ws)) is stale, name
    # a vapour pressure's fitted range drives notes only
    ws = _plant(tmp_path / "range")
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    path = ws.root / "process/materials.yaml"
    path.write_text(path.read_text().replace("[287.7, 354.07]", "[280.0, 360.0]"))
    assert not _stale(ws)


def test_a_time_end_on_the_stills_own_batch_is_circular(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "end: {residue: {key: A, mole_fraction: 0.01}}", "end: {time: 12000}"
    )
    recipe = json.loads(json.dumps(RECIPE))
    recipe["batch_size"] = {"value": 4000, "unit": "kg", "stream": "S4", "provenance": "assumed"}
    ws = _plant(tmp_path, flowsheet=flowsheet, recipe=recipe)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written == 0
    (finding,) = [f for f in result.findings if f.rule == "cheme.process-propagate-still"]
    assert "circular" in finding.message
    (unit,) = still_report(ws.root).units
    assert "circular" in unit["problem"]
    # on the charge it is not: the still waits for the batch's hours, then solves once
    recipe["batch_size"]["stream"] = "S1"
    ws = _plant(tmp_path / "charge", flowsheet=flowsheet, recipe=recipe)
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written == 2
    (unit,) = still_report(ws.root).units
    assert unit["solution"]["hours_of_flows_per_batch"] == pytest.approx(
        4000 / (80 * 78.11 + 20 * 128.17), rel=1e-4
    )
    assert not unit["differences"]


def test_a_still_that_fails_in_a_later_pass_writes_nothing(tmp_path, monkeypatch):
    from chemeascode.domains.process import batch_still

    real = batch_still.solve_node
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            raise StillError("no bubble point: the still boils dry (nothing volatile left)")
        return real(*args, **kwargs)

    monkeypatch.setattr(batch_still, "solve_node", flaky)
    ws = _plant(tmp_path)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert len(calls) > 1
    assert result.written == 0
    assert any(f.rule == "cheme.process-propagate-still" for f in result.findings)
    streams = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    assert "state" not in streams[2] and "state" not in streams[3]


def test_a_heat_of_vaporization_in_kj_per_mol_is_flagged(tmp_path):
    ws = _plant(
        tmp_path,
        materials=MATERIALS.replace("heat_of_vaporization: 30720", "heat_of_vaporization: 30.72"),
    )
    (warning,) = _findings(ws)
    assert warning.level == "warning" and warning.file == "process/materials.yaml"
    assert "A: heat_of_vaporization 30.72" in warning.message
    assert "multiply by 1000" in warning.hint and warning.line is not None


CUTS = (
    FLOWSHEET.replace(
        "      feed: {stream: S2, mode: constant_level}\n"
        "      end: {residue: {key: A, mole_fraction: 0.01}}\n"
        "      outlets: {distillate: top, residue: bottom}\n",
        "      cuts:\n"
        "        - {outlet: top, end: {distilled: 0.3, basis: mass}}\n"
        "        - {outlet: mid, end: {residue: {key: A, mole_fraction: 0.05}}}\n"
        "      outlets: {residue: bottom}\n",
    )
    .replace(
        "      - {id: swap, direction: in}\n",
        "      - {id: mid, direction: out}\n",
    )
    .replace("    to: S.swap\n", "    to: S.in\n")
    .replace(
        "  - id: S4\n",
        "  - id: S5\n    from: S.mid\n    to: D2.in\n    template: liquid\n  - id: S4\n",
    )
    .replace(
        "  - {id: R, ports: [{id: in, direction: in}]}\n",
        "  - {id: R, ports: [{id: in, direction: in}]}\n"
        "  - {id: D2, ports: [{id: in, direction: in}]}\n",
    )
)


def test_propagate_writes_cuts_in_turn_with_a_kg_h_boilup(tmp_path):
    # one charge: the toluene stream goes to a mixer-free charge, so drop it here
    flowsheet = CUTS.replace("value: 20, unit: kmol/h", "value: 1500, unit: kg/h")
    start = flowsheet.index("  - id: S2\n")
    end = flowsheet.index("  - id: S3\n")
    flowsheet = flowsheet[:start] + flowsheet[end:]
    flowsheet = flowsheet.replace("values: {A: 0.8, P: 0.2}", "values: {A: 0.4, B: 0.4, P: 0.2}")
    ws = _plant(tmp_path, flowsheet=flowsheet)
    assert not _findings(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written == 3, [f.format() for f in result.findings]
    streams = {
        s["id"]: s
        for s in yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    }
    top, mid, bottom = (streams[i]["state"]["design"] for i in ("S3", "S5", "S4"))
    charge = 40 * 78.11 + 40 * 92.14 + 20 * 128.17
    flows = [s["flow"]["value"] for s in (top, mid, bottom)]
    assert sum(flows) == pytest.approx(charge, rel=1e-5)
    assert flows[0] == pytest.approx(0.3 * charge, rel=1e-5)  # a mass share distilled
    assert bottom["composition"]["values"]["A"] == pytest.approx(0.05, rel=1e-4)
    # the first cut is the richer in benzene
    assert top["composition"]["values"]["A"] > mid["composition"]["values"]["A"]
    assert not _stale(ws)
    (unit,) = still_report(ws.root, "design").units
    first, second = unit["solution"]["cuts"]
    assert first["energy_kWh_per_batch"] + second["energy_kWh_per_batch"] == pytest.approx(
        unit["solution"]["energy_kWh_per_batch"], rel=1e-9
    )
    # 1500 kg/h of vapour: the time is the mass distilled over the rate
    distilled = sum(flows[:2])
    assert unit["solution"]["boilup_time_h"] == pytest.approx(distilled / 1500, rel=1e-6)


def test_propagate_writes_a_put_and_take_swap(tmp_path):
    flowsheet = FLOWSHEET.replace(
        "feed: {stream: S2, mode: constant_level}",
        "feed: {stream: S2, mode: portions, portions: 3, down_to: 0.5}",
    )
    ws = _plant(tmp_path, flowsheet=flowsheet)
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written == 2
    streams = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    top, bottom = (s["state"]["design"] for s in streams[2:])
    charge = 80 * 78.11 + 20 * 128.17 + 120 * 92.14
    assert top["flow"]["value"] + bottom["flow"]["value"] == pytest.approx(charge, rel=1e-5)
    assert bottom["composition"]["values"]["A"] == pytest.approx(0.01, rel=1e-4)
    (unit,) = still_report(ws.root).units
    assert "portions" in unit["detail"] and not unit["differences"]
    assert not _stale(ws)


def test_the_command_takes_a_case_and_refuses_an_unknown_one(tmp_path, monkeypatch):
    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path)
    monkeypatch.chdir(ws.root)
    out = CliRunner().invoke(app, ["process", "stills", "--case", "design"])
    assert out.exit_code == 0, out.output
    assert "solvent swap S" in out.output
    out = CliRunner().invoke(app, ["process", "stills", "--case", "nope"])
    assert out.exit_code == 2
    assert "unknown case" in out.output


def test_the_solvent_swap_example_is_current():
    from pathlib import Path

    from chemeascode.project.validate import validate_workspace

    example = Path(__file__).parents[1] / "examples/process-solvent-swap"
    report = validate_workspace(Workspace(example))
    assert not [f.format() for f in report.findings if f.level != "info"]
    process, _ = load(example)
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    (unit,) = still_report(example).units
    sol = unit["solution"]
    assert unit["model"] == "solvent swap" and unit["sourced"] and not unit["differences"]
    assert sol["residue"]["mole_fractions"]["MEOH"] == pytest.approx(0.005, rel=1e-6)
    assert not sol["notes"]
    recipe = recipe_report(example)
    swap = next(s for s in recipe.steps if s.operation == "swap")
    assert swap.basis == "calculated"
    assert swap.end - swap.start == pytest.approx(sol["boilup_time_h"], rel=1e-9)
