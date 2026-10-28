"""The lifting study of the heavy items of the 3D model (``cheme layout lifting``).

For every item of ``dimensions.weight`` at or above ``heavy_lift_t`` (outside a closed casing)
it states, from the committed ``layout/plant-model.yaml`` and the layout criteria:

- the crane: a building's overhead crane (its ``capacity_t`` against the gross load: the row
  gives the capacity, the utilisation and ``building crane <t> t carries it`` or ``... short``;
  the capacity needed is the gross load), or the nearest ``crane_pad``
  zone within reach (the ``lifting`` rule's choice), with what blocks the lane from the pad
  over the item (the ``lifting`` rule's lane);
- the working radius: in plan from the pad's centre (where the crane is ASSUMED to slew) to
  the item's centre, m;
- the gross load: weight x ``lift_dynamic_factor`` x (1 + ``lift_rigging_fraction``), t; the
  load moment: gross load x radius, t m; the chart capacity needed at that radius: gross load
  / ``lift_chart_utilisation``, t;
- the lift height: the highest top of what stands in the lane (from grade up), plus
  ``lift_clearance_m``, and at least the item's set elevation; the hook height: lift height +
  the item's height + ``lift_rigging_height_m``, m;
- the setdown: the laydown zones within reach that hold the item's footprint, nearest first.

Every factor is ASSUMED (``domains/spatial/data/layout-criteria.yaml``) until the plant's
``criteria:`` or the lifting plan replaces it. Choosing the crane stays a human judgement,
unless the plant gives load charts (``layout/crane-chart.yaml``, kind ``crane_chart``: radius
against capacity, with the source). Then each lift is checked against the charts for its pad:
the capacity at the smallest tabulated radius at or beyond the lift's radius (no
interpolation), and the hook height against ``max_hook_height_m``; a lift no chart carries is
``cheme.layout-lifting-capacity`` (warning).

A written study (``--write``: ``layout/lifting-study.csv`` and ``.md``) that is no longer what
the committed model gives is ``cheme.layout-lifting-study-outdated`` (warning, validate).
"""

from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE, LIST_FILES, Workspace

CHART_FILE = LIST_FILES["crane_chart"]
STUDY_MD = "layout/lifting-study.md"
STUDY_CSV = "layout/lifting-study.csv"
#: What blocks a lane: shown by name up to this many, then counted.
LANE_SHOWN = 6
COLUMNS = (
    "tag",
    "weight_t",
    "crane",
    "pad",
    "radius_m",
    "gross_t",
    "moment_tm",
    "required_t",
    "lift_height_m",
    "hook_height_m",
    "lane",
    "laydown",
    "chart",
    "chart_radius_m",
    "chart_capacity_t",
    "utilisation",
    "status",
)


@dataclass
class Lift:
    """One heavy item's lift (see the module text); lengths m, loads t."""

    tag: str
    weight_t: float
    crane: str  # "building <id>", "mobile", "none"
    pad: str | None
    radius_m: float | None
    gross_t: float
    moment_tm: float | None
    required_t: float
    lift_height_m: float
    hook_height_m: float
    blockers: list[str] = field(default_factory=list)
    laydown: str | None = None
    building_crane_t: float | None = None
    chart: str | None = None
    chart_radius_m: float | None = None
    chart_capacity_t: float | None = None
    utilisation: float | None = None
    status: str = ""
    #: The weight is the item's heaviest maintenance lift (``dimensions.lift_weight``).
    part: bool = False

    def row(self) -> dict[str, str]:
        def num(v: float | None) -> str:
            return "" if v is None else f"{round(v, 3):g}"

        return {
            "tag": self.tag,
            "weight_t": num(self.weight_t),
            "crane": self.crane,
            "pad": self.pad or "",
            "radius_m": num(self.radius_m),
            "gross_t": num(self.gross_t),
            "moment_tm": num(self.moment_tm),
            "required_t": num(self.required_t),
            "lift_height_m": num(self.lift_height_m),
            "hook_height_m": num(self.hook_height_m),
            "lane": (
                " ".join(self.blockers[:LANE_SHOWN])
                + (
                    f" +{len(self.blockers) - LANE_SHOWN}"
                    if len(self.blockers) > LANE_SHOWN
                    else ""
                )
                if self.blockers
                else "clear"
            ),
            "laydown": self.laydown or "",
            "chart": self.chart or "",
            "chart_radius_m": num(self.chart_radius_m),
            "chart_capacity_t": num(self.chart_capacity_t),
            "utilisation": num(self.utilisation),
            "status": self.status,
        }


@dataclass
class LiftingStudy:
    """Every heavy lift, the findings and the criteria used."""

    lifts: list[Lift] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)
    charts: list[str] = field(default_factory=list)
    model_sha256: str | None = None
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    def payload(self) -> dict[str, Any]:
        return {
            "model": LAYOUT_MODEL_FILE,
            "model_sha256": self.model_sha256,
            "criteria": self.criteria,
            "charts": self.charts,
            "lifts": [asdict(lift) for lift in self.lifts],
            "findings": [asdict(f) for f in self.findings],
        }

    def to_json(self) -> str:
        return json.dumps(self.payload() | {"source": self.source.as_dict()}, indent=2)


CRITERIA = (
    "heavy_lift_t",
    "crane_reach_m",
    "lane_margin_m",
    "lift_clearance_m",
    "lift_dynamic_factor",
    "lift_rigging_fraction",
    "lift_rigging_height_m",
    "lift_chart_utilisation",
)


def _capacity(chart: Any, radius: float) -> tuple[float | None, float | None]:
    """The chart's capacity at the smallest tabulated radius at or beyond *radius*."""
    for row in chart.chart:
        if row.radius_m >= radius - 1e-9:
            return row.radius_m, row.capacity_t
    return None, None


def study(
    model: dict[str, Any], routing: Any = None, plan: Any = None, charts: Any = None
) -> LiftingStudy:
    """The lifting study of a model document (see the module text); *charts* a parsed
    ``layout/crane-chart.yaml`` or None."""
    from chemeascode.domains.spatial.engineering_rules import EngineeringRules
    from chemeascode.domains.spatial.model_rules import _Rules, declared_view
    from chemeascode.domains.spatial.schemas import RoutingRules

    rules = routing.rules if routing is not None else RoutingRules()
    eng = EngineeringRules(_Rules(declared_view(model), rules, routing, plan))
    c = eng.criteria
    result = LiftingStudy(
        criteria={name: {"value": c.values[name], "basis": c.basis[name]} for name in CRITERIA},
        charts=[chart.id for chart in getattr(charts, "cranes", None) or ()],
        model_sha256=(model.get("provenance") or {}).get("output_sha256"),
    )
    for case in eng.lift_cases():
        item = case["item"]
        x0, y0, z0, x1, y1, z1 = item["bbox"]
        weight = case["weight"]
        gross = eng.gross_lift_t(weight)
        required = gross / c.lift_chart_utilisation
        tops: dict[str, float] = {}
        radius = None
        pad_id = None
        building = case["building"]
        if case["pad"] is not None:
            pad_id, pad = case["pad"]
            cx, cy = (pad[0] + pad[2]) / 2, (pad[1] + pad[3]) / 2
            radius = math.hypot((x0 + x1) / 2 - cx, (y0 + y1) / 2 - cy)
            eng._lane(item, pad, low=0.0, tops=tops)
        highest = max(tops.values(), default=0.0)
        lift_height = max(highest + c.lift_clearance_m, z0)
        hook = lift_height + (z1 - z0) + c.lift_rigging_height_m
        lift = Lift(
            tag=case["tag"],
            weight_t=weight,
            part=bool(case.get("part")),
            crane=f"building {building['id']}" if building else ("mobile" if pad_id else "none"),
            pad=pad_id,
            radius_m=None if radius is None else round(radius, 3),
            gross_t=round(gross, 3),
            moment_tm=None if radius is None else round(gross * radius, 3),
            required_t=round(required, 3),
            lift_height_m=round(lift_height, 3),
            hook_height_m=round(hook, 3),
            blockers=list(case["blockers"]),
            laydown=min(case["laydowns"], key=lambda e: (e[1], e[0]))[0]
            if case["laydowns"]
            else None,
        )
        if building is not None:
            crane = building.get("crane") or {}
            capacity = crane.get("capacity_t")
            lift.building_crane_t = capacity
            # an overhead crane carries the gross load (hook, rigging, dynamic), not the weight;
            # the chart utilisation of a mobile crane does not apply to it
            lift.required_t = round(gross, 3)
            if capacity is None:
                lift.status = "no crane"
            else:
                lift.chart_capacity_t = float(capacity)
                lift.utilisation = round(gross / float(capacity), 3) if capacity else None
                ok = float(capacity) >= gross - 1e-9
                lift.status = (
                    f"building crane {float(capacity):g} t {'carries it' if ok else 'short'}"
                )
        elif pad_id is None:
            lift.status = "no crane pad"
        elif lift.blockers:
            lift.status = "lane blocked"
        else:
            lift.status = "lane clear"
        if pad_id is not None and charts is not None and charts.cranes:
            _check_charts(lift, charts, result.findings)
        if not lift.laydown:
            lift.status += ", no laydown"
        result.lifts.append(lift)
    return result


def _check_charts(lift: Lift, charts: Any, findings: list[Finding]) -> None:
    usable = [ch for ch in charts.cranes if not ch.pads or lift.pad in ch.pads]
    if not usable:
        findings.append(
            Finding(
                CHART_FILE,
                "warning",
                "cheme.layout-lifting-capacity",
                f"lift of {lift.tag} from {lift.pad}: no crane chart is for that pad",
                ids=[lift.tag, lift.pad or ""],
                hint="add the pad to a chart's pads: (or leave pads: empty for every pad)",
                key=lift.tag,
            )
        )
        lift.status += ", no chart"
        return
    best = None
    for chart in usable:
        at, capacity = _capacity(chart, lift.radius_m or 0.0)
        hook_ok = chart.max_hook_height_m is None or lift.hook_height_m <= chart.max_hook_height_m
        margin = -math.inf if capacity is None else capacity - lift.required_t
        rank = (capacity is not None and margin >= -1e-9 and hook_ok, margin, chart.id)
        if best is None or rank[:2] > best[0][:2]:
            best = (rank, chart, at, capacity, hook_ok)
    assert best is not None
    (fits, _, _), chart, at, capacity, hook_ok = best
    lift.chart, lift.chart_radius_m, lift.chart_capacity_t = chart.id, at, capacity
    if capacity:
        lift.utilisation = round(lift.gross_t / capacity, 3)
    if fits:
        lift.status += f", {chart.id} carries it"
        return
    if capacity is None:
        why = f"its radius {lift.radius_m:g} m is beyond the chart of {chart.id}"
    elif not hook_ok:
        why = (
            f"the hook height {lift.hook_height_m:g} m is above {chart.id}'s "
            f"{chart.max_hook_height_m:g} m"
        )
    else:
        why = (
            f"{chart.id} lifts {capacity:g} t at {at:g} m; the lift needs {lift.required_t:g} t "
            f"({lift.gross_t:g} t gross at {lift.utilisation:.0%} of the chart)"
        )
    lift.status += ", chart short"
    findings.append(
        Finding(
            CHART_FILE,
            "warning",
            "cheme.layout-lifting-capacity",
            f"lift of {lift.tag} ({lift.weight_t:g} t) from {lift.pad} at {lift.radius_m:g} m: "
            f"{why}",
            ids=[lift.tag, lift.pad or "", chart.id],
            hint="a larger crane or configuration (a chart that carries it), a pad nearer the "
            "item, or a lifting plan that accepts it with its reasons",
            key=lift.tag,
        )
    )


def study_csv(result: LiftingStudy) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(lift.row() for lift in result.lifts)
    return buffer.getvalue()


def study_markdown(result: LiftingStudy) -> str:
    lines = [
        "# Lifting study",
        "",
        f"Generated by `cheme layout lifting` from `{LAYOUT_MODEL_FILE}` (model "
        f"output_sha256 `{result.model_sha256 or 'unknown'}`)"
        + (f" and `{CHART_FILE}` ({', '.join(result.charts)})" if result.charts else "")
        + ". Radius from the crane pad's centre (where the crane is ASSUMED to slew) to the "
        "item's centre; gross load = weight x dynamic factor x (1 + rigging fraction); load "
        "moment = gross load x radius; capacity needed = gross load / chart utilisation (a mobile "
        "crane; a building's overhead crane needs the gross load, its capacity_t in the capacity "
        "column); lift "
        "height = highest top in the lane + clearance (at least the set elevation); hook height "
        "= lift height + item height + rigging height.",
        "",
    ]
    if not result.charts:
        lines += [
            "No crane load chart is given (`layout/crane-chart.yaml`): the crane is chosen by "
            "the lifting contractor against the capacity needed at each radius below.",
            "",
        ]
    lines += [
        "| item | weight t | crane | pad | radius m | gross t | moment t m | needed t | lift "
        "height m | hook height m | lane | laydown | chart | capacity t | status |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---|",
    ]
    for lift in result.lifts:
        r = lift.row()
        tag = r["tag"] + (" (heaviest part)" if lift.part else "")
        lines.append(
            f"| {tag} | {r['weight_t']} | {r['crane']} | {r['pad']} | {r['radius_m']} | "
            f"{r['gross_t']} | {r['moment_tm']} | {r['required_t']} | {r['lift_height_m']} | "
            f"{r['hook_height_m']} | {r['lane']} | {r['laydown']} | {r['chart']} | "
            f"{r['chart_capacity_t']} | {r['status']} |"
        )
    lines += ["", "## Criteria (ASSUMED unless the site plan's criteria say otherwise)", ""]
    for name, entry in result.criteria.items():
        lines.append(f"- `{name}` {entry['value']:g}: {entry['basis']}")
    if result.findings:
        lines += ["", "## Findings", ""] + [f"- {f.format()}" for f in result.findings]
    lines += [
        "",
        "Not covered: ground bearing under the crane and its outriggers, the rigging design, "
        "the crane's own clearance to overhead lines and structures while slewing, wind, "
        "tandem lifts and tailing: the lifting plan (competent person, crane contractor).",
    ]
    return "\n".join(lines) + "\n"


def lifting_study(root: Path) -> LiftingStudy:
    """The lifting study of the committed model of the plant repository at *root*.

    Raises :class:`FileNotFoundError` without a model."""
    from chemeascode.domains.spatial.layout_validate import workspace_layout
    from chemeascode.domains.spatial.model import read

    workspace = Workspace(Path(root))
    path = workspace.layout_model_file()
    if path is None:
        raise FileNotFoundError(f"no {LAYOUT_MODEL_FILE}; run cheme layout build")
    model = read(path.read_text(encoding="utf-8"))
    if model is None:
        raise ValueError(f"{LAYOUT_MODEL_FILE} is not a YAML mapping")
    layout = workspace_layout(workspace, None)
    charts = workspace.parsed_lists(("crane_chart",)).get("crane_chart")
    result = study(model, layout.routing, layout.site_plan, charts)
    inputs = [LAYOUT_MODEL_FILE, CHART_FILE, LIST_FILES.get("equipment", "")]
    result.source = source_revision(workspace.root, [p for p in inputs if p])
    return result


def study_findings(workspace: Workspace) -> list[Finding]:
    """``cheme.layout-lifting-study-outdated`` (warning, for ``validate``): a written lifting
    study (``layout/lifting-study.csv`` or ``.md``) that is not what ``cheme layout lifting``
    gives for the committed model now, the check of ``cheme layout lifting --check``. Nothing
    when no study is written or there is no model to compare with."""
    written = [name for name in (STUDY_CSV, STUDY_MD) if (workspace.root / name).is_file()]
    if not written or workspace.layout_model_file() is None:
        return []
    result = lifting_study(workspace.root)
    texts = {STUDY_CSV: study_csv(result), STUDY_MD: study_markdown(result)}
    return [
        Finding(
            name,
            "warning",
            "cheme.layout-lifting-study-outdated",
            f"{name} is not the lifting study of the committed {LAYOUT_MODEL_FILE} (rebuilt, or "
            "its criteria, crane charts or heavy items changed since it was written)",
            hint="run cheme layout lifting --write and commit the study",
        )
        for name in written
        if (workspace.root / name).read_text(encoding="utf-8") != texts[name]
    ]


def capacity_findings(workspace: Workspace, model: dict[str, Any], routing: Any, plan: Any):
    """The ``layout-lifting-capacity`` findings when the plant gives crane charts (for
    ``validate`` and the gates); empty without a chart file."""
    if workspace.list_file("crane_chart") is None:
        return []
    charts = workspace.parsed_lists(("crane_chart",)).get("crane_chart")
    if charts is None:
        return []  # validate reports the schema error
    return study(model, routing, plan, charts).findings
