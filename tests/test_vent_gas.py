"""Gas-liquid batch, ADR 0071: a vent's inerts passing through, a head space the batch expels,
an inert sweep that degasses a dissolved volatile (Raoult) or gas (Henry), a formed gas's heat
of absorption and the vent condenser's freezing check. Against closed forms: the stripping of
a dissolved volatile by a sweep, ``n_S ln(n/n_0) + (1 - K)(n - n_0) = -g K t``; the head space
a dose displaces at a constant vapour share, ``F = c v q / (1 + v P Y / (R T))``; the head
space's gas at the end, ``(1 - Y) P (V_vessel - V) / (R T)``; the heat of absorption of the
dissolved share. In a plant: propagate with a pad stream and a sweep dose, the rules, the
reports. A vent without the new fields solves, reports and fingerprints as in 1.11.0."""

import math

import pytest
import yaml

from chemeascode.domains.chemistry.liquid import Liquid
from chemeascode.domains.chemistry.reactions import Reactions
from chemeascode.domains.chemistry.thermochemistry import R
from chemeascode.domains.process.model import load, rules
from chemeascode.domains.process.propagate import run
from chemeascode.domains.process.reactors import reactor_report
from chemeascode.domains.process.schema import Batch, HenryConstant, Vent
from chemeascode.domains.process.stirred_tank import Dose, TankError, solve_batch
from chemeascode.domains.process.vent_vapour import VentPhase
from tests.test_semibatch_vent import CP, HEAT, V, _reactions
from tests.test_vent_vapour import GAS, _clausius, _constant, _vapour_flowsheet
from tests.test_vent_vapour import _plant as _vapour_plant

P = 101.325
T = 300.0
DHVAP = 30000.0
SWEEP = 3600.0  # s


def _slow():
    """A -> B, liquid, both at the same molar volume: no change of the volume or the vapour."""
    return Reactions.model_validate(
        {
            "schema": "cheme/reactions/v1",
            "kind": "reactions",
            "reactions": [
                {
                    "id": "R1",
                    "stoichiometry": {"A": -1, "B": 1},
                    "phase": "liquid",
                    "heat_of_reaction": {"value": -1000.0, "provenance": "assumed"},
                    "rate": {
                        "form": "power_law",
                        "basis": "volume",
                        "driving": "concentration",
                        "k": {"A": 1e-3},
                        "orders": {"A": 1},
                        "provenance": "assumed",
                    },
                }
            ],
        }
    ).reactions


def _phase(volatile, pressures, degassing=None, condenser=None, heats=None):
    return VentPhase(
        volatile=list(volatile),
        vapour_pressure={n: p for n, p in pressures.items() if n not in (degassing or {})},
        heat_of_vaporization=heats if heats is not None else dict.fromkeys(volatile, DHVAP),
        liquid_heat_capacity=dict.fromkeys(volatile, 150.0),
        gas={"G": GAS, "N": GAS},
        condenser=condenser,
        degassing=degassing or {},
    )


def _vent(**kw):
    return {"stream": "V"} | kw


def _batch(vent, dosed=False, **kw):
    dosing = {"dosing": [{"stream": "D", "time": SWEEP}]} if dosed else {}
    return Batch.model_validate({"provenance": "assumed", "vent": vent} | dosing | kw)


def _solve(vent, charge, doses, phase=None, pad=None, reactions=None, volumes=None, **kw):
    return solve_batch(
        reactions or _slow(),
        charge,
        T,
        P,
        _batch(vent, bool(doses), **kw),
        {"N": GAS, "G": GAS},
        Liquid(volumes or {"A": 0.1, "B": 0.1, "S": 0.1, "D": 0.1}),
        {"A": 150.0, "B": 150.0, "S": 150.0, "D": 150.0},
        doses=doses,
        vent_phase=phase,
        head_space=pad,
    )


def _stripped(n0, solvent, k, g, t):
    """n of a dissolved volatile left after a sweep of g kmol/s for t s over a non-volatile
    solvent: n_S ln(n / n_0) + (1 - K)(n - n_0) = -g K t (Newton)."""
    n = n0
    for _ in range(100):
        f = solvent * math.log(n / n0) + (1 - k) * (n - n0) + g * k * t
        n -= f / (solvent / n + (1 - k))
    return n


@pytest.mark.parametrize("law", ["raoult", "henry"])
def test_an_inert_sweep_degasses_a_dissolved_volatile(law):
    """A dissolved D (5 % of a non-volatile S) swept by an inert N at g kmol/s: dn/dt = -g y /
    (1 - Y), y = K x; by Raoult's law (K = P_D / P) or Henry's (K = H / P, ADR 0071) alike. The
    sweep passes through whole; the liquid holds no trace of it."""
    k = 0.6
    if law == "raoult":
        phase = _phase("D", {"D": _constant(k * P)})
        vapour = {"components": ["D"]}
    else:
        henry = HenryConstant(points=[(T, k * P)], provenance="assumed")
        phase = _phase("D", {}, degassing={"D": henry}, heats={"D": 20000.0})
        vapour = {"components": ["D"], "henry": {"D": henry.model_dump()}}
    sweep = 2.0  # kmol of N over the hour
    result = _solve(
        _vent(inerts=["N"], vapour=vapour),
        {"S": 5.0, "D": 0.25},
        [Dose({"N": sweep}, T, [(0.0, SWEEP, 1.0)])],
        phase,
    )
    expected = _stripped(0.25, 5.0, k, sweep / SWEEP, SWEEP)
    assert result.outlet["D"] == pytest.approx(expected, rel=1e-7)
    assert result.vent["D"] == pytest.approx(0.25 - expected, rel=1e-7)
    assert result.vent["N"] == pytest.approx(sweep, rel=1e-12)
    assert "N" not in result.outlet or result.outlet["N"] == 0.0
    # the vapour's heat: Raoult's latent heat, or Henry's heat of desorption
    heat = DHVAP if law == "raoult" else 20000.0
    assert result.heat_terms["vent vapour"] == pytest.approx(heat * result.vapour["D"], rel=1e-12)
    assert result.vapour["D"] == pytest.approx(0.25 - expected, rel=1e-7)


def test_a_degassing_gas_passes_the_condenser():
    """With a condenser, a Henry gas passes it whole (it never condenses) and counts with the
    non-condensables; a condensable is flashed over both."""
    henry = HenryConstant(points=[(T, 0.6 * P)], provenance="assumed")
    pressure = _clausius(50.0, 4000.0)
    phase = _phase("SD", {"S": pressure}, degassing={"D": henry}, condenser=270.0)
    vent = _vent(
        inerts=["N"],
        vapour={"components": ["S", "D"], "henry": {"D": henry.model_dump()}},
        condenser={"temperature": 270.0, "provenance": "assumed"},
    )
    result = _solve(vent, {"S": 5.0, "D": 0.25}, [Dose({"N": 2.0}, T, [(0.0, SWEEP, 1.0)])], phase)
    assert result.condensate["D"] == pytest.approx(0.0, abs=1e-15)
    assert result.vent["D"] == pytest.approx(result.vapour["D"], rel=1e-12)
    assert 0 < result.condensate["S"] < result.vapour["S"]
    # the condenser's terms: the Henry gas cooled as a gas, not condensed
    assert result.condenser_terms["condensation"] == pytest.approx(
        result.condensate["S"] * DHVAP, rel=1e-12
    )


def test_a_dose_of_air_passes_its_nitrogen():
    """copper-i-chloride-1 L-3: a dose with an inert passes it straight through to the vent; the
    rest of the dose dissolves (a vent of inerts only, no gas formed)."""
    result = _solve(
        _vent(inerts=["N"]),
        {"S": 5.0},
        [Dose({"A": 1.0, "N": 3.76}, T, [(0.0, SWEEP, 1.0)])],
    )
    assert result.vent == {"N": pytest.approx(3.76, rel=1e-12)}
    assert result.outlet.get("N", 0.0) == 0.0
    assert result.outlet["A"] + result.outlet["B"] == pytest.approx(1.0, rel=1e-9)
    assert result.peak_vent_flow == pytest.approx(3.76 / SWEEP, rel=1e-9)
    with pytest.raises(TankError, match="in the charge"):
        _solve(_vent(inerts=["N"]), {"S": 5.0, "N": 0.1}, [Dose({"A": 1.0}, T, [(0, SWEEP, 1)])])


def test_the_head_space_a_dose_displaces():
    """Every liquid component at P0 (Y = P0 / P constant): the head space expels F = c v q /
    (1 + v P Y / (R T)), c = (1 - Y) P / (R T), while A doses at q (molar volume v), and the
    gas carries F Y / (1 - Y) of vapour; what is left of the pad leaves by the vent at the end."""
    y = 30.0 / P
    phase = _phase("ABS", dict.fromkeys("ABS", _constant(30.0)))
    pad = {"N": 0.5}
    vent = _vent(inerts=["N"], vapour={}, head_space={"stream": "PAD", "provenance": "assumed"})
    result = _solve(vent, {"S": 5.0}, [Dose({"A": 1.0}, T, [(0.0, SWEEP, 1.0)])], phase, pad)
    c = (1 - y) * P / (R * T)
    expelled = c * 0.1 * 1.0 / (1 + 0.1 * P * y / (R * T))
    head = result.head_space
    assert head["expelled_kmol"]["N"] == pytest.approx(expelled, rel=1e-8)
    assert sum(result.vapour.values()) == pytest.approx(expelled * y / (1 - y), rel=1e-8)
    assert head["end_kmol"]["N"] == pytest.approx(0.5 - expelled, rel=1e-8)
    assert result.vent["N"] == pytest.approx(0.5, rel=1e-12)  # the whole pad, in the end
    # the vessel: the charge's 0.5 m3 and the head space its pad fills, saturated
    assert head["start_m3"] == pytest.approx(0.5 * R * T / ((1 - y) * P), rel=1e-12)
    assert head["vessel_m3"] == pytest.approx(0.5 + head["start_m3"], rel=1e-12)
    # at the end the head space holds (1 - Y) P (V_vessel - V) / (R T)
    room = head["vessel_m3"] - result.volume
    assert head["end_m3"] == pytest.approx(room, rel=1e-12)
    assert head["end_kmol"]["N"] == pytest.approx((1 - y) * P * room / (R * T), rel=1e-8)
    # the peak: the displacement's own gas with its vapour, all along the dose
    assert result.peak_vent_flow == pytest.approx(expelled / (1 - y) / SWEEP, rel=1e-6)
    # a pad too small for the dose: the liquid fills the vessel
    with pytest.raises(TankError, match="fills the vessel"):
        _solve(vent, {"S": 5.0}, [Dose({"A": 1.0}, T, [(0.0, SWEEP, 1.0)])], phase, {"N": 0.002})


def test_the_head_space_follows_the_vapour_pressure_rise():
    """A batch of S with A charged, A -> B where only B is volatile: the vapour's share rises as
    B forms and the head space expels its gas; it holds (1 - Y) P (V_vessel - V) / (R T) at the
    end, and its gas formed and expelled add up to the pad."""
    phase = _phase("B", {"B": _constant(60.0)})
    vent = _vent(
        inerts=["N"],
        vapour={"components": ["B"]},
        head_space={"stream": "PAD", "provenance": "assumed"},
    )
    result = _solve(vent, {"S": 4.0, "A": 1.0}, [], phase, {"N": 0.4}, time=3600)
    head = result.head_space
    held = {n: v for n, v in result.outlet.items() if v > 0}
    y = 60.0 * held["B"] / sum(held.values()) / P
    room = head["end_m3"]  # the vessel less the liquid at the end (result.volume: the charge's)
    assert sum(head["end_kmol"].values()) == pytest.approx((1 - y) * P * room / (R * T), rel=1e-7)
    assert head["end_kmol"]["N"] + head["expelled_kmol"]["N"] == pytest.approx(0.4, rel=1e-9)
    assert head["expelled_kmol"]["N"] > 0.02
    assert result.vapour["B"] > 0
    # the balance: B formed is in the liquid or left as vapour
    assert result.outlet["B"] + result.vent["B"] == pytest.approx(result.extents["R1"], rel=1e-9)


def test_a_formed_gas_releases_its_heat_of_absorption():
    """A -> B + G, 40 % of G vented: its dissolved 60 % releases its heat of absorption as it
    forms, a term of the isothermal duty and heat in the adiabatic balance."""
    volumes, cp = V | {"G": 0.05}, CP | {"G": 60.0}
    vent = {
        "stream": "V",
        "components": ["G"],
        "fraction": {"G": 0.4},
        "heat_of_absorption": {"values": {"G": -50000.0}, "provenance": "assumed"},
    }
    batch = Batch.model_validate({"time": 1800, "vent": vent, "provenance": "assumed"})
    args = (_reactions(1e-3), {"S": 5.0, "A": 1.0}, T, P)
    result = solve_batch(*args, batch, {}, Liquid(volumes), cp)
    extent = result.extents["R1"]
    assert result.heat_terms["absorption"] == pytest.approx(0.6 * extent * -50000.0, rel=1e-7)
    assert result.heat_terms["reaction"] == pytest.approx(-extent * -HEAT, rel=1e-7)
    hot = solve_batch(
        *args, batch.model_copy(update={"heat": "adiabatic"}), {}, Liquid(volumes), cp
    )
    plain = Batch.model_validate(
        {"time": 1800, "heat": "adiabatic", "provenance": "assumed"}
        | {"vent": {k: v for k, v in vent.items() if k != "heat_of_absorption"}}
    )
    cool = solve_batch(*args, plain, {}, Liquid(volumes), cp)
    assert hot.temperature > cool.temperature + 1.0


def test_a_semibatchs_peak_cooling_duty_takes_the_heat_of_absorption():
    """A -> B + G dosed into an isothermal semi-batch, 40 % of G vented: the dissolved 60 %
    releases its heat of absorption as it forms, so the peak cooling duty is the one without
    it times 1 + (1 - f) |h_abs| / |dH_r| (the same trajectory, every step's heat scaled)."""
    from tests.test_semibatch_vent import _batch as _dosed

    volumes, cp = V | {"G": 0.05}, CP | {"G": 60.0}
    vent = {"stream": "V", "components": ["G"], "fraction": {"G": 0.4}}
    absorbing = vent | {"heat_of_absorption": {"values": {"G": -50000.0}, "provenance": "assumed"}}

    def solved(spec):
        return solve_batch(
            _reactions(1e-2),
            {"S": 5.0},
            T,
            P,
            _dosed(spec),
            {},
            Liquid(volumes),
            cp,
            doses=[Dose({"A": 1.0}, T, [(0.0, 3600.0, 1.0)])],
        )

    plain, heated = solved(vent), solved(absorbing)
    assert plain.peak_cooling_duty > 0
    assert heated.peak_cooling_duty == pytest.approx(
        plain.peak_cooling_duty * (1 + 0.6 * 50000.0 / abs(HEAT)), rel=1e-9
    )


def test_the_schema_of_the_gas_liquid_vent():
    pad = {"stream": "PAD", "provenance": "assumed"}
    Vent.model_validate(_vent(inerts=["N"], head_space=pad))
    with pytest.raises(ValueError, match="components that form, or inerts"):
        Vent.model_validate(_vent())
    with pytest.raises(ValueError, match="give vent.inerts"):
        Vent.model_validate(_vent(components=["G"], head_space=pad))
    with pytest.raises(ValueError, match="forms or an inert, not both"):
        Vent.model_validate(_vent(components=["G"], inerts=["G"]))
    with pytest.raises(ValueError, match="an inert is a gas"):
        Vent.model_validate(_vent(inerts=["N"], vapour={"components": ["N"]}))
    with pytest.raises(ValueError, match="neither forms nor degasses"):
        Vent.model_validate(
            _vent(
                inerts=["N"],
                heat_of_absorption={"values": {"N": -1.0}, "provenance": "assumed"},
            )
        )
    # a vent without the new fields dumps as in 1.11.0
    assert set(Vent.model_validate(_vent(components=["G"])).model_dump()) == {
        "stream",
        "components",
    }


# -- in a plant ---------------------------------------------------------------------------------

N2 = (
    "  - {id: N, name: nitrogen, formula: N2, molar_mass: 28.01, normal_boiling_point: 77.4,\n"
    "     ideal_gas: {dHf_298: 0, S_298: 191.6, cp_R: [3.5]}}\n"
)
PAD = (
    "  - id: SP\n    from: NP.out\n    to: R.pad\n    template: pad\n    state:\n      design:\n"
    "        temperature: {value: 300, provenance: given}\n"
    "        pressure: {value: 101.325, provenance: given}\n"
    "        flow: {value: 0.5, provenance: given}\n"
    "        composition: {basis: mole_fraction, values: {N: 1.0}, provenance: given}\n"
)
HEAD = (
    "vent: {stream: S4, components: [G], inerts: [N], vapour: {}, head_space: {stream: SP, "
    "provenance: assumed}, condenser: {temperature: 270, energy_port: qc, provenance: assumed}}"
)


def _gas_plant(tmp_path, vent=HEAD, melting="", supply="", pad=PAD):
    from tests.test_vent_vapour import VAPOUR_MATERIALS

    materials = (
        VAPOUR_MATERIALS.replace("templates:\n", N2 + "templates:\n")
        .replace("{id: gas, components: [G, S]}", "{id: gas, components: [G, S, N]}")
        .replace("templates:\n", "templates:\n  - {id: pad, components: [N]}\n")
        .replace("heat_of_vaporization: 30000", "heat_of_vaporization: 30000" + melting)
    )
    flowsheet = (
        _vapour_flowsheet(vent)
        .replace("feeds:\n", "feeds:\n  - {id: NP, ports: [{id: out, direction: out}]}\n")
        .replace("{id: dose, direction: in}", "{id: dose, direction: in}, {id: pad, direction: in}")
        .replace("utility: {kind: cooling_water}", "utility: {kind: cooling_water" + supply + "}")
    )
    return _vapour_plant(tmp_path, flowsheet + pad, materials)


def _found(ws, rule="cheme.process-reactor"):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return [(f.level, f.message) for f in found + rules(process) if f.rule == rule]


def test_propagate_with_a_padded_head_space(tmp_path):
    """The pad stream's nitrogen leaves by the vent, the liquid holds none, the balance closes;
    process reactors reports the head space."""
    ws = _gas_plant(tmp_path)
    assert not [m for level, m in _found(ws) if level == "error"]
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 3, [f.format() for f in result.findings]
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    states = {s["id"]: s.get("state", {}).get("design", {}) for s in data}
    gas, liquid = states["S4"]["composition"]["values"], states["S3"]["composition"]["values"]
    assert "N" not in liquid
    assert 0 < gas["N"] < 1  # the pad, with the gas formed and the vapour past the condenser
    process, _ = load(ws.root)
    from chemeascode.domains.process.model import balance_of

    assert balance_of(process, "R", "design").status == "ok"
    assert not [f.format() for f in rules(process) if f.rule == "cheme.process-calculated-stale"]
    (row,) = reactor_report(ws.root).reactors
    head = row["tank"]["vent"]["head_space"]
    assert head["start_kmol"] == {"N": 0.5} and head["expelled_kmol"]["N"] > 0
    assert row["tank"]["vent"]["kmol_h"]["N"] == pytest.approx(0.5, rel=1e-12)
    from chemeascode.domains.process.reactors import reactor_text

    assert "head space" in reactor_text(reactor_report(ws.root))


def test_gas_rules(tmp_path):
    errors = [m for level, m in _found(_gas_plant(tmp_path, pad="")) if level == "error"]
    assert any("pad SP is no inlet stream" in m for m in errors)
    stray = PAD.replace("values: {N: 1.0}", "values: {N: 0.9, S: 0.1}")
    errors = [m for level, m in _found(_gas_plant(tmp_path / "b", pad=stray)) if level == "error"]
    assert any("carries S, no inert" in m for m in errors)
    unknown = HEAD.replace("inerts: [N]", "inerts: [N, X]")
    errors = [m for level, m in _found(_gas_plant(tmp_path / "c", unknown)) if level == "error"]
    assert any("inert(s) X not declared" in m for m in errors)
    lacking = _gas_plant(tmp_path / "d")
    text = (lacking.root / "process/materials.yaml").read_text()
    (lacking.root / "process/materials.yaml").write_text(
        text.replace("{id: gas, components: [G, S, N]}", "{id: gas, components: [G, S]}")
    )
    errors = [m for level, m in _found(lacking) if level == "error"]
    assert any("lacks N (N: an inert of the vent)" in m for m in errors)


def test_the_vent_condenser_freezing_check(tmp_path):
    """potassium-tert-butoxide-1 L-9: S melts at 280 K; the condenser's outlet at 270 K and the
    cooling water's supply at 275 K both lie below it (warnings); none without a melting
    point, or above it."""
    rule = "cheme.process-condenser-freezing"
    assert not _found(_gas_plant(tmp_path), rule)
    found = _found(
        _gas_plant(
            tmp_path / "b",
            melting=", melting_point: 280",
            supply=", supply_temperature: {value: 275, provenance: assumed}",
        ),
        rule,
    )
    assert [level for level, _ in found] == ["warning", "warning"]
    assert "its outlet at 270 K" in found[0][1] and "S (280 K)" in found[0][1]
    assert "its coolant CW's supply at 275 K" in found[1][1]
    assert not _found(_gas_plant(tmp_path / "c", melting=", melting_point: 260"), rule)


def test_a_sweep_dose_in_a_plant_and_its_screening(tmp_path):
    """A dose that carries an inert (half of it N): propagate passes all the N to the vent and
    none to the liquid; the screening leaves it out of the content (no liquid_molar_volume
    asked of it) and still reports the gas the reaction forms at the MTSR."""
    from chemeascode.domains.process.model import balance_of
    from chemeascode.domains.safety.reaction_hazards import screen

    vent = "vent: {stream: S4, components: [G], inerts: [N], vapour: {}}"
    ws = _gas_plant(tmp_path, vent=vent, pad="")
    flowsheet = ws.root / "process/flowsheet.yaml"
    flowsheet.write_text(
        flowsheet.read_text().replace("values: {A: 1.0}", "values: {A: 0.5, N: 0.5}")
    )
    materials = ws.root / "process/materials.yaml"
    materials.write_text(
        materials.read_text().replace(
            "{id: liquid, components: [A, B, S]}", "{id: liquid, components: [A, B, S, N]}"
        )
    )
    assert not [m for level, m in _found(ws) if level == "error"]
    process, _ = load(ws.root)
    run(ws, process, "design", write=True)
    data = yaml.safe_load(flowsheet.read_text())["streams"]
    states = {s["id"]: s.get("state", {}).get("design", {}) for s in data}
    assert "N" not in states["S3"]["composition"]["values"]
    assert states["S4"]["composition"]["values"]["N"] > 0
    process, _ = load(ws.root)
    assert balance_of(process, "R", "design").status == "ok"
    (entry,) = screen(ws.root).entries
    assert not [m for m in entry.missing if "N" in m.split()]
    assert entry.gas_release is not None and entry.gas_release["rate_kmol_s"] > 0
    assert any("N pass(es) through" in note for note in entry.notes)


def test_a_vent_of_inerts_only_screens_no_gas_release():
    """A vent that takes no formed gas (a sweep, a pad) releases none at a cooling failure:
    no gas release, so no warning for a missing vent capacity."""
    from types import SimpleNamespace

    from chemeascode.domains.safety.reaction_hazards import _forms_gas

    def item(vent):
        return SimpleNamespace(batch=SimpleNamespace(vent=vent))

    assert not _forms_gas(item(Vent.model_validate(_vent(inerts=["N"]))))
    assert _forms_gas(item(Vent.model_validate(_vent(components=["G"], inerts=["N"]))))
    assert not _forms_gas(item(None))


def _batch_gas_plant(tmp_path):
    """The padded gas plant as a plain ``reactor: batch``: the charge S1 (S and A) and the
    head space's pad SP its only inlets, no dose."""
    ws = _gas_plant(tmp_path)
    flowsheet = ws.root / "process/flowsheet.yaml"
    text = flowsheet.read_text()
    dose = text[text.index("  - id: S2\n") : text.index("  - id: S3\n")]
    flowsheet.write_text(
        text.replace(dose, "")
        .replace("reactor: semibatch", "reactor: batch")
        .replace("batch: {dosing: [{stream: S2, time: 3600}], ", "batch: {time: 3600, ")
        .replace("{id: dose, direction: in}, ", "")
        .replace("  - {id: G, ports: [{id: out, direction: out}]}\n", "")
        .replace("flow: {value: 5, provenance: given}", "flow: {value: 6, provenance: given}")
        .replace("values: {S: 1.0}", "values: {S: 0.8333333333, A: 0.1666666667}")
    )
    return ws


def test_a_plain_batch_with_a_padded_head_space(tmp_path):
    """A ``reactor: batch`` with a head space (not only a semi-batch): propagate closes the
    balance, process reactors and the recipe solve it, the hazard screening solves the vented
    batch with its pad (the pad no feed of the liquid) and the Monte Carlo samples it."""
    from chemeascode.domains.process.model import balance_of
    from chemeascode.domains.process.reactor_uncertainty import sample_node
    from chemeascode.domains.process.recipe import Recipe, evaluate
    from chemeascode.domains.safety.reaction_hazards import screen

    ws = _batch_gas_plant(tmp_path)
    assert not [m for level, m in _found(ws) if level == "error"]
    process, _ = load(ws.root)
    result = run(ws, process, "design", write=True)
    assert result.written >= 3, [f.format() for f in result.findings]
    process, _ = load(ws.root)
    assert balance_of(process, "R", "design").status == "ok"
    (row,) = reactor_report(ws.root).reactors
    assert row["tank"]["vent"]["head_space"]["start_kmol"] == {"N": 0.5}
    (entry,) = screen(ws.root).entries
    assert not entry.missing, entry.missing
    assert any(note.startswith("vent S4:") for note in entry.notes)
    assert entry.mtsr is not None
    reactions = ws.root / "process/reactions.yaml"
    reactions.write_text(
        reactions.read_text().replace(
            "orders: {A: 1}, provenance: assumed}}",
            "orders: {A: 1}, provenance: assumed,\n            uncertainty: {A: {gsd2: 4.0}}}}",
        )
    )
    sampled = sample_node(ws.root, "R", samples=20)
    assert sampled.key == "A"
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    s3 = next(s for s in data if s["id"] == "S3")["state"]["design"]["flow"]["value"]
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
                    "operations": [{"id": "react", "kind": "react", "from": "R"}],
                }
            ],
        }
    )
    process, _ = load(ws.root)
    (gas,) = evaluate(process, recipe).vents
    assert "N" in gas.kmol


def _edit(ws, name, *pairs):
    path = ws.root / f"process/{name}.yaml"
    text = path.read_text()
    for old, new in pairs:
        assert old in text, (name, old)
        text = text.replace(old, new)
    path.write_text(text)


def _henry_plant(tmp_path, share=0.10, boiling=", normal_boiling_point: 188", hazard=""):
    """The padded semi-batch whose vent forms G and degasses a dissolved X (no Antoine
    vapour_pressure) by ``vapour.henry`` (ADR 0071), X *share* of the charge, propagated."""
    vent = HEAD.replace(
        "vapour: {}", "vapour: {henry: {X: {points: [[300, 200]], provenance: assumed}}}"
    )
    ws = _gas_plant(tmp_path, vent=vent)
    _edit(
        ws,
        "flowsheet",
        ("values: {S: 1.0}", f"values: {{S: {1 - share:.6g}, X: {share:.6g}}}"),
        *([("hazard: {td24: 390, ", f"hazard: {{td24: 390, {hazard}")] if hazard else []),
    )
    _edit(
        ws,
        "materials",
        (
            "templates:\n",
            "  - {id: X, name: X, formula: HCl, molar_mass: 36.46, liquid_molar_volume: 0.1,\n"
            f"     liquid_heat_capacity: 150{boiling}}}\ntemplates:\n",
        ),
        ("{id: liquid, components: [A, B, S, G]}", "{id: liquid, components: [A, B, S, G, X]}"),
        ("{id: gas, components: [G, S, N]}", "{id: gas, components: [G, S, N, X]}"),
    )
    assert not [m for level, m in _found(ws) if level == "error"]
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written >= 3
    return ws


def test_the_screening_of_a_henry_gas(tmp_path):
    """A vent.vapour.henry gas X (ADR 0071) in the thermal screening (ADR 0069): the gas
    release carries it at its Henry constant (no KeyError for its missing vapour_pressure),
    the default MTT leaves it out at 10 % of the liquid (a declared dissolved gas, not the
    liquid boiling at 188 K) and the dissolved release names it, with what the gas strips."""
    from chemeascode.domains.safety.reaction_hazards import HENRY_GAS, screen

    ws = _henry_plant(tmp_path)
    report = screen(ws.root)
    (entry,) = report.entries
    assert entry.mtt == 400.0 and entry.mtt_basis == "normal boiling point of A"
    assert entry.mtt_left_out == {"X": HENRY_GAS}
    over = entry.gas_release["largest_over_batch"]
    assert over["by_component_kmol_s"]["X"] > 0
    row = entry.dissolved_release["components"]["X"]
    assert row["why"] == HENRY_GAS and row["stripped_kmol_s"] > 0
    assert 0 < entry.gas_release["vapour_share"] < 1
    dissolved = [f for f in report.findings if f.rule == "cheme.reactor-hazard-dissolved"]
    assert dissolved and "X up to" in dissolved[0].message
    assert not [
        f for f in report.findings if f.rule == "cheme.reactor-hazard-class" and f.level != "info"
    ]


def test_the_screenings_saturation_takes_a_henry_gas_at_h_x_over_p():
    """reaction_hazards._saturation: ``y_i = K_i x_i``, Raoult for S, ``H x / P`` for a
    degassing gas X (which has no vapour_pressure)."""
    from chemeascode.domains.safety.reaction_hazards import _saturation

    henry = HenryConstant.model_validate({"points": [[300, 200]], "provenance": "assumed"})
    phase = _phase(["S", "X"], {"S": _constant(50.0)}, degassing={"X": henry})
    y = _saturation(phase, {"S": 0.9, "X": 0.1, "A": 0.0}, T, P)
    assert y == pytest.approx({"S": 0.9 * 50.0 / P, "X": 0.1 * 200.0 / P}, rel=1e-12)


def test_a_henry_gas_without_a_boiling_point_and_at_the_bubble_point(tmp_path):
    """A Henry gas with no normal_boiling_point (a gas above its critical point) is still a
    dissolved release; hazard.mtt_from: bubble-point leaves it out of the bubble point whatever
    its boiling point (here 350 K, above T_p)."""
    from chemeascode.domains.safety.reaction_hazards import HENRY_GAS, screen

    (entry,) = screen(_henry_plant(tmp_path / "a", share=0.001, boiling="").root).entries
    row = entry.dissolved_release["components"]["X"]
    assert row["why"] == HENRY_GAS and row["boiling_point_K"] is None
    assert row["stripped_kmol_s"] > 0
    # the default MTT names it too, with no boiling point (ADR 0071)
    assert entry.mtt_left_out == {"X": HENRY_GAS}
    assert [n for n in entry.notes if n.startswith("MTT: left out") and "X" in n]
    ws = _henry_plant(
        tmp_path / "b",
        boiling=", normal_boiling_point: 350",
        hazard="mtt_from: bubble-point, ",
    )
    (entry,) = screen(ws.root).entries
    assert "X" in entry.bubble_point["left_out"]
    assert not [m for m in entry.missing if "X" in m.replace(",", " ").split()]


VP = ", vapour_pressure: {a: 15.0, b: 4000, form: ln, pressure_unit: kPa, provenance: assumed}"


def _dosed_henry_plant(tmp_path, latent="", absorption="", liquids=""):
    """The padded semi-batch with a vent.vapour.henry gas X that is also dosed (S2 carries X,
    90 % absorbed), X boiling at 350 K (above T_p, 300 K) with *latent* in materials.yaml, A
    and B volatile (with *liquids* in materials.yaml), hazard.mtt_from: bubble-point; the vent
    with *absorption*. Propagated."""
    vent = HEAD.replace(
        "vapour: {}",
        "vapour: {henry: {X: {points: [[300, 200]], provenance: assumed}}}" + absorption,
    )
    ws = _gas_plant(tmp_path, vent=vent)
    _edit(
        ws,
        "flowsheet",
        ("hazard: {td24: 390, ", "hazard: {td24: 390, mtt_from: bubble-point, "),
        ("values: {S: 1.0}", "values: {S: 0.7, A: 0.2, X: 0.1}"),
        ("values: {A: 1.0}", "values: {X: 1.0}"),
        ("{stream: S2, time: 3600}", "{stream: S2, time: 3600, absorbed: 0.9}"),
    )
    _edit(
        ws,
        "materials",
        *(
            (
                f"{{id: {n}, name: {n}, formula: {f}, molar_mass: {m}, liquid_molar_volume: 0.1,\n"
                "     liquid_heat_capacity: 150, normal_boiling_point: 400}",
                f"{{id: {n}, name: {n}, formula: {f}, molar_mass: {m}, liquid_molar_volume: 0.1,\n"
                f"     liquid_heat_capacity: 150, normal_boiling_point: 400{VP}{liquids}}}",
            )
            for n, f, m in (("A", "C2H4O", 44.05), ("B", "C2H4", 28.05))
        ),
        (
            "templates:\n",
            "  - {id: X, name: X, formula: HCl, molar_mass: 36.46, liquid_molar_volume: 0.1,\n"
            f"     liquid_heat_capacity: 150, normal_boiling_point: 350{latent}}}\ntemplates:\n",
        ),
        ("{id: liquid, components: [A, B, S, G]}", "{id: liquid, components: [A, B, S, G, X]}"),
        ("{id: gas, components: [G, S, N]}", "{id: gas, components: [A, B, G, S, N, X]}"),
    )
    assert not [m for level, m in _found(ws) if level == "error"]
    process, _ = load(ws.root)
    assert run(ws, process, "design", write=True).written >= 2
    return ws


def test_a_dosed_henry_gas_is_left_out_of_the_bubble_point(tmp_path):
    """Integration review of 1.12.0: a vent.vapour.henry gas that is also dosed kept the
    reason "dosed gas", so hazard.mtt_from: bubble-point took it (boiling at 350 K, above T_p)
    for a Raoult liquid and lost the MTT for want of its vapour_pressure. The Henry gas is a
    dissolved gas whatever its boiling point, dosed or not (ADR 0071)."""
    from chemeascode.domains.safety.reaction_hazards import HENRY_GAS, screen

    (entry,) = screen(_dosed_henry_plant(tmp_path).root).entries
    assert entry.mtt is not None and entry.mtt_basis.startswith("bubble point")
    assert "X" in entry.bubble_point["left_out"]
    assert not [m for m in entry.missing if "bubble point needs" in m]
    assert entry.dissolved_release["components"]["X"]["why"] == HENRY_GAS


def test_the_boil_up_asks_a_henry_gas_for_its_heat_of_absorption(tmp_path):
    """Integration review of 1.12.0: a content boiling at the MTSR with a Henry gas X in its
    vapour: the gas's latent heat is its heat of desorption, -vent.heat_of_absorption (ADR
    0071), so the missing entry names that field, not heat_of_vaporization (which X has in
    materials.yaml and which does not count for it); given, only A's heat_of_vaporization is
    asked for."""
    from chemeascode.domains.safety.reaction_hazards import screen

    latent = ", heat_of_vaporization: 20000"
    (entry,) = screen(_dosed_henry_plant(tmp_path / "a", latent=latent).root).entries
    (boil,) = [m for m in entry.missing if m.startswith("the boil-up at the MTSR")]
    assert boil == (
        "the boil-up at the MTSR: heat_of_vaporization of A; vent.heat_of_absorption of X "
        "(its heat of desorption, vent.vapour.henry)"
    )
    absorption = ", heat_of_absorption: {values: {X: -20000}, provenance: assumed}"
    ws = _dosed_henry_plant(tmp_path / "b", latent=latent, absorption=absorption)
    (entry,) = screen(ws.root).entries
    (boil,) = [m for m in entry.missing if m.startswith("the boil-up at the MTSR")]
    assert boil == "the boil-up at the MTSR: heat_of_vaporization of A"


def test_an_endothermic_absorption_gives_no_negative_boil_up(tmp_path):
    """Integration review of 1.12.0: the boil-up divides the reactions' heat by the vapour's
    latent heat, a Henry gas's being -vent.heat_of_absorption. A positive heat_of_absorption
    (an endothermic absorption, which the schema allows) outweighing the liquids' made it
    negative, and the boil-up came out at -6129 m3/h, unflagged. The boil-up is now missing
    and says why; an exothermic absorption still gives a positive one."""
    from chemeascode.domains.safety.reaction_hazards import screen

    latent = ", heat_of_vaporization: 20000"
    liquids = ", heat_of_vaporization: 30000"
    absorption = ", heat_of_absorption: {values: {X: 200000}, provenance: assumed}"
    ws = _dosed_henry_plant(tmp_path / "a", latent, absorption, liquids)
    (entry,) = screen(ws.root).entries
    assert "boil_up" not in (entry.gas_release or {})
    (boil,) = [m for m in entry.missing if m.startswith("the boil-up at the MTSR")]
    assert boil == (
        "the boil-up at the MTSR: the vapour's latent heat is not positive "
        "(vent.heat_of_absorption of X: an endothermic absorption, its desorption releases heat)"
    )
    absorption = ", heat_of_absorption: {values: {X: -20000}, provenance: assumed}"
    ws = _dosed_henry_plant(tmp_path / "b", latent, absorption, liquids)
    (entry,) = screen(ws.root).entries
    assert not [m for m in entry.missing if m.startswith("the boil-up at the MTSR")]
    boil_up = entry.gas_release["boil_up"]
    assert boil_up["vapour_kmol_s"] > 0 and boil_up["vapour_m3_h"] > 0
    assert all(v > 0 for v in boil_up["by_component_kmol_s"].values())


def test_a_vent_of_inerts_only_reports_the_boil_up(tmp_path):
    """A vent of inerts only with vapour (ADR 0071) forms no gas at a cooling failure, but a
    content that boils at the MTSR boils up through it (ADR 0069): gas_release.boils and its
    boil_up with the cheme.reactor-hazard-vent warning; below the boiling point no gas
    release and no warning."""
    from chemeascode.domains.safety.reaction_hazards import screen

    vent = (
        "vent: {stream: S4, inerts: [N], vapour: {}, head_space: {stream: SP, provenance: assumed}}"
    )
    found = {}
    for heat in ("-100000", "-1000000"):
        ws = _gas_plant(tmp_path / heat, vent=vent)
        _edit(
            ws,
            "reactions",
            ("{A: -1, B: 1, G: 1}", "{A: -1, B: 1}"),
            ("value: -100000", f"value: {heat}"),
        )
        _edit(
            ws,
            "materials",
            ("formula: C2H4, molar_mass: 28.05", "formula: C2H4O, molar_mass: 44.05"),
            ("{id: liquid, components: [A, B, S, G]}", "{id: liquid, components: [A, B, S]}"),
            ("{id: gas, components: [G, S, N]}", "{id: gas, components: [S, N]}"),
        )
        assert not [m for level, m in _found(ws) if level == "error"]
        process, _ = load(ws.root)
        run(ws, process, "design", write=True)
        report = screen(ws.root)
        (entry,) = report.entries
        found[heat] = (entry, [f for f in report.findings if f.rule == "cheme.reactor-hazard-vent"])
    entry, vents = found["-100000"]
    assert entry.gas_release is None and not vents and not entry.missing
    entry, vents = found["-1000000"]
    gas = entry.gas_release
    assert gas["boils"] and gas["rate_kmol_s"] == 0.0 and "largest_over_batch" not in gas
    assert gas["boil_up"]["vapour_m3_h"] > 0 and entry.mtsr > gas["boil_up"]["temperature_K"]
    (vent_finding,) = vents
    assert vent_finding.level == "warning" and "boil-up at the bubble point" in vent_finding.message
