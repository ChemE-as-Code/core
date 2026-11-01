"""``cheme assess lca-scenarios``: one machine-readable record per LCA scenario.

A record (``lca/scenarios/<id>.json``, schema :data:`RECORD_SCHEMA`) states, for one scenario of
``lca/lca.yaml`` (and the baseline), what a process library, the Process Atlas or a Brightway job
needs to use it without re-deriving anything (docs/framework/lci-scenarios.md):

- a stable id ``<dataset>/<case>/<scenario>`` and the parent design case (flowsheet ``cases:``:
  its declared capacity, provenance and applicability);
- three layers kept apart: the unallocated **foreground** (every exchange, per the dataset's
  basis, with a fingerprint), the **linked inventory** (each exchange's background in this
  scenario against the baseline's, with geography, year, status and source, and its state:
  linked, proxy, missing, unmapped, free) and the **characterised impacts** (per functional
  unit, with the allocation method and shares that made them);
- the gaps (never zeros), the warnings, the scenario's classification and publication policy,
  and the fingerprints of what it rests on (no time, no commit), so ``--check`` finds a stale
  record.

A regional scenario changes the background only: its foreground is the baseline's (relation
``unchanged``). Only a scenario naming its own flowsheet ``case:`` changes the foreground
(relation ``design-case``). :func:`compare_cases` sets existing cases side by side; nothing here
scales a design to a capacity it was not computed for.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import asdict
from typing import Any

from chemeascode.domains.assessment.lca.allocation import MISSING
from chemeascode.domains.assessment.lca.comparability import effective_scope
from chemeascode.domains.assessment.lca.comparability import verdict as scenario_verdict
from chemeascode.domains.assessment.lca.impacts import GAP_REASONS, real_gaps
from chemeascode.domains.assessment.lca.inventory import Inventory, inventory
from chemeascode.domains.assessment.lca.report import (
    BASELINE,
    PUBLICATION_ORDER,
    SCREENING_STATUSES,
    UNREGISTERED,
    LcaReport,
    _climate,
    _ids,
    _source_policy,
    manifest,
    maturity,
)
from chemeascode.domains.assessment.lca.schemas import LcaFile
from chemeascode.foundation.findings import Finding

RECORD_SCHEMA = "cheme/lca-scenario/v1"
#: One record per scenario: ``lca/scenarios/<scenario id>.json`` (never overwriting another).
SCENARIO_DIR = "lca/scenarios"
#: Findings about one scenario: they belong to that scenario's record only.
_SCENARIO_RULES = (
    "cheme.lca-scenario-geography",
    "cheme.lca-scenario-year",
    "cheme.lca-scenario-unchecked",
    "cheme.lca-scenario-key",
    "cheme.lca-scenario-empty",
)
#: Baseline findings about the study's own geography and year: a regional scenario has its own.
_BASELINE_RULES = ("cheme.lca-geography", "cheme.lca-reference-year", "cheme.lca-unchecked")


def _sha(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _round(value: float | None) -> float | None:
    return None if value is None else float(f"{value:.6g}")


def record_path(scenario: str) -> str:
    return f"{SCENARIO_DIR}/{scenario}.json"


def _spec(scope: LcaFile, scenario: str):
    return next((s for s in scope.scenarios if s.id == scenario), None)


def _case(report: LcaReport, case_id: str) -> dict[str, Any]:
    """The design case: the flowsheet case's declared capacity, provenance and applicability."""
    from chemeascode.domains.process.model import load

    process, _ = load(report.root)
    case = None
    if process is not None:
        case = next((c for c in process.flowsheet.cases if c.id == case_id), None)
    found: dict[str, Any] = {"id": case_id}
    if case is None:
        return found
    found.update(
        {
            "description": case.description,
            "capacity": case.capacity or None,
            "provenance": case.provenance,
            "applicability": case.applicability.model_dump(mode="json")
            if case.applicability
            else None,
            "source": case.source or None,
            # outside what a model or data were checked for: never read as predictive
            "extrapolated": case.provenance == "extrapolated",
        }
    )
    return found


def _state(inv: Inventory, row, impacts: list, gaps: list) -> str:
    if row.key not in inv.backgrounds:
        if row.mapping.startswith(MISSING):
            return "missing"
        if row.mapping == "emission":
            return "released"  # counted by its emission:* exchanges
        return "free" if row.mapping == "free" else "unmapped"
    if not impacts:
        return "gap"
    if any("PROXY" in _ids(i.status) for i in impacts):
        return "proxy"
    if gaps:
        return "partial"
    return "linked"


def _links(
    report: LcaReport, inv: Inventory, scenario: str, replace: dict[str, str]
) -> list[dict[str, Any]]:
    """Each exchange's background in *scenario*, against the baseline's mapping."""
    base = report.inventory
    amounts = {e.key: e for e in inv.dataset.exchanges}
    found = []
    for row in inv.rows:
        exchange = amounts.get(row.key)
        if exchange is None or exchange.type == "product":
            continue  # a co-product, or an allocation credit (substitution:): not an exchange
        impacts = [i for i in report.impacts if i.scenario == scenario and i.key == row.key]
        gaps = [g for g in report.gaps if g.scenario == scenario and g.key == row.key]
        background = inv.backgrounds.get(row.key)
        baseline_background = base.backgrounds.get(row.key) if base else None
        first = impacts[0] if impacts else None
        entry: dict[str, Any] = {
            "key": row.key,
            "title": row.title,
            "phase": row.phase,
            "amount": _round(exchange.amount),
            "unit": exchange.unit,
            "state": _state(inv, row, impacts, gaps),
            "background": first.basis if first else None,
            "baseline": None,
            "replaced": False,
            "location": first.location or None if first else None,
            "year": first.year if first else None,
            "status": first.status or None if first else None,
            "source_id": first.source_id or None if first else None,
            "note": None,
        }
        own = (
            next((f for f in report.factors.factors if f.id == first.basis), None)
            if first and report.factors is not None
            else None
        )
        # the data year only where declared: it decides the year compared,
        # so it belongs in the record; the publication year is metadata of the factor file, and
        # records without a data year keep their bytes
        if own is not None and own.data_year is not None:
            entry["data_year"] = own.data_year
        declared = effective_scope(report.factors, first.basis)[0] if first else None
        # the background's declared scope (null: not declared), never inferred from text
        entry["scope"] = (
            declared.model_dump(mode="json", exclude_none=True, exclude={"note"})
            if declared is not None and declared.declared
            else None
        )
        entry["baseline"] = _mapping(base, row.key) or None
        if baseline_background is not None:
            factor = baseline_background.factor
            entry["replaced"] = bool(factor and factor in replace) or bool(
                baseline_background.activity is not None
                and baseline_background.activity.database in replace
            )
        if background is not None:
            entry["note"] = background.proxy or None
        elif row.mapping.startswith(MISSING):
            entry["note"] = row.mapping.removeprefix(MISSING)
        if gaps:
            entry["gaps"] = sorted({g.category for g in gaps})
        found.append(entry)
    return found


def _mapping(inv: Inventory, key: str) -> str:
    return next((r.mapping for r in inv.rows if r.key == key), "")


def _publication(report: LcaReport, scenario: str) -> dict[str, Any]:
    scope = report.scope
    registry = {s.id: s for s in report.sources}
    policies: dict[str, str] = {}
    contributions = [i for i in report.impacts if i.scenario == scenario]
    if scenario == BASELINE:
        contributions += report.credits
    for impact in contributions:
        for source_id in _ids(impact.source_id) or [UNREGISTERED]:
            policies[source_id] = _source_policy(source_id, scope, report.factors, registry)
    policy = max(policies.values(), key=PUBLICATION_ORDER.index, default="public")
    decision = scope.publication
    return {
        "policy": policy,
        "publishable": policy == "public"
        or (policy == "restricted" and decision is not None and decision.allow_restricted),
        "restricted_by": sorted(k for k, v in policies.items() if v != "public"),
    }


def _findings(
    report: LcaReport, scenario: str, regional: bool, own_case: bool, own_year: bool = False
) -> list[Finding]:
    """The findings of *scenario*'s record: its own (its characterisation, its own case's
    inventory), the scenario rules naming it, and the study's general ones; never another
    scenario's, nor, for a design-case scenario, the baseline case's inventory's."""
    key = lambda f: (f.rule, f.message)  # noqa: E731
    mine = {key(f) for f in report.scenario_findings.get(scenario, [])}
    others = {
        key(f)
        for other, raised in report.scenario_findings.items()
        if other != scenario
        for f in raised
    }
    if own_case:
        others |= {key(f) for f in report.inventory.findings}
    found = []
    for finding in report.findings:
        if key(finding) in others and key(finding) not in mine:
            continue
        if finding.level == "info" and finding.rule not in _SCENARIO_RULES:
            continue
        if finding.rule in _SCENARIO_RULES:
            if scenario in finding.ids:
                found.append(finding)
            continue
        if regional and finding.rule in _BASELINE_RULES:
            continue  # the study's own location: the scenario is checked against its own
        if own_year and finding.rule == "cheme.lca-reference-year":
            continue  # the scenario's own year is checked instead
        found.append(finding)
    return found


def _classification(
    report: LcaReport, scenario: str, findings: list[Finding]
) -> tuple[str, list[str]]:
    """The scenario's class by the criteria of :func:`.report.classify`, on its own
    contributions, gaps and geography."""
    if not report.loaded or not report.categories:
        return "unavailable", ["the LCA does not compute"]
    reasons = []
    gaps = real_gaps([g for g in report.gaps if g.scenario == scenario])
    if gaps:
        reasons.append(f"{len({g.key for g in gaps})} exchanges without a burden in some category")
    statuses = sorted(
        {s for i in report.impacts if i.scenario == scenario for s in _ids(i.status)}
        & set(SCREENING_STATUSES)
    )
    if report.example:
        reasons.append("example factors")
    if statuses:
        reasons.append(f"factors {', '.join(statuses)}")
    if all(_climate(c) for c in report.categories):
        reasons.append("climate categories only: a carbon footprint, not a multi-impact LCA")
    flagged = {
        "cheme.lca-geography": "geography mismatch",
        "cheme.lca-reference-year": "reference year mismatch",
        "cheme.lca-method-mix": "method mix mismatch",
        "cheme.lca-scenario-geography": "geography mismatch",
        "cheme.lca-scenario-year": "reference year mismatch",
    }
    for rule in sorted({f.rule for f in findings if f.rule in flagged}):
        if flagged[rule] not in reasons:
            reasons.append(flagged[rule])
    if any(f.rule in ("cheme.lca-unchecked", "cheme.lca-scenario-unchecked") for f in findings):
        reasons.append("geography or reference year not checked")
    if gaps:
        return "partial", reasons
    return ("screening" if reasons else "complete"), reasons


def record(report: LcaReport, scenario: str) -> dict[str, Any]:
    """The record of *scenario* (``baseline`` or an id of ``lca/lca.yaml``) of a computed
    *report*. Deterministic: the same inputs give the same record."""
    scope: LcaFile = report.scope
    if scenario not in report.scenarios:
        raise KeyError(scenario)
    spec = _spec(scope, scenario)
    inv = report.scenario_inventories.get(scenario, report.inventory)
    dataset = inv.dataset
    base_case = report.inventory.case
    if spec is None:
        kind, relation, replace = "baseline", "baseline", {}
    else:
        replace = spec.factors if scope.backend == "factors" else spec.databases
        relation = "design-case" if inv.case != base_case else "unchanged"
        kind = "design-case" if relation == "design-case" else "background"
    regional = spec is not None and spec.regional
    findings = _findings(
        report,
        scenario,
        regional,
        inv is not report.inventory and inv.case != base_case,
        spec is not None and spec.year is not None,
    )
    notes = []
    if relation == "unchanged":
        notes.append(
            "background sensitivity: the foreground is the baseline's; physical flows and "
            "duties are unchanged"
        )
    if relation == "design-case":
        notes.append(
            f"design case {inv.case}: the foreground was derived from that flowsheet case, "
            "not scaled from the baseline"
        )
    design_case = _case(report, inv.case)
    if design_case.get("extrapolated"):
        notes.append(f"case {inv.case} is extrapolated: not a predictive or validated design")
    exchanges = [
        {
            "key": e.key,
            "title": e.title,
            "type": e.type,
            "phase": e.phase,
            "amount": _round(e.amount),
            "unit": e.unit,
            "provenance": e.provenance,
        }
        for e in dataset.exchanges
    ]
    classification, reasons = _classification(report, scenario, findings)
    # per category: what the baseline characterises that is a gap here (the totals do not
    # compare), and whether the category has a total at all: a category whose contributions
    # are all gaps, or that lacks one the baseline has, gets null, never 0
    totals: dict[str, float | None] = {}
    standing = report.comparability(scenario)
    dropped_by = {c: keys for c, keys in standing.items() if keys}
    gaps_here = real_gaps([g for g in report.gaps if g.scenario == scenario])
    for category in report.categories:
        totals[category.id] = (
            None if category.id in standing else _round(report.totals(scenario)[category.id])
        )
    dropped = sorted({k for keys in dropped_by.values() for k in keys})
    # categories whose total (core's convention) excludes gaps: partial, never complete
    partial = sorted(
        {g.category for g in gaps_here} & {c for c, v in totals.items() if v is not None}
    )
    fu = scope.functional_unit
    reference = dataset.product(fu.product)
    reference_unit = reference.unit if reference is not None else "kg"
    run = manifest(report)
    data = {
        "schema": RECORD_SCHEMA,
        "id": f"{dataset.id}/{inv.case}/{scenario}",
        "scenario": {
            "id": scenario,
            "kind": kind,
            "title": (spec.title if spec else "") or None,
            "location": (spec.location if spec and spec.location else scope.location) or None,
            "year": (spec.year if spec and spec.year is not None else scope.year),
            "electricity": spec.electricity if spec else None,
            "source": (spec.source if spec else "") or None,
            "replaces": dict(sorted(replace.items())),
            "missing": dict(sorted(spec.missing.items())) if spec else {},
            "proxy": dict(sorted(spec.proxy.items())) if spec else {},
        },
        "process": {
            "dataset": dataset.id,
            "title": dataset.title,
            "technology": dataset.technology or None,
        },
        "design_case": design_case,
        # like-for-like / proxy / not comparable with the baseline, from the factors' scope
        "comparability": scenario_verdict(report, scenario),
        "foreground": {
            "layer": "foreground",
            "relation": relation,
            "scope": dataset.scope,
            "basis": dataset.basis,
            "boundary": dataset.boundary,
            "fingerprint": _sha(exchanges),
            "exchanges": exchanges,
        },
        "linked_inventory": {
            "layer": "linked-inventory",
            "backend": report.backend,
            "basis": dataset.basis,
            "exchanges": _links(report, inv, scenario, replace),
        },
        "impacts": {
            "layer": "characterized-impact",
            "functional_unit": {
                "product": fu.product,
                "amount": fu.amount,
                "unit": fu.unit,
                # in the reference product's unit (kg; kWh for an energy product)
                "kg": inv.amount if reference_unit == "kg" else None,
                "reference_amount": {"value": inv.amount, "unit": reference_unit},
            },
            "allocation": {
                "method": inv.method,
                "shares": {k: _round(v) for k, v in sorted(inv.shares.items())},
            },
            "categories": [
                {"id": c.id, "unit": c.unit, "method": c.method or None} for c in report.categories
            ],
            # null: not computable without the gaps (see dropped_by_category, gaps)
            "totals": totals,
            # the sum of what was characterised, gaps excluded: not a footprint when partial
            "characterised_sum": {k: _round(v) for k, v in report.totals(scenario).items()},
            "partial_categories": partial,
            "comparable": not dropped,
            "dropped": dropped,
            "dropped_by_category": dropped_by,
            "classification": classification,
            "reasons": reasons,
        },
        "gaps": [
            {
                **{k: v for k, v in asdict(g).items() if k != "scenario"},
                "quantity": _round(g.quantity),
                "why": GAP_REASONS.get(g.reason, g.reason),
            }
            for g in report.gaps
            if g.scenario == scenario
        ],
        "notes": notes,
        "warnings": [
            {"rule": f.rule, "level": f.level, "message": f.message, "file": f.file}
            for f in findings
        ],
        "publication": _publication(report, scenario),
        "inputs": {
            "files": run["inputs"],
            "mapping": run["mapping"],
            "scenario": _sha(spec.model_dump(mode="json")) if spec else None,
            "background": run["background"],
            "software": run["software"],
        },
    }
    return data


def records(report: LcaReport, ids: list[str] | None = None) -> dict[str, str]:
    """``lca/scenarios/<id>.json`` of each scenario of *ids* (all, the baseline first, when
    None), by path."""
    chosen = ids or list(report.scenarios)
    unknown = [i for i in chosen if i not in report.scenarios]
    if unknown:
        raise KeyError(", ".join(unknown))
    return {
        record_path(s): json.dumps(record(report, s), indent=2, ensure_ascii=False) + "\n"
        for s in chosen
    }


# -- design cases --------------------------------------------------------------------------


def compare_cases(root, cases: list[str] | None = None) -> tuple[list[dict[str, Any]], list]:
    """The flowsheet cases of the plant at *root* side by side (all when *cases* is None): each
    case's declared capacity and provenance, and each exchange per unit of the functional
    unit's product (``per_unit``: per kg, or per kWh for an energy product, each value with its
    unit; formerly ``per_kg``). Only cases the flowsheet holds; an exchange a
    case lacks is None, never 0 or a value scaled from another case."""
    from pathlib import Path

    import yaml

    from chemeascode.domains.assessment.lca.inventory import LCA_FILE
    from chemeascode.domains.process.model import load

    root = Path(root)
    findings: list[Finding] = []
    process, found = load(root)
    findings += [f for f in found if f.level == "error"]
    try:
        scope = LcaFile.model_validate(
            yaml.safe_load((root / LCA_FILE).read_text(encoding="utf-8")) or {}
        )
    except Exception as failure:  # noqa: BLE001 - reported as a finding
        findings.append(
            Finding(
                LCA_FILE,
                "error",
                "cheme.lca-no-scope",
                f"{LCA_FILE} does not load: {str(failure).splitlines()[0]}",
                hint="cheme validate names the line",
            )
        )
        return [], findings
    if process is None:
        return [], findings
    known = [c.id for c in process.flowsheet.cases]
    chosen = cases or known
    for case in chosen:
        if case not in known:
            findings.append(
                Finding(
                    "process/flowsheet.yaml",
                    "error",
                    "cheme.lca-case",
                    f"case {case!r} is not a case of process/flowsheet.yaml: it is not computed "
                    "and is not derived from another case",
                    ids=[case],
                    hint=f"compute it as a flowsheet case first; cases: {', '.join(known)}",
                )
            )
    from chemeascode.domains.assessment.lca.report import _construction_inputs

    takeoff, equipment, found = _construction_inputs(root, scope)
    findings += found
    lca_text = (root / LCA_FILE).read_text(encoding="utf-8")
    rows = []
    product = f"product:{scope.functional_unit.product}"
    for case in [c for c in chosen if c in known]:
        inv = inventory(
            process,
            scope.model_copy(update={"case": case}),
            lca_text,
            takeoff,
            equipment,
            maturity(root),
        )
        findings += [
            dataclasses.replace(f, message=f"case {case}: {f.message}", ids=[*f.ids, case])
            for f in inv.findings
        ]
        info = next(c for c in process.flowsheet.cases if c.id == case)
        entry: dict[str, Any] = {
            "case": case,
            "description": info.description,
            "capacity": info.capacity or None,
            "provenance": info.provenance,
            "extrapolated": info.provenance == "extrapolated",
            "applicability": info.applicability.model_dump(mode="json")
            if info.applicability
            else None,
            "product": None,
            "per_unit": {},
            # construction left without an amount (no weight, unmatched, no take-off): missing
            "unknown": sorted(key for key, _, _ in inv.unknown),
        }
        if inv.dataset is not None:
            made = inv.dataset.product(product)
            amount = made.amount if made is not None else None
            unit = made.unit if made is not None else "kg"
            entry["product"] = {"key": product, "amount": _round(amount), "unit": f"{unit}/h"}
            if amount:
                # per unit of the product: per kg, or per kWh for an energy product
                entry["per_unit"] = {
                    e.key: {"amount": _round(e.amount / amount), "unit": f"{e.unit}/{unit}"}
                    for e in inv.dataset.exchanges
                    if e.key != product
                }
        rows.append(entry)
    keys = sorted({k for r in rows for k in r["per_unit"]})
    for row in rows:
        row["per_unit"] = {k: row["per_unit"].get(k) for k in keys}
    return rows, findings
