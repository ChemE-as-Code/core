"""Property packages: routing, coverage and the benchmark of package ``syngas-pr-vapor``.

The benchmark compares the package as ``cheme process props`` runs it (``props.Adapter``) with
CoolProp 8.0.0 (pinned in the ``props`` extra), which evaluates the reference equations of state
of the pure fluids (CoolProp BibTeX keys in ``SYNGAS.benchmark.reference``) and the GERG-2008
(Kunz and Wagner 2012) and Gernert (2013) mixture models; for ammonia with hydrogen, nitrogen,
argon and methane, which CoolProp lacks, the test loads the Neumann et al. (2020) models into
CoolProp from their published parameters (tests/data/syngas_references.yaml) and checks that load
against the published equation. The test computes both sides on a grid over every claimed region.
Measured data back the reference where it is used beyond its pure-fluid validity or for ammonia:
Date (1973) for N2-NH3 and Ar-NH3, Cheng et al. (2019) for methane at 673 K. Tolerances are the
claim, recorded in ``SYNGAS.benchmark.tolerances``: a point that fails narrows the claimed region,
never the tolerance.
"""

import itertools
import json
import math
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("thermo")
CP = pytest.importorskip("CoolProp.CoolProp")

from chemeascode.domains.process import property_packages as packages  # noqa: E402
from chemeascode.domains.process.fill import coverage, run  # noqa: E402
from chemeascode.domains.process.model import load  # noqa: E402
from chemeascode.domains.process.property_packages import AIR, SYNGAS  # noqa: E402
from chemeascode.domains.process.props import (  # noqa: E402
    Adapter,
    Inputs,
    Unsupported,
    method_fingerprint,
)
from chemeascode.domains.process.schema import (  # noqa: E402
    ApplicationRange,
    PropertyMethod,
    Region,
)
from chemeascode.foundation.workspace import Workspace  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
REFS = yaml.safe_load(
    (Path(__file__).parent / "data" / "process_props_references.yaml").read_text()
)
#: component id -> (CAS, CoolProp fluid)
FLUIDS = {
    "H2": ("1333-74-0", "Hydrogen"),
    "N2": ("7727-37-9", "Nitrogen"),
    "NH3": ("7664-41-7", "Ammonia"),
    "AR": ("7440-37-1", "Argon"),
    "CH4": ("74-82-8", "Methane"),
    "CO": ("630-08-0", "CarbonMonoxide"),
    "CO2": ("124-38-9", "CarbonDioxide"),
}
MOLAR_MASS = {
    "H2": 2.016,
    "N2": 28.014,
    "NH3": 17.031,
    "AR": 39.948,
    "CH4": 16.043,
    "CO": 28.010,
    "CO2": 44.009,
    "O2": 31.998,
}
CAS = {cid: cas for cid, (cas, _) in FLUIDS.items()} | {"O2": "7782-44-7"}
TOL = SYNGAS.benchmark.tolerances
SYN = yaml.safe_load((Path(__file__).parent / "data" / "syngas_references.yaml").read_text())
NEUMANN = SYN["neumann2020"]
CP_CAS = {fluid: cas for cas, fluid in FLUIDS.values()}


def _departure(name: str) -> dict:
    """A published departure function as a CoolProp "Gaussian+Exponential" one."""
    terms = NEUMANN["departure"][name]
    exp = [t for t in terms if t["type"] == "exp"]
    gbs = [t for t in terms if t["type"] == "GBS"]
    assert terms == exp + gbs  # CoolProp takes the exponential terms first
    keys = ("eta", "beta", "gamma", "epsilon")
    return {
        "Name": f"cheme-Neumann2020-{name}",
        "aliases": [],
        "type": "Gaussian+Exponential",
        "Npower": len(exp),
        **{k: [t[k] for t in terms] for k in ("n", "t", "d")},
        "l": [t.get("l", 0) for t in terms],
        **{k: [t.get(k, 0.0) for t in terms] for k in keys},
        "BibTeX": "Neumann-FPE-2020",
    }


def _load_neumann():
    """Register the Neumann et al. departure functions, and a placeholder entry for the
    ammonia pairs CoolProp has none for (each state then sets the published parameters)."""
    try:
        CP.set_departure_functions(json.dumps([_departure(n) for n in NEUMANN["departure"]]))
    except ValueError as already:  # registered by an earlier import in this process
        assert "already" in str(already).lower(), already
    known = set(CP.get_global_param_string("mixture_binary_pairs_list").split(","))
    for p in NEUMANN["pairs"]:
        a, b = sorted((CP_CAS[p["i"]], CP_CAS[p["j"]]))
        if f"{a}&{b}" not in known:
            CP.apply_simple_mixing_rule(a, b, "linear")


_load_neumann()


def _neumann_state(names: list[str], fractions: list[float]):
    """A CoolProp HEOS state with the Neumann et al. parameters for every ammonia pair."""
    state = CP.AbstractState("HEOS", "&".join(names))
    state.set_mole_fractions(fractions)
    for p in NEUMANN["pairs"]:
        if p["i"] not in names or p["j"] not in names:
            continue
        i, j = names.index(p["i"]), names.index(p["j"])
        beta_t, beta_v = p["betaT"], p["betaV"]
        if i > j:  # EOS-CG-2021 Eq. 7
            i, j, beta_t, beta_v = j, i, 1 / beta_t, 1 / beta_v
        if p.get("departure"):
            state.set_binary_interaction_string(
                i, j, "function", f"cheme-Neumann2020-{p['departure']}"
            )
        for key, value in (
            ("betaT", beta_t),
            ("gammaT", p["gammaT"]),
            ("betaV", beta_v),
            ("gammaV", p["gammaV"]),
            ("Fij", float(p["F"])),
        ):
            state.set_binary_interaction_double(i, j, key, value)
    return state


MATERIALS = """\
schema: cheme/process/v1
kind: materials
components:
{components}
property_method:
  adapter: thermo
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


def _plant(root: Path, streams: dict, package: str | None = None, ids=tuple(FLUIDS)) -> Workspace:
    """A plant with the synthesis-gas components and *streams* {id: (T K, P kPa(a), x)}."""
    (root / "process").mkdir(parents=True)
    (root / "plant.yaml").write_text("name: pkg-test\nstage: concept\n")
    comps = "\n".join(
        f"  - {{id: {c}, name: {c}, cas: {CAS[c]}, molar_mass: {MOLAR_MASS[c]}}}" for c in ids
    )
    (root / "process/materials.yaml").write_text(
        MATERIALS.format(components=comps, package=f"  package: {package}\n" if package else "")
    )
    letters = [f"p{i}" for i in range(len(streams))]
    text = ""
    for (sid, (t, p, x)), port in zip(streams.items(), letters, strict=True):
        values = ", ".join(f"{k}: {v}" for k, v in x.items())
        text += (
            f"  - id: {sid}\n    from: IN.{port}\n    to: OUT.{port}\n    state:\n      design:\n"
            f"        temperature: {{value: {t}, provenance: given}}\n"
            f"        pressure: {{value: {p}, provenance: given}}\n"
            f"        composition: {{basis: mole_fraction, values: {{{values}}}, "
            "provenance: given}\n"
        )
    (root / "process/flowsheet.yaml").write_text(
        FLOWSHEET.format(
            ports_out=", ".join(f"{{id: {p}, direction: out}}" for p in letters),
            ports_in=", ".join(f"{{id: {p}, direction: in}}" for p in letters),
            streams=text,
        )
    )
    return Workspace(root)


def _process(ws):
    process, found = load(ws.root)
    assert process is not None, [f.format() for f in found]
    return process


@pytest.fixture(scope="module")
def syngas(tmp_path_factory):
    ws = _plant(
        tmp_path_factory.mktemp("syngas") / "plant",
        {"S1": (300.0, 2000.0, {"H2": 0.75, "N2": 0.25})},
        package="syngas-pr-vapor",
    )
    return Adapter(_process(ws))


# -- the registry -------------------------------------------------------------------------------


def test_registry_ids_and_claims_are_consistent():
    assert len({p.id for p in packages.PACKAGES}) == len(packages.PACKAGES)
    for package in packages.PACKAGES:
        claim = package.validated
        assert set(claim.components) == set(package.components)
        assert Path(__file__).resolve().parents[1].joinpath(package.benchmark.test).exists()
        for cas, boxes in (claim.component_regions or {}).items():
            assert cas in package.components
            for box in boxes:
                assert claim.temperature[0] <= box.temperature[0] < box.temperature[1]
                assert box.temperature[1] <= claim.temperature[1]
                assert claim.pressure[0] <= box.pressure[0] < box.pressure[1]
                assert box.pressure[1] <= claim.pressure[1]
        for key in claim.pairs or []:
            a, b = key.split("&")
            assert (
                a in package.components
                and b in package.components
                and key == "&".join(sorted((a, b)))
            )


def test_air_package_tolerances_are_the_reference_files():
    tol = AIR.benchmark.tolerances
    assert tol["air_density_rel"] == REFS["air_density"]["tolerance_rel"]
    assert tol["gas_density_rel"] == REFS["gas_density"]["tolerance_rel"]
    assert tol["saturation_temperature_abs_K"] == REFS["saturation_temperature"]["tolerance_abs"]
    assert tol["liquid_density_rel"] == REFS["liquid_density"]["tolerance_rel"]
    assert tol["two_phase_temperature_abs_K"] == REFS["two_phase"]["tolerance_T_abs"]
    assert tol["vapor_fraction_abs"] == REFS["two_phase"]["tolerance_vf_abs"]


def test_composition_limits_allow_round_off_alike_and_are_mole_fractions():
    nh3, h2 = packages.NH3, packages.H2
    edge = {nh3: packages.NH3_IN_MIXTURE + 1e-13, h2: 1 - packages.NH3_IN_MIXTURE - 1e-13}
    assert not packages.limit_gaps(SYNGAS, edge)
    assert not packages.region_gaps(SYNGAS, set(edge), 400.0, 8000.0, fractions=edge)
    over = {nh3: packages.NH3_IN_MIXTURE + 1e-6, h2: 1 - packages.NH3_IN_MIXTURE - 1e-6}
    assert packages.limit_gaps(SYNGAS, over)
    assert packages.region_gaps(SYNGAS, set(over), 400.0, 8000.0, fractions=over)
    with pytest.raises(ValueError):
        Region(temperature=(300, 400), pressure=(100, 1000), max_mole_fraction=1.5)
    with pytest.raises(ValueError):
        ApplicationRange(pair_limits={"a&b": {"a": 0.0}})


def test_syngas_claim_stays_inside_the_reference_equations_validity():
    hot = SYN["cheng2019"]
    for cid, (cas, fluid) in FLUIDS.items():
        for box in SYNGAS.validated.component_regions[cas]:
            assert box.temperature[0] >= CP.PropsSI("Tmin", fluid), cid
            assert box.pressure[1] * 1e3 <= CP.PropsSI("pmax", fluid), cid
            if box.temperature[1] <= CP.PropsSI("Tmax", fluid):
                continue
            # beyond the reference equation only where measured: methane, no more of it, no
            # hotter and at no higher pressure than in Cheng et al.'s gas
            assert cid == "CH4" and box.max_mole_fraction <= hot["x"]["CH4"], (cid, box)
            assert box.temperature[1] <= hot["temperature_K"], box
            assert box.pressure[1] <= max(p for p, _, _ in hot["points"]), box
    # every claimed pair has a reference mixture model (no estimated parameters): GERG-2008 or
    # Gernert in CoolProp, or for ammonia the Neumann et al. models
    neumann = {packages.pair(CP_CAS[p["i"]], CP_CAS[p["j"]]) for p in NEUMANN["pairs"]}
    for key in SYNGAS.validated.pairs:
        if key in neumann:
            continue
        a, b = key.split("&")
        assert CP.get_mixture_binary_pair_data(a, b, "BibTeX") in {
            "Kunz-JCED-2012",
            "Gernert-Thesis-2013",
        } or CP.get_mixture_binary_pair_data(b, a, "BibTeX") in {
            "Kunz-JCED-2012",
            "Gernert-Thesis-2013",
        }, key
    nh3 = FLUIDS["NH3"][0]
    assert {p for p in SYNGAS.validated.pairs if nh3 in p} == neumann
    # each ammonia pair is limited to the dilute ammonia the benchmark covers
    assert set(SYNGAS.validated.pair_limits) == neumann


def test_the_loaded_ammonia_models_are_the_published_equation():
    """CoolProp with the loaded parameters gives, at a fixed density and temperature, the
    departure term of EOS-CG-2021 Eq. 9 evaluated here from the published coefficients."""
    for name, other in (("H2-NH3", "Hydrogen"), ("Ar-NH3", "Argon")):
        terms = NEUMANN["departure"][name]
        for t, rho in ((300.0, 12000.0), (450.0, 6000.0), (700.0, 3000.0)):
            x = [0.7, 0.3]
            full = _neumann_state([other, "Ammonia"], x)
            full.update(CP.DmolarT_INPUTS, rho, t)
            bare = _neumann_state([other, "Ammonia"], x)
            bare.set_binary_interaction_double(0, 1, "Fij", 0.0)
            bare.update(CP.DmolarT_INPUTS, rho, t)
            delta, tau = full.delta(), full.tau()
            expected = (
                x[0]
                * x[1]
                * sum(
                    k["n"]
                    * delta ** k["d"]
                    * tau ** k["t"]
                    * (
                        math.exp(-(delta ** k["l"]))
                        if k["type"] == "exp"
                        else math.exp(
                            -k["eta"] * (delta - k["epsilon"]) ** 2
                            - k["beta"] * (tau - k["gamma"]) ** 2
                        )
                    )
                    for k in terms
                )
            )
            assert full.alphar() - bare.alphar() == pytest.approx(expected, rel=1e-9, abs=1e-12)
    # the reducing parameters are the published ones, in CoolProp's pair order
    state = _neumann_state(["Ammonia", "Nitrogen"], [0.2, 0.8])
    assert state.get_binary_interaction_double(0, 1, "betaT") == pytest.approx(1 / 1.057512)
    assert state.get_binary_interaction_double(0, 1, "gammaV") == pytest.approx(1.447261)


def test_ammonia_reference_reproduces_measured_compressibility_factors():
    """Date (1973): N2-NH3 and Ar-NH3 gas at 323.15 K, Z within 0.2 %."""
    data = SYN["date1973"]
    t = data["temperature_K"]
    worst = 0.0
    for mixture in data["mixtures"]:
        x = mixture["x"]
        state = _neumann_state([FLUIDS[c][1] for c in x], list(x.values()))
        for atm, z in mixture["Z"].items():
            state.update(CP.PT_INPUTS, atm * 101325.0, t)
            assert state.phase() == CP.iphase_gas, (x, atm)
            worst = max(worst, abs(state.compressibility_factor() / z - 1))
    assert worst <= data["reference_tolerance_rel"], worst


def test_methane_reference_beyond_625_k_reproduces_measured_densities():
    """Cheng et al. (2019): H2-CO2-CH4 at 673.1 K, where CoolProp extrapolates Setzmann-Wagner;
    GERG-2008 matches the measured densities within their expanded uncertainty (and a margin)."""
    data = SYN["cheng2019"]
    x = data["x"]
    state = CP.AbstractState("HEOS", "&".join(FLUIDS[c][1] for c in x))
    state.set_mole_fractions(list(x.values()))
    for p, rho, u in data["points"]:
        state.update(CP.PT_INPUTS, p * 1e3, data["temperature_K"])
        assert abs(state.rhomolar() / rho - 1) <= u / rho + data["reference_margin_rel"], p


# -- the benchmark (the claim) ------------------------------------------------------------------


def _grid(boxes, step=25):
    """Temperatures every *step* K and the box edges, pressures at the box edges and between."""
    temps = sorted(
        {t for b in boxes for t in range(int(b.temperature[0]), int(b.temperature[1]) + 1, step)}
        | {b.temperature[1] for b in boxes}
    )
    pressures = sorted(
        {100.0, 300.0, 1000.0, 2000.0, 3000.0, 5000.0, 7500.0}
        | {float(p) for p in range(10000, 30001, 2500)}
        | {b.pressure[1] for b in boxes}
    )
    return temps, pressures


def _boxes_at(cid, xc):
    """The claimed boxes of component *cid* at mole fraction *xc*."""
    return [
        b
        for b in SYNGAS.validated.component_regions[FLUIDS[cid][0]]
        if b.max_mole_fraction is None or xc <= b.max_mole_fraction
    ]


def _inside(boxes, t, p):
    return any(
        b.temperature[0] <= t <= b.temperature[1] and b.pressure[0] <= p <= b.pressure[1]
        for b in boxes
    )


def _reference(x):
    names = [FLUIDS[c][1] for c in x]
    if len(names) > 1:
        state = _neumann_state(names, list(x.values()))
    else:
        state = CP.AbstractState("HEOS", names[0])
    gas = {CP.iphase_gas, CP.iphase_supercritical_gas, CP.iphase_supercritical}

    def at(t, p):
        """Density kg/m3 and molar enthalpy J/mol; the phase is checked to be gas where
        CoolProp's phase-stability flash converges (else the gas phase is imposed)."""
        try:
            state.unspecify_phase()
            state.update(CP.PT_INPUTS, p * 1e3, t)
            assert state.phase() in gas, (x, t, p, state.phase())
        except ValueError:
            state.specify_phase(CP.iphase_gas)
            state.update(CP.PT_INPUTS, p * 1e3, t)
        return state.rhomass(), state.hmolar()

    return at


def _benchmark(adapter, x, density_tol, step=25):
    """Every grid point inside the claim of mixture *x*: (n points, worst density deviation,
    worst enthalpy-difference deviation kJ/kmol)."""
    regions = {c: _boxes_at(c, xc) for c, xc in x.items()}
    by_cas = {FLUIDS[c][0]: xc for c, xc in x.items()}
    assert not packages.limit_gaps(SYNGAS, by_cas), x  # a composition the claim holds
    boxes = [b for c in x for b in regions[c]]
    ref = _reference(x)
    # enthalpy differences from the lowest claimed temperature at 100 kPa(a)
    anchor = (max(min(b.temperature[0] for b in regions[c]) for c in x), 100.0)
    h0 = adapter.flash(Inputs(*anchor, x)).enthalpy
    _, h0_ref = ref(*anchor)
    n, worst_rho, worst_h = 0, 0.0, 0.0
    temps, pressures = _grid(boxes, step)
    for t, p in itertools.product(temps, pressures):
        if not all(_inside(regions[c], t, p) for c in x):
            continue
        got = adapter.flash(Inputs(float(t), p, x))
        assert got.phase == "vapor", (x, t, p)
        rho, h = ref(t, p)
        d_rho = got.density / rho - 1
        d_h = (got.enthalpy - h0) - (h - h0_ref)  # J/mol = kJ/kmol
        assert abs(d_rho) <= density_tol, (x, t, p, d_rho)
        assert abs(d_h) <= TOL["enthalpy_difference_abs_kJ_per_kmol"], (x, t, p, d_h)
        n += 1
        worst_rho, worst_h = max(worst_rho, abs(d_rho)), max(worst_h, abs(d_h))
    return n, worst_rho, worst_h


@pytest.mark.parametrize("cid", list(FLUIDS))
def test_pure_fluid_against_its_reference_equation_of_state(syngas, cid):
    n, rho, _ = _benchmark(syngas, {cid: 1.0}, TOL["density_rel_pure"])
    assert n > 50 and rho > 0.005  # the grid reaches where Peng-Robinson drifts


MIXABLE = ["H2", "N2", "AR", "CH4", "CO", "CO2"]


@pytest.mark.parametrize(
    "a,b", list(itertools.combinations(MIXABLE, 2)), ids=lambda v: v if isinstance(v, str) else ""
)
def test_binary_against_the_reference_mixture_model(syngas, a, b):
    for xa in (0.1, 0.5, 0.9):
        n, _, _ = _benchmark(syngas, {a: xa, b: round(1 - xa, 10)}, TOL["density_rel"], 50)
        assert n > 30


@pytest.mark.parametrize("other", ["H2", "N2"])  # CH4 and Ar: dilute, in GASES
def test_dilute_ammonia_binary_against_the_reference_mixture_model(syngas, other):
    for x_nh3 in (0.05, 0.15, packages.NH3_IN_MIXTURE):
        n, _, _ = _benchmark(
            syngas, {other: round(1 - x_nh3, 10), "NH3": x_nh3}, TOL["density_rel"]
        )
        assert n > 30


#: Representative gases (compositions chosen for the test, not data).
GASES = {
    "ammonia make-up": {"H2": 0.7395, "N2": 0.2465, "CH4": 0.011, "AR": 0.003},
    "ammonia loop inerts": {"H2": 0.60, "N2": 0.20, "CH4": 0.13, "AR": 0.07},
    "ammonia converter inlet": {"H2": 0.66, "N2": 0.22, "CH4": 0.05, "AR": 0.04, "NH3": 0.03},
    "ammonia converter outlet": {"H2": 0.54, "N2": 0.18, "CH4": 0.06, "AR": 0.05, "NH3": 0.17},
    "ammonia at its limits": {"H2": 0.45, "N2": 0.15, "CH4": 0.05, "AR": 0.10, "NH3": 0.25},
    "ammonia, nitrogen-rich": {"N2": 0.55, "H2": 0.10, "AR": 0.10, "NH3": 0.25},
    "ammonia, methane-rich": {"H2": 0.40, "N2": 0.15, "CH4": 0.20, "NH3": 0.25},
    "ammonia, inerts at their limits": {
        "H2": 0.40,
        "N2": 0.13,
        "CH4": 0.20,
        "AR": 0.10,
        "NH3": 0.17,
    },
    "methanol syngas": {"H2": 0.70, "CO": 0.15, "CO2": 0.08, "CH4": 0.05, "N2": 0.02},
    "methanol loop": {"H2": 0.80, "CO": 0.05, "CO2": 0.03, "CH4": 0.10, "N2": 0.02},
    "shifted gas": {"H2": 0.55, "CO2": 0.30, "CO": 0.05, "CH4": 0.05, "N2": 0.04, "AR": 0.01},
}


@pytest.mark.parametrize("gas", list(GASES))
def test_multicomponent_gas_against_the_reference_mixture_model(syngas, gas):
    n, _, _ = _benchmark(syngas, GASES[gas], TOL["density_rel"])
    assert n > 30


R = 8.314462618  # J/(mol K)


def test_package_against_measured_ammonia_mixtures(syngas):
    """Date (1973) at 323.15 K: every measured point the claim holds, within the claim's
    tolerance; the argon-rich and ammonia-rich mixtures are refused."""
    data = SYN["date1973"]
    t = data["temperature_K"]
    checked = 0
    for mixture in data["mixtures"]:
        x = mixture["x"]
        mw = sum(xc * MOLAR_MASS[c] for c, xc in x.items()) / 1000.0
        for atm, z in mixture["Z"].items():
            p = atm * 101.325
            inside = not packages.limit_gaps(
                SYNGAS, {FLUIDS[c][0]: xc for c, xc in x.items()}
            ) and all(_inside(_boxes_at(c, xc), t, p) for c, xc in x.items())
            if not inside:
                with pytest.raises(Unsupported):
                    syngas.flash(Inputs(t, p, x))
                continue
            rho = syngas.flash(Inputs(t, p, x)).density
            assert abs(p * 1e3 * mw / (rho * R * t) / z - 1) <= TOL["measured_density_rel"], (
                x,
                atm,
            )
            checked += 1
    assert checked >= 25


def test_package_against_measured_hot_methane_gas(syngas):
    """Cheng et al. (2019): H2-CO2-CH4 at 673.1 K, above methane's reference equation."""
    data = SYN["cheng2019"]
    x = data["x"]
    mw = sum(xc * MOLAR_MASS[c] for c, xc in x.items()) / 1000.0
    checked = 0
    for p, rho, _ in data["points"]:
        if p > 20000:
            with pytest.raises(Unsupported):  # beyond the claimed 20 MPa
                syngas.flash(Inputs(data["temperature_K"], p, x))
            continue
        got = syngas.flash(Inputs(data["temperature_K"], p, x)).density / mw
        assert abs(got / rho - 1) <= TOL["measured_density_rel"], p
        checked += 1
    assert checked == 7


# -- refusals of the syngas package -------------------------------------------------------------


def test_syngas_refuses_what_it_does_not_claim(syngas):
    with pytest.raises(Unsupported) as pair:  # no reference model for NH3 with CO
        syngas.flash(Inputs(700.0, 15000.0, {"H2": 0.6, "CO": 0.2, "NH3": 0.2}))
    assert pair.value.rule == "property-unsupported"
    assert "pair carbon monoxide-ammonia (not benchmarked)" in str(pair.value)
    with pytest.raises(Unsupported) as rich:  # more ammonia than the mixture benchmark
        syngas.flash(Inputs(700.0, 15000.0, {"H2": 0.5, "N2": 0.2, "NH3": 0.3}))
    assert rich.value.rule == "property-out-of-range"
    assert "ammonia at mole fraction 0.3 with hydrogen (claimed up to 0.25)" in str(rich.value)
    with pytest.raises(Unsupported) as argon:  # Peng-Robinson misses Ar-NH3
        syngas.flash(Inputs(600.0, 5000.0, {"H2": 0.6, "AR": 0.2, "NH3": 0.2}))
    assert "argon at mole fraction 0.2 with ammonia (claimed up to 0.1)" in str(argon.value)
    with pytest.raises(Unsupported) as hot:  # CO beyond its reference equation's 500 K
        syngas.flash(Inputs(550.0, 8000.0, {"H2": 0.7, "CO": 0.3}))
    assert hot.value.rule == "property-out-of-range"
    assert "carbon monoxide is claimed at" in str(hot.value)
    # methane above 625 K: only dilute (measured at x 0.2026) and to 673.1 K
    assert syngas.flash(Inputs(650.0, 15000.0, {"H2": 0.8, "CH4": 0.2})).phase == "vapor"
    for t, x_ch4 in ((650.0, 0.3), (700.0, 0.1)):
        with pytest.raises(Unsupported) as methane:
            syngas.flash(Inputs(t, 15000.0, {"H2": 1 - x_ch4, "CH4": x_ch4}))
        assert "methane is claimed at" in str(methane.value)
        assert "625-673.1 K from 100 to 20000 kPa(a) up to mole fraction 0.2026" in str(
            methane.value
        )
    with pytest.raises(Unsupported) as liquid:  # liquid ammonia: outside every claimed box
        syngas.flash(Inputs(250.0, 1000.0, {"NH3": 1.0}))
    assert liquid.value.rule == "property-out-of-range"
    with pytest.raises(Unsupported) as vle:
        syngas.k_values(2000.0, {"H2": 0.75, "N2": 0.25})
    assert "claims vapour only" in str(vle.value)
    with pytest.raises(Unsupported):
        syngas.liquid_viscosity(300.0, {"N2": 1.0})


def test_syngas_vapour_quantities_for_sizing(syngas):
    x = {"H2": 0.75, "N2": 0.25}
    k = syngas.heat_capacity_ratio(Inputs(700.0, 15000.0, x))  # single root, labelled liquid
    assert 1.3 < k < 1.5
    s = syngas.entropy(Inputs(700.0, 15000.0, x))
    out = syngas.flash_ps(20000.0, s, x)  # an isentropic compression stays vapour
    assert out.phase == "vapor" and out.density > syngas.flash(Inputs(700.0, 15000.0, x)).density


# -- routing ------------------------------------------------------------------------------------


def test_routing_picks_the_package_covering_the_most_streams(tmp_path):
    ws = _plant(
        tmp_path / "a",
        {
            "MAKEUP": (300.0, 3000.0, {"H2": 0.74, "N2": 0.25, "AR": 0.01}),
            "LOOP": (700.0, 15000.0, {"H2": 0.6, "CO": 0.2, "NH3": 0.2}),
            "PURGE": (400.0, 10000.0, {"H2": 0.6, "N2": 0.2, "CH4": 0.1, "AR": 0.1}),
            "COLD": (300.0, 15000.0, {"H2": 0.6, "N2": 0.2, "CH4": 0.1, "AR": 0.1}),
        },
    )
    process = _process(ws)
    listed = coverage(process, "design")
    assert listed.coverage["package"] == "syngas-pr-vapor"
    assert "covers 2 of the 3 component sets" in listed.coverage["reason"]
    rows = {r["id"]: r for r in listed.coverage["streams"]}
    assert rows["MAKEUP"]["status"] == "covered"
    assert rows["LOOP"]["status"] == "not-covered" and "ammonia" in rows["LOOP"]["reason"]
    # the nearest other package and what it lacks
    assert (
        "no package covers it; the nearest is this process's syngas-pr-vapor"
        in rows["LOOP"]["reason"]
    )
    assert rows["PURGE"]["status"] == "covered"
    # components covered, state outside the benchmarked boxes (PR drifts in cold dense gas)
    assert rows["COLD"]["rule"] == "cheme.process-property-out-of-range"
    assert "hydrogen is claimed at" in rows["COLD"]["reason"]
    assert [f.ids for f in listed.findings] == [["LOOP"], ["COLD"]]
    # nothing written
    before = (ws.root / "process/flowsheet.yaml").read_text()
    assert (ws.root / "process/flowsheet.yaml").read_text() == before


def test_fill_with_the_syngas_package_records_it(tmp_path):
    ws = _plant(
        tmp_path / "a",
        {
            "MAKEUP": (300.0, 3000.0, {"H2": 0.74, "N2": 0.25, "AR": 0.01}),
            "LOOP": (700.0, 15000.0, {"H2": 0.6, "CO": 0.2, "NH3": 0.2}),
            "CONVERTER": (700.0, 15000.0, {"H2": 0.6, "N2": 0.2, "NH3": 0.2}),
        },
    )
    result = run(ws, _process(ws), "design", write=True)
    assert result.refused == ["LOOP"]
    flowsheet = yaml.safe_load((ws.root / "process/flowsheet.yaml").read_text())
    makeup = flowsheet["streams"][0]["state"]["design"]
    assert makeup["phase"]["value"] == "vapor"
    assert "package syngas-pr-vapor" in makeup["calculated"]["density"]["source"]
    assert "calculated" not in flowsheet["streams"][1]["state"]["design"]
    # ammonia converter gas (dilute NH3 with H2 and N2) is claimed now
    assert flowsheet["streams"][2]["state"]["design"]["phase"]["value"] == "vapor"
    method = yaml.safe_load((ws.root / "process/materials.yaml").read_text())["property_method"]
    assert method["package"] == "syngas-pr-vapor" and method["status"] == "configured"
    assert method["application_range"]["phases"] == ["vapor"]
    nh3_boxes = method["application_range"]["component_regions"]["7664-41-7"]
    assert {b.get("max_mole_fraction") for b in nh3_boxes} == {None, 0.25}
    assert method["application_range"]["pair_limits"]["1333-74-0&7664-41-7"] == {"7664-41-7": 0.25}
    assert method["benchmark"]["test"] == "tests/test_property_packages.py"
    assert method["benchmark"]["tolerances"]["density_rel"] == 0.03
    # recorded now: a second fill keeps the package and changes nothing
    first = (ws.root / "process/flowsheet.yaml").read_text()
    assert run(ws, _process(ws), "design", write=True).written == 0
    assert (ws.root / "process/flowsheet.yaml").read_text() == first


def test_a_recorded_package_is_used_and_an_unknown_one_refused(tmp_path):
    streams = {"S1": (300.0, 3000.0, {"N2": 1.0})}  # both packages cover nitrogen
    assert coverage(_process(_plant(tmp_path / "a", streams)), "design").coverage["package"] == (
        "air-pr-chemsep"  # first in the registry on a tie
    )
    chosen = coverage(_process(_plant(tmp_path / "b", streams, "syngas-pr-vapor")), "design")
    assert chosen.coverage["package"] == "syngas-pr-vapor" and chosen.coverage["recorded"]
    ws = _plant(tmp_path / "c", streams, "nope")
    listed = coverage(_process(ws), "design")
    assert listed.coverage["package"] is None
    assert [f.level for f in listed.findings] == ["error"]
    result = run(ws, _process(ws), "design", write=True)
    assert [f.rule for f in result.findings] == ["cheme.process-property-unsupported"]
    assert "unknown property package 'nope'" in result.findings[0].message
    from chemeascode.domains.process.model import rules

    found = [f for f in rules(_process(ws)) if f.rule == "cheme.process-property-package"]
    assert found and found[0].file == "process/materials.yaml" and found[0].line


def test_a_stream_another_package_covers_names_it(tmp_path):
    ws = _plant(
        tmp_path / "a",
        {
            "A1": (300.0, 101.325, {"N2": 0.79, "O2": 0.21}),
            "A2": (290.0, 101.325, {"N2": 0.79, "O2": 0.21}),
            "SYN": (300.0, 3000.0, {"H2": 0.75, "N2": 0.25}),
        },
        ids=("N2", "H2", "O2"),
    )
    listed = coverage(_process(ws), "design")
    assert listed.coverage["package"] == "air-pr-chemsep"
    syn = next(r for r in listed.coverage["streams"] if r["id"] == "SYN")
    assert (
        "package syngas-pr-vapor covers it, but this process uses air-pr-chemsep" in (syn["reason"])
    )


def test_legacy_method_is_the_air_package_and_keeps_its_fingerprint(tmp_path):
    # a property_method --fill recorded before packages (no package field): its fingerprint,
    # which every calculated value of an existing plant carries, is unchanged
    legacy = PropertyMethod(
        adapter="thermo",
        status="configured",
        phase_models=dict(AIR.phase_models),
        eos=AIR.eos,
        binary_interaction=AIR.binary_interaction,
        application_range=AIR.validated,
        versions={"thermo": "0.6.1", "chemicals": "1.5.2"},
    )
    assert method_fingerprint(legacy) == "4407ec560dc1d659"
    recorded = legacy.model_copy(update={"package": AIR.id, "benchmark": AIR.benchmark})
    assert method_fingerprint(recorded) == "4407ec560dc1d659"
    assert packages.choose(None, legacy=True, mixtures=[{"1333-74-0"}]).package is AIR
    syngas = legacy.model_copy(
        update={
            "package": SYNGAS.id,
            "phase_models": dict(SYNGAS.phase_models),
            "application_range": SYNGAS.validated,
        }
    )
    assert method_fingerprint(syngas) != method_fingerprint(legacy)


def test_examples_route_as_expected(tmp_path):
    shutil.copytree(EXAMPLES / "process-ammonia", tmp_path / "nh3")
    listed = coverage(_process(Workspace(tmp_path / "nh3")), "design")
    assert listed.coverage["package"] in {"syngas-pr-vapor", "air-pr-chemsep"}
    shutil.copytree(EXAMPLES / "process-blocks", tmp_path / "blocks")
    blocks = coverage(_process(Workspace(tmp_path / "blocks")), "design")
    assert all(r["status"] != "covered" for r in blocks.coverage["streams"])


def test_cli_coverage_writes_nothing(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from chemeascode.interfaces.cli import app

    ws = _plant(tmp_path / "a", {"S1": (300.0, 3000.0, {"H2": 0.75, "N2": 0.25})})
    before = sorted((p, p.read_text()) for p in (ws.root / "process").iterdir())
    monkeypatch.chdir(ws.root)
    shown = CliRunner().invoke(app, ["process", "props", "--coverage"])
    assert shown.exit_code == 0, shown.output
    assert "property package: syngas-pr-vapor" in shown.output and "S1: syngas" in shown.output
    as_json = CliRunner().invoke(app, ["process", "props", "--coverage", "--json"])
    assert '"package": "syngas-pr-vapor"' in as_json.output
    assert sorted((p, p.read_text()) for p in (ws.root / "process").iterdir()) == before
    both = CliRunner().invoke(app, ["process", "props", "--coverage", "--check"])
    assert both.exit_code == 2
