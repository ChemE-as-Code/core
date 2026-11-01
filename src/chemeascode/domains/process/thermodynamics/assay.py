"""Petroleum assays (schema ``cheme/assay/v1``, ``process/assays.yaml``): sourced distillation
curves or cuts characterised into versioned pseudocomponents.

An assay states where its data come from (``source``) and either

- a distillation curve (``TBP`` or ASTM ``D86``: liquid volume percent distilled against
  temperature, from the initial to the final boiling point) and the density of the whole
  fraction (specific gravity 60/60 °F, API gravity or the density at 15 °C) or, instead of the
  density, its Watson K; or
- its cuts, each with its liquid volume percent, normal boiling point and specific gravity.

A measured molar mass is a check, not an input. :func:`characterize` turns an assay into
pseudocomponents, every step deterministic and named in :data:`CORRELATIONS`:

1. a D86 curve is converted to TBP (:func:`d86_to_tbp`, API procedure 3A1.1);
2. the TBP curve, linear between the given points, is cut into ``pseudocomponents`` cuts of
   equal liquid volume (default 8); a cut's normal boiling point is the mean temperature of the
   curve over its volume;
3. the cuts of a curve share one Watson K: the fraction's, from its specific gravity and the
   volume-weighted cube roots of the cut boiling points (so the cut gravities reproduce the
   fraction's exactly under ideal mixing by volume), or the one the assay gives;
4. molar mass, critical temperature and pressure and the carbon-to-hydrogen weight ratio from
   the boiling point and specific gravity (Riazi-Daubert 1987), the acentric factor (Lee-Kesler,
   ``chemicals.acentric.LK_omega``), and the similarity variable of the C/H composition, from
   which thermo's Lastovka-Shaw method gives the ideal-gas heat capacity;
5. the mass and mole fractions of the pseudocomponents from their volumes, gravities and molar
   masses.

Nothing is extrapolated. A curve that does not run from 0 to 100 % distilled, has fewer than
:data:`MIN_POINTS` points (a D86 curve: not exactly :data:`D86_POINTS`) or falls back, cuts
whose volumes do not add up to 100 %, or a missing density is ``cheme.assay-insufficient``; a
pseudocomponent whose boiling point, gravity, molar mass or reduced boiling point lies outside
:data:`RANGES` (where the correlations were fitted) is ``cheme.assay-extrapolation``. Either
refuses the assay: no pseudocomponent is produced.

Each characterisation carries :data:`METHOD_VERSION` and a 16-hex ``fingerprint`` of the method
version and the assay inputs (not its id, title or source text); a pseudocomponent's
``identity`` is ``pseudo:<fingerprint>:<n>``, so two pseudocomponents with the same identity
were made by the same method from the same data. :func:`comparability` names what differs
between two characterisations; results made from different ones are not comparable, and every
:class:`AssayFlash` carries the fingerprint it was made from. ``cheme process assay --fill``
records each characterisation in :data:`RECORD_FILE`; ``cheme validate`` and ``--check`` report
a record made from other inputs or another method version (``cheme.assay-record-stale``).

The flash of the pseudocomponents (:func:`flash`, :func:`saturation`) is a Peng-Robinson flash
through thermo with no interaction parameters between pseudocomponents (kij = 0). It is claimed
only inside :data:`FLASH_CLAIM`, benchmarked in ``tests/test_assay.py`` against CoolProp's
reference multi-fluid models for a defined naphtha surrogate; a state or a pseudocomponent
outside it is computed but reported outside the claim.

The checks (:func:`check`, the validation findings) need only the standard library; the
characterisation needs ``chemicals`` and the flash ``thermo`` (extra ``props``), both imported
inside the functions. The pure-component routes (``phase.py``, the DWSIM simulation) do not use
this module and still refuse a pseudocomponent.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision, value_fingerprint
from chemeascode.foundation.schema_base import Strict, unsupported_schema
from chemeascode.foundation.schemas.run import finding_dict
from chemeascode.foundation.yamlsource import _compose, _yaml_line, syntax_finding

SCHEMA = "cheme/assay/v1"
ASSAYS_FILE = "process/assays.yaml"
RECORD_FILE = "process/assay-characterization.json"
RECORD_SCHEMA = "cheme/assay-characterization/v1"
#: The version of the characterisation method: raised whenever a step or a coefficient changes,
#: so that a recorded characterisation made by another method is reported stale.
METHOD_VERSION = "1"
#: The fewest points of a TBP curve: the initial and final boiling points and three between.
MIN_POINTS = 5
#: The points of a D86 curve API procedure 3A1.1 converts, liquid volume percent distilled.
D86_POINTS = (0.0, 10.0, 30.0, 50.0, 70.0, 90.0, 100.0)
DEFAULT_PSEUDOCOMPONENTS = 8
#: Density of water at 60 °F, kg/m3 (the reference of ``chemicals.utils.SG``).
WATER_60F = 999.0170824078306

#: The correlations and definitions a characterisation uses, by id.
CORRELATIONS: dict[str, str] = {
    "d86-tbp-api-3a1.1": (
        "ASTM D86 to TBP: API Technical Data Book procedure 3A1.1 (Daubert 1994), "
        "TBP50 = 0.8718 D86_50^1.0258 and dTBP = A dD86^B per interval (degF), as given in "
        "Riazi, M.R. (2005) Characterization and Properties of Petroleum Fractions, ASTM MNL50, "
        "chapter 3"
    ),
    "tbp-equal-volume-cuts": (
        "cuts of equal liquid volume of the TBP curve (linear between the given points); a "
        "cut's normal boiling point is the curve's mean temperature over its volume"
    ),
    "constant-watson-k": (
        "Watson K = (Tb/degR)^(1/3)/SG (definition as chemicals.utils.Watson_K); the cuts of "
        "one curve share one K: the fraction's from its specific gravity and the volume-weighted "
        "cube roots of the cut boiling points (ideal mixing by volume), or the assay's"
    ),
    "riazi-daubert-1987": (
        "Riazi, M.R., Daubert, T.E. (1987) Characterization parameters for petroleum fractions, "
        "Ind. Eng. Chem. Res. 26(4) 755-759, doi:10.1021/ie00064a023: theta = a exp(b Tb + c SG "
        "+ d Tb SG) Tb^e SG^f (Tb in degR) for molar mass, Tc, Pc and the C/H weight ratio; "
        "fitted to 38 pure hydrocarbons C1-C20, M 70-300, Tb 80-650 degF"
    ),
    "lee-kesler-omega": (
        "acentric factor: Lee, B.I., Kesler, M.G. (1975) AIChE J. 21(3) 510-527, "
        "doi:10.1002/aic.690210313 (chemicals.acentric.LK_omega); the vapour-pressure form "
        "Kesler and Lee (1976, Hydrocarbon Processing 55(3) 153-158) use for Tb/Tc <= 0.8"
    ),
    "lastovka-shaw-2013": (
        "ideal-gas heat capacity: Lastovka, V., Shaw, J.M. (2013) Fluid Phase Equilib. 356 "
        "338-370, doi:10.1016/j.fluid.2013.07.023 (thermo HeatCapacityGas LASTOVKA_SHAW), "
        "from the similarity variable of the C/H composition the Riazi-Daubert C/H ratio gives"
    ),
    "peng-robinson-kij0": (
        "Peng, D.-Y., Robinson, D.B. (1976) Ind. Eng. Chem. Fundam. 15(1) 59-64, "
        "doi:10.1021/i160057a011, through thermo (PRMIX, FlashVL); no interaction parameters "
        "between pseudocomponents (kij = 0)"
    ),
}

#: Where the correlations were fitted; a pseudocomponent outside is refused (no extrapolation).
#: Riazi-Daubert (1987): Tb 80-650 degF and M 70-300 (the paper's range); SG 0.63-0.97, the
#: range of the API's Riazi-Daubert molar-mass procedure (DWSIM PropertyMethods.MW_Riazi);
#: Lee-Kesler: the vapour-pressure form for a reduced boiling point Tb/Tc <= 0.8.
RANGES: dict[str, tuple[float, float]] = {
    "normal_boiling_point_K": ((80 + 459.67) / 1.8, (650 + 459.67) / 1.8),
    "specific_gravity": (0.63, 0.97),
    "molar_mass": (70.0, 300.0),
    "reduced_boiling_point": (0.0, 0.8),
}

#: What the flash of the pseudocomponents is benchmarked for (``tests/test_assay.py``): states
#: and pseudocomponents inside these bounds, the tolerances the benchmark holds. Largest
#: deviations found: saturation temperature 1.8 K (paraffinic surrogate, bubble point at
#: 50 kPa(a)), enthalpy difference 18.2 kJ/kg (of 910 kJ/kg, vapour at 550 K), molar mass
#: 1.5 %, liquid density at 15 degC 0.15 %.
FLASH_CLAIM: dict[str, Any] = {
    "temperature_K": (300.0, 550.0),
    "pressure_kPa": (50.0, 500.0),
    "normal_boiling_point_K": (340.0, 448.0),
    "specific_gravity": (0.66, 0.875),
    "properties": [
        "bubble and dew temperatures at a given pressure",
        "enthalpy differences of liquid, saturated liquid, saturated vapour and vapour states "
        "from the liquid at 300 K and the same pressure",
        "molar mass of the mixture",
        "liquid density at 15 degC by ideal mixing of the cut gravities (not the "
        "Peng-Robinson liquid density)",
    ],
    "not_claimed": [
        "Peng-Robinson liquid density (3 % low for the surrogates; use the cut gravities)",
        "states inside the two-phase region: vapour fractions, phase compositions and "
        "enthalpies between the bubble and dew points are not compared",
        "liquid heat capacity: enthalpy differences within the liquid are low by up to 6 % "
        "of the difference (inside the absolute tolerance)",
        "pseudocomponents outside 340-448 K or SG 0.66-0.875; naphthenic and aromatic "
        "fractions are represented by one naphthene (cyclohexane) and one aromatic (toluene) "
        "only; light ends below 340 K (C5 and lighter); heavy fractions",
        "mixtures with defined compounds (water, hydrogen, light gases)",
    ],
    "tolerances": {
        "saturation_temperature_abs_K": 2.0,
        "enthalpy_difference_abs_kJ_per_kg": 20.0,
        "molar_mass_rel": 0.03,
        "liquid_density_15C_rel": 0.01,
    },
    "benchmark": {
        "test": "tests/test_assay.py",
        "reference": (
            "CoolProp 8.0.0 (HEOS) multi-fluid models of two defined naphtha surrogates "
            "(n-hexane to n-decane; n-hexane to n-nonane with cyclohexane and toluene): pure "
            "fluid reference equations of state, departure functions and parameters of "
            "Kunz-JCED-2012 (GERG-2008) for the alkane pairs and Bell-JCED-2016 for the pairs "
            "with cyclohexane or toluene; each surrogate characterised from its cuts (the "
            "normal boiling point and specific gravity of each compound from the same models)"
        ),
    },
}

TemperatureUnit = Literal["K", "°C", "°F"]


def to_kelvin(value: float, unit: str) -> float:
    if unit == "K":
        return value
    if unit == "°C":
        return value + 273.15
    if unit == "°F":
        return (value + 459.67) / 1.8
    raise ValueError(f"temperature unit {unit!r}: K, °C or °F")


# -- schema -----------------------------------------------------------------------------------


class Distillation(Strict):
    """A distillation curve: liquid volume percent distilled against temperature."""

    method: Literal["TBP", "D86"] = Field(
        description="TBP (true boiling point) or ASTM D86 (converted to TBP by API 3A1.1)"
    )
    points: list[tuple[float, float]] = Field(
        description="[liquid volume percent distilled, temperature] pairs, from 0 (initial "
        "boiling point) to 100 (final boiling point); D86: exactly 0, 10, 30, 50, 70, 90, 100"
    )


class Cut(Strict):
    """One cut of a fraction, as an assay reports it."""

    name: str | None = Field(default=None, description="Shown name, e.g. 'C7 cut'")
    liquid_volume_percent: float = Field(gt=0, le=100)
    boiling_point: float = Field(description="Normal boiling point, in temperature_unit")
    specific_gravity: float = Field(gt=0, description="60/60 °F")


class Assay(Strict):
    """One sourced assay of a petroleum fraction."""

    id: str = Field(min_length=1)
    title: str = ""
    source: str = Field(
        min_length=1, description="Where the data come from: a document, report or DOI"
    )
    temperature_unit: TemperatureUnit = Field(description="Of the curve or the cuts")
    distillation: Distillation | None = None
    cuts: list[Cut] | None = None
    specific_gravity: float | None = Field(default=None, gt=0, description="60/60 °F")
    api_gravity: float | None = None
    density_15C: float | None = Field(default=None, gt=0, description="kg/m3 at 15 °C")
    watson_k: float | None = Field(
        default=None, gt=0, description="Instead of the density: the K the cuts share"
    )
    molar_mass: float | None = Field(
        default=None, gt=0, description="Measured, g/mol: checked against the characterisation"
    )
    pseudocomponents: int | None = Field(
        default=None, ge=1, le=50, description=f"Cuts of a curve; {DEFAULT_PSEUDOCOMPONENTS}"
    )


class Assays(Strict):
    """``process/assays.yaml``."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["assays"]
    assays: list[Assay] = Field(default_factory=list)

    @model_validator(mode="after")
    def _version(self) -> Assays:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self


# -- results ----------------------------------------------------------------------------------


@dataclass
class Pseudocomponent:
    """One pseudocomponent: its identity, fractions and properties (SI: K, Pa, g/mol)."""

    identity: str
    name: str
    volume_fraction: float
    mass_fraction: float
    mole_fraction: float
    normal_boiling_point_K: float
    specific_gravity: float
    watson_k: float
    molar_mass: float
    critical_temperature_K: float
    critical_pressure_Pa: float
    acentric_factor: float
    carbon_hydrogen_ratio: float
    atoms: dict[str, float]
    similarity_variable: float
    #: property -> "given" or the id of the correlation in CORRELATIONS
    provenance: dict[str, str]


@dataclass
class Characterization:
    """An assay characterised (or refused: ``pseudocomponents`` empty, error findings)."""

    assay: str
    method_version: str
    fingerprint: str
    inputs: dict[str, Any]
    source: str
    tbp_K: list[tuple[float, float]] = field(default_factory=list)
    pseudocomponents: list[Pseudocomponent] = field(default_factory=list)
    bulk: dict[str, float] = field(default_factory=dict)
    correlations: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def refused(self) -> bool:
        return not self.pseudocomponents

    def as_dict(self) -> dict[str, Any]:
        return {
            "assay": self.assay,
            "method_version": self.method_version,
            "fingerprint": self.fingerprint,
            "source": self.source,
            "inputs": self.inputs,
            "tbp_K": [list(p) for p in self.tbp_K],
            "bulk": dict(self.bulk),
            "correlations": {c: CORRELATIONS[c] for c in self.correlations},
            "pseudocomponents": [asdict(p) for p in self.pseudocomponents],
            "findings": [finding_dict(f) for f in self.findings],
        }


@dataclass
class AssayReport:
    """The characterisations of ``process/assays.yaml`` and the file's own findings."""

    characterizations: list[Characterization]
    findings: list[Finding]
    source: SourceRevision | None = None

    def all_findings(self) -> list[Finding]:
        return self.findings + [f for c in self.characterizations for f in c.findings]


# -- D86 to TBP -------------------------------------------------------------------------------

#: API 3A1.1: (lower, upper) volume percent -> (A, B) of dTBP = A dD86^B, degF.
_D86_INTERVALS: dict[tuple[float, float], tuple[float, float]] = {
    (0.0, 10.0): (7.4012, 0.60244),
    (10.0, 30.0): (4.9004, 0.71644),
    (30.0, 50.0): (3.0305, 0.80076),
    (50.0, 70.0): (2.5282, 0.82002),
    (70.0, 90.0): (3.0419, 0.75497),
    (90.0, 100.0): (0.11798, 1.6606),
}


def d86_to_tbp(points: dict[float, float]) -> dict[float, float]:
    """The TBP temperatures (K) of ASTM D86 *points* (volume percent -> K) by API procedure
    3A1.1: the 50 % point from ``TBP50 = 0.8718 D86_50^1.0258``, the others by adding or
    subtracting ``A dD86^B`` interval by interval (degF). *points* must hold 50 and a contiguous
    run of :data:`D86_POINTS` around it; a temperature that falls back raises ``ValueError``."""
    volumes = sorted(points)
    if 50.0 not in points or any(v not in D86_POINTS for v in volumes):
        raise ValueError(f"D86 points must include 50 and be among {D86_POINTS}")
    i0, i1 = D86_POINTS.index(volumes[0]), D86_POINTS.index(volumes[-1])
    if volumes != list(D86_POINTS[i0 : i1 + 1]):
        raise ValueError("D86 points must be contiguous among the standard points")
    fahrenheit = {v: points[v] * 1.8 - 459.67 for v in volumes}
    if fahrenheit[50.0] <= 0:  # the power law in degF has no real value there
        raise ValueError(
            f"the D86 50 % point {fahrenheit[50.0]:.4g} degF is at or below 0 degF, where API "
            "3A1.1 (TBP50 = 0.8718 D86_50^1.0258, degF) does not apply"
        )
    tbp = {50.0: 0.8718 * fahrenheit[50.0] ** 1.0258}
    for lower, upper in zip(volumes, volumes[1:], strict=False):
        rise = fahrenheit[upper] - fahrenheit[lower]
        if rise < 0:
            raise ValueError(f"the D86 curve falls back between {lower:g} and {upper:g} %")
    below = [v for v in volumes if v <= 50.0]
    for lower, upper in zip(below[-2::-1], below[::-1], strict=False):
        a, b = _D86_INTERVALS[(lower, upper)]
        tbp[lower] = tbp[upper] - a * (fahrenheit[upper] - fahrenheit[lower]) ** b
    above = [v for v in volumes if v >= 50.0]
    for lower, upper in zip(above, above[1:], strict=False):
        a, b = _D86_INTERVALS[(lower, upper)]
        tbp[upper] = tbp[lower] + a * (fahrenheit[upper] - fahrenheit[lower]) ** b
    return {v: (tbp[v] + 459.67) / 1.8 for v in volumes}


# -- inputs, fingerprint, comparability --------------------------------------------------------


def inputs(assay: Assay) -> dict[str, Any]:
    """What a characterisation is made from: the assay without its id, title and source (the
    default number of pseudocomponents of a curve filled in)."""
    data = assay.model_dump(mode="json", exclude={"id", "title", "source"}, exclude_none=True)
    if assay.distillation is not None and assay.pseudocomponents is None:
        data["pseudocomponents"] = DEFAULT_PSEUDOCOMPONENTS
    return data


def fingerprint(assay: Assay) -> str:
    """The 16-hex fingerprint of :data:`METHOD_VERSION` and the assay's :func:`inputs`."""
    return value_fingerprint({"method": METHOD_VERSION, "inputs": inputs(assay)})


def _differences(a: Any, b: Any, path: str = "") -> list[str]:
    if isinstance(a, dict) and isinstance(b, dict):
        out: list[str] = []
        for key in sorted(set(a) | set(b)):
            where = f"{path}.{key}" if path else key
            if key not in a or key not in b:
                out.append(f"{where}: only in {'the first' if key in a else 'the second'}")
            else:
                out += _differences(a[key], b[key], where)
        return out
    return [] if a == b else [f"{path}: {json.dumps(a)} != {json.dumps(b)}"]


def comparability(a: Characterization, b: Characterization) -> list[str]:
    """Why results made from *a* and from *b* are not comparable (empty: same method version
    and inputs, so the same pseudocomponents)."""
    reasons = []
    if a.method_version != b.method_version:
        reasons.append(f"method version {a.method_version} != {b.method_version}")
    reasons += [f"input {d}" for d in _differences(a.inputs, b.inputs)]
    if not reasons and a.fingerprint != b.fingerprint:
        reasons.append(f"fingerprint {a.fingerprint} != {b.fingerprint}")
    return reasons


# -- checks -----------------------------------------------------------------------------------


def _specific_gravity(assay: Assay) -> float | None:
    if assay.specific_gravity is not None:
        return assay.specific_gravity
    if assay.api_gravity is not None:
        return 141.5 / (assay.api_gravity + 131.5)
    if assay.density_15C is not None:
        # 15 degC taken for 60 degF (15.56 degC): below 0.1 % for a naphtha
        return assay.density_15C / WATER_60F
    return None


def _densities(assay: Assay) -> list[str]:
    return [
        k
        for k in ("specific_gravity", "api_gravity", "density_15C")
        if getattr(assay, k) is not None
    ]


@dataclass
class _Context:
    """Where an assay is, for its findings."""

    file: str
    doc: Any
    index: int
    assay: Assay

    @property
    def basis(self) -> str:
        return "cuts" if self.assay.cuts is not None else "distillation"

    def finding(
        self, level: str, rule: str, message: str, *path: Any, hint: str = "", key: str = ""
    ) -> Finding:
        return Finding(
            self.file,
            level,  # type: ignore[arg-type]
            rule,
            f"assay {self.assay.id}: {message}",
            line=_yaml_line(self.doc, ["assays", self.index, *path]),
            ids=[self.assay.id],
            hint=hint,
            key=f"{self.assay.id}:{key}" if key else "",
        )


def _insufficient(assay: Assay, ctx: _Context) -> list[Finding]:
    """``cheme.assay-insufficient``: what the assay lacks for a characterisation."""
    rule = "cheme.assay-insufficient"
    if (assay.distillation is None) == (assay.cuts is None):
        return [
            ctx.finding(
                "error",
                rule,
                "give either a distillation curve or the cuts, not "
                + ("both" if assay.cuts is not None else "neither"),
                hint="distillation: {method, points} with the fraction's density, or cuts: "
                "[{liquid_volume_percent, boiling_point, specific_gravity}]",
                key="basis",
            )
        ]
    if assay.cuts is not None:
        return _insufficient_cuts(assay, ctx)
    found: list[Finding] = []
    curve = assay.distillation
    assert curve is not None
    densities = _densities(assay)
    if len(densities) > 1:
        found.append(
            ctx.finding(
                "error",
                rule,
                f"give one density of the fraction, not {', '.join(densities)}",
                densities[1],
                hint="keep the measured one",
                key="density",
            )
        )
    if not densities and assay.watson_k is None:
        found.append(
            ctx.finding(
                "error",
                rule,
                "no density of the fraction (specific_gravity, api_gravity or density_15C) "
                "and no watson_k",
                "distillation",
                hint="a curve alone does not fix the cut gravities; add the measured density",
                key="density",
            )
        )
    volumes = [p[0] for p in curve.points]
    temperatures = [p[1] for p in curve.points]
    where = ("distillation", "points")
    if curve.method == "D86" and volumes != list(D86_POINTS):
        found.append(
            ctx.finding(
                "error",
                rule,
                f"a D86 curve needs the points {', '.join(f'{v:g}' for v in D86_POINTS)} %, "
                f"not {', '.join(f'{v:g}' for v in volumes)}",
                *where,
                hint="API 3A1.1 converts these points only; interpolating others would invent data",
                key="points",
            )
        )
    if curve.method == "TBP" and len(volumes) < MIN_POINTS:
        found.append(
            ctx.finding(
                "error",
                rule,
                f"{len(volumes)} points; a TBP curve needs at least {MIN_POINTS}",
                *where,
                hint="give the initial and final boiling points and at least three between",
                key="points",
            )
        )
    if volumes and (volumes[0] != 0.0 or volumes[-1] != 100.0):
        found.append(
            ctx.finding(
                "error",
                rule,
                f"the curve runs from {volumes[0]} to {volumes[-1]} %, not from 0 to 100 %",
                *where,
                hint="give the initial (0 %) and final (100 %) boiling points: the curve is "
                "not extrapolated",
                key="ends",
            )
        )
    if any(b <= a for a, b in zip(volumes, volumes[1:], strict=False)):
        found.append(
            ctx.finding(
                "error",
                rule,
                "the volume percents are not strictly increasing",
                *where,
                key="order",
            )
        )
    rising = all(b >= a for a, b in zip(temperatures, temperatures[1:], strict=False))
    if not rising or (temperatures and temperatures[-1] <= temperatures[0]):
        found.append(
            ctx.finding(
                "error",
                rule,
                "the temperatures fall back (a distillation curve rises with the volume)",
                *where,
                hint="check the units and the order of the points",
                key="falls-back",
            )
        )
    return found


def _insufficient_cuts(assay: Assay, ctx: _Context) -> list[Finding]:
    rule = "cheme.assay-insufficient"
    found: list[Finding] = []
    cuts = assay.cuts or []
    total = sum(c.liquid_volume_percent for c in cuts)
    if not cuts or abs(total - 100.0) > 0.1:
        found.append(
            ctx.finding(
                "error",
                rule,
                f"the cuts add up to {total:g} % of the liquid volume, not 100 %",
                "cuts",
                hint="give every cut of the fraction; a missing cut is not extrapolated",
                key="cuts",
            )
        )
    extra = [
        k
        for k in (*_densities(assay), "watson_k", "pseudocomponents")
        if getattr(assay, k) is not None
    ]
    if extra:
        found.append(
            ctx.finding(
                "error",
                rule,
                f"{', '.join(extra)} not used with cuts (each cut has its own gravity)",
                extra[0],
                hint="remove them, or give the distillation curve instead of the cuts",
                key="cuts-extra",
            )
        )
    return found


# -- characterisation -------------------------------------------------------------------------

_RD87 = {  # Riazi-Daubert (1987), Tb-SG pairs: a, b, c, d, e, f; Tb in degR
    "molar_mass": (581.96, 5.43076e-4, -9.53384, 1.11056e-3, 0.97476, 6.51274),
    "critical_temperature_R": (10.6443, -5.1747e-4, -0.54444, 3.5995e-4, 0.81067, 0.53691),
    "critical_pressure_psia": (6.162e6, -4.725e-3, -4.8014, 3.1939e-3, -0.4844, 4.0846),
    "carbon_hydrogen_ratio": (17.22022, 8.24983e-3, 16.9402, -6.93931e-3, -2.72522, -6.79769),
}
_PSI = 6894.757293168361
_C, _H = 12.011, 1.008


def riazi_daubert(boiling_point_K: float, specific_gravity: float) -> dict[str, float]:
    """Molar mass (g/mol), critical temperature (K) and pressure (Pa) and the
    carbon-to-hydrogen weight ratio of a fraction from its normal boiling point and specific
    gravity (Riazi-Daubert 1987); no range check (:func:`characterize` does it)."""
    tb = boiling_point_K * 1.8
    sg = specific_gravity

    def theta(key: str) -> float:
        a, b, c, d, e, f = _RD87[key]
        return a * math.exp(b * tb + c * sg + d * tb * sg) * tb**e * sg**f

    return {
        "molar_mass": theta("molar_mass"),
        "critical_temperature_K": theta("critical_temperature_R") / 1.8,
        "critical_pressure_Pa": theta("critical_pressure_psia") * _PSI,
        "carbon_hydrogen_ratio": theta("carbon_hydrogen_ratio"),
    }


def _mean(curve: list[tuple[float, float]], lower: float, upper: float) -> float:
    """The mean of the piecewise linear *curve* (volume, T) over [lower, upper]."""
    total = 0.0
    for (v0, t0), (v1, t1) in zip(curve, curve[1:], strict=False):
        a, b = max(lower, v0), min(upper, v1)
        if b <= a:
            continue
        slope = (t1 - t0) / (v1 - v0)
        total += (t0 + slope * (a - v0) + t0 + slope * (b - v0)) / 2 * (b - a)
    return total / (upper - lower)


@dataclass
class _Cut:
    name: str
    volume_fraction: float
    boiling_point_K: float
    specific_gravity: float
    provenance: dict[str, str]


def _cuts(assay: Assay) -> tuple[list[_Cut], list[tuple[float, float]], float, list[str]]:
    """The cuts of an assay that passed :func:`_insufficient`: the cuts, the TBP curve (K), the
    Watson K they share (0 for given cuts) and the correlations used. ``ValueError`` for a D86
    curve the conversion refuses."""
    unit = assay.temperature_unit
    if assay.cuts is not None:
        total = sum(c.liquid_volume_percent for c in assay.cuts)
        given = {"normal_boiling_point": "given", "specific_gravity": "given"}
        cuts = [
            _Cut(
                c.name or f"{assay.id}:{n + 1}",
                c.liquid_volume_percent / total,
                to_kelvin(c.boiling_point, unit),
                c.specific_gravity,
                dict(given),
            )
            for n, c in enumerate(assay.cuts)
        ]
        return cuts, [], 0.0, []
    curve = assay.distillation
    assert curve is not None
    used = ["tbp-equal-volume-cuts", "constant-watson-k"]
    kelvin = {p[0]: to_kelvin(p[1], unit) for p in curve.points}
    if curve.method == "D86":
        kelvin = d86_to_tbp(kelvin)
        used.insert(0, "d86-tbp-api-3a1.1")
    tbp = sorted(kelvin.items())
    n = assay.pseudocomponents or DEFAULT_PSEUDOCOMPONENTS
    edges = [100.0 * i / n for i in range(n + 1)]
    boiling = [_mean(tbp, a, b) for a, b in zip(edges, edges[1:], strict=False)]
    roots = [(1.8 * t) ** (1 / 3) for t in boiling]
    sg = _specific_gravity(assay)
    k = sum(roots) / n / sg if sg is not None else float(assay.watson_k or 0.0)
    origin = "constant-watson-k" if sg is not None else "given watson_k (constant-watson-k)"
    cuts = [
        _Cut(
            f"{assay.id}:{i + 1}",
            1.0 / n,
            t,
            r / k,
            {"normal_boiling_point": "tbp-equal-volume-cuts", "specific_gravity": origin},
        )
        for i, (t, r) in enumerate(zip(boiling, roots, strict=True))
    ]
    return cuts, tbp, k, used


def _extrapolation(cut: _Cut, props: dict[str, float], ctx: _Context, n: int) -> list[Finding]:
    """``cheme.assay-extrapolation``: a pseudocomponent outside :data:`RANGES`."""
    values = {
        "normal_boiling_point_K": cut.boiling_point_K,
        "specific_gravity": cut.specific_gravity,
        "molar_mass": props["molar_mass"],
        "reduced_boiling_point": cut.boiling_point_K / props["critical_temperature_K"],
    }
    found = []
    for name, value in values.items():
        low, high = RANGES[name]
        if not low <= value <= high:
            found.append(
                ctx.finding(
                    "error",
                    "cheme.assay-extrapolation",
                    f"pseudocomponent {cut.name}: {name} {value:.4g} lies outside "
                    f"{low:.4g}-{high:.4g}, where the correlations were fitted",
                    ctx.basis,
                    hint="a fraction outside the range is not characterised (no "
                    "extrapolation); light ends and heavy fractions need another method",
                    key=f"{n + 1}:{name}",
                )
            )
    return found


def _problems(assay: Assay, ctx: _Context) -> tuple[list[Finding], tuple | None]:
    """The checks of :func:`check` and :func:`characterize`: the findings and, when there is
    no error, what the cuts gave (cuts, TBP curve, Watson K, correlations, their properties)."""
    found = _insufficient(assay, ctx)
    if any(f.level == "error" for f in found):
        return found, None
    try:
        cuts, tbp, k, used = _cuts(assay)
    except ValueError as failure:  # the D86 conversion refuses a curve that falls back
        found.append(
            ctx.finding("error", "cheme.assay-insufficient", str(failure), ctx.basis, key="d86")
        )
        return found, None
    props = [riazi_daubert(c.boiling_point_K, c.specific_gravity) for c in cuts]
    for n, (cut, p) in enumerate(zip(cuts, props, strict=True)):
        found += _extrapolation(cut, p, ctx, n)
    if any(f.level == "error" for f in found):
        return found, None
    return found, (cuts, tbp, k, used, props)


def characterize(
    assay: Assay, *, file: str = ASSAYS_FILE, doc: Any = None, index: int = 0
) -> Characterization:
    """*assay* characterised into pseudocomponents (see the module docstring), or refused with
    ``cheme.assay-insufficient``/``-extrapolation`` findings and no pseudocomponent. *doc*
    (the YAML nodes) and *index* (the assay's position) give the findings their lines. Needs
    ``chemicals`` (extra ``props``) once the checks pass."""
    ctx = _Context(file, doc, index, assay)
    result = Characterization(
        assay=assay.id,
        method_version=METHOD_VERSION,
        fingerprint=fingerprint(assay),
        inputs=inputs(assay),
        source=assay.source,
    )
    result.findings, made = _problems(assay, ctx)
    if made is None:
        return result
    cuts, tbp, k, used, props = made

    from chemicals.acentric import LK_omega
    from chemicals.elements import similarity_variable

    used = [*used, "riazi-daubert-1987", "lee-kesler-omega", "lastovka-shaw-2013"]
    mass = [c.volume_fraction * c.specific_gravity for c in cuts]
    moles = [m / p["molar_mass"] for m, p in zip(mass, props, strict=True)]
    for n, (cut, p) in enumerate(zip(cuts, props, strict=True)):
        hydrogen = p["molar_mass"] / (1.0 + p["carbon_hydrogen_ratio"])
        atoms = {"C": (p["molar_mass"] - hydrogen) / _C, "H": hydrogen / _H}
        result.pseudocomponents.append(
            Pseudocomponent(
                identity=f"pseudo:{result.fingerprint}:{n + 1}",
                name=cut.name,
                volume_fraction=cut.volume_fraction,
                mass_fraction=mass[n] / sum(mass),
                mole_fraction=moles[n] / sum(moles),
                normal_boiling_point_K=cut.boiling_point_K,
                specific_gravity=cut.specific_gravity,
                watson_k=(1.8 * cut.boiling_point_K) ** (1 / 3) / cut.specific_gravity,
                molar_mass=p["molar_mass"],
                critical_temperature_K=p["critical_temperature_K"],
                critical_pressure_Pa=p["critical_pressure_Pa"],
                acentric_factor=LK_omega(
                    cut.boiling_point_K, p["critical_temperature_K"], p["critical_pressure_Pa"]
                ),
                carbon_hydrogen_ratio=p["carbon_hydrogen_ratio"],
                atoms=atoms,
                similarity_variable=similarity_variable(atoms),
                provenance={
                    **cut.provenance,
                    "molar_mass": "riazi-daubert-1987",
                    "critical_temperature": "riazi-daubert-1987",
                    "critical_pressure": "riazi-daubert-1987",
                    "carbon_hydrogen_ratio": "riazi-daubert-1987",
                    "acentric_factor": "lee-kesler-omega",
                    "ideal_gas_heat_capacity": "lastovka-shaw-2013",
                },
            )
        )
    gravity = sum(mass)
    molar_mass = sum(mass) / sum(moles)
    result.tbp_K = tbp
    result.correlations = used
    result.bulk = {
        "specific_gravity": gravity,
        "api_gravity": 141.5 / gravity - 131.5,
        "liquid_density_15C_kg_m3": gravity * WATER_60F,
        "molar_mass": molar_mass,
        **({"watson_k": k} if k else {}),
    }
    result.findings += _consistency(assay, ctx, k, molar_mass)
    return result


def _consistency(assay: Assay, ctx: _Context, k: float, molar_mass: float) -> list[Finding]:
    """``cheme.assay-inconsistent``: a Watson K the density overrides (info), a measured molar
    mass the pseudocomponents miss by more than 5 % (warning)."""
    found = []
    if assay.watson_k is not None and _densities(assay):
        found.append(
            ctx.finding(
                "info",
                "cheme.assay-inconsistent",
                f"watson_k {assay.watson_k:g} is not used: the density fixes the cut gravities "
                f"(their shared K is {k:.3f})",
                "watson_k",
                hint="remove watson_k, or the density if K is the measured value",
                key="watson-k",
            )
        )
    if assay.molar_mass is not None:
        deviation = molar_mass / assay.molar_mass - 1.0
        if abs(deviation) > 0.05:
            found.append(
                ctx.finding(
                    "warning",
                    "cheme.assay-inconsistent",
                    f"the pseudocomponents' molar mass {molar_mass:.1f} g/mol differs from the "
                    f"measured {assay.molar_mass:g} g/mol by {deviation:+.1%}",
                    "molar_mass",
                    hint="check the curve, density and molar mass; Riazi-Daubert molar masses "
                    "of fractions deviate by about 5 % on average",
                    key="molar-mass",
                )
            )
    return found


# -- the workspace file -----------------------------------------------------------------------


def load(root: Path) -> tuple[Assays | None, Any, list[Finding]]:
    """``process/assays.yaml`` of the repository at *root*: the model, its YAML nodes and the
    findings of the file (``yaml.syntax``, ``cheme.assay-schema``, ``-duplicate-id``); None
    when the file is missing or does not follow the schema."""
    path = root / ASSAYS_FILE
    if not path.is_file():
        return None, None, []
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(ASSAYS_FILE, failure, text)]
    doc = _compose(path)
    try:
        assays = Assays.model_validate(data)
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    ASSAYS_FILE,
                    "error",
                    "cheme.assay-schema",
                    f"{SCHEMA}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema process-assays`",
                )
                for e in failure.errors()
            ],
        )
    found = []
    seen: set[str] = set()
    for i, a in enumerate(assays.assays):
        if a.id in seen:
            found.append(
                Finding(
                    ASSAYS_FILE,
                    "error",
                    "cheme.assay-duplicate-id",
                    f"assay id {a.id} is used twice",
                    line=_yaml_line(doc, ["assays", i, "id"]),
                    ids=[a.id],
                    hint="give every assay its own id",
                )
            )
        seen.add(a.id)
    return assays, doc, found


def check(root: Path) -> list[Finding]:
    """The findings of ``process/assays.yaml`` that need no optional library: the file's,
    insufficient assays and extrapolation (the correlations are evaluated, nothing else)."""
    assays, doc, found = load(root)
    for i, a in enumerate(assays.assays if assays else []):
        found += _problems(a, _Context(ASSAYS_FILE, doc, i, a))[0]
    return found


def assay_report(root: Path, ids: list[str] | None = None) -> AssayReport:
    """Every assay of ``process/assays.yaml`` (or those in *ids*) characterised, with the
    file's findings and its source revision. An id the file does not hold raises
    ``KeyError``."""
    assays, doc, found = load(root)
    known = [a.id for a in assays.assays] if assays else []
    for wanted in ids or []:
        if wanted not in known:
            raise KeyError(wanted)
    report = AssayReport(characterizations=[], findings=found)
    for i, a in enumerate(assays.assays if assays else []):
        if not ids or a.id in ids:
            report.characterizations.append(characterize(a, file=ASSAYS_FILE, doc=doc, index=i))
    report.source = source_revision(root, [ASSAYS_FILE])
    return report


# -- the record -------------------------------------------------------------------------------


def read_record(root: Path) -> dict[str, Any] | None:
    """:data:`RECORD_FILE`, or None when it is absent, not JSON or another schema."""
    path = root / RECORD_FILE
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_bytes())
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != RECORD_SCHEMA:
        return None
    return data if isinstance(data.get("assays"), dict) else None


def fill(root: Path, report: AssayReport) -> list[str]:
    """Write the characterisations of *report* that were not refused into :data:`RECORD_FILE`,
    keeping the other assays' entries; the ids written. An entry holds the characterisation
    (:meth:`Characterization.as_dict`), when and by which version it was made, and the
    revision of the assay file."""
    from chemeascode.foundation.workspace import installed_version

    data = read_record(root) or {"schema": RECORD_SCHEMA, "kind": "assay-characterization"}
    data.setdefault("assays", {})
    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tool = "cheme-as-code " + ".".join(str(n) for n in installed_version())
    written = []
    for c in report.characterizations:
        if c.refused:
            continue
        data["assays"][c.assay] = {
            "characterized_at": now,
            "tool": tool,
            **c.as_dict(),
            "file_revision": report.source.as_dict() if report.source else None,
        }
        written.append(c.assay)
    data["assays"] = dict(sorted(data["assays"].items()))
    path = root / RECORD_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return written


def record_findings(root: Path, missing: bool = False) -> list[Finding]:
    """``cheme.assay-record-stale`` (warning) for each recorded assay whose inputs or method
    version changed since, or that the assay file no longer holds; with *missing*,
    ``cheme.assay-record-missing`` (info) for an assay without an entry. Needs no optional
    library: the fingerprints are compared, nothing is characterised."""
    assays, doc, _ = load(root)
    data = read_record(root)
    if assays is None or (data is None and not missing):
        return []
    recorded = (data or {}).get("assays", {})
    found = []
    current = {a.id: (i, a) for i, a in enumerate(assays.assays)}
    for assay_id, (i, a) in current.items():
        entry = recorded.get(assay_id)
        line = _yaml_line(doc, ["assays", i, "id"])
        if entry is None:
            if missing:
                found.append(
                    Finding(
                        ASSAYS_FILE,
                        "info",
                        "cheme.assay-record-missing",
                        f"assay {assay_id}: no characterisation recorded in {RECORD_FILE}",
                        line=line,
                        ids=[assay_id],
                        hint="run `cheme process assay --fill`",
                    )
                )
            continue
        now = fingerprint(a)
        if entry.get("fingerprint") != now or entry.get("method_version") != METHOD_VERSION:
            found.append(
                Finding(
                    ASSAYS_FILE,
                    "warning",
                    "cheme.assay-record-stale",
                    f"assay {assay_id}: the recorded characterisation {entry.get('fingerprint')} "
                    f"(method {entry.get('method_version')}) was made from other inputs or by "
                    f"another method; now {now} (method {METHOD_VERSION})",
                    line=line,
                    ids=[assay_id],
                    hint="run `cheme process assay --fill`; results made from the old "
                    "pseudocomponents are not comparable with new ones",
                )
            )
    for assay_id in sorted(set(recorded) - set(current)):
        found.append(
            Finding(
                RECORD_FILE,
                "warning",
                "cheme.assay-record-stale",
                f"assay {assay_id} is recorded but no longer in {ASSAYS_FILE}",
                ids=[assay_id],
                hint="restore the assay, or run `cheme process assay --fill --prune`",
            )
        )
    return found


def prune(root: Path) -> list[str]:
    """Remove the entries of :data:`RECORD_FILE` whose assay the file no longer holds; the ids
    removed."""
    assays, _, _ = load(root)
    data = read_record(root)
    if assays is None or data is None:
        return []
    current = {a.id for a in assays.assays}
    gone = sorted(set(data["assays"]) - current)
    for assay_id in gone:
        del data["assays"][assay_id]
    if gone:
        (root / RECORD_FILE).write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return gone


def workspace_findings(root: Path, targets: set[Path] | None = None) -> tuple[list[Finding], bool]:
    """What ``cheme validate`` reports of the assays (:func:`check` and a stale record) when
    the assay file or the record is a target, and whether the assay file was read."""
    paths = [root / ASSAYS_FILE, root / RECORD_FILE]
    if not paths[0].is_file():
        return [], False
    if targets is not None and not any(p.resolve() in targets for p in paths):
        return [], False
    return check(root) + record_findings(root), True


# -- flash ------------------------------------------------------------------------------------


@dataclass
class AssayFlash:
    """A Peng-Robinson flash of a characterisation at one state; ``outside_claim`` says why the
    state or a pseudocomponent lies outside :data:`FLASH_CLAIM` (empty: inside)."""

    assay: str
    characterization: str
    method_version: str
    temperature_K: float
    pressure_kPa: float
    phase: str
    vapour_fraction: float
    vapour_mass_fraction: float
    enthalpy_J_per_kg: float
    molar_mass: float
    solver: dict[str, str]
    outside_claim: list[str]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def outside_flash_claim(
    char: Characterization, temperature_K: float | None, pressure_kPa: float
) -> list[str]:
    """Why a state (temperature None: not checked) or a pseudocomponent of *char* lies outside
    :data:`FLASH_CLAIM`; empty when inside."""
    claim = FLASH_CLAIM
    out = []
    t_lo, t_hi = claim["temperature_K"]
    p_lo, p_hi = claim["pressure_kPa"]
    if temperature_K is not None and not t_lo <= temperature_K <= t_hi:
        out.append(f"{temperature_K:.6g} K is outside {t_lo:g}-{t_hi:g} K")
    if not p_lo <= pressure_kPa <= p_hi:
        out.append(f"{pressure_kPa:.6g} kPa(a) is outside {p_lo:g}-{p_hi:g} kPa(a)")
    b_lo, b_hi = claim["normal_boiling_point_K"]
    s_lo, s_hi = claim["specific_gravity"]
    for p in char.pseudocomponents:
        if not b_lo <= p.normal_boiling_point_K <= b_hi:
            out.append(
                f"{p.name}: normal boiling point {p.normal_boiling_point_K:.1f} K is outside "
                f"{b_lo:g}-{b_hi:g} K"
            )
        if not s_lo <= p.specific_gravity <= s_hi:
            out.append(f"{p.name}: SG {p.specific_gravity:.4f} is outside {s_lo:g}-{s_hi:g}")
    return out


def _flasher(char: Characterization) -> tuple[Any, list[float]]:
    """thermo's FlashVL over the pseudocomponents (Peng-Robinson, kij = 0, Lastovka-Shaw
    ideal-gas heat capacities) and their mole fractions."""
    from thermo import (
        PRMIX,
        CEOSGas,
        CEOSLiquid,
        ChemicalConstantsPackage,
        FlashVL,
        PropertyCorrelationsPackage,
    )
    from thermo.heat_capacity import LASTOVKA_SHAW, HeatCapacityGas

    if char.refused:
        raise ValueError(f"assay {char.assay} was refused: no pseudocomponents to flash")
    ps = char.pseudocomponents
    constants = ChemicalConstantsPackage(
        names=[p.identity for p in ps],
        MWs=[p.molar_mass for p in ps],
        Tbs=[p.normal_boiling_point_K for p in ps],
        Tcs=[p.critical_temperature_K for p in ps],
        Pcs=[p.critical_pressure_Pa for p in ps],
        omegas=[p.acentric_factor for p in ps],
        atomss=[dict(p.atoms) for p in ps],
        similarity_variables=[p.similarity_variable for p in ps],
    )
    heat_capacities = [
        HeatCapacityGas(
            similarity_variable=p.similarity_variable, MW=p.molar_mass, method=LASTOVKA_SHAW
        )
        for p in ps
    ]
    correlations = PropertyCorrelationsPackage(
        constants, HeatCapacityGases=heat_capacities, skip_missing=True
    )
    n = len(ps)
    eos = {
        "Tcs": constants.Tcs,
        "Pcs": constants.Pcs,
        "omegas": constants.omegas,
        "kijs": [[0.0] * n for _ in range(n)],
    }
    gas = CEOSGas(PRMIX, eos, HeatCapacityGases=heat_capacities)
    liquid = CEOSLiquid(PRMIX, eos, HeatCapacityGases=heat_capacities)
    return FlashVL(constants, correlations, liquid=liquid, gas=gas), [p.mole_fraction for p in ps]


def _solver() -> dict[str, str]:
    import thermo

    return {"name": "thermo", "version": thermo.__version__, "method": "Peng-Robinson, kij = 0"}


def flash(char: Characterization, temperature_K: float, pressure_kPa: float) -> AssayFlash:
    """A temperature-pressure flash of the characterised fraction (its overall composition).
    The enthalpy is relative to the ideal gas at 298.15 K without formation enthalpy: use
    differences only. ``ValueError`` for a refused characterisation; needs ``thermo`` (extra
    ``props``)."""
    flasher, zs = _flasher(char)
    state = flasher.flash(T=temperature_K, P=pressure_kPa * 1e3, zs=zs)
    beta = float(state.VF)
    mass_beta = beta * state.gas.MW() / state.MW() if state.gas is not None and beta > 0 else 0.0
    phase = "vapour" if beta >= 1.0 else ("liquid" if beta <= 0.0 else "two-phase")
    return AssayFlash(
        assay=char.assay,
        characterization=char.fingerprint,
        method_version=char.method_version,
        temperature_K=temperature_K,
        pressure_kPa=pressure_kPa,
        phase=phase,
        vapour_fraction=beta,
        vapour_mass_fraction=float(mass_beta),
        enthalpy_J_per_kg=float(state.H_mass()),
        molar_mass=float(state.MW()),
        solver=_solver(),
        outside_claim=outside_flash_claim(char, temperature_K, pressure_kPa),
        notes=[
            "enthalpy relative to the ideal gas at 298.15 K without formation enthalpy: use "
            "differences",
            "kij = 0 between pseudocomponents",
        ],
    )


def saturation(char: Characterization, pressure_kPa: float) -> dict[str, Any]:
    """The bubble and dew temperatures (K) of the characterised fraction at *pressure_kPa*,
    with the characterisation fingerprint, the solver and why it lies outside the claim."""
    flasher, zs = _flasher(char)
    bubble = float(flasher.flash(P=pressure_kPa * 1e3, VF=0.0, zs=zs).T)
    dew = float(flasher.flash(P=pressure_kPa * 1e3, VF=1.0, zs=zs).T)
    outside = outside_flash_claim(char, None, pressure_kPa)
    t_lo, t_hi = FLASH_CLAIM["temperature_K"]
    for name, t in (("bubble", bubble), ("dew", dew)):
        if not t_lo <= t <= t_hi:
            outside.append(f"{name} temperature {t:.6g} K is outside {t_lo:g}-{t_hi:g} K")
    return {
        "assay": char.assay,
        "characterization": char.fingerprint,
        "method_version": char.method_version,
        "pressure_kPa": pressure_kPa,
        "bubble_temperature_K": bubble,
        "dew_temperature_K": dew,
        "solver": _solver(),
        "outside_claim": outside,
    }
