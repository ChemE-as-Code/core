"""Property packages: the benchmarked methods ``cheme process props`` may use.

A package names an adapter, its equation of state and models, the source of its binary
interaction parameters, the components it covers (CAS numbers) and its validated range per
phase, per component (:class:`~chemeascode.domains.process.schema.Region` boxes, some only up to
a mole fraction) and per binary pair (some only up to mole fractions: ``pair_limits``), with the
test that benchmarks that range and the tolerance it asserts. Nothing outside a
package's range is claimed: a stream no package covers is refused, naming the nearest package and
what it lacks (``props.range_problems``); there is no fallback.

A process uses one package (materials.yaml ``property_method.package``, or, when none is
recorded, the package that covers the most streams: :func:`choose`). Adding a package means
adding a :class:`Package` here **and** a test that benchmarks every claim it makes against an
authoritative reference (a reference equation of state, or published data with the source
cited); a component, phase or region the test does not cover stays out of the claim.

Pure data: works without thermo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations

from chemeascode.domains.process.schema import ApplicationRange, Benchmark, Region

EOS = "Peng-Robinson (thermo PRMIX)"
KIJ = "ChemSep PR kij (thermo IPDB 'ChemSep PR')"
ENTHALPY_MODEL = (
    "Peng-Robinson departure + ideal-gas heat capacities; ideal gas 298.15 K, 101.325 kPa = 0"
)


@dataclass(frozen=True)
class Package:
    id: str
    title: str
    #: what computes it (``props.Adapter`` implements ``thermo``)
    adapter: str
    eos: str
    binary_interaction: str
    phase_models: dict[str, str]
    #: CAS number -> name
    components: dict[str, str]
    validated: ApplicationRange
    benchmark: Benchmark
    #: the liquid density model (None: no liquid claimed)
    liquid_density: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def vapor_only(self) -> bool:
        return set(self.validated.phases) == {"vapor"}

    def name(self, cas: str) -> str:
        return self.components.get(cas) or NAMES.get(cas, cas)


def pair(a: str, b: str) -> str:
    """The key of a binary pair of CAS numbers (sorted, ``&``-joined)."""
    return "&".join(sorted((a, b)))


def _boxes(
    *boxes: tuple[float, float, float], p_min: float = 100.0, max_x: float | None = None
) -> list[Region]:
    """``(T_min K, T_max K, P_max kPa(a))`` boxes, each from *p_min* kPa(a), up to mole
    fraction *max_x* (None: any)."""
    return [
        Region(temperature=(lo, hi), pressure=(p_min, pmax), max_mole_fraction=max_x)
        for lo, hi, pmax in boxes
    ]


# -- air separation (release 1) -----------------------------------------------------------------

AIR_COMPONENTS = {"7727-37-9": "nitrogen", "7782-44-7": "oxygen", "7440-37-1": "argon"}
AIR = Package(
    id="air-pr-chemsep",
    title="Air separation: N2/O2/Ar, Peng-Robinson VLE, ChemSep kij, COSTALD liquid density",
    adapter="thermo",
    eos=EOS,
    binary_interaction=KIJ,
    phase_models={
        "vle": "phi-phi, Peng-Robinson for both phases",
        "vapor_density": "Peng-Robinson",
        "liquid_density": "COSTALD (chemicals COSTALD_mixture)",
        "enthalpy": ENTHALPY_MODEL,
    },
    components=AIR_COMPONENTS,
    validated=ApplicationRange(
        temperature=(77.0, 315.0),
        pressure=(100.0, 3200.0),
        vle_pressure=(100.0, 600.0),
        phases=["vapor", "liquid", "two-phase"],
        components=sorted(AIR_COMPONENTS),
    ),
    benchmark=Benchmark(
        test="tests/test_process_props.py",
        reference="NIST WebBook reference equations of state (Span 2000 N2, Schmidt-Wagner 1985 "
        "O2, Lemmon 2000 air and N2/O2/Ar mixture), values in "
        "tests/data/process_props_references.yaml",
        tolerances={
            "air_density_rel": 0.005,
            "gas_density_rel": 0.01,
            "saturation_temperature_abs_K": 0.3,
            "liquid_density_rel": 0.015,
            "two_phase_temperature_abs_K": 0.3,
            "vapor_fraction_abs": 0.03,
        },
    ),
    liquid_density="COSTALD",
)

# -- synthesis-loop gases (vapour) --------------------------------------------------------------

SYNGAS_COMPONENTS = {
    "1333-74-0": "hydrogen",
    "7727-37-9": "nitrogen",
    "7664-41-7": "ammonia",
    "7440-37-1": "argon",
    "74-82-8": "methane",
    "630-08-0": "carbon monoxide",
    "124-38-9": "carbon dioxide",
}
H2, N2, AR, CH4, NH3 = "1333-74-0", "7727-37-9", "7440-37-1", "74-82-8", "7664-41-7"
#: Ammonia in a mixture: up to this mole fraction (a synthesis converter outlet holds about 0.2).
NH3_IN_MIXTURE = 0.25
#: Argon with ammonia: up to this mole fraction (Peng-Robinson with the ChemSep kij misses the
#: Ar-NH3 binary by more than 3 % in density above about 5 MPa, also against Date 1973).
AR_WITH_NH3 = 0.10
#: Methane with ammonia: up to this mole fraction (methane-rich ammonia gas misses the enthalpy
#: tolerance above about 10 MPa; loop gas holds up to about 0.15).
CH4_WITH_NH3 = 0.20
#: Methane above its reference equation's 625 K: in mixtures up to the mole fraction and the
#: temperature (673.1 K) Cheng et al. 2019 measured.
CH4_HOT = 0.2026

#: Where tests/test_property_packages.py holds the tolerances against the reference equations of
#: state (pure fluids within 2 % in density, the mixtures within 3 %). Upper temperatures stop at
#: the stated validity of each reference equation (CoolProp's Tmax: CO 500 K, CH4 625 K, NH3
#: 725 K) except methane in mixtures to 673.1 K, where measured densities exist; boxes step down in
#: pressure at low temperature, where Peng-Robinson densities drift.
SYNGAS_REGIONS = {
    "1333-74-0": _boxes(
        (250, 1000, 5000),
        (350, 1000, 10000),
        (450, 1000, 15000),
        (500, 1000, 20000),
        (600, 1000, 30000),
    ),
    "7727-37-9": _boxes(
        (250, 1000, 5000),
        (300, 1000, 10000),
        (400, 1000, 15000),
        (500, 1000, 20000),
        (725, 1000, 25000),
    ),
    "7440-37-1": _boxes(
        (250, 1000, 5000),
        (300, 1000, 10000),
        (400, 1000, 15000),
        (450, 1000, 20000),
        (550, 1000, 25000),
        (700, 1000, 30000),
    ),
    "74-82-8": _boxes(
        (250, 625, 2000),
        (300, 625, 3000),
        (350, 625, 5000),
        (400, 625, 10000),
        (450, 625, 15000),
        (500, 625, 20000),
    )
    + _boxes((625, 673.1, 20000), max_x=CH4_HOT),
    "630-08-0": _boxes((250, 500, 5000), (300, 500, 10000), (350, 500, 15000), (450, 500, 20000)),
    "124-38-9": _boxes(
        (250, 1000, 1000),
        (300, 1000, 3000),
        (350, 1000, 5000),
        (400, 1000, 10000),
        (450, 1000, 20000),
        (700, 1000, 30000),
    ),
    # ammonia: pure, the vapour well away from saturation and the critical point (405.6 K); in
    # mixtures, dilute (its partial pressure stays below saturation)
    "7664-41-7": _boxes(
        (350, 725, 1000),
        (400, 725, 3000),
        (450, 725, 10000),
        (500, 725, 15000),
        (600, 725, 20000),
    )
    + _boxes(
        (320, 725, 5000),
        (375, 725, 10000),
        (450, 725, 15000),
        (500, 725, 20000),
        max_x=NH3_IN_MIXTURE,
    ),
}
#: Ammonia's pairs benchmarked against the Neumann et al. (2020) mixture models (no CO or CO2).
NH3_PAIRS = sorted(pair(NH3, other) for other in (H2, N2, AR, CH4))
#: The pairs benchmarked against GERG-2008 (Kunz and Wagner 2012) or Gernert (2013) mixture
#: models, and ammonia's.
SYNGAS_PAIRS = sorted(
    [pair(a, b) for a, b in combinations([H2, N2, AR, CH4, "630-08-0", "124-38-9"], 2)] + NH3_PAIRS
)
SYNGAS_PAIR_LIMITS = {key: {NH3: NH3_IN_MIXTURE} for key in NH3_PAIRS} | {
    pair(AR, NH3): {NH3: NH3_IN_MIXTURE, AR: AR_WITH_NH3},
    pair(CH4, NH3): {NH3: NH3_IN_MIXTURE, CH4: CH4_WITH_NH3},
}
SYNGAS = Package(
    id="syngas-pr-vapor",
    title="Synthesis-loop gases (H2, N2, Ar, CH4, CO, CO2; NH3 pure and dilute with H2, N2, "
    "Ar, CH4), vapour only, Peng-Robinson, ChemSep kij",
    adapter="thermo",
    eos=EOS,
    binary_interaction=KIJ,
    phase_models={
        "phase": "Peng-Robinson flash; vapour only (a single-phase state on the only EOS root "
        "above the pseudo-critical temperature counts as vapour)",
        "vapor_density": "Peng-Robinson",
        "enthalpy": ENTHALPY_MODEL,
    },
    components=SYNGAS_COMPONENTS,
    validated=ApplicationRange(
        temperature=(250.0, 1000.0),
        pressure=(100.0, 30000.0),
        phases=["vapor"],
        components=sorted(SYNGAS_COMPONENTS),
        component_regions=SYNGAS_REGIONS,
        pairs=SYNGAS_PAIRS,
        pair_limits=SYNGAS_PAIR_LIMITS,
    ),
    benchmark=Benchmark(
        test="tests/test_property_packages.py",
        reference="CoolProp 8.0.0 (HEOS) reference equations of state, evaluated by the test: "
        "CoolProp keys Leachman-JPCRD-2009 (H2), Span-JPCRD-2000 (N2), Tegeler-JPCRD-1999 (Ar), "
        "Setzmann-JPCRD-1991 (CH4), Lemmon-JCED-2006 (CO), Span-JPCRD-1996 (CO2), Gao-JPCRD-2020 "
        "(NH3); mixtures with the GERG-2008 (Kunz-JCED-2012) and Gernert-Thesis-2013 departure "
        "functions, and for ammonia with H2, N2, Ar and CH4 the Neumann et al. (Fluid Phase "
        "Equilib. 511, 112496, 2020) models with the parameters of EOS-CG-2021 (Neumann et al., "
        "Int. J. Thermophys. 44, 178, 2023, Tables 4 and 5). Measured: Date (Rev. Phys. Chem. "
        "Jpn. 43, 63, 1973) N2-NH3 and Ar-NH3 compressibility factors at 323.15 K; Cheng et al. "
        "(J. Chem. Eng. Data 64, 1693, 2019) H2-CO2-CH4 densities at 673.1 K. Values in "
        "tests/data/syngas_references.yaml",
        tolerances={
            "density_rel_pure": 0.02,
            "density_rel": 0.03,
            "enthalpy_difference_abs_kJ_per_kmol": 300.0,
            "measured_density_rel": 0.03,
        },
    ),
    notes=[
        "vapour only: liquid, two-phase, VLE and liquid viscosity are not claimed",
        f"ammonia in a mixture: with hydrogen, nitrogen, argon and methane only, up to mole "
        f"fraction {NH3_IN_MIXTURE:g}, with argon up to {AR_WITH_NH3:g} and methane up to "
        f"{CH4_WITH_NH3:g} (no CO or CO2 with NH3)",
        f"methane is claimed to 625 K (its reference equation), and in mixtures up to mole "
        f"fraction {CH4_HOT:g} to 673.1 K (measured densities); carbon monoxide above 500 K is not "
        "claimed (no reference equation or measured densities), so hot methanol reactor gas is "
        "refused, and ammonia converter gas with methane above 673.1 K too",
    ],
)

#: The registry, in order of preference on a tie.
PACKAGES: tuple[Package, ...] = (AIR, SYNGAS)
#: Component names by CAS number, over every package.
NAMES = {cas: name for p in PACKAGES for cas, name in p.components.items()}
#: The package of a ``property_method`` recorded before packages existed.
LEGACY = AIR


def get(package_id: str) -> Package | None:
    return next((p for p in PACKAGES if p.id == package_id), None)


def component_gaps(package: Package, cas: set[str], claim: ApplicationRange | None = None):
    """What *package* lacks for a mixture of *cas* (``None`` for a component without a CAS
    number): components outside it, then pairs it has not benchmarked; empty when covered."""
    claim = claim or package.validated
    names = {c: package.name(c) for c in cas if c}
    missing = [
        f"component {names.get(c, 'without a CAS number')} ({c or 'no CAS'})"
        for c in sorted(cas, key=lambda c: c or "")
        if not c or c not in claim.components
    ]
    if missing or claim.pairs is None:
        return missing
    known = set(claim.pairs)
    return [
        f"pair {names[a]}-{names[b]} (not benchmarked)"
        for a, b in combinations(sorted(cas), 2)
        if pair(a, b) not in known
    ]


#: Round-off allowed on a mole-fraction limit (normalised compositions), for boxes and pairs alike.
X_ROUND_OFF = 1e-12


def _holds(box: Region, temperature: float, pressure: float, x: float | None) -> bool:
    return (
        box.temperature[0] <= temperature <= box.temperature[1]
        and box.pressure[0] <= pressure <= box.pressure[1]
        and (
            box.max_mole_fraction is None
            or (x is not None and x <= box.max_mole_fraction + X_ROUND_OFF)
        )
    )


def region_gaps(
    package: Package,
    cas: set[str],
    temperature: float,
    pressure: float,
    claim: ApplicationRange | None = None,
    fractions: dict[str, float] | None = None,
) -> list[str]:
    """Components of *cas* whose benchmarked boxes in *package* do not hold *temperature* K,
    *pressure* kPa(a) and their mole fraction in *fractions* (CAS -> x; None: unknown, so only
    the boxes for any mole fraction count). The overall range is checked separately."""
    claim = claim or package.validated
    if not claim.component_regions:
        return []
    found = []
    for c in sorted(cas):
        boxes = claim.component_regions.get(c)
        x = fractions.get(c) if fractions is not None else None
        if boxes is None or any(_holds(b, temperature, pressure, x) for b in boxes):
            continue
        found.append(
            f"{package.name(c)} is claimed "
            + ", ".join(
                f"at {b.temperature[0]:g}-{b.temperature[1]:g} K from {b.pressure[0]:g} to "
                f"{b.pressure[1]:g} kPa(a)"
                + (
                    f" up to mole fraction {b.max_mole_fraction:g}"
                    if b.max_mole_fraction is not None
                    else ""
                )
                for b in boxes
            )
        )
    return found


def limit_gaps(
    package: Package, fractions: dict[str, float], claim: ApplicationRange | None = None
) -> list[str]:
    """The pair limits of *package* the mixture *fractions* (CAS -> mole fraction) exceeds."""
    claim = claim or package.validated
    found = []
    for key, limits in sorted((claim.pair_limits or {}).items()):
        a, b = key.split("&")
        if fractions.get(a, 0.0) <= 0.0 or fractions.get(b, 0.0) <= 0.0:
            continue
        found += [
            f"{package.name(c)} at mole fraction {fractions[c]:g} with "
            f"{package.name(b if c == a else a)} (claimed up to {top:g})"
            for c, top in sorted(limits.items())
            if fractions[c] > top + X_ROUND_OFF
        ]
    return found


def in_overall(claim: ApplicationRange, temperature: float, pressure: float) -> bool:
    lo, hi = claim.temperature or (0.0, float("inf"))
    plo, phi = claim.pressure or (0.0, float("inf"))
    return lo <= temperature <= hi and plo <= pressure <= phi


@dataclass
class Choice:
    """The package of a process and why (*package* None: *reason* says why there is none)."""

    package: Package | None
    reason: str
    recorded: bool = False


def choose(recorded: str | None, legacy: bool, mixtures: list[set[str]]) -> Choice:
    """The package of a process: *recorded* (materials.yaml ``property_method.package``), else
    the release-1 package when a method was configured before packages existed (*legacy*),
    else the one covering the most of *mixtures* (the CAS sets of the streams; first in
    :data:`PACKAGES` on a tie), else the one sharing the most components with them."""
    if recorded:
        found = get(recorded)
        if found is None:
            return Choice(
                None,
                f"unknown property package {recorded!r} (known: "
                f"{', '.join(p.id for p in PACKAGES)})",
                recorded=True,
            )
        return Choice(found, "recorded in property_method.package", recorded=True)
    if legacy:
        return Choice(LEGACY, "property_method configured before packages: the release-1 one")
    scores = [sum(not component_gaps(p, m) for m in mixtures) for p in PACKAGES]
    best = max(scores, default=0)
    if best > 0:
        package = PACKAGES[scores.index(best)]
        return Choice(
            package, f"covers {best} of the {len(mixtures)} component sets of the streams"
        )
    every = set().union(*mixtures) if mixtures else set()
    overlap = [len(every & set(p.components)) for p in PACKAGES]
    package = PACKAGES[overlap.index(max(overlap))]
    return Choice(package, "covers no stream's components; the nearest by shared components")
