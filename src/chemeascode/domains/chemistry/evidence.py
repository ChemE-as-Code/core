"""Schema ``cheme/reaction-evidence/v1`` (``process/reaction-evidence.yaml``): the sourced
evidence behind a process's reactions, the candidate routes it supports and the model basis
chosen from it.

The file is written while the reaction set is still open, before ``process/reactions.yaml``
holds the model: the searches run (query, tool, date), the sources found (DOI or patent
publication number, access reached, reuse conditions), one observation per experiment or
operating example (its exact location in the source, the conditions, conversion, selectivity
and yield kept apart, the kinetics as reported), the candidate routes, the conflicts between
sources, and the ``model_basis``: which route, reactions and evidence the engineering model
uses, and what it assumes beyond the evidence. Every number states whether the source
reports it, it is derived from reported values, or it is assumed; a value the source does not
give is listed under ``missing``, never filled in.

Rules (``cheme.evidence-*``), each finding naming the file, line, rule and a hint:

- ``evidence-schema``: the file does not follow ``cheme/reaction-evidence/v1``;
- ``evidence-duplicate-id``: two sources, routes or observations with one id;
- ``evidence-reference``: an observation, conflict, search or the model basis naming a source,
  route or observation the file does not declare;
- ``evidence-identity``: a malformed DOI or patent publication number, a patent without its
  number, a paper with neither DOI nor URL (warning);
- ``evidence-location``: an observation reporting values without the page, table, figure or
  example they are on;
- ``evidence-access``: reported values from a source only seen as a search snippet, or not
  accessed at all; a snippet does not establish a numerical claim;
- ``evidence-unit``: a temperature, pressure, time or fraction in a unit this file does not
  read, or a fraction outside 0 to 1;
- ``evidence-yield-basis`` (warning): a yield that does not say isolated or analytical, or a
  yield or selectivity without the reactant it is relative to;
- ``evidence-yield-conversion`` (warning): a molar yield above the conversion of the reactant it
  is relative to, in one observation: the bases are mixed up;
- ``evidence-duplicate`` (warning): two observations at one location of one source;
- ``evidence-kinetics`` (warning): kinetics without a rate basis or a validity range;
- ``evidence-model-basis``: a selected route without a model basis, more than one selected
  route, a model basis on a route that is not selected or without evidence; (warning) model
  evidence from another route, or pooled from observations on different catalysts;
- ``evidence-component``, ``evidence-reaction``, ``evidence-catalyst``: an id that
  ``process/materials.yaml``, ``reactions.yaml`` or ``catalysts.yaml`` does not declare
  (components and catalysts: warnings, and only when that file exists; the model basis's
  reactions: errors);
- ``evidence-handoff`` (info): a model reaction whose given conversion, heat of reaction or
  rate cites none of the model basis's observations.

The functions take the declared ids as plain sets, so that they need nothing from the process
domain; :mod:`chemeascode.project.evidence` reads the plant's files.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from chemeascode.domains.chemistry.reactions import REACTIONS_FILE, Reaction
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.schema_base import Strict, unsupported_schema
from chemeascode.foundation.units import PRESSURE_UNITS, TEMPERATURE_UNITS, to_kelvin, to_kpa_abs
from chemeascode.foundation.yamlsource import _yaml_line, syntax_finding

SCHEMA = "cheme/reaction-evidence/v1"
EVIDENCE_FILE = "process/reaction-evidence.yaml"

#: DOI: ``10.<registrant>/<suffix>`` (no ``doi:`` or URL prefix).
DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
#: Patent publication number: office, an optional series (US reissue RE, a Japanese era
#: letter), the number (a year and a dash allowed) and the kind code, e.g. US7652167B2,
#: EP0757027A1, USRE45678E, JPH0812345A, JP2000-123456A.
PATENT_RE = re.compile(r"^[A-Z]{2}[A-Z]{0,2}\d[\d-]{2,14}(?:[A-Z]\d?)?$")
#: Units of a fraction (conversion, selectivity, yield) and their factor to a fraction.
FRACTION_UNITS = {"%": 0.01, "1": 1.0}
#: Units of a residence or contact time, and their factor to s.
TIME_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0}

ValueStatus = Literal["reported", "derived", "assumed"]
Access = Literal["full-text", "abstract", "snippet", "unavailable"]


# -- schema -------------------------------------------------------------------------------------


class Value(Strict):
    """One number from a source, or a range: ``value`` or ``range`` (min, max), in ``unit``.

    ``reported``: the source states it at ``location``; ``derived``: computed from reported
    values (``derived_from`` says how); ``assumed``: not in the source (``note`` says why)."""

    value: float | None = None
    range: tuple[float, float] | None = None
    unit: str = Field(description="As reported; '1' for a dimensionless number or fraction.")
    status: ValueStatus = "reported"
    derived_from: str = ""
    uncertainty: float | None = Field(
        default=None, ge=0, description="Plus or minus, in unit, where the source gives one."
    )
    note: str = ""

    @model_validator(mode="after")
    def _shape(self) -> Value:
        if (self.value is None) == (self.range is None):
            raise ValueError("give value or range (min, max), not both")
        if self.range is not None and not self.range[0] <= self.range[1]:
            raise ValueError("range is (min, max) with min <= max")
        if self.status == "derived" and not self.derived_from.strip():
            raise ValueError("a derived value says how in derived_from")
        if self.status == "assumed" and not self.note.strip():
            raise ValueError("an assumed value says why in note")
        return self

    def bounds(self) -> tuple[float, float]:
        if self.range is not None:
            return self.range
        assert self.value is not None
        return self.value, self.value


class Source(Strict):
    """A paper, patent, review, handbook, database entry, report, thesis or web page."""

    id: str
    kind: Literal["paper", "patent", "review", "handbook", "database", "report", "thesis", "web"]
    title: str = ""
    authors: str = ""
    year: int | None = Field(default=None, ge=1800, le=2100)
    doi: str = Field(default="", description="10.xxxx/..., without doi: or https://doi.org/")
    patent: str = Field(default="", description="Publication number with kind code: US7652167B2")
    url: str = ""
    accessed: dt.date = Field(description="When it was read (ISO date).")
    access: Access = Field(
        description="What was read: full-text, abstract, snippet (a search result only) or "
        "unavailable (paywalled, not found)."
    )
    reuse: str = Field(
        default="",
        description="Licence or reuse conditions (CC BY 4.0; copyrighted: facts and citation "
        "only). The file stores citations and extracted facts, not the document.",
    )
    notes: str = ""


class Search(Strict):
    """One query run with an agent's search tool."""

    query: str
    tool: str = Field(description="The tool or service used (web search, patent search, ...).")
    date: dt.date
    status: Literal["done", "no-results", "unavailable"] = Field(
        default="done", description="unavailable: the tool or the service could not be used."
    )
    found: list[str] = Field(default_factory=list, description="Source ids it led to.")
    notes: str = ""


class Conversion(Strict):
    component: str = Field(description="The reactant converted (component id).")
    value: Value
    basis: Literal["per-pass", "overall", "equilibrium"] | None = None
    measurement: str = Field(default="", description="How it was measured (GC, titration).")


class Selectivity(Strict):
    product: str
    value: Value
    relative_to: str = Field(default="", description="The converted reactant (denominator).")
    basis: Literal["molar", "carbon", "mass"] | None = None
    measurement: str = ""


class Yield(Strict):
    product: str
    value: Value
    type: Literal["isolated", "analytical"] | None = None
    relative_to: str = Field(default="", description="The reactant fed (denominator).")
    basis: Literal["molar", "carbon", "mass"] | None = None
    measurement: str = ""


class Conditions(Strict):
    temperature: Value | None = None
    pressure: Value | None = None
    phase: Literal["gas", "liquid", "mixed", "supercritical"] | None = None
    solvent: str = ""
    catalyst: str = Field(default="", description="An id of process/catalysts.yaml.")
    catalyst_formulation: str = Field(default="", description="As the source describes it.")
    catalyst_loading: Value | None = None
    feed: dict[str, Value] = Field(
        default_factory=dict, description="Component id -> amount, ratio or fraction."
    )
    residence_time: Value | None = None
    contact_time: Value | None = None
    space_velocity: Value | None = None
    notes: str = ""


class KineticsEvidence(Strict):
    """A rate law as the source reports it, before it becomes a ``rate:`` of reactions.yaml."""

    equation: str = Field(description="As written in the source.")
    rate_basis: str = Field(default="", description="Per kg of catalyst, per m3 of liquid, ...")
    parameters: dict[str, Value] = Field(default_factory=dict)
    temperature_range: Value | None = None
    pressure_range: Value | None = None
    fitting: str = Field(default="", description="Data, reactor and method of the fit.")


class Observation(Strict):
    """One experiment or operating example of one source, with its context."""

    id: str
    source: str
    route: str
    location: str = Field(
        default="", description="Page, table, figure, paragraph or patent example."
    )
    kind: Literal["experiment", "operating-example", "review-summary", "kinetics", "equilibrium"]
    scale: Literal["lab", "pilot", "industrial", "patent-example", "computational"] | None = None
    equation: str = ""
    conditions: Conditions | None = None
    conversion: list[Conversion] = Field(default_factory=list)
    selectivity: list[Selectivity] = Field(default_factory=list)
    yields: list[Yield] = Field(default_factory=list, alias="yield")
    outlet: dict[str, Value] = Field(
        default_factory=dict,
        description="Component -> outlet or product composition as reported (wt %, mol %).",
    )
    byproducts: list[str] = Field(default_factory=list)
    separation: str = Field(default="", description="Separation and recycle context reported.")
    kinetics: KineticsEvidence | None = None
    missing: list[str] = Field(
        default_factory=list, description="What the source does not report (left unfilled)."
    )
    notes: str = ""

    def values(self) -> list[tuple[list[Any], str, Value]]:
        """Every value of the observation: its location below the observation, what it is
        (``temperature``, ``pressure``, ``time``, ``fraction`` or ``other``) and the value."""
        found: list[tuple[list[Any], str, Value]] = []
        if self.conditions is not None:
            c = self.conditions
            for name, kind in (
                ("temperature", "temperature"),
                ("pressure", "pressure"),
                ("catalyst_loading", "other"),
                ("residence_time", "time"),
                ("contact_time", "time"),
                ("space_velocity", "other"),
            ):
                if getattr(c, name) is not None:
                    found.append((["conditions", name], kind, getattr(c, name)))
            found += [(["conditions", "feed", k], "other", v) for k, v in c.feed.items()]
        found += [(["outlet", k], "other", v) for k, v in self.outlet.items()]
        for key, items in (
            ("conversion", self.conversion),
            ("selectivity", self.selectivity),
            ("yield", self.yields),
        ):
            found += [([key, i, "value"], "fraction", item.value) for i, item in enumerate(items)]
        if self.kinetics is not None:
            k = self.kinetics
            found += [(["kinetics", "parameters", n], "other", v) for n, v in k.parameters.items()]
            for name, kind in (
                ("temperature_range", "temperature"),
                ("pressure_range", "pressure"),
            ):
                if getattr(k, name) is not None:
                    found.append((["kinetics", name], kind, getattr(k, name)))
        return found


class Route(Strict):
    """A candidate route to the product."""

    id: str
    title: str = ""
    equations: list[str] = Field(default_factory=list, description="Overall, for readers.")
    reactants: list[str] = Field(default_factory=list, description="Component ids.")
    products: list[str] = Field(default_factory=list, description="Component ids.")
    reactions: list[str] = Field(
        default_factory=list, description="Ids of process/reactions.yaml, once written."
    )
    catalysts: list[str] = Field(default_factory=list, description="Ids of catalysts.yaml.")
    status: Literal["candidate", "selected", "rejected"] = "candidate"
    rationale: str = ""
    gaps: list[str] = Field(default_factory=list, description="What the evidence leaves open.")


class EvidenceConflict(Strict):
    """Observations that disagree, kept side by side."""

    about: str
    observations: list[str] = Field(min_length=2)
    note: str = ""
    resolution: str = Field(default="", description="How the model basis treats it, if at all.")


class ModelBasis(Strict):
    """What the engineering model takes from the evidence, and what it assumes beyond it."""

    route: str
    reactions: list[str] = Field(min_length=1, description="Ids of process/reactions.yaml.")
    catalyst: str = Field(default="", description="An id of process/catalysts.yaml.")
    evidence: list[str] = Field(default_factory=list, description="Observation ids.")
    assumptions: list[str] = Field(
        default_factory=list, description="Each assumption beyond the evidence, and its check."
    )
    validation: str = Field(default="", description="How the assumptions will be tested.")
    decision: str = Field(default="", description="The DESIGN.md entry, e.g. D-004.")
    decided_by: str = ""
    date: dt.date | None = None


class ReactionEvidence(Strict):
    """The reaction evidence of the process."""

    schema_: str = Field(alias="schema", description=f"Always {SCHEMA}.")
    kind: Literal["reaction-evidence"]
    product: str = Field(description="The product (component id).")
    question: str = Field(
        default="", description="Route, phase, scale and operating range the search is for."
    )
    searches: list[Search] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    observations: list[Observation] = Field(default_factory=list)
    conflicts: list[EvidenceConflict] = Field(default_factory=list)
    model_basis: ModelBasis | None = None

    @model_validator(mode="after")
    def _version(self) -> ReactionEvidence:
        if self.schema_ != SCHEMA:
            raise ValueError(unsupported_schema(self.schema_, SCHEMA))
        return self

    def sources_by_id(self) -> dict[str, Source]:
        return {s.id: s for s in self.sources}

    def routes_by_id(self) -> dict[str, Route]:
        return {r.id: r for r in self.routes}

    def observations_by_id(self) -> dict[str, Observation]:
        return {o.id: o for o in self.observations}


# -- loading ------------------------------------------------------------------------------------


def load(root: Path) -> tuple[ReactionEvidence | None, Any, list[Finding]]:
    """The evidence file of the plant at *root*, its YAML nodes and its schema findings; None
    (and no findings) without the file."""
    path = Path(root) / EVIDENCE_FILE
    if not path.is_file():
        return None, None, []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as failure:
        return None, None, [Finding(EVIDENCE_FILE, "error", "yaml.syntax", str(failure))]
    try:
        data = yaml.safe_load(text) or {}
        doc = yaml.compose(text)
    except yaml.YAMLError as failure:
        return None, None, [syntax_finding(EVIDENCE_FILE, failure, text)]
    try:
        return ReactionEvidence.model_validate(data), doc, []
    except ValidationError as failure:
        return (
            None,
            doc,
            [
                Finding(
                    EVIDENCE_FILE,
                    "error",
                    "cheme.evidence-schema",
                    f"{SCHEMA}: {'.'.join(str(p) for p in e['loc']) or '(file)'}: {e['msg']}",
                    line=_yaml_line(doc, e["loc"]),
                    hint="see `cheme schema reaction-evidence`",
                )
                for e in failure.errors()
            ],
        )


# -- checks -------------------------------------------------------------------------------------


@dataclass
class Declared:
    """The ids the plant's other files declare; None where that file does not exist."""

    components: set[str] | None = None
    #: The reactions by id, in the order of the file (the first of a duplicated id).
    reactions: dict[str, Reaction] | None = None
    catalysts: set[str] | None = None
    #: The files that exist but do not follow their schema: their ids are unknown, not
    #: missing, so nothing is checked against them (their schema findings say why).
    unreadable: frozenset[str] = frozenset()
    #: The position of each reaction id in ``process/reactions.yaml`` (its first entry).
    reaction_index: dict[str, int] = field(default_factory=dict)


class _Out:
    def __init__(self, doc: Any) -> None:
        self.doc = doc
        self.findings: list[Finding] = []

    def add(
        self,
        level: str,
        rule: str,
        message: str,
        loc: list[Any],
        ids: list[str],
        hint: str,
        file: str = EVIDENCE_FILE,
        doc: Any = None,
        key: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                file,
                level,  # type: ignore[arg-type]
                f"cheme.evidence-{rule}",
                message,
                line=_yaml_line(doc if file != EVIDENCE_FILE else self.doc, loc),
                ids=ids,
                hint=hint,
                key=key,
            )
        )


def rules(
    evidence: ReactionEvidence,
    doc: Any,
    declared: Declared | None = None,
    reactions_doc: Any = None,
) -> list[Finding]:
    """Every ``cheme.evidence-*`` finding of *evidence* (its YAML nodes *doc*), against the ids
    *declared* by the plant's materials, reactions and catalysts (*reactions_doc*: the YAML
    nodes of ``process/reactions.yaml``, for the handoff findings)."""
    declared = declared or Declared()
    out = _Out(doc)
    _id_rules(out, evidence)
    _reference_rules(out, evidence)
    _identity_rules(out, evidence)
    sources = evidence.sources_by_id()
    for i, obs in enumerate(evidence.observations):
        _observation_rules(out, sources, i, obs)
    _duplicate_rules(out, evidence)
    _model_rules(out, evidence)
    _declared_rules(out, evidence, declared)
    _handoff_rules(out, evidence, declared, reactions_doc)
    return out.findings


def _id_rules(out: _Out, evidence: ReactionEvidence) -> None:
    seen: dict[str, str] = {}
    for key, items in (
        ("sources", evidence.sources),
        ("routes", evidence.routes),
        ("observations", evidence.observations),
    ):
        for i, item in enumerate(items):
            if item.id in seen:
                out.add(
                    "error",
                    "duplicate-id",
                    f"{key}[{i}]: id {item.id} is already used by {seen[item.id]}",
                    [key, i, "id"],
                    [item.id],
                    "sources, routes and observations share one set of ids; rename one",
                )
            else:
                seen[item.id] = f"{key}[{i}]"


def _reference_rules(out: _Out, evidence: ReactionEvidence) -> None:
    sources, routes = evidence.sources_by_id(), evidence.routes_by_id()
    observations = evidence.observations_by_id()

    def unknown(kind: str, ref: str, known: dict[str, Any], loc: list[Any], owner: str) -> None:
        if ref in known:
            return
        listed = ", ".join(sorted(known)) or "none"
        out.add(
            "error",
            "reference",
            f"{owner}: {kind} {ref!r} is not declared",
            loc,
            [ref],
            f"name one of the file's {kind}s ({listed}), or add it",
            key=f"{owner}+{ref}",
        )

    for i, search in enumerate(evidence.searches):
        for j, ref in enumerate(search.found):
            unknown("source", ref, sources, ["searches", i, "found", j], f"search {i + 1}")
    for i, obs in enumerate(evidence.observations):
        unknown("source", obs.source, sources, ["observations", i, "source"], obs.id)
        unknown("route", obs.route, routes, ["observations", i, "route"], obs.id)
    for i, conflict in enumerate(evidence.conflicts):
        for j, ref in enumerate(conflict.observations):
            at = ["conflicts", i, "observations", j]
            unknown("observation", ref, observations, at, f"conflict {conflict.about!r}")
    basis = evidence.model_basis
    if basis is not None:
        unknown("route", basis.route, routes, ["model_basis", "route"], "model_basis")
        for j, ref in enumerate(basis.evidence):
            at = ["model_basis", "evidence", j]
            unknown("observation", ref, observations, at, "model_basis")


def _identity_rules(out: _Out, evidence: ReactionEvidence) -> None:
    for i, source in enumerate(evidence.sources):
        loc = ["sources", i]
        doi = source.doi.strip()
        if doi and not DOI_RE.match(doi):
            out.add(
                "error",
                "identity",
                f"source {source.id}: DOI {doi!r} is not of the form 10.xxxx/...",
                [*loc, "doi"],
                [source.id],
                "write the bare DOI, without doi: or https://doi.org/",
                key=f"{source.id}+doi",
            )
        number = source.patent.strip()
        if number and not PATENT_RE.match(number):
            out.add(
                "warning",
                "identity",
                f"source {source.id}: patent number {number!r} is not a publication number",
                [*loc, "patent"],
                [source.id],
                "office, number and kind code without blanks, e.g. US7652167B2 or EP0757027A1",
                key=f"{source.id}+patent",
            )
        if source.kind == "patent" and not number:
            out.add(
                "error",
                "identity",
                f"source {source.id} is a patent without its publication number",
                loc,
                [source.id],
                "give patent: with the office, number and kind code",
                key=f"{source.id}+no-patent",
            )
        if source.kind in ("paper", "review") and not doi and not source.url.strip():
            out.add(
                "warning",
                "identity",
                f"source {source.id}: a {source.kind} with neither DOI nor URL",
                loc,
                [source.id],
                "give its DOI, so that a reviewer can find the location cited",
                key=f"{source.id}+no-doi",
            )


def _unit_problem(path: list[Any], kind: str, value: Value) -> tuple[str, str] | None:
    """(message, hint) when the unit of *value* (a *kind* of :meth:`Observation.values`, at
    *path* below an observation) is not one this file reads, or a fraction lies outside 0 to 1."""
    name = ".".join(str(p) for p in path if p != "value")
    lo, hi = value.bounds()
    if kind == "temperature":
        if value.unit not in TEMPERATURE_UNITS or to_kelvin(lo, value.unit) is None:
            return f"temperature in {value.unit!r}", "write K or °C"
        if (to_kelvin(lo, value.unit) or 0.0) <= 0:
            return f"temperature {lo:g} {value.unit} is not above 0 K", "check the value"
    elif kind == "pressure":
        if value.unit not in PRESSURE_UNITS:
            units = ", ".join(PRESSURE_UNITS)
            return f"pressure in {value.unit!r}", f"say absolute or gauge: one of {units}"
    elif kind == "time":
        if value.unit not in TIME_UNITS:
            return f"{name} in {value.unit!r}", "write s, min or h"
    elif kind == "fraction":
        factor = FRACTION_UNITS.get(value.unit)
        if factor is None:
            return f"{name} in {value.unit!r}", "write % or 1 (a fraction)"
        if not 0 <= lo * factor <= hi * factor <= 1:
            return f"{name} {lo:g} to {hi:g} {value.unit} is outside 0 to 1", "check the unit"
    elif not value.unit.strip():
        return f"{name} has no unit", "write the unit the source gives"
    return None


def fraction(value: Value) -> tuple[float, float] | None:
    """A conversion, selectivity or yield as a fraction (min, max); None for another unit."""
    factor = FRACTION_UNITS.get(value.unit)
    if factor is None:
        return None
    lo, hi = value.bounds()
    return lo * factor, hi * factor


def _observation_rules(out: _Out, sources: dict[str, Source], i: int, obs: Observation) -> None:
    loc = ["observations", i]
    values = obs.values()
    reported = [v for _, _, v in values if v.status == "reported"]
    source = sources.get(obs.source)
    conversions = {c.component: c for c in obs.conversion}
    if reported and not obs.location.strip():
        out.add(
            "error",
            "location",
            f"observation {obs.id}: {len(reported)} reported value(s) without a location",
            loc,
            [obs.id],
            "give the page, table, figure or example the values are on",
        )
    if reported and source is not None and source.access in ("snippet", "unavailable"):
        out.add(
            "error",
            "access",
            f"observation {obs.id}: values reported from source {source.id}, which was "
            f"{'only seen as a search snippet' if source.access == 'snippet' else 'not accessed'}",
            loc,
            [obs.id, source.id],
            "open the source and cite the location, or list the values under missing: a "
            "snippet does not establish a numerical claim",
        )
    for path, kind, value in values:
        problem = _unit_problem(path, kind, value)
        if problem is not None:
            message, hint = problem
            where = "+".join(str(p) for p in path if p != "value")
            message = f"observation {obs.id}: {message}"
            at = [*loc, *path]
            out.add("error", "unit", message, at, [obs.id], hint, key=f"{obs.id}+{where}")
    for j, item in enumerate(obs.yields):
        at = [*loc, "yield", j]
        if item.type is None:
            out.add(
                "warning",
                "yield-basis",
                f"observation {obs.id}: yield of {item.product} is neither isolated nor analytical",
                at,
                [obs.id, item.product],
                "give type: isolated or analytical as the source says; if it does not, say so "
                "in missing",
                key=f"{obs.id}+yield-{j}+type",
            )
        if not item.relative_to:
            out.add(
                "warning",
                "yield-basis",
                f"observation {obs.id}: yield of {item.product} relative to no reactant",
                at,
                [obs.id, item.product],
                "give relative_to: the reactant the yield is based on",
                key=f"{obs.id}+yield-{j}+relative_to",
            )
        conv = conversions.get(item.relative_to)
        y, x = fraction(item.value), conv and fraction(conv.value)
        if conv is not None and y and x and item.basis in (None, "molar") and y[0] > x[1] + 1e-9:
            out.add(
                "warning",
                "yield-conversion",
                f"observation {obs.id}: yield of {item.product} ({y[0]:.3g}) above the "
                f"conversion of {item.relative_to} ({x[1]:.3g})",
                at,
                [obs.id, item.product],
                "a molar yield cannot exceed the conversion of its reactant: check whether the "
                "source's 'yield' is a selectivity, or another basis",
                key=f"{obs.id}+yield-{j}+conversion",
            )
    for j, item in enumerate(obs.selectivity):
        if not item.relative_to:
            out.add(
                "warning",
                "yield-basis",
                f"observation {obs.id}: selectivity to {item.product} relative to no reactant",
                [*loc, "selectivity", j],
                [obs.id, item.product],
                "give relative_to: the converted reactant the selectivity is based on",
                key=f"{obs.id}+selectivity-{j}+relative_to",
            )
    kin = obs.kinetics
    if kin is not None:
        lacking = [
            what
            for what, ok in (
                ("rate basis", kin.rate_basis.strip()),
                ("temperature range", kin.temperature_range is not None),
            )
            if not ok
        ]
        if lacking:
            out.add(
                "warning",
                "kinetics",
                f"observation {obs.id}: kinetics without {' and '.join(lacking)}",
                [*loc, "kinetics"],
                [obs.id],
                "a rate law holds on its basis and inside the conditions it was fitted to; if "
                "the source does not say, list it under missing",
            )


def _duplicate_rules(out: _Out, evidence: ReactionEvidence) -> None:
    seen: dict[tuple[str, str], str] = {}
    for i, obs in enumerate(evidence.observations):
        where = " ".join(obs.location.casefold().split())
        if not where:
            continue
        key = (obs.source, where)
        if key in seen:
            out.add(
                "warning",
                "duplicate",
                f"observation {obs.id}: the same location of source {obs.source} as "
                f"observation {seen[key]}",
                ["observations", i, "location"],
                [obs.id, seen[key]],
                "record each experiment once; if they are two runs on one table, say which "
                "row or entry",
            )
        else:
            seen[key] = obs.id


def _model_rules(out: _Out, evidence: ReactionEvidence) -> None:
    selected = [(i, r) for i, r in enumerate(evidence.routes) if r.status == "selected"]
    basis = evidence.model_basis
    for i, route in selected[1:]:
        out.add(
            "error",
            "model-basis",
            f"route {route.id} is selected, and so is {selected[0][1].id}",
            ["routes", i, "status"],
            [route.id],
            "select one route for the model; keep the others as candidate or rejected",
            key=f"{route.id}+selected-twice",
        )
    if selected and basis is None:
        i, route = selected[0]
        out.add(
            "error",
            "model-basis",
            f"route {route.id} is selected but there is no model_basis",
            ["routes", i, "status"],
            [route.id],
            "write model_basis: the route, the reactions of process/reactions.yaml, the "
            "observations they rest on and the assumptions beyond them",
            key=f"{route.id}+no-model-basis",
        )
    if basis is None:
        return
    route = evidence.routes_by_id().get(basis.route)
    if route is not None and route.status != "selected":
        out.add(
            "error",
            "model-basis",
            f"model_basis uses route {route.id}, which is {route.status}",
            ["model_basis", "route"],
            [route.id],
            "mark the route selected, with its rationale",
            key=f"{route.id}+not-selected",
        )
    if not basis.evidence:
        out.add(
            "error",
            "model-basis",
            "model_basis names no evidence",
            ["model_basis"],
            [basis.route],
            "list the observations the model rests on; with none, the model is an assumption "
            "and says so in assumptions",
            key=f"{basis.route}+no-evidence",
        )
    observations = evidence.observations_by_id()
    catalysts: dict[str, list[str]] = {}
    for j, ref in enumerate(basis.evidence):
        obs = observations.get(ref)
        if obs is None:
            continue
        if obs.route != basis.route:
            out.add(
                "warning",
                "model-basis",
                f"model_basis: observation {ref} belongs to route {obs.route}, not {basis.route}",
                ["model_basis", "evidence", j],
                [ref],
                "use the route's own evidence, or explain the transfer in assumptions",
                key=f"{basis.route}+{ref}+other-route",
            )
        cond = obs.conditions
        cat = (cond.catalyst or cond.catalyst_formulation).strip() if cond is not None else ""
        if cat:
            catalysts.setdefault(cat.casefold(), []).append(ref)
        if (
            cond is not None
            and cond.catalyst
            and basis.catalyst
            and cond.catalyst != basis.catalyst
        ):
            out.add(
                "warning",
                "model-basis",
                f"model_basis: catalyst {basis.catalyst}, but observation {ref} is on "
                f"{cond.catalyst}",
                ["model_basis", "evidence", j],
                [ref],
                "use evidence on the model's catalyst, or explain the transfer in assumptions",
                key=f"{basis.route}+{ref}+other-catalyst",
            )
    if len(catalysts) > 1 and not basis.assumptions:
        out.add(
            "warning",
            "model-basis",
            "model_basis pools observations on different catalysts: "
            + "; ".join(f"{c}: {', '.join(refs)}" for c, refs in sorted(catalysts.items())),
            ["model_basis", "evidence"],
            [basis.route],
            "do not pool incompatible experiments; choose one catalyst's evidence, or state the "
            "assumption that makes them comparable",
            key=f"{basis.route}+pooled",
        )


def _declared_rules(out: _Out, evidence: ReactionEvidence, declared: Declared) -> None:
    components = declared.components
    if components is not None:
        refs: list[tuple[str, list[Any]]] = [(evidence.product, ["product"])]
        for i, route in enumerate(evidence.routes):
            refs += [(c, ["routes", i, "reactants", j]) for j, c in enumerate(route.reactants)]
            refs += [(c, ["routes", i, "products", j]) for j, c in enumerate(route.products)]
        for i, obs in enumerate(evidence.observations):
            loc = ["observations", i]
            if obs.conditions is not None:
                refs += [(c, [*loc, "conditions", "feed", c]) for c in obs.conditions.feed]
            refs += [(c, [*loc, "outlet", c]) for c in obs.outlet]
            refs += [(c.component, [*loc, "conversion", j]) for j, c in enumerate(obs.conversion)]
            for key, items in (("selectivity", obs.selectivity), ("yield", obs.yields)):
                for j, item in enumerate(items):
                    refs.append((item.product, [*loc, key, j]))
                    if item.relative_to:
                        refs.append((item.relative_to, [*loc, key, j, "relative_to"]))
        reported: set[str] = set()
        for ref, loc in refs:
            if ref and ref not in components and ref not in reported:
                reported.add(ref)
                out.add(
                    "warning",
                    "component",
                    f"component {ref} is not declared in process/materials.yaml",
                    loc,
                    [ref],
                    "declare it with its formula, CAS and InChIKey (skill materials), so the "
                    "evidence and the model name one chemical",
                )
    reactions = declared.reactions
    for i, route in enumerate(evidence.routes):
        for j, ref in enumerate(route.reactions):
            if reactions is not None and ref not in reactions:
                out.add(
                    "warning",
                    "reaction",
                    f"route {route.id}: reaction {ref} is not in {REACTIONS_FILE}",
                    ["routes", i, "reactions", j],
                    [route.id, ref],
                    f"write it in {REACTIONS_FILE} (skill reactions), or remove it",
                )
    basis = evidence.model_basis
    if basis is not None and REACTIONS_FILE not in declared.unreadable:
        for j, ref in enumerate(basis.reactions):
            if reactions is None or ref not in reactions:
                out.add(
                    "error",
                    "reaction",
                    f"model_basis: reaction {ref} is not in {REACTIONS_FILE}",
                    ["model_basis", "reactions", j],
                    [ref],
                    f"write the model's reactions in {REACTIONS_FILE} (skill reactions)",
                )
    catalysts = declared.catalysts
    if catalysts is None:
        return
    refs = [
        (c, ["routes", i, "catalysts", j])
        for i, r in enumerate(evidence.routes)
        for j, c in enumerate(r.catalysts)
    ]
    refs += [
        (o.conditions.catalyst, ["observations", i, "conditions", "catalyst"])
        for i, o in enumerate(evidence.observations)
        if o.conditions is not None and o.conditions.catalyst
    ]
    if basis is not None and basis.catalyst:
        refs.append((basis.catalyst, ["model_basis", "catalyst"]))
    reported_catalysts: set[str] = set()
    for ref, loc in refs:
        if ref not in catalysts and ref not in reported_catalysts:
            reported_catalysts.add(ref)
            out.add(
                "warning",
                "catalyst",
                f"catalyst {ref} is not declared in process/catalysts.yaml",
                loc,
                [ref],
                "declare it (skill reactions), or keep the source's description in "
                "catalyst_formulation",
            )


def _handoff_rules(
    out: _Out, evidence: ReactionEvidence, declared: Declared, reactions_doc: Any
) -> None:
    basis = evidence.model_basis
    if basis is None or declared.reactions is None or not basis.evidence:
        return
    cited = set(basis.evidence) | {
        obs.source for obs in evidence.observations if obs.id in basis.evidence
    }
    for ref in basis.reactions:
        reaction = declared.reactions.get(ref)
        if reaction is None:
            continue
        i = declared.reaction_index.get(ref)
        for name in ("conversion", "heat_of_reaction", "rate"):
            value = getattr(reaction, name)
            if value is None or value.provenance != "given":
                continue
            if any(
                re.search(rf"(?<![\w-]){re.escape(c)}(?![\w-])", value.source or "") for c in cited
            ):
                continue
            out.add(
                "info",
                "handoff",
                f"reaction {ref}: the given {name} cites none of the model basis's evidence",
                ["reactions", i, name] if i is not None else ["reactions"],
                [ref],
                f"name the observation it comes from in its source (e.g. {EVIDENCE_FILE} "
                f"{basis.evidence[0]}), or mark it assumed",
                file=REACTIONS_FILE,
                doc=reactions_doc,
                key=f"{ref}+{name}",
            )


# -- route comparison ---------------------------------------------------------------------------


@dataclass
class RouteSummary:
    """What the evidence says about one route (:func:`route_comparison`)."""

    id: str
    title: str
    status: str
    sources: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    scales: list[str] = field(default_factory=list)
    #: K, min and max over the observations that report a temperature.
    temperature: tuple[float, float] | None = None
    #: kPa(a), min and max over the observations that report an absolute pressure.
    pressure: tuple[float, float] | None = None
    #: Component -> (min, max) fraction, per kind: conversion, selectivity, yield.
    performance: dict[str, dict[str, tuple[float, float]]] = field(default_factory=dict)
    kinetics: list[str] = field(default_factory=list)
    byproducts: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    #: Sources its observations cite that were not read in full (abstract, snippet, none).
    unavailable: list[str] = field(default_factory=list)
    rationale: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "sources": self.sources,
            "observations": self.observations,
            "scales": self.scales,
            "temperature_K": list(self.temperature) if self.temperature else None,
            "pressure_kPa_abs": list(self.pressure) if self.pressure else None,
            "performance": {
                kind: {name: list(r) for name, r in table.items()}
                for kind, table in self.performance.items()
            },
            "kinetics": self.kinetics,
            "byproducts": self.byproducts,
            "conflicts": self.conflicts,
            "gaps": self.gaps,
            "unavailable": self.unavailable,
            "rationale": self.rationale,
        }


def _widen(old: tuple[float, float] | None, lo: float, hi: float) -> tuple[float, float]:
    return (lo, hi) if old is None else (min(old[0], lo), max(old[1], hi))


def _converted(value: Value | None, convert: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    lo, hi = value.bounds()
    a, b = convert(lo, value.unit), convert(hi, value.unit)
    return None if a is None or b is None else (a, b)


def route_comparison(evidence: ReactionEvidence) -> list[RouteSummary]:
    """One summary per route: its sources and observations, the ranges of temperature,
    pressure, conversion, selectivity and yield reported (each kept apart), the kinetics found,
    the conflicts it is part of, its gaps (the route's and every observation's ``missing``) and
    the sources that could not be read. Only ``reported`` and ``derived`` values count."""
    sources = evidence.sources_by_id()
    summaries: list[RouteSummary] = []
    for route in evidence.routes:
        s = RouteSummary(route.id, route.title, route.status, rationale=route.rationale)
        s.gaps = list(route.gaps)
        obs_ids: set[str] = set()
        for obs in evidence.observations:
            if obs.route != route.id:
                continue
            obs_ids.add(obs.id)
            s.observations.append(obs.id)
            if obs.source not in s.sources:
                s.sources.append(obs.source)
            if obs.scale and obs.scale not in s.scales:
                s.scales.append(obs.scale)
            s.gaps += [f"{obs.id}: {m}" for m in obs.missing]
            s.byproducts += [b for b in obs.byproducts if b not in s.byproducts]
            if obs.kinetics is not None:
                s.kinetics.append(f"{obs.id}: {obs.kinetics.equation}")
            cond = obs.conditions
            if cond is not None:
                for name, convert in (("temperature", to_kelvin), ("pressure", to_kpa_abs)):
                    value = getattr(cond, name)
                    if value is None or value.status == "assumed":
                        continue
                    found = _converted(value, convert)
                    if found is not None:
                        setattr(s, name, _widen(getattr(s, name), *found))
            for kind, items, key in (
                ("conversion", obs.conversion, "component"),
                ("selectivity", obs.selectivity, "product"),
                ("yield", obs.yields, "product"),
            ):
                for item in items:
                    if item.value.status == "assumed":
                        continue
                    found = fraction(item.value)
                    if found is None:
                        continue
                    table = s.performance.setdefault(kind, {})
                    name = getattr(item, key)
                    if kind == "yield" and item.type:
                        name = f"{name} ({item.type})"
                    table[name] = _widen(table.get(name), *found)
        for conflict in evidence.conflicts:
            if obs_ids & set(conflict.observations):
                s.conflicts.append(f"{conflict.about}: {', '.join(conflict.observations)}")
        s.unavailable = [
            f"{sid} ({sources[sid].access})"
            for sid in s.sources
            if sid in sources and sources[sid].access != "full-text"
        ]
        summaries.append(s)
    return summaries


def comparison_text(evidence: ReactionEvidence) -> str:
    """:func:`route_comparison` as text, one block per route, then the model basis."""

    def span(r: tuple[float, float], fmt: str = "{:.3g}") -> str:
        a, b = (fmt.format(x) for x in r)
        return a if a == b else f"{a}-{b}"

    question = f" -- {evidence.question}" if evidence.question else ""
    lines = [f"product: {evidence.product}{question}"]
    for s in route_comparison(evidence):
        lines.append("")
        lines.append(f"{s.id} [{s.status}] {s.title}".rstrip())
        lines.append(
            f"  evidence: {len(s.observations)} observation(s) from {len(s.sources)} source(s)"
            + (f"; scale {', '.join(s.scales)}" if s.scales else "")
        )
        if s.temperature:
            lines.append(f"  temperature: {span(s.temperature, '{:.0f}')} K")
        if s.pressure:
            lines.append(f"  pressure: {span(s.pressure, '{:.0f}')} kPa(a)")
        for kind in ("conversion", "selectivity", "yield"):
            for name, r in sorted(s.performance.get(kind, {}).items()):
                pct = (r[0] * 100, r[1] * 100)
                lines.append(f"  {kind} {name}: {span(pct)} %")
        for text in s.kinetics:
            lines.append(f"  kinetics {text}")
        if s.byproducts:
            lines.append(f"  byproducts: {', '.join(s.byproducts)}")
        for text in s.conflicts:
            lines.append(f"  conflict: {text}")
        for text in s.unavailable:
            lines.append(f"  not read: {text}")
        for text in s.gaps:
            lines.append(f"  gap: {text}")
        if s.rationale:
            lines.append(f"  rationale: {s.rationale}")
    cited = {o.source for o in evidence.observations}
    unread = [s for s in evidence.sources if s.id not in cited and s.access != "full-text"]
    if unread:
        lines.append("")
        lines += [f"not read, no observation: {s.id} ({s.access})" for s in unread]
    basis = evidence.model_basis
    lines.append("")
    if basis is None:
        lines.append("model basis: none selected yet")
    else:
        lines.append(
            f"model basis: route {basis.route}, reactions {', '.join(basis.reactions)}"
            + (f", catalyst {basis.catalyst}" if basis.catalyst else "")
            + (f" ({basis.decision})" if basis.decision else "")
        )
        lines.append(f"  evidence: {', '.join(basis.evidence) or 'none'}")
        lines += [f"  assumption: {a}" for a in basis.assumptions]
        if basis.validation:
            lines.append(f"  validation: {basis.validation}")
    return "\n".join(lines)


# -- support of a specified model value ---------------------------------------------------------


@dataclass
class Support:
    """Whether the decided model basis supports one specified value of a conversion reactor
    (:func:`model_support`): the observations it rests on, or why it does not stand."""

    #: ``conversion`` (of ``component``) or ``selectivity`` (to ``component``, of ``key``)
    quantity: str
    component: str
    value: float
    supported: bool = False
    key: str = ""
    #: The model basis's route.
    route: str = ""
    #: The catalyst of the observations that cover the value ("" when none is stated).
    catalyst: str = ""
    #: The observations that cover the value, each as ``id (source, location)``.
    observations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    #: Min and max fraction over those observations (with their uncertainty).
    observed: tuple[float, float] | None = None
    #: K and kPa(a), min and max over those observations, where they report it (each one's
    #: own conditions hold the operating point).
    temperature: tuple[float, float] | None = None
    pressure: tuple[float, float] | None = None
    #: Usable observations at the operating point exclude the value: the evidence contradicts
    #: it (not merely: cannot be compared).
    contradicted: bool = False
    #: Why the value does not count as sourced (empty when supported).
    reasons: list[str] = field(default_factory=list)
    #: Observations left out and conditions not compared, with the reason.
    notes: list[str] = field(default_factory=list)

    @property
    def what(self) -> str:
        if self.quantity == "selectivity":
            return f"selectivity to {self.component}" + (f" (of {self.key})" if self.key else "")
        return f"conversion of {self.component}"

    def text(self) -> str:
        head = f"{self.what} {self.value:g}"
        if self.supported:
            lo, hi = self.observed or (self.value, self.value)
            catalyst = f", catalyst {self.catalyst}" if self.catalyst else ""
            return (
                f"{head} within the observed {lo:.3g}-{hi:.3g} of route {self.route}{catalyst} "
                f"({EVIDENCE_FILE}: {', '.join(self.observations)})"
            )
        return f"{head} not supported by {EVIDENCE_FILE}: " + "; ".join(self.reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "quantity": self.quantity,
            "component": self.component,
            "key": self.key,
            "value": self.value,
            "supported": self.supported,
            "contradicted": self.contradicted,
            "route": self.route,
            "catalyst": self.catalyst,
            "observations": self.observations,
            "sources": self.sources,
            "observed": list(self.observed) if self.observed else None,
            "temperature_K": list(self.temperature) if self.temperature else None,
            "pressure_kPa_abs": list(self.pressure) if self.pressure else None,
            "reasons": self.reasons,
            "notes": self.notes,
            "text": self.text(),
        }


@dataclass
class Blocking:
    """The error findings (:func:`rules`) that keep evidence from supporting a model value:
    per observation (its own, and its source's), and on the model basis or its route (any of
    these blocks every value)."""

    observations: dict[str, list[str]] = field(default_factory=dict)
    basis: list[str] = field(default_factory=list)


def blocking(evidence: ReactionEvidence, findings: list[Finding]) -> Blocking:
    """The error findings of *findings* (:func:`rules` on *evidence*) that block support:
    those naming an observation; those naming a source, for every observation citing it (a
    malformed identity, a duplicated id); those on the model basis or naming a route
    (``evidence-model-basis``: two routes selected, the basis on a route not selected, ...)."""
    found = Blocking()
    observations = {o.id for o in evidence.observations}
    sources = {s.id for s in evidence.sources}
    routes = {r.id for r in evidence.routes}
    citing: dict[str, list[str]] = {}
    for obs in evidence.observations:
        citing.setdefault(obs.source, []).append(obs.id)
    for f in findings:
        if f.level != "error":
            continue
        text = f"{f.rule}: {f.message}"
        ids = list(dict.fromkeys(f.ids or []))
        on_basis = f.rule == "cheme.evidence-model-basis" or f.message.startswith("model_basis")
        if on_basis or any(ref in routes for ref in ids):
            if text not in found.basis:
                found.basis.append(text)
            continue
        named = [ref for ref in ids if ref in observations]
        named += [o for ref in ids if ref in sources for o in citing.get(ref, [])]
        for ref in dict.fromkeys(named):
            found.observations.setdefault(ref, []).append(text)
    return found


def covers(evidence: ReactionEvidence | None, reactions: list[str]) -> bool:
    """Whether the model basis of *evidence* names every one of *reactions*."""
    basis = evidence.model_basis if evidence is not None else None
    return basis is not None and bool(reactions) and set(reactions) <= set(basis.reactions)


def _reports(obs: Observation, quantity: str, component: str) -> list[Any]:
    """The conversions of *component* (or selectivities to it) *obs* reports, of any basis."""
    if quantity == "conversion":
        return [c for c in obs.conversion if c.component == component]
    return [s for s in obs.selectivity if s.product == component]


def _span(value: Value | None, convert: Any, factor: float = 1.0) -> tuple[float, float] | None:
    """A reported condition as (min, max) in K or kPa(a), widened by its uncertainty (in its
    unit, times *factor*); None when not given, assumed or in a unit this file does not read."""
    if value is None or value.status == "assumed":
        return None
    got = _converted(value, convert)
    if got is None:
        return None
    spread = (value.uncertainty or 0.0) * factor
    return got[0] - spread, got[1] + spread


def _inside(xs: list[float], span: tuple[float, float]) -> bool:
    return all(span[0] - 1e-9 <= x <= span[1] + 1e-9 for x in xs)


def _catalyst(obs: Observation) -> str:
    """The catalyst an observation is on: its id, else the formulation as written ("")."""
    cond = obs.conditions
    return (cond.catalyst or cond.catalyst_formulation).strip() if cond is not None else ""


#: The conditions an observation may record that :func:`model_support` does not compare.
UNCOMPARED = (
    "residence or contact time",
    "space velocity",
    "feed composition and ratios",
    "catalyst loading",
    "phase and solvent",
)


def model_support(
    evidence: ReactionEvidence,
    quantity: Literal["conversion", "selectivity"],
    component: str,
    value: float,
    key: str = "",
    temperatures: list[float] | None = None,
    pressures: list[float] | None = None,
    errors: Blocking | None = None,
    unknown_cases: list[str] | None = None,
    catalyst_names: list[str] | None = None,
    reactor_catalyst: str = "",
) -> Support:
    """Whether the model basis of *evidence* supports a specified per-pass *value* (a fraction)
    of a conversion reactor: the ``conversion`` of *component*, or the molar ``selectivity`` to
    *component* of the converted *key* (as a fraction: product formed per key converted, times
    the key's over the product's coefficient), at the reactor's operating *temperatures* (K)
    and *pressures* (kPa(a)) from the flowsheet; *unknown_cases* are the cases without an
    operating temperature. *errors* are the blocking error findings (:func:`blocking`);
    *reactor_catalyst* the catalyst the reactor holds (``catalyst:`` of the step, an id of
    ``process/catalysts.yaml``): the basis's catalyst must be it, and when the basis names
    none the observations must be on it. *catalyst_names* the other names of that
    catalyst (the basis's, else the reactor's: its name in
    ``process/catalysts.yaml``) an observation's ``catalyst_formulation`` may give.

    The model basis's route must be selected, no error finding may be on the basis or its
    route, and the operating temperature known in every case: the value is a claim at the
    reactor's conditions. A cited observation on that route reporting the quantity counts when
    no error finding names it or its source, its source id is declared once and was read in
    full text, it states its catalyst (``catalyst``, else ``catalyst_formulation``; a
    non-catalytic one says so in the formulation) and, when the basis names one, it is that
    catalyst (its id, or a formulation equal to its id or *catalyst_names*), the value is
    reported or derived (not assumed) in a fraction unit and labelled: a conversion ``basis:
    per-pass`` (not unstated, ``overall`` or ``equilibrium``), a selectivity ``basis: molar``
    with ``relative_to`` the key. It must report a temperature whose range (with its
    uncertainty; a single value covers only itself) holds every operating temperature; a
    pressure, where both give one, likewise (a pressure either side does not give is noted,
    not compared). Only temperature and pressure are compared: the other conditions
    (:data:`UNCOMPARED`) are listed as not compared on every verdict (supported or
    contradicted). The value must
    lie within the range those observations span (each one's value or range, widened by its
    uncertainty): interpolation, never extrapolation. Observations on different catalysts are
    not pooled: one catalyst's observations must cover the value. A conflict the file flags on
    any cited observation of the quantity means it is not supported, whatever its resolution
    says. ``contradicted`` is set only when nothing else kept the value from support: the
    usable observations, compared at a known operating point, exclude it."""
    basis = evidence.model_basis
    found = Support(quantity, component, value, key=key)
    if basis is None:
        found.reasons.append("no model_basis")
        return found
    errors = errors or Blocking()
    found.route = basis.route
    route = evidence.routes_by_id().get(basis.route)
    if route is None or route.status != "selected":
        state = "not declared" if route is None else route.status
        found.reasons.append(f"the model basis's route {basis.route} is {state}, not selected")
    found.reasons += [f"model basis: {text}" for text in errors.basis]
    if basis.catalyst and reactor_catalyst and basis.catalyst != reactor_catalyst:
        found.reasons.append(f"evidence on {basis.catalyst}, reactor holds {reactor_catalyst}")
    target = basis.catalyst or reactor_catalyst  # the catalyst the observations must be on
    temperatures = temperatures or []
    pressures = pressures or []
    if unknown_cases:
        found.reasons.append(
            f"operating temperature unknown in case {', '.join(unknown_cases)} (no outlet "
            "temperature in the flowsheet): the value cannot be placed within the observed "
            "conditions"
        )
    elif not temperatures:
        found.reasons.append(
            "operating temperature unknown (no outlet temperature in the flowsheet): the value "
            "cannot be placed within the observed conditions"
        )
    if not pressures:
        found.notes.append("operating pressure unknown: pressure not compared")
    sources = evidence.sources_by_id()
    declared: dict[str, int] = {}
    for s in evidence.sources:
        declared[s.id] = declared.get(s.id, 0) + 1
    observations = evidence.observations_by_id()
    cited: set[str] = set()
    candidates: list[tuple[Observation, Value, tuple[float, float] | None]] = []
    for ref in basis.evidence:
        obs = observations.get(ref)
        if obs is None:
            continue
        for item in _reports(obs, quantity, component):
            cited.add(obs.id)
            why = ""
            source = sources.get(obs.source)
            cond = obs.conditions
            temperature = _span(cond.temperature if cond else None, to_kelvin)
            pressure_value = cond.pressure if cond else None
            pressure = None
            if pressure_value is not None:
                factor = PRESSURE_UNITS.get(pressure_value.unit, (1.0, None))[0] or 1.0
                pressure = _span(pressure_value, to_kpa_abs, factor)
            blocked = errors.observations.get(obs.id)
            on = _catalyst(obs)
            names = {target.casefold(), *(n.casefold() for n in catalyst_names or [])}
            is_basis = bool(target) and (
                cond.catalyst == target
                if cond is not None and cond.catalyst
                else on.casefold() in names
            )
            if obs.route != basis.route:
                why = f"on route {obs.route}, not {basis.route}"
            elif source is None:
                why = f"source {obs.source} is not declared"
            elif declared.get(obs.source, 0) > 1:
                why = f"source id {obs.source} is declared {declared[obs.source]} times"
            elif source.access != "full-text":
                why = f"source {source.id} not read in full ({source.access})"
            elif blocked:
                why = "error finding(s): " + "; ".join(blocked)
            elif not on:
                why = "catalyst not stated (catalyst or catalyst_formulation)"
            elif target and not is_basis:
                whose = "the model basis's" if basis.catalyst else "the reactor's"
                why = f"on catalyst {on}, not {whose} {target}"
            elif item.value.status == "assumed":
                why = "the value is assumed, not reported"
            elif fraction(item.value) is None:
                why = f"unit {item.value.unit} is not a fraction"
            elif quantity == "conversion" and item.basis != "per-pass":
                why = (
                    f"an {item.basis} conversion, not per pass"
                    if item.basis
                    else "basis not stated (per-pass, overall or equilibrium)"
                )
            elif quantity == "selectivity" and item.basis != "molar":
                why = (
                    f"a {item.basis}-basis selectivity, not molar"
                    if item.basis
                    else "basis not stated (molar, carbon or mass)"
                )
            elif quantity == "selectivity" and item.relative_to != key:
                why = (
                    f"relative to {item.relative_to}, not {key}"
                    if item.relative_to
                    else f"relative_to not stated (the key is {key})"
                )
            elif not temperatures:
                why = "the operating temperature is unknown: not compared"
            elif temperature is None:
                why = "no temperature reported: cannot be placed at the operating point"
            elif not _inside(temperatures, temperature):
                why = (
                    f"at {temperature[0]:.4g}-{temperature[1]:.4g} K, not the operating temperature"
                )
            elif pressures and pressure is not None and not _inside(pressures, pressure):
                why = f"at {pressure[0]:.4g}-{pressure[1]:.4g} kPa(a), not the operating pressure"
            if why:
                found.notes.append(f"{obs.id} left out: {why}")
                continue
            if pressures and pressure is None:
                found.notes.append(f"{obs.id}: no pressure reported, pressure not compared")
            candidates.append((obs, item.value, temperature))
    for conflict in evidence.conflicts:
        shared = cited & set(conflict.observations)
        if shared:
            others = [o for o in conflict.observations if o not in shared]
            found.reasons.append(
                f"conflict {conflict.about!r} on {', '.join(sorted(shared))}"
                + (f" and {', '.join(others)}" if others else "")
                + (f" (resolution: {conflict.resolution})" if conflict.resolution else "")
            )
    # nothing compared yet: whatever the range shows then is not a contradiction
    comparable = not found.reasons
    if not candidates:
        if not comparable:
            return found
        found.reasons.append(
            f"no observation of the model basis reports the {found.what} at the operating "
            "point, read in full, labelled per pass (molar, relative to the key) and not "
            "assumed" + (" (" + "; ".join(found.notes) + ")" if found.notes else "")
        )
        return found
    # one catalyst's observations (never pooled across catalysts)
    groups: dict[str, list[tuple[Observation, Value, tuple[float, float] | None]]] = {}
    for candidate in candidates:
        name = target or _catalyst(candidate[0])  # all on it when there is one
        groups.setdefault(name.casefold(), []).append(candidate)
    spans: list[tuple[str, tuple[float, float], list[Any]]] = []
    for group in groups.values():
        observed: tuple[float, float] | None = None
        for _, item_value, _ in group:
            lo, hi = fraction(item_value) or (0.0, 0.0)
            spread = (item_value.uncertainty or 0.0) * FRACTION_UNITS[item_value.unit]
            observed = _widen(observed, lo - spread, hi + spread)
        assert observed is not None
        spans.append((target or _catalyst(group[0][0]), observed, group))
    chosen = next((s for s in spans if _inside([value], s[1])), spans[0])
    name, observed, group = chosen
    if len(spans) > 1:
        found.notes.append(
            "not pooled across catalysts: "
            + "; ".join(
                f"{n}: {o[0]:.3g}-{o[1]:.3g} ({', '.join(c[0].id for c in g)})" for n, o, g in spans
            )
        )
    found.catalyst = name
    found.observed = observed
    for obs, _, temperature in group:
        if temperature is not None:
            found.temperature = _widen(found.temperature, *temperature)
        cond = obs.conditions
        if cond is not None and cond.pressure is not None:
            factor = PRESSURE_UNITS.get(cond.pressure.unit, (1.0, None))[0] or 1.0
            pressure = _span(cond.pressure, to_kpa_abs, factor)
            if pressure is not None:
                found.pressure = _widen(found.pressure, *pressure)
        source = sources[obs.source]
        found.observations.append(f"{obs.id} ({source.id}, {obs.location or 'no location'})")
        if source.id not in found.sources:
            found.sources.append(source.id)
    if not _inside([value], observed):
        found.contradicted = comparable
        where = " (no single catalyst's observations cover it)" if len(spans) > 1 else ""
        found.reasons.append(
            f"{value:g} outside the observed range {observed[0]:.3g}-{observed[1]:.3g} at "
            f"the outlet temperature/pressure ({', '.join(o.id for o, _, _ in group)}; other "
            f"conditions not compared){where}"
        )
    found.supported = not found.reasons
    if found.supported or found.contradicted:  # a verdict on outlet T and P only
        found.notes.append("not compared: " + ", ".join(UNCOMPARED))
    return found
