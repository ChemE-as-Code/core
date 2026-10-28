"""cheme process props (thermo adapter, fill/check, stale values) and process links (phase B).

The reference values and their sources are in tests/data/process_props_references.yaml; what
passes here is what the method claims (props.VALIDATED), nothing more.
"""

import math
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("thermo")

from chemeascode.domains.process.fill import run
from chemeascode.domains.process.model import link_problem, load, rules
from chemeascode.domains.process.props import (
    METASTABLE_TOLERANCE,
    VALIDATED,
    Adapter,
    Inputs,
    Unsupported,
)
from chemeascode.foundation.workspace import Workspace

REFS = yaml.safe_load(
    (Path(__file__).parent / "data" / "process_props_references.yaml").read_text()
)
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
FLUID = {"N2": "N2", "O2": "O2", "AR": "AR"}
AIR = {"N2": 0.7812, "O2": 0.2096, "AR": 0.0092}

MATERIALS = """\
# Air components (test plant)
schema: cheme/process/v1
kind: materials
components:
  - {id: N2, name: Nitrogen, cas: 7727-37-9, molar_mass: 28.014}
  - {id: O2, name: Oxygen, cas: 7782-44-7, molar_mass: 31.998}
  - {id: AR, name: Argon, cas: 7440-37-1, molar_mass: 39.948}
  - {id: CO2, name: Carbon dioxide, cas: 124-38-9, molar_mass: 44.009}
templates:
  - {id: air, components: [N2, O2, AR, CO2]}
property_method:
  adapter: thermo
  status: placeholder
"""

FLOWSHEET = """\
# Test flowsheet: comments must survive props --fill.
schema: cheme/process/v1
kind: flowsheet
units: {pressure: kPa(a), temperature: K, flow: kg/h, duty: kW, enthalpy: kJ/kmol,
  enthalpy_reference: {state: ideal_gas, temperature: 298.15, pressure: 101.325}}
feeds:
  - {id: AIR, ports: [{id: a, direction: out}, {id: b, direction: out}, {id: c, direction: out}]}
products:
  - {id: OUT, ports: [{id: a, direction: in}, {id: b, direction: in}, {id: c, direction: in}]}
streams:
  - id: S1
    from: AIR.a
    to: OUT.a
    template: air
    links: [{target: equipment, ref: K-1101}, {target: line, ref: "100-AIR-001", sheet: P-01}]
    state:
      design:
        # ambient air
        pressure: {value: 101.325, provenance: given}
        temperature: {value: 293.15, provenance: given}
        composition:
          {basis: mole_fraction, values: {N2: 0.7812, O2: 0.2096, AR: 0.0092}, provenance: assumed}
  - id: S2
    from: AIR.b
    to: OUT.b
    template: air
    state:
      design:
        pressure: {value: 130, provenance: given}
        temperature: {value: 91.0, provenance: assumed}
        composition: {basis: mole_fraction, values: {O2: 0.995, AR: 0.005}, provenance: assumed}
        phase: {value: liquid, provenance: given, source: LOX product}
        calculated:
          density: {value: 1130, unit: kg/m3, provenance: given, source: vendor}
  - id: S3
    from: AIR.c
    to: OUT.c
    template: air
    state:
      design:
        pressure: {value: 130, provenance: given}
        temperature: {value: 85.0, provenance: assumed}
        composition: {basis: mole_fraction, values: {N2: 0.5, O2: 0.5}, provenance: assumed}
"""


@pytest.fixture
def plant(tmp_path):
    root = tmp_path / "plant"
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text(
        "name: props-test\nstage: concept\nsheets:\n  - {id: P-01, title: Air}\n"
    )
    (root / "process/materials.yaml").write_text(MATERIALS)
    (root / "process/flowsheet.yaml").write_text(FLOWSHEET)
    return Workspace(root)


@pytest.fixture
def adapter(plant):
    process, _ = load(plant.root)
    return Adapter(process)


def _fill(ws, write=True):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return run(ws, process, "design", write=write)


def _state(ws, sid):
    data = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    return next(s for s in data["streams"] if s["id"] == sid)["state"]["design"]


def _edit_state(ws, sid, key, value):
    path = ws.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    next(s for s in data["streams"] if s["id"] == sid)["state"]["design"][key] = value
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def _pure(name):
    return dict(AIR) if name == "AIR" else {FLUID[name]: 1.0}


# -- reference tests (the claim) ----------------------------------------------------------------


@pytest.mark.parametrize("point", REFS["air_density"]["points"], ids=lambda p: f"{p['P']}kPa")
def test_air_density_reference(adapter, point):
    got = adapter.flash(Inputs(point["T"], point["P"], AIR))
    assert got.phase == "vapor"
    assert got.density == pytest.approx(point["rho"], rel=REFS["air_density"]["tolerance_rel"])


@pytest.mark.parametrize("point", REFS["gas_density"]["points"], ids=lambda p: p["fluid"])
def test_gas_density_reference(adapter, point):
    got = adapter.flash(Inputs(point["T"], point["P"], _pure(point["fluid"])))
    assert got.density == pytest.approx(point["rho"], rel=REFS["gas_density"]["tolerance_rel"])


@pytest.mark.parametrize(
    "point", REFS["saturation_temperature"]["points"], ids=lambda p: f"{p['fluid']}-{p['P']}"
)
def test_saturation_temperature_reference(adapter, point):
    got = adapter.saturation_temperature(point["P"], _pure(point["fluid"]))
    tol = REFS["saturation_temperature"]["tolerance_abs"]
    assert got == pytest.approx(point["T"], abs=tol)
    # and the flash puts the phase on the right side of it (inside the claimed range)
    if point["T"] - 1.0 >= VALIDATED.temperature[0]:
        below = adapter.flash(Inputs(point["T"] - 1.0, point["P"], _pure(point["fluid"])))
        assert below.phase == "liquid"
    assert adapter.flash(Inputs(point["T"] + 1.0, point["P"], _pure(point["fluid"]))).phase == (
        "vapor"
    )


@pytest.mark.parametrize(
    "point", REFS["liquid_density"]["points"], ids=lambda p: f"{p['fluid']}-{p['P']}"
)
def test_liquid_density_reference(adapter, point):
    # 0.3 K below saturation (the claimed Tsat accuracy), so PR sees a liquid; the saturated
    # liquid density changes by about 0.1 % over those 0.3 K.
    sub = REFS["saturation_temperature"]["tolerance_abs"]
    got = adapter.flash(Inputs(point["T"] - sub, point["P"], _pure(point["fluid"])))
    assert got.phase == "liquid"
    tol = REFS["liquid_density"]["tolerance_rel"]
    assert got.density == pytest.approx(point["rho"], rel=tol)


@pytest.mark.parametrize("point", REFS["two_phase"]["points"], ids=lambda p: f"{p['P']}kPa")
def test_two_phase_reference(adapter, point):
    refs = REFS["two_phase"]
    zs = {"N2": point["x_N2"], "O2": 1 - point["x_N2"]}
    bubble = adapter.saturation_temperature(point["P"], zs, 0.0)
    dew = adapter.saturation_temperature(point["P"], zs, 1.0)
    assert bubble == pytest.approx(point["bubble"], abs=refs["tolerance_T_abs"])
    assert dew == pytest.approx(point["dew"], abs=refs["tolerance_T_abs"])
    got = adapter.flash(Inputs(point["T_mid"], point["P"], zs))
    assert got.phase == "two-phase" and got.density is None
    assert got.vapor_fraction == pytest.approx(point["vf"], abs=refs["tolerance_vf_abs"])


def test_k_values_of_a_component_absent_from_a_sharp_split(adapter):
    # the dew point of a nitrogen product with no argon: argon's K is the infinite-dilution
    # ratio phi_liquid / phi_vapour of the same Peng-Robinson states (formerly refused as "no
    # liquid AR at the bubble point")
    xd = {"N2": 0.9999, "O2": 0.0001, "AR": 0.0}
    t, k = adapter.k_values(540.0, xd, 1.0)
    assert 94.0 < t < 97.0  # N2 at 5.4 bar dews near 95.6 K
    assert set(k) == {"N2", "O2", "AR"}
    # argon lies between oxygen and nitrogen in volatility; the trace limit of a small argon
    # fraction gives the same ratio
    assert k["O2"] < k["AR"] < k["N2"]
    _, k_trace = adapter.k_values(540.0, {"N2": 0.9999 - 1e-7, "O2": 0.0001, "AR": 1e-7}, 1.0)
    assert k["AR"] == pytest.approx(k_trace["AR"], rel=1e-4)
    # the bubble point of an oxygen product with no nitrogen
    _, kb = adapter.k_values(140.0, {"N2": 0.0, "O2": 0.99, "AR": 0.01}, 0.0)
    assert kb["N2"] > kb["AR"] > kb["O2"]


def test_claimed_range_is_what_the_references_cover():
    covered_T = [p["T"] for group in REFS.values() for p in group.get("points", []) if "T" in p]
    covered_P = [p["P"] for group in REFS.values() for p in group.get("points", [])]
    lo, hi = VALIDATED.temperature
    assert lo >= 77.0 - 0.5 and hi <= max(covered_T) + 2.0
    plo, phi = VALIDATED.pressure
    assert plo >= 100.0 and phi <= max(covered_P) * 1.05
    vlo, vhi = VALIDATED.vle_pressure
    liquid_P = [p["P"] for p in REFS["liquid_density"]["points"]]
    assert vhi <= max(liquid_P) * 1.1 and vlo >= 100.0


# -- refusals -----------------------------------------------------------------------------------


def test_out_of_range_and_unsupported_are_refused(adapter):
    with pytest.raises(Unsupported) as hot:
        adapter.flash(Inputs(500.0, 101.325, AIR))
    assert hot.value.rule == "property-out-of-range"
    with pytest.raises(Unsupported) as high:
        adapter.flash(Inputs(100.0, 2000.0, _pure("N2")))  # liquid N2 above the VLE claim
    assert high.value.rule == "property-out-of-range"
    with pytest.raises(Unsupported) as co2:
        adapter.flash(Inputs(293.15, 101.325, {**AIR, "CO2": 0.0004}))
    assert co2.value.rule == "property-unsupported" and "CO2" in str(co2.value)
    with pytest.raises(Unsupported) as solid:
        adapter.flash(Inputs(80.0, 101.325, {"AR": 1.0}))  # below argon's triple point
    assert solid.value.rule == "property-unsupported" and "melting" in str(solid.value)


def test_non_positive_pressure_is_refused_and_not_written(plant):
    _edit_state(plant, "S1", "pressure", {"value": 0, "provenance": "given"})
    result = _fill(plant)
    found = [f for f in result.findings if "S1" in f.ids]
    assert found and found[0].rule == "cheme.process-property-unsupported"
    assert "not positive" in found[0].message
    assert "calculated" not in _state(plant, "S1")


def test_unsupported_mixture_is_refused(tmp_path):
    shutil.copytree(EXAMPLES / "process-blocks", tmp_path / "blocks")
    ws = Workspace(tmp_path / "blocks")
    before = (ws.root / "process/flowsheet.yaml").read_text()
    result = _fill(ws)
    rules_found = {f.rule for f in result.findings}
    assert "cheme.process-property-unsupported" in rules_found
    assert (ws.root / "process/flowsheet.yaml").read_text() == before


# -- fill, check, stale -------------------------------------------------------------------------


def test_fill_writes_values_method_versions_and_fingerprints(plant):
    result = _fill(plant)
    assert not [f for f in result.findings if f.level == "error"]
    s1 = _state(plant, "S1")
    assert s1["phase"]["value"] == "vapor" and s1["phase"]["provenance"] == "calculated"
    calc = s1["calculated"]
    assert calc["density"]["value"] == pytest.approx(1.2046, rel=0.005)
    assert calc["density"]["unit"] == "kg/m3" and calc["density"]["provenance"] == "calculated"
    assert {q["origin"] for q in calc.values()} == {"correlation"}
    assert "origin" not in s1["phase"]
    assert calc["molar_mass"]["value"] == pytest.approx(28.96, rel=0.002)
    assert "enthalpy" in calc and len(calc["density"]["fingerprint"]) == 16
    s3 = _state(plant, "S3")
    assert s3["phase"]["value"] == "two-phase" and 0 < s3["phase"]["vapor_fraction"] < 1
    assert "density" not in s3["calculated"]
    text = (plant.root / "process/flowsheet.yaml").read_text()
    assert "# ambient air" in text and "comments must survive" in text
    method = yaml.safe_load((plant.root / "process/materials.yaml").read_text())
    method = method["property_method"]
    assert method["status"] == "configured" and method["versions"]["thermo"] == "0.6.1"
    assert "ChemSep" in method["binary_interaction"] and method["eos"]
    assert method["application_range"]["vle_pressure"] == [100.0, 600.0]
    process, found = load(plant.root)
    assert not [f for f in found + rules(process) if f.rule.endswith("calculated-stale")]
    # a second fill changes nothing
    first = (plant.root / "process/flowsheet.yaml").read_text()
    assert _fill(plant).written == 0
    assert (plant.root / "process/flowsheet.yaml").read_text() == first
    assert not [f for f in _fill(plant, write=False).findings if f.level != "info"]


def test_fill_never_overwrites_given_or_assumed(plant):
    result = _fill(plant)
    s2 = _state(plant, "S2")
    assert s2["phase"] == {"value": "liquid", "provenance": "given", "source": "LOX product"}
    assert s2["calculated"]["density"] == {
        "value": 1130,
        "unit": "kg/m3",
        "provenance": "given",
        "source": "vendor",
    }
    assert s2["calculated"]["molar_mass"]["provenance"] == "calculated"
    assert any("S2 density: given value kept" in line for line in result.lines)


def test_a_phase_contradicting_the_inputs_writes_nothing(plant):
    # LOX at 95 K and 130 kPa is 2.4 K above its saturation temperature (92.6 K): vapour; the
    # liquid root is metastable far beyond the tolerance
    _edit_state(plant, "S2", "temperature", {"value": 95.0, "provenance": "assumed"})
    result = _fill(plant)
    found = [f for f in result.findings if f.rule == "cheme.process-property-metastable"]
    assert found and "S2" in found[0].ids and "nothing written" in found[0].message
    assert "metastable beyond the tolerance" in found[0].message
    assert "S2" in result.refused
    assert "molar_mass" not in _state(plant, "S2")["calculated"]


def test_a_given_two_phase_the_flash_contradicts_writes_nothing(plant):
    _edit_state(plant, "S2", "phase", {"value": "two-phase", "provenance": "assumed"})
    result = _fill(plant)
    found = [f for f in result.findings if f.rule == "cheme.process-property-phase"]
    assert found and "S2" in found[0].ids and "nothing written" in found[0].message


# -- phase-constrained flash (pre-release issue 97) ------------------------------------------------

N2 = {"N2": 1.0}
LOX = {"O2": 0.995, "AR": 0.005}


def test_near_saturation_nitrogen_vapour_on_its_vapour_root(adapter):
    dew = adapter.saturation_temperature(130.0, N2, 1.0)
    inputs = Inputs(dew - 0.03, 130.0, N2)
    assert adapter.flash(inputs).phase == "liquid"  # PR: 0.03 K into the liquid
    got = adapter.flash(inputs, "vapor")
    assert got.phase == "vapor" and got.constrained and got.stable_phase == "liquid"
    assert got.vapor_fraction == 1.0
    assert 0 < got.metastability < METASTABLE_TOLERANCE
    # the vapour root is continuous with the saturated vapour at the dew point
    saturated = adapter.flash(Inputs(dew + 0.03, 130.0, N2))
    assert saturated.phase == "vapor" and not saturated.constrained
    assert got.density == pytest.approx(saturated.density, rel=0.005)
    assert 4.0 < got.density < 8.0  # not the liquid's ~800 kg/m3
    assert got.enthalpy == pytest.approx(saturated.enthalpy, abs=5.0)
    assert adapter.entropy(inputs, "vapor") == pytest.approx(
        adapter.entropy(Inputs(dew + 0.03, 130.0, N2)), abs=0.1
    )
    # where the flash agrees, the constraint changes nothing
    assert adapter.flash(Inputs(dew + 1.0, 130.0, N2), "vapor") == adapter.flash(
        Inputs(dew + 1.0, 130.0, N2)
    )


def test_subcooled_liquid_is_not_constrained_and_a_vapour_there_is_metastable(adapter):
    inputs = Inputs(78.0, 130.0, N2)  # 1.4 K below the boiling point at 130 kPa
    liquid = adapter.flash(inputs, "liquid")
    assert liquid.phase == "liquid" and not liquid.constrained and liquid.density > 790
    with pytest.raises(Unsupported) as refused:
        adapter.flash(inputs, "vapor")
    assert refused.value.rule == "property-metastable"
    assert "RT above the stable liquid" in str(refused.value)


def test_no_root_beyond_the_spinodal(adapter):
    from chemeascode.domains.process.props import phase_root

    flasher, _ = adapter._flasher(("7440-37-1", "7727-37-9", "7782-44-7"))
    # nitrogen at 110 K and 30 bar(a): one real root, the liquid's
    zs = [0.0, 1.0, 0.0]
    assert phase_root(flasher, 110.0, 3.0e6, zs, "vapor") is None
    assert phase_root(flasher, 110.0, 3.0e6, zs, "liquid") is not None
    assert phase_root(flasher, 78.0, 1.3e5, zs, "vapor") is not None  # metastable, but a root


def test_fill_writes_a_near_saturation_vapour_phase_constrained(plant):
    process, _ = load(plant.root)
    dew = Adapter(process).saturation_temperature(130.0, N2, 1.0)
    _edit_state(plant, "S3", "temperature", {"value": round(dew - 0.03, 3), "provenance": "given"})
    _edit_state(
        plant, "S3", "composition", {"basis": "mole_fraction", "values": N2, "provenance": "given"}
    )
    _edit_state(plant, "S3", "phase", {"value": "vapor", "provenance": "assumed", "source": "dew"})
    result = _fill(plant)
    assert "S3" not in result.refused
    info = [f for f in result.findings if f.rule == "cheme.process-property-phase-constrained"]
    assert info and info[0].level == "info" and "S3" in info[0].ids
    s3 = _state(plant, "S3")
    assert s3["phase"] == {"value": "vapor", "provenance": "assumed", "source": "dew"}
    calc = s3["calculated"]
    assert 4.0 < calc["density"]["value"] < 8.0
    for name in ("molar_mass", "density", "enthalpy", "exergy"):
        assert calc[name]["provenance"] == "calculated"
        assert "phase-constrained vapor root (assumed phase; flash liquid" in calc[name]["source"]
    assert any("S3: vapor" in line and "phase-constrained" in line for line in result.lines)
    # current: a second fill writes nothing, validate and --check find nothing stale
    assert _fill(plant).written == 0
    process, found = load(plant.root)
    assert not [f for f in found + rules(process) if f.rule.endswith("calculated-stale")]
    assert not [f for f in _fill(plant, write=False).findings if f.level not in ("info",)]
    # the values belong to the stated phase: another stated phase makes them stale
    _edit_state(plant, "S3", "phase", {"value": "liquid", "provenance": "assumed"})
    process, found = load(plant.root)
    stale = [f for f in found + rules(process) if f.rule.endswith("calculated-stale")]
    assert stale and "S3" in stale[0].ids


def test_fill_writes_a_liquid_at_its_bubble_point_phase_constrained(plant):
    process, _ = load(plant.root)
    bubble = Adapter(process).saturation_temperature(130.0, LOX, 0.0)
    _edit_state(
        plant, "S2", "temperature", {"value": round(bubble + 0.02, 3), "provenance": "given"}
    )
    result = _fill(plant)
    assert "S2" not in result.refused
    calc = _state(plant, "S2")["calculated"]
    assert calc["density"]["provenance"] == "given"  # the vendor's value stays
    assert "phase-constrained liquid root (given phase; flash" in calc["enthalpy"]["source"]
    assert calc["enthalpy"]["value"] < -10_000  # liquid: below the vapour's ~-6,000 kJ/kmol


def test_fill_of_a_subcooled_liquid_is_not_marked(plant):
    _fill(plant)
    calc = _state(plant, "S2")["calculated"]  # LOX at 91 K, 130 kPa: subcooled
    assert "phase-constrained" not in calc["molar_mass"]["source"]
    assert "phase-constrained" not in calc["enthalpy"]["source"]


def test_changed_inputs_make_values_stale_and_refused_refill_keeps_them(plant, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app
    from chemeascode.project.validate import validate_workspace

    _fill(plant)
    old = _state(plant, "S1")["calculated"]["density"]["value"]
    _edit_state(plant, "S1", "temperature", {"value": 500.0, "provenance": "given"})
    stale = [f for f in validate_workspace(plant).findings if f.rule.endswith("calculated-stale")]
    assert stale and stale[0].level == "warning" and "S1" in stale[0].ids
    monkeypatch.chdir(plant.root)
    shown = CliRunner().invoke(app, ["process", "streams", "--md"])
    assert "STALE" in shown.output
    result = _fill(plant)  # 500 K is outside the claim: refused, old values kept and stale
    rules_found = {f.rule for f in result.findings if "S1" in f.ids}
    assert {"cheme.process-property-out-of-range", "cheme.process-calculated-stale"} <= (
        rules_found
    )
    assert _state(plant, "S1")["calculated"]["density"]["value"] == old
    check = CliRunner().invoke(app, ["process", "props", "--check"])
    assert check.exit_code == 1 and "out-of-range" in check.output


def test_check_reports_a_hand_changed_calculated_value(plant, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    _fill(plant)
    path = plant.root / "process/flowsheet.yaml"
    data = yaml.safe_load(path.read_text())
    data["streams"][0]["state"]["design"]["calculated"]["density"]["value"] = 2.0
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    monkeypatch.chdir(plant.root)
    result = CliRunner().invoke(app, ["process", "props", "--check"])
    assert result.exit_code == 1 and "recalculated" in result.output


# -- links --------------------------------------------------------------------------------------


def _lists(tmp_path):
    from chemeascode.schemas import EquipmentList, InstrumentList, LineList

    return {
        "equipment": EquipmentList.model_validate(
            {"equipment": [{"tag": "K-1101", "type": "Compressor", "sheet": "P-01"}]}
        ),
        "lines": LineList.model_validate(
            {"lines": [{"number": "100-AIR-001", "from": "K-1101", "to": "E-1", "sheet": "P-02"}]}
        ),
        "instruments": InstrumentList.model_validate({"instruments": [{"tag": "PI-1"}]}),
    }


def test_links_resolve_against_lists_and_sheet_scope(tmp_path):
    from chemeascode.domains.process.schema import Link

    lists = _lists(tmp_path)
    sheets = {"P-01", "P-02"}
    assert link_problem(Link(target="equipment", ref="K-1101"), lists, sheets) is None
    assert link_problem(Link(target="equipment", ref="K-1101", sheet="P-01"), lists, sheets) is None
    assert "not in the equipment list" in link_problem(
        Link(target="equipment", ref="K-9"), lists, sheets
    )
    assert "per its list, not P-01" in link_problem(
        Link(target="line", ref="100-AIR-001", sheet="P-01"), lists, sheets
    )
    assert "not declared" in link_problem(
        Link(target="instrument", ref="PI-1", sheet="P-09"), lists, sheets
    )
    assert link_problem(Link(target="sheet", ref="P-02"), lists, sheets) is None
    assert "not declared" in link_problem(Link(target="sheet", ref="P-03"), lists, sheets)
    assert "no valid" in link_problem(Link(target="line", ref="X"), {}, sheets)


def test_multi_target_links_are_info_until_the_gate(plant):
    from chemeascode.project.checks import run_checks

    process, _ = load(plant.root)
    found = [
        f
        for f in rules(process, _lists(None), ["P-01"])
        if f.rule == "cheme.process-link-unresolved"
    ]
    assert len(found) == 1 and found[0].level == "info"  # the line is on P-02, not P-01
    assert "100-AIR-001" in found[0].message
    (plant.root / "checks").mkdir()
    (plant.root / "checks/checks.yaml").write_text(
        "checks:\n"
        "  - {id: links-c, title: c, stage: concept, kind: process-links, level: warning}\n"
        "  - {id: links-b, title: b, stage: concept, kind: process-links}\n"
    )
    results = {r.id: r for r in run_checks(plant)}
    assert results["links-c"].status == "pass" and results["links-c"].detail.startswith("warning")
    assert results["links-b"].status == "fail" and "unresolved" in results["links-b"].detail


# -- exergy -------------------------------------------------------------------------------------


def test_chemical_exergy_table_and_mixing():
    from chemeascode.domains.process import exergy

    assert exergy.standard("7782-44-7") == 3970.0
    assert exergy.standard("7732-18-5", "liquid") == 900.0
    assert exergy.standard("7782-44-7", "liquid") is None
    pure, missing = exergy.chemical({"7782-44-7": 1.0})
    assert (pure, missing) == (3970.0, [])
    # air: the standard values less the mixing term, nearly the reference environment
    air, _ = exergy.chemical({"7727-37-9": 0.79, "7782-44-7": 0.21})
    rt0 = exergy.R * 298.15
    expected = 0.79 * 720 + 0.21 * 3970 + rt0 * (0.79 * math.log(0.79) + 0.21 * math.log(0.21))
    assert air == pytest.approx(expected) and 0 < air < 200
    assert exergy.chemical({"9999-99-9": 1.0}) == (None, ["9999-99-9"])


def test_exergy_of_compressed_oxygen(adapter):
    from chemeascode.domains.process import exergy
    from chemeascode.domains.process.exergy import stream_exergy
    from chemeascode.domains.process.props import Inputs

    t0, p0 = exergy.dead_state()
    value, missing = stream_exergy(adapter, Inputs(313.15, 3100.0, {"O2": 1.0}))
    # chemical 3.97 MJ/kmol plus nearly isothermal compression RT0 ln(P/P0); real gas within 1 %
    ideal = 3970.0 + exergy.R * t0 * math.log(3100.0 / p0)
    assert missing == [] and value == pytest.approx(ideal, rel=0.01)
    # at the dead state only the chemical exergy is left
    dead, _ = stream_exergy(adapter, Inputs(t0, p0, {"O2": 1.0}))
    assert dead == pytest.approx(3970.0, abs=1.0)
    # a cold liquid holds more than the gas at the same pressure
    liquid, _ = stream_exergy(adapter, Inputs(85.0, 130.0, {"O2": 1.0}))
    assert liquid > dead + 10_000


def test_fill_writes_exergy_with_its_source(plant):
    _fill(plant)
    calc = _state(plant, "S1")["calculated"]
    assert calc["exergy"]["unit"] == "kJ/kmol" and "Szargut" in calc["exergy"]["source"]
    assert 0 < calc["exergy"]["value"] < 1000  # ambient air: next to nothing
