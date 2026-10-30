"""Stage gates on the 3D layout: ``kind: layout-model`` in ``checks/checks.yaml``.

A gate lists what it ``require``\\s; each requirement is one test on the layout files, the
committed model ``layout/plant-model.yaml`` and the findings of ``cheme validate``:

- ``site``, ``areas``, ``roads``, ``racks``: the site plan declares a site and at least one
  area, road and rack;
- ``placed``: every equipment-list item has a placement, or its ``layout-not-placed`` finding
  is accepted with a reason (an internal of another item);
- ``separations``: the site plan declares at least one separation;
- ``model-current``: the model exists and validate reports it neither edited, outdated nor
  built by another generator version;
- ``nozzles``: no nozzle override names a nozzle the P&ID lacks, and no piped nozzle was placed
  by default;
- ``mounted``: every item standing above grade is mounted on a building or structure level, or
  stands on another item;
- ``routed``: every line of the line list at or above ``min_dn`` (and not excluded by number
  pattern or fluid) is routed or skipped with a reason;
- ``clashes``: no model finding of ``rules`` (default: clashes and headroom) at warning or
  above is left unaccepted;
- ``zones``: ``layout/zones.yaml`` declares at least one zone, and no
  ``layout-zone-source`` finding (a source the model cannot place) is left unaccepted;
- ``drawings``: a review record of ``topic`` (default ``layout``) cites the plot plan and at
  least ``sections`` sections (``layout-plan*``, ``layout-section-*`` file names);
- ``cables``: the repository has an electrical list, the model has its cables, and no
  ``layout-cable-missing`` or ``layout-cable-unrouted`` finding is left unaccepted (a cable to
  every motor and instrument, each routed in trays);
- ``trays``: no ``layout-tray-fill``, ``layout-tray-separation`` or ``layout-tray-voltage``
  finding is left unaccepted;
- ``lifting``: every heavy item (``heavy_lift_t``) has its crane (a building's overhead
  crane, or a crane pad within reach with a clear lane) and a laydown, and, when the plant
  gives crane load charts (``layout/crane-chart.yaml``), a chart that carries the lift: no
  ``layout-lifting``, ``layout-laydown`` or ``layout-lifting-capacity`` finding left
  unaccepted;
- ``lifting-current``: ``layout/lifting-study.csv`` (and ``.md`` when written) is what
  ``cheme layout lifting`` gives for the committed model now (validate reports a written study
  that is not as ``cheme.layout-lifting-study-outdated``);
- ``hvac``: a layout with a clad building (walls) has ``layout/hvac.yaml`` and its model has
  the ducts, and no ``layout-hvac-capacity`` or ``layout-duct-unrouted`` finding is left
  unaccepted (a layout without clad buildings passes: there is nothing to ventilate).

The checks are structural: that a route, a platform or a zone is *right* is the review's
judgement, recorded in that review record.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Iterable
from typing import Any

import yaml

from chemeascode.foundation.acceptance import acceptance
from chemeascode.foundation.findings import _SEVERITY, Finding
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE, Workspace

REQUIREMENTS = (
    "site",
    "areas",
    "roads",
    "racks",
    "placed",
    "separations",
    "model-current",
    "nozzles",
    "mounted",
    "routed",
    "clashes",
    "zones",
    "drawings",
    "cables",
    "trays",
    "hvac",
    "lifting",
    "lifting-current",
)
#: Model findings the ``cables`` and ``trays`` requirements fail on.
CABLE_RULES = ("cheme.layout-cable-missing", "cheme.layout-cable-unrouted")
TRAY_RULES = (
    "cheme.layout-tray-fill",
    "cheme.layout-tray-separation",
    "cheme.layout-tray-voltage",
)
#: Findings the ``zones`` requirement fails on: a zone source the model cannot place.
ZONE_RULES = ("cheme.layout-zone-source",)
#: Findings the ``lifting`` requirement fails on.
LIFT_RULES = (
    "cheme.layout-lifting",
    "cheme.layout-laydown",
    "cheme.layout-lifting-capacity",
)
#: Model findings the ``hvac`` requirement fails on.
HVAC_RULES = ("cheme.layout-hvac-capacity", "cheme.layout-duct-unrouted")
#: Model findings a ``clashes`` requirement fails on when the gate names no ``rules``.
CLASH_RULES = ("cheme.layout-clash-*", "cheme.layout-headroom")
MODEL_STATE_RULES = (
    "cheme.layout-model-edited",
    "cheme.layout-model-outdated",
    "cheme.layout-model-version",
    "cheme.layout-model-missing",
)
#: How far above grade an item counts as elevated, and how close it must sit on another
#: item's top to stand on it, m.
ELEVATED_M = 0.05
#: Problems listed by name before "and N more".
SHOWN = 3


def _load(workspace: Workspace, kind: str) -> Any:
    from chemeascode.domains.spatial.schemas import LAYOUT_SCHEMAS

    path = workspace.layout_file(kind)
    if path is None:
        return None
    try:
        return LAYOUT_SCHEMAS[kind].model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        )
    except Exception:  # noqa: BLE001 - validate reports the schema error itself
        return None


def _named(items: list[str], what: str) -> str:
    shown = ", ".join(items[:SHOWN])
    more = f" and {len(items) - SHOWN} more" if len(items) > SHOWN else ""
    return f"{len(items)} {what}: {shown}{more}"


def _matches(value: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if any(c in pattern for c in "*?["):
            if fnmatch.fnmatchcase(value, pattern):
                return True
        elif value == pattern or value.startswith(pattern):
            return True
    return False


def _model(workspace: Workspace) -> dict[str, Any] | None:
    from chemeascode.domains.spatial.model import read

    path = workspace.layout_model_file()
    return read(path.read_text(encoding="utf-8")) if path is not None else None


def _unaccepted(findings: list[Finding], rules: Iterable[str], accept: list[Any]) -> list[Finding]:
    rules = list(rules)
    return [
        f
        for f in findings
        if f.accepted is None
        and _SEVERITY[f.level] >= _SEVERITY["warning"]
        and any(r == f.rule or fnmatch.fnmatchcase(f.rule, r) for r in rules)
        and acceptance(accept, f) is None
    ]


def _stands_on(item: dict[str, Any], others: list[dict[str, Any]]) -> bool:
    x0, y0, z0, x1, y1, _ = item["bbox"]
    for other in others:
        if other is item:
            continue
        a0, b0, _, a1, b1, top = other["bbox"]
        if abs(top - z0) <= ELEVATED_M + 0.05 and a0 < x1 and x0 < a1 and b0 < y1 and y0 < b1:
            return True
    return False


def unrouted_lines(
    model: dict[str, Any],
    lines: Any,
    min_dn: float = 0.0,
    exclude_lines: Iterable[str] = (),
    exclude_fluids: Iterable[str] = (),
) -> list[str]:
    """The line numbers the ``routed`` requirement fails on, each with why."""
    from chemeascode.domains.piping.pipe_data import parse_dn
    from chemeascode.domains.spatial.report import layout_report

    fluids = {f.strip().lower() for f in exclude_fluids}
    listed = {line.number.strip(): line for line in getattr(lines, "lines", None) or ()}
    # the lines the P&IDs route but the line list lacks count too (DN from their pipes)
    drawn: dict[str, float | None] = {}
    for pipe in model.get("pipes", []):
        drawn[pipe["line"]] = max(drawn.get(pipe["line"]) or 0.0, pipe.get("dn") or 0.0) or None
    for item in model.get("unrouted", []):
        drawn.setdefault(item["line"], None)
    wanted: dict[str, Any] = {}
    for number in sorted(set(listed) | set(drawn)):
        line = listed.get(number)
        dn = parse_dn(line.nominal_diameter) if line is not None else drawn.get(number)
        fluid = (line.fluid or "") if line is not None else ""
        if dn is not None and dn < min_dn:
            continue
        if _matches(number, exclude_lines) or fluid.strip().lower() in fluids:
            continue
        wanted[number] = line
    report = layout_report(model, [], list(wanted))
    failing = []
    for entry in report["lines"]:
        if entry["line"] not in wanted or entry["status"] in ("routed", "skipped", "not on a P&ID"):
            continue
        open_ = [u for u in entry["unrouted"] if not u["reason"].startswith("skipped")]
        if open_:
            failing.append(f"{entry['line']} ({open_[0]['reason']})")
    return failing


def layout_gate(
    workspace: Workspace,
    require: list[str],
    findings: list[Finding],
    *,
    min_dn: float = 25.0,
    exclude_lines: Iterable[str] = (),
    exclude_fluids: Iterable[str] = (),
    rules: Iterable[str] = (),
    accept: list[Any] | None = None,
    sections: int = 2,
    topic: str = "layout",
    records: list[Any] | None = None,
) -> list[str]:
    """What fails the gate (see the module text): one text per failing requirement, each
    saying what to do; empty when it passes."""
    problems: list[str] = []
    accept = accept or []
    needs = set(require)
    plan = _load(workspace, "site_plan")
    if needs & {"site", "areas", "roads", "racks", "separations"} and plan is None:
        problems.append("no valid layout/site-plan.yaml: declare the site, areas, roads and racks")
    elif plan is not None:
        for name in ("areas", "roads", "racks", "separations"):
            if name in needs and not getattr(plan, name):
                problems.append(f"layout/site-plan.yaml declares no {name}")
    if "placed" in needs:
        equipment = workspace.parsed_lists(("equipment",)).get("equipment")
        placements = _load(workspace, "placement")
        placed = {p.tag for p in placements.equipment} if placements is not None else set()
        # an item without a placement of its own on purpose (an internal of another item, such
        # as a reboiler in a column sump) has its layout-not-placed finding accepted
        internal = {
            tag
            for f in findings
            if f.rule == "cheme.layout-not-placed"
            and (f.accepted is not None or acceptance(accept, f) is not None)
            for tag in f.ids
        }
        missing = [
            item.tag
            for item in getattr(equipment, "equipment", None) or ()
            if item.tag not in placed and item.tag not in internal
        ]
        if placements is None:
            problems.append("no valid layout/equipment-placement.yaml: place every item")
        elif missing:
            problems.append(
                _named(missing, "equipment-list items not placed")
                + " (layout/equipment-placement.yaml)"
            )
    model_needs = needs & {"model-current", "nozzles", "mounted", "routed", "cables", "hvac"}
    model = _model(workspace) if model_needs else None
    if model_needs and model is None:
        problems.append(f"no {LAYOUT_MODEL_FILE}: run cheme layout build and commit it")
    if "model-current" in needs and model is not None:
        stale = [f for f in findings if f.rule in MODEL_STATE_RULES and f.accepted is None]
        if stale:
            problems.append(
                f"{stale[0].rule.removeprefix('cheme.')}: {stale[0].message}; run cheme "
                "layout build and commit the model"
            )
    if "nozzles" in needs:
        unknown = [f for f in findings if f.rule == "cheme.layout-nozzle-unknown"]
        if unknown:
            problems.append(_named([f.message for f in unknown], "unknown nozzle overrides"))
        if model is not None:
            defaulted = [
                n["id"]
                for item in model.get("equipment", [])
                for n in item.get("nozzles", [])
                if n.get("basis") == "default" and (n.get("refs") or {}).get("segments")
            ]
            if defaulted:
                problems.append(
                    _named(defaulted, "piped nozzles placed by default")
                    + ": give their position in the placement's nozzles:"
                )
    if "mounted" in needs and model is not None:
        items = model.get("equipment", [])
        loose = [
            item["tag"]
            for item in items
            if item["bbox"][2] > ELEVATED_M
            and not item.get("mount")
            and abs(item["bbox"][2] - (item.get("plinth") or 0.0)) > ELEVATED_M
            and not _stands_on(item, items)
        ]
        if loose:
            problems.append(
                _named(loose, "elevated items on nothing")
                + ": mount them on a building or structure level (mount:)"
            )
    if "routed" in needs and model is not None:
        lines = workspace.parsed_lists(("lines",)).get("lines")
        failing = unrouted_lines(model, lines, min_dn, exclude_lines, exclude_fluids)
        if failing:
            problems.append(
                _named(failing, "lines neither routed nor skipped")
                + "; see cheme layout report, then route them or skip them with a reason "
                "in piping/routing.yaml"
            )
    if "clashes" in needs:
        open_ = _unaccepted(findings, list(rules) or CLASH_RULES, accept)
        if open_:
            counts: dict[str, int] = {}
            for f in open_:
                counts[f.rule] = counts.get(f.rule, 0) + 1
            what = ", ".join(f"{n} {rule}" for rule, n in sorted(counts.items()))
            problems.append(
                f"{what} not accepted; first: {open_[0].id}; fix them (via points, pins, moves) "
                "or accept them with a reason"
            )
    if "cables" in needs and model is not None:
        if workspace.list_file("electrical") is None:
            problems.append(
                "no electrical/electrical-list.yaml: declare the rooms (and motors, junction "
                "boxes), then cheme layout build"
            )
        elif model.get("cables") is None:
            problems.append(
                f"{LAYOUT_MODEL_FILE} has no cables: fix electrical/electrical-list.yaml "
                "(cheme validate), then cheme layout build"
            )
        else:
            open_ = _unaccepted(findings, CABLE_RULES, accept)
            if open_:
                problems.append(
                    _named(
                        [f.ids[0] if f.ids else f.message for f in open_],
                        "loads without a routed cable",
                    )
                    + "; see cheme layout cables, complete the electrical list or accept "
                    "with a reason"
                )
    if "hvac" in needs and model is not None:
        buildings = _load(workspace, "building")
        clad = [b.id for b in getattr(buildings, "buildings", None) or () if b.walls != "none"]
        if workspace.layout_file("hvac") is None:
            if clad:
                problems.append(
                    _named(clad, "clad buildings without ventilation")
                    + ": declare their units and rooms in layout/hvac.yaml (skill hvac-ducts), "
                    "then cheme layout build"
                )
        elif model.get("ducts") is None:
            problems.append(
                f"{LAYOUT_MODEL_FILE} has no ducts: fix layout/hvac.yaml (cheme validate), "
                "then cheme layout build"
            )
        else:
            open_ = _unaccepted(findings, HVAC_RULES, accept)
            if open_:
                problems.append(
                    _named([f.key or f.message for f in open_], "HVAC capacity or routing findings")
                    + " not accepted; resize, add a unit or louvre, give the ducts room, or "
                    "accept with a reason"
                )
    if "trays" in needs:
        open_ = _unaccepted(findings, TRAY_RULES, accept)
        if open_:
            problems.append(
                _named(
                    [f.key or f.message for f in open_],
                    "tray fill, separation or voltage findings",
                )
                + " not accepted; declare more power trays on the rack, or trays of the "
                "cables' voltage class (power_trays in electrical/tray-rules.yaml), split the "
                "loads or accept with a reason"
            )
    if "zones" in needs:
        zones = _load(workspace, "zones")
        if zones is None or not zones.zones:
            problems.append("layout/zones.yaml declares no zone")
        unplaced = _unaccepted(findings, ZONE_RULES, accept)
        if unplaced:
            problems.append(
                _named([f.message for f in unplaced], "zone sources not placed")
                + "; name a placed tag, a nozzle (TAG/N1) or a routed line with an open end, or "
                "accept with a reason"
            )
    if "lifting" in needs:
        open_ = _unaccepted(findings, LIFT_RULES, accept)
        if open_:
            problems.append(
                _named([f.key or f.message for f in open_], "lifting findings")
                + " not accepted; see cheme layout lifting: a crane pad within reach, a "
                "clear lane, a laydown and a crane chart that carries the lift, or accept with "
                "the lifting plan's reason"
            )
    if "lifting-current" in needs:
        problems += _lifting_current(workspace)
    if "drawings" in needs:
        problems += _drawings(workspace, topic, sections, records)
    return problems


def _lifting_current(workspace: Workspace) -> list[str]:
    from chemeascode.domains.spatial.lifting import STUDY_CSV, study_findings

    if not (workspace.root / STUDY_CSV).is_file():
        return [f"no {STUDY_CSV}: run cheme layout lifting --write and commit it"]
    if workspace.layout_model_file() is None:
        return [f"no {LAYOUT_MODEL_FILE}; run cheme layout build"]
    try:
        outdated = study_findings(workspace)
    except ValueError as failure:
        return [str(failure)]
    return [f"{f.file} is not current: run cheme layout lifting --write" for f in outdated]


def _drawings(
    workspace: Workspace, topic: str, sections: int, records: list[Any] | None
) -> list[str]:
    if records is None:
        from chemeascode.foundation.reviews import load_records

        records = load_records(workspace)
    best = (0, 0, "")
    for record in records:
        front = record.front
        if front is None or front.topic != topic:
            continue
        plans = set(re.findall(r"layout-(?:plan|level)[\w.=,-]*\.(?:png|svg)", record.text))
        cuts = set(re.findall(r"layout-section-[xy][\w.=,-]*\.(?:png|svg)", record.text))
        best = max(best, (len(plans) > 0, len(cuts), record.name))
    has_plan, cuts, name = best
    if not name:
        return [
            f"no review record of topic {topic}: render the plot plan and {sections} sections "
            "(cheme layout render --png), look at them and record the layout review"
        ]
    if not has_plan or cuts < sections:
        return [
            f"{name} cites {'a' if has_plan else 'no'} plot plan and {cuts} section(s); "
            f"a layout review needs the plan and {sections} sections (build/layout-plan.png, "
            "build/layout-section-...png)"
        ]
    return []
