"""The benchmark of package ``water-methanol-pcsaft-liquid`` (PC-SAFT through feos, ADR 0046).

The package as ``cheme process props`` runs it (``props_feos.FeosAdapter``) against:

- the pure fluids' reference equations of state in CoolProp 8.0.0 (IAPWS-95 for water, de Reuck
  and Craven for methanol), on a grid over every box claimed at any mole fraction;
- measured mixture densities: Coquelet et al. 2005 (283.15 to 353.15 K) and the excess volumes of
  Safarov et al. 2004 (298.15 to 523.15 K, to 60 MPa) with the reference pure-fluid volumes;
- measured bubble points (Jodecke et al. 2005, Soujanya et al. 2010) for the phase margin
  ``bubble_pressure_rel``;
- measured excess enthalpies (Dettmann et al. 2006), which show why no enthalpy is claimed.

Every measured point inside the claim must hold the tolerance; a point that fails narrows the
claim, never the tolerance. Values: tests/data/water_methanol_references.yaml (ThermoML).
"""

from pathlib import Path

import numpy as np
import pytest
import yaml

pytest.importorskip("feos")
CP = pytest.importorskip("CoolProp.CoolProp")

from chemeascode.domains.process import property_packages as packages  # noqa: E402
from chemeascode.domains.process.fill import coverage, run  # noqa: E402
from chemeascode.domains.process.model import load  # noqa: E402
from chemeascode.domains.process.property_packages import (  # noqa: E402
    METHANOL,
    WATER,
    WATER_METHANOL,
)
from chemeascode.domains.process.props import (  # noqa: E402
    Inputs,
    Unsupported,
    adapter_for,
    range_problems,
)
from chemeascode.domains.process.props_feos import BINARY, PURE, FeosAdapter  # noqa: E402
from chemeascode.foundation.workspace import Workspace  # noqa: E402

REFS = yaml.safe_load(
    (Path(__file__).parent / "data" / "water_methanol_references.yaml").read_text()
)
TOL = WATER_METHANOL.benchmark.tolerances
MARGIN = TOL["bubble_pressure_rel"]
M = WATER_METHANOL.molar_masses
FLUID = {WATER: "Water", METHANOL: "Methanol"}

MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
  - {{id: H2O, name: water, cas: 7732-18-5, molar_mass: 18.015}}
  - {{id: MEOH, name: methanol, cas: 67-56-1, molar_mass: 32.042}}
property_method:
  adapter: feos
  status: placeholder
{package}"""

FLOWSHEET = """\
schema: cheme/process/v1
kind: flowsheet
units: {{pressure: kPa(a), temperature: K, flow: kg/h, duty: kW, enthalpy: kJ/kmol,
  enthalpy_reference: {{state: ideal_gas, temperature: 298.15, pressure: 101.325}}}}
feeds:
  - {{id: IN, ports: [{ports_out}]}}
products:
  - {{id: OUT, ports: [{ports_in}]}}
streams:
{streams}"""


def _plant(root: Path, streams: dict, package: str | None = "water-methanol-pcsaft-liquid"):
    """A plant with water and methanol and *streams* {id: (T K, P kPa(a), x_meoh, phase)}."""
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: pcsaft-test\nstage: concept\n")
    (root / "process/materials.yaml").write_text(
        MATERIALS.format(package=f"  package: {package}\n" if package else "")
    )
    ports = [f"p{i}" for i in range(len(streams))]
    text = ""
    for (sid, (t, p, x, phase)), port in zip(streams.items(), ports, strict=True):
        text += (
            f"  - id: {sid}\n    from: IN.{port}\n    to: OUT.{port}\n    state:\n      design:\n"
            f"        temperature: {{value: {t}, provenance: given}}\n"
            f"        pressure: {{value: {p}, provenance: given}}\n"
            f"        composition: {{basis: mole_fraction, values: {{H2O: {1 - x:.6g}, "
            f"MEOH: {x:.6g}}}, provenance: given}}\n"
        )
        if phase:
            text += f"        phase: {{value: {phase}, provenance: assumed}}\n"
    (root / "process/flowsheet.yaml").write_text(
        FLOWSHEET.format(
            ports_out=", ".join(f"{{id: {p}, direction: out}}" for p in ports),
            ports_in=", ".join(f"{{id: {p}, direction: in}}" for p in ports),
            streams=text,
        )
    )
    return Workspace(root)


def _process(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return process


@pytest.fixture(scope="module")
def adapter(tmp_path_factory) -> FeosAdapter:
    ws = _plant(tmp_path_factory.mktemp("pcsaft") / "plant", {"S1": (300.0, 200.0, 0.5, None)})
    found = adapter_for(_process(ws))
    assert isinstance(found, FeosAdapter)
    return found


def _x(x_meoh: float) -> dict[str, float]:
    return {k: v for k, v in (("MEOH", x_meoh), ("H2O", 1.0 - x_meoh)) if v > 0}


def _liquid(adapter: FeosAdapter, t: float, p: float, x_meoh: float) -> float:
    """The package's density at *t* K, at *p* kPa(a) or, where that is within the bubble-pressure
    margin, at the pressure that clears it: a measured liquid's density changes by less than
    0.05 % over that step (compressibility about 1e-9 1/Pa)."""
    cas, x = adapter._composition(_x(x_meoh))
    bubble = adapter._model(cas).bubble_pressure(t, x) / 1000.0
    p = max(p, (1.0 + MARGIN) * bubble * 1.001)
    return adapter.flash(Inputs(t, p, _x(x_meoh))).density, p


def _claimed(adapter: FeosAdapter, t: float, p: float, x_meoh: float) -> bool:
    return not range_problems(adapter.process, Inputs(t, p, _x(x_meoh)))


# -- the registry and the data ------------------------------------------------------------------


def test_the_package_is_registered_with_its_parameter_files():
    assert packages.get("water-methanol-pcsaft-liquid") is WATER_METHANOL
    assert WATER_METHANOL.adapter == "feos" and not WATER_METHANOL.enthalpy
    assert WATER_METHANOL.liquid_only and WATER_METHANOL.validated.phases == ["liquid"]
    assert WATER_METHANOL.benchmark.test == "tests/test_property_packages_pcsaft.py"
    pure = yaml.safe_load(PURE.read_text())
    assert sorted(r["identifier"]["cas"] for r in pure) == sorted([WATER, METHANOL])
    (binary,) = yaml.safe_load(BINARY.read_text())
    assert binary["k_ij"] == pytest.approx(-0.0159473671673194)
    assert (PURE.parent / "SOURCE.md").exists() and (PURE.parent / "license-mit").exists()
    # the claim stays inside the reference equations' validity
    for cas, boxes in WATER_METHANOL.validated.component_regions.items():
        for box in boxes:
            assert box.temperature[0] >= CP.PropsSI("Tmin", FLUID[cas])
            assert box.temperature[1] <= CP.PropsSI("Tmax", FLUID[cas])
            assert box.pressure[1] * 1e3 <= CP.PropsSI("pmax", FLUID[cas])


# -- pure fluids --------------------------------------------------------------------------------


@pytest.mark.parametrize("cas", [WATER, METHANOL])
def test_pure_liquid_against_its_reference_equation_of_state(adapter, cas):
    """Every box claimed at any mole fraction, on a grid of temperatures and pressures; states
    the margin leaves undecided are refused, and nothing is claimed as liquid that the reference
    equation puts in the vapour."""
    x_meoh = 1.0 if cas == METHANOL else 0.0
    fluid = FLUID[cas]
    worst, checked = 0.0, 0
    for box in WATER_METHANOL.validated.component_regions[cas]:
        if box.max_mole_fraction is not None:
            continue
        for t in np.linspace(*box.temperature, 8):
            psat = CP.PropsSI("P", "T", t, "Q", 0, fluid) / 1000.0
            for p in np.geomspace(box.pressure[0], box.pressure[1], 7):
                inputs = Inputs(float(t), float(p), _x(x_meoh))
                try:
                    result = adapter.flash(inputs)
                except Unsupported:
                    continue
                assert p > psat, (t, p)
                ref = CP.PropsSI("Dmass", "T", t, "P", p * 1000.0, fluid)
                worst = max(worst, abs(result.density / ref - 1.0))
                checked += 1
    assert checked >= 40
    assert worst <= TOL["density_rel_pure"], worst


# -- mixtures, measured -------------------------------------------------------------------------


def test_mixture_densities_against_coquelet_2005(adapter):
    worst, claimed = 0.0, 0
    for t, x_water, density in REFS["coquelet2005"]["values"]:
        x_meoh = 1.0 - x_water
        if not _claimed(adapter, t, 101.325, x_meoh):
            continue
        calc, _ = _liquid(adapter, t, 101.325, x_meoh)
        worst = max(worst, abs(calc / density - 1.0))
        claimed += 1
    assert claimed >= 110  # of 180
    assert worst <= TOL["density_rel"], worst


def test_mixture_densities_against_safarov_2004(adapter):
    """The measured excess volume with the reference equations' pure-fluid volumes."""
    worst, claimed = 0.0, 0
    for t, p, x_meoh, excess in REFS["safarov2004"]["values"]:
        if not _claimed(adapter, t, p, x_meoh):
            continue
        volume = (
            x_meoh / CP.PropsSI("Dmolar", "T", t, "P", p * 1000.0, "Methanol")
            + (1 - x_meoh) / CP.PropsSI("Dmolar", "T", t, "P", p * 1000.0, "Water")
            + excess
        )
        ref = (x_meoh * M[METHANOL] + (1 - x_meoh) * M[WATER]) / 1000.0 / volume
        calc, _ = _liquid(adapter, t, p, x_meoh)
        worst = max(worst, abs(calc / ref - 1.0))
        claimed += 1
    assert claimed >= 90
    assert worst <= TOL["density_rel"], worst


def test_the_claim_stops_where_the_measured_densities_fail(adapter):
    """Cold water-rich liquid and hot mixtures miss by more than the tolerance: unclaimed."""
    measured = {(t, x): d for t, x, d in REFS["coquelet2005"]["values"]}
    x_w = max(x for t, x in measured if t == 283.15)  # the most water-rich point
    cas, x = adapter._composition(_x(1.0 - x_w))
    cold = (
        adapter._model(cas).liquid_density(283.15, 101325.0, x)
        * 1e-3
        * (x[0] * M[METHANOL] + x[1] * M[WATER])
    )
    assert abs(cold / measured[(283.15, x_w)] - 1.0) > TOL["density_rel"]
    assert not _claimed(adapter, 283.15, 101.325, 1.0 - x_w)
    assert not _claimed(adapter, 448.15, 5000.0, 0.5)  # Safarov: +1.4 %
    assert not _claimed(adapter, 300.0, 200.0, 0.0)  # pure water below 360 K: +3 %
    assert _claimed(adapter, 300.0, 200.0, 0.5) and _claimed(adapter, 380.0, 500.0, 0.0)


# -- phase ----------------------------------------------------------------------------------------


def test_the_bubble_margin_covers_the_measured_bubble_points(adapter):
    """PC-SAFT's bubble pressure against every measured one, either way: the margin within
    which the adapter does not decide the phase on its own."""
    points = [(t, x, p) for t, x, p in REFS["jodecke2005"]["values"]]
    points += [(t, x, p) for x, p, t in REFS["soujanya2010"]["values"]]
    worst = 0.0
    for t, x_meoh, p in points:
        cas, x = adapter._composition(_x(x_meoh))
        calc = adapter._model(cas).bubble_pressure(t, x) / 1000.0
        worst = max(worst, calc / p - 1.0, p / calc - 1.0)
    assert len(points) == 66
    assert MARGIN / 2 < worst <= MARGIN, worst


def test_the_package_claims_liquid_only(adapter):
    x, t = _x(0.5), 375.0
    cas, xs = adapter._composition(x)
    bubble = adapter._model(cas).bubble_pressure(t, xs) / 1000.0
    assert 0.7 * bubble > 100.0  # every state below inside the claimed pressures
    assert adapter.flash(Inputs(t, 1.3 * bubble, x)).phase == "liquid"
    with pytest.raises(Unsupported) as close:  # inside the margin, no phase given
        adapter.flash(Inputs(t, 1.1 * bubble, x))
    assert "liquid is not established" in str(close.value)
    with pytest.raises(Unsupported) as below:
        adapter.flash(Inputs(t, 0.9 * bubble, x))
    assert "vapour or two-phase" in str(below.value)
    # a liquid given or assumed: its root, phase-constrained below the bubble pressure
    given = adapter.flash(Inputs(t, 0.9 * bubble, x), "liquid")
    assert given.phase == "liquid" and given.stable_phase == "two-phase"
    assert 0.0 < given.metastability < 0.05
    assert adapter.flash(Inputs(t, 1.1 * bubble, x), "liquid").stable_phase is None
    with pytest.raises(Unsupported) as far:
        adapter.flash(Inputs(t, 0.7 * bubble, x), "liquid")
    assert far.value.rule == "property-phase"
    with pytest.raises(Unsupported):
        adapter.flash(Inputs(t, 1.3 * bubble, x), "vapor")


def test_nothing_but_density_is_claimed(adapter):
    result = adapter.flash(Inputs(300.0, 200.0, _x(0.5)))
    assert result.enthalpy is None and 850.0 < result.density < 950.0
    for call in (
        lambda: adapter.entropy(Inputs(300.0, 200.0, _x(0.5))),
        lambda: adapter.heat_capacity_ratio(Inputs(300.0, 200.0, _x(0.5))),
        lambda: adapter.k_values(101.325, _x(0.5)),
        lambda: adapter.bubble_pressure(330.0, _x(0.5)),
        lambda: adapter.liquid_viscosity(300.0, _x(0.5)),
        lambda: adapter.flash_ph(200.0, -40000.0, _x(0.5)),
    ):
        with pytest.raises(Unsupported) as refused:
            call()
        assert "claims liquid density only" in str(refused.value)


def test_the_excess_enthalpy_is_why_no_enthalpy_is_claimed():
    """PC-SAFT's excess enthalpy against Dettmann et al. 2006 where both pure fluids are liquid:
    the wrong sign below about 420 K, misses far beyond the 0.3 kJ/mol the syngas package
    claims enthalpy differences to."""
    import feos
    import si_units as si

    def h_res(cas, t, p, x):
        parameters = feos.Parameters.from_json(
            cas, str(PURE), str(BINARY) if len(cas) > 1 else None,
            identifier_option=feos.IdentifierOption.Cas,
        )  # fmt: skip
        state = feos.State(
            feos.EquationOfState.pcsaft(parameters),
            temperature=t * si.KELVIN,
            pressure=p * 1000.0 * si.PASCAL,
            composition=np.asarray(x),
            density_initialization="liquid",
        )
        return state.molar_enthalpy(feos.Contributions.Residual) / (si.KILO * si.JOULE / si.MOL)

    misses, wrong_sign = [], 0
    for t, p, x_meoh, measured in REFS["dettmann2006"]["values"]:
        if t > 370.0 or p < 2000.0:
            continue
        calc = (
            h_res([METHANOL, WATER], t, p, [x_meoh, 1 - x_meoh])
            - x_meoh * h_res([METHANOL], t, p, [1.0])
            - (1 - x_meoh) * h_res([WATER], t, p, [1.0])
        )
        misses.append(abs(calc - measured))
        wrong_sign += measured < 0 < calc
    assert len(misses) >= 50
    assert max(misses) > 1.0 and wrong_sign >= len(misses) // 2


# -- props --fill ---------------------------------------------------------------------------------


def test_fill_writes_density_only_and_records_the_package(tmp_path):
    ws = _plant(
        tmp_path / "a",
        {
            "CRUDE": (300.0, 200.0, 0.5, None),  # methanol-water liquid
            "COLD": (300.0, 200.0, 0.05, None),  # water-rich below 323 K: not claimed
            "HOT": (400.0, 101.325, 0.5, None),  # vapour
            "SAT": (337.0, 101.325, 0.95, "liquid"),  # near its bubble point, liquid assumed
        },
    )
    result = run(ws, _process(ws), "design", write=True)
    assert sorted(result.refused) == ["COLD", "HOT"]
    assert "enthalpy not calculated: package water-methanol-pcsaft-liquid claims no enthalpy" in (
        result.lines
    )
    streams = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())["streams"]
    crude = streams[0]["state"]["design"]
    assert crude["phase"]["value"] == "liquid"
    assert set(crude["calculated"]) == {"molar_mass", "density"}
    assert (
        "feos 0.10.5, PC-SAFT, package water-methanol-pcsaft-liquid"
        in (crude["calculated"]["density"]["source"])
    )
    sat = streams[3]["state"]["design"]
    assert sat["phase"]["value"] == "liquid" and "density" in sat["calculated"]
    method = yaml.safe_load((ws.root / "process/materials.yaml").read_text())["property_method"]
    assert method["adapter"] == "feos" and method["package"] == "water-methanol-pcsaft-liquid"
    assert set(method["versions"]) == {"feos", "si-units"}
    assert method["application_range"]["phases"] == ["liquid"]
    assert result.adapter.solver.name == "feos"
    # a second fill changes nothing
    first = (ws.root / "process/flowsheet.yaml").read_text()
    assert run(ws, _process(ws), "design", write=True).written == 0
    assert (ws.root / "process/flowsheet.yaml").read_text() == first


def test_water_methanol_streams_route_to_the_package(tmp_path):
    ws = _plant(tmp_path / "a", {"S1": (300.0, 200.0, 0.5, None)}, package=None)
    listed = coverage(_process(ws), "design")
    assert listed.coverage["package"] == "water-methanol-pcsaft-liquid"
    assert listed.coverage["streams"][0]["status"] == "covered"


def test_without_feos_the_message_names_the_extra(tmp_path, monkeypatch):
    from chemeascode.integrations import feos as integration

    monkeypatch.setattr(integration, "installed", lambda: False)
    ws = _plant(tmp_path / "a", {"S1": (300.0, 200.0, 0.5, None)})
    result = run(ws, _process(ws), "design", write=True)
    assert [f.rule for f in result.findings] == ["cheme.process-property-unsupported"]
    assert "saft extra" in result.findings[0].message
    assert "cheme-as-code[saft]" in result.findings[0].hint
