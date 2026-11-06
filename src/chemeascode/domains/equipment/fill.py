"""``cheme datasheets fill``: calculated sizes into the TBD fields of draft datasheets.

For every draft datasheet (``draft: true``) it calculates what the linked flowsheet streams, the
layout model and the declared parameters allow, and writes each value with its basis: the
calculation and its inputs (stream ids, nozzles, pipes, cited tables) in ``source``,
``assumed: true`` when any input is an assumption. A field it cannot calculate stays ``TBD``
with the reason. It never overwrites a value it did not write: a field is filled only when it
is ``TBD``, missing, or was written by an earlier fill (its source starts with
:data:`FILL_MARK`).

A value calculated from the flowsheet streams carries the :func:`stream_fingerprint` of the
streams at the item's linked nodes, and ``origin: correlation``; a value that reads other inputs
too (a catalyst, the routed pipes and nozzles, the design basis, the sheet's own dimensions)
names them in ``inputs`` and its fingerprint covers them (:func:`input_data`). When those
inputs change, validate reports the value as ``cheme.datasheet-stale`` (warning,
:func:`stale_findings`) until a fill rewrites it. A value without a fingerprint (one an
earlier release filled, or one written by hand) is never reported stale. The sheet's
``operating`` then names the case and the streams (:func:`linked_streams`) the values come
from: ``case`` and ``streams``, which validate resolves (``cheme.contract-ref``). Without
``--case``, a sheet whose ``operating.case`` names a flowsheet case is filled from that case.

What it calculates, by the DEXPI class of the item (the words of
:data:`~chemeascode.domains.equipment.datasheets.TYPE_FIELDS`):

- exchangers, coolers, condensers, reboilers: the duty from the enthalpy change of the linked
  streams (property adapter :mod:`chemeascode.domains.process.props`, refused outside its
  validated range), the LMTD and its correction F for the declared arrangement, and
  ``A = Q / (U F LMTD) (1 + margin)`` with U given or from the typical-coefficient table;
- pumps: differential head from the stream pressures, the static head between the nozzles of
  the source and destination items and the line losses along the routed pipes of
  ``layout/plant-model.yaml`` (:mod:`chemeascode.domains.process.hydraulics`), NPSH available
  from the suction conditions and the vapour pressure, and the power for a declared
  efficiency;
- compressors, blowers, expanders and turbines: the stages for a declared maximum pressure
  ratio per stage, the isentropic or polytropic power for a declared efficiency (real gas
  through the adapter, else ideal gas with a stated Cp/Cv), the intercooler duties;
- columns: Fenske-Underwood-Gilliland stages where the keys and relative volatilities are
  available (:mod:`chemeascode.domains.process.separations.shortcut`); trays from the stages
  less the reboiler and a partial condenser (``type_specific.condenser_type``, else the
  step's ``condenser`` in ``process/simulation.yaml``, else a total condenser, assumed);
- vessels, drums, tanks: the volume from the sheet's dimensions (the inside diameter and the
  tangent length where given; it replaces the draft's volume from the list's dimensions too),
  and the residence time against the design basis' ``residence_times``;
- reactors (a reactor or converter class, or any item linked to a reactive step: DEXPI draws
  a reactor as a vessel): the catalyst mass and bed volume of the linked step's bed
  (``reactor: pfr``, :mod:`chemeascode.domains.process.fixed_bed`), its pressure drop, and the
  vessel volume as the bed's (heads and internals not included: a lower bound); without a bed,
  the bed volume from the catalyst's space velocity (the middle of its range, assumed) and the
  feed; the duty from ``cheme process reactors`` (H(out) - H(in), ideal gas).

The equipment estimate (``cheme assess equipment``) reads the filled sizes (``area_m2``,
``shaft_power_kw``, ``fluid_power_kw``, ``duty_kw``, ``volume_m3``) as it reads any datasheet
value, with their source and ``ASSUMED`` marking.
"""

from __future__ import annotations

import contextlib
import heapq
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from chemeascode.domains.equipment import coverage, sizing
from chemeascode.domains.equipment.datasheets import (
    DATASHEET_DIR,
    DRAFT_SIZING_TBD,
    DRAFT_VOLUME,
    MARKERS,
    VALUE_SECTIONS,
    datasheet_paths,
    field_state,
    type_fields,
    type_row,
)
from chemeascode.domains.process import hydraulics
from chemeascode.domains.process.hydraulics import G
from chemeascode.foundation.findings import Finding
from chemeascode.foundation.provenance import (
    NOT_INPUTS,
    SourceRevision,
    source_revision,
    value_fingerprint,
    written_by,
)
from chemeascode.foundation.units import to_kelvin, to_kpa_abs
from chemeascode.foundation.workspace import LAYOUT_MODEL_FILE, LIST_FILES, Workspace
from chemeascode.foundation.yamlsource import _compose, _yaml_line

#: The start of the source of every value a fill writes (and may rewrite).
FILL_MARK = "cheme datasheets fill"
#: The fields of a stream's state a fill's stream fingerprint covers.
STATE_FIELDS = ("pressure", "temperature", "flow", "composition", "phase", "duty")
#: Parameters a datasheet declares in ``type_specific`` (or ``--param name=value`` gives, as an
#: assumption): name -> (unit, what it is).
PARAMETERS: dict[str, tuple[str, str]] = {
    "arrangement": ("", f"exchanger flow arrangement: {', '.join(sizing.ARRANGEMENTS)}"),
    "u_service": ("", "row of the typical overall coefficients (cheme datasheets fill --list)"),
    "overall_u_w_m2k": ("W/(m2 K)", "overall heat-transfer coefficient"),
    "area_margin": ("", "area margin as a fraction (0.1 = 10 %)"),
    "utility_inlet_temperature_degc": ("degC", "the other side's inlet temperature"),
    "utility_outlet_temperature_degc": ("degC", "the other side's outlet temperature"),
    "pump_efficiency": ("", "pump efficiency (hydraulic power / shaft power)"),
    "density_kg_m3": ("kg/m3", "liquid density"),
    "viscosity_mpa_s": ("mPa s", "liquid viscosity"),
    "vapour_pressure_kpa": ("kPa(a)", "vapour pressure at the suction temperature"),
    "pipe_roughness": ("", "row of the pipe roughness table"),
    "pipe_schedule": ("", "pipe schedule of the routed lines: 40 or 10S"),
    "control_valve_dp_kpa": ("kPa", "control valve pressure drop allowance in the discharge"),
    "stream_pressures_at": (
        "",
        "where a pump's inlet and outlet stream pressures apply: ends (default: at the source "
        "and destination items, static head and routed line losses added) or pump (at the "
        "pump's own nozzles, nothing added)",
    ),
    "suction_from": (
        "",
        "where a pump's suction line starts in the layout model: an item TAG, a nozzle TAG/N or "
        "a pipe's end pipe:<pipe id>:start|end (a battery limit or a tie-in); replaces the "
        "flowsheet's source",
    ),
    "discharge_to": ("", "where a pump's discharge line ends, as suction_from"),
    "mass_flow_kg_h": ("kg/h", "a pump's mass flow, for a pump no flowsheet stream links"),
    "suction_pressure_kpa": (
        "kPa(a)",
        "pressure at suction_from, for a pump no flowsheet stream links",
    ),
    "discharge_pressure_kpa": (
        "kPa(a)",
        "pressure at discharge_to, for a pump no flowsheet stream links",
    ),
    "suction_nozzle": ("", "the pump's suction nozzle (N1, ...)"),
    "discharge_nozzle": ("", "the pump's discharge nozzle"),
    "isentropic_efficiency": ("", "compressor or expander isentropic efficiency"),
    "polytropic_efficiency": ("", "compressor or expander polytropic efficiency"),
    "max_stage_pressure_ratio": ("", "maximum pressure ratio per compressor stage"),
    "intercooler_outlet_temperature_degc": ("degC", "gas temperature after each intercooler"),
    "heat_capacity_ratio": ("", "Cp/Cv of the gas (ideal-gas route)"),
    "mechanical_efficiency": ("", "fluid power / shaft power of a machine"),
    "light_key": ("", "column light key (component id)"),
    "heavy_key": ("", "column heavy key (component id)"),
    "reflux_ratio": ("", "column reflux ratio"),
    "reflux_ratio_factor": ("", "reflux ratio / minimum reflux ratio"),
    "tray_efficiency": ("", "overall stage efficiency of the column"),
    "condenser_type": (
        "",
        "column condenser: total, partial (an equilibrium stage, not a tray) or none",
    ),
}
#: The condenser types of a column (as ``condenser`` of a unit spec in process/simulation.yaml).
CONDENSERS = ("total", "partial", "none")
#: Sub-steps of the real-gas polytropic integration.
POLYTROPIC_STEPS = 50
SIG = 4


class _Refused(Exception):
    """A value cannot be calculated: *reason* goes into its TBD source; *rule* (when set) and
    *level* make it a finding too."""

    def __init__(self, reason: str, rule: str = "", level: str = "info", hint: str = "") -> None:
        super().__init__(reason)
        self.reason, self.rule, self.level, self.hint = reason, rule, level, hint


def _sig(value: float) -> float:
    return float(f"{value:.{SIG}g}")


@dataclass
class Param:
    value: Any
    source: str
    assumed: bool

    def number(self) -> float:
        try:
            return float(self.value)
        except (TypeError, ValueError) as failure:
            raise _Refused(f"{self.source}: {self.value!r} is not a number") from failure

    def text(self) -> str:
        return f"{self.value} ({'ASSUMED: ' if self.assumed else ''}{self.source})"


@dataclass
class FillResult:
    """What a fill run wrote: per datasheet the keys filled and left TBD, the new texts."""

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    #: Datasheets that are not drafts: never filled.
    skipped: list[str] = field(default_factory=list)
    filled: dict[str, list[str]] = field(default_factory=dict)
    tbd: dict[str, list[str]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    #: The git commit and the fingerprints of the inputs when this was computed.
    source: SourceRevision = field(default_factory=lambda: SourceRevision(None))


# -- the stream side ------------------------------------------------------------------------------


@dataclass
class _Stream:
    id: str
    stream: Any
    inputs: Any  # props.Inputs or None
    why: str  # what is missing when inputs is None
    mass_flow: float | None  # kg/s
    pressure: float | None  # kPa(a)
    temperature: float | None  # K


class _Context:
    """The flowsheet, the adapter and the layout model, loaded once per run."""

    def __init__(self, root: Path, case: str | None) -> None:
        from chemeascode.domains.process.model import load

        self.root = root
        self.process, findings = load(root) if (root / "process").is_dir() else (None, [])
        if self.process is not None and any(f.level == "error" for f in findings):
            self.process = None
        self.case = case or (self.process.flowsheet.default_case() if self.process else None)
        self._adapter: Any = None
        self._adapter_error: str | None = None
        path = root / LAYOUT_MODEL_FILE
        self.model: dict[str, Any] | None = None
        if path.is_file():
            try:
                loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
                self.model = loaded if isinstance(loaded, dict) else None
            except yaml.YAMLError:
                self.model = None
        self._network: _Network | None = None
        #: The design basis' residence times by tag.
        self.basis: dict[str, Any] = {}
        #: Whether a stream was read since the last reset: the values written after it carry
        #: the stream fingerprint.
        self.read = False
        self._specs: dict[str, Any] | None = None
        #: Whether ``process/simulation.yaml`` is there but does not load.
        self.specs_unread = False

    @property
    def specs(self) -> dict[str, Any]:
        """The unit specs of ``process/simulation.yaml`` by step id (none when it does not
        load, see :attr:`specs_unread`)."""
        if self._specs is None:
            loaded = _simulation_specs(self.root)
            self.specs_unread = loaded is None
            self._specs = loaded or {}
        return self._specs

    @property
    def network(self) -> _Network | None:
        if self.model is None:
            return None
        if self._network is None:
            self._network = _Network(self.model)
        return self._network

    def adapter(self) -> Any:
        from chemeascode.domains.process.props import Adapter, Unsupported

        if self._adapter is None and self._adapter_error is None:
            try:
                self._adapter = Adapter(self.process)
            except Unsupported as failure:
                self._adapter_error = str(failure)
        if self._adapter is None:
            raise _Refused(
                f"property adapter unavailable: {self._adapter_error}",
                "cheme.datasheet-fill-props",
                "warning",
                "install cheme-as-code with the props extra "
                "(uv tool install 'cheme-as-code[props]')",
            )
        return self._adapter

    def call(self, what: str, fn: Any, *args: Any) -> Any:
        """An adapter call; a refusal becomes a :class:`_Refused` naming *what*."""
        from chemeascode.domains.process.props import Unsupported

        try:
            return fn(*args)
        except Unsupported as failure:
            raise _Refused(
                f"{what}: {failure}",
                f"cheme.datasheet-fill-{failure.rule}",
                "warning",
                "the property method is claimed only inside its validated range "
                "(cheme process props); give the value with its source instead",
            ) from failure

    def linked_nodes(self, tag: str) -> list[str]:
        return _linked_nodes(self.process, tag)

    def fingerprint(self, tag: str) -> str | None:
        if self.process is None or self.case is None:
            return None
        return stream_fingerprint(self.process, tag, self.case)

    def node_tags(self, node_id: str) -> list[str]:
        node = self.process.nodes.get(node_id) if self.process else None
        return [lk.ref for lk in (node.links if node else []) if lk.target == "equipment"]

    def streams(self, node_id: str, direction: str, kind: str = "material") -> list[_Stream]:
        from chemeascode.domains.process.model import stream_flows
        from chemeascode.domains.process.props import gather

        found = []
        fs = self.process.flowsheet
        self.read = True
        for stream in fs.streams:
            end = stream.to if direction == "in" else stream.from_
            if end.split(".", 1)[0] != node_id or stream.kind != kind:
                continue
            state = stream.state.get(self.case)
            gathered = gather(self.process, stream, self.case)
            why = ", ".join(gathered.missing + [m for _, m in gathered.problems])
            flows = stream_flows(self.process, stream, self.case)
            pressure = temperature = None
            if state is not None and state.pressure is not None:
                pressure = to_kpa_abs(
                    state.pressure.value, state.pressure.unit or fs.units.pressure
                )
            if state is not None and state.temperature is not None:
                temperature = to_kelvin(
                    state.temperature.value, state.temperature.unit or fs.units.temperature
                )
            found.append(
                _Stream(
                    stream.id,
                    stream,
                    gathered.inputs,
                    why,
                    flows.total / 3600.0 if flows.total is not None else None,
                    pressure,
                    temperature,
                )
            )
        return found

    def one_in_one_out(self, tag: str) -> tuple[str, _Stream, _Stream]:
        nodes = self.linked_nodes(tag)
        if not nodes:
            raise _Refused(f"no flowsheet node links {tag} (links: in process/flowsheet.yaml)")
        for node in nodes:
            ins, outs = self.streams(node, "in"), self.streams(node, "out")
            if len(ins) == 1 and len(outs) == 1:
                return node, ins[0], outs[0]
        raise _Refused(
            f"no linked node of {tag} has one material inlet and one outlet ({', '.join(nodes)})"
        )

    def molar_mass(self, stream: _Stream) -> float:
        comps = self.process.components()
        if stream.inputs is None:
            raise _Refused(f"stream {stream.id}: {stream.why or 'no state'}")
        total = 0.0
        for name, x in stream.inputs.fractions.items():
            mw = getattr(comps.get(name), "molar_mass", None)
            if not mw:
                raise _Refused(f"no molar_mass of {name} in process/materials.yaml")
            total += x * mw
        return total

    def flash(self, stream: _Stream) -> Any:
        if stream.inputs is None:
            raise _Refused(f"stream {stream.id}: {stream.why or 'no state in case ' + self.case}")
        return self.call(f"stream {stream.id}", self.adapter().flash, stream.inputs)

    def where(self, stream: _Stream) -> str:
        return f"process/flowsheet.yaml stream {stream.id} (case {self.case})"


# -- the layout side: the routed pipes as a network -----------------------------------------------


def _vec(value: Any) -> tuple[float, float, float]:
    return (float(value[0]), float(value[1]), float(value[2]))


def _key(point: tuple[float, float, float]) -> tuple[int, int, int]:
    return (round(point[0] * 500), round(point[1] * 500), round(point[2] * 500))


def _dist(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.dist(a, b)


@dataclass
class _Edge:
    a: tuple[int, int, int]
    b: tuple[int, int, int]
    pipe: dict[str, Any]
    length: float
    fittings: list[str]  # fitting keys of the hydraulics table, or "?<name>" when unknown
    start_dir: tuple[float, float, float] | None
    end_dir: tuple[float, float, float] | None


def _unit(a: tuple[float, ...], b: tuple[float, ...]) -> tuple[float, float, float] | None:
    d = _dist(a, b)
    return None if d < 1e-9 else ((b[0] - a[0]) / d, (b[1] - a[1]) / d, (b[2] - a[2]) / d)


def _angle(d1: tuple[float, ...], d2: tuple[float, ...]) -> float:
    dot = max(-1.0, min(1.0, sum(x * y for x, y in zip(d1, d2, strict=True))))
    return math.degrees(math.acos(dot))


def _bend(angle: float) -> str | None:
    if angle <= 1.0:
        return None
    for nominal, name in ((90, "elbow_90"), (45, "elbow_45")):
        if abs(angle - nominal) <= 1.0:
            return name
    return f"?bend {round(angle)} deg"


class _Network:
    """The routed pipes of a layout model as a graph: nodes are pipe ends and tee points (2 mm
    grid), edges stretches of pipe with their length and fittings; nozzles label their ends."""

    def __init__(self, model: dict[str, Any]) -> None:
        pipes = [p for p in model.get("pipes") or [] if isinstance(p, dict) and p.get("points")]
        self.nozzles: dict[str, tuple[float, float, float]] = {}
        for item in model.get("equipment") or []:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag") or item.get("id"))
            for nozzle in item.get("nozzles") or []:
                if nozzle.get("point"):
                    self.nozzles[f"{tag}/{nozzle.get('name')}"] = _vec(nozzle["point"])
        #: The nozzles the model's items list (not only a pipe's end).
        self.item_nozzles = set(self.nozzles)
        polylines = []
        for pipe in pipes:
            points: list[tuple[float, float, float]] = []
            for raw in pipe["points"]:
                p = _vec(raw)
                if not points or _dist(p, points[-1]) > 0.002:
                    points.append(p)
            polylines.append(points)
        # labels of the ends: nozzle refs
        self.label: dict[tuple[int, int, int], str] = {}
        for pipe, points in zip(pipes, polylines, strict=True):
            if len(points) < 2:
                continue
            for end, point in zip(pipe.get("ends") or [], (points[0], points[-1]), strict=False):
                if isinstance(end, dict) and end.get("kind") == "nozzle" and end.get("ref"):
                    self.label[_key(point)] = str(end["ref"])
                    self.nozzles.setdefault(str(end["ref"]), point)
        inline: dict[str, list[dict[str, Any]]] = {}
        for item in model.get("inline") or []:
            if isinstance(item, dict) and item.get("pipe") and item.get("point"):
                inline.setdefault(str(item["pipe"]), []).append(item)
        # stations along each pipe: (arc position, kind, value)
        self.edges: list[_Edge] = []
        end_points = {}
        for points in polylines:
            if len(points) >= 2:
                end_points[_key(points[0])] = points[0]
                end_points[_key(points[-1])] = points[-1]
        for pipe, points in zip(pipes, polylines, strict=True):
            if len(points) < 2:
                continue
            arcs = [0.0]
            for a, b in zip(points, points[1:], strict=False):
                arcs.append(arcs[-1] + _dist(a, b))
            stations: list[tuple[float, str, Any]] = []
            dirs = [_unit(a, b) for a, b in zip(points, points[1:], strict=False)]
            for i in range(1, len(points) - 1):
                if dirs[i - 1] and dirs[i]:
                    name = _bend(_angle(dirs[i - 1], dirs[i]))
                    if name:
                        stations.append((arcs[i], "fitting", name))
            for item in inline.get(str(pipe.get("id")), []):
                s = self._project(_vec(item["point"]), points, arcs)
                if s is not None:
                    name = str(item.get("dexpi_class") or item.get("kind") or "item")
                    stations.append((s, "fitting", name))
            # a tee on this pipe's run: another pipe's end on its interior
            for key, point in end_points.items():
                if key in (_key(points[0]), _key(points[-1])):
                    continue
                s = self._project(point, points, arcs, tol=0.002)
                if s is not None and 1e-3 < s < arcs[-1] - 1e-3:
                    stations.append((s, "split", key))
            stations.sort(key=lambda t: (t[0], t[1]))
            start, s0, fittings = _key(points[0]), 0.0, []
            start_dir = dirs[0]
            for s, kind, value in stations:
                if kind == "fitting":
                    fittings.append(value if hydraulics.fitting_k(value) else f"?{value}")
                    continue
                self.edges.append(
                    _Edge(
                        start, value, pipe, s - s0, fittings, start_dir, self._dir_at(dirs, arcs, s)
                    )
                )
                start, s0, fittings = value, s, []
                start_dir = self._dir_at(dirs, arcs, s)
            self.edges.append(
                _Edge(start, _key(points[-1]), pipe, arcs[-1] - s0, fittings, start_dir, dirs[-1])
            )
        self.ends: dict[str, tuple[tuple[float, float, float], tuple[float, float, float]]] = {
            str(pipe.get("id")): (points[0], points[-1])
            for pipe, points in zip(pipes, polylines, strict=True)
            if len(points) >= 2
        }
        self.adjacent: dict[tuple[int, int, int], list[int]] = {}
        for index, edge in enumerate(self.edges):
            self.adjacent.setdefault(edge.a, []).append(index)
            self.adjacent.setdefault(edge.b, []).append(index)
        self.by_ref = {ref: key for key, ref in self.label.items()}
        # pipe ends named as end points (open_end): kept apart from the nozzle labels
        self.open_ends: dict[str, tuple[int, int, int]] = {}

    @staticmethod
    def _project(
        p: tuple[float, float, float], points: list, arcs: list[float], tol: float = 0.05
    ) -> float | None:
        best = None
        for i, (a, b) in enumerate(zip(points, points[1:], strict=False)):
            length = _dist(a, b)
            if length < 1e-9:
                continue
            t = sum((p[j] - a[j]) * (b[j] - a[j]) for j in range(3)) / length**2
            t = max(0.0, min(1.0, t))
            foot = tuple(a[j] + t * (b[j] - a[j]) for j in range(3))
            d = _dist(p, foot)
            if d <= tol and (best is None or d < best[0]):
                best = (d, arcs[i] + t * length)
        return best[1] if best else None

    @staticmethod
    def _dir_at(dirs: list, arcs: list[float], s: float) -> Any:
        for i in range(len(dirs)):
            if arcs[i] - 1e-9 <= s <= arcs[i + 1] + 1e-9:
                return dirs[i]
        return dirs[-1]

    def open_end(self, pipe_id: str, end: str) -> str | None:
        """The end point label of the *end* (``start`` or ``end``) of routed pipe *pipe_id*:
        ``pipe:<pipe id>:<end>`` (a battery limit, a free end, or a tie-in where the pipe meets
        another), or the nozzle's label when the end sits on an item nozzle; None when the model
        has no such pipe. The label names the end only as a start or target of :meth:`path`;
        the network is not changed, so other paths still pass through that point."""
        ends = self.ends.get(pipe_id)
        if ends is None or end not in ("start", "end"):
            return None
        point = ends[0] if end == "start" else ends[1]
        key = _key(point)
        if key in self.label:
            return self.label[key]
        ref = f"pipe:{pipe_id}:{end}"
        self.open_ends[ref] = key
        self.nozzles[ref] = point
        return ref

    def path(
        self, start_ref: str, targets: set[str]
    ) -> tuple[str, list[tuple[_Edge, bool]]] | None:
        """The shortest routed path from nozzle *start_ref* (``TAG/N``) to a nozzle of an item
        in *targets* (a tag; or a nozzle ``TAG/N`` or an open end ``pipe:<id>:<end>`` from
        :meth:`open_end`), not passing through another item: ``(target nozzle, [(edge,
        forward)])``."""
        start = self.by_ref.get(start_ref, self.open_ends.get(start_ref))
        if start is None:
            return None
        open_targets = {self.open_ends[t]: t for t in sorted(targets) if t in self.open_ends}
        best: dict[tuple[int, int, int], float] = {start: 0.0}
        back: dict[tuple[int, int, int], tuple[int, bool]] = {}
        queue: list[tuple[float, tuple[int, int, int]]] = [(0.0, start)]
        while queue:
            dist, node = heapq.heappop(queue)
            if dist > best.get(node, math.inf):
                continue
            label = self.label.get(node)
            if node != start and (label or node in open_targets):
                found = open_targets.get(node)
                if found is None and (label.split("/", 1)[0] in targets or label in targets):
                    found = label
                if found is not None:
                    steps = []
                    while node != start:
                        index, forward = back[node]
                        steps.append((self.edges[index], forward))
                        edge = self.edges[index]
                        node = edge.a if forward else edge.b
                    return found, list(reversed(steps))
                if label:
                    continue  # another item's nozzle: the path does not pass through items
            for index in self.adjacent.get(node, []):
                edge = self.edges[index]
                forward = edge.a == node
                other = edge.b if forward else edge.a
                nd = dist + edge.length
                if nd < best.get(other, math.inf) - 1e-12:
                    best[other] = nd
                    back[other] = (index, forward)
                    heapq.heappush(queue, (nd, other))
        return None

    def tees(self, steps: list[tuple[_Edge, bool]]) -> list[str | None]:
        """The tee fitting at the end of each step of the path, aligned with *steps* (``None``
        where the step ends at a plain joint or the path's end): at a node with three or more
        pipe ends, along the run (straight on) or through the branch (turning)."""
        found: list[str | None] = [None] * len(steps)
        for index, ((e1, f1), (e2, f2)) in enumerate(zip(steps, steps[1:], strict=False)):
            node = e1.b if f1 else e1.a
            if len(self.adjacent.get(node, [])) < 3:
                continue
            d_in = e1.end_dir if f1 else _neg(e1.start_dir)
            d_out = e2.start_dir if f2 else _neg(e2.end_dir)
            straight = d_in is not None and d_out is not None and _angle(d_in, d_out) <= 1.0
            found[index] = "tee_run" if straight else "tee_branch"
        return found


def _neg(d: Any) -> Any:
    return None if d is None else (-d[0], -d[1], -d[2])


# -- reading parameters ---------------------------------------------------------------------------


def _is_tbd(entry: Any) -> bool:
    value = entry.get("value") if isinstance(entry, dict) else entry
    return isinstance(value, str) and value.strip().upper().startswith("TBD")


def _ours(entry: Any) -> bool:
    return written_by(entry, FILL_MARK)


def _marked(entry: Any) -> bool:
    """A ``supplier`` or ``not_applicable`` field: the fill never writes it."""
    return field_state(entry) in MARKERS


def _machine_tbd(entry: Any) -> bool:
    """A TBD a tool wrote (a draft's sizing placeholder, or a fill's reason): a fill may
    replace its reason; any other TBD reason was written by hand and is kept."""
    if not isinstance(entry, dict):
        return True
    source = " ".join(str(entry.get("source") or "").split())
    return (
        not source
        or source.endswith(f"({FILL_MARK})")
        or source == f"TBD: {DRAFT_SIZING_TBD}"
        or source.startswith(FILL_MARK)
    )


def fillable(specific: dict[str, Any], key: str) -> bool:
    """Whether a fill may write *key*: missing, TBD, or written by an earlier fill (never a
    ``supplier`` or ``not_applicable`` field)."""
    entry = specific.get(key)
    if key in specific and _marked(entry):
        return False
    return key not in specific or _is_tbd(entry) or _ours(entry)


def _param(specific: dict[str, Any], given: dict[str, str], name: str) -> Param | None:
    entry = specific.get(name)
    if entry is not None and not _is_tbd(entry) and not _ours(entry) and not _marked(entry):
        if isinstance(entry, dict):
            return Param(
                entry.get("value"),
                str(entry.get("source") or f"datasheet type_specific.{name}"),
                bool(entry.get("assumed")),
            )
        return Param(entry, f"datasheet type_specific.{name}", False)
    if name in given:
        value: Any = given[name]
        with contextlib.suppress(ValueError):
            value = float(value)
        return Param(value, f"{FILL_MARK} --param {name}={given[name]}", True)
    return None


# -- the fill -------------------------------------------------------------------------------------


class _Sheet:
    """One draft being filled: its type_specific values, and the rows written."""

    def __init__(self, name: str, data: dict[str, Any], given: dict[str, str]) -> None:
        self.name = name
        self.data = data
        self.specific: dict[str, Any] = data.setdefault("type_specific", {}) or {}
        data["type_specific"] = self.specific
        self.given = given
        self.filled: list[str] = []
        self.tbd: list[str] = []
        self.findings: list[Finding] = []
        self.used: dict[str, Param] = {}
        #: What the item's calculation has read so far, as a filled value's inputs: the declared
        #: parameters asked for (``param:<name>``, found or not: declaring one later changes the
        #: value too) and the sheet's own given values (``datasheet:type_specific.<key>``).
        #: Cleared before each class's calculation (:func:`fill_datasheets`).
        self.read: dict[str, None] = {}
        self.tag = str(data.get("tag") or "").strip()
        #: The flowsheet of the run, and the fingerprint of the streams the item's values are
        #: calculated from (:func:`stream_fingerprint`).
        self.context: _Context | None = None
        self.fingerprint: str | None = None
        #: Whether a value calculated from the streams was written (with the fingerprint).
        self.from_streams = False
        #: The size fields of the item's class: a TBD is added for these only.
        self.required = {k for k, _ in type_fields(str(data.get("type") or ""))}

    def param(self, name: str) -> Param | None:
        found = _param(self.specific, self.given, name)
        self.read[f"param:{name}"] = None
        if found is not None:
            self.used[name] = found
        return found

    def given_number(self, key: str) -> tuple[float, str, bool] | None:
        """The datasheet's own numeric value of *key* (not TBD, not written by a fill): value,
        ``given <key> (<source>)`` and whether it is assumed."""
        self.read[f"datasheet:type_specific.{key}"] = None
        entry = self.specific.get(key)
        if entry is None or fillable(self.specific, key):
            return None
        value = _number(entry)
        if value is None:
            return None
        source = entry.get("source", "") if isinstance(entry, dict) else ""
        assumed = bool(entry.get("assumed")) if isinstance(entry, dict) else False
        text = f"given type_specific.{key} {value:g} ({'ASSUMED: ' if assumed else ''}"
        text += f"{' '.join(str(source).split()) or 'no source given'})"
        return value, text, assumed

    def need(self, name: str, why: str) -> Param:
        found = self.param(name)
        if found is None:
            unit, what = PARAMETERS[name]
            raise _Refused(
                f"declare type_specific.{name} ({what}{', ' + unit if unit else ''}) {why}"
            )
        return found

    def put(
        self,
        key: str,
        value: Any,
        unit: str,
        basis: str,
        assumed: bool,
        replace: bool = False,
        inputs: list[str] | None = None,
        streams: bool = True,
        reads: list[str] | None = None,
    ) -> None:
        """Write *key* when :func:`fillable` (or, with *replace*, when the caller decided it may
        rewrite it: never a marker). Its fingerprint covers the item's streams (once a stream
        was read, unless not *streams*), the *inputs* (:func:`input_data`: shipped table rows
        too, ``table:<table>/<row>``) and the parameters and given values the calculation read
        (*reads*; by default all it read so far, :attr:`read`), named in the entry's
        ``inputs``."""
        if not (fillable(self.specific, key) or replace and not _marked(self.specific.get(key))):
            return
        if isinstance(value, float):
            value = _sig(value)
        elif isinstance(value, list):
            value = [_sig(v) if isinstance(v, float) else v for v in value]
        entry: dict[str, Any] = {"value": value, "unit": unit, "source": f"{FILL_MARK}: {basis}"}
        if assumed:
            entry["assumed"] = True
        context = self.context
        read = self.fingerprint if streams and context is not None and context.read else None
        refs = [*(inputs or []), *(self.read if reads is None else reads)]
        refs = [r for r in dict.fromkeys(refs) if r != f"datasheet:type_specific.{key}"]
        if refs and context is not None:
            for ref in refs:  # a --param named here is recorded, for the stale check to read
                if ref.startswith("param:") and ref not in self.read:
                    self.param(ref.removeprefix("param:"))
            found = {
                ref: input_data(
                    ref,
                    self.data,
                    context.process,
                    context.model,
                    context.basis,
                    context.specs,
                    self.given,
                )
                for ref in refs
            }
            entry["fingerprint"] = inputs_fingerprint(read, found)
            entry["inputs"] = refs
        elif read:
            entry["fingerprint"] = read
        if read:
            entry["origin"] = "correlation"
            self.from_streams = True
        self.specific[key] = entry
        self.filled.append(key)

    def drop(self, key: str) -> None:
        """Remove an earlier fill's value of *key* the calculation no longer gives (the
        intercooler duties of a machine now of one stage): left, it would read as current."""
        entry = self.specific.get(key)
        if entry is not None and _ours(entry) and not _is_tbd(entry):
            del self.specific[key]

    def tbd_value(self, key: str, unit: str, refusal: _Refused, add: bool = False) -> None:
        """Leave *key* TBD with the reason. A field the item's class does not need
        (:func:`~chemeascode.domains.equipment.datasheets.type_fields`) is not added when the
        sheet does not have it (unless *add*: a field every item of the class has); a TBD
        reason written by hand stays as it is."""
        entry = self.specific.get(key)
        if not fillable(self.specific, key):
            return
        if key not in self.specific and key not in self.required and not add:
            return
        if _is_tbd(entry) and not _machine_tbd(entry):
            self.tbd.append(key)
            return
        self.specific[key] = {
            "value": "TBD",
            "unit": unit,
            "source": f"TBD: {refusal.reason} ({FILL_MARK})",
        }
        self.tbd.append(key)
        if refusal.rule:
            key_id = f"{self.tag}/{key}"
            if not any(f.key == key_id for f in self.findings):
                self.findings.append(
                    Finding(
                        self.name,
                        refusal.level,  # type: ignore[arg-type]
                        refusal.rule,
                        f"{self.tag} {key}: {refusal.reason}",
                        ids=[self.tag],
                        hint=refusal.hint or "the value stays TBD",
                        key=key_id,
                    )
                )


def _kind(type_: str) -> str | None:
    row = type_row(type_)
    return row[0][0] if row else None


def fill_datasheets(
    root: Path,
    tags: list[str] | None = None,
    write: bool = True,
    parameters: dict[str, str] | None = None,
    case: str | None = None,
    dimensions: bool = False,
) -> FillResult:
    """Fill the TBD fields of the draft datasheets of the plant repository at *root* (every
    draft, or those of *tags*); with *write*, write them. *parameters* are assumptions the
    caller declares for every item (``--param``); a value a datasheet declares wins.

    Every draft also gets the main dimensions and the empty weight the equipment list and the
    layout model state (:func:`~chemeascode.domains.equipment.outline.derived_dimensions`).
    With *dimensions*, only those are filled, into final datasheets too: a field is added
    when the sheet does not have it, or rewritten when an earlier fill wrote it; a value
    written by hand, a TBD and a marker are kept."""
    root = Path(root)
    workspace = Workspace(root)
    result = FillResult()
    given = dict(parameters or {})
    for name in given:
        if name not in PARAMETERS:
            result.findings.append(
                Finding(
                    DATASHEET_DIR,
                    "error",
                    "cheme.datasheet-fill-param",
                    f"unknown parameter {name}",
                    hint=f"one of {', '.join(sorted(PARAMETERS))}",
                )
            )
    if any(f.level == "error" for f in result.findings):
        return result
    from chemeascode.domains.equipment.outline import derived_dimensions

    equipment = workspace.parsed_lists(("equipment",)).get("equipment")
    listed = {item.tag.strip(): item for item in equipment.equipment} if equipment else {}
    context = _Context(root, case) if not dimensions else None
    default_case = context.case if context is not None else None
    model = context.model if context is not None else _read_model(root)
    result.source = source_revision(
        root,
        [
            "process/flowsheet.yaml",
            "process/materials.yaml",
            "process/design-basis.yaml",
            "equipment/equipment-list.yaml",
            "process/reactions.yaml",
            "process/catalysts.yaml",
            LAYOUT_MODEL_FILE,
            *(workspace.relative(p) for p in datasheet_paths(workspace)),
        ],
    )
    design_basis = _residence_times(root)
    if context is not None:
        context.basis = design_basis
    seen: set[str] = set()
    for path in datasheet_paths(workspace):
        name = workspace.relative(path)
        text = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            continue  # validate reports it
        if not isinstance(data, dict):
            continue
        tag = str(data.get("tag") or path.stem).strip()
        if tags and tag not in tags:
            continue
        seen.add(tag)
        if not data.get("draft") and not dimensions:
            result.skipped.append(name)
            continue
        sheet = _Sheet(name, data, given)
        if tag in listed:  # first: a vessel's volume follows the dimensions
            dims, weights = derived_dimensions(listed[tag], model, mark=FILL_MARK)
            _merge(data, "dimensions", dims, sheet.filled)
            _merge(data, "weights", weights, sheet.filled)
        if not dimensions:
            assert context is not None
            if case is None:  # without --case, a sheet that names a case is filled from it
                context.case = _sheet_case(data, context.process) or default_case
            context.read = False
            sheet.context, sheet.fingerprint = context, context.fingerprint(tag)
            kind = _kind(str(data.get("type") or ""))
            # DEXPI has no reactor class (a reactor is a PressureVessel): a vessel (or an item of
            # no sized class) linked to a reactive step is the reactor; a heater or a column
            # keeps its own fill
            process = context.process
            vessel = kind == "vessel"
            if (
                kind in (None, "vessel")
                and process is not None
                and any(process.reactive(n) for n in context.linked_nodes(tag))
            ):
                kind = "reactor"
            handler = HANDLERS.get(kind or "")
            if kind == "reactor" and vessel:
                # the vessel's own volume (its dimensions) first: the bed's is a lower bound
                _vessel(sheet, context, design_basis.get(tag))
            if handler is not None:
                sheet.read.clear()
                handler(sheet, context)
            if kind in ("vessel", "column"):
                _vessel(sheet, context, design_basis.get(tag))
            if kind == "reactor":
                _bed_fits(sheet)
            if kind is not None:
                _unsupported(sheet, kind)
            if sheet.from_streams and context.case is not None:
                streams = [s.id for s in linked_streams(context.process, tag)]
                _write_references(data, context.case, streams)
        # the --param assumptions this sheet used (a datasheet's own are in its type_specific)
        sheet.used = {k: v for k, v in sheet.used.items() if v.source.startswith(FILL_MARK)}
        old = [
            b
            for b in data.get("sizing_basis") or []
            if str((b or {}).get("reference", "")).startswith(FILL_MARK)
        ]
        # the scope of what a fill writes: preliminary sizing (coverage.SIZING_COVERAGE); kept
        # by a --dimensions run, which calculates no size
        scope = not dimensions or any(
            (b or {}).get("parameter") == coverage.SCOPE_PARAMETER for b in old
        )
        if sheet.used or old or scope:
            basis = [
                b
                for b in data.get("sizing_basis") or []
                if not str((b or {}).get("reference", "")).startswith(FILL_MARK)
            ]
            if scope:
                basis.append(_scope_entry(str(data.get("type") or "")))
            if dimensions:  # no size recalculated: the --param values behind them stay recorded
                basis += [b for b in old if (b or {}).get("parameter") in PARAMETERS]
            for pname, used in sorted(sheet.used.items()):
                unit = PARAMETERS[pname][0]
                basis.append(
                    {
                        "parameter": pname,
                        "value": {
                            "value": used.value,
                            "unit": unit,
                            "source": used.source,
                            **({"assumed": True} if used.assumed else {}),
                        },
                        "reference": f"{FILL_MARK}: {PARAMETERS[pname][1]}",
                    }
                )
            data["sizing_basis"] = basis
        document = _compose(path)
        for finding in sheet.findings:
            key = finding.key.split("/", 1)[-1]
            finding.line = _yaml_line(document, ["type_specific", key])
        result.findings += sheet.findings
        result.filled[name] = sheet.filled
        result.tbd[name] = sheet.tbd
        header = "".join(line for line in text.splitlines(keepends=True)[: _header_lines(text)])
        new = header + yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
        if new == text or data == yaml.safe_load(text):
            result.unchanged.append(name)
            continue
        result.texts[name] = new
        if write:
            path.write_text(new, encoding="utf-8")
        result.written.append(name)
    for tag in tags or []:
        if tag not in seen:
            result.findings.append(
                Finding(
                    DATASHEET_DIR,
                    "error",
                    "cheme.datasheet-fill-tag",
                    f"no datasheet of {tag}",
                    ids=[tag],
                    hint="cheme datasheets draft --tag " + tag,
                )
            )
    return result


def _unsupported(sheet: _Sheet, kind: str) -> None:
    """Leave the fields of the aspects core does not calculate for *kind* (rating, mechanical
    design, corrosion allowance, relief) TBD with the reason, so a draft does not look complete
    there (:func:`.coverage.unsupported_fields`); a field already given or marked stays."""
    for key, unit, reason in coverage.unsupported_fields(kind):
        if key in sheet.tbd or key in sheet.filled:
            continue  # the class's own fill handled it (a column's flooding diameter)
        sheet.tbd_value(key, unit, _Refused(reason), add=True)


def _scope_entry(type_: str) -> dict[str, Any]:
    """The ``sizing_basis`` line that says what the fill's values are: preliminary sizing,
    with the class's unsupported aspects named."""
    kind = coverage.class_of(type_)
    row = coverage.coverage_of(kind or "") or {}
    unsupported = [a.replace("_", " ") for a, cell in row.items() if cell.status == "unsupported"]
    reference = (
        f"{FILL_MARK}: the values it writes are preliminary process sizing (short-cut methods, "
        "declared or typical parameters), not a rating or a design to a code"
    )
    if unsupported:
        reference += "; not calculated: " + ", ".join(unsupported)
    return {
        "parameter": coverage.SCOPE_PARAMETER,
        "value": coverage.SCOPE_VALUE,
        "reference": f"{reference} ({coverage.DOC})",
    }


def _linked_nodes(process: Any, tag: str) -> list[str]:
    """The flowsheet nodes of *process* that link the equipment item *tag*."""
    if process is None:
        return []
    return [
        node_id
        for node_id, node in process.nodes.items()
        if any(lk.target == "equipment" and lk.ref == tag for lk in node.links)
    ]


def linked_streams(process: Any, tag: str) -> list[Any]:
    """The flowsheet streams of *process* that start or end at a node linking *tag*, in
    flowsheet order: those a fill reads, and those :func:`stream_fingerprint` covers."""
    nodes = set(_linked_nodes(process, tag))
    return [
        stream
        for stream in (process.flowsheet.streams if process is not None else [])
        if stream.from_.split(".", 1)[0] in nodes or stream.to.split(".", 1)[0] in nodes
    ]


def _sheet_case(data: dict[str, Any], process: Any) -> str | None:
    """The flowsheet case the sheet's ``operating.case`` names, when *process* has it."""
    operating = data.get("operating")
    named = operating.get("case") if isinstance(operating, dict) else None
    if process is None or not isinstance(named, str):
        return None
    return named if named in {c.id for c in process.flowsheet.cases} else None


def _write_references(data: dict[str, Any], case: str, streams: list[str]) -> None:
    """Record in ``operating`` the flowsheet *case* and *streams* the sheet's values were
    calculated from: ``case`` and ``streams`` first, replacing those of an earlier fill."""
    operating = data.get("operating")
    if operating is not None and not isinstance(operating, dict):
        return  # not a mapping: validate reports it
    rest = {k: v for k, v in (operating or {}).items() if k not in ("case", "streams")}
    refs = {"case": case, "streams": streams, **rest}
    if "operating" in data:
        data["operating"] = refs
        return
    # a new section: after the sheet's head (tag, type, service, draft)
    items = list(data.items())
    head = [i for i, (k, _) in enumerate(items) if k in ("tag", "type", "service", "draft")]
    items.insert(head[-1] + 1 if head else 0, ("operating", refs))
    data.clear()
    data.update(items)


def stream_fingerprint(process: Any, tag: str, case: str) -> str | None:
    """The input fingerprint of the values a fill calculates for *tag* from the flowsheet in
    *case*: the states of every stream at a node linked to *tag* (their values and units, not
    their provenance, source, fingerprint, uncertainty or origin: ``NOT_INPUTS``). None when
    no stream is there."""
    data: dict[str, Any] = {}
    for stream in linked_streams(process, tag):
        state = stream.state.get(case)
        data[stream.id] = {
            name: value.model_dump(mode="json", exclude=NOT_INPUTS)
            for name in STATE_FIELDS
            if (value := getattr(state, name, None)) is not None
        }
    return value_fingerprint({"case": case, "streams": data}) if data else None


def _stripped(data: Any) -> Any:
    """*data* without the fields that describe a value rather than state it (``NOT_INPUTS``,
    and a filled value's ``inputs``), at any depth."""
    if isinstance(data, dict):
        return {k: _stripped(v) for k, v in data.items() if k not in NOT_INPUTS | {"inputs"}}
    if isinstance(data, list):
        return [_stripped(v) for v in data]
    return data


def input_data(
    ref: str,
    data: dict[str, Any],
    process: Any,
    model: dict[str, Any] | None,
    basis: dict[str, Any],
    specs: dict[str, Any] | None = None,
    given: dict[str, Any] | None = None,
) -> Any:
    """What the input *ref* of a filled value (its ``inputs``) states now, for its
    fingerprint; None when it is not there: ``catalyst:<id>`` (the catalyst of
    ``process/catalysts.yaml``), ``pipe:<id>`` (the routed pipe of the layout *model* with the
    inline items on it), ``nozzle:<TAG>/<N>`` (an item's nozzle there), ``residence_time:<TAG>``
    (the design *basis* rule), ``condenser:<step>`` (the condenser the step's unit spec in
    ``process/simulation.yaml``, *specs*, declares), ``datasheet:<section>.<key>`` (a value of
    the sheet *data*), ``param:<name>`` (the declared parameter as the fill reads it: the
    sheet's ``type_specific`` value, else the ``--param`` value, *given*, or the one a fill
    recorded in the sheet's ``sizing_basis``) or ``table:<table>/<row>`` (a row of a table
    cheme-as-code ships: ``overall-coefficients/<row>``, ``roughness/<row>``,
    ``fittings/<row>``, ``pipe-sizes/<schedule>/DN<dn>``) or ``recipe:<unit procedure>`` (its
    entry and the batch size in ``process/recipe.yaml``)."""
    kind, _, name = ref.partition(":")
    model = model or {}
    if kind == "condenser":
        return _declared_condenser((specs or {}).get(name))
    if kind == "param":
        specific = data.get("type_specific")
        found = _param(
            specific if isinstance(specific, dict) else {},
            _recorded_params(data) if given is None else given,
            name,
        )
        return {"value": found.value, "assumed": found.assumed} if found is not None else None
    if kind == "table":
        return _table_row(name)
    if kind == "recipe":
        from chemeascode.domains.process.recipe import load_recipe

        recipe = load_recipe(process.root)[0] if process is not None else None
        procedures = [u for u in (recipe.unit_procedures if recipe else []) if u.id == name]
        if not procedures:
            return None
        # the batch's content is the batch size over this stream's rate: its state counts too
        stream = next(
            (s for s in process.flowsheet.streams if s.id == recipe.batch_size.stream), None
        )
        return _stripped(
            {
                "batch_size": recipe.batch_size.model_dump(mode="json"),
                "batch_size_stream": (
                    {c: q.model_dump(mode="json") for c, q in stream.state.items()}
                    if stream is not None
                    else None
                ),
                "unit_procedure": procedures[0].model_dump(mode="json", by_alias=True),
            }
        )
    if kind == "catalyst":
        catalysts = process.catalysts.by_id() if process is not None and process.catalysts else {}
        found = catalysts.get(name)
        return _stripped(found.model_dump(mode="json")) if found is not None else None
    if kind == "pipe":
        pipes = [p for p in model.get("pipes") or [] if isinstance(p, dict) and p.get("id") == name]
        inline = [i for i in model.get("inline") or [] if isinstance(i, dict)]
        inline = [i for i in inline if str(i.get("pipe")) == name]
        return _stripped({"pipe": pipes, "inline": inline}) if pipes else None
    if kind == "nozzle":
        tag, _, nozzle = name.partition("/")
        for item in model.get("equipment") or []:
            if isinstance(item, dict) and str(item.get("tag") or item.get("id")) == tag:
                for entry in item.get("nozzles") or []:
                    if isinstance(entry, dict) and str(entry.get("name")) == nozzle:
                        return _stripped(entry)
        return None
    if kind == "residence_time":
        rule = basis.get(name)
        return _stripped(rule.model_dump(mode="json")) if rule is not None else None
    if kind == "datasheet":
        section, _, key = name.partition(".")
        holder = data.get(section)
        return _stripped(holder.get(key)) if isinstance(holder, dict) else None
    return None


def _recorded_params(data: dict[str, Any]) -> dict[str, Any]:
    """The ``--param`` values a fill used for the sheet *data*, as it recorded them in
    ``sizing_basis``."""
    found: dict[str, Any] = {}
    for entry in data.get("sizing_basis") or []:
        if not isinstance(entry, dict) or entry.get("parameter") not in PARAMETERS:
            continue
        value = entry.get("value")
        if str(entry.get("reference", "")).startswith(FILL_MARK) and isinstance(value, dict):
            found[str(entry["parameter"])] = value.get("value")
    return found


def _table_row(name: str) -> Any:
    """The row *name* (``<table>/<row>``) of a shipped table, as :func:`input_data` reads it."""
    table, _, row = name.partition("/")
    if table == "overall-coefficients":
        return sizing.u_row(row)
    if table in ("roughness", "fittings"):
        return hydraulics.table_row(table, row)
    if table == "pipe-sizes":
        schedule, _, dn = row.partition("/")
        with contextlib.suppress(ValueError):
            return hydraulics.size_row(float(dn.removeprefix("DN")), schedule)
    return None


def inputs_fingerprint(streams: str | None, inputs: dict[str, Any]) -> str:
    """The fingerprint of a filled value that names *inputs* (``{ref: input_data}``), over the
    :func:`stream_fingerprint` *streams* too (None: it does not depend on the streams)."""
    return value_fingerprint({"streams": streams, "inputs": inputs})


@dataclass
class _Recorded:
    """A filled value's place in its sheet, its fingerprint and its named inputs."""

    where: list[str]
    fingerprint: str
    inputs: list[str]
    #: Whether it was calculated from the streams too (``origin: correlation``).
    streams: bool


def _fingerprinted(node: Any, where: list[str], found: list[_Recorded]) -> None:
    if isinstance(node, dict) and "value" in node:
        if node.get("fingerprint") and _ours(node):
            inputs = node.get("inputs")
            refs = [str(r) for r in inputs] if isinstance(inputs, list) else []
            streams = node.get("origin") == "correlation"
            found.append(_Recorded(where, str(node["fingerprint"]), refs, streams))
    elif isinstance(node, dict):
        for key, entry in node.items():
            _fingerprinted(entry, [*where, str(key)], found)


def stale_findings(workspace: Workspace) -> list[Finding]:
    """``cheme.datasheet-stale`` (warning): a datasheet value a fill calculated whose
    fingerprint matches its inputs in no case of the flowsheet any more: the item's streams
    (:func:`stream_fingerprint`) and the inputs it names (:func:`input_data`). Only values with a
    ``fingerprint`` are compared; nothing is reported when the flowsheet does not load (validate
    reports that)."""
    from chemeascode.domains.process.model import load

    sheets: list[tuple[Path, dict[str, Any], str, list[_Recorded]]] = []
    for path in datasheet_paths(workspace):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        found: list[_Recorded] = []
        for section in VALUE_SECTIONS:
            if isinstance(data.get(section), dict):
                _fingerprinted(data[section], [section], found)
        if found:
            sheets.append((path, data, str(data.get("tag") or path.stem).strip(), found))
    root = workspace.root
    if not sheets:
        return []
    process = None
    if (root / "process").is_dir():
        process, problems = load(root)
        if process is None or any(f.level == "error" for f in problems):
            return []
    cases = [c.id for c in process.flowsheet.cases] if process is not None else []
    model = _read_model(root)
    basis = _loaded_residence_times(root)
    # the kinds of input whose file is there but does not load: not compared (validate reports
    # the file), as the streams of a flowsheet that does not load
    unread = {"residence_time"} if basis is None else set()
    if model is None and (root / LAYOUT_MODEL_FILE).is_file():
        unread |= {"pipe", "nozzle"}
    specs: dict[str, Any] | None = {}
    if any(r.startswith("condenser:") for *_, found in sheets for v in found for r in v.inputs):
        specs = _simulation_specs(root)
        if specs is None:
            unread.add("condenser")
    findings = []
    for path, data, tag, found in sheets:
        streams = {stream_fingerprint(process, tag, case) for case in cases}
        stale = []
        for value in found:
            if value.inputs:
                if value.streams and process is None:
                    continue  # from the streams, and no flowsheet
                if any(r.partition(":")[0] in unread for r in value.inputs):
                    continue
                named = {
                    r: input_data(r, data, process, model, basis or {}, specs) for r in value.inputs
                }
                current = {inputs_fingerprint(s, named) for s in [*streams, None]}
            elif process is None:
                continue  # from the streams, and no flowsheet
            else:
                current = streams
            if value.fingerprint not in current:
                stale.append(value.where)
        if not stale:
            continue
        names = [".".join(where) for where in stale]
        findings.append(
            Finding(
                workspace.relative(path),
                "warning",
                "cheme.datasheet-stale",
                f"{tag}: {', '.join(names[:6])}"
                + (f" and {len(names) - 6} more" if len(names) > 6 else "")
                + " filled from inputs that have changed since (the flowsheet streams, or what "
                "the value's inputs name)",
                line=_yaml_line(_compose(path), stale[0]),
                ids=[tag],
                hint=f"cheme datasheets fill --tag {tag} rewrites them (a draft: true sheet); "
                "or check each value and give it with its own source",
            )
        )
    return findings


def _read_model(root: Path) -> dict[str, Any] | None:
    path = root / LAYOUT_MODEL_FILE
    if not path.is_file():
        return None
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return None
    return loaded if isinstance(loaded, dict) else None


def _merge(data: dict[str, Any], section: str, found: dict[str, Any], filled: list[str]) -> None:
    """Put the derived entries *found* into ``data[section]``: a key the sheet does not have,
    or one an earlier fill wrote (its source starts with :data:`FILL_MARK`); a value written
    by hand, a TBD and a marker stay. A nested group (``support``) is merged key by key."""
    if not found:
        return
    target = data.get(section)
    if not isinstance(target, dict):
        if target is not None:
            return  # not a mapping: validate reports it
        target = {}
    changed = False

    def put(holder: dict[str, Any], key: str, entry: Any, path: str) -> None:
        nonlocal changed
        old = holder.get(key)
        if isinstance(entry, dict) and "value" not in entry:  # a group: support
            group = old if isinstance(old, dict) and "value" not in old else None
            if group is None:
                if key in holder:
                    return
                group = {}
            before = dict(group)
            for sub, value in entry.items():
                put(group, sub, value, f"{path}.{sub}")
            if group != before:
                holder[key] = group
            return
        if key in holder and not _ours(old):
            return
        if old != entry:
            holder[key] = entry
            filled.append(path)
            changed = True

    for key, entry in found.items():
        put(target, key, entry, f"{section}.{key}")
    if section in data:
        data[section] = target
    elif changed:  # a new section: after the one it follows in the schema
        after = {"dimensions": ("materials", "design"), "weights": ("dimensions", "materials")}
        anchor = next((k for k in after.get(section, ()) if k in data), None)
        items = list(data.items())
        at = [k for k, _ in items].index(anchor) + 1 if anchor else len(items)
        items.insert(at, (section, target))
        data.clear()
        data.update(items)


def _header_lines(text: str) -> int:
    count = 0
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        count += 1
    return count


def _residence_times(root: Path) -> dict[str, Any]:
    return _loaded_residence_times(root) or {}


def _loaded_residence_times(root: Path) -> dict[str, Any] | None:
    """The design basis' residence times by tag; None when the file is there but does not
    load (validate reports it)."""
    from chemeascode.domains.requirements.schemas import DesignBasis

    path = root / "process" / "design-basis.yaml"
    if not path.is_file():
        return {}
    try:
        basis = DesignBasis.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    except Exception:  # noqa: BLE001 - validate reports a design basis that does not load
        return None
    return {r.tag: r for r in basis.residence_times}


def _simulation_specs(root: Path) -> dict[str, Any] | None:
    """The unit specs of ``process/simulation.yaml`` by step id; None when the file is there
    but does not load (validate reports it)."""
    from chemeascode.domains.process.simulation import SIMULATION_FILE
    from chemeascode.domains.process.simulation.schema import Simulation

    path = root / SIMULATION_FILE
    if not path.is_file():
        return {}
    try:
        simulation = Simulation.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        )
    except Exception:  # noqa: BLE001 - validate reports a simulation file that does not load
        return None
    return dict(simulation.specs)


def _declared_condenser(spec: Any) -> str | None:
    """A unit spec's ``condenser`` where the file states it (the schema's default ``total`` is
    not a declaration)."""
    return spec.condenser if spec is not None and "condenser" in spec.model_fields_set else None


# -- exchangers -----------------------------------------------------------------------------------


@dataclass
class _Side:
    """One side of an exchanger: a linked node with one material inlet and one outlet."""

    node: str
    inlet: _Stream
    outlet: _Stream

    def temperatures(self) -> tuple[float, float]:
        if self.inlet.temperature is None or self.outlet.temperature is None:
            raise _Refused(f"streams {self.inlet.id}/{self.outlet.id}: temperatures missing")
        return self.inlet.temperature, self.outlet.temperature

    def duty(self, context: _Context) -> tuple[float, str]:
        """The heat the side takes up, kW (negative: it gives heat off), and the basis."""
        a, b = self.inlet, self.outlet
        if a.mass_flow is None:
            raise _Refused(f"stream {a.id}: no flow in case {context.case}")
        ra, rb = context.flash(a), context.flash(b)
        mw = ra.molar_mass
        duty = a.mass_flow / mw * (rb.enthalpy - ra.enthalpy)
        basis = (
            f"Q = n (h_out - h_in) = {a.mass_flow * 3600:.6g} kg/h / {mw:.4g} kg/kmol x "
            f"({rb.enthalpy:.6g} - {ra.enthalpy:.6g}) kJ/kmol, streams {a.id} -> {b.id} "
            f"(process/flowsheet.yaml, case {context.case}), enthalpies by the property adapter "
            "(cheme process props method)"
        )
        return duty, basis


def _sides(sheet: _Sheet, context: _Context) -> list[_Side]:
    nodes = context.linked_nodes(sheet.tag)
    if not nodes:
        raise _Refused(f"no flowsheet node links {sheet.tag} (links: in process/flowsheet.yaml)")
    sides = []
    for node in nodes:
        ins, outs = context.streams(node, "in"), context.streams(node, "out")
        if len(ins) == 1 and len(outs) == 1:
            sides.append(_Side(node, ins[0], outs[0]))
    if not sides:
        raise _Refused(
            f"no linked node has one material inlet and one outlet ({', '.join(nodes)}), so "
            "no side gives the duty and temperatures"
        )
    return sides


def _duty(sheet: _Sheet, context: _Context) -> tuple[float, str, bool] | None:
    """The duty, kW: the datasheet's own value, else calculated and written; None (and TBD)
    when neither."""
    given = sheet.given_number("duty_kw")
    if given is not None:
        return given
    try:
        sides = _sides(sheet, context)
        duty, basis = sides[0].duty(context)
        sheet.put("duty_kw", abs(duty), "kW", basis, False)
        if len(sides) > 1:
            other, _ = sides[1].duty(context)
            if abs(abs(other) - abs(duty)) > 0.01 * abs(duty):
                sheet.findings.append(
                    Finding(
                        sheet.name,
                        "warning",
                        "cheme.datasheet-fill-balance",
                        f"{sheet.tag}: the sides' duties differ, {abs(duty):.4g} kW "
                        f"({sides[0].node}) and {abs(other):.4g} kW ({sides[1].node})",
                        ids=[sheet.tag],
                        hint="check the stream states of both sides",
                        key=f"{sheet.tag}/duty_kw",
                    )
                )
        return abs(duty), basis, False
    except _Refused as refusal:
        sheet.tbd_value("duty_kw", "kW", refusal)
        return None


def _heater(sheet: _Sheet, context: _Context) -> None:
    _duty(sheet, context)


def _exchanger(sheet: _Sheet, context: _Context) -> None:
    duty = _duty(sheet, context)
    # temperatures of both sides: a cooled side (inlet warmer than outlet) is the hot one
    try:
        sides = _sides(sheet, context)
        side = sides[0]
        t_in, t_out = side.temperatures()
        if len(sides) > 1:
            u_in, u_out = sides[1].temperatures()
            other_basis = f"streams {sides[1].inlet.id} -> {sides[1].outlet.id}"
            other_assumed = False
        else:
            p_in = sheet.need("utility_inlet_temperature_degc", "(one side is linked)")
            p_out = sheet.need("utility_outlet_temperature_degc", "(one side is linked)")
            u_in, u_out = p_in.number() + 273.15, p_out.number() + 273.15
            other_basis = f"other side {p_in.text()} -> {p_out.text()} degC"
            other_assumed = p_in.assumed or p_out.assumed
        if t_in > t_out or (t_in == t_out and u_in < u_out):
            hot, cold = (t_in, t_out), (u_in, u_out)
        else:
            hot, cold = (u_in, u_out), (t_in, t_out)
        arrangement = sheet.need("arrangement", "to choose the LMTD correction")
        arr = str(arrangement.value)
        try:
            dt = sizing.lmtd(hot[0], hot[1], cold[0], cold[1], arr)
            f = sizing.correction_factor(hot[0], hot[1], cold[0], cold[1], arr)
        except ValueError as failure:
            raise _Refused(
                str(failure),
                "cheme.datasheet-fill-temperatures",
                "warning",
                "check the stream temperatures and the arrangement",
            ) from failure
        temps = (
            f"hot {hot[0]:.5g} -> {hot[1]:.5g} K, cold {cold[0]:.5g} -> {cold[1]:.5g} K "
            f"(streams {side.inlet.id} -> {side.outlet.id}; {other_basis})"
        )
        assumed = other_assumed or arrangement.assumed
        # the temperatures and the arrangement, not a given duty
        reads = [r for r in sheet.read if r != "datasheet:type_specific.duty_kw"]
        sheet.put(
            "lmtd_k", dt, "K", f"LMTD, {arr} ({arrangement.source}), {temps}", assumed, reads=reads
        )
        if arr != "1-2":
            sheet.drop("lmtd_correction_f")
        else:
            low = f < sizing.F_MIN
            sheet.put(
                "lmtd_correction_f",
                f,
                "",
                f"F, 1 shell pass ({sizing.BOWMAN}), {temps}"
                + (f"; below {sizing.F_MIN_SOURCE}" if low else ""),
                assumed,
                reads=reads,
            )
            if low:
                sheet.findings.append(
                    Finding(
                        sheet.name,
                        "warning",
                        "cheme.datasheet-fill-correction-factor",
                        f"{sheet.tag}: LMTD correction F {f:.3g} of one 1-2 shell is below "
                        f"{sizing.F_MIN_SOURCE}",
                        ids=[sheet.tag],
                        hint="more shells in series or a counter-current exchanger; the area "
                        "is written but is not a sound single-shell design",
                        key=f"{sheet.tag}/lmtd_correction_f",
                    )
                )
    except _Refused as refusal:
        for key, unit in (("lmtd_k", "K"), ("area_m2", "m2")):
            sheet.tbd_value(key, unit, refusal)
        return
    try:
        if duty is None:
            raise _Refused("needs the duty")
        q, q_basis, q_assumed = duty
        given_u = sheet.param("overall_u_w_m2k")
        u_inputs: list[str] = []
        if given_u is not None:
            u, u_basis, u_assumed = given_u.number(), f"U {given_u.text()}", given_u.assumed
        else:
            row = sheet.need("u_service", "or overall_u_w_m2k, to choose U")
            typical = sizing.typical_u(str(row.value))
            if typical is None:
                raise _Refused(
                    f"u_service {row.value!r} is not a row of the typical overall coefficients"
                )
            u, u_assumed = typical.value, True
            u_basis = (
                f"U {typical.value:g} W/(m2 K) ASSUMED as design typical (middle of "
                f"{typical.low:g}-{typical.high:g}), {typical.source}"
            )
            u_inputs = [f"table:overall-coefficients/{typical.id}"]
            sheet.put(
                "overall_u_w_m2k",
                u,
                "W/(m2 K)",
                u_basis,
                True,
                inputs=u_inputs,
                reads=["param:overall_u_w_m2k", "param:u_service"],
            )
        margin_param = sheet.param("area_margin")
        margin = margin_param.number() if margin_param else 0.0
        margin_text = (
            f"margin {margin_param.text()}" if margin_param else "no margin (none declared)"
        )
        area = sizing.exchanger_area(q, u, f, dt, margin)
        q_text = q_basis if q_basis.startswith("Q =") else f"Q {q_basis}"
        sheet.put(
            "area_m2",
            area,
            "m2",
            f"A = Q / (U F LMTD) (1 + margin) = {q:.4g} kW / ({u:.4g} x {f:.4g} x "
            f"{dt:.4g} K) x {1 + margin:g}; {u_basis}; {margin_text}; {q_text}",
            assumed or u_assumed or q_assumed or bool(margin_param and margin_param.assumed),
            inputs=u_inputs,
        )
    except _Refused as refusal:
        sheet.tbd_value("area_m2", "m2", refusal)


# -- pumps ----------------------------------------------------------------------------------------


#: The parameters of a pump's discharge side and its power: not inputs of its NPSH available.
_NOT_NPSH = frozenset(
    f"param:{name}"
    for name in (
        "control_valve_dp_kpa",
        "discharge_nozzle",
        "discharge_to",
        "discharge_pressure_kpa",
        "pump_efficiency",
    )
)


@dataclass
class _Line:
    nozzle: str  # the pump nozzle (TAG/N)
    target: str  # the nozzle at the other end
    loss: Any  # hydraulics.LineLoss
    text: str
    elevation_pump: float
    elevation_target: float
    assumed: bool
    #: The routed pipes, the nozzles at both ends and the table rows read (pipe sizes, roughness,
    #: fitting K), as a filled value's inputs.
    inputs: list[str]


def _route(
    sheet: _Sheet,
    context: _Context,
    nozzle_param: str,
    targets: list[str],
    exclude: str | None,
    mass_flow: float,
    density: float,
    viscosity: float,
    what: str,
) -> _Line:
    network = context.network
    if network is None:
        raise _Refused(f"no {LAYOUT_MODEL_FILE} (cheme layout build)")
    if not targets:
        raise _Refused(f"the {what} stream's other end links no equipment")
    declared = sheet.param(nozzle_param)
    candidates = (
        [f"{sheet.tag}/{declared.value}"]
        if declared
        else sorted(r for r in network.by_ref if r.split("/", 1)[0] == sheet.tag and r != exclude)
    )
    found = []
    for ref in candidates:
        path = network.path(ref, set(targets))
        if path is not None:
            found.append((sum(e.length for e, _ in path[1]), ref, path))
    if not found:
        raise _Refused(
            f"no routed path in {LAYOUT_MODEL_FILE} from a nozzle of {sheet.tag} to "
            f"{' or '.join(targets)}"
        )
    _, ref, (target, steps) = min(found)
    roughness_param = sheet.param("pipe_roughness")
    schedule_param = sheet.param("pipe_schedule")
    schedule = str(schedule_param.value) if schedule_param else "40"
    assumed = schedule_param is None or schedule_param.assumed
    segments, notes, unknown = [], [], []
    tables: dict[str, None] = {}  # the shipped table rows read, as inputs
    tees = network.tees(steps)
    for index, (edge, _) in enumerate(steps):
        pipe = edge.pipe
        dn = float(pipe.get("dn") or 0.0)
        layout_od = float(pipe.get("od") or 0.0)
        sized = hydraulics.inside_diameter(dn, schedule)
        tables[f"table:pipe-sizes/{schedule}/DN{dn:g}"] = None
        if sized is None:
            raise _Refused(
                f"pipe {pipe.get('id')}: no outside diameter or wall thickness of DN {dn:g} "
                f"schedule {schedule} (declare pipe_schedule 40 or 10S, or give the head)"
            )
        inside, od_row, wall = sized
        od = od_row.value
        if roughness_param is not None:
            material, r_assumed = str(roughness_param.value), roughness_param.assumed
        else:
            text = str((pipe.get("class") or {}).get("material") or "")
            if not any(w in text for w in ("CS", "SS", "steel", "Steel")):
                raise _Refused(
                    f"pipe {pipe.get('id')}: class material {text!r} is not steel; declare "
                    "pipe_roughness"
                )
            material, r_assumed = "commercial_steel", True
        rough = hydraulics.roughness(material)
        tables[f"table:roughness/{material}"] = None
        if rough is None:
            raise _Refused(f"pipe_roughness {material!r} is not a row of the roughness table")
        assumed = assumed or r_assumed
        fittings: dict[str, float] = {}
        tee = tees[index]  # the tee where this stretch ends, charged at its velocity
        names = list(edge.fittings) + ([tee] if tee else [])
        for name in names:
            # an unknown fitting too: a K added to the table later would count
            tables[f"table:fittings/{name.removeprefix('?')}"] = None
            if name.startswith("?"):
                unknown.append(name[1:])
                continue
            k = hydraulics.fitting_k(name)
            fittings[name] = fittings.get(name, 0.0) + k.value  # type: ignore[union-attr]
        segments.append(hydraulics.Segment(edge.length, inside.value, rough.value, fittings))
        od_note = (
            f" (the layout model's {layout_od * 1000:g} mm is not the schedule's OD)"
            if layout_od > 0 and abs(layout_od - od) > 5.1e-4  # the model's ODs are to the mm
            else ""
        )
        notes.append(
            f"{pipe.get('id')} DN {dn:g} OD {od * 1000:g} mm ({od_row.source}){od_note}, wall "
            f"{wall.value * 1000:g} mm ({wall.source}), ID {inside.value * 1000:.4g} mm, "
            f"roughness {rough.value * 1000:g} mm ({rough.source}"
            f"{', ASSUMED from the pipe class material' if roughness_param is None else ''})"
            + (f", fittings {', '.join(sorted(fittings))}" if fittings else "")
        )
    loss = hydraulics.line_loss(mass_flow, density, viscosity, segments)
    text = (
        f"{what} line {ref} -> {target}: " + "; ".join(notes) + f"; {loss.describe()}; "
        f"K: {hydraulics._data()['fittings']['source']}"
        + (f"; schedule {schedule} ASSUMED (none declared)" if schedule_param is None else "")
        + (f"; not counted (no K in the table): {', '.join(sorted(unknown))}" if unknown else "")
    )
    return _Line(
        ref,
        target,
        loss,
        text,
        network.nozzles[ref][2],
        network.nozzles[target][2],
        assumed,
        [  # those the model names (a nozzle only at a pipe's end is in its pipe's)
            *dict.fromkeys(
                f"pipe:{edge.pipe['id']}" for edge, _ in steps if edge.pipe.get("id") is not None
            ),
            *(f"nozzle:{n}" for n in dict.fromkeys((ref, target)) if n in network.item_nozzles),
            *tables,
        ],
    )


def _pump(sheet: _Sheet, context: _Context) -> None:
    keys = (
        ("flow_m3_h", "m3/h"),
        ("differential_head_m", "m"),
        ("npsh_available_m", "m"),
        ("shaft_power_kw", "kW"),
    )
    try:
        try:
            node, inlet, outlet = context.one_in_one_out(sheet.tag)
        except _Refused as refusal:
            if sheet.param("suction_from") and sheet.param("discharge_to"):
                _pump_declared(sheet, context)
                return
            if sheet.param("mass_flow_kg_h") is not None:  # meant as a declared pump
                raise _Refused(
                    f"{refusal.reason}; for a pump no stream links declare "
                    "type_specific.suction_from and discharge_to (its end points in the layout "
                    "model)"
                ) from refusal
            raise
        if inlet.mass_flow is None:
            raise _Refused(f"stream {inlet.id}: no flow in case {context.case}")
        if inlet.pressure is None or outlet.pressure is None:
            raise _Refused(f"streams {inlet.id}/{outlet.id}: no absolute pressure")
        given_rho = sheet.param("density_kg_m3")
        if given_rho is not None:
            rho, rho_text, rho_assumed = (
                given_rho.number(),
                f"rho {given_rho.text()}",
                given_rho.assumed,
            )
        else:
            props = context.flash(inlet)
            if props.phase != "liquid" or props.density is None:
                raise _Refused(
                    f"stream {inlet.id} is {props.phase} at the suction: a pump needs liquid",
                    "cheme.datasheet-fill-phase",
                    "warning",
                    "check the suction state (temperature, pressure)",
                )
            rho, rho_assumed = props.density, False
            rho_text = f"rho {rho:.4g} kg/m3 (property adapter, stream {inlet.id})"
    except _Refused as refusal:
        for key, unit in keys:
            sheet.tbd_value(key, unit, refusal)
        return
    m = inlet.mass_flow
    q = m / rho * 3600.0
    sheet.put(
        "flow_m3_h",
        q,
        "m3/h",
        f"Q = m / rho = {m * 3600:.6g} kg/h ({context.where(inlet)}) / {rho:.4g} kg/m3; {rho_text}",
        rho_assumed,
    )
    dp = outlet.pressure - inlet.pressure
    head_parts = [
        f"pressure {dp:.4g} kPa ({outlet.id} {outlet.pressure:.5g} - {inlet.id} "
        f"{inlet.pressure:.5g} kPa(a)) = {sizing.pressure_head(dp, rho):.4g} m"
    ]
    head = sizing.pressure_head(dp, rho)
    assumed = rho_assumed
    suction = discharge = None
    viscosity_text = ""
    mu_assumed = False
    at = sheet.param("stream_pressures_at")
    at_word = str(at.value).strip().lower() if at else "ends"
    at_text, at_assumed = (at.text(), at.assumed) if at else ("", False)
    at_pump = at_word == "pump"
    if at_word not in ("ends", "pump"):
        assumed = True
        head_parts.append(
            f"stream_pressures_at {at_text} is neither ends nor pump: taken as ends (ASSUMED)"
        )
    if at_pump:
        assumed = assumed or at_assumed
        head_parts.append(
            f"the stream pressures are at the pump's nozzles (stream_pressures_at {at_text}): "
            "static head and line losses already in them, not added"
        )
    try:
        if at_pump:
            raise _Refused("")
        given_mu = sheet.param("viscosity_mpa_s")
        if given_mu is not None:
            mu, viscosity_text = given_mu.number() / 1000.0, f"mu {given_mu.text()} mPa s"
            mu_assumed = given_mu.assumed
        else:
            if inlet.temperature is None or inlet.inputs is None:
                raise _Refused(f"stream {inlet.id}: no temperature or composition for viscosity")
            mu, mu_basis = context.call(
                "viscosity",
                context.adapter().liquid_viscosity,
                inlet.temperature,
                inlet.inputs.fractions,
            )
            viscosity_text = f"mu {mu * 1000:.4g} mPa s ASSUMED ({mu_basis})"
            mu_assumed = True
        sources = [t for n in _ends(context, inlet, "from") for t in context.node_tags(n)]
        sinks = [t for n in _ends(context, outlet, "to") for t in context.node_tags(n)]
        sources = [t for t in sources if t != sheet.tag]
        sinks = [t for t in sinks if t != sheet.tag]
        declared_from, declared_to = sheet.param("suction_from"), sheet.param("discharge_to")
        if declared_from is not None:
            sources = [_endpoint(context, str(declared_from.value))]
        if declared_to is not None:
            sinks = [_endpoint(context, str(declared_to.value))]
        suction = _route(sheet, context, "suction_nozzle", sources, None, m, rho, mu, "suction")
        discharge = _route(
            sheet, context, "discharge_nozzle", sinks, suction.nozzle, m, rho, mu, "discharge"
        )
        static = discharge.elevation_target - suction.elevation_target
        head += static + suction.loss.head + discharge.loss.head
        assumed = assumed or mu_assumed or suction.assumed or discharge.assumed
        head_parts += [
            "the stream pressures taken at the source and destination items (stream_pressures_at "
            + (f"{at_text})" if at else "ends, the default)"),
            f"static {static:.4g} m (nozzle {discharge.target} at z "
            f"{discharge.elevation_target:.3f} m - nozzle {suction.target} at z "
            f"{suction.elevation_target:.3f} m, "
            f"{LAYOUT_MODEL_FILE}; liquid levels above the nozzles not counted)",
            f"suction losses {suction.loss.head:.4g} m",
            f"discharge losses {discharge.loss.head:.4g} m",
            f"{viscosity_text}",
            suction.text,
            discharge.text,
        ]
    except _Refused as refusal:
        if not at_pump:
            assumed = True
            head_parts.append(
                "ASSUMED: the stream pressures are at the pump nozzles; static head and line "
                f"losses not included ({refusal.reason})"
            )
    cv = sheet.param("control_valve_dp_kpa")
    if cv is not None:
        head += sizing.pressure_head(cv.number(), rho)
        head_parts.append(f"control valve allowance {cv.text()} kPa")
        assumed = assumed or cv.assumed
    # the routed lines and the nozzle elevations behind the static head and the losses
    routed = [*suction.inputs, *discharge.inputs] if suction and discharge else []
    sheet.put(
        "differential_head_m",
        head,
        "m",
        f"H = {head:.4g} m: " + "; ".join(p for p in head_parts if p) + f"; {rho_text}",
        assumed,
        inputs=routed,
    )
    head_reads = list(sheet.read)
    # NPSH available
    try:
        given_pv = sheet.param("vapour_pressure_kpa")
        if given_pv is not None:
            pv, pv_text, pv_assumed = (
                given_pv.number(),
                f"p_vap {given_pv.text()}",
                given_pv.assumed,
            )
        else:
            if inlet.temperature is None or inlet.inputs is None:
                raise _Refused(f"stream {inlet.id}: no temperature or composition")
            pv = context.call(
                f"vapour pressure of stream {inlet.id}",
                context.adapter().bubble_pressure,
                inlet.temperature,
                inlet.inputs.fractions,
            )
            pv_text = (
                f"p_vap {pv:.5g} kPa(a) (bubble point at {inlet.temperature:.5g} K, "
                "property adapter)"
            )
            pv_assumed = False
        if suction is not None:
            static_s = suction.elevation_target - suction.elevation_pump
            loss = suction.loss.head
            npsh_assumed = pv_assumed or rho_assumed or suction.assumed or mu_assumed
            where = (
                f"static {static_s:.4g} m (nozzle {suction.target} at z "
                f"{suction.elevation_target:.3f} m above suction {suction.nozzle} at z "
                f"{suction.elevation_pump:.3f} m; the liquid level above the nozzle not counted), "
                f"suction losses {loss:.4g} m"
            )
        elif at_pump:
            static_s = loss = 0.0
            npsh_assumed = pv_assumed or rho_assumed or at_assumed
            where = f"the inlet pressure is at the pump suction (stream_pressures_at {at_text})"
        else:
            static_s = loss = 0.0
            npsh_assumed = True
            where = "ASSUMED: the inlet pressure is at the pump suction (no routed suction line)"
        npsh = sizing.npsh_available(inlet.pressure, pv, rho, static_s, loss)
        sheet.put(
            "npsh_available_m",
            npsh,
            "m",
            f"NPSHa = (p_in - p_vap) / (rho g) + static - losses: p_in {inlet.pressure:.5g} kPa(a) "
            f"({context.where(inlet)}), {pv_text}, {rho_text}, {where}",
            npsh_assumed,
            inputs=suction.inputs if suction is not None else None,
            reads=[r for r in sheet.read if r not in _NOT_NPSH],
        )
    except _Refused as refusal:
        sheet.tbd_value("npsh_available_m", "m", refusal)
    try:
        eta = sheet.need("pump_efficiency", "(ASSUMED until the supplier's curve)")
        given_head = sheet.given_number("differential_head_m")
        h, h_text = (given_head[0], given_head[1]) if given_head else (head, f"{head:.4g} m")
        power = sizing.hydraulic_power(m, h) / eta.number()
        sheet.put(
            "shaft_power_kw",
            power,
            "kW",
            f"P = m g H / eta = {m:.4g} kg/s x {G} m/s2 x {h_text} / {eta.text()}",
            True,
            inputs=None if given_head else routed,
            reads=[
                *([] if given_head else head_reads),
                "param:pump_efficiency",
                "datasheet:type_specific.differential_head_m",
            ],
        )
    except _Refused as refusal:
        sheet.tbd_value("shaft_power_kw", "kW", refusal)


def _endpoint(context: _Context, spec: str) -> str:
    """The network label of a declared end point (``TAG``, ``TAG/N``, ``pipe:<id>:<end>``)."""
    spec = spec.strip()
    if not spec.startswith("pipe:"):
        return spec
    network = context.network
    if network is None:
        raise _Refused(f"no {LAYOUT_MODEL_FILE} (cheme layout build)")
    pipe_id, _, end = spec[len("pipe:") :].rpartition(":")
    ref = network.open_end(pipe_id, end)
    if ref is None:
        raise _Refused(f"{spec}: no routed pipe {pipe_id!r} with a {end!r} end in the layout model")
    return ref


def _pump_declared(sheet: _Sheet, context: _Context) -> None:
    """A pump no flowsheet stream links, sized from its declared end points and conditions
    (:func:`chemeascode.domains.equipment.pumps.size_pump`)."""
    from chemeascode.domains.equipment import pumps

    keys = (
        ("flow_m3_h", "m3/h"),
        ("differential_head_m", "m"),
        ("npsh_available_m", "m"),
        ("shaft_power_kw", "kW"),
    )
    used: list[Param] = []

    def need(name: str) -> float:
        found = sheet.need(name, "(a pump no flowsheet stream links)")
        used.append(found)
        return found.number()

    def optional(name: str) -> float | None:
        found = sheet.param(name)
        if found is None:
            return None
        used.append(found)
        return found.number()

    try:
        if context.model is None:
            raise _Refused(f"no {LAYOUT_MODEL_FILE} (cheme layout build)")
        m = need("mass_flow_kg_h") / 3600.0
        rho = need("density_kg_m3")
        mu = need("viscosity_mpa_s") / 1000.0
        p_s, p_d = need("suction_pressure_kpa"), need("discharge_pressure_kpa")
        pv, eta = optional("vapour_pressure_kpa"), optional("pump_efficiency")
        cv = optional("control_valve_dp_kpa") or 0.0
        nozzles = {k: sheet.param(k) for k in ("suction_nozzle", "discharge_nozzle")}
        schedule, rough = sheet.param("pipe_schedule"), sheet.param("pipe_roughness")
        net = pumps.PipeNetwork._of(context.network)  # type: ignore[arg-type]
        duty = pumps.size_pump(
            net,
            sheet.tag,
            suction_from=str(sheet.param("suction_from").value),  # type: ignore[union-attr]
            discharge_to=str(sheet.param("discharge_to").value),  # type: ignore[union-attr]
            mass_flow_kg_s=m,
            density_kg_m3=rho,
            viscosity_pa_s=mu,
            suction_pressure_kpa=p_s,
            discharge_pressure_kpa=p_d,
            vapour_pressure_kpa=pv,
            efficiency=eta,
            allowance_kpa=cv,
            suction_nozzle=str(nozzles["suction_nozzle"].value)
            if nozzles["suction_nozzle"]
            else None,
            discharge_nozzle=str(nozzles["discharge_nozzle"].value)
            if nozzles["discharge_nozzle"]
            else None,
            schedule=str(schedule.value) if schedule else None,
            roughness=str(rough.value) if rough else None,
            inputs_assumed=any(p.assumed for p in (schedule, rough) if p is not None),
        )
    except (pumps.SizingError, _Refused) as failure:
        refusal = failure if isinstance(failure, _Refused) else _Refused(str(failure))
        flow = _declared_flow(sheet)
        for key, unit in keys:
            if key == "flow_m3_h" and flow is not None:
                # the flow needs no routed line: Q = m / rho from the declared values
                sheet.put(key, flow[0], unit, flow[1], flow[2], inputs=[], reads=flow[3])
                continue
            sheet.tbd_value(key, unit, refusal)
        return
    inputs = "; ".join(f"{p.text()}" for p in used)
    assumed = duty.assumed or any(p.assumed for p in used)
    declared = (
        f"declared end points suction_from {sheet.param('suction_from').text()}, "  # type: ignore[union-attr]
        f"discharge_to {sheet.param('discharge_to').text()}"  # type: ignore[union-attr]
    )
    values = {
        "flow_m3_h": duty.flow_m3_h,
        "differential_head_m": duty.differential_head_m,
        "npsh_available_m": duty.npsh_available_m,
        "shaft_power_kw": duty.shaft_power_kw,
    }
    whys = {
        "npsh_available_m": "declare type_specific.vapour_pressure_kpa",
        "shaft_power_kw": "declare type_specific.pump_efficiency (ASSUMED until the supplier's "
        "curve)",
    }
    suction, both = list(duty.suction.inputs), [*duty.suction.inputs, *duty.discharge.inputs]
    flow_reads = ["param:mass_flow_kg_h", "param:density_kg_m3"]
    read = list(sheet.read)
    # what each value read: the routed lines, the table rows and the declared parameters
    depends = {
        "flow_m3_h": ([], flow_reads),
        "differential_head_m": (
            both,
            [r for r in read if r not in ("param:vapour_pressure_kpa", "param:pump_efficiency")],
        ),
        "npsh_available_m": (suction, [r for r in read if r not in _NOT_NPSH]),
        "shaft_power_kw": (both, [r for r in read if r != "param:vapour_pressure_kpa"]),
    }
    for key, unit in keys:
        value = values[key]
        if value is None:
            sheet.tbd_value(key, unit, _Refused(whys[key]))
            continue
        sheet.put(
            key,
            value,
            unit,
            f"{duty.basis[key]}; {declared}; inputs {inputs} (pumps.size_pump)",
            assumed or key == "shaft_power_kw",
            inputs=depends[key][0],
            reads=depends[key][1],
        )


def _declared_flow(sheet: _Sheet) -> tuple[float, str, bool, list[str]] | None:
    """A declared pump's volume flow from its declared mass flow and density: (m3/h, basis,
    assumed, the parameters read); None when either is missing or not a positive number."""
    m, rho = sheet.param("mass_flow_kg_h"), sheet.param("density_kg_m3")
    if m is None or rho is None:
        return None
    try:
        mass, density = m.number(), rho.number()
    except _Refused:
        return None
    if not (mass > 0 and density > 0):
        return None
    return (
        mass / density,
        f"Q = m / rho = {mass:.6g} kg/h / {density:.6g} kg/m3 (declared mass_flow_kg_h "
        f"{m.text()}; density_kg_m3 {rho.text()}); the head, NPSH and power need the routed "
        "lines",
        m.assumed or rho.assumed,
        ["param:mass_flow_kg_h", "param:density_kg_m3"],
    )


def _ends(context: _Context, stream: _Stream, end: str) -> list[str]:
    text = stream.stream.from_ if end == "from" else stream.stream.to
    node = text.split(".", 1)[0]
    if context.process is None:
        return [node]
    # a port delegating to a block: the block and its container count too
    return [node, *context.process.ancestors(node)]


# -- compressors and expanders --------------------------------------------------------------------


def _machine(sheet: _Sheet, context: _Context) -> None:
    keys = [("fluid_power_kw", "kW"), ("shaft_power_kw", "kW")]
    try:
        node, inlet, outlet = context.one_in_one_out(sheet.tag)
        if inlet.mass_flow is None:
            raise _Refused(f"stream {inlet.id}: no flow in case {context.case}")
        if None in (inlet.pressure, outlet.pressure, inlet.temperature):
            raise _Refused(f"streams {inlet.id}/{outlet.id}: pressure or temperature missing")
        ratio = outlet.pressure / inlet.pressure
        compression = ratio >= 1.0
        poly = sheet.param("polytropic_efficiency")
        eta = poly or sheet.need(
            "isentropic_efficiency", "or polytropic_efficiency (ASSUMED until the supplier's)"
        )
        kind = "polytropic" if poly else "isentropic"
        if compression:
            max_ratio = sheet.need("max_stage_pressure_ratio", "to set the number of stages")
            n, stage_ratio = sizing.stages_for(ratio, max_ratio.number())
            stage_basis = (
                f"{n} stage(s) of ratio {stage_ratio:.4g} (overall {ratio:.4g}, max per stage "
                f"{max_ratio.text()})"
            )
        else:
            max_ratio, n, stage_ratio = None, 1, ratio
            stage_basis = f"one expansion stage, ratio {ratio:.4g}"
        ic = sheet.param("intercooler_outlet_temperature_degc")
        t_ic = ic.number() + 273.15 if ic else inlet.temperature
        ic_text = (
            f"intercooled to {ic.text()} degC"
            if ic
            else f"intercooled to the suction temperature {inlet.temperature:.5g} K (ASSUMED: "
            "none declared)"
        ) + (
            ", no intercooler or aftercooler pressure drop (ASSUMED: the stage ratios split "
            f"{outlet.id}'s pressure)"
        )
        stages = _real_gas(sheet, context, inlet, n, stage_ratio, t_ic, eta.number(), kind)
        route = "real gas, property adapter (enthalpy, entropy)"
        route_assumed = False
        if isinstance(stages, _Refused):
            stages, route = _ideal_gas(
                sheet, context, inlet, n, stage_ratio, t_ic, eta.number(), kind, stages
            )
            route_assumed = True
    except _Refused as refusal:
        for key, unit in keys:
            sheet.tbd_value(key, unit, refusal)
        return
    m = inlet.mass_flow
    works = [w for w, _, _ in stages]
    power = abs(m * sum(works))
    assumed = True  # the efficiency is a declared assumption until the supplier's
    basis = (
        f"{kind} efficiency {eta.text()}; {stage_basis}; m {m * 3600:.6g} kg/h "
        f"({context.where(inlet)}), {inlet.pressure:.5g} -> {outlet.pressure:.5g} kPa(a) "
        f"({outlet.id}; the stream pressures taken at the machine's flanges, line losses not "
        f"added), suction {inlet.temperature:.5g} K; {route}"
    )
    if compression and n > 1:
        basis += f"; {ic_text}"
    sheet.put(
        "fluid_power_kw",
        power,
        "kW",
        f"P = m sum(w) = {power:.4g} kW, stage work {', '.join(f'{w:.4g}' for w in works)} kJ/kg; "
        + basis,
        assumed or route_assumed,
    )
    if compression:
        stage_assumed = bool(max_ratio and max_ratio.assumed)
        stage_reads = ["param:max_stage_pressure_ratio"]  # not the efficiency
        sheet.put("number_of_stages", n, "", stage_basis, stage_assumed, reads=stage_reads)
        sheet.put(
            "stage_pressure_ratio", stage_ratio, "", stage_basis, stage_assumed, reads=stage_reads
        )
    fluid_reads = list(sheet.read)
    outlet_t = stages[-1][1]
    sheet.put("discharge_temperature_k", outlet_t, "K", f"last stage outlet; {basis}", True)
    if compression and n > 1:
        duties = [abs(m * d) for _, _, d in stages[:-1]]
        sheet.put(
            "intercooler_duties_kw",
            duties,
            "kW",
            f"m (h_stage_out - h_intercooled) per intercooler; {ic_text}; {basis}",
            True,
        )
    else:
        sheet.drop("intercooler_duties_kw")
    try:
        mech = sheet.need("mechanical_efficiency", "to give the shaft power")
        given_power = sheet.given_number("fluid_power_kw")
        fp, fp_text = (
            (given_power[0], given_power[1]) if given_power else (power, f"{power:.4g} kW")
        )
        shaft = fp / mech.number() if compression else fp * mech.number()
        sheet.put(
            "shaft_power_kw",
            shaft,
            "kW",
            f"fluid power {fp_text} {'/' if compression else 'x'} {mech.text()}",
            True,
            reads=[
                *([] if given_power else fluid_reads),
                "param:mechanical_efficiency",
                "datasheet:type_specific.fluid_power_kw",
            ],
        )
    except _Refused as refusal:
        sheet.tbd_value("shaft_power_kw", "kW", refusal)


def _real_gas(
    sheet: _Sheet,
    context: _Context,
    inlet: _Stream,
    n: int,
    stage_ratio: float,
    t_ic: float,
    eta: float,
    kind: str,
) -> list[tuple[float, float, float]] | _Refused:
    """Stages through the adapter: ``[(work kJ/kg, outlet T K, after-cooler duty kJ/kg)]``, or
    the refusal (the ideal-gas route takes over)."""
    from chemeascode.domains.process.props import Inputs

    try:
        adapter = context.adapter()
        if inlet.inputs is None:
            raise _Refused(f"stream {inlet.id}: {inlet.why}")
        x = inlet.inputs.fractions
        t, p = inlet.inputs.temperature, inlet.inputs.pressure
        mw = context.call("suction", adapter.flash, inlet.inputs).molar_mass
        out = []
        for i in range(n):
            h1 = context.call("stage inlet", adapter.flash, Inputs(t, p, x)).enthalpy
            p2 = p * stage_ratio
            if kind == "isentropic":
                s1 = context.call("stage inlet", adapter.entropy, Inputs(t, p, x))
                h2s = context.call("isentropic outlet", adapter.flash_ps, p2, s1, x).enthalpy
                dh = (h2s - h1) / eta if p2 >= p else (h2s - h1) * eta
                h2 = h1 + dh
            else:  # polytropic: small isentropic steps, each at the polytropic efficiency
                h, tp, pp = h1, t, p
                step = stage_ratio ** (1.0 / POLYTROPIC_STEPS)
                for _ in range(POLYTROPIC_STEPS):
                    s = context.call("polytropic step", adapter.entropy, Inputs(tp, pp, x))
                    hs = context.call("polytropic step", adapter.flash_ps, pp * step, s, x).enthalpy
                    dh = (hs - h) / eta if step >= 1 else (hs - h) * eta
                    h += dh
                    pp *= step
                    tp = _t_of(context, adapter, pp, h, x)
                h2 = h
            t2 = _t_of(context, adapter, p2, h2, x)
            cool = 0.0
            if i < n - 1:
                h_ic = context.call("intercooled", adapter.flash, Inputs(t_ic, p2, x)).enthalpy
                cool = (h2 - h_ic) / mw
                t = t_ic
            out.append(((h2 - h1) / mw, t2, cool))
            p = p2
        return out
    except _Refused as refusal:
        return refusal


def _t_of(context: _Context, adapter: Any, p: float, h: float, x: dict[str, float]) -> float:
    from chemeascode.domains.process.props import Unsupported

    try:
        state = adapter._raw(x, P=p * 1000.0, H=h)
    except Unsupported as failure:
        raise _Refused(str(failure)) from failure
    context.call("stage outlet", adapter._checked, float(state.T), p, x)
    return float(state.T)


def _ideal_gas(
    sheet: _Sheet,
    context: _Context,
    inlet: _Stream,
    n: int,
    stage_ratio: float,
    t_ic: float,
    eta: float,
    kind: str,
    why: _Refused,
) -> tuple[list[tuple[float, float, float]], str]:
    k_param = sheet.param("heat_capacity_ratio")
    if k_param is not None:
        k, k_text = k_param.number(), f"Cp/Cv {k_param.text()}"
    else:
        if inlet.inputs is None:
            raise _Refused(f"real gas: {why.reason}; ideal gas: stream {inlet.id}: {inlet.why}")
        try:
            k = context.call(
                "Cp/Cv at the suction", context.adapter().heat_capacity_ratio, inlet.inputs
            )
        except _Refused as refusal:
            raise _Refused(
                f"real gas: {why.reason}; ideal gas: {refusal.reason}; declare heat_capacity_ratio",
                why.rule,
                why.level,
                why.hint,
            ) from refusal
        k_text = f"Cp/Cv {k:.4g} at the suction (property adapter)"
    mw = context.molar_mass(inlet)
    t = inlet.temperature
    out = []
    cp = sizing.R * k / ((k - 1.0) * mw)
    for i in range(n):
        stage = sizing.ideal_gas_stage(t, stage_ratio, k, mw, eta, kind)
        cool = cp * (stage.outlet_temperature - t_ic) if i < n - 1 else 0.0
        out.append((stage.work, stage.outlet_temperature, cool))
        t = t_ic
    route = (
        f"ideal gas, constant {k_text}, M {mw:.4g} kg/kmol (ASSUMED: Z = 1; the real-gas "
        f"route was refused: {why.reason})"
    )
    return out, route


# -- columns --------------------------------------------------------------------------------------


def _condenser(sheet: _Sheet, context: _Context, step: str) -> tuple[str, str, list[str], bool]:
    """The column's condenser type: ``type_specific.condenser_type`` (or ``--param``), else the
    ``condenser`` the linked *step*'s unit spec in ``process/simulation.yaml`` declares, else a
    total condenser, assumed. The type, its basis for the source, the inputs it was read from
    (for the fingerprint) and whether it is assumed."""
    from chemeascode.domains.process.simulation import SIMULATION_FILE

    declared = sheet.param("condenser_type")
    if declared is not None:
        kind = str(declared.value).strip().lower()
        if kind not in CONDENSERS:
            raise _Refused(
                f"type_specific.condenser_type {declared.value!r} is not one of "
                f"{', '.join(CONDENSERS)}"
            )
        where, assumed = declared.source, declared.assumed
        given = declared.source.startswith(FILL_MARK)  # --param: not in the sheet
        inputs = [] if given else ["datasheet:type_specific.condenser_type"]
    elif (kind := _declared_condenser(context.specs.get(step))) is not None:
        where, assumed = f"{SIMULATION_FILE} specs.{step}.condenser", False
        inputs = [f"condenser:{step}"]
    else:
        unread = f"; {SIMULATION_FILE} does not load" if context.specs_unread else ""
        return (
            "total",
            "a total condenser (not a stage) ASSUMED: no condenser type declared "
            f"(type_specific.condenser_type, or condenser of specs.{step} in {SIMULATION_FILE}"
            f"{unread})",
            [],
            True,
        )
    text = "no condenser" if kind == "none" else f"a {kind} condenser"
    return kind, f"{text} ({'ASSUMED: ' if assumed else ''}{where})", inputs, assumed


def _column(sheet: _Sheet, context: _Context) -> None:
    from chemeascode.domains.process.props import Inputs
    from chemeascode.domains.process.separations import shortcut

    keys = [
        ("minimum_stages", ""),
        ("minimum_reflux_ratio", ""),
        ("theoretical_stages", ""),
        ("number_of_stages", ""),
    ]
    try:
        nodes = context.linked_nodes(sheet.tag)
        if not nodes:
            raise _Refused(
                f"no flowsheet node links {sheet.tag} (links: in process/flowsheet.yaml)"
            )
        chosen = None
        for node in nodes:
            ins, outs = context.streams(node, "in"), context.streams(node, "out")
            if len(ins) == 1 and len(outs) == 2:
                chosen, step = (ins[0], outs), node
        if chosen is None:
            raise _Refused(
                "the shortcut method needs a linked node with one feed and two products "
                f"({', '.join(nodes)})"
            )
        feed, products = chosen
        for s in (feed, *products):
            if s.inputs is None:
                raise _Refused(f"stream {s.id}: {s.why}")
        z = feed.inputs.fractions
        lk_p, hk_p = sheet.param("light_key"), sheet.param("heavy_key")
        comps = sorted(z)
        if lk_p and hk_p:
            lk, hk = str(lk_p.value), str(hk_p.value)
        elif len(comps) == 2:
            lk = hk = ""
        else:
            raise _Refused(
                f"declare type_specific.light_key and heavy_key (feed {feed.id} has "
                f"{len(comps)} components: {', '.join(comps)})"
            )
        adapter = context.adapter()
        # distillate: the product richer in the light key; volatilities at its dew point and at
        # the bottoms' bubble point, geometric mean
        if not lk:
            temperature, kv = context.call(
                "feed bubble point", adapter.k_values, feed.inputs.pressure, z
            )
            lk, hk = sorted(comps, key=lambda c: -kv[c])
        for name in (lk, hk):
            if name not in z:
                raise _Refused(f"key {name} is not in feed {feed.id}")
        top, bottom = sorted(products, key=lambda s: -s.inputs.fractions.get(lk, 0.0))
        xd, xb = dict(top.inputs.fractions), dict(bottom.inputs.fractions)
        for name in z:
            xd.setdefault(name, 0.0)
            xb.setdefault(name, 0.0)
        t_top, k_top = context.call(
            f"dew point of {top.id}", adapter.k_values, top.inputs.pressure, xd, 1.0
        )
        t_bot, k_bot = context.call(
            f"bubble point of {bottom.id}", adapter.k_values, bottom.inputs.pressure, xb, 0.0
        )
        alphas = {c: math.sqrt((k_top[c] / k_top[hk]) * (k_bot[c] / k_bot[hk])) for c in z}
        # feed quality q = (H_dew - H_F) / (H_dew - H_bubble) at the feed pressure
        hf = context.flash(feed).enthalpy
        p = feed.inputs.pressure
        t_b, _ = context.call("feed bubble point", adapter.k_values, p, z, 0.0)
        t_d, _ = context.call("feed dew point", adapter.k_values, p, z, 1.0)
        h_b = context.call("feed bubble point", adapter.flash, Inputs(t_b, p, z)).enthalpy
        h_d = context.call("feed dew point", adapter.flash, Inputs(t_d, p, z)).enthalpy
        q = (h_d - hf) / (h_d - h_b)
        try:
            nmin = shortcut.fenske(xd[lk], xd[hk], xb[lk], xb[hk], alphas[lk] / alphas[hk])
            theta = shortcut.underwood_theta(alphas, z, q, lk, hk)
            rmin = shortcut.underwood_min_reflux(alphas, xd, theta)
        except ValueError as failure:
            raise _Refused(str(failure)) from failure
        inputs = (
            f"keys {lk}/{hk} ({'declared' if lk_p else 'binary: the more volatile is light'}), "
            f"feed {feed.id} q {q:.4g} (enthalpy at {p:.5g} kPa(a)), distillate {top.id}, "
            f"bottoms {bottom.id} (process/flowsheet.yaml, case {context.case}); "
            f"alpha_{lk}/{hk} {alphas[lk] / alphas[hk]:.4g}: geometric mean of the top "
            f"(dew point {t_top:.4g} K) and bottom (bubble point {t_bot:.4g} K), property adapter; "
            f"{shortcut.SOURCES}"
        )
        sheet.put("minimum_stages", nmin, "", f"Fenske Nmin; {inputs}", False)
        sheet.put(
            "minimum_reflux_ratio", rmin, "", f"Underwood, theta {theta:.5g}; {inputs}", False
        )
    except _Refused as refusal:
        for key, unit in keys:
            sheet.tbd_value(key, unit, refusal)
        return
    try:
        given_r = sheet.param("reflux_ratio")
        if given_r is not None:
            r, r_text, r_assumed = given_r.number(), f"R {given_r.text()}", given_r.assumed
        else:
            factor = sheet.need("reflux_ratio_factor", "or reflux_ratio")
            r = factor.number() * rmin
            r_text, r_assumed = f"R = {factor.text()} x Rmin {rmin:.4g}", factor.assumed
        try:
            n = shortcut.gilliland(r, rmin, nmin)
        except ValueError as failure:
            raise _Refused(str(failure)) from failure
        sheet.put("reflux_ratio", r, "", f"{r_text}", r_assumed)
        sheet.put(
            "theoretical_stages",
            n,
            "",
            f"Gilliland (Molokanov) at {r_text}, Nmin {nmin:.4g}; theoretical stages "
            f"including the reboiler; {inputs}",
            r_assumed,
        )
    except _Refused as refusal:
        for key, unit in keys[2:]:
            sheet.tbd_value(key, unit, refusal)
        n = None
    try:
        if n is None:
            raise _Refused("needs the theoretical stages")
        eff = sheet.need("tray_efficiency", "to turn theoretical stages into trays")
        condenser, condenser_basis, condenser_inputs, condenser_assumed = _condenser(
            sheet, context, step
        )
        # the partial reboiler is an equilibrium stage of the count, not a tray; so is a
        # partial condenser (a total condenser returns all its vapour as liquid: no stage)
        stages = "1 for the reboiler"
        if condenser == "partial":
            stages = "2 for the reboiler and the partial condenser"
        deducted = 2.0 if condenser == "partial" else 1.0
        trays = math.ceil(max(n - deducted, 0.0) / eff.number() - 1e-9)
        sheet.put(
            "number_of_stages",
            trays,
            "",
            f"trays = ceil((theoretical stages {n:.4g} - {stages}, equilibrium stages but not "
            f"trays) / {eff.text()}); {condenser_basis}",
            condenser_assumed or eff.assumed or r_assumed,
            inputs=condenser_inputs or None,
        )
    except _Refused as refusal:
        sheet.tbd_value("number_of_stages", "", refusal)
    sheet.tbd_value(
        "flooding_diameter_m",
        "m",
        _Refused(
            "no flooding correlation in cheme-as-code is cleanly sourced: take the diameter from a "
            "tray or packing supplier's hydraulic rating"
        ),
        add=True,
    )


# -- vessels --------------------------------------------------------------------------------------


def _number(entry: Any) -> float | None:
    value = entry.get("value") if isinstance(entry, dict) else entry
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


#: The dimensions a vessel's volume may be read from (:func:`_shell_volume`).
SHELL_DIMENSIONS = (
    "orientation",
    "inside_diameter",
    "outside_diameter",
    "tangent_length",
    "overall_length",
    "overall_height",
)


def _draft_volume(entry: Any) -> bool:
    """A vessel volume the draft took from the list's dimensions (:data:`DRAFT_VOLUME`, after
    the equipment list's path)."""
    source = str(entry.get("source") or "") if isinstance(entry, dict) else ""
    return source.startswith(f"{LIST_FILES['equipment']} {DRAFT_VOLUME}")


def _shell_volume(data: dict[str, Any]) -> tuple[float, str, list[str]] | None:
    """A vessel's volume ``pi/4 D^2 L`` from the datasheet's dimensions: the typed
    ``dimensions`` first (the inside diameter, else the outside; the tangent length, else the
    overall length of a horizontal item or the overall height), else the legacy
    ``type_specific`` ``diameter_m`` with ``length_m`` or ``height_m``. The volume, its basis
    and every field it may be read from (``section.key``: a field added later that would take
    priority changes its fingerprint too); None without a diameter and a length."""
    from chemeascode.domains.equipment.outline import number

    dims = data.get("dimensions") if isinstance(data.get("dimensions"), dict) else {}
    diameter = next(
        ((k, v) for k in ("inside_diameter", "outside_diameter") if (v := number(dims.get(k)))),
        None,
    )
    horizontal = dims.get("orientation") == "horizontal" or (
        dims.get("orientation") is None and number(dims.get("overall_length"))
    )
    lengths = ("tangent_length", "overall_length" if horizontal else "overall_height")
    length = next(((k, v) for k in lengths if (v := number(dims.get(k)))), None)
    candidates = [
        *(f"dimensions.{k}" for k in SHELL_DIMENSIONS),
        *(f"type_specific.{k}" for k in ("diameter_m", "length_m", "height_m")),
    ]
    if diameter and length:
        (d_key, d), (l_key, size) = diameter, length
        if l_key == "tangent_length":
            bound = "the cylindrical shell between the tangent lines, heads not included"
            if d_key == "outside_diameter":
                bound += "; over the outside diameter: an upper bound of the shell"
        else:
            ends = "heads" if horizontal else "heads and skirt"
            bound = f"over the {l_key.replace('_', ' ')}, {ends} not separated: an upper bound"
        basis = (
            f"pi/4 D^2 L, D {d:g} m (dimensions.{d_key}), L {size:g} m (dimensions.{l_key}); "
            + bound
        )
        return sizing.cylinder_volume(d, size), basis, candidates
    spec = data.get("type_specific") if isinstance(data.get("type_specific"), dict) else {}
    d = _number(spec.get("diameter_m"))
    along = "length" if _number(spec.get("length_m")) else "height"
    length_m = _number(spec.get(f"{along}_m"))
    if not d or not length_m:
        return None
    basis = (
        f"pi/4 D^2 x {along}, D {d:g} m, {along} {length_m:g} m (type_specific dimensions; "
        "heads and skirt not separated: an upper bound)"
    )
    return sizing.cylinder_volume(d, length_m), basis, candidates


def _vessel(sheet: _Sheet, context: _Context, rule: Any) -> None:
    sheet.read.clear()
    spec = sheet.specific
    current = spec.get("volume_m3")
    # an earlier fill's or the draft's volume too: the dimensions may have changed
    if fillable(spec, "volume_m3") or _draft_volume(current):
        found = _shell_volume(sheet.data)
        if found is not None:
            volume, basis, read = found
            # from the dimensions alone: not from the streams
            inputs = [f"datasheet:{key}" for key in read]
            sheet.put(
                "volume_m3", volume, "m3", basis, True, replace=True, inputs=inputs, streams=False
            )
        elif _ours(current):
            sheet.tbd_value(
                "volume_m3",
                "m3",
                _Refused(
                    "no diameter with a tangent length, overall length or height in dimensions "
                    "(or diameter_m with length_m or height_m)"
                ),
            )
    if rule is None:
        return
    try:
        volume = _number(spec.get("volume_m3"))
        if not volume:
            raise _Refused("no volume_m3")
        nodes = context.linked_nodes(sheet.tag)
        liquid = []
        given_rho = sheet.param("density_kg_m3")
        for node in nodes:
            for s in context.streams(node, "out"):
                state = s.stream.state.get(context.case)
                phase = state.phase.value if state is not None and state.phase else None
                props = None
                if phase is None:
                    props = context.flash(s)
                    phase = props.phase
                if phase != "liquid":
                    continue
                if given_rho is not None:
                    density = given_rho.number()
                else:
                    density = (props or context.flash(s)).density
                if s.mass_flow is None or not density:
                    raise _Refused(f"stream {s.id}: no flow or density")
                liquid.append((s, s.mass_flow / density * 3600.0))
        if not liquid:
            raise _Refused(f"no liquid outlet stream of a node linked to {sheet.tag}")
        flow = sum(q for _, q in liquid)
        held = volume * rule.volume_fraction
        minutes = sizing.residence_time_min(held, flow)
        source = (
            f"t = V f / Q = {volume:.4g} m3 x {rule.volume_fraction:g} / {flow:.4g} m3/h "
            f"(liquid outlets {', '.join(s.id for s, _ in liquid)}, process/flowsheet.yaml case "
            f"{context.case}, density "
            f"{given_rho.text() + ' kg/m3' if given_rho else 'by the property adapter'}); "
            f"required {rule.minutes:g} min (process/design-basis.yaml "
            f"residence_times{': ' + rule.source if rule.source else ''})"
        )
        inputs = [f"residence_time:{sheet.tag}", "datasheet:type_specific.volume_m3"]
        sheet.put("residence_time_min", minutes, "min", source, True, inputs=inputs)
        if minutes < rule.minutes:
            sheet.findings.append(
                Finding(
                    sheet.name,
                    "warning",
                    "cheme.datasheet-residence-time",
                    f"{sheet.tag}: residence time {minutes:.3g} min, the design basis asks for "
                    f"{rule.minutes:g} min",
                    ids=[sheet.tag],
                    hint="a larger vessel, or a design basis that allows less",
                    key=f"{sheet.tag}/residence_time_min",
                )
            )
    except _Refused as refusal:
        sheet.tbd_value("residence_time_min", "min", refusal)


def _reactor(sheet: _Sheet, context: _Context) -> None:
    from chemeascode.domains.process.fixed_bed import BedError, solve_node
    from chemeascode.domains.process.reactors import reactor_entry

    process = context.process
    keys = ("catalyst_mass_kg", "catalyst_volume_m3", "volume_m3", "pressure_drop_kpa")
    units = ("kg", "m3", "m3", "kPa")
    nodes = [n for n in context.linked_nodes(sheet.tag) if process and process.reactive(n)]
    if process is None or len(nodes) != 1:
        why = _Refused(
            "no reactor step linked to " + sheet.tag
            if not nodes
            else f"several reactor steps linked to {sheet.tag}: {', '.join(nodes)}"
        )
        for key, unit in zip(keys, units, strict=True):
            sheet.tbd_value(key, unit, why)
        sheet.tbd_value("duty_kw", "kW", why)
        return
    node_id = nodes[0]
    node = process.nodes[node_id]
    case = context.case or process.flowsheet.default_case()
    inlets = [s.stream for s in context.streams(node_id, "in")]
    if getattr(node, "reactor", None) in ("cstr", "batch", "semibatch"):
        _stirred_reactor(sheet, process, node, node_id, inlets, case)
        return
    try:
        if getattr(node, "reactor", None) == "pfr":
            if len(inlets) != 1:
                raise _Refused(f"{node_id}: a fixed bed takes one inlet stream")
            try:
                bed, _ = solve_node(process, node, inlets[0], case)
            except BedError as failure:
                raise _Refused(f"{node_id}: {failure}") from failure
            where = f"the bed of {node_id} (process/flowsheet.yaml, case {case})"
            assumed = node.bed.provenance == "assumed"
            # the catalyst's densities and particles size the bed
            inputs = [f"catalyst:{node.catalyst}"] if getattr(node, "catalyst", None) else []
            sheet.put("catalyst_mass_kg", bed.catalyst_mass, "kg", where, assumed, inputs=inputs)
            sheet.put(
                "catalyst_volume_m3", bed.catalyst_volume, "m3", where, assumed, inputs=inputs
            )
            sheet.put(
                "pressure_drop_kpa",
                bed.pressure_drop,
                "kPa",
                f"Ergun along {where}" + (f" ({'; '.join(bed.notes)})" if bed.notes else ""),
                True,
                inputs=inputs,
            )
            volume, volume_source = bed.catalyst_volume, where
        else:
            volume, volume_source = _bed_from_space_velocity(sheet, context, node, inlets, case)
            inputs = [f"catalyst:{node.catalyst}"]
        current = sheet.specific.get("volume_m3")
        source = current.get("source") if isinstance(current, dict) else ""
        if current is None or _is_tbd(current) or BED_VOLUME in str(source):
            sheet.put(
                "volume_m3",
                volume,
                "m3",
                f"{BED_VOLUME} ({volume_source}); heads, distributors and internals not "
                "included: a lower bound",
                True,
                inputs=inputs,
            )
        sheet.bed = (volume, volume_source)
    except _Refused as refusal:
        for key, unit in zip(keys, units, strict=True):
            sheet.tbd_value(key, unit, refusal, add=key != "volume_m3")
    entry = reactor_entry(process, node_id, case, with_bed=False)
    if entry["duty_kW"] is not None:
        sheet.put(
            "duty_kw",
            entry["duty_kW"],
            "kW",
            f"H(out) - H(in) of {node_id}, ideal gas on the elements basis (cheme process "
            f"reactors, case {case}): positive is heat added"
            + "".join(f"; {note}" for note in entry["duty_assumptions"]),
            True,
        )
    else:
        sheet.tbd_value(
            "duty_kw", "kW", _Refused("; ".join(entry["missing"]) or "no duty"), add=True
        )


def _recipe_vessel(process: Any, node_id: str, case: str) -> Any:
    """The vessel process/recipe.yaml sizes for batch step *node_id*, or None."""
    from chemeascode.domains.process.recipe import batch_vessel, evaluate, load_recipe

    recipe, doc, _ = load_recipe(process.root)
    if recipe is None:
        return None
    return batch_vessel(process, recipe, evaluate(process, recipe, doc, case), node_id)


def _stirred_reactor(
    sheet: _Sheet, process: Any, node: Any, node_id: str, inlets: list[Any], case: str
) -> None:
    """A stirred tank's working volume (all tanks of the series, a lower bound: no freeboard)
    and its duty, from :func:`.process.stirred_tank.solve_node`; a batch's volume is left to
    its batch size and cycle (TBD), its duty too (it varies over the batch)."""
    from chemeascode.domains.process.stirred_tank import TankError, solve_node

    for key in ("catalyst_mass_kg", "catalyst_volume_m3", "pressure_drop_kpa"):
        sheet.tbd_value(
            key,
            {"catalyst_mass_kg": "kg", "pressure_drop_kpa": "kPa"}.get(key, "m3"),
            _Refused(f"{node_id} is a {node.reactor}, not a bed"),
        )
    if node.reactor in ("batch", "semibatch"):
        why = _Refused(
            f"{node_id} is a {node.reactor}: its volume follows the batch size and cycle, and "
            "its duty varies over the batch (cheme process reactors gives the heat released)"
        )
        vessel = _recipe_vessel(process, node_id, case)
        if vessel is not None:
            sheet.put(
                "volume_m3",
                vessel.volume,
                "m3",
                f"the vessel of {vessel.procedure} in process/recipe.yaml (cheme process "
                f"recipe): {vessel.working_volume:.4g} m3 of batch, {vessel.fill:.0%} full",
                True,
                inputs=[f"recipe:{vessel.procedure}"],
            )
        else:
            sheet.tbd_value("volume_m3", "m3", why, add=True)
        if vessel is not None and vessel.peak_duty is not None:
            sheet.put(
                "duty_kw",
                -vessel.peak_duty,
                "kW",
                f"the peak duty to remove from one batch of {vessel.procedure} "
                "(process/recipe.yaml, cheme process recipe): negative is heat removed",
                True,
                inputs=[f"recipe:{vessel.procedure}"],
            )
        else:
            sheet.tbd_value("duty_kw", "kW", why, add=True)
        return
    try:
        if len(inlets) != 1:
            raise _Refused(f"{node_id}: a tank takes one inlet stream")
        try:
            tank, _ = solve_node(process, node, inlets[0], case)
        except TankError as failure:
            raise _Refused(f"{node_id}: {failure}") from failure
    except _Refused as refusal:
        sheet.tbd_value("volume_m3", "m3", refusal, add=True)
        sheet.tbd_value("duty_kw", "kW", refusal, add=True)
        return
    count = node.tank.count
    where = f"the tank{'s' if count > 1 else ''} of {node_id} (process/flowsheet.yaml, case {case})"
    assumed = node.tank.provenance == "assumed"
    sheet.put(
        "volume_m3",
        (tank.volume or 0.0) * count,
        "m3",
        f"working volume of {where}"
        + (f", {count} tanks together" if count > 1 else "")
        + "; freeboard, heads and internals not included: a lower bound",
        assumed,
    )
    if tank.duty is not None:
        sheet.put(
            "duty_kw", tank.duty, "kW", f"H(out) - H(in) of {where}: positive is heat added", True
        )
    else:
        sheet.tbd_value("duty_kw", "kW", _Refused("; ".join(tank.notes) or "no duty"), add=True)


#: How the reactor fill marks a vessel volume that is only its bed's.
BED_VOLUME = "the catalyst bed's volume"


def _bed_fits(sheet: _Sheet) -> None:
    """A warning when the datasheet's vessel volume (from its dimensions or given) is less
    than the bed the fill sized (compared unrounded; not the bed's own copy)."""
    found = getattr(sheet, "bed", None)
    entry = sheet.specific.get("volume_m3")
    source = entry.get("source") if isinstance(entry, dict) else ""
    if found is None or BED_VOLUME in str(source):
        return
    volume, volume_source = found
    held = _number(entry)
    if held is not None and held < volume * (1 - 1e-3):
        sheet.findings.append(
            Finding(
                sheet.name,
                "warning",
                "cheme.datasheet-reactor-volume",
                f"{sheet.tag}: vessel volume {held:.4g} m3 is less than its catalyst bed "
                f"({volume:.4g} m3, {volume_source})",
                ids=[sheet.tag],
                hint="a larger vessel, or a smaller bed",
                key=f"{sheet.tag}/volume_m3",
            )
        )


def _bed_from_space_velocity(
    sheet: _Sheet, context: _Context, node: Any, inlets: list[Any], case: str
) -> tuple[float, str]:
    """The bed volume (m3) from the catalyst's space velocity and the feed, and its basis;
    the catalyst mass too where the catalyst gives its bulk density."""
    from chemeascode.domains.process.model import GAS_CONSTANT, stream_flows

    process = context.process
    catalysts = process.catalysts.by_id() if process.catalysts else {}
    catalyst = catalysts.get(getattr(node, "catalyst", None) or "")
    if catalyst is None or catalyst.space_velocity is None:
        raise _Refused(f"{node.id}: no bed and no catalyst space velocity to size it from")
    sv = catalyst.space_velocity
    middle = sum(sv.range) / 2
    flows = [stream_flows(process, s, case) for s in inlets]
    if sv.basis == "WHSV":
        mass_flow = sum(f.total or 0.0 for f in flows)
        if not mass_flow or any(f.total is None for f in flows):
            raise _Refused(f"{node.id}: no feed flow for the WHSV")
        mass = mass_flow / middle
        bulk = getattr(catalyst.physical, "bulk_density", None)
        if not bulk:
            raise _Refused(
                f"catalyst {catalyst.id}: no bulk density to turn the WHSV mass into a volume"
            )
        volume = mass / bulk
        basis = (
            f"WHSV {middle:g} 1/h (middle of catalyst {catalyst.id}'s range), "
            f"{mass_flow:.6g} kg/h fed"
        )
    else:
        if sv.basis == "LHSV":
            raise _Refused(f"{node.id}: LHSV needs the liquid feed volume; give the bed instead")
        comps = process.components()
        moles = water = 0.0
        waters: set[str] = set()
        for f in flows:
            if f.components is None:
                raise _Refused(f"{node.id}: no feed composition for the GHSV")
            for n, kg in f.components.items():
                mw = getattr(comps.get(n), "molar_mass", None)
                if kg and not mw:
                    raise _Refused(f"{node.id}: no molar_mass of {n} for the GHSV")
                if sv.gas == "dry" and _is_water(comps.get(n), n):
                    waters.add(n)
                    water += kg / mw if kg else 0.0
                    continue
                moles += kg / mw if kg else 0.0
        nc = process.flowsheet.units.normal_conditions
        t_n, p_n = (nc.temperature, nc.pressure) if nc else (273.15, 101.325)
        normal = moles * GAS_CONSTANT * t_n / p_n  # Nm3/h
        volume = normal / middle
        if sv.gas == "dry":
            gas = (
                f"dry gas ({', '.join(sorted(waters))} {water:.6g} kmol/h left out)"
                if waters
                else "dry gas (no water, CAS 7732-18-5 or H2O, in the feed)"
            )
        else:
            gas = "wet gas (water vapour counted; the catalyst states no dry basis)"
        basis = (
            f"GHSV {middle:g} 1/h (middle of catalyst {catalyst.id}'s range), {normal:.6g} Nm3/h "
            f"of {gas} fed at {t_n:g} K and {p_n:g} kPa"
        )
        mass = None
        bulk = getattr(catalyst.physical, "bulk_density", None)
        if bulk:
            mass = volume * bulk
    inputs = [f"catalyst:{catalyst.id}"]
    sheet.put("catalyst_volume_m3", volume, "m3", basis, True, inputs=inputs)
    if mass is not None:
        sheet.put("catalyst_mass_kg", mass, "kg", basis + ", bulk density", True, inputs=inputs)
    return volume, basis


def _is_water(component: Any, name: str) -> bool:
    """Whether a feed component is water: by its CAS number or formula, else its id."""
    cas = str(getattr(component, "cas", "") or "").strip()
    formula = str(getattr(component, "formula", "") or "").replace(" ", "")
    return cas == "7732-18-5" or formula == "H2O" or name.strip().lower() in ("h2o", "water")


HANDLERS = {
    "reactor": _reactor,
    "exchanger": _exchanger,
    "heater": _heater,
    "pump": _pump,
    "compressor": _machine,
    "turbine": _machine,
    "column": _column,
}
