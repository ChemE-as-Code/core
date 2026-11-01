"""``cheme maturity``: which calculation maturity level the evidence in a plant repository
supports, requirement by requirement (docs/framework/maturity.md).

Three axes are kept apart:

- **calculation maturity**, four levels, each with requirements checked here from files:
  ``sourced`` (a sourced process description), ``balanced`` (a balanced conceptual PFD),
  ``predictive`` (a converged predictive simulation) and ``engineering`` (a preliminary or
  basic engineering package). A level is reached when every required requirement of it and of
  every level below passes. Schema-valid files and generated drawings never satisfy a
  calculation requirement: the requirements read balances, sources, model bases and run
  records, not the presence of sheets;
- **artifact completeness**: which deliverables exist (sheets, lists, datasheets, layout,
  estimates), reported beside the levels and never counted towards them;
- **review**: the library manifest's ``validation.status`` and the review records, echoed as
  found. No command sets them.

Each requirement has a status: ``pass``, ``fail`` (the evidence is there and does not satisfy
it), ``missing`` (an input or record is absent) or ``unsupported`` (core cannot evaluate it).
Specified models (conversions, component splits, stream values as written) count only as
``specified``: sourced, they support ``balanced``; never ``predictive``
(:mod:`chemeascode.domains.process.model_basis`). A specified conversion or selectivity is
sourced by its own source (unless the evidence contradicts it) or by the decided model basis
of ``process/reaction-evidence.yaml`` whose observations cover it at the reactor's outlet
temperature and pressure (:mod:`chemeascode.domains.process.evidence_basis`).

The report maps the level onto the design maturity labels of the library manifest's ``maturity``
(:data:`LIBRARY_MATURITY`) and says whether a manifest (``process.yaml``) claims more. Both are
qualified in user-facing text, never a bare "maturity" (docs/concepts/glossary.md).
"""

from __future__ import annotations

import datetime as _dt
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.workspace import Workspace
from chemeascode.foundation.yamlsource import _compose, _yaml_line

REPORT_SCHEMA = "cheme/maturity-report/v1"
MATURITY_FILE = "checks/maturity.json"
DESIGN_BASIS_FILE = "process/design-basis.yaml"
#: The process-library manifest of a plant repository (schema cheme-as-code/process/v1).
MANIFEST_FILE = "process.yaml"

#: (id, title, the highest library ``maturity`` label the level supports)
LEVELS = (
    ("sourced", "Sourced process description", "concept"),
    ("balanced", "Balanced conceptual PFD", "screening"),
    ("predictive", "Converged predictive simulation", "screening"),
    ("engineering", "Preliminary/basic engineering package", "basic-engineering"),
)
#: The library manifest's design maturity labels, lowest first; the last two no check here supports.
LIBRARY_MATURITY = (
    "concept",
    "screening",
    "basic-engineering",
    "detail-engineering",
    "operating-reference",
)
#: What the engineering package level does not cover, whatever passes.
ENGINEERING_LIMITATIONS = (
    "mechanical design to a code (wall thickness, nozzle loads) is not checked",
    "materials and corrosion selection is not checked",
    "relief and blowdown sizing is not checked",
    "control and dynamic behaviour is not checked",
)


@dataclass
class Requirement:
    """One requirement of one level, evaluated."""

    id: str
    level: str
    title: str
    status: str = "pass"  # pass, fail, missing, unsupported
    required: bool = True
    file: str = ""
    line: int | None = None
    detail: str = ""
    hint: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def rule(self) -> str:
        return f"cheme.maturity-{self.id.replace('.', '-')}"

    def entry(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status,
            "required": self.required,
            "rule": self.rule,
            "file": self.file,
            "line": self.line,
            "detail": self.detail,
            "hint": self.hint,
            "evidence": self.evidence,
        }

    def finding(self) -> Finding:
        level = "error" if self.required else "info"
        return Finding(
            self.file or ".",
            level,  # type: ignore[arg-type]
            self.rule,
            f"{self.status}: {self.title}" + (f" ({self.detail})" if self.detail else ""),
            line=self.line,
            hint=self.hint or f"see docs/framework/maturity.md, requirement {self.id}",
        )


@dataclass
class MaturityReport:
    """The evaluated levels and the other two axes (see the module docstring)."""

    level: str | None
    levels: list[dict[str, Any]]
    requirements: list[Requirement]
    model_basis: list[dict[str, Any]]
    cases: list[dict[str, Any]]
    assumptions: dict[str, Any]
    unresolved: list[dict[str, Any]]
    limitations: list[dict[str, Any]]
    artifacts: dict[str, Any]
    review: dict[str, Any]
    manifest: dict[str, Any]
    source: dict[str, Any]
    findings: list[Finding] = field(default_factory=list)
    core_version: str = ""
    checked_at: str = ""
    #: The highest level evaluated (``through=`` of :func:`maturity_report`); None: all.
    evaluated_through: str | None = None

    def as_dict(self) -> dict[str, Any]:
        index = [lv[0] for lv in LEVELS].index(self.level) + 1 if self.level else 0
        return {
            "schema": REPORT_SCHEMA,
            "kind": "maturity-report",
            "core_version": self.core_version,
            "checked_at": self.checked_at,
            "level": self.level,
            "level_index": index,
            "evaluated_through": self.evaluated_through or LEVELS[-1][0],
            "library_maturity": supported_label(self.level),
            "levels": self.levels,
            "model_basis": self.model_basis,
            "cases": self.cases,
            "assumptions": self.assumptions,
            "unresolved": self.unresolved,
            "limitations": self.limitations,
            "artifacts": self.artifacts,
            "review": self.review,
            "manifest": self.manifest,
            "source": self.source,
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "level": f.level,
                    "rule": f.rule,
                    "message": f.message,
                    "hint": f.hint,
                }
                for f in self.findings
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, ensure_ascii=False)


def supported_label(level: str | None) -> str | None:
    """The highest library ``maturity`` label *level* supports (None: none)."""
    return next((label for lid, _, label in LEVELS if lid == level), None)


# -- helpers --------------------------------------------------------------------------------------


def _version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("cheme-as-code")
    except PackageNotFoundError:
        return "unknown"


def _shown(items: list[str], limit: int = 6) -> str:
    text = ", ".join(items[:limit])
    return text + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _read_yaml(path: Path) -> tuple[Any, str]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), ""
    except (OSError, yaml.YAMLError) as failure:
        return None, str(failure).splitlines()[0]


def _assumed_count(data: Any) -> int:
    """Values with ``provenance: assumed`` anywhere in *data*."""
    if isinstance(data, dict):
        own = 1 if data.get("provenance") == "assumed" else 0
        return own + sum(_assumed_count(v) for v in data.values())
    if isinstance(data, list):
        return sum(_assumed_count(v) for v in data)
    return 0


# -- level 1: sourced process description ---------------------------------------------------------


def _sourced(root: Path, process: Any, findings: list[Finding]) -> list[Requirement]:
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.requirements.schemas import DesignBasis

    out = []
    req = Requirement(
        "sourced.flowsheet", "sourced", "process flowsheet loads", file=FLOWSHEET_FILE
    )
    errors = [f for f in findings if f.level == "error"]
    if not (root / FLOWSHEET_FILE).is_file():
        req.status, req.hint = "missing", "write process/flowsheet.yaml (kind: flowsheet)"
    elif process is None or errors:
        first = errors[0] if errors else None
        req.status = "fail"
        req.detail = first.message if first else "it does not load"
        req.file, req.line = (first.file, first.line) if first else (FLOWSHEET_FILE, None)
        req.hint = "run cheme validate and fix the schema errors"
    out.append(req)

    req = Requirement(
        "sourced.design-basis",
        "sourced",
        "design basis: capacity, feeds and products",
        file=DESIGN_BASIS_FILE,
    )
    path = root / DESIGN_BASIS_FILE
    if not path.is_file():
        req.status = "missing"
        req.hint = (
            "write process/design-basis.yaml (capacity, feeds, products; cheme schema design_basis)"
        )
    else:
        from chemeascode.foundation.provenance import file_fingerprint

        req.evidence["fingerprint"] = file_fingerprint(path)
        data, problem = _read_yaml(path)
        try:
            basis = DesignBasis.model_validate(data or {}) if not problem else None
        except ValueError as failure:
            basis, problem = None, str(failure).splitlines()[0]
        if basis is None:
            req.status, req.detail, req.hint = "fail", problem, "run cheme validate"
        else:
            empty = [
                name
                for name, value in (
                    ("capacity", basis.capacity),
                    ("feeds", basis.feeds),
                    ("products", basis.products),
                )
                if not value
            ]
            req.evidence["assumptions"] = len(basis.assumptions)
            if empty:
                req.status = "fail"
                req.detail = "empty: " + ", ".join(empty)
                req.hint = "state the capacity, the feeds and the products with their sources"
    out.append(req)

    req = Requirement(
        "sourced.boundary",
        "sourced",
        "feeds and products declared; feed flows and compositions given with a source",
        file=FLOWSHEET_FILE,
    )
    if process is None:
        req.status, req.detail = "missing", "no flowsheet"
    else:
        fs = process.flowsheet
        problems = []
        if not fs.feeds or not fs.products:
            problems.append("the flowsheet declares no " + ("feed" if not fs.feeds else "product"))
        unsourced = []
        feeds = {f.id for f in fs.feeds}
        for index, stream in enumerate(fs.streams):
            start, _ = process.ends(stream)
            if stream.kind != "material" or start is None or start.node not in feeds:
                continue
            for case in fs.cases:
                state = stream.state.get(case.id)
                for name in ("flow", "composition"):
                    value = getattr(state, name, None) if state is not None else None
                    if value is None or value.provenance != "given" or not value.source.strip():
                        if not unsourced:
                            req.line = _yaml_line(process.flowsheet_doc, ["streams", index])
                        unsourced.append(f"{stream.id} {name} ({case.id})")
        if unsourced:
            problems.append("not given with a source: " + _shown(unsourced))
        req.evidence["feed_values_unsourced"] = unsourced
        if problems:
            req.status, req.detail = "fail", "; ".join(problems)
            req.hint = "give the feed flows and compositions with provenance given and a source"
    out.append(req)
    return out


# -- level 2: balanced conceptual PFD -------------------------------------------------------------


def _balances(process: Any) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str], bool]:
    """Per case the balance entries (with residual and tolerance), the not-evaluable and the
    imbalanced ones as text, and whether a dynamic scope makes one unsupported."""
    from chemeascode.domains.process.model import balances

    fs = process.flowsheet
    per_case: dict[str, list[dict[str, Any]]] = {}
    open_: list[str] = []
    failing: list[str] = []
    unsupported = False
    for case in fs.cases:
        rows = []
        for b in balances(process, case.id):
            if b.status == "no-streams":
                continue
            node = process.nodes.get(b.node)
            tol = getattr(node, "tolerance", None) or fs.tolerance
            row = b.entry()
            row["residual_kg_h"] = round(b.inlet - b.outlet, 6)
            row["tolerance"] = {"abs_kg_h": tol.abs, "rel": tol.rel}
            if b.status == "unsupported":
                unsupported = True
            elif b.status == "not-evaluable" or b.missing:
                open_.append(f"{b.node} ({case.id}): {_shown(b.missing, 3) or 'not evaluable'}")
            if b.status == "imbalance":
                failing.append(f"{b.node} ({case.id}): {'; '.join(b.failing[:2])}")
            rows.append(row)
        per_case[case.id] = rows
    return per_case, open_, failing, unsupported


def _balanced(process: Any, bases: list[Any]) -> tuple[list[Requirement], dict[str, Any]]:
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.model import rules

    out = []
    req = Requirement(
        "balanced.process-rules",
        "balanced",
        "no error in the process rules (units, ports, reactions, reactors)",
        file=FLOWSHEET_FILE,
    )
    if process is None:
        req.status, req.detail = "missing", "no flowsheet"
    else:
        errors = [
            f
            for f in rules(process)
            if f.level == "error" and not f.rule.startswith("cheme.process-balance")
        ]
        req.evidence["errors"] = len(errors)
        if errors:
            req.status = "fail"
            req.file, req.line = errors[0].file, errors[0].line
            req.detail = f"{len(errors)} error(s), first: {errors[0].rule}: {errors[0].message}"
            req.hint = "run cheme validate"
    out.append(req)

    evaluable = Requirement(
        "balanced.balances-evaluable",
        "balanced",
        "every block and step balance evaluable in every case (mass and components or elements)",
        file=FLOWSHEET_FILE,
    )
    closed = Requirement(
        "balanced.balances-closed",
        "balanced",
        "every balance closes within the flowsheet's explicit tolerance",
        file=FLOWSHEET_FILE,
    )
    summary: dict[str, Any] = {}
    if process is None:
        evaluable.status = closed.status = "missing"
        evaluable.detail = closed.detail = "no flowsheet"
    else:
        per_case, open_, failing, unsupported = _balances(process)
        summary = {"open": open_, "failing": failing}
        closed.evidence["balances"] = per_case
        evaluable.evidence["not_evaluable"] = open_
        if unsupported:
            evaluable.status = "unsupported"
            evaluable.detail = "a block has balance_scope: dynamic"
        elif open_:
            evaluable.status = "fail"
            evaluable.detail = _shown(open_, 4)
            evaluable.hint = "give the missing flows and compositions (cheme process propagate)"
        if not any(per_case.values()):
            closed.status, closed.detail = "missing", "no balance to evaluate"
        elif failing:
            closed.status, closed.detail = "fail", _shown(failing, 4)
            closed.hint = "correct the stream values until the balances close"
        elif open_:
            closed.status = "fail"
            closed.detail = "only partly evaluable: an open balance cannot be shown closed"
            closed.hint = "give the values balanced.balances-evaluable names"
    out += [evaluable, closed]

    req = Requirement(
        "balanced.model-basis",
        "balanced",
        "every reactor and separator rests on a sourced model or sourced specified values",
        file=FLOWSHEET_FILE,
    )
    weak = [u for u in bases if not u.sourced]
    req.evidence["units"] = {u.id: u.basis for u in bases}
    backed = {u.id: u.evidence for u in bases if u.evidence}
    if backed:  # process/reaction-evidence.yaml against the specified conversions
        req.evidence["reaction_evidence"] = backed
    if process is None:
        req.status, req.detail = "missing", "no flowsheet"
    elif weak:
        req.status = "fail"
        req.file, req.line = weak[0].file, weak[0].line
        req.detail = _shown([f"{u.id}: {u.basis}, {u.detail}" for u in weak], 3)
        req.hint = (
            "give the specified values with provenance given and a source (a conversion: or "
            "observations of the decided model basis of process/reaction-evidence.yaml that "
            "cover it), or declare a reactor/separator model whose data are given"
        )
    elif not bases:
        req.detail = "no reactor or separator"
    out.append(req)

    out.append(_energy_balances(process))
    return out, summary


# -- level 3: converged predictive simulation -----------------------------------------------------


def _predictive(
    root: Path,
    process: Any,
    bases: list[Any],
    balanced: dict[str, Requirement],
    sim_state: dict[str, Any],
) -> list[Requirement]:
    from chemeascode.domains.process.simulation import SIMULATION_FILE, record

    out = []
    sim = sim_state.get("sim")
    spec = Requirement(
        "predictive.simulation-spec",
        "predictive",
        "process/simulation.yaml translates into a simulator model for every case",
        file=SIMULATION_FILE,
    )
    translations = sim_state.get("translations", {})
    if not (root / SIMULATION_FILE).is_file():
        spec.status, spec.hint = "missing", "write process/simulation.yaml (kind: simulation)"
    elif sim is None or process is None:
        spec.status = "fail"
        spec.detail = "; ".join(f.message for f in sim_state.get("findings", [])[:2])
        spec.hint = "run cheme process simulate --check"
    else:
        refused = [c for c, t in translations.items() if t.model is None]
        if refused:
            errors = [f for f in translations[refused[0]].findings if f.level == "error"]
            spec.status = "fail"
            if errors:
                spec.file, spec.line = errors[0].file, errors[0].line
            message = errors[0].message if errors else "no model made"
            spec.detail = f"refused for case {', '.join(refused)}: {message}"
            spec.hint = "run cheme process simulate --check"
    out.append(spec)

    data = record.read(root)
    rec = Requirement(
        "predictive.run-record",
        "predictive",
        "a run record for every case",
        file=record.RUN_FILE,
    )
    current = Requirement(
        "predictive.current",
        "predictive",
        "every run record is current: simulated from the inputs as they are (fingerprints)",
        file=record.RUN_FILE,
    )
    converged = Requirement(
        "predictive.converged",
        "predictive",
        "every recorded run converged without errors",
        file=record.RUN_FILE,
    )
    solver = Requirement(
        "predictive.solver",
        "predictive",
        "simulator, simulator version, property package and core version recorded",
        file=record.RUN_FILE,
    )
    cases = [c.id for c in process.flowsheet.cases] if process is not None else []
    entries = {c: record.entry_of(data, c) for c in cases}
    absent = [c for c, e in entries.items() if e is None]
    if process is None or not cases or len(absent) == len(cases):
        for req in (rec, current, converged, solver):
            req.status = "missing"
            req.detail = f"no run recorded in {record.RUN_FILE}"
            req.hint = "run cheme process simulate --fill (it records the run)"
    else:
        from chemeascode.foundation.provenance import source_revision

        fingerprints = source_revision(root, record.RUN_INPUTS).fingerprints
        if absent:
            rec.status, rec.detail = "missing", "no run for case " + ", ".join(absent)
            rec.hint = "run cheme process simulate --fill --case <case>"
        stale, unconverged, unpinned = [], [], []
        for case, entry in entries.items():
            if entry is None:
                continue
            translation = translations.get(case)
            now = translation.fingerprint if translation and translation.model else None
            state = record.staleness(entry, now, fingerprints)
            errors = [f for f in entry.get("findings", []) if f.get("level") == "error"]
            current.evidence[case] = {
                "run_at": entry.get("run_at"),
                **state,
            }
            converged.evidence[case] = {
                "converged": entry.get("converged"),
                "status": entry.get("status"),
                "iterations": entry.get("iterations"),
                "messages": entry.get("messages", [])[:5],
                "errors": [f.get("message") for f in errors][:5],
            }
            simulator = entry.get("simulator") or {}
            solver.evidence[case] = {
                "simulator": simulator.get("name"),
                "version": simulator.get("version"),
                "property_package": entry.get("property_package"),
                "tool": entry.get("tool"),
            }
            if state["stale"] is not False:
                stale.append(case)
            if not entry.get("converged") or errors:
                unconverged.append(case)
            if not simulator.get("version") or not entry.get("tool"):
                unpinned.append(case)
        if stale:
            current.status = "fail"
            current.detail = "stale or not comparable for case " + ", ".join(stale)
            current.hint = "run cheme process simulate --fill"
        if unconverged:
            converged.status = "fail"
            converged.detail = "not converged or with errors: case " + ", ".join(unconverged)
            converged.hint = "fix the specs until the simulation converges without errors"
        if unpinned:
            solver.status, solver.detail = "fail", "version missing: " + ", ".join(unpinned)
            solver.hint = "rerun cheme process simulate --fill with a current core"
    out += [rec, current, converged, solver]

    coverage = Requirement(
        "predictive.coverage",
        "predictive",
        "every step simulated: none excluded and left at specified values",
        file=SIMULATION_FILE,
    )
    if sim is None or process is None:
        coverage.status, coverage.detail = "missing", "no simulation"
        coverage.hint = "write process/simulation.yaml and run cheme process simulate --fill"
    else:
        left_out = record.excluded(process, sim)
        coverage.evidence["excluded"] = left_out
        if left_out:
            coverage.status = "fail"
            coverage.detail = "excluded: " + _shown(sorted(left_out))
            coverage.hint = "their streams stay specified; simulate them to claim predictive"
    out.append(coverage)

    physical = Requirement(
        "predictive.balances",
        "predictive",
        "physical validity: the balances of the simulated flowsheet close within tolerance",
        file=balanced["balanced.balances-closed"].file,
    )
    for key in ("balanced.balances-evaluable", "balanced.balances-closed"):
        if balanced[key].status != "pass":
            physical.status = "fail" if balanced[key].status == "fail" else balanced[key].status
            physical.detail = f"{key}: {balanced[key].detail}"
            physical.hint = balanced[key].hint
            break
    out.append(physical)

    basis = Requirement(
        "predictive.model-basis",
        "predictive",
        "every reactor and separator predicted by a model: specified splits, conversions and "
        "stream values cap the level at balanced",
        file=SIMULATION_FILE if sim is not None else "process/flowsheet.yaml",
    )
    specified = [u for u in bases if not u.predictive]
    unsimulated = [u for u in bases if u.predictive and not u.simulated]
    if process is None:
        basis.status, basis.detail = "missing", "no flowsheet"
    elif specified or unsimulated:
        basis.status = "fail"
        first = (specified or unsimulated)[0]
        basis.file, basis.line = first.file, first.line
        parts = [f"specified: {u.id} ({u.basis})" for u in specified]
        parts += [f"not in the simulation: {u.id} ({u.basis})" for u in unsimulated]
        basis.detail = _shown(parts, 4)
        basis.hint = "replace specified splits and conversions by predictive unit models"
    out.append(basis)

    out.append(_property_package(sim, sim_state.get("doc")))
    out.append(_property_regime(sim, process, entries, translations))
    if process is not None:
        out.append(_stream_properties(process))
    out += _energy_audit(process, data, cases)
    out.append(_formation_data(process, data, cases))
    return out


def _property_regime(
    sim: Any, process: Any, entries: dict[str, Any], translations: dict[str, Any]
) -> Requirement:
    """``predictive.property-regime``: the simulation's property package has a benchmarked
    range in methods.yml (:func:`~chemeascode.domains.process.thermodynamics.methods.
    simulation_claim`) and every state DWSIM evaluated with it lies inside: the feeds of each
    recorded case (from its translation, as the worker got them) and the material streams the
    run record holds (energy streams carry no state), from the simulator version benchmarked
    and with the package's own interaction parameters. On a pass the properties the claim
    does not cover are listed as limitations, with the mixture streams whose density they
    would concern. Unsupported for a package without a claim."""
    from chemeascode.domains.process.simulation import SIMULATION_FILE, record
    from chemeascode.domains.process.thermodynamics.methods import (
        application_range,
        outside_claim,
        simulation_claim,
    )
    from chemeascode.foundation.units import to_kelvin, to_kpa_abs

    req = Requirement(
        "predictive.property-regime",
        "predictive",
        "the property methods are used inside their declared regimes",
        file=SIMULATION_FILE,
    )
    if sim is None:
        req.status, req.detail = "missing", "no simulation"
        req.hint = "write process/simulation.yaml (its property package)"
        return req
    req.evidence["property_package"] = sim.property_package
    claim = simulation_claim(sim.property_package)
    if claim is None:
        claimed = application_range("simulation")
        req.status = "unsupported"
        req.detail = (
            f"the DWSIM route claims no application range for '{sim.property_package}' "
            f"(thermodynamics/methods.yml: {claimed}), so no stream can be shown inside one"
        )
        req.hint = (
            "satisfied once methods.yml declares a range for this package that a test "
            "benchmarks against reference data, and every simulated stream lies inside it"
        )
        req.evidence["route_application_range"] = claimed
        return req
    req.evidence["claim"] = {
        "simulator_version": claim.simulator_version,
        "components": dict(claim.components),
        "properties": list(claim.properties),
        "not_claimed": list(claim.not_claimed),
        "tolerances": dict(claim.tolerances),
        "benchmark": claim.benchmark.test,
    }
    components = process.components() if process is not None else {}
    kinds = {s.id: s.kind for s in process.flowsheet.streams} if process is not None else {}
    problems: list[str] = []
    #: (case, stream, "feed" or "stream") of every state checked
    states: list[tuple[str, str, str]] = []
    mixtures: list[str] = []

    # The run record holds no phase: a claim limited to some phases cannot be shown to hold.
    unjudged_phases = not {"vapor", "liquid", "two-phase"} <= set(claim.phases)

    def check(case: str, sid: str, what: str, kelvin: Any, kpa: Any, present: set) -> None:
        states.append((case, sid, what))
        if kelvin is None or kpa is None:
            problems.append(f"case {case}, {what} {sid}: units not convertible")
            return
        if unjudged_phases:
            problems.append(
                f"case {case}, {what} {sid}: phase not recorded, so it cannot be shown inside "
                f"the claimed phases ({', '.join(claim.phases)})"
            )
        if len(present) > 1:
            mixtures.append(f"{sid} ({case})")
        for why in outside_claim(claim, kelvin, kpa, present):
            problems.append(f"case {case}, {what} {sid}: {why}")

    if sim.interaction_parameters:
        pairs = ", ".join("-".join(p.components) for p in sim.interaction_parameters)
        problems.append(
            f"simulation.yaml sets interaction parameters ({pairs}); the claim holds for "
            "DWSIM's own"
        )
    recorded = {c: e for c, e in entries.items() if e is not None}
    for case, entry in recorded.items():
        version = str((entry.get("simulator") or {}).get("version") or "")
        if version.split(".")[:3] != claim.simulator_version.split("."):
            problems.append(
                f"case {case}: run with DWSIM {version or '(no version)'}, the claim is "
                f"benchmarked on {claim.simulator_version}"
            )
        # the feeds: the record holds the simulated outlets only, DWSIM flashes the feeds too
        translation = translations.get(case)
        model = translation.model if translation is not None else None
        if model is None:
            problems.append(f"case {case}: no simulator model, so its feeds cannot be checked")
        else:
            cas = {c["id"]: c.get("cas") or None for c in model["compounds"]}
            for s in model["streams"]:
                feed = s.get("feed")
                if s.get("kind") != "material" or not feed:
                    continue
                present = {cas.get(cid) for cid, v in feed["mole_fractions"].items() if v > 0}
                kpa = feed["pressure_Pa"] / 1000.0
                check(case, s["id"], "feed", feed["temperature_K"], kpa, present)
        rows = entry.get("streams", [])
        # every simulated outlet has its row; one without cannot be shown inside the claim (a
        # record without any row is missing, below)
        recorded_ids = {str(row.get("id")) for row in rows}
        for sid in translation.outlets if translation is not None and rows else []:
            if kinds.get(sid) == "material" and sid not in recorded_ids:
                problems.append(f"case {case}, stream {sid}: no simulated state recorded")
        for row in rows:
            sid = str(row.get("id"))
            if kinds.get(sid, "material") != "material":
                continue  # an energy stream: a duty, no state
            values = row.get("values") or {}
            t, p, x = (values.get(k) for k in ("temperature", "pressure", "composition"))
            if not (t and p and x):
                problems.append(f"case {case}, stream {sid}: no simulated state")
                continue
            present = {
                getattr(components.get(cid), "cas", None) or None
                for cid, v in (x.get("values") or {}).items()
                if v and v > 0
            }
            kelvin = to_kelvin(t["value"], t.get("unit") or "K")
            kpa = to_kpa_abs(p["value"], p.get("unit") or "kPa(a)")
            check(case, sid, "stream", kelvin, kpa, present)
    feeds = sum(1 for s in states if s[2] == "feed")
    req.evidence["states_checked"] = len(states)
    req.evidence["feeds_checked"] = feeds
    if problems:
        req.status = "fail"
        req.detail = _shown(problems, 3)
        req.hint = (
            "keep every feed and stream inside the claimed boxes of the package "
            f"(thermodynamics/methods.yml, benchmarked by {claim.benchmark.test}), or extend "
            "the benchmark"
        )
        req.evidence["outside"] = problems[:20]
    elif not recorded:
        req.status, req.detail = "missing", f"no run recorded in {record.RUN_FILE}"
        req.hint = "run cheme process simulate --fill (the regime is checked on its streams)"
    elif not any(s[2] == "stream" for s in states):
        req.status, req.detail = "missing", "the run records hold no simulated stream state"
        req.hint = "run cheme process simulate --fill"
    else:
        req.detail = (
            f"{len(states)} state(s) ({feeds} feed(s), {len(states) - feeds} simulated "
            f"stream(s)) inside the benchmarked range of '{sim.property_package}' "
            f"({claim.benchmark.test}); claimed: {'; '.join(claim.properties)}"
        )
        # inside the boxes is no more than the benchmark: what it does not claim stays listed
        limitations = [f"not claimed by {claim.benchmark.test}: {t}" for t in claim.not_claimed]
        if mixtures:
            limitations.append(
                "mixture states whose density (liquid or gas) the claim does not cover: "
                + _shown(sorted(set(mixtures)), 8)
            )
        req.evidence["limitations"] = limitations
    return req


def _property_package(sim: Any, doc: Any) -> Requirement:
    """``predictive.property-package``: the supported-method contract of the package
    (:func:`~chemeascode.domains.process.simulation.translate.property_package_findings`):
    supported by the worker, and recommended by a recorded selection or substituted with a
    recorded reason."""
    from chemeascode.domains.process.simulation import SIMULATION_FILE

    req = Requirement(
        "predictive.property-package",
        "predictive",
        "the property package is supported and recommended by a recorded method selection "
        "(or a recorded substitution)",
        file=SIMULATION_FILE,
    )
    if sim is None:
        req.status, req.detail = "missing", "no simulation"
        req.hint = "write process/simulation.yaml (its property package)"
        return req
    from chemeascode.domains.process.simulation.translate import property_package_findings

    found = property_package_findings(sim, doc, require_selection=True)
    req.evidence["property_package"] = sim.property_package
    req.evidence["findings"] = [
        {"rule": f.rule, "level": f.level, "message": f.message} for f in found
    ]
    bad = [f for f in found if f.level in ("error", "warning")]
    unrecorded = [f for f in found if f.rule == "cheme.process-sim-method-unrecorded"]
    substituted = [f for f in found if f.rule == "cheme.process-sim-method-substituted"]
    first = (bad or unrecorded or [None])[0]
    if first is not None:
        req.status = "fail" if bad else "missing"
        req.line, req.detail, req.hint = first.line, first.message, first.hint
    elif substituted:
        req.evidence["substitution"] = substituted[0].message
    return req


def _stream_properties(process: Any) -> Requirement:
    """``predictive.stream-properties``: every stream with calculated properties is covered by
    the process's property package (:func:`chemeascode.domains.process.props.choose_package`,
    the per-stream coverage of ``cheme process props --coverage``)."""
    from chemeascode.domains.process import FLOWSHEET_FILE, MATERIALS_FILE
    from chemeascode.domains.process.fill import coverage
    from chemeascode.domains.process.props import choose_package

    req = Requirement(
        "predictive.stream-properties",
        "predictive",
        "every stream with calculated properties lies inside the benchmarked claim of the "
        "process's property package",
        file=FLOWSHEET_FILE,
    )
    choice = choose_package(process)
    package = choice.package
    req.evidence["package"] = package.id if package else None
    req.evidence["reason"] = choice.reason
    if package is not None:
        req.evidence["benchmark"] = {
            "test": package.benchmark.test,
            "reference": package.benchmark.reference,
            "tolerances": dict(package.benchmark.tolerances),
        }
    with_props = {
        (s.id, case)
        for s in process.flowsheet.streams
        if s.kind == "material"
        for case, state in s.state.items()
        if state.calculated
    }
    req.evidence["streams_with_calculated_properties"] = sorted(f"{s} ({c})" for s, c in with_props)
    if not with_props:
        req.detail = "no stream has calculated properties"
        return req
    uncovered = []
    rows: dict[str, list[dict[str, Any]]] = {}
    for case in sorted({c for _, c in with_props}):
        found = coverage(process, case).coverage or {}
        rows[case] = found.get("streams", [])
        for row in rows[case]:
            if (row["id"], case) in with_props and row.get("status") != "covered":
                uncovered.append(f"{row['id']} ({case}): {row.get('status')}: {row.get('reason')}")
    req.evidence["coverage"] = rows
    if package is None:
        req.status, req.file = "fail", MATERIALS_FILE
        req.detail = f"no property package: {choice.reason}"
        req.hint = "name a package cheme process props --coverage lists"
    elif uncovered:
        req.status = "fail"
        req.detail = _shown(uncovered, 3)
        req.hint = (
            "keep the calculated properties inside the package's benchmarked claim, or use a "
            "package whose benchmark covers them (cheme process props --coverage)"
        )
    return req


def _energy_balances(process: Any) -> Requirement:
    """``balanced.energy-closure`` (not required): the flowsheet's energy balances per block
    and step (:func:`chemeascode.domains.process.energy.energy_balances`), as evidence."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.domains.process.energy import energy_balances

    req = Requirement(
        "balanced.energy-closure",
        "balanced",
        "energy balances of the blocks and steps (stream enthalpies against energy streams)",
        required=False,
        file=FLOWSHEET_FILE,
    )
    if process is None:
        req.status, req.detail = "missing", "no flowsheet"
        return req
    by_status: dict[str, list[str]] = {}
    rows: dict[str, list[dict[str, Any]]] = {}
    for case in process.flowsheet.cases:
        found = [b for b in energy_balances(process, case.id) if b.status != "no-streams"]
        rows[case.id] = [b.entry() for b in found]
        for b in found:
            by_status.setdefault(b.status, []).append(f"{b.node} ({case.id})")
    req.evidence["balances"] = rows
    req.evidence["by_status"] = by_status
    if by_status.get("imbalance"):
        req.status, req.detail = "fail", "imbalance: " + _shown(by_status["imbalance"], 4)
        req.hint = "check the duties and the calculated enthalpies of those nodes"
    elif by_status.get("ok") and not (
        by_status.get("not-evaluable") or by_status.get("unsupported")
    ):
        req.detail = f"{len(by_status['ok'])} balance(s) close"
    elif by_status.get("unsupported"):
        req.status = "unsupported"
        req.detail = "the enthalpy reference does not allow the balance at " + _shown(
            by_status["unsupported"], 4
        )
    else:
        req.status = "missing"
        req.detail = "no balance evaluable: stream enthalpies or duties missing"
        req.hint = "cheme process props --fill writes the enthalpies"
    return req


def _furnace_energy(root: Path) -> Requirement:
    """``balanced.furnace-energy`` (not required; only with ``process/furnaces.yaml``): the
    energy basis of each solid-reaction furnace (:mod:`chemeascode.domains.process.furnace`).
    It passes when every furnace is calculated (not the specific-energy fallback) and closes;
    a refused furnace (an unsupported reaction, data out of range, Cantera missing) is
    unsupported. The degree of calcination stays given: nothing here is predictive."""
    from chemeascode.domains.process.furnace import (
        ASSUMPTIONS,
        FURNACES_FILE,
        NOT_CLAIMED,
        furnace_report,
    )

    req = Requirement(
        "balanced.furnace-energy",
        "balanced",
        "energy basis of the solid-reaction furnaces: element balance and furnace energy "
        "closure from condensed-phase data",
        required=False,
        file=FURNACES_FILE,
    )
    report = furnace_report(root)
    req.evidence["furnaces"] = [
        {
            "id": r.id,
            "basis": r.basis,
            "mode": r.mode,
            "heat_input_kW": r.heat_input_kW,
            "heat_input_range_kW": r.heat_input_range_kW,
            "residual_kW": r.residual_kW,
            "tolerance_kW": r.tolerance_kW,
            "specific_energy_GJ_t": r.specific_energy_GJ_t,
            "closed": r.closed,
        }
        for r in report.results
    ]
    req.evidence["limitations"] = [f"furnace: assumed {a}" for a in ASSUMPTIONS] + [
        f"furnace: not claimed: {n}" for n in NOT_CLAIMED
    ]
    errors = [f for f in report.findings if f.level == "error"]
    refused = [
        f
        for f in errors
        if f.rule
        in ("cheme.furnace-unsupported", "cheme.furnace-data-range", "cheme.furnace-extra")
    ]
    first = (errors or [f for f in report.findings if f.level == "warning"] or [None])[0]
    if first is not None:
        req.line = first.line
    fallback = [r.id for r in report.results if r.mode == "fallback"]
    if refused:
        req.status = "unsupported"
        req.detail = "; ".join(f.message for f in refused[:3])
        req.hint = refused[0].hint
    elif errors or not report.results:
        req.status = "fail" if report.results else "missing"
        req.detail = "; ".join(f.message for f in errors[:3]) or "no furnace declared"
        req.hint = errors[0].hint if errors else "declare the furnaces in process/furnaces.yaml"
    elif any(r.closed is False for r in report.results):
        req.status = "fail"
        req.detail = "not closed: " + ", ".join(r.id for r in report.results if r.closed is False)
        req.hint = "cheme process furnace shows the residual of each"
    elif fallback:
        req.status = "missing"
        req.detail = "conceptual fallback (specific heat use), no energy balance: " + ", ".join(
            fallback
        )
        req.hint = "declare fuel, air and losses and use method: energy-balance"
    else:
        req.detail = f"{len(report.results)} furnace(s) calculated and closed"
    return req


def _formation_data(process: Any, data: Any, cases: list[str]) -> Requirement:
    """``predictive.formation-data``: the reaction heat the simulator applies (its database's
    formation enthalpies) agrees with the formation enthalpies declared in materials, reactor by
    reactor (the energy audit's recorded DWSIM values and component changes, compared again with
    the formation enthalpies in materials now: :func:`...energy.recompare`). Declared values that
    differ beyond the data tolerance (simulation/energy.py DATA_TOLERANCE, 1 % of the reaction
    heat) fail; a smaller nonzero difference, chemicals' fallback values that differ, or a
    reacting component without a value are limitations, not a failure."""
    from chemeascode.domains.process.simulation import record
    from chemeascode.domains.process.simulation.energy import REACTORS, recompare

    req = Requirement(
        "predictive.formation-data",
        "predictive",
        "the simulated reaction heat agrees with the formation enthalpies declared in "
        "process/materials.yaml",
        file=record.RUN_FILE,
    )
    entries = {c: record.entry_of(data, c) for c in cases}
    audits = {c: e.get("energy") for c, e in entries.items() if e is not None}
    if process is None or not audits or not all(isinstance(a, dict) for a in audits.values()):
        req.status, req.detail = "missing", "no energy audit recorded"
        req.hint = "run cheme process simulate --fill (it records the energy audit)"
        return req
    failing, limited, open_, reactors = [], [], [], 0
    for case, audit in audits.items():
        compared = {}
        # against materials as they are now: the declared values are not in the run's
        # fingerprint, so the comparison stored at simulate time may describe older values
        current = recompare(process, audit)
        for row in (audit.get("closure") or {}).get("units") or []:
            if row.get("unit") not in REACTORS:
                continue
            reactors += 1
            found = current.get(row["id"], row.get("formation_data"))
            compared[row["id"]] = found
            where = f"{row['id']} ({case})"
            if found is None:
                open_.append(f"{where}: {row.get('reason') or 'not compared'}")
            else:
                if found["status"] == "declared-differs":
                    differing = [
                        f"{x['id']} {x['difference_kJ_kmol']:+.6g} kJ/kmol"
                        for x in found["components"]
                        if x["origin"] == "declared" and x["difference_kJ_kmol"]
                    ]
                    failing.append(
                        f"{where}: {found['declared_difference_kW']:.4g} kW (data tolerance "
                        f"{found['data_tolerance_kW']:.3g} kW): {', '.join(differing)}"
                    )
                limited += [f"case {case}: {text}" for text in found.get("limitations") or []]
                if found["status"] == "not-compared":
                    limited.append(f"{where}: no reacting component has a project value")
        req.evidence[case] = compared
    if not reactors:
        req.detail = "no reacting unit in the simulated plant"
    elif failing:
        req.status, req.detail = "fail", "; ".join(failing)
        req.hint = (
            "the simulator's reactor duty rests on other formation enthalpies than the declared "
            "ones: check both sources and say which the design rests on; never edit a value to "
            "pass"
        )
    elif open_:
        req.status = "unsupported"
        req.detail = "not compared: " + "; ".join(open_)
        req.hint = "satisfied once every reactor's energy closure is evaluated"
    elif limited:
        req.detail = "limitations: " + "; ".join(limited)
        req.evidence["limitations"] = limited
    return req


def _energy_audit(process: Any, data: Any, cases: list[str]) -> list[Requirement]:
    """``predictive.energy-closure`` and ``predictive.exchangers``: the energy audit each run
    record keeps under ``energy`` (:mod:`chemeascode.domains.process.simulation.energy`)."""
    from chemeascode.domains.process.simulation import record

    closure = Requirement(
        "predictive.energy-closure",
        "predictive",
        "the simulated plant's enthalpy flows close with its heat and work within tolerance",
        file=record.RUN_FILE,
    )
    exchangers = Requirement(
        "predictive.exchangers",
        "predictive",
        "no exchanger temperature cross or approach below its minimum, every utility level "
        "can serve its duty",
        file=record.RUN_FILE,
    )
    entries = {c: record.entry_of(data, c) for c in cases}
    audits = {c: e.get("energy") for c, e in entries.items() if e is not None}
    if process is None or not audits:
        for req in (closure, exchangers):
            req.status, req.detail = "missing", "no run recorded"
            req.hint = "run cheme process simulate --fill (it records the energy audit)"
        return [closure, exchangers]
    older = [c for c, a in audits.items() if not isinstance(a, dict)]
    if older:
        for req in (closure, exchangers):
            req.status = "missing"
            req.detail = "no energy audit in the run of case " + ", ".join(older)
            req.hint = "the run was recorded before the audit existed: rerun simulate --fill"
        return [closure, exchangers]
    failing, unsupported, stated = [], [], []
    for case, audit in audits.items():
        plant = (audit.get("closure") or {}).get("plant") or {}
        closure.evidence[case] = plant
        status = plant.get("status")
        if status == "imbalance":
            failing.append(
                f"case {case}: residual {plant.get('residual_kW', 0):.4g} kW, tolerance "
                f"{plant.get('tolerance_kW', 0):.4g} kW"
            )
        elif status != "ok":
            reasons = "; ".join(plant.get("reasons") or []) or "no reason recorded"
            unsupported.append(f"case {case}: {status}: {reasons}")
        elif plant.get("stated"):
            stated.append(
                f"case {case}: {plant.get('stated_kW', 0):.4g} kW stated by specified splits ("
                + ", ".join(plant["stated"])
                + ")"
            )
    if stated and not failing and not unsupported:
        closure.detail = (
            "closes with the specified splits' imbalances stated, not judged (enthalpy out "
            "minus in): " + "; ".join(stated)
        )
    if failing:
        closure.status, closure.detail = "fail", "; ".join(failing)
        closure.hint = "find the unit whose closure fails (energy.closure.units in the record)"
    elif unsupported:
        closure.status = "unsupported"
        closure.detail = (
            "the plant closure is not evaluated (" + "; ".join(unsupported) + "): a reacting "
            "unit without a heat-of-formation basis (its property package's enthalpy reference "
            "is not verified, or the run did not report DWSIM's formation enthalpies), or a unit "
            "whose duty sign is not established, so energy conservation cannot be shown"
        )
        closure.hint = (
            "satisfied once every unit's closure is evaluable: reactors on a verified package "
            "(simulation/energy.py FORMATION_PACKAGES) in a current run; no column top "
            "without condenser; a component separator recorded before ADR 0038: simulate again"
        )
    bad, open_ = [], []
    for case, audit in audits.items():
        for row in audit.get("exchangers") or []:
            if row.get("status") in ("crossed", "below-min-approach"):
                bad.append(f"{row.get('id')} ({case}): {row['status']}")
            elif row.get("status") == "not-evaluable":
                open_.append(f"{row.get('id')} ({case})")
        for row in audit.get("utility_levels") or []:
            if row.get("status") == "infeasible":
                bad.append(f"{row.get('id')} {row.get('role')} from {row.get('terminal')} ({case})")
        exchangers.evidence[case] = {
            "exchangers": audit.get("exchangers") or [],
            "utility_levels": audit.get("utility_levels") or [],
        }
    if bad:
        exchangers.status, exchangers.detail = "fail", _shown(bad, 4)
        exchangers.hint = "change the exchanger temperatures or the utility level"
    elif open_:
        exchangers.status = "missing"
        exchangers.detail = "not evaluable: " + _shown(open_, 4)
        exchangers.hint = "the record lacks their temperatures or duties: rerun simulate --fill"
    return [closure, exchangers]


# -- level 4: preliminary/basic engineering package -----------------------------------------------


def _engineering(
    workspace: Workspace, validation: Callable[[], Any] | None = None
) -> list[Requirement]:
    """*validation*: returns the ``cheme validate`` report of *workspace* (a gate run passes its
    shared one, so the whole-repository validation, the costly part, runs once)."""
    from chemeascode.domains.process import FLOWSHEET_FILE
    from chemeascode.project.checks import _datasheets

    out = []
    equipment = Requirement(
        "engineering.equipment-list",
        "engineering",
        "an equipment list",
        file="equipment/equipment-list.yaml",
    )
    datasheets = Requirement(
        "engineering.datasheets",
        "engineering",
        "a valid, final datasheet for every equipment item",
        file="equipment/datasheets/",
    )
    pid = Requirement("engineering.pid", "engineering", "P&IDs without errors", file="pid/")
    links = Requirement(
        "engineering.process-links",
        "engineering",
        "every flowsheet link resolves against the lists and the sheets",
        file=FLOWSHEET_FILE,
    )
    has_list = workspace.list_file("equipment") is not None
    pids = workspace.pid_files()
    # A sheet plant.yaml declares is not a P&ID until its file exists.
    drawn = [p for p in pids if p.is_file()]
    if not has_list:
        equipment.status = datasheets.status = "missing"
        equipment.hint = "write equipment/equipment-list.yaml"
        datasheets.hint = "write the equipment list, then cheme datasheets fill"
    else:
        status, detail = _datasheets(workspace)
        if status != "pass":
            datasheets.status, datasheets.detail = "fail", detail
            datasheets.hint = "cheme datasheets fill, then complete them"
    if not drawn:
        pid.status, pid.hint = "missing", "draft the P&IDs (cheme sheet new)"
        if pids:
            names = sorted(workspace.relative(p) for p in pids)
            pid.detail = "no declared P&ID sheet is drawn: " + _shown(names)
    if has_list or pids:
        from chemeascode.project.validate import validate_workspace

        report = validation() if validation is not None else validate_workspace(workspace)
        errors = [f for f in report.findings if f.level == "error" and f.accepted is None]
        if has_list:
            listed = [f for f in errors if f.file.startswith("equipment/")]
            if listed:
                equipment.status = "fail"
                equipment.detail = f"{len(listed)} error(s), first: {listed[0].message}"
                equipment.hint = "run cheme validate"
        sheets = {workspace.relative(p) for p in pids}
        on_sheets = [f for f in errors if f.file in sheets]
        # Declared P&IDs without a file are reported on plant.yaml, not on the sheet (process
        # sheets, kind bfd or pfd, get the same rules and are not P&IDs).
        declared = [sheet for sheet in workspace.config().sheets if sheet.kind == "pid"]
        undrawn = [
            f
            for f in report.findings
            if f.rule in ("cheme.missing-sheet", "cheme.sheet-planned") and f.accepted is None
        ]
        not_drawn = [i for f in undrawn for i in f.ids[:1] if i in {sheet.id for sheet in declared}]
        # A P&ID listed outside the repository is never read (cheme.sheet-outside-repo, which
        # names the file in its message and has no ids).
        outside = [
            f.message
            for f in report.findings
            if f.rule == "cheme.sheet-outside-repo" and f.accepted is None
        ]
        not_drawn += [
            sheet.id
            for sheet in declared
            if workspace.sheet_path(sheet.file) is None
            and any(repr(sheet.file) in message for message in outside)
        ]
        pid.evidence["sheets"] = sorted(sheets)
        pid.evidence["not_drawn"] = not_drawn
        if drawn and (on_sheets or not_drawn):
            pid.status = "fail"
            parts = (
                [f"{len(on_sheets)} error(s), first: {on_sheets[0].message}"] if on_sheets else []
            )
            if not_drawn:
                parts.append("not drawn: " + _shown(not_drawn))
            pid.detail = "; ".join(parts)
            pid.hint = (
                "run cheme validate"
                if on_sheets
                else "draw them (cheme sheet new), each at a path inside the repository"
            )
        unresolved = [f for f in report.findings if f.rule == "cheme.process-link-unresolved"]
        if unresolved:
            links.status = "fail"
            links.detail = f"{len(unresolved)} unresolved, first: {unresolved[0].message}"
            links.hint = "resolve them in process/flowsheet.yaml or the lists"
    else:
        links.status, links.detail = "missing", "no equipment list and no P&ID to link to"
        links.hint = "write the equipment list and the P&IDs, then link the flowsheet to them"
    if not (workspace.root / FLOWSHEET_FILE).is_file():
        links.status, links.detail = "missing", f"no {FLOWSHEET_FILE}: no link is checked"
        links.hint = "write the flowsheet and link it to the lists and the sheets"
    out += [equipment, datasheets, pid, links]
    out.append(
        Requirement(
            "engineering.consistency",
            "engineering",
            "datasheet duties and sizes cross-checked against the current simulation",
            status="unsupported",
            required=False,
            file="equipment/datasheets/",
            detail="not cross-checked by this command",
        )
    )
    return out


# -- the other two axes ---------------------------------------------------------------------------

#: Deliverables by kind: globs from the repository root.
ARTIFACTS = {
    "design_basis": [DESIGN_BASIS_FILE],
    "equipment_list": ["equipment/equipment-list.yaml"],
    "datasheets": ["equipment/datasheets/*.yaml"],
    "line_list": ["piping/line-list.yaml"],
    "instrument_list": ["control/instrument-list.yaml"],
    "layout": ["layout/*.yaml"],
    "estimate": ["estimate/*.yaml"],
    "lca": ["lca/*.yaml", "lca/*.csv"],
    "simulation_record": ["process/simulation-run.json"],
}


def _artifacts(workspace: Workspace) -> dict[str, Any]:
    from chemeascode.foundation.provenance import file_fingerprint

    root = workspace.root
    sheets = []
    try:
        declared = workspace.config().sheets
    except ValueError:
        declared = []
    for sheet in declared:
        path = workspace.sheet_path(sheet.file)
        exists = path is not None and path.is_file()
        sheets.append(
            {
                "id": sheet.id,
                "kind": sheet.kind,
                "file": sheet.file,
                "exists": exists,
                "generated": sheet.generator is not None,
                "fingerprint": file_fingerprint(path) if exists and path else None,
            }
        )
    files = {}
    for kind, globs in ARTIFACTS.items():
        found = sorted(
            workspace.relative(p) for g in globs for p in root.glob(g) if workspace.contains(p)
        )
        files[kind] = found
    return {
        "note": "artifact completeness never establishes calculation maturity",
        "sheets": sheets,
        "files": files,
    }


def _manifest(root: Path, level: str | None) -> tuple[dict[str, Any], list[Finding]]:
    """The library manifest's maturity claim against the evidence, and its review status."""
    path = root / MANIFEST_FILE
    supported = supported_label(level)
    out: dict[str, Any] = {"file": None, "supported_maturity": supported}
    findings: list[Finding] = []
    if not path.is_file():
        return out, findings
    data, _ = _read_yaml(path)
    if not isinstance(data, dict) or data.get("schema") != "cheme-as-code/process/v1":
        return out, findings
    claimed = data.get("maturity")
    validation = data.get("validation") if isinstance(data.get("validation"), dict) else {}
    out.update(
        {
            "file": MANIFEST_FILE,
            "claimed_maturity": claimed,
            "review_status": validation.get("status"),
        }
    )
    if claimed in LIBRARY_MATURITY:
        top = LIBRARY_MATURITY.index(supported) if supported else -1
        exceeds = LIBRARY_MATURITY.index(claimed) > top
        out["claim_exceeds_evidence"] = exceeds
        if exceeds:
            findings.append(
                Finding(
                    MANIFEST_FILE,
                    "warning",
                    "cheme.maturity-claim-exceeds",
                    f"design maturity {claimed} claimed; the calculation maturity the "
                    f"evidence reaches supports {supported or 'no design maturity'}",
                    line=_yaml_line(_compose(path), ["maturity"]),
                    hint="lower the claim, or add the evidence the failing requirements name",
                )
            )
    return out, findings


def _review(workspace: Workspace, manifest: dict[str, Any]) -> dict[str, Any]:
    from chemeascode.foundation.reviews import load_records

    records = []
    for record in load_records(workspace):
        front = record.front
        records.append(
            {
                "path": record.name,
                "topic": front.topic if front else None,
                "reviewer_kind": front.reviewer_kind if front else None,
                "reviewed_commit": front.reviewed_commit if front else None,
                "approved_by": front.approved_by if front else None,
            }
        )
    return {
        "note": "set by people only: cheme maturity reads it and never writes it",
        "manifest_status": manifest.get("review_status"),
        "records": records,
    }


# -- the report -----------------------------------------------------------------------------------


def maturity_report(
    root: Path,
    *,
    through: str | None = None,
    validation: Callable[[], Any] | None = None,
) -> MaturityReport:
    """Evaluate the plant repository at *root* (see the module docstring). Read-only.

    *through*: evaluate the levels up to this one only; the levels above are reported with
    status ``not-evaluated`` and no requirements, and the reached level is capped there. The
    engineering level runs the whole-repository ``cheme validate`` (P&IDs loaded with pyDEXPI:
    the dominant cost, some 30 s on a plant like ASU-1); ``through`` below it skips that.
    *validation*: returns that validate report, to share one already computed.
    """
    ids = [lv[0] for lv in LEVELS]
    if through is not None and through not in ids:
        raise ValueError(f"unknown calculation maturity level {through!r}; one of {', '.join(ids)}")
    top = ids.index(through) if through is not None else len(ids) - 1
    from chemeascode.domains.chemistry.evidence import EVIDENCE_FILE, blocking
    from chemeascode.domains.process.model import load
    from chemeascode.domains.process.model_basis import model_bases
    from chemeascode.domains.process.simulation import SIMULATION_FILE
    from chemeascode.domains.process.simulation.record import RUN_FILE
    from chemeascode.domains.process.simulation.record import read as read_record
    from chemeascode.foundation.provenance import source_revision
    from chemeascode.project.evidence import checked as checked_evidence

    workspace = Workspace(root)
    process, load_findings = load(root)
    sim_state: dict[str, Any] = {}
    if process is not None and (root / SIMULATION_FILE).is_file():
        from chemeascode.domains.process.simulation.translate import load as load_sim
        from chemeascode.domains.process.simulation.translate import translate

        sim, sim_doc, found = load_sim(root)
        sim_state = {"sim": sim, "doc": sim_doc, "findings": found, "translations": {}}
        if sim is not None:
            for case in process.flowsheet.cases:
                sim_state["translations"][case.id] = translate(process, sim, sim_doc, case.id)
    unit_bases: dict[str, dict[str, Any]] = {}
    for translation in sim_state.get("translations", {}).values():
        unit_bases.update(getattr(translation, "bases", {}) or {})
    runs: dict[str, list[dict[str, Any]]] = {}
    for entry in ((read_record(root) or {}).get("cases") or {}).values():
        rows = entry.get("units") if isinstance(entry, dict) else None
        for row in rows or []:
            if isinstance(row, dict) and row.get("id"):
                runs.setdefault(row["id"], []).append(row)
    # a conversion reactor's values its decided model basis covers count as sourced; an
    # observation with an error finding (cheme.evidence-*) supports none
    evidence, evidence_findings = checked_evidence(root) if process is not None else (None, [])
    evidence_errors = blocking(evidence, evidence_findings) if evidence else None
    cells = None
    if process is not None:
        from chemeascode.domains.process.electrochemical_cell import (
            cell_bases,
            cell_report,
            has_cells,
        )

        cells = cell_bases(cell_report(root)) if has_cells(root) else None
    adsorption: dict[str, Any] = {}
    if process is not None:
        from chemeascode.domains.process.separations.adsorption import evaluate
        from chemeascode.domains.process.separations.adsorption import load as load_adsorption

        ads, ads_doc, _ = load_adsorption(root)
        if ads is not None:
            results, _ = evaluate(process, ads, ads_doc, sim_state.get("sim"))
            adsorption = {r.id: r for r in results}
    bases = (
        model_bases(
            process,
            sim_state.get("sim"),
            unit_bases,
            runs,
            evidence,
            evidence_errors,
            cells,
            adsorption,
        )
        if process is not None
        else []
    )

    requirements = _sourced(root, process, load_findings)
    balanced, balance_summary = _balanced(process, bases)
    errors = [f for f in evidence_findings if f.level == "error"]
    if errors and any(u.evidence for u in bases):  # what kept observations from support
        model = next(r for r in balanced if r.id == "balanced.model-basis")
        model.evidence["reaction_evidence_errors"] = [
            {"file": f.file, "line": f.line, "rule": f.rule, "message": f.message, "hint": f.hint}
            for f in errors
        ]
    requirements += balanced
    if (root / "process/furnaces.yaml").is_file():
        requirements.append(_furnace_energy(root))
    by_id = {r.id: r for r in requirements}
    if top >= ids.index("predictive"):
        requirements += _predictive(root, process, bases, by_id, sim_state)
    if top >= ids.index("engineering"):
        requirements += _engineering(workspace, validation)

    levels = []
    reached: str | None = None
    below = True
    for index, (lid, title, label) in enumerate(LEVELS):
        if index > top:
            levels.append(
                {
                    "id": lid,
                    "title": title,
                    "library_maturity": label,
                    "status": "not-evaluated",
                    "reached": False,
                    "requirements": [],
                }
            )
            continue
        own = [r for r in requirements if r.level == lid]
        passes = all(r.status == "pass" for r in own if r.required)
        if passes and below:
            reached = lid
        below = below and passes
        levels.append(
            {
                "id": lid,
                "title": title,
                "library_maturity": label,
                "status": "pass" if passes else "fail",
                "reached": passes and below,
                "requirements": [r.entry() for r in own],
            }
        )

    cases = []
    if process is not None:
        translations = sim_state.get("translations", {})
        for case in process.flowsheet.cases:
            cases.append(
                {
                    "id": case.id,
                    "description": case.description,
                    "default": case.default,
                    "balanced": not any(
                        f"({case.id})" in text
                        for text in balance_summary.get("open", [])
                        + balance_summary.get("failing", [])
                    ),
                    "simulated": case.id in translations
                    and translations[case.id].model is not None,
                }
            )

    design_assumptions: list[str] = []
    data, _ = (
        _read_yaml(root / DESIGN_BASIS_FILE) if (root / DESIGN_BASIS_FILE).is_file() else (None, "")
    )
    if isinstance(data, dict) and isinstance(data.get("assumptions"), list):
        design_assumptions = [str(a) for a in data["assumptions"]]
    assumed = {}
    for name in (
        "process/flowsheet.yaml",
        SIMULATION_FILE,
        "process/reactions.yaml",
        "process/catalysts.yaml",
    ):
        if (root / name).is_file():
            parsed, _ = _read_yaml(root / name)
            assumed[name] = _assumed_count(parsed)
    assumptions = {
        "design_basis": design_assumptions,
        "assumed_values": assumed,
        "models": {u.id: u.assumptions for u in bases if u.assumptions},
    }
    unresolved = [
        {"requirement": r.id, "status": r.status, "file": r.file, "detail": r.detail}
        for r in requirements
        if r.required and r.status in ("fail", "missing")
    ]
    limitations = [
        {"subject": u.id, "file": u.file, "line": u.line, "limitation": text}
        for u in bases
        for text in u.limitations
    ]
    limitations += [
        {"subject": r.id, "file": r.file, "line": r.line, "limitation": r.detail}
        for r in requirements
        if r.status == "unsupported"
    ]
    limitations += [
        {"subject": r.id, "file": r.file, "line": r.line, "limitation": text}
        for r in requirements
        for text in r.evidence.get("limitations") or []
    ]
    if top >= ids.index("engineering"):
        limitations += [
            {"subject": "engineering", "file": "", "line": None, "limitation": text}
            for text in ENGINEERING_LIMITATIONS
        ]
    package = next((r for r in requirements if r.id == "predictive.property-package"), None)
    if package is not None and package.evidence.get("substitution"):
        limitations.append(
            {
                "subject": package.id,
                "file": package.file,
                "line": package.line,
                "limitation": "substituted property package: " + package.evidence["substitution"],
            }
        )
    if sim_state.get("sim") is not None:
        from chemeascode.domains.process.thermodynamics.methods import route_limitations

        limitations += [
            {"subject": "simulation-route", "file": SIMULATION_FILE, "line": None, "limitation": t}
            for t in route_limitations("simulation")
        ]
    artifacts = _artifacts(workspace)
    if process is not None:
        from chemeascode.domains.assessment.flows import boundary_gaps

        gaps = boundary_gaps(process)
        artifacts["boundary"] = {
            **gaps.entry(),
            "findings": [
                {
                    "file": f.file,
                    "line": f.line,
                    "level": f.level,
                    "rule": f.rule,
                    "message": f.message,
                    "hint": f.hint,
                }
                for f in gaps.findings
            ],
        }
        limitations += [
            {"subject": "boundary", "file": f.file, "line": f.line, "limitation": f.message}
            for f in gaps.findings
            if f.level in ("warning", "error")
        ]
    manifest, manifest_findings = _manifest(root, reached)
    if manifest.get("claim_exceeds_evidence") and top < len(ids) - 1 and reached == ids[top]:
        _, supporting = claim_level(root)
        if supporting is not None and ids.index(supporting) > top:
            # a level above *through* might support the claim: not decided here
            manifest["claim_exceeds_evidence"] = None
            manifest_findings = []
    findings = [r.finding() for r in requirements if r.status != "pass"] + manifest_findings
    inputs = [
        "plant.yaml",
        MANIFEST_FILE,
        DESIGN_BASIS_FILE,
        "process/flowsheet.yaml",
        "process/materials.yaml",
        "process/reactions.yaml",
        "process/catalysts.yaml",
        EVIDENCE_FILE,
        "process/adsorption.yaml",
        SIMULATION_FILE,
        RUN_FILE,
        "equipment/equipment-list.yaml",
        "process/furnaces.yaml",
    ]
    now = _dt.datetime.now(_dt.UTC).replace(microsecond=0)
    return MaturityReport(
        level=reached,
        levels=levels,
        requirements=requirements,
        model_basis=[u.entry() for u in bases],
        cases=cases,
        assumptions=assumptions,
        unresolved=unresolved,
        limitations=limitations,
        artifacts=artifacts,
        review=_review(workspace, manifest),
        manifest=manifest,
        source=source_revision(root, inputs).as_dict(),
        findings=findings,
        core_version=_version(),
        checked_at=now.isoformat().replace("+00:00", "Z"),
        evaluated_through=through,
    )


def claim_level(root: Path) -> tuple[str | None, str | None]:
    """The library manifest's maturity claim and the lowest level whose evidence supports it.

    ``(None, None)``: no ``process.yaml`` (cheme-as-code/process/v1) or no known claim;
    ``(claim, None)``: no level supports the claim (detail-engineering and above).
    """
    path = root / MANIFEST_FILE
    data, _ = _read_yaml(path) if path.is_file() else (None, "")
    if not isinstance(data, dict) or data.get("schema") != "cheme-as-code/process/v1":
        return None, None
    claim = data.get("maturity")
    if claim not in LIBRARY_MATURITY:
        return None, None
    wanted = LIBRARY_MATURITY.index(claim)
    level = next((lid for lid, _, label in LEVELS if LIBRARY_MATURITY.index(label) >= wanted), None)
    return claim, level


def maturity_gate(
    root: Path,
    require: str | None,
    max_claim: bool = False,
    validation: Callable[[], Any] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """``kind: maturity`` of checks/checks.yaml: the problems (empty: the gate passes) and the
    evidence (the level, and the failing requirements as findings: file, line, rule, hint).

    *require*: the level that must be reached. *max_claim*: also fail when process.yaml claims
    a design maturity above what the evidence supports. Only the levels the gate needs are
    evaluated (:func:`maturity_report` ``through=``): the engineering level, and with it the
    whole-repository validation, only when *require* or the claim needs it.
    """
    ids = [lv[0] for lv in LEVELS]
    needed = [require] if require else []
    claim, supporting = claim_level(root) if max_claim else (None, None)
    if claim is not None:
        needed.append(supporting or ids[0])  # a claim no level supports exceeds at any level
    through = max(needed, key=ids.index) if needed else ids[0]
    report = maturity_report(root, through=through, validation=validation)
    reached = report.level
    problems: list[str] = []
    failing: list[Requirement] = []
    if require and (reached is None or ids.index(reached) < ids.index(require)):
        failing = [
            r
            for r in report.requirements
            if r.required and r.status != "pass" and ids.index(r.level) <= ids.index(require)
        ]
        shown = "; ".join(
            f"{r.file or '.'}{f':{r.line}' if r.line else ''}: {r.rule} {r.status}"
            + (f" ({r.hint})" if r.hint else "")
            for r in failing[:3]
        )
        more = f" and {len(failing) - 3} more" if len(failing) > 3 else ""
        problems.append(
            f"calculation maturity {reached or 'none'} below {require}: {shown}{more}; "
            "run `cheme maturity`"
        )
    exceeds = [f for f in report.findings if f.rule == "cheme.maturity-claim-exceeds"]
    over = exceeds[0] if max_claim and exceeds else None
    if over is not None:
        where = f"{over.file}:{over.line}" if over.line else over.file
        problems.append(f"{where}: {over.rule} {over.message} ({over.hint})")
    evidence: dict[str, Any] = {
        "level": reached,
        "evaluated_through": through,
        "library_maturity": supported_label(reached),
    }
    if claim is not None:
        evidence["claimed_maturity"] = claim
    if over is not None:
        evidence["claim"] = {
            "file": over.file,
            "line": over.line,
            "rule": over.rule,
            "message": over.message,
            "hint": over.hint,
        }
    if failing:
        evidence["failing"] = [
            {
                "file": r.file or ".",
                "line": r.line,
                "rule": r.rule,
                "status": r.status,
                "hint": r.hint or f"see docs/framework/maturity.md, requirement {r.id}",
            }
            for r in failing
        ]
    return problems, evidence


def maturity_payload(
    root: Path,
    *,
    through: str | None = None,
    validation: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    """The report of the plant repository at *root* as JSON-ready data, for read-only callers
    (``cheme serve``): :func:`maturity_report` without :func:`write_report`. ``checked_at`` is
    the time of this evaluation, in the returned data only; nothing is written. Without
    *through* the engineering level runs the whole-repository validation (see
    :func:`maturity_report`), so a caller evaluates it once per request."""
    return maturity_report(root, through=through, validation=validation).as_dict()


def write_report(root: Path, report: MaturityReport) -> Path:
    """Write *report* to :data:`MATURITY_FILE` (the only file this module writes)."""
    path = root / MATURITY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.to_json() + "\n", encoding="utf-8")
    return path


def report_lines(report: MaturityReport) -> list[str]:
    """The report as text: per level its requirements, then the findings and the summary."""
    marks = {"pass": "ok  ", "fail": "FAIL", "missing": "MISS", "unsupported": "n/s "}
    lines = []
    for level in report.levels:
        state = "reached" if level["reached"] else level["status"]
        lines.append(f"{level['id']}: {level['title']} -- {state}")
        for req in level["requirements"]:
            optional = "" if req["required"] else " (not required)"
            lines.append(f"  {marks[req['status']]} {req['id']}: {req['title']}{optional}")
    if report.model_basis:
        lines.append("model basis:")
        for unit in report.model_basis:
            kind = "predictive" if unit["predictive"] else "specified"
            sourced = "sourced" if unit["sourced"] else "unsourced"
            lines.append(f"  {unit['id']} ({unit['role']}): {unit['basis']}, {kind}, {sourced}")
    units = {u["id"] for u in report.model_basis}
    for item in report.limitations:
        if item["subject"] in units:
            lines.append(f"limitation {item['subject']}: {item['limitation']}")
    for finding in report.findings:
        lines.append(finding.format())
    claim = report.manifest.get("claimed_maturity")
    lines.append(
        f"calculation maturity: {report.level or 'none'}"
        + (f" (design maturity claimed: {claim})" if claim else "")
    )
    label = supported_label(report.level)
    lines.append(
        f"design maturity the evidence supports: {label or 'none'}"
        + (
            f"; the claim {claim} exceeds it"
            if claim and report.manifest.get("claim_exceeds_evidence")
            else ""
        )
    )
    review = report.review.get("manifest_status")
    lines.append(f"review status (people only): {review or 'not recorded'}")
    return lines
