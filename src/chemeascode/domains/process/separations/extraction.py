"""``cheme process extract``: liquid-liquid extraction as equilibrium stages.

A unit of ``process/extraction.yaml`` (schema ``cheme/extraction/v1``) is one extractor: a feed
(the carrier with the solute) and a solvent feed enter a countercurrent cascade of ``stages``
equilibrium stages at one temperature (one stage: a mixer-settler). Each stage is a
liquid-liquid equilibrium (:mod:`.lle`) on NRTL with thermo's implementation
(:func:`chemeascode.integrations.thermo.nrtl_ln_gammas`) and the interaction parameters of an
**LLE system**: a bundled one (``data/lle-systems.yaml``, by ``system:``) or one the unit gives
(``model:``, with its source). The cascade is solved by alternating forward and backward stage
sweeps until the stage flows stop changing.

What it is, and what it is not:

- **predictive**: the raffinate and extract follow from the phase equilibrium, unlike a
  ``component_separator``'s given recoveries (``separations.coverage``: specified split). The
  result is evidence for a flowsheet's extractor; it does not enter ``process/simulation.yaml``,
  so the maturity report's ``predictive.model-basis`` still counts a component separator there
  as specified (the predicted split per component is reported for its ``basis_source``);
- **bounded**: a stage that holds one liquid is a failure, a feed and solvent that form one
  liquid together are refused (no two-phase region), and nothing is extrapolated: a missing
  binary pair is refused (never taken as zero) and so is a temperature outside the parameters'
  range. The result is ``qualified`` only for a bundled system with a benchmark
  (``qualification``), inside its benchmarked temperatures and solute fractions;
- **the extraction unit only**: solvent regeneration (stripping or distilling the extract, the
  raffinate's solvent recovery) is a separate unit. The solvent feed is an input with its
  composition as the regeneration returns it;
- **isothermal, liquid only**: the pressure is recorded, not used (no vapour is checked); no
  energy balance is evaluated (the parameters are fitted to tie lines, not to heats of mixing).

Inputs are findings (file, line, rule id, hint); only a wrong call (no plant repository, an
unknown unit id) raises.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.process.schema import FLOW_UNITS, CompositionValue, Quantity
from chemeascode.domains.process.separations import lle
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.schema_base import Strict
from chemeascode.foundation.schemas.run import (
    AdapterResult,
    Solver,
    StreamResult,
    UnitResult,
    finding_dict,
)
from chemeascode.foundation.units import to_kelvin
from chemeascode.foundation.yamlsource import _yaml_line, syntax_finding

SCHEMA = "cheme/extraction/v1"
EXTRACTION_FILE = "process/extraction.yaml"
SYSTEMS_FILE = Path(__file__).parents[1] / "data" / "lle-systems.yaml"
SOURCE = "cheme process extract"
#: Largest cascade solved.
MAX_STAGES = 30
#: Sum of the fractions of a composition within this of 1.
FRACTION_SUM_TOLERANCE = 1e-4
#: Stage sweeps before the cascade is reported not converged.
MAX_SWEEPS = 400
#: Largest change of a stage flow between two sweeps, relative to the total inlet flow.
SWEEP_TOLERANCE = 1e-10
#: Gas constant, J/(mol K) (CODATA 2018, exact), for parameters given in J/mol or cal/mol.
R = 8.314462618
CALORIE = 4.184

BOUNDARY = (
    "the extraction stages only: feed and solvent in, raffinate and extract out; solvent "
    "regeneration (recovering the solvent from the extract and the raffinate) is a separate unit"
)
LIMITATIONS = (
    "isothermal stages at the stated temperature; no energy balance (heats of mixing are not "
    "qualified by tie-line parameters)",
    "liquid phases only: the pressure is recorded, not used; no vapour is checked",
    "equilibrium stages: no stage efficiency, entrainment, hydrodynamics or column sizing",
)


# -- LLE systems --------------------------------------------------------------------------------


class Reference(Strict):
    """A literature source: its citation, DOI or URL, and where in it the values are."""

    citation: str
    doi: str = ""
    url: str = ""
    location: str = Field(default="", description="Table, page or section of the values")
    access: Literal["full-text", "abstract", "secondary"] = "full-text"


class LLEComponent(Strict):
    """A component of an LLE system."""

    name: str
    cas: str
    molar_mass: float = Field(gt=0, description="kg/kmol")


class NrtlPair(Strict):
    """``tau_ij = a_ij + b_ij / T + e_ij ln(T/K) + f_ij T`` (``b`` in K, J/mol or cal/mol, the
    latter two divided by R; ``f`` in 1/K), ``G_ij = exp(-alpha tau_ij)``, alpha symmetric."""

    i: str
    j: str
    a_ij: float = 0.0
    a_ji: float = 0.0
    b_ij: float
    b_ji: float
    e_ij: float = 0.0
    e_ji: float = 0.0
    f_ij: float = 0.0
    f_ji: float = 0.0
    alpha: float = Field(gt=0, le=1)


class NrtlParameters(Strict):
    """The NRTL pairs of an LLE system."""

    unit: Literal["K", "J/mol", "cal/mol"] = Field(description="Unit of b_ij and b_ji")
    pairs: list[NrtlPair] = Field(min_length=1)


class Qualification(Strict):
    """What a core test benchmarks the system against, and the range it holds over."""

    test: str
    reference: Reference
    carrier: str
    solute: str
    solvent: str
    temperature_K: tuple[float, float]
    basis: Literal["mass_fraction", "mole_fraction"]
    #: The solute fractions of each phase spanned by the benchmark tie lines.
    solute_min: dict[Literal["raffinate", "extract"], float] = Field(default_factory=dict)
    solute_max: dict[Literal["raffinate", "extract"], float]
    tolerances: dict[str, float]
    observed: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class LLESystem(Strict):
    """A set of components with sourced NRTL parameters for their liquid-liquid equilibrium."""

    id: str
    title: str = ""
    model: Literal["NRTL"] = "NRTL"
    components: list[LLEComponent] = Field(min_length=2)
    nrtl: NrtlParameters
    temperature_K: tuple[float, float] = Field(description="Range the parameters were fitted on")
    source: Reference
    qualification: Qualification | None = None

    def names(self) -> list[str]:
        return [c.name for c in self.components]

    def missing_pairs(self) -> list[tuple[str, str]]:
        names = self.names()
        given = {frozenset((p.i, p.j)) for p in self.nrtl.pairs}
        return [
            (a, b)
            for k, a in enumerate(names)
            for b in names[k + 1 :]
            if frozenset((a, b)) not in given
        ]

    def matrices(self) -> dict[str, list[list[float]]]:
        """The keyword arguments of :func:`chemeascode.integrations.thermo.nrtl_ln_gammas`:
        ``tau_a``, ``tau_b`` (K), ``alpha``, ``tau_e`` and ``tau_f`` (1/K) in the order of
        :attr:`components`."""
        index = {name: k for k, name in enumerate(self.names())}
        n = len(index)
        scale = {"K": 1.0, "J/mol": 1.0 / R, "cal/mol": CALORIE / R}[self.nrtl.unit]
        out = {
            k: [[0.0] * n for _ in range(n)] for k in ("tau_a", "tau_b", "tau_e", "tau_f", "alpha")
        }
        for p in self.nrtl.pairs:
            i, j = index[p.i], index[p.j]
            out["tau_a"][i][j], out["tau_a"][j][i] = p.a_ij, p.a_ji
            out["tau_b"][i][j], out["tau_b"][j][i] = p.b_ij * scale, p.b_ji * scale
            out["tau_e"][i][j], out["tau_e"][j][i] = p.e_ij, p.e_ji
            out["tau_f"][i][j], out["tau_f"][j][i] = p.f_ij, p.f_ji
            out["alpha"][i][j] = out["alpha"][j][i] = p.alpha
        return out

    @model_validator(mode="after")
    def _pairs_name_components(self) -> LLESystem:
        names = set(self.names())
        for p in self.nrtl.pairs:
            unknown = {p.i, p.j} - names
            if unknown or p.i == p.j:
                raise ValueError(
                    f"NRTL pair {p.i}/{p.j}: not two of the components {sorted(names)}"
                )
        return self


class _SystemsFile(Strict):
    schema_: Literal["cheme/lle-systems/v1"] = Field(alias="schema")
    systems: list[LLESystem]


@functools.cache
def bundled_systems() -> dict[str, LLESystem]:
    """The LLE systems shipped with core (``data/lle-systems.yaml``), by id."""
    data = yaml.safe_load(SYSTEMS_FILE.read_text(encoding="utf-8"))
    return {s.id: s for s in _SystemsFile.model_validate(data).systems}


# -- the plant file -----------------------------------------------------------------------------


class Feed(Strict):
    """An inlet: its flow and composition over the LLE system's components."""

    flow: Quantity = Field(description="kmol/h, kmol/s, kg/h, kg/s or t/h")
    composition: CompositionValue


class ExtractionUnit(Strict):
    """One extractor: feed and solvent feed through countercurrent equilibrium stages."""

    id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_\-]*$")
    represents: str | None = Field(
        default=None, description="The flowsheet step or block this unit evaluates (informative)"
    )
    system: str | None = Field(default=None, description="A bundled LLE system's id")
    model: LLESystem | None = Field(default=None, description="An LLE system with its source")
    stages: int = Field(ge=1, le=MAX_STAGES)
    temperature: Quantity
    pressure: Quantity | None = None
    carrier: str = Field(description="The feed's main component, the raffinate's (e.g. water)")
    solute: str
    solvent: str
    feed: Feed
    solvent_feed: Feed

    @model_validator(mode="after")
    def _one_system(self) -> ExtractionUnit:
        if (self.system is None) == (self.model is None):
            raise ValueError("give either system (a bundled LLE system) or model, not both")
        if len({self.carrier, self.solute, self.solvent}) != 3:
            raise ValueError("carrier, solute and solvent must be three different components")
        return self


class ExtractionFile(Strict):
    """Liquid-liquid extractors (process/extraction.yaml): equilibrium stages on NRTL."""

    schema_: Literal["cheme/extraction/v1"] = Field(alias="schema")
    units: list[ExtractionUnit] = Field(min_length=1)


def load(root: Path) -> tuple[ExtractionFile | None, Any, list[Finding]]:
    """``process/extraction.yaml`` of the plant at *root*, its YAML nodes and its schema
    findings; None (and no findings) without the file."""
    path = Path(root) / EXTRACTION_FILE
    if not path.is_file():
        return None, None, []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return None, None, [Finding(EXTRACTION_FILE, "error", "yaml.syntax", str(failure))]
    try:
        data = yaml.safe_load(text) or {}
        doc = yaml.compose(text)
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(EXTRACTION_FILE, failure, text)]
    try:
        return ExtractionFile.model_validate(data), doc, []
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    EXTRACTION_FILE,
                    "error",
                    "cheme.extraction-schema",
                    f"{SCHEMA}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema process-extraction`",
                )
                for e in failure.errors()
            ],
        )


# -- the cascade --------------------------------------------------------------------------------


@dataclass
class Stage:
    """One equilibrium stage: its raffinate and extract (kmol/h per component)."""

    number: int
    raffinate: list[float]
    extract: list[float]
    liquids: int
    residual: float = 0.0


@dataclass
class Cascade:
    stages: list[Stage]
    sweeps: int
    converged: bool
    change: float
    #: The stage whose equilibrium did not converge (the cascade stops there), if any.
    failed_stage: int | None = None


def countercurrent(
    model: lle.Model,
    feed: list[float],
    solvent: list[float],
    stages: int,
    carrier: int,
    max_sweeps: int = MAX_SWEEPS,
) -> Cascade:
    """*stages* countercurrent equilibrium stages: *feed* (kmol/h per component) enters stage 1
    and leaves stage N as raffinate, *solvent* enters stage N and leaves stage 1 as extract.
    The liquid richer in component *carrier* is the raffinate. A stage whose mixture holds one
    liquid passes it on whole (to the raffinate when it holds more carrier than the stage's
    other inlet, else to the extract) and is reported with ``liquids == 1``. A stage whose
    equilibrium does not converge stops the sweeps (``failed_stage``)."""
    f = np.asarray(feed, dtype=float)
    s = np.asarray(solvent, dtype=float)
    scale = float(f.sum() + s.sum())
    raff = [f.copy() for _ in range(stages)]
    extr = [s.copy() for _ in range(stages)]
    liquids = [2] * stages
    residuals = [0.0] * stages
    ln_k: list[list[float] | None] = [None] * stages
    change = float("inf")
    failed: int | None = None
    sweep = 0
    for sweep in range(1, max_sweeps + 1):
        change = 0.0
        order = range(stages) if sweep % 2 else range(stages - 1, -1, -1)
        for n in order:
            inlet_r = f if n == 0 else raff[n - 1]
            inlet_e = s if n == stages - 1 else extr[n + 1]
            mixed = inlet_r + inlet_e
            total = float(mixed.sum())
            z = mixed / total
            eq = lle.split(model, z, ln_k=ln_k[n]) if ln_k[n] is not None else None
            if eq is None or eq.liquids == 1 or not eq.converged:
                eq = lle.split(model, z)
            if not eq.converged:
                failed = n + 1
                break
            if eq.liquids == 2:
                x1, x2 = np.asarray(eq.x1), np.asarray(eq.x2)
                n1, n2 = (1.0 - eq.beta) * total * x1, eq.beta * total * x2
                new_r, new_e = (n1, n2) if x1[carrier] >= x2[carrier] else (n2, n1)
                ln_k[n] = eq.ln_k
                residuals[n] = eq.residual
            else:
                share = inlet_r[carrier] / max(float(inlet_r.sum()), 1e-300)
                other = inlet_e[carrier] / max(float(inlet_e.sum()), 1e-300)
                zero = np.zeros_like(mixed)
                new_r, new_e = (mixed, zero) if share >= other else (zero, mixed)
                ln_k[n] = None
                residuals[n] = 0.0
            liquids[n] = eq.liquids
            change = max(
                change,
                float(np.max(np.abs(new_r - raff[n]))) / scale,
                float(np.max(np.abs(new_e - extr[n]))) / scale,
            )
            raff[n], extr[n] = new_r, new_e
        if failed is not None or change < SWEEP_TOLERANCE:
            break
    result = [
        Stage(
            n + 1,
            [float(v) for v in raff[n]],
            [float(v) for v in extr[n]],
            liquids[n],
            residuals[n],
        )
        for n in range(stages)
    ]
    converged = failed is None and change < SWEEP_TOLERANCE
    return Cascade(result, sweep, converged, change, failed)


# -- one unit -----------------------------------------------------------------------------------


@dataclass
class UnitOutcome:
    """The result for one extraction unit."""

    id: str
    status: Literal["converged", "not-converged", "refused", "failed"]
    system: str = ""
    represents: str | None = None
    components: list[str] = field(default_factory=list)
    temperature_K: float | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    streams: dict[str, dict[str, Any]] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)
    closure: dict[str, Any] = field(default_factory=dict)
    energy: dict[str, Any] = field(default_factory=dict)
    qualification: dict[str, Any] = field(default_factory=dict)
    model: dict[str, Any] = field(default_factory=dict)
    sweeps: int | None = None
    messages: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))
    boundary: str = BOUNDARY
    basis: str = "equilibrium-stage"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "basis": self.basis,
            "represents": self.represents,
            "system": self.system,
            "components": self.components,
            "temperature_K": self.temperature_K,
            "model": self.model,
            "qualification": self.qualification,
            "performance": self.performance,
            "closure": self.closure,
            "energy": self.energy,
            "streams": self.streams,
            "stages": self.stages,
            "sweeps": self.sweeps,
            "boundary": self.boundary,
            "limitations": self.limitations,
            "messages": self.messages,
            "findings": [finding_dict(f) for f in self.findings],
        }


class _Refusal(Exception):
    def __init__(self, rule: str, message: str, loc: list[Any], hint: str) -> None:
        super().__init__(message)
        self.rule, self.message, self.loc, self.hint = rule, message, loc, hint


def _molar_flows(feed: Feed, system: LLESystem, where: list[Any]) -> np.ndarray:
    """kmol/h per component of the system."""
    names = system.names()
    mass = np.array([c.molar_mass for c in system.components])
    values = feed.composition.values
    unknown = sorted(set(values) - set(names))
    if unknown:
        raise _Refusal(
            "cheme.extraction-component",
            f"{', '.join(unknown)}: not a component of LLE system {system.id} ({', '.join(names)})",
            [*where, "composition", "values"],
            "use the system's component names, or a system that holds these components",
        )
    fractions = np.array([float(values.get(n, 0.0)) for n in names])
    if (fractions < 0).any() or abs(fractions.sum() - 1.0) > FRACTION_SUM_TOLERANCE:
        raise _Refusal(
            "cheme.extraction-composition",
            f"fractions sum to {fractions.sum():.6g}, not 1 (or a fraction is negative)",
            [*where, "composition", "values"],
            f"give fractions that sum to 1 within {FRACTION_SUM_TOLERANCE:g}",
        )
    fractions = fractions / fractions.sum()
    unit = feed.flow.unit or ""
    kind, factor = FLOW_UNITS.get(unit, (None, None))
    if kind not in ("mass", "mole") or feed.flow.value <= 0:
        raise _Refusal(
            "cheme.extraction-flow",
            f"flow {feed.flow.value:g} {unit}: give a positive flow in kmol/h, kmol/s, kg/h, kg/s "
            "or t/h",
            [*where, "flow"],
            "state the flow on a mass or molar basis",
        )
    if feed.composition.basis == "mass_fraction":
        moles_per_kg = fractions / mass
        mole_fractions = moles_per_kg / moles_per_kg.sum()
        mean_mass = 1.0 / moles_per_kg.sum()
    else:
        mole_fractions = fractions
        mean_mass = float(fractions @ mass)
    flow = feed.flow.value * factor
    kmol_h = flow if kind == "mole" else flow / mean_mass
    return kmol_h * mole_fractions


def _stream(flows: list[float] | np.ndarray, system: LLESystem) -> dict[str, Any]:
    names = system.names()
    n = np.asarray(flows, dtype=float)
    kg = n * np.array([c.molar_mass for c in system.components])
    total, total_kg = float(n.sum()), float(kg.sum())
    return {
        "flow_kmol_h": total,
        "flow_kg_h": total_kg,
        "component_kmol_h": dict(zip(names, (float(v) for v in n), strict=True)),
        "mole_fraction": {
            k: (float(v) / total if total else 0.0) for k, v in zip(names, n, strict=True)
        },
        "mass_fraction": {
            k: (float(v) / total_kg if total_kg else 0.0) for k, v in zip(names, kg, strict=True)
        },
    }


def _ratio(a: float, b: float) -> float | None:
    return a / b if b > 0 else None


def _stage_figures(raff: dict, extr: dict, carrier: str, solute: str) -> dict[str, Any]:
    """Distribution coefficient (mass and mole basis) and selectivity of one stage."""
    wr, we = raff["mass_fraction"], extr["mass_fraction"]
    xr, xe = raff["mole_fraction"], extr["mole_fraction"]
    d_mass = _ratio(we[solute], wr[solute])
    d_mole = _ratio(xe[solute], xr[solute])
    d_carrier = _ratio(we[carrier], wr[carrier])
    return {
        "distribution_mass": d_mass,
        "distribution_mole": d_mole,
        "selectivity": (d_mass / d_carrier) if d_mass is not None and d_carrier else None,
    }


def _system_of(unit: ExtractionUnit) -> LLESystem:
    if unit.model is not None:
        return unit.model
    systems = bundled_systems()
    if unit.system not in systems:
        raise _Refusal(
            "cheme.extraction-system",
            f"no bundled LLE system {unit.system!r} (known: {', '.join(sorted(systems))})",
            ["system"],
            "name a bundled system (`cheme process extract --systems`) or give model: with "
            "sourced NRTL parameters",
        )
    return systems[unit.system]


def evaluate_unit(
    unit: ExtractionUnit, loc: list[Any] | None = None, doc: Any = None
) -> UnitOutcome:
    """Solve one extraction unit. *loc* is the unit's place in the YAML file and *doc* its node
    tree, for the findings' lines."""
    loc = loc or []
    out = UnitOutcome(unit.id, "refused", represents=unit.represents)

    def refuse(refusal: _Refusal) -> UnitOutcome:
        out.status = "refused"
        out.messages.append(refusal.message)
        out.findings.append(
            Finding(
                EXTRACTION_FILE,
                "error",
                refusal.rule,
                f"{unit.id}: {refusal.message}",
                line=_yaml_line(doc, [*loc, *refusal.loc]) if doc is not None else None,
                ids=[unit.id],
                hint=refusal.hint,
            )
        )
        return out

    try:
        system = _system_of(unit)
        out.system = system.id
        out.components = system.names()
        out.model = _model_dict(system, bundled=unit.model is None)
        names = system.names()
        for role in ("carrier", "solute", "solvent"):
            if getattr(unit, role) not in names:
                raise _Refusal(
                    "cheme.extraction-component",
                    f"{role} {getattr(unit, role)!r} is not a component of LLE system "
                    f"{system.id} ({', '.join(names)})",
                    [role],
                    "name one of the system's components",
                )
        missing = system.missing_pairs()
        if missing:
            raise _Refusal(
                "cheme.extraction-parameters",
                "no NRTL parameters for "
                + ", ".join(f"{a}/{b}" for a, b in missing)
                + ": a missing pair is not taken as zero",
                ["model", "nrtl", "pairs"],
                "give every binary pair with its source, or use a system that has them",
            )
        temperature = to_kelvin(unit.temperature.value, unit.temperature.unit or "")
        if temperature is None:
            raise _Refusal(
                "cheme.extraction-temperature",
                f"temperature unit {unit.temperature.unit!r}: give K or °C",
                ["temperature"],
                "write the temperature in K or °C",
            )
        out.temperature_K = temperature
        lo, hi = system.temperature_K
        if not lo - 0.05 <= temperature <= hi + 0.05:
            raise _Refusal(
                "cheme.extraction-temperature",
                f"{temperature:.2f} K is outside the range of the {system.id} parameters "
                f"({lo:g}-{hi:g} K): LLE parameters are not extrapolated",
                ["temperature"],
                "operate inside the parameters' range or give parameters fitted at this "
                "temperature",
            )
        feed = _molar_flows(unit.feed, system, ["feed"])
        solvent = _molar_flows(unit.solvent_feed, system, ["solvent_feed"])
        from chemeascode.integrations.thermo import nrtl_ln_gammas

        try:
            model = nrtl_ln_gammas(temperature, **system.matrices())
        except ValueError as failure:
            raise _Refusal("cheme.extraction-backend", str(failure), [], str(failure)) from None
        overall = lle.split(model, (feed + solvent) / float((feed + solvent).sum()))
        # a search that did not converge is not evidence of one liquid: the cascade's stages
        # then report it (not-converged)
        if overall.liquids == 1 and overall.converged:
            raise _Refusal(
                "cheme.extraction-one-liquid",
                f"feed and solvent form one liquid at {temperature:.2f} K (no two-phase region "
                "at their overall composition): there is nothing to extract into",
                ["solvent_feed"],
                "change the solvent-to-feed ratio, the solvent or the temperature; check the "
                "binodal of the system",
            )
    except _Refusal as refusal:
        return refuse(refusal)

    idx = {name: k for k, name in enumerate(names)}
    cascade = countercurrent(model, list(feed), list(solvent), unit.stages, idx[unit.carrier])
    out.sweeps = cascade.sweeps
    stage_rows = []
    for stage in cascade.stages:
        raff, extr = _stream(stage.raffinate, system), _stream(stage.extract, system)
        stage_rows.append(
            {
                "stage": stage.number,
                "liquids": stage.liquids,
                "iso_activity_residual": stage.residual,
                "raffinate": raff,
                "extract": extr,
                **(
                    _stage_figures(raff, extr, unit.carrier, unit.solute)
                    if stage.liquids == 2
                    else {}
                ),
            }
        )
    out.stages = stage_rows
    raffinate = np.asarray(cascade.stages[-1].raffinate)
    extract = np.asarray(cascade.stages[0].extract)
    out.streams = {
        "feed": _stream(feed, system),
        "solvent_feed": _stream(solvent, system),
        "raffinate": _stream(raffinate, system),
        "extract": _stream(extract, system),
    }
    inlet = feed + solvent
    imbalance = inlet - raffinate - extract
    out.closure = {
        "status": "closed",
        "max_relative_component_imbalance": float(
            np.max(np.abs(imbalance) / np.maximum(inlet, 1e-300 + inlet.sum() * 1e-12))
        ),
        "overall_relative_imbalance": float(abs(imbalance.sum()) / inlet.sum()),
        "tolerance": 1e-8,
    }
    if out.closure["max_relative_component_imbalance"] > 1e-8:
        out.closure["status"] = "open"
    out.energy = {
        "status": "not-evaluated",
        "reason": "isothermal stages at the stated temperature; the NRTL parameters are fitted "
        "to tie lines, so the heat of mixing they imply is not qualified and no duty is given",
    }
    s, c, v = idx[unit.solute], idx[unit.carrier], idx[unit.solvent]
    mass = np.array([cmp.molar_mass for cmp in system.components])
    split_to_extract = {
        name: (float(extract[k] / inlet[k]) if inlet[k] > 0 else None)
        for k, name in enumerate(names)
    }
    first, last = stage_rows[0], stage_rows[-1]
    out.performance = {
        "solute_recovery": _ratio(float(extract[s]), float(feed[s])),
        "solvent_loss_fraction": _ratio(float(raffinate[v]), float(solvent[v])),
        "solvent_loss_kg_h": float(raffinate[v] * mass[v]),
        "carrier_to_extract_fraction": _ratio(float(extract[c]), float(inlet[c])),
        "solvent_to_feed_mass_ratio": float(solvent @ mass) / float(feed @ mass),
        "distribution_mass": {
            "stage_1": first.get("distribution_mass"),
            f"stage_{unit.stages}": last.get("distribution_mass"),
        },
        "selectivity": {
            "stage_1": first.get("selectivity"),
            f"stage_{unit.stages}": last.get("selectivity"),
        },
        "split_to_extract": split_to_extract,
    }
    one_liquid = [st.number for st in cascade.stages if st.liquids == 1]
    if one_liquid:
        out.status = "failed"
        out.messages.append(f"stage(s) {', '.join(map(str, one_liquid))} hold one liquid")
        out.findings.append(
            Finding(
                EXTRACTION_FILE,
                "error",
                "cheme.extraction-stage-one-liquid",
                f"{unit.id}: stage(s) {', '.join(map(str, one_liquid))} of {unit.stages} hold one "
                "liquid at the converged flows: the cascade leaves the two-phase region",
                line=_yaml_line(doc, [*loc, "stages"]) if doc is not None else None,
                ids=[unit.id],
                hint="change the solvent-to-feed ratio or the number of stages",
            )
        )
    elif not cascade.converged:
        out.status = "not-converged"
        out.messages.append(
            f"the equilibrium of stage {cascade.failed_stage} did not converge"
            if cascade.failed_stage is not None
            else f"stage flows still change by {cascade.change:.2e} (relative) after "
            f"{cascade.sweeps} sweeps"
        )
        out.findings.append(
            Finding(
                EXTRACTION_FILE,
                "error",
                "cheme.extraction-not-converged",
                f"{unit.id}: the cascade did not converge in {cascade.sweeps} sweeps",
                line=_yaml_line(doc, [*loc, "stages"]) if doc is not None else None,
                ids=[unit.id],
                hint="fewer stages, or a solvent ratio away from the plait point",
            )
        )
    elif out.closure["status"] != "closed":
        out.status = "failed"
        out.messages.append("the component balance does not close")
    else:
        out.status = "converged"
    out.qualification = _qualification(system, unit, out, bundled=unit.model is None)
    return out


def _model_dict(system: LLESystem, bundled: bool) -> dict[str, Any]:
    from importlib.metadata import PackageNotFoundError, version

    from chemeascode.foundation.workspace import installed_version

    try:
        thermo_version = version("thermo")
    except PackageNotFoundError:
        thermo_version = None
    return {
        "name": "NRTL",
        "backend": "thermo",
        "backend_version": thermo_version,
        "core_version": ".".join(str(n) for n in installed_version()),
        "parameters": "bundled" if bundled else "plant file (model:)",
        "parameter_source": system.source.model_dump(mode="json"),
        "parameter_temperature_K": list(system.temperature_K),
    }


def _qualification(
    system: LLESystem, unit: ExtractionUnit, out: UnitOutcome, bundled: bool
) -> dict[str, Any]:
    q = system.qualification
    if not bundled or q is None:
        why = (
            "parameters from the plant file: not benchmarked in core"
            if not bundled
            else f"bundled system {system.id} has no benchmark"
        )
        return {"status": "unqualified", "reasons": [why]}
    reasons = []
    if out.status != "converged":
        reasons.append(f"the unit is {out.status}")
    t = out.temperature_K or 0.0
    lo, hi = q.temperature_K
    if not lo - 0.05 <= t <= hi + 0.05:
        reasons.append(f"{t:.2f} K outside the benchmarked {lo:g}-{hi:g} K")
    key = "mass_fraction" if q.basis == "mass_fraction" else "mole_fraction"
    for row in out.stages:
        for phase in ("raffinate", "extract"):
            value = row[phase][key][unit.solute]
            if value > q.solute_max[phase] + 1e-9:
                reasons.append(
                    f"stage {row['stage']} {phase}: solute {q.basis} {value:.4f} above the "
                    f"largest benchmarked {q.solute_max[phase]:.4f}"
                )
            low = q.solute_min.get(phase)
            if low is not None and value < low - 1e-9:
                reasons.append(
                    f"stage {row['stage']} {phase}: solute {q.basis} {value:.4f} below the "
                    f"smallest benchmarked {low:.4f}"
                )
    if (unit.carrier, unit.solute, unit.solvent) != (q.carrier, q.solute, q.solvent):
        reasons.append(
            f"the benchmark tests {q.solute} from {q.carrier} into {q.solvent}, not these roles"
        )
    return {
        "status": "unqualified" if reasons else "qualified",
        "reasons": reasons,
        "benchmark": q.test,
        "reference": q.reference.model_dump(mode="json"),
        "tolerances": q.tolerances,
        "observed": q.observed,
    }


# -- the report ---------------------------------------------------------------------------------


@dataclass
class ExtractionReport:
    units: list[UnitOutcome] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    source: SourceRevision | None = None

    @property
    def ok(self) -> bool:
        return not any(f.level == "error" for f in self.findings) and all(
            u.status == "converged" for u in self.units
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": "cheme/extraction-result/v1",
            "units": [u.as_dict() for u in self.units],
            "findings": [finding_dict(f) for f in self.findings],
            "source": self.source.as_dict() if self.source else None,
        }

    def adapter_results(self) -> list[AdapterResult]:
        """One adapter result (``cheme/adapter-result/v1``) per unit; ``case`` is the unit."""
        from chemeascode.foundation.workspace import installed_version

        version = ".".join(str(n) for n in installed_version())
        inputs = self.source.as_dict() if self.source else {}
        results = []
        for u in self.units:
            results.append(
                AdapterResult(
                    case=u.id,
                    status=u.status,
                    solver=Solver(
                        name=SOURCE,
                        version=version,
                        method=f"NRTL ({u.model.get('backend', 'thermo')} "
                        f"{u.model.get('backend_version') or '?'}), system {u.system or '?'}",
                    ),
                    inputs=inputs,
                    iterations=u.sweeps,
                    messages=u.messages,
                    units=[
                        UnitResult(
                            id=u.id,
                            status="simulated" if u.status == "converged" else u.status,
                            converged=u.status == "converged",
                            results={
                                k: v
                                for k, v in u.as_dict().items()
                                if k not in ("streams", "findings", "messages", "id", "status")
                            },
                        )
                    ],
                    streams=[
                        StreamResult(id=f"{u.id}.{name}", values=values)
                        for name, values in u.streams.items()
                        if name in ("raffinate", "extract")
                    ],
                    findings=[finding_dict(f) for f in u.findings],
                )
            )
        return results


def extraction_report(root: Path, unit: str | None = None) -> ExtractionReport:
    """Every unit of ``process/extraction.yaml`` (or the one named *unit*) of the plant at
    *root*. Raises FileNotFoundError without the file and KeyError for an unknown unit id."""
    root = Path(root)
    if not (root / EXTRACTION_FILE).is_file():
        raise FileNotFoundError(f"{EXTRACTION_FILE} does not exist")
    spec, doc, findings = load(root)
    report = ExtractionReport(findings=list(findings))
    report.source = source_revision(root, [EXTRACTION_FILE])
    if spec is None:
        return report
    ids = [u.id for u in spec.units]
    if unit is not None and unit not in ids:
        raise KeyError(f"no unit {unit!r} in {EXTRACTION_FILE} (units: {', '.join(ids)})")
    seen: set[str] = set()
    for k, u in enumerate(spec.units):
        if u.id in seen:
            report.findings.append(
                Finding(
                    EXTRACTION_FILE,
                    "error",
                    "cheme.extraction-duplicate",
                    f"unit id {u.id} is declared twice",
                    line=_yaml_line(doc, ["units", k, "id"]),
                    ids=[u.id],
                    hint="give each unit its own id",
                )
            )
            continue
        seen.add(u.id)
        if unit is not None and u.id != unit:
            continue
        outcome = evaluate_unit(u, ["units", k], doc)
        report.units.append(outcome)
        report.findings.extend(outcome.findings)
    return report


def _fmt(value: float | None, spec: str = ".4g") -> str:
    return "-" if value is None else format(value, spec)


def extraction_text(report: ExtractionReport) -> str:
    """The report as text, one block per unit."""
    lines: list[str] = []
    for u in report.units:
        lines.append(
            f"{u.id}: {u.status}, {len(u.stages) or '?'} equilibrium stage(s), system "
            f"{u.system or '?'}"
            + (f", {u.temperature_K:.2f} K" if u.temperature_K else "")
            + (f" (represents {u.represents})" if u.represents else "")
        )
        if u.performance:
            p = u.performance
            lines.append(
                f"  solute recovery {_fmt(p['solute_recovery'])}, solvent loss "
                f"{_fmt(p['solvent_loss_fraction'])} ({_fmt(p['solvent_loss_kg_h'])} kg/h), "
                f"S/F {_fmt(p['solvent_to_feed_mass_ratio'])} (mass)"
            )
            d, sel = p["distribution_mass"], p["selectivity"]
            lines.append(
                "  distribution (mass) "
                + ", ".join(f"{k} {_fmt(v)}" for k, v in d.items())
                + "; selectivity "
                + ", ".join(f"{k} {_fmt(v)}" for k, v in sel.items())
            )
            for name in ("raffinate", "extract"):
                st = u.streams[name]
                lines.append(
                    f"  {name}: {st['flow_kg_h']:.6g} kg/h, mass fractions "
                    + ", ".join(f"{k} {v:.4f}" for k, v in st["mass_fraction"].items())
                )
            lines.append(
                f"  closure {u.closure['status']} (max relative component imbalance "
                f"{u.closure['max_relative_component_imbalance']:.1e}); energy "
                f"{u.energy['status']}"
            )
        q = u.qualification
        if q:
            lines.append(
                f"  qualification: {q['status']}"
                + (f" ({'; '.join(q['reasons'])})" if q.get("reasons") else "")
            )
        for message in u.messages:
            lines.append(f"  {message}")
        lines.append(f"  boundary: {u.boundary}")
    for finding in report.findings:
        lines.append(finding.format())
    return "\n".join(lines)


def systems_table() -> list[dict[str, Any]]:
    """The bundled LLE systems: components, parameter source, range and qualification."""
    rows = []
    for s in bundled_systems().values():
        q = s.qualification
        rows.append(
            {
                "id": s.id,
                "title": s.title,
                "components": s.names(),
                "temperature_K": list(s.temperature_K),
                "source": s.source.citation,
                "qualified": q is not None,
                "benchmark": q.test if q else None,
                "reference": q.reference.citation if q else None,
                "solute_min": dict(q.solute_min) if q else None,
                "solute_max": dict(q.solute_max) if q else None,
                "tolerances": q.tolerances if q else None,
            }
        )
    return rows
