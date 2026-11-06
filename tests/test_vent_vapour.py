"""The vent's vapour, its partial condenser and the Henry split of a vent gas (ADR 0062):
the vapour a gas carries against Y / (1 - Y), the condenser's flash against one condensable
with an inert (G K / (1 - K)), its duty and the vessel's evaporative cooling against their
terms, an adiabatic vented batch's energy balance with its vapour, a Henry component's
solubility at the end, the vapour-laden gas release of the screening; in a plant: propagate's
vent, condensate and condenser duty, the rules, the reports and the recipe. A vent without the
new fields fingerprints as in 1.9.0."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.thermochemistry import IdealGas, R
from chemeascode.domains.process.model import balance_of, load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report, reactor_text
from chemeascode.domains.process.recipe import Recipe, evaluate
from chemeascode.domains.process.schema import Batch, HenryConstant, VapourPressure, Vent
from chemeascode.domains.process.stirred_tank import Dose, TankError, solve_batch
from chemeascode.domains.process.vent_vapour import VentPhase, condense, henry_phase
from chemeascode.domains.safety.reaction_hazards import hazard_text, screen
from tests.test_semibatch_vent import CP, DOSING, HEAT, MATERIALS, V, _batch, _reactions
from tests.test_semibatch_vent import FLOWSHEET as VENTED
from tests.test_semibatch_vent import _plant as _vented_plant

P = 101.325
DHVAP = 30000.0  # kJ/kmol
GAS = IdealGas(dHf_298=-1e5, S_298=200.0, cp_R=[3.5])


def _constant(kpa):
    """An Antoine vapour pressure of *kpa* at every temperature."""
    return VapourPressure(a=math.log10(kpa / 100.0), b=0.0, provenance="assumed")


def _clausius(kpa_300, b):
    """ln P(kPa) = a - b / T, P(300 K) = *kpa_300*."""
    return VapourPressure(
        a=math.log(kpa_300) + b / 300.0, b=b, form="ln", pressure_unit="kPa", provenance="assumed"
    )


def _phase(volatile, pressure, condenser=None, returns=True, henry=None):
    return VentPhase(
        volatile=list(volatile),
        vapour_pressure=dict.fromkeys(volatile, pressure),
        heat_of_vaporization=dict.fromkeys(volatile, DHVAP),
        liquid_heat_capacity={n: CP.get(n, 150.0) for n in volatile},
        gas={"G": GAS},
        condenser=condenser,
        returns=returns,
        henry=henry or {},
    )


def _run(vent, phase, batch=None, t=300.0, doses=None, volumes=V, cp=CP, k=1e-3):
    return solve_batch(
        _reactions(k),
        {"S": 5.0},
        t,
        P,
        batch or _batch(vent),
        {"G": GAS},
        Liquid(volumes),
        cp,
        doses=doses or [Dose({"A": 1.0}, t, [(0.0, DOSING, 1.0)])],
        vent_phase=phase,
    )


VAPOUR = {"stream": "V", "components": ["G"], "vapour": {}}


def test_the_gas_carries_y_over_one_less_y_of_vapour():
    """Every liquid component at the same vapour pressure P0: Y = P0 / P whatever the
    composition, so the vapour is G Y / (1 - Y) of the gas, each component in its share."""
    result = _run(VAPOUR, _phase("ABS", _constant(30.0)))
    y = 30.0 / P
    gas = result.vent["G"]
    assert sum(result.vapour.values()) == pytest.approx(gas * y / (1 - y), rel=1e-9)
    assert result.vapour_share == pytest.approx(y, rel=1e-12)
    # no condenser: what the gas carries off leaves by the vent
    for n in "ABS":
        assert result.vent[n] == pytest.approx(result.vapour[n], rel=1e-12)
    # the balance closes over the two outlets: charged and dosed plus formed
    extent = result.extents["R1"]
    for name, given in (("A", 1.0), ("B", 0.0), ("S", 5.0), ("G", 0.0)):
        nu = {"A": -1, "B": 1, "G": 1}.get(name, 0)
        assert result.outlet[name] + result.vent.get(name, 0.0) == pytest.approx(
            given + nu * extent, rel=1e-9, abs=1e-12
        )
    assert gas == pytest.approx(extent, rel=1e-9)
    # the vessel's evaporative cooling is a heat term of its isothermal duty
    assert result.heat_terms["vent vapour"] == pytest.approx(
        DHVAP * sum(result.vapour.values()), rel=1e-12
    )
    assert result.vent_temperature == pytest.approx(300.0)


def test_one_condensable_with_an_inert_leaves_saturated():
    """The flash: one condensable over an inert passes G K / (1 - K); a gas that holds all of
    its vapour at T_c condenses none; several condensables leave at y_i = K_i x_i."""
    assert condense(1.0, {"S": 1.0}, {"S": 0.2}) == {"S": pytest.approx(0.25, rel=1e-12)}
    assert condense(2.0, {"S": 0.1}, {"S": 0.2}) == {"S": 0.1}  # 0.1/2.1 below K
    assert condense(0.0, {"S": 1.0}, {"S": 0.2}) == {"S": 0.0}
    vapour, k = {"A": 0.6, "S": 0.4}, {"A": 0.05, "S": 0.3}
    past = condense(1.0, vapour, k)
    liquid = {n: vapour[n] - past[n] for n in vapour}
    x = {n: v / sum(liquid.values()) for n, v in liquid.items()}
    y = {n: v / (1.0 + sum(past.values())) for n, v in past.items()}
    for n in vapour:
        assert y[n] == pytest.approx(k[n] * x[n], rel=1e-9)


def test_the_condenser_returns_its_condensate_and_its_duty_is_its_terms():
    """S alone volatile (Clausius-Clapeyron), a condenser at 270 K: the gas past it holds
    G K_c / (1 - K_c) of S whatever the vessel's composition; the liquid loses only that; the
    vessel's heat is the latent heat carried off plus the condensate warmed back, the
    condenser's the condensate's latent heat, the vapour cooled as liquid and G cooled."""
    pressure = _clausius(50.0, 4000.0)
    phase = _phase("S", pressure, condenser=270.0)
    vent = VAPOUR | {"condenser": {"temperature": 270.0, "provenance": "assumed"}}
    result = _run(vent, phase)
    gas = result.vent["G"]
    k_c = pressure.kpa(270.0) / P
    assert result.vent["S"] == pytest.approx(gas * k_c / (1 - k_c), rel=1e-6)
    carried, condensed = result.vapour["S"], result.condensate["S"]
    assert condensed == pytest.approx(carried - result.vent["S"], rel=1e-12)
    assert condensed > 0.5 * carried
    assert result.outlet["S"] == pytest.approx(5.0 - result.vent["S"], rel=1e-9)
    assert result.heat_terms["vent vapour"] == pytest.approx(DHVAP * carried, rel=1e-12)
    assert result.heat_terms["condensate return"] == pytest.approx(
        condensed * 150.0 * 30.0, rel=1e-12
    )
    assert result.condenser_terms == {
        "condensation": pytest.approx(condensed * DHVAP, rel=1e-12),
        "vapour cooled": pytest.approx(carried * 150.0 * 30.0, rel=1e-12),
        "gas cooled": pytest.approx(gas * 3.5 * R * 30.0, rel=1e-9),
    }
    assert result.condenser_heat == pytest.approx(sum(result.condenser_terms.values()))
    assert result.vent_temperature == 270.0
    # the condensate to a stream: the liquid loses all the gas carried off
    away = _run(
        vent | {"condenser": {"temperature": 270.0, "returns": "C", "provenance": "assumed"}},
        _phase("S", pressure, condenser=270.0, returns=False),
    )
    assert away.outlet["S"] == pytest.approx(5.0 - away.vapour["S"], rel=1e-9)
    assert "condensate return" not in away.heat_terms
    # without G's ideal-gas data its cooling is left out (a minor term), and said
    bare = _phase("S", pressure, condenser=270.0)
    bare.gas = {}
    cold = _run(vent, bare)
    assert cold.condenser_terms["gas cooled"] == 0.0
    assert any("leaves out the cooling of G" in n for n in cold.notes)
    # without the heat of vaporization it is not known
    bare.heat_of_vaporization = {}
    assert _run(vent, bare).condenser_heat is None


def test_an_adiabatic_vented_batch_with_vapour_follows_its_closed_form():
    """A batch of S 5, A 1 (no dosing), every component at the same vapour pressure and cp: the
    gas carries c = Y / (1 - Y) kmol of vapour per kmol of G formed, so the liquid holds N =
    N_0 - c xi and C dT = (-dH - c dHvap) dxi / (cp N): T = T_0 - (kappa / c) ln(1 - c xi /
    N_0), kappa = (-dH - c dHvap) / cp (the vapour leaves with its own liquid enthalpy)."""
    batch = Batch.model_validate(
        {"time": 1800, "heat": "adiabatic", "vent": VAPOUR, "provenance": "assumed"}
    )
    result = solve_batch(
        _reactions(1e-3),
        {"S": 5.0, "A": 1.0},
        300.0,
        P,
        batch,
        {"G": GAS},
        Liquid(V),
        CP,
        vent_phase=_phase("ABS", _constant(30.0)),
    )
    extent = result.extents["R1"]
    c = (30.0 / P) / (1 - 30.0 / P)
    assert sum(result.vapour.values()) == pytest.approx(c * extent, rel=1e-9)
    kappa = (-HEAT - c * DHVAP) / 150.0
    expected = 300.0 - kappa / c * math.log(1 - c * extent / 6.0)
    assert result.temperature == pytest.approx(expected, rel=1e-7)
    # without the vapour the batch would run hotter: the evaporative cooling counts
    dry = Batch.model_validate(
        {
            "time": 1800,
            "heat": "adiabatic",
            "vent": {"stream": "V", "components": ["G"]},
            "provenance": "assumed",
        }
    )
    hot = solve_batch(_reactions(1e-3), {"S": 5.0, "A": 1.0}, 300.0, P, dry, {}, Liquid(V), CP)
    assert hot.temperature > result.temperature + 5


def test_a_boiling_content_is_refused():
    with pytest.raises(TankError, match="the content boils"):
        _run(VAPOUR, _phase("S", _constant(150.0)))


def test_henry_leaves_the_liquid_saturated():
    """G with H: the liquid at the end holds x_G = y_G P / H (y_G = 1 alone, 1 - Y with the
    vapour), and the vent the rest of what formed."""
    volumes, cp = V | {"G": 0.05}, CP | {"G": 60.0}
    vent = {
        "stream": "V",
        "components": ["G"],
        "henry": {"G": {"points": [[300.0, 2000.0]], "provenance": "assumed"}},
    }
    result = _run(vent, henry_phase(Vent.model_validate(vent)), volumes=volumes, cp=cp)
    x = result.outlet["G"] / sum(result.outlet.values())
    assert x == pytest.approx(P / 2000.0, rel=1e-8)
    assert result.vent["G"] + result.outlet["G"] == pytest.approx(result.extents["R1"], rel=1e-9)
    (entry,) = result.henry.values()
    assert entry["state"] == "saturated" and 0 < entry["share_vented"] < 1
    # with the vapour (every component at 30 kPa): the gas over the liquid is 1 - Y of G
    both = vent | {"vapour": {}}
    phase = _phase("ABS", _constant(30.0), henry=Vent.model_validate(both).henry)
    result = _run(both, phase, volumes=volumes, cp=cp)
    x = result.outlet["G"] / sum(result.outlet.values())
    # Y over the liquid that holds G too: x = (1 - (1 - x) P0 / P) P / H
    y0, h = 30.0 / P, P / 2000.0
    assert x == pytest.approx((1 - y0) * h / (1 - y0 * h), rel=1e-8)
    # very soluble: all that forms stays dissolved, and the result says so
    soluble = {**vent, "henry": {"G": {"points": [[300.0, 1.0]], "provenance": "assumed"}}}
    result = _run(soluble, henry_phase(Vent.model_validate(soluble)), volumes=volumes, cp=cp)
    assert result.vent.get("G", 0.0) == pytest.approx(0.0, abs=1e-12)
    assert any("below its solubility" in n for n in result.notes)


def test_henry_constant_interpolates_ln_h_in_one_over_t():
    h = HenryConstant(points=[(300.0, 1000.0), (350.0, 4000.0)], provenance="assumed")
    middle = 2 / (1 / 300 + 1 / 350)  # halfway in 1/T
    assert h.kpa(middle) == (pytest.approx(2000.0, rel=1e-12), False)
    assert h.kpa(300.0)[0] == pytest.approx(1000.0)
    assert h.kpa(400.0)[1]  # extrapolated


def test_the_schema_of_the_vent_vapour():
    vent = Vent.model_validate(
        VAPOUR | {"condenser": {"temperature": 270, "energy_port": "qc", "provenance": "assumed"}}
    )
    assert vent.condenser.returns == "vessel"
    with pytest.raises(ValueError, match="needs vapour|give vent.vapour"):
        Vent.model_validate(
            {
                "stream": "V",
                "components": ["G"],
                "condenser": {"temperature": 270, "provenance": "assumed"},
            }
        )
    with pytest.raises(ValueError, match="not both"):
        Vent.model_validate(
            {
                "stream": "V",
                "components": ["G"],
                "fraction": {"G": 0.5},
                "henry": {"G": {"points": [[300, 10]], "provenance": "assumed"}},
            }
        )
    with pytest.raises(ValueError, match="a vent component is a gas"):
        Vent.model_validate(VAPOUR | {"vapour": {"components": ["G"]}})
    # a vent without the new fields dumps as in 1.9.0
    plain = Vent.model_validate({"stream": "V", "components": ["G"]}).model_dump()
    assert set(plain) == {"stream", "components"}


# -- in a plant ---------------------------------------------------------------------------------

S_ANTOINE = (
    "vapour_pressure: {a: %r, b: 4000, form: ln, pressure_unit: kPa, provenance: assumed}, "
    "heat_of_vaporization: 30000" % (math.log(50.0) + 4000 / 300.0)
)
VAPOUR_MATERIALS = (
    MATERIALS.replace(
        "  - {id: S, name: S, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
        "     liquid_heat_capacity: 150, normal_boiling_point: 400}",
        "  - {id: S, name: S, formula: C2H4O, molar_mass: 44.05, liquid_molar_volume: 0.1,\n"
        f"     liquid_heat_capacity: 150, normal_boiling_point: 400, {S_ANTOINE}}}",
    )
    .replace(
        "{id: G, name: G, formula: O, molar_mass: 16.0, normal_boiling_point: 188}",
        "{id: G, name: G, formula: O, molar_mass: 16.0, normal_boiling_point: 188,\n"
        "     ideal_gas: {dHf_298: -100000, S_298: 200, cp_R: [3.5]}}",
    )
    .replace("{id: gas, components: [G]}", "{id: gas, components: [G, S]}")
)
CONDENSER = (
    "vent: {stream: S4, components: [G], vapour: {}, condenser: {temperature: 270, "
    "energy_port: qc, provenance: assumed}}"
)
CW = (
    "  - id: CW\n    category: utility\n    utility: {kind: cooling_water}\n"
    "    ports: [{id: r, direction: in, kind: energy}]\n"
)


def _vapour_flowsheet(vent=CONDENSER, condensate=False):
    text = (
        VENTED.replace("vent: {stream: S4, components: [G]}", vent)
        .replace("products:\n", "products:\n" + CW)
        .replace(
            "{id: gas, direction: out}]",
            "{id: gas, direction: out}, {id: qc, direction: out, kind: energy}"
            + (", {id: cond, direction: out}" if condensate else "")
            + "]",
        )
    )
    text += "  - {id: QC, kind: energy, from: R.qc, to: CW.r}\n"
    if condensate:
        text = text.replace(
            "products:\n", "products:\n  - {id: RCV, ports: [{id: in, direction: in}]}\n"
        )
        text += "  - id: S5\n    from: R.cond\n    to: RCV.in\n    template: gas\n"
    return text


def _plant(tmp_path, flowsheet=None, materials=VAPOUR_MATERIALS):
    ws = _vented_plant(tmp_path, flowsheet or _vapour_flowsheet())
    (ws.root / "process/materials.yaml").write_text(materials)
    return ws


def _states(ws):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    return {s["id"]: s.get("state", {}).get("design", {}) for s in data}


def _errors(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [f.message for f in found + rules(process) if f.level == "error"]


def test_propagate_writes_the_vapour_the_condenser_and_its_duty(tmp_path):
    ws = _plant(tmp_path)
    assert not _errors(ws)
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 3, [f.format() for f in result.findings]
    states = _states(ws)
    gas, liquid, duty = states["S4"], states["S3"], states["QC"]
    # the vent: G and the S past the condenser, at its 270 K
    y = gas["composition"]["values"]
    k_c = math.exp(math.log(50.0) + 4000 / 300.0 - 4000 / 270.0) / P
    assert y["S"] == pytest.approx(k_c, rel=1e-5)
    assert gas["temperature"]["value"] == pytest.approx(270.0)
    assert liquid["temperature"]["value"] == pytest.approx(300.0)
    # the condenser's duty on its own stream, out of R to the cooling water
    assert duty["duty"]["provenance"] == "calculated" and duty["duty"]["value"] > 0
    process, _ = load(ws.root)
    assert balance_of(process, "R", "design").status == "ok"
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    assert not _errors(ws)
    (row,) = reactor_report(ws.root).reactors
    vent = row["tank"]["vent"]
    assert vent["temperature_K"] == 270.0 and vent["condensate_kmol_h"]["S"] > 0
    stream = vent["condenser_duty"]["stream"]
    assert stream["id"] == "QC" and stream["model_kW"] == pytest.approx(duty["duty"]["value"])
    text = reactor_text(reactor_report(ws.root))
    assert "condenser at 270 K condenses S" in text and "vent condenser duty" in text
    # the batch's own duty holds the vessel's evaporative cooling
    assert "vent vapour" in row["model_duty"]["terms_kW"]


def test_the_condensate_to_a_stream(tmp_path):
    vent = CONDENSER.replace("energy_port: qc,", "energy_port: qc, returns: S5,")
    ws = _plant(tmp_path, _vapour_flowsheet(vent, condensate=True))
    assert not _errors(ws), _errors(ws)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    states = _states(ws)
    assert states["S5"]["composition"]["values"] == {"S": 1.0}
    assert states["S5"]["temperature"]["value"] == pytest.approx(270.0)
    process, _ = load(ws.root)
    balance = balance_of(process, "R", "design")
    assert balance.status == "ok" and sorted(balance.streams_out) == ["S3", "S4", "S5"]
    # the condensate is no second liquid outlet: the reactor's outlet is the liquid's S3
    (row,) = reactor_report(ws.root).reactors
    assert row["temperature_out_K"] == pytest.approx(300.0)
    assert row["pressure_out_kPa"] == pytest.approx(P)
    assert "one outlet with a temperature" not in row["missing"]
    assert "T out 300 K" in reactor_text(reactor_report(ws.root))


def test_vent_vapour_rules(tmp_path):
    lacking = VAPOUR_MATERIALS.replace(
        "{id: gas, components: [G, S]}", "{id: gas, components: [G]}"
    )
    assert any(
        "vent stream S4's template gas lacks the vapour's S" in m
        for m in _errors(_plant(tmp_path / "a", materials=lacking))
    )
    stray = CONDENSER.replace("energy_port: qc,", "energy_port: out,")
    assert any(
        "energy_port out is no energy port" in m
        for m in _errors(_plant(tmp_path / "b", _vapour_flowsheet(stray)))
    )
    nowhere = CONDENSER.replace("energy_port: qc,", "energy_port: qc, returns: S9,")
    assert any(
        "condensate stream S9 is no outlet" in m
        for m in _errors(_plant(tmp_path / "c", _vapour_flowsheet(nowhere)))
    )
    named = CONDENSER.replace("vapour: {}", "vapour: {components: [B]}")
    assert any(
        "B without a vapour_pressure" in m
        for m in _errors(_plant(tmp_path / "d", _vapour_flowsheet(named)))
    )
    # a condenser at or above the vessel's 300 K condenses nothing and heats the gas
    hot = CONDENSER.replace("temperature: 270", "temperature: 310")
    assert any(
        "vent condenser at 310 K is not below the vessel's 300 K" in m
        for m in _errors(_plant(tmp_path / "e", _vapour_flowsheet(hot)))
    )
    assert not any("is not below the vessel's" in m for m in _errors(_plant(tmp_path / "f")))
    # an adiabatic batch only starts at the charge's temperature: a warning
    adiabatic = _plant(
        tmp_path / "g",
        _vapour_flowsheet(hot).replace("batch: {dosing:", "batch: {heat: adiabatic, dosing:"),
    )
    process, _ = load(adiabatic.root)
    (found,) = [f for f in rules(process) if "is not below the vessel's" in f.message]
    assert found.level == "warning" and "where the adiabatic batch starts" in found.message


def _held(t_charge, t_condenser):
    """The condenser plant with batch.heat_up, its charge S1 at *t_charge* K and its liquid
    outlet S3 given at 300 K, which the isothermal batch is held at."""
    text = _vapour_flowsheet(
        CONDENSER.replace("temperature: 270", f"temperature: {t_condenser}")
    ).replace("vent: {stream: S4", "heat_up: true, vent: {stream: S4")
    s1 = text.index("  - id: S1")
    text = text[:s1] + text[s1:].replace(
        "temperature: {value: 300", f"temperature: {{value: {t_charge}", 1
    )
    liquid = "  - id: S3\n    from: R.out\n    to: P.in\n    template: liquid\n"
    assert liquid in text and "heat_up: true" in text
    return text.replace(
        liquid,
        liquid
        + "    state:\n      design:\n        temperature: {value: 300, provenance: given}\n",
    )


def test_the_condenser_rule_takes_the_temperature_an_isothermal_batch_is_held_at(tmp_path):
    """An isothermal batch is held at its liquid outlet's given temperature, not its charge's
    (batch.heat_up heats a colder charge to it): a condenser at 290 K over a batch held at
    300 K with its charge at 285 K condenses and is no error; one at 310 K over a batch held at
    300 K with its charge at 320 K heats the gas and is."""
    cold = _plant(tmp_path / "cold", _held(285, 290))
    assert not _errors(cold), _errors(cold)
    process, _ = load(cold.root)
    run(cold, process, "design", write=True)
    (row,) = reactor_report(cold.root).reactors
    assert row["tank"]["vent"]["condensate_kmol_h"]["S"] > 0
    hot = _errors(_plant(tmp_path / "hot", _held(320, 310)))
    assert any(
        "vent condenser at 310 K is not below the vessel's 300 K (the outlet S3 held" in m
        for m in hot
    ), hot


def test_the_vent_condensers_energy_port_is_in_no_outlets_or_tears_fingerprint(tmp_path):
    """The condenser's energy_port only picks the stream its duty is written on: naming it
    changes neither the batch's outlets' inputs nor a tear's fingerprint."""
    from chemeascode.domains.process.recycle import loop_inputs
    from chemeascode.domains.process.stirred_tank import solve_node, tank_inlet

    def fingerprints(name, vent):
        process, _ = load(_plant(tmp_path / name, _vapour_flowsheet(vent)).root)
        node = process.nodes["R"]
        inlets = [s for s in process.flowsheet.streams if process.ends(s)[1].node == "R"]
        _, inputs = solve_node(process, node, tank_inlet(node, inlets), "design")
        return inputs, loop_inputs(process, "design", ["S3"])

    named = fingerprints("a", CONDENSER)
    assert named == fingerprints("b", CONDENSER.replace("energy_port: qc, ", ""))


def test_henry_in_a_plant(tmp_path):
    vent = (
        "vent: {stream: S4, components: [G], "
        "henry: {G: {points: [[300, 2000]], provenance: assumed}}}"
    )
    materials = MATERIALS.replace(
        "normal_boiling_point: 188}",
        "normal_boiling_point: 188, liquid_molar_volume: 0.05, liquid_heat_capacity: 60}",
    )
    ws = _vented_plant(tmp_path, VENTED.replace("vent: {stream: S4, components: [G]}", vent))
    (ws.root / "process/materials.yaml").write_text(materials)
    assert not _errors(ws)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    x = _states(ws)["S3"]["composition"]["values"]["G"]
    assert x == pytest.approx(P / 2000.0, rel=1e-5)
    (row,) = reactor_report(ws.root).reactors
    assert row["tank"]["vent"]["henry"]["G"]["state"] == "saturated"
    assert "G dissolved" in reactor_text(reactor_report(ws.root))


def test_the_screening_takes_the_vapour_laden_gas(tmp_path):
    """The gas release at the MTSR carries the liquid's vapour there: its volume is the
    non-condensables' over 1 - Y; a content whose vapour pressure reaches P at the MTSR
    boils, which is a warning of its own."""
    report = screen(_plant(tmp_path / "a").root)
    (entry,) = report.entries
    gas = entry.gas_release
    assert 0 < gas["vapour_share"] < 1
    assert gas["rate_m3_h"] == pytest.approx(
        gas["noncondensable_m3_h"] / (1 - gas["vapour_share"]), rel=1e-12
    )
    assert gas["noncondensable_m3_h"] == pytest.approx(
        gas["rate_kmol_s"] * R * gas["temperature_K"] / gas["pressure_kPa"] * 3600, rel=1e-12
    )
    # what formed stays on one basis, the non-condensables; the vapour-laden volume apart
    volume = R * gas["temperature_K"] / gas["pressure_kPa"]
    assert gas["formed_m3"] == pytest.approx(gas["formed_kmol"] * volume, rel=1e-12)
    assert gas["formed_m3_with_vapour"] == pytest.approx(
        gas["formed_m3"] / (1 - gas["vapour_share"]), rel=1e-12
    )
    assert (
        f"({gas['formed_m3']:.4g} m3; {gas['formed_m3_with_vapour']:.4g} m3 with the liquid's "
        "vapour) formed by"
    ) in hazard_text(report)
    hot = VAPOUR_MATERIALS.replace(
        "a: %r, b: 4000" % (math.log(50.0) + 4000 / 300.0),
        "a: %r, b: 12000" % (math.log(90.0) + 12000 / 300.0),
    )
    report = screen(_plant(tmp_path / "b", materials=hot).root)
    (entry,) = report.entries
    assert entry.gas_release["boils"] and entry.gas_release["vapour_share"] >= 1
    assert any("the content boils at the MTSR" in f.message for f in report.findings)
    # without vent.vapour the release is as in 1.9.0
    (plain,) = screen(_vented_plant(tmp_path / "c").root).entries
    assert "vapour_share" not in plain.gas_release
    assert "formed_m3_with_vapour" not in plain.gas_release


def test_the_recipe_gives_the_vent_at_the_condensers_temperature(tmp_path):
    ws = _plant(tmp_path)
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    s3 = _states(ws)["S3"]["flow"]["value"]
    recipe = Recipe.model_validate(
        {
            "schema": "cheme/recipe/v1",
            "kind": "recipe",
            "batch_size": {"value": 2 * s3, "unit": "kg", "stream": "S3", "provenance": "assumed"},
            "hours_per_year": {"value": 8000, "provenance": "assumed"},
            "unit_procedures": [
                {
                    "id": "UP1",
                    "unit": "R",
                    "operations": [{"id": "dose", "kind": "dose", "from": "R"}],
                }
            ],
        }
    )
    process, _ = load(ws.root)
    (gas,) = evaluate(process, recipe).vents
    assert gas.temperature == 270.0 and "S" in gas.kmol
    assert gas.peak_volume_flow == pytest.approx(gas.peak_rate * R * 270.0 / P * 3600, rel=1e-9)


#: The outlet fingerprints cheme-as-code 1.9.0 wrote for test_semibatch_vent's vented
#: semi-batch, whole and with a fraction: a vent without the new fields keeps them.
FINGERPRINTS_1_9_0 = {"vent": "227e2a30800bfbcb", "fraction": "0402dcfdf03b8854"}


@pytest.mark.parametrize("kind", ["vent", "fraction"])
def test_a_vent_without_vapour_fingerprints_as_in_1_9_0(tmp_path, kind):
    flowsheet = VENTED
    if kind == "fraction":
        flowsheet = VENTED.replace("components: [G]}", "components: [G], fraction: {G: 0.5}}")
    ws = _vented_plant(tmp_path, flowsheet)
    if kind == "fraction":
        path = ws.root / "process/materials.yaml"
        path.write_text(
            MATERIALS.replace(
                "normal_boiling_point: 188}",
                "normal_boiling_point: 188, liquid_molar_volume: 0.05, liquid_heat_capacity: 50}",
            )
        )
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    states = _states(ws)
    for stream in ("S3", "S4"):
        for name in ("composition", "flow", "temperature", "pressure"):
            assert states[stream][name]["fingerprint"] == FINGERPRINTS_1_9_0[kind]
