"""Material take-off (MTO) from the generated 3D layout model.

:func:`take_off` reads the model document (``layout/plant-model.yaml``, the contract in
``docs/framework/layout-model.md``) and counts the bulk materials in it:

- **pipe**: length per DN, pipe class and insulation (``m``); the length of a pipe declared
  ``buried`` (``piping/routing.yaml``) that lies in the ground (its top at or below grade) is a
  row of its own, group ``buried`` (for its coating and trench);
- **elbow**: a change of direction inside a pipe's polyline, or where two pipes of one chain
  meet at an angle (``elbow 90``, ``elbow 45``, else ``bend <deg>``);
- **tee**: a pipe end on another pipe's run, or three pipe ends at one point (``tee``, or
  ``reducing tee`` when the branch is smaller; see :func:`_junctions`);
- **reducer**: two pipe ends of different DN at one point, or a placed reducer elsewhere;
- **flange**: one pipe flange at each piped nozzle and at each flange of a placed valve or
  in-line item; **gasket**: one gasket and bolt set per flanged joint (as many as flanges);
- **valve**: placed valves, check valves and safety valves by DEXPI class and DN; **inline**:
  the other placed in-line items (silencers, filters, ...);
- **steel**: tonnage of every ``member`` part from its section and length
  (``data/steel-sections.yaml``) by section and group (rack, structure, stair, ladder,
  platform, step-over, building, equipment); the crane runways are steel, the overhead crane
  itself (bridge, end carriages, crab) is a machine and not in it;
- **grating**: plan area of grating parts (floors, treads, landings, platforms);
- **insulation**: outer surface of insulated pipes, and of ``insulation`` cylinders;
- **concrete**: volume of concrete parts (plinths, foundations, ring walls, bund walls).

The counts are what the model shows: a pipe the router did not route, a fitting the model does
not draw and steel without a section (shoes, chairs, tank handrails) are not in it. The take-off
is deterministic: the same model gives the same rows in the same order.

:func:`mto_report` is the Python entry point (a repository root in, an :class:`MtoReport` out);
``cheme assess mto`` and ``GET /api/mto`` format it. This module reads files only, never
the working directory, and imports no other domain.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import SourceRevision, source_revision
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE

#: Where ``cheme assess mto --write`` puts the take-off.
MTO_CSV = "estimate/mto.csv"
MTO_MD = "estimate/mto.md"
SECTIONS_FILE = Path(__file__).parent / "data" / "steel-sections.yaml"
#: Two points closer than this are one point, m.
TOL = 0.002
#: A buried pipe's top this little above grade still counts as in the ground, m.
GRADE_TOL = 0.001
#: A change of direction above this is a fitting, degrees.
MIN_BEND_DEG = 1.0
#: Valves (category ``valve``) by the model's inline ``kind``.
VALVE_KINDS = ("valve", "check_valve", "safety_valve")
#: Flanges of an in-line item the model draws no flange parts for.
DEFAULT_FLANGES = {"valve": 2, "check_valve": 2, "safety_valve": 2}
#: Model collections whose parts are counted, with the group their parts belong to.
COLLECTIONS = {
    "areas": "area",
    "racks": "rack",
    "buildings": "building",
    "structures": "structure",
    "platforms": "platform",
    "step_overs": "step-over",
    "support_steel": "support-steel",
    "equipment": "equipment",
    "supports": "support",
    "inline": "inline",
}
#: Collections whose proposed (generated) entries are left out until pinned: proposed valve
#: access platforms and support steel.
PROPOSED_ONLY_PINNED = ("structures", "support_steel")
#: A part under one of these keys of an item belongs to this group instead.
SUBGROUPS = {"stairs": "stair", "ladders": "ladder", "ladder": "ladder"}
SIDES = {"north", "south", "east", "west", "start", "end", "a", "b", "x", "y", "base"}
COLUMNS = (
    "category",
    "item",
    "dn",
    "dn2",
    "class",
    "spec",
    "group",
    "count",
    "quantity",
    "unit",
    "length_m",
)
UNITS = {
    "pipe": "m",
    "elbow": "ea",
    "tee": "ea",
    "reducer": "ea",
    "flange": "ea",
    "gasket": "ea",
    "valve": "ea",
    "inline": "ea",
    "steel": "t",
    "grating": "m2",
    "insulation": "m2",
    "concrete": "m3",
}
CATEGORY_ORDER = tuple(UNITS)

Vec = tuple[float, float, float]


@dataclass(frozen=True)
class MtoRow:
    """One line of the take-off: a quantity of one kind of material."""

    category: str
    item: str
    dn: float | None = None
    #: The smaller DN of a reducer, the branch DN of a tee.
    dn2: float | None = None
    #: The pipe class code (pipes, fittings, flanges, valves).
    pipe_class: str = ""
    #: Insulation of a pipe, material of a member.
    spec: str = ""
    #: Where the parts are: rack, structure, stair, ladder, platform, equipment, area, ...
    group: str = ""
    #: Pipes, members or parts counted (for ``ea`` rows: the quantity).
    count: int = 0
    quantity: float = 0.0
    unit: str = ""
    #: Steel: the members' total length, m.
    length_m: float | None = None

    @property
    def key(self) -> str:
        """A readable id of the row, e.g. ``pipe DN100 PN16 bare``."""
        parts = [self.category] + ([self.item] if self.item != self.category else [])
        if self.dn is not None:
            parts.append(f"DN{self.dn:g}" + (f"x{self.dn2:g}" if self.dn2 is not None else ""))
        parts += [p for p in (self.pipe_class, self.spec, self.group) if p]
        return " ".join(parts)

    def csv_row(self) -> dict[str, str]:
        return {
            "category": self.category,
            "item": self.item,
            "dn": _num(self.dn),
            "dn2": _num(self.dn2),
            "class": self.pipe_class,
            "spec": self.spec,
            "group": self.group,
            "count": str(self.count),
            "quantity": _num(self.quantity),
            "unit": self.unit,
            "length_m": _num(self.length_m),
        }


def _num(value: float | None) -> str:
    if value is None:
        return ""
    return f"{round(value, 3):g}"


@dataclass
class TakeOff:
    """The take-off of one model document."""

    rows: list[MtoRow] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    #: ``provenance.output_sha256`` of the model it was taken from.
    model_sha256: str | None = None

    def totals(self) -> dict[str, dict[str, float]]:
        """Quantity per category and unit, e.g. ``{"pipe": {"m": 812.4}}``."""
        found: dict[str, dict[str, float]] = {}
        for row in self.rows:
            unit = found.setdefault(row.category, {})
            unit[row.unit] = round(unit.get(row.unit, 0.0) + row.quantity, 3)
        return found


# -- geometry ------------------------------------------------------------------------------------


def _vec(value: Any) -> Vec:
    return (float(value[0]), float(value[1]), float(value[2]))


def _sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(a: Vec) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _unit(a: Vec) -> Vec | None:
    n = _norm(a)
    return None if n < 1e-9 else (a[0] / n, a[1] / n, a[2] / n)


def _angle(d1: Vec, d2: Vec) -> float:
    dot = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1] + d1[2] * d2[2]))
    return math.degrees(math.acos(dot))


def _key(point: Vec) -> tuple[int, int, int]:
    return (round(point[0] * 500), round(point[1] * 500), round(point[2] * 500))


def _points(pipe: dict[str, Any]) -> list[Vec]:
    """The pipe's polyline without repeated points."""
    out: list[Vec] = []
    for raw in pipe.get("points") or []:
        point = _vec(raw)
        if not out or _norm(_sub(point, out[-1])) > TOL:
            out.append(point)
    return out


def _directions(points: list[Vec]) -> list[Vec]:
    return [d for a, b in zip(points, points[1:], strict=False) if (d := _unit(_sub(b, a)))]


def _sheet(entry: dict[str, Any]) -> str | None:
    """The P&ID sheet a pipe or an in-line item is on (``refs.sheet``)."""
    return (entry.get("refs") or {}).get("sheet")


def _on_segment(p: Vec, a: Vec, b: Vec) -> bool:
    ab = _sub(b, a)
    length = _norm(ab)
    if length < TOL:
        return False
    t = ((p[0] - a[0]) * ab[0] + (p[1] - a[1]) * ab[1] + (p[2] - a[2]) * ab[2]) / length**2
    if t < 0 or t > 1:
        return False
    foot = (a[0] + t * ab[0], a[1] + t * ab[1], a[2] + t * ab[2])
    return _norm(_sub(p, foot)) <= TOL


def _bend_item(angle: float) -> str:
    for nominal in (90, 45):
        if abs(angle - nominal) <= MIN_BEND_DEG:
            return f"elbow {nominal}"
    return f"bend {round(angle):d}"


# -- the collector ------------------------------------------------------------------------------


class _Counter:
    """Sums quantities per row key, keeping the first-seen order irrelevant (rows are sorted)."""

    def __init__(self) -> None:
        self.rows: dict[tuple, list[float]] = {}

    def add(
        self,
        category: str,
        item: str,
        *,
        dn: float | None = None,
        dn2: float | None = None,
        pipe_class: str = "",
        spec: str = "",
        group: str = "",
        count: int = 1,
        quantity: float | None = None,
        length: float | None = None,
    ) -> None:
        key = (category, item, dn, dn2, pipe_class, spec, group)
        entry = self.rows.setdefault(key, [0, 0.0, 0.0])
        entry[0] += count
        entry[1] += float(count) if quantity is None else quantity
        entry[2] += length or 0.0

    def result(self) -> list[MtoRow]:
        rows = []
        for (category, item, dn, dn2, cls, spec, group), (count, qty, length) in self.rows.items():
            rows.append(
                MtoRow(
                    category,
                    item,
                    dn,
                    dn2,
                    cls,
                    spec,
                    group,
                    int(count),
                    round(qty, 3),
                    UNITS[category],
                    round(length, 3) if category == "steel" else None,
                )
            )
        rows.sort(
            key=lambda r: (
                CATEGORY_ORDER.index(r.category),
                r.group,
                r.item,
                -1.0 if r.dn is None else r.dn,
                -1.0 if r.dn2 is None else r.dn2,
                r.pipe_class,
                r.spec,
            )
        )
        return rows


@cache
def section_masses() -> dict[str, float]:
    """kg/m by normalized section name (``data/steel-sections.yaml``, aliases resolved)."""
    data = yaml.safe_load(SECTIONS_FILE.read_text(encoding="utf-8"))
    masses = {_section_name(k): float(v) for k, v in data["sections"].items()}
    for alias, target in (data.get("aliases") or {}).items():
        masses[_section_name(alias)] = masses[_section_name(target)]
    return masses


def _section_name(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).upper()


def _buried_length(pipe: dict[str, Any], points: list[Vec]) -> float:
    """The length of a ``buried`` pipe in the ground: where its top (axis plus OD / 2 and
    insulation) is at or below grade (z = 0), risers through grade counted to grade."""
    r = float(pipe.get("od") or 0.0) / 2 + float(pipe.get("insulation_mm") or 0.0) / 1000.0
    total = 0.0
    for a, b in zip(points, points[1:], strict=False):
        length = _norm(_sub(b, a))
        top_a, top_b = a[2] + r, b[2] + r
        if max(top_a, top_b) <= GRADE_TOL:
            total += length
        elif min(top_a, top_b) < 0.0:
            total += length * -min(top_a, top_b) / abs(top_b - top_a)
    return total


def _pipe_spec(pipe: dict[str, Any]) -> str:
    thickness = float(pipe.get("insulation_mm") or 0.0)
    if thickness <= 0:
        return "bare"
    jacket = pipe.get("jacket")
    return f"insulation {thickness:g} mm" + (f" {jacket}" if jacket else "")


def _class_code(pipe: dict[str, Any] | None) -> str:
    if not pipe:
        return ""
    cls = pipe.get("class") or {}
    return str(cls.get("code") or "") if isinstance(cls, dict) else str(cls)


def _iter_parts(item: Any, group: str) -> list[tuple[str, dict[str, Any]]]:
    """``(group, part)`` for every part under *item*: its ``parts`` and ``walls`` lists and
    those of its stairs and ladders."""
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(item, dict):
        for key, value in item.items():
            if key in ("parts", "walls") and isinstance(value, list):
                found += [(group, p) for p in value if isinstance(p, dict) and "kind" in p]
            elif key in SUBGROUPS:
                found += _iter_parts(value, SUBGROUPS[key])
    elif isinstance(item, list):
        for value in item:
            found += _iter_parts(value, group)
    return found


def _part_name(part: dict[str, Any], area_kind: str | None = None) -> str:
    """The kind of a part from its id's last component: digits and side words dropped
    (``saddle-2-pad`` -> ``saddle-pad``, ``wall-north`` -> ``wall``)."""
    last = str(part.get("id", "")).rsplit("/", 1)[-1]
    tokens = [t for t in last.split("-") if t and not re.fullmatch(r"[a-z]?\d+[a-z]?(\.\d+)?", t)]
    tokens = [t for t in tokens if t not in SIDES] or ["part"]
    name = "-".join(tokens)
    return f"{area_kind} {name}" if area_kind else name


def _volume(part: dict[str, Any]) -> float | None:
    kind = part.get("kind")
    if kind == "box":
        dx, dy, dz = (float(v) for v in part["size"])
        return dx * dy * dz
    if kind == "cylinder":
        return (
            math.pi
            * float(part["radius"]) ** 2
            * _norm(_sub(_vec(part["end"]), _vec(part["start"])))
        )
    if kind == "annulus":
        return _ring_area(part) * float(part.get("depth") or 0.0)
    return None


def _ring_area(part: dict[str, Any]) -> float:
    inner, outer = float(part["radius"]), float(part["radius_end"])
    arc = part.get("arc_deg")
    sweep = 360.0 if not arc else (float(arc[1]) - float(arc[0])) % 360.0 or 360.0
    return math.pi * (outer * outer - inner * inner) * sweep / 360.0


def _plan_area(part: dict[str, Any]) -> float | None:
    kind = part.get("kind")
    if kind == "box":
        return float(part["size"][0]) * float(part["size"][1])
    if kind == "annulus":
        return _ring_area(part)
    return None


# -- the take-off -------------------------------------------------------------------------------


def take_off(model: dict[str, Any], model_file: str = LAYOUT_MODEL_FILE) -> TakeOff:
    """The material take-off of a layout model document (as :func:`yaml.safe_load` gives it)."""
    counter = _Counter()
    findings: list[Finding] = []
    pipes = [p for p in model.get("pipes") or [] if isinstance(p, dict)]
    by_id = {p.get("id"): p for p in pipes}
    # a segment id is unique on its sheet only: key by (sheet, segment)
    by_segment = {(_sheet(p), p.get("segment")): p for p in pipes}
    inline = [i for i in model.get("inline") or [] if isinstance(i, dict)]

    # pipe length and insulation
    for pipe in pipes:
        points = _points(pipe)
        length = sum(_norm(_sub(b, a)) for a, b in zip(points, points[1:], strict=False))
        dn, cls, spec = float(pipe.get("dn") or 0.0), _class_code(pipe), _pipe_spec(pipe)
        buried = _buried_length(pipe, points) if pipe.get("buried") is not None else 0.0
        if length - buried > TOL or buried <= TOL:
            counter.add("pipe", "pipe", dn=dn, pipe_class=cls, spec=spec, quantity=length - buried)
        if buried > TOL:
            counter.add(
                "pipe", "pipe", dn=dn, pipe_class=cls, spec=spec, group="buried", quantity=buried
            )
        thickness = float(pipe.get("insulation_mm") or 0.0) / 1000.0
        if thickness > 0:
            outer = float(pipe.get("od") or 0.0) + 2 * thickness
            counter.add(
                "insulation",
                "pipe insulation",
                dn=dn,
                spec=spec,
                group="pipe",
                quantity=math.pi * outer * length,
            )
        for d1, d2 in zip(_directions(points), _directions(points)[1:], strict=False):
            angle = _angle(d1, d2)
            if angle > MIN_BEND_DEG:
                counter.add("elbow", _bend_item(angle), dn=dn, pipe_class=cls)

    # junctions: tees, reducers, elbows between pipes of one chain
    junction_points = _junctions(pipes, counter)

    # in-line items
    for item in inline:
        pipe = by_id.get(item.get("pipe")) or {}
        dn = float(pipe["dn"]) if pipe.get("dn") is not None else None
        cls = _class_code(pipe)
        kind = item.get("kind", "item")
        dexpi = str(item.get("dexpi_class") or kind)
        if kind in VALVE_KINDS:
            counter.add("valve", dexpi, dn=dn, pipe_class=cls)
        elif kind == "reducer":
            if _key(_vec(item["point"])) not in junction_points:
                counter.add("reducer", "reducer", dn=dn, pipe_class=cls)
            continue
        else:
            counter.add("inline", dexpi, dn=dn, pipe_class=cls)
        flanges = [
            str(p.get("id", "")).rsplit("/", 1)[-1]
            for p in item.get("parts") or []
            if re.fullmatch(r"flange-\d+|outlet-flange", str(p.get("id", "")).rsplit("/", 1)[-1])
        ]
        if not flanges:
            flanges = ["flange"] * DEFAULT_FLANGES.get(kind, 0)
        segments = (item.get("refs") or {}).get("segments") or []
        sheet = _sheet(item) or _sheet(pipe)
        outlet = next(
            (
                by_segment[(sheet, s)]
                for s in segments
                if s != item.get("segment") and (sheet, s) in by_segment
            ),
            pipe,
        )
        for name in flanges:
            on = outlet if name == "outlet-flange" else pipe
            on_dn = float(on["dn"]) if on.get("dn") is not None else None
            for category in ("flange", "gasket"):
                counter.add(
                    category,
                    "weld neck flange" if category == "flange" else "gasket and bolt set",
                    dn=on_dn,
                    pipe_class=_class_code(on),
                )

    # flanges at piped nozzles
    ends: dict[tuple[int, int, int], dict[str, Any]] = {}
    for pipe in pipes:
        points = _points(pipe)
        if points:
            ends.setdefault(_key(points[0]), pipe)
            ends.setdefault(_key(points[-1]), pipe)
    for equipment in model.get("equipment") or []:
        for nozzle in equipment.get("nozzles") or []:
            if not nozzle.get("point"):
                continue
            pipe = ends.get(_key(_vec(nozzle["point"])))
            if pipe is None:
                continue
            for category in ("flange", "gasket"):
                counter.add(
                    category,
                    "weld neck flange" if category == "flange" else "gasket and bolt set",
                    dn=float(pipe.get("dn") or 0.0),
                    pipe_class=_class_code(pipe),
                )

    # steel, grating, insulation and concrete parts
    unknown: dict[str, int] = {}
    for collection, group in COLLECTIONS.items():
        for owner in model.get(collection) or []:
            if collection in PROPOSED_ONLY_PINNED and owner.get("source") == "generated":
                continue  # a proposal (a valve access platform, a post): counted once pinned
            area_kind = owner.get("kind") if collection == "areas" else None
            for part_group, part in _iter_parts(owner, group):
                _count_part(counter, part, part_group, area_kind, unknown)
    if unknown:
        listed = ", ".join(f"{name} ({n})" for name, n in sorted(unknown.items()))
        findings.append(
            Finding(
                model_file,
                "warning",
                "cheme.mto-section-unknown",
                f"steel members of sections without a mass per metre are left out of the "
                f"tonnage: {listed}",
                ids=sorted(unknown),
                hint="name a section of cheme-as-code's steel-sections.yaml (HEB, HEA, IPE, UPN, "
                "L, RHS, FL) in layout/structures.yaml, or add its weight to the estimate by hand",
            )
        )
    if not pipes:
        findings.append(
            Finding(
                model_file,
                "info",
                "cheme.mto-no-pipes",
                "the model has no routed pipes: the take-off has no piping",
                hint="run cheme layout build (with piping/line-list.yaml and the P&IDs)",
            )
        )
    sha = (model.get("provenance") or {}).get("output_sha256")
    return TakeOff(counter.result(), findings, sha)


def _count_part(
    counter: _Counter,
    part: dict[str, Any],
    group: str,
    area_kind: str | None,
    unknown: dict[str, int],
) -> None:
    kind, material = part.get("kind"), part.get("material")
    if kind == "member" and material == "crane" and part.get("lod") == 2:
        return  # the overhead crane's bridge and end carriages: a machine, not bulk steel
    if kind == "member":
        section = re.sub(r"\s+", "", str(part.get("section") or ""))
        start, end = _vec(part["start"]), _vec(part["end"])
        length = _norm(_sub(end, start))
        mass = section_masses().get(_section_name(section))
        if mass is None:
            unknown[section or "(no section)"] = unknown.get(section or "(no section)", 0) + 1
            return
        counter.add(
            "steel",
            section,
            spec=str(material or "steel"),
            group=group,
            quantity=mass * length / 1000.0,
            length=length,
        )
    elif material == "grating":
        area = _plan_area(part)
        if area is not None:
            counter.add("grating", "grating", group=group, quantity=area)
    elif material == "concrete":
        volume = _volume(part)
        if volume is not None:
            counter.add("concrete", _part_name(part, area_kind), group=group, quantity=volume)
    elif material == "insulation" and kind == "cylinder":
        length = _norm(_sub(_vec(part["end"]), _vec(part["start"])))
        counter.add(
            "insulation",
            "equipment insulation",
            group=group,
            quantity=2 * math.pi * float(part["radius"]) * length,
        )


def _junctions(pipes: list[dict[str, Any]], counter: _Counter) -> set[tuple[int, int, int]]:
    """Count the fittings where pipes meet; the keys of the points where a reducer was
    counted (a placed reducer there is the same fitting).

    At each point where pipe ends meet: one pipe running through it and *n* ends on it give
    *n* tees (run DN of the pipe through, branch DN of the end); without a pipe through, two
    ends are a straight joint (a reducer when their DN differ, an elbow when they meet at an
    angle), three ends a tee (run: the two largest), *n* > 3 ends *n* - 2 tees."""
    polylines = [_points(p) for p in pipes]
    boxes = []
    for points in polylines:
        if points:
            xs, ys, zs = zip(*points, strict=True)
            boxes.append((min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)))
        else:
            boxes.append(None)
    meeting: dict[tuple[int, int, int], list[tuple[int, Vec, Vec]]] = {}
    for index, points in enumerate(polylines):
        if len(points) < 2:
            continue
        start_dir = _unit(_sub(points[1], points[0]))
        end_dir = _unit(_sub(points[-1], points[-2]))
        # the direction pointing away from the joint, into the pipe
        meeting.setdefault(_key(points[0]), []).append((index, points[0], start_dir))
        meeting.setdefault(_key(points[-1]), []).append(
            (index, points[-1], (-end_dir[0], -end_dir[1], -end_dir[2]))
        )
    reducers: set[tuple[int, int, int]] = set()
    for key in sorted(meeting):
        ends = meeting[key]
        point = ends[0][1]
        own = {index for index, _, _ in ends}
        through = None
        for index, points in enumerate(polylines):
            if index in own or boxes[index] is None:
                continue
            box = boxes[index]
            if not (
                box[0] - TOL <= point[0] <= box[3] + TOL
                and box[1] - TOL <= point[1] <= box[4] + TOL
                and box[2] - TOL <= point[2] <= box[5] + TOL
            ):
                continue
            if any(_on_segment(point, a, b) for a, b in zip(points, points[1:], strict=False)):
                through = index
                break
        dns = [float(pipes[index].get("dn") or 0.0) for index, _, _ in ends]
        if through is not None:
            run = pipes[through]
            run_dn = float(run.get("dn") or 0.0)
            for dn in dns:
                item = "tee" if abs(dn - run_dn) < 1e-6 else "reducing tee"
                counter.add(
                    "tee",
                    item,
                    dn=max(run_dn, dn),
                    dn2=min(run_dn, dn) if item != "tee" else None,
                    pipe_class=_class_code(run),
                )
            continue
        if len(ends) == 2:
            (i1, _, d1), (i2, _, d2) = ends
            big, small = sorted((i1, i2), key=lambda i: -float(pipes[i].get("dn") or 0.0))
            big_dn, small_dn = (float(pipes[i].get("dn") or 0.0) for i in (big, small))
            if d1 and d2:
                # both directions point away from the joint: in line when opposite
                angle = 180.0 - _angle(d1, d2)
                if angle > MIN_BEND_DEG:
                    counter.add(
                        "elbow", _bend_item(angle), dn=big_dn, pipe_class=_class_code(pipes[big])
                    )
            if abs(big_dn - small_dn) > 1e-6:
                counter.add(
                    "reducer",
                    "reducer",
                    dn=big_dn,
                    dn2=small_dn,
                    pipe_class=_class_code(pipes[big]),
                )
                reducers.add(key)
        elif len(ends) >= 3:
            ordered = sorted(
                ((float(pipes[i].get("dn") or 0.0), i) for i, _, _ in ends), reverse=True
            )
            run_dn, run_index = ordered[0]
            for dn, _ in ordered[2:]:
                item = "tee" if abs(dn - run_dn) < 1e-6 else "reducing tee"
                counter.add(
                    "tee",
                    item,
                    dn=run_dn,
                    dn2=dn if item != "tee" else None,
                    pipe_class=_class_code(pipes[run_index]),
                )
    return reducers


# -- formatting ----------------------------------------------------------------------------------


def mto_csv(rows: list[MtoRow]) -> str:
    """The take-off as CSV (one row per :class:`MtoRow`, columns :data:`COLUMNS`)."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(row.csv_row() for row in rows)
    return buffer.getvalue()


def mto_markdown(takeoff: TakeOff, model_file: str = LAYOUT_MODEL_FILE) -> str:
    """The take-off as a Markdown report: totals, then one table per category."""
    lines = [
        "# Material take-off",
        "",
        f"Generated by `cheme assess mto` from `{model_file}` (model output_sha256 "
        f"`{takeoff.model_sha256 or 'unknown'}`). Quantities are what the 3D model shows: "
        "unrouted lines, fittings it does not draw and steel without a section are not in "
        "them. Check them before pricing (skill `mto-estimate`).",
        "",
        "## Totals",
        "",
        "| category | quantity | unit |",
        "|---|---:|---|",
    ]
    for category, units in takeoff.totals().items():
        for unit, quantity in units.items():
            lines.append(f"| {category} | {_num(quantity)} | {unit} |")
    for category in CATEGORY_ORDER:
        rows = [r for r in takeoff.rows if r.category == category]
        if not rows:
            continue
        lines += ["", f"## {category}", ""]
        lines += [
            "| item | DN | class | spec | group | count | quantity | unit |",
            "|---|---|---|---|---|---:|---:|---|",
        ]
        for r in rows:
            dn = "" if r.dn is None else f"{r.dn:g}" + (f" x {r.dn2:g}" if r.dn2 else "")
            quantity = _num(r.quantity) + (
                f" ({_num(r.length_m)} m)" if r.length_m is not None else ""
            )
            lines.append(
                f"| {r.item} | {dn} | {r.pipe_class} | {r.spec} | {r.group} | {r.count} | "
                f"{quantity} | {r.unit} |"
            )
    if takeoff.findings:
        lines += ["", "## Findings", ""] + [f"- {f.format()}" for f in takeoff.findings]
    return "\n".join(lines) + "\n"


# -- the Python entry point ---------------------------------------------------------------------


@dataclass
class MtoReport:
    """The take-off of a plant repository's committed model, with what it was computed from."""

    root: Path
    takeoff: TakeOff
    #: The git commit and fingerprint of the model file when this was computed.
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))

    @property
    def rows(self) -> list[MtoRow]:
        return self.takeoff.rows

    @property
    def findings(self) -> list[Finding]:
        return self.takeoff.findings

    @property
    def loaded(self) -> bool:
        return not any(f.level == "error" for f in self.findings)

    def payload(self) -> dict[str, Any]:
        """The document ``cheme assess mto --json`` prints and ``GET /api/mto`` serves."""
        return mto_payload(self.takeoff) | {"source": self.source.as_dict()}

    def to_json(self) -> str:
        return json.dumps(self.payload(), indent=2)


def mto_payload(takeoff: TakeOff, model_file: str = LAYOUT_MODEL_FILE) -> dict[str, Any]:
    return {
        "model": model_file,
        "model_sha256": takeoff.model_sha256,
        "columns": list(COLUMNS),
        "rows": [
            {k: v for k, v in asdict(r).items() if k != "pipe_class"}
            | {"class": r.pipe_class, "key": r.key}
            for r in takeoff.rows
        ],
        "totals": takeoff.totals(),
        "findings": [asdict(f) for f in takeoff.findings],
    }


def load_model(text: str | None, model_file: str = LAYOUT_MODEL_FILE) -> tuple[dict | None, list]:
    """The model document of *text*, or None with the finding that says why."""
    if text is None:
        return None, [
            Finding(
                model_file,
                "error",
                "cheme.mto-model-missing",
                f"no {model_file}: there is nothing to take off",
                hint="run cheme layout build and commit the model",
            )
        ]
    try:
        loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
        data = yaml.load(text, Loader=loader)  # a safe loader
    except yaml.YAMLError as failure:
        return None, [
            Finding(model_file, "error", "cheme.mto-model-missing", f"not YAML: {failure}")
        ]
    if not isinstance(data, dict):
        return None, [Finding(model_file, "error", "cheme.mto-model-missing", "not a YAML mapping")]
    return data, []


def model_takeoff(text: str | None, model_file: str = LAYOUT_MODEL_FILE) -> TakeOff:
    """The take-off of a model file's *text* (None: no model)."""
    model, problems = load_model(text, model_file)
    if model is None:
        return TakeOff([], problems)
    return take_off(model, model_file)


def mto_report(root: Path) -> MtoReport:
    """The material take-off of the model ``layout/plant-model.yaml`` under *root*."""
    path = Path(root) / LAYOUT_MODEL_FILE
    text = path.read_text(encoding="utf-8") if path.is_file() else None
    return MtoReport(
        Path(root), model_takeoff(text), source_revision(Path(root), [LAYOUT_MODEL_FILE])
    )


def matches(pattern: str | None, value: str) -> bool:
    """A glob of a rate's ``where:`` (None matches anything)."""
    return pattern is None or fnmatchcase(value, pattern)
